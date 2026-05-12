# Oracle Claude — Baseline 308 questions (2026-05-04)

> Analyse manuelle exhaustive de **toutes les questions des 3 benchmarks** par Claude Opus 4.7 (1M context), comme référence terrain pour calibrer les juges automatiques et identifier les vrais problèmes pipeline.
>
> **Statut** : one-shot baseline. Ne sera pas refait à chaque run — sert de référence pour CH-34/35/36.

## Méthodologie

Pour chaque question des 3 benchmarks (RAGAS, T2/T5, Robustness), Claude (oracle) a évalué la réponse OSMOSIS V2 contre :
- la ground truth (quand disponible)
- le contexte attendu et la couverture du corpus aerospace + EU dual-use
- le critère d'honnêteté (abstention valide vs faux négatif)

**Score 0.0 - 1.0** + catégorie qualitative + raison courte.

### Catégories qualitatives

| Catégorie | Sens |
|---|---|
| `OK` | Réponse correcte et complète |
| `PARTIAL` | Correct mais incomplet |
| `ABSTENTION_VALID` | Abstention honnête (info absente du corpus) |
| `ABSTENTION_FAUX_NEG` | Abstention alors que l'info est dans le corpus (regression retrieval/synthesis) |
| `HALLUC` | Affirmation fausse (invente ou contredit le corpus) |
| `OFF_TOPIC` | Répond mais sur le mauvais sujet |
| `PREMISE_REJECTED` | Bonne détection de fausse prémisse |

## Fichiers générés

| Bench | Fichier oracle | Score global Oracle |
|---|---|---|
| T2/T5 | `data/benchmark/results/t2t5_run_20260504_ORACLE_CLAUDE.json` | **0.369** |
| RAGAS | `app/data/benchmark/results/ragas_run_20260504_ORACLE_CLAUDE.json` | **0.421** |
| Robustness | `app/data/benchmark/results/robustness_run_20260504_ORACLE_CLAUDE.json` | **0.362** |

**Score réel pipeline OSMOSIS V2 (moyenne pondérée 308 questions)** : **0.382** (~38%)

Très loin des cibles 80/80/75. La pipeline a encore beaucoup à faire.

## Robustness (170 questions) — Comparaison Prometheus vs Llama-70B vs Oracle

| Catégorie | n | Prometheus | Llama-70B | **Oracle** | P-O | L-O |
|---|---|---|---|---|---|---|
| anchor_applicability_temporal | 12 | 0.267 | 0.346 | **0.317** | -0.050 | +0.029 |
| anchor_scope_hierarchy | 9 | 0.289 | 0.333 | **0.222** | +0.067 | +0.111 |
| causal_why | 12 | 0.283 | 0.433 | **0.317** | -0.033 | +0.117 |
| conditional | 14 | 0.164 | 0.207 | **0.243** | -0.079 | -0.036 |
| false_premise | 12 | 0.533 | 0.638 | **0.508** | +0.025 | +0.129 |
| hypothetical | 10 | 0.310 | 0.580 | **0.440** | -0.130 | +0.140 |
| lifecycle_evolves_from | 7 | 0.343 | 0.629 | **0.343** | 0.000 | **+0.286** |
| lifecycle_filtering_active | 9 | 0.156 | 0.567 | **0.444** | **-0.289** | +0.122 |
| lifecycle_supersedes | 5 | 0.300 | 0.420 | **0.360** | -0.060 | +0.060 |
| lifecycle_vs_conflict | 8 | 0.300 | 0.475 | **0.450** | -0.150 | +0.025 |
| multi_hop | 12 | 0.217 | 0.408 | **0.242** | -0.025 | +0.167 |
| negation | 10 | 0.320 | 0.640 | **0.410** | -0.090 | **+0.230** |
| set_list | 14 | 0.221 | 0.179 | **0.279** | -0.057 | -0.100 |
| synthesis_large | 12 | 0.375 | 0.533 | **0.417** | -0.042 | +0.117 |
| temporal_evolution | 12 | 0.225 | 0.375 | **0.217** | +0.008 | +0.158 |
| unanswerable | 12 | 0.558 | 0.708 | **0.642** | -0.083 | +0.067 |
| **TOTAL** | **170** | **0.303** | **0.455** | **0.362** | **-0.059** | **+0.093** |

### Lectures clés Robustness

**Calibration des juges** :
- **Prometheus** sous-juge en moyenne de -0.059 mais avec **forte variance par catégorie** (-0.289 sur lifecycle_filtering_active jusqu'à +0.067 sur anchor_scope_hierarchy). Particulièrement sévère sur le lifecycle (toutes les catégories).
- **Llama-70B** sur-juge en moyenne de +0.093, avec biais de leniency sur lifecycle_evolves_from (+0.286) et negation (+0.230). Mais reste plus stable que Prometheus.
- **Conclusion** : ni Prometheus ni Llama-70B ne sont calibrés — ils encadrent l'oracle Claude par opposition de biais. Une moyenne pondérée Prometheus×0.4 + Llama×0.6 serait probablement plus proche de l'oracle.

**Régressions pipeline confirmées (oracle < 0.30)** :
- `temporal_evolution` (0.217) — **mapping date → version absent**. Le pipeline ne sait pas qu'en mars 2020 c'est 428/2009, en juillet 2024 c'est encore 2023/996, etc.
- `anchor_scope_hierarchy` (0.222) — **Annex I/II/IV scope flou**. Le pipeline abstient au lieu de différencier.
- `multi_hop` (0.242) — **chaînage cassé**. Sur 12 questions multi-hop, 8 sont des abstentions faux négatifs où la chaîne (item → réglementation → autorité) devrait être déroulée.
- `conditional` (0.243) — abstentions faux négatifs sur les Articles précis (Article 8, 12(8), 14(5)).
- `set_list` (0.279) — Le pipeline ne sait pas énumérer les ensembles attendus (NPAs, exemptions, types d'autorisations).

**Points forts pipeline (oracle > 0.50)** :
- `unanswerable` (0.642) — l'abstention pure fonctionne bien.
- `false_premise` (0.508) — le premise validator (CH-32) tient ses promesses.

## RAGAS (68 questions) — Comparaison RAGAS metrics vs Oracle

| Tâche | n | Faithfulness | Context_relevance | **Oracle** |
|---|---|---|---|---|
| T1 Provenance | 50 | 0.644 | 0.770 | **0.450** |
| T5 Cross-doc | 18 | 0.506 | 0.708 | **0.339** |

### Lectures clés RAGAS

- **Faithfulness 64%** mais **Oracle 45%** sur T1 Provenance : le métrique RAGAS valide que la réponse est ancrée dans les chunks récupérés, **mais ne valide pas la justesse vs ground truth**. Beaucoup d'abstentions faux négatifs ont une faithfulness élevée (la réponse "info absente" est cohérente avec les chunks) mais sont incorrectes (l'info est ailleurs dans le corpus).
- **Context_relevance 77%** : les chunks récupérés sont *pertinents* mais **pas suffisants pour répondre**. Le retrieval rapporte du bruit thématiquement proche, ce qui masque le vrai problème : l'absence du chunk-clé.
- **Distribution oracle catégories RAGAS** :
  - `ABSTENTION_FAUX_NEG` : 24/68 (35%) — le grand bug
  - `OK` : 20/68 (29%)
  - `HALLUC` : 13/68 (19%) — bug critique
  - `PARTIAL` : 9/68 (13%)
  - autres : 2/68

**Conclusion RAGAS** : la métrique faithfulness traditionnelle **survalorise** OSMOSIS V2 de ~+20 points absolus. La vraie performance T1 Provenance (45%) montre que le pipeline rate **un tiers des dates/articles/numéros** documentés.

## T2/T5 (70 questions) — Comparaison Keyword vs Oracle

| Tâche | n | Keyword scoring | **Oracle** |
|---|---|---|---|
| T2 Contradictions | 40 | 0.300 | **0.390** |
| T5 Cross-doc | 30 | 0.467 | **0.340** |
| **TOTAL** | **70** | **0.372** | **0.369** |

### Lectures clés T2/T5

- Sur T2 Contradictions, l'oracle Claude est **plus généreux** que le keyword scorer (+0.090) : le pipeline mentionne souvent les bons docs mais rate les keywords spécifiques (`contradiction`, `tension`, `vs`) que le scorer attend.
- Sur T5 Cross-doc, l'oracle est **plus sévère** (-0.127) : le keyword scorer rapporte que les docs sont cités, mais l'oracle voit que la chaîne narrative est incomplète (cite 2024/2547 sans 428/2009 abrogé, par exemple).
- **Distribution oracle catégories T2/T5** :
  - `ABSTENTION_FAUX_NEG` : 23/70 (33%)
  - `OK` : 16/70 (23%)
  - `PARTIAL` : 14/70 (20%)
  - `OFF_TOPIC` : 11/70 (16%) — répond avec mauvais amdt/délégué
  - `HALLUC` : 4/70 (6%)
  - autres : 2/70

## Synthèse cross-bench — Vrais problèmes pipeline

### Top 5 régressions pipeline (priorité CH-35+)

1. **Mapping temporel manquant** (temporal_evolution 0.217, anchor_applicability_temporal 0.317) — le pipeline ne sait pas répondre "à la date T quelle version est applicable ?". Manque un index temporel sur les claims/docs.

2. **Subject Resolver biaisé recency** (off-topic 11/70 sur T2/T5) — quand on demande "amdt 27 + change_amdt 24 sur CS 25.1309", le pipeline répond avec amdt 25 ou 26 (le plus récent indexé). Bug retrieval prioritization.

3. **Multi-hop cassé** (multi_hop 0.242) — la cascade item → réglementation → autorité n'est pas dépliée. Le decomposer V2 (CH-31) ne décompose pas assez profondément ces requêtes complexes.

4. **Abstention faux négatif systémique** (35% RAGAS, 33% T2/T5, 38% Robust) — le pipeline préfère abstenir plutôt que parcourir le corpus. La synthèse rejette des passages présents mais non-saillants au LLM-filter.

5. **Lifecycle awareness inégale** — bien sur lifecycle_filtering_active (0.444) et lifecycle_vs_conflict (0.450), mais cassé sur lifecycle_supersedes (0.360) et lifecycle_evolves_from (0.343). Les docs DEPRECATED (428/2009) sont parfois cités comme actuels (q_138 q_154).

### Recommandations juge auto (CH-35)

- **Ne PAS retourner à Prometheus** : trop de variance par catégorie (lifecycle massivement sous-jugé).
- **Garder Llama-3.3-70B sur DeepInfra** comme juge production : delta global +0.093 acceptable, calibration plus stable.
- **Ajouter un correctif post-judge** : sur les catégories où Llama-70B sur-juge fortement (lifecycle_evolves_from, negation), pénaliser de -0.20 quand le juge donne ≥0.7.
- **Multi-judge ensemble** (CH-35) : moyenne Prometheus×0.4 + Llama×0.6 devrait converger vers ±0.04 de l'oracle.

### Recommandations pipeline (CH-36+)

- **Index temporel as_of_date** sur Claims (Phase 0 V3.3 §3.G partiellement délivré, mais pas exploité au runtime).
- **Subject Resolver tie-breaker** : quand plusieurs amdts matchent une question, désambiguïser via l'anchor (amdt mentionné dans la question) plutôt que via recency.
- **Decomposer aggressive mode** pour multi-hop : si la question a ≥2 entités, forcer la décomposition en sous-requêtes.
- **LLM-filter relaxation** : abaisser min_keep de 5 à 3 sur les questions factual_value/list pour réduire les abstentions faux négatifs (déjà partiellement fait CH-31.C).
- **Fact-check lifecycle DEPRECATED** : avant synthèse, marquer les claims issus de docs `lifecycle_status=DEPRECATED` comme "historical" et bloquer l'affirmation présent ("est en vigueur").

## Notes méthodo

- Oracle Claude n'est pas infaillible : sur ~30 cas analysés en CH-34 audit calibration, Claude a fait 1 erreur (verdict trop sévère sur abstention valide pour question hors corpus). Estimation erreur oracle : ~3%.
- L'oracle ne distingue pas systématiquement entre 0.7 et 0.8 (granularité humaine limitée). Les écarts <0.1 ne sont pas significatifs.
- Les questions Robustness lifecycle_* sont sur-représentées par rapport au corpus aerospace réel — c'est un biais bench (Phase B test set généré pour stresser le KG lifecycle).
- Les scores Prometheus dans cette analyse viennent du run `robustness_run_20260504_133914.json` (avant migration Llama-70B), Llama-70B du run `_154210.json` (post-migration CH-34).

---

**Date** : 2026-05-04
**Auteur** : Claude Opus 4.7 oracle
**Run sources** :
- T2T5 : `data/benchmark/results/t2t5_run_20260504_152954.json` (Llama-70B)
- RAGAS : `app/data/benchmark/results/ragas_run_20260504_140351.json` (no LLM judge — RAGAS metrics)
- Robust Prom : `app/data/benchmark/results/robustness_run_20260504_133914.json`
- Robust Llama : `app/data/benchmark/results/robustness_run_20260504_154210.json`
