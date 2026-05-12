#!/usr/bin/env python3
"""
S2 — Pair Selection multi-signal + Scope/Temporal Gate (run + dry-run).

Pipeline complet :
1. CandidateMinerV33 mine des paires multi-signal (5 signaux composites)
2. ScopeTemporalGateV33 évalue chaque paire et produit un verdict
3. Distribution des verdicts + audit metrics

Modes :
- --dry-run : ne persist pas les markers C12_SCANNED, juste affiche stats
- --run : persiste les markers + Gate verdicts (audit trail)

Usage :
    docker exec knowbase-app python /tmp/run_s2_pair_selection.py --dry-run
    docker exec knowbase-app python /tmp/run_s2_pair_selection.py --run
    docker exec knowbase-app python /tmp/run_s2_pair_selection.py --threshold 0.55 --max-pairs 5000

Cible (cf. plan §S2 acceptation) :
- ≥30% des paires retenues par S2.A sont filtrées par S2.B sans LLM
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

sys.path.insert(0, "/app/src")

from knowbase.relations.candidate_miner_v33 import CandidateMinerV33  # noqa: E402
from knowbase.relations.gate_v33 import ScopeTemporalGateV33  # noqa: E402
from knowbase.relations.v33_types import GateDecision  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="S2 pair selection + Scope/Temporal Gate")
    parser.add_argument("--dry-run", action="store_true", help="Don't persist markers, just show stats")
    parser.add_argument("--run", action="store_true", help="Persist C12_SCANNED markers + Gate verdicts")
    parser.add_argument("--threshold", type=float, default=0.55, help="Composite score threshold (default 0.55)")
    parser.add_argument("--max-pairs", type=int, default=10000, help="Cap total pairs (default 10000)")
    parser.add_argument("--gate-sample", type=int, default=0, help="Sample size for Gate evaluation (0=all). Default 0=all.")
    parser.add_argument("--skip-new-pairs", action="store_true", help="Skip multi-signal new pairs mining (use only C4 cached). Recommended on first run to avoid Neo4j OOM.")
    args = parser.parse_args()

    if not args.dry_run and not args.run:
        logger.error("Must specify --dry-run or --run")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"run_s2_pair_selection_{ts}.md"
    summary_path = OUTPUT_DIR / f"run_s2_pair_selection_{ts}.json"

    logger.info("=" * 70)
    logger.info(f"S2 — Pair Selection + Gate ({'DRY-RUN' if args.dry_run else 'RUN'})")
    logger.info("=" * 70)
    logger.info(f"Tenant : {TENANT_ID}")
    logger.info(f"Threshold : {args.threshold}")
    logger.info(f"Max pairs : {args.max_pairs}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        # === Step 1 — Candidate mining (S2.A) ===
        logger.info("\n--- Step 1: Pair selection multi-signal (S2.A) ---")
        miner = CandidateMinerV33(driver, tenant_id=TENANT_ID)
        t0 = time.time()
        candidates = miner.mine_candidates(
            composite_threshold=args.threshold,
            max_pairs=args.max_pairs,
            include_new_pairs=not args.skip_new_pairs,
        )
        elapsed_mining = time.time() - t0
        logger.info(f"  {len(candidates):,} candidates retained (elapsed: {elapsed_mining:.1f}s)")

        if not candidates:
            logger.warning("No candidates found — adjust threshold or check KG state")
            return 0

        # === Step 2 — Gate evaluation (S2.B) ===
        logger.info("\n--- Step 2: Scope/Temporal Gate (S2.B) ---")
        gate = ScopeTemporalGateV33(driver, tenant_id=TENANT_ID)

        sample = candidates[: args.gate_sample] if args.gate_sample else candidates
        logger.info(f"  Evaluating {len(sample):,} pairs through Gate")

        verdicts = []
        t0 = time.time()
        for i, pair in enumerate(sample):
            if i % 500 == 0 and i > 0:
                rate = i / (time.time() - t0) if (time.time() - t0) > 0 else 0
                logger.info(f"  {i:,}/{len(sample):,} ({rate:.0f}/s)")
            v = gate.evaluate_pair(pair.claim_a_id, pair.claim_b_id)
            verdicts.append(v)
        elapsed_gate = time.time() - t0
        logger.info(f"  Gate eval done in {elapsed_gate:.1f}s ({len(sample)/elapsed_gate:.0f}/s)")

        # === Step 3 — Aggregate stats ===
        decision_counts = Counter(v.decision.value for v in verdicts)
        scope_counts = Counter(v.scope_relation.value for v in verdicts)
        temporal_counts = Counter(v.temporal_relation.value for v in verdicts)

        n_total = len(verdicts)
        n_skip = decision_counts.get(GateDecision.SKIP_DISJOINT.value, 0)
        n_likely_sup = decision_counts.get(GateDecision.LIKELY_SUPERSEDES.value, 0)
        n_likely_reaffirm = decision_counts.get(GateDecision.LIKELY_REAFFIRMS.value, 0)
        n_full_llm = decision_counts.get(GateDecision.FULL_LLM_CLASSIFY.value, 0)

        n_filtered_no_llm = n_skip + n_likely_sup + n_likely_reaffirm
        filter_rate = (n_filtered_no_llm / n_total * 100) if n_total else 0

        logger.info("\n--- Synthèse Gate ---")
        logger.info(f"  Total paires évaluées : {n_total:,}")
        logger.info(f"  Filtrées sans LLM : {n_filtered_no_llm:,} ({filter_rate:.0f}%)")
        logger.info(f"    SKIP_DISJOINT : {n_skip:,}")
        logger.info(f"    LIKELY_SUPERSEDES : {n_likely_sup:,}")
        logger.info(f"    LIKELY_REAFFIRMS : {n_likely_reaffirm:,}")
        logger.info(f"  → LLM classifier (S3) : {n_full_llm:,}")
        logger.info(f"\n  Cible plan : ≥30% filtered without LLM. {'✅ ATTEINTE' if filter_rate >= 30 else '⚠️ EN-DESSOUS'}")

        # === Step 4 — Persist if --run ===
        if args.run:
            logger.info("\n--- Step 4: Persist C12_SCANNED markers ---")
            n_marked = miner.mark_pairs_scanned(candidates)
            logger.info(f"  Marked {n_marked:,} pairs :C12_SCANNED")

            # Persist Gate verdicts on the relation (audit trail)
            logger.info("\n--- Step 4 bis: Persist Gate verdicts ---")
            with driver.session() as s:
                count_persisted = 0
                for v in verdicts:
                    s.run("""
                        MATCH (a:Claim {claim_id: $aid, tenant_id: $tid})-[r:C12_SCANNED]-(b:Claim {claim_id: $bid, tenant_id: $tid})
                        SET r.gate_decision = $decision,
                            r.gate_scope_relation = $scope_rel,
                            r.gate_temporal_relation = $temp_rel,
                            r.gate_pre_classified = $pre_classified,
                            r.gate_reasoning = $reasoning,
                            r.gate_evaluated_at = $ts
                    """,
                        aid=v.a_claim_id, bid=v.b_claim_id, tid=TENANT_ID,
                        decision=v.decision.value,
                        scope_rel=v.scope_relation.value,
                        temp_rel=v.temporal_relation.value,
                        pre_classified=v.pre_classified_relation.value if v.pre_classified_relation else None,
                        reasoning=v.reasoning,
                        ts=ts,
                    )
                    count_persisted += 1
                logger.info(f"  Persisted {count_persisted:,} Gate verdicts")
        else:
            logger.info("\n[DRY-RUN] No markers persisted, no Gate verdicts saved.")

        # === Step 5 — Sample examples ===
        logger.info("\n--- Step 5: Sample examples by decision ---")
        for decision_value in [d.value for d in GateDecision]:
            samples = [v for v in verdicts if v.decision.value == decision_value][:3]
            if not samples:
                continue
            logger.info(f"\n  [{decision_value}] {decision_counts.get(decision_value, 0):,} pairs — top 3 examples:")
            for v in samples:
                logger.info(f"    {v.a_claim_id} <-> {v.b_claim_id}: scope={v.scope_relation.value}, temp={v.temporal_relation.value}")
                logger.info(f"      → {v.reasoning[:100]}")

        # === Markdown report ===
        md = [
            f"# S2 — Pair Selection + Gate ({ts})",
            "",
            f"**Mode** : `{'DRY-RUN' if args.dry_run else 'RUN'}` · **Threshold** : `{args.threshold}` · **Max pairs** : `{args.max_pairs}`",
            "",
            "## Synthèse",
            "",
            f"- Pairs mined (S2.A) : **{len(candidates):,}**",
            f"- Pairs evaluated by Gate : **{n_total:,}**",
            f"- Filtered without LLM : **{n_filtered_no_llm:,} ({filter_rate:.0f}%)**",
            f"- → LLM classifier (S3) : {n_full_llm:,}",
            "",
            "**Cible plan** : ≥30% filtered without LLM",
            f"**Résultat** : {'✅ Atteinte' if filter_rate >= 30 else '⚠️ En-dessous'}",
            "",
            "## Distribution des décisions",
            "",
            "| Décision | Count | % |",
            "|---|---:|---:|",
        ]
        for d in [GateDecision.SKIP_DISJOINT, GateDecision.LIKELY_SUPERSEDES, GateDecision.LIKELY_REAFFIRMS, GateDecision.FULL_LLM_CLASSIFY]:
            count = decision_counts.get(d.value, 0)
            pct = count / n_total * 100 if n_total else 0
            md.append(f"| {d.value} | {count:,} | {pct:.1f}% |")
        md.append("")
        md.append("## Distribution scope_relation")
        md.append("")
        md.append("| Relation | Count |")
        md.append("|---|---:|")
        for k, v in scope_counts.most_common():
            md.append(f"| {k} | {v:,} |")
        md.append("")
        md.append("## Distribution temporal_relation")
        md.append("")
        md.append("| Relation | Count |")
        md.append("|---|---:|")
        for k, v in temporal_counts.most_common():
            md.append(f"| {k} | {v:,} |")
        md.append("")

        report_path.write_text("\n".join(md), encoding="utf-8")

        summary = {
            "timestamp": ts,
            "tenant_id": TENANT_ID,
            "mode": "dry-run" if args.dry_run else "run",
            "threshold": args.threshold,
            "max_pairs": args.max_pairs,
            "candidates_mined": len(candidates),
            "pairs_evaluated_by_gate": n_total,
            "filter_rate_pct": filter_rate,
            "decision_counts": dict(decision_counts),
            "scope_counts": dict(scope_counts),
            "temporal_counts": dict(temporal_counts),
            "elapsed_mining_s": elapsed_mining,
            "elapsed_gate_s": elapsed_gate,
        }
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info(f"\n✅ Report : {report_path}")
        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
