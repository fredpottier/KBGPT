# OSMOSE Phase 2.12 - Entity Resolution & Relation Discovery

## Spécification Architecture Cible

**Date**: 2025-12-25
**Phase**: 2.12 (après 2.11a Claims MVP)
**Status**: ✅ VALIDATED - Ready for v1 Production Implementation
**Contributeurs**: Claude Code, ChatGPT (analyse croisée)
**Reviews**:
- ChatGPT v1 : 5 corrections intégrées (blocking, co_occurrence, sous-types, auto-calibration, précision>recall)
- ChatGPT v2 : Validation finale + scope v1 Production défini (section 11)

---

## 1. Contexte et Problème Initial

### 1.1 Constat

Après import de documents dans OSMOSE, on observe dans Neo4j :
- Des concepts (CanonicalConcept) créés correctement
- Des relations (RawAssertion) entre concepts du **même document**
- **Beaucoup de concepts isolés** (degree=0) qui ne sont reliés à rien

### 1.2 Cause Racine

L'extraction de relations actuelle est **document-centric** :

```
Document → Extraction NER → Concepts du document
                                    ↓
                    Catalogue fermé (c1, c2, c3...)
                                    ↓
          LLM Relation Extractor (segment-level + doc-level)
                                    ↓
                    RawAssertions entre concepts
                    du MÊME document seulement
```

**Code concerné** :
- `osmose_integration.py:268-274` : Catalogue construit uniquement avec concepts du document courant
- `supervisor.py:769-770` : `identify_bucket3_concepts` utilise `state.promoted` (document courant)
- `llm_relation_extractor.py:219-222` : Prompt LLM avec "CATALOGUE FERMÉ"

### 1.3 Conséquence

Si un concept `GDPR` apparaît dans le document A et un concept `Data Protection Officer` dans le document B, **aucune relation ne sera créée entre eux**, même s'ils sont sémantiquement liés.

---

## 2. Principes Architecturaux (State of the Art)

### 2.1 Invariant Fondamental

> **On ne crée JAMAIS les relations cross-document pendant l'ingestion primaire.**

Raisons :
- Le contexte sémantique est **local** (document-level)
- Les relations canoniques sont **globales** (graph-level)
- Mélanger les deux crée du bruit et rend le pipeline non déterministe

### 2.2 Pattern Standard (Google KG, Microsoft Turing, Neo4j Research)

```
1. Document Ingestion (per-doc)
   - Concepts locaux
   - Relations locales (fort signal)

2. Entity Resolution (global)
   - Déduplication cross-doc
   - Fusion / Alias
   - Alignement sémantique

3. Relation Discovery (global, périodique)
   - Cross-document
   - Evidence-based
   - Traçable
```

### 2.3 Distinction Critique

| Phase 2 : Entity Resolution | Phase 3 : Relation Discovery |
|----------------------------|------------------------------|
| "Est-ce le **MÊME** concept ?" | "Ces concepts sont-ils **LIÉS** ?" |
| Fusion / Alias / Dédoublonnage | Création de liens sémantiques |
| Doit être fait **AVANT** Phase 3 | Nécessite un graphe "propre" |

**Si Phase 2 est fragile, Phase 3 devient un amplificateur de bruit.**

---

## 3. Phase 0 : Identity Schema (Fondation)

### 3.1 Problème

Sans définition de ce qui constitue "le même concept" par type, les seuils de merge sont arbitraires.

### 3.2 Solution : Types Génériques + Extension par Domaine

#### Niveau 1 : Types Universels (Built-in, Domain-Agnostic)

```yaml
ENTITY:
  description: "Chose nommée identifiable"
  identity_signals:
    - name_normalized (obligatoire)
    - type_match (obligatoire)
    - embedding_similarity (candidat)
  default_thresholds:
    auto: 0.98
    defer: 0.85

CONCEPT:
  description: "Notion abstraite, idée"
  identity_signals:
    - name_normalized
    - definition_similarity
    - usage_context_similarity
  default_thresholds:
    auto: 0.99  # Ultra-restrictif mais possible (voir AUTO_SAFE ci-dessous)
    defer: 0.80
  # AUTO autorisé UNIQUEMENT si toutes ces conditions sont vraies :
  auto_safe_conditions:
    - exact_normalized_match: true
    - definition_fingerprint_match: true  # Même hash de définition
    - stable_across_n_docs: 3  # Confirmé dans N+ documents

ROLE:
  description: "Fonction, responsabilité"
  identity_signals:
    - label_normalized
    - defining_context
  default_thresholds:
    auto: 0.95
    defer: 0.80

ORGANIZATION:
  description: "Entité organisationnelle"
  identity_signals:
    - name_normalized
    - location (si disponible)
    - org_type
  default_thresholds:
    auto: 0.95 (si location match)
    defer: 0.85

DOCUMENT:
  description: "Source documentaire"
  identity_signals:
    - title_normalized
    - identifier (si disponible)
    - date
  default_thresholds:
    auto: 0.98 (si identifier exact)
    defer: 0.85

STANDARD:
  description: "Norme, référentiel"
  identity_signals:
    - name_normalized
    - issuer
    - version
  default_thresholds:
    auto: 0.95 (si version match)
    defer: 0.85
```

#### Niveau 1b : Sous-Types Optionnels (Hiérarchie Légère)

Pour affiner le comportement sans casser le domain-agnostic :

```yaml
# Sous-types de ROLE (optionnels, détectés automatiquement ou via Domain Context)
ROLE/HUMAN:
  parent: ROLE
  description: "Rôle humain (DPO, CEO, Security Officer...)"
  identity_boost: "same org + same title = higher confidence"

ROLE/SYSTEM:
  parent: ROLE
  description: "Rôle applicatif (API Gateway, Message Broker...)"
  identity_boost: "same tech stack context"

ROLE/ORGANIZATIONAL:
  parent: ROLE
  description: "Fonction organisationnelle (Compliance Team, Legal Dept...)"
  identity_boost: "same org structure"

# Sous-types de ENTITY (optionnels)
ENTITY/NORMATIVE:
  parent: ENTITY
  description: "Entité définie par une norme (Article 5, Clause 3.2...)"
  identity_signals_extra:
    - parent_standard
    - section_number
  auto_threshold: 0.90  # Plus permissif car structuré

ENTITY/TECHNICAL:
  parent: ENTITY
  description: "Entité technique (Protocol, Algorithm, System...)"
  identity_boost: "version + vendor match"

# Détection automatique du sous-type
subtype_detection:
  method: "pattern matching + LLM classification (cached)"
  fallback: "use parent type policy"
  confidence_required: 0.80  # Sinon, utiliser type parent
```

#### Niveau 2 : Signaux d'Identité Génériques

```yaml
LEXICAL_SIGNALS:
  exact_match:
    weight: 1.0
    description: "Noms identiques après normalisation"

  acronym_expansion:
    weight: 0.9
    description: "Acronyme ↔ forme longue"
    example: "GDPR" ↔ "General Data Protection Regulation"

  alias_overlap:
    weight: 0.85
    description: "Surface forms partagées"

SEMANTIC_SIGNALS:
  embedding_similarity:
    weight: configurable
    threshold: 0.85
    description: "Proximité vectorielle (Qdrant)"

  context_similarity:
    weight: 0.7
    description: "Contextes d'usage similaires"

STRUCTURAL_SIGNALS:
  same_document:
    weight: 0.3
    description: "Boost si apparus dans le même doc"

  # ⚠️ co_occurrence RETIRÉ de Phase 2
  # Raison: C'est un signal de RELATION, pas d'IDENTITY
  # Un concept peut co-apparaître fréquemment avec un autre sans être le même
  # Exemple: "GDPR" et "DPO" co-apparaissent souvent mais ne sont pas identiques
  # → Réservé à Phase 3 (Relation Discovery) uniquement
```

#### Niveau 3 : Domain Context (Extension Optionnelle)

Le Domain Context existant dans OSMOSE peut enrichir avec des types spécialisés :

```yaml
# Exemple: chargé dynamiquement pour domaine "privacy_regulation"
domain: privacy_regulation

extends_types:
  REGULATION:
    parent_type: DOCUMENT
    additional_signals:
      - jurisdiction
      - year
      - official_reference
    identity_rule: "jurisdiction + acronym + year"

  ARTICLE:
    parent_type: ENTITY
    additional_signals:
      - number
      - parent_document
    identity_rule: "number + parent_document"
```

---

## 4. Modèle de Décision : AUTO / DEFER / REJECT

### 4.1 Principe Fondamental

> **Aucune dette opérationnelle humaine**

Le système doit être autonome. L'intervention humaine est exceptionnelle et budgetée, pas un workflow permanent.

### 4.2 Les Trois États

```
AUTO    → Action immédiate (haute précision garantie)
          Merge ou création de lien effectué automatiquement

DEFER   → Pas assez de signal maintenant
          Réévaluation automatique future quand plus de données
          PAS une queue humaine

REJECT  → Confiance trop faible
          On ignore cette paire
```

### 4.3 Différence avec NEEDS_REVIEW

| Ancien modèle (NEEDS_REVIEW) | Nouveau modèle (DEFER) |
|------------------------------|------------------------|
| File d'attente humaine | État temporaire système |
| Croissance infinie | Borné (expire après N jours) |
| Humain = valideur permanent | Humain = oracle ponctuel |
| Bloquant | Non-bloquant |

### 4.4 L'Humain comme Oracle Ponctuel

```yaml
Human Review:
  role: "Source de labels pour calibration des seuils"
  frequency: "Exceptionnelle, budgetée"
  cap: "~20 décisions / semaine / tenant maximum"

  selection_strategy:
    - Cas les plus fréquents en DEFER (impact fort)
    - Cas ambigus mais récurrents
    - Cas qui débloquent un cluster entier

  purpose: "Ajuster seuils/règles, PAS vider une inbox"

  optional: true  # Système doit fonctionner sans
```

### 4.5 Auto-Calibration Sans Labels Humains

```yaml
Signaux d'apprentissage autonome:

  cohérence_graphe:
    description: "Un merge qui augmente les contradictions est pénalisé"
    signal: "Nombre d'incohérences post-merge"

  stabilité_temporelle:
    description: "Alias confirmé sur N documents = confiance monte"
    signal: "Nombre de docs où la paire co-apparaît"

  evidence_accumulation:
    description: "Plus de preuves textuelles = plus de confiance"
    signal: "Nombre de chunks avec co-présence"

  pattern_consistency:
    description: "Merge cohérent avec patterns existants"
    signal: "Similarité avec merges déjà validés (AUTO)"
```

### 4.6 Cadre AutoCalibration (Formalisé)

Comment les signaux ajustent concrètement les seuils :

```yaml
AutoCalibration:
  # Fréquence d'exécution
  cadence: "weekly"  # Batch job hebdomadaire
  scope: "per_type"  # Calibration séparée par type de concept

  # Métriques de feedback utilisées
  feedback_signals:
    merge_stability:
      description: "% de merges AUTO qui restent stables (non-annulés)"
      healthy_threshold: "> 98%"
      action_if_below: "augmenter threshold_auto de 0.01"

    defer_resolution_rate:
      description: "% de DEFER qui deviennent AUTO (vs EXPIRED)"
      healthy_threshold: "> 40%"
      action_if_below: "baisser threshold_defer de 0.01"

    graph_coherence:
      description: "Contradictions créées par les merges récents"
      measurement: "Claims CONFLICTING post-merge"
      action_if_high: "augmenter threshold_auto de 0.02"

  # Ajustements automatiques
  adjustments:
    threshold_auto:
      direction: "+/- 0.01 per cycle"
      bounds: [0.90, 1.0]  # Jamais en dessous de 0.90
      constraint: "never lower if precision < target"

    threshold_defer:
      direction: "+/- 0.01 per cycle"
      bounds: [0.70, 0.95]  # Ni trop permissif ni trop restrictif

  # Garde-fous (hard limits)
  guardrails:
    precision_floor: 0.95  # Jamais sacrifier la précision
    max_adjustment_per_cycle: 0.02  # Pas de changement brutal
    require_n_samples: 100  # Minimum de décisions pour ajuster
    rollback_if_degradation: true  # Annuler si métriques se dégradent

  # Logging et audit
  audit:
    log_every_adjustment: true
    store_threshold_history: true
    alert_on_unusual_drift: true
```

**Exemple concret** :
```
Cycle 1 (Semaine 1):
- ENTITY threshold_auto = 0.98
- 150 merges AUTO, 148 stables (98.7%) ✓
- Pas d'ajustement

Cycle 2 (Semaine 2):
- 200 merges AUTO, 190 stables (95%) ⚠️
- 10 merges ont créé des contradictions
- Action: threshold_auto → 0.99

Cycle 3 (Semaine 3):
- 180 merges AUTO, 178 stables (98.9%) ✓
- Stabilisé à nouveau
```

---

## 5. Phase 2 : Entity Resolution Cross-Document

### 5.1 Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│                    ENTITY RESOLUTION PIPELINE                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐                                            │
│  │ CandidateFinder  │                                            │
│  │                  │  1. Qdrant top-K PAR TYPE                  │
│  │                  │     (entity↔entity, standard↔standard)     │
│  │                  │  2. Lexical (acronyme/expansion)           │
│  │                  │  3. Surface form overlap                   │
│  └────────┬─────────┘                                            │
│           │ Paires candidates                                    │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │PairSimilarityScorer│  Cross-encoder pairwise                  │
│  │                  │  + Signaux lexicaux                        │
│  │                  │  + Signaux structurels                     │
│  │                  │  Output: score + breakdown par signal      │
│  └────────┬─────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────────────────────────────────────┐            │
│  │           IDENTITY DECISION ROUTER                │            │
│  │                                                   │            │
│  │  Charger policy pour type(A) et type(B)           │            │
│  │                                                   │            │
│  │  IF score > threshold_auto AND explicit_evidence: │            │
│  │     → AUTO (merge maintenant)                     │            │
│  │                                                   │            │
│  │  ELIF score > threshold_defer:                    │            │
│  │     → DEFER (stocker pour réévaluation)           │            │
│  │                                                   │            │
│  │  ELSE:                                            │            │
│  │     → REJECT                                      │            │
│  └──────────────────────────────────────────────────┘            │
│           │                    │                                 │
│           ▼                    ▼                                 │
│  ┌─────────────┐      ┌─────────────────┐                        │
│  │IdentityResolver│   │  DeferredStore  │                        │
│  │             │      │                 │                        │
│  │ • Alias →   │      │ • pair_id       │                        │
│  │   surface_  │      │ • score         │                        │
│  │   forms     │      │ • signals       │                        │
│  │ • Relations │      │ • created_at    │                        │
│  │   migrées   │      │ • doc_count     │                        │
│  │ • Provenance│      │ • expires_at    │                        │
│  └─────────────┘      └─────────────────┘                        │
│                                │                                 │
│                                ▼                                 │
│                    ┌─────────────────────┐                       │
│                    │ DeferredReevaluator │                       │
│                    │    (batch job)      │                       │
│                    │                     │                       │
│                    │ Périodiquement:     │                       │
│                    │ 1. Récupérer DEFER  │                       │
│                    │ 2. Recalculer score │                       │
│                    │ 3. Promouvoir→AUTO  │                       │
│                    │    ou Expirer→REJECT│                       │
│                    └─────────────────────┘                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 Blocking Strategy (Éviter O(N²))

> **Point critique** : Sans blocking intelligent, Phase 2 devient O(N²) déguisé. Même avec Qdrant top-K, on risque de scorer trop de paires et le coût cross-encoder explose.

Le blocking **réduit l'espace de décision** AVANT le scoring coûteux.

```yaml
Blocking Strategies:

  # Niveau 1 : Filtre lexical rapide (O(1) lookup)
  lexical_block:
    same_first_token:
      description: "Même premier mot après normalisation"
      example: "Data Protection" ↔ "Data Controller"
      cost: "très faible"

    acronym_family:
      description: "Acronyme et ses expansions connues"
      example: "GDPR" dans même block que "General Data Protection Regulation"
      implementation: "Lookup table acronymes → expansions"

    normalized_prefix:
      description: "Même préfixe normalisé (3+ chars)"
      example: "Ransomware" ↔ "Ransomware Attack"

  # Niveau 2 : Filtre structurel (graph-based)
  structural_block:
    same_document_family:
      description: "Concepts d'une même famille documentaire"
      example: "Concepts de GDPR Chapter 1, 2, 3..."
      signal: "Forte probabilité de relation si même source"

    same_domain_context:
      description: "Concepts du même Domain Context"
      example: "privacy_regulation" concepts ensemble
      implementation: "Tag domain_context sur CanonicalConcept"

  # Niveau 3 : Filtre sémantique cheap (embedding)
  semantic_block:
    embedding_threshold:
      description: "Seuil bas pour candidats Qdrant"
      threshold: 0.75  # Cheap filter, pas le scoring final
      purpose: "Éliminer paires clairement non-liées"
      note: "Ce n'est PAS le seuil de merge, juste un pré-filtre"

  # Ordre d'application (pipeline)
  blocking_pipeline:
    1. lexical_block      # Le plus rapide
    2. structural_block   # Graph lookup
    3. semantic_block     # Qdrant top-K avec threshold 0.75

  # Métriques blocking
  blocking_metrics:
    reduction_target: "> 95%"  # Réduire 95% des paires avant scoring
    false_negative_tolerance: "< 1%"  # Accepter de rater 1% pour performance
```

**Exemple chiffré** :
- 10,000 concepts → 50M paires possibles (O(N²))
- Après blocking : ~50,000 paires candidates (0.1%)
- Cross-encoder sur 50K = viable
- Cross-encoder sur 50M = impossible

### 5.3 Contraintes Dures (Non Négociables)

```yaml
Entity Resolution Constraints:

  no_embedding_only_merge:
    description: "Pas de merge basé SEULEMENT sur embedding + cross-encoder"
    minimum_required: "surface_form match OU acronym_expansion OU definition_match"

  no_transitive_auto_merge:
    description: "Si A~B et B~C, ne pas déduire A=C automatiquement"
    rule: "Chaque paire évaluée indépendamment"

  type_compatibility:
    description: "Ne jamais comparer types incompatibles"
    rule: "ENTITY↔ENTITY, CONCEPT↔CONCEPT, pas ROLE↔DOCUMENT"

  provenance_mandatory:
    description: "Tout merge doit être traçable"
    stored: ["merged_from", "merge_reason", "merge_method", "merge_timestamp"]
```

### 5.3 Structure de Données : DeferredMergeCandidate

```python
class DeferredMergeCandidate:
    pair_id: str                    # Hash unique de la paire
    concept_a_id: str
    concept_b_id: str
    concept_type: str               # Type commun

    # Scores
    similarity_score: float         # Cross-encoder
    signal_breakdown: Dict[str, float]  # Score par signal

    # Métadonnées
    created_at: datetime
    last_evaluated_at: datetime
    evaluation_count: int           # Nombre de réévaluations

    # Signaux accumulés
    doc_count_a: int                # Docs où A apparaît
    doc_count_b: int                # Docs où B apparaît
    shared_surface_forms: int       # Surface forms partagées (alias communs)

    # Expiration
    expires_at: datetime            # Auto-REJECT après cette date

    # Status
    status: Literal["DEFER", "AUTO", "REJECT", "EXPIRED"]
```

---

## 6. Phase 3 : Relation Discovery Cross-Document

### 6.1 Prérequis

Phase 3 ne s'exécute que sur un graphe "propre" (post Phase 2).

### 6.2 Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│                 RELATION DISCOVERY PIPELINE                      │
│            (Post Phase 2 - graphe "propre")                      │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐                                            │
│  │ CandidateGenerator│                                           │
│  │                  │  1. Concepts isolés (degree < N)           │
│  │                  │  2. Embedding proximity (Qdrant top-K)     │
│  │                  │  3. Type compatibility matrix              │
│  └────────┬─────────┘                                            │
│           │ Paires (concept_A, concept_B)                        │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │EvidenceRetriever │  OBLIGATOIRE - pas de lien sans preuve     │
│  │                  │                                            │
│  │  Types d'evidence (par force):                                │
│  │  1. CO_PRESENCE (score 1.0)                                   │
│  │     → A et B dans le même chunk                               │
│  │                                                               │
│  │  2. NORMATIVE_REFERENCE (score 0.95)                          │
│  │     → A cite explicitement B                                  │
│  │     → Patterns: "defined in", "pursuant to", "under"          │
│  │                                                               │
│  │  3. PATH_EVIDENCE (score 0.80)                                │
│  │     → A...X...B dans le même doc (chaîne ≤3 hops)             │
│  │                                                               │
│  │  4. CROSS_DOC_PATH (score 0.70)                               │
│  │     → Doc A: A→X, Doc B: X→B                                  │
│  │     → Nécessite validation LLM stricte                        │
│  │                                                               │
│  │  5. EMBEDDING_ONLY (score 0.0)                                │
│  │     → Similarité sans preuve textuelle                        │
│  │     → SKIP (pas de relation créée)                            │
│  │                                                               │
│  │  Si aucune evidence ≥ 0.70 → SKIP cette paire                 │
│  └────────┬─────────┘                                            │
│           │ Paires + evidence_objects                            │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │  LLMValidator    │  Rôle: VALIDATOR + LABELER                 │
│  │                  │  PAS générateur de relations               │
│  │                  │                                            │
│  │  Prompt strict:                                               │
│  │  "Voici 2 concepts et des extraits où ils apparaissent.       │
│  │   Existe-t-il une relation factuelle entre eux ?              │
│  │   Si oui, quel type parmi: [SET FERMÉ]                        │
│  │   Si non, réponds 'NO_RELATION'"                              │
│  │                                                               │
│  │  Set fermé initial (Core):                                    │
│  │  REQUIRES, ENABLES, PART_OF, APPLIES_TO, DEFINES              │
│  │                                                               │
│  │  Set étendu (exploration/annotation):                         │
│  │  + DEPENDS_ON, PREVENTS, CAUSES, SUPERSEDES, RELATED_TO       │
│  └────────┬─────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                            │
│  │  RelationWriter  │                                            │
│  │                  │  RawAssertion avec:                        │
│  │                  │  • origin = "discovery"                    │
│  │                  │  • evidence_type = "CO_PRESENCE|PATH|..."  │
│  │                  │  • evidence_chunk_ids = [...]              │
│  │                  │  • evidence_doc_ids = [...]                │
│  │                  │  • maturity = CANDIDATE                    │
│  │                  │  • confidence = LLM score                  │
│  │                  │  • validation_method = "llm_gpt4o"         │
│  └──────────────────┘                                            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 6.3 Contraintes Dures (Non Négociables)

```yaml
Relation Discovery Constraints:

  evidence_mandatory:
    description: "Pas de relation cross-doc sans evidence"
    minimum_evidence_score: 0.70

  llm_is_validator:
    description: "LLM valide et labellise, ne génère pas"
    rule: "Evidence d'abord, LLM ensuite"

  closed_relation_set:
    description: "Types de relations contrôlés"
    core_set: [REQUIRES, ENABLES, PART_OF, APPLIES_TO, DEFINES]
    extended_set: [DEPENDS_ON, PREVENTS, CAUSES, SUPERSEDES, RELATED_TO]
    rule: "Core en production, Extended en exploration"

  related_to_cap:
    description: "Limiter les relations génériques"
    rule: "RELATED_TO < 20% des relations créées"
```

### 6.4 Choix Architectural : Précision > Recall

> **Choix assumé** : On privilégie la **précision** à la **complétude**.

```yaml
Precision_over_Recall:
  statement: |
    Le seuil evidence ≥ 0.70 peut sous-connecter le graphe sur certains domaines.
    Certaines relations réelles mais structurelles (non explicites dans le texte)
    ne seront pas découvertes.

  rationale:
    - Faux positifs = bruit difficile à nettoyer
    - Faux négatifs = relations manquantes, détectables plus tard
    - Un graphe précis est exploitable, un graphe bruité ne l'est pas
    - L'utilisateur peut toujours suggérer des relations manuellement

  trade_off:
    precision_target: "> 90%"
    recall_accepted: "60-70%"  # Acceptable pour un système autonome

  mitigations:
    - Relations structurelles légères (MENTIONED_IN, CO_OCCURS_IN_DOC) créées automatiquement
    - UI permet suggestion de relations par l'utilisateur (oracle ponctuel)
    - Phase 3 peut être re-exécutée quand nouveaux documents arrivent
    - Ajuster threshold_evidence à la baisse si domaine bien connu
```

Ce choix est **explicite et assumé**, pas un bug ou une limitation.

### 6.5 Structure Evidence Object

```python
class EvidenceObject:
    evidence_type: Literal[
        "CO_PRESENCE",
        "NORMATIVE_REFERENCE",
        "PATH_EVIDENCE",
        "CROSS_DOC_PATH"
    ]

    strength_score: float           # 0.70 - 1.0

    # Sources
    chunk_ids: List[str]
    doc_ids: List[str]

    # Contenu
    snippets: List[str]             # Extraits textuels
    path_description: Optional[str]  # Pour PATH_EVIDENCE

    # Méthode
    retrieval_method: str           # "qdrant_search", "graph_traversal", etc.
```

---

## 7. Outils et Librairies

### 7.1 Verdict par Outil

| Outil | Verdict | Usage | Timing |
|-------|---------|-------|--------|
| **Qdrant** | ✅ Déjà en place | Candidate generation (top-K) | Maintenant |
| **Cross-encoder** | ✅ À ajouter | PairSimilarityScorer | Phase 2 |
| **Neo4j GDS** | ⏳ Plus tard | Node Similarity, Link Prediction | Quand graphe densifié |
| **Splink/Dedupe** | 🤔 Optionnel | Entity Resolution structurée | Si on "records-ifie" les concepts |

### 7.2 Neo4j GDS : Quand et Comment

```yaml
Neo4j GDS:
  prerequisite: "Graphe suffisamment connecté"

  early_use_possible:
    - Relations structurelles simples: MENTIONED_IN, CO_OCCURS_IN_DOC
    - Permet d'avoir un voisinage exploitable sans inventer des relations sémantiques

  later_use:
    - Node Similarity (Jaccard/Overlap sur voisinages)
    - Link Prediction pipelines (si exemples gold disponibles)

  not_a_silver_bullet:
    - Ne "comprend" pas le texte
    - Fournit candidats et scoring structurel
    - La vérité reste: evidence in text + provenance
```

---

## 8. Critères d'Acceptation

### 8.1 Propriété Fondamentale

> **Aucune dette opérationnelle humaine**

### 8.2 Métriques

```yaml
Metrics:

  defer_queue_bounded:
    description: "Taille file DEFER ne croît pas indéfiniment"
    rule: "Expire après 30 jours OU 100 nouveaux docs sans changement"
    target: "< 1000 paires DEFER par tenant"

  auto_rate:
    description: "Taux de décisions automatiques"
    target: "> 70%"

  defer_auto_resolution:
    description: "Taux de DEFER résolus automatiquement (→AUTO ou →EXPIRED)"
    target: "> 90%"

  human_intervention:
    description: "Volume d'intervention humaine"
    target: "< 20/semaine (optionnel, système fonctionne sans)"

  system_autonomous:
    description: "Système utile sans AUCUNE review humaine"
    target: "OUI"
```

### 8.3 Qualité

```yaml
Quality Metrics:

  merge_precision:
    description: "Précision des AUTO merges"
    measurement: "Échantillonnage + validation manuelle périodique"
    target: "> 95%"

  relation_precision:
    description: "Précision des relations découvertes"
    measurement: "Échantillonnage + validation manuelle périodique"
    target: "> 90%"

  evidence_coverage:
    description: "% de relations avec evidence textuelle"
    target: "100% (contrainte dure)"
```

---

## 9. Résumé Exécutif

### Ce qui existe déjà dans OSMOSE

- ✅ Extraction NER (concepts)
- ✅ Relations intra-document (RawAssertion)
- ✅ Normalisation pour dédup intra-doc (`normalize_canonical_key`)
- ✅ Domain Context (extensibilité par domaine)
- ✅ Maturity system (CANDIDATE, VALIDATED, CONFLICTING)
- ✅ Qdrant pour embeddings

### Ce qui manque

- ❌ Entity Resolution cross-document (Phase 2)
- ❌ Relation Discovery cross-document (Phase 3)
- ❌ Identity Policy par type
- ❌ Modèle AUTO/DEFER/REJECT
- ❌ Cross-encoder pour scoring pairwise
- ❌ DeferredReevaluator (batch job)

### Ordre d'implémentation recommandé

1. **Phase 0** : Définir Identity Schema par type générique
2. **Phase 2** : Entity Resolution (CandidateFinder → Scorer → Router → Resolver)
3. **Phase 3** : Relation Discovery (post Phase 2 uniquement)

### Principes Non Négociables

1. **Domain-agnostic** : Types génériques, Domain Context pour extension
2. **Evidence-first** : Pas de merge/relation sans preuve explicable
3. **Autonome** : DEFER ≠ queue humaine, auto-calibration
4. **Traçable** : Provenance sur tout (merge_reason, evidence, origin)
5. **Borné** : Aucune file d'attente infinie

---

## 10. Questions Ouvertes pour Review

### Résolues par Review ChatGPT v1

1. ~~Blocking strategy manquante~~ → ✅ Section 5.2 ajoutée
2. ~~co_occurrence = signal d'identité~~ → ✅ Retiré de Phase 2, réservé Phase 3
3. ~~Policy par type trop plate~~ → ✅ Sous-types optionnels ajoutés (Niveau 1b)
4. ~~Auto-calibration conceptuelle~~ → ✅ Section 4.6 formalisée avec cadence/garde-fous
5. ~~Précision vs Recall implicite~~ → ✅ Section 6.4 explicite le choix assumé

### Questions restantes

1. Les types génériques + sous-types optionnels sont-ils suffisants comme base ?
   → **Réponse probable** : Oui, valider en implémentation

2. Les seuils par défaut (auto=0.98, defer=0.85) sont-ils raisonnables ?
   → **Réponse** : Oui, avec auto-calibration qui ajustera

3. Faut-il un mécanisme de "promotion" des relations Extended → Core ?
   → **À décider** après observation en production

4. Quelle granularité pour le blocking ? (per-type, per-domain, global)
   → **Suggestion** : per-type avec override par Domain Context

---

## 11. Scope v1 Production

> **Objectif** : Solution déployable en production, pas un MVP minimal.

### 11.1 Obligatoire v1

| Composant | Description | Criticité |
|-----------|-------------|-----------|
| **Identity Schema** | 6 types génériques avec seuils par type | Fondation |
| **Blocking Pipeline** | Lexical (acronym, prefix) + Semantic (embedding > 0.75) | Performance O(N²) → O(N) |
| **PairSimilarityScorer** | Cross-encoder + signaux lexicaux (exact_match, acronym_expansion) | Qualité scoring |
| **Cache Scores Redis** | Cache des scores pairwise pour éviter re-calcul | Coût opérationnel |
| **Decision Router** | AUTO/DEFER/REJECT avec seuils fixes par type | Architecture décision |
| **DeferredStore** | Stockage DEFER (Neo4j ou Redis) avec TTL 30 jours | Gestion temporalité |
| **DeferredReevaluator** | Batch job quotidien minimum | **CRITIQUE** - Évite accumulation infinie |
| **Métriques** | Logs structurés + endpoint `/api/entity-resolution/stats` | Monitoring production |
| **Provenance** | Traçabilité complète (merge_reason, evidence, timestamps) | Auditabilité |

### 11.2 Différé (avec justification)

| Composant | Justification du report | Condition d'activation |
|-----------|------------------------|------------------------|
| **Sous-types optionnels** | Nécessite observation des patterns réels en production. Les types génériques fonctionnent, les sous-types optimisent. | Après 2-4 semaines de data, quand patterns identifiés |
| **Blocking structural** | Optimisation. Lexical + semantic réduisent déjà >90% des paires. | Quand "familles documentaires" identifiées |
| **Auto-calibration** | Impossible sans historique. Seuils fixes bien choisis en v1. | Après 4-6 semaines de décisions loguées |
| **Dashboard graphique** | Logs structurés + API stats suffisent pour monitoring initial. | Quand besoin de visualisation avancée |

### 11.3 Seuils v1 (fixes, par type)

```yaml
# Seuils initiaux conservateurs (ajustables manuellement après observation)
ENTITY:
  threshold_auto: 0.98
  threshold_defer: 0.85

CONCEPT:
  threshold_auto: 0.99  # Ultra-restrictif
  threshold_defer: 0.80

ROLE:
  threshold_auto: 0.95
  threshold_defer: 0.80

ORGANIZATION:
  threshold_auto: 0.95
  threshold_defer: 0.85

DOCUMENT:
  threshold_auto: 0.98
  threshold_defer: 0.85

STANDARD:
  threshold_auto: 0.95
  threshold_defer: 0.85
```

### 11.4 Ordre d'implémentation recommandé

```
1. Infrastructure
   ├── DeferredStore (Redis ou Neo4j node type)
   ├── Cache scores Redis
   └── Endpoint /api/entity-resolution/stats

2. Core Pipeline
   ├── CandidateFinder (blocking lexical + semantic)
   ├── PairSimilarityScorer (cross-encoder + signaux)
   └── IdentityDecisionRouter (AUTO/DEFER/REJECT)

3. Resolution
   ├── IdentityResolver (merge avec provenance)
   └── DeferredReevaluator (batch job)

4. Intégration
   ├── Hook post-ingestion (déclencher Entity Resolution)
   └── Logs structurés + métriques
```

---

*Document finalisé après review croisée Claude Code / ChatGPT v2*
*Validé pour implémentation Phase 2.12 - v1 Production*
