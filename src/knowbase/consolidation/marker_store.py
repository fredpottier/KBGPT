"""
MarkerStore - Gestion des noeuds Marker pour diff queries optimisees.

Materialise les markers comme noeuds Neo4j pour permettre des requetes
de diff rapides via index au lieu de scans de listes.

Architecture (ADR Section 5.1):
- (:Marker {value, kind}) - Noeud marker unique par valeur
- (ProtoConcept)-[:ASSERTED_WITH_MARKER {confidence, is_inherited}]->(Marker)
- Index sur Marker.value pour lookups rapides

Usage:
    store = MarkerStore(tenant_id="default")
    await store.ensure_marker("1809", kind="numeric_code")
    await store.link_concept_to_marker(concept_id, "1809", confidence=0.9)

    # Diff query
    concepts_with_1809 = await store.get_concepts_with_marker("1809")
    diff = await store.diff_markers(["1809"], ["2020"])

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 5.1
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum
import logging
import re

logger = logging.getLogger(__name__)


class MarkerKind(str, Enum):
    """Type de marqueur detecte."""
    NUMERIC_CODE = "numeric_code"     # 1809, 2020, 2508
    VERSION = "version"               # v1.0.0, 3.2.1
    FPS = "fps"                       # FPS03, FPS05
    SP = "sp"                         # SP02, SP100
    YEAR = "year"                     # 2024, 2025
    EDITION = "edition"               # Cloud, Private, Public
    UNKNOWN = "unknown"


@dataclass
class MarkerNode:
    """Representation d'un noeud Marker."""
    value: str
    kind: MarkerKind = MarkerKind.UNKNOWN
    normalized_value: Optional[str] = None
    tenant_id: str = "default"

    def __post_init__(self):
        if self.normalized_value is None:
            self.normalized_value = self.value.upper().strip()


@dataclass
class ConceptMarkerLink:
    """Lien entre un concept et un marker."""
    concept_id: str
    marker_value: str
    confidence: float = 1.0
    is_inherited: bool = False
    qualifier_source: str = "explicit"


@dataclass
class DiffResult:
    """Resultat d'une requete de diff entre markers."""
    only_in_a: List[str] = field(default_factory=list)  # Concepts uniquement dans A
    only_in_b: List[str] = field(default_factory=list)  # Concepts uniquement dans B
    in_both: List[str] = field(default_factory=list)    # Concepts dans les deux
    marker_a: str = ""
    marker_b: str = ""
    stats: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "marker_a": self.marker_a,
            "marker_b": self.marker_b,
            "only_in_a": self.only_in_a,
            "only_in_b": self.only_in_b,
            "in_both": self.in_both,
            "stats": {
                "count_only_a": len(self.only_in_a),
                "count_only_b": len(self.only_in_b),
                "count_both": len(self.in_both),
                **self.stats
            }
        }


def detect_marker_kind(value: str) -> MarkerKind:
    """
    Detecte le type de marqueur depuis sa valeur.

    Args:
        value: Valeur du marqueur

    Returns:
        MarkerKind detecte
    """
    value_upper = value.upper().strip()

    # FPS pattern (FPS01, FPS03, etc.)
    if re.match(r'^FPS\d{1,2}$', value_upper):
        return MarkerKind.FPS

    # SP pattern (SP02, SP100, etc.)
    if re.match(r'^SP\d{2,3}$', value_upper):
        return MarkerKind.SP

    # Version pattern (v1.0.0, 3.2.1, etc.)
    if re.match(r'^V?\d+\.\d+(\.\d+)?$', value_upper):
        return MarkerKind.VERSION

    # SAP numeric code (1809, 2020, 2508, etc.)
    if re.match(r'^(1[89]\d{2}|20[0-9]{2}|2[1-4]\d{2}|25\d{2})$', value_upper):
        return MarkerKind.NUMERIC_CODE

    # Year pattern (2024, 2025, etc.)
    if re.match(r'^20\d{2}$', value_upper):
        return MarkerKind.YEAR

    # Edition keywords
    if value_upper in ("CLOUD", "PRIVATE", "PUBLIC", "ON-PREMISE", "HYBRID"):
        return MarkerKind.EDITION

    return MarkerKind.UNKNOWN


class MarkerStore:
    """
    Gestionnaire de noeuds Marker dans Neo4j.

    Materialise les markers comme noeuds pour permettre des requetes
    de diff optimisees via index.

    Usage:
        >>> store = MarkerStore(tenant_id="default")
        >>> await store.ensure_marker("1809")
        >>> await store.link_concept_to_marker("pc_xxx", "1809", confidence=0.9)
        >>> diff = await store.diff_markers(["1809"], ["2020"])
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le MarkerStore.

        Args:
            tenant_id: ID du tenant
        """
        self.tenant_id = tenant_id
        self._neo4j_client = None

    def _get_neo4j_client(self):
        """Lazy init du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            from knowbase.config.settings import get_settings

            settings = get_settings()
            self._neo4j_client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )
        return self._neo4j_client

    async def ensure_indexes(self) -> None:
        """
        Cree les index necessaires pour les Marker nodes.

        Indexes:
        - Marker.value (unique par tenant)
        - Marker.kind
        """
        client = self._get_neo4j_client()

        queries = [
            # Index sur valeur (lookup rapide)
            """
            CREATE INDEX marker_value IF NOT EXISTS
            FOR (m:Marker) ON (m.value, m.tenant_id)
            """,
            # Index sur kind (filtrage par type)
            """
            CREATE INDEX marker_kind IF NOT EXISTS
            FOR (m:Marker) ON (m.kind)
            """,
        ]

        try:
            with client.driver.session(database="neo4j") as session:
                for query in queries:
                    session.run(query)
            logger.info("[MarkerStore] Indexes created/verified")
        except Exception as e:
            logger.warning(f"[MarkerStore] Index creation failed: {e}")

    async def ensure_marker(
        self,
        value: str,
        kind: Optional[MarkerKind] = None,
    ) -> MarkerNode:
        """
        Cree ou recupere un noeud Marker.

        Args:
            value: Valeur du marqueur
            kind: Type de marqueur (auto-detecte si None)

        Returns:
            MarkerNode cree ou existant
        """
        if kind is None:
            kind = detect_marker_kind(value)

        normalized = value.upper().strip()

        client = self._get_neo4j_client()

        query = """
        MERGE (m:Marker {value: $value, tenant_id: $tenant_id})
        ON CREATE SET
            m.kind = $kind,
            m.normalized_value = $normalized,
            m.created_at = datetime()
        ON MATCH SET
            m.kind = COALESCE(m.kind, $kind),
            m.updated_at = datetime()
        RETURN m.value AS value, m.kind AS kind, m.normalized_value AS normalized
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    value=value,
                    kind=kind.value,
                    normalized=normalized,
                    tenant_id=self.tenant_id
                )
                record = result.single()

                if record:
                    return MarkerNode(
                        value=record["value"],
                        kind=MarkerKind(record["kind"]) if record["kind"] else MarkerKind.UNKNOWN,
                        normalized_value=record["normalized"],
                        tenant_id=self.tenant_id
                    )

        except Exception as e:
            logger.error(f"[MarkerStore] Failed to ensure marker {value}: {e}")

        return MarkerNode(value=value, kind=kind, tenant_id=self.tenant_id)

    async def link_concept_to_marker(
        self,
        concept_id: str,
        marker_value: str,
        confidence: float = 1.0,
        is_inherited: bool = False,
        qualifier_source: str = "explicit",
    ) -> bool:
        """
        Cree une relation ASSERTED_WITH_MARKER entre un concept et un marker.

        Args:
            concept_id: ID du ProtoConcept
            marker_value: Valeur du marker
            confidence: Confiance dans le lien
            is_inherited: True si herite du document
            qualifier_source: Source du qualificateur

        Returns:
            True si succes
        """
        # S'assurer que le marker existe
        await self.ensure_marker(marker_value)

        client = self._get_neo4j_client()

        query = """
        MATCH (pc:ProtoConcept {concept_id: $concept_id, tenant_id: $tenant_id})
        MATCH (m:Marker {value: $marker_value, tenant_id: $tenant_id})
        MERGE (pc)-[r:ASSERTED_WITH_MARKER]->(m)
        ON CREATE SET
            r.confidence = $confidence,
            r.is_inherited = $is_inherited,
            r.qualifier_source = $qualifier_source,
            r.created_at = datetime()
        ON MATCH SET
            r.confidence = CASE WHEN $confidence > r.confidence THEN $confidence ELSE r.confidence END,
            r.updated_at = datetime()
        RETURN r IS NOT NULL AS created
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    concept_id=concept_id,
                    marker_value=marker_value,
                    confidence=confidence,
                    is_inherited=is_inherited,
                    qualifier_source=qualifier_source,
                    tenant_id=self.tenant_id
                )
                record = result.single()
                return record["created"] if record else False

        except Exception as e:
            logger.error(
                f"[MarkerStore] Failed to link concept {concept_id} to marker {marker_value}: {e}"
            )
            return False

    async def link_concepts_batch(
        self,
        links: List[ConceptMarkerLink],
    ) -> int:
        """
        Cree des liens concept-marker en batch.

        Args:
            links: Liste de liens a creer

        Returns:
            Nombre de liens crees
        """
        if not links:
            return 0

        # S'assurer que tous les markers existent
        unique_markers = set(link.marker_value for link in links)
        for marker_value in unique_markers:
            await self.ensure_marker(marker_value)

        client = self._get_neo4j_client()

        query = """
        UNWIND $links AS link
        MATCH (pc:ProtoConcept {concept_id: link.concept_id, tenant_id: $tenant_id})
        MATCH (m:Marker {value: link.marker_value, tenant_id: $tenant_id})
        MERGE (pc)-[r:ASSERTED_WITH_MARKER]->(m)
        ON CREATE SET
            r.confidence = link.confidence,
            r.is_inherited = link.is_inherited,
            r.qualifier_source = link.qualifier_source,
            r.created_at = datetime()
        RETURN count(r) AS created
        """

        links_data = [
            {
                "concept_id": link.concept_id,
                "marker_value": link.marker_value,
                "confidence": link.confidence,
                "is_inherited": link.is_inherited,
                "qualifier_source": link.qualifier_source,
            }
            for link in links
        ]

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    links=links_data,
                    tenant_id=self.tenant_id
                )
                record = result.single()
                count = record["created"] if record else 0
                logger.info(f"[MarkerStore] Linked {count} concepts to markers")
                return count

        except Exception as e:
            logger.error(f"[MarkerStore] Batch link failed: {e}")
            return 0

    async def get_concepts_with_marker(
        self,
        marker_value: str,
        min_confidence: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Recupere tous les concepts associes a un marker.

        Args:
            marker_value: Valeur du marker
            min_confidence: Confiance minimale

        Returns:
            Liste de concepts avec metadata
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (pc:ProtoConcept)-[r:ASSERTED_WITH_MARKER]->(m:Marker {value: $marker_value, tenant_id: $tenant_id})
        WHERE pc.tenant_id = $tenant_id AND r.confidence >= $min_confidence
        OPTIONAL MATCH (pc)-[:INSTANCE_OF]->(cc:CanonicalConcept)
        RETURN
            pc.concept_id AS concept_id,
            pc.concept_name AS label,
            r.confidence AS confidence,
            r.is_inherited AS is_inherited,
            cc.canonical_id AS canonical_id,
            cc.canonical_name AS canonical_name
        ORDER BY r.confidence DESC
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    marker_value=marker_value,
                    min_confidence=min_confidence,
                    tenant_id=self.tenant_id
                )
                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"[MarkerStore] Query failed for marker {marker_value}: {e}")
            return []

    async def get_markers_for_concept(
        self,
        concept_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Recupere tous les markers associes a un concept.

        Args:
            concept_id: ID du concept

        Returns:
            Liste de markers avec metadata
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (pc:ProtoConcept {concept_id: $concept_id, tenant_id: $tenant_id})
              -[r:ASSERTED_WITH_MARKER]->(m:Marker)
        RETURN
            m.value AS value,
            m.kind AS kind,
            r.confidence AS confidence,
            r.is_inherited AS is_inherited,
            r.qualifier_source AS qualifier_source
        ORDER BY r.confidence DESC
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    concept_id=concept_id,
                    tenant_id=self.tenant_id
                )
                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"[MarkerStore] Query failed for concept {concept_id}: {e}")
            return []

    async def diff_markers(
        self,
        markers_a: List[str],
        markers_b: List[str],
        min_confidence: float = 0.5,
    ) -> DiffResult:
        """
        Calcule la difference entre deux ensembles de markers.

        PR4: Utilise Document.global_markers au lieu des nœuds Marker.
        Les concepts sont associés aux markers via leur Document parent.

        Retourne les concepts:
        - Uniquement dans A (markers_a mais pas markers_b)
        - Uniquement dans B (markers_b mais pas markers_a)
        - Dans les deux

        Args:
            markers_a: Premier ensemble de markers
            markers_b: Deuxieme ensemble de markers
            min_confidence: Confiance minimale (non utilisé dans cette version)

        Returns:
            DiffResult avec les trois ensembles
        """
        client = self._get_neo4j_client()

        # PR4: Query basée sur Document.global_markers
        # Compare par canonical_name pour trouver les concepts sémantiquement identiques
        # même s'ils viennent de documents différents (avant consolidation Pass 2)
        query = """
        // Documents avec markers A
        MATCH (d_a:Document)
        WHERE d_a.tenant_id = $tenant_id
          AND d_a.global_markers IS NOT NULL
          AND any(m IN d_a.global_markers WHERE m IN $markers_a)

        // Concepts extraits avec leur canonical_name
        MATCH (pc_a:ProtoConcept)-[:EXTRACTED_FROM]->(d_a)
        MATCH (pc_a)-[:INSTANCE_OF]->(cc_a:CanonicalConcept)
        WHERE pc_a.tenant_id = $tenant_id
        WITH collect(DISTINCT cc_a.canonical_name) AS concepts_a

        // Documents avec markers B
        MATCH (d_b:Document)
        WHERE d_b.tenant_id = $tenant_id
          AND d_b.global_markers IS NOT NULL
          AND any(m IN d_b.global_markers WHERE m IN $markers_b)

        // Concepts extraits avec leur canonical_name
        MATCH (pc_b:ProtoConcept)-[:EXTRACTED_FROM]->(d_b)
        MATCH (pc_b)-[:INSTANCE_OF]->(cc_b:CanonicalConcept)
        WHERE pc_b.tenant_id = $tenant_id
        WITH concepts_a, collect(DISTINCT cc_b.canonical_name) AS concepts_b

        // Calculer les ensembles (par nom canonique)
        WITH concepts_a, concepts_b,
             [x IN concepts_a WHERE NOT x IN concepts_b] AS only_a,
             [x IN concepts_b WHERE NOT x IN concepts_a] AS only_b,
             [x IN concepts_a WHERE x IN concepts_b] AS in_both

        RETURN only_a, only_b, in_both
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    markers_a=markers_a,
                    markers_b=markers_b,
                    tenant_id=self.tenant_id
                )
                record = result.single()

                if record:
                    logger.info(
                        f"[MarkerStore] Diff complete: "
                        f"{len(record['only_a'] or [])} only in A, "
                        f"{len(record['only_b'] or [])} only in B, "
                        f"{len(record['in_both'] or [])} in both"
                    )
                    return DiffResult(
                        only_in_a=record["only_a"] or [],
                        only_in_b=record["only_b"] or [],
                        in_both=record["in_both"] or [],
                        marker_a=",".join(markers_a),
                        marker_b=",".join(markers_b),
                        stats={
                            "min_confidence": min_confidence,
                        }
                    )

        except Exception as e:
            logger.error(f"[MarkerStore] Diff query failed: {e}", exc_info=True)

        return DiffResult(marker_a=",".join(markers_a), marker_b=",".join(markers_b))

    async def get_all_markers(
        self,
        kind_filter: Optional[MarkerKind] = None,
    ) -> List[Dict[str, Any]]:
        """
        Liste tous les markers avec leurs statistiques.

        Extrait les markers depuis les propriétés global_markers des Documents
        (architecture PR4) plutôt que des nœuds Marker séparés.

        Args:
            kind_filter: Filtrer par type de marker

        Returns:
            Liste de markers avec count de concepts
        """
        client = self._get_neo4j_client()

        # PR4: Extraire markers depuis Document.global_markers
        # Compter les concepts via la relation EXTRACTED_FROM
        query = """
        MATCH (d:Document)
        WHERE d.tenant_id = $tenant_id
          AND d.global_markers IS NOT NULL
          AND size(d.global_markers) > 0
        UNWIND d.global_markers AS marker_value
        WITH marker_value, collect(DISTINCT d) AS docs

        // Compter les concepts associés aux documents de ce marker
        OPTIONAL MATCH (pc:ProtoConcept)-[:EXTRACTED_FROM]->(doc)
        WHERE doc IN docs AND pc.tenant_id = $tenant_id

        WITH marker_value, docs, count(DISTINCT pc) AS concept_count

        RETURN
            marker_value AS value,
            CASE
                WHEN marker_value =~ '^[0-9]{4}$' THEN 'numeric_code'
                WHEN marker_value =~ '^FPS[0-9]+$' THEN 'fps'
                WHEN marker_value =~ '^SP[0-9]+$' THEN 'sp'
                WHEN marker_value =~ '^v?[0-9]+\\.[0-9]+' THEN 'version'
                WHEN marker_value IN ['Cloud', 'Private', 'Public', 'On-Premise'] THEN 'edition'
                ELSE 'unknown'
            END AS kind,
            concept_count,
            1.0 AS avg_confidence
        ORDER BY concept_count DESC
        """

        try:
            params = {"tenant_id": self.tenant_id}

            with client.driver.session(database="neo4j") as session:
                result = session.run(query, **params)
                markers = [dict(record) for record in result]

                # Filtrer par kind si demandé
                if kind_filter:
                    markers = [m for m in markers if m.get("kind") == kind_filter.value]

                logger.info(f"[MarkerStore] Found {len(markers)} markers from Documents")
                return markers

        except Exception as e:
            logger.error(f"[MarkerStore] List markers failed: {e}")
            return []


# Singleton
_marker_store_instances: Dict[str, MarkerStore] = {}


def get_marker_store(tenant_id: str = "default") -> MarkerStore:
    """Retourne l'instance singleton du MarkerStore pour un tenant."""
    global _marker_store_instances
    if tenant_id not in _marker_store_instances:
        _marker_store_instances[tenant_id] = MarkerStore(tenant_id=tenant_id)
    return _marker_store_instances[tenant_id]


__all__ = [
    "MarkerKind",
    "MarkerNode",
    "ConceptMarkerLink",
    "DiffResult",
    "MarkerStore",
    "get_marker_store",
    "detect_marker_kind",
]
