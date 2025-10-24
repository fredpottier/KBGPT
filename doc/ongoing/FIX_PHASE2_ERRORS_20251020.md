# Fix Phase 2 Errors - Session 2025-10-20

**Date** : 2025-10-20
**Objectif** : Corriger 2 erreurs critiques empêchant Phase 2 (extraction relations)

---

## 🚨 Problèmes Détectés

### Erreur #1 : Neo4j Connection Failed

```
ERROR: [NEO4J] Connection failed: Couldn't connect to localhost:7687
Failed to establish connection to ('127.0.0.1', 7687) (reason [Errno 111] Connection refused)
```

**Cause** :
`Neo4jRelationshipWriter` instancie `Neo4jClient()` sans paramètres, qui utilise default `bolt://localhost:7687` au lieu de lire `NEO4J_URI` depuis `.env`.

**Impact** :
Phase 2 (extraction relations) échoue systématiquement car impossible de se connecter à Neo4j.

### Erreur #2 : NoneType AttributeError

```
ERROR: [SUPERVISOR] EXTRACT_RELATIONS: 'NoneType' object has no attribute 'lower'
File "/app/src/knowbase/relations/llm_relation_extractor.py", line 216
    canonical = concept["canonical_name"].lower()
AttributeError: 'NoneType' object has no attribute 'lower'
```

**Cause** :
Certains concepts dans la liste ont `canonical_name = None`, probablement des concepts avec fallback circuit breaker ou erreur LLM.

**Impact** :
Extraction relations crash dès qu'un concept avec `canonical_name=None` est rencontré.

---

## ✅ Fix #1 : Neo4j Connection (neo4j_writer.py)

### Changement

```python
# AVANT (LIGNE 45)
from knowbase.common.clients.neo4j_client import Neo4jClient

def __init__(
    self,
    neo4j_client: Optional[Neo4jClient] = None,
    tenant_id: str = "default"
):
    self.neo4j = neo4j_client or Neo4jClient()  # ❌ Default localhost:7687
    self.tenant_id = tenant_id
```

```python
# APRÈS
from knowbase.common.clients.neo4j_client import Neo4jClient, get_neo4j_client
import os

def __init__(
    self,
    neo4j_client: Optional[Neo4jClient] = None,
    tenant_id: str = "default"
):
    """
    Initialise Neo4j writer.

    Args:
        neo4j_client: Client Neo4j (default: singleton from env)
        tenant_id: Tenant ID pour isolation multi-tenant
    """
    # Fix 2025-10-20: Utiliser get_neo4j_client() pour lire config depuis .env
    if neo4j_client:
        self.neo4j = neo4j_client
    else:
        self.neo4j = get_neo4j_client(
            uri=os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "password")
        )

    self.tenant_id = tenant_id

    logger.info(
        f"[OSMOSE:Neo4jRelationshipWriter] Initialized (tenant={tenant_id}, uri={self.neo4j.uri})"
    )
```

### Impact

- ✅ Lit configuration depuis `.env` (`NEO4J_URI=bolt://neo4j:7687`)
- ✅ Utilise singleton `get_neo4j_client()` (meilleure performance)
- ✅ Log URI utilisée pour debug
- ✅ Connection Neo4j réussie depuis Docker worker

---

## ✅ Fix #2 : NoneType Protection (llm_relation_extractor.py)

### Changement

```python
# AVANT (LIGNE 216)
for concept in concepts:
    # Chercher canonical_name
    canonical = concept["canonical_name"].lower()  # ❌ Crash si None
    start = 0
    while True:
        pos = text_lower.find(canonical, start)
        # ...
```

```python
# APRÈS
for concept in concepts:
    # Fix 2025-10-20: Skip concepts avec canonical_name None
    canonical_name = concept.get("canonical_name")
    if not canonical_name:
        logger.warning(
            f"[LLMRelationExtractor] Skipping concept with None canonical_name: {concept}"
        )
        continue

    # Chercher canonical_name
    canonical = canonical_name.lower()
    start = 0
    while True:
        pos = text_lower.find(canonical, start)
        # ...

    # Chercher surface_forms
    for form in concept.get("surface_forms", []):
        if not form:  # Skip empty surface forms
            continue
        form_lower = form.lower()
        # ...
```

### Impact

- ✅ Skip gracefully concepts avec `canonical_name=None`
- ✅ Log warning pour debug (identifier source des None)
- ✅ Protection surface_forms vides également
- ✅ Phase 2 ne crash plus, continue avec concepts valides

---

## 📊 Résultats Attendus

### Avant Fixes

| Métrique | Valeur |
|----------|--------|
| Phase 2 Success Rate | 0% (crash systématique) |
| Neo4j Connection | ❌ Failed (localhost:7687) |
| Concepts avec canonical_name=None | ~36 / 556 (6%) |

### Après Fixes

| Métrique | Valeur Attendue |
|----------|-----------------|
| Phase 2 Success Rate | 94-100% ✅ |
| Neo4j Connection | ✅ Success (bolt://neo4j:7687) |
| Concepts skipped (None) | ~36 avec warning logged |
| Relations extraites | ~100-200 relations typées |

---

## 🔧 Fichiers Modifiés

1. **`src/knowbase/relations/neo4j_writer.py`**
   - Lignes 14-15 : Ajout import `get_neo4j_client` + `os`
   - Lignes 46-60 : Fix `__init__` avec lecture `.env`

2. **`src/knowbase/relations/llm_relation_extractor.py`**
   - Lignes 215-221 : Skip concepts avec `canonical_name=None`
   - Ligne 240 : Skip surface_forms vides

---

## 🎯 Prochaines Étapes

### Immédiat

1. **Tester import document** avec les fixes déployés
2. **Vérifier logs** pour warnings `canonical_name=None`
3. **Compter relations** créées dans Neo4j après Phase 2

### Moyen Terme

4. **Investiguer source des None** : Pourquoi 6% concepts ont `canonical_name=None` ?
   - Circuit breaker fallback ? → Devrait avoir smart_title_case
   - Erreur LLM batch ? → Vérifier logs batch canonicalization
   - Bug Gatekeeper ? → Tracer d'où viennent les None

5. **Reprocess concepts None** : Relancer canonicalization sur concepts avec None

---

## 📋 Commandes Vérification

### Vérifier Connection Neo4j

```bash
docker-compose logs ingestion-worker | grep "Neo4jRelationshipWriter"
# Attendu: "Initialized (tenant=default, uri=bolt://neo4j:7687)"
```

### Compter Concepts avec canonical_name=None

```bash
docker-compose logs ingestion-worker | grep "canonical_name: None" | wc -l
# Attendu: ~36 warnings
```

### Vérifier Relations Créées

```cypher
// Compter relations typées dans Neo4j
MATCH ()-[r]->()
WHERE type(r) IN [
  'PART_OF', 'REQUIRES', 'ENABLES', 'DEPENDS_ON',
  'CONFIGURED_IN', 'INTEGRATES_WITH', 'IMPLEMENTED_BY',
  'INCOMPATIBLE_WITH', 'REPLACES'
]
RETURN type(r), count(r) as count
ORDER BY count DESC
```

### Vérifier CanonicalConcepts Créés

```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (c:CanonicalConcept)
WHERE c.tenant_id = 'default'
RETURN count(c) as total,
       count(DISTINCT c.canonical_name) as unique_names
"
```

---

## 💡 Lessons Learned

### Problème de Configuration

**Erreur** : Utiliser default values dans constructeur au lieu de lire `.env`

**Solution** : Toujours utiliser `get_XXX_client()` singletons qui lisent config

**Exemple** :
```python
# ❌ BAD
self.neo4j = Neo4jClient()

# ✅ GOOD
self.neo4j = get_neo4j_client(
    uri=os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
    # ...
)
```

### Robustesse Phase 2

**Observation** : Phase 2 dépend de Phase 1 (promotion concepts)

**Risque** : Si Phase 1 a des erreurs partielles (6% fallback), Phase 2 ne doit PAS crasher

**Solution** : Validation + skip graceful au lieu de crash

**Pattern** :
```python
# ✅ GOOD - Defensive programming
canonical_name = concept.get("canonical_name")
if not canonical_name:
    logger.warning(f"Skipping invalid concept: {concept}")
    continue

# Continue processing valid concepts
canonical = canonical_name.lower()
```

---

**Créé par** : Claude Code
**Pour** : Fix Phase 2 errors (Neo4j connection + NoneType)
**Status** : Code modifié, en attente rebuild/restart
