# ADR: Structural Graph from DoclingDocument (Option C)

**Status:** Ready for Implementation ✅
**Date:** 2026-01-09
**Updated:** 2026-01-09 (v3 - corrections ChatGPT appliquées)
**Authors:** Claude Code, ChatGPT (co-design)
**Supersedes:** Heuristiques relation_likelihood basées sur markers
**Review:** ChatGPT validation complète - 4 blocking issues résolus

---

## Decisions (MUST/SHOULD/MAY)

Cette section liste les décisions explicites pour une implémentation sans ambiguïté.

### D1. Identifiants, Multi-Tenant et Versioning

| Décision | Niveau | Description |
|----------|--------|-------------|
| D1.1 | **MUST** | Tous les nœuds structuraux portent `tenant_id` |
| D1.2 | **MUST** | Introduire un nœud `DocumentVersion` pour gérer l'audit trail versionné |
| D1.3 | **MUST** | `DocumentContext` unique sur `(tenant_id, doc_id)` - représente le document "stable" |
| D1.4 | **MUST** | `DocumentVersion` unique sur `(tenant_id, doc_id, doc_version_id)` où `doc_version_id = doc_hash` |
| D1.5 | **MUST** | Page/Section/DocItem/Chunk sont attachés à `DocumentVersion` et portent `doc_version_id` |
| D1.6 | **MUST** | DocItem unique sur `(tenant_id, doc_id, doc_version_id, item_id)` |
| D1.7 | **MUST** | `item_id` = Docling `self_ref`, unique dans une version de document |

```
Modèle de versioning :

(DocumentContext {tenant_id, doc_id})  ← stable, représente "le document"
    │
    └──[:HAS_VERSION]──▶ (DocumentVersion {tenant_id, doc_id, doc_version_id, is_current:bool})
                              │
                              ├──[:HAS_PAGE]──▶ (PageContext {doc_version_id, page_no})
                              ├──[:HAS_SECTION]──▶ (SectionContext {doc_version_id, ...})
                              └──[:CONTAINS]──▶ (DocItem {doc_version_id, item_id, ...})
```

### D2. Reading Order (Déterministe)

| Décision | Niveau | Description |
|----------|--------|-------------|
| D2.1 | **MUST** | Le `reading_order_index` est calculé par tri déterministe, pas par ordre des listes Python |
| D2.2 | **MUST** | Règle de tri : `page_no ASC` → `bbox.top ASC` → `bbox.left ASC` → `self_ref ASC` (tie-breaker) |
| D2.3 | **SHOULD** | Stocker `reading_order_index` comme Int sur chaque DocItem |

```python
def compute_reading_order(items: List[DocItem]) -> List[DocItem]:
    """Tri déterministe pour reading order."""
    return sorted(items, key=lambda x: (
        x.page_no or 0,
        x.bbox_y0 or 0,      # top
        x.bbox_x0 or 0,      # left
        x.item_id,           # tie-breaker stable
    ))
```

### D3. Types et Classification

| Décision | Niveau | Description |
|----------|--------|-------------|
| D3.1 | **MUST** | Définir `RELATION_BEARING_TYPES` = `{TEXT, HEADING, CAPTION, FOOTNOTE}` |
| D3.2 | **MUST** | Définir `STRUCTURE_BEARING_TYPES` = `{TABLE, FIGURE, CODE, FORMULA, FURNITURE, REFERENCE}` |
| D3.3 | **MUST** | `LIST_ITEM` est RELATION_BEARING **iff** `section.is_relation_bearing == true` **AND** `section.list_ratio < 0.5`, sinon STRUCTURE_BEARING |
| D3.4 | **SHOULD** | Mapper tous les `DocItemLabel` inconnus vers `OTHER` (structure-bearing par défaut) |

```python
RELATION_BEARING_TYPES = {"TEXT", "HEADING", "CAPTION", "FOOTNOTE"}
STRUCTURE_BEARING_TYPES = {"TABLE", "FIGURE", "CODE", "FORMULA", "FURNITURE", "REFERENCE", "OTHER"}

def is_item_relation_bearing(item: DocItem, section_profile: StructuralProfile) -> bool:
    """Détermine si un item est relation-bearing selon son type et le contexte section."""
    if item.item_type in RELATION_BEARING_TYPES:
        return True
    if item.item_type == "LIST_ITEM":
        # LIST_ITEM dépend du contexte section
        return section_profile.is_relation_bearing and section_profile.list_ratio < 0.5
    return False
```

### D4. Assignment DocItem → SectionContext

| Décision | Niveau | Description |
|----------|--------|-------------|
| D4.1 | **MUST** | Les sections sont créées à partir des `HEADING` (TITLE, SECTION_HEADER) dans l'ordre de lecture |
| D4.2 | **MUST** | Un HEADING de niveau N ouvre une section qui se termine au prochain HEADING de niveau ≤ N |
| D4.3 | **MUST** | Tous les DocItems entre deux HEADING sont assignés à la section ouverte par le premier |
| D4.4 | **SHOULD** | `section_path` = concaténation des titres de la hiérarchie (ex: "1. Introduction / 1.1 Overview") |
| D4.5 | **MUST** | Créer une section `root` pour le document + sous-sections par page si aucun HEADING détecté |
| D4.6 | **MUST** | Conserver la hiérarchie Docling native (parent/group) comme metadata sur DocItem, sans l'utiliser comme section model |

```python
def assign_items_to_sections(items: List[DocItem]) -> Dict[str, List[DocItem]]:
    """Assigne chaque item à sa section basée sur les headings."""
    sections = {}
    current_section = "root"
    section_stack = []  # [(level, section_id)]
    has_headings = any(i.item_type == "HEADING" for i in items)

    for item in sorted(items, key=lambda x: x.reading_order_index):
        if item.item_type == "HEADING":
            level = item.heading_level or 1
            # Fermer les sections de niveau >= level
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            # Ouvrir nouvelle section
            section_id = generate_section_id(item)
            section_stack.append((level, section_id))
            current_section = section_id
        elif not has_headings:
            # Fallback: section par page si pas de headings
            current_section = f"root/page_{item.page_no:03d}"

        sections.setdefault(current_section, []).append(item)

    return sections
```

> **Note**: La hiérarchie Docling (`parent_item_id`, `group_id`) est stockée sur chaque DocItem
> mais n'est PAS utilisée pour construire les sections. Elle est conservée pour des usages
> futurs (navigation avancée, extraction structurée) sans impacter le modèle section actuel.

### D5. Provenance (Multi-Prov)

| Décision | Niveau | Description |
|----------|--------|-------------|
| D5.1 | **MUST** | `primary_prov` = prov avec **page_no minimal**, puis bbox top minimal, puis self_ref (déterministe) |
| D5.2 | **MUST** | Stocker `page_span_min`, `page_span_max` pour items multi-pages |
| D5.3 | **MUST** | Format bbox : coordonnées absolues, stocker `bbox_unit` ∈ {`points`, `pixels`, `normalized`} |
| D5.4 | **MUST** | Stocker `page_width`, `page_height` dans PageContext pour permettre conversion |
| D5.5 | **SHOULD** | Stocker bbox comme 4 floats séparés : `bbox_x0, bbox_y0, bbox_x1, bbox_y1` (pas JSON) |

```python
def select_primary_prov(prov_list: List[ProvenanceItem]) -> ProvenanceItem:
    """Sélectionne la provenance primaire de façon déterministe."""
    if not prov_list:
        return None
    if len(prov_list) == 1:
        return prov_list[0]

    # Tri déterministe : page_no ASC, bbox.top ASC, bbox.left ASC
    return min(prov_list, key=lambda p: (
        p.page_no,
        p.bbox.t if p.bbox else 0,  # top
        p.bbox.l if p.bbox else 0,  # left
    ))
```

### D6. doc_hash (Versioning)

| Décision | Niveau | Description |
|----------|--------|-------------|
| D6.1 | **MUST** | `doc_hash` = SHA-256 du JSON canonisé de DoclingDocument |
| D6.2 | **MUST** | Canonisation : tri des clés, suppression des champs volatiles (voir liste ci-dessous) |
| D6.3 | **MUST** | Arrondi des floats (bbox, confidence) à N décimales avant hash (défaut N=2) |
| D6.4 | **MUST** | Tri déterministe des listes par `self_ref` avant dump JSON |
| D6.5 | **SHOULD** | Préfixer le hash avec la version du schema : `v1:{sha256}` |
| D6.6 | **NOTE** | Le nombre de décimales (D6.3) est configurable via `HASH_FLOAT_PRECISION`. Si Docling émet des floats avec plus de précision significative, augmenter à 4 décimales. |

**Champs volatiles à exclure (MUST):**
- `origin.mtime`, `origin.atime`, `origin.ctime`
- `origin.path`, `origin.uri`, `origin.filename` (chemins locaux)
- `created_at`, `processed_at`, `timestamp`, `runtime`, `elapsed`
- `pipeline_version`, `docling_version` (stocker à côté dans DocumentContext, pas dans le hash)

**Champs à normaliser (MUST):**
- `confidence`, `score` : arrondir à 2 décimales
- Listes d'items : trier par `self_ref` avant serialisation

```python
import hashlib
import json
from copy import deepcopy

VOLATILE_ORIGIN_KEYS = {"mtime", "atime", "ctime", "path", "uri", "filename"}
VOLATILE_ROOT_KEYS = {"created_at", "processed_at", "timestamp", "runtime",
                       "elapsed", "pipeline_version", "docling_version"}

def compute_doc_hash(doc_dict: dict) -> str:
    """Calcule un hash stable du DoclingDocument."""
    canonical = deepcopy(doc_dict)

    # Supprimer champs volatiles au niveau origin
    if "origin" in canonical and isinstance(canonical["origin"], dict):
        for key in VOLATILE_ORIGIN_KEYS:
            canonical["origin"].pop(key, None)

    # Supprimer champs volatiles au niveau root
    for key in VOLATILE_ROOT_KEYS:
        canonical.pop(key, None)

    # Trier les listes par self_ref pour déterminisme
    for key in ["texts", "tables", "pictures", "groups"]:
        if key in canonical and isinstance(canonical[key], list):
            canonical[key] = sorted(
                canonical[key],
                key=lambda x: x.get("self_ref", "") if isinstance(x, dict) else ""
            )

    # Arrondir les floats (bbox, confidence, score)
    round_floats_recursive(canonical, decimals=2)

    # JSON canonique (clés triées, pas d'espaces)
    json_str = json.dumps(canonical, sort_keys=True, separators=(',', ':'))

    # SHA-256
    sha = hashlib.sha256(json_str.encode()).hexdigest()
    return f"v1:{sha}"

def round_floats_recursive(obj, decimals=2):
    """Arrondit tous les floats récursivement."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, float):
                obj[k] = round(v, decimals)
            else:
                round_floats_recursive(v, decimals)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, float):
                obj[i] = round(item, decimals)
            else:
                round_floats_recursive(item, decimals)
```

### D7. Stockage Artefact DoclingDocument

| Décision | Niveau | Description |
|----------|--------|-------------|
| D7.1 | **MUST** | Persister `DoclingDocument.export_to_dict()` comme artefact JSON |
| D7.2 | **MUST** | Chemin : `data/docling_artifacts/{tenant_id}/{doc_id}/{doc_hash}.json` |
| D7.3 | **SHOULD** | Compression gzip pour réduire le volume |
| D7.4 | **MAY** | Chiffrement au repos si données sensibles |
| D7.5 | **MUST** | Rétention : conserver toutes les versions (audit trail) |

### D8. Migration (Pattern Industriel)

| Décision | Niveau | Description |
|----------|--------|-------------|
| D8.1 | **MUST** | Le produit cible est **Option C uniquement** (pas de coexistence permanente) |
| D8.2 | **MUST** | Mode "shadow" (dual-write) strictement interne, non exposé fonctionnellement |
| D8.3 | **MUST** | Cutover quand invariants validés : coverage ≥ 99%, provenance 100%, evidence rate stable |
| D8.4 | **MUST** | Ancien pipeline décommissionné immédiatement après cutover |
| D8.5 | **SHOULD** | Feature flag `USE_STRUCTURAL_GRAPH` pour basculer la lecture |

### D9. Indexes Neo4j (Production)

| Décision | Niveau | Description |
|----------|--------|-------------|
| D9.1 | **MUST** | Contrainte unique sur DocumentContext : `(tenant_id, doc_id)` |
| D9.2 | **MUST** | Contrainte unique sur DocumentVersion : `(tenant_id, doc_id, doc_version_id)` |
| D9.3 | **MUST** | Contrainte unique sur DocItem : `(tenant_id, doc_id, doc_version_id, item_id)` |
| D9.4 | **MUST** | Contrainte unique sur PageContext : `(tenant_id, doc_version_id, page_no)` |
| D9.5 | **MUST** | Index sur DocItem : `(tenant_id, doc_version_id, reading_order_index)` pour parcours ordonné |
| D9.6 | **MUST** | Index sur SectionContext : `(tenant_id, doc_version_id)` |
| D9.7 | **SHOULD** | Index sur DocItem.item_type pour requêtes par type |

```cypher
// Contraintes uniques (alignées avec D1 versioning model)
CREATE CONSTRAINT doc_context_unique IF NOT EXISTS
FOR (d:DocumentContext) REQUIRE (d.tenant_id, d.doc_id) IS UNIQUE;

CREATE CONSTRAINT doc_version_unique IF NOT EXISTS
FOR (v:DocumentVersion) REQUIRE (v.tenant_id, v.doc_id, v.doc_version_id) IS UNIQUE;

CREATE CONSTRAINT docitem_unique IF NOT EXISTS
FOR (i:DocItem) REQUIRE (i.tenant_id, i.doc_id, i.doc_version_id, i.item_id) IS UNIQUE;

CREATE CONSTRAINT page_unique IF NOT EXISTS
FOR (p:PageContext) REQUIRE (p.tenant_id, p.doc_version_id, p.page_no) IS UNIQUE;

// Indexes de performance
CREATE INDEX docitem_order IF NOT EXISTS
FOR (i:DocItem) ON (i.tenant_id, i.doc_version_id, i.reading_order_index);

CREATE INDEX docitem_type IF NOT EXISTS
FOR (i:DocItem) ON (i.tenant_id, i.item_type);

CREATE INDEX section_version IF NOT EXISTS
FOR (s:SectionContext) ON (s.tenant_id, s.doc_version_id);

// Index pour trouver la version courante d'un document
CREATE INDEX doc_version_current IF NOT EXISTS
FOR (v:DocumentVersion) ON (v.tenant_id, v.doc_id, v.is_current);
```

### D10. structural_profile (Calcul)

| Décision | Niveau | Description |
|----------|--------|-------------|
| D10.1 | **MUST** | Ratios calculés par **nombre d'items** (pas par volume texte ou surface) |
| D10.2 | **MUST** | `is_relation_bearing` = `text_ratio + heading_ratio + caption_ratio > 0.5` |
| D10.3 | **MUST** | `is_structure_bearing` = `table_ratio + figure_ratio + list_ratio > 0.5` |
| D10.4 | **SHOULD** | Recalculer `structural_profile` à chaque modification de la section |
| D10.5 | **MUST** | `dominant_types` = top 2 types par count |
| D10.6 | **NOTE** | `is_relation_bearing` et `is_structure_bearing` peuvent être **tous deux true** (pas mutuellement exclusif). Une section mixte (texte + tableaux) aura les deux flags actifs. |

```python
def compute_structural_profile(items: List[DocItem]) -> StructuralProfile:
    """Calcule le profil structurel d'une section."""
    total = len(items)
    if total == 0:
        return StructuralProfile.empty()

    counts = Counter(item.item_type for item in items)

    return StructuralProfile(
        text_ratio=counts.get("TEXT", 0) / total,
        heading_ratio=counts.get("HEADING", 0) / total,
        table_ratio=counts.get("TABLE", 0) / total,
        list_ratio=counts.get("LIST_ITEM", 0) / total,
        figure_ratio=counts.get("FIGURE", 0) / total,
        caption_ratio=counts.get("CAPTION", 0) / total,
        dominant_types=get_top_n_types(counts, n=2),
        is_relation_bearing=(
            counts.get("TEXT", 0) + counts.get("HEADING", 0) +
            counts.get("CAPTION", 0) + counts.get("FOOTNOTE", 0)
        ) / total > 0.5,
        is_structure_bearing=(
            counts.get("TABLE", 0) + counts.get("FIGURE", 0) +
            counts.get("LIST_ITEM", 0)
        ) / total > 0.5,
    )
```

### D11. Représentation Textuelle TABLE/FIGURE

| Décision | Niveau | Description |
|----------|--------|-------------|
| D11.1 | **MUST** | TABLE : stocker `table_json` (cells/headers canoniques) comme source de vérité |
| D11.2 | **MUST** | TABLE : `DocItem.text` = Markdown normalisé (max 50 rows, max 10 cols, échappement stable) |
| D11.3 | **MUST** | FIGURE : `DocItem.text` = caption si disponible, sinon chaîne vide `""` |
| D11.4 | **MUST** | FIGURE : conserver `item_type=FIGURE`, bbox, page_no même si text vide |
| D11.5 | **MAY** | Pass dédiée "figure description" via LLM déclenchée uniquement quand nécessaire (autre ADR) |
| D11.6 | **MUST** | Si `table_to_text()` échoue (structure corrompue), retourner `"[TABLE: parsing error]"` et logger un warning |
| D11.7 | **SHOULD** | Valider que le Markdown généré est syntaxiquement correct avant stockage |

```python
import logging
logger = logging.getLogger(__name__)

def table_to_text(table_item) -> str:
    """Convertit une table Docling en Markdown normalisé pour embeddings."""
    MAX_ROWS = 50
    MAX_COLS = 10

    try:
        headers = table_item.headers[:MAX_COLS] if table_item.headers else []
        rows = [row[:MAX_COLS] for row in table_item.cells[:MAX_ROWS]]

        lines = []
        if headers:
            lines.append("| " + " | ".join(escape_md(h) for h in headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in rows:
            lines.append("| " + " | ".join(escape_md(str(c)) for c in row) + " |")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[table_to_text] Failed to convert table {table_item.self_ref}: {e}")
        return "[TABLE: parsing error]"

def figure_to_text(picture_item, caption: str = None) -> str:
    """Texte pour une figure : caption ou vide."""
    return caption.strip() if caption else ""
```

---

## Contexte

### Le Problème Identifié

Lors de l'implémentation de Phase 1 (filtrage des sections "catalogue-like"), nous avons découvert un problème architectural fondamental :

1. **Docling extrait une structure riche** : types d'items (TABLE, TEXT, LIST_ITEM, FIGURE...), hiérarchie, provenance (page, bbox), etc.

2. **Le Linearizer aplatit cette structure** en texte avec des marqueurs :
   ```
   [TABLE_START id=table_1]
   | col1 | col2 |
   [TABLE_END]
   ```

3. **Nous essayons de réinférer la structure** depuis ces marqueurs via des heuristiques (`bullet_ratio`, `verb_density`, regex sur `[TABLE_START]`...)

4. **Cette approche est fondamentalement fragile** :
   - Les marqueurs ne sont pas un contrat API stable
   - La réinférence est forcément incomplète
   - Nous payons un coût de complexité permanent

### Diagnostic Empirique

Tests sur Operations Guide (2026-01-09) :
- 90% des sections classées HIGH/MEDIUM (le filtre ne filtre pas)
- Réduction candidats de seulement 21.3% (attendu >70%)
- Sections contenant `[TABLE_START]` classées HIGH car `bullet_ratio=0`

**Cause racine** : Les patterns structurels Docling (tables, visual enrichments) ne sont pas reconnus car nous travaillons sur du texte linéarisé, pas sur la structure native.

---

## Décision

### Axiome Central

> **La structure du document doit être consommée sous forme structurée (DoclingDocument), jamais inférée depuis une linéarisation.**

### Solution : Option C "Structural Graph"

Construire un **Structural Graph** dans Neo4j qui représente fidèlement la structure Docling :

```
DoclingDocument (structure riche)
  → DocItem nodes (Neo4j) + PageContext + SectionContext enrichi
  → Type-aware Chunks (NARRATIVE/TABLE/FIGURE)
  → Evidence-first Relation Engine

Le Linearizer devient un produit secondaire (debug/UI), pas une source de vérité.
```

---

## Modèle de Données

### Entités Neo4j

#### `DocumentContext` (existant, enrichi)
```
- doc_id: String (unique)
- doc_hash: String (hash du DoclingDocument pour versioning)
- tenant_id: String
- source_uri: String (optionnel)
- ingested_at: DateTime
- pipeline_version: String
- docling_version: String
- title: String (optionnel)
```

#### `PageContext` (nouveau)
```
- tenant_id: String (MUST)
- doc_id: String (MUST)
- doc_version_id: String (= doc_hash, MUST)
- page_no: Int (MUST)
- page_width: Float (MUST, pour conversion bbox)
- page_height: Float (MUST, pour conversion bbox)
- bbox_unit: String (MUST, ∈ {"points", "pixels", "normalized"})
```

#### `SectionContext` (existant, enrichi)
```
- tenant_id: String (MUST)
- context_id: String (MUST)
- doc_id: String (MUST)
- doc_version_id: String (= doc_hash, MUST)
- section_path: String
- section_level: Int
- title: String (optionnel)

# NOUVEAU - structural_profile
- dominant_types: List[String]  # ["TABLE", "TEXT"]
- is_relation_bearing: Boolean
- is_structure_bearing: Boolean
- table_ratio: Float
- list_ratio: Float
- figure_ratio: Float
- text_ratio: Float
```

#### `DocItem` (nouveau - coeur de l'Option C)
```
# Identifiants
- tenant_id: String (MUST)
- doc_id: String (MUST)
- doc_version_id: String (= doc_hash, MUST)
- item_id: String (= Docling self_ref, MUST)

# Type et contenu
- item_type: Enum  # TEXT, HEADING, LIST_ITEM, TABLE, FIGURE, CAPTION, CODE, FORMULA, FOOTNOTE, FURNITURE, OTHER
- heading_level: Int (optionnel, pour HEADING)
- text: String (pour types textuels, Markdown pour TABLE)
- table_json: String (optionnel, JSON canonique pour TABLE)

# Hiérarchie Docling (conservée comme metadata)
- parent_item_id: String (optionnel, = Docling parent.self_ref)
- group_id: String (optionnel, = Docling group self_ref)

# Provenance (voir D5 pour sélection primary_prov)
- page_no: Int (primary prov, MUST)
- page_span_min: Int (optionnel, si multi-page)
- page_span_max: Int (optionnel, si multi-page)
- bbox_x0, bbox_y0, bbox_x1, bbox_y1: Float (optionnel, coordonnées absolues)
- bbox_unit: String (MUST si bbox présent, ∈ {"points", "pixels", "normalized"})
- charspan_start, charspan_end: Int (optionnel)

# Ordre et metadata
- reading_order_index: Int (MUST)
- confidence: Float (optionnel)
- created_at: DateTime
```

### Relations Neo4j

```cypher
// Hiérarchie document
(d:DocumentContext)-[:HAS_PAGE]->(p:PageContext)
(d:DocumentContext)-[:HAS_SECTION]->(s:SectionContext)
(s:SectionContext)-[:SUBSECTION_OF]->(s2:SectionContext)  // optionnel

// Contenu
(s:SectionContext)-[:CONTAINS]->(i:DocItem)
(i:DocItem)-[:ON_PAGE]->(p:PageContext)
(i:DocItem)-[:NEXT_IN_READING_ORDER]->(j:DocItem)

// Chunking
(chunk:Chunk)-[:DERIVED_FROM]->(i:DocItem)  // un chunk référence N items

// Sémantique (existant)
(c:CanonicalConcept)-[:MENTIONED_IN]->(s:SectionContext)
(c:CanonicalConcept)-[:ANCHORED_IN]->(chunk:Chunk)  // ou DocItem

// Relations avec evidence enrichie
(c1:CanonicalConcept)-[r:REQUIRES|ENABLES|...]->(c2:CanonicalConcept)
// r.evidence_item_ids: List[String]  # IDs des DocItems
// r.evidence_chunk_id: String
// r.evidence_page_no: Int
// r.evidence_bbox: String (JSON)
```

---

## Mapping Docling → DocItem

### Types Docling Disponibles (DocItemLabel)

| DocItemLabel | item_type | is_relation_bearing |
|--------------|-----------|---------------------|
| TEXT | TEXT | true |
| PARAGRAPH | TEXT | true |
| TITLE | HEADING | true |
| SECTION_HEADER | HEADING | true |
| LIST_ITEM | LIST_ITEM | partial |
| TABLE | TABLE | false |
| CHART | TABLE | false |
| PICTURE | FIGURE | false |
| CAPTION | CAPTION | true |
| CODE | CODE | false |
| FORMULA | FORMULA | false |
| FOOTNOTE | FOOTNOTE | true |
| PAGE_HEADER | FURNITURE | false |
| PAGE_FOOTER | FURNITURE | false |
| REFERENCE | REFERENCE | false |

### Extraction depuis DoclingDocument

```python
def extract_doc_items(doc: DoclingDocument) -> List[DocItem]:
    items = []
    reading_order = 0

    # Textes (incluant headings, list items, etc.)
    for text_item in doc.texts:
        items.append(DocItem(
            item_id=text_item.self_ref,
            item_type=map_label_to_type(text_item.label),
            text=text_item.text,
            page_no=text_item.prov[0].page_no if text_item.prov else None,
            bbox=text_item.prov[0].bbox if text_item.prov else None,
            charspan=text_item.prov[0].charspan if text_item.prov else None,
            reading_order_index=reading_order,
        ))
        reading_order += 1

    # Tables
    for table_item in doc.tables:
        items.append(DocItem(
            item_id=table_item.self_ref,
            item_type="TABLE",
            text=table_to_text(table_item),  # Représentation textuelle
            page_no=table_item.prov[0].page_no if table_item.prov else None,
            bbox=table_item.prov[0].bbox if table_item.prov else None,
            reading_order_index=reading_order,
        ))
        reading_order += 1

    # Pictures
    for pic in doc.pictures:
        items.append(DocItem(
            item_id=pic.self_ref,
            item_type="FIGURE",
            page_no=pic.prov[0].page_no if pic.prov else None,
            bbox=pic.prov[0].bbox if pic.prov else None,
            reading_order_index=reading_order,
        ))
        reading_order += 1

    return items
```

---

## Chunking Type-Aware

### Règles de Chunking

| chunk_kind | Sources DocItem | Pipeline |
|------------|-----------------|----------|
| NARRATIVE_TEXT | TEXT, HEADING, CAPTION, FOOTNOTE | Relation extraction, Anchors |
| TABLE_TEXT | TABLE | Table-specific processing |
| FIGURE_TEXT | FIGURE + CAPTION | Vision enrichment |
| CODE_TEXT | CODE, FORMULA | Code analysis (optionnel) |

### Principe

```python
def create_chunks(doc_items: List[DocItem]) -> List[Chunk]:
    chunks = []
    current_narrative = []

    for item in sorted(doc_items, key=lambda x: x.reading_order_index):
        if item.item_type in NARRATIVE_TYPES:
            current_narrative.append(item)
            if should_split(current_narrative):
                chunks.append(Chunk(
                    kind="NARRATIVE_TEXT",
                    item_ids=[i.item_id for i in current_narrative],
                    text=merge_texts(current_narrative),
                ))
                current_narrative = []
        else:
            # Flush narrative buffer
            if current_narrative:
                chunks.append(Chunk(kind="NARRATIVE_TEXT", ...))
                current_narrative = []

            # Chunk dédié pour table/figure
            chunks.append(Chunk(
                kind=f"{item.item_type}_TEXT",
                item_ids=[item.item_id],
                text=item.text,
            ))

    return chunks
```

---

## Relation Engine - Evidence-First

### Candidate Generation (nouveau paradigme)

```python
def generate_candidates(chunk: Chunk) -> List[RelationCandidate]:
    # SEULEMENT sur chunks NARRATIVE_TEXT
    if chunk.kind != "NARRATIVE_TEXT":
        return []

    # Concepts ancrés dans ce chunk
    anchored = get_anchored_concepts(chunk)

    # Paires locales = candidats
    candidates = []
    for c1, c2 in combinations(anchored, 2):
        candidates.append(RelationCandidate(
            subject=c1,
            object=c2,
            chunk_id=chunk.id,
            item_ids=chunk.item_ids,
            text=chunk.text,  # Evidence déjà localisée!
        ))

    return candidates
```

### Evidence Native

```python
def store_validated_relation(relation: ValidatedRelation):
    # Evidence = item_ids + page + bbox (provenance complète)
    neo4j.create_relation(
        subject=relation.subject,
        object=relation.object,
        rel_type=relation.relation_type,
        properties={
            "evidence_quote": relation.quote,
            "evidence_chunk_id": relation.chunk_id,
            "evidence_item_ids": relation.item_ids,  # Traçabilité!
            "evidence_page_no": get_page_from_items(relation.item_ids),
            "confidence": relation.confidence,
        }
    )
```

---

## Impact sur le Code Existant

### Fichiers à Modifier

| Fichier | Modification |
|---------|--------------|
| `docling_extractor.py` | Extraire et persister DoclingDocument dict |
| `navigation_layer_builder.py` | Créer DocItem nodes, enrichir SectionContext |
| `hybrid_anchor_chunker.py` | Type-aware chunking |
| `semantic_consolidation_pass3.py` | Candidates depuis chunks NARRATIVE |
| `linearizer.py` | Déclasser (debug only), feature flag |

### Nouveaux Fichiers

| Fichier | Rôle |
|---------|------|
| `src/knowbase/structural/docitem_builder.py` | DoclingDocument → DocItem nodes |
| `src/knowbase/structural/section_profiler.py` | Calcul structural_profile |
| `src/knowbase/structural/type_aware_chunker.py` | Chunking par type |

### Migration

1. **Dual-write** : Écrire ancien + nouveau format pendant transition
2. **Validation** : Comparer coverage, counts, invariants
3. **Cutover** : Basculer lecture sur nouveau format
4. **Décommission** : Supprimer ancien chemin

---

## Conséquences

### Positives

1. **Robustesse** : Plus de dépendance aux markers textuels
2. **Précision** : `item_type=TABLE` est une vérité, pas une inférence
3. **Traçabilité** : Provenance complète (page, bbox, item_ids)
4. **Moins de coût LLM** : Tables/figures ne passent pas par relation extraction
5. **Agnostique métier** : Types universels (TEXT, TABLE, FIGURE...)
6. **Auditabilité** : "Montre-moi où c'est écrit" = trivial

### Négatives

1. **Migration** : Réingestion nécessaire pour documents existants
2. **Complexité initiale** : Plus de nodes Neo4j (DocItems)
3. **Dépendance Docling** : Types liés à l'API Docling (mais plus stable que markers)

### Risques

1. **Volume Neo4j** : Mitigation par indexes appropriés
2. **Évolution Docling** : Mitigation par mapping abstrait (DocItemLabel → item_type)

---

## KPIs de Succès

### Structural KPIs

- Distribution `item_type` par document
- Ratio narrative vs table vs figure (doit correspondre à la réalité)
- Coverage : % items assignés à sections, % items chunkés

### Relation KPIs

- Candidates per 1k tokens (NARRATIVE only)
- Validation rate (doit augmenter significativement)
- Abstain rate par chunk_kind (TABLE → N/A)

### Quality KPIs

- Evidence quote validation : doit être ~100%
- Relations avec provenance complète : 100%
- Orphan anchors : 0

---

## Références

- Docling Documentation: https://github.com/DS4SD/docling
- `DoclingDocument` model: `docling.datamodel.document.DoclingDocument`
- `DocItemLabel` enum: `docling.datamodel.base_models.DocItemLabel`
- ADR Navigation Layer: `doc/ongoing/ADR_NAVIGATION_LAYER.md`
- Phase 1 diagnostic: Session Claude Code 2026-01-09

---

## Annexe: Types Docling Complets

```python
class DocItemLabel(Enum):
    CAPTION = "caption"
    CHART = "chart"
    FOOTNOTE = "footnote"
    FORMULA = "formula"
    LIST_ITEM = "list_item"
    PAGE_FOOTER = "page_footer"
    PAGE_HEADER = "page_header"
    PICTURE = "picture"
    SECTION_HEADER = "section_header"
    TABLE = "table"
    TEXT = "text"
    TITLE = "title"
    DOCUMENT_INDEX = "document_index"
    CODE = "code"
    CHECKBOX_SELECTED = "checkbox_selected"
    CHECKBOX_UNSELECTED = "checkbox_unselected"
    FORM = "form"
    KEY_VALUE_REGION = "key_value_region"
    GRADING_SCALE = "grading_scale"
    HANDWRITTEN_TEXT = "handwritten_text"
    EMPTY_VALUE = "empty_value"
    PARAGRAPH = "paragraph"
    REFERENCE = "reference"
```
