# Fixes Critiques Phase 2 OSMOSE - 2025-10-22

**Status** : 🔴 BLOQUANT - 0 relations sémantiques + 0 chunks Qdrant
**Durée investigation** : 3 jours
**Fichiers concernés** : 2 fichiers Python

---

## 📊 Résumé Problèmes

| # | Problème | Impact | Fichier | Status |
|---|----------|--------|---------|--------|
| **#1** | Import path incorrect `neo4j_client` | 🔴 EXTRACT_RELATIONS crash → 0 relations | `supervisor.py:275` | ✅ Fix commit `5c5b0f0` |
| **#2** | 0 chunks Qdrant | 🔴 RAG impossible | `supervisor.py:387-465` | ✅ Fix commit `2b68743` |
| **#3** | Hallucination faux positifs acronymes | 🟠 Ontologies rejetées (IaaS, SIEM/SOAR) | `adaptive_ontology_manager.py:220-246` | ✅ Fix commit `036f806` |
| **#4** | Caractère `&` rejeté | 🟡 Concepts rejetés ("MFA & Auth") | `adaptive_ontology_manager.py:19` | ⚠️ Fix NON appliqué |

---

## 🔴 PROBLÈME #1 : Import Path Neo4j Client (CRITIQUE)

### Symptômes
```
ERROR: [SUPERVISOR] FSM step failed: No module named 'knowbase.common.neo4j_client'
```
→ EXTRACT_RELATIONS crashe systématiquement
→ **0 relations sémantiques** extraites dans Neo4j

### Cause Racine
**Ligne 275** de `src/knowbase/agents/supervisor/supervisor.py` :
```python
from knowbase.common.neo4j_client import get_neo4j_client  # ❌ FAUX
```

Le module est à : `knowbase.common.clients.neo4j_client`

### Fix Appliqué (Commit `5c5b0f0`)
```python
from knowbase.common.clients.neo4j_client import get_neo4j_client  # ✅ CORRECT
```

### Vérification Post-Fix
```bash
# Logs attendus si fix OK :
[SUPERVISOR] EXTRACT_RELATIONS: Retrieved 457 concepts from Neo4j with surface_forms
[SUPERVISOR] EXTRACT_RELATIONS: Extracted 150-300 relations in X.Xs
[SUPERVISOR] EXTRACT_RELATIONS: ✅ Wrote 150-300 new relations

# Neo4j query :
MATCH ()-[r]->()
WHERE r.tenant_id = 'default' AND type(r) <> 'CO_OCCURS_WITH'
RETURN type(r), count(*)
ORDER BY count(*) DESC
```

**Résultat attendu** : 150-300 relations sémantiques (REQUIRES, ENABLES, PART_OF, etc.)

---

## 🔴 PROBLÈME #2 : 0 Chunks dans Qdrant (CRITIQUE)

### Symptômes
```bash
curl http://localhost:6333/collections/knowbase
# points_count: 0
```
→ **RAG impossible**, recherche vectorielle non fonctionnelle

### Cause Racine
Code FINALIZE dans supervisor.py **ajouté mais jamais exécuté** car container utilise ancienne image.

### Fix Appliqué (Commit `2b68743`)
Ajout complet chunking + upload Qdrant lignes **387-465** de `supervisor.py`.

### Vérification Post-Fix
```bash
# Logs attendus si fix OK :
[SUPERVISOR] FINALIZE: Created 500-1000 chunks
[SUPERVISOR] FINALIZE: ✅ Uploaded 500-1000 chunks to Qdrant collection 'knowbase'

# Qdrant query :
curl http://localhost:6333/collections/knowbase
```

**Résultat attendu** : `points_count: 500-1000`

---

## 🟠 PROBLÈME #3 : Hallucination Faux Positifs Acronymes

### Symptômes
```
ERROR: [AdaptiveOntology:Store] ❌ HALLUCINATION DETECTED:
raw='IaaS' vs canonical='Infrastructure as a Service' (similarity=0.19, acronym=False, threshold=0.3)
raw='SIEM/SOAR' vs canonical='Security Information...' (similarity=0.16, acronym=False, threshold=0.3)
```

→ Acronymes valides rejetés → **0 ontologies** sauvegardées dans Neo4j

### Cause Racine
`is_valid_acronym()` ne gère PAS :
1. Les acronymes avec slash "/" (SIEM/SOAR)
2. Extraction correcte initiales pour acronymes courts

### Fix Appliqué (Commit `036f806`)
Ajout smart acronym detection lignes **220-246** de `adaptive_ontology_manager.py`.

### Vérification Post-Fix
```bash
# Logs attendus si fix OK :
[AdaptiveOntology:Store] ✅ Stored ontology 'IaaS' (acronym detected, sim=0.19 > 0.15)
[AdaptiveOntology:Store] ✅ Stored ontology 'SIEM/SOAR' (acronym detected, sim=0.16 > 0.15)

# Neo4j query :
MATCH (o:AdaptiveOntology) WHERE o.tenant_id = 'default' RETURN count(o)
```

**Résultat attendu** : 200-400 ontologies

---

## 🟡 PROBLÈME #4 : Caractère `&` Rejeté

### Symptômes
```
ERROR: [AdaptiveOntology:Store] Validation error: Invalid characters in concept name: MFA & Risk-Based Authentication
```

### Cause Racine
**Ligne 19** de `adaptive_ontology_manager.py` :
```python
VALID_CONCEPT_NAME_PATTERN = re.compile(r"^[\w\s\-_\/\.\,\(\)\'\"]+$", re.UNICODE)
```

Pattern n'inclut PAS le caractère `&`

### Fix à Appliquer
```python
VALID_CONCEPT_NAME_PATTERN = re.compile(r"^[\w\s\-_\/\.\,\(\)\'\"\&]+$", re.UNICODE)
#                                                                 ↑ Ajouter \&
```

### Vérification Post-Fix
```bash
# Log attendu :
[AdaptiveOntology:Store] ✅ Stored ontology 'MFA & Risk-Based Authentication'
```

---

## ✅ Plan d'Action Rebuild Propre

### Étape 1 : Vérifier Commits Git
```bash
git log --oneline -5

# Résultat attendu :
5c5b0f0 fix(relations): Corriger chemin import neo4j_client (common.clients)
2b68743 feat(chunks): Ajouter TextChunker dans FINALIZE
036f806 fix(ontology): Smart acronym detection
```

### Étape 2 : Appliquer Fix #4 (Manquant)
```bash
# Modifier ligne 19 de adaptive_ontology_manager.py
# Ajouter \& au pattern regex
```

### Étape 3 : Purge Complete + Rebuild
```bash
# Arrêter tous les services
docker-compose down

# Purger cache Docker
docker system prune -a -f

# Rebuild SANS cache
docker-compose build --no-cache ingestion-worker

# Démarrer services
docker-compose up -d

# Purger Neo4j
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain \
  "MATCH (n) WHERE n.tenant_id = 'default' DETACH DELETE n"

# Purger Redis
docker exec knowbase-redis redis-cli FLUSHALL
```

### Étape 4 : Test Import
1. Uploader document test (ex: RISE_with_SAP_Cloud_ERP_Private.pptx)
2. Surveiller logs en temps réel
3. Vérifier métriques

### Étape 5 : Validation Métriques

| Métrique | Avant Fixes | Cible Après Fixes |
|----------|-------------|-------------------|
| **Relations sémantiques Neo4j** | 0 | 150-300 |
| **Chunks Qdrant** | 0 | 500-1000 |
| **Ontologies Neo4j** | 0 | 200-400 |
| **Canonical_name=None** | 100 (18%) | 0 (0%) |
| **Hallucination faux positifs** | 6 acronymes | 0 |

---

## 🔍 Commandes Diagnostic Post-Import

```bash
# 1. Relations sémantiques
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain \
  "MATCH ()-[r]->() WHERE r.tenant_id = 'default' AND type(r) <> 'CO_OCCURS_WITH' \
   RETURN type(r) as relation_type, count(*) as count ORDER BY count DESC LIMIT 10"

# 2. Chunks Qdrant
curl -s http://localhost:6333/collections/knowbase | python -c \
  "import sys, json; data=json.load(sys.stdin); print(f\"Points: {data['result']['points_count']}\")"

# 3. Ontologies Neo4j
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain \
  "MATCH (o:AdaptiveOntology) WHERE o.tenant_id = 'default' RETURN count(o) as total"

# 4. Concepts avec canonical_name=None
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain \
  "MATCH (c:CanonicalConcept) WHERE c.tenant_id = 'default' AND c.canonical_name IS NULL RETURN count(c)"
```

---

## 📝 Notes Importantes

1. **NE PAS utiliser cache Docker** : `--no-cache` obligatoire pour rebuild
2. **Purger Neo4j ET Redis** avant chaque test pour résultats propres
3. **Vérifier timestamp image** : `docker images sap-kb-worker` doit être RÉCENT
4. **Container doit utiliser nouvelle image** : `docker ps` doit montrer creation récente

---

**Créé par** : Claude Code
**Date** : 2025-10-22
**Prochaine étape** : Rebuild propre avec validation complète
