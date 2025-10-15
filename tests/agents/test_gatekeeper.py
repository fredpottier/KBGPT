"""
Tests pour GatekeeperDelegate.
"""

import pytest
from src.knowbase.agents.gatekeeper.gatekeeper import (
    GatekeeperDelegate,
    GateProfile,
    GATE_PROFILES,
    GateCheckInput,
    GateCheckOutput,
    PromoteConceptsInput
)
from src.knowbase.agents.base import AgentState


class TestGateProfile:
    """Tests pour GateProfile."""

    def test_gate_profile_initialization(self):
        """Test initialisation GateProfile."""
        profile = GateProfile(
            name="TEST",
            min_confidence=0.75,
            required_fields=["name", "type"],
            max_length=80,
            min_length=5
        )

        assert profile.name == "TEST"
        assert profile.min_confidence == 0.75
        assert profile.required_fields == ["name", "type"]
        assert profile.max_length == 80
        assert profile.min_length == 5

    def test_gate_profile_defaults(self):
        """Test valeurs par défaut GateProfile."""
        profile = GateProfile(name="TEST")

        assert profile.min_confidence == 0.7
        assert profile.required_fields == ["name", "type"]
        assert profile.max_length == 100
        assert profile.min_length == 3

    def test_predefined_gate_profiles(self):
        """Test profils prédéfinis."""
        assert "STRICT" in GATE_PROFILES
        assert "BALANCED" in GATE_PROFILES
        assert "PERMISSIVE" in GATE_PROFILES

        strict = GATE_PROFILES["STRICT"]
        assert strict.min_confidence == 0.85
        assert "definition" in strict.required_fields

        balanced = GATE_PROFILES["BALANCED"]
        assert balanced.min_confidence == 0.70
        assert "name" in balanced.required_fields

        permissive = GATE_PROFILES["PERMISSIVE"]
        assert permissive.min_confidence == 0.60


class TestGatekeeperDelegate:
    """Tests pour GatekeeperDelegate."""

    @pytest.fixture
    def gatekeeper(self):
        """Fixture GatekeeperDelegate."""
        return GatekeeperDelegate(config={})

    @pytest.fixture
    def valid_candidates(self):
        """Fixture candidates valides."""
        return [
            {
                "name": "SAP S/4HANA",
                "type": "PRODUCT",
                "definition": "Enterprise resource planning system",
                "language": "en",
                "confidence": 0.85
            },
            {
                "name": "SAP Fiori",
                "type": "TOOL",
                "definition": "User experience design system",
                "language": "en",
                "confidence": 0.78
            },
            {
                "name": "ERP",
                "type": "ENTITY",
                "definition": "",
                "language": "en",
                "confidence": 0.65
            }
        ]

    @pytest.fixture
    def invalid_candidates(self):
        """Fixture candidates invalides."""
        return [
            {"name": "ab", "type": "ENTITY", "confidence": 0.9},  # Trop court
            {"name": "the", "type": "ENTITY", "confidence": 0.9},  # Stopword
            {"name": "ized", "type": "ENTITY", "confidence": 0.9},  # Fragment
            {"name": "test@example.com", "type": "ENTITY", "confidence": 0.9},  # PII
            {"name": "ValidName", "type": "ENTITY", "confidence": 0.50}  # Confidence trop basse
        ]

    def test_gatekeeper_initialization(self, gatekeeper):
        """Test initialisation GatekeeperDelegate."""
        assert gatekeeper.role.value == "gatekeeper_delegate"
        assert gatekeeper.default_profile == "BALANCED"
        assert "the" in gatekeeper.stopwords
        assert "ized" in gatekeeper.fragments
        assert "gate_check" in gatekeeper.tools
        assert "promote_concepts" in gatekeeper.tools

    def test_gatekeeper_initialization_custom_profile(self):
        """Test initialisation avec profil custom."""
        gatekeeper = GatekeeperDelegate(config={"default_profile": "STRICT"})

        assert gatekeeper.default_profile == "STRICT"

    def test_check_hard_rejection_too_short(self, gatekeeper):
        """Test rejet hard: nom trop court."""
        reason = gatekeeper._check_hard_rejection("ab")

        assert reason is not None
        assert "short" in reason.lower()

    def test_check_hard_rejection_too_long(self, gatekeeper):
        """Test rejet hard: nom trop long."""
        long_name = "a" * 101
        reason = gatekeeper._check_hard_rejection(long_name)

        assert reason is not None
        assert "long" in reason.lower()

    def test_check_hard_rejection_stopword(self, gatekeeper):
        """Test rejet hard: stopword."""
        reason = gatekeeper._check_hard_rejection("the")

        assert reason is not None
        assert "stopword" in reason.lower()

    def test_check_hard_rejection_fragment(self, gatekeeper):
        """Test rejet hard: fragment."""
        reason = gatekeeper._check_hard_rejection("ized")

        assert reason is not None
        assert "fragment" in reason.lower()

    def test_check_hard_rejection_pii_email(self, gatekeeper):
        """Test rejet hard: PII email."""
        reason = gatekeeper._check_hard_rejection("user@example.com")

        assert reason is not None
        assert "pii" in reason.lower()

    def test_check_hard_rejection_pii_phone(self, gatekeeper):
        """Test rejet hard: PII phone."""
        reason = gatekeeper._check_hard_rejection("+33 6 12 34 56 78")

        assert reason is not None
        assert "pii" in reason.lower()

    def test_check_hard_rejection_valid(self, gatekeeper):
        """Test validation: nom valide."""
        reason = gatekeeper._check_hard_rejection("SAP S/4HANA")

        assert reason is None

    def test_gate_check_tool_balanced_profile(self, gatekeeper, valid_candidates):
        """Test gate_check avec profil BALANCED."""
        tool_input = GateCheckInput(
            candidates=valid_candidates,
            profile_name="BALANCED"
        )

        result = gatekeeper._gate_check_tool(tool_input)

        assert result.success is True
        output = GateCheckOutput(**result.data)

        # SAP S/4HANA et SAP Fiori devraient passer (≥0.70)
        assert len(output.promoted) == 2
        # ERP devrait être rejeté (0.65 < 0.70)
        assert len(output.rejected) == 1
        assert not output.retry_recommended  # 66% promoted (2/3)

    def test_gate_check_tool_strict_profile(self, gatekeeper, valid_candidates):
        """Test gate_check avec profil STRICT."""
        tool_input = GateCheckInput(
            candidates=valid_candidates,
            profile_name="STRICT"
        )

        result = gatekeeper._gate_check_tool(tool_input)

        assert result.success is True
        output = GateCheckOutput(**result.data)

        # Seul SAP S/4HANA devrait passer (≥0.85 + definition non vide)
        assert len(output.promoted) == 1
        assert output.promoted[0]["name"] == "SAP S/4HANA"

    def test_gate_check_tool_permissive_profile(self, gatekeeper, valid_candidates):
        """Test gate_check avec profil PERMISSIVE."""
        tool_input = GateCheckInput(
            candidates=valid_candidates,
            profile_name="PERMISSIVE"
        )

        result = gatekeeper._gate_check_tool(tool_input)

        assert result.success is True
        output = GateCheckOutput(**result.data)

        # Tous devraient passer (≥0.60)
        assert len(output.promoted) == 3

    def test_gate_check_tool_invalid_candidates(self, gatekeeper, invalid_candidates):
        """Test gate_check avec candidates invalides."""
        tool_input = GateCheckInput(
            candidates=invalid_candidates,
            profile_name="BALANCED"
        )

        result = gatekeeper._gate_check_tool(tool_input)

        assert result.success is True
        output = GateCheckOutput(**result.data)

        # Tous devraient être rejetés (hard rejections)
        assert len(output.promoted) == 0
        assert len(output.rejected) == 5
        assert output.retry_recommended  # 0% promoted

    def test_gate_check_tool_retry_recommendation(self, gatekeeper):
        """Test recommandation retry (< 30% promoted)."""
        candidates = [
            {"name": "Valid1", "type": "ENTITY", "confidence": 0.50},  # Rejeté
            {"name": "Valid2", "type": "ENTITY", "confidence": 0.55},  # Rejeté
            {"name": "Valid3", "type": "ENTITY", "confidence": 0.75},  # Promu
            {"name": "Valid4", "type": "ENTITY", "confidence": 0.60},  # Rejeté
        ]

        tool_input = GateCheckInput(
            candidates=candidates,
            profile_name="BALANCED"
        )

        result = gatekeeper._gate_check_tool(tool_input)
        output = GateCheckOutput(**result.data)

        # 1 promu / 4 total = 25% < 30%
        assert output.retry_recommended is True

    def test_gate_check_tool_unknown_profile(self, gatekeeper, valid_candidates):
        """Test gate_check avec profil inconnu (fallback BALANCED)."""
        tool_input = GateCheckInput(
            candidates=valid_candidates,
            profile_name="UNKNOWN_PROFILE"
        )

        result = gatekeeper._gate_check_tool(tool_input)

        assert result.success is True
        # Devrait utiliser BALANCED par défaut

    def test_promote_concepts_tool(self, gatekeeper):
        """Test promote_concepts tool."""
        concepts = [
            {"name": "SAP S/4HANA", "type": "PRODUCT"},
            {"name": "SAP Fiori", "type": "TOOL"}
        ]

        tool_input = PromoteConceptsInput(concepts=concepts)

        result = gatekeeper._promote_concepts_tool(tool_input)

        assert result.success is True
        assert result.data["promoted_count"] == 2

    @pytest.mark.asyncio
    async def test_execute_no_candidates(self, gatekeeper):
        """Test execute avec aucun candidate."""
        state = AgentState(document_id="test-doc", candidates=[])

        final_state = await gatekeeper.execute(state)

        assert len(final_state.promoted) == 0

    @pytest.mark.asyncio
    async def test_execute_with_candidates(self, gatekeeper, valid_candidates):
        """Test execute avec candidates valides."""
        state = AgentState(
            document_id="test-doc",
            candidates=valid_candidates
        )

        final_state = await gatekeeper.execute(state)

        # Devrait avoir promoted quelques concepts (profil BALANCED)
        assert len(final_state.promoted) > 0
        assert len(final_state.promoted) <= len(valid_candidates)

    @pytest.mark.asyncio
    async def test_execute_with_instruction(self, gatekeeper, valid_candidates):
        """Test execute avec instruction (profil custom)."""
        state = AgentState(
            document_id="test-doc",
            candidates=valid_candidates
        )

        final_state = await gatekeeper.execute(state, instruction="STRICT")

        # Avec STRICT, moins de concepts promoted
        # (SAP S/4HANA uniquement car seul avec confidence ≥ 0.85 + definition)
        assert len(final_state.promoted) <= len(valid_candidates)

    @pytest.mark.asyncio
    async def test_execute_calls_promote(self, gatekeeper, valid_candidates):
        """Test execute appelle promote_concepts."""
        state = AgentState(
            document_id="test-doc",
            candidates=valid_candidates
        )

        # Mock promote_concepts_tool
        original_tool = gatekeeper._promote_concepts_tool
        call_count = [0]

        def mock_promote(tool_input):
            call_count[0] += 1
            return original_tool(tool_input)

        gatekeeper._promote_concepts_tool = mock_promote

        await gatekeeper.execute(state)

        # Devrait avoir appelé promote une fois (si promoted non vide)
        if state.promoted:
            assert call_count[0] == 1
