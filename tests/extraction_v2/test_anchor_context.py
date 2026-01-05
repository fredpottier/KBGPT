"""
Tests pour AnchorContext (PR2 - ADR_ASSERTION_AWARE_KG).

Teste:
- Heuristics: detection polarity, markers, override
- AnchorContextAnalyzer: orchestration heuristics + LLM
- InheritanceEngine: matrice d'heritage DocContext -> AnchorContext
- ProtoConceptContext: agregation des contextes anchors
"""

import pytest
from knowbase.extraction_v2.context.anchor_models import (
    Polarity,
    AssertionScope,
    OverrideType,
    QualifierSource,
    LocalMarker,
    AnchorContext,
    ProtoConceptContext,
)
from knowbase.extraction_v2.context.heuristics import (
    PassageHeuristics,
    HeuristicResult,
    detect_polarity_simple,
    detect_local_markers_simple,
)
from knowbase.extraction_v2.context.anchor_context_analyzer import (
    AnchorContextAnalyzer,
    get_anchor_context_analyzer,
)
from knowbase.extraction_v2.context.inheritance import (
    InheritanceEngine,
    InheritanceRule,
    get_inheritance_engine,
)
from knowbase.extraction_v2.context.models import (
    DocScope,
    DocContextFrame,
)


class TestPolarity:
    """Tests pour Polarity enum."""

    def test_values(self):
        assert Polarity.POSITIVE.value == "positive"
        assert Polarity.NEGATIVE.value == "negative"
        assert Polarity.FUTURE.value == "future"
        assert Polarity.DEPRECATED.value == "deprecated"
        assert Polarity.CONDITIONAL.value == "conditional"
        assert Polarity.UNKNOWN.value == "unknown"

    def test_from_string(self):
        assert Polarity("positive") == Polarity.POSITIVE
        assert Polarity("negative") == Polarity.NEGATIVE
        assert Polarity("deprecated") == Polarity.DEPRECATED


class TestAssertionScope:
    """Tests pour AssertionScope enum."""

    def test_values(self):
        assert AssertionScope.GENERAL.value == "general"
        assert AssertionScope.CONSTRAINED.value == "constrained"
        assert AssertionScope.UNKNOWN.value == "unknown"


class TestLocalMarker:
    """Tests pour LocalMarker."""

    def test_creation(self):
        m = LocalMarker(
            value="1809",
            evidence="applies to 1809 only",
            confidence=0.9,
        )
        assert m.value == "1809"
        assert m.confidence == 0.9

    def test_serialization(self):
        m = LocalMarker(value="FPS03", evidence="FPS03 release", confidence=0.8)
        d = m.to_dict()
        assert d["value"] == "FPS03"
        assert d["confidence"] == 0.8

        m2 = LocalMarker.from_dict(d)
        assert m2.value == m.value


class TestAnchorContext:
    """Tests pour AnchorContext."""

    def test_creation(self):
        ctx = AnchorContext(
            polarity=Polarity.NEGATIVE,
            scope=AssertionScope.CONSTRAINED,
            local_markers=[LocalMarker(value="1809", evidence="", confidence=0.9)],
            is_override=False,
            confidence=0.85,
            qualifier_source=QualifierSource.EXPLICIT,
        )
        assert ctx.polarity == Polarity.NEGATIVE
        assert ctx.scope == AssertionScope.CONSTRAINED
        assert ctx.has_local_markers()
        assert ctx.get_markers() == ["1809"]

    def test_neutral(self):
        ctx = AnchorContext.neutral()
        assert ctx.polarity == Polarity.POSITIVE
        assert ctx.scope == AssertionScope.UNKNOWN
        assert ctx.confidence == 0.3

    def test_serialization(self):
        ctx = AnchorContext(
            polarity=Polarity.FUTURE,
            scope=AssertionScope.GENERAL,
            confidence=0.7,
        )
        d = ctx.to_dict()
        assert d["polarity"] == "future"
        assert d["scope"] == "general"

        ctx2 = AnchorContext.from_dict(d)
        assert ctx2.polarity == ctx.polarity
        assert ctx2.scope == ctx.scope


class TestPassageHeuristics:
    """Tests pour PassageHeuristics."""

    @pytest.fixture
    def heuristics(self):
        return PassageHeuristics()

    def test_detect_negation(self, heuristics):
        """Test detection de negation."""
        result = heuristics.analyze("This feature is not available in 1809")
        assert result.polarity == Polarity.NEGATIVE
        assert result.polarity_confidence >= 0.6

    def test_detect_future(self, heuristics):
        """Test detection de futur."""
        result = heuristics.analyze("This will be available in the next release")
        assert result.polarity == Polarity.FUTURE
        assert "will be" in result.polarity_evidence[0].lower() or "next release" in result.polarity_evidence[0].lower()

    def test_detect_deprecated(self, heuristics):
        """Test detection de deprecated."""
        result = heuristics.analyze("This function is deprecated since 2020")
        assert result.polarity == Polarity.DEPRECATED
        assert result.polarity_confidence >= 0.7

    def test_detect_conditional(self, heuristics):
        """Test detection de conditional."""
        result = heuristics.analyze("If you enable this option, the feature becomes active")
        assert result.polarity == Polarity.CONDITIONAL

    def test_detect_positive_default(self, heuristics):
        """Test detection positive par defaut."""
        result = heuristics.analyze("The system provides comprehensive reporting capabilities")
        assert result.polarity == Polarity.POSITIVE

    def test_detect_local_markers_version(self, heuristics):
        """Test detection de marqueurs version."""
        result = heuristics.analyze("This applies to S/4HANA 1809 FPS03")
        markers = [m.value for m in result.local_markers]
        assert "1809" in markers
        assert "FPS03" in markers

    def test_detect_local_markers_year(self, heuristics):
        """Test detection de marqueurs annee."""
        result = heuristics.analyze("Available in the 2025 edition")
        markers = [m.value for m in result.local_markers]
        assert "2025" in markers

    def test_detect_override_switch(self, heuristics):
        """Test detection d'override switch."""
        result = heuristics.analyze("Unlike 1809, the 2020 version has this feature")
        assert result.is_override
        assert result.override_type == OverrideType.SWITCH

    def test_detect_override_range(self, heuristics):
        """Test detection d'override range."""
        result = heuristics.analyze("Starting with version 2020, this is enabled")
        assert result.is_override
        assert result.override_type == OverrideType.RANGE

    def test_detect_override_generalization(self, heuristics):
        """Test detection d'override generalization."""
        result = heuristics.analyze("This applies to all versions of the product")
        assert result.is_override
        assert result.override_type == OverrideType.GENERALIZATION

    def test_needs_llm_for_override(self, heuristics):
        """Test que override declenche needs_llm."""
        result = heuristics.analyze("Unlike previous versions, this feature is now available")
        assert result.is_override
        assert result.needs_llm  # Override detecte = besoin LLM

    def test_short_passage(self, heuristics):
        """Test passage trop court."""
        result = heuristics.analyze("Hi")
        assert result.polarity == Polarity.POSITIVE
        assert result.polarity_confidence == 0.3


class TestDetectPolaritySimple:
    """Tests pour detect_polarity_simple."""

    def test_deprecated(self):
        assert detect_polarity_simple("This is deprecated") == Polarity.DEPRECATED

    def test_future(self):
        assert detect_polarity_simple("Will be available soon") == Polarity.FUTURE

    def test_negative(self):
        assert detect_polarity_simple("This is not supported") == Polarity.NEGATIVE

    def test_conditional(self):
        assert detect_polarity_simple("If enabled, this works") == Polarity.CONDITIONAL

    def test_positive(self):
        assert detect_polarity_simple("The feature provides value") == Polarity.POSITIVE


class TestDetectLocalMarkersSimple:
    """Tests pour detect_local_markers_simple."""

    def test_detect_version(self):
        markers = detect_local_markers_simple("S/4HANA 1809 release")
        assert "1809" in markers

    def test_detect_fps(self):
        markers = detect_local_markers_simple("FPS03 update")
        assert "FPS03" in markers

    def test_detect_multiple(self):
        markers = detect_local_markers_simple("From 2020 to 2023, FPS05 is required")
        assert "2020" in markers
        assert "2023" in markers
        assert "FPS05" in markers


class TestAnchorContextAnalyzer:
    """Tests pour AnchorContextAnalyzer."""

    @pytest.fixture
    def analyzer(self):
        return AnchorContextAnalyzer(use_llm=False)

    def test_analyze_sync_negative(self, analyzer):
        """Test analyse synchrone avec negation."""
        ctx = analyzer.analyze_sync("This feature is not available")
        assert ctx.polarity == Polarity.NEGATIVE

    def test_analyze_sync_with_markers(self, analyzer):
        """Test analyse synchrone avec marqueurs."""
        ctx = analyzer.analyze_sync("Available in 1809 only")
        assert ctx.has_local_markers()
        assert "1809" in ctx.get_markers()
        assert ctx.scope == AssertionScope.CONSTRAINED
        assert ctx.qualifier_source == QualifierSource.EXPLICIT

    def test_analyze_sync_with_doc_context(self, analyzer):
        """Test analyse avec doc_context herite."""
        doc_context = DocContextFrame(
            document_id="test",
            strong_markers=["2020"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.9,
        )
        ctx = analyzer.analyze_sync(
            passage="The system provides this capability",
            doc_context=doc_context,
        )
        # Devrait heriter du doc_context si pas de markers locaux
        # Le passage ne contient pas de markers, donc heritage
        assert ctx.qualifier_source in (
            QualifierSource.INHERITED_STRONG,
            QualifierSource.INHERITED_WEAK,
            QualifierSource.NONE
        )

    def test_analyze_sync_empty_passage(self, analyzer):
        """Test avec passage vide."""
        ctx = analyzer.analyze_sync("")
        assert ctx == AnchorContext.neutral()

    @pytest.mark.asyncio
    async def test_analyze_async_without_llm(self, analyzer):
        """Test analyse async sans LLM (fallback heuristiques)."""
        ctx = await analyzer.analyze("This is deprecated in 1809")
        assert ctx.polarity == Polarity.DEPRECATED
        assert ctx.has_local_markers()

    def test_get_singleton(self):
        """Test que get_anchor_context_analyzer retourne singleton."""
        a1 = get_anchor_context_analyzer()
        a2 = get_anchor_context_analyzer()
        assert a1 is a2


class TestInheritanceEngine:
    """Tests pour InheritanceEngine."""

    @pytest.fixture
    def engine(self):
        return InheritanceEngine()

    def test_override_wins(self, engine):
        """Test que override local gagne sur heritage."""
        doc_context = DocContextFrame(
            document_id="test",
            strong_markers=["1809"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.9,
        )
        local_markers = [LocalMarker(value="2020", evidence="", confidence=0.9)]

        scope, source, inherited, conf = engine.apply_inheritance(
            doc_context=doc_context,
            local_markers=local_markers,
            is_override=True,
        )

        assert scope == AssertionScope.CONSTRAINED
        assert source == QualifierSource.EXPLICIT
        assert inherited == []  # Pas d'heritage car override

    def test_explicit_markers_win(self, engine):
        """Test que marqueurs explicites gagnent."""
        doc_context = DocContextFrame(
            document_id="test",
            strong_markers=["1809"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.9,
        )
        local_markers = [LocalMarker(value="2020", evidence="", confidence=0.9)]

        scope, source, inherited, conf = engine.apply_inheritance(
            doc_context=doc_context,
            local_markers=local_markers,
            is_override=False,
        )

        assert scope == AssertionScope.CONSTRAINED
        assert source == QualifierSource.EXPLICIT
        assert inherited == []

    def test_inherit_strong(self, engine):
        """Test heritage strong markers."""
        doc_context = DocContextFrame(
            document_id="test",
            strong_markers=["1809"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.9,
        )

        scope, source, inherited, conf = engine.apply_inheritance(
            doc_context=doc_context,
            local_markers=[],
            is_override=False,
        )

        assert scope == AssertionScope.CONSTRAINED
        assert source == QualifierSource.INHERITED_STRONG
        assert "1809" in inherited
        assert conf == 0.95

    def test_inherit_weak(self, engine):
        """Test heritage weak markers."""
        doc_context = DocContextFrame(
            document_id="test",
            weak_markers=["FPS03"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.7,
        )

        scope, source, inherited, conf = engine.apply_inheritance(
            doc_context=doc_context,
            local_markers=[],
            is_override=False,
        )

        assert scope == AssertionScope.CONSTRAINED
        assert source == QualifierSource.INHERITED_WEAK
        assert "FPS03" in inherited
        assert conf == 0.85

    def test_mixed_no_inheritance(self, engine):
        """Test que MIXED scope n'herite pas."""
        doc_context = DocContextFrame(
            document_id="test",
            strong_markers=["1809", "2020"],
            doc_scope=DocScope.MIXED,
            scope_confidence=0.5,
        )

        scope, source, inherited, conf = engine.apply_inheritance(
            doc_context=doc_context,
            local_markers=[],
            is_override=False,
        )

        assert scope == AssertionScope.UNKNOWN
        assert source == QualifierSource.NONE
        assert inherited == []

    def test_general_scope(self, engine):
        """Test doc scope GENERAL."""
        doc_context = DocContextFrame(
            document_id="test",
            doc_scope=DocScope.GENERAL,
            scope_confidence=0.8,
        )

        scope, source, inherited, conf = engine.apply_inheritance(
            doc_context=doc_context,
            local_markers=[],
            is_override=False,
        )

        assert scope == AssertionScope.GENERAL
        assert source == QualifierSource.NONE

    def test_no_doc_context(self, engine):
        """Test sans doc_context."""
        scope, source, inherited, conf = engine.apply_inheritance(
            doc_context=None,
            local_markers=[],
            is_override=False,
        )

        assert scope == AssertionScope.UNKNOWN
        assert source == QualifierSource.NONE
        assert conf == 0.5

    def test_compute_final_context(self, engine):
        """Test compute_final_context."""
        doc_context = DocContextFrame(
            document_id="test",
            strong_markers=["1809"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.9,
        )

        ctx = engine.compute_final_context(
            polarity=Polarity.POSITIVE,
            polarity_confidence=0.8,
            doc_context=doc_context,
            local_markers=[],
            is_override=False,
        )

        assert ctx.polarity == Polarity.POSITIVE
        assert ctx.scope == AssertionScope.CONSTRAINED
        assert ctx.qualifier_source == QualifierSource.INHERITED_STRONG
        # Markers herites
        assert any(m.value == "1809" for m in ctx.local_markers)

    def test_get_singleton(self):
        """Test singleton."""
        e1 = get_inheritance_engine()
        e2 = get_inheritance_engine()
        assert e1 is e2


class TestProtoConceptContext:
    """Tests pour ProtoConceptContext."""

    def test_empty(self):
        """Test contexte vide."""
        ctx = ProtoConceptContext()
        assert ctx.polarity == Polarity.UNKNOWN
        assert ctx.scope == AssertionScope.UNKNOWN
        assert not ctx.has_conflict

    def test_from_anchors_all_positive(self):
        """Test agregation anchors tous positifs."""
        anchor_contexts = [
            AnchorContext(
                polarity=Polarity.POSITIVE,
                scope=AssertionScope.GENERAL,
                confidence=0.8,
            ),
            AnchorContext(
                polarity=Polarity.POSITIVE,
                scope=AssertionScope.GENERAL,
                confidence=0.9,
            ),
        ]
        ctx = ProtoConceptContext.from_anchors(anchor_contexts)

        assert ctx.polarity == Polarity.POSITIVE
        assert not ctx.has_conflict
        assert ctx.confidence == 0.85  # Moyenne

    def test_from_anchors_mixed_polarity(self):
        """Test agregation avec conflit polarite."""
        anchor_contexts = [
            AnchorContext(
                polarity=Polarity.POSITIVE,
                confidence=0.8,
            ),
            AnchorContext(
                polarity=Polarity.NEGATIVE,
                confidence=0.8,
            ),
        ]
        ctx = ProtoConceptContext.from_anchors(anchor_contexts)

        assert ctx.has_conflict
        assert "polarity_conflict" in ctx.conflict_flags[0]

    def test_from_anchors_constrained_wins(self):
        """Test que constrained avec haute confiance gagne."""
        anchor_contexts = [
            AnchorContext(
                scope=AssertionScope.GENERAL,
                confidence=0.6,
            ),
            AnchorContext(
                scope=AssertionScope.CONSTRAINED,
                confidence=0.9,
            ),
        ]
        ctx = ProtoConceptContext.from_anchors(anchor_contexts)

        assert ctx.scope == AssertionScope.CONSTRAINED

    def test_from_anchors_marker_aggregation(self):
        """Test agregation des marqueurs."""
        anchor_contexts = [
            AnchorContext(
                local_markers=[LocalMarker(value="1809", evidence="", confidence=0.9)],
                confidence=0.8,
            ),
            AnchorContext(
                local_markers=[LocalMarker(value="1809", evidence="", confidence=0.8)],
                confidence=0.9,
            ),
            AnchorContext(
                local_markers=[LocalMarker(value="2020", evidence="", confidence=0.7)],
                confidence=0.7,
            ),
        ]
        ctx = ProtoConceptContext.from_anchors(anchor_contexts)

        # 1809 devrait avoir le score le plus eleve (2 occurrences)
        assert "1809" in ctx.markers
        assert ctx.markers[0] == "1809"  # Premier car plus haut score

    def test_from_anchors_qualifier_source(self):
        """Test agregation qualifier source."""
        anchor_contexts = [
            AnchorContext(
                qualifier_source=QualifierSource.INHERITED_WEAK,
                confidence=0.7,
            ),
            AnchorContext(
                qualifier_source=QualifierSource.EXPLICIT,
                confidence=0.8,
            ),
        ]
        ctx = ProtoConceptContext.from_anchors(anchor_contexts)

        # EXPLICIT devrait gagner
        assert ctx.qualifier_source == QualifierSource.EXPLICIT

    def test_serialization(self):
        """Test serialisation."""
        ctx = ProtoConceptContext(
            polarity=Polarity.POSITIVE,
            scope=AssertionScope.CONSTRAINED,
            markers=["1809", "FPS03"],
            confidence=0.85,
        )
        d = ctx.to_dict()
        assert d["polarity"] == "positive"
        assert d["scope"] == "constrained"
        assert d["markers"] == ["1809", "FPS03"]

        ctx2 = ProtoConceptContext.from_dict(d)
        assert ctx2.polarity == ctx.polarity
        assert ctx2.markers == ctx.markers


class TestIntegrationPR2:
    """Tests d'integration PR2."""

    def test_full_flow_negative_with_marker(self):
        """Test flow complet: passage negatif avec marqueur."""
        # Passage test
        passage = "This feature is not available in SAP S/4HANA 1809"

        # Analyse heuristique
        heuristics = PassageHeuristics()
        hresult = heuristics.analyze(passage)

        assert hresult.polarity == Polarity.NEGATIVE
        assert any(m.value == "1809" for m in hresult.local_markers)

        # Analyse complete
        analyzer = AnchorContextAnalyzer(use_llm=False)
        ctx = analyzer.analyze_sync(passage)

        assert ctx.polarity == Polarity.NEGATIVE
        assert ctx.scope == AssertionScope.CONSTRAINED
        assert ctx.qualifier_source == QualifierSource.EXPLICIT

    def test_full_flow_with_inheritance(self):
        """Test flow complet avec heritage."""
        # Doc context
        doc_context = DocContextFrame(
            document_id="test",
            strong_markers=["2020"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.9,
        )

        # Passage sans marqueur
        passage = "The system provides comprehensive reporting capabilities"

        # Analyse
        analyzer = AnchorContextAnalyzer(use_llm=False)
        ctx = analyzer.analyze_sync(passage, doc_context)

        assert ctx.polarity == Polarity.POSITIVE
        assert ctx.scope == AssertionScope.CONSTRAINED  # Herite
        assert ctx.qualifier_source == QualifierSource.INHERITED_STRONG

    def test_full_flow_override(self):
        """Test flow complet avec override."""
        # Doc context
        doc_context = DocContextFrame(
            document_id="test",
            strong_markers=["1809"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.9,
        )

        # Passage avec override
        passage = "Unlike 1809, the 2020 version supports this feature"

        # Analyse
        analyzer = AnchorContextAnalyzer(use_llm=False)
        ctx = analyzer.analyze_sync(passage, doc_context)

        # Override detecte
        assert ctx.is_override
        # Markers locaux presents
        assert ctx.has_local_markers()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
