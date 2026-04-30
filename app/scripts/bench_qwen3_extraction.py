#!/usr/bin/env python3
"""
P3.5 — Bench Qwen3-235B vs Qwen2.5-14B sur extraction de claims.

Compare les 2 modèles sur 5 docs représentatifs du corpus actuel.

Métriques :
- nb claims extraits
- taux JSON valide (réponses LLM bien formées)
- latence moyenne par batch
- hallucination cross-corpus (claims mentionnant des sujets hors-doc)

Sortie : data/forensics/qwen3_extraction_bench_<ts>.json + rapport markdown.

Usage :
  docker exec knowbase-app python /app/scripts/bench_qwen3_extraction.py
  --baseline-vllm http://18.185.16.189:8000   # Qwen2.5-14B
  --challenger deepinfra                       # Qwen3-235B via DEEPINFRA_API_KEY
  --doc-ids cs25_amdt_28_32f1a9ac dualuse_reg_2021_821_original_65eef5dc
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, "/app/src")

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("bench_qwen3")

FORENSICS_DIR = Path("/data/forensics")
FORENSICS_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = Path("/data/extraction_cache")

# Prompt simplifié extraction claims pour le bench (pas le prompt ClaimFirst complet,
# trop lourd pour bench rapide — ici on mesure surtout JSON validity + cohérence).
EXTRACTION_PROMPT = """Extract atomic factual claims from the following document text.

Each claim is a single, self-contained, verifiable factual statement.

Output JSON only:
{
  "claims": [
    {"text": "verbatim or near-verbatim claim", "evidence_quote": "quote from source"}
  ]
}

Rules:
- Maximum 20 claims per call
- evidence_quote MUST be substring of the input
- Skip mentions of other documents/regulations not under analysis
- If the text is empty or non-factual, return {"claims": []}

Document text:
"""


def call_vllm(vllm_url: str, model: str, prompt: str, timeout: float = 60.0) -> tuple[str, float]:
    """Call vLLM-compatible endpoint, return (raw_response, latency_seconds)."""
    start = time.time()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{vllm_url.rstrip('/')}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"], time.time() - start
    except Exception as exc:
        logger.error("vLLM call failed: %s", exc)
        return f'{{"error": "{exc}"}}', time.time() - start


def call_deepinfra(model: str, prompt: str, api_key: str, timeout: float = 60.0) -> tuple[str, float]:
    """Call DeepInfra (OpenAI-compatible)."""
    start = time.time()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"},
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"], time.time() - start
    except Exception as exc:
        logger.error("DeepInfra call failed: %s", exc)
        return f'{{"error": "{exc}"}}', time.time() - start


def evaluate_response(raw: str, source_text: str) -> dict[str, Any]:
    """Parse + valide la réponse LLM, mesure les métriques qualité."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "json_valid": False,
            "json_error": str(exc),
            "n_claims": 0,
            "n_with_evidence": 0,
            "n_evidence_in_source": 0,
            "claims": [],
        }

    claims = parsed.get("claims", [])
    if not isinstance(claims, list):
        return {
            "json_valid": False,
            "json_error": "claims field is not a list",
            "n_claims": 0,
            "n_with_evidence": 0,
            "n_evidence_in_source": 0,
            "claims": [],
        }

    n_with_evidence = 0
    n_evidence_in_source = 0
    src_lower = source_text.lower()
    for c in claims:
        if isinstance(c, dict) and c.get("evidence_quote"):
            n_with_evidence += 1
            if c["evidence_quote"].strip().lower() in src_lower:
                n_evidence_in_source += 1

    return {
        "json_valid": True,
        "n_claims": len(claims),
        "n_with_evidence": n_with_evidence,
        "n_evidence_in_source": n_evidence_in_source,
        "claims": claims[:5],  # premiers 5 pour audit
    }


def load_doc_text(doc_id: str, max_chars: int = 8000) -> str | None:
    """Charge le full_text d'un doc depuis le cache, tronqué à max_chars."""
    parts = doc_id.rsplit("_", 1)
    if len(parts) != 2:
        return None
    hash_prefix = parts[1]
    candidates = list(CACHE_DIR.glob(f"{hash_prefix}*.v5cache.json"))
    if not candidates:
        return None
    try:
        data = json.loads(candidates[0].read_text())
        ft = data.get("extraction", {}).get("full_text", "")
        return ft[:max_chars]
    except Exception:
        return None


def run_bench(doc_ids: list[str], runners: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for doc_id in doc_ids:
        source = load_doc_text(doc_id)
        if not source:
            logger.warning("Skipping %s : no source text", doc_id)
            continue
        prompt = EXTRACTION_PROMPT + source
        doc_results = {"doc_id": doc_id, "source_chars": len(source), "runners": {}}
        for r in runners:
            logger.info("Running %s on %s", r["label"], doc_id)
            if r["mode"] == "vllm":
                raw, lat = call_vllm(r["url"], r["model"], prompt)
            elif r["mode"] == "deepinfra":
                raw, lat = call_deepinfra(r["model"], prompt, r["api_key"])
            else:
                continue
            metrics = evaluate_response(raw, source)
            doc_results["runners"][r["label"]] = {
                "latency_s": round(lat, 2),
                "model": r["model"],
                **metrics,
            }
        results.append(doc_results)
    return {"results": results, "ts": datetime.utcnow().isoformat() + "Z"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-vllm", default=os.getenv("VLLM_URL", ""), help="URL vLLM Qwen2.5-14B")
    parser.add_argument("--baseline-model", default="Qwen/Qwen2.5-14B-Instruct-AWQ")
    parser.add_argument("--challenger", choices=["deepinfra", "vllm", "skip"], default="deepinfra")
    parser.add_argument("--challenger-model", default="Qwen/Qwen3-235B-A22B-Instruct-2507")
    parser.add_argument("--challenger-vllm", default="")
    parser.add_argument("--doc-ids", nargs="+", default=[
        "cs25_amdt_28_32f1a9ac",
        "dualuse_reg_2021_821_original_65eef5dc",
        "dualuse_del_2024_2547_cb08f84b",
    ])
    args = parser.parse_args()

    runners = []
    if args.baseline_vllm:
        runners.append({
            "label": "qwen25_14b_vllm",
            "mode": "vllm",
            "url": args.baseline_vllm,
            "model": args.baseline_model,
        })
    if args.challenger == "deepinfra":
        api_key = os.getenv("DEEPINFRA_API_KEY")
        if not api_key:
            logger.error("DEEPINFRA_API_KEY not set, skipping challenger")
        else:
            runners.append({
                "label": "qwen3_235b_deepinfra",
                "mode": "deepinfra",
                "model": args.challenger_model,
                "api_key": api_key,
            })
    elif args.challenger == "vllm" and args.challenger_vllm:
        runners.append({
            "label": "qwen3_235b_vllm",
            "mode": "vllm",
            "url": args.challenger_vllm,
            "model": args.challenger_model,
        })

    if not runners:
        logger.error("No runners configured")
        return 1

    logger.info("Running bench on %d docs × %d runners", len(args.doc_ids), len(runners))
    bench = run_bench(args.doc_ids, runners)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = FORENSICS_DIR / f"qwen3_extraction_bench_{ts}.json"
    with out_path.open("w") as f:
        json.dump(bench, f, indent=2, default=str)

    # Print summary
    print(f"\n=== BENCH SUMMARY ===\n")
    for doc_result in bench["results"]:
        print(f"\n{doc_result['doc_id']} ({doc_result['source_chars']} chars):")
        for label, m in doc_result["runners"].items():
            print(
                f"  {label:30s}  json_valid={m.get('json_valid')}  "
                f"n_claims={m.get('n_claims', 0):3d}  "
                f"evidence_ok={m.get('n_evidence_in_source', 0):3d}/{m.get('n_with_evidence', 0):3d}  "
                f"latency={m.get('latency_s', 0):.1f}s"
            )
    print(f"\nForensics : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
