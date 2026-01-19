# ADR: Charspan Contract v1

**Statut**: Draft
**Date**: 2026-01-18
**Auteurs**: Claude + ChatGPT (consultation)
**Neo4j**: 5.26.0

---

## 1. Contexte et Problème

### 1.1 Situation initiale

Le système OSMOSE avait **mélangé 3 notions de position** qui n'ont pas la même sémantique:

| Type | Définition | Problème |
|------|------------|----------|
| `charspan per-page` | Position dans la page (0-based par page) | Inutilisable pour localisation document |
| `charspan docwide` | Position dans le document entier | Manquant sur DocItems |
| `span relatif` | Position dans le texte d'un chunk/DocItem | Perdu après extraction |

### 1.2 Symptômes observés

```
Données actuelles dans Neo4j:
- p.char_start_docwide = valeurs incorrectes (début du DocItem, pas du concept)
- r.char_start / r.char_end = NULL (positions sur ANCHORED_IN)
- d.charspan_start = 0 (per-page, pas docwide)
- d.charspan_start_docwide = NULL (Phase 0 non exécutée)
```

### 1.3 Cause racine

Code dans `osmose_persistence.py` (Phase 3b):
```python
# BUG: Copie le début du DocItem, pas la position du concept
SET p.char_start_docwide = d.charspan_start,
    p.char_end_docwide = d.charspan_end
```

Les positions primaires de l'extracteur (NER/spaCy) existaient mais n'étaient pas propagées.

---

## 2. Décision

**Purger les données existantes et implémenter le Charspan Contract v1.**

Données Neo4j et Qdrant considérées comme jetables. Fix forward uniquement.

---

## 3. Spec Contractuelle v1

### 3.1 Terminologie

| Terme | Définition |
|-------|------------|
| `Document.text_docwide` | Concaténation canonique du texte du document |
| `DocItem.text` | Texte exact du DocItem |
| `docwide span` | Intervalle `[start, end)` en indices de caractères dans `Document.text_docwide` |
| `relative span` | Intervalle `[start, end)` relatif au texte de la cible (DocItem.text) |

**Convention**: Intervalle demi-ouvert `[start, end)` (start inclus, end exclus).

### 3.2 Source of Truth (SoT)

**SoT = relation `ANCHORED_IN`**

La position exacte d'un ProtoConcept **MUST** être stockée sur l'edge:

```
(p:ProtoConcept)-[r:ANCHORED_IN]->(d:DocItem)
```

Propriétés obligatoires sur `r`:

| Propriété | Type | Description |
|-----------|------|-------------|
| `span_start` | int >= 0 | Relatif à `d.text` |
| `span_end` | int > span_start | Relatif à `d.text` |
| `anchor_quality` | enum | PRIMARY, DERIVED, APPROX, AMBIGUOUS |
| `anchor_method` | string | spacy_ner, llm, indexOf_fallback, regex... |
| `anchor_id` | string | Clé unique: `{proto_id}:{docitem_id}:{span_start}:{span_end}` |
| `surface_form` | string (opt) | Texte exact matché |
| `confidence` | float (opt) | Score de l'extracteur |

### 3.3 Propriétés obligatoires sur DocItem

| Propriété | Type | Description |
|-----------|------|-------------|
| `docitem_id` | string | ID unique |
| `doc_id` | string | ID du document parent |
| `text` | string | Texte du DocItem (peut être vide, pas NULL) |
| `charspan_start_docwide` | int >= 0 | Début dans le document |
| `charspan_end_docwide` | int > start | Fin dans le document |

**Invariant**: `charspan_end_docwide - charspan_start_docwide == len(text)`

### 3.4 Calcul docwide d'un anchor

Formule unique:
```
anchor_start_docwide = d.charspan_start_docwide + r.span_start
anchor_end_docwide   = d.charspan_start_docwide + r.span_end
```

Vérification:
```
Document.text_docwide[anchor_start_docwide:anchor_end_docwide] == d.text[r.span_start:r.span_end]
```

### 3.5 Cache optionnel sur ProtoConcept

`p.char_start_docwide` / `p.char_end_docwide` **MAY** exister mais:
- C'est **dérivé**, recomputable, non contractuel
- Il **MUST** être cohérent avec "best anchor"

Règle "best anchor":
1. `anchor_quality` le plus élevé: PRIMARY > DERIVED > APPROX > AMBIGUOUS
2. Tie-breaker: plus petit `d.charspan_start_docwide`, puis plus petit `r.span_start`

### 3.6 Modes d'ancrage (anchor_quality)

| Valeur | Description | Usage |
|--------|-------------|-------|
| `PRIMARY` | Spans fournis par extracteur primaire (NER/spaCy/LLM) avec offsets | Relations extractives |
| `DERIVED` | Calculé par transformation fiable et déterministe | Relations extractives |
| `APPROX` | indexOf / fuzzy match | Navigation only |
| `AMBIGUOUS` | Plusieurs matches plausibles | Require disambiguation |

**Règle**: Les opérations de preuve stricte **MUST** refuser APPROX et AMBIGUOUS.

### 3.7 Interdictions (anti-regressions)

- Ne jamais faire `p.char_start_docwide = d.charspan_start` (per-page)
- Ne jamais stocker des spans "docwide" sur l'edge si l'edge pointe vers DocItem
- Ne jamais "réparer" silencieusement un anchor: tout fallback doit être tagué APPROX

---

## 4. Schéma Neo4j (5.26.0)

### 4.1 Constraints d'unicité

```cypher
-- Document
CREATE CONSTRAINT document_doc_id_unique IF NOT EXISTS
FOR (d:Document)
REQUIRE d.doc_id IS UNIQUE;

-- DocItem
CREATE CONSTRAINT docitem_id_unique IF NOT EXISTS
FOR (di:DocItem)
REQUIRE di.docitem_id IS UNIQUE;

-- ProtoConcept
CREATE CONSTRAINT protoconcept_id_unique IF NOT EXISTS
FOR (p:ProtoConcept)
REQUIRE p.proto_id IS UNIQUE;
```

### 4.2 Constraints d'existence - DocItem

```cypher
CREATE CONSTRAINT docitem_text_exists IF NOT EXISTS
FOR (di:DocItem)
REQUIRE di.text IS NOT NULL;

CREATE CONSTRAINT docitem_doc_id_exists IF NOT EXISTS
FOR (di:DocItem)
REQUIRE di.doc_id IS NOT NULL;

CREATE CONSTRAINT docitem_docwide_start_exists IF NOT EXISTS
FOR (di:DocItem)
REQUIRE di.charspan_start_docwide IS NOT NULL;

CREATE CONSTRAINT docitem_docwide_end_exists IF NOT EXISTS
FOR (di:DocItem)
REQUIRE di.charspan_end_docwide IS NOT NULL;
```

### 4.3 Constraints d'existence - ANCHORED_IN

```cypher
CREATE CONSTRAINT anchored_in_span_start_exists IF NOT EXISTS
FOR ()-[r:ANCHORED_IN]-()
REQUIRE r.span_start IS NOT NULL;

CREATE CONSTRAINT anchored_in_span_end_exists IF NOT EXISTS
FOR ()-[r:ANCHORED_IN]-()
REQUIRE r.span_end IS NOT NULL;

CREATE CONSTRAINT anchored_in_quality_exists IF NOT EXISTS
FOR ()-[r:ANCHORED_IN]-()
REQUIRE r.anchor_quality IS NOT NULL;

CREATE CONSTRAINT anchored_in_method_exists IF NOT EXISTS
FOR ()-[r:ANCHORED_IN]-()
REQUIRE r.anchor_method IS NOT NULL;

CREATE CONSTRAINT anchored_in_anchor_id_exists IF NOT EXISTS
FOR ()-[r:ANCHORED_IN]-()
REQUIRE r.anchor_id IS NOT NULL;
```

### 4.4 Constraints d'existence - ProtoConcept

```cypher
CREATE CONSTRAINT protoconcept_doc_id_exists IF NOT EXISTS
FOR (p:ProtoConcept)
REQUIRE p.doc_id IS NOT NULL;

CREATE CONSTRAINT protoconcept_name_exists IF NOT EXISTS
FOR (p:ProtoConcept)
REQUIRE p.concept_name IS NOT NULL;
```

### 4.5 Indexes performance

```cypher
-- Navigation par doc
CREATE INDEX docitem_by_doc_id IF NOT EXISTS
FOR (di:DocItem)
ON (di.doc_id);

CREATE INDEX protoconcept_by_doc_id IF NOT EXISTS
FOR (p:ProtoConcept)
ON (p.doc_id);

-- Debug / lookup
CREATE INDEX protoconcept_by_name IF NOT EXISTS
FOR (p:ProtoConcept)
ON (p.concept_name);

-- Qualité d'ancrage
CREATE INDEX anchored_in_by_quality IF NOT EXISTS
FOR ()-[r:ANCHORED_IN]-()
ON (r.anchor_quality);
```

---

## 5. Pseudo-code d'implémentation

### 5.1 Dataclasses

```python
@dataclass
class ContextualEvidence:
    docitem_id: str
    surface_form: str
    char_start: int        # relatif à DocItem.text
    char_end: int          # relatif à DocItem.text (end exclus)
    method: str            # "spacy_ner", "llm", ...
    confidence: float | None = None

@dataclass
class ProtoConceptCandidate:
    proto_id: str
    concept_name: str
    doc_id: str
    evidences: list[ContextualEvidence]  # 1..n anchors
```

### 5.2 Phase 0: Construction DocItems avec docwide spans

```python
def build_docitems_with_docwide_spans(doc_items: list[DocItem], separator="\n\n"):
    """
    Canonical reading order déjà imposé (ex: docling order).
    On construit une 'document text' implicite en concaténant di.text + separator.
    separator fait partie du contrat (doit être stable).
    """
    cursor = 0
    for di in doc_items:
        di.charspan_start_docwide = cursor
        di.charspan_end_docwide = cursor + len(di.text)
        cursor = di.charspan_end_docwide + len(separator)
```

### 5.3 Phase 1: Extraction NER avec offsets relatifs

```python
def extract_protoconcepts_from_docitem(di: DocItem) -> list[ContextualEvidence]:
    doc = nlp(di.text)
    out = []
    for ent in doc.ents:
        # ent.start_char / ent.end_char sont relatifs à di.text (parfait)
        out.append(ContextualEvidence(
            docitem_id=di.docitem_id,
            surface_form=ent.text,
            char_start=ent.start_char,
            char_end=ent.end_char,
            method="spacy_ner",
            confidence=None
        ))
    return out
```

### 5.4 Validator (avant persistance)

```python
def validate_anchor(di_text: str, ev: ContextualEvidence) -> None:
    if ev.char_start < 0 or ev.char_end <= ev.char_start:
        raise ValueError("Invalid span ordering")
    if ev.char_end > len(di_text):
        raise ValueError("Span out of bounds")
    slice_ = di_text[ev.char_start:ev.char_end]
    if slice_ != ev.surface_form:
        raise ValueError(f"Surface form mismatch: '{slice_}' != '{ev.surface_form}'")
```

### 5.5 Persistance Neo4j

```python
def persist_protoconcept_and_anchors(tx, pc: ProtoConceptCandidate, docitems_by_id: dict):
    # 1) Upsert ProtoConcept
    tx.run("""
    MERGE (p:ProtoConcept {proto_id: $proto_id})
    SET p.concept_name = $concept_name,
        p.doc_id = $doc_id
    """, proto_id=pc.proto_id, concept_name=pc.concept_name, doc_id=pc.doc_id)

    # 2) For each evidence => create ANCHORED_IN with relative spans
    for ev in pc.evidences:
        di = docitems_by_id[ev.docitem_id]
        validate_anchor(di.text, ev)

        anchor_id = f"{pc.proto_id}:{ev.docitem_id}:{ev.char_start}:{ev.char_end}"

        tx.run("""
        MATCH (p:ProtoConcept {proto_id: $proto_id})
        MATCH (di:DocItem {docitem_id: $docitem_id})
        MERGE (p)-[r:ANCHORED_IN {anchor_id: $anchor_id}]->(di)
        SET r.span_start = $span_start,
            r.span_end = $span_end,
            r.surface_form = $surface_form,
            r.anchor_quality = "PRIMARY",
            r.anchor_method = $method,
            r.confidence = $confidence
        """, proto_id=pc.proto_id,
             docitem_id=ev.docitem_id,
             anchor_id=anchor_id,
             span_start=ev.char_start,
             span_end=ev.char_end,
             surface_form=ev.surface_form,
             method=ev.method,
             confidence=ev.confidence)
```

### 5.6 Calcul best anchor cache (optionnel)

```python
def compute_best_anchor_cache(tx, proto_id: str):
    tx.run("""
    MATCH (p:ProtoConcept {proto_id: $proto_id})-[r:ANCHORED_IN]->(di:DocItem)
    WITH p, r, di,
         CASE r.anchor_quality
           WHEN "PRIMARY" THEN 3
           WHEN "DERIVED" THEN 2
           WHEN "APPROX" THEN 1
           ELSE 0
         END AS q
    ORDER BY q DESC, di.charspan_start_docwide ASC, r.span_start ASC
    WITH p, r, di
    LIMIT 1
    SET p.char_start_docwide = di.charspan_start_docwide + r.span_start,
        p.char_end_docwide   = di.charspan_start_docwide + r.span_end
    """, proto_id=proto_id)
```

---

## 6. Sanity Checks (Go/No-Go)

### 6.1 Aucune relation sans spans

```cypher
MATCH (:ProtoConcept)-[r:ANCHORED_IN]->(:DocItem)
WHERE r.span_start IS NULL OR r.span_end IS NULL
RETURN count(r) AS missing_spans;
-- Objectif: 0
```

### 6.2 Aucun DocItem sans docwide

```cypher
MATCH (di:DocItem)
WHERE di.charspan_start_docwide IS NULL OR di.charspan_end_docwide IS NULL
RETURN count(di) AS missing_docwide;
-- Objectif: 0
```

### 6.3 Bounds invalides

```cypher
MATCH (:ProtoConcept)-[r:ANCHORED_IN]->(di:DocItem)
WHERE r.span_start < 0 OR r.span_end <= r.span_start OR r.span_end > size(di.text)
RETURN count(r) AS invalid_bounds;
-- Objectif: 0
```

### 6.4 Surface form incohérente

```cypher
MATCH (:ProtoConcept)-[r:ANCHORED_IN]->(di:DocItem)
WHERE r.surface_form IS NOT NULL
  AND substring(di.text, r.span_start, r.span_end - r.span_start) <> r.surface_form
RETURN count(r) AS surface_mismatch;
-- Objectif: 0
```

---

## 7. Plan d'implémentation

| Étape | Fichier(s) | Action | Statut |
|-------|------------|--------|--------|
| 1 | `app/scripts/setup_charspan_schema.py` | Créer constraints + indexes Neo4j | Done |
| 2 | `src/knowbase/structural/models.py` | Ajouter `charspan_*_docwide` au modèle | Done |
| 2b | `src/knowbase/structural/docitem_builder.py` | Calculer `charspan_*_docwide` via `compute_docwide_charspans()` | Done |
| 3 | `src/knowbase/ingestion/osmose_persistence.py` | Propager spans + anchor_quality sur ANCHORED_IN | Done |
| 4 | `src/knowbase/relations/anchor_validator.py` | Validator bounds + surface_form | Done |
| 5 | Purge + test | Ré-ingérer un document pilote | In Progress |

---

## 8. Références

- Consultation ChatGPT (2026-01-18): Spec contractuelle + schéma Neo4j
- ADR_COVERAGE_PROPERTY_NOT_NODE.md: Coverage = DocItem
- ADR_STRUCTURAL_CONTEXT_ALIGNMENT.md: Section ID alignment
- ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md: Evidence Bundle architecture

---

## 9. Notes d'implémentation

### 9.1 Contraintes non exprimables en Neo4j

Les validations suivantes doivent rester dans le **validator applicatif**:
- `span_end > span_start`
- `span_end <= size(di.text)`

### 9.2 Séparateur docwide

Le séparateur `\n\n` entre DocItems fait partie du contrat. Il doit être stable entre les runs pour que les positions docwide soient reproductibles.

### 9.3 Compatibilité avec le schéma existant

Certaines constraints peuvent échouer si des données legacy existent. **Solution retenue**: purger et recommencer.
