"""Audit des confidences intent detection sur le bench P2 full."""
import json
from collections import Counter, defaultdict
from pathlib import Path

# On n'a pas les confidences explicitement dans le bench output (intent dict pas serialisé).
# Mais on a les traces JSONL — où elles devraient être.

trace_path = Path("/app/data/runtime_v4_2/traces/2026-05-10.jsonl")
if not trace_path.exists():
    print("No traces yet")
    raise SystemExit(0)

n_total = 0
by_layer = defaultdict(list)
by_op_misroute = defaultdict(list)

# On a aussi besoin du gold pour catégoriser
gold = {q["id"]: q for q in json.load(open("/app/benchmark/questions/aero_t6_robustness.json"))}

# Map question → gold (par texte exact)
gold_by_text = {q["question"]: q for q in gold.values()}

with trace_path.open(encoding="utf-8") as f:
    for line in f:
        try:
            t = json.loads(line)
        except Exception:
            continue
        n_total += 1
        layer = t.get("layer_used", "?")
        verifier = t.get("verifier_result") or {}
        v_dec = verifier.get("decision")
        v_conf = verifier.get("confidence")
        op = t.get("layer1_operator")
        gold_q = gold_by_text.get(t.get("question", ""))
        gold_cat = (gold_q or {}).get("category", "?")
        gold_behavior = (gold_q or {}).get("ground_truth", {}).get("expected_behavior", "?")

        if layer.startswith("layer1_"):
            entry = {
                "qid": (gold_q or {}).get("id", "?"),
                "category": gold_cat,
                "expected_behavior": gold_behavior,
                "operator": op,
                "verifier_decision": v_dec,
                "verifier_confidence": v_conf,
            }
            by_layer[layer].append(entry)

            # Détection misroute : opérateur trigger sur catégorie incompatible
            misroute_categories = {
                "layer1_lifecycle_resolution": {"false_premise", "unanswerable", "causal_why",
                                                "hypothetical", "set_list", "synthesis_large"},
                "layer1_kg_query": {"unanswerable", "false_premise", "causal_why", "hypothetical"},
                "layer1_temporal_active": {"hypothetical", "false_premise"},
                "layer1_set_reasoning": {"false_premise", "unanswerable"},
            }
            if gold_cat in misroute_categories.get(layer, set()):
                by_op_misroute[layer].append(entry)

print(f"Total traces: {n_total}\n")
for layer, entries in by_layer.items():
    print(f"\n=== {layer} ({len(entries)} triggered) ===")
    cats = Counter(e["category"] for e in entries)
    print(f"  By category: {dict(cats)}")
    confs = [e["verifier_confidence"] for e in entries if e["verifier_confidence"] is not None]
    if confs:
        print(f"  Verifier confidence : min={min(confs):.2f} median={sorted(confs)[len(confs)//2]:.2f} max={max(confs):.2f}")

print("\n=== Misroutes (operator vs incompatible category) ===")
for layer, entries in by_op_misroute.items():
    if entries:
        print(f"\n{layer} : {len(entries)} misroutes")
        for e in entries[:10]:
            print(f"  {e['qid']:25s} | cat={e['category']:18s} | exp={e['expected_behavior']:30s} | v_dec={e['verifier_decision']:10s} | v_conf={e['verifier_confidence']}")
