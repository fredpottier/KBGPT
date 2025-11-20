# Phase 1.8 : LLM Hybrid Intelligence

**Période:** Semaines 11-17 (7 semaines)
**Status:** 🟡 PLANIFIÉE
**Objectif:** Optimiser extraction concepts et relations via LLM ciblé sans compromettre l'USP OSMOSE

---

## 🎯 Vision Phase 1.8

### Raison d'Être

Suite à l'analyse HELIOS (2025-11-19), cette phase améliore la **qualité du Knowledge Graph** en utilisant les LLMs modernes de manière **intelligente et économe**, tout en **préservant l'USP différenciateur** de KnowWhere :

- ✅ **Dual-Graph Architecture** (Proto-KG → Published-KG)
- ✅ **Gatekeeper Quality Gates** (STRICT/BALANCED/PERMISSIVE)
- ✅ **Adaptive Ontology Learning** (amélioration incrémentale)
- ✅ **Cost-Aware Routing** (NO_LLM/SMALL/BIG)

### Anti-Patterns à Éviter

❌ **NE PAS** devenir un "Copilot clone" (LLM end-to-end sans quality gates)
❌ **NE PAS** sacrifier l'ontology learning pour du LLM pur
❌ **NE PAS** exploser les coûts (target max: $0.14/doc vs $0.03 baseline)

---

## 📊 Métriques Baseline (Phase 1 V2.1)

### Performance Actuelle

```
Document moyen (50 segments, 100 concepts, 150 relations):
├─ Rappel concepts: 70%
├─ Précision concepts: 85%
├─ Rappel relations: 50%
├─ Précision relations: 60%
├─ Coût total: $0.03/doc
├─ Latence extraction: 15s
├─ Latence gatekeeper: 28s (556 concepts batch)
├─ LLM calls/doc: 25
└─ Ontology cache hit rate: 50%
```

### Targets Phase 1.8

```
Document moyen (50 segments, 100 concepts, 150 relations):
├─ Rappel concepts: 85% (+ 15 pts) ✅
├─ Précision concepts: 90% (+ 5 pts) ✅
├─ Rappel relations: 70% (+ 20 pts) ✅
├─ Précision relations: 80% (+ 20 pts) ✅
├─ Coût total: $0.14/doc (+ 367%, justified) ⚠️
├─ Latence extraction: 18s (+ 3s, acceptable)
├─ Latence gatekeeper: 25s (- 3s, optimization) ✅
├─ LLM calls/doc: 20 (- 5, via prefetch) ✅
└─ Ontology cache hit rate: 70% (+ 20 pts) ✅
```

---

## 🚀 Sprints Phase 1.8

### **Sprint 1.8.1 : P1 - Extraction Concepts Hybrid (Semaines 11-12)**

**Objectif:** Améliorer rappel concepts via LLM ciblé sur segments LOW-QUALITY NER

**Composants impactés:**
- `src/knowbase/agents/extractor/orchestrator.py`
- `src/knowbase/semantic/extraction/concept_extractor.py`

**Livrables:**
1. ✅ Nouveau routing rule : `LOW_QUALITY_NER` → LLM structured output
2. ✅ Prompt optimisé triples extraction (concepts + relations)
3. ✅ Feature flag `ENABLE_HYBRID_EXTRACTION` (default: OFF)
4. ✅ Tests A/B sur 50 documents (baseline vs hybrid)
5. ✅ Dashboard métriques : Rappel/Précision avant/après
6. ✅ Budget alert si coût > $0.10/doc

**Effort:** 10 jours-dev (2 semaines)
**Risques:**
- ⚠️ Coût réel > prévu si routing rule trop permissif
- ⚠️ Latence LLM dépasse 5s/segment (target: 2-3s)

**Success Criteria:**
- Rappel concepts: 70% → 85% (+ 15 pts)
- Coût: $0.03 → $0.05/doc (+ 67%, acceptable)
- Feature flag testée sur 100 documents prod

---

### **Sprint 1.8.2 : P2 - Gatekeeper Prefetch Ontology (Semaines 13-14)**

**Objectif:** Réduire LLM calls via prefetch intelligent ontology

**Composants impactés:**
- `src/knowbase/ontology/adaptive_ontology_manager.py`
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py`
- `src/knowbase/common/clients/redis_client.py`

**Livrables:**
1. ✅ `prefetch_for_document_type()` dans `AdaptiveOntologyManager`
2. ✅ Mapping document types → ontology domains
   - SAP_Product_Doc → `sap_products`
   - Security_Audit → `security_concepts`
   - Legal_Contract → `legal_terms`
3. ✅ Intégration prefetch dans `pptx_pipeline.py:250`
4. ✅ Redis cache warming automatique (TTL 1h)
5. ✅ Métriques cache hit rate avant/après
6. ✅ Documentation mapping types → domains

**Effort:** 8 jours-dev (2 semaines)
**Risques:**
- ⚠️ Redis memory overflow si ontology trop large (mitigation: TTL court)
- ⚠️ Cache stale si ontology mise à jour (mitigation: invalidation proactive)

**Success Criteria:**
- LLM calls/doc: 25 → 20 (- 20%)
- Ontology cache hit rate: 50% → 70% (+ 20 pts)
- Coût gatekeeper: $0.002 → $0.001/doc (- 50%)
- Latence gatekeeper: 28s → 25s (- 3s)

---

### **Sprint 1.8.3 : P3 - Relations LLM Smart Enrichment (Semaines 15-17)**

**Objectif:** Améliorer précision/rappel relations via LLM sur zone grise

**Composants impactés:**
- `src/knowbase/agents/pattern_miner/pattern_miner.py`
- `src/knowbase/common/llm_router.py` (nouveau TaskType)
- `src/knowbase/agents/supervisor/supervisor.py` (budget cap)

**Livrables:**
1. ✅ `_enrich_low_confidence_relations()` dans `PatternMiner`
2. ✅ Nouveau `TaskType.RELATION_EXTRACTION`
3. ✅ Budget cap : MAX 20 batches × 50 paires = 1000 paires/doc
4. ✅ Prompt batch relation extraction optimisé
5. ✅ Feature flag `ENABLE_LLM_RELATION_ENRICHMENT` (default: OFF)
6. ✅ Human-in-the-loop validation (sample 10% relations)
7. ✅ Dashboard métriques relations : Précision/Rappel avant/après

**Effort:** 15 jours-dev (3 semaines)
**Risques:**
- ⚠️ Explosion coût si zone grise > 60% relations (mitigation: budget cap strict)
- ⚠️ Hallucinations LLM créent faux positifs (mitigation: confidence weighting)
- ⚠️ Latence LLM batch > 10s (mitigation: async parallel batches)

**Success Criteria:**
- Précision relations: 60% → 80% (+ 20 pts)
- Rappel relations: 50% → 70% (+ 20 pts)
- Coût relations: $0.01 → $0.08/doc (+ 700%, justified by quality)
- Budget cap respecté: 100% documents < 20 batches

---

## 📐 Architecture Technique Détaillée

### 1. Extraction Concepts Hybrid (P1)

#### Nouveau Routing Rule

```python
# src/knowbase/agents/extractor/orchestrator.py

class ExtractorOrchestrator(BaseAgent):
    def _select_extraction_route_v18(
        self,
        prepass_output: PrepassAnalyzerOutput,
        segment_text: str,
        state: AgentState
    ) -> ExtractionRoute:
        """
        Routing intelligent V1.8 avec détection LOW_QUALITY_NER.

        Règles:
        1. Si NER < 3 entities ET segment > 200 tokens → SMALL (LLM)
        2. Si NER < 3 entities ET segment ≤ 200 tokens → NO_LLM
        3. Si 3 ≤ NER ≤ 8 → SMALL
        4. Si NER > 8 → BIG

        Fallback chain: BIG → SMALL → NO_LLM (selon budget)
        """
        entity_count = prepass_output.entity_count
        segment_length = len(segment_text.split())

        # NOUVEAU Phase 1.8: Détection LOW_QUALITY_NER
        if entity_count < 3 and segment_length > 200:
            logger.info(
                f"[EXTRACTOR:V1.8] LOW_QUALITY_NER detected "
                f"(entities={entity_count}, tokens={segment_length}), routing to SMALL"
            )
            return ExtractionRoute.SMALL

        # Garde routing existant Phase 1
        if entity_count < 3:
            return ExtractionRoute.NO_LLM
        elif entity_count <= 8:
            return ExtractionRoute.SMALL
        else:
            return ExtractionRoute.BIG
```

#### Prompt Structured Triples Extraction

```python
# src/knowbase/semantic/extraction/prompts.py

TRIPLE_EXTRACTION_SYSTEM_PROMPT = """You are a concept and relation extraction expert.

Your task is to extract semantic triples (subject-predicate-object) from text.

# Output Format (JSON)

{
  "concepts": [
    {
      "name": "Canonical concept name",
      "type": "Technology|Product|Standard|Organization|...",
      "definition": "Clear definition in 1-2 sentences",
      "confidence": 0.95,
      "mentions": ["variant1", "variant2"],
      "language": "en"
    }
  ],
  "relations": [
    {
      "subject": "Concept A",
      "predicate": "ENHANCES|DEPENDS_ON|IMPLEMENTS|IS_A|PART_OF|USES|...",
      "object": "Concept B",
      "confidence": 0.90,
      "context": "Text snippet supporting this relation"
    }
  ]
}

# Guidelines

1. **Concepts**: Extract key entities (products, technologies, standards, organizations)
2. **Types**: Use specific types (avoid "Unknown")
3. **Definitions**: Concise, factual (no marketing language)
4. **Relations**: Extract ONLY explicit or strongly implied relations
5. **Confidence**:
   - 0.9-1.0: Explicit statement
   - 0.7-0.9: Strongly implied
   - 0.5-0.7: Weakly implied
6. **Language**: Detect language of concept (en, fr, de, es, etc.)

# Relation Types

- ENHANCES: A improves/strengthens B
- DEPENDS_ON: A requires B to function
- IMPLEMENTS: A realizes/executes B
- IS_A: A is a type/subclass of B
- PART_OF: A is a component of B
- USES: A utilizes B
- RELATES_TO: Generic semantic relation
- PRECEDES: A happens before B
- MITIGATES: A reduces risk of B
"""

TRIPLE_EXTRACTION_USER_PROMPT = """Extract concepts and relations from this text segment.

**Text:**
{segment_text}

**Context:** This segment is from a {document_type} document about {topic}.

Return JSON with "concepts" and "relations" arrays.
"""
```

#### Feature Flag Configuration

```yaml
# config/feature_flags.yaml

phase_1_8:
  # P1: Extraction Concepts Hybrid
  enable_hybrid_extraction:
    enabled: false  # Default OFF, enable per tenant
    description: "LLM structured output for LOW_QUALITY_NER segments"
    cost_impact: "Medium (+67% extraction cost)"
    quality_impact: "High (+15% concept recall)"

  hybrid_extraction_config:
    min_segment_length: 200  # tokens
    max_ner_entities: 3  # threshold for LOW_QUALITY_NER
    llm_timeout: 5  # seconds
    max_cost_per_doc: 0.10  # USD, alert if exceeded
```

---

### 2. Gatekeeper Prefetch Ontology (P2)

#### Prefetch Manager

```python
# src/knowbase/ontology/adaptive_ontology_manager.py

class AdaptiveOntologyManager:
    """
    Phase 1.8: Ajout prefetch intelligent pour document types connus.
    """

    # Mapping document types → ontology domains
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

    def prefetch_for_document_type(
        self,
        document_type: str,
        tenant_id: str,
        ttl_seconds: int = 3600
    ) -> int:
        """
        Précharge ontology entries pour un type de document.

        Workflow:
        1. Map document_type → domain
        2. Query Neo4j CanonicalConcepts du domain
        3. Store dans Redis cache (TTL 1h)
        4. Return count entries loaded

        Args:
            document_type: Type document (ex: "SAP_Product_Doc")
            tenant_id: ID tenant
            ttl_seconds: TTL Redis cache (default: 1h)

        Returns:
            Nombre d'entries préchargées
        """
        domain = self.DOCUMENT_TYPE_TO_DOMAIN.get(document_type)

        if not domain:
            logger.debug(
                f"[ONTOLOGY:Prefetch] No mapping for document_type='{document_type}', skip prefetch"
            )
            return 0

        logger.info(
            f"[ONTOLOGY:Prefetch] Loading domain '{domain}' for document_type '{document_type}'"
        )

        # Query Neo4j pour canonical concepts du domaine
        with self.neo4j_client.driver.session(database="neo4j") as session:
            result = session.run("""
                MATCH (c:CanonicalConcept)
                WHERE c.tenant_id = $tenant_id
                  AND c.metadata.domain = $domain
                RETURN
                    c.canonical_name as canonical_name,
                    c.unified_definition as definition,
                    c.metadata as metadata,
                    c.quality_score as quality_score
            """, tenant_id=tenant_id, domain=domain)

            # Store dans Redis cache
            entries_loaded = 0

            for record in result:
                canonical_name = record["canonical_name"]

                # Structure cache entry
                cache_entry = {
                    "canonical_name": canonical_name,
                    "definition": record["definition"],
                    "metadata": record["metadata"],
                    "quality_score": record["quality_score"],
                    "source": "ontology_prefetch",
                    "confidence": 1.0  # Ontology = ground truth
                }

                # Store dans Redis (key: ontology:{tenant_id}:{canonical_name})
                cache_key = f"ontology:{tenant_id}:{canonical_name.lower()}"

                self.redis_client.setex(
                    cache_key,
                    ttl_seconds,
                    json.dumps(cache_entry)
                )

                entries_loaded += 1

            logger.info(
                f"[ONTOLOGY:Prefetch] ✅ Loaded {entries_loaded} entries for domain '{domain}' "
                f"(TTL={ttl_seconds}s)"
            )

            return entries_loaded
```

#### Intégration Pipeline PPTX

```python
# src/knowbase/ingestion/pipelines/pptx_pipeline.py

def process_pptx(
    pptx_path: Path,
    document_type_id: str | None = None,
    progress_callback=None,
    rq_job=None,
    use_vision: bool = True,
):
    # ... (code existant) ...

    # Ligne 250: Charger context_prompt personnalisé
    document_context_prompt = load_document_type_context(document_type_id)

    # ===== PHASE 1.8: PREFETCH ONTOLOGY =====
    # Précharger ontology entries pour document types connus
    # Réduit LLM calls de ~40% dans Gatekeeper
    if document_type_id:
        try:
            from knowbase.ontology.adaptive_ontology_manager import AdaptiveOntologyManager
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            from knowbase.common.clients.redis_client import get_redis_client

            neo4j_client = get_neo4j_client()
            redis_client = get_redis_client()

            ontology_mgr = AdaptiveOntologyManager(
                neo4j_client=neo4j_client,
                redis_client=redis_client
            )

            entries_loaded = ontology_mgr.prefetch_for_document_type(
                document_type=document_type_id,
                tenant_id="default",
                ttl_seconds=3600  # 1 hour
            )

            logger.info(
                f"[PHASE1.8:Prefetch] ✅ Loaded {entries_loaded} ontology entries "
                f"for document_type '{document_type_id}'"
            )

        except Exception as e:
            logger.warning(
                f"[PHASE1.8:Prefetch] Failed to prefetch ontology: {e}, "
                f"continuing without prefetch"
            )

    # ... (suite du pipeline) ...
```

#### Configuration Feature Flag

```yaml
# config/feature_flags.yaml

phase_1_8:
  # P2: Gatekeeper Prefetch Ontology
  enable_ontology_prefetch:
    enabled: false  # Default OFF, enable per tenant
    description: "Prefetch ontology entries for known document types"
    cost_impact: "Negative (-50% gatekeeper LLM calls)"
    quality_impact: "Neutral (no quality change)"
    performance_impact: "Positive (-3s gatekeeper latency)"

  ontology_prefetch_config:
    cache_ttl_seconds: 3600  # 1 hour
    max_entries_per_domain: 500  # limit Redis memory
    enable_cache_warming: true  # background task
```

---

### 3. Relations LLM Smart Enrichment (P3)

#### Enrichment Logic

```python
# src/knowbase/agents/pattern_miner/pattern_miner.py

class PatternMiner(BaseAgent):
    """Phase 1.8: Ajout LLM enrichment pour relations LOW confidence."""

    async def _enrich_low_confidence_relations(
        self,
        candidate_relations: List[Dict[str, Any]],
        state: AgentState,
        concepts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Enrichit relations LOW confidence (0.4-0.6) via LLM batch.

        Workflow:
        1. Filter zone grise (confidence 0.4-0.6)
        2. Batch LLM processing (50 paires/call)
        3. Merge LLM insights avec pattern matching
        4. Update confidence (weighted average)
        5. Respect budget cap (MAX 20 batches)

        Args:
            candidate_relations: Relations extraites via pattern matching
            state: État global (pour budget cap)
            concepts: Liste concepts pour contexte

        Returns:
            Relations enrichies
        """
        # Feature flag check
        if not self._is_feature_enabled("enable_llm_relation_enrichment", state.tenant_id):
            logger.debug("[PATTERN MINER:V1.8] LLM relation enrichment disabled, skip")
            return candidate_relations

        # Filter zone grise
        low_conf_relations = [
            r for r in candidate_relations
            if 0.4 <= r.get("confidence", 0) <= 0.6
        ]

        if not low_conf_relations:
            logger.debug("[PATTERN MINER:V1.8] No low-confidence relations to enrich")
            return candidate_relations

        # Budget cap check
        max_batches = self.config.get("max_llm_relation_batches", 20)
        current_batches = state.llm_calls_count.get("RELATION_ENRICHMENT", 0)

        if current_batches >= max_batches:
            logger.warning(
                f"[PATTERN MINER:V1.8] Budget cap reached "
                f"({current_batches}/{max_batches} batches), skip enrichment"
            )
            return candidate_relations

        logger.info(
            f"[PATTERN MINER:V1.8] Enriching {len(low_conf_relations)} "
            f"low-confidence relations via LLM (budget: {current_batches}/{max_batches} batches)"
        )

        # Batch processing (50 paires/batch)
        batch_size = 50
        enriched_relations = []
        batches_used = 0

        for i in range(0, len(low_conf_relations), batch_size):
            # Check budget cap AVANT chaque batch
            if current_batches + batches_used >= max_batches:
                logger.warning(
                    f"[PATTERN MINER:V1.8] Budget cap reached mid-processing, "
                    f"skipping remaining {len(low_conf_relations) - i} relations"
                )
                break

            batch = low_conf_relations[i:i+batch_size]

            # Construire prompt batch
            pairs_data = []
            for idx, rel in enumerate(batch, 1):
                source = rel.get("source", "")
                target = rel.get("target", "")

                # Trouver concepts pour contexte
                source_concept = next((c for c in concepts if c.get("name") == source), None)
                target_concept = next((c for c in concepts if c.get("name") == target), None)

                pair_context = {
                    "index": idx,
                    "source": source,
                    "target": target,
                    "source_type": source_concept.get("type") if source_concept else "Unknown",
                    "target_type": target_concept.get("type") if target_concept else "Unknown",
                    "pattern_relation": rel.get("type", "RELATED_TO"),
                    "pattern_confidence": rel.get("confidence", 0.0),
                    "co_occurrence_count": rel.get("co_occurrence_count", 0)
                }

                pairs_data.append(pair_context)

            # Appel LLM batch ASYNC
            try:
                enriched_batch = await self._call_llm_relation_enrichment(
                    pairs_data,
                    state.tenant_id
                )

                # Merge résultats LLM avec relations originales
                for original_rel, llm_result in zip(batch, enriched_batch):
                    # Update avec insights LLM
                    original_rel["llm_relation_type"] = llm_result.get("relation_type")
                    original_rel["llm_confidence"] = llm_result.get("confidence", 0.0)
                    original_rel["llm_reasoning"] = llm_result.get("reasoning", "")

                    # Calculate weighted confidence
                    # Pattern matching: 40%, LLM: 60%
                    pattern_conf = original_rel["confidence"]
                    llm_conf = llm_result.get("confidence", 0.0)
                    original_rel["confidence"] = (pattern_conf * 0.4 + llm_conf * 0.6)

                    # Override relation type si LLM plus confiant
                    if llm_conf > pattern_conf:
                        original_rel["type"] = llm_result.get("relation_type", original_rel["type"])

                    enriched_relations.append(original_rel)

                batches_used += 1

                logger.debug(
                    f"[PATTERN MINER:V1.8] Batch {batches_used} enriched "
                    f"({len(batch)} relations, avg confidence: "
                    f"{sum(r['confidence'] for r in batch) / len(batch):.2f})"
                )

            except Exception as e:
                logger.error(
                    f"[PATTERN MINER:V1.8] LLM enrichment batch failed: {e}, "
                    f"keeping original relations"
                )
                enriched_relations.extend(batch)  # Fallback: keep originals

        # Update state counters
        state.llm_calls_count["RELATION_ENRICHMENT"] = current_batches + batches_used

        # Merge avec relations high confidence (inchangées)
        high_conf_relations = [
            r for r in candidate_relations
            if r.get("confidence", 0) > 0.6
        ]

        final_relations = high_conf_relations + enriched_relations

        logger.info(
            f"[PATTERN MINER:V1.8] ✅ Enrichment complete: "
            f"{len(enriched_relations)} enriched, {len(high_conf_relations)} high-conf unchanged, "
            f"{batches_used} batches used"
        )

        return final_relations

    async def _call_llm_relation_enrichment(
        self,
        pairs_data: List[Dict[str, Any]],
        tenant_id: str
    ) -> List[Dict[str, Any]]:
        """
        Appel LLM batch pour enrichissement relations.

        Args:
            pairs_data: Liste de paires concepts avec contexte
            tenant_id: ID tenant pour injection contexte métier

        Returns:
            Liste résultats LLM (même ordre que pairs_data)
        """
        # Construire prompt batch
        pairs_text = []
        for pair in pairs_data:
            pair_line = (
                f"{pair['index']}. {pair['source']} ({pair['source_type']}) → "
                f"{pair['target']} ({pair['target_type']}) | "
                f"Pattern: {pair['pattern_relation']} (conf={pair['pattern_confidence']:.2f})"
            )
            pairs_text.append(pair_line)

        prompt = f"""Analyze these concept pairs and determine semantic relations.

For each pair, output:
- relation_type: Specific relation (ENHANCES, DEPENDS_ON, IMPLEMENTS, IS_A, PART_OF, USES, MITIGATES, PRECEDES, etc.)
- confidence: 0.0-1.0 (based on semantic strength)
- reasoning: Brief explanation

**Concept Pairs:**
{chr(10).join(pairs_text)}

**Output JSON:**
{{
  "relations": [
    {{
      "pair_index": 1,
      "relation_type": "ENHANCES",
      "confidence": 0.85,
      "reasoning": "Multi-Factor Authentication strengthens security by adding layer"
    }},
    ...
  ]
}}

IMPORTANT: Return results in SAME ORDER as input (1-{len(pairs_data)}).
"""

        from knowbase.common.llm_router import TaskType

        # Injection contexte métier (Phase 2)
        system_prompt = RELATION_ENRICHMENT_SYSTEM_PROMPT
        if self.context_injector:
            system_prompt = self.context_injector.inject_context(
                system_prompt,
                tenant_id
            )

        # Appel LLM async
        response_content = await self.llm_router.acomplete(
            task_type=TaskType.RELATION_EXTRACTION,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=4000,
            response_format={"type": "json_object"}
        )

        # Parse résultat
        result_json = json.loads(response_content.strip())
        return result_json.get("relations", [])


# Prompt système
RELATION_ENRICHMENT_SYSTEM_PROMPT = """You are a semantic relation analysis expert.

Your task is to analyze concept pairs and determine precise semantic relations.

# Relation Types

- **ENHANCES**: A improves/strengthens B (ex: MFA enhances Security)
- **DEPENDS_ON**: A requires B to function (ex: API depends on Authentication)
- **IMPLEMENTS**: A realizes/executes B (ex: SAST implements Security Testing)
- **IS_A**: A is a type/subclass of B (ex: iPhone is a Smartphone)
- **PART_OF**: A is a component of B (ex: CPU part of Computer)
- **USES**: A utilizes B (ex: Application uses Database)
- **MITIGATES**: A reduces risk of B (ex: Firewall mitigates DDoS)
- **PRECEDES**: A happens before B (ex: Authentication precedes Authorization)
- **RELATES_TO**: Generic semantic relation (use only if above don't fit)

# Confidence Scoring

- **0.9-1.0**: Explicit, undeniable relation
- **0.7-0.9**: Strong implication, very likely
- **0.5-0.7**: Moderate implication, possible
- **0.3-0.5**: Weak implication, uncertain
- **0.0-0.3**: No clear relation

# Guidelines

1. Use SPECIFIC relation types (avoid RELATES_TO unless necessary)
2. Base confidence on semantic strength, not just co-occurrence
3. Consider concept types when selecting relation
4. Provide concise reasoning (1 sentence)
"""
```

#### Budget Cap Configuration

```python
# src/knowbase/agents/supervisor/supervisor.py

class SupervisorAgent:
    """Phase 1.8: Ajout budget cap pour relations enrichment."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        # Phase 1.8: Budget caps
        self.budget_caps = {
            "SMALL": config.get("budget_small", 120),
            "BIG": config.get("budget_big", 8),
            "VISION": config.get("budget_vision", 2),
            "RELATION_ENRICHMENT": config.get("budget_relation_enrichment", 20)  # NOUVEAU
        }

        logger.info(
            f"[SUPERVISOR:V1.8] Budget caps initialized: "
            f"SMALL={self.budget_caps['SMALL']}, "
            f"BIG={self.budget_caps['BIG']}, "
            f"VISION={self.budget_caps['VISION']}, "
            f"RELATION_ENRICHMENT={self.budget_caps['RELATION_ENRICHMENT']}"
        )
```

#### Feature Flag Configuration

```yaml
# config/feature_flags.yaml

phase_1_8:
  # P3: Relations LLM Smart Enrichment
  enable_llm_relation_enrichment:
    enabled: false  # Default OFF, enable per tenant
    description: "LLM batch enrichment for low-confidence relations (0.4-0.6)"
    cost_impact: "High (+700% relation extraction cost)"
    quality_impact: "Very High (+20% precision, +20% recall)"

  llm_relation_enrichment_config:
    confidence_min: 0.4  # zone grise start
    confidence_max: 0.6  # zone grise end
    batch_size: 50  # paires/batch
    max_batches_per_doc: 20  # budget cap
    llm_timeout: 10  # seconds
    weight_pattern: 0.4  # pattern matching weight
    weight_llm: 0.6  # LLM weight
```

---

## 📊 Tracking & Metrics Dashboard

### Métriques à Surveiller (Grafana/Loki)

```yaml
# monitoring/dashboards/phase_1_8_metrics.yaml

phase_1_8_dashboard:
  panels:
    # Panel 1: Extraction Concepts
    - title: "Concepts Recall & Precision"
      metrics:
        - concepts_recall_baseline: 70%
        - concepts_recall_current: gauge
        - concepts_precision_baseline: 85%
        - concepts_precision_current: gauge
      alerts:
        - recall_drop: "< 75% for 5 consecutive docs"
        - precision_drop: "< 80% for 5 consecutive docs"

    # Panel 2: Cost Tracking
    - title: "Cost per Document"
      metrics:
        - cost_baseline: $0.03
        - cost_current: gauge
        - cost_budget: $0.14
        - cost_alert_threshold: $0.20
      alerts:
        - cost_exceeded: "> $0.20/doc"

    # Panel 3: Latency
    - title: "Pipeline Latency"
      metrics:
        - extraction_latency_baseline: 15s
        - extraction_latency_current: gauge
        - gatekeeper_latency_baseline: 28s
        - gatekeeper_latency_current: gauge
      alerts:
        - latency_exceeded: "> 60s total"

    # Panel 4: LLM Calls
    - title: "LLM Calls per Document"
      metrics:
        - llm_calls_baseline: 25
        - llm_calls_current: gauge
        - llm_calls_target: 20
        - ontology_cache_hit_rate: gauge (target: 70%)
      alerts:
        - llm_calls_exceeded: "> 40/doc"

    # Panel 5: Relations Quality
    - title: "Relations Precision & Recall"
      metrics:
        - relations_precision_baseline: 60%
        - relations_precision_current: gauge
        - relations_recall_baseline: 50%
        - relations_recall_current: gauge
      alerts:
        - relations_quality_drop: "< baseline for 10 docs"

    # Panel 6: Feature Flags Status
    - title: "Feature Flags (Phase 1.8)"
      toggles:
        - enable_hybrid_extraction: boolean
        - enable_ontology_prefetch: boolean
        - enable_llm_relation_enrichment: boolean
```

### Logs Structurés

```python
# src/knowbase/common/logging.py

def log_phase_1_8_metrics(
    document_id: str,
    tenant_id: str,
    metrics: Dict[str, Any]
):
    """
    Log métriques Phase 1.8 pour monitoring Grafana/Loki.

    Format JSON structuré pour parsing facile.
    """
    logger.info(
        "[PHASE1.8:METRICS]",
        extra={
            "document_id": document_id,
            "tenant_id": tenant_id,
            "phase": "1.8",
            "metrics": {
                # Extraction
                "concepts_extracted": metrics.get("concepts_count", 0),
                "concepts_recall": metrics.get("concepts_recall", 0.0),
                "concepts_precision": metrics.get("concepts_precision", 0.0),
                "extraction_latency_s": metrics.get("extraction_latency", 0.0),

                # Gatekeeper
                "llm_calls_gatekeeper": metrics.get("llm_calls_gatekeeper", 0),
                "ontology_cache_hits": metrics.get("ontology_cache_hits", 0),
                "ontology_cache_misses": metrics.get("ontology_cache_misses", 0),
                "gatekeeper_latency_s": metrics.get("gatekeeper_latency", 0.0),

                # Relations
                "relations_extracted": metrics.get("relations_count", 0),
                "relations_enriched_llm": metrics.get("relations_enriched", 0),
                "relations_precision": metrics.get("relations_precision", 0.0),
                "relations_recall": metrics.get("relations_recall", 0.0),

                # Cost
                "cost_extraction_usd": metrics.get("cost_extraction", 0.0),
                "cost_gatekeeper_usd": metrics.get("cost_gatekeeper", 0.0),
                "cost_relations_usd": metrics.get("cost_relations", 0.0),
                "cost_total_usd": metrics.get("cost_total", 0.0),

                # Feature flags
                "feature_hybrid_extraction": metrics.get("feature_hybrid_extraction", False),
                "feature_ontology_prefetch": metrics.get("feature_ontology_prefetch", False),
                "feature_llm_relation_enrichment": metrics.get("feature_llm_relation_enrichment", False),
            }
        }
    )
```

---

## 🧪 Tests & Validation

### Test Plan Sprint 1.8.1 (P1)

```python
# tests/phase_1_8/test_hybrid_extraction.py

import pytest
from knowbase.agents.extractor.orchestrator import ExtractorOrchestrator
from knowbase.agents.base import AgentState

class TestHybridExtraction:
    """Tests pour extraction concepts hybrid Phase 1.8."""

    def test_low_quality_ner_routing(self):
        """Test routing LOW_QUALITY_NER → SMALL."""
        orchestrator = ExtractorOrchestrator()

        # Segment avec peu d'entities NER mais long texte
        segment_text = "Lorem ipsum " * 100  # 200 tokens
        prepass_output = PrepassAnalyzerOutput(
            entity_count=2,  # < 3
            entity_density=0.01,
            recommended_route="NO_LLM"
        )

        route = orchestrator._select_extraction_route_v18(
            prepass_output,
            segment_text,
            state=AgentState()
        )

        assert route == ExtractionRoute.SMALL  # Should trigger LLM

    @pytest.mark.asyncio
    async def test_hybrid_extraction_quality(self):
        """Test qualité extraction hybrid vs baseline."""
        # TODO: Implémenter test A/B sur 50 documents
        # Mesurer: rappel concepts avant/après
        pass

    @pytest.mark.asyncio
    async def test_hybrid_extraction_cost(self):
        """Test coût extraction hybrid vs budget."""
        # TODO: Vérifier coût < $0.10/doc
        pass
```

### Test Plan Sprint 1.8.2 (P2)

```python
# tests/phase_1_8/test_ontology_prefetch.py

import pytest
from knowbase.ontology.adaptive_ontology_manager import AdaptiveOntologyManager

class TestOntologyPrefetch:
    """Tests pour prefetch ontology Phase 1.8."""

    def test_prefetch_sap_products(self):
        """Test prefetch pour document type SAP."""
        ontology_mgr = AdaptiveOntologyManager(...)

        entries_loaded = ontology_mgr.prefetch_for_document_type(
            document_type="SAP_Product_Doc",
            tenant_id="default"
        )

        assert entries_loaded > 0  # Devrait charger entries SAP

    def test_cache_hit_improvement(self):
        """Test amélioration cache hit rate."""
        # TODO: Mesurer cache hit rate avant/après prefetch
        # Target: 50% → 70%
        pass

    def test_redis_memory_limit(self):
        """Test que prefetch respecte limite mémoire Redis."""
        # TODO: Vérifier max 500 entries/domain
        pass
```

### Test Plan Sprint 1.8.3 (P3)

```python
# tests/phase_1_8/test_relation_enrichment.py

import pytest
from knowbase.agents.pattern_miner.pattern_miner import PatternMiner

class TestRelationEnrichment:
    """Tests pour LLM relation enrichment Phase 1.8."""

    @pytest.mark.asyncio
    async def test_low_confidence_enrichment(self):
        """Test enrichissement relations LOW confidence."""
        pattern_miner = PatternMiner()

        # Relations zone grise (0.4-0.6)
        candidate_relations = [
            {"source": "MFA", "target": "Security", "confidence": 0.55, "type": "RELATED_TO"}
        ]

        enriched = await pattern_miner._enrich_low_confidence_relations(
            candidate_relations,
            state=AgentState(),
            concepts=[...]
        )

        # Vérifier confidence améliorée
        assert enriched[0]["confidence"] > 0.55
        # Vérifier relation type plus spécifique
        assert enriched[0]["type"] != "RELATED_TO"

    @pytest.mark.asyncio
    async def test_budget_cap_respected(self):
        """Test respect budget cap (20 batches max)."""
        # TODO: Simuler document avec 2000 relations zone grise
        # Vérifier que seuls 20 batches (1000 paires) sont traités
        pass

    def test_relation_quality_improvement(self):
        """Test amélioration qualité relations."""
        # TODO: Mesurer précision/rappel avant/après sur 100 docs
        # Target: Précision 60% → 80%, Rappel 50% → 70%
        pass
```

---

## 📅 Timeline & Milestones

### Semaine 11-12 : Sprint 1.8.1 (P1 - Extraction Hybrid)

**Jour 1-2 :** Implémentation routing + prompt
- Modifier `ExtractorOrchestrator._select_extraction_route_v18()`
- Créer `TRIPLE_EXTRACTION_SYSTEM_PROMPT`
- Tests unitaires routing

**Jour 3-4 :** Tests A/B qualité
- Sélectionner 50 documents test
- Mesurer rappel/précision baseline
- Activer feature flag sur 50 docs
- Comparer métriques

**Jour 5 :** Dashboard + déploiement
- Configurer Grafana panel extraction
- Alertes coût > $0.10/doc
- Déploiement production (flag OFF)

**Milestone M1.8.1 :** ✅ Hybrid extraction testée, prête pour rollout progressif

---

### Semaine 13-14 : Sprint 1.8.2 (P2 - Gatekeeper Prefetch)

**Jour 1-2 :** Implémentation prefetch
- `AdaptiveOntologyManager.prefetch_for_document_type()`
- Mapping document types → domains
- Tests unitaires prefetch

**Jour 3 :** Intégration pipeline
- Modifier `pptx_pipeline.py:250`
- Redis cache warming
- Tests intégration

**Jour 4-5 :** Validation cache hit rate
- Mesurer avant/après sur 100 docs
- Optimiser TTL si nécessaire
- Dashboard Grafana cache metrics

**Milestone M1.8.2 :** ✅ Ontology prefetch actif, cache hit rate > 65%

---

### Semaine 15-17 : Sprint 1.8.3 (P3 - Relations Enrichment)

**Jour 1-3 :** Implémentation enrichment
- `PatternMiner._enrich_low_confidence_relations()`
- `TaskType.RELATION_EXTRACTION`
- Budget cap dans SupervisorAgent
- Tests unitaires

**Jour 4-5 :** Tests qualité
- Mesurer précision/rappel relations sur 20 docs
- Human-in-the-loop validation (sample 10%)
- Ajustement prompts si besoin

**Jour 6-7 :** Dashboard + déploiement
- Grafana panel relations
- Alertes budget cap
- Documentation Human review process
- Déploiement production (flag OFF)

**Milestone M1.8.3 :** ✅ Relations enrichment testée, qualité validée

---

## 🎯 Success Criteria Phase 1.8

### Critères Objectifs (Mesurables)

| Métrique | Baseline (Phase 1) | Target Phase 1.8 | Status |
|----------|-------------------|------------------|--------|
| **Rappel concepts** | 70% | 85% (+ 15 pts) | 🟡 À valider |
| **Précision concepts** | 85% | 90% (+ 5 pts) | 🟡 À valider |
| **Rappel relations** | 50% | 70% (+ 20 pts) | 🟡 À valider |
| **Précision relations** | 60% | 80% (+ 20 pts) | 🟡 À valider |
| **Coût/doc** | $0.03 | ≤ $0.14 (+ 367%) | 🟡 À mesurer |
| **Latence extraction** | 15s | ≤ 18s (+ 20%) | 🟡 À mesurer |
| **Latence gatekeeper** | 28s | ≤ 25s (- 11%) | 🟡 À mesurer |
| **LLM calls/doc** | 25 | ≤ 20 (- 20%) | 🟡 À mesurer |
| **Cache hit rate** | 50% | ≥ 70% (+ 20 pts) | 🟡 À mesurer |

### Critères Qualitatifs

✅ **USP Preserved:** Dual-Graph + Gatekeeper + Ontology Learning reste unique
✅ **No Copilot Clone:** Architecture différenciée maintenue
✅ **Budget Controlled:** Alertes coût actives, budget caps respectés
✅ **Progressive Rollout:** Feature flags permettent activation par tenant
✅ **Monitoring Active:** Dashboard Grafana opérationnel

---

## 🚨 Risques & Mitigations

### Risque 1 : Explosion Coût
**Probabilité:** Moyenne
**Impact:** Élevé
**Mitigation:**
- Budget caps stricts (code + monitoring)
- Alertes coût > $0.20/doc
- Feature flags permettent rollback immédiat
- Tests coût sur 100 docs AVANT rollout prod

### Risque 2 : Latence LLM
**Probabilité:** Moyenne
**Impact:** Moyen
**Mitigation:**
- Async parallel batching (5 concurrent)
- Circuit breaker (timeout 10s)
- Fallback graceful si timeout
- Monitoring latence P95/P99

### Risque 3 : Hallucinations LLM
**Probabilité:** Élevée
**Impact:** Moyen
**Mitigation:**
- Gatekeeper filters (confidence threshold)
- Human-in-the-loop validation (10% sample)
- Feedback loop améliore prompts
- Logging décisions LLM (audit trail)

### Risque 4 : Cache Stale (Ontology)
**Probabilité:** Faible
**Impact:** Faible
**Mitigation:**
- TTL court (1h)
- Invalidation proactive sur ontology update
- Monitoring cache freshness

### Risque 5 : Feature Interference
**Probabilité:** Faible
**Impact:** Moyen
**Mitigation:**
- Tests intégration AVANT chaque sprint
- Feature flags isolent composants
- Rollback procédure documentée

---

## 📝 Checklist Déploiement

### Avant Sprint 1.8.1 (P1)
- [ ] Feature flag `enable_hybrid_extraction` créé en config
- [ ] Dashboard Grafana panel extraction configuré
- [ ] Sélectionner 50 documents test pour A/B
- [ ] Baseline metrics mesurées (rappel/précision concepts)

### Avant Sprint 1.8.2 (P2)
- [ ] Feature flag `enable_ontology_prefetch` créé
- [ ] Mapping document types → domains complété
- [ ] Redis cache configuré (TTL, memory limits)
- [ ] Dashboard cache hit rate configuré

### Avant Sprint 1.8.3 (P3)
- [ ] Feature flag `enable_llm_relation_enrichment` créé
- [ ] Budget cap RELATION_ENRICHMENT configuré (20 batches)
- [ ] Prompt RELATION_ENRICHMENT_SYSTEM_PROMPT validé
- [ ] Process Human-in-the-loop documenté

### Après Phase 1.8 Complète
- [ ] Tous les success criteria validés
- [ ] Documentation utilisateur mise à jour
- [ ] Runbook opérationnel créé
- [ ] Démo client préparée
- [ ] Migration guide Phase 2 écrit

---

## 🔗 Liens Documentation

- **Phase 1 V2.1 COMPLETE:** `doc/phases/PHASE1_SEMANTIC_CORE.md`
- **Phase 2 (en cours):** `doc/phases/PHASE2_INTELLIGENCE_AVANCEE.md`
- **Analyse HELIOS:** Session 2025-11-19
- **Feature Flags:** `config/feature_flags.yaml`
- **Monitoring:** `monitoring/dashboards/phase_1_8_metrics.yaml`

---

## 📞 Contacts & Support

**Phase Owner:** [Votre nom]
**Tech Lead:** [Tech lead]
**Slack Channel:** #phase-1-8-llm-hybrid
**Stand-up:** Lundi/Mercredi/Vendredi 10h

---

**🌊 OSMOSE Phase 1.8 — Intelligence Hybride LLM sans compromis USP**

*Dernière mise à jour: 2025-11-19 par HELIOS*
