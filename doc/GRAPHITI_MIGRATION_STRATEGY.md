# Stratégie Migration Qdrant → Graphiti

**Date**: 30 septembre 2025
**Status**: Documentation stratégie pour gros volumes

## 🔍 Diagnostic

### Problème Identifié
La migration directe de **~1000 chunks Qdrant** vers Graphiti présente des défis majeurs :

1. **Traitement LLM par entité**
   - Graphiti utilise **Claude (Anthropic)** via SDK `graphiti-core` v0.13.0
   - Chaque entité créée déclenche un appel LLM pour extraction/enrichissement
   - Limite observée : 8192 tokens output (probablement Claude 3.5 Sonnet)

2. **Performance**
   - Temps estimé : **5-10 secondes/document** (appel LLM)
   - Pour 1000 documents : **1.5 à 3 heures**
   - Coût API : ~$0.003/document → **$3-5** pour 1000 documents

3. **Complexité données Qdrant**
   - Payloads hétérogènes (champs `dict`, `str`, `int`)
   - Structure variable selon source (PPTX, PDF, Excel)
   - Nécessite conversions robustes

## 🎯 Approche POC (Immédiate)

### Migration Limitée : 50 Documents
**Script**: `data/migrate_simple.py` (version limitée)

**Objectifs**:
- ✅ Valider le processus de migration
- ✅ Tester l'intégration Graphiti end-to-end
- ✅ Démontrer les capacités du Knowledge Graph
- ✅ Mesurer temps/coût réels

**Limitations acceptables pour POC**:
- Seulement 50 chunks migrés
- Pas de relations entre documents (phase 1)
- Type d'entité unique : `DOCUMENT`

## 🚀 Stratégie Production (Future)

### Option 1: Migration Incrémentale (Recommandée)
**Principe**: Ne pas migrer l'historique, utiliser Graphiti pour le futur

```
┌─────────────────────────────────────────────┐
│  Documents Existants (~1000)                │
│  ────────────────────────────                │
│  Restent dans Qdrant                        │
│  Recherche vectorielle classique            │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  Nouveaux Documents (post-activation)       │
│  ────────────────────────────────            │
│  Ingestion → Qdrant + Graphiti              │
│  Double indexation automatique              │
└─────────────────────────────────────────────┘
```

**Avantages**:
- ✅ Pas de coût/temps migration massive
- ✅ KG se construit organiquement
- ✅ Données historiques restent disponibles (Qdrant)
- ✅ Transition progressive

**Implémentation**:
1. Modifier pipelines ingestion (`src/knowbase/ingestion/pipelines/`)
2. Ajouter step Graphiti après indexation Qdrant
3. Documenter dans CLAUDE.md

### Option 2: Migration Batch Asynchrone
**Principe**: Migration en arrière-plan avec queue

```python
# Pseudo-code
async def migrate_batch(start_offset: int, batch_size: int = 100):
    """Migre un batch de documents en background"""
    documents = qdrant.scroll(offset=start_offset, limit=batch_size)

    for doc in documents:
        # Créer job Redis
        redis.lpush("graphiti:migration:queue", json.dumps({
            "doc_id": doc.id,
            "payload": doc.payload,
            "retry_count": 0
        }))

# Worker dédié traite la queue
# Rate limiting: 10 docs/minute pour contrôler coût API
```

**Avantages**:
- ✅ Migration progressive sans bloquer l'app
- ✅ Reprise sur erreur
- ✅ Contrôle du débit (rate limiting)
- ✅ Monitoring via Redis

**Inconvénients**:
- ⚠️ Complexité infrastructure
- ⚠️ Temps total : plusieurs heures/jours
- ⚠️ Coût API incompressible

### Option 3: Migration Bulk Sans LLM
**Principe**: Insertion directe Neo4j, bypass enrichissement Graphiti

```cypher
-- Création massive entités Neo4j
UNWIND $documents AS doc
CREATE (e:Entity {
  uuid: randomUUID(),
  name: doc.name,
  entity_type: 'DOCUMENT',
  group_id: 'corporate',
  created_at: timestamp()
})
SET e += doc.attributes
```

**Avantages**:
- ✅ Très rapide : ~1000 docs en quelques secondes
- ✅ Aucun coût API LLM
- ✅ Conserve structure Graphiti (compatible)

**Inconvénients**:
- ❌ Pas d'enrichissement sémantique
- ❌ Pas d'extraction automatique relations
- ❌ Bypass l'intelligence de Graphiti

**Quand l'utiliser**:
- Restauration d'urgence depuis backup Qdrant
- Migration initiale one-shot d'archives
- Complément d'Option 1 pour documents clés

## 📊 Comparaison Options

| Critère | Option 1<br/>(Incrémental) | Option 2<br/>(Batch Async) | Option 3<br/>(Bulk Neo4j) |
|---------|------------------|------------------|----------------|
| **Temps setup** | 1 jour | 3-5 jours | 1 jour |
| **Temps migration** | N/A (pas de migration) | 3-10h | 5 minutes |
| **Coût API** | $0 | $3-5 | $0 |
| **Qualité KG** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| **Complexité** | Faible | Élevée | Moyenne |
| **Maintenance** | Facile | Moyenne | Facile |
| **Recommandé** | ✅ **OUI** | Pour gros volumes | Backup/urgence |

## 🛠️ Implémentation Recommandée

### Phase 1: POC (Actuel)
- [x] Migration 50 documents pour validation
- [ ] Mesurer temps/coût réel
- [ ] Documenter résultats

### Phase 2: Production (Semaine prochaine)
- [ ] Implémenter Option 1 (Incrémental)
- [ ] Modifier `pptx_pipeline.py`, `pdf_pipeline.py`
- [ ] Ajouter step `_index_to_graphiti()` après Qdrant
- [ ] Tests E2E avec nouveau document

### Phase 3: Migration historique (Si besoin)
- [ ] Décision: Option 2 vs Option 3
- [ ] Si Option 2 : Créer worker Redis dédié
- [ ] Si Option 3 : Script Cypher bulk + validation

## 🔧 Configuration LLM Graphiti

### Modèle Actuel
- **Provider**: Anthropic (Claude)
- **Modèle**: Non spécifié dans config → probablement **Claude 3.5 Sonnet**
- **Token limit output**: 8192 (observé dans logs)
- **API Key**: `ANTHROPIC_API_KEY` (variable env)

### Coût Estimé
- **Claude 3.5 Sonnet**: $3/M input tokens, $15/M output tokens
- **Moyenne/document**: ~2K tokens input, ~500 tokens output
- **Coût unitaire**: ~$0.006 + $0.0075 = **~$0.014/document**
- **1000 documents**: **~$14**

### Optimisation Possible
1. **Downgrade modèle**: Claude 3 Haiku ($0.25/$1.25 per M)
   - Réduction coût : **~75%** ($3.5 pour 1000 docs)
   - Qualité légèrement inférieure

2. **Batch requests**: Pas supporté natif Graphiti SDK

3. **Cache prompts**: Anthropic Prompt Caching
   - Réduction : ~90% sur tokens système
   - Nécessite SDK graphiti-core >= 0.14.0 (à vérifier)

## 📝 Scripts Disponibles

### 1. `migrate_simple.py` (POC - 50 docs)
```bash
docker exec knowbase-app bash -c "cd /data && PYTHONPATH=/app/src python migrate_simple.py"
```

### 2. `migrate_qdrant_to_graphiti.py` (Complet - non recommandé)
```bash
# ⚠️ Ne pas lancer sans limite : prendra plusieurs heures
docker exec knowbase-app bash -c "cd /data && PYTHONPATH=/app/src python migrate_qdrant_to_graphiti.py"
```

### 3. Future: `migrate_bulk_neo4j.py` (Option 3)
À créer si besoin d'urgence

## 🎯 Décision Requise

**Question clé**: Faut-il migrer l'historique Qdrant ou seulement utiliser Graphiti pour le futur ?

**Recommandation**: **Option 1 (Incrémental)** pour production normale
- Historique reste dans Qdrant (déjà indexé, performant)
- Nouveaux docs → Double indexation (Qdrant + Graphiti)
- KG se construit progressivement avec documents pertinents

**Exception**: Si besoin absolu de reconstruire KG depuis backup Qdrant → **Option 3 (Bulk)**

---

**Auteur**: Claude Code
**Review**: À faire avec l'équipe
**Next steps**: Valider POC 50 documents puis décider stratégie production