# Matrice de Traçabilité — Rationalisation Documentation OSMOSE

**Date** : 2026-03-29
**Objectif** : Garantir qu'aucune substance décisionnelle n'est perdue lors de l'archivage massif
**Méthode** : Lecture exhaustive de ~180 documents, extraction des décisions/pistes écartées/travaux non terminés

---

## 1. INVENTAIRE DES INVARIANTS INVIOLABLES

Ces principes sont déclarés à travers de multiples ADRs et doivent survivre dans le doc **NORTH_STAR.md** reconstruit.

| ID | Invariant | Sources | Statut code |
|---|---|---|---|
| **INV-1** | Aucun concept sans anchor textuel (ANCHORED_IN → DocItem) | ADR-20241229, ADR_COVERAGE_PROPERTY, ADR_CHARSPAN | ✅ Implémenté |
| **INV-2** | Pas de texte LLM indexé comme preuve (anti-hallucination) | ADR-20241229, ADR_DECISION_DEFENSE | ✅ Implémenté |
| **INV-3** | Neo4j = source de vérité, Qdrant = projection retrieval | ADR_QDRANT_RETRIEVAL_PROJECTION, ADR-20260106 | ✅ Implémenté |
| **INV-4** | Graph-First : KG interrogé AVANT Qdrant | ADR-20260106, GRAPH_FIRST_PRINCIPLE | ✅ Implémenté |
| **INV-5** | Scope ≠ Assertion (navigation ≠ reasoning) | ADR_SCOPE_VS_ASSERTION, ADR-20260101-navigation | ✅ Implémenté |
| **INV-6** | Domain-agnostic : POS/UD, jamais lexical-métier | ADR_MULTI_SPAN, KG_AGNOSTIC, ADR-20250105 | ✅ Implémenté |
| **INV-7** | Language-agnostic : embeddings multilingues, cross-lingual auto | PHASE1_SEMANTIC_CORE, OSMOSE_ARCHITECTURE_TECHNIQUE | ✅ Implémenté |
| **INV-8** | Applicability over Truth (vérité documentaire contextualisée) | ADR_NORTH_STAR_VERITE_DOCUMENTAIRE | ✅ Principe actif |
| **INV-9** | Conservative Subject Resolution (abstention > faux positif) | ADR_COREF_NAMED_NAMED, ClaimFirst models | ✅ Implémenté |
| **INV-10** | Discriminants discovered, not hardcoded | KG_AGNOSTIC_ARCHITECTURE | ✅ Principe actif |
| **INV-11** | Evidence Bundles = artefact justification, PAS relation KG navigable | ADR_MULTI_SPAN_EVIDENCE_BUNDLES | ✅ Implémenté |
| **INV-12** | Coverage = propriété invariante, PAS type de noeud | ADR_COVERAGE_PROPERTY_NOT_NODE | ✅ Implémenté |
| **INV-13** | Safe-by-default normalisation (UNRESOLVED si doute) | ADR-20250105-marker-normalization | ✅ Implémenté |
| **INV-14** | Silence KG = RAG pur (dégradation gracieuse) | PHASE_B_INTENT_DRIVEN_SEARCH | ✅ Implémenté |
| **INV-15** | Statut décision dérivé déterministiquement (jamais LLM) | ADR_DECISION_DEFENSE | ⚠️ Partiellement |
| **INV-16** | Merge réversible (MERGED_INTO relation, pas suppression) | SPEC-PHASE2.12, SPEC-CORPUS_CONSOLIDATION | ⏳ Non implémenté |
| **INV-17** | Type A = chunks RAG identiques (hard constraint) | PHASE_B_SPRINT_PLAN, PHASE_B_CONSOLIDATED | ✅ Implémenté |
| **INV-18** | Métadonnées structurelles ≠ inférences (titre, section = faits) | SPRINT2_SYNTHESE_CONSENSUS_CHUNKING | ✅ Principe actif |
| **INV-19** | Unité de preuve (DocItem/Claim) ≠ Unité de lecture (Chunk Qdrant) | ADR_UNITE_PREUVE_VS_UNITE_LECTURE | ✅ Implémenté |

---

## 2. PISTES ÉCARTÉES CRITIQUES

Ces décisions **négatives** sont aussi importantes que les positives. Elles empêchent de refaire les mêmes erreurs.

### Architecture fondamentale

| Piste écartée | Pourquoi rejetée | Source | Doit migrer vers |
|---|---|---|---|
| Concept-focused chunks | Explosion combinatoire 140:1, 35 min/doc → inacceptable | ADR-20241229 | NORTH_STAR |
| Texte LLM dans Qdrant | Non vérifiable, hallucinations | ADR-20241229 | NORTH_STAR |
| Retrieval-first (RAG classique) | Biais vectoriel "transformation" → Digital Transformation au lieu de Quotation→Contract | ADR-20260106 | NORTH_STAR |
| Graphiti pour facts | Texte dans edges, migré Neo4j native | OSMOSIS_PROJECT_HISTORY | HISTORIQUE |
| Linéarisation comme source | Perd structure Docling | ADR_STRUCTURAL_GRAPH | ARCH_PIPELINE |
| Bottom-up extraction exhaustive (v1) | 90k+ nodes, peu relations, fragmentation | ADR_STRATIFIED_READING | ARCH_PIPELINE |
| Top-down pur (v2.1) | Concepts inventés, 34% SINK, 37% vides | ADR_HYBRID_EXTRACT_THEN_STRUCTURE | ARCH_PIPELINE |

### Pipelines & extraction

| Piste écartée | Pourquoi rejetée | Source | Doit migrer vers |
|---|---|---|---|
| Vision ON pour Knowledge Units | Anchor rate 12-17% (vs 56.6% text-only) — mismatch structurel | ADR-20260126-vision-out-of-KG | ARCH_PIPELINE |
| Vision prompt en français | 52% assertions FR → 0% anchor (bug) | SPEC_VISION_ANCHOR_FIX | ARCH_PIPELINE |
| Hardcoded domain regexes | Viole agnosticisme | ADR-20250105 | NORTH_STAR |
| Schema-based extraction (Reducto style) | Incompatible cross-doc reasoning | ADR-20241230-reducto | ARCH_PIPELINE |
| LayoutLMv3 | Overkill initial, heuristiques suffisent | ADR-20241230-reducto | ARCH_PIPELINE |
| Full LLM pour coref | Coût prohibitif | ADR_COREF_NAMED_NAMED | ARCH_PIPELINE |
| Whitelist lexicale prédicats | Langue-spécifique | ADR_MULTI_SPAN | NORTH_STAR |

### Retrieval & synthèse

| Piste écartée | Pourquoi rejetée | Source | Doit migrer vers |
|---|---|---|---|
| Bloc KG dans prompt synthèse | Dégrade -8pp factual, +6.9pp false_idk | SPRINT0_RAPPORT_EXHAUSTIF | CHANTIER_BENCHMARK |
| IntentResolver par prototypes embeddes | 75% questions mal classées Type C | SPRINT2_DIAGNOSTIC_INTENT_RESOLVER | ARCH_RETRIEVAL |
| Query rewriting LLM | Latence excessive (2-15s) | PHASE_B_CONSOLIDATED | ARCH_RETRIEVAL |
| Community summaries GraphRAG | Coûteux, stale, perte traçabilité | PHASE_B_CONSOLIDATED | ARCH_RETRIEVAL |
| Passage node HippoRAG 2 | Redondant avec chunk_ids existants | PHASE_B_CONSOLIDATED | ARCH_RETRIEVAL |

### Stratégie produit

| Piste écartée | Pourquoi rejetée | Source | Doit migrer vers |
|---|---|---|---|
| Plateforme doc généraliste ("Chat with docs") | Marché saturé | STRATEGY_REPOSITIONNEMENT | VISION_PRODUIT |
| Positionnement "Truth Engine" | Politique, non vendable | STRATEGY_REPOSITIONNEMENT | VISION_PRODUIT |
| Focus SAP uniquement | Bataille perdue d'avance | STRATEGY_REPOSITIONNEMENT | VISION_PRODUIT |
| Multi-tenant logique | Risque fuite données, audit complexe | ARCHITECTURE_DEPLOIEMENT | OPS |

---

## 3. TRAVAUX NON TERMINÉS

### Critiques (bloquent la progression)

| Chantier | État actuel | Ce qui reste | Source | Migre vers |
|---|---|---|---|---|
| **Re-chunking corpus** | Rechunker écrit, pas branché | Brancher TypeAwareChunks + notes + prefixe, re-ingestion | SPRINT2_DIAGNOSTIC_CHUNKING | CHANTIER_CHUNKING |
| **KG Signal Detector** | Design validé, pas implémenté | Remplace IntentResolver, fondation Signal-Driven | SPRINT2_DIAGNOSTIC_INTENT_RESOLVER | ARCH_RETRIEVAL |
| **Entity Resolution corpus-level** | Spec validée (PATCH-ER/LINK/BUDGET) | 3 patchers à implémenter, 67% concepts isolés | SPEC-PHASE2.12, SPEC-CORPUS_CONSOLIDATION | CHANTIER_KG_QUALITY |
| **Burst : 7 derniers docs** | 21/28 caches, 7 en cours | Terminer burst, ClaimFirst 22 nouveaux, benchmark | Mémoire projet | CHANTIER_BENCHMARK |

### Importants (améliorent qualité)

| Chantier | État actuel | Ce qui reste | Source | Migre vers |
|---|---|---|---|---|
| Evidence Bundle Resolver Pass 3 | Safe mode intra-section actif | Extended mode (inter-sections), Assisted mode (UI) | ADR_MULTI_SPAN | ARCH_PIPELINE |
| ApplicabilityAxis causalité | Bug identifié (année non propagée) | Fix ContextExtractor, passer titre complet | Mémoire projet | ARCH_CLAIMFIRST |
| Canonicalisation renforcée | Plan 3 sprints, pas commencé | Exact dedup → token blocking → embedding + LLM | ADR_KG_QUALITY_V3 | CHANTIER_KG_QUALITY |
| Déduplication acronymes | Design prêt, pas implémenté | AcronymMap 3 sources, clustering, merge proposals | ACRONYM_CONCEPT_DEDUP | CHANTIER_KG_QUALITY |
| Facet Engine V2 navigation | Code production complet | Sprint 3-4 (gouvernance, navigation runtime) | ADR_FACET_ENGINE_V2 | CHANTIER_ATLAS |
| Atlas Phase 1 (Chat↔Atlas) | Design validé, 2-3j implémentation | Articles liés dans chat, insight hints | ADR_ATLAS_EVOLUTION | CHANTIER_ATLAS |
| Concept Assembly Engine (Wiki) | Architecture designée | POC 4 briques, Evidence Pack, Constrained Generator | WIKI_OSMOSIS_CONCEPT_ASSEMBLY | CHANTIER_ATLAS |
| Cockpit opérationnel | Architecture complète approuvée | V1 MVP (6 widgets, pipeline SVG) | ADR_COCKPIT_OPERATIONNEL | CHANTIER_COCKPIT |
| Normative Rules & SpecFacts | Spec approuvée V1 | NormativePatternExtractor, StructureParser, Pass 2c | ADR_NORMATIVE_RULES | ARCH_PIPELINE |
| Coref Named-Named | Gating + LLM design validé | Phases B-D (cache global, LLM arbiter, cache contextuel) | ADR_COREF_NAMED_NAMED | ARCH_PIPELINE |
| Source Enrollment multi-sources | ADR draft | Connecteurs SharePoint/Google/S3, IngestionEvent | ADR_SOURCE_ENROLLMENT | OPS |
| Intelligence Report UI | Design pas commencé | Visualisation contradictions, dashboard | STRATEGY_REPOSITIONNEMENT | VISION_PRODUIT |
| Decision Defense strict | Principe actif, enforcement faible | Proof obligations dans synthesis.py, gap qualification | ADR_DECISION_DEFENSE | NORTH_STAR |

### Complétés (à documenter comme acquis)

| Livrable | Date | Source | Migre vers |
|---|---|---|---|
| Phase 1 Semantic Core v2.1 | Oct 2025 | PHASE1_SEMANTIC_CORE | HISTORIQUE |
| Phase 1.5 Agentique Pilot (95%) | Nov 2025 | OSMOSE_ROADMAP_INTEGREE | HISTORIQUE |
| Phase 2.3 InferenceEngine + Living Ontology | Dec 2025 | TRACKING-OSMOSE_STATUS | HISTORIQUE |
| Phase 2.5 Memory Layer | Dec 2025 | PHASE2.5_MEMORY_LAYER | HISTORIQUE |
| Phase 2.7 Concept Matching Engine | Dec 2025 | SPEC-PHASE2.7 | ARCH_RETRIEVAL |
| Phase 2.10 Relation Extraction V3 | Dec 2025 | SPEC-PHASE2.10 | ARCH_PIPELINE |
| Sprint 0 Benchmark diagnostic | Mars 2026 | SPRINT0_RAPPORT_EXHAUSTIF | CHANTIER_BENCHMARK |
| Sprint 1 (canary, prompt fix, refactoring) | Mars 2026 | SPRINT1_IMPLEMENTATION_PLAN | CHANTIER_BENCHMARK |
| Rechunker + text_chunker | Mars 2026 | SPRINT2_DIAGNOSTIC_CHUNKING | ARCH_RETRIEVAL |
| Facet Engine V2 (code complet) | Mars 2026 | ADR_FACET_ENGINE_V2 | ARCH_CLAIMFIRST |

---

## 4. CONSTATS EMPIRIQUES CLÉS

Ces mesures justifient des décisions et doivent être préservées.

| Constat | Valeur | Impact sur décision | Source | Migre vers |
|---|---|---|---|---|
| Vision ON anchor rate | 12-17% | → Vision exclue du chemin KG | ADR-20260126 | ARCH_PIPELINE |
| Text-only anchor rate | 56.6% | → Baseline sain confirmé | ADR-20260126 | ARCH_PIPELINE |
| Chunks < 100 chars | 70% | → Re-chunking obligatoire | SPRINT2_DIAGNOSTIC | CHANTIER_CHUNKING |
| TypeAwareChunks median | 102 chars (vs 68 DocItems) | → Utiliser TAC au lieu DocItems pour Qdrant | SPRINT2_DIAGNOSTIC | CHANTIER_CHUNKING |
| Speaker notes PPTX | 33-45% slides, 551-893 chars | → Mine d'or non exploitée | SPRINT2_PISTES | CHANTIER_CHUNKING |
| Test borne sup. Claude Sonnet | +39pp avec chunks 1500 chars | → Fondation chunks est LE bottleneck | PHASE_B_SPRINT_PLAN | CHANTIER_CHUNKING |
| Haiku 3.5 | 80% correct, $0.004/q | → Candidat synthèse production | Mémoire projet | ARCH_RETRIEVAL |
| Bloc KG dans prompt | -8pp factual | → Approche ABANDONNÉE | SPRINT0_RAPPORT | CHANTIER_BENCHMARK |
| T2 contradictions OSMOSIS vs RAG | 100% vs 0% | → GAME CHANGER, différenciation | SPRINT0_RAPPORT | VISION_PRODUIT |
| T1 KG factual vs RAG | +15pp | → KG apporte valeur cross-doc | SPRINT0_RAPPORT | CHANTIER_BENCHMARK |
| IntentResolver 75% mal classées | 75% Type A → Type C | → Bascule Signal-Driven | SPRINT2_INTENT_RESOLVER | ARCH_RETRIEVAL |
| MENTIONED_IN explosion | 2,048,725 rels (2000x) | → Fix context_id alignment | ADR_STRUCTURAL_CONTEXT | ARCH_PIPELINE |
| Concepts isolés (degree=0) | 67.6% | → Entity Resolution urgente | SPEC-PHASE2.12 | CHANTIER_KG_QUALITY |
| V2.1 top-down : SINK | 34% | → Pivot vers Extract-then-Structure | ADR_HYBRID_EXTRACT | ARCH_PIPELINE |
| Concept-focused chunks perf | 35 min/doc | → Pivot vers 2-pass (10 min/doc) | ADR-20241229 | NORTH_STAR |
| ID-first extraction | 82% relations perdues avant fix | → Catalogue fermé avec index numériques | SPEC-PHASE2.8 | ARCH_PIPELINE |
| Qwen confidences | ~0.60 uniforme | → Calibration seuils nécessaire | RAPPORT_LINKING_DIAGNOSTIC | ARCH_PIPELINE |
| Linking coverage | 11.7% → 81.9% | → Fix triggers + soft/hard gates validé | AMELIORATIONS_PASS1 | ARCH_PIPELINE |
| Score commercial global | 5.5/10 | → R&D avancée, pas encore produit vendable | STRATEGY_REPOSITIONNEMENT | VISION_PRODUIT |

---

## 5. MAPPING DOCUMENTS → DOCS CIBLES RECONSTRUITS

### NORTH_STAR.md (Invariants, principes fondateurs, Decision Defense)

| Document source | Ce qu'il apporte |
|---|---|
| `foundations/GRAPH_FIRST_PRINCIPLE.md` | Principe "le graphe est le routeur" |
| `foundations/KG_AGNOSTIC_ARCHITECTURE.md` | 5 couches, 4 profils visibilité, pas de hardcoding domaine |
| `adr/ADR_NORTH_STAR_VERITE_DOCUMENTAIRE.md` | Vérité documentaire contextualisée, ClaimKey |
| `adr/ADR_SCOPE_VS_ASSERTION_SEPARATION.md` | INV-SEP-01→04, Scope ≠ Assertion |
| `ongoing/ADR_DECISION_DEFENSE_ARCHITECTURE.md` | Decision Defense, abstention qualifiée, R1→R5 |
| `adr/ADR_COVERAGE_PROPERTY_NOT_NODE.md` | Coverage comme propriété, ABR/OR/SAR |
| `adr/ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md` | Evidence ≠ KG relation, agnosticisme linguistique |
| `ongoing/ADR_UNITE_PREUVE_VS_UNITE_LECTURE.md` | Séparation preuve vs lecture |
| Concept-focused chunks rejection (ADR-20241229) | Piste écartée critique |
| Vision OUT of KG (ADR-20260126) | Piste écartée critique |
| Bloc KG dans prompt (SPRINT0) | Piste écartée critique |

### VISION_PRODUIT.md (Positionnement, capacités, stratégie marché)

| Document source | Ce qu'il apporte |
|---|---|
| `ongoing/OSMOSIS_VISION_PRODUIT_2026-03.md` | 5 capacités fondamentales |
| `ongoing/STRATEGY_REPOSITIONNEMENT_OSMOSIS_2026-03.md` | Documentation Verification Platform, marché cible |
| `ongoing/OSMOSE_USAGES_QUOTIDIENS.md` | Cas d'usage concrets |
| `ongoing/ADR_EXPLOITATION_LAYER.md` | 3 usages A/B/C (composition, companion, navigator) |
| `phases/OSMOSE_AMBITION_PRODUIT_ROADMAP.md` | USPs vs Copilot/Gemini |
| `ongoing/SPRINT0_RAPPORT_EXHAUSTIF.md` | T2 contradictions 100% vs 0% (différenciation) |
| Score commercial 5.5/10 (STRATEGY) | État réaliste du produit |

### HISTORIQUE_PIVOTS.md (Timeline, leçons, décisions historiques)

| Document source | Ce qu'il apporte |
|---|---|
| `OSMOSIS_PROJECT_HISTORY.md` | Timeline SAP KB → KnowWhere → OSMOSE |
| `phases/PHASE1_SEMANTIC_CORE.md` | Phase 1 complétée (acquis) |
| `phases/PHASE2.5_MEMORY_LAYER.md` | Memory Layer complétée (acquis) |
| `tracking/TRACKING-OSMOSE_STATUS_ACTUEL.md` | État phases Dec 2025 |
| `phases/OSMOSE_ROADMAP_INTEGREE.md` | Roadmap macro 45 semaines |
| Métriques -70% temps, -98% chunks (ADR-20241229) | Gains mesurés du pivot |

### ARCH_PIPELINE.md (Pipeline stratifié Pass 0→3, Docling, vision, cache)

| Document source | Ce qu'il apporte |
|---|---|
| `adr/ADR_STRATIFIED_READING_MODEL.md` | Modèle lecture stratifié, concepts frugaux |
| `ongoing/ADR_HYBRID_EXTRACT_THEN_STRUCTURE.md` | Extract-then-Structure (V2.2), I1→I6 |
| `adr/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md` | Option C, DocItem, TypeAwareChunk |
| `adr/ADR-20241230-reducto-parsing-primitives.md` | Table summaries, confidence, layout-aware |
| `adr/ADR-20260101-document-structural-awareness.md` | Zones, templates, linguistic cues |
| `adr/ADR-20260104-assertion-aware-kg.md` | DocContextFrame, polarity, scope |
| `adr/ADR_CHARSPAN_CONTRACT_V1.md` | Contrat positions caractères |
| `ongoing/ADR-20260126-vision-out-of-knowledge-path.md` | Vision exclue + constats empiriques |
| `ongoing/ADR_PASS09_GLOBAL_VIEW.md` | GlobalView 100% sections |
| `adr/ADR-20241230-option-a-prime.md` | Relations alignées chunks, fenêtre [i-1,i,i+1] |
| `specs/extraction/SPEC-EXTRACTION_PIPELINE_ARCHITECTURE.md` | Pipeline PDF/PPTX détaillé |
| `specs/extraction/SPEC-VISION_GATING_V4.md` | 4 signaux, décision binaire |
| `specs/extraction/SPEC-PHASE2.8_ID_FIRST_EXTRACTION.md` | Catalogue fermé index numériques |
| `specs/extraction/SPEC-PHASE2.8_RAW_CANONICAL_ARCHITECTURE.md` | 2-layer Raw/Canonical |
| `specs/extraction/SPEC-PHASE2.8.1_CANONICAL_DEDUP_FIX.md` | Intersection logic 3-way |
| `specs/graph/SPEC-PHASE2.9_SEGMENT_LEVEL_RELATIONS.md` | Relations segment-level |
| `specs/graph/SPEC-PHASE2.10_RELATION_EXTRACTION_V3.md` | 12 types fermés, maturité épistémique |
| `specs/graph/SPEC-LLM_PROMPT_RELATION_TYPES_VALIDATION.md` | Prompt structure validation |
| `ongoing/ADR_NORMATIVE_RULES_SPEC_FACTS.md` | NormativeRule, SpecFact |
| `ongoing/ADR_CONCEPT_ADMISSIBILITY.md` | Admissibilité conceptuelle locale |
| `ongoing/AMELIORATIONS_PASS1_LINKING.md` | Coverage 11.7→81.9%, triggers, soft/hard gates |
| `ongoing/PLAN_QWEN_STRUCTURED_OUTPUTS.md` | vLLM JSON Schema, validation post-LLM |
| `ongoing/RAPPORT_LINKING_DIAGNOSTIC.md` | Qwen ~0.60 uniforme, calibration |
| Pistes v1 bottom-up, v2.1 top-down (écartées) | Leçons architecturales |

### ARCH_CLAIMFIRST.md (Pipeline ClaimFirst 9 phases, facets, quality)

| Document source | Ce qu'il apporte |
|---|---|
| Code `claimfirst/orchestrator.py` | Pipeline 9 phases (code = vérité) |
| `ongoing/ADR_FACET_ENGINE_V2.md` | Prototypes composites, scoring multi-signal |
| `adr/ADR-20250105-marker-normalization.md` | MarkerMention→CanonicalMarker |
| `adr/ADR_COREF_NAMED_NAMED_VALIDATION.md` | Gating + LLM coref |
| `ongoing/APPLICABILITY_AXIS_DESIGN_V2.1.md` | Axes applicabilité |
| `adr/ADR_CORPUS_AWARE_LEX_KEY.md` | compute_lex_key() |
| `adr/ADR_UNIFIED_CORPUS_PROMOTION.md` | Pass 2.0 single-stage |
| `adr/ADR_STRUCTURAL_CONTEXT_ALIGNMENT.md` | context_id alignment |
| `specs/graph/SPEC-PHASE2.11_CANONICAL_CLAIMS.md` | CanonicalClaim unaires |
| ApplicabilityAxis bug (année non propagée) | Travail non terminé |

### ARCH_RETRIEVAL.md (Graph-Guided RAG, Layer R, rechunker, synthesis)

| Document source | Ce qu'il apporte |
|---|---|
| `adr/ADR-20260106-graph-first-architecture.md` | 3 modes (Reasoned/Anchored/Text-only) |
| `ongoing/ADR_QDRANT_RETRIEVAL_PROJECTION_V2.md` | Layer R/P, point ID déterministe |
| `adr/ADR-20260101-navigation-layer.md` | ContextNode, Non-Promotion Clause |
| `specs/graph/SPEC-PHASE2.7_CONCEPT_MATCHING.md` | 3 paliers, 78% golden set |
| `ongoing/PHASE_B_CONSOLIDATED_ANALYSIS.md` | KG2RAG, constats empiriques |
| `ongoing/PHASE_B_INTENT_DRIVEN_SEARCH.md` | Architecture Signal-Driven |
| `ongoing/SPRINT2_DIAGNOSTIC_INTENT_RESOLVER.md` | 75% mal classées → abandon |
| Code `search.py`, `retriever.py`, `synthesis.py` | Implémentation actuelle |
| Haiku tiered ($0.004/q) | Architecture LLM tiered |

### ARCH_STOCKAGE.md (Neo4j schema, Qdrant collections, PG, Redis)

| Document source | Ce qu'il apporte |
|---|---|
| `architecture/ARCHITECTURE_DEPLOIEMENT.md` | 1 instance = 1 client |
| `architecture/OSMOSE_ARCHITECTURE_TECHNIQUE.md` | Dual-graph Proto/Published |
| `architecture/OSMOSIS_ARCHITECTURE_CIBLE_V2.md` | Structure-first, Domain Context |
| `adr/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md` | Schema DocItem/SectionContext/PageContext |
| `specs/extraction/SPEC-EXTRACTION_CACHE_USAGE.md` | Cache .knowcache.json |
| Code `db/models.py`, clients Qdrant/Neo4j/Redis | Schéma actuel |

### CHANTIER_BENCHMARK.md (Framework, scores, stratégie)

| Document source | Ce qu'il apporte |
|---|---|
| `ongoing/SPRINT0_RAPPORT_EXHAUSTIF.md` | Diagnostic complet, constats clés |
| `ongoing/SPRINT0_ZONES_OMBRE_ANALYSIS.md` | Recommandations état de l'art |
| `ongoing/PHASE_B_SPRINT_PLAN.md` | Sprints 0→2, scores par sprint |
| `ongoing/BENCHMARK_V5_ANALYSE_CONTRADICTIONS.md` | Analyse contradictions récente |
| Code `benchmark/` | Framework actuel |
| Questions PPTX 20 supplémentaires | Extension benchmark |

### CHANTIER_CHUNKING.md (Diagnostic, rechunker, unité preuve/lecture)

| Document source | Ce qu'il apporte |
|---|---|
| `ongoing/SPRINT2_DIAGNOSTIC_CHUNKING.md` | Root cause analysis, métriques |
| `ongoing/SPRINT2_PISTES_CHUNKING_ARCHITECTURE.md` | 6 pistes A→F |
| `ongoing/SPRINT2_SYNTHESE_CONSENSUS_CHUNKING.md` | Plan consensus 3 phases |
| `ongoing/ADR_UNITE_PREUVE_VS_UNITE_LECTURE.md` | Séparation formelle |
| `ongoing/RESEARCH_CHUNKING_STRATEGIES_RAG.md` | État de l'art 2024-2025 |
| Constats : 70% < 100 chars, +39pp avec 1500 chars | Métriques clés |

### CHANTIER_ATLAS.md (Wiki, Concept Assembly, facettes navigation)

| Document source | Ce qu'il apporte |
|---|---|
| `ongoing/ADR_ATLAS_EVOLUTION.md` | 3 phases Atlas cognitif |
| `ongoing/WIKI_OSMOSIS_CONCEPT_ASSEMBLY_ENGINE.md` | Architecture 4 briques |
| `ongoing/WIKI_OSMOSIS_PROJECT_PRESCRIPTION.md` | Vision long terme Wikipedia |
| `ongoing/ADR_FACET_ENGINE_V2.md` | Navigation par facettes |

### CHANTIER_COCKPIT.md (Supervision opérationnelle)

| Document source | Ce qu'il apporte |
|---|---|
| `ongoing/ADR_COCKPIT_OPERATIONNEL.md` | Architecture complète 651 lignes |

### CHANTIER_KG_QUALITY.md (Canonicalisation, entités, relations)

| Document source | Ce qu'il apporte |
|---|---|
| `ongoing/ADR_KG_QUALITY_PIPELINE_V3.md` | 6 chantiers, 3 sprints |
| `ongoing/ACRONYM_CONCEPT_DEDUP_PLAN.md` | Déduplication acronymes |
| `specs/graph/SPEC-PHASE2.12_ENTITY_RELATION.md` | PATCH-ER/LINK/BUDGET |
| `specs/ingestion/SPEC-CORPUS_CONSOLIDATION.md` | Consolidation corpus-level |
| 67.6% concepts isolés, 1% relations/claims | Métriques motivantes |

### OPS.md (Docker, AWS, burst, backup, monitoring)

| Document source | Ce qu'il apporte |
|---|---|
| `operations/OPS_GUIDE.md` | Procédures opérationnelles |
| `operations/AWS_DEPLOYMENT_GUIDE.md` | Déploiement ECR→EC2 |
| `operations/AWS_COST_MANAGEMENT.md` | Optimisation coûts |
| `operations/AWS_BACKUP_RESTORE_STRATEGY.md` | Stratégie backup |
| `operations/BURST_SPOT_ARCHITECTURE.md` | EC2 Spot, vLLM |
| `operations/GOLDEN_AMI_BURST_SPEC.md` | AMI v8 |
| `operations/DOCKER_SETUP.md` | Multi-compose |
| `ongoing/ADR_SOURCE_ENROLLMENT.md` | Multi-sources, zero-retention |
| `architecture/ARCHITECTURE_DEPLOIEMENT.md` | 1 instance = 1 client |

### DEV_GUIDE.md (Structure code, feature flags, tests, conventions)

| Document source | Ce qu'il apporte |
|---|---|
| `guides/FEATURE_FLAGS_GUIDE.md` | Configuration feature flags |
| `guides/kw.README.md` | Script kw.ps1 |
| `specs/ingestion/SPEC-PROCESSUS_IMPORT_DOCUMENT.md` | Flux import |
| Code analysis (structure arborescence) | État réel |

---

## 6. DOCUMENTS SANS SUBSTANCE DÉCISIONNELLE UNIQUE

Ces documents peuvent être archivés sans extraction — leur contenu est soit redondant, soit purement opérationnel daté.

| Document | Raison archivage pur |
|---|---|
| `ongoing/ANALYSE_IMPORT_*` | Diagnostics datés, métriques absorbées dans rapports Sprint |
| `ongoing/NEO4J_RECAP_*` | Snapshots état KG datés |
| `ongoing/AUDIT_RUN8_*` | Diagnostic spécifique à un run |
| `ongoing/DEMO_USE_CASES_PLAN_*` | Plan démo daté (passé) |
| `ongoing/RESUME_CHATGPT_*` | Résumé pour session ChatGPT (contexte éphémère) |
| `ongoing/TRACKING_PIPELINE_V2.md` | Tracking absorbé dans ARCH_PIPELINE |
| `ongoing/github_issue_sessions_index.md` | Bug report Claude Code (hors OSMOSE) |
| `ongoing/DOC_PIPELINE_V2_TECHNIQUE_EXHAUSTIVE.md` | 4766 lignes, marqué "EN COURS", remplacé par docs reconstruits |
| `ongoing/SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md` | Spec classes MVP V1, absorbée dans ARCH_PIPELINE |
| `ongoing/SPEC_TECHNIQUE_MVP_V1_USAGE_B.md` | Spec MVP V1 Challenge, absorbée dans ARCH_RETRIEVAL |
| `ongoing/SPEC_VISION_SEMANTIC_INTEGRATION.md` | Absorbée dans ARCH_PIPELINE |
| `ongoing/SPEC_VISION_ANCHOR_FIX.md` | Fix ponctuel, constat préservé dans constats empiriques |
| `research/etudes/*` | Études exploratoires, conclusions absorbées dans ADRs |
| `research/OSMOSE_COGNITIVE_MATURITY.md` | Analyse exploratoire |
| `research/OSMOSE_MULTI_TENANT_ARCHITECTURE.md` | Décision 1-instance-par-client prise |
| `tracking/TRACKING-PHASE1_8.md` | Phase complétée |
| `tracking/TRACKING-CONSISTENCY_AUDIT-2026-01.md` | Audit daté |
| `phases/PHASE1_8_LLM_HYBRID_INTELLIGENCE.md` | Phase complétée |
| Multiples versions V1/V2/V2.1 | Seule V2.1 survit dans docs reconstruits |

---

## 7. RÉSUMÉ QUANTITATIF

| Métrique | Valeur |
|---|---|
| Documents analysés | ~180 |
| Invariants inviolables extraits | 19 |
| Pistes écartées critiques documentées | 27 |
| Travaux non terminés identifiés | 20+ |
| Constats empiriques clés préservés | 25 |
| Documents cibles reconstruits | 15 |
| Documents archivables sans extraction | 20+ |

---

## 8. PROCHAINES ÉTAPES

1. **Validation utilisateur** de cette matrice (tu es ici)
2. Archivage dans `doc/archive/pre-rationalization-2026-03/`
3. Reconstruction des 15 docs cibles
4. Vérification croisée code ↔ docs reconstruites
5. Mise à jour `doc/README.md`
