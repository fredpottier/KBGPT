"""
OSMOSIS V4 — Channel 1 Factual Verifier (CH-41 Tranche 2 factual).

Vérifications déterministes (pas de LLM) sur le pipeline factual :
  C1. Schema integrity facts_first_v1 factual.
  C2. Fact integrity (fact_id unique, source.quote ≥10 chars, source.doc_id présent,
       object.raw substring of source.quote).
  C3. Composer mapping (sentence_support[support_ids] référencent facts existants).
  C4. direct_answer_fact_ids ⊆ facts[].fact_id et non-vide si answerable.
  C5. Identifier exact-match (heuristique préfixée — réutilise list_verifier).
  C6. Lifecycle status valide (ACTIVE | DEPRECATED | UNKNOWN ou string Domain Pack).

Repair policy D-FF7 :
  - error → reject
  - warning → keep, log
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from knowbase.facts_first.list_verifier import (
    IDENTIFIER_HEURISTIC_RE,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    VerifierIssue,
    VerifierReport,
)


REQUIRED_COMMON_FIELDS = (
    "schema_version", "primary_type", "answerability", "coverage_state",
    "language", "extracted_at", "extraction_model",
)
REQUIRED_FACTUAL_FIELDS = ("facts", "direct_answer_fact_ids")
REQUIRED_FACT_FIELDS = ("fact_id", "subject", "predicate", "object", "source", "confidence")
REQUIRED_OBJECT_FIELDS = ("raw",)


class Channel1FactualVerifier:
    """Vérifier déterministe pour le pipeline Tranche 2 factual."""

    def verify(
        self,
        question: str,
        facts_first: dict,
        composer_output: Optional[dict] = None,
    ) -> VerifierReport:
        report = VerifierReport(passed=True)

        # C1 — Schema common
        self._check_common(facts_first, report)
        factual_specific = facts_first.get("factual_specific") or {}
        # Schema factual
        for f in REQUIRED_FACTUAL_FIELDS:
            if f not in factual_specific:
                report.add(VerifierIssue(
                    code="schema.factual.missing_field",
                    severity=SEVERITY_ERROR,
                    message=f"factual_specific missing field '{f}'",
                ))

        facts = factual_specific.get("facts") or []
        direct_ids = factual_specific.get("direct_answer_fact_ids") or []

        # C2 — Fact integrity
        fact_ids = self._check_facts(facts, report)

        # C4 — direct_answer_fact_ids ⊆ facts
        for did in direct_ids:
            if did not in fact_ids:
                report.add(VerifierIssue(
                    code="factual.direct_answer.unknown_id",
                    severity=SEVERITY_ERROR,
                    message=f"direct_answer_fact_ids contains unknown id {did!r}",
                ))
        if facts and not direct_ids and facts_first.get("answerability") == "answerable":
            report.add(VerifierIssue(
                code="factual.direct_answer.empty",
                severity=SEVERITY_WARNING,
                message="answerability=answerable but direct_answer_fact_ids is empty",
            ))

        # Coverage / answerability coherence
        ans = facts_first.get("answerability")
        if ans == "answerable" and not facts:
            report.add(VerifierIssue(
                code="factual.answerable_but_empty",
                severity=SEVERITY_ERROR,
                message="answerability=answerable but facts is empty",
            ))

        # C3 — Composer mapping
        if composer_output is not None:
            self._check_composer_mapping(composer_output, fact_ids, report)

        # C5 — Identifier match (warning only)
        self._check_identifier_match(question, facts, composer_output, report)

        return report

    # ------------------------------------------------------------------ C1

    def _check_common(self, ff: dict, report: VerifierReport) -> None:
        for f in REQUIRED_COMMON_FIELDS:
            if f not in ff:
                report.add(VerifierIssue(
                    code="schema.common.missing_field",
                    severity=SEVERITY_ERROR,
                    message=f"Missing common field '{f}'",
                ))
        if ff.get("schema_version") != "facts_first_v1":
            report.add(VerifierIssue(
                code="schema.common.bad_version",
                severity=SEVERITY_ERROR,
                message=f"schema_version must be 'facts_first_v1'",
            ))
        if ff.get("primary_type") != "factual":
            report.add(VerifierIssue(
                code="schema.common.bad_primary_type",
                severity=SEVERITY_ERROR,
                message=f"primary_type must be 'factual', got {ff.get('primary_type')!r}",
            ))
        if ff.get("answerability") not in ("answerable", "partial", "unanswerable", "false_premise"):
            report.add(VerifierIssue(
                code="schema.common.bad_answerability",
                severity=SEVERITY_ERROR,
                message=f"Invalid answerability {ff.get('answerability')!r}",
            ))
        if ff.get("coverage_state") not in ("complete", "partial", "unknown", "not_applicable"):
            report.add(VerifierIssue(
                code="schema.common.bad_coverage_state",
                severity=SEVERITY_ERROR,
                message=f"Invalid coverage_state {ff.get('coverage_state')!r}",
            ))

    # ------------------------------------------------------------------ C2

    def _check_facts(self, facts: list, report: VerifierReport) -> set[str]:
        seen: set[str] = set()
        for idx, f in enumerate(facts):
            if not isinstance(f, dict):
                report.add(VerifierIssue(
                    code="factual.fact.not_object",
                    severity=SEVERITY_ERROR,
                    message=f"facts[{idx}] is not an object",
                ))
                continue
            for req in REQUIRED_FACT_FIELDS:
                if req not in f:
                    report.add(VerifierIssue(
                        code="factual.fact.missing_field",
                        severity=SEVERITY_ERROR,
                        message=f"facts[{idx}] missing field '{req}'",
                    ))
            fid = f.get("fact_id")
            if fid:
                if fid in seen:
                    report.add(VerifierIssue(
                        code="factual.fact.duplicate_id",
                        severity=SEVERITY_ERROR,
                        message=f"duplicate fact_id {fid!r}",
                    ))
                seen.add(fid)
            obj = f.get("object") or {}
            for req in REQUIRED_OBJECT_FIELDS:
                if req not in obj:
                    report.add(VerifierIssue(
                        code="factual.fact.object.missing_field",
                        severity=SEVERITY_ERROR,
                        message=f"facts[{idx}].object missing '{req}'",
                    ))
            obj_raw = str(obj.get("raw") or "")
            src = f.get("source") or {}
            quote = str(src.get("quote") or "")
            if len(quote.strip()) < 10:
                report.add(VerifierIssue(
                    code="factual.fact.source.quote_too_short",
                    severity=SEVERITY_ERROR,
                    message=f"facts[{idx}].source.quote < 10 chars",
                    context={"fact_id": fid},
                ))
            if not src.get("doc_id"):
                report.add(VerifierIssue(
                    code="factual.fact.source.missing_doc_id",
                    severity=SEVERITY_ERROR,
                    message=f"facts[{idx}].source missing doc_id",
                    context={"fact_id": fid},
                ))
            # Object.raw doit apparaître dans la quote (ou paraphrase courte autorisée)
            if obj_raw and quote and obj_raw.lower() not in quote.lower():
                # Tolérance : tokens > 1 char tous dans la quote
                tokens = [t for t in obj_raw.lower().split() if len(t) > 1]
                if tokens and not all(t in quote.lower() for t in tokens):
                    report.add(VerifierIssue(
                        code="factual.fact.object.raw_not_in_quote",
                        severity=SEVERITY_WARNING,
                        message=f"facts[{idx}].object.raw not literally in source.quote",
                        context={"fact_id": fid, "raw": obj_raw[:80], "quote": quote[:120]},
                    ))
            try:
                conf = float(f.get("confidence", 0.0))
                if not (0.0 <= conf <= 1.0):
                    raise ValueError()
            except (TypeError, ValueError):
                report.add(VerifierIssue(
                    code="factual.fact.confidence.invalid",
                    severity=SEVERITY_WARNING,
                    message=f"facts[{idx}].confidence invalid",
                    context={"fact_id": fid},
                ))
            # Lifecycle status check (warning si valeur non-standard)
            qualifiers = f.get("qualifiers") or {}
            ls = qualifiers.get("lifecycle_status")
            if ls and ls not in ("ACTIVE", "DEPRECATED", "UNKNOWN"):
                # Domain Pack extension possible — info-level
                report.add(VerifierIssue(
                    code="factual.fact.lifecycle_status.domain_pack_value",
                    severity=SEVERITY_INFO,
                    message=f"lifecycle_status='{ls}' (Domain Pack extension)",
                    context={"fact_id": fid},
                ))
        return seen

    # ------------------------------------------------------------------ C3

    def _check_composer_mapping(
        self, composer_output: dict, fact_ids: set[str], report: VerifierReport
    ) -> None:
        ss = composer_output.get("sentence_support") or []
        if not isinstance(ss, list):
            report.add(VerifierIssue(
                code="composer.sentence_support.not_list",
                severity=SEVERITY_ERROR,
                message="sentence_support not a list",
            ))
            return
        unknown: set[str] = set()
        cited: set[str] = set()
        for s in ss:
            if not isinstance(s, dict):
                continue
            for sid in s.get("support_ids") or []:
                if not isinstance(sid, str):
                    continue
                if sid not in fact_ids:
                    unknown.add(sid)
                else:
                    cited.add(sid)
        if unknown:
            report.add(VerifierIssue(
                code="composer.support_ids.unknown",
                severity=SEVERITY_ERROR,
                message=f"sentence_support cites unknown fact_ids: {sorted(unknown)[:10]}",
            ))
        if fact_ids and not cited:
            report.add(VerifierIssue(
                code="composer.facts.uncited",
                severity=SEVERITY_WARNING,
                message="No fact cited by any sentence_support",
            ))

    # ------------------------------------------------------------------ C5

    def _check_identifier_match(
        self,
        question: str,
        facts: list,
        composer_output: Optional[dict],
        report: VerifierReport,
    ) -> None:
        question_ids = {self._normalize_id(m.group(0)) for m in IDENTIFIER_HEURISTIC_RE.finditer(question)}
        if not question_ids:
            return
        haystack = []
        for f in facts:
            haystack.append(f.get("subject") or "")
            obj = f.get("object") or {}
            haystack.append(str(obj.get("raw") or ""))
            haystack.append((f.get("source") or {}).get("quote") or "")
        if composer_output:
            haystack.append(composer_output.get("answer_text") or "")
        text = " ".join(haystack)
        haystack_ids = {self._normalize_id(m.group(0)) for m in IDENTIFIER_HEURISTIC_RE.finditer(text)}
        missing = question_ids - haystack_ids
        if missing:
            report.add(VerifierIssue(
                code="identifier.missing_in_response",
                severity=SEVERITY_WARNING,
                message=f"Question identifiers not echoed: {sorted(missing)}",
            ))

    @staticmethod
    def _normalize_id(s: str) -> str:
        return " ".join(s.lower().split())


_default: Optional[Channel1FactualVerifier] = None


def get_factual_verifier() -> Channel1FactualVerifier:
    global _default
    if _default is None:
        _default = Channel1FactualVerifier()
    return _default


def reset_factual_verifier() -> None:
    global _default
    _default = None
