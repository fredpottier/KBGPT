"""
ConstrainedGenerator — Brique 4 du Concept Assembly Engine (Phase 2).

Génère un article wiki section par section via LLM, avec provenance
obligatoire et validation des citations. La section "sources" est
générée de manière déterministe (pas de LLM).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Set

from knowbase.wiki.models import (
    ArticlePlan,
    EvidencePack,
    EvidenceUnit,
    GeneratedArticle,
    GeneratedSection,
    PlannedSection,
)

logger = logging.getLogger("[OSMOSE] constrained_generator")

MAX_EVIDENCE_CHARS = 6000
MAX_TOKENS = 3000


DEFAULT_LANGUAGE = "français"


class ConstrainedGenerator:
    """Génère un article wiki contraint par les preuves d'un EvidencePack."""

    def __init__(self, language: str = DEFAULT_LANGUAGE):
        self._language = language

    def generate(self, pack: EvidencePack, plan: ArticlePlan) -> GeneratedArticle:
        """Génère l'article complet, section par section."""
        sections: List[GeneratedSection] = []

        for planned in plan.sections:
            if planned.is_deterministic:
                section = self._generate_sources_section(pack)
            else:
                section = self._generate_section(planned, pack)
            sections.append(section)
            logger.info(
                f"  Section '{section.section_type}': "
                f"confidence={section.confidence:.2f}, "
                f"citations={len(section.citations_used)}, "
                f"gaps={len(section.gaps)}"
            )

        all_citations = []
        all_gaps = []
        confidences = []
        for s in sections:
            all_citations.extend(s.citations_used)
            all_gaps.extend(s.gaps)
            confidences.append(s.confidence)

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return GeneratedArticle(
            concept_name=plan.concept_name,
            plan=plan,
            sections=sections,
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_citations=len(set(all_citations)),
            average_confidence=round(avg_conf, 3),
            all_gaps=all_gaps,
        )

    def _generate_section(
        self, section: PlannedSection, pack: EvidencePack
    ) -> GeneratedSection:
        """Génère une section via LLM."""
        evidence_json = self._build_evidence_json(section.unit_ids, pack, section)
        source_context = self._build_source_context(pack)

        # Lazy imports
        from knowbase.common.llm_router import complete_metadata_extraction
        from knowbase.config.prompts_loader import load_prompts, render_prompt

        # Charger et rendre le prompt depuis prompts.yaml
        registry = load_prompts()
        wiki_cfg = registry.get("wiki_article", {})
        system_tpl = wiki_cfg.get("system", "You are OSMOSE. Write in {{ language }}.")
        template = wiki_cfg.get("template", "")

        lang = self._language
        system_msg = render_prompt(system_tpl, language=lang)
        user_prompt = render_prompt(
            template,
            section_title=section.title,
            concept_name=pack.concept.canonical_name,
            generation_instructions=section.generation_instructions,
            evidence_json=evidence_json,
            source_context=source_context,
            language=lang,
        )

        messages = [
            {"role": "system", "content": system_msg.strip()},
            {"role": "user", "content": user_prompt.strip()},
        ]

        try:
            response = complete_metadata_extraction(
                messages=messages,
                max_tokens=MAX_TOKENS,
            )

            parsed = self._parse_llm_response(response, section)
            validated = self._validate_citations(parsed, pack)
            return validated

        except Exception as e:
            logger.error(f"Erreur génération section '{section.section_type}': {e}")
            return GeneratedSection(
                section_type=section.section_type,
                title=section.title,
                content="Génération échouée.",
                citations_used=[],
                confidence=0.0,
                gaps=[f"Erreur de génération : {str(e)}"],
            )

    def _build_source_context(self, pack: EvidencePack) -> str:
        """Construit un contexte sur la diversité des sources pour le prompt."""
        src_count = len(pack.source_index)
        total_units = sum(s.unit_count for s in pack.source_index)

        if src_count == 1:
            src = pack.source_index[0]
            return (
                f"SOURCE CONTEXT: All {total_units} evidence units come from a SINGLE document: "
                f"\"{src.doc_title or src.doc_id}\" ({src.doc_type or 'unknown type'}). "
                f"Acknowledge this limited perspective naturally in your writing. "
                f"Note in gaps what other document types would strengthen the coverage."
            )
        elif src_count <= 3:
            titles = [f"\"{s.doc_title or s.doc_id}\" ({s.unit_count} units)" for s in pack.source_index]
            return (
                f"SOURCE CONTEXT: Evidence comes from {src_count} documents: "
                f"{', '.join(titles)}. Cross-reference perspectives when possible."
            )
        else:
            return (
                f"SOURCE CONTEXT: Evidence is well-distributed across {src_count} documents "
                f"({total_units} total units). Synthesize across sources for a comprehensive view."
            )

    def _generate_sources_section(self, pack: EvidencePack) -> GeneratedSection:
        """Génère la section sources de manière déterministe (pas de LLM)."""
        lines = ["| Document | Type | Units | Contribution |", "|---|---|---|---|"]
        for src in pack.source_index:
            pct = f"{src.contribution_pct * 100:.0f}%"
            doc_type = src.doc_type or "—"
            lines.append(f"| {src.doc_title or src.doc_id} | {doc_type} | {src.unit_count} | {pct} |")

        return GeneratedSection(
            section_type="sources",
            title="Sources documentaires",
            content="\n".join(lines),
            citations_used=[],
            confidence=1.0,
            gaps=[],
        )

    def _build_evidence_json(
        self,
        unit_ids: List[str],
        pack: EvidencePack,
        section: PlannedSection,
    ) -> str:
        """Construit le JSON d'evidence filtré pour une section."""
        unit_index: Dict[str, EvidenceUnit] = {u.unit_id: u for u in pack.units}

        # Units assignés à cette section
        selected = [unit_index[uid] for uid in unit_ids if uid in unit_index]

        evidence: Dict = {"units": []}

        for u in selected:
            evidence["units"].append({
                "unit_id": u.unit_id,
                "text": u.text,
                "doc_title": u.doc_title,
                "rhetorical_role": u.rhetorical_role,
                "claim_type": u.claim_type,
            })

        # Enrichissement contextuel par type de section
        if section.section_type == "contradictions" and pack.confirmed_conflicts:
            evidence["conflicts"] = [
                {
                    "unit_a": c.unit_id_a,
                    "unit_b": c.unit_id_b,
                    "type": c.conflict_type,
                    "description": c.description,
                }
                for c in pack.confirmed_conflicts
            ]

        if section.section_type == "tensions" and pack.candidate_tensions:
            evidence["tensions"] = [
                {
                    "unit_a": t.unit_id_a,
                    "unit_b": t.unit_id_b,
                    "type": t.tension_type,
                    "description": t.description,
                }
                for t in pack.candidate_tensions
            ]

        if section.section_type == "temporal" and pack.temporal_evolution:
            evidence["timeline"] = [
                {
                    "axis_value": step.axis_value,
                    "change_type": step.change_type,
                    "unit_ids": step.unit_ids,
                }
                for step in pack.temporal_evolution.timeline
            ]

        if section.section_type == "related" and pack.related_concepts:
            evidence["related_concepts"] = [
                {
                    "entity_name": rc.entity_name,
                    "entity_type": rc.entity_type,
                    "co_occurrence_count": rc.co_occurrence_count,
                }
                for rc in pack.related_concepts
            ]

        if section.section_type == "scope":
            # Résumé des scope_signatures distinctes
            scopes = set()
            for u in pack.units:
                sig = u.scope_signature
                scope_key = f"{sig.generality_level}/{sig.geographic_scope or 'N/A'}/{sig.source_granularity}"
                scopes.add(scope_key)
            evidence["scope_signatures"] = sorted(scopes)

        result = json.dumps(evidence, ensure_ascii=False, indent=2)

        # Troncature si trop long
        if len(result) > MAX_EVIDENCE_CHARS:
            truncated_units, current_len = self._truncate_units(
                selected, pack, section
            )

            evidence["units"] = [
                {
                    "unit_id": u.unit_id,
                    "text": u.text,
                    "doc_title": u.doc_title,
                    "rhetorical_role": u.rhetorical_role,
                    "claim_type": u.claim_type,
                }
                for u in truncated_units
            ]
            result = json.dumps(evidence, ensure_ascii=False, indent=2)
            logger.warning(
                f"Evidence tronquée pour section '{section.section_type}': "
                f"{len(selected)} → {len(truncated_units)} units"
            )

        return result

    def _truncate_units(
        self,
        selected: List[EvidenceUnit],
        pack: EvidencePack,
        section: PlannedSection,
    ) -> tuple:
        """Tronque les units en respectant la limite de caractères.

        Pour la section 'related', garantit au moins 1 unit par concept lié
        (meilleur weight) avant de remplir avec le reste par weight décroissant.
        """
        priority_ids: Set[str] = set()

        if section.section_type == "related" and pack.related_concepts:
            selected_ids = {u.unit_id for u in selected}
            for rc in pack.related_concepts:
                # Prendre le premier supporting_unit_id présent dans selected
                for uid in rc.supporting_unit_ids:
                    if uid in selected_ids:
                        priority_ids.add(uid)
                        break

        # Trier : priority units en premier, puis par weight décroissant
        priority_units = [u for u in selected if u.unit_id in priority_ids]
        rest_units = sorted(
            [u for u in selected if u.unit_id not in priority_ids],
            key=lambda u: u.weight,
            reverse=True,
        )
        ordered = priority_units + rest_units

        truncated_units = []
        current_len = 200  # Marge pour le contexte additionnel
        for u in ordered:
            entry = json.dumps({
                "unit_id": u.unit_id,
                "text": u.text,
                "doc_title": u.doc_title,
                "rhetorical_role": u.rhetorical_role,
                "claim_type": u.claim_type,
            }, ensure_ascii=False)
            if current_len + len(entry) > MAX_EVIDENCE_CHARS:
                break
            truncated_units.append(u)
            current_len += len(entry)

        return truncated_units, current_len

    def _parse_llm_response(
        self, response: str, section: PlannedSection
    ) -> GeneratedSection:
        """Parse la réponse JSON du LLM."""
        text = response.strip()

        # Nettoyage des markers ```json
        if text.startswith("```"):
            # Retirer première ligne (```json) et dernière (```)
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Parse JSON échoué pour section '{section.section_type}': {e}")
            return GeneratedSection(
                section_type=section.section_type,
                title=section.title,
                content="Génération échouée.",
                citations_used=[],
                confidence=0.0,
                gaps=[f"Erreur de parsing JSON : {str(e)}"],
            )

        raw_gaps = data.get("gaps", [])
        filtered_gaps = self._filter_placeholder_gaps(raw_gaps)

        return GeneratedSection(
            section_type=section.section_type,
            title=section.title,
            content=data.get("content", ""),
            citations_used=data.get("citations_used", []),
            confidence=float(data.get("confidence", 0.5)),
            gaps=filtered_gaps,
        )

    def _validate_citations(
        self, section: GeneratedSection, pack: EvidencePack
    ) -> GeneratedSection:
        """Vérifie que les citations référencent des unit_ids réels."""
        valid_ids = {u.unit_id for u in pack.units}
        valid_citations = []
        phantom_count = 0

        for cid in section.citations_used:
            if cid in valid_ids:
                valid_citations.append(cid)
            else:
                phantom_count += 1
                logger.warning(f"Citation fantôme retirée : {cid}")

        adjusted_confidence = max(0.0, section.confidence - 0.1 * phantom_count)

        return GeneratedSection(
            section_type=section.section_type,
            title=section.title,
            content=section.content,
            citations_used=valid_citations,
            confidence=round(adjusted_confidence, 3),
            gaps=section.gaps,
        )

    @staticmethod
    def _filter_placeholder_gaps(gaps: List[str]) -> List[str]:
        """Retire les gaps génériques/placeholders produits par le LLM."""
        placeholder_patterns = [
            r"^[Ii]nformation manquante\s*\d*$",
            r"^[Gg]ap\s*\d*$",
            r"^[Ll]acune\s*\d*$",
            r"^[Mm]issing info(rmation)?\s*\d*$",
            r"^N/?A$",
            r"^\.\.\.$",
        ]
        filtered = []
        for gap in gaps:
            g = gap.strip()
            if not g:
                continue
            if any(re.match(p, g) for p in placeholder_patterns):
                continue
            filtered.append(g)
        return filtered

    @staticmethod
    def _strip_repeated_title(content: str, title: str) -> str:
        """Retire le titre de section si le LLM l'a répété en début de contenu."""
        stripped = content.lstrip()
        # Patterns : "## Titre", "**Titre**", "Titre\n", "# Titre"
        for prefix in [
            f"## {title}",
            f"# {title}",
            f"**{title}**",
            title,
        ]:
            if stripped.lower().startswith(prefix.lower()):
                stripped = stripped[len(prefix):].lstrip(" \t\n:-")
                break
        return stripped

    @staticmethod
    def _clean_unknown_citations(content: str) -> str:
        """Retire les citations contenant 'unknown' comme unit_id."""
        # [doc_title, unknown] → [doc_title]
        content = re.sub(r'\[([^,\]]+),\s*unknown\]', r'[\1]', content)
        return content

    @staticmethod
    def _clean_unit_ids_from_citations(content: str) -> str:
        """Retire les unit_ids des citations pour le rendu lisible.

        [doc_title, eu_abc123] → [doc_title]
        [doc_title, eu_abc123, eu_def456] → [doc_title]
        """
        # Multi unit_ids: [doc_title, eu_xxx, eu_yyy, ...]
        content = re.sub(
            r'\[([^,\]]+?)(?:,\s*eu_[a-f0-9]+)+\]',
            r'[\1]',
            content,
        )
        return content

    def render_markdown(self, article: GeneratedArticle) -> str:
        """Produit le rendu Markdown final de l'article."""
        lines = [
            f"# {article.concept_name}",
            "",
            f"*Article généré par OSMOSE — {article.generated_at} "
            f"| Langue : {self._language} "
            f"| Confiance moyenne : {article.average_confidence * 100:.0f}%*",
            "",
            "---",
            "",
        ]

        for section in article.sections:
            lines.append(f"## {section.title}")
            lines.append("")
            content = self._strip_repeated_title(section.content, section.title)
            content = self._clean_unknown_citations(content)
            content = self._clean_unit_ids_from_citations(content)
            lines.append(content)
            lines.append("")

        if article.all_gaps:
            lines.append("---")
            lines.append("")
            lines.append("### Lacunes identifiées")
            lines.append("")
            for gap in article.all_gaps:
                lines.append(f"- {gap}")
            lines.append("")

        return "\n".join(lines)
