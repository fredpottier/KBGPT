# Résumé de la nuit 04/05 → 05/05

## Travail accompli

### Sprint A (Retrieval overhaul) — ✅ TERMINÉ
- A.1 Hybrid BM25+vector RRF
- A.2 LLM-filter bypass factual_value/list/definition/boolean/entity_lookup/relationship/enumeration
- A.3 Subject Resolver anchor tie-breaker
- A.4 Cross-encoder rerank GPU (BGE-v2-m3, 60x speedup)

### Sprint B (Synthèse anti-hallucination) — ✅ TERMINÉ
- B.1 Faithfulness judge cross-lingual prompt
- B.2 Premise validator cross-lingual prompt
- B.3 Skip-regen avec premise NEUTRAL + initial cite docs
- B.4 Hallucination guard lexical (regulation_id, dates, value+unit, NPA, CS, amdt)

### Sprint C (Régulatoire guardrails) — ✅ C.1 TERMINÉ
- C.1 Lifecycle filter sur synthèse (DEPRECATED demote sur current intent, 9/9 tests)
- C.2 Date→version index — non démarré (pertinence faible, ROI vu)
- C.3 Hallucination ensemble — couvert par B.4 (lexical) — version LLM remise à plus tard

### Sprint D (Calibration finale) — ✅ D.1 TERMINÉ (à valider)
- D.1 Synthesis prompt v3 — règles 10+11 ajoutées :
  - Détection prémisses fausses quantitatives (60j vs 30j, 50J vs 21J, etc.)
  - "Pourquoi X..." → vérifier X avant de justifier
- D.2-D.4 — non démarrés

## Fichiers modifiés

```
src/knowbase/runtime_v2/retriever.py             # A.1 + A.4 (rerank GPU)
src/knowbase/runtime_v2/llm_filter.py            # A.2 (bypass factual)
src/knowbase/runtime_v2/question_subject_resolver.py  # A.3 (anchor tie-breaker)
src/knowbase/runtime_v2/faithfulness_judge.py    # B.1 (cross-lingual prompt)
src/knowbase/runtime_v2/premise_validator.py     # B.2 (cross-lingual prompt)
src/knowbase/runtime_v2/pipeline.py              # B.3 (skip-regen) + C.1 (lifecycle filter) + B.4 (hallu guard hook)
src/knowbase/runtime_v2/hallucination_guard.py   # B.4 (NEW)
src/knowbase/runtime_v2/lifecycle_filter.py      # C.1 (NEW)
src/knowbase/runtime_v2/synthesis.py             # D.1 (prompt v3)
docker-compose.yml                                # GPU pour knowbase-app (A.4)
benchmark/evaluators/robustness_diagnostic.py    # concurrency=1 default (saturation fix)
```

## Résultats benches vs baseline 04/05

| Bench | Métrique clé | Baseline | Post nuit | Δ |
|---|---|---|---|---|
| **RAGAS** | faithfulness_total | 0.607 | **0.759** | **+15.2pp** ✅✅ |
| RAGAS | faithfulness | 0.590 | 0.677 | +8.7pp ✅ |
| RAGAS | context_relevance | 0.754 | 0.788 | +3.4pp ✅ |
| **Robust** | global (Llama-70B) | 0.455 | **0.495** | **+4.1pp** ✅ |
| Robust | causal_why | 0.433 | **0.742** | **+30.8pp** ✅✅ |
| Robust | multi_hop | 0.408 | 0.600 | +19.2pp ✅ |
| Robust | conditional | 0.207 | 0.336 | +12.9pp ✅ |
| Robust | temporal_evolution | 0.375 | 0.475 | +10.0pp ✅ |
| **Robust** | false_premise (REGRESSION) | 0.637 | 0.508 | **-12.9pp** ❌ |
| Robust | unanswerable | 0.708 | 0.617 | -9.2pp ❌ |
| Robust | negation | 0.640 | 0.560 | -8.0pp ❌ |
| **T2T5** | composite | 0.367 | 0.382 | +1.5pp |
| T2T5 | tension_mentioned | 0.125 | 0.225 | +10.0pp ✅ |
| T2T5 | multi_doc_cited (REGRESSION) | 0.633 | 0.518 | -11.5pp ❌ |

## Ce qui reste à faire au réveil

### 1. Valider D.1 (5 min)

```powershell
docker restart knowbase-app
```

Le prompt synthesis v3 sera chargé. Pour tester rapidement les 6 cas false_premise qui régressaient :

```bash
# Question test : "Pourquoi le délai d'évaluation est-il de 60 jours ?" (vrai = 30j)
curl -s -X POST http://localhost:8000/api/runtime_v2/answer -H "Content-Type: application/json" \
  --data '{"question":"Pourquoi le délai d'\''évaluation d'\''une transaction par les autorités EU est-il de 60 jours dans le règlement 2021/821 ?","top_k_claims":10}'
```

Si la réponse mentionne explicitement la contradiction "60j vs 30j" → D.1 fonctionne.

### 2. Re-bench Robust + RAGAS pour mesurer D.1

```bash
# Solo concurrency=1 pour éviter timeouts
curl -s -X POST http://localhost:8000/api/benchmarks/robustness/run -H "Content-Type: application/json" \
  --data '{"tag":"POST_D1_SYNTH_V3","description":"D.1 synthesis prompt v3 - false premise detection"}'

curl -s -X POST http://localhost:8000/api/benchmarks/ragas/run -H "Content-Type: application/json" \
  --data '{"profile":"standard","tag":"POST_D1_SYNTH_V3","description":"D.1 verify no regression"}'
```

Cible D.1 : récupérer +5 à +10pp sur false_premise / unanswerable / negation sans casser les gains majeurs (causal_why +30.8pp, multi_hop +19.2pp).

### 3. Si D.1 valide → continuer Sprint D (D.2-D.4)

- D.2 Domain Pack hints aerospace_compliance (NPA, ED Decisions)
- D.3 Confidence-based final abstention
- D.4 Re-bench complet final

## Trajectoire vers les cibles

| Bench | Actuel | D.1 estimé | D.1+D.2+D.3 estimé | Cible |
|---|---|---|---|---|
| RAGAS faithfulness_total | 0.759 | 0.78 | **0.80-0.82** | 0.80 ✅ |
| Robust global | 0.495 | 0.55 | **0.60-0.65** | 0.75 ❌ encore loin |
| T2T5 composite | 0.382 | 0.40 | **0.45** | 0.80 ❌ très loin |

**RAGAS à portée de la cible 80% post Sprint D.** Robust et T2T5 nécessitent plus de travail (Sprint E ?).

## Points d'attention

1. **Robust set_list -5.7pp** : régression sur les listes — le rerank GPU favorise pertinence sur diversité multi-doc. À traiter si critique pour le use-case.

2. **T2T5 multi_doc_cited -11.5pp** : même cause que set_list. Trade-off acceptable car la pertinence est plus critique en régulatoire.

3. **Test pipeline solo** = 27s/q. Avec concurrency = 4+, timeout 300s à cause de saturation DeepInfra. Pour production, considérer :
   - vLLM EC2 dédié plutôt que DeepInfra (résoud rate-limit)
   - OU réduire LLM calls par pipeline (faithfulness judge optionnel sur questions courtes ?)
