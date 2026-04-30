#!/usr/bin/env python3
"""
Génération Atlas narratif depuis Perspectives V2 (P5.2).

Usage :
  docker exec -e VLLM_URL=http://x.y.z.w:8000 knowbase-app python /app/scripts/generate_atlas.py
  docker exec knowbase-app python /app/scripts/generate_atlas.py --wipe --max 30
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

from knowbase.atlas import AtlasGenerator


def _resolve_vllm_url() -> str:
    """Lit Redis burst state pour obtenir vLLM URL."""
    try:
        import redis as _redis
        import json as _json
        r = _redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)
        raw = r.get("osmose:burst:state")
        if raw:
            state = _json.loads(raw)
            if state.get("active") and state.get("vllm_url"):
                return state["vllm_url"]
    except Exception:
        pass
    return os.getenv("VLLM_URL", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=60, help="Max perspectives à traiter")
    parser.add_argument("--wipe", action="store_true", help="Supprime Atlas existant avant régénération")
    parser.add_argument("--vllm-url", default="")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger = logging.getLogger("generate_atlas")

    vllm_url = args.vllm_url or _resolve_vllm_url()
    if not vllm_url:
        logger.error("No vLLM URL configured (Redis burst state empty + VLLM_URL not set + --vllm-url not provided)")
        return 1

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    driver = GraphDatabase.driver(neo4j_uri, auth=("neo4j", os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")))

    gen = AtlasGenerator(
        driver=driver,
        vllm_url=vllm_url,
        tenant_id=os.getenv("TENANT_ID", "default"),
        vllm_model=os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ"),
    )

    logger.info(f"Starting Atlas generation: vllm={vllm_url}, max={args.max}, wipe={args.wipe}")
    stats = gen.generate_all(max_perspectives=args.max, wipe_existing=args.wipe)

    print("\n=== Atlas Generation Stats ===")
    print(f"  Perspectives processed : {stats.n_perspectives_processed}")
    print(f"  Topics generated       : {stats.n_topics_generated}")
    print(f"  Topics persisted       : {stats.n_topics_persisted}")
    print(f"  Roots created          : {stats.n_roots_created}")
    print(f"  Homepage generated     : {stats.homepage_generated}")
    print(f"  Errors                 : {len(stats.errors)}")
    print(f"  Duration               : {stats.duration_seconds}s")
    print(f"  Estimated cost         : ${stats.estimated_cost_usd}")
    if stats.errors:
        print(f"\n  First errors :")
        for e in stats.errors[:5]:
            print(f"    - {e}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
