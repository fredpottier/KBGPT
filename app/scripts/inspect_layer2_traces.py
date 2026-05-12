"""Inspecte les traces avec activité Layer 2."""
import json
from pathlib import Path

trace_path = Path("/app/data/runtime_v4_2/traces/2026-05-10.jsonl")
recent = []
with trace_path.open(encoding="utf-8") as f:
    for line in f:
        try:
            t = json.loads(line)
        except Exception:
            continue
        if t.get("layer2_iterations"):
            recent.append(t)

print(f"Total traces with layer2 activity: {len(recent)}")
for t in recent[-3:]:
    qid = t["question_id"]
    layer = t["layer_used"]
    iters = t.get("layer2_iterations")
    print(f"\n--- {qid} : layer={layer} iters={iters} ---")
    print(f"  Q: {t['question'][:140]}")
    print(f"  final answer: {(t.get('final_answer') or {}).get('answer_excerpt', '')[:200]}")
    for tc in (t.get("layer2_tool_calls") or [])[:8]:
        rs = tc.get("result_summary", "")[:120]
        print(f"    iter={tc['iteration']} {tc['tool_name']:30s} | {rs}")
