"""Build A3.8 gold-sets : 50q SAP stratifiées + 30q ConflictPending.

Cf ADR_PARSE_EVALUATE_RUNTIME §7.1 (gates GA3-5/6/9) + §7.3 (protocole).

Génère 2 fichiers JSON :
    benchmark/questions/gold_set_a38_50q.json — sous-échantillon stratifié SAP
    benchmark/questions/gold_set_a38_30q_cp.json — questions ciblant les ConflictPending réels

Distribution viée 50q (cf ADR §7.3, distribution adaptée au gold-set dispo) :
    factual          15 (V2: 50 dispo)
    comparison       10 (V2: 28)
    multi_hop        10 (V2: 23 → proxy contradiction/lifecycle)
    contextual        5 (V2: 9)
    false_premise     5 (V2: 6 → unanswerable/edge)
    lifecycle         3 (V2: 3, max dispo)
    unanswerable      2 (V2: 3)
    Total: 50

Pour les 30q CP : pour chaque :ConflictPending unresolved (jusqu'à 30), construit
1 question domain-agnostic ciblant le subject + predicate. Format universel
("What does the corpus say about X's Y ?") sans biais SAP.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("build_a38_gold_sets")


STRATIFIED_QUOTAS = {
    "factual": 15,
    "comparison": 10,
    "multi_hop": 10,
    "contextual": 5,
    "false_premise": 5,
    "lifecycle": 3,
    "unanswerable": 2,
}


def build_50q_stratified(source_path: Path, output_path: Path, seed: int = 42):
    """Sub-sample stratifié de gold_set_sap_v2 (143q → 50q)."""
    with open(source_path, "r", encoding="utf-8") as f:
        all_qs = json.load(f)

    by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for q in all_qs:
        by_type[q.get("primary_type", "unknown")].append(q)

    logger.info("Source: %d questions across %d types", len(all_qs), len(by_type))
    rng = random.Random(seed)
    sampled: List[Dict[str, Any]] = []

    for cat, quota in STRATIFIED_QUOTAS.items():
        pool = by_type.get(cat, [])
        if not pool:
            logger.warning("Category '%s' has 0 questions in source — skip", cat)
            continue
        n = min(quota, len(pool))
        if n < quota:
            logger.warning(
                "Category '%s' has only %d (quota %d) — taking all",
                cat, n, quota,
            )
        chosen = rng.sample(pool, n)
        sampled.extend(chosen)
        logger.info("  %s: %d/%d sampled (pool=%d)", cat, n, quota, len(pool))

    # Si on n'a pas atteint 50, compléter avec d'autres types
    if len(sampled) < 50:
        deficit = 50 - len(sampled)
        used_ids = {q["id"] for q in sampled}
        remaining_pool: List[Dict[str, Any]] = []
        for cat, pool in by_type.items():
            if cat in STRATIFIED_QUOTAS:
                continue
            remaining_pool.extend([q for q in pool if q["id"] not in used_ids])
        if remaining_pool:
            extras = rng.sample(remaining_pool, min(deficit, len(remaining_pool)))
            sampled.extend(extras)
            logger.info("  filler (other types): %d added", len(extras))

    logger.info("Final 50q sample: %d questions", len(sampled))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sampled, f, ensure_ascii=False, indent=2)
    logger.info("Written: %s", output_path)


def build_30q_cp(output_path: Path, tenant_id: str = "default", limit: int = 30):
    """Build 30 questions ciblant les :ConflictPending unresolved du KG live.

    Stratégie : prend les CP où AU MOINS UN claim a subject_canonical (anchor
    pour la question). Les autres claims involved peuvent être moins structurés —
    ils sont quand même listés comme involved_claims pour la ground_truth.
    """
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    client = get_neo4j_client()
    rows = client.execute_query(
        """
        MATCH (cp:ConflictPending {tenant_id: $tid, resolution_status: 'unresolved'})
        MATCH (cp)-[:INVOLVES]->(claim:Claim)
        WITH cp, collect({
            claim_id: claim.claim_id,
            subject: claim.subject_canonical,
            predicate: claim.predicate,
            value: claim.object_canonical,
            text: claim.text
        }) AS involved
        // Au moins 2 claims involved ET au moins 1 avec subject_canonical (anchor)
        WHERE size(involved) >= 2
          AND any(c IN involved WHERE c.subject IS NOT NULL)
        RETURN cp.conflict_id AS cp_id, cp.reason AS reason, involved
        LIMIT $limit
        """,
        tid=tenant_id,
        limit=limit,
    )

    questions: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        involved = row["involved"]
        # Anchor = premier claim avec subject_canonical
        anchor = next((c for c in involved if c.get("subject")), None)
        if anchor is None:
            continue
        subject = anchor["subject"]
        predicate = anchor.get("predicate") or "any property"
        # Question domain-agnostic
        question = (
            f"What does the corpus say about the relation '{predicate}' "
            f"for subject '{subject}'?"
        )
        questions.append({
            "id": f"GA3-9_CP_{i+1:03d}",
            "question": question,
            "primary_type": "contradiction_check",
            "language": "en",
            "cp_id": row["cp_id"],
            "cp_reason": row.get("reason"),
            "involved_claims": involved,
            "ground_truth": {
                "answer": (
                    f"The corpus contains conflicting claims about '{predicate}' for '{subject}'."
                ),
                "expected_conflict_exposure": True,
            },
            "annotation_meta": {
                "annotator": "auto_from_cp_neo4j",
                "tenant_id": tenant_id,
            },
        })

    logger.info("Built %d ConflictPending questions", len(questions))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    logger.info("Written: %s", output_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=Path("benchmark/questions/gold_set_sap_v2.json"),
                        help="Path to gold_set_sap_v2 source")
    parser.add_argument("--out-50q", type=Path,
                        default=Path("benchmark/questions/gold_set_a38_50q.json"))
    parser.add_argument("--out-30q-cp", type=Path,
                        default=Path("benchmark/questions/gold_set_a38_30q_cp.json"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    build_50q_stratified(args.source, args.out_50q, seed=args.seed)
    build_30q_cp(args.out_30q_cp)


if __name__ == "__main__":
    main()
