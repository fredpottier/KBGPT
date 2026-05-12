"""Build Document Structures for V5 Reading Agent from cached extractions.

Fallback when PDFs are not available locally : reads .v5cache.json and produces
a flat page-based structure (each page = section level 1, numbering = page #).

Output format matches what runtime_v5.structure_loader expects (see CH-51 doc).
Less granular than the Docling/markdown-headings version used for aerospace
(no heading hierarchy detection), but sufficient to test V5 on any corpus where
PDFs are gone but extraction caches are kept.

Corpus-agnostic : reads all caches in /data/extraction_cache regardless of
domain (SAP, regulatory, medical, etc.).
"""
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path

CACHE_DIR = Path("/data/extraction_cache")
OUT_DIR = Path("/data/poc_a/structures")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def section_hash(doc_id: str, page: int, idx: int) -> str:
    h = hashlib.sha1(f"{doc_id}|page{page}|p{idx}".encode("utf-8")).hexdigest()
    return f"sec_{h[:14]}"


def extract_title_from_page_text(text: str, max_len: int = 120) -> str:
    """Heuristique : premier paragraphe non-vide comme titre de la page."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return ""
    title = lines[0]
    if len(title) > max_len:
        title = title[:max_len].rsplit(" ", 1)[0] + "..."
    return title


def build_structure_from_cache(cache_path: Path) -> dict:
    """Parse one .v5cache.json and produce a Document Structure JSON."""
    with open(cache_path, encoding="utf-8") as f:
        cache = json.load(f)

    extraction = cache.get("extraction", {})
    doc_id = cache.get("document_id") or extraction.get("document_id")
    if not doc_id:
        raise ValueError(f"{cache_path}: no document_id")

    pages_data = extraction.get("structure", {}).get("pages", [])
    sections = []

    for page_idx, page in enumerate(pages_data):
        text = page.get("text_markdown") or ""
        if not text.strip():
            continue
        title = extract_title_from_page_text(text)
        sec_id = section_hash(doc_id, page_idx, 0)
        sections.append({
            "section_id": sec_id,
            "level": 1,
            "numbering": str(page_idx + 1),  # 1-indexed page number
            "title": title or f"Page {page_idx + 1}",
            "page_range": [page_idx, page_idx],
            "text": text,
            "section_path": f"/Page {page_idx + 1}",
            "parent_id": None,
            "children_ids": [],
        })

    structure = {
        "doc_id": doc_id,
        "doc_name": doc_id,
        "n_pages": len(pages_data),
        "sections": sections,
        "root_section_ids": [s["section_id"] for s in sections],
    }
    return structure


def main():
    caches = sorted(CACHE_DIR.glob("*.v5cache.json"))
    print(f"Found {len(caches)} cache files")

    written = 0
    skipped = 0
    errors = []
    for cache_path in caches:
        try:
            structure = build_structure_from_cache(cache_path)
            doc_id = structure["doc_id"]
            out = OUT_DIR / f"{doc_id}.json"
            if out.exists():
                # Skip if aerospace structure already there (don't overwrite the
                # high-quality Docling-headings version)
                # Detect by comparing : aerospace structures have hierarchical
                # levels (level > 1 exists). Page-based fallback always level=1.
                try:
                    existing = json.loads(out.read_text(encoding="utf-8"))
                    has_hierarchy = any(s.get("level", 1) > 1 for s in existing.get("sections", []))
                    if has_hierarchy:
                        print(f"  SKIP (better Docling version exists): {doc_id[:50]}")
                        skipped += 1
                        continue
                except Exception:
                    pass

            out.write_text(json.dumps(structure, indent=2, ensure_ascii=False), encoding="utf-8")
            written += 1
            print(f"  ✓ {doc_id[:60]}: {len(structure['sections'])} sections")
        except Exception as e:
            errors.append((str(cache_path), str(e)))
            print(f"  ✗ {cache_path.name}: {e}")

    print(f"\n✓ Done. Written: {written} | Skipped (hierarchy preserved): {skipped} | Errors: {len(errors)}")


if __name__ == "__main__":
    main()
