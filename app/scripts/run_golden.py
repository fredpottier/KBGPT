"""Runner de non-régression « golden » du runtime (chantier remédiation KeyPoint).

Pour chaque corpus × question : appelle /api/runtime_v6/answer, classe la réponse
(answer / abstain / debate) et compare à l'attendu. Sert de garde-fou à CHAQUE
étape (Étape 0 = snapshot baseline).

Classification :
  - abstain : 0 claim cité (le système s'est tu)
  - debate  : réponse contient l'appendice « Question débattue »
  - answer  : claims cités, pas d'appendice débat

Usage (dans le conteneur app) :
  python scripts/run_golden.py            # compare au comportement FINAL (expected)
  python scripts/run_golden.py --baseline # compare au baseline_expected si présent
  options : --corpus alcohol_health  --base http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

ABSTAIN_MARKERS = ("aucune information", "non couvert", "ne permet pas", "abstention",
                   "aspects non couverts", "reformuler")


def classify(resp: dict) -> str:
    text = (resp.get("answer_text") or "").lower()
    n_cit = len(resp.get("cited_claims") or [])
    if "débattue" in text or "debattue" in text:
        return "debate"
    if n_cit == 0:
        return "abstain"
    # filet : certaines abstentions citent 0 mais d'autres formulent un repli
    if any(m in text for m in ABSTAIN_MARKERS) and n_cit == 0:
        return "abstain"
    return "answer"


def ask(base: str, question: str, tenant: str, timeout: int = 200) -> dict:
    body = json.dumps({"question": question, "tenant_id": tenant}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/runtime_v6/answer", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--corpus", default="")
    ap.add_argument("--baseline", action="store_true",
                    help="comparer à baseline_expected (sinon expected final)")
    ap.add_argument("--file", default=os.path.join(os.path.dirname(__file__), "golden_questions.json"))
    args = ap.parse_args()

    data = json.load(open(args.file, encoding="utf-8"))
    corpora = data["corpora"]
    if args.corpus:
        corpora = {args.corpus: corpora[args.corpus]}

    total = ok = 0
    mismatches = []
    print(f"{'corpus':16} {'cat':28} {'exp':8} {'got':8} {'?':3} question")
    print("-" * 110)
    for cname, cfg in corpora.items():
        tenant = cfg["tenant_id"]
        for item in cfg["questions"]:
            exp = item.get("baseline_expected", item["expected"]) if args.baseline else item["expected"]
            try:
                resp = ask(args.base, item["q"], tenant)
                got = classify(resp)
            except Exception as e:
                got = f"ERR:{type(e).__name__}"
            total += 1
            good = (got == exp)
            if good:
                ok += 1
            else:
                mismatches.append((cname, item["cat"], item["q"], exp, got))
            flag = "OK" if good else "XX"
            print(f"{cname:16} {item['cat']:28} {exp:8} {str(got):8} {flag:3} {item['q'][:50]}")
            time.sleep(0.3)
    print("-" * 110)
    print(f"RESULT {ok}/{total} conformes ({'baseline' if args.baseline else 'final'})")
    if mismatches:
        print("MISMATCHES :")
        for m in mismatches:
            print(f"  [{m[0]}/{m[1]}] attendu={m[3]} obtenu={m[4]} — {m[2][:60]}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
