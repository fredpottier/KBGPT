# OSMOSIS Extraction V2 - Décisions d'architecture consolidées

**Date:** 2026-01-02
**Status:** ✅ VALIDÉ - Prêt pour implémentation
**Source:** Revue critique Claude + Arbitrage ChatGPT

---

## 🎯 Principe directeur

> **Vision observe. Vision décrit. OSMOSE raisonne.**

---

## ✅ Décision 1 : Interface de sortie V2 → OSMOSE

### Le problème résolu
OSMOSE est **text-centric**, la V2 est **structure-centric**.

### La solution : Sortie bi-couche

```python
@dataclass
class ExtractionResult:
    """Interface de sortie V2 vers OSMOSE."""

    # 🔹 Couche compatibilité (obligatoire) - consommée par OSMOSE
    full_text: str  # Texte linéarisé avec marqueurs structurels

    # 🔹 Couche structure enrichie (pour futur, audit, UI)
    structure: DocumentOutput  # Structure complète préservée

    # 🔹 Index de provenance
    page_index: List[PageIndex]  # Mapping offsets texte → pages/slides
```

### Format de linéarisation

Le `full_text` est linéarisé **avec marqueurs explicites** :

```
[PAGE 6 | TYPE=ARCHITECTURE_DIAGRAM]
[TITLE level=1] Target Architecture Overview

[TABLE_START id=tbl_1]
| Component | Role |
| SAP BTP   | Integration Platform |
[TABLE_END]

[VISUAL_ENRICHMENT id=vision_6_1 confidence=0.82]
diagram_type: architecture_diagram

visible_elements:
- [E1|box] "SAP Enterprise Cloud Services"
- [E2|box] "Customer"

visible_relations (visual only):
- [E1] -> [E2]
  relation: connected
  evidence: line/arrow
  direction: unclear

ambiguities:
- arrow direction between E1 and E2 is not readable
[END_VISUAL_ENRICHMENT]

[PARAGRAPH]
This architecture enables seamless integration between...
```

### Règles de linéarisation

| Élément | Marqueur | Exemple |
|---------|----------|---------|
| Page/Slide | `[PAGE n]` | `[PAGE 6]` |
| Titre | `[TITLE level=n]` | `[TITLE level=1] Overview` |
| Paragraphe | `[PARAGRAPH]` | `[PARAGRAPH] Text...` |
| Table | `[TABLE_START id=x]...[TABLE_END]` | Markdown table |
| Vision | `[VISUAL_ENRICHMENT]...[END_VISUAL_ENRICHMENT]` | Format descriptif |

### Spécification des marqueurs (BNF simplifié)

```bnf
marker       ::= '[' marker_type attributes? ']'
marker_type  ::= 'PAGE' | 'TITLE' | 'PARAGRAPH' | 'TABLE_START' | 'TABLE_END'
               | 'VISUAL_ENRICHMENT' | 'END_VISUAL_ENRICHMENT'
attributes   ::= (key '=' value)+
key          ::= [a-z_]+
value        ::= [a-zA-Z0-9_.-]+

# Exemples valides:
# [PAGE 6]
# [TITLE level=1]
# [TABLE_START id=tbl_1]
# [VISUAL_ENRICHMENT id=vision_6_1 confidence=0.82]
```

**Règles de parsing:**
- Les marqueurs sont **toujours sur une ligne dédiée** (sauf `[PARAGRAPH]`)
- Regex de détection : `^\[(PAGE|TITLE|TABLE_START|TABLE_END|VISUAL_ENRICHMENT|END_VISUAL_ENRICHMENT)[^\]]*\]`
- Les attributs sont optionnels sauf `id` pour `TABLE_START` et `VISUAL_ENRICHMENT`

### Ce qui est interdit

- ❌ Injecter `DocumentOutput` directement dans TopicSegmenter
- ❌ Forcer OSMOSE à comprendre des bounding boxes
- ❌ Perdre le lien texte ↔ page ↔ vision

---

## ✅ Décision 2 : Domain Context unique

### Le problème résolu
Risque de double système DomainContext (existant vs V2).

### La solution : Réutiliser l'existant + Adaptateur

```python
def get_domain_context_for_vision(tenant_id: str) -> VisionDomainContext:
    """
    Adaptateur : DomainContextStore → VisionDomainContext.
    Une seule source de vérité.
    """
    profile = get_domain_context_store().get_profile(tenant_id)

    return VisionDomainContext(
        name=profile.industry,
        interpretation_rules=profile.interpretation_rules or [],
        vocabulary=profile.common_acronyms or {},
        key_concepts=profile.key_concepts or [],
        extraction_focus=profile.extraction_focus or ""
    )
```

### Règles

- ✅ `DomainContextStore` reste la source unique
- ✅ Vision **consomme** le contexte, ne le **définit** pas
- ❌ Pas de YAML spécifique Vision
- ❌ Pas de logique métier en dur dans les prompts Vision

---

## ✅ Décision 3 : Vision alimente OSMOSE (clarification majeure)

### Le problème résolu
"Vision ne doit pas alimenter OSMOSE" était **trop strict**.

### La vérité nuancée

> Vision PEUT alimenter le texte OSMOSE, **sous forme descriptive, factuelle et traçable**.

### Deux sorties Vision distinctes

| Sortie | Format | Usage |
|--------|--------|-------|
| `VisionExtraction` | JSON structuré | KG direct (relations visuelles) |
| `vision_text` | Texte balisé | Injection dans `full_text` pour OSMOSE |

### Format `vision_text` (pour OSMOSE)

```
=== VISUAL_ENRICHMENT | PAGE 6 | confidence=0.82 ===
diagram_type: architecture_diagram

visible_elements:
- [E1|box] "SAP Enterprise Cloud Services"
- [E2|box] "Customer"

visible_relations (visual only):
- [E1] -> [E2]
  relation: connected
  evidence: line/arrow

ambiguities:
- arrow direction unclear
=== END_VISUAL_ENRICHMENT ===
```

### Règle d'or

```
✅ Vision → description factuelle → texte OSMOSE
❌ Vision → interprétation métier → texte "naturel" → OSMOSE
```

### Vers le Knowledge Graph

| Source | Nature | Confiance |
|--------|--------|-----------|
| Vision | Relation visuelle explicite | Forte (evidence-based) |
| OSMOSE | Relation sémantique inférée | Probabiliste |

Deux pipelines parallèles :
- `texte → OSMOSE → relations sémantiques`
- `vision → relations visuelles (VISUAL_FLOW, etc.)`

---

## ✅ Décision 4 : Formats supportés (MISE À JOUR 2026-01-02)

### Clarification importante

**Docling supporte officiellement PPTX** (format Office Open XML).
Documentation officielle Docling : PDF, DOCX, XLSX, **PPTX**, Markdown, AsciiDoc, HTML, Images, WebVTT.

👉 **Décision révisée** : Docling devient le point d'entrée **unifié** pour tous les formats Office.

### Règle impérative

> Si le format ne peut pas contenir de structure visuelle porteuse de sens,
> la Vision doit être **explicitement bypassée**.

### Mapping Format → Pipeline (UNIFIÉ)

```
PDF / DOCX / PPTX / XLSX (formats Office)
 ├─ Docling (texte + tables + structure + shapes)
 ├─ Vision Gating V4 (page/slide-level)
 └─ Vision (si VISION_REQUIRED)

Images (PNG, JPEG, TIFF, BMP, WEBP)
 ├─ Docling (OCR si texte détectable)
 └─ Vision direct (toujours)

Markdown / AsciiDoc / HTML / CSV / WebVTT
 └─ Docling (structure uniquement)
 └─ ❌ Vision INTERDITE
```

### Avantages de l'approche unifiée

- ✅ **Un seul extracteur** : DoclingExtractor pour tous les formats Office
- ✅ **Moins de code spécifique** : pas de branche python-pptx vs Docling
- ✅ **Cohérence garantie** : même structure de sortie quel que soit le format
- ✅ **Maintenance simplifiée** : un seul point d'entrée à maintenir

---

## ✅ Décision 5 : Extraction unifiée via Docling (RÉVISÉE)

### Contexte
La recommandation antérieure d'utiliser `python-pptx` séparément était une **proposition pragmatique**
dans un contexte où le support PPTX de Docling n'était pas confirmé.

**Docling supporte officiellement PPTX** → cette décision est révisée.

### La solution unifiée

```
Tous formats Office → Docling → VisionUnit → Vision Gating → Vision (si requis)
```

### VDS : détection des shapes/connecteurs

À vérifier lors de Phase 0 : comment Docling expose les shapes/drawings pour PPTX.

Options :
1. **Docling expose les shapes** → utiliser directement `visual_elements[]` de Docling
2. **Fallback python-pptx** → si Docling n'expose pas les connecteurs

```python
# Option Fallback : Détection connecteurs via python-pptx (si nécessaire)
from pptx.enum.shapes import MSO_SHAPE_TYPE

def count_connectors_fallback(slide) -> int:
    count = 0
    for shape in slide.shapes:
        if shape.shape_type in (MSO_SHAPE_TYPE.LINE, MSO_SHAPE_TYPE.CONNECTOR):
            count += 1
    return count
```

---

## ✅ Décision 6 : VDS (Vector Drawing Signal) - Approche unifiée

### Stratégie

1. **Priorité : sortie Docling** → utiliser `visual_elements[]` si disponible
2. **Fallback format-spécifique** → si Docling ne fournit pas assez de détails

### Sources par format

| Format | Source primaire | Fallback |
|--------|-----------------|----------|
| PDF | Docling `visual_elements[]` | PyMuPDF `page.get_drawings()` |
| PPTX | Docling `visual_elements[]` | python-pptx `MSO_SHAPE_TYPE` |
| DOCX/XLSX | Docling uniquement | N/A |

### Note Phase 0

Tester si Docling expose :
- [ ] Nombre de shapes/drawings
- [ ] Type (rectangle, ligne, connecteur, flèche)
- [ ] Bounding boxes
- [ ] Connecteurs distincts des shapes simples

---

## ✅ Décision 7 : Seuils expérimentaux

### Marquage explicite

```python
# Seuils à calibrer sur corpus réel
DEFAULT_EXPERIMENTAL_THRESHOLDS = {
    "SDS_HIGH": 0.08,
    "SDS_MEDIUM": 0.04,
    "TFS_HIGH_RATIO": 0.75,
    "TFS_MIN_BLOCKS": 12,
    # TODO: Calibration Phase 2
}
```

### TODO
- [ ] Annoter 50 pages manuellement
- [ ] Calculer signaux
- [ ] Optimiser seuils

---

## ✅ Décision 8 : VTS (Visual Table Signal)

### Règle

```python
def compute_visual_table_signal(unit) -> float:
    # Si Docling a déjà reconnu la table → pas besoin de Vision
    if unit.has_structured_tables:
        return 0.0

    # VTS réservé aux pseudo-tables graphiques
    return detect_visual_grid_pattern(unit)
```

---

## ✅ Décision 9 : Structured Merge

### Règle d'or

> **Vision n'écrase JAMAIS Docling/python-pptx.**

### Stratégie de merge

```python
@dataclass
class MergedPageOutput:
    page_index: int

    # Socle (Docling ou python-pptx)
    base_blocks: List[TextBlock]
    base_tables: List[Table]

    # Enrichissement Vision (attaché, pas fusionné)
    vision_enrichment: Optional[VisionExtraction] = None

    # Provenance
    provenance: MergeProvenance
```

### Attachement Vision → Base

1. Par `page_index` / `slide_index` (obligatoire)
2. Par `bbox overlap` (optionnel, pour précision)
3. Marquage explicite `source: "docling" | "vision"`

---

## ✅ Décision 10 : Cache versionné

### Format

```json
{
  "cache_version": "v2",
  "created_at": "2026-01-02T14:30:00Z",
  "extraction": {
    "full_text": "...",
    "structure": { ... },
    "page_index": [ ... ]
  },
  "gating_decisions": [ ... ],
  "vision_results": [ ... ]
}
```

### Invalidation

```python
CURRENT_CACHE_VERSION = "v2"

def is_cache_valid(cache_data: dict) -> bool:
    return cache_data.get("cache_version") == CURRENT_CACHE_VERSION
```

---

## 📋 Checklist pré-implémentation (mise à jour)

Tous les bloquants sont levés :

- [x] Interface V2 → OSMOSE : `ExtractionResult` bi-couche
- [x] DomainContext : réutiliser existant + adaptateur
- [x] Vision → OSMOSE : via `vision_text` descriptif
- [x] Formats : mapping clair, Vision limitée
- [x] PPTX : python-pptx (pas Docling)
- [x] VDS PPTX : MSO_SHAPE_TYPE
- [x] Structured Merge : règles définies
- [x] Cache : versionné

---

## 🚀 Prêt pour implémentation

L'architecture est **validée et complète**.

### Ordre d'implémentation avec dépendances

```
Phase 1: Modèles de données ──────────┐
         (ExtractionResult,           │
          VisionUnit, etc.)           │
              │                       │
              ▼                       │
Phase 2: Extracteurs ─────────────────┼──► DÉPENDANCE STRICTE
         (Docling PDF,                │    Phase 1 DOIT être gelée
          python-pptx PPTX)           │    avant Phase 3
              │                       │
              ▼                       │
Phase 3: Vision Gating V4 ◄───────────┘
         (signaux + engine)
              │
              ▼
Phase 4: Vision Path
         (prompt + adaptateur DomainContext)
              │
              ▼
Phase 5: Merge + Linéarisation
              │
              ▼
Phase 6: Intégration pipeline OSMOSE
              │
              ▼
Phase 7: Tests + Calibration seuils
```

### ⚠️ Contrainte critique

> **Phase 1 (modèles) DOIT être gelée avant de commencer Phase 3 (Gating).**

Pourquoi ? Tous les signaux, décisions et merges dépendent des modèles.
Changer les modèles après Phase 3 coûte très cher.

### Risques résiduels acceptés

| Risque | Niveau | Mitigation |
|--------|--------|------------|
| Calibration des signaux | 🟡 Normal | Itération sur corpus réel |
| Qualité Vision sur schémas denses | 🟡 Normal | Ambiguïtés + confidence |
| Volume de `full_text` augmenté | 🟢 Faible | Bon compromis actuel |
