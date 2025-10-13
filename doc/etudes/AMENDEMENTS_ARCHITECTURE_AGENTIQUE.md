# 🔧 Amendements - Architecture Agentique OSMOSE

**Document:** ARCHITECTURE_AGENTIQUE_OSMOSE.md v1.0
**Date Amendements:** 2025-10-13
**Feedback Source:** Analyse OpenAI
**Statut:** ✅ Corrections Critiques

---

## Executive Summary Amendements

Suite à l'analyse OpenAI, **9 corrections critiques** et **7 améliorations** identifiées:

**Corrections Critiques:**
1. ❌ **Coûts incohérents** : Exec summary $0.18/1000p vs calculs $0.81/1000p → **CORRIGÉ $0.81/$2.56**
2. ❌ **Overhead tokens omis** : Prompts système, JSON schema, retry non comptés → **+20% coeff ajouté**
3. ❌ **Embeddings coût manquant** : text-embedding-3-small $0.0001/1k tokens → **Poste ajouté**
4. ❌ **Rate limits non gérés** : Pas de concurrency control → **LLM Dispatcher ajouté**
5. ❌ **Routing pré-pass flou** : entity_count_estimate d'où ? → **NER léger spécifié**
6. ❌ **Cross-segment evidence** : Spans manquants par segment → **Bi-evidence obligatoire**
7. ❌ **Idempotence non garantie** : candidate_id non déterministe → **Hash SHA1 défini**
8. ❌ **Multi-tenant sécurité faible** : Pas de namespace isolation → **Namespaces Qdrant + contraintes Neo4j**
9. ❌ **Vision sous-estimée** : 1% vs réalité PPTX → **Profil PPT-heavy 5-10% ajouté**

**Améliorations:**
- PII/conformité gate ajouté
- Profiles multi-langues FR/DE
- Cache Bloom filter anti-collision
- Mesures qualité procédure explicite
- Budget quotas par tenant/jour
- Concurrency scheduler priorité/budget
- Profil documents PPT-heavy

**Impact cost model révisé:**
- Scénario A: $0.20 → **$0.26/doc** (overhead +20%, embeddings +5%)
- Scénario B: $0.64 → **$0.83/doc** (overhead +20%, embeddings +5%)

---

## Table des Matières

1. [Correction #1: Coûts Incohérents](#correction-1-coûts-incohérents)
2. [Correction #2: Overhead Tokens](#correction-2-overhead-tokens)
3. [Correction #3: Coût Embeddings](#correction-3-coût-embeddings)
4. [Correction #4: LLM Dispatcher Rate Limits](#correction-4-llm-dispatcher-rate-limits)
5. [Correction #5: Pré-pass Routing](#correction-5-pré-pass-routing)
6. [Correction #6: Bi-Evidence Cross-Segment](#correction-6-bi-evidence-cross-segment)
7. [Correction #7: Idempotence Candidate ID](#correction-7-idempotence-candidate-id)
8. [Correction #8: Multi-Tenant Sécurité](#correction-8-multi-tenant-sécurité)
9. [Correction #9: Vision Profil PPT-Heavy](#correction-9-vision-profil-ppt-heavy)
10. [Amélioration #1: PII/Conformité Gate](#amélioration-1-piiconformité-gate)
11. [Amélioration #2: Profiles Multi-Langues](#amélioration-2-profiles-multi-langues)
12. [Cost Model Révisé Final](#cost-model-révisé-final)
13. [Redlines Mises à Jour](#redlines-mises-à-jour)

---

## Correction #1: Coûts Incohérents

### Problème Identifié

**Executive summary ligne 5:**
> "Scénario A (mostly SMALL) = **0,18$/1000 pages**"

**Calculs Section 7.2:**
> "Scénario A: ~$0.20/doc (250 pages) = **$0.81/1000 pages**"

**→ Incohérence: 0.18 vs 0.81 (facteur 4.5x !)**

### Correction Appliquée

**AVANT (Executive Summary):**
```
Cost model chiffré: Scénario A (mostly SMALL) = 0,18$/1000 pages,
Scénario B (mix BIG) = 0,42$/1000 pages
```

**APRÈS (Corrigé):**
```
Cost model chiffré: Scénario A (mostly SMALL) = 0,81$/1000 pages
($0.20/doc 250 pages), Scénario B (mix BIG) = 2,56$/1000 pages
($0.64/doc 250 pages). Hypothèses: 4 segments/page, 300 tokens/segment,
cache hit 20%, sans overhead tokens (voir Correction #2 pour ajustements).
```

**Propagation:**
- Section 7.2: ✅ Déjà correct ($0.81 et $2.56)
- Section 7.3 Tableau comparaison: ✅ Déjà correct
- Section 9 Redlines: ❌ À corriger (utilise 0.18/0.42)
- Conclusion: ❌ À corriger

---

## Correction #2: Overhead Tokens

### Problème Identifié

**Calculs Section 7.2 omettent:**
- Prompts système (≈200 tokens/appel)
- JSON schema dans prompt (≈150 tokens)
- Messages d'erreur/retry (≈100 tokens/retry)
- Second opinion avec contexte (≈300 tokens supplémentaires)

**Impact estimé:** +15-25% tokens input effectifs

### Correction Appliquée

**Coefficient d'overhead:** **+20%** (conservateur)

**Nouveau calcul Scénario A:**

```python
# AVANT (Section 7.2)
Cost SMALL batches = 63 × $0.000396 = $0.025
Cost BIG batches = 20 × $0.0033 = $0.066
Cost VISION = 10 × $0.01525 = $0.153
Cost cross-segment = $0.00495
Cost second opinions = $0.0043
TOTAL = $0.253/doc

# APRÈS (avec overhead +20%)
Base cost = $0.253
Overhead (prompts système, schema, retry) = $0.253 × 0.20 = $0.051
TOTAL avec overhead = $0.304/doc (avant cache)

Avec cache hit 20%:
= $0.304 × 0.80 = $0.243/doc

Par 1000 pages:
= ($0.243 / 250) × 1000 = $0.97/1000 pages
```

**Tableau révisé (avec overhead, sans embeddings encore):**

| Scénario | Coût/doc base | Overhead +20% | Après cache 20% | Coût/1000p |
|----------|---------------|---------------|-----------------|------------|
| A - Mostly SMALL | $0.253 | $0.304 | $0.243 | $0.97 |
| B - Mix BIG | $0.799 | $0.959 | $0.767 | $3.07 |

---

## Correction #3: Coût Embeddings

### Problème Identifié

**Architecture utilise:**
- OpenAI `text-embedding-3-small` (1536 dimensions)
- Coût: **$0.00002/1k tokens** (soit $0.02/1M tokens)

**Volumétrie non comptée:**
- Embedding chaque entity name + properties text
- Embedding narrative threads summaries
- Embedding pour cache semantic (SimHash + embedding double)

**Estimation volumétrie:**

```python
# Par document 250 pages, 1000 segments
Entities extracted = 290 (SMALL + BIG segments)
Avg tokens/entity = 50 (name + properties)
Total tokens embeddings = 290 × 50 = 14,500 tokens

Narrative threads = 2-3/doc
Tokens/thread summary = 200
Total threads tokens = 3 × 200 = 600 tokens

Cache embeddings (segments uniques) = 1000 × 300 × 0.80 (20% cache hit) = 240k tokens

TOTAL embeddings tokens/doc ≈ 255k tokens
Cost embeddings = 255k × ($0.00002 / 1k) = $0.0051/doc
```

**Impact:** +$0.005/doc ≈ **+2% coût total**

### Correction Appliquée

**Ajout poste "Embeddings" au Budget Governor:**

```yaml
# config/osmose_budget_governor.yaml (AMENDÉ)

budget_governor:
  # ... (existant)

  models:
    # ... (SMALL, BIG, VISION existants)

    embeddings:  # NOUVEAU
      name: "text-embedding-3-small"
      cost_per_1k: 0.00002
      dimensions: 1536
      typical_tokens_per_entity: 50
      typical_tokens_per_thread: 200

  caps_per_document:
    # ... (existant)
    max_embedding_tokens: 300000  # NOUVEAU: 300k tokens max embeddings/doc
```

**Nouveau calcul avec embeddings:**

| Scénario | Base+Overhead | Embeddings | Total | Après cache | Coût/1000p |
|----------|---------------|------------|-------|-------------|------------|
| A - Mostly SMALL | $0.304 | $0.005 | $0.309 | $0.247 | **$0.99** |
| B - Mix BIG | $0.959 | $0.005 | $0.964 | $0.771 | **$3.08** |

---

## Correction #4: LLM Dispatcher Rate Limits

### Problème Identifié

**Scénario A: 63 batches SMALL + 20 BIG = 83 appels LLM/doc**

**Sans rate controller:**
- Parallélisme non maîtrisé → rate limits API (10k TPM, 500 RPM typique)
- Backpressure → timeouts → retries → coûts explosion
- Pas de prioritisation (BIG > SMALL, narrative > simple)

### Correction Appliquée

**Ajout Agent #6: LLM Dispatcher** (coordination rate limits)

#### Rôle

**Responsabilités:**
- Contrôle concurrence par modèle (SMALL, BIG, VISION)
- Fenêtre glissante rate limits (TPM, RPM)
- Queue prioritaire (narrative > complex > simple)
- Backoff centralisé (exponential retry avec jitter)

**Politiques:**

```python
class LLMDispatcher:
    def __init__(self, config: DispatcherConfig):
        self.config = config
        self.windows = {
            "SMALL": RateLimitWindow(rpm=500, tpm=10000),  # gpt-4o-mini
            "BIG": RateLimitWindow(rpm=100, tpm=5000),      # gpt-4o
            "VISION": RateLimitWindow(rpm=50, tpm=2000)     # gpt-4o-vision
        }
        self.queues = {
            "SMALL": PriorityQueue(),
            "BIG": PriorityQueue(),
            "VISION": PriorityQueue()
        }
        self.concurrent_semaphores = {
            "SMALL": asyncio.Semaphore(20),  # Max 20 concurrent SMALL
            "BIG": asyncio.Semaphore(5),     # Max 5 concurrent BIG
            "VISION": asyncio.Semaphore(2)   # Max 2 concurrent VISION
        }

    async def dispatch(self, request: LLMRequest) -> LLMResponse:
        """
        Dispatch avec rate limiting + prioritization + backoff.

        Priority scoring:
        - narrative_thread = 3 pts
        - complexity > 0.7 = 2 pts
        - complexity 0.4-0.7 = 1 pt
        - simple < 0.4 = 0 pts
        """
        route = request.route
        priority = self._compute_priority(request)

        # Enqueue
        await self.queues[route].put((priority, request))

        # Wait for rate limit window + semaphore
        async with self.concurrent_semaphores[route]:
            # Check rate limits
            while not self.windows[route].can_proceed(request.tokens_estimate):
                await asyncio.sleep(0.1)  # Wait 100ms

            # Consume rate limit
            self.windows[route].consume(request.tokens_estimate)

            # Execute LLM call
            try:
                response = await self._execute_llm_call(request)
                return response
            except RateLimitError as e:
                # Backoff exponential
                await self._backoff(request.retry_count)
                request.retry_count += 1
                if request.retry_count > 3:
                    raise
                return await self.dispatch(request)  # Retry

    def _compute_priority(self, request: LLMRequest) -> int:
        priority = 0
        if request.in_narrative_thread:
            priority += 3
        if request.complexity > 0.7:
            priority += 2
        elif request.complexity > 0.4:
            priority += 1
        return priority

    async def _backoff(self, retry_count: int):
        base_delay = 2 ** retry_count  # Exponential: 2, 4, 8s
        jitter = random.uniform(0, 1)
        await asyncio.sleep(base_delay + jitter)

class RateLimitWindow:
    def __init__(self, rpm: int, tpm: int):
        self.rpm = rpm  # Requests per minute
        self.tpm = tpm  # Tokens per minute
        self.window_size = 60  # 60 seconds
        self.requests_window = deque(maxlen=rpm)
        self.tokens_window = deque(maxlen=tpm)

    def can_proceed(self, tokens_estimate: int) -> bool:
        now = time.time()
        # Clean old entries (>60s ago)
        self._clean_window(now)

        # Check RPM
        if len(self.requests_window) >= self.rpm:
            return False

        # Check TPM
        current_tokens = sum([t for _, t in self.tokens_window])
        if current_tokens + tokens_estimate > self.tpm:
            return False

        return True

    def consume(self, tokens_estimate: int):
        now = time.time()
        self.requests_window.append(now)
        self.tokens_window.append((now, tokens_estimate))

    def _clean_window(self, now: float):
        # Remove entries older than 60s
        cutoff = now - self.window_size
        while self.requests_window and self.requests_window[0] < cutoff:
            self.requests_window.popleft()
        while self.tokens_window and self.tokens_window[0][0] < cutoff:
            self.tokens_window.popleft()
```

**Configuration:**

```yaml
# config/osmose_llm_dispatcher.yaml (NOUVEAU)

llm_dispatcher:
  enabled: true

  rate_limits:
    small:
      rpm: 500  # Requests per minute
      tpm: 10000  # Tokens per minute
      max_concurrent: 20
    big:
      rpm: 100
      tpm: 5000
      max_concurrent: 5
    vision:
      rpm: 50
      tpm: 2000
      max_concurrent: 2

  priority_weights:
    narrative_thread: 3
    high_complexity: 2  # >0.7
    medium_complexity: 1  # 0.4-0.7
    simple: 0  # <0.4

  retry_policy:
    max_retries: 3
    backoff_base: 2  # Exponential base (2^retry_count)
    jitter_max: 1.0  # Random jitter 0-1s

  queue_depth_max: 1000  # Max queued requests per route
  queue_timeout: 120  # Timeout si request en queue >120s
```

**Mapping Agents mis à jour:**

| Agent | Tools | Criticité | Latence | **Dépendances** |
|-------|-------|-----------|---------|-----------------|
| Supervisor | emit_metrics, check_timeout, handle_error | 🔴 P0 | <10ms | - |
| Extractor Orchestrator | route_segments, **llm_dispatch**, cache_get, write_protokg | 🔴 P0 | 5-20s | **LLM Dispatcher** |
| Pattern Miner | mine_relaters, **llm_dispatch**, simhash_match | 🟡 P1 | 3-8s | **LLM Dispatcher** |
| Gatekeeper Delegate | promote_via_gate, **llm_dispatch**, compute_* | 🔴 P0 | 2-5s | **LLM Dispatcher** |
| Budget Manager | budget_check, budget_consume, budget_refund | 🔴 P0 | <50ms | - |
| **LLM Dispatcher** | **rate_limit_check, enqueue, dispatch, backoff** | **🔴 P0** | **<100ms** | **Redis (queue state)** |

**Impact latence:**

Avec dispatcher + queue prioritaire:
- Documents simples (low priority): +2-5s latency (queuing)
- Documents narratifs (high priority): <1s overhead (fast-track)
- **SLA P95 ajusté:** <180s → **<220s** (marge dispatcher)

---

## Correction #5: Pré-pass Routing

### Problème Identifié

**Extractor Orchestrator route basé sur:**
```python
segment.entity_count_estimate < 3  # D'où vient ce nombre ?
segment.complexity <= 0.6          # Comment calculé sans LLM ?
```

**→ Pas de spécification du pré-pass léger**

### Correction Appliquée

**Ajout Tool: `prepass_analyze_segment`**

#### Responsabilité

Analyse légère (sans LLM) pour estimer:
- `entity_count_estimate` (via NER léger multi-langue)
- `complexity` (via features linguistiques + layout)
- `contains_charts` (via détection patterns images)
- `in_narrative_thread` (via marqueurs causaux/temporaux)

#### Implémentation

```python
import spacy
import re
from typing import Dict

class PrepassAnalyzer:
    """
    Pré-pass analysis léger pour routing sans LLM.

    Utilise:
    - spaCy NER multi-langue (léger, <100ms/segment)
    - Patterns regex causaux/temporaux
    - Features layout (titres, listes, tableaux)
    - Heuristiques densité syntaxique
    """

    def __init__(self):
        # Load spaCy small models (fast NER)
        self.nlp_en = spacy.load("en_core_web_sm")
        self.nlp_fr = spacy.load("fr_core_news_sm")
        self.nlp_de = spacy.load("de_core_news_sm")

        # Causal markers (multi-langue)
        self.causal_markers = {
            "en": ["because", "therefore", "as a result", "due to", "consequently", "thus", "hence"],
            "fr": ["parce que", "donc", "par conséquent", "en raison de", "ainsi", "de ce fait"],
            "de": ["weil", "daher", "deshalb", "infolgedessen", "somit", "folglich"]
        }

        # Temporal markers
        self.temporal_markers = {
            "en": ["revised", "updated", "replaced", "superseded", "deprecated", "modified", "changed"],
            "fr": ["révisé", "mis à jour", "remplacé", "obsolète", "modifié", "changé"],
            "de": ["überarbeitet", "aktualisiert", "ersetzt", "veraltet", "geändert"]
        }

    def analyze_segment(self, segment: Segment, language: str = "en") -> SegmentAnalysis:
        """
        Analyse pré-pass d'un segment (sans LLM).

        Returns:
            SegmentAnalysis avec entity_count_estimate, complexity, features
        """
        text = segment.text

        # 1. NER léger pour entity_count_estimate
        nlp = self._get_nlp(language)
        doc = nlp(text)
        entities = [ent for ent in doc.ents if ent.label_ in ["PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "LAW", "NORP"]]
        entity_count_estimate = len(set([ent.text.lower() for ent in entities]))

        # 2. Complexity scoring (0.0-1.0)
        complexity_score = self._compute_complexity(text, doc, language)

        # 3. Features detection
        contains_charts = self._detect_charts(segment.metadata)
        in_narrative_thread = self._detect_narrative_markers(text, language)

        # 4. Token estimate
        tokens_estimate = len(doc)  # spaCy tokenization

        return SegmentAnalysis(
            segment_id=segment.id,
            entity_count_estimate=entity_count_estimate,
            complexity=complexity_score,
            contains_charts=contains_charts,
            in_narrative_thread=in_narrative_thread,
            tokens_estimate=tokens_estimate,
            features={
                "causal_markers_count": self._count_markers(text, self.causal_markers[language]),
                "temporal_markers_count": self._count_markers(text, self.temporal_markers[language]),
                "sentence_count": len(list(doc.sents)),
                "avg_sentence_length": sum([len(sent) for sent in doc.sents]) / len(list(doc.sents)) if list(doc.sents) else 0,
                "noun_chunks_count": len(list(doc.noun_chunks))
            }
        )

    def _compute_complexity(self, text: str, doc, language: str) -> float:
        """
        Complexity score basé sur:
        - Densité syntaxique (noun chunks / tokens)
        - Longueur moyenne phrases
        - Présence marqueurs causaux/temporaux
        - Profondeur dépendances syntaxiques
        """
        score = 0.0

        # Feature 1: Densité noun chunks (0-0.3)
        noun_chunks_density = len(list(doc.noun_chunks)) / len(doc) if len(doc) > 0 else 0
        score += min(0.3, noun_chunks_density * 2)

        # Feature 2: Longueur moyenne phrases (0-0.3)
        sents = list(doc.sents)
        if sents:
            avg_sent_length = sum([len(sent) for sent in sents]) / len(sents)
            if avg_sent_length > 25:
                score += 0.3
            elif avg_sent_length > 15:
                score += 0.15

        # Feature 3: Marqueurs causaux/temporaux (0-0.2)
        causal_count = self._count_markers(text, self.causal_markers[language])
        temporal_count = self._count_markers(text, self.temporal_markers[language])
        if causal_count + temporal_count > 3:
            score += 0.2
        elif causal_count + temporal_count > 1:
            score += 0.1

        # Feature 4: Profondeur syntaxique (0-0.2)
        max_depth = max([self._get_dep_depth(token) for token in doc]) if doc else 0
        if max_depth > 5:
            score += 0.2
        elif max_depth > 3:
            score += 0.1

        return min(1.0, score)

    def _detect_narrative_markers(self, text: str, language: str) -> bool:
        """
        Détecte si segment contient marqueurs narratifs (causal/temporal).
        """
        causal_count = self._count_markers(text, self.causal_markers[language])
        temporal_count = self._count_markers(text, self.temporal_markers[language])
        return (causal_count + temporal_count) >= 2

    def _detect_charts(self, metadata: Dict) -> bool:
        """
        Détecte si segment contient charts/images via metadata layout.
        """
        if "images" in metadata and len(metadata["images"]) > 0:
            return True
        if "layout_type" in metadata and metadata["layout_type"] in ["chart", "table", "figure"]:
            return True
        return False

    def _count_markers(self, text: str, markers: list) -> int:
        text_lower = text.lower()
        return sum([1 for marker in markers if marker in text_lower])

    def _get_dep_depth(self, token) -> int:
        depth = 0
        current = token
        while current.head != current:
            depth += 1
            current = current.head
        return depth

    def _get_nlp(self, language: str):
        if language == "en":
            return self.nlp_en
        elif language == "fr":
            return self.nlp_fr
        elif language == "de":
            return self.nlp_de
        else:
            return self.nlp_en  # Fallback
```

**Intégration dans Extractor Orchestrator:**

```python
class ExtractorOrchestrator:
    def __init__(self, config):
        # ...
        self.prepass_analyzer = PrepassAnalyzer()

    async def route_segments(self, segments: List[Segment], doc_intel: DocumentIntelligence) -> List[RoutedSegment]:
        """
        Route segments avec pré-pass analysis.
        """
        routed = []

        for segment in segments:
            # Pré-pass analysis (léger, sans LLM)
            analysis = self.prepass_analyzer.analyze_segment(segment, doc_intel.language)

            # Update segment avec analysis
            segment.entity_count_estimate = analysis.entity_count_estimate
            segment.complexity = analysis.complexity
            segment.contains_charts = analysis.contains_charts
            segment.in_narrative_thread = analysis.in_narrative_thread
            segment.token_estimate = analysis.tokens_estimate

            # Route decision
            route = self._decide_route(segment, doc_intel)

            routed.append(RoutedSegment(
                segment=segment,
                route=route,
                analysis=analysis
            ))

        return routed
```

**Performance:**

- Latency pré-pass: **50-100ms/segment** (spaCy small models)
- Total overhead 1000 segments: **50-100s** (parallélisable)
- Précision routing: **85-90%** (validation empirique nécessaire)

**KPI ajouté:**

```python
routing_prediction_error = abs(entity_count_actual - entity_count_estimate) / entity_count_actual
```

Target: <20% erreur prédiction (affiner pré-pass si >30%)

---

## Correction #6: Bi-Evidence Cross-Segment

### Problème Identifié

**Prompt cross-segment demande:**
```json
{
  "cross_segment_relations": [
    {
      "source": "entity",
      "target": "entity",
      "evidence": "narrative justification"  // Pas de spans par segment
    }
  ]
}
```

**→ Evidence globale, pas d'ancrage par segment**

### Correction Appliquée

**Nouveau format cross-segment relations:**

```json
{
  "cross_segment_relations": [
    {
      "source": "CRR Revised",
      "target": "CRR v1.0",
      "type": "SUPERSEDES",
      "confidence": 0.82,
      "evidence_narrative": "Both revised methodology and original definition discussed in CRR evolution narrative thread",
      "evidence_spans_per_segment": [  // NOUVEAU: Evidence par segment
        {
          "segment_id": "seg_003",
          "spans": [
            {"start": 120, "end": 180, "text": "The revised methodology excludes inactive accounts"}
          ]
        },
        {
          "segment_id": "seg_007",
          "spans": [
            {"start": 45, "end": 95, "text": "Original CRR calculation methodology (v1.0)"}
          ]
        }
      ],
      "cross_segment": true
    }
  ]
}
```

**Validation stricte:**

```python
def validate_cross_segment_relation(relation: CrossSegmentRelation) -> ValidationResult:
    """
    Validation bi-evidence: au moins 1 span par segment impliqué.
    """
    errors = []

    if not relation.evidence_spans_per_segment or len(relation.evidence_spans_per_segment) < 2:
        errors.append("Cross-segment relation requires evidence from at least 2 segments")

    segment_ids = set([esp.segment_id for esp in relation.evidence_spans_per_segment])
    if len(segment_ids) < 2:
        errors.append("Cross-segment relation must span at least 2 different segments")

    for esp in relation.evidence_spans_per_segment:
        if not esp.spans or len(esp.spans) == 0:
            errors.append(f"Segment {esp.segment_id} has no evidence spans")

    # Si validation échoue → downgrade to RELATED_TO (cap 5%)
    if errors:
        relation.type = "RELATED_TO"
        relation.promoted = False  # Ne sera pas promu Published-KG
        relation.validation_errors = errors

    return ValidationResult(valid=len(errors) == 0, errors=errors)
```

**Policy ajoutée:**

**Si bi-evidence manquante:**
1. Relation downgrade vers `RELATED_TO` (compte dans cap 5%)
2. Status `PENDING_REVIEW` (human validation requise)
3. Jamais auto-promoted Published-KG

**Prompt cross-segment amendé:**

```python
CROSS_SEGMENT_PROMPT_AMENDED = """
...

**OUTPUT JSON**:
{{
  "cross_segment_relations": [
    {{
      "source": "entity name",
      "target": "entity name",
      "type": "enum({allowed_relation_types})",
      "confidence": float,
      "evidence_narrative": "high-level justification",
      "evidence_spans_per_segment": [  // MANDATORY: At least 1 span per segment
        {{
          "segment_id": "seg_X",
          "spans": [
            {{"start": int, "end": int, "text": "exact quote from segment X"}}
          ]
        }},
        {{
          "segment_id": "seg_Y",
          "spans": [
            {{"start": int, "end": int, "text": "exact quote from segment Y"}}
          ]
        }}
      ]
    }}
  ]
}}

**CRITICAL RULE**:
Each cross-segment relation MUST have evidence_spans_per_segment with at least
1 span from EACH segment involved. If you cannot provide bi-evidence, DO NOT
create the relation.
"""
```

---

## Correction #7: Idempotence Candidate ID

### Problème Identifié

**write_protokg tool:**
> "Idempotence: Oui (upsert via MERGE sur candidate_id)"

**Mais candidate_id comment généré ?** Non spécifié → risque doublons si re-runs.

### Correction Appliquée

**Formule déterministe candidate_id:**

```python
import hashlib
import json

def generate_candidate_id(
    tenant_id: str,
    document_id: str,
    segment_id: str,
    entity_or_relation: Dict,
    evidence_spans: List[Dict]
) -> str:
    """
    Génère candidate_id déterministe via SHA1.

    Inputs:
    - tenant_id: Isolation multi-tenant
    - document_id: Document source
    - segment_id: Segment d'extraction
    - entity_or_relation: {"name": ..., "type": ..., "properties": ...}
    - evidence_spans: [{"start": ..., "end": ..., "text": ...}]

    Returns:
    - candidate_id: sha1 hex digest (40 chars)
    """
    # Normalize entity/relation (ordre properties canonique)
    normalized = {
        "name": entity_or_relation.get("name", ""),
        "type": entity_or_relation.get("type", ""),
        "properties": sorted(entity_or_relation.get("properties", {}).items())
    }

    # Normalize evidence spans (ordre par start position)
    normalized_spans = sorted(
        [{"start": s["start"], "end": s["end"]} for s in evidence_spans],
        key=lambda x: x["start"]
    )

    # Construct hash input
    hash_input = {
        "tenant_id": tenant_id,
        "document_id": document_id,
        "segment_id": segment_id,
        "entity_or_relation": normalized,
        "evidence_spans": normalized_spans
    }

    # JSON canonique (sorted keys)
    hash_string = json.dumps(hash_input, sort_keys=True, separators=(',', ':'))

    # SHA1 (40 chars hex)
    candidate_id = hashlib.sha1(hash_string.encode('utf-8')).hexdigest()

    return candidate_id

# Exemple
candidate_id = generate_candidate_id(
    tenant_id="tenant_acme",
    document_id="doc_12345",
    segment_id="seg_003",
    entity_or_relation={
        "name": "Customer Retention Rate",
        "type": "Metric",
        "properties": {"version": "v2.0", "excludes": "inactive_accounts"}
    },
    evidence_spans=[
        {"start": 120, "end": 180, "text": "The revised methodology..."}
    ]
)
# → "a3f5e8b2c1d4... (40 chars)"
```

**Neo4j MERGE query amendé:**

```cypher
// write_protokg avec candidate_id déterministe

MERGE (c:CandidateEntity {candidate_id: $candidate_id})
ON CREATE SET
  c.tenant_id = $tenant_id,
  c.document_id = $document_id,
  c.segment_id = $segment_id,
  c.name = $entity_name,
  c.type = $entity_type,
  c.properties = $properties,
  c.evidence_spans = $evidence_spans,
  c.confidence = $confidence,
  c.status = 'PENDING_REVIEW',
  c.created_at = datetime()
ON MATCH SET
  c.updated_at = datetime(),
  c.confidence = CASE WHEN $confidence > c.confidence THEN $confidence ELSE c.confidence END
RETURN c
```

**Idempotence garantie:**
- Re-run même segment → même candidate_id → MERGE ON MATCH (update timestamp, confidence max)
- Pas de duplicates CandidateEntity dans Proto-KG

---

## Correction #8: Multi-Tenant Sécurité

### Problème Identifié

**Architecture utilise `tenant_id` mais:**
- Qdrant: pas de namespace isolation (cross-tenant leakage possible)
- Neo4j: index sur tenant_id, mais pas de contrainte compound
- Budget Governor: caps par document, pas par tenant/jour

### Correction Appliquée

#### 8.1 Namespaces Qdrant par Tenant

**Qdrant 1.8+ supporte multi-tenancy via payload filters, mais isolation stricte nécessite collections séparées.**

**Stratégie:**

```python
# Collection naming: knowwhere_proto_{tenant_id}
# Ex: knowwhere_proto_tenant_acme, knowwhere_proto_tenant_globex

def get_qdrant_collection_name(tenant_id: str, scope: str = "proto") -> str:
    """
    Collection name isolation par tenant.
    """
    return f"knowwhere_{scope}_{tenant_id}"

# Lors de création collection
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

client = QdrantClient(host="localhost", port=6333)

for tenant_id in tenants:
    collection_name = get_qdrant_collection_name(tenant_id, "proto")
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
    )
```

**Avantages:**
- Isolation stricte (pas de cross-tenant leakage)
- Quotas indépendants par tenant
- Performances (pas de filter overhead sur tenant_id)

**Inconvénient:**
- Prolifération collections (100 tenants = 200 collections proto+published)
- Monitoring complexité

**Alternative si trop de tenants (>1000):**

Garder collection unique avec **filter strictement appliqué**:

```python
# Search avec tenant_id filter mandatory
results = client.search(
    collection_name="knowwhere_proto",
    query_vector=query_embedding,
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value=tenant_id)
            )
        ]
    ),
    limit=10
)
```

**Security layer:** Valider tenant_id avant toute query (API endpoint)

---

#### 8.2 Contraintes Neo4j Compound

**Ajout contraintes compound tenant_id + candidate_id:**

```cypher
// Contrainte unique compound (tenant_id, candidate_id)
CREATE CONSTRAINT candidate_entity_tenant_compound IF NOT EXISTS
FOR (c:CandidateEntity)
REQUIRE (c.tenant_id, c.candidate_id) IS UNIQUE;

CREATE CONSTRAINT candidate_relation_tenant_compound IF NOT EXISTS
FOR (r:CandidateRelation)
REQUIRE (r.tenant_id, r.candidate_id) IS UNIQUE;

// Contraintes Published-KG
CREATE CONSTRAINT entity_tenant_compound IF NOT EXISTS
FOR (e:Entity)
REQUIRE (e.tenant_id, e.entity_id) IS UNIQUE;

CREATE CONSTRAINT relation_tenant_compound IF NOT EXISTS
FOR (r:Relation)
REQUIRE (r.tenant_id, r.relation_id) IS UNIQUE;

// Index performance sur tenant_id seul (queries filtrées)
CREATE INDEX entity_tenant_idx IF NOT EXISTS
FOR (e:Entity) ON (e.tenant_id);
```

**Queries amendées:**

```cypher
// AVANT (risque cross-tenant si candidate_id collision)
MATCH (c:CandidateEntity {candidate_id: $candidate_id})
RETURN c

// APRÈS (sécurisé)
MATCH (c:CandidateEntity {tenant_id: $tenant_id, candidate_id: $candidate_id})
RETURN c
```

---

#### 8.3 Budget Quotas par Tenant/Jour

**Budget Governor amendé:**

```yaml
# config/osmose_budget_governor.yaml (AMENDÉ)

budget_governor:
  # ... (existant caps_per_document)

  caps_per_tenant:  # NOUVEAU
    max_cost_usd_per_day: 100.0  # $100/jour/tenant (ajustable)
    max_documents_per_day: 500   # 500 docs/jour max/tenant
    max_calls_small_per_day: 60000  # 60k SMALL calls/jour
    max_calls_big_per_day: 4000     # 4k BIG calls/jour
    max_calls_vision_per_day: 1000  # 1k VISION calls/jour

  # Alerting par tenant
  alerts:
    tenant_budget_80_percent:
      threshold: 0.80
      action: "log_warning"
    tenant_budget_exceeded:
      threshold: 1.0
      action: "throttle_tenant"  # Throttle ingestion pour tenant
```

**Implementation:**

```python
class BudgetGovernor:
    # ... (existant)

    def check_tenant_budget(self, tenant_id: str, call_type: CallType) -> BudgetCheckResult:
        """
        Check budget tenant/jour avant appel LLM.
        """
        state = self._get_tenant_state(tenant_id)  # Redis key: budget:tenant:{tenant_id}:{date}

        # Check daily caps
        if state.cost_usd_today >= self.config.caps_per_tenant.max_cost_usd_per_day:
            return BudgetCheckResult(allowed=False, reason="Tenant daily budget exceeded")

        if state.documents_today >= self.config.caps_per_tenant.max_documents_per_day:
            return BudgetCheckResult(allowed=False, reason="Tenant daily doc limit exceeded")

        if call_type == CallType.SMALL and state.calls_small_today >= self.config.caps_per_tenant.max_calls_small_per_day:
            return BudgetCheckResult(allowed=False, reason="Tenant SMALL calls daily limit exceeded")

        # ... (BIG, VISION checks)

        return BudgetCheckResult(allowed=True)

    def _get_tenant_state(self, tenant_id: str) -> TenantBudgetState:
        """
        Redis key: budget:tenant:{tenant_id}:{YYYY-MM-DD}
        Expire à minuit UTC (TTL auto)
        """
        date_key = datetime.utcnow().strftime("%Y-%m-%d")
        redis_key = f"budget:tenant:{tenant_id}:{date_key}"

        state_json = self.redis.get(redis_key)
        if state_json:
            return TenantBudgetState.parse_raw(state_json)
        else:
            # Initialize state
            state = TenantBudgetState(
                tenant_id=tenant_id,
                date=date_key,
                cost_usd_today=0.0,
                documents_today=0,
                calls_small_today=0,
                calls_big_today=0,
                calls_vision_today=0
            )
            # Set with TTL (expire à minuit)
            ttl_seconds = self._seconds_until_midnight()
            self.redis.setex(redis_key, ttl_seconds, state.json())
            return state
```

---

## Correction #9: Vision Profil PPT-Heavy

### Problème Identifié

**Scénario A/B utilisent:**
- 1% VISION (Scénario A)
- 2% VISION (Scénario B)

**Réalité PPTX/rapports visuels riches:** 5-10% segments contiennent charts/tables/images

### Correction Appliquée

**Ajout Scénario C: PPT-Heavy**

```python
# Scénario C: Documents riches en visuels (PPTX, rapports graphiques)
Routing breakdown:
- 40% NO_LLM (segments texte simple)
- 20% LLM_SMALL
- 30% LLM_BIG
- 10% VISION  # 10x vs Scénario A

Total segments = 1000

NO_LLM = 400
LLM_SMALL = 200 segments → 50 batches × $0.000396 = $0.0198
LLM_BIG = 300 segments → 150 batches × $0.0033 = $0.495
VISION = 100 segments × $0.01525 = $1.525  # 10x impact !

Cross-segment = $0.00495
Second opinions = 50 × $0.0001485 = $0.0074

TOTAL base = $2.05/doc

Avec overhead +20% + embeddings:
= $2.05 × 1.20 + $0.005 = $2.465/doc

Avec cache 20%:
= $2.465 × 0.80 = $1.97/doc

Par 1000 pages:
= ($1.97 / 250) × 1000 = $7.88/1000 pages
```

**Tableau révisé avec Scénario C:**

| Scénario | Routing | Vision % | Coût/doc | Coût/1000p | Usage |
|----------|---------|----------|----------|------------|-------|
| A - Mostly SMALL | 70% NO_LLM, 25% SMALL, 4% BIG, 1% VISION | **1%** | $0.26 | $1.04 | PDF textuels production |
| B - Mix BIG | 50% NO_LLM, 20% SMALL, 28% BIG, 2% VISION | **2%** | $0.83 | $3.32 | Documents critiques textuels |
| **C - PPT-Heavy** | **40% NO_LLM, 20% SMALL, 30% BIG, 10% VISION** | **10%** | **$1.97** | **$7.88** | **PPTX, rapports graphiques** |

**Policy ajoutée:**

Détection automatique profil document (pré-pass):

```python
def detect_document_profile(document: Document) -> str:
    """
    Détecte profil document pour ajuster caps budget.
    """
    total_segments = len(document.segments)
    vision_segments = sum([1 for seg in document.segments if seg.contains_charts])
    vision_ratio = vision_segments / total_segments if total_segments > 0 else 0

    if vision_ratio > 0.08:
        return "PPT_HEAVY"  # >8% vision → Scénario C
    elif vision_ratio > 0.015:
        return "MIX_BIG"    # 1.5-8% vision → Scénario B
    else:
        return "MOSTLY_SMALL"  # <1.5% vision → Scénario A

# Ajuster caps budget selon profil
if profile == "PPT_HEAVY":
    budget_caps.max_calls_vision = 100  # Au lieu de 2
    budget_caps.max_total_cost_usd = 3.0  # Au lieu de 1.50
```

---

## Amélioration #1: PII/Conformité Gate

### Problème Identifié

**Aucun mécanisme de détection PII/secrets** avant promotion Published-KG → risque conformité GDPR/HIPAA

### Amélioration Ajoutée

**Ajout Tool: `pii_gate_check`**

#### Responsabilité

Détection PII (Personally Identifiable Information) et secrets avant promotion:
- Noms personnes (PERSON entities)
- Emails, téléphones
- SSN, numéros carte crédit
- API keys, tokens
- Adresses IP privées

#### Implémentation

```python
import re
from typing import List, Dict

class PIIGate:
    """
    PII/secret detection gate avant promotion Published-KG.

    Politiques:
    - PII détectée → anonymization OU rejection
    - Secrets détectés → REJECT toujours (pas de promotion)
    - Configuré par tenant (certains tenants autorisent PII)
    """

    def __init__(self, config: PIIGateConfig):
        self.config = config

        # Regex patterns pour secrets
        self.secret_patterns = [
            r'sk-[A-Za-z0-9]{48}',  # OpenAI API keys
            r'AIza[0-9A-Za-z\-_]{35}',  # Google API keys
            r'xox[baprs]-[0-9]{10,12}-[a-zA-Z0-9]{24}',  # Slack tokens
            r'-----BEGIN (RSA|DSA|EC|OPENSSH) PRIVATE KEY-----',  # SSH keys
            r'ghp_[A-Za-z0-9]{36}',  # GitHub tokens
        ]

        # Regex patterns pour PII
        self.pii_patterns = {
            "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            "phone": r'\b(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
            "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
            "credit_card": r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
            "ip_private": r'\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3})\b'
        }

    def check_candidate(self, candidate: CandidateEntity, tenant_policy: TenantPIIPolicy) -> PIICheckResult:
        """
        Check PII/secrets dans candidate entity.

        Returns:
            PIICheckResult avec action (ALLOW | ANONYMIZE | REJECT)
        """
        issues = []

        # Check evidence spans pour secrets
        for span in candidate.evidence_spans:
            for pattern in self.secret_patterns:
                if re.search(pattern, span.text):
                    issues.append(PIIIssue(
                        type="SECRET",
                        pattern=pattern,
                        span=span,
                        severity="CRITICAL"
                    ))

        # Check evidence spans pour PII
        for pii_type, pattern in self.pii_patterns.items():
            for span in candidate.evidence_spans:
                if re.search(pattern, span.text):
                    issues.append(PIIIssue(
                        type="PII",
                        subtype=pii_type,
                        pattern=pattern,
                        span=span,
                        severity="HIGH"
                    ))

        # Check entity name/properties pour PII
        if candidate.type == "PERSON":
            issues.append(PIIIssue(
                type="PII",
                subtype="person_name",
                span=None,
                severity="MEDIUM"
            ))

        # Décision basée sur tenant policy
        if not issues:
            return PIICheckResult(action=PIIAction.ALLOW, issues=[])

        # Secrets → REJECT toujours
        if any(issue.type == "SECRET" for issue in issues):
            return PIICheckResult(action=PIIAction.REJECT, issues=issues, reason="Secrets detected")

        # PII → Selon policy tenant
        if tenant_policy.allow_pii:
            return PIICheckResult(action=PIIAction.ALLOW, issues=issues, reason="Tenant allows PII")
        elif tenant_policy.anonymize_pii:
            return PIICheckResult(action=PIIAction.ANONYMIZE, issues=issues, reason="Anonymization required")
        else:
            return PIICheckResult(action=PIIAction.REJECT, issues=issues, reason="Tenant rejects PII")

    def anonymize_candidate(self, candidate: CandidateEntity, issues: List[PIIIssue]) -> CandidateEntity:
        """
        Anonymize PII dans candidate (replace avec placeholders).
        """
        anonymized = candidate.copy()

        for issue in issues:
            if issue.type == "PII" and issue.span:
                # Replace PII avec placeholder
                placeholder = f"[{issue.subtype.upper()}]"
                anonymized.evidence_spans = [
                    EvidenceSpan(
                        start=span.start,
                        end=span.end,
                        text=re.sub(issue.pattern, placeholder, span.text)
                    )
                    for span in anonymized.evidence_spans
                ]

        # Flag anonymized
        anonymized.anonymized = True
        anonymized.anonymization_issues = issues

        return anonymized
```

**Configuration:**

```yaml
# config/osmose_pii_gate.yaml (NOUVEAU)

pii_gate:
  enabled: true

  # Patterns détection secrets
  secret_patterns:
    - "sk-[A-Za-z0-9]{48}"  # OpenAI
    - "AIza[0-9A-Za-z\\-_]{35}"  # Google
    - "xox[baprs]-[0-9]{10,12}-[a-zA-Z0-9]{24}"  # Slack
    - "-----BEGIN (RSA|DSA|EC|OPENSSH) PRIVATE KEY-----"

  # Patterns PII
  pii_patterns:
    email: "\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b"
    phone: "\\b(\\+?\\d{1,3}[-.\\s]?)?(\\(?\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4})\\b"
    ssn: "\\b\\d{3}-\\d{2}-\\d{4}\\b"
    credit_card: "\\b\\d{4}[-\\s]?\\d{4}[-\\s]?\\d{4}[-\\s]?\\d{4}\\b"

  # Policy par défaut (overridable par tenant)
  default_policy:
    allow_pii: false
    anonymize_pii: true  # Anonymize si détecté
    reject_secrets: true  # Toujours reject secrets

  # Tenant-specific policies (exemples)
  tenant_policies:
    tenant_pharma_x:
      allow_pii: true  # Pharma autorise PERSON names
      anonymize_pii: false
      reject_secrets: true

    tenant_finance_y:
      allow_pii: false
      anonymize_pii: true
      reject_secrets: true
```

**Intégration Gatekeeper:**

```python
class GatekeeperDelegate:
    def __init__(self, config):
        # ...
        self.pii_gate = PIIGate(config.pii_gate)

    async def evaluate_candidate(self, candidate: CandidateEntity, profile: GateProfile) -> PromotionDecision:
        # ... (gate profile evaluation existant)

        # PII check avant promotion
        tenant_policy = self.pii_gate.config.get_tenant_policy(candidate.tenant_id)
        pii_check = self.pii_gate.check_candidate(candidate, tenant_policy)

        if pii_check.action == PIIAction.REJECT:
            return PromotionDecision(
                action=Action.REJECT,
                reason=f"PII/Secret detected: {pii_check.reason}",
                pii_issues=pii_check.issues
            )
        elif pii_check.action == PIIAction.ANONYMIZE:
            candidate = self.pii_gate.anonymize_candidate(candidate, pii_check.issues)

        # Continue gate evaluation avec candidate (potentiellement anonymisé)
        # ...
```

**KPI ajouté:**

```python
pii_rejection_rate = (pii_rejected_count / total_candidates) * 100
```

Target: <1% (la plupart tenants ne manipulent pas PII critiques)

---

## Amélioration #2: Profiles Multi-Langues

### Problème Identifié

**Gate profiles fournis:** EN/finance, EN/pharma, multi/general

**Réalité production:** Documents FR, DE, ES, multi-langues

### Amélioration Ajoutée

**Ajout gate profiles FR et DE:**

```yaml
# config/osmose_gate_profiles.yaml (AMENDÉ)

gate_profiles:
  # ... (profiles EN existants)

  - name: "finance_fr"
    domain: "finance"
    language: "fr"

    weights:
      llm_confidence: 0.25
      source_count: 0.15
      type_validity: 0.10
      orphan_penalty: 0.10
      narrative_coherence: 0.15
      semantic_uniqueness: 0.10
      causal_reasoning_quality: 0.10
      contextual_richness: 0.05

    thresholds:
      auto_promote: 0.85
      human_review: 0.70

    # Marqueurs causaux FR (pour causal_reasoning_quality)
    causal_markers:
      - "parce que"
      - "donc"
      - "par conséquent"
      - "en raison de"
      - "ainsi"
      - "de ce fait"
      - "c'est pourquoi"

    # Marqueurs temporels FR
    temporal_markers:
      - "révisé"
      - "mis à jour"
      - "remplacé"
      - "obsolète"
      - "modifié"
      - "changé"
      - "déprécié"

    tuning_policy:
      auto_tune_enabled: true
      tune_frequency_days: 7

  - name: "finance_de"
    domain: "finance"
    language: "de"

    weights:
      llm_confidence: 0.25
      source_count: 0.15
      type_validity: 0.10
      orphan_penalty: 0.10
      narrative_coherence: 0.15
      semantic_uniqueness: 0.10
      causal_reasoning_quality: 0.10
      contextual_richness: 0.05

    thresholds:
      auto_promote: 0.85
      human_review: 0.70

    causal_markers:
      - "weil"
      - "daher"
      - "deshalb"
      - "infolgedessen"
      - "somit"
      - "folglich"
      - "aus diesem Grund"

    temporal_markers:
      - "überarbeitet"
      - "aktualisiert"
      - "ersetzt"
      - "veraltet"
      - "geändert"
      - "modifiziert"

    tuning_policy:
      auto_tune_enabled: true
      tune_frequency_days: 7

  - name: "pharma_fr"
    domain: "pharma"
    language: "fr"
    # ... (similaire finance_fr avec poids ajustés pharma)

  - name: "pharma_de"
    domain: "pharma"
    language: "de"
    # ... (similaire finance_de avec poids ajustés pharma)
```

**Language Router:**

```python
def select_gate_profile(document: Document, domain: str) -> GateProfile:
    """
    Sélectionne gate profile basé sur langue + domaine.
    """
    language = document.language  # Détecté lors du profiling

    profile_name = f"{domain}_{language}"

    # Fallback si profile spécifique pas disponible
    if not profile_exists(profile_name):
        profile_name = f"{domain}_en"  # Fallback EN

    if not profile_exists(profile_name):
        profile_name = "general_multi"  # Ultimate fallback

    return load_gate_profile(profile_name)
```

**Détection langue automatique:**

Ajouté au `SemanticDocumentProfiler`:

```python
from langdetect import detect_langs

class SemanticDocumentProfiler:
    # ...

    async def analyze_document(self, document_path: str, document_text: str) -> DocumentIntelligence:
        # ... (existant)

        # Language detection
        language = self._detect_language(document_text)

        return DocumentIntelligence(
            document_path=document_path,
            language=language,  # NOUVEAU
            domain=domain,
            # ...
        )

    def _detect_language(self, text: str) -> str:
        """
        Détecte langue via langdetect (basé sur n-grams).
        """
        try:
            langs = detect_langs(text[:5000])  # Sample 5k chars
            # langs = [LanguageConfidence(lang='en', prob=0.9999...), ...]
            if langs:
                return langs[0].lang  # Most confident
        except:
            pass
        return "en"  # Fallback
```

---

## Cost Model Révisé Final

### Tableau Complet avec Toutes Corrections

**Hypothèses mises à jour:**
- 4 segments/page, 300 tokens/segment
- **Overhead tokens +20%** (prompts système, schema, retry)
- **Embeddings +$0.005/doc** (text-embedding-3-small)
- Cache hit 20% (conservateur, augmentera avec volume)

| Scénario | Routing | Vision % | Coût Base | Overhead +20% | Embeddings | Total | Après Cache 20% | **Coût/Doc** | **Coût/1000p** |
|----------|---------|----------|-----------|---------------|------------|-------|-----------------|--------------|----------------|
| **A - Mostly SMALL** | 70% NO_LLM, 25% SMALL, 4% BIG, 1% VISION | 1% | $0.253 | $0.051 | $0.005 | $0.309 | $0.247 | **$0.25** | **$1.00** |
| **B - Mix BIG** | 50% NO_LLM, 20% SMALL, 28% BIG, 2% VISION | 2% | $0.799 | $0.160 | $0.005 | $0.964 | $0.771 | **$0.77** | **$3.08** |
| **C - PPT-Heavy** | 40% NO_LLM, 20% SMALL, 30% BIG, 10% VISION | 10% | $2.05 | $0.410 | $0.005 | $2.465 | $1.972 | **$1.97** | **$7.88** |

**Arrondis pour communication:**
- Scénario A: **$0.25/doc** ou **$1/1000 pages**
- Scénario B: **$0.77/doc** ou **$3/1000 pages**
- Scénario C: **$1.97/doc** ou **$8/1000 pages**

### Comparaison Legacy vs OSMOSE Agentique

| Approche | Coût/Doc (250p) | Coût/1000p | Maîtrise Budget | Scalabilité |
|----------|-----------------|------------|-----------------|-------------|
| **Legacy Monolithique** (estimé) | $0.60 - $1.20 | $2.40 - $4.80 | ❌ Non maîtrisé | ⚠️ Limitée |
| **OSMOSE Agentique Scénario A** | **$0.25** | **$1.00** | ✅ Caps durs | ✅ 10x throughput |
| **OSMOSE Agentique Scénario B** | **$0.77** | **$3.08** | ✅ Caps durs | ✅ 10x throughput |

**Économies estimées:** -40% à -60% selon scénario vs legacy

---

## Redlines Mises à Jour

### Document: ARCHITECTURE_AGENTIQUE_OSMOSE.md

#### Executive Summary

**AVANT (ligne 5):**
```
Cost model chiffré: Scénario A (mostly SMALL) = 0,18$/1000 pages,
Scénario B (mix BIG) = 0,42$/1000 pages
```

**APRÈS:**
```
Cost model chiffré: Scénario A (mostly SMALL) = $1.00/1000 pages
($0.25/doc 250 pages), Scénario B (mix BIG) = $3.08/1000 pages
($0.77/doc), Scénario C (PPT-heavy) = $7.88/1000 pages ($1.97/doc).
Inclut overhead tokens +20%, embeddings $0.005/doc, cache hit 20%.
Hypothèses: 4 segments/page, 300 tokens/segment.
```

#### Section 2.2 Mapping Agents

**AJOUTER Agent #6:**

```markdown
#### Agent 6: **LLM Dispatcher** (Rate Limits & Concurrency)

**Responsabilités**:
- Contrôle concurrence par modèle (SMALL: 20 concurrent, BIG: 5, VISION: 2)
- Fenêtre glissante rate limits (TPM, RPM)
- Queue prioritaire (narrative > complex > simple)
- Backoff centralisé exponential retry avec jitter

**Politiques de Décision**:
- Priority scoring: narrative_thread +3, complexity >0.7 +2, 0.4-0.7 +1
- Rate limit enforcement via sliding window (60s)
- Retry max 3x avec backoff 2^retry_count + jitter

**Tools Autorisés**:
- `rate_limit_check(route, tokens_estimate) -> bool`
- `enqueue(request, priority) -> QueuePosition`
- `dispatch(request) -> LLMResponse` (avec backoff si rate limit)
- `get_queue_depth(route) -> int`
```

#### Section 4 Tools

**AJOUTER Tools:**

1. **`prepass_analyze_segment`** (Section Correction #5)
2. **`pii_gate_check`** (Section Amélioration #1)
3. **`rate_limit_check`, `enqueue`, `dispatch`** (Section Correction #4)

#### Section 7.2 Cost Model

**REMPLACER tableaux avec Cost Model Révisé Final (ci-dessus)**

#### Section 9 Redlines

**METTRE À JOUR toutes références coûts:**
- $0.18 → $1.00/1000p (Scénario A)
- $0.42 → $3.08/1000p (Scénario B)
- Ajouter Scénario C: $7.88/1000p

---

## Récapitulatif Amendements

### Corrections Critiques Appliquées

| # | Correction | Impact | Statut |
|---|------------|--------|--------|
| 1 | Coûts incohérents 0.18 vs 0.81 | ✅ Unifié: $1.00 et $3.08/1000p | ✅ CORRIGÉ |
| 2 | Overhead tokens +20% | ✅ Ajouté au cost model | ✅ CORRIGÉ |
| 3 | Coût embeddings manquant | ✅ +$0.005/doc ajouté | ✅ CORRIGÉ |
| 4 | LLM Dispatcher rate limits | ✅ Agent #6 ajouté | ✅ CORRIGÉ |
| 5 | Pré-pass routing flou | ✅ PrepassAnalyzer spécifié | ✅ CORRIGÉ |
| 6 | Bi-evidence cross-segment | ✅ Evidence spans par segment obligatoire | ✅ CORRIGÉ |
| 7 | Idempotence candidate_id | ✅ Hash SHA1 déterministe défini | ✅ CORRIGÉ |
| 8 | Multi-tenant sécurité | ✅ Namespaces Qdrant + contraintes Neo4j | ✅ CORRIGÉ |
| 9 | Vision sous-estimée | ✅ Scénario C PPT-heavy 10% ajouté | ✅ CORRIGÉ |

### Améliorations Ajoutées

| # | Amélioration | Impact | Statut |
|---|--------------|--------|--------|
| 1 | PII/conformité gate | ✅ PIIGate tool + tenant policies | ✅ AJOUTÉ |
| 2 | Profiles multi-langues FR/DE | ✅ Gate profiles FR/DE + language router | ✅ AJOUTÉ |
| 3 | Cache Bloom filter | 🟡 Anti-collision (à implémenter si collisions) | 🟡 OPTIONNEL |
| 4 | Mesures qualité procédure | 🟡 Sample hebdo validation humaine | 🟡 OPTIONNEL |
| 5 | Budget quotas tenant/jour | ✅ Caps tenant daily ajoutés | ✅ AJOUTÉ |
| 6 | Concurrency scheduler priorité | ✅ LLM Dispatcher avec priority queue | ✅ AJOUTÉ |
| 7 | Profil documents PPT-heavy | ✅ Scénario C avec auto-detection | ✅ AJOUTÉ |

### Cost Model Final Révisé

**Production recommandée:**

- **Documents textuels (PDF):** Scénario A → **$1/1000 pages**
- **Documents complexes:** Scénario B → **$3/1000 pages**
- **Documents visuels (PPTX):** Scénario C → **$8/1000 pages**

**Économies vs Legacy:** -40% à -60%

---

## Prochaines Actions

1. **Valider amendements** avec équipe/stakeholders
2. **Mettre à jour** ARCHITECTURE_AGENTIQUE_OSMOSE.md v1.1 (incorporer tous amendements)
3. **Plan pilote ajusté** avec Scénario A/B/C (100 docs: 50 textuels, 30 complexes, 20 PPTX)
4. **Implémenter corrections critiques** avant pilote (LLM Dispatcher, PrepassAnalyzer, PIIGate)

---

**Version Amendements:** 1.0
**Date:** 2025-10-13
**Statut:** ✅ Complet - Prêt pour intégration

---

> **🔧 "Amendements appliqués: de la théorie optimiste à l'implémentation pragmatique."**
