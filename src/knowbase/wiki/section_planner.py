"""
SectionPlanner — Brique 3 du Concept Assembly Engine (Phase 2).

Planification déterministe (sans LLM) des sections d'un article wiki
à partir d'un EvidencePack. Produit un ArticlePlan avec assignation
des evidence units aux sections.
"""

from __future__ import annotations

import logging
import re
from typing import List, Set

from knowbase.wiki.models import (
    ArticlePlan,
    EvidencePack,
    PlannedSection,
)

logger = logging.getLogger("[OSMOSE] section_planner")


# ─── Instructions de génération par type de section ─────────────────────

SECTION_INSTRUCTIONS = {
    "overview": (
        "Synthétise en 2-3 paragraphes les points essentiels du concept. "
        "Commence par une définition si disponible. Cite chaque source."
    ),
    "definition": (
        "Rédige une définition précise basée sur les sources documentaires. "
        "Si plusieurs définitions existent, présente-les toutes avec leurs sources."
    ),
    "key_properties": (
        "Liste et explique les caractéristiques principales du concept. "
        "Chaque caractéristique doit être sourcée."
    ),
    "obligations": (
        "Présente les obligations et prescriptions de manière structurée. "
        "Distingue les obligations (must/shall) des permissions (may/can)."
    ),
    "temporal": (
        "Décris l'évolution chronologique du concept. "
        "Pour chaque étape, indique ce qui a changé et pourquoi si connu."
    ),
    "contradictions": (
        "Présente de manière neutre les contradictions détectées. "
        "Cite les deux versions. N'arbitre pas entre les sources."
    ),
    "tensions": (
        "Ton prudent : 'il semble que...', 'divergence potentielle'. "
        "Présente les tensions sans conclure. Recommande une vérification."
    ),
    "scope": (
        "Décris la portée et l'applicabilité du concept selon les différents "
        "domaines et contextes identifiés dans les sources."
    ),
    "related": (
        "Présente les concepts liés et leur relation avec le concept principal. "
        "Indique le nombre de co-occurrences pour chaque lien."
    ),
    "sources": "",  # Déterministe, pas d'instructions LLM
}

# Titre français par type de section
SECTION_TITLES = {
    "overview": "Vue d'ensemble",
    "definition": "Définition",
    "key_properties": "Caractéristiques principales",
    "obligations": "Obligations et prescriptions",
    "temporal": "Évolution temporelle",
    "contradictions": "Contradictions détectées",
    "tensions": "Tensions à confirmer",
    "scope": "Portée et applicabilité",
    "related": "Concepts liés",
    "sources": "Sources documentaires",
}


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


class SectionPlanner:
    """Planifie les sections d'un article wiki à partir d'un EvidencePack."""

    def plan(self, pack: EvidencePack) -> ArticlePlan:
        """Produit un ArticlePlan déterministe depuis un EvidencePack."""
        units = pack.units
        unit_index = {u.unit_id: u for u in units}
        sections: List[PlannedSection] = []
        assigned_ids: Set[str] = set()
        is_small_pack = len(units) < 5

        # ── overview (TOUJOURS) ──
        top_ids = [u.unit_id for u in sorted(units, key=lambda u: u.weight, reverse=True)[:3]]
        sections.append(self._make_section("overview", top_ids))
        assigned_ids.update(top_ids)

        if is_small_pack:
            # Pack trop petit → seulement overview + sources
            sections.append(self._make_section("sources", [], is_deterministic=True))
            return self._build_plan(pack, sections, assigned_ids)

        # ── definition ──
        def_ids = [u.unit_id for u in units if u.rhetorical_role == "definition"]
        if def_ids:
            sections.append(self._make_section("definition", def_ids))
            assigned_ids.update(def_ids)

        # ── key_properties ──
        prop_ids = [
            u.unit_id for u in units
            if u.rhetorical_role in ("mention", "context")
        ]
        if len(prop_ids) >= 5:
            sections.append(self._make_section("key_properties", prop_ids))
            assigned_ids.update(prop_ids)

        # ── obligations ──
        oblig_ids = [
            u.unit_id for u in units
            if u.claim_type in ("PRESCRIPTIVE", "PERMISSIVE")
        ]
        if oblig_ids:
            sections.append(self._make_section("obligations", oblig_ids))
            assigned_ids.update(oblig_ids)

        # ── temporal ──
        if pack.temporal_evolution and pack.temporal_evolution.timeline:
            temporal_ids = []
            for step in pack.temporal_evolution.timeline:
                temporal_ids.extend(step.unit_ids)
            if temporal_ids:
                sections.append(self._make_section("temporal", temporal_ids))
                assigned_ids.update(temporal_ids)

        # ── contradictions ──
        if pack.confirmed_conflicts:
            conflict_ids = []
            for c in pack.confirmed_conflicts:
                conflict_ids.extend([c.unit_id_a, c.unit_id_b])
            # Garder uniquement les IDs existants
            conflict_ids = [uid for uid in conflict_ids if uid in unit_index]
            if conflict_ids:
                sections.append(self._make_section("contradictions", conflict_ids))
                assigned_ids.update(conflict_ids)

        # ── tensions ──
        if pack.candidate_tensions:
            tension_ids = []
            for t in pack.candidate_tensions:
                tension_ids.extend([t.unit_id_a, t.unit_id_b])
            tension_ids = [uid for uid in tension_ids if uid in unit_index]
            if tension_ids:
                sections.append(self._make_section("tensions", tension_ids))
                assigned_ids.update(tension_ids)

        # ── scope ──
        all_domains: Set[str] = set()
        for u in units:
            all_domains.update(u.facet_domains)
        if len(all_domains) >= 2:
            # Pas d'unit_ids — instructions contiennent le résumé des scopes
            scope_instructions = (
                SECTION_INSTRUCTIONS["scope"]
                + f" Domaines identifiés : {', '.join(sorted(all_domains))}."
            )
            sections.append(PlannedSection(
                section_type="scope",
                title=SECTION_TITLES["scope"],
                unit_ids=[],
                generation_instructions=scope_instructions,
            ))

        # ── related ──
        if len(pack.related_concepts) >= 2:
            related_ids = []
            for rc in pack.related_concepts:
                related_ids.extend(rc.supporting_unit_ids)
            related_ids = [uid for uid in related_ids if uid in unit_index]
            if related_ids:
                sections.append(self._make_section("related", related_ids))
                assigned_ids.update(related_ids)

        # ── sources (TOUJOURS, déterministe) ──
        sections.append(self._make_section("sources", [], is_deterministic=True))

        return self._build_plan(pack, sections, assigned_ids)

    def _make_section(
        self,
        section_type: str,
        unit_ids: List[str],
        is_deterministic: bool = False,
    ) -> PlannedSection:
        return PlannedSection(
            section_type=section_type,
            title=SECTION_TITLES[section_type],
            unit_ids=unit_ids,
            generation_instructions=SECTION_INSTRUCTIONS[section_type],
            is_deterministic=is_deterministic,
        )

    def _build_plan(
        self,
        pack: EvidencePack,
        sections: List[PlannedSection],
        assigned_ids: Set[str],
    ) -> ArticlePlan:
        all_ids = {u.unit_id for u in pack.units}
        unassigned = sorted(all_ids - assigned_ids)
        total_assigned = len(assigned_ids)

        logger.info(
            f"Plan: {len(sections)} sections, "
            f"{total_assigned}/{len(all_ids)} units assignés, "
            f"{len(unassigned)} non assignés"
        )

        return ArticlePlan(
            concept_name=pack.concept.canonical_name,
            slug=_slugify(pack.concept.canonical_name),
            sections=sections,
            total_units_assigned=total_assigned,
            unassigned_unit_ids=unassigned,
        )
