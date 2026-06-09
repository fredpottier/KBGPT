"""Tests unitaires du module Execute — runtime_a3.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.3 + §4.

Stratégie :
    - Injecter un Neo4jClient mock + un qdrant_search mock + un embedder mock
    - Vérifier que les Cypher reçus contiennent les filtres bitemporels obligatoires
    - Vérifier coverage_signal selon priority + n_claims
    - Vérifier side-effect ConflictPending §2.6
    - Vérifier error handling
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from knowbase.runtime_a3.execute import (
    CYPHER_KG_CLAIMS,
    CYPHER_KG_CLAIMS_LIST,
    CYPHER_LIFECYCLE,
    CYPHER_CONTRADICTIONS,
    CYPHER_CONFLICT_PENDING,
    Executor,
    execute,
    _escape_lucene_query,
    _extract_query_identifiers,
)
from knowbase.runtime_a3.plan import plan
from knowbase.runtime_a3.schemas import (
    ClaimSummary,
    ExecuteOutput,
    ParseInput,
    ParseOutput,
    PlanOutput,
    SubGoal,
    ToolCall,
    ToolResult,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_parse_input(
    question: str = "test",
    tenant_id: str = "default",
    as_of_date: datetime | None = None,
) -> ParseInput:
    return ParseInput(question=question, tenant_id=tenant_id, as_of_date=as_of_date)


def _make_parse_output(
    sub_goals: List[SubGoal] | None = None,
    raw_question: str = "test",
) -> ParseOutput:
    return ParseOutput(
        sub_goals=sub_goals or [],
        entities=[],
        language="en",
        raw_question=raw_question,
        parse_confidence=0.9,
        parse_warnings=[],
        schema_version="a3.0",
    )


def _make_neo4j_mock(rows_by_query: Dict[str, List[Dict[str, Any]]] | None = None):
    """Crée un mock Neo4jClient qui retourne des rows distincts selon la query.

    rows_by_query: dict {SUBSTRING_QUERY: [rows]} — matché par substring.

    Pour les assertions, `mock.calls_by_query_substring` est un dict
    {substring: last_params}. `mock.last_call_params` reste pour rétro-compat
    mais capture LE DERNIER appel (peut être ConflictPending — utiliser
    `calls_by_query_substring` pour cibler un Cypher précis).
    """
    mock = MagicMock()
    mock.calls_by_query_substring = {}
    rows_by_query = rows_by_query or {}

    def execute_query(query: str, **params):
        for substring, rows in rows_by_query.items():
            if substring in query:
                mock.calls_by_query_substring[substring] = params
                mock.last_call_params = params
                mock.last_call_query = query
                return rows
        mock.last_call_params = params
        mock.last_call_query = query
        return []

    mock.execute_query.side_effect = execute_query
    return mock


def _claim_node(claim_id: str, **kwargs) -> Dict[str, Any]:
    base = {
        "claim_id": claim_id,
        "subject_canonical": kwargs.get("subject_canonical", "X"),
        "predicate": kwargs.get("predicate", "p"),
        "value": kwargs.get("value", "v"),
        "confidence": kwargs.get("confidence", 0.9),
        "valid_from": kwargs.get("valid_from"),
        "valid_until": kwargs.get("valid_until"),
        "invalidated_at": kwargs.get("invalidated_at"),
        "ingested_at": kwargs.get("ingested_at"),
        "marker_type": kwargs.get("marker_type", "explicit"),
    }
    return base


def _section_node(section_id: str, **kwargs) -> Dict[str, Any]:
    return {
        "section_id": section_id,
        "document_id": kwargs.get("document_id", "doc_001"),
        "heading": kwargs.get("heading", "Heading"),
        "text": kwargs.get("text", "some text"),
    }


# ============================================================================
# Cypher templates — filtre bitemporel obligatoire
# ============================================================================


class TestCypherBitemporal:
    def test_kg_claims_has_bitemporal_filter(self):
        assert "c.invalidated_at IS NULL" in CYPHER_KG_CLAIMS
        assert "c.valid_from IS NULL OR date(c.valid_from) <= date($as_of)" in CYPHER_KG_CLAIMS
        assert "c.valid_until IS NULL OR date(c.valid_until) >= date($as_of)" in CYPHER_KG_CLAIMS

    def test_kg_claims_list_has_bitemporal_filter(self):
        assert "c.invalidated_at IS NULL" in CYPHER_KG_CLAIMS_LIST
        assert "c.valid_from IS NULL OR date(c.valid_from) <= date($as_of)" in CYPHER_KG_CLAIMS_LIST

    def test_lifecycle_no_bitemporal_filter(self):
        """ADR §4.3 : lifecycle retourne TOUTES les versions (historique)."""
        assert "invalidated_at IS NULL" not in CYPHER_LIFECYCLE

    def test_contradictions_filters_invalidated(self):
        assert "a.invalidated_at IS NULL" in CYPHER_CONTRADICTIONS
        assert "b.invalidated_at IS NULL" in CYPHER_CONTRADICTIONS

    def test_conflict_pending_filters_unresolved(self):
        assert "resolution_status = 'unresolved'" in CYPHER_CONFLICT_PENDING

    def test_tenant_id_in_all_queries(self):
        for q in [CYPHER_KG_CLAIMS, CYPHER_KG_CLAIMS_LIST, CYPHER_LIFECYCLE,
                  CYPHER_CONTRADICTIONS, CYPHER_CONFLICT_PENDING]:
            assert "tenant_id: $tenant_id" in q


# ============================================================================
# kg_claims handler
# ============================================================================


class TestKgClaims:
    def test_kg_claims_returns_claims_and_sections(self):
        neo4j_mock = _make_neo4j_mock({
            "MATCH (c:Claim {tenant_id: $tenant_id})": [
                {
                    "c": _claim_node("clm_001", subject_canonical="entity_x"),
                    "sections": [_section_node("sec_001"), _section_node("sec_002")],
                },
                {
                    "c": _claim_node("clm_002", subject_canonical="entity_x"),
                    "sections": [_section_node("sec_001")],  # déduplication
                },
            ]
        })
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="entity_x")
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert len(result.results) == 1
        r0 = result.results[0]
        assert len(r0.claims) == 2
        assert r0.claims[0].claim_id == "clm_001"
        # Dédup sections
        assert len(r0.sections) == 2
        assert r0.error is None

    def test_kg_claims_params_passed_to_neo4j(self):
        neo4j_mock = _make_neo4j_mock({"MATCH (c:Claim": []})
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        fixed_as_of = datetime(2026, 5, 21, tzinfo=timezone.utc)
        pi = _make_parse_input(as_of_date=fixed_as_of)
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X", predicate_hint="p1")
        ])
        plan_out = plan(pi, po)
        execute(pi, po, plan_out, executor=ex)
        params = neo4j_mock.last_call_params
        assert params["subject"] == "X"
        assert params["predicate"] == "p1"
        assert params["tenant_id"] == "default"
        assert params["as_of"] == fixed_as_of.date().isoformat()


# ============================================================================
# kg_claims_list handler
# ============================================================================


class TestKgClaimsList:
    def test_list_returns_multiple_claims(self):
        rows = [
            {"c": _claim_node(f"clm_{i:03d}"), "sections": []}
            for i in range(10)
        ]
        neo4j_mock = _make_neo4j_mock({"ORDER BY coalesce(c.confidence": rows})
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="list_enumeration", subject_canonical="X", predicate_hint="contains")
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert len(result.results[0].claims) == 10


# ============================================================================
# lifecycle_query handler
# ============================================================================


class TestLifecycleQuery:
    def test_lifecycle_no_as_of_param(self):
        neo4j_mock = _make_neo4j_mock({"r:EVOLUTION_OF|SUPERSEDES": [
            {"c": _claim_node("clm_old"), "sections": [], "rels": []}
        ]})
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="lifecycle_trace", subject_canonical="X")
        ])
        plan_out = plan(pi, po)
        execute(pi, po, plan_out, executor=ex)
        # Cibler le call lifecycle (le dernier call peut être ConflictPending)
        params = neo4j_mock.calls_by_query_substring["r:EVOLUTION_OF|SUPERSEDES"]
        assert "as_of" not in params  # ADR §4.3
        assert params["subject"] == "X"
        assert params["tenant_id"] == "default"


# ============================================================================
# contradiction_surface handler
# ============================================================================


class TestContradictionSurface:
    def test_contradictions_dedupe_claims_and_extract_relations(self):
        rows = [
            {
                "a": _claim_node("clm_A", subject_canonical="X"),
                "b": _claim_node("clm_B", subject_canonical="Y"),
                "r": {"type": "CONTRADICTS", "confidence": 0.92},
                "sections_a": [_section_node("sec_a")],
                "sections_b": [_section_node("sec_b")],
            },
            # Doublon (même paire) — doit dédupliquer
            {
                "a": _claim_node("clm_A", subject_canonical="X"),
                "b": _claim_node("clm_B", subject_canonical="Y"),
                "r": {"type": "CONTRADICTS", "confidence": 0.92},
                "sections_a": [_section_node("sec_a")],
                "sections_b": [_section_node("sec_b")],
            },
        ]
        neo4j_mock = _make_neo4j_mock({"r:CONTRADICTS": rows})
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="contradiction_check", subject_canonical="X")
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        r0 = result.results[0]
        # 2 claims uniques (déduplication par claim_id)
        assert len(r0.claims) == 2
        assert {c.claim_id for c in r0.claims} == {"clm_A", "clm_B"}
        # Relations capturées
        assert len(r0.relations_traced) == 2  # un par row
        assert all(r.relation_type == "CONTRADICTS" for r in r0.relations_traced)


# ============================================================================
# Coverage signal
# ============================================================================


class TestCoverageSignal:
    @pytest.mark.parametrize("n_claims,priority,expected", [
        (0, 1, "empty"),
        (0, 2, "empty"),
        (1, 1, "partial"),
        (2, 1, "partial"),
        (3, 1, "full"),
        (10, 1, "full"),
        (1, 2, "full"),
        (5, 2, "full"),
    ])
    def test_compute_coverage_signal(self, n_claims, priority, expected):
        assert Executor._compute_coverage_signal(n_claims, priority) == expected

    def test_priority_1_with_2_claims_partial(self):
        rows = [
            {"c": _claim_node("c1"), "sections": []},
            {"c": _claim_node("c2"), "sections": []},
        ]
        neo4j_mock = _make_neo4j_mock({"MATCH (c:Claim": rows})
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X", priority=1)
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert result.results[0].coverage_signal == "partial"

    def test_priority_2_with_1_claim_full(self):
        rows = [{"c": _claim_node("c1"), "sections": []}]
        neo4j_mock = _make_neo4j_mock({"MATCH (c:Claim": rows})
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X", priority=2)
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert result.results[0].coverage_signal == "full"

    def test_empty_when_no_claims(self):
        neo4j_mock = _make_neo4j_mock({"MATCH (c:Claim": []})
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X", priority=1)
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert result.results[0].coverage_signal == "empty"


# ============================================================================
# ConflictPending side-effect (§2.6)
# ============================================================================


class TestConflictPendingSideEffect:
    def test_conflict_pending_attached_to_results(self):
        # 1er call: kg_claims retourne 2 claims
        # 2nd call: conflict_pending_surface retourne 1 CP touchant clm_001
        neo4j_mock = MagicMock()
        call_history = []

        def execute_query(query: str, **params):
            call_history.append((query, params))
            if "MATCH (c:Claim" in query and "ConflictPending" not in query:
                return [
                    {"c": _claim_node("clm_001"), "sections": []},
                    {"c": _claim_node("clm_002"), "sections": []},
                ]
            if "ConflictPending" in query:
                # Le 2ème claim_id passé doit être dans la liste
                returned_ids = params.get("returned_claim_ids", [])
                assert "clm_001" in returned_ids and "clm_002" in returned_ids
                return [{
                    "cp": {
                        "conflict_id": "cp_001",
                        "resolution_status": "unresolved",
                        "reason": "value_divergence",
                    },
                    "involved_claim_ids": ["clm_001", "clm_002"],
                }]
            return []

        neo4j_mock.execute_query.side_effect = execute_query
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X")
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        # Le ToolResult doit avoir 1 ConflictPending (dédupliqué)
        cps = result.results[0].conflict_pendings
        assert len(cps) == 1
        assert cps[0].conflict_id == "cp_001"
        assert "clm_001" in cps[0].involved_claim_ids

    def test_no_claims_no_conflict_pending_lookup(self):
        """Si aucun claim retourné, aucune query CP ne doit partir."""
        neo4j_mock = MagicMock()
        query_count = [0]

        def execute_query(query: str, **params):
            query_count[0] += 1
            if "ConflictPending" in query:
                pytest.fail("Should not query ConflictPending when no claims")
            return []

        neo4j_mock.execute_query.side_effect = execute_query
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X")
        ])
        plan_out = plan(pi, po)
        execute(pi, po, plan_out, executor=ex)
        # Une seule query partie (kg_claims), pas de CP
        assert query_count[0] == 1

    def test_conflict_pending_failure_non_fatal(self):
        """Si la query CP échoue, on continue (sans CP attachés)."""
        neo4j_mock = MagicMock()

        def execute_query(query: str, **params):
            if "ConflictPending" in query:
                raise Exception("Boom")
            return [{"c": _claim_node("clm_001"), "sections": []}]

        neo4j_mock.execute_query.side_effect = execute_query
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X")
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        # Claim retourné, mais pas de CP attaché (échec silencieux)
        assert len(result.results[0].claims) == 1
        assert result.results[0].conflict_pendings == []
        assert result.results[0].error is None  # Le tool principal a réussi


# ============================================================================
# Procedure chain side-effect (Phase B, P1.5)
# ============================================================================


class TestProcedureChainSideEffect:
    def _run(self, monkeypatch, claim_rows, proc_rows):
        from knowbase.runtime_a3.execute import CYPHER_PROCEDURE_CHAIN  # noqa: F401
        monkeypatch.setenv("V6_PROCEDURE_CHAIN", "1")
        neo4j_mock = MagicMock()

        def execute_query(query: str, **params):
            if "p:Procedure" in query:
                return proc_rows(params)
            if "MATCH (c:Claim" in query:
                return claim_rows
            return []

        neo4j_mock.execute_query.side_effect = execute_query
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False,
                      predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        plan_out = plan(pi, po)
        return execute(pi, po, plan_out, executor=ex)

    def test_procedure_chain_attached(self, monkeypatch):
        claim_rows = [
            {"c": _claim_node("clm_001", procedure_id="proc_a"), "sections": []},
            {"c": _claim_node("clm_002", procedure_id="proc_a"), "sections": []},
        ]

        def proc_rows(params):
            ids = params.get("returned_claim_ids", [])
            assert "clm_001" in ids
            return [{
                "p": {"name": "Enable SSO", "goal": "SSO active", "prerequisites": ["admin rights"]},
                "procedure_id": "proc_a",
                "steps": [
                    {"order": 2, "action": "Activate SAML trust"},
                    {"order": 1, "action": "Configure IdP"},
                    {"order": 3, "action": ""},  # filtré (action vide)
                ],
                "entry_claim_ids": ["clm_001", "clm_002"],
            }]

        result = self._run(monkeypatch, claim_rows, proc_rows)
        chains = result.results[0].procedure_chains
        assert len(chains) == 1
        pc = chains[0]
        assert pc.procedure_id == "proc_a"
        assert pc.name == "Enable SSO"
        # steps triés par order, action vide filtrée
        assert [s["action"] for s in pc.ordered_steps] == ["Configure IdP", "Activate SAML trust"]
        assert pc.prerequisites == ["admin rights"]

    def test_procedure_chain_toggle_off_by_default(self, monkeypatch):
        monkeypatch.delenv("V6_PROCEDURE_CHAIN", raising=False)
        neo4j_mock = MagicMock()
        queried = {"proc": False}

        def execute_query(query: str, **params):
            if "p:Procedure" in query:
                queried["proc"] = True
            if "MATCH (c:Claim" in query:
                return [{"c": _claim_node("clm_001", procedure_id="proc_a"), "sections": []}]
            return []

        neo4j_mock.execute_query.side_effect = execute_query
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False,
                      predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert queried["proc"] is False  # pas de lookup si toggle off
        assert result.results[0].procedure_chains == []

    def test_procedure_chain_failure_non_fatal(self, monkeypatch):
        monkeypatch.setenv("V6_PROCEDURE_CHAIN", "1")
        neo4j_mock = MagicMock()

        def execute_query(query: str, **params):
            if "p:Procedure" in query:
                raise Exception("Boom")
            if "MATCH (c:Claim" in query:
                return [{"c": _claim_node("clm_001", procedure_id="proc_a"), "sections": []}]
            return []

        neo4j_mock.execute_query.side_effect = execute_query
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False,
                      predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert result.results[0].procedure_chains == []
        assert result.results[0].error is None


# ============================================================================
# qdrant_sections (fallback)
# ============================================================================


class TestQdrantSections:
    def test_qdrant_search_called_with_correct_params(self):
        embedder_mock = MagicMock(return_value=[0.1, 0.2, 0.3])
        qdrant_mock = MagicMock(return_value=[
            {
                "id": "chunk_001",
                "score": 0.85,
                "payload": {
                    "section_id": "sec_001",
                    "document_id": "doc_001",
                    "text": "some chunk text " * 100,  # long text → truncated
                    "heading": "Heading 1",
                },
            },
            {
                "id": "chunk_002",
                "score": 0.72,
                "payload": {"section_id": "sec_002", "text": "short text"},
            },
        ])
        neo4j_mock = _make_neo4j_mock({})  # all empty → forces qdrant fallback
        ex = Executor(
            neo4j_client=neo4j_mock,
            qdrant_search=qdrant_mock,
            embedder=embedder_mock,
            subject_resolver_enabled=False,
            predicate_resolver_enabled=False,
        )
        pi = _make_parse_input(question="my question?")
        # All sub_goals unmappable → fallback Qdrant
        po = _make_parse_output(
            sub_goals=[SubGoal(kind="fact_lookup", subject_canonical=None)],
            raw_question="my question?",
        )
        plan_out = plan(pi, po)
        # Vérifie que Plan a bien injecté qdrant_sections
        assert any(tc.tool == "qdrant_sections" for tc in plan_out.tool_calls)
        result = execute(pi, po, plan_out, executor=ex)
        assert len(result.results) == 1
        r0 = result.results[0]
        assert r0.tool == "qdrant_sections"
        assert len(r0.sections) == 2
        # Truncation
        assert r0.sections[0].text_excerpt is not None
        assert len(r0.sections[0].text_excerpt) <= 503  # 500 + "..."
        # Embedder appelé avec la question
        embedder_mock.assert_called_once_with("my question?")
        # Qdrant appelé avec le bon tenant
        qdrant_mock.assert_called_once()
        kwargs = qdrant_mock.call_args.kwargs
        assert kwargs["tenant_id"] == "default"
        assert kwargs["query_vector"] == [0.1, 0.2, 0.3]


# ============================================================================
# Error handling
# ============================================================================


class TestErrorHandling:
    def test_neo4j_exception_captured_in_tool_result(self):
        neo4j_mock = MagicMock()
        neo4j_mock.execute_query.side_effect = Exception("Connection lost")
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X")
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        r0 = result.results[0]
        assert r0.error is not None
        assert "Connection lost" in r0.error
        assert r0.coverage_signal == "empty"
        assert r0.claims == []

    def test_multiple_tools_one_fails(self):
        """Une tool en échec ne casse pas les autres."""
        call_count = [0]

        def execute_query(query: str, **params):
            call_count[0] += 1
            # 1er appel kg_claims pour sub_goal_idx=0 → réussit
            # 2ème appel kg_claims pour sub_goal_idx=1 → échoue
            if call_count[0] == 1:
                return [{"c": _claim_node("clm_a"), "sections": []}]
            raise Exception("Tool 2 fail")

        neo4j_mock = MagicMock()
        neo4j_mock.execute_query.side_effect = execute_query
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="A"),
            SubGoal(kind="fact_lookup", subject_canonical="B"),
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert len(result.results) == 2
        assert result.results[0].error is None
        assert len(result.results[0].claims) == 1
        assert result.results[1].error is not None


# ============================================================================
# Determinism + timing
# ============================================================================


class TestExecuteOutput:
    def test_total_duration_measured(self):
        neo4j_mock = _make_neo4j_mock({"MATCH (c:Claim": []})
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X")
        ])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert result.total_duration_s >= 0.0
        assert result.results[0].duration_s >= 0.0

    def test_schema_version(self):
        neo4j_mock = _make_neo4j_mock({"MATCH (c:Claim": []})
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[
            SubGoal(kind="fact_lookup", subject_canonical="X")
        ])
        result = execute(pi, po, plan(pi, po), executor=ex)
        assert result.schema_version == "a3.0"


# ============================================================================
# Empty plan (no sub_goals)
# ============================================================================


class TestEmptyPlan:
    def test_no_subgoals_returns_empty_results(self):
        neo4j_mock = MagicMock()
        ex = Executor(neo4j_client=neo4j_mock, subject_resolver_enabled=False, predicate_resolver_enabled=False)
        pi = _make_parse_input()
        po = _make_parse_output(sub_goals=[])
        plan_out = plan(pi, po)
        result = execute(pi, po, plan_out, executor=ex)
        assert result.results == []
        # Pas de query partie
        neo4j_mock.execute_query.assert_not_called()


# ============================================================================
# Domain-agnostic charter
# ============================================================================


class TestDomainAgnostic:
    def test_execute_module_no_corpus_tokens(self):
        from pathlib import Path
        import inspect
        from knowbase.runtime_a3 import execute as execute_module

        src = Path(inspect.getfile(execute_module)).read_text(encoding="utf-8").lower()
        forbidden = ["sap ", "s/4hana", "s4hana", "rise ", "fiori", "hana ",
                     "aerospace", "ehs", "etops",
                     "icd-10", "icd10", "fda ",
                     "gdpr", "eu 2021"]
        for token in forbidden:
            assert token not in src, f"Corpus-specific token '{token}' found in execute.py"


# ============================================================================
# #435 / #436 — préservation des identifiants pour BM25 (escaping + extraction)
# ============================================================================


def test_extract_query_identifiers_keeps_codes_drops_common_words():
    ids = _extract_query_identifiers(
        "Quelle valeur HIC impose AC 25.562-1C pour le test 16g et ETSO-C127c ?")
    low = {i.lower() for i in ids}
    assert "25.562-1c" in low          # code avec point/tiret
    assert "16g" in low                # valeur+unité
    assert "etso-c127c" in low         # ref normative
    assert "hic" in low                # all-caps ≥3
    assert "ac" not in low             # all-caps <3 → ignoré
    assert "quelle" not in low and "test" not in low  # mots banals ignorés


def test_escape_lucene_query_neutralizes_special_chars():
    esc = _escape_lucene_query("ref 25.853(b) and /SAPAPO/OM03 (2021/821)")
    # parenthèses et slashes — qui cassent le parser Lucene — sont échappés
    assert r"\(" in esc and r"\)" in esc
    assert r"\/" in esc
    # le contenu littéral reste présent (juste précédé de backslash)
    assert "25.853" in esc and "SAPAPO" in esc and "2021" in esc


def test_ensure_question_identifiers_restores_lost_ids():
    # query reconstruite (aspect-emphasis) ayant perdu le code de la question
    restored = Executor._ensure_question_identifiers(
        "head injury criterion threshold", "What HIC does AC 25.562-1C set?")
    assert "25.562-1C" in restored      # identifiant ré-injecté
    # no-op si déjà présent
    same = Executor._ensure_question_identifiers(
        "limit for 25.562-1C", "value of 25.562-1C")
    assert same.count("25.562-1C") == 1


def test_ensure_question_identifiers_flag_off(monkeypatch):
    monkeypatch.setenv("V6_QUERY_PRESERVE_IDS", "0")
    q = Executor._ensure_question_identifiers("rebuilt query", "about 25.562-1C")
    assert q == "rebuilt query"         # flag off → inchangé
