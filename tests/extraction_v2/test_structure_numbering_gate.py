"""
Tests pour StructureNumberingGate (Plan v2.1).

Teste les 3 signaux de détection de numérotation structurelle:
- S1: Séquentialité (même préfixe avec numéros consécutifs)
- S2: Position structurelle (début de ligne + ponctuation)
- S3: Préfixe quasi-toujours numéroté

Cas de test basés sur les faux positifs identifiés:
- SAP-014: "Content 2", "PUBLIC 3"
- SAP-016: "Public 2", "Public 3"
- SAP-020: "PUBLIC 2", "PUBLIC 3"
- SAP-021: "PUBLIC 1", "EXTERNAL 2", "Resources 42", "PUBLIC 3"

Spec: doc/ongoing/PLAN_STRUCTURE_NUMBERING_GATE_V2.1.md
"""

import pytest
from knowbase.extraction_v2.context.candidate_mining import (
    StructureNumberingGate,
    StructureGateConfig,
    MarkerCandidate,
    SequenceDetectionResult,
)


class TestSignalS1Sequentiality:
    """Tests pour Signal S1 - Détection de séquentialité."""

    def setup_method(self):
        self.gate = StructureNumberingGate()

    def test_detect_sequence_public_1_2_3(self):
        """Séquence consécutive PUBLIC 1, 2, 3 -> longueur 3."""
        candidates = [
            MarkerCandidate(value="PUBLIC 1", source="body", lexical_shape="entity_numeral"),
            MarkerCandidate(value="PUBLIC 2", source="body", lexical_shape="entity_numeral"),
            MarkerCandidate(value="PUBLIC 3", source="body", lexical_shape="entity_numeral"),
        ]
        results = self.gate.detect_sequences(candidates)

        assert "PUBLIC" in results
        assert results["PUBLIC"].max_consecutive == 3
        assert results["PUBLIC"].numbers_found == [1, 2, 3]

    def test_detect_sequence_non_consecutive(self):
        """Séquence non consécutive PUBLIC 1, 3 -> longueur 1."""
        candidates = [
            MarkerCandidate(value="PUBLIC 1", source="body", lexical_shape="entity_numeral"),
            MarkerCandidate(value="PUBLIC 3", source="body", lexical_shape="entity_numeral"),
        ]
        results = self.gate.detect_sequences(candidates)

        assert "PUBLIC" in results
        assert results["PUBLIC"].max_consecutive == 1  # Pas consécutif

    def test_detect_sequence_iphone_different_prefix(self):
        """iPhone 14, 15, 16 sont valides (vraies versions)."""
        candidates = [
            MarkerCandidate(value="iPhone 14", source="body", lexical_shape="entity_numeral"),
            MarkerCandidate(value="iPhone 15", source="body", lexical_shape="entity_numeral"),
            MarkerCandidate(value="iPhone 16", source="body", lexical_shape="entity_numeral"),
        ]
        results = self.gate.detect_sequences(candidates)

        # iPhone forme une séquence mais c'est un produit réel
        assert "iPhone" in results
        assert results["iPhone"].max_consecutive == 3

    def test_detect_sequence_mixed_prefixes(self):
        """Préfixes différents ne forment pas de séquence commune."""
        candidates = [
            MarkerCandidate(value="PUBLIC 1", source="body", lexical_shape="entity_numeral"),
            MarkerCandidate(value="EXTERNAL 2", source="body", lexical_shape="entity_numeral"),
            MarkerCandidate(value="PUBLIC 3", source="body", lexical_shape="entity_numeral"),
        ]
        results = self.gate.detect_sequences(candidates)

        # PUBLIC n'a pas de séquence consécutive (1, 3)
        assert results["PUBLIC"].max_consecutive == 1
        # EXTERNAL n'a qu'un seul numéro
        assert results["EXTERNAL"].max_consecutive == 1


class TestSignalS2PositionIndicator:
    """Tests pour Signal S2 - Position structurelle."""

    def setup_method(self):
        self.gate = StructureNumberingGate()

    def test_position_start_of_line_colon(self):
        """PUBLIC 3: en début de ligne."""
        full_text = """Document content
PUBLIC 3: This is section 3
More content here"""

        result = self.gate.check_position_indicator("PUBLIC 3", full_text)
        assert result is True

    def test_position_start_of_line_period(self):
        """Content 2. en début de ligne."""
        full_text = """Introduction
Content 2. This describes the content
End"""

        result = self.gate.check_position_indicator("Content 2", full_text)
        assert result is True

    def test_position_alone_on_line(self):
        """PUBLIC 3 seul sur une ligne."""
        full_text = """Header
PUBLIC 3
Body text here"""

        result = self.gate.check_position_indicator("PUBLIC 3", full_text)
        assert result is True

    def test_position_in_middle_of_sentence(self):
        """iPhone 15 au milieu d'une phrase -> pas structurel."""
        full_text = """The new iPhone 15 features incredible performance and design."""

        result = self.gate.check_position_indicator("iPhone 15", full_text)
        assert result is False

    def test_position_tls_13_in_context(self):
        """TLS 1.3 dans une phrase technique -> pas structurel."""
        full_text = """We recommend using TLS 1.3 for secure connections.
The TLS 1.3 protocol provides enhanced security."""

        result = self.gate.check_position_indicator("TLS 1", full_text)
        assert result is False


class TestSignalS3PrefixMostlyNumbered:
    """Tests pour Signal S3 - Préfixe quasi-toujours numéroté."""

    def setup_method(self):
        self.gate = StructureNumberingGate()

    def test_prefix_mostly_numbered_public(self):
        """PUBLIC apparaît 3x avec numéros, 0x standalone -> S3 = True."""
        full_text = """PUBLIC 1: First section
PUBLIC 2: Second section
PUBLIC 3: Third section
All sections are PUBLIC numbered."""

        result = self.gate.check_prefix_mostly_numbered("PUBLIC", full_text)
        # count_numbered=3, count_standalone=0, distinct_numbers=3 -> True
        assert result is True

    def test_prefix_mixed_usage_tls(self):
        """TLS apparaît standalone ET avec numéros -> S3 = False."""
        full_text = """TLS 1.3 is the latest version.
TLS handshake process is complex.
TLS protocol security is essential.
TLS 1.2 is still widely used."""

        result = self.gate.check_prefix_mostly_numbered("TLS", full_text)
        # TLS apparaît standalone plusieurs fois -> False
        assert result is False

    def test_prefix_single_numbered(self):
        """Un seul numéro ne suffit pas pour S3."""
        full_text = """iPhone 15 is the latest model.
iPhone users love the design.
iPhone market share is growing."""

        result = self.gate.check_prefix_mostly_numbered("iPhone", full_text)
        # count_numbered=1, count_standalone=2 -> False
        assert result is False


class TestDecisionMatrix:
    """Tests pour la matrice de décision complète."""

    def setup_method(self):
        self.gate = StructureNumberingGate()

    def test_hard_reject_seq3_with_position(self):
        """Seq>=3 ET S2=True -> HARD_REJECT."""
        candidates = [
            MarkerCandidate(value="PUBLIC 1", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="PUBLIC 2", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="PUBLIC 3", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
        ]
        full_text = """PUBLIC 1:
First section content
PUBLIC 2:
Second section content
PUBLIC 3:
Third section content"""

        # Note: order is (survivors, soft_flagged, hard_rejected)
        survivors, soft, rejected = self.gate.filter_candidates(candidates, full_text, "test_doc")

        # Tous doivent être rejetés (HARD_REJECT)
        assert len(rejected) == 3
        assert len(survivors) == 0
        assert all(c.structure_risk == "HARD_REJECT" for c in rejected)

    def test_soft_flag_seq2(self):
        """Seq=2 -> SOFT_FLAG."""
        candidates = [
            MarkerCandidate(value="PUBLIC 1", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="PUBLIC 2", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
        ]
        full_text = """PUBLIC 1: First
PUBLIC 2: Second
Other content"""

        # Note: order is (survivors, soft_flagged, hard_rejected)
        survivors, soft, rejected = self.gate.filter_candidates(candidates, full_text, "test_doc")

        # Doivent être SOFT_FLAG (pas HARD_REJECT car seq=2 < 3)
        assert len(soft) == 2
        assert len(rejected) == 0
        assert all(c.structure_risk == "SOFT_FLAG" for c in soft)

    def test_low_risk_tls_13(self):
        """TLS 1.3 sans séquence ni position structurelle -> LOW (conservé)."""
        candidates = [
            MarkerCandidate(value="TLS 1", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
        ]
        full_text = """We recommend using TLS 1.3 for secure connections.
The TLS protocol provides security. TLS handshake is fast."""

        # Note: order is (survivors, soft_flagged, hard_rejected)
        survivors, soft, rejected = self.gate.filter_candidates(candidates, full_text, "test_doc")

        # TLS 1 doit être conservé (LOW risk)
        assert len(survivors) == 1
        assert survivors[0].structure_risk == "LOW"


class TestIntegrationSAPDocuments:
    """Tests d'intégration sur les documents SAP problématiques."""

    def setup_method(self):
        self.gate = StructureNumberingGate()

    def test_sap_021_markers(self):
        """SAP-021: PUBLIC 1, EXTERNAL 2, Resources 42, PUBLIC 3."""
        candidates = [
            MarkerCandidate(value="PUBLIC 1", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="EXTERNAL 2", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="Resources 42", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="PUBLIC 2", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="PUBLIC 3", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="2.6", source="body", lexical_shape="semver", is_weak_candidate=False),  # Version réelle
            MarkerCandidate(value="4.4", source="body", lexical_shape="semver", is_weak_candidate=False),  # Version réelle
        ]

        # Simuler le document avec numérotation structurelle
        full_text = """SAP Business AI Guide
PUBLIC 1:
Introduction to AI capabilities...

PUBLIC 2:
Advanced features...

PUBLIC 3:
Integration options...

EXTERNAL 2:
External resources...

Resources 42:
Additional materials...

Version 2.6 released
Compatible with 4.4
"""

        # Note: order is (survivors, soft_flagged, hard_rejected)
        survivors, soft, rejected = self.gate.filter_candidates(candidates, full_text, "SAP-021")

        # Les versions 2.6 et 4.4 doivent survivre (pas weak)
        survivor_values = {c.value for c in survivors}
        assert "2.6" in survivor_values or "4.4" in survivor_values

        # Les numérotations structurelles doivent être filtrées ou flaggées
        rejected_values = {c.value for c in rejected + soft}
        # PUBLIC 1/2/3 avec seq=3 + position -> HARD_REJECT ou SOFT_FLAG
        assert len(rejected) + len(soft) >= 2  # Au moins quelques faux positifs détectés


class TestFallbackSilentDocuments:
    """Tests pour le fallback des documents silencieux."""

    def setup_method(self):
        config = StructureGateConfig(fallback_max_markers=2)
        self.gate = StructureNumberingGate(config)

    def test_fallback_all_rejected(self):
        """Si tous rejetés, garder K meilleurs en fallback."""
        candidates = [
            MarkerCandidate(value="PUBLIC 1", source="body", lexical_shape="entity_numeral", is_weak_candidate=True, occurrences=5),
            MarkerCandidate(value="PUBLIC 2", source="body", lexical_shape="entity_numeral", is_weak_candidate=True, occurrences=3),
            MarkerCandidate(value="PUBLIC 3", source="body", lexical_shape="entity_numeral", is_weak_candidate=True, occurrences=1),
        ]

        full_text = """PUBLIC 1:
PUBLIC 2:
PUBLIC 3:
All structural numbering."""

        # Note: order is (survivors, soft_flagged, hard_rejected)
        survivors, soft, rejected = self.gate.filter_candidates(candidates, full_text, "silent_doc")

        # Si tous rejetés (HARD_REJECT)
        if len(survivors) == 0:
            fallback = self.gate.apply_fallback_if_silent(
                final_markers=survivors,
                rejected=rejected,  # Use hard_rejected for fallback
                doc_id="silent_doc"
            )

            # Doit garder max 2 markers
            assert len(fallback) <= 2
            # Marqués comme fallback
            assert all(m.structure_fallback for m in fallback)


class TestCasesLimites:
    """Tests pour les cas limites (versions réelles vs numérotation)."""

    def setup_method(self):
        self.gate = StructureNumberingGate()

    def test_iso_27001_preserved(self):
        """ISO 27001 est un standard, pas une numérotation de section."""
        candidates = [
            MarkerCandidate(value="ISO 27001", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
        ]
        full_text = """Our company is ISO 27001 certified.
The ISO 27001 standard requires regular audits.
ISO compliance is mandatory."""

        # Note: order is (survivors, soft_flagged, hard_rejected)
        survivors, soft, rejected = self.gate.filter_candidates(candidates, full_text, "iso_doc")

        # ISO 27001 ne devrait pas être HARD_REJECT (pas de séquence)
        survivor_values = {c.value for c in survivors + soft}
        assert "ISO 27001" in survivor_values

    def test_stage_2_context_dependent(self):
        """Stage 2 peut être structurel ou version selon contexte."""
        # Contexte structurel avec séquence 1/2/3
        structural_text = """Project Phases:
Stage 1:
Initial planning
Stage 2:
Development phase
Stage 3:
Testing"""

        # Note: order is (survivors, soft_flagged, hard_rejected)
        survivors, soft, rejected = self.gate.filter_candidates(
            [MarkerCandidate(value="Stage 1", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
             MarkerCandidate(value="Stage 2", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
             MarkerCandidate(value="Stage 3", source="body", lexical_shape="entity_numeral", is_weak_candidate=True)],
            structural_text,
            "structural_doc"
        )

        # Avec séquence 1/2/3 + position structurelle, devrait être HARD_REJECT ou SOFT_FLAG
        assert len(rejected) + len(soft) >= 2


class TestConfigOptions:
    """Tests pour les options de configuration."""

    def test_disabled_gate(self):
        """Gate désactivé ne filtre rien."""
        config = StructureGateConfig(enabled=False)
        gate = StructureNumberingGate(config)

        candidates = [
            MarkerCandidate(value="PUBLIC 1", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="PUBLIC 2", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="PUBLIC 3", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
        ]
        full_text = "PUBLIC 1:\nPUBLIC 2:\nPUBLIC 3:"

        # Note: order is (survivors, soft_flagged, hard_rejected)
        survivors, soft, rejected = gate.filter_candidates(candidates, full_text, "test")

        # Tous conservés car gate désactivé
        assert len(survivors) == 3
        assert len(rejected) == 0

    def test_higher_sequence_threshold(self):
        """Seuil de séquence à 4 ne rejette pas seq=3."""
        config = StructureGateConfig(sequence_threshold=4)
        gate = StructureNumberingGate(config)

        candidates = [
            MarkerCandidate(value="PUBLIC 1", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="PUBLIC 2", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
            MarkerCandidate(value="PUBLIC 3", source="body", lexical_shape="entity_numeral", is_weak_candidate=True),
        ]
        full_text = "PUBLIC 1:\nPUBLIC 2:\nPUBLIC 3:"

        # Note: order is (survivors, soft_flagged, hard_rejected)
        survivors, soft, rejected = gate.filter_candidates(candidates, full_text, "test")

        # Seq=3 < threshold=4, donc pas de HARD_REJECT
        assert len(rejected) == 0
