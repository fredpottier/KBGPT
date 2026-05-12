#!/usr/bin/env python3
"""Survey corpus pour extraire 1 paragraphe représentatif par doc."""
import json, glob, os, re

caches = sorted(glob.glob("/data/extraction_cache/*.v5cache.json"))
for c in caches:
    d = json.load(open(c))
    ext = d.get("extraction", {})
    doc_id = ext.get("document_id") or d.get("document_id", "?")
    ft = ext.get("full_text") or ""
    if not ft:
        print(f"== {doc_id} == EMPTY")
        continue
    # Première phrase substantielle (skip headers)
    paragraphs = re.split(r"\[PARAGRAPH\]", ft)
    sample_paras = [p.strip() for p in paragraphs if 100 < len(p.strip()) < 600][:3]
    print(f"\n== {doc_id} ==")
    print(f"   len_full_text={len(ft)}")
    for sp in sample_paras:
        sp = re.sub(r"\s+", " ", sp.replace("\n", " "))
        print(f"   • {sp[:300]}")
