"""
Service KG Health Score — evaluation intrinseque de la qualite du Knowledge Graph.

Objectif : produire un diagnostic multi-axes (Provenance, Structure, Distribution,
Coherence) sans dependre d'un corpus de questions. Les seuils sont calibres sur les
donnees reelles (tenant 'default', avril 2026).

Architecture :
- Une unique session Neo4j pour toutes les requetes (perf)
- 6 requetes Cypher "socle" + 3 metriques reemployees depuis l'existant
- Weak Connected Components via GDS (Neo4j Graph Data Science)
- Temps de calcul cible : < 3s sur corpus actuel (~10K claims, 5K entities)

Pondérations globales :
    Provenance   25%  (Tracabilite 10 + Diversite 10 + Canonicalisation 5)
    Structure    35%  (Facet linkage 20 + Anti-orphelins 10 + Subject resolved 5)
    Distribution 20%  (Entropie 10 + Richesse 5 + Anti-hub 5)
    Coherence    20%  (Contradictions 5 + Classification tensions 5 +
                       Densite relations 3 + Claims connectes 3 +
                       Composante geante 2 + Perspective 2)
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from knowbase.api.schemas.kg_health import (
    ActionablesPanel,
    DocLinkageRow,
    FamilyScore,
    HubRow,
    KGHealthCorpusSummary,
    KGHealthDrilldownResponse,
    KGHealthScoreResponse,
    Metric,
    MetricStatus,
    SingletonStats,
)

logger = logging.getLogger("[OSMOSE] kg_health")


# ── Seuils calibres (tenant 'default', avril 2026) ─────────────────────
# Format : (green_min, yellow_min) — sous yellow_min = red

THRESHOLDS: Dict[str, Tuple[float, float]] = {
    # Provenance
    "verbatim_traceability": (0.70, 0.40),
    "source_diversity_2plus": (0.30, 0.15),
    "canonicalization_rate": (0.70, 0.40),
    # Structure
    "claim_facet_linkage": (0.70, 0.40),
    "claim_entity_linkage": (0.85, 0.70),
    "non_orphan_entities": (0.90, 0.75),  # inverse du taux d'orphelins
    "doc_subject_resolved": (0.70, 0.40),
    # Distribution
    "normalized_entropy": (0.65, 0.45),
    "richness_normalized": (0.60, 0.30),
    "non_hub_dominance": (0.95, 0.85),  # 1 - max_share
    # Coherence
    "non_contradiction_rate": (0.95, 0.85),
    "contradiction_classification_rate": (0.90, 0.50),
    "relation_density_normalized": (0.70, 0.30),
    "non_isolated_claims_rate": (0.50, 0.20),
    "giant_component_ratio": (0.80, 0.60),
    "perspective_freshness": (0.80, 0.40),
}


def classify(value: float, key: str) -> MetricStatus:
    """Retourne le status (green/yellow/red) d'une metrique normalisee [0,1]."""
    green_min, yellow_min = THRESHOLDS[key]
    if value >= green_min:
        return MetricStatus(zone="green", label="Bon")
    if value >= yellow_min:
        return MetricStatus(zone="yellow", label="A surveiller")
    return MetricStatus(zone="red", label="Critique")


def classify_score(score: float) -> MetricStatus:
    """Classification d'un score 0-100 (famille ou global)."""
    if score >= 70:
        return MetricStatus(zone="green", label="Bon")
    if score >= 40:
        return MetricStatus(zone="yellow", label="A surveiller")
    return MetricStatus(zone="red", label="Critique")


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


# ── Service ────────────────────────────────────────────────────────────


class KGHealthService:
    """Calcule le KG Health Score pour un tenant donne."""

    def __init__(self):
        from knowbase.common.clients.neo4j_client import get_neo4j_client

        self._client = get_neo4j_client()

    # ── Point d'entree principal ───────────────────────────────────────

    def compute_score(self, tenant_id: str) -> KGHealthScoreResponse:
        start = time.time()

        with self._client.driver.session() as session:
            # Pre-calcul des agregats partages (evite les doublons de queries)
            stats = self._fetch_base_stats(session, tenant_id)

            provenance = self._compute_provenance(session, tenant_id, stats)
            structure = self._compute_structure(session, tenant_id, stats)
            distribution = self._compute_distribution(session, tenant_id, stats)
            coherence = self._compute_coherence(session, tenant_id, stats)

            actionables = self._compute_actionables(session, tenant_id, stats)

        # Score global pondere
        weights = {
            "provenance": 0.25,
            "structure": 0.35,
            "distribution": 0.20,
            "coherence": 0.20,
        }
        global_score = (
            provenance.score * weights["provenance"]
            + structure.score * weights["structure"]
            + distribution.score * weights["distribution"]
            + coherence.score * weights["coherence"]
        )
        global_score = round(global_score, 1)

        summary = KGHealthCorpusSummary(
            total_claims=stats["total_claims"],
            total_entities=stats["total_entities"],
            total_facets=stats["total_facets"],
            total_documents=stats["total_documents"],
            total_contradictions=stats["total_contradictions"],
        )

        duration_ms = int((time.time() - start) * 1000)
        logger.info(f"[kg_health] Score compute: {duration_ms}ms, global={global_score}")

        return KGHealthScoreResponse(
            global_score=global_score,
            global_status=classify_score(global_score),
            families=[provenance, structure, distribution, coherence],
            summary=summary,
            actionables=actionables,
            computed_at=datetime.utcnow(),
            compute_duration_ms=duration_ms,
        )

    # ── Agregats partages ──────────────────────────────────────────────

    def _fetch_base_stats(self, session, tenant_id: str) -> Dict[str, Any]:
        """Une seule passe sur le KG pour recuperer les compteurs partages."""
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WITH count(c) AS total_claims,
                 count(DISTINCT c.doc_id) AS total_documents,
                 sum(CASE WHEN NOT (c)-[:ABOUT]->(:Entity) THEN 1 ELSE 0 END) AS claims_no_entity,
                 sum(CASE WHEN NOT (c)-[:BELONGS_TO_FACET]->(:Facet) THEN 1 ELSE 0 END) AS claims_no_facet,
                 sum(CASE WHEN c.verbatim_quote IS NOT NULL AND c.verbatim_quote <> '' THEN 1 ELSE 0 END) AS claims_with_verbatim
            MATCH (e:Entity {tenant_id: $tid})
            WITH total_claims, total_documents, claims_no_entity, claims_no_facet, claims_with_verbatim,
                 count(e) AS total_entities,
                 sum(CASE WHEN NOT (:Claim)-[:ABOUT]->(e) THEN 1 ELSE 0 END) AS orphan_entities,
                 sum(CASE WHEN (e)-[:SAME_CANON_AS]->(:CanonicalEntity) THEN 1 ELSE 0 END) AS canonicalized_entities
            OPTIONAL MATCH (f:Facet {tenant_id: $tid})
            WHERE f.lifecycle IS NULL OR f.lifecycle <> 'deprecated'
            WITH total_claims, total_documents, claims_no_entity, claims_no_facet, claims_with_verbatim,
                 total_entities, orphan_entities, canonicalized_entities,
                 count(f) AS total_facets
            RETURN total_claims, total_documents, total_entities, total_facets,
                   claims_no_entity, claims_no_facet, claims_with_verbatim,
                   orphan_entities, canonicalized_entities
            """,
            tid=tenant_id,
        ).single()

        # Contradictions : total + classifiees + distribution par level
        # (fix PR1 : ne plus filtrer sur tension_level='hard' uniquement, qui renvoyait 0)
        contra_result = session.run(
            """
            MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS]-(c2:Claim)
            WHERE c1.claim_id < c2.claim_id
            WITH r,
                 coalesce(r.tension_level, 'NULL') AS level
            RETURN count(*) AS total,
                   sum(CASE WHEN level = 'hard' THEN 1 ELSE 0 END) AS hard_total,
                   sum(CASE WHEN level = 'soft' THEN 1 ELSE 0 END) AS soft_total,
                   sum(CASE WHEN level = 'none' THEN 1 ELSE 0 END) AS none_total,
                   sum(CASE WHEN level <> 'NULL' THEN 1 ELSE 0 END) AS classified_total
            """,
            tid=tenant_id,
        ).single()

        # Relations claim <-> claim (toutes natures) + claims isoles
        relations_result = session.run(
            """
            MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS|REFINES|QUALIFIES|COMPLEMENTS|SPECIALIZES|CHAINS_TO|EVOLVES_TO]-(c2:Claim)
            WHERE c1.claim_id < c2.claim_id
            RETURN count(DISTINCT r) AS total_relations
            """,
            tid=tenant_id,
        ).single()

        isolated_result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WITH count(c) AS total,
                 sum(CASE WHEN NOT EXISTS {
                     MATCH (c)-[:CONTRADICTS|REFINES|QUALIFIES|COMPLEMENTS|SPECIALIZES|CHAINS_TO|EVOLVES_TO]-(:Claim)
                 } THEN 1 ELSE 0 END) AS isolated
            RETURN total, isolated
            """,
            tid=tenant_id,
        ).single()

        # DocumentContext : % resolved
        ctx_result = session.run(
            """
            MATCH (ctx:DocumentContext {tenant_id: $tid})
            WITH count(ctx) AS total_ctx,
                 sum(CASE WHEN ctx.resolution_status = 'resolved' THEN 1 ELSE 0 END) AS resolved
            RETURN total_ctx, resolved
            """,
            tid=tenant_id,
        ).single()

        return {
            "total_claims": result["total_claims"] or 0,
            "total_documents": result["total_documents"] or 0,
            "total_entities": result["total_entities"] or 0,
            "total_facets": result["total_facets"] or 0,
            "claims_no_entity": result["claims_no_entity"] or 0,
            "claims_no_facet": result["claims_no_facet"] or 0,
            "claims_with_verbatim": result["claims_with_verbatim"] or 0,
            "orphan_entities": result["orphan_entities"] or 0,
            "canonicalized_entities": result["canonicalized_entities"] or 0,
            "total_contradictions": contra_result["total"] or 0,
            "hard_contradictions": contra_result["hard_total"] or 0,
            "soft_contradictions": contra_result["soft_total"] or 0,
            "none_contradictions": contra_result["none_total"] or 0,
            "classified_contradictions": contra_result["classified_total"] or 0,
            "total_claim_relations": relations_result["total_relations"] or 0,
            "isolated_claims": isolated_result["isolated"] or 0,
            "total_ctx": ctx_result["total_ctx"] or 0,
            "resolved_ctx": ctx_result["resolved"] or 0,
        }

    # ── Famille 1 — Provenance (25%) ───────────────────────────────────

    def _compute_provenance(self, session, tenant_id: str, stats: Dict[str, Any]) -> FamilyScore:
        total_claims = max(stats["total_claims"], 1)
        total_entities = max(stats["total_entities"], 1)

        # M1.1 — Tracabilite verbatim
        verbatim_rate = stats["claims_with_verbatim"] / total_claims
        m_verbatim = Metric(
            key="verbatim_traceability",
            label="Tracabilite verbatim",
            description="% de claims avec une citation verbatim du texte source",
            value=round(verbatim_rate, 4),
            display_value=_fmt_pct(verbatim_rate),
            weight=0.40,
            status=classify(verbatim_rate, "verbatim_traceability"),
        )

        # M1.2 — Diversite multi-source (Q5)
        diversity_row = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
            WITH e.normalized_name AS subject, c.claim_type AS predicate,
                 count(DISTINCT c.doc_id) AS source_count
            WITH count(*) AS total_facts,
                 sum(CASE WHEN source_count >= 2 THEN 1 ELSE 0 END) AS multi_source
            RETURN total_facts, multi_source
            """,
            tid=tenant_id,
        ).single()
        total_facts = max(diversity_row["total_facts"] or 0, 1)
        multi_source = diversity_row["multi_source"] or 0
        diversity_rate = multi_source / total_facts
        m_diversity = Metric(
            key="source_diversity_2plus",
            label="Diversite multi-source",
            description=f"% de faits (subject+predicat) supportes par >= 2 documents ({multi_source}/{total_facts})",
            value=round(diversity_rate, 4),
            display_value=_fmt_pct(diversity_rate),
            weight=0.40,
            status=classify(diversity_rate, "source_diversity_2plus"),
        )

        # M1.3 — Canonicalisation des entites
        canon_rate = stats["canonicalized_entities"] / total_entities
        m_canon = Metric(
            key="canonicalization_rate",
            label="Canonicalisation entites",
            description=f"% d'Entity reliees a une CanonicalEntity ({stats['canonicalized_entities']}/{total_entities})",
            value=round(canon_rate, 4),
            display_value=_fmt_pct(canon_rate),
            weight=0.20,
            status=classify(canon_rate, "canonicalization_rate"),
        )

        metrics = [m_verbatim, m_diversity, m_canon]
        score = self._family_score(metrics)
        return FamilyScore(
            name="provenance",
            label="Provenance",
            score=score,
            status=classify_score(score),
            weight=0.25,
            metrics=metrics,
        )

    # ── Famille 2 — Structure (35%) ────────────────────────────────────

    def _compute_structure(self, session, tenant_id: str, stats: Dict[str, Any]) -> FamilyScore:
        total_claims = max(stats["total_claims"], 1)
        total_entities = max(stats["total_entities"], 1)

        # M2.1 — Claim -> Facet linkage (la plus critique)
        facet_linkage = 1 - (stats["claims_no_facet"] / total_claims)
        m_facet = Metric(
            key="claim_facet_linkage",
            label="Linkage Claim -> Facet",
            description=f"% de claims rattaches a au moins une Facet ({total_claims - stats['claims_no_facet']}/{total_claims})",
            value=round(facet_linkage, 4),
            display_value=_fmt_pct(facet_linkage),
            weight=0.55,
            status=classify(facet_linkage, "claim_facet_linkage"),
            drilldown_available=True,
            drilldown_key="worst_docs",
        )

        # M2.2 — Anti-orphelins (Entity)
        orphan_rate = stats["orphan_entities"] / total_entities
        non_orphan = 1 - orphan_rate
        m_orphan = Metric(
            key="non_orphan_entities",
            label="Entites non-orphelines",
            description=f"% d'Entity referencees par au moins un Claim ({total_entities - stats['orphan_entities']}/{total_entities})",
            value=round(non_orphan, 4),
            display_value=_fmt_pct(non_orphan),
            weight=0.25,
            status=classify(non_orphan, "non_orphan_entities"),
        )

        # M2.3 — Subject resolution (DocumentContext)
        total_ctx = max(stats["total_ctx"], 1)
        subject_resolved_rate = stats["resolved_ctx"] / total_ctx
        m_subject = Metric(
            key="doc_subject_resolved",
            label="Sujet de document resolu",
            description=f"% de DocumentContext avec sujet principal resolu ({stats['resolved_ctx']}/{total_ctx})",
            value=round(subject_resolved_rate, 4),
            display_value=_fmt_pct(subject_resolved_rate),
            weight=0.20,
            status=classify(subject_resolved_rate, "doc_subject_resolved"),
        )

        metrics = [m_facet, m_orphan, m_subject]
        score = self._family_score(metrics)
        return FamilyScore(
            name="structure",
            label="Structure",
            score=score,
            status=classify_score(score),
            weight=0.35,
            metrics=metrics,
        )

    # ── Famille 3 — Distribution (20%) ─────────────────────────────────

    def _compute_distribution(self, session, tenant_id: str, stats: Dict[str, Any]) -> FamilyScore:
        total_claims = max(stats["total_claims"], 1)
        total_documents = max(stats["total_documents"], 1)
        total_entities = max(stats["total_entities"], 1)

        # M3.1 — Entropie Shannon sur claim_type (Q4)
        entropy_rows = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WITH c.claim_type AS ctype, count(*) AS n
            RETURN ctype, n
            """,
            tid=tenant_id,
        ).values()

        total_n = sum(row[1] for row in entropy_rows) or 1
        distinct_types = max(len(entropy_rows), 1)
        if distinct_types > 1:
            entropy = 0.0
            for _, n in entropy_rows:
                p = n / total_n
                if p > 0:
                    entropy += -p * math.log2(p)
            normalized_entropy = entropy / math.log2(distinct_types)
        else:
            normalized_entropy = 0.0

        m_entropy = Metric(
            key="normalized_entropy",
            label="Diversite des types de claim",
            description=f"Entropie normalisee sur {distinct_types} types (Shannon / log2(N))",
            value=round(normalized_entropy, 4),
            display_value=f"{normalized_entropy:.2f}",
            weight=0.50,
            status=classify(normalized_entropy, "normalized_entropy"),
        )

        # M3.2 — Richesse (entities par document, cap 50)
        entities_per_doc = total_entities / total_documents
        richness_normalized = min(entities_per_doc / 50.0, 1.0)
        m_richness = Metric(
            key="richness_normalized",
            label="Richesse par document",
            description=f"{entities_per_doc:.1f} entites par document en moyenne (cap 50 = 100%)",
            value=round(richness_normalized, 4),
            display_value=f"{entities_per_doc:.1f} e/doc",
            weight=0.25,
            status=classify(richness_normalized, "richness_normalized"),
        )

        # M3.3 — Anti-hub dominance (Q3 : max share)
        hub_row = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim)
            WITH e, count(c) AS cc
            WITH collect({name: e.normalized_name, claims: cc}) AS entities, sum(cc) AS total
            UNWIND entities AS entity
            WITH entity, toFloat(entity.claims) / total AS share
            RETURN entity.name AS name, share
            ORDER BY share DESC LIMIT 1
            """,
            tid=tenant_id,
        ).single()
        max_share = (hub_row["share"] if hub_row else 0.0) or 0.0
        non_hub_score = 1 - max_share
        m_hub = Metric(
            key="non_hub_dominance",
            label="Absence de hub anormal",
            description=f"Top entite = {max_share * 100:.2f}% du total (anomalie > 15%)",
            value=round(non_hub_score, 4),
            display_value=f"{non_hub_score * 100:.1f}%",
            weight=0.25,
            status=classify(non_hub_score, "non_hub_dominance"),
            drilldown_available=True,
            drilldown_key="top_hubs",
        )

        metrics = [m_entropy, m_richness, m_hub]
        score = self._family_score(metrics)
        return FamilyScore(
            name="distribution",
            label="Distribution",
            score=score,
            status=classify_score(score),
            weight=0.20,
            metrics=metrics,
        )

    # ── Famille 4 — Coherence (20%) ────────────────────────────────────

    def _compute_coherence(self, session, tenant_id: str, stats: Dict[str, Any]) -> FamilyScore:
        total_claims = max(stats["total_claims"], 1)
        total_contra = max(stats["total_contradictions"], 1)  # evite div/0 si 0 contra

        # M4.1 — Signal contradictions : severite ponderee
        # Poids : hard=1.0, soft=0.3, none=0.0, unknown/NULL=0.7
        unclassified_contra = total_contra - stats["classified_contradictions"]
        weighted_contra_count = (
            stats["hard_contradictions"] * 1.0
            + stats["soft_contradictions"] * 0.3
            + stats["none_contradictions"] * 0.0
            + unclassified_contra * 0.7
        )
        burden_rate = weighted_contra_count / total_claims if total_claims > 0 else 0.0
        non_contra = 1 - min(burden_rate, 1.0)
        m_contra = Metric(
            key="non_contradiction_rate",
            label="Signal contradictions",
            description=(
                f"{stats['total_contradictions']} contradictions "
                f"(hard={stats['hard_contradictions']}, soft={stats['soft_contradictions']}, "
                f"none={stats['none_contradictions']}, unclassif.={unclassified_contra})"
            ),
            value=round(non_contra, 4),
            display_value=f"{non_contra * 100:.2f}%",
            weight=0.25,
            status=classify(non_contra, "non_contradiction_rate"),
        )

        # M4.2 — Taux de classification des tensions (PR1 observabilite)
        if stats["total_contradictions"] > 0:
            classif_rate = stats["classified_contradictions"] / stats["total_contradictions"]
        else:
            classif_rate = 1.0  # Pas de contradictions = rien a classifier
        m_classif = Metric(
            key="contradiction_classification_rate",
            label="Classification des tensions",
            description=(
                f"{stats['classified_contradictions']}/{stats['total_contradictions']} "
                f"contradictions avec tension_level renseigne"
            ),
            value=round(classif_rate, 4),
            display_value=_fmt_pct(classif_rate),
            weight=0.25,
            status=classify(classif_rate, "contradiction_classification_rate"),
        )

        # M4.3 — Densite des relations claim-claim
        # Target : 0.5 relation/claim = saturation (100%), 0 = 0%
        relations = stats["total_claim_relations"]
        density_raw = relations / total_claims
        density_normalized = min(density_raw / 0.5, 1.0)
        m_density = Metric(
            key="relation_density_normalized",
            label="Densite des relations",
            description=f"{relations} relations claim<->claim / {total_claims} claims = {density_raw:.2f} rel/claim",
            value=round(density_normalized, 4),
            display_value=f"{density_raw:.2f} rel/claim",
            weight=0.15,
            status=classify(density_normalized, "relation_density_normalized"),
        )

        # M4.4 — Claims connectes (non isoles)
        isolated = stats["isolated_claims"]
        connected_rate = 1 - (isolated / total_claims)
        m_connected = Metric(
            key="non_isolated_claims_rate",
            label="Claims connectes",
            description=f"{total_claims - isolated}/{total_claims} claims ont >= 1 relation claim<->claim",
            value=round(connected_rate, 4),
            display_value=_fmt_pct(connected_rate),
            weight=0.15,
            status=classify(connected_rate, "non_isolated_claims_rate"),
        )

        # M4.5 — Composante geante (Q6, GDS)
        giant_ratio, singleton_stats = self._compute_giant_component(session, tenant_id)
        m_giant = Metric(
            key="giant_component_ratio",
            label="Composante principale",
            description=f"{giant_ratio * 100:.1f}% du graphe fait partie de la composante geante",
            value=round(giant_ratio, 4),
            display_value=_fmt_pct(giant_ratio),
            weight=0.10,
            status=classify(giant_ratio, "giant_component_ratio"),
        )

        # M4.6 — Perspective freshness
        freshness_value, freshness_status = self._compute_perspective_freshness(session, tenant_id)
        m_perspective = Metric(
            key="perspective_freshness",
            label="Fraicheur Perspective",
            description=f"Statut : {freshness_status}",
            value=round(freshness_value, 4),
            display_value=freshness_status,
            weight=0.10,
            status=classify(freshness_value, "perspective_freshness"),
        )

        metrics = [m_contra, m_classif, m_density, m_connected, m_giant, m_perspective]
        score = self._family_score(metrics)

        # Stasher singleton_stats + perspective_status pour actionables
        self._cached_singletons = singleton_stats
        self._cached_perspective_status = freshness_status

        return FamilyScore(
            name="coherence",
            label="Coherence",
            score=score,
            status=classify_score(score),
            weight=0.20,
            metrics=metrics,
        )

    def _compute_giant_component(self, session, tenant_id: str) -> Tuple[float, Optional[SingletonStats]]:
        """Projette un graphe GDS, calcule WCC, retourne ratio + stats singletons."""
        graph_name = f"kg_health_{tenant_id}_{int(time.time())}"

        try:
            # Projection
            session.run(
                """
                CALL gds.graph.project.cypher(
                  $gname,
                  'MATCH (n) WHERE n.tenant_id = $tid AND (n:Claim OR n:Entity OR n:Facet) RETURN id(n) AS id',
                  'MATCH (c:Claim {tenant_id: $tid})-[r:ABOUT|BELONGS_TO_FACET]-(x) RETURN id(c) AS source, id(x) AS target',
                  {parameters: {tid: $tid}}
                )
                YIELD graphName
                RETURN graphName
                """,
                gname=graph_name,
                tid=tenant_id,
            ).consume()

            # WCC stats
            wcc = session.run(
                f"""
                CALL gds.wcc.stream('{graph_name}')
                YIELD componentId, nodeId
                WITH componentId, count(nodeId) AS size
                WITH count(*) AS total_components,
                     sum(CASE WHEN size = 1 THEN 1 ELSE 0 END) AS singletons,
                     max(size) AS largest,
                     sum(size) AS total_nodes
                RETURN total_components, singletons, largest, total_nodes
                """
            ).single()

            total_nodes = wcc["total_nodes"] or 0
            largest = wcc["largest"] or 0
            total_components = wcc["total_components"] or 0
            singletons = wcc["singletons"] or 0

            giant_ratio = (largest / total_nodes) if total_nodes > 0 else 0.0
            singleton_rate = (singletons / total_components) if total_components > 0 else 0.0

            stats = SingletonStats(
                total_components=total_components,
                singletons=singletons,
                singleton_rate=round(singleton_rate, 4),
                giant_component_size=largest,
                giant_component_pct=round(giant_ratio * 100, 2),
            )
            return giant_ratio, stats
        except Exception as e:
            logger.warning(f"[kg_health] GDS WCC failed: {e}")
            return 0.0, None
        finally:
            # Cleanup systematique
            try:
                session.run(
                    f"CALL gds.graph.drop('{graph_name}', false) YIELD graphName RETURN graphName"
                ).consume()
            except Exception:
                pass

    def _compute_perspective_freshness(self, session, tenant_id: str) -> Tuple[float, str]:
        """Reprend la logique de claimfirst/stats."""
        try:
            row = session.run(
                """
                MATCH (p:Perspective {tenant_id: $tid})
                WITH count(p) AS pcount, max(p.updated_at) AS last_build
                OPTIONAL MATCH (c:Claim {tenant_id: $tid})
                WHERE last_build IS NOT NULL AND c.created_at > last_build
                RETURN pcount, last_build, count(c) AS new_claims
                """,
                tid=tenant_id,
            ).single()

            pcount = row["pcount"] or 0
            new_claims = row["new_claims"] or 0

            if pcount == 0:
                return 0.0, "no_perspectives"
            if new_claims < 50:
                return 1.0, "fresh"
            if new_claims < 200:
                return 0.5, "warning"
            return 0.0, "stale"
        except Exception as e:
            logger.debug(f"[kg_health] Perspective freshness failed: {e}")
            return 0.0, "unknown"

    # ── Actionables ────────────────────────────────────────────────────

    def _compute_actionables(self, session, tenant_id: str, stats: Dict[str, Any]) -> ActionablesPanel:
        # Top 10 docs mal extraits
        worst_docs_rows = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WITH c.doc_id AS doc_id, count(c) AS claims_total,
                 sum(CASE WHEN (c)-[:BELONGS_TO_FACET]->(:Facet) THEN 1 ELSE 0 END) AS claims_with_facet
            OPTIONAL MATCH (ctx:DocumentContext {doc_id: doc_id, tenant_id: $tid})
            WITH doc_id, claims_total, claims_with_facet,
                 toFloat(claims_with_facet) / claims_total AS linkage_rate,
                 coalesce(ctx.resolution_status, 'MISSING_CONTEXT') AS subject_status
            WHERE claims_total >= 5
            RETURN doc_id, claims_total, linkage_rate, subject_status
            ORDER BY linkage_rate ASC
            LIMIT 10
            """,
            tid=tenant_id,
        )
        worst_docs = [
            DocLinkageRow(
                doc_id=r["doc_id"],
                claims_total=r["claims_total"],
                linkage_rate=round(r["linkage_rate"], 4),
                subject_status=r["subject_status"],
            )
            for r in worst_docs_rows
        ]

        # Top hubs > 1%
        hub_rows = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim)
            WITH e, count(c) AS cc
            WITH collect({name: e.normalized_name, claims: cc}) AS entities, sum(cc) AS total
            UNWIND entities AS entity
            WITH entity, toFloat(entity.claims) / total AS share
            WHERE share > 0.01
            RETURN entity.name AS name, entity.claims AS claims, share
            ORDER BY share DESC LIMIT 10
            """,
            tid=tenant_id,
        )
        top_hubs = [
            HubRow(
                entity=r["name"],
                claims=r["claims"],
                share_pct=round(r["share"] * 100, 2),
            )
            for r in hub_rows
        ]

        # Perspective staleness (compter new_claims pour affichage)
        new_claims_count = 0
        try:
            perspective_row = session.run(
                """
                MATCH (p:Perspective {tenant_id: $tid})
                WITH max(p.updated_at) AS last_build
                OPTIONAL MATCH (c:Claim {tenant_id: $tid})
                WHERE last_build IS NOT NULL AND c.created_at > last_build
                RETURN count(c) AS new_claims
                """,
                tid=tenant_id,
            ).single()
            new_claims_count = perspective_row["new_claims"] or 0
        except Exception:
            pass

        return ActionablesPanel(
            worst_docs=worst_docs,
            top_hubs=top_hubs,
            singleton_stats=getattr(self, "_cached_singletons", None),
            perspective_status=getattr(self, "_cached_perspective_status", None),
            perspective_new_claims=new_claims_count,
        )

    # ── Utilities ──────────────────────────────────────────────────────

    def _family_score(self, metrics: List[Metric]) -> float:
        """Score 0-100 d'une famille a partir de ses metriques ponderees."""
        total_weight = sum(m.weight for m in metrics) or 1.0
        weighted = sum(m.value * m.weight for m in metrics)
        return round((weighted / total_weight) * 100, 1)

    # ── Drilldown ──────────────────────────────────────────────────────

    def drilldown(self, key: str, tenant_id: str, limit: int = 30) -> KGHealthDrilldownResponse:
        """Retourne le top N detaille pour une metrique donnee."""
        with self._client.driver.session() as session:
            if key == "worst_docs":
                return self._drilldown_worst_docs(session, tenant_id, limit)
            if key == "top_hubs":
                return self._drilldown_top_hubs(session, tenant_id, limit)
            if key == "orphan_entities":
                return self._drilldown_orphan_entities(session, tenant_id, limit)
            raise ValueError(f"Unknown drilldown key: {key}")

    def _drilldown_worst_docs(self, session, tenant_id: str, limit: int) -> KGHealthDrilldownResponse:
        rows = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WITH c.doc_id AS doc_id, count(c) AS claims_total,
                 sum(CASE WHEN (c)-[:BELONGS_TO_FACET]->(:Facet) THEN 1 ELSE 0 END) AS claims_with_facet
            OPTIONAL MATCH (ctx:DocumentContext {doc_id: doc_id, tenant_id: $tid})
            WITH doc_id, claims_total, claims_with_facet,
                 toFloat(claims_with_facet) / claims_total AS linkage_rate,
                 coalesce(ctx.resolution_status, 'MISSING_CONTEXT') AS subject_status
            WHERE claims_total >= 5
            RETURN doc_id, claims_total, linkage_rate, subject_status
            ORDER BY linkage_rate ASC
            LIMIT $limit
            """,
            tid=tenant_id,
            limit=limit,
        )
        data = [
            {
                "doc_id": r["doc_id"],
                "claims_total": r["claims_total"],
                "linkage_pct": round(r["linkage_rate"] * 100, 1),
                "subject_status": r["subject_status"],
            }
            for r in rows
        ]
        return KGHealthDrilldownResponse(
            key="worst_docs",
            title="Top documents avec faible linkage Claim -> Facet",
            columns=["doc_id", "claims_total", "linkage_pct", "subject_status"],
            rows=data,
            total_available=len(data),
        )

    def _drilldown_top_hubs(self, session, tenant_id: str, limit: int) -> KGHealthDrilldownResponse:
        rows = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim)
            WITH e, count(c) AS cc
            WITH collect({name: e.normalized_name, claims: cc}) AS entities, sum(cc) AS total
            UNWIND entities AS entity
            WITH entity, toFloat(entity.claims) / total AS share
            WHERE share > 0.005
            RETURN entity.name AS name, entity.claims AS claims, share
            ORDER BY share DESC LIMIT $limit
            """,
            tid=tenant_id,
            limit=limit,
        )
        data = [
            {
                "entity": r["name"],
                "claims": r["claims"],
                "share_pct": round(r["share"] * 100, 2),
            }
            for r in rows
        ]
        return KGHealthDrilldownResponse(
            key="top_hubs",
            title="Entites dominantes (candidates a fusion ou filtrage)",
            columns=["entity", "claims", "share_pct"],
            rows=data,
            total_available=len(data),
        )

    def _drilldown_orphan_entities(self, session, tenant_id: str, limit: int) -> KGHealthDrilldownResponse:
        rows = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})
            WHERE NOT (:Claim)-[:ABOUT]->(e)
            RETURN e.normalized_name AS name, coalesce(e.entity_type, 'unknown') AS entity_type,
                   coalesce(e.mention_count, 0) AS mention_count
            ORDER BY mention_count DESC
            LIMIT $limit
            """,
            tid=tenant_id,
            limit=limit,
        )
        data = [
            {
                "entity": r["name"],
                "entity_type": r["entity_type"],
                "mention_count": r["mention_count"],
            }
            for r in rows
        ]
        return KGHealthDrilldownResponse(
            key="orphan_entities",
            title="Entites orphelines (non referencees par aucun Claim)",
            columns=["entity", "entity_type", "mention_count"],
            rows=data,
            total_available=len(data),
        )


# ── Singleton ──────────────────────────────────────────────────────────

_service: Optional[KGHealthService] = None


def get_kg_health_service() -> KGHealthService:
    global _service
    if _service is None:
        _service = KGHealthService()
    return _service
