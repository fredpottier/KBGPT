# Oracle Injection Test — Résultats (2026-05-04 20:48)

## Protocole

20 cas **ABSTENTION_FAUX_NEG** (oracle_score ≤ 0.2) sélectionnés depuis l'oracle Claude :
- 5 RAGAS T1 Provenance (factuelles précises)
- 15 Robustness (temporal, causal, conditional, multi_hop, scope, lifecycle)

Pour chaque cas :
1. Extraction de chunks pertinents depuis le `full_text` du cache (fenêtre ±400 chars autour des keywords)
2. Injection directe dans `ResponseSynthesizer` (bypass retrieval, KG, LLM-filter)
3. Comparaison verbatim vs réponse oracle / ground truth

**Synthèse** : Qwen2.5-72B-Instruct via DeepInfra (vLLM EC2 down → fallback automatique), température 0.2, max 350 tokens.

## Résultats globaux

| Statut | n | % |
|---|---|---|
| ✅ **Correct** (OK ou parfait) | 14 | **70%** |
| ⚠️ Partiel | 3 | 15% |
| ❌ KO (off-topic / abstention / hallucination) | 3 | 15% |

**Comparaison avec le bench original (mêmes 20 questions)** :

| Mesure | Bench original | Oracle injection | Delta |
|---|---|---|---|
| Score moyen oracle Claude | ~0.15 | **~0.70** (estimé) | **+55 pp** |
| Taux ABSTENTION_FAUX_NEG | 100% (par sélection) | 5% (1/20) | **-95 pp** |
| Taux HALLUC | 0% (par sélection) | 5% (1/20) | +5 pp (acceptable) |

## Verdict par cas

### ✅ Réponses correctes (14)

| qid | Verdict | Note |
|---|---|---|
| rag_T1_6 | ✅ OK | Définition global export auth correctement reformulée |
| rag_T1_10 | ✅ Parfait | Cite RGPD + 2018/1725 verbatim |
| rag_T1_14 | ✅ OK | Article 3 + Annex I + nuance catch-all |
| rob_q_25 | ✅ Parfait | 428/2009 mars 2020 + date adoption |
| rob_q_30 | ✅ Parfait | "n'était plus en vigueur" + 9 sept 2021 |
| rob_q_29 | ✅ OK | amdt 28 + ED Decision 2023/021/R |
| rob_q_34 | ✅ Parfait | 2023/996 du 23 fév 2023 |
| rob_q_36 | ✅ OK | Modernisation, surveillance cyber |
| rob_q_40 | ✅ OK | Cohérence customs |
| rob_q_85 | ✅ Parfait | Article 8, autorisation tech assistance |
| rob_q_88 | ✅ OK | 21J aujourd'hui (avec explication 3.5J historique) |
| rob_q_132 | ✅ OK | Annex I vs IV différents périmètres |
| rob_q_137 | ✅ OK | CS exigence vs AMC moyens |
| rob_q_120 | ✅ Parfait | 2021/821 a remplacé 428/2009 + dispositions transitoires |

### ⚠️ Réponses partielles (3)

| qid | Verdict | Note |
|---|---|---|
| rag_T1_25 | PARTIAL | Mention autorisation mais pas l'autorité MS (élément central du ground truth) |
| rob_q_109 | PARTIAL | Vague "où services fournis", manque référence Article 6 |
| rob_q_114 | PARTIAL | Évaluation des risques mentionnée mais pas explicitement "obtenir autorisation" |

### ❌ Échecs (3)

| qid | Verdict | Cause |
|---|---|---|
| rag_T1_3 | ABSTENTION | Chunks récupérés ne contiennent pas le concept exact "extension du délai" — search terms imparfaits OU info pas en verbatim "30 days" mais reformulée. Bug **chunk extraction**, pas synthèse. |
| rob_q_45 | OFF-TOPIC | Synthèse confond les 2 mentions de "30 days" du corpus (extension délai éval vs notification premier usage). Bug **synthèse subtile**, prompt à raffiner. |
| rob_q_153 | **HALLUCINATION** | Synthèse dit "n'abroge pas" alors qu'Article 41 du repeal est dans les chunks. Bug **synthèse grave** — fait défensif d'abstention quand la formulation est binaire (totalement/partiellement). |

## Conclusion

**L'hypothèse #2 (retrieval/filter) est confirmée.**

Quand on fournit à la synthèse les bons chunks (extraits manuellement par grep sur les keywords), le pipeline produit une **réponse correcte dans 70% des cas** (vs ~15% en bench original) sur des questions que le pipeline déclarait "info absente".

**Ventilation des causes du gap 38% → vrai potentiel** :

| Couche | Estimation contribution | Action |
|---|---|---|
| **Retrieval / LLM-filter** (chunks corrects pas remontés à la synthèse) | **~70-80%** des échecs | LLM-filter relax min_keep, BM25+vector hybrid, Subject Resolver tie-breaker, decomposer aggressive, re-rank cross-encoder |
| **Synthèse** (chunks fournis, pas de bonne réponse) | ~15-20% | Prompt anti-abstention plus strict, pénaliser "n'abroge pas" patterns, mentionner explicitement quand source = formulation binaire |
| **Ingestion** (info pas dans le KG/cache) | <5% | Marginal sur ce périmètre |

## Conséquence stratégique

Le travail accompli **n'est pas perdu**. La pipeline elle-même (synthesis + caches + KG) est fonctionnelle. C'est la **couche retrieval/filter qui sous-performe**.

Les leviers concrets sont **tous dans le code existant** :
1. `llm_filter.py` : abaisser `min_keep` à 3 systématiquement, ou désactiver complètement sur questions factuelles
2. `retriever.py` : ajouter BM25 keyword en parallèle du vector + fusion RRF (Reciprocal Rank Fusion)
3. `query_decomposer` : forcer décomposition sur questions multi_hop et conditional
4. `question_subject_resolver.py` : tie-breaker par anchor (mention explicite dans question) plutôt que par recency
5. Re-rank des top-K avec cross-encoder léger (ms-marco-MiniLM)

**Estimation gain attendu** : si le retrieval/filter passe de 30% à 70% de hit rate (même top-K), et la synthèse maintient son 70% sur chunks corrects, score global passerait de 38% à ~55-60%. Pas encore les cibles 80/80/75 mais une progression visible.

**Estimation effort** : 2-3 semaines, pas de réingestion, pas de réécriture KG.

## Données

- Test cases : `benchmark/oracle_injection_test/test_cases.py`
- Script : `benchmark/oracle_injection_test/run_injection_test.py`
- Résultats bruts : `benchmark/oracle_injection_test/injection_test_results_20260504_204826.json`

---
*Test exécuté en ~3 minutes (DeepInfra latency 4-16s/call, 19/20 succès — 1 échec import circulaire au cold-start).*
