# 🌊 PROJET OSMOSE - Overview & Conventions

**Date:** 2025-10-13
**Statut:** Active Development
**Phase Actuelle:** Phase 0 → Phase 1 (Setup Infrastructure)

---

## 📛 Naming Conventions

### Produit
- **Nom Commercial:** **KnowWhere** (anciennement "KnowBase" ou "SAP KB")
- **Tagline:** *"Le Cortex Documentaire des Organisations"*
- **Positionnement:** Semantic Intelligence Knowledge Graph Platform

### Projet Pivot
- **Nom de Code:** **OSMOSE** (Organic Semantic Memory Organization & Smart Extraction)
- **Version Cible:** KnowWhere MVP 1.0
- **Architecture:** Dual-Graph Semantic Intelligence

### Différenciation vs Itérations Précédentes

| Itération | Objectif | Statut |
|-----------|----------|--------|
| **Back2Promise** | Retour aux promesses initiales, stabilisation | ✅ Complété |
| **NorthStar** | Vision long-terme, exploration concepts | ✅ Complété |
| **OSMOSE** 🌊 | **Pivot architectural complet - Semantic Intelligence** | 🚀 **EN COURS** |

**OSMOSE est le pivot majeur** qui transforme KnowWhere d'un RAG intelligent en une plateforme de Semantic Intelligence avec dual-graph architecture, narrative threads detection, et living ontology.

---

## 🎯 Objectif Projet OSMOSE

> **Transformer KnowWhere en la première plateforme d'Intelligence Sémantique Documentaire du marché**

### Ce qui change avec OSMOSE

**AVANT (Legacy)** :
- Extraction simple entities + RAG basique
- Neo4j single-graph
- Qdrant vector search
- Quality control manuel
- Ontologie statique

**APRÈS (OSMOSE)** :
- 🌊 **Dual-Graph Architecture** (Proto-KG → Published-KG)
- 🧠 **Semantic Intelligence Layer** (narrative threads, causal chains)
- 🤖 **Intelligent Gatekeeper** (auto-promotion multi-critères)
- 🌱 **Living Ontology** (pattern discovery automatique)
- 📊 **Volumetry Management** (lifecycle HOT/WARM/COLD/FROZEN)
- 🎨 **Context-Preserving Extraction** (intelligent clustering)

### Valeur Ajoutée Unique

**USP OSMOSE** :
1. **Evolution Tracking** : Timeline automatique d'évolution des concepts cross-documents
2. **Conflict Detection** : Détection contradictions entre versions documentaires
3. **Semantic Governance** : Quality control intelligent avec gatekeeper adaptatif
4. **Living Ontology** : Ontologie qui évolue automatiquement via pattern discovery

**Différenciation vs Competitors** :
- ❌ Microsoft Copilot : RAG basique, pas de narrative intelligence
- ❌ Google Gemini Workspace : Search sémantique, pas de cross-doc reasoning
- ✅ **KnowWhere (OSMOSE)** : Seul outil avec narrative threads + evolution tracking

---

## 📂 Structure Documentation OSMOSE

```
doc/
├── OSMOSE_PROJECT_OVERVIEW.md                    # Ce document (naming, overview)
├── OSMOSE_ARCHITECTURE_TECHNIQUE.md              # Spécification technique complète
├── OSMOSE_REFACTORING_PLAN.md                    # Plan migration existant → OSMOSE
├── OSMOSE_AMBITION_PRODUIT_ROADMAP.md            # Vision produit, GTM, roadmap 32 semaines
├── OSMOSE_FRONTEND_MIGRATION_STRATEGY.md         # Stratégie frontend parallèle
├── OSMOSE_PIVOT_ANALYSIS.md                      # Analyse faisabilité pivot
│
├── phase1_osmose/                                # Phase 1: Semantic Core (Sem 1-10)
│   ├── PHASE1_IMPLEMENTATION_PLAN.md             # Plan détaillé implémentation Phase 1
│   ├── PHASE1_TRACKING.md                        # Tracking progrès Phase 1
│   └── PHASE1_CHECKPOINTS.md                     # Critères validation checkpoints
│
├── phase2_osmose/                                # Phase 2: Dual-Graph + Gatekeeper (Sem 11-18)
├── phase3_osmose/                                # Phase 3: Living Intelligence (Sem 19-26)
├── phase4_osmose/                                # Phase 4: Enterprise Polish (Sem 27-32)
│
└── archive/
    ├── feat-neo4j-native/                        # Archives itérations précédentes
    ├── back2promise/
    └── northstar/
```

---

## 🚀 Roadmap OSMOSE - 32 Semaines

### Phase 1 : Semantic Core (Semaines 1-10)
**Objectif:** Démontrer USP unique avec cas d'usage KILLER (CRR Evolution)

**Composants Clés:**
- `SemanticDocumentProfiler` : Analyse intelligence document
- `NarrativeThreadDetector` : Détection fils narratifs cross-documents
- `IntelligentSegmentationEngine` : Clustering contextuel
- `DualStorageExtractor` : Extraction Proto-KG

**Checkpoint:** Démo CRR Evolution fonctionne, différenciation vs Copilot évidente

### Phase 2 : Dual-Graph + Gatekeeper (Semaines 11-18)
**Objectif:** Architecture scalable + quality control intelligent

**Composants Clés:**
- `Neo4jProtoManager` / `Neo4jPublishedManager`
- `SemanticIntelligentGatekeeper` : Multi-criteria scoring
- `PromotionOrchestrator` : Pipeline Proto → Published

**Checkpoint:** Gatekeeper >85% précision, Proto/Published opérationnels

### Phase 3 : Living Intelligence (Semaines 19-26)
**Objectif:** Différenciation ultime - ontologie vivante

**Composants Clés:**
- `LivingIntelligentOntology` : Pattern discovery
- `IntelligentVolumetryManager` : Lifecycle management
- `BudgetManager` : Cost optimization

**Checkpoint:** Patterns découverts automatiquement, volumétrie maîtrisée

### Phase 4 : Enterprise Polish + GTM (Semaines 27-32)
**Objectif:** MVP commercialisable, go-to-market ready

**Composants Clés:**
- Quality Control UI (frontend)
- Entity Constellation Explorer (D3 viz)
- Budget Intelligence Center
- Documentation complète + démos

**Checkpoint:** MVP 1.0 prêt pour premiers clients

---

## 💻 Conventions Code OSMOSE

### Naming Python

**Modules:**
```python
# Nouveau code OSMOSE
src/knowbase/semantic/           # Semantic Intelligence Layer
src/knowbase/semantic/profiler.py
src/knowbase/semantic/narrative_detector.py
src/knowbase/semantic/gatekeeper.py
src/knowbase/semantic/living_ontology.py
```

**Classes:**
```python
class SemanticDocumentProfiler:
    """Analyse l'intelligence sémantique du document (OSMOSE)"""
    pass

class NarrativeThreadDetector:
    """Détecte fils narratifs cross-documents (OSMOSE)"""
    pass
```

**Docstrings:**
```python
def analyze_document(self, document_path: str) -> DocumentIntelligence:
    """
    Analyse l'intelligence sémantique d'un document.

    Fait partie du système OSMOSE (Semantic Intelligence Layer).
    Détecte narrative threads, complexity zones, et alloue budget extraction.

    Args:
        document_path: Chemin vers le document à analyser

    Returns:
        DocumentIntelligence avec profil sémantique complet

    Note:
        OSMOSE Phase 1 - Semantic Core
    """
```

### Configuration

**Fichier:** `config/osmose_semantic_intelligence.yaml`

```yaml
# KnowWhere OSMOSE Configuration
# Semantic Intelligence Layer

project:
  name: "KnowWhere"
  codename: "OSMOSE"
  version: "1.0.0-alpha"

semantic_intelligence:
  profiler:
    enabled: true
    complexity_thresholds: [0.3, 0.6, 0.9]

  narrative_detection:
    enabled: true
    causal_connectors: ["because", "therefore", "as a result"]
    temporal_markers: ["revised", "updated", "replaced"]
```

### Feature Flags

```python
# config/features.yaml
extraction_mode: "SEMANTIC"  # SEMANTIC | LEGACY

# Code usage
if config.extraction_mode == "SEMANTIC":
    # OSMOSE semantic extraction
    profiler = SemanticDocumentProfiler()
else:
    # Legacy extraction (backward compatibility)
    extractor = LegacyExtractor()
```

---

## 📊 Métriques Succès OSMOSE

### Métriques Techniques (MVP)

| Métrique | Target | Priorité |
|----------|--------|----------|
| Narrative threads precision | >80% | 🔴 P0 |
| Gatekeeper auto-promotion rate | >85% | 🔴 P0 |
| Gatekeeper precision | >90% | 🔴 P0 |
| Processing speed | <45s/doc | 🟡 P1 |
| Proto-KG volumetry | <10k entities | 🟡 P1 |
| Cost per document | $0.40-0.80 | 🟢 P2 |

### Métriques Business (6 mois post-MVP)

| Métrique | Target | Priorité |
|----------|--------|----------|
| POCs signés | 3-5 | 🔴 P0 |
| Clients payants | 2-3 | 🔴 P0 |
| ARR | 50-150k€ | 🟡 P1 |
| NPS | >50 | 🟢 P2 |

---

## 🔗 Documents Référence OSMOSE

### Documents Stratégiques
1. **`OSMOSE_PIVOT_ANALYSIS.md`** : Analyse faisabilité, coûts, risques
2. **`OSMOSE_AMBITION_PRODUIT_ROADMAP.md`** : Vision produit, use cases, GTM
3. **`OSMOSE_ARCHITECTURE_TECHNIQUE.md`** : Spécification technique complète

### Documents Opérationnels
4. **`OSMOSE_REFACTORING_PLAN.md`** : Plan migration code existant
5. **`OSMOSE_FRONTEND_MIGRATION_STRATEGY.md`** : Stratégie frontend (ChakraUI)

### Documents Phase 1
6. **`phase1_osmose/PHASE1_IMPLEMENTATION_PLAN.md`** : Plan détaillé Sem 1-10
7. **`phase1_osmose/PHASE1_TRACKING.md`** : Tracking hebdomadaire progrès

---

## ⚠️ IMPORTANT - Conventions à Respecter

### ✅ À FAIRE
- ✅ Utiliser "KnowWhere" pour toute communication produit
- ✅ Utiliser "OSMOSE" pour référencer ce projet pivot
- ✅ Préfixer nouveaux modules avec `semantic/` (ex: `src/knowbase/semantic/`)
- ✅ Ajouter docstring mention "OSMOSE Phase X" dans nouveau code
- ✅ Feature flag `SEMANTIC | LEGACY` pour backward compatibility
- ✅ Logs structurés avec tag `[OSMOSE]` pour nouveau code

### ❌ À ÉVITER
- ❌ Ne plus utiliser "KnowBase" (ancien nom)
- ❌ Ne plus utiliser "SAP KB" (ancien nom technique)
- ❌ Ne pas mélanger code OSMOSE avec legacy sans feature flag
- ❌ Ne pas modifier code legacy sans tests backward compatibility
- ❌ Ne pas utiliser "NorthStar" ou "Back2Promise" pour ce pivot

---

## 🌊 Pourquoi "OSMOSE" ?

**OSMOSE** = **O**rganic **S**emantic **M**emory **O**rganization & **S**mart **E**xtraction

**Métaphore biologique** :
- 🧠 Comme l'osmose cellulaire, KnowWhere filtre et fait passer l'information importante (Proto → Published)
- 🌱 Processus organique : l'ontologie évolue naturellement (Living Ontology)
- 🔄 Équilibre dynamique : volumétrie managée (HOT/WARM/COLD)
- 🎯 Sélectivité intelligente : Gatekeeper comme membrane semi-perméable

**Symbolisme projet** :
- Fluidité et naturel (vs rigidité systèmes classiques)
- Intelligence émergente (patterns découverts automatiquement)
- Adaptation continue (thresholds adaptatifs)

---

## 📍 Prochaines Étapes

### Immédiat (Cette Session)
1. ✅ Renommer tous documents avec préfixe `OSMOSE_`
2. ✅ Mettre à jour contenu : "KnowBase" → "KnowWhere"
3. ✅ Créer structure `doc/phase1_osmose/`
4. ✅ Créer `PHASE1_IMPLEMENTATION_PLAN.md`
5. ✅ Créer `PHASE1_TRACKING.md`

### Phase 1 Semaine 1-2 (Next)
1. Créer structure `src/knowbase/semantic/`
2. Setup Neo4j Proto-KG schema
3. Setup Qdrant Proto collections
4. Configuration `config/osmose_semantic_intelligence.yaml`

---

**Version:** 1.0
**Auteur:** Solo Founder Journey
**Contact:** [À compléter]

---

> *"OSMOSE : Quand l'intelligence documentaire devient organique."* 🌊
