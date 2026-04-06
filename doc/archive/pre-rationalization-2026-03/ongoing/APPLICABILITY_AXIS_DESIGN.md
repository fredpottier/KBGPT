# Design Document: Applicability Axis — Raisonnement Temporel/Contextuel Claim-First

**Date:** 2026-02-04
**Branche cible:** `feat/applicability-axis`
**Statut:** DRAFT - En attente validation

---

## 1. Contexte & Problème

### 1.1 Constat

Le pipeline Claim-First actuel extrait et persiste des claims documentées avec leur contexte d'applicabilité (`DocumentContext.qualifiers`). Cependant, il manque la capacité de **raisonner sur l'évolution** des claims à travers différents contextes ordonnables.

### 1.2 Valeur Différenciante Visée

| RAG Simple | Claim-First + Applicability Axis |
|------------|----------------------------------|
| Retrouve des passages | Raisonne sur des affirmations documentées |
| Répond "oui/non" | Répond "documenté dans contexte X, pas dans Y" |
| Contexte = filtrage | Contexte = axe de comparaison |
| Statique | Évolutif (depuis quand, encore applicable) |

### 1.3 Corpus de Validation

Documents de test (même sujet, contextes ordonnables) :
- `018_S4HANA_1809_BUSINESS_SCOPE_MASTER_L23.pdf` (version 1809)
- `025_SAP_S4HANA_2023_Feature_Scope_Description.pdf` (version 2023)
- `023_1212_Business-Scope-2025-SAP-Cloud-ERP-Private.pdf` (version 2025)

⚠️ **Contrainte absolue** : Solution 100% agnostique domaine.

---

## 2. Diagnostic de l'Existant

### 2.1 Ce Qui Existe Déjà (Réutilisable)

| Composant | Fichier | Capacité | Lacune |
|-----------|---------|----------|--------|
| **DocumentContext** | `models/document_context.py` | `qualifiers: Dict`, `qualifier_candidates: Dict`, `temporal_scope: str` | Pas de notion d'ordonnabilité |
| **SubjectAnchor** | `models/subject_anchor.py` | `qualifiers_validated`, `qualifiers_candidates` | Pas de notion d'axe de comparaison |
| **ContextExtractor** | `extractors/context_extractor.py` | Patterns bootstrap (version, region, edition) | Pas de détection d'ordonnabilité |
| **ScopedQueryEngine** | `query/scoped_query.py` | Résolution sujet avant query, filtrage par scope | Pas de comparaison inter-contextes |
| **ClaimCluster** | `models/result.py` | Agrégation inter-documents | Pas d'alignement par axe |

### 2.2 Points d'Extension Identifiés

```
INGESTION (enrichissement)
├── ContextExtractor
│   └── [NOUVEAU] ApplicabilityAxisDetector
│       - Détecter qualifiers ordonnables
│       - Inférer type d'ordre (numérique, date, version)
│       - Calculer comparabilité entre docs

PERSISTENCE (nouveau schéma)
├── claim_persister.py
│   └── [MODIFIER] Persister ApplicabilityAxis
│   └── [NOUVEAU] Relations COMPARABLE_WITH, SUPERSEDES

QUERY (nouveau engine)
├── [NOUVEAU] TemporalQueryEngine
│   - Questions "depuis quand"
│   - Questions "encore applicable"
│   - Policy "latest"
│   - Validation de texte
```

### 2.3 Ce Qui Manque Réellement

1. **Modèle d'Axe Ordonnable** — Représenter qu'un qualifier est ordonnable
2. **Détecteur d'Ordonnabilité** — Inférer si un qualifier est comparable
3. **Comparateur de Contextes** — Déterminer si deux DocumentContext sont comparables
4. **Policy "Latest"** — Définir le contexte par défaut
5. **Query Engine Temporel** — Répondre aux questions A/B/C/D
6. **Stratégie d'Abstention** — Quand ne pas répondre

---

## 3. Modèle de Données Proposé

### 3.1 ApplicabilityAxis (Nouvel Objet)

```python
# src/knowbase/claimfirst/models/applicability_axis.py

class OrderType(str, Enum):
    """Type d'ordonnabilité d'un axe."""
    NUMERIC = "numeric"           # 1, 2, 3... ou 1809, 2023, 2025
    CHRONOLOGICAL = "chronological"  # Dates, années
    SEMANTIC_VERSION = "semantic_version"  # 1.0.0, 2.1.3
    ORDINAL = "ordinal"           # Phase 1, Phase 2... ou Generation 1, 2
    UNORDERED = "unordered"       # Région, édition (pas d'ordre naturel)
    UNKNOWN = "unknown"           # Pas assez de données

class ApplicabilityAxis(BaseModel):
    """
    Axe d'applicabilité découvert depuis le corpus.

    Un axe représente une dimension de comparaison entre documents.
    Exemple: "version" est un axe ordonnable (1809 < 2023 < 2025).

    INV-10 RESPECTÉ: Découvert du corpus, jamais hardcodé.
    """
    axis_id: str                          # "axis_{tenant}_{key}"
    tenant_id: str

    # Identification
    axis_key: str                         # Clé du qualifier: "version", "year", etc.
    axis_label: str                       # Label lisible: "Product Version"

    # Ordonnabilité
    order_type: OrderType
    is_orderable: bool                    # True si comparaison possible
    order_confidence: float               # [0-1] confiance dans l'ordre

    # Valeurs observées (corpus-driven)
    observed_values: List[str]            # ["1809", "2023", "2025"]
    value_order: Optional[List[str]]      # Ordre calculé si orderable

    # Couverture corpus
    doc_count: int                        # Nombre de docs avec cet axe
    coverage_ratio: float                 # Proportion du corpus couvert

    # Métadonnées
    detection_method: str                 # "pattern" | "llm" | "manual"
    created_at: datetime
    updated_at: datetime

    def compare(self, value_a: str, value_b: str) -> Optional[int]:
        """
        Compare deux valeurs sur cet axe.

        Returns:
            -1 si a < b, 0 si a == b, 1 si a > b, None si non comparable
        """
        if not self.is_orderable or self.value_order is None:
            return None

        try:
            idx_a = self.value_order.index(value_a)
            idx_b = self.value_order.index(value_b)
            return (idx_a > idx_b) - (idx_a < idx_b)
        except ValueError:
            return None  # Valeur inconnue
```

### 3.2 ContextComparability (Relation Entre Documents)

```python
# src/knowbase/claimfirst/models/context_comparability.py

class ComparabilityStatus(str, Enum):
    """Statut de comparabilité entre deux contextes."""
    COMPARABLE = "comparable"           # Même sujet, axe commun ordonné
    DISJOINT = "disjoint"               # Sujets différents ou scopes non recouvrants
    PARTIAL = "partial"                 # Partiellement comparable (certains axes)
    UNKNOWN = "unknown"                 # Pas assez d'information

class ContextComparability(BaseModel):
    """
    Relation de comparabilité entre deux DocumentContext.

    Détermine si deux documents peuvent être comparés sur un axe donné.
    """
    doc_id_a: str
    doc_id_b: str
    tenant_id: str

    # Comparabilité globale
    status: ComparabilityStatus

    # Détail par axe
    comparable_axes: List[str]            # Axes où comparaison possible
    disjoint_axes: List[str]              # Axes incompatibles

    # Ordre relatif (si comparable)
    ordering: Optional[Dict[str, int]]    # {"version": -1} = A avant B sur version

    # Confiance
    confidence: float                     # [0-1]
    abstention_reason: Optional[str]      # Si non comparable, pourquoi

class LatestContextPolicy(BaseModel):
    """
    Policy pour déterminer le contexte "latest".

    Configurable par tenant et/ou sujet.
    """
    policy_id: str
    tenant_id: str
    subject_id: Optional[str]             # Si None, policy par défaut tenant

    # Axe principal de comparaison
    primary_axis: str                     # "version", "year", etc.
    fallback_axes: List[str]              # Si primary non disponible

    # Comportement en cas d'ambiguïté
    on_ambiguity: str                     # "ask" | "abstain" | "show_all"

    # Métadonnées
    is_default: bool
    created_at: datetime
```

### 3.3 Extension de DocumentContext

```python
# Ajouts à DocumentContext existant

class DocumentContext(BaseModel):
    # ... champs existants ...

    # NOUVEAUX CHAMPS
    applicable_axes: List[str] = []       # Axes détectés pour ce doc
    axis_values: Dict[str, str] = {}      # {"version": "2023", "region": "EU"}
    comparability_computed: bool = False  # Cache de comparabilité calculé
```

### 3.4 Schéma Neo4j Étendu

```cypher
// Nouveaux nœuds
(:ApplicabilityAxis {
    axis_id: string,
    tenant_id: string,
    axis_key: string,
    axis_label: string,
    order_type: string,
    is_orderable: boolean,
    order_confidence: float,
    observed_values: [string],
    value_order: [string],  // NULL si non orderable
    doc_count: int,
    coverage_ratio: float,
    detection_method: string
})

// Nouvelles relations
(DocumentContext)-[:HAS_AXIS_VALUE {value: string}]->(ApplicabilityAxis)
(DocumentContext)-[:COMPARABLE_WITH {
    status: string,
    comparable_axes: [string],
    ordering_json: string  // {"version": -1}
}]->(DocumentContext)
(DocumentContext)-[:SUPERSEDES {
    axis: string,
    confidence: float
}]->(DocumentContext)

// Index
CREATE INDEX axis_key_idx FOR (a:ApplicabilityAxis) ON (a.tenant_id, a.axis_key)
CREATE INDEX doc_axis_idx FOR ()-[r:HAS_AXIS_VALUE]-() ON (r.value)
```

---

## 4. Plan d'Implémentation

### 4.1 Nouveaux Modules

| Module | Fichier | Responsabilité |
|--------|---------|----------------|
| **ApplicabilityAxisDetector** | `extractors/axis_detector.py` | Détecter axes ordonnables depuis corpus |
| **AxisOrderInferrer** | `extractors/axis_order_inferrer.py` | Inférer type d'ordre et calculer ordre |
| **ContextComparator** | `resolution/context_comparator.py` | Calculer comparabilité entre docs |
| **TemporalQueryEngine** | `query/temporal_query_engine.py` | Répondre questions A/B/C/D |
| **LatestPolicyResolver** | `query/latest_policy_resolver.py` | Résoudre "latest" selon policy |
| **TextValidator** | `query/text_validator.py` | Valider texte utilisateur vs corpus |

### 4.2 Fichiers à Créer

```
src/knowbase/claimfirst/
├── models/
│   ├── applicability_axis.py       # [CRÉER] ApplicabilityAxis, OrderType
│   └── context_comparability.py    # [CRÉER] ContextComparability, LatestContextPolicy
├── extractors/
│   ├── axis_detector.py            # [CRÉER] ApplicabilityAxisDetector
│   └── axis_order_inferrer.py      # [CRÉER] AxisOrderInferrer
├── resolution/
│   └── context_comparator.py       # [CRÉER] ContextComparator
├── query/
│   ├── temporal_query_engine.py    # [CRÉER] TemporalQueryEngine
│   ├── latest_policy_resolver.py   # [CRÉER] LatestPolicyResolver
│   └── text_validator.py           # [CRÉER] TextValidator
└── persistence/
    └── axis_persister.py           # [CRÉER] Persistance axes Neo4j
```

### 4.3 Fichiers à Modifier

```
src/knowbase/claimfirst/
├── orchestrator.py                 # Ajouter phase AxisDetection
├── models/document_context.py      # Ajouter axis_values, applicable_axes
├── extractors/context_extractor.py # Intégrer AxisDetector
├── persistence/claim_persister.py  # Persister axes et comparabilités
└── persistence/neo4j_schema.py     # Ajouter contraintes/indexes axes

src/knowbase/api/
├── routers/claimfirst.py           # Endpoints temporels
└── schemas/claimfirst.py           # Schemas request/response
```

### 4.4 APIs Internes

```python
# AxisDetector
class ApplicabilityAxisDetector:
    async def detect_axes(
        self,
        doc_contexts: List[DocumentContext]
    ) -> List[ApplicabilityAxis]:
        """Détecte axes depuis ensemble de DocumentContext."""

    async def infer_orderability(
        self,
        axis_key: str,
        values: List[str]
    ) -> Tuple[OrderType, float]:
        """Infère si un axe est ordonnable et avec quelle confiance."""

# ContextComparator
class ContextComparator:
    async def compute_comparability(
        self,
        doc_a: DocumentContext,
        doc_b: DocumentContext,
        axes: List[ApplicabilityAxis]
    ) -> ContextComparability:
        """Calcule relation de comparabilité entre deux docs."""

    async def find_comparable_docs(
        self,
        doc_context: DocumentContext,
        candidate_docs: List[DocumentContext]
    ) -> List[Tuple[DocumentContext, ContextComparability]]:
        """Trouve tous les docs comparables à un doc donné."""

# TemporalQueryEngine
class TemporalQueryEngine:
    async def query_since_when(
        self,
        capability_description: str,
        subject_id: Optional[str] = None
    ) -> SinceWhenResponse:
        """Question A: Depuis quand cette capacité existe?"""

    async def query_still_applicable(
        self,
        capability_description: str,
        target_context: Optional[str] = None
    ) -> ApplicabilityResponse:
        """Question B: Cette capacité est-elle encore applicable?"""

    async def validate_text(
        self,
        user_text: str,
        target_context: Optional[str] = None
    ) -> TextValidationResponse:
        """Question D: Valider affirmation utilisateur."""

# LatestPolicyResolver
class LatestPolicyResolver:
    async def resolve_latest(
        self,
        subject_id: Optional[str],
        available_contexts: List[DocumentContext]
    ) -> LatestResolutionResult:
        """Résout le contexte 'latest' selon policy."""
```

---

## 5. Stratégie d'Abstention

### 5.1 Règles d'Abstention

| Situation | Comportement | Message Type |
|-----------|--------------|--------------|
| Aucun axe ordonnable détecté | **ABSTAIN** | "Cannot determine temporal ordering" |
| Axes multiples ambigus | **ASK** | "Multiple axes found: version, year. Which one?" |
| Documents non comparables | **EXPLAIN** | "Documents cover disjoint scopes" |
| Capability non trouvée | **NOT_DOCUMENTED** | "Not documented in corpus" |
| Trouvée avant mais pas dans latest | **UNCERTAIN** | "Documented in v2023, not in v2025 (may persist)" |
| Suppression explicite | **REMOVED** | "Explicitly removed in v2025" |

### 5.2 Réponses Structurées

```python
class TemporalQueryStatus(str, Enum):
    CONFIRMED = "confirmed"           # Documenté dans contexte cible
    NOT_DOCUMENTED = "not_documented" # Pas trouvé
    UNCERTAIN = "uncertain"           # Présent avant, pas dans latest
    REMOVED = "removed"               # Suppression explicite documentée
    CONTRADICTED = "contradicted"     # Contredit par autre claim
    INCOMPARABLE = "incomparable"     # Scopes non comparables
    AMBIGUOUS = "ambiguous"           # Besoin clarification

class SinceWhenResponse(BaseModel):
    status: TemporalQueryStatus

    # Si trouvé
    first_occurrence: Optional[str]       # Contexte de première occurrence
    first_occurrence_claims: List[str]    # claim_ids preuves

    # Évolution
    evolution_timeline: List[Dict]        # [{context, status, claims}]

    # Applicabilité actuelle
    current_status: Optional[str]         # Dans "latest"

    # Abstention
    abstention_reason: Optional[str]
    clarification_needed: Optional[str]

class TextValidationResponse(BaseModel):
    status: TemporalQueryStatus

    # Détail validation
    matching_claims: List[str]            # Claims qui supportent
    contradicting_claims: List[str]       # Claims qui contredisent

    # Contexte
    validated_in_context: Optional[str]   # Où c'est vrai
    not_found_in_context: Optional[str]   # Où non documenté

    # Confiance
    confidence: float

    # Explication
    explanation: str
```

### 5.3 Règle Clé: Absence ≠ Suppression

```python
def interpret_absence(
    capability: str,
    found_in_contexts: List[str],
    not_found_in_contexts: List[str],
    explicit_removals: List[Claim]
) -> TemporalQueryStatus:
    """
    Interprète l'absence d'une capability dans un contexte.

    RÈGLE FONDAMENTALE: absence ≠ suppression
    La suppression ne peut être affirmée QUE si explicitement documentée.
    """
    if explicit_removals:
        return TemporalQueryStatus.REMOVED

    if found_in_contexts and not_found_in_contexts:
        # Présent avant, absent maintenant → UNCERTAIN (pas REMOVED)
        return TemporalQueryStatus.UNCERTAIN

    if not found_in_contexts and not found_in_contexts:
        return TemporalQueryStatus.NOT_DOCUMENTED

    return TemporalQueryStatus.CONFIRMED
```

---

## 6. Profils Verticaux: Analyse des Options

### 6.1 Option A — Core 100% Agnostique

**Principe:** Tout découvert du corpus, aucun profil métier.

```python
# Détection ordonnabilité 100% heuristique
class AgnosticAxisDetector:
    NUMERIC_PATTERN = r'^\d+(\.\d+)*$'
    YEAR_PATTERN = r'^(19|20)\d{2}$'
    VERSION_PATTERN = r'^v?\d+(\.\d+){0,2}$'

    def detect_order_type(self, values: List[str]) -> OrderType:
        if all(re.match(self.YEAR_PATTERN, v) for v in values):
            return OrderType.CHRONOLOGICAL
        if all(re.match(self.VERSION_PATTERN, v) for v in values):
            return OrderType.SEMANTIC_VERSION
        if all(re.match(self.NUMERIC_PATTERN, v) for v in values):
            return OrderType.NUMERIC
        # Tentative ordre lexicographique si patterns similaires
        if self._looks_ordinal(values):
            return OrderType.ORDINAL
        return OrderType.UNKNOWN
```

**Avantages:**
- Zéro biais domaine
- Généralisable à tout corpus
- Pas de maintenance profils

**Inconvénients:**
- Plus d'abstention (axes non détectés)
- Faux négatifs sur patterns inhabituels
- Pas d'aide contextuelle

### 6.2 Option B — Core Agnostique + Profils Activables

**Principe:** Core agnostique, profils optionnels pour aider la détection.

```python
# config/vertical_profiles.yaml
profiles:
  it_software:
    name: "IT / Software"
    axis_hints:
      - pattern: "(version|release|patch)"
        likely_order: semantic_version
      - pattern: "(SP|service pack)"
        likely_order: numeric
    qualifier_patterns:
      - "^v?\\d+\\.\\d+(\\.\\d+)?$"  # 1.0.0
      - "^\\d{4}$"                    # 2023

  automotive:
    name: "Automotive"
    axis_hints:
      - pattern: "(model year|MY)"
        likely_order: chronological
      - pattern: "(generation|gen)"
        likely_order: ordinal

  clinical:
    name: "Clinical / Pharma"
    axis_hints:
      - pattern: "(phase|trial)"
        likely_order: ordinal
      - pattern: "(IND|NDA|BLA)"
        likely_order: ordinal
```

```python
class ProfileAwareAxisDetector(AgnosticAxisDetector):
    def __init__(self, profile: Optional[str] = None):
        self.profile = self._load_profile(profile) if profile else None

    def detect_order_type(self, values: List[str], key: str) -> OrderType:
        # 1. Toujours essayer détection agnostique d'abord
        agnostic_result = super().detect_order_type(values)

        if agnostic_result != OrderType.UNKNOWN:
            return agnostic_result

        # 2. Si profil activé, utiliser comme HINT (pas vérité)
        if self.profile:
            hint = self._get_profile_hint(key)
            if hint and self._validate_hint(values, hint):
                return hint

        return OrderType.UNKNOWN
```

**Avantages:**
- Meilleure détection sur domaines connus
- Moins d'abstention
- Suggestions contextuelles

**Inconvénients:**
- Maintenance des profils
- Risque de biais si mal utilisé
- Complexité configuration

### 6.3 Recommandation: Option B avec Garde-Fous

**Design recommandé:**

1. **Core toujours agnostique** — La détection agnostique est TOUJOURS tentée en premier
2. **Profils = hints, jamais vérité** — Un profil ne peut que SUGGÉRER, jamais AFFIRMER
3. **Profils désactivables** — Tout fonctionne sans profil (défaut)
4. **Profils non structurants** — Ils n'affectent pas le schéma de données

```python
# Invariant profil
PROFILE_INVARIANT = """
Un profil NE PEUT PAS:
- Créer un axe sans preuve corpus
- Forcer un ordre non validé par les données
- Être requis pour le fonctionnement
- Être source de vérité

Un profil PEUT:
- Suggérer des patterns à chercher
- Proposer un type d'ordre probable
- Aider à la désambiguïsation
- Enrichir les labels utilisateur
"""
```

### 6.4 Comment Départager par Tests

| Test | Option A (agnostique) | Option B (profils) | Gagnant |
|------|----------------------|-------------------|---------|
| Corpus SAP (test actuel) | Détecte "version" comme NUMERIC | Détecte "version" comme SEMANTIC_VERSION avec meilleur ordre | **B** |
| Corpus médical inconnu | Abstention sur "phase" | Abstention sur "phase" (profil pas chargé) | **Égal** |
| Corpus avec patterns atypiques ("Gen Alpha", "Gen Beta") | Abstention probable | Profil automotive suggère ORDINAL | **B** |
| Corpus sans patterns reconnaissables | Abstention | Abstention (profil n'aide pas) | **Égal** |
| Faux positif risqué | Moins probable | Plus probable si profil mal configuré | **A** |

**Verdict:** Option B avec profils DÉSACTIVÉS par défaut, activables explicitement.

---

## 7. Plan de Tests

### 7.1 Tests Unitaires

```python
# tests/claimfirst/test_axis_detector.py

class TestAxisDetector:
    def test_detect_numeric_order(self):
        values = ["1809", "2023", "2025"]
        detector = ApplicabilityAxisDetector()
        order_type, confidence = detector.infer_orderability("version", values)
        assert order_type == OrderType.NUMERIC
        assert confidence > 0.8

    def test_detect_unordered(self):
        values = ["EU", "US", "APAC"]
        detector = ApplicabilityAxisDetector()
        order_type, confidence = detector.infer_orderability("region", values)
        assert order_type == OrderType.UNORDERED

    def test_abstention_on_ambiguous(self):
        values = ["alpha", "beta", "gamma"]  # Pourrait être ordonné, pas sûr
        detector = ApplicabilityAxisDetector()
        order_type, confidence = detector.infer_orderability("phase", values)
        assert order_type == OrderType.UNKNOWN or confidence < 0.5

# tests/claimfirst/test_context_comparator.py

class TestContextComparator:
    def test_comparable_same_subject_different_version(self):
        doc_a = DocumentContext(doc_id="a", subject_ids=["s4hana"], axis_values={"version": "2023"})
        doc_b = DocumentContext(doc_id="b", subject_ids=["s4hana"], axis_values={"version": "2025"})

        comparator = ContextComparator()
        result = comparator.compute_comparability(doc_a, doc_b, [version_axis])

        assert result.status == ComparabilityStatus.COMPARABLE
        assert result.ordering["version"] == -1  # a < b

    def test_disjoint_different_subjects(self):
        doc_a = DocumentContext(doc_id="a", subject_ids=["s4hana"])
        doc_b = DocumentContext(doc_id="b", subject_ids=["business_one"])

        comparator = ContextComparator()
        result = comparator.compute_comparability(doc_a, doc_b, [])

        assert result.status == ComparabilityStatus.DISJOINT
```

### 7.2 Tests d'Intégration (Corpus SAP)

```python
# tests/claimfirst/test_temporal_queries_sap.py

class TestTemporalQueriesSAP:
    """Tests sur le corpus SAP (3 documents)."""

    @pytest.fixture
    def corpus(self):
        # Charger les 3 documents de test
        return load_test_corpus([
            "018_S4HANA_1809_BUSINESS_SCOPE_MASTER_L23.pdf",
            "025_SAP_S4HANA_2023_Feature_Scope_Description.pdf",
            "023_1212_Business-Scope-2025-SAP-Cloud-ERP-Private.pdf"
        ])

    # Question A: Depuis quand
    async def test_since_when_feature_exists_in_all(self, corpus):
        """Feature présente dans toutes les versions."""
        engine = TemporalQueryEngine(corpus)
        response = await engine.query_since_when("General Ledger accounting")

        assert response.status == TemporalQueryStatus.CONFIRMED
        assert response.first_occurrence == "1809"
        assert len(response.first_occurrence_claims) > 0

    async def test_since_when_feature_new_in_2023(self, corpus):
        """Feature apparue en 2023."""
        engine = TemporalQueryEngine(corpus)
        response = await engine.query_since_when("Joule AI assistant")

        assert response.status == TemporalQueryStatus.CONFIRMED
        assert response.first_occurrence in ["2023", "2025"]

    async def test_since_when_not_documented(self, corpus):
        """Feature inexistante."""
        engine = TemporalQueryEngine(corpus)
        response = await engine.query_since_when("Blockchain integration")

        assert response.status == TemporalQueryStatus.NOT_DOCUMENTED

    # Question B: Encore applicable
    async def test_still_applicable_confirmed(self, corpus):
        """Feature toujours présente."""
        engine = TemporalQueryEngine(corpus)
        response = await engine.query_still_applicable(
            "Material Management",
            target_context="2025"
        )

        assert response.status == TemporalQueryStatus.CONFIRMED

    async def test_still_applicable_uncertain(self, corpus):
        """Feature présente avant, pas documentée dans latest."""
        engine = TemporalQueryEngine(corpus)
        # Supposons une feature documentée en 1809 mais pas en 2025
        response = await engine.query_still_applicable(
            "Some legacy feature",
            target_context="2025"
        )

        # RÈGLE: absence ≠ suppression
        assert response.status in [
            TemporalQueryStatus.UNCERTAIN,
            TemporalQueryStatus.NOT_DOCUMENTED
        ]
        assert response.status != TemporalQueryStatus.REMOVED

    # Question C: Latest par défaut
    async def test_default_latest_context(self, corpus):
        """Sans contexte spécifié, utiliser latest."""
        engine = TemporalQueryEngine(corpus)
        response = await engine.query_still_applicable("Fiori UX")

        # Devrait avoir résolu vers 2025 automatiquement
        assert "2025" in response.validated_in_context or response.abstention_reason

    # Question D: Validation texte
    async def test_validate_text_confirmed(self, corpus):
        """Texte correct validé."""
        validator = TextValidator(corpus)
        response = await validator.validate(
            "S/4HANA supports real-time analytics",
            target_context="2023"
        )

        assert response.status == TemporalQueryStatus.CONFIRMED
        assert len(response.matching_claims) > 0

    async def test_validate_text_contradicted(self, corpus):
        """Texte faux détecté."""
        validator = TextValidator(corpus)
        response = await validator.validate(
            "S/4HANA does not support cloud deployment",
            target_context="2023"
        )

        assert response.status == TemporalQueryStatus.CONTRADICTED
        assert len(response.contradicting_claims) > 0
```

### 7.3 Indicateurs de Qualité

| Indicateur | Définition | Cible V1 |
|------------|------------|----------|
| **Precision** | Claims pertinentes / Claims retournées | > 85% |
| **Recall** | Claims pertinentes trouvées / Claims pertinentes existantes | > 70% |
| **Abstention Rate** | Requêtes avec abstention / Total requêtes | 10-30% (acceptable) |
| **False Positive Rate** | Faux CONFIRMED / Total CONFIRMED | < 5% |
| **False Removal Rate** | Faux REMOVED / Total REMOVED | 0% (critique) |

### 7.4 Scénarios de Test Manuels

```markdown
## Scénario 1: Traçabilité Feature

**Input:** "Depuis quand S/4HANA supporte la comptabilité multi-devises?"

**Expected:**
- Status: CONFIRMED
- First occurrence: 1809 (ou plus ancien)
- Claims: [claim_ids avec preuves]
- Timeline: [{1809: present}, {2023: present}, {2025: present}]

## Scénario 2: Feature Disparue (fausse piste)

**Input:** "La fonctionnalité XYZ est-elle encore disponible en 2025?"

**Expected SI non documentée en 2025 mais présente en 2023:**
- Status: UNCERTAIN (PAS REMOVED)
- Explanation: "Documented in v2023, not found in v2025. May persist without explicit mention."

**Expected SI suppression explicite documentée:**
- Status: REMOVED
- Explanation: "Explicitly deprecated in v2025 release notes"
- Evidence: [claim_ids]

## Scénario 3: Validation Texte Ambigu

**Input:** "S/4HANA permet la gestion des stocks en temps réel"
**Context:** Non spécifié (devrait utiliser latest)

**Expected:**
- Resolve latest → 2025
- Search claims about "inventory management" + "real-time"
- Status: CONFIRMED si trouvé, NOT_DOCUMENTED sinon
```

---

## 8. Séquence d'Implémentation Recommandée

### Phase 1: Fondations (2-3 jours)
1. Créer modèles `ApplicabilityAxis`, `ContextComparability`
2. Créer `ApplicabilityAxisDetector` (version agnostique)
3. Tests unitaires détection

### Phase 2: Comparabilité (2 jours)
4. Créer `ContextComparator`
5. Intégrer dans `ClaimPersister` (nouvelles relations Neo4j)
6. Tests comparabilité

### Phase 3: Query Engine (3-4 jours)
7. Créer `LatestPolicyResolver`
8. Créer `TemporalQueryEngine` (questions A/B/C)
9. Créer `TextValidator` (question D)
10. Tests intégration sur corpus SAP

### Phase 4: API & Polish (2 jours)
11. Endpoints FastAPI
12. Stratégie d'abstention complète
13. Documentation
14. Tests E2E

**Total estimé: 9-11 jours de développement**

---

## 9. Questions Ouvertes

1. **Granularité des axes:** Un document peut-il avoir plusieurs valeurs pour un même axe? (ex: "version: 2023-2025")

2. **Héritage de scope:** Si un claim est dans un cluster inter-docs, le scope du cluster est-il l'union ou l'intersection?

3. **Conflits de policy:** Si deux policies s'appliquent (tenant + subject), laquelle prévaut?

4. **Cache de comparabilité:** Recalculer à chaque requête ou pré-calculer à l'ingestion?

---

## 10. Annexe: Mapping Capabilities → Composants

| Capability | Composant Principal | Composants Support |
|------------|--------------------|--------------------|
| **(A) Depuis quand** | `TemporalQueryEngine.query_since_when()` | AxisDetector, Comparator |
| **(B) Encore applicable** | `TemporalQueryEngine.query_still_applicable()` | LatestPolicyResolver |
| **(C) Latest implicite** | `LatestPolicyResolver.resolve_latest()` | Policy config |
| **(D) Validation texte** | `TextValidator.validate()` | TemporalQueryEngine |

---

**Document rédigé par:** Claude (analyse codebase + design)
**À valider par:** Équipe produit
**Prochaine étape:** Validation du design avant implémentation
