#!/usr/bin/env python3
"""Rejoue les jugements Claude sur un bench JSON existant."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from dotenv import load_dotenv
load_dotenv()

import httpx

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]


def judge(passage_text, doc_title, claims_a, claims_b, model="claude-sonnet-4-20250514"):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    prompt = f"""You are evaluating two LLM extractions of CLAIMS from the same source passage.

## Source passage (from "{doc_title}")
{passage_text}

## Extraction A (baseline: Qwen2.5-72B)
{json.dumps(claims_a, ensure_ascii=False, indent=2)}

## Extraction B (challenger: Qwen3-235B-A22B-Instruct-2507)
{json.dumps(claims_b, ensure_ascii=False, indent=2)}

Evaluate on these axes (1-5 scale):
- coverage: how many genuine claims from the passage are captured
- precision: how few hallucinated/incorrect claims
- structured_form_quality: subject/predicate/object correctness when filled

Then verdict: A_BETTER | B_BETTER | EQUIVALENT (with one-sentence justification).

Return STRICT JSON: {{"A": {{"coverage": int, "precision": int, "structured_form_quality": int}}, "B": {{...}}, "verdict": "...", "justification": "..."}}"""

    payload = {
        "model": model,
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}],
    }
    with httpx.Client(timeout=90) as client:
        r = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
    r.raise_for_status()
    text = r.json()["content"][0]["text"].strip()
    if "```json" in text:
        s = text.find("```json") + 7
        e = text.find("```", s)
        text = text[s:e].strip()
    elif text.startswith("```"):
        s = text.find("```") + 3
        e = text.rfind("```")
        text = text[s:e].strip()
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--model", default="claude-sonnet-4-20250514")
    args = ap.parse_args()

    data = json.load(open(args.input, encoding="utf-8"))
    verdicts = {"A_BETTER": 0, "B_BETTER": 0, "EQUIVALENT": 0, "ERROR": 0}
    coverage_a, coverage_b, prec_a, prec_b = [], [], [], []

    # Fallback: re-fetch passage_text depuis Neo4j si manquant dans le JSON
    text_cache = {}
    needs_neo4j = any("text" not in s for s in data["samples"])
    if needs_neo4j:
        from neo4j import GraphDatabase
        uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        pwd = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
        drv = GraphDatabase.driver(uri, auth=(user, pwd))
        pids = [s["passage_id"] for s in data["samples"] if "passage_id" in s]
        with drv.session() as session:
            r = session.run(
                "MATCH (c:Claim) WHERE c.passage_id IN $pids "
                "WITH c.passage_id AS pid, head(collect(c.passage_text)) AS txt "
                "RETURN pid, txt",
                pids=pids,
            ).data()
        for row in r:
            text_cache[row["pid"]] = row["txt"]
        drv.close()
        print(f"[neo4j] re-fetched {len(text_cache)}/{len(pids)} passage texts")

    for i, s in enumerate(data["samples"]):
        if "claims" not in s.get("baseline", {}) or "claims" not in s.get("challenger", {}):
            print(f"Sample {i+1}: skip (missing claims)")
            continue
        passage_text = s.get("text") or text_cache.get(s.get("passage_id", ""), "")
        if not passage_text:
            print(f"Sample {i+1}: skip (no text)")
            continue
        try:
            v = judge(
                passage_text=passage_text,
                doc_title=s["doc_title"],
                claims_a=s["baseline"]["claims"],
                claims_b=s["challenger"]["claims"],
                model=args.model,
            )
            s["judge"] = v
            verdict = v.get("verdict", "ERROR")
            if verdict in verdicts: verdicts[verdict] += 1
            else: verdicts["ERROR"] += 1
            if v.get("A"):
                coverage_a.append(v["A"].get("coverage", 0))
                prec_a.append(v["A"].get("precision", 0))
            if v.get("B"):
                coverage_b.append(v["B"].get("coverage", 0))
                prec_b.append(v["B"].get("precision", 0))
            print(f"Sample {i+1:2d}: {verdict:12s} | A.cov={v.get('A',{}).get('coverage','?')} B.cov={v.get('B',{}).get('coverage','?')} | {v.get('justification','')[:100]}")
        except Exception as e:
            print(f"Sample {i+1}: ERROR {type(e).__name__}: {e}")
            verdicts["ERROR"] += 1

    data["summary"]["judge_verdicts"] = verdicts
    if coverage_a: data["summary"]["judge_avg_coverage_baseline"] = round(sum(coverage_a)/len(coverage_a), 2)
    if coverage_b: data["summary"]["judge_avg_coverage_challenger"] = round(sum(coverage_b)/len(coverage_b), 2)
    if prec_a: data["summary"]["judge_avg_precision_baseline"] = round(sum(prec_a)/len(prec_a), 2)
    if prec_b: data["summary"]["judge_avg_precision_challenger"] = round(sum(prec_b)/len(prec_b), 2)

    out_path = Path(args.input).with_suffix(".rejudged.json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== VERDICTS ===")
    for k, v in verdicts.items(): print(f"  {k}: {v}")
    if coverage_a: print(f"\nCoverage avg: A={data['summary']['judge_avg_coverage_baseline']} B={data['summary']['judge_avg_coverage_challenger']}")
    if prec_a: print(f"Precision avg: A={data['summary']['judge_avg_precision_baseline']} B={data['summary']['judge_avg_precision_challenger']}")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
