"""
OSMOSIS V4 — Channel 1 List Verifier (composant [E1], CH-41.3, Tranche 1 list).

Vérifications déterministes (PAS de LLM) sur le pipeline list :
  C1. Schema integrity facts_first_v1 list (champs requis, types).
  C2. Item integrity (item_id unique, source.quote ≥ 10 chars, source.doc_id présent).
  C3. Composer mapping (sentence_support[support_ids] référencent des item_id existants).
  C4. Coverage_state cohérent avec items.length et expected_exhaustive.
  C5. Identifier exact-match (si la question contient un identifier explicite, il
      doit apparaître dans au moins un item.label OR la réponse).

Output VerifierReport :
  - passed: bool
  - issues: list[VerifierIssue]
  - severity: max severity (info | warning | error)

Repair policy (D-FF7) :
  - error → reject (caller retry ou fallback)
  - warning → keep, log
  - info → keep
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional


SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
_SEV_ORDER = {SEVERITY_INFO: 0, SEVERITY_WARNING: 1, SEVERITY_ERROR: 2}


# Regex domain-agnostic pour extraire des "identifiers" candidats du texte
# (CS XX.YYY, EU YYYY/NNN, NPA YYYY-NN, Annex N, Article N)
IDENTIFIER_HEURISTIC_RE = re.compile(
    r"\b("
    r"(?:CS|EN|EASA|FAA|ED)[-\s]?\d{1,4}(?:\.\d{1,4}){0,2}"  # CS 25.788, ED 2024/021
    r"|(?:EU|UE|EC|EEC|REG)[\s]?\d{2,4}/\d{2,4}"            # EU 2021/821, REG 428/2009
    r"|\d{4}/\d{2,4}"                                       # 2021/821
    r"|NPA[-\s]?\d{4}-\d{2}"                                # NPA 2018-05
    r"|Annex(?:e)?\s+[IVX]+|Annexe?\s+\d+"                  # Annex I, Annexe 1
    r"|Article\s+\d+"                                       # Article 8
    r")\b",
    re.IGNORECASE,
)


@dataclass
class VerifierIssue:
    code: str
    severity: str
    message: str
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message, "context": self.context}


@dataclass
class VerifierReport:
    passed: bool
    issues: list[VerifierIssue] = field(default_factory=list)
    severity: str = SEVERITY_INFO

    def add(self, issue: VerifierIssue) -> None:
        self.issues.append(issue)
        if _SEV_ORDER[issue.severity] > _SEV_ORDER[self.severity]:
            self.severity = issue.severity
        if issue.severity == SEVERITY_ERROR:
            self.passed = False

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "severity": self.severity,
            "issues": [i.to_dict() for i in self.issues],
        }


REQUIRED_COMMON_FIELDS = (
    "schema_version", "primary_type", "answerability", "coverage_state",
    "language", "extracted_at", "extraction_model",
)
REQUIRED_LIST_FIELDS = ("list_subject", "items", "enumeration_quality")
REQUIRED_QUALITY_FIELDS = ("expected_exhaustive", "coverage_state", "evidence_count", "deduped_count")
REQUIRED_ITEM_FIELDS = ("item_id", "label", "source", "confidence")


class Channel1ListVerifier:
    """Vérifier déterministe pour le pipeline Tranche 1 list."""

    def verify(
        self,
        question: str,
        facts_first: dict,
        composer_output: Optional[dict] = None,
    ) -> VerifierReport:
        report = VerifierReport(passed=True)

        # C1 — Schema integrity
        self._check_common_schema(facts_first, report)
        list_specific = facts_first.get("list_specific") or {}
        self._check_list_schema(list_specific, report)

        items = list_specific.get("items") or []
        # C2 — Item integrity
        item_ids = self._check_items(items, report)

        # C4 — Coverage state coherence
        self._check_coverage_coherence(facts_first, list_specific, items, report)

        # C5 — Identifier exact-match (si question contient un identifier explicite)
        self._check_identifier_match(question, items, composer_output, report)

        # C3 — Composer mapping (uniquement si composer_output fourni)
        if composer_output is not None:
            self._check_composer_mapping(composer_output, item_ids, report)

        return report

    # ------------------------------------------------------------------ C1

    def _check_common_schema(self, ff: dict, report: VerifierReport) -> None:
        for f in REQUIRED_COMMON_FIELDS:
            if f not in ff:
                report.add(VerifierIssue(
                    code="schema.common.missing_field",
                    severity=SEVERITY_ERROR,
                    message=f"Missing common field '{f}'",
                    context={"field": f},
                ))
        if ff.get("schema_version") != "facts_first_v1":
            report.add(VerifierIssue(
                code="schema.common.bad_version",
                severity=SEVERITY_ERROR,
                message=f"schema_version must be 'facts_first_v1', got {ff.get('schema_version')!r}",
            ))
        if ff.get("primary_type") != "list":
            report.add(VerifierIssue(
                code="schema.common.bad_primary_type",
                severity=SEVERITY_ERROR,
                message=f"primary_type must be 'list', got {ff.get('primary_type')!r}",
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

    def _check_list_schema(self, ls: dict, report: VerifierReport) -> None:
        for f in REQUIRED_LIST_FIELDS:
            if f not in ls:
                report.add(VerifierIssue(
                    code="schema.list.missing_field",
                    severity=SEVERITY_ERROR,
                    message=f"list_specific missing field '{f}'",
                ))
        eq = ls.get("enumeration_quality") or {}
        for f in REQUIRED_QUALITY_FIELDS:
            if f not in eq:
                report.add(VerifierIssue(
                    code="schema.list.quality.missing_field",
                    severity=SEVERITY_ERROR,
                    message=f"enumeration_quality missing '{f}'",
                ))

    # ------------------------------------------------------------------ C2

    def _check_items(self, items: list, report: VerifierReport) -> set[str]:
        seen_ids: set[str] = set()
        for idx, it in enumerate(items):
            if not isinstance(it, dict):
                report.add(VerifierIssue(
                    code="item.not_object",
                    severity=SEVERITY_ERROR,
                    message=f"item[{idx}] is not an object",
                ))
                continue
            for f in REQUIRED_ITEM_FIELDS:
                if f not in it:
                    report.add(VerifierIssue(
                        code="item.missing_field",
                        severity=SEVERITY_ERROR,
                        message=f"item[{idx}] missing field '{f}'",
                    ))
            iid = it.get("item_id")
            if iid:
                if iid in seen_ids:
                    report.add(VerifierIssue(
                        code="item.duplicate_id",
                        severity=SEVERITY_ERROR,
                        message=f"duplicate item_id {iid!r}",
                    ))
                seen_ids.add(iid)
            src = it.get("source") or {}
            quote = str(src.get("quote") or "")
            if len(quote.strip()) < 10:
                report.add(VerifierIssue(
                    code="item.source.quote_too_short",
                    severity=SEVERITY_ERROR,
                    message=f"item[{idx}].source.quote < 10 chars",
                    context={"item_id": iid},
                ))
            if not src.get("doc_id"):
                report.add(VerifierIssue(
                    code="item.source.missing_doc_id",
                    severity=SEVERITY_ERROR,
                    message=f"item[{idx}].source missing doc_id",
                    context={"item_id": iid},
                ))
            try:
                conf = float(it.get("confidence", 0.0))
                if not (0.0 <= conf <= 1.0):
                    raise ValueError("oor")
            except (TypeError, ValueError):
                report.add(VerifierIssue(
                    code="item.confidence.invalid",
                    severity=SEVERITY_WARNING,
                    message=f"item[{idx}].confidence not in [0,1]",
                    context={"item_id": iid, "value": it.get("confidence")},
                ))
        return seen_ids

    # ------------------------------------------------------------------ C3

    def _check_composer_mapping(
        self, composer_output: dict, item_ids: set[str], report: VerifierReport
    ) -> None:
        ss = composer_output.get("sentence_support") or []
        if not isinstance(ss, list):
            report.add(VerifierIssue(
                code="composer.sentence_support.not_list",
                severity=SEVERITY_ERROR,
                message="sentence_support is not a list",
            ))
            return
        unknown_ids: set[str] = set()
        cited_ids: set[str] = set()
        for s in ss:
            if not isinstance(s, dict):
                continue
            for sid in s.get("support_ids") or []:
                if not isinstance(sid, str):
                    continue
                if sid not in item_ids:
                    unknown_ids.add(sid)
                else:
                    cited_ids.add(sid)
        if unknown_ids:
            report.add(VerifierIssue(
                code="composer.support_ids.unknown",
                severity=SEVERITY_ERROR,
                message=f"sentence_support cites unknown item_ids: {sorted(unknown_ids)[:10]}",
            ))
        # Items pas cités du tout : warning (pas error — l'intro peut résumer)
        uncited = item_ids - cited_ids
        if uncited:
            report.add(VerifierIssue(
                code="composer.items.uncited",
                severity=SEVERITY_WARNING,
                message=f"{len(uncited)} item(s) not cited by any sentence_support",
                context={"uncited": sorted(uncited)[:10]},
            ))

    # ------------------------------------------------------------------ C4

    def _check_coverage_coherence(
        self, ff: dict, ls: dict, items: list, report: VerifierReport
    ) -> None:
        cs = ff.get("coverage_state")
        eq = ls.get("enumeration_quality") or {}
        eq_cs = eq.get("coverage_state")
        if cs and eq_cs and cs != eq_cs:
            report.add(VerifierIssue(
                code="coverage.mismatch",
                severity=SEVERITY_WARNING,
                message=f"coverage_state mismatch: common={cs}, list={eq_cs}",
            ))
        # deduped_count doit égaler len(items)
        deduped = eq.get("deduped_count")
        if isinstance(deduped, int) and deduped != len(items):
            report.add(VerifierIssue(
                code="coverage.deduped_count_mismatch",
                severity=SEVERITY_WARNING,
                message=f"deduped_count ({deduped}) != items.length ({len(items)})",
            ))
        # complete avec 0 items est incohérent
        if cs == "complete" and not items:
            report.add(VerifierIssue(
                code="coverage.complete_but_empty",
                severity=SEVERITY_ERROR,
                message="coverage_state=complete but items is empty",
            ))
        # answerable avec 0 items aussi
        if ff.get("answerability") == "answerable" and not items:
            report.add(VerifierIssue(
                code="answerability.answerable_but_empty",
                severity=SEVERITY_ERROR,
                message="answerability=answerable but items is empty",
            ))

    # ------------------------------------------------------------------ C5

    def _check_identifier_match(
        self,
        question: str,
        items: list,
        composer_output: Optional[dict],
        report: VerifierReport,
    ) -> None:
        question_ids = {self._normalize_id(m.group(0)) for m in IDENTIFIER_HEURISTIC_RE.finditer(question)}
        if not question_ids:
            return
        # Texte cumulé : labels + composer answer_text + sources.quote
        haystack_parts: list[str] = []
        for it in items:
            haystack_parts.append(it.get("label") or "")
            src = it.get("source") or {}
            haystack_parts.append(src.get("quote") or "")
        if composer_output:
            haystack_parts.append(composer_output.get("answer_text") or "")
        haystack = " ".join(haystack_parts)
        haystack_ids = {self._normalize_id(m.group(0)) for m in IDENTIFIER_HEURISTIC_RE.finditer(haystack)}
        missing = question_ids - haystack_ids
        if missing:
            # Severity warning : peut être OK si la question demande explicitement quelque chose
            # qui n'est PAS l'identifier (ex "List items in EU 2021/821" — l'EU 2021/821 est le scope, pas un item).
            # On signale sans bloquer.
            report.add(VerifierIssue(
                code="identifier.missing_in_response",
                severity=SEVERITY_WARNING,
                message=f"Question identifiers not echoed in response: {sorted(missing)}",
                context={"question_ids": sorted(question_ids), "haystack_ids": sorted(haystack_ids)},
            ))

    @staticmethod
    def _normalize_id(s: str) -> str:
        return " ".join(s.lower().split())


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_default_verifier: Optional[Channel1ListVerifier] = None


def get_list_verifier() -> Channel1ListVerifier:
    global _default_verifier
    if _default_verifier is None:
        _default_verifier = Channel1ListVerifier()
    return _default_verifier


def reset_list_verifier() -> None:
    global _default_verifier
    _default_verifier = None
