"""
ConceptDiffService - Service pour requetes de diff entre markers/versions.

Permet de repondre aux questions generiques:
- "Qu'est-ce qui est dans A mais pas dans B?"
- "Qu'est-ce qui a change entre A et B?"
- "Qu'est-ce qui est valide pour toutes les variantes?"

Architecture (ADR Section 3):
- Utilise MarkerStore pour queries optimisees via Marker nodes
- Fallback sur proprietes de liste si Marker nodes non materialises
- Support filtrage par polarity, confidence, document

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 7 (PR3)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum
import logging

from knowbase.consolidation.marker_store import (
    MarkerStore,
    DiffResult,
    get_marker_store,
)
from knowbase.extraction_v2.context.anchor_models import Polarity, AssertionScope

logger = logging.getLogger(__name__)


class DiffMode(str, Enum):
    """Mode de calcul du diff."""
    CONCEPTS = "concepts"           # Diff sur les concepts
    ASSERTIONS = "assertions"       # Diff sur les assertions (polarity-aware)
    RELATIONS = "relations"         # Diff sur les relations


@dataclass
class ConceptInfo:
    """Information sur un concept dans un diff."""
    concept_id: str
    label: str
    canonical_id: Optional[str] = None
    canonical_name: Optional[str] = None
    polarity: str = "unknown"
    scope: str = "unknown"
    confidence: float = 0.0
    markers: List[str] = field(default_factory=list)
    document_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "label": self.label,
            "canonical_id": self.canonical_id,
            "canonical_name": self.canonical_name,
            "polarity": self.polarity,
            "scope": self.scope,
            "confidence": self.confidence,
            "markers": self.markers,
            "document_id": self.document_id,
        }


@dataclass
class AssertionInfo:
    """Information sur une assertion dans un diff."""
    concept_id: str
    label: str
    polarity: str
    scope: str
    markers: List[str]
    confidence: float
    document_id: str
    document_name: Optional[str] = None
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "label": self.label,
            "polarity": self.polarity,
            "scope": self.scope,
            "markers": self.markers,
            "confidence": self.confidence,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "evidence": self.evidence[:2],
        }


@dataclass
class ConceptDiffResult:
    """Resultat complet d'un diff de concepts."""
    marker_a: str
    marker_b: str
    mode: DiffMode
    only_in_a: List[ConceptInfo] = field(default_factory=list)
    only_in_b: List[ConceptInfo] = field(default_factory=list)
    in_both: List[ConceptInfo] = field(default_factory=list)
    changed: List[Dict[str, Any]] = field(default_factory=list)  # Concepts avec changement polarity/scope
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "marker_a": self.marker_a,
            "marker_b": self.marker_b,
            "mode": self.mode.value,
            "only_in_a": [c.to_dict() for c in self.only_in_a],
            "only_in_b": [c.to_dict() for c in self.only_in_b],
            "in_both": [c.to_dict() for c in self.in_both],
            "changed": self.changed,
            "stats": {
                "count_only_a": len(self.only_in_a),
                "count_only_b": len(self.only_in_b),
                "count_both": len(self.in_both),
                "count_changed": len(self.changed),
                **self.stats
            }
        }


@dataclass
class AssertionQueryResult:
    """Resultat d'une requete d'assertions pour un concept."""
    concept_id: str
    canonical_id: Optional[str]
    label: str
    assertions: List[AssertionInfo] = field(default_factory=list)
    aggregated_polarity: str = "unknown"
    aggregated_scope: str = "unknown"
    has_conflict: bool = False
    conflict_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "canonical_id": self.canonical_id,
            "label": self.label,
            "assertions": [a.to_dict() for a in self.assertions],
            "aggregated_polarity": self.aggregated_polarity,
            "aggregated_scope": self.aggregated_scope,
            "has_conflict": self.has_conflict,
            "conflict_flags": self.conflict_flags,
        }


class ConceptDiffService:
    """
    Service pour queries de diff entre markers/versions.

    Supporte trois modes:
    1. CONCEPTS: Diff simple sur presence/absence de concepts
    2. ASSERTIONS: Diff avec prise en compte de polarity
    3. RELATIONS: Diff sur les relations entre concepts (future)

    Usage:
        >>> service = ConceptDiffService(tenant_id="default")
        >>> diff = await service.diff_by_markers("1809", "2020")
        >>> print(diff.only_in_a)  # Concepts dans 1809 mais pas 2020
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le service.

        Args:
            tenant_id: ID du tenant
        """
        self.tenant_id = tenant_id
        self._marker_store = None
        self._neo4j_client = None

    def _get_marker_store(self) -> MarkerStore:
        """Lazy init du MarkerStore."""
        if self._marker_store is None:
            self._marker_store = get_marker_store(self.tenant_id)
        return self._marker_store

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

    async def diff_by_markers(
        self,
        marker_a: str,
        marker_b: str,
        mode: DiffMode = DiffMode.CONCEPTS,
        min_confidence: float = 0.5,
        include_details: bool = True,
    ) -> ConceptDiffResult:
        """
        Calcule le diff entre deux markers.

        Args:
            marker_a: Premier marker (ex: "1809")
            marker_b: Deuxieme marker (ex: "2020")
            mode: Mode de diff
            min_confidence: Confiance minimale
            include_details: Inclure les details des concepts

        Returns:
            ConceptDiffResult avec les trois ensembles
        """
        logger.info(
            f"[ConceptDiffService] Diff {marker_a} vs {marker_b} "
            f"(mode={mode.value}, min_conf={min_confidence})"
        )

        # Essayer d'abord via MarkerStore (optimise)
        marker_store = self._get_marker_store()
        basic_diff = await marker_store.diff_markers(
            markers_a=[marker_a],
            markers_b=[marker_b],
            min_confidence=min_confidence,
        )

        # Construire le resultat enrichi
        result = ConceptDiffResult(
            marker_a=marker_a,
            marker_b=marker_b,
            mode=mode,
        )

        if include_details:
            # Enrichir avec details des concepts
            result.only_in_a = await self._enrich_concept_list(
                basic_diff.only_in_a, marker_a
            )
            result.only_in_b = await self._enrich_concept_list(
                basic_diff.only_in_b, marker_b
            )
            result.in_both = await self._enrich_concept_list(
                basic_diff.in_both, f"{marker_a},{marker_b}"
            )

            # Mode ASSERTIONS: detecter les changements de polarity
            if mode == DiffMode.ASSERTIONS and basic_diff.in_both:
                result.changed = await self._detect_polarity_changes(
                    basic_diff.in_both, marker_a, marker_b
                )
        else:
            # Mode leger: juste les IDs
            result.only_in_a = [
                ConceptInfo(concept_id=cid, label="") for cid in basic_diff.only_in_a
            ]
            result.only_in_b = [
                ConceptInfo(concept_id=cid, label="") for cid in basic_diff.only_in_b
            ]
            result.in_both = [
                ConceptInfo(concept_id=cid, label="") for cid in basic_diff.in_both
            ]

        result.stats = {
            "min_confidence": min_confidence,
            "mode": mode.value,
        }

        logger.info(
            f"[ConceptDiffService] Diff complete: "
            f"{len(result.only_in_a)} only in A, "
            f"{len(result.only_in_b)} only in B, "
            f"{len(result.in_both)} in both, "
            f"{len(result.changed)} changed"
        )

        return result

    async def diff_by_documents(
        self,
        document_id_a: str,
        document_id_b: str,
        mode: DiffMode = DiffMode.CONCEPTS,
        min_confidence: float = 0.5,
    ) -> ConceptDiffResult:
        """
        Calcule le diff entre deux documents.

        Args:
            document_id_a: ID du premier document
            document_id_b: ID du deuxieme document
            mode: Mode de diff
            min_confidence: Confiance minimale

        Returns:
            ConceptDiffResult
        """
        client = self._get_neo4j_client()

        # Query pour obtenir les concepts de chaque document
        query = """
        // Concepts du document A
        MATCH (pc_a:ProtoConcept)-[:EXTRACTED_FROM]->(d_a:Document {doc_id: $doc_a})
        WHERE pc_a.tenant_id = $tenant_id
        WITH collect(DISTINCT {id: pc_a.concept_id, label: pc_a.concept_name}) AS concepts_a

        // Concepts du document B
        MATCH (pc_b:ProtoConcept)-[:EXTRACTED_FROM]->(d_b:Document {doc_id: $doc_b})
        WHERE pc_b.tenant_id = $tenant_id
        WITH concepts_a, collect(DISTINCT {id: pc_b.concept_id, label: pc_b.concept_name}) AS concepts_b

        // Calculer les ensembles
        WITH concepts_a, concepts_b,
             [x IN concepts_a WHERE NOT x.id IN [y IN concepts_b | y.id]] AS only_a,
             [x IN concepts_b WHERE NOT x.id IN [y IN concepts_a | y.id]] AS only_b,
             [x IN concepts_a WHERE x.id IN [y IN concepts_b | y.id]] AS in_both

        RETURN only_a, only_b, in_both
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    doc_a=document_id_a,
                    doc_b=document_id_b,
                    tenant_id=self.tenant_id
                )
                record = result.single()

                if record:
                    return ConceptDiffResult(
                        marker_a=document_id_a,
                        marker_b=document_id_b,
                        mode=mode,
                        only_in_a=[
                            ConceptInfo(concept_id=c["id"], label=c["label"])
                            for c in (record["only_a"] or [])
                        ],
                        only_in_b=[
                            ConceptInfo(concept_id=c["id"], label=c["label"])
                            for c in (record["only_b"] or [])
                        ],
                        in_both=[
                            ConceptInfo(concept_id=c["id"], label=c["label"])
                            for c in (record["in_both"] or [])
                        ],
                        stats={"mode": "document_diff"}
                    )

        except Exception as e:
            logger.error(f"[ConceptDiffService] Document diff failed: {e}")

        return ConceptDiffResult(
            marker_a=document_id_a,
            marker_b=document_id_b,
            mode=mode
        )

    async def get_assertions_for_concept(
        self,
        concept_id: str,
        include_canonical: bool = True,
    ) -> AssertionQueryResult:
        """
        Recupere toutes les assertions pour un concept.

        Args:
            concept_id: ID du concept (proto ou canonical)
            include_canonical: Inclure les assertions du canonical

        Returns:
            AssertionQueryResult avec toutes les assertions
        """
        client = self._get_neo4j_client()

        # Query pour obtenir les assertions
        query = """
        // Trouver le concept (proto ou canonical)
        OPTIONAL MATCH (pc:ProtoConcept {concept_id: $concept_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (cc:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})

        WITH COALESCE(pc, cc) AS concept,
             CASE WHEN pc IS NOT NULL THEN 'proto' ELSE 'canonical' END AS concept_type

        // Si canonical, recuperer tous les protos lies
        OPTIONAL MATCH (pc2:ProtoConcept)-[:INSTANCE_OF]->(concept)
        WHERE concept_type = 'canonical'

        WITH concept, concept_type,
             CASE WHEN concept_type = 'canonical'
                  THEN collect(pc2)
                  ELSE [concept]
             END AS protos

        // Recuperer les assertions depuis EXTRACTED_FROM
        UNWIND protos AS proto
        OPTIONAL MATCH (proto)-[r:EXTRACTED_FROM]->(d:Document)

        RETURN
            concept.concept_id AS concept_id,
            CASE WHEN concept_type = 'canonical'
                 THEN concept.canonical_id
                 ELSE null
            END AS canonical_id,
            COALESCE(concept.concept_name, concept.canonical_name) AS label,
            collect({
                proto_id: proto.concept_id,
                polarity: COALESCE(r.polarity, 'unknown'),
                scope: COALESCE(r.scope, 'unknown'),
                markers: COALESCE(r.markers, []),
                confidence: COALESCE(r.confidence, 0.5),
                document_id: d.id,
                document_name: d.name
            }) AS assertions
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    concept_id=concept_id,
                    tenant_id=self.tenant_id
                )
                record = result.single()

                if record:
                    assertions = []
                    polarities = set()
                    scopes = set()

                    for a in (record["assertions"] or []):
                        if a["proto_id"]:
                            assertions.append(AssertionInfo(
                                concept_id=a["proto_id"],
                                label=record["label"] or "",
                                polarity=a["polarity"],
                                scope=a["scope"],
                                markers=a["markers"] or [],
                                confidence=a["confidence"],
                                document_id=a["document_id"] or "",
                                document_name=a["document_name"],
                            ))
                            if a["polarity"] != "unknown":
                                polarities.add(a["polarity"])
                            if a["scope"] != "unknown":
                                scopes.add(a["scope"])

                    # Detecter conflits
                    has_conflict = len(polarities) > 1
                    conflict_flags = []
                    if has_conflict:
                        conflict_flags.append(f"polarity_conflict: {list(polarities)}")

                    # Agreger
                    agg_polarity = list(polarities)[0] if len(polarities) == 1 else "unknown"
                    agg_scope = "constrained" if "constrained" in scopes else (
                        "general" if "general" in scopes else "unknown"
                    )

                    return AssertionQueryResult(
                        concept_id=concept_id,
                        canonical_id=record["canonical_id"],
                        label=record["label"] or "",
                        assertions=assertions,
                        aggregated_polarity=agg_polarity,
                        aggregated_scope=agg_scope,
                        has_conflict=has_conflict,
                        conflict_flags=conflict_flags,
                    )

        except Exception as e:
            logger.error(f"[ConceptDiffService] Assertion query failed: {e}")

        return AssertionQueryResult(
            concept_id=concept_id,
            canonical_id=None,
            label="",
        )

    async def get_concepts_by_scope(
        self,
        scope: AssertionScope,
        marker_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[ConceptInfo]:
        """
        Recupere les concepts par scope (general, constrained, unknown).

        Args:
            scope: Scope a filtrer
            marker_filter: Optionnel, filtrer par marker
            limit: Nombre max de resultats

        Returns:
            Liste de ConceptInfo
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (pc:ProtoConcept)-[r:EXTRACTED_FROM]->(d:Document)
        WHERE pc.tenant_id = $tenant_id
          AND r.scope = $scope
        """ + ("""
          AND $marker IN r.markers
        """ if marker_filter else "") + """
        OPTIONAL MATCH (pc)-[:INSTANCE_OF]->(cc:CanonicalConcept)
        RETURN
            pc.concept_id AS concept_id,
            pc.concept_name AS label,
            cc.canonical_id AS canonical_id,
            cc.canonical_name AS canonical_name,
            r.polarity AS polarity,
            r.scope AS scope,
            r.confidence AS confidence,
            r.markers AS markers,
            d.id AS document_id
        LIMIT $limit
        """

        try:
            params = {
                "tenant_id": self.tenant_id,
                "scope": scope.value,
                "limit": limit,
            }
            if marker_filter:
                params["marker"] = marker_filter

            with client.driver.session(database="neo4j") as session:
                result = session.run(query, **params)
                return [
                    ConceptInfo(
                        concept_id=r["concept_id"],
                        label=r["label"] or "",
                        canonical_id=r["canonical_id"],
                        canonical_name=r["canonical_name"],
                        polarity=r["polarity"] or "unknown",
                        scope=r["scope"] or "unknown",
                        confidence=r["confidence"] or 0.5,
                        markers=r["markers"] or [],
                        document_id=r["document_id"],
                    )
                    for r in result
                ]

        except Exception as e:
            logger.error(f"[ConceptDiffService] Scope query failed: {e}")
            return []

    async def get_concepts_by_polarity(
        self,
        polarity: Polarity,
        marker_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[ConceptInfo]:
        """
        Recupere les concepts par polarity.

        Utile pour trouver:
        - Tous les concepts deprecies
        - Tous les concepts futurs (roadmap)
        - Tous les concepts negatifs (absents)

        Args:
            polarity: Polarity a filtrer
            marker_filter: Optionnel, filtrer par marker
            limit: Nombre max de resultats

        Returns:
            Liste de ConceptInfo
        """
        client = self._get_neo4j_client()

        query = """
        MATCH (pc:ProtoConcept)-[r:EXTRACTED_FROM]->(d:Document)
        WHERE pc.tenant_id = $tenant_id
          AND r.polarity = $polarity
        """ + ("""
          AND $marker IN r.markers
        """ if marker_filter else "") + """
        OPTIONAL MATCH (pc)-[:INSTANCE_OF]->(cc:CanonicalConcept)
        RETURN
            pc.concept_id AS concept_id,
            pc.concept_name AS label,
            cc.canonical_id AS canonical_id,
            cc.canonical_name AS canonical_name,
            r.polarity AS polarity,
            r.scope AS scope,
            r.confidence AS confidence,
            r.markers AS markers,
            d.id AS document_id
        LIMIT $limit
        """

        try:
            params = {
                "tenant_id": self.tenant_id,
                "polarity": polarity.value,
                "limit": limit,
            }
            if marker_filter:
                params["marker"] = marker_filter

            with client.driver.session(database="neo4j") as session:
                result = session.run(query, **params)
                return [
                    ConceptInfo(
                        concept_id=r["concept_id"],
                        label=r["label"] or "",
                        canonical_id=r["canonical_id"],
                        canonical_name=r["canonical_name"],
                        polarity=r["polarity"] or "unknown",
                        scope=r["scope"] or "unknown",
                        confidence=r["confidence"] or 0.5,
                        markers=r["markers"] or [],
                        document_id=r["document_id"],
                    )
                    for r in result
                ]

        except Exception as e:
            logger.error(f"[ConceptDiffService] Polarity query failed: {e}")
            return []

    async def _enrich_concept_list(
        self,
        concept_names: List[str],
        marker_context: str,
    ) -> List[ConceptInfo]:
        """
        Enrichit une liste de noms canoniques avec les details des concepts.

        PR4: Reçoit des canonical_name (pas des concept_id) car la comparaison
        se fait par nom pour trouver les concepts sémantiquement identiques.
        """
        if not concept_names:
            return []

        client = self._get_neo4j_client()

        # PR4: Recherche par canonical_name au lieu de concept_id
        query = """
        UNWIND $concept_names AS cname
        MATCH (cc:CanonicalConcept {canonical_name: cname})
        OPTIONAL MATCH (pc:ProtoConcept)-[:INSTANCE_OF]->(cc)
        WHERE pc.tenant_id = $tenant_id
        OPTIONAL MATCH (pc)-[:EXTRACTED_FROM]->(d:Document)
        WITH cname, cc, collect(DISTINCT pc)[0] AS pc, collect(DISTINCT d)[0] AS d
        RETURN
            COALESCE(pc.concept_id, cc.canonical_id) AS concept_id,
            cname AS label,
            cc.canonical_id AS canonical_id,
            cc.canonical_name AS canonical_name,
            'unknown' AS polarity,
            'unknown' AS scope,
            0.5 AS confidence,
            COALESCE(d.global_markers, []) AS markers,
            d.id AS document_id
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    concept_names=concept_names,
                    tenant_id=self.tenant_id
                )
                return [
                    ConceptInfo(
                        concept_id=r["concept_id"] or r["canonical_name"],
                        label=r["label"] or "",
                        canonical_id=r["canonical_id"],
                        canonical_name=r["canonical_name"],
                        polarity=r["polarity"],
                        scope=r["scope"],
                        confidence=r["confidence"],
                        markers=r["markers"],
                        document_id=r["document_id"],
                    )
                    for r in result
                ]

        except Exception as e:
            logger.error(f"[ConceptDiffService] Enrich failed: {e}")
            return [ConceptInfo(concept_id=cname, label=cname) for cname in concept_names]

    async def _detect_polarity_changes(
        self,
        concept_ids: List[str],
        marker_a: str,
        marker_b: str,
    ) -> List[Dict[str, Any]]:
        """Detecte les changements de polarity entre deux markers."""
        changes = []

        client = self._get_neo4j_client()

        query = """
        UNWIND $concept_ids AS cid
        MATCH (pc:ProtoConcept {concept_id: cid, tenant_id: $tenant_id})
        MATCH (pc)-[r:EXTRACTED_FROM]->(d:Document)
        WHERE $marker_a IN r.markers OR $marker_b IN r.markers
        RETURN
            pc.concept_id AS concept_id,
            pc.concept_name AS label,
            r.polarity AS polarity,
            r.markers AS markers
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    concept_ids=concept_ids,
                    marker_a=marker_a,
                    marker_b=marker_b,
                    tenant_id=self.tenant_id
                )

                # Grouper par concept
                concept_assertions: Dict[str, Dict[str, str]] = {}
                for r in result:
                    cid = r["concept_id"]
                    markers = r["markers"] or []
                    polarity = r["polarity"] or "unknown"

                    if cid not in concept_assertions:
                        concept_assertions[cid] = {
                            "label": r["label"],
                            "polarity_a": None,
                            "polarity_b": None,
                        }

                    if marker_a in markers:
                        concept_assertions[cid]["polarity_a"] = polarity
                    if marker_b in markers:
                        concept_assertions[cid]["polarity_b"] = polarity

                # Detecter les changements
                for cid, data in concept_assertions.items():
                    pa = data["polarity_a"]
                    pb = data["polarity_b"]
                    if pa and pb and pa != pb:
                        changes.append({
                            "concept_id": cid,
                            "label": data["label"],
                            "polarity_in_a": pa,
                            "polarity_in_b": pb,
                            "change_type": f"{pa}_to_{pb}",
                        })

        except Exception as e:
            logger.error(f"[ConceptDiffService] Polarity change detection failed: {e}")

        return changes


# Singleton
_diff_service_instances: Dict[str, ConceptDiffService] = {}


def get_concept_diff_service(tenant_id: str = "default") -> ConceptDiffService:
    """Retourne l'instance singleton du ConceptDiffService."""
    global _diff_service_instances
    if tenant_id not in _diff_service_instances:
        _diff_service_instances[tenant_id] = ConceptDiffService(tenant_id=tenant_id)
    return _diff_service_instances[tenant_id]


__all__ = [
    "DiffMode",
    "ConceptInfo",
    "AssertionInfo",
    "ConceptDiffResult",
    "AssertionQueryResult",
    "ConceptDiffService",
    "get_concept_diff_service",
]
