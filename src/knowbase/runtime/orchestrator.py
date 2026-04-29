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


def _temporal_result_to_chunk(t: TemporalQueryResult) -> dict:
    """Convertit un TemporalQueryResult en dict chunk standard (compatible composer)."""
    return {
        "claim_id": t.claim_id,
        "text": t.text,
        "doc_id": t.doc_id,
        "publication_date": t.publication_date,
        "validity_start": t.validity_start,
        "validity_end": t.validity_end,
        "lifecycle_status": t.lifecycle_status,
        "score": float(t.recency_weight),
        "diff_change_type": t.diff_change_type,
    }


def _parse_iso_date(value) -> Optional[date]:
    """Parse une string ISO en date, retourne None si invalide."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

VLLM_URL = os.getenv("VLLM_URL", "http://3.79.236.241:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowbase_chunks_v2")


SYNTHESIS_PROMPT = """Tu es un assistant régulatoire qui synthétise des réponses factuelles.

Question : {question}
Mode de réponse : {mode}{mode_hint}

Voici les passages les plus pertinents trouvés dans le corpus (avec leur metadata) :

{context}

{mode_instruction}

Synthétise une **réponse courte** (1-3 phrases maximum) à la question, en t'appuyant
**uniquement** sur les passages fournis. Si les passages ne permettent pas de répondre,
dis-le explicitement.

Ne cite pas explicitement les passages dans ta réponse — ils seront affichés séparément
dans la section "Preuves".

Réponse courte :"""


# Instructions par mode injectées dans le synthesis prompt (R3+R4 calibration)
MODE_INSTRUCTIONS: dict[str, str] = {
    "LOOKUP_FACTUAL": (
        "→ Réponds avec la valeur exacte si trouvée. Si plusieurs valeurs pour le même "
        "champ, indique-le explicitement (ambiguïté)."
    ),
    "APPLICABILITY_QUERY": (
        "→ Réponds en listant les règles qui s'appliquent au scope demandé. "
        "Mentionne les conditions et exceptions si elles sont dans les passages."
    ),
    "SNAPSHOT_TEMPORAL": (
        "→ Donne la règle TELLE QU'ELLE ÉTAIT à la date demandée. Ne mélange pas avec "
        "des règles plus récentes ou plus anciennes. Si certains passages sont d'autres "
        "périodes, ignore-les."
    ),
    "DIFF_EVOLUTION": (
        "→ Décris ce qui a changé entre les deux dates : ce qui a été ajouté, retiré, "
        "ou modifié. Utilise les annotations 'introduced', 'retired', 'modified' fournies "
        "dans la metadata si présentes."
    ),
    "CONFLICT_RISK": (
        "→ Décris la nature du conflit entre les passages. Indique les claims contradictoires "
        "et la raison du conflit. Ne tranche pas — présente les deux positions."
    ),
    "EXPLORATION_RELATIONAL": (
        "→ Réponds en énumérant les éléments par type de relation (SUBSET, EXCEPTION, etc.). "
        "Indique le nombre par catégorie."
    ),
    "SYNTHESIS_SUMMARY": (
        "→ Résume en couvrant les axes principaux du sujet. Reste neutre et descriptif."
    ),
}


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

        # 3. Retrieve (selon régime + mode)
        chunks: list[dict] = []
        relations: list[dict] = []

        # 3.a Modes temporels : routent via TemporalRetriever (V3.3 §4 bis)
        # On capte ces modes en amont pour utiliser le retriever spécialisé. Qdrant
        # complète ensuite si besoin pour pertinence sémantique.
        if resolved.mode == ResponseMode.SNAPSHOT_TEMPORAL and resolved.temporal_anchor:
            chunks = self._retrieve_temporal_snapshot(resolved, plan)
            # Sur ce mode, on cherche aussi les relations (SUPERSEDES) qui touchent ces claims
            relations = self._retrieve_kg_relations(plan)
        elif resolved.mode == ResponseMode.DIFF_EVOLUTION and resolved.temporal_range:
            chunks = self._retrieve_temporal_diff(resolved, plan)
            relations = self._retrieve_kg_relations(plan)
        else:
            # 3.b Pipeline régime standard
            if plan.regime in (Regime.RAG_LED, Regime.HYBRID):
                chunks = self._retrieve_qdrant(resolved.raw_query, plan)

                # Auto-escalation après retrieval RAG_LED
                if plan.regime == Regime.RAG_LED:
                    # Signaux RAG (lifecycle + temporal ambiguity)
                    plan = self.evidence_planner.maybe_escalate(plan, chunks)

                    # Signaux KG additionnels (UNRESOLVED_CONFLICT + MULTI_VERSION)
                    if not plan.escalation_triggered and chunks:
                        top_ids = [c.get("claim_id") for c in chunks[:5] if c.get("claim_id")]
                        kg_signals = self.evidence_planner.detect_kg_signals(
                            top_ids, kg_lookup_fn=self._kg_lookup_for_signals
                        )
                        if kg_signals:
                            plan = self.evidence_planner.maybe_escalate(plan, chunks, signals=kg_signals)

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

        # 6. LLM synthesis pour short_answer (R2.B + R3+R4 calibration mode-aware)
        if synthesize and chunks:
            try:
                synthesized = self._synthesize_short_answer(
                    question, chunks[:5], resolved=resolved
                )
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
            cache_folder = str(self._settings.hf_home) if getattr(self._settings, "hf_home", None) else None
            self._embeddings_model = get_sentence_transformer(
                self._settings.embeddings_model or "intfloat/multilingual-e5-large",
                cache_folder=cache_folder,
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
        query_text = f"query: {query}" if "e5" in (self._settings.embeddings_model or "").lower() else query
        try:
            query_vector = self._embeddings_model.encode(query_text).tolist()
        except Exception as e:
            logger.warning(f"[Runtime] Embedding failed: {e}")
            return []

        # Qdrant search — préférer settings.qdrant_collection si présent, fallback env var
        collection_name = getattr(self._settings, "qdrant_collection", None) or QDRANT_COLLECTION
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        try:
            results = self._qdrant.search(
                collection_name=collection_name,
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
    # Retrieval temporel (V3.3 §4 bis)
    # ------------------------------------------------------------------------

    def _retrieve_temporal_snapshot(
        self, resolved: ResolvedQuery, plan: RetrievalPlan
    ) -> list[dict]:
        """
        Mode SNAPSHOT_TEMPORAL : claims valides à `as_of_date`.

        Stratégie hybride :
        1. TemporalRetriever récupère les claims valides à T (filtrage strict KG)
        2. Qdrant cherche en parallèle pour la pertinence sémantique
        3. Intersection = claims valides à T ET pertinents
        4. Si l'intersection est vide → fallback sur les chunks KG bruts (pertinence
           moindre mais cohérence temporelle garantie)
        """
        as_of = resolved.temporal_anchor
        if as_of is None:
            return []

        # Étape 1 — récupérer les claims valides à T
        try:
            valid_claims = self.temporal_retriever.retrieve_snapshot(
                as_of_date=as_of,
                limit=plan.qdrant_top_k * 3,  # large pool pour intersection
            )
        except Exception as e:
            logger.warning(f"[Runtime] TemporalRetriever.snapshot failed: {e}")
            return []

        if not valid_claims:
            logger.info(f"[Runtime] No claims valid at {as_of}")
            return []

        valid_ids = {c.claim_id for c in valid_claims}
        logger.info(f"[Runtime] {len(valid_claims)} claims valides à {as_of}")

        # Étape 2 — Qdrant pour la pertinence sémantique
        rag_chunks = self._retrieve_qdrant(resolved.raw_query, plan)

        # Étape 3 — intersection (claims valides ET pertinents)
        relevant_valid = [c for c in rag_chunks if c.get("claim_id") in valid_ids]

        if relevant_valid:
            logger.info(f"[Runtime] {len(relevant_valid)} claims valides ET pertinents")
            return relevant_valid

        # Étape 4 — fallback : chunks KG bruts (cohérence temporelle prioritaire)
        logger.info(f"[Runtime] Intersection vide → fallback sur top {plan.qdrant_top_k} claims valides")
        return [_temporal_result_to_chunk(c) for c in valid_claims[: plan.qdrant_top_k]]

    def _retrieve_temporal_diff(
        self, resolved: ResolvedQuery, plan: RetrievalPlan
    ) -> list[dict]:
        """
        Mode DIFF_EVOLUTION : claims qui ont changé entre period_start et period_end.

        Catégories produites par TemporalRetriever :
        - introduced (publiés dans la période)
        - retired (validity_end dans la période)
        - modified (via SUPERSEDES dans la période)
        """
        if not resolved.temporal_range:
            return []
        period_start, period_end = resolved.temporal_range

        try:
            diff_claims = self.temporal_retriever.retrieve_diff(
                period_start=period_start,
                period_end=period_end,
                limit=plan.qdrant_top_k,
            )
        except Exception as e:
            logger.warning(f"[Runtime] TemporalRetriever.diff failed: {e}")
            return []

        logger.info(
            f"[Runtime] DIFF [{period_start} → {period_end}]: {len(diff_claims)} claims"
            f" ({sum(1 for c in diff_claims if c.diff_change_type == 'introduced')} intro, "
            f"{sum(1 for c in diff_claims if c.diff_change_type == 'retired')} retired, "
            f"{sum(1 for c in diff_claims if c.diff_change_type == 'modified')} modified)"
        )

        return [_temporal_result_to_chunk(c) for c in diff_claims]

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
                  b.publication_date AS b_pub, b.validity_start AS b_vstart,
                  b.lifecycle_status AS b_lifecycle,
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

    def _kg_lookup_for_signals(self, claim_ids: list[str]) -> dict:
        """
        Lookup Cypher pour détection des signaux UNRESOLVED_CONFLICT + MULTI_VERSION.

        Pour chaque claim_id, on cherche :
        - les CONFLICTs (haute confidence) qui le touchent
        - les SUPERSEDES entrants ET sortants (qty)
        """
        if not claim_ids:
            return {"conflicts": [], "supersedes_in": [], "supersedes_out": []}

        with self.neo4j_driver.session() as s:
            # Conflicts touching claim_ids
            conflict_rows = s.run("""
                MATCH (a:Claim)-[r:LOGICAL_RELATION {type: 'CONFLICT'}]-(b:Claim)
                WHERE a.tenant_id = $tid AND a.claim_id IN $ids
                  AND r.confidence >= 0.85
                  AND coalesce(r.legacy, false) = false
                  AND coalesce(r.is_contradiction, false) = true
                RETURN a.claim_id AS claim_id, count(distinct r) AS conflict_count
            """, tid=self.tenant_id, ids=claim_ids).data()

            sup_in_rows = s.run("""
                MATCH (newer:Claim)-[r:LOGICAL_RELATION {type: 'SUPERSEDES'}]->(target:Claim)
                WHERE target.tenant_id = $tid AND target.claim_id IN $ids
                  AND coalesce(r.legacy, false) = false
                RETURN target.claim_id AS claim_id, count(distinct r) AS n_in
            """, tid=self.tenant_id, ids=claim_ids).data()

            sup_out_rows = s.run("""
                MATCH (target:Claim)-[r:LOGICAL_RELATION {type: 'SUPERSEDES'}]->(older:Claim)
                WHERE target.tenant_id = $tid AND target.claim_id IN $ids
                  AND coalesce(r.legacy, false) = false
                RETURN target.claim_id AS claim_id, count(distinct r) AS n_out
            """, tid=self.tenant_id, ids=claim_ids).data()

        return {
            "conflicts": [{"claim_id": r["claim_id"], "conflict_count": r["conflict_count"]} for r in conflict_rows],
            "supersedes_in": [{"claim_id": r["claim_id"], "n_in": r["n_in"]} for r in sup_in_rows],
            "supersedes_out": [{"claim_id": r["claim_id"], "n_out": r["n_out"]} for r in sup_out_rows],
        }

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

    def _synthesize_short_answer(
        self,
        question: str,
        top_chunks: list[dict],
        resolved: Optional[ResolvedQuery] = None,
    ) -> Optional[str]:
        """Appel vLLM pour synthèse 1-3 phrases (mode-aware)."""
        context_parts = []
        for i, c in enumerate(top_chunks, 1):
            doc = c.get("doc_id", "?")
            text = (c.get("text") or "").strip()[:400]
            metadata = []
            if c.get("publication_date"):
                metadata.append(f"pub: {c['publication_date']}")
            if c.get("validity_start"):
                metadata.append(f"valid_from: {c['validity_start']}")
            if c.get("validity_end"):
                metadata.append(f"valid_until: {c['validity_end']}")
            if c.get("lifecycle_status") and c["lifecycle_status"] != "UNKNOWN":
                metadata.append(f"status: {c['lifecycle_status']}")
            if c.get("diff_change_type"):
                metadata.append(f"diff: {c['diff_change_type']}")
            meta_str = " · ".join(metadata) if metadata else ""
            context_parts.append(f"[{i}] doc={doc} {meta_str}\n{text}")

        context = "\n\n".join(context_parts)

        # Mode-aware instruction (R3+R4 calibration)
        mode_str = resolved.mode.value if resolved and resolved.mode else "UNKNOWN"
        mode_instruction = MODE_INSTRUCTIONS.get(mode_str, "")
        # Hint temporel pour SNAPSHOT/DIFF
        mode_hint = ""
        if resolved:
            if resolved.temporal_anchor:
                mode_hint = f" (point-in-time: {resolved.temporal_anchor.isoformat()})"
            elif resolved.temporal_range:
                mode_hint = f" (period: {resolved.temporal_range[0].isoformat()} → {resolved.temporal_range[1].isoformat()})"

        prompt = SYNTHESIS_PROMPT.format(
            question=question,
            context=context,
            mode=mode_str,
            mode_hint=mode_hint,
            mode_instruction=mode_instruction,
        )

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
