# Phase 1.5 - Architecture Agentique V1.1

**Status**: 🟢 IMPLÉMENTÉ (Sem 11 Jour 1-2)
**Date**: 2025-10-15
**Version**: 1.1.0
**Objectif**: Maîtrise coûts LLM + scalabilité production via 6 agents spécialisés

---

## 🎯 Objectifs Phase 1.5

### Problèmes Phase 1 V2.1
- ❌ **Coûts LLM non maîtrisés**: LLM appelé systématiquement sans routing
- ❌ **Qualité concepts insuffisante**: Definitions vides, typage ENTITY uniquement
- ❌ **Pas de rate limiting**: Risque dépassement quotas OpenAI
- ❌ **Pas de retry logic**: Échecs LLM = perte définitive
- ❌ **Pas de multi-tenant**: Isolation budgets/tenant absente

### Solutions Phase 1.5
- ✅ **Routing intelligent**: NO_LLM/SMALL/BIG selon densité entities
- ✅ **Quality gates**: GatekeeperDelegate avec 3 profils (STRICT/BALANCED/PERMISSIVE)
- ✅ **Rate limiting**: 500/100/50 RPM (SMALL/BIG/VISION)
- ✅ **Retry policy**: 1 retry max avec BIG model si Gate < 30% promoted
- ✅ **Multi-tenant budgets**: Caps document + quotas jour/tenant

---

## 🏗️ Architecture: 6 Agents Spécialisés

### Architecture FSM

```
┌─────────────────────────────────────────────────────────────┐
│                    SUPERVISOR AGENT (FSM Master)             │
│  INIT → BUDGET_CHECK → SEGMENT → EXTRACT → MINE_PATTERNS    │
│         → GATE_CHECK → PROMOTE → FINALIZE → DONE            │
└──────┬─────────────┬────────────┬───────────┬───────────────┘
       │             │            │           │
       ▼             ▼            ▼           ▼
  ┌─────────┐  ┌─────────────┐ ┌──────────┐ ┌──────────────┐
  │ BUDGET  │  │  EXTRACTOR  │ │  MINER   │ │  GATEKEEPER  │
  │ MANAGER │  │ORCHESTRATOR │ │          │ │   DELEGATE   │
  └─────────┘  └─────────────┘ └──────────┘ └──────────────┘
       │             │                             │
       └─────────────┼─────────────────────────────┘
                     ▼
              ┌─────────────┐
              │     LLM     │
              │  DISPATCHER │
              └─────────────┘
```

---

## 🤖 Agents

### 1. SupervisorAgent (FSM Master)

**Fichier**: `src/knowbase/agents/supervisor/supervisor.py`
**Config**: `config/agents/supervisor.yaml`

**Responsabilités**:
- Orchestration FSM stricte (10 états: INIT → DONE)
- Timeout enforcement (300s/doc)
- Max steps enforcement (50 steps/doc)
- Error handling avec état ERROR
- Retry logic (1 retry max avec BIG si Gate < 30%)

**FSM States**:
```python
class FSMState(str, Enum):
    INIT = "init"
    BUDGET_CHECK = "budget_check"
    SEGMENT = "segment"
    EXTRACT = "extract"
    MINE_PATTERNS = "mine_patterns"
    GATE_CHECK = "gate_check"
    PROMOTE = "promote"
    FINALIZE = "finalize"
    ERROR = "error"
    DONE = "done"
```

**FSM Transitions**:
- `INIT → BUDGET_CHECK`
- `BUDGET_CHECK → SEGMENT | ERROR`
- `SEGMENT → EXTRACT | ERROR`
- `EXTRACT → MINE_PATTERNS | ERROR`
- `MINE_PATTERNS → GATE_CHECK | ERROR`
- `GATE_CHECK → PROMOTE | EXTRACT (retry) | ERROR`
- `PROMOTE → FINALIZE | ERROR`
- `FINALIZE → DONE | ERROR`
- `ERROR → DONE` (terminal)

**Metrics**:
- `steps_count`: Nombre d'étapes FSM
- `cost_incurred`: Coût total accumulé ($)
- `llm_calls_count`: Compteur par tier (SMALL/BIG/VISION)

---

### 2. ExtractorOrchestrator (Routing Agent)

**Fichier**: `src/knowbase/agents/extractor/orchestrator.py`
**Config**: `config/agents/routing_policies.yaml`

**Responsabilités**:
- Analyse segments avec **PrepassAnalyzer** (NER spaCy)
- Route vers NO_LLM/SMALL/BIG selon densité entities
- Extraction concepts avec budget awareness
- Fallback graceful (BIG → SMALL → NO_LLM)

**Routing Logic**:
```python
if entity_count < 3:
    route = NO_LLM  # NER + Clustering uniquement
elif entity_count <= 8:
    route = SMALL   # gpt-4o-mini
else:
    route = BIG     # gpt-4o
```

**Fallback Chain**:
1. Si `budget_remaining["BIG"] == 0` → fallback SMALL
2. Si `budget_remaining["SMALL"] == 0` → fallback NO_LLM
3. NO_LLM toujours disponible (pas de coût)

**Tools**:
- `prepass_analyzer`: NER spaCy pour routing
- `extract_concepts`: Extraction avec route choisie

---

### 3. PatternMiner (Cross-Segment Reasoning)

**Fichier**: `src/knowbase/agents/miner/miner.py`

**Responsabilités**:
- Détection patterns récurrents (frequency ≥ 2)
- Co-occurrence analysis (concepts même segment)
- Hierarchy inference (parent-child relations)
- Named Entity disambiguation

**Algorithmes**:
1. **Frequency analysis**: Count occurrences cross-segments
2. **Pattern scoring**: `pattern_score = freq / total_segments`
3. **Co-occurrence**: Lie concepts dans même segment
4. **Hierarchy inference**: Détecte relations parent-child

**Output**:
- Enrichit `state.candidates` avec:
  - `pattern_score`: float (0-1)
  - `frequency`: int
  - `related_concepts`: List[str]

**Tools**:
- `detect_patterns`: Détecte patterns récurrents
- `link_concepts`: Créer relations CO_OCCURRENCE

---

### 4. GatekeeperDelegate (Quality Control)

**Fichier**: `src/knowbase/agents/gatekeeper/gatekeeper.py`
**Config**: `config/agents/gate_profiles.yaml`

**Responsabilités**:
- Score candidates selon Gate Profile (STRICT/BALANCED/PERMISSIVE)
- Promeut concepts ≥ seuil vers Neo4j Published
- Rejette fragments, stopwords, PII
- Recommande retry si promotion_rate < 30%

**Gate Profiles**:

| Profil       | min_confidence | required_fields        | min_promotion_rate |
|--------------|----------------|------------------------|-------------------|
| STRICT       | 0.85           | name, type, definition | 50%               |
| BALANCED     | 0.70           | name, type             | 30%               |
| PERMISSIVE   | 0.60           | name                   | 20%               |

**Hard Rejections**:
- Nom < 3 chars ou > 100 chars
- Stopwords (the, and, or, le, de, etc.)
- Fragments (ized, ial, ing, tion)
- PII patterns (email, phone, SSN, credit card)

**Tools**:
- `gate_check`: Score et filtre candidates
- `promote_concepts`: Promotion Neo4j Proto→Published

---

### 5. BudgetManager (Caps & Quotas)

**Fichier**: `src/knowbase/agents/budget/budget.py`
**Config**: `config/agents/budget_limits.yaml`

**Responsabilités**:
- Enforce caps durs par document
- Enforce quotas tenant/jour (Redis)
- Tracking temps-réel consommation
- Refund logic si retry échoue

**Caps Document**:
```yaml
SMALL: 120 calls/doc
BIG: 8 calls/doc
VISION: 2 calls/doc
```

**Quotas Tenant/Jour**:
```yaml
SMALL: 10,000 calls/jour/tenant
BIG: 500 calls/jour/tenant
VISION: 100 calls/jour/tenant
```

**Redis Keys**:
```
budget:tenant:{tenant_id}:SMALL:{date} → count calls
budget:tenant:{tenant_id}:BIG:{date} → count calls
budget:tenant:{tenant_id}:VISION:{date} → count calls
```

**TTL**: 24h (rolling window)

**Tools**:
- `check_budget`: Vérifie quotas disponibles
- `consume_budget`: Consomme après appel LLM
- `refund_budget`: Rembourse si retry échoue

---

### 6. LLMDispatcher (Rate Limiting)

**Fichier**: `src/knowbase/agents/dispatcher/dispatcher.py`

**Responsabilités**:
- Rate limiting strict (500/100/50 RPM)
- Priority queue (P0 retry > P1 first pass > P2 batch)
- Concurrency control (10 calls max simultanées)
- Circuit breaker (suspend si error_rate > 30%)

**Rate Limits**:
```yaml
SMALL (gpt-4o-mini): 500 RPM
BIG (gpt-4o): 100 RPM
VISION (gpt-4o-vision): 50 RPM
```

**Priority Queue**:
- **P0 (RETRY)**: Retry après échec → priorité absolue
- **P1 (FIRST_PASS)**: Premier passage → priorité normale
- **P2 (BATCH)**: Traitement batch → basse priorité

**Circuit Breaker**:
- **CLOSED**: Normal operation
- **OPEN**: Error rate > 30%, suspend 60s
- **HALF_OPEN**: Test recovery après 60s

**Métriques**:
- Queue size par priorité
- Active calls count
- Total calls
- Error rate (sliding window 100 calls)

**Tools**:
- `dispatch_llm`: Enqueue et execute appel LLM
- `get_queue_stats`: Métriques temps-réel

---

## 📊 État Partagé (AgentState)

**Fichier**: `src/knowbase/agents/base.py`

```python
class AgentState(BaseModel):
    """État partagé entre agents (passé via FSM)."""
    document_id: str
    tenant_id: str = "default"

    # Budget tracking
    budget_remaining: Dict[str, int] = {
        "SMALL": 120,
        "BIG": 8,
        "VISION": 2
    }

    # Extraction state
    segments: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    promoted: List[Dict[str, Any]] = []

    # Metrics
    cost_incurred: float = 0.0
    llm_calls_count: Dict[str, int] = {
        "SMALL": 0,
        "BIG": 0,
        "VISION": 0
    }

    # FSM tracking
    current_step: str = "init"
    steps_count: int = 0
    max_steps: int = 50
    started_at: float = Field(default_factory=time.time)
    timeout_seconds: int = 300  # 5 min/doc

    # Errors
    errors: List[str] = []
```

---

## 🛠️ Tools (JSON I/O Strict)

### Base Classes

```python
class ToolInput(BaseModel):
    """Schema de base pour input de tool (JSON strict)."""
    pass

class ToolOutput(BaseModel):
    """Schema de base pour output de tool (JSON strict)."""
    success: bool
    message: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
```

### Liste des Tools Implémentés

| Agent                | Tool Name          | Input                                      | Output                              |
|----------------------|--------------------|--------------------------------------------|-------------------------------------|
| ExtractorOrchestrator| prepass_analyzer   | segment_text, language                     | entity_count, recommended_route     |
| ExtractorOrchestrator| extract_concepts   | segment, route, use_llm                    | concepts, cost, llm_calls           |
| PatternMiner         | detect_patterns    | candidates, min_frequency                  | patterns, enriched_candidates       |
| PatternMiner         | link_concepts      | candidates                                 | relations (CO_OCCURRENCE)           |
| GatekeeperDelegate   | gate_check         | candidates, profile_name                   | promoted, rejected, retry_recommended|
| GatekeeperDelegate   | promote_concepts   | concepts                                   | promoted_count                      |
| BudgetManager        | check_budget       | tenant_id, model_tier, requested_calls     | budget_ok, remaining, reason        |
| BudgetManager        | consume_budget     | tenant_id, model_tier, calls, cost         | consumed, new_remaining             |
| BudgetManager        | refund_budget      | tenant_id, model_tier, calls, cost         | refunded, new_remaining             |
| LLMDispatcher        | dispatch_llm       | model_tier, prompt, priority, max_tokens   | response, cost, latency_ms          |
| LLMDispatcher        | get_queue_stats    | -                                          | queue_sizes, active_calls, error_rate|

---

## 📈 KPIs et Métriques

### Métriques Temps-Réel (par document)

| Métrique              | Cible                | Mesure                          |
|-----------------------|----------------------|---------------------------------|
| Cost per doc          | $0.25 (Scénario A)   | `state.cost_incurred`           |
| Processing time       | < 30s/doc            | `time.time() - state.started_at`|
| Promotion rate        | ≥ 30%                | `len(promoted) / len(candidates)`|
| LLM calls SMALL       | ≤ 120/doc            | `state.llm_calls_count["SMALL"]`|
| LLM calls BIG         | ≤ 8/doc              | `state.llm_calls_count["BIG"]`  |
| FSM steps             | ≤ 50/doc             | `state.steps_count`             |

### Métriques Agrégées (tenant/jour)

| Métrique              | Cible                | Mesure                          |
|-----------------------|----------------------|---------------------------------|
| Daily cost            | < $50/tenant/jour    | Redis ZSUM costs:{tenant}:{date}|
| Daily calls SMALL     | ≤ 10k/tenant/jour    | Redis GET budget:tenant:SMALL   |
| Daily calls BIG       | ≤ 500/tenant/jour    | Redis GET budget:tenant:BIG     |
| Error rate            | < 5%                 | Sliding window 100 calls        |
| Circuit breaker trips | 0/jour               | Count OPEN transitions          |

---

## 🚀 Intégration Pipeline

### Avant (Phase 1 V2.1)

```python
# ingestion/osmose_integration.py
async def run_osmose_pipeline(doc_path: str):
    # Segmentation
    segments = await topic_segmenter.segment(doc)

    # Extraction (LLM systématique!)
    concepts = await concept_extractor.extract(segments)

    # Indexation
    indexed = await semantic_indexer.index(concepts)

    # Storage Neo4j
    await store_to_neo4j(indexed)
```

### Après (Phase 1.5 Agentique)

```python
# ingestion/osmose_integration.py
async def run_osmose_pipeline_agentique(doc_path: str):
    # Initialiser état
    state = AgentState(
        document_id=doc_id,
        tenant_id=tenant_id
    )

    # Lancer Supervisor FSM
    supervisor = SupervisorAgent(config)
    final_state = await supervisor.execute(state)

    # Retourner résultats
    return {
        "promoted": final_state.promoted,
        "cost": final_state.cost_incurred,
        "llm_calls": final_state.llm_calls_count,
        "steps": final_state.steps_count
    }
```

---

## ✅ Validation Phase 1.5

### Critères de Succès (GO/NO-GO)

| Critère                      | Cible              | Mesure                    | Status |
|------------------------------|--------------------|--------------------------| ------ |
| Cost Scénario A              | ≤ $1.00/1000p      | Mesure pilote 50 PDF     | 🟡 TODO|
| Cost Scénario B              | ≤ $3.08/1000p      | Mesure pilote 30 PDF     | 🟡 TODO|
| Cost Scénario C              | ≤ $7.88/1000p      | Mesure pilote 20 PPTX    | 🟡 TODO|
| Processing time              | < 30s/doc          | P95 latency              | 🟡 TODO|
| Quality promotion rate       | ≥ 30%              | Gate BALANCED            | 🟡 TODO|
| Rate limit violations        | 0                  | Count 429 errors         | 🟡 TODO|
| Circuit breaker trips        | 0                  | Count OPEN transitions   | 🟡 TODO|
| Multi-tenant isolation       | 100%               | Budget leaks             | 🟡 TODO|

### Tests Pilote (Semaine 11-12)

**Semaine 11 (Jours 3-5)**:
- 50 PDF textuels (Scénario A)
- Objectif: $0.25/doc, < 30s/doc

**Semaine 12**:
- 30 PDF complexes (Scénario B): $0.77/doc
- 20 PPTX (Scénario C): $1.57/doc

---

## 📝 Fichiers Créés

### Code Python

```
src/knowbase/agents/
├── __init__.py                      # Package init
├── base.py                          # BaseAgent, AgentState, ToolInput/Output
├── supervisor/
│   ├── __init__.py
│   └── supervisor.py                # SupervisorAgent (FSM Master)
├── extractor/
│   ├── __init__.py
│   └── orchestrator.py              # ExtractorOrchestrator
├── miner/
│   ├── __init__.py
│   └── miner.py                     # PatternMiner
├── gatekeeper/
│   ├── __init__.py
│   └── gatekeeper.py                # GatekeeperDelegate
├── budget/
│   ├── __init__.py
│   └── budget.py                    # BudgetManager
└── dispatcher/
    ├── __init__.py
    └── dispatcher.py                # LLMDispatcher
```

### Configuration YAML

```
config/agents/
├── supervisor.yaml                  # FSM config, retry policy
├── routing_policies.yaml            # Routing thresholds, model configs
├── gate_profiles.yaml               # STRICT/BALANCED/PERMISSIVE
└── budget_limits.yaml               # Caps, quotas, cost targets
```

### Documentation

```
doc/phase1_osmose/
└── PHASE1.5_ARCHITECTURE_AGENTIQUE.md  # Ce fichier
```

---

## 🔮 Prochaines Étapes

### Semaine 11 (Jours 3-5)
- [ ] Tests unitaires pour chaque agent
- [ ] Intégration avec `osmose_integration.py`
- [ ] Setup Redis (quotas tracking)
- [ ] Pilote Scénario A (50 PDF textuels)
- [ ] Dashboard Grafana (10 KPIs)

### Semaine 12
- [ ] Pilote Scénarios B & C
- [ ] Optimisation budgets (ajustement seuils)
- [ ] Tests multi-tenant isolation
- [ ] Rapport technique 20 pages

### Semaine 13
- [ ] Analyse résultats pilote
- [ ] Décision GO/NO-GO Phase 2
- [ ] Validation critères de succès
- [ ] Présentation stakeholders

---

**Fin Phase 1.5 - Architecture Agentique V1.1**

*Date création: 2025-10-15*
*Auteur: Claude Code + User*
*Version: 1.1.0*
