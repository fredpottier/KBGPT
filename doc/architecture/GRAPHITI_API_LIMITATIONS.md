# Limitations API Graphiti - Phase 1 Critère 1.3

**Date**: 2025-10-01
**Contexte**: Implémentation synchronisation Qdrant ↔ Graphiti

## Problème Identifié

L'API Graphiti (version zepai/graphiti:latest) présente des limitations qui empêchent certains workflows de backfill/enrichissement.

### 1. Pas de Récupération Episode par ID Custom

**Problème** :
- POST `/messages` crée un episode mais retourne uniquement `{"success": true}`
- L'UUID de l'episode n'est PAS retourné dans la réponse
- GET `/episodes/{group_id}?last_n=N` retourne des episodes avec `uuid` généré par Graphiti
- Le champ `name` dans l'episode est vide (`name: ""`)
- Pas d'endpoint GET `/episode/{uuid}` disponible

**Impact** :
```python
# ❌ IMPOSSIBLE: Récupérer un episode spécifique après création
result = graphiti_client.add_episode(group_id="test", messages=[...])
# result = {"success": true}  ← Pas d'episode_id retourné !

# Plus tard...
episode = graphiti_client.get_episode(episode_id="???")  # ← Quel ID utiliser ?
```

**Workaround Actuel** :
- Stocker `episode_id` custom dans la metadata Qdrant
- Ne PAS utiliser l'UUID Graphiti pour la récupération
- Utiliser `/search` pour requêtes sémantiques sur le knowledge graph

### 2. Backfill Entities Non Viable

**Cas d'Usage Souhaité** :
Enrichir rétroactivement les chunks Qdrant avec les entities extraites par Graphiti :

```python
# Récupérer chunks avec episode_id
chunks = qdrant.scroll(filter={"episode_id": {"$exists": True}})

# Pour chaque episode...
for episode_id in unique_episode_ids:
    # ❌ IMPOSSIBLE: Récupérer l'episode depuis Graphiti
    episode = graphiti.get_episode(episode_uuid=episode_id)

    # Extraire entities
    entities = extract_entities_from_episode(episode)

    # Enrichir chunks
    qdrant.set_payload(chunk_ids, {"entities": entities})
```

**Pourquoi Ça Ne Marche Pas** :
1. L'`episode_id` stocké dans Qdrant est notre ID custom (ex: `"test_sync_Group_Reporting_Overview_L1"`)
2. Graphiti génère ses propres UUID (ex: `"8ac0480a-fe54-425b-b81b-14b8d1e9bbdf"`)
3. Aucun mapping entre nos IDs et les UUID Graphiti
4. Pas de champ custom pour stocker notre ID dans l'episode Graphiti

**Tentatives de Fix** :
- ✅ Essayé de filtrer par `name`: le champ est vide dans l'API
- ✅ Essayé GET `/episode/{uuid}`: endpoint n'existe pas (405 Method Not Allowed)
- ❌ Impossible de récupérer episode par `source_description` ou `content`

### 3. Structure Episode Sans Facts

**Observation** :
```json
{
  "uuid": "8ac0480a-fe54-425b-b81b-14b8d1e9bbdf",
  "name": "",
  "group_id": "test_sync",
  "content": "...",
  "entity_edges": [],
  "created_at": "2025-10-01T21:11:32.499003Z"
}
```

**Problème** :
- Le champ `entity_edges` est vide alors que des entities ont été créées
- Pas de champ `facts` ou `entities` dans la réponse
- Impossible d'extraire les entities depuis l'episode récupéré

**Hypothèse** :
- Graphiti utilise un modèle asynchrone : les entities sont créées APRÈS la réponse
- Les `entity_edges` ne sont peut-être peuplés que lors de requêtes `/search`

## Solutions Implémentées

### Solution 1: Sync Metadata Uniquement (✅ Implémenté)

**Architecture** :
```
Ingestion PPTX
├─ Créer chunks → Qdrant (avec embeddings)
├─ Créer episode → Graphiti (avec entities/relations)
└─ Sync metadata bidirectionnelle:
   ├─ Qdrant chunks: {episode_id, episode_name, has_knowledge_graph}
   └─ Graphiti episode content: "Qdrant Chunks (total: 45): uuid1, uuid2..."
```

**Avantages** :
- ✅ Traçabilité bidirectionnelle fonctionnelle
- ✅ Requêtes Qdrant peuvent filtrer par `has_knowledge_graph=true`
- ✅ Requêtes Graphiti `/search` peuvent inclure context Qdrant

**Limitations** :
- ❌ Pas d'enrichissement des chunks avec entities Graphiti après coup
- ❌ Pas de canonicalisation automatique des entities dans Qdrant

### Solution 2: Utiliser `/search` Pour Enrichissement (🔄 Alternative)

**Workflow Alternatif** :
```python
# Au lieu de récupérer un episode spécifique...
# Utiliser la recherche sémantique pour obtenir entities/relations pertinentes

search_results = graphiti_client.search(
    group_id=tenant_id,
    query=chunk_text,
    num_results=10
)

# search_results contient entities/relations extraites du graph
entities = extract_entities_from_search(search_results)

# Enrichir chunk
qdrant.set_payload(chunk_id, {"related_entities": entities})
```

**Avantages** :
- ✅ Utilise l'API Graphiti disponible
- ✅ Entities contextuelles (pas juste celles d'un episode)

**Limitations** :
- ❌ Nécessite appel API pour chaque chunk (performance)
- ❌ Entities non filtrées par episode spécifique

## Recommandations

### Court Terme (Phase 1)

1. **Accepter la limitation** : Le backfill `enrich_chunks_with_entities()` n'est PAS implémentable avec l'API actuelle
2. **Documenter l'architecture réelle** : Sync metadata uniquement, pas d'enrichissement entities
3. **Valider avec tests** : Vérifier que la sync bidirectionnelle fonctionne correctement

### Moyen Terme (Phase 2-3)

1. **Proposer amélioration API Graphiti** :
   - Retourner `episode_uuid` dans POST `/messages`
   - Ajouter GET `/episode/{uuid}` avec entities complètes
   - Permettre stockage metadata custom dans episode

2. **Alternative architecture** :
   - Extraire entities AVANT l'appel Graphiti
   - Stocker entities directement dans metadata Qdrant
   - Utiliser Graphiti uniquement pour graph traversal (pas comme source entities)

### Long Terme (Production)

1. **Évaluer alternatives** :
   - Neo4j direct au lieu de Graphiti (plus de contrôle)
   - PostgreSQL + pgvector pour entities (déjà utilisé)
   - Graphiti uniquement pour visualisation, pas workflow critique

## Conclusion

L'implémentation actuelle du Critère 1.3 (Phase 1) est **fonctionnelle mais incomplète** :

✅ **Ce qui fonctionne** :
- Extraction entities/relations depuis PPTX
- Création episodes Graphiti avec knowledge graph
- Sync metadata bidirectionnelle Qdrant ↔ Graphiti
- Requêtes sémantiques sur knowledge graph via `/search`

❌ **Ce qui ne fonctionne PAS** :
- Backfill entities depuis Graphiti vers Qdrant
- Récupération episode spécifique par ID custom
- Enrichissement rétroactif des chunks avec entities Graphiti

**Statut** : Limitation documentée, contournement via metadata sync uniquement.

---

**Références** :
- Code: `src/knowbase/graphiti/backfill_entities.py` (non viable)
- API Doc: http://localhost:8300/docs (Graphiti OpenAPI)
- Architecture: `doc/architecture/ENTITIES_VS_FACTS_DISTINCTION.md`
