# ADR — OSMOSIS V4 Facts-First Architecture

**Status** : Proposed (2026-05-06)
**Validation** : 3 voix — Fred + Claude + ChatGPT
**Predecessors** : `ADR_OSMOSIS_V4_ARCHITECTURE.md` (V4 initial — sprints S0/S0.5/S1/S2/S3 SUPERSEDED par cet ADR)
**References** :
- `V4_S0_BASELINE.md` (résultats Sprint S0 — diagnostic fondateur)
- `V4_S0_DISAGREEMENT_ANALYSIS.md` (top-20 judge_overscored)
- `feedback_no_mvp_transitoire.md` (contrainte produit)

---

## 1. Contexte et motivation

Sprint S0 V4 (2026-05-05) a démontré par mesure :
- **factual_correctness 0.368** (médiane 0.40, p25=0.00) sur 97q gold-set v4
- **item_recall 0.07** sur questions list — 4% des items attendus présents dans les réponses
- **31.7% des samples judge_overscored** vs structured metrics
- **structured_avg 0.41 vs judge 0.53** = +11.7pp d'overscoring confirmé
- **50% des questions déclenchent une régen NLI** (mDeBERTa) — faux positifs UNFAITHFUL

**Diagnostic** : le pipeline V3 (chunks → LLM résume → réponse) souffre de **compression sémantique destructive**. Le LLM perd / simplifie / modifie l'info en route. Le verifier ne fait que constater le dégât.

**Conséquence** : optimiser le verifier (Sprint S1 initial) ne corrige pas la perte amont. Il faut **empêcher la perte**, pas la détecter.

**Contrainte produit non-négociable** (cf `feedback_no_mvp_transitoire.md`) : pas de MVP transitoire. Implémenter la cible directement.

---

## 2. Décision architecturale

### D-FF1 — Pipeline V4 facts-first

```
Question
  │
  ▼
[A] QuestionAnalyzer (type detection multi-label top-2)
  │
  ▼
[B] EvidenceCollector (Claims Neo4j primaire + chunks Qdrant secondaire)
  │
  ▼
[C] Type-Adaptive Structurer (cœur du pipeline)
  │
  ▼
[D] Composer (LLM borné au JSON structuré → prose, ne crée aucun fait)
  │
  ▼
[E] Verifier 2 channels (citation déterministe + NLI ciblé sur sentences à risque)
  │
  ▼
Réponse user-facing
```

Le LLM ne décide plus de la **structure** de la réponse. Il extrait des faits structurés (étape C), puis formate (étape D). La vérité est construite **avant** la réponse, pas pendant.

### D-FF2 — Source primaire = Claims Neo4j

Les 40 196 claims atomiques (médiane 113 chars) déjà persistés dans Neo4j servent de source primaire au Structurer. Les chunks Qdrant restent en source secondaire pour contexte/disambiguation.

**Fallback** : pour un tenant sans Claims indexés (futur Domain Pack neuf), le Structurer dégrade vers chunks-only. À documenter mais ne bloque pas la livraison.

### D-FF3 — Type-adaptive (pas EAV universel)

6 types primaires reconnus par le QuestionAnalyzer + 1 dispatch hors-types :
1. `factual`
2. `list`
3. `temporal`
4. `comparison`
5. `causal`
6. `unanswerable` / `false_premise`

Chaque type a son **schéma JSON dédié** (cf §4 Schémas). Pas de schéma EAV universel — les schémas sont structurellement différents (causal = chain ordonnée, comparison = paire + relation, list = enumeration, etc.).

### D-FF4 — Composer borné au JSON

Le Composer reçoit le JSON structuré + la question. Sa sortie inclut un mapping `sentence → support_ids` pour traçabilité. Il ne peut introduire **aucun fait** absent du JSON. Tout token `[number/date/identifier]` dans la réponse doit exister dans le JSON.

### D-FF5 — Verifier 2 channels avec déclenchement conditionnel

- **Channel 1 (déterministe, 0ms)** : chaque sentence a un `support_ids` non vide ET tout identifier/date/number cité existe dans les `source.quote` des objets référencés. Sinon → repair.
- **Channel 2 (NLI ciblé, ~1-2s)** : déclenché uniquement sur sentences flagged par C1 OU contenant relation comparison OU mécanisme causal. NLI multilingue mDeBERTa (déjà en place V3) en triage, escalade vers specialist (MiniCheck/HHEM EN-only) si C2 ambiguous.

### D-FF6 — Stockage Neo4j séparé, persistence conditionnelle

Nouveaux nœuds runtime/persistable :
```cypher
(:StructuredFact)
(:StructuredList)
(:StructuredListItem)
(:StructuredTemporalEvent)
(:StructuredComparison)
(:StructuredCausalChain)
(:StructuredCausalStep)
```

Relations vers les objets existants :
```cypher
(StructuredFact)-[:DERIVED_FROM]->(Claim)
(StructuredFact)-[:SUPPORTED_BY]->(Passage)
(StructuredFact)-[:FROM_DOCUMENT]->(Document)
(StructuredFact)-[:USES_CHUNK]->(RetrievalChunk)
```

Les Claims existants ne sont **pas** modifiés. Les StructuredFact dérivent d'eux.

**Persist policy** : runtime-only par défaut. Persistance Neo4j uniquement si `confidence ≥ 0.7` ET utile (audit, benchmark, cache cross-question). Évite de polluer le KG durable avec du bruit runtime.

### D-FF7 — Tranches verticales (pas MVP)

Chaque tranche implémente l'**architecture cible complète** sur un type. V3 reste actif sur les types non encore migrés et est éteint type par type au fur et à mesure.

```
Tranche 1 : list                         (item_recall 0.07 → ≥ 0.65)
Tranche 2 : factual                       (exact_match identifiers)
Tranche 3 : temporal + comparison         (lifecycle metadata + LOGICAL_RELATION)
Tranche 4 : causal_why                    (causal chain extraction + missing_links)
Tranche 5 : unanswerable / false_premise  (negative evidence + correction)
Tranche 6 : verifier cascade complet      (PAS avant — qualité vient du fact extraction)
```

### D-FF8 — Gate par type (jamais score global)

Aucun score global ne peut autoriser le déploiement d'un type. Chaque type a son gate. Si un type échoue, on ne le ship pas — V3 reste actif sur ce type uniquement.

---

## 2-bis. Verrouillage contrats — pré-requis bloquant avant code

> **Réserve forte ChatGPT (2026-05-06 review)** : « Verrouiller le contrat du Structured Evidence Package commun et le contrat d'extension Domain Pack avant de coder la tranche list. Sans ça, tu risques de bien réussir `list`, mais de devoir refaire les fondations au moment de `temporal/comparison`. »

Cette étape est **bloquante** pour CH-41.0 (pré-requis) et a fortiori pour CH-41.1+ (code).

### D-FF9 — Contrat Structured Evidence Package commun (figé avant code)

Tous les schémas par type partagent un **socle commun versionné**. Aucun champ commun ne peut être ajouté/modifié après tranche 1 sans bump de `schema_version` + plan de migration.

```json
{
  "schema_version": "facts_first_v1",
  "primary_type": "factual | list | temporal | comparison | causal | unanswerable | false_premise",
  "answerability": "answerable | partial | unanswerable | false_premise",
  "coverage_state": "complete | partial | unknown | not_applicable",
  "source": {
    "doc_id": "...",
    "claim_id": "...",
    "chunk_id": "...",
    "page_no": 42,
    "quote": "exact verbatim source quote"
  },
  "confidence": 0.0_to_1.0,
  "language": "fr | en | ...",
  "extracted_at": "ISO-8601",
  "extraction_model": "Qwen2.5-72B-Instruct@deepinfra | Qwen2.5-14B-Instruct-AWQ@vllm | ..."
}
```

Chaque type ajoute ses champs spécifiques **dans des espaces nommés** (ex `list_specific.items`, `comparison_specific.compared_facts`, `causal_specific.chains`) — pas de collision possible entre types.

### D-FF10 — Contrat d'extension Domain Pack (figé avant code)

Un Domain Pack peut étendre les valeurs énumérées **sans modifier le code core**. Le core minimal universel est :

| Champ | Core minimal universel | Extension Domain Pack possible |
|-------|------------------------|--------------------------------|
| `comparison.relation.type` | `equivalent`, `different`, `related`, `unknown` | `conflict`, `supersession`, `subset`, `superset`, `complementary`, `BLOCKS`, `REQUIRES`, `CONTRAINDICATES`, ... |
| `comparison.relation.basis` | `value`, `time`, `unknown` | `scope`, `method`, `definition`, `regulatory_framework`, `clinical_context`, ... |
| `temporal.change_type` | `added`, `removed`, `changed`, `unknown` | `replaced`, `modified`, `superseded`, `clarified`, `deprecated_by_amendment`, ... |
| `temporal.time_anchor.kind` | `date`, `version`, `unknown` | `amendment`, `release`, `effective_date`, `applicable_from`, ... |
| `causal.steps.role` | `cause`, `effect`, `condition`, `unknown` | `mechanism`, `exception`, `context`, ... |
| `factual.qualifiers.lifecycle_status` | `ACTIVE`, `DEPRECATED`, `UNKNOWN` | `DRAFT`, `IN_REVIEW`, `WITHDRAWN`, `SUPERSEDED`, ... |

**Format Domain Pack extension** :
```yaml
# domain_packs/<domain>/facts_first_extensions.yaml
schema_version: facts_first_v1
extensions:
  comparison:
    relation_types:
      - { name: SUPERSESSION, description: "later active source replaces older deprecated", maps_to: different }
      - { name: SUBSET, description: "...", maps_to: related }
  temporal:
    change_types:
      - { name: replaced, description: "...", maps_to: changed }
```

Règle invariante : **toute valeur Domain Pack étendue doit avoir un `maps_to` vers le core minimal universel**. Permet au Composer générique de produire une réponse cohérente même si le Domain Pack n'est pas chargé.

### D-FF11 — Fallback EAV = abstention structurée, pas généraliste

Le schéma EAV universel (cf §3 ci-dessous) est **un mode d'abstention structurée**, pas un chemin de réponse généraliste. Quand le router ne reconnaît pas un type avec confidence ≥ 0.5, le système :
1. Applique l'extraction EAV minimale `{entity, attribute, value, source, confidence}`
2. Le Composer formate avec **disclaimer explicite** : « Cette question ne correspond pas à un type de réponse pris en charge par OSMOSIS. Voici les faits structurés extraits, sans synthèse interprétative. »
3. La réponse est marquée `coverage_state: not_applicable` et `answerability: partial`

Le mode EAV ne doit **pas** devenir le fourre-tout. Il existe pour ne pas retomber en LLM-libre silencieux. Si > 10% du trafic tombe sur EAV, c'est un signal de revoir la typologie.

### D-FF12 — Panel stress-test 100q = couverture typologique seulement

Le panel stress-test 100q multi-domaines (médical, juridique, software docs, RH, produit) sert **uniquement** à valider :
1. Que ≥ 95% du trafic tombe dans un type avec confidence ≥ 0.5 (HFF5)
2. Que les schémas par type sont **structurellement** capables de représenter ces questions

Il **ne sert pas** à mesurer la qualité de réponse end-to-end (factual_correctness, item_recall, etc.) — ça reste sur le gold-set v4 enrichi par tranche. Pas de chantier parallèle « bench multi-domaines ».

### D-FF13 — Chunk-extractive fallback pour factual simple

> **Contexte** : le système V1.1 historique avait un mécanisme « si KG silencieux → RAG pur » via `signal_policy.py` (mode `DIRECT`). Ce mécanisme a été perdu dans le pipeline V3 (CH-39) puis dans le design Facts-First initial. Or l'historique mesuré montre que sur les questions factuelles simples (« quelle version de X »), le KG dégradait les réponses (RAG pur +6pp).
>
> Risque V4 sans garde-fou : Facts-First reproduit l'erreur historique en imposant le chemin `router → claims Neo4j → structurer → JSON → composer` sur des questions où le top chunk Qdrant a déjà la réponse exacte.
>
> Décision validée 3 voix (Fred + Claude + ChatGPT, 2026-05-06) : préserver Facts-First comme chemin nominal MAIS introduire une soupape déterministe quand le Structurer signale lui-même une faible confiance.

**Activation (toutes conditions cumulatives)** :
- `primary_type = factual` (router single-label, conf ≥ 0.7)
- `FactualStructurer` retourne 0 fact OU `max(facts[].confidence) < initial_threshold`
- Top chunk Qdrant score ≥ `initial_threshold`
- `object.kind ∈ {date, number, identifier, name, currency, duration, boolean}` (PAS `text` — exigerait synthèse)
- Aucune `LOGICAL_RELATION` critique détectée sur le sujet (CONFLICT/SUPERSESSION en cours)
- **Pas de désaccord explicite** entre fact faible Structurer et chunk top-1 (cf cas désaccord ci-dessous)

**Comportement** :
- Extraction verbatim depuis chunk top-1 uniquement (pas claims Neo4j)
- LLM mode « extract verbatim, do not synthesize » (prompt court ≤ 30 lignes)
- Sortie au format `facts_first_v1` valide (pas un retour V3 caché)
- `factual_specific.facts[0].source.chunk_id = <top_chunk_id>` obligatoire
- `diagnostic.fallback_mode = "factual_simple_chunk_extractive"`
- Citation chunk_id obligatoire (verifier C1 valide)

**Cas désaccord claims vs chunk** :
Si `FactualStructurer` extrait un fact faible (confidence < threshold) mais sa `value` diverge du chunk top-1 (signal de tension potentielle) :
- **NE PAS** trancher arbitrairement
- Si la divergence porte sur un `object.raw` numérique/identifiant → `coverage_state: unknown` + `diagnostic.fallback_mode = "factual_simple_conflict_suspected"` + `answerability: partial`
- Le Composer signale honnêtement les 2 sources sans en privilégier une

**Seuils** :
- `initial_threshold = 0.7` à la livraison de tranche 2 (factual)
- **Recalibration obligatoire** sur gold-set factual simple post-tranche 2 (cf charte anti-V2 « toute claim de gain mesurée AVANT annonce »)
- Persisté dans `config/response_modes_thresholds.yaml` à terme (intégration mode `factual_simple_fallback_threshold`)

**Gate ship CH-41 (factual = tranche 2)** :
Sur gold-set factual simple (≥ 30 questions stratifiées avec `object.kind` court) :
- `factual_correctness(facts-first avec D-FF13) ≥ factual_correctness(RAG baseline pur)`
- Sinon → la tranche `factual` ne ship pas, V3 reste actif sur ce type jusqu'à correction

→ Implique de mesurer le **RAG baseline pur** en parallèle (retrieval + LLM extract sans Structurer) sur les mêmes 30+ questions. À cadrer dans CH-41.0 pré-requis.

**Pourquoi pas un retour V3 caché** :
Le fallback reste un **Structured Evidence Package valide** au format `facts_first_v1`. Source = chunk au lieu de Claim Neo4j, mais sortie homogène avec le reste du pipeline (composer + verifier + citation déterministe). Aucune dérogation à la charte « pas de réponse user-facing directement depuis chunks sans package structuré » (D-FF1).

---

## 3. Hors-typologie (gestion robuste)

Risque identifié : un Type-Adaptive avec routing strict plante silencieusement sur questions multi-label, hors-typologie ou méta.

### Stratégie B+C+E (validée Fred)

1. **Schéma EAV universel comme base de fallback** : si le router renvoie un type avec confidence < 0.5, le Structurer applique l'extraction EAV minimale `{entity, attribute, value, qualifiers, source, confidence}` pour produire au moins une réponse structurée. Jamais retomber en LLM-libre.
2. **Multi-label top-2** avec confidence threshold :
   - conf ≥ 0.7 → un type unique
   - 0.5 ≤ conf < 0.7 → top-2 + composition combinée
   - conf < 0.5 → EAV universel seul
3. **ABSTAIN explicite** si l'extraction EAV elle-même retourne 0 fait pertinent. La réponse devient « Cette question ne peut pas être traitée par les chemins structurés actuels. [détail] » — honnête, jamais une réponse fabriquée.

### Gate de couverture (obligatoire avant livraison tranche 1)

Mesurer sur :
- **Gold-set v4 actuel** (97q aero) : quel % tombe naturellement dans 1 type / multi-label top-2 / hors-types ?
- **Panel stress-test multi-domaines** (NEW à construire — 100q variées : médical, juridique, software docs, RH, produit) : même mesure

**Critère** : ≥ 95% du trafic doit tomber dans un type avec confidence ≥ 0.5. Sinon → revoir la typologie (ajouter type, étendre via Domain Pack) avant déploiement.

---

## 4. Schémas par type (extraits du design Structurer V1 ChatGPT, ajustés)

> Source du design détaillé : réponse ChatGPT 2026-05-06 (intégrée avec ajustements ci-dessous).
> Schémas complets (orchestration, prompts, gates, latences cibles) : reportées en annexe.

### 4.1 Ajustements vs design ChatGPT initial

| # | Champ | Ajustement |
|---|-------|------------|
| AC1 | `relation.type` (comparison) | Core minimal universel `{equivalent, different, related, unknown}`. Extensions `{conflict, supersession, subset, superset, complementary, ...}` via Domain Pack actif (pas hardcoded). |
| AC2 | `change_type` (temporal) | Idem AC1 — core universel `{added, removed, changed, unknown}` + extensions Domain Pack. |
| AC3 | `detected_issue.type` (false_premise) | Reformulé en signal sémantique multilingue : `{assumption_contradicts_evidence: bool, nature: free_text, contradicting_evidence_ids: [...]}`. Pas de liste fermée domain-spécifique. |
| AC4 | Latences cibles | Marquées **hypothèses**, pas commits. Mesure obligatoire post-tranche 1, ré-évaluation si dépassement. |
| AC5 | Effort tranche 1 | Ré-évalué à **3-4 semaines** (5 composants + dataset list enrichi 20→50 questions + 250+ atomes gold annotés humainement + bench dédié + ablation). |
| AC6 | Gold-set d'atomes | NEW : pour mesurer F1 extraction par type, nécessite annotation humaine d'atomes attendus. ≥ 50 questions × ≥ 5 atomes = 250+ atomes par type. Construction obligatoire **avant** déploiement de chaque tranche. |
| AC7 | Fallback chunks-only | Documenté pour tenants sans Claims indexés (Domain Pack neuf). Dégradation contrôlée, ne bloque pas livraison. |

### 4.2 Schémas par type (références)

Voir annexe complète. Synthèse :

- **list** : `items[]` avec `{label, normalized_label, item_type, source, confidence}` + `enumeration_quality.coverage_state`
- **factual** : `facts[]` avec `{subject, predicate, object{raw, normalized, kind, unit}, qualifiers{condition, scope, time_anchor, lifecycle_status}, source, confidence}`
- **temporal** : `timeline[]` avec `{event_id, time_anchor, state{status, predicate, value}, change_type, source}` + `current_basis`
- **comparison** : `compared_facts[]` (sides A/B) + `relation{type, basis, explanation, confidence}` + `preferred_answer_basis`
- **causal** : `causal_chains[]` avec `steps[]` (role ∈ cause/condition/mechanism/effect/exception/context) + `missing_links[]`
- **unanswerable / false_premise** : `decision`, `question_assumption`, `supporting_negative_evidence[]`, `correction`, `abstention_reason`

### 4.3 Schéma commun à tous les types

```json
{
  "schema_version": "facts_first_v1",
  "primary_type": "...",
  "answerability": "answerable | partial | unanswerable | false_premise",
  "coverage_state": "complete | partial | unknown | not_applicable",
  // ... champs spécifiques au type
}
```

Tout objet structuré porte un `source` :
```json
{
  "doc_id": "...",
  "claim_id": "...",  // identifie le Claim Neo4j source
  "chunk_id": "...",  // optional, pour fallback
  "page_no": 42,
  "quote": "exact verbatim source quote"
}
```

---

## 5. Plan d'exécution révisé

| Étape | Durée estimée | Livrable | Gate |
|-------|---------------|----------|------|
| **0. Pré-requis** | 1 sem | Enrichir gold-set v4 list (20→50q), construire panel stress-test 100q multi-domaines, annoter 250+ atomes list humainement | Gold-set list ≥ 50q + panel stress-test ≥ 100q + atomes annotés ≥ 250 |
| **1. Tranche list** | 3-4 sem | QuestionAnalyzer (limité list detection), EvidenceCollector, ListStructurer, ListComposer, Channel 1 verifier, bench dédié | item_f1 ≥ 0.70, item_recall ≥ 0.65, source_accuracy ≥ 0.80, p95 ≤ 35s, couverture types ≥ 95% gate |
| **2. Tranche factual** | 2-3 sem | FactualStructurer, exact_identifier verification | fact_tuple_f1 ≥ 0.75, exact_identifier_match ≥ 0.80 |
| **3. Tranche temporal+comparison** | 3-4 sem | TemporalStructurer + ComparisonStructurer, exploitation lifecycle metadata + LOGICAL_RELATION | event_f1 ≥ 0.70, lifecycle_status_accuracy ≥ 0.80, side_fact_f1 ≥ 0.75, relation_accuracy ≥ 0.70 |
| **4. Tranche causal** | 3-4 sem | CausalStructurer avec missing_links | causal_step_f1 ≥ 0.65, chain_order_accuracy ≥ 0.70, unsupported_mechanism_rate ≤ 10% |
| **5. Tranche answerability** | 2 sem | AnswerabilityStructurer (false_premise + unanswerable), correction d'abord du schéma gold-set v4 (cf bug Pearson -0.94) | decision_accuracy ≥ 0.80, negative_evidence_recall ≥ 0.65, false_rejection_rate ≤ 10% |
| **6. Verifier cascade complet** | 2 sem | Channel 2 NLI ciblé multilingue + bake-off A/B/C juges si Pearson juge encore < 0.7 après correction schéma | faithfulness +5pp + regen rate -50% + delta FR-EN ≤ 5pp |

**Total : 15-19 semaines** (3.5-4.5 mois). Plus long que l'ADR initial V4 (18-23 sem mais avec sprints S0.5/S1/S2/S3 différents). Le delta vient de l'investissement dans les gold-sets d'atomes (obligatoire pour mesurer F1).

---

## 6. Hypothèses à valider (non démontrées)

Reformulation explicite des claims projetés en hypothèses, comme demandé par la charte anti-V2 (« toute claim de gain mesurée AVANT annonce ») :

- **HFF1** : F1 extraction de faits sur Qwen2.5-72B (DeepInfra, modèle effectif Sprint S0) ≥ 0.70 par type. Sur Qwen-14B-AWQ (vLLM EC2 si attaché) probablement plus bas. **Gate** : mesure obligatoire avant tranche 1.
- **HFF2** : Composer borné au JSON ne dégrade pas la fluidité prose vs synthesis libre. **Gate** : eval humain sur 50 réponses tranche 1.
- **HFF3** : Gates par type atteignables (item_recall ≥ 0.65, fact_tuple_f1 ≥ 0.75, etc.) avec architecture facts-first. À mesurer tranche 1.
- **HFF4** : Latences cibles atteignables (list p50 ≤ 23s, p95 ≤ 35s) malgré l'ajout de stages. À mesurer tranche 1.
- **HFF5** : Couverture types ≥ 95% sur panel stress-test multi-domaines. À mesurer après construction panel.

**Si HFF1 ou HFF3 est réfutée tranche 1** → réviser les schémas, possiblement simplifier vers EAV universel sur certains types.
**Si HFF5 < 95%** → ajouter type ou étendre via Domain Pack.

---

## 7. Charte anti-V2 maintenue

Invariants préservés :

| Invariant | Application Facts-First |
|-----------|------------------------|
| Aucun listing métier hardcodé dans le pipeline | Relations comparison / change_type temporal sont en core minimal universel + extension Domain Pack. Pas de regex métier. |
| Décompositions sémantiques par Domain Pack uniquement | Idem. Les types métiers (procédural, scope-applicability, ...) passent par Domain Pack. |
| Max 5 règles dans Decision Gate | Repair policy = 4 règles (identifier mismatch / missing item / unsupported mechanism / unsupported relation) + 1 fallback déterministe. ✅ |
| Max 50 lignes par prompt synthesis | Composer prompt = ~30 lignes. Structurer prompts = ~40 lignes par type. ✅ |
| Toute nouvelle métrique justifiée par failure mode observé | item_recall (set_list 0.207), exact_match (factual_correctness 0.37), causal_step_f1 (causal_why -15pp régression S0). Tous justifiés. ✅ |
| Toute claim de gain mesurée AVANT annonce | HFF1-HFF5 reformulés en hypothèses. ✅ |
| Tout swap de modèle = bake-off A/B/C sur gold-set | Bake-off juge LLM (Llama-3.3-70B vs Qwen-72B vs Selene-1-Mini-8B) reporté tranche 6 après correction schéma gold-set false_premise/unanswerable. ✅ |
| Pipeline shippable à tout moment | V3 reste actif sur types non-migrés. Tranches verticales = pas d'état intermédiaire instable. ✅ |
| Multi-langue par construction | Tous schémas et prompts FR/EN. Schéma EAV universel pour fallback hors-types domain-agnostic. ✅ |

---

## 8. Risques et mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| F1 extraction < 0.70 sur Qwen-72B (HFF1 réfutée) | Moyenne | Élevé | Si tranche 1 mesure F1 < 0.70 → simplifier schémas (moins de qualifiers), tester routing 14B/72B selon difficulté du document |
| Composer borné dégrade fluidité prose (HFF2 réfutée) | Faible | Moyen | Eval humain obligatoire sur 50 réponses tranche 1. Si dégradation visible → relâcher contraintes mais garder support_ids obligatoire |
| Couverture types < 95% sur stress-test multi-domaines (HFF5 réfutée) | Moyenne | Élevé | Stratégie d'extension Domain Pack documentée. EAV universel comme filet de sécurité non-dégradant |
| Latence p95 > 40s tranche 1 (HFF4 réfutée) | Moyenne | Moyen | Cache du QuestionAnalyzer (questions similaires), Structurer parallélisable sur claims indépendantes |
| Gold-set d'atomes annoté trop coûteux (250+ atomes par type × 6 types = 1500+) | Élevée | Moyen | Bootstrap LLM auto + review Claude (déjà éprouvé sur gold-set v4) + sanity-check Fred sur 10 atomes diversifiés |
| Regression V3 sur types non-migrés pendant tranches 1-5 | Faible | Élevé | Gate « zéro régression V3 » sur chaque tranche. Feature flag par type pour rollback rapide. |
| Variance LLM-judge ±5-8pp masque les gains tranche-à-tranche | Confirmée | Moyen | Comparer toujours sur 2-3 runs. Préférer structured metrics (déterministes) ou factual_correctness (reference-based) pour les gates. |

---

## 9. Ce que cet ADR remplace

- **ADR_OSMOSIS_V4_ARCHITECTURE.md sprints S0.5/S1/S2/S3** : SUPERSEDED par les tranches 1-6 ci-dessus
- **Décisions D2 verifier cascade dans S1** : reportée à tranche 6
- **Décision D3 Evidence Structurer conditionnel hard routes** : SUPERSEDED — Structurer est universel, pas conditionnel
- **Décision D5 Question Router 4 types démarrage** : SUPERSEDED — 6 types reconnus + dispatch hors-types via EAV fallback
- **Décision D7 régen phrase-level** : reportée à tranche 6 (verifier cascade) ; entretemps regen V3 conservé sur types non-migrés

L'ADR_OSMOSIS_V4_ARCHITECTURE reste valide pour : décisions D11 gold-set humain (étendu ici), D12 charte anti-V2 (maintenue), D13 gates quantifiés (maintenus).

---

## 10. Action immédiate next session

**Étape 0 (BLOQUANT, NEW post-review ChatGPT)** : Verrouiller les contrats avant tout code
1. **Geler le schéma Structured Evidence Package commun** (D-FF9) — un seul fichier `schemas/facts_first_v1_common.json` validé Fred + relu LLM tiers
2. **Geler le contrat Domain Pack extension** (D-FF10) — format YAML + règle `maps_to` core minimal
3. **Documenter le mode EAV abstention** (D-FF11) — disclaimer explicite, pas généraliste
4. **Cadrer le panel stress-test** (D-FF12) — couverture typologique uniquement, pas qualité

Sans cette étape 0 : risque de devoir refaire les fondations à tranche 3 (temporal/comparison) — ChatGPT review 2026-05-06 l'a flaggé comme **réserve forte**.

**Étape 1 (CH-41.0 — pré-requis Tranche 1)** :
1. **Construire panel stress-test 100q multi-domaines** (médical, juridique, software docs, RH, produit) pour valider HFF5 (couverture types)
2. **Enrichir gold-set v4 list** de 20 → 50 questions (+ 250 atomes annotés humainement)
3. **Corriger schéma gold-set v4 false_premise/unanswerable** (signaux dédiés multilingues domain-agnostic) — débloquer Pearson juge avant tranche 6

**Étape 2 (CH-41.1 → CH-41.4 — Tranche list)** :
- Implémentation contre les contrats figés en étape 0
- Bench dédié + ablation
- Gate item_f1 ≥ 0.70 / item_recall ≥ 0.65 / source_accuracy ≥ 0.80 / p95 ≤ 35s

**Validation Fred (2026-05-06)** : option (a) démarrer pré-requis maintenant + (c) lancer session relecture LLM tiers en parallèle sur ADR_V4_FACTS_FIRST. Décision actée.

---

## Annexe A — Design Structurer V1 cible (référence)

Schémas JSON détaillés par type, prompts d'extraction, orchestration runtime, repair policy, persistance Neo4j : voir réponse ChatGPT 2026-05-06 archivée dans `doc/ongoing/STRUCTURER_V1_DESIGN_REFERENCE.md` (à créer en miroir avec les ajustements §4.1).

## Annexe B — Critique du design Structurer V1 (Claude, 2026-05-06)

Évaluation point-par-point du design ChatGPT, ajustements C1-C8 documentés en §4.1.

---

*Fin ADR_V4_FACTS_FIRST. Status : Proposed, en attente validation Fred pour démarrage pré-requis tranche 1.*
