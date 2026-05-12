"""
OSMOSIS V4 — Tranche 5 Causal pipeline (CH-41 T5).

CausalStructurer + CausalComposer + Channel1CausalVerifier.
Schéma : facts_first_v1_causal.json (causal_chains avec steps + missing_links + answer_mode).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from knowbase.facts_first.evidence_collector import EvidenceBundle
from knowbase.facts_first.list_verifier import (
    IDENTIFIER_HEURISTIC_RE, SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING,
    VerifierIssue, VerifierReport,
)
from knowbase.runtime_v3.llm_client import RuntimeLLMClient, get_runtime_llm_client

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "facts_first_v1"
DEFAULT_TOP_EVIDENCE = 18
MIN_QUOTE_CHARS = 10

# Levier 4 — override modèle Structurer (Llama-3.3-70B-Turbo bake-off, etc.)
STRUCTURER_MODEL_OVERRIDE = os.getenv("FACTS_FIRST_STRUCTURER_MODEL", "")


SYSTEM_PROMPT_STRUCTURER = """You extract a CAUSAL CHAIN explaining the user's "why" question, strictly grounded in the evidence pool.

Output JSON ONLY:
{
  "causal_question": "<reformulation of the why-question>",
  "causal_chains": [
    {
      "chain_id": "C1",
      "steps": [
        {
          "step_id": "C1_S1",
          "role": "cause | effect | condition | unknown",
          "statement": "<verbatim or close-to-verbatim statement of the step>",
          "source": {
            "doc_id": "...", "claim_id": "...", "chunk_id": null, "page_no": null, "section_id": null,
            "quote": "<≥10 chars verbatim>"
          },
          "confidence": <0-1>
        }
      ],
      "chain_confidence": <0-1>,
      "missing_links": [
        {"position": "before_first | between_steps | after_last",
         "description": "what is missing in the evidence chain",
         "between_step_ids": null or ["Cx_Sy", "Cx_Sz"]}
      ]
    }
  ],
  "answer_mode": "full_explanation | partial_explanation | no_explanation_supported"
}

RULES:
1. Each step MUST have verbatim source quote ≥10 chars from EVIDENCE POOL.
2. Steps in chain are ordered (cause → effect, or condition → consequence).
3. If the chain has gaps not covered by evidence → declare them in missing_links (D-FF1: do not invent).
4. If NO causal explanation is supported by evidence → causal_chains=[] and answer_mode="no_explanation_supported".
5. Multiple chains allowed only if evidence supports concurrent explanations.

Return only the JSON object."""


SYSTEM_PROMPT_COMPOSER = """Produce a short causal explanation from a structured chain.
Output JSON ONLY: {"answer_text": "...", "sentence_support": [{"sentence_index": 0, "text": "...", "support_ids": ["C1_S1"]}]}

Rules:
- Use step.statement verbatim where possible.
- Connect steps with causal connectors ("because", "therefore", "this leads to").
- If missing_links non-empty, mention the gap honestly ("The evidence does not explicitly state X").
- If chains empty: 'La réponse à votre question n'a pas été trouvée...'."""


@dataclass
class StructurerResult:
    facts_first_json: dict
    raw_llm_output: str = ""
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    parse_error: Optional[str] = None
    rejected_steps: list[dict] = field(default_factory=list)


@dataclass
class ComposerResult:
    answer_text: str
    sentence_support: list[dict]
    language: str = "en"
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    parse_error: Optional[str] = None
    format: str = "causal_prose"
    raw_llm_output: str = ""

    def to_dict(self) -> dict:
        return {"answer_text": self.answer_text, "sentence_support": self.sentence_support,
                "language": self.language, "format": self.format}


def _quote_grounded(quote: str, pool_norm) -> bool:
    q_norm = " ".join(quote.lower().split())
    if len(q_norm) < MIN_QUOTE_CHARS:
        return False
    for _, pq in pool_norm:
        if q_norm in pq or pq in q_norm:
            return True
    item_tokens = set(t for t in q_norm.split() if len(t) > 3)
    if not item_tokens:
        return False
    for _, pq in pool_norm:
        pt = set(t for t in pq.split() if len(t) > 3)
        if pt and len(item_tokens & pt) / max(1, len(item_tokens)) >= 0.5:
            return True
    return False


class CausalStructurer:
    def __init__(self, llm: Optional[RuntimeLLMClient] = None,
                 max_chains: int = 3, max_steps: int = 8,
                 top_evidence: int = DEFAULT_TOP_EVIDENCE,
                 temperature: float = 0.05, max_tokens: int = 1800, timeout: float = 120.0) -> None:  # CH-46 L6 : 2500→1800
        self.llm = llm or get_runtime_llm_client()
        self.max_chains = max_chains
        self.max_steps = max_steps
        self.top_evidence = top_evidence
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def structure(
        self,
        question: str,
        evidence: EvidenceBundle,
        language: str = "en",
        domain_pack: Optional[str] = None,
        tenant_id: str = "default",
        feedback_for_retry: Optional[str] = None,
    ) -> StructurerResult:
        t0 = time.time()
        if not evidence.claims:
            return self._empty(question, evidence, language, domain_pack, tenant_id, "no_evidence", t0)

        ev_pool = sorted(evidence.claims, key=lambda c: c.score, reverse=True)[: self.top_evidence]
        evidence_block = "\n".join(
            f"EV{i} | doc={c.doc_id} | claim={c.claim_id or c.chunk_id or '?'} | quote: {(c.quote or '')[:400]}"
            for i, c in enumerate(ev_pool, 1)
        )
        feedback = f"\n\nPREVIOUS ATTEMPT FEEDBACK:\n{feedback_for_retry[:600]}\n" if feedback_for_retry else ""
        user_prompt = (
            f"QUESTION (language={language}): {question.strip()}\n\n"
            f"EVIDENCE POOL ({len(ev_pool)} candidates):\n{evidence_block}{feedback}\n\n"
            "Extract a causal chain. Output JSON only."
        )
        try:
            kw = {
                "messages": [{"role": "system", "content": SYSTEM_PROMPT_STRUCTURER},
                             {"role": "user", "content": user_prompt}],
                "temperature": self.temperature, "max_tokens": self.max_tokens,
                "json_mode": True, "timeout": self.timeout,
            }
            if STRUCTURER_MODEL_OVERRIDE:
                kw["model_override"] = STRUCTURER_MODEL_OVERRIDE
            meta = self.llm.chat_completion_with_meta(**kw)
        except Exception as exc:
            logger.warning("CausalStructurer LLM failed: %s", exc)
            r = self._empty(question, evidence, language, domain_pack, tenant_id, f"llm_error", t0)
            r.parse_error = str(exc)
            return r

        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            r = self._empty(question, evidence, language, domain_pack, tenant_id, "json_parse_error", t0)
            r.parse_error = f"json_parse: {exc}"; r.raw_llm_output = raw[:600]
            return r

        validated_chains, rejected = self._validate(parsed.get("causal_chains", []), ev_pool)
        answer_mode = str(parsed.get("answer_mode") or "no_explanation_supported")
        if answer_mode not in ("full_explanation", "partial_explanation", "no_explanation_supported"):
            answer_mode = "partial_explanation" if validated_chains else "no_explanation_supported"
        if not validated_chains:
            answer_mode = "no_explanation_supported"

        ff = {
            "schema_version": SCHEMA_VERSION, "primary_type": "causal", "secondary_type": None,
            "answerability": "answerable" if validated_chains else "unanswerable",
            "coverage_state": "complete" if answer_mode == "full_explanation" else
                              ("partial" if validated_chains else "unknown"),
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": f"{meta.get('model') or 'unknown'}@{meta.get('provider') or 'unknown'}",
            "tenant_id": tenant_id, "domain_pack": domain_pack,
            "causal_specific": {
                "causal_question": str(parsed.get("causal_question") or question)[:300],
                "causal_chains": validated_chains,
                "answer_mode": answer_mode,
            },
            "diagnostic": {"latency_ms": int((time.time() - t0) * 1000),
                           "evidence_count": len(ev_pool),
                           "rejected_steps_count": len(rejected)},
        }
        return StructurerResult(
            facts_first_json=ff, raw_llm_output=raw[:600],
            latency_ms=int((time.time() - t0) * 1000),
            model=meta.get("model", ""), provider=meta.get("provider", ""),
            rejected_steps=rejected,
        )

    def _validate(self, raw_chains, ev_pool):
        valid_chains: list[dict] = []
        rejected_all: list[dict] = []
        pool_norm = [(c, " ".join((c.quote or "").lower().split())) for c in ev_pool]
        for ci, raw_chain in enumerate((raw_chains or [])[: self.max_chains], start=1):
            if not isinstance(raw_chain, dict):
                rejected_all.append({"chain_idx": ci, "reason": "not_object"}); continue
            raw_steps = raw_chain.get("steps") or []
            valid_steps: list[dict] = []
            for si, raw_step in enumerate((raw_steps or [])[: self.max_steps], start=1):
                if not isinstance(raw_step, dict):
                    rejected_all.append({"reason": "step_not_object"}); continue
                statement = str(raw_step.get("statement") or "").strip()
                src = raw_step.get("source") or {}
                quote = str(src.get("quote") or "").strip()
                if not statement or len(statement) < 5:
                    rejected_all.append({"reason": "statement_too_short"}); continue
                if len(quote) < MIN_QUOTE_CHARS:
                    rejected_all.append({"reason": "quote_too_short"}); continue
                if not _quote_grounded(quote, pool_norm):
                    rejected_all.append({"reason": "quote_not_grounded"}); continue
                try:
                    conf = max(0.0, min(1.0, float(raw_step.get("confidence", 0.5))))
                except (TypeError, ValueError):
                    conf = 0.5
                valid_steps.append({
                    "step_id": f"C{ci}_S{len(valid_steps) + 1}",
                    "role": str(raw_step.get("role") or "unknown")[:30],
                    "statement": statement[:600],
                    "source": {
                        "doc_id": str(src.get("doc_id") or "unknown"),
                        "claim_id": src.get("claim_id"),
                        "chunk_id": src.get("chunk_id"),
                        "page_no": src.get("page_no"),
                        "section_id": src.get("section_id"),
                        "quote": quote[:1000],
                    },
                    "confidence": conf,
                })
            if not valid_steps:
                continue
            try:
                chain_conf = max(0.0, min(1.0, float(raw_chain.get("chain_confidence", 0.5))))
            except (TypeError, ValueError):
                chain_conf = 0.5
            missing_links = []
            for ml in (raw_chain.get("missing_links") or []):
                if isinstance(ml, dict) and ml.get("position") in ("before_first", "between_steps", "after_last"):
                    missing_links.append({
                        "position": ml["position"],
                        "description": str(ml.get("description") or "")[:300],
                        "between_step_ids": ml.get("between_step_ids"),
                    })
            valid_chains.append({
                "chain_id": f"C{len(valid_chains) + 1}",
                "steps": valid_steps,
                "chain_confidence": chain_conf,
                "missing_links": missing_links,
            })
        return valid_chains, rejected_all

    def _empty(self, question, evidence, language, domain_pack, tenant_id, reason, t0):
        ff = {
            "schema_version": SCHEMA_VERSION, "primary_type": "causal", "secondary_type": None,
            "answerability": "unanswerable", "coverage_state": "unknown",
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": "none@none",
            "tenant_id": tenant_id, "domain_pack": domain_pack,
            "causal_specific": {
                "causal_question": question[:300],
                "causal_chains": [],
                "answer_mode": "no_explanation_supported",
            },
            "diagnostic": {"latency_ms": int((time.time() - t0) * 1000),
                           "evidence_count": len(evidence.claims), "reason": reason},
        }
        return StructurerResult(facts_first_json=ff, latency_ms=int((time.time() - t0) * 1000))


class CausalComposer:
    def __init__(self, llm: Optional[RuntimeLLMClient] = None,
                 model_override: Optional[str] = None) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.model_override = model_override or "google/gemma-3-12b-it"

    def compose(self, facts_first: dict) -> ComposerResult:
        t0 = time.time()
        language = (facts_first.get("language") or "en").lower()
        cs = facts_first.get("causal_specific") or {}
        chains = cs.get("causal_chains") or []
        answer_mode = cs.get("answer_mode")
        if not chains or answer_mode == "no_explanation_supported":
            msg = self._abstention_message(language)
            return ComposerResult(
                answer_text=msg,
                sentence_support=[{"sentence_index": 0, "text": msg, "support_ids": []}],
                language=language, latency_ms=int((time.time() - t0) * 1000),
                model="deterministic", provider="local",
            )

        chains_compact = []
        for ch in chains:
            chains_compact.append({
                "chain_id": ch["chain_id"],
                "steps": [{"step_id": s["step_id"], "role": s["role"], "statement": s["statement"]}
                          for s in ch["steps"]],
                "missing_links": ch.get("missing_links", []),
            })
        user = (
            f"LANGUAGE: {language}\nQUESTION: {cs.get('causal_question', '')}\n"
            f"ANSWER_MODE: {answer_mode}\n"
            f"CHAINS:\n{json.dumps(chains_compact, ensure_ascii=False, indent=2)}\n\n"
            "Compose a causal explanation. Output JSON only."
        )
        try:
            meta = self.llm.chat_completion_with_meta(
                messages=[{"role": "system", "content": SYSTEM_PROMPT_COMPOSER},
                          {"role": "user", "content": user}],
                temperature=0.05, max_tokens=900, json_mode=True, timeout=30.0,
                model_override=self.model_override,
            )
        except Exception as exc:
            return self._fallback(chains, language, t0, str(exc))
        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._fallback(chains, language, t0, f"json_parse: {exc}")
        answer = str(parsed.get("answer_text") or "").strip()
        ss = parsed.get("sentence_support") or []
        if not answer or not isinstance(ss, list):
            return self._fallback(chains, language, t0, "missing_fields")
        clean = []
        for i, s in enumerate(ss):
            if isinstance(s, dict) and s.get("text"):
                sids = [str(x) for x in (s.get("support_ids") or []) if isinstance(x, (str, int))]
                clean.append({"sentence_index": int(s.get("sentence_index", i)),
                              "text": str(s["text"])[:500], "support_ids": sids})
        return ComposerResult(
            answer_text=answer, sentence_support=clean, language=language,
            latency_ms=int((time.time() - t0) * 1000),
            model=meta.get("model", ""), provider=meta.get("provider", ""),
            raw_llm_output=raw[:600],
        )

    def _fallback(self, chains, language, t0, parse_error):
        intro = "Explication causale :" if language.startswith("fr") else "Causal explanation:"
        lines = [intro]
        all_step_ids = []
        for ch in chains:
            for s in ch.get("steps", []):
                all_step_ids.append(s["step_id"])
        ss = [{"sentence_index": 0, "text": intro, "support_ids": all_step_ids[:8]}]
        for ch in chains:
            for idx, step in enumerate(ch.get("steps", []), 1):
                line = f"  - [{step['role']}] {step['statement']}"
                lines.append(line)
                ss.append({"sentence_index": len(ss),
                           "text": line, "support_ids": [step["step_id"]]})
        return ComposerResult(
            answer_text="\n".join(lines), sentence_support=ss, language=language,
            latency_ms=int((time.time() - t0) * 1000),
            model="deterministic", provider="local", parse_error=parse_error,
        )

    @staticmethod
    def _abstention_message(language):
        return ("La réponse à votre question n'a pas été trouvée dans les documents disponibles."
                if language.startswith("fr") else
                "The answer to your question was not found in the available documents.")


REQUIRED_COMMON = ("schema_version", "primary_type", "answerability", "coverage_state", "language", "extracted_at", "extraction_model")


class Channel1CausalVerifier:
    def verify(self, question: str, facts_first: dict, composer_output: Optional[dict] = None) -> VerifierReport:
        report = VerifierReport(passed=True)
        for f in REQUIRED_COMMON:
            if f not in facts_first:
                report.add(VerifierIssue("schema.common.missing_field", SEVERITY_ERROR, f"Missing '{f}'"))
        if facts_first.get("schema_version") != "facts_first_v1":
            report.add(VerifierIssue("schema.common.bad_version", SEVERITY_ERROR, ""))
        if facts_first.get("primary_type") != "causal":
            report.add(VerifierIssue("schema.common.bad_primary_type", SEVERITY_ERROR, ""))
        cs = facts_first.get("causal_specific") or {}
        for f in ("causal_question", "causal_chains", "answer_mode"):
            if f not in cs:
                report.add(VerifierIssue("schema.causal.missing_field", SEVERITY_ERROR, f"missing '{f}'"))

        chains = cs.get("causal_chains") or []
        all_step_ids: set[str] = set()
        for ci, ch in enumerate(chains):
            if not isinstance(ch, dict):
                report.add(VerifierIssue("causal.chain.not_object", SEVERITY_ERROR, f"chain[{ci}]"))
                continue
            steps = ch.get("steps") or []
            if not steps:
                report.add(VerifierIssue("causal.chain.empty_steps", SEVERITY_ERROR, f"chain[{ci}]"))
            seen_step_ids: set[str] = set()
            for si, step in enumerate(steps):
                if not isinstance(step, dict):
                    report.add(VerifierIssue("causal.step.not_object", SEVERITY_ERROR, f"step[{ci}.{si}]"))
                    continue
                stid = step.get("step_id")
                if stid:
                    if stid in seen_step_ids:
                        report.add(VerifierIssue("causal.step.duplicate_id", SEVERITY_ERROR, f"dup {stid}"))
                    seen_step_ids.add(stid)
                    all_step_ids.add(stid)
                src = step.get("source") or {}
                if len((src.get("quote") or "").strip()) < MIN_QUOTE_CHARS:
                    report.add(VerifierIssue("causal.step.source.quote_too_short", SEVERITY_ERROR,
                                             f"step[{ci}.{si}].source.quote", context={"step_id": stid}))
                if not src.get("doc_id"):
                    report.add(VerifierIssue("causal.step.source.missing_doc_id", SEVERITY_ERROR,
                                             f"step[{ci}.{si}].source", context={"step_id": stid}))

        if facts_first.get("answerability") == "answerable" and not chains:
            report.add(VerifierIssue("causal.answerable_but_empty", SEVERITY_ERROR, "empty chains"))

        if composer_output is not None:
            ss = composer_output.get("sentence_support") or []
            unknown: set[str] = set()
            for s in ss:
                for sid in (s or {}).get("support_ids") or []:
                    if isinstance(sid, str) and sid not in all_step_ids:
                        unknown.add(sid)
            if unknown:
                report.add(VerifierIssue("composer.support_ids.unknown", SEVERITY_ERROR,
                                         f"unknown step_ids: {sorted(unknown)[:5]}"))

        question_ids = {m.group(0).lower().strip() for m in IDENTIFIER_HEURISTIC_RE.finditer(question)}
        if question_ids:
            haystack = " ".join(
                [str(s.get("statement", "")) + " " + str((s.get("source") or {}).get("quote", ""))
                 for ch in chains for s in (ch.get("steps") or [])]
            )
            if composer_output:
                haystack += " " + (composer_output.get("answer_text") or "")
            haystack_ids = {m.group(0).lower().strip() for m in IDENTIFIER_HEURISTIC_RE.finditer(haystack)}
            missing = question_ids - haystack_ids
            if missing:
                report.add(VerifierIssue("identifier.missing_in_response", SEVERITY_WARNING,
                                         f"missing: {sorted(missing)}"))
        return report


_default_structurer: Optional[CausalStructurer] = None
_default_composer: Optional[CausalComposer] = None
_default_verifier: Optional[Channel1CausalVerifier] = None


def get_causal_structurer():
    global _default_structurer
    if _default_structurer is None:
        _default_structurer = CausalStructurer()
    return _default_structurer


def get_causal_composer():
    global _default_composer
    if _default_composer is None:
        _default_composer = CausalComposer()
    return _default_composer


def get_causal_verifier():
    global _default_verifier
    if _default_verifier is None:
        _default_verifier = Channel1CausalVerifier()
    return _default_verifier
