# V5.1 Bench 143q gold_set_sap_v2 — Rapport

*Template à remplir post-exécution*
*Date : 2026-05-13*
*Modèle : DeepSeek-V3.1 via Together AI*
*Endpoint : POST /api/runtime_v5/answer (async)*

---

## Résumé exécutif

**V5.1 score (Llama-3.3-70B judge)** : **<TBD>**

| Système | Score | Vs cible | Verdict |
|---|---:|---|---|
| **V5.1 prod (cette run)** | **<TBD>** | cible Phase 1 ADR : 0.65-0.70 | <TBD> |
| V5 v2 POC (S0 v2) | 0.631 | baseline à dépasser | — |
| Ceiling LLM v2 (oracle) | 0.606 | plafond informationnel | — |
| V5 POC v1 (30q hard Fred) | 0.737 | corpus différent | — |
| V4.2 (30q hard Fred) | 0.333 | RAG cassé | — |
| EKX (30q hard Fred) | 0.858 | proprietary SAP | — |

---

## 1. Conditions de run

- **Architecture** : ReasoningAgentV51 (cf S4 intégration)
- **Tools** : 9 public (6 POC + 3 V2 S3.4) + 1 experimental (list_versions)
- **LLM** : DeepSeek-V3.1 via Together AI (charte OSMOSIS)
- **Judge** : Llama-3.3-70B-Instruct via DeepInfra
- **DSG** : corpus SAP migré 38 docs / 6905 sections en Neo4j V5 (S1)
- **Verifier** : NoOpVerifier (bake-off S7.7 différé)
- **Cheap path** : non activé (S4.5 différé)

## 2. Métriques pipeline (objectives, sans LLM-judge)

| Métrique | Valeur | Cible ADR V1.5 |
|---|---:|---|
| Completed | <X>/143 (<X>%) | n/a |
| Failed | <X>/143 | <5% |
| Latence avg | <X>s | p50 ≤25s |
| Latence median | <X>s | ≤25s |
| Latence p95 | <X>s | ≤60s |
| Iterations avg | <X> | sous hard_cap 12 |
| Tool calls avg | <X> | sous hard_cap 40 |
| Retrieved chars avg | <X> | sous hard_cap 120k |
| Output tokens avg | <X> | sous hard_cap 8k |
| Citations rate | <X>% | ≥80% cible |
| Phantom tool_call rate | <X>% | <5% acceptable |
| Stop "concluded" rate | <X>% | (élevé = bon : agent finit naturellement) |

## 3. Per-shape stats

| Shape | n | Score | Latence | Citations | Concluded |
|---|---:|---:|---:|---:|---:|
| factual (n=50) | | | | | |
| comparison (n=28) | | | | | |
| multi_hop (n=23) | | | | | |
| contextual (n=9) | | | | | |
| false_premise (n=6) | | | | | |
| causal (n=6) | | | | | |
| negation (n=6) | | | | | |
| listing (n=6) | | | | | |
| lifecycle (n=3) | | | | | |
| unanswerable (n=3) | | | | | |
| quantitative (n=3) | | | | | |

## 4. Distribution scores judge

- 1.0 (parfait) : <X>/<N> (<X>%)
- 0.5 (partiel)  : <X>/<N> (<X>%)
- 0.0 (raté)    : <X>/<N> (<X>%)

## 5. Insights majeurs

### 5.1 V5.1 vs V5 POC v2 (apples-to-apples)
- <TBD post-bench>

### 5.2 Shapes où V5.1 excelle
- <TBD>

### 5.3 Shapes où V5.1 stagne
- <TBD>

### 5.4 Anomalies observées
- <TBD : phantoms, hallucinations, timeouts, etc.>

---

## 6. Verdict + prochaines actions

**GO Phase 2 si** :
- V5.1 score ≥ V5 POC v2 (0.631) — confirmation non-régression
- Phantom rate < 5%
- Aucun shape catastrophique (<0.30)

**Actions immédiates si OK** :
- S7.7 exécution réelle (HHEM-2.1 wrap + bake-off) — verifier production
- S3.5 exécution réelle (handlers quantitatifs) — combler gap 0.57
- S2.0 bench Docling vs SmolDocling

**Actions si NO-GO** :
- Audit failures par shape
- Re-tester avec budget shape augmenté
- Investiguer phantom tool_call si encore présent
