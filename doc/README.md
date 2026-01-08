# Documentation KnowWhere - Projet OSMOSE

**Version:** 2.0
**Date:** 2025-11-15
**Status:** Phase 1 Finalisée - Phase 2 En Cours

---

## Bienvenue

Bienvenue dans la documentation du projet **KnowWhere** (nom commercial) / **OSMOSE** (nom de code technique : Organic Semantic Memory Organization & Smart Extraction).

**Tagline** : *"Le Cortex Documentaire des Organisations - Comprendre vos documents ET maîtriser vos coûts"*

---

## 🏷️ Naming & Positionnement

- **Nom commercial** : **KnowWhere**
- **Nom de code** : **OSMOSE** (Organic Semantic Memory Organization & Smart Extraction)
- **Positionnement** : Plateforme d'intelligence sémantique documentaire

---

## 📚 Navigation Rapide

### 🎯 Documents Principaux (Racine)

| Document | Description | Audience |
|----------|-------------|----------|
| [OSMOSE_AMBITION_PRODUIT_ROADMAP.md](./OSMOSE_AMBITION_PRODUIT_ROADMAP.md) | Vision produit, différenciation vs Copilot/Gemini | Product Owners |
| [OSMOSE_ARCHITECTURE_TECHNIQUE.md](./OSMOSE_ARCHITECTURE_TECHNIQUE.md) | Architecture complète V2.1 (Dual-Graph Intelligence) | Développeurs, Architectes |
| [OSMOSE_ROADMAP_INTEGREE.md](./OSMOSE_ROADMAP_INTEGREE.md) | Roadmap 4 phases (32 semaines) | Tous |
| [PROCESSUS_IMPORT_DOCUMENT.md](./PROCESSUS_IMPORT_DOCUMENT.md) | Guide détaillé : Comment un document est traité | Utilisateurs, PO |

### 🧭 Fondations & ADN OSMOSE

| Document | Description | Audience |
|----------|-------------|----------|
| [foundations/OSMOSE_PRINCIPLES.md](./foundations/OSMOSE_PRINCIPLES.md) | Principes non négociables (agnostique, maturité, gouvernance) | Tous |
| [foundations/KG_AGNOSTIC_ARCHITECTURE.md](./foundations/KG_AGNOSTIC_ARCHITECTURE.md) | Modèle 5 couches & invariants | Architectes |

### 📖 Documentation par Phase

| Document | Description | Status |
|----------|-------------|--------|
| [phases/PHASE1_SEMANTIC_CORE.md](./phases/PHASE1_SEMANTIC_CORE.md) | **Phase 1 complète** (Semaines 1-10) : Semantic Core | ✅ Finalisé |
| [phases/PHASE2_INTELLIGENCE.md](./phases/PHASE2_INTELLIGENCE.md) | **Phase 2** (Semaines 14-24) : Intelligence Relationnelle | 🔄 En cours |

**Réalisations Phase 1** :
- ✅ Topic segmentation intelligente
- ✅ Concept extraction multi-niveaux (NER + clustering + LLM)
- ✅ Canonicalisation cross-linguale
- ✅ Proto-KG (Neo4j + Qdrant)
- ✅ Chunking adaptatif avec métadonnées sémantiques

### 📘 Guides Pratiques

| Document | Description | Audience |
|----------|-------------|----------|
| [guides/OSMOSE_PURE_GUIDE.md](./guides/OSMOSE_PURE_GUIDE.md) | Guide complet OSMOSE Pure (migration, rebuild, tests) | Développeurs |
| [guides/GUIDE_CANONICALISATION_ROBUSTE.md](./guides/GUIDE_CANONICALISATION_ROBUSTE.md) | Canonicalisation robuste (37 pages) | Développeurs, Data Scientists |

### 🔧 Opérations & Déploiement

| Document | Description | Audience |
|----------|-------------|----------|
| [operations/ADMIN_GUIDE.md](./operations/ADMIN_GUIDE.md) | Guide administrateur (tenants, LLM, monitoring) | Admins |
| [operations/OPS_GUIDE.md](./operations/OPS_GUIDE.md) | Guide opérations (déploiement, scaling, DR) | DevOps/SRE |
| [operations/AWS_DEPLOYMENT_GUIDE.md](./operations/AWS_DEPLOYMENT_GUIDE.md) | Déploiement AWS (EC2, S3, Secrets Manager) | DevOps |
| [operations/AWS_COST_MANAGEMENT.md](./operations/AWS_COST_MANAGEMENT.md) | Gestion des coûts AWS | DevOps, Finance |

### 🧭 Décisions (ADR)

| Document | Description | Audience |
|----------|-------------|----------|
| [decisions/README.md](./decisions/README.md) | Index des ADR (1 décision = 1 ADR) | Architectes, Leads |

### 🧱 Spécifications (Specs)

| Document | Description | Audience |
|----------|-------------|----------|
| [specs/README.md](./specs/README.md) | Index des specs techniques | Dev, Architectes |

### 📌 Suivi (Tracking)

| Document | Description | Audience |
|----------|-------------|----------|
| [tracking/README.md](./tracking/README.md) | Statut, plans, backlog | Tous |

### 🔬 Research & Analyses

Docs exploratoires, comparatifs, benchmarks, audits.

**📂 Voir** : [research/README.md](./research/README.md)

---

## 🏗️ Structure Documentation Complète

```
doc/
├── README.md                               # ← Vous êtes ici
├── OSMOSE_AMBITION_PRODUIT_ROADMAP.md     # Vision produit
├── OSMOSE_ARCHITECTURE_TECHNIQUE.md       # Architecture technique
├── OSMOSE_ROADMAP_INTEGREE.md             # Roadmap 4 phases
├── PROCESSUS_IMPORT_DOCUMENT.md           # Guide import documents
│
├── foundations/                           # ADN / principes fondateurs
│   ├── OSMOSE_PRINCIPLES.md
│   ├── KG_AGNOSTIC_ARCHITECTURE.md
│   └── ...
│
├── decisions/                             # ADR (1 décision = 1 ADR)
│   ├── README.md
│   └── ADR_*.md
│
├── specs/                                 # Spécifications techniques
│   ├── README.md
│   └── ...
│
├── tracking/                              # Suivi, plans, backlog
│   ├── README.md
│   └── ...
│
├── research/                              # Analyses, benchmarks, audits
│   ├── README.md
│   └── ...
│
├── phases/                                # Documentation par phase
│   ├── PHASE1_SEMANTIC_CORE.md           # ✅ Phase 1 complète
│   └── PHASE2_INTELLIGENCE.md            # 🔄 Phase 2 (en cours)
│
├── guides/                                # Guides pratiques
│   ├── OSMOSE_PURE_GUIDE.md              # Guide OSMOSE Pure
│   └── GUIDE_CANONICALISATION_ROBUSTE.md  # Guide canonicalisation
│
├── operations/                            # Ops & Déploiement
│   ├── ADMIN_GUIDE.md
│   ├── OPS_GUIDE.md
│   ├── AWS_DEPLOYMENT_GUIDE.md
│   └── AWS_COST_MANAGEMENT.md
│
└── archive/                               # Archives historiques
    ├── diagnostics_2024/                 # Diagnostics datés
    ├── phase1_osmose_old/                # Ancien suivi Phase 1
    └── feat-neo4j-native/                # Ancienne branche
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

## 🚀 Checklist Démarrage par Rôle

### 👨‍💻 Développeur

1. ✅ [README.md racine](../README.md) - Setup local (1h)
2. ✅ [foundations/OSMOSE_PRINCIPLES.md](./foundations/OSMOSE_PRINCIPLES.md) (20 min)
3. ✅ [OSMOSE_ARCHITECTURE_TECHNIQUE.md](./OSMOSE_ARCHITECTURE_TECHNIQUE.md) (1h)
4. ✅ [PROCESSUS_IMPORT_DOCUMENT.md](./PROCESSUS_IMPORT_DOCUMENT.md) (30 min)
5. ✅ [phases/PHASE1_SEMANTIC_CORE.md](./phases/PHASE1_SEMANTIC_CORE.md) (1h)

### 👨‍💼 Product Owner

1. ✅ [OSMOSE_AMBITION_PRODUIT_ROADMAP.md](./OSMOSE_AMBITION_PRODUIT_ROADMAP.md) (1h)
2. ✅ [foundations/OSMOSE_PRINCIPLES.md](./foundations/OSMOSE_PRINCIPLES.md) (20 min)
3. ✅ [OSMOSE_ROADMAP_INTEGREE.md](./OSMOSE_ROADMAP_INTEGREE.md) (1h)
4. ✅ [PROCESSUS_IMPORT_DOCUMENT.md](./PROCESSUS_IMPORT_DOCUMENT.md) (30 min)

### 🔧 Administrateur

1. ✅ [OSMOSE_ARCHITECTURE_TECHNIQUE.md](./OSMOSE_ARCHITECTURE_TECHNIQUE.md) (1h)
2. ✅ [operations/ADMIN_GUIDE.md](./operations/ADMIN_GUIDE.md) (2h)

### 🚀 DevOps / SRE

1. ✅ [operations/OPS_GUIDE.md](./operations/OPS_GUIDE.md) (2h)
2. ✅ [operations/AWS_DEPLOYMENT_GUIDE.md](./operations/AWS_DEPLOYMENT_GUIDE.md) (1h)

---

## 📈 État Projet (2025-11-15)

### Phase 1 : Semantic Core ✅
- **Status** : Finalisé
- **Durée** : 10 semaines
- **Composants** : Topic segmentation, concept extraction, canonicalisation, Proto-KG
- **Résultat** : Pipeline production-ready avec GPU acceleration

### Phase 2 : Intelligence Relationnelle 🔄
- **Status** : En cours
- **Objectif** : Relations sémantiques typées (12 types)
- **Début** : Semaine 14
- **Durée prévue** : 11 semaines

---

**Version** : 2.0
**Dernière mise à jour** : 2025-11-15
**Maintenu par** : Équipe OSMOSE
