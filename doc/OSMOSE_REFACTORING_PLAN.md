# Plan de Refactoring - Architecture Actuelle vers Semantic Intelligence

**Version:** 1.0
**Date:** 2025-10-13
**Objectif:** Planification détaillée du refactoring de l'existant pour intégrer Semantic Intelligence

---

## Table des Matières

1. [État des Lieux Architecture Actuelle](#1-état-des-lieux-architecture-actuelle)
2. [Matrice Supprimer/Modifier/Créer](#2-matrice-supprimermodifiercréer)
3. [Plan de Migration par Phase](#3-plan-de-migration-par-phase)
4. [Stratégie de Compatibilité](#4-stratégie-de-compatibilité)
5. [Risks et Mitigations](#5-risks-et-mitigations)
6. [Checkpoints Validation](#6-checkpoints-validation)

---

## 1. État des Lieux Architecture Actuelle

### 1.1 Code Existant (Inventaire)

```
📦 Architecture Actuelle (v0.9.0-pre-pivot)
├── src/knowbase/
│   ├── ingestion/
│   │   ├── pipelines/
│   │   │   ├── pdf_pipeline.py (835 lignes) ⚠️ MODIFIER MAJEUR
│   │   │   ├── pptx_pipeline.py (~700 lignes) ⚠️ MODIFIER MAJEUR
│   │   │   └── excel_pipeline.py ✅ CONSERVER
│   │   └── queue/
│   │       ├── dispatcher.py ✅ CONSERVER
│   │       ├── worker.py (70 lignes) 🟡 MODIFIER MINEUR
│   │       └── jobs.py ✅ CONSERVER
│   │
│   ├── db/
│   │   └── models.py ⚠️ MODIFIER MAJEUR
│   │       ├── DocumentType (lignes 220-334) → MIGRER vers ExtractionProfile
│   │       ├── EntityTypeRegistry → ÉTENDRE pour Living Ontology
│   │       └── ImportHistoryRedis ✅ CONSERVER
│   │
│   ├── api/
│   │   ├── services/
│   │   │   ├── document_type_service.py ⚠️ MODIFIER MAJEUR
│   │   │   ├── entity_type_registry_service.py ⚠️ MODIFIER MAJEUR
│   │   │   ├── knowledge_graph_service.py ⚠️ MODIFIER MAJEUR
│   │   │   ├── ingestion.py (300+ lignes) ⚠️ MODIFIER MAJEUR
│   │   │   └── [autres services] ✅ CONSERVER
│   │   │
│   │   └── routers/
│   │       ├── ingest.py ⚠️ MODIFIER
│   │       ├── entity_types.py ⚠️ MODIFIER
│   │       └── [autres routers] 🟡 MODIFIER MINEUR
│   │
│   └── common/
│       ├── clients.py ✅ CONSERVER
│       ├── llm_router.py 🟡 MODIFIER MINEUR (métriques)
│       └── entity_normalizer.py ✅ CONSERVER
│
└── frontend/src/
    ├── app/
    │   ├── admin/
    │   │   ├── document-types/ ⚠️ MODIFIER/RENOMMER
    │   │   └── dynamic-types/ ⚠️ MODIFIER MAJEUR (Quality Control UI)
    │   └── api/ 🟡 MODIFIER (nouvelles routes)
    │
    └── components/
        └── ui/ 🟢 CRÉER NOUVEAUX (Mantine dashboards)
```

### 1.2 Problèmes Identifiés Architecture Actuelle

| Problème | Impact | Solution Pivot |
|----------|--------|----------------|
| **Extraction segment-par-segment indépendants** | Perte contexte narratif | Intelligent Clustering avec narrative threads |
| **Pas de gatekeeper intelligent** | Qualité données variable | Semantic Gatekeeper multi-critères |
| **Stockage unique (pas de staging)** | Pas de rollback, tout ou rien | Dual-Graph Proto/Published |
| **Volumétrie non maîtrisée** | Croissance illimitée (592 → 10k entities) | Lifecycle HOT/WARM/COLD/FROZEN |
| **Ontologie statique** | Nécessite intervention manuelle | Living Ontology pattern discovery |
| **Relations génériques** | 47 relation types fragmentés | Semantic validation + standardisation |
| **36% entités orphelines** | Graphe peu connecté | Narrative threads + causal chains |
| **Coût LLM non optimisé** | Budget uniforme, pas adaptatif | Budget Intelligence par complexité |

---

## 2. Matrice Supprimer/Modifier/Créer

### 2.1 SUPPRIMER (Code Obsolète)

| Fichier/Fonction | Raison Suppression | Remplacement |
|------------------|-------------------|--------------|
| ❌ Aucune suppression complète | Architecture actuelle reste base | Extension plutôt que remplacement |

**Justification** : On ne supprime RIEN, on ÉTEND. L'architecture actuelle devient "legacy mode" disponible en fallback.

### 2.2 MODIFIER (Refactoring Majeur)

#### 2.2.1 Backend Python

**src/knowbase/ingestion/pipelines/pdf_pipeline.py**

```python
# AVANT (v0.9.0)
async def process_pdf(file_path, use_vision=False):
    """
    Traitement PDF segment-par-segment.
    Pas de contexte narratif.
    """
    if use_vision:
        # Vision mode
        for page in pages:
            result = await ask_gpt_slide_analysis(page)
            await store_extraction(result)
    else:
        # Text-only mode
        for block in megaparse_blocks:
            result = await ask_gpt_block_analysis_text_only(block)
            await store_extraction(result)

# APRÈS (Semantic Intelligence)
async def process_pdf_semantic(file_path, use_vision=False):
    """
    Traitement PDF avec Semantic Intelligence.

    Flow:
    1. Semantic Document Profiling (nouveau)
    2. Intelligent Segmentation (nouveau)
    3. Extraction with narrative context (modifié)
    4. Stage to Proto-KG (nouveau)
    5. Gatekeeper evaluation (nouveau)
    """
    # 1. Semantic Profiling
    document_intelligence = await semantic_profiler.analyze_document(file_path)

    # 2. Intelligent Segmentation
    if use_vision:
        base_segments = await extract_pages(file_path)
    else:
        base_segments = await megaparse_extract(file_path)

    intelligent_clusters = await segmentation_engine.create_intelligent_clusters(
        document_intelligence,
        base_segments
    )

    # 3. Extraction with context
    for cluster in intelligent_clusters:
        extraction = await extract_with_semantic_context(
            cluster,
            document_intelligence
        )

        # 4. Stage to Proto-KG
        await stage_to_proto_storage(extraction)

    # 5. Gatekeeper evaluation
    await gatekeeper.evaluate_all_candidates(document_id)

    return ProcessingResult(
        document_id=document_id,
        entities_staged=...,
        auto_promoted_count=...,
        human_review_count=...
    )
```

**Modifications Concrètes** :

```diff
# pdf_pipeline.py

+ from knowbase.semantic.profiler import SemanticDocumentProfiler
+ from knowbase.semantic.segmentation import IntelligentSegmentationEngine
+ from knowbase.semantic.extraction import DualStorageExtractor
+ from knowbase.semantic.gatekeeper import SemanticIntelligentGatekeeper

  async def process_pdf(
      file_path: str,
      document_type_id: Optional[str],
      use_vision: bool = False,
+     extraction_mode: str = "SEMANTIC"  # NEW: SEMANTIC | LEGACY
  ):
+     # NEW: Semantic Intelligence mode
+     if extraction_mode == "SEMANTIC":
+         return await process_pdf_semantic(file_path, document_type_id, use_vision)
+
+     # LEGACY: Keep old pipeline for fallback
+     else:
+         return await process_pdf_legacy(file_path, document_type_id, use_vision)

+ async def process_pdf_semantic(file_path, document_type_id, use_vision):
+     """New Semantic Intelligence pipeline"""
+     profiler = SemanticDocumentProfiler(llm_client, config)
+     segmentation = IntelligentSegmentationEngine(config)
+     extractor = DualStorageExtractor(neo4j, qdrant, llm_client)
+     gatekeeper = SemanticIntelligentGatekeeper(llm_client, config)
+
+     # 1. Profile
+     doc_intelligence = await profiler.analyze_document(file_path)
+
+     # 2. Segment
+     base_segments = await _extract_base_segments(file_path, use_vision)
+     clusters = await segmentation.create_intelligent_clusters(
+         doc_intelligence, base_segments
+     )
+
+     # 3. Extract
+     for cluster in clusters:
+         extraction = await extractor.extract_with_narrative_context(cluster)
+         await extractor.stage_to_proto(extraction)
+
+     # 4. Evaluate
+     promotion_results = await gatekeeper.evaluate_all_candidates(file_path)
+
+     return ProcessingResult(
+         semantic_intelligence=doc_intelligence,
+         candidates_staged=len(clusters),
+         auto_promoted=promotion_results.promoted_count,
+         needs_review=promotion_results.review_count
+     )

+ # Rename old function
+ async def process_pdf_legacy(file_path, document_type_id, use_vision):
+     """Legacy pipeline (kept for fallback)"""
      # ... code actuel inchangé ...
```

**src/knowbase/db/models.py**

```diff
# models.py

+ # NEW: ExtractionProfile (remplace usage DocumentType)
+ class ExtractionProfile(Base):
+     """
+     Profile d'extraction pour guider Semantic Intelligence.
+     Remplace/complète DocumentType.
+     """
+     __tablename__ = "extraction_profiles"
+
+     id = Column(String(36), primary_key=True)
+     name = Column(String(100), nullable=False)
+     domain = Column(String(50))  # technical, business, regulatory, research
+     expected_complexity = Column(String(20))  # low, medium, high, very_high
+     expected_entity_types = Column(JSON)  # Liste types attendus
+     context_prompt = Column(Text)  # Prompt contextuel
+     budget_multiplier = Column(Float, default=1.0)  # Multiplicateur budget
+
+ # NEW: ProtoEntity (staging)
+ # Note: En fait stocké dans Neo4j, mais metadata SQLite pour tracking
+ class ProtoEntityMetadata(Base):
+     """Metadata des entities en Proto-KG (pour tracking)"""
+     __tablename__ = "proto_entity_metadata"
+
+     entity_uuid = Column(String(36), primary_key=True)
+     tenant_id = Column(String(36), nullable=False)
+     stage = Column(String(20))  # PROTO, PROMOTED, REJECTED
+     tier = Column(String(20))  # HOT, WARM, COLD, FROZEN
+     created_at = Column(DateTime)
+     promoted_at = Column(DateTime, nullable=True)
+     gatekeeper_score = Column(Float)
+
+ # MODIFY: EntityTypeRegistry (étendre pour Living Ontology)
  class EntityTypeRegistry(Base):
      __tablename__ = "entity_type_registry"

      id = Column(String(36), primary_key=True)
      tenant_id = Column(String(36), nullable=False)
      type_name = Column(String(100), nullable=False)
      status = Column(String(20))  # pending, approved, rejected
      created_at = Column(DateTime)

+     # NEW: Living Ontology fields
+     discovery_method = Column(String(50))  # MANUAL, LLM_DISCOVERED, PATTERN_MINED
+     pattern_support_count = Column(Integer, default=0)  # Combien de fois pattern observé
+     semantic_validation_score = Column(Float)  # Score validation LLM
+     trial_mode = Column(Boolean, default=False)  # En test K occurrences
+     trial_start_date = Column(DateTime, nullable=True)
+     trial_max_occurrences = Column(Integer, default=50)
+
+     parent_type = Column(String(100), nullable=True)  # Hiérarchie ontologie
+     related_types = Column(JSON)  # Types sémantiquement proches
```

**src/knowbase/api/services/ingestion.py**

```diff
# services/ingestion.py

  async def ingest_document(
      file_path: str,
      document_type_id: Optional[str],
-     use_vision: bool = False
+     use_vision: bool = False,
+     extraction_mode: str = "SEMANTIC"  # NEW
  ):
      """Service d'ingestion principal"""

+     # NEW: Choose pipeline
+     if extraction_mode == "SEMANTIC":
+         result = await pdf_pipeline.process_pdf_semantic(
+             file_path, document_type_id, use_vision
+         )
+     else:
+         result = await pdf_pipeline.process_pdf_legacy(
+             file_path, document_type_id, use_vision
+         )

-     # OLD: Direct storage
-     await neo4j_service.store_entities(result.entities)
-     await qdrant_service.store_concepts(result.concepts)

+     # NEW: Result already in Proto-KG, just return stats
      return {
          "status": "success",
          "document_id": result.document_id,
+         "extraction_mode": extraction_mode,
+         "semantic_intelligence": result.semantic_intelligence,
          "entities_extracted": result.entities_staged,
+         "auto_promoted": result.auto_promoted,
+         "needs_human_review": result.needs_review
      }
```

**src/knowbase/api/services/knowledge_graph_service.py**

```diff
# knowledge_graph_service.py

+ # NEW: Dual-graph orchestration
+ class KnowledgeGraphService:
+     def __init__(self):
+         self.neo4j_proto = Neo4jProtoManager(...)
+         self.neo4j_published = Neo4jPublishedManager(...)
+         self.qdrant_proto = QdrantProtoManager(...)
+         self.qdrant_published = QdrantPublishedManager(...)
+
+     async def get_entity(self, entity_uuid: str, include_proto: bool = False):
+         """
+         Récupère entity depuis Published-KG.
+         Si include_proto=True, aussi Proto-KG.
+         """
+         # Chercher dans Published d'abord
+         entity = await self.neo4j_published.get_entity(entity_uuid)
+
+         if not entity and include_proto:
+             entity = await self.neo4j_proto.get_entity(entity_uuid)
+
+         return entity
+
+     async def promote_candidate(self, entity_uuid: str, force: bool = False):
+         """
+         Promote entity de Proto vers Published.
+         """
+         # Récupérer candidate
+         candidate = await self.neo4j_proto.get_entity(entity_uuid)
+
+         if not force:
+             # Vérifier score gatekeeper
+             decision = await gatekeeper.evaluate_for_promotion(candidate)
+             if decision.action != PromotionAction.PROMOTE:
+                 raise ValueError(f"Candidate doesn't meet promotion criteria")
+
+         # Promote
+         await self.neo4j_proto.promote_entity_to_published(
+             entity_uuid,
+             decision.to_dict()
+         )
+
+         return {"status": "promoted", "entity_uuid": entity_uuid}
```

#### 2.2.2 Frontend Next.js/React

**frontend/src/app/admin/document-types/ → extraction-profiles/**

```diff
# Renommer dossier
- app/admin/document-types/
+ app/admin/extraction-profiles/

# page.tsx (liste)
  export default function ExtractionProfilesPage() {
      const { data: profiles } = useQuery(['extraction-profiles'], fetchProfiles)

      return (
          <VStack>
              <Heading>Extraction Profiles</Heading>
+             <Text color="gray.600">
+                 Configure semantic extraction profiles for different document domains
+             </Text>

              <Table>
                  <Thead>
                      <Tr>
                          <Th>Name</Th>
+                         <Th>Domain</Th>
+                         <Th>Expected Complexity</Th>
+                         <Th>Budget Multiplier</Th>
                          <Th>Actions</Th>
                      </Tr>
                  </Thead>
                  <Tbody>
                      {profiles?.map(profile => (
                          <Tr key={profile.id}>
                              <Td>{profile.name}</Td>
+                             <Td><Badge>{profile.domain}</Badge></Td>
+                             <Td><Badge>{profile.expected_complexity}</Badge></Td>
+                             <Td>{profile.budget_multiplier}x</Td>
                              <Td>
                                  <Button size="sm" as={Link} href={`/admin/extraction-profiles/${profile.id}`}>
                                      Edit
                                  </Button>
                              </Td>
                          </Tr>
                      ))}
                  </Tbody>
              </Table>
          </VStack>
      )
  }
```

**NEW: app/admin/quality-control/page.tsx**

```tsx
// NOUVEAU COMPOSANT: Quality Control Dashboard

import { DataTable } from '@/components/ui/DataTable'  // Nouveau
import { useQuery } from '@tanstack/react-query'

export default function QualityControlPage() {
    const { data: pendingCandidates } = useQuery(
        ['pending-candidates'],
        () => fetch('/api/gatekeeper/pending').then(r => r.json()),
        { refetchInterval: 10000 }  // Auto-refresh 10s
    )

    const handleBulkPromote = async (selectedIds: string[]) => {
        await fetch('/api/gatekeeper/promote-bulk', {
            method: 'POST',
            body: JSON.stringify({ candidate_ids: selectedIds })
        })
    }

    return (
        <VStack spacing={8}>
            <Heading>Semantic Quality Control</Heading>

            <SimpleGrid columns={3} gap={6}>
                <StatCard
                    label="Pending Review"
                    value={pendingCandidates?.review_count || 0}
                    icon={<AlertIcon />}
                />
                <StatCard
                    label="Auto-Promoted Today"
                    value={pendingCandidates?.promoted_today || 0}
                    icon={<CheckIcon />}
                />
                <StatCard
                    label="Rejected"
                    value={pendingCandidates?.rejected_count || 0}
                    icon={<CloseIcon />}
                />
            </SimpleGrid>

            <Card w="full">
                <CardBody>
                    <DataTable
                        data={pendingCandidates?.candidates || []}
                        columns={[
                            { key: 'name', label: 'Name' },
                            { key: 'type', label: 'Type' },
                            { key: 'composite_score', label: 'Score' },
                            { key: 'narrative_coherence', label: 'Narrative' },
                            { key: 'evidence_level', label: 'Evidence' },
                            { key: 'actions', label: 'Actions' }
                        ]}
                        onBulkAction={handleBulkPromote}
                        selectable
                    />
                </CardBody>
            </Card>
        </VStack>
    )
}
```

### 2.3 CRÉER (Nouveaux Composants)

**📌 NOTE IMPORTANTE FRONTEND** : Pour le détail complet de la stratégie frontend, voir **`FRONTEND_MIGRATION_STRATEGY.md`**. Cette section se concentre sur le backend.

#### 2.3.1 Backend - Semantic Intelligence Layer

```
🟢 CRÉER (15 000-20 000 lignes Python nouveau)

src/knowbase/semantic/
├── __init__.py
├── profiler/
│   ├── __init__.py
│   ├── document_profiler.py (500 lignes)
│   └── complexity_analyzer.py (300 lignes)
│
├── narrative/
│   ├── __init__.py
│   ├── thread_detector.py (600 lignes)
│   ├── causal_analyzer.py (400 lignes)
│   └── temporal_analyzer.py (300 lignes)
│
├── segmentation/
│   ├── __init__.py
│   └── intelligent_engine.py (400 lignes)
│
├── extraction/
│   ├── __init__.py
│   ├── dual_storage_extractor.py (500 lignes)
│   └── context_builder.py (300 lignes)
│
├── gatekeeper/
│   ├── __init__.py
│   ├── intelligent_gatekeeper.py (800 lignes)
│   ├── scoring_engine.py (400 lignes)
│   └── promotion_orchestrator.py (300 lignes)
│
├── storage/
│   ├── __init__.py
│   ├── neo4j_proto_manager.py (600 lignes)
│   ├── neo4j_published_manager.py (400 lignes)
│   ├── qdrant_proto_manager.py (400 lignes)
│   └── qdrant_published_manager.py (300 lignes)
│
├── lifecycle/
│   ├── __init__.py
│   ├── volumetry_manager.py (500 lignes)
│   └── tier_manager.py (300 lignes)
│
├── ontology/
│   ├── __init__.py
│   ├── living_ontology.py (600 lignes)
│   ├── pattern_discovery.py (500 lignes)
│   └── semantic_validator.py (400 lignes)
│
└── budget/
    ├── __init__.py
    ├── budget_manager.py (400 lignes)
    └── cost_tracker.py (300 lignes)

Total: ~10 000 lignes core + 5 000 lignes tests
```

**Priorité Création** (ordre implémentation) :

1. **Phase 1** (Semaines 1-10) :
   - `semantic/profiler/document_profiler.py` ⚠️ CRITIQUE
   - `semantic/narrative/thread_detector.py` ⚠️ CRITIQUE
   - `semantic/segmentation/intelligent_engine.py`
   - `semantic/storage/neo4j_proto_manager.py`
   - `semantic/storage/qdrant_proto_manager.py`

2. **Phase 2** (Semaines 11-18) :
   - `semantic/gatekeeper/intelligent_gatekeeper.py` ⚠️ CRITIQUE
   - `semantic/storage/neo4j_published_manager.py`
   - `semantic/extraction/dual_storage_extractor.py`

3. **Phase 3** (Semaines 19-26) :
   - `semantic/ontology/living_ontology.py`
   - `semantic/lifecycle/volumetry_manager.py`
   - `semantic/budget/budget_manager.py`

#### 2.3.2 Frontend - Nouveaux Dashboards

```
🟢 CRÉER (Frontend nouveau)

frontend/src/
├── app/admin/
│   ├── quality-control/
│   │   └── page.tsx (NEW) ⚠️ PRIORITÉ 1
│   │
│   ├── entity-constellation/
│   │   └── page.tsx (NEW) 🟡 PRIORITÉ 2
│   │
│   ├── budget-intelligence/
│   │   └── page.tsx (NEW) 🟡 PRIORITÉ 2
│   │
│   └── pattern-discovery/
│       └── page.tsx (NEW) 🟢 PRIORITÉ 3
│
└── components/ui/
    ├── DataTable.tsx (NEW si migration Mantine)
    ├── SemanticScoreCard.tsx (NEW)
    ├── NarrativeThreadViz.tsx (NEW)
    └── PromotionActionButtons.tsx (NEW)
```

#### 2.3.3 APIs Nouvelles

```
🟢 CRÉER (API Routes nouvelles)

src/knowbase/api/routers/
├── gatekeeper.py (NEW)
│   ├── GET /gatekeeper/pending
│   ├── POST /gatekeeper/promote/{candidate_id}
│   ├── POST /gatekeeper/promote-bulk
│   ├── POST /gatekeeper/reject/{candidate_id}
│   └── GET /gatekeeper/stats
│
├── semantic_query.py (NEW)
│   ├── POST /semantic-query/with-evolution
│   └── POST /semantic-query/cross-document
│
├── ontology_live.py (NEW)
│   ├── GET /ontology/patterns/discovered
│   ├── POST /ontology/patterns/{pattern_id}/validate
│   └── GET /ontology/evolution-history
│
└── volumetry.py (NEW)
    ├── GET /volumetry/stats
    └── POST /volumetry/transition-tier
```

### 2.4 Frontend - Résumé Impact (Développement Parallèle)

**⚠️ Voir `FRONTEND_MIGRATION_STRATEGY.md` pour stratégie complète**

#### Effort Frontend Total: 40-50 jours (parallèle backend)

**Vague 1 : Amélioration Base** (Sem 8-10 - 8 jours)
- WebSocket real-time integration
- Dashboard metrics enhanced
- Tables react-table upgrade (DataTable enterprise)

**Vague 2 : Dashboards Intelligence** (Sem 15-26 - 20 jours)
- 🔴 **Quality Control UI** (critique - 8j)
- Dashboard Intelligence enhanced (4j)
- Budget Intelligence Center (6j)
- Processing Pipeline Status (2j)

**Vague 3 : Polish & Documentation** (Sem 27-32 - 12 jours)
- UX improvements feedback
- Documentation UI composants
- Démos vidéo
- Responsive & accessibility

#### Composants Frontend Nouveaux

```
frontend/src/
├── app/admin/
│   ├── quality-control/page.tsx (NEW) ⚠️ P0
│   ├── budget/page.tsx (NEW) 🟡 P1
│   └── pipeline/page.tsx (NEW) 🟡 P1
│
├── components/
│   ├── dashboard/
│   │   ├── IntelligenceTrendsChart.tsx (NEW)
│   │   └── SemanticScoreCard.tsx (NEW)
│   │
│   ├── quality-control/
│   │   ├── CandidateDataTable.tsx (NEW)
│   │   └── EvidenceViewer.tsx (NEW)
│   │
│   └── ui/
│       └── DataTable.tsx (NEW - react-table wrapper)
│
└── lib/
    └── websocket.tsx (NEW - Socket.io)
```

#### Dépendances Frontend Additionnelles

```json
{
  "dependencies": {
    "@tanstack/react-table": "^8.10.0",  // DataTable enterprise
    "recharts": "^2.10.0",                // Charts
    "socket.io-client": "^4.6.0",         // Real-time
    "d3": "^7.8.5"                        // Visualizations (Phase 5+)
  }
}
```

**Décision Technique** : Rester ChakraUI (pas migration Mantine pour MVP)

---

## 3. Plan de Migration par Phase

### Phase 1 : Semantic Core (Semaines 1-10)

#### Semaine 1-2 : Setup Infrastructure

```bash
# Créer structure dossiers
mkdir -p src/knowbase/semantic/{profiler,narrative,segmentation,storage}

# Setup Neo4j Proto collections
# Script: scripts/setup_proto_kg.py
CREATE CONSTRAINT candidate_entity_unique ...

# Setup Qdrant Proto collections
# Script: scripts/setup_qdrant_proto.py
client.create_collection("concepts_proto", ...)

# Tests
pytest tests/semantic/test_infrastructure_setup.py
```

#### Semaine 3-4 : Semantic Document Profiler

```python
# Implémenter
src/knowbase/semantic/profiler/document_profiler.py

# Tester
tests/semantic/test_document_profiler.py

# Validation
- Test sur 10 documents variés
- Vérifier narrative threads détectés
- Vérifier complexity zones mappées
```

#### Semaine 5-8 : Narrative Thread Detection

```python
# Implémenter
src/knowbase/semantic/narrative/thread_detector.py
src/knowbase/semantic/narrative/causal_analyzer.py

# Tester sur cas d'usage KILLER
tests/semantic/test_crr_evolution.py
- 3 documents Customer Retention Rate
- Vérifier cross-document references détectés
- Vérifier evolution chain construite
```

#### Semaine 9-10 : Intégration Pipeline PDF

```python
# Modifier
src/knowbase/ingestion/pipelines/pdf_pipeline.py
+ process_pdf_semantic()

# Feature flag
extraction_mode = "SEMANTIC" | "LEGACY"

# Tests E2E
tests/integration/test_pdf_semantic_pipeline.py
- Ingest 5 PDFs en mode SEMANTIC
- Vérifier entities en Proto-KG
- Comparer vs mode LEGACY
```

**Checkpoint Phase 1** :
- ✅ Démo CRR Evolution fonctionne
- ✅ Narrative threads détectés sur 10+ docs
- ✅ Pipeline semantic opérationnel
- ✅ Pas de régression pipeline legacy

### Phase 2 : Dual-Graph + Gatekeeper (Semaines 11-18)

#### Semaine 11-12 : Proto-KG Storage

```python
# Implémenter
src/knowbase/semantic/storage/neo4j_proto_manager.py
src/knowbase/semantic/storage/qdrant_proto_manager.py

# Tester
tests/semantic/storage/test_proto_storage.py
- Stage 100 entities
- Vérifier MERGE logique
- Vérifier source_count incrémenté
```

#### Semaine 13-16 : Semantic Gatekeeper

```python
# Implémenter
src/knowbase/semantic/gatekeeper/intelligent_gatekeeper.py
src/knowbase/semantic/gatekeeper/scoring_engine.py

# Tester
tests/semantic/gatekeeper/test_scoring.py
- 50 entities avec scores variés
- Vérifier promotion auto >0.75
- Vérifier human review 0.65-0.75
- Vérifier rejection <0.65
```

#### Semaine 17-18 : Published-KG + Promotion

```python
# Implémenter
src/knowbase/semantic/storage/neo4j_published_manager.py
src/knowbase/semantic/gatekeeper/promotion_orchestrator.py

# Tester promotion transactionnelle
tests/semantic/test_promotion_pipeline.py
- Promote 20 entities Proto → Published
- Vérifier rollback si erreur
- Vérifier audit trail
```

**Checkpoint Phase 2** :
- ✅ Proto-KG contient candidats
- ✅ Gatekeeper évalue avec précision >85%
- ✅ Auto-promotion fonctionne
- ✅ Published-KG contient données validées

### Phase 3 : Living Ontology + Volumetry (Semaines 19-26)

#### Semaine 19-22 : Living Ontology

```python
# Implémenter
src/knowbase/semantic/ontology/living_ontology.py
src/knowbase/semantic/ontology/pattern_discovery.py

# Tester
tests/semantic/ontology/test_pattern_discovery.py
- Ingérer 50 docs avec patterns émergents
- Vérifier patterns détectés automatiquement
- Vérifier validation sémantique LLM
```

#### Semaine 23-26 : Volumetry Management

```python
# Implémenter
src/knowbase/semantic/lifecycle/volumetry_manager.py
src/knowbase/semantic/lifecycle/tier_manager.py

# Tester lifecycle
tests/semantic/lifecycle/test_tier_transitions.py
- Simuler HOT → WARM après 14j
- Simuler WARM → COLD après 60j
- Vérifier caps appliqués
```

**Checkpoint Phase 3** :
- ✅ Patterns découverts automatiquement
- ✅ Ontologie évolue sans intervention
- ✅ Volumétrie Proto-KG stable <10k entities
- ✅ Lifecycle fonctionne automatiquement

### Phase 4 : Frontend + Polish (Semaines 27-32)

#### Semaine 27-29 : Quality Control UI

```tsx
// Créer
frontend/src/app/admin/quality-control/page.tsx
frontend/src/components/ui/DataTable.tsx
frontend/src/components/ui/SemanticScoreCard.tsx

// Tester
- Interface liste candidats pending
- Bulk actions (promote, reject)
- Filtres (score, type, domain)
```

#### Semaine 30-31 : Dashboards Intelligence

```tsx
// Créer
frontend/src/app/admin/entity-constellation/page.tsx
frontend/src/app/admin/budget-intelligence/page.tsx

// Intégrer visualizations D3
// Real-time updates WebSocket
```

#### Semaine 32 : Documentation + Démos

```markdown
# Créer
doc/USER_GUIDE_SEMANTIC_INTELLIGENCE.md
doc/API_REFERENCE_SEMANTIC.md
doc/DEPLOYMENT_GUIDE.md

# Préparer démos
demos/crr_evolution_demo.mp4
demos/quality_control_demo.mp4
demos/living_ontology_demo.mp4
```

---

## 4. Stratégie de Compatibilité

### 4.1 Backward Compatibility

**Principe** : Ancien pipeline reste disponible, nouveau pipeline opt-in progressif

```python
# API ingestion avec feature flag
@router.post("/ingest/document")
async def ingest_document(
    file: UploadFile,
    extraction_mode: str = "LEGACY"  # LEGACY | SEMANTIC
):
    if extraction_mode == "SEMANTIC":
        return await ingest_semantic(file)
    else:
        return await ingest_legacy(file)
```

**Migration Progressive** :
1. Semaines 1-10 : Semantic mode opt-in, users testent
2. Semaines 11-18 : Semantic mode recommandé, legacy disponible
3. Semaines 19-26 : Semantic mode par défaut, legacy deprecated
4. Semaines 27+ : Legacy mode supprimé (ou archivé)

### 4.2 Data Migration Strategy

**592 Entities Actuelles → Published-KG ?**

```python
# Script: scripts/migrate_existing_to_published.py

async def migrate_existing_entities_to_published():
    """
    Migre les 592 entities actuelles vers Published-KG.

    Options:
    1. Grandfathering: Tout passe en Published-KG (rapide, moins de qualité)
    2. Re-evaluation: Passer par Gatekeeper (lent, plus de qualité)
    3. Hybride: Garder entities avec confidence >0.7, rejeter autres
    """

    # Option recommandée: Hybride
    existing_entities = await neo4j.get_all_entities()

    for entity in existing_entities:
        if entity.confidence >= 0.7 and entity.source_count >= 2:
            # Direct migration vers Published
            await neo4j_published.create_entity(entity)
        else:
            # Stage en Proto pour re-evaluation
            await neo4j_proto.stage_entity(entity)

    print(f"Migrated {migrated_count} to Published, {staged_count} to Proto")
```

---

## 5. Risks et Mitigations

### 5.1 Risques Techniques

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Narrative detection faux positifs** | Moyenne | Moyen | Threshold tuning, validation humaine échantillon |
| **Performance dégradée 3x** | Élevée | Moyen | Horizontal scaling workers, caching threads |
| **Sync Proto↔Published échoue** | Moyenne | Élevé | Transactions, retry logic, rollback automatique |
| **Gatekeeper trop strict** | Moyenne | Moyen | Seuils adaptatifs, feedback loop, human override |
| **Living Ontology drift** | Faible | Élevé | Version control ontologie, human approval patterns |

### 5.2 Risques Développement

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Sous-estimation effort** | Moyenne | Élevé | Buffers 20% par phase, checkpoints GO/NO-GO |
| **Scope creep** | Élevée | Moyen | MVP strict, "nice-to-have" en backlog Phase 5 |
| **Burnout solo dev** | Moyenne | Élevé | Rythme soutenable 25-30h/semaine, breaks réguliers |
| **Blockers techniques NLP** | Moyenne | Moyen | POCs early, librairies externes (spaCy, neuralcoref) |

---

## 6. Checkpoints Validation

### Checkpoint Phase 1 (Semaine 10)

**Critères GO/NO-GO** :

- [ ] Démo CRR Evolution fonctionne sur 3 documents
- [ ] Narrative threads détectés sur 10+ documents test
- [ ] Pipeline semantic traite 5 PDFs sans erreur
- [ ] Performance acceptable (<45s par document)
- [ ] Pas de régression pipeline legacy

**Si NO-GO** :
- Revoir approach narrative detection (simplifier?)
- Ajuster seuils complexity zones
- Besoin 2 semaines additionnelles?

### Checkpoint Phase 2 (Semaine 18)

**Critères GO/NO-GO** :

- [ ] Proto-KG contient 100+ entities staging
- [ ] Gatekeeper auto-promotion rate >80%
- [ ] Précision promotion validée (sample 50 entities)
- [ ] Published-KG fonctionnel avec données validées
- [ ] Transactional promotion sans erreurs

**Si NO-GO** :
- Revoir scoring gatekeeper (poids critères?)
- Simplifier promotion pipeline
- Besoin calibration thresholds

### Checkpoint Phase 3 (Semaine 26)

**Critères GO/NO-GO** :

- [ ] Pattern discovery détecte 3+ patterns valides
- [ ] Living Ontology evolve automatiquement
- [ ] Volumétrie Proto-KG stable (<10k entities)
- [ ] Lifecycle transitions fonctionnent (HOT→WARM→COLD)

**Si NO-GO** :
- Pattern discovery peut être feature Phase 5
- Lifecycle manuel acceptable temporairement
- Focus sur stabilité avant automation complète

### Checkpoint Phase 4 (Semaine 32)

**Critères GO/NO-GO** :

- [ ] Quality Control UI fonctionnelle et utilisable
- [ ] 3-5 POCs clients testent MVP
- [ ] Documentation complète et compréhensible
- [ ] Démos automatisées prêtes
- [ ] Metrics montrent différenciation vs Copilot

**Si GO** : Lancement MVP commercialisable
**Si NO-GO** : 2-4 semaines polish additionnelles

---

## Annexe : Scripts Migration

### A.1 Setup Proto-KG

```python
# scripts/setup_proto_kg.py

async def setup_proto_kg_schema():
    """Setup Neo4j Proto-KG schema"""

    cypher_constraints = """
    // CandidateEntity constraints
    CREATE CONSTRAINT candidate_entity_unique IF NOT EXISTS
    FOR (e:CandidateEntity)
    REQUIRE (e.tenant_id, e.normalized_name, e.entity_type) IS UNIQUE;

    CREATE INDEX candidate_entity_stage IF NOT EXISTS
    FOR (e:CandidateEntity) ON (e.stage);

    CREATE INDEX candidate_entity_tier IF NOT EXISTS
    FOR (e:CandidateEntity) ON (e.tier);

    CREATE INDEX candidate_entity_created_at IF NOT EXISTS
    FOR (e:CandidateEntity) ON (e.created_at);

    // Published Entity constraints
    CREATE CONSTRAINT entity_unique IF NOT EXISTS
    FOR (e:Entity)
    REQUIRE (e.tenant_id, e.normalized_name, e.entity_type) IS UNIQUE;
    """

    await neo4j_client.execute_cypher(cypher_constraints)
    print("✅ Neo4j Proto-KG schema created")
```

### A.2 Setup Qdrant Proto

```python
# scripts/setup_qdrant_proto.py

async def setup_qdrant_proto_collections():
    """Setup Qdrant Proto collections"""

    # Concepts Proto
    qdrant_client.create_collection(
        collection_name="concepts_proto",
        vectors_config=VectorParams(size=384, distance=Distance.COSINE)
    )

    # Concepts Published
    qdrant_client.create_collection(
        collection_name="concepts_published",
        vectors_config=VectorParams(size=384, distance=Distance.COSINE)
    )

    print("✅ Qdrant Proto collections created")
```

---

## Conclusion Refactoring Plan

**Approche** : Extension progressive, pas remplacement brutal

**Timeline** : 32 semaines (8 mois) solo dev

**Risques** : Maîtrisables avec checkpoints GO/NO-GO

**Backward Compatibility** : Pipeline legacy preserved en fallback

**Migration Data** : Hybride (grandfathering + re-evaluation)

**Next Step** : Voir `AMBITION_PRODUIT_ROADMAP.md` pour vision globale et phasing clair.
