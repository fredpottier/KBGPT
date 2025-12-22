# Phase 2.11a - Claims MVP : Plan d'Implémentation

*Version: 1.0.0*
*Date: 2025-12-22*
*Statut: APPROVED - Ready for Implementation*

---

## Table des Matières

1. [Contrat KG ↔ RAG (Acté)](#1-contrat-kg--rag-acté)
2. [Décisions Techniques Phase 2.11a](#2-décisions-techniques-phase-211a)
3. [API Response Schema v1](#3-api-response-schema-v1)
4. [Tracking Plan & Métriques](#4-tracking-plan--métriques)
5. [Checklist Definition of Done](#5-checklist-definition-of-done)
6. [Tâches d'Implémentation (P0/P1/P2)](#6-tâches-dimplémentation-p0p1p2)
7. [Risques et Mitigations](#7-risques-et-mitigations)

---

## 1. Contrat KG ↔ RAG (Acté)

### 1.1 Règle Fondamentale

> **Le KG qualifie la vérité, le RAG la raconte.**
> **Le KG ne tranche que si la qualification est incontestable.**

### 1.2 Maturity-Driven Flow

| Maturité | KG fait | RAG fait | Réponse |
|----------|---------|----------|---------|
| **VALIDATED** | Décide | N'invente rien | Valeur canonique + sources |
| **CANDIDATE** | Propose | Explique avec disclaimer | Valeur probable + narration |
| **CONFLICTING** | Refuse de trancher | Compare et explicite | Liste structurée + incertitude |
| **NO_CLAIM** | - | Fallback pur | Narration RAG seule |

### 1.3 Ce que le KG NE DOIT JAMAIS faire

- ❌ Supprimer une valeur conflictuelle sans preuve
- ❌ Trancher par récence si le scope est flou
- ❌ Masquer un conflit "pour simplifier la réponse"
- ❌ Se substituer au RAG quand l'incertitude est réelle

### 1.4 Seuils Go/No-Go Supersession (Phase 2.12)

| Métrique | Seuil GO | Raison |
|----------|----------|--------|
| % VALIDATED | ≥ 50% | Sinon trop de bruit |
| % CONFLICTING | ≤ 20% | Sinon système anxiogène |
| Qualité scope | ≥ 70% | Sinon faux variants |
| asserted_at fiable | ≥ 60% | Sinon récence inutile |

**Tous les critères doivent être vrais pour activer la supersession automatique.**

⚠️ **Supersession désactivée en Phase 2.11a** - On collecte les données d'abord.

---

## 2. Décisions Techniques Phase 2.11a

### 2.1 Architecture Claims

```
Document → Chunks → LLM Extraction → RawClaim → CanonicalClaim
                                                      │
                                                      ▼
                                              API Response
                                              (KG + RAG)
```

### 2.2 Modèle de Données

#### RawClaim (existant, à adapter)

```python
class RawClaim(BaseModel):
    raw_claim_id: str
    tenant_id: str = "default"
    raw_fingerprint: str

    # Sujet
    subject_concept_id: str
    subject_surface_form: Optional[str]

    # Claim - CHANGEMENT: attribute_key remplace claim_type
    attribute_key: str  # Ex: "sla.availability", "threshold.ram_min"
    value_raw: str
    value_type: ClaimValueType
    value_numeric: Optional[float]
    unit: Optional[str]

    # Scope
    scope_raw: str
    scope_struct: dict
    scope_key: str  # Hash normalisé

    # Temporalité
    asserted_at: Optional[datetime]  # Date du document
    asserted_at_confidence: float = 0.0  # 0-1
    asserted_at_source: str = "unknown"  # file_meta | doc_header | heuristic | unknown
    valid_time_hint: Optional[str]

    # Provenance
    source_doc_id: str
    source_chunk_id: str
    evidence_text: str

    # Document Authority (prévu, pas exploité en 2.11a)
    document_authority: str = "unknown"  # contractual | official | policy | technical | marketing | unknown

    # Qualité
    confidence: float
    flags: RawClaimFlags
```

#### CanonicalClaim (existant, à adapter)

```python
class CanonicalClaim(BaseModel):
    canonical_claim_id: str
    tenant_id: str = "default"

    # Sujet
    subject_concept_id: str

    # Claim canonique
    attribute_key: str  # Ex: "sla.availability"
    value: str
    value_numeric: Optional[float]
    unit: Optional[str]
    value_type: ClaimValueType

    # Scope
    normalized_scope: dict  # Normalisé
    raw_scope: dict  # Original (audit)
    scope_key: str

    # Multi-sourcing
    distinct_documents: int
    total_assertions: int
    confidence_p50: float  # ATTENTION: jamais utilisée seule pour décider (voir règle ci-dessous)

    # Maturité (Phase 2.11a: pas de SUPERSEDED)
    maturity: ClaimMaturity  # VALIDATED | CANDIDATE | CONFLICTING

    # Relations (Phase 2.11a: conflicts_with uniquement)
    conflicts_with: List[str]
    # refines: Optional[str]  # Désactivé en 2.11a
    # supersedes: Optional[str]  # Désactivé en 2.11a

    # Sources
    sources: List[ClaimSource]
```

### 2.3 Scope Normalization (Obligatoire)

#### Mapping Synonymes (v1)

```python
SCOPE_KEY_SYNONYMS = {
    # Géographie
    "geography": "region",
    "area": "region",
    "territory": "region",
    "market": "region",

    # Environnement
    "env": "environment",
    "deployment": "environment",

    # Édition/Tier
    "edition": "tier",
    "package": "tier",
    "level": "tier",
    "plan": "tier",

    # Plateforme
    "cloud": "platform",
    "hyperscaler": "platform",
    "provider": "platform",
}

SCOPE_VALUE_NORMALIZATIONS = {
    # Régions
    "europe": "emea",
    "eu": "emea",
    "apac": "asia_pacific",
    "americas": "americas",
    "na": "north_america",

    # Environnements
    "prod": "production",
    "dev": "development",
    "staging": "staging",

    # Tiers
    "standard": "standard",
    "premium": "premium",
    "enterprise": "enterprise",
}
```

#### Fonction de Normalisation

```python
def normalize_scope(raw_scope: dict) -> tuple[dict, str]:
    """
    Normalise un scope et retourne (normalized_scope, scope_key).
    """
    normalized = {}
    for key, value in raw_scope.items():
        # Normaliser la clé
        norm_key = SCOPE_KEY_SYNONYMS.get(key.lower().strip(), key.lower().strip())

        # Normaliser la valeur
        norm_value = value.lower().strip() if isinstance(value, str) else value
        norm_value = SCOPE_VALUE_NORMALIZATIONS.get(norm_value, norm_value)

        normalized[norm_key] = norm_value

    # Générer scope_key (hash stable)
    sorted_items = sorted(normalized.items())
    scope_key = hashlib.sha1(json.dumps(sorted_items).encode()).hexdigest()[:12]

    return normalized, scope_key
```

### 2.4 Document Authority

Champ prévu dans RawClaim, **pas exploité pour les décisions en 2.11a**.

```python
DOCUMENT_AUTHORITY_LEVELS = {
    "contractual": 5,   # Contrats, SLA officiels
    "official": 4,      # Documentation officielle
    "policy": 3,        # Politiques internes
    "technical": 2,     # Documentation technique
    "marketing": 1,     # Présentations, whitepapers
    "unknown": 0,       # Non déterminé
}
```

### 2.5 Règles de Garde-Fou

#### Règle 1 : confidence_p50 jamais seule

> **`confidence_p50` ne doit JAMAIS être utilisée seule pour décider de la maturité.**

Elle doit toujours être combinée avec :
- Nombre de sources distinctes (`distinct_documents`)
- Compatibilité des valeurs (même valeur vs divergentes)
- Qualité du scope (normalisé vs raw)

#### Règle 2 : Limite attribute_key par subject (soft)

> **Warning si un subject accumule > 50 attribute_keys distincts.**

Ce n'est pas un blocage, mais un indicateur de :
- Possible hallucination LLM
- Fragmentation silencieuse des claims
- Besoin de révision du prompt ou des documents

Logging recommandé :
```python
if len(attribute_keys_for_subject) > 50:
    logger.warning(
        f"[OSMOSE] Subject {subject_id} has {len(attribute_keys_for_subject)} "
        "distinct attribute_keys - review for fragmentation"
    )
```

### 2.6 asserted_at Extraction

```python
def extract_asserted_at(doc_metadata: dict, content: str) -> tuple[datetime, float, str]:
    """
    Extrait la date du document avec confidence et source.

    Returns:
        (date, confidence, source)
    """
    # Priorité 1: Date explicite dans le contenu
    date_in_content = extract_date_from_content(content)
    if date_in_content:
        return date_in_content, 0.9, "doc_header"

    # Priorité 2: Métadonnées fichier (PDF, PPTX)
    if "creation_date" in doc_metadata:
        return doc_metadata["creation_date"], 0.7, "file_meta"

    if "modified_date" in doc_metadata:
        return doc_metadata["modified_date"], 0.5, "file_meta"

    # Priorité 3: Heuristique (année dans le nom de fichier)
    year_match = re.search(r"20[12]\d", doc_metadata.get("filename", ""))
    if year_match:
        return datetime(int(year_match.group()), 1, 1), 0.3, "heuristic"

    # Fallback: date d'ingestion
    return datetime.utcnow(), 0.1, "unknown"
```

---

## 3. API Response Schema v1

### 3.1 Schéma Global

```typescript
interface ClaimAPIResponse {
  request_id: string;
  query: QueryInfo;
  decision_policy: DecisionPolicy;
  result_type: "CLAIM_ANSWER" | "CLAIM_COMPARISON" | "NO_CLAIM";

  // Présent si result_type = NO_CLAIM (clarification KG status)
  kg_status?: "NO_STRUCTURED_CLAIM_FOUND" | "KG_NOT_QUERIED";

  // Présent si result_type = CLAIM_ANSWER
  claim_answer?: ClaimAnswer;

  // Présent si result_type = CLAIM_COMPARISON
  claim_comparison?: ClaimComparison;

  // Toujours présent
  sources: Source[];
  alternatives: AlternativeClaim[];
  rag_fallback: RAGFallback | null;
  telemetry: Telemetry;
}
```

### 3.2 Types Détaillés

```typescript
interface QueryInfo {
  text: string;
  language: string;
  extracted_subject?: string;
  extracted_attribute?: string;
}

interface DecisionPolicy {
  mode: "kg_then_rag" | "kg_only" | "rag_only";
  kg_decides_only_if: "VALIDATED";
  rag_used_for: ("CANDIDATE" | "CONFLICTING" | "NO_CLAIM")[];
}

interface ClaimAnswer {
  subject: {
    concept_id: string;
    label: string;
  };
  attribute_key: string;
  value: {
    value: string | number | boolean;
    unit?: string;
    value_type: "number" | "percentage" | "currency" | "boolean" | "text" | "duration" | "version" | "date";
  };
  normalized_scope: Record<string, string>;
  raw_scope?: Record<string, string>;  // Pour audit
  maturity: "VALIDATED" | "CANDIDATE";
  confidence: number;
  explanation: string;
}

interface ClaimComparison {
  subject: {
    concept_id: string;
    label: string;
  };
  attribute_key: string;
  normalized_scope: Record<string, string>;
  maturity: "CONFLICTING";
  reason: string;
}

interface AlternativeClaim {
  value: {
    value: string | number | boolean;
    unit?: string;
    value_type: string;
  };
  confidence: number;
  sources: Source[];
}

interface Source {
  source_id: string;
  title: string;
  document_date?: string;
  authority: "contractual" | "official" | "policy" | "technical" | "marketing" | "unknown";
  evidence: {
    quote: string;
    location?: {
      page?: number;
      segment_id?: string;
    };
  };
}

interface RAGFallback {
  summary: string;
  supporting_chunks: {
    chunk_id: string;
    score: number;
    source_id: string;
    snippet: string;
  }[];
}

interface Telemetry {
  kg: {
    claims_considered: number;
    canonical_claims_considered: number;
  };
  rag: {
    chunks_considered: number;
  };
  latency_ms: {
    kg: number;
    rag: number;
    total: number;
  };
}
```

### 3.3 Exemples de Réponses

#### 3.3.1 VALIDATED (KG décide)

```json
{
  "request_id": "req_abc123",
  "query": {
    "text": "What is the SLA for S/4HANA Cloud, Private Edition?",
    "language": "en",
    "extracted_subject": "S/4HANA Cloud, Private Edition",
    "extracted_attribute": "sla.availability"
  },
  "decision_policy": {
    "mode": "kg_then_rag",
    "kg_decides_only_if": "VALIDATED",
    "rag_used_for": ["CANDIDATE", "CONFLICTING", "NO_CLAIM"]
  },
  "result_type": "CLAIM_ANSWER",
  "claim_answer": {
    "subject": {
      "concept_id": "c_s4hana_pe",
      "label": "SAP S/4HANA Cloud, Private Edition"
    },
    "attribute_key": "sla.availability",
    "value": {
      "value": 99.9,
      "unit": "%",
      "value_type": "percentage"
    },
    "normalized_scope": {
      "region": "global"
    },
    "maturity": "VALIDATED",
    "confidence": 0.93,
    "explanation": "Single canonical value validated from 3 consistent sources for the same scope."
  },
  "sources": [
    {
      "source_id": "doc_2024_contract",
      "title": "RISE with SAP - SLA Annex",
      "document_date": "2024-03-12",
      "authority": "contractual",
      "evidence": {
        "quote": "Availability is guaranteed at 99.9% for Private Edition deployments.",
        "location": {
          "page": 42,
          "segment_id": "seg_17"
        }
      }
    }
  ],
  "alternatives": [],
  "rag_fallback": null,
  "telemetry": {
    "kg": {
      "claims_considered": 6,
      "canonical_claims_considered": 2
    },
    "rag": {
      "chunks_considered": 0
    },
    "latency_ms": {
      "kg": 120,
      "rag": 0,
      "total": 140
    }
  }
}
```

#### 3.3.2 CANDIDATE (KG propose + RAG explique)

```json
{
  "request_id": "req_def456",
  "query": {
    "text": "What is the RAM requirement for SAP HANA?",
    "language": "en"
  },
  "decision_policy": {
    "mode": "kg_then_rag",
    "kg_decides_only_if": "VALIDATED",
    "rag_used_for": ["CANDIDATE", "CONFLICTING", "NO_CLAIM"]
  },
  "result_type": "CLAIM_ANSWER",
  "claim_answer": {
    "subject": {
      "concept_id": "c_hana",
      "label": "SAP HANA"
    },
    "attribute_key": "threshold.ram_min",
    "value": {
      "value": 64,
      "unit": "GB",
      "value_type": "number"
    },
    "normalized_scope": {
      "environment": "production"
    },
    "maturity": "CANDIDATE",
    "confidence": 0.74,
    "explanation": "Likely value from single source. RAG provides supporting context."
  },
  "sources": [
    {
      "source_id": "doc_tech_spec",
      "title": "SAP HANA Hardware Requirements",
      "document_date": "2023-09-15",
      "authority": "technical",
      "evidence": {
        "quote": "Minimum RAM: 64 GB for production workloads.",
        "location": {
          "page": 12
        }
      }
    }
  ],
  "alternatives": [],
  "rag_fallback": {
    "summary": "The 64 GB minimum is commonly cited for production environments. Development environments may require less (32 GB). Large-scale deployments may need significantly more based on data volume.",
    "supporting_chunks": [
      {
        "chunk_id": "qdr_chunk_42",
        "score": 0.87,
        "source_id": "doc_tech_spec",
        "snippet": "For production systems, a minimum of 64 GB RAM is required..."
      }
    ]
  },
  "telemetry": {
    "kg": {
      "claims_considered": 3,
      "canonical_claims_considered": 1
    },
    "rag": {
      "chunks_considered": 8
    },
    "latency_ms": {
      "kg": 95,
      "rag": 210,
      "total": 320
    }
  }
}
```

#### 3.3.3 CONFLICTING (KG refuse de trancher)

```json
{
  "request_id": "req_ghi789",
  "query": {
    "text": "What is the SLA availability for S/4HANA Cloud?",
    "language": "en"
  },
  "decision_policy": {
    "mode": "kg_then_rag",
    "kg_decides_only_if": "VALIDATED",
    "rag_used_for": ["CANDIDATE", "CONFLICTING", "NO_CLAIM"]
  },
  "result_type": "CLAIM_COMPARISON",
  "claim_comparison": {
    "subject": {
      "concept_id": "c_s4hana_cloud",
      "label": "SAP S/4HANA Cloud"
    },
    "attribute_key": "sla.availability",
    "normalized_scope": {
      "region": "global"
    },
    "maturity": "CONFLICTING",
    "reason": "Multiple incompatible values found for identical scope. Cannot determine which is current without additional context."
  },
  "sources": [],
  "alternatives": [
    {
      "value": {
        "value": 99.7,
        "unit": "%",
        "value_type": "percentage"
      },
      "confidence": 0.88,
      "sources": [
        {
          "source_id": "doc_2021_sla",
          "title": "SAP Cloud SLA Agreement 2021",
          "document_date": "2021-06-10",
          "authority": "contractual",
          "evidence": {
            "quote": "Service availability: 99.7%",
            "location": {
              "page": 8
            }
          }
        }
      ]
    },
    {
      "value": {
        "value": 99.9,
        "unit": "%",
        "value_type": "percentage"
      },
      "confidence": 0.85,
      "sources": [
        {
          "source_id": "doc_2024_marketing",
          "title": "RISE with SAP Overview",
          "document_date": "2024-03-12",
          "authority": "marketing",
          "evidence": {
            "quote": "Industry-leading 99.9% availability",
            "location": {
              "page": 15
            }
          }
        }
      ]
    }
  ],
  "rag_fallback": {
    "summary": "Two different SLA values are documented. The 99.7% appears in a 2021 contractual document, while 99.9% appears in 2024 marketing materials. The discrepancy may reflect: (1) an actual SLA improvement, (2) different editions (Public vs Private), or (3) marketing vs contractual commitments. Recommend verifying against the current contract.",
    "supporting_chunks": [
      {
        "chunk_id": "qdr_chunk_12",
        "score": 0.91,
        "source_id": "doc_2021_sla",
        "snippet": "..."
      },
      {
        "chunk_id": "qdr_chunk_45",
        "score": 0.89,
        "source_id": "doc_2024_marketing",
        "snippet": "..."
      }
    ]
  },
  "telemetry": {
    "kg": {
      "claims_considered": 8,
      "canonical_claims_considered": 2
    },
    "rag": {
      "chunks_considered": 12
    },
    "latency_ms": {
      "kg": 150,
      "rag": 280,
      "total": 450
    }
  }
}
```

#### 3.3.4 NO_CLAIM (Fallback RAG pur)

```json
{
  "request_id": "req_jkl012",
  "query": {
    "text": "What is the data retention policy for SAP SuccessFactors?",
    "language": "en"
  },
  "decision_policy": {
    "mode": "kg_then_rag",
    "kg_decides_only_if": "VALIDATED",
    "rag_used_for": ["CANDIDATE", "CONFLICTING", "NO_CLAIM"]
  },
  "result_type": "NO_CLAIM",
  "kg_status": "NO_STRUCTURED_CLAIM_FOUND",
  "claim_answer": null,
  "claim_comparison": null,
  "sources": [],
  "alternatives": [],
  "rag_fallback": {
    "summary": "No structured claim was found for data retention policy. Based on retrieved passages, SAP SuccessFactors data retention depends on customer configuration and regional compliance requirements. Standard retention is typically 7 years for HR records, but this varies by module and jurisdiction.",
    "supporting_chunks": [
      {
        "chunk_id": "qdr_chunk_78",
        "score": 0.72,
        "source_id": "doc_sf_admin",
        "snippet": "Data retention settings can be configured per module..."
      }
    ]
  },
  "telemetry": {
    "kg": {
      "claims_considered": 0,
      "canonical_claims_considered": 0
    },
    "rag": {
      "chunks_considered": 15
    },
    "latency_ms": {
      "kg": 45,
      "rag": 320,
      "total": 380
    }
  }
}
```

---

## 4. Tracking Plan & Métriques

### 4.1 Métriques de Distribution Maturité

```python
class ClaimMetrics:
    """Métriques à collecter pour chaque run d'extraction/consolidation."""

    # Distribution maturité
    total_canonical_claims: int
    count_validated: int
    count_candidate: int
    count_conflicting: int

    @property
    def pct_validated(self) -> float:
        return self.count_validated / self.total_canonical_claims * 100

    @property
    def pct_conflicting(self) -> float:
        return self.count_conflicting / self.total_canonical_claims * 100
```

**Objectifs Phase 2.11a :**

| Métrique | Cible | Seuil Alerte |
|----------|-------|--------------|
| % VALIDATED | ≥ 50% | < 30% |
| % CONFLICTING | ≤ 20% | > 35% |
| % CANDIDATE | remainder | - |

### 4.2 Qualité Scope

```python
class ScopeQualityMetrics:
    """Métriques de qualité des scopes extraits."""

    total_scopes_extracted: int
    scopes_normalized_clean: int  # Clés connues, valeurs normalisées
    scopes_partially_normalized: int  # Clés inconnues mais valeurs ok
    scopes_raw_only: int  # Normalisation échouée

    # Top erreurs
    unknown_keys: Counter  # {key: count}
    divergent_values: List[tuple]  # [(key, value1, value2, count)]

    @property
    def pct_clean(self) -> float:
        return self.scopes_normalized_clean / self.total_scopes_extracted * 100
```

**Objectifs Phase 2.11a :**

| Métrique | Cible | Action si non atteint |
|----------|-------|----------------------|
| % scopes clean | ≥ 70% | Enrichir SCOPE_KEY_SYNONYMS |
| Top 10 unknown keys | Analyse | Ajouter au mapping si récurrents |

### 4.3 Coverage asserted_at

```python
class TemporalCoverageMetrics:
    """Métriques de couverture temporelle."""

    total_raw_claims: int
    claims_with_asserted_at: int

    # Par source
    by_source: Dict[str, int]  # {"doc_header": N, "file_meta": N, ...}

    # Confidence distribution
    confidence_distribution: List[float]  # Histogramme

    @property
    def pct_with_date(self) -> float:
        return self.claims_with_asserted_at / self.total_raw_claims * 100

    @property
    def pct_high_confidence(self) -> float:
        """% claims avec confidence >= 0.7"""
        return sum(1 for c in self.confidence_distribution if c >= 0.7) / len(self.confidence_distribution) * 100
```

**Objectifs Phase 2.11a :**

| Métrique | Cible | Impact |
|----------|-------|--------|
| % avec date | ≥ 60% | Supersession possible |
| % high confidence | ≥ 40% | Récence fiable |

### 4.4 Coverage document_authority

```python
class AuthorityCoverageMetrics:
    """Métriques de couverture authority."""

    total_documents: int
    docs_with_authority: int

    by_level: Dict[str, int]  # {"contractual": N, "official": N, ...}

    @property
    def pct_known(self) -> float:
        return self.docs_with_authority / self.total_documents * 100
```

**Phase 2.11a : Collecte uniquement, pas d'exploitation.**

### 4.5 Taux de Conflits par Attribute/Subject

```python
class ConflictAnalysisMetrics:
    """Analyse détaillée des conflits."""

    # Par attribute_key
    conflicts_by_attribute: Counter  # {"sla.availability": 5, "threshold.ram": 2}

    # Par subject
    conflicts_by_subject: Counter  # {"c_s4hana": 3, "c_hana": 2}

    # Top 20 paires (subject, attribute) les plus conflictuelles
    top_conflict_pairs: List[tuple]  # [(subject, attribute, count)]
```

**Usage :** Identifier les zones de friction documentaire.

### 4.6 Dashboard Métriques (Format Log)

```python
def log_claim_metrics(metrics: dict):
    """Log structuré pour analyse."""
    logger.info(
        "[OSMOSE] Claim Extraction Metrics",
        extra={
            "event": "claim_extraction_complete",
            "metrics": {
                "distribution": {
                    "total": metrics["total"],
                    "validated": metrics["validated"],
                    "candidate": metrics["candidate"],
                    "conflicting": metrics["conflicting"],
                    "pct_validated": metrics["pct_validated"],
                    "pct_conflicting": metrics["pct_conflicting"],
                },
                "scope_quality": {
                    "pct_clean": metrics["scope_pct_clean"],
                    "unknown_keys_top5": metrics["unknown_keys"][:5],
                },
                "temporal": {
                    "pct_with_date": metrics["pct_with_date"],
                    "pct_high_confidence": metrics["pct_date_high_conf"],
                },
                "conflicts": {
                    "top_attributes": metrics["top_conflict_attributes"][:10],
                },
            },
        }
    )
```

---

## 5. Checklist Definition of Done

### 5.1 Extraction Claims

- [ ] **EXT-01** : LLM extrait `attribute_key` libre (pas d'enum)
- [ ] **EXT-02** : LLM extrait `scope_struct` en dict libre
- [ ] **EXT-03** : `value_type` et `unit` correctement parsés
- [ ] **EXT-04** : `evidence_text` toujours présent et ≤ 500 chars
- [ ] **EXT-05** : `flags` (negated, hedged, conditional) détectés
- [ ] **EXT-06** : `asserted_at` extrait avec `confidence` et `source`
- [ ] **EXT-07** : `document_authority` assigné (même si "unknown")

### 5.2 Scope Normalization

- [ ] **SCOPE-01** : Mapping synonymes clés appliqué
- [ ] **SCOPE-02** : Valeurs normalisées (casing, trim)
- [ ] **SCOPE-03** : `scope_key` généré de façon stable (hash)
- [ ] **SCOPE-04** : `raw_scope` conservé pour audit
- [ ] **SCOPE-05** : Métriques qualité scope loguées

### 5.3 Consolidation

- [ ] **CONS-01** : Groupement par `(subject, attribute_key, scope_key)`
- [ ] **CONS-02** : Calcul `maturity` : VALIDATED si multi-source concordant
- [ ] **CONS-03** : Calcul `maturity` : CONFLICTING si valeurs incompatibles
- [ ] **CONS-04** : `confidence_p50` calculé
- [ ] **CONS-05** : `conflicts_with` peuplé si CONFLICTING
- [ ] **CONS-06** : **PAS de supersession** (désactivé en 2.11a)

### 5.4 API Response

- [ ] **API-01** : Endpoint `/api/claims/search` implémenté
- [ ] **API-02** : Response Schema v1 respecté
- [ ] **API-03** : `result_type` correct (CLAIM_ANSWER, CLAIM_COMPARISON, NO_CLAIM)
- [ ] **API-04** : `rag_fallback` généré pour CANDIDATE et CONFLICTING
- [ ] **API-05** : `telemetry` inclus dans chaque réponse
- [ ] **API-06** : Latence totale < 500ms (P95)

### 5.5 Tracking

- [ ] **TRACK-01** : Métriques distribution maturité loguées
- [ ] **TRACK-02** : Métriques scope quality loguées
- [ ] **TRACK-03** : Métriques temporal coverage loguées
- [ ] **TRACK-04** : Top conflits loggés
- [ ] **TRACK-05** : Dashboard ou export CSV disponible

### 5.6 Tests

- [ ] **TEST-01** : Unit tests extraction (≥ 80% coverage)
- [ ] **TEST-02** : Unit tests consolidation
- [ ] **TEST-03** : Unit tests scope normalization
- [ ] **TEST-04** : Integration test pipeline complet
- [ ] **TEST-05** : Test avec 20 documents réels
- [ ] **TEST-06** : Test cas VALIDATED, CANDIDATE, CONFLICTING, NO_CLAIM

---

## 6. Tâches d'Implémentation (P0/P1/P2)

### 6.1 P0 — Bloquant (Semaine 1)

| ID | Tâche | Effort | Risque | Dépendances |
|----|-------|--------|--------|-------------|
| **P0-01** | Refactor `types.py` : `claim_type` → `attribute_key` | S | Bas | - |
| **P0-02** | Ajouter champs `asserted_at_*` et `document_authority` | S | Bas | P0-01 |
| **P0-03** | Ajouter `normalized_scope` + `raw_scope` dans CanonicalClaim | S | Bas | P0-01 |
| **P0-04** | Implémenter `normalize_scope()` avec mapping v1 | M | Moyen | - |
| **P0-05** | Refactor `llm_claim_extractor.py` : prompt agnostic | M | Moyen | P0-01 |
| **P0-06** | Créer `claim_consolidator.py` minimal | L | Moyen | P0-01, P0-04 |

**Effort** : S = 2h, M = 4h, L = 8h

### 6.2 P1 — Important (Semaine 2)

| ID | Tâche | Effort | Risque | Dépendances |
|----|-------|--------|--------|-------------|
| **P1-01** | Créer `raw_claim_writer.py` (Neo4j) | M | Bas | P0-01 |
| **P1-02** | Créer `canonical_claim_writer.py` (Neo4j) | M | Bas | P0-06 |
| **P1-03** | Endpoint `/api/claims/search` | L | Moyen | P1-01, P1-02 |
| **P1-04** | Response builder (VALIDATED/CANDIDATE/CONFLICTING/NO_CLAIM) | L | Moyen | P1-03 |
| **P1-05** | Intégration RAG fallback dans response | M | Bas | P1-04 |
| **P1-06** | Logging métriques structured | M | Bas | P0-06 |

### 6.3 P2 — Nice to Have (Semaine 3)

| ID | Tâche | Effort | Risque | Dépendances |
|----|-------|--------|--------|-------------|
| **P2-01** | Script test 20 documents | M | Bas | P1-* |
| **P2-02** | Export métriques CSV/JSON | S | Bas | P1-06 |
| **P2-03** | Enrichir mapping scope (based on data) | S | Bas | P2-01 |
| **P2-04** | Documentation API (OpenAPI) | M | Bas | P1-03 |
| **P2-05** | Dashboard métriques (optionnel) | L | Bas | P2-02 |

### 6.4 Diagramme de Dépendances

```
P0-01 (types.py refactor)
  ├── P0-02 (asserted_at)
  ├── P0-03 (normalized_scope)
  ├── P0-05 (prompt refactor)
  └── P0-06 (consolidator)
        └── P1-02 (canonical writer)
              └── P1-03 (API endpoint)
                    └── P1-04 (response builder)
                          └── P1-05 (RAG fallback)

P0-04 (normalize_scope)
  └── P0-06 (consolidator)

P1-01 (raw claim writer)
  └── P1-03 (API endpoint)

P1-06 (metrics logging)
  └── P2-02 (export)
        └── P2-05 (dashboard)
```

---

## 7. Risques et Mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Extraction scope trop bruitée | Moyen | Haut | Mapping v1 + itérations sur data |
| asserted_at rarement disponible | Moyen | Moyen | Accepter "unknown", différer supersession |
| Trop de CONFLICTING | Moyen | Haut | Analyser top conflits, affiner scope |
| Latence API > 500ms | Bas | Moyen | Cache Qdrant, optimiser consolidation |
| LLM hallucine des scopes | Moyen | Moyen | Prompt strict + evidence obligatoire |

---

## Annexes

### A. Schema Neo4j (Phase 2.11a)

```cypher
// Constraints
CREATE CONSTRAINT raw_claim_id IF NOT EXISTS
FOR (rc:RawClaim) REQUIRE rc.raw_claim_id IS UNIQUE;

CREATE CONSTRAINT canonical_claim_id IF NOT EXISTS
FOR (cc:CanonicalClaim) REQUIRE cc.canonical_claim_id IS UNIQUE;

// Indexes
CREATE INDEX claim_subject IF NOT EXISTS
FOR (cc:CanonicalClaim) ON (cc.subject_concept_id);

CREATE INDEX claim_attribute IF NOT EXISTS
FOR (cc:CanonicalClaim) ON (cc.attribute_key);

CREATE INDEX claim_scope_key IF NOT EXISTS
FOR (cc:CanonicalClaim) ON (cc.scope_key);

CREATE INDEX claim_maturity IF NOT EXISTS
FOR (cc:CanonicalClaim) ON (cc.maturity);
```

### B. Prompt Claim Extractor v1 (Agnostic)

Voir `llm_claim_extractor.py` pour le prompt complet.

Principes clés :
- `attribute_key` libre (snake_case)
- `scope_struct` libre (dict key/value)
- Evidence obligatoire
- Flags détectés
- Pas de claim_type enum

---

*Document créé le 2025-12-22*
*Validé par : [User] + Claude + ChatGPT*
