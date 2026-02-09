# src/knowbase/claimfirst/persistence/claim_persister.py
"""
ClaimPersister - Persistance Neo4j pour le pipeline Claim-First.

Persiste tous les artefacts du pipeline:
- Passages
- Claims
- Entities
- Facets
- ClaimClusters
- Relations (SUPPORTED_BY, ABOUT, HAS_FACET, IN_CLUSTER, etc.)

Utilise MERGE pour l'idempotence.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.entity import Entity
from knowbase.claimfirst.models.facet import Facet
from knowbase.claimfirst.models.passage import Passage
from knowbase.claimfirst.models.result import ClaimFirstResult, ClaimCluster, ClaimRelation
from knowbase.claimfirst.models.document_context import DocumentContext
from knowbase.claimfirst.models.subject_anchor import SubjectAnchor
from knowbase.claimfirst.models.applicability_axis import ApplicabilityAxis
from knowbase.claimfirst.models.comparable_subject import ComparableSubject

logger = logging.getLogger(__name__)


class ClaimPersister:
    """
    Persiste les résultats du pipeline Claim-First dans Neo4j.

    Utilise MERGE pour garantir l'idempotence.
    """

    def __init__(self, driver, tenant_id: str = "default"):
        """
        Initialise le persister.

        Args:
            driver: Neo4j driver
            tenant_id: Tenant ID par défaut
        """
        self.driver = driver
        self.tenant_id = tenant_id

        self.stats = {
            "passages_created": 0,
            "claims_created": 0,
            "entities_created": 0,
            "facets_created": 0,
            "clusters_created": 0,
            "relations_created": 0,
            "doc_contexts_created": 0,
            "subject_anchors_created": 0,
            "comparable_subjects_created": 0,
            "comparable_subjects_merged": 0,
            "axes_created": 0,
            "axis_value_relations_created": 0,
        }

    def persist(self, result: ClaimFirstResult) -> dict:
        """
        Persiste un résultat complet du pipeline.

        Args:
            result: ClaimFirstResult à persister

        Returns:
            Statistiques de persistance
        """
        with self.driver.session() as session:
            # 0. DocumentContext (INV-8: scope appartient au Document)
            if result.doc_context:
                self._persist_document_context(session, result.doc_context, result.doc_id)

            # 0.1. ApplicabilityFrame JSON sur le DocumentContext
            if result.applicability_frame and hasattr(result.applicability_frame, 'to_json_dict'):
                self._persist_applicability_frame(
                    session, result.doc_context, result.applicability_frame
                )

            # 0.5. ComparableSubject (INV-25: sujet stable comparable)
            if result.comparable_subject:
                # Peut retourner un sujet fusionné avec un existant
                persisted_subject = self._persist_comparable_subject(
                    session, result.comparable_subject
                )
                # Lier DocumentContext → ComparableSubject (avec le sujet potentiellement fusionné)
                if result.doc_context:
                    self._persist_context_comparable_link(
                        session, result.doc_context, persisted_subject
                    )

            # 0.55. SubjectAnchors (INV-9: résolution conservative) - topics secondaires
            for anchor in result.subject_anchors:
                self._persist_subject_anchor(session, anchor)

            # 0.6. Relations DocumentContext → SubjectAnchor (ABOUT_SUBJECT) - topics
            if result.doc_context and result.doc_context.subject_ids:
                self._persist_context_subject_links(
                    session, result.doc_context, result.doc_id
                )

            # 0.7. ApplicabilityAxis (INV-12/14/25/26)
            for axis in result.detected_axes:
                self._persist_applicability_axis(session, axis)

            # 0.8. Relations DocumentContext → ApplicabilityAxis (HAS_AXIS_VALUE)
            if result.doc_context and result.doc_context.axis_values:
                self._persist_axis_value_relations(
                    session, result.doc_context, result.detected_axes
                )

            # 1. Passages — conditionnel via OSMOSE_SKIP_PASSAGE_PERSIST
            skip_passage_persist = os.getenv("OSMOSE_SKIP_PASSAGE_PERSIST", "true").lower() == "true"

            # Construire un index passage_id → Passage pour enrichir les claims
            passage_index = {p.passage_id: p for p in result.passages}

            if not skip_passage_persist:
                # Comportement legacy : persister les Passages comme nœuds Neo4j
                linked_passage_ids = {passage_id for _, passage_id in result.claim_passage_links}
                passages_to_persist = [p for p in result.passages if p.passage_id in linked_passage_ids]

                logger.debug(
                    f"[OSMOSE:ClaimPersister] Persisting {len(passages_to_persist)}/{len(result.passages)} "
                    f"passages (filtering orphans)"
                )

                for passage in passages_to_persist:
                    self._persist_passage(session, passage)
            else:
                passages_to_persist = []
                logger.debug(
                    "[OSMOSE:ClaimPersister] OSMOSE_SKIP_PASSAGE_PERSIST=true — "
                    "passages stockés comme propriétés sur les Claims"
                )

            # Construire un mapping claim_id → passage pour extra_props
            claim_passage_map: Dict[str, str] = {}
            for claim_id, passage_id in result.claim_passage_links:
                claim_passage_map[claim_id] = passage_id

            # 2. Claims (avec extra_props passage si skip_passage_persist)
            for claim in result.claims:
                extra_props = None
                if skip_passage_persist:
                    p_id = claim_passage_map.get(claim.claim_id)
                    passage = passage_index.get(p_id) if p_id else None
                    if passage:
                        extra_props = {
                            "passage_text": passage.text,
                            "section_title": passage.section_title,
                            "page_no": passage.page_no,
                            "passage_char_start": passage.char_start,
                            "passage_char_end": passage.char_end,
                        }
                self._persist_claim(session, claim, extra_props=extra_props)

            # 3. Entities
            for entity in result.entities:
                self._persist_entity(session, entity)

            # 4. Facets
            for facet in result.facets:
                self._persist_facet(session, facet)

            # 5. ClaimClusters
            for cluster in result.clusters:
                self._persist_cluster(session, cluster)

            # 6-7. Relations Passage (seulement si passages persistés comme nœuds)
            if not skip_passage_persist:
                # 6. Relations Passage → Document (FROM)
                self._persist_passage_document_links(session, passages_to_persist, result.doc_id)

                # 7. Relations Claim → Passage (SUPPORTED_BY)
                for claim_id, passage_id in result.claim_passage_links:
                    self._persist_supported_by(session, claim_id, passage_id)

            # 8. Relations Claim → Entity (ABOUT)
            for claim_id, entity_id in result.claim_entity_links:
                self._persist_about(session, claim_id, entity_id)

            # 9. Relations Claim → Facet (HAS_FACET)
            for claim_id, facet_id in result.claim_facet_links:
                self._persist_has_facet(session, claim_id, facet_id)

            # 10. Relations Claim → Cluster (IN_CLUSTER)
            for claim_id, cluster_id in result.claim_cluster_links:
                self._persist_in_cluster(session, claim_id, cluster_id)

            # 11. Relations inter-claims (CONTRADICTS, REFINES, QUALIFIES)
            for relation in result.relations:
                self._persist_claim_relation(session, relation)

        logger.info(
            f"[OSMOSE:ClaimPersister] Persisted: "
            f"{self.stats['doc_contexts_created']} contexts, "
            f"{self.stats['comparable_subjects_created']} comparable subjects, "
            f"{self.stats['subject_anchors_created']} topic anchors, "
            f"{self.stats['axes_created']} axes, "
            f"{self.stats['passages_created']} passages, "
            f"{self.stats['claims_created']} claims, "
            f"{self.stats['entities_created']} entities, "
            f"{self.stats['facets_created']} facets, "
            f"{self.stats['clusters_created']} clusters, "
            f"{self.stats['relations_created']} relations"
        )

        return dict(self.stats)

    def _persist_passage(self, session, passage: Passage) -> None:
        """Persiste un Passage."""
        props = passage.to_neo4j_properties()
        query = """
        MERGE (p:Passage {passage_id: $passage_id})
        SET p += $props
        """
        session.run(query, passage_id=passage.passage_id, props=props)
        self.stats["passages_created"] += 1

    def _persist_claim(self, session, claim: Claim, extra_props: Optional[Dict[str, Any]] = None) -> None:
        """Persiste une Claim avec propriétés supplémentaires optionnelles."""
        props = claim.to_neo4j_properties()
        if extra_props:
            props.update(extra_props)
        query = """
        MERGE (c:Claim {claim_id: $claim_id})
        SET c += $props
        """
        session.run(query, claim_id=claim.claim_id, props=props)
        self.stats["claims_created"] += 1

    def _persist_entity(self, session, entity: Entity) -> None:
        """Persiste une Entity (MERGE sur normalized_name)."""
        props = entity.to_neo4j_properties()
        query = """
        MERGE (e:Entity {normalized_name: $normalized_name, tenant_id: $tenant_id})
        ON CREATE SET e += $props
        ON MATCH SET e.mention_count = e.mention_count + 1
        """
        session.run(
            query,
            normalized_name=entity.normalized_name,
            tenant_id=entity.tenant_id,
            props=props,
        )
        self.stats["entities_created"] += 1

    def _persist_facet(self, session, facet: Facet) -> None:
        """Persiste une Facet."""
        props = facet.to_neo4j_properties()
        query = """
        MERGE (f:Facet {facet_id: $facet_id})
        SET f += $props
        """
        session.run(query, facet_id=facet.facet_id, props=props)
        self.stats["facets_created"] += 1

    def _persist_cluster(self, session, cluster: ClaimCluster) -> None:
        """Persiste un ClaimCluster."""
        props = cluster.to_neo4j_properties()
        query = """
        MERGE (cc:ClaimCluster {cluster_id: $cluster_id})
        SET cc += $props
        """
        session.run(query, cluster_id=cluster.cluster_id, props=props)
        self.stats["clusters_created"] += 1

    def _persist_document_context(
        self,
        session,
        context: DocumentContext,
        doc_id: str,
    ) -> None:
        """
        Persiste un DocumentContext et le lie au Document.

        INV-8: Le scope appartient au Document, pas à la Claim.

        Crée:
        - Noeud DocumentContext
        - Relation Document -[:HAS_CONTEXT]-> DocumentContext
        """
        # Neo4j n'accepte pas les dicts comme propriétés, sérialiser en JSON
        props = {
            "doc_id": context.doc_id,
            "tenant_id": context.tenant_id,
            "primary_subject": context.primary_subject,
            "raw_subjects": context.raw_subjects,
            "subject_ids": context.subject_ids,
            "resolution_status": context.resolution_status.value,
            "resolution_confidence": context.resolution_confidence,
            "qualifiers_json": json.dumps(context.qualifiers) if context.qualifiers else "{}",
            "qualifier_candidates_json": json.dumps(context.qualifier_candidates) if context.qualifier_candidates else "{}",
            "document_type": context.document_type,
            "temporal_scope": context.temporal_scope,
            "extraction_method": context.extraction_method,
            "created_at": context.created_at.isoformat(),
        }

        # Créer/mettre à jour le DocumentContext
        query = """
        MERGE (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
        SET dc += $props
        """
        session.run(query, doc_id=context.doc_id, tenant_id=context.tenant_id, props=props)

        # Lier au Document (si existe)
        link_query = """
        MATCH (d:Document {doc_id: $doc_id})
        MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
        MERGE (d)-[:HAS_CONTEXT]->(dc)
        """
        session.run(link_query, doc_id=doc_id, tenant_id=context.tenant_id)

        self.stats["doc_contexts_created"] += 1

    def _persist_applicability_frame(
        self,
        session,
        context: Optional[DocumentContext],
        frame,
    ) -> None:
        """
        Stocke le frame JSON sur le nœud DocumentContext dans Neo4j.

        Le frame est sérialisé en JSON string pour le stockage.
        """
        if not context:
            return

        frame_json = json.dumps(frame.to_json_dict())

        query = """
        MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
        SET dc.applicability_frame_json = $frame_json,
            dc.applicability_frame_method = $method,
            dc.applicability_frame_field_count = $field_count
        """
        session.run(
            query,
            doc_id=context.doc_id,
            tenant_id=context.tenant_id,
            frame_json=frame_json,
            method=frame.method,
            field_count=len(frame.fields),
        )

    def _persist_subject_anchor(self, session, anchor: SubjectAnchor) -> None:
        """
        Persiste un SubjectAnchor.

        INV-9: Résolution conservative des sujets.
        """
        # Neo4j n'accepte pas les dicts comme propriétés, sérialiser en JSON
        props = {
            "subject_id": anchor.subject_id,
            "canonical_name": anchor.canonical_name,
            "aliases_explicit": anchor.aliases_explicit,
            "aliases_inferred": anchor.aliases_inferred,
            "aliases_learned": anchor.aliases_learned,
            "domain": anchor.domain,
            "qualifiers_validated_json": json.dumps(anchor.qualifiers_validated) if anchor.qualifiers_validated else "{}",
            "qualifiers_candidates_json": json.dumps(anchor.qualifiers_candidates) if anchor.qualifiers_candidates else "{}",
            "source_doc_ids": anchor.source_doc_ids,
            "possible_equivalents": anchor.possible_equivalents,
            "created_at": anchor.created_at.isoformat(),
            "updated_at": anchor.updated_at.isoformat(),
        }

        query = """
        MERGE (sa:SubjectAnchor {subject_id: $subject_id})
        SET sa += $props
        """
        session.run(query, subject_id=anchor.subject_id, props=props)
        self.stats["subject_anchors_created"] += 1

    def _persist_comparable_subject(
        self,
        session,
        subject: ComparableSubject,
    ) -> ComparableSubject:
        """
        Persiste un ComparableSubject avec fusion intelligente.

        INV-25: Sujet stable comparable entre documents.

        Cherche d'abord un ComparableSubject existant avec un nom similaire
        pour éviter les doublons ("S/4HANA" vs "SAP S/4HANA").

        Returns:
            Le ComparableSubject (existant fusionné ou nouveau créé)
        """
        # 1. Chercher un ComparableSubject existant avec nom similaire
        existing = self._find_similar_comparable_subject(
            session, subject.tenant_id, subject.canonical_name
        )

        if existing:
            # Fusionner : ajouter l'alias et le doc_id
            logger.info(
                f"[ClaimPersister] Merging '{subject.canonical_name}' "
                f"into existing ComparableSubject '{existing['canonical_name']}'"
            )
            query = """
            MATCH (cs:ComparableSubject {subject_id: $subject_id})
            SET cs.doc_count = cs.doc_count + 1,
                cs.updated_at = datetime(),
                cs.aliases = CASE
                    WHEN $new_alias IS NOT NULL AND NOT $new_alias IN coalesce(cs.aliases, [])
                    THEN coalesce(cs.aliases, []) + $new_alias
                    ELSE cs.aliases
                END,
                cs.source_doc_ids = CASE
                    WHEN $doc_id IS NOT NULL AND NOT $doc_id IN coalesce(cs.source_doc_ids, [])
                    THEN coalesce(cs.source_doc_ids, []) + $doc_id
                    ELSE cs.source_doc_ids
                END
            RETURN cs.subject_id as subject_id, cs.canonical_name as canonical_name
            """
            # Ajouter comme alias si différent
            new_alias = subject.canonical_name if subject.canonical_name.lower() != existing['canonical_name'].lower() else None
            doc_id = subject.source_doc_ids[0] if subject.source_doc_ids else None
            session.run(
                query,
                subject_id=existing['subject_id'],
                new_alias=new_alias,
                doc_id=doc_id,
            )
            # Retourner le sujet existant avec l'ID correct
            subject.subject_id = existing['subject_id']
            subject.canonical_name = existing['canonical_name']
            self.stats["comparable_subjects_merged"] += 1
            return subject

        # 2. Pas d'existant similaire - créer nouveau
        props = subject.to_neo4j_properties()
        query = """
        MERGE (cs:ComparableSubject {subject_id: $subject_id})
        SET cs += $props
        """
        session.run(query, subject_id=subject.subject_id, props=props)
        self.stats["comparable_subjects_created"] += 1
        return subject

    def _find_similar_comparable_subject(
        self,
        session,
        tenant_id: str,
        canonical_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Cherche un ComparableSubject existant qui représente le MÊME sujet.

        Utilise le LLM pour valider que deux noms similaires représentent
        bien le même sujet (évite de fusionner "HANA" avec "S/4HANA").

        Args:
            session: Session Neo4j
            tenant_id: Tenant ID
            canonical_name: Nom à chercher

        Returns:
            Dict avec subject_id et canonical_name si trouvé, None sinon
        """
        name_lower = canonical_name.lower().strip()

        # 1. Chercher des candidats potentiels par containment
        query = """
        MATCH (cs:ComparableSubject)
        WHERE cs.tenant_id = $tenant_id
          AND (
            toLower(cs.canonical_name) CONTAINS $name_lower
            OR $name_lower CONTAINS toLower(cs.canonical_name)
          )
        RETURN cs.subject_id as subject_id, cs.canonical_name as canonical_name
        ORDER BY size(cs.canonical_name) DESC
        LIMIT 5
        """
        result = session.run(query, tenant_id=tenant_id, name_lower=name_lower)
        candidates = [dict(r) for r in result]

        if not candidates:
            return None

        # 2. Valider chaque candidat via LLM
        for candidate in candidates:
            if self._llm_validate_same_subject(canonical_name, candidate["canonical_name"]):
                return candidate

        return None

    def _llm_validate_same_subject(
        self,
        name1: str,
        name2: str,
    ) -> bool:
        """
        Utilise le LLM pour valider si deux noms représentent le même sujet.

        Exemples:
        - "S/4HANA" et "SAP S/4HANA" → True (même produit)
        - "HANA" et "S/4HANA" → False (produits différents)
        - "Clio III" et "Renault Clio III" → True (même véhicule)

        Args:
            name1: Premier nom
            name2: Second nom

        Returns:
            True si même sujet, False sinon
        """
        # Cas trivial : identiques après normalisation
        if name1.lower().strip() == name2.lower().strip():
            return True

        try:
            from knowbase.common.llm_router import get_llm_router, TaskType

            router = get_llm_router()

            prompt = f"""Deux noms de sujets ont été détectés dans des documents différents.
Détermines si ces deux noms représentent EXACTEMENT le même sujet/produit/entité.

Nom 1: "{name1}"
Nom 2: "{name2}"

ATTENTION:
- "SAP S/4HANA" et "S/4HANA" = MÊME sujet (variante avec/sans préfixe marque)
- "HANA" et "S/4HANA" = DIFFÉRENTS (HANA est une base de données, S/4HANA est un ERP)
- "Renault Clio" et "Clio" = MÊME sujet (variante avec/sans marque)
- "Clio" et "Megane" = DIFFÉRENTS (modèles différents)

Réponds UNIQUEMENT par "SAME" ou "DIFFERENT"."""

            response = router.complete(
                task_type=TaskType.FAST_CLASSIFICATION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=10,
            )

            response_clean = response.strip().upper()
            is_same = "SAME" in response_clean and "DIFFERENT" not in response_clean

            logger.debug(
                f"[ClaimPersister] LLM validation '{name1}' vs '{name2}': "
                f"{response_clean} → {'merge' if is_same else 'keep separate'}"
            )

            return is_same

        except Exception as e:
            logger.warning(f"[ClaimPersister] LLM validation failed: {e}")
            # En cas d'erreur, ne pas fusionner (sécurité)
            return False

    def _persist_context_comparable_link(
        self,
        session,
        context: DocumentContext,
        subject: ComparableSubject,
    ) -> None:
        """
        Crée la relation DocumentContext -[:ABOUT_COMPARABLE]-> ComparableSubject.

        INV-25: Sujet stable comparable entre documents.

        Met aussi à jour primary_subject du DocumentContext avec le canonical_name
        du ComparableSubject résolu (synchronisation pour cohérence).
        """
        query = """
        MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
        MATCH (cs:ComparableSubject {subject_id: $subject_id})
        MERGE (dc)-[:ABOUT_COMPARABLE]->(cs)
        SET dc.primary_subject = cs.canonical_name,
            dc.primary_subject_confidence = cs.confidence
        """
        session.run(
            query,
            doc_id=context.doc_id,
            tenant_id=context.tenant_id,
            subject_id=subject.subject_id,
        )
        self.stats["relations_created"] += 1

    def _persist_context_subject_links(
        self,
        session,
        context: DocumentContext,
        doc_id: str,
    ) -> None:
        """
        Crée les relations DocumentContext -[:ABOUT_SUBJECT]-> SubjectAnchor.

        INV-8: Le scope appartient au Document.
        Note: Ces relations sont pour les topics secondaires.
        Le sujet principal comparable utilise ABOUT_COMPARABLE.
        """
        for subject_id in context.subject_ids:
            query = """
            MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
            MATCH (sa:SubjectAnchor {subject_id: $subject_id})
            MERGE (dc)-[:ABOUT_SUBJECT]->(sa)
            """
            session.run(
                query,
                doc_id=doc_id,
                tenant_id=context.tenant_id,
                subject_id=subject_id,
            )
            self.stats["relations_created"] += 1

    def _persist_applicability_axis(
        self,
        session,
        axis: ApplicabilityAxis,
    ) -> None:
        """
        Persiste un ApplicabilityAxis.

        INV-12/14/25: Axe d'applicabilité avec ordering.

        Note: Fusionne les known_values et source_doc_ids au lieu de les remplacer.
        """
        props = axis.to_neo4j_properties()

        # Extraire les listes à fusionner
        new_values = props.pop("known_values", []) or []
        new_doc_ids = props.pop("source_doc_ids", []) or []

        query = """
        MERGE (ax:ApplicabilityAxis {axis_id: $axis_id})
        ON CREATE SET
            ax = $props,
            ax.known_values = $new_values,
            ax.source_doc_ids = $new_doc_ids,
            ax.doc_count = 1
        ON MATCH SET
            ax.known_values = apoc.coll.toSet(coalesce(ax.known_values, []) + $new_values),
            ax.source_doc_ids = apoc.coll.toSet(coalesce(ax.source_doc_ids, []) + $new_doc_ids),
            ax.doc_count = size(apoc.coll.toSet(coalesce(ax.source_doc_ids, []) + $new_doc_ids)),
            ax.axis_display_name = CASE WHEN ax.axis_display_name IS NULL THEN $props.axis_display_name ELSE ax.axis_display_name END,
            ax.is_orderable = $props.is_orderable,
            ax.order_type = $props.order_type,
            ax.ordering_confidence = $props.ordering_confidence
        """
        session.run(
            query,
            axis_id=axis.axis_id,
            props=props,
            new_values=new_values,
            new_doc_ids=new_doc_ids,
        )
        self.stats["axes_created"] += 1

    def _persist_axis_value_relations(
        self,
        session,
        context: DocumentContext,
        axes: List[ApplicabilityAxis],
    ) -> None:
        """
        Crée les relations DocumentContext -[:HAS_AXIS_VALUE]-> ApplicabilityAxis.

        INV-26: Evidence obligatoire (passage_id ou snippet_ref).

        Properties sur la relation:
        - value_type: SCALAR/RANGE/SET
        - scalar_value / range_start / range_end / set_values
        - evidence_passage_id
        - evidence_snippet_ref
        - reliability
        """
        # Créer un mapping axis_key → axis_id
        axis_map = {ax.axis_key: ax.axis_id for ax in axes}

        for axis_key, axis_value_dict in context.axis_values.items():
            # Trouver l'axis_id correspondant
            axis_id = axis_map.get(axis_key)
            if not axis_id:
                # Essayer de trouver dans Neo4j
                result = session.run(
                    """
                    MATCH (ax:ApplicabilityAxis {tenant_id: $tenant_id, axis_key: $axis_key})
                    RETURN ax.axis_id as axis_id
                    LIMIT 1
                    """,
                    tenant_id=context.tenant_id,
                    axis_key=axis_key,
                )
                record = result.single()
                if record:
                    axis_id = record["axis_id"]
                else:
                    logger.warning(
                        f"[OSMOSE:ClaimPersister] No axis found for key {axis_key}"
                    )
                    continue

            # Extraire les propriétés de la relation (INV-26)
            rel_props = {
                "value_type": axis_value_dict.get("value_type", "scalar"),
                "scalar_value": axis_value_dict.get("scalar_value"),
                "range_start": axis_value_dict.get("range_start"),
                "range_end": axis_value_dict.get("range_end"),
                "set_values": axis_value_dict.get("set_values"),
                "evidence_passage_id": axis_value_dict.get("evidence_passage_id"),
                "evidence_snippet_ref": axis_value_dict.get("evidence_snippet_ref", "unknown"),
                "reliability": axis_value_dict.get("reliability", "explicit_text"),
            }

            query = """
            MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
            MATCH (ax:ApplicabilityAxis {axis_id: $axis_id})
            MERGE (dc)-[r:HAS_AXIS_VALUE]->(ax)
            SET r += $props
            """
            session.run(
                query,
                doc_id=context.doc_id,
                tenant_id=context.tenant_id,
                axis_id=axis_id,
                props=rel_props,
            )
            self.stats["axis_value_relations_created"] += 1

    def _persist_passage_document_links(
        self,
        session,
        passages: List[Passage],
        doc_id: str,
    ) -> None:
        """Crée les relations Passage → Document (FROM)."""
        query = """
        MATCH (p:Passage {passage_id: $passage_id})
        MATCH (d:Document {doc_id: $doc_id})
        MERGE (p)-[:FROM]->(d)
        """
        for passage in passages:
            session.run(query, passage_id=passage.passage_id, doc_id=doc_id)
            self.stats["relations_created"] += 1

    def _persist_supported_by(
        self,
        session,
        claim_id: str,
        passage_id: str,
    ) -> None:
        """Crée la relation Claim -[:SUPPORTED_BY]-> Passage."""
        query = """
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (p:Passage {passage_id: $passage_id})
        MERGE (c)-[:SUPPORTED_BY]->(p)
        """
        session.run(query, claim_id=claim_id, passage_id=passage_id)
        self.stats["relations_created"] += 1

    def _persist_about(
        self,
        session,
        claim_id: str,
        entity_id: str,
    ) -> None:
        """
        Crée la relation Claim -[:ABOUT]-> Entity.

        Note: Pas de {role} en V1 (INV-4).
        """
        query = """
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (e:Entity {entity_id: $entity_id})
        MERGE (c)-[:ABOUT]->(e)
        """
        session.run(query, claim_id=claim_id, entity_id=entity_id)
        self.stats["relations_created"] += 1

    def _persist_has_facet(
        self,
        session,
        claim_id: str,
        facet_id: str,
    ) -> None:
        """Crée la relation Claim -[:HAS_FACET]-> Facet."""
        query = """
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (f:Facet {facet_id: $facet_id})
        MERGE (c)-[:HAS_FACET]->(f)
        """
        session.run(query, claim_id=claim_id, facet_id=facet_id)
        self.stats["relations_created"] += 1

    def _persist_in_cluster(
        self,
        session,
        claim_id: str,
        cluster_id: str,
    ) -> None:
        """Crée la relation Claim -[:IN_CLUSTER]-> ClaimCluster."""
        query = """
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (cc:ClaimCluster {cluster_id: $cluster_id})
        MERGE (c)-[:IN_CLUSTER]->(cc)
        """
        session.run(query, claim_id=claim_id, cluster_id=cluster_id)
        self.stats["relations_created"] += 1

    def _persist_claim_relation(
        self,
        session,
        relation: ClaimRelation,
    ) -> None:
        """Crée une relation inter-claims (CONTRADICTS, REFINES, QUALIFIES)."""
        props = relation.to_neo4j_properties()
        rel_type = relation.relation_type.value

        query = f"""
        MATCH (c1:Claim {{claim_id: $source_id}})
        MATCH (c2:Claim {{claim_id: $target_id}})
        MERGE (c1)-[r:{rel_type}]->(c2)
        SET r += $props
        """
        session.run(
            query,
            source_id=relation.source_claim_id,
            target_id=relation.target_claim_id,
            props=props,
        )
        self.stats["relations_created"] += 1

    def delete_document_claims(
        self,
        doc_id: str,
        tenant_id: Optional[str] = None,
    ) -> dict:
        """
        Supprime toutes les claims d'un document.

        Utile pour le retraitement.

        Args:
            doc_id: Document ID
            tenant_id: Tenant ID (optionnel)

        Returns:
            Statistiques de suppression
        """
        tenant_id = tenant_id or self.tenant_id
        stats = {"claims_deleted": 0, "passages_deleted": 0, "relations_deleted": 0}

        with self.driver.session() as session:
            # Supprimer les relations d'abord
            rel_query = """
            MATCH (c:Claim {doc_id: $doc_id, tenant_id: $tenant_id})-[r]->()
            DELETE r
            RETURN count(r) as count
            """
            result = session.run(rel_query, doc_id=doc_id, tenant_id=tenant_id)
            stats["relations_deleted"] = result.single()["count"]

            # Supprimer les claims
            claim_query = """
            MATCH (c:Claim {doc_id: $doc_id, tenant_id: $tenant_id})
            DELETE c
            RETURN count(c) as count
            """
            result = session.run(claim_query, doc_id=doc_id, tenant_id=tenant_id)
            stats["claims_deleted"] = result.single()["count"]

            # Supprimer les passages (seulement si pas en mode skip)
            skip_passage_persist = os.getenv("OSMOSE_SKIP_PASSAGE_PERSIST", "true").lower() == "true"
            if not skip_passage_persist:
                passage_query = """
                MATCH (p:Passage {doc_id: $doc_id, tenant_id: $tenant_id})
                WHERE NOT EXISTS {
                    MATCH (c:Claim)-[:SUPPORTED_BY]->(p)
                }
                DELETE p
                RETURN count(p) as count
                """
                result = session.run(passage_query, doc_id=doc_id, tenant_id=tenant_id)
                stats["passages_deleted"] = result.single()["count"]

        logger.info(
            f"[OSMOSE:ClaimPersister] Deleted claims for doc {doc_id}: "
            f"{stats['claims_deleted']} claims, "
            f"{stats['passages_deleted']} passages, "
            f"{stats['relations_deleted']} relations"
        )

        return stats

    def get_stats(self) -> dict:
        """Retourne les statistiques de persistance."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "passages_created": 0,
            "claims_created": 0,
            "entities_created": 0,
            "facets_created": 0,
            "clusters_created": 0,
            "relations_created": 0,
            "doc_contexts_created": 0,
            "subject_anchors_created": 0,
            "comparable_subjects_created": 0,
            "comparable_subjects_merged": 0,
            "axes_created": 0,
            "axis_value_relations_created": 0,
        }


__all__ = [
    "ClaimPersister",
]
