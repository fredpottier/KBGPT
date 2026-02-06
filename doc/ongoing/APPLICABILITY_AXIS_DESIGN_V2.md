# Design Document V2: Applicability Axis — Version Révisée

**Date:** 2026-02-04
**Révision:** V2 (intégration feedback ChatGPT)
**Statut:** DRAFT - Patches critiques intégrés

---

## Changelog V1 → V2

| Risque Identifié | Patch Intégré |
|------------------|---------------|
| R1: capability_description = bombe | **IntentResolver** + disambiguation obligatoire |
| R2: ClaimCluster ≠ même fait | **ClaimKey-lite** découvert, cluster = auxiliaire |
| R3: COMPARABLE_WITH = O(n²) | Calcul à la volée, pas de persistence paires |
| R4: AxisDetector pas agnostique | Séparation **orderability** vs **ordering** |
| R5: "latest" ≠ max simple | **LatestSelector** avec critères de gouvernance |
| R6: UNCERTAIN pas actionnable | **uncertainty_signals[]** typés |
| Q7: Granularité axe | Modèle scalar/range/set |
| R8: Path minimal | **V1 Minimale** définie explicitement |

---

## 1. PATCH CRITIQUE #1 : IntentResolver (R1)

### 1.1 Problème

L'API `query_since_when(capability_description: str)` suppose que l'utilisateur fournit une description exploitable. En réalité :
- Questions vagues : "depuis quand feature X"
- Synonymes : "accounting" vs "general ledger" vs "GL"
- Paraphrases : "real-time analytics" vs "live reporting"

Sans IntentResolver, on retombe dans un RAG post-traité.

### 1.2 Solution : TargetClaimIntent + Disambiguation

```python
# src/knowbase/claimfirst/query/intent_resolver.py

class ClaimIntentType(str, Enum):
    """Type d'intention détectée."""
    CAPABILITY = "capability"       # "does X support Y"
    TEMPORAL = "temporal"           # "since when", "still applicable"
    VALIDATION = "validation"       # "is this statement true"
    COMPARISON = "comparison"       # "difference between A and B"

class TargetClaimIntent(BaseModel):
    """
    Intention extraite de la question utilisateur.

    INVARIANT: Produit des CANDIDATS, jamais une décision.
    """
    intent_type: ClaimIntentType

    # Extraction conservative
    raw_query: str                           # Question originale
    extracted_terms: List[str]               # Termes clés extraits

    # Candidats (PAS décision)
    candidate_clusters: List[str]            # cluster_ids potentiellement pertinents
    candidate_entities: List[str]            # entity_ids mentionnées
    candidate_facets: List[str]              # facet_ids applicables

    # Contexte demandé (si explicite)
    explicit_context: Optional[Dict[str, str]]  # {"version": "2023"}
    context_is_explicit: bool                   # False = utiliser latest

    # Ambiguïté
    is_ambiguous: bool
    disambiguation_needed: bool
    disambiguation_options: List[Dict]       # Options à présenter si ambigu

    # Confiance
    confidence: float                        # [0-1]
    abstention_reason: Optional[str]

class IntentResolver:
    """
    Résout l'intention utilisateur en candidats exploitables.

    RÈGLE: Si ambigu → disambiguation, PAS réponse hasardeuse.
    """

    def __init__(self, claim_index: ClaimIndex):
        self.claim_index = claim_index
        self.entity_matcher = FuzzyEntityMatcher()
        self.cluster_ranker = ClusterRanker()

    async def resolve(
        self,
        user_query: str,
        subject_context: Optional[str] = None
    ) -> TargetClaimIntent:
        """
        Extrait l'intention de la question utilisateur.

        Stratégie:
        1. Classification du type d'intention
        2. Extraction termes clés (conservative)
        3. Retrieval candidats (top-k clusters + entities)
        4. Évaluation ambiguïté
        5. Si ambigu: préparer disambiguation, PAS répondre
        """
        # 1. Classification intention
        intent_type = await self._classify_intent(user_query)

        # 2. Extraction termes (sans hallucination)
        terms = self._extract_key_terms(user_query)

        # 3. Retrieval candidats
        candidate_clusters = await self._find_candidate_clusters(
            terms,
            subject_context,
            top_k=5  # Toujours plusieurs candidats
        )

        candidate_entities = await self._find_candidate_entities(terms)

        # 4. Évaluation ambiguïté
        is_ambiguous = self._evaluate_ambiguity(
            candidate_clusters,
            candidate_entities,
            terms
        )

        # 5. Construction intent
        return TargetClaimIntent(
            intent_type=intent_type,
            raw_query=user_query,
            extracted_terms=terms,
            candidate_clusters=[c.cluster_id for c in candidate_clusters],
            candidate_entities=[e.entity_id for e in candidate_entities],
            candidate_facets=self._infer_facets(terms),
            explicit_context=self._extract_explicit_context(user_query),
            context_is_explicit=self._has_explicit_context(user_query),
            is_ambiguous=is_ambiguous,
            disambiguation_needed=is_ambiguous,
            disambiguation_options=self._build_disambiguation_options(
                candidate_clusters
            ) if is_ambiguous else [],
            confidence=self._compute_confidence(candidate_clusters, is_ambiguous),
            abstention_reason=None
        )

    def _evaluate_ambiguity(
        self,
        clusters: List[ClaimCluster],
        entities: List[Entity],
        terms: List[str]
    ) -> bool:
        """
        Détermine si l'intention est ambiguë.

        Ambiguë si:
        - Top-2 clusters ont scores proches (delta < 0.1)
        - Termes matchent plusieurs entités distinctes
        - Pas de cluster avec score > 0.7
        """
        if not clusters:
            return True

        if len(clusters) >= 2:
            score_delta = clusters[0].match_score - clusters[1].match_score
            if score_delta < 0.1:
                return True

        if clusters[0].match_score < 0.7:
            return True

        return False

    def _build_disambiguation_options(
        self,
        clusters: List[ClaimCluster]
    ) -> List[Dict]:
        """
        Construit les options de disambiguation à présenter.
        """
        return [
            {
                "cluster_id": c.cluster_id,
                "label": c.canonical_label,
                "sample_claim": c.representative_claim_text[:100],
                "doc_count": c.doc_count,
                "score": c.match_score
            }
            for c in clusters[:4]  # Max 4 options
        ]
```

### 1.3 Workflow avec Disambiguation

```
USER: "Depuis quand la feature accounting est disponible?"

1. IntentResolver.resolve()
   → intent_type: TEMPORAL
   → extracted_terms: ["accounting", "feature"]
   → candidate_clusters: [
       {id: "c1", label: "General Ledger Accounting", score: 0.82},
       {id: "c2", label: "Cost Accounting", score: 0.78},
       {id: "c3", label: "Management Accounting", score: 0.75}
     ]
   → is_ambiguous: True (delta 0.04 < 0.1)
   → disambiguation_needed: True

2. TemporalQueryEngine détecte disambiguation_needed

3. RESPONSE (pas de réponse hasardeuse):
   {
     "status": "disambiguation_required",
     "message": "Plusieurs types d'accounting trouvés. Lequel?",
     "options": [
       {"id": "c1", "label": "General Ledger Accounting (3 docs)"},
       {"id": "c2", "label": "Cost Accounting (2 docs)"},
       {"id": "c3", "label": "Management Accounting (2 docs)"}
     ]
   }

4. USER sélectionne "c1"

5. TemporalQueryEngine.query_since_when(cluster_id="c1")
   → Réponse précise sur General Ledger
```

---

## 2. PATCH CRITIQUE #2 : ClaimKey-lite (R2)

### 2.1 Problème

`ClaimCluster` agrège par similarité textuelle, pas par "même fait comparable".

Exemple :
- "Compatibility pack usage rights extended until 2030"
- "Usage rights for X valid until 2025"

→ Cluster ensemble (similarité forte) mais **ce ne sont pas le même fait**.

### 2.2 Solution : ClaimKey Découvert (pas hardcodé)

```python
# src/knowbase/claimfirst/models/claim_key.py

class ClaimKeyType(str, Enum):
    """Types de clés découvertes."""
    PROPERTY = "property"           # X.property = value
    CAPABILITY = "capability"       # X supports Y
    CONSTRAINT = "constraint"       # X limited to Y
    TEMPORAL = "temporal"           # X valid until Y
    RELATION = "relation"           # X relates to Y

class ClaimKey(BaseModel):
    """
    Clé d'alignement inter-documents pour un fait comparable.

    INVARIANT: Découverte par patterns + LLM, VALIDÉE par cooccurrence.
    Pas hardcodée, pas ontologie.

    Exemple: "s4hana.compatibility_pack.usage_rights.expiration"
    """
    key_id: str                              # Unique
    tenant_id: str

    # Structure hiérarchique découverte
    subject_part: str                        # "s4hana"
    property_path: List[str]                 # ["compatibility_pack", "usage_rights", "expiration"]

    # Type
    key_type: ClaimKeyType

    # Validation corpus
    claim_ids: List[str]                     # Claims alignées sur cette clé
    doc_ids: List[str]                       # Docs où cette clé apparaît
    occurrence_count: int

    # Confiance
    discovery_method: str                    # "pattern" | "llm" | "manual"
    validation_status: str                   # "candidate" | "validated" | "rejected"
    confidence: float

    # Valeurs observées
    observed_values: Dict[str, List[str]]    # {doc_id: [values]}

    @property
    def canonical_path(self) -> str:
        """Chemin canonique pour comparaison."""
        return f"{self.subject_part}.{'.'.join(self.property_path)}"


class ClaimKeyDiscoverer:
    """
    Découvre des ClaimKeys depuis le corpus.

    Stratégie:
    1. Patterns syntaxiques (X.property = value)
    2. LLM extraction structurée (prompt conservatif)
    3. Validation par cooccurrence cross-doc (≥2 docs)
    """

    VALIDATION_THRESHOLD = 2  # Min docs pour valider une clé

    async def discover_keys(
        self,
        claims: List[Claim],
        clusters: List[ClaimCluster]
    ) -> List[ClaimKey]:
        """
        Découvre ClaimKeys depuis claims et clusters.
        """
        candidate_keys = []

        # 1. Extraction par patterns
        pattern_keys = self._extract_by_patterns(claims)
        candidate_keys.extend(pattern_keys)

        # 2. Extraction LLM sur clusters (plus efficient)
        for cluster in clusters:
            if cluster.doc_count >= 2:  # Multi-doc = potentiel alignement
                llm_keys = await self._extract_by_llm(cluster)
                candidate_keys.extend(llm_keys)

        # 3. Validation par cooccurrence
        validated_keys = self._validate_by_cooccurrence(candidate_keys)

        return validated_keys

    def _extract_by_patterns(self, claims: List[Claim]) -> List[ClaimKey]:
        """
        Extraction déterministe par patterns syntaxiques.

        Patterns:
        - "X is/are [value]"
        - "X supports/enables Y"
        - "X valid/available until [date]"
        - "X limited to [constraint]"
        """
        patterns = [
            (r"(.+?)\s+(?:is|are)\s+(.+)", ClaimKeyType.PROPERTY),
            (r"(.+?)\s+supports?\s+(.+)", ClaimKeyType.CAPABILITY),
            (r"(.+?)\s+(?:valid|available)\s+until\s+(.+)", ClaimKeyType.TEMPORAL),
            (r"(.+?)\s+limited\s+to\s+(.+)", ClaimKeyType.CONSTRAINT),
        ]
        # ... implementation
        return []

    def _validate_by_cooccurrence(
        self,
        candidates: List[ClaimKey]
    ) -> List[ClaimKey]:
        """
        Valide les clés par présence dans ≥2 documents.

        INVARIANT: Une clé n'est validée que si elle apparaît
        dans plusieurs documents avec des valeurs potentiellement différentes.
        """
        validated = []

        for key in candidates:
            if len(set(key.doc_ids)) >= self.VALIDATION_THRESHOLD:
                key.validation_status = "validated"
                validated.append(key)

        return validated
```

### 2.3 Relation ClaimCluster ↔ ClaimKey

```
ClaimCluster = auxiliaire (similarité textuelle)
     ↓
ClaimKey = alignement de fait (même propriété comparable)
     ↓
Timeline se fait par ClaimKey, PAS par Cluster

Exemple:
- Cluster "usage rights" contient 5 claims similaires
- Mais seulement 3 parlent de "expiration_date" (même ClaimKey)
- Timeline "expiration_date" = sur ces 3 claims uniquement
```

---

## 3. PATCH CRITIQUE #3 : Pas de COMPARABLE_WITH Persisté (R3)

### 3.1 Problème

`COMPARABLE_WITH` entre tous les DocumentContext = O(n²).
- 3 docs : 3 relations (ok)
- 100 docs : 4950 relations (problème)
- 1000 docs : 499500 relations (explosion)

### 3.2 Solution : Calcul à la Volée

```python
# src/knowbase/claimfirst/resolution/comparability_resolver.py

class ComparabilityResolver:
    """
    Calcule la comparabilité à la volée, sans persistence O(n²).

    Persiste seulement:
    - ApplicabilityAxis (les axes)
    - DocumentContext.axis_values (valeurs par doc)
    - LatestChain (ordre linéaire si applicable)

    NE persiste PAS:
    - COMPARABLE_WITH (toutes les paires)
    """

    def __init__(self, cache_ttl: int = 300):
        self.cache = LRUCache(maxsize=1000, ttl=cache_ttl)

    async def are_comparable(
        self,
        doc_a: DocumentContext,
        doc_b: DocumentContext,
        axes: List[ApplicabilityAxis]
    ) -> ComparabilityResult:
        """
        Détermine si deux docs sont comparables.
        Calcul à la volée avec cache LRU.
        """
        cache_key = f"{doc_a.doc_id}:{doc_b.doc_id}"

        if cache_key in self.cache:
            return self.cache[cache_key]

        result = self._compute_comparability(doc_a, doc_b, axes)
        self.cache[cache_key] = result

        return result

    def _compute_comparability(
        self,
        doc_a: DocumentContext,
        doc_b: DocumentContext,
        axes: List[ApplicabilityAxis]
    ) -> ComparabilityResult:
        """
        Calcul effectif de comparabilité.

        Comparable si:
        1. Même subject (ou subjects avec overlap)
        2. Au moins un axe ordonnable en commun
        3. Valeurs sur cet axe permettent comparaison
        """
        # 1. Check subject overlap
        subject_overlap = set(doc_a.subject_ids) & set(doc_b.subject_ids)
        if not subject_overlap:
            return ComparabilityResult(
                status=ComparabilityStatus.DISJOINT,
                reason="No common subject"
            )

        # 2. Find orderable axes in common
        common_axes = []
        for axis in axes:
            if (axis.is_orderable and
                axis.axis_key in doc_a.axis_values and
                axis.axis_key in doc_b.axis_values):
                common_axes.append(axis)

        if not common_axes:
            return ComparabilityResult(
                status=ComparabilityStatus.PARTIAL,
                reason="No orderable axis in common"
            )

        # 3. Compute ordering on primary axis
        primary_axis = common_axes[0]  # ou selon policy
        ordering = primary_axis.compare(
            doc_a.axis_values[primary_axis.axis_key],
            doc_b.axis_values[primary_axis.axis_key]
        )

        return ComparabilityResult(
            status=ComparabilityStatus.COMPARABLE,
            comparable_axes=[a.axis_key for a in common_axes],
            ordering={primary_axis.axis_key: ordering}
        )

    async def find_comparable_docs(
        self,
        target_doc: DocumentContext,
        all_docs: List[DocumentContext],
        axes: List[ApplicabilityAxis]
    ) -> List[Tuple[DocumentContext, ComparabilityResult]]:
        """
        Trouve tous les docs comparables au doc cible.
        Filtrage efficace sans O(n²) persistence.
        """
        # Pré-filtre par subject (index Neo4j)
        same_subject_docs = [
            d for d in all_docs
            if set(d.subject_ids) & set(target_doc.subject_ids)
        ]

        # Comparabilité sur subset filtré
        results = []
        for doc in same_subject_docs:
            if doc.doc_id != target_doc.doc_id:
                comp = await self.are_comparable(target_doc, doc, axes)
                if comp.status == ComparabilityStatus.COMPARABLE:
                    results.append((doc, comp))

        return results
```

### 3.3 Ce qui EST Persisté

```cypher
// Persisté : Axes (O(k) où k = nombre d'axes, typiquement < 10)
(:ApplicabilityAxis {axis_key, is_orderable, value_order})

// Persisté : Valeurs par doc (O(n) où n = nombre de docs)
(DocumentContext)-[:HAS_AXIS_VALUE {value}]->(ApplicabilityAxis)

// Persisté : Chaîne ordonnée si linéaire (O(n))
(DocumentContext)-[:SUPERSEDES {axis}]->(DocumentContext)
// Seulement si ordre total clair (A < B < C)

// NON persisté : Toutes les paires (évite O(n²))
// COMPARABLE_WITH calculé à la volée avec cache
```

---

## 4. PATCH CRITIQUE #4 : Séparation Orderability vs Ordering (R4)

### 4.1 Problème

L'AxisDetector "agnostique" utilise des regex qui ne couvrent pas :
- "Phase II", "Gen Alpha", "Mk7", "Stage 3", "Rev B"
- "EU MDR 2017/745" (référence réglementaire)

Risque : inventer un ordre faux.

### 4.2 Solution : Deux Questions Distinctes

```python
# src/knowbase/claimfirst/models/applicability_axis.py

class OrderingConfidence(str, Enum):
    """Niveau de confiance dans l'ordre."""
    CERTAIN = "certain"           # Ordre prouvé (numériques, dates)
    INFERRED = "inferred"         # Ordre inféré avec confiance
    UNKNOWN = "unknown"           # Ordonnable mais ordre inconnu
    NOT_APPLICABLE = "not_applicable"  # Pas ordonnable

class ApplicabilityAxis(BaseModel):
    """Version révisée avec séparation orderability/ordering."""

    axis_id: str
    axis_key: str

    # QUESTION 1: Est-ce ordonnable? (peut-on comparer?)
    is_orderable: bool
    orderability_confidence: float        # Confiance que c'est ordonnable
    orderability_evidence: List[str]      # Preuves ("numeric pattern", "date format")

    # QUESTION 2: Connaît-on l'ordre? (séparé!)
    ordering_confidence: OrderingConfidence
    value_order: Optional[List[str]]      # Ordre SI connu, None sinon
    ordering_evidence: List[str]          # Preuves de l'ordre

    # Valeurs observées
    observed_values: List[str]

    def can_compare(self, value_a: str, value_b: str) -> bool:
        """Peut-on comparer ces deux valeurs?"""
        return (
            self.is_orderable and
            value_a in self.observed_values and
            value_b in self.observed_values
        )

    def compare(self, value_a: str, value_b: str) -> Optional[int]:
        """
        Compare deux valeurs.

        Returns:
            -1/0/1 si ordre connu
            None si ordonnable mais ordre inconnu

        INVARIANT: Ne jamais inventer un ordre.
        """
        if not self.can_compare(value_a, value_b):
            return None

        if self.ordering_confidence == OrderingConfidence.UNKNOWN:
            # Ordonnable mais ordre inconnu → None
            return None

        if self.value_order is None:
            return None

        try:
            idx_a = self.value_order.index(value_a)
            idx_b = self.value_order.index(value_b)
            return (idx_a > idx_b) - (idx_a < idx_b)
        except ValueError:
            return None


class AxisOrderInferrer:
    """
    Infère l'ordre des valeurs sur un axe.

    INVARIANT: Ordre inféré seulement si preuve suffisante.
    Sinon: orderability=True, ordering=UNKNOWN.
    """

    def infer_order(
        self,
        axis_key: str,
        values: List[str]
    ) -> Tuple[bool, OrderingConfidence, Optional[List[str]]]:
        """
        Retourne (is_orderable, ordering_confidence, value_order).
        """
        # Cas 1: Numériques purs
        if self._all_numeric(values):
            sorted_values = sorted(values, key=self._numeric_key)
            return (True, OrderingConfidence.CERTAIN, sorted_values)

        # Cas 2: Années
        if self._all_years(values):
            sorted_values = sorted(values)
            return (True, OrderingConfidence.CERTAIN, sorted_values)

        # Cas 3: Versions sémantiques
        if self._all_semver(values):
            sorted_values = sorted(values, key=self._semver_key)
            return (True, OrderingConfidence.CERTAIN, sorted_values)

        # Cas 4: Patterns ordinaux reconnus (Phase I/II/III)
        ordinal_order = self._try_ordinal_order(values)
        if ordinal_order:
            return (True, OrderingConfidence.INFERRED, ordinal_order)

        # Cas 5: Potentiellement ordonnable mais ordre inconnu
        if self._looks_orderable(values):
            return (True, OrderingConfidence.UNKNOWN, None)

        # Cas 6: Pas ordonnable (régions, éditions, etc.)
        return (False, OrderingConfidence.NOT_APPLICABLE, None)

    def _looks_orderable(self, values: List[str]) -> bool:
        """
        Heuristique: est-ce que ça RESSEMBLE à quelque chose d'ordonnable?

        True si patterns similaires suggèrent une séquence.
        """
        # Patterns qui suggèrent ordonnabilité
        ordinal_hints = [
            r'(?:phase|stage|step|gen|generation|rev|version|v)\s*\w+',
            r'(?:mk|mark)\s*\d+',
            r'\d+(?:st|nd|rd|th)',
        ]

        matches = sum(
            1 for v in values
            if any(re.search(p, v.lower()) for p in ordinal_hints)
        )

        return matches >= len(values) * 0.5
```

### 4.3 Impact sur les Réponses

```
Cas: values = ["Gen Alpha", "Gen Beta", "Gen Gamma"]

AVANT (V1):
  is_orderable: False (pas reconnu)
  → Abstention totale

APRÈS (V2):
  is_orderable: True
  ordering_confidence: UNKNOWN
  value_order: None

  → Peut répondre: "Feature présente dans Gen Alpha et Gen Beta"
  → Ne peut PAS répondre: "Feature apparue en Gen Alpha" (ordre inconnu)
```

---

## 5. PATCH CRITIQUE #5 : LatestSelector avec Gouvernance (R5)

### 5.1 Problème

"latest = max(version)" est naïf :
- Document "draft" publié après "approved"
- Marketing publié après technical guide
- Region-specific (EU) vs global
- Addendum vs master document

### 5.2 Solution : LatestSelector Multi-Critères

```python
# src/knowbase/claimfirst/query/latest_selector.py

class DocumentAuthority(str, Enum):
    """Niveau d'autorité d'un document."""
    MASTER = "master"               # Document de référence
    OFFICIAL = "official"           # Document officiel
    SUPPLEMENTARY = "supplementary" # Complément
    DRAFT = "draft"                 # Brouillon
    MARKETING = "marketing"         # Marketing (moins autoritatif)
    UNKNOWN = "unknown"

class LatestSelectionCriteria(BaseModel):
    """
    Critères de sélection du "latest" context.

    INVARIANT: Ces critères sont DÉCOUVERTS ou CONFIGURÉS,
    jamais hardcodés pour un domaine spécifique.
    """
    # Axe principal de comparaison
    primary_axis: str                        # "version", "year", etc.
    fallback_axes: List[str] = []

    # Critères de gouvernance (découverts ou configurés)
    authority_ranking: List[DocumentAuthority] = [
        DocumentAuthority.MASTER,
        DocumentAuthority.OFFICIAL,
        DocumentAuthority.SUPPLEMENTARY,
        DocumentAuthority.DRAFT,
        DocumentAuthority.MARKETING,
    ]

    # Filtres d'éligibilité
    required_status: Optional[str] = None    # "approved", "published"
    excluded_types: List[str] = []           # ["draft", "internal"]
    scope_must_match: bool = True            # Exclure scopes disjoints

    # Comportement ambiguïté
    on_tie: str = "ask"                      # "ask" | "newest" | "most_authoritative"
    on_disjoint_scopes: str = "explain"      # "explain" | "abstain"


class LatestSelector:
    """
    Sélectionne le contexte "latest" selon critères de gouvernance.

    Pas juste max(axis), mais sélection intelligente.
    """

    def __init__(self, criteria: LatestSelectionCriteria):
        self.criteria = criteria

    async def select_latest(
        self,
        candidates: List[DocumentContext],
        axes: List[ApplicabilityAxis],
        subject_filter: Optional[str] = None
    ) -> LatestSelectionResult:
        """
        Sélectionne le contexte "latest" parmi les candidats.
        """
        # 1. Filtrer par subject si spécifié
        if subject_filter:
            candidates = [
                c for c in candidates
                if subject_filter in c.subject_ids
            ]

        if not candidates:
            return LatestSelectionResult(
                status="no_candidates",
                selected=None,
                reason="No documents match the subject filter"
            )

        # 2. Filtrer par éligibilité (status, type)
        eligible = self._filter_eligible(candidates)

        if not eligible:
            return LatestSelectionResult(
                status="none_eligible",
                selected=None,
                reason="No documents meet eligibility criteria",
                excluded_reasons={
                    c.doc_id: self._exclusion_reason(c)
                    for c in candidates
                }
            )

        # 3. Grouper par scope (éviter comparaison de scopes disjoints)
        scope_groups = self._group_by_compatible_scope(eligible)

        if len(scope_groups) > 1 and self.criteria.scope_must_match:
            return LatestSelectionResult(
                status="disjoint_scopes",
                selected=None,
                reason="Multiple disjoint scopes found",
                scope_groups=[
                    {"scope": g["scope_desc"], "docs": [d.doc_id for d in g["docs"]]}
                    for g in scope_groups
                ],
                clarification_needed="Which scope are you interested in?"
            )

        # 4. Sélectionner le plus récent sur l'axe principal
        primary_axis = self._get_axis(axes, self.criteria.primary_axis)

        if not primary_axis or not primary_axis.is_orderable:
            # Fallback sur autorité si pas d'axe ordonnable
            return self._select_by_authority(eligible)

        # 5. Trier par axe + autorité
        ranked = self._rank_candidates(eligible, primary_axis)

        # 6. Vérifier les égalités
        if len(ranked) > 1 and self._is_tie(ranked[0], ranked[1], primary_axis):
            return self._handle_tie(ranked)

        return LatestSelectionResult(
            status="selected",
            selected=ranked[0],
            reason=f"Latest on {self.criteria.primary_axis}",
            ranking=[
                {"doc_id": c.doc_id, "score": s}
                for c, s in ranked[:5]
            ]
        )

    def _filter_eligible(
        self,
        candidates: List[DocumentContext]
    ) -> List[DocumentContext]:
        """Filtre par critères d'éligibilité."""
        eligible = []

        for c in candidates:
            # Status requis
            if self.criteria.required_status:
                if c.document_status != self.criteria.required_status:
                    continue

            # Types exclus
            if c.document_type in self.criteria.excluded_types:
                continue

            # Autorité minimale
            if c.authority == DocumentAuthority.DRAFT:
                if DocumentAuthority.DRAFT not in self.criteria.authority_ranking[:3]:
                    continue

            eligible.append(c)

        return eligible

    def _rank_candidates(
        self,
        candidates: List[DocumentContext],
        primary_axis: ApplicabilityAxis
    ) -> List[Tuple[DocumentContext, float]]:
        """
        Classe les candidats par (axis_value, authority).
        """
        def score(doc: DocumentContext) -> Tuple[int, int]:
            # Score axe (plus récent = plus haut)
            axis_value = doc.axis_values.get(primary_axis.axis_key)
            if axis_value and primary_axis.value_order:
                try:
                    axis_score = primary_axis.value_order.index(axis_value)
                except ValueError:
                    axis_score = -1
            else:
                axis_score = -1

            # Score autorité
            try:
                auth_score = self.criteria.authority_ranking.index(doc.authority)
            except ValueError:
                auth_score = len(self.criteria.authority_ranking)

            return (-axis_score, auth_score)  # Négatif car on veut max en premier

        ranked = sorted(candidates, key=score)
        return [(c, score(c)) for c in ranked]
```

### 5.3 Configuration Agnostique

```yaml
# config/latest_policies.yaml (découvert ou configuré)
default_policy:
  primary_axis: "auto"  # Détecte automatiquement l'axe principal
  authority_ranking:
    - master
    - official
    - supplementary
    - draft
  on_tie: "ask"
  scope_must_match: true

# Profils optionnels (activables)
profiles:
  regulatory:
    primary_axis: "effective_date"
    required_status: "approved"
    excluded_types: ["draft", "guidance"]
```

---

## 6. PATCH CRITIQUE #6 : Uncertainty Signals (R6)

### 6.1 Problème

`UNCERTAIN` = "présent avant, pas en latest" n'est pas actionnable.

L'utilisateur a besoin de savoir **pourquoi** c'est incertain.

### 6.2 Solution : Uncertainty Signals Typés

```python
# src/knowbase/claimfirst/query/uncertainty_signals.py

class UncertaintySignalType(str, Enum):
    """Types de signaux d'incertitude."""

    # Signaux d'absence
    OLDER_ONLY = "older_only"                    # Mentionné seulement dans versions anciennes
    SCOPE_MISMATCH = "scope_mismatch"            # Scope différent (cloud vs on-prem)
    COVERAGE_GAP = "coverage_gap"                # Zone non couverte par latest doc

    # Signaux de remplacement potentiel
    REPLACEMENT_MENTIONED = "replacement_mentioned"  # "replaced by X"
    MIGRATION_PATH = "migration_path"                # "migrate to X"
    DEPRECATED_SIGNAL = "deprecated_signal"          # "deprecated", "legacy"

    # Signaux de continuité
    RELATED_CLAIMS_PRESENT = "related_claims_present"  # Claims connexes toujours là
    PARENT_FEATURE_PRESENT = "parent_feature_present"  # Feature parente toujours là
    NO_CONTRADICTION = "no_contradiction"              # Pas de claim contradictoire

class UncertaintySignal(BaseModel):
    """Signal individuel d'incertitude."""
    signal_type: UncertaintySignalType
    description: str
    evidence_claim_ids: List[str] = []
    confidence: float                    # Confiance dans ce signal

    @property
    def suggests_persistence(self) -> bool:
        """Ce signal suggère-t-il que la feature persiste?"""
        return self.signal_type in [
            UncertaintySignalType.RELATED_CLAIMS_PRESENT,
            UncertaintySignalType.PARENT_FEATURE_PRESENT,
            UncertaintySignalType.NO_CONTRADICTION,
        ]

    @property
    def suggests_obsolescence(self) -> bool:
        """Ce signal suggère-t-il que la feature est obsolète?"""
        return self.signal_type in [
            UncertaintySignalType.REPLACEMENT_MENTIONED,
            UncertaintySignalType.MIGRATION_PATH,
            UncertaintySignalType.DEPRECATED_SIGNAL,
        ]

class UncertaintyAnalysis(BaseModel):
    """Analyse complète de l'incertitude."""

    # Classification globale
    status: str                          # "uncertain_persistence" | "likely_obsolete" | "likely_still_valid"

    # Signaux collectés
    signals: List[UncertaintySignal]

    # Résumé
    persistence_signals: int             # Nombre de signaux suggérant persistence
    obsolescence_signals: int            # Nombre de signaux suggérant obsolescence

    # Verdict nuancé
    persistence_likelihood: float        # [0-1] probabilité que ça persiste

    # Explication
    explanation: str

    @classmethod
    def analyze(
        cls,
        claim_key: ClaimKey,
        found_in_contexts: List[str],
        not_found_in_contexts: List[str],
        all_claims: List[Claim]
    ) -> "UncertaintyAnalysis":
        """
        Analyse l'incertitude pour une ClaimKey.
        """
        signals = []

        # Signal: Présent seulement dans anciens contextes
        if found_in_contexts and not_found_in_contexts:
            signals.append(UncertaintySignal(
                signal_type=UncertaintySignalType.OLDER_ONLY,
                description=f"Documented in {found_in_contexts}, not in {not_found_in_contexts}",
                confidence=0.9
            ))

        # Chercher signaux de remplacement
        replacement_claims = cls._find_replacement_signals(claim_key, all_claims)
        for rc in replacement_claims:
            signals.append(UncertaintySignal(
                signal_type=UncertaintySignalType.REPLACEMENT_MENTIONED,
                description=f"Replacement mentioned: {rc.text[:100]}",
                evidence_claim_ids=[rc.claim_id],
                confidence=0.8
            ))

        # Chercher claims connexes encore présentes
        related_present = cls._find_related_claims_present(claim_key, all_claims, not_found_in_contexts)
        if related_present:
            signals.append(UncertaintySignal(
                signal_type=UncertaintySignalType.RELATED_CLAIMS_PRESENT,
                description=f"{len(related_present)} related claims still documented",
                evidence_claim_ids=[c.claim_id for c in related_present[:3]],
                confidence=0.6
            ))

        # Calculer likelihood
        persistence_signals = sum(1 for s in signals if s.suggests_persistence)
        obsolescence_signals = sum(1 for s in signals if s.suggests_obsolescence)

        if obsolescence_signals > persistence_signals:
            status = "likely_obsolete"
            likelihood = 0.3
        elif persistence_signals > obsolescence_signals:
            status = "likely_still_valid"
            likelihood = 0.7
        else:
            status = "uncertain_persistence"
            likelihood = 0.5

        return cls(
            status=status,
            signals=signals,
            persistence_signals=persistence_signals,
            obsolescence_signals=obsolescence_signals,
            persistence_likelihood=likelihood,
            explanation=cls._generate_explanation(signals, status)
        )
```

### 6.3 Impact sur les Réponses

```json
// AVANT (V1)
{
  "status": "UNCERTAIN",
  "explanation": "May persist without explicit mention"
}

// APRÈS (V2)
{
  "status": "UNCERTAIN",
  "uncertainty_analysis": {
    "status": "likely_obsolete",
    "persistence_likelihood": 0.3,
    "signals": [
      {
        "type": "older_only",
        "description": "Documented in v2023, not in v2025"
      },
      {
        "type": "replacement_mentioned",
        "description": "Replacement mentioned: 'Feature X has been replaced by Feature Y'",
        "evidence": ["claim_123"]
      }
    ],
    "explanation": "Feature was documented in v2023 but not in v2025. A replacement was mentioned, suggesting this feature may be obsolete."
  }
}
```

---

## 7. PATCH #7 : Granularité Axe (scalar/range/set)

```python
# src/knowbase/claimfirst/models/axis_value.py

class AxisValueType(str, Enum):
    SCALAR = "scalar"     # Valeur unique: "2023"
    RANGE = "range"       # Plage: "2023-2025"
    SET = "set"           # Ensemble: ["EU", "US"]

class AxisValue(BaseModel):
    """Valeur d'un axe avec support multi-types."""

    value_type: AxisValueType

    # Selon le type
    scalar_value: Optional[str] = None
    range_min: Optional[str] = None
    range_max: Optional[str] = None
    set_values: Optional[List[str]] = None

    @classmethod
    def from_scalar(cls, value: str) -> "AxisValue":
        return cls(value_type=AxisValueType.SCALAR, scalar_value=value)

    @classmethod
    def from_range(cls, min_val: str, max_val: str) -> "AxisValue":
        return cls(value_type=AxisValueType.RANGE, range_min=min_val, range_max=max_val)

    @classmethod
    def from_set(cls, values: List[str]) -> "AxisValue":
        return cls(value_type=AxisValueType.SET, set_values=values)

    def overlaps_with(self, other: "AxisValue", axis: ApplicabilityAxis) -> Optional[bool]:
        """
        Vérifie si deux valeurs se chevauchent.

        Returns:
            True si overlap, False si disjoint, None si indéterminable
        """
        if self.value_type == AxisValueType.SCALAR and other.value_type == AxisValueType.SCALAR:
            return self.scalar_value == other.scalar_value

        if self.value_type == AxisValueType.RANGE and other.value_type == AxisValueType.SCALAR:
            return self._scalar_in_range(other.scalar_value, axis)

        if self.value_type == AxisValueType.RANGE and other.value_type == AxisValueType.RANGE:
            return self._ranges_overlap(other, axis)

        if self.value_type == AxisValueType.SET or other.value_type == AxisValueType.SET:
            return self._sets_overlap(other)

        return None

    def _scalar_in_range(self, scalar: str, axis: ApplicabilityAxis) -> Optional[bool]:
        """Vérifie si un scalar est dans le range."""
        if not axis.value_order:
            return None

        try:
            scalar_idx = axis.value_order.index(scalar)
            min_idx = axis.value_order.index(self.range_min)
            max_idx = axis.value_order.index(self.range_max)
            return min_idx <= scalar_idx <= max_idx
        except ValueError:
            return None
```

---

## 8. V1 MINIMALE (Path le Plus Court)

### 8.1 Scope V1 Strict

| Inclus en V1 | Exclu (V2+) |
|--------------|-------------|
| AxisDetector (orderability + values) | ClaimKey-lite (V2) |
| LatestSelector (avec gouvernance) | Clustering amélioré (V2) |
| IntentResolver (avec disambiguation) | Conflict detection riche (V2) |
| TemporalQueryEngine (A/B/C) | COMPARABLE_WITH persisté (jamais) |
| TextValidator (D) avec uncertainty_signals | Profils verticaux (V2) |

### 8.2 Fichiers V1

```
CRÉER (8 fichiers):
src/knowbase/claimfirst/
├── models/
│   ├── applicability_axis.py       # Axis + OrderingConfidence
│   └── axis_value.py               # Scalar/Range/Set
├── extractors/
│   └── axis_detector.py            # Detection orderability
├── query/
│   ├── intent_resolver.py          # IntentResolver + disambiguation
│   ├── latest_selector.py          # LatestSelector + gouvernance
│   ├── temporal_query_engine.py    # Questions A/B/C
│   ├── text_validator.py           # Question D
│   └── uncertainty_signals.py      # Signals typés

MODIFIER (3 fichiers):
├── models/document_context.py      # + axis_values: Dict[str, AxisValue]
├── orchestrator.py                 # + phase AxisDetection
└── persistence/claim_persister.py  # Persister axes (pas COMPARABLE_WITH)
```

### 8.3 Séquence V1

```
Jour 1-2: Modèles + AxisDetector
  - applicability_axis.py
  - axis_value.py
  - axis_detector.py
  - Tests unitaires

Jour 3: IntentResolver
  - intent_resolver.py
  - Tests disambiguation

Jour 4-5: LatestSelector + TemporalQueryEngine
  - latest_selector.py (avec gouvernance)
  - temporal_query_engine.py (A/B/C)
  - Tests intégration

Jour 6-7: TextValidator + UncertaintySignals
  - uncertainty_signals.py
  - text_validator.py (D)
  - Tests E2E sur corpus SAP

Jour 8: Intégration + Polish
  - Modifier orchestrator
  - Modifier claim_persister
  - API endpoints
  - Documentation
```

### 8.4 Critères de Succès V1

| Test | Critère | Seuil |
|------|---------|-------|
| Axis detection (corpus SAP) | Détecte "version" comme ordonnable | ✅ |
| Ordering (1809, 2023, 2025) | Ordre correct | ✅ |
| Intent disambiguation | Propose options si ambigu | ✅ |
| Latest selection | Sélectionne 2025 (ou explique pourquoi pas) | ✅ |
| Since when "GL Accounting" | Retourne première occurrence + preuves | ✅ |
| Still applicable | Répond avec uncertainty_signals si incertain | ✅ |
| Text validation | Confirme/réfute avec claims + signals | ✅ |
| False REMOVED rate | 0% (jamais dire REMOVED sans preuve) | ✅ |

---

## 9. Résumé des Invariants V2

| ID | Invariant | Violation = Bug |
|----|-----------|-----------------|
| **INV-11** | IntentResolver produit CANDIDATS, pas décision | Réponse sans disambiguation quand ambigu |
| **INV-12** | ClaimKey validé par cooccurrence (≥2 docs) | ClaimKey créé sur 1 seul doc |
| **INV-13** | COMPARABLE_WITH jamais persisté | Relation COMPARABLE_WITH en Neo4j |
| **INV-14** | Séparation orderability / ordering | compare() retourne valeur si ordre inconnu |
| **INV-15** | Latest = critères gouvernance, pas juste max | Latest = max(axis) sans filtre |
| **INV-16** | UNCERTAIN accompagné de signals | Status UNCERTAIN sans uncertainty_analysis |
| **INV-17** | REMOVED seulement si explicitement documenté | REMOVED inféré de l'absence |

---

## 10. Questions Résolues

| Question | Décision |
|----------|----------|
| Granularité axe | Scalar/Range/Set supportés |
| ClaimCluster vs fait | ClaimKey-lite en V2, cluster = auxiliaire |
| COMPARABLE_WITH | Jamais persisté, calcul à la volée |
| Ordre inconnu | Peut dire "présent dans X et Y", pas "depuis X" |
| Latest ambigu | Demande clarification (on_tie: "ask") |
| Absence vs suppression | REMOVED seulement si explicite (INV-17) |

---

**Document révisé suite au feedback ChatGPT**
**Prêt pour implémentation V1**
