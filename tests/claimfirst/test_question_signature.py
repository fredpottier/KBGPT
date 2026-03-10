# tests/claimfirst/test_question_signature.py
"""
Tests QuestionSignature — Modèle + Extracteur Level A.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Any, Dict, Optional

from knowbase.claimfirst.models.question_signature import (
    QuestionSignature,
    QSExtractionLevel,
    QSValueType,
)
from knowbase.claimfirst.extractors.question_signature_extractor import (
    LEVEL_A_PATTERNS,
    extract_question_signatures_level_a,
    MAX_QS_PER_DOC,
)


# =============================================================================
# Helpers
# =============================================================================


@dataclass
class FakeClaim:
    """Stub léger pour les tests."""

    claim_id: str
    text: str
    doc_id: str = "doc_test"
    structured_form: Optional[Dict[str, Any]] = None


# =============================================================================
# Tests Modèle
# =============================================================================


class TestQuestionSignatureModel:

    def test_create_basic(self):
        """Création d'une QS avec tous les champs requis."""
        qs = QuestionSignature(
            qs_id="qs_c1_min_version",
            claim_id="c1",
            doc_id="doc1",
            question="What is the minimum TLS version?",
            dimension_key="min_tls_version",
            value_type=QSValueType.VERSION,
            extracted_value="1.2",
            extraction_level=QSExtractionLevel.LEVEL_A,
            pattern_name="minimum_version",
        )
        assert qs.dimension_key == "min_tls_version"
        assert qs.value_type == QSValueType.VERSION
        assert qs.confidence == 1.0

    def test_neo4j_roundtrip(self):
        """to_neo4j_properties → from_neo4j_record fonctionne."""
        qs = QuestionSignature(
            qs_id="qs_c1_test",
            claim_id="c1",
            doc_id="doc1",
            question="What is X?",
            dimension_key="test_key",
            value_type=QSValueType.NUMBER,
            extracted_value="42",
            extraction_level=QSExtractionLevel.LEVEL_A,
            pattern_name="test_pattern",
            scope_subject="SAP HANA",
        )
        props = qs.to_neo4j_properties()
        qs2 = QuestionSignature.from_neo4j_record(props)
        assert qs2.qs_id == qs.qs_id
        assert qs2.dimension_key == qs.dimension_key
        assert qs2.value_type == QSValueType.NUMBER
        assert qs2.scope_subject == "SAP HANA"

    def test_value_types(self):
        """Tous les QSValueType sont valides."""
        for vt in QSValueType:
            assert isinstance(vt.value, str)
        assert QSValueType.VERSION.value == "version"
        assert QSValueType.PERCENT.value == "percent"


# =============================================================================
# Tests Patterns Level A
# =============================================================================


class TestLevelAPatterns:
    """Tester chaque pattern regex individuellement."""

    def test_minimum_version(self):
        """'minimum version is 1.2' → min_version."""
        claim = FakeClaim(
            "c1",
            "The minimum version is 1.2 for all connections.",
            structured_form={"subject": "TLS", "predicate": "requires", "object": "1.2"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert len(results) >= 1
        qs = results[0]
        assert qs.dimension_key == "min_version"
        assert qs.extracted_value == "1.2"
        assert qs.value_type == QSValueType.VERSION

    def test_minimum_version_required(self):
        """'1.2 is the minimum required version' → min_version."""
        claim = FakeClaim(
            "c1",
            "TLS 1.2 is the minimum required version for all SAP connections.",
            structured_form={"subject": "TLS", "predicate": "requires", "object": "1.2"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "min_version" for qs in results)

    def test_requires_version(self):
        """'requires version 7.50' → required_version."""
        claim = FakeClaim(
            "c2",
            "SAP NetWeaver requires at least version 7.50 of the ABAP kernel.",
            structured_form={"subject": "SAP NetWeaver", "predicate": "requires", "object": "7.50"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "required_version" for qs in results)
        qs = [q for q in results if q.dimension_key == "required_version"][0]
        assert "7.50" in qs.extracted_value

    def test_minimum_ram(self):
        """'minimum RAM is 128 GB' → min_ram."""
        claim = FakeClaim(
            "c3",
            "The minimum required RAM is 128 GB for production systems.",
            structured_form={"subject": "S/4HANA", "predicate": "requires", "object": "128 GB"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "min_ram" for qs in results)
        qs = [q for q in results if q.dimension_key == "min_ram"][0]
        assert qs.extracted_value == "128"
        assert qs.value_type == QSValueType.NUMBER

    def test_minimum_ram_reverse(self):
        """'128 GB of memory is required' → min_ram."""
        claim = FakeClaim(
            "c3b",
            "At least 128 GB of RAM is required for production.",
            structured_form={"subject": "S/4HANA", "predicate": "requires", "object": "128 GB"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "min_ram" for qs in results)

    def test_requires_protocol(self):
        """'requires TLS 1.2' → required_protocol."""
        claim = FakeClaim(
            "c4",
            "All connections require TLS 1.2 or higher for encryption.",
            structured_form={"subject": "SAP BTP", "predicate": "requires", "object": "TLS 1.2"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "required_protocol" for qs in results)

    def test_default_port(self):
        """'default port is 443' → default_port."""
        claim = FakeClaim(
            "c5",
            "The default port is 443 for HTTPS connections.",
            structured_form={"subject": "HTTPS", "predicate": "uses", "object": "443"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "default_port" for qs in results)
        qs = [q for q in results if q.dimension_key == "default_port"][0]
        assert qs.extracted_value == "443"

    def test_deprecated_since(self):
        """'deprecated since 2023' → deprecated_since."""
        claim = FakeClaim(
            "c6",
            "SAPscript is deprecated since SAP S/4HANA 2020.",
            structured_form={"subject": "SAPscript", "predicate": "deprecated", "object": "2020"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "deprecated_since" for qs in results)

    def test_end_of_support(self):
        """'end of support: December 2027' → end_of_support."""
        claim = FakeClaim(
            "c7",
            "End of mainstream support: December 2027 for SAP ECC 6.0.",
            structured_form={"subject": "SAP ECC", "predicate": "end of support", "object": "2027"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "end_of_support" for qs in results)

    def test_timeout_value(self):
        """'timeout is 300 seconds' → timeout."""
        claim = FakeClaim(
            "c8",
            "The session timeout is set to 300 seconds by default.",
            structured_form={"subject": "session", "predicate": "timeout", "object": "300s"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "timeout" for qs in results)
        qs = [q for q in results if q.dimension_key == "timeout"][0]
        assert qs.extracted_value == "300"

    def test_retention_period(self):
        """'data retention period is 90 days' → retention_period."""
        claim = FakeClaim(
            "c9",
            "The data retention period is 90 days for audit logs.",
            structured_form={"subject": "audit logs", "predicate": "retention", "object": "90 days"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "retention_period" for qs in results)

    def test_maximum_connections(self):
        """'maximum concurrent connections is 500' → max_connections."""
        claim = FakeClaim(
            "c10",
            "The maximum concurrent connections is 500 for this service.",
            structured_form={"subject": "service", "predicate": "max connections", "object": "500"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert any(qs.dimension_key == "max_connections" for qs in results)


# =============================================================================
# Tests Extraction complète
# =============================================================================


class TestExtraction:

    def test_no_match(self):
        """Claim sans pattern → 0 résultats."""
        claim = FakeClaim(
            "c1",
            "SAP S/4HANA Cloud is available in multiple regions worldwide.",
            structured_form={"subject": "S/4HANA", "predicate": "available", "object": "multiple regions"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert len(results) == 0

    def test_short_claim_skipped(self):
        """Claims < 20 chars → skippées."""
        claim = FakeClaim("c1", "TLS 1.2 required")
        results = extract_question_signatures_level_a([claim], "doc1")
        assert len(results) == 0

    def test_deduplication_same_dim_value(self):
        """Deux claims avec même dimension_key + valeur → 1 seule QS."""
        c1 = FakeClaim("c1", "The minimum version is 1.2 for connections.",
                        structured_form={"subject": "TLS"})
        c2 = FakeClaim("c2", "Minimum required version is 1.2 per policy.",
                        structured_form={"subject": "TLS"})
        results = extract_question_signatures_level_a([c1, c2], "doc1")
        min_ver = [qs for qs in results if qs.dimension_key == "min_version"]
        assert len(min_ver) == 1

    def test_multiple_patterns_same_claim(self):
        """Une claim peut matcher plusieurs patterns différents."""
        claim = FakeClaim(
            "c1",
            "All connections require TLS 1.2, with a default port of 443.",
            structured_form={"subject": "SAP BTP"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        dim_keys = {qs.dimension_key for qs in results}
        assert "default_port" in dim_keys
        # TLS peut matcher required_protocol ou requires_version

    def test_cap_max_qs_per_doc(self):
        """Max MAX_QS_PER_DOC QS par document."""
        claims = []
        for i in range(100):
            claims.append(FakeClaim(
                f"c{i}",
                f"The default port is {1000 + i} for service {i}.",
                structured_form={"subject": f"service_{i}"},
            ))
        results = extract_question_signatures_level_a(claims, "doc1")
        assert len(results) <= MAX_QS_PER_DOC

    def test_qs_id_format(self):
        """qs_id = 'qs_{claim_id}_{pattern_name}'."""
        claim = FakeClaim(
            "claim_abc",
            "The default port is 8443 for secure access.",
            structured_form={"subject": "HTTPS"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert len(results) >= 1
        assert results[0].qs_id.startswith("qs_claim_abc_")

    def test_scope_subject_from_structured_form(self):
        """scope_subject doit venir du structured_form.subject."""
        claim = FakeClaim(
            "c1",
            "The minimum version is 7.52 for all deployments.",
            structured_form={"subject": "SAP NetWeaver", "predicate": "requires", "object": "7.52"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        assert len(results) >= 1
        assert results[0].scope_subject == "SAP NetWeaver"

    def test_extraction_level_is_level_a(self):
        """Toutes les QS Level A doivent avoir extraction_level = LEVEL_A."""
        claim = FakeClaim(
            "c1",
            "The default port is 3000 for the frontend.",
            structured_form={"subject": "frontend"},
        )
        results = extract_question_signatures_level_a([claim], "doc1")
        for qs in results:
            assert qs.extraction_level == QSExtractionLevel.LEVEL_A
            assert qs.confidence == 1.0
