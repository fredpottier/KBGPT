# CH-49 Phase 2 — Livraison operators Cap2.B/C/D

**Date** : 2026-05-10
**Statut** : 🟡 Phase 2 code livré, bench non-régression en cours (P2.M)
**Référence ADR** : `2026-05-10_CH-49_ADR_PIPELINE_V4_2_ARCHITECTURE_CIBLE_v1.md` v1.1

---

## Composants livrés Phase 2

### 3 nouveaux operators Layer 1

| Operator | Fichier | Pattern adressé | Trigger smoke validation |
|---|---|---|---|
| **Cap2.B** lifecycle_resolution | `runtime_v4_2/operators/lifecycle_resolution.py` | "qui a remplacé X" / SUPERSEDES / EVOLVES_FROM | 4/5 ✅ smoke (1 KG-only) |
| **Cap2.C** kg_query | `runtime_v4_2/operators/kg_query.py` | "combien de X" / "list active" / "supersession chain" | COUNT 2/2 ✅, LIST_BY_STATUS 0/2 (intent variabilité) |
| **Cap2.D** set_reasoning | `runtime_v4_2/operators/set_reasoning.py` | "qu'est-ce qui n'est PAS X" / exemptions / exclusions | 3/3 ✅ négations, 2/2 non-négation correctement écartées |

### Pipeline runtime_v4_2

Cascade d'escalation Layer 1 (par ordre dans pipeline.py) :
```
question
  → 0.A temporal_active_version  (Cap2.A — POC, déjà livré P1)
  → 0.B lifecycle_resolution      (Cap2.B — Phase 2)
  → 0.C kg_query                  (Cap2.C — Phase 2)
  → 0.D set_reasoning             (Cap2.D — Phase 2)
  → Layer 0 cheap_certainty       (extraction Llama-Turbo + Q↔A Verifier)
```

Chaque operator est testé séquentiellement. Le premier qui retourne `decision=ANSWER` répond. Les autres reçoivent NOT_APPLICABLE ou ABSTAIN avec fallback explicite.

---

## Matrix priority multi-tag (P2.M v1)

**Approche v1 (ordre = priorité)** : la cascade actuelle est suffisante car les intents detection sémantiques sont mutuellement exclusifs dans la majorité des cas observés. Les chevauchements (ex : Cap2.B `chain` vs Cap2.C `CHAIN`) résolvent bien sur le 1er triggering.

**Justification de l'ordre A → B → C → D** :
1. **Cap2.A temporal_active** : critère temporel précis (date X) → spécificité maximale
2. **Cap2.B lifecycle_resolution** : relation explicite (replaced/superseded by) → spécificité haute
3. **Cap2.C kg_query** : query structurelle (count/list_by_status/chain) → spécificité moyenne
4. **Cap2.D set_reasoning** : négation/exclusion → utilise retrieval Qdrant + LLM filter, plus permissif → en dernier

**Approche v2 (multi-label scoring) — différée** : selon ADR Amendment 8, un scoring multi-dimensionnel (intent_scores par operator) sera implémenté Phase 3 si la v1 montre des conflits réels en production.

---

## Charte respectée

✅ **Domain-agnostic strict** : tous les prompts INTENT_DETECTION utilisent placeholders abstraits (`<DOC_X>`, `<STATUS>`, `<REL>`, `<X>`) — JAMAIS d'identifiers du corpus actuel
✅ **LLM = aiguilleur ou rédacteur, jamais operator** : le raisonnement structurel (Cypher, set ops, traversée KG) est en code Python déterministe
✅ **Anti-biais auto-juge** : Q↔A Verifier DeepSeek-V3.1 ≠ Composer Llama-Turbo (cohérence Phase 1)
✅ **Pattern fallback uniforme** : primary → fallback_1 (Qdrant resolver) → fallback_2 (multi-candidate) → escalate Layer 2 (Phase 3)

### Faute corrigée pendant Phase 2

Le 1er prompt INTENT_DETECTION_PROMPT de Cap2.B contenait 4 exemples avec identifiers du corpus actuel (`428/2009`, `2021/821`, `2009/125`, `CS-25`) — viole la charte. Corrigé immédiatement après audit Fred avec placeholders abstraits.

---

## Constat KG actuel

Le KG de production contient seulement **4 LIFECYCLE_RELATION** (1 SUPERSEDES + 3 EVOLVES_FROM, toutes sur le pattern dualuse 2021/821 → 428/2009). Cela limite naturellement le nombre de questions où Cap2.B et Cap2.C peuvent briller dans les benchmarks actuels.

**Conséquence prévisible** : les bench Robust 120q ne montreront pas de gain spectaculaire de Cap2.B/C parce que les questions du bench ciblent surtout des contenus factuels CS-25 / aerospace, pas des questions structurelles lifecycle. Ce n'est pas un défaut des operators — c'est un constat de couverture KG.

**Test Armand corpus** (CS-25 amendments + 2021/821 + 821 amendments) sera meilleur révélateur de Cap2.B/C grâce à plus de relations.

---

## Composants additionnels

| Fichier | Rôle |
|---|---|
| `app/scripts/smoke_lifecycle_op.py` | Smoke test Cap2.B (5 questions) |
| `app/scripts/smoke_kg_query_op.py` | Smoke test Cap2.C (3 query types + non-applicable) |
| `app/scripts/smoke_set_reasoning_op.py` | Smoke test Cap2.D (5 questions négation/non-négation) |

---

## P2.M — Bench non-régression + correction critique

### Bench Robust 120q comparatif

| Run | score_best | p50 | p95 | L0 | L1 | misroutes |
|---|---:|---:|---:|---:|---:|---:|
| P1 (A only) | 0.867 | 8.6s | 19.9s | 95 | 25 | 3 |
| P2 full (no veto) | 0.861 | 15.4s | 23.1s | 88 | 32 | **5** ❌ |
| **P2 full + veto** | **0.859** | **19.7s** | **37.7s** | **114** | **6** | **0** ✅ |

### Découverte critique (10/05) : verifier veto manquant

L'audit des traces P2 full a révélé que les 4 operators Cap2.X consultaient le Q↔A Verifier **mais retournaient ANSWER quoi qu'il arrive** — bug architectural majeur.

Le verifier détectait correctement les misroutes (`MISALIGNED` confidence 0.9-0.95 sur 12/12 cas observés) mais sa décision était ignorée. Conséquence : 5 questions ont reçu une réponse "techniquement correcte mais hors-cible" :
- false_premise routée Cap2.B (lifecycle) → confirme une fausse prémisse implicitement
- causal_why routée Cap2.B (lifecycle) → ne donne pas l'explication causale
- unanswerable routée Cap2.C (COUNT) → réponse trompeuse
- 2 hypothetical routées Cap2.A (temporal_active) → ne raisonne pas l'hypothèse

### Correction appliquée (commit 10/05)

Refactor `pipeline.py` : pour chacun des 4 operators Cap2.X, si `align.decision == "MISALIGNED"` post-Layer 1 → fallback vers le prochain operator ou Layer 0. Le verifier a maintenant le **dernier mot**.

### Résultats post-correction

- ✅ **0 misroute** confirmé (vs 5 avant)
- ✅ 5/5 misroutes récupérées en Layer 0 (3 score up, 2 score down — net positif)
- ⚠️ **+89% p95 latency** : 19.9s → 37.7s — coût des cascades veto (jusqu'à 4 operators × 3-7s + verifier)
- ⚠️ Layer 1 trigger : 32 → 6 (le veto rejette 26 false-positifs)

### Trade-off accepté

Le verifier veto est **non-négociable pour rester anti-Goodhart** : sans lui, on retourne des réponses techniquement valides mais hors-cible, qui passent le scorer multi-view (sujet partagé) mais trompent l'utilisateur.

L'augmentation de latence sera adressée par les optimisations Phase 3 :
- **Intent detection unifiée** : 1 LLM call qui retourne intent pour TOUS les operators (économise 3-4 calls × 3s = 9-12s)
- **Smart routing en amont** (Phase 3 Cap3 orchestrator) : analyseur qui dispatche directement vers le bon operator

---

## Prochaines étapes

1. **Phase 3.A POC modèle Layer 2** (~2-3j) : DeepSeek vs Claude Sonnet 4.6 vs GPT-4o
2. **Phase 3.B Layer 2 implementation** (~3-4j) : tool registry + agent loop + intent detection unifiée
3. **Phase 4 Cap2.E comparison_contradiction** (~3-4j) : evidence-first cluster + LLM qualifier
