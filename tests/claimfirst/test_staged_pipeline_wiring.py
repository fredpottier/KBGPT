"""
Test d'intégration P1.4b — câblage Stage A -> Stage B dans ClaimExtractor.

Stages mockés (pas de LLM/burst) : on vérifie que _extract_claims_staged_async enchaîne
sélection -> décomposition -> mapping, et que _claim_from_candidate produit un Claim avec
VERBATIM reconstruit depuis l'unité source (réutilise _build_claim).
"""

import asyncio
import types

import pytest

from knowbase.claimfirst.extractors.claim_extractor import ClaimExtractor, BatchTask
from knowbase.claimfirst.extractors.decomposition_stage import (
    ClaimCandidate,
    DecompositionResult,
)
from knowbase.claimfirst.extractors.selection_gate import SelectionResult
from knowbase.stratified.pass1.assertion_unit_indexer import AssertionUnitIndexer


def _make_task():
    text = "SAP HANA supports in-memory processing for analytics workloads."
    idx = AssertionUnitIndexer(min_unit_length=5)  # flag OFF -> pas de spaCy
    unit_result = idx.index_docitem("doc1:p1", text, item_type="paragraph")
    assert unit_result.units, "le test exige au moins une unité"
    passage = types.SimpleNamespace(passage_id="doc1:p1", text=text)
    task = BatchTask(
        batch_id=0, units=unit_result.units, passage=passage, unit_result=unit_result,
        tenant_id="default", doc_id="doc1", doc_title="T", doc_type="technical",
    )
    return task, unit_result.units[0].unit_local_id


def test_staged_wiring_produces_claim_with_verbatim():
    ext = ClaimExtractor(llm_client=None, use_staged_pipeline=True)
    task, first_uid = _make_task()

    # Stage A mock : garder toutes les unités
    async def fake_aclassify(unit_pairs):
        return SelectionResult(kept_ids=[uid for uid, _ in unit_pairs])

    # Stage B mock : 1 claim ancré sur la 1re unité
    async def fake_adecompose(kept, passage_context=""):
        return DecompositionResult(claims=[ClaimCandidate(
            subject="SAP HANA", predicate="supports",
            objects=["in-memory processing"],
            modality="assertive", polarity="affirmative",
            self_contained_text="SAP HANA supports in-memory processing for analytics workloads.",
            source_unit_ids=[first_uid],
        )])

    ext._selection_gate.aclassify = fake_aclassify
    ext._decomposition_stage.adecompose = fake_adecompose

    claims = asyncio.run(ext._extract_claims_staged_async(task))
    assert claims is not None and len(claims) == 1
    c = claims[0]
    assert "in-memory" in c.text
    # verbatim GARANTI reconstruit depuis l'unité source (≠ texte décontextualisé inventé)
    assert c.verbatim_quote and c.verbatim_quote in task.passage.text
    assert c.doc_id == "doc1"


def test_staged_wiring_drops_via_selection():
    ext = ClaimExtractor(llm_client=None, use_staged_pipeline=True)
    task, _ = _make_task()

    async def drop_all(unit_pairs):
        return SelectionResult(kept_ids=[])  # tout jeté par Stage A

    called = {"decomp": False}

    async def should_not_run(kept, passage_context=""):
        called["decomp"] = True
        return DecompositionResult()

    ext._selection_gate.aclassify = drop_all
    ext._decomposition_stage.adecompose = should_not_run

    claims = asyncio.run(ext._extract_claims_staged_async(task))
    assert claims == []
    assert called["decomp"] is False  # Stage B non appelé si rien n'est gardé


def test_staged_wiring_fallback_on_stage_b_failure():
    ext = ClaimExtractor(llm_client=None, use_staged_pipeline=True)
    task, _ = _make_task()

    async def keep_all(unit_pairs):
        return SelectionResult(kept_ids=[uid for uid, _ in unit_pairs])

    async def fail(kept, passage_context=""):
        return DecompositionResult(judge_failed=True)  # échec technique

    ext._selection_gate.aclassify = keep_all
    ext._decomposition_stage.adecompose = fail

    # None => l'appelant retombe sur le chemin legacy (méga-prompt)
    claims = asyncio.run(ext._extract_claims_staged_async(task))
    assert claims is None


def test_flag_off_no_stages_instantiated():
    ext = ClaimExtractor(llm_client=None, use_staged_pipeline=False)
    assert ext.use_staged_pipeline is False
    assert ext._selection_gate is None
    assert ext._decomposition_stage is None
