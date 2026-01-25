"""
OSMOSE Pipeline V2 - Pass 1 Persister
======================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Persiste les résultats Pass 1 dans Neo4j:
- Subject (HAS_SUBJECT)
- Theme (HAS_THEME, SCOPED_TO)
- Concept (HAS_CONCEPT)
- Information (HAS_INFORMATION, ANCHORED_IN)
- AssertionLog (LOGGED_FOR)

Respecte les invariants V2-001 à V2-010.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from knowbase.stratified.models import (
    Pass1Result,
    Subject,
    Theme,
    Concept,
    Information,
    AssertionLogEntry,
    AssertionStatus,
)
from knowbase.stratified.models.information import InformationMVP, PromotionStatus

logger = logging.getLogger(__name__)


class Pass1PersisterV2:
    """
    Persiste les résultats Pass 1 dans Neo4j.

    Crée les nœuds et relations du graphe sémantique:
    - Document -[:HAS_SUBJECT]-> Subject
    - Subject -[:HAS_THEME]-> Theme
    - Theme -[:HAS_CONCEPT]-> Concept
    - Theme -[:SCOPED_TO]-> Section (optionnel)
    - Concept -[:HAS_INFORMATION]-> Information
    - Information -[:ANCHORED_IN]-> DocItem
    - AssertionLog -[:LOGGED_FOR]-> Document
    """

    def __init__(self, neo4j_driver=None, tenant_id: str = "default"):
        """
        Args:
            neo4j_driver: Driver Neo4j
            tenant_id: Identifiant du tenant
        """
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    def persist(self, result: Pass1Result) -> Dict[str, int]:
        """
        Persiste un Pass1Result complet dans Neo4j.

        Args:
            result: Résultat Pass 1 à persister

        Returns:
            Dict avec compteurs de nœuds créés
        """
        if not self.driver:
            logger.warning("[OSMOSE:Pass1:Persist] No Neo4j driver configured")
            return {"error": "no_driver"}

        stats = {
            "subject": 0,
            "themes": 0,
            "concepts": 0,
            "informations": 0,
            "informations_mvp": 0,
            "claimkeys": 0,
            "assertion_logs": 0,
            "relations": 0,
        }

        with self.driver.session() as session:
            try:
                # 1. Créer le Subject
                session.execute_write(
                    self._create_subject_tx,
                    result.doc.doc_id,
                    result.subject,
                    self.tenant_id
                )
                stats["subject"] = 1
                logger.info(f"[OSMOSE:Pass1:Persist] Subject créé: {result.subject.subject_id}")

                # 2. Créer les Themes
                for theme in result.themes:
                    session.execute_write(
                        self._create_theme_tx,
                        result.subject.subject_id,
                        theme,
                        self.tenant_id
                    )
                    stats["themes"] += 1
                logger.info(f"[OSMOSE:Pass1:Persist] {stats['themes']} themes créés")

                # 3. Créer les Concepts
                for concept in result.concepts:
                    session.execute_write(
                        self._create_concept_tx,
                        concept,
                        self.tenant_id
                    )
                    stats["concepts"] += 1
                logger.info(f"[OSMOSE:Pass1:Persist] {stats['concepts']} concepts créés")

                # 4. Créer les Informations + ANCHORED_IN
                for info in result.informations:
                    session.execute_write(
                        self._create_information_tx,
                        info,
                        self.tenant_id
                    )
                    stats["informations"] += 1
                    stats["relations"] += 2  # HAS_INFORMATION + ANCHORED_IN
                logger.info(f"[OSMOSE:Pass1:Persist] {stats['informations']} informations créées")

                # 4b. Créer les InformationMVP + ClaimKey (MVP V1)
                claimkeys_created = set()
                for info_mvp in result.informations_mvp:
                    # Créer le ClaimKey si nécessaire (MERGE évite duplicata)
                    if info_mvp.claimkey_id and info_mvp.claimkey_id not in claimkeys_created:
                        session.execute_write(
                            self._create_claimkey_tx,
                            info_mvp.claimkey_id,
                            self.tenant_id
                        )
                        claimkeys_created.add(info_mvp.claimkey_id)
                        stats["claimkeys"] += 1

                    # Créer InformationMVP + relation ANSWERS
                    session.execute_write(
                        self._create_information_mvp_tx,
                        info_mvp,
                        result.doc.doc_id,
                        self.tenant_id
                    )
                    stats["informations_mvp"] += 1
                    if info_mvp.claimkey_id:
                        stats["relations"] += 1  # ANSWERS

                logger.info(
                    f"[OSMOSE:Pass1:Persist] {stats['informations_mvp']} InformationMVP créées, "
                    f"{stats['claimkeys']} ClaimKeys"
                )

                # 5. Créer les AssertionLog
                for log_entry in result.assertion_log:
                    session.execute_write(
                        self._create_assertion_log_tx,
                        result.doc.doc_id,
                        log_entry,
                        self.tenant_id
                    )
                    stats["assertion_logs"] += 1
                logger.info(f"[OSMOSE:Pass1:Persist] {stats['assertion_logs']} assertion logs créés")

            except Exception as e:
                logger.error(f"[OSMOSE:Pass1:Persist] Erreur: {e}")
                raise

        return stats

    @staticmethod
    def _create_subject_tx(tx, doc_id: str, subject: Subject, tenant_id: str):
        """Transaction: créer Subject et lier au Document."""
        query = """
        MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
        MERGE (s:Subject {subject_id: $subject_id, tenant_id: $tenant_id})
        SET s.name = $name,
            s.text = $text,
            s.structure = $structure,
            s.language = $language,
            s.justification = $justification,
            s.created_at = datetime()
        MERGE (d)-[:HAS_SUBJECT]->(s)
        RETURN s.subject_id AS id
        """
        tx.run(query, {
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "subject_id": subject.subject_id,
            "name": subject.name,
            "text": subject.text,
            "structure": subject.structure.value,
            "language": subject.language,
            "justification": subject.justification,
        })

    @staticmethod
    def _create_theme_tx(tx, subject_id: str, theme: Theme, tenant_id: str):
        """Transaction: créer Theme et lier au Subject."""
        query = """
        MATCH (s:Subject {subject_id: $subject_id, tenant_id: $tenant_id})
        MERGE (t:Theme {theme_id: $theme_id, tenant_id: $tenant_id})
        SET t.name = $name,
            t.created_at = datetime()
        MERGE (s)-[:HAS_THEME]->(t)
        """
        tx.run(query, {
            "subject_id": subject_id,
            "tenant_id": tenant_id,
            "theme_id": theme.theme_id,
            "name": theme.name,
        })

        # Créer SCOPED_TO vers les sections si spécifié
        if theme.scoped_to_sections:
            for section_id in theme.scoped_to_sections:
                scope_query = """
                MATCH (t:Theme {theme_id: $theme_id, tenant_id: $tenant_id})
                MATCH (sec:Section {section_id: $section_id, tenant_id: $tenant_id})
                MERGE (t)-[:SCOPED_TO]->(sec)
                """
                tx.run(scope_query, {
                    "theme_id": theme.theme_id,
                    "section_id": section_id,
                    "tenant_id": tenant_id,
                })

    @staticmethod
    def _create_concept_tx(tx, concept: Concept, tenant_id: str):
        """Transaction: créer Concept et lier au Theme."""
        query = """
        MATCH (t:Theme {theme_id: $theme_id, tenant_id: $tenant_id})
        MERGE (c:Concept {concept_id: $concept_id, tenant_id: $tenant_id})
        SET c.name = $name,
            c.definition = $definition,
            c.role = $role,
            c.variants = $variants,
            c.lex_key = $lex_key,
            c.created_at = datetime()
        MERGE (t)-[:HAS_CONCEPT]->(c)
        """
        tx.run(query, {
            "theme_id": concept.theme_id,
            "tenant_id": tenant_id,
            "concept_id": concept.concept_id,
            "name": concept.name,
            "definition": concept.definition,
            "role": concept.role.value,
            "variants": concept.variants,
            "lex_key": concept.lex_key,
        })

    @staticmethod
    def _create_information_tx(tx, info: Information, tenant_id: str):
        """Transaction: créer Information avec ANCHORED_IN → DocItem."""
        # Extraire l'item_id de la partie finale du docitem_id composé
        # Format: "tenant:doc_id:item_id" → on veut la partie après le 2e ":"
        docitem_id = info.anchor.docitem_id
        parts = docitem_id.split(":", 2)  # Max 2 splits (tenant:doc_id:item_id)
        item_id = parts[2] if len(parts) >= 3 else docitem_id

        query = """
        MATCH (c:Concept {concept_id: $concept_id, tenant_id: $tenant_id})
        MATCH (di:DocItem {item_id: $item_id, tenant_id: $tenant_id})
        MERGE (i:Information {info_id: $info_id, tenant_id: $tenant_id})
        SET i.text = $text,
            i.type = $type,
            i.confidence = $confidence,
            i.docitem_id = $docitem_id,
            i.created_at = datetime()
        MERGE (c)-[:HAS_INFORMATION]->(i)
        MERGE (i)-[:ANCHORED_IN {span_start: $span_start, span_end: $span_end}]->(di)
        """
        tx.run(query, {
            "concept_id": info.concept_id,
            "tenant_id": tenant_id,
            "item_id": item_id,
            "docitem_id": docitem_id,  # Garder le full ID comme propriété
            "info_id": info.info_id,
            "text": info.text,
            "type": info.type.value,
            "confidence": info.confidence,
            "span_start": info.anchor.span_start,
            "span_end": info.anchor.span_end,
        })

    @staticmethod
    def _create_assertion_log_tx(tx, doc_id: str, entry: AssertionLogEntry, tenant_id: str):
        """Transaction: créer AssertionLog et lier au Document."""
        query = """
        MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
        CREATE (a:AssertionLog {
            assertion_id: $assertion_id,
            tenant_id: $tenant_id,
            text: $text,
            type: $type,
            confidence: $confidence,
            status: $status,
            reason: $reason,
            concept_id: $concept_id,
            created_at: datetime()
        })
        CREATE (a)-[:LOGGED_FOR]->(d)
        """
        tx.run(query, {
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "assertion_id": entry.assertion_id,
            "text": entry.text,
            "type": entry.type.value,
            "confidence": entry.confidence,
            "status": entry.status.value,
            "reason": entry.reason.value,
            "concept_id": entry.concept_id,
        })

    @staticmethod
    def _create_claimkey_tx(tx, claimkey_id: str, tenant_id: str):
        """Transaction: créer ClaimKey (MERGE pour éviter duplicata)."""
        # Extraire la clé depuis l'ID (ck_xxx → xxx)
        key = claimkey_id.replace("ck_", "") if claimkey_id.startswith("ck_") else claimkey_id

        query = """
        MERGE (ck:ClaimKey {claimkey_id: $claimkey_id, tenant_id: $tenant_id})
        ON CREATE SET
            ck.key = $key,
            ck.created_at = datetime()
        """
        tx.run(query, {
            "claimkey_id": claimkey_id,
            "tenant_id": tenant_id,
            "key": key,
        })

    @staticmethod
    def _create_information_mvp_tx(tx, info_mvp: InformationMVP, doc_id: str, tenant_id: str):
        """Transaction: créer InformationMVP avec relation ANSWERS vers ClaimKey."""
        # Utiliser to_neo4j_properties() pour obtenir toutes les propriétés
        props = info_mvp.to_neo4j_properties()

        # Requête de base pour créer InformationMVP
        if info_mvp.claimkey_id:
            # Avec lien vers ClaimKey
            query = """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
            MATCH (ck:ClaimKey {claimkey_id: $claimkey_id, tenant_id: $tenant_id})
            CREATE (i:InformationMVP {
                information_id: $information_id,
                tenant_id: $tenant_id,
                document_id: $document_id,
                text: $text,
                exact_quote: $exact_quote,
                type: $type,
                rhetorical_role: $rhetorical_role,
                span_page: $span_page,
                value_kind: $value_kind,
                value_raw: $value_raw,
                value_normalized: $value_normalized,
                value_unit: $value_unit,
                value_operator: $value_operator,
                context_edition: $context_edition,
                context_region: $context_region,
                context_product: $context_product,
                promotion_status: $promotion_status,
                claimkey_id: $claimkey_id,
                fingerprint: $fingerprint,
                confidence: $confidence,
                language: $language,
                created_at: datetime()
            })
            CREATE (i)-[:EXTRACTED_FROM]->(d)
            CREATE (i)-[:ANSWERS]->(ck)
            """
        else:
            # Sans lien vers ClaimKey (PROMOTED_UNLINKED)
            query = """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
            CREATE (i:InformationMVP {
                information_id: $information_id,
                tenant_id: $tenant_id,
                document_id: $document_id,
                text: $text,
                exact_quote: $exact_quote,
                type: $type,
                rhetorical_role: $rhetorical_role,
                span_page: $span_page,
                value_kind: $value_kind,
                value_raw: $value_raw,
                value_normalized: $value_normalized,
                value_unit: $value_unit,
                value_operator: $value_operator,
                context_edition: $context_edition,
                context_region: $context_region,
                context_product: $context_product,
                promotion_status: $promotion_status,
                fingerprint: $fingerprint,
                confidence: $confidence,
                language: $language,
                created_at: datetime()
            })
            CREATE (i)-[:EXTRACTED_FROM]->(d)
            """

        tx.run(query, {
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "information_id": props["information_id"],
            "document_id": props["document_id"],
            "text": props["text"],
            "exact_quote": props["exact_quote"],
            "type": props["type"],
            "rhetorical_role": props["rhetorical_role"],
            "span_page": props["span_page"],
            "value_kind": props["value_kind"],
            "value_raw": props["value_raw"],
            "value_normalized": props["value_normalized"],
            "value_unit": props["value_unit"],
            "value_operator": props["value_operator"],
            "context_edition": props["context_edition"],
            "context_region": props["context_region"],
            "context_product": props["context_product"],
            "promotion_status": props["promotion_status"],
            "claimkey_id": props["claimkey_id"],
            "fingerprint": props["fingerprint"],
            "confidence": props["confidence"],
            "language": props["language"],
        })

    def delete_pass1_data(self, doc_id: str) -> int:
        """
        Supprime les données Pass 1 pour un document.

        Utile pour réexécuter Pass 1 sur un document.
        """
        if not self.driver:
            return 0

        with self.driver.session() as session:
            result = session.execute_write(
                self._delete_pass1_data_tx,
                doc_id,
                self.tenant_id
            )
            return result

    @staticmethod
    def _delete_pass1_data_tx(tx, doc_id: str, tenant_id: str) -> int:
        """Transaction: supprimer données Pass 1."""
        # Supprimer dans l'ordre inverse des dépendances
        queries = [
            # AssertionLog
            """
            MATCH (a:AssertionLog)-[:LOGGED_FOR]->(d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
            DETACH DELETE a
            """,
            # Information
            """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})-[:HAS_SUBJECT]->(:Subject)-[:HAS_THEME]->(:Theme)-[:HAS_CONCEPT]->(:Concept)-[:HAS_INFORMATION]->(i:Information)
            DETACH DELETE i
            """,
            # Concept
            """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})-[:HAS_SUBJECT]->(:Subject)-[:HAS_THEME]->(:Theme)-[:HAS_CONCEPT]->(c:Concept)
            DETACH DELETE c
            """,
            # Theme
            """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})-[:HAS_SUBJECT]->(:Subject)-[:HAS_THEME]->(t:Theme)
            DETACH DELETE t
            """,
            # Subject
            """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})-[:HAS_SUBJECT]->(s:Subject)
            DETACH DELETE s
            """,
        ]

        total_deleted = 0
        for query in queries:
            result = tx.run(query, {"doc_id": doc_id, "tenant_id": tenant_id})
            summary = result.consume()
            total_deleted += summary.counters.nodes_deleted

        return total_deleted


def persist_pass1_result(
    result: Pass1Result,
    neo4j_driver=None,
    tenant_id: str = "default"
) -> Dict[str, int]:
    """
    Fonction utilitaire pour persister un Pass1Result.

    Args:
        result: Résultat Pass 1
        neo4j_driver: Driver Neo4j
        tenant_id: Identifiant du tenant

    Returns:
        Dict avec compteurs
    """
    persister = Pass1PersisterV2(neo4j_driver=neo4j_driver, tenant_id=tenant_id)
    return persister.persist(result)
