"""
OSMOSE Vision Gating v3.4 - Text Structure Detection

Améliorations v3.4:
- STRUCTURED_TEXT Detection: Analyse la distribution des blocs texte pour
  distinguer "label soup" (diagrammes) vs "paragraphes" (texte structuré).
- Métriques: short_ratio (% blocs ≤30 chars), avg_block, max_block
- Formule: STRUCTURED_TEXT = (short_ratio < 0.35) AND (avg_block > 60 OR max_block > 200)
- Surcouche sur v3.3: Si texte dense + peu visuels + STRUCTURED_TEXT → SKIP

Améliorations v3.3:
- Text Density + NonTpl Override: Si texte dense (>2500 chars) ET peu d'éléments
  visuels informatifs (<15 NonTpl), skip Vision même si draw_area élevé.
- Cas typique: Documents SAP avec template graphique (fonds colorés, bandeaux)
  mais contenu informatif dans le texte natif.

Améliorations v3.2 (basées sur analyse ChatGPT):
1. BBox quantization: Signatures robustes avec buckets larges (2%)
2. Header/footer adaptatif: Calculé dynamiquement via text blocks
3. Banner-like rule: Éléments larges récurrents = template même si > 2%
4. Clustering IoU greedy: Groupe éléments similaires par proximité spatiale

Principe clé: Détection "fuzzy" des templates pour documents designés (CNIL, etc.)

Author: OSMOSE + ChatGPT collaboration
Date: 2026-01
"""

import math
import hashlib
import logging
from typing import Dict, Any, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class VisionDecision(Enum):
    """Décision de gating Vision."""
    SKIP = "skip"          # Extraction texte suffit
    REQUIRED = "required"  # Vision nécessaire
    OPTIONAL = "optional"  # Cas limite


@dataclass
class TemplateCluster:
    """Cluster d'éléments visuels similaires (potentiel template)."""
    cx: float  # Centre X normalisé
    cy: float  # Centre Y normalisé
    w: float   # Largeur normalisée
    h: float   # Hauteur normalisée
    element_type: str  # "D" (drawing) ou "I" (image)
    pages: Set[int] = field(default_factory=set)

    def iou(self, cx2: float, cy2: float, w2: float, h2: float) -> float:
        """Calcule IoU (Intersection over Union) avec un autre rect."""
        # Convertir centre+taille en x0,y0,x1,y1
        x0_1, y0_1 = self.cx - self.w/2, self.cy - self.h/2
        x1_1, y1_1 = self.cx + self.w/2, self.cy + self.h/2
        x0_2, y0_2 = cx2 - w2/2, cy2 - h2/2
        x1_2, y1_2 = cx2 + w2/2, cy2 + h2/2

        # Intersection
        xi0 = max(x0_1, x0_2)
        yi0 = max(y0_1, y0_2)
        xi1 = min(x1_1, x1_2)
        yi1 = min(y1_1, y1_2)

        if xi1 <= xi0 or yi1 <= yi0:
            return 0.0

        inter = (xi1 - xi0) * (yi1 - yi0)
        area1 = self.w * self.h
        area2 = w2 * h2
        union = area1 + area2 - inter

        return inter / union if union > 0 else 0.0


@dataclass
class DocumentProfile:
    """Profil document issu de Pass 1."""
    template_clusters: List[TemplateCluster]
    text_threshold: int
    drawings_count_threshold: int
    chars_per_page: List[int]
    non_template_counts: List[int]
    doc_class: str  # "presentation", "report", "mixed"
    total_pages: int
    header_limit: float  # Y normalisé de fin de header (adaptatif)
    footer_limit: float  # Y normalisé de début de footer (adaptatif)


@dataclass
class GatingResult:
    """Résultat du gating avec justification."""
    decision: VisionDecision
    reason: str
    chars: int = 0
    visual_signal: float = 0.0
    img_area: float = 0.0
    draw_area: float = 0.0
    draw_cnt: int = 0
    non_template_cnt: int = 0


# Patterns de pages triviales (multi-langue)
TRIVIAL_PATTERNS = [
    "thank you", "thanks", "merci", "danke", "vielen dank",
    "agenda", "table of contents", "sommaire", "table des matières", "inhalt",
    "appendix", "annexe", "backup slides",
    "questions", "q&a", "fragen",
    "contact", "contacts", "coordonnées",
    "legal disclaimer", "copyright", "all rights reserved",
    "confidential", "confidentiel",
]

# Configuration v3.2
BBOX_QUANTIZATION_STEP = 0.02  # 2% buckets pour quantification (legacy)
CENTER_DIST_THRESHOLD = 0.03  # Distance max entre centres (3% de la page)
SIZE_RATIO_MIN = 0.7  # Ratio taille min pour match (permet 30% de variation)
SIZE_RATIO_MAX = 1.43  # Ratio taille max (1/0.7)
TEMPLATE_FREQ_THRESHOLD = 0.75  # Fréquence min pour template (zone-aware)
TEMPLATE_FREQ_HIGH = 0.90  # Fréquence haute = template même en body
BANNER_WIDTH_MIN = 0.7  # Largeur min pour être un "banner"
BANNER_HEIGHT_MAX = 0.25  # Hauteur max pour être un "banner"

# Configuration v3.4 - Text Structure Detection (validé ChatGPT)
TEXT_HEAVY_THRESHOLD = 1200  # Seuil texte dense (abaissé de 2500 pour capturer plus de pages)
LOW_VISUAL_CONTENT_THRESHOLD = 15  # Seuil éléments visuels informatifs
SHORT_BLOCK_CHARS = 30  # Seuil pour "bloc court" (labels vs paragraphes)
SHORT_RATIO_THRESHOLD = 0.35  # Si < 35% blocs courts = paragraphes
AVG_BLOCK_THRESHOLD = 60  # Moyenne bloc > 60 chars = texte structuré
MAX_BLOCK_THRESHOLD = 200  # Au moins un bloc > 200 chars = paragraphe présent


def _quantize(val: float, step: float = BBOX_QUANTIZATION_STEP) -> int:
    """Quantifie une valeur normalisée en bucket."""
    return int(round(val / step))


def _bucket_count(n: int) -> str:
    """Bucket pour nombre d'opérations de dessin."""
    if n <= 1: return "1"
    if n <= 3: return "2-3"
    if n <= 7: return "4-7"
    if n <= 15: return "8-15"
    return "16+"


def _rect_to_cwh(rect, W: float, H: float) -> Tuple[float, float, float, float]:
    """Convertit un rect en (cx, cy, w, h) normalisés."""
    x0, y0 = rect.x0 / W, rect.y0 / H
    x1, y1 = rect.x1 / W, rect.y1 / H
    w = x1 - x0
    h = y1 - y0
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    return (cx, cy, max(0, w), max(0, h))


def _area_norm(rect, W: float, H: float) -> float:
    """Calcule l'aire normalisée d'un rectangle."""
    area = max(0.0, (rect.x1 - rect.x0) * (rect.y1 - rect.y0))
    return area / (W * H)


def _hash_bytes(b: bytes, n: int = 8) -> str:
    """Hash tronqué pour identifier les images."""
    return hashlib.sha1(b).hexdigest()[:n]


def _percentile(values: List[float], p: float) -> float:
    """Calcule un percentile sans numpy."""
    vals = sorted(values)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return vals[int(k)]
    return vals[f] + (vals[c] - vals[f]) * (k - f)


def _compute_adaptive_zones(doc) -> Tuple[float, float]:
    """
    Calcule les limites header/footer adaptatives basées sur les blocs texte.

    Returns:
        (header_limit, footer_limit) en coordonnées normalisées
    """
    n = len(doc)
    if n == 0:
        return (0.12, 0.88)

    y_top_mins = []
    y_bottom_maxs = []

    for i in range(min(n, 20)):  # Analyser les 20 premières pages max
        page = doc[i]
        W, H = page.rect.width, page.rect.height
        if W == 0 or H == 0:
            continue

        blocks = page.get_text("blocks")
        if not blocks:
            continue

        # Filtrer les blocs texte significatifs (> 20 chars)
        text_blocks = [b for b in blocks if len(b[4]) > 20 if b[6] == 0]  # b[6]==0 = text block

        if text_blocks:
            y_tops = [b[1] / H for b in text_blocks]  # y0 normalisé
            y_bottoms = [b[3] / H for b in text_blocks]  # y1 normalisé
            y_top_mins.append(min(y_tops))
            y_bottom_maxs.append(max(y_bottoms))

    if not y_top_mins:
        return (0.12, 0.88)

    # Médiane + marge
    median_top = _percentile(y_top_mins, 50)
    median_bottom = _percentile(y_bottom_maxs, 50)

    header_limit = max(0.05, median_top - 0.02)  # Au moins 5%
    footer_limit = min(0.95, median_bottom + 0.02)  # Au plus 95%

    # Sanity check
    if header_limit > 0.25:
        header_limit = 0.20  # Cap à 20% pour header
    if footer_limit < 0.80:
        footer_limit = 0.85  # Cap à 85% pour footer

    return (header_limit, footer_limit)


def _is_in_zone(cy: float, h: float, header_limit: float, footer_limit: float) -> str:
    """Détermine la zone d'un élément (header/footer/body) avec limites adaptatives."""
    y0 = cy - h/2
    y1 = cy + h/2

    if y1 <= header_limit:
        return "header"
    if y0 >= footer_limit:
        return "footer"
    return "body"


def _is_banner_like(w: float, h: float, cy: float, header_limit: float) -> bool:
    """Détecte si un élément ressemble à un bandeau (header large)."""
    # Large, pas trop haut, et proche du haut de page
    return (
        w >= BANNER_WIDTH_MIN and
        h <= BANNER_HEIGHT_MAX and
        cy <= header_limit + 0.10  # Dans le header ou juste en dessous
    )


def _elements_match(c1_cx, c1_cy, c1_w, c1_h, cx, cy, w, h) -> bool:
    """
    Matching hybride centre + taille (plus robuste qu'IoU seul).

    Critères:
    - Distance entre centres < 3% de la page
    - Ratio de taille entre 0.7 et 1.43 (permet 30% de variation)
    """
    # Distance entre centres
    dist = math.sqrt((c1_cx - cx)**2 + (c1_cy - cy)**2)
    if dist > CENTER_DIST_THRESHOLD:
        return False

    # Ratio de taille (éviter division par zéro)
    if c1_w < 0.001 or c1_h < 0.001 or w < 0.001 or h < 0.001:
        return False

    w_ratio = w / c1_w
    h_ratio = h / c1_h

    if not (SIZE_RATIO_MIN <= w_ratio <= SIZE_RATIO_MAX):
        return False
    if not (SIZE_RATIO_MIN <= h_ratio <= SIZE_RATIO_MAX):
        return False

    return True


def _cluster_elements_greedy(
    elements: List[Tuple[str, float, float, float, float, int]],  # (type, cx, cy, w, h, page_idx)
) -> List[TemplateCluster]:
    """
    Clustering greedy des éléments visuels par centre + taille.

    Plus robuste que IoU pour les éléments qui bougent légèrement.
    """
    clusters: List[TemplateCluster] = []

    for elem_type, cx, cy, w, h, page_idx in elements:
        matched = False

        for cluster in clusters:
            if cluster.element_type != elem_type:
                continue

            if _elements_match(cluster.cx, cluster.cy, cluster.w, cluster.h, cx, cy, w, h):
                # Match trouvé - ajouter la page au cluster
                cluster.pages.add(page_idx)
                # Mettre à jour le centroïde (moyenne mobile)
                n = len(cluster.pages)
                cluster.cx = cluster.cx * (n-1)/n + cx/n
                cluster.cy = cluster.cy * (n-1)/n + cy/n
                cluster.w = cluster.w * (n-1)/n + w/n
                cluster.h = cluster.h * (n-1)/n + h/n
                matched = True
                break

        if not matched:
            # Créer un nouveau cluster
            new_cluster = TemplateCluster(
                cx=cx, cy=cy, w=w, h=h,
                element_type=elem_type,
                pages={page_idx}
            )
            clusters.append(new_cluster)

    return clusters


def _extract_visual_elements(doc, page, page_idx: int, W: float, H: float) -> List[Tuple[str, float, float, float, float, int]]:
    """
    Extrait les éléments visuels d'une page avec coordonnées normalisées.

    Returns:
        Liste de (type, cx, cy, w, h, page_idx)
    """
    elements = []

    # Drawings
    for d in page.get_drawings() or []:
        try:
            rect = d["rect"]
            cx, cy, w, h = _rect_to_cwh(rect, W, H)
            if w > 0.001 and h > 0.001:  # Ignorer les éléments minuscules
                elements.append(("D", cx, cy, w, h, page_idx))
        except Exception:
            pass

    # Images
    for img in page.get_images(full=True) or []:
        try:
            xref = img[0]
            bboxes = page.get_image_bbox(xref)

            import fitz
            if isinstance(bboxes, fitz.Rect):
                bboxes = [bboxes]
            elif not bboxes:
                continue

            for rect in bboxes:
                if not hasattr(rect, 'x0'):
                    continue
                cx, cy, w, h = _rect_to_cwh(rect, W, H)
                if w > 0.001 and h > 0.001:
                    elements.append(("I", cx, cy, w, h, page_idx))
        except Exception:
            pass

    return elements


def profile_document(doc, template_freq: float = TEMPLATE_FREQ_THRESHOLD) -> DocumentProfile:
    """
    Pass 1: Profiling du document avec détection fuzzy des templates.

    Utilise clustering IoU et header/footer adaptatif pour détecter
    les éléments récurrents même sur documents "designés".
    """
    n = len(doc)
    if n == 0:
        return DocumentProfile(
            template_clusters=[],
            text_threshold=1200,
            drawings_count_threshold=6,
            chars_per_page=[],
            non_template_counts=[],
            doc_class="unknown",
            total_pages=0,
            header_limit=0.12,
            footer_limit=0.88
        )

    logger.debug(f"[VisionGating v3.4] Pass 1: Profiling {n} pages")

    # 1. Calculer les zones adaptatives
    header_limit, footer_limit = _compute_adaptive_zones(doc)
    logger.debug(f"[VisionGating v3.4] Adaptive zones: header<{header_limit:.2f}, footer>{footer_limit:.2f}")

    # 2. Collecter tous les éléments visuels
    all_elements = []
    chars_per_page = [0] * n

    for i in range(n):
        page = doc[i]
        W, H = page.rect.width, page.rect.height

        if W == 0 or H == 0:
            continue

        text = page.get_text("text") or ""
        chars_per_page[i] = len(text)

        elements = _extract_visual_elements(doc, page, i, W, H)
        all_elements.extend(elements)

    # 3. Clustering par centre + taille (plus robuste qu'IoU)
    clusters = _cluster_elements_greedy(all_elements)

    # 4. Identifier les clusters template
    template_clusters = []
    for cluster in clusters:
        freq = len(cluster.pages) / n
        zone = _is_in_zone(cluster.cy, cluster.h, header_limit, footer_limit)
        area = cluster.w * cluster.h
        is_banner = _is_banner_like(cluster.w, cluster.h, cluster.cy, header_limit)

        # Critères v3.2 pour être template:
        # Option 1: Fréquence >= 75% ET (header/footer OU petite surface OU banner-like)
        # Option 2: Fréquence >= 90% ET (area <= 6% OU banner) - zone ignorée
        is_template = False

        if freq >= TEMPLATE_FREQ_HIGH:
            # Fréquence très haute = template même en body
            if area <= 0.06 or is_banner:
                is_template = True
        elif freq >= template_freq:
            # Fréquence normale = dépend de la zone
            if zone in ("header", "footer") or area <= 0.03 or is_banner:
                is_template = True

        if is_template:
            template_clusters.append(cluster)
            logger.debug(
                f"[VisionGating v3.4] Template cluster: type={cluster.element_type}, "
                f"zone={zone}, area={area:.3f}, freq={freq:.2f}, banner={is_banner}"
            )

    logger.info(f"[VisionGating v3.4] Found {len(template_clusters)} template clusters")

    # 5. Calculer les stats non-template par page
    non_template_counts = [0] * n
    for i in range(n):
        page = doc[i]
        W, H = page.rect.width, page.rect.height

        if W == 0 or H == 0:
            continue

        elements = _extract_visual_elements(doc, page, i, W, H)

        for elem_type, cx, cy, w, h, _ in elements:
            # Vérifier si cet élément matche un template cluster
            is_template = False
            for tc in template_clusters:
                if tc.element_type == elem_type and _elements_match(tc.cx, tc.cy, tc.w, tc.h, cx, cy, w, h):
                    is_template = True
                    break

            if not is_template:
                non_template_counts[i] += 1

    # 6. Calculer seuils adaptatifs
    valid_chars = [c for c in chars_per_page if c > 0]
    valid_counts = [c for c in non_template_counts]

    text_threshold = max(1200, int(_percentile(valid_chars, 60))) if valid_chars else 1200
    drawings_threshold = max(4, int(round(_percentile(valid_counts, 75)))) if valid_counts else 6

    # 7. Classifier le document
    median_chars = _percentile(valid_chars, 50) if valid_chars else 0
    pages_with_visuals = sum(1 for c in non_template_counts if c > 0)
    visual_ratio = pages_with_visuals / n if n > 0 else 0

    if median_chars < 400 and visual_ratio > 0.5:
        doc_class = "presentation"
    elif median_chars > 1500 and visual_ratio < 0.3:
        doc_class = "report"
    else:
        doc_class = "mixed"

    logger.info(
        f"[VisionGating v3.4] Document profile: class={doc_class}, "
        f"median_chars={median_chars:.0f}, visual_ratio={visual_ratio:.2f}, "
        f"text_threshold={text_threshold}, drawings_threshold={drawings_threshold}, "
        f"template_clusters={len(template_clusters)}"
    )

    return DocumentProfile(
        template_clusters=template_clusters,
        text_threshold=text_threshold,
        drawings_count_threshold=drawings_threshold,
        chars_per_page=chars_per_page,
        non_template_counts=non_template_counts,
        doc_class=doc_class,
        total_pages=n,
        header_limit=header_limit,
        footer_limit=footer_limit
    )


@dataclass
class TextBlockMetrics:
    """Métriques de distribution des blocs texte pour v3.4."""
    n_blocks: int = 0
    short_count: int = 0  # Blocs ≤30 chars
    short_ratio: float = 0.0  # Proportion blocs courts
    avg_block: float = 0.0  # Taille moyenne des blocs
    max_block: int = 0  # Taille du plus grand bloc
    is_structured: bool = False  # True si paragraphes détectés


def _compute_text_block_metrics(page) -> TextBlockMetrics:
    """
    Calcule les métriques de distribution des blocs texte.

    Distingue:
    - "Label soup" (diagrammes): beaucoup de petits blocs courts
    - "Paragraphes" (texte structuré): moins de blocs, plus longs

    Returns:
        TextBlockMetrics avec short_ratio, avg_block, max_block
    """
    blocks = page.get_text("blocks")

    if not blocks:
        return TextBlockMetrics()

    # Filtrer uniquement les blocs texte (b[6] == 0)
    text_blocks = [b for b in blocks if len(b) > 6 and b[6] == 0]

    if not text_blocks:
        return TextBlockMetrics()

    # Calculer longueur de chaque bloc
    block_lengths = []
    for b in text_blocks:
        text = b[4].strip() if len(b) > 4 else ""
        if text:  # Ignorer blocs vides
            block_lengths.append(len(text))

    if not block_lengths:
        return TextBlockMetrics()

    n_blocks = len(block_lengths)
    short_count = sum(1 for length in block_lengths if length <= SHORT_BLOCK_CHARS)
    short_ratio = short_count / n_blocks if n_blocks > 0 else 0.0
    avg_block = sum(block_lengths) / n_blocks if n_blocks > 0 else 0.0
    max_block = max(block_lengths) if block_lengths else 0

    # Formule STRUCTURED_TEXT validée ChatGPT:
    # (short_ratio < 0.35) AND (avg_block > 60 OR max_block > 200)
    is_structured = (
        short_ratio < SHORT_RATIO_THRESHOLD and
        (avg_block > AVG_BLOCK_THRESHOLD or max_block > MAX_BLOCK_THRESHOLD)
    )

    return TextBlockMetrics(
        n_blocks=n_blocks,
        short_count=short_count,
        short_ratio=short_ratio,
        avg_block=avg_block,
        max_block=max_block,
        is_structured=is_structured
    )


def decide_page(doc, page, profile: DocumentProfile, page_index: int = 0) -> GatingResult:
    """
    Pass 2: Décision pour une page spécifique.

    Calcule un score visuel informatif en ignorant les templates clusters,
    puis décide SKIP/VISION/OPTIONAL.
    """
    W, H = page.rect.width, page.rect.height

    if W == 0 or H == 0:
        return GatingResult(
            decision=VisionDecision.SKIP,
            reason="invalid_page_dimensions"
        )

    text = page.get_text("text") or ""
    chars = len(text)
    text_lower = text.strip().lower()

    # Règle 1: Page triviale (patterns connus)
    if chars < 800:
        for pattern in TRIVIAL_PATTERNS:
            if pattern in text_lower:
                return GatingResult(
                    decision=VisionDecision.SKIP,
                    reason=f"trivial_pattern:{pattern}",
                    chars=chars
                )

    # Extraire les éléments visuels
    elements = _extract_visual_elements(doc, page, page_index, W, H)

    # Calculer les métriques visuelles non-template
    img_area = 0.0
    draw_area = 0.0
    draw_cnt = 0
    has_curves = False
    body_visuals = False
    non_template_cnt = 0

    for elem_type, cx, cy, w, h, _ in elements:
        # Vérifier si cet élément matche un template cluster
        is_template = False
        for tc in profile.template_clusters:
            if tc.element_type == elem_type and _elements_match(tc.cx, tc.cy, tc.w, tc.h, cx, cy, w, h):
                is_template = True
                break

        if is_template:
            continue

        area = w * h
        zone = _is_in_zone(cy, h, profile.header_limit, profile.footer_limit)

        if elem_type == "D":
            draw_area += area
            draw_cnt += 1
        else:
            img_area += area

        non_template_cnt += 1

        if zone == "body":
            body_visuals = True

    # Vérifier les courbes dans les drawings (analyse plus fine)
    for d in page.get_drawings() or []:
        items = d.get("items", [])
        if any(op[0] == "c" for op in items):
            has_curves = True
            break

    # Calculer le score visuel
    K = profile.drawings_count_threshold
    visual_signal = 0.0

    if img_area > 0.02:
        visual_signal += 1.0
    if draw_area > 0.04:
        visual_signal += 1.0
    if draw_cnt >= K:
        visual_signal += 0.7
    if has_curves and non_template_cnt > 0:
        visual_signal += 0.7
    if body_visuals:
        visual_signal += 0.7

    # Règle 2: Peu de texte + visuels → VISION
    if chars < 50 and (img_area > 0 or draw_cnt > 0):
        return GatingResult(
            decision=VisionDecision.REQUIRED,
            reason="low_text_with_visuals",
            chars=chars,
            visual_signal=visual_signal,
            img_area=img_area,
            draw_area=draw_area,
            draw_cnt=draw_cnt,
            non_template_cnt=non_template_cnt
        )

    # Règle 2.5 (v3.4): Texte dense + peu d'éléments visuels + STRUCTURED_TEXT → SKIP
    # Amélioration v3.4: On vérifie aussi la structure du texte (paragraphes vs labels)
    # STRUCTURED_TEXT = (short_ratio < 0.35) AND (avg_block > 60 OR max_block > 200)
    # Cas typique: documents SAP Scope avec template graphique mais contenu paragraphes
    # Contre-exemple: diagrammes avec beaucoup de petits labels (short_ratio élevé)

    if chars > TEXT_HEAVY_THRESHOLD and non_template_cnt < LOW_VISUAL_CONTENT_THRESHOLD:
        # Calculer les métriques de blocs texte
        block_metrics = _compute_text_block_metrics(page)

        if block_metrics.is_structured:
            # v3.4: Paragraphes détectés → SKIP car Vision n'apportera rien
            return GatingResult(
                decision=VisionDecision.SKIP,
                reason=f"text_heavy_structured (sr={block_metrics.short_ratio:.2f}, avg={block_metrics.avg_block:.0f}, max={block_metrics.max_block})",
                chars=chars,
                visual_signal=visual_signal,
                img_area=img_area,
                draw_area=draw_area,
                draw_cnt=draw_cnt,
                non_template_cnt=non_template_cnt
            )
        # else: pas structuré (label soup) → continuer évaluation, peut-être besoin Vision

    # Règle 3: Signal visuel fort → VISION
    if visual_signal >= 1.0:
        return GatingResult(
            decision=VisionDecision.REQUIRED,
            reason="visual_signal",
            chars=chars,
            visual_signal=visual_signal,
            img_area=img_area,
            draw_area=draw_area,
            draw_cnt=draw_cnt,
            non_template_cnt=non_template_cnt
        )

    # Règle 4: Beaucoup de texte + pas de visuels → SKIP
    if chars > profile.text_threshold and visual_signal == 0:
        return GatingResult(
            decision=VisionDecision.SKIP,
            reason="text_heavy_no_visuals",
            chars=chars,
            visual_signal=visual_signal,
            non_template_cnt=non_template_cnt
        )

    # Règle 5: Cas ambigus → OPTIONAL
    return GatingResult(
        decision=VisionDecision.OPTIONAL,
        reason="ambiguous",
        chars=chars,
        visual_signal=visual_signal,
        img_area=img_area,
        draw_area=draw_area,
        draw_cnt=draw_cnt,
        non_template_cnt=non_template_cnt
    )


def gate_document(doc) -> List[GatingResult]:
    """
    Gating complet d'un document (Pass 1 + Pass 2 pour toutes les pages).
    """
    profile = profile_document(doc)
    results = []

    for i in range(len(doc)):
        page = doc[i]
        result = decide_page(doc, page, profile, page_index=i + 1)
        results.append(result)

    # Stats finales
    vision_count = sum(1 for r in results if r.decision == VisionDecision.REQUIRED)
    skip_count = sum(1 for r in results if r.decision == VisionDecision.SKIP)
    optional_count = sum(1 for r in results if r.decision == VisionDecision.OPTIONAL)

    logger.info(
        f"[VisionGating v3.4] Document gating complete: "
        f"{len(results)} pages, {vision_count} VISION, {skip_count} SKIP, {optional_count} OPTIONAL"
    )

    return results


# ============================================================================
# Fonctions de compatibilité avec l'ancienne API
# ============================================================================

def should_use_vision(
    slide_text: str,
    slide_notes: str = "",
    slide_index: int = 0,
    has_shapes: bool = False,
    has_images: bool = False,
    has_charts: bool = False,
    drawings: Optional[List[Dict[str, Any]]] = None,
    min_text_threshold: int = 800,
    max_empty_threshold: int = 50,
) -> GatingResult:
    """
    Fonction de compatibilité avec l'ancienne API (single-page, sans contexte document).

    Pour un gating optimal, utiliser gate_document() sur le document complet.
    """
    combined_text = f"{slide_text} {slide_notes}".strip()
    text_lower = combined_text.lower()
    chars = len(combined_text)

    # Patterns triviaux
    if chars < 800:
        for pattern in TRIVIAL_PATTERNS:
            if pattern in text_lower:
                return GatingResult(
                    decision=VisionDecision.SKIP,
                    reason=f"trivial_pattern:{pattern}",
                    chars=chars
                )

    # Page vide avec visuels
    if chars < max_empty_threshold:
        if has_images or has_charts or has_shapes:
            return GatingResult(
                decision=VisionDecision.REQUIRED,
                reason="empty_with_visuals",
                chars=chars
            )
        else:
            return GatingResult(
                decision=VisionDecision.SKIP,
                reason="empty_page",
                chars=chars
            )

    # Images présentes
    if has_images:
        return GatingResult(
            decision=VisionDecision.REQUIRED,
            reason="has_images",
            chars=chars
        )

    # Charts présents
    if has_charts:
        return GatingResult(
            decision=VisionDecision.REQUIRED,
            reason="has_charts",
            chars=chars
        )

    # Shapes présents
    if has_shapes:
        return GatingResult(
            decision=VisionDecision.REQUIRED,
            reason="has_shapes",
            chars=chars
        )

    # Texte seul
    if chars > min_text_threshold:
        return GatingResult(
            decision=VisionDecision.SKIP,
            reason="text_only",
            chars=chars
        )

    return GatingResult(
        decision=VisionDecision.OPTIONAL,
        reason="ambiguous",
        chars=chars
    )


def estimate_vision_savings_pptx(slides_data: List[Dict[str, Any]], include_optional: bool = True) -> Dict[str, Any]:
    """
    Estime les économies de gating pour un PPTX (format slides_data).

    Compatibilité avec l'ancien pipeline PPTX.

    Args:
        slides_data: Liste de dictionnaires avec les données de chaque slide
        include_optional: Si True, inclut les slides optionnelles dans le décompte Vision

    Returns:
        Statistiques de gating (total_slides, required_vision, optional_vision, etc.)
    """
    total = len(slides_data)
    required = 0
    optional = 0
    skip = 0

    for slide in slides_data:
        text = slide.get("text", "")
        notes = slide.get("notes", "")
        has_shapes = slide.get("has_shapes", False)
        has_images = slide.get("has_images", False)
        has_charts = slide.get("has_charts", False)

        result = should_use_vision(
            slide_text=text,
            slide_notes=notes,
            has_shapes=has_shapes,
            has_images=has_images,
            has_charts=has_charts
        )

        if result.decision == VisionDecision.REQUIRED:
            required += 1
        elif result.decision == VisionDecision.OPTIONAL:
            optional += 1
        else:
            skip += 1

    # Calcul du coût
    cost_per_call = 0.03
    vision_calls = required + (optional if include_optional else 0)
    cost_no_gating = total * cost_per_call
    cost_with_gating = vision_calls * cost_per_call
    savings = cost_no_gating - cost_with_gating
    savings_percent = (savings / cost_no_gating * 100) if cost_no_gating > 0 else 0

    return {
        "total_slides": total,
        "required_vision": required,
        "optional_vision": optional,
        "skip_vision": skip,
        "estimated_cost_no_gating_usd": round(cost_no_gating, 2),
        "estimated_cost_with_gating_usd": round(cost_with_gating, 2),
        "estimated_savings_usd": round(savings, 2),
        "savings_percent": round(savings_percent, 1),
    }


def estimate_vision_savings(doc) -> Dict[str, Any]:
    """
    Estime les économies de gating sur un document PDF complet.
    """
    results = gate_document(doc)

    total = len(results)
    vision_count = sum(1 for r in results if r.decision == VisionDecision.REQUIRED)
    skip_count = sum(1 for r in results if r.decision == VisionDecision.SKIP)
    optional_count = sum(1 for r in results if r.decision == VisionDecision.OPTIONAL)

    # Estimation coût (gpt-4o vision ~$0.03/page)
    cost_per_vision_call = 0.03
    cost_no_gating = total * cost_per_vision_call
    cost_with_gating = vision_count * cost_per_vision_call
    savings = cost_no_gating - cost_with_gating
    savings_percent = (savings / cost_no_gating * 100) if cost_no_gating > 0 else 0

    return {
        "total_pages": total,
        "vision_required": vision_count,
        "skip": skip_count,
        "optional": optional_count,
        "estimated_cost_no_gating_usd": round(cost_no_gating, 2),
        "estimated_cost_with_gating_usd": round(cost_with_gating, 2),
        "estimated_savings_usd": round(savings, 2),
        "savings_percent": round(savings_percent, 1),
    }


__all__ = [
    "VisionDecision",
    "GatingResult",
    "DocumentProfile",
    "TemplateCluster",
    "TextBlockMetrics",
    "profile_document",
    "decide_page",
    "gate_document",
    "should_use_vision",
    "estimate_vision_savings",
    "estimate_vision_savings_pptx",
]
