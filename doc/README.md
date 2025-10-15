# 🌊 OSMOSE - Documentation

**Documentation simplifiée du projet OSMOSE (KnowWhere)**

---

## 📖 Comment naviguer cette documentation

### 🎯 3 Fichiers Principaux (À la racine)

1. **Vision Produit**: [`OSMOSE_AMBITION_PRODUIT_ROADMAP.md`](./OSMOSE_AMBITION_PRODUIT_ROADMAP.md)
   - Ambition du projet
   - Différenciation vs concurrents (Copilot, Gemini)
   - Roadmap produit 32 semaines

2. **Architecture Technique**: [`OSMOSE_ARCHITECTURE_TECHNIQUE.md`](./OSMOSE_ARCHITECTURE_TECHNIQUE.md)
   - Architecture complète
   - Technologies utilisées
   - Décisions techniques

3. **Roadmap Globale**: [`OSMOSE_ROADMAP_INTEGREE.md`](./OSMOSE_ROADMAP_INTEGREE.md)
   - Vue d'ensemble 4 phases
   - Timeline et dépendances
   - Durée et objectifs

---

## 📋 Phases d'Implémentation

**1 FICHIER PAR PHASE dans [`phases/`](./phases/):**

- ✅ **Phase 1 (COMPLETE)**: [`phases/PHASE1_SEMANTIC_CORE.md`](./phases/PHASE1_SEMANTIC_CORE.md)
  - Composants livrés (TopicSegmenter, ConceptExtractor, SemanticIndexer, ConceptLinker)
  - Tests & Validation
  - Métriques finales

- 🔄 **Phase 2 (À venir)**: `phases/PHASE2_INTELLIGENCE_AVANCEE.md`
- 🔄 **Phase 3 (À venir)**: `phases/PHASE3_PRODUCTION_KG.md`
- 🔄 **Phase 4 (À venir)**: `phases/PHASE4_ADVANCED_FEATURES.md`

**Principe: 1 seul fichier par phase** = tout au même endroit, facile à suivre.

---

## 📁 Documents de Travail

**Tous les docs en cours, études, migrations → [`ongoing/`](./ongoing/)**

Ces documents sont des travaux en cours, des études exploratoires ou des plans de migration temporaires. Ils ne sont pas nécessaires pour comprendre le projet global.

Exemples:
- `ongoing/OSMOSE_PURE_MIGRATION.md` - Plan migration Phase 1.5
- `ongoing/OSMOSE_STATUS_ACTUEL.md` - Snapshot statut (mis à jour régulièrement)
- `ongoing/etudes/` - Études techniques exploratoires

---

## 📁 Archives

**Anciennes structures et docs obsolètes → [`archive/`](./archive/)**

Conservées pour historique uniquement.

---

## 📁 Structure Documentation (Simplifiée)

```
doc/
├── README.md                                      # Ce fichier (guide navigation)
│
├── OSMOSE_AMBITION_PRODUIT_ROADMAP.md            # Vision produit
├── OSMOSE_ARCHITECTURE_TECHNIQUE.md              # Architecture technique
├── OSMOSE_ROADMAP_INTEGREE.md                    # Roadmap globale 4 phases
│
├── phases/                                       # 1 fichier par phase
│   ├── PHASE1_SEMANTIC_CORE.md                   # Phase 1 ✅ COMPLETE
│   ├── PHASE2_INTELLIGENCE_AVANCEE.md            # Phase 2 (à venir)
│   ├── PHASE3_PRODUCTION_KG.md                   # Phase 3 (à venir)
│   └── PHASE4_ADVANCED_FEATURES.md               # Phase 4 (à venir)
│
├── ongoing/                                      # Docs de travail en cours
│   ├── OSMOSE_PURE_MIGRATION.md                  # Plan migration Phase 1.5
│   ├── OSMOSE_STATUS_ACTUEL.md                   # Snapshot statut actuel
│   └── etudes/                                   # Études techniques
│
└── archive/                                      # Archives (historique)
```

---

## 🚀 Quick Start

| Je veux...                          | Fichier à consulter                                                          |
| ----------------------------------- | ---------------------------------------------------------------------------- |
| Comprendre la vision produit        | [`OSMOSE_AMBITION_PRODUIT_ROADMAP.md`](./OSMOSE_AMBITION_PRODUIT_ROADMAP.md) |
| Voir l'architecture technique       | [`OSMOSE_ARCHITECTURE_TECHNIQUE.md`](./OSMOSE_ARCHITECTURE_TECHNIQUE.md)     |
| Voir le plan global (4 phases)      | [`OSMOSE_ROADMAP_INTEGREE.md`](./OSMOSE_ROADMAP_INTEGREE.md)                 |
| Comprendre Phase 1 (Semantic Core)  | [`phases/PHASE1_SEMANTIC_CORE.md`](./phases/PHASE1_SEMANTIC_CORE.md)         |
| Voir où on en est maintenant        | [`ongoing/OSMOSE_STATUS_ACTUEL.md`](./ongoing/OSMOSE_STATUS_ACTUEL.md)       |

---

## 📝 Principes de Documentation

1. **3 fichiers principaux** à la racine pour vision globale
2. **1 fichier par phase** dans `phases/` - Tout au même endroit
3. **Docs de travail** dans `ongoing/` - Ne polluent pas la racine
4. **Pas de duplication** - Chaque information à un seul endroit
5. **Structure stable** - Pas de création anarchique de fichiers

---

**Dernière mise à jour:** 2025-10-14
**Version:** 3.0 - Structure ultra-simplifiée
