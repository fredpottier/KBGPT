"""
Tests pour les upgrades qualité pré-réimport :
- Upgrade 1: Filtres qualité Phase 1.6 (language-agnostic)
- Upgrade 2: Entity ponctuation + max_entity_length=50
- Upgrade 3: Cap clusters 50 + trim centroïde
"""

import uuid
import pytest
import numpy as np

from knowbase.claimfirst.models.claim import Claim, ClaimType
from knowbase.claimfirst.models.entity import is_valid_entity_name
from knowbase.claimfirst.quality_filters import (
    filter_claims_quality,
    has_positive_signal,
    is_heading_like,
    BOILERPLATE_PATTERNS,
)
from knowbase.claimfirst.clustering.claim_clusterer import (
    ClaimClusterer,
    MAX_CLUSTER_SIZE,
)


# ── Helpers ──────────────────────────────────────────────────────

def _make_claim(
    text: str,
    confidence: float = 0.8,
    structured_form=None,
    doc_id: str = "doc1",
) -> Claim:
    """Crée une Claim minimale pour les tests."""
    return Claim(
        claim_id=f"claim_{uuid.uuid4().hex[:8]}",
        tenant_id="default",
        doc_id=doc_id,
        text=text,
        claim_type=ClaimType.FACTUAL,
        verbatim_quote=text if len(text) >= 10 else text + " " * (10 - len(text)),
        passage_id=f"pass_{uuid.uuid4().hex[:8]}",
        confidence=confidence,
        structured_form=structured_form,
    )


# ── Upgrade 1: Filtres qualité Phase 1.6 ────────────────────────

class TestQualityFilterShortClaims:
    """Filtre 1 : longueur minimale avec exemptions positives."""

    def test_filter_rejects_short_without_signal(self):
        """Claim < 30 chars, pas de SF, pas de version → filtrée."""
        claim = Claim(
            claim_id="c1", tenant_id="default", doc_id="d1",
            text="A short text here.",  # 18 chars, < 30
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="A short text here.",
            passage_id="p1", confidence=0.8,
        )
        kept, stats = filter_claims_quality([claim])
        assert stats["filtered_short"] == 1
        assert len(kept) == 0

    def test_filter_keeps_short_with_structured_form(self):
        """Claim courte avec structured_form complet → gardée."""
        claim = Claim(
            claim_id="c1", tenant_id="default", doc_id="d1",
            text="TLS 1.2 is required.",  # 20 chars
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="TLS 1.2 is required.",
            passage_id="p1", confidence=0.8,
            structured_form={"subject": "TLS", "predicate": "REQUIRES", "object": "1.2"},
        )
        kept, stats = filter_claims_quality([claim])
        assert stats["kept"] == 1
        assert len(kept) == 1

    def test_filter_keeps_short_with_version(self):
        """Pattern version (1.2) → gardée."""
        claim = Claim(
            claim_id="c1", tenant_id="default", doc_id="d1",
            text="Requires TLS 1.2 minimum",  # 24 chars, has version pattern
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Requires TLS 1.2 minimum",
            passage_id="p1", confidence=0.8,
        )
        kept, stats = filter_claims_quality([claim])
        assert stats["kept"] == 1

    def test_filter_keeps_short_with_operator(self):
        """Pattern opérateur (>=) → gardée."""
        claim = Claim(
            claim_id="c1", tenant_id="default", doc_id="d1",
            text="Minimum >= 4 GB RAM",  # 19 chars, has operator
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Minimum >= 4 GB RAM",
            passage_id="p1", confidence=0.8,
        )
        kept, stats = filter_claims_quality([claim])
        assert stats["kept"] == 1

    def test_filter_keeps_short_with_label_value(self):
        """Pattern "label: value" → gardée."""
        claim = Claim(
            claim_id="c1", tenant_id="default", doc_id="d1",
            text="Protocol: HTTPS only",  # 20 chars, label:value
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Protocol: HTTPS only",
            passage_id="p1", confidence=0.8,
        )
        kept, stats = filter_claims_quality([claim])
        assert stats["kept"] == 1


class TestQualityFilterBoilerplate:
    """Filtre 2 : boilerplate universel."""

    def test_filter_rejects_boilerplate_copyright(self):
        """© copyright → filtrée."""
        claim = _make_claim("© 2025 SAP SE All Rights Reserved disclaimer text")
        kept, stats = filter_claims_quality([claim])
        assert stats["filtered_boilerplate"] == 1

    def test_filter_rejects_boilerplate_sap_note(self):
        """SAP Note NNNNN → filtrée."""
        claim = _make_claim("SAP Note 3456789 applies to this configuration")
        kept, stats = filter_claims_quality([claim])
        assert stats["filtered_boilerplate"] == 1

    def test_filter_rejects_url_only(self):
        """URL seule → filtrée."""
        claim = _make_claim("https://help.sap.com/docs/some/long/path/here")
        kept, stats = filter_claims_quality([claim])
        assert stats["filtered_boilerplate"] == 1

    def test_filter_rejects_number_only(self):
        """Numéro seul → filtrée (court + pas de signal)."""
        claim = Claim(
            claim_id="c1", tenant_id="default", doc_id="d1",
            text="42.       ",  # padded to pass min_length validator
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="42.       ",
            passage_id="p1", confidence=0.8,
        )
        kept, stats = filter_claims_quality([claim])
        # Filtered as short (< 30 chars, no positive signal) or boilerplate
        assert len(kept) == 0


class TestQualityFilterHeading:
    """Filtre 3 : heading-like."""

    def test_filter_rejects_heading_like(self):
        """Title case, pas de ponctuation → heading → filtrée."""
        claim = _make_claim("Cloud Integration Best Practices Overview")
        kept, stats = filter_claims_quality([claim])
        assert stats["filtered_heading"] == 1
        assert len(kept) == 0

    def test_filter_keeps_assertion_with_period(self):
        """Terminée par . → signal d'assertion → gardée."""
        claim = _make_claim("Cloud integration uses TLS 1.2.")
        kept, stats = filter_claims_quality([claim])
        assert stats["kept"] == 1

    def test_filter_keeps_assertion_with_comma(self):
        """Contient , → signal d'assertion → gardée."""
        claim = _make_claim("For production, TLS 1.2 is recommended.")
        kept, stats = filter_claims_quality([claim])
        assert stats["kept"] == 1

    def test_filter_keeps_assertion_with_digit(self):
        """Contient chiffres → signal d'assertion → gardée."""
        claim = _make_claim("Supports up to 10 000 concurrent users")
        kept, stats = filter_claims_quality([claim])
        assert stats["kept"] == 1

    def test_is_heading_like_direct(self):
        """Test direct de is_heading_like."""
        # Heading : title case, pas de ponctuation
        assert is_heading_like("Cloud Integration Best Practices Overview") is True
        # Pas heading : a un point
        assert is_heading_like("Cloud integration uses TLS 1.2.") is False
        # Pas heading : trop court
        assert is_heading_like("Short Title") is False
        # Pas heading : trop long
        assert is_heading_like("A" * 81) is False


class TestQualityFilterMultilang:
    """Vérification multilangue."""

    def test_filter_multilang_french(self):
        """Pattern label:value en français → gardée."""
        claim = _make_claim("Version minimale : 2.0 requise pour production")
        kept, stats = filter_claims_quality([claim])
        assert stats["kept"] == 1

    def test_filter_stats_tracking(self):
        """Vérifie les 4 compteurs dans les stats."""
        claims = [
            _make_claim("Cloud Integration Best Practices Overview"),  # heading
            _make_claim("© 2025 SAP SE All Rights Reserved disclaimer text"),  # boilerplate
            _make_claim("This is a valid technical claim with real content."),  # kept
        ]
        # Ajout d'une claim courte
        claims.append(Claim(
            claim_id="c_short", tenant_id="default", doc_id="d1",
            text="Too short!",  # < 30 chars, pas de signal
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Too short!",
            passage_id="p1", confidence=0.8,
        ))
        kept, stats = filter_claims_quality(claims)
        assert "kept" in stats
        assert "filtered_short" in stats
        assert "filtered_boilerplate" in stats
        assert "filtered_heading" in stats
        total = stats["kept"] + stats["filtered_short"] + stats["filtered_boilerplate"] + stats["filtered_heading"]
        assert total == len(claims)


class TestHasPositiveSignal:
    """Test direct des signaux positifs."""

    def test_version_signal(self):
        claim = _make_claim("Requires TLS 1.2 minimum")
        assert has_positive_signal(claim) is True

    def test_operator_signal(self):
        claim = Claim(
            claim_id="c1", tenant_id="default", doc_id="d1",
            text="Memory >= 4 GB",
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Memory >= 4 GB",
            passage_id="p1", confidence=0.8,
        )
        assert has_positive_signal(claim) is True

    def test_unit_signal(self):
        claim = Claim(
            claim_id="c1", tenant_id="default", doc_id="d1",
            text="Latency 50ms max",
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Latency 50ms max",
            passage_id="p1", confidence=0.8,
        )
        assert has_positive_signal(claim) is True

    def test_no_signal(self):
        claim = Claim(
            claim_id="c1", tenant_id="default", doc_id="d1",
            text="Just a word.",
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Just a word.",
            passage_id="p1", confidence=0.8,
        )
        assert has_positive_signal(claim) is False


# ── Upgrade 2: Entity ponctuation ────────────────────────────────

class TestEntityPunctuation:
    """Filtres de ponctuation dans is_valid_entity_name."""

    def test_entity_rejects_comma_in_name(self):
        assert is_valid_entity_name("Cloud Integration, batch mode") is False

    def test_entity_rejects_semicolon(self):
        assert is_valid_entity_name("TLS; SSL") is False

    def test_entity_rejects_sentence_dot(self):
        assert is_valid_entity_name("Integration supports real-time.") is False

    def test_entity_keeps_version_dot(self):
        """"S/4HANA 2.0" → accepté (. dans version)."""
        assert is_valid_entity_name("S/4HANA 2.0") is True

    def test_entity_rejects_long_parenthesis(self):
        assert is_valid_entity_name(
            "Cloud Platform (with all integrated services and APIs)"
        ) is False

    def test_entity_keeps_short_parenthesis(self):
        assert is_valid_entity_name("SAP BTP (BTP)") is True

    def test_entity_keeps_6_word_name(self):
        assert is_valid_entity_name("SAP S/4HANA Cloud Central Finance") is True


# ── Upgrade 3: Cap clusters ──────────────────────────────────────

class TestClusterCap:
    """Cap de taille MAX_CLUSTER_SIZE=50."""

    def test_max_cluster_size_constant(self):
        assert MAX_CLUSTER_SIZE == 50

    def test_cluster_cap_keeps_small(self):
        """10 claims → cluster de 10, pas impacté par le cap."""
        clusterer = ClaimClusterer()
        claims = [
            _make_claim(f"Claim number {i} about the same topic.", doc_id=f"doc{i}")
            for i in range(10)
        ]
        valid_pairs = []
        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                valid_pairs.append((claims[i], claims[j]))
        clusters = clusterer._build_clusters(claims, valid_pairs, "default")
        assert len(clusters) == 1
        assert clusters[0].claim_count == 10

    def test_cluster_cap_trims_large(self):
        """80 claims → cluster de max 50."""
        clusterer = ClaimClusterer()
        claims = [
            _make_claim(
                f"Claim number {i:03d} about the same technical topic.",
                doc_id=f"doc{i}",
            )
            for i in range(80)
        ]
        # Chaîne linéaire → Union-Find regroupe tout
        valid_pairs = []
        for i in range(len(claims) - 1):
            valid_pairs.append((claims[i], claims[i + 1]))
        clusters = clusterer._build_clusters(claims, valid_pairs, "default")
        assert len(clusters) == 1
        assert clusters[0].claim_count <= MAX_CLUSTER_SIZE

    def test_cluster_unique_ids_deterministic(self):
        """Même input → même output (sorted)."""
        clusterer = ClaimClusterer()
        claims = [
            _make_claim(f"Claim about topic {i} in detail.", doc_id=f"doc{i}")
            for i in range(5)
        ]
        valid_pairs = [
            (claims[0], claims[1]),
            (claims[1], claims[2]),
            (claims[2], claims[3]),
            (claims[3], claims[4]),
        ]
        clusters_1 = clusterer._build_clusters(claims, valid_pairs, "default")
        clusters_2 = clusterer._build_clusters(claims, valid_pairs, "default")
        assert clusters_1[0].claim_ids == clusters_2[0].claim_ids
        assert clusters_1[0].claim_ids == sorted(clusters_1[0].claim_ids)


class TestTrimToCore:
    """Méthode _trim_to_core pour sélection par centroïde."""

    def test_trim_to_core_selects_closest(self):
        """Les claims proches du centroïde sont gardées."""
        clusterer = ClaimClusterer()
        claims = [
            _make_claim(
                f"Claim about technical topic number {i}.",
                doc_id=f"doc{i}",
            )
            for i in range(10)
        ]
        embeddings = {}
        for i, c in enumerate(claims):
            if i < 8:
                vec = np.zeros(10)
                vec[0] = 1.0
                vec[1] = 0.01 * i
            else:
                vec = np.zeros(10)
                vec[5] = 1.0  # outlier
            embeddings[c.claim_id] = vec

        result = clusterer._trim_to_core(claims, embeddings, max_size=5)
        assert len(result) == 5
        outlier_ids = {claims[8].claim_id, claims[9].claim_id}
        kept_ids = {c.claim_id for c in result}
        assert len(outlier_ids & kept_ids) <= 1

    def test_trim_to_core_fallback_no_embeddings(self):
        """Sans embeddings → fallback confiance."""
        clusterer = ClaimClusterer()
        claims = [
            _make_claim("High confidence claim about the topic.", confidence=0.95),
            _make_claim("Medium confidence claim about things.", confidence=0.7),
            _make_claim("Low confidence claim about something.", confidence=0.3),
        ]
        result = clusterer._trim_to_core(claims, {}, max_size=2)
        assert len(result) == 2
        assert result[0].confidence >= result[1].confidence
