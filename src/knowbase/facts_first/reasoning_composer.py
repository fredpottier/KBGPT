"""
OSMOSIS V4.1 — Constrained Reasoning Composer (CH-47.2).

Composer agentic CONTRAINT (Qwen2.5-72B-Instruct) qui prend un facts_first enrichi
de relational_facts et produit une réponse user-facing AVEC une `reasoning_chain`
typée et tracée. Cite obligatoirement chaque step par evidence_ids ou relation_id.

Architecture (cf ADR §10.4) :
  Structurer → atomic_facts (V4 actuel)
  RelationalStructurer (CH-47.1) → atomic_facts + relational_facts + reasoning_graph
        ↓
  ReasoningComposer (CH-47.2)  ← CE MODULE
        ↓
  Channel 2 NLI (CH-47.3)

Charte (ADR §10.5) :
  - Anti-LLM-libre : reasoning_steps tracés par construction
  - Citations forcées : every step MUST cite evidence_ids OR relation_id
  - Anti-hallucination : pas d'introduction de connaissance externe
  - Inference_strength obligatoire (direct | probable | speculative)
  - Logique d'abstention raisonnée (pas ABSTAIN brutal V4)

Contrairement aux Composer V4 actuels (presentation-only Gemma-12B), ce Composer
peut SYNTHÉTISER au-delà des facts atomiques, mais DANS LES LIMITES de evidences
et relations fournies.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from knowbase.runtime_v3.llm_client import RuntimeLLMClient, get_runtime_llm_client

logger = logging.getLogger(__name__)


REASONING_STEP_TYPES = (
    "evidence_identification",
    "causal_inference",
    "purpose_synthesis",
    "distinction",
    "conditional_projection",
    "hypothetical_projection",
    "composition",
)

INFERENCE_STRENGTHS = ("direct", "probable", "speculative")


# Override modèle via env. Default Qwen2.5-72B (ADR §10.4 décidé).
REASONING_COMPOSER_MODEL_OVERRIDE = os.getenv(
    "REASONING_COMPOSER_MODEL", "Qwen/Qwen2.5-72B-Instruct"
)


SYSTEM_PROMPT = """You are a Constrained Reasoning Composer. Your task is to generate a structured answer to a user question using ONLY the provided atomic_facts and relational_facts.

OUTPUT JSON ONLY conforming to this schema:
{
  "reasoning_steps": [
    {
      "step": 1,
      "type": "evidence_identification | causal_inference | purpose_synthesis | distinction | conditional_projection | hypothetical_projection | composition",
      "inference": "<natural language statement of the reasoning step>",
      "evidence_ids": ["<atomic_fact id>"],
      "relation_id": "<R id> | null",
      "inference_strength": "direct | probable | speculative",
      "confidence": 0.0-1.0
    }
  ],
  "answer": "<user-facing prose in the question language, with [doc=...] inline citations>",
  "citations": ["<atomic_fact id>", "<R id>"],
  "reasoning_confidence": 0.0-1.0,
  "abstention_reason": "<null OR constructive explanation if cannot answer>"
}

INFERENCE_STRENGTH (apply STRICTLY):

   "direct" = step is a literal paraphrase of ONE atomic_fact OR follows ONE relational_fact
              marked "direct" without combining or generalizing.
              The inference text must be entailable by a SINGLE evidence_quote alone.
              ABSTRACT PATTERN: if atomic_fact f_a states "<P>", a direct step rephrases it
              minimally without adding scope, qualifier, or combining with another fact.

   "probable" = step COMBINES multiple atomic_facts OR multiple relational_facts,
                OR generalizes/reformulates beyond a single evidence_quote,
                OR infers a relation between facts not explicitly marked.
                The inference is grounded in evidence but requires composition.
                ABSTRACT PATTERNS:
                  - combine f_a + f_b → joint statement covering both
                  - reformulate "<X marker Y>" into "<Y is consequence of X>" without quoting marker
                  - infer purpose/distinction/condition not stated with explicit marker

   "speculative" = inference goes beyond what evidence directly supports,
                   used as last resort with explicit caveat in answer.
                   Should be RARE.

CRITICAL CONSTRAINTS:
1. Every reasoning_step MUST cite at least one evidence_ids OR a relation_id. No exception.
2. Self-check before marking "direct": "Is my inference text fully supported by ONE single
   evidence_quote, without paraphrase that adds words/concepts?" If no → use "probable".
3. For causal/conditional/hypothetical questions: USE relational_facts when present.
4. Do NOT introduce knowledge outside provided evidence. Any specific value, numeric quantity,
   named entity, or technical qualifier mentioned in your inference MUST appear in at least
   one evidence_quote. If you cannot find it in the evidence, do not state it.
5. The "answer" field is user-facing prose. Include INLINE citations using ONLY the doc_id
   value found in the "source.doc_id" field of the cited atomic_fact, in the exact form
   [doc=<doc_id_value_from_source>]. NEVER use the internal atomic_fact id (f1, f2, ...) or
   the chunk id (C0, C1, ...) or the relational id (R1, R2, ...) in the inline citation.
   Pattern correct : [doc=<value found in atomic_facts[i].source.doc_id>]
   Pattern incorrect : [doc=f1], [doc=C0], [doc=R1], [doc=doc=...] (these reference internal IDs, not source doc_ids)
6. If reasoning_graph empty AND atomic_facts insufficient: emit abstention WITH constructive
   reason (e.g., "Found facts about X but no relation to Y in the corpus"), NOT a generic
   "not found in documents".

Output the JSON object only. No prose."""


@dataclass
class ReasoningComposerResult:
    """Output structuré du ReasoningComposer."""
    reasoning_steps: list[dict] = field(default_factory=list)
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    reasoning_confidence: float = 0.0
    abstention_reason: Optional[str] = None
    parse_error: Optional[str] = None
    raw_llm_output: str = ""
    latency_ms: int = 0
    model: str = ""
    n_steps: int = 0
    n_steps_rejected: int = 0  # steps sans citation valide

    def to_dict(self) -> dict:
        return {
            "reasoning_steps": self.reasoning_steps,
            "answer": self.answer,
            "citations": self.citations,
            "reasoning_confidence": self.reasoning_confidence,
            "abstention_reason": self.abstention_reason,
            "n_steps": self.n_steps,
            "n_steps_rejected": self.n_steps_rejected,
        }


class ReasoningComposer:
    """Composer constrained reasoning Qwen2.5-72B (CH-47.2)."""

    def __init__(
        self,
        llm: Optional[RuntimeLLMClient] = None,
        max_tokens: int = 2000,
        temperature: float = 0.1,
        timeout: float = 180.0,
        model_override: Optional[str] = None,
    ) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.model_override = model_override or REASONING_COMPOSER_MODEL_OVERRIDE

    def compose(
        self,
        question: str,
        atomic_facts: list[dict],
        relational_facts: list[dict],
        reasoning_graph: Optional[dict] = None,
        primary_type: str = "factual",
    ) -> ReasoningComposerResult:
        """Génère reasoning_chain + answer.

        Args:
            question: question utilisateur
            atomic_facts: liste d'atomic_facts (id, text, source: {doc_id, quote})
            relational_facts: liste de relational_facts (id, relation_type, antecedent_ids,
                              consequent_ids, evidence_quote, inference_strength)
            reasoning_graph: dict {nodes, edges} (optional)
            primary_type: type de question (causal, hypothetical, etc.)
        """
        t0 = time.time()

        # Construit le prompt user
        af_str = json.dumps(
            [
                {
                    "id": f.get("id"),
                    "text": f.get("text", "")[:300],
                    "source": (f.get("source") or {}),
                }
                for f in atomic_facts[:30]
            ],
            ensure_ascii=False,
            indent=2,
        )
        rf_str = json.dumps(
            [
                {
                    "id": r.get("id"),
                    "relation_type": r.get("relation_type"),
                    "marker": r.get("marker"),
                    "antecedent_ids": r.get("antecedent_ids"),
                    "consequent_ids": r.get("consequent_ids"),
                    "evidence_quote": (r.get("evidence_quote") or "")[:300],
                    "inference_strength": r.get("inference_strength"),
                }
                for r in (relational_facts or [])[:20]
            ],
            ensure_ascii=False,
            indent=2,
        )
        rg_str = json.dumps(reasoning_graph or {"nodes": [], "edges": []}, ensure_ascii=False)

        user_prompt = (
            f"QUESTION (type={primary_type}): {question}\n\n"
            f"ATOMIC_FACTS:\n{af_str}\n\n"
            f"RELATIONAL_FACTS:\n{rf_str}\n\n"
            f"REASONING_GRAPH:\n{rg_str}\n\n"
            f"Generate reasoning_steps and a user-facing answer. Output JSON only."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            meta = self.llm.chat_completion_with_meta(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                json_mode=True,
                timeout=self.timeout,
                model_override=self.model_override,
            )
        except Exception as exc:
            latency_ms = int((time.time() - t0) * 1000)
            logger.warning("ReasoningComposer LLM failed: %s", exc)
            return ReasoningComposerResult(
                parse_error=f"llm_error: {exc}",
                latency_ms=latency_ms,
            )

        latency_ms = int((time.time() - t0) * 1000)
        raw = meta.get("content", "") or ""
        return self._parse(raw, latency_ms, meta.get("model", ""), atomic_facts, relational_facts)

    def _parse(
        self,
        raw: str,
        latency_ms: int,
        model: str,
        atomic_facts: list[dict],
        relational_facts: list[dict],
    ) -> ReasoningComposerResult:
        """Parse + valide le JSON LLM. Channel 1 Verifier rules (ADR D-CH47.4)."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return ReasoningComposerResult(
                parse_error=f"json: {exc}",
                latency_ms=latency_ms,
                model=model,
                raw_llm_output=raw[:500],
            )

        if not isinstance(data, dict):
            return ReasoningComposerResult(
                parse_error="not_object",
                latency_ms=latency_ms,
                model=model,
                raw_llm_output=raw[:500],
            )

        # Validation Channel 1 (ADR §10.4 D-CH47.4) sur reasoning_steps
        atomic_ids = {f.get("id") for f in atomic_facts}
        relational_ids = {r.get("id") for r in (relational_facts or [])}

        valid_steps: list[dict] = []
        rejected_count = 0

        for step in data.get("reasoning_steps") or []:
            if not isinstance(step, dict):
                rejected_count += 1
                continue
            evidence_ids = step.get("evidence_ids") or []
            relation_id = step.get("relation_id")
            inference = step.get("inference") or ""
            strength = step.get("inference_strength")
            stype = step.get("type")

            # Cond 1 — Aucune citation : rejet
            if not evidence_ids and not relation_id:
                rejected_count += 1
                continue
            # Cond 2 — IDs inexistants : rejet
            if evidence_ids and not all(e in atomic_ids for e in evidence_ids):
                rejected_count += 1
                continue
            if relation_id and relation_id not in relational_ids:
                rejected_count += 1
                continue
            # Validation strength (Cond 3 partielle — sans evidence_quote check)
            if strength not in INFERENCE_STRENGTHS:
                rejected_count += 1
                continue
            if stype not in REASONING_STEP_TYPES:
                # Garde le step mais marque type inconnu
                stype = "composition"
            if not inference or len(inference) < 5:
                rejected_count += 1
                continue

            valid_steps.append({
                "step": step.get("step", len(valid_steps) + 1),
                "type": stype,
                "inference": inference[:600],
                "evidence_ids": evidence_ids,
                "relation_id": relation_id,
                "inference_strength": strength,
                "confidence": _safe_conf(step.get("confidence", 0.5)),
            })

        return ReasoningComposerResult(
            reasoning_steps=valid_steps,
            answer=str(data.get("answer", "") or "")[:5000],
            citations=[c for c in (data.get("citations") or [])
                       if isinstance(c, str) and (c in atomic_ids or c in relational_ids)],
            reasoning_confidence=_safe_conf(data.get("reasoning_confidence", 0.5)),
            abstention_reason=(data.get("abstention_reason") or None),
            parse_error=None,
            raw_llm_output=raw[:500],
            latency_ms=latency_ms,
            model=model,
            n_steps=len(valid_steps),
            n_steps_rejected=rejected_count,
        )


def _safe_conf(x, default: float = 0.5) -> float:
    try:
        v = float(x)
        return max(0.0, min(1.0, v))
    except (TypeError, ValueError):
        return default


# Singleton
_default: Optional[ReasoningComposer] = None


def get_reasoning_composer() -> ReasoningComposer:
    """Singleton du ReasoningComposer."""
    global _default
    if _default is None:
        _default = ReasoningComposer()
    return _default


def reset_reasoning_composer() -> None:
    """Force re-init (test/dev)."""
    global _default
    _default = None
