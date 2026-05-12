"""POC-A jour 1 — test Docling sur 1 PDF pour voir le format DoclingDocument.

Convertit un PDF et explore l'API : items, headings, sections, hiérarchie.
"""
from docling.document_converter import DocumentConverter

PDF = "/data/docs_done/dualuse_del_2024_2025.pdf"  # le plus petit (1 MB) pour test rapide

converter = DocumentConverter()
print(f"Converting {PDF}...")
result = converter.convert(PDF)
doc = result.document

print(f"\n=== DoclingDocument ===")
print(f"Type: {type(doc).__name__}")
print(f"Attrs: {[a for a in dir(doc) if not a.startswith('_')][:30]}")
print(f"Name: {getattr(doc, 'name', None)}")
print(f"Pages: {len(doc.pages) if hasattr(doc, 'pages') else 'n/a'}")

print(f"\n=== Texts (top 10) ===")
texts = getattr(doc, "texts", []) or []
for i, t in enumerate(texts[:10]):
    label = getattr(t, "label", None)
    level = getattr(t, "level", None) or getattr(t, "label_level", None)
    text = getattr(t, "text", "")[:80]
    print(f"  [{i}] label={label} level={level} | {text}")

print(f"\n=== Total elements ===")
print(f"  texts: {len(texts)}")
print(f"  pictures: {len(getattr(doc, 'pictures', []) or [])}")
print(f"  tables: {len(getattr(doc, 'tables', []) or [])}")

# Tester export markdown structure
md = doc.export_to_markdown()
print(f"\n=== Markdown export (first 800 chars) ===")
print(md[:800])
print(f"...\n[total length: {len(md)}]")

# Tester recherche de headings
print(f"\n=== Headings detected ===")
headings = [t for t in texts if getattr(t, "label", None) in ("section_header", "title", "heading")]
print(f"  Total headings: {len(headings)}")
for h in headings[:10]:
    label = getattr(h, "label", None)
    level = getattr(h, "level", None)
    text = getattr(h, "text", "")[:60]
    print(f"    {label} L{level} | {text}")
