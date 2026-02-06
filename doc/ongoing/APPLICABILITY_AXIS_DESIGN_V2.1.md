# Design Document V2.1: Applicability Axis — Verrouillages Finaux

**Date:** 2026-02-04
**Révision:** V2.1.1 (review final ChatGPT)
**Statut:** ✅ GO FOR IMPLEMENTATION

---

## Changelog V2.1 → V2.1.1 (Review Final)

| Risque Final | Ajustement |
|--------------|------------|
| R1: Système "auto-suffisant" | **INV-23**: Toute réponse cite explicitement ses claims sources |
| R2: ClaimKey trop puissant | **INV-12 renforcé**: ≥2 docs ET ≥2 valeurs distinctes |
| R3: LatestSelector politique | Séparation LatestSelector (mécanique) / LatestPolicy (déclarative) |
| R4: IntentResolver mini-agent | **INV-24**: Toujours ≥2 candidats (sauf exact match) |

---

## Changelog V2 → V2.1

| Zone Identifiée | Verrouillage |
|-----------------|--------------|
| Z1: IntentResolver cluster-first | Disambiguation UI enrichie + no-answer-when-ambiguous |
| Z2: ClaimKey candidate/validated | Règles d'usage explicites pour nouveautés |
| Z3: LatestSelector authority | Unknown = ask, pas score inventé |
| Z4: AxisValue persistence | Properties structurées, pas string |
| Z5: observed_values memory | Stats + sample, pas toutes les valeurs |
| Z6: persistence_likelihood | Renommé `heuristic_confidence_hint` |
| Z7: primary_axis choice | Vient de policy explicite |

---

## 1. VERROUILLAGE Z1 : Disambiguation UI Enrichie

### 1.1 Règle

**INV-18:** La disambiguation DOIT afficher contexte riche, pas juste label.

```python
class DisambiguationOption(BaseModel):
    """
    Option de disambiguation enrichie.

    INVARIANT INV-18: Jamais label-only.
    """
    cluster_id: str
    canonical_label: str

    # ENRICHISSEMENTS OBLIGATOIRES
    sample_claim_text: str              # Extrait de claim représentative (max 150 chars)
    sample_claim_verbatim: str          # Verbatim exact (preuve)
    facet_names: List[str]              # Facettes associées
    entity_names: List[str]             # Entités mentionnées
    doc_count: int                      # Nombre de documents
    scope_preview: Optional[str]        # Ex: "versions 2023-2025, EU region"

    # Score (pour tri, PAS pour décision)
    match_score: float

    def to_user_display(self) -> Dict:
        """Format pour affichage utilisateur."""
        return {
            "label": self.canonical_label,
            "description": self.sample_claim_text,
            "coverage": f"{self.doc_count} documents",
            "scope": self.scope_preview or "All scopes",
            "topics": self.facet_names[:3],
            "entities": self.entity_names[:3]
        }
```

### 1.2 Règle de Forçage Disambiguation

```python
class IntentResolver:
    # Seuils de forçage disambiguation
    DELTA_THRESHOLD = 0.15        # Delta min entre top-2 pour répondre sans demander
    MIN_CONFIDENCE = 0.75         # Confiance min du top-1 pour répondre
    MAX_SOFT_CLUSTERS = 3         # Si >3 clusters au-dessus de 0.6, forcer disambiguation

    def _must_disambiguate(
        self,
        candidates: List[RankedCluster]
    ) -> Tuple[bool, str]:
        """
        Détermine si disambiguation est obligatoire.

        Returns:
            (must_disambiguate, reason)
        """
        if not candidates:
            return (True, "no_candidates")

        if len(candidates) == 1:
            if candidates[0].score < self.MIN_CONFIDENCE:
                return (True, "low_confidence_single")
            return (False, "")

        # Check delta
        delta = candidates[0].score - candidates[1].score
        if delta < self.DELTA_THRESHOLD:
            return (True, f"delta_too_low:{delta:.2f}")

        # Check soft clusters
        soft_count = sum(1 for c in candidates if c.score > 0.6)
        if soft_count > self.MAX_SOFT_CLUSTERS:
            return (True, f"too_many_soft_candidates:{soft_count}")

        # Check top-1 confidence
        if candidates[0].score < self.MIN_CONFIDENCE:
            return (True, "top_confidence_insufficient")

        return (False, "")
```

### 1.3 Comportement Strict

```python
async def resolve(self, user_query: str, ...) -> TargetClaimIntent:
    # ...
    must_disambiguate, reason = self._must_disambiguate(candidates)

    if must_disambiguate:
        # JAMAIS répondre, TOUJOURS demander
        return TargetClaimIntent(
            # ...
            is_ambiguous=True,
            disambiguation_needed=True,
            disambiguation_options=[
                self._build_rich_option(c) for c in candidates[:4]
            ],
            forced_disambiguation_reason=reason,
            # PAS de réponse partielle
            selected_cluster=None
        )
```

---

## 2. VERROUILLAGE Z2 : ClaimKey Candidate vs Validated

### 2.1 Règle d'Usage

**INV-19:** ClaimKey `candidate` (1 doc) JAMAIS utilisée pour "since when".

```python
class ClaimKeyUsageRule(str, Enum):
    """Règles d'usage selon validation_status."""

    # VALIDATED (≥2 docs) : usage complet
    VALIDATED_TIMELINE = "validated_timeline"      # Peut répondre "since when"
    VALIDATED_COMPARISON = "validated_comparison"  # Peut comparer entre docs

    # CANDIDATE (1 doc) : usage restreint
    CANDIDATE_PRESENCE = "candidate_presence"      # Peut dire "documented in X"
    CANDIDATE_NO_TIMELINE = "candidate_no_timeline"  # NE PEUT PAS dire "since when"


class ClaimKeyQueryRules:
    """
    Règles d'utilisation des ClaimKeys selon leur statut.
    """

    @staticmethod
    def can_answer_since_when(key: ClaimKey) -> bool:
        """
        Peut-on répondre "depuis quand" avec cette ClaimKey?

        RÈGLE: UNIQUEMENT si validated (≥2 docs avec timeline).
        Sinon, on ne peut pas établir de timeline fiable.
        """
        if key.validation_status != "validated":
            return False
        if len(set(key.doc_ids)) < 2:
            return False
        return True

    @staticmethod
    def can_answer_presence(key: ClaimKey, context: str) -> bool:
        """
        Peut-on répondre "documenté dans X" avec cette ClaimKey?

        RÈGLE: OK même si candidate, MAIS avec caveat.
        """
        return context in key.doc_ids

    @staticmethod
    def get_answer_mode(key: ClaimKey, question_type: str) -> str:
        """
        Détermine le mode de réponse autorisé.
        """
        if question_type == "since_when":
            if not ClaimKeyQueryRules.can_answer_since_when(key):
                return "cannot_answer_timeline"
            return "full_timeline"

        if question_type == "still_applicable":
            if key.validation_status == "candidate":
                return "presence_only_with_caveat"
            return "full_comparison"

        return "unknown"
```

### 2.2 Réponse pour Nouveautés (1 seul doc)

```python
# Cas: Feature apparue pour la première fois dans latest (2025)
# ClaimKey existe mais validation_status = "candidate"

response = {
    "status": "documented",
    "context": "2025",
    "caveat": "This capability is documented only in the latest context (2025). "
              "No prior documentation exists to establish when it first appeared.",
    "can_answer_since_when": False,
    "claims": [...]
}

# PAS: "Since 2025" (car on ne sait pas si c'était là avant sans doc)
```

---

## 3. VERROUILLAGE Z3 : LatestSelector Authority Agnostique

### 3.1 Règle

**INV-20:** Si authority/status inconnus → `ask` ou `explain`, JAMAIS scorer à l'aveugle.

```python
class LatestSelector:

    def _rank_candidates(
        self,
        candidates: List[DocumentContext],
        primary_axis: ApplicabilityAxis
    ) -> LatestRankingResult:
        """
        Classe les candidats.

        RÈGLE INV-20: Si authority unknown pour >50% des candidats,
        ne pas utiliser authority dans le ranking.
        """
        # Check authority coverage
        unknown_count = sum(
            1 for c in candidates
            if c.authority == DocumentAuthority.UNKNOWN
        )
        authority_coverage = 1 - (unknown_count / len(candidates))

        if authority_coverage < 0.5:
            # Trop d'unknowns → ne pas utiliser authority
            return self._rank_by_axis_only(candidates, primary_axis)

        # Authority utilisable
        return self._rank_by_axis_and_authority(candidates, primary_axis)

    def _rank_by_axis_only(
        self,
        candidates: List[DocumentContext],
        primary_axis: ApplicabilityAxis
    ) -> LatestRankingResult:
        """
        Ranking sans authority (axis seul).

        Si égalité sur axis → demander clarification.
        """
        # Trier par axis value
        sorted_candidates = sorted(
            candidates,
            key=lambda c: self._axis_sort_key(c, primary_axis),
            reverse=True  # Plus récent en premier
        )

        # Check égalité
        if len(sorted_candidates) >= 2:
            top_value = sorted_candidates[0].axis_values.get(primary_axis.axis_key)
            second_value = sorted_candidates[1].axis_values.get(primary_axis.axis_key)

            if top_value == second_value:
                # Égalité → cannot decide
                return LatestRankingResult(
                    status="tie_needs_clarification",
                    tied_candidates=sorted_candidates[:2],
                    reason="Multiple documents with same axis value, authority unknown"
                )

        return LatestRankingResult(
            status="ranked",
            ranked=sorted_candidates,
            ranking_method="axis_only"
        )
```

### 3.2 Source d'Authority

```python
class DocumentContextEnricher:
    """
    Enrichit DocumentContext avec authority/status.

    RÈGLE: Authority vient de:
    1. Métadonnées explicites (si disponibles)
    2. UNKNOWN sinon (jamais inventé)
    3. Profil V2 (optionnel, futur)
    """

    def enrich_authority(self, doc: DocumentContext) -> DocumentContext:
        # 1. Check métadonnées explicites
        if doc.raw_metadata:
            explicit_auth = doc.raw_metadata.get("document_authority")
            explicit_status = doc.raw_metadata.get("document_status")

            if explicit_auth:
                doc.authority = DocumentAuthority(explicit_auth)
            if explicit_status:
                doc.document_status = explicit_status

        # 2. Si pas de métadonnées → UNKNOWN (pas d'invention)
        if doc.authority is None:
            doc.authority = DocumentAuthority.UNKNOWN

        if doc.document_status is None:
            doc.document_status = "unknown"

        return doc

    # PAS de heuristiques basées sur naming conventions SAP
    # PAS de: if "master" in title.lower(): authority = MASTER
```

---

## 4. VERROUILLAGE Z4 : AxisValue Persistence Structurée

### 4.1 Schéma Neo4j Révisé

```cypher
// AVANT (V2 - problématique):
// (DocumentContext)-[:HAS_AXIS_VALUE {value: "2023"}]->(ApplicabilityAxis)
// → Perte de structure range/set

// APRÈS (V2.1 - structuré):
(DocumentContext)-[:HAS_AXIS_VALUE {
    value_type: "scalar" | "range" | "set",
    scalar_value: "2023",           // si scalar
    range_min: null,                // si range
    range_max: null,                // si range
    set_values: null                // si set (JSON array string)
}]->(ApplicabilityAxis)

// Exemple range:
(doc_multi_version)-[:HAS_AXIS_VALUE {
    value_type: "range",
    scalar_value: null,
    range_min: "2023",
    range_max: "2025",
    set_values: null
}]->(axis_version)

// Exemple set:
(doc_multi_region)-[:HAS_AXIS_VALUE {
    value_type: "set",
    scalar_value: null,
    range_min: null,
    range_max: null,
    set_values: '["EU", "US", "APAC"]'
}]->(axis_region)
```

### 4.2 Désérialisation

```python
class AxisValuePersistence:
    """Persistence structurée des AxisValue."""

    @staticmethod
    def to_neo4j_properties(axis_value: AxisValue) -> Dict:
        """Convertit AxisValue en properties Neo4j."""
        props = {
            "value_type": axis_value.value_type.value,
            "scalar_value": None,
            "range_min": None,
            "range_max": None,
            "set_values": None
        }

        if axis_value.value_type == AxisValueType.SCALAR:
            props["scalar_value"] = axis_value.scalar_value
        elif axis_value.value_type == AxisValueType.RANGE:
            props["range_min"] = axis_value.range_min
            props["range_max"] = axis_value.range_max
        elif axis_value.value_type == AxisValueType.SET:
            props["set_values"] = json.dumps(axis_value.set_values)

        return props

    @staticmethod
    def from_neo4j_properties(props: Dict) -> AxisValue:
        """Reconstruit AxisValue depuis properties Neo4j."""
        value_type = AxisValueType(props["value_type"])

        if value_type == AxisValueType.SCALAR:
            return AxisValue.from_scalar(props["scalar_value"])
        elif value_type == AxisValueType.RANGE:
            return AxisValue.from_range(props["range_min"], props["range_max"])
        elif value_type == AxisValueType.SET:
            return AxisValue.from_set(json.loads(props["set_values"]))

        raise ValueError(f"Unknown value_type: {value_type}")
```

---

## 5. VERROUILLAGE Z5 : observed_values Memory

### 5.1 Règle

**INV-21:** `ApplicabilityAxis.observed_values` contient stats + sample, pas toutes les valeurs.

```python
class ApplicabilityAxis(BaseModel):
    """Version révisée avec observed_values optimisé."""

    axis_id: str
    axis_key: str

    # Orderability
    is_orderable: bool
    ordering_confidence: OrderingConfidence
    value_order: Optional[List[str]]      # Ordre SI connu (subset représentatif)

    # STATS au lieu de toutes les valeurs
    observed_values_sample: List[str]     # Max 20 valeurs représentatives
    observed_values_count: int            # Nombre total distinct
    observed_values_patterns: List[str]   # Patterns détectés ["numeric", "year"]

    # Pour comparaison, on ne stocke que les valeurs ordonnées
    # Les valeurs complètes sont dans DocumentContext.axis_values


class AxisStatisticsComputer:
    """Calcule les stats sans stocker toutes les valeurs."""

    MAX_SAMPLE_SIZE = 20

    def compute_stats(
        self,
        all_values: List[str]
    ) -> Tuple[List[str], int, List[str]]:
        """
        Calcule sample + count + patterns.

        Returns:
            (sample, count, patterns)
        """
        unique_values = list(set(all_values))
        count = len(unique_values)

        # Sample représentatif
        if count <= self.MAX_SAMPLE_SIZE:
            sample = unique_values
        else:
            # Prendre premier, dernier, et échantillon milieu
            sample = self._representative_sample(unique_values)

        # Patterns
        patterns = self._detect_patterns(unique_values)

        return (sample, count, patterns)

    def _representative_sample(self, values: List[str]) -> List[str]:
        """Échantillon représentatif (premiers, derniers, répartis)."""
        n = len(values)
        indices = [0, n-1]  # Premier et dernier

        # Ajouter des points intermédiaires
        step = n // (self.MAX_SAMPLE_SIZE - 2)
        for i in range(step, n - step, step):
            indices.append(i)
            if len(indices) >= self.MAX_SAMPLE_SIZE:
                break

        return [values[i] for i in sorted(set(indices))]
```

---

## 6. VERROUILLAGE Z6 : Renommage persistence_likelihood

### 6.1 Changement

```python
# AVANT (V2)
class UncertaintyAnalysis:
    persistence_likelihood: float  # [0-1] "probabilité"

# APRÈS (V2.1)
class UncertaintyAnalysis:
    heuristic_confidence_hint: float  # [0-1] score heuristique (PAS probabilité)

    # Documentation explicite
    """
    heuristic_confidence_hint:
        Score heuristique basé sur les signaux collectés.
        0.0-0.3 = signaux suggèrent obsolescence
        0.4-0.6 = incertain, signaux mixtes
        0.7-1.0 = signaux suggèrent persistence

        ⚠️ CE N'EST PAS UNE PROBABILITÉ.
        C'est un indicateur pour priorisation UI uniquement.
        Les uncertainty_signals[] sont la source de vérité auditable.
    """
```

### 6.2 Affichage Utilisateur

```python
def format_uncertainty_for_user(analysis: UncertaintyAnalysis) -> Dict:
    """
    Format pour affichage utilisateur.

    RÈGLE: Ne jamais présenter heuristic_confidence_hint comme probabilité.
    """
    # Verdict textuel basé sur signaux (pas sur le score)
    if analysis.obsolescence_signals > analysis.persistence_signals:
        verdict = "Evidence suggests this may be obsolete"
    elif analysis.persistence_signals > analysis.obsolescence_signals:
        verdict = "Evidence suggests this likely persists"
    else:
        verdict = "Insufficient evidence to determine status"

    return {
        "status": analysis.status,
        "verdict": verdict,
        # PAS de "probability: 70%"
        "evidence": [
            {
                "type": s.signal_type.value,
                "description": s.description,
                "supporting_claims": s.evidence_claim_ids
            }
            for s in analysis.signals
        ],
        "recommendation": "Review the evidence above to make an informed decision"
    }
```

---

## 7. VERROUILLAGE Z7 : primary_axis depuis Policy

### 7.1 Règle

**INV-22:** `primary_axis` vient de LatestSelectionCriteria (policy), jamais de `common_axes[0]`.

```python
class ComparabilityResolver:

    def _select_primary_axis(
        self,
        common_axes: List[ApplicabilityAxis],
        policy: LatestSelectionCriteria
    ) -> Optional[ApplicabilityAxis]:
        """
        Sélectionne l'axe primaire selon policy.

        RÈGLE INV-22: L'axe vient de policy, pas de l'ordre de la liste.
        """
        # 1. Axe explicite dans policy
        if policy.primary_axis and policy.primary_axis != "auto":
            for axis in common_axes:
                if axis.axis_key == policy.primary_axis:
                    return axis
            # Policy spécifie un axe non présent → problème config
            return None

        # 2. Mode "auto" : règles déterministes
        return self._auto_select_primary_axis(common_axes)

    def _auto_select_primary_axis(
        self,
        axes: List[ApplicabilityAxis]
    ) -> Optional[ApplicabilityAxis]:
        """
        Sélection automatique déterministe.

        Critères (dans l'ordre):
        1. Ordering confidence (CERTAIN > INFERRED > UNKNOWN)
        2. Coverage (présent dans plus de docs)
        3. Alphabétique (fallback déterministe)
        """
        if not axes:
            return None

        def sort_key(axis: ApplicabilityAxis) -> Tuple:
            # Ordering confidence score
            confidence_order = {
                OrderingConfidence.CERTAIN: 0,
                OrderingConfidence.INFERRED: 1,
                OrderingConfidence.UNKNOWN: 2,
                OrderingConfidence.NOT_APPLICABLE: 3
            }
            conf_score = confidence_order.get(axis.ordering_confidence, 4)

            # Coverage (négatif car on veut max)
            coverage_score = -axis.doc_count

            # Alphabétique (fallback)
            alpha_score = axis.axis_key

            return (conf_score, coverage_score, alpha_score)

        sorted_axes = sorted(axes, key=sort_key)
        return sorted_axes[0]
```

---

## 8. SECTIONS DÉTAILLÉES POUR REVIEW FINAL

### 8.1 TemporalQueryEngine (Questions A/B/C)

```python
# src/knowbase/claimfirst/query/temporal_query_engine.py

class TemporalQueryEngine:
    """
    Moteur de requêtes temporelles.

    Gère les questions:
    - A: "Depuis quand X existe?"
    - B: "X est-il encore applicable dans le contexte Y?"
    - C: Context implicite = latest
    """

    def __init__(
        self,
        intent_resolver: IntentResolver,
        latest_selector: LatestSelector,
        comparability_resolver: ComparabilityResolver,
        claim_index: ClaimIndex
    ):
        self.intent_resolver = intent_resolver
        self.latest_selector = latest_selector
        self.comparability_resolver = comparability_resolver
        self.claim_index = claim_index

    # ==================== QUESTION A: SINCE WHEN ====================

    async def query_since_when(
        self,
        user_query: str,
        subject_filter: Optional[str] = None
    ) -> SinceWhenResponse:
        """
        Question A: "Depuis quand cette capacité existe?"

        Flow:
        1. Résoudre intent (avec disambiguation si nécessaire)
        2. Identifier ClaimKey(s) pertinentes
        3. Vérifier si timeline possible (INV-19)
        4. Construire timeline ordonnée
        5. Retourner première occurrence + évolution
        """
        # 1. Résoudre intent
        intent = await self.intent_resolver.resolve(user_query, subject_filter)

        if intent.disambiguation_needed:
            return SinceWhenResponse(
                status=TemporalQueryStatus.DISAMBIGUATION_REQUIRED,
                disambiguation_options=intent.disambiguation_options,
                message="Please clarify which capability you're asking about"
            )

        # 2. Identifier ClaimKeys
        claim_keys = await self._find_relevant_claim_keys(intent)

        if not claim_keys:
            return SinceWhenResponse(
                status=TemporalQueryStatus.NOT_DOCUMENTED,
                message="No documented claims found matching your query"
            )

        # 3. Vérifier si timeline possible (INV-19)
        primary_key = claim_keys[0]

        if not ClaimKeyQueryRules.can_answer_since_when(primary_key):
            # ClaimKey candidate (1 doc) → pas de timeline
            return SinceWhenResponse(
                status=TemporalQueryStatus.TIMELINE_NOT_AVAILABLE,
                message="This capability is documented, but timeline cannot be established "
                        "(appears in only one context)",
                documented_in_contexts=primary_key.doc_ids,
                claims=self._get_claims_for_key(primary_key)
            )

        # 4. Construire timeline
        timeline = await self._build_timeline(primary_key)

        if timeline.ordering_unknown:
            # Axe ordonnable mais ordre inconnu → liste sans ordre
            return SinceWhenResponse(
                status=TemporalQueryStatus.CONTEXTS_LISTED,
                message="This capability is documented in multiple contexts, "
                        "but their order cannot be determined",
                contexts_unordered=timeline.contexts,
                claims=timeline.all_claims
            )

        # 5. Retourner timeline ordonnée
        return SinceWhenResponse(
            status=TemporalQueryStatus.TIMELINE_AVAILABLE,
            first_occurrence=timeline.first_context,
            first_occurrence_claims=timeline.first_claims,
            evolution_timeline=timeline.ordered_entries,
            current_status=timeline.latest_status
        )

    async def _build_timeline(
        self,
        claim_key: ClaimKey
    ) -> TimelineResult:
        """
        Construit la timeline pour une ClaimKey.
        """
        # Récupérer tous les docs avec cette key
        doc_contexts = await self._get_doc_contexts(claim_key.doc_ids)

        # Trouver l'axe principal
        axes = await self._get_applicable_axes(doc_contexts)
        primary_axis = self.comparability_resolver._auto_select_primary_axis(axes)

        if not primary_axis:
            return TimelineResult(ordering_unknown=True, contexts=claim_key.doc_ids)

        # Vérifier si ordre connu
        if primary_axis.ordering_confidence == OrderingConfidence.UNKNOWN:
            return TimelineResult(
                ordering_unknown=True,
                contexts=[
                    {
                        "doc_id": d.doc_id,
                        "axis_value": d.axis_values.get(primary_axis.axis_key),
                        "claims": claim_key.observed_values.get(d.doc_id, [])
                    }
                    for d in doc_contexts
                ]
            )

        # Ordre connu → timeline ordonnée
        ordered_docs = self._order_docs_by_axis(doc_contexts, primary_axis)

        return TimelineResult(
            ordering_unknown=False,
            first_context=ordered_docs[0].doc_id,
            first_claims=claim_key.observed_values.get(ordered_docs[0].doc_id, []),
            ordered_entries=[
                {
                    "context": d.doc_id,
                    "axis_value": d.axis_values.get(primary_axis.axis_key),
                    "status": "documented",
                    "claims": claim_key.observed_values.get(d.doc_id, [])
                }
                for d in ordered_docs
            ],
            latest_status="documented" if ordered_docs else "unknown"
        )

    # ==================== QUESTION B: STILL APPLICABLE ====================

    async def query_still_applicable(
        self,
        user_query: str,
        target_context: Optional[str] = None
    ) -> StillApplicableResponse:
        """
        Question B: "Cette capacité est-elle encore applicable?"

        Flow:
        1. Résoudre intent
        2. Déterminer contexte cible (explicit ou latest)
        3. Chercher claims dans contexte cible
        4. Si pas trouvé → chercher dans contextes précédents
        5. Analyser incertitude si applicable
        """
        # 1. Résoudre intent
        intent = await self.intent_resolver.resolve(user_query)

        if intent.disambiguation_needed:
            return StillApplicableResponse(
                status=TemporalQueryStatus.DISAMBIGUATION_REQUIRED,
                disambiguation_options=intent.disambiguation_options
            )

        # 2. Déterminer contexte cible
        if target_context:
            # Contexte explicite
            target_doc = await self._get_doc_context(target_context)
            if not target_doc:
                return StillApplicableResponse(
                    status=TemporalQueryStatus.CONTEXT_NOT_FOUND,
                    message=f"Context '{target_context}' not found"
                )
        else:
            # Contexte implicite = latest (Question C intégrée)
            latest_result = await self._resolve_latest_context(intent)

            if latest_result.status != "selected":
                return StillApplicableResponse(
                    status=TemporalQueryStatus.LATEST_AMBIGUOUS,
                    message=latest_result.reason,
                    latest_candidates=latest_result.candidates
                )

            target_doc = latest_result.selected

        # 3. Chercher claims dans contexte cible
        claims_in_target = await self._find_claims_in_context(
            intent.candidate_clusters,
            target_doc.doc_id
        )

        if claims_in_target:
            return StillApplicableResponse(
                status=TemporalQueryStatus.CONFIRMED,
                target_context=target_doc.doc_id,
                claims=claims_in_target,
                message="Capability is documented in the target context"
            )

        # 4. Pas trouvé dans target → chercher dans contextes précédents
        previous_contexts = await self._find_previous_contexts(target_doc)
        claims_in_previous = {}

        for prev_doc in previous_contexts:
            prev_claims = await self._find_claims_in_context(
                intent.candidate_clusters,
                prev_doc.doc_id
            )
            if prev_claims:
                claims_in_previous[prev_doc.doc_id] = prev_claims

        if not claims_in_previous:
            return StillApplicableResponse(
                status=TemporalQueryStatus.NOT_DOCUMENTED,
                target_context=target_doc.doc_id,
                message="Capability not documented in any available context"
            )

        # 5. Trouvé avant mais pas dans target → analyser incertitude
        all_claims = [c for claims in claims_in_previous.values() for c in claims]

        uncertainty = UncertaintyAnalysis.analyze(
            claim_key=None,  # Simplified for V1
            found_in_contexts=list(claims_in_previous.keys()),
            not_found_in_contexts=[target_doc.doc_id],
            all_claims=all_claims
        )

        return StillApplicableResponse(
            status=TemporalQueryStatus.UNCERTAIN,
            target_context=target_doc.doc_id,
            found_in_previous=claims_in_previous,
            uncertainty_analysis=uncertainty,
            message="Capability documented in previous contexts but not in target"
        )

    # ==================== HELPERS ====================

    async def _resolve_latest_context(
        self,
        intent: TargetClaimIntent
    ) -> LatestSelectionResult:
        """
        Résout le contexte "latest" pour cet intent.
        """
        # Récupérer tous les docs concernés
        subject_ids = await self._extract_subject_ids(intent)

        all_docs = await self.claim_index.get_docs_for_subjects(subject_ids)
        axes = await self._get_applicable_axes(all_docs)

        # Sélectionner latest
        return await self.latest_selector.select_latest(
            candidates=all_docs,
            axes=axes,
            subject_filter=subject_ids[0] if subject_ids else None
        )
```

### 8.2 TextValidator (Question D)

```python
# src/knowbase/claimfirst/query/text_validator.py

class TextValidator:
    """
    Validateur de texte utilisateur contre le corpus.

    Question D: "Cette affirmation est-elle correcte?"

    Réponses possibles:
    - CONFIRMED: Documenté dans contexte cible
    - INCORRECT: Contredit par le corpus
    - NOT_DOCUMENTED: Pas trouvé
    - UNCERTAIN: Présent avant mais pas en latest (avec signals)
    """

    def __init__(
        self,
        temporal_engine: TemporalQueryEngine,
        claim_index: ClaimIndex,
        contradiction_detector: ContradictionDetector
    ):
        self.temporal_engine = temporal_engine
        self.claim_index = claim_index
        self.contradiction_detector = contradiction_detector

    async def validate(
        self,
        user_statement: str,
        target_context: Optional[str] = None
    ) -> TextValidationResponse:
        """
        Valide une affirmation utilisateur.

        Flow:
        1. Extraire l'assertion de la phrase utilisateur
        2. Chercher claims supportantes dans contexte cible
        3. Chercher claims contradictoires
        4. Si pas trouvé → chercher dans contextes précédents
        5. Construire réponse avec niveau de confiance
        """
        # 1. Extraire assertion
        extracted = await self._extract_assertion(user_statement)

        if extracted.is_ambiguous:
            return TextValidationResponse(
                status=ValidationStatus.CLARIFICATION_NEEDED,
                message="Could not clearly identify the assertion to validate",
                extracted_assertion=extracted.best_guess,
                clarification_suggestions=extracted.alternatives
            )

        # 2. Déterminer contexte cible
        target_doc = await self._resolve_target_context(target_context)

        if not target_doc and target_context:
            return TextValidationResponse(
                status=ValidationStatus.CONTEXT_NOT_FOUND,
                message=f"Context '{target_context}' not found"
            )

        # Si pas de contexte spécifié, utiliser latest
        if not target_doc:
            latest_result = await self.temporal_engine._resolve_latest_context(
                TargetClaimIntent(
                    intent_type=ClaimIntentType.VALIDATION,
                    raw_query=user_statement,
                    extracted_terms=extracted.key_terms,
                    candidate_clusters=[],
                    candidate_entities=[],
                    candidate_facets=[],
                    explicit_context=None,
                    context_is_explicit=False,
                    is_ambiguous=False,
                    disambiguation_needed=False,
                    disambiguation_options=[],
                    confidence=0.8,
                    abstention_reason=None
                )
            )

            if latest_result.status != "selected":
                return TextValidationResponse(
                    status=ValidationStatus.LATEST_AMBIGUOUS,
                    message="Multiple possible contexts, please specify",
                    context_options=[c.doc_id for c in latest_result.candidates[:4]]
                )

            target_doc = latest_result.selected

        # 3. Chercher claims supportantes
        supporting_claims = await self._find_supporting_claims(
            extracted.assertion,
            target_doc.doc_id
        )

        # 4. Chercher claims contradictoires
        contradicting_claims = await self._find_contradicting_claims(
            extracted.assertion,
            target_doc.doc_id
        )

        # 5. Évaluer résultat
        if contradicting_claims:
            # Contradiction trouvée → INCORRECT
            return TextValidationResponse(
                status=ValidationStatus.INCORRECT,
                target_context=target_doc.doc_id,
                message="Statement contradicted by documented claims",
                contradicting_claims=[
                    {
                        "claim_id": c.claim_id,
                        "text": c.text,
                        "verbatim": c.verbatim_quote,
                        "contradiction_type": c.contradiction_type
                    }
                    for c in contradicting_claims
                ],
                confidence=self._compute_contradiction_confidence(contradicting_claims)
            )

        if supporting_claims:
            # Support trouvé → CONFIRMED
            return TextValidationResponse(
                status=ValidationStatus.CONFIRMED,
                target_context=target_doc.doc_id,
                message="Statement supported by documented claims",
                supporting_claims=[
                    {
                        "claim_id": c.claim_id,
                        "text": c.text,
                        "verbatim": c.verbatim_quote,
                        "support_strength": c.similarity_score
                    }
                    for c in supporting_claims
                ],
                confidence=self._compute_support_confidence(supporting_claims)
            )

        # 6. Pas trouvé dans target → chercher avant
        previous_results = await self._search_previous_contexts(
            extracted.assertion,
            target_doc
        )

        if previous_results.found_in_previous:
            # Trouvé avant mais pas en latest → UNCERTAIN avec signals
            uncertainty = UncertaintyAnalysis.analyze(
                claim_key=None,
                found_in_contexts=list(previous_results.contexts.keys()),
                not_found_in_contexts=[target_doc.doc_id],
                all_claims=previous_results.all_claims
            )

            return TextValidationResponse(
                status=ValidationStatus.UNCERTAIN,
                target_context=target_doc.doc_id,
                message="Statement documented in previous contexts but not in target",
                found_in_previous=previous_results.contexts,
                uncertainty_analysis=uncertainty,
                # JAMAIS dire REMOVED (INV-17)
                removal_status="not_asserted"
            )

        # 7. Jamais trouvé → NOT_DOCUMENTED
        return TextValidationResponse(
            status=ValidationStatus.NOT_DOCUMENTED,
            target_context=target_doc.doc_id,
            message="Statement not documented in available corpus"
        )

    async def _find_contradicting_claims(
        self,
        assertion: str,
        doc_id: str
    ) -> List[ContradictingClaim]:
        """
        Cherche des claims qui contredisent l'assertion.

        Types de contradiction détectés:
        - Négation directe ("X supports Y" vs "X does not support Y")
        - Valeur différente ("X is A" vs "X is B")
        - Exclusion ("X only supports Y" vs assertion "X supports Z")
        """
        # Récupérer claims candidates (même domaine sémantique)
        candidate_claims = await self.claim_index.search_similar(
            assertion,
            doc_id=doc_id,
            top_k=20
        )

        contradictions = []

        for claim in candidate_claims:
            contradiction = await self.contradiction_detector.detect(
                assertion,
                claim.text
            )

            if contradiction.is_contradiction:
                contradictions.append(ContradictingClaim(
                    claim_id=claim.claim_id,
                    text=claim.text,
                    verbatim_quote=claim.verbatim_quote,
                    contradiction_type=contradiction.type,
                    confidence=contradiction.confidence
                ))

        # Trier par confiance
        return sorted(contradictions, key=lambda c: c.confidence, reverse=True)

    async def _find_supporting_claims(
        self,
        assertion: str,
        doc_id: str
    ) -> List[SupportingClaim]:
        """
        Cherche des claims qui supportent l'assertion.

        Support = similarité sémantique haute + pas de contradiction.
        """
        candidate_claims = await self.claim_index.search_similar(
            assertion,
            doc_id=doc_id,
            top_k=10,
            min_similarity=0.75  # Seuil de support
        )

        supporting = []

        for claim in candidate_claims:
            # Vérifier que ce n'est pas une contradiction déguisée
            contradiction = await self.contradiction_detector.detect(
                assertion,
                claim.text
            )

            if not contradiction.is_contradiction:
                supporting.append(SupportingClaim(
                    claim_id=claim.claim_id,
                    text=claim.text,
                    verbatim_quote=claim.verbatim_quote,
                    similarity_score=claim.similarity
                ))

        return supporting
```

---

## 9. TESTS BLACKBOX V1 (6 Tests Critiques)

```python
# tests/claimfirst/test_temporal_blackbox.py

class TestTemporalBlackbox:
    """
    6 tests blackbox pour valider le socle V1.

    Ces tests DOIVENT passer avant release.
    """

    @pytest.fixture
    def corpus(self):
        """Charge le corpus SAP (3 docs)."""
        return load_test_corpus([
            "018_S4HANA_1809_...",
            "025_SAP_S4HANA_2023_...",
            "023_...2025_..."
        ])

    # TEST 1: Latest selection avec justification
    async def test_latest_selected_with_justification(self, corpus):
        """
        Question sans contexte → latest sélectionné + pourquoi.
        """
        engine = TemporalQueryEngine(corpus)
        response = await engine.query_still_applicable(
            "Does S/4HANA support real-time analytics?"
            # Pas de target_context → doit utiliser latest
        )

        # Latest doit être sélectionné
        assert response.target_context is not None
        # Doit être 2025 (le plus récent)
        assert "2025" in response.target_context

        # Justification présente
        assert response.latest_selection_reason is not None

    # TEST 2: Since when avec ordering CERTAIN
    async def test_since_when_ordering_certain(self, corpus):
        """
        "Since when X?" avec axe ordering CERTAIN (1809/2023/2025).
        """
        engine = TemporalQueryEngine(corpus)
        response = await engine.query_since_when(
            "Since when does S/4HANA support General Ledger?"
        )

        # Timeline disponible
        assert response.status == TemporalQueryStatus.TIMELINE_AVAILABLE

        # Première occurrence identifiée
        assert response.first_occurrence is not None

        # Claims preuves présentes
        assert len(response.first_occurrence_claims) > 0

        # Timeline ordonnée
        assert len(response.evolution_timeline) >= 1
        # Vérifier ordre croissant
        values = [e["axis_value"] for e in response.evolution_timeline]
        assert values == sorted(values)

    # TEST 3: Since when avec ordering UNKNOWN
    async def test_since_when_ordering_unknown_refuses_timeline(self, corpus):
        """
        "Since when X?" sur axe ordering UNKNOWN → refuse timeline.
        """
        # Simuler un corpus avec axe non ordonnable
        corpus_unknown_order = create_corpus_with_unknown_order()

        engine = TemporalQueryEngine(corpus_unknown_order)
        response = await engine.query_since_when(
            "Since when does feature X exist?"
        )

        # NE DOIT PAS donner de timeline
        assert response.status == TemporalQueryStatus.CONTEXTS_LISTED

        # DOIT lister les contextes sans ordre
        assert response.contexts_unordered is not None
        assert len(response.contexts_unordered) > 0

        # NE DOIT PAS dire "depuis context X"
        assert response.first_occurrence is None

    # TEST 4: Validation contradiction explicite
    async def test_validation_contradiction_detected(self, corpus):
        """
        Phrase fausse (contradiction explicite) → INCORRECT.
        """
        validator = TextValidator(corpus)
        response = await validator.validate(
            "S/4HANA does not support cloud deployment",
            target_context="2023"
        )

        # Doit détecter contradiction
        assert response.status == ValidationStatus.INCORRECT

        # Claims contradictoires présentes
        assert len(response.contradicting_claims) > 0

        # Type de contradiction identifié
        assert response.contradicting_claims[0]["contradiction_type"] is not None

    # TEST 5: Validation UNCERTAIN avec signals
    async def test_validation_uncertain_with_signals(self, corpus):
        """
        Phrase non documentée en latest mais présente avant → UNCERTAIN + signals.
        """
        # Simuler une feature présente en 2023 mais pas en 2025
        validator = TextValidator(corpus)
        response = await validator.validate(
            "Feature XYZ is available",  # Présent en 2023, absent en 2025
            target_context="2025"
        )

        # Doit être UNCERTAIN (pas REMOVED - INV-17)
        assert response.status == ValidationStatus.UNCERTAIN

        # Signals présents
        assert response.uncertainty_analysis is not None
        assert len(response.uncertainty_analysis.signals) > 0

        # JAMAIS REMOVED sans preuve explicite
        assert response.removal_status == "not_asserted"

    # TEST 6: Disambiguation obligatoire sur question vague
    async def test_disambiguation_forced_on_vague_query(self, corpus):
        """
        Question vague ("feature accounting") → disambiguation obligatoire.
        """
        engine = TemporalQueryEngine(corpus)
        response = await engine.query_since_when(
            "Since when is accounting available?"  # Vague: GL? Cost? Management?
        )

        # Doit demander disambiguation
        assert response.status == TemporalQueryStatus.DISAMBIGUATION_REQUIRED

        # Options enrichies (pas juste labels)
        assert len(response.disambiguation_options) > 0
        for option in response.disambiguation_options:
            assert "label" in option
            assert "sample_claim_text" in option  # INV-18
            assert "doc_count" in option

        # PAS de réponse partielle
        assert response.first_occurrence is None
        assert response.evolution_timeline is None
```

---

## 10. INVARIANTS COMPLETS V2.1

| ID | Invariant | Fichier Principal |
|----|-----------|-------------------|
| INV-11 | IntentResolver → CANDIDATS, pas décision | intent_resolver.py |
| INV-12 | ClaimKey validated si ≥2 docs | claim_key.py |
| INV-13 | COMPARABLE_WITH jamais persisté | comparability_resolver.py |
| INV-14 | compare() → None si ordre inconnu | applicability_axis.py |
| INV-15 | Latest = gouvernance multi-critères | latest_selector.py |
| INV-16 | UNCERTAIN avec uncertainty_signals | uncertainty_signals.py |
| INV-17 | REMOVED seulement si explicite | text_validator.py |
| **INV-18** | Disambiguation UI enrichie (pas label-only) | intent_resolver.py |
| **INV-19** | ClaimKey candidate: pas de "since when" | claim_key.py |
| **INV-20** | Authority unknown → ask, pas score | latest_selector.py |
| **INV-21** | observed_values = stats + sample | applicability_axis.py |
| **INV-22** | primary_axis depuis policy explicite | comparability_resolver.py |

---

## 11. CHECKLIST GO/NO-GO V1

| Critère | Statut | Notes |
|---------|--------|-------|
| Disambiguation UI enrichie | ✅ Verrouillé | INV-18 |
| ClaimKey candidate rules | ✅ Verrouillé | INV-19 |
| Authority unknown handling | ✅ Verrouillé | INV-20 |
| AxisValue persistence structurée | ✅ Verrouillé | Section 4 |
| observed_values optimisé | ✅ Verrouillé | INV-21 |
| heuristic_confidence_hint renommé | ✅ Verrouillé | Section 6 |
| primary_axis depuis policy | ✅ Verrouillé | INV-22 |
| 6 tests blackbox définis | ✅ Verrouillé | Section 9 |

**VERDICT: GO FOR IMPLEMENTATION**

---

**Document finalisé pour implémentation V1**
**Prêt pour coding sprint 8 jours**
