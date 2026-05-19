# S7 — Verifier Bake-off Protocol

*Date : 2026-05-13*
*ADR : V1.5 §3f (CH-52.8.7)*
*Statut : **PRÉPARATION** — exécution sous décisions user*

---

## 0. Contexte

L'ADR §3f impose un **bake-off mesuré** des candidats verifier (vs annonce SOTA).
V5.1 livre l'architecture complète (claim segmenter + NLI interface + thresholds
par shape + answer-level checks + orchestrator). Le **backend NLI réel** reste
à sélectionner via ce bake-off.

**Baseline V5.1 actuelle** : `NoOpVerifier` (toujours SUPPORTED) — safe default
pour ne pas bloquer la mise en route. À remplacer par le winner du bake-off
post-S0.1 (gate ADR).

---

## 1. Candidats à tester

| Modèle | Taille | Source | Pour |
|---|---:|---|---|
| **HHEM-2.1-Open** | 184M | Vectara HF | Default actuel runtime_v3 / baseline réf |
| **HHEM-7B** | 7B | Vectara (mars 2026) | +12pp F1 annoncé vs 2.1, à valider |
| **MiniCheck-770M** | 770M | Liu et al. 2024, HF | Designed grounding, rapide |
| **Patronus Lynx-8B** | 8B | Patronus AI | 128k context, vérifier dispo Together AI |
| **Patronus Glider-3.8B** | 3.8B | Patronus AI (jan 2026) | Parity Lynx 2× moins params |

**Plan B si Lynx non dispo Together AI** : se concentrer sur HHEM-2.1, HHEM-7B
(si dispo HF), MiniCheck, Glider. Le bake-off reste représentatif.

---

## 2. Claim-level set d'évaluation

**Cible** : 80 questions, stratifié par shape :
- 40 SAP (depuis gold_set_sap_v2)
- 30 aerospace (depuis POC-A, gold_set_v4)
- 10 stress (false_premise + unanswerable + contradictory_citations injectées)

**Stratification par shape** (cohérent ADR §3f) :
| Shape | Min n | Note |
|---|---:|---|
| factual | 15 | gros volume, cible cible majoritaire |
| listing | 8 | |
| lifecycle | 8 | |
| causal | 8 | |
| comparison | 8 | |
| false_premise | 8 | shape inverted threshold |
| unanswerable | 8 | shape inverted threshold |
| quantitative | 8 | |
| multi_hop | 9 | rest |

**Format claim-level set** :
```json
{
  "claim_id": "cl_001",
  "question_id": "q_sap_042",
  "answer_shape": "factual",
  "claim_text": "The RTO is 4 hours for production tier.",
  "evidence_text": "...",
  "ground_truth_decision": "supported|contradicted|neutral",
  "expert_annotator": "fred",
  "rationale": "..."
}
```

---

## 3. Métriques + Gate decision

Pour chaque candidat :

**Métriques par shape** :
- Précision (TP / (TP + FP))
- Rappel (TP / (TP + FN))
- F1 = 2 * P * R / (P + R)

**Métriques globales** :
- F1 moyen sur les 8 shapes (égale pondération)
- Latence p50, p95
- Coût $ / 1000 verifications

**Gate Winner** :
- **Critère 1 (qualité)** : F1 moyen ≥ baseline HHEM-2.1 + 5pp
- **Critère 2 (latence)** : p95 ≤ 3s (cohérent ADR §3a latence budget)
- **Critère 3 (coût)** : ≤ 2× coût baseline acceptable si gain qualité ≥ 10pp
- **Critère 4 (inverted shapes)** : F1 ≥ 0.70 sur false_premise + unanswerable

Tie-breaker : MiniCheck > Glider > HHEM-7B > Lynx-8B > HHEM-2.1 (priorité
performance/coût ratio).

---

## 4. Protocole d'exécution

### Phase A — Préparation panel
1. Constituer 80 claims via extraction des réponses V5.1 sur gold_set
2. Annotation manuelle (Fred + 1 reviewer) : decision + rationale
3. Validation split train/test 70/30 (anti-overfit threshold)
4. Persist `data/verifier_bench/claim_set_v1.jsonl`

### Phase B — Implémentation backends
1. HHEM-2.1 : wrapper sentence-transformers existant (déjà installé runtime_v3)
2. HHEM-7B : check dispo HF + wrap si oui
3. MiniCheck-770M : `bespokelabs/Bespoke-MiniCheck-7B` ou variant 770M
4. Lynx-8B : check dispo Together AI / DeepInfra
5. Glider-3.8B : check dispo HF

### Phase C — Exécution
1. Pour chaque candidat, run sur 80 claims
2. Compute scores per shape
3. Compute latency stats (p50, p95)
4. Compute cost estimate

### Phase D — Calibration thresholds
Pour le winner : recalibration Youden's J par shape sur split train (56 claims).
Validation sur split test (24 claims, jamais touché).
Persist `config/verifier_thresholds.yaml` versionné.

### Phase E — Gate decision + ADR addendum
- Document gain F1 / latence / coût vs baseline
- Si tous critères passent → swap NoOpVerifier en winner dans GroundingVerifier
  config default
- Sinon → garder NoOpVerifier + alert OTel verifier_unavailable retryable

---

## 5. Risques + Mitigation

| Risque | Mitigation |
|---|---|
| Lynx-8B non dispo Together AI | Plan B avec 4 candidats au lieu de 5 |
| HHEM-7B non publié HF | Skip, garder 2.1 comme baseline |
| Latence p95 > 3s sur all candidates | Threshold relaxé à 5s temporairement, ré-évaluer post Phase 2 |
| Aucun candidat F1 ≥ baseline + 5pp | Garder HHEM-2.1 actuel + investiguer claim segmentation (peut-être problème en amont) |
| Cross-corpus dérive scores | Bench séparé par corpus + check stability |

---

## 6. Estimation budget

| Étape | Effort | Budget LLM |
|---|---|---|
| Constituer 80 claims annotés | 1 jour Fred + reviewer | $0 |
| Impl 4-5 backends | 0.5j dev | $0 |
| Bench Phase C (5 × 80q × 2 calls) | ~2h | ~$5-10 |
| Calibration Phase D | 0.5j | $0 |
| ADR addendum | 2h | $0 |
| **Total** | **~2.5j dev + 1j annotation** | **~$10** |

---

## 7. Livrables attendus

- ✅ `src/knowbase/runtime_v5/verifier/` complet (35 tests passent)
- ✅ Architecture industrielle : segmenter + backends + thresholds + answer checks + orchestrator
- ⏳ `data/verifier_bench/claim_set_v1.jsonl` (80 claims annotés)
- ⏳ Impl 4-5 VerifierBackend production-grade
- ⏳ `data/verifier_bench/bakeoff_<date>.json` (résultats mesurés)
- ⏳ `config/verifier_thresholds.yaml` calibré
- ⏳ `doc/ongoing/S7_BAKEOFF_RESULTS.md` (winner + gate decision)

---

## 8. Décisions à valider (avant exécution)

### D1 — Constitution panel 80q
- **Option A** : extraire claims des réponses V5.1 existantes (post-bench S0 v2)
  → besoin de run V5.1 sur gold_set_sap_v2 d'abord
- **Option B** : annotation directe sur claims atomiques crafted (manual)
- **Option C** : mix 50/50

### D2 — Inclusion HHEM-7B / Glider-3.8B
Décision conditionnée par disponibilité HF check.

### D3 — Calibration trimestrielle automatique ?
- **Option A** : pipeline scheduled refresh thresholds (post-Phase 1)
- **Option B** : recalibration manuelle on-demand seulement

### D4 — Activation winner par défaut Phase 1 ?
- **Option A** : activer immédiatement post-bake-off (risque qualité non vérifiée)
- **Option B** : shadow mode 2 semaines (winner exécute en parallèle de NoOp, on
  compare décisions sans bloquer la réponse)

---

## 9. Status sprint S7 global

| Sub-sprint | Statut |
|---|---|
| S7.1 Claim segmenter | ✅ |
| S7.2 Verifier backends interface | ✅ (NoOp + Mock + Threshold + HHEM adapter) |
| S7.3 Answer-level consistency checks | ✅ 4 checks |
| S7.4 Thresholds par shape + Youden's J | ✅ |
| S7.5 VerifierFailure typed + retry policy | ✅ |
| S7.6 GroundingVerifier orchestrator | ✅ |
| **S7.7 Bake-off exécution** | **🟡 PREP livré — exécution sous décisions D1-D4** |

Au prochain "enchaine" : décisions D1-D4 puis exécution bake-off, OU bascule
autre sprint (S8 Threat Model, S9 Frontend, branchement HTTP prod).
