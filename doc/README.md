# Documentation OSMOSIS

**Version :** 4.0 — Refondation Vision Mai 2026
**Projet :** OSMOSIS (Organic Semantic Memory Organization & Smart Extraction)

> Cette documentation a été refondée le 18 mai 2026 suite à la validation d'une nouvelle vision (modèle hiérarchique 2-niveaux Document+Claim, bitemporel, Probability Isolation, multi-domaines, traçabilité click-to-source). Le doc **VISION.md** absorbe et remplace les anciennes fondations (NORTH_STAR.md, VISION_PRODUIT.md, HISTORIQUE_PIVOTS.md) qui sont archivées dans `archive/2026-05_pre-vision-cleanup/`.

---

## Structure simplifiée

```
doc/
├── README.md                  # Ce fichier — guide de navigation
├── VISION.md                  # ⭐ Source de vérité produit + architecturale
├── EXECUTION_ROADMAP.md       # ⭐ Plan d'exécution (phases, kill switches, maturité)
├── ARCH_PIPELINE.md           # Pipeline stratifié Pass 0→3
├── ARCH_CLAIMFIRST.md         # Pipeline ClaimFirst 9 phases
├── ARCH_RETRIEVAL.md          # Graph-Guided RAG, Signal-Driven
├── ARCH_STOCKAGE.md           # Neo4j + Qdrant + PostgreSQL + Redis
├── OPS.md                     # Docker, kw.ps1, AWS, monitoring
├── DEV_GUIDE.md               # Structure code, conventions, endpoints
├── ongoing/
│   ├── adr/                   # 17 ADR structurants (architecture decisions)
│   ├── chantiers/             # 76 chantiers (historiques + en cours)
│   ├── etudes/                # 16 études exploratoires + reviews externes
│   └── sessions/              # 16 snapshots datés (bilans, rapports)
└── archive/
    ├── pre-rationalization-2026-03/   # 232 fichiers (archive de mars 2026)
    └── 2026-05_pre-vision-cleanup/    # 8 fichiers absorbés par VISION.md
```

---

## Documents fondateurs

### ⭐ Référence active (à lire en priorité)

| Document | Contenu | Quand le lire |
|----------|---------|---------------|
| [VISION.md](./VISION.md) | **Source de vérité unique** — mission, axiomes (AX-1 à AX-16), modèle épistémique bitemporel, capacités produit C1-C5, anti-vision, gouvernance | À chaque début de session, avant tout chantier |
| [EXECUTION_ROADMAP.md](./EXECUTION_ROADMAP.md) | **Plan d'exécution** — matrice de maturité composants, phasage A→D, kill switches K-1 à K-5, backlog ADR | Pour situer une tâche dans la roadmap |

### Architecture détaillée

| Document | Contenu |
|----------|---------|
| [ARCH_PIPELINE.md](./ARCH_PIPELINE.md) | Pipeline stratifié Pass 0→3, Docling, vision gating, extraction |
| [ARCH_CLAIMFIRST.md](./ARCH_CLAIMFIRST.md) | Pipeline ClaimFirst 9 phases, Facet Engine V2, marker normalization |
| [ARCH_RETRIEVAL.md](./ARCH_RETRIEVAL.md) | Graph-Guided RAG, Signal-Driven search, Concept Matching, Layer R |
| [ARCH_STOCKAGE.md](./ARCH_STOCKAGE.md) | Neo4j + Qdrant + PostgreSQL + Redis — schémas, collections |

### Opérationnel

| Document | Contenu |
|----------|---------|
| [OPS.md](./OPS.md) | Docker multi-compose, kw.ps1, Burst EC2 Spot, AWS, backup, monitoring |
| [DEV_GUIDE.md](./DEV_GUIDE.md) | Structure code, API endpoints, frontend pages, conventions |

---

## Documents de travail (`ongoing/`)

| Dossier | Contenu | Cas d'usage |
|---------|---------|-------------|
| [ongoing/adr/](./ongoing/adr/) | 17 ADR (Architecture Decision Records) | Décisions techniques majeures avec rationale et alternatives écartées |
| [ongoing/chantiers/](./ongoing/chantiers/) | 76 chantiers (CH-XX numérotés + récents) | Spécifications + résultats de chantiers d'implémentation |
| [ongoing/etudes/](./ongoing/etudes/) | 16 études exploratoires + reviews externes (Codex, Sonnet) | Recherches préliminaires, propositions non encore tranchées |
| [ongoing/sessions/](./ongoing/sessions/) | 16 snapshots datés (bilans de session, rapports, statuts) | Historique opérationnel |

---

## Documents archivés

| Dossier archive | Contenu |
|-----------------|---------|
| `archive/pre-rationalization-2026-03/` | 232 fichiers de l'avant-rationalisation (mars 2026) |
| `archive/2026-05_pre-vision-cleanup/` | 8 fichiers absorbés par VISION.md (NORTH_STAR, VISION_PRODUIT, HISTORIQUE_PIVOTS, MATRICE_TRACABILITE, TODOLIST, et brouillons obsolètes) |

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

## Pour un nouveau venu

Ordre de lecture recommandé :

1. **VISION.md** (~15 min) — comprendre ce qu'on construit et pourquoi
2. **EXECUTION_ROADMAP.md** (~10 min) — comprendre où on en est et où on va
3. **ARCH_PIPELINE.md** + **ARCH_CLAIMFIRST.md** (~30 min) — pipeline d'ingestion
4. **ARCH_RETRIEVAL.md** + **ARCH_STOCKAGE.md** (~30 min) — pipeline runtime et stockage
5. **OPS.md** + **DEV_GUIDE.md** (~20 min) — exploitation et conventions code

---

*Dernière mise à jour : 2026-05-18 (refondation Vision)*
