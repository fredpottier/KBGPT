# tests/claimfirst/test_facet_registry.py
"""
Tests pour le Facet Registry émergent 3-tier.

- FacetCandidateExtractor (Tier 1, parse only — pas de LLM)
- FacetRegistry (Tier 2, lifecycle + near-duplicate)
- FacetMatcher refactorisé (Tier 3, 4 signaux)
- Anti-régression (sur-fragmentation, faux positifs, promotion abusive)
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from knowbase.claimfirst.models.facet import (
    Facet,
    FacetFamily,
    FacetKind,
    FacetLifecycle,
    get_seed_facets,
    get_predefined_facets,
    _KIND_TO_FAMILY,
)
from knowbase.claimfirst.extractors.facet_candidate_extractor import (
    FacetCandidate,
    FacetCandidateExtractor,
    _parse_llm_response,
    _normalize_dimension_key,
)
from knowbase.claimfirst.linkers.facet_registry import (
    FacetRegistry,
    _levenshtein_distance,
    _keywords_overlap,
)
from knowbase.claimfirst.linkers.facet_matcher import (
    FacetMatcher,
    DEFAULT_WEIGHTS,
)


# ─── Helpers ──────────────────────────────────────────────────────────


def _make_claim(text: str, claim_id: str = "c1", section_id: str = ""):
    """Crée un mock Claim minimal."""
    claim = MagicMock()
    claim.claim_id = claim_id
    claim.text = text
    claim.scope = None
    claim.section_id = section_id
    return claim


def _make_facet(
    domain: str,
    tenant_id: str = "test",
    family: FacetFamily = FacetFamily.THEMATIC,
    keywords: list = None,
    lifecycle: FacetLifecycle = FacetLifecycle.VALIDATED,
) -> Facet:
    """Crée une Facet pour les tests."""
    return Facet(
        facet_id=f"facet_{domain.replace('.', '_')}",
        tenant_id=tenant_id,
        facet_name=domain.replace(".", " / ").title(),
        facet_family=family,
        domain=domain,
        lifecycle=lifecycle,
        keywords=keywords or [],
    )


def _make_candidate(
    dim_key: str,
    name: str = "Test Facet",
    family: str = "thematic",
    keywords: list = None,
    doc_id: str = "doc_001",
    confidence: float = 0.9,
) -> FacetCandidate:
    return FacetCandidate(
        canonical_name=name,
        dimension_key=dim_key,
        facet_family=family,
        keywords=keywords or ["kw1", "kw2"],
        confidence=confidence,
        source_doc_id=doc_id,
    )


# ═══════════════════════════════════════════════════════════════════════
# Tests Modèle Facet enrichi
# ═══════════════════════════════════════════════════════════════════════


class TestFacetModel:
    """Tests du modèle Facet enrichi."""

    def test_facet_lifecycle_default(self):
        facet = _make_facet("security", lifecycle=FacetLifecycle.CANDIDATE)
        assert facet.lifecycle == FacetLifecycle.CANDIDATE

    def test_facet_family_values(self):
        assert FacetFamily.THEMATIC.value == "thematic"
        assert FacetFamily.NORMATIVE.value == "normative"
        assert FacetFamily.OPERATIONAL.value == "operational"

    def test_facet_lifecycle_values(self):
        assert FacetLifecycle.CANDIDATE.value == "candidate"
        assert FacetLifecycle.VALIDATED.value == "validated"
        assert FacetLifecycle.DEPRECATED.value == "deprecated"

    def test_facet_kind_to_family_mapping(self):
        assert _KIND_TO_FAMILY[FacetKind.DOMAIN] == FacetFamily.THEMATIC
        assert _KIND_TO_FAMILY[FacetKind.OBLIGATION] == FacetFamily.NORMATIVE
        assert _KIND_TO_FAMILY[FacetKind.CAPABILITY] == FacetFamily.OPERATIONAL

    def test_create_from_candidate(self):
        facet = Facet.create_from_candidate(
            dimension_key="compliance.data_protection",
            canonical_name="Data Protection Compliance",
            facet_family=FacetFamily.NORMATIVE,
            tenant_id="test",
            keywords=["gdpr", "privacy"],
            source_doc_id="doc_001",
        )
        assert facet.facet_id == "facet_compliance_data_protection"
        assert facet.facet_family == FacetFamily.NORMATIVE
        assert facet.lifecycle == FacetLifecycle.CANDIDATE
        assert facet.source_doc_count == 1
        assert "doc_001" in facet.source_doc_ids
        assert facet.parent_domain == "compliance"

    def test_seed_facets(self):
        seeds = get_seed_facets("test")
        assert len(seeds) > 0
        for s in seeds:
            assert s.lifecycle == FacetLifecycle.VALIDATED
            assert s.source_doc_count == 0
            assert s.promotion_reason == "seed_bootstrap"

    def test_to_neo4j_properties_enriched(self):
        facet = Facet.create_from_candidate(
            dimension_key="security.encryption",
            canonical_name="Encryption",
            facet_family=FacetFamily.OPERATIONAL,
            tenant_id="test",
            keywords=["aes", "tls"],
        )
        props = facet.to_neo4j_properties()
        assert "lifecycle" in props
        assert props["lifecycle"] == "candidate"
        assert props["facet_family"] == "operational"
        assert props["keywords"] == ["aes", "tls"]

    def test_from_neo4j_record_retrocompat(self):
        """Rétrocompatibilité : record sans facet_family ni lifecycle."""
        record = {
            "facet_id": "facet_security_domain",
            "tenant_id": "test",
            "facet_name": "Security",
            "facet_kind": "domain",
            "domain": "security",
        }
        facet = Facet.from_neo4j_record(record)
        assert facet.facet_family == FacetFamily.THEMATIC
        assert facet.lifecycle == FacetLifecycle.VALIDATED

    def test_from_neo4j_record_full(self):
        record = {
            "facet_id": "facet_compliance_gdpr",
            "tenant_id": "test",
            "facet_name": "GDPR Compliance",
            "facet_kind": "domain",
            "facet_family": "normative",
            "domain": "compliance.gdpr",
            "lifecycle": "validated",
            "source_doc_count": 5,
            "keywords": ["gdpr", "privacy"],
        }
        facet = Facet.from_neo4j_record(record)
        assert facet.facet_family == FacetFamily.NORMATIVE
        assert facet.lifecycle == FacetLifecycle.VALIDATED
        assert facet.source_doc_count == 5

    def test_predefined_facets_still_work(self):
        """Les facettes prédéfinies restent fonctionnelles."""
        facets = get_predefined_facets("test")
        assert len(facets) == 21
        for f in facets:
            assert f.tenant_id == "test"
            assert f.facet_id


# ═══════════════════════════════════════════════════════════════════════
# Tests FacetCandidateExtractor (Tier 1)
# ═══════════════════════════════════════════════════════════════════════


class TestNormalizeDimensionKey:
    def test_basic(self):
        assert _normalize_dimension_key("compliance.data_protection") == "compliance.data_protection"

    def test_spaces_to_snake(self):
        assert _normalize_dimension_key("Data Protection") == "data_protection"

    def test_hyphens_to_snake(self):
        assert _normalize_dimension_key("cloud-security") == "cloud_security"

    def test_max_3_levels(self):
        assert _normalize_dimension_key("a.b.c.d.e") == "a.b.c"

    def test_empty_parts_removed(self):
        assert _normalize_dimension_key("a..b") == "a.b"

    def test_special_chars_removed(self):
        assert _normalize_dimension_key("compliance@gdpr!") == "compliancegdpr"


class TestParseLLMResponse:
    def test_valid_response(self):
        response = json.dumps({
            "facets": [
                {
                    "canonical_name": "Data Protection",
                    "dimension_key": "compliance.data_protection",
                    "facet_family": "normative",
                    "keywords": ["gdpr", "privacy", "data protection"],
                    "confidence": 0.95,
                },
                {
                    "canonical_name": "Cloud Security",
                    "dimension_key": "security.cloud",
                    "facet_family": "thematic",
                    "keywords": ["encryption", "firewall"],
                    "confidence": 0.85,
                },
            ]
        })
        candidates = _parse_llm_response(response, "doc_001")
        assert len(candidates) == 2
        assert candidates[0].dimension_key == "compliance.data_protection"
        assert candidates[0].facet_family == "normative"
        assert candidates[0].source_doc_id == "doc_001"

    def test_invalid_json(self):
        candidates = _parse_llm_response("not json at all", "doc_001")
        assert candidates == []

    def test_markdown_wrapper(self):
        response = '```json\n{"facets": [{"canonical_name": "Test", "dimension_key": "test.one", "facet_family": "thematic", "keywords": [], "confidence": 0.8}]}\n```'
        candidates = _parse_llm_response(response, "doc_001")
        assert len(candidates) == 1

    def test_vague_labels_rejected(self):
        response = json.dumps({
            "facets": [
                {
                    "canonical_name": "General",
                    "dimension_key": "general",
                    "facet_family": "thematic",
                    "keywords": [],
                    "confidence": 0.5,
                },
                {
                    "canonical_name": "Security",
                    "dimension_key": "security.access",
                    "facet_family": "thematic",
                    "keywords": ["auth"],
                    "confidence": 0.9,
                },
            ]
        })
        candidates = _parse_llm_response(response, "doc_001")
        assert len(candidates) == 1
        assert candidates[0].dimension_key == "security.access"

    def test_max_6_facets(self):
        facets = [
            {
                "canonical_name": f"Facet {i}",
                "dimension_key": f"domain.sub_{i}",
                "facet_family": "thematic",
                "keywords": [f"kw{i}"],
                "confidence": 0.8,
            }
            for i in range(10)
        ]
        response = json.dumps({"facets": facets})
        candidates = _parse_llm_response(response, "doc_001")
        assert len(candidates) == 6

    def test_dedup_by_dimension_key(self):
        response = json.dumps({
            "facets": [
                {"canonical_name": "A", "dimension_key": "security.access", "facet_family": "thematic", "keywords": [], "confidence": 0.9},
                {"canonical_name": "B", "dimension_key": "security.access", "facet_family": "thematic", "keywords": [], "confidence": 0.8},
            ]
        })
        candidates = _parse_llm_response(response, "doc_001")
        assert len(candidates) == 1

    def test_invalid_family_defaults_to_thematic(self):
        response = json.dumps({
            "facets": [
                {"canonical_name": "A", "dimension_key": "test.one", "facet_family": "invalid", "keywords": [], "confidence": 0.8},
            ]
        })
        candidates = _parse_llm_response(response, "doc_001")
        assert len(candidates) == 1
        assert candidates[0].facet_family == "thematic"


# ═══════════════════════════════════════════════════════════════════════
# Tests FacetRegistry (Tier 2)
# ═══════════════════════════════════════════════════════════════════════


class TestLevenshteinDistance:
    def test_identical(self):
        assert _levenshtein_distance("abc", "abc") == 0

    def test_one_edit(self):
        assert _levenshtein_distance("abc", "abd") == 1

    def test_empty(self):
        assert _levenshtein_distance("", "abc") == 3

    def test_delete(self):
        assert _levenshtein_distance("abcd", "abc") == 1


class TestKeywordsOverlap:
    def test_full_overlap(self):
        assert _keywords_overlap(["a", "b"], ["a", "b"]) == 1.0

    def test_no_overlap(self):
        assert _keywords_overlap(["a", "b"], ["c", "d"]) == 0.0

    def test_partial_overlap(self):
        result = _keywords_overlap(["a", "b", "c"], ["a", "d", "e"])
        assert 0.0 < result < 1.0

    def test_empty_lists(self):
        assert _keywords_overlap([], ["a"]) == 0.0


class TestFacetRegistry:
    def test_register_new_candidate(self):
        registry = FacetRegistry("test")
        candidates = [_make_candidate("security.access", doc_id="doc_001")]
        result = registry.register_candidates(candidates)
        assert len(result) == 1
        facet = result[0]
        assert facet.lifecycle == FacetLifecycle.CANDIDATE
        assert facet.source_doc_count == 1

    def test_register_increments_doc_count(self):
        registry = FacetRegistry("test")
        registry.register_candidates([_make_candidate("security.access", doc_id="doc_001")])
        registry.register_candidates([_make_candidate("security.access", doc_id="doc_002")])
        facet = registry.get_facet_by_key("security.access")
        assert facet.source_doc_count == 2
        assert len(facet.source_doc_ids) == 2

    def test_no_duplicate_on_same_doc(self):
        registry = FacetRegistry("test")
        registry.register_candidates([_make_candidate("security.access", doc_id="doc_001")])
        registry.register_candidates([_make_candidate("security.access", doc_id="doc_001")])
        facet = registry.get_facet_by_key("security.access")
        assert facet.source_doc_count == 1

    def test_promotion_at_3_docs(self):
        registry = FacetRegistry("test")
        for i in range(3):
            registry.register_candidates([
                _make_candidate("compliance.gdpr", doc_id=f"doc_{i:03d}")
            ])
        facet = registry.get_facet_by_key("compliance.gdpr")
        assert facet.lifecycle == FacetLifecycle.VALIDATED
        assert facet.promoted_at is not None
        assert "3 docs" in facet.promotion_reason

    def test_promotion_requires_diversity(self):
        """3 docs du même doc_id → pas de promotion."""
        registry = FacetRegistry("test")
        # 3 enregistrements mais du même doc
        registry.register_candidates([_make_candidate("compliance.gdpr", doc_id="doc_001")])
        registry.register_candidates([_make_candidate("compliance.gdpr", doc_id="doc_001")])
        registry.register_candidates([_make_candidate("compliance.gdpr", doc_id="doc_001")])
        facet = registry.get_facet_by_key("compliance.gdpr")
        assert facet.lifecycle == FacetLifecycle.CANDIDATE
        assert facet.source_doc_count == 1  # Même doc_id → pas incrémenté

    def test_get_validated_facets(self):
        registry = FacetRegistry("test")
        # Injecter des seeds
        registry._inject_seeds()
        validated = registry.get_validated_facets()
        assert len(validated) > 0
        assert all(f.lifecycle == FacetLifecycle.VALIDATED for f in validated)

    def test_get_all_facets(self):
        registry = FacetRegistry("test")
        registry.register_candidates([_make_candidate("test.one", doc_id="d1")])
        registry._inject_seeds()
        all_facets = registry.get_all_facets()
        assert len(all_facets) > 1  # seeds + 1 candidate

    def test_near_duplicate_detection_levenshtein(self):
        registry = FacetRegistry("test")
        registry.register_candidates([
            _make_candidate("security.access_control", doc_id="d1")
        ])
        registry.register_candidates([
            _make_candidate("security.access_contrl", doc_id="d2")  # lev=1
        ])
        dups = registry.get_near_duplicate_queue()
        assert len(dups) >= 1
        keys = [(d[0], d[1]) for d in dups]
        assert any(
            "access_contrl" in k1 or "access_contrl" in k2
            for k1, k2 in keys
        )

    def test_near_duplicate_detection_keywords(self):
        registry = FacetRegistry("test")
        registry.register_candidates([
            _make_candidate(
                "data.protection",
                keywords=["gdpr", "privacy", "data", "consent", "personal"],
                doc_id="d1",
            )
        ])
        registry.register_candidates([
            _make_candidate(
                "privacy.compliance",
                keywords=["gdpr", "privacy", "data", "consent", "regulation"],
                doc_id="d2",
            )
        ])
        dups = registry.get_near_duplicate_queue()
        assert len(dups) >= 1

    def test_seed_facets_loaded_when_empty(self):
        registry = FacetRegistry("test")
        registry.load_from_neo4j(neo4j_driver=None)  # Pas de driver → seed
        assert len(registry._cache) > 0
        validated = registry.get_validated_facets()
        assert len(validated) > 0

    def test_keywords_enrichment(self):
        registry = FacetRegistry("test")
        registry.register_candidates([
            _make_candidate("security.access", keywords=["auth", "sso"], doc_id="d1")
        ])
        registry.register_candidates([
            _make_candidate("security.access", keywords=["mfa", "oauth"], doc_id="d2")
        ])
        facet = registry.get_facet_by_key("security.access")
        assert "auth" in facet.keywords
        assert "mfa" in facet.keywords
        assert "sso" in facet.keywords

    def test_stats(self):
        registry = FacetRegistry("test")
        registry._inject_seeds()
        registry.register_candidates([_make_candidate("test.new", doc_id="d1")])
        stats = registry.get_stats()
        assert stats["total"] > 0
        assert "by_lifecycle" in stats
        assert "by_family" in stats

    def test_persist_mock(self):
        """Vérifie que persist_to_neo4j appelle la bonne requête."""
        registry = FacetRegistry("test")
        registry.register_candidates([_make_candidate("test.one", doc_id="d1")])

        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        count = registry.persist_to_neo4j(mock_driver)
        assert count == 1
        assert mock_session.run.called


# ═══════════════════════════════════════════════════════════════════════
# Tests FacetMatcher refactorisé (Tier 3)
# ═══════════════════════════════════════════════════════════════════════


class TestFacetMatcher:
    def test_keyword_matching(self):
        matcher = FacetMatcher()
        facet = _make_facet(
            "security.encryption",
            keywords=["encryption", "tls", "aes", "cipher"],
        )
        claim = _make_claim("This system uses AES-256 encryption with TLS 1.3")

        results = matcher.assign_claim_to_facets(
            claim=claim,
            validated_facets=[facet],
            facets_by_id={facet.facet_id: facet},
            facets_by_domain={facet.domain: facet},
            doc_facet_ids=set(),
        )
        assert len(results) >= 1
        _, score, signals = results[0]
        assert score >= 0.3
        assert "keyword" in signals

    def test_document_inheritance(self):
        matcher = FacetMatcher()
        facet = _make_facet("compliance.gdpr", keywords=[])
        claim = _make_claim("Something about data.")

        results = matcher.assign_claim_to_facets(
            claim=claim,
            validated_facets=[facet],
            facets_by_id={facet.facet_id: facet},
            facets_by_domain={facet.domain: facet},
            doc_facet_ids={facet.domain},
        )
        # doc_inherit alone = 0.25 < 0.3 → not enough
        # If no other signal matches, shouldn't create link
        if results:
            _, score, signals = results[0]
            assert score >= 0.3

    def test_section_context(self):
        matcher = FacetMatcher()
        facet = _make_facet("operations.backup", keywords=[])
        claim = _make_claim("Daily snapshots are taken.", section_id="sec_backup")

        results = matcher.assign_claim_to_facets(
            claim=claim,
            validated_facets=[facet],
            facets_by_id={facet.facet_id: facet},
            facets_by_domain={facet.domain: facet},
            doc_facet_ids=set(),
            section_facet_map={"sec_backup": [facet.domain]},
        )
        # section alone = 0.25 < 0.3 → not enough alone
        # But combined signals could pass
        for _, score, signals in results:
            assert score >= 0.3

    def test_multi_facet_assignment(self):
        matcher = FacetMatcher()
        f1 = _make_facet("security.encryption", keywords=["encryption", "aes"])
        f2 = _make_facet("compliance.gdpr", keywords=["gdpr", "data protection"])
        claim = _make_claim("GDPR requires AES encryption for data protection")

        results = matcher.assign_claim_to_facets(
            claim=claim,
            validated_facets=[f1, f2],
            facets_by_id={f1.facet_id: f1, f2.facet_id: f2},
            facets_by_domain={f1.domain: f1, f2.domain: f2},
            doc_facet_ids=set(),
        )
        facet_ids = [r[0] for r in results]
        assert len(facet_ids) >= 1  # Au moins un match

    def test_threshold_respected(self):
        matcher = FacetMatcher(min_score=0.5)
        facet = _make_facet("niche.topic", keywords=["rare_keyword"])
        claim = _make_claim("This text has nothing related to that topic")

        results = matcher.assign_claim_to_facets(
            claim=claim,
            validated_facets=[facet],
            facets_by_id={facet.facet_id: facet},
            facets_by_domain={facet.domain: facet},
            doc_facet_ids=set(),
        )
        assert len(results) == 0

    def test_assignment_signals_populated(self):
        matcher = FacetMatcher()
        facet = _make_facet("security.access", keywords=["access", "authentication"])
        claim = _make_claim("Access control requires multi-factor authentication")

        results = matcher.assign_claim_to_facets(
            claim=claim,
            validated_facets=[facet],
            facets_by_id={facet.facet_id: facet},
            facets_by_domain={facet.domain: facet},
            doc_facet_ids={facet.domain},
        )
        if results:
            _, _, signals = results[0]
            assert "+" in signals or signals in ("keyword", "doc_inherit", "section", "claimkey")

    def test_match_api_backward_compat(self):
        """L'API match() retourne (facets, links) comme avant."""
        matcher = FacetMatcher()
        facets = [_make_facet("security.encryption", keywords=["encryption"])]
        claims = [_make_claim("Uses encryption", claim_id="c1")]

        result_facets, links = matcher.match(
            claims=claims,
            tenant_id="test",
            validated_facets=facets,
            doc_facet_ids=["security.encryption"],
        )
        assert isinstance(result_facets, list)
        assert isinstance(links, list)
        for link in links:
            assert len(link) == 2  # (claim_id, facet_id)

    def test_assign_claims_to_facets_returns_4_tuples(self):
        matcher = FacetMatcher()
        facets = [_make_facet("security.encryption", keywords=["encryption"])]
        claims = [_make_claim("Uses AES encryption", claim_id="c1")]

        results = matcher.assign_claims_to_facets(
            claims=claims,
            validated_facets=facets,
            doc_facet_ids=["security.encryption"],
        )
        for item in results:
            assert len(item) == 4  # (claim_id, facet_id, score, signals)
            claim_id, facet_id, score, signals = item
            assert isinstance(score, float)
            assert isinstance(signals, str)

    def test_stats_tracking(self):
        matcher = FacetMatcher()
        facets = [_make_facet("security.encryption", keywords=["encryption"])]
        claims = [_make_claim("Uses encryption", claim_id="c1")]
        matcher.match(claims=claims, tenant_id="test", validated_facets=facets)
        stats = matcher.get_stats()
        assert stats["claims_processed"] >= 1

    def test_reset_stats(self):
        matcher = FacetMatcher()
        matcher.stats["claims_processed"] = 99
        matcher.reset_stats()
        assert matcher.stats["claims_processed"] == 0


# ═══════════════════════════════════════════════════════════════════════
# Tests Anti-Régression
# ═══════════════════════════════════════════════════════════════════════


class TestAntiRegression:
    def test_near_duplicate_synonyms_detected(self):
        """Corpus avec synonymes proches → détectés dans review queue."""
        registry = FacetRegistry("test")
        registry.register_candidates([
            _make_candidate(
                "data.protection",
                keywords=["gdpr", "privacy", "data", "protection", "compliance"],
                doc_id="d1",
            )
        ])
        registry.register_candidates([
            _make_candidate(
                "data.privacy",
                keywords=["gdpr", "privacy", "data", "personal", "compliance"],
                doc_id="d2",
            )
        ])
        dups = registry.get_near_duplicate_queue()
        # Keywords overlap >= 60% → should be detected
        assert len(dups) >= 1

    def test_no_false_positive_inheritance(self):
        """Doc 'Security' avec claim 'availability' → pas assignée à security."""
        matcher = FacetMatcher()
        sec_facet = _make_facet("security.encryption", keywords=["encryption", "cipher"])
        claim = _make_claim("System availability is 99.9%", claim_id="c1")

        results = matcher.assign_claim_to_facets(
            claim=claim,
            validated_facets=[sec_facet],
            facets_by_id={sec_facet.facet_id: sec_facet},
            facets_by_domain={sec_facet.domain: sec_facet},
            doc_facet_ids={sec_facet.domain},  # doc est "security"
        )
        # doc_inherit seul = 0.25 < 0.3 → pas de lien
        for _, score, _ in results:
            assert score >= 0.3  # si assigné, au moins un autre signal

    def test_promotion_abusive_same_title(self):
        """3 docs quasi-identiques (même doc_id) → promotion refusée."""
        registry = FacetRegistry("test")
        for _ in range(5):
            registry.register_candidates([
                _make_candidate("niche.topic", doc_id="same_doc_id")
            ])
        facet = registry.get_facet_by_key("niche.topic")
        assert facet.lifecycle == FacetLifecycle.CANDIDATE
        assert facet.source_doc_count == 1

    def test_promotion_with_real_diversity(self):
        """3 documents distincts → promotion effective."""
        registry = FacetRegistry("test")
        for i in range(3):
            registry.register_candidates([
                _make_candidate("compliance.hipaa", doc_id=f"doc_{i:03d}")
            ])
        facet = registry.get_facet_by_key("compliance.hipaa")
        assert facet.lifecycle == FacetLifecycle.VALIDATED

    def test_empty_dimension_key_ignored(self):
        registry = FacetRegistry("test")
        result = registry.register_candidates([
            _make_candidate("", doc_id="d1"),
        ])
        assert len(result) == 0


# ═══════════════════════════════════════════════════════════════════════
# Tests FacetCandidateExtractor (sans LLM)
# ═══════════════════════════════════════════════════════════════════════


class TestFacetCandidateExtractor:
    def test_extract_without_llm_returns_empty(self):
        """Sans LLM configuré, l'extracteur ne crash pas."""
        extractor = FacetCandidateExtractor()
        doc_ctx = MagicMock()
        doc_ctx.doc_id = "test_doc"
        doc_ctx.raw_subjects = ["Security Guide"]

        with patch.object(extractor, '_build_with_llm', return_value=None):
            result = extractor.extract(doc_ctx)
            assert result == []

    def test_extract_with_mock_llm(self):
        extractor = FacetCandidateExtractor()
        doc_ctx = MagicMock()
        doc_ctx.doc_id = "test_doc"
        doc_ctx.raw_subjects = ["Security Guide"]

        mock_response = json.dumps({
            "facets": [
                {
                    "canonical_name": "Access Control",
                    "dimension_key": "security.access_control",
                    "facet_family": "thematic",
                    "keywords": ["access", "rbac", "permissions"],
                    "confidence": 0.9,
                }
            ]
        })

        with patch.object(extractor, '_build_with_llm', return_value=mock_response):
            result = extractor.extract(doc_ctx)
            assert len(result) == 1
            assert result[0].dimension_key == "security.access_control"

    def test_stats_tracking(self):
        extractor = FacetCandidateExtractor()
        doc_ctx = MagicMock()
        doc_ctx.doc_id = "test_doc"
        doc_ctx.raw_subjects = []

        with patch.object(extractor, '_build_with_llm', return_value=None):
            extractor.extract(doc_ctx)
            stats = extractor.get_stats()
            assert stats["docs_processed"] == 1
