# Design Doc — QuestionSignature Cross-Doc v1

**Date** : 2026-03-09
**Statut** : DRAFT — Pour review avant implémentation
**Référence** : `ARCH_CROSS_DOC_KNOWLEDGE_LAYERS.md` (C2a), analyse ChatGPT mars 2026

---

## 1. Principe directeur

> QuestionSignature n'est **pas** une brique autonome.
> C'est le **runtime object** obtenu quand on combine :
> - une **clé de question stabilisée** (ClaimKey / QuestionDimension)
> - un **contrat de valeur comparable** (ValueInfo / ValueContract)
> - un **scope de comparabilité résolu** (Scope Resolver)

On ne crée pas un nouvel extracteur parallèle. On **orchestre les briques existantes** :
- `ClaimKey` (`stratified/models/claimkey.py`) → base conceptuelle du registre de dimensions
- `ValueInfo` (`stratified/models/information.py`) → contrat de valeur
- `DocumentContext` + `CanonicalEntity` → scope resolution
- `value_contradicts.py` → comparabilité et non-exclusivité

### Règle d'agnosticité domaine

> **Aucun composant du pipeline ne doit contenir de logique spécifique à un domaine fonctionnel.**
>
> Les patterns existants (`ClaimKeyPatterns`, `question_signature_extractor.py`) sont
> biaisés IT/infrastructure (TLS, SLA, backup, RAM, ports...). Ils NE doivent PAS
> être utilisés comme source de vérité pour les dimensions, ni comme filtre de
> sélection des claims.
>
> Le pipeline détecte des **structures linguistiques** (nombre + unité, opérateur
> normatif, booléen, comparaison), jamais des **topics** (TLS, backup, SLA).
> Les dimensions émergent du corpus, elles ne sont pas pré-codées.

---

## 2. Architecture en 4 étapes

```
Claims (Neo4j, 15K+)
    │
    ▼
┌─────────────────────────────────────────┐
│  Étape 0 — Candidate Gating            │
│  Déterministe, sans LLM                │
│  Signaux structurels domain-agnostic   │
│  → ~20% des claims retenues           │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Étape 1 — Comparability Gate (LLM)    │
│  Classification binaire peu coûteuse   │
│  COMPARABLE_FACT / NON / ABSTAIN       │
│  → ~40% des candidates retenues       │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Étape 2 — Extraction structurée (LLM) │
│  Question + Value + Scope evidence     │
│  Evidence-locked, 1 claim à la fois    │
│  → QS candidates brutes               │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Étape 3 — Stabilisation               │
│  a) QuestionDimension Mapper           │
│  b) Scope Resolver (cascade)           │
│  c) Value Normalizer                   │
│  → QS finales persistées              │
└─────────────────────────────────────────┘
```

---

## 3. Artefact 1 — Candidate Gating (Étape 0)

### Principe

Filtre **domain-agnostic** basé sur des signaux de comparabilité structurels.
On ne cherche PAS "est-ce technique?" mais "cette claim porte-t-elle une réponse à une question factuelle stable?".

### Signaux positifs

Deux catégories de signaux, avec des règles de combinaison différentes :

**Signaux forts (claim retenue si ≥1 signal fort) :**

| Signal | Regex / Heuristique | Exemples |
|--------|---------------------|----------|
| **Valeur numérique + unité** | `\d+(?:\.\d+)?\s*(%\|GB\|MB\|days?\|hours?\|seconds?\|ms\|years?\|months?\|weeks?)` | "128 GB", "90 days", "99.7%" |
| **Version explicite** | `v?\d+\.\d+(?:\.\d+)*` ou `version\s+\d+` | "TLS 1.2", "version 7.50" |
| **Contrainte min/max + valeur** | `(minimum\|maximum\|at\s+least\|at\s+most\|up\s+to)\s+\d+` | "minimum 128 GB", "up to 500" |
| **Dépréciation/fin de vie** | `\b(deprecated\|end\s+of\s+(support\|life\|maintenance)\|replaced\s+by\|superseded)\b` | "deprecated since 2023" |
| **Valeur par défaut + valeur** | `(default\|defaults?\s+to)\s+\S+` | "default is 443", "defaults to enabled" |

**Signaux faibles (claim retenue seulement si ≥2 signaux faibles, OU 1 faible + entité liée) :**

| Signal | Regex / Heuristique | Pourquoi faible |
|--------|---------------------|-----------------|
| **Opérateur normatif seul** | `\b(must\|shall\|requires?\|mandatory\|prohibited)\b` | Trop fréquent sans valeur associée |
| **Booléen implicite seul** | `\b(enabled\|disabled\|supported\|not\s+supported\|allowed\|not\s+allowed)\b` | "Feature X is available" = bruit |
| **Fréquence/périodicité** | `\b(daily\|weekly\|monthly\|quarterly\|hourly)\b` | Peut être procédural |
| **Seuil/limite** | `\b(threshold\|limit\|cap\|ceiling\|floor)\b` | Peut être vague sans valeur |

> **Règle** : un signal faible seul ne suffit pas. Il faut soit un 2e signal
> (ex: "must" + "enabled" = 2 faibles → retenu), soit la présence d'une entité
> liée (ex: "encryption is enabled" + entité ABOUT "SAP S/4HANA" → retenu).
> Cela évite que des claims descriptives vagues ("Feature X is available")
> polluent le pipeline.

### Signaux négatifs (claim exclue si match)

| Signal | Raison |
|--------|--------|
| `len(text) < 30` | Trop court pour être une assertion factuelle complète |
| Claim de type `EXAMPLE` (rhetorical_role) | Les exemples ne sont pas des assertions comparables |
| Claim sans structured_form ET sans entités liées | Pas de contexte pour le scope |

### Ce qui NE DOIT PAS être un signal

| Anti-signal | Pourquoi c'est interdit |
|---|---|
| Présence de mots-clés domaine (TLS, backup, SLA, RAM...) | Biaise vers IT/infra |
| Match d'un `ClaimKeyPattern` existant | Patterns domain-specific |
| Présence d'un nom de produit SAP | Biaise vers un éditeur |
| Langue ou format spécifique | Le système est multi-langue |

Le prefilter détecte des **structures linguistiques** universelles, pas des topics.

### Interface Python

```python
@dataclass
class GatingResult:
    """Résultat du candidate gating."""
    claim_id: str
    retained: bool
    signals: list[str]      # Signaux matchés (pour audit)
    score: int              # Nombre de signaux (pour priorisation batch)

def candidate_gate(claim: Claim) -> GatingResult:
    """
    Filtre déterministe domain-agnostic.
    Retourne retained=True si ≥1 signal positif et 0 signal négatif bloquant.
    """
```

### Projection de coût

Sur le corpus actuel (15 782 claims) :
- Analyse du dry-run : ~178 claims avec "must be", ~95 "is required", ~101 "is available", ~28 "by default", ~14 "up to N"
- Estimation : **~2000-3000 claims retenues** (~15-20%)

---

## 4. Artefact 2 — Comparability Gate LLM (Étape 1)

### Prompt

```
You are a comparability classifier. Given a factual claim from a document,
determine whether it answers an IMPLICIT FACTUAL QUESTION that could
meaningfully appear in OTHER INDEPENDENT documents.

A COMPARABLE_FACT is a claim that:
- States a specific value, constraint, requirement, policy, or capability
- Could be asked as a stable factual question (e.g., "What is X?", "Is X required?")
- Another document about a related subject could answer the SAME question differently

A NON_COMPARABLE_FACT is a claim that:
- Is purely procedural ("To configure X, do Y")
- Is an example or illustration
- Is too context-specific to appear in another document
- Describes a workflow step, not an assertion

Claim: "{claim_text}"
Entities mentioned: {entity_names}

Respond with exactly one of:
- COMPARABLE_FACT
- NON_COMPARABLE_FACT
- ABSTAIN (if genuinely uncertain)
```

### Politique ABSTAIN

- **Mode précision (défaut)** : ABSTAIN → drop (traité comme NON)
- **Mode découverte** : ABSTAIN → extraction si score gating ≥ 2 signaux structurels

### Coût estimé

- ~2500 claims × ~50 tokens/claim = ~125K tokens
- Avec Qwen2.5-14B local (burst) : quasi-gratuit
- Avec API cloud : ~$0.15 (Haiku) à ~$2 (Sonnet)

---

## 5. Artefact 3 — Extraction structurée (Étape 2)

### Prompt

```
You are a factual question extractor. Given a claim from a document,
extract the implicit factual question it answers.

RULES:
1. The question must be ANSWERABLE by the claim text alone
2. The dimension_key must be snake_case, ≤ 5 words, domain-agnostic
   Examples: "min_tls_version", "data_retention_period", "backup_frequency"
   Bad: "sap_s4hana_tls" (too specific), "requirement" (too vague)
3. Extract the value AS STATED in the claim (raw), then normalize if possible
4. For scope: extract ONLY what the claim explicitly states or implies
   about WHICH product/subject/context this applies to
5. If you cannot extract a stable question, return null

Claim: "{claim_text}"
Entities: {entity_names}
Document subject: "{doc_primary_subject}"

Respond in JSON:
{
  "candidate_question": "What is the minimum TLS version required?",
  "candidate_dimension_key": "min_tls_version",
  "value_type": "version",          // number|version|boolean|string|enum|percent
  "value_raw": "TLS 1.3",
  "value_normalized": "1.3",
  "operator": ">=",                 // =, >=, <=, >, <, approx, in
  "scope_evidence": "SAP S/4HANA",  // text from claim indicating scope
  "scope_basis": "claim_explicit",  // claim_explicit|claim_entities|document_context
  "confidence": 0.9,
  "abstain_reason": null
}
```

### Contrat de sortie

```python
@dataclass
class QSCandidate:
    """Sortie brute de l'étape 2 (avant stabilisation)."""
    claim_id: str
    doc_id: str

    # Question
    candidate_question: str
    candidate_dimension_key: str            # BROUILLON — jamais utilisé tel quel.
                                            # Sera normalisé par le Dimension Mapper (Étape 3a).

    # Value (contrat strict — liste fermée ci-dessous)
    value_type: str                         # Voir §5.1 — liste fermée
    value_raw: str
    value_normalized: Optional[str]
    operator: str                           # Voir §5.1 — liste fermée

    # Scope evidence (brut, pas encore résolu)
    scope_evidence: Optional[str]           # Texte de la claim indiquant le scope
    scope_basis: str                        # claim_explicit|claim_entities|document_context

    # Meta
    confidence: float
    abstain_reason: Optional[str]

    # Gate info (tracabilité)
    gate_label: str                         # COMPARABLE_FACT
    gating_signals: list[str]               # Signaux étape 0
```

### 5.1 Contrats stricts — Listes fermées (v1)

> Ces listes sont **contractuelles**. Le LLM doit produire exactement l'une de
> ces valeurs. Toute sortie hors liste est rejetée (fallback vers `ABSTAIN`).

**`value_type`** — Liste fermée :

| Valeur | Sémantique | Exemples |
|---|---|---|
| `number` | Quantité numérique avec ou sans unité | "128 GB", "36 months", "500" |
| `version` | Version logicielle ou standard | "1.2", "7.50", "2023 FPS03" |
| `boolean` | Vrai/faux, activé/désactivé | "enabled", "not supported", "mandatory" |
| `percent` | Pourcentage | "99.7%", "85%" |
| `enum` | Valeur parmi un ensemble fini | "daily", "weekly", "customer" |
| `string` | Texte libre (dernier recours) | "SAP S/4HANA 2020" |

**`operator`** — Liste fermée :

| Valeur | Sémantique | Exemple |
|---|---|---|
| `=` | Valeur exacte | "default port is 443" |
| `>=` | Minimum / au moins | "minimum version 1.2" |
| `<=` | Maximum / au plus | "must not exceed 36 months" |
| `>` | Strictement supérieur | "above 500 connections" |
| `<` | Strictement inférieur | "below 100ms" |
| `approx` | Approximation | "approximately 30 days" |
| `in` | Appartenance à un ensemble | "supported in EU, US, JP" |

> Toute sortie LLM avec un `value_type` ou `operator` hors de ces listes est
> **rejetée** et la claim est marquée `abstain_reason: "invalid_value_type"`
> ou `"invalid_operator"`.

---

## 6. Artefact 4 — QuestionDimension Registry (Étape 3a)

### Modèle

```python
@dataclass
class QuestionDimension:
    """
    Registre de dimensions factuelles cross-doc.

    Évolution gouvernée de ClaimKey : même logique de promotion,
    mais avec politique de scope et contrat de valeur explicites.
    """
    dimension_id: str                       # "qd_min_tls_version"
    dimension_key: str                      # "min_tls_version"
    canonical_question: str                 # "What is the minimum TLS version required?"

    # Contrat de valeur
    value_type: str                         # number|version|boolean|string|enum|percent
    allowed_operators: list[str]            # [">=", "="]
    value_comparable: str                   # strict|loose|non_comparable

    # Politique de scope
    scope_policy: str                       # any|requires_product|requires_entity|requires_axis
    scope_axis_keys: list[str]              # ["product"] — axes nécessaires pour comparer

    # Lifecycle (identique à ClaimKey)
    status: str                             # candidate|validated|deprecated|merged
    info_count: int                         # Nombre de QS liées
    doc_count: int                          # Nombre de docs distincts

    # Gouvernance
    positive_examples: list[str]            # Claims qui matchent cette dimension
    negative_examples: list[str]            # Claims qui semblent matcher mais ne matchent PAS
    merged_into: Optional[str]              # Si status=merged, pointe vers la dimension cible

    # Audit
    created_at: datetime
    updated_at: datetime
    created_by: str                         # "pattern_level_a"|"llm_level_b"|"admin"
```

### Règles de promotion

| Transition | Condition |
|---|---|
| → `candidate` | Première apparition d'une dimension_key |
| `candidate` → `validated` | ≥ 2 documents distincts + valeurs comparables + pas de collision sémantique |
| `validated` → `deprecated` | Plus aucune QS active depuis N jours, OU remplacée par merge |
| `candidate/validated` → `merged` | Deux dimensions reconnues comme synonymes (même question, même value_type) |

### Mapper de normalisation

```python
def map_to_dimension(
    candidate_key: str,
    candidate_question: str,
    value_type: str,
    operator: str,
    registry: list[QuestionDimension],
) -> tuple[str, float]:
    """
    Mappe une clé candidate vers une dimension existante ou crée un candidate.

    Score composite (tous les critères sont nécessaires, pas juste l'embedding) :

    1. Similarité de dimension_key
       - Exacte → score = 1.0
       - Préfixe commun ≥ 60% → score = 0.8
       - Sinon → 0.0

    2. Similarité sémantique de la question canonique
       - Embedding similarity > 0.85 → bonus +0.3
       - MAIS : vérifier que min/max, in/out, enable/disable ne sont pas
         inversés. "minimum TLS version" ≠ "maximum TLS version" même si
         embedding similarity ~0.95.

    3. Compatibilité value_type (obligatoire)
       - Même type → OK
       - Types différents → BLOQUANT (pas de merge)

    4. Compatibilité operator
       - >= vs >= → OK
       - >= vs <= → BLOQUANT (question inversée : min vs max)
       - = vs >= → OK (loose)

    5. Veto sur inversion sémantique
       - Si la question candidate contient "minimum" et la dimension existante
         contient "maximum" (ou vice versa) → BLOQUANT
       - Si "enabled" vs "disabled" → BLOQUANT
       - Si "required" vs "optional" → BLOQUANT

    Seuil de match : score_composite ≥ 0.7 ET aucun critère BLOQUANT
    Sinon → nouvelle dimension candidate.

    Returns:
        (dimension_id, match_score)
    """
```

> **Point critique** : les embeddings rapprochent des questions voisines mais
> sémantiquement opposées ("min TLS version" ≈ "max TLS version", similarity ~0.95).
> Le score embedding seul est **insuffisant** pour le mapping. Les critères 4 et 5
> (operator + veto inversion) sont des **garde-fous obligatoires** contre les
> faux merges.

### Seed initial — Registry vide par défaut

> **Le registry démarre VIDE.** Aucune dimension pré-codée.
>
> Les patterns existants (`ClaimKeyPatterns`, `question_signature_extractor.py`)
> sont biaisés IT/infrastructure. Les utiliser comme seed biaiserait le système
> vers un domaine fonctionnel, violant le principe d'agnosticité.
>
> Les dimensions émergent organiquement du corpus via le pipeline LLM (Étape 2)
> puis sont stabilisées par le mapper (Étape 3a). Une dimension devient `validated`
> quand elle apparaît dans ≥2 documents indépendants — pas parce qu'elle était
> pré-codée.

**Exception optionnelle** : un administrateur peut injecter manuellement des
dimensions (`created_by: "admin"`) pour un tenant spécifique si le domaine est
connu. Mais ce n'est jamais automatique ni par défaut.

---

## 7. Artefact 5 — Scope Resolver (Étape 3b)

### Modèle de sortie

```python
@dataclass
class ResolvedScope:
    """Scope de comparabilité résolu pour une QS."""

    # Ancre primaire
    primary_anchor_type: str                # canonical_entity|document_subject|legal_frame|
                                            # population|channel|service_scope|other
    primary_anchor_id: Optional[str]        # CanonicalEntity ID si applicable
    primary_anchor_label: str               # "SAP S/4HANA"

    # Axes de qualification (réutilise ApplicabilityAxis)
    axes: list[ScopeAxis]

    # Provenance
    scope_basis: str                        # claim_explicit|claim_entities|
                                            # section_context|document_context
    inheritance_mode: str                   # explicit|mixed|inherited

    # Statut
    scope_status: str                       # resolved|inherited|ambiguous|missing
    scope_confidence: float                 # [0-1]

    # Comparabilité
    comparable_for_dimension: bool          # True si le scope est suffisant
                                            # pour la dimension_key donnée


@dataclass
class ScopeAxis:
    """Un axe de qualification du scope."""
    axis_key: str                           # "product", "edition", "region", "population"
    value: str                              # "SAP S/4HANA"
    value_id: Optional[str]                 # CanonicalEntity ID si applicable
    source: str                             # "claim"|"entity"|"document"
```

### Cascade de résolution

```
Priorité 1 — Scope explicite dans la claim
    Si claim.text mentionne un produit/sujet identifiable
    ET ce produit est lié à une CanonicalEntity
    → scope_basis = "claim_explicit"
    → scope_status = "resolved"
    → scope_confidence = 0.95

Priorité 2 — Entités ABOUT liées à la claim
    Si claim -[:ABOUT]-> Entity -[:SAME_CANON_AS]-> CanonicalEntity
    ET l'entité a un entity_type discriminant pour le scope
    → scope_basis = "claim_entities"
    → scope_status = "resolved"
    → scope_confidence = 0.85

    Résolution du type d'ancre depuis entity_type :
    - PRODUCT, COMPONENT → primary_anchor_type = "canonical_entity"
    - STANDARD, REGULATION → primary_anchor_type = "legal_frame"
    - ACTOR, ORGANIZATION → primary_anchor_type = "service_scope"
    - CONCEPT, METRIC, OTHER → NON discriminant pour le scope,
      passer à la priorité 3

    Note : CanonicalEntity porte déjà entity_type (inféré par vote
    majoritaire sur les Entity sources, voir ARCH_CROSS_DOC v3 §C1).
    Si entity_type = "other" ou absent → le scope n'est pas résolu
    par cette priorité, on descend dans la cascade.

Priorité 3 — Contexte de section / passage
    Si claim.passage_id → Passage.section_title contient un sujet identifiable
    → scope_basis = "section_context"
    → scope_status = "inherited"
    → scope_confidence = 0.70

Priorité 4 — DocumentContext
    Si DocumentContext.primary_subject est résolu
    → scope_basis = "document_context"
    → scope_status = "inherited"
    → scope_confidence = 0.60

Priorité 5 — Aucun scope
    → scope_status = "ambiguous"
    → comparable_for_dimension = False
```

### Conditions de blocage de comparabilité

Deux QS sont **comparables** si et seulement si :

1. Même `dimension_key` (validée, pas candidate)
2. `value_type` compatible
3. `operator` compatible (>= vs >= OK, >= vs = OK avec LOOSE, >= vs <= → NON)
4. `primary_anchor` identique OU relié via `SAME_CANON_AS`
5. Axes qualifiants **non contradictoires** (ex: "EU" vs "China" → NON)
6. `scope_status` ≠ `ambiguous` pour les deux

```python
@dataclass
class ComparabilityVerdict:
    """Résultat de la comparaison de deux QS."""
    level: str                              # COMPARABLE_STRICT | COMPARABLE_LOOSE |
                                            # NOT_COMPARABLE | NEED_REVIEW
    reason: Optional[str]                   # Obligatoire si NOT_COMPARABLE ou NEED_REVIEW
    blocking_criterion: Optional[str]       # Le critère qui a bloqué

# Raisons de non-comparabilité (liste fermée pour debug et audit)
NON_COMPARABILITY_REASONS = [
    "dimension_not_validated",              # dimension_key encore candidate
    "dimension_mismatch",                   # dimension_keys différentes
    "incompatible_value_type",              # number vs boolean par ex.
    "incompatible_operator",                # >= vs <= (question inversée)
    "anchor_mismatch",                      # scopes sans lien SAME_CANON_AS
    "contradictory_axes",                   # EU vs China
    "ambiguous_scope",                      # scope_status = ambiguous sur ≥1
    "missing_scope",                        # scope_status = missing sur ≥1
]

def are_comparable(qs_a: QuestionSignature, qs_b: QuestionSignature) -> ComparabilityVerdict:
    """
    Évalue la comparabilité de deux QS.
    La raison de non-comparabilité est TOUJOURS renseignée si level ≠ COMPARABLE_*.
    """
```

---

## 8. Matrice de décision de comparabilité

| Critère | STRICT | LOOSE | NOT_COMPARABLE |
|---|---|---|---|
| dimension_key | validated, identique | validated, identique | différente OU candidate |
| value_type | identique | identique | incompatible |
| operator | identique | compatible (≥ vs =) | contradictoire (≥ vs ≤) |
| primary_anchor | identique | relié via SAME_CANON_AS | sans lien |
| axes qualifiants | tous identiques | non contradictoires | contradictoires (EU vs CN) |
| scope_status | resolved des 2 côtés | ≥1 inherited | ≥1 ambiguous |

---

## 9. Modèle final — QuestionSignature (runtime object)

```python
@dataclass
class QuestionSignature:
    """
    Runtime object = ClaimKey stabilisée + Value Contract + Scope résolu.
    Persisté en Neo4j après les 4 étapes.
    """
    qs_id: str                              # "qs_{claim_id}_{dimension_key}"

    # Lien claim source
    claim_id: str
    doc_id: str
    tenant_id: str

    # Dimension (depuis le registry)
    dimension_id: str                       # "qd_min_tls_version"
    dimension_key: str                      # "min_tls_version"
    canonical_question: str                 # "What is the minimum TLS version required?"

    # Value Contract (depuis ValueInfo)
    value: ValueInfo                        # kind, raw, normalized, unit, operator, comparable

    # Scope résolu
    scope: ResolvedScope                    # Ancre + axes + provenance + statut

    # Extraction metadata
    extraction_method: str                  # "pattern_level_a"|"llm_level_b"
    extraction_confidence: float            # [0-1]
    gate_label: str                         # COMPARABLE_FACT
    gating_signals: list[str]               # Signaux étape 0

    # Audit
    created_at: datetime
```

### Relations Neo4j

```cypher
(:Claim)-[:HAS_QUESTION_SIG {confidence}]->(:QuestionSignature)
(:QuestionSignature)-[:ANSWERS]->(:QuestionDimension)
(:QuestionSignature)-[:SCOPED_BY]->(:CanonicalEntity)  // optionnel
```

---

## 10. Cas de test représentatifs (10 cas)

### Cas 1 — Comparaison valide, scope explicite

```
Claim A: "SAP S/4HANA requires TLS 1.2 for all connections"
Claim B: "SAP S/4HANA must use TLS 1.3 minimum"
→ dimension_key: "min_tls_version"
→ scope: {primary_anchor: "SAP S/4HANA", basis: claim_explicit}
→ Verdict: COMPARABLE_STRICT, values 1.2 vs 1.3 → EVOLUTION
```

### Cas 2 — Comparaison invalide, scopes différents

```
Claim A: "SAP S/4HANA requires TLS 1.2"
Claim C: "SuccessFactors requires TLS 1.3"
→ dimension_key: "min_tls_version" (identique)
→ scope A: {anchor: "SAP S/4HANA"}, scope C: {anchor: "SuccessFactors"}
→ Verdict: NOT_COMPARABLE (anchors non reliés via SAME_CANON_AS)
```

### Cas 3 — Scope hérité du document

```
Claim: "The minimum version is 7.50 for the ABAP kernel"
Document: "SAP S/4HANA 2023 Installation Guide"
→ dimension_key: "min_version"
→ scope: {anchor: "SAP S/4HANA", basis: document_context, status: inherited}
→ Comparable avec LOOSE seulement
```

### Cas 4 — Claim non-comparable (procédurale)

```
Claim: "To configure SSL, open transaction STRUST"
→ Étape 0: signal "configure" → retenu (opérateur normatif? non, procédural)
→ Étape 1 (LLM): NON_COMPARABLE_FACT
→ Drop
```

### Cas 5 — Booléen implicite

```
Claim: "Encryption at rest is enabled by default"
→ dimension_key: "encryption_at_rest_default"
→ value: {type: boolean, raw: "enabled", normalized: true}
→ scope: {basis: document_context}
```

### Cas 6 — Multi-domaine (réglementaire)

```
Claim: "Under GDPR, data retention must not exceed 36 months"
→ dimension_key: "max_data_retention"
→ value: {type: number, raw: "36 months", normalized: 36, unit: "months", operator: "<="}
→ scope: {anchor_type: "legal_frame", anchor_label: "GDPR"}
```

### Cas 7 — Multi-domaine (clinique)

```
Claim: "Metformin dosage for adults over 65 should not exceed 1500mg daily"
→ dimension_key: "max_daily_dosage"
→ value: {type: number, raw: "1500mg", normalized: 1500, unit: "mg", operator: "<="}
→ scope: {anchor_type: "population", anchor_label: "adults over 65",
          axes: [{key: "molecule", value: "Metformin"}]}
```

### Cas 8 — ABSTAIN au gate

```
Claim: "SAP BTP provides integration capabilities"
→ Étape 0: signal "provides" (?) → seuil = 1 signal faible
→ Étape 1 (LLM): ABSTAIN
→ Mode précision: Drop. Mode découverte: Drop aussi (score gating = 1 < 2)
```

### Cas 9 — Dimension key collision

```
QS candidate: dimension_key = "minimum_tls"
Registry existant: "min_tls_version" (question similaire, même value_type)
→ Mapper: score composite = 0.92 → match vers "min_tls_version"
→ PAS de création de nouvelle dimension
```

### Cas 10 — Nouvelle dimension émergente

```
QS candidate: dimension_key = "max_concurrent_sessions"
Registry: aucun match > 0.7
→ Créer QuestionDimension candidate
→ Statut = candidate (1 seul doc)
→ Deviendra validated quand un 2e doc produit la même dimension
```

---

## 11. Plan d'évaluation

### Gold set minimal (avant implémentation complète)

| Catégorie | Nombre | Source |
|---|---|---|
| Claims comparables (vrais positifs) | 50 | Security Guides 2022+2023 |
| Claims factuelles mais non comparables | 50 | Feature Scope Descriptions |
| Cas scope ambigu | 30 | Claims sans entité explicite |
| Faux amis cross-doc (même question, scope différent) | 20 | Multi-produit |
| Cas multi-domaines | 20 | Réglementaire, clinique (synthétique) |

### Métriques cibles

| Métrique | Cible |
|---|---|
| Précision gate (COMPARABLE vs NON) | ≥ 90% |
| Rappel gate | ≥ 70% (faux négatifs tolérés) |
| Stabilité dimension_key (même question → même clé) | ≥ 95% |
| Précision scope resolver | ≥ 85% |
| Taux de comparabilité valide | ≥ 80% des paires tentées |

---

## 12. Relation avec le code existant

### Briques à réutiliser

| Brique existante | Rôle dans le nouveau pipeline | Attention |
|---|---|---|
| `ClaimKey` (stratified/models/) | **Modèle conceptuel** du QuestionDimension (status lifecycle, promotion rules) | Étendre ou référencer, pas copier |
| `ValueInfo` (stratified/models/information.py) | Contrat de valeur (kind, normalized, operator, comparable) | Réutiliser tel quel |
| `ContextInfo` (stratified/models/information.py) | Base du scope (product, region, edition, inheritance_mode) | Enrichir avec anchor typé |
| `DocumentContext` (claimfirst/models/) | Scope resolver priorité 4 | Réutiliser tel quel |
| `CanonicalEntity` + `SAME_CANON_AS` | Scope resolver priorité 2 + comparabilité cross-anchor | Réutiliser tel quel |
| `value_contradicts.py` | Non-exclusivity gate, ValueFrame parsing | Réutiliser tel quel |

### Briques existantes à NE PAS réutiliser comme moteur

| Brique | Pourquoi ne pas l'utiliser directement |
|---|---|
| `ClaimKeyPatterns` (stratified/claimkey/) | Patterns IT/cloud-spécifiques (SLA, TLS, backup, RTO/RPO). Viole l'agnosticité domaine. |
| `question_signature_extractor.py` (Level A) | Patterns IT/infra (RAM, ports, protocoles). Même biais. |
| `CANONICAL_PREDICATES` | Liste fermée de 12 prédicats. Utile comme signal faible dans le prefilter, mais ne doit pas conditionner la sélection. |

> Ces briques peuvent fournir des **signaux bonus** dans le prefilter (si un pattern matche, c'est un indice supplémentaire), mais jamais être la source de la `dimension_key` ni le critère principal de sélection.

### Code à créer

| Composant | Fichier suggéré |
|---|---|
| Candidate Gating | `src/knowbase/claimfirst/extractors/comparability_gate.py` |
| LLM Gate + Extraction | `src/knowbase/claimfirst/extractors/qs_llm_extractor.py` |
| QuestionDimension model | `src/knowbase/claimfirst/models/question_dimension.py` |
| Dimension Mapper | `src/knowbase/claimfirst/extractors/dimension_mapper.py` |
| Scope Resolver | `src/knowbase/claimfirst/extractors/scope_resolver.py` |
| QuestionSignature v2 model | Modifier `src/knowbase/claimfirst/models/question_signature.py` |
| Pipeline orchestrateur | `app/scripts/extract_question_signatures_v2.py` |
| Tests | `tests/claimfirst/test_qs_pipeline.py` |

### Code à supprimer / rétrograder

| Fichier | Action |
|---|---|
| `question_signature_extractor.py` (Level A regex) | Fusionner les signaux dans le candidate gating |
| `QuestionSignature` v1 model | Remplacer par v2 avec scope + value contract |

---

## 13. Séquencement d'implémentation

> **Principe** : cette implémentation est une **v1 instrumentée**. Chaque étape
> doit produire des logs de debug explicites (claims retenues/rejetées, raisons,
> scores) pour permettre l'audit et le tuning. Pas de boîte noire.

```
Phase 1 — Modèles de données (1-2 jours)
├── QuestionDimension model (registry vide, pas de seed)
├── ResolvedScope + ScopeAxis models
├── ComparabilityVerdict + NON_COMPARABILITY_REASONS
├── QSCandidate (contrat de sortie étape 2)
├── QuestionSignature v2 model (runtime object)
└── Tests unitaires sur les modèles

Phase 2 — Étape 0 + Scope Resolver (2 jours)
├── Candidate Gating (signaux forts/faibles, domain-agnostic)
├── Scope Resolver (cascade 5 niveaux)
├── Dry-run gating sur corpus → métriques de volume
├── Dry-run scope resolver sur les retenues → audit
└── Tests unitaires (10 cas §10)

Phase 3 — LLM Gate (1-2 jours)
├── Comparability Gate prompt + parsing (appel LLM séparé)
├── Politique ABSTAIN = drop (mode précision)
├── Tests sur sous-ensemble (2 docs sécurité + 1 non-IT)
└── Métriques : taux COMPARABLE / NON / ABSTAIN

Phase 4 — LLM Extraction + Mapper (2-3 jours)
├── Extraction structurée prompt + parsing (appel LLM séparé)
├── Validation contrats stricts (value_type, operator → listes fermées)
├── Dimension Mapper v1 (match déterministe d'abord, embedding en bonus)
├── Tests mapper (cas 9 + 10 du §10)
└── Métriques : taux de match vs création candidate

Phase 5 — Intégration + Audit (1-2 jours)
├── Script orchestrateur (pipeline complet)
├── Persistence Neo4j (QS + QuestionDimension + relations)
├── Dry-run complet sur 2 docs sécurité + 1 doc non-IT
├── Audit qualité : comparabilité, scope, dimension stability
└── Métriques de succès (§11)
```

**Effort total estimé** : 7-10 jours

> **Important** : le LLM gate (Phase 3) et l'extraction structurée (Phase 4)
> sont **deux appels LLM séparés**, pas un seul. Le coût supplémentaire est
> négligeable en mode burst local, et la séparation donne une bien meilleure
> lisibilité, debug et évaluation indépendante de chaque étape.

### Axes de scope v1 — Périmètre limité

Pour la v1, le scope resolver ne gère que 4 types d'axes :

| axis_key | Sémantique | Source typique |
|---|---|---|
| `product` | Produit/composant logiciel | CanonicalEntity (PRODUCT, COMPONENT) |
| `legal_frame` | Cadre réglementaire | CanonicalEntity (STANDARD, REGULATION) |
| `region` | Zone géographique | DocumentContext.qualifiers, claim text |
| `edition` | Version/édition du document | DocumentContext.axis_values |

Les axes plus riches (population, molécule, canal...) seront ajoutés après
validation de la v1 sur le corpus actuel.

---

## 14. Décisions ouvertes

1. **ClaimKey vs QuestionDimension** — **TRANCHÉ** :
   Ce sont deux objets distincts avec des rôles différents.
   - **ClaimKey** = pattern d'assertion locale. Sert à structurer l'extraction
     dans un document. Peut être domain-specific (hérité de `ClaimKeyPatterns`).
   - **QuestionDimension** = question factuelle cross-doc stable. Sert à aligner
     les informations entre documents. Domain-agnostic, gouverné par le registry.
   - Le flow est : `Claim → (optionnel) ClaimKey → QuestionDimension → QuestionSignature`
   - Une QS peut exister sans ClaimKey préalable (extraction LLM directe).
   - Une ClaimKey peut exister sans QuestionDimension (assertion locale non comparable).

2. **Batch LLM** — **TRANCHÉ** : deux appels séparés.
   - Gate (Étape 1) = classification binaire, prompt court, peu coûteux.
   - Extraction (Étape 2) = extraction structurée, prompt riche.
   - Combiner les deux dégraderait la lisibilité, le debug et l'évaluation
     indépendante. Le surcoût est négligeable en burst local.

3. **Embedding pour le Dimension Mapper** — **TRANCHÉ** : déterministe d'abord.
   - V1 : matching déterministe (similarité de dimension_key + compatibilité
     value_type/operator + veto inversions sémantiques). Pas d'embedding.
   - V2 (après validation) : ajouter embedding comme signal bonus, jamais
     comme critère principal. Utiliser l'embedding TEI existant si disponible.

4. **Granularité du gold set** — **TRANCHÉ** : coder d'abord le prefilter.
   - Phase 2 : dry-run du gating → identifier les claims retenues.
   - Constituer le gold set à partir des sorties du gating (plus réaliste
     que des cas inventés manuellement).
   - Compléter avec 20 cas synthétiques multi-domaines (réglementaire, clinique).

5. **scope_policy sur QuestionDimension** — **REPORTÉ à v2**.
   - En v1, `scope_policy` = `"any"` par défaut pour toutes les dimensions.
   - La comparabilité est contrôlée par le scope resolver + la matrice §8,
     pas par une politique par dimension.
   - Quand le corpus sera plus riche et les patterns de scope mieux compris,
     on ajoutera des policies spécifiques (`requires_product`, `requires_entity`).
