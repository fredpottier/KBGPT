"""
OSMOSE - NormativeWriter

Persiste les NormativeRule et SpecFact dans Neo4j.

Ces entités sont NON-TRAVERSABLES (pas de graph walk) mais:
- Indexables (recherche par attribut, modalité, valeur)
- Filtrables par scope (doc.topic, section.scope)
- Requêtables via API
- Citables (evidence traçable)

ADR: doc/ongoing/ADR_NORMATIVE_RULES_SPEC_FACTS.md

Author: Claude Code
Date: 2026-01-22
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from .types import (
    NormativeRule,
    SpecFact,
    dedup_key_rule,
    dedup_key_fact,
)

logger = logging.getLogger(__name__)


@dataclass
class NormativeWriteStats:
    """Statistiques d'écriture normative."""

    rules_written: int = 0
    rules_deduplicated: int = 0
    facts_written: int = 0
    facts_deduplicated: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def total_written(self) -> int:
        return self.rules_written + self.facts_written

    @property
    def total_deduplicated(self) -> int:
        return self.rules_deduplicated + self.facts_deduplicated


class NormativeWriter:
    """
    Writer pour persister NormativeRule et SpecFact dans Neo4j.

    Gère:
    - Création des nœuds NormativeRule et SpecFact
    - Déduplication via clé canonique
    - Liens vers DocumentContext via scope_anchors
    - Indexation pour recherche rapide

    Usage:
        writer = NormativeWriter(neo4j_client, tenant_id="default")
        stats = writer.write_rules(rules)
        stats = writer.write_facts(facts)
    """

    VERSION = "v1.0.0"

    def __init__(
        self,
        neo4j_client,
        tenant_id: str = "default",
    ):
        """
        Initialise le writer.

        Args:
            neo4j_client: Client Neo4j connecté
            tenant_id: ID tenant
        """
        self.neo4j_client = neo4j_client
        self.tenant_id = tenant_id
        self._ensure_constraints()

    def _ensure_constraints(self):
        """Crée les contraintes et index Neo4j si nécessaire."""
        constraints = [
            # Contrainte unique pour NormativeRule
            """
            CREATE CONSTRAINT normative_rule_id IF NOT EXISTS
            FOR (n:NormativeRule) REQUIRE n.rule_id IS UNIQUE
            """,
            # Contrainte unique pour SpecFact
            """
            CREATE CONSTRAINT spec_fact_id IF NOT EXISTS
            FOR (f:SpecFact) REQUIRE f.fact_id IS UNIQUE
            """,
            # Index pour recherche par clé de dédup
            """
            CREATE INDEX normative_rule_dedup IF NOT EXISTS
            FOR (n:NormativeRule) ON (n.dedup_key, n.tenant_id)
            """,
            """
            CREATE INDEX spec_fact_dedup IF NOT EXISTS
            FOR (f:SpecFact) ON (f.dedup_key, f.tenant_id)
            """,
            # Index pour recherche par document
            """
            CREATE INDEX normative_rule_doc IF NOT EXISTS
            FOR (n:NormativeRule) ON (n.source_doc_id, n.tenant_id)
            """,
            """
            CREATE INDEX spec_fact_doc IF NOT EXISTS
            FOR (f:SpecFact) ON (f.source_doc_id, f.tenant_id)
            """,
            # Index pour recherche par modalité (NormativeRule)
            """
            CREATE INDEX normative_rule_modality IF NOT EXISTS
            FOR (n:NormativeRule) ON (n.modality, n.tenant_id)
            """,
            # Index pour recherche par attribut (SpecFact)
            """
            CREATE INDEX spec_fact_attribute IF NOT EXISTS
            FOR (f:SpecFact) ON (f.attribute_name, f.tenant_id)
            """,
        ]

        try:
            with self.neo4j_client.driver.session(database="neo4j") as session:
                for constraint in constraints:
                    try:
                        session.run(constraint)
                    except Exception as e:
                        # Ignorer si contrainte existe déjà
                        if "already exists" not in str(e).lower():
                            logger.warning(f"[NormativeWriter] Constraint error: {e}")
        except Exception as e:
            logger.warning(f"[NormativeWriter] Could not create constraints: {e}")

    def write_rules(self, rules: List[NormativeRule]) -> NormativeWriteStats:
        """
        Persiste une liste de NormativeRule dans Neo4j.

        Utilise MERGE avec dedup_key pour éviter les doublons.

        Args:
            rules: Liste de règles à persister

        Returns:
            NormativeWriteStats avec résultats
        """
        stats = NormativeWriteStats()

        if not rules:
            return stats

        query = """
        UNWIND $rules AS rule
        MERGE (n:NormativeRule {dedup_key: rule.dedup_key, tenant_id: rule.tenant_id})
        ON CREATE SET
            n.rule_id = rule.rule_id,
            n.subject_text = rule.subject_text,
            n.subject_concept_id = rule.subject_concept_id,
            n.modality = rule.modality,
            n.constraint_type = rule.constraint_type,
            n.constraint_value = rule.constraint_value,
            n.constraint_unit = rule.constraint_unit,
            n.constraint_condition_span = rule.constraint_condition_span,
            n.evidence_span = rule.evidence_span,
            n.evidence_section = rule.evidence_section,
            n.source_doc_id = rule.source_doc_id,
            n.source_chunk_id = rule.source_chunk_id,
            n.source_segment_id = rule.source_segment_id,
            n.extraction_method = rule.extraction_method,
            n.confidence = rule.confidence,
            n.extractor_version = rule.extractor_version,
            n.created_at = datetime(),
            n.doc_coverage = 1,
            n.section_coverage = 1,
            n.raw_rule_ids = [rule.rule_id]
        ON MATCH SET
            n.doc_coverage = n.doc_coverage + 1,
            n.raw_rule_ids = n.raw_rule_ids + rule.rule_id,
            n.updated_at = datetime()
        RETURN n.rule_id AS rule_id,
               CASE WHEN n.doc_coverage = 1 THEN 'created' ELSE 'merged' END AS status
        """

        try:
            # Préparer les données
            # Note: Les enums str,Enum de Pydantic peuvent être des strings ou des enums
            def enum_value(e):
                """Extrait la valeur string d'un enum ou retourne le string directement."""
                return e.value if hasattr(e, "value") else str(e)

            rule_data = []
            for rule in rules:
                rule_dict = {
                    "rule_id": rule.rule_id,
                    "tenant_id": rule.tenant_id,
                    "dedup_key": dedup_key_rule(rule),
                    "subject_text": rule.subject_text,
                    "subject_concept_id": rule.subject_concept_id,
                    "modality": enum_value(rule.modality),
                    "constraint_type": enum_value(rule.constraint_type),
                    "constraint_value": rule.constraint_value,
                    "constraint_unit": rule.constraint_unit,
                    "constraint_condition_span": rule.constraint_condition_span,
                    "evidence_span": rule.evidence_span,
                    "evidence_section": rule.evidence_section,
                    "source_doc_id": rule.source_doc_id,
                    "source_chunk_id": rule.source_chunk_id,
                    "source_segment_id": rule.source_segment_id,
                    "extraction_method": enum_value(rule.extraction_method),
                    "confidence": rule.confidence,
                    "extractor_version": rule.extractor_version,
                }
                rule_data.append(rule_dict)

            with self.neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(query, rules=rule_data)
                for record in result:
                    if record["status"] == "created":
                        stats.rules_written += 1
                    else:
                        stats.rules_deduplicated += 1

            logger.info(
                f"[NormativeWriter] Wrote {stats.rules_written} rules, "
                f"deduplicated {stats.rules_deduplicated}"
            )

        except Exception as e:
            logger.error(f"[NormativeWriter] Error writing rules: {e}")
            stats.errors.append(str(e))

        return stats

    def write_facts(self, facts: List[SpecFact]) -> NormativeWriteStats:
        """
        Persiste une liste de SpecFact dans Neo4j.

        Utilise MERGE avec dedup_key pour éviter les doublons.

        Args:
            facts: Liste de facts à persister

        Returns:
            NormativeWriteStats avec résultats
        """
        stats = NormativeWriteStats()

        if not facts:
            return stats

        query = """
        UNWIND $facts AS fact
        MERGE (f:SpecFact {dedup_key: fact.dedup_key, tenant_id: fact.tenant_id})
        ON CREATE SET
            f.fact_id = fact.fact_id,
            f.attribute_name = fact.attribute_name,
            f.attribute_concept_id = fact.attribute_concept_id,
            f.spec_type = fact.spec_type,
            f.value = fact.value,
            f.value_numeric = fact.value_numeric,
            f.unit = fact.unit,
            f.source_structure = fact.source_structure,
            f.structure_context = fact.structure_context,
            f.row_header = fact.row_header,
            f.column_header = fact.column_header,
            f.evidence_text = fact.evidence_text,
            f.evidence_section = fact.evidence_section,
            f.source_doc_id = fact.source_doc_id,
            f.source_chunk_id = fact.source_chunk_id,
            f.source_segment_id = fact.source_segment_id,
            f.extraction_method = fact.extraction_method,
            f.confidence = fact.confidence,
            f.extractor_version = fact.extractor_version,
            f.created_at = datetime(),
            f.doc_coverage = 1,
            f.section_coverage = 1,
            f.raw_fact_ids = [fact.fact_id]
        ON MATCH SET
            f.doc_coverage = f.doc_coverage + 1,
            f.raw_fact_ids = f.raw_fact_ids + fact.fact_id,
            f.updated_at = datetime()
        RETURN f.fact_id AS fact_id,
               CASE WHEN f.doc_coverage = 1 THEN 'created' ELSE 'merged' END AS status
        """

        try:
            # Préparer les données
            # Note: Les enums str,Enum de Pydantic peuvent être des strings ou des enums
            def enum_value(e):
                """Extrait la valeur string d'un enum ou retourne le string directement."""
                return e.value if hasattr(e, "value") else str(e)

            fact_data = []
            for fact in facts:
                fact_dict = {
                    "fact_id": fact.fact_id,
                    "tenant_id": fact.tenant_id,
                    "dedup_key": dedup_key_fact(fact),
                    "attribute_name": fact.attribute_name,
                    "attribute_concept_id": fact.attribute_concept_id,
                    "spec_type": enum_value(fact.spec_type),
                    "value": fact.value,
                    "value_numeric": fact.value_numeric,
                    "unit": fact.unit,
                    "source_structure": enum_value(fact.source_structure),
                    "structure_context": fact.structure_context,
                    "row_header": fact.row_header,
                    "column_header": fact.column_header,
                    "evidence_text": fact.evidence_text,
                    "evidence_section": fact.evidence_section,
                    "source_doc_id": fact.source_doc_id,
                    "source_chunk_id": fact.source_chunk_id,
                    "source_segment_id": fact.source_segment_id,
                    "extraction_method": enum_value(fact.extraction_method),
                    "confidence": fact.confidence,
                    "extractor_version": fact.extractor_version,
                }
                fact_data.append(fact_dict)

            with self.neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(query, facts=fact_data)
                for record in result:
                    if record["status"] == "created":
                        stats.facts_written += 1
                    else:
                        stats.facts_deduplicated += 1

            logger.info(
                f"[NormativeWriter] Wrote {stats.facts_written} facts, "
                f"deduplicated {stats.facts_deduplicated}"
            )

        except Exception as e:
            logger.error(f"[NormativeWriter] Error writing facts: {e}")
            stats.errors.append(str(e))

        return stats

    def link_to_document(self, doc_id: str) -> int:
        """
        Crée les relations EXTRACTED_FROM entre rules/facts et le document.

        Args:
            doc_id: ID du document

        Returns:
            Nombre de liens créés
        """
        query = """
        // Lier les NormativeRule au document
        MATCH (n:NormativeRule {source_doc_id: $doc_id, tenant_id: $tenant_id})
        MATCH (d:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
        MERGE (n)-[r:EXTRACTED_FROM]->(d)
        ON CREATE SET r.created_at = datetime()
        WITH count(r) AS rule_links

        // Lier les SpecFact au document
        MATCH (f:SpecFact {source_doc_id: $doc_id, tenant_id: $tenant_id})
        MATCH (d:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
        MERGE (f)-[r:EXTRACTED_FROM]->(d)
        ON CREATE SET r.created_at = datetime()

        RETURN rule_links + count(r) AS total_links
        """

        try:
            with self.neo4j_client.driver.session(database="neo4j") as session:
                result = session.run(
                    query, doc_id=doc_id, tenant_id=self.tenant_id
                )
                record = result.single()
                return record["total_links"] if record else 0

        except Exception as e:
            logger.warning(f"[NormativeWriter] Error linking to document: {e}")
            return 0


# =============================================================================
# Factory
# =============================================================================

_writer_cache: Dict[str, NormativeWriter] = {}


def get_normative_writer(
    neo4j_client,
    tenant_id: str = "default",
) -> NormativeWriter:
    """
    Factory pour obtenir une instance de NormativeWriter.

    Args:
        neo4j_client: Client Neo4j connecté
        tenant_id: ID tenant

    Returns:
        NormativeWriter instance
    """
    cache_key = f"{tenant_id}"

    if cache_key not in _writer_cache:
        _writer_cache[cache_key] = NormativeWriter(
            neo4j_client=neo4j_client,
            tenant_id=tenant_id,
        )

    return _writer_cache[cache_key]
