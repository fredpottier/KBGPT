#!/usr/bin/env python3
"""
Script de réparation cross-référence Neo4j ↔ Qdrant
Utilise les données existantes pour établir les liens manquants
"""
import sys
sys.path.insert(0, '/app')

from knowbase.common.clients.neo4j_client import get_neo4j_client
from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.config.settings import get_settings

settings = get_settings()

# Connexion clients
neo4j_client = get_neo4j_client(
    uri=settings.neo4j_uri,
    user=settings.neo4j_user,
    password=settings.neo4j_password,
    database="neo4j"
)
qdrant_client = get_qdrant_client()

print("[FIX] Démarrage cross-référence...")

# Étape 1: Récupérer mapping Proto → Canonical depuis Neo4j
proto_to_canonical = {}
with neo4j_client.driver.session(database="neo4j") as session:
    result = session.run("""
        MATCH (p:ProtoConcept)-[:PROMOTED_TO]->(c:CanonicalConcept)
        WHERE p.tenant_id = $tenant_id
        RETURN p.concept_id as proto_id, c.canonical_id as canonical_id
    """, tenant_id="default")

    for record in result:
        proto_to_canonical[record["proto_id"]] = record["canonical_id"]

print(f"[FIX] Retrieved {len(proto_to_canonical)} Proto→Canonical mappings")

# Étape 2: Parcourir tous les chunks Qdrant et construire les mappings
chunk_to_canonicals = {}
canonical_to_chunks = {}

# Scroll tous les chunks
offset = None
batch_count = 0
total_chunks = 0

while True:
    result = qdrant_client.scroll(
        collection_name="knowbase",
        limit=1000,
        offset=offset,
        with_payload=True,
        with_vectors=False
    )

    points, next_offset = result

    if not points:
        break

    batch_count += 1
    total_chunks += len(points)

    for point in points:
        proto_ids = point.payload.get("proto_concept_ids", [])

        if not proto_ids:
            continue

        canonical_ids = []
        for proto_id in proto_ids:
            canonical_id = proto_to_canonical.get(proto_id)
            if canonical_id:
                canonical_ids.append(canonical_id)
                # Mapper Canonical → Chunks pour Neo4j
                if canonical_id not in canonical_to_chunks:
                    canonical_to_chunks[canonical_id] = []
                canonical_to_chunks[canonical_id].append(str(point.id))

        if canonical_ids:
            chunk_to_canonicals[str(point.id)] = canonical_ids

    print(f"[FIX] Batch {batch_count}: processed {len(points)} chunks (total: {total_chunks})")

    offset = next_offset
    if not offset:
        break

print(f"[FIX] Mapped {len(chunk_to_canonicals)} chunks to canonical concepts")

# Étape 3: Update chunks Qdrant avec canonical_concept_ids
if chunk_to_canonicals:
    update_count = 0
    for chunk_id, canonical_ids in chunk_to_canonicals.items():
        qdrant_client.set_payload(
            collection_name="knowbase",
            payload={"canonical_concept_ids": canonical_ids},
            points=[chunk_id]
        )
        update_count += 1
        if update_count % 100 == 0:
            print(f"[FIX] Updated {update_count}/{len(chunk_to_canonicals)} chunks in Qdrant...")

    print(f"[FIX] ✅ Updated {len(chunk_to_canonicals)} chunks in Qdrant with canonical_concept_ids")

# Étape 4: Update CanonicalConcepts Neo4j avec chunk_ids
if canonical_to_chunks:
    with neo4j_client.driver.session(database="neo4j") as session:
        update_count = 0
        for canonical_id, chunk_list in canonical_to_chunks.items():
            session.run("""
                MATCH (c:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
                SET c.chunk_ids = $chunk_ids
            """, canonical_id=canonical_id, tenant_id="default", chunk_ids=chunk_list)
            update_count += 1
            if update_count % 100 == 0:
                print(f"[FIX] Updated {update_count}/{len(canonical_to_chunks)} concepts in Neo4j...")

    print(f"[FIX] ✅ Updated {len(canonical_to_chunks)} CanonicalConcepts in Neo4j with chunk_ids")

# Résumé
print(f"\n[FIX] ✅ Cross-reference complete:")
print(f"  - {len(chunk_to_canonicals)} chunks → canonical concepts")
print(f"  - {len(canonical_to_chunks)} canonical concepts → chunks")

neo4j_client.close()
