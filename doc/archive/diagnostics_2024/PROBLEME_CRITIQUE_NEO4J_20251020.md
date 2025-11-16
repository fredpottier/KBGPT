# PROBLÈME CRITIQUE - Neo4j Syntax Error - 2025-10-20

**Date** : 2025-10-20 12:00
**Priorité** : P0 - CRITIQUE - Bloque tout le système

---

## 🔥 Problème Critique Découvert

### Erreur Neo4j Syntax
```
{neo4j_code: Neo.ClientError.Statement.SyntaxError}
{message: Unknown operation '!=' (you probably meant to use '<>', which is the operator for inequality testing)}
```

### Cause Racine
**Neo4j 5.26.0 REJETTE l'opérateur `!=` et NÉCESSITE `<>`**

J'ai appliqué le FIX INVERSE de ce qui était nécessaire !

---

## ⚠️ Cascade de Problèmes Causés

### 1. EntityNormalizerNeo4j Cassé
**Impact** : TOUTES les queries Cypher échouent

**Fichiers affectés** :
- `src/knowbase/ontology/entity_normalizer_neo4j.py` (lignes 85, 147, 247)
- `src/knowbase/neo4j_custom/schemas.py` (lignes 218, 243, 304)

**Conséquence** :
- EntityNormalizerNeo4j ne peut pas chercher dans l'ontologie
- Fallback automatique vers LLMCanonicalizer

### 2. LLMCanonicalizer Échoue Aussi
**Erreurs observées** :
```
JSON parse error: Unterminated string starting at: line 9 column 3 (char 439)
```

**Problèmes possibles** :
1. JSON truncation (malgré max_tokens=400)
2. String escaping issues dans JSON
3. LLM retourne JSON mal formé

**Conséquence** :
- 5 échecs consécutifs
- Circuit breaker OPEN
- Tous les concepts suivants → title case fallback (confidence=0.50)

### 3. Résultat Final
**Neo4j contient** :
- "24X7" (au lieu de "24x7 Operations")
- "3Rd Party" (au lieu de "Third Party")
- "Abap Development" (correct par chance)
- "Access Control & Logging" (contient `&` → validation erreur)

**Phase 2** :
- Aucune relation typée créée (USES, REQUIRES, etc.)
- Qdrant vide (0 concepts indexés)

---

## ✅ Solution Correcte

### Action 1 : ANNULER le fix `!=` → `<>`
**REMETTRE** tous les `!=` en `<>` dans :
1. `src/knowbase/ontology/entity_normalizer_neo4j.py`
2. `src/knowbase/neo4j_custom/schemas.py`

### Action 2 : Investiguer LLMCanonicalizer JSON truncation
Malgré max_tokens=400, il y a toujours des problèmes de parsing JSON.

**Hypothèses** :
1. **JSON contient des strings avec newlines non escapées**
2. **reasoning field contient du texte avec quotes non escapées**
3. **response_format={"type": "json_object"} pas respecté par LLM**

**Solution possible** :
- Ajouter `response_format={"type": "json_object"}` explicitement
- Ou parse plus robuste avec regex cleanup

---

## 📋 Plan d'Action Immédiat

### Étape 1 : Annuler Fix Incorrect
```bash
# Remettre <> dans entity_normalizer_neo4j.py lignes 85, 147, 247
# Remettre <> dans schemas.py lignes 218, 243, 304
```

### Étape 2 : Fix LLMCanonicalizer JSON Parsing
Options :
1. **Option A** : Ajouter `response_format` explicitement
2. **Option B** : Parse plus robuste avec cleanup
3. **Option C** : Réduire complexité du schéma JSON (enlever reasoning?)

### Étape 3 : Purge + Rebuild + Test
```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (n) WHERE n.tenant_id = 'default' DETACH DELETE n
"
docker-compose build --no-cache ingestion-worker
docker-compose restart ingestion-worker
```

---

## 🎯 Métriques de Succès Attendues

### Après Fix Correct
1. ✅ EntityNormalizerNeo4j fonctionne (no syntax error)
2. ✅ LLMCanonicalizer ne déclenche PAS le circuit breaker
3. ✅ Concepts Neo4j avec noms canoniques officiels
4. ✅ Phase 2 relations créées (USES, REQUIRES, etc.)
5. ✅ Qdrant rempli avec vectors

---

## 📝 Leçons Apprises

### Erreur 1 : Confiance Aveugle Documentation
**Problème** : J'ai supposé que Neo4j moderne supportait `!=`

**Réalité** : Neo4j 5.26.0 NÉCESSITE `<>` et rejette `!=`

**Leçon** : TOUJOURS tester les queries avant déploiement

### Erreur 2 : Rebuild Sans Vérification
**Problème** : J'ai rebuild sans tester les queries

**Leçon** : Tester queries Cypher dans Neo4j shell AVANT rebuild

---

## 🔍 Commandes de Diagnostic

### Test Query Neo4j
```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (ont:OntologyEntity {tenant_id: 'default'})
WHERE ont.status <> 'auto_learned_pending'
RETURN count(ont)
"
```

Si ça marche → `<>` est correct
Si erreur → `!=` est correct

---

**Status** : CRITIQUE - Fix incorrect identifié
**Prochaine Étape** : Annuler fix + investiguer LLMCanonicalizer JSON
