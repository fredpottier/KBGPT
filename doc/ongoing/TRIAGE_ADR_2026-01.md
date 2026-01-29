# Rapport de Triage ADR - Janvier 2026

**Date:** 2026-01-29
**Auteur:** auto-claude (session 007-nettoyage-adrs)
**Objectif:** Auditer et trier les 55 fichiers de documentation architecturale (20 dans `doc/adr/` + 35 dans `doc/ongoing/`) en croisant avec le code v2 implémenté.

---

## Méthodologie

1. **Inventaire** : Lister exhaustivement les fichiers dans `doc/adr/` et `doc/ongoing/`
2. **Validation croisée** : Pour chaque ADR, vérifier l'existence des concepts dans le code v2 actif (`app/src/knowbase/stratified/`, `extraction_v2/`, `structural/`, `agents/`, `ingestion/`)
3. **Classification** : Catégoriser chaque fichier en GARDER / ARCHIVER / PROMOUVOIR
4. **Exécution** : Déplacer les fichiers via `git mv` (préservation historique)
5. **Vérification** : Contrôle d'intégrité (liens, comptages, aucune suppression)

**Base de référence code v2 :**
- Pipeline Stratifié V2 (`stratified/`) - Pass 0 à Pass 09
- Extraction V2 (`extraction_v2/`) - GatingEngine, TableSummarizer, VisionAnalyzer
- Structural Graph (`structural/`) - DocItem, TypeAwareChunk, StructuralGraphBuilder
- Agent Architecture (`agents/`) - SupervisorAgent FSM
- Persistence (`ingestion/osmose_persistence.py`) - anchor_proto_concepts_to_docitems

**Exclusion explicite :** Code legacy SemanticPipelineV2 (`src/knowbase/semantic/`)

---

## Classification des fichiers

### A. doc/adr/ (20 fichiers)

| Fichier | Source | Décision | Justification | Référence code v2 |
|---------|--------|----------|---------------|-------------------|
| `README.md` | doc/adr/ | GARDER | Index des ADRs, à mettre à jour après triage | N/A |
| `CONSOLIDATED_ADR_OSMOSE.md` | doc/adr/ | GARDER | Document de consolidation utile pour partage externe | N/A |
| `ADR-20241229-hybrid-anchor-model.md` | doc/adr/ | GARDER | ACCEPTED - Implémenté dans ingestion/hybrid_anchor_chunker.py, semantic/extraction/hybrid_anchor_extractor.py | `ingestion/hybrid_anchor_chunker.py` |
| `ADR-20241230-option-a-prime-chunk-aligned-relations.md` | doc/adr/ | GARDER | ACCEPTED - Principes appliqués dans stratified/pass2/relation_extractor.py | `stratified/pass2/relation_extractor.py` |
| `ADR-20241230-reducto-parsing-primitives.md` | doc/adr/ | GARDER | IMPLEMENTED - 100% dans extraction_v2/ : GatingEngine, TableSummarizer, VisionAnalyzer, layout detection | `extraction_v2/` |
| `ADR-20250105-marker-normalization-layer.md` | doc/adr/ | GARDER | IMPLEMENTED - 100% dans extraction_v2/context/ : DocContextExtractor, heuristics, domain-agnostic normalization | `extraction_v2/context/` |
| `ADR-20260101-document-structural-awareness.md` | doc/adr/ | GARDER | IMPLEMENTED - 100% dans extraction_v2/context/structural/ : ZoneSegmenter, TemplateDetector, LinguisticCueDetector | `extraction_v2/context/structural/` |
| `ADR-20260101-navigation-layer.md` | doc/adr/ | GARDER | IMPLEMENTED - Couche navigation/ implémentée, séparée du sémantique | `navigation/` |
| `ADR-20260104-assertion-aware-kg.md` | doc/adr/ | GARDER | IMPLEMENTED - Dans extraction_v2/context/anchor_context_analyzer.py et stratified/pass1/ | `extraction_v2/context/anchor_context_analyzer.py` |
| `ADR-20260106-graph-first-architecture.md` | doc/adr/ | GARDER | DRAFT - Direction architecturale future en discussion, pas encore implémenté | N/A (futur) |
| `ADR_CHARSPAN_CONTRACT_V1.md` | doc/adr/ | GARDER | DRAFT - Contrat de position utilisé par DocItem dans structural/models.py | `structural/models.py` |
| `ADR_COREF_NAMED_NAMED_VALIDATION.md` | doc/adr/ | GARDER | VALIDÉ - Implémenté dans ingestion/pipelines/pass05_coref.py (Pass 0.5) | `ingestion/pipelines/pass05_coref.py` |
| `ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md` | doc/adr/ | GARDER | ACCEPTED - compute_lex_key() utilisé dans Pass 2.0 et consolidation | `stratified/pass2/` |
| `ADR_COVERAGE_PROPERTY_NOT_NODE.md` | doc/adr/ | GARDER | ACCEPTED - Implémenté dans ingestion/osmose_persistence.py : anchor_proto_concepts_to_docitems() | `ingestion/osmose_persistence.py` |
| `ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md` | doc/adr/ | GARDER | ACCEPTED - Architecture future Pass 3.5, principes cohérents avec pipeline actuel | N/A (futur Pass 3.5) |
| `ADR_STRUCTURAL_CONTEXT_ALIGNMENT.md` | doc/adr/ | GARDER | ACCEPTED - Fix context_id appliqué dans pipeline de persistence | `ingestion/osmose_persistence.py` |
| `ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md` | doc/adr/ | GARDER | READY - Implémenté dans structural/ : DocItemBuilder, TypeAwareChunker, StructuralGraphBuilder | `structural/` |
| `ADR_UNIFIED_CORPUS_PROMOTION.md` | doc/adr/ | GARDER | ACCEPTED - Principes appliqués dans stratified/pass1/promotion_engine.py | `stratified/pass1/promotion_engine.py` |
| `ADR_DUAL_CHUNKING_ARCHITECTURE.md` | doc/adr/ | ARCHIVER | SUPERSEDED - Types CoverageChunk/DocumentChunk remplacés par DocItem+TypeAwareChunk (Option C). Superseded par ADR_COVERAGE_PROPERTY_NOT_NODE + ADR_STRUCTURAL_GRAPH_FROM_DOCLING | Obsolète |
| `ADR_PROPERTY_NAMING_NORMALIZATION.md` | doc/adr/ | ARCHIVER | EN COURS mais dette technique dont le tracking n'est plus maintenu. Conventions établies, document non-ADR. | Obsolète |

### B. doc/ongoing/ (35 fichiers)

| Fichier | Source | Décision | Justification | Référence code v2 |
|---------|--------|----------|---------------|-------------------|
| `ADR_DECISION_DEFENSE_ARCHITECTURE.md` | doc/ongoing/ | GARDER | ACCEPTED - Pivot fondamental, définit Evidence Graph | `agents/`, `stratified/` |
| `ADR_DISCURSIVE_RELATIONS.md` | doc/ongoing/ | GARDER | ACCEPTED - Extension du modèle assertion | `stratified/pass2/` |
| `ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md` | doc/ongoing/ | GARDER | ACCEPTED - Mécanisme de mining Pass 2.5 | `stratified/pass2/` |
| `ADR_SCOPE_VS_ASSERTION_SEPARATION.md` | doc/ongoing/ | PROMOUVOIR | APPROVED BLOCKING - Fondation architecturale permanente → doc/adr/ | `stratified/pass1/` |
| `ADR_NORMATIVE_RULES_SPEC_FACTS.md` | doc/ongoing/ | GARDER | APPROVED V1 - NormativeRule et SpecFact | `stratified/pass1/` |
| `ADR_STRATIFIED_READING_MODEL.md` | doc/ongoing/ | PROMOUVOIR | Review Final - Définit l'architecture v2 (Lecture Stratifiée) → doc/adr/ | `stratified/` |
| `ADR_EXPLOITATION_LAYER.md` | doc/ongoing/ | GARDER | DRAFT - Couche exploitation future | N/A (futur) |
| `ADR_NORTH_STAR_VERITE_DOCUMENTAIRE.md` | doc/ongoing/ | PROMOUVOIR | NORTH STAR VALIDÉ - Vision produit permanente → doc/adr/ | Vision produit |
| `ADR_PASS09_GLOBAL_VIEW_CONSTRUCTION.md` | doc/ongoing/ | GARDER | ACCEPTED - Pass 0.9 implémenté | `stratified/pass09/` |
| `ADR-20260126-vision-out-of-knowledge-path.md` | doc/ongoing/ | GARDER | ACCEPTED - Contrainte vision | `extraction_v2/` |
| `ARCH_STRATIFIED_PIPELINE_V2.md` | doc/ongoing/ | GARDER | Architecture pipeline actif | `stratified/` |
| `SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md` | doc/ongoing/ | GARDER | Spec MVP en cours | N/A (en cours) |
| `SPEC_TECHNIQUE_MVP_V1_USAGE_B.md` | doc/ongoing/ | GARDER | Spec technique active | N/A (en cours) |
| `TRACKING_PIPELINE_V2.md` | doc/ongoing/ | GARDER | Tracking pipeline actif | N/A (tracking) |
| `SPEC_VISION_SEMANTIC_INTEGRATION.md` | doc/ongoing/ | GARDER | Spec vision intégration active | N/A (en cours) |
| `DOC_PIPELINE_V2_TECHNIQUE_EXHAUSTIVE.md` | doc/ongoing/ | GARDER | Documentation technique exhaustive du pipeline v2 | `stratified/`, `extraction_v2/` |
| `ADR_POC_DISCURSIVE_RELATION_DISCRIMINATION.md` | doc/ongoing/ | ARCHIVER | POC exploratoire, cadrage terminé | Terminé |
| `ADR_DISCURSIVE_RELATIONS_BACKLOG.md` | doc/ongoing/ | ARCHIVER | Backlog implémentation terminé (phases A-E COMPLETE) | Terminé |
| `ADR-20260123-stratified-reading-poc-validation.md` | doc/ongoing/ | ARCHIVER | POC VALIDÉ ET CLOS - résultats intégrés | Terminé |
| `DECISION_DEFENSE_IMPLEMENTATION_BACKLOG.md` | doc/ongoing/ | ARCHIVER | Backlog d'implémentation, tracking terminé | Terminé |
| `IMPL_POC_STRATIFIED_READING.md` | doc/ongoing/ | ARCHIVER | POC implémenté et clos | Terminé |
| `EXTRACT_RISE_SAP_CLOUD_ERP_PRIVATE_SECURITY.md` | doc/ongoing/ | ARCHIVER | Extraction ponctuelle terminée | Terminé |
| `EXTRACT_RISE_SAP_CLOUD_ERP_PRIVATE_SECURITY_V2.md` | doc/ongoing/ | ARCHIVER | V2 extraction ponctuelle terminée | Terminé |
| `NEO4J_RECAP_2026-01-26_RUN5.md` | doc/ongoing/ | ARCHIVER | Recap daté, snapshot historique | Terminé |
| `DIAGNOSTIC_TESTS_PLAN_2026-01-26.md` | doc/ongoing/ | ARCHIVER | Plan diagnostic daté, résolu | Terminé |
| `DIAGNOSTIC_ROOT_CAUSE_FOUND.md` | doc/ongoing/ | ARCHIVER | Root cause trouvée, résolu | Terminé |
| `SPEC_VISION_ANCHOR_FIX_2026-01-26.md` | doc/ongoing/ | ARCHIVER | Fix spécifique appliqué | Terminé |
| `ANALYSE_QWEN14B_PROBLEMES_2026-01-27.md` | doc/ongoing/ | ARCHIVER | Analyse datée, résolu | Terminé |
| `PLAN_QWEN_STRUCTURED_OUTPUTS_2026-01-27.md` | doc/ongoing/ | ARCHIVER | Plan daté, implémenté | Terminé |
| `ANALYSE_QUALITE_EXTRACTION_2026-01-27.md` | doc/ongoing/ | ARCHIVER | Analyse datée, résolu | Terminé |
| `IDEA_ADAPTIVE_CONCEPT_BUDGET.md` | doc/ongoing/ | ARCHIVER | Idée exploratoire, évaluée | Terminé |
| `AMÉLIORATIONS_PASS1_LINKING_2026-01.md` | doc/ongoing/ | ARCHIVER | Améliorations datées, appliquées | Terminé |
| `EXTRACTION_ANALYSIS_RISE_SAP_CLOUD_ERP_PRIVATE.md` | doc/ongoing/ | ARCHIVER | Analyse extraction terminée | Terminé |
| `ANALYSE_EXTRACTION_2026-01-28.md` | doc/ongoing/ | ARCHIVER | Analyse datée, résolu | Terminé |
| `RESUME_CHATGPT_OSMOSE_PIPELINE_2026-01-28.md` | doc/ongoing/ | ARCHIVER | Résumé pour ChatGPT, ponctuel | Terminé |

---

## Résumé des actions

| Action | Source | Nombre | Destination |
|--------|--------|--------|-------------|
| GARDER | doc/adr/ | 18 | doc/adr/ (inchangé) |
| ARCHIVER | doc/adr/ | 2 | doc/archive/adr/ |
| GARDER | doc/ongoing/ | 13 | doc/ongoing/ (inchangé) |
| PROMOUVOIR | doc/ongoing/ | 3 | doc/adr/ |
| ARCHIVER | doc/ongoing/ | 19 | doc/archive/ |
| **Total** | | **55** | |

### Comptage attendu après triage

| Dossier | Avant | Après | Delta |
|---------|-------|-------|-------|
| doc/adr/ | 20 | 21 | +3 promus, -2 archivés = +1 |
| doc/ongoing/ | 35 | 13 | -19 archivés, -3 promus = -22 |
| doc/archive/adr/ | 0 | 2 | +2 depuis doc/adr/ |
| doc/archive/ (autres) | existant | +19 | +19 depuis doc/ongoing/ |

---

*Rapport généré automatiquement - sera finalisé en phase 6 avec les résultats effectifs.*
