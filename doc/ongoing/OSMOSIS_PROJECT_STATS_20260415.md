# OSMOSIS — Statistiques du Projet

*Genere le 15 avril 2026*

## Vue d'ensemble

| Metrique | Valeur |
|----------|--------|
| **Premier commit** | 5 septembre 2025, 18h18 |
| **Dernier commit** | 10 avril 2026, 23h49 |
| **Duree du projet** | **7 mois et 10 jours** |
| **Total commits** | **1 256** |
| **Total lignes inserees** | **1 396 537** |
| **Code en production** | **85 696** lignes Python + **47 099** lignes TypeScript = **136 044 lignes** |
| **Fichiers Python** | 2 692 |
| **Fichiers TypeScript/TSX** | 196 |
| **Questions benchmark** | 23 fichiers, 700+ questions |
| **Branches** | 56 (29 actives) |
| **Taille du repo** | 3.6 GB (138 MB git history) |

## Rythme de developpement par mois

| Mois | Commits | Lignes inserees | Fait marquant |
|------|---------|-----------------|---------------|
| Sep 2025 | 63 | 84 014 | Lancement — PPTX ingester |
| Oct 2025 | **278** | **222 847** | Mois record — infra AWS + pipeline |
| Nov 2025 | 8 | 31 454 | Pause relative |
| Dec 2025 | 27 | 119 196 | Phase 2 Intelligence + Burst EC2 |
| Jan 2026 | **144** | **210 705** | Extraction V2 + Pipeline Stratifie |
| Fev 2026 | 69 | 97 385 | ClaimFirst complet |
| Mar 2026 | 63 | 70 979 | Benchmarks + Response Modes V3 |
| Avr 2026 | **163** | 87 663 | Corpus reglementaire + Mode Local LLM |

## Sessions nocturnes

| Stat | Valeur |
|------|--------|
| **Commits entre 22h et 1h** | **172** (14% de tous les commits) |
| **Heure la plus active** | **14h-15h** (141 commits) |
| **2e pic** | **22h-23h** (131 commits) — les sessions du soir |
| **Commit le plus tardif** | **23:59** le 9 avril 2026 |
| **Commit le jour de Noel** | 25 dec 2025, 23h57 — "Claims MVP complet + Entity Resolution" |
| **Commit le 31 decembre** | 31 dec 2025, 20h08 — "Burst Mode EC2 Spot stable" |

## Distribution horaire des commits

```
00h: ████████  41
07h: █  6
08h: ███  18
09h: █████  26
10h: ██████  31
11h: ████████  42
12h: ███████████  57
13h: █████████  45
14h: ██████████████  71
15h: ██████████████  70
16h: █████  28
17h: ███████  37
18h: ████████████  62
19h: ██████████  51
20h: ██████████  53
21h: █████████  46
22h: ████████████  63
23h: █████████████  68
```

## Distribution par jour de la semaine

| Jour | Commits |
|------|---------|
| Lundi | 84 |
| Mardi | 135 |
| Mercredi | 120 |
| **Jeudi** | **179** |
| **Vendredi** | **161** |
| Samedi | 71 |
| Dimanche | 65 |

## Records

| Record | Detail |
|--------|--------|
| **Jour le plus productif** | **35 commits** le 2 avril 2026 et le 10 octobre 2025 |
| **Plus gros commit** | **44 667 lignes** — plan migration LLM locaux (23 sep 2025) |
| **Streak le plus long** | **9 jours consecutifs** (jusqu'au 27 jan 2026) |
| **Semaines actives** | **26 sur 31** — code au moins une semaine sur 5/6 |

## Top 10 plus gros commits

| Lignes | Date | Description |
|--------|------|-------------|
| 44 667 | 23 sep 2025 | Plan migration LLM locaux |
| 30 923 | 19 dec 2025 | Phase 2.3 - InferenceEngine + Graph-Guided RAG |
| 27 677 | 6 fev 2026 | Pipeline ClaimFirst complet + ApplicabilityFrame |
| 24 750 | 29 dec 2025 | Burst Mode EC2 Spot + ADR Hybrid Anchor |
| 23 856 | 13 oct 2025 | Infrastructure EC2 + ECR |
| 22 840 | 19 jan 2026 | Evidence Bundle + coreference + ADR |
| 19 846 | 24 oct 2025 | Timezone Europe/Paris + optimisations |
| 19 840 | 2 jan 2026 | Extraction V2 complete + Vision Gating V4 |
| 16 569 | 25 jan 2026 | Pipeline Stratifie V2 - Pass 1/2/3 |
| 16 249 | 16 nov 2025 | Cross-ref Neo4j/Qdrant + Phase 2 |

## Features vs Fixes

| Type | Nombre | % |
|------|--------|---|
| **feat** (nouvelles features) | **316** | 43% |
| **fix** (corrections) | **254** | 35% |
| **docs** (documentation) | **107** | 15% |
| **refactor** | 32 | 4% |
| **chore** | 15 | 2% |

## Mots les plus frequents dans les messages de commit

1. feat (319) — construire
2. fix (274) — corriger
3. phase (156) — structurer
4. docs (96) — documenter
5. ajouter (75) — enrichir
6. corriger (53) — fiabiliser
7. claude (51) — collaborer
8. pipeline (48) — automatiser
9. pass (48) — stratifier

## Jalons majeurs

- **Sep 2025** : Fondations — ingestion PPTX/PDF, Qdrant, FastAPI
- **Oct 2025** : Infrastructure AWS, EC2 Spot, deploiement
- **Dec 2025** : Phase 2 Intelligence, Burst Mode EC2, Claims MVP (commit de Noel !)
- **Jan 2026** : Extraction V2, Vision Gating, Pipeline Stratifie
- **Fev 2026** : ClaimFirst complet, ApplicabilityFrame
- **Mar 2026** : Benchmarks framework, Response Modes V3, Perspectives V2
- **Avr 2026** : Corpus reglementaire (71 docs, 9483 claims), Mode Local LLM (RTX 5070 Ti), Domain Packs
