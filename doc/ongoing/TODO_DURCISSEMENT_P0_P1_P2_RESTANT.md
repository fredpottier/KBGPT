# TODO Durcissement P0-P1-P2 - Implémentations Restantes

**Date** : 2025-10-17
**Status** : Phase 1/3 complétée (P0.1 + P0.3 + P2.2)
**Commit actuel** : `a5d6df9`

---

## ✅ COMPLÉTÉ (Commit a5d6df9)

### P0.1 - Sanitization Cypher Neo4j ✅
- Fonction `_sanitize_concept_name()` : Regex validation
- Fonction `_validate_tenant_id()` : Tenant isolation
- Application dans tous appels Neo4j (lookup, store, add_alias, increment_usage)

### P0.3 - Cache Poisoning Protection ✅
- Validation confidence minimale (≥0.6)
- Hallucination detection (similarité ≥0.3)
- Aliases limit (max 50)
- Unicité canonical_name (merge au lieu duplicate)

### P2.2 - Tenant Isolation ✅
- Validation format tenant_id : `[a-z0-9_-]{1,50}`
- Application partout

---

## 🚧 EN COURS - P0.2 Rate Limiting LLM + Circuit Breaker

### Objectif
Protéger contre DoS via appels LLM excessifs :
- Max 50 appels LLM canonicalization/document
- Circuit breaker si 5 échecs LLM consécutifs
- Timeout explicite 5s par appel LLM

### Fichiers à Modifier

#### 1. `src/knowbase/ontology/adaptive_ontology_manager.py`

**Ajouter méthode** (après `__init__`) :

```python
def __init__(self, neo4j_client, redis_client=None, max_llm_calls_per_doc=50):
    self.neo4j = neo4j_client
    self.redis = redis_client  # Pour rate limiting
    self.max_llm_calls_per_doc = max_llm_calls_per_doc
    logger.info("[AdaptiveOntology] Manager initialized")

def check_llm_budget(self, tenant_id: str, document_id: str) -> bool:
    """
    Vérifie quota LLM canonicalization pour ce document (P0 - DoS protection).

    Args:
        tenant_id: ID tenant
        document_id: ID document

    Returns:
        True si budget OK, False si quota dépassé
    """
    if not self.redis:
        logger.warning("[AdaptiveOntology:LLM Budget] Redis unavailable, skipping rate limiting")
        return True  # Pas de rate limiting si Redis indisponible

    key = f"adaptive_ontology:llm_calls:{tenant_id}:{document_id}"

    try:
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

        logger.debug(
            f"[AdaptiveOntology:LLM Budget] ✅ OK for doc {document_id}: "
            f"{calls}/{self.max_llm_calls_per_doc} calls"
        )
        return True

    except Exception as e:
        logger.error(f"[AdaptiveOntology:LLM Budget] Error checking budget: {e}")
        return True  # Fail open si erreur Redis
```

#### 2. `src/knowbase/ontology/llm_canonicalizer.py`

**Ajouter Circuit Breaker simple** (début fichier, avant class) :

```python
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import json
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# SIMPLE CIRCUIT BREAKER (P0 - DoS Protection)
# ═══════════════════════════════════════════════════

class SimpleCircuitBreaker:
    """
    Circuit breaker simple pour LLM calls.

    États:
    - CLOSED: Normal, appels passent
    - OPEN: Circuit ouvert, appels bloqués (fallback)
    - HALF_OPEN: Test si service récupéré

    Transitions:
    - CLOSED → OPEN: après failure_threshold échecs consécutifs
    - OPEN → HALF_OPEN: après recovery_timeout secondes
    - HALF_OPEN → CLOSED: après 1 succès
    - HALF_OPEN → OPEN: après 1 échec
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def call(self, func, *args, **kwargs):
        """Execute function avec circuit breaker protection."""

        # Si circuit OPEN, vérifier si on peut passer à HALF_OPEN
        if self.state == "OPEN":
            if self.last_failure_time and \
               (datetime.now() - self.last_failure_time).total_seconds() >= self.recovery_timeout:
                logger.info("[CircuitBreaker] OPEN → HALF_OPEN (recovery timeout elapsed)")
                self.state = "HALF_OPEN"
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker OPEN (failures={self.failure_count}, "
                    f"recovery in {self.recovery_timeout}s)"
                )

        # Tenter appel
        try:
            result = func(*args, **kwargs)

            # Succès → reset failure count
            if self.state == "HALF_OPEN":
                logger.info("[CircuitBreaker] HALF_OPEN → CLOSED (call succeeded)")
                self.state = "CLOSED"

            self.failure_count = 0
            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = datetime.now()

            logger.warning(
                f"[CircuitBreaker] Call failed ({self.failure_count}/{self.failure_threshold}): {e}"
            )

            # Si HALF_OPEN, échec immédiat → OPEN
            if self.state == "HALF_OPEN":
                logger.error("[CircuitBreaker] HALF_OPEN → OPEN (call failed)")
                self.state = "OPEN"
                raise CircuitBreakerOpenError("Circuit breaker re-opened after test failure")

            # Si seuil atteint → OPEN
            if self.failure_count >= self.failure_threshold:
                logger.error(
                    f"[CircuitBreaker] CLOSED → OPEN (failures={self.failure_count} >= {self.failure_threshold})"
                )
                self.state = "OPEN"
                raise CircuitBreakerOpenError(f"Circuit breaker opened after {self.failure_count} failures")

            # Re-raise erreur originale
            raise


class CircuitBreakerOpenError(Exception):
    """Exception when circuit breaker is open."""
    pass
```

**Modifier class LLMCanonicalizer** :

```python
class LLMCanonicalizer:
    """Service de canonicalisation via LLM léger (P0 - DoS protected)."""

    def __init__(self, llm_router):
        self.llm_router = llm_router
        self.model = "gpt-4o-mini"

        # P0: Circuit breaker (5 échecs → ouvert 60s)
        self.circuit_breaker = SimpleCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60
        )

        logger.info(
            f"[LLMCanonicalizer] Initialized with model={self.model}, "
            f"circuit_breaker (threshold=5, recovery=60s)"
        )

    def canonicalize(
        self,
        raw_name: str,
        context: Optional[str] = None,
        domain_hint: Optional[str] = None,
        timeout: int = 5  # P0: Timeout explicite
    ) -> CanonicalizationResult:
        """
        Canonicalise un nom via LLM (P0 - DoS protected).

        Protections:
        - Circuit breaker (5 échecs → fallback .title())
        - Timeout explicite 5s
        """

        logger.debug(
            f"[LLMCanonicalizer] Canonicalizing '{raw_name}' "
            f"(context_len={len(context) if context else 0}, domain={domain_hint})"
        )

        # Construire prompt LLM
        prompt = self._build_canonicalization_prompt(
            raw_name=raw_name,
            context=context,
            domain_hint=domain_hint
        )

        try:
            # P0: Appel via circuit breaker
            def _llm_call():
                from knowbase.common.llm_router import TaskType

                return self.llm_router.complete(
                    task_type=TaskType.CANONICALIZATION,
                    messages=[
                        {"role": "system", "content": CANONICALIZATION_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    timeout=timeout  # P0: Timeout explicite
                )

            response_content = self.circuit_breaker.call(_llm_call)

            # Parse résultat JSON
            result_json = json.loads(response_content)
            result = CanonicalizationResult(**result_json)

            logger.info(
                f"[LLMCanonicalizer] ✅ '{raw_name}' → '{result.canonical_name}' "
                f"(confidence={result.confidence:.2f}, type={result.concept_type})"
            )

            return result

        except CircuitBreakerOpenError as e:
            # Circuit ouvert → fallback direct
            logger.warning(f"[LLMCanonicalizer] Circuit breaker OPEN: {e}, falling back to .title()")
            return CanonicalizationResult(
                canonical_name=raw_name.strip().title(),
                confidence=0.3,
                reasoning=f"Circuit breaker open: {str(e)}",
                aliases=[],
                concept_type="Unknown",
                domain=None,
                ambiguity_warning="LLM service unavailable (circuit breaker open)",
                possible_matches=[],
                metadata={"circuit_breaker": "open"}
            )

        except Exception as e:
            logger.error(f"[LLMCanonicalizer] ❌ Error canonicalizing '{raw_name}': {e}")

            # Fallback: retourner résultat basique
            return CanonicalizationResult(
                canonical_name=raw_name.strip().title(),
                confidence=0.5,
                reasoning=f"LLM error, fallback to title case: {str(e)}",
                aliases=[],
                concept_type="Unknown",
                domain=None,
                ambiguity_warning="LLM canonicalization failed",
                possible_matches=[],
                metadata={"error": str(e)}
            )
```

#### 3. `src/knowbase/agents/gatekeeper/gatekeeper.py`

**Modifier `_canonicalize_concept_name()`** (ligne 627) :

```python
def _canonicalize_concept_name(
    self,
    raw_name: str,
    context: Optional[str] = None,
    tenant_id: str = "default",
    document_id: Optional[str] = None  # P0: Ajouté pour rate limiting
) -> tuple[str, float]:
    """
    Canonicalise nom concept via Adaptive Ontology (Phase 1.6+ P0 protected).

    Protections P0:
    - Rate limiting: max 50 appels LLM/document
    - Circuit breaker: fallback si LLM down
    - Timeout: 5s par appel
    """
    # Vérifier disponibilité des services
    if not self.llm_canonicalizer or not self.adaptive_ontology:
        logger.debug(
            f"[GATEKEEPER:Canonicalization] LLM Canonicalizer unavailable, "
            f"skipping adaptive canonicalization for '{raw_name}'"
        )
        return raw_name.strip().title(), 0.5

    # P0: Vérifier budget LLM (rate limiting)
    if document_id and not self.adaptive_ontology.check_llm_budget(tenant_id, document_id):
        logger.warning(
            f"[GATEKEEPER:Canonicalization] ❌ LLM budget exceeded for doc {document_id}, "
            f"falling back to .title()"
        )
        return raw_name.strip().title(), 0.3

    # 1. Lookup cache ontologie
    cached = self.adaptive_ontology.lookup(raw_name, tenant_id)

    if cached:
        # Cache HIT (pas de coût LLM)
        logger.debug(
            f"[GATEKEEPER:Canonicalization] ✅ Cache HIT '{raw_name}' → '{cached['canonical_name']}' "
            f"(confidence={cached['confidence']:.2f}, source={cached.get('source', 'unknown')})"
        )
        self.adaptive_ontology.increment_usage(cached["canonical_name"], tenant_id)
        return cached["canonical_name"], cached["confidence"]

    # 2. Cache MISS → LLM canonicalization (avec protections P0)
    logger.info(
        f"[GATEKEEPER:Canonicalization] 🔍 Cache MISS '{raw_name}', calling LLM canonicalizer..."
    )

    try:
        llm_result = self.llm_canonicalizer.canonicalize(
            raw_name=raw_name,
            context=context,
            domain_hint=None,
            timeout=5  # P0: Timeout explicite
        )

        logger.info(
            f"[GATEKEEPER:Canonicalization] ✅ LLM canonicalized '{raw_name}' → '{llm_result.canonical_name}' "
            f"(confidence={llm_result.confidence:.2f}, type={llm_result.concept_type})"
        )

        # 3. Store dans ontologie adaptive
        self.adaptive_ontology.store(
            tenant_id=tenant_id,
            canonical_name=llm_result.canonical_name,
            raw_name=raw_name,
            canonicalization_result=llm_result.model_dump(),
            context=context,
            document_id=document_id  # P0: Pour tracking
        )

        return llm_result.canonical_name, llm_result.confidence

    except Exception as e:
        logger.error(
            f"[GATEKEEPER:Canonicalization] ❌ LLM canonicalization failed for '{raw_name}': {e}, "
            f"falling back to title case"
        )
        return raw_name.strip().title(), 0.5
```

**Propager document_id dans les 3 appels** (lignes 777, 792, 800) :

```python
# Ligne 777 - Obtenir document_id du state
document_id = self.state.document_id if hasattr(self.state, 'document_id') else None

# Lignes 777, 792, 800 - Ajouter document_id parameter
canonical_name, llm_confidence = self._canonicalize_concept_name(
    raw_name=concept_name,
    context=definition,
    tenant_id=tenant_id,
    document_id=document_id  # P0: Ajouté
)
```

---

## 🔄 P1 - Stabilité Production

### P1.1 - Distributed Locks Redis Neo4j Writes

**Problème** : Race condition lors de création CanonicalConcepts simultanés

**Fichier** : `src/knowbase/common/clients/neo4j_client.py`

**Solution** : Wrapper `promote_to_published_kg()` avec distributed lock Redis

```python
def promote_to_published_kg_safe(self, proto_concept_id: str, canonical_name: str,
                                  tenant_id: str, redis_client, ...):
    """Promote avec distributed lock Redis (P1 - Race condition protection)."""

    lock_key = f"lock:canonical:{tenant_id}:{canonical_name}"
    lock_timeout = 30  # 30 secondes

    # Try acquire lock
    lock_acquired = redis_client.set(lock_key, "1", nx=True, ex=lock_timeout)

    if not lock_acquired:
        # Lock déjà tenu → wait 500ms et retry once
        logger.warning(f"[NEO4J:Promote] Lock held for '{canonical_name}', waiting...")
        time.sleep(0.5)
        lock_acquired = redis_client.set(lock_key, "1", nx=True, ex=lock_timeout)

        if not lock_acquired:
            raise RuntimeError(f"Cannot acquire lock for '{canonical_name}' after retry")

    try:
        # Critical section: promote to published
        return self.promote_to_published_kg(
            proto_concept_id, canonical_name, tenant_id, ...
        )
    finally:
        # Release lock
        redis_client.delete(lock_key)
```

---

### P1.2 - Singleton SentenceTransformer (Memory)

**Problème** : 420MB × 10 workers = 4.2GB RAM

**Fichier** : `src/knowbase/agents/gatekeeper/embeddings_contextual_scorer.py`

**Solution** : Singleton partagé

```python
import threading

class EmbeddingsModelPool:
    """Singleton pool for SentenceTransformer model (P1 - Memory optimization)."""

    _instance = None
    _model = None
    _lock = threading.Lock()

    @classmethod
    def get_model(cls):
        """Get shared model instance (thread-safe)."""
        if cls._model is None:
            with cls._lock:
                if cls._model is None:  # Double-check locking
                    logger.info("[OSMOSE] Loading SentenceTransformer model (once)...")
                    from sentence_transformers import SentenceTransformer
                    cls._model = SentenceTransformer(
                        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
                        device="cpu"  # Force CPU (pas GPU memory leak)
                    )
                    logger.info("[OSMOSE] SentenceTransformer loaded (420MB)")
        return cls._model


class EmbeddingsContextualScorer:
    def __init__(self, ...):
        # Lazy loading via pool
        self.model = None

    def _get_model(self):
        """Get model lazily from shared pool."""
        if self.model is None:
            self.model = EmbeddingsModelPool.get_model()
        return self.model

    def score_entities(self, candidates: List[Dict], full_text: str) -> List[Dict]:
        # Use lazy-loaded model
        model = self._get_model()
        # ...
```

---

### P1.3 - Limits + Timeout GraphScorer

**Problème** : O(n²) sur gros documents → timeout 30s

**Fichier** : `src/knowbase/agents/gatekeeper/graph_centrality_scorer.py`

**Solution** : Max entities limit + timeout PageRank

```python
class GraphCentralityScorer:
    def __init__(
        self,
        min_centrality: float = 0.15,
        centrality_weights: Dict[str, float] = None,
        enable_tf_idf: bool = True,
        enable_salience: bool = True,
        max_entities: int = 300,  # P1: Max entities
        timeout_seconds: int = 10  # P1: Timeout
    ):
        self.min_centrality = min_centrality
        self.centrality_weights = centrality_weights or {...}
        self.enable_tf_idf = enable_tf_idf
        self.enable_salience = enable_salience
        self.max_entities = max_entities
        self.timeout_seconds = timeout_seconds

    def score_entities(self, candidates: List[Dict], full_text: str) -> List[Dict]:
        # P1: Limit entities
        if len(candidates) > self.max_entities:
            logger.warning(
                f"[OSMOSE] GraphScorer: Too many candidates ({len(candidates)}), "
                f"scoring top {self.max_entities} by frequency"
            )
            candidates_sorted = sorted(
                candidates,
                key=lambda x: x.get("frequency", 0),
                reverse=True
            )
            candidates = candidates_sorted[:self.max_entities]

        # Construire graphe co-occurrence
        graph = self._build_cooccurrence_graph(candidates, full_text)

        # P1: PageRank avec timeout
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("PageRank computation timeout")

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(self.timeout_seconds)

        try:
            pagerank_scores = nx.pagerank(graph, max_iter=100)
        except TimeoutError:
            logger.error(
                f"[OSMOSE] GraphScorer: PageRank timeout ({self.timeout_seconds}s), "
                f"using fallback degree centrality"
            )
            # Fallback: degree centrality (plus rapide O(n))
            pagerank_scores = {node: graph.degree(node) / graph.number_of_nodes()
                             for node in graph.nodes()}
        finally:
            signal.alarm(0)

        # ... reste du scoring
```

---

## 🔍 P2 - Observability

### P2.1 - Monitoring Prometheus

**Fichier** : `src/knowbase/ontology/adaptive_ontology_manager.py`

**Solution** : Ajouter métriques Prometheus

```python
from prometheus_client import Counter, Histogram, Gauge

# Métriques globales
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

llm_canonicalization_budget_exceeded = Counter(
    "llm_canonicalization_budget_exceeded_total",
    "LLM budget exceeded events",
    ["tenant_id"]
)


class AdaptiveOntologyManager:
    def lookup(self, raw_name: str, tenant_id: str) -> Optional[Dict]:
        result = # ... (existing code)

        # P2: Instrumentation
        if result:
            adaptive_ontology_lookups.labels(tenant_id=tenant_id, hit_miss="hit").inc()
        else:
            adaptive_ontology_lookups.labels(tenant_id=tenant_id, hit_miss="miss").inc()

        return result

    def store(self, tenant_id: str, canonical_name: str, ...):
        # ... (existing code)

        # P2: Update cache size gauge
        stats = self.get_stats(tenant_id)
        adaptive_ontology_cache_size.labels(tenant_id=tenant_id).set(
            stats["total_entries"]
        )

    def check_llm_budget(self, tenant_id: str, document_id: str) -> bool:
        # ... (existing code)

        if calls > self.max_llm_calls_per_doc:
            # P2: Instrumentation budget exceeded
            llm_canonicalization_budget_exceeded.labels(tenant_id=tenant_id).inc()
            return False
```

**Dashboard Grafana** (à créer dans `config/grafana/`) :
- Panel 1: Cache hit rate (%) par tenant
- Panel 2: Cache size évolution
- Panel 3: LLM canonicalization latency (p50, p95, p99)
- Panel 4: Budget exceeded alerts

---

### P2.3 - Context LLM Truncation Intelligent

**Fichier** : `src/knowbase/ontology/llm_canonicalizer.py`

**Solution** : Ne pas couper mots

```python
def _truncate_context(self, context: str, max_chars: int = 500) -> str:
    """
    Truncate context intelligemment (P2 - Quality improvement).

    Évite de couper au milieu d'un mot.
    """
    if len(context) <= max_chars:
        return context

    # Trouver dernier espace avant limite
    truncated = context[:max_chars]
    last_space = truncated.rfind(' ')

    if last_space > max_chars * 0.8:  # Au moins 80% contexte
        return truncated[:last_space] + "..."
    else:
        # Pas d'espace trouvé → fallback
        return truncated + "..."

def _build_canonicalization_prompt(self, raw_name: str, context: Optional[str], ...):
    parts = [f"**Concept Name:** {raw_name}"]

    if context:
        # P2: Truncation intelligente
        context_snippet = self._truncate_context(context, max_chars=500)
        parts.append(f"**Context:** {context_snippet}")

    # ...
```

---

## 🧪 Tests Validation

### Test P0 - Injection Cypher

```bash
# Test 1: Caractères invalides
curl -X POST http://localhost:8000/api/test_sanitize \
  -H "Content-Type: application/json" \
  -d '{"raw_name": "'; DROP DATABASE neo4j; --", "tenant_id": "default"}'

# Attendu: 400 Bad Request "Invalid characters in concept name"

# Test 2: Nom trop long
curl -X POST http://localhost:8000/api/test_sanitize \
  -H "Content-Type: application/json" \
  -d '{"raw_name": "'$(python -c 'print("A" * 300)')'", "tenant_id": "default"}'

# Attendu: 400 Bad Request "Concept name too long"
```

### Test P0 - Rate Limiting LLM

```python
# test_rate_limiting.py
def test_llm_rate_limiting():
    """Test que rate limiting bloque après 50 appels."""

    from knowbase.ontology.adaptive_ontology_manager import AdaptiveOntologyManager
    from knowbase.ontology.llm_canonicalizer import LLMCanonicalizer

    manager = AdaptiveOntologyManager(neo4j, redis, max_llm_calls_per_doc=50)
    canonicalizer = LLMCanonicalizer(llm_router)

    document_id = "test_doc_123"
    tenant_id = "default"

    # 50 premiers appels → OK
    for i in range(50):
        assert manager.check_llm_budget(tenant_id, document_id) == True

    # 51ème appel → BLOCKED
    assert manager.check_llm_budget(tenant_id, document_id) == False

    print("✅ Rate limiting test PASSED")
```

### Test P0 - Circuit Breaker

```python
# test_circuit_breaker.py
def test_circuit_breaker():
    """Test que circuit breaker ouvre après 5 échecs."""

    from knowbase.ontology.llm_canonicalizer import LLMCanonicalizer, CircuitBreakerOpenError

    canonicalizer = LLMCanonicalizer(llm_router_mock_failing)

    # 5 premiers appels → Échecs mais circuit fermé
    for i in range(5):
        try:
            canonicalizer.canonicalize("Test")
        except Exception:
            pass  # Attendu

    # 6ème appel → Circuit OPEN
    try:
        result = canonicalizer.canonicalize("Test")
        # Fallback .title() should be used
        assert result.canonical_name == "Test"
        assert result.confidence == 0.3
        assert "circuit breaker" in result.reasoning.lower()
    except CircuitBreakerOpenError:
        pass  # Also acceptable

    print("✅ Circuit breaker test PASSED")
```

### Test P0 - Cache Poisoning

```python
# test_cache_poisoning.py
def test_cache_poisoning_protection():
    """Test protections contre cache poisoning."""

    from knowbase.ontology.adaptive_ontology_manager import AdaptiveOntologyManager

    manager = AdaptiveOntologyManager(neo4j, redis)

    # Test 1: Low confidence → rejected
    result = manager.store(
        tenant_id="default",
        canonical_name="SAP S/4HANA",
        raw_name="SAP S/4HANA",
        canonicalization_result={"confidence": 0.4}  # < 0.6
    )
    assert result == ""  # Pas stocké

    # Test 2: Hallucination → rejected
    result = manager.store(
        tenant_id="default",
        canonical_name="Microsoft Azure",  # Hallucination
        raw_name="SAP S/4HANA",
        canonicalization_result={"confidence": 0.9}
    )
    assert result == ""  # Pas stocké (similarity < 0.3)

    # Test 3: OK → stored
    result = manager.store(
        tenant_id="default",
        canonical_name="SAP S/4HANA Cloud",
        raw_name="SAP S/4HANA",
        canonicalization_result={"confidence": 0.85}
    )
    assert result != ""  # Stocké

    print("✅ Cache poisoning protection test PASSED")
```

---

## 📊 Checklist Implémentation

### Phase 1 (P0) - Urgences ✅ (Partiellement complété)

- [x] P0.1 - Sanitization Cypher (Commit a5d6df9)
- [x] P0.3 - Cache Poisoning (Commit a5d6df9)
- [x] P2.2 - Tenant Isolation (Commit a5d6df9)
- [ ] P0.2 - Rate Limiting LLM + Circuit Breaker (⚠️ TODO ci-dessus)

### Phase 2 (P1) - Stabilité

- [ ] P1.1 - Distributed Locks Redis
- [ ] P1.2 - Singleton SentenceTransformer
- [ ] P1.3 - Limits GraphScorer

### Phase 3 (P2) - Observability

- [ ] P2.1 - Monitoring Prometheus
- [ ] P2.3 - Context Truncation

### Tests

- [ ] Test injection Cypher
- [ ] Test rate limiting LLM
- [ ] Test circuit breaker
- [ ] Test cache poisoning
- [ ] Test concurrence Neo4j
- [ ] Test memory embeddings

---

## 📈 Prochaines Sessions

**Session 1** : Compléter P0.2 (Rate Limiting + Circuit Breaker)
- Implémenter `SimpleCircuitBreaker` dans `llm_canonicalizer.py`
- Ajouter `check_llm_budget()` dans `adaptive_ontology_manager.py`
- Intégrer dans `gatekeeper.py`
- Tests validation

**Session 2** : P1.1-P1.3 (Stabilité)
- Distributed locks Redis
- Singleton embeddings
- GraphScorer limits

**Session 3** : P2.1 + P2.3 + Tests E2E
- Monitoring Prometheus
- Context truncation
- Tests complets P0-P1-P2

---

**Dernière mise à jour** : 2025-10-17
**Commit actuel** : `a5d6df9` (P0.1 + P0.3 + P2.2 complétés)
**Prochaine étape** : P0.2 (Rate Limiting + Circuit Breaker)
