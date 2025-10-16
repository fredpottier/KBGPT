# 🤖 Architecture Agentique pour OSMOSE - Étude Complète

**Projet:** KnowWhere - OSMOSE
**Type:** Étude exploratoire (validation en attente)
**Date:** 2025-10-13
**Statut:** 🟡 DRAFT - Non validé

---

## Executive Summary

Cette étude propose une **architecture agentique orchestrée** pour le pipeline d'ingestion OSMOSE Dual-KG, avec objectif de **maîtriser coûts LLM** tout en préservant qualité sémantique. **Design minimal: 5 agents spécialisés** (Supervisor, Extractor Orchestrator, Pattern Miner, Gatekeeper Delegate, Budget Manager) coordonnés via FSM strict (no free-form). **Politiques de routing quantifiées**: NO_LLM (<3 entités), LLM_SMALL (3-8 entités), LLM_BIG (>8 ou cross-segment Top-3). **Gate profiles objectivés** avec formules chiffrées (narrative_coherence via cosine embedding clusters, semantic_uniqueness via SimHash distance). **Budget Governor**: caps durs 120 calls SMALL/doc, 8 calls BIG/doc, 2 vision/doc max. **Cost model chiffré**: Scénario A (mostly SMALL) = **0,18$/1000 pages**, Scénario B (mix BIG) = **0,42$/1000 pages** (hypothèses: 4 segments/page, 300 tokens/segment). **KPIs cibles**: Cost/promoted <0,05$, Precision@Promote >90%, Orphan Ratio <8%, cache hit-rate >60%. **Plan pilote 3 semaines**: 100 docs A/B test (SMALL vs BIG dominance), seuils go/no-go sur coût/précision. **Risque majeur**: explosion RELATED_TO si pas de cap 5% strict. **Evidence spans extractives obligatoires** pour toute promotion, Neo4j = SSoT facts, Qdrant = vecteurs + neo4j_id pointeurs. Architecture **ready-to-implement** avec JSON schemas, YAML configs, pseudo-code FSM, et redlines précises sur docs existants.

---

## Table des Matières

1. [Étude de Pertinence](#1-étude-de-pertinence)
2. [Design Agentique Minimal](#2-design-agentique-minimal)
3. [FSM & Workflow Orchestration](#3-fsm--workflow-orchestration)
4. [Schéma de Tools (I/O JSON)](#4-schéma-de-tools-io-json)
5. [Politiques de Routing & Prompts](#5-politiques-de-routing--prompts)
6. [Gate Profiles & Formules](#6-gate-profiles--formules)
7. [Budget Governor & Cost Model](#7-budget-governor--cost-model)
8. [KPIs & SLAs](#8-kpis--slas)
9. [Redlines Documentation Existante](#9-redlines-documentation-existante)
10. [Plan Pilote](#10-plan-pilote)

**Annexes:**
- A. YAML Configs Complets
- B. Schémas JSON Tools
- C. Pseudo-code FSM
- D. Calculs Cost Model Détaillés

---

## 1. Étude de Pertinence

### 1.1 Pourquoi une Architecture Agentique ?

**Problème actuel** (architecture monolithique OSMOSE):
- Pipeline séquentiel rigide : Profile → Segment → Extract → Stage
- Décisions routing LLM hardcodées dans code Python
- Pas de coordination budget inter-segments
- Impossible d'adapter stratégie extraction en fonction du contexte document
- Coûts LLM non prévisibles ni maîtrisables

**Bénéfices architecture agentique**:

| Bénéfice | Impact Quantifié | Justification |
|----------|------------------|---------------|
| **Maîtrise coûts** | -40% à -60% coûts LLM | Routing intelligent NO_LLM/SMALL/BIG, batch optimisé, cache cross-doc |
| **Qualité préservée** | Precision@Promote >90% | Escalade BIG seulement si nécessaire, second opinion Top-K |
| **Scalabilité** | 10x throughput | Parallélisation agents, async tools, queue management |
| **Observabilité** | 100% traçabilité | Chaque décision agent = event structuré, replay possible |
| **Adaptabilité** | Tuning hebdo auto | Gate profiles & budget params ajustés via feedback loop KPIs |

### 1.2 Comparaison Architecture

| Critère | Monolithique (actuel) | Agentique (proposé) |
|---------|----------------------|---------------------|
| **Routing LLM** | Hardcodé (if/else) | Policies déclaratives (YAML) |
| **Budget control** | Aucun (explosion possible) | Governor centralisé avec caps durs |
| **Cross-segment reasoning** | Impossible ou coûteux (10k tokens) | Top-K éligibles seulement, batch différé |
| **Cache** | Par appel LLM (basique) | Cross-doc SimHash + semantic cache |
| **Observabilité** | Logs Python basiques | Events structurés, metrics temps-réel |
| **Coût/doc estimé** | 0,60$ - 1,20$ (non maîtrisé) | 0,18$ - 0,42$ (selon scénario) |

### 1.3 Décision Recommandée

**✅ GO Architecture Agentique** pour OSMOSE Phase 2+

**Justification**:
- Objectif business KnowWhere = scalabilité (1000+ docs/jour à terme)
- Coûts LLM = OPEX principal (prédictibilité critique)
- Architecture agentique = standard industry (LangGraph, CrewAI, AutoGen pattern)
- Implémentation progressive possible (agents par agents)

**Contre-indication**: Si Phase 1 échoue (CRR Evolution non démontrée), alors pas besoin agentique.

---

## 2. Design Agentique Minimal

### 2.1 Principe de Contrôle

**Architecture**: **Supervisor + Specialists** (5 agents total)

```
┌─────────────────────────────────────────────────────────┐
│                   Supervisor Agent                      │
│  (FSM Master, timeout enforcement, error handling)      │
└────┬───────────────────────────────────────────────┬────┘
     │                                                │
     ├─── Extractor Orchestrator ────────────────────┤
     │    (routing NO_LLM/SMALL/BIG, batch mgmt)     │
     │                                                │
     ├─── Pattern Miner ─────────────────────────────┤
     │    (cross-segment eligibility, relate mining) │
     │                                                │
     ├─── Gatekeeper Delegate ───────────────────────┤
     │    (proto→published eval, profile matching)   │
     │                                                │
     └─── Budget Manager ────────────────────────────┘
          (pre-check, consume, refund, alerting)
```

**Pas de free-form**: FSM strict avec transitions explicites, max_steps=50, timeout=300s/doc.

### 2.2 Rôles des Agents

#### Agent 1: **Supervisor** (Orchestrateur Principal)

**Responsabilités**:
- Contrôle FSM global (init → route → extract → mine → gate → finalize)
- Timeout enforcement (300s max/doc, 30s max/state)
- Error handling & retry logic (3 retries max, exponential backoff)
- Metrics emission (latency, success_rate, error_types)

**Politiques de Décision**:
- Transition état suivant si state.is_complete == True
- Abort si timeout_exceeded ou error_count > 3
- Escalade humaine si état = BLOCKED (orphan ratio >20%, budget exceeded)

**Tools Autorisés**:
- `emit_metrics(metric_name, value, tags)`
- `check_timeout(state, max_seconds)`
- `handle_error(error, retry_policy)`
- `log_event(level, message, context)`

**Pseudo-code FSM** (voir Section 3)

---

#### Agent 2: **Extractor Orchestrator** (Extraction Intelligente)

**Responsabilités**:
- Router chaque segment: NO_LLM | LLM_SMALL | LLM_BIG | VISION
- Batch segments pour appels LLM (2-6 segments/batch selon tokens)
- Gestion cache: vérifier `cache_get(simhash)` avant appel LLM
- Orchestrer extraction cross-segment (Top-K éligibles seulement)

**Politiques de Décision**:

```python
def route_segment(segment: Segment, doc_intel: DocumentIntelligence) -> Route:
    # Policy 1: NO_LLM si entités < 3 ET pas de narrative thread
    if segment.entity_count_estimate < 3 and not segment.in_narrative_thread:
        return Route.NO_LLM

    # Policy 2: LLM_SMALL si 3-8 entités ET complexity <= 0.6
    if 3 <= segment.entity_count_estimate <= 8 and segment.complexity <= 0.6:
        return Route.LLM_SMALL

    # Policy 3: LLM_BIG si >8 entités OU complexity > 0.6 OU narrative thread
    if segment.entity_count_estimate > 8 or segment.complexity > 0.6 or segment.in_narrative_thread:
        return Route.LLM_BIG

    # Policy 4: VISION si contains_charts et vision_budget_available
    if segment.contains_charts and budget.vision_calls_remaining > 0:
        return Route.VISION

    return Route.LLM_SMALL  # Fallback
```

**Seuils Chiffrés**:
- NO_LLM: <3 entités estimées
- LLM_SMALL: 3-8 entités, complexity ≤0.6, tokens <600
- LLM_BIG: >8 entités OU complexity >0.6 OU narrative thread
- VISION: charts détectés ET budget vision disponible (≤2 calls/doc)

**Batch Policy**:
```python
def create_batches(segments: List[Segment], route: Route) -> List[Batch]:
    max_tokens_per_batch = {
        Route.LLM_SMALL: 1800,  # ~3-4 segments
        Route.LLM_BIG: 3000      # ~2-3 segments
    }

    batches = []
    current_batch = []
    current_tokens = 0

    for seg in segments:
        if current_tokens + seg.token_estimate > max_tokens_per_batch[route]:
            batches.append(Batch(segments=current_batch, route=route))
            current_batch = [seg]
            current_tokens = seg.token_estimate
        else:
            current_batch.append(seg)
            current_tokens += seg.token_estimate

    if current_batch:
        batches.append(Batch(segments=current_batch, route=route))

    return batches
```

**Tools Autorisés**:
- `route_segments(segments, doc_intel) -> List[RoutedSegment]`
- `llm_extract_batch(batch, model, prompt_template) -> ExtractionResult`
- `vision_extract(segment, image_data) -> ExtractionResult`
- `cache_get(simhash) -> Optional[CachedResult]`
- `cache_put(simhash, result, ttl=86400)`
- `normalize_and_link(entities, relations) -> NormalizedGraph`
- `write_protokg(graph, tenant_id, document_id)`

---

#### Agent 3: **Pattern Miner** (Cross-Segment Reasoning)

**Responsabilités**:
- Identifier Top-K segments éligibles au cross-segment reasoning
- Miner relations cross-segment (RELATED_TO via semantic similarity)
- Appliquer cap strict RELATED_TO ≤ 5% total relations
- Détecter patterns émergents (pour Living Ontology Phase 3)

**Politiques de Décision**:

```python
def select_cross_segment_eligible(segments: List[Segment], K=3) -> List[Segment]:
    """
    Critères éligibilité cross-segment (Top-K/doc):
    1. Complexity >0.7 (zones denses)
    2. In narrative thread (continuité sémantique)
    3. Connectivity delta attendu >0.3 (segments isolés à relier)
    """
    scored = []
    for seg in segments:
        score = 0.0
        if seg.complexity > 0.7:
            score += 0.4
        if seg.in_narrative_thread:
            score += 0.4
        if seg.connectivity_delta_expected > 0.3:  # Segment isolé = potentiel lien
            score += 0.2
        scored.append((seg, score))

    # Top-K seulement
    scored.sort(key=lambda x: x[1], reverse=True)
    return [seg for seg, score in scored[:K] if score >= 0.5]  # Threshold 0.5 min
```

**Cross-Segment Reasoning Format**:
```python
# Input pour LLM cross-segment
cross_segment_input = {
    "document_context": {
        "title": doc.title,
        "domain": doc.domain,
        "narrative_threads": [t.summary for t in doc.narrative_threads]
    },
    "segments": [
        {
            "segment_id": seg.id,
            "text": seg.text,
            "entities_extracted": seg.entities,  # Déjà extraites en intra-segment
            "position": seg.position
        }
        for seg in eligible_segments  # Top-K seulement
    ],
    "task": "Identify IMPLICIT semantic relations between entities across these segments. Focus on: causal links, temporal sequences, conceptual hierarchies. Output ONLY relations not already extracted intra-segment."
}
```

**Garde-fous**:
- Indépendance segment_id préservée (pas de fusion segments)
- RELATED_TO cap: si relations_count * 0.05 < related_to_count, ABORT
- Budget: 1 appel BIG cross-segment max/doc (réservé Top-3)

**Tools Autorisés**:
- `mine_relaters(segments, existing_graph, max_K=3) -> List[Relation]`
- `llm_cross_segment(eligible_segments, context) -> CrossSegmentResult`
- `simhash_match(entity_a, entity_b, threshold=0.85) -> bool`
- `compute_connectivity_delta(segment, graph) -> float`

---

#### Agent 4: **Gatekeeper Delegate** (Quality Control)

**Responsabilités**:
- Évaluer chaque candidat Proto-KG via gate profile (domaine/langue)
- Calculer composite score multi-critères (voir Section 6)
- Décider: AUTO_PROMOTE | HUMAN_REVIEW | REJECT
- Gérer second opinion LLM si score dans zone grise [0.70-0.80]

**Politiques de Décision**:

```python
def evaluate_candidate(candidate: CandidateEntity, profile: GateProfile) -> PromotionDecision:
    # Critères de base
    base_score = (
        profile.weights.llm_confidence * candidate.llm_confidence +
        profile.weights.source_count * min(candidate.source_count / 3.0, 1.0) +
        profile.weights.type_validity * candidate.type_validity_score +
        profile.weights.orphan_penalty * (1.0 - candidate.is_orphan)
    )

    # Critères intelligence sémantique (OSMOSE)
    intel_score = (
        profile.weights.narrative_coherence * candidate.narrative_coherence +
        profile.weights.semantic_uniqueness * candidate.semantic_uniqueness +
        profile.weights.causal_reasoning * candidate.causal_reasoning_quality +
        profile.weights.contextual_richness * candidate.contextual_richness
    )

    composite_score = (base_score * 0.6) + (intel_score * 0.4)  # 60/40 base/intel

    # Décision
    if composite_score >= profile.thresholds.auto_promote:  # Ex: 0.85
        return PromotionDecision(action=Action.AUTO_PROMOTE, score=composite_score)
    elif composite_score >= profile.thresholds.human_review:  # Ex: 0.70
        # Zone grise: second opinion
        second_opinion = llm_second_opinion(candidate, profile)
        if second_opinion.confidence > 0.75:
            return PromotionDecision(action=Action.AUTO_PROMOTE, score=composite_score, second_opinion=True)
        else:
            return PromotionDecision(action=Action.HUMAN_REVIEW, score=composite_score)
    else:
        return PromotionDecision(action=Action.REJECT, score=composite_score)
```

**Seuils par Profile** (voir Section 6 pour formules détaillées):
- `auto_promote_threshold`: 0.85 (finance), 0.80 (pharma), 0.75 (general)
- `human_review_threshold`: 0.70 (tous domaines)
- `reject_threshold`: <0.70

**Tools Autorisés**:
- `promote_via_gate(candidate, profile) -> PromotionDecision`
- `llm_second_opinion(candidate, profile) -> SecondOpinion`
- `compute_narrative_coherence(candidate, proto_context) -> float`
- `compute_semantic_uniqueness(candidate, proto_graph) -> float`
- `json_validate(candidate, schema) -> ValidationResult`

---

#### Agent 5: **Budget Manager** (Cost Control)

**Responsabilités**:
- Pre-check budget disponible avant chaque appel LLM
- Consume budget (tracker appels, tokens, coûts)
- Refund si erreur/retry
- Alerting si seuils dépassés (>90% budget doc, >80% vision calls)

**Politiques de Décision**:

```python
def budget_check(doc_id: str, call_type: CallType) -> BudgetCheckResult:
    """
    Caps durs par document:
    - max_calls_small: 120
    - max_calls_big: 8
    - max_calls_vision: 2
    - max_tokens_per_call: 4000 (SMALL), 8000 (BIG)
    """
    current = get_budget_state(doc_id)

    if call_type == CallType.SMALL:
        if current.calls_small >= 120:
            return BudgetCheckResult(allowed=False, reason="SMALL calls cap exceeded")
    elif call_type == CallType.BIG:
        if current.calls_big >= 8:
            return BudgetCheckResult(allowed=False, reason="BIG calls cap exceeded")
    elif call_type == CallType.VISION:
        if current.calls_vision >= 2:
            return BudgetCheckResult(allowed=False, reason="VISION calls cap exceeded")

    # Check total cost cap (optional, par tenant)
    if current.cost_usd > get_tenant_budget_cap(doc_id):
        return BudgetCheckResult(allowed=False, reason="Tenant budget cap exceeded")

    return BudgetCheckResult(allowed=True)

def budget_consume(doc_id: str, call_type: CallType, tokens_used: int, cost_usd: float):
    """Incrémenter compteurs + persist Redis"""
    state = get_budget_state(doc_id)

    if call_type == CallType.SMALL:
        state.calls_small += 1
    elif call_type == CallType.BIG:
        state.calls_big += 1
    elif call_type == CallType.VISION:
        state.calls_vision += 1

    state.tokens_used += tokens_used
    state.cost_usd += cost_usd

    set_budget_state(doc_id, state)

    # Alerting
    if state.cost_usd / get_doc_budget_target(doc_id) > 0.9:
        emit_alert("budget_90_percent", doc_id, state)
```

**Tools Autorisés**:
- `budget_check(doc_id, call_type) -> BudgetCheckResult`
- `budget_consume(doc_id, call_type, tokens, cost_usd)`
- `budget_refund(doc_id, call_type, tokens, cost_usd)`
- `get_budget_state(doc_id) -> BudgetState`
- `emit_alert(alert_type, doc_id, context)`

---

### 2.3 Mapping Agents → Tools (Tableau Récapitulatif)

| Agent | Tools Principaux | Criticité | Latence Typique |
|-------|------------------|-----------|-----------------|
| **Supervisor** | `emit_metrics`, `check_timeout`, `handle_error` | 🔴 P0 | <10ms |
| **Extractor Orchestrator** | `route_segments`, `llm_extract_batch`, `cache_get`, `write_protokg` | 🔴 P0 | 5-20s |
| **Pattern Miner** | `mine_relaters`, `llm_cross_segment`, `simhash_match` | 🟡 P1 | 3-8s |
| **Gatekeeper Delegate** | `promote_via_gate`, `llm_second_opinion`, `compute_*` | 🔴 P0 | 2-5s |
| **Budget Manager** | `budget_check`, `budget_consume`, `budget_refund` | 🔴 P0 | <50ms |

---

## 3. FSM & Workflow Orchestration

### 3.1 States Machine (10 états)

```
INIT → ROUTE → EXTRACT_BATCH → CROSS_SEGMENT → NORMALIZE →
WRITE_PROTO → GATE_EVAL → PROMOTE → FINALIZE → [END | ERROR]
```

**Timeouts**:
- Global: 300s/document (abort si dépassé)
- Per-state: 30s max (sauf EXTRACT_BATCH: 60s, CROSS_SEGMENT: 45s)

**Max-steps**: 50 transitions max (évite boucles infinies)

### 3.2 Diagramme FSM

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  [INIT]  Document loaded, budget initialized                │
│    │                                                          │
│    v                                                          │
│  [ROUTE]  Extractor Orchestrator: route segments             │
│    │      NO_LLM/SMALL/BIG/VISION                            │
│    v                                                          │
│  [EXTRACT_BATCH]  Parallel LLM calls (batches 2-6 segs)     │
│    │              Cache check, normalize entities            │
│    v                                                          │
│  [CROSS_SEGMENT]  Pattern Miner: Top-K eligible only        │
│    │              (optional, si K>0)                          │
│    v                                                          │
│  [NORMALIZE]  Dedup via SimHash, link entities              │
│    │                                                          │
│    v                                                          │
│  [WRITE_PROTO]  Persist to Neo4j Proto-KG                   │
│    │                                                          │
│    v                                                          │
│  [GATE_EVAL]  Gatekeeper Delegate: score all candidates     │
│    │                                                          │
│    v                                                          │
│  [PROMOTE]  Auto-promote ≥0.85, Human review 0.70-0.85      │
│    │                                                          │
│    v                                                          │
│  [FINALIZE]  Emit metrics, cleanup, mark doc processed      │
│    │                                                          │
│    v                                                          │
│  [END]  Success                                              │
│                                                              │
│  [ERROR]  Retry logic (max 3), then escalate human          │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 Pseudo-code FSM (Supervisor)

```python
class SupervisorAgent:
    def __init__(self, config: Config):
        self.fsm = FSM(states=STATES, initial=State.INIT)
        self.timeout_global = 300  # seconds
        self.timeout_per_state = 30
        self.max_steps = 50
        self.retry_policy = RetryPolicy(max_retries=3, backoff_factor=2)

    async def orchestrate_document(self, doc: Document) -> Result:
        start_time = time.time()
        step_count = 0
        state = State.INIT
        context = Context(doc=doc, budget=BudgetState(), errors=[])

        while state != State.END and state != State.ERROR:
            step_count += 1

            # Guardrails
            if step_count > self.max_steps:
                return Result(status=Status.ERROR, reason="Max steps exceeded")

            if time.time() - start_time > self.timeout_global:
                return Result(status=Status.TIMEOUT, reason="Global timeout exceeded")

            # Execute state
            try:
                state_start = time.time()
                next_state, context = await self.execute_state(state, context)
                state_duration = time.time() - state_start

                # Per-state timeout check
                timeout_state = self.get_state_timeout(state)
                if state_duration > timeout_state:
                    self.emit_warning(f"State {state} exceeded timeout {timeout_state}s")

                # Transition
                self.emit_metrics("state_transition", {
                    "from": state,
                    "to": next_state,
                    "duration_ms": state_duration * 1000
                })
                state = next_state

            except Exception as e:
                context.errors.append(e)

                # Retry logic
                if len(context.errors) <= self.retry_policy.max_retries:
                    await asyncio.sleep(self.retry_policy.backoff_factor ** len(context.errors))
                    continue  # Retry same state
                else:
                    state = State.ERROR

        # Finalize
        total_duration = time.time() - start_time
        self.emit_metrics("document_processed", {
            "doc_id": doc.id,
            "status": state,
            "duration_s": total_duration,
            "steps": step_count,
            "cost_usd": context.budget.cost_usd
        })

        return Result(status=Status.SUCCESS if state == State.END else Status.ERROR, context=context)

    async def execute_state(self, state: State, context: Context) -> Tuple[State, Context]:
        if state == State.INIT:
            # Initialize budget, load doc
            context.budget = BudgetState(doc_id=context.doc.id)
            return (State.ROUTE, context)

        elif state == State.ROUTE:
            # Extractor Orchestrator: route segments
            routed = await self.extractor_orchestrator.route_segments(
                context.doc.segments,
                context.doc.intelligence
            )
            context.routed_segments = routed
            return (State.EXTRACT_BATCH, context)

        elif state == State.EXTRACT_BATCH:
            # Parallel extraction batches
            results = await self.extractor_orchestrator.extract_all_batches(
                context.routed_segments,
                context.budget
            )
            context.extraction_results = results

            # Decide if cross-segment needed
            if self.pattern_miner.has_eligible_segments(context.doc):
                return (State.CROSS_SEGMENT, context)
            else:
                return (State.NORMALIZE, context)

        elif state == State.CROSS_SEGMENT:
            # Pattern Miner: Top-K cross-segment
            cross_relations = await self.pattern_miner.mine_cross_segment(
                context.doc.segments,
                context.extraction_results,
                K=3
            )
            context.extraction_results.add_relations(cross_relations)
            return (State.NORMALIZE, context)

        elif state == State.NORMALIZE:
            # Normalize & link entities
            graph = await self.extractor_orchestrator.normalize_and_link(
                context.extraction_results
            )
            context.proto_graph = graph
            return (State.WRITE_PROTO, context)

        elif state == State.WRITE_PROTO:
            # Persist to Neo4j Proto-KG
            await self.extractor_orchestrator.write_protokg(
                context.proto_graph,
                context.doc.tenant_id,
                context.doc.id
            )
            return (State.GATE_EVAL, context)

        elif state == State.GATE_EVAL:
            # Gatekeeper evaluation
            decisions = await self.gatekeeper_delegate.evaluate_all_candidates(
                context.proto_graph,
                context.doc.domain
            )
            context.promotion_decisions = decisions
            return (State.PROMOTE, context)

        elif state == State.PROMOTE:
            # Execute promotions
            promoted_count = await self.gatekeeper_delegate.execute_promotions(
                context.promotion_decisions
            )
            context.metrics.promoted_count = promoted_count
            return (State.FINALIZE, context)

        elif state == State.FINALIZE:
            # Cleanup, emit final metrics
            await self.emit_final_metrics(context)
            return (State.END, context)

        else:
            raise ValueError(f"Unknown state: {state}")

    def get_state_timeout(self, state: State) -> int:
        timeouts = {
            State.EXTRACT_BATCH: 60,
            State.CROSS_SEGMENT: 45,
        }
        return timeouts.get(state, 30)  # Default 30s
```

---

## 4. Schéma de Tools (I/O JSON)

### 4.1 Tool: `route_segments`

**Responsabilité**: Router chaque segment vers NO_LLM/SMALL/BIG/VISION

**Input**:
```json
{
  "segments": [
    {
      "segment_id": "seg_001",
      "text": "Customer Retention Rate (CRR) measures...",
      "position": {"page": 1, "section": "2.1"},
      "token_estimate": 280,
      "entity_count_estimate": 5,
      "complexity": 0.45,
      "contains_charts": false,
      "in_narrative_thread": true,
      "narrative_thread_id": "thread_crr_evolution"
    }
  ],
  "document_intelligence": {
    "domain": "finance",
    "overall_complexity": 0.62,
    "narrative_threads_count": 2
  }
}
```

**Output**:
```json
{
  "routed_segments": [
    {
      "segment_id": "seg_001",
      "route": "LLM_BIG",
      "reason": "in_narrative_thread=true",
      "estimated_cost_usd": 0.008,
      "batch_group": "batch_big_001"
    }
  ]
}
```

**Erreurs**:
- `INVALID_SEGMENT`: segment manque champs obligatoires
- `ROUTE_POLICY_ERROR`: policy ne peut pas déterminer route

**Idempotence**: Oui (même input → même routing)

---

### 4.2 Tool: `llm_extract_batch`

**Responsabilité**: Appel LLM pour extraction batch (2-6 segments)

**Input**:
```json
{
  "batch_id": "batch_small_003",
  "model": "gpt-4o-mini",
  "segments": [
    {
      "segment_id": "seg_005",
      "text": "The revised methodology excludes inactive accounts..."
    },
    {
      "segment_id": "seg_006",
      "text": "ISO 23592 standard compliance was achieved in Q3..."
    }
  ],
  "prompt_template": "extract_entities_strict",
  "domain": "finance",
  "output_schema": {
    "type": "object",
    "properties": {
      "entities": {"type": "array"},
      "relations": {"type": "array"}
    },
    "required": ["entities", "relations"]
  },
  "max_tokens": 2000
}
```

**Output**:
```json
{
  "batch_id": "batch_small_003",
  "success": true,
  "results": [
    {
      "segment_id": "seg_005",
      "entities": [
        {
          "name": "CRR Revised Methodology",
          "type": "Methodology",
          "confidence": 0.92,
          "evidence_spans": [
            {"start": 0, "end": 45, "text": "The revised methodology excludes inactive..."}
          ],
          "properties": {
            "excludes": "inactive_accounts",
            "version": "v2.0"
          }
        }
      ],
      "relations": [
        {
          "source": "CRR Revised Methodology",
          "target": "CRR v1.0",
          "type": "SUPERSEDES",
          "confidence": 0.88,
          "evidence_spans": [
            {"start": 20, "end": 45, "text": "revised methodology"}
          ]
        }
      ]
    }
  ],
  "tokens_used": 1250,
  "cost_usd": 0.0025,
  "latency_ms": 1800,
  "model_used": "gpt-4o-mini"
}
```

**Erreurs**:
- `LLM_TIMEOUT`: appel LLM >30s
- `LLM_INVALID_RESPONSE`: réponse ne match pas schema
- `LLM_RATE_LIMIT`: quota API dépassé
- `BUDGET_EXCEEDED`: budget check failed

**Idempotence**: Non (cache via `cache_get` avant appel)

---

### 4.3 Tool: `llm_second_opinion`

**Responsabilité**: Second avis LLM pour candidats en zone grise (score 0.70-0.85)

**Input**:
```json
{
  "candidate": {
    "entity_name": "Customer Retention Rate ISO",
    "entity_type": "Metric",
    "confidence": 0.78,
    "evidence_spans": [...],
    "properties": {...},
    "composite_score": 0.76
  },
  "gate_profile": {
    "domain": "finance",
    "thresholds": {
      "auto_promote": 0.85,
      "human_review": 0.70
    }
  },
  "proto_context": {
    "similar_entities_count": 2,
    "orphan_status": false
  }
}
```

**Output**:
```json
{
  "second_opinion": {
    "confidence": 0.82,
    "reasoning": "Entity has strong evidence spans and semantic uniqueness score 0.88. Recommend promotion despite borderline base score.",
    "recommend_promote": true,
    "adjusted_score": 0.82
  },
  "tokens_used": 450,
  "cost_usd": 0.0012,
  "model_used": "gpt-4o-mini"
}
```

**Erreurs**: Idem `llm_extract_batch`

**Idempotence**: Non

---

### 4.4 Tool: `vision_extract`

**Responsabilité**: Extraction vision API (charts, tables)

**Input**:
```json
{
  "segment_id": "seg_012",
  "image_data": "base64_encoded_image",
  "image_metadata": {
    "width": 1200,
    "height": 800,
    "format": "png"
  },
  "prompt": "Extract all entities and relations from this chart.",
  "model": "gpt-4o"
}
```

**Output**:
```json
{
  "segment_id": "seg_012",
  "entities": [...],
  "relations": [...],
  "tokens_used": 1500,
  "cost_usd": 0.015,
  "confidence": 0.75
}
```

**Erreurs**:
- `VISION_UNSUPPORTED_FORMAT`: format image non supporté
- `VISION_BUDGET_EXCEEDED`: cap 2 calls/doc atteint

**Idempotence**: Non

---

### 4.5 Tool: `json_validate`

**Responsabilité**: Validation JSON schema strict

**Input**:
```json
{
  "data": {
    "entities": [...],
    "relations": [...]
  },
  "schema": {
    "type": "object",
    "properties": {...},
    "required": ["entities", "relations"]
  }
}
```

**Output**:
```json
{
  "valid": true,
  "errors": []
}
```

**Erreurs**:
- `SCHEMA_VALIDATION_FAILED`: data ne match pas schema

**Idempotence**: Oui

---

### 4.6 Tool: `normalize_and_link`

**Responsabilité**: Normalisation entités + link via SimHash

**Input**:
```json
{
  "extraction_results": [
    {
      "segment_id": "seg_001",
      "entities": [
        {"name": "CRR", "type": "Metric", "confidence": 0.90},
        {"name": "Customer Retention Rate", "type": "Metric", "confidence": 0.92}
      ],
      "relations": [...]
    }
  ],
  "simhash_threshold": 0.85
}
```

**Output**:
```json
{
  "normalized_graph": {
    "entities": [
      {
        "normalized_name": "Customer Retention Rate",
        "canonical_id": "entity_001",
        "merged_from": ["CRR", "Customer Retention Rate"],
        "simhash": "0xABCD1234",
        "type": "Metric",
        "confidence_max": 0.92,
        "evidence_spans_merged": [...]
      }
    ],
    "relations": [...],
    "dedup_count": 1
  }
}
```

**Erreurs**: Aucune (best-effort)

**Idempotence**: Oui

---

### 4.7 Tool: `write_protokg`

**Responsabilité**: Persist graph to Neo4j Proto-KG

**Input**:
```json
{
  "graph": {
    "entities": [...],
    "relations": [...]
  },
  "tenant_id": "tenant_acme",
  "document_id": "doc_12345",
  "metadata": {
    "processed_at": "2025-10-13T14:30:00Z",
    "pipeline_version": "osmose-v1.0"
  }
}
```

**Output**:
```json
{
  "success": true,
  "entities_written": 42,
  "relations_written": 58,
  "neo4j_transaction_id": "tx_789"
}
```

**Erreurs**:
- `NEO4J_CONNECTION_ERROR`: connexion échouée
- `NEO4J_WRITE_ERROR`: transaction échouée

**Idempotence**: Oui (upsert via MERGE sur candidate_id)

---

### 4.8 Tool: `promote_via_gate`

**Responsabilité**: Évaluation gatekeeper + décision promotion

**Input**:
```json
{
  "candidate": {
    "candidate_id": "cand_001",
    "entity_name": "ISO 23592",
    "entity_type": "Standard",
    "confidence": 0.90,
    "evidence_spans": [...],
    "source_count": 3,
    "properties": {...}
  },
  "gate_profile": {
    "domain": "finance",
    "weights": {...},
    "thresholds": {...}
  },
  "proto_context": {
    "similar_entities": [...],
    "narrative_threads": [...]
  }
}
```

**Output**:
```json
{
  "decision": {
    "action": "AUTO_PROMOTE",
    "composite_score": 0.87,
    "breakdown": {
      "base_score": 0.85,
      "intel_score": 0.90,
      "narrative_coherence": 0.88,
      "semantic_uniqueness": 0.92,
      "causal_reasoning_quality": 0.85
    },
    "reason": "Score 0.87 >= auto_promote_threshold 0.85"
  }
}
```

**Erreurs**: Aucune (toujours retourne décision)

**Idempotence**: Oui (même candidate → même score)

---

### 4.9 Tool: `mine_relaters`

**Responsabilité**: Mine relations cross-segment (Top-K éligibles)

**Input**:
```json
{
  "eligible_segments": [
    {"segment_id": "seg_003", "entities": [...]},
    {"segment_id": "seg_007", "entities": [...]},
    {"segment_id": "seg_012", "entities": [...]}
  ],
  "existing_graph": {
    "entities": [...],
    "relations": [...]
  },
  "max_K": 3,
  "related_to_cap_percent": 5.0
}
```

**Output**:
```json
{
  "cross_segment_relations": [
    {
      "source": "CRR Revised",
      "target": "CRR v1.0",
      "type": "RELATED_TO",
      "confidence": 0.78,
      "evidence": "Both entities discussed in narrative thread",
      "cross_segment": true
    }
  ],
  "related_to_count": 2,
  "related_to_percent": 3.4,
  "cap_respected": true
}
```

**Erreurs**:
- `CAP_EXCEEDED`: RELATED_TO >5% abort

**Idempotence**: Oui

---

### 4.10 Tool: `compact_rotate`

**Responsabilité**: Lifecycle management Proto-KG (HOT→WARM→COLD)

**Input**:
```json
{
  "tenant_id": "tenant_acme",
  "policy": {
    "hot_ttl_days": 7,
    "warm_ttl_days": 30,
    "cold_ttl_days": 90
  }
}
```

**Output**:
```json
{
  "compacted": {
    "entities_moved_warm": 120,
    "entities_moved_cold": 45,
    "entities_deleted_frozen": 10
  }
}
```

**Erreurs**: Best-effort (log warnings)

**Idempotence**: Oui (dates check)

---

### 4.11 Tool: `budget_check`

**Responsabilité**: Pre-check budget disponible

**Input**:
```json
{
  "doc_id": "doc_12345",
  "call_type": "LLM_SMALL"
}
```

**Output**:
```json
{
  "allowed": true,
  "remaining": {
    "calls_small": 85,
    "calls_big": 6,
    "calls_vision": 2,
    "cost_usd_remaining": 0.35
  }
}
```

**Erreurs**:
- `BUDGET_EXCEEDED`: cap atteint

**Idempotence**: Oui

---

### 4.12 Tool: `budget_consume`

**Responsabilité**: Incrémenter budget post-appel

**Input**:
```json
{
  "doc_id": "doc_12345",
  "call_type": "LLM_SMALL",
  "tokens_used": 1250,
  "cost_usd": 0.0025
}
```

**Output**:
```json
{
  "success": true,
  "new_state": {
    "calls_small": 36,
    "tokens_used": 45000,
    "cost_usd": 0.095
  }
}
```

**Erreurs**: Aucune

**Idempotence**: Non (persist Redis incr)

---

### 4.13 Tool: `cache_get` / `cache_put`

**Responsabilité**: Cache semantic (SimHash-based)

**Input `cache_get`**:
```json
{
  "simhash": "0xABCD1234",
  "cache_scope": "cross_doc"
}
```

**Output `cache_get`**:
```json
{
  "hit": true,
  "cached_result": {
    "entities": [...],
    "relations": [...]
  },
  "cached_at": "2025-10-12T10:30:00Z",
  "ttl_remaining_seconds": 72000
}
```

**Input `cache_put`**:
```json
{
  "simhash": "0xABCD1234",
  "result": {
    "entities": [...],
    "relations": [...]
  },
  "ttl_seconds": 86400
}
```

**Output `cache_put`**:
```json
{
  "success": true
}
```

**Erreurs**: Best-effort (miss si pas en cache)

**Idempotence**: `cache_get` oui, `cache_put` oui (overwrite)

---

### 4.14 Tool: `simhash_match`

**Responsabilité**: Calculer distance SimHash entre 2 entités

**Input**:
```json
{
  "entity_a": {
    "name": "CRR",
    "type": "Metric",
    "text_context": "Customer Retention Rate measures..."
  },
  "entity_b": {
    "name": "Customer Retention Rate",
    "type": "Metric",
    "text_context": "CRR is calculated as..."
  },
  "threshold": 0.85
}
```

**Output**:
```json
{
  "match": true,
  "similarity": 0.91,
  "simhash_a": "0xABCD1234",
  "simhash_b": "0xABCD1278"
}
```

**Erreurs**: Aucune

**Idempotence**: Oui

---

### 4.15 Tool: `emit_metrics`

**Responsabilité**: Émettre métriques temps-réel (Prometheus/StatsD)

**Input**:
```json
{
  "metric_name": "osmose.extraction.latency_ms",
  "value": 1850,
  "tags": {
    "route": "LLM_SMALL",
    "domain": "finance",
    "doc_id": "doc_12345"
  },
  "metric_type": "histogram"
}
```

**Output**:
```json
{
  "success": true
}
```

**Erreurs**: Best-effort (log si échec)

**Idempotence**: Oui (cumulative metrics)

---

## 5. Politiques de Routing & Prompts

### 5.1 Règles de Routing (Seuils Chiffrés)

| Route | Critères | Seuils | Model | Cost/1k tokens |
|-------|----------|--------|-------|----------------|
| **NO_LLM** | Extraction rule-based | <3 entités estimées ET pas narrative thread | N/A | $0 |
| **LLM_SMALL** | Extraction standard | 3-8 entités, complexity ≤0.6, tokens <600 | gpt-4o-mini | $0.002 |
| **LLM_BIG** | Extraction complexe | >8 entités OU complexity >0.6 OU narrative thread | gpt-4o | $0.010 |
| **VISION** | Charts/tables | contains_charts=true ET budget vision disponible | gpt-4o-vision | $0.015 |

### 5.2 Batch Policy (2-6 segments/appel)

```python
# Batch size adaptatif
def compute_batch_size(route: Route, segments: List[Segment]) -> int:
    if route == Route.LLM_SMALL:
        max_tokens_batch = 1800  # ~3-4 segments
    elif route == Route.LLM_BIG:
        max_tokens_batch = 3000  # ~2-3 segments

    batch = []
    batch_tokens = 0

    for seg in segments:
        if batch_tokens + seg.token_estimate > max_tokens_batch:
            yield batch
            batch = [seg]
            batch_tokens = seg.token_estimate
        else:
            batch.append(seg)
            batch_tokens += seg.token_estimate

    if batch:
        yield batch
```

**Contrainte**: Batch size ∈ [2, 6] segments (optimum latency/cost)

### 5.3 Prompts Stricts (JSON + Enums Fermées)

#### Prompt Template: `extract_entities_strict`

```python
EXTRACT_PROMPT = """
You are extracting structured entities and relations from document segments.

**STRICT RULES**:
1. Output ONLY valid JSON matching the schema below
2. Use ONLY these entity types: {allowed_entity_types}
3. Use ONLY these relation types: {allowed_relation_types}
4. For each entity/relation, provide `evidence_spans` with exact char positions
5. NO inference beyond explicit text
6. NO generic relations (e.g., "RELATED_TO" must have semantic justification)

**INPUT SEGMENTS**:
{segments_json}

**OUTPUT SCHEMA**:
{{
  "entities": [
    {{
      "name": "string (exact from text)",
      "type": "enum({allowed_entity_types})",
      "confidence": "float [0.0-1.0]",
      "evidence_spans": [
        {{"start": int, "end": int, "text": "exact quote"}}
      ],
      "properties": {{"key": "value"}}
    }}
  ],
  "relations": [
    {{
      "source": "string (entity name)",
      "target": "string (entity name)",
      "type": "enum({allowed_relation_types})",
      "confidence": "float [0.0-1.0]",
      "evidence_spans": [
        {{"start": int, "end": int, "text": "exact quote"}}
      ]
    }}
  ]
}}

**ALLOWED ENTITY TYPES**: {allowed_entity_types}
**ALLOWED RELATION TYPES**: {allowed_relation_types}

**OUTPUT JSON**:
"""
```

**Paramètres**:
- `allowed_entity_types`: Liste fermée par domaine (ex: finance = ["Metric", "Methodology", "Standard", "Organization"])
- `allowed_relation_types`: ["SUPERSEDES", "MODIFIES", "COMPLIES_WITH", "USES", "PART_OF"] (pas de "RELATED_TO" générique)

#### Prompt Template: `cross_segment_reasoning`

```python
CROSS_SEGMENT_PROMPT = """
You are identifying IMPLICIT semantic relations between entities across document segments.

**CONTEXT**:
- Document: {document_title}
- Domain: {domain}
- Narrative threads: {narrative_threads_summary}

**SEGMENTS** (Top-{K} eligible):
{segments_with_entities_json}

**TASK**:
Identify ONLY relations that are:
1. NOT already extracted intra-segment
2. Semantically meaningful (causal, temporal, hierarchical)
3. Supported by narrative context

**OUTPUT JSON**:
{{
  "cross_segment_relations": [
    {{
      "source": "entity name",
      "target": "entity name",
      "type": "enum({allowed_relation_types})",
      "confidence": float,
      "evidence": "narrative justification",
      "segment_ids": ["seg_X", "seg_Y"]
    }}
  ]
}}

**CONSTRAINTS**:
- Max {max_relations} relations
- Type MUST be one of: {allowed_relation_types}
- NO "RELATED_TO" unless semantic justification provided

**OUTPUT JSON**:
"""
```

**Paramètres**:
- `K`: Top-K segments éligibles (default 3)
- `max_relations`: Cap relations cross-segment (default 10)

### 5.4 Evidence Spans Obligatoires

**Validation stricte**:
```python
def validate_extraction(result: ExtractionResult) -> ValidationResult:
    errors = []

    for entity in result.entities:
        if not entity.evidence_spans or len(entity.evidence_spans) == 0:
            errors.append(f"Entity '{entity.name}' missing evidence_spans")

        for span in entity.evidence_spans:
            if span.start < 0 or span.end <= span.start:
                errors.append(f"Invalid span for '{entity.name}': start={span.start}, end={span.end}")

    for relation in result.relations:
        if not relation.evidence_spans or len(relation.evidence_spans) == 0:
            errors.append(f"Relation '{relation.source}->{relation.target}' missing evidence_spans")

    return ValidationResult(valid=len(errors) == 0, errors=errors)
```

**Reject si**: Entité/relation sans `evidence_spans` = INVALID

### 5.5 Cross-Segment Eligibility (Critères Objectifs)

```python
def compute_eligibility_score(segment: Segment, doc: Document) -> float:
    score = 0.0

    # Critère 1: Complexity haute (zones denses)
    if segment.complexity > 0.7:
        score += 0.4

    # Critère 2: In narrative thread (continuité sémantique)
    if segment.in_narrative_thread:
        score += 0.4

    # Critère 3: Connectivity delta attendu (segment isolé = potentiel lien)
    # Connectivity delta = (relations_attendues - relations_actuelles) / relations_attendues
    expected_relations = segment.entity_count * 0.5  # Heuristique: 50% entités liées
    actual_relations = segment.relations_count
    connectivity_delta = max(0, (expected_relations - actual_relations) / expected_relations)

    if connectivity_delta > 0.3:
        score += 0.2

    return score

def select_top_K_eligible(segments: List[Segment], K=3) -> List[Segment]:
    scored = [(seg, compute_eligibility_score(seg, doc)) for seg in segments]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Seuil min 0.5
    return [seg for seg, score in scored[:K] if score >= 0.5]
```

**Seuils**:
- Complexity >0.7 = +0.4 pts
- In narrative thread = +0.4 pts
- Connectivity delta >0.3 = +0.2 pts
- **Seuil éligibilité**: ≥0.5 (nécessite au moins 2 critères partiels)

### 5.6 Garde-fous NO Inference

**Rules strictes LLM**:
1. **NO inference beyond text**: Extraction extractive seulement, pas de knowledge world
2. **NO generic relations**: "RELATED_TO" interdit sauf justification sémantique explicite
3. **Enums fermées**: Types entités/relations = liste blanche par domaine
4. **Evidence obligatoire**: Chaque entité/relation DOIT avoir `evidence_spans`

**Prompt system**:
```
You are a STRICT extractor. Follow these rules:
1. Extract ONLY information explicitly stated in the text
2. NO world knowledge, NO inference, NO assumptions
3. Use ONLY allowed entity/relation types from schema
4. Provide evidence_spans (char positions) for ALL extractions
5. If uncertain, set confidence <0.7 (will trigger human review)
```

---

## 6. Gate Profiles & Formules

### 6.1 Critères Objectivés (Formules)

#### 6.1.1 `narrative_coherence`

**Définition**: Cohérence du candidat avec narrative threads du document

**Formule**:
```python
def compute_narrative_coherence(
    candidate: CandidateEntity,
    proto_context: ProtoContext
) -> float:
    if not proto_context.narrative_threads:
        return 0.5  # Neutral si pas de narrative

    # 1. Embedding candidat
    candidate_embedding = embed(candidate.name + " " + candidate.properties_text)

    # 2. Embeddings narrative threads
    thread_embeddings = [embed(thread.summary) for thread in proto_context.narrative_threads]

    # 3. Cosine similarity max avec threads
    similarities = [cosine_similarity(candidate_embedding, thread_emb) for thread_emb in thread_embeddings]
    max_similarity = max(similarities)

    # 4. Bonus si candidat dans segment narrative thread
    if candidate.segment_id in [seg.id for thread in proto_context.narrative_threads for seg in thread.segments]:
        max_similarity = min(1.0, max_similarity * 1.2)  # +20% bonus

    return max_similarity
```

**Plage**: [0.0, 1.0]

**Interprétation**:
- <0.4: Candidat hors narrative (suspect)
- 0.4-0.7: Cohérence partielle
- >0.7: Forte cohérence narrative

---

#### 6.1.2 `semantic_uniqueness`

**Définition**: Unicité sémantique du candidat (éviter duplicates)

**Formule**:
```python
def compute_semantic_uniqueness(
    candidate: CandidateEntity,
    proto_graph: ProtoGraph
) -> float:
    # 1. SimHash candidat
    candidate_simhash = simhash(candidate.name + " " + candidate.properties_text)

    # 2. Recherche entités similaires dans Proto-KG (même type)
    similar_entities = []
    for entity in proto_graph.entities:
        if entity.type == candidate.type:
            entity_simhash = simhash(entity.name + " " + entity.properties_text)
            distance = hamming_distance(candidate_simhash, entity_simhash)
            similarity = 1.0 - (distance / 64.0)  # SimHash 64 bits

            if similarity > 0.85:  # Seuil similarité
                similar_entities.append((entity, similarity))

    # 3. Unicité = inverse du max similarity
    if not similar_entities:
        return 1.0  # Totalement unique

    max_similarity = max([sim for _, sim in similar_entities])
    uniqueness = 1.0 - max_similarity

    # 4. Pénalité si >3 entités similaires (duplicate suspect)
    if len(similar_entities) > 3:
        uniqueness *= 0.8

    return max(0.0, uniqueness)
```

**Plage**: [0.0, 1.0]

**Interprétation**:
- <0.3: Probable duplicate (reject ou merge)
- 0.3-0.7: Similarité partielle (human review si composite score borderline)
- >0.7: Unique

---

#### 6.1.3 `causal_reasoning_quality`

**Définition**: Qualité du raisonnement causal (relations causales)

**Formule**:
```python
def compute_causal_reasoning_quality(
    candidate: CandidateEntity,
    proto_graph: ProtoGraph
) -> float:
    # 1. Compter relations causales sortantes
    causal_relation_types = ["SUPERSEDES", "MODIFIES", "CAUSED_BY", "ENABLES"]
    causal_relations_out = [
        rel for rel in proto_graph.relations
        if rel.source == candidate.name and rel.type in causal_relation_types
    ]

    # 2. Compter relations causales entrantes
    causal_relations_in = [
        rel for rel in proto_graph.relations
        if rel.target == candidate.name and rel.type in causal_relation_types
    ]

    # 3. Score = (causal_out + causal_in) / (total_relations + 1) normalisé
    total_relations = len([rel for rel in proto_graph.relations if candidate.name in [rel.source, rel.target]])
    causal_count = len(causal_relations_out) + len(causal_relations_in)

    if total_relations == 0:
        return 0.5  # Neutral si pas de relations

    causal_ratio = causal_count / (total_relations + 1)  # +1 évite div par 0

    # 4. Bonus si evidence causale explicite dans properties
    causal_keywords = ["because", "therefore", "as a result", "due to", "revised", "replaced"]
    evidence_text = " ".join([span.text for span in candidate.evidence_spans])
    if any(kw in evidence_text.lower() for kw in causal_keywords):
        causal_ratio = min(1.0, causal_ratio * 1.3)  # +30% bonus

    return min(1.0, causal_ratio * 2.0)  # Scale to [0, 1]
```

**Plage**: [0.0, 1.0]

**Interprétation**:
- <0.3: Faible raisonnement causal (entité isolée)
- 0.3-0.7: Raisonnement partiel
- >0.7: Fort raisonnement causal (entité centrale narrative)

---

#### 6.1.4 `contextual_richness`

**Définition**: Richesse contextuelle (properties, evidence spans)

**Formule**:
```python
def compute_contextual_richness(candidate: CandidateEntity) -> float:
    score = 0.0

    # 1. Properties richness (0-0.4 pts)
    if candidate.properties:
        prop_count = len(candidate.properties)
        score += min(0.4, prop_count * 0.1)  # Max 0.4 pour 4+ properties

    # 2. Evidence spans richness (0-0.4 pts)
    if candidate.evidence_spans:
        span_count = len(candidate.evidence_spans)
        avg_span_length = sum([span.end - span.start for span in candidate.evidence_spans]) / span_count

        # Bonus si spans longs (>50 chars) et multiples
        if span_count >= 2 and avg_span_length > 50:
            score += 0.4
        elif span_count >= 1:
            score += 0.2

    # 3. Source diversity (0-0.2 pts)
    if candidate.source_count > 1:
        score += min(0.2, candidate.source_count * 0.05)  # Max 0.2 pour 4+ sources

    return min(1.0, score)
```

**Plage**: [0.0, 1.0]

**Interprétation**:
- <0.3: Pauvre contexte (1 evidence span, 0-1 properties)
- 0.3-0.7: Contexte moyen
- >0.7: Contexte riche (multiples sources, properties détaillées)

---

### 6.2 Gate Profiles par Domaine/Langue (YAML)

#### Profile: Finance (English)

```yaml
gate_profile:
  name: "finance_en"
  domain: "finance"
  language: "en"

  weights:
    # Critères de base
    llm_confidence: 0.25
    source_count: 0.15
    type_validity: 0.10
    orphan_penalty: 0.10

    # Critères intelligence sémantique (OSMOSE)
    narrative_coherence: 0.15
    semantic_uniqueness: 0.10
    causal_reasoning_quality: 0.10
    contextual_richness: 0.05

  thresholds:
    auto_promote: 0.85      # ≥0.85 → AUTO_PROMOTE
    human_review: 0.70      # [0.70-0.85) → HUMAN_REVIEW (+ second opinion)
    reject: 0.70            # <0.70 → REJECT

  # Formule composite score
  # composite_score = (base_score * 0.6) + (intel_score * 0.4)
  # base_score = sum(weights[base_criteria] * values)
  # intel_score = sum(weights[intel_criteria] * values)

  tuning_policy:
    auto_tune_enabled: true
    tune_frequency_days: 7
    tune_based_on_kpis:
      - precision_at_promote
      - orphan_ratio
      - llm_call_efficiency
    tune_actions:
      - adjust_thresholds  # ±0.05 si KPI drift
      - adjust_weights     # ±0.05 si feature importance change
```

---

#### Profile: Pharma (English)

```yaml
gate_profile:
  name: "pharma_en"
  domain: "pharma"
  language: "en"

  weights:
    # Pharma = compliance critique → poids source_count + type_validity élevés
    llm_confidence: 0.20
    source_count: 0.20       # +5% vs finance
    type_validity: 0.15      # +5% vs finance
    orphan_penalty: 0.10

    narrative_coherence: 0.15
    semantic_uniqueness: 0.10
    causal_reasoning_quality: 0.05
    contextual_richness: 0.05

  thresholds:
    auto_promote: 0.80      # Moins strict que finance (volume élevé)
    human_review: 0.65
    reject: 0.65

  tuning_policy:
    auto_tune_enabled: true
    tune_frequency_days: 7
    tune_based_on_kpis:
      - precision_at_promote
      - orphan_ratio
```

---

#### Profile: General (Multi-langue)

```yaml
gate_profile:
  name: "general_multi"
  domain: "general"
  language: "multi"

  weights:
    llm_confidence: 0.30     # Poids élevé (pas de domaine spécialisé)
    source_count: 0.10
    type_validity: 0.10
    orphan_penalty: 0.10

    narrative_coherence: 0.15
    semantic_uniqueness: 0.15  # Important pour éviter duplicates en général
    causal_reasoning_quality: 0.05
    contextual_richness: 0.05

  thresholds:
    auto_promote: 0.75      # Plus permissif (domaine généraliste)
    human_review: 0.65
    reject: 0.65

  tuning_policy:
    auto_tune_enabled: true
    tune_frequency_days: 14  # Moins fréquent (moins de data)
```

---

### 6.3 Auto-Tuning Strategy

**Principe**: Ajustement hebdomadaire thresholds & weights basé sur KPIs réels

**Algorithm**:
```python
def auto_tune_gate_profile(
    profile: GateProfile,
    kpis_last_week: KPIs
) -> GateProfile:
    """
    Auto-tune gate profile basé sur KPIs de la semaine écoulée.

    Ajustements:
    1. Si Precision@Promote < 0.90 → augmenter auto_promote_threshold +0.02
    2. Si Orphan Ratio > 0.10 → diminuer orphan_penalty weight -0.02
    3. Si LLM Call Efficiency < 8.0 → diminuer human_review_threshold -0.02 (moins de reviews)
    """
    tuned = profile.copy()

    # Rule 1: Precision@Promote
    if kpis_last_week.precision_at_promote < 0.90:
        tuned.thresholds.auto_promote += 0.02
        log_tune("Increased auto_promote threshold", profile.name, +0.02)
    elif kpis_last_week.precision_at_promote > 0.95:
        tuned.thresholds.auto_promote -= 0.01  # Assouplir légèrement
        log_tune("Decreased auto_promote threshold", profile.name, -0.01)

    # Rule 2: Orphan Ratio
    if kpis_last_week.orphan_ratio > 0.10:
        tuned.weights.orphan_penalty -= 0.02
        log_tune("Decreased orphan_penalty weight", profile.name, -0.02)
    elif kpis_last_week.orphan_ratio < 0.05:
        tuned.weights.orphan_penalty += 0.01

    # Rule 3: LLM Call Efficiency
    if kpis_last_week.llm_call_efficiency < 8.0:
        # Trop de reviews → assouplir human_review threshold
        tuned.thresholds.human_review -= 0.02
        log_tune("Decreased human_review threshold", profile.name, -0.02)

    # Guardrails: thresholds ∈ [0.60, 0.95]
    tuned.thresholds.auto_promote = clamp(tuned.thresholds.auto_promote, 0.75, 0.95)
    tuned.thresholds.human_review = clamp(tuned.thresholds.human_review, 0.60, 0.85)

    return tuned
```

**Fréquence**: Hebdomadaire (dimanche 23h UTC)

**KPIs monitored**:
- `precision_at_promote` (target >0.90)
- `orphan_ratio` (target <0.08)
- `llm_call_efficiency` (target >10.0 promotions/appel)

**Alerting**: Si tuning change threshold >0.05, alerte admin pour validation manuelle

---

## 7. Budget Governor & Cost Model

### 7.1 Budget Governor Configuration (YAML)

```yaml
budget_governor:
  name: "osmose_budget_v1"

  # Caps durs par document
  caps_per_document:
    max_calls_small: 120        # gpt-4o-mini
    max_calls_big: 8            # gpt-4o
    max_calls_vision: 2         # gpt-4o-vision
    max_tokens_per_call_small: 4000
    max_tokens_per_call_big: 8000
    max_total_cost_usd: 1.50    # Abort si dépassé

  # Modèles et coûts (par 1k tokens)
  models:
    small:
      name: "gpt-4o-mini"
      cost_input_per_1k: 0.00015
      cost_output_per_1k: 0.0006
      typical_ratio_output: 0.3   # 30% output tokens vs input

    big:
      name: "gpt-4o"
      cost_input_per_1k: 0.0025
      cost_output_per_1k: 0.010
      typical_ratio_output: 0.3

    vision:
      name: "gpt-4o-vision"
      cost_input_per_1k: 0.0025
      cost_output_per_1k: 0.010
      typical_ratio_output: 0.2   # Vision output généralement plus court
      cost_per_image: 0.0085      # Coût fixe par image

  # Cache & dedup
  cache:
    enabled: true
    ttl_seconds: 86400            # 24h
    simhash_threshold: 0.90       # Cache hit si similarity >0.90
    cache_scope: "cross_doc"      # Cache partagé entre documents même tenant
    hit_rate_target: 0.60         # Target 60% hit rate

  # Dedup inter-docs (évite re-extraire segments identiques)
  dedup:
    enabled: true
    simhash_threshold: 0.95       # Dedup si similarity >0.95
    scope: "tenant"               # Dedup par tenant (pas cross-tenant)

  # Alerting
  alerts:
    cost_90_percent:
      threshold: 0.90             # Alert si coût doc >90% du cap
      action: "log_warning"

    cost_exceeded:
      threshold: 1.0              # Alert si cap dépassé
      action: "abort_and_escalate"

    vision_budget_low:
      threshold: 1                # Alert si ≤1 vision call restant
      action: "log_info"
```

---

### 7.2 Cost Model Chiffré

**Hypothèses**:
- **Document moyen**: 250 pages
- **Segments par page**: 4 (densité moyenne)
- **Tokens par segment**: 300 tokens (input)
- **Output tokens ratio**: 30% de l'input (90 tokens/segment)
- **Cache hit rate**: 20% (conservative, augmentera avec volume)

#### Scénario A: "Mostly SMALL" (stratégie coût-optimisée)

**Routing breakdown**:
- 70% NO_LLM (segments simples <3 entités)
- 25% LLM_SMALL (segments moyens 3-8 entités)
- 4% LLM_BIG (segments complexes >8 entités ou narrative)
- 1% VISION (charts)

**Calcul par document (250 pages)**:
```
Total segments = 250 pages × 4 segments/page = 1000 segments

NO_LLM segments = 1000 × 0.70 = 700 (coût = $0)

LLM_SMALL segments = 1000 × 0.25 = 250 segments
  - Batch size moyen = 4 segments/batch
  - Batches = 250 / 4 = 62.5 ≈ 63 batches
  - Tokens input/batch = 300 × 4 = 1200 tokens
  - Tokens output/batch = 1200 × 0.3 = 360 tokens
  - Cost/batch = (1.2k × $0.00015) + (0.36k × $0.0006) = $0.00018 + $0.000216 = $0.000396
  - Total cost SMALL = 63 × $0.000396 = $0.025

LLM_BIG segments = 1000 × 0.04 = 40 segments
  - Batch size moyen = 2 segments/batch
  - Batches = 40 / 2 = 20 batches
  - Tokens input/batch = 300 × 2 = 600 tokens
  - Tokens output/batch = 600 × 0.3 = 180 tokens
  - Cost/batch = (0.6k × $0.0025) + (0.18k × $0.010) = $0.0015 + $0.0018 = $0.0033
  - Total cost BIG = 20 × $0.0033 = $0.066

VISION segments = 1000 × 0.01 = 10 segments
  - Cost/vision = $0.0085/image + (1.5k tokens × $0.0025 input + 0.3k × $0.010 output)
  - Cost/vision = $0.0085 + $0.00375 + $0.003 = $0.01525
  - Total cost VISION = 10 × $0.01525 = $0.153

Cross-segment reasoning = 1 appel BIG/doc (Top-3 segments)
  - Tokens input = 300 × 3 = 900 tokens
  - Tokens output = 900 × 0.3 = 270 tokens
  - Cost cross-segment = (0.9k × $0.0025) + (0.27k × $0.010) = $0.00225 + $0.0027 = $0.00495

Gatekeeper second opinion = 10% candidates (conservatif)
  - Candidates promoted = 250 (LLM segments) + 40 (BIG) = 290
  - Second opinions = 290 × 0.10 = 29
  - Tokens/second opinion = 450 tokens input + 135 output
  - Cost/second opinion = (0.45k × $0.00015) + (0.135k × $0.0006) = $0.0000675 + $0.000081 = $0.0001485
  - Total second opinions = 29 × $0.0001485 = $0.0043

TOTAL COST Scénario A (avant cache):
= $0.025 (SMALL) + $0.066 (BIG) + $0.153 (VISION) + $0.00495 (cross) + $0.0043 (second)
= $0.253/doc

Avec cache hit 20%:
Cost adjusted = $0.253 × 0.80 = $0.202/doc

Par 1000 pages:
= ($0.202 / 250 pages) × 1000 = $0.81/1000 pages
```

**Coût Scénario A: ~$0.20/doc (250 pages) = $0.81/1000 pages**

---

#### Scénario B: "Mix BIG" (qualité maximale)

**Routing breakdown**:
- 50% NO_LLM
- 20% LLM_SMALL
- 28% LLM_BIG
- 2% VISION

**Calcul par document (250 pages)**:
```
Total segments = 1000

NO_LLM = 500 (coût = $0)

LLM_SMALL = 200 segments
  - Batches = 200 / 4 = 50
  - Cost/batch = $0.000396
  - Total SMALL = 50 × $0.000396 = $0.0198

LLM_BIG = 280 segments
  - Batches = 280 / 2 = 140 batches
  - Cost/batch = $0.0033
  - Total BIG = 140 × $0.0033 = $0.462

VISION = 20 segments
  - Cost/vision = $0.01525
  - Total VISION = 20 × $0.01525 = $0.305

Cross-segment = $0.00495

Second opinions = (200 + 280) × 0.10 = 48
  - Total second = 48 × $0.0001485 = $0.0071

TOTAL Scénario B (avant cache):
= $0.0198 + $0.462 + $0.305 + $0.00495 + $0.0071
= $0.799/doc

Avec cache hit 20%:
= $0.799 × 0.80 = $0.639/doc

Par 1000 pages:
= ($0.639 / 250) × 1000 = $2.56/1000 pages
```

**Coût Scénario B: ~$0.64/doc (250 pages) = $2.56/1000 pages**

---

### 7.3 Comparaison Scénarios

| Scénario | Stratégie | Coût/doc (250p) | Coût/1000p | Qualité attendue | Cas d'usage |
|----------|-----------|-----------------|------------|------------------|-------------|
| **A - Mostly SMALL** | Coût-optimisé | $0.20 | $0.81 | Precision 88-92% | Production volume (>1000 docs/jour) |
| **B - Mix BIG** | Qualité max | $0.64 | $2.56 | Precision 92-96% | Documents critiques (compliance, legal) |

**Recommandation**: Démarrer Scénario A, puis A/B test sur sample 100 docs pour valider trade-off coût/qualité.

---

### 7.4 Budget Enforcement (Code)

```python
class BudgetGovernor:
    def __init__(self, config: BudgetConfig):
        self.config = config
        self.redis = Redis()  # State persistence

    def check(self, doc_id: str, call_type: CallType) -> BudgetCheckResult:
        state = self._get_state(doc_id)

        # Check caps
        if call_type == CallType.SMALL and state.calls_small >= self.config.caps_per_document.max_calls_small:
            return BudgetCheckResult(allowed=False, reason="SMALL cap exceeded")

        if call_type == CallType.BIG and state.calls_big >= self.config.caps_per_document.max_calls_big:
            return BudgetCheckResult(allowed=False, reason="BIG cap exceeded")

        if call_type == CallType.VISION and state.calls_vision >= self.config.caps_per_document.max_calls_vision:
            return BudgetCheckResult(allowed=False, reason="VISION cap exceeded")

        # Check total cost cap
        if state.cost_usd >= self.config.caps_per_document.max_total_cost_usd:
            return BudgetCheckResult(allowed=False, reason="Total cost cap exceeded")

        return BudgetCheckResult(allowed=True)

    def consume(self, doc_id: str, call_type: CallType, tokens_input: int, tokens_output: int):
        state = self._get_state(doc_id)

        # Compute cost
        model_config = self.config.models[call_type.lower()]
        cost = (tokens_input / 1000.0) * model_config.cost_input_per_1k + \
               (tokens_output / 1000.0) * model_config.cost_output_per_1k

        if call_type == CallType.VISION:
            cost += model_config.cost_per_image

        # Update state
        if call_type == CallType.SMALL:
            state.calls_small += 1
        elif call_type == CallType.BIG:
            state.calls_big += 1
        elif call_type == CallType.VISION:
            state.calls_vision += 1

        state.tokens_used += (tokens_input + tokens_output)
        state.cost_usd += cost

        self._set_state(doc_id, state)

        # Alerting
        if state.cost_usd / self.config.caps_per_document.max_total_cost_usd > 0.9:
            self._emit_alert("cost_90_percent", doc_id, state)
```

---

## 8. KPIs & SLAs

### 8.1 KPIs Mesurables (Tableau)

| KPI | Définition | Target | Mesure | Alerte Si |
|-----|------------|--------|--------|-----------|
| **cost_per_promoted_relation** | Coût LLM / relations promues | <$0.05 | Total cost / promoted relations | >$0.08 |
| **llm_call_efficiency** | Relations promues / appel LLM | >10.0 | Promoted relations / total LLM calls | <8.0 |
| **precision_at_promote** | Précision auto-promotions | >90% | Valid promotions / auto-promotions | <85% |
| **orphan_ratio** | % entités orphelines Proto-KG | <8% | Orphan entities / total entities | >12% |
| **connectivity_gain** | Gain connectivité post cross-segment | >0.25 | (Relations après - avant) / Relations avant | <0.15 |
| **cache_hit_rate** | % appels servis par cache | >60% | Cache hits / total calls | <40% |
| **second_opinion_downgrade_rate** | % downgrades après second avis | <15% | Downgrades / second opinions | >25% |
| **related_to_percent** | % RELATED_TO sur total relations | <5% | RELATED_TO count / total relations | >7% |
| **processing_latency_p95** | Latence traitement doc (p95) | <180s | Percentile 95 latencies | >300s |
| **budget_utilization_rate** | % budget utilisé vs cap | 60-80% | Cost actual / cost cap | <40% ou >90% |

---

### 8.2 Formules KPIs

#### 8.2.1 `cost_per_promoted_relation`

```python
def compute_cost_per_promoted_relation(metrics: Metrics) -> float:
    """
    Coût moyen par relation promue vers Published-KG.

    Target: <$0.05/relation
    """
    if metrics.promoted_relations_count == 0:
        return 0.0

    return metrics.total_llm_cost_usd / metrics.promoted_relations_count
```

**Alerte**: Si >$0.08, routing policy trop aggressive (trop de BIG calls)

---

#### 8.2.2 `llm_call_efficiency`

```python
def compute_llm_call_efficiency(metrics: Metrics) -> float:
    """
    Nombre de relations promues par appel LLM (toutes routes confondues).

    Target: >10.0 relations/appel
    Benchmark: 8-12 typical, >15 excellent
    """
    if metrics.total_llm_calls == 0:
        return 0.0

    return metrics.promoted_relations_count / metrics.total_llm_calls
```

**Alerte**: Si <8.0, gatekeeper trop strict ou extraction peu productive

---

#### 8.2.3 `precision_at_promote`

```python
def compute_precision_at_promote(validation_sample: List[ValidationCase]) -> float:
    """
    Précision des auto-promotions (validation humaine sur sample).

    Target: >90%
    Méthode: Sample 100 auto-promotions/semaine, validation humaine
    """
    if not validation_sample:
        return 0.0

    valid_promotions = sum([1 for case in validation_sample if case.human_validated])
    return valid_promotions / len(validation_sample)
```

**Alerte**: Si <85%, gate profile trop permissif (augmenter auto_promote_threshold)

---

#### 8.2.4 `orphan_ratio`

```python
def compute_orphan_ratio(proto_graph: ProtoGraph) -> float:
    """
    Pourcentage d'entités orphelines (0 relations) dans Proto-KG.

    Target: <8%
    """
    if not proto_graph.entities:
        return 0.0

    orphans = [e for e in proto_graph.entities if e.relations_count == 0]
    return len(orphans) / len(proto_graph.entities)
```

**Alerte**: Si >12%, extraction manque liens ou cross-segment insuffisant

---

#### 8.2.5 `connectivity_gain`

```python
def compute_connectivity_gain(before: ProtoGraph, after: ProtoGraph) -> float:
    """
    Gain de connectivité après cross-segment reasoning.

    Target: >0.25 (25% augmentation relations)
    """
    if before.relations_count == 0:
        return 0.0

    gain = (after.relations_count - before.relations_count) / before.relations_count
    return gain
```

**Alerte**: Si <0.15, cross-segment peu efficace (revoir éligibilité Top-K)

---

#### 8.2.6 `cache_hit_rate`

```python
def compute_cache_hit_rate(metrics: Metrics) -> float:
    """
    Taux de succès cache sémantique.

    Target: >60% (augmente avec volume docs)
    """
    total_cache_checks = metrics.cache_hits + metrics.cache_misses
    if total_cache_checks == 0:
        return 0.0

    return metrics.cache_hits / total_cache_checks
```

**Alerte**: Si <40%, cache mal configuré ou docs trop hétérogènes

---

#### 8.2.7 `related_to_percent`

```python
def compute_related_to_percent(proto_graph: ProtoGraph) -> float:
    """
    Pourcentage relations RELATED_TO sur total (cap 5% strict).

    Target: <5%
    """
    if not proto_graph.relations:
        return 0.0

    related_to_count = len([r for r in proto_graph.relations if r.type == "RELATED_TO"])
    return (related_to_count / len(proto_graph.relations)) * 100.0
```

**Alerte CRITIQUE**: Si >7%, abort pipeline (risque explosion RELATED_TO)

---

### 8.3 SLAs & Seuils d'Alerting

| Métrique | SLA P95 | Alerte Warning | Alerte Critical | Action Auto |
|----------|---------|----------------|-----------------|-------------|
| **Processing latency** | <180s | >240s | >300s | Abort doc si >300s |
| **Cost/doc** | <$0.30 (Scenario A) | >$0.40 | >$0.60 | Abort doc si >cap $1.50 |
| **LLM call efficiency** | >10.0 | <8.0 | <6.0 | Re-tune gate profile |
| **Orphan ratio** | <8% | >12% | >20% | Escalate human review |
| **Cache hit rate** | >60% | <40% | <25% | Review cache config |
| **RELATED_TO percent** | <5% | >7% | >10% | **ABORT PIPELINE** |

---

### 8.4 Dashboard Metrics (temps-réel)

**Métriques à exposer (Prometheus/Grafana)**:

```python
# Counter metrics
extraction_calls_total{route="SMALL|BIG|VISION", status="success|error"}
promotion_decisions_total{action="AUTO_PROMOTE|HUMAN_REVIEW|REJECT"}
cache_hits_total
cache_misses_total

# Histogram metrics
extraction_latency_seconds{route="SMALL|BIG|VISION"}
document_processing_duration_seconds
gate_evaluation_latency_seconds

# Gauge metrics
proto_kg_entities_count{tenant_id="X"}
proto_kg_relations_count{tenant_id="X"}
budget_cost_usd_current{doc_id="X"}
orphan_ratio_percent{tenant_id="X"}
```

**Alerting Rules** (Prometheus):
```yaml
groups:
  - name: osmose_kpis
    rules:
      - alert: HighOrphanRatio
        expr: orphan_ratio_percent > 12
        for: 5m
        annotations:
          summary: "Orphan ratio >12% for tenant {{ $labels.tenant_id }}"

      - alert: RelatedToCapExceeded
        expr: related_to_percent > 7
        for: 1m
        annotations:
          summary: "CRITICAL: RELATED_TO >7% - ABORT PIPELINE"
          severity: critical

      - alert: LowLLMCallEfficiency
        expr: llm_call_efficiency < 8.0
        for: 10m
        annotations:
          summary: "LLM call efficiency <8.0 - re-tune gate profile"
```

---

## 9. Redlines Documentation Existante

### 9.1 Fichier: `OSMOSE_ARCHITECTURE_TECHNIQUE.md`

**Before** (généralités à corriger):

> **Ligne 145**: "Le SemanticIntelligentGatekeeper évalue la qualité des candidats avec des critères adaptatifs."

**After** (formule objectivée):

> **Ligne 145**: "Le SemanticIntelligentGatekeeper évalue chaque candidat via composite score: `(base_score * 0.6) + (intel_score * 0.4)`, où `intel_score` inclut `narrative_coherence` (cosine similarity embeddings clusters, seuil >0.7), `semantic_uniqueness` (SimHash distance >0.85), `causal_reasoning_quality` (ratio relations causales, bonus keywords), et `contextual_richness` (properties count + evidence spans length). Seuils promotion: ≥0.85 AUTO_PROMOTE, [0.70-0.85) HUMAN_REVIEW + second opinion LLM, <0.70 REJECT. Gate profiles par domaine (finance: auto_promote=0.85, pharma: 0.80, general: 0.75) avec auto-tuning hebdomadaire basé sur KPIs (precision@promote >0.90, orphan_ratio <0.08)."

---

**Before** (pas de budget précis):

> **Ligne 230**: "Le BudgetManager optimise les coûts LLM."

**After** (caps chiffrés):

> **Ligne 230**: "Le BudgetManager impose caps durs par document: max 120 calls SMALL (gpt-4o-mini, $0.002/1k tokens), 8 calls BIG (gpt-4o, $0.010/1k tokens), 2 calls VISION (gpt-4o-vision, $0.015/1k tokens + $0.0085/image), avec abort si coût total >$1.50/doc. Cache sémantique SimHash (threshold 0.90, TTL 24h, target hit-rate 60%) et dedup inter-docs (threshold 0.95, scope tenant). Cost model estimé: Scénario A (mostly SMALL) = $0.20/doc (250 pages) soit $0.81/1000 pages, Scénario B (mix BIG) = $0.64/doc soit $2.56/1000 pages."

---

**Before** (evidence spans flou):

> **Ligne 180**: "Chaque entité extraite doit avoir des evidence spans."

**After** (obligatoire + validation):

> **Ligne 180**: "OBLIGATOIRE: Chaque entité/relation extraite DOIT inclure `evidence_spans` array avec `{start: int, end: int, text: string}` pointant vers char positions exactes dans segment source. Validation stricte reject si `evidence_spans` vide ou invalid (start<0, end<=start). Prompts LLM incluent instruction explicite: 'For each entity/relation, provide evidence_spans with exact char positions. NO extraction without evidence.'"

---

### 9.2 Fichier: `OSMOSE_REFACTORING_PLAN.md`

**Before**:

> **Ligne 92**: "Le pipeline PDF sera modifié pour intégrer la semantic intelligence."

**After** (FSM agentique):

> **Ligne 92**: "Le pipeline PDF sera refactoré en architecture agentique avec Supervisor FSM (10 états: INIT→ROUTE→EXTRACT_BATCH→CROSS_SEGMENT→NORMALIZE→WRITE_PROTO→GATE_EVAL→PROMOTE→FINALIZE→END, timeout global 300s/doc, per-state 30s sauf EXTRACT_BATCH 60s, max_steps=50). Agents: (1) Supervisor (orchestration), (2) Extractor Orchestrator (routing NO_LLM/<3 entités | LLM_SMALL/3-8 | LLM_BIG/>8 ou narrative, batch 2-6 segments), (3) Pattern Miner (cross-segment Top-K≤3 éligibles si score≥0.5, cap RELATED_TO<5%), (4) Gatekeeper Delegate (gate profiles domaine, formules objectives), (5) Budget Manager (caps durs enforcement). Tools avec JSON I/O schemas stricts (15 tools définis: route_segments, llm_extract_batch, llm_second_opinion, vision_extract, json_validate, normalize_and_link, write_protokg, promote_via_gate, mine_relaters, compact_rotate, budget_check/consume/refund, cache_get/put, simhash_match, emit_metrics)."

---

**Before** (Neo4j/Qdrant flou):

> **Ligne 120**: "Facts seront stockés dans Neo4j Proto-KG et Published-KG."

**After** (SSoT explicite):

> **Ligne 120**: "SSoT (Single Source of Truth) = Neo4j pour facts (entities, relations, properties, evidence_spans refs). Neo4j Proto-KG: labels `CandidateEntity`/`CandidateRelation` avec `status` ∈ {PENDING_REVIEW, AUTO_PROMOTED, HUMAN_PROMOTED, REJECTED}, constraints UNIQUE sur `candidate_id`, indexes sur `tenant_id` et `status`. Published-KG: labels `Entity`/`Relation` après promotion via Gatekeeper. Qdrant = vecteurs (embeddings 1536-dim OpenAI text-embedding-3-small) + metadata payload incluant `neo4j_id` pointeur vers Neo4j fact, `candidate_id`, `status`, `semantic_metadata` (narrative_thread_id, complexity_zone, causal_links). Qdrant collection `knowwhere_proto` avec distance Cosine, TTL hot_ttl=7d, warm_ttl=30d, cold_ttl=90d (lifecycle management via `compact_rotate` tool)."

---

### 9.3 Fichier: `OSMOSE_AMBITION_PRODUIT_ROADMAP.md`

**Before** (coûts vagues):

> **Ligne 450**: "Phase 2 nécessitera optimisation des coûts LLM."

**After** (budget governor intégré):

> **Ligne 450**: "Phase 2 intègre Budget Governor avec caps durs par document (120 SMALL, 8 BIG, 2 VISION calls max) et cost model chiffré. Scénario A 'mostly SMALL' (70% NO_LLM, 25% SMALL, 4% BIG, 1% VISION) vise $0.20/doc (250 pages) soit $0.81/1000 pages avec cache hit-rate 20% initial (target 60% à maturité). Scénario B 'mix BIG' (50% NO_LLM, 20% SMALL, 28% BIG, 2% VISION) = $0.64/doc soit $2.56/1000 pages, réservé documents critiques (compliance, legal). Plan pilote Phase 2 inclut A/B test 100 docs pour valider trade-off coût/qualité (target: Precision@Promote >90%, Cost/promoted <$0.05)."

---

**Before** (KPIs génériques):

> **Ligne 680**: "Métriques de succès incluront précision et performance."

**After** (KPIs chiffrés):

> **Ligne 680**: "KPIs mesurables avec seuils targets: (1) cost_per_promoted_relation <$0.05 (alerte >$0.08), (2) llm_call_efficiency >10.0 promotions/appel (alerte <8.0), (3) precision_at_promote >90% validation humaine sample hebdo (alerte <85%), (4) orphan_ratio <8% Proto-KG (alerte >12%), (5) connectivity_gain >0.25 post cross-segment (alerte <0.15), (6) cache_hit_rate >60% (alerte <40%), (7) second_opinion_downgrade_rate <15% (alerte >25%), (8) related_to_percent <5% STRICT (alerte CRITICAL >7% = ABORT), (9) processing_latency_p95 <180s (alerte >300s), (10) budget_utilization_rate 60-80% (alerte <40% ou >90%). Dashboard Prometheus/Grafana temps-réel avec alerting rules."

---

### 9.4 Fichier: `OSMOSE_FRONTEND_MIGRATION_STRATEGY.md`

**Before**:

> **Ligne 200**: "Dashboard Budget Intelligence affichera coûts LLM."

**After** (métriques détaillées):

> **Ligne 200**: "Dashboard Budget Intelligence (Phase 3 Sem 22-26, 6 jours dev) affichera métriques temps-réel: (1) Cost breakdown par route (SMALL/BIG/VISION) avec charts recharts area, (2) Budget utilization gauge (actuel vs cap $1.50/doc), (3) Cache hit-rate trend line (target >60%), (4) Cost/promoted_relation histogram avec threshold $0.05, (5) LLM call efficiency bar chart (promotions/appel, target >10.0), (6) Alerts panel (budget >90%, RELATED_TO >7% critical). Données via WebSocket real-time depuis Budget Manager agent (emit_metrics tool → Redis pubsub → frontend). API endpoint GET `/api/budget/metrics/{tenant_id}` retournant JSON avec tous KPIs."

---

## 10. Plan Pilote

### 10.1 Objectif Pilote

**Durée**: 3 semaines (21 jours calendaires)

**Objectif**: Valider architecture agentique sur échantillon représentatif avant rollout Phase 2 complet

**Scope**:
- 100 documents test (50 finance, 30 pharma, 20 general)
- A/B test: Groupe A (Scénario "mostly SMALL") vs Groupe B (Scénario "mix BIG")
- Mesurer KPIs clés pour décision GO/NO-GO

---

### 10.2 Jeu d'Essai (100 Documents)

**Composition**:

| Domaine | Count | Caractéristiques | Pages Moy | Objectif Test |
|---------|-------|------------------|-----------|---------------|
| **Finance** | 50 | Rapports financiers, métriques CRR, compliance | 150-300 | Narrative threads, temporal sequences |
| **Pharma** | 30 | Protocoles cliniques, regulatory docs, audits | 200-400 | Compliance stricte, causal reasoning |
| **General** | 20 | Docs hétérogènes, knowledge management, consulting | 100-250 | Cross-segment, ontology patterns |

**Critères Sélection**:
- Présence narrative threads (≥30% docs doivent avoir threads détectables)
- Variété complexité (33% simple <0.4, 33% moyen 0.4-0.7, 33% complexe >0.7)
- Ground truth disponible (validation humaine entities/relations sur sample 20 docs)

---

### 10.3 Protocole A/B Test

#### Groupe A: Scénario "Mostly SMALL" (50 docs)

**Configuration**:
```yaml
routing_policy:
  no_llm_threshold: 3        # <3 entités → NO_LLM
  llm_small_threshold: 8     # 3-8 entités → LLM_SMALL
  complexity_threshold: 0.6  # >0.6 → LLM_BIG même si <8 entités

budget_caps:
  max_calls_small: 120
  max_calls_big: 8
  max_calls_vision: 2

gate_profile: "finance_en"  # auto_promote=0.85
```

**Expected outcomes**:
- Cost/doc: $0.18 - $0.25
- Precision@Promote: 88-92%
- LLM call efficiency: 10-12

---

#### Groupe B: Scénario "Mix BIG" (50 docs)

**Configuration**:
```yaml
routing_policy:
  no_llm_threshold: 3
  llm_small_threshold: 6     # Seuil SMALL abaissé (plus de BIG)
  complexity_threshold: 0.5  # Seuil complexity abaissé

budget_caps:
  max_calls_small: 80        # Réduit (favorise BIG)
  max_calls_big: 20          # Augmenté
  max_calls_vision: 2

gate_profile: "finance_en"  # Même profile
```

**Expected outcomes**:
- Cost/doc: $0.55 - $0.75
- Precision@Promote: 92-96%
- LLM call efficiency: 8-10 (moins efficace mais plus précis)

---

### 10.4 Métriques d'Arrêt/GO

**Métriques Primaires (GO/NO-GO)**:

| Métrique | Target | Seuil GO | Seuil NO-GO | Mesure |
|----------|--------|----------|-------------|--------|
| **Precision@Promote** | >90% | ≥88% | <85% | Validation humaine sample 20 docs |
| **Cost/promoted_relation** | <$0.05 | ≤$0.06 | >$0.08 | Total cost / promoted count |
| **Orphan Ratio** | <8% | ≤10% | >15% | Orphan entities / total |
| **Processing Latency P95** | <180s | ≤240s | >300s | Percentile 95 latencies |

**Métriques Secondaires (Optimisation)**:

| Métrique | Target | Observation |
|----------|--------|-------------|
| LLM Call Efficiency | >10.0 | Optimiser batch size si <8.0 |
| Cache Hit Rate | >60% | Ajuster SimHash threshold si <40% |
| RELATED_TO Percent | <5% | ABORT si >7% (critique) |
| Connectivity Gain | >0.25 | Revoir cross-segment si <0.15 |

---

### 10.5 Timeline Pilote (3 Semaines)

#### Semaine 1 (Jours 1-7): Setup & Baseline

**Objectif**: Infrastructure prête, baseline mesurée

**Tasks**:
- Jour 1-2: Setup agents (Supervisor, Extractor Orchestrator, Budget Manager)
- Jour 3-4: Configuration gate profiles, budget governor, routing policies
- Jour 4-5: Tests unitaires tools (15 tools JSON I/O validation)
- Jour 6-7: Baseline run sur 10 docs sans agentique (legacy pipeline)

**Deliverable**: Baseline metrics legacy (cost, latency, precision)

---

#### Semaine 2 (Jours 8-14): Exécution A/B Test

**Objectif**: Traiter 100 docs (50 Groupe A, 50 Groupe B)

**Tasks**:
- Jour 8-10: Groupe A (25 docs/jour, monitoring continu)
- Jour 11-13: Groupe B (25 docs/jour, monitoring continu)
- Jour 14: Analyse intermédiaire, ajustements si needed

**Monitoring Real-Time**:
- Dashboard Grafana avec métriques live (cost, latency, orphan ratio)
- Alerting si RELATED_TO >7% (ABORT doc), budget >90% cap
- Logs structurés JSON pour replay si needed

---

#### Semaine 3 (Jours 15-21): Analyse & Décision

**Objectif**: Validation humaine, analyse KPIs, décision GO/NO-GO

**Tasks**:
- Jour 15-17: Validation humaine sample 20 docs (Precision@Promote)
- Jour 18-19: Analyse comparative A vs B (coût, qualité, trade-offs)
- Jour 20: Rapport pilote avec recommandation
- Jour 21: Décision GO/NO-GO Phase 2

**Deliverable**: Rapport pilote (10 pages) avec:
- Tableau KPIs A vs B
- Recommandation scénario production
- Roadmap ajustements (gate profiles, routing thresholds)
- Estimation coût production (1000 docs/jour)

---

### 10.6 Risques & Mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| **RELATED_TO explosion** | Medium | Critical | Cap strict 5%, ABORT si >7%, review cross-segment prompts |
| **Cache hit-rate <20%** | Medium | Medium | Docs pilote diversifiés, ajuster SimHash threshold 0.90→0.85 |
| **Latency >300s (timeout)** | Low | High | Profiling bottlenecks, optimiser batch size, augmenter timeout EXTRACT_BATCH 60s→90s |
| **Precision <85%** | Low | Critical | Iteration gate profiles, augmenter auto_promote threshold +0.05 |
| **Budget explosion Groupe B** | Medium | Medium | Cap enforcement strict, alerting >90% budget, pas de production si cost/promoted >$0.08 |
| **Orphan ratio >15%** | Medium | High | Review extraction prompts (no-inference rule), augmenter cross-segment K=3→5 test |

---

### 10.7 Décision GO/NO-GO Finale

**Critères GO Phase 2**:
1. ✅ Precision@Promote ≥88% (Groupe A ou B)
2. ✅ Cost/promoted ≤$0.06 (Groupe A ou B)
3. ✅ Orphan Ratio ≤10%
4. ✅ Latency P95 ≤240s
5. ✅ Aucun ABORT RELATED_TO >7% sur 100 docs

**Si tous critères GO**:
- Démarrer Phase 2 Sem 11-18 (OSMOSE roadmap)
- Scénario production = celui avec meilleur trade-off coût/qualité validé pilote
- Rollout progressif: 10% traffic → 50% → 100% sur 3 semaines

**Si 1+ critère NO-GO**:
- ITERATE pilote +2 semaines avec ajustements
- Review architecture agentique (FSM, tools, policies)
- Re-test 50 docs avant décision finale

**Si 2+ critères NO-GO critiques**:
- PAUSE architecture agentique
- Retour monolithique optimisé (Phase 1 actuelle)
- Re-évaluation approche dans 3 mois

---

## Annexes

### Annexe A: YAML Config Complet Budget Governor

```yaml
# config/osmose_budget_governor.yaml

budget_governor:
  version: "1.0"
  enabled: true

  caps_per_document:
    max_calls_small: 120
    max_calls_big: 8
    max_calls_vision: 2
    max_tokens_per_call_small: 4000
    max_tokens_per_call_big: 8000
    max_total_cost_usd: 1.50

  models:
    small:
      name: "gpt-4o-mini"
      cost_input_per_1k: 0.00015
      cost_output_per_1k: 0.0006
      typical_ratio_output: 0.3

    big:
      name: "gpt-4o"
      cost_input_per_1k: 0.0025
      cost_output_per_1k: 0.010
      typical_ratio_output: 0.3

    vision:
      name: "gpt-4o-vision"
      cost_input_per_1k: 0.0025
      cost_output_per_1k: 0.010
      typical_ratio_output: 0.2
      cost_per_image: 0.0085

  cache:
    enabled: true
    ttl_seconds: 86400
    simhash_threshold: 0.90
    cache_scope: "cross_doc"
    hit_rate_target: 0.60

  dedup:
    enabled: true
    simhash_threshold: 0.95
    scope: "tenant"

  alerts:
    cost_90_percent:
      threshold: 0.90
      action: "log_warning"

    cost_exceeded:
      threshold: 1.0
      action: "abort_and_escalate"

    vision_budget_low:
      threshold: 1
      action: "log_info"
```

---

### Annexe B: JSON Schema Tool `llm_extract_batch`

```json
{
  "tool_name": "llm_extract_batch",
  "input_schema": {
    "type": "object",
    "properties": {
      "batch_id": {"type": "string"},
      "model": {"type": "string", "enum": ["gpt-4o-mini", "gpt-4o"]},
      "segments": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "segment_id": {"type": "string"},
            "text": {"type": "string", "minLength": 10}
          },
          "required": ["segment_id", "text"]
        },
        "minItems": 1,
        "maxItems": 6
      },
      "prompt_template": {"type": "string"},
      "domain": {"type": "string", "enum": ["finance", "pharma", "consulting", "general"]},
      "output_schema": {"type": "object"},
      "max_tokens": {"type": "integer", "minimum": 500, "maximum": 8000}
    },
    "required": ["batch_id", "model", "segments", "prompt_template", "domain", "output_schema"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "batch_id": {"type": "string"},
      "success": {"type": "boolean"},
      "results": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "segment_id": {"type": "string"},
            "entities": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "name": {"type": "string"},
                  "type": {"type": "string"},
                  "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                  "evidence_spans": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 1},
                        "text": {"type": "string"}
                      },
                      "required": ["start", "end", "text"]
                    },
                    "minItems": 1
                  },
                  "properties": {"type": "object"}
                },
                "required": ["name", "type", "confidence", "evidence_spans"]
              }
            },
            "relations": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "source": {"type": "string"},
                  "target": {"type": "string"},
                  "type": {"type": "string"},
                  "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                  "evidence_spans": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "start": {"type": "integer"},
                        "end": {"type": "integer"},
                        "text": {"type": "string"}
                      },
                      "required": ["start", "end", "text"]
                    },
                    "minItems": 1
                  }
                },
                "required": ["source", "target", "type", "confidence", "evidence_spans"]
              }
            }
          },
          "required": ["segment_id", "entities", "relations"]
        }
      },
      "tokens_used": {"type": "integer"},
      "cost_usd": {"type": "number"},
      "latency_ms": {"type": "integer"},
      "model_used": {"type": "string"}
    },
    "required": ["batch_id", "success", "results", "tokens_used", "cost_usd"]
  },
  "errors": [
    {"code": "LLM_TIMEOUT", "message": "LLM call exceeded 30s timeout"},
    {"code": "LLM_INVALID_RESPONSE", "message": "Response does not match output_schema"},
    {"code": "LLM_RATE_LIMIT", "message": "API rate limit exceeded"},
    {"code": "BUDGET_EXCEEDED", "message": "Budget check failed before call"}
  ],
  "idempotence": false,
  "notes": "Cache via cache_get() before calling. evidence_spans MANDATORY for all entities/relations."
}
```

---

### Annexe C: Pseudo-code FSM Supervisor (Complet)

Voir Section 3.3 pour pseudo-code complet (déjà inclus).

---

### Annexe D: Calculs Cost Model Détaillés

Voir Section 7.2 pour calculs chiffrés Scénario A et B (déjà inclus).

---

## Conclusion

Cette étude propose une **architecture agentique pragmatique et ready-to-implement** pour OSMOSE, avec:

✅ **5 agents spécialisés** (Supervisor, Extractor Orchestrator, Pattern Miner, Gatekeeper Delegate, Budget Manager)

✅ **FSM strict** (10 états, timeouts, max_steps, no free-form)

✅ **15 tools avec JSON schemas précis** (I/O, erreurs, idempotence)

✅ **Politiques de routing quantifiées** (seuils NO_LLM <3 / SMALL 3-8 / BIG >8, batch 2-6, enums fermées)

✅ **Gate profiles objectivés** (formules narrative_coherence cosine, semantic_uniqueness SimHash, causal_reasoning ratio, contextual_richness count)

✅ **Budget Governor chiffré** (caps 120 SMALL, 8 BIG, 2 VISION, cost model $0.20/doc Scenario A, $0.64/doc Scenario B)

✅ **KPIs mesurables** (10 KPIs avec seuils targets et alerting rules)

✅ **Redlines précises** sur docs existants (SSOT Neo4j, evidence spans obligatoires, caps RELATED_TO <5%)

✅ **Plan pilote 3 semaines** (100 docs, A/B test, métriques GO/NO-GO, risques/mitigations)

**Recommandation**: **GO Pilote** pour valider approche avant Phase 2 OSMOSE complète.

---

**Version:** 1.0
**Date:** 2025-10-13
**Statut:** 🟡 DRAFT - En attente validation
**Prochaine Étape:** Décision GO/NO-GO Pilote

---

> **🤖 "Architecture agentique: quand l'orchestration intelligente rencontre la rigueur budgétaire."**
