"""
Test E2E pipeline runtime_v2 sur les 20 cas oracle.

Appelle le endpoint /api/runtime_v2/answer pour chaque question et compare
la réponse à l'expected. Verdict heuristique :
- OK : réponse contient au moins 1 search_term ET cite au moins 1 doc attendu
- PARTIAL : cite des docs mais pas les search_terms ; ou search_terms présents
  mais sans citation des bons docs
- ABSTENTION : la réponse contient des marqueurs d'abstention
- KO : ni search_terms ni docs corrects
"""
from __future__ import annotations

import sys
import time
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_cases import TEST_CASES  # noqa: E402

API_URL = "http://localhost:8000/api/runtime_v2/answer"

ABSTENTION_MARKERS = [
    "ne fournit pas", "ne contient pas", "n'est pas explicitement", "n'est pas mentionn",
    "ne mentionne pas", "ne précise pas", "n'est pas clair", "is not explicitly",
    "does not provide", "does not contain", "is not specified", "does not mention",
    "ne stipule pas", "n'aborde pas",
]


def call_pipeline(question: str, top_k: int = 10, timeout: float = 180.0) -> dict:
    body = json.dumps({"question": question, "top_k_claims": top_k}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    data["_latency_s"] = round(time.time() - t0, 2)
    return data


def classify(answer: str, search_terms: list[str], expected_docs: list[str]) -> str:
    al = (answer or "").lower()
    n_terms = sum(1 for t in search_terms if t.lower() in al)
    n_docs = sum(1 for d in expected_docs if d.lower() in al)
    is_abstention = any(m in al for m in ABSTENTION_MARKERS)
    if is_abstention:
        # Mais si abstention dit "info absente" alors qu'elle est dans le corpus → ABSTENTION_FAUX_NEG
        return "ABSTENTION"
    if n_terms >= 1 and n_docs >= 1:
        return "OK"
    if n_terms >= 1 or n_docs >= 1:
        return "PARTIAL"
    return "KO"


def main():
    results = []
    n_ok = n_partial = n_abst = n_ko = 0
    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/20] {tc['qid']}: {tc['question'][:80]}")
        try:
            d = call_pipeline(tc["question"])
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"qid": tc["qid"], "verdict": "ERROR", "error": str(e)})
            n_ko += 1
            continue

        ans = d.get("synthesized_answer") or ""
        verdict = classify(ans, tc["search_terms"], tc["doc_ids"])
        if verdict == "OK":
            n_ok += 1
        elif verdict == "PARTIAL":
            n_partial += 1
        elif verdict == "ABSTENTION":
            n_abst += 1
        else:
            n_ko += 1

        marker = {"OK": "✅", "PARTIAL": "⚠️", "ABSTENTION": "🚫", "KO": "❌"}[verdict]
        print(f"  {marker} [{verdict}] ({d.get('_latency_s')}s)")
        print(f"  Expected: {tc['expected'][:90]}")
        print(f"  Got:      {ans[:200]}")

        # Extract diagnostic key fields
        diag = d.get("diagnostic", {})
        faith = diag.get("faithfulness", {})
        results.append({
            "qid": tc["qid"],
            "verdict": verdict,
            "answer": ans[:500],
            "expected": tc["expected"],
            "latency_s": d.get("_latency_s"),
            "faith_verdict": faith.get("verdict"),
            "faith_score": faith.get("score"),
            "regenerated": faith.get("regenerated"),
            "regen_skip_reason": diag.get("faithfulness_regen_skip_reason"),
            "regen_adopted_reason": diag.get("faithfulness_regen_adopted_reason"),
            "n_kept_filter": diag.get("llm_filter", {}).get("n_kept"),
            "filter_fallback": diag.get("llm_filter", {}).get("fallback_reason"),
        })

    print()
    print("=" * 70)
    print(f"OK:         {n_ok:2d}/20 ({n_ok*5}%)")
    print(f"PARTIAL:    {n_partial:2d}/20 ({n_partial*5}%)")
    print(f"ABSTENTION: {n_abst:2d}/20 ({n_abst*5}%)")
    print(f"KO:         {n_ko:2d}/20 ({n_ko*5}%)")
    print()
    print(f"Score réussi (OK + 0.5*PARTIAL): {(n_ok + 0.5*n_partial)*5:.0f}%")
    print("=" * 70)

    out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "n_ok": n_ok, "n_partial": n_partial,
            "n_abstention": n_abst, "n_ko": n_ko,
            "score_estimate_pct": round((n_ok + 0.5*n_partial)*5, 1),
        },
        "per_case": results,
    }
    out_path = Path(__file__).parent / f"e2e_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Saved → {out_path}")


if __name__ == "__main__":
    main()
