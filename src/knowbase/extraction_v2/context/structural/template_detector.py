"""
TemplateDetector - Detection des fragments repetitifs (boilerplate).

Identifie les fragments de texte qui apparaissent de maniere repetitive
sur plusieurs pages, indiquant du contenu template/boilerplate :
- Footers (copyright, legal notices)
- Headers (branding, titles)
- Numeros de page
- Disclaimers

Ce composant est agnostique et detecte la repetition par clustering,
sans hypothese sur le contenu.

Spec: doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md - Section 4.2
"""

from __future__ import annotations
from collections import defaultdict
from typing import Dict, List, Optional, Set
import logging

from knowbase.extraction_v2.context.structural.models import (
    Zone,
    PageZones,
    TemplateFragment,
    TemplateCluster,
    StructuralAnalysis,
    StructuralConfidence,
    normalize_for_template_matching,
)


logger = logging.getLogger(__name__)


class TemplateDetector:
    """
    Detecte les fragments template/boilerplate par analyse de repetition.

    Usage:
        >>> detector = TemplateDetector()
        >>> analysis = detector.analyze(pages_zones)
        >>> print(analysis.template_fragments)
    """

    def __init__(
        self,
        min_pages_ratio: float = 0.3,
        min_occurrences: int = 2,
        zone_consistency_threshold: float = 0.6,
        min_line_length: int = 10,
    ):
        """
        Initialise le detecteur.

        Args:
            min_pages_ratio: Ratio minimum de pages couvertes (0.3 = 30%)
            min_occurrences: Nombre minimum d'occurrences pour etre template
            zone_consistency_threshold: Seuil de consistance de zone (0.6 = 60% meme zone)
            min_line_length: Longueur minimum d'une ligne pour etre consideree
        """
        self.min_pages_ratio = min_pages_ratio
        self.min_occurrences = min_occurrences
        self.zone_consistency_threshold = zone_consistency_threshold
        self.min_line_length = min_line_length

    def analyze(self, pages_zones: List[PageZones]) -> StructuralAnalysis:
        """
        Analyse complete d'un document pour detecter les templates.

        Args:
            pages_zones: Liste des PageZones (output du ZoneSegmenter)

        Returns:
            StructuralAnalysis avec templates et statistiques
        """
        if not pages_zones:
            return StructuralAnalysis()

        total_pages = len(pages_zones)
        structural_confidence = StructuralConfidence.from_page_count(total_pages)

        # Etape 1: Clustering des lignes par texte normalise
        clusters = self._cluster_lines(pages_zones)

        # Etape 2: Filtrer les clusters qui sont des templates
        template_fragments = self._filter_template_clusters(clusters, total_pages)

        # Etape 3: Calculer les statistiques
        zone_stats = self._compute_zone_statistics(pages_zones)
        template_coverage = self._compute_template_coverage(
            pages_zones, template_fragments
        )

        logger.info(
            f"[TemplateDetector] Found {len(template_fragments)} template fragments, "
            f"coverage={template_coverage:.1%}, confidence={structural_confidence.value}"
        )

        return StructuralAnalysis(
            pages_zones=pages_zones,
            template_fragments=template_fragments,
            structural_confidence=structural_confidence,
            total_pages=total_pages,
            zone_statistics=zone_stats,
            template_coverage=template_coverage,
        )

    def _cluster_lines(self, pages_zones: List[PageZones]) -> Dict[str, TemplateCluster]:
        """
        Groupe les lignes par texte normalise.

        Returns:
            Dict[normalized_text -> TemplateCluster]
        """
        clusters: Dict[str, TemplateCluster] = {}

        for page_zones in pages_zones:
            for line in page_zones.get_all_lines():
                # Ignorer les lignes trop courtes
                if len(line.text) < self.min_line_length:
                    continue

                normalized = line.normalized_text
                if not normalized or len(normalized) < self.min_line_length:
                    continue

                if normalized not in clusters:
                    clusters[normalized] = TemplateCluster(normalized_key=normalized)

                clusters[normalized].add_occurrence(
                    page_index=page_zones.page_index,
                    zone=line.zone,
                    original_text=line.text,
                    line_index=line.line_index,
                )

        return clusters

    def _filter_template_clusters(
        self,
        clusters: Dict[str, TemplateCluster],
        total_pages: int,
    ) -> List[TemplateFragment]:
        """
        Filtre les clusters pour ne garder que les vrais templates.

        Criteres:
        - Apparait sur min_pages_ratio des pages
        - Au moins min_occurrences occurrences
        - Zone consistency >= threshold OU zone dominante != MAIN
        """
        templates = []

        for normalized, cluster in clusters.items():
            pages_covered = len(cluster.pages_covered)
            pages_ratio = pages_covered / total_pages if total_pages > 0 else 0

            # Critere 1: Assez de pages couvertes
            if pages_ratio < self.min_pages_ratio:
                continue

            # Critere 2: Assez d'occurrences
            if len(cluster.occurrences) < self.min_occurrences:
                continue

            # Critere 3: Zone consistency OU pas dans MAIN
            # (les fragments MAIN peuvent etre du contenu repete legitime)
            is_consistent = cluster.zone_consistency >= self.zone_consistency_threshold
            is_not_main = cluster.dominant_zone != Zone.MAIN

            # REGLE ADR: Fragments MAIN avec haute consistance peuvent etre du contenu
            # semantique repete (normes, procedures). On les garde mais avec
            # template_likelihood reduit.
            if not is_consistent and not is_not_main:
                continue

            template = cluster.to_template_fragment(total_pages)

            # Ajuster template_likelihood pour MAIN zone (REGLE ADR)
            if cluster.dominant_zone == Zone.MAIN:
                # Reduire la likelihood pour MAIN - peut etre du contenu semantique
                template.template_likelihood *= 0.5

            templates.append(template)

        # Trier par template_likelihood decroissante
        templates.sort(key=lambda t: t.template_likelihood, reverse=True)

        return templates

    def _compute_zone_statistics(self, pages_zones: List[PageZones]) -> Dict[str, int]:
        """Calcule les statistiques par zone."""
        stats = {"top": 0, "main": 0, "bottom": 0}

        for page_zones in pages_zones:
            stats["top"] += len(page_zones.top_lines)
            stats["main"] += len(page_zones.main_lines)
            stats["bottom"] += len(page_zones.bottom_lines)

        return stats

    def _compute_template_coverage(
        self,
        pages_zones: List[PageZones],
        templates: List[TemplateFragment],
    ) -> float:
        """
        Calcule le pourcentage de lignes couvertes par des templates.
        """
        if not pages_zones:
            return 0.0

        template_normalized: Set[str] = {t.normalized_text for t in templates}
        total_lines = 0
        template_lines = 0

        for page_zones in pages_zones:
            for line in page_zones.get_all_lines():
                total_lines += 1
                if line.normalized_text in template_normalized:
                    template_lines += 1

        return template_lines / total_lines if total_lines > 0 else 0.0

    def get_template_likelihood_for_value(
        self,
        value: str,
        analysis: StructuralAnalysis,
    ) -> float:
        """
        Calcule la template_likelihood pour une valeur specifique.

        Args:
            value: Valeur a chercher (ex: "2019")
            analysis: Analyse structurelle du document

        Returns:
            Score 0.0-1.0 de template_likelihood
        """
        template = analysis.get_template_for_value(value)
        if template:
            return template.template_likelihood
        return 0.0

    def get_zone_distribution_for_value(
        self,
        value: str,
        analysis: StructuralAnalysis,
    ) -> Dict[str, int]:
        """
        Calcule la distribution par zone pour une valeur.

        Args:
            value: Valeur a chercher
            analysis: Analyse structurelle

        Returns:
            Dict avec count par zone
        """
        return analysis.get_zone_distribution_for_value(value)

    def get_positional_stability_for_value(
        self,
        value: str,
        analysis: StructuralAnalysis,
    ) -> float:
        """
        Calcule la stabilite positionnelle pour une valeur.

        Retourne le ratio d'occurrences dans la zone dominante.
        """
        template = analysis.get_template_for_value(value)
        if template:
            return template.zone_consistency

        # Calculer manuellement si pas dans un template
        zone_dist = analysis.get_zone_distribution_for_value(value)
        total = sum(zone_dist.values())
        if total == 0:
            return 0.0

        max_count = max(zone_dist.values())
        return max_count / total


# === Singleton ===

_detector_instance: Optional[TemplateDetector] = None


def get_template_detector(
    min_pages_ratio: float = 0.3,
    min_occurrences: int = 2,
) -> TemplateDetector:
    """
    Retourne l'instance singleton du TemplateDetector.

    Args:
        min_pages_ratio: Ratio minimum de pages couvertes
        min_occurrences: Nombre minimum d'occurrences

    Returns:
        Instance de TemplateDetector
    """
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = TemplateDetector(
            min_pages_ratio=min_pages_ratio,
            min_occurrences=min_occurrences,
        )
    return _detector_instance


__all__ = [
    "TemplateDetector",
    "get_template_detector",
]
