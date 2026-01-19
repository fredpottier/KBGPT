#!/usr/bin/env python3
"""
Script de diagnostic pour analyser le problème SPAN vs ANCHORED_IN.

Vérifie:
1. Combien de ProtoConcepts ont anchor_status=SPAN
2. Combien de relations ANCHORED_IN existent
3. Quels ProtoConcepts SPAN n'ont pas de relation ANCHORED_IN

Usage:
    docker-compose exec app python scripts/diagnose_anchored_in.py
"""

import logging
from knowbase.common.clients.neo4j_client import get_neo4j_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    """Exécute le diagnostic."""
    neo4j_client = get_neo4j_client()
    tenant_id = "default"

    print("\n" + "=" * 70)
    print("DIAGNOSTIC: SPAN vs ANCHORED_IN")
    print("=" * 70)

    with neo4j_client.driver.session(database="neo4j") as session:
        # 1. Compter les ProtoConcepts par anchor_status
        result = session.run("""
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})
            RETURN p.anchor_status AS status, count(*) AS count
            ORDER BY count DESC
        """, tenant_id=tenant_id)

        print("\n1. ProtoConcepts par anchor_status:")
        print("-" * 40)
        total_span = 0
        for record in result:
            status = record["status"] or "NULL"
            count = record["count"]
            if status == "SPAN":
                total_span = count
            print(f"   {status}: {count}")

        # 2. Compter les relations ANCHORED_IN
        result = session.run("""
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})-[r:ANCHORED_IN]->(dc:DocumentChunk)
            RETURN count(r) AS count, count(DISTINCT p) AS distinct_concepts
        """, tenant_id=tenant_id)

        record = result.single()
        anchored_in_count = record["count"] if record else 0
        distinct_concepts_with_anchor = record["distinct_concepts"] if record else 0

        print(f"\n2. Relations ANCHORED_IN:")
        print("-" * 40)
        print(f"   Total relations: {anchored_in_count}")
        print(f"   Concepts distincts avec ANCHORED_IN: {distinct_concepts_with_anchor}")

        # 3. Identifier les ProtoConcepts SPAN sans ANCHORED_IN
        result = session.run("""
            MATCH (p:ProtoConcept {tenant_id: $tenant_id, anchor_status: 'SPAN'})
            WHERE NOT exists((p)-[:ANCHORED_IN]->(:DocumentChunk))
            RETURN p.concept_id AS id, p.concept_name AS name, p.doc_id AS doc
            LIMIT 10
        """, tenant_id=tenant_id)

        orphans = list(result)
        orphan_count = len(orphans)

        print(f"\n3. ProtoConcepts SPAN sans ANCHORED_IN:")
        print("-" * 40)

        # Compter le total
        result = session.run("""
            MATCH (p:ProtoConcept {tenant_id: $tenant_id, anchor_status: 'SPAN'})
            WHERE NOT exists((p)-[:ANCHORED_IN]->(:DocumentChunk))
            RETURN count(p) AS count
        """, tenant_id=tenant_id)
        total_orphans = result.single()["count"]

        print(f"   Total: {total_orphans} / {total_span} SPAN concepts sans ANCHORED_IN")
        if total_orphans > 0:
            print(f"\n   Exemples (10 premiers):")
            for record in orphans:
                print(f"   - {record['name'][:40]:<40} (doc: {record['doc'][-12:]})")

        # 4. Analyser les chunks pour un document spécifique
        result = session.run("""
            MATCH (d:Document {tenant_id: $tenant_id})
            WITH d.document_id AS doc_id LIMIT 1
            OPTIONAL MATCH (dc:DocumentChunk {document_id: doc_id, tenant_id: $tenant_id})
            RETURN doc_id,
                   count(dc) AS chunk_count,
                   min(dc.char_start) AS min_start,
                   max(dc.char_end) AS max_end
        """, tenant_id=tenant_id)

        record = result.single()
        if record and record["doc_id"]:
            print(f"\n4. Exemple de document:")
            print("-" * 40)
            print(f"   Document: {record['doc_id'][-20:]}")
            print(f"   Chunks: {record['chunk_count']}")
            print(f"   Couverture: [{record['min_start']} - {record['max_end']}]")

        # 5. Résumé
        print("\n" + "=" * 70)
        print("RÉSUMÉ")
        print("=" * 70)
        if total_span > 0:
            coverage = (total_span - total_orphans) / total_span * 100
            print(f"   Concepts SPAN: {total_span}")
            print(f"   Avec ANCHORED_IN: {total_span - total_orphans} ({coverage:.1f}%)")
            print(f"   Sans ANCHORED_IN: {total_orphans} ({100-coverage:.1f}%) <- PROBLÈME")

        if total_orphans > 0:
            print(f"\n   ⚠️  {total_orphans} concepts SPAN n'ont pas de lien vers les chunks!")
            print("   Causes possibles:")
            print("   - Positions d'anchor hors de la plage des chunks")
            print("   - Problème de calcul de char_offset")
            print("   - Concept_id mismatch entre anchor et Neo4j")
        else:
            print(f"\n   ✅ Tous les concepts SPAN ont une relation ANCHORED_IN!")


if __name__ == "__main__":
    main()
