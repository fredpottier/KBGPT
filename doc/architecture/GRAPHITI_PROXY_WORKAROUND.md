# GraphitiProxy - Workaround API Limitations

**Date création**: 2025-10-02
**Référence issue**: https://github.com/fredpottier/KBGPT/issues/18
**Statut**: Workaround temporaire - À SUPPRIMER si API Graphiti corrigée upstream

---

## 🎯 Problème

L'API Graphiti (version zepai/graphiti:latest) présente des limitations critiques qui bloquent certains workflows:

### Limitation 1: POST /messages ne retourne pas episode_uuid

**Symptôme**:
```python
result = graphiti_client.add_episode(
    group_id="tenant_1",
    messages=[...]
)
# result = {"success": true}  ← Pas d'episode_uuid !
```

**Impact**:
- Impossible de lier chunks Qdrant à episode Graphiti immédiatement
- Pas de traçabilité bidirectionnelle Qdrant ↔ Graphiti
- Workflow de backfill entities bloqué

### Limitation 2: GET /episode/{uuid} n'existe pas

**Symptôme**:
```bash
GET http://graphiti:8300/episode/abc-123
# 405 Method Not Allowed
```

**Impact**:
- Impossible de récupérer episode par UUID Graphiti
- Pas de récupération par custom_id
- Enrichissement rétroactif impossible

### Limitation 3: Pas de mapping custom_id ↔ graphiti_uuid

**Symptôme**:
- API ne permet pas de stocker metadata custom dans episode
- Champ `name` vide dans réponse
- Pas de lien entre notre ID et UUID Graphiti

**Impact**:
- Impossible de retrouver episode créé avec nos IDs métier
- Migration données existantes bloquée

---

## ✅ Solution: GraphitiProxy

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Application Code                       │
│  (pptx_pipeline_kg.py, migration, etc.)                 │
└────────────────┬────────────────────────────────────────┘
                 │
                 │ get_graphiti_service()
                 ▼
┌─────────────────────────────────────────────────────────┐
│              GraphitiFactory                             │
│                                                          │
│  if GRAPHITI_USE_PROXY=true:                            │
│    return GraphitiProxy(client)  ← Enrichi              │
│  else:                                                   │
│    return GraphitiClient         ← Standard             │
└────────────────┬────────────────────────────────────────┘
                 │
                 ├─────────────────┬────────────────────────┐
                 ▼                 ▼                        ▼
      ┌──────────────────┐ ┌──────────────┐   ┌───────────────────┐
      │  GraphitiProxy   │ │   Cache      │   │  GraphitiClient   │
      │   (enrichi)      │ │ (disque+RAM) │   │   (standard)      │
      └──────────────────┘ └──────────────┘   └───────────────────┘
                 │                                        │
                 └────────────────┬───────────────────────┘
                                  ▼
                        ┌──────────────────┐
                        │  Graphiti API    │
                        │  (zepai/graphiti)│
                        └──────────────────┘
```

### Composants

#### 1. GraphitiProxy (`src/knowbase/graphiti/graphiti_proxy.py`)

**Fonctionnalités**:

**add_episode() enrichi**:
```python
# Standard (client Graphiti)
result = client.add_episode(...)
# {"success": true}  ← PAS d'episode_uuid

# GraphitiProxy
result = proxy.add_episode(..., custom_id="my_episode_001")
# {
#   "success": true,
#   "episode_uuid": "abc-123-def",  ← ENRICHI
#   "custom_id": "my_episode_001",
#   "created_at": "2025-10-02T...",
#   ...
# }
```

**Mécanisme**:
1. Appelle `client.add_episode()` (API standard)
2. Immédiatement après, appelle `client.get_episodes(last_n=1)` pour récupérer UUID
3. Enrichit réponse avec `episode_uuid`
4. Sauvegarde mapping `custom_id ↔ episode_uuid` dans cache

**get_episode() par custom_id ou UUID**:
```python
# Par custom_id
episode = proxy.get_episode("my_episode_001")

# Par UUID Graphiti
episode = proxy.get_episode("abc-123-def-456")
```

**Mécanisme**:
- Si `custom_id`: Récupère UUID depuis cache, puis cherche episode
- Si `uuid`: Cherche directement dans episodes récents (via `get_episodes(last_n=100)`)

**Cache persistant**:
- Fichiers JSON: `/data/graphiti_cache/{custom_id}.json`
- Structure:
  ```json
  {
    "custom_id": "tenant_1_episode_001",
    "episode_uuid": "abc-123-def",
    "group_id": "tenant_1",
    "created_at": "2025-10-02T12:00:00Z",
    "cached_at": "2025-10-02T12:00:01Z",
    "metadata": {
      "name": "Episode Name",
      "content_length": 5000,
      "entity_edges_count": 42
    }
  }
  ```

**Proxy transparent**:
- Méthodes non-interceptées (`search`, `get_episodes`, etc.) sont déléguées au client standard
- Utilisation transparente: `proxy.search(...)` = `client.search(...)`

#### 2. GraphitiFactory (`src/knowbase/graphiti/graphiti_factory.py`)

**Feature flag**:
```python
from knowbase.graphiti.graphiti_factory import get_graphiti_service

# Retourne proxy OU client selon env var
graphiti = get_graphiti_service()
```

**Variables d'environnement**:
```bash
# Activer proxy (défaut: true)
GRAPHITI_USE_PROXY=true

# Dossier cache (défaut: /data/graphiti_cache)
GRAPHITI_CACHE_DIR=/data/graphiti_cache

# Activer cache disque (défaut: true)
GRAPHITI_CACHE_ENABLED=true
```

**Basculement dynamique**:
```python
# Force proxy
graphiti = get_graphiti_service(use_proxy=True)

# Force client standard
graphiti = get_graphiti_service(use_proxy=False)
```

---

## 📋 Usage

### 1. Configuration (.env)

**Activer proxy** (recommandé):
```bash
GRAPHITI_USE_PROXY=true
GRAPHITI_CACHE_ENABLED=true
GRAPHITI_CACHE_DIR=/data/graphiti_cache
```

**Désactiver proxy** (fallback si problèmes):
```bash
GRAPHITI_USE_PROXY=false
```

### 2. Code Application

**Migration depuis get_graphiti_client()**:
```python
# AVANT
from knowbase.graphiti.graphiti_client import get_graphiti_client
graphiti = get_graphiti_client()

# APRÈS
from knowbase.graphiti.graphiti_factory import get_graphiti_service
graphiti = get_graphiti_service()  # Retourne proxy ou client selon config
```

**Création episode**:
```python
result = graphiti.add_episode(
    group_id="tenant_1",
    messages=[{"content": "...", "role_type": "user"}],
    custom_id="my_custom_episode_001"  # ← IMPORTANT pour mapping
)

# Si proxy activé
print(result["episode_uuid"])  # "abc-123-def"
print(result["custom_id"])     # "my_custom_episode_001"

# Si client standard
print(result.get("episode_uuid"))  # None (pas enrichi)
```

**Récupération episode**:
```python
# Par custom_id (si proxy activé)
episode = graphiti.get_episode("my_custom_episode_001")

# Par UUID Graphiti
episode = graphiti.get_episode("abc-123-def-456")
```

**Transparence**:
```python
# Méthodes non-modifiées fonctionnent normalement
results = graphiti.search(query="SAP S/4HANA")
episodes = graphiti.get_episodes(group_id="tenant_1", last_n=10)
```

### 3. Cache Management

**Nettoyer cache spécifique**:
```python
graphiti.clear_cache(custom_id="my_episode_001")
```

**Nettoyer tout le cache**:
```python
graphiti.clear_cache()
```

**Vérifier cache**:
```python
episode_uuid = graphiti.get_episode_uuid(custom_id="my_episode_001")
if episode_uuid:
    print(f"Trouvé dans cache: {episode_uuid}")
```

---

## 🧪 Tests

**Fichier**: `tests/graphiti/test_graphiti_proxy.py`

**Tests implémentés** (14 tests):
1. add_episode enrichit réponse avec episode_uuid
2. add_episode génère custom_id si non fourni
3. get_episode par custom_id depuis cache
4. get_episode par UUID Graphiti
5. Cache persiste entre instances
6. Cache peut être désactivé
7. clear_cache() nettoie cache
8. Fallback gracieux si API error
9. _is_uuid() détecte UUIDs
10. Proxy transparent pour méthodes non-interceptées
11. Factory retourne proxy si env=true
12. Factory retourne client standard si env=false
13. is_proxy_enabled() lit env var
14. EpisodeCacheEntry.to_dict()

**Exécution**:
```bash
pytest tests/graphiti/test_graphiti_proxy.py -v
```

---

## ⚠️ Limitations & Considérations

### Limitations

1. **Performance**: Appel supplémentaire `get_episodes(last_n=1)` après chaque création (+50-100ms)
2. **Scale**: get_episode() par UUID limite à 100 derniers episodes (limitation API)
3. **Race conditions**: Si 2 episodes créés simultanément, UUID récupéré peut être incorrect
4. **Cache growth**: Cache peut grossir indéfiniment (prévoir nettoyage périodique)

### Recommandations

1. **Toujours fournir custom_id** lors de add_episode():
   ```python
   # ✅ BON
   result = graphiti.add_episode(..., custom_id="tenant_doc_20251002")

   # ⚠️ ÉVITER (custom_id auto-généré, moins lisible)
   result = graphiti.add_episode(...)
   ```

2. **Monitorer taille cache**:
   ```bash
   du -sh /data/graphiti_cache
   ```

3. **Nettoyage périodique** (cron):
   ```bash
   # Supprimer cache > 30 jours
   find /data/graphiti_cache -name "*.json" -mtime +30 -delete
   ```

4. **Logs surveillance**:
   ```bash
   docker-compose logs app | grep "GraphitiProxy"
   ```

---

## 🔄 Migration Plan (si API upstream corrigée)

### Indicateurs API corrigée

1. **POST /messages retourne episode_uuid**:
   ```bash
   curl -X POST http://graphiti:8300/messages \
     -H "Content-Type: application/json" \
     -d '{"group_id": "test", "messages": [...]}'

   # Si réponse contient "episode_uuid" → API corrigée
   ```

2. **GET /episode/{uuid} disponible**:
   ```bash
   curl http://graphiti:8300/episode/abc-123
   # Si 200 OK → API corrigée
   ```

### Steps Migration

1. **Tester API upstream**:
   ```bash
   # Vérifier version Graphiti
   docker-compose exec graphiti cat /app/version.txt

   # Tester endpoints
   pytest tests/graphiti/test_graphiti_api_improvements.py
   ```

2. **Basculer vers client standard**:
   ```bash
   # .env
   GRAPHITI_USE_PROXY=false
   ```

3. **Valider sans proxy**:
   ```bash
   # Tests end-to-end
   pytest tests/ingestion/test_pptx_pipeline_kg.py -v
   ```

4. **Supprimer code proxy**:
   ```bash
   git rm src/knowbase/graphiti/graphiti_proxy.py
   git rm src/knowbase/graphiti/graphiti_factory.py
   git rm tests/graphiti/test_graphiti_proxy.py

   # Remplacer appels
   sed -i 's/get_graphiti_service/get_graphiti_client/g' \
     src/knowbase/ingestion/pipelines/pptx_pipeline_kg.py
   ```

5. **Nettoyer cache**:
   ```bash
   rm -rf /data/graphiti_cache
   ```

---

## 📊 Métriques & Monitoring

### Métriques utiles

```python
# Taux de réussite enrichissement
graphiti_proxy_enrichment_success_rate = episodes_enriched / episodes_created

# Taux hit cache
graphiti_proxy_cache_hit_rate = cache_hits / total_lookups

# Taille cache
graphiti_proxy_cache_size_mb = du /data/graphiti_cache
```

### Logs clés

```bash
# Succès enrichissement
[GraphitiProxy] Episode created successfully - custom_id=X, episode_uuid=Y

# Cache hit
[GraphitiProxy] Found in cache: custom_id → episode_uuid

# Fallback
[GraphitiProxy] Could not retrieve episode_uuid - Returning standard result

# Warning temporaire
[GraphitiProxy] Workaround temporaire - Surveiller GitHub issue #18
```

---

## 🔗 Références

- **GitHub Issue**: https://github.com/fredpottier/KBGPT/issues/18
- **Code Proxy**: `src/knowbase/graphiti/graphiti_proxy.py`
- **Code Factory**: `src/knowbase/graphiti/graphiti_factory.py`
- **Tests**: `tests/graphiti/test_graphiti_proxy.py`
- **Usage**: `src/knowbase/ingestion/pipelines/pptx_pipeline_kg.py:793`

---

**IMPORTANT**: Ce code est un **workaround temporaire**. Il doit être supprimé dès que l'API Graphiti upstream sera corrigée. Surveiller l'issue GitHub #18 pour updates.
