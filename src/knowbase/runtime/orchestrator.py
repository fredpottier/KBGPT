"""
R1+R2 — Runtime Orchestrator V1.1.

Chef d'orchestre qui chaîne les 4 composants V1.1 :

    Query → QueryResolver → EvidencePlanner → Retrieval (Qdrant + Cypher)
                          → TrustEvaluator → ResponseComposer → Response

Branche les vrais services :
- Qdrant via shared_clients.get_qdrant_client()
- Embeddings via get_sentence_transformer()
- Neo4j via GraphDatabase
- TemporalRetriever (V3.3 §4 bis) pour les modes temporels
- LLM synthèse vLLM EC2 pour short_answer (R2.B implementation)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import date
from typing import Optional

import httpx
from neo4j import GraphDatabase

from knowbase.runtime.evidence_planner import EvidencePlanner, Regime, RetrievalPlan
from knowbase.runtime.query_resolver import QueryResolver, ResolvedQuery, ResponseMode
from knowbase.runtime.response_composer import ComposedResponse, ResponseComposer
from knowbase.runtime.trust_evaluator import TrustEvaluator
from knowbase.retrieval.temporal_retriever import TemporalRetriever, TemporalQueryResult

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

VLLM_URL = os.getenv("VLLM_URL", "http://3.79.236.241:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowbase")


SYNTHESIS_PROMPT = """Tu es un assistant régulatoire qui synthétise des réponses factuelles.

Question : {question}

Voici les passages les plus pertinents trouvés dans le corpus (avec leur metadata) :

{context}

Synthétise une **réponse courte** (1-3 phrases maximum) à la question, en t'appuyant
**uniquement** sur les passages fournis. Si les passages ne permettent pas de répondre,
dis-le explicitement.

Ne cite pas explicitement les passages dans ta réponse — ils seront affichés séparément
dans la section "Preuves".

Réponse courte :"""


# ============================================================================
# Orchestrator
# ============================================================================

class RuntimeOrchestrator:
    """Chef d'orchestre du pipeline runtime V1.1."""

    def __init__(
        self,
        tenant_id: str = "default",
        vllm_url: Optional[str] = None,
        vllm_model: Optional[str] = None,
    ):
        self.tenant_id = tenant_id
        self.vllm_url = (vllm_url or VLLM_URL).rstrip("/")
        self.vllm_model = vllm_model or VLLM_MODEL

        # Composants V1.1
        self.query_resolver = QueryResolver()
        self.evidence_planner = EvidencePlanner()
        self.trust_evaluator = TrustEvaluator()
        self.response_composer = ResponseComposer()

        # Drivers
        self.neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        self.temporal_retriever = TemporalRetriever(self.neo4j_driver, tenant_id=tenant_id)

        # Lazy-init Qdrant + embeddings
        self._qdrant = None
        self._embeddings_model = None
        self._settings = None

    def close(self):
        """Ferme le driver Neo4j."""
        if self.neo4j_driver:
            self.neo4j_driver.close()

    # ------------------------------------------------------------------------
    # Pipeline principal
    # ------------------------------------------------------------------------

    def query(
        self,
        question: str,
        persona_hints: Optional[dict] = None,
        synthesize: bool = True,
    ) -> ComposedResponse:
        """
        Pipeline complet : query → resolve → plan → retrieve → trust → compose.

        Args:
            question: question utilisateur
            persona_hints: optionnel, dict de hints (persona, verbosity, etc.)
            synthesize: si True, appelle LLM pour synthèse short_answer
                        (sinon retourne le top chunk text brut)

        Returns:
            ComposedResponse complète.
        """
        logger.info(f"[Runtime] Query: {question[:80]}")

        # 1. Resolve
        resolved = self.query_resolver.resolve(question, persona_hints=persona_hints)
        logger.info(f"[Runtime] Mode: {resolved.mode.value} (conf={resolved.confidence:.2f})")

        # 2. Plan
        plan = self.evidence_planner.plan(resolved)
        logger.info(f"[Runtime] Initial regime: {plan.regime.value}")

        # 3. Retrieve (selon régime)
        chunks: list[dict] = []
        relations: list[dict] = []

        if plan.regime in (Regime.RAG_LED, Regime.HYBRID):
            chunks = self._retrieve_qdrant(resolved.raw_query, plan)

            # Auto-escalation après retrieval RAG_LED
            if plan.regime == Regime.RAG_LED:
                plan = self.evidence_planner.maybe_escalate(plan, chunks)
                if plan.escalation_triggered:
                    logger.info(f"[Runtime] Escalation: {plan.escalation_reason}")

        # Si KG_LED (initial ou après escalation) → traverser le KG
        if plan.regime in (Regime.KG_LED, Regime.HYBRID):
            relations = self._retrieve_kg_relations(plan)
            # Si KG_LED pur (pas RAG_LED initial), on récupère aussi les chunks
            # depuis les claims trouvés via traversal
            if not chunks:
                chunks = self._retrieve_chunks_from_relations(relations)
                # Fallback : si pas de relations, faire un Qdrant pur
                if not chunks:
                    chunks = self._retrieve_qdrant(resolved.raw_query, plan)

        # 4. Trust
        trust = self.trust_evaluator.evaluate(
            chunks=chunks,
            relations=relations,
            regime=plan.regime,
            mode=resolved.mode,
            as_of_date=resolved.temporal_anchor,
        )
        logger.info(f"[Runtime] kg_trust: {trust.score} ({trust.level.value})")

        # 5. Compose
        composed = self.response_composer.compose(
            resolved=resolved,
            plan=plan,
            chunks=chunks,
            relations=relations,
            trust=trust,
        )

        # 6. LLM synthesis pour short_answer (R2.B)
        if synthesize and chunks:
            try:
                synthesized = self._synthesize_short_answer(question, chunks[:5])
                if synthesized:
                    composed.short_answer = synthesized
            except Exception as e:
                logger.warning(f"[Runtime] LLM synthesis failed: {e}")

        return composed

    # ------------------------------------------------------------------------
    # Retrieval Qdrant
    # ------------------------------------------------------------------------

    def _ensure_qdrant_clients(self):
        """Lazy-init des clients Qdrant + embeddings."""
        if self._qdrant is None:
            from knowbase.common.clients.shared_clients import get_qdrant_client, get_sentence_transformer
            from knowbase.config.settings import get_settings
            self._qdrant = get_qdrant_client()
            self._settings = get_settings()
            # Modèle d'embeddings (e5-large)
            self._embeddings_model = get_sentence_transformer(
                self._settings.embedding_model_name or "intfloat/multilingual-e5-large",
                cache_folder=str(self._settings.models_dir) if self._settings.models_dir else None,
            )

    def _retrieve_qdrant(self, query: str, plan: RetrievalPlan) -> list[dict]:
        """Retrieval Qdrant + enrichissement metadata depuis Neo4j."""
        try:
            self._ensure_qdrant_clients()
        except Exception as e:
            logger.warning(f"[Runtime] Qdrant unavailable: {e}")
            return []

        # Embed query
        # e5 conventions : prefix "query: " pour les queries
        query_text = f"query: {query}" if "e5" in (self._settings.embedding_model_name or "").lower() else query
        try:
            query_vector = self._embeddings_model.encode(query_text).tolist()
        except Exception as e:
            logger.warning(f"[Runtime] Embedding failed: {e}")
            return []

        # Qdrant search
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        try:
            results = self._qdrant.search(
                collection_name=QDRANT_COLLECTION,
                query_vector=query_vector,
                limit=plan.qdrant_top_k,
                with_payload=True,
            )
        except Exception as e:
            logger.warning(f"[Runtime] Qdrant search failed: {e}")
            return []

        # Build chunk list + enrichir avec metadata Neo4j (publication_date, validity_start, lifecycle)
        chunk_dicts = []
        claim_ids = []
        for r in results:
            payload = dict(r.payload or {})
            chunk = {
                "claim_id": payload.get("claim_id") or payload.get("id"),
                "text": payload.get("text") or payload.get("content") or "",
                "doc_id": payload.get("doc_id"),
                "score": float(r.score),
            }
            chunk_dicts.append(chunk)
            if chunk["claim_id"]:
                claim_ids.append(chunk["claim_id"])

        # Enrichissement Neo4j
        if claim_ids:
            metadata = self._fetch_claim_metadata(claim_ids)
            for chunk in chunk_dicts:
                cid = chunk.get("claim_id")
                if cid and cid in metadata:
                    chunk.update(metadata[cid])

        return chunk_dicts

    def _fetch_claim_metadata(self, claim_ids: list[str]) -> dict[str, dict]:
        """Récupère publication_date, validity_start, lifecycle_status depuis Neo4j."""
        if not claim_ids:
            return {}
        with self.neo4j_driver.session() as s:
            rows = s.run("""
                MATCH (c:Claim) WHERE c.tenant_id = $tid AND c.claim_id IN $ids
                RETURN c.claim_id AS claim_id,
                       c.publication_date AS publication_date,
                       c.validity_start AS validity_start,
                       c.validity_end AS validity_end,
                       c.lifecycle_status AS lifecycle_status
            """, tid=self.tenant_id, ids=claim_ids).data()
        return {r["claim_id"]: {
            "publication_date": r["publication_date"],
            "validity_start": r["validity_start"],
            "validity_end": r["validity_end"],
            "lifecycle_status": r["lifecycle_status"],
        } for r in rows}

    # ------------------------------------------------------------------------
    # Retrieval Cypher (KG_LED)
    # ------------------------------------------------------------------------

    def _retrieve_kg_relations(self, plan: RetrievalPlan) -> list[dict]:
        """Récupère les LOGICAL_RELATION pertinentes selon le plan."""
        with self.neo4j_driver.session() as s:
            # Construction du WHERE clauses
            where_clauses = ["a.tenant_id = $tid", "coalesce(r.legacy, false) = false"]

            # Filtrage par type
            if plan.relation_types_filter:
                where_clauses.append("r.type IN $types")

            # Filtrage derived
            if not plan.use_derived:
                where_clauses.append("coalesce(r.derived, false) = false")

            # Filtrage temporel
            if plan.temporal_filter and plan.temporal_filter.get("mode") == "SNAPSHOT":
                as_of = plan.temporal_filter.get("as_of_date")
                if as_of:
                    where_clauses.append("(a.validity_start IS NULL OR a.validity_start <= $as_of)")
                    where_clauses.append("(a.validity_end IS NULL OR a.validity_end >= $as_of)")

            where_str = " AND ".join(where_clauses)

            params = {
                "tid": self.tenant_id,
                "types": plan.relation_types_filter or [],
                "as_of": (plan.temporal_filter or {}).get("as_of_date"),
            }

            query = f"""
                MATCH (a:Claim)-[r:LOGICAL_RELATION]->(b:Claim)
                WHERE {where_str}
                RETURN
                  a.claim_id AS a_claim_id, a.text AS a_text, a.doc_id AS a_doc_id,
                  a.publication_date AS a_pub, a.validity_start AS a_vstart,
                  a.lifecycle_status AS a_lifecycle,
                  b.claim_id AS b_claim_id, b.text AS b_text, b.doc_id AS b_doc_id,
                  b.publication_date AS b_pub,
                  r.type AS type, r.confidence AS confidence,
                  r.strength AS strength, r.is_contradiction AS is_contradiction,
                  r.reasoning AS reasoning,
                  coalesce(r.derived, false) AS derived,
                  r.scope_alignment AS scope_alignment,
                  r.temporal_relation AS temporal_relation
                ORDER BY r.confidence DESC
                LIMIT 50
            """

            rows = s.run(query, **params).data()
        return [dict(r) for r in rows]

    def _retrieve_chunks_from_relations(self, relations: list[dict]) -> list[dict]:
        """Convertit les relations KG en chunks pour la composition."""
        seen_ids = set()
        chunks = []
        for r in relations:
            for side in ("a", "b"):
                cid = r.get(f"{side}_claim_id")
                if not cid or cid in seen_ids:
                    continue
                seen_ids.add(cid)
                chunks.append({
                    "claim_id": cid,
                    "text": r.get(f"{side}_text", ""),
                    "doc_id": r.get(f"{side}_doc_id"),
                    "publication_date": r.get(f"{side}_pub"),
                    "validity_start": r.get(f"{side}_vstart") if side == "a" else None,
                    "lifecycle_status": r.get(f"{side}_lifecycle") if side == "a" else None,
                    "score": float(r.get("confidence") or 0),
                    "via_relation": r.get("type"),
                })
        return chunks

    # ------------------------------------------------------------------------
    # LLM synthesis pour short_answer (R2.B)
    # ------------------------------------------------------------------------

    def _synthesize_short_answer(self, question: str, top_chunks: list[dict]) -> Optional[str]:
        """Appel vLLM pour synthèse 1-3 phrases."""
        context_parts = []
        for i, c in enumerate(top_chunks, 1):
            doc = c.get("doc_id", "?")
            text = (c.get("text") or "").strip()[:400]
            metadata = []
            if c.get("publication_date"):
                metadata.append(f"pub: {c['publication_date']}")
            if c.get("validity_start"):
                metadata.append(f"valid_from: {c['validity_start']}")
            if c.get("lifecycle_status") and c["lifecycle_status"] != "UNKNOWN":
                metadata.append(f"status: {c['lifecycle_status']}")
            meta_str = " · ".join(metadata) if metadata else ""
            context_parts.append(f"[{i}] doc={doc} {meta_str}\n{text}")

        context = "\n\n".join(context_parts)
        prompt = SYNTHESIS_PROMPT.format(question=question, context=context)

        try:
            response = httpx.post(
                f"{self.vllm_url}/v1/chat/completions",
                json={
                    "model": self.vllm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 250,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content
        except Exception as e:
            logger.warning(f"[Runtime] LLM synthesis call failed: {e}")
            return None


__all__ = ["RuntimeOrchestrator"]
