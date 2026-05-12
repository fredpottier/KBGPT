"""Inspecte le contenu page.text_markdown des caches v5."""
import json

CACHE = "/data/extraction_cache/65eef5dc5c50bef3904411846a3ec981ac0331f8c321e093e2457683b422beca.v5cache.json"

c = json.load(open(CACHE))
pages = c["extraction"]["structure"]["pages"]

print(f"=== Inspection page.text_markdown sur {len(pages)} pages ===\n")

# Échantillon de pages
for i in [0, 1, 2, 3, 4, 10, 100]:
    if i >= len(pages):
        continue
    p = pages[i]
    md = p.get("text_markdown", "")
    print(f"--- Page {i} (text_markdown, {len(md)} chars) ---")
    print(md[:500])
    print()

# Compter les headings markdown dans toutes les pages
import re
total_headings_md = 0
heading_samples = []
for p in pages:
    md = p.get("text_markdown", "") or ""
    headings = re.findall(r"^(#{1,6})\s+(.+)$", md, re.MULTILINE)
    total_headings_md += len(headings)
    for h in headings[:3]:
        heading_samples.append((len(h[0]), h[1]))

print(f"\n=== Total ===")
print(f"Headings markdown détectés (toutes pages): {total_headings_md}")
print(f"\nSample headings:")
for level, title in heading_samples[:20]:
    print(f"  L{level} | {title[:80]}")

# text_json check
print(f"\n=== text_json sur 1 page ===")
tj = pages[0].get("text_json")
print(f"type: {type(tj).__name__}, len: {len(str(tj))}")
if isinstance(tj, list) and tj:
    print(f"[0] keys: {list(tj[0].keys()) if isinstance(tj[0], dict) else type(tj[0]).__name__}")
    print(f"[0]: {str(tj[0])[:300]}")
elif isinstance(tj, dict):
    print(f"keys: {list(tj.keys())}")
elif isinstance(tj, str):
    print(f"sample: {tj[:300]}")
