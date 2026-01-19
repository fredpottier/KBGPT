"""
Pass 2 Quality Service - Métriques automatiques de qualité KG

Implémente le Niveau 1 du framework de contrôle qualité :
- A) Densité & couverture (segments, relations/segment)
- B) Taux de déduplication
- C) Vagueness score (relations molles)
- D) Hub explosion (concentration des degrés)
- E) Contradictions / cycles

Produit un verdict automatique :
- OK : métriques dans les normes
- TOO_PERMISSIVE : trop de bruit détecté
- TOO_RESTRICTIVE : couverture insuffisante

Author: Claude Code
Date: 2026-01
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import logging

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)


class QualityVerdict(str, Enum):
    """Verdict qualité automatique."""
    OK = "OK"
    TOO_PERMISSIVE = "TOO_PERMISSIVE"
    TOO_RESTRICTIVE = "TOO_RESTRICTIVE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Types de relations considérées comme "vagues"
VAGUE_RELATION_TYPES = {
    "associated_with",
    "related_to",
    "connected_to",
    "linked_to",
    "other",
}

# Seuils pour le verdict automatique
THRESHOLDS = {
    # Too Restrictive
    "min_coverage_pct": 10.0,           # < 10% segments traités
    "min_relations_per_segment": 2.0,   # < 2 relations/segment

    # Too Permissive
    "max_dup_ratio": 0.55,              # > 55% de doublons
    "max_vague_pct": 35.0,              # > 35% relations vagues
    "max_top1_degree_share": 0.20,      # > 20% sur un seul nœud
    "max_relations_per_segment": 10.0,  # > 10 relations/segment (suspect)

    # Cycles / Symétries (warning, pas blocking)
    "max_symmetric_ratio": 0.15,        # > 15% de paires symétriques
}


@dataclass
class DensityMetrics:
    """Métriques de densité et couverture."""
    segments_total: int
    segments_processed: int
    coverage_pct: float
    raw_relations: int
    unique_relations: int
    dup_ratio: float
    relations_per_segment: float
    relations_per_1k_chars: float = 0.0


@dataclass
class VaguenessMetrics:
    """Métriques de relations vagues."""
    total_relations: int
    vague_relations: int
    vague_pct: float
    vague_types_distribution: Dict[str, int] = field(default_factory=dict)


@dataclass
class HubMetrics:
    """Métriques de concentration des degrés."""
    total_edges: int
    top1_node: str
    top1_degree: int
    top1_degree_share: float
    top10_degree_share: float
    top10_nodes: List[Tuple[str, int]] = field(default_factory=list)


@dataclass
class CycleMetrics:
    """Métriques de cycles et symétries."""
    symmetric_pairs: int          # A→B et B→A avec même type
    symmetric_ratio: float
    short_cycles_3: int           # A→B→C→A
    problematic_pairs: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class QualityReport:
    """Rapport de qualité complet."""
    document_id: str
    verdict: QualityVerdict
    verdict_reasons: List[str]

    density: DensityMetrics
    vagueness: VaguenessMetrics
    hubs: HubMetrics
    cycles: CycleMetrics

    # Score global 0-100
    quality_score: float

    # Flags détaillés
    flags: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "verdict": self.verdict.value,
            "verdict_reasons": self.verdict_reasons,
            "quality_score": round(self.quality_score, 1),
            "density": {
                "segments_total": self.density.segments_total,
                "segments_processed": self.density.segments_processed,
                "coverage_pct": round(self.density.coverage_pct, 1),
                "raw_relations": self.density.raw_relations,
                "unique_relations": self.density.unique_relations,
                "dup_ratio": round(self.density.dup_ratio, 3),
                "relations_per_segment": round(self.density.relations_per_segment, 2),
            },
            "vagueness": {
                "total_relations": self.vagueness.total_relations,
                "vague_relations": self.vagueness.vague_relations,
                "vague_pct": round(self.vagueness.vague_pct, 1),
                "vague_types": self.vagueness.vague_types_distribution,
            },
            "hubs": {
                "total_edges": self.hubs.total_edges,
                "top1_node": self.hubs.top1_node,
                "top1_degree": self.hubs.top1_degree,
                "top1_degree_share": round(self.hubs.top1_degree_share, 3),
                "top10_degree_share": round(self.hubs.top10_degree_share, 3),
                "top10_nodes": [{"node": n, "degree": d} for n, d in self.hubs.top10_nodes],
            },
            "cycles": {
                "symmetric_pairs": self.cycles.symmetric_pairs,
                "symmetric_ratio": round(self.cycles.symmetric_ratio, 3),
                "short_cycles_3": self.cycles.short_cycles_3,
                "problematic_pairs": self.cycles.problematic_pairs[:5],  # Top 5
            },
            "flags": self.flags,
        }


class Pass2QualityService:
    """
    Service d'analyse qualité pour Pass 2.

    Calcule les métriques de qualité sur les relations extraites
    et produit un verdict automatique.
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        if neo4j_client is None:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        self.neo4j = neo4j_client
        self.tenant_id = tenant_id

    def analyze_document(self, document_id: str) -> Optional[QualityReport]:
        """
        Analyse la qualité des relations pour un document.

        Args:
            document_id: ID du document à analyser

        Returns:
            QualityReport ou None si données insuffisantes
        """
        try:
            # Calculer toutes les métriques
            density = self._compute_density_metrics(document_id)
            vagueness = self._compute_vagueness_metrics(document_id)
            hubs = self._compute_hub_metrics(document_id)
            cycles = self._compute_cycle_metrics(document_id)

            # Déterminer le verdict
            verdict, reasons, flags = self._compute_verdict(
                density, vagueness, hubs, cycles
            )

            # Calculer le score global
            quality_score = self._compute_quality_score(
                density, vagueness, hubs, cycles, flags
            )

            return QualityReport(
                document_id=document_id,
                verdict=verdict,
                verdict_reasons=reasons,
                density=density,
                vagueness=vagueness,
                hubs=hubs,
                cycles=cycles,
                quality_score=quality_score,
                flags=flags,
            )

        except Exception as e:
            logger.error(f"[Pass2Quality] Error analyzing {document_id}: {e}")
            return None

    def analyze_corpus(self) -> Dict[str, Any]:
        """
        Analyse la qualité globale du corpus.

        Returns:
            Dict avec métriques agrégées et verdicts par document
        """
        # Récupérer tous les documents avec des relations
        query = """
        MATCH (ra:RawAssertion {tenant_id: $tenant_id})
        RETURN DISTINCT ra.source_doc_id AS doc_id
        """
        results = self._execute_query(query, {"tenant_id": self.tenant_id})
        doc_ids = [r["doc_id"] for r in results if r["doc_id"]]

        reports = []
        for doc_id in doc_ids:
            report = self.analyze_document(doc_id)
            if report:
                reports.append(report)

        # Agréger
        if not reports:
            return {"status": "no_data", "documents": []}

        total_relations = sum(r.density.unique_relations for r in reports)
        avg_coverage = sum(r.density.coverage_pct for r in reports) / len(reports)
        avg_vague_pct = sum(r.vagueness.vague_pct for r in reports) / len(reports)

        verdicts_count = {v.value: 0 for v in QualityVerdict}
        for r in reports:
            verdicts_count[r.verdict.value] += 1

        return {
            "status": "analyzed",
            "documents_count": len(reports),
            "total_unique_relations": total_relations,
            "avg_coverage_pct": round(avg_coverage, 1),
            "avg_vague_pct": round(avg_vague_pct, 1),
            "verdicts_distribution": verdicts_count,
            "documents": [r.to_dict() for r in reports],
        }

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute une requête Cypher."""
        if not self.neo4j.driver:
            return []

        database = getattr(self.neo4j, 'database', 'neo4j')
        with self.neo4j.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def _compute_density_metrics(self, document_id: str) -> DensityMetrics:
        """Calcule les métriques de densité et couverture."""
        # Compter les segments (depuis les RawAssertions)
        query_segments = """
        MATCH (ra:RawAssertion {tenant_id: $tenant_id})
        WHERE ra.source_doc_id STARTS WITH $doc_prefix
        RETURN
            count(DISTINCT ra.source_chunk_id) AS segments_processed,
            count(ra) AS raw_relations
        """

        # Utiliser un préfixe pour matcher le document
        doc_prefix = document_id.split("_")[0] if "_" in document_id else document_id

        results = self._execute_query(query_segments, {
            "tenant_id": self.tenant_id,
            "doc_prefix": document_id
        })

        segments_processed = results[0]["segments_processed"] if results else 0
        raw_relations = results[0]["raw_relations"] if results else 0

        # Compter les relations uniques (CanonicalRelations)
        query_unique = """
        MATCH (cr:CanonicalRelation {tenant_id: $tenant_id})
        WHERE cr.subject_concept_id IN [
            c.canonical_id
            FOR c IN [(cc:CanonicalConcept)<-[:INSTANCE_OF]-(pc:ProtoConcept {document_id: $doc_id}) | cc]
        ] OR cr.object_concept_id IN [
            c.canonical_id
            FOR c IN [(cc:CanonicalConcept)<-[:INSTANCE_OF]-(pc:ProtoConcept {document_id: $doc_id}) | cc]
        ]
        RETURN count(cr) AS unique_relations
        """

        # Simplification: compter toutes les CanonicalRelations pour le tenant
        query_unique_simple = """
        MATCH (cr:CanonicalRelation {tenant_id: $tenant_id})
        RETURN count(cr) AS unique_relations
        """
        results_unique = self._execute_query(query_unique_simple, {
            "tenant_id": self.tenant_id
        })
        unique_relations = results_unique[0]["unique_relations"] if results_unique else 0

        # Estimer le total de segments (depuis les ProtoConcepts)
        query_total_segments = """
        MATCH (pc:ProtoConcept {doc_id: $doc_id, tenant_id: $tenant_id})
        RETURN count(DISTINCT pc.section_id) AS total_segments
        """
        results_total = self._execute_query(query_total_segments, {
            "doc_id": document_id,
            "tenant_id": self.tenant_id
        })
        segments_total = results_total[0]["total_segments"] if results_total else segments_processed

        # Calculer les ratios
        coverage_pct = (segments_processed / segments_total * 100) if segments_total > 0 else 0
        dup_ratio = 1 - (unique_relations / raw_relations) if raw_relations > 0 else 0
        relations_per_segment = raw_relations / segments_processed if segments_processed > 0 else 0

        return DensityMetrics(
            segments_total=segments_total,
            segments_processed=segments_processed,
            coverage_pct=coverage_pct,
            raw_relations=raw_relations,
            unique_relations=unique_relations,
            dup_ratio=max(0, dup_ratio),  # Éviter les valeurs négatives
            relations_per_segment=relations_per_segment,
        )

    def _compute_vagueness_metrics(self, document_id: str) -> VaguenessMetrics:
        """Calcule les métriques de relations vagues."""
        query = """
        MATCH (cr:CanonicalRelation {tenant_id: $tenant_id})
        RETURN cr.relation_type AS rel_type, count(cr) AS cnt
        """
        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        total = 0
        vague = 0
        vague_dist: Dict[str, int] = {}

        for r in results:
            rel_type = r["rel_type"] or "unknown"
            cnt = r["cnt"]
            total += cnt

            if rel_type.lower() in VAGUE_RELATION_TYPES:
                vague += cnt
                vague_dist[rel_type] = cnt

        vague_pct = (vague / total * 100) if total > 0 else 0

        return VaguenessMetrics(
            total_relations=total,
            vague_relations=vague,
            vague_pct=vague_pct,
            vague_types_distribution=vague_dist,
        )

    def _compute_hub_metrics(self, document_id: str) -> HubMetrics:
        """Calcule les métriques de concentration des degrés."""
        # Calculer le degré de chaque concept (entrant + sortant)
        query = """
        MATCH (cr:CanonicalRelation {tenant_id: $tenant_id})
        WITH cr.subject_concept_id AS concept, count(*) AS out_degree
        RETURN concept, out_degree AS degree
        UNION ALL
        MATCH (cr:CanonicalRelation {tenant_id: $tenant_id})
        WITH cr.object_concept_id AS concept, count(*) AS in_degree
        RETURN concept, in_degree AS degree
        """
        results = self._execute_query(query, {"tenant_id": self.tenant_id})

        # Agréger les degrés par concept
        degree_map: Dict[str, int] = {}
        for r in results:
            concept = r["concept"]
            if concept:
                degree_map[concept] = degree_map.get(concept, 0) + r["degree"]

        if not degree_map:
            return HubMetrics(
                total_edges=0,
                top1_node="",
                top1_degree=0,
                top1_degree_share=0,
                top10_degree_share=0,
            )

        # Trier par degré décroissant
        sorted_nodes = sorted(degree_map.items(), key=lambda x: x[1], reverse=True)
        total_edges = sum(d for _, d in sorted_nodes) // 2  # Chaque arête comptée 2 fois

        top1_node, top1_degree = sorted_nodes[0]
        top10 = sorted_nodes[:10]
        top10_degree_sum = sum(d for _, d in top10)

        # Le degree share est le ratio du degré sur le total des arêtes
        # Mais comme chaque arête contribue à 2 degrés, on normalise
        total_degree = sum(d for _, d in sorted_nodes)
        top1_share = top1_degree / total_degree if total_degree > 0 else 0
        top10_share = top10_degree_sum / total_degree if total_degree > 0 else 0

        return HubMetrics(
            total_edges=total_edges,
            top1_node=top1_node,
            top1_degree=top1_degree,
            top1_degree_share=top1_share,
            top10_degree_share=top10_share,
            top10_nodes=top10,
        )

    def _compute_cycle_metrics(self, document_id: str) -> CycleMetrics:
        """Calcule les métriques de cycles et symétries."""
        # Détecter les paires symétriques (A→B et B→A avec même type)
        query_symmetric = """
        MATCH (cr1:CanonicalRelation {tenant_id: $tenant_id})
        MATCH (cr2:CanonicalRelation {tenant_id: $tenant_id})
        WHERE cr1.subject_concept_id = cr2.object_concept_id
          AND cr1.object_concept_id = cr2.subject_concept_id
          AND cr1.relation_type = cr2.relation_type
          AND id(cr1) < id(cr2)
        RETURN
            cr1.subject_concept_id AS a,
            cr1.object_concept_id AS b,
            cr1.relation_type AS rel_type
        LIMIT 20
        """
        symmetric_results = self._execute_query(query_symmetric, {"tenant_id": self.tenant_id})

        symmetric_pairs = len(symmetric_results)
        problematic_pairs = [
            {"a": r["a"], "b": r["b"], "type": r["rel_type"]}
            for r in symmetric_results
        ]

        # Compter le total de relations pour le ratio
        query_total = """
        MATCH (cr:CanonicalRelation {tenant_id: $tenant_id})
        RETURN count(cr) AS total
        """
        total_results = self._execute_query(query_total, {"tenant_id": self.tenant_id})
        total_relations = total_results[0]["total"] if total_results else 1

        symmetric_ratio = (symmetric_pairs * 2) / total_relations if total_relations > 0 else 0

        # Cycles de longueur 3 (plus coûteux, limite)
        # Simplifié: on ne le calcule pas pour l'instant
        short_cycles_3 = 0

        return CycleMetrics(
            symmetric_pairs=symmetric_pairs,
            symmetric_ratio=symmetric_ratio,
            short_cycles_3=short_cycles_3,
            problematic_pairs=problematic_pairs,
        )

    def _compute_verdict(
        self,
        density: DensityMetrics,
        vagueness: VaguenessMetrics,
        hubs: HubMetrics,
        cycles: CycleMetrics
    ) -> Tuple[QualityVerdict, List[str], Dict[str, bool]]:
        """
        Calcule le verdict automatique basé sur les métriques.

        Returns:
            (verdict, reasons, flags)
        """
        flags = {
            "low_coverage": density.coverage_pct < THRESHOLDS["min_coverage_pct"],
            "low_relations_per_segment": density.relations_per_segment < THRESHOLDS["min_relations_per_segment"],
            "high_dup_ratio": density.dup_ratio > THRESHOLDS["max_dup_ratio"],
            "high_vague_pct": vagueness.vague_pct > THRESHOLDS["max_vague_pct"],
            "hub_explosion": hubs.top1_degree_share > THRESHOLDS["max_top1_degree_share"],
            "high_relations_per_segment": density.relations_per_segment > THRESHOLDS["max_relations_per_segment"],
            "high_symmetric_ratio": cycles.symmetric_ratio > THRESHOLDS["max_symmetric_ratio"],
        }

        reasons = []

        # Vérifier si données insuffisantes
        if density.raw_relations < 5:
            return QualityVerdict.INSUFFICIENT_DATA, ["Moins de 5 relations extraites"], flags

        # Compter les flags "too permissive"
        permissive_flags = sum([
            flags["high_dup_ratio"],
            flags["high_vague_pct"],
            flags["hub_explosion"],
            flags["high_relations_per_segment"],
        ])

        # Compter les flags "too restrictive"
        restrictive_flags = sum([
            flags["low_coverage"],
            flags["low_relations_per_segment"],
        ])

        # Décision
        if permissive_flags >= 2:
            verdict = QualityVerdict.TOO_PERMISSIVE
            if flags["high_dup_ratio"]:
                reasons.append(f"Taux de duplication élevé ({density.dup_ratio:.1%})")
            if flags["high_vague_pct"]:
                reasons.append(f"Trop de relations vagues ({vagueness.vague_pct:.1f}%)")
            if flags["hub_explosion"]:
                reasons.append(f"Concentration excessive sur {hubs.top1_node} ({hubs.top1_degree_share:.1%})")
            if flags["high_relations_per_segment"]:
                reasons.append(f"Trop de relations/segment ({density.relations_per_segment:.1f})")

        elif restrictive_flags >= 2 or (restrictive_flags >= 1 and density.raw_relations < 20):
            verdict = QualityVerdict.TOO_RESTRICTIVE
            if flags["low_coverage"]:
                reasons.append(f"Couverture faible ({density.coverage_pct:.1f}%)")
            if flags["low_relations_per_segment"]:
                reasons.append(f"Peu de relations/segment ({density.relations_per_segment:.1f})")
        else:
            verdict = QualityVerdict.OK
            reasons.append("Métriques dans les normes")

        # Ajouter warnings pour symétries
        if flags["high_symmetric_ratio"]:
            reasons.append(f"⚠️ {cycles.symmetric_pairs} paires symétriques détectées")

        return verdict, reasons, flags

    def _compute_quality_score(
        self,
        density: DensityMetrics,
        vagueness: VaguenessMetrics,
        hubs: HubMetrics,
        cycles: CycleMetrics,
        flags: Dict[str, bool]
    ) -> float:
        """
        Calcule un score de qualité global 0-100.

        Pondération:
        - Couverture: 25 points
        - Déduplication: 25 points
        - Vagueness: 25 points
        - Hub distribution: 15 points
        - Symétries: 10 points
        """
        score = 100.0

        # Couverture (25 pts)
        if density.coverage_pct < 10:
            score -= 25
        elif density.coverage_pct < 20:
            score -= 15
        elif density.coverage_pct < 25:
            score -= 5

        # Déduplication (25 pts)
        if density.dup_ratio > 0.55:
            score -= 25
        elif density.dup_ratio > 0.40:
            score -= 15
        elif density.dup_ratio > 0.25:
            score -= 5

        # Vagueness (25 pts)
        if vagueness.vague_pct > 35:
            score -= 25
        elif vagueness.vague_pct > 25:
            score -= 15
        elif vagueness.vague_pct > 15:
            score -= 5

        # Hub distribution (15 pts)
        if hubs.top1_degree_share > 0.25:
            score -= 15
        elif hubs.top1_degree_share > 0.15:
            score -= 8

        # Symétries (10 pts)
        if cycles.symmetric_ratio > 0.20:
            score -= 10
        elif cycles.symmetric_ratio > 0.10:
            score -= 5

        return max(0, score)


# Singleton
_quality_service: Optional[Pass2QualityService] = None


def get_pass2_quality_service(tenant_id: str = "default") -> Pass2QualityService:
    """Récupère le service de qualité Pass 2."""
    global _quality_service
    if _quality_service is None or _quality_service.tenant_id != tenant_id:
        _quality_service = Pass2QualityService(tenant_id=tenant_id)
    return _quality_service
