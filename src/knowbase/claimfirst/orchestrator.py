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

import json
import logging
import os
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.entity import Entity
from knowbase.claimfirst.models.facet import Facet, FacetLifecycle
from knowbase.claimfirst.extractors.facet_candidate_extractor import FacetCandidateExtractor
from knowbase.claimfirst.linkers.facet_registry import FacetRegistry
from knowbase.claimfirst.models.passage import Passage
from knowbase.claimfirst.models.result import ClaimFirstResult, ClaimCluster
from knowbase.claimfirst.models.subject_anchor import SubjectAnchor
from knowbase.claimfirst.models.document_context import DocumentContext, ResolutionStatus

from knowbase.claimfirst.extractors.claim_extractor import ClaimExtractor
from knowbase.claimfirst.constants import CANONICAL_PREDICATES
from knowbase.claimfirst.extractors.entity_extractor import EntityExtractor
from knowbase.claimfirst.extractors.entity_canonicalizer import EntityCanonicalizer
from knowbase.claimfirst.extractors.context_extractor import ContextExtractor
from knowbase.claimfirst.resolution.subject_resolver import SubjectResolver
from knowbase.claimfirst.resolution.subject_resolver_v2 import SubjectResolverV2
from knowbase.claimfirst.models.comparable_subject import ComparableSubject
from knowbase.claimfirst.axes.axis_detector import ApplicabilityAxisDetector
from knowbase.claimfirst.axes.axis_order_inferrer import AxisOrderInferrer
from knowbase.claimfirst.axes.axis_value_validator import AxisValueValidator
from knowbase.claimfirst.models.applicability_axis import ApplicabilityAxis
from knowbase.claimfirst.applicability import (
    EvidenceUnitSegmenter,
    CandidateMiner,
    FrameBuilder,
    FrameValidationPipeline,
    FrameAdapter,
    ApplicabilityFrame,
)
from knowbase.claimfirst.linkers.passage_linker import PassageLinker
from knowbase.claimfirst.linkers.entity_linker import EntityLinker
from knowbase.claimfirst.linkers.facet_matcher import FacetMatcher
from knowbase.claimfirst.clustering.claim_clusterer import ClaimClusterer
from knowbase.claimfirst.clustering.relation_detector import RelationDetector
from knowbase.claimfirst.composition.chain_detector import ChainDetector
from knowbase.claimfirst.composition.slot_enricher import SlotEnricher
from knowbase.claimfirst.persistence.claim_persister import ClaimPersister
from knowbase.claimfirst.quality_filters import filter_claims_quality

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
        facet_registry: Optional["FacetRegistry"] = None,
    ):
        """
        Initialise l'orchestrateur.

        Args:
            llm_client: Client LLM pour extraction des claims
            neo4j_driver: Driver Neo4j pour persistance (optionnel)
            embeddings_client: Client embeddings pour clustering (optionnel)
            tenant_id: Tenant ID
            persist_enabled: Si True, persiste les résultats
            facet_registry: Registre de facettes partagé (optionnel, créé sinon)
        """
        self.llm_client = llm_client
        self.neo4j_driver = neo4j_driver
        self.embeddings_client = embeddings_client
        self.tenant_id = tenant_id
        self.persist_enabled = persist_enabled

        # Predicats effectifs : merge core + domain packs actifs du tenant
        from knowbase.claimfirst.constants import get_effective_predicates
        (
            self._effective_predicates,
            self._effective_predicate_descriptions,
            self._effective_predicate_norm_map,
        ) = get_effective_predicates(tenant_id)
        logger.info(
            f"[OSMOSE:ClaimFirst] Effective predicates for tenant={tenant_id}: "
            f"{len(self._effective_predicates)} canonical "
            f"({len(self._effective_predicates - CANONICAL_PREDICATES)} domain-specific)"
        )

        # Composants Phase 1.5 (INV-8, INV-9)
        self.context_extractor = ContextExtractor(
            llm_client=llm_client,
            use_llm_subjects=True,
        )
        self.subject_resolver = SubjectResolver(
            embeddings_client=embeddings_client,
            tenant_id=tenant_id,
        )

        # Composant SubjectResolverV2 (INV-25: Domain-Agnostic)
        # Résout le ComparableSubject + classifie en AXIS_VALUE/DOC_TYPE/NOISE
        self.subject_resolver_v2 = SubjectResolverV2(
            tenant_id=tenant_id,
            llm_client=llm_client,
        )

        # Composant Applicability Axis (INV-12, INV-14, INV-25, INV-26)
        # LLM-first extraction (INV-25 Domain Agnosticism)
        self.axis_detector = ApplicabilityAxisDetector(
            llm_client=llm_client,
            use_llm_extraction=True,  # LLM-first pour versioning domain-agnostic
            tenant_id=tenant_id,
        )

        # Composant Axis Value Validator (Extract-then-Validate pattern)
        self.axis_validator = AxisValueValidator(
            llm_client=llm_client,
            max_passages_sample=3,
            tenant_id=tenant_id,
        )

        # Composants Phase 1
        self.claim_extractor = ClaimExtractor(
            llm_client,
            canonical_predicates=self._effective_predicates,
            predicate_descriptions=self._effective_predicate_descriptions,
            predicate_normalization_map=self._effective_predicate_norm_map,
        )
        self.entity_extractor = EntityExtractor(
            max_entity_length=50,
            max_entity_words=6,  # Noms marketing SAP font parfois 6 mots
        )
        self.entity_canonicalizer = EntityCanonicalizer(tenant_id=tenant_id)
        self.noun_chunk_extractor = None  # Lazy init (spaCy models loaded on first use)
        self.passage_linker = PassageLinker()
        self.entity_linker = EntityLinker()
        self.facet_matcher = FacetMatcher()
        self.facet_extractor = FacetCandidateExtractor()
        self.facet_registry = facet_registry or FacetRegistry(tenant_id)
        self.claim_clusterer = ClaimClusterer()
        self.relation_detector = RelationDetector()
        self.chain_detector = ChainDetector(
            canonical_predicates=self._effective_predicates,
        )
        self.slot_enricher = SlotEnricher(
            canonical_predicates=self._effective_predicates,
            predicate_descriptions=self._effective_predicate_descriptions,
            predicate_normalization_map=self._effective_predicate_norm_map,
        )

        # Persistance
        if neo4j_driver:
            self.persister = ClaimPersister(neo4j_driver, tenant_id)
        else:
            self.persister = None

        # Cache des SubjectAnchors connus
        self._subject_anchors: List[SubjectAnchor] = []

        # Cache des ApplicabilityAxis connus
        self._applicability_axes: List[ApplicabilityAxis] = []

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
        # Utiliser le titre du cache, ou None si absent (pas le doc_id comme fallback)
        # Le doc_id est un nom de fichier qui cause des extractions erronées
        doc_title = cache_result.doc_title if cache_result.doc_title else None
        # Pour les autres usages, on garde doc_id comme fallback pour l'affichage
        doc_title_display = doc_title or doc_id

        # Phase 0: Créer les Passages depuis les DocItems
        logger.info("[OSMOSE:ClaimFirst] Phase 0: Creating passages...")
        passages = self._create_passages(pass0, tenant_id)
        logger.info(f"  → {len(passages)} passages created")

        # Phase 0.5: Extraire DocumentContext et résoudre SubjectAnchors (INV-8, INV-9)
        logger.info("[OSMOSE:ClaimFirst] Phase 0.5: Extracting document context...")
        existing_subject_ids = {a.subject_id for a in self._subject_anchors}
        doc_context, new_anchors = self._extract_document_context(
            doc_id=doc_id,
            tenant_id=tenant_id,
            passages=passages,
            doc_title=doc_title,
        )
        logger.info(
            f"  → Context: primary='{doc_context.primary_subject}', "
            f"{len(doc_context.raw_subjects)} topics, "
            f"{len(doc_context.subject_ids)} resolved, "
            f"{len(doc_context.qualifiers)} qualifiers, "
            f"{len(new_anchors)} new anchors, "
            f"status={doc_context.resolution_status.value}"
        )

        # Phase 0.5c : Detection de langue du document via fasttext
        # Utilise les 3 premiers passages (texte long = detection fiable)
        if not doc_context.language:
            try:
                from knowbase.common.language_detector import detect_language

                sample_text = " ".join(p.text for p in passages[:3] if p.text)[:2000]
                if sample_text:
                    lang = detect_language(sample_text, min_confidence=0.70)
                    if lang:
                        doc_context.language = lang
                        logger.info(f"  → Language detected: {lang}")
            except Exception as e:
                logger.debug(f"  → Language detection failed (non-blocking): {e}")

        # Phase 0.5b: Valider les nouveaux sujets via LLM (quality gate)
        new_created = [a for a in new_anchors if a.subject_id not in existing_subject_ids]
        if new_created:
            new_anchors = self._validate_new_subjects_llm(
                new_created, all_anchors=new_anchors,
                doc_context=doc_context, doc_title=doc_title,
            )

        # Enrichir doc_title depuis le primary_subject si absent du cache
        # Le primary_subject est extrait par le LLM et contient souvent le titre réel
        if not doc_title and doc_context.primary_subject:
            doc_title = doc_context.primary_subject
            logger.info(f"  → doc_title inferred from primary_subject: '{doc_title}'")

        # Enrichir doc_title avec année/version depuis les premiers passages
        # Le titre du cache est souvent tronqué (ex: "SAP S/4HANA Security Guide")
        # alors que le full_text contient "Security Guide for SAP S/4HANA 2023"
        enriched_title = self._enrich_title_from_passages(doc_title, passages)
        if enriched_title and enriched_title != doc_title:
            logger.info(
                f"  → doc_title enriched from passages: '{doc_title}' → '{enriched_title}'"
            )
            doc_title = enriched_title

        # Phase 0.55: Resolve ComparableSubject (INV-25: Domain-Agnostic)
        logger.info("[OSMOSE:ClaimFirst] Phase 0.55: Resolving comparable subject...")
        comparable_subject, resolver_axis_values = self._resolve_comparable_subject(
            doc_id=doc_id,
            tenant_id=tenant_id,
            passages=passages,
            doc_context=doc_context,
            doc_title=doc_title,
        )
        if comparable_subject:
            # Propager le doc_id au ComparableSubject
            comparable_subject.add_doc_reference(doc_id)

            # Mettre à jour le resolution_status du DocumentContext
            cs_status = (
                ResolutionStatus.RESOLVED
                if comparable_subject.confidence >= 0.85
                else ResolutionStatus.LOW_CONFIDENCE
            )
            doc_context.resolution_status = cs_status
            doc_context.resolution_confidence = max(
                doc_context.resolution_confidence,
                comparable_subject.confidence,
            )

            logger.info(
                f"  → ComparableSubject: '{comparable_subject.canonical_name}' "
                f"(confidence={comparable_subject.confidence:.2f}, "
                f"status={cs_status.value})"
            )
        else:
            logger.info("  → ComparableSubject: abstained or not resolved")

        # Phase 0.56: Fallback promotion status
        # Si primary_subject + subject_ids sont populés mais status reste UNRESOLVED
        # (ComparableSubject a abstenu), promouvoir à RESOLVED. Un doc avec sujet
        # identifié par le LLM ne devrait pas etre classe "unresolved".
        if (
            doc_context.primary_subject
            and doc_context.subject_ids
            and doc_context.resolution_status == ResolutionStatus.UNRESOLVED
        ):
            doc_context.resolution_status = ResolutionStatus.RESOLVED
            logger.info(
                "  → Phase 0.56: promoted to RESOLVED "
                "(primary_subject + subject_ids present)"
            )

        # Phase 0.6: Build applicability frame (evidence-locked, replaces AxisDetector)
        logger.info("[OSMOSE:ClaimFirst] Phase 0.6: Building applicability frame...")
        applicability_frame, detected_axes = self._build_applicability_frame(
            doc_id=doc_id,
            tenant_id=tenant_id,
            passages=passages,
            doc_context=doc_context,
            doc_title=doc_title,
            resolver_axis_values=resolver_axis_values,
        )
        logger.info(
            f"  → {len(detected_axes)} axes detected: "
            f"{[ax.axis_key for ax in detected_axes]}"
        )
        if applicability_frame:
            logger.info(
                f"  → Frame: {len(applicability_frame.fields)} fields, "
                f"{len(applicability_frame.unknowns)} unknowns, "
                f"method={applicability_frame.method}"
            )

        # Phase 1: Extraire les Claims (pointer mode, prompt V2 enrichi)
        logger.info("[OSMOSE:ClaimFirst] Phase 1: Extracting claims (V2 prompt)...")
        domain_context_block = self._get_domain_context_block(tenant_id)
        claims, unit_index = self.claim_extractor.extract(
            passages=passages,
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_title=doc_title,
            doc_subject=doc_context.primary_subject or "",
            domain_context=domain_context_block,
        )
        logger.info(f"  → {len(claims)} claims extracted")

        # Phase 1.4: Gate Vérifiabilité (AVANT dedup — claims déjà vérifiées)
        skip_quality_gates = os.getenv("OSMOSE_SKIP_QUALITY_GATES", "false").lower() == "true"
        gate_runner = None
        if not skip_quality_gates:
            logger.info("[OSMOSE:ClaimFirst] Phase 1.4: Verifiability gate...")
            from knowbase.claimfirst.quality import QualityGateRunner
            gate_runner = QualityGateRunner()
            claims, verif_stats = gate_runner.run_verifiability_gate(claims)
            logger.info(
                f"  → {verif_stats['rejected_fabrication']} rejected, "
                f"{verif_stats['rewritten_evidence']} rewritten, "
                f"{verif_stats.get('bucket_not_claimable', 0)} not claimable, "
                f"{verif_stats['total_output']}/{verif_stats['total_input']} kept"
            )

        # Phase 1.5: Déduplication déterministe (texte exact + triplet S/P/O)
        logger.info("[OSMOSE:ClaimFirst] Phase 1.5: Deduplicating claims...")
        claims, dedup_stats = self._deduplicate_claims(claims)
        logger.info(
            f"  → {dedup_stats['kept']} claims kept, "
            f"{dedup_stats['removed_text']} removed (exact text), "
            f"{dedup_stats['removed_spo']} removed (SPO triplet)"
        )

        # Phase 1.6: Filtrage qualité (post-dedup, pré-enrichment)
        logger.info("[OSMOSE:ClaimFirst] Phase 1.6: Quality filtering...")
        claims, quality_stats = self._filter_claims_quality(claims)
        logger.info(
            f"  → {quality_stats['kept']} kept, "
            f"{quality_stats['filtered_short']} too short, "
            f"{quality_stats['filtered_boilerplate']} boilerplate, "
            f"{quality_stats['filtered_heading']} heading-like"
        )

        # Phase 1.6b-c: Gates déterministes + Atomicity splitter
        if not skip_quality_gates and gate_runner:
            logger.info("[OSMOSE:ClaimFirst] Phase 1.6b-c: Deterministic gates + atomicity...")
            claims, det_stats = gate_runner.run_deterministic_and_atomicity_gates(claims)
            logger.info(
                f"  → {det_stats['rejected_tautology']} tautology, "
                f"{det_stats['rejected_template']} template leak, "
                f"{det_stats['sf_discarded']} SF discarded, "
                f"{det_stats['claims_split']} split → "
                f"{det_stats['total_output']}/{det_stats['total_input']} after gates"
            )

        # Phase 1.7: Slot enrichment (claims sans structured_form)
        claims_without_sf = [c for c in claims if not c.structured_form]
        if claims_without_sf:
            logger.info(
                f"[OSMOSE:ClaimFirst] Phase 1.7: Enriching {len(claims_without_sf)} "
                f"claims without structured_form..."
            )
            enrichment_result = self.slot_enricher.enrich(claims_without_sf)
            logger.info(
                f"  → {enrichment_result.claims_enriched}/{len(claims_without_sf)} enriched"
            )

        # Phase 2: Extraire les Entities
        logger.info("[OSMOSE:ClaimFirst] Phase 2: Extracting entities...")
        entities, claim_entity_map = self.entity_extractor.extract_from_claims(
            claims=claims,
            passages=passages,
            tenant_id=tenant_id,
        )
        logger.info(f"  → {len(entities)} entities extracted")

        # Phase 2.1: NounChunk extraction (domain-agnostic, text-anchored)
        # Complète l'EntityExtractor regex avec des noun chunks spaCy pour
        # les claims sans entité — résout le problème des corpus non-techniques.
        logger.info("[OSMOSE:ClaimFirst] Phase 2.1: NounChunk entity extraction...")
        claims_without_entity = [
            c for c in claims
            if c.claim_id not in claim_entity_map or not claim_entity_map[c.claim_id]
        ]
        if claims_without_entity:
            try:
                from knowbase.claimfirst.extractors.noun_chunk_extractor import NounChunkExtractor

                if self.noun_chunk_extractor is None:
                    # Charger les domain_terms du pack actif
                    domain_terms = set()
                    try:
                        from knowbase.domain_packs.registry import get_pack_registry
                        registry = get_pack_registry()
                        for pack in registry.get_active_packs(tenant_id):
                            import json as _json
                            from pathlib import Path
                            for ctx_path in [
                                Path(__file__).parent.parent / "domain_packs" / pack.name / "context_defaults.json",
                                Path(f"/data/packs/{pack.name}/context_defaults.json"),
                            ]:
                                if ctx_path.exists():
                                    ctx = _json.loads(ctx_path.read_text(encoding="utf-8"))
                                    domain_terms.update(ctx.get("domain_terms", []))
                                    domain_terms.update(ctx.get("common_acronyms", {}).keys())
                                    break
                    except Exception:
                        pass

                    self.noun_chunk_extractor = NounChunkExtractor(domain_terms=domain_terms)

                # Construire l'index des entités déjà extraites
                existing_index = {e.normalized_name: e.entity_id for e in entities}

                nc_entities, nc_links = self.noun_chunk_extractor.extract_from_claims(
                    claims=claims_without_entity,
                    tenant_id=tenant_id,
                    existing_entity_index=existing_index,
                )

                # Fusionner avec les résultats existants
                entities.extend(nc_entities)
                for claim_id, entity_id in nc_links:
                    if claim_id not in claim_entity_map:
                        claim_entity_map[claim_id] = []
                    claim_entity_map[claim_id].append(entity_id)

                logger.info(
                    f"  → {len(nc_entities)} new noun-chunk entities, "
                    f"{len(nc_links)} new links "
                    f"(from {len(claims_without_entity)} orphan claims)"
                )
            except Exception as e:
                logger.warning(f"  → NounChunk extraction skipped: {e}")
        else:
            logger.info("  → 0 orphan claims, noun-chunk extraction skipped")

        # Phase 2.5: Canonicaliser les Entities (LLM-based fusion)
        logger.info("[OSMOSE:ClaimFirst] Phase 2.5: Canonicalizing entities...")
        # Construire claim_excerpts : entity_name → premier claim text mentionnant l'entité
        claim_excerpts: Dict[str, str] = {}
        claim_by_id = {c.claim_id: c for c in claims}
        for entity in entities:
            for claim_id, entity_ids in claim_entity_map.items():
                if entity.entity_id in entity_ids:
                    claim = claim_by_id.get(claim_id)
                    if claim:
                        claim_excerpts[entity.name] = claim.text
                        break
        entities, claim_entity_map = self.entity_canonicalizer.canonicalize(
            entities=entities,
            claim_entity_map=claim_entity_map,
            claim_excerpts=claim_excerpts,
        )
        logger.info(f"  → {len(entities)} entities after canonicalization")

        # Phase 2.6: Independence resolver (needs entities)
        if not skip_quality_gates and gate_runner:
            logger.info("[OSMOSE:ClaimFirst] Phase 2.6: Independence resolver...")
            claims, indep_stats = gate_runner.run_independence_gate(
                claims, claim_entity_map, passages, entities=entities,
            )
            logger.info(
                f"  → {indep_stats.get('resolved', 0)} resolved, "
                f"{indep_stats.get('bucketed', 0)} bucketed, "
                f"{indep_stats['total_output']}/{indep_stats['total_input']} after independence"
            )

        # Phase 2.7: Marquer PASS explicitement sur les claims restantes
        if not skip_quality_gates and gate_runner:
            pass_count = gate_runner.mark_pass_on_remaining(
                claims, gate_runner._verif_scores
            )
            logger.info(
                f"[OSMOSE:ClaimFirst] Phase 2.7: {pass_count} claims marquées PASS"
            )

        # Phase 2.8: Dériver SubjectAnchors depuis les entités canonicalisées
        logger.info("[OSMOSE:ClaimFirst] Phase 2.8: Deriving subjects from entities...")
        entity_subjects, doc_context = self._derive_subjects_from_entities(
            entities=entities,
            claim_entity_map=claim_entity_map,
            claims=claims,
            doc_context=doc_context,
            doc_id=doc_id,
            tenant_id=tenant_id,
            doc_title=doc_title,
        )
        if entity_subjects:
            new_anchors = entity_subjects
            logger.info(
                f"  → {len(entity_subjects)} entity-derived subjects "
                f"(replaced Phase 0.5 subjects)"
            )
        else:
            logger.info("  → No entity-derived subjects, keeping Phase 0.5 fallback")

        # Phase 2.9: Facet Candidate Extraction (1 LLM call per doc)
        logger.info("[OSMOSE:ClaimFirst] Phase 2.9: Extracting facet candidates...")
        facet_candidates = self.facet_extractor.extract(
            doc_context=doc_context,
            claims=claims,
            doc_title=doc_title,
        )
        self.facet_registry.register_candidates(facet_candidates)
        doc_facet_ids = [c.dimension_key for c in facet_candidates]
        logger.info(f"  → {len(facet_candidates)} facet candidates extracted")

        # Phase 3: Facet Assignment (déterministe, 4 signaux)
        logger.info("[OSMOSE:ClaimFirst] Phase 3: Matching facets...")
        validated_facets = self.facet_registry.get_validated_facets()
        facets, claim_facet_links = self.facet_matcher.match(
            claims=claims,
            tenant_id=tenant_id,
            validated_facets=validated_facets,
            doc_facet_ids=doc_facet_ids,
        )
        logger.info(f"  → {len(facets)} facets, {len(claim_facet_links)} links")

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

        # Phase 4.5: Domain Pack Enrichment (si packs actifs)
        logger.info("[OSMOSE:ClaimFirst] Phase 4.5: Domain Pack enrichment...")
        pack_new_entities, pack_new_links, pack_link_methods = (
            self._run_domain_pack_enrichment(
                claims=claims,
                entities=entities,
                claim_entity_links=claim_entity_links,
                tenant_id=tenant_id,
            )
        )
        if pack_new_entities:
            entities.extend(pack_new_entities)
            claim_entity_links.extend(pack_new_links)
            logger.info(
                f"  → {len(pack_new_entities)} new entities, "
                f"{len(pack_new_links)} new ABOUT links from domain packs"
            )
        else:
            logger.info("  → No domain packs active or no new entities")

        # Phase 4.6: Canonical Alias Resolution (renommer les entités via aliases domain pack)
        renamed_count = self._resolve_canonical_aliases(entities, tenant_id)
        if renamed_count > 0:
            logger.info(f"  → {renamed_count} entités renommées via canonical aliases")

        # Phase 4.7: Filtre entites non-linkees
        # Supprime les Entity crees (NounChunk + Extractor) qui ne sont referencees
        # par AUCUN claim_entity_link — sinon elles deviennent orphelines en base
        # (mention_count incremente mais pas de ABOUT persiste).
        linked_entity_ids = {eid for _, eid in claim_entity_links}
        before_filter = len(entities)
        entities = [e for e in entities if e.entity_id in linked_entity_ids]
        removed = before_filter - len(entities)
        if removed > 0:
            # Nettoyer aussi claim_entity_map pour coherence avec Phase 5/6 qui
            # l'utilisent (cluster + relation detectors resolvent eid contre entities)
            claim_entity_map = {
                cid: [eid for eid in eids if eid in linked_entity_ids]
                for cid, eids in claim_entity_map.items()
            }
            logger.info(
                f"  → Phase 4.7: {removed} entites non-linkees filtrees "
                f"(evite orphelines en base)"
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

        # Phase 6: Détection de relations (value-level CONTRADICTS + regex REFINES/QUALIFIES)
        logger.info("[OSMOSE:ClaimFirst] Phase 6: Detecting relations...")
        relations = self.relation_detector.detect(
            claims=claims,
            clusters=clusters if clusters else None,
            entities_by_claim=claim_entity_map,
            entities=entities,
        )
        logger.info(f"  → {len(relations)} relations detected")

        # Phase 6.5: Chaînes compositionnelles S/P/O
        logger.info("[OSMOSE:ClaimFirst] Phase 6.5: Detecting S/P/O chains...")
        chain_relations = self.chain_detector.detect(claims)
        relations.extend(chain_relations)
        logger.info(f"  → {len(chain_relations)} chains detected")

        # Phase 6.6: Extraction QuestionSignatures (Level A — regex, zero-cost)
        logger.info("[OSMOSE:ClaimFirst] Phase 6.6: Extracting QuestionSignatures...")
        question_signatures = self._extract_question_signatures(claims, doc_id, tenant_id)
        logger.info(f"  → {len(question_signatures)} QuestionSignatures extracted (Level A)")

        # Construire le résultat
        processing_time_ms = int((time.time() - start_time) * 1000)
        extractor_stats = self.claim_extractor.get_stats()

        result = ClaimFirstResult(
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_context=doc_context,
            comparable_subject=comparable_subject,
            subject_anchors=new_anchors,
            detected_axes=detected_axes,
            applicability_frame=applicability_frame,
            passages=passages,
            claims=claims,
            entities=entities,
            facets=facets,
            clusters=clusters,
            relations=relations,
            question_signatures=question_signatures,
            claim_passage_links=claim_passage_links,
            claim_entity_links=claim_entity_links,
            claim_facet_links=claim_facet_links,
            claim_cluster_links=claim_cluster_links,
            claim_entity_link_methods=pack_link_methods,
            processing_time_ms=processing_time_ms,
            llm_calls=extractor_stats.get("llm_calls", 0),
            llm_tokens_used=extractor_stats.get("tokens_used", 0),
        )

        logger.info(
            f"[OSMOSE:ClaimFirst] Processing complete: "
            f"{result.claim_count} claims, "
            f"{result.entity_count} entities, "
            f"{result.facet_count} facets, "
            f"{result.cluster_count} clusters, "
            f"{result.qs_count} QS in {processing_time_ms}ms"
        )

        # Ligne résumé structurée logfmt — parsable par Loki pour dashboard Grafana
        logger.info(
            f"[CLAIMFIRST:SUMMARY] "
            f"doc_id={doc_id} "
            f"claims={result.claim_count} "
            f"entities={result.entity_count} "
            f"facets={result.facet_count} "
            f"clusters={result.cluster_count} "
            f"qs={result.qs_count} "
            f"llm_calls={result.llm_calls} "
            f"llm_tokens={result.llm_tokens_used} "
            f"duration_ms={processing_time_ms}"
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

        # Phase 7.5: Classification des tensions (tension_level + tension_nature)
        # Appelle ContradictionClassifier sur les CONTRADICTS fraichement persistees
        # (filtre reviewed=false). Non-bloquant : une erreur n'arrete pas l'import.
        if self.persist_enabled and self.neo4j_driver and result.relations:
            has_contradicts = any(
                getattr(r, "relation_type", None) == "CONTRADICTS"
                for r in result.relations
            )
            if has_contradicts:
                try:
                    from knowbase.claimfirst.clustering.contradiction_classifier import (
                        ContradictionClassifier,
                    )

                    logger.info(
                        "[OSMOSE:ClaimFirst] Phase 7.5: Classifying tensions..."
                    )
                    classifier = ContradictionClassifier(
                        self.neo4j_driver, batch_size=5
                    )
                    classif_stats = classifier.classify_all(
                        tenant_id=result.tenant_id
                    )
                    if classif_stats.get("total", 0) > 0:
                        by_level = classif_stats.get("by_level", {})
                        logger.info(
                            f"  -> {classif_stats['classified']} tensions classified "
                            f"in {classif_stats['batches']} batches "
                            f"(hard={by_level.get('hard', 0)}, "
                            f"soft={by_level.get('soft', 0)}, "
                            f"unknown={by_level.get('unknown', 0)})"
                        )
                    else:
                        logger.info("  -> no unreviewed tensions")
                except Exception as e:
                    logger.warning(
                        f"[OSMOSE:ClaimFirst] Tension classification failed "
                        f"(non-blocking): {e}"
                    )

        # Phase 8: Persist chunks to Qdrant Layer R
        # ADR: Unite de preuve vs Unite de lecture.
        # Les TypeAwareChunks du cache sont l'unite de lecture :
        # - PDF : chunks Docling + rechunker (target 1500, overlap 200)
        # - PPTX : slides reconstruites via pptx_extractor (deja dans le cache)
        # Fallback → Passages atomiques (legacy)
        type_aware_chunks = cache_result.pass0_result.chunks if cache_result.pass0_result else []

        if self.persist_enabled and (type_aware_chunks or result.passages):
            try:
                logger.info("[OSMOSE:ClaimFirst] Phase 8: Persisting chunks to Qdrant...")

                if type_aware_chunks:
                    qdrant_count = self._persist_type_aware_chunks_to_qdrant(
                        chunks=type_aware_chunks,
                        doc_id=result.doc_id,
                        tenant_id=result.tenant_id,
                        doc_context=result.doc_context,
                    )
                else:
                    # Fallback : ancienne methode si pas de TypeAwareChunks
                    qdrant_count = self._persist_chunks_to_qdrant(
                        passages=result.passages,
                        doc_id=result.doc_id,
                        tenant_id=result.tenant_id,
                        doc_context=result.doc_context,
                    )
                result.qdrant_points_upserted = qdrant_count
                logger.info(f"  -> {qdrant_count} points upserted to Qdrant Layer R")

                # Phase 8b: Bridge claim↔chunk pour ce document
                # Met à jour chunk_ids sur les claims Neo4j (cache rebuildable, INV-BRIDGE)
                try:
                    bridge_count = self._bridge_claims_to_chunks(
                        doc_id=result.doc_id,
                        tenant_id=result.tenant_id,
                    )
                    logger.info(f"  -> {bridge_count} claims bridged to Qdrant chunks")
                except Exception as e:
                    logger.warning(
                        f"[OSMOSE:ClaimFirst] Claim-chunk bridge failed (non-blocking): {e}"
                    )
            except Exception as e:
                logger.warning(
                    f"[OSMOSE:ClaimFirst] Qdrant persistence failed (non-blocking): {e}"
                )

        return result

    # =========================================================================
    # Phase 6.6: QuestionSignature extraction (Level A — regex, zero-cost)
    # =========================================================================

    def _extract_question_signatures(
        self,
        claims: List[Claim],
        doc_id: str,
        tenant_id: str,
    ) -> list:
        """
        Extrait les QuestionSignatures Level A (regex) depuis les claims.

        Zero-cost LLM — patterns déterministes uniquement.
        """
        from knowbase.claimfirst.extractors.question_signature_extractor import (
            extract_question_signatures_level_a,
        )

        try:
            return extract_question_signatures_level_a(claims, doc_id, tenant_id)
        except Exception as e:
            logger.warning(
                f"[OSMOSE:ClaimFirst] QS extraction failed (non-blocking): {e}"
            )
            return []

    # =========================================================================
    # Phase 8: Qdrant Layer R persistence
    # =========================================================================

    def _persist_type_aware_chunks_to_qdrant(
        self,
        chunks,
        doc_id: str,
        tenant_id: str,
        doc_context=None,
    ) -> int:
        """
        Persiste les TypeAwareChunks via le rechunker dans Qdrant Layer R.

        Utilise le rechunker existant (target 1500 chars, overlap 200) pour
        produire des chunks autonomes avec recouvrement. Prefixe chaque chunk
        avec le contexte documentaire (doc_title + section_title).

        ADR: Unite de preuve vs Unite de lecture.
        """
        from knowbase.retrieval.qdrant_layer_r import (
            delete_doc_from_layer_r,
            ensure_layer_r_collection,
            upsert_layer_r,
        )
        from knowbase.retrieval.rechunker import rechunk_for_retrieval
        from knowbase.common.clients.embeddings import get_embedding_manager

        if not chunks:
            return 0

        # Supprimer les anciens points
        try:
            delete_doc_from_layer_r(doc_id, tenant_id)
        except Exception as e:
            logger.debug(f"[OSMOSE:ClaimFirst] Qdrant delete_doc skipped: {e}")

        # Construire le dictionnaire section_id → titre lisible
        # Les SectionInfo sont dans le cache (pass0_result.sections)
        section_titles = {}
        try:
            from knowbase.stratified.pass0.cache_loader import load_pass0_from_cache
            # Les sections sont dans le structural graph du cache
            for chunk in chunks:
                if hasattr(chunk, 'section_id') and chunk.section_id:
                    # Extraire le titre lisible depuis le section_id slug
                    # Format: sec_SLUG_HASH → on prend le SLUG et on le rend lisible
                    sid = chunk.section_id
                    if sid.startswith("sec_"):
                        # Supprimer le prefix "sec_" et le hash final (_6chars)
                        parts = sid[4:].rsplit("_", 1)
                        if len(parts) == 2 and len(parts[1]) == 6:
                            slug = parts[0]
                        else:
                            slug = sid[4:]
                        # Convertir le slug en titre lisible
                        title = slug.replace("_", " ").strip()
                        # Capitaliser les mots significatifs
                        title = " ".join(
                            w.upper() if len(w) <= 3 and w.isalpha() else w.capitalize()
                            for w in title.split()
                        )
                        if title and len(title) > 3:
                            section_titles[sid] = title
        except Exception as e:
            logger.debug(f"[OSMOSE:ClaimFirst] Section title extraction failed: {e}")

        # Rechunker V2 : filtre + consolidation section + decoupe overlap + force-merge
        sub_chunks = rechunk_for_retrieval(
            chunks=chunks,
            tenant_id=tenant_id,
            doc_id=doc_id,
            target_chars=1500,
            overlap_chars=200,
            section_titles=section_titles,
        )

        if not sub_chunks:
            logger.info("[OSMOSE:ClaimFirst] No valid sub-chunks after rechunking")
            return 0

        # Prefixe contextuel deterministe (ADR: metadonnees structurelles = faits documentaires)
        doc_title = ""
        if doc_context:
            doc_title = getattr(doc_context, "primary_subject", "") or ""

        for sc in sub_chunks:
            # Ne pas ajouter de prefixe si le texte en a deja un
            # (le pptx_extractor ajoute son propre prefixe contextuel)
            if sc.text.startswith("[Document:"):
                continue

            prefix_parts = []
            if doc_title:
                prefix_parts.append(f"Document: {doc_title}")
            if sc.section_title:
                prefix_parts.append(f"Section: {sc.section_title}")
            elif sc.section_id:
                prefix_parts.append(f"Section: {sc.section_id}")
            if sc.page_no:
                prefix_parts.append(f"Page {sc.page_no}")

            if prefix_parts:
                prefix = "[" + " | ".join(prefix_parts) + "]\n\n"
                sc.text = prefix + sc.text

        logger.info(
            f"[OSMOSE:ClaimFirst] Rechunked: {len(chunks)} TypeAwareChunks → "
            f"{len(sub_chunks)} SubChunks for Qdrant"
        )

        # Embeddings
        texts = [sc.text for sc in sub_chunks]
        manager = get_embedding_manager()
        embeddings = manager.encode(texts)

        if embeddings is None or len(embeddings) == 0:
            logger.warning("[OSMOSE:ClaimFirst] No embeddings generated")
            return 0

        # Filtrer les zero-vectors et normaliser en listes Python
        import numpy as np
        pairs = []
        for sc, emb in zip(sub_chunks, embeddings):
            if isinstance(emb, np.ndarray):
                emb_list = emb.tolist()
            elif isinstance(emb, list):
                emb_list = emb
            else:
                emb_list = list(emb)
            if any(v != 0.0 for v in emb_list[:10]):
                pairs.append((sc, emb_list))

        if not pairs:
            return 0

        ensure_layer_r_collection()

        # Extraire axis_values du doc_context
        doc_axis_map = {}
        if doc_context:
            af = getattr(doc_context, "applicability_frame", None)
            if af:
                for axis_name, axis_val in [
                    ("release_id", getattr(af, "release_id", None)),
                    ("version", getattr(af, "version", None)),
                ]:
                    if axis_val:
                        doc_axis_map[axis_name] = axis_val

        n = upsert_layer_r(pairs, tenant_id=tenant_id, doc_axis_values=doc_axis_map)
        return n

    def _bridge_claims_to_chunks(self, doc_id: str, tenant_id: str) -> int:
        """
        Phase 8b: Bridge claim↔chunk pour un document.

        Matche les claims Neo4j aux chunks Qdrant du même document via :
        1. Substring match du verbatim_quote
        2. Overlap mot-à-mot claim.text → chunk
        Met à jour chunk_ids sur les claims (cache rebuildable, INV-BRIDGE).
        """
        import re
        import requests as _requests

        def _normalize(text: str) -> str:
            t = text.lower().strip()
            return re.sub(r'\s+', ' ', t)

        # 1. Charger les chunks Qdrant du document
        qdrant_url = os.environ.get("QDRANT_URL", "http://qdrant:6333")
        collection = "knowbase_chunks_v2"
        doc_chunks = []
        offset = None
        while True:
            body = {
                "limit": 500,
                "with_payload": ["chunk_id", "text"],
                "with_vector": False,
                "filter": {"must": [
                    {"key": "doc_id", "match": {"value": doc_id}},
                    {"key": "tenant_id", "match": {"value": tenant_id}},
                ]},
            }
            if offset:
                body["offset"] = offset
            resp = _requests.post(
                f"{qdrant_url}/collections/{collection}/points/scroll",
                json=body, timeout=15,
            )
            data = resp.json().get("result", {})
            for p in data.get("points", []):
                pl = p.get("payload", {})
                if pl.get("text"):
                    doc_chunks.append({
                        "chunk_id": pl.get("chunk_id", str(p.get("id", ""))),
                        "text": pl["text"],
                    })
            offset = data.get("next_page_offset")
            if not offset:
                break

        if not doc_chunks:
            return 0

        # 2. Charger les claims du document depuis Neo4j
        with self.neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid, doc_id: $doc_id})
                RETURN c.claim_id AS claim_id,
                       c.verbatim_quote AS verbatim,
                       c.text AS claim_text
                """,
                tid=tenant_id, doc_id=doc_id,
            )
            claims = [(r["claim_id"], r["verbatim"] or "", r["claim_text"] or "") for r in result]

        if not claims:
            return 0

        # 3. Matcher
        bridge_batch = []
        for claim_id, verbatim, claim_text in claims:
            matched_id = None

            # Niveau 1+2 : substring verbatim
            if verbatim and len(verbatim) >= 20:
                v_norm = _normalize(verbatim)
                for chunk in doc_chunks:
                    if v_norm in _normalize(chunk["text"]):
                        matched_id = chunk["chunk_id"]
                        break
                if not matched_id:
                    v_start = v_norm[:80]
                    if len(v_start) >= 30:
                        for chunk in doc_chunks:
                            if v_start in _normalize(chunk["text"]):
                                matched_id = chunk["chunk_id"]
                                break

            # Niveau 3+4 : overlap mot-à-mot
            if not matched_id:
                text = verbatim or claim_text or ""
                if len(text) >= 15:
                    t_words = set(_normalize(text).split())
                    if len(t_words) >= 3:
                        best_id, best_ov = None, 0.0
                        for chunk in doc_chunks:
                            c_words = set(_normalize(chunk["text"]).split())
                            if not c_words:
                                continue
                            ov = len(t_words & c_words) / len(t_words)
                            if ov > best_ov:
                                best_ov = ov
                                best_id = chunk["chunk_id"]
                        if best_ov >= 0.5:
                            matched_id = best_id

            if matched_id:
                bridge_batch.append({"claim_id": claim_id, "chunk_id": matched_id})

        # 4. Persister chunk_ids dans Neo4j
        if bridge_batch:
            with self.neo4j_driver.session() as session:
                session.run(
                    """
                    UNWIND $batch AS item
                    MATCH (c:Claim {claim_id: item.claim_id})
                    SET c.chunk_ids = [item.chunk_id]
                    """,
                    batch=bridge_batch,
                )

        return len(bridge_batch)

    def _persist_chunks_to_qdrant(
        self,
        passages: List[Passage],
        doc_id: str,
        tenant_id: str,
        doc_context: Optional[Any] = None,
    ) -> int:
        """
        LEGACY: Persiste les Passages ClaimFirst comme chunks vectoriels dans Qdrant Layer R.

        Chaque Passage est converti en SubChunk (sub_index=0, atomique)
        puis encodé et upserté de manière idempotente (UUID5).

        Args:
            passages: Passages du document
            doc_id: Document ID
            tenant_id: Tenant ID

        Returns:
            Nombre de points upsertés
        """
        from knowbase.retrieval.qdrant_layer_r import (
            delete_doc_from_layer_r,
            ensure_layer_r_collection,
            upsert_layer_r,
        )
        from knowbase.retrieval.rechunker import SubChunk
        from knowbase.common.clients.embeddings import get_embedding_manager

        # Filtrer les passages vides ou trop courts
        MIN_CHARS = 20
        valid_passages = [p for p in passages if p.text and len(p.text.strip()) >= MIN_CHARS]
        if not valid_passages:
            logger.info(f"[OSMOSE:ClaimFirst] No valid passages to persist to Qdrant")
            return 0

        # Supprimer les anciens points de ce document (idempotence sur re-import)
        try:
            delete_doc_from_layer_r(doc_id, tenant_id)
        except Exception as e:
            logger.debug(f"[OSMOSE:ClaimFirst] Qdrant delete_doc skipped: {e}")

        # Mapping item_type → kind pour Qdrant
        KIND_MAP = {
            "paragraph": "NARRATIVE_TEXT",
            "heading": "NARRATIVE_TEXT",
            "table": "TABLE",
            "figure": "FIGURE",
            "code": "CODE",
            "list_item": "NARRATIVE_TEXT",
        }

        # Convertir Passages → SubChunks
        sub_chunks = []
        for p in valid_passages:
            sc = SubChunk(
                chunk_id=p.passage_id,
                sub_index=0,
                text=p.text,
                parent_chunk_id=p.passage_id,
                section_id=p.section_id,
                doc_id=p.doc_id,
                tenant_id=p.tenant_id,
                kind=KIND_MAP.get(p.item_type, "NARRATIVE_TEXT"),
                page_no=p.page_no or 0,
                page_span_min=p.page_no,
                page_span_max=p.page_no,
                item_ids=p.unit_ids if p.unit_ids else [],
                text_origin=f"claimfirst:{p.passage_id}",
            )
            sub_chunks.append(sc)

        logger.debug(
            f"[OSMOSE:ClaimFirst] Encoding {len(sub_chunks)} passages for Qdrant..."
        )

        # Générer les embeddings
        texts = [sc.text for sc in sub_chunks]
        manager = get_embedding_manager()
        embeddings = manager.encode(texts)

        # Filtrer les zero vectors (textes trop longs skippés par TEI)
        pairs = []
        skipped = 0
        for sc, emb in zip(sub_chunks, embeddings):
            if np.any(emb != 0):
                pairs.append((sc, emb))
            else:
                skipped += 1
        if skipped > 0:
            logger.warning(
                f"[OSMOSE:ClaimFirst] Filtered {skipped} zero-vector embeddings "
                f"(TEI 413 skips) — {len(pairs)} chunks will be indexed"
            )

        ensure_layer_r_collection()

        # Extraire axis_values du doc_context pour enrichir les chunks Qdrant (B.1)
        doc_axis_map: dict[str, str] | None = None
        if doc_context and hasattr(doc_context, 'axis_values') and doc_context.axis_values:
            doc_axis_map = {}
            for k, v in doc_context.axis_values.items():
                if isinstance(v, dict) and v.get("scalar_value"):
                    doc_axis_map[k] = v["scalar_value"]
            if not doc_axis_map:
                doc_axis_map = None

        n = upsert_layer_r(pairs, tenant_id=tenant_id, doc_axis_values=doc_axis_map)

        return n

    def _deduplicate_claims(
        self,
        claims: List[Claim],
    ) -> Tuple[List[Claim], Dict[str, int]]:
        """
        Déduplication déterministe intra-document.

        Niveau 1: Texte exact (même text normalisé → garder meilleure confidence)
        Niveau 2: Triplet S/P/O (même structured_form → garder meilleure confidence)

        Calcule content_fingerprint sur chaque claim survivante.

        Args:
            claims: Claims extraites (toutes du même document)

        Returns:
            Tuple[claims dédup, stats dict]
        """
        if not claims:
            return claims, {"kept": 0, "removed_text": 0, "removed_spo": 0}

        initial_count = len(claims)

        # Niveau 1: Dédup texte exact
        best_by_text: Dict[str, Claim] = {}
        for claim in claims:
            key = claim.text.lower().strip()
            existing = best_by_text.get(key)
            if existing is None or claim.confidence > existing.confidence:
                best_by_text[key] = claim

        after_text = list(best_by_text.values())
        removed_text = initial_count - len(after_text)

        # Niveau 2: Dédup triplet S/P/O
        best_by_spo: Dict[Tuple[str, str, str], Claim] = {}
        no_spo: List[Claim] = []

        for claim in after_text:
            sf = claim.structured_form
            if sf and sf.get("subject") and sf.get("predicate") and sf.get("object"):
                key = (
                    str(sf["subject"]).lower().strip(),
                    str(sf["predicate"]).lower().strip(),
                    str(sf["object"]).lower().strip(),
                )
                existing = best_by_spo.get(key)
                if existing is None or claim.confidence > existing.confidence:
                    best_by_spo[key] = claim
            else:
                no_spo.append(claim)

        after_spo = list(best_by_spo.values()) + no_spo
        removed_spo = len(after_text) - len(after_spo)

        # Calculer content_fingerprint sur les survivantes
        for claim in after_spo:
            claim.content_fingerprint = claim.compute_content_fingerprint()

        stats = {
            "kept": len(after_spo),
            "removed_text": removed_text,
            "removed_spo": removed_spo,
        }

        return after_spo, stats

    def _filter_claims_quality(
        self,
        claims: List[Claim],
    ) -> Tuple[List[Claim], Dict[str, int]]:
        """Délègue au module quality_filters (Phase 1.6)."""
        return filter_claims_quality(claims)

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

    def _get_domain_context_block(self, tenant_id: str) -> str:
        """
        Charge le bloc Domain Context pour injection dans le prompt V2.

        Retourne une chaîne vide si aucun contexte n'est configuré.
        """
        try:
            from knowbase.ontology.domain_context_injector import get_domain_context_injector
            injector = get_domain_context_injector()
            # On injecte sur un prompt vide pour récupérer uniquement le bloc contexte
            result = injector.inject_context("", tenant_id)
            if result.strip():
                return result.strip()
        except Exception as e:
            logger.warning(
                f"[OSMOSE:ClaimFirst] Domain context not available for tenant "
                f"'{tenant_id}': {e} — version disambiguation will be degraded"
            )
        return ""

    def _get_axis_policy(self, tenant_id: str) -> dict:
        """
        Charge axis_policy depuis le DomainContext.
        Résultat cacheable par tenant pour la durée d'un run d'import.
        """
        cache_key = f"_axis_policy_{tenant_id}"
        cached = getattr(self, cache_key, None)
        if cached is not None:
            return cached

        policy: dict = {}
        try:
            from knowbase.ontology.domain_context_store import get_domain_context_store
            dc_profile = get_domain_context_store().get_profile(tenant_id)
            if dc_profile and dc_profile.axis_policy:
                policy = json.loads(dc_profile.axis_policy)
        except Exception:
            pass

        setattr(self, cache_key, policy)
        return policy

    def _build_applicability_frame(
        self,
        doc_id: str,
        tenant_id: str,
        passages: List[Passage],
        doc_context: DocumentContext,
        doc_title: Optional[str] = None,
        resolver_axis_values: Optional[List] = None,
    ) -> Tuple[Optional[ApplicabilityFrame], List[ApplicabilityAxis]]:
        """
        Construit l'ApplicabilityFrame via le pipeline evidence-locked A→B→C→D.

        Remplace l'ancien _detect_document_axes.

        Args:
            doc_id: Document ID
            tenant_id: Tenant ID
            passages: Passages du document
            doc_context: Contexte documentaire
            doc_title: Titre du document
            resolver_axis_values: AxisValueOutput du SubjectResolver (priors)

        Returns:
            Tuple[Optional[ApplicabilityFrame], List[ApplicabilityAxis]]
        """
        try:
            # Layer A: Segmenter les passages en EvidenceUnits
            segmenter = EvidenceUnitSegmenter()
            units = segmenter.segment(passages)

            if not units:
                logger.info("[OSMOSE:ClaimFirst] No evidence units produced, skipping frame")
                return None, []

            # Layer B: Scan déterministe pour markers et value candidates
            miner = CandidateMiner()
            profile = miner.mine(
                units=units,
                doc_id=doc_id,
                title=doc_title,
                primary_subject=doc_context.primary_subject,
            )

            # Compute canonical values using DomainContext policy
            axis_policy = self._get_axis_policy(tenant_id)
            strip_prefixes = axis_policy.get("strip_prefixes", [])
            canonicalization_enabled = axis_policy.get("canonicalization_enabled", True)

            if strip_prefixes and canonicalization_enabled:
                from knowbase.claimfirst.applicability.models import compute_canonical_value
                for vc in profile.value_candidates:
                    vc.canonical_value = compute_canonical_value(
                        vc.raw_value, vc.value_type, strip_prefixes
                    )

            # Layer C: Construire le frame (LLM evidence-locked ou fallback déterministe)
            builder = FrameBuilder(
                llm_client=self.llm_client,
                use_llm=True,
            )

            # Charger le Domain Context optionnel
            domain_context_prompt = self._get_domain_context_block(tenant_id)

            frame = builder.build(
                profile=profile,
                units=units,
                domain_context_prompt=domain_context_prompt,
                resolver_axis_values=resolver_axis_values,
            )

            # Layer D: Valider le frame
            validator = FrameValidationPipeline(tenant_id=tenant_id)
            frame = validator.validate(frame, units, profile)

            # Adapter: Frame → ApplicabilityAxis[] (rétrocompat)
            adapter = FrameAdapter()

            # Mettre à jour le DocumentContext
            adapter.update_document_context(frame, doc_context, profile=profile)

            # Convertir en axes pour compatibilité
            detected_axes = adapter.frame_to_axes(
                frame=frame,
                tenant_id=tenant_id,
                doc_id=doc_id,
                profile=profile,
            )

            # Mettre à jour le cache d'axes
            _order_inferrer = AxisOrderInferrer()
            for axis in detected_axes:
                existing = next(
                    (ax for ax in self._applicability_axes if ax.axis_id == axis.axis_id),
                    None
                )
                if existing:
                    changed = False
                    for v in axis.known_values:
                        changed |= existing.add_value(v, doc_id)

                    # Re-inférer l'ordre après merge si nouvelles valeurs
                    if changed and len(existing.known_values) >= 2:
                        order_result = _order_inferrer.infer_order(
                            axis_key=existing.axis_key,
                            values=list(existing.known_values),
                        )
                        if order_result.is_orderable:
                            existing.is_orderable = True
                            existing.order_type = order_result.order_type
                            existing.ordering_confidence = order_result.confidence
                            existing.value_order = order_result.inferred_order
                            logger.info(
                                f"[OSMOSE:ClaimFirst] Axis {existing.axis_key} "
                                f"re-inferred post-merge: {order_result.inferred_order} "
                                f"({order_result.confidence.value})"
                            )
                        # Ne pas écraser un axe déjà orderable par un résultat négatif
                else:
                    self._applicability_axes.append(axis)

            # Propager les axes re-inférés dans detected_axes pour persistence
            for i, axis in enumerate(detected_axes):
                cached = next(
                    (ax for ax in self._applicability_axes if ax.axis_id == axis.axis_id),
                    None
                )
                if cached and cached.is_orderable and not axis.is_orderable:
                    detected_axes[i] = cached

            return frame, detected_axes

        except Exception as e:
            logger.error(
                f"[OSMOSE:ClaimFirst] ApplicabilityFrame pipeline failed: {e}",
                exc_info=True,
            )
            return None, []

    def _detect_document_axes(
        self,
        doc_id: str,
        tenant_id: str,
        passages: List[Passage],
        doc_context: DocumentContext,
        doc_title: Optional[str] = None,
    ) -> List[ApplicabilityAxis]:
        """
        Détecte les axes d'applicabilité pour un document.

        Pattern "Extract-then-Validate":
        1. Bootstrap patterns détectent des candidats
        2. LLM valide/choisit la valeur appropriée (INV-25 domain-agnostic)

        INV-12, INV-14, INV-25, INV-26.

        Args:
            doc_id: Document ID
            tenant_id: Tenant ID
            passages: Passages du document
            doc_context: Contexte documentaire
            doc_title: Titre du document

        Returns:
            Liste des ApplicabilityAxis détectés
        """
        from knowbase.claimfirst.axes.axis_order_inferrer import AxisOrderInferrer

        # 1. Détecter les observations d'axes (candidats)
        observations = self.axis_detector.detect(
            doc_id=doc_id,
            tenant_id=tenant_id,
            passages=passages,
            doc_title=doc_title,
        )

        if not observations:
            return []

        logger.debug(
            f"[OSMOSE:ClaimFirst] Axis candidates before validation: "
            f"{[(o.axis_key, o.values_extracted) for o in observations]}"
        )

        # 2. Valider via LLM (Extract-then-Validate pattern)
        validated_observations = self.axis_validator.validate(
            observations=observations,
            doc_title=doc_title,
            passages=passages,
        )

        logger.debug(
            f"[OSMOSE:ClaimFirst] Axis values after validation: "
            f"{[(o.axis_key, o.values_extracted) for o in validated_observations]}"
        )

        if not validated_observations:
            logger.info(
                f"[OSMOSE:ClaimFirst] All axis candidates rejected by LLM validation"
            )
            return []

        # 3. Créer les axes depuis les observations validées
        order_inferrer = AxisOrderInferrer()
        detected_axes = self.axis_detector.create_axes_from_observations(
            observations=validated_observations,
            tenant_id=tenant_id,
            doc_id=doc_id,
            order_inferrer=order_inferrer,
        )

        # 4. Mettre à jour le doc_context avec les valeurs d'axes validées
        for obs in validated_observations:
            if obs.values_extracted and obs.evidence_spans:
                evidence = obs.evidence_spans[0]
                doc_context.axis_values[obs.axis_key] = {
                    "value_type": "scalar",
                    "scalar_value": obs.values_extracted[0],
                    "evidence_passage_id": evidence.passage_id,
                    "evidence_snippet_ref": evidence.snippet_ref,
                    "reliability": obs.reliability,
                }
                if obs.axis_key not in doc_context.applicable_axes:
                    doc_context.applicable_axes.append(obs.axis_key)

        # 5. Mettre à jour le cache d'axes
        for axis in detected_axes:
            existing = next(
                (ax for ax in self._applicability_axes if ax.axis_id == axis.axis_id),
                None
            )
            if existing:
                # Fusionner les valeurs
                for v in axis.known_values:
                    existing.add_value(v, doc_id)
            else:
                self._applicability_axes.append(axis)

        return detected_axes

    def _extract_document_context(
        self,
        doc_id: str,
        tenant_id: str,
        passages: List[Passage],
        doc_title: Optional[str] = None,
    ) -> Tuple[DocumentContext, List[SubjectAnchor]]:
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
            Tuple[DocumentContext, List[SubjectAnchor]]:
                - DocumentContext configuré avec sujets résolus
                - Liste des SubjectAnchors créés/mis à jour pour ce document
        """
        # 1. Extraire le contexte (sujets bruts, qualificateurs)
        context = self.context_extractor.extract(
            doc_id=doc_id,
            tenant_id=tenant_id,
            passages=passages,
            doc_title=doc_title,
        )

        # 2. Résoudre les sujets vers SubjectAnchors (INV-9)
        new_anchors: List[SubjectAnchor] = []

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

                    # Collecter les anchors impliqués (nouveaux ou mis à jour)
                    new_anchors.append(result.anchor)

                    # Mettre à jour le cache si nouveau
                    if result.match_type == "new":
                        self._subject_anchors.append(result.anchor)

        return context, new_anchors

    def _validate_new_subjects_llm(
        self,
        new_subjects: List[SubjectAnchor],
        all_anchors: List[SubjectAnchor],
        doc_context: DocumentContext,
        doc_title: Optional[str] = None,
        batch_size: int = 30,
    ) -> List[SubjectAnchor]:
        """
        Valide les nouveaux SubjectAnchors via LLM (3 classes).

        - NOISE → revoke (retiré du cache + doc_context)
        - UNCERTAIN → conservé, tagué pour audit
        - VALID → conservé

        Fail-open : si erreur LLM/parsing → ne rien révoquer + log erreur.
        """
        if not new_subjects:
            return all_anchors

        for i in range(0, len(new_subjects), batch_size):
            batch = new_subjects[i:i + batch_size]
            verdicts = self._llm_validate_subject_batch(
                batch, doc_title=doc_title,
                primary_subject=doc_context.primary_subject,
            )
            # Fail-open : si None → on garde tout
            if verdicts is None:
                continue

            for j, anchor in enumerate(batch):
                idx = j + 1  # index 1-based comme envoyé au LLM
                entry = verdicts.get(idx)
                if not entry:
                    continue  # Index manquant → fail-open, on garde

                verdict = entry.get("verdict", "VALID")
                reason = entry.get("reason", "")

                if verdict == "NOISE":
                    # Révoquer du cache et du doc_context
                    if anchor in self._subject_anchors:
                        self._subject_anchors.remove(anchor)
                    doc_context.remove_subject(anchor.subject_id)
                    all_anchors = [a for a in all_anchors if a.subject_id != anchor.subject_id]
                    logger.info(
                        f"[OSMOSE:ClaimFirst] Subject revoked by LLM: "
                        f"'{anchor.canonical_name}' (reason={reason})"
                    )
                elif verdict == "UNCERTAIN":
                    logger.info(
                        f"[OSMOSE:ClaimFirst] Subject uncertain (kept): "
                        f"'{anchor.canonical_name}' (reason={reason})"
                    )
                # VALID → rien à faire

        return all_anchors

    # ------------------------------------------------------------------
    # Phase 2.8 — Dériver SubjectAnchors depuis entités canonicalisées
    # ------------------------------------------------------------------

    def _derive_subjects_from_entities(
        self,
        entities: List[Entity],
        claim_entity_map: Dict[str, List[str]],
        claims: List[Claim],
        doc_context: DocumentContext,
        doc_id: str,
        tenant_id: str,
        doc_title: Optional[str] = None,
    ) -> Tuple[List[SubjectAnchor], DocumentContext]:
        """
        Phase 2.8 : dérive des SubjectAnchors depuis les entités canonicalisées.

        Étapes :
          A. Candidats coverage-based (seuils numériques, aucun filtre type/nom)
          B. Evidence pack diversifié (3 snippets par candidat)
          C. LLM arbiter "documentary subjectness" (1 appel batch)
          D. Résolution via SubjectResolver.resolve_batch()
          E. Mise à jour doc_context (conserve primary, remplace secondaires)

        Returns:
            (entity_anchors, doc_context) — liste vide si fallback Phase 0.5
        """
        from collections import Counter, defaultdict

        MIN_ENTITY_CLAIMS = 8
        MIN_ENTITY_COVERAGE_SMALL = 0.03  # 3% pour petits docs
        MIN_ENTITY_COVERAGE_FLOOR = 0.005  # 0.5% plancher pour gros docs
        MAX_CANDIDATES_FOR_LLM = 12
        MAX_FINAL_SUBJECTS = 5

        # --- Étape A : Candidats coverage-based ---
        entity_claim_counts: Counter = Counter()
        for claim_id, entity_ids in claim_entity_map.items():
            for eid in entity_ids:
                entity_claim_counts[eid] += 1

        entity_by_id = {e.entity_id: e for e in entities}

        total_claims = len(claims)
        # Seuil adaptatif : 3% pour petits docs, dégressif pour gros docs
        # garantit que le seuil ne descend pas en-dessous de MIN_ENTITY_CLAIMS
        if total_claims > 0:
            min_coverage = max(
                MIN_ENTITY_CLAIMS / total_claims,
                MIN_ENTITY_COVERAGE_FLOOR,
            )
        else:
            min_coverage = MIN_ENTITY_COVERAGE_SMALL
        logger.debug(
            f"  Phase 2.8: adaptive coverage threshold = {min_coverage:.3f} "
            f"({min_coverage * 100:.1f}%) for {total_claims} claims"
        )

        candidates = []
        for entity_id, claim_count in entity_claim_counts.items():
            entity = entity_by_id.get(entity_id)
            if not entity:
                continue
            coverage = claim_count / total_claims if total_claims > 0 else 0
            if claim_count >= MIN_ENTITY_CLAIMS and coverage >= min_coverage:
                candidates.append((entity, claim_count, coverage))

        candidates.sort(key=lambda x: x[1], reverse=True)

        if logger.isEnabledFor(logging.DEBUG) and candidates:
            top_display = candidates[:8]
            logger.debug(
                f"  Phase 2.8: top candidates: "
                + ", ".join(
                    f"'{e.name}'({cnt}, {cov:.1%})"
                    for e, cnt, cov in top_display
                )
            )

        candidates = candidates[:MAX_CANDIDATES_FOR_LLM]

        if not candidates:
            logger.info("  → No entity candidates above thresholds")
            return [], doc_context

        # --- Étape B : Evidence pack diversifié ---
        entity_to_claims: Dict[str, List[str]] = defaultdict(list)
        for claim_id, entity_ids in claim_entity_map.items():
            for eid in entity_ids:
                entity_to_claims[eid].append(claim_id)

        claim_by_id = {c.claim_id: c for c in claims}

        def _pick_diverse_snippets(claim_ids: List[str], n: int = 3) -> List[str]:
            valid = [cid for cid in claim_ids if cid in claim_by_id]
            if len(valid) <= n:
                return [claim_by_id[cid].text for cid in valid]
            step = max(1, len(valid) // n)
            picked = [valid[i * step] for i in range(n)]
            return [claim_by_id[cid].text for cid in picked]

        candidates_json = []
        for entity, count, coverage in candidates:
            snippets = _pick_diverse_snippets(entity_to_claims[entity.entity_id])
            candidates_json.append({
                "index": len(candidates_json) + 1,
                "entity_name": entity.name,
                "entity_type": entity.entity_type.value if hasattr(entity.entity_type, 'value') else str(entity.entity_type),
                "claim_count": count,
                "coverage_pct": round(coverage * 100, 1),
                "evidence_snippets": snippets,
            })

        logger.info(f"  → {len(candidates_json)} entity candidates for LLM subjectness check")

        # --- Étape C : LLM arbiter "documentary subjectness" ---
        try:
            from knowbase.common.llm_router import get_llm_router, TaskType

            candidates_text = json.dumps(candidates_json, indent=2, ensure_ascii=False)
            title_display = doc_title or doc_id

            prompt = f"""You are classifying entity candidates as document subjects.
A "subject" is a meaningful topic that this document is ABOUT — a useful pivot for navigation and retrieval.

Document: "{title_display}"

For each candidate below, evidence snippets from the document are provided.
Judge ONLY based on the evidence — is this entity a central topic of the document, or just a mentioned term?

Classify each as:
- SUBJECT: a central topic of this document, useful for navigation
- TOO_GENERIC: too broad to serve as a navigation pivot. Includes: common nouns ("system", "data", "process", "role", "user"), the corpus owner or publisher name if it appears in every document, and umbrella terms so broad they match most documents in a collection
- NOISE: not a meaningful topic

Candidates:
{candidates_text}

Return JSON:
{{"decisions": [{{"index": 1, "verdict": "SUBJECT", "reason": "..."}}]}}"""

            router = get_llm_router()
            response = router.complete(
                task_type=TaskType.METADATA_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1500,
                response_format={"type": "json_object"},
            ).strip()

            data = json.loads(response)
            decisions = data.get("decisions", [])

        except Exception as e:
            logger.warning(
                f"[OSMOSE:ClaimFirst] Phase 2.8 LLM failed (fail-open): {e}"
            )
            return [], doc_context

        # --- Étape D : Résolution via SubjectResolver ---
        valid_names = []
        for d in decisions:
            idx = d.get("index")
            verdict = d.get("verdict", "")
            if isinstance(idx, int) and 1 <= idx <= len(candidates_json) and verdict == "SUBJECT":
                valid_names.append(candidates_json[idx - 1]["entity_name"])
        valid_names = valid_names[:MAX_FINAL_SUBJECTS]

        if not valid_names:
            logger.info("  → LLM classified no entities as SUBJECT")
            return [], doc_context

        logger.info(f"  → LLM selected {len(valid_names)} subjects: {valid_names}")

        # Phase 2.8 subjects sont triple-validés (coverage + LLM + canon)
        # → bypass is_valid_subject_name() qui rejetterait les noms courts
        results = self.subject_resolver.resolve_batch(
            raw_subjects=valid_names,
            existing_anchors=self._subject_anchors,
            doc_id=doc_id,
            skip_name_validation=True,
        )

        entity_anchors = []
        for result in results:
            if result.anchor:
                entity_anchors.append(result.anchor)
                if doc_id not in result.anchor.source_doc_ids:
                    result.anchor.source_doc_ids.append(doc_id)
                if result.match_type == "new" and result.anchor not in self._subject_anchors:
                    self._subject_anchors.append(result.anchor)

        # --- Étape E : Mise à jour doc_context ---
        if entity_anchors:
            # Vider les sujets secondaires de Phase 0.5
            for old_sid in list(doc_context.subject_ids):
                doc_context.remove_subject(old_sid)

            # Ajouter les sujets dérivés des entités
            for anchor in entity_anchors:
                doc_context.add_subject(
                    anchor.subject_id, ResolutionStatus.RESOLVED, 0.95
                )

            return entity_anchors, doc_context
        else:
            return [], doc_context

    def _llm_validate_subject_batch(
        self,
        anchors: List[SubjectAnchor],
        doc_title: Optional[str] = None,
        primary_subject: Optional[str] = None,
    ) -> Optional[Dict[int, Dict]]:
        """
        1 appel LLM pour classifier N sujets en VALID/NOISE/UNCERTAIN.

        Returns:
            dict {index: {"verdict": "VALID|NOISE|UNCERTAIN", "reason": str}}
            ou None si erreur (fail-open)
        """
        from knowbase.common.llm_router import get_llm_router, TaskType

        subjects_text = "\n".join(
            f"{i+1}. \"{a.canonical_name}\""
            for i, a in enumerate(anchors)
        )

        ctx_lines = []
        if doc_title:
            ctx_lines.append(f"Document title: {doc_title}")
        if primary_subject:
            ctx_lines.append(f"Primary subject: {primary_subject}")
        doc_ctx = "\n".join(ctx_lines) if ctx_lines else "No document context available."

        prompt = f"""Classify each candidate subject name as VALID, NOISE, or UNCERTAIN.

VALID = legitimate document subject (product name, technology, standard, concept, methodology, specification)
NOISE = clearly NOT a subject (sentence fragment, action phrase, generic description, vague term)
UNCERTAIN = ambiguous, could be either

Document context:
{doc_ctx}

Candidate subjects:
{subjects_text}

Return JSON: {{"results": [{{"index": 1, "verdict": "VALID", "reason": "product name"}}]}}"""

        router = get_llm_router()
        try:
            response = router.complete(
                task_type=TaskType.METADATA_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
                response_format={"type": "json_object"},
            ).strip()

            data = json.loads(response)
            results = data.get("results", [])

            verdict_map: Dict[int, Dict] = {}
            for entry in results:
                idx = entry.get("index")
                if isinstance(idx, int) and 1 <= idx <= len(anchors):
                    verdict_map[idx] = {
                        "verdict": entry.get("verdict", "VALID"),
                        "reason": entry.get("reason", ""),
                    }

            return verdict_map

        except Exception as e:
            logger.warning(
                f"[OSMOSE:ClaimFirst] Subject validation LLM failed (fail-open): {e}"
            )
            return None

    def _resolve_comparable_subject(
        self,
        doc_id: str,
        tenant_id: str,
        passages: List[Passage],
        doc_context: DocumentContext,
        doc_title: Optional[str] = None,
    ) -> Tuple[Optional[ComparableSubject], List]:
        """
        Résout le ComparableSubject via SubjectResolverV2.

        INV-25: Domain-Agnostic - aucun vocabulaire IT/SAP hardcodé.

        Le resolver v2 classifie les candidats extraits en:
        - COMPARABLE_SUBJECT: sujet stable comparable entre documents
        - AXIS_VALUE: valeur discriminante (temporal, geographic, revision, etc.)
        - DOC_TYPE: type/genre documentaire
        - NOISE: bruit à ignorer

        Args:
            doc_id: Document ID
            tenant_id: Tenant ID
            passages: Passages du document
            doc_context: Contexte documentaire déjà extrait
            doc_title: Titre du document

        Returns:
            Tuple[ComparableSubject ou None, List[AxisValueOutput]]
        """
        # 1. Préparer les candidats depuis les sources disponibles
        candidates = self._extract_resolver_candidates(
            doc_context=doc_context,
            passages=passages,
            doc_title=doc_title,
        )

        if not candidates:
            logger.debug("[OSMOSE:ClaimFirst] No candidates for subject resolution")
            return None, []

        # 2. Préparer les snippets sources pour le prompt
        header_snippets = self._extract_header_snippets(passages, max_snippets=5)
        cover_snippets = self._extract_cover_snippets(passages, max_snippets=3)
        global_view_excerpt = self._extract_global_view_excerpt(passages, max_chars=1200)

        # 3. Appeler SubjectResolverV2
        resolver_output, comparable_subject = self.subject_resolver_v2.resolve(
            candidates=candidates,
            filename=doc_id,  # doc_id sert de filename si pas de métadonnée explicite
            title=doc_title or "",
            header_snippets=header_snippets,
            cover_snippets=cover_snippets,
            global_view_excerpt=global_view_excerpt,
        )

        # 4. Traiter le résultat
        axis_values = []
        if resolver_output and not resolver_output.abstain.must_abstain:
            # Récupérer les axis_values pour propagation au FrameBuilder
            if resolver_output.axis_values:
                axis_values = resolver_output.axis_values
                logger.debug(
                    f"[OSMOSE:ClaimFirst] SubjectResolverV2 detected axis_values: "
                    f"{[(av.value_raw, av.discriminating_role.value) for av in axis_values]}"
                )

            # Log le doc_type si détecté
            if resolver_output.doc_type and resolver_output.doc_type.label != "unknown":
                logger.debug(
                    f"[OSMOSE:ClaimFirst] SubjectResolverV2 detected doc_type: "
                    f"'{resolver_output.doc_type.label}'"
                )
                # Enrichir le doc_context avec le doc_type si pas déjà défini
                if not doc_context.document_type:
                    doc_context.document_type = resolver_output.doc_type.label

        return comparable_subject, axis_values

    def _enrich_title_from_passages(
        self,
        doc_title: Optional[str],
        passages: List[Passage],
    ) -> Optional[str]:
        """
        Enrichit le titre du document avec l'année/version trouvée dans les premiers passages.

        Le titre issu du cache est souvent tronqué (ex: "SAP S/4HANA Security Guide").
        Les premiers passages contiennent fréquemment le titre complet avec l'année
        (ex: "Security Guide for SAP S/4HANA 2023").

        Stratégie:
        1. Chercher dans les 5 premiers passages un texte qui contient le doc_title
           (ou ses mots-clés) PLUS un identifiant année/version.
        2. Si trouvé, retourner ce titre enrichi.
        3. Sinon, retourner le doc_title original.

        Args:
            doc_title: Titre original (peut être None ou tronqué)
            passages: Passages du document (triés par reading_order)

        Returns:
            Titre enrichi ou titre original
        """
        if not doc_title:
            return doc_title

        import re as _re

        # Normaliser le titre pour la recherche (minuscule, sans ponctuation superflue)
        title_lower = doc_title.lower().strip()

        # Extraire les mots-clés significatifs du titre (>= 3 chars, pas des stopwords)
        stopwords = {"for", "the", "and", "of", "in", "to", "a", "an", "on", "by", "with"}
        title_keywords = [
            w for w in _re.findall(r"[a-zA-Z0-9/]+", title_lower)
            if len(w) >= 3 and w not in stopwords
        ]

        if not title_keywords:
            return doc_title

        # Pattern pour détecter année (4 chiffres 19xx/20xx) ou version (vX.Y, X.Y.Z)
        year_version_pattern = _re.compile(
            r"""
            (?:                         # Année
                \b((?:19|20)\d{2})\b
            )
            |
            (?:                         # Version explicite (v2.0, Version 3.1)
                (?:v|version\s*)(\d+(?:\.\d+)+)
            )
            |
            (?:                         # Identifiant numérique 4 chiffres (ex: 1809, 2021)
                \b(\d{4})\b
            )
            """,
            _re.IGNORECASE | _re.VERBOSE,
        )

        # Vérifier si le titre contient déjà une année/version
        if year_version_pattern.search(doc_title):
            return doc_title  # Déjà enrichi, pas besoin de chercher

        # Chercher dans les premiers passages un texte contenant le titre + année/version
        sorted_passages = sorted(passages, key=lambda p: p.reading_order_index)

        best_match: Optional[str] = None
        best_score = 0

        for passage in sorted_passages[:8]:  # Premiers 8 passages (zone cover/intro)
            text = (passage.text or "").strip()
            if not text or len(text) < 10 or len(text) > 500:
                continue

            text_lower = text.lower()

            # Compter combien de mots-clés du titre sont présents dans ce passage
            matched_keywords = sum(1 for kw in title_keywords if kw in text_lower)
            keyword_ratio = matched_keywords / len(title_keywords) if title_keywords else 0

            # On exige au moins 60% des mots-clés du titre
            if keyword_ratio < 0.6:
                continue

            # Chercher une année/version dans ce passage
            yv_match = year_version_pattern.search(text)
            if not yv_match:
                continue

            # Score = ratio de mots-clés matchés (préférer le match le plus complet)
            score = keyword_ratio

            if score > best_score:
                best_score = score
                # Utiliser le texte du passage comme titre enrichi
                # Nettoyer: prendre la ligne la plus pertinente si multi-ligne
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                for line in lines:
                    line_lower = line.lower()
                    line_kw_count = sum(1 for kw in title_keywords if kw in line_lower)
                    if line_kw_count >= len(title_keywords) * 0.6 and year_version_pattern.search(line):
                        best_match = line
                        break
                else:
                    # Pas de ligne unique contenant tout — utiliser le texte complet tronqué
                    best_match = text[:300]

        if best_match:
            return best_match

        return doc_title

    def _extract_resolver_candidates(
        self,
        doc_context: DocumentContext,
        passages: List[Passage],
        doc_title: Optional[str] = None,
    ) -> List[str]:
        """
        Extrait les candidats pour SubjectResolverV2.

        Sources:
        - primary_subject du doc_context
        - raw_subjects du doc_context
        - qualifiers du doc_context
        - Titre du document (tokenisé)
        - En-têtes des premiers passages

        Args:
            doc_context: Contexte documentaire
            passages: Passages du document
            doc_title: Titre du document

        Returns:
            Liste de candidats uniques
        """
        candidates = set()

        # 1. Primary subject (si présent)
        if doc_context.primary_subject:
            candidates.add(doc_context.primary_subject)

        # 2. Raw subjects (topics secondaires)
        for subject in doc_context.raw_subjects:
            if subject:
                candidates.add(subject)

        # 3. Qualifiers (dict: key -> value)
        for key, value in doc_context.qualifiers.items():
            if value:
                candidates.add(str(value))
            # La clé aussi peut être informative (ex: "version")
            if key and key not in ("type", "status"):
                candidates.add(str(key))

        # 4. Titre du document (segments significatifs)
        if doc_title:
            # Ajouter le titre complet
            candidates.add(doc_title)
            # Extraire segments entre délimiteurs courants
            import re
            # Délimiteurs plus restrictifs pour éviter de couper "S/4HANA"
            segments = re.split(r'[-–—|:]', doc_title)
            for seg in segments:
                seg = seg.strip()
                if seg and len(seg) >= 5:  # Min 5 chars pour éviter fragments
                    candidates.add(seg)

        # 5. Titres de sections des premiers passages
        for passage in passages[:10]:  # Premiers 10 passages
            if passage.section_title:
                candidates.add(passage.section_title)

        # 6. Texte des premiers passages (cover area du document)
        # Les premiers passages contiennent souvent le titre complet, la version,
        # la date — des informations critiques pour le resolver.
        for passage in passages[:8]:
            text = (passage.text or "").strip()
            if text and 5 <= len(text) <= 200:
                candidates.add(text)

        # Nettoyer et filtrer
        cleaned = []
        for c in candidates:
            c = c.strip()
            if c and len(c) >= 2 and len(c) <= 200:
                cleaned.append(c)

        # Dédupliquer en préservant l'ordre
        seen = set()
        result = []
        for c in cleaned:
            c_lower = c.lower()
            if c_lower not in seen:
                seen.add(c_lower)
                result.append(c)

        return result[:20]  # Max 20 candidats

    def _extract_header_snippets(
        self,
        passages: List[Passage],
        max_snippets: int = 5,
    ) -> List[str]:
        """Extrait les snippets d'en-têtes (titres de sections) depuis les passages."""
        snippets = []
        for passage in passages[:20]:
            if passage.section_title and passage.section_title not in snippets:
                snippets.append(passage.section_title)
                if len(snippets) >= max_snippets:
                    break
        return snippets

    def _extract_cover_snippets(
        self,
        passages: List[Passage],
        max_snippets: int = 3,
    ) -> List[str]:
        """Extrait les snippets de couverture (premiers passages)."""
        snippets = []
        for passage in passages[:5]:
            text = passage.text[:300] if passage.text else ""
            if text:
                snippets.append(text)
                if len(snippets) >= max_snippets:
                    break
        return snippets

    def _extract_global_view_excerpt(
        self,
        passages: List[Passage],
        max_chars: int = 1200,
    ) -> str:
        """Construit un extrait de vue globale depuis les passages."""
        texts = []
        current_len = 0

        for passage in passages[:20]:
            text = passage.text[:200] if passage.text else ""
            if text:
                if current_len + len(text) > max_chars:
                    break
                texts.append(text)
                current_len += len(text) + 10  # +10 pour le séparateur

        return " ... ".join(texts)

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
            "subject_resolver_v2": self.subject_resolver_v2.get_stats(),
            "axis_detector": self.axis_detector.get_stats(),
            "axis_validator": self.axis_validator.get_stats(),
            "claim_extractor": self.claim_extractor.get_stats(),
            "entity_extractor": self.entity_extractor.get_stats(),
            "entity_canonicalizer": self.entity_canonicalizer.get_stats(),
            "passage_linker": self.passage_linker.get_stats(),
            "entity_linker": self.entity_linker.get_stats(),
            "facet_extractor": self.facet_extractor.get_stats(),
            "facet_registry": self.facet_registry.get_stats(),
            "facet_matcher": self.facet_matcher.get_stats(),
            "claim_clusterer": self.claim_clusterer.get_stats(),
            "relation_detector": self.relation_detector.get_stats(),
            "chain_detector": self.chain_detector.get_stats(),
            "slot_enricher": self.slot_enricher.get_stats(),
            "persister": self.persister.get_stats() if self.persister else {},
            "subject_anchors_cached": len(self._subject_anchors),
            "applicability_axes_cached": len(self._applicability_axes),
        }

    def reset_stats(self) -> None:
        """Réinitialise toutes les statistiques."""
        self.context_extractor.reset_stats()
        self.subject_resolver.reset_stats()
        self.subject_resolver_v2.reset_stats()
        self.axis_detector.reset_stats()
        self.axis_validator.reset_stats()
        self.claim_extractor.reset_stats()
        self.entity_extractor.reset_stats()
        self.entity_canonicalizer.reset_stats()
        self.passage_linker.reset_stats()
        self.entity_linker.reset_stats()
        self.facet_matcher.reset_stats()
        self.claim_clusterer.reset_stats()
        self.relation_detector.reset_stats()
        self.chain_detector.reset_stats()
        self.slot_enricher.reset_stats()
        if self.persister:
            self.persister.reset_stats()


    # =========================================================================
    # Phase 4.5 — Domain Pack Enrichment
    # =========================================================================

    def _run_domain_pack_enrichment(
        self,
        claims: List[Claim],
        entities: List[Entity],
        claim_entity_links: List[Tuple[str, str]],
        tenant_id: str,
    ) -> Tuple[List[Entity], List[Tuple[str, str]], Dict[Tuple[str, str], str]]:
        """
        Enrichissement via Domain Packs actifs (Phase 4.5).

        INV-PACK: Le pack augmente le recall. Le core garde le monopole de la décision.
        INV-PERSIST: Aucun artefact pack persiste sans passage par les gates core.
        INV-CONFLICT: Conflit inter-pack → marque ambigu, review admin.

        Returns:
            (new_entities, new_links, link_methods)
        """
        from knowbase.domain_packs.registry import get_pack_registry
        from knowbase.claimfirst.models.entity import is_valid_entity_name, Entity as EntityModel, EntityType

        registry = get_pack_registry()
        active_packs = registry.get_active_packs(tenant_id)

        if not active_packs:
            return [], [], {}

        # Identifier les claims isolées (sans relation ABOUT)
        claims_with_entity = {cid for cid, _ in claim_entity_links}
        isolated_claims = [c for c in claims if c.claim_id not in claims_with_entity]

        if not isolated_claims:
            logger.info("  → No isolated claims to enrich")
            return [], [], {}

        logger.info(f"  → {len(isolated_claims)} isolated claims, {len(active_packs)} active pack(s)")

        # Charger le domain context
        domain_context = None
        try:
            from knowbase.ontology.domain_context_store import get_domain_context_store
            domain_context = get_domain_context_store().get_profile(tenant_id)
        except Exception as e:
            logger.warning(f"  → Cannot load domain context: {e}")

        existing_norms = {e.normalized_name for e in entities}
        all_new_entities: List[Entity] = []
        all_new_links: List[Tuple[str, str]] = []
        link_methods: Dict[Tuple[str, str], str] = {}

        # Tracking pour détection conflits inter-pack
        # {normalized_name: (entity_type, pack_name)}
        entity_type_by_pack: Dict[str, List[Tuple[EntityType, str]]] = defaultdict(list)

        for pack in active_packs:
            pack_stoplist = set(
                EntityModel.normalize(s) for s in pack.get_entity_stoplist()
            )

            for extractor in pack.get_entity_extractors():
                try:
                    new_entities, candidate_map = extractor.extract(
                        claims=isolated_claims,
                        existing_entities=entities + all_new_entities,
                        domain_context=domain_context,
                    )
                except Exception as e:
                    logger.error(
                        f"  → Extractor error in pack '{pack.name}': {e}"
                    )
                    continue

                # Gate core (INV-PERSIST)
                for entity in new_entities:
                    norm = entity.normalized_name

                    # Stoplist domaine
                    if norm in pack_stoplist:
                        continue

                    # is_valid_entity_name avec relaxation NER
                    if not is_valid_entity_name(entity.name, ner_sourced=True):
                        continue

                    # Dedup vs existant
                    if norm in existing_norms:
                        continue

                    # Tag source
                    object.__setattr__(entity, "source_pack", pack.name)

                    # Track pour conflits inter-pack
                    entity_type_by_pack[norm].append(
                        (entity.entity_type, pack.name)
                    )

                    all_new_entities.append(entity)
                    existing_norms.add(norm)

                # Créer les liens ABOUT pour les candidats validés
                valid_entity_ids = {e.entity_id for e in all_new_entities}
                for claim_id, entity_ids in candidate_map.items():
                    for eid in entity_ids:
                        if eid in valid_entity_ids:
                            link = (claim_id, eid)
                            all_new_links.append(link)
                            link_methods[link] = f"domain_pack:{pack.name}"

            # Linker core sur les claims isolées + nouvelles entités du pack
            pack_entities = [
                e for e in all_new_entities if e.source_pack == pack.name
            ]
            if pack_entities:
                extra_links = self.entity_linker.link(
                    claims=isolated_claims,
                    entities=pack_entities,
                )
                for link in extra_links:
                    if link not in all_new_links:
                        all_new_links.append(link)
                        link_methods[link] = f"domain_pack:{pack.name}"

        # Détection conflits inter-pack (INV-CONFLICT)
        for norm, type_pack_list in entity_type_by_pack.items():
            if len(type_pack_list) > 1:
                types = {t for t, _ in type_pack_list}
                if len(types) > 1:
                    packs_involved = [p for _, p in type_pack_list]
                    logger.warning(
                        f"  → CONFLICT: '{norm}' has conflicting types "
                        f"from packs {packs_involved}: {types}"
                    )
                    # Retirer l'entité conflictuelle
                    all_new_entities = [
                        e for e in all_new_entities
                        if e.normalized_name != norm
                    ]
                    # Retirer les liens associés
                    conflicting_ids = {
                        e.entity_id for e in all_new_entities
                        if e.normalized_name == norm
                    }
                    all_new_links = [
                        (cid, eid) for cid, eid in all_new_links
                        if eid not in conflicting_ids
                    ]
                    # Créer une action hygiene PROPOSED
                    try:
                        self._create_conflict_hygiene_action(
                            norm, type_pack_list, tenant_id
                        )
                    except Exception as e:
                        logger.error(f"  → Error creating conflict action: {e}")

        return all_new_entities, all_new_links, link_methods

    def _create_conflict_hygiene_action(
        self,
        normalized_name: str,
        type_pack_list: List[Tuple],
        tenant_id: str,
    ) -> None:
        """Crée un noeud HygieneAction pour un conflit inter-pack."""
        try:
            from knowbase.hygiene.models import HygieneAction, ActionType, ActionStatus
            import uuid

            action = HygieneAction(
                action_id=str(uuid.uuid4()),
                action_type=ActionType.MERGE_CANONICAL,
                status=ActionStatus.PROPOSED,
                layer=4,
                tenant_id=tenant_id,
                after_state={
                    "conflicting_packs": [p for _, p in type_pack_list],
                    "candidate_types": [t.value for t, _ in type_pack_list],
                    "normalized_name": normalized_name,
                    "source": "domain_pack_conflict",
                },
                description=(
                    f"Conflit inter-pack: '{normalized_name}' typé différemment "
                    f"par {len(type_pack_list)} packs"
                ),
            )
            logger.info(
                f"  → Created hygiene action for conflict: {normalized_name}"
            )
        except ImportError:
            logger.debug("  → Hygiene module not available for conflict action")


    def _resolve_canonical_aliases(
        self,
        entities: "List",
        tenant_id: str,
    ) -> int:
        """Phase 4.6 — Résout les aliases canoniques des domain packs actifs.

        Si une entité porte un nom qui est un alias connu (ex: "RISE with SAP"),
        elle est renommée vers le nom canonique (ex: "SAP S/4HANA Cloud Private Edition").
        Cela évite de créer des doublons que l'hygiène devrait ensuite fusionner.
        """
        from knowbase.domain_packs.registry import get_pack_registry

        registry = get_pack_registry()
        active_packs = registry.get_active_packs(tenant_id)

        if not active_packs:
            return 0

        # Construire la table d'aliases consolidée (tous packs confondus)
        all_aliases: Dict[str, str] = {}
        for pack in active_packs:
            defaults = pack._load_defaults_json()
            raw_aliases = defaults.get("canonical_aliases", {})
            for alias, canonical in raw_aliases.items():
                all_aliases[alias.lower()] = canonical

        if not all_aliases:
            return 0

        renamed = 0
        seen_canonicals: Dict[str, "Entity"] = {}

        for entity in entities:
            canonical = all_aliases.get(entity.name.lower())
            if not canonical:
                # Essayer aussi avec le normalized_name
                canonical = all_aliases.get(entity.normalized_name)
            if not canonical:
                continue
            if canonical.lower() == entity.name.lower():
                continue  # déjà le bon nom

            old_name = entity.name
            entity.name = canonical
            entity.normalized_name = canonical.lower().strip()
            renamed += 1
            logger.debug(
                f"  → Alias resolved: '{old_name}' => '{canonical}'"
            )

        return renamed


__all__ = [
    "ClaimFirstOrchestrator",
]
