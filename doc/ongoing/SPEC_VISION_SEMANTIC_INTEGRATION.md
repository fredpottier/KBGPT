# SPEC : Vision Semantic Integration pour Pipeline V2

**Statut**: VALIDÉ (ChatGPT + Claude)
**Date**: 2026-01-24
**Contexte**: Résolution du gap Vision dans Pipeline V2

---

## Problème Identifié

Le POC Lecture Stratifiée a validé Pass 1 sur du texte simple (PyMuPDF), mais le pipeline de production utilise Docling + Vision Gating. Le cache V2 actuel produit :

- `FIGURE_TEXT` chunks avec `text: ""` (vide)
- `vision_results[]` avec des éléments géométriques (pas de texte sémantique)

**Pass 1 attend du TEXTE.** Les chunks vides cassent le contrat.

---

## Décision Architecture

**Option retenue : Vision Semantic Reader intégré dans Pass 0**

Le chemin Vision produit désormais du TEXTE SÉMANTIQUE (pas de géométrie). Pass 1 reste inchangé dans son contrat textuel.

---

## Mise à jour ADR requise

L'ADR `ARCH_STRATIFIED_PIPELINE_V2.md` doit être mis à jour :

```diff
- PASS 0 : Extraction + Structural Graph (Docling + Vision Gating - INCHANGÉ)
+ PASS 0 : Extraction + Structural Graph (Docling + Vision Semantic Reader)
+
+ Le chemin Vision produit désormais du TEXTE SÉMANTIQUE (pas de géométrie).
+ Contrat : tous les chunks ont du texte exploitable.
```

---

## Invariants Pass 0 V2

| # | Invariant | Conséquence |
|---|-----------|-------------|
| I1 | **Aucun chunk vide** | `chunk.text != ""` toujours |
| I2 | **DocItem atomique** | 1 DocItem = 1 item Docling OU 1 `vision_page` explicite |
| I3 | **Ancrage obligatoire** | Tout chunk a `docitem_ids[]` non vide |
| I4 | **Traçabilité origine** | `text_origin: docling | vision_semantic | ocr | placeholder` |
| I5 | **Vision = texte descriptif** | Pas d'assertions pré-promues depuis Vision |

---

## Enums

```python
class TextOrigin(str, Enum):
    """Origine du texte dans un DocItem/Chunk."""
    DOCLING = "docling"              # Extraction Docling native
    VISION_SEMANTIC = "vision_semantic"  # GPT-4o Vision interpretation
    OCR = "ocr"                      # Fallback OCR basique
    PLACEHOLDER = "placeholder"      # Échec total, placeholder non vide

class DocItemType(str, Enum):
    """Types de DocItem atomiques."""
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE = "table"
    TABLE_ROW = "table_row"
    FIGURE = "figure"
    FIGURE_CAPTION = "figure_caption"
    VISION_PAGE = "vision_page"      # NOUVEAU: page interprétée par Vision

class VisionFailureReason(str, Enum):
    """Raisons d'échec Vision."""
    VISION_TIMEOUT = "vision_timeout"
    VISION_RATE_LIMIT = "vision_rate_limit"
    VISION_PARSE_ERROR = "vision_parse_error"
    OCR_FAILED = "ocr_failed"
    IMAGE_UNREADABLE = "image_unreadable"
```

---

## Interfaces

```python
@dataclass
class VisionSemanticResult:
    """Sortie du Vision Semantic Reader."""
    page_no: int

    # TEXTE PRINCIPAL (obligatoire, jamais vide)
    semantic_text: str  # 2-8 phrases, factuel/observable
    text_origin: TextOrigin

    # Métadonnées audit
    diagram_type: Optional[str]  # "architecture_diagram", "flowchart", etc.
    confidence: float
    key_entities: List[str]

    # Traçabilité (pour cache/replay)
    model: str  # "gpt-4o"
    prompt_version: str  # "v1.0"
    image_hash: str  # SHA256 de l'image source

    # Optionnel: hints pour Pass 1 (jamais promues directement)
    candidate_hints: Optional[List[str]] = None

    # En cas d'échec partiel
    failure_reason: Optional[VisionFailureReason] = None


@dataclass
class DocItemV3:
    """DocItem atomique pour Cache V3."""
    id: str
    type: DocItemType
    text: str  # JAMAIS VIDE
    text_origin: TextOrigin
    page_no: int
    section_id: Optional[str]

    # Si origin = vision_semantic
    vision_metadata: Optional[Dict] = None


@dataclass
class ChunkV3:
    """Chunk pour Cache V3."""
    chunk_id: str
    text: str  # JAMAIS VIDE
    kind: ChunkKind  # NARRATIVE_TEXT, TABLE_TEXT, FIGURE_TEXT
    text_origin: TextOrigin
    page_no: int
    section_id: Optional[str]
    docitem_ids: List[str]  # JAMAIS VIDE
```

---

## Fallback Strategy (3 tiers)

```
Page Image
    │
    ▼
┌─────────────┐
│ GPT-4o Call │──── Success ────────────────────────┐
└──────┬──────┘                                     │
       │ Fail/Timeout                               │
       ▼                                            │
┌─────────────┐                                     │
│ Retry (1x)  │──── Success ────────────────────┐   │
└──────┬──────┘                                 │   │
       │ Fail                                   │   │
       ▼                                        │   │
┌─────────────┐                                 │   │
│ OCR Basic   │──── Success ────────────────┐   │   │
│ + Formatter │                             │   │   │
└──────┬──────┘                             │   │   │
       │ Fail                               │   │   │
       ▼                                    ▼   ▼   ▼
┌─────────────┐                        ┌────────────────┐
│ Placeholder │───────────────────────▶│ DocItem + Chunk│
│ + Log       │                        │ avec TEXTE     │
└─────────────┘                        └────────────────┘
```

**Placeholder standard** : `"[VISUAL_CONTENT: Page {n} - interpretation unavailable]"`

---

## Format Cache V3

```json
{
  "cache_version": "v3",
  "pipeline_version": "stratified_v2",
  "created_at": "2026-01-24T...",
  "document_id": "...",
  "source_file_hash": "...",

  "extraction": {
    "document_id": "...",
    "title": "SAP S/4HANA Upgrade Guide",
    "language": "en",
    "page_count": 42,

    "full_text": "...",

    "structural_graph": {
      "sections": [...],

      "doc_items": [
        {
          "id": "docitem_001",
          "type": "paragraph",
          "text": "Read this guide carefully...",
          "text_origin": "docling",
          "page_no": 1,
          "section_id": "sec_001"
        },
        {
          "id": "docitem_015",
          "type": "vision_page",
          "text": "Ce diagramme illustre l'architecture...",
          "text_origin": "vision_semantic",
          "page_no": 5,
          "section_id": "sec_003",
          "vision_metadata": {
            "diagram_type": "architecture_diagram",
            "confidence": 0.92,
            "key_entities": ["SAP S/4HANA", "Fiori", "HANA DB"],
            "model": "gpt-4o",
            "prompt_version": "v1.0",
            "image_hash": "a1b2c3..."
          }
        }
      ],

      "chunks": [
        {
          "chunk_id": "chunk_001",
          "text": "Read this guide carefully...",
          "kind": "NARRATIVE_TEXT",
          "text_origin": "docling",
          "page_no": 1,
          "docitem_ids": ["docitem_001"]
        },
        {
          "chunk_id": "chunk_015",
          "text": "Ce diagramme illustre l'architecture...",
          "kind": "FIGURE_TEXT",
          "text_origin": "vision_semantic",
          "page_no": 5,
          "docitem_ids": ["docitem_015"]
        }
      ]
    }
  }
}
```

---

## Prompt Vision Semantic Reader (v1.0)

```yaml
vision_semantic_reader:
  version: "v1.0"
  system: |
    Tu es un expert en analyse de documents techniques.
    Ta tâche : décrire le contenu visuel de manière FACTUELLE et OBSERVABLE.

    RÈGLES:
    - Décris ce que tu VOIS, pas ce que tu INTERPRÈTES
    - 2-8 phrases maximum
    - Identifie les entités principales (noms, labels)
    - Décris les relations visuelles (flèches, connexions, groupes)
    - N'invente RIEN qui n'est pas visible

    ÉVITE:
    - "Ceci représente officiellement..."
    - "L'architecture cible est..."
    - Toute affirmation normative non visible

  user: |
    Analyse cette page de document.

    Décris le contenu visuel de manière factuelle :
    - Quel type de visuel (diagramme, tableau, schéma, slide) ?
    - Quelles entités sont visibles (labels, noms, composants) ?
    - Quelles relations sont montrées (flèches, liens, hiérarchies) ?

    Réponds en texte lisible, comme si tu décrivais la page à quelqu'un.
```

---

## Plan d'Implémentation

### Phase 10 : Vision Semantic Integration

| ID | Tâche | Priorité |
|----|-------|----------|
| VS-001 | Créer enums `TextOrigin`, `VisionFailureReason` | P0 |
| VS-002 | Créer `VisionSemanticReader` class | P0 |
| VS-003 | Implémenter fallback 3-tier | P0 |
| VS-004 | Intégrer dans pipeline extraction | P0 |
| VS-005 | Mettre à jour format cache → V3 | P0 |
| VS-006 | Supprimer caches V2 existants | P0 |
| VS-007 | Re-extraire corpus (19 docs) | P0 |
| VS-008 | Valider invariant "aucun chunk vide" | P0 |
| VS-009 | Mettre à jour ADR | P1 |

---

## Historique

| Date | Événement |
|------|-----------|
| 2026-01-24 | Identification du gap Vision (chunks FIGURE_TEXT vides) |
| 2026-01-24 | Review ChatGPT : recommandation Option B → Vision Semantic Reader |
| 2026-01-24 | Spec finalisée avec invariants, enums, fallback strategy |
| 2026-01-24 | Validation ChatGPT + Claude |
