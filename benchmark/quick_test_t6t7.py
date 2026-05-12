"""Test ciblé : 3 T6 fausses prémisses + 3 T7 inférences."""
import io, json, sys, time, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

CASES = [
    ("T6 fausse prémisse #1", "Pourquoi le règlement (UE) 2021/821 interdit-il toute exportation de produits à double usage vers les pays tiers ?", "T6"),
    ("T6 fausse prémisse #2", "Pourquoi le règlement 2021/821 exige-t-il une autorisation pour tous les transferts de technologie sans exception ?", "T6"),
    ("T6 fausse prémisse #3", "Pourquoi le délai d'évaluation d'une transaction par les autorités EU est-il de 60 jours dans le règlement 2021/821 ?", "T6"),
    ("T7 inférence #1", "Quel règlement a remplacé le règlement (CE) n° 428/2009 du Conseil ?", "T7"),
    ("T7 inférence #2", "Quels actes délégués modifient l'Annex I du règlement (UE) 2021/821 ?", "T7"),
    ("T7 inférence #3", "Quelle est la version actuellement en vigueur du règlement EU sur les exportations de produits à double usage ?", "T7"),
]

for label, q, kind in CASES:
    print("=" * 100)
    print(f"## {label} ({kind})")
    print(f"Q: {q[:160]}")
    payload = {"question": q, "top_k_claims": 8}
    req = urllib.request.Request("http://localhost:8000/api/runtime_v2/answer",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"ERROR: {e}")
        continue
    el = round(time.time() - t0, 1)
    diag = d.get("diagnostic", {})
    pv = diag.get("premise_validator", {})
    fj = diag.get("faithfulness", {})
    skip = diag.get("faithfulness_regen_skip_reason")
    adopt = diag.get("faithfulness_regen_adopted_reason")
    print(f"  elapsed={el}s")
    print(f"  PREMISE: false_premise={pv.get('has_false_premise')} n={pv.get('n_presuppositions')}")
    for p in (pv.get("presuppositions") or []):
        print(f"    -> {p.get('verdict')} c={p.get('confidence')}")
    print(f"  FAITH: verdict={fj.get('verdict')} regen={fj.get('regenerated')}")
    if skip: print(f"  SKIP: {skip}")
    if adopt: print(f"  ADOPT: {adopt}")
    print(f"  ANSWER: {(d.get('synthesized_answer') or '')[:300]}")
    print()
