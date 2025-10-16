# Documentation KnowWhere - Projet OSMOSE

**Version:** 1.0
**Date:** 2025-10-16
**Status:** Phase 1.5 Finalisée - GO Phase 2

---

## Bienvenue

Bienvenue dans la documentation du projet **KnowWhere** (nom commercial) / **OSMOSE** (nom de code technique : Organic Semantic Memory Organization & Smart Extraction).

**Tagline** : *"Le Cortex Documentaire des Organisations - Comprendre vos documents ET maîtriser vos coûts"*

---

## Navigation Rapide

### 📘 Pour Démarrer

| Document | Description | Audience |
|----------|-------------|----------|
| [OSMOSE_PROJECT_OVERVIEW.md](./OSMOSE_PROJECT_OVERVIEW.md) | **Vue d'ensemble du projet**, naming, conventions | Tous |
| [README.md (racine)](../README.md) | Setup développement, installation locale | Développeurs |
| [CLAUDE.md (racine)](../CLAUDE.md) | Configuration Claude Code, conventions projet | Développeurs |

### 🏗️ Architecture & Roadmap

| Document | Description | Phase |
|----------|-------------|-------|
| [OSMOSE_ARCHITECTURE_TECHNIQUE.md](./OSMOSE_ARCHITECTURE_TECHNIQUE.md) | **Architecture complète V2.1** (4 composants core) | Phase 1 |
| [OSMOSE_ROADMAP_INTEGREE.md](./OSMOSE_ROADMAP_INTEGREE.md) | **Roadmap 37 semaines** (Phases 1-4 détaillées) | Toutes |
| [OSMOSE_AMBITION_PRODUIT_ROADMAP.md](./OSMOSE_AMBITION_PRODUIT_ROADMAP.md) | Vision produit, différenciation vs Copilot/Gemini | Produit |

### 🚀 Phase 1.5 - Architecture Agentique (FINALISÉE)

| Document | Description | Status |
|----------|-------------|--------|
| [phase1_osmose/PHASE1.5_TRACKING_V2.md](./phase1_osmose/PHASE1.5_TRACKING_V2.md) | **Tracking consolidé Phase 1.5** (95% complété) | ✅ Finalisé |
| [phase1_osmose/GUIDE_CANONICALISATION_ROBUSTE.md](./phase1_osmose/GUIDE_CANONICALISATION_ROBUSTE.md) | Guide canonicalisation robuste (37 pages) | ✅ Complété |

**Réalisations Phase 1.5** :
- ✅ 6 agents orchestrés (Supervisor, Extractor, Miner, Gatekeeper, Budget, Dispatcher)
- ✅ 18 tools JSON I/O stricts
- ✅ Architecture multi-tenant (Neo4j + Qdrant + Redis)
- ✅ Filtrage contextuel hybride (Graph + Embeddings, +30% précision)
- ✅ Canonicalisation robuste (P0.1-P1.3, sandbox + rollback + decision trace)
- ✅ 13,458 lignes code production-ready + 165 tests

### 📚 Guides Utilisateurs

| Document | Description | Audience |
|----------|-------------|----------|
| [UserGuide/ADMIN_GUIDE.md](./UserGuide/ADMIN_GUIDE.md) | **Guide administrateur complet** (tenants, LLM, ontologie, monitoring) | Admins |
| [UserGuide/OPS_GUIDE.md](./UserGuide/OPS_GUIDE.md) | **Guide opérations** (déploiement, scaling, monitoring, DR) | DevOps/SRE |

### 🔧 Configuration

| Fichier | Description |
|---------|-------------|
| `config/llm_models.yaml` | Configuration modèles LLM (SMALL/BIG/VISION) |
| `config/prompts.yaml` | Prompts personnalisables par famille |
| `config/sap_solutions.yaml` | Catalogue ontologie SAP |
| `config/canonicalization_thresholds.yaml` | Seuils adaptatifs canonicalisation (8 profils) |
| `config/agents/*.yaml` | Configuration agents (supervisor, routing, gates, budgets) |
| `config/grafana_dashboard.json` | Dashboard Grafana 18 panels |

---

## Status Phase 1.5 (2025-10-16)

### ✅ Réalisations Majeures

| Composant | Status | Lignes Code | Tests |
|-----------|--------|-------------|-------|
| **6 Agents Agentiques** | ✅ Complété | 1,896 | 70 tests |
| **Infrastructure Multi-Tenant** | ✅ Complété | 1,610 | 26 tests |
| **Filtrage Contextuel Hybride** | ✅ Complété | 930 | 38 tests |
| **Canonicalisation Robuste** | ✅ Complété | 4,330 | - |
| **Total** | **95% Finalisé** | **13,458** | **165 tests** |

### 📊 Décision Stratégique

**✅ GO Phase 2** : Architecture technique complète et production-ready

**Tests E2E reportés** : Semaine 14 Phase 2 (nécessite corpus dédié 50+ PDF, 1 semaine)

**Impact** : Aucun bloqueur technique. Validation performance non bloquante.

---

## Checklist Documentation par Rôle

### 👨‍💻 Développeur

1. ✅ [OSMOSE_PROJECT_OVERVIEW.md](./OSMOSE_PROJECT_OVERVIEW.md) (30 min)
2. ✅ [README.md racine](../README.md) - Setup local (1h)
3. ✅ [OSMOSE_ARCHITECTURE_TECHNIQUE.md](./OSMOSE_ARCHITECTURE_TECHNIQUE.md) (1h)

### 👨‍💼 Product Owner

1. ✅ [OSMOSE_AMBITION_PRODUIT_ROADMAP.md](./OSMOSE_AMBITION_PRODUIT_ROADMAP.md) (1h)
2. ✅ [OSMOSE_ROADMAP_INTEGREE.md](./OSMOSE_ROADMAP_INTEGREE.md) (1h)
3. ✅ [phase1_osmose/PHASE1.5_TRACKING_V2.md](./phase1_osmose/PHASE1.5_TRACKING_V2.md) (30 min)

### 🔧 Administrateur

1. ✅ [OSMOSE_ARCHITECTURE_TECHNIQUE.md](./OSMOSE_ARCHITECTURE_TECHNIQUE.md) (1h)
2. ✅ [UserGuide/ADMIN_GUIDE.md](./UserGuide/ADMIN_GUIDE.md) (2h)

### 🚀 DevOps / SRE

1. ✅ [OSMOSE_ARCHITECTURE_TECHNIQUE.md](./OSMOSE_ARCHITECTURE_TECHNIQUE.md) (1h)
2. ✅ [UserGuide/OPS_GUIDE.md](./UserGuide/OPS_GUIDE.md) (2h)

---

## Structure Documentation

```
doc/
├── README.md                              # Ce fichier (index principal)
├── OSMOSE_PROJECT_OVERVIEW.md             # Overview projet
├── OSMOSE_ARCHITECTURE_TECHNIQUE.md       # Architecture V2.1
├── OSMOSE_ROADMAP_INTEGREE.md             # Roadmap 37 semaines
├── OSMOSE_AMBITION_PRODUIT_ROADMAP.md     # Vision produit
│
├── phase1_osmose/                         # Phase 1.5
│   ├── PHASE1.5_TRACKING_V2.md            # Tracking (95% complété)
│   └── GUIDE_CANONICALISATION_ROBUSTE.md  # Guide canonicalisation
│
├── UserGuide/                             # Guides utilisateurs
│   ├── ADMIN_GUIDE.md                     # Guide administrateur
│   └── OPS_GUIDE.md                       # Guide opérations
│
└── archive/                               # Documentation historique
```

---

## Monitoring

- **Grafana Dashboard** : http://localhost:3001
- **Prometheus** : http://localhost:9090
- **Neo4j Browser** : http://localhost:7474
- **Qdrant Dashboard** : http://localhost:6333/dashboard

---

**Version** : 1.0
**Dernière mise à jour** : 2025-10-16
**Maintenu par** : Équipe OSMOSE
