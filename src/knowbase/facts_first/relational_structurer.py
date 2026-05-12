"""
OSMOSIS V4.1 — Relational Structurer (CH-47.1).

Composant additionnel qui enrichit un facts_first existant avec :
  - relational_facts : relations logico-linguistiques entre atomic_facts
                       (causal, purpose, distinction, conditional, hypothetical)
  - reasoning_graph : nodes (atomic IDs) + edges (via relational_fact)

Ne remplace PAS les Structurers existants — vient en post-processing optionnel
pour les types reasoning (causal, hypothetical, conditional, multi_hop). List et
factual simples restent inchangés (prototype CH-47 a montré qu'ils n'en ont pas
besoin).

Architecture (cf ADR §10.4) :
  Structurer existant → atomic_facts (V4 actuel)
        ↓
  RelationalStructurer (NEW) → atomic_facts + relational_facts + reasoning_graph
        ↓
  ReasoningComposer (CH-47.2) → reasoning_steps avec citations forcées

Charte (ADR §10.5) :
  - Marqueurs linguistiques = signaux d'aide UNIVERSELS (FR/EN/DE), pas conditions
  - Anti-graphe global : relations ancrées au corpus local de la question
  - Anti-règles métier : taxonomie P0 limitée à 5 types validés
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from knowbase.runtime_v3.llm_client import RuntimeLLMClient, get_runtime_llm_client

logger = logging.getLogger(__name__)


# Taxonomie P0 — 5 types validés empiriquement (ADR D-CH47.2)
RELATION_TYPES_P0 = ("causal", "purpose", "distinction", "conditional", "hypothetical")

# Niveaux inference_strength (ADR D-CH47.3)
INFERENCE_STRENGTHS = ("direct", "probable", "speculative")


# Override modèle via env (réutilise le pattern des Structurers existants)
RELATIONAL_MODEL_OVERRIDE = os.getenv("RELATIONAL_STRUCTURER_MODEL", "")


SYSTEM_PROMPT = """You are a Relational Structurer for a multi-domain reasoning Q&A system.

Given (1) a user question, (2) a set of evidence chunks, and (3) a list of atomic_facts already
extracted from these chunks, your task is to identify RELATIONAL FACTS — logico-linguistic
relationships between atomic_facts that are anchored in the evidence.

OUTPUT JSON ONLY conforming to this schema:
{
  "relational_facts": [
    {
      "id": "R1",
      "relation_type": "causal | purpose | distinction | conditional | hypothetical",
      "marker": "<linguistic marker if present in evidence_quote, else null>",
      "antecedent_ids": ["<atomic_fact id>"],
      "consequent_ids": ["<atomic_fact id>"],
      "evidence_quote": "<verbatim quote >= 10 chars supporting the relation>",
      "evidence_doc_id": "<doc_id>",
      "inference_strength": "direct | probable | speculative",
      "confidence": 0.0-1.0
    }
  ],
  "reasoning_graph": {
    "nodes": ["<atomic_fact id>"],
    "edges": [{"from": "<id>", "to": "<id>", "via": "<R id>"}]
  }
}

RELATION TYPES (universal, multilingual):
- causal: A causes / leads to / necessitates / results in B
- purpose: A is done in order to / so as to achieve B
- distinction: A and B differ in purpose / scope / role / timing
- conditional: if A then B / when A, B / B provided A / unless A
- hypothetical: in case of A, B would occur / assuming A

INFERENCE_STRENGTH (strictly applied):
- "direct": linguistic marker explicitly present in evidence_quote (because, donc, therefore,
            par consequent, hence, in order to, afin de, if/then, si/alors, when, lorsque,
            unless, sauf si, ...). The relation is stated, not inferred.
- "probable": inference reasonable from adjacent context, NO explicit marker. Multiple
              atomic_facts COMBINED to derive the relation. Reformulation beyond a single
              quote.
- "speculative": weak inference, hypothesis only. Should be rare. Mention with reservation.

CRITICAL CONSTRAINTS:
1. Linguistic markers are HELPFUL SIGNALS, not necessary conditions. Extract relations from
   context even without explicit marker — but mark inference_strength accordingly.
2. Every relational_fact MUST have evidence_quote >= 10 chars from the chunks provided.
3. antecedent_ids and consequent_ids MUST reference atomic_facts that exist in the input list.
4. Do NOT propagate inferences beyond the local question corpus (only the chunks given).
5. Do NOT invent relations not anchored in evidence.
6. If no relations can be extracted, return empty relational_facts array — that is a valid
   answer ("not applicable for this question").

Output the JSON object only. No prose."""


@dataclass
class RelationalResult:
    """Output structuré du RelationalStructurer."""
    relational_facts: list[dict] = field(default_factory=list)
    reasoning_graph: dict = field(default_factory=lambda: {"nodes": [], "edges": []})
    parse_error: Optional[str] = None
    raw_llm_output: str = ""
    latency_ms: int = 0
    model: str = ""
    n_relations: int = 0


class RelationalStructurer:
    """Extrait les relational_facts depuis evidence + atomic_facts existants.

    Utilisé pour les types reasoning (causal, hypothetical, conditional, multi_hop).
    """

    def __init__(
        self,
        llm: Optional[RuntimeLLMClient] = None,
        max_tokens: int = 1500,
        temperature: float = 0.1,
        timeout: float = 120.0,
        model_override: Optional[str] = None,
    ) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.model_override = model_override or (RELATIONAL_MODEL_OVERRIDE or None)

    def extract(
        self,
        question: str,
        atomic_facts: list[dict],
        evidence_chunks: list[dict],
        language: str = "en",
    ) -> RelationalResult:
        """Extrait les relational_facts.

        Args:
            question: question utilisateur
            atomic_facts: liste de dicts {id, text, source: {doc_id, quote}, ...}
                          (déjà extraits par un Structurer en amont)
            evidence_chunks: liste de chunks {id?, doc_id, quote/text}
                             (utilisés comme context pour identifier les relations)
            language: ISO 639-1

        Returns:
            RelationalResult avec relational_facts + reasoning_graph.
        """
        t0 = time.time()

        if not atomic_facts:
            return RelationalResult(
                parse_error="no_atomic_facts",
                latency_ms=int((time.time() - t0) * 1000),
            )

        atomic_str = "\n".join([
            f"  [{f.get('id', '?')}] {f.get('text', '')[:300]}"
            f" (source: doc={((f.get('source') or {}).get('doc_id') or '?')})"
            for f in atomic_facts[:30]
        ])

        chunks_str = "\n".join([
            f"  [{c.get('id', f'C{i}')}] doc={c.get('doc_id', '?')}: "
            f"{(c.get('quote') or c.get('text') or '')[:600]}"
            for i, c in enumerate(evidence_chunks[:12])
        ])

        user_prompt = (
            f"QUESTION: {question}\n\n"
            f"ATOMIC_FACTS (already extracted, reference these by id):\n{atomic_str}\n\n"
            f"EVIDENCE CHUNKS (for finding relations):\n{chunks_str}\n\n"
            f"Extract relational_facts and reasoning_graph as JSON. Output JSON only."
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
            logger.warning("RelationalStructurer LLM failed: %s", exc)
            return RelationalResult(
                parse_error=f"llm_error: {exc}",
                latency_ms=latency_ms,
            )

        latency_ms = int((time.time() - t0) * 1000)
        raw = meta.get("content", "") or ""
        return self._parse(raw, latency_ms, meta.get("model", ""), atomic_facts)

    def _parse(
        self,
        raw: str,
        latency_ms: int,
        model: str,
        atomic_facts: list[dict],
    ) -> RelationalResult:
        """Parse + valide le JSON LLM."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return RelationalResult(
                parse_error=f"json: {exc}",
                latency_ms=latency_ms,
                model=model,
                raw_llm_output=raw[:500],
            )

        if not isinstance(data, dict):
            return RelationalResult(
                parse_error="not_object",
                latency_ms=latency_ms,
                model=model,
                raw_llm_output=raw[:500],
            )

        # Validation déterministe des relational_facts
        atomic_ids = {f.get("id") for f in atomic_facts}
        valid_relations: list[dict] = []
        rejected_count = 0

        for rel in data.get("relational_facts", []) or []:
            if not isinstance(rel, dict):
                rejected_count += 1
                continue
            rel_id = rel.get("id")
            rel_type = rel.get("relation_type")
            antecedents = rel.get("antecedent_ids") or []
            consequents = rel.get("consequent_ids") or []
            quote = rel.get("evidence_quote") or ""
            doc_id = rel.get("evidence_doc_id") or ""
            strength = rel.get("inference_strength")

            # Validation
            if not rel_id or not rel_id.startswith("R"):
                rejected_count += 1
                continue
            if rel_type not in RELATION_TYPES_P0:
                rejected_count += 1
                continue
            if not antecedents or not consequents:
                rejected_count += 1
                continue
            # IDs doivent référencer des atomic_facts existants
            if not all(a in atomic_ids for a in antecedents):
                rejected_count += 1
                continue
            if not all(c in atomic_ids for c in consequents):
                rejected_count += 1
                continue
            if len(quote) < 10:
                rejected_count += 1
                continue
            if not doc_id:
                rejected_count += 1
                continue
            if strength not in INFERENCE_STRENGTHS:
                rejected_count += 1
                continue

            valid_relations.append({
                "id": rel_id,
                "relation_type": rel_type,
                "marker": rel.get("marker") if isinstance(rel.get("marker"), str) else None,
                "antecedent_ids": antecedents,
                "consequent_ids": consequents,
                "evidence_quote": quote[:1500],
                "evidence_doc_id": doc_id,
                "inference_strength": strength,
                "confidence": _safe_conf(rel.get("confidence", 0.5)),
            })

        # Validation reasoning_graph
        graph = data.get("reasoning_graph") or {}
        valid_rel_ids = {r["id"] for r in valid_relations}
        nodes = [n for n in (graph.get("nodes") or []) if n in atomic_ids]
        edges = []
        for e in graph.get("edges") or []:
            if not isinstance(e, dict):
                continue
            f, t, v = e.get("from"), e.get("to"), e.get("via")
            if f in atomic_ids and t in atomic_ids and v in valid_rel_ids:
                edges.append({"from": f, "to": t, "via": v})

        return RelationalResult(
            relational_facts=valid_relations,
            reasoning_graph={"nodes": nodes, "edges": edges},
            n_relations=len(valid_relations),
            parse_error=None if valid_relations or rejected_count == 0 else f"all_rejected_{rejected_count}",
            latency_ms=latency_ms,
            model=model,
            raw_llm_output=raw[:500],
        )


def _safe_conf(x, default: float = 0.5) -> float:
    try:
        v = float(x)
        return max(0.0, min(1.0, v))
    except (TypeError, ValueError):
        return default


# ============================================================================
# Mode UNIFIED : atomic_facts + relational_facts en 1 call LLM (économie latence)
# ============================================================================
#
# Pour le pipeline V4.1 reasoning_mode, on évite 3 calls LLM (Structurer V4 +
# RelationalStructurer + Composer) en faisant atomic+relational en un seul call.
# Style validé par le prototype CH-47 (10/10 questions).

UNIFIED_SYSTEM_PROMPT = """You are a Relational Structurer for a multi-domain reasoning Q&A system. Extract two levels of facts from the evidence chunks to answer a reasoning question:

1. ATOMIC FACTS: directly stated assertions (subject-predicate-object).
2. RELATIONAL FACTS: relationships between atomic_facts that are anchored in the evidence.

OUTPUT JSON ONLY conforming to this schema:
{
  "answerability": "answerable_with_reasoning | answerable | unanswerable",
  "atomic_facts": [
    {
      "id": "f1",
      "text": "<verbatim or near-verbatim assertion from evidence>",
      "source": {"doc_id": "...", "quote": "<verbatim quote >= 10 chars>"}
    }
  ],
  "relational_facts": [
    {
      "id": "R1",
      "relation_type": "causal | purpose | distinction | conditional | hypothetical",
      "marker": "<linguistic marker if present, else null>",
      "antecedent_ids": ["f1"],
      "consequent_ids": ["f2"],
      "evidence_quote": "<verbatim quote supporting the relation>",
      "evidence_doc_id": "<doc_id>",
      "inference_strength": "direct | probable | speculative",
      "confidence": 0.0-1.0
    }
  ],
  "reasoning_graph": {"nodes": ["f1"], "edges": [{"from": "f1", "to": "f2", "via": "R1"}]}
}

RELATION TYPES (universal, multilingual):
- causal: A causes / leads to / necessitates / results in B
- purpose: A is done in order to / so as to achieve B
- distinction: A and B differ in purpose / scope / role / timing
- conditional: if A then B / when A, B / B provided A / unless A
- hypothetical: in case of A, B would occur / assuming A

INFERENCE_STRENGTH:
- "direct": linguistic marker explicitly present in evidence_quote
- "probable": inference reasonable from adjacent context, no explicit marker
- "speculative": weak inference, hypothesis only

CRITICAL CONSTRAINTS:
1. Linguistic markers are HELPFUL SIGNALS, not necessary conditions.
2. Every relational_fact MUST have evidence_quote >= 10 chars.
3. Do NOT propagate inferences beyond the local question corpus.
4. Do NOT invent relations not anchored in evidence.
5. Set answerability="answerable_with_reasoning" if relational_facts needed; "answerable" if atomic suffice; "unanswerable" if even relational analysis cannot answer.

Output the JSON object only. No prose."""


@dataclass
class UnifiedExtractionResult:
    """Output unifié atomic+relational en 1 call."""
    atomic_facts: list[dict] = field(default_factory=list)
    relational_facts: list[dict] = field(default_factory=list)
    reasoning_graph: dict = field(default_factory=lambda: {"nodes": [], "edges": []})
    answerability: str = "answerable"
    parse_error: Optional[str] = None
    raw_llm_output: str = ""
    latency_ms: int = 0
    model: str = ""


def extract_unified(
    question: str,
    evidence_chunks: list[dict],
    language: str = "en",
    structurer: Optional[RelationalStructurer] = None,
) -> UnifiedExtractionResult:
    """Extrait atomic_facts + relational_facts en 1 call LLM.

    Style prototype CH-47, économie latence pour le pipeline V4.1 reasoning_mode.
    """
    s = structurer or get_relational_structurer()
    t0 = time.time()

    if not evidence_chunks:
        return UnifiedExtractionResult(
            parse_error="no_evidence", latency_ms=int((time.time() - t0) * 1000),
        )

    chunks_str = "\n".join([
        f"[{c.get('id', f'C{i}')}] doc={c.get('doc_id', '?')}: "
        f"{(c.get('quote') or c.get('text') or '')[:1500]}"
        for i, c in enumerate(evidence_chunks[:12])
    ])

    user = (
        f"QUESTION: {question}\n\n"
        f"EVIDENCE CHUNKS:\n{chunks_str}\n\n"
        f"Extract atomic_facts, relational_facts and reasoning_graph as JSON."
    )

    messages = [
        {"role": "system", "content": UNIFIED_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]

    try:
        meta = s.llm.chat_completion_with_meta(
            messages=messages,
            temperature=s.temperature,
            max_tokens=2500,  # plus généreux pour atomic + relational + graph
            json_mode=True,
            timeout=s.timeout,
            model_override=s.model_override,
        )
    except Exception as exc:
        latency_ms = int((time.time() - t0) * 1000)
        return UnifiedExtractionResult(
            parse_error=f"llm_error: {exc}", latency_ms=latency_ms,
        )

    latency_ms = int((time.time() - t0) * 1000)
    raw = meta.get("content", "") or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return UnifiedExtractionResult(
            parse_error=f"json: {exc}", latency_ms=latency_ms,
            raw_llm_output=raw[:500], model=meta.get("model", ""),
        )
    if not isinstance(data, dict):
        return UnifiedExtractionResult(
            parse_error="not_object", latency_ms=latency_ms,
            raw_llm_output=raw[:500], model=meta.get("model", ""),
        )

    # Validation atomic_facts
    valid_atomics: list[dict] = []
    atomic_ids = set()
    for af in data.get("atomic_facts") or []:
        if not isinstance(af, dict):
            continue
        aid = af.get("id")
        text = (af.get("text") or "").strip()
        src = af.get("source") or {}
        quote = (src.get("quote") or "").strip()
        if not aid or not text or len(quote) < 10:
            continue
        valid_atomics.append({
            "id": aid, "text": text[:600],
            "source": {"doc_id": src.get("doc_id") or "?", "quote": quote[:1500]},
            "confidence": _safe_conf(af.get("confidence", 0.7)),
        })
        atomic_ids.add(aid)

    # Validation relational_facts via la même logique que le module
    valid_rels: list[dict] = []
    for rel in data.get("relational_facts") or []:
        if not isinstance(rel, dict):
            continue
        rel_id = rel.get("id")
        rt = rel.get("relation_type")
        ant = rel.get("antecedent_ids") or []
        cons = rel.get("consequent_ids") or []
        quote = rel.get("evidence_quote") or ""
        doc_id = rel.get("evidence_doc_id") or ""
        strength = rel.get("inference_strength")
        if not rel_id or not rel_id.startswith("R"):
            continue
        if rt not in RELATION_TYPES_P0:
            continue
        if not ant or not cons or len(quote) < 10 or not doc_id:
            continue
        if strength not in INFERENCE_STRENGTHS:
            continue
        if not all(a in atomic_ids for a in ant) or not all(c in atomic_ids for c in cons):
            continue
        valid_rels.append({
            "id": rel_id, "relation_type": rt,
            "marker": rel.get("marker") if isinstance(rel.get("marker"), str) else None,
            "antecedent_ids": ant, "consequent_ids": cons,
            "evidence_quote": quote[:1500], "evidence_doc_id": doc_id,
            "inference_strength": strength,
            "confidence": _safe_conf(rel.get("confidence", 0.5)),
        })
    rel_ids = {r["id"] for r in valid_rels}

    # reasoning_graph
    rg = data.get("reasoning_graph") or {}
    nodes = [n for n in (rg.get("nodes") or []) if n in atomic_ids]
    edges = []
    for e in rg.get("edges") or []:
        if not isinstance(e, dict):
            continue
        if e.get("from") in atomic_ids and e.get("to") in atomic_ids and e.get("via") in rel_ids:
            edges.append({"from": e["from"], "to": e["to"], "via": e["via"]})

    answerability = data.get("answerability") or "answerable"
    if answerability not in ("answerable", "answerable_with_reasoning", "unanswerable"):
        answerability = "answerable"

    return UnifiedExtractionResult(
        atomic_facts=valid_atomics,
        relational_facts=valid_rels,
        reasoning_graph={"nodes": nodes, "edges": edges},
        answerability=answerability,
        parse_error=None,
        raw_llm_output=raw[:500],
        latency_ms=latency_ms,
        model=meta.get("model", ""),
    )


# Singleton
_default: Optional[RelationalStructurer] = None


def get_relational_structurer() -> RelationalStructurer:
    """Singleton du RelationalStructurer."""
    global _default
    if _default is None:
        _default = RelationalStructurer()
    return _default


def reset_relational_structurer() -> None:
    """Force re-init (test/dev)."""
    global _default
    _default = None
