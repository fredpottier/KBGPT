# ADR: Document Structural Awareness Layer

*Architecture Decision Record - OSMOSE Cognitive Infrastructure*
*Date: Janvier 2026*
*Status: ✅ IMPLEMENTED - Janvier 2026*
*Reviewers: Claude (Anthropic), ChatGPT (OpenAI)*

---

## Implementation Status (Janvier 2026)

| Composant | Fichier | Status |
|-----------|---------|--------|
| **Phase 1: Infrastructure structurelle** | | ✅ **COMPLET** |
| ZoneSegmenter | `extraction_v2/context/structural/zone_segmenter.py` | ✅ |
| TemplateDetector | `extraction_v2/context/structural/template_detector.py` | ✅ |
| Models (PageZones, TemplateFragment) | `extraction_v2/context/structural/models.py` | ✅ |
| **Phase 2: Enrichissement candidats** | | ✅ **COMPLET** |
| MarkerCandidate enrichi | `extraction_v2/context/candidate_mining.py` | ✅ |
| LinguisticCueDetector | `extraction_v2/context/structural/linguistic_cue_detector.py` | ✅ |
| EvidenceSample avec zone/page | `extraction_v2/context/candidate_mining.py` | ✅ |
| **Phase 3: LLM Validation** | | ✅ **COMPLET** |
| Prompt production-grade | `extraction_v2/context/prompts.py` | ✅ |
| CandidateGate (filtrage universel) | `extraction_v2/context/candidate_mining.py` | ✅ |

**Fichiers implémentés:**
```
src/knowbase/extraction_v2/context/structural/
├── __init__.py
├── zone_segmenter.py      # ~150 lignes - Segmentation TOP/MAIN/BOTTOM
├── template_detector.py   # ~300 lignes - Détection boilerplate
├── linguistic_cue_detector.py  # ~300 lignes - Scoring patterns linguistiques
└── models.py              # ~400 lignes - PageZones, TemplateFragment, ContextualCues
```

---

## 1. Contexte et Problème

### 1.1 Constat

Lors de la validation du pipeline DocContext (PR1-4), un faux positif a été identifié :

| Document | Marker détecté | Classification | Réalité |
|----------|----------------|----------------|---------|
| `S4HANA_1809_BUSINESS_SCOPE_MASTER_L23.pdf` | `1809` | strong_marker | ✅ Correct (version SAP) |
| | `2019` | weak_marker | ❌ Faux positif (copyright footer) |

Le `2019` provient de la ligne `"© 2019 SAP SE or an SAP affiliate company. All rights reserved."` répétée en bas de chaque slide.

### 1.2 Analyse racine

Le système actuel ne distingue pas :
- Le **contenu porteur de sens documentaire** (titres, sections, révisions)
- Le **contenu structurel répétitif** (templates, légal, branding, footers)

Un humain fait cette distinction **avant même de réfléchir au sens**.
Le cortex documentaire OSMOSE doit faire pareil.

### 1.3 Pourquoi un filtre hardcodé est inacceptable

Une solution naïve serait d'ajouter un regex pour filtrer les lignes de copyright.

**Raisons du rejet :**
1. **Violation de l'agnosticisme** : OSMOSE doit fonctionner pour tout domaine
2. **Maintenance infinie** : Chaque nouveau format nécessiterait un pattern
3. **Faux négatifs** : Un document sur le "Copyright Act 2019" serait filtré à tort

---

## 2. Décision

### 2.1 Principe fondamental

> **Un marqueur n'est valide que s'il contribue à différencier le document en tant qu'artefact informationnel.**
>
> Tout élément purement décoratif, légal ou structurel est du *template noise*, indépendamment de sa valeur sémantique brute.

Ce principe est **agnostique** :
- Ce n'est pas "copyright SAP"
- Ce n'est pas "année ≠ version"
- C'est "ce qui différencie ce document d'un autre document équivalent"

### 2.2 Solution retenue

Implémenter un **Document Structural Awareness Layer** qui :
1. Segmente chaque page en zones logiques (TOP/MAIN/BOTTOM)
2. Détecte les fragments répétitifs inter-pages (template/boilerplate)
3. Enrichit chaque MarkerCandidate avec des features structurelles
4. Permet au LLM d'arbitrer avec des données objectives

### 2.3 Hypothèses explicites et modes de défaillance

> *Section ajoutée suite au review ChatGPT - Janvier 2026*

#### Hypothèses cognitives du système

Ce système **encode des hypothèses sur la forme de l'information humaine** :

1. **Hypothèse de répétition** : Un fragment répété sur plusieurs pages dans la même zone est probablement du template
2. **Hypothèse de zone** : Les footers/headers contiennent généralement du contenu structurel, pas sémantique
3. **Hypothèse de stabilité** : Un contenu à haute stabilité positionnelle est probablement décoratif

Ces hypothèses sont **valides pour 80-90% des documents humains**, mais pas universelles.

#### Règles de protection (OBLIGATOIRES)

> **RÈGLE 1 : La répétition seule ne suffit JAMAIS à conclure TEMPLATE_NOISE.**
> Elle doit être combinée à : zone + cues linguistiques + faible diversité contextuelle.
>
> Repeated fragments in MAIN_ZONE with `scope_language_score > 0.3` must NOT be auto-rejected.

> **RÈGLE 2 : Quand les signaux structurels sont faibles ou conflictuels, préférer AMBIGUOUS.**
> Le LLM ne doit JAMAIS deviner. En cas de doute, AMBIGUOUS est la réponse correcte.

> **RÈGLE 3 : `lexical_shape` ne doit JAMAIS être utilisé pour inférer un sens.**
> Ce champ décrit uniquement la forme lexicale, pas la sémantique.

#### Cas de défaillance connus

| Cas | Comportement attendu | Risque si non géré |
|-----|---------------------|-------------------|
| Documents courts (1-2 pages) | `structural_confidence=LOW`, pas de décision forte | Sur-classification AMBIGUOUS |
| Normes/standards (répétition sémantique) | MAIN_ZONE + scope_language → CONTEXT_SETTING | Faux TEMPLATE_NOISE |
| Documents créatifs (anti-template) | Absence de structure acceptée | Forcer un contexte inexistant |
| OCR bruité | Signaux faibles partout | Sur-dépendance au LLM |

---

## 3. Architecture

### 3.1 Pipeline cible

```
Document
    ↓
┌─────────────────────────────────────┐
│  Structural Normalization           │  ← Nouveau
│  (Zone Segmentation per page)       │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Template Detection                 │  ← Nouveau
│  (Repetition clustering)            │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Marker Candidate Extraction        │  ← Existant (enrichi)
│  (Structure-aware)                  │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Marker Characterization            │  ← Nouveau
│  (Statistical + Structural)         │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  LLM Validation                     │  ← Existant (prompt amélioré)
│  (Arbitre, pas extracteur)          │
└─────────────────────────────────────┘
    ↓
DocContextFrame (trusted)
```

### 3.2 Positionnement dans l'architecture OSMOSE

```
extraction_v2/
├── context/
│   ├── structural/                    ← NOUVEAU MODULE
│   │   ├── __init__.py
│   │   ├── zone_segmenter.py         # Segmentation TOP/MAIN/BOTTOM
│   │   ├── template_detector.py      # Détection boilerplate
│   │   └── models.py                 # PageZones, TemplateFragment
│   │
│   ├── candidate_mining.py           # Enrichi avec zone awareness
│   ├── doc_context_extractor.py      # Orchestration mise à jour
│   ├── prompts.py                    # Prompt production-grade
│   └── models.py                     # MarkerCandidate enrichi
```

---

## 4. Composants détaillés

### 4.1 Zone Segmenter

**Responsabilité** : Segmenter chaque page en zones logiques.

**Zones définies** (agnostiques) :
- `TOP_ZONE` : Premières lignes textuelles significatives
- `MAIN_ZONE` : Corps du contenu
- `BOTTOM_ZONE` : Dernières lignes textuelles significatives

**Règles de segmentation** :
```python
@dataclass
class ZoneConfig:
    top_lines_count: int = 3          # Lignes considérées comme TOP
    bottom_lines_count: int = 3       # Lignes considérées comme BOTTOM
    min_line_length: int = 5          # Ignorer lignes < N chars
    ignore_pure_numbers: bool = True  # Ignorer numéros de page
```

**Interface** :
```python
class ZoneSegmenter:
    def segment_page(self, page_text: str) -> PageZones:
        """
        Segmente une page en zones.

        Returns:
            PageZones avec top_lines, main_lines, bottom_lines
        """

    def segment_document(self, pages: List[str]) -> List[PageZones]:
        """Segmente toutes les pages d'un document."""
```

**Modèle de sortie** :
```python
@dataclass
class PageZones:
    page_index: int
    top_lines: List[str]
    main_lines: List[str]
    bottom_lines: List[str]

    def get_zone_for_position(self, line_index: int) -> str:
        """Retourne 'top', 'main', ou 'bottom'."""
```

### 4.2 Template Detector

**Responsabilité** : Identifier les fragments répétitifs inter-pages.

**Principe** : Un fragment est "template-like" si :
- Il apparaît sur une majorité de pages
- Dans la même zone relative
- Avec très peu de variation textuelle

**Algorithme** :
```python
class TemplateDetector:
    def __init__(
        self,
        min_pages_ratio: float = 0.5,      # Présent sur 50%+ des pages
        similarity_threshold: float = 0.9,  # Similarité textuelle
        zone_consistency_threshold: float = 0.8,  # Même zone 80%+ du temps
    ):
        pass

    def detect_templates(
        self,
        pages_zones: List[PageZones]
    ) -> List[TemplateFragment]:
        """
        Détecte les fragments template/boilerplate.

        Algorithm:
        1. Normaliser chaque ligne (lowercase, chiffres masqués, espaces compressés)
        2. Grouper par similarité (clustering)
        3. Calculer pages_covered_ratio par cluster
        4. Calculer zone_consistency par cluster
        5. Retourner fragments avec template_likelihood > threshold
        """
```

**Modèle de sortie** :
```python
@dataclass
class TemplateFragment:
    normalized_text: str
    original_samples: List[str]
    pages_covered: List[int]
    pages_covered_ratio: float
    dominant_zone: str  # 'top', 'main', 'bottom'
    zone_consistency: float
    template_likelihood: float

    def contains_value(self, value: str) -> bool:
        """Vérifie si ce template contient une valeur donnée."""
```

**Normalisation** :
```python
def normalize_for_template_matching(text: str) -> str:
    """
    Normalisation agnostique pour détection de répétition.

    - lowercase
    - chiffres → '#'
    - espaces multiples → single space
    - ponctuation normalisée
    """
    text = text.lower()
    text = re.sub(r'\d+', '#', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text
```

### 4.3 MarkerCandidate enrichi

**Contrat cible** (production) :

```python
from enum import Enum

class StructuralConfidence(Enum):
    """Niveau de confiance structurelle du document."""
    HIGH = "high"      # >= 5 pages, signaux clairs
    MEDIUM = "medium"  # 3-4 pages, signaux partiels
    LOW = "low"        # 1-2 pages, peu de signal statistique

@dataclass
class MarkerCandidate:
    # === Identité ===
    value: str
    lexical_shape: str  # numeric_4, alphanumeric, semantic_token (JAMAIS pour inférer sens)

    # === Distribution ===
    occurrences_total: int
    pages_covered: int
    pages_covered_ratio: float

    # === Zones (NOUVEAU) ===
    zone_distribution: Dict[str, int]  # {'top': 0, 'main': 5, 'bottom': 68}
    dominant_zone: str  # 'top', 'main', 'bottom'
    positional_stability: float  # 0.0-1.0 (apparaît toujours même zone)

    # === Template detection (NOUVEAU) ===
    template_likelihood: float  # 0.0-1.0
    is_in_template_fragment: bool

    # === Evidence ===
    evidence_samples: List[EvidenceSample]  # Max 5, avec zone + page

    # === Linguistic cues (NOUVEAU) ===
    contextual_cues: ContextualCues

    # === Structural confidence (NOUVEAU - Review ChatGPT) ===
    structural_confidence: StructuralConfidence

@dataclass
class EvidenceSample:
    page: int
    zone: str  # 'top', 'main', 'bottom'
    text: str  # 20-120 chars

@dataclass
class ContextualCues:
    scope_language_score: float    # 0.0-1.0 (version, release, as of...)
    legal_language_score: float    # 0.0-1.0 (©, all rights reserved...)
    contrast_language_score: float # 0.0-1.0 (vs, unlike, compared to...)
```

### 4.4 Linguistic Cue Detector

**Responsabilité** : Scorer la présence de patterns linguistiques universels autour d'un candidat.

**Patterns agnostiques** :

```python
# Scope language (indique un marqueur de contexte)
SCOPE_LANGUAGE_PATTERNS = [
    r'\b(?:version|release|edition|revision)\b',
    r'\b(?:as\s+of|from|since|starting)\b',
    r'\b(?:applies?\s+to|valid\s+for|available\s+in)\b',
    r'\b(?:new\s+in|introduced\s+in|added\s+in)\b',
    r'\b(?:removed\s+in|deprecated|obsolete)\b',
]

# Legal language (indique du template/boilerplate)
LEGAL_LANGUAGE_PATTERNS = [
    r'©|®|™',
    r'\ball\s+rights\s+reserved\b',
    r'\bcopyright\b',
    r'\bconfidential\b',
    r'\btrademark\b',
    r'\blegal\s+notice\b',
    r'\bproprietary\b',
]

# Contrast language (indique comparaison = potentiellement MIXED)
CONTRAST_LANGUAGE_PATTERNS = [
    r'\bvs\.?\b',
    r'\bversus\b',
    r'\bunlike\b',
    r'\bcompared\s+(?:to|with)\b',
    r'\bin\s+contrast\b',
]
```

**Interface** :
```python
class LinguisticCueDetector:
    def score_context(
        self,
        text: str,  # Evidence text around candidate
    ) -> ContextualCues:
        """
        Score les patterns linguistiques dans le contexte.

        Returns:
            ContextualCues avec scores 0.0-1.0
        """
```

---

## 5. LLM Validation (Production-grade)

### 5.1 Nouveau rôle du LLM

En production, le LLM **ne doit jamais** :
- "Deviner" qu'un nombre est une version
- Décider sans evidence structurelle
- Inférer un sens métier

Le LLM **doit uniquement** :
1. **Classer** un candidat en : `CONTEXT_SETTING`, `TEMPLATE_NOISE`, `AMBIGUOUS`
2. **Justifier** sa décision par les features fournies
3. **Refuser** s'il n'a pas assez d'éléments

### 5.2 Prompt production-grade

```
You are validating document context markers.

A context marker is a token that meaningfully differentiates this document
as a specific variant or edition of the same informational artifact.

## Principles (domain-agnostic)

- Do NOT assume any industry or domain meaning.
- Repeated boilerplate, legal notices, branding, or template text
  must be classified as TEMPLATE_NOISE, even if they contain numbers or years.
- A marker is CONTEXT_SETTING only if it appears in the document's
  main subject (title, headings, revision section, or main content)
  and is NOT dominated by template characteristics.

## Decision rules

For each candidate, you receive:
- zone_distribution: where it appears (top/main/bottom zones)
- positional_stability: how consistently it appears in the same zone
- template_likelihood: probability this is template/boilerplate content
- evidence_samples: text excerpts with zone and page
- contextual_cues: linguistic pattern scores (scope/legal/contrast)

Apply these rules:
1. If structural_confidence = LOW → max confidence = 0.6 (never strong decisions)
2. HIGH template_likelihood (>0.7) + bottom zone dominance → TEMPLATE_NOISE
3. HIGH legal_language_score (>0.5) + HIGH positional_stability → TEMPLATE_NOISE
4. CONTEXT_SETTING requires evidence from title, heading, or main body
   WITH scope_language_score > 0.3 AND template_likelihood < 0.5
5. Repeated fragments in MAIN_ZONE with scope_language_score > 0.3 → NOT template
6. If structural signals weak or conflicting → AMBIGUOUS (never guess)

## Output format (strict JSON)

{
  "markers": [
    {
      "value": "...",
      "category": "CONTEXT_SETTING|TEMPLATE_NOISE|AMBIGUOUS",
      "confidence": 0.0-1.0,
      "justification": "Brief explanation based on provided features",
      "evidence_used": "Quote from evidence_samples that supports decision"
    }
  ],
  "doc_scope": "GENERAL|VARIANT_SPECIFIC|MIXED",
  "scope_confidence": 0.0-1.0
}
```

### 5.3 Exemple de classification attendue

**Input candidats** :
```json
{
  "candidates": [
    {
      "value": "1809",
      "zone_distribution": {"top": 2, "main": 15, "bottom": 0},
      "positional_stability": 0.3,
      "template_likelihood": 0.1,
      "evidence_samples": [
        {"page": 0, "zone": "top", "text": "Business Scope Release 1809"}
      ],
      "contextual_cues": {
        "scope_language_score": 0.9,
        "legal_language_score": 0.0,
        "contrast_language_score": 0.0
      }
    },
    {
      "value": "2019",
      "zone_distribution": {"top": 0, "main": 0, "bottom": 68},
      "positional_stability": 0.98,
      "template_likelihood": 0.95,
      "evidence_samples": [
        {"page": 3, "zone": "bottom", "text": "© 2019 SAP SE... All rights reserved"}
      ],
      "contextual_cues": {
        "scope_language_score": 0.0,
        "legal_language_score": 0.95,
        "contrast_language_score": 0.0
      }
    }
  ]
}
```

**Output attendu** :
```json
{
  "markers": [
    {
      "value": "1809",
      "category": "CONTEXT_SETTING",
      "confidence": 0.95,
      "justification": "Appears in top/main zones with high scope_language_score, low template_likelihood",
      "evidence_used": "Business Scope Release 1809"
    },
    {
      "value": "2019",
      "category": "TEMPLATE_NOISE",
      "confidence": 0.98,
      "justification": "100% bottom zone, 98% positional stability, 95% legal language, clear copyright boilerplate",
      "evidence_used": "© 2019 SAP SE... All rights reserved"
    }
  ],
  "doc_scope": "VARIANT_SPECIFIC",
  "scope_confidence": 0.95
}
```

---

## 6. Intégration avec composants existants

### 6.1 Réutilisation du Gating V4

Le Gating V4 calcule déjà des signaux utiles par page :
- `TFS` (Text Fragmentation Score)
- `SDS` (Spatial Dispersion Score)
- `VTS` (Visual Table Score)

**Intégration** :
- Fragment à faible SDS + haute répétition → template très probable
- Fragment à haute dispersion → contenu principal

### 6.2 Enrichissement du cache V2

Le cache `*.v2cache.json` doit inclure les nouvelles données :

```json
{
  "doc_context": {
    "structural_analysis": {
      "pages_zones": [...],
      "template_fragments": [...],
      "zone_statistics": {...}
    },
    "strong_markers": [...],
    "weak_markers": [...],
    ...
  }
}
```

---

## 7. Plan d'implémentation

### Phase 1 : Infrastructure structurelle (PR5) ✅ DONE
- [x] `ZoneSegmenter` avec tests
- [x] `TemplateDetector` avec tests
- [x] Modèles `PageZones`, `TemplateFragment`
- [x] Intégration dans pipeline extraction

### Phase 2 : Enrichissement candidats (PR6) ✅ DONE
- [x] `MarkerCandidate` enrichi (zone_distribution, template_likelihood, etc.)
- [x] `LinguisticCueDetector` (scope_language, legal_language, contrast_language)
- [x] `EvidenceSample` avec zone/page
- [x] Mise à jour `CandidateMiner` avec `enrich_candidates_with_structural_analysis()`

### Phase 3 : LLM Validation (PR7) ✅ DONE
- [x] Nouveau prompt production-grade dans `prompts.py`
- [x] CandidateGate avec 10+ filtres universels
- [x] Validation sur corpus varié

---

## 8. Critères de succès

### 8.1 Cas de test obligatoires

| Document | Marker | Attendu | Justification |
|----------|--------|---------|---------------|
| SAP 1809 deck | `1809` | CONTEXT_SETTING | Titre, scope language |
| SAP 1809 deck | `2019` | TEMPLATE_NOISE | Footer répétitif, legal |
| Generic whitepaper | `2024` (publication) | TEMPLATE_NOISE | Footer/header répétitif |
| Generic whitepaper | `v3.2` (version) | CONTEXT_SETTING | Titre, scope language |
| Legal doc "Copyright Act 2019" | `2019` | CONTEXT_SETTING | Titre, main content |

### 8.2 Métriques

| Métrique | Cible |
|----------|-------|
| Faux positifs template → context | < 5% |
| Faux négatifs context → template | < 2% |
| Temps ajouté par document | < 100ms |

---

## 9. Conséquences

### 9.1 Positives
- **Agnosticisme renforcé** : Aucune règle métier, uniquement structure universelle
- **Robustesse** : Détection automatique de nouveaux patterns de template
- **Explicabilité** : Chaque décision LLM justifiée par features objectives
- **Évolutivité** : Nouvelles features ajoutables sans casser le contrat

### 9.2 Négatives
- **Complexité accrue** : Nouveau module à maintenir
- **Latence légère** : +50-100ms par document
- **Cache invalidation** : Les caches V2 existants devront être régénérés

### 9.3 Risques
- **Edge cases** : Documents très courts (1-2 pages) = moins de signal de répétition
- **Formats exotiques** : Documents sans structure claire (images, scans)

---

## 10. Références

- ADR_ASSERTION_AWARE_KG.md (PR1-4)
- OSMOSE_COGNITIVE_MATURITY.md
- Discussion Claude × ChatGPT (Janvier 2026)

---

*Ce document sera mis à jour après validation et implémentation de chaque phase.*
