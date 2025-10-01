# Analyse Architecture Complète - Phase 1 Critère 1.3

**Date**: 2025-10-01
**Critère**: Integration Knowledge Graph (Qdrant ↔ Graphiti)
**Statut**: Implémenté avec limitations documentées

---

## 📊 Vue d'Ensemble

### Objectif Initial
Intégrer un knowledge graph (Graphiti/Neo4j) pour extraire entities et relations depuis les documents SAP, enrichissant la recherche vectorielle Qdrant avec des capacités de graph traversal.

### Ce Qui a Été Implémenté

```
┌─────────────────────────────────────────────────────────────┐
│                    PIPELINE KG UNIFIÉ                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  PPTX Input                                                  │
│      ↓                                                       │
│  1. Extraction Slides (MegaParse)                           │
│      ↓                                                       │
│  2. Triple Output:                                           │
│     ├─ Chunks (texte)                                       │
│     ├─ Entities (concepts SAP, produits, technologies)      │
│     └─ Relations (USES, INTEGRATES_WITH, PROVIDES)          │
│      ↓                                                       │
│  3. Ingestion Parallèle:                                    │
│     ├─ Qdrant: chunks + embeddings                          │
│     └─ Graphiti: episode + entities + relations             │
│      ↓                                                       │
│  4. Sync Metadata Bidirectionnelle:                         │
│     ├─ Qdrant chunks: {episode_id, episode_name, has_kg}    │
│     └─ Graphiti episode: "Qdrant Chunks: uuid1, uuid2..."   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Résultats Mesurés

**Document Test**: `Group_Reporting_Overview_L1.pptx` (16 slides)

| Métrique | Valeur | Notes |
|----------|--------|-------|
| Chunks Qdrant | 40-45 | Chunking sémantique 500-1000 tokens |
| Entities extraites | 76-78 | Concepts SAP, produits, technologies |
| Relations extraites | 60-62 | USES, INTEGRATES_WITH, PROVIDES |
| Success Rate | 93.75% | 15/16 slides traitées |
| Episode Graphiti | 1 | Un episode par document |
| Sync bidirectionnelle | ✅ | Metadata liées correctement |

---

## 🏗️ Architecture Détaillée

### Composants Créés

#### 1. `src/knowbase/graphiti/graphiti_client.py` (325 lignes)

**Responsabilité**: Client HTTP pour l'API Graphiti

```python
class GraphitiClient:
    - healthcheck() -> bool
    - add_episode(group_id, messages) -> dict
    - get_episodes(group_id, last_n) -> List[dict]
    - get_episode(episode_uuid, group_id) -> Optional[dict]  # ⚠️ Limité
    - search(group_id, query, num_results) -> dict
    - delete_episode(episode_uuid) -> bool
    - clear_group(group_id) -> bool
```

**Points Forts**:
- ✅ Gestion erreurs HTTP avec retry
- ✅ Logging structuré
- ✅ Timeout configuré (120s pour traitement LLM)

**Faiblesses**:
- ❌ `get_episode()` non fiable (API limitation)
- ❌ Pas de cache pour requêtes répétées
- ❌ Pas de rate limiting
- ❌ Pas de métriques performance

#### 2. `src/knowbase/graphiti/qdrant_sync.py` (331 lignes)

**Responsabilité**: Synchronisation bidirectionnelle Qdrant ↔ Graphiti

```python
class QdrantGraphitiSyncService:
    - ingest_with_kg(content, metadata, tenant_id) -> SyncResult
    - link_chunks_to_episode(chunk_ids, episode_id, episode_name) -> None
    - enrich_chunks_with_entities(chunk_ids, episode_id) -> int  # ⚠️ Non viable
    - get_episode_for_chunks(chunk_ids) -> Optional[str]
```

**Points Forts**:
- ✅ Sync metadata atomique via `set_payload()`
- ✅ Dataclass `SyncResult` pour résultats typés
- ✅ Singleton pattern pour éviter multiples instances

**Faiblesses**:
- ❌ `enrich_chunks_with_entities()` cassé (API limitation)
- ❌ Pas de rollback en cas d'échec partiel
- ❌ Pas de validation cohérence données
- ❌ Pas de retry pour failures transitoires

#### 3. `src/knowbase/ingestion/pipelines/pptx_pipeline_kg.py` (922 lignes)

**Responsabilité**: Pipeline unifié PPTX → Qdrant + Graphiti

**Workflow**:
```python
async def process_pptx_kg(pptx_path, tenant_id, document_type):
    1. Extraction slides (MegaParse)
    2. Pour chaque slide:
       a. Extraction entities/relations (LLM)
       b. Chunking texte
       c. Création embeddings
    3. Ingestion batch Qdrant (tous chunks)
    4. Création episode Graphiti (toutes entities/relations)
    5. Sync metadata bidirectionnelle
    6. Return SyncResult
```

**Points Forts**:
- ✅ Extraction parallèle entities + chunks
- ✅ Gestion erreurs par slide (pas d'arrêt complet)
- ✅ Logging détaillé avec statistiques
- ✅ Support document_type pour prompts custom

**Faiblesses**:
- ❌ Pas de transaction atomique (Qdrant ✅ mais Graphiti ❌)
- ❌ Pas de cleanup en cas d'échec Graphiti
- ❌ Duplication code avec `pptx_pipeline.py` (refactor nécessaire)
- ❌ Pas de limite sur taille episode (peut dépasser max tokens LLM)

#### 4. `src/knowbase/graphiti/backfill_entities.py` (153 lignes)

**Responsabilité**: Enrichissement rétroactif chunks avec entities Graphiti

**Statut**: ❌ **Non viable** (limitation API Graphiti)

**Problème**:
```python
# ❌ IMPOSSIBLE: Récupérer episode par ID custom
episode = graphiti_client.get_episode(episode_uuid=custom_id)
# API retourne 405 Method Not Allowed
```

**Alternative Proposée**: Utiliser `/search` pour enrichissement contextuel (Phase 2)

#### 5. Docker Compose Configuration

**Fichier**: `docker-compose.graphiti.yml`

**Services**:
- `neo4j`: Graph database (Neo4j 5.26.0)
- `postgres-graphiti`: Stockage metadata (pgvector/pg16)
- `graphiti`: Service API (zepai/graphiti:latest)
- `graphiti-admin`: Interface Adminer (debug)

**Fix Critique**: Ajout réseau `knowbase_net` pour communication inter-services

```yaml
networks:
  - graphiti_net  # Isolation interne
  - knowbase_net  # Communication avec app/worker
```

---

## 🔍 Analyse Approfondie

### Forces de l'Implémentation

#### 1. **Separation of Concerns** ✅
- Pipeline extraction (MegaParse)
- Client API (GraphitiClient)
- Service sync (QdrantGraphitiSyncService)
- Pipeline orchestration (pptx_pipeline_kg)

Chaque composant a une responsabilité claire et peut être testé/modifié indépendamment.

#### 2. **Metadata Bidirectionnelle** ✅
```python
# Qdrant → Graphiti
chunks[uuid] = {
    "episode_id": "test_sync_doc_123",
    "episode_name": "PPTX: Group_Reporting_Overview_L1.pptx",
    "has_knowledge_graph": True
}

# Graphiti → Qdrant
episode.content = """
This document contains 76 entities and 62 relations
extracted from 45 content chunks.

Qdrant Chunks (total: 45): uuid1, uuid2, uuid3...
"""
```

Permet requêtes cross-system :
- Qdrant: "Quels chunks ont un knowledge graph ?" → filter `has_knowledge_graph=true`
- Graphiti: "Quel episode correspond à ces chunks ?" → parse `episode.content`

#### 3. **Resilience par Slide** ✅
```python
for slide_idx, slide_content in enumerate(slides):
    try:
        extract_entities_relations(slide_content)
    except Exception as e:
        logger.error(f"Erreur slide {slide_idx}: {e}")
        failed_slides.append(slide_idx)
        continue  # Ne pas bloquer tout le document
```

Un slide en échec n'empêche pas le traitement des autres.

#### 4. **Observabilité** ✅
- Logging structuré avec niveaux INFO/DEBUG/ERROR
- Statistiques détaillées (entities/relations par type)
- Métriques success_rate
- Bannières visuelles dans logs

### Faiblesses de l'Implémentation

#### 1. **Pas de Transaction Atomique** ❌

**Problème**:
```python
# 1. Chunks insérés dans Qdrant ✅
chunk_ids = await qdrant_client.upsert_chunks(chunks)

# 2. Episode créé dans Graphiti ❌ (peut échouer)
result = graphiti_client.add_episode(group_id, messages)

# 3. Si Graphiti échoue → chunks orphelins dans Qdrant !
```

**Impact**:
- Données incohérentes entre systèmes
- Chunks sans `episode_id` → pas de lien vers KG
- Pas de cleanup automatique

**Solution Proposée** (Phase 2):
```python
try:
    chunk_ids = await qdrant_client.upsert_chunks(chunks)
    result = graphiti_client.add_episode(group_id, messages)
    await sync_service.link_chunks_to_episode(chunk_ids, episode_id)
except Exception as e:
    # Rollback Qdrant
    qdrant_client.delete(collection_name, ids=chunk_ids)
    raise
```

#### 2. **API Graphiti Limitations** ❌

Voir `doc/architecture/GRAPHITI_API_LIMITATIONS.md` pour détails complets.

**Limitations Critiques**:
1. POST `/messages` retourne `{"success": true}` sans `episode_uuid`
2. Pas de GET `/episode/{uuid}` disponible
3. Champ `name` vide dans episodes retournés
4. Champ `entity_edges` vide dans GET `/episodes`

**Conséquences**:
- ❌ Impossible backfill entities depuis Graphiti
- ❌ Pas de récupération episode par ID custom
- ❌ Dépendance à `/search` pour queries enrichies

#### 3. **Duplication Code avec Pipeline Classique** ❌

**Fichiers Dupliqués**:
- `pptx_pipeline.py` (ligne 1-600): Extraction + chunking + Qdrant
- `pptx_pipeline_kg.py` (ligne 1-922): **MÊME CODE** + Graphiti

**Problèmes**:
- Maintenance double (bug fix dans les 2 fichiers)
- Risque divergence comportement
- Tests dupliqués

**Refactoring Proposé** (Phase 2):
```python
# pptx_pipeline_base.py
class PptxPipelineBase:
    def extract_slides()
    def chunk_content()
    def create_embeddings()

# pptx_pipeline.py (extends Base)
class PptxPipeline(PptxPipelineBase):
    def process(): extract → chunk → qdrant

# pptx_pipeline_kg.py (extends Base)
class PptxPipelineKG(PptxPipelineBase):
    def process(): extract → chunk+entities → qdrant+graphiti
```

#### 4. **Pas de Validation Cohérence Données** ❌

**Scénarios Non Gérés**:
```python
# Cas 1: Chunks dans Qdrant MAIS pas d'episode dans Graphiti
chunks = qdrant.scroll(filter={"has_knowledge_graph": True})
# → Comment valider que tous les episode_id existent dans Graphiti ?

# Cas 2: Episode dans Graphiti MAIS chunks supprimés de Qdrant
episodes = graphiti.get_episodes(group_id)
# → Comment détecter les "dangling episodes" ?

# Cas 3: Metadata incohérente
chunk.payload["episode_id"] = "episode_123"
episode.content = "Qdrant Chunks: uuid1, uuid2"  # uuid1 != chunk.id
# → Pas de validation cross-system
```

**Solution Proposée** (Phase 2):
```python
# Validation service
class SyncValidator:
    def validate_chunks_have_episodes(self, tenant_id) -> List[str]:
        """Retourne chunk_ids orphelins"""

    def validate_episodes_have_chunks(self, tenant_id) -> List[str]:
        """Retourne episode_ids orphelins"""

    def validate_metadata_consistency(self, tenant_id) -> Dict[str, Any]:
        """Valide cohérence bidirectionnelle"""
```

#### 5. **Performance Non Optimisée** ❌

**Extraction Entities LLM**:
```python
# ❌ Appel LLM pour CHAQUE slide (16 slides = 16 appels)
for slide in slides:
    entities = await extract_entities(slide.content)  # 2-5s par slide
```

**Total**: 16 slides × 3s = **48 secondes** juste pour extraction entities

**Optimisation Proposée** (Phase 2):
```python
# ✅ Batch processing avec semaphore
async def extract_entities_batch(slides, max_concurrent=5):
    sem = asyncio.Semaphore(max_concurrent)
    tasks = [extract_with_sem(slide, sem) for slide in slides]
    return await asyncio.gather(*tasks)

# 16 slides / 5 concurrent × 3s = 10 secondes (80% plus rapide)
```

#### 6. **Pas de Gestion Déduplication** ❌

**Problème**:
```python
# Import 1: Document X → 76 entities créées
process_pptx_kg("doc_x.pptx", tenant="acme")

# Import 2: MÊME document → 76 entities DUPLIQUÉES
process_pptx_kg("doc_x.pptx", tenant="acme")
```

**Graphiti Behavior**:
- Crée nouvel episode à chaque import
- Merge entities par `name` MAIS préserve `valid_at` différent
- Facts peuvent être dupliqués avec timestamps différents

**Solution Proposée** (Phase 3 - Facts Gouvernance):
```python
# Détection document déjà importé
existing = qdrant.search(query=doc_hash, tenant_id=tenant, limit=1)
if existing and existing[0].score > 0.99:
    logger.warning(f"Document déjà importé: {existing[0].id}")
    return {"status": "duplicate", "existing_chunks": existing}
```

#### 7. **Sécurité et Validation Inputs** ⚠️

**Problèmes Potentiels**:
```python
# Pas de validation tenant_id
process_pptx_kg(tenant_id="../../etc/passwd")  # Path traversal ?

# Pas de limite taille episode content
episode_content = "\n".join([slide.text for slide in slides])  # 100MB ?

# Pas de sanitization entities extraites
entity_name = "<script>alert('xss')</script>"  # Stocké tel quel
```

**Mitigations Proposées** (Phase 2):
```python
# Validation tenant_id
assert re.match(r'^[a-zA-Z0-9_-]+$', tenant_id), "Invalid tenant_id"

# Limite taille episode
MAX_EPISODE_SIZE = 50_000  # tokens
if len(episode_content) > MAX_EPISODE_SIZE:
    episode_content = episode_content[:MAX_EPISODE_SIZE]

# Sanitization entities
entity_name = html.escape(entity_name)
```

---

## 🧪 Tests et Validation

### Tests Créés

**Fichier**: `tests/integration/test_qdrant_graphiti_sync.py` (400 lignes)

#### Tests Fonctionnels (✅ Validés)

1. **test_chunks_created_with_episode_metadata**: Valide metadata sync Qdrant
2. **test_episode_created_in_graphiti**: Valide création episodes Graphiti
3. **test_bidirectional_metadata_sync**: Valide liens bidirectionnels
4. **test_search_graphiti_from_qdrant_context**: Valide requêtes cross-system
5. **test_full_pipeline_kg_integration**: Valide workflow end-to-end
6. **test_link_chunks_to_episode**: Valide méthode sync service

#### Tests Limitations (📋 Documentation)

7. **test_cannot_get_episode_by_custom_id**: Documente limitation API GET
8. **test_episode_entity_edges_empty**: Documente limitation entity_edges vides

### Tests Manquants (Phase 2)

- ❌ Tests performance (extraction entities batch)
- ❌ Tests rollback (échec partiel Graphiti)
- ❌ Tests validation cohérence (chunks orphelins)
- ❌ Tests déduplication (imports répétés)
- ❌ Tests sécurité (injection, path traversal)
- ❌ Tests charge (100+ documents simultanés)

---

## 📈 Métriques et Performance

### Temps Traitement (Document Test 16 Slides)

| Étape | Temps | % Total |
|-------|-------|---------|
| Extraction slides (MegaParse) | 5-8s | 15% |
| Extraction entities/relations (LLM) | 30-40s | 70% |
| Chunking + embeddings | 3-5s | 10% |
| Ingestion Qdrant | 1-2s | 3% |
| Ingestion Graphiti | 1-2s | 3% |
| **Total** | **40-57s** | **100%** |

### Goulots d'Étranglement

1. **Extraction Entities LLM** (70% du temps)
   - Appels séquentiels (pas de parallélisme)
   - Modèle Claude 3.5 Sonnet (2-3s par slide)
   - Solution: Batch processing + modèle plus rapide (Haiku)

2. **MegaParse Extraction** (15% du temps)
   - Dépend de la complexité PPTX
   - Pas d'optimisation possible (librairie externe)

### Scalabilité

**Limites Actuelles**:
- ✅ Qdrant: Supporte millions de chunks (scalable)
- ⚠️ Graphiti: Performance inconnue à 10K+ episodes
- ❌ Neo4j: Peut nécessiter tuning pour graphs larges (100K+ nodes)

**Recommandations**:
- Monitoring Neo4j (query performance, memory usage)
- Index sur `group_id` dans episodes
- Pagination pour `/episodes/{group_id}` si > 1000 episodes

---

## 🚨 Risques et Points d'Attention

### Risques Critiques (🔴 High)

1. **Données Incohérentes Entre Systèmes**
   - Pas de transaction atomique Qdrant + Graphiti
   - Échec Graphiti → chunks orphelins
   - Mitigation: Ajouter rollback Qdrant (Phase 2)

2. **Dépendance API Graphiti Non Documentée**
   - Pas de versioning API
   - Changements breaking possibles
   - Mitigation: Tests e2e pour détecter regressions

3. **Performance Dégradée à l'Échelle**
   - Extraction LLM séquentielle
   - Pas de cache entities
   - Mitigation: Batch processing + cache Redis (Phase 2)

### Risques Modérés (🟡 Medium)

4. **Duplication Code Pipeline**
   - Maintenance double
   - Divergence comportement
   - Mitigation: Refactoring base class (Phase 2)

5. **Pas de Monitoring Production**
   - Aucune métrique Graphiti
   - Pas d'alerting échecs sync
   - Mitigation: Prometheus + Grafana (Phase 3)

6. **Sécurité Inputs Non Validés**
   - Injection possible dans entity_name
   - Path traversal tenant_id
   - Mitigation: Validation + sanitization (Phase 2)

### Risques Faibles (🟢 Low)

7. **Logs Verbeux**
   - Pollution logs avec statistiques détaillées
   - Mitigation: Level DEBUG pour stats (Phase 2)

8. **Pas de Rate Limiting**
   - Possible DoS sur API Graphiti
   - Mitigation: Rate limiter (Phase 3)

---

## 🔮 Recommandations Phase 2

### Priorité 1 (Critique)

1. **Implémenter Rollback Qdrant**
   ```python
   try:
       chunks = await qdrant_client.upsert_chunks(...)
       episode = graphiti_client.add_episode(...)
   except GraphitiError:
       await qdrant_client.delete(ids=chunk_ids)
       raise
   ```

2. **Refactoring Pipeline Base**
   - Extraire code commun `pptx_pipeline_base.py`
   - Extends dans `pptx_pipeline.py` et `pptx_pipeline_kg.py`
   - Tests unitaires base class

3. **Validation Cohérence Données**
   - Script `validate_sync_consistency.py`
   - Détection chunks orphelins
   - Détection episodes orphelins

### Priorité 2 (Importante)

4. **Batch Processing Extraction LLM**
   - `asyncio.Semaphore(5)` pour parallélisme contrôlé
   - Réduction temps traitement 70%

5. **Monitoring Graphiti**
   - Métriques Prometheus (episodes créés, erreurs API)
   - Dashboard Grafana

6. **Tests Performance**
   - Benchmark 100 documents
   - Mesure temps par étape
   - Profiling Neo4j queries

### Priorité 3 (Nice to Have)

7. **Cache Entities Extraites**
   - Redis cache pour entities déjà vues
   - Évite appels LLM dupliqués

8. **Alternative Backfill via /search**
   - Enrichissement chunks avec entities contextuelles
   - Remplace `enrich_chunks_with_entities()` cassé

9. **Interface Visualisation Knowledge Graph**
   - Intégration `zep-graph-visualization`
   - Dashboard exploration Neo4j

---

## ✅ Critères Acceptation Phase 1 (Bilan)

| Critère | Statut | Notes |
|---------|--------|-------|
| Extraction entities/relations depuis PPTX | ✅ 100% | 76 entities, 62 relations par document |
| Ingestion chunks Qdrant | ✅ 100% | 40-45 chunks par document |
| Création episodes Graphiti | ✅ 100% | 1 episode par document |
| Sync metadata bidirectionnelle | ✅ 100% | `episode_id` ↔ `chunk_ids` |
| Requêtes cross-system | ✅ 100% | Filter Qdrant + Search Graphiti |
| Backfill entities | ❌ 0% | Non viable (API limitation) |
| Tests end-to-end | ✅ 80% | 8 tests créés, manque perf/sécurité |
| Documentation architecture | ✅ 100% | Ce document + limitations |

**Statut Global**: **85% Complet** (7/8 critères validés)

---

## 📝 Conclusion

### Ce Qui Fonctionne Bien

✅ **Pipeline triple-output unifié** : Extraction simultanée chunks + entities + relations
✅ **Sync metadata bidirectionnelle** : Traçabilité Qdrant ↔ Graphiti
✅ **Resilience** : Échec slide n'arrête pas le document
✅ **Observabilité** : Logs structurés + statistiques détaillées
✅ **Tests e2e** : Validation workflow complet

### Ce Qui Nécessite Amélioration

❌ **Transaction atomique** : Rollback Qdrant en cas d'échec Graphiti
❌ **Performance LLM** : Batch processing extraction entities
❌ **Duplication code** : Refactoring pipeline base
❌ **Validation cohérence** : Détection données orphelines
❌ **Backfill entities** : Alternative via `/search` (Phase 2)

### Prochaines Étapes

**Phase 2 (Court Terme)** :
1. Implémenter rollback transactions
2. Batch processing extraction LLM
3. Refactoring pipeline base
4. Tests performance + sécurité

**Phase 3 (Moyen Terme)** :
1. Facts Gouvernance (détection conflits)
2. Monitoring production (Prometheus/Grafana)
3. Visualisation knowledge graph
4. Canonicalisation entities

**Phase 4 (Long Terme)** :
1. Évaluation alternatives Graphiti (Neo4j direct ?)
2. Optimisation Neo4j (indexes, queries)
3. Scale testing (10K+ documents)
4. Multi-tenant isolation

---

**Auteur**: Claude Code
**Version**: 1.0
**Dernière Mise à Jour**: 2025-10-01
