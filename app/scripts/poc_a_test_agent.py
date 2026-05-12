"""POC-A — test l'agent sur 1 question pour valider le pattern."""
import sys, json
sys.path.insert(0, "/app/src")

from knowbase.runtime_v5.reasoning_agent import run_agent

# Test sur q_0 (false_premise)
QUESTION = "Pourquoi le règlement (UE) 2021/821 interdit-il toute exportation de produits à double usage vers les pays tiers ?"

print(f"Question: {QUESTION}\n")
result = run_agent(QUESTION, max_iterations=6, verbose=True)

print(f"\n\n======== ANSWER ========")
print(result["answer"])

print(f"\n======== STATS ========")
print(f"  n_iterations: {result['n_iterations']}")
print(f"  stopped_reason: {result['stopped_reason']}")
print(f"  tokens_total: {result['tokens_total']}")
print(f"  n_tool_calls: {len(result['trace'])}")
print(f"  tool sequence: {[t['tool'] for t in result['trace']]}")
