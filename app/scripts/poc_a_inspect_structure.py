"""Inspecte la structure générée pour 2021/821."""
import json

d = json.load(open("/app/data/poc_a/structures/dualuse_reg_2021_821_original_65eef5dc.json"))
print(f"Doc: {d['doc_id']}")
print(f"N pages: {d['n_pages']}")
print(f"N sections: {len(d['sections'])}")
print(f"N roots: {len(d['root_section_ids'])}")
print()
levels = {}
for s in d["sections"]:
    levels[s["level"]] = levels.get(s["level"], 0) + 1
print(f"Level distribution: {dict(sorted(levels.items()))}")
print()
print("First 20 sections:")
for s in d["sections"][:20]:
    title = s["title"][:60]
    num = (s.get("numbering") or "")[:20]
    print(f"  L{s['level']} [{num:<20}] | {title}")

print("\nArticle-related sections:")
arts = [s for s in d["sections"] if "Article" in s.get("title", "")][:15]
for s in arts:
    title = s["title"][:60]
    num = (s.get("numbering") or "")[:20]
    txt_len = len(s.get("text", ""))
    print(f"  L{s['level']} [{num:<20}] | {title:<60} | text={txt_len}")

print("\nSection with longest text:")
top_text = sorted(d["sections"], key=lambda s: len(s.get("text", "")), reverse=True)[:3]
for s in top_text:
    print(f"  L{s['level']} | {s['title'][:60]} | text={len(s.get('text',''))}")

print("\nSample section_path (first 10):")
for s in d["sections"][:10]:
    print(f"  {s['section_path']}")
