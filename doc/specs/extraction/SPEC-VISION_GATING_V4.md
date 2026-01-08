# Vision Gating v4 — Spécification complète

**Date: 2026-01-02**
**Status: Prêt pour implémentation**

---

## 0. Objectif

Décider **de façon déterministe et explicable** si une page / slide / zone doit être analysée par un LLM Vision.

### Contraintes non négociables

* ❌ Pas de décision basée uniquement sur le volume de texte
* ❌ Pas de dépendance au format (PDF vs PPTX)
* ❌ Pas d'appel Vision "par sécurité"
* ✅ Support explicite :

  * images raster (PNG/JPG)
  * diagrammes en shapes (PPTX / PDF vectoriel)
  * tables visuelles non tabulaires
* ✅ Décision traçable (scores + raisons)

---

## 1. Unité de décision

Le gating s'applique à une **unit** parmi :

* `PDF_PAGE`
* `PPTX_SLIDE`
* `DOC_ZONE` (optionnel, futur)

Chaque unit est évaluée indépendamment.

---

## 2. Entrées du Vision Gating

Pour chaque unit, le gating consomme :

### 2.1 Données Docling (obligatoires)

* `blocks[]` (type, text_length, bbox)
* `tables[]` (structurées ou non)
* `visual_elements[]`

  * images raster
  * drawings vectoriels
  * bounding boxes
* `page_dimensions`

### 2.2 Métadonnées techniques

* format source (`PDF`, `PPTX`)
* index (page / slide)
* présence de notes (PPTX)

### 2.3 Domain Context (optionnel mais recommandé)

* règles d'interprétation
* vocabulaire
* **sert uniquement à pondérer certains seuils**, jamais à forcer Vision

---

## 3. Signaux structurels (features)

Chaque signal est **mesurable**, **local**, **sans LLM**.

### 3.1 Raster Image Signal (RIS)

Détecte les schémas sous forme d'images.

**Mesures**

* `num_large_images`
* `largest_image_area_ratio` (image_area / page_area)
* `image_contains_text` (OCR simple : oui/non)

**Score**

```text
RIS =
  1.0 if largest_image_area_ratio ≥ 0.30
  0.7 if largest_image_area_ratio ≥ 0.20
  0.4 if largest_image_area_ratio ≥ 0.10
  0.0 otherwise
```

---

### 3.2 Vector Drawing Signal (VDS)

Détecte les diagrammes en shapes (le point critique).

**Mesures**

* `num_drawings` (PDF: get_drawings, PPTX: shapes != picture)
* `num_connectors` (lignes / flèches)
* `drawing_area_ratio` (union bbox drawings / page_area)

**Score**

```text
VDS =
  1.0 if num_connectors ≥ 3 OR drawing_area_ratio ≥ 0.35
  0.7 if num_drawings ≥ 15
  0.4 if num_drawings ≥ 8
  0.0 otherwise
```

---

### 3.3 Text Fragmentation Signal (TFS)

Un diagramme en shapes contient **beaucoup de texte**, mais fragmenté.

**Mesures**

* `num_text_blocks`
* `avg_block_length`
* `short_block_ratio` (blocks < 200 chars)

**Score**

```text
TFS =
  1.0 if short_block_ratio ≥ 0.75 AND num_text_blocks ≥ 12
  0.6 if short_block_ratio ≥ 0.60
  0.0 otherwise
```

---

### 3.4 Spatial Dispersion Signal (SDS)

Mesure si le texte est **dispersé spatialement** (layout non linéaire).

**Mesures**

* variance des centres `(cx, cy)` des blocs
* entropy de distribution spatiale

**Score**

```text
SDS =
  1.0 if spatial_entropy ≥ HIGH
  0.5 if spatial_entropy ≥ MEDIUM
  0.0 otherwise
```

---

### 3.5 Visual Table Signal (VTS)

Tables "dessinées" ou pseudo-tables.

**Mesures**

* présence de grilles non reconnues comme table structurée
* alignements multiples texte + lignes

**Score**

```text
VTS =
  1.0 if visual_table_detected
  0.0 otherwise
```

---

## 4. Scoring global

Chaque unit reçoit un **Vision Need Score (VNS)**.

### Pondération par défaut

```text
VNS =
  0.30 * RIS +
  0.30 * VDS +
  0.15 * TFS +
  0.15 * SDS +
  0.10 * VTS
```

> ⚠️ Le Domain Context peut **ajuster les poids ±10%**, jamais les seuils absolus.

---

## 5. Seuils de décision

```text
if VNS ≥ 0.60 → VISION_REQUIRED
if 0.40 ≤ VNS < 0.60 → VISION_RECOMMENDED
if VNS < 0.40 → NO_VISION
```

### Règle de sécurité

Si `VDS == 1.0` **OU** `RIS == 1.0` → **VISION_REQUIRED**, quel que soit le reste.

---

## 6. Règles explicites anti-erreurs

* ❌ Beaucoup de texte ≠ pas de vision

* ❌ Image petite ≠ décorative (si connectée à texte)

* ❌ PPTX ≠ vision automatique

* ❌ PDF texte ≠ no-vision automatique

* ✅ Connecteurs ⇒ vision

* ✅ Forte dispersion ⇒ vision

* ✅ Shapes massifs ⇒ vision

---

## 7. Sortie du Vision Gating

La sortie doit être **auditable**.

```json
{
  "unit_id": "PDF_PAGE_6",
  "decision": "VISION_REQUIRED",
  "vision_need_score": 0.78,
  "signals": {
    "RIS": 0.0,
    "VDS": 1.0,
    "TFS": 0.6,
    "SDS": 0.5,
    "VTS": 0.0
  },
  "reasons": [
    "high number of vector drawings",
    "presence of connectors",
    "high text fragmentation"
  ]
}
```

---

## 8. Pseudo-code (Claude-Code ready)

```python
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional

class VisionDecision(Enum):
    NO_VISION = "NO_VISION"
    VISION_RECOMMENDED = "VISION_RECOMMENDED"
    VISION_REQUIRED = "VISION_REQUIRED"

@dataclass
class VisionGatingResult:
    decision: VisionDecision
    vision_need_score: float
    signals: Dict[str, float]
    reasons: List[str]

DEFAULT_WEIGHTS = {
    "RIS": 0.30,
    "VDS": 0.30,
    "TFS": 0.15,
    "SDS": 0.15,
    "VTS": 0.10
}

def compute_vision_gating(unit, domain_context=None) -> VisionGatingResult:
    RIS = compute_raster_image_signal(unit)
    VDS = compute_vector_drawing_signal(unit)
    TFS = compute_text_fragmentation_signal(unit)
    SDS = compute_spatial_dispersion_signal(unit)
    VTS = compute_visual_table_signal(unit)

    weights = DEFAULT_WEIGHTS.copy()
    if domain_context:
        weights = adjust_weights(weights, domain_context)

    VNS = (
        weights["RIS"] * RIS +
        weights["VDS"] * VDS +
        weights["TFS"] * TFS +
        weights["SDS"] * SDS +
        weights["VTS"] * VTS
    )

    reasons = []

    # Règle de sécurité
    if RIS == 1.0 or VDS == 1.0:
        decision = VisionDecision.VISION_REQUIRED
        if RIS == 1.0:
            reasons.append("large raster image detected")
        if VDS == 1.0:
            reasons.append("high number of vector drawings or connectors")
    elif VNS >= 0.60:
        decision = VisionDecision.VISION_REQUIRED
        reasons.append(f"high vision need score ({VNS:.2f})")
    elif VNS >= 0.40:
        decision = VisionDecision.VISION_RECOMMENDED
        reasons.append(f"moderate vision need score ({VNS:.2f})")
    else:
        decision = VisionDecision.NO_VISION

    # Ajouter les raisons des signaux élevés
    if TFS >= 0.6:
        reasons.append("high text fragmentation")
    if SDS >= 0.5:
        reasons.append("high spatial dispersion")
    if VTS >= 1.0:
        reasons.append("visual table detected")

    return VisionGatingResult(
        decision=decision,
        vision_need_score=round(VNS, 2),
        signals={
            "RIS": RIS, "VDS": VDS, "TFS": TFS, "SDS": SDS, "VTS": VTS
        },
        reasons=reasons
    )
```

---

## 9. Garantie apportée par V4

* 🧱 **Structure-first**
* 🧠 **Vision only when structure matters**
* 🧯 **Anti-hallucination by design**
* 🧬 **Compatible Domain Context**
* 🧩 **Extensible (zones, pages partielles)**

---

## 10. Implémentation des signaux

### 10.1 RIS - Raster Image Signal

```python
def compute_raster_image_signal(unit) -> float:
    """Détecte les images raster significatives."""
    images = unit.visual_elements.get("images", [])
    if not images:
        return 0.0

    page_area = unit.page_dimensions["width"] * unit.page_dimensions["height"]

    largest_ratio = 0.0
    for img in images:
        img_area = img["bbox"]["width"] * img["bbox"]["height"]
        ratio = img_area / page_area
        largest_ratio = max(largest_ratio, ratio)

    if largest_ratio >= 0.30:
        return 1.0
    elif largest_ratio >= 0.20:
        return 0.7
    elif largest_ratio >= 0.10:
        return 0.4
    return 0.0
```

### 10.2 VDS - Vector Drawing Signal

```python
def compute_vector_drawing_signal(unit) -> float:
    """Détecte les diagrammes en shapes vectoriels."""
    drawings = unit.visual_elements.get("drawings", [])
    connectors = unit.visual_elements.get("connectors", [])

    num_drawings = len(drawings)
    num_connectors = len(connectors)

    # Calcul du ratio de surface
    page_area = unit.page_dimensions["width"] * unit.page_dimensions["height"]
    drawing_area = sum(
        d["bbox"]["width"] * d["bbox"]["height"]
        for d in drawings
    )
    drawing_area_ratio = drawing_area / page_area if page_area > 0 else 0

    # Score
    if num_connectors >= 3 or drawing_area_ratio >= 0.35:
        return 1.0
    elif num_drawings >= 15:
        return 0.7
    elif num_drawings >= 8:
        return 0.4
    return 0.0
```

### 10.3 TFS - Text Fragmentation Signal

```python
def compute_text_fragmentation_signal(unit) -> float:
    """Détecte la fragmentation textuelle (indicateur de diagramme)."""
    blocks = unit.blocks
    if not blocks:
        return 0.0

    num_text_blocks = len(blocks)
    short_blocks = [b for b in blocks if len(b.get("text", "")) < 200]
    short_block_ratio = len(short_blocks) / num_text_blocks

    if short_block_ratio >= 0.75 and num_text_blocks >= 12:
        return 1.0
    elif short_block_ratio >= 0.60:
        return 0.6
    return 0.0
```

### 10.4 SDS - Spatial Dispersion Signal

```python
import numpy as np

def compute_spatial_dispersion_signal(unit) -> float:
    """Mesure la dispersion spatiale du texte."""
    blocks = unit.blocks
    if len(blocks) < 3:
        return 0.0

    # Calculer les centres des blocs
    centers = []
    for b in blocks:
        bbox = b.get("bbox", {})
        cx = bbox.get("x", 0) + bbox.get("width", 0) / 2
        cy = bbox.get("y", 0) + bbox.get("height", 0) / 2
        centers.append((cx, cy))

    # Normaliser par dimensions page
    page_w = unit.page_dimensions["width"]
    page_h = unit.page_dimensions["height"]

    centers_norm = [(c[0]/page_w, c[1]/page_h) for c in centers]

    # Calculer variance spatiale
    xs = [c[0] for c in centers_norm]
    ys = [c[1] for c in centers_norm]

    variance = np.var(xs) + np.var(ys)

    # Seuils empiriques
    HIGH_THRESHOLD = 0.08
    MEDIUM_THRESHOLD = 0.04

    if variance >= HIGH_THRESHOLD:
        return 1.0
    elif variance >= MEDIUM_THRESHOLD:
        return 0.5
    return 0.0
```

### 10.5 VTS - Visual Table Signal

```python
def compute_visual_table_signal(unit) -> float:
    """Détecte les tables visuelles non structurées."""
    drawings = unit.visual_elements.get("drawings", [])
    blocks = unit.blocks

    # Chercher des patterns de grille
    horizontal_lines = [d for d in drawings if is_horizontal_line(d)]
    vertical_lines = [d for d in drawings if is_vertical_line(d)]

    # Si plusieurs lignes H et V alignées = probable table visuelle
    if len(horizontal_lines) >= 3 and len(vertical_lines) >= 2:
        return 1.0

    # Chercher alignements de texte en grille
    if detect_text_grid_pattern(blocks):
        return 1.0

    return 0.0
```

---

## 11. Extensions futures

* Vision Gating **par zone** (ROI)
* Double-pass Vision (local VLM → GPT-4o fallback)
* Feedback loop KG → ajustement des seuils
