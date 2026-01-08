# Phase 2.9 - Segment-Level Relation Extraction

**Date de création:** 2025-12-21
**Status:** 📋 PLANIFIÉ - En attente d'implémentation
**Priorité:** CRITIQUE (85% des concepts sans relations)
**Collaboration:** Claude Code + ChatGPT (analyse croisée)
**Dépendances:** Phase 2.8.1 (Canonical Dedup Fix) ✅ COMPLETE

---

## 1. Position dans la Timeline

```
Phase 2 : Intelligence Relationnelle Avancée
════════════════════════════════════════════

├─ Phase 2.5 : Memory Layer                    ✅ COMPLETE
├─ Phase 2.7 : Concept Matching Engine         ✅ COMPLETE (78% golden set)
├─ Phase 2.8 : ID-First Relation Extraction    ✅ IMPLÉMENTÉ (document-level)
│   └─ Phase 2.8.1 : Canonical Dedup Fix       ✅ COMPLETE
├─ Phase 2.9 : Segment-Level Relations         🔴 EN COURS ← VOUS ÊTES ICI
│   ├─ 2.9.1 : Extraction par segment
│   ├─ 2.9.2 : Catalogue hybride (local + global)
│   └─ 2.9.3 : Cross-segment relations (PatternMiner)
└─ Phase 2.10+ : Consolidation & Inference     ⏸️ NOT STARTED
```

---

## 2. Contexte et Problème

### 2.1 Symptôme Observé

Après implémentation Phase 2.8 (ID-First), **85% des CanonicalConcepts restent isolés** (sans relations).

**Stats Neo4j (2025-12-21):**
```
CanonicalConcepts: 1081
  - Avec relations: 165 (15%)
  - Isolés: 916 (85%) ← PROBLÈME
```

### 2.2 Cause Racine : Document-Level vs Segment-Level

**Architecture prévue (OSMOSE_CRITIQUE_BONNES_PRATIQUES_KG_ACADEMIQUES.md):**
```python
# Extraction par segment sémantique
for segment in topics:
    await Extractor.execute(state, segment)

# Pattern mining cross-segments
state = await PatternMiner.execute(state)
```

**Implémentation actuelle (Phase 2.8):**
```python
# Catalogue = TOUS les concepts du document
catalogue = build_catalogue(state.promoted)  # 400+ concepts pour gros docs

# LLM reçoit catalogue complet
relations = await extract_relations(text, catalogue)
```

### 2.3 Corrélation Inversée Taille Catalogue ↔ Utilisation

| Document | Concepts | Utilisés | Taux |
|----------|----------|----------|------|
| bird_protection_directive | 39 | 32 | **82%** |
| eu_ai_act | 438 | 48 | **11%** |
| eprivacy_directive | 98 | 16 | **16%** |
| eidas_regulation | 177 | 25 | **14%** |

**Conclusion:** Le LLM est submergé par les gros catalogues et n'utilise qu'une fraction des concepts.

---

## 3. Solution : Extraction Segment-Level avec Catalogue Hybride

### 3.1 Architecture Cible

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SEGMENT-LEVEL RELATION EXTRACTION                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Document                                                                │
│     │                                                                    │
│     ▼                                                                    │
│  TopicSegmenter                                                          │
│     │                                                                    │
│     ├─► Segment 1 ─► Concepts Locaux (10-30)                            │
│     │        │                                                           │
│     │        ▼                                                           │
│     │   ┌────────────────────────────────────────┐                       │
│     │   │ CATALOGUE HYBRIDE (Segment 1)          │                       │
│     │   │                                        │                       │
│     │   │  • Concepts locaux: c1-c25 (du segment)│                       │
│     │   │  • Top-K globaux: c100-c110 (fréquents)│                       │
│     │   │  • Hub concepts: c200-c205 (déjà liés) │                       │
│     │   │                                        │                       │
│     │   │  Total: ~40-50 concepts max            │                       │
│     │   └────────────────────────────────────────┘                       │
│     │        │                                                           │
│     │        ▼                                                           │
│     │   LLM Relation Extraction                                          │
│     │        │                                                           │
│     │        ▼                                                           │
│     │   RawAssertions (Segment 1)                                        │
│     │                                                                    │
│     ├─► Segment 2 ─► Concepts Locaux ─► Catalogue Hybride ─► Relations   │
│     │                                                                    │
│     ├─► Segment N ─► ...                                                 │
│     │                                                                    │
│     └─► PatternMiner (Cross-Segment)                                     │
│              │                                                           │
│              ▼                                                           │
│         Cross-Segment Relations                                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Catalogue Hybride : Composition

Pour chaque segment, le catalogue contient :

| Source | Critère de sélection | Limite |
|--------|---------------------|--------|
| **Concepts locaux** | Extraits du segment actuel | Tous (10-40) |
| **Top-K globaux** | Fréquence cross-documents (occurrence_count) | 10-15 |
| **Hub concepts** | Déjà liés (degree > 2) | 5-10 |
| **Concepts adjacents** | Même topic que segment | 5-10 |

**Total catalogue hybride: 40-60 concepts max** (vs 400+ actuellement)

### 3.3 Avantages

1. **Meilleur focus LLM** : Catalogue manageable → utilisation ~80% (vs 11%)
2. **Relations intra-segment** : Forte cohérence sémantique
3. **Cross-segment via hubs** : Concepts fréquents servent de "ponts"
4. **Scalabilité** : Temps extraction linéaire vs quadratique

---

## 4. Spécifications Techniques

### 4.1 Modification du State

```python
# state.py (AgentState)
@dataclass
class AgentState:
    # Existant
    promoted: List[PromotedConcept]  # Tous les concepts promotés

    # NOUVEAU: Concepts par segment
    segments_with_concepts: Dict[str, SegmentWithConcepts] = field(default_factory=dict)

@dataclass
class SegmentWithConcepts:
    segment_id: str
    text: str
    topic_id: str
    local_concepts: List[str]  # concept_ids locaux
    catalogue_concept_ids: List[str]  # catalogue hybride pour ce segment
```

### 4.2 Construction du Catalogue Hybride

```python
# relations/catalogue_builder.py (NOUVEAU)

def build_hybrid_catalogue(
    segment: SegmentWithConcepts,
    all_promoted: List[PromotedConcept],
    neo4j_client: Neo4jClient,
    tenant_id: str,
    config: CatalogueConfig = None
) -> Tuple[str, Dict[str, str]]:
    """
    Construit un catalogue hybride pour un segment.

    Returns:
        (catalogue_json, index_to_concept_id)
    """
    config = config or CatalogueConfig()

    # 1. Concepts locaux (du segment)
    local_concepts = [
        c for c in all_promoted
        if c.concept_id in segment.local_concepts
    ]

    # 2. Top-K globaux (par occurrence cross-documents)
    global_top_k = neo4j_client.get_top_concepts_by_occurrence(
        tenant_id=tenant_id,
        limit=config.top_k_global,
        exclude_ids=[c.concept_id for c in local_concepts]
    )

    # 3. Hub concepts (déjà bien connectés)
    hub_concepts = neo4j_client.get_hub_concepts(
        tenant_id=tenant_id,
        min_degree=config.hub_min_degree,
        limit=config.hub_limit,
        exclude_ids=[c.concept_id for c in local_concepts + global_top_k]
    )

    # 4. Concepts adjacents (même topic)
    adjacent_concepts = [
        c for c in all_promoted
        if c.topic_id == segment.topic_id
        and c.concept_id not in segment.local_concepts
    ][:config.adjacent_limit]

    # Fusion et déduplication
    all_concepts = deduplicate_by_id(
        local_concepts + global_top_k + hub_concepts + adjacent_concepts
    )

    # Limiter au max
    all_concepts = all_concepts[:config.max_catalogue_size]

    # Construire catalogue indexé
    return build_indexed_catalogue(all_concepts)


@dataclass
class CatalogueConfig:
    top_k_global: int = 15
    hub_min_degree: int = 3
    hub_limit: int = 10
    adjacent_limit: int = 10
    max_catalogue_size: int = 60
```

### 4.3 Requêtes Neo4j pour Catalogue

```python
# neo4j_client.py (nouvelles méthodes)

def get_top_concepts_by_occurrence(
    self,
    tenant_id: str,
    limit: int = 15,
    exclude_ids: List[str] = None
) -> List[PromotedConcept]:
    """Récupère les concepts les plus fréquents cross-documents."""
    exclude_clause = ""
    if exclude_ids:
        exclude_clause = "AND NOT c.canonical_id IN $exclude_ids"

    query = f"""
    MATCH (c:CanonicalConcept {{tenant_id: $tenant_id}})
    WHERE c.occurrence_count IS NOT NULL
    {exclude_clause}
    RETURN c.canonical_id AS id,
           c.canonical_name AS name,
           c.concept_type AS type,
           c.occurrence_count AS count
    ORDER BY c.occurrence_count DESC
    LIMIT $limit
    """
    # ...


def get_hub_concepts(
    self,
    tenant_id: str,
    min_degree: int = 3,
    limit: int = 10,
    exclude_ids: List[str] = None
) -> List[PromotedConcept]:
    """Récupère les concepts avec le plus de relations (hubs)."""
    exclude_clause = ""
    if exclude_ids:
        exclude_clause = "AND NOT c.canonical_id IN $exclude_ids"

    query = f"""
    MATCH (c:CanonicalConcept {{tenant_id: $tenant_id}})
    WHERE c.canonical_id IS NOT NULL
    {exclude_clause}
    WITH c,
         SIZE((c)<-[:HAS_SUBJECT]-()) + SIZE((c)<-[:HAS_OBJECT]-()) AS degree
    WHERE degree >= $min_degree
    RETURN c.canonical_id AS id,
           c.canonical_name AS name,
           c.concept_type AS type,
           degree
    ORDER BY degree DESC
    LIMIT $limit
    """
    # ...
```

### 4.4 Intégration dans le Pipeline

```python
# agents/supervisor/supervisor.py (modifié)

async def execute_relation_extraction(self, state: AgentState) -> AgentState:
    """Extraction segment-level au lieu de document-level."""

    all_relations = []
    all_unresolved = []

    # Pour chaque segment
    for segment_id, segment in state.segments_with_concepts.items():

        # 1. Construire catalogue hybride pour ce segment
        catalogue_json, index_map = build_hybrid_catalogue(
            segment=segment,
            all_promoted=state.promoted,
            neo4j_client=self.neo4j_client,
            tenant_id=state.tenant_id
        )

        logger.info(
            f"[OSMOSE:Relations] Segment {segment_id}: "
            f"{len(segment.local_concepts)} local + "
            f"{len(index_map) - len(segment.local_concepts)} global = "
            f"{len(index_map)} concepts"
        )

        # 2. Extraction relations pour ce segment
        relations, unresolved = await self.relation_extractor.extract_relations_v3(
            text=segment.text,
            catalogue_json=catalogue_json,
            index_to_concept_id=index_map,
            segment_id=segment_id,
            document_id=state.document_id
        )

        all_relations.extend(relations)
        all_unresolved.extend(unresolved)

    # 3. Cross-segment relations (PatternMiner) - Phase 2.9.3
    if self.config.enable_cross_segment:
        cross_relations = await self.pattern_miner.extract_cross_segment_relations(
            segments=state.segments_with_concepts,
            hub_concepts=state.hub_concepts
        )
        all_relations.extend(cross_relations)

    # 4. Écrire les relations
    for relation in all_relations:
        await self.raw_assertion_writer.write(relation)

    for mention in all_unresolved:
        await self.unresolved_writer.write(mention)

    state.relations_extracted = len(all_relations)
    return state
```

---

## 5. Plan d'Implémentation

### Phase 2.9.1 : Extraction par Segment (Priorité P0)

| Tâche | Fichier | Effort | Status |
|-------|---------|--------|--------|
| Créer `SegmentWithConcepts` dataclass | `agents/state.py` | 1h | ⏸️ |
| Modifier Extractor pour populer `segments_with_concepts` | `agents/extractor/orchestrator.py` | 2h | ⏸️ |
| Créer `catalogue_builder.py` | `relations/catalogue_builder.py` | 3h | ⏸️ |
| Ajouter `get_top_concepts_by_occurrence()` | `common/clients/neo4j_client.py` | 1h | ⏸️ |
| Ajouter `get_hub_concepts()` | `common/clients/neo4j_client.py` | 1h | ⏸️ |
| Modifier Supervisor pour loop segments | `agents/supervisor/supervisor.py` | 3h | ⏸️ |
| Tests unitaires | `tests/relations/test_catalogue_builder.py` | 2h | ⏸️ |

**Effort total 2.9.1:** ~13h (2 jours)

### Phase 2.9.2 : Ajout occurrence_count (Dépendance)

| Tâche | Fichier | Effort | Status |
|-------|---------|--------|--------|
| Ajouter `occurrence_count` à CanonicalConcept | `neo4j_client.py` | 1h | ⏸️ |
| Incrémenter à chaque nouvelle mention | `gatekeeper.py` | 1h | ⏸️ |
| Script migration backfill | `scripts/backfill_occurrence_count.py` | 2h | ⏸️ |

**Effort total 2.9.2:** ~4h

### Phase 2.9.3 : Cross-Segment Relations (Optionnel P2)

| Tâche | Fichier | Effort | Status |
|-------|---------|--------|--------|
| Créer PatternMiner agent | `agents/pattern_miner/` | 8h | ⏸️ |
| Prompt cross-segment relations | `config/prompts.yaml` | 2h | ⏸️ |
| Intégration Supervisor | `agents/supervisor/supervisor.py` | 2h | ⏸️ |

**Effort total 2.9.3:** ~12h (2 jours)

---

## 6. Métriques de Succès

| Métrique | Avant (2.8) | Cible (2.9) |
|----------|-------------|-------------|
| Concepts utilisés (gros docs) | 11-16% | > 70% |
| Concepts isolés (sans relations) | 85% | < 30% |
| Temps extraction par segment | N/A | < 5s |
| Temps extraction total doc | ~30s (doc-level) | ~45s (10 segments × 4.5s) |
| Relations par segment | N/A | 5-15 |

---

## 7. Risques et Mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Cross-segment relations manquées | Moyenne | Moyen | Hub concepts dans catalogue + Phase 2.9.3 |
| Overhead temps (N appels LLM) | Moyenne | Faible | Parallélisation segments, budget tokens réduit |
| Doublons relations inter-segments | Basse | Faible | Dédup RawAssertion sur (subject, object, predicate) |
| Concepts locaux insuffisants | Basse | Moyen | Top-K globaux + hubs comblent |

---

## 8. Références

- **Problème identifié:** Phase 2.8.1 Section 11
- **Architecture originale:** `doc/ongoing/OSMOSE_CRITIQUE_BONNES_PRATIQUES_KG_ACADEMIQUES.md`
- **ID-First (base):** `doc/ongoing/PHASE2.8_ID_FIRST_EXTRACTION.md`
- **Conversation technique:** Claude Code + ChatGPT 2025-12-21

---

---

## 9. Implémentation Réalisée

### 9.1 Fichiers Créés/Modifiés

| Fichier | Type | Description |
|---------|------|-------------|
| `src/knowbase/agents/base.py` | Modifié | Ajout `SegmentWithConcepts` dataclass |
| `src/knowbase/relations/catalogue_builder.py` | **Créé** | Construction catalogue hybride |
| `src/knowbase/common/clients/neo4j_client.py` | Modifié | Ajout `get_top_concepts_by_occurrence()`, `get_hub_concepts()`, `increment_occurrence_count()` |
| `src/knowbase/agents/extractor/orchestrator.py` | Modifié | Population `segments_with_concepts` |
| `src/knowbase/agents/supervisor/supervisor.py` | Modifié | Extraction segment-level avec fallback document-level |
| `src/knowbase/agents/miner/miner.py` | Modifié | Ajout `extract_cross_segment_relations()` |
| `src/knowbase/relations/__init__.py` | Modifié | Export nouveaux modules |
| `scripts/backfill_occurrence_count.py` | **Créé** | Script migration occurrence_count |

### 9.2 Architecture Implémentée

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    PHASE 2.9 - SEGMENT-LEVEL FLOW                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Document → TopicSegmenter → Segments                                   │
│                                   │                                      │
│                                   ▼                                      │
│  ExtractorOrchestrator ─────► segments_with_concepts                    │
│       │                       (Dict[segment_id, SegmentWithConcepts])   │
│       │                                                                  │
│       ▼                                                                  │
│  GatekeeperDelegate ─────► state.promoted (concepts promotés)           │
│                                                                          │
│       ▼                                                                  │
│  Supervisor.EXTRACT_RELATIONS                                            │
│       │                                                                  │
│       ├─► Pour chaque segment:                                          │
│       │     1. build_hybrid_catalogue()                                 │
│       │     2. LLMRelationExtractor.extract_relations_id_first()        │
│       │     3. RawAssertionWriter.write_assertion()                     │
│       │                                                                  │
│       └─► PatternMiner.extract_cross_segment_relations() [optionnel]    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 9.3 Configuration

```python
# CatalogueConfig par défaut
config = CatalogueConfig(
    top_k_global=15,      # Concepts fréquents cross-docs
    hub_min_degree=3,      # Minimum relations pour être hub
    hub_limit=10,          # Max hubs dans catalogue
    adjacent_limit=10,     # Max concepts du même topic
    max_catalogue_size=60  # Taille max catalogue hybride
)
```

### 9.4 Fallback Document-Level

Si `segments_with_concepts` est vide, le système bascule automatiquement sur l'extraction document-level (Phase 2.8 legacy) pour assurer la rétrocompatibilité.

---

**Version:** 2.0
**Dernière MAJ:** 2025-12-22 00:00 UTC
**Status:** ✅ IMPLÉMENTÉ
**Auteurs:** Claude Code + ChatGPT (validation croisée)
