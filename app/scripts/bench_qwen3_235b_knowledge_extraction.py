#!/usr/bin/env python3
"""
Bench Qwen3-235B-A22B-Instruct-2507 vs Qwen2.5-72B-Instruct sur knowledge_extraction.

Sample N passages depuis Neo4j (Claims + verbatim source via unit_ids -> Passages),
rejoue l'extraction avec les 2 modèles via DeepInfra, compare.

Usage:
    docker compose exec app python scripts/bench_qwen3_235b_knowledge_extraction.py \
        --num-samples 15 --judge claude

Output:
    data/bench_qwen3_235b_<timestamp>.json
    Console summary
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
from typing import Any, Dict, List, Optional

import httpx

# Path bootstrap pour exécution directe
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bench_qwen3_235b")

DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"

MODEL_BASELINE = "Qwen/Qwen2.5-72B-Instruct"
MODEL_CHALLENGER = "Qwen/Qwen3-235B-A22B-Instruct-2507"

# Pricing DeepInfra (per million tokens)
PRICING = {
    "Qwen/Qwen2.5-72B-Instruct": {"in": 0.36, "out": 0.40},
    "Qwen/Qwen3-235B-A22B-Instruct-2507": {"in": 0.071, "out": 0.10},
}


def fetch_sample_passages(num_samples: int) -> List[Dict[str, Any]]:
    """Sample N passages depuis Neo4j via les Claims (qui portent passage_text en propriete).

    Schema observe : pas de node Passage materialise. Les claims ont les props
    passage_id, passage_text, doc_id directement. On groupe par passage_id pour
    reconstituer (text, doc_id, baseline_claims).
    """
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))

    with driver.session() as session:
        result = session.run(
            """
            MATCH (c:Claim)
            WHERE c.passage_text IS NOT NULL
              AND size(c.passage_text) >= 200
              AND size(c.passage_text) <= 2000
              AND c.doc_id IS NOT NULL
            WITH c.passage_id AS pid, c.passage_text AS text, c.doc_id AS doc_id,
                 collect({claim_text: c.text, claim_type: c.claim_type})[..8] AS baseline_claims,
                 count(c) AS n_claims
            WHERE n_claims >= 2 AND n_claims <= 10
            WITH pid, text, doc_id, baseline_claims, n_claims
            ORDER BY rand()
            LIMIT $n
            OPTIONAL MATCH (d:DocumentContext {doc_id: doc_id})
            RETURN text, pid, doc_id,
                   coalesce(d.primary_subject, doc_id, 'Unknown') AS doc_title,
                   coalesce(d.doc_type, 'pdf') AS doc_type,
                   '' AS section_title,
                   baseline_claims,
                   n_claims AS baseline_n
            """,
            n=num_samples,
        )
        rows = [dict(r) for r in result]
    driver.close()
    log.info(f"Sampled {len(rows)} passages from Neo4j")
    return rows


def build_minimal_prompt(passage_text: str, doc_title: str, doc_type: str, section_title: str) -> str:
    """Reproduit le prompt knowledge_extraction de claim_extractor.py (version simplifiée).

    Le passage entier est traité comme une unité unique U1 (suffisant pour le bench:
    on mesure la capacité d'extraction sur une portion significative de texte, pas
    la précision pointer/verbatim).
    """
    predicates_table = (
        "| Predicate | Description |\n|-----------|-------------|\n"
        "| USES | X explicitly uses Y |\n"
        "| REQUIRES | X needs Y to function |\n"
        "| BASED_ON | X is built on or runs on Y |\n"
        "| SUPPORTS | X supports or is designed for Y |\n"
        "| ENABLES | X makes possible a specific named capability Y |\n"
        "| PROVIDES | X provides, delivers, or offers Y |\n"
        "| EXTENDS | X extends or adds functionality to Y |\n"
        "| REPLACES | X replaces or succeeds Y |\n"
        "| PART_OF | X is a module or component of Y |\n"
        "| INTEGRATED_IN | X is integrated or embedded in Y |\n"
        "| COMPATIBLE_WITH | X works alongside Y |\n"
        "| CONFIGURES | X configures, manages, or controls Y |\n"
    )
    units_text = f"U1: {passage_text}"
    return f"""You are an expert in structured knowledge extraction from documents.

You receive numbered text units (U1, U2, etc.) from a document.
Your task is to identify CLAIMS — precise, documented assertions useful
for building a knowledge graph.

## Document context

Title: {doc_title}
Type: {doc_type}
Current section: {section_title or 'N/A'}

## Value grid (IMPORTANT)

**HIGH VALUE** — Relational claims between two named entities:
- X uses / is based on / requires Y
- X replaces / succeeds Y
- X is integrated in / embedded in Y
→ For these claims, fill the `structured_form` field.

**MEDIUM VALUE** — Specific factual claims with an identifiable subject:
- X offers a specific capability
- X has a specific limitation / constraint
→ `structured_form` = null

**DO NOT EXTRACT**:
- Fragments without a verb or identifiable subject
- Generic user actions
- Reformulations of section titles
- Legal texts, disclaimers, copyrights

## Claim types
FACTUAL, PRESCRIPTIVE, DEFINITIONAL, CONDITIONAL, PERMISSIVE, PROCEDURAL

## Response format (JSON)
{{"claims": [
  {{"claim_text": "...", "claim_type": "FACTUAL", "unit_id": "U1",
    "confidence": 0.9, "scope": {{"version": null, "region": null, "edition": null, "conditions": []}},
    "structured_form": {{"subject": "X", "predicate": "USES", "object": "Y"}}}}
]}}

## STRICT CONSTRAINT — structured_form predicates

{predicates_table}

- NEVER invent a predicate outside this list.
- If the relationship does not fit, set "structured_form": null.

## Units to analyze

{units_text}

Return ONLY a JSON object: {{"claims": [...]}}
No explanation, no markdown fences."""


def call_deepinfra(model: str, prompt: str, timeout: int = 120) -> Dict[str, Any]:
    """Appelle DeepInfra et retourne (response_text, latency_ms, in_tokens, out_tokens)."""
    headers = {"Authorization": f"Bearer {DEEPINFRA_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an expert in structured knowledge extraction."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }
    t0 = time.time()
    with httpx.Client(timeout=timeout) as client:
        r = client.post(DEEPINFRA_URL, headers=headers, json=payload)
    latency_ms = int((time.time() - t0) * 1000)
    r.raise_for_status()
    data = r.json()
    return {
        "text": data["choices"][0]["message"]["content"],
        "latency_ms": latency_ms,
        "in_tokens": data["usage"]["prompt_tokens"],
        "out_tokens": data["usage"]["completion_tokens"],
    }


def parse_claims(response_text: str) -> List[Dict[str, Any]]:
    """Parse la réponse JSON, robuste aux markdown fences."""
    txt = response_text.strip()
    if "```json" in txt:
        s = txt.find("```json") + 7
        e = txt.find("```", s)
        if e > s:
            txt = txt[s:e].strip()
    elif txt.startswith("```"):
        s = txt.find("```") + 3
        e = txt.rfind("```")
        if e > s:
            txt = txt[s:e].strip()
    try:
        obj = json.loads(txt)
    except json.JSONDecodeError:
        return []
    if isinstance(obj, dict):
        return obj.get("claims", [])
    if isinstance(obj, list):
        return obj
    return []


def validate_claim_schema(claim: Dict[str, Any]) -> bool:
    """Vérifie que le claim a les champs essentiels."""
    if not isinstance(claim, dict):
        return False
    if not claim.get("claim_text"):
        return False
    if not claim.get("claim_type"):
        return False
    sf = claim.get("structured_form")
    if sf is not None:
        if not isinstance(sf, dict):
            return False
        if sf.get("subject") and sf.get("predicate") and sf.get("object"):
            return True
        return False  # structured_form partiel = invalide
    return True


def cost_usd(model: str, in_t: int, out_t: int) -> float:
    p = PRICING[model]
    return (in_t * p["in"] + out_t * p["out"]) / 1_000_000


def judge_with_claude(passage_text: str, doc_title: str,
                       claims_baseline: List[Dict[str, Any]],
                       claims_challenger: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Appelle Claude pour comparer paire par paire les 2 extractions."""
    if not ANTHROPIC_API_KEY:
        return {"verdict": "SKIPPED", "reason": "ANTHROPIC_API_KEY missing"}
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    prompt = f"""You are evaluating two LLM extractions of CLAIMS from the same source passage.

## Source passage (from "{doc_title}")
{passage_text}

## Extraction A (baseline: Qwen2.5-72B)
{json.dumps(claims_baseline, ensure_ascii=False, indent=2)}

## Extraction B (challenger: Qwen3-235B-A22B-Instruct-2507)
{json.dumps(claims_challenger, ensure_ascii=False, indent=2)}

Evaluate on these axes (1-5 scale):
- coverage: how many genuine claims from the passage are captured
- precision: how few hallucinated/incorrect claims
- structured_form_quality: subject/predicate/object correctness when filled

Then verdict: A_BETTER | B_BETTER | EQUIVALENT (with one-sentence justification).

Return STRICT JSON: {{"A": {{"coverage": int, "precision": int, "structured_form_quality": int}}, "B": {{...}}, "verdict": "...", "justification": "..."}}"""

    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        with httpx.Client(timeout=90) as client:
            r = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        r.raise_for_status()
        text = r.json()["content"][0]["text"].strip()
        if "```json" in text:
            s = text.find("```json") + 7
            e = text.find("```", s)
            text = text[s:e].strip()
        return json.loads(text)
    except Exception as e:
        return {"verdict": "ERROR", "reason": str(e)}


def run_bench(num_samples: int, use_judge: bool, output_path: Path) -> Dict[str, Any]:
    samples = fetch_sample_passages(num_samples)
    if not samples:
        log.error("No passages sampled — KG empty or schema mismatch")
        return {}

    results: List[Dict[str, Any]] = []
    agg = {
        "baseline": {"calls": 0, "claims": 0, "valid_claims": 0, "structured_pct": 0.0,
                     "latency_ms_total": 0, "in_tok": 0, "out_tok": 0, "errors": 0},
        "challenger": {"calls": 0, "claims": 0, "valid_claims": 0, "structured_pct": 0.0,
                        "latency_ms_total": 0, "in_tok": 0, "out_tok": 0, "errors": 0},
    }

    for i, s in enumerate(samples):
        log.info(f"--- Sample {i+1}/{len(samples)} — {s['doc_title'][:60]} ---")
        prompt = build_minimal_prompt(
            passage_text=s["text"], doc_title=s["doc_title"],
            doc_type=s["doc_type"], section_title=s["section_title"],
        )

        sample_out: Dict[str, Any] = {
            "passage_id": s["pid"], "doc_title": s["doc_title"],
            "section_title": s["section_title"], "text_len": len(s["text"]),
            "kg_baseline_n_claims": s["baseline_n"],
        }

        for label, model in [("baseline", MODEL_BASELINE), ("challenger", MODEL_CHALLENGER)]:
            try:
                resp = call_deepinfra(model, prompt)
                claims = parse_claims(resp["text"])
                valid = sum(1 for c in claims if validate_claim_schema(c))
                struct = sum(1 for c in claims if c.get("structured_form"))
                struct_pct = (struct / len(claims) * 100) if claims else 0.0
                cost = cost_usd(model, resp["in_tokens"], resp["out_tokens"])

                sample_out[label] = {
                    "claims_count": len(claims), "valid_count": valid,
                    "structured_count": struct, "structured_pct": round(struct_pct, 1),
                    "latency_ms": resp["latency_ms"],
                    "in_tokens": resp["in_tokens"], "out_tokens": resp["out_tokens"],
                    "cost_usd": round(cost, 5), "claims": claims,
                }
                agg[label]["calls"] += 1
                agg[label]["claims"] += len(claims)
                agg[label]["valid_claims"] += valid
                agg[label]["latency_ms_total"] += resp["latency_ms"]
                agg[label]["in_tok"] += resp["in_tokens"]
                agg[label]["out_tok"] += resp["out_tokens"]
                log.info(f"  {label} ({model}): {len(claims)} claims ({valid} valid), "
                         f"{resp['latency_ms']}ms, ${cost:.5f}")
            except Exception as e:
                log.error(f"  {label} ERROR: {e}")
                sample_out[label] = {"error": str(e)}
                agg[label]["errors"] += 1

        if use_judge and "claims" in sample_out.get("baseline", {}) and "claims" in sample_out.get("challenger", {}):
            verdict = judge_with_claude(
                passage_text=s["text"], doc_title=s["doc_title"],
                claims_baseline=sample_out["baseline"]["claims"],
                claims_challenger=sample_out["challenger"]["claims"],
            )
            sample_out["judge"] = verdict
            log.info(f"  Judge: {verdict.get('verdict', 'N/A')}")

        results.append(sample_out)

    # Agrégats finaux
    summary = {}
    for label in ("baseline", "challenger"):
        a = agg[label]
        n = a["calls"] if a["calls"] else 1
        cost = cost_usd(MODEL_BASELINE if label == "baseline" else MODEL_CHALLENGER,
                        a["in_tok"], a["out_tok"])
        summary[label] = {
            "model": MODEL_BASELINE if label == "baseline" else MODEL_CHALLENGER,
            "calls": a["calls"], "errors": a["errors"],
            "claims_total": a["claims"], "valid_claims_total": a["valid_claims"],
            "claims_avg_per_passage": round(a["claims"] / n, 2),
            "latency_ms_avg": round(a["latency_ms_total"] / n, 0),
            "in_tokens_total": a["in_tok"], "out_tokens_total": a["out_tok"],
            "cost_usd_total": round(cost, 4),
            "cost_per_passage": round(cost / n, 5),
        }

    if use_judge:
        verdicts = [r["judge"]["verdict"] for r in results
                    if "judge" in r and "verdict" in r["judge"]]
        summary["judge_verdicts"] = {
            "A_BETTER": verdicts.count("A_BETTER"),
            "B_BETTER": verdicts.count("B_BETTER"),
            "EQUIVALENT": verdicts.count("EQUIVALENT"),
        }

    output = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "num_samples": num_samples, "models": {
            "baseline": MODEL_BASELINE, "challenger": MODEL_CHALLENGER,
        },
        "summary": summary, "samples": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Wrote {output_path}")
    return output


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--num-samples", type=int, default=15)
    p.add_argument("--judge", choices=["claude", "none"], default="claude")
    p.add_argument("--output", type=str, default="")
    args = p.parse_args()

    if not DEEPINFRA_API_KEY:
        log.error("DEEPINFRA_API_KEY missing")
        sys.exit(1)
    if args.judge == "claude" and not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY missing, judge will be skipped")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.output) if args.output else Path(f"data/bench_qwen3_235b_{ts}.json")

    output = run_bench(args.num_samples, args.judge == "claude", out_path)
    if not output:
        sys.exit(1)

    print("\n" + "=" * 70)
    print("BENCH SUMMARY")
    print("=" * 70)
    s = output["summary"]
    for label in ("baseline", "challenger"):
        d = s[label]
        print(f"\n{label.upper()} — {d['model']}")
        print(f"  calls={d['calls']} errors={d['errors']}")
        print(f"  claims_total={d['claims_total']} valid={d['valid_claims_total']} "
              f"avg/passage={d['claims_avg_per_passage']}")
        print(f"  latency_avg={d['latency_ms_avg']}ms")
        print(f"  tokens in={d['in_tokens_total']} out={d['out_tokens_total']}")
        print(f"  cost=${d['cost_usd_total']:.4f} (${d['cost_per_passage']:.5f}/passage)")
    if "judge_verdicts" in s:
        print(f"\nJudge: {s['judge_verdicts']}")
    print()
    if s["challenger"]["cost_usd_total"] > 0 and s["baseline"]["cost_usd_total"] > 0:
        savings = (1 - s["challenger"]["cost_usd_total"] / s["baseline"]["cost_usd_total"]) * 100
        print(f"Cost savings if migrate: {savings:+.1f}%")


if __name__ == "__main__":
    main()
