# ADR - NormativeRule & SpecFact : Assertions Non-Relationnelles

**Statut**: ✅ **APPROVED – V1**
**Date**: 2026-01-21
**Validation**: 2026-01-21
**Auteurs**: Équipe OSMOSE
**Dépend de**: ADR Scope vs Assertion (BLOCKING, APPROVED)
**Contexte**: Capturer les informations "high-value" qui ne sont pas des relations A→B

---

## Validation V1

### Ce que V1 garantit

> V1 garantit : **extraction pattern-first** + **preuve locale obligatoire** + **non-traversable** + **scope-only applicability**.

### Conditions de validation (non négociables)

| Condition | Invariant | Garantie |
|-----------|-----------|----------|
| **No domain-coded predicates** | INV-AGN-01 | Tout domaine va dans `scope_tags`, jamais dans les prédicats |
| **Pattern-first is mandatory** | R1 | HYBRID ne structure que, ne décide jamais si c'est normatif |

### Non-goals V1 (itérations futures)

| Élément | Statut V1 | V1.x/V2 |
|---------|-----------|---------|
| Couverture multi-langues (DE, IT, ES, ...) | EN + FR | Extension lexiques |
| Patterns avancés (expressions idiomatiques) | Patterns de base | Enrichissement |
| Promotion complexe (scoring, merge) | Dédup simple | Pipeline complet |
| Traversabilité conditionnelle | Non-traversable | À évaluer |

---

### Historique des changements

| Version | Date | Changements |
|---------|------|-------------|
| V1 APPROVED | 2026-01-21 | Validation après review "architecte grincheux" |
| V0.2 REVIEW | 2026-01-21 | Intégration trous ChatGPT : DefendableStatement, ScopeAnchor, dédup, edge cases, INV-AGN-01 |
| V0.1 DRAFT | 2026-01-21 | Création initiale |

---

## Résumé exécutif

> **Beaucoup d'informations critiques dans les documents techniques ne sont pas des relations entre concepts.**

Les règles normatives ("TLS 1.2 is required") et les spécifications structurées ("Min RAM: 256GB") sont **défendables** mais ne rentrent pas dans le modèle `Subject → Predicate → Object`.

Cet ADR propose deux nouvelles classes d'assertions qui respectent les invariants evidence-first tout en capturant cette information "decision-grade".

---

## Contexte

### Le problème

Notre pipeline actuel cherche des **relations entre concepts** :
```
Concept A --[REQUIRES]--> Concept B
```

Mais les documents techniques contiennent énormément d'informations critiques qui ne sont pas des relations :

| Type | Exemple textuel | Valeur métier |
|------|-----------------|---------------|
| Règle normative | "All HTTP connections are to be configured with TLS 1.2+" | Obligation de sécurité |
| Seuil minimum | "Requires a minimum of 256GB RAM" | Sizing |
| Valeur par défaut | "Timeout defaults to 30 seconds" | Configuration |
| Spec structurée | Tableau "Parameter \| Value" | Référence technique |

Ces informations sont :
- ✅ **Défendables** (preuve locale explicite)
- ✅ **High-value** (utiles pour la prise de décision)
- ❌ **Non capturées** par l'extraction relationnelle actuelle

### Exemples multi-domaines (agnosticité)

> **IMPORTANT** : Ce système est **domain-agnostic**. Les mêmes primitives s'appliquent à tous les domaines.

| Domaine | NormativeRule | SpecFact |
|---------|---------------|----------|
| **IT Sécurité** | "All connections must use TLS 1.2+" | `Protocol: HTTPS` |
| **Automobile** | "Tyre pressure shall be maintained at 2.8 bar" | `Front: 2.8 bar / Rear: 3.0 bar` |
| **Médical** | "Maximum daily dose shall not exceed 4g" | `Dosage: 500mg every 6h` |
| **Réglementaire** | "Records shall be retained for minimum 5 years" | `Retention period: 5 years` |
| **Retail** | "Allergens must be clearly displayed" | `Allergens: nuts, gluten` |

**Même schéma, mêmes règles d'extraction.**

### Pourquoi ce n'est pas du Type 2

La tentation serait de créer des relations implicites :
```
❌ "TLS 1.2 required" → REQUIRES(Solution, TLS 1.2)  // Quel est le sujet ?
❌ "256GB RAM minimum" → REQUIRES(SAP HANA, 256GB)   // Relation inventée
```

Ces relations **inventent un sujet** qui n'est pas explicite dans la phrase.

La bonne approche est de capturer **l'énoncé normatif lui-même** comme assertion :
```
✅ "TLS 1.2 required" → NORMATIVE_RULE(TLS >= 1.2, REQUIRED)
✅ "256GB RAM minimum" → SPEC_FACT(RAM, MIN, 256GB)
```

---

## Décision

Nous introduisons deux nouvelles classes d'assertions qui complètent les relations inter-concepts :

### 1. NormativeRule (Règle normative)

> Une **NormativeRule** capture une obligation, interdiction ou recommandation explicite avec un marqueur modal.

**Structure** :
```python
class NormativeRule(BaseModel):
    rule_id: str
    tenant_id: str

    # Le sujet de la règle (ce qui est contraint)
    subject_text: str           # Ex: "HTTP connections", "password length"
    subject_concept_id: Optional[str]  # Si mappable à un concept connu

    # La modalité (force de l'obligation)
    modality: NormativeModality  # MUST, SHOULD, MAY, MUST_NOT, etc.

    # La contrainte ou valeur
    constraint_type: ConstraintType  # EQUALS, MIN, MAX, RANGE, ENUM
    constraint_value: str       # Ex: "TLS 1.2", "256GB", "8 characters"
    constraint_unit: Optional[str]  # Ex: "GB", "seconds", "characters"

    # Evidence (preuve locale)
    evidence_span: str          # La phrase source
    evidence_section: str       # Le scope setter (titre section)
    source_doc_id: str
    source_chunk_id: str

    # Traçabilité
    extraction_method: ExtractionMethod  # PATTERN ou HYBRID
    confidence: float
```

**Marqueurs détectés** (pattern-first) :
| Langue | Marqueurs MUST | Marqueurs SHOULD | Marqueurs MAY |
|--------|----------------|------------------|---------------|
| EN | must, shall, are to be, is required, required, mandatory | should, recommended, advisable | may, can, optional |
| FR | doit, doivent, obligatoire, requis, impératif | devrait, recommandé, conseillé | peut, peuvent, optionnel |

**Exemples** :
```
Texte: "All HTTP connections are to be configured with TLS 1.2 or higher"
→ NormativeRule(
    subject_text="HTTP connections",
    modality=MUST,
    constraint_type=MIN,
    constraint_value="TLS 1.2",
    evidence_span="All HTTP connections are to be configured with TLS 1.2 or higher"
)

Texte: "Passwords must be at least 8 characters"
→ NormativeRule(
    subject_text="Passwords",
    modality=MUST,
    constraint_type=MIN,
    constraint_value="8",
    constraint_unit="characters"
)
```

### 2. SpecFact (Fait structuré)

> Un **SpecFact** capture une valeur ou spécification extraite d'une structure tabulaire ou liste clé-valeur.

**Structure** :
```python
class SpecFact(BaseModel):
    fact_id: str
    tenant_id: str

    # L'attribut spécifié
    attribute_name: str         # Ex: "RAM", "Timeout", "Port"
    attribute_concept_id: Optional[str]  # Si mappable

    # Le type de spécification
    spec_type: SpecType         # VALUE, MIN, MAX, DEFAULT, RANGE

    # La valeur
    value: str                  # Ex: "256", "30", "8080"
    unit: Optional[str]         # Ex: "GB", "seconds", ""

    # Contexte structurel (la preuve)
    source_structure: StructureType  # TABLE, KEY_VALUE_LIST, BULLET_LIST
    structure_context: str      # Ex: "System Requirements table"
    row_header: Optional[str]   # Pour les tableaux
    column_header: Optional[str]

    # Evidence
    evidence_text: str          # Le texte brut de la cellule/ligne
    evidence_section: str       # Scope setter
    source_doc_id: str
    source_chunk_id: str

    # Traçabilité
    extraction_method: ExtractionMethod
    confidence: float
```

**Structures détectées** :
| Type | Pattern | Exemple |
|------|---------|---------|
| TABLE | Header row + data rows | `| Parameter | Value |` |
| KEY_VALUE_LIST | `Label: Value` ou `Label = Value` | `Timeout: 30s` |
| BULLET_LIST | `- Label: Value` | `- Min RAM: 256GB` |

**Exemples** :
```
Structure: Tableau "System Requirements"
| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM       | 256GB   | 512GB       |

→ SpecFact(
    attribute_name="RAM",
    spec_type=MIN,
    value="256",
    unit="GB",
    source_structure=TABLE,
    structure_context="System Requirements",
    row_header="RAM",
    column_header="Minimum"
)

→ SpecFact(
    attribute_name="RAM",
    spec_type=RECOMMENDED,
    value="512",
    unit="GB",
    ...
)
```

---

## Enums associés

```python
class NormativeModality(str, Enum):
    """Force de l'obligation normative."""
    MUST = "MUST"           # Obligation (shall, must, required)
    MUST_NOT = "MUST_NOT"   # Interdiction (must not, shall not)
    SHOULD = "SHOULD"       # Recommandation forte
    SHOULD_NOT = "SHOULD_NOT"
    MAY = "MAY"             # Permission/Option

class ConstraintType(str, Enum):
    """Type de contrainte."""
    EQUALS = "EQUALS"       # Valeur exacte
    MIN = "MIN"             # Minimum (>=)
    MAX = "MAX"             # Maximum (<=)
    RANGE = "RANGE"         # Entre min et max
    ENUM = "ENUM"           # Liste de valeurs possibles
    PATTERN = "PATTERN"     # Format (regex, etc.)

class SpecType(str, Enum):
    """Type de spécification."""
    VALUE = "VALUE"         # Valeur simple
    MIN = "MIN"             # Minimum
    MAX = "MAX"             # Maximum
    DEFAULT = "DEFAULT"     # Valeur par défaut
    RECOMMENDED = "RECOMMENDED"

class StructureType(str, Enum):
    """Type de structure source."""
    TABLE = "TABLE"
    KEY_VALUE_LIST = "KEY_VALUE_LIST"
    BULLET_LIST = "BULLET_LIST"
    DEFINITION_LIST = "DEFINITION_LIST"
```

---

## Invariants

### INV-NORM-01 : Preuve locale obligatoire

> Toute NormativeRule ou SpecFact **DOIT** avoir une preuve textuelle locale (span ou cellule).

Le contexte documentaire (titre du doc, section parente) est un **scope**, pas une preuve.

### INV-NORM-02 : Marqueur explicite requis

> Une NormativeRule **DOIT** contenir un marqueur modal détectable (must/shall/required/etc.).

Pas de déduction de modalité depuis le contexte.

### INV-NORM-03 : Structure explicite pour SpecFact

> Un SpecFact **DOIT** provenir d'une structure identifiable (tableau, liste clé-valeur).

Pas d'extraction de "valeurs" depuis du texte libre sans structure.

### INV-NORM-04 : Pas de sujet inventé

> Le sujet d'une règle ou spec est **ce qui est explicitement mentionné**, pas ce qu'on déduit du contexte.

```
❌ "256GB required" dans un doc S/4HANA → subject = "S/4HANA"  // Inventé
✅ "256GB required" dans un doc S/4HANA → subject = "RAM" ou null  // Explicite
```

### INV-AGN-01 : Domain-Agnostic Semantics (CRITIQUE)

> Aucun `RelationType`, `NormativeModality`, `ConstraintType` ou `SpecType` ne doit encoder un domaine métier.

**Les prédicats sont des primitives trans-domaines ; le domaine est porté par le scope et les tags.**

```
❌ RISE_CUSTOMER_RESPONSIBILITY     // Domain-coded
❌ SAP_MANAGED_SERVICE              // Domain-coded
❌ MEDICAL_DOSAGE_LIMIT             // Domain-coded

✅ MUST / MUST_NOT / SHOULD / MAY   // Universal modalities
✅ MIN / MAX / EQUALS / RANGE       // Universal constraints
✅ scope_tags: ["security", "sap", "rise"]  // Domain in tags
```

**Test d'agnosticité** : Avant d'ajouter un type/prédicat, vérifier :

> "Est-ce que cette règle fonctionnerait sur un manuel d'aspirateur Dyson, un protocole clinique, et une norme ISO — sans modification ?"

- Si **non** et c'est du **contenu dépendant du doc** → mettre dans `scope_tags`
- Si **non** et c'est une **configuration** → paramètre configurable
- Si **non** autrement → **règle codée en dur à éviter**

---

## Intégration avec l'architecture existante

### Décision : Option B — Entités séparées avec interface commune

**DÉCISION PRISE** : Option B avec `DefendableStatement` comme interface commune.

```
┌─────────────────────────────────────────────────────────────────┐
│                    DefendableStatement (Protocol)                │
│  - statement_id: str                                            │
│  - tenant_id: str                                               │
│  - evidence_span: str                                           │
│  - source_doc_id: str                                           │
│  - source_chunk_id: str                                         │
│  - extraction_method: ExtractionMethod                          │
│  - confidence: float                                            │
│  - scope_anchors: List[ScopeAnchor]  # Pour retrouver, pas prouver│
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ SemanticRelation│   │ SemanticRule    │   │ SemanticFact    │
│ (graph edges)   │   │ (from Normative)│   │ (from SpecFact) │
│ A --[REL]--> B  │   │ subject MUST X  │   │ attr = value    │
│ TRAVERSABLE     │   │ NON-TRAVERSABLE │   │ NON-TRAVERSABLE │
└───────────────┘   └─────────────────┘   └─────────────────┘
```

**Rationale** :
- Les relations (SemanticRelation) sont des **edges** concept→concept → traversables
- Les règles et faits sont des **énoncés autonomes** → non-traversables, mais indexables et requêtables

### Pipeline de promotion (v1 simplifié)

```
┌──────────────┐          ┌─────────────────┐          ┌─────────────────┐
│ NormativeRule │ ──dedup──► │ CanonicalRule   │ ──promote─► │ SemanticRule    │
│ (raw extract) │          │ (deduplicated)  │          │ (queryable)     │
└──────────────┘          └─────────────────┘          └─────────────────┘

┌──────────────┐          ┌─────────────────┐          ┌─────────────────┐
│ SpecFact     │ ──dedup──► │ CanonicalFact   │ ──promote─► │ SemanticFact    │
│ (raw extract) │          │ (deduplicated)  │          │ (queryable)     │
└──────────────┘          └─────────────────┘          └─────────────────┘
```

**v1** : pas de promotion complexe, juste stockage + déduplication.

### Décision : Non-traversabilité

> **DÉCISION** : NormativeRule et SpecFact sont **NON-TRAVERSABLES** par défaut.

Ils sont :
- ✅ **Indexables** (recherche par attribut, modalité, valeur)
- ✅ **Filtrables par scope** (doc.topic, section.scope)
- ✅ **Requêtables** (API directe)
- ✅ **Citables** (evidence traçable)
- ❌ **Non-traversables** (pas de graph walk)

La traversée (mode Reasoned) reste réservée aux `SemanticRelation`.

### Relation avec Scope Layer

Les NormativeRule et SpecFact bénéficient du scope sans en dépendre :

```
┌─ Scope Layer ─────────────────────────────────┐
│ Document: "S/4HANA Security Guide"            │
│ Section: "Network Configuration"              │
└───────────────────────────────────────────────┘
                    ↓ (ancrage, pas preuve)
┌─ Assertion Layer ─────────────────────────────┐
│ NormativeRule: TLS >= 1.2, MUST               │
│ Evidence: "connections are to be configured"  │
└───────────────────────────────────────────────┘
```

Le scope permet de **retrouver** la règle (filtrage Anchored), pas de la **prouver**.

### ScopeAnchor — Portée d'applicabilité (sans assertion)

Pour répondre à "Montre-moi les règles applicables à X" **sans créer de relation fausse** :

```python
class ScopeAnchor(BaseModel):
    """Ancrage non-traversable d'une règle/fact dans le scope."""
    doc_id: str
    section_id: Optional[str]
    scope_setter_ids: List[str]  # Titres, captions qui définissent le scope
    scope_tags: List[str]        # Dérivés des scope setters, pas du LLM
```

**Usage** :
```
Query: "Montre les règles applicables à S/4HANA"
1. Filter doc.topic = "S/4HANA"
2. Return NormativeRule WHERE scope_anchors.doc_id IN filtered_docs
3. → Règles trouvées par scope, pas par relation inventée
```

**Invariant** : `scope_tags` sont dérivés des **scope setters documentaires** (titres, headers), jamais inférés par LLM.

### Déduplication et Canonicalisation

> Éviter 25 fois "TLS>=1.2" recopié sur 25 slides.

**Clé de déduplication NormativeRule** :
```python
def dedup_key_rule(rule: NormativeRule) -> str:
    """Clé unique pour déduplication."""
    return f"{normalize(rule.subject_text)}|{rule.modality}|{rule.constraint_type}|{normalize(rule.constraint_value)}|{rule.constraint_unit or ''}"

# Exemples :
# "HTTP_CONNECTIONS|MUST|MIN|TLS_1.2|"
# "PASSWORD_LENGTH|MUST|MIN|8|CHARACTERS"
```

**Clé de déduplication SpecFact** :
```python
def dedup_key_fact(fact: SpecFact) -> str:
    """Clé unique pour déduplication."""
    return f"{normalize(fact.attribute_name)}|{fact.spec_type}|{normalize(fact.value)}|{fact.unit or ''}"

# Exemples :
# "RAM|MIN|256|GB"
# "TIMEOUT|DEFAULT|30|SECONDS"
```

**Métriques de couverture** (sur entité canonique) :
```python
class CanonicalRule(BaseModel):
    canonical_key: str           # Clé de dédup
    doc_coverage: int            # Nombre de documents distincts
    section_coverage: int        # Nombre de sections distinctes
    raw_rule_ids: List[str]      # Liens vers extractions brutes
    first_seen_doc_id: str       # Pour traçabilité
```

**v1 simplifié** : déduplication à l'écriture, pas de promotion complexe.

---

## Pipeline d'extraction

### Pour NormativeRule

```
1. Pattern Matcher détecte marqueur modal (must/shall/required/etc.)
2. Parser extrait :
   - subject_text (ce qui est contraint)
   - constraint (la valeur/seuil)
3. [Optionnel] LLM valide et structure (HYBRID)
4. Écriture NormativeRule avec evidence
```

### Pour SpecFact

```
1. Structure Detector identifie tableau/liste
2. Parser extrait :
   - headers (contexte)
   - cells (valeurs)
   - labels (attributs)
3. Pour chaque paire attribut-valeur :
   - Créer SpecFact
   - Attacher evidence structurelle
```

---

## Edge cases linguistiques et règles de désambiguïsation

> **Objectif** : Éviter la "normativité fantôme" (Type 2 déguisé en règle)

### Cas problématiques à gérer

| Cas | Exemple | Traitement |
|-----|---------|------------|
| **Négation** | "must not", "shall not", "no X allowed" | Extraire comme `MUST_NOT` avec constraint explicite |
| **Conditionnels** | "if", "when", "in case of" | Exiger `constraint_condition_span` ou ABSTAIN |
| **"Unless" (exception)** | "must X unless Y" | Capturer condition dans champ dédié |
| **"Can" ambigu** | "can be configured" | ABSTAIN sauf si autres marqueurs présents |
| **Portée universelle** | "all", "only", "at least" | Inclure dans subject_text ("all connections") |
| **Versions/ranges** | "TLS 1.2+", ">=256GB", "1.2 or higher" | Parser comme constraint_type=MIN |

### Règles de désambiguïsation

**R1 — PATTERN obligatoire, HYBRID optionnel pour structurer**
```
✅ NormativeRule extraction = PATTERN détecte le marqueur
✅ HYBRID autorisé pour structurer subject/constraint
❌ HYBRID interdit pour décider si c'est normatif
```

**R2 — Conditionnel détecté → champ obligatoire ou ABSTAIN**
```python
if conditional_detected:  # if/when/unless/in case of
    if constraint_condition_span:
        # OK, condition capturée
        pass
    else:
        # ABSTAIN - on ne sait pas la condition
        return None
```

**R3 — "Can" seul → ABSTAIN**
```
"can be used" → ABSTAIN (capacité ou permission ?)
"can and should be used" → MAY (confirmation par "should")
"users can optionally enable" → MAY ("optional" confirme)
```

**R4 — Négation → modalité négative explicite**
```
"must not exceed" → MUST_NOT + constraint_type=MAX
"no connections allowed" → MUST_NOT + constraint=0
"shall not be used" → MUST_NOT
```

### Tests de régression — Edge cases

```python
EDGE_CASE_TESTS = [
    # Négations
    ("Passwords must not exceed 128 characters", MUST_NOT, MAX, "128"),
    ("No plaintext connections allowed", MUST_NOT, EQUALS, "0"),

    # Conditionnels → ABSTAIN si condition non capturée
    ("If using cloud, TLS is required", ABSTAIN),  # Condition = "using cloud"
    ("TLS required when connecting externally", CONDITIONAL, "connecting externally"),

    # "Can" ambigu
    ("The system can process 1000 req/s", ABSTAIN),  # Capacité, pas permission
    ("Users can optionally enable dark mode", MAY, "enable dark mode"),

    # Versions/ranges
    ("TLS 1.2 or higher required", MUST, MIN, "TLS 1.2"),
    ("Maximum 256GB supported", None, MAX, "256"),  # Pas de modalité !
]
```

---

## Cas d'usage

### Cas 1 : Recherche de prérequis

```
User: "What are the minimum requirements for S/4HANA?"

1. Scope filter: doc.topic contains "S/4HANA"
2. Query NormativeRule: modality IN (MUST, REQUIRED)
3. Query SpecFact: spec_type = MIN
4. Return: Liste de règles et specs avec citations
```

### Cas 2 : Audit de conformité

```
User: "Show all security requirements"

1. Scope filter: section.scope contains "security"
2. Query NormativeRule: subject_text matches security patterns
3. Return: Liste de règles normatives avec modalité et evidence
```

### Cas 3 : Configuration reference

```
User: "What are the default timeout values?"

1. Query SpecFact: spec_type = DEFAULT, attribute contains "timeout"
2. Return: Liste de specs avec source structurelle
```

---

## Métriques de succès

| Métrique | Cible | Rationale |
|----------|-------|-----------|
| NormativeRule extraites | +30% infos capturées | Règles = high-value |
| SpecFact extraites | +50% infos capturées | Tableaux = très denses |
| Précision NormativeRule | ≥ 95% | Marqueurs modaux = fiables |
| Précision SpecFact | ≥ 90% | Structures = moins ambiguës |
| FP Type 2 | 0% | Invariant absolu |

---

## Tests de régression

```python
NORMATIVE_REGRESSION_CASES = [
    # DOIT extraire
    ("All connections must use TLS 1.2", NormativeRule, MUST, "TLS 1.2"),
    ("Passwords shall be at least 8 characters", NormativeRule, MUST, "8"),
    ("It is recommended to use 512GB RAM", NormativeRule, SHOULD, "512GB"),

    # NE DOIT PAS extraire (pas de marqueur modal)
    ("TLS 1.2 provides better security", None),  # Pas d'obligation
    ("Many customers use 256GB RAM", None),      # Pas de règle
]

SPECFACT_REGRESSION_CASES = [
    # DOIT extraire (structure explicite)
    ("| RAM | 256GB |", SpecFact, "RAM", "256GB"),
    ("Timeout: 30 seconds", SpecFact, "Timeout", "30"),

    # NE DOIT PAS extraire (pas de structure)
    ("The system needs about 256GB", None),  # Texte libre
]
```

---

## Prochaines étapes

1. ✅ **Valider l'ADR** avec l'équipe (Status: APPROVED V1)
2. ✅ **Implémenter les enums** dans `types.py` - `NormativeModality`, `ConstraintType`, `SpecType`, `StructureType`
3. ✅ **Créer les modèles** `NormativeRule` et `SpecFact` dans `types.py`
4. ✅ **Implémenter le NormativePatternExtractor** - `normative_pattern_extractor.py`
5. ✅ **Implémenter le StructureParser** - `structure_parser.py`
6. ✅ **Intégrer dans Pass 2** - Phase 2c `NORMATIVE_EXTRACTION` dans `pass2_orchestrator.py` (2026-01-22)
7. ✅ **Tests de régression** - `test_normative_extractors.py` (28 tests) + `test_normative_writer.py` (22 tests)

### Implémentation Pass 2c (2026-01-22)

Nouveaux fichiers:
- `src/knowbase/relations/normative_writer.py` - Writer Neo4j pour NormativeRule/SpecFact

Modifications:
- `src/knowbase/ingestion/pass2_orchestrator.py` - Ajout phase `NORMATIVE_EXTRACTION`
- `src/knowbase/relations/__init__.py` - Export `NormativeWriter`, `get_normative_writer`

Pipeline Pass 2c:
1. `NormativePatternExtractor.extract_from_text()` → `List[NormativeRule]`
2. `StructureParser.extract_from_text()` → `List[SpecFact]`
3. `NormativeWriter.write_rules()` / `.write_facts()` → Neo4j avec déduplication
4. `NormativeWriter.link_to_document()` → Relations `EXTRACTED_FROM`

---

## Références

- [ADR_SCOPE_VS_ASSERTION_SEPARATION.md](./ADR_SCOPE_VS_ASSERTION_SEPARATION.md) - Séparation Scope/Assertion
- [ADR_DISCURSIVE_RELATIONS.md](./ADR_DISCURSIVE_RELATIONS.md) - Relations discursives
- [ADR_DISCURSIVE_RELATIONS_BACKLOG.md](./ADR_DISCURSIVE_RELATIONS_BACKLOG.md) - Backlog implémentation
- Discussion ChatGPT - Proposition NormativeRule/SpecFact (2026-01-21)
- Review ChatGPT - "Architecte grincheux" : 3 trous + 2 décisions + agnosticité (2026-01-21)
