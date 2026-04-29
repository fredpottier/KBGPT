#!/usr/bin/env python3
"""
Phase B / Test 2 — LLM Tier 4 sample sur 50 claims avec signal Tier 3.

Objectif : valider la qualité d'extraction temporelle par le LLM Qwen2.5-14B-Instruct-AWQ
sur des claims contenant un signal lexical (année 19xx-20xx OU mot-clé temporel).

Pour chaque claim, demander au LLM :
- publication_date (when was the rule published)
- validity_start / validity_end (when does the rule apply)
- confidence + reasoning

Output : rapport markdown avec stats + 10 exemples détaillés.

Usage : docker exec knowbase-app python /tmp/audit_phase_b_test2.py
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import httpx
from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

VLLM_URL = os.getenv("VLLM_URL", "http://18.199.218.46:8000")
VLLM_MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"

OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TS = datetime.now().strftime("%Y%m%d_%H%M%S")
MD_PATH = OUTPUT_DIR / f"audit_phase_b_test2_{TS}.md"
JSON_PATH = OUTPUT_DIR / f"audit_phase_b_test2_{TS}.json"

SAMPLE_SIZE = 50
MAX_PARALLEL = 10

PROMPT_SYSTEM = """You are a regulatory analyst extracting temporal information from regulatory text.

For the given passage, extract:
- publication_date: when this rule was published or last amended (YYYY format if uncertain, YYYY-MM-DD if precise)
- validity_start: when this rule started applying (or null if not stated)
- validity_end: when this rule stops applying (or null if still active or not stated)
- confidence: high / medium / low
- reasoning: short explanation citing specific words from the passage

Return ONLY valid JSON, no preamble. Use null for unknown fields.
Schema:
{
  "publication_date": "YYYY" or "YYYY-MM-DD" or null,
  "validity_start": "YYYY-MM-DD" or null,
  "validity_end": "YYYY-MM-DD" or null,
  "confidence": "high" | "medium" | "low",
  "reasoning": "..."
}"""


def extract_one(claim: dict) -> dict:
    """Call vLLM for one claim, return result dict."""
    user_prompt = f"""Passage (from {claim['doc_id']}):

{claim['passage_text']}

---
Claim text: {claim['claim_text']}

Extract temporal information."""

    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }

    t0 = time.time()
    try:
        r = httpx.post(f"{VLLM_URL}/v1/chat/completions", json=payload, timeout=60.0)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        elapsed = time.time() - t0

        # parse JSON output
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # try to find a JSON block
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group(0)) if m else {"_parse_error": True, "raw": content[:300]}

        return {
            "claim_id": claim["claim_id"],
            "doc_id": claim["doc_id"],
            "claim_text": claim["claim_text"][:200],
            "passage_excerpt": claim["passage_text"][:300],
            "result": parsed,
            "elapsed_s": elapsed,
            "tokens": usage,
        }
    except Exception as e:
        return {
            "claim_id": claim["claim_id"],
            "doc_id": claim["doc_id"],
            "claim_text": claim["claim_text"][:200],
            "_error": str(e),
            "elapsed_s": time.time() - t0,
        }


def main() -> None:
    print(f"Querying {SAMPLE_SIZE} claims with Tier 3 lexical signals...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as s:
        # Sample claims with temporal signal
        rows = s.run("""
            MATCH (c:Claim) WHERE c.tenant_id=$t AND c.passage_text IS NOT NULL
            WITH c,
              c.passage_text =~ '(?s).*(19|20)[0-9]{2}.*' AS has_year,
              c.passage_text =~ '(?si).*(effective|valid until|valid from|in force|enters into force|repealed|superseded|amended|amendment|revision).*' AS has_keyword
            WHERE has_year OR has_keyword
            WITH c, rand() AS r
            ORDER BY r
            LIMIT $n
            RETURN c.claim_id AS claim_id, c.doc_id AS doc_id, c.text AS claim_text, c.passage_text AS passage_text
        """, t=TENANT_ID, n=SAMPLE_SIZE).data()
    driver.close()

    print(f"  Got {len(rows)} claims")
    print(f"Running LLM Tier 4 on {VLLM_URL} (model: {VLLM_MODEL})...")
    print(f"  Parallel workers: {MAX_PARALLEL}")

    t_start = time.time()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
        futures = {ex.submit(extract_one, c): c for c in rows}
        completed = 0
        for f in as_completed(futures):
            results.append(f.result())
            completed += 1
            if completed % 10 == 0:
                print(f"  {completed}/{len(rows)} done ({time.time() - t_start:.1f}s)")

    elapsed_total = time.time() - t_start
    print(f"\nDone in {elapsed_total:.1f}s")

    # === Stats ===
    errors = [r for r in results if r.get("_error")]
    parse_errors = [r for r in results if r.get("result", {}).get("_parse_error")]
    valid = [r for r in results if not r.get("_error") and not r.get("result", {}).get("_parse_error")]

    # Distribution of confidence
    conf_dist = {"high": 0, "medium": 0, "low": 0, "missing": 0}
    pubdate_filled = 0
    validity_start_filled = 0
    validity_end_filled = 0
    for r in valid:
        res = r.get("result", {})
        c = res.get("confidence", "missing")
        if c not in conf_dist:
            c = "missing"
        conf_dist[c] += 1
        if res.get("publication_date"):
            pubdate_filled += 1
        if res.get("validity_start"):
            validity_start_filled += 1
        if res.get("validity_end"):
            validity_end_filled += 1

    avg_elapsed = sum(r.get("elapsed_s", 0) for r in results) / max(len(results), 1)
    total_input_tokens = sum((r.get("tokens", {}) or {}).get("prompt_tokens", 0) for r in results)
    total_output_tokens = sum((r.get("tokens", {}) or {}).get("completion_tokens", 0) for r in results)

    # === Output JSON ===
    JSON_PATH.write_text(json.dumps({
        "metadata": {"timestamp": TS, "sample_size": len(rows), "vllm_url": VLLM_URL, "model": VLLM_MODEL},
        "stats": {
            "total": len(results),
            "errors": len(errors),
            "parse_errors": len(parse_errors),
            "valid": len(valid),
            "confidence_distribution": conf_dist,
            "publication_date_filled": pubdate_filled,
            "validity_start_filled": validity_start_filled,
            "validity_end_filled": validity_end_filled,
            "elapsed_total_s": elapsed_total,
            "avg_elapsed_s": avg_elapsed,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
        },
        "results": results,
    }, indent=2, default=str), encoding="utf-8")

    # === Output Markdown ===
    md = [
        f"# Phase B / Test 2 — LLM Tier 4 sample ({SAMPLE_SIZE} claims) — {TS}",
        "",
        f"**vLLM endpoint** : `{VLLM_URL}` · **Model** : `{VLLM_MODEL}`",
        f"**Sample** : {len(rows)} claims with Tier 3 lexical signal · **Parallel** : {MAX_PARALLEL}",
        "",
        "## Stats globales",
        "",
        f"- Total processed : {len(results)}",
        f"- Valid responses : {len(valid)} ({len(valid)/len(results)*100:.0f}%)",
        f"- Errors (network/timeout) : {len(errors)}",
        f"- JSON parse errors : {len(parse_errors)}",
        f"- Total elapsed : {elapsed_total:.1f}s",
        f"- Avg per claim : {avg_elapsed:.2f}s",
        f"- Throughput : {len(results)/elapsed_total:.1f} claims/s",
        f"- **Estimation pour 3 401 claims Tier 3** : {3401/(len(results)/elapsed_total)/60:.1f} min",
        f"- Total input tokens : {total_input_tokens:,}",
        f"- Total output tokens : {total_output_tokens:,}",
        "",
        "## Coverage des champs extraits",
        "",
        f"- `publication_date` rempli : {pubdate_filled}/{len(valid)} ({pubdate_filled/max(len(valid),1)*100:.0f}%)",
        f"- `validity_start` rempli : {validity_start_filled}/{len(valid)} ({validity_start_filled/max(len(valid),1)*100:.0f}%)",
        f"- `validity_end` rempli : {validity_end_filled}/{len(valid)} ({validity_end_filled/max(len(valid),1)*100:.0f}%)",
        "",
        "## Distribution confidence",
        "",
        "| Niveau | Count | % |",
        "|---|---:|---:|",
    ]
    for k in ["high", "medium", "low", "missing"]:
        v = conf_dist[k]
        md.append(f"| {k} | {v} | {v/max(len(valid),1)*100:.0f}% |")
    md.append("")

    # 10 examples (mix high/medium/low)
    md.append("## 10 exemples détaillés")
    md.append("")
    examples = []
    for level in ["high", "medium", "low"]:
        for r in valid:
            if r.get("result", {}).get("confidence") == level and len([e for e in examples if e.get("result", {}).get("confidence") == level]) < 4:
                examples.append(r)
        if len(examples) >= 10:
            break
    for i, r in enumerate(examples[:10], 1):
        res = r.get("result", {})
        md.append(f"### Exemple {i} — confidence: {res.get('confidence', 'N/A')}")
        md.append(f"- **doc_id** : `{r['doc_id']}`")
        md.append(f"- **claim** : {r['claim_text']}")
        md.append(f"- **passage excerpt** : {r['passage_excerpt'][:200]}…")
        md.append(f"- **Output LLM** :")
        md.append("  ```json")
        md.append("  " + json.dumps(res, ensure_ascii=False, indent=2).replace("\n", "\n  "))
        md.append("  ```")
        md.append("")

    # Errors si any
    if errors:
        md.append("## Erreurs")
        md.append("")
        for r in errors[:5]:
            md.append(f"- `{r['claim_id']}` : {r.get('_error', 'unknown')[:200]}")
        md.append("")

    # Synthèse
    md.append("## Synthèse")
    md.append("")
    valid_pct = len(valid) / len(results) * 100
    pubdate_pct = pubdate_filled / max(len(valid), 1) * 100
    if valid_pct >= 90 and pubdate_pct >= 50:
        md.append(f"✅ **Verdict** : Tier 4 LLM viable. {valid_pct:.0f}% de réponses valides, {pubdate_pct:.0f}% avec publication_date extraite. Coût estimé pour 3 401 claims : ~{3401*avg_elapsed/MAX_PARALLEL/60:.0f} min EC2 vLLM (parallel 10).")
    elif valid_pct >= 75:
        md.append(f"⚠️ **Verdict** : Tier 4 fonctionne mais qualité moyenne ({pubdate_pct:.0f}% publication_date). À ajuster prompt + temperature.")
    else:
        md.append(f"❌ **Verdict** : Tier 4 insuffisant ({valid_pct:.0f}% valides). Vérifier prompt, modèle, ou stratégie.")
    md.append("")

    MD_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"\n✅ Report: {MD_PATH}")
    print(f"  Valid: {len(valid)}/{len(results)}")
    print(f"  Pub date filled: {pubdate_filled}/{len(valid)}")
    print(f"  Throughput: {len(results)/elapsed_total:.1f} claims/s")
    print(f"  Estimated for 3401 claims: {3401/(len(results)/elapsed_total)/60:.1f} min")


if __name__ == "__main__":
    main()
