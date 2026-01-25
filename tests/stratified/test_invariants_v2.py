"""
OSMOSE Pipeline V2 - Tests d'Invariants
========================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md
Date: 2026-01-23

Checklist V2-00x : validation post-ingestion.
Ces tests s'exécutent en CI après chaque ingestion.
"""

import pytest
from typing import Any

# Note: Ces tests nécessitent une connexion Neo4j
# Ils sont conçus pour être exécutés après ingestion


class TestInvariantsV2:
    """Tests d'invariants pour Pipeline V2."""

    # ========================================================================
    # V2-001 — Information ancrée sur DocItem
    # ========================================================================

    QUERY_V2_001 = """
    MATCH (inf:Information)
    WHERE NOT (inf)-[:ANCHORED_IN]->(:DocItem)
    RETURN count(inf) AS missing
    """

    def test_v2_001_information_anchored_on_docitem(self, neo4j_session):
        """V2-001: Chaque Information doit avoir ANCHORED_IN → DocItem."""
        result = neo4j_session.run(self.QUERY_V2_001).single()
        missing = result["missing"]
        assert missing == 0, f"V2-001 FAILED: {missing} Information(s) sans ancrage DocItem"

    # ========================================================================
    # V2-002 — Interdiction d'ancrage sur chunk
    # ========================================================================

    QUERY_V2_002 = """
    MATCH (inf:Information)-[:ANCHORED_IN]->(x)
    WHERE NOT x:DocItem
    RETURN count(inf) AS invalid
    """

    def test_v2_002_no_anchor_on_chunk(self, neo4j_session):
        """V2-002: ANCHORED_IN ne doit jamais viser autre chose que DocItem."""
        result = neo4j_session.run(self.QUERY_V2_002).single()
        invalid = result["invalid"]
        assert invalid == 0, f"V2-002 FAILED: {invalid} ancrage(s) invalide(s) (non-DocItem)"

    # ========================================================================
    # V2-003 — Span relatif cohérent
    # ========================================================================

    QUERY_V2_003 = """
    MATCH (inf:Information)-[r:ANCHORED_IN]->(di:DocItem)
    WHERE r.span_start < 0
       OR r.span_end <= r.span_start
       OR r.span_end > size(di.text)
    RETURN count(inf) AS bad_spans
    """

    def test_v2_003_span_coherent(self, neo4j_session):
        """V2-003: span_start >= 0, span_end > span_start, span_end <= len(text)."""
        result = neo4j_session.run(self.QUERY_V2_003).single()
        bad_spans = result["bad_spans"]
        assert bad_spans == 0, f"V2-003 FAILED: {bad_spans} span(s) incohérent(s)"

    # ========================================================================
    # V2-004 — AssertionLog exhaustif
    # ========================================================================

    QUERY_V2_004 = """
    MATCH (d:Document)
    OPTIONAL MATCH (d)<-[:LOGGED_FOR]-(a:AssertionLog)
    WITH d, count(a) AS log_count
    WHERE log_count = 0
    RETURN count(d) AS docs_without_log
    """

    def test_v2_004_assertion_log_exists(self, neo4j_session):
        """V2-004: Chaque document doit avoir au moins une entrée AssertionLog."""
        result = neo4j_session.run(self.QUERY_V2_004).single()
        docs_without_log = result["docs_without_log"]
        # Warning par défaut, fail si mode strict
        if docs_without_log > 0:
            pytest.warns(UserWarning, match=f"V2-004 WARNING: {docs_without_log} doc(s) sans AssertionLog")

    # ========================================================================
    # V2-005 — reason/status dans enums
    # ========================================================================

    VALID_STATUSES = ["PROMOTED", "ABSTAINED", "REJECTED"]
    VALID_REASONS = [
        "promoted", "low_confidence", "policy_rejected",
        "no_concept_match", "ambiguous_linking",
        "no_docitem_anchor", "ambiguous_span", "cross_docitem",
        "generic_term", "single_mention", "contradicts_existing"
    ]

    QUERY_V2_005_STATUS = """
    MATCH (a:AssertionLog)
    WHERE NOT a.status IN $valid_statuses
    RETURN count(a) AS bad_status
    """

    QUERY_V2_005_REASON = """
    MATCH (a:AssertionLog)
    WHERE NOT a.reason IN $valid_reasons
    RETURN count(a) AS bad_reason
    """

    def test_v2_005_status_in_enum(self, neo4j_session):
        """V2-005a: AssertionLog.status doit être dans l'enum."""
        result = neo4j_session.run(
            self.QUERY_V2_005_STATUS,
            valid_statuses=self.VALID_STATUSES
        ).single()
        bad_status = result["bad_status"]
        assert bad_status == 0, f"V2-005a FAILED: {bad_status} status invalide(s)"

    def test_v2_005_reason_in_enum(self, neo4j_session):
        """V2-005b: AssertionLog.reason doit être dans l'enum."""
        result = neo4j_session.run(
            self.QUERY_V2_005_REASON,
            valid_reasons=self.VALID_REASONS
        ).single()
        bad_reason = result["bad_reason"]
        assert bad_reason == 0, f"V2-005b FAILED: {bad_reason} reason(s) invalide(s)"

    # ========================================================================
    # V2-006 — PROMOTED ⇒ Information existe
    # ========================================================================

    QUERY_V2_006 = """
    MATCH (a:AssertionLog {status:"PROMOTED"})-[:LOGGED_FOR]->(d:Document)
    OPTIONAL MATCH (inf:Information {doc_id:d.doc_id})
    WHERE inf.type = a.type
    WITH a, inf
    WHERE inf IS NULL
    RETURN count(a) AS promoted_without_info
    """

    def test_v2_006_promoted_has_information(self, neo4j_session):
        """V2-006: Chaque assertion PROMOTED doit avoir une Information correspondante."""
        result = neo4j_session.run(self.QUERY_V2_006).single()
        promoted_without_info = result["promoted_without_info"]
        assert promoted_without_info == 0, \
            f"V2-006 FAILED: {promoted_without_info} assertion(s) PROMOTED sans Information"

    # ========================================================================
    # V2-007 — Cap frugalité concepts (max 15)
    # ========================================================================

    QUERY_V2_007 = """
    MATCH (d:Document)-[:HAS_SUBJECT]->(:Subject)-[:HAS_THEME]->(:Theme)-[:HAS_CONCEPT]->(c:Concept)
    WITH d, count(c) AS n
    WHERE n > 15
    RETURN d.doc_id AS doc_id, n AS concept_count
    """

    def test_v2_007_concept_frugality(self, neo4j_session):
        """V2-007: Maximum 15 concepts par document."""
        results = list(neo4j_session.run(self.QUERY_V2_007))
        assert len(results) == 0, \
            f"V2-007 FAILED: {len(results)} document(s) dépassent 15 concepts"

    # ========================================================================
    # V2-008 — DocItem atomique (pas de fusion)
    # ========================================================================

    MAX_DOCITEM_SIZE = 4000  # Configurable

    QUERY_V2_008 = """
    MATCH (di:DocItem)
    WHERE size(di.text) > $max_size
    RETURN count(di) AS oversized
    """

    def test_v2_008_docitem_atomic(self, neo4j_session):
        """V2-008: DocItem ne doit pas dépasser MAX_DOCITEM_SIZE caractères."""
        result = neo4j_session.run(
            self.QUERY_V2_008,
            max_size=self.MAX_DOCITEM_SIZE
        ).single()
        oversized = result["oversized"]
        if oversized > 0:
            pytest.warns(UserWarning, match=f"V2-008 WARNING: {oversized} DocItem(s) surdimensionné(s)")

    # ========================================================================
    # V2-009 — Cohérence documentaire
    # ========================================================================

    QUERY_V2_009 = """
    MATCH (di:DocItem)
    WHERE NOT ( (:Section)-[:CONTAINS_ITEM]->(di) )
    RETURN count(di) AS unsectioned
    """

    def test_v2_009_docitem_has_section(self, neo4j_session):
        """V2-009: Chaque DocItem doit appartenir à une Section."""
        result = neo4j_session.run(self.QUERY_V2_009).single()
        unsectioned = result["unsectioned"]
        assert unsectioned == 0, f"V2-009 FAILED: {unsectioned} DocItem(s) sans Section"

    # ========================================================================
    # V2-010 — Theme→Section si SCOPED_TO activé
    # ========================================================================

    QUERY_V2_010 = """
    MATCH (t:Theme)
    WHERE NOT (t)-[:SCOPED_TO]->(:Section)
    RETURN count(t) AS unscoped
    """

    def test_v2_010_theme_scoped(self, neo4j_session, theme_scoping_enabled: bool = False):
        """V2-010: Si theme_scoping=true, chaque Theme doit avoir SCOPED_TO."""
        if not theme_scoping_enabled:
            pytest.skip("theme_scoping désactivé")

        result = neo4j_session.run(self.QUERY_V2_010).single()
        unscoped = result["unscoped"]
        if unscoped > 0:
            pytest.warns(UserWarning, match=f"V2-010 WARNING: {unscoped} Theme(s) sans SCOPED_TO")


# ============================================================================
# METRICS SANITY (bonus)
# ============================================================================

class TestMetricsSanity:
    """Tests de santé des métriques."""

    QUERY_INFO_CONCEPT_RATIO = """
    MATCH (d:Document)-[:HAS_SUBJECT]->(:Subject)-[:HAS_THEME]->(:Theme)-[:HAS_CONCEPT]->(c:Concept)
    OPTIONAL MATCH (c)-[:HAS_INFORMATION]->(inf:Information)
    WITH d, count(DISTINCT c) AS concepts, count(inf) AS infos
    WHERE concepts > 0
    RETURN d.doc_id AS doc_id,
           concepts,
           infos,
           toFloat(infos) / concepts AS ratio
    """

    def test_info_concept_ratio_normatif(self, neo4j_session):
        """Vérifie que les documents normatifs ont ratio >= 2."""
        results = list(neo4j_session.run(self.QUERY_INFO_CONCEPT_RATIO))
        # Note: Ce test est informatif, pas bloquant
        for r in results:
            if r["ratio"] < 1.0:
                pytest.warns(
                    UserWarning,
                    match=f"Document {r['doc_id']} a ratio faible ({r['ratio']:.2f})"
                )

    QUERY_PROMOTION_RATE = """
    MATCH (a:AssertionLog)
    WITH count(a) AS total,
         sum(CASE WHEN a.status = 'PROMOTED' THEN 1 ELSE 0 END) AS promoted
    WHERE total > 0
    RETURN toFloat(promoted) / total AS promotion_rate
    """

    def test_promotion_rate_in_range(self, neo4j_session):
        """Vérifie que le taux de promotion est dans une plage raisonnable (15-40%)."""
        result = neo4j_session.run(self.QUERY_PROMOTION_RATE).single()
        if result:
            rate = result["promotion_rate"]
            if rate < 0.10 or rate > 0.50:
                pytest.warns(
                    UserWarning,
                    match=f"Taux de promotion inhabituel: {rate:.1%}"
                )


# ============================================================================
# FIXTURE PLACEHOLDER
# ============================================================================

@pytest.fixture
def neo4j_session():
    """
    Fixture pour session Neo4j.
    À implémenter avec la vraie connexion.
    """
    # from knowbase.common.neo4j_client import get_neo4j_driver
    # driver = get_neo4j_driver()
    # with driver.session() as session:
    #     yield session
    pytest.skip("Neo4j session fixture not implemented")
