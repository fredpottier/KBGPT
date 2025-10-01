# NORTH STAR - TRACKING PHASE 1

**Référence**: `doc/NORTH_STAR_IMPLEMENTATION_TRACKING.md` - Phase 1
**Statut Global**: 🚧 EN COURS
**Date début**: 2025-10-01
**Effort estimé**: ~7 jours

---

## 🎯 OBJECTIFS PHASE 1

### Objectif Principal
Stabiliser l'architecture Knowledge Graph multi-tenant avec Graphiti en production.

### Critères de Succès Phase 1
1. ✅ Multi-tenancy fonctionnel (isolation complète par tenant)
2. ✅ Episodes & Facts gouvernés (validation + approbation)
3. ⏸️ Intégration Qdrant ↔ Graphiti (sync bidirectionnelle)
4. ⏸️ Search hybride Qdrant + Graphiti
5. ⏸️ Migration données existantes

---

## 📋 CRITÈRES PHASE 1 (5 CRITÈRES)

### ✅ Critère 1.1 - Multi-Tenancy Graphiti
**Priorité**: P0 (Critical)
**Effort estimé**: ~2 jours
**Effort réel**: 0j (POC Phase 2 validé)
**Statut**: ✅ COMPLET
**Commit**: N/A (POC Graphiti)

**Description**: Infrastructure multi-tenant avec isolation Neo4j + PostgreSQL

**Implémentation existante**:
- `src/knowbase/services/tenant.py` - Service gestion tenants (140 lignes)
- `src/knowbase/graphiti/graphiti_client.py` - Client Graphiti multi-tenant (280 lignes)
- `src/knowbase/api/routers/tenants.py` - API tenants CRUD (180 lignes)
- Persistence JSON: `data/tenants/tenants.json`, `memberships.json`

**Fonctionnalités**:
- Création/modification/suppression tenants
- Isolation complète par tenant_id (Neo4j labels, PostgreSQL schema)
- Stats par tenant (users, episodes, facts)
- Gestion users/memberships

**Tests**: ✅ Validé en POC (fonctionnel)

**Documentation**: POC Graphiti Phase 2

---

### ✅ Critère 1.2 - Episodes & Facts Gouvernance
**Priorité**: P0 (Critical)
**Effort estimé**: ~3 jours
**Effort réel**: 0j (POC Phase 3 validé)
**Statut**: ✅ COMPLET
**Commit**: N/A (POC Graphiti)

**Description**: Workflow de gouvernance facts avec validation admin

**Implémentation existante**:
- `src/knowbase/graphiti/graphiti_governance.py` - Service gouvernance (200 lignes)
- `src/knowbase/api/routers/governance.py` - API gouvernance (150 lignes)
- Workflow: PENDING → APPROVED/REJECTED
- Audit trail complet (created_by, approved_by, timestamps)

**Fonctionnalités**:
- Episodes créés automatiquement (source: slides, RFP, docs)
- Facts extraits → statut PENDING
- Review admin → APPROVED/REJECTED
- Filtres par statut (approved_only pour prod)

**Tests**: ✅ Validé en POC (fonctionnel)

**Documentation**: POC Graphiti Phase 3

---

### ⏸️ Critère 1.3 - Intégration Qdrant ↔ Graphiti
**Priorité**: P0 (Critical)
**Effort estimé**: ~3 jours
**Statut**: ⏸️ À IMPLÉMENTER
**Assigné**: -

**Description**: Synchronisation bidirectionnelle Qdrant chunks ↔ Graphiti facts

**Objectifs**:
1. **Ingestion enrichie**:
   - Pipeline PPTX/PDF → chunks Qdrant + episodes/facts Graphiti
   - Liaison chunks ↔ facts (IDs croisés)

2. **Metadata sync**:
   - Chunks Qdrant: ajouter `episode_id`, `episode_name`
   - Episodes Graphiti: référencer `chunk_ids`

3. **Backfill entities**:
   - Utiliser Graphiti entities pour canonicalisation Qdrant
   - Batch update metadata chunks (canonical_entity_id)

**Architecture proposée**:
```python
# Service: src/knowbase/graphiti/qdrant_sync.py

async def ingest_slide_with_kg(slide: SlideInput, tenant_id: str):
    """Pipeline enrichi : chunks Qdrant + episode Graphiti"""

    # 1. Chunks Qdrant (existant)
    chunks = await create_chunks(slide)
    chunk_ids = await qdrant_client.upsert(chunks)

    # 2. Episode Graphiti
    episode = await graphiti_client.add_episode(
        name=f"Slide: {slide.title}",
        episode_body=slide.content,
        source_description=f"PPTX {slide.filename}",
        reference_time=datetime.now(),
        tenant_id=tenant_id
    )

    # 3. Lier chunks → episode (metadata Qdrant)
    await qdrant_client.update_metadata(
        chunk_ids,
        {
            "episode_id": episode.uuid,
            "episode_name": episode.name
        }
    )

    return {"chunks": chunk_ids, "episode_id": episode.uuid}
```

**Livrables**:
- [ ] Service `src/knowbase/graphiti/qdrant_sync.py` - Sync bidirectionnelle
- [ ] Refactor `src/knowbase/ingestion/pipelines/pptx_pipeline.py` - Intégration Graphiti
- [ ] Refactor `src/knowbase/ingestion/pipelines/pdf_pipeline.py` - Intégration Graphiti
- [ ] Endpoint `POST /ingest/slide-with-kg` - Pipeline enrichi
- [ ] Tests `tests/ingestion/test_qdrant_graphiti_sync.py` - Tests end-to-end

**Dépendances**:
- Critère 1.1 ✅ (Multi-tenancy)
- Critère 1.2 ✅ (Gouvernance)

---

### ⏸️ Critère 1.4 - Search Hybride Qdrant + Graphiti
**Priorité**: P1 (Important)
**Effort estimé**: ~2 jours
**Statut**: ⏸️ À IMPLÉMENTER
**Assigné**: -

**Description**: Requête combinée Qdrant (chunks) + Graphiti (facts/entities)

**Objectifs**:
1. **Search dual**:
   - Qdrant: chunks similaires (vector search)
   - Graphiti: facts pertinents (graph search)

2. **Reranking hybride**:
   - Fusion scores Qdrant + Graphiti
   - Pondération configurable (ex: 60% Qdrant, 40% Graphiti)

3. **Enrichissement résultats**:
   - Chunks → ajouter facts liés (via episode_id)
   - Facts → ajouter chunks sources

**Architecture proposée**:
```python
# Service: src/knowbase/search/hybrid_search.py

async def hybrid_search(
    query: str,
    tenant_id: str,
    limit: int = 10
) -> List[HybridResult]:
    """Search hybride Qdrant + Graphiti"""

    # 1. Qdrant: chunks similaires
    qdrant_results = await qdrant_client.search(
        query=query,
        tenant_id=tenant_id,
        limit=limit * 2  # Over-fetch pour reranking
    )

    # 2. Graphiti: facts pertinents
    graphiti_results = await graphiti_client.search(
        query=query,
        tenant_id=tenant_id,
        num_results=limit
    )

    # 3. Reranking hybride
    combined = rerank_hybrid(
        qdrant_results=qdrant_results,
        graphiti_results=graphiti_results,
        weights={"qdrant": 0.6, "graphiti": 0.4}
    )

    return combined[:limit]
```

**Livrables**:
- [ ] Service `src/knowbase/search/hybrid_search.py` - Search Qdrant + Graphiti
- [ ] Reranker `src/knowbase/search/hybrid_reranker.py` - Fusion scores
- [ ] Endpoint `POST /search/hybrid` - API search hybride
- [ ] Tests `tests/search/test_hybrid_search.py` - Tests search

**Dépendances**:
- Critère 1.3 ⏸️ (Intégration Qdrant ↔ Graphiti)

---

### ⏸️ Critère 1.5 - Migration Données Existantes
**Priorité**: P1 (Important)
**Effort estimé**: ~2 jours
**Statut**: ⏸️ À IMPLÉMENTER
**Assigné**: -

**Description**: Migrer chunks Qdrant existants → episodes Graphiti

**Objectifs**:
1. **Analyse existant**:
   - Lister chunks Qdrant actuels (collection `knowbase`)
   - Identifier sources (filename, import_id, solution)

2. **Création episodes**:
   - Grouper chunks par source
   - Créer 1 episode Graphiti par source
   - Lier chunks ↔ episodes (metadata `episode_id`)

3. **Validation**:
   - Vérifier 100% chunks liés
   - Stats migration (episodes créés, chunks migrés)

**Architecture proposée**:
```python
# Script: scripts/migrate_qdrant_to_graphiti.py

async def migrate_qdrant_to_graphiti(tenant_id: str):
    """Migration batch chunks Qdrant → episodes Graphiti"""

    # 1. Lister tous chunks Qdrant
    chunks = await qdrant_client.scroll(
        collection="knowbase",
        limit=10000
    )

    # 2. Grouper par source (filename, import_id)
    chunks_by_source = group_by_source(chunks)

    # 3. Créer episode par source
    episodes_created = 0
    for source, source_chunks in chunks_by_source.items():
        episode = await graphiti_client.add_episode(
            name=f"Migration: {source}",
            episode_body=combine_chunks_content(source_chunks),
            source_description=f"Migrated from Qdrant: {source}",
            tenant_id=tenant_id
        )

        # 4. Update chunks avec episode_id
        chunk_ids = [c.id for c in source_chunks]
        await qdrant_client.update_metadata(
            chunk_ids,
            {
                "episode_id": episode.uuid,
                "migrated": True
            }
        )
        episodes_created += 1

    return {
        "episodes_created": episodes_created,
        "chunks_migrated": len(chunks)
    }
```

**Livrables**:
- [ ] Script `scripts/migrate_qdrant_to_graphiti.py` - Migration batch
- [ ] Service `src/knowbase/migration/qdrant_graphiti_migration.py` - Service migration
- [ ] Endpoint `POST /admin/migrate/qdrant-to-graphiti` - Trigger migration
- [ ] Tests `tests/migration/test_qdrant_graphiti_migration.py` - Tests migration

**Dépendances**:
- Critère 1.3 ⏸️ (Intégration Qdrant ↔ Graphiti)

---

## 📊 BILAN PHASE 1

| Critère | Statut | Effort Estimé | Effort Réel | Tests | Commit |
|---------|--------|---------------|-------------|-------|--------|
| 1.1 Multi-Tenancy | ✅ FAIT | ~2j | 0j (POC) | ✅ Validé | POC |
| 1.2 Gouvernance | ✅ FAIT | ~3j | 0j (POC) | ✅ Validé | POC |
| 1.3 Intégration Qdrant ↔ Graphiti | ⏸️ TODO | ~3j | - | - | - |
| 1.4 Search Hybride | ⏸️ TODO | ~2j | - | - | - |
| 1.5 Migration Données | ⏸️ TODO | ~2j | - | - | - |

**SCORE ACTUEL**: 2/5 (40%) - POC Graphiti validé ✅
**EFFORT RESTANT**: ~7 jours
**TESTS**: 0/5 critères testés en intégration

---

## 🎯 PROCHAINE ACTION

### Action Immédiate
**Démarrer Critère 1.3**: Intégration Qdrant ↔ Graphiti

**Étapes**:
1. Créer service `qdrant_sync.py`
2. Refactor `pptx_pipeline.py` pour créer episodes
3. Ajouter liaison chunks → episodes (metadata)
4. Tests end-to-end ingestion + search

**Commandes**:
```bash
# Créer fichiers
touch src/knowbase/graphiti/qdrant_sync.py
touch tests/ingestion/test_qdrant_graphiti_sync.py

# Tests
docker-compose exec app pytest tests/ingestion/test_qdrant_graphiti_sync.py -v
```

---

## 🔧 CONFIGURATION REQUISE

### Variables d'environnement (.env)
```bash
# Graphiti (déjà configuré)
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
POSTGRES_GRAPHITI_URI=postgresql://user:pass@postgres_graphiti:5432/graphiti

# Qdrant (déjà configuré)
QDRANT_URL=http://qdrant:6333

# Tenants (nouveau)
DEFAULT_TENANT_ID=default
TENANT_STORAGE_PATH=/data/tenants
```

### Collections Qdrant
- `knowbase` - Collection principale (existante)
- Métadonnées enrichies: `episode_id`, `episode_name`, `tenant_id`

### Neo4j Labels
- `(:Episode {uuid, name, tenant_id})` - Episodes multi-tenant
- `(:Entity {name, tenant_id})` - Entités canoniques
- `(:Fact {uuid, status, tenant_id})` - Facts gouvernés

---

## 📈 MÉTRIQUES SUCCESS PHASE 1

### Fonctionnelles
- ✅ Multi-tenancy: isolation complète (0 fuite cross-tenant)
- ✅ Gouvernance: 100% facts reviewed avant production
- ⏸️ Intégration: 100% chunks liés à episodes
- ⏸️ Search hybride: recall amélioré de 20% vs Qdrant seul
- ⏸️ Migration: 100% données existantes migrées sans perte

### Techniques
- ⏸️ Latence ingestion: <5s par slide (chunks + episode)
- ⏸️ Latence search hybride: <200ms (p95)
- ⏸️ Tests intégration: 100% passent
- ⏸️ Coverage code nouveau: >80%

---

## ⚠️ RISQUES & PARADES

### Risque 1 - Performance Sync Bidirectionnelle
**Impact**: Latence ingestion augmentée (Qdrant + Graphiti)
**Probabilité**: Moyenne
**Parade**:
- Ingestion async (Redis queue)
- Batch episodes (grouper chunks par source)
- Cache episodes créés (éviter duplicates)

### Risque 2 - Migration Données Volumineuses
**Impact**: Timeout migration si 100k+ chunks
**Probabilité**: Haute
**Parade**:
- Migration par batch (1000 chunks/batch)
- Reprise sur erreur (checkpointing)
- Monitoring progression (logs structurés)

### Risque 3 - Compatibilité Schéma Qdrant
**Impact**: Métadonnées manquantes dans chunks existants
**Probabilité**: Moyenne
**Parade**:
- Migration progressive (flag `migrated`)
- Fallback si episode_id absent (search Qdrant only)
- Enrichissement asynchrone (job background)

---

## 📚 DOCUMENTATION ASSOCIÉE

### Documents de référence
- `doc/NORTH_STAR_IMPLEMENTATION_TRACKING.md` - Roadmap globale
- `doc/NORTH_STAR_IMPLEMENTATION_TRACKING_PHASE0.md` - Phase 0 complète
- `doc/ARCHITECTURE_RAG_KG_NORTH_STAR.md` - Architecture globale

### Code existant (POC Graphiti)
- `src/knowbase/services/tenant.py` - Multi-tenancy
- `src/knowbase/graphiti/graphiti_client.py` - Client Graphiti
- `src/knowbase/graphiti/graphiti_governance.py` - Gouvernance
- `src/knowbase/api/routers/tenants.py` - API tenants
- `src/knowbase/api/routers/governance.py` - API gouvernance

### À créer (Phase 1)
- `src/knowbase/graphiti/qdrant_sync.py`
- `src/knowbase/search/hybrid_search.py`
- `src/knowbase/migration/qdrant_graphiti_migration.py`

---

## 🚀 PHASE SUIVANTE

**Phase 2 - Query Understanding & Router**
- **Référence**: `doc/NORTH_STAR_IMPLEMENTATION_TRACKING_PHASE2.md` (à créer)
- **Effort estimé**: ~7 jours
- **Objectifs**:
  - Intent classification (factual, conversational, analytical)
  - Entity extraction depuis query
  - Router intelligent (Qdrant, Graphiti, Hybrid)

---

*Dernière mise à jour : 2025-10-01*
*Document de suivi : Phase 1*
*Tracking global : `doc/NORTH_STAR_IMPLEMENTATION_TRACKING.md`*
*Phase précédente : `doc/NORTH_STAR_IMPLEMENTATION_TRACKING_PHASE0.md` ✅*
