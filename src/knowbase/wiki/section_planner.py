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
        "En 2-3 paragraphes, présente le CONTEXTE et l'IMPORTANCE du concept : "
        "pourquoi il apparaît dans le corpus, quel rôle il joue, quels enjeux il soulève. "
        "NE PAS définir le concept ici (une section Définition existe pour ça). "
        "Concentre-toi sur la vue d'ensemble : contexte, portée, impact."
    ),
    "definition": (
        "Donne la DÉFINITION PRÉCISE du concept telle qu'elle ressort des sources. "
        "Si plusieurs définitions ou acceptions existent, présente-les en expliquant "
        "leurs nuances. NE PAS répéter le contexte ou l'importance (déjà couvert "
        "dans la Vue d'ensemble). Reste factuel et concis."
    ),
    "key_properties": (
        "Identifie les caractéristiques STRUCTURANTES du concept — les principes, "
        "mécanismes ou propriétés qui définissent son fonctionnement. "
        "Regroupe les détails similaires plutôt que de lister chaque fait séparément. "
        "Évite les détails d'implémentation très spécifiques (noms de champs, IDs techniques) "
        "sauf s'ils illustrent un principe important."
    ),
    "obligations": (
        "Présente les obligations et prescriptions avec une STRUCTURE CLAIRE. "
        "Use this Markdown format:\n"
        "1. Start with a SHORT introductory sentence summarizing the regulatory landscape.\n"
        "2. Then organize into THEMATIC SUB-GROUPS using **bold headings** followed by bullet lists:\n"
        "   **Thème 1 — Titre court**\n"
        "   - Obligation ou prescription [source, unit_id]\n"
        "   - Autre point [source, unit_id]\n\n"
        "   **Thème 2 — Titre court**\n"
        "   - ...\n"
        "3. Within each group, distinguish clearly:\n"
        "   - 🔴 Obligations (must/shall) — use firm language\n"
        "   - 🟡 Recommendations (should/recommended) — use nuanced language\n"
        "   - 🟢 Permissions (may/can) — indicate optional nature\n"
        "4. Do NOT write a wall of prose. Use bullet points for each individual prescription.\n"
        "5. IMPORTANT: Focus on GENERAL PRINCIPLES and high-level rules, not low-level "
        "implementation details. If multiple evidence units describe similar specific procedures, "
        "synthesize them into a single bullet that captures the underlying rule or principle. "
        "Only mention specific technical details if they illustrate a broader concept."
    ),
    "temporal": (
        "Décris l'évolution chronologique du concept. "
        "Pour chaque étape, indique ce qui a changé et pourquoi si connu."
    ),
    "contradictions": (
        "Présente les contradictions détectées de manière structurée et pédagogique.\n\n"
        "RÈGLES DE FORMAT:\n"
        "1. Traite chaque contradiction SÉPARÉMENT avec un sous-titre **gras** décrivant le point de divergence.\n"
        "2. Pour chaque contradiction, si un terme technique ou une métrique apparaît, "
        "EXPLIQUE-LE brièvement en 1 phrase pour un lecteur non-spécialiste.\n"
        "3. Puis présente les deux valeurs en vis-à-vis avec leurs sources.\n"
        "4. Termine par une phrase d'interprétation neutre (pourquoi cette divergence peut exister : "
        "périmètres différents, méthodes de mesure, contextes, périodes, etc.).\n"
        "5. N'arbitre JAMAIS entre les sources. Reste factuel.\n\n"
        "STRUCTURE par contradiction:\n"
        "**[Point de divergence en langage clair]**\n\n"
        "[Si nécessaire, explication du terme/métrique clé]. Selon [Source A], [valeur A]. "
        "En revanche, [Source B] rapporte [valeur B]. "
        "[Hypothèse neutre sur l'origine de la divergence.]\n\n"
        "ADAPTER LE TON selon le type de tension fourni dans le JSON des conflits :\n"
        "- value_conflict : 'Les sources divergent sur ce point...'\n"
        "- scope_conflict : 'Cette valeur varie selon le contexte...'\n"
        "- temporal_conflict : 'La recommandation a évolué...'\n"
        "- complementary : 'Ces résultats éclairent des aspects différents...'\n"
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
        "Explique comment les concepts liés se rattachent au concept principal. "
        "Pour chaque relation, explique la NATURE du lien (est utilisé par, dépend de, "
        "est un sous-concept de...) plutôt que de simplement compter les co-occurrences."
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
    "contradictions": "Points de débat",
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

        # ── definition (exclure les units déjà dans overview pour éviter la redondance) ──
        def_ids = [
            u.unit_id for u in units
            if u.rhetorical_role == "definition" and u.unit_id not in assigned_ids
        ]
        if def_ids:
            sections.append(self._make_section("definition", def_ids))
            assigned_ids.update(def_ids)

        # ── key_properties (top units par weight, pas tous) ──
        prop_units = sorted(
            [u for u in units if u.rhetorical_role in ("mention", "context")],
            key=lambda u: u.weight,
            reverse=True,
        )
        MAX_KEY_PROPS = 15
        prop_ids = [u.unit_id for u in prop_units[:MAX_KEY_PROPS]]
        if len(prop_ids) >= 5:
            sections.append(self._make_section("key_properties", prop_ids))
            assigned_ids.update(prop_ids)

        # ── obligations (top units par weight, pas tous) ──
        oblig_units = sorted(
            [u for u in units if u.claim_type in ("PRESCRIPTIVE", "PERMISSIVE")],
            key=lambda u: u.weight,
            reverse=True,
        )
        MAX_OBLIGATIONS = 12
        oblig_ids = [u.unit_id for u in oblig_units[:MAX_OBLIGATIONS]]
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

        # ── contradictions (filtrées par show_in_article) ──
        article_conflicts = [
            c for c in pack.confirmed_conflicts
            if c.show_in_article and c.tension_level != "none"
        ]
        if article_conflicts:
            conflict_ids = []
            for c in article_conflicts:
                conflict_ids.extend([c.unit_id_a, c.unit_id_b])
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
