"""Comparison & Contradiction Operator (Cap2.E — CH-49 Phase 4).

Operator evidence-first pour les questions de COMPARAISON et de CONTRADICTION.

Pour T2 contradictions / différences entre versions / "X et Y sont-ils alignés".

Architecture (charte ADR §1, evidence-first PAS LLM-detector) :
  1. INTENT — LLM léger DeepSeek : {is_comparison, subjects, aspect}
  2. RETRIEVAL — Qdrant sur la question (top_k=20)
  3. CLUSTERING déterministe Python — group_by (subject_normalized, predicate_normalized)
     sur structured_form_json des claims
  4. DETECTION déterministe — clusters avec ≥2 claims aux objets différents = contradiction potentielle
  5. QUALIFIER LLM — décider la nature : lifecycle_evolution / scope_difference /
     genuine_conflict / no_contradiction (UNIQUEMENT sur clusters ambigus)
  6. FORMATTING — résultat avec evidence quotes

Charte :
  - Pas de regex métier, pas de keywords corpus-spécifiques
  - LLM-detector REJETÉ (Amendment 9 ADR, ChatGPT critique) — l'evidence cluster
    décide d'abord, le LLM ne fait que QUALIFIER les clusters trouvés
  - Domain-agnostic : raisonne sur structured_form_json générique (subject/predicate/object)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


INTENT_DETECTION_PROMPT = """You analyze user questions to determine if they ask for a COMPARISON between two subjects, or to detect a CONTRADICTION/INCONSISTENCY between sources.

Return JSON only :
{
  "is_comparison_or_contradiction": <bool>,
  "subjects": ["<list of subjects compared, 1 or 2 typically>"],
  "aspect": "<the dimension compared : value, date, scope, requirement...>",
  "expected_outcome": "comparison" | "contradiction_detection" | "alignment_check" | null,
  "confidence": <float 0-1>,
  "reason": "<one short sentence>"
}

Set is_comparison_or_contradiction=true if the question :
- compares two named entities/values/documents on a common axis
- asks if two sources agree/disagree
- asks for differences between versions or items
- asks to detect inconsistencies in available evidence

Set false for : factual lookup, lists, causal explanations, hypothetical, lifecycle resolution per se (use lifecycle_resolution instead).

Examples (abstract — placeholders <X>, <Y>, <ASPECT>):
- "Compare <X> and <Y> on <ASPECT>" → is_comparison=true, subjects=["<X>", "<Y>"], aspect="<ASPECT>"
- "Are <X> and <Y> aligned regarding <ASPECT>?" → is_comparison=true, expected_outcome="alignment_check"
- "Is there a contradiction between <X> and <Y>?" → is_comparison=true, expected_outcome="contradiction_detection"
- "What is the difference between <X> and <Y>?" → is_comparison=true, expected_outcome="comparison"
- "What is the value of <X>?" → is_comparison=false (factual)
- "Why was <X> repealed?" → is_comparison=false (causal)
"""


QUALIFIER_PROMPT = """You analyze a CLUSTER of fact claims that share the same SUBJECT and PREDICATE but have DIFFERENT OBJECTS, to qualify the type of divergence.

Inputs :
- The original user QUESTION
- A CLUSTER of 2+ claims with same (subject, predicate) but differing objects
- For each claim : object value, doc_id, evidence quote, publication_date if available

Output STRICT JSON :
{
  "divergence_type": "lifecycle_evolution" | "scope_difference" | "genuine_conflict" | "no_real_divergence",
  "explanation": "<one sentence on why>",
  "primary_claims": [<claim_indices that matter to answer>],
  "confidence": <float 0-1>
}

Divergence types :
- "lifecycle_evolution" : claims diverge because one supersedes/amends the other (different dates, normal evolution)
- "scope_difference" : claims diverge because they apply to different scopes/conditions (not contradictory)
- "genuine_conflict" : claims directly contradict on the same scope at the same time → this IS a contradiction
- "no_real_divergence" : the differing objects are actually compatible (e.g. one is more specific than the other)

Stay grounded in the cluster contents. Don't invent facts."""


# --- Helpers déterministes (clustering) ---

_NORMALIZE_RE = re.compile(r"\s+")


def _norm(text: Optional[str]) -> str:
    """Normalise pour clustering : lowercase + collapse whitespace + strip."""
    if not text:
        return ""
    return _NORMALIZE_RE.sub(" ", text.lower()).strip()


def _parse_structured(structured_json: Optional[str]) -> dict:
    if not structured_json:
        return {}
    if isinstance(structured_json, dict):
        return structured_json
    try:
        return json.loads(structured_json)
    except (json.JSONDecodeError, TypeError):
        return {}


@dataclass
class ClaimRecord:
    claim_id: str
    doc_id: str
    subject: str
    predicate: str
    object: str
    quote: str
    publication_date: Optional[str] = None


@dataclass
class DivergenceCluster:
    subject_norm: str
    predicate_norm: str
    claims: list[ClaimRecord] = field(default_factory=list)
    qualified: bool = False
    divergence_type: Optional[str] = None
    explanation: Optional[str] = None
    primary_claim_indices: list[int] = field(default_factory=list)


@dataclass
class ComparisonContradictionResult:
    triggered: bool
    answer: str = ""
    expected_outcome: Optional[str] = None
    n_clusters_analyzed: int = 0
    n_genuine_conflicts: int = 0
    divergences: list[dict] = field(default_factory=list)
    intent: dict = field(default_factory=dict)
    decision: str = "ABSTAIN"
    abstention_reason: Optional[str] = None
    fallback_path: str = "primary"
    latency_breakdown_ms: dict = field(default_factory=dict)


class ComparisonContradictionOperator:
    """Operator Cap2.E : evidence-first cluster + LLM qualifier."""

    DEEPSEEK_MODEL = "deepseek-ai/DeepSeek-V3.1"
    DEEPSEEK_BASE_URL = "https://api.together.xyz/v1"

    def __init__(
        self,
        evidence_collector: Any,
        timeout: float = 30.0,
        top_k: int = 20,
    ) -> None:
        self.evidence_collector = evidence_collector
        self.timeout = timeout
        self.top_k = top_k
        self.api_key = os.getenv("TOGETHER_API_KEY", "")

    # ---------------------------------------------------------------- Intent
    def detect_intent(self, question: str) -> dict:
        return self._llm_json(INTENT_DETECTION_PROMPT, f"Question: {question}", default={
            "is_comparison_or_contradiction": False,
            "subjects": [],
            "aspect": None,
            "expected_outcome": None,
            "confidence": 0.0,
            "reason": "intent_call_failed",
        })

    def qualify_cluster(self, question: str, cluster_payload: dict) -> dict:
        user = (
            f"QUESTION:\n{question}\n\n"
            f"CLUSTER:\n{json.dumps(cluster_payload, ensure_ascii=False, indent=2)}"
        )
        return self._llm_json(QUALIFIER_PROMPT, user, default={
            "divergence_type": "no_real_divergence",
            "explanation": "qualifier_call_failed",
            "primary_claims": [],
            "confidence": 0.0,
        })

    def _llm_json(self, system_prompt: str, user_msg: str, default: dict) -> dict:
        if not self.api_key:
            return default
        payload = {
            "model": self.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.0,
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=httpx.HTTPTransport(retries=0),
            ) as client:
                resp = client.post(
                    f"{self.DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload, headers=headers,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"ComparisonContradiction LLM call failed: {exc}")
            return default

    # ---------------------------------------------------- Clustering
    @staticmethod
    def _build_records(claims: list) -> list[ClaimRecord]:
        records = []
        for c in claims:
            structured_str = getattr(c, "structured_form_json", None)
            structured = _parse_structured(structured_str)
            subject = structured.get("subject", "")
            predicate = structured.get("predicate", "")
            obj = structured.get("object", "")
            if not (subject and predicate and obj):
                continue
            records.append(ClaimRecord(
                claim_id=getattr(c, "claim_id", ""),
                doc_id=getattr(c, "doc_id", ""),
                subject=subject,
                predicate=predicate,
                object=obj,
                quote=(getattr(c, "quote", "") or "")[:400],
                publication_date=getattr(c, "publication_date", None),
            ))
        return records

    @staticmethod
    def _cluster_by_subject_predicate(records: list[ClaimRecord]) -> list[list[ClaimRecord]]:
        """Group records by (subject_norm, predicate_norm). Return clusters with ≥2 distinct objects."""
        groups: dict[tuple[str, str], list[ClaimRecord]] = defaultdict(list)
        for r in records:
            key = (_norm(r.subject), _norm(r.predicate))
            groups[key].append(r)
        clusters: list[list[ClaimRecord]] = []
        for key, items in groups.items():
            distinct_objects = {_norm(it.object) for it in items}
            if len(items) >= 2 and len(distinct_objects) >= 2:
                clusters.append(items)
        return clusters

    # ---------------------------------------------------------- Formatting
    @staticmethod
    def _format_answer(divergences: list[DivergenceCluster]) -> str:
        if not divergences:
            return "Aucune divergence factuelle détectée dans les preuves disponibles."
        lines = []
        n_genuine = sum(1 for d in divergences if d.divergence_type == "genuine_conflict")
        if n_genuine:
            lines.append(
                f"{n_genuine} contradiction(s) factuelle(s) identifiée(s) "
                f"sur {len(divergences)} divergence(s) analysée(s) :"
            )
        else:
            lines.append(
                f"{len(divergences)} divergence(s) détectée(s) — résolution ci-dessous :"
            )
        for i, d in enumerate(divergences[:5], 1):
            label = {
                "genuine_conflict": "⚠ Contradiction factuelle",
                "lifecycle_evolution": "Évolution lifecycle",
                "scope_difference": "Scope différent",
                "no_real_divergence": "Pas de divergence réelle",
            }.get(d.divergence_type or "", "Divergence")
            lines.append(f"\n{i}. {label} sur « {d.claims[0].subject} {d.claims[0].predicate} »")
            for j, claim in enumerate(d.claims[:3]):
                date = f" ({claim.publication_date})" if claim.publication_date else ""
                lines.append(
                    f"   - {claim.object}{date} [doc={claim.doc_id}]"
                )
                if claim.quote:
                    lines.append(f"     « {claim.quote[:200]} »")
            if d.explanation:
                lines.append(f"   → {d.explanation}")
        return "\n".join(lines)

    # ---------------------------------------------------------- Public API
    def execute(self, question: str) -> ComparisonContradictionResult:
        timings: dict[str, int] = {}
        result = ComparisonContradictionResult(triggered=False)

        # 1. Intent
        t0 = time.time()
        intent = self.detect_intent(question)
        timings["intent_ms"] = int((time.time() - t0) * 1000)
        result.intent = intent

        if not intent.get("is_comparison_or_contradiction"):
            result.decision = "NOT_APPLICABLE"
            result.abstention_reason = "intent_not_comparison"
            result.latency_breakdown_ms = timings
            return result

        result.triggered = True
        result.expected_outcome = intent.get("expected_outcome")

        # 2. Retrieval
        t0 = time.time()
        try:
            bundle = self.evidence_collector.collect(
                question=question, top_k=self.top_k, mode="single",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"ComparisonContradiction retrieval failed: {exc}")
            result.decision = "ABSTAIN"
            result.abstention_reason = f"retrieval_error: {exc}"
            result.fallback_path = "escalate"
            result.latency_breakdown_ms = timings
            return result
        timings["retrieval_ms"] = int((time.time() - t0) * 1000)

        if not bundle.claims:
            result.decision = "ABSTAIN"
            result.abstention_reason = "no_evidence"
            result.fallback_path = "escalate"
            result.latency_breakdown_ms = timings
            return result

        # 3. Clustering déterministe
        t0 = time.time()
        records = self._build_records(bundle.claims)
        clusters = self._cluster_by_subject_predicate(records)
        timings["cluster_ms"] = int((time.time() - t0) * 1000)
        result.n_clusters_analyzed = len(clusters)

        if not clusters:
            # Pas de divergence détectée par le clustering — fallback Layer 2
            result.decision = "ABSTAIN"
            result.abstention_reason = "no_cluster_with_divergent_objects"
            result.fallback_path = "escalate"
            result.latency_breakdown_ms = timings
            return result

        # 4. Qualifier LLM par cluster (max 5 pour latence)
        t0 = time.time()
        divergences: list[DivergenceCluster] = []
        for cluster_records in clusters[:5]:
            cluster_payload = {
                "subject": cluster_records[0].subject,
                "predicate": cluster_records[0].predicate,
                "claims": [
                    {
                        "index": i,
                        "object": r.object,
                        "doc_id": r.doc_id,
                        "publication_date": r.publication_date,
                        "evidence_quote": r.quote,
                    }
                    for i, r in enumerate(cluster_records[:5])
                ],
            }
            qual = self.qualify_cluster(question, cluster_payload)
            divergence = DivergenceCluster(
                subject_norm=_norm(cluster_records[0].subject),
                predicate_norm=_norm(cluster_records[0].predicate),
                claims=cluster_records,
                qualified=True,
                divergence_type=qual.get("divergence_type"),
                explanation=qual.get("explanation"),
                primary_claim_indices=qual.get("primary_claims") or [],
            )
            divergences.append(divergence)
            if divergence.divergence_type == "genuine_conflict":
                result.n_genuine_conflicts += 1
        timings["qualify_ms"] = int((time.time() - t0) * 1000)

        result.divergences = [
            {
                "subject": d.claims[0].subject,
                "predicate": d.claims[0].predicate,
                "type": d.divergence_type,
                "explanation": d.explanation,
                "n_claims": len(d.claims),
            }
            for d in divergences
        ]

        # 5. Format réponse
        if not divergences:
            result.decision = "ABSTAIN"
            result.abstention_reason = "no_divergences_qualified"
            result.fallback_path = "escalate"
            result.latency_breakdown_ms = timings
            return result

        result.answer = self._format_answer(divergences)
        result.decision = "ANSWER"
        result.latency_breakdown_ms = timings
        return result
