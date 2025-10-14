# 🌊 OSMOSE - NarrativeThreadDetector V2 : Spécification Architecture Cible

**Projet:** KnowWhere - OSMOSE Phase 1 (Extended)
**Composant:** NarrativeThreadDetector V2
**Status:** Architecture Cible - Spécification Technique
**Date:** 2025-10-13
**Auteur:** Architecture Review

---

## 📋 Table des Matières

1. [Contexte et Motivation](#contexte-et-motivation)
2. [Vision Cible V2](#vision-cible-v2)
3. [Architecture Technique](#architecture-technique)
4. [Data Model Proto-KG](#data-model-proto-kg)
5. [Performance et Optimisation](#performance-et-optimisation)
6. [Plan d'Implémentation](#plan-dimplémentation)
7. [Critères de Succès](#critères-de-succès)

---

## 📋 Contexte et Motivation

### Problèmes Identifiés V1 (Implémentation Actuelle)

#### 1. Scan Global Naïf

**Code actuel** (`narrative_detector.py:124`):
```python
pattern = rf'([^.!?]*)\b{re.escape(connector)}\b([^.!?]*[.!?])'
matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))
```

**Problèmes:**
- ❌ Scan sur **tout le texte** d'un coup (1.3M chars pour 650 pages)
- ❌ Un seul thread créé par type de connecteur → span de 650 pages
- ❌ Performance: >30s juste pour regex sur longs docs
- ❌ Pas de compréhension contextuelle (Finance vs Supply Chain vs HR)

**Exemple concret:**
```
Document 650 pages contient "because" 247 fois:
- Page 3 (Finance): "CRR changed BECAUSE..."
- Page 89 (Supply Chain): "OEE improved BECAUSE..."
- Page 178 (HR): "Retention changed BECAUSE..."

V1 crée: 1 thread (page 3 → page 178) 🚨
→ Mélange 3 narratives distinctes !
```

---

#### 2. PPTX Visuels Ignorés

**V1 actuelle:**
```python
# Extraction texte uniquement via MegaParse
text_content = megaparse.extract_text(pptx_file)
# Graphiques, charts, timelines visuelles = PERDUS
```

**Impact:**
```
Présentation "CRR Evolution Q1-Q4 2023.pptx":
- Slide 5: Graphique évolution CRR (72% → 75% → 78% → 82%)
- Slide 12: Timeline "v1.0 (2022) → v2.0 (2023) → v3.0 (2024)"
- Slide 18: Diagramme causal "Nouvelle méthodologie → +6% CRR"

Texte extrait: ~500 chars (titres + notes)
Connecteurs causaux: 0
Marqueurs temporels: 0

→ Aucun thread détecté 🚨
→ KILLER FEATURE inopérante sur PPTX
```

---

#### 3. Multiples Narratives Confondues

**V1 crée une seule séquence par connecteur** (`narrative_detector.py:141-154`):
```python
if len(matches) >= 2:  # Au moins 2 occurrences
    sequence = {
        "start_pos": matches[0].start(),    # Premier match
        "end_pos": matches[-1].end()         # Dernier match
        # → Tout ce qui est entre = inclus dans le thread !
    }
```

**Conséquence:**
- Thread A (CRR Finance) + Thread B (OEE Supply Chain) = **fusionnés**
- Keywords mélangés: ["CRR", "Finance", "OEE", "Supply", "Chain"]
- Confidence artificiellement haute (9 occurrences de "because")

---

#### 4. Enrichissement LLM Inadéquat

**V1 limite** (`narrative_detector.py:266`):
```python
context = text[thread.start_position:thread.end_position]
if len(context) > 1500:
    context = context[:1500] + "..."
```

**Problème:**
```
Thread span: 95,000 chars (50 pages)
LLM voit: 1,500 chars (1.6% du contexte)

→ LLM conclut: "CRR evolution"
→ Thread contient AUSSI (non vu): OEE, HR retention
→ Faux positif majeur
```

---

#### 5. Multilinguisme Non Supporté

**V1 hardcodé anglais** (`config.py:34-41`):
```python
causal_connectors: List[str] = [
    "because", "therefore", "as a result"
]
temporal_markers: List[str] = [
    "revised", "updated", "replaced"
]
```

**Impact:**
- Documents français/allemands/italiens: 0 détection
- Marché SAP international = non adressable

---

## 🎯 Vision Cible V2 : Architecture Narrative-as-Events

### Principes Fondamentaux

```
┌──────────────────────────────────────────────────────┐
│ V1 (Naïve)                                           │
│ Text → Regex Global → Thread → LLM Enrich           │
│                                                      │
│ Problèmes: Pas de contexte, pas de structure        │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ V2 (Intelligente)                                    │
│ Text → Topics → Events → Threads → Timeline         │
│        ↓        ↓        ↓         ↓                 │
│     Cluster  Anchored  Graph    Ordered             │
│                                                      │
│ Avantages: Contextuel, structuré, sémantique        │
└──────────────────────────────────────────────────────┘
```

### Pipeline Complet V2

```
Document (650 pages, 1.3M chars)
    ↓
┌─────────────────────────────────────────┐
│ 1. TOPIC SEGMENTATION                   │
│    - Structural (sections, pages)       │
│    - Semantic windowing (3000 chars)    │
│    - Embeddings clustering              │
│    - Anchor extraction (NER + TF-IDF)   │
│                                          │
│ Output: Topics [{id, windows, anchors}] │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ 2. EVENT EXTRACTION                      │
│    - Pattern-based (regex temporal)     │
│    - LLM-based (structured output)      │
│    - Vision-based (PPTX charts)         │
│    - Validation (evidence + anchors)    │
│                                          │
│ Output: Events [{entity, change, date}] │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ 3. THREAD CONSTRUCTION                   │
│    - Group by (topic, entity)           │
│    - Temporal ordering                  │
│    - Relation building (causes, etc.)   │
│    - Timeline generation                │
│                                          │
│ Output: Threads [{events, relations}]   │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ 4. CROSS-DOCUMENT FUSION                 │
│    - Entity canonicalization            │
│    - Event deduplication                │
│    - Conflict resolution                │
│    - Master timeline                    │
│                                          │
│ Output: Cross-Doc Threads               │
└─────────────────────────────────────────┘
```

---

## 🏗️ Architecture Technique Détaillée

### 1. TopicSegmenter

**Objectif:** Découper document en topics sémantiquement cohérents

**Algorithme:**

```python
class TopicSegmenter:
    """Segmente documents en topics avec clustering sémantique"""

    async def segment_document(
        self,
        document: Document,
        config: SegmentationConfig
    ) -> List[Topic]:
        """
        1. Extraction sections (via MegaParse headers)
        2. Windowing (3000 chars, 25% overlap)
        3. Embeddings (OpenAI text-embedding-3-small)
        4. Clustering (HDBSCAN)
        5. Anchor extraction (NER + TF-IDF)
        """

        # 1. Sections structurelles
        sections = self._extract_sections(document)

        all_topics = []
        for section in sections:
            # 2. Windows
            windows = self._create_windows(
                section.text,
                size=3000,
                overlap=0.25
            )

            # 3. Embeddings (parallèle)
            embeddings = await self.embedder.embed_batch(
                [w.text for w in windows]
            )

            # 4. Clustering
            clusters = self.clusterer.cluster(embeddings)

            # 5. Topics
            for cluster_id, cluster_windows in clusters.items():
                anchors = self._extract_anchors(cluster_windows)
                cohesion = self._calculate_cohesion(embeddings)

                topic = Topic(
                    topic_id=f"{section.id}_cluster_{cluster_id}",
                    section_path=section.path,
                    windows=cluster_windows,
                    anchors=anchors,
                    cohesion_score=cohesion
                )
                all_topics.append(topic)

        return all_topics
```

**Exemple Output:**
```python
Topic(
    topic_id="sec_3_2_cluster_0",
    section_path="3.2 Financial Metrics / 3.2.1 CRR Methodology",
    windows=[
        Window(text="CRR calculation methodology...", start=15000, end=18000),
        Window(text="Updated formula ISO 23592...", start=17500, end=20500),
        # ... 8 more windows
    ],
    anchors=["CRR", "Customer Retention Rate", "ISO 23592", "formula"],
    cohesion_score=0.82
)
```

**Bénéfices:**
- ✅ Threads limités à un topic → pas de pollution
- ✅ Anchors permettent filtrage (seuls windows pertinents)
- ✅ Cohesion = métrique qualité

---

### 2. EventExtractor

**Objectif:** Transformer topics en événements structurés

**Schema Event:**
```python
@dataclass
class NarrativeEvent:
    """Événement normalisé"""

    # ID
    event_id: str
    topic_id: str

    # Entity
    entity: str                      # "CRR", "Methodology"
    entity_type: str                 # "METRIC", "PROCESS", "STANDARD"

    # Change
    change_type: str                 # "INTRODUCED", "UPDATED", "DEPRECATED"
    value_before: Optional[str]      # "v1.0", "72%"
    value_after: Optional[str]       # "v2.0", "82%"

    # Temporality
    date: Optional[str]              # "2023-03-15", "Q3 2023"
    date_precision: str              # "EXACT", "QUARTER", "YEAR"

    # Causality
    cause: Optional[str]             # "ISO compliance required"
    cause_type: Optional[str]        # "REGULATORY", "BUSINESS"

    # Evidence
    evidence_spans: List[Span]       # Positions exactes
    evidence_strength: float         # 0.0-1.0

    # Metadata
    confidence: float
    extraction_method: str           # "PATTERN", "LLM", "VISION"
    source_document: str
```

**Pipeline Extraction:**

```python
class EventExtractor:
    """Extrait events via 3 méthodes complémentaires"""

    async def extract_events(
        self,
        topic: Topic,
        document: Document
    ) -> List[NarrativeEvent]:
        events = []

        # 1. Pattern-based (rapide, haute précision)
        pattern_events = self.pattern_extractor.extract(topic)
        events.extend(pattern_events)

        # 2. LLM-based (contexte, haute recall)
        if len(pattern_events) < MIN_EVENTS_THRESHOLD:
            llm_events = await self.llm_extractor.extract(topic)
            events.extend(llm_events)

        # 3. Vision-based (PPTX uniquement)
        if document.type == "PPTX":
            vision_events = await self.vision_extractor.extract(topic, document)
            events.extend(vision_events)

        # 4. Validation
        events = self._validate_events(events, topic)
        events = self._deduplicate_events(events)

        return events
```

#### 2.1 PatternBasedExtractor

**Patterns supportés:**

```python
# Temporal patterns
r'(?P<entity>\w+)\s+(?P<marker>updated|revised|changed)\s+(?:in|on)\s+(?P<date>\d{4}[-/]\d{2}[-/]\d{2}|\d{4}|Q[1-4]\s+\d{4})'

# Version patterns
r'v(?P<v_before>[\d.]+)\s*(?:→|->|to)\s*v(?P<v_after>[\d.]+)'

# Causal patterns (avec anchor)
r'(?P<entity>\w+)\s+(?P<change>improved|changed|decreased)\s+because\s+(?P<cause>[^.!?]+)'

# Value change patterns
r'(?P<entity>\w+)\s+(?:increased|decreased|changed)\s+from\s+(?P<val_before>[\d.]+%?)\s+to\s+(?P<val_after>[\d.]+%?)'
```

**Exemple détection:**
```
Text: "CRR formula updated in March 2023 to comply with ISO 23592"

Pattern match:
  entity: "CRR"
  marker: "updated"
  date: "March 2023"

Event créé:
NarrativeEvent(
    entity="CRR",
    change_type="UPDATED",
    date="2023-03",
    date_precision="MONTH",
    cause="ISO 23592 compliance",
    evidence_spans=[Span(start=15000, end=15080)],
    extraction_method="PATTERN",
    confidence=0.85
)
```

#### 2.2 LLMBasedExtractor

**Prompt structuré:**

```python
prompt = f"""
Analyze this document section about: {", ".join(topic.anchors)}

Extract narrative events (changes, updates, evolutions).

Context:
\"\"\"
{context}
\"\"\"

For each event, identify:
1. Entity (what changed): metric name, process, standard
2. Change type: INTRODUCED | UPDATED | REVISED | DEPRECATED | INCREASED | DECREASED
3. Values before/after (if mentioned)
4. Date or time period
5. Cause (if mentioned)
6. Evidence (exact quote)

Return JSON array:
[
  {{
    "entity": "<name>",
    "entity_type": "METRIC|PROCESS|STANDARD",
    "change_type": "<type>",
    "value_before": "<value or null>",
    "value_after": "<value or null>",
    "date": "<date or null>",
    "cause": "<cause or null>",
    "evidence": "<exact quote>"
  }}
]

JSON:"""

response = await llm.complete(prompt, temperature=0.2)
```

**Avantages LLM:**
- ✅ Comprend paraphrases ("formula was revised" = "methodology updated")
- ✅ Extrait causalité implicite
- ✅ Gère contexte multi-phrases
- ✅ Multilang (fonctionne sur FR/DE/IT)

#### 2.3 VisionBasedExtractor (PPTX)

**Objectif:** Extraire narratives des graphiques/charts

**Pipeline PPTX:**

```python
async def extract_pptx_events(
    self,
    topic: Topic,
    document: PPTXDocument
) -> List[NarrativeEvent]:

    events = []

    # 1. Trouver slides candidates
    candidate_slides = self._find_vision_candidates(document, topic)

    # 2. Pour chaque slide (max 3)
    for slide in candidate_slides[:3]:

        # 2a. Tenter parse XML chart
        chart_data = self._try_parse_chart_xml(slide)

        if chart_data:
            # XML disponible → extraction directe
            slide_events = self._events_from_chart_data(chart_data, topic)
        else:
            # Pas de XML → Vision LLM
            slide_events = await self._extract_with_vision(slide, topic)

        events.extend(slide_events)

    return events
```

**XML Chart Parsing:**

```python
def _parse_chart_xml(slide: Slide) -> Optional[ChartData]:
    """
    Parse XML chart PPTX (python-pptx)

    Supporte:
    - Bar charts
    - Line charts
    - Combo charts
    - Tables
    """
    if not slide.has_chart:
        return None

    chart = slide.shapes[0].chart  # Assume first chart

    # Extraire séries
    series_data = []
    for series in chart.series:
        values = [(cat, val) for cat, val in zip(
            chart.categories,
            series.values
        )]
        series_data.append({
            "name": series.name,
            "values": values
        })

    return ChartData(
        type=chart.chart_type,
        title=chart.chart_title.text if chart.has_title else "",
        series=series_data,
        x_axis_title=chart.value_axis.axis_title.text,
        y_axis_title=chart.category_axis.axis_title.text
    )
```

**Vision LLM (si XML absent):**

```python
async def _extract_with_vision(
    self,
    slide: Slide,
    topic: Topic
) -> List[NarrativeEvent]:
    """Extraction multimodale via GPT-4V"""

    # Render slide en image
    image = self._render_slide(slide, size=(1024, 1024))

    prompt = f"""
Analyze this slide about: {", ".join(topic.anchors)}

Title: {slide.title}
Notes: {slide.notes or "None"}

Extract timeline/evolution data:
1. Metric or entity name
2. Time points (dates, quarters, years)
3. Values at each point
4. Changes (increases, decreases)
5. Causes (if annotated)

Return JSON:
{{
  "entity": "<name>",
  "timeline": [
    {{"period": "Q1 2023", "value": "72%"}},
    {{"period": "Q2 2023", "value": "78%"}}
  ],
  "changes": [
    {{
      "from": "Q1 2023",
      "to": "Q2 2023",
      "value_before": "72%",
      "value_after": "78%",
      "change": "+6%",
      "cause": "v2.0 methodology"
    }}
  ]
}}

JSON:"""

    response = await llm_vision.complete(
        prompt,
        image=image,
        model="gpt-4o",
        temperature=0.2
    )

    # Build events
    data = json.loads(response)
    return self._build_events_from_vision(data, topic, slide)
```

**Cost Control:**

```python
def _find_vision_candidates(
    self,
    document: PPTXDocument,
    topic: Topic
) -> List[Slide]:
    """
    Sélection intelligente slides pour vision

    Critères:
    1. Title contient topic anchors
    2. Title contient keywords: evolution, trend, timeline
    3. Slide contient chart/image
    """
    candidates = []

    for slide in document.slides:
        # Anchors ?
        if not any(a.lower() in slide.title.lower() for a in topic.anchors):
            continue

        # Evolution keywords ?
        keywords = ["evolution", "trend", "timeline", "change",
                    "Q1", "Q2", "Q3", "Q4", "2022", "2023", "2024"]
        if not any(k in slide.title.lower() for k in keywords):
            continue

        # Visual content ?
        if not (slide.has_chart or slide.has_image):
            continue

        candidates.append(slide)

    # Top 3 par relevance score
    return sorted(candidates, key=lambda s: self._relevance_score(s, topic))[:3]
```

**Coût par deck:**
```
45 slides PPTX
→ 8 candidates (keywords match)
→ 3 processed (cap)
→ 3 × $0.013 (GPT-4V) = $0.039/deck

Acceptable ✅
```

---

### 3. ThreadBuilder

**Objectif:** Construire fils narratifs à partir d'événements

**Algorithme:**

```python
class ThreadBuilder:
    """Construit threads = graphes d'événements"""

    def build_threads(
        self,
        events: List[NarrativeEvent],
        topics: List[Topic]
    ) -> List[NarrativeThread]:

        # 1. Grouper par (topic, entity canonique)
        grouped = self._group_events(events)

        # 2. Construire thread par groupe
        threads = []
        for (topic_id, entity), group_events in grouped.items():
            thread = self._build_single_thread(
                topic_id,
                entity,
                group_events
            )
            threads.append(thread)

        return threads

    def _build_single_thread(
        self,
        topic_id: str,
        entity: str,
        events: List[NarrativeEvent]
    ) -> NarrativeThread:

        # 1. Tri chronologique
        sorted_events = self.temporal_reasoner.sort(events)

        # 2. Identifier relations
        relations = []
        for i, event_a in enumerate(sorted_events):
            for event_b in sorted_events[i+1:]:

                # Temporal: dates ordonnées ?
                if self._precedes(event_a, event_b):
                    relations.append(("PRECEDES", event_a, event_b))

                # Causal: mention dans cause ?
                if event_a.entity in (event_b.cause or ""):
                    relations.append(("CAUSES", event_a, event_b))

                # Evolution: versions compatibles ?
                if self._is_evolution(event_a, event_b):
                    relations.append(("EVOLVES_TO", event_a, event_b))

        # 3. Timeline
        timeline = self._build_timeline(sorted_events, relations)

        return NarrativeThread(
            thread_id=f"thread_{topic_id}_{entity}",
            topic_id=topic_id,
            entity=entity,
            events=sorted_events,
            relations=relations,
            timeline=timeline,
            confidence=mean([e.confidence for e in sorted_events])
        )
```

**Exemple Thread:**

```python
NarrativeThread(
    thread_id="thread_sec_3_2_cluster_0_CRR",
    topic_id="sec_3_2_cluster_0",
    entity="Customer Retention Rate",

    events=[
        NarrativeEvent(
            entity="CRR",
            change_type="INTRODUCED",
            value_after="v1.0",
            date="2022-01-15"
        ),
        NarrativeEvent(
            entity="CRR",
            change_type="UPDATED",
            value_before="v1.0",
            value_after="v2.0",
            date="2023-03-15",
            cause="ISO 23592 compliance"
        ),
        NarrativeEvent(
            entity="CRR",
            change_type="INCREASED",
            value_before="72%",
            value_after="82%",
            date="2023-Q3",
            cause="v2.0 methodology",
            extraction_method="VISION"
        )
    ],

    relations=[
        ("PRECEDES", event[0], event[1]),
        ("EVOLVES_TO", event[0], event[1]),
        ("PRECEDES", event[1], event[2]),
        ("CAUSES", event[1], event[2])
    ],

    timeline={
        "2022-01-15": "CRR v1.0 Introduced",
        "2023-03-15": "CRR v2.0 Updated (cause: ISO compliance)",
        "2023-Q3": "CRR Increased 72% → 82% (cause: v2.0)"
    },

    confidence=0.86
)
```

---

### 4. CrossDocumentFusion

**Objectif:** Fusionner threads de documents multiples

**Pipeline:**

```python
class CrossDocumentFusion:
    """Fusionne threads cross-documents"""

    def fuse_threads(
        self,
        threads_by_doc: Dict[str, List[NarrativeThread]]
    ) -> List[NarrativeThread]:

        # 1. Extraire tous threads
        all_threads = []
        for doc_id, threads in threads_by_doc.items():
            for thread in threads:
                thread.source_document_id = doc_id
                all_threads.append(thread)

        # 2. Canonicaliser entities
        for thread in all_threads:
            thread.entity_canonical = self.entity_linker.canonicalize(
                thread.entity
            )

        # 3. Grouper par entity canonique
        grouped = defaultdict(list)
        for thread in all_threads:
            grouped[thread.entity_canonical].append(thread)

        # 4. Fusionner chaque groupe
        master_threads = []
        for entity, threads in grouped.items():
            if len(threads) == 1:
                # Pas de fusion nécessaire
                master_threads.append(threads[0])
            else:
                # Fusionner
                master = self._fuse_entity_threads(entity, threads)
                master_threads.append(master)

        return master_threads

    def _fuse_entity_threads(
        self,
        entity: str,
        threads: List[NarrativeThread]
    ) -> NarrativeThread:

        # 1. Fusionner tous events
        all_events = []
        for thread in threads:
            all_events.extend(thread.events)

        # 2. Dédupliquer events (même date + valeur)
        unique_events = self._deduplicate_events(all_events)

        # 3. Résoudre conflits (dates identiques, valeurs différentes)
        resolved_events = self.conflict_resolver.resolve(unique_events)

        # 4. Tri chronologique
        sorted_events = sorted(resolved_events, key=lambda e: e.date or "")

        # 5. Rebuild relations
        relations = self._rebuild_relations(sorted_events)

        # 6. Master timeline
        timeline = self._build_master_timeline(sorted_events)

        # 7. Provenance
        source_docs = list(set(e.source_document for e in sorted_events))

        return NarrativeThread(
            thread_id=f"master_{entity}",
            entity=entity,
            events=sorted_events,
            relations=relations,
            timeline=timeline,
            confidence=mean([e.confidence for e in sorted_events]),
            source_documents=source_docs,
            is_cross_document=True
        )
```

**Entity Canonicalization:**

```python
class EntityLinker:
    """Résout aliases et normalise entities"""

    ALIASES = {
        "Customer Retention Rate": ["CRR", "customer retention", "retention rate"],
        "ISO 23592": ["ISO23592", "ISO standard 23592"],
        # ... patterns communs
    }

    def canonicalize(self, entity: str) -> str:
        """
        Normalise entity name

        CRR → Customer Retention Rate
        customer retention → Customer Retention Rate
        """
        entity_lower = entity.lower()

        # Check aliases
        for canonical, aliases in self.ALIASES.items():
            if entity_lower in [a.lower() for a in aliases]:
                return canonical

        # LLM fallback (si pas dans dict)
        # ...

        return entity.title()
```

---

## 🗄️ Data Model Proto-KG

### Neo4j Schema

```cypher
// ==========================================
// NARRATIVE INTELLIGENCE - Proto-KG Schema
// ==========================================

// --- Topics ---
CREATE CONSTRAINT topic_id_unique IF NOT EXISTS
FOR (t:NarrativeTopic) REQUIRE t.topic_id IS UNIQUE;

(:NarrativeTopic {
    topic_id: String,
    section_path: String,
    anchors: [String],
    cohesion_score: Float,
    tenant_id: String,
    created_at: DateTime
})

// --- Events (Candidates) ---
CREATE CONSTRAINT event_candidate_id_unique IF NOT EXISTS
FOR (e:EventCandidate) REQUIRE e.candidate_id IS UNIQUE;

(:EventCandidate {
    candidate_id: String,
    topic_id: String,

    // Entity
    entity: String,
    entity_type: String,

    // Change
    change_type: String,
    value_before: String?,
    value_after: String?,

    // Temporality
    date: String?,
    date_precision: String,

    // Causality
    cause: String?,
    cause_type: String?,

    // Evidence
    evidence_spans: [Map],
    evidence_strength: Float,

    // Metadata
    confidence: Float,
    extraction_method: String,
    source_document: String,

    // Gate status
    status: String,
    tenant_id: String,
    created_at: DateTime
})

// --- Relations ---

// Topic containment
(:EventCandidate)-[:IN_TOPIC]->(:NarrativeTopic)

// Temporal
(:EventCandidate)-[:PRECEDES {confidence: Float}]->(:EventCandidate)

// Causal
(:EventCandidate)-[:CAUSES {evidence: String, confidence: Float}]->(:EventCandidate)

// Evolution
(:EventCandidate)-[:EVOLVES_TO {from: String, to: String}]->(:EventCandidate)

// Cross-doc linking
(:EventCandidate)-[:SAME_AS {similarity: Float}]->(:EventCandidate)

// Provenance
(:EventCandidate)-[:EXTRACTED_FROM]->(:Document)
(:NarrativeTopic)-[:DERIVED_FROM]->(:Document)

// --- Published Events (after Gate) ---
CREATE CONSTRAINT event_id_unique IF NOT EXISTS
FOR (e:Event) REQUIRE e.event_id IS UNIQUE;

(:Event {
    // Same schema as EventCandidate
    promoted_at: DateTime,
    promoted_by: String
})

(:Event)-[:PROMOTED_FROM]->(:EventCandidate)
```

### Qdrant Payload

```python
{
    "collection": "knowwhere_proto",
    "payload": {
        # Existing fields...

        # Narrative-specific
        "narrative_events": [
            {
                "event_id": "evt_123",
                "entity": "CRR",
                "change_type": "UPDATED",
                "date": "2023-03-15"
            }
        ],
        "narrative_topics": [
            {
                "topic_id": "topic_abc",
                "anchors": ["CRR", "ISO 23592"]
            }
        ],
        "has_narrative_thread": True,
        "narrative_confidence": 0.86
    }
}
```

---

## ⚡ Performance et Optimisation

### Multi-Threading Parallèle

```python
import asyncio

class ParallelNarrativeDetector:
    """Détection parallèle agressive"""

    async def process_multiple_documents(
        self,
        documents: List[Document]
    ) -> Dict[str, List[NarrativeThread]]:

        # 1. Segmentation parallèle (par doc)
        segmentation_tasks = [
            self.topic_segmenter.segment_document(doc)
            for doc in documents
        ]
        topics_by_doc = await asyncio.gather(*segmentation_tasks)

        # 2. Extraction parallèle (par topic)
        all_topics = []
        doc_mapping = {}
        for doc, topics in zip(documents, topics_by_doc):
            for topic in topics:
                all_topics.append((doc, topic))

        extraction_tasks = [
            self.event_extractor.extract_events(topic, doc)
            for doc, topic in all_topics
        ]
        events_by_topic = await asyncio.gather(*extraction_tasks)

        # 3. Thread building (par doc)
        threads_by_doc = {}
        for doc, topics in zip(documents, topics_by_doc):
            doc_events = [e for topic_events in events_by_topic for e in topic_events]
            threads = self.thread_builder.build_threads(doc_events, topics)
            threads_by_doc[doc.id] = threads

        return threads_by_doc
```

### Performance Targets

**Document 650 pages:**

```
Pipeline V2 (parallèle):

1. Segmentation: 15s
   - Structural: 2s
   - Windows: 1s
   - Embeddings (batch API): 10s
   - Clustering: 2s

2. Event Extraction: 12s (parallel)
   - Pattern: 3s
   - LLM (parallel 10 topics): 8s
   - Vision (3 slides): 5s

3. Thread Building: 4s
   - Grouping: 1s
   - Relations: 2s
   - Timeline: 1s

4. Neo4j Staging: 2s

Total: ~33s (< 45s target ✅)
```

**Cost per Document:**
```
Embeddings: $0.003
LLM Extraction: $0.007
Vision (PPTX): $0.039

Total: ~$0.05 / doc (< $2.00 budget ✅)
```

---

## 📅 Plan d'Implémentation

### Phase 1 : Fondations (Semaines 7-9)

**Semaine 7 : TopicSegmenter**
- Classe TopicSegmenter
- Structural + Semantic windowing
- Embeddings + HDBSCAN clustering
- Anchor extraction
- Tests 100-200 pages

**Semaine 8 : EventExtractor (Pattern + LLM)**
- Classe EventExtractor
- PatternBasedExtractor
- LLMBasedExtractor
- Validation + dedup
- Tests extraction

**Semaine 9 : ThreadBuilder**
- Classe ThreadBuilder
- Grouping + ordering
- Relation identification
- Timeline construction
- Tests threads

### Phase 2 : PPTX et Cross-Doc (Semaines 10-11)

**Semaine 10 : VisionBasedExtractor**
- Chart XML parsing
- Vision candidate detection
- GPT-4V integration
- Cost control
- Tests PPTX

**Semaine 11 : CrossDocumentFusion**
- Entity canonicalization
- Event deduplication
- Conflict resolution
- Master thread
- Tests fusion

### Phase 3 : Proto-KG et Qualité (Semaines 12-13)

**Semaine 12 : Neo4j Integration**
- Schema update
- Staging implementation
- Relation creation
- Query narratives
- Tests integration

**Semaine 13 : Quality & Multilang**
- Multilingual patterns
- Language detection
- Quality metrics
- Tests multilang
- Performance benchmarks

### Phase 4 : Démo (Semaine 14)

**Semaine 14 : CRR Evolution Demo**
- Test end-to-end
- Démo script
- Timeline visualization
- Copilot comparison
- Documentation

---

## 🎯 Critères de Succès

### Métriques Techniques

| Métrique | Target | Validation |
|----------|--------|------------|
| Precision événements | ≥85% | Échantillon 50 docs |
| Recall événements | ≥80% | Docs annotés |
| Timeline accuracy | ≥90% | Ordre chronologique |
| Cross-doc linking | ≥75% | Entité reliée |
| Performance | <45s/doc | p95 sur 600 pages |
| Cost | <$0.10/doc | Moyenne 100 docs |
| PPTX coverage | ≥70% | % decks avec events |

### USP Démo

**Query:** "Comment CRR a-t-elle évolué dans nos documents ?"

**Response attendue:**

```
CRR Evolution Timeline (2022-2023)

2022-01-15 │ CRR v1.0 Introduced
           │ Formula: Simple average
           │ Source: [Doc1, p.12]
           │
2022-11-20 │ Audit Identified Gap
           │ Finding: v1.0 lacks ISO 23592
           │ Source: [Doc3, p.287]
           │ ↓ [CAUSES]
           │
2023-03-15 │ CRR v2.0 Updated
           │ Formula: ISO 23592 weighted
           │ Cause: Compliance + audit
           │ Source: [Doc2, p.5]
           │ ↓ [CAUSES]
           │
2023-Q3    │ CRR Performance Improved
           │ Value: 72% → 82% (+10%)
           │ Cause: v2.0 methodology
           │ Source: [Doc4, Slide 5 - Chart]

✅ 4 événements détectés
✅ 2 relations causales
✅ 4 sources (PDF + PPTX)
✅ Confidence: 0.88
```

**vs Copilot:** Pas de timeline, pas de causalité, pas de vision PPTX

---

## 📚 Dépendances

### Libraries

```python
# requirements.txt additions

# Clustering
hdbscan>=0.8.33
scikit-learn>=1.3.0

# NER
spacy>=3.7.0
en_core_web_sm>=3.7.0
fr_core_news_sm>=3.7.0
de_core_news_sm>=3.7.0

# PPTX
python-pptx>=0.6.23

# Vision
pillow>=10.0.0
```

---

**🌊 OSMOSE V2 : "Du pattern matching naïf à l'intelligence narrative."**

**Status:** Spécification Technique - Ready for Implementation
**Next:** Review + Validation Plan
