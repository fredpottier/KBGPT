# Dossier `chantiers/` — docs liés au tracking

> **But** : centraliser les documents (ADR, analyses, spécifications, audits) liés à un chantier précis du tracking.
> **Source de vérité du pilotage** : `../TRACKING_CHANTIERS_2026-05-02.md`
> **Convention nommage** : `YYYY-MM-DD_CH-XX[.Y]_NOM_DESCRIPTIF.md`
>   - Préfixe date = première création (du `git log --diff-filter=A`)
>   - Préfixe chantier = ID dans le tracking
>   - Tri chronologique naturel par `ls`

## Vue chronologique (par date de création)

| Date | Chantier | Fichier | Sujet |
|------|----------|---------|-------|
| 2026-04-01 | CH-16 | [2026-04-01_CH-16_SPEC_EXACT_ANSWER_GATE_V1.md](2026-04-01_CH-16_SPEC_EXACT_ANSWER_GATE_V1.md) | Spec gate déterministe pré-LLM (EXACT_NUMERIC, IDENTIFIER, VERSION_DATE) |
| 2026-04-01 | CH-20 | [2026-04-01_CH-20_ANALYSE_NEGATIVE_REJECTION_STRATEGY.md](2026-04-01_CH-20_ANALYSE_NEGATIVE_REJECTION_STRATEGY.md) | Coverage Score pré-synthèse + abstention |
| 2026-04-01 | CH-30 | [2026-04-01_CH-30_ANALYSE_COUVERTURE_QUESTIONS.md](2026-04-01_CH-30_ANALYSE_COUVERTURE_QUESTIONS.md) | Analyse couverture des questions par catégorie |
| 2026-04-01 | CH-30 | [2026-04-01_CH-30_SPEC_BENCHMARK_DASHBOARD_UI.md](2026-04-01_CH-30_SPEC_BENCHMARK_DASHBOARD_UI.md) | Spec dashboard frontend admin/benchmarks |
| 2026-04-02 | CH-08 | [2026-04-02_CH-08_SPEC_VERIFY_V2_DOCUMENT_REVIEW.md](2026-04-02_CH-08_SPEC_VERIFY_V2_DOCUMENT_REVIEW.md) | Spec upload .docx → analyse → .docx annoté Word |
| 2026-04-02 | CH-21 | [2026-04-02_CH-21_ANALYSE_ETAPE_QUALITE.md](2026-04-02_CH-21_ANALYSE_ETAPE_QUALITE.md) | Investigation chain_coverage 52.3% (chunks fragiles) |
| 2026-04-02 | CH-30 | [2026-04-02_CH-30_QUALITE_EVALUATEURS.md](2026-04-02_CH-30_QUALITE_EVALUATEURS.md) | Chantier qualité évaluateurs (LLM-juge vs keyword) |
| 2026-04-04 | CH-22 | [2026-04-04_CH-22_ANALYSE_KG_CONTEXT_POLLUTION.md](2026-04-04_CH-22_ANALYSE_KG_CONTEXT_POLLUTION.md) | Diagnostic pollution KG en mode DIRECT |
| 2026-04-06 | CH-13 | [2026-04-06_CH-13_PROPOSITION_ANSWER_GAP_DETECTOR.md](2026-04-06_CH-13_PROPOSITION_ANSWER_GAP_DETECTOR.md) | Proposition technique Answer Gap Detector (TF-IDF) |
| 2026-04-17 | CH-15 | [2026-04-17_CH-15_HEALTH_TOOLBOX_SCRIPTS.md](2026-04-17_CH-15_HEALTH_TOOLBOX_SCRIPTS.md) | Catégorisation des 117 scripts Python |
| 2026-04-17 | CH-18 | [2026-04-17_CH-18_INVESTIGATION_JUDGE_STABILITY.md](2026-04-17_CH-18_INVESTIGATION_JUDGE_STABILITY.md) | Non-déterminisme gpt-4o-mini (37%-84%) |
| 2026-04-17 | CH-19 | [2026-04-17_CH-19_INVESTIGATION_KG_QUALITY_REGULATORY.md](2026-04-17_CH-19_INVESTIGATION_KG_QUALITY_REGULATORY.md) | Bruit P5 entités génériques sur corpus régulatoire |
| 2026-04-18 | CH-17 | [2026-04-18_CH-17_INVESTIGATION_FACET_LINKAGE.md](2026-04-18_CH-17_INVESTIGATION_FACET_LINKAGE.md) | Facet linkage 27% biomédical (BLOCKED) |
| 2026-04-29 | CH-24 | [2026-04-29_CH-24_ADR_RAISONNEMENT_UI.md](2026-04-29_CH-24_ADR_RAISONNEMENT_UI.md) | ADR UI Raisonnement étendu (DIRECT/AUGMENTED/silences) |
| 2026-05-02 | CH-02 | [2026-05-02_CH-02_CADRAGE_V33_VS_V2.md](2026-05-02_CH-02_CADRAGE_V33_VS_V2.md) | Cadrage Phase 1 V3.3 résiduel |
| 2026-05-02 | CH-02.2 | [2026-05-02_CH-02.2_AUDIT_LOGICAL_RELATION.md](2026-05-02_CH-02.2_AUDIT_LOGICAL_RELATION.md) | Audit qualité 4 862 LOGICAL_RELATION |
| 2026-05-03 | CH-30 | [2026-05-03_CH-30_BENCHMARK_INVENTAIRE_AEROSPACE.md](2026-05-03_CH-30_BENCHMARK_INVENTAIRE_AEROSPACE.md) | Inventaire KG aerospace + cadrage format |
| 2026-05-05 | CH-40 | [2026-05-05_CH-40_ADR_V4_ARCHITECTURE.md](2026-05-05_CH-40_ADR_V4_ARCHITECTURE.md) | ADR V4 initial (13 décisions D1-D13) |
| 2026-05-05 | CH-40 | [2026-05-05_CH-40_S0_BASELINE.md](2026-05-05_CH-40_S0_BASELINE.md) | **Doc maître consolidé S0** (504 lignes self-contained) |
| 2026-05-05 | CH-40 | [2026-05-05_CH-40_S0_DISAGREEMENT_ANALYSIS.md](2026-05-05_CH-40_S0_DISAGREEMENT_ANALYSIS.md) | Top-20 cas judge_overscored ≥ 0.2 |
| 2026-05-05 | CH-40 | [2026-05-05_CH-40_S0_SANITY_CHECK.md](2026-05-05_CH-40_S0_SANITY_CHECK.md) | 9 questions sanity check Fred (verdict ternaire) |
| 2026-05-06 | CH-41 | [2026-05-06_CH-41_ADR_FACTS_FIRST.md](2026-05-06_CH-41_ADR_FACTS_FIRST.md) | **ADR principal facts-first** (D-FF1 à D-FF12) |
| 2026-05-06 | CH-41 | [2026-05-06_CH-41_STRUCTURER_V1_DESIGN_REFERENCE.md](2026-05-06_CH-41_STRUCTURER_V1_DESIGN_REFERENCE.md) | Design détaillé Structurer V1 (réponse ChatGPT 06/05) |
| 2026-05-06 | CH-41 | [2026-05-06_CH-41_EAV_ABSTENTION_MODE.md](2026-05-06_CH-41_EAV_ABSTENTION_MODE.md) | Mode EAV abstention structurée (D-FF11) |
| 2026-05-06 | CH-41 | [2026-05-06_CH-41_STRESS_TEST_PANEL_SPEC.md](2026-05-06_CH-41_STRESS_TEST_PANEL_SPEC.md) | Cadrage panel stress-test 100q multi-domaines (D-FF12) |

## Vue par chantier

### CH-02 — Modèle V3.3 résiduel post-V2 anchor-driven
- 2026-05-02_CH-02_CADRAGE_V33_VS_V2.md — Cadrage Phase 1 (4 sous-chantiers).
- 2026-05-02_CH-02.2_AUDIT_LOGICAL_RELATION.md — Audit 4 862 LOGICAL_RELATION par Claude expert.

### CH-08 — Verify V2 Document Review Word
- 2026-04-02_CH-08_SPEC_VERIFY_V2_DOCUMENT_REVIEW.md

### CH-13 — Answer Gap Detector
- 2026-04-06_CH-13_PROPOSITION_ANSWER_GAP_DETECTOR.md

### CH-15 — Health Toolbox scripts
- 2026-04-17_CH-15_HEALTH_TOOLBOX_SCRIPTS.md

### CH-16 — Exact Answer Gate V1
- 2026-04-01_CH-16_SPEC_EXACT_ANSWER_GATE_V1.md

### CH-17 — Facet linkage 27% biomédical (BLOCKED)
- 2026-04-18_CH-17_INVESTIGATION_FACET_LINKAGE.md

### CH-18 — Instabilité juge LLM benchmarks T2/T5
- 2026-04-17_CH-18_INVESTIGATION_JUDGE_STABILITY.md

### CH-19 — KG Quality régulatoire P5
- 2026-04-17_CH-19_INVESTIGATION_KG_QUALITY_REGULATORY.md

### CH-20 — Negative Rejection
- 2026-04-01_CH-20_ANALYSE_NEGATIVE_REJECTION_STRATEGY.md

### CH-21 — Étape qualité OSMOSIS chunks fragiles
- 2026-04-02_CH-21_ANALYSE_ETAPE_QUALITE.md

### CH-22 — Pollution KG mode DIRECT
- 2026-04-04_CH-22_ANALYSE_KG_CONTEXT_POLLUTION.md

### CH-24 — UI Raisonnement étendu
- 2026-04-29_CH-24_ADR_RAISONNEMENT_UI.md

### CH-30 — Refonte benchmarks V2 (RAGAS, T1/T2/T5/T6/T7, Robustesse)
- 2026-04-01_CH-30_ANALYSE_COUVERTURE_QUESTIONS.md
- 2026-04-01_CH-30_SPEC_BENCHMARK_DASHBOARD_UI.md
- 2026-04-02_CH-30_QUALITE_EVALUATEURS.md
- 2026-05-03_CH-30_BENCHMARK_INVENTAIRE_AEROSPACE.md

### CH-40 — Sprint S0 V4 : Calibration & Gold-set
- 2026-05-05_CH-40_ADR_V4_ARCHITECTURE.md
- 2026-05-05_CH-40_S0_BASELINE.md (**doc maître consolidé**)
- 2026-05-05_CH-40_S0_DISAGREEMENT_ANALYSIS.md
- 2026-05-05_CH-40_S0_SANITY_CHECK.md

### CH-41 — V4 Facts-First : Tranche 1 list (architecture cible)
- 2026-05-06_CH-41_ADR_FACTS_FIRST.md (**ADR principal**)
- 2026-05-06_CH-41_STRUCTURER_V1_DESIGN_REFERENCE.md
- 2026-05-06_CH-41_EAV_ABSTENTION_MODE.md
- 2026-05-06_CH-41_STRESS_TEST_PANEL_SPEC.md

## Hors `chantiers/` mais liés à des chantiers (laissés à racine)

Ces docs ont été identifiés comme **potentiellement liés** à un chantier mais sans citation explicite dans le tracking. Restent à la racine de `doc/ongoing/` pour validation user :

| Fichier (racine /ongoing/) | Chantier potentiel | À valider |
|----------------------------|--------------------|-----------|
| `CONTRADICTION_DETECTION_ARCHITECTURE.md` | CH-02 (architecture V3.3) | Lien implicite |
| `CHANTIER_REFONTE_CHAT.md` | CH-05 | Nom suggère le lien |
| `CHANTIER_VERIFY_V1_ETAT.md` | CH-07 | Nom suggère le lien |
| `RECHERCHE_UNANSWERABLE_DETECTION.md` | CH-13 (research) | Recherche état de l'art |
| `CORPUS_PREECLAMPSIA_PLAN.md` | CH-17 (corpus biomédical) | Plan corpus pour relancer |
| `ANALYSE_KG_ENRICHMENT_GAP.md` | CH-22 | Sujet pollution KG |

Si tu veux qu'un de ces docs entre dans `chantiers/` après revue, le déplacer avec préfixe `YYYY-MM-DD_CH-XX_`.

## ADRs structurels (NON chantier-spécifiques)

Ces ADRs définissent l'architecture globale OSMOSIS et restent à la racine de `doc/ongoing/`. Ils sont référencés par plusieurs chantiers mais n'appartiennent pas à un chantier précis :
- `ADR_BENCH_PROTOCOL_ARMAND.md`
- `ADR_CORPUS_VIVANT_PHILOSOPHIE.md`
- `ADR_DOMAIN_PACK_LIFECYCLE.md`
- `ADR_ENTITY_EXTRACTION_DOMAIN_AGNOSTIC.md`
- `ADR_INGESTION_CONFIDENCE.md`
- `ADR_KG_INJECTION_ARCHITECTURE_V2.md`
- `ADR_KG_INJECTION_ARCHITECTURE_V3.md`
- `ADR_LIFECYCLE_VS_LOGICAL_RELATIONS.md`
- `ADR_LLM_CONFIGURATION_PAGE.md`
- `ADR_LLM_CONFIGURATION_PAGE_V2.md`
- `ADR_LOCAL_LLM_STRATEGY.md`
- `ADR_PERSPECTIVE_LAYER_ARCHITECTURE.md`
- `ADR_RUNTIME_V2_OPERATIONAL.md`
- `ADR_TENSION_CLASSIFICATION.md`
- `RUNTIME_EXPLOITATION_ARCHITECTURE.md`

## Convention pour nouveaux docs

Tout nouveau document lié à un chantier du tracking doit :
1. Être créé dans ce dossier `chantiers/` (pas à la racine de `/ongoing/`)
2. Être préfixé par sa date de création + ID chantier : `YYYY-MM-DD_CH-XX_NOM_DESCRIPTIF.md`
3. Avoir son entrée ajoutée à ce README (section chronologique + section par chantier)

Tout document **non lié** à un chantier précis (ADR structurel, vision, audit transversal, snapshot, recherche état de l'art) reste à la racine de `doc/ongoing/`.
