# Audit régression V3 → V4.2 — Synthèse exhaustive pour analyse externe

**Date** : 2026-05-10
**Statut** : 🔴 **Régression mesurée et confirmée** sur 3 benchs officiels
**Audience** : LLMs externes (ChatGPT-5, Claude Web Opus, Gemini, etc.) pour avis indépendant

---

## TL;DR

Après 5 jours de pivot architectural (V3 → V4 facts-first → V4.1 evidence-grounded reasoning → V4.2 Tiered Pipeline), le système OSMOSIS **régresse de 25% sur le bench Robustness** (170 questions, LLM-judge Llama-3.3-70B Together AI) par rapport à la baseline V3 abandonnée. **22% des questions où V3 répondait correctement reçoivent désormais "réponse non trouvée" en V4.2**.

Ce document détaille les chiffres, les patterns de régression, les hypothèses de cause, et pose des questions ouvertes pour analyse indépendante.

---

## 1. Contexte court — qu'est-ce qu'OSMOSIS

OSMOSIS est un système RAG+KG en environnement régulé (corpus aérospatial : CS-25 EASA + règlements EU dual-use 428/2009 et 2021/821 + délégués). Cible Test Armand (1er client). Architecture combine :

- Vector store Qdrant (claims atomiques + chunks reconstruits)
- Knowledge graph Neo4j (entités, relations LIFECYCLE, contradictions, claims structurées)
- Pipeline runtime qui répond aux questions via retrieval + synthèse LLM

Modèles utilisés (open-source uniquement, exclusion Sonnet/GPT-4o pour coût) :
- Llama-3.3-70B-Instruct-Turbo (Composer/Synthesizer) via Together AI
- DeepSeek-V3.1 (Q↔A Verifier, intent detection) via Together AI
- Llama-3.3-70B (LLM-judge officiel) via DeepInfra

---

## 2. Historique architectural (5 derniers jours)

| Date | Version | Description courte | Robustness score |
|---|---|---|---:|
| 05/05 | **V3_FINAL3** | Pipeline 5 stages "agentic synthesis" + decomposer + HyDE + LLM-filter + cross-encoder rerank | **0.545** ✅ |
| 05/05 | V3_S0_BASELINE | V3 + métriques structurées Sprint S0 | 0.531 |
| 06/05 | **Pivot V4 facts-first** | Décision 3 voix : abandon V3, refonte facts-first par tranches verticales (list, factual, temporal, comparison, causal) | — |
| 07/05 | V4 Tranches 1-5 | QuestionAnalyzer + EvidenceCollector + 5 type-adaptive Structurers + Composers + Channel 1+2 verifiers | (régression -18pp constatée) |
| 08/05 | V4_CH46_POSTOPT | Optimisations latence Phase A+B+C | **0.351** (-36% vs V3) |
| 09/05 | V4_CH48_LLAMA_TURBO | Bake-off Together AI : Llama-3.3-70B-Turbo retenu partout (Composer + Structurer) | **0.403** (-26% vs V3) |
| 10/05 | **V4.2_BASELINE** | Tiered Pipeline (Layer 0 + 5 operators Cap2.A/B/C/D/E + Layer 2 orchestrator + UnifiedIntentRouter + verifier veto) | **0.408** (-25% vs V3) |

**La régression est apparue dès le pivot V4 (06-07/05) et n'a jamais été récupérée**, malgré les chantiers CH-46 (latence), CH-47 (evidence-grounded reasoning), CH-48 (Together AI), CH-49 (Tiered Pipeline livré 10/05).

---

## 3. Architecture V4.2 livrée (état actuel, qui régresse)

### Pipeline en couches d'escalade

```
question
  └─ UnifiedIntentRouter (1 LLM call DeepSeek) → dispatche vers operators applicables
  ├─ Layer 1 : 5 operators déterministes (Cap2.A/B/C/D/E)
  │   ├─ temporal_active_version : Cypher Neo4j sur publication_date
  │   ├─ lifecycle_resolution : Cypher LIFECYCLE_RELATION (SUPERSEDES, EVOLVES_FROM, REAFFIRMS)
  │   ├─ kg_query : COUNT / LIST_BY_STATUS / CHAIN
  │   ├─ set_reasoning : retrieval + LLM filter pour exclusions/négations
  │   └─ comparison_contradiction : cluster déterministe Python par (subject, predicate)
  │       puis LLM qualifier (lifecycle_evolution / scope_difference / genuine_conflict)
  │
  ├─ Layer 0 : Cheap Certainty (si aucun operator ne trigger)
  │   ├─ EvidenceCollector (Qdrant top_k=12 + claims Neo4j)
  │   ├─ Llama-3.3-70B-Turbo : extraction directe avec prompt minimaliste
  │   └─ Q↔A Alignment Verifier (DeepSeek-V3.1) : famille distincte = anti-biais
  │
  └─ Layer 2 : Adaptive Orchestrator (si Layer 0 ABSTAIN/MISALIGNED)
      └─ Agent DeepSeek-V3.1 avec tool_calls (vector_search + 5 operators + extract_answer)
```

### Verifier veto critique
Tout operator Layer 1 OU Layer 0 qui retourne ANSWER passe par le Q↔A Verifier (DeepSeek). Si verdict = `MISALIGNED`, la réponse est **rejetée** et le pipeline cascade vers le prochain layer ou retourne ABSTAIN. Cette logique **anti-Goodhart** est le mécanisme central de l'architecture V4.2.

### Distribution observée sur Robust 170q
- **95%** Layer 0 (cheap certainty)
- 4% Layer 1 (operators ne déclenchent que sur questions très précises)
- 1% Layer 2 visible (verifier rejette les compositions agentic)

### Charte respectée (auditée par grep)
- Domain-agnostic strict : 0 référence corpus dans `runtime_v4_2/`. Tous prompts INTENT avec placeholders abstraits (`<DOC_X>`, `<STATUS>`).
- Pas de modèles propriétaires (Sonnet/GPT-4o).
- LLM = aiguilleur ou rédacteur, jamais operator structurel (Cypher/code Python pour le raisonnement).
- LIFECYCLE_RELATION evidence-locked (déclarations textuelles explicites uniquement → KG actuel a 4 relations).

---

## 4. Résultats des 3 benchs officiels (10/05/2026)

### 4.1 Robustness (170 questions, 10 catégories, LLM-judge Llama-3.3-70B)

| Version | Date | Score global |
|---|---|---:|
| V3_FINAL3 | 05/05 | **0.545** |
| V3_S0_BASELINE | 05/05 | 0.531 |
| V4_CH46_POSTOPT | 08/05 | 0.351 |
| V4_CH48_LLAMA_TURBO | 09/05 | 0.403 |
| **V4.2_BASELINE** | **10/05** | **0.408** |
| **Cible mémoire projet** | | **≥ 0.75** |

### 4.2 T2T5 standard (70 questions, contradictions T2 + cross-doc T5)

| Métrique | V4.2_BASELINE | Cible |
|---|---:|---:|
| both_sides_surfaced (T2) | **0.07** | ≥ 0.80 |
| tension_mentioned (T2) | **0.025** | — |
| both_sources_cited (T2) | **0.25** | — |
| chain_coverage (T5) | **0.185** | ≥ 0.80 |
| multi_doc_cited (T5) | 0.367 | — |
| total_evaluated | 70 (40 T2 + 30 T5) | |

### 4.3 RAGAS standard (80 questions T1+T5, faithfulness/context_relevance/factual_correctness)

| Version | Date | faithfulness | context_relevance | factual_correctness |
|---|---|---:|---:|---:|
| V3_FINAL3 | 05/05 | **0.632** | **0.822** | n/a |
| V3_S0_GOLD | 05/05 | 0.612 | 0.696 | n/a |
| V4_CH46_POSTOPT | 08/05 | 0.580 | 0.733 | 0.256 |
| V4_CH48_LLAMA_TURBO | 09/05 | 0.576 | 0.720 | 0.267 |
| **V4.2_BASELINE** | **10/05** | **ÉCHEC** | **ÉCHEC** | **ÉCHEC** |

**RAGAS V4.2 a complètement échoué silencieusement** :
```
ERROR: No valid samples for RAGAS evaluation
Benchmark completed in 849.9s — OSMOSIS scores: {}
```

**Cause** : runtime_v4_2 ne remonte pas `chunks_used` dans la réponse JSON (décision explicite dans le code : *"On ne réexpose pas les claims internes pour Layer 0"*). RAGAS a besoin de ces contexts pour calculer faithfulness/context_relevance. Sans contexts → 0 sample valide.

---

## 5. Audit question-par-question V3 vs V4.2 (Robustness)

170 questions communes croisées par `question_id`.

### 5.1 Distribution globale

| Cas | Nombre | % |
|---|---:|---:|
| Both OK (V3 ≥ 0.5 ET V4.2 ≥ 0.5) | 57 | 33% |
| Both KO (V3 < 0.5 ET V4.2 < 0.5) | 63 | 37% |
| **Régression** (V3 OK → V4.2 KO) | **37** | **22%** |
| Gain (V3 KO → V4.2 OK) | 13 | 8% |
| **Net** : **-24 questions perdues** | | |

### 5.2 Régressions par catégorie

| Catégorie | Régressions / Total | % |
|---|---:|---:|
| hypothetical | 6/10 | **60%** |
| temporal_evolution | 6/12 | **50%** |
| false_premise | 5/12 | **42%** |
| multi_hop | 5/12 | **42%** |
| lifecycle_vs_conflict | 3/8 | 38% |
| lifecycle_evolves_from | 2/7 | 29% |
| causal_why | 3/12 | 25% |
| lifecycle_supersedes | 1/5 | 20% |
| synthesis_large | 2/12 | 17% |
| conditional | 2/14 | 14% |
| lifecycle_filtering_active | 1/9 | 11% |
| negation | 1/10 | 10% |

Les catégories les plus impactées sont **hypothetical, temporal_evolution, false_premise, multi_hop** — précisément celles que l'architecture en couches V4.2 prétendait améliorer (operators temporal_active, lifecycle_resolution, etc.).

### 5.3 Patterns de régression identifiés (mesures sur 37 cas)

| Pattern | Nombre | % des régressions |
|---|---:|---:|
| **V4.2 abstient** ("La réponse n'a pas été trouvée") | **27/37** | **73%** |
| V4.2 hors-cible selon LLM-judge | 14/37 | 38% |

Les 73% de régressions par abstention sont le **signal central** : V4.2 transforme des réponses V3 correctes (citées avec doc IDs, judge "correctly identifies...") en abstentions silencieuses.

### 5.4 Exemples concrets de régression

#### Exemple 1 : Question lifecycle simple (q_125, lifecycle_supersedes)
```
Q: Le règlement 428/2009 est-il toujours en vigueur ?

V3 (0.9) — Correctly identifies replacement regulation with evidence
"Le règlement 428/2009 n'est plus en vigueur. Il a été remplacé par le règlement
(UE) 2021/821, qui est le nouveau cadre réglementaire pour le contrôle des exportations,
transferts, intermédiaires et transit d'articles à double usage [doc=dualuse_reg_2021_821_...]"

V4.2 (0.2) — Fails to identify replacement regulation
"La réponse à votre question n'a pas été trouvée dans les documents disponibles."
```
**Note** : la LIFECYCLE_RELATION existe explicitement dans Neo4j (4 relations dont SUPERSEDES 428/2009 → 2021/821). Cap2.B `lifecycle_resolution` aurait dû déclencher. Soit l'intent detection a raté, soit le verifier a rejeté.

#### Exemple 2 : Question conditional (q_106, conditional)
```
Q: Si l'item à exporter n'est pas dans l'Annex I du règlement 2021/821, faut-il une autorisation ?

V3 (0.8) — Answer is mostly correct but slightly deviates from reference
"Si l'item à exporter n'est pas dans l'Annex I du règlement 2021/821, une autorisation
peut néanmoins être requise si l'exportateur a été informé par les autorités que l'item
est destiné à des utilisations liées au développement..."

V4.2 (0.0) — Answer is irrelevant and does not address the question
"La réponse extraite ne correspond pas précisément à la question.
Réessai avec un raisonnement plus poussé recommandé."
```
**Note** : message de fallback verifier MISALIGNED. Le pipeline V4.2 a produit une réponse, le verifier l'a rejetée, mais aucun layer n'a pu en produire une alternative valide.

#### Exemple 3 : Question contradiction inversée (q_143, lifecycle_vs_conflict)
```
Q: Y a-t-il une contradiction sur l'énergie d'impact des grands items en verre ?

V3 (0.8) — Correctly identifies no contradiction
"Il n'y a pas de contradiction sur l'énergie d'impact des grands items en verre.
Selon les amendments, les grands items en verre doivent être testés avec une énergie
d'impact de 21 J, causée par une balle de 51 mm de diamètre ou, alternativement, par
une autre méthode équivalente..."

V4.2 (0.2) — Fails to distinguish evolution from conflict, raising a false alarm
"Oui, il y a une contradiction sur l'énergie d'impact des grands items en verre,
car certains documents [doc=cs25_amdt_26_...], [doc=cs25_amdt_25_...], [doc=cs25_amdt_22_...]
spécifient une énergie d'impact de 80 J, tandis que d'autres..."
```
**Note** : ironiquement, c'est précisément ce que `Cap2.E comparison_contradiction` doit empêcher (cluster + qualifier evolution vs conflict). Soit l'operator n'a pas triggered, soit le qualifier a mal qualifié.

#### Exemple 4 : Question temporal explicit (q_25, temporal_evolution)
```
Q: Quelle régulation EU dual-use était applicable en mars 2020 ?

V3 (0.9) — Answer accurately cites relevant regulations and their timelines
"En mars 2020, la régulation EU dual-use applicable était le Règlement (CE) n° 428/2009
du Conseil, qui a été adopté le 5 mai 2009 et est entré en vigueur le 29 mai 2009..."

V4.2 (0.0) — Answer is irrelevant and doesn't address the question
"La réponse extraite ne correspond pas précisément à la question.
Réessai avec un raisonnement plus poussé recommandé."
```
**Note** : Cap2.A `temporal_active_version` est l'operator dédié à cette question. Il n'a pas triggered (intent rate) ou son résultat a été rejeté par le verifier.

---

## 6. Hypothèses de cause (à challenger)

### Hypothèse A : Le verifier veto est trop strict (impact suspecté : élevé)
Le Q↔A Alignment Verifier (DeepSeek-V3.1) compare la réponse à la question pour décider ALIGNED/MISALIGNED/ABSTAIN_OK. En cas de MISALIGNED, le pipeline rejette la réponse.

Sur les exemples q_106, q_25, on voit le message *"La réponse extraite ne correspond pas précisément à la question. Réessai avec un raisonnement plus poussé recommandé"* qui est précisément ce que le pipeline retourne quand le verifier dit MISALIGNED.

**Possibilité** : le verifier rejette des réponses partiellement correctes que V3 acceptait. Le seuil de strictness est mal calibré, et le pipeline n'a pas de fallback "réponse partielle est mieux que rien".

### Hypothèse B : Le prompt Layer 0 est trop conservatif (impact suspecté : élevé)
Le prompt extraction du Layer 0 stipule explicitement :
```
- If the chunks don't contain the answer, respond exactly:
  "La reponse a votre question n'a pas ete trouvee dans les documents disponibles."
- Stay concise: 1-3 sentences max
```

Sur 27/37 régressions = abstention ("La réponse n'a pas été trouvée"), c'est probablement la conséquence directe : **le prompt Layer 0 a un biais d'abstention**. V3 utilisait un prompt synthesis 5 stages avec Composer agentic plus volumineux — il "trouvait" plus souvent la réponse.

### Hypothèse C : Cap2.A/B/C/D/E ne triggerent presque jamais (impact suspecté : moyen)
Sur 170 questions, Layer 1 ne trigger que sur 4-7 questions (2-4%). Conséquence : 95% des questions tombent en Layer 0 directement, donc l'architecture en couches sophistiquée n'apporte rien. Pour les questions lifecycle/temporal/contradiction qui auraient dû déclencher Cap2.B/C/E, l'intent detection LLM léger DeepSeek les classe comme non-applicables.

Soit l'intent detection est trop conservatif, soit les conditions de déclenchement sont mal écrites.

### Hypothèse D : Régression dès le pipeline V4 facts-first non corrigée (impact suspecté : élevé)
Le pivot du 06/05 (V3 → V4) a démantelé le pipeline V3 "agentic synthesis" en 5 stages pour le remplacer par "facts-first" = type-adaptive Structurers + Composers. Cette refonte a produit -18pp Robustness dès le 07/05 (CH-47 mémoire).

Tous les chantiers suivants (CH-46, CH-47, CH-48, CH-49) **ont travaillé sur l'optimisation** de cette nouvelle architecture (latence, modèles, couches d'escalade) **sans jamais réparer la régression de base**.

V4.2 n'est qu'une couche au-dessus de V4 défaillant. Le verifier veto et l'architecture en couches ne peuvent pas compenser une dégradation upstream du pipeline de génération.

### Hypothèse E : Le LLM-judge est-il fiable ? (impact suspecté : faible mais à valider)
Mémoire projet note : *"Variance LLM-judge ±5-8pp inter-runs identiques"*, *"Prometheus sous-évalue 70% des réponses RAG"*. Mais on a basculé Prometheus → Llama-3.3-70B en mai (CH-34) précisément parce que Llama est plus calibré.

Néanmoins, une variance ±5pp ne peut pas expliquer un -25%. Et l'audit qualitatif (5 exemples ci-dessus) confirme que V4.2 abstient là où V3 répondait correctement — c'est factuel, pas un artefact du judge.

---

## 7. État de la dette architecturale

### Ce qui a été ajouté V3 → V4.2 (5 jours)
- Pipeline facts-first complet (5 type-adaptive Structurers, 5 Composers, 2 Channel verifiers, EvidenceRerouter)
- Module `runtime_v4_2/` (12 fichiers Python)
- 5 operators Cap2.A/B/C/D/E (lifecycle, kg_query, set_reasoning, comparison_contradiction)
- Layer 2 Adaptive Orchestrator avec tool use DeepSeek
- UnifiedIntentRouter
- Multi-view scorer + abstain reward + telemetry QuestionTrace
- ADR v1.1 LOCKED post 2 rounds critique LLMs externes
- 6 commits + 4 docs livraison

### Ce qui n'a pas progressé sur les benchs
- **Robustness** : régression -25% maintenue
- **T2T5 contradictions** : 7-25% (cible 80%)
- **RAGAS** : bench cassé en V4.2

### Ce qui marchait dans V3
- Pipeline 5 stages : decomposer → retrieval enrichi (HyDE+LLM-filter+rerank) → synthesis → verification (premise+NLI judge)
- Faithfulness 0.632, context_relevance 0.822, Robustness 0.545
- Réponses citées avec doc IDs verbatim, gestion correcte des prémisses fausses, des évolutions lifecycle, des questions conditionnelles

---

## 8. Questions ouvertes pour analyse externe

1. **Le pivot V3 → V4 facts-first du 06/05 était-il justifié au regard des chiffres ?** À l'époque, V3 était à 0.545 (cible 0.75). On a abandonné un système qui marchait *moins bien que la cible* pour un système qui s'est révélé *moins bien que V3*. Aurait-il fallu itérer V3 plutôt que pivoter ?

2. **Le verifier veto strict est-il le bon design ?** L'argument anti-Goodhart est solide, mais 73% des régressions = abstentions. Un verifier "soft" (warning seulement) ou un seuil de confidence plus bas (rejection seulement si confidence > 0.9) aurait-il préservé les réponses V3 ?

3. **Le prompt Layer 0 minimaliste est-il adapté à un corpus régulé ?** L'instruction *"if not found, respond exactly: 'La réponse n'a pas été trouvée'"* produit clairement une abstention abusive. Un prompt synthesis-style (avec composer) aurait-il préservé les réponses V3 ?

4. **L'architecture en couches d'escalade dynamique est-elle correcte ?** Si 95% des questions vont en Layer 0, les couches Cap2.A/B/C/D/E + Layer 2 sont-elles utiles ? Ne sont-elles que de la sophistication non rentabilisée ?

5. **Le pivot était-il prématuré ?** Avons-nous abandonné V3 sans avoir compris ce qui marchait dedans, et dont la perte a causé la régression actuelle ?

6. **Faut-il rollback sur V3 et capitaliser sur ce qui marchait ?** V3 reste accessible (`/api/runtime_v3/answer`), `RUNTIME_VERSION=v3` activable. La tentation est forte mais il faut comprendre POURQUOI V3 marchait avant de revenir.

7. **Le LLM-judge officiel mesure-t-il la bonne chose ?** Mes mesures multi-view internes donnaient 0.86 sur le même bench (très généreuses, rétrocompatibles avec abstain reward). Le LLM-judge donne 0.41. Les utilisateurs verraient quelle version ?

---

## 9. Données brutes pour vérification

Tous les fichiers de bench sont disponibles dans `data/benchmark/results/` :
- `robustness_run_20260505_104355_V3_FINAL3.json` (V3 référence)
- `robustness_run_20260505_163544_V3_S0_BASELINE.json`
- `robustness_run_20260508_060359_V4_CH46_POSTOPT.json`
- `robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json`
- `robustness_run_20260510_145658_v4_2_baseline.json` (V4.2 actuel)
- `t2t5_run_20260510_150946_v4_2_baseline.json`
- `ragas_run_20260510_152503_v4_2_baseline.json` (échec, scores vides)
- `ragas_run_20260505_105155_V3_FINAL3.json` (V3 référence RAGAS)

Script d'audit : `app/scripts/audit_v3_vs_v42.py` (croise per_sample par question_id).

---

## 10. Conclusion

OSMOSIS V4.2 livre une **architecture théoriquement élégante** (Tiered Pipeline avec verifier veto anti-Goodhart, 5 operators déterministes, orchestrator agentic, telemetry complète, charte domain-agnostic stricte). Tous les principes architecturaux post-2024 sont respectés (CRAG, Self-RAG, Adaptive RAG, evidence-first contradictions, escalation dynamique).

**Et pourtant, sur 3 benchs officiels, V4.2 régresse de 25% par rapport à V3** qui implémentait des principes plus simples. **22% du corpus voit V4.2 abstient là où V3 répondait correctement**. Le bench RAGAS V4.2 ne fonctionne plus du tout (chunks_used non exposés).

C'est un cas d'école de **sophistication non productive** : ajouter des couches d'optimisation sur un pipeline upstream défaillant ne le répare pas. Le pivot V3 → V4 du 06/05 a créé une dette qui n'a jamais été remboursée et que l'architecture V4.2 ne peut pas compenser.

L'avis indépendant de LLMs externes est sollicité sur les 7 questions ouvertes du §8 — particulièrement sur le bien-fondé du pivot V3 → V4, et sur l'opportunité d'un rollback partiel ou complet vers V3 comme baseline opérationnelle.
