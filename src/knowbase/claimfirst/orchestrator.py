# src/knowbase/claimfirst/orchestrator.py
"""
ClaimFirstOrchestrator - Pipeline claim-first complet.

Orchestre toutes les phases du pipeline:
0. Extraire DocumentContext (INV-8: scope appartient au document)
0.5. Résoudre SubjectAnchors (INV-9: résolution conservative)
1. Indexer Passages (DocItems → Passages avec units)
2. Extraire Claims (pointer mode, verbatim garanti)
3. Extraire Entities (light, déterministe)
4. Matcher Facets (déterministe)
5. Linker (Passage→Claim, Claim→Entity, Claim→Facet)
6. Cluster Claims (dedup inter-docs)
7. Détecter Relations (CONTRADICTS, REFINES, QUALIFIES)
8. Persist Neo4j
9. Bridge Layer R (adapter pour claims)

INV-8: Applicability over Truth (scope = DocumentContext)
INV-9: Conservative Subject Resolution (aliases typés)
INV-10: Discriminants Découverts, pas Hardcodés
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.entity import Entity
from knowbase.claimfirst.models.facet import Facet
from knowbase.claimfirst.models.passage import Passage
from knowbase.claimfirst.models.result import ClaimFirstResult, ClaimCluster
from knowbase.claimfirst.models.subject_anchor import SubjectAnchor
from knowbase.claimfirst.models.document_context import DocumentContext, ResolutionStatus

from knowbase.claimfirst.extractors.claim_extractor import ClaimExtractor
from knowbase.claimfirst.extractors.entity_extractor import EntityExtractor
from knowbase.claimfirst.extractors.context_extractor import ContextExtractor
from knowbase.claimfirst.resolution.subject_resolver import SubjectResolver
from knowbase.claimfirst.linkers.passage_linker import PassageLinker
from knowbase.claimfirst.linkers.entity_linker import EntityLinker
from knowbase.claimfirst.linkers.facet_matcher import FacetMatcher
from knowbase.claimfirst.clustering.claim_clusterer import ClaimClusterer
from knowbase.claimfirst.clustering.relation_detector import RelationDetector
from knowbase.claimfirst.persistence.claim_persister import ClaimPersister

from knowbase.stratified.pass0.cache_loader import CacheLoadResult
from knowbase.stratified.pass1.assertion_unit_indexer import UnitIndexResult

logger = logging.getLogger(__name__)


class ClaimFirstOrchestrator:
    """
    Pipeline claim-first complet.

    Orchestre l'extraction, le linking, le clustering et la persistance
    des claims documentées.
    """

    def __init__(
        self,
        llm_client: Any,
        neo4j_driver: Any = None,
        embeddings_client: Any = None,
        tenant_id: str = "default",
        persist_enabled: bool = True,
    ):
        """
        Initialise l'orchestrateur.

        Args:
            llm_client: Client LLM pour extraction des claims
            neo4j_driver: Driver Neo4j pour persistance (optionnel)
            embeddings_client: Client embeddings pour clustering (optionnel)
            tenant_id: Tenant ID
            persist_enabled: Si True, persiste les résultats
        """
        self.llm_client = llm_client
        self.neo4j_driver = neo4j_driver
        self.embeddings_client = embeddings_client
        self.tenant_id = tenant_id
        self.persist_enabled = persist_enabled

        # Composants Phase 1.5 (INV-8, INV-9)
        self.context_extractor = ContextExtractor(
            llm_client=llm_client,
            use_llm_subjects=True,
        )
        self.subject_resolver = SubjectResolver(
            embeddings_client=embeddings_client,
            tenant_id=tenant_id,
        )

        # Composants Phase 1
        self.claim_extractor = ClaimExtractor(llm_client)
        self.entity_extractor = EntityExtractor()
        self.passage_linker = PassageLinker()
        self.entity_linker = EntityLinker()
        self.facet_matcher = FacetMatcher()
        self.claim_clusterer = ClaimClusterer()
        self.relation_detector = RelationDetector()

        # Persistance
        if neo4j_driver:
            self.persister = ClaimPersister(neo4j_driver, tenant_id)
        else:
            self.persister = None

        # Cache des SubjectAnchors connus
        self._subject_anchors: List[SubjectAnchor] = []

    def process(
        self,
        doc_id: str,
        cache_result: CacheLoadResult,
        tenant_id: Optional[str] = None,
    ) -> ClaimFirstResult:
        """
        Traite un document complet.

        Args:
            doc_id: Document ID
            cache_result: Résultat du cache Pass0
            tenant_id: Tenant ID (override)

        Returns:
            ClaimFirstResult avec tous les artefacts
        """
        tenant_id = tenant_id or self.tenant_id
        start_time = time.time()

        logger.info(f"[OSMOSE:ClaimFirst] Processing document {doc_id}...")

        # Vérifier le cache
        if not cache_result.success or not cache_result.pass0_result:
            logger.error(f"[OSMOSE:ClaimFirst] Invalid cache result for {doc_id}")
            return ClaimFirstResult(
                tenant_id=tenant_id,
                doc_id=doc_id,
            )

        pass0 = cache_result.pass0_result
        doc_title = cache_result.doc_title or doc_id

        # Phase 0: Créer les Passages depuis les DocItems
        logger.info("[OSMOSE:ClaimFirst] Phase 0: Creating passages...")
        passages = self._create_passages(pass0, tenant_id)
        logger.info(f"  → {len(passages)} passages created")

        # Phase 0.5: Extraire DocumentContext et résoudre SubjectAnchors (INV-8, INV-9)
        logger.info("[OSMOSE:ClaimFirst] Phase 0.5: Extracting document context...")
        doc_context = self._extract_document_context(
            doc_id=doc_id,
            tenant_id=tenant_id,
            passages=passages,
            doc_title=doc_title,
        )
        logger.info(
            f"  → Context: {len(doc_context.raw_subjects)} subjects, "
            f"{len(doc_context.qualifiers)} qualifiers, "
            f"status={doc_context.resolution_status.value}"
        )

        # Phase 1: Extraire les Claims (pointer mode)
        logger.info("[OSMOSE:ClaimFirst] Phase 1: Extracting claims...")
        claims, unit_index = self.claim_extractor.extract(
            passages=passages,
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_title=doc_title,
        )
        logger.info(f"  → {len(claims)} claims extracted")

        # Phase 2: Extraire les Entities
        logger.info("[OSMOSE:ClaimFirst] Phase 2: Extracting entities...")
        entities, claim_entity_map = self.entity_extractor.extract_from_claims(
            claims=claims,
            passages=passages,
            tenant_id=tenant_id,
        )
        logger.info(f"  → {len(entities)} entities extracted")

        # Phase 3: Matcher les Facets
        logger.info("[OSMOSE:ClaimFirst] Phase 3: Matching facets...")
        facets, claim_facet_links = self.facet_matcher.match(
            claims=claims,
            tenant_id=tenant_id,
        )
        logger.info(f"  → {len(facets)} facets matched")

        # Phase 4: Linking
        logger.info("[OSMOSE:ClaimFirst] Phase 4: Linking...")

        # Claim → Passage (SUPPORTED_BY)
        claim_passage_links = self.passage_linker.link(
            claims=claims,
            passages=passages,
            unit_index=unit_index,
        )

        # Claim → Entity (ABOUT)
        claim_entity_links = self.entity_linker.link(
            claims=claims,
            entities=entities,
        )

        logger.info(
            f"  → {len(claim_passage_links)} passage links, "
            f"{len(claim_entity_links)} entity links, "
            f"{len(claim_facet_links)} facet links"
        )

        # Phase 5: Clustering (si plusieurs claims)
        logger.info("[OSMOSE:ClaimFirst] Phase 5: Clustering...")
        clusters: List[ClaimCluster] = []
        claim_cluster_links: List[Tuple[str, str]] = []

        if len(claims) >= 2:
            # Générer embeddings si client disponible
            embeddings = self._generate_embeddings(claims) if self.embeddings_client else None

            clusters = self.claim_clusterer.cluster(
                claims=claims,
                embeddings=embeddings,
                entities_by_claim=claim_entity_map,
                tenant_id=tenant_id,
            )

            # Créer les liens Claim → Cluster
            for cluster in clusters:
                for claim_id in cluster.claim_ids:
                    claim_cluster_links.append((claim_id, cluster.cluster_id))
                    # Mettre à jour le cluster_id sur la claim
                    claim = next((c for c in claims if c.claim_id == claim_id), None)
                    if claim:
                        claim.cluster_id = cluster.cluster_id

        logger.info(f"  → {len(clusters)} clusters created")

        # Phase 6: Détection de relations
        logger.info("[OSMOSE:ClaimFirst] Phase 6: Detecting relations...")
        relations = self.relation_detector.detect(
            claims=claims,
            clusters=clusters if clusters else None,
            entities_by_claim=claim_entity_map,
        )
        logger.info(f"  → {len(relations)} relations detected")

        # Construire le résultat
        processing_time_ms = int((time.time() - start_time) * 1000)
        extractor_stats = self.claim_extractor.get_stats()

        result = ClaimFirstResult(
            tenant_id=tenant_id,
            doc_id=doc_id,
            passages=passages,
            claims=claims,
            entities=entities,
            facets=facets,
            clusters=clusters,
            relations=relations,
            claim_passage_links=claim_passage_links,
            claim_entity_links=claim_entity_links,
            claim_facet_links=claim_facet_links,
            claim_cluster_links=claim_cluster_links,
            processing_time_ms=processing_time_ms,
            llm_calls=extractor_stats.get("llm_calls", 0),
            llm_tokens_used=extractor_stats.get("tokens_used", 0),
        )

        logger.info(
            f"[OSMOSE:ClaimFirst] Processing complete: "
            f"{result.claim_count} claims, "
            f"{result.entity_count} entities, "
            f"{result.facet_count} facets, "
            f"{result.cluster_count} clusters in {processing_time_ms}ms"
        )

        return result

    def process_and_persist(
        self,
        doc_id: str,
        cache_result: CacheLoadResult,
        tenant_id: Optional[str] = None,
    ) -> ClaimFirstResult:
        """
        Traite et persiste un document.

        Args:
            doc_id: Document ID
            cache_result: Résultat du cache Pass0
            tenant_id: Tenant ID (override)

        Returns:
            ClaimFirstResult avec tous les artefacts
        """
        result = self.process(doc_id, cache_result, tenant_id)

        # Phase 7: Persist Neo4j
        if self.persist_enabled and self.persister:
            logger.info("[OSMOSE:ClaimFirst] Phase 7: Persisting to Neo4j...")
            persist_stats = self.persister.persist(result)
            logger.info(f"  → {persist_stats}")

        return result

    def _create_passages(
        self,
        pass0,
        tenant_id: str,
    ) -> List[Passage]:
        """
        Crée les Passages depuis les DocItems du Pass0.

        Args:
            pass0: Pass0Result
            tenant_id: Tenant ID

        Returns:
            Liste de Passages
        """
        passages = []

        for doc_item in pass0.doc_items:
            passage = Passage.from_docitem(
                docitem=doc_item,
                tenant_id=tenant_id,
            )
            passages.append(passage)

        return passages

    def _generate_embeddings(
        self,
        claims: List[Claim],
    ) -> Dict[str, Any]:
        """
        Génère les embeddings pour les claims.

        Args:
            claims: Claims à encoder

        Returns:
            Dict claim_id → embedding vector
        """
        if not self.embeddings_client:
            return {}

        embeddings = {}
        texts = [c.text for c in claims]

        try:
            # Interface OpenAI-like
            if hasattr(self.embeddings_client, "embeddings"):
                response = self.embeddings_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=texts,
                )
                for i, claim in enumerate(claims):
                    embeddings[claim.claim_id] = response.data[i].embedding

            # Interface custom
            elif hasattr(self.embeddings_client, "encode"):
                vectors = self.embeddings_client.encode(texts)
                for i, claim in enumerate(claims):
                    embeddings[claim.claim_id] = vectors[i]

        except Exception as e:
            logger.warning(f"[OSMOSE:ClaimFirst] Failed to generate embeddings: {e}")

        return embeddings

    def _extract_document_context(
        self,
        doc_id: str,
        tenant_id: str,
        passages: List[Passage],
        doc_title: Optional[str] = None,
    ) -> DocumentContext:
        """
        Extrait le DocumentContext et résout les SubjectAnchors.

        INV-8: Le scope appartient au Document, pas à la Claim.
        INV-9: Résolution conservative des sujets.

        Args:
            doc_id: Document ID
            tenant_id: Tenant ID
            passages: Passages du document
            doc_title: Titre du document

        Returns:
            DocumentContext configuré avec sujets résolus
        """
        # 1. Extraire le contexte (sujets bruts, qualificateurs)
        context = self.context_extractor.extract(
            doc_id=doc_id,
            tenant_id=tenant_id,
            passages=passages,
            doc_title=doc_title,
        )

        # 2. Résoudre les sujets vers SubjectAnchors (INV-9)
        if context.raw_subjects:
            results = self.subject_resolver.resolve_batch(
                raw_subjects=context.raw_subjects,
                existing_anchors=self._subject_anchors,
                doc_id=doc_id,
            )

            for result in results:
                if result.anchor:
                    context.add_subject(
                        subject_id=result.anchor.subject_id,
                        status=result.status,
                        confidence=result.confidence,
                    )

                    # Ajouter le doc aux sources du SubjectAnchor
                    if doc_id not in result.anchor.source_doc_ids:
                        result.anchor.source_doc_ids.append(doc_id)

                    # Mettre à jour le cache si nouveau
                    if result.match_type == "new":
                        self._subject_anchors.append(result.anchor)

        return context

    def load_subject_anchors_from_neo4j(self) -> int:
        """
        Charge les SubjectAnchors existants depuis Neo4j.

        Utilisé au démarrage pour initialiser le cache.

        Returns:
            Nombre de SubjectAnchors chargés
        """
        if not self.neo4j_driver:
            return 0

        try:
            with self.neo4j_driver.session() as session:
                result = session.run(
                    """
                    MATCH (sa:SubjectAnchor {tenant_id: $tenant_id})
                    RETURN sa
                    """,
                    {"tenant_id": self.tenant_id}
                )

                self._subject_anchors = []
                for record in result:
                    anchor_data = dict(record["sa"])
                    anchor = SubjectAnchor.from_neo4j_record(anchor_data)
                    self._subject_anchors.append(anchor)

                logger.info(
                    f"[OSMOSE:ClaimFirst] Loaded {len(self._subject_anchors)} "
                    f"SubjectAnchors from Neo4j"
                )

                return len(self._subject_anchors)

        except Exception as e:
            logger.warning(f"[OSMOSE:ClaimFirst] Failed to load SubjectAnchors: {e}")
            return 0

    def get_stats(self) -> dict:
        """Retourne les statistiques agrégées."""
        return {
            "context_extractor": self.context_extractor.get_stats(),
            "subject_resolver": self.subject_resolver.get_stats(),
            "claim_extractor": self.claim_extractor.get_stats(),
            "entity_extractor": self.entity_extractor.get_stats(),
            "passage_linker": self.passage_linker.get_stats(),
            "entity_linker": self.entity_linker.get_stats(),
            "facet_matcher": self.facet_matcher.get_stats(),
            "claim_clusterer": self.claim_clusterer.get_stats(),
            "relation_detector": self.relation_detector.get_stats(),
            "persister": self.persister.get_stats() if self.persister else {},
            "subject_anchors_cached": len(self._subject_anchors),
        }

    def reset_stats(self) -> None:
        """Réinitialise toutes les statistiques."""
        self.context_extractor.reset_stats()
        self.subject_resolver.reset_stats()
        self.claim_extractor.reset_stats()
        self.entity_extractor.reset_stats()
        self.passage_linker.reset_stats()
        self.entity_linker.reset_stats()
        self.facet_matcher.reset_stats()
        self.claim_clusterer.reset_stats()
        self.relation_detector.reset_stats()
        if self.persister:
            self.persister.reset_stats()


__all__ = [
    "ClaimFirstOrchestrator",
]
