"""
ImportAnalyticsService - Service d'analyse détaillée des imports.

Fournit des métriques complètes sur l'extraction V2 et OSMOSE :
- Temps par phase (Docling, Gating, Vision, Merge, OSMOSE)
- Requêtes LLM (Vision, 4o-mini)
- Qualité extraction (Docling, Vision Gating, Vision GPT-4o, OSMOSE)
- Concepts Proto/Canoniques
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class PhaseMetrics:
    """Métriques d'une phase de traitement."""
    name: str
    duration_ms: float
    llm_calls: int = 0
    llm_model: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "llm_calls": self.llm_calls,
            "llm_model": self.llm_model,
            "details": self.details,
        }


@dataclass
class GatingAnalysis:
    """Analyse des décisions de Vision Gating."""
    total_pages: int
    vision_required: int
    vision_recommended: int
    no_vision: int
    avg_vns: float
    max_vns: float
    # Distribution des raisons
    reasons_distribution: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_pages": self.total_pages,
            "vision_required": self.vision_required,
            "vision_recommended": self.vision_recommended,
            "no_vision": self.no_vision,
            "avg_vns": round(self.avg_vns, 3),
            "max_vns": round(self.max_vns, 3),
            "reasons_distribution": self.reasons_distribution,
        }


@dataclass
class VisionAnalysis:
    """Analyse des extractions Vision GPT-4o."""
    pages_processed: int
    total_elements: int
    total_relations: int
    avg_elements_per_page: float
    element_types: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pages_processed": self.pages_processed,
            "total_elements": self.total_elements,
            "total_relations": self.total_relations,
            "avg_elements_per_page": round(self.avg_elements_per_page, 2),
            "element_types": self.element_types,
        }


@dataclass
class OsmoseAnalysis:
    """Analyse des résultats OSMOSE."""
    proto_concepts: int
    canonical_concepts: int
    topics_segmented: int
    relations_stored: int
    phase2_relations: int
    embeddings_stored: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proto_concepts": self.proto_concepts,
            "canonical_concepts": self.canonical_concepts,
            "topics_segmented": self.topics_segmented,
            "relations_stored": self.relations_stored,
            "phase2_relations": self.phase2_relations,
            "embeddings_stored": self.embeddings_stored,
        }


@dataclass
class ImportAnalytics:
    """Résultat complet d'analyse d'un import."""
    document_id: str
    document_name: str
    file_type: str
    import_timestamp: str
    cache_used: bool

    # Métriques globales
    total_pages: int
    total_chars: int
    total_duration_ms: float

    # Phases
    phases: List[PhaseMetrics]

    # Analyses détaillées
    gating: Optional[GatingAnalysis] = None
    vision: Optional[VisionAnalysis] = None
    osmose: Optional[OsmoseAnalysis] = None

    # Qualité
    quality_score: float = 0.0
    quality_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_name": self.document_name,
            "file_type": self.file_type,
            "import_timestamp": self.import_timestamp,
            "cache_used": self.cache_used,
            "total_pages": self.total_pages,
            "total_chars": self.total_chars,
            "total_duration_ms": self.total_duration_ms,
            "phases": [p.to_dict() for p in self.phases],
            "gating": self.gating.to_dict() if self.gating else None,
            "vision": self.vision.to_dict() if self.vision else None,
            "osmose": self.osmose.to_dict() if self.osmose else None,
            "quality_score": self.quality_score,
            "quality_notes": self.quality_notes,
        }


class ImportAnalyticsService:
    """
    Service d'analyse des imports.

    Récupère les données depuis :
    - Cache V2 (extraction_cache/*.v2cache.json)
    - Neo4j (concepts, relations)
    - Redis (métriques temps réel)
    """

    def __init__(
        self,
        cache_dir: str = "/data/extraction_cache",
        neo4j_client=None,
    ):
        self.cache_dir = Path(cache_dir)
        self.neo4j_client = neo4j_client
        logger.info(f"[ImportAnalytics] Initialized with cache_dir={cache_dir}")

    def list_imports(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Liste les imports disponibles (depuis le cache V2)."""
        imports = []

        if not self.cache_dir.exists():
            return imports

        for cache_file in sorted(
            self.cache_dir.glob("*.v2cache.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:limit]:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                extraction = data.get("extraction", {})
                # Extraire le hash sans l'extension .v2cache
                file_hash = cache_file.stem
                if file_hash.endswith(".v2cache"):
                    file_hash = file_hash[:-8]  # Enlever ".v2cache"

                stats = extraction.get("stats", {})
                metrics = stats.get("metrics", {})
                imports.append({
                    "cache_file": cache_file.name,
                    "file_hash": file_hash,
                    "document_id": extraction.get("document_id", "unknown"),
                    "source_path": extraction.get("source_path", ""),
                    "file_type": extraction.get("file_type", ""),
                    "total_pages": metrics.get("total_pages", 0),
                    "total_chars": len(extraction.get("full_text", "")),
                    "created_at": data.get("created_at", ""),
                })
            except Exception as e:
                logger.warning(f"Error reading cache {cache_file}: {e}")

        return imports

    def get_analytics(self, file_hash: str) -> Optional[ImportAnalytics]:
        """
        Récupère les analytics complètes pour un import.

        Args:
            file_hash: Hash SHA256 du fichier (nom du cache sans extension)
        """
        cache_path = self.cache_dir / f"{file_hash}.v2cache.json"

        if not cache_path.exists():
            logger.warning(f"[ImportAnalytics] Cache not found: {file_hash}")
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            return self._build_analytics(cache_data, file_hash)

        except Exception as e:
            logger.error(f"[ImportAnalytics] Error loading analytics: {e}")
            return None

    def _build_analytics(
        self,
        cache_data: Dict[str, Any],
        file_hash: str,
    ) -> ImportAnalytics:
        """Construit l'objet ImportAnalytics depuis les données du cache."""
        extraction = cache_data.get("extraction", {})
        stats = extraction.get("stats", {})
        metrics = stats.get("metrics", {})
        config = stats.get("config", {})

        # Infos de base
        document_id = extraction.get("document_id", file_hash)
        source_path = extraction.get("source_path", "")
        document_name = Path(source_path).name if source_path else document_id

        # Phases de traitement
        phases = self._extract_phases(metrics)

        # Analyse Gating
        gating = self._analyze_gating(extraction.get("gating_decisions", []))

        # Analyse Vision
        vision = self._analyze_vision(extraction.get("structure", {}))

        # Analyse OSMOSE (depuis Neo4j si disponible)
        osmose = self._analyze_osmose(document_id)

        # Calcul qualité
        quality_score, quality_notes = self._compute_quality(
            gating, vision, osmose, stats
        )

        return ImportAnalytics(
            document_id=document_id,
            document_name=document_name,
            file_type=extraction.get("file_type", "unknown"),
            import_timestamp=cache_data.get("created_at", ""),
            cache_used=False,  # Sera mis à jour si on détecte un cache hit
            total_pages=metrics.get("total_pages", 0),
            total_chars=len(extraction.get("full_text", "")),
            total_duration_ms=metrics.get("total_time_ms", 0),
            phases=phases,
            gating=gating,
            vision=vision,
            osmose=osmose,
            quality_score=quality_score,
            quality_notes=quality_notes,
        )

    def _extract_phases(self, metrics: Dict[str, Any]) -> List[PhaseMetrics]:
        """Extrait les métriques par phase."""
        phases = []

        # Phase 1: Extraction Docling
        if "extraction_time_ms" in metrics:
            phases.append(PhaseMetrics(
                name="Docling Extraction",
                duration_ms=metrics["extraction_time_ms"],
                details={"ocr_enabled": True},
            ))

        # Phase 2: Vision Gating
        if "gating_time_ms" in metrics:
            phases.append(PhaseMetrics(
                name="Vision Gating",
                duration_ms=metrics["gating_time_ms"],
                details={
                    "required": metrics.get("vision_required_pages", 0),
                    "recommended": metrics.get("vision_recommended_pages", 0),
                },
            ))

        # Phase 3: Vision Analysis
        if "vision_time_ms" in metrics:
            vision_pages = metrics.get("vision_processed_pages", 0)
            phases.append(PhaseMetrics(
                name="Vision Analysis",
                duration_ms=metrics["vision_time_ms"],
                llm_calls=vision_pages,
                llm_model="gpt-4o",
                details={"pages_analyzed": vision_pages},
            ))

        # Phase 4: Merge
        if "merge_time_ms" in metrics:
            phases.append(PhaseMetrics(
                name="Structured Merge",
                duration_ms=metrics["merge_time_ms"],
            ))

        # Phase 5: Linearization
        if "linearize_time_ms" in metrics:
            phases.append(PhaseMetrics(
                name="Linearization",
                duration_ms=metrics["linearize_time_ms"],
            ))

        return phases

    def _analyze_gating(
        self,
        decisions: List[Dict[str, Any]],
    ) -> Optional[GatingAnalysis]:
        """Analyse les décisions de gating."""
        if not decisions:
            return None

        vision_required = 0
        vision_recommended = 0
        no_vision = 0
        vns_scores = []
        reasons_count: Dict[str, int] = {}

        for d in decisions:
            # Le champ est "decision" dans le cache V2, pas "action"
            decision = d.get("decision", d.get("action", "none"))
            vns = d.get("vision_need_score", 0)
            vns_scores.append(vns)

            if decision == "vision_required":
                vision_required += 1
            elif decision == "vision_recommended":
                vision_recommended += 1
            else:
                no_vision += 1

            # Compter les raisons
            for reason in d.get("reasons", []):
                # Extraire le type de raison
                if "raster" in reason.lower():
                    key = "raster_image"
                elif "vector" in reason.lower():
                    key = "vector_drawing"
                elif "fragmentation" in reason.lower():
                    key = "text_fragmentation"
                elif "dispersion" in reason.lower():
                    key = "spatial_dispersion"
                elif "table" in reason.lower():
                    key = "visual_table"
                elif "vns" in reason.lower():
                    key = "vns_score"
                else:
                    key = "other"
                reasons_count[key] = reasons_count.get(key, 0) + 1

        return GatingAnalysis(
            total_pages=len(decisions),
            vision_required=vision_required,
            vision_recommended=vision_recommended,
            no_vision=no_vision,
            avg_vns=sum(vns_scores) / len(vns_scores) if vns_scores else 0,
            max_vns=max(vns_scores) if vns_scores else 0,
            reasons_distribution=reasons_count,
        )

    def _analyze_vision(
        self,
        structure: Dict[str, Any],
    ) -> Optional[VisionAnalysis]:
        """Analyse les extractions Vision."""
        pages = structure.get("pages", [])
        if not pages:
            return None

        pages_with_vision = 0
        total_elements = 0
        total_relations = 0
        element_types: Dict[str, int] = {}

        for page in pages:
            vision = page.get("vision")
            if vision:
                pages_with_vision += 1
                elements = vision.get("elements", [])
                relations = vision.get("relations", [])

                total_elements += len(elements)
                total_relations += len(relations)

                for elem in elements:
                    etype = elem.get("type", "unknown")
                    element_types[etype] = element_types.get(etype, 0) + 1

        if pages_with_vision == 0:
            return None

        return VisionAnalysis(
            pages_processed=pages_with_vision,
            total_elements=total_elements,
            total_relations=total_relations,
            avg_elements_per_page=total_elements / pages_with_vision,
            element_types=element_types,
        )

    def _analyze_osmose(self, document_id: str) -> Optional[OsmoseAnalysis]:
        """Analyse les résultats OSMOSE depuis Neo4j."""
        if not self.neo4j_client or not self.neo4j_client.driver:
            # Retourner des valeurs par défaut si pas de client Neo4j
            return OsmoseAnalysis(
                proto_concepts=0,
                canonical_concepts=0,
                topics_segmented=0,
                relations_stored=0,
                phase2_relations=0,
                embeddings_stored=0,
            )

        try:
            # Requêtes Neo4j pour récupérer les stats
            with self.neo4j_client.driver.session() as session:
                # Proto concepts
                result = session.run(
                    """
                    MATCH (c:ProtoConcept {doc_id: $doc_id})
                    RETURN count(c) as count
                    """,
                    doc_id=document_id,
                )
                proto = result.single()["count"]

                # Canonical concepts (liés via INSTANCE_OF depuis les ProtoConcepts)
                result = session.run(
                    """
                    MATCH (p:ProtoConcept {doc_id: $doc_id})-[:INSTANCE_OF]->(c:CanonicalConcept)
                    RETURN count(DISTINCT c) as count
                    """,
                    doc_id=document_id,
                )
                canonical = result.single()["count"]

                # Relations (depuis les ProtoConcepts du document)
                result = session.run(
                    """
                    MATCH (p:ProtoConcept {doc_id: $doc_id})-[r]->()
                    RETURN count(r) as count
                    """,
                    doc_id=document_id,
                )
                relations = result.single()["count"]

                return OsmoseAnalysis(
                    proto_concepts=proto,
                    canonical_concepts=canonical,
                    topics_segmented=0,  # TODO: récupérer depuis les topics
                    relations_stored=relations,
                    phase2_relations=0,  # TODO: filtrer par type
                    embeddings_stored=0,  # TODO: récupérer depuis Qdrant
                )

        except Exception as e:
            logger.error(f"[ImportAnalytics] Neo4j error: {e}")
            return None

    def _compute_quality(
        self,
        gating: Optional[GatingAnalysis],
        vision: Optional[VisionAnalysis],
        osmose: Optional[OsmoseAnalysis],
        stats: Dict[str, Any],
    ) -> tuple[float, List[str]]:
        """Calcule un score de qualité et des notes."""
        score = 0.0
        notes = []
        factors = 0

        # Qualité Gating
        if gating and gating.total_pages > 0:
            # Bon si le gating a fait des choix discriminants
            vision_ratio = (gating.vision_required + gating.vision_recommended) / gating.total_pages
            if 0.3 <= vision_ratio <= 0.7:
                score += 1.0
                notes.append("✅ Vision Gating discriminant")
            elif vision_ratio > 0.9:
                score += 0.5
                notes.append("⚠️ Trop de pages envoyées à Vision")
            else:
                score += 0.7
                notes.append("ℹ️ Peu de pages nécessitent Vision")
            factors += 1

        # Qualité Vision
        if vision and vision.pages_processed > 0:
            if vision.avg_elements_per_page >= 5:
                score += 1.0
                notes.append("✅ Extraction Vision riche")
            elif vision.avg_elements_per_page >= 2:
                score += 0.7
                notes.append("ℹ️ Extraction Vision modérée")
            else:
                score += 0.4
                notes.append("⚠️ Extraction Vision pauvre")
            factors += 1

        # Qualité OSMOSE
        if osmose:
            if osmose.proto_concepts > 50:
                score += 1.0
                notes.append("✅ Beaucoup de concepts extraits")
            elif osmose.proto_concepts > 10:
                score += 0.7
                notes.append("ℹ️ Concepts extraits correctement")
            else:
                score += 0.4
                notes.append("⚠️ Peu de concepts extraits")
            factors += 1

        # Normaliser
        final_score = (score / factors * 100) if factors > 0 else 0

        return round(final_score, 1), notes


__all__ = [
    "ImportAnalyticsService",
    "ImportAnalytics",
    "PhaseMetrics",
    "GatingAnalysis",
    "VisionAnalysis",
    "OsmoseAnalysis",
]
