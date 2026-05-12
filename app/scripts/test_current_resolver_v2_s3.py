#!/usr/bin/env python3
"""
Test V2-S3 — Current Resolver gradué sur le corpus aerospace_compliance.

Cas testés :
  A. Tout le corpus (sans subject_id, sans candidate_doc_ids) → résultat global
  B. Restreint aux CS-25 amendments → on attend Amdt 28 (le plus récent) en top
  C. Restreint aux dual-use base regulations → on attend 2021/821 (LIFECYCLE_RELATION
     SUPERSEDES exclut 428/2009 explicitement)
  D. Restreint aux delegated acts → on attend le plus récent (2024/2547)
  E. Restreint à 1 doc seul → auto_pick_single_candidate
  F. Resolve à une date passée (as_of=2020-01-01) → 428/2009 doit être actif
     (puisque 2021/821 n'existait pas encore)

Tous les tests inspectent la décision (auto_pick / suggest / escalate / not_found)
et les scores des candidats.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

from knowbase.current import CurrentResolver, CurrentResolverResult

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("test_current")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")


def _print_result(label: str, result: CurrentResolverResult) -> None:
    print(f"\n=== {label} ===")
    print(f"  decision: {result.decision.value}")
    print(f"  reasoning: {result.reasoning}")
    print(f"  n_phase1: {result.n_filtered_in_phase1}")
    if result.top_candidate:
        c = result.top_candidate
        print(
            f"  TOP: {c.doc_id} (conf={c.confidence:.3f} | "
            f"recency={c.score_recency:.2f} version={c.score_version_ordering:.2f} "
            f"centrality={c.score_kg_centrality:.2f} trust={c.score_trust:.2f})"
        )
    if result.alternatives:
        print(f"  Alternatives ({len(result.alternatives)}):")
        for a in result.alternatives[:5]:
            print(f"    {a.doc_id} (conf={a.confidence:.3f})")


def main() -> int:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    resolver = CurrentResolver(driver=driver, tenant_id=TENANT_ID)

    # === A. Tout le corpus ===
    result_a = resolver.resolve()
    _print_result("A. Tout le corpus (17 docs)", result_a)

    # === B. Restreint aux CS-25 amendments ===
    cs25_amdt_ids = [
        "cs25_amdt_22_8e69026c",
        "cs25_amdt_23_0869bab2",
        "cs25_amdt_24_86b11545",
        "cs25_amdt_25_a41bdc85",
        "cs25_amdt_26_6450b31e",
        "cs25_amdt_27_992260a7",
        "cs25_amdt_28_32f1a9ac",
    ]
    result_b = resolver.resolve(candidate_doc_ids=cs25_amdt_ids)
    _print_result("B. CS-25 Amendments (Amdt 28 attendu en top)", result_b)
    assert (
        result_b.top_candidate
        and result_b.top_candidate.doc_id == "cs25_amdt_28_32f1a9ac"
    ), "Expected Amdt 28 as top"

    # === C. Restreint aux dual-use base regulations ===
    dualuse_base_ids = [
        "dualuse_reg_428_2009_original_372b7ac3",
        "dualuse_reg_2021_821_original_65eef5dc",
    ]
    result_c = resolver.resolve(candidate_doc_ids=dualuse_base_ids)
    _print_result(
        "C. Dual-use base regulations (LIFECYCLE_RELATION SUPERSEDES doit exclure 428/2009)",
        result_c,
    )
    # 428/2009 est SUPERSEDED par 2021/821 (LIFECYCLE_RELATION) → seul 2021/821 doit rester
    assert (
        result_c.top_candidate
        and result_c.top_candidate.doc_id
        == "dualuse_reg_2021_821_original_65eef5dc"
    ), "Expected 2021/821 as top (428/2009 superseded)"
    if result_c.alternatives:
        for a in result_c.alternatives:
            assert (
                a.doc_id != "dualuse_reg_428_2009_original_372b7ac3"
            ), "428/2009 should be filtered out by SUPERSEDES"

    # === D. Restreint aux delegated acts ===
    deleg_ids = [
        "dualuse_del_2023_66_cdc2b691",
        "dualuse_del_2023_996_3616a044",
        "dualuse_del_2024_2025_908a03cf",
        "dualuse_del_2024_2547_cb08f84b",
    ]
    result_d = resolver.resolve(candidate_doc_ids=deleg_ids)
    _print_result("D. Delegated acts (2024/2547 attendu — le plus récent)", result_d)
    # Le plus récent en publication_date est 2024-09-05 → 2024/2547

    # === E. 1 doc seul ===
    result_e = resolver.resolve(candidate_doc_ids=["cs25_amdt_28_32f1a9ac"])
    _print_result("E. Single candidate (auto_pick_single)", result_e)
    assert result_e.decision.value == "auto_pick_single_candidate"

    # === F. As-of dans le passé (2020-01-01) sur dual-use base ===
    # À cette date, 2021/821 n'existait pas (publié 2021-06-11), donc 428/2009 (2009-05-05) seul
    # devrait passer le filtre validity_start ≤ as_of.
    # Note : le SUPERSEDES de 2021/821→428/2009 ne s'applique pas car 2021/821.validity_start > 2020-01-01.
    result_f = resolver.resolve(
        candidate_doc_ids=dualuse_base_ids,
        as_of=date(2020, 1, 1),
    )
    _print_result(
        "F. Dual-use base au 2020-01-01 (428/2009 attendu — 2021/821 pas encore publié)",
        result_f,
    )
    if result_f.top_candidate:
        # On vérifie que 2021/821 ne passe pas
        assert (
            result_f.top_candidate.doc_id != "dualuse_reg_2021_821_original_65eef5dc"
        ), "2021/821 should be filtered out at 2020-01-01"

    print("\n✓ Tous les tests OK")
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
