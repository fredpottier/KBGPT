#!/usr/bin/env python3
"""
S3 sample — 12-class LogicalRelation classifier sur un échantillon de paires.

Pré-requis : S2 a tourné (`run_s2_pair_selection.py --run`) → les paires
sont marquées `:C12_SCANNED` avec `gate_decision`.

Pipeline :
1. Sélectionne les paires C12_SCANNED avec gate_decision = FULL_LLM_CLASSIFY
2. Sample N (défaut 50)
3. Run LogicalRelationClassifier sur chaque paire (parallel=10)
4. Distribution des 12 types + sample examples
5. Persist optionnel en LOGICAL_RELATION

Usage :
    docker exec knowbase-app python /tmp/run_s3_classifier_sample.py --sample 50
    docker exec knowbase-app python /tmp/run_s3_classifier_sample.py --sample 50 --persist
    docker exec knowbase-app python /tmp/run_s3_classifier_sample.py --decision LIKELY_SUPERSEDES --sample 20
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

sys.path.insert(0, "/app/src")

from knowbase.relations.logical_relation_classifier import LogicalRelationClassifier  # noqa: E402
from knowbase.relations.v33_types import (  # noqa: E402
    LogicalRelationOutput,
    LogicalRelationType,
    ScopeRelation,
    TemporalRelation,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")
VLLM_URL = os.getenv("VLLM_URL", "http://18.199.218.46:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_PARALLEL = 10


def fetch_candidate_pairs(driver, tenant_id: str, decision: str, sample_size: int) -> list[dict]:
    """Récupère les paires C12_SCANNED avec une gate_decision donnée."""
    with driver.session() as s:
        rows = s.run("""
            MATCH (a:Claim {tenant_id: $t})-[r:C12_SCANNED]-(b:Claim {tenant_id: $t})
            WHERE a.claim_id < b.claim_id
              AND r.gate_decision = $decision
              AND coalesce(r.legacy, false) = false
            RETURN
              a.claim_id AS a_id, a.text AS a_text, a.doc_id AS a_doc,
              a.publication_date AS a_pub, a.validity_start AS a_vstart,
              b.claim_id AS b_id, b.text AS b_text, b.doc_id AS b_doc,
              b.publication_date AS b_pub, b.validity_start AS b_vstart,
              r.gate_scope_relation AS scope_rel,
              r.gate_temporal_relation AS temp_rel,
              r.composite_score AS score
            ORDER BY r.composite_score DESC
            LIMIT $n
        """, t=tenant_id, decision=decision, n=sample_size).data()
    return rows


def classify_one(classifier: LogicalRelationClassifier, pair: dict) -> tuple[dict, LogicalRelationOutput | None]:
    """Worker pour ThreadPoolExecutor."""
    scope_rel = None
    temp_rel = None
    if pair.get("scope_rel"):
        try:
            scope_rel = ScopeRelation(pair["scope_rel"])
        except ValueError:
            pass
    if pair.get("temp_rel"):
        try:
            temp_rel = TemporalRelation(pair["temp_rel"])
        except ValueError:
            pass

    out = classifier.classify(
        claim_a_text=pair["a_text"] or "",
        claim_b_text=pair["b_text"] or "",
        scope_relation=scope_rel,
        temporal_relation=temp_rel,
        publication_date_a=pair.get("a_pub"),
        publication_date_b=pair.get("b_pub"),
        validity_start_a=pair.get("a_vstart"),
        validity_start_b=pair.get("b_vstart"),
    )
    return pair, out


def persist_logical_relation(driver, tenant_id: str, pair: dict, out: LogicalRelationOutput, ts: str) -> None:
    """Persist LOGICAL_RELATION typed edge avec props complètes."""
    if out.relation == LogicalRelationType.UNRELATED:
        # Skip persistence (V3.3 §3.G.3)
        return

    with driver.session() as s:
        s.run("""
            MATCH (a:Claim {claim_id: $aid, tenant_id: $tid})
            MATCH (b:Claim {claim_id: $bid, tenant_id: $tid})
            MERGE (a)-[r:LOGICAL_RELATION {type: $type}]->(b)
            ON CREATE SET
                r.strength = $strength,
                r.confidence = $confidence,
                r.scope_alignment = $scope_alignment,
                r.temporal_relation = $temporal_relation,
                r.is_contradiction = $is_contradiction,
                r.contradiction_reason = $contradiction_reason,
                r.reasoning = $reasoning,
                r.alternatives = $alternatives,
                r.extracted_by = $model,
                r.extracted_at = $ts,
                r.derived = false
            ON MATCH SET
                r.confidence = CASE WHEN $confidence > coalesce(r.confidence, 0.0) THEN $confidence ELSE r.confidence END,
                r.last_updated_at = $ts
        """,
            aid=pair["a_id"], bid=pair["b_id"], tid=tenant_id,
            type=out.relation.value,
            strength=out.strength.value,
            confidence=out.confidence,
            scope_alignment=out.scope_alignment.value if out.scope_alignment else None,
            temporal_relation=out.temporal_relation.value if out.temporal_relation else None,
            is_contradiction=out.is_contradiction,
            contradiction_reason=out.contradiction_reason,
            reasoning=out.reasoning,
            alternatives=json.dumps(out.alternatives) if out.alternatives else None,
            model=VLLM_MODEL,
            ts=ts,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="S3 sample 12-class classifier")
    parser.add_argument("--sample", type=int, default=50, help="Number of pairs to classify (default 50)")
    parser.add_argument("--decision", default="FULL_LLM_CLASSIFY", help="Gate decision filter (default FULL_LLM_CLASSIFY)")
    parser.add_argument("--persist", action="store_true", help="Persist LOGICAL_RELATION edges")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"run_s3_classifier_sample_{ts}.md"
    summary_path = OUTPUT_DIR / f"run_s3_classifier_sample_{ts}.json"

    logger.info("=" * 70)
    logger.info(f"S3 Sample — 12-class LogicalRelation classifier")
    logger.info("=" * 70)
    logger.info(f"vLLM : {VLLM_URL} ({VLLM_MODEL})")
    logger.info(f"Sample size : {args.sample}")
    logger.info(f"Gate decision filter : {args.decision}")
    logger.info(f"Persist : {args.persist}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        # Fetch
        pairs = fetch_candidate_pairs(driver, TENANT_ID, args.decision, args.sample)
        if not pairs:
            logger.warning(f"No pairs found with decision={args.decision}. Run S2 first.")
            return 1
        logger.info(f"\n{len(pairs)} pairs fetched")

        # Classify
        classifier = LogicalRelationClassifier(vllm_url=VLLM_URL, model=VLLM_MODEL)
        results: list[tuple[dict, LogicalRelationOutput | None]] = []

        t_start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
            futures = {ex.submit(classify_one, classifier, p): p for p in pairs}
            completed = 0
            for f in as_completed(futures):
                pair, out = f.result()
                results.append((pair, out))
                completed += 1
                if completed % 10 == 0:
                    logger.info(f"  {completed}/{len(pairs)} ({time.time() - t_start:.1f}s)")

        elapsed = time.time() - t_start
        logger.info(f"\nDone in {elapsed:.1f}s ({len(pairs) / elapsed:.1f}/s)")

        # Stats
        valid_results = [(p, o) for p, o in results if o is not None]
        relation_counts = Counter(o.relation.value for _, o in valid_results)
        contradiction_count = sum(1 for _, o in valid_results if o.is_contradiction)
        strength_counts = Counter(o.strength.value for _, o in valid_results)

        logger.info(f"\n=== Distribution des 12 types ===")
        for k, v in relation_counts.most_common():
            pct = v / len(valid_results) * 100 if valid_results else 0
            logger.info(f"  {k}: {v} ({pct:.0f}%)")
        logger.info(f"\nVraies contradictions (CONFLICT + scope aligned + conf ≥ 0.90) : {contradiction_count}")
        logger.info(f"Strength dist : {dict(strength_counts)}")

        # Sample examples
        logger.info(f"\n=== Sample examples ===")
        for rel_type in [LogicalRelationType.CONFLICT, LogicalRelationType.SUBSET, LogicalRelationType.EQUIVALENT,
                         LogicalRelationType.SUPERSEDES, LogicalRelationType.UNRELATED]:
            samples = [(p, o) for p, o in valid_results if o.relation == rel_type][:2]
            if not samples:
                continue
            logger.info(f"\n  [{rel_type.value}]")
            for p, o in samples:
                logger.info(f"    A ({p['a_doc']}): {p['a_text'][:120]}")
                logger.info(f"    B ({p['b_doc']}): {p['b_text'][:120]}")
                logger.info(f"    → conf={o.confidence:.2f}, strength={o.strength.value}, contradiction={o.is_contradiction}")
                logger.info(f"    reasoning: {o.reasoning[:150]}")

        # Persist
        if args.persist:
            logger.info(f"\n--- Persisting LOGICAL_RELATION edges ---")
            persisted = 0
            skipped_unrelated = 0
            for p, o in valid_results:
                if o.relation == LogicalRelationType.UNRELATED:
                    skipped_unrelated += 1
                    continue
                persist_logical_relation(driver, TENANT_ID, p, o, ts)
                persisted += 1
            logger.info(f"  Persisted : {persisted}")
            logger.info(f"  Skipped UNRELATED : {skipped_unrelated}")

        # Markdown report
        md = [
            f"# S3 Sample — 12-class classifier ({ts})",
            "",
            f"**vLLM** : `{VLLM_URL}` · **Sample** : {len(pairs)} · **Gate decision** : `{args.decision}` · **Persist** : `{args.persist}`",
            "",
            "## Distribution des 12 types",
            "",
            "| Type | Count | % |",
            "|---|---:|---:|",
        ]
        for k, v in relation_counts.most_common():
            pct = v / len(valid_results) * 100 if valid_results else 0
            md.append(f"| {k} | {v} | {pct:.0f}% |")
        md.append("")
        md.append(f"**Vraies contradictions** (CONFLICT + aligned scope + conf ≥ 0.90) : {contradiction_count}")
        md.append("")
        md.append("## Stats")
        md.append("")
        md.append(f"- Total pairs : {len(pairs)}")
        md.append(f"- Valid LLM responses : {len(valid_results)}")
        md.append(f"- Failed : {len(pairs) - len(valid_results)}")
        md.append(f"- Throughput : {len(pairs) / elapsed:.1f}/s")
        md.append(f"- Total elapsed : {elapsed:.1f}s")
        md.append("")
        md.append("## Sample examples")
        md.append("")
        for rel_type in [LogicalRelationType.CONFLICT, LogicalRelationType.SUBSET, LogicalRelationType.EQUIVALENT,
                         LogicalRelationType.SUPERSEDES, LogicalRelationType.SUPERSET, LogicalRelationType.EXCEPTION,
                         LogicalRelationType.OVERLAP, LogicalRelationType.DISJOINT, LogicalRelationType.DEFINITION_OF,
                         LogicalRelationType.EVOLVES_FROM, LogicalRelationType.REAFFIRMS, LogicalRelationType.UNRELATED]:
            samples = [(p, o) for p, o in valid_results if o.relation == rel_type][:3]
            if not samples:
                continue
            md.append(f"### {rel_type.value}")
            md.append("")
            for p, o in samples:
                md.append(f"- **A** (`{p['a_doc']}`) : {(p['a_text'] or '')[:200]}")
                md.append(f"- **B** (`{p['b_doc']}`) : {(p['b_text'] or '')[:200]}")
                md.append(f"  - conf=`{o.confidence:.2f}`, strength=`{o.strength.value}`, is_contradiction=`{o.is_contradiction}`")
                md.append(f"  - reasoning: {o.reasoning[:300]}")
                md.append("")

        report_path.write_text("\n".join(md), encoding="utf-8")

        summary = {
            "timestamp": ts,
            "vllm_url": VLLM_URL,
            "sample_size": len(pairs),
            "gate_decision": args.decision,
            "valid_results": len(valid_results),
            "elapsed_s": elapsed,
            "throughput_per_s": len(pairs) / elapsed,
            "relation_counts": dict(relation_counts),
            "contradictions": contradiction_count,
            "strength_counts": dict(strength_counts),
            "persisted": args.persist,
        }
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info(f"\n✅ Report : {report_path}")
        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
