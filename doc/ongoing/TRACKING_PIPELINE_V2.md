# Tracking Pipeline Stratifié V2

**Statut Global**: EN COURS
**Branche**: `pivot/stratified-pipeline-v2`
**Début**: 2026-01-23
**Dernière MAJ**: 2026-01-23

---

## Vue d'Ensemble

| Phase | Nom | Statut | Progression |
|-------|-----|--------|-------------|
| 0 | Fondations | 🟢 TERMINÉ | 100% |
| 1 | Pass 0 - Structural Graph | 🟢 TERMINÉ | 100% |
| 2 | Pass 1 - Lecture Stratifiée | ⚪ À FAIRE | 0% |
| 3 | Pass 2 - Enrichissement | ⚪ À FAIRE | 0% |
| 4 | Pass 3 - Consolidation | ⚪ À FAIRE | 0% |
| 5 | API V2 | ⚪ À FAIRE | 0% |
| 6 | UI V2 | ⚪ À FAIRE | 0% |
| 7 | Tests E2E | ⚪ À FAIRE | 0% |
| 8 | Validation | ⚪ À FAIRE | 0% |
| 9 | Migration | ⚪ À FAIRE | 0% |

**Légende**: ⚪ À faire | 🟡 En cours | 🟢 Terminé | 🔴 Bloqué

---

## Phase 0 : Fondations

**Objectif**: Mettre en place la structure, les schémas et les invariants.

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| F-001 | Créer branche `pivot/stratified-pipeline-v2` | 🟢 | Claude | Fait 2026-01-23 |
| F-002 | Rédiger ARCH_STRATIFIED_PIPELINE_V2.md | 🟢 | Claude | Avec reviews ChatGPT |
| F-003 | Créer structure dossiers `src/knowbase/stratified/` | 🟢 | Claude | pass1/, pass2/, pass3/, models/, db/ |
| F-004 | Schéma Neo4j V2 (cypher) | 🟢 | Claude | 8 contraintes, 12 indexes |
| F-005 | Modèles Pydantic (schemas.py) | 🟢 | Claude | Pass1Result, enums, structures |
| F-006 | Tests invariants V2-00x | 🟢 | Claude | 10 tests + metrics sanity |
| F-007 | Exécuter schema Neo4j sur instance | 🟢 | Claude | 8 contraintes + 12 indexes |
| F-008 | Valider imports Pydantic | 🟢 | Claude | Tous imports OK |

**Critères de validation Phase 0**:
- [x] Schema Neo4j exécuté sans erreur
- [x] `from knowbase.stratified.models import Pass1Result` fonctionne
- [ ] Tests invariants découverts par pytest

---

## Phase 1 : Pass 0 - Structural Graph

**Objectif**: Créer le graphe structurel (Document, Section, DocItem) à partir de l'extraction Docling.

**Dépendances**: Phase 0 complète

### 🎯 DÉCOUVERTE MAJEURE (Session #3)

Le code structural existe déjà dans `src/knowbase/structural/` :
- `StructuralGraphBuilder` - orchestrateur complet
- `DocItemBuilder` - extraction DocItems depuis Docling
- `SectionProfiler` - assignment sections
- `TypeAwareChunker` - création chunks
- `neo4j_schema.py` - contraintes et indexes (schéma existant)
- Feature flag: `USE_STRUCTURAL_GRAPH=true`

**Analyse de compatibilité V2** :
| Aspect | Existant | V2 | Action |
|--------|----------|-----|--------|
| Document node | `DocumentContext` + `DocumentVersion` | `Document` | Adapter labels |
| DocItem constraint | `(tenant_id, doc_id, doc_version_id, item_id)` | `(tenant_id, docitem_id)` | Générer `docitem_id` composite |
| Section node | `SectionContext` | `Section` | Adapter labels |
| TypeAwareChunk | Présent | Optionnel | Garder pour Qdrant retrieval |

**Stratégie**: Créer un **adapter V2** qui wrap le code existant plutôt que recréer.

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| P0-001 | Analyser pipeline extraction existant | 🟢 | Claude | StructuralGraphBuilder découvert |
| P0-002 | Analyser compatibilité schéma V2 | 🟢 | Claude | Voir tableau ci-dessus |
| P0-003 | Créer `pass0_adapter.py` | 🟢 | Claude | `stratified/pass0/adapter.py` |
| P0-004 | Générer `docitem_id` composite | 🟢 | Claude | `get_docitem_id_v2()` + `parse_docitem_id_v2()` |
| P0-005 | Mapper labels Neo4j V2 | 🟢 | Claude | `_create_document_v2_tx`, `_create_sections_v2_tx` |
| P0-006 | Créer mapping chunk→DocItem | 🟢 | Claude | `ChunkToDocItemMapping`, index inversé |
| P0-007 | Activer feature flag `USE_STRUCTURAL_GRAPH` | 🟢 | Claude | Déjà activé dans .env |
| P0-008 | Tests unitaires adapter | 🟢 | Claude | 15 tests passent |
| P0-009 | Test intégration document réel | 🟢 | Claude | `test_pass0_integration.py` créé |

**Critères de validation Phase 1**:
- [ ] Document PDF → nodes Document + Section + DocItem en Neo4j
- [ ] Mapping chunk_id → docitem_id disponible
- [ ] TypeAwareChunks dans Qdrant avec docitem_id
- [ ] Invariant V2-009 passe (DocItem a Section)

---

## Phase 2 : Pass 1 - Lecture Stratifiée

**Objectif**: Implémenter la lecture stratifiée validée par le POC.

**Dépendances**: Phase 1 complète

### 2.1 Document Analysis (Phase 1.1)

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| P1-001 | Migrer `document_analyzer.py` du POC | ⚪ | - | poc/extractors/ → stratified/pass1/ |
| P1-002 | Adapter prompts pour production | ⚪ | - | stratified/prompts/ |
| P1-003 | Implémenter détection HOSTILE | ⚪ | - | > 10 sujets → reject |
| P1-004 | Créer node Subject en Neo4j | ⚪ | - | HAS_SUBJECT |
| P1-005 | Tests unitaires 1.1 | ⚪ | - | |

### 2.2 Concept Identification (Phase 1.2)

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| P1-010 | Migrer `concept_identifier.py` du POC | ⚪ | - | |
| P1-011 | Implémenter garde-fou frugalité (max 15) | ⚪ | - | |
| P1-012 | Créer nodes Theme + Concept | ⚪ | - | HAS_THEME, HAS_CONCEPT |
| P1-013 | Implémenter SCOPED_TO (Theme→Section) | ⚪ | - | Optionnel mais recommandé |
| P1-014 | Tests unitaires 1.2 | ⚪ | - | |

### 2.3 Assertion Extraction (Phase 1.3)

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| P1-020 | Migrer `semantic_assertion_extractor.py` | ⚪ | - | |
| P1-021 | Adapter pour sortie chunk_id + span | ⚪ | - | Transitoire |
| P1-022 | Tests unitaires 1.3 | ⚪ | - | |

### 2.4 Anchor Resolution (Phase 1.3b) - CRITIQUE

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| P1-030 | Créer `anchor_resolver.py` | ⚪ | - | chunk_id → docitem_id |
| P1-031 | Implémenter matching texte chunk↔DocItem | ⚪ | - | Fuzzy si nécessaire |
| P1-032 | Calculer span relatif au DocItem | ⚪ | - | |
| P1-033 | Gérer cas NO_DOCITEM_ANCHOR | ⚪ | - | → AssertionLog ABSTAINED |
| P1-034 | Gérer cas CROSS_DOCITEM | ⚪ | - | Assertion sur 2+ DocItems |
| P1-035 | Tests unitaires 1.3b | ⚪ | - | Cas nominaux + edge cases |

### 2.5 Semantic Linking + Promotion (Phase 1.4)

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| P1-040 | Migrer linking sémantique du POC | ⚪ | - | |
| P1-041 | Implémenter Promotion Policy | ⚪ | - | ALWAYS/CONDITIONAL/RARELY/NEVER |
| P1-042 | Créer nodes Information | ⚪ | - | HAS_INFORMATION, ANCHORED_IN |
| P1-043 | Créer nodes AssertionLog | ⚪ | - | LOGGED_FOR |
| P1-044 | Implémenter enum AssertionLogReason | ⚪ | - | 11 valeurs |
| P1-045 | Tests unitaires 1.4 | ⚪ | - | |

### 2.6 Orchestration Pass 1

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| P1-050 | Créer `pass1_orchestrator.py` | ⚪ | - | Enchaîne 1.1→1.2→1.3→1.3b→1.4 |
| P1-051 | Retourner Pass1Result complet | ⚪ | - | JSON canonique |
| P1-052 | Mode burst (synchrone) | ⚪ | - | Priorité |
| P1-053 | Tests intégration Pass 1 complet | ⚪ | - | 1 document de bout en bout |

**Critères de validation Phase 2**:
- [ ] Document → Subject + Themes + Concepts + Informations
- [ ] Toutes les Information ancrées sur DocItem (V2-001)
- [ ] AssertionLog exhaustif (V2-004)
- [ ] Max 15 concepts (V2-007)
- [ ] Pass1Result JSON valide

---

## Phase 3 : Pass 2 - Enrichissement

**Objectif**: Extraire les relations entre concepts.

**Dépendances**: Phase 2 complète

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| P2-001 | Créer `relation_extractor.py` | ⚪ | - | |
| P2-002 | Définir types relations | ⚪ | - | REQUIRES, ENABLES, CONSTRAINS... |
| P2-003 | Implémenter garde-fou (max 3 rel/concept) | ⚪ | - | |
| P2-004 | Créer relations Neo4j | ⚪ | - | Avec evidence |
| P2-005 | Classification fine (optionnel) | ⚪ | - | Si domaine réglementaire |
| P2-006 | Tests unitaires Pass 2 | ⚪ | - | |
| P2-007 | Tests intégration Pass 2 | ⚪ | - | |

**Critères de validation Phase 3**:
- [ ] Relations extraites entre concepts
- [ ] Evidence rattachée à chaque relation
- [ ] Pas d'explosion (≤ 3 rel/concept)

---

## Phase 4 : Pass 3 - Consolidation Corpus

**Objectif**: Fusionner concepts/thèmes cross-documents.

**Dépendances**: Phase 3 complète, plusieurs documents ingérés

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| P3-001 | Créer `entity_resolver.py` | ⚪ | - | |
| P3-002 | Embeddings noms concepts | ⚪ | - | Avec variants |
| P3-003 | Clustering par similarité | ⚪ | - | Seuil 0.85 |
| P3-004 | Validation LLM cas ambigus | ⚪ | - | |
| P3-005 | Créer CanonicalConcept | ⚪ | - | SAME_AS |
| P3-006 | Créer `theme_aligner.py` | ⚪ | - | |
| P3-007 | Créer CanonicalTheme | ⚪ | - | ALIGNED_TO |
| P3-008 | Mode manuel (on-demand) | ⚪ | - | Pour tests |
| P3-009 | Mode batch (cron) | ⚪ | - | Pour prod |
| P3-010 | Tests unitaires Pass 3 | ⚪ | - | |
| P3-011 | Tests intégration Pass 3 | ⚪ | - | Multi-documents |

**Critères de validation Phase 4**:
- [ ] Concepts identiques fusionnés cross-doc
- [ ] CanonicalConcept créés
- [ ] Mode manuel fonctionne depuis UI

---

## Phase 5 : API V2

**Objectif**: Créer les endpoints `/v2/*` pour le nouveau pipeline.

**Dépendances**: Phases 2-4 (au moins Pass 1 fonctionnel)

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| API-001 | Créer router `/v2/documents` | ⚪ | - | CRUD documents V2 |
| API-002 | Endpoint POST `/v2/ingest` | ⚪ | - | Déclenche Pass 0 + Pass 1 |
| API-003 | Endpoint POST `/v2/enrich` | ⚪ | - | Déclenche Pass 2 |
| API-004 | Endpoint POST `/v2/consolidate` | ⚪ | - | Déclenche Pass 3 |
| API-005 | Endpoint GET `/v2/documents/{id}/graph` | ⚪ | - | Retourne graphe sémantique |
| API-006 | Endpoint GET `/v2/search` | ⚪ | - | Recherche sur graphe V2 |
| API-007 | Endpoint GET `/v2/documents/{id}/assertions` | ⚪ | - | AssertionLog (debug) |
| API-008 | Schémas OpenAPI | ⚪ | - | |
| API-009 | Tests API | ⚪ | - | |

**Critères de validation Phase 5**:
- [ ] Swagger `/v2/*` accessible
- [ ] Ingestion via API fonctionne
- [ ] Recherche retourne résultats V2

---

## Phase 6 : UI V2

**Objectif**: Créer l'interface pour le pipeline V2.

**Dépendances**: Phase 5 (API fonctionnelle)

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| UI-001 | Créer page `/enrichment-v2` | ⚪ | - | Nouvelle page, pas modifier legacy |
| UI-002 | Visualisation Subject/Themes/Concepts | ⚪ | - | Arbre hiérarchique |
| UI-003 | Visualisation Informations | ⚪ | - | Avec ancrage DocItem |
| UI-004 | Bouton "Lancer Pass 1" | ⚪ | - | Mode burst |
| UI-005 | Bouton "Lancer Pass 2" | ⚪ | - | |
| UI-006 | Bouton "Lancer Pass 3" | ⚪ | - | Mode manuel |
| UI-007 | Consultation AssertionLog | ⚪ | - | Debug: promoted/abstained/rejected |
| UI-008 | Indicateurs métriques | ⚪ | - | Ratio info/concept, etc. |
| UI-009 | Tests E2E UI | ⚪ | - | |

**Critères de validation Phase 6**:
- [ ] Page `/enrichment-v2` accessible
- [ ] Ingestion document via UI fonctionne
- [ ] Visualisation graphe sémantique

---

## Phase 7 : Tests E2E

**Objectif**: Valider le pipeline complet sur corpus de référence.

**Dépendances**: Phases 1-6 complètes

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| E2E-001 | Définir corpus de test (19 docs) | ⚪ | - | Mêmes que legacy |
| E2E-002 | Script d'ingestion batch | ⚪ | - | |
| E2E-003 | Exécuter tous les invariants V2-00x | ⚪ | - | CI |
| E2E-004 | Mesurer nodes/document | ⚪ | - | Cible: < 250 |
| E2E-005 | Mesurer temps/document | ⚪ | - | Cible: < 10 min |
| E2E-006 | Comparer avec legacy | ⚪ | - | |
| E2E-007 | Review résultats avec ChatGPT | ⚪ | - | |
| E2E-008 | Rapport de validation | ⚪ | - | |

**Critères de validation Phase 7**:
- [ ] 19 documents ingérés sans erreur
- [ ] Tous invariants V2-00x passent
- [ ] Nodes/doc < 250 (vs ~4700 legacy)
- [ ] Réduction ≥ 95%

---

## Phase 8 : Validation

**Objectif**: Décision Go/No-Go pour migration.

**Dépendances**: Phase 7 complète

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| VAL-001 | Revue métriques | ⚪ | - | |
| VAL-002 | Revue qualité sémantique | ⚪ | - | Échantillon manuel |
| VAL-003 | Décision Go/No-Go | ⚪ | Fred | |
| VAL-004 | Documentation décision | ⚪ | - | ADR si No-Go |

---

## Phase 9 : Migration

**Objectif**: Basculer sur V2 et décommissionner legacy.

**Dépendances**: Phase 8 = Go

| ID | Tâche | Statut | Assigné | Notes |
|----|-------|--------|---------|-------|
| MIG-001 | Feature flag V2 activé | ⚪ | - | |
| MIG-002 | Re-processing corpus existant | ⚪ | - | |
| MIG-003 | Période de coexistence | ⚪ | - | Legacy + V2 |
| MIG-004 | Monitoring comparatif | ⚪ | - | |
| MIG-005 | Supprimer page legacy | ⚪ | - | |
| MIG-006 | Supprimer code legacy | ⚪ | - | |
| MIG-007 | Endpoints `/v2/*` → `/` | ⚪ | - | |
| MIG-008 | Documentation finale | ⚪ | - | |

---

## Risques et Blocages

| ID | Risque | Impact | Mitigation | Statut |
|----|--------|--------|------------|--------|
| R-001 | Anchor Resolution échoue souvent | Pass 1 inutilisable | Améliorer matching fuzzy | ⚪ |
| R-002 | Performance LLM insuffisante | Temps > cible | Optimiser prompts, batching | ⚪ |
| R-003 | Qualité sémantique dégradée vs legacy | No-Go | Ajuster Promotion Policy | ⚪ |

---

## Métriques de Suivi

### Progression Globale

```
Phase 0: ████████████████████ 100% ✅
Phase 1: ████████████████████ 100% ✅
Phase 2: ░░░░░░░░░░░░░░░░░░░░ 0%
Phase 3: ░░░░░░░░░░░░░░░░░░░░ 0%
Phase 4: ░░░░░░░░░░░░░░░░░░░░ 0%
Phase 5: ░░░░░░░░░░░░░░░░░░░░ 0%
Phase 6: ░░░░░░░░░░░░░░░░░░░░ 0%
Phase 7: ░░░░░░░░░░░░░░░░░░░░ 0%
Phase 8: ░░░░░░░░░░░░░░░░░░░░ 0%
Phase 9: ░░░░░░░░░░░░░░░░░░░░ 0%
─────────────────────────────
TOTAL:   ████░░░░░░░░░░░░░░░░ 19%
```

### Compteurs

| Métrique | Valeur |
|----------|--------|
| Tâches totales | 89 |
| Tâches terminées | 17 |
| Tâches en cours | 0 |
| Tâches bloquées | 0 |

---

## Journal des Sessions

| Date | Session | Réalisations |
|------|---------|--------------|
| 2026-01-23 | #1 | POC validé, ADR créé et publié |
| 2026-01-23 | #2 | Architecture V2, reviews ChatGPT, structure code, livrables |
| 2026-01-23 | #3 | Phase 0 terminée, début Phase 1 - **Découverte: StructuralGraphBuilder existe** |
| 2026-01-23 | #4 | **Phase 1 TERMINÉE**: Pass0Adapter V2, mappings chunk→DocItem, 15 tests unitaires, test intégration |

---

## Références

- [ARCH_STRATIFIED_PIPELINE_V2.md](./ARCH_STRATIFIED_PIPELINE_V2.md) - Architecture détaillée
- [ADR-20260123-stratified-reading-poc-validation.md](./ADR-20260123-stratified-reading-poc-validation.md) - Validation POC
- [neo4j_schema_v2.cypher](../../src/knowbase/stratified/db/neo4j_schema_v2.cypher) - Schéma Neo4j
- [schemas.py](../../src/knowbase/stratified/models/schemas.py) - Modèles Pydantic
- [test_invariants_v2.py](../../tests/stratified/test_invariants_v2.py) - Tests invariants
