# src/knowbase/claimfirst/persistence/neo4j_schema.py
"""
Schéma Neo4j pour le pipeline Claim-First.

Définit les contraintes, indexes et labels pour le graphe de claims.

Architecture (CHEMIN CANONIQUE - INV-8 CORRECTIF 6 + PATCH C + CHANTIER 0):

    # CHEMIN CANONIQUE (seul officiel, ne jamais en créer d'autre)
    (Document)-[:HAS_CONTEXT]->(DocumentContext)-[:ABOUT_SUBJECT]->(SubjectAnchor)
    # Passages migrés comme propriétés sur Claim (Chantier 0 Phase 1A)
    # Claim.passage_text, .section_title, .page_no, .passage_char_start, .passage_char_end

    # SHORTCUT UNIQUE autorisé (pour perf query)
    (Claim)-[:IN_DOCUMENT]->(Document)

    # Relations additionnelles
    (Claim)-[:ABOUT]->(Entity)            # Claim parle de Entity (pas de role V1)
    (Claim)-[:HAS_FACET]->(Facet)         # Claim catégorisée par Facet
    (Claim)-[:IN_CLUSTER]->(ClaimCluster) # Claim membre de Cluster
    (Claim)-[:CONTRADICTS]->(Claim)       # Claims incompatibles
    (Claim)-[:REFINES]->(Claim)           # Claim A précise Claim B
    (Claim)-[:QUALIFIES]->(Claim)         # Claim A conditionne Claim B

    # Équivalence possible (non confirmée) - INV-9
    (SubjectAnchor)-[:POSSIBLE_EQUIVALENT]->(SubjectAnchor)

INV-2: Direction des relations = de l'objet détaillé vers l'objet englobant/catégoriel.
INV-8: Scope appartient au Document via DocumentContext, pas à la Claim.
INV-9: Résolution conservative des sujets (SubjectAnchor avec aliases typés).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SchemaConstraint:
    """Définition d'une contrainte Neo4j."""
    name: str
    label: str
    property_key: str
    constraint_type: str = "UNIQUE"  # UNIQUE, EXISTS, etc.

    def to_cypher(self) -> str:
        """Génère le Cypher pour créer la contrainte."""
        if self.constraint_type == "UNIQUE":
            return (
                f"CREATE CONSTRAINT {self.name} IF NOT EXISTS "
                f"FOR (n:{self.label}) REQUIRE n.{self.property_key} IS UNIQUE"
            )
        elif self.constraint_type == "NODE_KEY":
            return (
                f"CREATE CONSTRAINT {self.name} IF NOT EXISTS "
                f"FOR (n:{self.label}) REQUIRE (n.{self.property_key}) IS NODE KEY"
            )
        else:
            raise ValueError(f"Unsupported constraint type: {self.constraint_type}")


@dataclass
class SchemaIndex:
    """Définition d'un index Neo4j."""
    name: str
    label: str
    property_keys: List[str]
    index_type: str = "BTREE"  # BTREE, TEXT, FULLTEXT

    def to_cypher(self) -> str:
        """Génère le Cypher pour créer l'index."""
        props = ", ".join(f"n.{k}" for k in self.property_keys)
        if self.index_type == "FULLTEXT":
            return (
                f"CREATE FULLTEXT INDEX {self.name} IF NOT EXISTS "
                f"FOR (n:{self.label}) ON EACH [{props}]"
            )
        else:
            return (
                f"CREATE INDEX {self.name} IF NOT EXISTS "
                f"FOR (n:{self.label}) ON ({props})"
            )


@dataclass
class ClaimFirstSchema:
    """
    Schéma complet pour le pipeline Claim-First.

    Définit tous les labels, contraintes et indexes nécessaires.
    """

    # Labels des nœuds
    # Note: Passage retiré (Chantier 0 Phase 1A — données migrées sur Claim)
    LABELS = [
        "Claim",
        "Entity",
        "Facet",
        "ClaimCluster",
        "Document",           # Réutilisé depuis le schéma existant
        "SubjectAnchor",      # INV-9: Sujet canonique avec aliases typés
        "DocumentContext",    # INV-8: Contexte d'applicabilité du document
        "ApplicabilityAxis",  # INV-12/14/25: Axe d'applicabilité
        "ComparableSubject",  # INV-25: Sujet stable comparable entre documents
    ]

    # Types de relations
    # Note: FROM et SUPPORTED_BY retirés (Chantier 0 Phase 1A)
    RELATION_TYPES = [
        "ABOUT",             # Claim → Entity (pas de role V1, INV-4)
        "HAS_FACET",         # Claim → Facet
        "IN_CLUSTER",        # Claim → ClaimCluster
        "IN_DOCUMENT",       # Claim → Document (SHORTCUT UNIQUE - INV-8 PATCH C)
        "CONTRADICTS",       # Claim → Claim
        "REFINES",           # Claim → Claim
        "QUALIFIES",         # Claim → Claim
        "HAS_CONTEXT",       # Document → DocumentContext (INV-8)
        "ABOUT_SUBJECT",     # DocumentContext → SubjectAnchor (INV-8) - topics secondaires
        "ABOUT_COMPARABLE",  # DocumentContext → ComparableSubject (INV-25) - sujet stable
        "POSSIBLE_EQUIVALENT",  # SubjectAnchor → SubjectAnchor (INV-9)
        "HAS_AXIS_VALUE",    # DocumentContext → ApplicabilityAxis (INV-26)
    ]

    # Contraintes (unicité)
    # Note: passage_unique retiré (Chantier 0 Phase 1A)
    constraints: List[SchemaConstraint] = field(default_factory=lambda: [
        # Claim: unique par (claim_id, tenant_id)
        SchemaConstraint(
            name="claim_unique",
            label="Claim",
            property_key="claim_id",
            constraint_type="UNIQUE"
        ),

        # Entity: unique par (entity_id, tenant_id)
        SchemaConstraint(
            name="entity_claimfirst_unique",
            label="Entity",
            property_key="entity_id",
            constraint_type="UNIQUE"
        ),

        # Facet: unique par facet_id
        SchemaConstraint(
            name="facet_unique",
            label="Facet",
            property_key="facet_id",
            constraint_type="UNIQUE"
        ),

        # ClaimCluster: unique par cluster_id
        SchemaConstraint(
            name="claimcluster_unique",
            label="ClaimCluster",
            property_key="cluster_id",
            constraint_type="UNIQUE"
        ),

        # SubjectAnchor: unique par subject_id (INV-9)
        SchemaConstraint(
            name="subject_anchor_unique",
            label="SubjectAnchor",
            property_key="subject_id",
            constraint_type="UNIQUE"
        ),

        # DocumentContext: unique par doc_id (INV-8)
        SchemaConstraint(
            name="doc_context_unique",
            label="DocumentContext",
            property_key="doc_id",
            constraint_type="UNIQUE"
        ),

        # ApplicabilityAxis: unique par axis_id (INV-12/14/25)
        SchemaConstraint(
            name="axis_id_unique",
            label="ApplicabilityAxis",
            property_key="axis_id",
            constraint_type="UNIQUE"
        ),

        # ComparableSubject: unique par subject_id (INV-25)
        SchemaConstraint(
            name="comparable_subject_unique",
            label="ComparableSubject",
            property_key="subject_id",
            constraint_type="UNIQUE"
        ),
    ])

    # Indexes pour les requêtes fréquentes
    indexes: List[SchemaIndex] = field(default_factory=lambda: [
        # Index sur doc_id pour filtrer par document
        SchemaIndex(
            name="claim_doc",
            label="Claim",
            property_keys=["doc_id"]
        ),
        # Note: passage_doc et passage_tenant retirés (Chantier 0 Phase 1A)

        # Index sur tenant_id pour multi-tenant
        SchemaIndex(
            name="claim_tenant",
            label="Claim",
            property_keys=["tenant_id"]
        ),
        SchemaIndex(
            name="entity_tenant",
            label="Entity",
            property_keys=["tenant_id"]
        ),
        SchemaIndex(
            name="claimcluster_tenant",
            label="ClaimCluster",
            property_keys=["tenant_id"]
        ),

        # Index sur normalized_name pour Entity lookup
        SchemaIndex(
            name="entity_normalized",
            label="Entity",
            property_keys=["normalized_name"]
        ),

        # Index sur domain pour Facet navigation
        SchemaIndex(
            name="facet_domain",
            label="Facet",
            property_keys=["domain"]
        ),

        # Index sur claim_type pour filtrage
        SchemaIndex(
            name="claim_type",
            label="Claim",
            property_keys=["claim_type"]
        ),

        # Index composite pour Claim (doc_id, tenant_id)
        SchemaIndex(
            name="claim_doc_tenant",
            label="Claim",
            property_keys=["doc_id", "tenant_id"]
        ),

        # Index fulltext sur claim.text pour recherche
        SchemaIndex(
            name="claim_text_search",
            label="Claim",
            property_keys=["text"],
            index_type="FULLTEXT"
        ),

        # Index fulltext sur entity.name pour recherche
        SchemaIndex(
            name="entity_name_search",
            label="Entity",
            property_keys=["name"],
            index_type="FULLTEXT"
        ),

        # ==== INV-8/INV-9: SubjectAnchor et DocumentContext ====

        # Index sur canonical_name pour SubjectAnchor lookup
        SchemaIndex(
            name="subject_canonical",
            label="SubjectAnchor",
            property_keys=["canonical_name"]
        ),

        # Index sur tenant_id pour SubjectAnchor multi-tenant
        SchemaIndex(
            name="subject_tenant",
            label="SubjectAnchor",
            property_keys=["tenant_id"]
        ),

        # Index fulltext sur aliases_explicit pour recherche de sujets
        SchemaIndex(
            name="subject_aliases_search",
            label="SubjectAnchor",
            property_keys=["aliases_explicit"],
            index_type="FULLTEXT"
        ),

        # Index sur doc_id pour DocumentContext lookup
        SchemaIndex(
            name="doccontext_doc",
            label="DocumentContext",
            property_keys=["doc_id"]
        ),

        # Index sur tenant_id pour DocumentContext multi-tenant
        SchemaIndex(
            name="doccontext_tenant",
            label="DocumentContext",
            property_keys=["tenant_id"]
        ),

        # Index sur resolution_status pour filtrage
        SchemaIndex(
            name="doccontext_status",
            label="DocumentContext",
            property_keys=["resolution_status"]
        ),

        # ==== INV-12/14/25/26: ApplicabilityAxis ====

        # Index sur axis_key pour ApplicabilityAxis lookup
        SchemaIndex(
            name="axis_key_idx",
            label="ApplicabilityAxis",
            property_keys=["tenant_id", "axis_key"]
        ),

        # Index sur tenant_id pour ApplicabilityAxis multi-tenant
        SchemaIndex(
            name="axis_tenant",
            label="ApplicabilityAxis",
            property_keys=["tenant_id"]
        ),

        # Index sur ordering_confidence pour filtrage
        SchemaIndex(
            name="axis_ordering_confidence",
            label="ApplicabilityAxis",
            property_keys=["ordering_confidence"]
        ),

        # ==== INV-25: ComparableSubject ====

        # Index sur canonical_name pour ComparableSubject lookup
        SchemaIndex(
            name="comparable_subject_name",
            label="ComparableSubject",
            property_keys=["canonical_name"]
        ),

        # Index sur tenant_id pour ComparableSubject multi-tenant
        SchemaIndex(
            name="comparable_subject_tenant",
            label="ComparableSubject",
            property_keys=["tenant_id"]
        ),

        # Index composite pour ComparableSubject (tenant_id, canonical_name)
        SchemaIndex(
            name="comparable_subject_tenant_name",
            label="ComparableSubject",
            property_keys=["tenant_id", "canonical_name"]
        ),

        # Index fulltext sur aliases pour recherche de sujets comparables
        SchemaIndex(
            name="comparable_subject_aliases_search",
            label="ComparableSubject",
            property_keys=["aliases"],
            index_type="FULLTEXT"
        ),
    ])


def setup_claimfirst_schema(driver, drop_existing: bool = False) -> dict:
    """
    Configure le schéma Neo4j pour le pipeline Claim-First.

    Args:
        driver: Neo4j driver
        drop_existing: Si True, supprime les contraintes/indexes existants

    Returns:
        Dict avec statistiques de création
    """
    schema = ClaimFirstSchema()
    stats = {
        "constraints_created": 0,
        "constraints_skipped": 0,
        "indexes_created": 0,
        "indexes_skipped": 0,
        "errors": [],
    }

    with driver.session() as session:
        # Optionnel: Drop existing constraints/indexes
        if drop_existing:
            logger.warning("[OSMOSE:ClaimFirst] Dropping existing schema...")
            for constraint in schema.constraints:
                try:
                    session.run(f"DROP CONSTRAINT {constraint.name} IF EXISTS")
                    logger.info(f"  Dropped constraint: {constraint.name}")
                except Exception as e:
                    logger.debug(f"  Could not drop constraint {constraint.name}: {e}")

            for index in schema.indexes:
                try:
                    session.run(f"DROP INDEX {index.name} IF EXISTS")
                    logger.info(f"  Dropped index: {index.name}")
                except Exception as e:
                    logger.debug(f"  Could not drop index {index.name}: {e}")

        # Créer les contraintes
        logger.info("[OSMOSE:ClaimFirst] Creating constraints...")
        for constraint in schema.constraints:
            try:
                cypher = constraint.to_cypher()
                session.run(cypher)
                stats["constraints_created"] += 1
                logger.info(f"  Created constraint: {constraint.name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    stats["constraints_skipped"] += 1
                    logger.debug(f"  Constraint exists: {constraint.name}")
                else:
                    stats["errors"].append(f"Constraint {constraint.name}: {e}")
                    logger.error(f"  Error creating constraint {constraint.name}: {e}")

        # Créer les indexes
        logger.info("[OSMOSE:ClaimFirst] Creating indexes...")
        for index in schema.indexes:
            try:
                cypher = index.to_cypher()
                session.run(cypher)
                stats["indexes_created"] += 1
                logger.info(f"  Created index: {index.name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    stats["indexes_skipped"] += 1
                    logger.debug(f"  Index exists: {index.name}")
                else:
                    stats["errors"].append(f"Index {index.name}: {e}")
                    logger.error(f"  Error creating index {index.name}: {e}")

    logger.info(
        f"[OSMOSE:ClaimFirst] Schema setup complete: "
        f"{stats['constraints_created']} constraints, "
        f"{stats['indexes_created']} indexes created"
    )

    return stats


def verify_claimfirst_schema(driver) -> dict:
    """
    Vérifie que le schéma Claim-First est correctement configuré.

    Args:
        driver: Neo4j driver

    Returns:
        Dict avec statut de vérification
    """
    schema = ClaimFirstSchema()
    result = {
        "valid": True,
        "missing_constraints": [],
        "missing_indexes": [],
        "existing_constraints": [],
        "existing_indexes": [],
    }

    with driver.session() as session:
        # Vérifier les contraintes
        constraints_result = session.run("SHOW CONSTRAINTS")
        existing_constraints = {r["name"] for r in constraints_result}

        for constraint in schema.constraints:
            if constraint.name in existing_constraints:
                result["existing_constraints"].append(constraint.name)
            else:
                result["missing_constraints"].append(constraint.name)
                result["valid"] = False

        # Vérifier les indexes
        indexes_result = session.run("SHOW INDEXES")
        existing_indexes = {r["name"] for r in indexes_result}

        for index in schema.indexes:
            if index.name in existing_indexes:
                result["existing_indexes"].append(index.name)
            else:
                result["missing_indexes"].append(index.name)
                result["valid"] = False

    if result["valid"]:
        logger.info("[OSMOSE:ClaimFirst] Schema verification: VALID")
    else:
        logger.warning(
            f"[OSMOSE:ClaimFirst] Schema verification: INVALID - "
            f"missing {len(result['missing_constraints'])} constraints, "
            f"{len(result['missing_indexes'])} indexes"
        )

    return result


def get_cleanup_queries(tenant_id: str) -> List[str]:
    """
    Génère les requêtes Cypher pour nettoyer les données d'un tenant.

    ATTENTION: Ces requêtes suppriment des données!

    Args:
        tenant_id: Tenant ID à nettoyer

    Returns:
        Liste de requêtes Cypher
    """
    return [
        # Supprimer les relations d'abord
        # Note: SUPPORTED_BY et FROM retirés (Chantier 0 Phase 1A)
        f"""
        MATCH (c:Claim {{tenant_id: '{tenant_id}'}})-[r:ABOUT|HAS_FACET|IN_CLUSTER|IN_DOCUMENT|CONTRADICTS|REFINES|QUALIFIES]->()
        DELETE r
        """,
        # INV-8/INV-9: Relations DocumentContext et SubjectAnchor
        f"""
        MATCH (dc:DocumentContext {{tenant_id: '{tenant_id}'}})-[r:ABOUT_SUBJECT]->()
        DELETE r
        """,
        f"""
        MATCH ()-[r:HAS_CONTEXT]->(dc:DocumentContext {{tenant_id: '{tenant_id}'}})
        DELETE r
        """,
        f"""
        MATCH (sa:SubjectAnchor {{tenant_id: '{tenant_id}'}})-[r:POSSIBLE_EQUIVALENT]->()
        DELETE r
        """,
        # INV-26: Relations HAS_AXIS_VALUE
        f"""
        MATCH (dc:DocumentContext {{tenant_id: '{tenant_id}'}})-[r:HAS_AXIS_VALUE]->()
        DELETE r
        """,
        # INV-25: Relations ABOUT_COMPARABLE
        f"""
        MATCH (dc:DocumentContext {{tenant_id: '{tenant_id}'}})-[r:ABOUT_COMPARABLE]->()
        DELETE r
        """,
        # Puis les nœuds
        # Note: Passage retiré (Chantier 0 Phase 1A)
        f"MATCH (c:Claim {{tenant_id: '{tenant_id}'}}) DELETE c",
        f"MATCH (e:Entity {{tenant_id: '{tenant_id}'}}) DELETE e",
        f"MATCH (f:Facet {{tenant_id: '{tenant_id}'}}) DELETE f",
        f"MATCH (cc:ClaimCluster {{tenant_id: '{tenant_id}'}}) DELETE cc",
        f"MATCH (dc:DocumentContext {{tenant_id: '{tenant_id}'}}) DELETE dc",
        f"MATCH (sa:SubjectAnchor {{tenant_id: '{tenant_id}'}}) DELETE sa",
        f"MATCH (ax:ApplicabilityAxis {{tenant_id: '{tenant_id}'}}) DELETE ax",
        f"MATCH (cs:ComparableSubject {{tenant_id: '{tenant_id}'}}) DELETE cs",
    ]


# Point d'entrée pour exécution directe
if __name__ == "__main__":
    import os
    from neo4j import GraphDatabase

    # Configuration depuis variables d'environnement
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    logging.basicConfig(level=logging.INFO)

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        print("\n=== Setup Claim-First Schema ===\n")
        stats = setup_claimfirst_schema(driver)
        print(f"\nStats: {stats}")

        print("\n=== Verify Schema ===\n")
        verify = verify_claimfirst_schema(driver)
        print(f"\nVerification: {verify}")
    finally:
        driver.close()


__all__ = [
    "ClaimFirstSchema",
    "SchemaConstraint",
    "SchemaIndex",
    "setup_claimfirst_schema",
    "verify_claimfirst_schema",
    "get_cleanup_queries",
]
