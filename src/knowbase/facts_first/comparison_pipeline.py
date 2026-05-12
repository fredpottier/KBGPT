"""
OSMOSIS V4 — Tranche 4 Comparison pipeline (CH-41 T4).

ComparisonStructurer + ComparisonComposer + Channel1ComparisonVerifier.
Schéma : facts_first_v1_comparison.json (compared_facts ≥ 2, relation, preferred_answer_basis).
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
RELATION_TYPES_CORE = {"equivalent", "different", "related", "unknown"}
BASIS_CORE = {"value", "time", "unknown"}

# Levier 4 — override modèle Structurer (Llama-3.3-70B-Turbo bake-off, etc.)
STRUCTURER_MODEL_OVERRIDE = os.getenv("FACTS_FIRST_STRUCTURER_MODEL", "")


SYSTEM_PROMPT_STRUCTURER = """You COMPARE ≥2 sides for the user's question, strictly grounded in the evidence pool.

Output JSON ONLY:
{
  "comparison_subject": "<what is being compared (e.g. 'impact energy', 'data retention')>",
  "compared_facts": [
    {
      "side_id": "A", "label": "<label (e.g. 'EU 2021/821', 'CS-25 amdt 26')>",
      "fact": {
        "subject": "...", "predicate": "...",
        "object_raw": "<verbatim value>",
        "qualifiers": {
          "condition": null, "scope": null, "time_anchor": "<context anchor or null>",
          "lifecycle_status": "ACTIVE | DEPRECATED | UNKNOWN"
        }
      },
      "source": {
        "doc_id": "...", "claim_id": "...", "chunk_id": null, "page_no": null, "section_id": null,
        "quote": "<≥10 chars verbatim>"
      }
    },
    {"side_id": "B", "label": "...", "fact": {...}, "source": {...}}
  ],
  "relation": {
    "type": "equivalent | different | related | unknown",
    "basis": "value | time | unknown",
    "explanation": "<why this relation>",
    "confidence": <0-1>
  },
  "preferred_answer_basis": {"side_id": "A|B|...", "reason": "active_source | most_recent | broader_scope"}
}

RULES:
1. ≥2 compared_facts (sides A, B, optionally C/D).
2. Each side MUST have verbatim source quote ≥10 chars from EVIDENCE POOL.
3. relation.type uses core values; if Domain Pack extension needed, still output verbatim.
4. preferred_answer_basis points to the ACTIVE side if applicable, or the most recent.
5. If no genuine comparison possible from evidence → compared_facts=[].

Return only the JSON object."""


SYSTEM_PROMPT_COMPOSER = """Produce a short comparative answer from a structured comparison.
Output JSON ONLY: {"answer_text": "...", "sentence_support": [{"sentence_index": 0, "text": "...", "support_ids": ["A", "B"]}]}

Rules:
- Use object_raw values verbatim from each side.
- Highlight the preferred_answer_basis side as 'current' if status is ACTIVE.
- Mention the relation type (equivalent/different/related) honestly.
- If compared_facts empty: 'La réponse à votre question n'a pas été trouvée...' / 'The answer was not found...'."""


@dataclass
class StructurerResult:
    facts_first_json: dict
    raw_llm_output: str = ""
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    parse_error: Optional[str] = None
    rejected_sides: list[dict] = field(default_factory=list)


@dataclass
class ComposerResult:
    answer_text: str
    sentence_support: list[dict]
    language: str = "en"
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    parse_error: Optional[str] = None
    format: str = "comparison_prose"
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


class ComparisonStructurer:
    def __init__(self, llm: Optional[RuntimeLLMClient] = None,
                 max_sides: int = 5, top_evidence: int = DEFAULT_TOP_EVIDENCE,
                 temperature: float = 0.05, max_tokens: int = 1800, timeout: float = 120.0) -> None:  # CH-46 L6 : 2500→1800
        self.llm = llm or get_runtime_llm_client()
        self.max_sides = max_sides
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
            "Build a structured comparison. Output JSON only."
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
            logger.warning("ComparisonStructurer LLM failed: %s", exc)
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

        validated, rejected = self._validate(parsed.get("compared_facts", []), ev_pool)
        # Comparison nécessite ≥ 2 sides — sinon unanswerable
        if len(validated) < 2:
            return self._empty_with_rejected(question, evidence, language, domain_pack, tenant_id,
                                              "fewer_than_2_sides", t0, rejected)

        relation = parsed.get("relation") or {}
        rel_type = str(relation.get("type") or "unknown")
        rel_basis = str(relation.get("basis") or "unknown")
        try:
            rel_conf = max(0.0, min(1.0, float(relation.get("confidence", 0.5))))
        except (TypeError, ValueError):
            rel_conf = 0.5

        pref = parsed.get("preferred_answer_basis") or {}
        pref_clean = None
        if pref.get("side_id") in {f["side_id"] for f in validated}:
            pref_clean = {
                "side_id": pref["side_id"],
                "reason": str(pref.get("reason") or "unknown")[:200],
            }

        ff = {
            "schema_version": SCHEMA_VERSION, "primary_type": "comparison", "secondary_type": None,
            "answerability": "answerable",
            "coverage_state": "partial",
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": f"{meta.get('model') or 'unknown'}@{meta.get('provider') or 'unknown'}",
            "tenant_id": tenant_id, "domain_pack": domain_pack,
            "comparison_specific": {
                "comparison_subject": str(parsed.get("comparison_subject") or "")[:200] or "subject",
                "compared_facts": validated,
                "relation": {
                    "type": rel_type[:50],
                    "basis": rel_basis[:50],
                    "explanation": str(relation.get("explanation") or "")[:500],
                    "confidence": rel_conf,
                },
                "preferred_answer_basis": pref_clean,
            },
            "diagnostic": {"latency_ms": int((time.time() - t0) * 1000),
                           "evidence_count": len(ev_pool),
                           "rejected_sides_count": len(rejected)},
        }
        return StructurerResult(
            facts_first_json=ff, raw_llm_output=raw[:600],
            latency_ms=int((time.time() - t0) * 1000),
            model=meta.get("model", ""), provider=meta.get("provider", ""),
            rejected_sides=rejected,
        )

    def _validate(self, raw_sides, ev_pool):
        valid: list[dict] = []
        rejected: list[dict] = []
        pool_norm = [(c, " ".join((c.quote or "").lower().split())) for c in ev_pool]
        seen_ids: set[str] = set()
        for raw in (raw_sides or [])[: self.max_sides]:
            if not isinstance(raw, dict):
                rejected.append({"reason": "not_object"}); continue
            sid = str(raw.get("side_id") or "").strip().upper()
            if sid not in {"A", "B", "C", "D", "E"}:
                rejected.append({"reason": "invalid_side_id"}); continue
            if sid in seen_ids:
                rejected.append({"reason": "duplicate_side_id"}); continue
            seen_ids.add(sid)
            fact = raw.get("fact") or {}
            obj_raw = str(fact.get("object_raw") or "").strip()
            subject = str(fact.get("subject") or "").strip()
            predicate = str(fact.get("predicate") or "").strip()
            src = raw.get("source") or {}
            quote = str(src.get("quote") or "").strip()
            if not subject or not predicate or not obj_raw or len(quote) < MIN_QUOTE_CHARS:
                rejected.append({"reason": "missing_field"}); continue
            if not _quote_grounded(quote, pool_norm):
                rejected.append({"reason": "quote_not_grounded"}); continue
            qualifiers = fact.get("qualifiers") or {}
            valid.append({
                "side_id": sid,
                "label": str(raw.get("label") or sid)[:200],
                "fact": {
                    "subject": subject[:300],
                    "predicate": predicate[:200],
                    "object_raw": obj_raw[:500],
                    "qualifiers": {
                        "condition": qualifiers.get("condition"),
                        "scope": qualifiers.get("scope"),
                        "time_anchor": qualifiers.get("time_anchor"),
                        "lifecycle_status": str(qualifiers.get("lifecycle_status") or "UNKNOWN"),
                    },
                },
                "source": {
                    "doc_id": str(src.get("doc_id") or "unknown"),
                    "claim_id": src.get("claim_id"),
                    "chunk_id": src.get("chunk_id"),
                    "page_no": src.get("page_no"),
                    "section_id": src.get("section_id"),
                    "quote": quote[:1000],
                },
            })
        return valid, rejected

    def _empty(self, question, evidence, language, domain_pack, tenant_id, reason, t0):
        ff = {
            "schema_version": SCHEMA_VERSION, "primary_type": "comparison", "secondary_type": None,
            "answerability": "unanswerable", "coverage_state": "unknown",
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": "none@none",
            "tenant_id": tenant_id, "domain_pack": domain_pack,
            "comparison_specific": {
                "comparison_subject": "subject",
                "compared_facts": [],
                "relation": {"type": "unknown", "basis": "unknown", "explanation": "", "confidence": 0.0},
                "preferred_answer_basis": None,
            },
            "diagnostic": {"latency_ms": int((time.time() - t0) * 1000),
                           "evidence_count": len(evidence.claims), "reason": reason},
        }
        return StructurerResult(facts_first_json=ff, latency_ms=int((time.time() - t0) * 1000))

    def _empty_with_rejected(self, question, evidence, language, domain_pack, tenant_id, reason, t0, rejected):
        result = self._empty(question, evidence, language, domain_pack, tenant_id, reason, t0)
        result.rejected_sides = rejected
        return result


class ComparisonComposer:
    def __init__(self, llm: Optional[RuntimeLLMClient] = None,
                 model_override: Optional[str] = None) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.model_override = model_override or "google/gemma-3-12b-it"

    def compose(self, facts_first: dict) -> ComposerResult:
        t0 = time.time()
        language = (facts_first.get("language") or "en").lower()
        cs = facts_first.get("comparison_specific") or {}
        sides = cs.get("compared_facts") or []
        if not sides:
            msg = self._abstention_message(language)
            return ComposerResult(
                answer_text=msg,
                sentence_support=[{"sentence_index": 0, "text": msg, "support_ids": []}],
                language=language, latency_ms=int((time.time() - t0) * 1000),
                model="deterministic", provider="local",
            )

        sides_compact = [
            {"side_id": s["side_id"], "label": s["label"],
             "subject": s["fact"]["subject"], "predicate": s["fact"]["predicate"],
             "object_raw": s["fact"]["object_raw"],
             "lifecycle_status": s["fact"].get("qualifiers", {}).get("lifecycle_status")}
            for s in sides
        ]
        user = (
            f"LANGUAGE: {language}\nSUBJECT: {cs.get('comparison_subject', '')}\n"
            f"RELATION: {json.dumps(cs.get('relation', {}), ensure_ascii=False)}\n"
            f"PREFERRED: {cs.get('preferred_answer_basis')}\n"
            f"SIDES:\n{json.dumps(sides_compact, ensure_ascii=False, indent=2)}\n\n"
            "Compose a short comparative answer. Output JSON only."
        )
        try:
            meta = self.llm.chat_completion_with_meta(
                messages=[{"role": "system", "content": SYSTEM_PROMPT_COMPOSER},
                          {"role": "user", "content": user}],
                temperature=0.05, max_tokens=900, json_mode=True, timeout=30.0,
                model_override=self.model_override,
            )
        except Exception as exc:
            return self._fallback(sides, cs.get("relation", {}), language, t0, str(exc))
        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._fallback(sides, cs.get("relation", {}), language, t0, f"json_parse: {exc}")
        answer = str(parsed.get("answer_text") or "").strip()
        ss = parsed.get("sentence_support") or []
        if not answer or not isinstance(ss, list):
            return self._fallback(sides, cs.get("relation", {}), language, t0, "missing_fields")
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

    def _fallback(self, sides, relation, language, t0, parse_error):
        rel_type = relation.get("type", "different")
        intro = (f"Comparaison ({rel_type}) :" if language.startswith("fr") else f"Comparison ({rel_type}):")
        lines = [intro]
        ss = [{"sentence_index": 0, "text": intro, "support_ids": [s["side_id"] for s in sides]}]
        for idx, s in enumerate(sides, 1):
            line = f"- {s['label']} ({s['side_id']}): {s['fact']['predicate']} {s['fact']['object_raw']}"
            lines.append(line)
            ss.append({"sentence_index": idx, "text": line, "support_ids": [s["side_id"]]})
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


class Channel1ComparisonVerifier:
    def verify(self, question: str, facts_first: dict, composer_output: Optional[dict] = None) -> VerifierReport:
        report = VerifierReport(passed=True)
        for f in REQUIRED_COMMON:
            if f not in facts_first:
                report.add(VerifierIssue("schema.common.missing_field", SEVERITY_ERROR, f"Missing '{f}'"))
        if facts_first.get("schema_version") != "facts_first_v1":
            report.add(VerifierIssue("schema.common.bad_version", SEVERITY_ERROR, ""))
        if facts_first.get("primary_type") != "comparison":
            report.add(VerifierIssue("schema.common.bad_primary_type", SEVERITY_ERROR, ""))
        cs = facts_first.get("comparison_specific") or {}
        for f in ("comparison_subject", "compared_facts", "relation"):
            if f not in cs:
                report.add(VerifierIssue("schema.comparison.missing_field", SEVERITY_ERROR, f"missing '{f}'"))

        sides = cs.get("compared_facts") or []
        seen: set[str] = set()
        for idx, s in enumerate(sides):
            if not isinstance(s, dict):
                report.add(VerifierIssue("comparison.side.not_object", SEVERITY_ERROR, f"side[{idx}]"))
                continue
            sid = s.get("side_id")
            if sid:
                if sid in seen:
                    report.add(VerifierIssue("comparison.side.duplicate_id", SEVERITY_ERROR, f"dup {sid}"))
                seen.add(sid)
            src = s.get("source") or {}
            if len((src.get("quote") or "").strip()) < MIN_QUOTE_CHARS:
                report.add(VerifierIssue("comparison.side.source.quote_too_short", SEVERITY_ERROR,
                                         f"side[{idx}].source.quote", context={"side_id": sid}))
            if not src.get("doc_id"):
                report.add(VerifierIssue("comparison.side.source.missing_doc_id", SEVERITY_ERROR,
                                         f"side[{idx}].source", context={"side_id": sid}))

        if facts_first.get("answerability") == "answerable" and len(sides) < 2:
            report.add(VerifierIssue("comparison.answerable_but_too_few_sides", SEVERITY_ERROR,
                                     f"answerable but only {len(sides)} sides"))

        if composer_output is not None:
            ss = composer_output.get("sentence_support") or []
            unknown: set[str] = set()
            for s in ss:
                for sid in (s or {}).get("support_ids") or []:
                    if isinstance(sid, str) and sid not in seen:
                        unknown.add(sid)
            if unknown:
                report.add(VerifierIssue("composer.support_ids.unknown", SEVERITY_ERROR,
                                         f"unknown side_ids: {sorted(unknown)[:5]}"))

        question_ids = {m.group(0).lower().strip() for m in IDENTIFIER_HEURISTIC_RE.finditer(question)}
        if question_ids:
            haystack = " ".join(
                [str(s.get("label", "")) + " " + str(s.get("fact", {}).get("object_raw", ""))
                 + " " + str((s.get("source") or {}).get("quote", "")) for s in sides]
            )
            if composer_output:
                haystack += " " + (composer_output.get("answer_text") or "")
            haystack_ids = {m.group(0).lower().strip() for m in IDENTIFIER_HEURISTIC_RE.finditer(haystack)}
            missing = question_ids - haystack_ids
            if missing:
                report.add(VerifierIssue("identifier.missing_in_response", SEVERITY_WARNING,
                                         f"missing: {sorted(missing)}"))
        return report


_default_structurer: Optional[ComparisonStructurer] = None
_default_composer: Optional[ComparisonComposer] = None
_default_verifier: Optional[Channel1ComparisonVerifier] = None


def get_comparison_structurer():
    global _default_structurer
    if _default_structurer is None:
        _default_structurer = ComparisonStructurer()
    return _default_structurer


def get_comparison_composer():
    global _default_composer
    if _default_composer is None:
        _default_composer = ComparisonComposer()
    return _default_composer


def get_comparison_verifier():
    global _default_verifier
    if _default_verifier is None:
        _default_verifier = Channel1ComparisonVerifier()
    return _default_verifier
