# Documentation OSMOSIS

**Version :** 3.0 — Rationalisation Mars 2026
**Projet :** OSMOSIS (Organic Semantic Memory Organization & Smart Extraction)

---

## Structure

Cette documentation a été rationalisée le 29 mars 2026. Les 232 fichiers originaux sont archivés dans `archive/pre-rationalization-2026-03/`. La matrice de traçabilité garantit qu'aucune substance décisionnelle n'a été perdue.

### Fondations (3 docs)

| Document | Contenu |
|----------|---------|
| [NORTH_STAR.md](./NORTH_STAR.md) | **Invariants inviolables**, principes fondateurs, Decision Defense, pistes écartées critiques, profils de visibilité |
| [VISION_PRODUIT.md](./VISION_PRODUIT.md) | Positionnement produit, 5 capacités, différenciation vs Copilot/RAG, marché cible, usages A/B/C |
| [HISTORIQUE_PIVOTS.md](./HISTORIQUE_PIVOTS.md) | Timeline chronologique, pivots architecturaux, phases complétées, leçons apprises |

### Architecture (4 docs)

| Document | Contenu |
|----------|---------|
| [ARCH_PIPELINE.md](./ARCH_PIPELINE.md) | **Pipeline stratifié Pass 0→3**, Docling, vision gating, extraction, linking — vérifié contre le code |
| [ARCH_CLAIMFIRST.md](./ARCH_CLAIMFIRST.md) | **Pipeline ClaimFirst** 9 phases, Facet Engine V2, marker normalization, corpus promotion |
| [ARCH_RETRIEVAL.md](./ARCH_RETRIEVAL.md) | **Graph-Guided RAG**, Signal-Driven search, Concept Matching, Layer R, synthèse tiered |
| [ARCH_STOCKAGE.md](./ARCH_STOCKAGE.md) | **Neo4j + Qdrant + PostgreSQL + Redis** — schémas, collections, configuration |

### Chantiers actifs (5 docs)

| Document | Contenu |
|----------|---------|
| [CHANTIER_BENCHMARK.md](./CHANTIER_BENCHMARK.md) | Framework 320 questions, dual-judge, scores Sprint 0→2, architecture LLM tiered |
| [CHANTIER_CHUNKING.md](./CHANTIER_CHUNKING.md) | Diagnostic chunking (70% < 100 chars), stratégie rechunking, unité preuve vs lecture |
| [CHANTIER_ATLAS.md](./CHANTIER_ATLAS.md) | Atlas cognitif 3 phases, Concept Assembly Engine, Wikipedia OSMOSIS |
| [CHANTIER_COCKPIT.md](./CHANTIER_COCKPIT.md) | Cockpit opérationnel, 6 widgets, design system, architecture indépendante |
| [CHANTIER_KG_QUALITY.md](./CHANTIER_KG_QUALITY.md) | 6 chantiers qualité KG, Entity Resolution, déduplication acronymes |

### Ops & Dev (2 docs)

| Document | Contenu |
|----------|---------|
| [OPS.md](./OPS.md) | Docker multi-compose, kw.ps1, Burst EC2 Spot, AWS, backup, monitoring, purge |
| [DEV_GUIDE.md](./DEV_GUIDE.md) | Structure code, API endpoints, frontend pages, feature flags, conventions |

### Suivi & Traçabilité

| Document | Contenu |
|----------|---------|
| [TODOLIST.md](./TODOLIST.md) | **Plan d'exécution** : 4 phases, tâches ordonnancées, critères GO/NO-GO. Tâche terminée → mise à jour doc source → suppression ici. |
| [MATRICE_TRACABILITE_RATIONALIZATION.md](./MATRICE_TRACABILITE_RATIONALIZATION.md) | Preuve du refacto : 19 invariants, 27 pistes écartées, 20+ travaux non terminés, mapping sources→cibles |

---

## Interfaces

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API Swagger | http://localhost:8000/docs |
| Neo4j Browser | http://localhost:7474 |
| Qdrant Dashboard | http://localhost:6333/dashboard |
| Grafana | http://localhost:3001 |

---

## Archive

`doc/archive/pre-rationalization-2026-03/` contient les 232 fichiers originaux organisés par répertoire (adr/, specs/, ongoing/, research/, etc.). Consulter la matrice de traçabilité pour retrouver l'origine de chaque décision.

---

*Dernière mise à jour : 2026-03-29*
