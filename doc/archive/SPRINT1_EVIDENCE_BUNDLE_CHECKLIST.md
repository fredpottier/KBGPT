# Sprint 1: Evidence Bundle Resolver - Safe Mode

**Objectif**: 5-10 relations validées, précision ≥ 95%
**Scope**: Intra-section uniquement, textuels uniquement, pas de retypage visuel
**Référence**: `ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md` v1.3

---

## ⚠️ PRE-DEV GATE - Vérifier AVANT de coder

| # | Check | Status |
|---|-------|--------|
| 1 | **Pas de liste de lemmes anglais** (`GENERIC_VERBS`) - utiliser POS=AUX + dep-based | ☐ |
| 2 | **Charspans requis** - `ProtoConcept.char_start/char_end` existent dans le schéma | ☐ |
| 3 | **SectionContext.text** disponible - texte brut de la section accessible | ☐ |
| 4 | **Schéma Neo4j** - edges `HAS_RELATION`/`RELATES_TO` compatibles avec modèle existant | ☐ |
| 5 | **spaCy multi-langue** - modèle `xx_ent_wiki_sm` ou équivalent chargé | ☐ |

> **STOP** si un check échoue. Résoudre avant de commencer l'implémentation.

---

## Critères de Succès Sprint 1

| Métrique | Cible | Mesure |
|----------|-------|--------|
| Relations promues | 5-10 | `MATCH (r:SemanticRelation) RETURN count(r)` |
| Précision | ≥ 95% | Audit manuel échantillon |
| Bundles rejetés | ≥ 60% | Ratio rejetés/générés |
| Couverture intra-section | 100% | Tous bundles = même section |

---

## Phase 1: Modèles de Données

### 1.1 Créer les modèles Pydantic

**Fichier**: `src/knowbase/relations/evidence_bundle_models.py`

```python
# À implémenter:
- [ ] EvidenceFragment (dataclass)
      - fragment_id: str
      - fragment_type: Literal["ENTITY_MENTION", "PREDICATE_LEXICAL", "PREDICATE_VISUAL", "COREFERENCE_LINK"]
      - text: str
      - source_context_id: str
      - source_page: Optional[int]
      - confidence: float
      - extraction_method: str

- [ ] EvidenceBundle (dataclass)
      - bundle_id: str
      - evidence_subject: EvidenceFragment
      - evidence_object: EvidenceFragment
      - evidence_predicate: List[EvidenceFragment]
      - evidence_link: Optional[EvidenceFragment]
      - subject_concept_id: str
      - object_concept_id: str
      - relation_type_candidate: str
      - typing_confidence: float
      - confidence: float  # min(all fragments)
      - document_id: str
      - validation_status: Literal["CANDIDATE", "PROMOTED", "REJECTED"]
      - rejection_reason: Optional[str]

- [ ] BundleValidationResult (dataclass)
      - is_valid: bool
      - rejection_reason: Optional[str]
      - checks_passed: List[str]
      - checks_failed: List[str]
```

### 1.2 Créer le schéma Neo4j

**Fichier**: `src/knowbase/relations/evidence_bundle_schema.py`

```cypher
# Contraintes à créer:
- [ ] CREATE CONSTRAINT evidence_bundle_id IF NOT EXISTS
      FOR (eb:EvidenceBundle) REQUIRE eb.bundle_id IS UNIQUE;

- [ ] CREATE CONSTRAINT semantic_relation_id IF NOT EXISTS
      FOR (sr:SemanticRelation) REQUIRE sr.relation_id IS UNIQUE;

# Index:
- [ ] CREATE INDEX bundle_status IF NOT EXISTS
      FOR (eb:EvidenceBundle) ON (eb.tenant_id, eb.validation_status);

- [ ] CREATE INDEX bundle_document IF NOT EXISTS
      FOR (eb:EvidenceBundle) ON (eb.tenant_id, eb.document_id);
```

---

## Phase 2: Détection des Candidats (Intra-Section)

### 2.1 Requête de co-présence intra-section

**Fichier**: `src/knowbase/relations/candidate_detector.py`

```python
# À implémenter:
- [ ] find_intra_section_pairs(document_id, tenant_id) -> List[CandidatePair]
```

**Requête Cypher**:
```cypher
-- Trouver les paires de concepts dans la MÊME section
-- ⚠️ IMPORTANT: On exige des charspans pour localiser les entités
MATCH (p1:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
      -[:INSTANCE_OF]->(c1:CanonicalConcept)
MATCH (p2:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
      -[:INSTANCE_OF]->(c2:CanonicalConcept)
WHERE c1.canonical_id < c2.canonical_id           -- Éviter doublons
  AND p1.context_id = p2.context_id               -- MÊME SECTION (Sprint 1)
  AND p1.context_id IS NOT NULL
  AND p1.char_start IS NOT NULL                   -- ⚠️ EXIGE charspan
  AND p2.char_start IS NOT NULL                   -- ⚠️ EXIGE charspan
RETURN
    c1.canonical_id AS subject_id,
    c1.label AS subject_label,
    c2.canonical_id AS object_id,
    c2.label AS object_label,
    p1.context_id AS shared_context_id,
    p1.definition AS subject_quote,
    p2.definition AS object_quote,
    p1.char_start AS subject_char_start,          -- ⚠️ Offset début
    p1.char_end AS subject_char_end,              -- ⚠️ Offset fin
    p2.char_start AS object_char_start,           -- ⚠️ Offset début
    p2.char_end AS object_char_end                -- ⚠️ Offset fin
```

> **⚠️ RÈGLE SPRINT 1**: Ne traiter que les ProtoConcepts qui ont un ancrage charspan
> (`char_start`/`char_end`) dans le `SectionContext.text`.
> Si charspan absent → ABSTAIN (pas de bundle créé).
> Cette règle évite 70% des problèmes de "localisation fuzzy".

### 2.2 Extraction du prédicat

**Fichier**: `src/knowbase/relations/predicate_extractor.py`

```python
# À implémenter:
- [ ] extract_predicate_from_context(doc, subject_span, object_span) -> Optional[PredicateCandidate]
- [ ] is_valid_predicate_structure(doc, token) -> bool
- [ ] get_predicate_between_entities(doc, subj_start, obj_end) -> Optional[Token]
- [ ] locate_entity_in_doc(doc, char_start, char_end, label) -> Optional[Span]
```

**Logique** (avec charspans garantis):
1. Charger le texte de la section (`SectionContext.text`)
2. Parser avec spaCy → `doc`
3. Localiser les entités via leurs charspans exacts :
   - `subject_span = doc.char_span(subject_char_start, subject_char_end)`
   - `object_span = doc.char_span(object_char_start, object_char_end)`
4. Si `char_span()` retourne `None` (alignement tokens) → fallback fuzzy sur `label`
5. Chercher le verbe principal entre les deux spans
6. Valider structure (POS/DEP, pas AUX, pas copule)

```python
def locate_entity_in_doc(
    doc,
    char_start: int,
    char_end: int,
    label: str  # Fallback si char_span échoue
) -> Optional[Span]:
    """
    Localise une entité dans le doc via ses offsets.

    Stratégie:
    1. char_span exact (préféré)
    2. char_span avec alignment_mode="expand"
    3. Fuzzy match sur label (dernier recours)
    """
    # 1. Exact
    span = doc.char_span(char_start, char_end)
    if span:
        return span

    # 2. Expand (si offset tombe entre tokens)
    span = doc.char_span(char_start, char_end, alignment_mode="expand")
    if span:
        return span

    # 3. Fuzzy fallback (chercher le label)
    label_lower = label.lower()
    for ent in doc.ents:
        if ent.text.lower() == label_lower:
            return ent

    # 4. Dernier recours: substring match
    for i, token in enumerate(doc):
        if label_lower in token.text.lower():
            return doc[i:i+1]

    return None  # ABSTAIN si non trouvé
```

---

## Phase 3: Validation des Bundles

### 3.1 Validateur de proximité (trivial en Sprint 1)

**Fichier**: `src/knowbase/relations/bundle_validator.py`

```python
# À implémenter:
- [ ] validate_proximity(bundle: EvidenceBundle) -> bool
      # Sprint 1: Toujours True car intra-section uniquement
```

### 3.2 Validateur modal/intentionnel (POS-based)

```python
# À implémenter:
- [ ] is_modal_or_intentional(doc, predicate_token) -> bool
      - Vérifier token.pos_ == "AUX"
      - Vérifier "Mood=Cnd" in token.morph
      - Vérifier has_infinitive_complement(token)

- [ ] has_infinitive_complement(token) -> bool
      - Chercher child avec dep_ in {"xcomp", "advcl"} et pos_ == "VERB"
```

### 3.3 Validateur copules/attributifs (AGNOSTIQUE LANGUE)

```python
# À implémenter:
# ⚠️ NOTE: On n'utilise PAS de liste de lemmes (be, have, do...)
#          On détecte structurellement via POS/DEP (Universal Dependencies)

- [ ] is_auxiliary_verb(token) -> bool
      """Rejette si POS = AUX (auxiliaires et copules)."""
      return token.pos_ == "AUX"

- [ ] is_copula_or_attributive(doc, token) -> bool
      """
      Détecte les copules et structures attributives.

      AGNOSTIQUE LANGUE: Universal Dependencies.

      Rejette:
      - "X is Y" / "X est Y" / "X ist Y" (copule)
      - "X has Y" (possessif simple sans prep)
      - Verbe avec dépendance "cop", "attr", "acomp"
      """
      # 1. Token a une dépendance copule
      if token.dep_ == "cop":
          return True

      # 2. Token gouverne un attribut
      for child in token.children:
          if child.dep_ in {"attr", "acomp", "oprd"}:
              return True

      # 3. Structure V + OBJ sans complément prépositionnel (faible)
      if token.dep_ == "ROOT" and token.pos_ == "VERB":
          has_obj = any(c.dep_ in {"dobj", "obj"} for c in token.children)
          has_prep = any(c.dep_ in {"prep", "prt"} or c.pos_ == "ADP" for c in token.children)
          if has_obj and not has_prep:
              return True  # "X has Y" sans prep = structure faible

      return False
```

### 3.4 Validateur complet

```python
# À implémenter:
- [ ] validate_bundle(bundle: EvidenceBundle, doc) -> BundleValidationResult
      1. validate_proximity (trivial Sprint 1)
      2. validate_predicate_not_auxiliary (POS = AUX)
      3. validate_predicate_not_copula (dep-based)
      4. validate_predicate_not_modal (POS + morph)
      5. validate_predicate_structure (SVO/SVprep)
```

---

## Phase 4: Calcul de Confiance

### 4.1 Score composite

**Fichier**: `src/knowbase/relations/confidence_calculator.py`

```python
# À implémenter:
- [ ] compute_bundle_confidence(bundle: EvidenceBundle) -> float
      return min(
          bundle.evidence_subject.confidence,
          bundle.evidence_object.confidence,
          min(ep.confidence for ep in bundle.evidence_predicate)
      )
```

### 4.2 Confiance des fragments

```python
# Sources de confiance:
- [ ] ENTITY_MENTION: utiliser proto.extract_confidence
- [ ] PREDICATE_LEXICAL: 0.8 si structure SVO claire, 0.6 sinon
```

---

## Phase 5: Persistance Neo4j

### 5.1 Persister EvidenceBundle

**Fichier**: `src/knowbase/relations/bundle_persistence.py`

```python
# À implémenter:
- [ ] persist_bundle(bundle: EvidenceBundle) -> str
```

**Requête Cypher**:
```cypher
CREATE (eb:EvidenceBundle {
    bundle_id: $bundle_id,
    tenant_id: $tenant_id,
    document_id: $document_id,
    subject_concept_id: $subject_id,
    object_concept_id: $object_id,
    relation_type_candidate: $relation_type,
    typing_confidence: $typing_confidence,
    confidence: $confidence,
    validation_status: $status,
    rejection_reason: $rejection_reason,
    created_at: datetime()
})
RETURN eb.bundle_id
```

### 5.2 Promouvoir en SemanticRelation

```python
# À implémenter:
- [ ] promote_bundle_to_relation(bundle_id: str) -> str
```

**Requête Cypher**:
```cypher
MATCH (eb:EvidenceBundle {bundle_id: $bundle_id, tenant_id: $tenant_id})
WHERE eb.validation_status = 'CANDIDATE'
MATCH (c1:CanonicalConcept {canonical_id: eb.subject_concept_id})
MATCH (c2:CanonicalConcept {canonical_id: eb.object_concept_id})

CREATE (sr:SemanticRelation {
    relation_id: randomUUID(),
    tenant_id: $tenant_id,
    relation_type: eb.relation_type_candidate,
    confidence: eb.confidence,
    source_bundle_id: eb.bundle_id,
    created_at: datetime()
})

CREATE (c1)-[:HAS_RELATION]->(sr)
CREATE (sr)-[:RELATES_TO]->(c2)
CREATE (eb)-[:PROMOTED_TO]->(sr)

SET eb.validation_status = 'PROMOTED'

RETURN sr.relation_id
```

---

## Phase 6: Orchestrateur Pass 3.5

### 6.1 Pipeline principal

**Fichier**: `src/knowbase/relations/evidence_bundle_resolver.py`

```python
# À implémenter:
- [ ] class EvidenceBundleResolver:
      def __init__(self, neo4j_client, nlp_model)

      def process_document(self, document_id: str, tenant_id: str) -> ProcessingResult:
          1. find_intra_section_pairs()
          2. Pour chaque paire:
             a. extract_predicate()
             b. build_bundle()
             c. validate_bundle()
             d. compute_confidence()
             e. persist_bundle()
          3. Pour bundles valides avec confidence >= 0.7:
             a. promote_bundle_to_relation()
          4. Retourner stats
```

### 6.2 Intégration dans le pipeline

**Fichier**: `src/knowbase/ingestion/queue/pass35_jobs.py` (nouveau)

```python
# À implémenter:
- [ ] process_pass35_evidence_bundles(document_id, tenant_id)
- [ ] Appeler après Pass 3, avant Pass 4
```

---

## Phase 7: Tests

### 7.1 Tests unitaires

**Fichier**: `tests/relations/test_evidence_bundle_validator.py`

```python
# Tests à écrire:
- [ ] test_modal_detection_english()
      "X can integrate with Y" → REJECTED (MODAL)

- [ ] test_modal_detection_french()
      "X peut s'intégrer avec Y" → REJECTED (MODAL)

- [ ] test_intentional_detection()
      "X is designed to connect to Y" → REJECTED (INTENTIONAL)

- [ ] test_generic_verb_rejection()
      "X is Y" → REJECTED (GENERIC_VERB)

- [ ] test_valid_predicate()
      "X integrates with Y" → ACCEPTED

- [ ] test_valid_predicate_french()
      "X s'intègre avec Y" → ACCEPTED

- [ ] test_confidence_min()
      fragments [0.9, 0.8, 0.7] → confidence = 0.7
```

### 7.2 Tests d'intégration

**Fichier**: `tests/relations/test_evidence_bundle_e2e.py`

```python
# Tests à écrire:
- [ ] test_intra_section_bundle_creation()
- [ ] test_bundle_promotion_to_relation()
- [ ] test_rejection_logged_correctly()
```

---

## Phase 8: Métriques et Logging

### 8.1 Métriques à logger

```python
# À la fin de process_document():
logger.info(
    f"[OSMOSE:Pass3.5] Document {document_id}: "
    f"pairs_found={pairs}, "
    f"bundles_created={created}, "
    f"bundles_rejected={rejected}, "
    f"bundles_promoted={promoted}, "
    f"rejection_reasons={reason_counts}"
)
```

### 8.2 Audit trail

Chaque bundle rejeté doit avoir:
- `rejection_reason` explicite
- Timestamp
- Fragments impliqués

---

## Ordre d'Implémentation Recommandé

| Étape | Tâche | Dépendances | Effort |
|-------|-------|-------------|--------|
| 1 | Modèles Pydantic (Phase 1.1) | - | 1h |
| 2 | Schéma Neo4j (Phase 1.2) | - | 30min |
| 3 | Requête co-présence (Phase 2.1) | 1,2 | 1h |
| 4 | Validateurs POS (Phase 3.2, 3.3) | - | 2h |
| 5 | Extraction prédicat (Phase 2.2) | 4 | 2h |
| 6 | Validateur complet (Phase 3.4) | 4,5 | 1h |
| 7 | Calcul confiance (Phase 4) | 1 | 30min |
| 8 | Persistance (Phase 5) | 1,2 | 1h |
| 9 | Orchestrateur (Phase 6.1) | 3-8 | 2h |
| 10 | Tests unitaires (Phase 7.1) | 4,5,6 | 2h |
| 11 | Intégration pipeline (Phase 6.2) | 9 | 1h |
| 12 | Tests e2e (Phase 7.2) | 11 | 1h |

**Effort total estimé**: ~15h

---

## Fichiers à Créer

```
src/knowbase/relations/
├── evidence_bundle_models.py      # Phase 1.1
├── evidence_bundle_schema.py      # Phase 1.2
├── candidate_detector.py          # Phase 2.1
├── predicate_extractor.py         # Phase 2.2
├── bundle_validator.py            # Phase 3
├── confidence_calculator.py       # Phase 4
├── bundle_persistence.py          # Phase 5
└── evidence_bundle_resolver.py    # Phase 6.1

src/knowbase/ingestion/queue/
└── pass35_jobs.py                 # Phase 6.2

tests/relations/
├── test_evidence_bundle_validator.py  # Phase 7.1
└── test_evidence_bundle_e2e.py        # Phase 7.2
```

---

## Validation Finale Sprint 1

Avant de passer au Sprint 2, vérifier:

- [ ] Au moins 5 relations promues
- [ ] 0 faux positifs sur échantillon de 10 relations
- [ ] Tous les bundles rejetés ont une `rejection_reason` explicite
- [ ] Logs `[OSMOSE:Pass3.5]` fonctionnels
- [ ] Tests passent (unit + e2e)

---

*Checklist Sprint 1 - Evidence Bundle Resolver - Safe Mode*
*Référence: ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md v1.3*
