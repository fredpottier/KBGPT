# OSMOSE ADR Consolidated - Decisions Architecturales

**Date**: 2026-01-29
**Version**: 2.0
**Objectif**: Document consolidé des ADRs OSMOSE pour partage ChatGPT

Ce document résume toutes les décisions architecturales (ADRs) du projet OSMOSE,
organisées par thème. Chaque section contient les points essentiels à retenir.

---

## Table des Matières

1. [Architecture Structurelle](#1-architecture-structurelle)
   - 1.1 Option C - Structural Graph from DoclingDocument
   - 1.2 Coverage is a Property, Not a Node Type
   - 1.3 ~~Dual Chunking Architecture~~ *(ARCHIVÉ — superseded par 1.1 + 1.2)*

2. [Promotion et Normalisation](#2-promotion-et-normalisation)
   - 2.1 Unified Corpus Promotion (Pass 2.0)
   - 2.2 Corpus-Aware Lex-Key Normalization
   - 2.3 Structural Context Alignment

3. [Linguistic Layer](#3-linguistic-layer)
   - 3.1 Coref Named↔Named Validation

4. [Relations et Evidence](#4-relations-et-evidence)
   - 4.1 Multi-Span Evidence Bundles

5. [Schema Neo4j Consolidé](#5-schema-neo4j-consolide)

6. [Modèle de Lecture Stratifiée (v2)](#6-modèle-de-lecture-stratifiée-v2)
   - 6.1 Principe : Lire comme un humain
   - 6.2 Stratification de l'Information

7. [North Star - Vérité Documentaire Contextualisée](#7-north-star---vérité-documentaire-contextualisée)
   - 7.1 Positionnement épistémique
   - 7.2 ClaimKey et Compare/Challenge

8. [Séparation Scope vs Assertion](#8-séparation-scope-vs-assertion)
   - 8.1 Scope Layer vs Assertion Layer
   - 8.2 Invariants de séparation

---

## 1. Architecture Structurelle

### 1.1 Option C - Structural Graph from DoclingDocument

**Status**: Ready for Implementation | **Date**: 2026-01-10

#### Problème
Les chunks "fat" (400-800 tokens) détruisent la structure documentaire et empêchent:
- La localisation précise des concepts
- Les relations visuelles (diagrams)
- La traçabilité page/paragraphe

#### Solution
Construire un **Structural Graph** à partir du DoclingDocument AVANT le chunking:

```
DoclingDocument
      │
      ▼
┌─────────────────┐
│ STRUCTURAL GRAPH │
│ (Neo4j Layer 0) │
├─────────────────┤
│ PageContext     │ ← Représente une page physique
│ SectionContext  │ ← Section hiérarchique (heading)
│ DocItem         │ ← Élément atomique (paragraphe, figure, table row)
└─────────────────┘
      │
      ▼
┌─────────────────┐
│ TypeAwareChunk  │ ← Projection pour retrieval (type-specific)
└─────────────────┘
```

#### Relations

| Relation | Source → Target | Description |
|----------|-----------------|-------------|
| `ON_PAGE` | DocItem → PageContext | Localisation page |
| `CONTAINS` | SectionContext → DocItem | Hiérarchie |
| `DERIVED_FROM` | TypeAwareChunk → DocItem[] | Traçabilité |
| `ANCHORED_IN` | ProtoConcept → DocItem | Preuve position |

#### Types de DocItem

```python
class DocItemType(Enum):
    NARRATIVE_TEXT = "NARRATIVE_TEXT"     # Texte paragraphe
    TABLE_TEXT = "TABLE_TEXT"             # Contenu table
    FIGURE_TEXT = "FIGURE_TEXT"           # Caption/légende
    LIST_ITEM = "LIST_ITEM"               # Élément liste
    HEADING = "HEADING"                   # Titre section
```

#### Chunking Type-Aware

```python
CHUNKING_CONFIG = {
    DocItemType.NARRATIVE_TEXT: ChunkConfig(target=512, overlap=50),
    DocItemType.TABLE_TEXT: ChunkConfig(preserve_row=True, max=2048),
    DocItemType.FIGURE_TEXT: ChunkConfig(single_chunk=True),
}
```

---

### 1.2 Coverage is a Property, Not a Node Type

**Status**: Accepted | **Date**: 2026-01-16

#### Principe Fondamental

> **Coverage est un invariant produit, pas un type de nœud.**

L'invariant à garantir:
> *Tout anchor SPAN doit pouvoir pointer vers une unité persistée qui couvre sa position.*

#### Décision

| Action | Cible |
|--------|-------|
| **SUPPRIMER** | CoverageChunk, DocumentChunk (node types) |
| **CONSERVER** | Invariant coverage (preuve localisable) |
| **IMPLÉMENTER** | Via DocItem (granularité fine, charspan natif) |

#### Architecture Finale

```
AVANT (Dual Chunking - OBSOLÈTE)
────────────────────────────────
ProtoConcept ──ANCHORED_IN──> DocumentChunk (coverage)

APRÈS (Option C - ACTUEL)
─────────────────────────
ProtoConcept ──ANCHORED_IN──> DocItem
                              └── charspan_start, charspan_end
                              └── section_id (UUID → SectionContext)
```

#### Règle Contractuelle

> **ANCHORED_IN pointe uniquement vers DocItem, jamais vers des chunks retrieval.**

| Unité | Rôle |
|-------|------|
| **DocItem** | Proof surface (cible ANCHORED_IN) |
| **TypeAwareChunk** | Retrieval projection (recherche, RAG) |

#### KPIs de Remplacement

| Métrique | Formule | Cible |
|----------|---------|-------|
| **Anchor Bind Rate (ABR)** | Protos SPAN avec ANCHORED_IN / Total SPAN | 100% |
| **Orphan Ratio (OR)** | Protos sans ANCHORED_IN / Total | 0% |
| **Section Alignment Rate (SAR)** | Protos avec section_id valide / Total | 100% |

---

### 1.3 ~~Dual Chunking Architecture~~ *(ARCHIVÉ)*

> ⚠️ **ARCHIVÉ** — Superseded par [ADR_COVERAGE_PROPERTY_NOT_NODE](ADR_COVERAGE_PROPERTY_NOT_NODE.md) (§1.2) + [ADR_STRUCTURAL_GRAPH_FROM_DOCLING](ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md) (§1.1).
> Les types CoverageChunk/DocumentChunk ont été remplacés par DocItem + TypeAwareChunk (Option C).
> Le **principe** dual (coverage vs retrieval) persiste dans l'architecture actuelle, seuls les node types ont changé.
> ADR source archivé dans `doc/archive/adr/ADR_DUAL_CHUNKING_ARCHITECTURE.md`.

**Status**: ~~Accepted~~ → **Superseded** | **Date**: 2026-01-10

---

## 2. Promotion et Normalisation

### 2.1 Unified Corpus Promotion (Pass 2.0)

**Status**: Accepted | **Date**: 2026-01-09

#### Problème

L'ancien système promouvait en 2 étapes (Pass 2 document + Pass 4 corpus),
causant des promotions prématurées et des doublons cross-doc.

#### Solution: Single-Stage Promotion

```
Pass 1: Extraction ProtoConcepts (PAS de promotion)
        └── Stocke anchor_status, confidence, etc.

Pass 2.0: Unified Corpus Promotion
          └── Vue corpus complète AVANT toute promotion
          └── Groupement par lex_key cross-doc
          └── Création CanonicalConcept + INSTANCE_OF
```

#### Signal Minimal pour Cross-Doc

Un ProtoConcept peut être promu cross-doc si au moins UN:
- `anchor_status = SPAN` (position exacte)
- `role ∈ {definition, constraint}` (rôle sémantique fort)
- `confidence ≥ 0.7` (confiance suffisante)

#### Règles High-Signal V2

```python
def is_high_signal_v2(proto) -> bool:
    # R1: Position exacte = signal fort
    if proto.anchor_status == "SPAN":
        return True

    # R2: Rôle sémantique fort
    if proto.role in {"definition", "constraint"}:
        return True

    # R3: Confiance + rôle significatif
    if proto.confidence >= 0.7 and proto.role in {"comparison", "architecture"}:
        return True

    # R4: Métriques position si disponibles
    if proto.template_likelihood and proto.template_likelihood < 0.3:
        if proto.positional_stability and proto.positional_stability >= 0.7:
            return True

    return False
```

---

### 2.2 Corpus-Aware Lex-Key Normalization

**Status**: Accepted | **Date**: 2026-01-11

#### Problème

"SAP S/4HANA" dans Document A et "SAP S/4HANA" dans Document B créaient
2 CanonicalConcepts distincts à cause d'une normalisation insuffisante.

#### Solution: `compute_lex_key()`

```python
def compute_lex_key(canonical_name: str) -> str:
    """
    Normalisation forte:
    1. Lowercase
    2. Unicode NFKD → supprime accents
    3. Remove punctuation
    4. Normalize whitespace
    5. Light singularization

    Exemple: "SAP S/4HANA" → "sap s 4hana"
    """
```

#### Schéma Neo4j

| Propriété | Rôle | Exemple |
|-----------|------|---------|
| `CanonicalConcept.label` | Forme lisible (display) | "SAP S/4HANA" |
| `CanonicalConcept.lex_key` | Clé technique (matching) | "sap s 4hana" |
| `ProtoConcept.lex_key` | Clé technique (ajoutée) | "sap s 4hana" |

#### Type Guard Soft

Pour éviter les faux positifs (homonymes):

```python
def split_by_type_if_divergent(lex_key, protos):
    types = [p.type_heuristic for p in protos if p.type_heuristic]
    counter = Counter(types)
    dominance = top_count / total

    if dominance >= 0.70:
        return [(top_type, protos, False)]  # Pas de split

    if is_short_or_acronym(label):
        return split_by_type(protos)  # Split agressif

    return [(top_type, protos, True)]  # Garder + type_conflict=True
```

---

### 2.3 Structural Context Alignment

**Status**: Accepted | **Date**: 2026-01-11

#### Problème

Explosion MENTIONED_IN: **2,048,725 relations** pour 18 documents.
Cause: Confusion entre `section_id` (cluster textuel) et `context_id` (UUID section).

#### Solution

Ajouter `context_id` structurel sur ProtoConcept:

```cypher
-- AVANT (BUG)
MATCH (p:ProtoConcept)
WITH DISTINCT p.document_id AS doc_id
MATCH (s:SectionContext {doc_id: doc_id})  -- TOUTES les sections!
MERGE (cc)-[:MENTIONED_IN]->(s)

-- APRÈS (CORRECT)
MATCH (p:ProtoConcept)
WHERE p.context_id IS NOT NULL
MATCH (s:SectionContext {context_id: p.context_id})
MERGE (cc)-[:MENTIONED_IN]->(s)
```

#### Résultat Attendu

| Métrique | Avant | Après |
|----------|-------|-------|
| MENTIONED_IN relations | 2,048,725 | < 5,000 |
| Sections par concept | 655 | 2-5 |

---

## 3. Linguistic Layer

### 3.1 Coref Named↔Named Validation

**Status**: Validé | **Date**: 2025-01-15

#### Problème

FastCoref produit des faux positifs pour entités nommées similaires:
- "SAP S/4HANA" ≠ "SAP HANA" (ERP vs Database)

#### Solution: Gating + LLM + Cache

```
FastCoref détecte paire (A, B)
         │
         ▼
┌─────────────────────────┐
│  NamedNamedGatingPolicy │
│  (heuristiques rapides) │
└─────────────────────────┘
         │
    ┌────┴────┬────────┐
    ▼         ▼        ▼
 ACCEPT    REVIEW    REJECT
    │         │        │
    │    ┌────┴────┐   │
    │    │  Cache? │   │
    │    └────┬────┘   │
    │    HIT? │ MISS?  │
    │    ▼    ▼        │
    │    │  ┌─────┐    │
    │    │  │ LLM │    │
    │    │  └──┬──┘    │
    │    ▼    ▼        │
    └────► Décision ◄──┘
```

#### Métriques Gating (modèle "signaux de risque")

```python
def evaluate_named_pair(a, b, context_a, context_b):
    risk = 0

    jw = jaro_winkler(a, b)
    tj = token_jaccard(a, b)
    head_match = head_noun_match(a, b)

    # REJECT direct (cas extrêmes)
    if jw < 0.55: return REJECT, "STRING_SIMILARITY_LOW"
    if tj == 0: return REJECT, "NO_TOKEN_OVERLAP"

    # ACCEPT direct
    if jw >= 0.95 and tj >= 0.8: return ACCEPT, "HIGH_SIMILARITY"

    # Accumulation signaux risque
    if not head_match: risk += 1
    if tfidf_divergence(context_a, context_b) > 0.6: risk += 1
    if 0.55 <= jw <= 0.85: risk += 1
    if 0.1 < tj < 0.5: risk += 1

    if risk == 0: return ACCEPT, "LOW_RISK"
    return REVIEW, "NEEDS_LLM_VALIDATION"
```

#### Décisions Clés

| Question | Décision |
|----------|----------|
| Modèle LLM | vLLM Qwen sur EC2 (coût marginal nul) |
| Fallback LLM | ABSTAIN (philosophie abstention-first) |
| Cache | Global (paires normalisées) + Contextuel (termes courts) |

---

## 4. Relations et Evidence

### 4.1 Multi-Span Evidence Bundles

**Status**: Accepted with Clarifications | **Date**: 2026-01-17

#### Problème

Le KG est **structurellement pauvre**: 1 relation validée sur 850 concepts.
Le système est "localiste" (cherche preuve complète en 512 tokens) alors que
les preuves sont fragmentées à l'échelle du document.

**Exemple:**
- Page 1: "SAP S/4HANA Cloud, Private Edition is the flagship ERP..."
- Page 5: "The solution integrates seamlessly with SAP BTP..."
- Page 8: [Schema] S/4HANA PCE → BTP (flèche)

Les 3 fragments **prouvent** `S/4HANA_PCE --[INTEGRATES_WITH]--> SAP_BTP`,
mais aucun ne la contient entièrement.

#### Solution: Evidence Bundle Resolver

```python
@dataclass
class EvidenceBundle:
    """
    Bundle de preuves pour une relation candidate.

    IMPORTANT: Un EvidenceBundle n'est PAS de la connaissance.
    C'est un ARTEFACT DE JUSTIFICATION structure.
    """

    # Les 4 composants
    evidence_subject: EvidenceFragment      # EA: "SAP S/4HANA" (page 1)
    evidence_object: EvidenceFragment       # EB: "SAP BTP" (page 5)
    evidence_predicate: List[EvidenceFragment]  # EP: "integrates" + flèche
    evidence_link: Optional[EvidenceFragment]   # EL: "the solution" → coref

    # Typage TENTATIF (pas encore validé)
    relation_type_candidate: str    # Type proposé
    typing_confidence: float        # Confiance dans le typage

    # Confiance = min(all fragments) - JAMAIS de moyenne
    confidence: float

    validation_status: Literal["CANDIDATE", "PROMOTED", "REJECTED"]
```

#### Règles de Cohérence (OBLIGATOIRES)

**Règle 1: Proximité Documentaire**
```python
def validate_proximity(bundle) -> bool:
    # Au moins UNE condition vraie:
    # 1. Même section
    # 2. Sections avec parent commun (frères)
    # 3. Lien explicite via TOC/structure
    # 4. Distance max 3 sections consécutives
```

**Règle 2: Validation Lien Linguistique**
- "the solution" doit être résolu via topic dominant
- Topic doit être mentionné dans la section OU ses ancêtres
- Confiance topic binding ≥ 50%

**Règle 3: Cohérence Prédicat (AGNOSTIQUE domaine + langue)**

> Aucune whitelist lexicale métier. Détection morpho-syntaxique uniquement.

```python
def is_modal_or_intentional(doc, predicate_token) -> bool:
    """
    Rejette modaux/intentionnels via Universal Dependencies.
    AGNOSTIQUE LANGUE: fonctionne pour en, fr, de, es, it, ru, zh...
    """
    # Auxiliaire modal (can/peut/kann/puede...)
    if predicate_token.pos_ == "AUX":
        return True

    # Conditionnel morphologique
    if "Mood=Cnd" in str(predicate_token.morph):
        return True

    # Structure intentionnelle "designed to / vise à"
    if has_infinitive_complement(predicate_token):
        return True

    return False

# Verbes génériques exclus (linguistique, pas métier)
GENERIC_VERBS_EXCLUDED = {"be", "have", "do", "get", "make"}

# Relations visuelles (techniques Docling, pas métier)
AMBIGUOUS_VISUAL_RELATIONS = {"grouped_with", "near", "aligned_with"}
```

**Règle 4: Score Composite**
```python
def compute_bundle_confidence(bundle) -> float:
    return min(all_fragment_confidences)  # Maillon faible gouverne
```

#### Cas de Rejet Automatique

| Règle | Condition |
|-------|-----------|
| GENERIC_PREDICATE | "secured", "recommended" sans rattachement clair |
| SCOPE_MISMATCH | Entités dans scopes distincts |
| GLOBAL_TOPIC_ONLY | Lien basé uniquement sur topic global |
| AMBIGUOUS_VISUAL | `grouped_with` sans caption confirmant |
| EXCESSIVE_DISTANCE | Page 1 et page 50 sans lien structurel |

#### Retypage Relations Visuelles (AGNOSTIQUE)

Le retypage est basé sur le **texte présent**, pas sur des patterns métier:

```python
def retype_visual_relation(visual_relation, caption_text, adjacent_text):
    """
    Stratégie agnostique:
    1. Caption/label présent → utiliser comme type
    2. Prédicat dans contexte adjacent → extraire via POS
    3. Sinon → type générique (DIRECTED_RELATION, CONTAINS, etc.)
    """
    if caption_text:
        return normalize_relation_type(caption_text), 0.9

    predicate = extract_predicate_from_context(adjacent_text)
    if predicate and not is_modal_or_intentional(predicate):
        return normalize_relation_type(predicate.lemma_), 0.7

    # Fallback: types génériques
    GENERIC_TYPES = {
        "arrow_to": "DIRECTED_RELATION",
        "contains": "CONTAINS",
        "flow_to": "FLOW_RELATION",
    }
    return GENERIC_TYPES.get(visual_relation, "VISUAL_ASSOCIATION"), 0.5
```

**Extension optionnelle**: Mapping tenant-specific (config, pas cœur).

#### Mode Progressif

| Phase | Scope | Objectif |
|-------|-------|----------|
| **Safe (Sprint 1)** | Intra-section, textuel uniquement | 5-10 relations, précision ≥95% |
| **Extended (Sprint 2)** | Inter-sections liées, mono-topic | 15-25 relations, précision ≥90% |
| **Assisted (Sprint 3)** | Suggestions UI, human-in-the-loop | Pipeline complet |

---

## 5. Schema Neo4j Consolidé

### Nœuds Principaux

```cypher
// Structural Layer (Option C)
(:PageContext {page_id, doc_id, tenant_id, page_number})
(:SectionContext {context_id, section_id, doc_id, tenant_id, title, section_path})
(:DocItem {item_id, section_id, tenant_id, item_type, charspan_start, charspan_end, text_content})

// Retrieval Layer
(:TypeAwareChunk {chunk_id, tenant_id, item_type, text_content})

// Semantic Layer
(:ProtoConcept {
    concept_id, concept_name, lex_key,
    tenant_id, document_id, context_id,
    anchor_status, extract_confidence,
    type_heuristic, definition
})

(:CanonicalConcept {
    canonical_id, label, lex_key, type_bucket,
    tenant_id, type_fine, type_coarse,
    stability, unified_definition,
    proto_count, document_count, type_conflict
})

// Relations Layer (future)
(:EvidenceBundle {bundle_id, confidence, validation_status, ...})
(:SemanticRelation {relation_id, relation_type, confidence, ...})
```

### Relations

```cypher
// Structural
(:DocItem)-[:ON_PAGE]->(:PageContext)
(:SectionContext)-[:CONTAINS]->(:DocItem)
(:TypeAwareChunk)-[:DERIVED_FROM]->(:DocItem)

// Semantic
(:ProtoConcept)-[:ANCHORED_IN]->(:DocItem)      -- JAMAIS vers TypeAwareChunk!
(:ProtoConcept)-[:INSTANCE_OF]->(:CanonicalConcept)
(:CanonicalConcept)-[:MENTIONED_IN]->(:SectionContext)

// Evidence (future)
(:EvidenceBundle)-[:PROMOTED_TO]->(:SemanticRelation)
```

### Index Critiques

```cypher
CREATE INDEX proto_lex_key IF NOT EXISTS
FOR (p:ProtoConcept) ON (p.tenant_id, p.lex_key);

CREATE INDEX proto_context IF NOT EXISTS
FOR (p:ProtoConcept) ON (p.tenant_id, p.context_id);

CREATE CONSTRAINT canonical_unique IF NOT EXISTS
FOR (c:CanonicalConcept)
REQUIRE (c.tenant_id, c.lex_key, c.type_bucket) IS UNIQUE;
```

---

## 6. Modèle de Lecture Stratifiée (v2)

### 6.1 Principe : Lire comme un humain

**Status**: Review Final | **Date**: 2025-01-23
**Source**: [ADR_STRATIFIED_READING_MODEL.md](ADR_STRATIFIED_READING_MODEL.md)

#### Problème

OSMOSIS v1 extrait des concepts **chunk par chunk** (bottom-up), puis tente de valider des relations.
Résultat : 90k+ nodes pour 19 documents, très peu de relations validées, graphe "pur" mais **fonctionnellement inutile**.

> **Diagnostic** : OSMOSIS scanne, il ne lit pas. On utilise les LLM pour valider des liens entre artefacts fragmentés, au lieu de les utiliser pour comprendre et structurer.

#### Solution : Inversion du flux (top-down)

| OSMOSIS v1 (bottom-up) | OSMOSIS v2 (top-down) |
|------------------------|----------------------|
| Chunk → Concepts → Relations (échoue) | Document → Structure → Concepts → Information |
| Extraction locale puis consolidation | Compréhension globale puis extraction ciblée |
| Beaucoup de concepts, peu de liens | Peu de concepts, beaucoup d'information rattachée |
| LLM = validateur oui/non | LLM = lecteur qui comprend |

#### Flux en 4 étapes

1. **Comprendre le document** : Identifier Subject, Themes, Structure (arbre hiérarchique récursif)
2. **Identifier les concepts structurants** (20-50 par document) : Frugal, uniquement ceux qui portent plusieurs informations
3. **Extraire l'information rattachée** : Exhaustif, typé (DEFINITION, CAPABILITY, CONSTRAINT, etc.)
4. **Relations médiées** : Jamais par co-occurrence, toujours par Information qui lie deux concepts

#### Structures de dépendance des assertions (agnostique domaine)

| Structure | Définition | Rôle ConceptSitué |
|-----------|------------|-------------------|
| **CENTRAL** | Assertions dépendantes d'un artefact unique | `role = CENTRAL` |
| **TRANSVERSAL** | Assertions indépendantes | Concepts autonomes |
| **CONTEXTUAL** | Assertions conditionnelles | `role = CONTEXTUAL` |

### 6.2 Stratification de l'Information

| Niveau | Nom | Description | Volumétrie |
|--------|-----|-------------|------------|
| **N0** | Information | Unité atomique de sens, typée et ancrée | 200-500 / doc |
| **N1** | ConceptSitué | Objet mental stable, doc-level, frugal | 20-50 / doc |
| **N2** | Projection contextuelle | Fermeture informationnelle query-time | Calculé |
| **N3** | ConceptCanonique | Stabilisation cross-document, tardive | 50-150 / 20 docs |

> **Règle clé** : L'information est cheap, les concepts sont chers. Privilégier l'information.

---

## 7. North Star - Vérité Documentaire Contextualisée

### 7.1 Positionnement épistémique

**Status**: ✅ VALIDÉ COMME NORTH STAR | **Date**: 2026-01-25
**Source**: [ADR_NORTH_STAR_VERITE_DOCUMENTAIRE.md](ADR_NORTH_STAR_VERITE_DOCUMENTAIRE.md)

#### Formulation North Star

> **OSMOSIS est le Knowledge Graph documentaire de l'entreprise et l'arbitre de sa vérité documentaire :
> il capture, structure et expose la connaissance telle qu'elle est exprimée dans le corpus documentaire,
> sans jamais extrapoler au-delà de ce corpus.**

Version opérationnelle :
> **Dans le périmètre du corpus documentaire, OSMOSIS est la source de vérité. En dehors de ce périmètre, il n'a pas d'opinion.**

#### Ce qu'OSMOSIS arbitre

| Domaine | Exemple |
|---------|---------|
| Ce qui est **affirmé** | "TLS 1.2 est obligatoire" (doc A) → vrai dans le corpus |
| Ce qui est **contredit** | Doc A dit X, Doc B dit Y → la contradiction est vraie |
| Ce qui est **absent** | Aucun doc ne parle de Z → l'absence est vraie |

#### Principes fondamentaux

- **Information-First** : L'Information est l'entité primaire, le Concept est optionnel
- **Addressability-First** : Toute Information promue doit avoir au moins un pivot (Theme, ClaimKey, Concept, Facet)
- **LLM = Extracteur, pas Arbitre** : Citation exacte obligatoire, pas d'interprétation
- **Concept-Frugal** : LLM propose, Système dispose (Gates G1-G4)

### 7.2 ClaimKey et Compare/Challenge

Un **ClaimKey** est un identifiant stable représentant une question factuelle, indépendant du vocabulaire.

```yaml
ClaimKey:
  canonical_question: "Quelle est la version TLS minimum requise ?"
  key: "tls_min_version"
  status: emergent | comparable | deprecated | orphan
```

#### Contradictions exposées (jamais résolues)

| Nature | Description |
|--------|-------------|
| `value_conflict` | Valeurs différentes pour même question |
| `scope_conflict` | Applicabilité différente |
| `temporal_conflict` | Versions/dates différentes |
| `missing_claim` | Document ne se prononce pas |

---

## 8. Séparation Scope vs Assertion

### 8.1 Scope Layer vs Assertion Layer

**Status**: ✅ APPROVED — BLOCKING | **Date**: 2026-01-21
**Source**: [ADR_SCOPE_VS_ASSERTION_SEPARATION.md](ADR_SCOPE_VS_ASSERTION_SEPARATION.md)

#### Décision

Séparation stricte entre deux couches :

| Couche | Ce qu'elle exprime | Densité | Traversable |
|--------|-------------------|---------|-------------|
| **Scope Layer** | Ce que le document **couvre** | Dense | Non (navigation) |
| **Assertion Layer** | Ce que le document **affirme** | Sparse | Oui (raisonnement) |

> **OSMOSIS ne cherche pas à tout relier. Il cherche à ne relier que ce qui est défendable.**

#### Architecture

```
┌── SCOPE LAYER (dense) ──────────────────────────┐
│ Document topic, Section scope, DocItem mentions  │
│ Usage: Navigation, Filtrage, Recherche Anchored  │
│ Traversable: NON                                 │
└──────────────────────────────────────────────────┘
          │ (ancrage, pas promotion)
          ▼
┌── ASSERTION LAYER (sparse) ─────────────────────┐
│ RawAssertion → CanonicalRelation → Semantic...   │
│ Seules les relations avec PREUVE LOCALE          │
│ Usage: Raisonnement, Traversée, Inférence        │
│ Traversable: OUI                                 │
└──────────────────────────────────────────────────┘
```

### 8.2 Invariants de séparation

| Invariant | Règle |
|-----------|-------|
| **INV-SEP-01** | Un scope ne peut jamais être promu en assertion sans preuve textuelle locale |
| **INV-SEP-02** | Toute assertion doit avoir un EvidenceBundle avec au moins un span |
| **INV-SEP-03** | La Scope Layer sert à filtrer/naviguer, jamais à inférer/traverser |
| **INV-SEP-04** | La frontière Scope/Assertion doit être explicite dans le code et les données |

---

## Annexe: Pipeline OSMOSE Complet

```
Pass 0: Structural Graph (DoclingDocument → DocItem, SectionContext, PageContext)
Pass 0.5: Linguistic Layer (FastCoref + Named↔Named Gating)
Pass 1: Concept Extraction (→ ProtoConcept avec lex_key, context_id)
Pass 2.0: Unified Corpus Promotion (→ CanonicalConcept + INSTANCE_OF + MENTIONED_IN)
Pass 3: Relation Extraction (existant, intra-section)
Pass 3.5: Evidence Bundle Resolver (NEW - cross-section, visual)
Pass 4: Entity Resolution (existant)
Pass 5: Corpus-level Consolidation (existant)
```

---

## Changelog

| Date | Version | Changements |
|------|---------|-------------|
| 2026-01-17 | 1.0 | Création initiale - Consolidation 8 ADRs |
| 2026-01-17 | 1.1 | Multi-Span Evidence: clarifications ontologiques |
| 2026-01-17 | 1.2 | Multi-Span Evidence: agnosticité domaine + langue (POS-based) |
| 2026-01-29 | 2.0 | Triage ADR: §1.3 Dual Chunking marqué ARCHIVÉ (superseded). Ajout §6 Lecture Stratifiée, §7 North Star Vérité Documentaire, §8 Scope vs Assertion (3 ADRs promus). |

---

*Document généré pour partage ChatGPT - OSMOSE Knowledge Base*
