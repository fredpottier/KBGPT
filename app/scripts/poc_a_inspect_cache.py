"""Inspecte la structure interne d'un cache v5 pour voir si la hiérarchie est exploitable."""
import json
from pathlib import Path

# Cache du règlement 2021/821
CACHE = "/data/extraction_cache/65eef5dc5c50bef3904411846a3ec981ac0331f8c321e093e2457683b422beca.v5cache.json"

# Petit cache pour itérer rapidement
CACHE_DEL_2024_2025 = None  # à trouver

cache_dir = Path("/data/extraction_cache")
files = sorted(cache_dir.glob("*.v5cache.json"))
print(f"=== Caches disponibles ({len(files)}) ===")
for f in files:
    size_mb = f.stat().st_size / 1024 / 1024
    print(f"  {f.name[:16]}...  {size_mb:.1f} MB")

print(f"\n=== Inspection {CACHE} ===")
c = json.load(open(CACHE))
print(f"Top-level keys: {list(c.keys())}")

doc_id = c.get("document_id")
print(f"document_id: {doc_id}")

ex = c.get("extraction", {})
print(f"\nextraction keys: {list(ex.keys())}")

# Structure
struct = ex.get("structure", {})
print(f"\nstructure keys: {list(struct.keys()) if isinstance(struct, dict) else type(struct).__name__}")
if isinstance(struct, dict):
    pages = struct.get("pages", [])
    metadata = struct.get("metadata", {})
    stats = struct.get("stats", {})
    print(f"  n_pages in structure: {len(pages) if isinstance(pages, list) else 'n/a'}")
    print(f"  metadata: {metadata}")
    print(f"  stats: {stats}")

    # Inspect first page
    if pages and isinstance(pages, list) and len(pages) > 0:
        p0 = pages[0]
        print(f"\n  pages[0] type: {type(p0).__name__}")
        if isinstance(p0, dict):
            print(f"  pages[0] keys: {list(p0.keys())}")
            # peek certain fields
            for k in ("text", "elements", "items", "blocks", "headings", "sections"):
                v = p0.get(k)
                if v is not None:
                    s = str(v)[:200] if not isinstance(v, list) else f"[list of {len(v)}]"
                    print(f"  pages[0].{k}: {s}")

# page_index
pi = ex.get("page_index")
print(f"\npage_index type: {type(pi).__name__}")
if isinstance(pi, list) and pi:
    print(f"  len: {len(pi)}")
    print(f"  [0] type: {type(pi[0]).__name__}")
    if isinstance(pi[0], dict):
        print(f"  [0] keys: {list(pi[0].keys())}")
        for k, v in list(pi[0].items())[:8]:
            s = str(v)[:120]
            print(f"    {k}: {s}")

# full_text
ft = ex.get("full_text", "")
print(f"\nfull_text length: {len(ft)}")
print(f"full_text[:300]: {ft[:300]}")

# Check if any headings are detected
import re
md_headings = re.findall(r"^#+\s+.+$", ft, re.MULTILINE)
print(f"\nMarkdown-style headings in full_text: {len(md_headings)}")
if md_headings:
    for h in md_headings[:10]:
        print(f"  {h[:80]}")
