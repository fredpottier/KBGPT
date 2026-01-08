# Phase 2.11 - CanonicalClaim : Spécification Minimale

*Version: 0.1.0 - Draft Initial*
*Date: 2025-12-22*

## 1. Contexte et Motivation

### 1.1 Problème Identifié

Phase 2.10 gère les **relations binaires** (Subject → Relation → Object). Mais certaines informations critiques sont **unaires** :

| Type | Exemple | Structure |
|------|---------|-----------|
| Relation | "SAP HANA **requiert** 64GB RAM" | Subject → REQUIRES → Object |
| Claim | "Le SLA de S/4HANA est **99.7%**" | Subject → Attribut = Valeur |

Les Claims sont des **assertions de faits** sur un sujet, pas des relations entre deux concepts.

### 1.2 Cas d'Usage Critique : Variants vs Evolution

**Exemple réel :**
- Document A : "SLA S/4HANA Cloud = 99.7%"
- Document B : "SLA S/4HANA Cloud + Premium Package = 99.9%"

**Mauvaise interprétation :** 99.9% remplace 99.7%
**Bonne interprétation :** Ce sont des **variants** avec des scopes différents

```
CanonicalClaim #1:
  subject: S/4HANA Cloud
  claim_type: SLA_AVAILABILITY
  value: 99.7%
  scope_struct: {edition: "standard"}

CanonicalClaim #2:
  subject: S/4HANA Cloud
  claim_type: SLA_AVAILABILITY
  value: 99.9%
  scope_struct: {edition: "standard", package: "premium"}
```

→ Les deux **coexistent**, scope différent = claims distincts.

### 1.3 Killer Feature : CRR Evolution Tracker

Le **Customer Retention Rate (CRR)** est l'exemple canonique où on veut tracer l'évolution temporelle :

```
Q4 2023: CRR = 92%
Q1 2024: CRR = 94%
Q2 2024: CRR = 95%
```

Ici, les claims **se succèdent** dans le temps → relation `supersedes`.

---

## 2. Architecture 2-Layer (Miroir des Relations)

```
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 1 : EXTRACTION                     │
│                                                             │
│   Document → LLM → RawClaim (unary assertion brute)         │
│                                                             │
│   - 1 RawClaim par mention                                  │
│   - scope_raw = texte libre                                 │
│   - value_raw = texte brut                                  │
│   - flags = {negated, hedged, conditional, ambiguous_scope} │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   LAYER 2 : CONSOLIDATION                   │
│                                                             │
│   RawClaims → Grouping → CanonicalClaim                     │
│                                                             │
│   - Groupement par (subject, claim_type, scope_key)         │
│   - scope_struct = parsing structuré                        │
│   - Détection: refines / conflicts / supersedes             │
│   - Maturity: VALIDATED / CANDIDATE / CONFLICTING           │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Structures de Données

### 3.1 RawClaim (Layer 1)

```python
@dataclass
class RawClaimFlags:
    """Flags pour qualifier un RawClaim"""
    negated: bool = False           # "le SLA n'est PAS 99%"
    hedged: bool = False            # "environ", "approximativement"
    conditional: bool = False       # "si option premium"
    ambiguous_scope: bool = False   # scope mal défini

@dataclass
class RawClaim:
    """Assertion unaire brute extraite d'un document"""

    # Identifiants
    raw_claim_id: str               # UUID généré
    tenant_id: str = "default"

    # Sujet
    subject_concept_id: str         # ID du concept concerné
    subject_surface_form: str       # Texte original dans le doc

    # Claim
    claim_type: str                 # Type libre mais contrôlé
    value_raw: str                  # Valeur brute (ex: "99.7%", "64 Go")
    value_type: str                 # percentage | number | currency | boolean | text | duration | version

    # Scope (contexte d'applicabilité)
    scope_raw: str                  # Texte libre (audit)
    scope_struct: Dict[str, str]    # Clé/valeur extensible

    # Temporalité
    valid_time_hint: Optional[str]  # "Q4 2023", "depuis v2.0"

    # Provenance
    document_id: str
    chunk_id: str
    evidence: str                   # Citation exacte
    page_number: Optional[int]

    # Qualité
    confidence: float               # 0.0 - 1.0
    flags: RawClaimFlags

    # Métadonnées
    extraction_method: str = "llm_v1"
    extracted_at_utc: datetime = field(default_factory=datetime.utcnow)
```

### 3.2 CanonicalClaim (Layer 2)

```python
class ClaimMaturity(str, Enum):
    """Maturité épistémique d'un CanonicalClaim"""
    VALIDATED = "VALIDATED"               # Multi-source, cohérent
    CANDIDATE = "CANDIDATE"               # Source unique
    CONFLICTING = "CONFLICTING"           # Valeurs contradictoires
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"  # Dépend du contexte
    SUPERSEDED = "SUPERSEDED"             # Remplacé par version plus récente

@dataclass
class CanonicalClaim:
    """Claim consolidé et canonique"""

    # Identifiants
    canonical_claim_id: str         # UUID ou hash déterministe
    tenant_id: str = "default"

    # Sujet
    subject_concept_id: str         # Concept canonique

    # Claim canonique
    claim_type: str                 # Type normalisé
    value: str                      # Valeur canonique (normalisée)
    value_numeric: Optional[float]  # Valeur numérique si applicable
    unit: Optional[str]             # Unité (%, Go, €, etc.)

    # Scope structuré
    scope_struct: Dict[str, str]    # Clé/valeur extensible
    scope_key: str                  # Hash canonique pour groupement

    # Temporalité
    valid_from: Optional[date]
    valid_until: Optional[date]

    # Multi-sourcing
    distinct_documents: int
    total_assertions: int           # Nombre de RawClaims
    confidence_p50: float           # Médiane des confidences

    # Maturité
    maturity: ClaimMaturity
    status: str = "active"          # active | superseded | deprecated

    # Relations entre claims
    conflicts_with: List[str]       # IDs des claims en conflit
    refines: Optional[str]          # ID du claim parent (sous-scope)
    supersedes: Optional[str]       # ID du claim remplacé (temporel)

    # Sources
    sources: List[Dict[str, Any]]   # [{document_id, excerpt, date}]

    # Métadonnées
    created_at_utc: datetime
    last_seen_utc: datetime
```

---

## 4. Claim Types (Set Ouvert mais Contrôlé)

### 4.1 Types Génériques Recommandés

| claim_type | Description | value_type | Exemples |
|------------|-------------|------------|----------|
| `SLA_AVAILABILITY` | Disponibilité garantie | percentage | "99.7%", "99.9%" |
| `SLA_RESPONSE_TIME` | Temps de réponse garanti | duration | "< 200ms", "4h" |
| `THRESHOLD` | Seuil technique | number | "64 GB RAM min" |
| `PRICING` | Tarification | currency | "500€/user/month" |
| `VERSION` | Version actuelle | version | "v2.3.1", "2024 Q2" |
| `CAPACITY` | Capacité | number | "10M records max" |
| `CERTIFICATION` | Certification obtenue | text | "ISO 27001" |
| `METRIC` | Métrique business | number | "CRR = 94%" |
| `FEATURE_FLAG` | Disponibilité feature | boolean | "SSO = enabled" |
| `COMPATIBILITY` | Compatibilité | text | "Windows 10+" |

### 4.2 Extensibilité

Le système est **domain-agnostic** : nouveaux claim_types ajoutés par configuration, pas par code.

```yaml
# config/claim_types.yaml
claim_types:
  SLA_AVAILABILITY:
    value_type: percentage
    unit: "%"
    comparable: true

  METRIC:
    value_type: number
    comparable: true
    temporal: true  # Supporte supersedes

  PRICING:
    value_type: currency
    comparable: true
    scope_keys: [edition, region, contract_type]
```

---

## 5. Prompt d'Extraction (V1)

### 5.1 System Prompt

```
Tu es un expert en extraction d'informations factuelles.

Ta tâche : Extraire les CLAIMS (assertions de faits) depuis un texte.

Un CLAIM est une information UNAIRE : un SUJET possède un ATTRIBUT avec une VALEUR.

Exemples de claims :
- "Le SLA de S/4HANA est 99.7%" → sujet=S/4HANA, type=SLA_AVAILABILITY, value=99.7%
- "RAM minimum : 64 Go" → sujet=[contexte], type=THRESHOLD, value=64 Go
- "CRR Q4 2023 = 92%" → sujet=CRR, type=METRIC, value=92%, time=Q4 2023

SCOPE : Le contexte qui qualifie quand/où le claim s'applique.
- "avec le package premium" → scope: {package: "premium"}
- "en région Europe" → scope: {region: "Europe"}
- "depuis la version 2.0" → scope: {version: "2.0+"}

FLAGS à détecter :
- negated: le claim nie explicitement ("n'est PAS 99%")
- hedged: incertitude ("environ", "approximativement")
- conditional: condition ("si option X activée")
- ambiguous_scope: scope pas clair

NE PAS extraire :
- Relations entre deux concepts (utiliser extraction relations)
- Opinions ou jugements subjectifs
- Informations génériques sans valeur précise
```

### 5.2 User Prompt Template

```
## Catalogue de Concepts Disponibles
{catalogue_json}

## Texte à Analyser
{text}

## Instructions
Extrais les claims factuels. Pour chaque claim, fournis :

```json
{
  "claims": [
    {
      "subject_concept_id": "string",
      "subject_surface_form": "string",
      "claim_type": "string",
      "value_raw": "string",
      "value_type": "percentage|number|currency|boolean|text|duration|version",
      "scope_raw": "string",
      "scope_struct": {"key": "value"},
      "valid_time_hint": "string|null",
      "evidence": "citation exacte",
      "confidence": 0.0-1.0,
      "flags": {
        "negated": false,
        "hedged": false,
        "conditional": false,
        "ambiguous_scope": false
      }
    }
  ]
}
```
```

---

## 6. Règles de Consolidation

### 6.1 Groupement

Claims groupés par : `(subject_concept_id, claim_type, scope_key)`

Le `scope_key` est un hash canonique du `scope_struct` normalisé.

### 6.2 Détection des Relations entre Claims

```python
def detect_claim_relation(claim_a: CanonicalClaim, claim_b: CanonicalClaim) -> str:
    """Détecte la relation entre deux claims du même sujet et type"""

    # Même scope exact
    if claim_a.scope_key == claim_b.scope_key:
        if claim_a.value == claim_b.value:
            return "DUPLICATE"  # Fusion
        else:
            return "CONFLICTS"  # Valeurs différentes, même scope

    # Scope différent
    scope_a = claim_a.scope_struct
    scope_b = claim_b.scope_struct

    # B est un sous-scope de A (B plus spécifique)
    if is_subscope(scope_b, scope_a):
        return "B_REFINES_A"  # B précise A

    # A est un sous-scope de B
    if is_subscope(scope_a, scope_b):
        return "A_REFINES_B"

    # Scopes disjoints
    return "COEXIST"  # Variants indépendants


def is_subscope(child: Dict, parent: Dict) -> bool:
    """True si child contient toutes les clés de parent avec mêmes valeurs + extras"""
    for key, value in parent.items():
        if key not in child or child[key] != value:
            return False
    return len(child) > len(parent)
```

### 6.3 Détection Temporelle (Supersedes)

```python
def detect_supersedes(claims: List[CanonicalClaim]) -> List[Tuple[str, str]]:
    """Détecte les relations supersedes entre claims temporels"""

    # Trier par valid_from
    sorted_claims = sorted(claims, key=lambda c: c.valid_from or date.min)

    supersedes_pairs = []
    for i in range(1, len(sorted_claims)):
        prev = sorted_claims[i-1]
        curr = sorted_claims[i]

        # Même scope = succession temporelle
        if prev.scope_key == curr.scope_key:
            supersedes_pairs.append((curr.canonical_claim_id, prev.canonical_claim_id))
            prev.status = "superseded"
            prev.maturity = ClaimMaturity.SUPERSEDED

    return supersedes_pairs
```

### 6.4 Calcul Maturité

```python
def compute_claim_maturity(
    raw_claims: List[RawClaim],
    existing_conflicts: List[str]
) -> ClaimMaturity:
    """Calcule la maturité d'un CanonicalClaim"""

    # Conflits détectés
    if existing_conflicts:
        return ClaimMaturity.CONFLICTING

    # Valeurs multiples contradictoires
    unique_values = set(rc.value_raw for rc in raw_claims)
    if len(unique_values) > 1:
        return ClaimMaturity.CONFLICTING

    # Forte conditionnalité
    conditional_ratio = sum(1 for rc in raw_claims if rc.flags.conditional) / len(raw_claims)
    if conditional_ratio > 0.7:
        return ClaimMaturity.CONTEXT_DEPENDENT

    # Multi-sourcing
    distinct_docs = len(set(rc.document_id for rc in raw_claims))
    if distinct_docs >= 2:
        return ClaimMaturity.VALIDATED

    return ClaimMaturity.CANDIDATE
```

---

## 7. Response Contract v0

### 7.1 Principe : KG Gate

Le KG **contraint** ce que le système peut affirmer. Réponse = fonction de ce que le KG contient.

### 7.2 Niveaux de Réponse

| Niveau | Condition | Réponse Type |
|--------|-----------|--------------|
| **CONFIRMED** | CanonicalClaim VALIDATED + confiance ≥ 0.8 | "Le SLA de S/4HANA est 99.7% (confirmé par 3 sources)" |
| **CONTESTED** | CanonicalClaim CONFLICTING | "Deux valeurs trouvées : 99.7% (2 sources) vs 99.5% (1 source)" |
| **CONDITIONAL** | CanonicalClaim CONTEXT_DEPENDENT ou scope != {} | "99.7% en standard, 99.9% avec package premium" |
| **NO_EVIDENCE** | Aucun claim trouvé | "Aucune information sur le SLA de ce produit" |
| **SYNTHESIS** | Question complexe, multiples claims | Synthèse structurée avec sources |

### 7.3 Exemples Cross-Domain

**Question : "Quel est le SLA de S/4HANA ?"**

```json
{
  "response_type": "CONDITIONAL",
  "answer": "Le SLA de S/4HANA Cloud dépend de l'édition :",
  "claims": [
    {
      "value": "99.7%",
      "scope": "édition standard",
      "maturity": "VALIDATED",
      "sources": 3
    },
    {
      "value": "99.9%",
      "scope": "avec package premium",
      "maturity": "CANDIDATE",
      "sources": 1
    }
  ],
  "show_details": true
}
```

**Question : "Comment a évolué le CRR ?"**

```json
{
  "response_type": "SYNTHESIS",
  "answer": "Le Customer Retention Rate a progressé de 92% à 95% sur 3 trimestres :",
  "timeline": [
    {"period": "Q4 2023", "value": "92%", "status": "superseded"},
    {"period": "Q1 2024", "value": "94%", "status": "superseded"},
    {"period": "Q2 2024", "value": "95%", "status": "current"}
  ],
  "trend": "positive",
  "sources": ["rapport_annuel_2024.pdf", "board_q2.pptx"]
}
```

---

## 8. Schéma Neo4j

### 8.1 Nœuds

```cypher
// RawClaim (Layer 1)
CREATE CONSTRAINT raw_claim_id IF NOT EXISTS
FOR (rc:RawClaim) REQUIRE rc.raw_claim_id IS UNIQUE;

// CanonicalClaim (Layer 2)
CREATE CONSTRAINT canonical_claim_id IF NOT EXISTS
FOR (cc:CanonicalClaim) REQUIRE cc.canonical_claim_id IS UNIQUE;

// Index pour requêtes
CREATE INDEX claim_subject IF NOT EXISTS
FOR (cc:CanonicalClaim) ON (cc.subject_concept_id);

CREATE INDEX claim_type IF NOT EXISTS
FOR (cc:CanonicalClaim) ON (cc.claim_type);

CREATE INDEX claim_scope_key IF NOT EXISTS
FOR (cc:CanonicalClaim) ON (cc.scope_key);
```

### 8.2 Relations

```cypher
// RawClaim → CanonicalClaim
(rc:RawClaim)-[:CONSOLIDATED_INTO]->(cc:CanonicalClaim)

// CanonicalClaim → Concept
(cc:CanonicalClaim)-[:ABOUT]->(c:CanonicalConcept)

// Relations entre Claims
(cc1:CanonicalClaim)-[:CONFLICTS_WITH]->(cc2:CanonicalClaim)
(cc_child:CanonicalClaim)-[:REFINES]->(cc_parent:CanonicalClaim)
(cc_new:CanonicalClaim)-[:SUPERSEDES]->(cc_old:CanonicalClaim)

// Provenance
(rc:RawClaim)-[:EXTRACTED_FROM]->(d:Document)
```

---

## 9. Plan d'Implémentation

### Phase 2.11.1 : Types et Writer (Priorité 1)

- [ ] Ajouter `RawClaimFlags`, `RawClaim`, `ClaimMaturity`, `CanonicalClaim` dans `types.py`
- [ ] Créer `raw_claim_writer.py` (écriture RawClaim → Neo4j)
- [ ] Créer `claim_consolidator.py` (RawClaim → CanonicalClaim)

### Phase 2.11.2 : Extraction LLM (Priorité 2)

- [ ] Ajouter prompt V1 dans `llm_relation_extractor.py` (ou nouveau module)
- [ ] Méthode `extract_claims()` avec parsing JSON
- [ ] Intégration dans pipeline d'ingestion

### Phase 2.11.3 : Response Contract (Priorité 3)

- [ ] Endpoint `/api/claims/{concept_id}`
- [ ] Service `ClaimResponseBuilder` avec logique CONFIRMED/CONTESTED/etc.
- [ ] Intégration dans synthèse de réponse

### Phase 2.11.4 : UI et Tracking (Priorité 4)

- [ ] Affichage claims dans fiche concept
- [ ] Timeline pour claims temporels (CRR tracker)
- [ ] Indicateurs visuels de maturité

---

## 10. Métriques de Succès

| Métrique | Cible Phase 2.11 |
|----------|------------------|
| Claims extraits / document | ≥ 2 en moyenne |
| Précision extraction | ≥ 85% (validation manuelle) |
| Scope parsing réussi | ≥ 70% des claims |
| Multi-sourcing (VALIDATED) | ≥ 30% des claims |
| Détection supersedes | 100% pour claims temporels |

---

## 11. Risques et Mitigations

| Risque | Mitigation |
|--------|------------|
| Confusion claim vs relation | Prompt clair + exemples + fallback ASSOCIATED_WITH |
| Scope parsing échoue | Fallback scope_raw toujours stocké |
| Explosion claim_types | Configuration YAML + révision périodique |
| Performance extraction | Batch processing + caching |

---

## 12. Références

- Phase 2.10 : Architecture V3 Relations (`PHASE2.10_RELATION_EXTRACTION_V3.md`)
- Vision OSMOSE : `OSMOSE_AMBITION_PRODUIT_ROADMAP.md`
- CRR Evolution Tracker : `PHASE1_SEMANTIC_CORE.md` (Killer Feature)

---

*Document créé le 2025-12-22 par Claude Code*
*Basé sur discussion stratégique ChatGPT + vision OSMOSE*
