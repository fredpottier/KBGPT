# Post-bench A3.4-bis — Evaluator gate GA3-2 (2026-05-21)

**Status FINAL** : ✓ Gate ≥85% **ATTEINT** après amendement ADR §2.4.bis (Option A).
- Fallback déterministe : **100% (38/38)** sur 3 classes
- LIVE LLM (DeepSeek-V3.1) : **89.5% (34/38)** sur 3 classes

**Décision actée** : `INCORRECT` est un état terminal post-Synthesize, pas un verdict
Evaluate. L'ADR §2.4 a été amendé (§2.4.bis), les few-shot examples mis à jour
(4 examples au lieu de 5), et le system prompt révisé pour interdire explicitement
au LLM d'émettre INCORRECT.

**Découverte secondaire** : le fallback déterministe reste STRICTEMENT meilleur
que le LIVE LLM sur les 38 cas (100% vs 89.5%). Le LLM hésite sur 4 cas
INSUFFICIENT_EVIDENCE (préfère AMBIGUOUS). Implication A3.7 : runtime peut
court-circuiter le LLM pour les cas dont le fallback est confiant.

---

## 1. Résultats bruts

### 1.1 Mode fallback déterministe (LLM down → règles ADR §3.2 strictes)

| Métrique | Valeur |
|---|---|
| Accuracy globale | **76.0% (38/50)** |
| Gate GA3-2 ≥85% | ✗ FAIL |
| CORRECT | 100% (12/12) |
| AMBIGUOUS | 100% (13/13) |
| INCORRECT | **0% (0/12)** |
| INSUFFICIENT_EVIDENCE | 100% (13/13) |

**Lecture** : sur les 3 classes détectables structurellement, le fallback déterministe
atteint **100% (38/38)**. Les 12 erreurs sont toutes sur INCORRECT, classées CORRECT
par défaut.

### 1.2 Mode LIVE LLM (DeepSeek-V3.1 / Qwen3-235B via DeepInfra)

| Métrique | Valeur |
|---|---|
| Accuracy globale | **68.0% (34/50)** |
| Gate GA3-2 ≥85% | ✗ FAIL |
| CORRECT | 83.3% (10/12) — 2 fails edge (multi-tool aggregation, hard cap iter=2) |
| AMBIGUOUS | 100% (13/13) |
| INCORRECT | **0% (0/12)** |
| INSUFFICIENT_EVIDENCE | 84.6% (11/13) — 2 fails edge |

**Lecture** : le LLM PERD 8pp vs fallback déterministe. Régression principalement
sur les cas CORRECT edge (multi-coverage agrégation, hard-cap iteration=2) et 2
INSUFFICIENT que le LLM hésite à confirmer.

### 1.3 Matrice de confusion LIVE (rows=expected, cols=actual)

```
expected/actual         CORRECT  AMBIGUOUS  INCORRECT  INSUFFICIENT
CORRECT                    10         2          0           0
AMBIGUOUS                   0        13          0           0
INCORRECT                  11         1          0           0   ← TOTAL FAIL
INSUFFICIENT_EVIDENCE       0         2          0          11
```

---

## 2. Cause racine — limitation architecturale

**Constat** : INCORRECT à 0% dans les DEUX modes (fallback ET LLM).

`EvaluateInput` ne contient **que des signaux structurels** (cf §2.4 ADR) :
- Counts (`n_claims`, `n_sections`, `n_conflict_pendings`)
- Coverage signal par tool (`empty` / `partial` / `full`)
- Errors par tool
- `parse_confidence`, `iteration`

Il ne contient **JAMAIS** :
- Le texte verbatim des claims retournés
- Le contenu sémantique des sections
- La comparaison "subject demandé vs subject des claims trouvés"

Or, les 12 cas INCORRECT du gold-set exigent tous une compréhension **sémantique**
du contenu :
- "Results pertain to wrong subject (LLM-only detectable)"
- "Tool returned irrelevant claims (subject mismatch)"
- "Contradictory claims without ConflictPending detected"
- "Lifecycle trace returns unrelated entities"

**Le LLM Evaluate ne peut PAS distinguer "3 claims pertinents" de "3 claims hors
sujet" si on ne lui montre que les counts**. Il voit `coverage=full` et conclut
CORRECT — exactement comme le fallback.

C'est une limitation de **scope du module Evaluate**, pas d'implémentation.

---

## 3. Options de résolution

### Option A — Réviser l'ADR : INCORRECT déléguée au Synthesize/GroundingVerifier

**Principe** : reconnaître que `INCORRECT` n'est PAS détectable au niveau Evaluate
sans contenu textuel. Déplacer la détection sémantique vers :
1. **Synthesize** (LLM #3) : voit le texte verbatim des claims, peut détecter
   subject mismatch / contradiction sans CP.
2. **GroundingVerifier** (CH-52.8 déjà livré, NLI claim-vs-claim) : peut détecter
   contradictions sémantiques entre claims.

**Mécanique** :
- Evaluate retourne 3 verdicts structurellement détectables :
  `CORRECT / AMBIGUOUS / INSUFFICIENT_EVIDENCE`.
- Synthesize peut **rétrograder** un verdict CORRECT vers INCORRECT s'il détecte
  sémantiquement que l'evidence ne supporte pas la question (et fallback Qdrant
  TEXT_ONLY immédiat comme spec ADR §2.4).
- Renommer `Verdict` → `Verdict` à 3 classes initiales + état terminal `INCORRECT`
  produit en aval.

**Gate GA3-2 recalibré** : ≥85% sur 38 cas (12 CORRECT + 13 AMBIGUOUS + 13 INSUFFICIENT).
- Fallback actuel : **100% (38/38)** ✓
- LIVE LLM actuel : **89.5% (34/38)** ✓

**Coût** : amendement ADR §2.4 (P0) + adaptation runtime_v6 endpoint (A3.7) pour
intégrer rétrogradation Synthesize.

### Option B — Élargir EvaluateInput avec snippets textuels

**Principe** : injecter `claim_verbatim` (50-200 chars) pour les claims retournés,
permettant au LLM Evaluate de juger la pertinence sémantique.

**Mécanique** :
- `ToolResult.claims[].text_excerpt: Optional[str]` (déjà dans ClaimSummary via
  `extra=allow`).
- Execute.py truncate les claims à 200 chars + injecte dans `ClaimSummary`.
- User prompt Evaluate inclut les top-3 verbatims par sub_goal.

**Coût** :
- Increase prompt tokens 200-500 → 800-1500 (×2-3 latence + coût).
- Pas garanti que le LLM atteigne 85% sur cas edge (subject mismatch reste
  difficile sans dictionnaire d'équivalences).
- Re-implémenter A3.3 Execute pour inclure verbatim → tests + commit.

**Gain estimé** : +5 à +12pp sur INCORRECT (mais probablement insuffisant pour
atteindre 85% global, vu le score actuel sur cas edge).

### Option C — Garder l'architecture, recalibrer le gold-set

**Principe** : reconnaître que mes 12 cas INCORRECT exigeaient des signaux
non-structurels qui ne devraient pas être labellisés INCORRECT au niveau Evaluate.
Les **remplacer** par des cas où INCORRECT est détectable structurellement :
- Nombreux `:ConflictPending` non-résolus sur sub_goal P1 (signal de divergence)
- Iter=2 finalisé avec partial coverage uniquement (re-plan échoué)
- Confidence très basse sur claims retournés (`<0.4`)

**Coût** : 1h pour réécrire 12 cas du gold-set + re-bench.

**Risque** : on tordrait la définition d'INCORRECT pour qu'elle colle aux signaux
structurels disponibles, perdant la pureté ADR §2.4. Risque d'overfit au gold-set.

---

## 4. Recommandation

**Option A** — révision ADR.

Raisons :
1. **Honnête** : le bench A3.4-bis a révélé une limitation architecturale réelle.
   L'ignorer ou la "tordre" via Option B/C masquerait le vrai problème.
2. **Aligné avec VISION §4.5** : `mode ∈ REASONED / ANCHORED / TEXT_ONLY / ABSTENTION`.
   Le mode TEXT_ONLY (fallback Qdrant immédiat = ce que produit INCORRECT) est un
   verdict de **Synthesize**, pas d'Evaluate.
3. **Économe** : le fallback déterministe atteint 100% sur 3 classes — le LLM
   apporte +0 vs fallback dans ce périmètre. Question ouverte : faut-il GARDER
   le LLM Evaluate pour de l'AMBIGUOUS plus fin ? Bench A3.8 final mesurera.
4. **Découplage** : Synthesize + GroundingVerifier (CH-52.8) ont déjà vu le texte
   des claims et NLI. Ils sont bien placés pour détecter contradictions
   sémantiques. L'Evaluate devient un router lightweight basé signaux.

**Conséquences pour la suite** :
- Amendement ADR §2.4 → 3 verdicts initiaux + état terminal INCORRECT post-Synthesize.
- A3.5 (Synthesize) doit inclure la logique rétrograde CORRECT → INCORRECT si
  GroundingVerifier détecte contradiction non-CP.
- A3.4 module evaluate.py **conservé tel quel** — sa logique 3-classes est validée
  à 89.5% par le LIVE bench, 100% par fallback. Aucun changement de code.
- Gold-set existant gardé pour bench régression (gate recalibré sur 38 cas), mais
  les 12 INCORRECT documentés comme "hors-scope Evaluate, à valider via A3.5/A3.7
  bench end-to-end".

---

## 5. Files

- Bench script : `app/scripts/bench_a34_evaluator.py`
- Gold set : `tests/runtime_a3/data/evaluate_gold_set.py` (50 cas Python builder)
- Runs persistés :
  - `data/benchmark/a34_evaluator/run_fallback_only_20260521_154542.json`
  - `data/benchmark/a34_evaluator/run_live_llm_20260521_154953.json`

## 6. Décision finale (2026-05-21)

**Option A appliquée** (user confirmation).

Changements :
- `doc/ongoing/adr/ADR_PARSE_EVALUATE_RUNTIME.md` §2.4 + nouveau §2.4.bis : Verdict
  réduit à 3 classes au niveau Evaluate. INCORRECT = état terminal post-Synthesize.
- `src/knowbase/runtime_a3/prompts/evaluate_examples.json` : 5 → 4 few-shots
  (suppression INCORRECT).
- `src/knowbase/runtime_a3/evaluate.py` : system prompt revu, mention explicite
  "NEVER emit INCORRECT — reserved for downstream Synthesize/GroundingVerifier".
- `app/scripts/bench_a34_evaluator.py` : compute_metrics retourne désormais
  `accuracy_3_class` (gate effectif) en plus de `accuracy` legacy.
- `tests/runtime_a3/test_evaluate.py` : test `test_examples_load` adapté à 4
  examples + assertion qu'INCORRECT n'apparaît pas dans les few-shots.

Tests post-amendement : **154 passing**, aucune régression.

## 7. Résultats finaux gate GA3-2

### Mode fallback déterministe
- Accuracy 50 cas (legacy diagnostic) : 76% (38/50)
- **Accuracy 38 cas (gate 3-class) : 100% (38/38)**
- Gate GA3-2 ≥85% : **✓ PASS**

### Mode LIVE LLM (DeepSeek-V3.1 via DeepInfra)
- Accuracy 50 cas (legacy diagnostic) : 68% (34/50)
- **Accuracy 38 cas (gate 3-class) : 89.5% (34/38)**
- Gate GA3-2 ≥85% : **✓ PASS**
- Per class : CORRECT 100%, AMBIGUOUS 100%, INSUFFICIENT 69.2% (4 fails → AMBIGUOUS)

### Note pour A3.7 intégration runtime
Le fallback déterministe (100%) surclasse le LIVE LLM (89.5%) sur ce gold-set.
À considérer en A3.7 : court-circuit LLM si fallback confiant (e.g., tous full
ou tous empty), invocation LLM uniquement sur cas mixed/ambigus où sa nuance
sémantique peut apporter.
