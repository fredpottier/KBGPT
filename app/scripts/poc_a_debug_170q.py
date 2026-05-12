"""Debug : analyse des réponses Reading Agent pour comprendre la régression vs POC-A."""
import json
from collections import defaultdict

d = json.load(open("/app/data/benchmark/oracle_audit/poc_a_results_170q.json"))
qs = d["per_question"]

# Stats globales
print(f"Total questions: {len(qs)}\n")

# Compter réponses vides
empty = 0
short = 0  # < 50 chars
verbose = 0
for q in qs:
    a = q.get("agent_answer", "")
    if not a:
        empty += 1
    elif len(a) < 50:
        short += 1
    else:
        verbose += 1
print(f"Réponses vides : {empty}")
print(f"Réponses courtes (<50): {short}")
print(f"Réponses normales : {verbose}")

# Distribution par stopped_reason
stopped = defaultdict(int)
for q in qs:
    stopped[q.get("agent_stopped_reason", "unknown")] += 1
print(f"\nStopped reasons: {dict(stopped)}")

# Distribution n_iterations
iters = defaultdict(int)
for q in qs:
    iters[q.get("agent_n_iterations", 0)] += 1
print(f"N iterations distribution: {dict(sorted(iters.items()))}")

# Analyse par catégorie : score moyen + sample réponses
print("\n\n=== Sample par catégorie ===")
by_cat = defaultdict(list)
for q in qs:
    by_cat[q["category"]].append(q)

for cat in ["causal_why", "temporal_evolution", "multi_hop", "false_premise", "set_list", "conditional", "unanswerable"]:
    if cat not in by_cat:
        continue
    qs_cat = by_cat[cat]
    print(f"\n--- {cat} (n={len(qs_cat)}) ---")
    for q in qs_cat[:3]:
        a = q.get("agent_answer", "")
        ll = q.get("scores", {}).get("llama-3.3-70b", {}).get("score")
        n_iter = q.get("agent_n_iterations", 0)
        n_tools = q.get("agent_n_tool_calls", 0)
        tokens = q.get("agent_tokens_total", 0)
        stopped = q.get("agent_stopped_reason", "?")
        print(f"  {q['question_id']} | iter={n_iter} tools={n_tools} tokens={tokens} stopped={stopped} | Llama={ll}")
        print(f"    Q: {q['question'][:120]}")
        print(f"    A: {a[:200]}")
