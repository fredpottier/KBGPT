#!/usr/bin/env python3
"""
Test V2-S2 — Anchor Extractor + Anchor Filter sur questions diverses.

Lance N questions cross-domain à travers le pipeline V2-S2 :
  Question → AnchorExtractor (LLM) → ResolvedAnchor → AnchorFilter (Cypher) → matched_doc_ids

Valide :
- Sémantique multilingue (anglais, français)
- Distinction POINT vs RANGE vs CURRENT_DEFAULT
- Validator evidence-locked (rejette les hallucinations)
- Filtrage cohérent contre le KG aerospace_compliance

Usage : docker exec -e VLLM_URL=http://x.y.z.w:8000 knowbase-app python /app/scripts/test_anchor_v2_s2.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

from knowbase.anchor import AnchorExtractor, AnchorFilter

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("test_anchor")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

VLLM_URL = os.getenv("VLLM_URL", "http://18.199.218.46:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

FORENSICS_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
FORENSICS_DIR.mkdir(parents=True, exist_ok=True)

# Questions cross-domain — mix EN/FR, POINT/RANGE/CURRENT_DEFAULT, divers domaines
TEST_QUESTIONS = [
    # CURRENT_DEFAULT (aucun anchor explicite)
    "What are the export control rules for high-power lasers?",
    "Quel est le mode de chiffrement au repos de S/4HANA Cloud Private Edition ?",
    "What dosage is recommended for biomarker X?",
    # POINT — version explicite
    "Which APIs are available to manage a BusinessPartner in S/4HANA 1809?",
    "Quelles règles de certification sont définies dans CS-25 Amendment 27 ?",
    "What does Regulation (EU) 2021/821 say about brokering services?",
    # POINT — date explicite
    "What was the recommended dose in 2018?",
    "Quelle était la disposition légale au 15 décembre 2023 ?",
    # RANGE avec bornes
    "How did encryption evolve between S/4HANA 1809 and 2023?",
    "Comment cette règle a évolué entre 2018 et 2024 ?",
    "Compare CS-25 Amendment 27 and Amendment 28 on lightning protection.",
    # RANGE sans bornes
    "Comment le contrôle des exports dual-use a évolué dans la réglementation européenne ?",
    "List all dosage recommendations for biomarker Y since it was first approved.",
    # Questions ambiguës / pièges
    "Tell me everything about the S/4HANA 2023 release.",  # POINT (2023)
    "Quels sont les changements récents ?",  # RANGE sans bornes (récents = implicite)
]


def main() -> int:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    extractor = AnchorExtractor(vllm_url=VLLM_URL, model_id=VLLM_MODEL)
    filt = AnchorFilter(driver=driver, tenant_id=TENANT_ID)

    results = []
    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"\n[{i:02d}] Q: {q}")
        try:
            anchor = extractor.extract(q)
            print(f"    anchor_type={anchor.anchor_type.value} conf={anchor.confidence:.2f}")
            scope_repr = []
            for f in ("version", "date", "range_start", "range_end"):
                v = getattr(anchor.scope, f, None)
                if v:
                    scope_repr.append(f"{f}={v}")
            if anchor.scope.extraction_evidence:
                scope_repr.append(f"evidence='{anchor.scope.extraction_evidence}'")
            if scope_repr:
                print(f"    scope: {', '.join(scope_repr)}")
            print(f"    method={anchor.extraction_method}")

            filt_result = filt.filter(anchor)
            n = filt_result.n_matched
            ids_repr = (
                "ALL (no filter, current_default)"
                if filt_result.matched_doc_ids is None
                else f"{n} doc(s)"
                + (f" → {filt_result.matched_doc_ids[:3]}{'...' if n > 3 else ''}" if n else "")
            )
            print(f"    filter: method={filt_result.method} → {ids_repr}")

            results.append(
                {
                    "question": q,
                    "anchor": anchor.model_dump(),
                    "filter_method": filt_result.method,
                    "n_matched": n,
                    "matched_sample": (filt_result.matched_doc_ids or [])[:5]
                    if filt_result.matched_doc_ids is not None
                    else None,
                    "filter_diagnostic": filt_result.diagnostic,
                }
            )
        except Exception as exc:
            logger.error("Question %d failed: %s", i, exc, exc_info=True)
            results.append({"question": q, "error": str(exc)})

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = FORENSICS_DIR / f"anchor_v2_s2_test_{ts}.json"
    with out_path.open("w") as f:
        json.dump(
            {
                "metadata": {
                    "vllm_url": VLLM_URL,
                    "model_id": VLLM_MODEL,
                    "n_questions": len(TEST_QUESTIONS),
                    "ts": ts,
                },
                "results": results,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nForensics saved to {out_path}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
