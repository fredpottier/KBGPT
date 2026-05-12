"""Lifecycle Resolution Operator (Cap2.B — CH-49 Phase 2).

Operator déterministe pour les questions :
  - "Qui a remplacé X ?" / "Quel document succède à X ?"
  - "Que remplace Y ?" / "Quel document Y a-t-il abrogé ?"
  - "X SUPERSEDES Y ?" / "Quelle est la lignée d'évolution de Z ?"

Architecture (3 étapes, charte ADR §1) :
  1. INTENT — LLM léger DeepSeek : {is_lifecycle, direction, subject_keywords, relation_hint}
  2. KG QUERY — Cypher LIFECYCLE_RELATION (DocumentContext → DocumentContext)
  3. FORMATTING — composition déterministe avec evidence_quote + citations

Schéma Neo4j (validé 10/05/2026) :
  (successor:DocumentContext)-[r:LIFECYCLE_RELATION]->(predecessor:DocumentContext)
  Properties r : type ∈ {SUPERSEDES, EVOLVES_FROM, REAFFIRMS}, evidence_quote, confidence,
                 reasoning, evidence_claim_ids, derivation_path, model_id, extracted_at

Domain-agnostic : keywords sémantiques uniquement (pas de regex métier).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


INTENT_DETECTION_PROMPT = """You analyze user questions to determine if they ask about a document lifecycle relation (replacement, evolution, reaffirmation between documents).

Return JSON only:
{
  "is_lifecycle": <bool>,
  "direction": "successor_of" | "predecessor_of" | "chain" | null,
  "subject_keywords": ["<key terms identifying the target document>"],
  "relation_hint": "SUPERSEDES" | "EVOLVES_FROM" | "REAFFIRMS" | null,
  "confidence": <float 0-1>,
  "reason": "<short explanation>"
}

Set is_lifecycle=true if the question asks about:
- which document replaces/repeals/supersedes another
- which amendment evolves from / amends another document
- predecessor/successor of a document
- the lifecycle chain of evolution between document versions

Direction :
- "successor_of" : "what replaced X / what comes after X / who succeeds X"
- "predecessor_of" : "what does X replace / what does X repeal / what came before X"
- "chain" : "what is the evolution lineage of X / show the supersession chain"
- null : if not applicable

Relation hint (semantic, language-agnostic):
- SUPERSEDES : replace, repeal, abrogate, supersede, abroger, remplacer
- EVOLVES_FROM : amend, modify, evolve, replace-annex, modifier, evolution
- REAFFIRMS : reaffirm, confirm, restate
- null : if no specific hint

subject_keywords : identifiers, codes, dates or names typed by the user that uniquely point to the target document. Copy them verbatim from the question. NEVER invent identifiers or rephrase them.

Examples (abstract — placeholders <DOC_X>, <DOC_Y> stand for any document identifier the user might type):
- "What document replaced <DOC_X>?" → is_lifecycle=true, direction="successor_of", subject_keywords=["<DOC_X>"], relation_hint="SUPERSEDES"
- "What amended/modified <DOC_X>?" → is_lifecycle=true, direction="successor_of", subject_keywords=["<DOC_X>"], relation_hint="EVOLVES_FROM"
- "What does <DOC_X> replace / repeal?" → is_lifecycle=true, direction="predecessor_of", subject_keywords=["<DOC_X>"]
- "Show the supersession chain of <DOC_X>" → is_lifecycle=true, direction="chain", subject_keywords=["<DOC_X>"]
- "What is the version of <DOC_X> currently in force?" → is_lifecycle=false (this is temporal_active, NOT lifecycle resolution)
- "List the items inside <DOC_X>" → is_lifecycle=false
- "Why was <DOC_X> repealed?" → is_lifecycle=false (causal, not lifecycle resolution per se)
"""


@dataclass
class LifecycleResolutionResult:
    """Résultat operator Cap2.B."""

    triggered: bool
    answer: str = ""
    direction: Optional[str] = None  # successor_of | predecessor_of | chain
    subject_keywords: list[str] = field(default_factory=list)
    relation_hint: Optional[str] = None
    candidates: list[dict] = field(default_factory=list)
    intent: dict = field(default_factory=dict)
    cypher_n_hits: int = 0
    decision: str = "ABSTAIN"  # ANSWER | ABSTAIN | NOT_APPLICABLE
    abstention_reason: Optional[str] = None
    fallback_path: str = "primary"  # primary | fallback_1_qdrant | fallback_2_multi | escalate
    latency_breakdown_ms: dict = field(default_factory=dict)


class LifecycleResolutionOperator:
    """Operator Cap2.B : résolution lifecycle (SUPERSEDES / EVOLVES_FROM / REAFFIRMS)."""

    DEEPSEEK_MODEL = "deepseek-ai/DeepSeek-V3.1"
    DEEPSEEK_BASE_URL = "https://api.together.xyz/v1"

    GENERIC_KEYWORDS = {
        "document", "documents", "doc", "docs", "regulation", "regulations",
        "règlement", "règlements", "directive", "directives", "amendment", "amendments",
        "rule", "rules", "law", "laws", "act", "acts",
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
        self.evidence_collector = evidence_collector  # Qdrant fallback

    # ---------------------------------------------------------------- Intent
    def detect_intent(self, question: str) -> dict:
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
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"LifecycleResolution intent detection failed: {exc}")
            return {
                "is_lifecycle": False,
                "direction": None,
                "subject_keywords": [],
                "relation_hint": None,
                "confidence": 0.0,
                "reason": f"intent_error: {exc}",
            }

    # ---------------------------------------------------------------- Cypher
    def query_successors(
        self,
        subject_keywords: list[str],
        relation_type: Optional[str] = None,
    ) -> list[dict]:
        """Trouve les successors d'un document matché par keywords (qui a remplacé X).

        Schéma : (succ)-[r]->(pred) ; on filtre sur pred matchant les keywords.
        """
        if not subject_keywords:
            return []
        cypher = """
            MATCH (succ:DocumentContext)-[r:LIFECYCLE_RELATION]->(pred:DocumentContext)
            WHERE pred.tenant_id = $tenant_id
              AND any(kw IN $keywords WHERE
                  toLower(coalesce(pred.primary_subject, '')) CONTAINS toLower(kw)
                  OR any(rs IN coalesce(pred.raw_subjects, []) WHERE toLower(rs) CONTAINS toLower(kw))
                  OR toLower(coalesce(pred.doc_id, '')) CONTAINS toLower(kw)
                  OR toLower(coalesce(pred.full_doc_title, '')) CONTAINS toLower(kw)
              )
              AND ($rel_type IS NULL OR r.type = $rel_type)
            RETURN succ.doc_id AS successor_doc_id,
                   coalesce(succ.full_doc_title, succ.primary_subject, succ.doc_id) AS successor_title,
                   succ.publication_date AS successor_date,
                   pred.doc_id AS predecessor_doc_id,
                   coalesce(pred.full_doc_title, pred.primary_subject, pred.doc_id) AS predecessor_title,
                   r.type AS relation_type,
                   r.evidence_quote AS evidence_quote,
                   r.confidence AS confidence,
                   r.reasoning AS reasoning
            ORDER BY r.confidence DESC, succ.publication_date DESC
        """
        with self.driver.session(database="neo4j") as session:
            try:
                result = session.run(
                    cypher, tenant_id=self.tenant_id,
                    keywords=subject_keywords, rel_type=relation_type,
                )
                return [dict(rec) for rec in result]
            except Exception as exc:  # noqa: BLE001
                logger.error(f"LifecycleResolution query_successors failed: {exc}")
                return []

    def query_predecessors(
        self,
        subject_keywords: list[str],
        relation_type: Optional[str] = None,
    ) -> list[dict]:
        """Trouve les predecessors d'un document (que remplace X).

        Schéma : (succ matchant keywords)-[r]->(pred).
        """
        if not subject_keywords:
            return []
        cypher = """
            MATCH (succ:DocumentContext)-[r:LIFECYCLE_RELATION]->(pred:DocumentContext)
            WHERE succ.tenant_id = $tenant_id
              AND any(kw IN $keywords WHERE
                  toLower(coalesce(succ.primary_subject, '')) CONTAINS toLower(kw)
                  OR any(rs IN coalesce(succ.raw_subjects, []) WHERE toLower(rs) CONTAINS toLower(kw))
                  OR toLower(coalesce(succ.doc_id, '')) CONTAINS toLower(kw)
                  OR toLower(coalesce(succ.full_doc_title, '')) CONTAINS toLower(kw)
              )
              AND ($rel_type IS NULL OR r.type = $rel_type)
            RETURN succ.doc_id AS successor_doc_id,
                   coalesce(succ.full_doc_title, succ.primary_subject, succ.doc_id) AS successor_title,
                   pred.doc_id AS predecessor_doc_id,
                   coalesce(pred.full_doc_title, pred.primary_subject, pred.doc_id) AS predecessor_title,
                   pred.publication_date AS predecessor_date,
                   r.type AS relation_type,
                   r.evidence_quote AS evidence_quote,
                   r.confidence AS confidence,
                   r.reasoning AS reasoning
            ORDER BY r.confidence DESC
        """
        with self.driver.session(database="neo4j") as session:
            try:
                result = session.run(
                    cypher, tenant_id=self.tenant_id,
                    keywords=subject_keywords, rel_type=relation_type,
                )
                return [dict(rec) for rec in result]
            except Exception as exc:  # noqa: BLE001
                logger.error(f"LifecycleResolution query_predecessors failed: {exc}")
                return []

    def resolve_via_qdrant(self, question: str) -> list[str]:
        """Fallback Qdrant : extrait les doc_ids des claims les plus pertinents."""
        if self.evidence_collector is None:
            return []
        try:
            bundle = self.evidence_collector.collect(question=question, top_k=10, mode="single")
            doc_ids = list(dict.fromkeys(c.doc_id for c in bundle.claims if c.doc_id))
            return doc_ids[:8]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"LifecycleResolution Qdrant fallback failed: {exc}")
            return []

    def query_by_doc_ids(
        self,
        doc_ids: list[str],
        direction: str,
        relation_type: Optional[str] = None,
    ) -> list[dict]:
        """Cypher fallback : query par doc_id explicite (post Qdrant resolve)."""
        if not doc_ids:
            return []
        if direction == "successor_of":
            # On a doc_ids comme candidats predecessor potentiels
            cypher = """
                MATCH (succ:DocumentContext)-[r:LIFECYCLE_RELATION]->(pred:DocumentContext)
                WHERE pred.tenant_id = $tenant_id
                  AND pred.doc_id IN $doc_ids
                  AND ($rel_type IS NULL OR r.type = $rel_type)
                RETURN succ.doc_id AS successor_doc_id,
                       coalesce(succ.full_doc_title, succ.primary_subject, succ.doc_id) AS successor_title,
                       succ.publication_date AS successor_date,
                       pred.doc_id AS predecessor_doc_id,
                       coalesce(pred.full_doc_title, pred.primary_subject, pred.doc_id) AS predecessor_title,
                       r.type AS relation_type,
                       r.evidence_quote AS evidence_quote,
                       r.confidence AS confidence,
                       r.reasoning AS reasoning
                ORDER BY r.confidence DESC
            """
        else:
            cypher = """
                MATCH (succ:DocumentContext)-[r:LIFECYCLE_RELATION]->(pred:DocumentContext)
                WHERE succ.tenant_id = $tenant_id
                  AND succ.doc_id IN $doc_ids
                  AND ($rel_type IS NULL OR r.type = $rel_type)
                RETURN succ.doc_id AS successor_doc_id,
                       coalesce(succ.full_doc_title, succ.primary_subject, succ.doc_id) AS successor_title,
                       pred.doc_id AS predecessor_doc_id,
                       coalesce(pred.full_doc_title, pred.primary_subject, pred.doc_id) AS predecessor_title,
                       pred.publication_date AS predecessor_date,
                       r.type AS relation_type,
                       r.evidence_quote AS evidence_quote,
                       r.confidence AS confidence,
                       r.reasoning AS reasoning
                ORDER BY r.confidence DESC
            """
        with self.driver.session(database="neo4j") as session:
            try:
                result = session.run(
                    cypher, tenant_id=self.tenant_id,
                    doc_ids=doc_ids, rel_type=relation_type,
                )
                return [dict(rec) for rec in result]
            except Exception as exc:  # noqa: BLE001
                logger.error(f"LifecycleResolution query_by_doc_ids failed: {exc}")
                return []

    # ---------------------------------------------------------- Formatting
    @staticmethod
    def _label(title: Optional[str], doc_id: str) -> str:
        """Préfère un label court non-générique pour distinguer les documents.

        Si le titre est trop générique (souvent répété), on utilise doc_id comme suffixe
        identifiant pour éviter "X a remplacé X" quand les titres sont identiques.
        """
        title = (title or "").strip()
        if not title or len(title) < 5:
            return doc_id
        # Toujours suffixer avec doc_id pour distinguer (les titres canoniques peuvent être identiques)
        return f"{title} ({doc_id})"

    @classmethod
    def _format_answer_successor(cls, candidates: list[dict]) -> str:
        if not candidates:
            return ""
        if len(candidates) == 1:
            c = candidates[0]
            succ = cls._label(c.get("successor_title"), c["successor_doc_id"])
            pred = cls._label(c.get("predecessor_title"), c["predecessor_doc_id"])
            return (
                f"{succ} a remplacé {pred} "
                f"(relation {c['relation_type']}, confiance {c['confidence']:.2f}). "
                f"Evidence : « {c['evidence_quote']} » "
                f"[doc={c['successor_doc_id']}] "
                f"[doc={c['predecessor_doc_id']}]"
            )
        # Multi-candidates : déduplique par successor_doc_id (relations multiples sur même target/source)
        seen: set[str] = set()
        unique_cands = []
        for c in candidates:
            key = c["successor_doc_id"]
            if key not in seen:
                seen.add(key)
                unique_cands.append(c)
        if len(unique_cands) == 1:
            return cls._format_answer_successor(unique_cands)
        lines = [f"Plusieurs documents successeurs ont été identifiés ({len(unique_cands)}) :"]
        for c in unique_cands[:5]:
            label = cls._label(c.get("successor_title"), c["successor_doc_id"])
            lines.append(
                f"- {label} (relation {c['relation_type']}, "
                f"conf={c['confidence']:.2f}) [doc={c['successor_doc_id']}]"
            )
        if unique_cands[0].get("evidence_quote"):
            lines.append(f"\nEvidence principale : « {unique_cands[0]['evidence_quote']} »")
        return "\n".join(lines)

    @classmethod
    def _format_answer_predecessor(cls, candidates: list[dict]) -> str:
        if not candidates:
            return ""
        if len(candidates) == 1:
            c = candidates[0]
            succ = cls._label(c.get("successor_title"), c["successor_doc_id"])
            pred = cls._label(c.get("predecessor_title"), c["predecessor_doc_id"])
            return (
                f"{succ} a remplacé {pred} "
                f"(relation {c['relation_type']}, confiance {c['confidence']:.2f}). "
                f"Evidence : « {c['evidence_quote']} » "
                f"[doc={c['successor_doc_id']}] "
                f"[doc={c['predecessor_doc_id']}]"
            )
        # Déduplique par predecessor_doc_id
        seen: set[str] = set()
        unique_cands = []
        for c in candidates:
            key = c["predecessor_doc_id"]
            if key not in seen:
                seen.add(key)
                unique_cands.append(c)
        if len(unique_cands) == 1:
            return cls._format_answer_predecessor(unique_cands)
        lines = [f"Documents prédécesseurs identifiés ({len(unique_cands)}) :"]
        for c in unique_cands[:5]:
            label = cls._label(c.get("predecessor_title"), c["predecessor_doc_id"])
            lines.append(
                f"- {label} (relation {c['relation_type']}, "
                f"conf={c['confidence']:.2f}) [doc={c['predecessor_doc_id']}]"
            )
        if unique_cands[0].get("evidence_quote"):
            lines.append(f"\nEvidence principale : « {unique_cands[0]['evidence_quote']} »")
        return "\n".join(lines)

    # ---------------------------------------------------------- Public API
    def execute(self, question: str) -> LifecycleResolutionResult:
        timings: dict[str, int] = {}
        result = LifecycleResolutionResult(triggered=False)

        # 1. Intent detection
        t0 = time.time()
        intent = self.detect_intent(question)
        timings["intent_ms"] = int((time.time() - t0) * 1000)
        result.intent = intent

        if not intent.get("is_lifecycle"):
            result.decision = "NOT_APPLICABLE"
            result.abstention_reason = "intent_not_lifecycle"
            result.latency_breakdown_ms = timings
            return result

        result.triggered = True
        result.direction = intent.get("direction")
        keywords_raw = intent.get("subject_keywords") or []
        result.subject_keywords = [
            k for k in keywords_raw
            if k and k.lower() not in self.GENERIC_KEYWORDS and len(k) > 1
        ]
        result.relation_hint = intent.get("relation_hint")

        if not result.subject_keywords:
            # Fallback Qdrant resolver
            t0 = time.time()
            doc_ids = self.resolve_via_qdrant(question)
            timings["qdrant_resolver_ms"] = int((time.time() - t0) * 1000)
            if not doc_ids:
                result.decision = "ABSTAIN"
                result.abstention_reason = "no_keywords_no_qdrant"
                result.fallback_path = "escalate"
                result.latency_breakdown_ms = timings
                return result
            t0 = time.time()
            cands = self.query_by_doc_ids(
                doc_ids,
                direction=result.direction or "successor_of",
                relation_type=result.relation_hint,
            )
            timings["cypher_ms"] = int((time.time() - t0) * 1000)
            result.candidates = cands
            result.cypher_n_hits = len(cands)
            result.fallback_path = "fallback_1_qdrant"
        else:
            # Primary path
            t0 = time.time()
            if result.direction == "predecessor_of":
                cands = self.query_predecessors(
                    result.subject_keywords, result.relation_hint
                )
            else:
                # default successor_of (couvre aussi "chain" pour le moment)
                cands = self.query_successors(
                    result.subject_keywords, result.relation_hint
                )
            timings["cypher_ms"] = int((time.time() - t0) * 1000)

            if not cands:
                # Fallback Qdrant resolve doc_ids puis re-query
                t0 = time.time()
                doc_ids = self.resolve_via_qdrant(question)
                timings["qdrant_resolver_ms"] = int((time.time() - t0) * 1000)
                if doc_ids:
                    t0 = time.time()
                    cands = self.query_by_doc_ids(
                        doc_ids,
                        direction=result.direction or "successor_of",
                        relation_type=result.relation_hint,
                    )
                    timings["cypher_fallback_ms"] = int((time.time() - t0) * 1000)
                result.fallback_path = "fallback_1_qdrant"

            result.candidates = cands
            result.cypher_n_hits = len(cands)

        # 3. Format réponse
        if not result.candidates:
            result.decision = "ABSTAIN"
            result.abstention_reason = "no_lifecycle_relation_found"
            result.fallback_path = "escalate"
            result.latency_breakdown_ms = timings
            return result

        if result.direction == "predecessor_of":
            answer = self._format_answer_predecessor(result.candidates)
        else:
            answer = self._format_answer_successor(result.candidates)

        if not answer:
            result.decision = "ABSTAIN"
            result.abstention_reason = "format_failed"
            result.latency_breakdown_ms = timings
            return result

        result.answer = answer
        result.decision = "ANSWER"
        if len(result.candidates) > 1:
            result.fallback_path = "fallback_2_multi"
        result.latency_breakdown_ms = timings
        return result
