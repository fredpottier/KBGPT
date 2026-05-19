# Dossier `chantiers/` — chantiers actifs et traces de référence

> **Version 2.0** — 19/05/2026 (refondation post-VISION.md)
> **But** : centraliser les chantiers actifs + traces décisionnelles encore valides après la refondation Vision du 18-19/05/2026.
> **Source de vérité pilotage** : tracker Claude Code (TaskList) + `doc/EXECUTION_ROADMAP.md` §2 (phases A→D)
> **Convention nommage** : `YYYY-MM-DD_CH-XX[.Y]_NOM_DESCRIPTIF.md` (date = première création)

## 🗂️ Que contient ce dossier après refondation ?

Après l'audit du 19/05/2026 (cf rapport audit vision-guardian), ce dossier ne contient plus que les chantiers **🟢 actifs** ou **traces décisionnelles encore vivantes** pour la suite. Les 49 chantiers historiques ou exploratoires ont été déplacés vers `doc/archive/2026-05_post-vision-cleanup/` (4 sous-dossiers, voir §Archives ci-dessous).

**État au 19/05/2026** : 30 fichiers actifs (29 chantiers + ce README).

## 📋 Chantiers actifs — Vue par thème

### Traces décisionnelles 🔑 critiques (à connaître)

| Date | Chantier | Fichier | Valeur pour la suite |
|------|----------|---------|---------------------|
| 2026-05-10 | **CH-50** | [Oracle Audit Results](2026-05-10_CH-50_ORACLE_AUDIT_RESULTS.md) | Démontre la borne supérieure 0.86-0.94 (Sonnet+lecture libre) et fonde le pivot vers V5 Reading Agent. **À relire pour comprendre pourquoi V5.1 plafonne à 0.61**. |
| 2026-05-10 | CH-50 | [Frontier Models Tests](2026-05-10_CH-50_FRONTIER_MODELS_TESTS.md) | Mesures OpenAI A+B+C+E (cap LLM frontier). |
| 2026-05-11 | **CH-51** | [Reading Agent Bench 170q](2026-05-11_CH-51_READING_AGENT_BENCH_170Q.md) | Validation POC V5 sur bench robustness 170q. Base de CH-52 industrialisation. |

### Calibration & gap analyses (préparent Phase A)

| Date | Chantier | Fichier | Cible Phase |
|------|----------|---------|-------------|
| ~2026-05-13 | S0.5 | [Fast Path Results](S0.5_FAST_PATH_RESULTS.md) | Données utiles pour latence Phase A3 |
| ~2026-05-14 | S0.6 | [Audit Conclusions](S0.6_AUDIT_CONCLUSIONS.md) | Conclusions transition V4→V5 |
| ~2026-05-14 | S0.6 | [Gap EKX Analysis](S0.6_GAP_EKX_ANALYSIS.md) | **Référence cible 0.86** (EKX) sur 30q hard |

### Trace V4 livraisons (référence historique — chantiers livrés ou décisions à conserver)

#### CH-02 — Modèle V3.3 résiduel

| Fichier | Description |
|---------|-------------|
| [CH-02_CADRAGE_V33_VS_V2.md](2026-05-02_CH-02_CADRAGE_V33_VS_V2.md) | Cadrage Phase 1 (4 sous-chantiers) |
| [CH-02.2_AUDIT_LOGICAL_RELATION.md](2026-05-02_CH-02.2_AUDIT_LOGICAL_RELATION.md) | Audit 4862 LOGICAL_RELATION par Claude expert |

#### CH-40 — Sprint S0 V4 (Calibration & Gold-set)

| Fichier | Description |
|---------|-------------|
| [CH-40_ADR_V4_ARCHITECTURE.md](2026-05-05_CH-40_ADR_V4_ARCHITECTURE.md) | ADR V4 initial (13 décisions D1-D13) |
| [CH-40_S0_BASELINE.md](2026-05-05_CH-40_S0_BASELINE.md) | **Doc maître consolidé S0** (504 lignes self-contained) |
| [CH-40_S0_DISAGREEMENT_ANALYSIS.md](2026-05-05_CH-40_S0_DISAGREEMENT_ANALYSIS.md) | Top-20 cas judge_overscored ≥ 0.2 |
| [CH-40_S0_SANITY_CHECK.md](2026-05-05_CH-40_S0_SANITY_CHECK.md) | 9 questions sanity check Fred |

#### CH-41 — V4 Facts-First Tranche 1 (livré)

| Fichier | Description |
|---------|-------------|
| [CH-41_ADR_FACTS_FIRST.md](2026-05-06_CH-41_ADR_FACTS_FIRST.md) | **ADR principal facts-first** (D-FF1 à D-FF12) |
| [CH-41_STRUCTURER_V1_DESIGN_REFERENCE.md](2026-05-06_CH-41_STRUCTURER_V1_DESIGN_REFERENCE.md) | Design détaillé Structurer V1 |
| [CH-41_EAV_ABSTENTION_MODE.md](2026-05-06_CH-41_EAV_ABSTENTION_MODE.md) | Mode EAV abstention structurée (D-FF11) |
| [CH-41_STRESS_TEST_PANEL_SPEC.md](2026-05-06_CH-41_STRESS_TEST_PANEL_SPEC.md) | Cadrage panel stress-test multi-domaines (D-FF12) |
| [CH-41.1_QUESTION_ANALYZER_RESULTS.md](2026-05-06_CH-41.1_QUESTION_ANALYZER_RESULTS.md) | Résultats QuestionAnalyzer |
| [CH-41.4_BENCH_LIST_TRANCHE1_RESULTS.md](2026-05-06_CH-41.4_BENCH_LIST_TRANCHE1_RESULTS.md) | Bench list tranche 1 résultats |
| [CH-41_TRANCHE2_FACTUAL_RESULTS.md](2026-05-06_CH-41_TRANCHE2_FACTUAL_RESULTS.md) | Bench tranche 2 factual |
| [CH-41_RAG_BASELINE_FACTUAL.md](2026-05-06_CH-41_RAG_BASELINE_FACTUAL.md) | Baseline RAG vs facts-first |
| [CH-41_TRANSVERSE_AND_TRANCHES3-5_RECAP.md](2026-05-06_CH-41_TRANSVERSE_AND_TRANCHES3-5_RECAP.md) | Recap tranches 3-5 transverses |

#### CH-49 — Refonte V4.2 (livraison complète)

| Fichier | Description |
|---------|-------------|
| [CH-49_ADR_PIPELINE_V4_1_CORRECTIONS.md](2026-05-09_CH-49_ADR_PIPELINE_V4_1_CORRECTIONS.md) | ADR corrections par type V4.1 |
| [CH-49_ADR_PIPELINE_V4_2_ARCHITECTURE_CIBLE_v1.md](2026-05-10_CH-49_ADR_PIPELINE_V4_2_ARCHITECTURE_CIBLE_v1.md) | ADR v1.0 architecture V4.2 (5 capabilities) |
| [CH-49_AUDIT_REGRESSION_V3_VS_V4_2.md](2026-05-10_CH-49_AUDIT_REGRESSION_V3_VS_V4_2.md) | Audit regression V3 vs V4.2 |
| [CH-49_P1_BENCH_RESULTS.md](2026-05-10_CH-49_P1_BENCH_RESULTS.md) | Bench Phase 1 |
| [CH-49_P1_MULTI_VIEW_SCORER_CALIBRATION.md](2026-05-10_CH-49_P1_MULTI_VIEW_SCORER_CALIBRATION.md) | Multi-view scorer calibration |
| [CH-49_P5_BENCH_FINAL_RESULTS.md](2026-05-10_CH-49_P5_BENCH_FINAL_RESULTS.md) | Bench final 120q V4.2 |
| [CH-49_PHASE1_LIVRAISON.md](2026-05-10_CH-49_PHASE1_LIVRAISON.md) | Phase 1 livraison |
| [CH-49_PHASE2_LIVRAISON.md](2026-05-10_CH-49_PHASE2_LIVRAISON.md) | Phase 2 livraison |

## 📦 Archives — `doc/archive/2026-05_post-vision-cleanup/`

Suite à l'audit du 19/05/2026, **49 chantiers/ADR ont été déplacés en archive** pour préservation historique sans pollution du dossier actif :

| Sous-dossier | Contenu | Nombre |
|---|---|---|
| `adr_historiques/` | ADR de paradigmes V2/V3/V4 supersédés par VISION.md (CORPUS_VIVANT, KG_V2, LLM_CONFIG×2, LOCAL_LLM, PERSPECTIVE_LAYER, RUNTIME_V2) | 7 |
| `chantiers_pre_refondation/` | Chantiers livrés avril 2026 (CH-08, CH-13, CH-15, CH-16, CH-17, CH-18, CH-19, CH-20, CH-21, CH-22, CH-24, CH-30) + 5 chantiers V4 livrés début mai | 19 |
| `voies_exploratoires/` | V6 exploration (REFONTE_INGESTION, NEO4J_SCHEMA, DOUBLE_BENCH), bake-offs LLM (Qwen3-235B, downsize), CH-46/47/48 (Together AI, optims latence V4), plans sprint P3/4/5, S3.5, S7, BACKLOG_DEV | 16 |
| `features_futures/` | Chantiers UI/UX (CHANTIER_BENCHMARK, CHUNKING, COCKPIT, KG_QUALITY, REFONTE_CHAT, VERIFY_V1, ATLAS) — différés en Phase D | 7 |

**Total archivé** : 49 fichiers. **Supprimés** (obsolètes) : 5 fichiers (ADR_BENCH_PROTOCOL_ARMAND + PHASING_OSMOSIS_V2 + V6_J1_NIGHT_REPORT + VOIE_A_ABLATION + VOIE_A_DEBRIEF).

> Les archives sont **conservées** pour préservation mémoire/audit. Aucune suppression de contenu décisionnel.

## 🚀 Convention pour nouveaux chantiers

Tout nouveau chantier doit :

1. **Être rattaché à une phase A→D** de `doc/EXECUTION_ROADMAP.md` OU à un kill switch K-1 à K-6 OU à un ADR du backlog §4
2. **Être créé ici** avec format `YYYY-MM-DD_CH-XX_NOM.md` (préfixe date + ID)
3. **Être ajouté au tracker** (TaskCreate) avec subject rattaché à la phase (ex: `PHASE A1 — ...`)
4. **Être référencé** dans ce README si c'est un livrable structurant

Tout chantier **non rattachable** à VISION/ROADMAP doit être **tracé d'abord dans `doc/ongoing/etudes/deviations_log.md`** par l'agent `vision-guardian` (ou manuellement) AVANT démarrage. Voir VISION.md §11.3.

## 📚 Documents structurants à connaître

Avant tout nouveau chantier, lire dans l'ordre :
1. [`doc/VISION.md`](../../VISION.md) — 16 axiomes + capacités + anti-vision (~15 min)
2. [`doc/EXECUTION_ROADMAP.md`](../../EXECUTION_ROADMAP.md) — phases A→D + kill switches (~10 min)
3. Ce README pour identifier les traces de référence pertinentes au chantier
4. Si chantier touche au code runtime : lire `doc/ARCH_*.md` selon zone

---

*Refondé 2026-05-19 dans le cadre de la refondation Vision (P3 cleanup post-VISION.md).*
