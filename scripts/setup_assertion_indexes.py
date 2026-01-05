#!/usr/bin/env python3
"""
Script de création des index Neo4j pour les diff queries (PR4).

Usage:
    python scripts/setup_assertion_indexes.py

Ou via Docker:
    docker-compose exec app python scripts/setup_assertion_indexes.py

Index créés:
- Document.id (lookup rapide)
- Document.detected_variant (filtrage par variante)
- ProtoConcept.tenant_id (filtrage multi-tenant)
- Marker.value (diff queries optimisées)
- Marker.kind (filtrage par type de marker)

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 7 (PR4)
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.config.settings import get_settings


def create_assertion_indexes():
    """Crée les index Neo4j pour les diff queries."""
    settings = get_settings()

    print("[SETUP] Connecting to Neo4j...")
    client = get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database="neo4j"
    )

    if not client.is_connected():
        print("[ERROR] Cannot connect to Neo4j")
        return False

    indexes = [
        # =====================================================================
        # Document indexes
        # =====================================================================
        {
            "name": "document_id_tenant",
            "query": """
            CREATE INDEX document_id_tenant IF NOT EXISTS
            FOR (d:Document) ON (d.id, d.tenant_id)
            """,
            "description": "Index Document par id+tenant pour lookup rapide"
        },
        {
            "name": "document_variant",
            "query": """
            CREATE INDEX document_variant IF NOT EXISTS
            FOR (d:Document) ON (d.detected_variant)
            """,
            "description": "Index Document par variante détectée"
        },
        {
            "name": "document_scope",
            "query": """
            CREATE INDEX document_scope IF NOT EXISTS
            FOR (d:Document) ON (d.doc_scope)
            """,
            "description": "Index Document par doc_scope"
        },

        # =====================================================================
        # ProtoConcept indexes
        # =====================================================================
        {
            "name": "proto_tenant",
            "query": """
            CREATE INDEX proto_tenant IF NOT EXISTS
            FOR (p:ProtoConcept) ON (p.tenant_id)
            """,
            "description": "Index ProtoConcept par tenant"
        },
        {
            "name": "proto_id_tenant",
            "query": """
            CREATE INDEX proto_id_tenant IF NOT EXISTS
            FOR (p:ProtoConcept) ON (p.concept_id, p.tenant_id)
            """,
            "description": "Index ProtoConcept par id+tenant"
        },

        # =====================================================================
        # Marker indexes (PR3)
        # =====================================================================
        {
            "name": "marker_value_tenant",
            "query": """
            CREATE INDEX marker_value_tenant IF NOT EXISTS
            FOR (m:Marker) ON (m.value, m.tenant_id)
            """,
            "description": "Index Marker par valeur+tenant pour diff queries"
        },
        {
            "name": "marker_kind",
            "query": """
            CREATE INDEX marker_kind IF NOT EXISTS
            FOR (m:Marker) ON (m.kind)
            """,
            "description": "Index Marker par kind pour filtrage"
        },

        # =====================================================================
        # CanonicalConcept indexes
        # =====================================================================
        {
            "name": "canonical_id_tenant",
            "query": """
            CREATE INDEX canonical_id_tenant IF NOT EXISTS
            FOR (c:CanonicalConcept) ON (c.canonical_id, c.tenant_id)
            """,
            "description": "Index CanonicalConcept par id+tenant"
        },
        {
            "name": "canonical_stability",
            "query": """
            CREATE INDEX canonical_stability IF NOT EXISTS
            FOR (c:CanonicalConcept) ON (c.stability)
            """,
            "description": "Index CanonicalConcept par stability"
        },

        # =====================================================================
        # DocumentChunk indexes
        # =====================================================================
        {
            "name": "chunk_id_tenant",
            "query": """
            CREATE INDEX chunk_id_tenant IF NOT EXISTS
            FOR (dc:DocumentChunk) ON (dc.chunk_id, dc.tenant_id)
            """,
            "description": "Index DocumentChunk par id+tenant"
        },
        {
            "name": "chunk_document",
            "query": """
            CREATE INDEX chunk_document IF NOT EXISTS
            FOR (dc:DocumentChunk) ON (dc.document_id)
            """,
            "description": "Index DocumentChunk par document_id"
        },
    ]

    print(f"[SETUP] Creating {len(indexes)} indexes...")

    success_count = 0
    for idx in indexes:
        try:
            with client.driver.session(database="neo4j") as session:
                session.run(idx["query"])
                print(f"  ✅ {idx['name']}: {idx['description']}")
                success_count += 1
        except Exception as e:
            print(f"  ⚠️ {idx['name']}: {e}")

    print(f"\n[SETUP] ✅ {success_count}/{len(indexes)} indexes created/verified")

    # Vérifier les index existants
    print("\n[SETUP] Existing indexes:")
    with client.driver.session(database="neo4j") as session:
        result = session.run("SHOW INDEXES YIELD name, labelsOrTypes, properties, state")
        for record in result:
            print(f"  - {record['name']}: {record['labelsOrTypes']} {record['properties']} ({record['state']})")

    return True


def create_constraints():
    """Crée les contraintes Neo4j (unicité, existence)."""
    settings = get_settings()

    client = get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database="neo4j"
    )

    if not client.is_connected():
        return False

    constraints = [
        {
            "name": "document_id_unique",
            "query": """
            CREATE CONSTRAINT document_id_unique IF NOT EXISTS
            FOR (d:Document) REQUIRE (d.id, d.tenant_id) IS UNIQUE
            """,
            "description": "Unicité Document id+tenant"
        },
        {
            "name": "proto_id_unique",
            "query": """
            CREATE CONSTRAINT proto_id_unique IF NOT EXISTS
            FOR (p:ProtoConcept) REQUIRE (p.concept_id, p.tenant_id) IS UNIQUE
            """,
            "description": "Unicité ProtoConcept id+tenant"
        },
        {
            "name": "canonical_id_unique",
            "query": """
            CREATE CONSTRAINT canonical_id_unique IF NOT EXISTS
            FOR (c:CanonicalConcept) REQUIRE (c.canonical_id, c.tenant_id) IS UNIQUE
            """,
            "description": "Unicité CanonicalConcept id+tenant"
        },
        {
            "name": "marker_value_unique",
            "query": """
            CREATE CONSTRAINT marker_value_unique IF NOT EXISTS
            FOR (m:Marker) REQUIRE (m.value, m.tenant_id) IS UNIQUE
            """,
            "description": "Unicité Marker value+tenant"
        },
    ]

    print(f"\n[SETUP] Creating {len(constraints)} constraints...")

    success_count = 0
    for cst in constraints:
        try:
            with client.driver.session(database="neo4j") as session:
                session.run(cst["query"])
                print(f"  ✅ {cst['name']}: {cst['description']}")
                success_count += 1
        except Exception as e:
            # Constraints peuvent déjà exister ou syntaxe non supportée
            print(f"  ⚠️ {cst['name']}: {e}")

    print(f"\n[SETUP] ✅ {success_count}/{len(constraints)} constraints created/verified")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("KnowWhere - Setup Assertion Indexes (PR4)")
    print("=" * 60)
    print()

    success_idx = create_assertion_indexes()
    success_cst = create_constraints()

    if success_idx and success_cst:
        print("\n✅ Setup completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Setup completed with errors")
        sys.exit(1)
