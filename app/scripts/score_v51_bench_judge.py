"""Score V5.1 bench via LLM-judge (Llama-3.3-70B-Instruct).

Charte OSMOSIS (no proprietary judge). Cohérent S0 v2 (judge déjà calibré).
Lit le fichier bench_v51_http_143q output et produit un score par question
en comparant answer vs ground_truth.

Prompt judge : binary {1.0, 0.5, 0.0} avec rationale.
  1.0 = answer correctly captures ground truth (numerics OK, identifiers OK)
  0.5 = partial answer (some info correct but incomplete OR with errors)
  0.0 = wrong / abstain when answerable / hallucination

Sortie : scoring augmenté du bench file + report comparatif vs baselines.

Usage :
    docker exec knowbase-app python scripts/score_v51_bench_judge.py \\
        --input benchmark/runs/v51_bench_143q_<ts>.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests


JUDGE_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
JUDGE_ENDPOINT = "https://api.deepinfra.com/v1/openai/chat/completions"

JUDGE_PROMPT = """You are an expert evaluator scoring an LLM-generated answer against a ground-truth reference.

QUESTION TYPE: {primary_type}
QUESTION: {question}

GROUND TRUTH (reference answer):
{ground_truth}

CANDIDATE ANSWER:
{answer}

Scoring rubric (binary with partial credit):
- 1.0 : Answer correctly captures the ground truth. For numeric/identifier answers, exact values match. No factual error.
- 0.5 : Partial credit. Some correct info but incomplete OR has minor errors OR cites correct doc but wrong value.
- 0.0 : Wrong answer / hallucination / abstain when ground truth is answerable / completely off-topic.

Special cases:
- For false_premise: 1.0 if candidate correctly rejects the false premise (says "this doesn't exist", "no such component"). 0.0 if it makes up information.
- For unanswerable: 1.0 if candidate appropriately abstains. 0.0 if it fabricates.
- For comparison/multi_hop: 1.0 if all key dimensions in ground truth are covered correctly.

Output ONLY a JSON object (no markdown, no code fences):
{{"score": 1.0|0.5|0.0, "rationale": "1-2 sentence justification"}}"""


def judge_one(question: str, ground_truth: str, answer: str, primary_type: str,
              max_retries: int = 3) -> dict:
    """Score 1 question via Llama-3.3-70B judge."""
    key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if not key:
        return {"_error": "no_deepinfra_api_key"}

    prompt = JUDGE_PROMPT.format(
        primary_type=primary_type,
        question=question[:1000],
        ground_truth=ground_truth[:2000],
        answer=answer[:3000],
    )
    payload = {
        "model": JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 300,
    }

    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                JUDGE_ENDPOINT,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"].strip()
            # Try parse JSON (strip code fences if any)
            content_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
            try:
                parsed = json.loads(content_clean)
                score = parsed.get("score")
                if score not in (0.0, 0.5, 1.0):
                    return {"_error": f"invalid_score: {score}", "raw": content}
                return {
                    "score": float(score),
                    "rationale": str(parsed.get("rationale", ""))[:500],
                }
            except json.JSONDecodeError:
                # Try regex fallback
                m = re.search(r'"score"\s*:\s*([\d.]+)', content)
                if m:
                    return {"score": float(m.group(1)),
                            "rationale": content[:500]}
                return {"_error": "non_json_response", "raw": content[:300]}
        except requests.HTTPError as e:
            last_err = f"http_{e.response.status_code}"
            if e.response.status_code < 500 and e.response.status_code != 429:
                return {"_error": last_err}
        except Exception as e:
            last_err = f"{type(e).__name__}"
        if attempt < max_retries - 1:
            time.sleep(2 ** (attempt + 1))
    return {"_error": last_err or "unknown"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True,
                        help="bench output JSON")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        root = Path("/app") if Path("/app").exists() else Path.cwd()
        input_path = root / args.input
    if not input_path.exists():
        print(f"ERROR: {input_path} not found")
        return 1

    data = json.loads(input_path.read_text(encoding="utf-8"))
    results = data["results"]
    if args.limit > 0:
        results = results[: args.limit]
    n_total = len(results)

    print(f"=== Scoring V5.1 bench via {JUDGE_MODEL} ===")
    print(f"Input : {input_path}")
    print(f"To score: {n_total} questions")

    # Output path
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = input_path.parent / f"{input_path.stem}_scored_{ts}.json"

    scored = []
    t0 = time.time()
    for i, r in enumerate(results):
        if r.get("status") != "completed" or not r.get("answer"):
            scored.append({**r, "judge_score": 0.0,
                           "judge_rationale": "no_answer_to_judge"})
            continue
        question = r.get("question", "")
        gt = r.get("ground_truth", "")
        answer = r.get("answer", "")
        primary_type = r.get("primary_type", "unknown")

        print(f"[{i+1}/{n_total}] {r.get('qid')} [{primary_type}]...", end=" ", flush=True)
        out = judge_one(question, gt, answer, primary_type)
        if "_error" in out:
            print(f"❌ {out['_error']}")
            scored.append({**r, "judge_score": None,
                           "judge_rationale": f"judge_error: {out['_error']}"})
        else:
            score = out["score"]
            print(f"{score:.1f} — {out['rationale'][:80]}")
            scored.append({**r, "judge_score": score,
                           "judge_rationale": out["rationale"]})

        # Periodic save
        if (i + 1) % 10 == 0 or i + 1 == n_total:
            output_path.write_text(json.dumps({
                "_meta": {
                    **(data.get("_meta", {})),
                    "judge_model": JUDGE_MODEL,
                    "scored_at": ts,
                    "n_scored": i + 1,
                    "score_duration_s": round(time.time() - t0, 1),
                },
                "results": scored,
            }, indent=2, ensure_ascii=False), encoding="utf-8")

    # Final aggregate
    valid_scores = [s for s in scored if s.get("judge_score") is not None]
    if valid_scores:
        mean_score = statistics.mean(s["judge_score"] for s in valid_scores)
        print(f"\n{'=' * 70}")
        print(f"FINAL SCORING")
        print(f"{'=' * 70}")
        print(f"Scored: {len(valid_scores)}/{len(scored)}")
        print(f"Mean score: {mean_score:.3f}")

        # Per shape
        by_shape: dict[str, list[float]] = {}
        for s in valid_scores:
            by_shape.setdefault(s["primary_type"], []).append(s["judge_score"])
        print(f"\n--- Per shape ---")
        for shape, scores in sorted(by_shape.items()):
            print(f"  {shape:<15} n={len(scores):3d}  mean={statistics.mean(scores):.3f}  "
                  f"perfect={sum(1 for x in scores if x == 1.0):3d}  "
                  f"zero={sum(1 for x in scores if x == 0.0):3d}")

        # Distribution
        dist = Counter(s["judge_score"] for s in valid_scores)
        print(f"\n--- Distribution ---")
        for k in (1.0, 0.5, 0.0):
            print(f"  {k} : {dist.get(k, 0):3d} ({100*dist.get(k, 0)/len(valid_scores):.0f}%)")

        # Baselines comparison
        print(f"\n--- vs baselines S0 v2 (gold_set_sap_v2 143q) ---")
        baselines = {
            "V5 v2 (POC initial)": 0.631,
            "Ceiling LLM v2": 0.606,
            "V5 POC v1 (30q hard)": 0.737,
            "V4.2 (30q hard)": 0.333,
            "EKX (30q hard)": 0.858,
        }
        print(f"  V5.1 (this run)       : {mean_score:.3f}")
        for name, score in baselines.items():
            delta = mean_score - score
            sign = "✅" if delta >= 0 else "❌"
            print(f"  {name:<22}: {score:.3f}  (Δ {delta:+.3f}) {sign}")

    print(f"\nWrote: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
