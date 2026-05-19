# Archive — Post-Vision Cleanup (mai 2026)

> Cette archive contient **49 fichiers** déplacés depuis `doc/ongoing/` lors de la refondation Vision du 18-19/05/2026, suite à l'audit de pertinence vs `doc/VISION.md` et `doc/EXECUTION_ROADMAP.md`.

## Contexte

Le 18/05/2026, le projet OSMOSIS a fait une refondation Vision (création de `VISION.md` + `EXECUTION_ROADMAP.md`) suite à un constat de dérive (10 jours de tweaks bench V5.1 sans franchir le plafond, cf VISION.md §8.4).

Le 19/05/2026, un audit complet de `doc/ongoing/adr/` (17 ADR) et `doc/ongoing/chantiers/` (76 chantiers) a été conduit pour classer chaque fichier en :
- 🟢 **Actif** (conservé dans `doc/ongoing/`)
- 🟡 **Historique valide** (déplacé ici)
- 🔴 **Obsolète** (supprimé — 5 fichiers : ADR_BENCH_PROTOCOL_ARMAND, PHASING_OSMOSIS_V2, V6_J1_NIGHT_REPORT, VOIE_A_×2)

**Résultat** : 28 fichiers conservés actifs, 49 archivés ici, 5 supprimés.

## Structure de l'archive

### `adr_historiques/` (7 fichiers)

ADR de paradigmes architecturaux **supersédés** par VISION.md ou différés en phase ultérieure :

- `ADR_CORPUS_VIVANT_PHILOSOPHIE.md` — Conception philosophique pré-impl, absorbée dans VISION.md §1
- `ADR_KG_INJECTION_ARCHITECTURE_V2.md` — Two-Pass architecture rejetée en V3
- `ADR_LLM_CONFIGURATION_PAGE.md` + `_V2.md` — Config UI admin différée Phase D
- `ADR_LOCAL_LLM_STRATEGY.md` — Stratégie self-host LLM différée Phase D
- `ADR_PERSPECTIVE_LAYER_ARCHITECTURE.md` — Couche Perspective différée post-runtime stable (Phase C)
- `ADR_RUNTIME_V2_OPERATIONAL.md` — SLA Runtime V2 anchor-driven obsolète (V2 abrogé)

### `chantiers_pre_refondation/` (19 fichiers)

Chantiers **livrés avant la refondation** (avril 2026 + mai V4) :

- 14 chantiers `2026-04-XX_CH-*.md` : CH-08 (Verify V2), CH-13 (Answer Gap), CH-15 (Health Toolbox), CH-16 (Exact Answer Gate), CH-17 (Facet linkage biomédical), CH-18 (Judge stability), CH-19 (KG quality régulatoire), CH-20 (Negative rejection), CH-21 (Étape qualité chunks), CH-22 (KG context pollution), CH-24 (UI raisonnement), CH-30 (4 docs benchmark)
- 5 chantiers mai V4 livrés début mai (avant Phase A nouvelle) : `2026-05-03_CH-30_BENCHMARK_INVENTAIRE_AEROSPACE`, `2026-05-07_BENCH_GLOBAL_V4_FINAL_ANALYSIS`, `2026-05-07_BENCH_POST_LEVIERS_LATENCE`, `2026-05-07_PHASE0_AUDIT_TAXONOMY`, `2026-05-07_S2_ROUTER_CHALLENGE_EXTERNE`

### `voies_exploratoires/` (16 fichiers)

Chantiers d'exploration **parallèles ou pré-V5.1**, paradigmes V4/V5/V6 abandonnés ou non intégrés au runtime cible :

- V6 exploration : `V6_REFONTE_INGESTION_PROPOSITION`, `V6_NEO4J_SCHEMA_DESIGN`, `V6_DOUBLE_BENCH_PROTOCOL`
- Bake-offs LLM : `BAKEOFF_LLM_DOWNSIZE_2026-05-15`, `BENCH_QWEN3_235B_KNOWLEDGE_EXTRACTION`
- CH-46/47/48 (V4 latence + Together AI) : `CH-46_OPTIMISATIONS_LATENCE_V4`, `CH-47_PHASE0B_MOCKS`, `CH-47_PHASE1_SPEC`, `CH-48_TOGETHER_AI_SETUP`
- Plans sprint V4 : `P3_BUGS_INVESTIGATION_PLAN`, `P4_RESILIENCE_SPRINT_PLAN`, `P5_POLISH_PLAN`, `PHASING_OSMOSIS_V2_FINALISATION` (déjà supprimé)
- Autres : `PLAN_C4_RELATIONS_EVIDENCE_FIRST`, `S3.5_MINI_POC_QUANTITATIF_PROTOCOL`, `S7_VERIFIER_BAKEOFF_PROTOCOL`, `BACKLOG_DEV_2026-05-01`

### `features_futures/` (7 fichiers)

Chantiers d'**infrastructure non-MVP** différés en Phase D ou C de l'EXECUTION_ROADMAP :

- `CHANTIER_ATLAS.md` — Atlas exploration visuelle (Phase C)
- `CHANTIER_BENCHMARK.md` — Framework benchmark consolidé
- `CHANTIER_CHUNKING.md` — Diagnostic et stratégie rechunking
- `CHANTIER_COCKPIT.md` — Cockpit opérationnel UI
- `CHANTIER_KG_QUALITY.md` — 6 chantiers qualité KG (Entity Resolution, dédup)
- `CHANTIER_REFONTE_CHAT.md` — Refonte interface chat (Phase C)
- `CHANTIER_VERIFY_V1_ETAT.md` — État Verify V1

## Comment utiliser cette archive

- **Pour consulter** : lire les fichiers ici sans les déplacer. Ils sont disponibles pour audit, mémoire historique, ou contexte d'une décision passée.
- **Pour réactiver un fichier** : si une feature ou un ADR devient pertinent (ex: passer en Phase C → réactiver `CHANTIER_REFONTE_CHAT`), le déplacer **back** vers `doc/ongoing/chantiers/` ou `doc/ongoing/adr/` avec git mv et mettre à jour le README du dossier cible.
- **Pour comprendre l'évolution du projet** : c'est un instantané de la doc telle qu'elle existait avant la refondation Vision. Utile pour comprendre les paradigmes passés (V1.1 / V2 / V3 / V3.3 / V4 / V4.1 / V4.2 / V5).

## Liens

- Source de vérité actuelle : [`doc/VISION.md`](../../VISION.md)
- Plan d'exécution : [`doc/EXECUTION_ROADMAP.md`](../../EXECUTION_ROADMAP.md)
- Anti-vision (pistes écartées) : VISION.md §8
- Décisions de refondation : `doc/ongoing/etudes/deviations_log.md`

---

*Archive créée le 19/05/2026 dans le cadre de la refondation Vision (P3 cleanup).*
