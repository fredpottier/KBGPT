# ADR: Document Context Constraints & Entity Hints

**Status**: VALIDATED - Reviewed by ChatGPT
**Date**: 2026-01-08
**Authors**: Fred (idee), Claude Code (redaction), ChatGPT (review/corrections)
**Contexte**: Amelioration de la detection de markers via contraintes Document Summary

---

## 1. Contexte et Probleme

### 1.1 Pipeline actuel d'extraction de markers

```
Document (texte brut)
       ↓
┌──────────────────────────────────────┐
│  CandidateMiner                      │
│  - Patterns regex (SEMVER, NUMERAL)  │  ← Extraction syntaxique
│  - Aucun contexte document           │
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│  CandidateGate (filtrage)            │
│  - Dates, copyright, pages, etc.     │  ← Filtrage par patterns
│  - Pas de contexte semantique        │
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│  LLM Validation (Arbitre)            │
│  - CONTEXT_SETTING / TEMPLATE_NOISE  │  ← Context limite (chunk)
└──────────────────────────────────────┘
       ↓
DocContextFrame (strong_markers, weak_markers)
```

### 1.2 Probleme identifie : ~40% de faux positifs

Source : `doc/ongoing/ANALYSE_FAUX_POSITIFS_MARKERS.md`

| Type de faux positif | Exemples | Cause racine |
|----------------------|----------|--------------|
| **Numerotation sections** | "PUBLIC 3", "Content 2", "EXTERNAL 2" | Pattern `MOT + CHIFFRE` trop permissif |
| **Mots courants** | "based", "any" | Extraction non filtree |
| **Qualificatifs** | "Private" (x2) | Confusion avec versions |

**Pattern problematique** (candidate_mining.py:77) :
```python
r'\b([A-Z][a-zA-Z0-9/]*)\s+(\d{1,2})\b'  # "iPhone 15" mais aussi "PUBLIC 3"
```

### 1.3 Limite du filtrage syntaxique

Le CandidateGate filtre correctement les patterns **universels** (dates, pages, trimestres) mais ne peut pas distinguer :
- `"iPhone 15"` (produit + generation) ✅
- `"PUBLIC 3"` (section de document) ❌

**Raison** : Le filtrage syntaxique n'a pas acces au **contexte global du document**.

---

## 2. Opportunite : Le Document Summary

### 2.1 Pipeline existant

OSMOSE dispose deja d'une etape `generate_document_summary()` qui :
1. Envoie un echantillon du document au LLM (4000 + 1000 derniers chars)
2. Genere un **resume contextuel** (theme, noms officiels, domaine)
3. Extrait un **technical_density_hint** (0.0-1.0)
4. Ce resume est ensuite **injecte dans tous les prompts d'extraction**

**Fichier** : `src/knowbase/ingestion/osmose_enrichment.py:191-270`

### 2.2 Ce que le prompt actuel demande

```
For the summary, focus on:
- Main theme/topic of the document
- Full official names of products, solutions, or key terms mentioned
- Industry or domain context
- Target audience
```

### 2.3 Ce qui manque (et peut etre ajoute)

| Information | Utilite | Impact sur markers |
|-------------|---------|-------------------|
| **Structure detectee** | "document avec sections numerotees" | Filtrage faux positifs |
| **Entity hints** | Entites dominantes du document | Renforcement normalisation |
| **Temporal hint** | Date explicite/inferee | Classification FRAGILE |
| **Scope hints** | "cloud only", "on-premise" | Differenciation variantes |

---

## 3. Proposition : Document Context Constraints & Entity Hints

### 3.1 Idee centrale

> **Le LLM n'extrait pas de markers. Il produit des contraintes globales et des "entity hints" qui guident l'interpretation des markers extraits localement (syntaxiques) et leur normalisation.**

Objectifs :

1. Injecter un **signal structurel global** (numerotation, artefacts de plan) pour reduire les faux positifs type `"PUBLIC 3"`.
2. Fournir des **entity hints** (entites dominantes, produits/systemes/normes) pour renforcer la normalisation des markers ambigus.
3. Fournir des **temporal hints** (date explicite/inferee) pour classifier FRAGILE/STALE au niveau document.
4. Respecter le principe **assertion-centric** : tout marker utilise doit rester tracable a une **preuve locale** (MarkerMention + excerpt/page/section). Le LLM summary ne cree aucune "verite" sans preuve.

Rationale :

* Le filtrage syntaxique n'a pas acces au contexte global.
* Le LLM chunk-level n'a pas assez de structure.
* Le summary voit un echantillon large et peut caracteriser la **structure** du document et ses **ancres dominantes**, sans devenir une source de verite sur les markers.

### 3.2 Nouveau format de retour propose (constraints-only)

```json
{
  "summary": "...",
  "technical_density": 0.7,
  "document_context": {
    "structure_hint": {
      "has_numbered_sections": true,
      "numbering_patterns": ["WORD+NUMBER", "1.2.3"],
      "confidence": 0.9
    },
    "entity_hints": [
      {
        "label": "SAP S/4HANA Cloud",
        "type_hint": "product|system|standard|regulation|org|other",
        "confidence": 0.8,
        "evidence": "explicit|inferred"
      }
    ],
    "temporal_hint": {
      "explicit": "2024-Q1",
      "inferred": "2024",
      "confidence": 0.7
    },
    "scope_hints": ["cloud", "on-premise", "public edition"]
  }
}
```

**Notes importantes** :

* `entity_hints` ne remplace pas les markers : il sert a **renforcer** ou **degrader** la confiance sur des markers extraits localement.
* `temporal_hint` ne cree pas une date officielle : il sert a configurer un **risque** (FRAGILE/STALE) et doit rester "soft".
* **Aucun champ `product_versions`** : le LLM ne cree pas de markers.

### 3.3 Integration avec le pipeline existant (hierarchie de verite)

Hierarchie explicite :

1. **MarkerMention (syntaxique + preuve locale)** = source de verite des markers detectes
2. **Normalization Layer (rules/aliases/human)** = transformation controlee des MarkerMentions
3. **Document Context (LLM)** = contraintes et hints (autorise / interdit / pondere), **jamais createur**

Pipeline :

```
Document (texte brut)
       ↓
┌──────────────────────────────────────┐
│ generate_document_summary()          │
│  - summary                           │
│  - technical_density                 │
│  - document_context (constraints)    │  ← NOUVEAU : contraintes/hints
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ CandidateMiner (syntaxique)          │  ← extraction MarkerMentions
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ CandidateGate + ContextConstraints   │
│  - filtres universels                │
│  - + structure_hint gating           │  ← rejette/abaisse risques "PUBLIC 3"
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ NormalizationEngine                  │
│  - rules/aliases                     │
│  - uses entity_hints as anchor boost │  ← renforce la normalisation
└──────────────────────────────────────┘
       ↓
DocContextFrame (strong/weak/unresolved markers + document_context)
```

**Regle cle** :

* **Aucun marker "LLM-only" n'entre dans DocContextFrame**.
  Le LLM ne peut que :
  - degrader (structure risk HIGH)
  - renforcer (entity hint corroborant)
  - aider a decider unresolved vs weak/strong

---

## 3.4 Decision Rules — MarkerMention → MarkerDecision (constraints-only)

### 3.4.1 Objectif

Transformer chaque `MarkerMention` extrait syntaxiquement en une decision standardisee :

* `ACCEPT_STRONG`
* `ACCEPT_WEAK`
* `UNRESOLVED`
* `REJECT`

... en appliquant :

1. des regles universelles (deja dans CandidateGate)
2. des **contraintes document-level** issues de `document_context` (structure_hint + entity_hints)
3. une logique **safe-by-default** (preferer UNRESOLVED a ACCEPT en cas de doute)

> Important : `document_context` ne cree jamais de MarkerMention. Il ne fait que ponderer/contraindre.

### 3.4.2 Structures de donnees

```python
@dataclass
class MarkerMention:
    raw_text: str                 # ex: "PUBLIC 3", "iPhone 15", "S/4HANA 2023"
    prefix: Optional[str]         # ex: "PUBLIC", "iPhone", "S/4HANA" (si parsable)
    number: Optional[str]         # ex: "3", "15", "2023"
    number_len: int               # len(number) if any
    shape: str                    # enum: WORD_NUMBER, YEAR, QUARTER, VERSIONLIKE, OTHER
    evidence: EvidenceRef         # {document_id, context_id, section_path, excerpt, char_start, char_end}
    position_hint: PositionHint   # {is_heading_like, line_start, has_colon_after, in_toc_like, ...}

@dataclass
class DocumentContext:
    structure_hint: StructureHint
    entity_hints: list[EntityHint]
    temporal_hint: TemporalHint

@dataclass
class StructureHint:
    has_numbered_sections: bool
    numbering_patterns: list[str]   # e.g., ["WORD+NUMBER", "1.2.3"]
    confidence: float

@dataclass
class EntityHint:
    label: str                      # dominant entity label
    type_hint: str                  # product|system|standard|regulation|org|other
    confidence: float
    evidence: str                   # explicit|inferred

@dataclass
class MarkerDecision:
    decision: str                   # ACCEPT_STRONG|ACCEPT_WEAK|UNRESOLVED|REJECT
    score: float                    # 0..1
    reasons: list[str]              # human-readable tags for debugging/audit
```

### 3.4.3 Fonctions auxiliaires (signaux)

```python
def is_small_number(m: MarkerMention) -> bool:
    return m.number is not None and m.number_len <= 2

def is_year_like(m: MarkerMention) -> bool:
    return m.shape == "YEAR" and m.number is not None and 1900 <= int(m.number) <= 2100

def is_heading_artifact(m: MarkerMention) -> bool:
    # agnostic structural cues (not lexical blacklists)
    return (
        m.position_hint.is_heading_like
        or m.position_hint.in_toc_like
        or m.position_hint.line_start and m.position_hint.has_colon_after
    )

def has_entity_anchor(m: MarkerMention, ctx: DocumentContext) -> bool:
    """
    True if the mention prefix or raw_text overlaps a dominant entity hint
    with sufficient confidence, e.g. prefix == "iPhone" matches entity_hints "iPhone".
    """
    if not m.prefix:
        return False
    for eh in ctx.entity_hints:
        if eh.confidence >= 0.75 and token_overlap(m.prefix, eh.label):
            return True
    return False

def structure_risk_high(m: MarkerMention, ctx: DocumentContext) -> bool:
    """
    High risk when the document has numbered sections and the mention looks like WORD+SMALL_NUMBER,
    especially in heading-like positions.
    """
    if ctx.structure_hint.confidence < 0.7:
        return False
    if not ctx.structure_hint.has_numbered_sections:
        return False
    if m.shape != "WORD_NUMBER":
        return False
    if not is_small_number(m):
        return False
    return True
```

### 3.4.4 Regles de decision (pseudo-code)

```python
def decide_marker(m: MarkerMention, ctx: DocumentContext) -> MarkerDecision:
    reasons = []
    score = 0.50  # baseline neutral

    # ---------------------------------------------------------
    # (0) Hard rejects from universal gate (dates, noise, etc.)
    # ---------------------------------------------------------
    if universal_reject(m):
        return MarkerDecision("REJECT", 0.0, ["UNIVERSAL_REJECT"])

    # ---------------------------------------------------------
    # (1) Strong accept candidates (safe shapes)
    # ---------------------------------------------------------
    if is_year_like(m):
        # year markers are not always "product versions", but are valid temporal markers
        score += 0.20
        reasons.append("YEAR_LIKE")

        # if the doc has explicit temporal hint matching, strengthen
        if ctx.temporal_hint and ctx.temporal_hint.explicit and matches_year(ctx.temporal_hint, m.number):
            score += 0.15
            reasons.append("MATCHES_TEMPORAL_HINT_EXPLICIT")

        return finalize(score, reasons, min_decision="ACCEPT_WEAK")

    # ---------------------------------------------------------
    # (2) Structural risk gating (key fix for PUBLIC 3)
    # ---------------------------------------------------------
    if structure_risk_high(m, ctx):
        reasons.append("STRUCTURE_RISK_HIGH")

        # Heading artifacts are almost certainly not variants/versions
        if is_heading_artifact(m):
            reasons.append("HEADING_OR_TOC_ARTIFACT")
            return MarkerDecision("REJECT", 0.05, reasons)

        # If not clearly heading-like, do not accept by default
        score -= 0.25

        # Only allow if there is a strong entity anchor corroborating
        if has_entity_anchor(m, ctx):
            score += 0.35
            reasons.append("ENTITY_ANCHOR_CORROBORATES")
        else:
            reasons.append("NO_ENTITY_ANCHOR")

        return finalize(score, reasons)

    # ---------------------------------------------------------
    # (3) WORD+NUMBER without high structure risk
    # ---------------------------------------------------------
    if m.shape == "WORD_NUMBER" and m.number is not None:
        reasons.append("WORD_NUMBER")

        # small numbers are inherently ambiguous; require corroboration
        if is_small_number(m):
            reasons.append("SMALL_NUMBER_AMBIGUOUS")
            score -= 0.15

            if has_entity_anchor(m, ctx):
                score += 0.30
                reasons.append("ENTITY_ANCHOR_CORROBORATES")
            else:
                reasons.append("NO_ENTITY_ANCHOR")

            return finalize(score, reasons)

        # larger numbers (>=3 digits) less likely to be heading counters, but still cautious
        score += 0.05
        if has_entity_anchor(m, ctx):
            score += 0.15
            reasons.append("ENTITY_ANCHOR_CORROBORATES")

        return finalize(score, reasons, min_decision="ACCEPT_WEAK")

    # ---------------------------------------------------------
    # (4) Fallback: unknown shapes stay unresolved unless corroborated
    # ---------------------------------------------------------
    reasons.append("UNKNOWN_SHAPE")
    if has_entity_anchor(m, ctx):
        score += 0.10
        reasons.append("ENTITY_ANCHOR_LIGHT_BOOST")
    return finalize(score, reasons)
```

### 3.4.5 Finalisation (safe-by-default thresholds)

```python
def finalize(score: float, reasons: list[str], min_decision: str="UNRESOLVED") -> MarkerDecision:
    score = max(0.0, min(1.0, score))

    # Hard policy: prefer UNRESOLVED over ACCEPT when ambiguous
    if score >= 0.80:
        decision = "ACCEPT_STRONG"
    elif score >= 0.60:
        decision = "ACCEPT_WEAK"
    elif score <= 0.20:
        decision = "REJECT"
    else:
        decision = "UNRESOLVED"

    # Enforce minimum decision if requested (e.g., years)
    decision = enforce_min(decision, min_decision)

    return MarkerDecision(decision, score, reasons)
```

### 3.4.6 Invariants (non-negociables)

**Invariant A — No marker creation**
`DocumentContext` ne cree jamais de MarkerMention. Il ne fait que modifier la decision ou le score.

**Invariant B — Reason tags mandatory**
Toute decision `ACCEPT_*` doit conserver des `reasons[]` explicites (audit/debug).

**Invariant C — Safe-by-default**
En cas de doute (score intermediaire), la decision doit rester `UNRESOLVED` plutot que "accept".

**Invariant D — Evidence local required**
Un marker accepte doit avoir une `EvidenceRef` locale (excerpt + context_id).
Le summary n'est pas une preuve.

### 3.4.7 Exemples

**PUBLIC 3** (doc structure, heading-like)
- `structure_risk_high=True` + `is_heading_artifact=True` → `REJECT`

**iPhone 15** (pas de numbering sections, entity_hints contient "iPhone")
- `WORD_NUMBER` + `SMALL_NUMBER` + `ENTITY_ANCHOR_CORROBORATES` → `ACCEPT_WEAK/STRONG`

**2023** (year-like, temporal_hint explicite "2023")
- `YEAR_LIKE` + `MATCHES_TEMPORAL_HINT_EXPLICIT` → `ACCEPT_WEAK` (temporal marker)

**S/4HANA 2023** (entity_hints contient "SAP S/4HANA", number >= 4 digits)
- `WORD_NUMBER` + `ENTITY_ANCHOR_CORROBORATES` → `ACCEPT_STRONG`

---

## 4. Benefices attendus

### 4.1 Reduction des faux positifs

| Probleme actuel | Solution avec Document Context Constraints |
|-----------------|-------------------------------------------|
| "PUBLIC 3" detecte comme version | `structure_hint.has_numbered_sections = true` + `is_heading_artifact` → REJECT |
| "Private" detecte comme version | LLM comprend que c'est un qualificatif de deployment → scope_hints |
| "2023" ambigu sans entity | `entity_hints` fournit l'ancre pour normalisation |

### 4.2 Enrichissement des SourceRef (Assertion-Centric)

Le nouveau modele `InstrumentedAnswer` (voir ADR Assertion-Centric) necessite :

```json
"document": {
  "date": "2025-02",
  "authority": "official"
}
```

Avec `temporal_hint`, ces informations sont extraites une seule fois au niveau document.

### 4.3 Amelioration de la classification FRAGILE

Regle (assertion_classifier) :
```python
STALE_MONTHS = 60  # document_date < now - 60 mois → FRAGILE
```

Avec `temporal_hint`, cette regle devient **applicable**.

### 4.4 Entity Anchor automatique

L'ADR Marker Normalization Layer exige un "Entity Anchor" pour normaliser les markers ambigus. Avec `entity_hints` :

```python
# Avant : Entity Anchor = concept extrait du document (incertain)
# Apres : Entity Anchor = entity_hints[0].label (explicite du LLM si confidence >= 0.75)
```

---

## 5. Compatibilite avec les ADRs existants

### 5.1 ADR_DOCUMENT_STRUCTURAL_AWARENESS.md

**Principe** : "Un marqueur n'est valide que s'il contribue a differencier le document en tant qu'artefact informationnel."

**Compatibilite** : ✅ Le `structure_hint` permet de rejeter les markers qui sont des artefacts structurels (sections).

### 5.2 ADR_MARKER_NORMALIZATION_LAYER.md

**Principe** : "PAS DE DOMAIN-SPECIFIC DANS LE MOTEUR"

**Compatibilite** : ✅ Le prompt LLM reste generique. C'est le document lui-meme qui fournit le contexte domaine, pas le code.

**Principe** : "Safe-by-default - Si normalisation incertaine → reste unresolved"

**Compatibilite** : ✅ Les `entity_hints` ont un champ `confidence`. Si < seuil → pas utilise comme ancre.

### 5.3 ANALYSE_FAUX_POSITIFS_MARKERS.md

**Piste B (recommandee)** : "Exiger un Entity Anchor fort"

**Compatibilite** : ✅ `entity_hints` fournit directement l'Entity Anchor.

**Piste A** : "Enrichir les signaux structurels"

**Compatibilite** : ✅ `structure_hint.has_numbered_sections` permet de filtrer les faux positifs type "PUBLIC 3".

---

## 6. Prompt LLM propose (constraints-first, no marker creation)

```
System: You are a document analyst.

Your tasks:
1) Produce a concise summary (1-2 paragraphs, max 500 characters).
2) Estimate technical density (0.0-1.0).
3) Produce DOCUMENT CONTEXT CONSTRAINTS to help interpret locally-extracted markers.
   IMPORTANT: You do NOT create markers. You only provide constraints and hints.

For the summary, focus on:
- Main theme/topic
- Full official names of the dominant entities (products/systems/standards/regulations/orgs)
- Domain context

For document_context, provide:

A) structure_hint:
- Does the document use numbered headings/sections?
- What numbering patterns are present (e.g., "WORD+NUMBER", "1.2.3")?
- Confidence.

B) entity_hints:
- List up to 5 dominant entities that the document is mainly about.
- For each, provide:
  - label
  - type_hint: product|system|standard|regulation|org|other
  - confidence
  - evidence: "explicit" if clearly stated, otherwise "inferred"
- IMPORTANT: Do not fabricate versions or years.

C) temporal_hint:
- If an explicit publication/creation date is clearly stated, extract it.
- If not explicit, you may provide a weak inferred year with low confidence.
- Prefer "unknown" over guessing.

D) scope_hints:
- Generic deployment/variant cues (cloud/on-premise/edition/region) if explicitly mentioned.

Strict rules:
- Do NOT output "product_versions".
- Do NOT turn section numbers into versions.
- If the document has numbered sections, tokens like "PUBLIC 3" are likely headings, not versions.
- If unsure, set confidence low and/or return empty lists.

Output JSON only:
{
  "summary": "...",
  "technical_density": 0.X,
  "document_context": {
    "structure_hint": {
      "has_numbered_sections": true/false,
      "numbering_patterns": ["..."],
      "confidence": 0.X
    },
    "entity_hints": [
      {"label":"...", "type_hint":"...", "confidence":0.X, "evidence":"explicit|inferred"}
    ],
    "temporal_hint": {"explicit":"YYYY-MM|YYYY-Q#", "inferred":"YYYY", "confidence":0.X},
    "scope_hints": ["..."]
  }
}

Write the summary in the same language as the document.
```

---

## 7. Implementation estimee

| Tache | Effort | Dependance |
|-------|--------|------------|
| Modifier prompt `generate_document_summary()` | 1h | - |
| Creer dataclasses `DocumentContext`, `StructureHint`, `EntityHint` | 30min | - |
| Parser la nouvelle structure JSON | 30min | - |
| Implementer `decide_marker()` dans CandidateGate | 2h | - |
| Modifier `NormalizationEngine` pour utiliser `entity_hints` | 1h | ADR Marker Normalization |
| Tests avec corpus faux positifs existant | 2h | - |
| **Total** | **~7h** | - |

---

## 8. Decision

**ADOPTE** avec les garde-fous suivants :

1. **LLM = contraintes uniquement** : Le Document Summary ne cree jamais de markers
2. **Hierarchie de verite** : MarkerMention > Normalization > Document Context
3. **Safe-by-default** : En cas de doute, decision = UNRESOLVED
4. **Audit obligatoire** : Toute decision ACCEPT_* doit avoir des `reasons[]`

---

## 9. References

- `doc/ongoing/ANALYSE_FAUX_POSITIFS_MARKERS.md` - Analyse des 40% de faux positifs
- `doc/ongoing/ADR_MARKER_NORMALIZATION_LAYER.md` - Architecture de normalisation
- `doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md` - Principes d'extraction
- `doc/ongoing/OSMOSE_ASSERTION_CENTRIC_IMPLEMENTATION.md` - Spec assertion-centric
- `src/knowbase/ingestion/osmose_enrichment.py:191-270` - Pipeline actuel document summary
