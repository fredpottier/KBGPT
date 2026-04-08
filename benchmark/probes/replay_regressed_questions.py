"""
Rejoue en live, via l'API OSMOSIS, une selection de questions qui ont
regresse sur Robustness entre PRE V17 et POST_PROMPT_B9.

Objectif : capturer la reponse COMPLETE (pas tronquee a 500 chars) et le
contexte retourne pour chaque question, afin de pouvoir analyser hors
ligne si le probleme est dans la forme (header parasite) ou dans le
contenu (retrieval/claims injectes).

Usage:
    docker exec knowbase-app python benchmark/probes/replay_regressed_questions.py

Sortie :
    data/benchmark/results/replay_regressed_YYYYMMDD_HHMMSS.json
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

API_BASE = os.getenv("OSMOSIS_API_URL", "http://localhost:8000")
PRE_PATH = "/app/data/benchmark/results/robustness_run_20260402_140940_V17_PREMISE_VERIF.json"
POST_B9_PATH = "/app/data/benchmark/results/robustness_run_20260408_121925_POST_PROMPT_B9.json"

CATEGORIES_TO_REPLAY = ("causal_why", "conditional", "temporal_evolution")
SCORE_DROP_THRESHOLD = 0.30  # regression d'au moins 30 points
MAX_QUESTIONS_PER_CATEGORY = 5  # suffisant pour voir les patterns


def get_token():
    r = requests.post(
        f"{API_BASE}/api/auth/login",
        json={"email": "admin@example.com", "password": "admin123"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def call_api(question, token):
    r = requests.post(
        f"{API_BASE}/api/search",
        json={
            "question": question,
            "use_graph_context": True,
            "graph_enrichment_level": "standard",
            "use_graph_first": True,
            "use_kg_traversal": True,
            "use_latest": True,
        },
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()


def main():
    pre = json.load(open(PRE_PATH))
    b9 = json.load(open(POST_B9_PATH))
    pre_by = {s["question_id"]: s for s in pre["per_sample"]}
    b9_by = {s["question_id"]: s for s in b9["per_sample"]}

    # Select worst regressions per category
    to_replay = []
    for cat in CATEGORIES_TO_REPLAY:
        cat_qs = [q for q in sorted(set(pre_by) & set(b9_by))
                  if pre_by[q].get("category") == cat]
        regressed = []
        for q in cat_qs:
            pr = pre_by[q].get("evaluation", {}).get("score")
            b9_ = b9_by[q].get("evaluation", {}).get("score")
            if pr is None or b9_ is None:
                continue
            if pr - b9_ >= SCORE_DROP_THRESHOLD:
                regressed.append((q, pr, b9_))
        regressed.sort(key=lambda x: x[2] - x[1])  # worst first
        to_replay.extend(regressed[:MAX_QUESTIONS_PER_CATEGORY])

    print(f"Selected {len(to_replay)} questions to replay ({len(CATEGORIES_TO_REPLAY)} categories x max {MAX_QUESTIONS_PER_CATEGORY})")

    token = get_token()
    print(f"Auth OK, starting replay...")

    results = []
    for i, (qid, pre_score, b9_score) in enumerate(to_replay, 1):
        question = pre_by[qid]["question"]
        print(f"\n[{i}/{len(to_replay)}] {qid} ({pre_by[qid].get('category','?')}) pre={pre_score:.2f} -> b9={b9_score:.2f}")
        print(f"  Q: {question[:110]}")
        try:
            t0 = time.time()
            data = call_api(question, token)
            elapsed = time.time() - t0

            # Extract key fields
            synthesis = data.get("synthesis", {})
            answer = synthesis.get("synthesized_answer", "") if isinstance(synthesis, dict) else ""

            search_results = data.get("results", [])
            chunks_text = [r.get("text", "")[:500] for r in search_results[:15]]
            sources = list({r.get("source_file", "") for r in search_results if r.get("source_file")})

            graph_context = data.get("graph_context", "") or ""
            mode = data.get("mode") or data.get("resolved_mode") or "?"

            print(f"  -> mode={mode}, answer_len={len(answer)}, chunks={len(search_results)}, sources={len(sources)}, elapsed={elapsed:.1f}s")
            print(f"  -> answer first line: {answer.lstrip().split(chr(10))[0][:110]}")

            results.append({
                "question_id": qid,
                "category": pre_by[qid].get("category"),
                "pre_score": pre_score,
                "b9_score": b9_score,
                "question": question,
                "pre_answer": pre_by[qid].get("answer", ""),  # truncated at 500 but starting point
                "pre_first_line": (pre_by[qid].get("answer", "") or "").lstrip().split("\n")[0][:200],
                "replay_answer": answer,
                "replay_answer_length": len(answer),
                "replay_mode": mode,
                "replay_sources": sources,
                "replay_chunks_count": len(search_results),
                "replay_chunks_preview": chunks_text,
                "replay_graph_context": graph_context[:3000],
                "replay_elapsed_s": round(elapsed, 1),
            })
        except Exception as e:
            print(f"  -> ERROR: {e}")
            results.append({
                "question_id": qid,
                "error": str(e),
            })

    # Save
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path("/app/data/benchmark/results") / f"replay_regressed_{ts}.json"
    out.write_text(json.dumps({"timestamp": ts, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] Saved to {out}")


if __name__ == "__main__":
    main()
