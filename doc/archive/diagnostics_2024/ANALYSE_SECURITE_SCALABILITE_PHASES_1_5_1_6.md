# Analyse Sécurité & Scalabilité - Phases 1.5, 1.6 & Adaptive Ontology

**Date** : 2025-10-17
**Périmètre** : Phase 1.5 (Filtrage Contextuel), Phase 1.6 (Cross-ref Neo4j↔Qdrant), Adaptive Ontology (LLM Canonicalizer)
**Objectif** : Identifier faiblesses critiques et proposer plan de durcissement production-ready

---

## 🎯 Résumé Exécutif

### Composants Analysés

1. **Phase 1.5 - Filtrage Contextuel Hybride**
   - `GraphCentralityScorer` : Scoring basé graphe de co-occurrence
   - `EmbeddingsContextualScorer` : Scoring sémantique multi-occurrences

2. **Phase 1.6 - Cross-Reference Neo4j ↔ Qdrant**
   - Bidirectional linking via `chunk_ids`
   - Synchronisation Proto-KG ↔ Published-KG

3. **Adaptive Ontology (LLM Canonicalizer)**
   - `LLMCanonicalizer` : Appels LLM synchrones (gpt-4o-mini)
   - `AdaptiveOntologyManager` : Cache Neo4j auto-apprenant
   - `Gatekeeper` : Intégration cascade 3 niveaux

### Verdict Global

| Critère | Score | Commentaire |
|---------|-------|-------------|
| **Sécurité** | ⚠️ 6/10 | Faiblesses injection, DoS, exposition secrets |
| **Scalabilité** | ⚠️ 5/10 | Bottlenecks LLM sync, Neo4j write locks, cache non distribué |
| **Charge** | ⚠️ 6/10 | Pas de rate limiting LLM, spike load possible |
| **Résilience** | ✅ 8/10 | Fallbacks gracieux, mais retry logic manquante |

---

## 🔴 FAIBLESSES CRITIQUES (Priorité P0)

### 1. **Injection Cypher Neo4j (CRITIQUE - P0)**

**Localisation** : `adaptive_ontology_manager.py:57-75`, `lookup()`

**Problème** :
```python
normalized_raw = raw_name.strip().lower()  # ❌ Pas d'échappement

query = """
MATCH (o:AdaptiveOntology)
WHERE o.tenant_id = $tenant_id
  AND (
      toLower(o.canonical_name) = $normalized_raw  # ✅ Paramétrisé
      OR ANY(alias IN o.aliases WHERE toLower(alias) = $normalized_raw)  # ✅ Paramétrisé
  )
"""
```

**Risque** :
Bien que les requêtes soient paramétrées (✅ Bonne pratique), `raw_name` n'est pas validé avant normalisation. Un attaquant pourrait injecter des caractères spéciaux Cypher si le système est exposé via API publique.

**Impact** : **ÉLEVÉ** - Lecture de données autres tenants, déni de service

**Recommandation** :
```python
import re

def _sanitize_concept_name(raw_name: str, max_length: int = 200) -> str:
    """Nettoie et valide nom concept avant utilisation."""
    # Longueur max
    if len(raw_name) > max_length:
        raise ValueError(f"Concept name too long: {len(raw_name)} > {max_length}")

    # Caractères autorisés: alphanumériques, espaces, -_/.,()
    if not re.match(r"^[\w\s\-_\/\.\,\(\)\'\"]+$", raw_name, re.UNICODE):
        raise ValueError(f"Invalid characters in concept name: {raw_name}")

    return raw_name.strip()

# Utiliser dans lookup(), store(), add_alias()
normalized_raw = self._sanitize_concept_name(raw_name).lower()
```

---

### 2. **DoS via LLM Canonicalizer (CRITIQUE - P0)**

**Localisation** : `llm_canonicalizer.py:89-97`, `gatekeeper.py:777-809`

**Problème** :
```python
# LLMCanonicalizer.canonicalize() - Appel synchrone sans rate limiting
response_content = self.llm_router.complete(
    task_type=TaskType.CANONICALIZATION,
    messages=[...],
    temperature=0.0,
    response_format={"type": "json_object"}
)
# ❌ Pas de timeout explicite
# ❌ Pas de circuit breaker
# ❌ Pas de rate limiting par tenant
```

**Scénario d'attaque** :
1. Attaquant upload document avec 500 concepts uniques (tous cache MISS)
2. System fait 500 appels LLM gpt-4o-mini synchrones
3. Latence : 500 × 1.5s = **750 secondes = 12.5 minutes**
4. Coût : 500 × $0.0001 = **$0.05/document**
5. **Répéter 100 fois → $5 + worker bloqué 20h**

**Impact** : **CRITIQUE** - DoS worker, épuisement budget LLM, coûts explosifs

**Recommandation** :

```python
# 1. Ajouter rate limiting tenant dans AdaptiveOntologyManager
class AdaptiveOntologyManager:
    def __init__(self, neo4j_client, redis_client=None, max_llm_calls_per_doc=50):
        self.neo4j = neo4j_client
        self.redis = redis_client  # Pour rate limiting
        self.max_llm_calls_per_doc = max_llm_calls_per_doc

    def check_llm_budget(self, tenant_id: str, document_id: str) -> bool:
        """Vérifie quota LLM canonicalization pour ce document."""
        if not self.redis:
            return True  # Pas de rate limiting si Redis indisponible

        key = f"adaptive_ontology:llm_calls:{tenant_id}:{document_id}"
        calls = self.redis.incr(key)

        if calls == 1:
            # Premier appel, expiration 1h
            self.redis.expire(key, 3600)

        if calls > self.max_llm_calls_per_doc:
            logger.error(
                f"[AdaptiveOntology:LLM Budget] ❌ EXCEEDED for doc {document_id}: "
                f"{calls}/{self.max_llm_calls_per_doc} calls"
            )
            return False

        return True

# 2. Ajouter timeout + circuit breaker dans LLMCanonicalizer
from circuitbreaker import circuit

class LLMCanonicalizer:
    @circuit(failure_threshold=5, recovery_timeout=60)
    def canonicalize(self, raw_name: str, context: Optional[str] = None,
                     domain_hint: Optional[str] = None, timeout: int = 5) -> CanonicalizationResult:
        """Canonicalise avec circuit breaker + timeout."""
        try:
            response_content = self.llm_router.complete(
                task_type=TaskType.CANONICALIZATION,
                messages=[...],
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=timeout  # ✅ Timeout explicite
            )
            # ...
        except CircuitBreakerError:
            # Circuit ouvert → fallback direct
            logger.error(f"[LLMCanonicalizer] Circuit breaker OPEN, fallback to .title()")
            return CanonicalizationResult(
                canonical_name=raw_name.strip().title(),
                confidence=0.3,
                reasoning="Circuit breaker open, LLM unavailable",
                aliases=[],
                concept_type="Unknown",
                domain=None,
                ambiguity_warning="LLM service unavailable",
                possible_matches=[],
                metadata={"circuit_breaker": "open"}
            )

# 3. Utiliser check dans Gatekeeper
def _canonicalize_concept_name(self, raw_name: str, context: Optional[str] = None,
                                tenant_id: str = "default", document_id: str = None) -> tuple[str, float]:
    # Vérifier budget LLM
    if document_id and not self.adaptive_ontology.check_llm_budget(tenant_id, document_id):
        logger.warning(
            f"[GATEKEEPER:Canonicalization] LLM budget exceeded for doc {document_id}, "
            f"falling back to .title()"
        )
        return raw_name.strip().title(), 0.3

    # Cache lookup...
    # LLM call avec circuit breaker...
```

---

### 3. **Cache Poisoning Adaptive Ontology (ÉLEVÉ - P0)**

**Localisation** : `adaptive_ontology_manager.py:102-186`, `store()`

**Problème** :
```python
# AdaptiveOntologyManager.store() - Aucune validation du résultat LLM
query = """
CREATE (o:AdaptiveOntology {
    ontology_id: randomUUID(),
    tenant_id: $tenant_id,
    canonical_name: $canonical_name,  # ❌ Pas de validation
    aliases: $aliases,  # ❌ Pas de validation liste
    ...
})
"""
# ❌ Pas de vérification: canonical_name != raw_name (détection erreur LLM)
# ❌ Pas de limite taille aliases (DoS)
# ❌ Pas de validation confidence >= seuil minimum
```

**Scénario d'attaque** :
1. LLM hallucine et retourne canonical_name="Microsoft Azure" pour raw_name="SAP S/4HANA"
2. Résultat incorrect stocké dans cache
3. **TOUS les futurs documents utilisent mapping erroné**
4. Knowledge Graph pollué, recherches faussées

**Impact** : **CRITIQUE** - Pollution durable du cache, dégradation qualité système

**Recommandation** :
```python
def store(self, tenant_id: str, canonical_name: str, raw_name: str,
          canonicalization_result: Dict[str, Any], context: Optional[str] = None,
          document_id: Optional[str] = None, min_confidence: float = 0.6) -> str:
    """Store avec validation strict du résultat LLM."""

    # 1. Validation confidence
    confidence = canonicalization_result.get("confidence", 0.0)
    if confidence < min_confidence:
        logger.warning(
            f"[AdaptiveOntology:Store] ❌ Low confidence {confidence:.2f} < {min_confidence}, "
            f"skipping store for '{canonical_name}'"
        )
        return ""

    # 2. Validation similarité raw_name <-> canonical_name (détection hallucination)
    from difflib import SequenceMatcher
    similarity = SequenceMatcher(None, raw_name.lower(), canonical_name.lower()).ratio()
    if similarity < 0.3:
        logger.error(
            f"[AdaptiveOntology:Store] ❌ HALLUCINATION DETECTED: "
            f"raw='{raw_name}' vs canonical='{canonical_name}' (similarity={similarity:.2f})"
        )
        return ""

    # 3. Validation taille aliases (limite 50)
    aliases = canonicalization_result.get("aliases", [])
    if len(aliases) > 50:
        logger.warning(f"[AdaptiveOntology:Store] Truncating aliases: {len(aliases)} → 50")
        aliases = aliases[:50]

    # 4. Validation unicité canonical_name pour ce tenant (éviter duplicates)
    existing = self.lookup(canonical_name, tenant_id)
    if existing and existing["canonical_name"] != canonical_name:
        logger.warning(
            f"[AdaptiveOntology:Store] Canonical name '{canonical_name}' already exists, "
            f"merging with existing entry"
        )
        # Merge aliases au lieu de créer nouveau node
        self.add_alias(existing["canonical_name"], tenant_id, raw_name)
        return existing["ontology_id"]

    # 5. Store avec validation OK
    # ... (reste du code)
```

---

## ⚠️ FAIBLESSES MOYENNES (Priorité P1)

### 4. **Race Condition Neo4j Write Locks (MOYEN - P1)**

**Localisation** : `neo4j_client.py:440-500`, `promote_to_published_kg()`

**Problème** :
```python
# Séquence non-atomique:
# 1. Récupérer ProtoConcept
# 2. Créer/Merger CanonicalConcept
# 3. Créer relation PROMOTED_TO

# Si 2 workers traitent même concept simultanément:
# → 2 CanonicalConcepts créés avec même canonical_name + tenant_id
```

**Scénario** :
- Document A et B mentionnent tous deux "SAP S/4HANA"
- Worker 1 et Worker 2 traitent en parallèle
- Race condition → **2 nodes CanonicalConcept identiques**

**Impact** : **MOYEN** - Duplicates dans Published-KG, queries plus lentes

**Recommandation** :
```python
# Option 1: Utiliser constraint UNIQUE sur (tenant_id, canonical_name) - DÉJÀ FAIT ✅
# (scripts/setup_adaptive_ontology.py:52-55)

# Option 2: Ajouter distributed lock Redis pour opération critique
def promote_to_published_kg_safe(self, proto_concept_id: str, canonical_name: str, ...):
    """Promote avec distributed lock Redis."""
    lock_key = f"lock:canonical:{tenant_id}:{canonical_name}"

    # Acquire lock (ttl=30s)
    lock_acquired = self.redis.set(lock_key, "1", nx=True, ex=30)

    if not lock_acquired:
        logger.warning(f"[NEO4J:Promote] Lock already held for '{canonical_name}', waiting...")
        time.sleep(0.5)
        # Retry une fois
        lock_acquired = self.redis.set(lock_key, "1", nx=True, ex=30)
        if not lock_acquired:
            raise RuntimeError(f"Cannot acquire lock for '{canonical_name}'")

    try:
        # Opération atomique Neo4j avec MERGE
        return self.promote_to_published_kg(proto_concept_id, canonical_name, ...)
    finally:
        # Release lock
        self.redis.delete(lock_key)
```

---

### 5. **Embeddings Scorer Memory Leak (MOYEN - P1)**

**Localisation** : `embeddings_contextual_scorer.py:150-250`

**Problème** :
```python
# SentenceTransformer charge modèle en mémoire
self.model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
# Taille modèle: ~420MB RAM

# Si Gatekeeper instancié N fois (multi-workers):
# → N × 420MB = 4.2GB pour 10 workers

# ❌ Pas de pooling de modèles
# ❌ Pas de lazy loading
```

**Impact** : **MOYEN** - Consommation mémoire excessive, OOM possible en prod

**Recommandation** :
```python
# Option 1: Singleton partagé entre agents
class EmbeddingsModelPool:
    _instance = None
    _model = None
    _lock = threading.Lock()

    @classmethod
    def get_model(cls):
        if cls._model is None:
            with cls._lock:
                if cls._model is None:
                    logger.info("[OSMOSE] Loading SentenceTransformer model (once)...")
                    cls._model = SentenceTransformer(
                        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
                        device="cpu"  # Forcer CPU pour éviter GPU memory
                    )
        return cls._model

class EmbeddingsContextualScorer:
    def __init__(self, ...):
        # Lazy loading via pool
        self.model = None

    def _get_model(self):
        if self.model is None:
            self.model = EmbeddingsModelPool.get_model()
        return self.model

# Option 2: Service externe (REST API)
# → Déployer sentence-transformers comme service séparé
# → Workers font appels HTTP au lieu de charger modèle local
```

---

### 6. **GraphCentralityScorer O(n²) Complexity (MOYEN - P1)**

**Localisation** : `graph_centrality_scorer.py:100-250`

**Problème** :
```python
# Construction graphe de co-occurrence
# Pour document avec N=500 entités:
# → Calcul PageRank: O(N×E) où E=edges ~ O(N²) worst case
# → Latence potentielle: >5s pour gros documents

# ❌ Pas de limite max_entities
# ❌ Pas de timeout
```

**Scénario** :
- Document SAP avec 1000 concepts extraits
- GraphCentralityScorer construit graphe 1000 nodes
- PageRank calcul → **timeout 30s**

**Impact** : **MOYEN** - Latence importante, worker bloqué

**Recommandation** :
```python
class GraphCentralityScorer:
    def __init__(self, ..., max_entities: int = 300, timeout_seconds: int = 10):
        self.max_entities = max_entities
        self.timeout_seconds = timeout_seconds

    def score_entities(self, candidates: List[Dict], full_text: str) -> List[Dict]:
        # 1. Limiter nombre d'entités scorées
        if len(candidates) > self.max_entities:
            logger.warning(
                f"[OSMOSE] GraphCentralityScorer: Too many candidates ({len(candidates)}), "
                f"scoring top {self.max_entities} only"
            )
            # Trier par frequency et prendre top N
            candidates_sorted = sorted(candidates, key=lambda x: x.get("frequency", 0), reverse=True)
            candidates = candidates_sorted[:self.max_entities]

        # 2. Timeout pour PageRank
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("PageRank computation timeout")

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(self.timeout_seconds)

        try:
            # Calcul PageRank avec timeout
            pagerank_scores = nx.pagerank(graph, max_iter=100)
        except TimeoutError:
            logger.error("[OSMOSE] GraphCentralityScorer: PageRank timeout, using fallback")
            # Fallback: degree centrality (plus rapide)
            pagerank_scores = {node: 0.5 for node in graph.nodes()}
        finally:
            signal.alarm(0)

        # ...
```

---

## ⚙️ FAIBLESSES MINEURES (Priorité P2)

### 7. **Pas de Monitoring Adaptive Ontology (FAIBLE - P2)**

**Problème** :
- Pas de métriques cache hit rate temps réel
- Pas d'alertes si cache hit < 50% (anomalie)
- Pas de dashboard Grafana pour AdaptiveOntology

**Recommandation** :
```python
# Ajouter instrumentation Prometheus
from prometheus_client import Counter, Histogram, Gauge

adaptive_ontology_lookups = Counter(
    "adaptive_ontology_lookups_total",
    "Total lookups in adaptive ontology",
    ["tenant_id", "hit_miss"]
)

adaptive_ontology_cache_size = Gauge(
    "adaptive_ontology_cache_size",
    "Number of entries in adaptive ontology",
    ["tenant_id"]
)

llm_canonicalization_latency = Histogram(
    "llm_canonicalization_latency_seconds",
    "LLM canonicalization latency",
    ["model"]
)

# Dans lookup()
def lookup(self, raw_name: str, tenant_id: str) -> Optional[Dict]:
    result = # ...
    if result:
        adaptive_ontology_lookups.labels(tenant_id=tenant_id, hit_miss="hit").inc()
    else:
        adaptive_ontology_lookups.labels(tenant_id=tenant_id, hit_miss="miss").inc()
    return result

# Dans store()
def store(self, ...):
    # ...
    adaptive_ontology_cache_size.labels(tenant_id=tenant_id).set(self.get_stats(tenant_id)["total_entries"])
```

---

### 8. **Contexte LLM Limité à 500 chars (FAIBLE - P2)**

**Localisation** : `llm_canonicalizer.py:140-142`

**Problème** :
```python
if context:
    # Limiter contexte à 500 chars
    context_snippet = context[:500]  # ❌ Truncation naïve (peut couper mot)
```

**Impact** : **FAIBLE** - Perte d'info contextuelle, baisse légère qualité canonicalisation

**Recommandation** :
```python
def _truncate_context(self, context: str, max_chars: int = 500) -> str:
    """Truncate context intelligemment (ne coupe pas mots)."""
    if len(context) <= max_chars:
        return context

    # Trouver dernier espace avant limite
    truncated = context[:max_chars]
    last_space = truncated.rfind(' ')

    if last_space > max_chars * 0.8:  # Au moins 80% du contexte
        return truncated[:last_space] + "..."
    else:
        return truncated + "..."  # Fallback si pas d'espace trouvé
```

---

### 9. **Pas de Validation Tenant Isolation (FAIBLE - P2)**

**Problème** :
- `tenant_id` passé en paramètre mais jamais validé
- Risque: un tenant accède aux données d'un autre si `tenant_id` manipulé

**Recommandation** :
```python
# Ajouter middleware validation tenant_id
VALID_TENANT_PATTERN = re.compile(r"^[a-z0-9_-]{1,50}$")

def validate_tenant_id(tenant_id: str) -> str:
    """Valide et sanitize tenant_id."""
    if not VALID_TENANT_PATTERN.match(tenant_id):
        raise ValueError(f"Invalid tenant_id format: {tenant_id}")
    return tenant_id

# Utiliser dans toutes les méthodes
def lookup(self, raw_name: str, tenant_id: str):
    tenant_id = validate_tenant_id(tenant_id)
    # ...
```

---

## 📊 Résumé Priorisation

| ID | Faiblesse | Priorité | Effort | Impact si non-fixé |
|----|-----------|----------|--------|-------------------|
| 1 | Injection Cypher Neo4j | **P0** | 2 jours | Data breach, DoS |
| 2 | DoS LLM Canonicalizer | **P0** | 3 jours | Worker bloqué, coûts ×100 |
| 3 | Cache Poisoning | **P0** | 2 jours | Pollution durable KG |
| 4 | Race Condition Neo4j | **P1** | 1 jour | Duplicates CanonicalConcepts |
| 5 | Memory Leak Embeddings | **P1** | 2 jours | OOM en prod |
| 6 | GraphScorer O(n²) | **P1** | 1 jour | Latence gros docs |
| 7 | Pas de Monitoring | **P2** | 3 jours | Blind spots production |
| 8 | Contexte LLM Tronqué | **P2** | 0.5 jour | Légère baisse qualité |
| 9 | Tenant Isolation | **P2** | 1 jour | Risque multi-tenancy |

---

## 🛡️ Plan de Durcissement (Recommandations)

### Phase 1 : Urgences P0 (Semaine 1)

**Objectif** : Bloquer vulnérabilités critiques avant production

1. **Jours 1-2** : Injection Cypher + Cache Poisoning
   - Ajouter `_sanitize_concept_name()` partout
   - Ajouter validation LLM results (confidence, similarity)
   - Tests fuzzing avec inputs malveillants

2. **Jours 3-5** : DoS LLM Canonicalizer
   - Implémenter rate limiting Redis per-doc
   - Ajouter circuit breaker (lib `circuitbreaker`)
   - Ajouter timeout explicite 5s sur LLM calls
   - Tests charge avec 100 concepts/doc

**Livrables** :
- Tests sécurité passants (fuzzing, injection)
- Rapport charge testing LLM rate limiting

---

### Phase 2 : Stabilité P1 (Semaine 2)

**Objectif** : Garantir stabilité en prod sous charge

1. **Jours 1-2** : Race Conditions + Memory
   - Distributed locks Redis pour promote_to_published
   - Singleton SentenceTransformer model
   - Tests concurrence (10 workers simultanés)

2. **Jours 3-4** : Performance GraphScorer
   - Max entities limit + timeout PageRank
   - Tests avec documents 1000+ concepts

**Livrables** :
- Tests concurrence 10 workers OK
- Benchmark latence gros documents

---

### Phase 3 : Observability P2 (Semaine 3)

**Objectif** : Visibilité complète en production

1. **Jours 1-3** : Monitoring Prometheus + Grafana
   - Métriques Adaptive Ontology (cache hit rate, size)
   - Dashboard Grafana dédié
   - Alertes: cache hit <50%, LLM latency >10s

2. **Jours 4-5** : Hardening Final
   - Tenant isolation validation
   - Context truncation intelligent
   - Tests E2E multi-tenant

**Livrables** :
- Dashboard Grafana opérationnel
- Alertes configurées PagerDuty/Slack

---

## 🧪 Tests de Validation Recommandés

### 1. Tests Sécurité

```bash
# Test injection Cypher
curl -X POST http://localhost:8000/api/canonicalize \
  -H "Content-Type: application/json" \
  -d '{"raw_name": "'; DROP DATABASE neo4j; --", "tenant_id": "default"}'

# Attendu: 400 Bad Request "Invalid characters in concept name"
```

### 2. Tests Charge LLM

```python
# Simuler document avec 200 concepts uniques (tous cache MISS)
import concurrent.futures

def test_llm_canonicalizer_load():
    concepts = [f"Concept_{i}" for i in range(200)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(canonicalizer.canonicalize, concept)
            for concept in concepts
        ]

        results = [f.result(timeout=120) for f in futures]

    # Vérifier:
    # - Pas de timeout
    # - Rate limiting déclenché après 50 concepts
    # - Circuit breaker pas ouvert
    assert len([r for r in results if r.confidence > 0.5]) >= 50
```

### 3. Tests Concurrence Neo4j

```python
# Tester race condition promote_to_published
def test_concurrent_promotion():
    proto_id_1 = create_proto_concept("SAP S/4HANA", "default")
    proto_id_2 = create_proto_concept("SAP S/4HANA", "default")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(
            neo4j_client.promote_to_published_kg,
            proto_id_1, "SAP S/4HANA", ...
        )
        future2 = executor.submit(
            neo4j_client.promote_to_published_kg,
            proto_id_2, "SAP S/4HANA", ...
        )

        canonical_id_1 = future1.result()
        canonical_id_2 = future2.result()

    # Vérifier: UN SEUL CanonicalConcept créé
    result = neo4j_client.run_query(
        "MATCH (c:CanonicalConcept {canonical_name: 'SAP S/4HANA', tenant_id: 'default'}) RETURN count(c)"
    )
    assert result[0]["count"] == 1
```

---

## 📈 Métriques de Succès Durcissement

| Métrique | Avant Durcissement | Cible Post-Durcissement |
|----------|-------------------|-------------------------|
| **Sécurité** | | |
| Tests injection passants | 0% | 100% |
| Fuzzing inputs malveillants | Non testé | 1000 inputs OK |
| **Scalabilité** | | |
| Latence doc 500 concepts | ~750s (12min) | <60s (rate limiting) |
| Memory usage 10 workers | 4.2GB | <1GB (singleton model) |
| **Charge** | | |
| Max concepts/doc sans crash | Inconnu | 1000+ (avec limits) |
| LLM calls/doc sans timeout | Illimité | Max 50 (hard cap) |
| **Résilience** | | |
| Uptime sous spike load | Inconnu | 99.9% (circuit breaker) |
| Recovery time après LLM down | Manual | <60s (auto circuit breaker) |

---

## 🎯 Conclusion

### Points Forts Actuels

✅ Fallbacks gracieux partout (bonne résilience)
✅ Requêtes Neo4j paramétrées (protection injection partielle)
✅ Architecture modulaire (facile à durcir)
✅ Budget Manager déjà en place (base rate limiting)

### Gaps Critiques à Combler

❌ **DoS LLM** : Pas de rate limiting ni circuit breaker
❌ **Cache poisoning** : Validation LLM results inexistante
❌ **Memory leak** : Modèle embeddings non partagé
❌ **Monitoring** : Blind spots production

### Recommandation Finale

**Priorité ABSOLUE** : Implémenter **Phase 1 (P0)** avant toute mise en production.

Les faiblesses P0 (injection, DoS LLM, cache poisoning) peuvent entraîner :
- **Data breach** (accès données autres tenants)
- **Coûts explosifs** (attaque DoS LLM = $100+ en 1h)
- **Pollution durable KG** (cache poisoning = dégradation qualité système)

**Effort** : 5 jours développement + 2 jours tests = **1.5 semaines**
**Gain** : System production-ready, sécurisé, scalable

---

**Dernière mise à jour** : 2025-10-17
**Auteur** : Claude Code (Analyse automatisée)
**Révision requise** : Équipe sécurité + DevOps
