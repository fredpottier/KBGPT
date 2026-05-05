"""
Audit qualitatif des échecs robustness :
- pour 5 questions failures (catégories variées),
- re-call l'API pour récupérer claims + answer + diagnostic complet,
- afficher le quadruplet question / GT / claims présentés / answer
- objectif : déterminer si claims contiennent l'info ou pas (oracle test).
"""
import io, json, sys, time, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPORT = json.load(open(r"C:/Projects/SAP_KB/app/data/benchmark/results/robustness_run_20260504_133914.json", encoding="utf-8"))
ps = REPORT["per_sample"]

# Sélection : 1 question failure par catégorie (score < 0.5), catégories prioritaires
PRIORITY_CATS = ["conditional", "lifecycle_filtering_active", "multi_hop", "causal_why",
                 "temporal_evolution", "set_list", "anchor_applicability_temporal"]

selected = []
for cat in PRIORITY_CATS:
    for s in ps:
        if s.get("category") == cat and (s.get("evaluation") or {}).get("score", 1.0) < 0.5:
            selected.append(s)
            break
    if len(selected) >= 5:
        break

print(f"Selected {len(selected)} failure samples for audit\n")

for i, s in enumerate(selected, 1):
    qid = s["question_id"]
    cat = s["category"]
    q = s["question"]
    saved_ans = s["answer"]
    score = s["evaluation"].get("score")
    judge_reason = s["evaluation"].get("judge_reason", "")[:200]

    print("=" * 100)
    print(f"### CASE {i}/{len(selected)} | category={cat} | score={score} | qid={qid}")
    print(f"Q: {q[:300]}")
    print()
    print(f"SAVED ANSWER (bench): {saved_ans[:300]}")
    print()
    print(f"JUDGE REASON: {judge_reason}")
    print()

    # Re-call API pour récupérer les claims + diagnostic complet
    payload = {"question": q, "top_k_claims": 8}
    req = urllib.request.Request("http://localhost:8000/api/runtime_v2/answer",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[CALL ERROR: {e}]\n")
        continue

    diag = d.get("diagnostic", {})
    print(f"FRESH ANSWER: {(d.get('synthesized_answer') or '')[:400]}")
    print()
    print(f"AUTHORITATIVE DOCS: {d.get('authoritative_doc_ids')}")
    pv = diag.get("premise_validator", {})
    if pv.get("presuppositions"):
        for p in pv["presuppositions"]:
            print(f"  PREMISE: {p.get('verdict')} c={p.get('confidence')} : {p.get('reasoning','')[:120]}")
    fj = diag.get("faithfulness", {})
    print(f"  FAITH: {fj.get('verdict')} score={fj.get('score')} regen={fj.get('regenerated')}")
    print()

    # AFFICHER LES CLAIMS PRESENTES AU SYNTHESIZER
    print("CLAIMS PRESENTED TO SYNTHESIZER (top 5):")
    for j, c in enumerate((d.get("claims") or [])[:5], 1):
        text = (c.get("text") or "").replace("\n", " ")
        print(f"  [{j}] doc={c.get('doc_id')} score={c.get('score'):.2f}")
        print(f"      {text[:300]}")
    print()

    time.sleep(0.5)
