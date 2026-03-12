"""
Tests Phase 2 — Concept Assembly Engine : Article Generation.

Couvre :
- SectionPlanner (100% déterministe, pas de mock)
- ConstrainedGenerator : parsing, validation citations, rendu markdown
  (mock du LLM uniquement pour _generate_section)
- Modèles Pydantic (sérialisation round-trip)
"""

from __future__ import annotations

import json
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from knowbase.wiki.models import (
    ArticlePlan,
    CandidateTension,
    ConfirmedConflict,
    EvidencePack,
    EvidenceUnit,
    GeneratedArticle,
    GeneratedSection,
    PlannedSection,
    QualitySignals,
    RelatedConcept,
    ResolvedConcept,
    SourceEntry,
    TemporalEvolution,
    TemporalStep,
)
from knowbase.wiki.section_planner import SectionPlanner


# ─── Fixtures ────────────────────────────────────────────────────────────


def _make_unit(
    unit_id: str,
    text: str = "Texte de test.",
    rhetorical_role: str = "mention",
    claim_type: str | None = None,
    weight: float = 1.0,
    doc_id: str = "doc_001",
    doc_title: str = "Document Test",
    facet_domains: List[str] | None = None,
) -> EvidenceUnit:
    return EvidenceUnit(
        unit_id=unit_id,
        source_type="claim",
        source_id=f"claim_{unit_id}",
        text=text,
        doc_id=doc_id,
        doc_title=doc_title,
        rhetorical_role=rhetorical_role,
        claim_type=claim_type,
        weight=weight,
        facet_domains=facet_domains or [],
    )


def _make_resolved(name: str = "EDPB") -> ResolvedConcept:
    return ResolvedConcept(
        canonical_name=name,
        entity_type="concept",
        entity_ids=["e1"],
        claim_count=10,
        doc_ids=["doc_001"],
    )


def _make_rich_pack() -> EvidencePack:
    """Pack riche avec toutes les sections possibles."""
    units = [
        # Définitions
        _make_unit("u01", "EDPB est le comité européen.", "definition", "DEFINITIONAL", 2.0),
        _make_unit("u02", "EDPB signifie European Data Protection Board.", "definition", "DEFINITIONAL", 1.8),
        # Mentions/context (>= 5 pour key_properties)
        _make_unit("u03", "EDPB publie des lignes directrices.", "mention", weight=1.5),
        _make_unit("u04", "EDPB coordonne les autorités nationales.", "mention", weight=1.3),
        _make_unit("u05", "EDPB émet des avis contraignants.", "context", weight=1.2),
        _make_unit("u06", "EDPB assure la cohérence du RGPD.", "context", weight=1.1),
        _make_unit("u07", "EDPB siège à Bruxelles.", "mention", weight=1.0),
        # Prescriptif
        _make_unit("u08", "Les autorités doivent consulter l'EDPB.", "rule", "PRESCRIPTIVE", 1.4),
        _make_unit("u09", "L'EDPB peut émettre des recommandations.", "rule", "PERMISSIVE", 1.1),
        # Temporal (référencés par timeline)
        _make_unit("u10", "Créé en 2018 par le RGPD.", "context", weight=0.9),
        _make_unit("u11", "Extension des compétences en 2020.", "context", weight=0.8),
        # Contradictions
        _make_unit("u12", "EDPB a un pouvoir contraignant.", "rule", weight=1.0, doc_id="doc_002", doc_title="Doc B"),
        _make_unit("u13", "EDPB n'a qu'un rôle consultatif.", "rule", weight=1.0, doc_id="doc_003", doc_title="Doc C"),
        # Tensions
        _make_unit("u14", "EDPB intervient dans les cas transfrontaliers.", "mention", weight=0.7),
        _make_unit("u15", "Les DPA nationales restent souveraines.", "mention", weight=0.7),
        # Related concepts
        _make_unit("u16", "Le RGPD encadre l'EDPB.", "context", weight=0.6, facet_domains=["privacy", "regulation"]),
        _make_unit("u17", "Le DPO travaille avec l'EDPB.", "mention", weight=0.5, facet_domains=["privacy", "compliance"]),
    ]

    return EvidencePack(
        concept=_make_resolved("EDPB"),
        units=units,
        temporal_evolution=TemporalEvolution(
            axis_name="year",
            timeline=[
                TemporalStep(axis_value="2018", change_type="ADDED", unit_ids=["u10"]),
                TemporalStep(axis_value="2020", change_type="MODIFIED", unit_ids=["u11"]),
            ],
        ),
        confirmed_conflicts=[
            ConfirmedConflict(unit_id_a="u12", unit_id_b="u13", description="Pouvoir vs consultatif"),
        ],
        candidate_tensions=[
            CandidateTension(unit_id_a="u14", unit_id_b="u15", description="Souveraineté vs transfrontalier"),
        ],
        related_concepts=[
            RelatedConcept(
                entity_name="RGPD",
                entity_type="regulation",
                co_occurrence_count=5,
                supporting_unit_ids=["u16"],
            ),
            RelatedConcept(
                entity_name="DPO",
                entity_type="role",
                co_occurrence_count=3,
                supporting_unit_ids=["u17"],
            ),
        ],
        source_index=[
            SourceEntry(doc_id="doc_001", doc_title="Document Test", unit_count=12, contribution_pct=0.7),
            SourceEntry(doc_id="doc_002", doc_title="Doc B", unit_count=3, contribution_pct=0.18),
            SourceEntry(doc_id="doc_003", doc_title="Doc C", unit_count=2, contribution_pct=0.12),
        ],
        quality_signals=QualitySignals(
            total_units=17,
            claim_units=17,
            chunk_units=0,
            doc_count=3,
            type_diversity=4,
            has_definition=True,
            has_temporal_data=True,
            confirmed_conflict_count=1,
            candidate_tension_count=1,
            coverage_score=0.72,
            coherence_risk_score=0.3,
        ),
        generated_at="2026-03-12T10:00:00Z",
    )


def _make_small_pack() -> EvidencePack:
    """Pack avec < 5 units → seulement overview + sources."""
    units = [
        _make_unit("u01", "Controller is responsible for data processing.", "definition", weight=2.0),
        _make_unit("u02", "Controller determines purposes and means.", "mention", weight=1.5),
        _make_unit("u03", "Must maintain records of processing.", "rule", "PRESCRIPTIVE", weight=1.0),
    ]
    return EvidencePack(
        concept=_make_resolved("controller"),
        units=units,
        source_index=[
            SourceEntry(doc_id="doc_001", doc_title="Document Test", unit_count=3, contribution_pct=1.0),
        ],
        quality_signals=QualitySignals(total_units=3, claim_units=3, doc_count=1),
        generated_at="2026-03-12T10:00:00Z",
    )


# ═══════════════════════════════════════════════════════════════════════
# Tests Modèles Pydantic
# ═══════════════════════════════════════════════════════════════════════


class TestModels:
    def test_planned_section_defaults(self):
        s = PlannedSection(section_type="overview", title="Vue d'ensemble")
        assert s.unit_ids == []
        assert s.is_deterministic is False
        assert s.generation_instructions == ""

    def test_article_plan_round_trip(self):
        plan = ArticlePlan(
            concept_name="EDPB",
            slug="edpb",
            sections=[PlannedSection(section_type="overview", title="Vue d'ensemble", unit_ids=["u1"])],
            total_units_assigned=1,
        )
        data = plan.model_dump()
        restored = ArticlePlan.model_validate(data)
        assert restored.concept_name == "EDPB"
        assert len(restored.sections) == 1

    def test_generated_section_confidence_bounds(self):
        s = GeneratedSection(section_type="overview", title="T", content="C", confidence=1.0)
        assert s.confidence == 1.0

        with pytest.raises(Exception):
            GeneratedSection(section_type="overview", title="T", content="C", confidence=1.5)

    def test_generated_article_round_trip(self):
        plan = ArticlePlan(concept_name="X", slug="x", sections=[], total_units_assigned=0)
        article = GeneratedArticle(
            concept_name="X",
            plan=plan,
            sections=[],
            generated_at="2026-03-12T00:00:00Z",
            total_citations=0,
            average_confidence=0.0,
            all_gaps=["gap1"],
        )
        data = json.loads(article.model_dump_json())
        restored = GeneratedArticle.model_validate(data)
        assert restored.all_gaps == ["gap1"]


# ═══════════════════════════════════════════════════════════════════════
# Tests SectionPlanner
# ═══════════════════════════════════════════════════════════════════════


class TestSectionPlanner:
    def setup_method(self):
        self.planner = SectionPlanner()

    # ── Small pack ──

    def test_small_pack_only_overview_and_sources(self):
        pack = _make_small_pack()
        plan = self.planner.plan(pack)
        types = [s.section_type for s in plan.sections]
        assert types == ["overview", "sources"]

    def test_small_pack_overview_has_top_3(self):
        pack = _make_small_pack()
        plan = self.planner.plan(pack)
        overview = plan.sections[0]
        # Pack a 3 units, overview prend top 3
        assert len(overview.unit_ids) == 3

    def test_small_pack_sources_is_deterministic(self):
        pack = _make_small_pack()
        plan = self.planner.plan(pack)
        sources = [s for s in plan.sections if s.section_type == "sources"][0]
        assert sources.is_deterministic is True

    # ── Rich pack ──

    def test_rich_pack_all_sections_present(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        types = [s.section_type for s in plan.sections]
        expected = [
            "overview", "definition", "key_properties", "obligations",
            "temporal", "contradictions", "tensions", "scope", "related", "sources",
        ]
        assert types == expected

    def test_rich_pack_overview_is_first(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        assert plan.sections[0].section_type == "overview"

    def test_rich_pack_sources_is_last(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        assert plan.sections[-1].section_type == "sources"

    def test_rich_pack_overview_top3_by_weight(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        overview = plan.sections[0]
        assert len(overview.unit_ids) == 3
        # Top 3 by weight : u01(2.0), u02(1.8), u03(1.5)
        assert overview.unit_ids == ["u01", "u02", "u03"]

    def test_rich_pack_definition_units(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        defn = [s for s in plan.sections if s.section_type == "definition"][0]
        assert set(defn.unit_ids) == {"u01", "u02"}

    def test_rich_pack_obligations_units(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        oblig = [s for s in plan.sections if s.section_type == "obligations"][0]
        assert set(oblig.unit_ids) == {"u08", "u09"}

    def test_rich_pack_temporal_units(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        temporal = [s for s in plan.sections if s.section_type == "temporal"][0]
        assert set(temporal.unit_ids) == {"u10", "u11"}

    def test_rich_pack_contradictions_units(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        contradictions = [s for s in plan.sections if s.section_type == "contradictions"][0]
        assert set(contradictions.unit_ids) == {"u12", "u13"}

    def test_rich_pack_tensions_units(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        tensions = [s for s in plan.sections if s.section_type == "tensions"][0]
        assert set(tensions.unit_ids) == {"u14", "u15"}

    def test_rich_pack_scope_no_units_but_has_instructions(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        scope = [s for s in plan.sections if s.section_type == "scope"][0]
        assert scope.unit_ids == []
        assert "privacy" in scope.generation_instructions
        assert "compliance" in scope.generation_instructions

    def test_rich_pack_related_units(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        related = [s for s in plan.sections if s.section_type == "related"][0]
        assert set(related.unit_ids) == {"u16", "u17"}

    def test_rich_pack_slug(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        assert plan.slug == "edpb"

    def test_rich_pack_total_units_assigned(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        assert plan.total_units_assigned > 0
        # Tous les units doivent être assignés (au moins dans overview ou leur section)
        all_assigned = set()
        for s in plan.sections:
            all_assigned.update(s.unit_ids)
        assert len(all_assigned) == plan.total_units_assigned

    def test_units_can_overlap_across_sections(self):
        """Un unit peut apparaître dans plusieurs sections (overlap voulu)."""
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        # u01 est dans overview (top weight) ET dans definition
        overview_ids = set(plan.sections[0].unit_ids)
        defn_ids = set([s for s in plan.sections if s.section_type == "definition"][0].unit_ids)
        overlap = overview_ids & defn_ids
        assert "u01" in overlap

    def test_generation_instructions_not_empty(self):
        pack = _make_rich_pack()
        plan = self.planner.plan(pack)
        for s in plan.sections:
            if not s.is_deterministic:
                assert s.generation_instructions, f"Section {s.section_type} sans instructions"

    # ── Edge cases : sections conditionnelles ──

    def test_no_definition_section_without_definitions(self):
        """Pas de section definition si aucun unit n'a ce rôle."""
        pack = _make_rich_pack()
        # Changer tous les rôles definition → mention
        for u in pack.units:
            if u.rhetorical_role == "definition":
                u.rhetorical_role = "mention"
        plan = self.planner.plan(pack)
        types = [s.section_type for s in plan.sections]
        assert "definition" not in types

    def test_no_temporal_without_evolution(self):
        pack = _make_rich_pack()
        pack.temporal_evolution = None
        plan = self.planner.plan(pack)
        types = [s.section_type for s in plan.sections]
        assert "temporal" not in types

    def test_no_contradictions_without_conflicts(self):
        pack = _make_rich_pack()
        pack.confirmed_conflicts = []
        plan = self.planner.plan(pack)
        types = [s.section_type for s in plan.sections]
        assert "contradictions" not in types

    def test_no_tensions_without_candidates(self):
        pack = _make_rich_pack()
        pack.candidate_tensions = []
        plan = self.planner.plan(pack)
        types = [s.section_type for s in plan.sections]
        assert "tensions" not in types

    def test_no_scope_with_less_than_2_domains(self):
        pack = _make_rich_pack()
        for u in pack.units:
            u.facet_domains = []
        plan = self.planner.plan(pack)
        types = [s.section_type for s in plan.sections]
        assert "scope" not in types

    def test_no_related_with_less_than_2_concepts(self):
        pack = _make_rich_pack()
        pack.related_concepts = pack.related_concepts[:1]
        plan = self.planner.plan(pack)
        types = [s.section_type for s in plan.sections]
        assert "related" not in types

    def test_no_key_properties_below_threshold(self):
        """key_properties nécessite >= 5 units mention/context."""
        pack = _make_rich_pack()
        # Garder seulement 2 units mention/context
        for u in pack.units:
            if u.rhetorical_role in ("mention", "context"):
                u.rhetorical_role = "rule"
        plan = self.planner.plan(pack)
        types = [s.section_type for s in plan.sections]
        assert "key_properties" not in types

    def test_invalid_conflict_unit_ids_skipped(self):
        """Si un conflict référence un unit_id inexistant, il est filtré."""
        pack = _make_small_pack()
        # Forcer un pack >= 5 units pour dépasser le seuil small_pack
        for i in range(5):
            pack.units.append(_make_unit(f"extra_{i}", weight=0.5))
        pack.confirmed_conflicts = [
            ConfirmedConflict(unit_id_a="u01", unit_id_b="fantome_999"),
        ]
        plan = self.planner.plan(pack)
        contradictions = [s for s in plan.sections if s.section_type == "contradictions"]
        if contradictions:
            # u01 valide, fantome filtré
            assert "fantome_999" not in contradictions[0].unit_ids
            assert "u01" in contradictions[0].unit_ids


# ═══════════════════════════════════════════════════════════════════════
# Tests ConstrainedGenerator (parsing, validation, rendu)
# ═══════════════════════════════════════════════════════════════════════


class TestConstrainedGeneratorParsing:
    """Tests du parsing et de la validation — pas d'appel LLM."""

    def setup_method(self):
        from knowbase.wiki.constrained_generator import ConstrainedGenerator

        self.gen = ConstrainedGenerator()

    def test_parse_valid_json(self):
        section = PlannedSection(section_type="overview", title="Vue d'ensemble")
        response = json.dumps({
            "content": "L'EDPB est un organe européen [Document Test, u01].",
            "citations_used": ["u01", "u02"],
            "confidence": 0.85,
            "gaps": ["Pas d'historique complet"],
        })
        result = self.gen._parse_llm_response(response, section)
        assert result.content.startswith("L'EDPB")
        assert result.confidence == 0.85
        assert len(result.citations_used) == 2
        assert result.gaps == ["Pas d'historique complet"]

    def test_parse_json_with_markdown_markers(self):
        section = PlannedSection(section_type="overview", title="T")
        response = '```json\n{"content": "test", "citations_used": [], "confidence": 0.7, "gaps": []}\n```'
        result = self.gen._parse_llm_response(response, section)
        assert result.content == "test"
        assert result.confidence == 0.7

    def test_parse_invalid_json_fallback(self):
        section = PlannedSection(section_type="overview", title="T")
        result = self.gen._parse_llm_response("ceci n'est pas du JSON", section)
        assert result.content == "Génération échouée."
        assert result.confidence == 0.0

    def test_validate_citations_removes_phantoms(self):
        pack = _make_rich_pack()
        section = GeneratedSection(
            section_type="overview",
            title="T",
            content="Texte",
            citations_used=["u01", "fantome_1", "u02", "fantome_2"],
            confidence=0.9,
        )
        validated = self.gen._validate_citations(section, pack)
        assert validated.citations_used == ["u01", "u02"]
        # 2 phantômes → -0.2
        assert abs(validated.confidence - 0.7) < 0.001

    def test_validate_citations_all_valid(self):
        pack = _make_rich_pack()
        section = GeneratedSection(
            section_type="overview",
            title="T",
            content="Texte",
            citations_used=["u01", "u02"],
            confidence=0.9,
        )
        validated = self.gen._validate_citations(section, pack)
        assert validated.citations_used == ["u01", "u02"]
        assert validated.confidence == 0.9

    def test_validate_citations_confidence_floor_zero(self):
        pack = _make_small_pack()
        section = GeneratedSection(
            section_type="overview",
            title="T",
            content="Texte",
            citations_used=["f1", "f2", "f3", "f4", "f5"],
            confidence=0.3,
        )
        validated = self.gen._validate_citations(section, pack)
        assert validated.confidence == 0.0
        assert validated.citations_used == []


class TestConstrainedGeneratorSources:
    """Tests de la section sources déterministe."""

    def setup_method(self):
        from knowbase.wiki.constrained_generator import ConstrainedGenerator

        self.gen = ConstrainedGenerator()

    def test_sources_section_deterministic(self):
        pack = _make_rich_pack()
        result = self.gen._generate_sources_section(pack)
        assert result.section_type == "sources"
        assert result.confidence == 1.0
        assert result.citations_used == []
        assert "Document Test" in result.content
        assert "Doc B" in result.content
        assert "Doc C" in result.content

    def test_sources_section_is_markdown_table(self):
        pack = _make_rich_pack()
        result = self.gen._generate_sources_section(pack)
        lines = result.content.split("\n")
        assert lines[0].startswith("| Document")
        assert lines[1].startswith("|---")


class TestConstrainedGeneratorEvidence:
    """Tests du build d'evidence JSON."""

    def setup_method(self):
        from knowbase.wiki.constrained_generator import ConstrainedGenerator

        self.gen = ConstrainedGenerator()

    def test_build_evidence_basic(self):
        pack = _make_rich_pack()
        section = PlannedSection(section_type="overview", title="T", unit_ids=["u01", "u02"])
        result = self.gen._build_evidence_json(["u01", "u02"], pack, section)
        data = json.loads(result)
        assert len(data["units"]) == 2
        assert data["units"][0]["unit_id"] == "u01"

    def test_build_evidence_contradictions_enriched(self):
        pack = _make_rich_pack()
        section = PlannedSection(section_type="contradictions", title="T", unit_ids=["u12", "u13"])
        result = self.gen._build_evidence_json(["u12", "u13"], pack, section)
        data = json.loads(result)
        assert "conflicts" in data
        assert len(data["conflicts"]) == 1

    def test_build_evidence_temporal_enriched(self):
        pack = _make_rich_pack()
        section = PlannedSection(section_type="temporal", title="T", unit_ids=["u10", "u11"])
        result = self.gen._build_evidence_json(["u10", "u11"], pack, section)
        data = json.loads(result)
        assert "timeline" in data
        assert len(data["timeline"]) == 2

    def test_build_evidence_related_enriched(self):
        pack = _make_rich_pack()
        section = PlannedSection(section_type="related", title="T", unit_ids=["u16", "u17"])
        result = self.gen._build_evidence_json(["u16", "u17"], pack, section)
        data = json.loads(result)
        assert "related_concepts" in data

    def test_build_evidence_scope_enriched(self):
        pack = _make_rich_pack()
        section = PlannedSection(section_type="scope", title="T", unit_ids=[])
        result = self.gen._build_evidence_json([], pack, section)
        data = json.loads(result)
        assert "scope_signatures" in data

    def test_build_evidence_unknown_unit_id_skipped(self):
        pack = _make_rich_pack()
        section = PlannedSection(section_type="overview", title="T", unit_ids=["u01", "fantome"])
        result = self.gen._build_evidence_json(["u01", "fantome"], pack, section)
        data = json.loads(result)
        assert len(data["units"]) == 1


class TestPlaceholderGapFilter:
    """Tests du filtre de gaps génériques."""

    def setup_method(self):
        from knowbase.wiki.constrained_generator import ConstrainedGenerator

        self.gen = ConstrainedGenerator()

    def test_filters_numbered_placeholders(self):
        gaps = ["Information manquante 1", "Information manquante 2", "Vrai gap utile"]
        result = self.gen._filter_placeholder_gaps(gaps)
        assert result == ["Vrai gap utile"]

    def test_filters_various_patterns(self):
        gaps = ["Gap 1", "lacune 3", "N/A", "...", "Missing info 2", ""]
        result = self.gen._filter_placeholder_gaps(gaps)
        assert result == []

    def test_keeps_real_gaps(self):
        gaps = [
            "Aucune information sur l'architecture technique",
            "Pas de données sur les versions antérieures à 2020",
        ]
        result = self.gen._filter_placeholder_gaps(gaps)
        assert len(result) == 2

    def test_empty_gaps(self):
        assert self.gen._filter_placeholder_gaps([]) == []

    def test_parse_filters_gaps_automatically(self):
        section = PlannedSection(section_type="overview", title="T")
        response = json.dumps({
            "content": "Contenu.",
            "citations_used": [],
            "confidence": 0.8,
            "gaps": ["Information manquante 1", "Vrai gap", "Information manquante 2"],
        })
        result = self.gen._parse_llm_response(response, section)
        assert result.gaps == ["Vrai gap"]


class TestTruncationRelatedPriority:
    """Tests de la troncature avec priorité pour concepts liés."""

    def setup_method(self):
        from knowbase.wiki.constrained_generator import ConstrainedGenerator

        self.gen = ConstrainedGenerator()

    def test_related_priority_units_kept(self):
        """Les units de supporting_unit_ids sont prioritaires dans la troncature."""
        pack = _make_rich_pack()
        # u16 et u17 sont les supporting_unit_ids des 2 related concepts
        section = PlannedSection(
            section_type="related", title="T",
            unit_ids=["u16", "u17"],
        )
        truncated, _ = self.gen._truncate_units(
            [u for u in pack.units if u.unit_id in {"u16", "u17"}],
            pack, section,
        )
        ids = {u.unit_id for u in truncated}
        # Les deux doivent être présents (petite liste, pas de troncature réelle)
        assert "u16" in ids
        assert "u17" in ids

    def test_non_related_section_no_priority(self):
        """Pour les sections non-related, pas de priorité spéciale."""
        pack = _make_rich_pack()
        units = [u for u in pack.units if u.unit_id in {"u03", "u04", "u05"}]
        section = PlannedSection(section_type="overview", title="T", unit_ids=["u03", "u04", "u05"])
        truncated, _ = self.gen._truncate_units(units, pack, section)
        # Triés par weight décroissant (u03=1.5, u04=1.3, u05=1.2)
        assert truncated[0].unit_id == "u03"


class TestConstrainedGeneratorMarkdown:
    """Tests du rendu Markdown."""

    def setup_method(self):
        from knowbase.wiki.constrained_generator import ConstrainedGenerator

        self.gen = ConstrainedGenerator()

    def test_render_markdown_structure(self):
        plan = ArticlePlan(concept_name="EDPB", slug="edpb", sections=[], total_units_assigned=0)
        article = GeneratedArticle(
            concept_name="EDPB",
            plan=plan,
            sections=[
                GeneratedSection(section_type="overview", title="Vue d'ensemble", content="Contenu overview.", confidence=0.8),
                GeneratedSection(section_type="sources", title="Sources", content="| table |", confidence=1.0),
            ],
            generated_at="2026-03-12T10:00:00Z",
            total_citations=3,
            average_confidence=0.9,
            all_gaps=["Manque info X"],
        )
        md = self.gen.render_markdown(article)
        assert md.startswith("# EDPB")
        assert "Confiance moyenne : 90%" in md
        assert "## Vue d'ensemble" in md
        assert "Contenu overview." in md
        assert "## Sources" in md
        assert "### Lacunes identifiées" in md
        assert "- Manque info X" in md

    def test_render_markdown_no_gaps(self):
        plan = ArticlePlan(concept_name="X", slug="x", sections=[], total_units_assigned=0)
        article = GeneratedArticle(
            concept_name="X",
            plan=plan,
            sections=[],
            generated_at="2026-03-12",
            total_citations=0,
            average_confidence=0.5,
            all_gaps=[],
        )
        md = self.gen.render_markdown(article)
        assert "Lacunes" not in md


# ═══════════════════════════════════════════════════════════════════════
# Test d'intégration : SectionPlanner → ConstrainedGenerator (mock LLM)
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationPlanToArticle:
    """Test end-to-end avec mock du LLM."""

    def test_plan_then_generate_with_mock_llm(self):
        from knowbase.wiki.constrained_generator import ConstrainedGenerator

        pack = _make_rich_pack()
        planner = SectionPlanner()
        plan = planner.plan(pack)

        generator = ConstrainedGenerator()

        # Mock le LLM pour retourner du JSON valide
        def fake_complete(messages, max_tokens=2000, temperature=0.1):
            return json.dumps({
                "content": "Contenu généré pour test.",
                "citations_used": ["u01"],
                "confidence": 0.8,
                "gaps": [],
            })

        # Mock le prompts_loader
        fake_registry = {
            "wiki_article": {
                "system": "Tu es OSMOSE.",
                "template": "Section: {{ section_title }}. Evidence: {{ evidence_json }}",
            },
            "families": {"default": {}},
        }

        fake_llm = MagicMock()
        fake_llm.complete_metadata_extraction = fake_complete

        fake_prompts = MagicMock()
        fake_prompts.load_prompts = MagicMock(return_value=fake_registry)
        fake_prompts.render_prompt = MagicMock(return_value="rendered prompt")

        with patch.dict("sys.modules", {
            "knowbase.common.llm_router": fake_llm,
            "knowbase.config.prompts_loader": fake_prompts,
        }):
            article = generator.generate(pack, plan)

        assert article.concept_name == "EDPB"
        assert len(article.sections) == len(plan.sections)
        assert article.average_confidence > 0
        # La section sources est déterministe, les autres mockées
        sources = [s for s in article.sections if s.section_type == "sources"][0]
        assert sources.confidence == 1.0
        assert "Document Test" in sources.content

        # Le markdown est rendable
        md = generator.render_markdown(article)
        assert "# EDPB" in md
