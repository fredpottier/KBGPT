# Tests ADR SCOPE Discursive Candidate Mining
# Ref: doc/ongoing/ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md
#
# Ces tests valident les 6 invariants de l'ADR:
# - INV-SCOPE-01: Pas de relation Concept→Concept directe
# - INV-SCOPE-02: Marquage DISCURSIVE + basis=["SCOPE"]
# - INV-SCOPE-03: Multi-span ≥2 DocItems obligatoire
# - INV-SCOPE-04: ABSTAIN motivé (Miner ou Verifier)
# - INV-SCOPE-05: Budgets = garde-fous épistémiques
# - INV-SCOPE-06: Routing = query-time only

import pytest
from unittest.mock import MagicMock, patch

from knowbase.relations.types import (
    CandidatePair,
    CandidatePairStatus,
    DiscursiveAbstainReason,
    DiscursiveBasis,
    EvidenceBundle,
    EvidenceSpan,
    EvidenceSpanRole,
    RelationType,
    ScopeMiningConfig,
)
from knowbase.relations.scope_candidate_miner import (
    DocItemInfo,
    ConceptInScope,
    SectionScope,
    ScopeCandidateMiner,
    select_scope_setter,
    compute_salience_score,
    get_mining_stats,
)


# =============================================================================
# Tests select_scope_setter (algorithme déterministe)
# =============================================================================

class TestSelectScopeSetter:
    """Tests pour l'algorithme de sélection du scope_setter."""

    def test_empty_list_returns_none(self):
        """Liste vide → None."""
        result = select_scope_setter([])
        assert result is None

    def test_heading_has_priority(self):
        """Un heading est prioritaire sur tout autre DocItem."""
        doc_items = [
            DocItemInfo("di1", "Some text content", "text", "sec1", "doc1", 1),
            DocItemInfo("di2", "Introduction", "heading", "sec1", "doc1", 1),
            DocItemInfo("di3", "More content here", "text", "sec1", "doc1", 1),
        ]
        result = select_scope_setter(doc_items)
        assert result.doc_item_id == "di2"
        assert result.item_type == "heading"

    def test_textual_fallback_when_no_heading(self):
        """Sans heading, premier DocItem textuel > 20 chars."""
        doc_items = [
            DocItemInfo("di1", "Short", "text", "sec1", "doc1", 1),
            DocItemInfo("di2", "This is a longer text content", "text", "sec1", "doc1", 1),
            DocItemInfo("di3", "Another item", "text", "sec1", "doc1", 1),
        ]
        result = select_scope_setter(doc_items, min_text_length=20)
        assert result.doc_item_id == "di2"

    def test_fallback_to_first_item(self):
        """Fallback au premier item si tous sont courts."""
        doc_items = [
            DocItemInfo("di1", "Short", "text", "sec1", "doc1", 1),
            DocItemInfo("di2", "Also short", "text", "sec1", "doc1", 1),
        ]
        result = select_scope_setter(doc_items, min_text_length=50)
        assert result.doc_item_id == "di1"

    def test_multiple_headings_takes_first(self):
        """Plusieurs headings → prend le premier."""
        doc_items = [
            DocItemInfo("di1", "First Heading", "heading", "sec1", "doc1", 1),
            DocItemInfo("di2", "Second Heading", "heading", "sec1", "doc1", 1),
        ]
        result = select_scope_setter(doc_items)
        assert result.doc_item_id == "di1"


# =============================================================================
# Tests compute_salience_score
# =============================================================================

class TestComputeSalienceScore:
    """Tests pour le calcul du score de saillance."""

    def test_mention_count_matters(self):
        """Plus de mentions → score plus élevé."""
        c1 = ConceptInScope("c1", "Concept A", mention_count=5, first_position=0, doc_item_ids=[])
        c2 = ConceptInScope("c2", "Concept B", mention_count=2, first_position=0, doc_item_ids=[])

        score1 = compute_salience_score(c1, total_doc_items=10)
        score2 = compute_salience_score(c2, total_doc_items=10)

        assert score1 > score2

    def test_position_matters(self):
        """Position plus précoce → score plus élevé (à mentions égales)."""
        c1 = ConceptInScope("c1", "Concept A", mention_count=3, first_position=1, doc_item_ids=[])
        c2 = ConceptInScope("c2", "Concept B", mention_count=3, first_position=8, doc_item_ids=[])

        score1 = compute_salience_score(c1, total_doc_items=10)
        score2 = compute_salience_score(c2, total_doc_items=10)

        assert score1 > score2

    def test_zero_total_items_fallback(self):
        """Avec 0 items totaux, retourne juste mention_count."""
        c = ConceptInScope("c1", "Concept A", mention_count=5, first_position=0, doc_item_ids=[])
        score = compute_salience_score(c, total_doc_items=0)
        assert score == 5.0


# =============================================================================
# Tests EvidenceBundle (INV-SCOPE-03)
# =============================================================================

class TestEvidenceBundle:
    """Tests pour la validation des EvidenceBundle."""

    def test_valid_bundle_with_two_distinct_items(self):
        """Bundle valide: ≥2 DocItems distincts."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="di1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="Heading text",
                ),
                EvidenceSpan(
                    doc_item_id="di2",
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt="Concept mention",
                    concept_id="c1",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
        )
        assert bundle.is_valid() is True

    def test_invalid_bundle_single_item(self):
        """Bundle invalide: 1 seul DocItem."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="di1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="Text",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
        )
        assert bundle.is_valid() is False

    def test_invalid_bundle_same_item_twice(self):
        """Bundle invalide: même DocItem répété."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="di1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="Text",
                ),
                EvidenceSpan(
                    doc_item_id="di1",  # Même item!
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt="Same text",
                    concept_id="c1",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
        )
        assert bundle.is_valid() is False

    def test_get_scope_setter(self):
        """Récupère le span SCOPE_SETTER."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="di1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="Heading",
                ),
                EvidenceSpan(
                    doc_item_id="di2",
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt="Mention",
                    concept_id="c1",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
        )
        setter = bundle.get_scope_setter()
        assert setter is not None
        assert setter.doc_item_id == "di1"

    def test_get_mentions(self):
        """Récupère les spans MENTION."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="di1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="Heading",
                ),
                EvidenceSpan(
                    doc_item_id="di2",
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt="Mention 1",
                    concept_id="c1",
                ),
                EvidenceSpan(
                    doc_item_id="di3",
                    role=EvidenceSpanRole.MENTION,
                    text_excerpt="Mention 2",
                    concept_id="c2",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
        )
        mentions = bundle.get_mentions()
        assert len(mentions) == 2
        assert all(m.role == EvidenceSpanRole.MENTION for m in mentions)

    def test_to_json_serialization(self):
        """Sérialisation JSON pour stockage dans RawAssertion."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(
                    doc_item_id="di1",
                    role=EvidenceSpanRole.SCOPE_SETTER,
                    text_excerpt="Text",
                ),
            ],
            section_id="sec1",
            document_id="doc1",
        )
        json_str = bundle.to_json()
        assert isinstance(json_str, str)
        assert "SCOPE" in json_str
        assert "di1" in json_str


# =============================================================================
# Tests CandidatePair (INV-SCOPE-01, INV-SCOPE-04)
# =============================================================================

class TestCandidatePair:
    """Tests pour CandidatePair."""

    def test_candidate_is_not_relation(self):
        """INV-SCOPE-01: CandidatePair n'est PAS une relation."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[
                EvidenceSpan(doc_item_id="di1", role=EvidenceSpanRole.SCOPE_SETTER, text_excerpt="H"),
                EvidenceSpan(doc_item_id="di2", role=EvidenceSpanRole.MENTION, text_excerpt="M", concept_id="c1"),
            ],
            section_id="sec1",
            document_id="doc1",
        )

        candidate = CandidatePair(
            candidate_id="cand_001",
            pivot_concept_id="c1",
            other_concept_id="c2",
            evidence_bundle=bundle,
            section_id="sec1",
            document_id="doc1",
        )

        # Status par défaut = PENDING (pas de relation créée)
        assert candidate.status == CandidatePairStatus.PENDING
        # Pas de relation_type assigné
        assert candidate.verified_relation_type is None

    def test_abstained_candidate_has_reason(self):
        """INV-SCOPE-04: ABSTAIN doit avoir une raison."""
        bundle = EvidenceBundle(
            basis=DiscursiveBasis.SCOPE,
            spans=[EvidenceSpan(doc_item_id="di1", role=EvidenceSpanRole.SCOPE_SETTER, text_excerpt="H")],
            section_id="sec1",
            document_id="doc1",
        )

        candidate = CandidatePair(
            candidate_id="cand_002",
            pivot_concept_id="c1",
            other_concept_id="c2",
            evidence_bundle=bundle,
            section_id="sec1",
            document_id="doc1",
            status=CandidatePairStatus.ABSTAINED,
            abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE,
            abstain_justification="Bundle has only 1 DocItem",
        )

        assert candidate.status == CandidatePairStatus.ABSTAINED
        assert candidate.abstain_reason == DiscursiveAbstainReason.WEAK_BUNDLE
        assert candidate.abstain_justification is not None


# =============================================================================
# Tests ScopeMiningConfig (INV-SCOPE-05)
# =============================================================================

class TestScopeMiningConfig:
    """Tests pour la configuration des budgets."""

    def test_default_values(self):
        """Valeurs par défaut conformes à l'ADR."""
        config = ScopeMiningConfig()
        assert config.top_k_pivots == 5
        assert config.max_concepts_per_scope == 30
        assert config.max_pairs_per_scope == 50
        assert config.require_min_spans == 2

    def test_whitelist_default(self):
        """Whitelist SCOPE V1: APPLIES_TO et REQUIRES uniquement."""
        config = ScopeMiningConfig()
        assert RelationType.APPLIES_TO in config.allowed_relation_types
        assert RelationType.REQUIRES in config.allowed_relation_types
        assert len(config.allowed_relation_types) == 2

    def test_custom_budgets(self):
        """On peut modifier les budgets (avec justification documentée)."""
        config = ScopeMiningConfig(
            top_k_pivots=3,
            max_pairs_per_scope=20,
        )
        assert config.top_k_pivots == 3
        assert config.max_pairs_per_scope == 20


# =============================================================================
# Tests DiscursiveAbstainReason (complétude)
# =============================================================================

class TestDiscursiveAbstainReason:
    """Tests pour les raisons d'ABSTAIN SCOPE."""

    def test_miner_level_reasons_exist(self):
        """Raisons niveau Miner (déterministe)."""
        assert DiscursiveAbstainReason.WEAK_BUNDLE is not None
        assert DiscursiveAbstainReason.SCOPE_BREAK is not None
        assert DiscursiveAbstainReason.NO_SCOPE_SETTER is not None

    def test_verifier_level_reasons_exist(self):
        """Raisons niveau Verifier (LLM)."""
        assert DiscursiveAbstainReason.TYPE2_RISK is not None
        assert DiscursiveAbstainReason.AMBIGUOUS_PREDICATE is not None
        assert DiscursiveAbstainReason.SCOPE_BREAK_LINGUISTIC is not None


# =============================================================================
# Tests ScopeCandidateMiner (mock Neo4j)
# =============================================================================

class TestScopeCandidateMinerMocked:
    """Tests du miner avec Neo4j mocké."""

    def _create_mock_driver(self, section_data: dict = None):
        """Crée un mock du driver Neo4j."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_result = MagicMock()

        if section_data:
            mock_record = MagicMock()
            mock_record.__getitem__ = lambda self, key: section_data.get(key)
            mock_result.single.return_value = mock_record
        else:
            mock_result.single.return_value = None

        mock_session.run.return_value = mock_result
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        return mock_driver

    def test_mine_empty_section(self):
        """Section inexistante → résultat vide."""
        mock_driver = self._create_mock_driver(None)

        miner = ScopeCandidateMiner(mock_driver)
        result = miner.mine_section("sec_unknown")

        assert result.section_id == "sec_unknown"
        assert len(result.candidates) == 0

    def test_mine_section_with_insufficient_concepts(self):
        """Section avec <2 concepts → pas de candidates."""
        mock_driver = self._create_mock_driver({
            "section_id": "sec1",
            "document_id": "doc1",
            "doc_items": [
                {"doc_item_id": "di1", "text": "Introduction to SAP", "item_type": "heading", "page_no": 1, "position": 0},
            ],
            "concept_mentions": [
                {"concept_id": "c1", "canonical_name": "SAP", "doc_item_id": "di1"},
            ],
        })

        miner = ScopeCandidateMiner(mock_driver)
        result = miner.mine_section("sec1")

        assert len(result.candidates) == 0
        assert result.stats["concepts"] == 1


# =============================================================================
# Tests get_mining_stats
# =============================================================================

class TestGetMiningStats:
    """Tests pour l'agrégation des stats."""

    def test_aggregate_empty_results(self):
        """Agrégation de résultats vides."""
        stats = get_mining_stats([])
        assert stats["sections"] == 0
        assert stats["pairs_valid"] == 0

    def test_aggregate_multiple_results(self):
        """Agrégation de plusieurs résultats."""
        from knowbase.relations.scope_candidate_miner import MiningResult

        r1 = MiningResult(
            section_id="sec1",
            candidates=[],
            abstained=[],
            stats={"doc_items": 10, "concepts": 5, "pairs_valid": 3, "abstained_weak_bundle": 1}
        )
        r2 = MiningResult(
            section_id="sec2",
            candidates=[],
            abstained=[],
            stats={"doc_items": 8, "concepts": 4, "pairs_valid": 2, "abstained_weak_bundle": 0}
        )

        stats = get_mining_stats([r1, r2])

        assert stats["sections"] == 2
        assert stats["doc_items"] == 18
        assert stats["concepts"] == 9
        assert stats["pairs_valid"] == 5
        assert stats["abstained_weak_bundle"] == 1
