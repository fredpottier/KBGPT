"""Temporal Active Version Operator (CH-49.POC Phase 1.B).

Operator déterministe pour les questions "version active d'un document à date X".
Pas de LLM dans la chaîne de raisonnement — juste pour détecter l'intent et formater.

Architecture (3 étapes) :
  1. INTENT — LLM léger DeepSeek : {is_temporal_active, subject_keywords, query_date}
  2. KG QUERY — Cypher : récupère DocumentContext + lifecycle_status + publication_date
                          dont primary_subject/raw_subjects matchent les keywords
  3. DETERMINISTIC REASONING — pure Python : trier par date, filtrer ≤ query_date,
                          return version active (la plus récente avant ou à query_date)
  4. OUTPUT FORMATTING — phrase finale Composer light (LLM optionnel pour formulation)

Domain-agnostic : pas de hardcoding "CS-25" / "règlement", la détection est sémantique.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


INTENT_DETECTION_PROMPT = """You analyze user questions to determine if they ask "which version of a document was active at a specific date".

Return JSON only:
{
  "is_temporal_active": <bool>,
  "subject_keywords": ["<key terms identifying the document subject>"],
  "query_date": "<YYYY-MM-DD>" | "today" | null,
  "confidence": <float 0-1>,
  "reason": "<short explanation>"
}

Set is_temporal_active=true if the question asks about:
- which version applies at date X
- what is in force at date X
- the current/active/applicable version
- versioning/evolution of a document at a specific point in time

Set is_temporal_active=false for general factual, conceptual, or list questions.

subject_keywords should identify the document subject — what kind of document the user is asking about (without making them corpus-specific).

query_date :
- if explicit date in question, return YYYY-MM-DD format
- if "today", "currently", "actuellement", "aujourd'hui", "en vigueur" → return "today"
- if no date mentioned → return null

Examples (abstract):
- "What document Y was applicable in March 2024?" → is_temporal_active=true, query_date="2024-03-01"
- "Which amendment is currently in force?" → is_temporal_active=true, query_date="today"
- "List the items of category C" → is_temporal_active=false
- "Why was X repealed?" → is_temporal_active=false (causal, not temporal active)
"""


@dataclass
class TemporalActiveResult:
    """Result of operator execution."""
    triggered: bool  # operator was applicable
    answer: str = ""
    active_doc_id: Optional[str] = None
    active_publication_date: Optional[str] = None
    query_date: Optional[str] = None
    candidates: list[dict] = field(default_factory=list)
    intent: dict = field(default_factory=dict)
    cypher_n_hits: int = 0
    decision: str = "ABSTAIN"  # ANSWER | ABSTAIN | NOT_APPLICABLE
    abstention_reason: Optional[str] = None
    latency_breakdown_ms: dict = field(default_factory=dict)


class TemporalActiveVersionOperator:
    """Operator déterministe : version active à une date donnée.

    Cypher cherche les DocumentContext dont primary_subject ou raw_subjects matchent
    les subject_keywords. Le raisonnement temporel (filtrage par date) est en Python.
    """

    DEEPSEEK_MODEL = "deepseek-ai/DeepSeek-V3.1"
    DEEPSEEK_BASE_URL = "https://api.together.xyz/v1"

    GENERIC_KEYWORDS = {
        "document", "documents", "doc", "docs",
        "item", "items", "all",
        "regulation", "regulations", "règlement", "règlements",
        "rule", "rules",
    }

    def __init__(
        self,
        neo4j_driver: Any,
        tenant_id: str = "default",
        timeout: float = 30.0,
        evidence_collector: Optional[Any] = None,
    ) -> None:
        self.driver = neo4j_driver
        self.tenant_id = tenant_id
        self.timeout = timeout
        self.api_key = os.getenv("TOGETHER_API_KEY", "")
        self.evidence_collector = evidence_collector  # optional Qdrant fallback

    # ------------------------------------------------------------------ Intent
    def detect_intent(self, question: str) -> dict:
        """Détecte si la question est temporal_active + extrait subject_keywords + query_date."""
        payload = {
            "model": self.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": INTENT_DETECTION_PROMPT},
                {"role": "user", "content": f"Question: {question}"},
            ],
            "temperature": 0.0,
            "max_tokens": 250,
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
        except Exception as exc:
            logger.warning(f"TemporalActive intent detection failed: {exc}")
            return {
                "is_temporal_active": False,
                "subject_keywords": [],
                "query_date": None,
                "confidence": 0.0,
                "reason": f"intent_error: {exc}",
            }

    # ------------------------------------------------------------------ Cypher
    def query_versions(self, subject_keywords: list[str]) -> list[dict]:
        """Récupère les DocumentContext correspondant aux keywords."""
        if not subject_keywords:
            return []
        cypher = """
            MATCH (d:DocumentContext)
            WHERE d.tenant_id = $tenant_id
              AND any(kw IN $keywords WHERE
                  toLower(coalesce(d.primary_subject, '')) CONTAINS toLower(kw)
                  OR any(rs IN coalesce(d.raw_subjects, []) WHERE toLower(rs) CONTAINS toLower(kw))
                  OR toLower(coalesce(d.doc_id, '')) CONTAINS toLower(kw)
              )
              AND d.publication_date IS NOT NULL
            RETURN d.doc_id AS doc_id,
                   d.publication_date AS publication_date,
                   d.lifecycle_status AS lifecycle_status,
                   d.primary_subject AS primary_subject,
                   d.raw_subjects AS raw_subjects
            ORDER BY d.publication_date ASC
        """
        with self.driver.session(database="neo4j") as session:
            try:
                result = session.run(cypher, tenant_id=self.tenant_id, keywords=subject_keywords)
                return [dict(rec) for rec in result]
            except Exception as exc:
                logger.error(f"TemporalActive Cypher failed: {exc}")
                return []

    def query_all_active(self) -> list[dict]:
        """Mode list_all_active_at_date : tous les DocumentContext avec date."""
        cypher = """
            MATCH (d:DocumentContext)
            WHERE d.tenant_id = $tenant_id
              AND d.publication_date IS NOT NULL
            RETURN d.doc_id AS doc_id,
                   d.publication_date AS publication_date,
                   d.lifecycle_status AS lifecycle_status,
                   d.primary_subject AS primary_subject,
                   d.raw_subjects AS raw_subjects
            ORDER BY d.publication_date ASC
            LIMIT 200
        """
        with self.driver.session(database="neo4j") as session:
            try:
                result = session.run(cypher, tenant_id=self.tenant_id)
                return [dict(rec) for rec in result]
            except Exception as exc:
                logger.error(f"TemporalActive query_all_active failed: {exc}")
                return []

    def resolve_via_qdrant(self, question: str) -> list[str]:
        """Fallback : Qdrant search → extrait les doc_ids les plus pertinents."""
        if self.evidence_collector is None:
            return []
        try:
            bundle = self.evidence_collector.collect(question=question, top_k=10, mode="single")
            doc_ids = list(dict.fromkeys(c.doc_id for c in bundle.claims if c.doc_id))
            return doc_ids[:8]
        except Exception as exc:
            logger.warning(f"TemporalActive Qdrant fallback failed: {exc}")
            return []

    def query_by_doc_ids(self, doc_ids: list[str]) -> list[dict]:
        """Cypher : récupère DocumentContext par doc_id direct."""
        if not doc_ids:
            return []
        cypher = """
            MATCH (d:DocumentContext)
            WHERE d.tenant_id = $tenant_id
              AND d.doc_id IN $doc_ids
              AND d.publication_date IS NOT NULL
            RETURN d.doc_id AS doc_id,
                   d.publication_date AS publication_date,
                   d.lifecycle_status AS lifecycle_status,
                   d.primary_subject AS primary_subject,
                   d.raw_subjects AS raw_subjects
            ORDER BY d.publication_date ASC
        """
        with self.driver.session(database="neo4j") as session:
            try:
                result = session.run(cypher, tenant_id=self.tenant_id, doc_ids=doc_ids)
                return [dict(rec) for rec in result]
            except Exception as exc:
                logger.error(f"query_by_doc_ids failed: {exc}")
                return []

    # -------------------------------------------------- Reasoning + formatting
    @staticmethod
    def _parse_date(s: Optional[str]) -> Optional[date]:
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def determine_active(self, candidates: list[dict], query_date: date) -> Optional[dict]:
        """Sélectionne la version active à query_date : publication_date la plus
        récente parmi celles ≤ query_date."""
        eligible = []
        for c in candidates:
            pd = self._parse_date(c.get("publication_date"))
            if pd is None:
                continue
            if pd <= query_date:
                eligible.append((pd, c))
        if not eligible:
            return None
        eligible.sort(key=lambda x: x[0], reverse=True)
        return eligible[0][1]

    def format_answer(self, active: dict, query_date: date, all_candidates: list[dict]) -> str:
        """Phrase finale (déterministe, pas de LLM)."""
        doc_id = active.get("doc_id", "?")
        pd = active.get("publication_date", "?")
        status = active.get("lifecycle_status", "ACTIVE")
        subject = active.get("primary_subject") or "the document"
        date_str = query_date.strftime("%Y-%m-%d")

        successors = [
            c for c in all_candidates
            if (sd := self._parse_date(c.get("publication_date"))) and sd > query_date
        ]
        successors.sort(key=lambda c: self._parse_date(c.get("publication_date")) or date.min)
        next_version_clause = ""
        if successors:
            ns = successors[0]
            next_version_clause = (
                f" Sa version successeur ({ns.get('doc_id')}, "
                f"publiée le {ns.get('publication_date')}) entre en vigueur ultérieurement."
            )

        return (
            f"À la date {date_str}, la version active de {subject} est "
            f"{doc_id} (publiée le {pd}, lifecycle_status={status}) [doc={doc_id}]."
            + next_version_clause
        )

    # ---------------------------------------------------------------- Execute
    def execute(self, question: str) -> TemporalActiveResult:
        timings: dict = {}

        # 1. Intent detection
        t0 = time.time()
        intent = self.detect_intent(question)
        timings["intent_ms"] = int((time.time() - t0) * 1000)

        if not intent.get("is_temporal_active"):
            return TemporalActiveResult(
                triggered=False,
                decision="NOT_APPLICABLE",
                intent=intent,
                latency_breakdown_ms=timings,
            )

        # 2. Resolve query_date
        qd_raw = intent.get("query_date")
        if qd_raw == "today":
            query_date = date.today()
        else:
            query_date = self._parse_date(qd_raw) or date.today()

        # 3. Cypher avec stratégies de fallback en cascade
        keywords = intent.get("subject_keywords") or []
        keywords_lower = {k.lower() for k in keywords}
        is_generic = bool(keywords_lower & self.GENERIC_KEYWORDS) and len(keywords) <= 2

        t0 = time.time()
        candidates: list[dict] = []
        resolution_path = "kw_match"

        # 3.A Match par keywords (si non générique)
        if keywords and not is_generic:
            candidates = self.query_versions(keywords)

        # 3.B Fallback Qdrant si keywords sémantiques mais 0 hit
        if not candidates and self.evidence_collector and keywords:
            doc_ids = self.resolve_via_qdrant(question)
            if doc_ids:
                candidates = self.query_by_doc_ids(doc_ids)
                resolution_path = "qdrant_fallback"

        # 3.C Mode list_all si keywords génériques ou toujours rien
        if not candidates and (is_generic or not keywords):
            candidates = self.query_all_active()
            resolution_path = "list_all_active"

        timings["cypher_ms"] = int((time.time() - t0) * 1000)
        timings["resolution_path"] = resolution_path

        if not candidates:
            return TemporalActiveResult(
                triggered=True,
                decision="ABSTAIN",
                abstention_reason=f"no_kg_versions_found (path={resolution_path})",
                intent=intent,
                query_date=query_date.strftime("%Y-%m-%d"),
                cypher_n_hits=0,
                latency_breakdown_ms=timings,
            )

        # 4. Reasoning déterministe
        t0 = time.time()
        active = self.determine_active(candidates, query_date)
        timings["reasoning_ms"] = int((time.time() - t0) * 1000)

        if active is None:
            return TemporalActiveResult(
                triggered=True,
                decision="ABSTAIN",
                abstention_reason="no_version_before_query_date",
                intent=intent,
                query_date=query_date.strftime("%Y-%m-%d"),
                candidates=candidates[:5],
                cypher_n_hits=len(candidates),
                latency_breakdown_ms=timings,
            )

        answer = self.format_answer(active, query_date, candidates)
        return TemporalActiveResult(
            triggered=True,
            decision="ANSWER",
            answer=answer,
            active_doc_id=active.get("doc_id"),
            active_publication_date=active.get("publication_date"),
            query_date=query_date.strftime("%Y-%m-%d"),
            candidates=candidates[:10],
            intent=intent,
            cypher_n_hits=len(candidates),
            latency_breakdown_ms=timings,
        )
