# Documentation KnowWhere - Projet OSMOSE

**Version:** 2.1
**Date:** 2026-01-06
**Status:** Phase 2 en cours

---

## Bienvenue

Bienvenue dans la documentation du projet **KnowWhere** (nom commercial) / **OSMOSE** (nom de code technique : Organic Semantic Memory Organization & Smart Extraction).

**Tagline** : *"Le Cortex Documentaire des Organisations - Comprendre vos documents ET maîtriser vos coûts"*

---

## 📚 Accès rapides par audience

### 👨‍💻 Développeurs

1. [Architecture technique](./architecture/OSMOSE_ARCHITECTURE_TECHNIQUE.md)
2. [Specs extraction (index)](./specs/extraction/)
3. [Guide OSMOSE Pure](./guides/OSMOSE_PURE_GUIDE.md)
4. [Guide import documents](./specs/ingestion/SPEC-PROCESSUS_IMPORT_DOCUMENT.md)

### 🧱 Architectes / Lead Tech

1. [ADN OSMOSE - Graph First](./foundations/GRAPH_FIRST_PRINCIPLE.md)
2. [Architecture de référence](./architecture/OSMOSE_ARCHITECTURE_TECHNIQUE.md)
3. [Décisions d’architecture (ADR)](./adr/README.md)
4. [Déploiement](./architecture/ARCHITECTURE_DEPLOIEMENT.md)

### 👨‍💼 Product Owner / Direction

1. [Ambition & Roadmap produit](./phases/OSMOSE_AMBITION_PRODUIT_ROADMAP.md)
2. [Roadmap intégrée](./phases/OSMOSE_ROADMAP_INTEGREE.md)
3. [Phase 1 : Semantic Core](./phases/PHASE1_SEMANTIC_CORE.md)

### 🔧 Ops / SRE

1. [Guide opérations](./operations/OPS_GUIDE.md)
2. [Guide admin](./operations/ADMIN_GUIDE.md)
3. [Déploiement AWS](./operations/AWS_DEPLOYMENT_GUIDE.md)
4. [Coûts AWS](./operations/AWS_COST_MANAGEMENT.md)

### 🔬 Recherche & Analyse

1. [Études et analyses](./research/)
2. [Suivi d’exécution](./tracking/)

---

## 🧭 Conventions de nommage

- **ADR** : `ADR-YYYYMMDD-slug.md` (voir [adr/README.md](./adr/README.md))
- **Specs** : `SPEC-<sujet>.md` par domaine (`specs/extraction`, `specs/graph`, `specs/ingestion`)
- **Tracking** : `TRACKING-<sujet>.md`

---

## 🗂️ Structure documentaire (stable)

```
doc/
├── README.md                         # Index global + parcours par audience
├── foundations/                      # Invariants / ADN OSMOSE
│   ├── KG_AGNOSTIC_ARCHITECTURE.md
│   └── GRAPH_FIRST_PRINCIPLE.md
├── adr/                              # Decisions d’architecture
│   ├── README.md                     # Index ADR (statut, tags)
│   └── ADR-YYYYMMDD-graph-first-architecture.md
├── architecture/                     # Architecture de référence (stables)
│   ├── OSMOSE_ARCHITECTURE_TECHNIQUE.md
│   └── ARCHITECTURE_DEPLOIEMENT.md
├── specs/                            # Spécifications techniques
│   ├── extraction/
│   ├── graph/
│   └── ingestion/
├── guides/                           # Guides pratiques dev
├── operations/                       # Runbook, déploiement, SRE
├── phases/                           # Roadmaps/phase delivery
├── research/                         # Études et analyses exploratoires
├── tracking/                         # Suivi d’exécution (journalisé)
└── archive/                          # Historique obsolète
```

---

## 🔧 Configuration Projet

| Fichier | Description |
|---------|-------------|
| `config/llm_models.yaml` | Configuration modèles LLM (SMALL/BIG/VISION) |
| `config/prompts.yaml` | Prompts personnalisables par famille |
| `config/sap_solutions.yaml` | Catalogue ontologie SAP |
| `config/semantic_intelligence_v2.yaml` | Configuration OSMOSE (embeddings, segmentation, extraction) |

---

## 📊 Monitoring & Interfaces

- **Frontend** : http://localhost:3000
- **API Docs (Swagger)** : http://localhost:8000/docs
- **Neo4j Browser** : http://localhost:7474
- **Qdrant Dashboard** : http://localhost:6333/dashboard
- **Grafana** : http://localhost:3001
- **Prometheus** : http://localhost:9090

---

**Dernière mise à jour** : 2026-01-06
**Maintenu par** : Équipe OSMOSE
