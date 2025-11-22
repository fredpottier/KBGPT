# Sprint 1.8.1d : Architecture SmartConceptMerger

**Date:** 2025-11-21
**Sprint:** Phase 1.8.1d - Extraction Locale + Fusion Contextuelle
**Status:** 🔵 DESIGN

---

## 🎯 Objectif

Résoudre le problème architectural de la segmentation pour documents structurés (PPTX) :
- **Problème actuel:** TopicSegmenter fusionne trop (87 slides → 5 segments → 28 concepts)
- **Solution:** Extraction locale granulaire (par slide) + fusion intelligente basée sur règles

---

## 📐 Architecture Globale

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OSMOSE Pipeline                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────┐                                                   │
│  │  Document    │                                                   │
│  │  Input       │                                                   │
│  │  (PPTX/PDF)  │                                                   │
│  └──────┬───────┘                                                   │
│         │                                                            │
│         ├─────► Document Type Detection                             │
│         │                                                            │
│    ┌────▼─────┐                                                     │
│    │ PPTX ?   │                                                     │
│    └────┬─────┘                                                     │
│         │                                                            │
│    ┌────▼──────────────────────────┬──────────────────────────┐    │
│    │ YES                            │ NO                       │    │
│    │                                │                          │    │
│    │ ┌────────────────────┐         │ ┌──────────────────┐   │    │
│    │ │ LOCAL EXTRACTION   │         │ │  TOPIC SEGMENTER │   │    │
│    │ │ (Per-Slide)        │         │ │  (Legacy)        │   │    │
│    │ └────────┬───────────┘         │ └────────┬─────────┘   │    │
│    │          │                      │          │             │    │
│    │  ┌───────▼──────────┐           │  ┌───────▼──────┐     │    │
│    │  │ ConceptExtractor │           │  │ Extraction   │     │    │
│    │  │ mode="local"     │           │  │ Classique    │     │    │
│    │  │ (par slide)      │           │  └──────┬───────┘     │    │
│    │  └───────┬──────────┘           │         │             │    │
│    │          │                      │         │             │    │
│    │  ┌───────▼──────────┐           │         │             │    │
│    │  │ Local Concepts   │           │         │             │    │
│    │  │ [3-10 par slide] │           │         │             │    │
│    │  └───────┬──────────┘           │         │             │    │
│    │          │                      │         │             │    │
│    │  ┌───────▼──────────────┐       │         │             │    │
│    │  │ SmartConceptMerger   │       │         │             │    │
│    │  │ (Fusion Rules)       │       │         │             │    │
│    │  └───────┬──────────────┘       │         │             │    │
│    │          │                      │         │             │    │
│    └──────────┼──────────────────────┴─────────┼─────────────┘    │
│               │                                 │                  │
│         ┌─────▼─────────────────────────────────▼─────┐            │
│         │     Canonical Concepts (Unified)            │            │
│         └─────┬───────────────────────────────────────┘            │
│               │                                                     │
│         ┌─────▼─────────────────────────────┐                      │
│         │     Neo4j Proto-KG + Qdrant       │                      │
│         └───────────────────────────────────┘                      │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 🧩 Composants

### 1. **ConceptExtractor (Modifié)**

**Fichier:** `src/knowbase/semantic/extraction/concept_extractor.py`

**Nouveau paramètre:**
```python
async def extract_concepts(
    self,
    topic: str,
    language: str = "en",
    document_context: Optional[str] = None,
    extraction_mode: str = "standard",  # NEW: "standard" | "local"
    source_metadata: Optional[Dict] = None  # NEW: {"slide_index": 1, "section": "intro"}
) -> List[Concept]
```

**Comportement:**
- **`mode="standard"`**: Extraction classique (contexte large, segmentation préalable)
- **`mode="local"`**: Extraction granulaire (focus segment isolé, preserve metadata source)

**Modifications requises:**
- Ajuster prompts LLM selon mode (local = granularité fine)
- Préserver `source_metadata` dans `Concept.metadata`
- Extraction locale: viser 3-10 concepts/segment (vs 5-15 classique)

---

### 2. **SmartConceptMerger (Nouveau)**

**Fichier:** `src/knowbase/semantic/fusion/smart_concept_merger.py`

**Rôle:** Orchestrateur de fusion contextuelle basée sur règles.

**API Principale:**
```python
class SmartConceptMerger:
    def __init__(
        self,
        rules: List[FusionRule],
        config: FusionConfig
    ):
        """
        Args:
            rules: Liste des règles de fusion (ordre = priorité)
            config: Configuration fusion (YAML)
        """
        self.rules = rules
        self.config = config
        self.logger = logging.getLogger(__name__)

    async def merge(
        self,
        local_concepts: List[List[Concept]],
        document_context: Optional[str] = None
    ) -> List[CanonicalConcept]:
        """
        Fusion intelligente des concepts locaux.

        Args:
            local_concepts: Liste de listes de concepts (1 liste par slide)
            document_context: Contexte global du document (optionnel)

        Returns:
            Liste de CanonicalConcepts fusionnés

        Process:
            1. Flatten concepts locaux (avec metadata source)
            2. Pour chaque règle (ordre priorité):
               - Identifier groupes éligibles
               - Appliquer règle
               - Marquer concepts traités
            3. Concepts non fusionnés → CanonicalConcepts individuels
        """
        pass
```

**Structure Données:**
```python
@dataclass
class FusionResult:
    """Résultat application règle fusion"""
    merged_concepts: List[CanonicalConcept]  # Concepts fusionnés
    preserved_concepts: List[Concept]  # Concepts préservés
    relationships: List[Tuple[str, str, str]]  # (concept1, rel_type, concept2)
    rule_name: str
    reason: str  # Explication pourquoi règle appliquée
```

---

### 3. **FusionRule (Abstract Base Class)**

**Fichier:** `src/knowbase/semantic/fusion/fusion_rules.py`

**Design Pattern:** Strategy Pattern

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from knowbase.semantic.models import Concept

class FusionRule(ABC):
    """Règle de fusion abstraite"""

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: Configuration règle (depuis YAML)
        """
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def name(self) -> str:
        """Nom unique de la règle"""
        pass

    @abstractmethod
    def should_apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> bool:
        """
        Détermine si règle doit s'appliquer.

        Args:
            concepts: Liste concepts candidats
            context: Contexte document/segment

        Returns:
            True si règle applicable
        """
        pass

    @abstractmethod
    async def apply(
        self,
        concepts: List[Concept],
        context: Optional[Dict] = None
    ) -> FusionResult:
        """
        Applique règle de fusion.

        Args:
            concepts: Concepts à fusionner
            context: Contexte additionnel

        Returns:
            FusionResult avec concepts fusionnés/préservés
        """
        pass
```

---

### 4. **Règles MVP (3 règles prioritaires)**

#### **Règle 1: MainEntitiesMergeRule**

**Fichier:** `src/knowbase/semantic/fusion/rules/main_entities.py`

**Objectif:** Fusionner entités principales répétées dans tout le document.

**Critères:**
- Concept répété dans ≥ X% des slides (config: `min_occurrence_ratio: 0.15`)
- Similarity ≥ 0.88 (config: `similarity_threshold: 0.88`)
- Type concept = `ENTITY` ou `PRODUCT`

**Logique:**
```python
class MainEntitiesMergeRule(FusionRule):
    def name(self) -> str:
        return "main_entities_merge"

    def should_apply(self, concepts: List[Concept], context: Optional[Dict] = None) -> bool:
        # Vérifier si au moins un concept répété ≥ min_occurrence_ratio
        total_slides = context.get("total_slides", 1)
        for concept in concepts:
            occurrences = len(concept.metadata.get("source_slides", []))
            ratio = occurrences / total_slides
            if ratio >= self.config.get("min_occurrence_ratio", 0.15):
                return True
        return False

    async def apply(self, concepts: List[Concept], context: Optional[Dict] = None) -> FusionResult:
        # 1. Identifier concepts répétés
        # 2. Calculer embeddings + cosine similarity
        # 3. Cluster concepts similaires (≥ threshold)
        # 4. Pour chaque cluster: créer CanonicalConcept
        # 5. Préserver concepts non fusionnés
        pass
```

**Exemple:**
```
Input:
- Slide 1: "SAP S/4HANA" (mention 1)
- Slide 5: "SAP S/4HANA Cloud" (mention 2)
- Slide 12: "S/4HANA" (mention 3)
- Slide 23: "SAP S/4HANA" (mention 4)
... (15 mentions sur 87 slides = 17% occurrence)

Output:
- CanonicalConcept("SAP S/4HANA", aliases=["S/4HANA", "SAP S/4HANA Cloud"])
- metadata.source_slides = [1, 5, 12, 23, ...]
```

---

#### **Règle 2: AlternativesFeaturesRule**

**Fichier:** `src/knowbase/semantic/fusion/rules/alternatives.py`

**Objectif:** Détecter alternatives/opposés et créer relations (PAS fusion).

**Critères:**
- Concepts sémantiquement opposés (similarity < 0.3 mais co-occurrents)
- Présence mots-clés antonymes: "vs", "versus", "instead of", "alternative to"
- Détection patterns: "Multi-Tenancy" ↔ "Single-Tenant"

**Logique:**
```python
class AlternativesFeaturesRule(FusionRule):
    def name(self) -> str:
        return "alternatives_features"

    def should_apply(self, concepts: List[Concept], context: Optional[Dict] = None) -> bool:
        # Rechercher paires concepts avec antonymes keywords
        antonym_patterns = ["vs", "versus", "instead of", "alternative"]
        for concept in concepts:
            if any(pattern in concept.name.lower() for pattern in antonym_patterns):
                return True
        return False

    async def apply(self, concepts: List[Concept], context: Optional[Dict] = None) -> FusionResult:
        # 1. Identifier paires opposées (NLP + keywords)
        # 2. Créer relation `alternative_to` (bidirectionnelle)
        # 3. Préserver TOUS concepts (pas de fusion)
        # 4. Enrichir metadata avec contexte comparaison
        pass
```

**Exemple:**
```
Input:
- Concept: "Multi-Tenancy" (mentionné slides 10-20)
- Concept: "Single-Tenant Architecture" (mentionné slides 10-20)
- Co-occurrence: 10 slides communs

Output:
- Concept("Multi-Tenancy") → PRESERVED
- Concept("Single-Tenant Architecture") → PRESERVED
- Relationship: ("Multi-Tenancy", "alternative_to", "Single-Tenant Architecture")
- metadata.comparison_context = "Architecture deployment options"
```

---

#### **Règle 3: SlideSpecificPreserveRule**

**Fichier:** `src/knowbase/semantic/fusion/rules/slide_specific.py`

**Objectif:** Préserver détails techniques mentionnés UNE SEULE FOIS (slide-specific).

**Critères:**
- Concept mentionné dans ≤ 2 slides (config: `max_occurrence: 2`)
- Type concept = `METRIC`, `DETAIL`, `TECHNICAL`
- Longueur nom > 15 chars (détails précis)

**Logique:**
```python
class SlideSpecificPreserveRule(FusionRule):
    def name(self) -> str:
        return "slide_specific_preserve"

    def should_apply(self, concepts: List[Concept], context: Optional[Dict] = None) -> bool:
        # Toujours appliquer (règle de préservation par défaut)
        return True

    async def apply(self, concepts: List[Concept], context: Optional[Dict] = None) -> FusionResult:
        # 1. Filtrer concepts rares (≤ max_occurrence)
        # 2. Créer CanonicalConcept individuel pour chacun
        # 3. Préserver metadata source_slides (traçabilité)
        # 4. Aucune fusion
        pass
```

**Exemple:**
```
Input:
- Concept: "Response Time < 200ms (P95)" (slide 42 uniquement)
- Concept: "Database Connection Pool Size: 50" (slide 67 uniquement)

Output:
- CanonicalConcept("Response Time < 200ms (P95)")
  - metadata.source_slides = [42]
  - metadata.frequency = "rare"
- CanonicalConcept("Database Connection Pool Size: 50")
  - metadata.source_slides = [67]
  - metadata.frequency = "rare"
```

---

## 📊 Flux de Données Détaillé

### Étape 1: Extraction Locale (Par Slide)

**Input:**
```python
slides_data = [
    {"index": 0, "text": "SAP S/4HANA is...", "notes": "..."},
    {"index": 1, "text": "Multi-Tenancy architecture...", "notes": "..."},
    # ... 87 slides
]
```

**Process:**
```python
local_concepts = []
for slide in slides_data:
    concepts = await extractor.extract_concepts(
        topic=slide['text'] + " " + slide.get('notes', ''),
        extraction_mode="local",
        source_metadata={"slide_index": slide['index']}
    )
    local_concepts.append(concepts)
```

**Output:**
```python
# 87 listes de 3-10 concepts chacune
local_concepts = [
    [  # Slide 0
        Concept(name="SAP S/4HANA", type="ENTITY", metadata={"slide_index": 0}),
        Concept(name="Cloud ERP", type="PRODUCT", metadata={"slide_index": 0}),
        ...
    ],
    [  # Slide 1
        Concept(name="Multi-Tenancy", type="ENTITY", metadata={"slide_index": 1}),
        ...
    ],
    # ...
]
# Total: ~300-800 concepts locaux (avant fusion)
```

---

### Étape 2: Fusion Contextuelle (SmartConceptMerger)

**Input:** `local_concepts` (87 listes)

**Process:**
```python
merger = SmartConceptMerger(
    rules=[
        MainEntitiesMergeRule(config_main),
        AlternativesFeaturesRule(config_alt),
        SlideSpecificPreserveRule(config_preserve)
    ],
    config=fusion_config
)

canonical_concepts = await merger.merge(
    local_concepts=local_concepts,
    document_context=document_summary
)
```

**Étapes internes:**

1. **Flatten + Index:**
   ```python
   # Aplatir concepts locaux
   flat_concepts = []
   for i, slide_concepts in enumerate(local_concepts):
       for concept in slide_concepts:
           concept.metadata['slide_index'] = i
           flat_concepts.append(concept)
   # Total: ~500 concepts
   ```

2. **Application Règle 1 (Main Entities):**
   ```python
   # Grouper concepts similaires répétés
   clusters = find_repeated_entities(flat_concepts)
   # Exemple cluster:
   # ["SAP S/4HANA", "S/4HANA", "SAP S/4HANA Cloud"]
   # → occurrences: [1, 5, 12, 23, ...] = 15 slides (17%)

   # Fusionner cluster → CanonicalConcept
   canonical = CanonicalConcept(
       name="SAP S/4HANA",
       aliases=["S/4HANA", "SAP S/4HANA Cloud"],
       source_slides=[1, 5, 12, 23, ...]
   )
   # Marquer concepts comme "fusionnés"
   ```

3. **Application Règle 2 (Alternatives):**
   ```python
   # Détecter paires opposées non fusionnées
   pairs = detect_alternatives(remaining_concepts)
   # Exemple: ("Multi-Tenancy", "Single-Tenant Architecture")

   # Créer relations (pas fusion)
   for c1, c2 in pairs:
       add_relationship(c1, "alternative_to", c2)
       preserve_concept(c1)
       preserve_concept(c2)
   ```

4. **Application Règle 3 (Slide Specific):**
   ```python
   # Préserver concepts rares
   rare_concepts = [c for c in remaining_concepts
                    if len(c.metadata.get("source_slides", [])) <= 2]

   for concept in rare_concepts:
       canonical = CanonicalConcept(
           name=concept.name,
           source_slides=[concept.metadata['slide_index']],
           metadata={"frequency": "rare"}
       )
   ```

**Output:**
```python
canonical_concepts = [
    # Fusionnés (règle 1)
    CanonicalConcept("SAP S/4HANA", occurrences=15),
    CanonicalConcept("Cloud ERP", occurrences=12),

    # Alternatives (règle 2 - préservés)
    CanonicalConcept("Multi-Tenancy", occurrences=10),
    CanonicalConcept("Single-Tenant Architecture", occurrences=10),

    # Slide-specific (règle 3)
    CanonicalConcept("Response Time < 200ms (P95)", occurrences=1),
    CanonicalConcept("Database Connection Pool: 50", occurrences=1),

    # ... ~200-400 concepts canoniques (vs 28 avant)
]
```

---

## 📁 Structure Fichiers

```
src/knowbase/semantic/
├── extraction/
│   └── concept_extractor.py  (MODIF - ajout extraction_mode)
│
├── fusion/  (NOUVEAU MODULE)
│   ├── __init__.py
│   ├── smart_concept_merger.py  (Orchestrateur - 400 lignes)
│   ├── fusion_rules.py  (ABC FusionRule - 100 lignes)
│   ├── models.py  (FusionResult, FusionConfig - 50 lignes)
│   │
│   └── rules/  (Règles concrètes)
│       ├── __init__.py
│       ├── main_entities.py  (Règle 1 - 150 lignes)
│       ├── alternatives.py  (Règle 2 - 120 lignes)
│       └── slide_specific.py  (Règle 3 - 100 lignes)
│
└── config.py  (MODIF - ajout FusionConfig)

config/
└── fusion_rules.yaml  (NOUVEAU - configuration règles)

tests/semantic/fusion/
├── test_smart_merger.py  (200 lignes)
├── test_fusion_rules.py  (300 lignes)
└── test_e2e_pptx_fusion.py  (400 lignes)
```

---

## ⚙️ Configuration YAML

**Fichier:** `config/fusion_rules.yaml`

```yaml
# Configuration SmartConceptMerger
fusion:
  enabled: true

  # Document types éligibles extraction locale
  local_extraction_types:
    - PPTX
    - PPTX_SLIDES

  # Règles de fusion (ordre = priorité)
  rules:
    - name: main_entities_merge
      enabled: true
      priority: 1
      config:
        min_occurrence_ratio: 0.15  # 15% des slides minimum
        similarity_threshold: 0.88
        eligible_types:
          - ENTITY
          - PRODUCT
          - TECHNOLOGY

    - name: alternatives_features
      enabled: true
      priority: 2
      config:
        antonym_keywords:
          - "vs"
          - "versus"
          - "instead of"
          - "alternative"
          - "compared to"
        min_co_occurrence: 3  # Présents ensemble sur ≥3 slides

    - name: slide_specific_preserve
      enabled: true
      priority: 3
      config:
        max_occurrence: 2  # Préserver si ≤ 2 mentions
        preserve_types:
          - METRIC
          - DETAIL
          - TECHNICAL
          - VALUE
        min_name_length: 10  # Détails précis

  # Fallback si aucune règle appliquée
  fallback_strategy: "preserve_all"  # preserve_all | merge_similar
```

---

## 🎯 Critères de Succès

| Métrique | Baseline (Avant) | Target (Après Sprint 1.8.1d) |
|----------|------------------|------------------------------|
| **Concepts extraits (87 slides PPTX)** | 28 | 200-400 |
| **Granularité concepts** | Trop générique | Fine (slide-level) |
| **Détection alternatives** | 0% | ≥ 80% paires détectées |
| **Préservation détails techniques** | Fusionnés/perdus | 100% préservés |
| **Latence extraction** | 7.5 min | ≤ 15 min (2× acceptable) |
| **Coût extraction** | N/A | ≤ $0.15/doc (vs $0.10 baseline) |

---

## 🔄 Évolution Future (Phases 2-3)

### Phase 2: Règles Avancées (Sprint 1.8.1e)

1. **HierarchyConstructionRule**
   - Détecter relations parent/child (SAP S/4HANA → SAP)
   - Construire hiérarchies automatiques

2. **NarrativeSequenceRule**
   - Lier concepts dans ordre chronologique (étapes implémentation)
   - Préserver narratives documentaires

3. **CrossDocumentMergeRule**
   - Fusionner concepts entre documents
   - Détecter évolutions (V1.0 vs V2.0)

### Phase 3: LLM-Assisted Fusion (Sprint 1.8.1f)

- Validation LLM pour cas ambigus (fusion ou préserver ?)
- Enrichissement définitions fusionnées

---

## 📊 Diagramme Flux Données

```
┌─────────────────────────────────────────────────────────────────┐
│ ÉTAPE 1: EXTRACTION LOCALE                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Slide 0: "SAP S/4HANA..."                                     │
│    ↓                                                            │
│  ConceptExtractor(mode="local")                                │
│    ↓                                                            │
│  [Concept("SAP S/4HANA", meta={slide:0}),                     │
│   Concept("Cloud ERP", meta={slide:0}),                       │
│   ...]  ← 5 concepts                                           │
│                                                                  │
│  Slide 1: "Multi-Tenancy..."                                   │
│    ↓                                                            │
│  ConceptExtractor(mode="local")                                │
│    ↓                                                            │
│  [Concept("Multi-Tenancy", meta={slide:1}),                   │
│   ...]  ← 3 concepts                                           │
│                                                                  │
│  ... (85 autres slides)                                         │
│                                                                  │
│  TOTAL: ~500 concepts locaux                                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ ÉTAPE 2: FUSION CONTEXTUELLE (SmartConceptMerger)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Step 1: Flatten + Index                                        │
│    → [500 concepts with slide_index metadata]                   │
│                                                                  │
│  Step 2: Apply Rule 1 (MainEntitiesMergeRule)                  │
│    → Identifier: "SAP S/4HANA" répété 15× (17% slides)         │
│    → Fusionner: ["SAP S/4HANA", "S/4HANA", "S/4HANA Cloud"]   │
│    → Output: CanonicalConcept("SAP S/4HANA", occurrences=15)  │
│    → Mark 15 concepts as "merged"                               │
│                                                                  │
│  Step 3: Apply Rule 2 (AlternativesFeaturesRule)               │
│    → Detect pair: ("Multi-Tenancy", "Single-Tenant")           │
│    → NO merge, create relationship: alternative_to             │
│    → Preserve both concepts                                     │
│                                                                  │
│  Step 4: Apply Rule 3 (SlideSpecificPreserveRule)              │
│    → Identify rare concepts (≤ 2 mentions)                      │
│    → Preserve: "Response Time < 200ms (P95)" (slide 42)        │
│    → Create individual CanonicalConcept                         │
│                                                                  │
│  Step 5: Remaining concepts                                     │
│    → Fallback: preserve_all strategy                            │
│    → Create individual CanonicalConcepts                        │
│                                                                  │
│  TOTAL: ~300 canonical concepts                                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ ÉTAPE 3: STORAGE (Neo4j + Qdrant)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Neo4j Proto-KG:                                                │
│    - CanonicalConcept nodes (300)                               │
│    - Relationships (alternative_to, relates_to)                 │
│    - Metadata (source_slides, frequency)                        │
│                                                                  │
│  Qdrant:                                                        │
│    - Embeddings (300 vectors)                                   │
│    - Payload (metadata filterable)                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚨 Risques & Mitigations

| Risque | Impact | Probabilité | Mitigation |
|--------|--------|-------------|------------|
| **Latence 2× TopicSegmenter** | Moyen | Haute | Parallélisation extraction locale + cache LLM |
| **Règles trop strictes (over-preserve)** | Moyen | Moyenne | Tests A/B + tuning seuils config |
| **Règles trop laxistes (over-merge)** | Élevé | Faible | Validation LLM-as-a-Judge sur clusters |
| **Régression pipeline PDF/TXT** | Élevé | Faible | Tests non-régression exhaustifs + feature flag |
| **Complexité maintenance règles** | Faible | Moyenne | Documentation YAML + exemples clairs |

---

## ✅ Validation Design

**Questions à valider avant implémentation:**

- [ ] Architecture SmartConceptMerger couvre cas d'usage PPTX comparatif ?
- [ ] Règles MVP (3) suffisantes pour démo ?
- [ ] Configuration YAML intuitive pour non-dev ?
- [ ] Flux données clair et testable ?
- [ ] Performance acceptable (2× latence max) ?
- [ ] Extensibilité future (Phase 2-3 règles) ?

**Reviewers:**
- **Tech Lead:** [À assigner]
- **Product Owner:** [À assigner]

**Status:** 🟡 EN REVUE

---

**Prochaine étape:** T1.8.1d.2 - Implémentation ConceptExtractor mode local
