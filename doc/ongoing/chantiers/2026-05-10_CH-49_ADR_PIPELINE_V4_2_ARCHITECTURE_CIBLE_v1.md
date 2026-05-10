# ADR CH-49 v1.0 — Architecture cible OSMOSIS V4.2 (Tiered Pipeline)

**Date** : 2026-05-10
**Statut** : 🟢 v1.1 — LOCKED post 2e round LLM critiques (ChatGPT-5 + Claude Web Opus, validation 9/10)
**Version précédente** : `2026-05-09_CH-49_ADR_PIPELINE_V4_1_CORRECTIONS.md` (v0.7, 32 décisions atomiques — déprécié)
**Amendments v1.0 → v1.1** : 5 points centraux + 4 ajouts Claude Web (cf §6)
**Inputs critiques** :
- 3 LLMs critiques (ChatGPT-5 ×2 + Claude Web Opus) — convergence "5 capabilities + reasoning escalation"
- État de l'art 2026 : CRAG, A2RAG, Self-RAG, Adaptive RAG, agentic RAG (cf §A.5 Sources)
- POC empirique CH-49.POC (Phase 1.A/B/C) — Layer 0 + 1 operator validés sur 30q stratifiés

---

## §0 — Principe architectural central

### **"Reasoning is an escalation, not a default."**

Toutes les questions ne doivent pas passer par le même pipeline lourd. Le système doit **escalader dynamiquement** selon le besoin réel de raisonnement détecté par signal.

| Layer | % attendu | Pour quoi |
|---|---:|---|
| **Layer 0 — Cheap Certainty** | **60-70%** | Factual simple, list simple, abstain qualifié |
| **Layer 1 — Structured Operators** | **20-30%** | Temporal active, set/negation, comparison, KG query |
| **Layer 2 — Adaptive Orchestrator** | **5-10%** | Multi-hop profond, causal complexe, audit, hypothétique multi-étape |

**Validation empirique POC** :
- Layer 0 sur factual → **+0.383pp** vs V4.1 (Robust subset 5q)
- Layer 1 (1 operator) sur temporal → **+0.100pp** + 100% de précision quand déclenché
- Sans Layer 2 → **causal -0.200pp, multi_hop -0.240pp** → Layer 2 **obligatoire** pour ces types

---

## §1 — Les 5 Capabilities runtime (architecture cible)

### Cap1 — **Cheap Certainty Layer** (Layer 0)
**Validé empiriquement POC (factual +0.383pp).**

**Composants** :
- Hybrid retrieval (RRF BM25 + dense + cross-encoder rerank) — reuse V4.1 existant
- Direct fact extraction (Llama-3.3-70B-Turbo Together AI, prompt minimal)
- **Q↔A Alignment Verifier** (DeepSeek-V3.1, famille distincte → anti-biais auto-juge)
- Quick abstain qualifié si Q↔A misalignment OU pas d'evidence

**Latence cible** : 5-10s (mesuré POC : 7.1s mean)

**Impact transverse** :
- Couvre Pattern A (list 40% — items hors-cible) via Q↔A Verifier
- Couvre Pattern F (factual 20% — extraction brute) via Q↔A Verifier
- Couvre Pattern O (unanswerable 40% — off-topic) via Q↔A Verifier

---

### Cap2 — **Structured Reasoning Operators** (Layer 1)
**Validé empiriquement POC (temporal_active_op : 100% précision quand déclenché, 6/30 escalations sur bench v2).**

### **Charte Cap2 (amendment v1.1)** ⭐⭐⭐
> **Le LLM ne doit JAMAIS être l'operator lui-même.**
> Il est uniquement :
> - **Aiguilleur** : intent detection (LLM léger DeepSeek)
> - **Rédacteur** : formatage final de la réponse
>
> Le raisonnement structurel (filtrage temporal, set ops, traversée KG, comparaison) est en **code Python déterministe** + Cypher.

**Operators planifiés** :

#### Cap2.A — `temporal_active_version_op` ✅ **POC implémenté**
Pour "version active à date X" / "applicable au [date]" / "currently in force"
- Cypher Neo4j → versions du sujet + publication_date
- Raisonnement déterministe Python : `effective_date ≤ query_date < successor.effective_date`
- Fallback Qdrant si keywords sémantiques pas dans subjects KG
- Fallback list_all_active si keywords trop génériques
- Latence 2-4s warm

#### Cap2.B — `lifecycle_resolution_op` (à implémenter)
Pour "qui a remplacé X" / "X SUPERSEDES Y" / "successeur de X"
- **Primary** : Cypher Neo4j sur LIFECYCLE_RELATION (type=SUPERSEDES, EVOLVES_FROM, REAFFIRMS)
- **Fallback 1** : si target/source non trouvé → Qdrant resolver pour identifier doc_id puis re-query
- **Fallback 2** : si plusieurs candidats → présenter tous avec evidence_quote
- **Ultimate fallback** : Escalate Layer 2 avec contexte complet
- Output : "Z a remplacé X (relation :SUPERSEDES, evidence_quote: ...)"

#### Cap2.C — `kg_query_op` (à implémenter)
Pour questions structurelles KG : "chaîne SUPERSEDES", "documents DEPRECATED", "comptage relations"
- **Primary** : Cypher templates par type de structure attendue (CHAIN, COUNT, LIST_BY_STATUS)
- **Fallback 1** : si template inconnu → décomposer la requête en sous-questions et tools chain
- **Ultimate fallback** : Escalate Layer 2
- Output : liste/comptage avec citations

#### Cap2.D — `set_reasoning_op` (à implémenter, généralisation de "negation_path")
Pour "qu'est-ce qui n'est PAS X" / "exemptions" / "exclusions"
- **Primary** : Cypher exclusions explicites (chunks "exempted from", "ne s'applique pas", "sauf", "excluding")
- **Fallback 1** : si pas d'exclusions explicites → retrieve all items + LLM filter (sémantique exclusion)
- **Fallback 2** : si ambigu → Layer 2 orchestrator
- Output : items explicitement exclus + raison

#### Cap2.E — `comparison_contradiction_op` (à implémenter, **evidence-first**)
Pour "X et Y sont-ils différents" / contradictions implicites détectées dans evidence
- **Primary (evidence-first, pas LLM-detector)** : cluster facts par ClaimKey (sujet/prédicat/scope) en code Python, comparer values
- **Fallback 1** : si cluster ambigu → LLM qualifier (uniquement pour décider lifecycle vs scope vs conflict)
- **Fallback 2** : si pas de divergence détectée mais judge attend une → Layer 2
- Output : "X = a, Y = b, résolution = lifecycle_supersedes/scope/conflict"

### Pattern fallback commun Cap2 (amendment v1.1)
Chaque operator Cap2.x suit obligatoirement le pattern :
1. **Primary path** (déterministe Python + Cypher)
2. **Fallback 1** (déterministe étendu, ex: Qdrant resolver, list_all, LLM filter ciblé)
3. **Fallback 2** (semi-déterministe, ex: décomposition)
4. **Ultimate fallback** : Escalate Layer 2 avec contexte complet (question + intent + tentatives échouées)

**Charte commune** :
- Détection sémantique multi-langue (LLM léger DeepSeek), JAMAIS regex/keywords lexicaux
- Raisonnement Python déterministe quand possible (pas LLM dans la chaîne)
- Output formaté avec citations `[doc=...]`
- Fallback gracieux vers Layer 2 si ABSTAIN

---

### Cap3 — **Adaptive Orchestrator** (Layer 2)
**Nécessité prouvée par POC (causal -0.200pp, multi_hop -0.240pp en l'absence de Layer 2).**

**Architecture** : LLM agent avec tool use natif
- Tools disponibles : `vector_search`, `graph_query`, `temporal_active_op` (Cap2.A), `set_reasoning_op` (Cap2.D), `lifecycle_resolution_op` (Cap2.B), `kg_query_op` (Cap2.C), `comparison_contradiction_op` (Cap2.E), `calculator`, `date_parser`
- Modèle : **À décider via POC dédié Phase 3.A** (cf §6 Amendment 6) — candidates : DeepSeek-V3.1 / **Claude Sonnet 4.6** (recommandation Claude Web) / GPT-4o
- Plan iterative : décompose la question, appelle les tools, synthétise
- Budget compute : max 3-5 iterations, timeout p95 45s

**Trigger Layer 2 (amendment v1.1 — ChatGPT critical)** ⭐⭐⭐ :
> Layer 2 déclenché en cas d'**échec, incertitude ou conflit de résolution** dans les layers inférieurs.

Cas explicites de trigger :
1. **Layer 0 ABSTAIN** sans operator Cap2 applicable
2. **Layer 1 retourne `partial` ou `low_confidence`** (< 0.7)
3. **Plusieurs operators Cap2 applicables avec scores conflictuels** (ex: temporal + comparison + negation simultanés)
4. **Aucun operator Cap2 applicable** mais Layer 0 abstain (question trop complexe pour extraction directe)

**Latence cible** : 30-45s (acceptable pour ~5-10% des questions)
**Cas d'usage typiques** : multi-hop juridique, causal complexe, audit retrospectif, hypothétiques multi-étapes

---

### Cap4 — **Evidence Routing & Structuring** (transverse)
**Reuse V4.1 + extensions**

- Facts-first canonical (déjà fait V4.1 : EvidenceCollector, Structurer)
- Evidence bundles typés : `relational`, `temporal`, `comparative`
- Provenance quality scoring (confidence par claim)
- **Identifiers preservation** (D-MH.1 ADR v0.7) : Composer doit verbatim citer les codes/dates/articles présents dans les facts

---

### Cap5 — **Evaluation & Observability** (transverse)
- **Multi-view scorer** (pas écraser exact/fuzzy/semantic en un seul max — challenge ChatGPT)
  - exact_match
  - fuzzy_match (Levenshtein/token_set_ratio)
  - semantic_match (embedding similarity > 0.75)
  - Validation 100q (pas 30) avec distribution équilibrée par type — challenge Claude Web
- **Abstain reward** : `unanswerable + abstain_correct → structured_avg=1.0` (anti-Goodhart)
- **Off-target metrics** : différencier `abstain_correct` / `abstain_wrong` / `off_target_listing`

### **3 catégories abstain monitoring (amendment v1.1 — ChatGPT critical)** ⭐⭐⭐
> Risque "Layer 0 abstain happy" : si le Q↔A Verifier rejette trop, on transforme erreurs off-topic en abstentions abusives. Logger 3 catégories distinctes :
1. **`aligned`** : Q↔A Verifier laisse passer
2. **`misaligned_abstain_correct`** : Verifier rejette ET le gold-set / heuristique confirme que c'était la bonne décision
3. **`misaligned_but_answerable`** : Verifier rejette MAIS la question est en fait answerable → **alerte qualité**

**Threshold alerte** : si `misaligned_but_answerable` > 5% → tuning prompt Verifier requis.

### **Telemetry schema (amendment v1.1 — Claude Web)**
```python
@dataclass
class QuestionTrace:
    question_id: str
    layer_used: str  # "layer0" | "layer1_<op_name>" | "layer2"
    layer0_output: dict
    verifier_result: dict  # {decision, reason, confidence, latency_ms}
    intent_scores: dict  # par operator candidate
    layer1_operator: str | None
    layer1_output: dict | None
    layer1_fallback_path: str | None  # primary | fallback_1 | fallback_2 | escalate
    layer2_plan: list | None
    layer2_tool_calls: list | None
    layer2_iterations: int | None
    final_answer: dict
    escalation_path: str  # "layer0" | "layer0→layer1_temporal" | "layer0→layer2"
    latency_breakdown_ms: dict
    cost_usd: float
    abstain_category: str | None  # aligned | misaligned_abstain_correct | misaligned_but_answerable
```

### **Distribution validation (amendment v1.1 — Claude Web)**
Hypothèse architecturale : Layer 0 60-70%, Layer 1 20-30%, Layer 2 5-10%.
Validation cible : après 1000 questions production, vérifier :
- Si Layer 2 > 15% → operators Cap2 pas assez couvrants → ajouter operators
- Si Layer 0 < 50% → intent detection trop conservateur → relaxer thresholds
- Si Layer 1 < 15% → fallback paths trop souvent escaladés → fixer fallbacks

- **Q↔A misalignment logging** : top-20 cases par jour pour amélioration prompt verifier
- Multi-tag gold-set v5 (déjà fait, 290q)

---

## §2 — Mapping ADR v0.7 → v1.0

Les **32 décisions atomiques** v0.7 sont absorbées par les 5 capabilities :

| Décision v0.7 | Absorbée dans Cap | Type |
|---|---|---|
| D-TR.5 (Q↔A Alignment) | **Cap1** | Cœur architecture |
| D-LIST.1 (Target Disambiguation) | **Cap1** + Cap5 (multi-view scorer) | Q↔A Verifier généralise |
| D-LIST.2 (kg_query path) | **Cap2.C** | Operator dédié |
| D-LIST.3 (Composer exhaustivité) | **Cap4** | Identifiers + completeness in Composer prompts |
| D-LIST.5 (scorer fuzzy) | **Cap5** (multi-view) | Pas écraser, multi-vues |
| D-LIST.6 (abstain/off-target observability) | **Cap5** | Telemetry |
| D-FACT.1 (conditionnelles detection) | **Cap2.A** ou **Cap3** | Routing escalation |
| D-FACT.2 (negation_path) | **Cap2.D** (`set_reasoning_op`) | Généralisé en set ops |
| D-FACT.3 (routage temporel) | **Cap2.A** | temporal_active_op |
| D-FACT.4 (hallucination guard) | **Cap1** + **Cap5** | Verifier + observability |
| D-UNA.2 (source attribution) | **Cap1** + **Cap4** | Verifier + provenance |
| D-UNA.3 (scope check) | **Cap1** | Q↔A Verifier post-retrieval (PAS pré-retrieval — challenge ChatGPT) |
| D-UNA.4 (abstain reward) | **Cap5** | Multi-view scorer |
| D-TEMP.1 (temporal active version) | **Cap2.A** ✅ POC | Implémenté |
| D-TEMP.2 (lien KG query) | **Cap2.C** | Operator dédié |
| D-TEMP.3 (inférence inverse) | **Cap2.B** (`lifecycle_resolution_op`) | Operator dédié |
| D-TEMP.4 (anti-dégénération) | **Cap1** | Validation Composer post-output |
| D-CAUSAL.1 (cause-targeting) | **Cap3** | Orchestrator décompose |
| D-CAUSAL.2 (anti-circularité) | **Cap1** | Validation Composer |
| D-CAUSAL.3 (multi-step hypothetical) | **Cap3** | Orchestrator multi-step |
| D-CAUSAL.4 (audit Structurer) | Investigation séparée (CH-50.x) | Diagnostic |
| D-COMP.1 (contradiction detector) | **Cap2.E** | Operator evidence-first (pas LLM-judge — challenge ChatGPT) |
| D-COMP.2 (Composer both sides) | **Cap2.E** + **Cap4** | Composer prompt + operator |
| D-MH.1 (preserve identifiers) | **Cap4** | Composer prompt + validation |
| D-TR.4 (multi-tag gold v5) | ✅ **fait** (gold v5 290q) | Pré-requis |
| D-TR.1 (gold-set complet) | ✅ **fait** (290q, 100% Robust + T2T5) | Pré-requis |
| D-TR.2 (métriques absolues) | **Cap5** | Multi-view scorer |
| D-TR.3 (anti-biais auto-juge) | **Cap1** (Verifier DeepSeek ≠ Composer Llama) | Garde-fou |

**Total** : 32 décisions → **5 capabilities + ~5 operators dédiés**

---

## §3 — Apprentissages POC empiriques

### Validations
1. **Layer 0 dépasse V4.1 sur factual simple** (+0.383pp Robust subset)
2. **Q↔A Alignment Verifier (DeepSeek-V3.1)** détecte off-topic correctement (UNA_006 fixé en POC smoke)
3. **Operator déterministe temporal_active** : 100% précision quand déclenché (6/30 escalations bench v2)
4. **Latence -60%** vs pipeline V4.1 (7.8s vs 17-21s)
5. **Fallback Qdrant + list_all_active** : récupère les keywords sémantiques pas dans subjects KG

### Confirmations limites
1. **Sans Layer 2** : causal -0.200pp, multi_hop -0.240pp (impossible à compenser sans orchestrator)
2. **Intent detection** déclenche 40% des temporal — 60% des questions "temporal" en réalité requièrent d'autres operators (lifecycle_resolution, kg_query) → confirme la **taxonomie multi-operators** Cap2

### Découverte architecturale clé
Sur 5 questions taggées `temporal` dans gold v5, on a **3 sous-types distincts** qui nécessitent **operators différents** :
- "Version active à date X" → `temporal_active_op` (Cap2.A)
- "Qui a remplacé X" → `lifecycle_resolution_op` (Cap2.B)
- "Chaîne SUPERSEDES" → `kg_query_op` (Cap2.C)

→ **Le multi-tag (D-TR.4 / Cap5) est nécessaire** pour router correctement.

---

## §4 — Plan d'exécution révisé

### Phase 1 — Layer 0 production-grade (déjà partiel POC, ~3-4j)
1. Promouvoir Layer 0 POC en path par défaut runtime_v4
2. Q↔A Verifier en production (DeepSeek-V3.1) — gérer rate-limits Together (retry exponential backoff + fallback provider)
3. **Unified prompt extract+intent+QA** (amendment v1.1 — Claude Web) : tester vs séparé, gain attendu -30% latence / -40% coût Layer 0
4. Multi-view scorer (Cap5) — révèle qualité cachée + validation 100q
5. Abstain reward (Cap5)
6. 3 catégories abstain logging (Cap5)

**Gates Phase 1 (amendment v1.1 — ChatGPT non-régression)** :
- ✅ Robust global ≥ 0.45 (vs 0.403 actuel V4.1)
- ✅ Layer 0 `false_abstain_rate` (`misaligned_but_answerable`) ≤ 5%
- ✅ Layer 0 p95 latency ≤ 12s (vs ~21s V4.1)
- ✅ Aucune régression > 0.05pp sur factual/list/unanswerable
- ✅ Citation/source preservation rate ≥ baseline V4.1

### Phase 2 — Operators Layer 1 (~6-8j)
1. **Cap2.A** `temporal_active_op` ✅ déjà POC — production-grade (3 fallback paths)
2. **Cap2.B** `lifecycle_resolution_op` (3j) — fallback paths documentés
3. **Cap2.C** `kg_query_op` (2j) — Cypher templates par type
4. **Cap2.D** `set_reasoning_op` (2-3j) — pour negation Pattern G
5. **Matrix de priorité multi-tag** (amendment v1.1 — Claude Web) : matrix simple Phase 2, scorer multi-dim Phase 3 si insuffisant
6. **Telemetry layer distribution** : QuestionTrace activé en production

**Gates Phase 2 (amendment v1.1 — non-régression)** :
- ✅ temporal +0.15pp, factual+negation +0.10pp, list +0.10pp
- ✅ Layer 1 success_rate (decision=ANSWER) ≥ 80% quand operator déclenché
- ✅ Pas de régression sur causal/multi_hop (qui restent en Layer 0/escalation)
- ✅ Distribution layer Layer 1 = 15-30%
- ✅ Coût moyen par question Layer 1 < 1.5x coût Layer 0

### Phase 3 — Adaptive Orchestrator Layer 2 (~5-7j)

#### **Phase 3.A — POC dédié choix modèle (2-3j, amendment v1.1)** ⭐⭐⭐
Avant de figer DeepSeek pour Layer 2, POC comparatif sur 25 questions stratifiées causal/multi_hop/hypothetical :

```python
models_poc = ["deepseek-v3.1", "claude-sonnet-4-6", "gpt-4o"]
metrics = [
    "structured_avg",
    "latency_p50", "latency_p95",
    "cost_per_question",
    "tool_call_success_rate",
    "tool_call_avg_iterations",
]
```

**Critères de décision** :
- Si Claude Sonnet 4.6 : structured_avg ≥ DeepSeek + 0.10 → **swap Claude**
- Si coût Claude < 2× DeepSeek ET perf meilleur → **swap Claude**
- Si latence p95 critique (> 40s) → optimiser prompt OU GPT-4o
- Sinon → **garder DeepSeek-V3.1** (cohérence Verifier Layer 0)

#### Phase 3.B — Implémentation Layer 2 (~3-4j)
1. Tool registry (vector_search, graph_query, operators Cap2.A-E)
2. LLM agent loop avec budget compute (max 3-5 iterations, timeout p95 45s)
3. Plan + execute + synthesize pattern
4. Trigger élargi (cf §1 Cap3 — 4 cas)

**Gates Phase 3 (amendment v1.1 — non-régression)** :
- ✅ causal +0.10pp, multi_hop +0.20pp, hypothetical multi-step +0.15pp
- ✅ Layer 2 escalation rate dans 5-10% (pas plus, pas moins)
- ✅ Layer 2 p95 latency ≤ 45s
- ✅ Cost per Layer 2 question < 5× cost Layer 0 question
- ✅ Tool call success rate ≥ 90% (pas de boucles infinies/erreurs tool)

### Phase 4 — `comparison_contradiction_op` + audit (~3-4j)
1. **Cap2.E** evidence-first cluster + LLM qualifier (pas LLM-detector — challenge ChatGPT)
2. **A/B test evidence-first vs LLM-detector** (amendment v1.1 — Claude Web) : valider empiriquement le choix evidence-first sur 30 questions T2
3. Investigation Structurer V4.1 vs V4.2 (audit qualité claims extraction)

**Gates Phase 4 (amendment v1.1 — non-régression)** :
- ✅ T2 contradictions both_sides_surfaced +0.20pp
- ✅ A/B test confirme evidence-first ≥ LLM-detector
- ✅ Pas de régression structured_avg < 0.55 global Robust

### Total estimé
**~17-23 jours** dev étalés sur 4-6 semaines (parallélisable en partie).

**Cible cumul** : Robust global_score 0.403 → **~0.55-0.60**.

---

## §5 — Risques et open questions

### Risques validés/mitigés
| Risque | Validation/mitigation |
|---|---|
| Pipeline inflation (challenge ChatGPT) | ✅ Architecture en couches escalation, pas empilement |
| Latence cumulée | ✅ Layer 0 5-10s, Layer 1 ~5s, Layer 2 30-45s — mean amorti < V4.1 actuel |
| Domain-agnostic violation | ✅ Sémantique LLM, pas regex domain |
| Biais auto-juge | ✅ Verifier DeepSeek ≠ Composer Llama |
| 32 patches au lieu d'archi (challenge 3 LLMs) | ✅ Refonte 5 capabilities |

### Risques résiduels à surveiller
1. **Cascade LLM verifiers** : Layer 0 + Q↔A Verifier + operator intent + Layer 1 LLM = potentiel 3-4 LLM calls. Mitigation : caching, parallelisation, opérateurs déterministes pure-python quand possible.
2. **Scorer multi-view** : éviter inflation faux positifs sur fuzzy. Mitigation : validation manuelle 30q avant promotion en production.
3. **Tool use Llama-Turbo vs DeepSeek** : Layer 2 tool use validé seulement chez OpenAI/Anthropic. POC nécessaire avec DeepSeek-V3.1 avant Phase 3.

### Open questions
1. Performance Layer 2 sur DeepSeek-V3.1 vs swap GPT-4/Claude pour le orchestrator ? **POC dédié Phase 3.A**
2. Faut-il un cache de keywords→doc_ids résolu via Qdrant pour accélérer les operators Cap2 ? **À mesurer post Phase 2.**
3. Comment gérer les questions hybrides multi-tag (factual + temporal + negation) ? **Multi-tag gold v5 + signal scoring → routing par capability dominante + escalation possible**.

---

## §6 — Amendments v1.0 → v1.1 (post 2e round LLM critiques)

### Amendments majeurs (5)

#### Amendment 1 — False abstain monitoring (Cap5)
> **Risque ChatGPT** : "Layer 0 abstain happy" → trans erreurs off-topic en abstentions abusives.
> **Action** : 3 catégories logging (aligned / misaligned_abstain_correct / misaligned_but_answerable) + threshold 5% alerte.

#### Amendment 2 — LLM = aiguilleur ou rédacteur, JAMAIS operator (Cap2 charte) ⭐⭐⭐
> **Convergence ChatGPT** : "lifecycle / KG query / temporal / comparison / set : déterministe ; LLM = aiguilleur ou rédacteur, pas operator."
> **Action** : charte explicite ajoutée dans Cap2.

#### Amendment 3 — Trigger Layer 2 élargi (Cap3) ⭐⭐⭐
> **Critique ChatGPT** : "Trigger Layer 2 si Layer 0 ABSTAIN ET aucun operator → trop restrictif, questions hybrides bloquées."
> **Action** : 4 cas explicites (échec / incertitude / conflit operators / pas d'operator applicable).

#### Amendment 4 — Gates de non-régression (chaque phase) ⭐⭐
> **Critique ChatGPT + Claude Web** : "Gates orientés score uniquement → manque non-régression latence/coût/false_abstain/source preservation."
> **Action** : gates étendus avec critères telemetry par phase.

#### Amendment 5 — Telemetry schema complet (Cap5) ⭐⭐
> **Recommandation Claude Web** : QuestionTrace dataclass + distribution validation cible.
> **Action** : schema explicite, distribution check après 1000 questions production.

### Amendments additionnels Claude Web (4)

#### Amendment 6 — POC Layer 2 modèle (Phase 3.A nouvelle)
DeepSeek-V3.1 vs **Claude Sonnet 4.6** (recommandation forte Claude Web) vs GPT-4o sur 25q. Critères de swap définis.

#### Amendment 7 — Unified prompt Layer 0 (Phase 1)
Extract + intent + Q↔A en 1 call. Gain attendu -30% latence / -40% coût Layer 0.

#### Amendment 8 — Fallback paths Cap2.B/C/D/E
Documentation explicite Primary → Fallback 1 → Fallback 2 → Escalate Layer 2 pour chaque operator (pattern uniforme).

#### Amendment 9 — Validation scorer 100q (pas 30)
Distribution : 20 exact_match_expected, 20 fuzzy_valid, 20 semantic_valid, 20 false_positives, 20 mixed.

### Checklist exécution v1.1

#### Avant Phase 1
- [ ] Budget latence p95 défini par layer (Layer 0: 12s, Layer 1: 25s, Layer 2: 45s)
- [ ] Stratégie rate-limits Together documentée (retry exponential backoff)
- [ ] Unified prompt Intent+Q↔A testé vs séparé (-30% latence cible)
- [ ] Schema QuestionTrace implémenté

#### Avant Phase 2
- [ ] Fallback paths documentés Cap2.B/C/D/E (présents dans ADR §1)
- [ ] Matrix de priorité multi-tag définie (simple)
- [ ] Telemetry layer distribution dashboard

#### Avant Phase 3
- [ ] **POC Layer 2 dédié** : DeepSeek vs Claude Sonnet 4.6 vs GPT-4o (Phase 3.A)
- [ ] Critères de décision modèle documentés
- [ ] Budget compute Layer 2 défini (max 3-5 iterations, timeout 45s)

#### Avant Phase 4
- [ ] Validation scorer multi-view sur 100q (pas 30)
- [ ] A/B test evidence-first vs LLM-detector (Cap2.E)

---

## §A — Annexes

### A.1 Données empiriques POC

**Bench POC v2 — 30 questions stratifiées (gold v5)** :

| Type | n | POC v2 struct_avg | V4.1 (gold v5) | Δ | POC mean ms |
|---|---:|---:|---:|---:|---:|
| factual | 5 | 0.583 | 0.200 | **+0.383** ✅ | 7568 |
| list | 5 | 0.100 | 0.000 | **+0.100** ✅ | 9708 |
| temporal | 5 | 0.200 | 0.175 | **+0.025** ✅ | 5611 |
| causal | 5 | 0.400 | 0.600 | -0.200 ⚠️ | 9340 |
| unanswerable | 5 | 0.000 | 0.000 | = | 7656 |
| multi_hop | 5 | 0.000 | 0.240 | -0.240 ⚠️ | 6724 |
| **GLOBAL** | 30 | **0.214** | 0.203 | **+0.011** ✅ | **7768** |

**Layers déclenchés** : layer0=24, layer1_temporal_active=6 (20%)

### A.2 Code POC livré (production-ready après tuning)

- `src/knowbase/runtime_v4_poc/qa_alignment_verifier.py` (Cap1)
- `src/knowbase/runtime_v4_poc/layer0_pipeline.py` (Cap1 + escalation)
- `src/knowbase/runtime_v4_poc/operators/temporal_active_version.py` (Cap2.A)
- `src/knowbase/api/routers/runtime_v4_poc.py` (endpoint)

### A.3 Charte (rappel)
- **Domain-agnostic strict** : sémantique LLM multi-langue, JAMAIS regex/keywords corpus-spécifiques
- **Anti-Goodhart** : tout fix doit améliorer pour utilisateurs prod, pas juste passer le bench
- **Cohérence bench/prod** : même pipeline (Layer 0 + operators + orchestrator)
- **Anti-biais auto-juge** : Verifier ≠ Composer (DeepSeek-V3.1 vs Llama-3.3-70B)

### A.4 Sources état de l'art 2026
- [Agentic RAG: The 2026 Production Guide - MarsDevs](https://www.marsdevs.com/guides/agentic-rag-2026-guide)
- [Rethinking RAG: Pipelines Are the Past, Agentic Is the Future](https://medium.com/@springrod/rethinking-rag-pipelines-are-the-past-agentic-is-the-future-77c887414621)
- [Adaptive Parallel Reasoning - BAIR Berkeley](https://bair.berkeley.edu/blog/2026/05/08/adaptive-parallel-reasoning/)
- [A2RAG: Adaptive Agentic Graph Retrieval](https://arxiv.org/html/2601.21162v1)
- [Reasoning RAG via System 1 or System 2 Survey](https://arxiv.org/html/2506.10408v1)
- [Corrective RAG (CRAG)](https://arxiv.org/abs/2401.15884)
- [Mitigating Hallucination LLMs Survey](https://arxiv.org/html/2510.24476v1)
- [Ontology-grounded KG hallucination mitigation](https://www.sciencedirect.com/science/article/abs/pii/S1532046426000171)

### A.5 Convergence challenges LLMs critiques (round 1 + 2)
| Point | ChatGPT-5 #1 | ChatGPT-5 #2 | Claude Web Opus #1 | ChatGPT-5 #3 | Claude Web Opus #2 | Validation POC | Amendment v1.1 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 32 décisions trop granulaires | ⚠️ | ✅ | ✅ | (résolu) | (résolu) | ✅ | — |
| Reasoning escalation principe | ⭐ | ⭐ | ⭐ | ✅ | ⭐⭐ | ✅ | — |
| Pipeline rigide → orchestration | ⚠️ | ⚠️ | ⭐ | ⚠️ | ⭐ | ✅ | — |
| Q↔A Alignment cœur archi | (impl.) | ⭐ | ⭐ | ⭐ | ⭐ | ✅ +0.383 | — |
| Multi-tag gold-set | (impl.) | ⭐ | ⭐ | (résolu) | (résolu) | ✅ v5 | — |
| Negation = set reasoning | (impl.) | ⭐ | ⭐ | (résolu) | (résolu) | À confirmer P2.D | — |
| Preserve identifiers | (impl.) | ⭐ | ⭐ | (résolu) | (résolu) | À confirmer P1 | — |
| Scope check post-retrieval | — | ⭐ | (similaire) | (résolu) | (résolu) | ✅ Verifier post | — |
| Contradiction evidence-first | — | ⭐ | (similaire) | ⭐ | (similaire) | À confirmer P4 | — |
| Scorer multi-view (pas unique) | — | ⭐ | ⭐ | ⭐ | ⭐ | Phase 1 Cap5 | — |
| **Layer 0 abstain happy risk** | — | — | — | ⭐⭐⭐ | (similaire) | Phase 1 | **A1** |
| **LLM ≠ operator (déterministe)** | ⭐ | ⭐ | (similaire) | ⭐⭐⭐ | (similaire) | Phase 2 | **A2** |
| **Trigger Layer 2 élargi** | — | — | — | ⭐⭐⭐ | ⭐ | Phase 3 | **A3** |
| **Gates non-régression** | — | — | — | ⭐⭐ | ⭐ | Toutes phases | **A4** |
| **Telemetry schema** | — | — | — | ⭐ | ⭐⭐ | Phase 1 | **A5** |
| **POC Layer 2 modèle** | — | — | — | — | ⭐⭐⭐ | Phase 3.A | **A6** |
| **Unified prompt Layer 0** | — | — | — | — | ⭐ | Phase 1 | **A7** |
| **Fallback paths Cap2.B/C/D/E** | — | — | — | — | ⭐ | Phase 2 | **A8** |
| **Validation scorer 100q** | — | — | — | — | ⭐ | Phase 1 | **A9** |
