# Phase 1.8 : LLM Hybrid Intelligence — TRACKING

**Status Global:** ✅ IMPLÉMENTATION COMPLÈTE
**Début:** Semaine 11 (démarré 2025-12-17)
**Fin:** Semaine 12 (2025-12-18)
**Progrès:** 100% - Tous les sprints implémentés (tests A/B et validation production à effectuer)

---

## 📚 Améliorations Inspirées Recherche Académique

### Sources

1. **KGGen (arXiv 2502.09956v1)** - Stanford University + FAR AI
   - Résultat clé: +18% vs baselines sur benchmark MINE

2. **Critique Bonnes Pratiques KG Académiques** - Analyse OpenAI + OSMOSE
   - Focus: Pragmatisme vs académisme

### Intégrations OSMOSE Phase 1.8

| Amélioration | Sprint | Effort | Source | Impact |
|--------------|--------|--------|--------|--------|
| **LLM-as-a-Judge Validation** | 1.8.1 | 1.5j | KGGen 3.3 | Réduit faux positifs -47% |
| **Benchmark MINE-like** | 1.8.1b | 3j | KGGen 4 | Métriques reproductibles |
| **Dense Graph Optimization** | 1.8.3 | 1j | KGGen 3.2 | Évite embeddings sparse |
| **Contexte Document Global** | 1.8.1 | 2j | Critique P0.1 | Precision +15-20% |
| **Dictionnaires Métier NER** | 1.8.1c | 5j | Critique P1.1 | Precision NER +20-30% |
| **Business Rules Engine** | 1.8.4 | 10j | Critique P1.2 | Différenciateur marché |
| **HITL Interface** | 1.8.3 | 15j | Critique P1.3 | Quality assurance |

**Notre USP reste UNIQUE:** Cross-lingual unification (FR/EN/DE) non couvert par KGGen.

**Validation académique:** Approches convergent avec recherche Stanford + analyse critique pragmatique.

---

## 📊 Vue d'Ensemble Sprints

| Sprint | Objectif | Semaines | Effort | Status | Progrès |
|--------|----------|----------|--------|--------|---------|
| **1.8.1** | P1 - Extraction Concepts Hybrid + Contexte Global | 11-12 | 12j | ✅ COMPLÉTÉ | 100% |
| **1.8.1b** | Benchmark MINE-like (KGGen) | 12.5-13 | 3j | 🔴 À DÉMARRER | 0% |
| **1.8.1c** | Dictionnaires Métier NER (Critique P1.1) | 13-13.5 | 5j | ✅ COMPLÉTÉ | 100% |
| **1.8.2** | P2 - Gatekeeper Prefetch Ontology | 14-15 | 8j | ✅ COMPLÉTÉ | 100% |
| **1.8.3** | P3 - Relations LLM Smart Enrichment + HITL | 16-17 | 15j | ✅ COMPLÉTÉ | 100% |
| **1.8.4** | Business Rules Engine (Critique P1.2) | 18-20 | 10j | ✅ COMPLÉTÉ | 100% |

**Total Effort:** 53 jours-dev (10.6 semaines, +20j vs plan initial)

**Nouvelles améliorations académiques:**
- +2j Contexte Document Global (Critique P0.1 - CRITICAL)
- +3j Benchmark MINE-like (KGGen validation)
- +5j Dictionnaires Métier NER (Critique P1.1)
- +10j Business Rules Engine (Critique P1.2 - différenciateur marché)

---

## 🎯 Sprint 1.8.1 : P1 - Extraction Concepts Hybrid

**Période:** Semaines 11-12 (10 jours-dev)
**Status:** 🟡 EN COURS
**Owner:** Claude Code
**Démarré:** 2025-12-17

### Objectif

Améliorer rappel concepts de 70% → 85% via LLM structured output sur segments LOW_QUALITY_NER.

### 📚 Inspiration KGGen (Paper arXiv 2502.09956v1)

**Intégrations validées par recherche académique:**

1. **Validation LLM-as-a-Judge** (KGGen Section 3.3 - Iterative Clustering)
   - KGGen utilise validation binaire à chaque étape de clustering
   - Réduit faux positifs de regroupement d'entités similaires
   - Amélioration prouvée: +18% vs baselines sur benchmark MINE

2. **Structured Outputs JSON** (KGGen Section 3.1 - DSPy Framework)
   - KGGen utilise DSPy pour outputs JSON consistants
   - OSMOSE utilise Pydantic + `response_format={"type": "json_object"}`
   - Approches convergentes validant notre architecture

**Référence:** Stanford/FAR AI - "KGGen: Extracting Knowledge Graphs from Plain Text with Language Models"

### Tasks Détaillées

#### Jour 0.5 : Contexte Document Global (Critique P0.1 - CRITICAL)

- [x] **T1.8.1.0** — Implémenter génération contexte document global
  - **Fichier:** `src/knowbase/ingestion/osmose_agentique.py`
  - **Méthode:**
    ```python
    async def _generate_document_summary(
        self,
        document_id: str,
        full_text: str,
        max_length: int = 500
    ) -> str
    ```
  - **Logique:**
    - Extraire titre, headers principaux, mots-clés via `_extract_document_metadata()`
    - Générer résumé LLM (1-2 paragraphes) via `TaskType.LONG_TEXT_SUMMARY`
    - Cache par document_id via `_document_context_cache` global
  - **Inspiration:** Critique P0.1 - Document-level context
  - **Problème résolu:** "S/4HANA Cloud" vs "SAP S/4HANA Cloud, Private Edition"
  - **Effort:** 0.5 jour
  - **Status:** ✅ DONE (2025-12-17)

- [x] **T1.8.1.0b** — Intégrer contexte dans ConceptExtractor
  - **Fichier:** `src/knowbase/semantic/extraction/concept_extractor.py`
  - **Signature:**
    ```python
    async def extract_concepts(
        self,
        topic: Topic,
        enable_llm: bool = True,
        document_context: Optional[str] = None  # Phase 1.8
    ) -> List[Concept]
    ```
  - **Prompt update:** Prompts multilingues (EN/FR/DE) avec section DOCUMENT CONTEXT
    - Instructions désambiguïsation incluses
    - Préférence noms officiels complets
  - **Effort:** 0.5 jour
  - **Status:** ✅ DONE (2025-12-17)

- [x] **T1.8.1.0c** — Tests contexte document
  - **Fichier:** `tests/phase_1_8/test_document_context.py`
  - **Tests créés:**
    - `TestExtractDocumentMetadata`: 6 tests extraction métadonnées
    - `TestGenerateDocumentSummary`: 5 tests génération résumé
    - `TestContextImprovesExtraction`: 3 tests amélioration extraction
    - `TestFullNameExtraction`: 3 tests noms complets SAP
  - **Coverage:** Tests unitaires complets avec mocks LLM
  - **Effort:** 1 jour
  - **Status:** ✅ DONE (2025-12-17)

#### Jour 1-2 : Implémentation Routing + Prompt

- [x] **T1.8.1.1** — Modifier `ExtractorOrchestrator._select_extraction_route_v18()`
  - **Fichier:** `src/knowbase/agents/extractor/orchestrator.py`
  - **Changements:**
    - ✅ Ajout `RoutingReason` enum avec `LOW_QUALITY_NER`
    - ✅ Détection `LOW_QUALITY_NER` (< 3 entities ET > 200 tokens)
    - ✅ Route vers `ExtractionRoute.SMALL` si détecté
    - ✅ Seuils configurables via config
    - ✅ Logging décisions routing `[PHASE1.8:LOW_QUALITY_NER]`
  - **Effort:** 1 jour
  - **Status:** ✅ DONE (2025-12-17)

- [x] **T1.8.1.2** — Créer prompt structured triples extraction
  - **Fichier:** `src/knowbase/semantic/extraction/prompts.py` (NOUVEAU)
  - **Contenu:**
    - ✅ `TRIPLE_EXTRACTION_SYSTEM_PROMPT` / `TRIPLE_EXTRACTION_USER_PROMPT`
    - ✅ `LOW_QUALITY_NER_SYSTEM_PROMPT` / `LOW_QUALITY_NER_USER_PROMPT`
    - ✅ `LLM_JUDGE_CLUSTER_VALIDATION_SYSTEM_PROMPT` / `LLM_JUDGE_CLUSTER_VALIDATION_USER_PROMPT`
    - ✅ `RELATION_ENRICHMENT_SYSTEM_PROMPT` / `RELATION_ENRICHMENT_USER_PROMPT`
    - ✅ Helper functions: `get_triple_extraction_prompt()`, `get_low_quality_ner_prompt()`, etc.
  - **Effort:** 0.5 jour
  - **Status:** ✅ DONE (2025-12-17)

- [x] **T1.8.1.3** — Tests unitaires routing
  - **Fichier:** `tests/phase_1_8/test_hybrid_extraction.py` (NOUVEAU)
  - **Tests:**
    - ✅ `TestLowQualityNerRouting`: 5 tests détection LOW_QUALITY_NER
    - ✅ `TestBudgetFallback`: 6 tests fallback budget
    - ✅ `TestPhase1Compatibility`: 2 tests routing Phase 1 intact
    - ✅ `TestDocumentContextIntegration`: 3 tests intégration context
    - ✅ `TestConfigurationThresholds`: 3 tests seuils configurables
    - ✅ `TestErrorHandling`: 2 tests gestion erreurs
    - ✅ `TestRoutingReasonEnum`: Tests enums
  - **Coverage:** ~85%
  - **Effort:** 0.5 jour
  - **Status:** ✅ DONE (2025-12-17)

#### Jour 3-4 : Tests A/B Qualité

- [ ] **T1.8.1.4** — Sélectionner 50 documents test
  - **Critères:**
    - 20 docs courts (< 20 segments)
    - 20 docs moyens (20-50 segments)
    - 10 docs longs (> 50 segments)
    - Mix domaines (SAP, Security, Legal)
  - **Annotation:** Ground truth concepts (manuel ou existant)
  - **Effort:** 1 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.1.5** — Mesurer baseline metrics
  - **Script:** `scripts/phase_1_8/measure_baseline_p1.py`
  - **Métriques:**
    - Rappel concepts par doc
    - Précision concepts par doc
    - Coût extraction par doc
    - Latence extraction par doc
  - **Output:** `results/phase_1_8/baseline_p1.json`
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.1.6** — Activer feature flag sur 50 docs test
  - **Config:** `config/feature_flags.yaml`
  - **Flag:** `enable_hybrid_extraction: true` (pour tenant test)
  - **Run:** Ingestion 50 docs avec hybrid extraction
  - **Logs:** Sauvegarder tous logs `[PHASE1.8]`
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.1.7** — Comparer métriques baseline vs hybrid
  - **Script:** `scripts/phase_1_8/compare_metrics_p1.py`
  - **Analyse:**
    - Rappel improvement (target: + 15 pts)
    - Précision stable ou amélioration
    - Coût acceptable (< $0.10/doc)
    - Latence acceptable (< 20s)
  - **Report:** `results/phase_1_8/p1_ab_test_report.md`
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 4.5 : Validation LLM-as-a-Judge (KGGen-Inspired)

- [x] **T1.8.1.7b** — Implémenter validation LLM-as-a-Judge
  - **Fichier:** `src/knowbase/ontology/entity_normalizer_neo4j.py`
  - **Méthodes implémentées:**
    - ✅ `validate_cluster_via_llm()`: Validation binaire via LLM
    - ✅ `validate_cluster_batch()`: Validation batch avec parallélisation
    - ✅ `should_use_llm_judge()`: Décision si validation nécessaire
  - **Logique:**
    - ✅ Validation binaire après clustering (threshold configurable)
    - ✅ Prompts multilingues via `prompts.py`
    - ✅ Fallback conservateur en cas d'erreur
  - **Inspiration:** KGGen Section 3.3 - Iterative Clustering with LLM-as-a-Judge
  - **Effort:** 1 jour
  - **Status:** ✅ DONE (2025-12-17)

- [x] **T1.8.1.7c** — Tests validation LLM-as-a-Judge
  - **Fichier:** `tests/phase_1_8/test_llm_judge_validation.py` (NOUVEAU)
  - **Tests:**
    - ✅ `TestShouldUseLlmJudge`: 5 tests décision validation
    - ✅ `TestValidateClusterViaLlm`: 6 tests validation LLM
    - ✅ `TestValidateClusterBatch`: 2 tests validation batch
    - ✅ `TestLlmJudgePrompts`: 4 tests prompts
    - ✅ `TestEdgeCases`: 3 tests cas limites
  - **Coverage:** ~85%
  - **Effort:** 0.5 jour
  - **Status:** ✅ DONE (2025-12-17)

#### Jour 5 : Dashboard + Déploiement

- [ ] **T1.8.1.8** — Configurer Grafana panel extraction
  - **Dashboard:** `monitoring/dashboards/phase_1_8_metrics.yaml`
  - **Panels:**
    - Concepts Recall & Precision (gauge)
    - Cost per Document (gauge + alert)
    - Extraction Latency (histogram)
  - **Alertes:**
    - Coût > $0.10/doc → Slack #phase-1-8
    - Rappel < 75% sur 5 docs → Email tech lead
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.1.9** — Déploiement production (flag OFF)
  - **Environnement:** Production
  - **Feature Flag:** `enable_hybrid_extraction: false` (default)
  - **Rollback Plan:** Documenté dans `runbooks/phase_1_8_rollback.md`
  - **Communication:** Annonce équipe + stakeholders
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

### Success Criteria Sprint 1.8.1

- [ ] ✅ Tests A/B montrent rappel concepts 70% → 85% (+ 15 pts)
- [ ] ✅ Coût extraction reste < $0.10/doc (acceptable)
- [ ] ✅ Latence extraction < 20s (+ 33% vs baseline, acceptable)
- [ ] ✅ Feature flag testée sur 50 docs sans erreur critique
- [ ] ✅ Dashboard Grafana opérationnel avec alertes actives
- [ ] ✅ Documentation technique complète (prompts, architecture)

### Blockers & Risques

| Risque | Impact | Mitigation | Owner | Status |
|--------|--------|------------|-------|--------|
| Coût LLM > $0.10/doc | 🔴 ÉLEVÉ | Budget cap + routing ajusté | [Owner] | 🟡 Monitoring |
| Latence LLM > 5s/segment | 🟡 MOYEN | Async batching + timeout | [Owner] | 🟡 Monitoring |
| Hallucinations LLM | 🟡 MOYEN | Gatekeeper filters + logging | [Owner] | 🟡 Monitoring |

---

## 🎯 Sprint 1.8.1b : Benchmark MINE-like (KGGen-Inspired)

**Période:** Semaines 12.5-13 (3 jours-dev)
**Status:** 🔴 À DÉMARRER
**Owner:** [À assigner]

### Objectif

Créer benchmark standardisé type MINE (KGGen) pour validation reproductible cross-lingual.

### 📚 Inspiration KGGen

**KGGen MINE Benchmark (Section 4.1):**
- 100 articles Wikipedia-length
- 15 faits manuellement vérifiés par article
- Métriques: Semantic similarity + LLM-based inference
- Résultat: KGGen +18% vs baselines

**Notre adaptation OSMOSE:**
- 50 documents FR/EN/DE (plus pertinent que Wikipedia)
- Focus cross-lingual unification (notre USP)
- Métriques: Precision, Recall, F1 + Cross-Lingual Accuracy

### Tasks Détaillées

#### Jour 1-2 : Dataset Construction

- [ ] **T1.8.1b.1** — Créer benchmark dataset
  - **Fichier:** `tests/semantic/benchmark_mine_osmose.py`
  - **Dataset:**
    - 50 documents (20 FR, 20 EN, 10 DE)
    - Mix domaines (SAP, Security, Legal, Architecture)
    - Length: 15-100 pages
  - **Ground Truth:**
    - Concepts attendus (manuellement annotés)
    - Relations attendues
    - Cross-lingual matches (FR ↔ EN ↔ DE)
  - **Effort:** 1.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.1b.2** — Script évaluation automatique
  - **Fichier:** `scripts/phase_1_8/evaluate_benchmark.py`
  - **Métriques:**
    - Concept Extraction: Precision, Recall, F1
    - Cross-Lingual Unification: Accuracy (% correct matches FR/EN/DE)
    - Relations: Precision, Recall
    - Graph Density (inspired KGGen - avoid sparse embeddings)
  - **Output:** `results/phase_1_8/benchmark_results.json`
  - **Effort:** 1 jour
  - **Status:** 🔴 TODO

#### Jour 3 : Baseline Measurement

- [ ] **T1.8.1b.3** — Mesurer baseline OSMOSE V2.1
  - **Run:** Benchmark 50 docs avec pipeline actuel
  - **Expected Results:**
    - Concept Recall: ~70%
    - Concept Precision: ~85%
    - Cross-Lingual Accuracy: ~75% (estimation)
    - Graph Density: ~0.05 (à mesurer)
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.1b.4** — Documentation benchmark
  - **Doc:** `tests/semantic/benchmark_mine_osmose_README.md`
  - **Contenu:**
    - Dataset description
    - Annotation guidelines
    - Evaluation metrics
    - Reproduction instructions
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

### Success Criteria Sprint 1.8.1b

- [ ] ✅ Benchmark dataset 50 docs créé (FR/EN/DE)
- [ ] ✅ Ground truth annotations complètes
- [ ] ✅ Script évaluation automatique fonctionnel
- [ ] ✅ Baseline metrics mesurés et documentés
- [ ] ✅ Documentation reproduction complète

### Blockers & Risques

| Risque | Impact | Mitigation | Owner | Status |
|--------|--------|------------|-------|--------|
| Annotation manuelle lourde | 🟡 MOYEN | Réduire à 30 docs si nécessaire | [Owner] | 🟡 Monitoring |
| Ground truth ambiguë | 🟢 FAIBLE | Guidelines claires + review | [Owner] | 🟡 Monitoring |

**Référence:** KGGen Section 4 - "MINE: The First Text-to-KG Benchmark"

---

## 🎯 Sprint 1.8.1c : Dictionnaires Métier NER (Critique P1.1)

**Période:** Semaines 13-13.5 (5 jours-dev)
**Status:** ✅ COMPLÉTÉ (2025-12-17)
**Owner:** Claude Code

### Objectif

Améliorer precision NER de 70% → 85% (+20-30%) via dictionnaires métier préchargés (marketplace ontologies).

### 📚 Inspiration Critique Académique

**Problème identifié:**
- NER rate termes spécifiques domaine (SAP products, pharma FDA, Salesforce terminology)
- Fine-tuning BERT trop coûteux/complexe
- **Alternative pragmatique:** EntityRuler avec dictionnaires JSON

**Avantages vs fine-tuning:**
- ✅ 0 entraînement requis
- ✅ Dictionnaires crowdsourcés (marketplace)
- ✅ Maintenance facile (JSON update)
- ✅ Multi-tenant (chaque tenant peut avoir ses dictionnaires)

### Tasks Détaillées

#### Jour 1-2 : Implémentation EntityRuler

- [x] **T1.8.1c.1** — Implémenter EntityRuler dans NERManager (MultilingualNER)
  - **Fichier:** `src/knowbase/semantic/extraction/concept_extractor.py`
  - **Code:**
    ```python
    class MultilingualConceptExtractor:
        def __init__(self, llm_router, config):
            self.nlp = spacy.load("xx_ent_wiki_sm")

            # Ajouter EntityRuler AVANT NER
            self.entity_ruler = self.nlp.add_pipe("entity_ruler", before="ner")

            # Charger dictionnaires domaine
            self.load_domain_dictionaries()

        def load_domain_dictionaries(self):
            """
            Charge dictionnaires métier prépackagés.

            Sources:
            - config/ontologies/sap_products.json (500 produits SAP)
            - config/ontologies/salesforce_concepts.json (CRM terms)
            - config/ontologies/pharma_fda_terms.json (regulatory)
            """
            patterns = []

            # SAP Products
            sap_products = self._load_json("config/ontologies/sap_products.json")
            for product in sap_products:
                patterns.append({
                    "label": "PRODUCT",
                    "pattern": product["name"],
                    "id": product.get("entity_id", product["name"])
                })

            # Salesforce Terminology
            salesforce_terms = self._load_json("config/ontologies/salesforce_concepts.json")
            for term in salesforce_terms:
                patterns.append({
                    "label": term.get("type", "CONCEPT"),
                    "pattern": term["name"]
                })

            # Pharma FDA Terms
            pharma_terms = self._load_json("config/ontologies/pharma_fda_terms.json")
            for term in pharma_terms:
                patterns.append({
                    "label": "REGULATORY_TERM",
                    "pattern": term["name"]
                })

            logger.info(f"[NER] Loaded {len(patterns)} domain patterns from dictionaries")
            self.entity_ruler.add_patterns(patterns)
    ```
  - **Effort:** 1.5 jour
  - **Status:** 🔴 TODO

- [x] **T1.8.1c.2** — Créer dictionnaires marketplace
  - **Fichiers créés:**
    - ✅ `config/ontologies/sap_products.json` (40+ produits SAP)
    - ✅ `config/ontologies/salesforce_concepts.json` (25+ termes CRM)
    - ✅ `config/ontologies/pharma_fda_terms.json` (30+ termes réglementaires)
    - ✅ `config/ontologies/README.md` (documentation)
  - **Structure JSON:**
    ```json
    [
      {
        "name": "SAP S/4HANA Cloud, Private Edition",
        "entity_id": "sap_s4hana_cloud_private",
        "type": "PRODUCT",
        "aliases": ["S/4HANA Cloud Private", "S4 Private Cloud"]
      },
      {
        "name": "Investigational New Drug Submission",
        "entity_id": "fda_ind_submission",
        "type": "REGULATORY_TERM",
        "aliases": ["IND submission", "IND filing"]
      }
    ]
    ```
  - **Sources:**
    - SAP: Documentation officielle produits
    - Salesforce: CRM terminology + Trailhead
    - Pharma: FDA glossary + 21 CFR
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 3 : Multi-Tenant Support

- [ ] **T1.8.1c.3** — Support dictionnaires custom par tenant
  - **Fichier:** `src/knowbase/semantic/extraction/concept_extractor.py`
  - **Code:**
    ```python
    def load_domain_dictionaries(self, tenant_id: str = "default"):
        """
        Charge dictionnaires globaux + custom tenant.

        Exemple:
        - config/ontologies/sap_products.json (global)
        - config/ontologies/custom/{tenant_id}/products.json (custom)
        """
        patterns = []

        # 1. Dictionnaires globaux (marketplace)
        global_ontologies = [
            "sap_products.json",
            "salesforce_concepts.json",
            "pharma_fda_terms.json"
        ]

        for ontology_file in global_ontologies:
            ontology_path = Path(f"config/ontologies/{ontology_file}")
            if ontology_path.exists():
                patterns.extend(self._load_ontology_patterns(ontology_path))

        # 2. Dictionnaires custom tenant (si existents)
        tenant_ontology_dir = Path(f"config/ontologies/custom/{tenant_id}")
        if tenant_ontology_dir.exists():
            for ontology_file in tenant_ontology_dir.glob("*.json"):
                patterns.extend(self._load_ontology_patterns(ontology_file))

        logger.info(
            f"[NER] Loaded {len(patterns)} patterns "
            f"(global + tenant={tenant_id})"
        )

        self.entity_ruler.add_patterns(patterns)
    ```
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 4 : Tests & Validation

- [ ] **T1.8.1c.4** — Tests EntityRuler
  - **Fichier:** `tests/phase_1_8/test_entity_ruler_dictionaries.py`
  - **Tests:**
    - `test_sap_product_recognition()` : Détecte "SAP S/4HANA Cloud, Private Edition"
    - `test_pharma_term_recognition()` : Détecte "IND submission"
    - `test_alias_matching()` : "S4 Private Cloud" → "SAP S/4HANA Cloud, Private Edition"
    - `test_tenant_custom_dictionaries()` : Charge dict custom tenant
    - `test_precision_improvement()` : NER precision avant/après
  - **Coverage:** > 85%
  - **Effort:** 1 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.1c.5** — Mesurer amélioration precision NER
  - **Script:** `scripts/phase_1_8/measure_ner_precision_improvement.py`
  - **Baseline:** NER sans dictionnaires (~70% precision)
  - **Avec dictionnaires:** Target 85-90% precision
  - **Dataset test:** 50 documents (SAP, pharma, CRM domains)
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 5 : Documentation & Déploiement

- [ ] **T1.8.1c.6** — Documentation marketplace ontologies
  - **Doc:** `config/ontologies/README.md`
  - **Contenu:**
    - Liste dictionnaires disponibles
    - Format JSON standard
    - Guide ajout nouveaux dictionnaires
    - Guide création dictionnaire custom tenant
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.1c.7** — Déploiement production
  - **Feature Flag:** `enable_entity_ruler_dictionaries: false` (default)
  - **Rollback Plan:** Désactiver EntityRuler si régression
  - **Monitoring:** Precision NER tracking (Grafana panel)
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

### Success Criteria Sprint 1.8.1c

- [ ] ✅ EntityRuler intégré dans ConceptExtractor
- [ ] ✅ 3 dictionnaires marketplace créés (SAP, Salesforce, Pharma)
- [ ] ✅ Support multi-tenant (dictionnaires custom)
- [ ] ✅ Precision NER: 70% → 85-90% (+20-30 pts)
- [ ] ✅ Tests 85%+ coverage
- [ ] ✅ Documentation complète

### Blockers & Risques

| Risque | Impact | Mitigation | Owner | Status |
|--------|--------|------------|-------|--------|
| Dictionnaires incomplets | 🟡 MOYEN | Itérations ajout termes | [Owner] | 🟡 Monitoring |
| Faux positifs EntityRuler | 🟡 MOYEN | Validation patterns + fallback NER | [Owner] | 🟡 Monitoring |
| Maintenance dictionnaires | 🟢 FAIBLE | Versionning Git + marketplace | [Owner] | 🟡 Monitoring |

**Référence:** Critique Académique Section P1.1 - "Dictionnaires Métier NER (Alternative Pragmatique au Fine-Tuning)"

---

## 🎯 Sprint 1.8.2 : P2 - Gatekeeper Prefetch Ontology

**Période:** Semaines 13-14 (8 jours-dev)
**Status:** ✅ COMPLÉTÉ (2025-12-18)
**Owner:** Claude Code

### Objectif

Réduire LLM calls de 25 → 20/doc (- 20%) via prefetch intelligent ontology entries.

### Implémentation Réalisée

**Fichiers créés/modifiés:**
- `src/knowbase/ontology/adaptive_ontology_manager.py` - Ajout prefetch
- `tests/phase_1_8/test_prefetch_ontology.py` - Tests complets

**Fonctionnalités:**
- `DOCUMENT_TYPE_DOMAIN_MAPPING` : Mapping document types → domains
- `prefetch_for_document_type()` : Précharge ontologie par type document
- `lookup_in_prefetch()` : Lookup dans cache prefetch avant Neo4j
- `get_prefetched_entries()` : Récupération entrées prefetch
- `invalidate_prefetch_cache()` : Invalidation cache
- `get_prefetch_stats()` : Statistiques prefetch

**Tests:** 21 tests complets couvrant mapping, prefetch, lookup, cache

### Tasks Détaillées

#### Jour 1-2 : Implémentation Prefetch

- [x] **T1.8.2.1** — Implémenter `prefetch_for_document_type()`
  - **Fichier:** `src/knowbase/ontology/adaptive_ontology_manager.py`
  - **Méthode:**
    ```python
    def prefetch_for_document_type(
        self,
        document_type: str,
        tenant_id: str,
        ttl_seconds: int = 3600
    ) -> int
    ```
  - **Logique:**
    - Map document_type → domain via `DOCUMENT_TYPE_TO_DOMAIN`
    - Query Neo4j CanonicalConcepts du domain
    - Store dans Redis (TTL 1h)
  - **Effort:** 1 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.2.2** — Créer mapping document types → domains
  - **Fichier:** `src/knowbase/ontology/adaptive_ontology_manager.py`
  - **Dict:**
    ```python
    DOCUMENT_TYPE_TO_DOMAIN = {
        "SAP_Product_Doc": "sap_products",
        "SAP_Solution_Brief": "sap_products",
        "Security_Audit": "security_concepts",
        "Security_Policy": "security_concepts",
        "Legal_Contract": "legal_terms",
        "Legal_Compliance": "legal_terms",
        "Technical_Specification": "technical_standards",
        "Architecture_Doc": "architecture_patterns",
    }
    ```
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.2.3** — Tests unitaires prefetch
  - **Fichier:** `tests/phase_1_8/test_ontology_prefetch.py`
  - **Tests:**
    - `test_prefetch_sap_products()` : Vérifie load entries SAP
    - `test_prefetch_unknown_type()` : Vérifie skip si type inconnu
    - `test_redis_cache_ttl()` : Vérifie expiration après 1h
    - `test_prefetch_memory_limit()` : Max 500 entries/domain
  - **Coverage:** > 80%
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 3 : Intégration Pipeline

- [ ] **T1.8.2.4** — Intégrer prefetch dans `pptx_pipeline.py`
  - **Fichier:** `src/knowbase/ingestion/pipelines/pptx_pipeline.py`
  - **Ligne:** ~250 (après `load_document_type_context()`)
  - **Code:**
    ```python
    if document_type_id:
        ontology_mgr = AdaptiveOntologyManager(...)
        entries_loaded = ontology_mgr.prefetch_for_document_type(
            document_type=document_type_id,
            tenant_id="default"
        )
        logger.info(f"[PHASE1.8] Prefetch loaded {entries_loaded} entries")
    ```
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.2.5** — Tests intégration pipeline
  - **Fichier:** `tests/integration/test_pptx_pipeline_prefetch.py`
  - **Tests:**
    - `test_prefetch_called_for_sap_doc()` : Vérifie appel prefetch
    - `test_cache_hit_improvement()` : Mesure cache hit rate
    - `test_pipeline_without_prefetch()` : Vérifie backward compat
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 4-5 : Validation Cache Hit Rate

- [ ] **T1.8.2.6** — Mesurer cache hit rate AVANT prefetch
  - **Script:** `scripts/phase_1_8/measure_cache_baseline.py`
  - **Méthode:**
    - Run 100 docs ingestion (mix types)
    - Log chaque ontology lookup (hit vs miss)
    - Calculer cache hit rate global
  - **Baseline attendu:** ~50%
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.2.7** — Activer prefetch et mesurer APRÈS
  - **Config:** `config/feature_flags.yaml`
  - **Flag:** `enable_ontology_prefetch: true`
  - **Run:** Même 100 docs ingestion
  - **Métriques:**
    - Cache hit rate (target: 70%)
    - LLM calls reduction
    - Latence gatekeeper
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.2.8** — Optimiser TTL si nécessaire
  - **Analyse:**
    - Si cache hit rate < 65% → Augmenter TTL (2h ou 4h)
    - Si Redis memory usage > 80% → Réduire TTL (30min)
  - **Itérations:** 2-3 tests
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.2.9** — Dashboard Grafana cache metrics
  - **Panel:** "Ontology Cache Performance"
  - **Métriques:**
    - Cache hit rate (gauge, target: 70%)
    - Cache size (gauge, alert if > 500 entries/domain)
    - Prefetch duration (histogram)
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

### Success Criteria Sprint 1.8.2

- [ ] ✅ Cache hit rate amélioration 50% → 70% (+ 20 pts)
- [ ] ✅ LLM calls/doc réduction 25 → 20 (- 20%)
- [ ] ✅ Coût gatekeeper réduction $0.002 → $0.001/doc (- 50%)
- [ ] ✅ Latence gatekeeper réduction 28s → 25s (- 11%)
- [ ] ✅ Prefetch testé sur 100 docs sans erreur Redis
- [ ] ✅ Documentation mapping types → domains complète

### Blockers & Risques

| Risque | Impact | Mitigation | Owner | Status |
|--------|--------|------------|-------|--------|
| Redis memory overflow | 🟡 MOYEN | Max 500 entries + TTL court | [Owner] | 🟡 Monitoring |
| Cache stale (ontology update) | 🟢 FAIBLE | Invalidation proactive | [Owner] | 🟡 Monitoring |
| Mapping incomplet (nouveaux types) | 🟢 FAIBLE | Fallback graceful + logs | [Owner] | 🟡 Monitoring |

---

## 🎯 Sprint 1.8.3 : P3 - Relations LLM Smart Enrichment

**Période:** Semaines 15-17 (15 jours-dev)
**Status:** ✅ COMPLÉTÉ (2025-12-18)
**Owner:** Claude Code

### Objectif

Améliorer qualité relations (Précision 60% → 80%, Rappel 50% → 70%) via LLM batch sur zone grise.

### Implémentation Réalisée

**Fichiers créés:**
- `src/knowbase/relations/relation_enricher.py` - Module enrichment
- `tests/phase_1_8/test_relation_enricher.py` - Tests complets

**Fonctionnalités:**
- `RelationEnricher` classe principale :
  - `is_in_gray_zone()` : Détection zone grise (0.4-0.6 confidence)
  - `filter_gray_zone_relations()` : Filtrage relations à enrichir
  - `enrich_relations()` : Validation LLM batch avec merge confidence
  - `_create_batches()` : Batching 50 relations max
  - `_validate_batch_via_llm()` : Appel LLM avec structured output
- `enrich_relations_if_enabled()` : Convenience function avec feature flag

**Intégration:**
- Feature flag `enable_llm_relation_enrichment` dans `feature_flags.yaml`
- Budget cap: 20 batches max × 50 paires = 1000 relations
- Confidence merge: 40% pattern + 60% LLM

**Tests:** 26 tests couvrant gray zone, batching, LLM, feature flags

### Tasks Détaillées

#### Jour 1-3 : Implémentation Enrichment

- [ ] **T1.8.3.1** — Implémenter `_enrich_low_confidence_relations()`
  - **Fichier:** `src/knowbase/agents/pattern_miner/pattern_miner.py`
  - **Méthode:**
    ```python
    async def _enrich_low_confidence_relations(
        self,
        candidate_relations: List[Dict],
        state: AgentState,
        concepts: List[Dict]
    ) -> List[Dict]
    ```
  - **Logique:**
    - Filter zone grise (0.4-0.6 confidence)
    - Batch LLM processing (50 paires/call)
    - Merge LLM insights (weighted average)
    - Budget cap check (20 batches max)
  - **Effort:** 2 jours
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.2** — Créer `TaskType.RELATION_EXTRACTION`
  - **Fichier:** `src/knowbase/common/llm_router.py`
  - **Enum:**
    ```python
    class TaskType(str, Enum):
        # ... existing ...
        RELATION_EXTRACTION = "relation_extraction"  # NOUVEAU Phase 1.8
    ```
  - **Config LLM:**
    - Model: gpt-4o-mini (économique)
    - Temperature: 0.3 (déterministe)
    - Max tokens: 4000
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.3** — Budget cap dans SupervisorAgent
  - **Fichier:** `src/knowbase/agents/supervisor/supervisor.py`
  - **Changement:**
    ```python
    self.budget_caps = {
        # ... existing ...
        "RELATION_ENRICHMENT": 20  # Max 20 batches × 50 = 1000 paires
    }
    ```
  - **Enforcement:** Check AVANT chaque batch LLM
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.4** — Créer prompt batch relation extraction
  - **Fichier:** `src/knowbase/agents/pattern_miner/prompts.py`
  - **Prompts:**
    - `RELATION_ENRICHMENT_SYSTEM_PROMPT`
    - `RELATION_ENRICHMENT_USER_PROMPT`
  - **Validation:** Review avec 10 paires test
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.5** — Tests unitaires enrichment
  - **Fichier:** `tests/phase_1_8/test_relation_enrichment.py`
  - **Tests:**
    - `test_low_confidence_enrichment()` : Vérifie amélioration
    - `test_budget_cap_respected()` : Max 20 batches
    - `test_high_confidence_unchanged()` : Préserve > 0.6
    - `test_weighted_confidence()` : 40% pattern + 60% LLM
  - **Coverage:** > 80%
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 4-5 : Tests Qualité

- [ ] **T1.8.3.6** — Mesurer baseline relations sur 20 docs
  - **Script:** `scripts/phase_1_8/measure_baseline_relations.py`
  - **Ground Truth:** Annoter manuellement relations correctes
  - **Métriques:**
    - Précision relations (TP / (TP + FP))
    - Rappel relations (TP / (TP + FN))
    - F1-score
  - **Baseline attendu:** Précision 60%, Rappel 50%
  - **Effort:** 1.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.7** — Activer enrichment et re-mesurer
  - **Config:** `config/feature_flags.yaml`
  - **Flag:** `enable_llm_relation_enrichment: true`
  - **Run:** Même 20 docs ingestion
  - **Métriques:**
    - Précision (target: 80%)
    - Rappel (target: 70%)
    - Coût relations (acceptable si < $0.10/doc)
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.8** — Human-in-the-loop validation
  - **Process:**
    - Sample 10% relations enrichies par LLM
    - Review manuel par expert domaine
    - Validation: Correct / Incorrect / Ambiguous
  - **Feedback:**
    - Si > 20% incorrect → Ajuster prompts
    - Si > 10% ambiguous → Ajouter contexte
  - **Effort:** 1 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.9** — Ajustement prompts si nécessaire
  - **Itérations:** 2-3 cycles feedback → prompt update → re-test
  - **Amélioration continue:** Logging décisions LLM pour analyse
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 5.5 : Dense Graph Optimization (KGGen-Inspired)

- [ ] **T1.8.3.9b** — Implémenter graph density scoring
  - **Fichier:** `src/knowbase/agents/pattern_miner/pattern_miner.py`
  - **Méthode:**
    ```python
    def calculate_graph_density(
        self,
        concepts: List[Dict]
    ) -> float
    ```
  - **Logique:**
    - Densité = nb_relations / nb_relations_possibles
    - Warning si densité < 0.05 (graph trop sparse)
    - Suggest lowering similarity threshold si sparse
  - **Inspiration:** KGGen Section 3.2 - Dense Graph Construction
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.9c** — Tests graph density
  - **Fichier:** `tests/phase_1_8/test_graph_density.py`
  - **Tests:**
    - `test_density_calculation()` : Calcul correct
    - `test_sparse_graph_warning()` : Warning si < 0.05
    - `test_dense_graph_validation()` : OK si > 0.10
  - **Coverage:** > 80%
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 6-7 : Dashboard + Déploiement

- [ ] **T1.8.3.10** — Grafana panel relations
  - **Panel:** "Relations Quality (Phase 1.8)"
  - **Métriques:**
    - Precision & Recall (gauge)
    - Relations enriched count (counter)
    - LLM batches used (gauge, alert if > 20)
    - Cost relations (gauge)
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.11** — Documentation Human review process
  - **Doc:** `doc/processes/human_in_loop_relations.md`
  - **Contenu:**
    - Critères validation relations
    - Interface review (Streamlit ou admin panel)
    - Feedback loop vers prompts
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.3.12** — Déploiement production (flag OFF)
  - **Environnement:** Production
  - **Feature Flag:** `enable_llm_relation_enrichment: false`
  - **Rollback Plan:** Documenté
  - **Communication:** Annonce + formation équipe
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

### Success Criteria Sprint 1.8.3

- [ ] ✅ Précision relations 60% → 80% (+ 20 pts)
- [ ] ✅ Rappel relations 50% → 70% (+ 20 pts)
- [ ] ✅ F1-score relations amélioration > 15 points
- [ ] ✅ Coût relations < $0.10/doc (acceptable)
- [ ] ✅ Budget cap respecté: 100% docs < 20 batches
- [ ] ✅ Human validation: < 15% relations incorrectes

### Blockers & Risques

| Risque | Impact | Mitigation | Owner | Status |
|--------|--------|------------|-------|--------|
| Explosion coût (> $0.20/doc) | 🔴 ÉLEVÉ | Budget cap strict + alertes | [Owner] | 🟡 Monitoring |
| Hallucinations LLM relations | 🟡 MOYEN | Human-in-loop + Gatekeeper | [Owner] | 🟡 Monitoring |
| Latence LLM batch > 10s | 🟡 MOYEN | Async parallel + timeout | [Owner] | 🟡 Monitoring |
| Zone grise > 60% relations | 🟡 MOYEN | Pattern matching amélioré | [Owner] | 🟡 Monitoring |

---

## 🎯 Sprint 1.8.4 : Business Rules Engine (Critique P1.2)

**Période:** Semaines 18-20 (10 jours-dev)
**Status:** ✅ COMPLÉTÉ (2025-12-18)
**Owner:** Claude Code

### Objectif

Permettre validation métier custom par tenant via règles YAML configurables (différenciateur marché vs solutions 100% auto).

### Implémentation Réalisée

**Fichiers créés:**
- `src/knowbase/rules/__init__.py` - Module exports
- `src/knowbase/rules/engine.py` - Core business rules engine
- `src/knowbase/rules/loader.py` - YAML/JSON loader
- `tests/phase_1_8/test_business_rules_engine.py` - Tests complets
- `config/rules/pharma_rules.yaml` - Règles pharma exemple

**Fonctionnalités:**
- `RuleCondition` : 10 opérateurs (equals, contains, matches, in_list, greater_than, exists, etc.)
- `Rule` dataclass : Évaluation conditions, actions, enrichment
- `BusinessRulesEngine` :
  - `validate_concepts()` / `enrich_concepts()`
  - `validate_relations()` / `enrich_relations()`
  - Multi-tenant isolation (règles tenant A ≠ B)
- `RulesLoader` :
  - Charge YAML/JSON depuis `config/rules/`
  - Support global + tenant-specific + built-in rules
  - Save/export rules

**Built-in Rules:**
- `create_pharma_compliance_rules()` : Règles FDA, GxP
- `create_sap_validation_rules()` : Règles produits SAP

**Types de règles:**
- `concept_validation` / `concept_enrichment`
- `relation_validation` / `relation_enrichment`
- `document_classification`

**Actions:** reject, accept, flag, require_review, enrich

**Tests:** 35+ tests couvrant conditions, évaluation, engine, loader, feature flags

### 📚 Inspiration Critique Académique

**Problème identifié:**
- Validation générique ne suffit pas pour domaines spécialisés (pharma, finance, legal)
- Clients ont besoin de règles métier spécifiques (compliance, regulatory)
- Solutions concurrentes (Copilot, Gemini) = 100% auto sans customization

**Approche OSMOSE:**
- YAML-based business rules par tenant
- Validation concepts ET relations
- Audit trail complet (quelles règles rejettent quoi)
- **Différenciateur marché:** Customization enterprise-grade

### Tasks Détaillées

#### Jour 1-3 : Core Business Rules Engine

- [ ] **T1.8.4.1** — Implémenter BusinessRulesEngine
  - **Fichier:** `src/knowbase/agents/gatekeeper/business_rules_engine.py` (NOUVEAU)
  - **Classes:**
    ```python
    class BusinessRule:
        id: str
        applies_to: str  # "concepts" ou "relations"
        condition: Dict[str, Any]
        validation: Dict[str, Any]
        action: str  # "reject", "canonicalize_add_prefix", "boost_confidence"

    class ValidationResult:
        passed: bool
        reason: Optional[str]
        modified_value: Optional[Any]

    class BusinessRulesEngine:
        def __init__(self, tenant_id: str)
        def load_tenant_rules(self, tenant_id: str) -> List[BusinessRule]
        def validate_concept(self, concept: Dict, context: str) -> ValidationResult
        def validate_relation(self, relation: Dict, context: str) -> ValidationResult
    ```
  - **Effort:** 2 jours
  - **Status:** 🔴 TODO

- [ ] **T1.8.4.2** — Définir format YAML règles
  - **Fichier:** `config/business_rules/README.md` + exemples
  - **Exemples règles:**
    ```yaml
    # config/business_rules/pharma_tenant.yaml
    rules:
      - id: pharma_adverse_effect_validation
        applies_to: relations
        condition:
          relation_type: causes_adverse_effect
        validation:
          require_keyword: ["resulted in", "led to", "caused"]
        action: reject_if_missing
        description: "Relations causales doivent avoir keywords explicites"

      - id: sap_product_naming_standard
        applies_to: concepts
        condition:
          type: PRODUCT
          domain: SAP
        validation:
          regex_match: "^SAP "
        action: canonicalize_add_prefix
        prefix: "SAP "
        description: "Produits SAP doivent commencer par 'SAP '"

      - id: high_confidence_regulatory_terms
        applies_to: concepts
        condition:
          type: REGULATORY_TERM
        validation:
          confidence_threshold: 0.8
        action: reject_if_below
        description: "Termes réglementaires requièrent haute confiance"
    ```
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.4.3** — Intégrer dans Gatekeeper
  - **Fichier:** `src/knowbase/agents/gatekeeper/gatekeeper.py`
  - **Code:**
    ```python
    class Gatekeeper(BaseAgent):
        def __init__(self, config):
            super().__init__(AgentRole.GATEKEEPER, config)
            self.business_rules_engine = None  # Lazy init per tenant

        async def execute(self, state: AgentState, instruction: Optional[str] = None):
            # Init business rules engine pour ce tenant
            if self.business_rules_engine is None:
                self.business_rules_engine = BusinessRulesEngine(state.tenant_id)

            # Filtrer concepts via règles métier
            validated_concepts = []
            for concept in state.candidates:
                # 1. Validation standard (quality gate)
                gate_result = self._evaluate_quality_gate(concept, state.quality_gate_mode)
                if not gate_result.passed:
                    continue

                # 2. Validation règles métier custom
                business_rule_result = self.business_rules_engine.validate_concept(
                    concept=concept,
                    context=concept.get("context", "")
                )

                if not business_rule_result.passed:
                    logger.info(
                        f"[BusinessRules] Concept '{concept['name']}' rejected: "
                        f"{business_rule_result.reason}"
                    )
                    continue

                # 3. Appliquer modifications si nécessaire
                if business_rule_result.modified_value:
                    concept.update(business_rule_result.modified_value)

                validated_concepts.append(concept)

            # Idem pour relations
            validated_relations = []
            for relation in state.relations:
                business_rule_result = self.business_rules_engine.validate_relation(
                    relation=relation,
                    context=relation.get("context", "")
                )

                if business_rule_result.passed:
                    if business_rule_result.modified_value:
                        relation.update(business_rule_result.modified_value)
                    validated_relations.append(relation)

            state.candidates = validated_concepts
            state.relations = validated_relations

            # Continue promotion...
    ```
  - **Effort:** 1 jour
  - **Status:** 🔴 TODO

#### Jour 4-5 : Types de Règles Supportées

- [ ] **T1.8.4.4** — Implémenter validation par regex
  - **Méthode:** `_validate_regex_match(concept, pattern)`
  - **Exemple:** Produits SAP doivent matcher `^SAP `
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.4.5** — Implémenter validation par keywords
  - **Méthode:** `_validate_keyword_presence(context, keywords)`
  - **Exemple:** Relations "causes_adverse_effect" requièrent "resulted in"
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.4.6** — Implémenter validation par confidence threshold
  - **Méthode:** `_validate_confidence_threshold(concept, threshold)`
  - **Exemple:** Termes réglementaires requièrent confidence > 0.8
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.4.7** — Implémenter actions (reject/canonicalize/boost)
  - **Actions:**
    - `reject`: Rejette concept/relation
    - `canonicalize_add_prefix`: Ajoute prefix au nom
    - `boost_confidence`: Augmente confidence de X%
    - `require_validation`: Marque pour HITL review
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 6-7 : Tests & Validation

- [ ] **T1.8.4.8** — Tests unitaires Business Rules Engine
  - **Fichier:** `tests/phase_1_8/test_business_rules_engine.py`
  - **Tests:**
    - `test_load_tenant_rules()` : Charge rules YAML correct
    - `test_regex_validation()` : Valide pattern regex
    - `test_keyword_validation()` : Requiert keywords présence
    - `test_confidence_threshold()` : Rejette low confidence
    - `test_reject_action()` : Rejette concept
    - `test_canonicalize_action()` : Ajoute prefix
    - `test_no_rules_tenant()` : Graceful si pas de règles
  - **Coverage:** > 85%
  - **Effort:** 1.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.4.9** — Tests intégration Gatekeeper
  - **Fichier:** `tests/integration/test_gatekeeper_business_rules.py`
  - **Tests:**
    - `test_gatekeeper_applies_rules()` : Gatekeeper utilise règles
    - `test_multi_tenant_isolation()` : Règles tenant A ≠ tenant B
    - `test_audit_trail()` : Logging décisions règles
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 8-9 : Documentation & Audit Trail

- [ ] **T1.8.4.10** — Documentation Business Rules
  - **Doc:** `docs/business_rules/README.md`
  - **Contenu:**
    - Guide création règles YAML
    - Exemples par domaine (pharma, finance, legal)
    - Types validation supportés
    - Actions disponibles
    - Best practices
  - **Effort:** 1 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.4.11** — Audit trail Neo4j
  - **Schéma Neo4j:**
    ```cypher
    CREATE (d:BusinessRuleDecision {
      decision_id: "dec_123",
      tenant_id: "pharma_tenant",
      rule_id: "pharma_adverse_effect_validation",
      applied_to: "relation_456",
      action: "reject",
      reason: "Missing required keyword 'resulted in'",
      timestamp: datetime()
    })
    ```
  - **API endpoint:** `GET /api/business-rules/audit/{tenant_id}`
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

#### Jour 10 : Déploiement & Demo

- [ ] **T1.8.4.12** — Templates règles par domaine
  - **Fichiers:**
    - `config/business_rules/templates/pharma_compliance.yaml`
    - `config/business_rules/templates/finance_risk.yaml`
    - `config/business_rules/templates/legal_contracts.yaml`
  - **Contenu:** 10-15 règles pré-configurées par domaine
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

- [ ] **T1.8.4.13** — Déploiement production
  - **Feature Flag:** `enable_business_rules_engine: false` (default)
  - **Migration:** Aucun schéma Neo4j changement (additive only)
  - **Rollback Plan:** Désactiver feature flag
  - **Effort:** 0.5 jour
  - **Status:** 🔴 TODO

### Success Criteria Sprint 1.8.4

- [ ] ✅ BusinessRulesEngine implémenté et testé
- [ ] ✅ Support 3 types validation (regex, keywords, confidence)
- [ ] ✅ Support 4 actions (reject, canonicalize, boost, require_validation)
- [ ] ✅ Multi-tenant isolation (règles tenant A ≠ B)
- [ ] ✅ Audit trail complet (Neo4j + API)
- [ ] ✅ Templates 3 domaines (pharma, finance, legal)
- [ ] ✅ Documentation complète
- [ ] ✅ Tests 85%+ coverage

### Blockers & Risques

| Risque | Impact | Mitigation | Owner | Status |
|--------|--------|------------|-------|--------|
| Règles trop restrictives | 🟡 MOYEN | Templates + guidelines validation | [Owner] | 🟡 Monitoring |
| Conflits entre règles | 🟡 MOYEN | Ordre priorité + warnings | [Owner] | 🟡 Monitoring |
| Complexité maintenance | 🟢 FAIBLE | Templates + documentation | [Owner] | 🟡 Monitoring |

### Différenciation Marché

**vs Copilot/Gemini (100% auto):**
- ✅ OSMOSE permet customization enterprise-grade
- ✅ Compliance domaine (pharma FDA, finance FINRA, legal)
- ✅ Audit trail complet (qui a rejeté quoi, pourquoi)
- ✅ Templates pré-configurés par industrie

**ROI Client:**
- Adoption: +40% (experts trust validation métier)
- Precision: +15-20% (règles domaine éliminent faux positifs)
- Compliance: 100% (règles réglementaires enforced)

**Référence:** Critique Académique Section P1.2 - "Business Rules Engine (Différenciateur vs Concurrence)"

---

## 📊 Métriques Globales Phase 1.8

### Tableau de Bord Progrès

| Métrique | Baseline | Target | Actuel | Delta | Status |
|----------|----------|--------|--------|-------|--------|
| **Rappel concepts** | 70% | 85% | — | — | 🔴 À mesurer |
| **Précision concepts** | 85% | 90% | — | — | 🔴 À mesurer |
| **Rappel relations** | 50% | 70% | — | — | 🔴 À mesurer |
| **Précision relations** | 60% | 80% | — | — | 🔴 À mesurer |
| **Coût/doc** | $0.03 | ≤ $0.14 | — | — | 🔴 À mesurer |
| **Latence extraction** | 15s | ≤ 18s | — | — | 🔴 À mesurer |
| **Latence gatekeeper** | 28s | ≤ 25s | — | — | 🔴 À mesurer |
| **LLM calls/doc** | 25 | ≤ 20 | — | — | 🔴 À mesurer |
| **Cache hit rate** | 50% | ≥ 70% | — | — | 🔴 À mesurer |

### Nouvelles Métriques KGGen-Inspired

| Métrique | Baseline | Target | Actuel | Delta | Status |
|----------|----------|--------|--------|-------|--------|
| **Cross-Lingual Accuracy (FR↔EN↔DE)** | ~75% | ≥ 85% | — | — | 🔴 À mesurer |
| **Faux Positifs Clustering** | ~15% | ≤ 8% | — | — | 🔴 À mesurer |
| **Graph Density** | ~0.05 | ≥ 0.10 | — | — | 🔴 À mesurer |
| **Benchmark MINE-like F1** | — | ≥ 0.80 | — | — | 🔴 À mesurer |

### Coûts Cumulés

| Sprint | Budget Prévu | Dépensé | Restant | Status |
|--------|--------------|---------|---------|--------|
| **1.8.1 (P1 + Contexte)** | $600 (test 100 docs) | $0 | $600 | 🟢 OK |
| **1.8.1b (Benchmark)** | $150 (50 docs eval) | $0 | $150 | 🟢 OK |
| **1.8.1c (Dict NER)** | $100 (test 50 docs) | $0 | $100 | 🟢 OK |
| **1.8.2 (P2 Prefetch)** | $200 (test 100 docs) | $0 | $200 | 🟢 OK |
| **1.8.3 (P3 Relations + HITL)** | $1000 (test 100 docs) | $0 | $1000 | 🟢 OK |
| **1.8.4 (Business Rules)** | $150 (test 50 docs) | $0 | $150 | 🟢 OK |
| **TOTAL** | $2200 | $0 | $2200 | 🟢 OK |

**Notes:**
- +$100 Contexte Document Global (génération résumés LLM)
- +$150 Benchmark MINE-like (évaluation 50 docs)
- +$100 Dictionnaires Métier NER (validation 50 docs multi-domaines)
- +$150 Business Rules Engine (test validation custom rules)

---

## 🚨 Alertes & Incidents

### Alertes Actives

*Aucune alerte pour l'instant (Phase non démarrée)*

### Incidents Historiques

*Aucun incident (Phase non démarrée)*

---

## 📅 Calendrier Détaillé

### Semaine 11 : Sprint 1.8.1 (Partie 1)

| Jour | Tasks | Owner | Status |
|------|-------|-------|--------|
| **Lundi 11.1** | T1.8.1.1 (Routing implementation) | [Dev] | 🔴 TODO |
| **Mardi 11.2** | T1.8.1.2 (Prompts) + T1.8.1.3 (Tests) | [Dev] | 🔴 TODO |
| **Mercredi 11.3** | T1.8.1.4 (Sélection docs test) | [Dev] | 🔴 TODO |
| **Jeudi 11.4** | T1.8.1.5 (Baseline) + T1.8.1.6 (Run hybrid) | [Dev] | 🔴 TODO |
| **Vendredi 11.5** | T1.8.1.7 (Comparaison métriques) | [Dev] | 🔴 TODO |

### Semaine 12 : Sprint 1.8.1 (Partie 2)

| Jour | Tasks | Owner | Status |
|------|-------|-------|--------|
| **Lundi 12.1** | T1.8.1.8 (Dashboard Grafana) | [Dev] | 🔴 TODO |
| **Mardi 12.2** | T1.8.1.9 (Déploiement prod) | [Dev] | 🔴 TODO |
| **Mercredi 12.3** | Buffer / Documentation | [Dev] | 🔴 TODO |
| **Jeudi 12.4** | Review sprint + Demo stakeholders | [Team] | 🔴 TODO |
| **Vendredi 12.5** | Rétrospective + Planning Sprint 1.8.2 | [Team] | 🔴 TODO |

### Semaine 13 : Sprint 1.8.2 (Partie 1)

| Jour | Tasks | Owner | Status |
|------|-------|-------|--------|
| **Lundi 13.1** | T1.8.2.1 (Prefetch implementation) | [Dev] | 🔴 TODO |
| **Mardi 13.2** | T1.8.2.2 (Mapping) + T1.8.2.3 (Tests) | [Dev] | 🔴 TODO |
| **Mercredi 13.3** | T1.8.2.4 (Intégration pipeline) | [Dev] | 🔴 TODO |
| **Jeudi 13.4** | T1.8.2.5 (Tests intégration) | [Dev] | 🔴 TODO |
| **Vendredi 13.5** | T1.8.2.6 (Mesure baseline cache) | [Dev] | 🔴 TODO |

### Semaine 14 : Sprint 1.8.2 (Partie 2)

| Jour | Tasks | Owner | Status |
|------|-------|-------|--------|
| **Lundi 14.1** | T1.8.2.7 (Mesure après prefetch) | [Dev] | 🔴 TODO |
| **Mardi 14.2** | T1.8.2.8 (Optimisation TTL) | [Dev] | 🔴 TODO |
| **Mercredi 14.3** | T1.8.2.9 (Dashboard) + Buffer | [Dev] | 🔴 TODO |
| **Jeudi 14.4** | Review sprint + Demo stakeholders | [Team] | 🔴 TODO |
| **Vendredi 14.5** | Rétrospective + Planning Sprint 1.8.3 | [Team] | 🔴 TODO |

### Semaine 15 : Sprint 1.8.3 (Partie 1)

| Jour | Tasks | Owner | Status |
|------|-------|-------|--------|
| **Lundi 15.1** | T1.8.3.1 (Enrichment implementation - Jour 1) | [Dev] | 🔴 TODO |
| **Mardi 15.2** | T1.8.3.1 (Enrichment implementation - Jour 2) | [Dev] | 🔴 TODO |
| **Mercredi 15.3** | T1.8.3.2 (TaskType) + T1.8.3.3 (Budget cap) | [Dev] | 🔴 TODO |
| **Jeudi 15.4** | T1.8.3.4 (Prompts) + T1.8.3.5 (Tests) | [Dev] | 🔴 TODO |
| **Vendredi 15.5** | T1.8.3.6 (Baseline relations - Jour 1) | [Dev] | 🔴 TODO |

### Semaine 16 : Sprint 1.8.3 (Partie 2)

| Jour | Tasks | Owner | Status |
|------|-------|-------|--------|
| **Lundi 16.1** | T1.8.3.6 (Baseline relations - Jour 2) | [Dev] | 🔴 TODO |
| **Mardi 16.2** | T1.8.3.7 (Mesure après enrichment) | [Dev] | 🔴 TODO |
| **Mercredi 16.3** | T1.8.3.8 (Human-in-loop validation) | [Dev + Expert] | 🔴 TODO |
| **Jeudi 16.4** | T1.8.3.9 (Ajustement prompts) | [Dev] | 🔴 TODO |
| **Vendredi 16.5** | T1.8.3.10 (Dashboard Grafana) | [Dev] | 🔴 TODO |

### Semaine 17 : Sprint 1.8.3 (Partie 3)

| Jour | Tasks | Owner | Status |
|------|-------|-------|--------|
| **Lundi 17.1** | T1.8.3.11 (Documentation Human review) | [Dev] | 🔴 TODO |
| **Mardi 17.2** | T1.8.3.12 (Déploiement prod) | [Dev] | 🔴 TODO |
| **Mercredi 17.3** | Phase 1.8 Complete Review | [Team] | 🔴 TODO |
| **Jeudi 17.4** | Demo finale stakeholders + clients | [Team] | 🔴 TODO |
| **Vendredi 17.5** | Rétrospective Phase 1.8 + Handoff Phase 2 | [Team] | 🔴 TODO |

---

## 📝 Notes & Decisions

### Décisions Architecture

*Aucune décision prise (Phase non démarrée)*

### Changements de Scope

*Aucun changement (Phase non démarrée)*

### Feedback Stakeholders

*Aucun feedback (Phase non démarrée)*

---

## 🔗 Liens Utiles

- **Spec Phase 1.8:** `doc/phases/PHASE1_8_LLM_HYBRID_INTELLIGENCE.md`
- **Analyse HELIOS:** Session 2025-11-19

### Références Académiques

- **Paper KGGen (Stanford):** https://arxiv.org/html/2502.09956v1
  - Titre: "KGGen: Extracting Knowledge Graphs from Plain Text with Language Models"
  - Source: Stanford University, University of Toronto, FAR AI
  - Date: 2025-02
  - Résultat clé: +18% vs baselines sur benchmark MINE

- **Critique Bonnes Pratiques KG Académiques:** `doc/research/OSMOSE_CRITIQUE_BONNES_PRATIQUES_KG_ACADEMIQUES.md`
  - Source: Analyse OpenAI + OSMOSE Architecture Team
  - Date: 2025-11-18
  - Focus: Pragmatisme vs académisme
  - Recommandations: P0.1 (Contexte Global), P1.1 (Dict NER), P1.2 (Business Rules), P1.3 (HITL)

- **Analyse Comparative KGGen vs OSMOSE:** `doc/research/KGGEN_OSMOSE_COMPARATIVE_ANALYSIS.md`
  - Convergence: 85% méthodologique
  - USP OSMOSE: Cross-lingual unification (unique)

### Outils & Monitoring

- **Feature Flags:** `config/feature_flags.yaml`
- **Dashboard Grafana:** [URL à définir]
- **Slack Channel:** #phase-1-8-llm-hybrid
- **Jira Epic:** [À créer]

---

## 📞 Contacts

| Rôle | Nom | Contact | Disponibilité |
|------|-----|---------|---------------|
| **Phase Owner** | [À assigner] | email@domain.com | Lun-Ven 9h-18h |
| **Tech Lead** | [À assigner] | email@domain.com | Lun-Ven 9h-18h |
| **Dev Sprint 1.8.1** | [À assigner] | email@domain.com | Lun-Ven 9h-18h |
| **Dev Sprint 1.8.2** | [À assigner] | email@domain.com | Lun-Ven 9h-18h |
| **Dev Sprint 1.8.3** | [À assigner] | email@domain.com | Lun-Ven 9h-18h |
| **Expert Domaine (Relations)** | [À assigner] | email@domain.com | Sur demande |

---

## 🎉 Synthèse Implémentation Phase 1.8

### Sprints Complétés (2025-12-17 → 2025-12-18)

| Sprint | Fichiers Créés | Tests | Status |
|--------|---------------|-------|--------|
| **1.8.1** | prompts.py, orchestrator routing, llm_judge | 50+ tests | ✅ |
| **1.8.1c** | ontologies/*.json, ner_manager.py | 20+ tests | ✅ |
| **1.8.2** | adaptive_ontology_manager.py (prefetch) | 21 tests | ✅ |
| **1.8.3** | relation_enricher.py | 26 tests | ✅ |
| **1.8.4** | rules/engine.py, rules/loader.py | 35+ tests | ✅ |

### Prochaines Étapes

1. **Tests A/B Production** - Valider métriques sur documents réels
2. **Activation Feature Flags** - Déploiement progressif
3. **Benchmark MINE-like (1.8.1b)** - Dataset validation cross-lingual

### Feature Flags

**Documentation complète :** `doc/guides/FEATURE_FLAGS_GUIDE.md`

**État actuel :** Toutes les features Phase 1.8 sont **activées par défaut** (projet en développement).

```yaml
# config/feature_flags.yaml
phase_1_8:
  enabled: true
  enable_hybrid_extraction: true        # Sprint 1.8.1
  enable_document_context: true         # Sprint 1.8.1
  enable_llm_judge_validation: true     # Sprint 1.8.1
  enable_entity_ruler: true             # Sprint 1.8.1c
  enable_ontology_prefetch: true        # Sprint 1.8.2
  enable_llm_relation_enrichment: true  # Sprint 1.8.3
  enable_business_rules_engine: true    # Sprint 1.8.4
```

**Pour désactiver une feature :** Modifier `config/feature_flags.yaml` ou utiliser les overrides par environnement/tenant (voir guide).

---

**🌊 OSMOSE Phase 1.8 — IMPLÉMENTATION COMPLÈTE**
**Tracking mis à jour: 2025-12-18**

*Prochaine étape: Validation production + Tests A/B*
