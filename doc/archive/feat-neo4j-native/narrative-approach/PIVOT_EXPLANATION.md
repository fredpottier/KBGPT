# 🔄 Archive: Approche Narrative (Abandonnée)

**Date Archive:** 2025-10-14
**Raison:** Pivot vers Architecture V2.1 (Concept-First, Language-Agnostic)

---

## Pourquoi cette approche a été abandonnée

### ❌ Problèmes Identifiés

**1. Mauvais Focus Fonctionnel**
- Focus: Narrative threads, causal chains, temporal evolution
- Besoin réel: Concept extraction pour documents descriptifs (guidelines, standards, architecture)
- **Conclusion**: Over-engineering pour des use cases inexistants en production

**2. Pas Language-Agnostic**
- Keywords hardcodés en anglais uniquement:
  - `causal_connectors = ["because", "therefore", "as a result"]`
  - `temporal_markers = ["revised", "updated", "superseded"]`
- **Problème**: Multinationales ont docs FR/EN/DE mixés
- **Conclusion**: Non-scalable pour environnements multilingues réels

**3. Pas de Cross-Lingual Unification**
- Aucun mécanisme pour unifier:
  - FR "authentification" = EN "authentication" = DE "Authentifizierung"
- **Problème**: Concepts dupliqués par langue dans le KG
- **Conclusion**: KG fragmenté, pas de vue unifiée cross-lingual

**4. Complexité Inutile**
- NarrativeThreadDetector: 420 lignes de regex patterns monolingues
- Timeline builder, causal/temporal chains
- **Problème**: Complexité élevée pour peu de valeur production
- **Conclusion**: ROI négatif (temps dev >> valeur business)

---

## Composants Implémentés (6 semaines)

### Semaines 1-2: Infrastructure
- ✅ Structure `src/knowbase/semantic/`
- ✅ Neo4j Proto-KG schema (mais basé sur narratives)
- ✅ Qdrant Proto collection `knowwhere_proto`
- ✅ Script `setup_infrastructure.py`
- ✅ Script `reset_proto_kg.py`

### Semaines 3-4: SemanticDocumentProfiler
- ✅ Complexity analysis (LLM-based) → **Conservable**
- ✅ Domain classification → **Conservable**
- ❌ Preliminary narrative detection → **Inutile**

### Semaines 5-6: NarrativeThreadDetector 🔥
- ❌ Causal sequences detection (9 connectors hardcodés EN)
- ❌ Temporal sequences detection (9 markers hardcodés EN)
- ❌ Timeline builder
- ❌ Cross-document linking (basé sur keywords monolingues)

**Total code**: ~1500 lignes (models, profiler, detector, tests)

---

## Ce qui est sauvé dans V2.1

### ✅ Infrastructure (avec modifications)
- Structure modules `src/knowbase/semantic/`
- Scripts setup/reset (adapter pour Concepts)
- Configuration système

### ✅ Profiler (partiel)
- Complexity analysis → Budget allocation
- Domain classification → Toujours utile

### ❌ Complètement supprimé
- NarrativeThreadDetector (420 lignes)
- Tests narratives
- Fixtures CRR Evolution (remplacées par docs descriptifs)

---

## Architecture V2.1 - Nouveau Focus

### 🎯 Principes V2.1
- **100% Documents Descriptifs** (guidelines, standards, architecture, CR)
- **Language-Agnostic** (NER multilingue + embeddings cross-lingual)
- **Concept-First** (extraction concepts sémantiques: ENTITY, PRACTICE, STANDARD, TOOL, ROLE)
- **Cross-Lingual Unification** (FR ↔ EN ↔ DE canonicalization automatique)

### 🔧 Pipeline V2.1 (4 étapes)
1. **TopicSegmenter** (windowing + clustering semantic)
2. **MultilingualConceptExtractor** (NER + Clustering + LLM)
3. **SemanticIndexer** (canonicalization cross-lingual)
4. **ConceptLinker** (relations cross-documents)

### 📊 USP V2.1
- Concept extraction multilingue automatique
- Cross-lingual concept unification (FR "auth" = EN "auth")
- Semantic relations (DEFINES, IMPLEMENTS, AUDITS, PROVES)
- Living Ontology (pattern discovery conceptuel)

---

## Leçons Apprises

### ❌ Erreurs à Éviter
1. **Implémenter avant de valider** le besoin réel utilisateur
2. **Keywords hardcodés** dans une architecture multilingue
3. **Over-engineering** features "cool" mais inutiles en prod
4. **Ignorer les contraintes réelles** (multilingue, descriptifs only)

### ✅ Bonnes Pratiques Conservées
1. **Documentation rigoureuse** (tracking, plans détaillés)
2. **Tests avec documents réels** (fixtures)
3. **Architecture modulaire** (facile à refactoriser)
4. **Commits atomiques** (facile à revert)

---

## Timeline

- **2025-10-13**: Démarrage Phase 1 (approche narrative)
- **2025-10-13**: Semaines 1-6 implémentées en 1 journée (!!)
- **2025-10-14**: Analyse pivot → Abandon approche narrative
- **2025-10-14**: Archive + Reset → Phase 1 V2.1 (concept-first)

**Temps "perdu"**: 1 journée (mais pivot critique évité à temps)

---

## Fichiers Archivés

- `PHASE1_IMPLEMENTATION_PLAN.md` (approche narrative)
- `PHASE1_TRACKING.md` (Semaines 1-6 narrative)
- `README.md` (phase 1 narrative)

**Code associé** (dans git history):
- Commits `0342190` à `95ec36a` (branche `feat/osmose-phase1`)

---

## Conclusion

**Décision**: Pivot nécessaire et salvateur.
**Coût**: 1 journée dev "perdue"
**Gain**: Éviter 32 semaines sur architecture inadaptée

> *"Mieux vaut pivoter tôt que persévérer dans l'erreur."*

---

**Prochaines Étapes**: Voir `doc/phase1_v2/PHASE1_IMPLEMENTATION_PLAN.md`
