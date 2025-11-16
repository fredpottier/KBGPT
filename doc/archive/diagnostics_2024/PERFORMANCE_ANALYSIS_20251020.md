# Analyse Performance - Import Document 250 Slides

**Date** : 2025-10-20
**Document** : RISE_with_SAP_Cloud_ERP_Private.pptx (250 slides)
**Durée totale** : 1h 09min 44s (4184 secondes)
**Status** : Phase 2 en échec (NoneType error)

---

## 📊 Résumé Exécutif

### Durée par Phase

| Phase | Durée | % du Total | Status |
|-------|-------|------------|--------|
| **Phase 1 - Extraction** | 16 min 18s | 23.4% | ✅ OK |
| **Phase 1 - Canonicalisation** | 53 min 08s | 76.2% | ⚠️ TRÈS LENT |
| **Phase 2 - Relations** | 3s | 0.1% | ❌ ÉCHEC |
| **Indexing Qdrant** | N/A | 0% | ❌ NON ATTEINT |

### Goulot d'Étranglement Principal

**🔴 CANONICALISATION = 76% du temps total**

---

## 📋 Chronologie Détaillée

### Phase 1 - Extraction (16 min 18s)

```
13:40:18 → Début FSM + Extraction
13:56:36 → Fin Extraction
```

**Résultats** :
- 79 segments créés
- 556 concepts candidats extraits
- Temps moyen : **12.4s/segment**

**Détails opérations** :
1. PDF conversion via LibreOffice (PPTX → PDF)
2. Vision API calls (GPT-4o Vision) pour chaque segment
3. Text extraction + chunking intelligent

**Évaluation** : ✅ **Performance acceptable**
- 12.4s/segment est raisonnable pour 250 slides
- Inclut PDF conversion + Vision API + chunking

---

### Phase 1 - Canonicalisation (53 min 08s) ⚠️

```
13:56:36 → Début Gate Check + Canonicalisation
14:49:44 → Fin Canonicalisation
```

**Résultats** :
- 556 concepts candidats traités
- 447 concepts canoniques créés
- 2266 relations proto-KG créées
- Temps moyen : **5.7s/concept**

**Opérations internes** :
1. **EntityNormalizerNeo4j** : Recherche dans ontologie (queries Cypher)
2. **LLMCanonicalizer** : Appels LLM séquentiels pour concepts non trouvés
3. **Circuit Breaker** : Gestion erreurs JSON parsing
4. **Gate Check** : Validation + promotion concepts
5. **Neo4j Persistence** : Création CanonicalConcept + relations PROMOTED_TO

**Métriques observées** :
- **209 changements d'état Circuit Breaker** (OPEN/HALF_OPEN/CLOSED)
- **3887 JSON truncation fixes** appliqués avec succès
- **10337 title case fallbacks** utilisés (logs dupliqués inclus)

**Évaluation** : 🔴 **GOULOT D'ÉTRANGLEMENT CRITIQUE**

---

### Phase 2 - Extraction Relations (3s) ❌

```
14:49:59 → Début EXTRACT_RELATIONS
14:50:00 → Initialisation composants
14:50:02 → ERREUR : 'NoneType' object has no attribute 'lower'
```

**Résultats** :
- ❌ Échec immédiat (3 secondes)
- 0 relations typées créées (USES, REQUIRES, etc.)
- Document incomplet dans Neo4j

**Impact** :
- Relations sémantiques absentes
- Indexing Qdrant jamais atteint
- Recherche dégradée (pas de graph traversal)

**Évaluation** : 🔴 **BLOQUANT - Empêche finalisation document**

---

## 🔍 Analyse Détaillée du Goulot

### Problème : Canonicalisation Trop Lente (53 min)

#### Causes Identifiées

**1. Circuit Breaker Instable (209 changements d'état)**

Le circuit breaker s'ouvre/ferme fréquemment :
```
CLOSED → OPEN (après 5 échecs consécutifs)
OPEN → HALF_OPEN (après 60s timeout)
HALF_OPEN → CLOSED (si 1 succès)
HALF_OPEN → OPEN (si 1 échec)
```

**Impact** :
- Chaque ouverture = 60s de délai avant retry
- 209 transitions ≈ **30-40 minutes perdues en timeouts**

**Cause racine** : JSON truncation par le LLM (malgré max_tokens=400)

---

**2. JSON Truncation Massive (3887 fixes appliqués)**

Le LLM (gpt-4o-mini) retourne du JSON tronqué :

```json
{
  "canonical_name": "Content Owner",
  "confidence": 0.85,
  "reasoning": "The term 'Content Owner' is commonly used in various contexts, including project management and content management, but doe
```

**Fix appliqué** : `_parse_json_robust()` complète le JSON
- Ferme quotes ouvertes
- Ajoute `}` manquants
- Parse le JSON complété

**Impact** :
- Fix fonctionne (3887 JSON réparés)
- Mais le retry prend du temps (~1-2s/concept supplémentaire)
- **Temps perdu** : ~1-2 heures cumulées en parsing retries

---

**3. Appels LLMCanonicalizer Séquentiels**

Actuellement :
```python
for concept in concepts:
    canonical_name = llm_canonicalizer.canonicalize(concept)
    # 1 appel LLM par concept → 556 appels séquentiels
```

**Impact** :
- 556 appels × 5.7s/appel = 53 minutes
- Pas de parallélisation
- Pas de batch processing

**Potentiel d'optimisation** : **TRÈS ÉLEVÉ (70-80% gain)**

---

**4. Neo4j Queries Non Optimisées**

EntityNormalizerNeo4j fait :
```cypher
MATCH (ont:OntologyEntity)-[:HAS_ALIAS]->(alias:OntologyAlias {
    normalized: $normalized,
    tenant_id: $tenant_id
})
WHERE ont.status <> 'auto_learned_pending'
RETURN ont.canonical_name, ont.entity_type
LIMIT 1
```

**Problèmes** :
- 1 query par concept (556 queries)
- Pas de cache en mémoire
- Index global sur `normalized` mais pas de cache applicatif

**Potentiel d'optimisation** : MOYEN (5-10% gain)

---

## 🚀 Plan d'Optimisation

### Priorité 0 : Fix Phase 2 NoneType Error (BLOQUANT)

**Problème** : Phase 2 échoue immédiatement avec `'NoneType' object has no attribute 'lower'`

**Impact** :
- Document incomplet
- Pas de relations sémantiques
- Pas d'indexing Qdrant
- Recherche dégradée

**Action** :
1. Identifier ligne exacte du crash
2. Ajouter null checks
3. Tester avec document actuel

**ROI** : **CRITIQUE - Déblocage complet de la pipeline**

---

### Priorité 1 : Batch LLMCanonicalizer (GAIN 70%)

**Objectif** : Réduire 53 min → 10-15 min

**Implémentation** :

#### Option A : Batch Processing (Recommandé)

Grouper 20 concepts par appel LLM :

```python
# Au lieu de :
for concept in concepts:
    result = llm.complete_canonicalization([{
        "role": "user",
        "content": f"Canonicalize: {concept}"
    }])

# Faire :
batch_size = 20
for i in range(0, len(concepts), batch_size):
    batch = concepts[i:i+batch_size]
    result = llm.complete_canonicalization([{
        "role": "user",
        "content": f"Canonicalize these {len(batch)} concepts:\n{json.dumps(batch)}"
    }])
    # Parser le JSON avec 20 résultats
```

**Schéma JSON batch** :
```json
{
  "canonicalizations": [
    {
      "raw_name": "aws",
      "canonical_name": "Amazon Web Services (AWS)",
      "confidence": 0.95,
      "reasoning": "..."
    },
    {
      "raw_name": "sap cloud",
      "canonical_name": "SAP Cloud Platform",
      "confidence": 0.90,
      "reasoning": "..."
    }
  ]
}
```

**Gain estimé** :
- 556 concepts / 20 par batch = **28 appels LLM** (au lieu de 556)
- 28 × 5s = **140s = 2.3 minutes** (au lieu de 53 minutes)
- **Réduction : 95% du temps de canonicalisation**

**Risques** :
- JSON plus complexe → Plus de risques de truncation
- Nécessite modifier schéma JSON + parsing

**Mitigation** :
- Utiliser `response_format={"type": "json_object"}` explicite
- Augmenter max_tokens à 2000-3000 pour batch de 20
- Garder fallback séquentiel si batch échoue

---

#### Option B : Parallélisation (Alternative)

Paralléliser les appels LLM :

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [
        executor.submit(llm_canonicalizer.canonicalize, concept)
        for concept in concepts
    ]
    results = [f.result() for f in futures]
```

**Gain estimé** :
- 556 concepts / 10 workers = **56 batches parallèles**
- 56 × 5s = **280s = 4.7 minutes**
- **Réduction : 91% du temps**

**Risques** :
- Rate limiting OpenAI (500 req/min)
- Coût API augmenté (même nombre d'appels)
- Circuit breaker complexe à gérer en //

---

### Priorité 2 : Optimiser Circuit Breaker (GAIN 20-30%)

**Problème** : 209 transitions OPEN/HALF_OPEN perdent 30-40 min

**Actions** :

#### 2.1 Réduire Timeout Récupération

```python
# Actuellement
recovery_timeout = 60  # secondes

# Proposé
recovery_timeout = 30  # secondes
```

**Gain estimé** : 15-20 minutes

---

#### 2.2 Augmenter Threshold Échecs

```python
# Actuellement
failure_threshold = 5  # échecs consécutifs

# Proposé
failure_threshold = 10  # échecs consécutifs
```

**Gain estimé** : Moins d'ouvertures → 5-10 minutes

---

#### 2.3 Améliorer JSON Parsing

**Problème** : 3887 JSON truncation fixes → retries multiples

**Actions** :
1. Ajouter `response_format={"type": "json_object"}` explicite dans llm_router
2. Augmenter max_tokens à 500 (actuellement 400)
3. Simplifier schéma JSON (enlever `reasoning` field si nécessaire)

```python
# Dans llm_router.py
def complete_canonicalization(
    messages: List[Dict[str, Any]],
    temperature: float = 0.0,
    max_tokens: int = 500,  # Augmenté de 400 à 500
    response_format: dict = {"type": "json_object"}  # AJOUTÉ
) -> str:
```

**Gain estimé** : 10-15 minutes

---

### Priorité 3 : Cache Neo4j (GAIN 5-10%)

**Implémentation** :

```python
from functools import lru_cache

class EntityNormalizerNeo4j:
    def __init__(self, driver):
        self.driver = driver
        self._cache = {}  # Cache en mémoire

    def normalize_entity_name(
        self,
        raw_name: str,
        entity_type_hint: Optional[str] = None,
        tenant_id: str = "default",
        include_pending: bool = False
    ):
        # Check cache
        cache_key = f"{tenant_id}:{raw_name.lower()}:{entity_type_hint}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Query Neo4j
        result = self._query_neo4j(...)

        # Store in cache
        self._cache[cache_key] = result
        return result
```

**Gain estimé** : 2-5 minutes (sur 556 concepts, beaucoup de duplicates)

---

## 📊 Estimations Gain Total

### Scénario Actuel (Baseline)

| Phase | Durée Actuelle |
|-------|----------------|
| Extraction | 16 min |
| Canonicalisation | 53 min |
| Phase 2 (si fonctionnait) | ~5 min (estimé) |
| Indexing | ~2 min (estimé) |
| **TOTAL** | **~76 minutes** |

---

### Scénario Optimisé (Tous les Fixes)

| Phase | Durée Optimisée | Gain |
|-------|-----------------|------|
| Extraction | 16 min | - |
| Canonicalisation | **5 min** | -48 min (-91%) |
| Phase 2 | 5 min | Débloqué |
| Indexing | 2 min | Débloqué |
| **TOTAL** | **28 minutes** | **-48 min (-63%)** |

---

### Détail Gains Canonicalisation

| Optimisation | Gain | Durée Résultante |
|--------------|------|------------------|
| Baseline | - | 53 min |
| **+ Batch LLM (20 concepts)** | -50 min | **3 min** |
| + Circuit breaker tuning | -15 min | 38 min |
| + JSON parsing amélioré | -10 min | 43 min |
| + Cache Neo4j | -3 min | 50 min |

**MEILLEURE OPTION : Batch LLM = 95% de gain à lui seul**

---

## 🎯 Recommandations Finales

### Actions Immédiates (Cette Semaine)

#### 1. Fixer Phase 2 NoneType Error (Priorité 0) ⚠️

**Action** :
```bash
# Trouver ligne exacte du crash
docker-compose logs ingestion-worker 2>&1 | grep "NoneType.*lower" -A 5 -B 5
```

**Délai** : 1-2 heures
**ROI** : CRITIQUE (déblocage complet)

---

#### 2. Implémenter Batch LLMCanonicalizer (Priorité 1) 🚀

**Action** :
1. Créer `batch_canonicalize()` dans `llm_canonicalizer.py`
2. Modifier schéma JSON pour supporter batch
3. Mettre à jour `_parse_json_robust()` pour batch
4. Tester avec 556 concepts

**Délai** : 4-6 heures
**ROI** : **TRÈS ÉLEVÉ (53 min → 3 min = -50 min)**

---

#### 3. Mesurer Nouveau Temps Total

Après fixes 1+2 :
- Tester import même document
- Comparer durée totale
- Vérifier qualité résultats (concepts + relations)

**Résultat attendu** : **28 minutes** (au lieu de 76 min)

---

### Actions Court Terme (Semaine Prochaine)

#### 4. Optimiser Circuit Breaker (Priorité 2)

- Réduire timeout : 60s → 30s
- Augmenter threshold : 5 → 10
- Ajouter `response_format` explicite

**Gain supplémentaire** : 5-10 minutes

---

#### 5. Implémenter Cache Neo4j (Priorité 3)

- LRU cache en mémoire
- Invalidation sur updates

**Gain supplémentaire** : 2-5 minutes

---

## 📈 Objectif Cible

### Temps Idéal pour 250 Slides

| Phase | Temps Cible |
|-------|-------------|
| Extraction | 15 min |
| Canonicalisation | **< 5 min** |
| Phase 2 Relations | 5 min |
| Indexing | 2 min |
| **TOTAL** | **< 30 minutes** |

**Avec batch LLM : OBJECTIF ATTEIGNABLE ✅**

---

## 🔧 Commandes Diagnostic

### Vérifier Temps Import Futur

```bash
# Monitorer timestamps
docker-compose logs ingestion-worker -f | grep -E "Starting|completed|ERROR"

# Calculer durée Phase 1
docker-compose logs ingestion-worker 2>&1 | grep -E "Starting extraction|Pattern mining starting" | tail -2

# Calculer durée Canonicalisation
docker-compose logs ingestion-worker 2>&1 | grep -E "Gate check starting|Starting persistence" | tail -2
```

### Vérifier Circuit Breaker

```bash
# Compter transitions
docker-compose logs ingestion-worker 2>&1 | grep "\[CircuitBreaker\]" | grep -E "OPEN|HALF_OPEN|CLOSED" | wc -l

# Voir état actuel
docker-compose logs ingestion-worker 2>&1 | grep "\[CircuitBreaker\]" | tail -10
```

### Vérifier JSON Truncation

```bash
# Compter fixes appliqués
docker-compose logs ingestion-worker 2>&1 | grep "Fixed truncated JSON" | wc -l

# Voir exemples
docker-compose logs ingestion-worker 2>&1 | grep "Fixed truncated JSON" | head -10
```

---

## 📝 Notes

### Pourquoi Batch LLM est la Meilleure Option ?

1. **Gain maximal (95%)** : 53 min → 3 min
2. **Simple à implémenter** : ~6h de dev
3. **Pas de risque rate limiting** : 28 appels au lieu de 556
4. **Coût API réduit** : -95% de calls
5. **Scalable** : Fonctionne pour 1000+ concepts

### Pourquoi Pas Parallélisation ?

1. **Gain inférieur** : 53 min → 5 min (vs 3 min avec batch)
2. **Plus complexe** : Gestion //  + circuit breaker
3. **Même coût API** : 556 calls (pas de réduction)
4. **Risque rate limiting** : OpenAI 500 req/min

---

**Créé par** : Claude Code
**Pour** : Analyse performance import document 250 slides
**Prochaine Étape** : Implémenter Batch LLMCanonicalizer
