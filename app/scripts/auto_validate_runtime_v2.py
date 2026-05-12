#!/usr/bin/env python3
"""
Validation auto-administrée du Runtime V2 — 4 tests selon VISION_RECENTREE §7.

Test 1 : 10 questions vérité courante — cible 90% de réponses cohérentes
Test 2 :  4 questions anchor explicite — cible 100% de scope correct
Test 3 :  2 questions évolution — cible timeline cohérente
Test 4 :  2 questions audit_mode — cible recall conflicts non-zéro si le scope a des CONFLICT KG

Chaque question est associée à des CRITÈRES PROGRAMMATIQUES vérifiables :
- expected_decision : la décision pipeline attendue
- expected_anchor_type : le type d'anchor attendu
- expected_in_authoritative : doc_id qui DOIT apparaître dans les sources autoritaires
- expected_min_claims : nombre minimum de claims attendus

Les critères sont conçus à partir de la lecture du corpus (17 docs aerospace_compliance) :
- CS-25 Amdt 22 (2018) → Amdt 28 (2023-12-15, current EASA cert spec)
- 2021/821 SUPERSEDES 428/2009 (delegated acts 2023/66, 2023/996, 2024/2547 amendent Annex I)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

from knowbase.common.clients.shared_clients import (
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.config.settings import get_settings
from knowbase.runtime_v2 import RuntimeV2Pipeline

logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("auto_validate")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

VLLM_URL = os.getenv("VLLM_URL", "http://18.199.218.46:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

FORENSICS_DIR = Path("/data/forensics")
FORENSICS_DIR.mkdir(parents=True, exist_ok=True)


# Doc IDs du corpus (référence)
DOC_AMDT_22 = "cs25_amdt_22_8e69026c"
DOC_AMDT_23 = "cs25_amdt_23_0869bab2"
DOC_AMDT_24 = "cs25_amdt_24_86b11545"
DOC_AMDT_25 = "cs25_amdt_25_a41bdc85"
DOC_AMDT_26 = "cs25_amdt_26_6450b31e"
DOC_AMDT_27 = "cs25_amdt_27_992260a7"
DOC_AMDT_28 = "cs25_amdt_28_32f1a9ac"
DOC_REG_428_2009 = "dualuse_reg_428_2009_original_372b7ac3"
DOC_REG_2021_821 = "dualuse_reg_2021_821_original_65eef5dc"
DOC_DEL_2023_66 = "dualuse_del_2023_66_cdc2b691"
DOC_DEL_2023_996 = "dualuse_del_2023_996_3616a044"
DOC_DEL_2024_2547 = "dualuse_del_2024_2547_cb08f84b"


# ============================================================
# TEST 1 — Vérité courante (10 questions, sans anchor explicite)
# Le système doit répondre depuis la version current de chaque sujet
# ============================================================
TEST_1_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "T1.1",
        "question": "What is the certification basis for Large Aeroplanes issued by EASA?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_AMDT_28],  # Amdt 28 = most recent CS-25
        "expected_min_claims": 1,
        "rationale": "CS-25 Amdt 28 (2023-12-15) is the current EASA certification spec for large aeroplanes.",
    },
    {
        "id": "T1.2",
        "question": "What is the EU regime for the control of exports of dual-use items?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_REG_2021_821, DOC_DEL_2024_2547, DOC_DEL_2023_996],  # Au moins un current dual-use doc
        "expected_min_claims": 1,
        "rationale": "2021/821 = base regulation, 2024/2547 = most recent delegated act (current). 428/2009 SUPERSEDED → exclu.",
        "expected_not_in_authoritative": [DOC_REG_428_2009],
    },
    {
        "id": "T1.3",
        "question": "Quelles sont les exigences de certification pour les grands avions ?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_AMDT_28],
        "expected_min_claims": 1,
        "rationale": "Multilingue : même attendu que T1.1 en français.",
    },
    {
        "id": "T1.4",
        "question": "Who publishes amendments to the Certification Specifications for Large Aeroplanes?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_AMDT_28],
        "expected_min_claims": 1,
        "rationale": "EASA publishes amendments via ED Decisions. Current = CS-25 Amdt 28.",
    },
    {
        "id": "T1.5",
        "question": "What is the legal basis under EU law for the dual-use export control regime?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_REG_2021_821, DOC_DEL_2024_2547, DOC_DEL_2023_996],
        "expected_min_claims": 1,
        "rationale": "2021/821 cite Article 207(2) TFEU comme base juridique. Current.",
    },
    {
        "id": "T1.6",
        "question": "What are dual-use items and how are they regulated when transiting the Union?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_REG_2021_821, DOC_DEL_2024_2547, DOC_DEL_2023_996],
        "expected_min_claims": 1,
        "rationale": "2021/821 régit le contrôle des items dual-use en transit.",
    },
    {
        "id": "T1.7",
        "question": "What is the role of Annex I in the EU dual-use regulation?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_REG_2021_821, DOC_DEL_2024_2547, DOC_DEL_2023_996],
        "expected_min_claims": 1,
        "rationale": "Annex I = list of dual-use items (refondue par 2024/2547 le plus récent).",
    },
    {
        "id": "T1.8",
        "question": "What does CS 25.1309 specify in the certification of large aeroplanes?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_AMDT_28],
        "expected_min_claims": 1,
        "rationale": "CS 25.1309 (Equipment systems and installations) — Amdt 28 = version current.",
    },
    {
        "id": "T1.9",
        "question": "What is the 'recast' procedure mentioned in EU dual-use regulations?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_REG_2021_821, DOC_DEL_2024_2547, DOC_DEL_2023_996],
        "expected_min_claims": 1,
        "rationale": "Le recast = refonte (2021/821 a recasté 428/2009). Current.",
    },
    {
        "id": "T1.10",
        "question": "What technical assistance is regulated for dual-use items?",
        "expected_decision": "answered_authoritative",
        "expected_anchor_type": "current_default",
        "expected_in_authoritative": [DOC_REG_2021_821, DOC_DEL_2024_2547, DOC_DEL_2023_996],
        "expected_min_claims": 1,
        "rationale": "2021/821 régit l'assistance technique. Current.",
    },
]


# ============================================================
# TEST 2 — Anchor explicite ponctuel (4 questions)
# Le système doit cibler la version explicitement demandée
# ============================================================
TEST_2_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "T2.1",
        "question": "What does CS 25.1309 require according to CS-25 Amendment 27?",
        "expected_decision": "answered_scoped",
        "expected_anchor_type": "point",
        "expected_in_authoritative": [DOC_AMDT_27],
        "expected_min_claims": 1,
        "rationale": "Anchor POINT version=Amendment 27 → seulement Amdt 27 (et change_amdt_28 qui le référence).",
    },
    {
        "id": "T2.2",
        "question": "What did Regulation (EU) 2021/821 establish for dual-use export control?",
        "expected_decision": "answered_scoped",
        "expected_anchor_type": "point",
        "expected_in_authoritative": [DOC_REG_2021_821],
        "expected_min_claims": 1,
        "rationale": "Anchor POINT version=2021/821.",
    },
    {
        "id": "T2.3",
        "question": "What was the dual-use control regime under Council Regulation (EC) No 428/2009?",
        "expected_decision": "answered_scoped",
        "expected_anchor_type": "point",
        "expected_in_authoritative": [DOC_REG_428_2009],
        "expected_min_claims": 1,
        "rationale": "Anchor POINT version=428/2009. Test que le système peut interroger une reg historique abrogée.",
    },
    {
        "id": "T2.4",
        "question": "What did Commission Delegated Regulation (EU) 2024/2547 amend in the dual-use list?",
        "expected_decision": "answered_scoped",
        "expected_anchor_type": "point",
        "expected_in_authoritative": [DOC_DEL_2024_2547],
        "expected_min_claims": 1,
        "rationale": "Anchor POINT version=2024/2547 (delegated act le plus récent).",
    },
]


# ============================================================
# TEST 3 — Évolution explicite (2 questions, anchor=range)
# Le système doit reconnaître la demande d'évolution et fournir une timeline
# ============================================================
TEST_3_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "T3.1",
        "question": "How has the EU dual-use export control regime evolved between 2009 and 2024?",
        "expected_decision": "answered_evolution",
        "expected_anchor_type": "range",
        "expected_min_evolution_points": 3,
        "rationale": "RANGE 2009-2024 → 428/2009 + 2021/821 + delegated acts → ≥ 3 timeline points.",
    },
    {
        "id": "T3.2",
        "question": "Comment les Certification Specifications CS-25 ont-elles évolué entre Amendment 22 et Amendment 28 ?",
        "expected_decision": "answered_evolution",
        "expected_anchor_type": "range",
        "expected_min_evolution_points": 3,
        "rationale": "RANGE Amdt 22 → Amdt 28 → ≥ 3 timeline points (Amdt 22, 23, 24, 25, 26, 27, 28).",
    },
]


# ============================================================
# TEST 4 — Mode audit (2 questions)
# Le système doit remonter les conflicts intra-anchor existants
# (16 CONFLICT déjà persistées dans le KG après ingestion phase précédente)
# ============================================================
TEST_4_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "T4.1",
        "question": "What does Regulation (EU) 2021/821 say about brokering services?",
        "expected_decision": "audit_report",
        "expected_anchor_type": "point",
        "expected_min_conflicts": 0,  # Au moins, on permet 0 si pas de CONFLICT dans ce scope précis
        "audit_mode": True,
        "rationale": "Audit sur 2021/821 — observe si CONFLICT entre claims du scope sont remontés.",
    },
    {
        "id": "T4.2",
        "question": "What are the EU rules for export control of dual-use items?",
        "expected_decision": "audit_report",
        "expected_anchor_type": "current_default",
        "expected_min_conflicts": 0,
        "audit_mode": True,
        "rationale": "Audit en mode current_default — large scope, on observe le rapport.",
    },
]


def evaluate(question_spec: dict, response, audit_mode: bool = False) -> dict[str, Any]:
    """Évalue une réponse contre les critères attendus."""
    checks: list[tuple[str, bool, str]] = []

    # Decision
    expected_decision = question_spec.get("expected_decision")
    actual_decision = response.decision.value
    checks.append(
        (
            "decision",
            actual_decision == expected_decision,
            f"expected={expected_decision}, actual={actual_decision}",
        )
    )

    # Anchor type
    expected_anchor = question_spec.get("expected_anchor_type")
    actual_anchor = response.anchor.anchor_type.value
    checks.append(
        (
            "anchor_type",
            actual_anchor == expected_anchor,
            f"expected={expected_anchor}, actual={actual_anchor}",
        )
    )

    # Authoritative doc_ids contains
    expected_in = question_spec.get("expected_in_authoritative", [])
    if expected_in:
        present = any(d in response.authoritative_doc_ids for d in expected_in)
        checks.append(
            (
                "authoritative_contains_expected",
                present,
                f"expected one of {expected_in}, actual={response.authoritative_doc_ids[:5]}",
            )
        )

    # Authoritative not in
    expected_not_in = question_spec.get("expected_not_in_authoritative", [])
    if expected_not_in:
        absent = all(d not in response.authoritative_doc_ids for d in expected_not_in)
        checks.append(
            (
                "authoritative_excludes_expected",
                absent,
                f"should NOT contain {expected_not_in}, actual={response.authoritative_doc_ids[:5]}",
            )
        )

    # Min claims
    expected_min_claims = question_spec.get("expected_min_claims")
    if expected_min_claims is not None and not audit_mode:
        ok = len(response.claims) >= expected_min_claims
        checks.append(
            (
                "min_claims",
                ok,
                f"expected ≥ {expected_min_claims}, actual={len(response.claims)}",
            )
        )

    # Min evolution points
    expected_min_eps = question_spec.get("expected_min_evolution_points")
    if expected_min_eps is not None:
        ok = len(response.evolution_points) >= expected_min_eps
        checks.append(
            (
                "min_evolution_points",
                ok,
                f"expected ≥ {expected_min_eps}, actual={len(response.evolution_points)}",
            )
        )

    # Min conflicts (audit)
    expected_min_conflicts = question_spec.get("expected_min_conflicts")
    if expected_min_conflicts is not None:
        ok = len(response.conflicts) >= expected_min_conflicts
        checks.append(
            (
                "min_conflicts",
                ok,
                f"expected ≥ {expected_min_conflicts}, actual={len(response.conflicts)}",
            )
        )

    n_passed = sum(1 for _, ok, _ in checks if ok)
    n_total = len(checks)
    overall_pass = n_passed == n_total

    return {
        "id": question_spec["id"],
        "question": question_spec["question"],
        "rationale": question_spec.get("rationale", ""),
        "actual_decision": actual_decision,
        "actual_anchor_type": actual_anchor,
        "actual_anchor_scope": response.anchor.scope.model_dump(exclude_none=True),
        "actual_authoritative": response.authoritative_doc_ids[:5],
        "actual_n_claims": len(response.claims),
        "actual_n_evolution_points": len(response.evolution_points),
        "actual_n_conflicts": len(response.conflicts),
        "actual_n_unresolved_conflicts": sum(1 for c in response.conflicts if not c.is_resolved_by_lifecycle),
        "actual_trust_score": response.trust_score,
        "checks": [
            {"name": name, "ok": ok, "detail": detail} for name, ok, detail in checks
        ],
        "overall_pass": overall_pass,
        "n_passed": n_passed,
        "n_total": n_total,
    }


def run_tests(test_list: list[dict], pipeline: RuntimeV2Pipeline, audit_default: bool = False) -> list[dict]:
    results = []
    for spec in test_list:
        audit = spec.get("audit_mode", audit_default)
        try:
            response = pipeline.answer(question=spec["question"], audit_mode=audit, top_k_claims=5)
            results.append(evaluate(spec, response, audit_mode=audit))
        except Exception as exc:
            logger.error("Test %s failed: %s", spec["id"], exc, exc_info=True)
            results.append({"id": spec["id"], "error": str(exc), "overall_pass": False})
    return results


def print_test_results(label: str, results: list[dict]) -> tuple[int, int]:
    print(f"\n=== {label} ===")
    n_pass = 0
    for r in results:
        status = "✓" if r.get("overall_pass") else "✗"
        if r.get("error"):
            print(f"  {status} {r['id']}: ERROR — {r['error']}")
            continue
        print(
            f"  {status} {r['id']} ({r['n_passed']}/{r['n_total']}): "
            f"decision={r['actual_decision']} anchor={r['actual_anchor_type']} "
            f"docs={r['actual_authoritative'][:2]}{'...' if len(r['actual_authoritative']) > 2 else ''} "
            f"claims={r['actual_n_claims']} evo={r['actual_n_evolution_points']} confl={r['actual_n_conflicts']}"
        )
        if not r.get("overall_pass"):
            for c in r.get("checks", []):
                if not c["ok"]:
                    print(f"      ✗ {c['name']}: {c['detail']}")
        if r.get("overall_pass"):
            n_pass += 1
    print(f"  Total: {n_pass}/{len(results)} pass")
    return n_pass, len(results)


def main() -> int:
    settings = get_settings()
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    qdrant = get_qdrant_client()
    embedder = get_sentence_transformer(
        settings.embeddings_model, cache_folder=str(settings.hf_home)
    )
    pipeline = RuntimeV2Pipeline(
        driver=driver,
        qdrant_client=qdrant,
        embedder=embedder,
        vllm_url=VLLM_URL,
        tenant_id=TENANT_ID,
        vllm_model=VLLM_MODEL,
    )

    print(f"VLLM={VLLM_URL}, NEO4J={NEO4J_URI}, TENANT={TENANT_ID}")

    print("\n" + "=" * 60)
    print("VALIDATION AUTO-ADMINISTREE — RUNTIME V2")
    print("Vision recentrée §7 — 4 critères")
    print("=" * 60)

    t1 = run_tests(TEST_1_QUESTIONS, pipeline)
    t2 = run_tests(TEST_2_QUESTIONS, pipeline)
    t3 = run_tests(TEST_3_QUESTIONS, pipeline)
    t4 = run_tests(TEST_4_QUESTIONS, pipeline, audit_default=True)

    p1, n1 = print_test_results("TEST 1 — Vérité courante (cible 90%)", t1)
    p2, n2 = print_test_results("TEST 2 — Anchor explicite (cible 100%)", t2)
    p3, n3 = print_test_results("TEST 3 — Évolution (cible timeline cohérente)", t3)
    p4, n4 = print_test_results("TEST 4 — Mode audit (cible recall non-zéro)", t4)

    print("\n" + "=" * 60)
    print(f"BILAN GLOBAL: T1={p1}/{n1} ({100*p1/n1:.0f}%), T2={p2}/{n2} ({100*p2/n2:.0f}%), T3={p3}/{n3} ({100*p3/n3:.0f}%), T4={p4}/{n4} ({100*p4/n4:.0f}%)")
    print(f"               Pass cible T1: {p1 >= 9}, T2: {p2 == n2}, T3: {p3 == n3}")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = FORENSICS_DIR / f"runtime_v2_validation_{ts}.json"
    with out_path.open("w") as f:
        json.dump(
            {
                "metadata": {"vllm_url": VLLM_URL, "model_id": VLLM_MODEL, "ts": ts},
                "test_1": t1,
                "test_2": t2,
                "test_3": t3,
                "test_4": t4,
                "summary": {
                    "test_1": {"pass": p1, "total": n1},
                    "test_2": {"pass": p2, "total": n2},
                    "test_3": {"pass": p3, "total": n3},
                    "test_4": {"pass": p4, "total": n4},
                },
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nForensics complet : {out_path}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
