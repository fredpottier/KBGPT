# ADR: Pass 0.9 - Global View Construction

**Status**: ACCEPTED
**Date**: 2026-01-25
**Auteurs**: OSMOSE Team
**Contexte**: Pipeline V2 - Lecture Stratifiée

---

## 1. Contexte et Problème

### 1.1 Diagnostic

Le Pipeline V2 Stratifié a l'architecture conceptuelle correcte (top-down) mais souffre d'un **déficit de représentation globale** :

| Phase | Contenu passé au LLM | Document 468K chars | Couverture |
|-------|---------------------|---------------------|------------|
| Pass 1.1 (DocumentAnalyzer) | 4000 chars | Pages 1-2 | **0.85%** |
| Pass 1.2 (ConceptIdentifier) | 5000 chars | Pages 1-3 | **1.07%** |

**Conséquence mesurée** sur `020_RISE_with_SAP_Cloud_ERP_Private_full.pdf` (230 pages) :

| Métrique | Obtenu | Attendu | Ratio |
|----------|--------|---------|-------|
| Thèmes | 7 | 20-30 | 23% |
| Concepts | 5 | 30-50 | 10% |
| Informations | 53 | 200-400 | 13% |

### 1.2 Cause Racine

> **Le pipeline V2 est conceptuellement top-down, mais opérationnellement myope.**

La "lecture globale" n'est pas une lecture - c'est un échantillon arbitraire des 2 premières pages. Le LLM n'a aucune visibilité sur :
- Les concepts introduits après la page 3
- Les thèmes développés dans le corps du document
- Les exceptions, limitations, annexes critiques

### 1.3 Principe ADR Violé

L'ADR V2 implicite stipule :

> **Le LLM doit disposer d'une représentation couvrant l'ensemble du document, même compressée.**

Le contrat réel est :
- ❌ Lire exhaustivement → impossible (limite tokens)
- ❌ Échantillonner naïvement → faux signal
- ✅ **Construire une vue globale synthétique mais couvrante**

---

## 2. Décision

### 2.1 Solution Adoptée

**Implémenter Pass 0.9 "Global View Construction"** entre Pass 0 (Structural Graph) et Pass 1.1 (Document Analysis).

Cette phase construit un **meta-document** qui :
- Couvre **100% des sections** du document
- Préserve la **structure hiérarchique**
- Respecte une **limite de tokens** compatible LLM (15-25K chars)

### 2.2 Options Évaluées

| Option | Description | Verdict |
|--------|-------------|---------|
| **A - Résumé dense hiérarchique** | Résumé par section → compression → meta-document | ✅ **ADOPTÉ** |
| B - Map/Reduce concepts | Extraction candidats per-chunk → fusion | ⚠️ Retour masqué au bottom-up |
| C - TOC + échantillonnage | TOC + 1000 chars par section | ⚠️ Bootstrap uniquement |
| D - Vision multi-page | Images PDF → GPT-4o Vision | ❌ Hors-scope, coûteux |

**Décision finale** : Option A comme fondation, Option C comme accélérateur/fallback.

---

## 3. Spécification Technique

### 3.1 Architecture Pass 0.9

```
┌─────────────────────────────────────────────────────────────────┐
│                     PASS 0.9 - GLOBAL VIEW                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Pass 0 Output (Cache v5)                                       │
│  ├── sections: List[Section]     (432 sections)                │
│  ├── doc_items: List[DocItem]    (6743 items)                  │
│  └── chunks: List[Chunk]         (1030 chunks)                 │
│                                                                 │
│                          ↓                                      │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ÉTAPE 1: Section Summarization (parallèle)              │   │
│  │                                                         │   │
│  │  Pour chaque section:                                   │   │
│  │  - Input: texte section (ou chunks de la section)      │   │
│  │  - Output: résumé 500-1000 chars                       │   │
│  │  - Contenu: sujets, concepts évoqués, type assertions  │   │
│  │                                                         │   │
│  │  Budget: ~500 tokens input + 200 output par section    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ÉTAPE 2: Hierarchical Compression                       │   │
│  │                                                         │   │
│  │  - Concaténation structurée des résumés                │   │
│  │  - Préservation hiérarchie (H1 > H2 > H3)             │   │
│  │  - Output: meta-document 15-25K chars                  │   │
│  │                                                         │   │
│  │  Format:                                                │   │
│  │  # Section 1: [titre]                                  │   │
│  │  [résumé 500-1000 chars]                               │   │
│  │  ## Section 1.1: [titre]                               │   │
│  │  [résumé]                                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ OUTPUT: GlobalView                                      │   │
│  │                                                         │   │
│  │  - meta_document: str (15-25K chars)                   │   │
│  │  - section_summaries: Dict[section_id, summary]        │   │
│  │  - coverage_stats: {sections_covered, chars_original}  │   │
│  │  - toc_enhanced: str (TOC + résumés inline)           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                          ↓
              Pass 1.1 utilise meta_document
              Pass 1.2 utilise meta_document + section_summaries
```

### 3.2 Intégration dans le Pipeline

```
Pass 0 (Structural Graph)
    ↓
Pass 0.9 (Global View Construction)  ← NOUVEAU
    ↓
Pass 1.1 (Document Analysis) - utilise GlobalView.meta_document
    ↓
Pass 1.2 (Concept Identification) - utilise GlobalView.meta_document
    ↓
Pass 1.3 (Assertion Extraction) - inchangé (per-chunk)
    ↓
Pass 1.4 (Promotion + Anchoring) - inchangé
```

### 3.3 Modèle de Données

```python
@dataclass
class SectionSummary:
    """Résumé d'une section du document."""
    section_id: str
    section_title: str
    level: int  # 1=H1, 2=H2, etc.
    summary: str  # 500-1000 chars
    concepts_mentioned: List[str]  # Concepts détectés
    assertion_types: List[str]  # Types d'assertions présentes
    char_count_original: int
    char_count_summary: int

@dataclass
class GlobalView:
    """Vue globale construite du document."""
    tenant_id: str
    doc_id: str

    # Meta-document pour LLM
    meta_document: str  # 15-25K chars, structuré

    # Détails par section
    section_summaries: Dict[str, SectionSummary]

    # Table des matières enrichie
    toc_enhanced: str

    # Statistiques de couverture
    coverage: GlobalViewCoverage

    # Métadonnées
    created_at: datetime
    llm_model_used: str
    total_llm_calls: int
    total_tokens_used: int

@dataclass
class GlobalViewCoverage:
    """Statistiques de couverture."""
    sections_total: int
    sections_summarized: int
    sections_skipped: int  # Trop courts, vides
    chars_original: int
    chars_meta_document: int
    compression_ratio: float  # chars_meta / chars_original
```

### 3.4 Prompt de Résumé de Section

```yaml
section_summary:
  system: |
    Tu es un expert en analyse documentaire pour OSMOSE.
    Tu dois produire un résumé INFORMATIF d'une section de document.

    RÈGLES:
    - Maximum 800 caractères
    - Identifier les CONCEPTS clés mentionnés
    - Noter les TYPES d'informations (définitions, règles, faits, procédures)
    - Préserver les VALEURS spécifiques (versions, pourcentages, limites)
    - NE PAS interpréter, seulement résumer fidèlement

  user: |
    SECTION: {section_title}
    NIVEAU: {level} (1=chapitre principal, 2=sous-section, etc.)

    CONTENU:
    {section_text}

    Réponds avec ce JSON:
    ```json
    {
      "summary": "Résumé de la section (max 800 chars)",
      "concepts": ["concept1", "concept2"],
      "assertion_types": ["definitional", "prescriptive", "factual"],
      "key_values": ["TLS 1.2", "99.95%", "30 days"]
    }
    ```
```

### 3.5 Estimation Budget LLM

Pour un document de 230 pages / 432 sections :

| Phase | Appels LLM | Tokens In | Tokens Out | Total |
|-------|------------|-----------|------------|-------|
| Section summarization | ~50-100 | ~500/appel | ~200/appel | 35-70K |
| (sections vides/courtes skip) | | | | |

**Coût estimé** (vLLM local) : ~0$ (gratuit)
**Coût estimé** (GPT-4o-mini) : ~$0.02-0.05 par document
**Temps estimé** : 30-60 secondes (parallélisé)

---

## 4. Garde-fous

### 4.1 Couverture Minimum

```python
MINIMUM_COVERAGE_RATIO = 0.95  # 95% des sections doivent être résumées

def validate_coverage(global_view: GlobalView) -> bool:
    ratio = global_view.coverage.sections_summarized / global_view.coverage.sections_total
    return ratio >= MINIMUM_COVERAGE_RATIO
```

### 4.2 Taille Meta-Document

```python
META_DOCUMENT_MIN_CHARS = 5000   # Minimum pour document court
META_DOCUMENT_MAX_CHARS = 30000  # Maximum pour éviter dépassement contexte LLM
META_DOCUMENT_TARGET = 20000    # Cible optimale

def validate_meta_document_size(meta_doc: str) -> bool:
    return META_DOCUMENT_MIN_CHARS <= len(meta_doc) <= META_DOCUMENT_MAX_CHARS
```

### 4.3 Fallback Mode (Option C)

Si le budget LLM est dépassé ou en cas d'erreur :

```python
def fallback_global_view(sections: List[Section], toc: str) -> GlobalView:
    """
    Fallback: TOC + premiers 1000 chars de chaque section.
    Moins précis mais garantit une couverture.
    """
    summaries = {}
    for section in sections:
        summaries[section.id] = SectionSummary(
            section_id=section.id,
            section_title=section.title,
            summary=section.text[:1000] + "..." if len(section.text) > 1000 else section.text,
            concepts_mentioned=[],  # Non détectés en fallback
            assertion_types=[],
            ...
        )
    ...
```

---

## 5. Implémentation

### 5.1 Fichiers à Créer

```
src/knowbase/stratified/pass09/
├── __init__.py
├── global_view_builder.py    # Classe principale
├── section_summarizer.py     # Résumé LLM par section
├── hierarchical_compressor.py # Compression en meta-document
└── models.py                 # SectionSummary, GlobalView, etc.
```

### 5.2 Intégration Orchestrator

```python
# Dans Pass1OrchestratorV2.process()

# NOUVEAU: Pass 0.9 - Global View Construction
from knowbase.stratified.pass09 import GlobalViewBuilder

global_view_builder = GlobalViewBuilder(llm_client=self.llm_client)
global_view = global_view_builder.build(
    doc_id=doc_id,
    sections=pass0_result.sections,
    chunks=chunks,
    toc=toc_extracted
)

# Pass 1.1 utilise maintenant le meta-document
subject, themes, is_hostile = self.document_analyzer.analyze(
    doc_id=doc_id,
    doc_title=doc_title,
    content=global_view.meta_document,  # ← CHANGEMENT CLÉ
    toc=global_view.toc_enhanced
)

# Pass 1.2 utilise aussi le meta-document
concepts, refused = self.concept_identifier.identify(
    ...
    content=global_view.meta_document,  # ← CHANGEMENT CLÉ
    ...
)
```

---

## 6. Critères de Succès

### 6.1 Métriques Cibles

Pour `020_RISE_with_SAP_Cloud_ERP_Private_full.pdf` après implémentation :

| Métrique | Avant | Cible | Amélioration |
|----------|-------|-------|--------------|
| Thèmes | 7 | 15-25 | +200% |
| Concepts | 5 | 20-40 | +400% |
| Informations | 53 | 150-300 | +300% |
| Couverture document | 1% | 100% | +9900% |

### 6.2 Validation

1. **Test unitaire** : GlobalViewBuilder produit un meta-document valide
2. **Test intégration** : Pass 1.1/1.2 utilisent le meta-document
3. **Test E2E** : Reprocess du document RISE avec nouvelles métriques
4. **Comparaison** : Avant/après sur 3 documents représentatifs

---

## 7. Risques et Mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Résumés LLM de mauvaise qualité | Moyenne | Haut | Fallback Option C + validation |
| Dépassement budget tokens | Faible | Moyen | Limite sections, batching |
| Temps de traitement trop long | Faible | Moyen | Parallélisation agressive |
| Meta-document trop dense | Moyenne | Moyen | Compression adaptative |

---

## 8. Références

- `doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md` - Architecture V2
- `doc/ongoing/TRACKING_PIPELINE_V2.md` - Suivi implémentation
- `src/knowbase/stratified/pass0/` - Pass 0 existant
- `src/knowbase/stratified/pass1/` - Pass 1 existant

---

**Approuvé par** : OSMOSE Team
**Date d'implémentation prévue** : 2026-01-25
