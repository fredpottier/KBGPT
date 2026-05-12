"""
OSMOSIS V4 — Tranche 3 Temporal pipeline (CH-41 T3).

3 composants compacts pour les questions temporelles (succession, lifecycle,
version chronology) : TemporalStructurer + TemporalComposer + Channel1TemporalVerifier.

Pattern réutilisé du Tranche 2 factual. Schéma figé : facts_first_v1_temporal.json.
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


SYSTEM_PROMPT_STRUCTURER = """You extract a TEMPORAL TIMELINE for the user's question, strictly grounded in the evidence pool.

Output JSON ONLY:
{
  "subject": "<temporal subject (e.g. 'EU dual-use Annex I', 'CS-25 impact energy requirement')>",
  "timeline": [
    {
      "event_id": "T1",
      "time_anchor": {
        "raw": "<verbatim ('Amendment 26', '20 May 2021', 'v3.2')>",
        "normalized": "<ISO date or normalized string or null>",
        "kind": "date | version | unknown"
      },
      "state": {
        "status": "ACTIVE | DEPRECATED | UNKNOWN",
        "predicate": "<short predicate (e.g. 'set required impact energy to')>",
        "value": "<verbatim value>"
      },
      "change_type": "added | removed | changed | unknown",
      "source": {
        "doc_id": "...", "claim_id": "...", "chunk_id": null, "page_no": null, "section_id": null,
        "quote": "<≥10 chars verbatim quote from evidence>"
      },
      "confidence": <0-1>
    }
  ],
  "current_basis": {"event_id": "T?", "reason": "<why this event is the 'current' one>"}
}

RULES:
1. Each event MUST be supported by a verbatim quote actually in the EVIDENCE POOL.
2. time_anchor.raw is verbatim from the source.
3. state.value verbatim.
4. Timeline ordered chronologically when possible.
5. current_basis points to the latest ACTIVE event (or null if no clear current state).
6. If no temporal evidence found → timeline=[].

Return only the JSON object."""


SYSTEM_PROMPT_COMPOSER = """You produce a short prose answer for a TEMPORAL question from a structured timeline.
Output JSON ONLY:
{"answer_text": "<2-5 sentences>", "sentence_support": [{"sentence_index": 0, "text": "...", "support_ids": ["T1"]}]}

Rules:
- Use the timeline events VERBATIM (state.value, time_anchor.raw).
- Mention current_basis if present (the answer should highlight the current state).
- If timeline empty: "La réponse à votre question n'a pas été trouvée dans les documents disponibles." (or English).
- DO NOT invent dates/versions."""


@dataclass
class StructurerResult:
    facts_first_json: dict
    raw_llm_output: str = ""
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    parse_error: Optional[str] = None
    rejected_events: list[dict] = field(default_factory=list)


@dataclass
class ComposerResult:
    answer_text: str
    sentence_support: list[dict]
    language: str = "en"
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    parse_error: Optional[str] = None
    format: str = "temporal_prose"
    raw_llm_output: str = ""

    def to_dict(self) -> dict:
        return {"answer_text": self.answer_text, "sentence_support": self.sentence_support,
                "language": self.language, "format": self.format}


def _quote_grounded(quote: str, pool_quotes_norm) -> bool:
    q_norm = " ".join(quote.lower().split())
    if len(q_norm) < MIN_QUOTE_CHARS:
        return False
    for _, pool_q in pool_quotes_norm:
        if q_norm in pool_q or pool_q in q_norm:
            return True
    item_tokens = set(t for t in q_norm.split() if len(t) > 3)
    if not item_tokens:
        return False
    for _, pool_q in pool_quotes_norm:
        pool_tokens = set(t for t in pool_q.split() if len(t) > 3)
        if pool_tokens and len(item_tokens & pool_tokens) / max(1, len(item_tokens)) >= 0.5:
            return True
    return False


class TemporalStructurer:
    def __init__(
        self,
        llm: Optional[RuntimeLLMClient] = None,
        max_events: int = 12,
        top_evidence: int = DEFAULT_TOP_EVIDENCE,
        temperature: float = 0.05,
        max_tokens: int = 1800,  # CH-46 L6 : 2500→1800
        timeout: float = 120.0,
    ) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.max_events = max_events
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
            f"EV{i} | doc={c.doc_id} | claim={c.claim_id or c.chunk_id or '?'} "
            f"| date={c.publication_date or 'n/a'} | quote: {(c.quote or '')[:400]}"
            for i, c in enumerate(ev_pool, 1)
        )
        feedback_section = f"\n\nPREVIOUS ATTEMPT FEEDBACK:\n{feedback_for_retry[:600]}\n" if feedback_for_retry else ""
        user_prompt = (
            f"QUESTION (language={language}): {question.strip()}\n\n"
            f"EVIDENCE POOL ({len(ev_pool)} candidates):\n{evidence_block}{feedback_section}\n\n"
            "Build a temporal timeline. Output JSON only."
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
            logger.warning("TemporalStructurer LLM failed: %s", exc)
            r = self._empty(question, evidence, language, domain_pack, tenant_id, f"llm_error: {exc}", t0)
            r.parse_error = str(exc)
            return r

        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            r = self._empty(question, evidence, language, domain_pack, tenant_id, "json_parse_error", t0)
            r.parse_error = f"json_parse: {exc}"; r.raw_llm_output = raw[:600]
            return r

        validated, rejected = self._validate(parsed.get("timeline", []), ev_pool)
        ff = {
            "schema_version": SCHEMA_VERSION, "primary_type": "temporal", "secondary_type": None,
            "answerability": "answerable" if validated else "unanswerable",
            "coverage_state": "partial" if validated else "unknown",
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": f"{meta.get('model') or 'unknown'}@{meta.get('provider') or 'unknown'}",
            "tenant_id": tenant_id, "domain_pack": domain_pack,
            "temporal_specific": {
                "subject": str(parsed.get("subject") or "")[:200] or "subject",
                "timeline": validated,
                "current_basis": parsed.get("current_basis"),
            },
            "diagnostic": {
                "latency_ms": int((time.time() - t0) * 1000),
                "evidence_count": len(ev_pool),
                "rejected_events_count": len(rejected),
            },
        }
        return StructurerResult(
            facts_first_json=ff, raw_llm_output=raw[:600],
            latency_ms=int((time.time() - t0) * 1000),
            model=meta.get("model", ""), provider=meta.get("provider", ""),
            rejected_events=rejected,
        )

    def _validate(self, raw_events, ev_pool):
        valid: list[dict] = []
        rejected: list[dict] = []
        pool_norm = [(c, " ".join((c.quote or "").lower().split())) for c in ev_pool]
        seen: set[str] = set()
        for raw in (raw_events or [])[: self.max_events]:
            if not isinstance(raw, dict):
                rejected.append({"reason": "not_object"}); continue
            ta = raw.get("time_anchor") or {}
            ta_raw = str(ta.get("raw") or "").strip()
            st = raw.get("state") or {}
            st_value = str(st.get("value") or "").strip()
            st_predicate = str(st.get("predicate") or "").strip()
            src = raw.get("source") or {}
            quote = str(src.get("quote") or "").strip()
            if not ta_raw or not st_predicate or not quote:
                rejected.append({"reason": "missing_field"}); continue
            if len(quote) < MIN_QUOTE_CHARS:
                rejected.append({"reason": "quote_too_short"}); continue
            if not _quote_grounded(quote, pool_norm):
                rejected.append({"reason": "quote_not_grounded"}); continue
            key = (ta_raw.lower(), st_value.lower())
            if key in seen:
                rejected.append({"reason": "duplicate"}); continue
            seen.add(key)
            try:
                conf = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
            except (TypeError, ValueError):
                conf = 0.5
            valid.append({
                "event_id": f"T{len(valid) + 1}",
                "time_anchor": {
                    "raw": ta_raw[:200],
                    "normalized": ta.get("normalized"),
                    "kind": str(ta.get("kind") or "unknown")[:30],
                },
                "state": {
                    "status": str(st.get("status") or "UNKNOWN")[:30],
                    "predicate": st_predicate[:200],
                    "value": st_value[:500],
                },
                "change_type": str(raw.get("change_type") or "unknown")[:30],
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
        return valid, rejected

    def _empty(self, question, evidence, language, domain_pack, tenant_id, reason, t0):
        ff = {
            "schema_version": SCHEMA_VERSION, "primary_type": "temporal", "secondary_type": None,
            "answerability": "unanswerable", "coverage_state": "unknown",
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": "none@none",
            "tenant_id": tenant_id, "domain_pack": domain_pack,
            "temporal_specific": {"subject": "subject", "timeline": [], "current_basis": None},
            "diagnostic": {"latency_ms": int((time.time() - t0) * 1000),
                           "evidence_count": len(evidence.claims), "reason": reason},
        }
        return StructurerResult(facts_first_json=ff, latency_ms=int((time.time() - t0) * 1000))


class TemporalComposer:
    def __init__(self, llm: Optional[RuntimeLLMClient] = None,
                 model_override: Optional[str] = None) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.model_override = model_override or "google/gemma-3-12b-it"

    def compose(self, facts_first: dict) -> ComposerResult:
        t0 = time.time()
        language = (facts_first.get("language") or "en").lower()
        ts = facts_first.get("temporal_specific") or {}
        timeline = ts.get("timeline") or []
        if not timeline:
            msg = ("La réponse à votre question n'a pas été trouvée dans les documents disponibles."
                   if language.startswith("fr") else
                   "The answer to your question was not found in the available documents.")
            return ComposerResult(
                answer_text=msg,
                sentence_support=[{"sentence_index": 0, "text": msg, "support_ids": []}],
                language=language, latency_ms=int((time.time() - t0) * 1000),
                model="deterministic", provider="local",
            )

        events_compact = [
            {"event_id": e["event_id"],
             "time_raw": e["time_anchor"]["raw"],
             "status": e["state"]["status"],
             "predicate": e["state"]["predicate"],
             "value": e["state"]["value"],
             "change_type": e.get("change_type")}
            for e in timeline
        ]
        user = (
            f"LANGUAGE: {language}\nSUBJECT: {ts.get('subject', '')}\n"
            f"CURRENT_BASIS: {ts.get('current_basis')}\n"
            f"TIMELINE:\n{json.dumps(events_compact, ensure_ascii=False, indent=2)}\n\n"
            "Compose a short temporal answer. Output JSON only."
        )
        try:
            meta = self.llm.chat_completion_with_meta(
                messages=[{"role": "system", "content": SYSTEM_PROMPT_COMPOSER},
                          {"role": "user", "content": user}],
                temperature=0.05, max_tokens=900, json_mode=True, timeout=30.0,
                model_override=self.model_override,
            )
        except Exception as exc:
            return self._fallback(timeline, ts.get("subject", ""), language, t0, str(exc))
        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._fallback(timeline, ts.get("subject", ""), language, t0, f"json_parse: {exc}")

        answer = str(parsed.get("answer_text") or "").strip()
        ss = parsed.get("sentence_support") or []
        if not answer or not isinstance(ss, list):
            return self._fallback(timeline, ts.get("subject", ""), language, t0, "missing_fields")

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

    def _fallback(self, timeline, subject, language, t0, parse_error):
        intro = f"Évolution chronologique de {subject} :" if language.startswith("fr") else f"Chronological evolution of {subject}:"
        lines = [intro]
        ss = [{"sentence_index": 0, "text": intro, "support_ids": [e["event_id"] for e in timeline]}]
        for idx, e in enumerate(timeline, 1):
            line = f"- {e['time_anchor']['raw']} : {e['state']['predicate']} {e['state']['value']} ({e['state']['status']})"
            lines.append(line)
            ss.append({"sentence_index": idx, "text": line, "support_ids": [e["event_id"]]})
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


class Channel1TemporalVerifier:
    def verify(self, question: str, facts_first: dict, composer_output: Optional[dict] = None) -> VerifierReport:
        report = VerifierReport(passed=True)
        for f in REQUIRED_COMMON:
            if f not in facts_first:
                report.add(VerifierIssue("schema.common.missing_field", SEVERITY_ERROR, f"Missing '{f}'"))
        if facts_first.get("schema_version") != "facts_first_v1":
            report.add(VerifierIssue("schema.common.bad_version", SEVERITY_ERROR, "schema_version"))
        if facts_first.get("primary_type") != "temporal":
            report.add(VerifierIssue("schema.common.bad_primary_type", SEVERITY_ERROR, f"primary_type"))
        ts = facts_first.get("temporal_specific") or {}
        for f in ("subject", "timeline"):
            if f not in ts:
                report.add(VerifierIssue("schema.temporal.missing_field", SEVERITY_ERROR, f"missing '{f}'"))

        timeline = ts.get("timeline") or []
        seen: set[str] = set()
        for idx, e in enumerate(timeline):
            if not isinstance(e, dict):
                report.add(VerifierIssue("temporal.event.not_object", SEVERITY_ERROR, f"event[{idx}]"))
                continue
            eid = e.get("event_id")
            if eid:
                if eid in seen:
                    report.add(VerifierIssue("temporal.event.duplicate_id", SEVERITY_ERROR, f"dup {eid}"))
                seen.add(eid)
            src = e.get("source") or {}
            if len((src.get("quote") or "").strip()) < MIN_QUOTE_CHARS:
                report.add(VerifierIssue("temporal.event.source.quote_too_short", SEVERITY_ERROR,
                                         f"event[{idx}].source.quote", context={"event_id": eid}))
            if not src.get("doc_id"):
                report.add(VerifierIssue("temporal.event.source.missing_doc_id", SEVERITY_ERROR,
                                         f"event[{idx}].source", context={"event_id": eid}))

        if facts_first.get("answerability") == "answerable" and not timeline:
            report.add(VerifierIssue("temporal.answerable_but_empty", SEVERITY_ERROR, "empty timeline"))

        if composer_output is not None:
            ss = composer_output.get("sentence_support") or []
            unknown: set[str] = set()
            for s in ss:
                for sid in (s or {}).get("support_ids") or []:
                    if isinstance(sid, str) and sid not in seen:
                        unknown.add(sid)
            if unknown:
                report.add(VerifierIssue("composer.support_ids.unknown", SEVERITY_ERROR,
                                         f"unknown event_ids: {sorted(unknown)[:5]}"))

        # Identifier match heuristique
        question_ids = {m.group(0).lower().strip() for m in IDENTIFIER_HEURISTIC_RE.finditer(question)}
        if question_ids:
            haystack = " ".join(
                [str(e.get("time_anchor", {}).get("raw", "")) + " " + str(e.get("state", {}).get("value", ""))
                 + " " + str((e.get("source") or {}).get("quote", "")) for e in timeline]
            )
            if composer_output:
                haystack += " " + (composer_output.get("answer_text") or "")
            haystack_ids = {m.group(0).lower().strip() for m in IDENTIFIER_HEURISTIC_RE.finditer(haystack)}
            missing = question_ids - haystack_ids
            if missing:
                report.add(VerifierIssue("identifier.missing_in_response", SEVERITY_WARNING,
                                         f"identifiers missing: {sorted(missing)}"))
        return report


_default_structurer: Optional[TemporalStructurer] = None
_default_composer: Optional[TemporalComposer] = None
_default_verifier: Optional[Channel1TemporalVerifier] = None


def get_temporal_structurer():
    global _default_structurer
    if _default_structurer is None:
        _default_structurer = TemporalStructurer()
    return _default_structurer


def get_temporal_composer():
    global _default_composer
    if _default_composer is None:
        _default_composer = TemporalComposer()
    return _default_composer


def get_temporal_verifier():
    global _default_verifier
    if _default_verifier is None:
        _default_verifier = Channel1TemporalVerifier()
    return _default_verifier
