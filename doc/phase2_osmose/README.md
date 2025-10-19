# 🌊 Phase 2 OSMOSE - Intelligence Relationnelle Avancée

**Répertoire:** `doc/phase2_osmose/`
**Status:** 🟡 NOT STARTED
**Durée:** Semaines 14-24 (11 semaines)
**Date Début Prévue:** 2025-10-19

---

## 📁 Structure Répertoire

```
phase2_osmose/
├── README.md                          # Ce fichier
├── PHASE2_EXECUTIVE_SUMMARY.md        # Vision & objectifs Phase 2
├── PHASE2_TRACKING.md                 # Suivi détaillé implémentation
└── (à venir)
    ├── PHASE2_ARCHITECTURE.md         # Design technique composants
    ├── PHASE2_API_REFERENCE.md        # Documentation API relations
    └── PHASE2_BENCHMARKS.md           # Résultats tests & métriques
```

---

## 🎯 Qu'est-ce que la Phase 2 ?

### Vision

> **"Transformer le graphe de concepts en tissu sémantique vivant."**

La Phase 2 enrichit l'architecture OSMOSE (Phase 1.5) avec une **intelligence relationnelle avancée** :

- **Relations typées** (USES, PART_OF, REQUIRES, etc.) vs simple co-occurrence
- **Hiérarchies produit** auto-construites (taxonomy)
- **Évolution temporelle** structurée (breaking changes, feature deltas)
- **Inférence logique** (relations transitives, cohérence validation)
- **Consolidation multi-sources** (consensus, conflict resolution)

### Différenciation Competitive

| Capability | Microsoft Copilot | Google Gemini | **OSMOSE Phase 2** |
|------------|-------------------|---------------|-------------------|
| **Relations typées** | ❌ | ❌ | ✅ 8+ types (USES, PART_OF, etc.) |
| **Hiérarchies produit** | ❌ | ❌ | ✅ Taxonomy auto-construite |
| **Évolution temporelle** | ⚠️ Mentions basiques | ⚠️ Générative | ✅ Delta structuré + breaking changes |
| **Relations inférées** | ❌ | ❌ | ✅ Transitive + coherence validation |
| **Graphe sémantique** | ❌ RAG flat | ❌ Embeddings only | ✅ Neo4j structuré + cross-ref Qdrant |

---

## 📚 Documentation

### Pour Commencer

1. **Lire en premier :** `PHASE2_EXECUTIVE_SUMMARY.md`
   - Vision stratégique
   - Objectifs clés (5 composants)
   - Use cases killer (CRR Evolution Tracker, Product Dependencies)

2. **Suivi implémentation :** `PHASE2_TRACKING.md`
   - Planning jour par jour (55 jours)
   - Checkpoints & livrables
   - KPIs & métriques temps réel

3. **Architecture technique :** `PHASE2_ARCHITECTURE.md` *(à créer)*
   - Design composants (RelationExtractionEngine, TaxonomyBuilder, etc.)
   - Schéma Neo4j relations
   - Flows de données

---

## 🎯 Objectifs Phase 2 (Résumé)

### 1. RelationExtractionEngine (Semaines 14-15)

**Objectif :** Détecter 8 types de relations sémantiques typées

**Types relations :**
- `PART_OF` : Composant → Système parent
- `USES` : Technologie → Dépendance
- `REPLACES` : Évolution produit
- `REQUIRES` : Prérequis fonctionnel
- `EXTENDS` : Extension/Add-on
- `INTEGRATES_WITH` : Intégration système
- `ENABLES` : Capacité fonctionnelle
- `COMPETES_WITH` : Alternative marché

**KPIs :**
- Precision ≥ 80%
- Recall ≥ 65%
- ≥ 70% concepts ont ≥ 1 relation typée

---

### 2. TaxonomyBuilder (Semaines 16-17)

**Objectif :** Organiser concepts en hiérarchies produit

**Méthode :**
- Clustering domaines (embeddings K-means)
- Détection relations PART_OF hiérarchiques
- Construction arbre taxonomy (max depth 5)

**KPIs :**
- Coverage ≥ 80% concepts
- 0 cycles détectés
- Profondeur moyenne : 2-4 niveaux

---

### 3. TemporalDiffEngine (Semaines 18-19)

**Objectif :** Détection évolutions produit + breaking changes

**Use Case Killer :** CRR Evolution Tracker Enhanced

**Fonctionnalités :**
- Détection versions automatique (regex + NER)
- Feature diff analysis (ADDED, REMOVED, UNCHANGED)
- Classification severity (MAJOR/MINOR/PATCH)
- Migration effort estimator

**KPIs :**
- Temporal relations ≥ 90% versioned concepts
- Precision delta detection ≥ 75%

---

### 4. RelationInferenceEngine (Semaines 20-21)

**Objectif :** Inférer relations implicites via raisonnement logique

**Fonctionnalités :**
- Transitive inference (PART_OF, REQUIRES)
- Coherence validation (cycles, conflits)
- Explainability (justification chains)

**KPIs :**
- ≥ 30% relations inférées
- 0 incohérences logiques
- Validation < 5s pour 10k concepts

---

### 5. CrossDocRelationMerger (Semaines 22-24)

**Objectif :** Consolidation multi-sources + conflict resolution

**Fonctionnalités :**
- Relation similarity detection
- Confidence aggregation (weighted avg)
- Recency vs confidence arbitrage
- Human validation flagging

**KPIs :**
- ≥ 60% relations consolidées multi-docs
- Conflict rate < 8%
- Consensus strength "HIGH" pour ≥ 70% relations

---

## 🚀 Quick Start (Semaine 14)

### Prérequis

```bash
# Python dependencies Phase 2
pip install sentence-transformers==2.2.2
pip install scikit-learn==1.3.0
pip install networkx==3.1

# Neo4j schema extensions
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass < schema_phase2.cypher
```

### Setup Corpus Test

```bash
# Sélection documents SAP (100 docs)
cp data/test_corpus/sap_s4hana_overview.pptx data/phase2_test/
cp data/test_corpus/sap_btp_architecture.pptx data/phase2_test/
cp data/test_corpus/sap_ccr_2020_2025/* data/phase2_test/

# Annotation manuelle 50 relations (gold standard)
python scripts/annotate_relations_gold_standard.py
```

### Premier Composant (RelationExtractionEngine)

```bash
# Créer structure code
mkdir -p src/knowbase/relations
touch src/knowbase/relations/__init__.py
touch src/knowbase/relations/extraction_engine.py

# Tests unitaires
mkdir -p tests/relations
touch tests/relations/test_extraction_engine.py

# Lancer développement (voir PHASE2_TRACKING.md J1-J10)
```

---

## 📊 Métriques de Succès (GO/NO-GO Phase 3)

### KPIs Critiques

| KPI | Target | Critique |
|-----|--------|----------|
| **Relations typées / concept** | ≥ 1.5 moyenne | ✅ OUI |
| **Coverage taxonomy** | ≥ 80% concepts | ✅ OUI |
| **Precision relation extraction** | ≥ 80% | ✅ OUI |
| **Recall relation extraction** | ≥ 65% | ⚠️ Nice-to-have |
| **Temporal relations** | ≥ 90% versioned concepts | ✅ OUI |
| **Relations inférées** | ≥ 30% total relations | ⚠️ Nice-to-have |
| **Conflict rate** | < 8% | ✅ OUI |
| **Cycles détectés** | 0 | ✅ OUI |

---

## 🎬 Démos Use Cases (Checkpoint S24)

### UC1 : SAP Product Dependencies

**Question :** *"Quelles sont toutes les dépendances de SAP Ariba ?"*

**Démo attendue :**
- Relations directes (REQUIRES) : SAP BTP, SAP Cloud Identity
- Relations indirectes inférées : SAP HANA Cloud (via BTP)
- Hiérarchie : SAP Solutions > SAP Procurement > SAP Ariba
- Chunks justificatifs cross-référencés

---

### UC2 : CRR Evolution Tracker

**Question :** *"Quels breaking changes entre SAP CCR 2020 et 2025 ?"*

**Démo attendue :**
- Timeline : 2020 → 2021 → 2023 → 2025
- Breaking changes détectés :
  - 2020→2021 : XML format deprecated
  - 2021→2023 : Manual validation removed
- Migration effort estimé : HIGH (40-60h)
- Documentation chunks liés

---

### UC3 : Taxonomy Navigation

**Question :** *"Liste tous les composants de SAP S/4HANA Cloud ?"*

**Démo attendue :**
- Hiérarchie complète via PART_OF transitive
- SAP S/4HANA Cloud → SAP Fiori → SAP Fiori Launchpad
- SAP S/4HANA Cloud → SAP Analytics Cloud → SAP Analytics Designer
- Grafana viz interactive

---

## 🔗 Liens Utiles

### Documentation Projet
- [Phase 1.5 (Agentique)](../PHASE1_TRACKING.md)
- [Roadmap Globale](../OSMOSE_ROADMAP_INTEGREE.md)
- [Architecture Technique](../OSMOSE_ARCHITECTURE_TECHNIQUE.md)

### Ressources Externes
- [Neo4j Graph Algorithms](https://neo4j.com/docs/graph-data-science/)
- [spaCy Dependency Parsing](https://spacy.io/usage/linguistic-features#dependency-parse)
- [Sentence Transformers](https://www.sbert.net/)

### Benchmarks Référence
- Google Knowledge Graph (relation extraction ~85% precision)
- WordNet (taxonomy coverage ~90%)
- ChangeLog parsers (temporal diff ~80% accuracy)

---

## ⚠️ Notes Importantes

### Prérequis Phase 1.5

**La Phase 2 nécessite Phase 1.5 complétée :**
- ✅ Architecture agentique opérationnelle (6 agents + 18 tools)
- ✅ Concepts canoniques dans Neo4j Published KG
- ✅ LLMCanonicalizer fonctionnel (normalisation noms)
- ✅ GraphCentralityScorer (réutilisé pour co-occurrences)
- ✅ Cross-référence Neo4j ↔ Qdrant chunks

**Si Phase 1.5 incomplète :** Compléter d'abord avant démarrage Phase 2.

---

### Risques Identifiés

| Risque | Mitigation |
|--------|-----------|
| **Precision relation < 80%** | Tuning prompts LLM + enrichir patterns |
| **Coverage taxonomy < 80%** | Clustering adaptatif + LLM fallback |
| **Performance queries > 5s** | Indexation Neo4j + caching |
| **Cycles non détectés** | Tests exhaustifs + validation continue |

---

## 📞 Contact & Support

**Questions Phase 2 :**
- Consulter `PHASE2_TRACKING.md` pour détails implémentation
- Consulter `PHASE2_EXECUTIVE_SUMMARY.md` pour vision stratégique

**Mise à Jour Documentation :**
- Fréquence : Tous les 3 jours (checkpoints)
- Responsable : Lead Dev Phase 2
- Review : Architect OSMOSE

---

**Dernière Mise à Jour :** 2025-10-19
**Prochaine Review :** Semaine 14 J3 (Checkpoint design)
