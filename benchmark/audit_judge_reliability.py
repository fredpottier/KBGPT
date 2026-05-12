"""
Audit fiabilité du juge LLM (Prometheus / Qwen-72B / autre).

Pour chaque task, échantillonne des cas variés (verdicts mixtes) et affiche
le quadruplet :
  Question
  Réponse OSMOSIS
  Ground Truth
  Verdict du juge

Permet d'identifier visuellement les jugements suspects (verdict incohérent
avec le contenu objectivement observable).
"""
import io
import json
import sys
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

JUDGMENTS_PATH = r"C:/Projects/SAP_KB/benchmark/results/judge_aero_v2_full_20260504_120105.json"
RESULTS_PATH = r"C:/Projects/SAP_KB/benchmark/results/aero_v2_full_20260504_120105.jsonl"
QUESTIONS_PATH = r"C:/Projects/SAP_KB/benchmark/questions/aero_all_290q.json"

# Charger
J = json.load(open(JUDGMENTS_PATH, encoding="utf-8"))
results = {}
with open(RESULTS_PATH, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        # le runner V2 utilise question_id (et task) — adaptons
        qid = r.get("question_id") or r.get("id")
        results[qid] = r
questions = {q["id"]: q for q in json.load(open(QUESTIONS_PATH, encoding="utf-8"))}

print(f"Loaded {len(J['judgments'])} judgments, {len(results)} results, {len(questions)} questions")
print(f"Judge metadata: {json.dumps(J['metadata'], indent=2, ensure_ascii=False)[:400]}")
print()


def display_case(jrec, idx_label=""):
    qid = jrec["question_id"]
    task = jrec["task"]
    judg = jrec.get("judgment") or {}
    err = jrec.get("error")
    q = questions.get(qid, {})
    r = results.get(qid, {})

    print(f"--- {idx_label} {qid} (task={task}) ---")
    print(f"QUESTION : {(q.get('question') or '')[:300]}")
    print()

    gt_keys = ["ground_truth_answer", "expected_answer", "expected_doc_id",
               "ground_truth_doc_id", "verbatim_quote",
               "claim_a", "claim_b", "expected_anchor", "expected_active_doc",
               "rejected_premise", "expected_no_hallucination", "chain"]
    print("GROUND TRUTH :")
    for k in gt_keys:
        v = q.get(k)
        if v:
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            print(f"  {k}: {str(v)[:300]}")
    print()

    ans = r.get("answer") or r.get("synthesized_answer") or ""
    docs = r.get("authoritative_doc_ids") or []
    print(f"REPONSE OSMOSIS : {ans[:400]}")
    print(f"AUTHORITATIVE DOC IDS : {docs[:5]}")
    print()

    if err:
        print(f"JUDGE ERROR : {err}")
    print(f"JUDGMENT :")
    for k, v in judg.items():
        if k == "reasoning":
            print(f"  {k}: {str(v)[:300]}")
        else:
            print(f"  {k}: {v}")
    print()


# Tableau d'analyse par task
by_task = defaultdict(list)
for j in J["judgments"]:
    by_task[j["task"]].append(j)

print("=" * 100)
print("DISTRIBUTION DES VERDICTS PAR TASK")
print("=" * 100)
for task, items in by_task.items():
    print(f"\n{task} (n={len(items)}):")
    # Compter combien ont judgment vide / error / non null
    n_err = sum(1 for j in items if j.get("error"))
    n_no_judg = sum(1 for j in items if not j.get("judgment"))
    n_with_judg = sum(1 for j in items if j.get("judgment"))
    print(f"  with_judgment: {n_with_judg} | no_judgment: {n_no_judg} | error: {n_err}")
    # Sample first valid judgment to show key set
    sample = next((j for j in items if j.get("judgment")), None)
    if sample:
        keys = list(sample["judgment"].keys())
        print(f"  judgment keys: {keys}")

print()
print("=" * 100)
print("ÉCHANTILLON DE CAS PAR TASK (3 par task : 1 verdict positif, 1 négatif, 1 surprenant)")
print("=" * 100)

for task in ["T1_provenance", "T2_contradictions", "T5_cross_doc",
            "T6_robustness", "T7_v2_anchor"]:
    items = by_task.get(task, [])
    if not items:
        continue

    print(f"\n\n###### TASK: {task} ######\n")

    # Cas 1 : verdict positif (answers_correctly=True OU factual=1.0)
    pos = [j for j in items if (j.get("judgment") or {}).get("answers_correctly") is True
           or (j.get("judgment") or {}).get("factual_correctness") == 1.0]
    if pos:
        display_case(pos[0], "[POS]")

    # Cas 2 : verdict négatif (answers_correctly=False)
    neg = [j for j in items if (j.get("judgment") or {}).get("answers_correctly") is False]
    if neg:
        display_case(neg[0], "[NEG]")

    # Cas 3 : tous champs à 0/False (judge potentiellement defective)
    zero = [j for j in items if all(
        (v is False or v == 0 or v == 0.0) for k, v in (j.get("judgment") or {}).items()
        if k != "reasoning" and isinstance(v, (bool, int, float))
    )]
    if zero:
        display_case(zero[0], "[ALL_ZERO]")
    elif neg:
        display_case(neg[-1], "[NEG_2]")
