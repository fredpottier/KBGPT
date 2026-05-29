"""Métrique déterministe exact_id_recall (anti-bruit juge LLM).

Pour chaque question factual, extrait les tokens-codes de ground_truth.exact_identifiers
(CG5Z, CBGLWB, /SAPAPO/OM13, P_RCF_STAT, 066, WWI...) et vérifie leur présence
(substring case-insensitive) dans answer_text. Reproductible, zéro LLM.

Usage : p3_eval_exact_id_recall.py <run.json> [<run2.json>]  → compare si 2 fichiers.
"""
from __future__ import annotations
import json
import re
import sys

GOLD = "benchmark/questions/gold_set_a38_50q.json"
CODE_RE = re.compile(r"[A-Z0-9/_]{3,}")  # tokens code-like (majuscules/chiffres/slash/underscore)
STOPCODES = {"SAP", "THE", "AND", "FOR", "WITH", "ARE", "NOT"}


def extract_codes(identifiers):
    codes = []
    for s in identifiers or []:
        for tok in CODE_RE.findall(s or ""):
            t = tok.strip("/_")
            if len(t) >= 3 and t.upper() not in STOPCODES and not t.isalpha() or (t.isupper() and len(t) >= 4):
                codes.append(tok)
    # dédup en préservant l'ordre
    seen = set(); out = []
    for c in codes:
        if c.lower() not in seen:
            seen.add(c.lower()); out.append(c)
    return out


def eval_run(path, gold_by_id):
    run = json.load(open(path))
    rows = []
    for x in run["results_50q"]:
        gt = gold_by_id.get(x["id"], {}).get("ground_truth", {})
        codes = extract_codes(gt.get("exact_identifiers"))
        if not codes:
            continue
        ans = (x["run"].get("answer_text") or "").lower()
        found = [c for c in codes if c.lower() in ans]
        recall = len(found) / len(codes)
        rows.append((x["id"], recall, len(found), len(codes), x["judge_score"],
                     x["question"][:40], codes, found))
    return rows


def main():
    gold = json.load(open(GOLD))
    gbid = {q["id"]: q for q in gold}
    files = sys.argv[1:]
    results = {}
    for f in files:
        rows = eval_run(f, gbid)
        mean = sum(r[1] for r in rows) / len(rows) if rows else 0
        results[f] = (mean, rows)
        print(f"\n=== {f.split('/')[-1]} : exact_id_recall mean={mean:.3f} (n={len(rows)}) | judge mean={sum(r[4] for r in rows)/len(rows):.3f} ===")
    if len(files) == 2:
        _, r1 = results[files[0]]; _, r2 = results[files[1]]
        d1 = {r[0]: r for r in r1}; d2 = {r[0]: r for r in r2}
        print(f"\n{'id':<20} {'rec1':>5} {'rec2':>5} {'j1':>4} {'j2':>4}  question")
        for qid in d1:
            a = d1[qid]; b = d2.get(qid)
            if not b:
                continue
            flag = "  <<id-DROP" if b[1] < a[1] else ("  ++id" if b[1] > a[1] else "")
            print(f"{qid:<20} {a[1]:>5.2f} {b[1]:>5.2f} {a[4]:>4} {b[4]:>4}  {a[5]}{flag}")


if __name__ == "__main__":
    main()
