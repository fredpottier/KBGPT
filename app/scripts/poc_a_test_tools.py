"""POC-A — test rapide des Reading Tools sur la structure 2021/821."""
import sys, json
sys.path.insert(0, "/app/src")
from knowbase.runtime_v5.reading_tools import (
    outline, read, find_in, resolve_ref, expand_context, list_versions,
)

DOC = "dualuse_reg_2021_821_original_65eef5dc"

print("=== TEST 1: outline ===")
r = outline(DOC, max_sections=15)
for s in r["outline"]:
    print(f"  L{s['level']} | {s['numbering']:<15} | {s['title'][:50]}")
print()

print("=== TEST 2: read 'Article 5' ===")
r = read(DOC, "Article 5", max_chars=600)
if "error" not in r:
    print(f"  Found: {r['title']}")
    print(f"  Path: {r['section_path']}")
    print(f"  Text ({r['text_chars_total']} chars total):\n  {r['text'][:400]}...")
else:
    print(f"  ERROR: {r['error']}")
print()

print("=== TEST 3: read 'Article 12' (autorisations) ===")
r = read(DOC, "Article 12", max_chars=400)
if "error" not in r:
    print(f"  Found: {r['title']}")
    print(f"  Text snippet: {r['text'][:300]}...")
print()

print("=== TEST 4: find_in 'public domain' ===")
r = find_in(DOC, "public domain", max_results=3, snippet_chars=200)
print(f"  N hits: {r['n_hits']}")
for h in r["hits"]:
    print(f"  - L{h['level']} {h['numbering']:<15} | {h['title'][:40]}")
    print(f"    snippet: {h['snippet'][:200]}")
print()

print("=== TEST 5: resolve_ref 'Article 5(3)' ===")
r = resolve_ref(DOC, "Article 5(3)")
print(f"  Candidates searched: {r['candidates_searched']}")
print(f"  N matches: {r['n_matches']}")
for m in r["matches"]:
    print(f"  - {m['numbering']:<15} | {m['title'][:50]} | matched_on={m['matched_on']}")
print()

print("=== TEST 6: expand_context (around Article 5) ===")
r5 = read(DOC, "Article 5", max_chars=100)
if "section_id" in r5:
    r = expand_context(DOC, r5["section_id"], window=2)
    print(f"  Section: {r['section'].get('title', '')}")
    print(f"  Previous: {[s['title'][:30] for s in r['previous_siblings']]}")
    print(f"  Next: {[s['title'][:30] for s in r['next_siblings']]}")
print()

print("=== TEST 7: list_versions '2021/821' ===")
r = list_versions("2021/821")
if "error" in r:
    print(f"  ERROR: {r['error']}")
else:
    print(f"  N relations: {r['n_relations']}")
    for rel in r["relations"][:5]:
        print(f"  - {rel.get('source','')[:30]} -[{rel.get('rel_type','')}/{rel.get('lifecycle_type','')}]-> {rel.get('target','')[:30]}")
