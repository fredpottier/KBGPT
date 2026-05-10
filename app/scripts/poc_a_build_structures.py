"""POC-A jour 1 — Build Document Structure pour les 5 PDFs cibles.

Pour chaque PDF :
  1. Convertit avec Docling
  2. Parse le markdown export pour reconstituer l'arbre des sections (niveaux #, ##, ###)
  3. Stocke la structure complète en JSON local

Format JSON output :
{
  "doc_id": "...",
  "doc_name": "...",
  "n_pages": int,
  "sections": [
    {
      "section_id": "...",         # hash unique
      "level": 1,                  # 1=top
      "numbering": "1" | "Article 5" | None,  # auto-détecté si présent dans titre
      "title": "...",
      "page_range": [start, end],
      "text": "...",               # texte concaténé entre headings
      "section_path": "/Article 1",  # chemin complet
      "children_ids": [...]
    }
  ],
  "by_id": {section_id: section_object},
  "root_section_ids": [...]        # sections de niveau 1
}
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path

OUT_DIR = Path("/app/data/poc_a/structures")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Mapping doc_id (KG) → fichier PDF
TARGET_DOCS = {
    "dualuse_reg_2021_821_original_65eef5dc": "/data/docs_done/dualuse_reg_2021_821_original.pdf",
    "cs25_amdt_22_8e69026c": "/data/docs_done/cs25_amdt_22.pdf",
    "cs25_amdt_23_0869bab2": "/data/docs_done/cs25_amdt_23.pdf",
    "cs25_amdt_28_32f1a9ac": "/data/docs_done/cs25_amdt_28.pdf",
    "dualuse_del_2023_996_3616a044": "/data/docs_done/dualuse_del_2023_996.pdf",
}


def section_hash(doc_id: str, level: int, title: str, page: int) -> str:
    h = hashlib.sha1(f"{doc_id}|{level}|{title}|{page}".encode("utf-8")).hexdigest()
    return f"sec_{h[:14]}"


def detect_numbering(title: str) -> str:
    """Détecte la numérotation au début du titre, agnostique du domaine."""
    title_clean = title.strip()
    patterns = [
        r"^(\d+(?:\.\d+)+)\b",       # 1.1, 1.2.3
        r"^(\d+)\b",                  # "5" simple
        r"^([A-Z][A-Za-z]*\s+\d+(?:\(\w+\))?)",  # "Article 5", "Article 5(3)"
        r"^(Annex(?:e)?\s+[IVX]+(?:\.\d+)*)",     # "Annex I", "Annex I.2"
        r"^(Chapter\s+[IVX]+(?:\.\d+)*)",          # "Chapter II"
        r"^(Section\s+[IVX]+(?:\.\d+)*)",
        r"^([\(\[]?\d+[\)\]])",                    # (1), [1]
    ]
    for pat in patterns:
        m = re.match(pat, title_clean)
        if m:
            return m.group(1)
    return ""


def parse_md_structure(md_text: str, doc_id: str, doc_pages: int) -> list:
    """Parse le markdown export pour reconstituer l'arbre des sections.

    Détecte les headings #, ##, ###, ... et accumule le texte entre eux.
    """
    lines = md_text.split("\n")
    sections = []
    current_section = None
    current_lines = []

    for line in lines:
        # Heading detection : 1 à 6 #
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            # Flush previous section
            if current_section is not None:
                current_section["text"] = "\n".join(current_lines).strip()
                sections.append(current_section)
            level = len(m.group(1))
            title = m.group(2).strip()
            numbering = detect_numbering(title)
            section_id = section_hash(doc_id, level, title, len(sections))
            current_section = {
                "section_id": section_id,
                "level": level,
                "numbering": numbering,
                "title": title,
                "text": "",
                "children_ids": [],
                "parent_id": None,
                "page_range": [None, None],
                "section_path": "",
            }
            current_lines = []
        else:
            current_lines.append(line)

    # Flush last
    if current_section is not None:
        current_section["text"] = "\n".join(current_lines).strip()
        sections.append(current_section)

    # Compute parent_id en parcourant : pour chaque section, parent = dernière section avec level < self.level
    parent_stack = []  # liste de (level, section_id)
    for sec in sections:
        # Pop tout ce qui est >= au level courant
        while parent_stack and parent_stack[-1][0] >= sec["level"]:
            parent_stack.pop()
        if parent_stack:
            parent_id = parent_stack[-1][1]
            sec["parent_id"] = parent_id
            # Append en children du parent
            for s in sections:
                if s["section_id"] == parent_id:
                    s["children_ids"].append(sec["section_id"])
                    break
        parent_stack.append((sec["level"], sec["section_id"]))

    # Compute section_path en remontant les parents
    by_id = {s["section_id"]: s for s in sections}
    for sec in sections:
        path_parts = []
        cur = sec
        while cur is not None:
            path_parts.append(cur["title"][:60])
            cur = by_id.get(cur["parent_id"]) if cur["parent_id"] else None
        path_parts.reverse()
        sec["section_path"] = "/" + "/".join(path_parts)

    return sections


def convert_pdf(doc_id: str, pdf_path: str) -> dict:
    from docling.document_converter import DocumentConverter
    converter = DocumentConverter()
    print(f"\n[{doc_id}]")
    print(f"  Converting {pdf_path}...")
    t0 = time.time()
    result = converter.convert(pdf_path)
    doc = result.document
    n_pages = len(doc.pages) if hasattr(doc, "pages") else 0
    md_text = doc.export_to_markdown()
    print(f"  Conversion done in {time.time()-t0:.0f}s. Pages={n_pages}, md_len={len(md_text)}")

    sections = parse_md_structure(md_text, doc_id, n_pages)
    print(f"  Extracted {len(sections)} sections")

    # Distribution levels
    levels = {}
    for s in sections:
        levels[s["level"]] = levels.get(s["level"], 0) + 1
    print(f"  Level distribution: {dict(sorted(levels.items()))}")

    # Index by id
    by_id = {s["section_id"]: s for s in sections}
    root_ids = [s["section_id"] for s in sections if s["parent_id"] is None]

    return {
        "doc_id": doc_id,
        "pdf_path": pdf_path,
        "n_pages": n_pages,
        "md_full": md_text,  # gardé pour debug
        "sections": sections,
        "root_section_ids": root_ids,
    }


def main():
    for doc_id, pdf_path in TARGET_DOCS.items():
        out_file = OUT_DIR / f"{doc_id}.json"
        if out_file.exists():
            print(f"[skip] {doc_id} déjà fait")
            continue
        try:
            structure = convert_pdf(doc_id, pdf_path)
            # Sauvegarde sans le md_full (trop gros) dans un fichier séparé
            md_full = structure.pop("md_full")
            (OUT_DIR / f"{doc_id}.md").write_text(md_full, encoding="utf-8")
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(structure, f, indent=2, ensure_ascii=False)
            print(f"  Saved → {out_file}")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    # Résumé
    print(f"\n=== RÉSUMÉ ===")
    for doc_id in TARGET_DOCS:
        f = OUT_DIR / f"{doc_id}.json"
        if f.exists():
            d = json.load(open(f))
            n_sec = len(d.get("sections", []))
            n_root = len(d.get("root_section_ids", []))
            print(f"  {doc_id:<50} : {n_sec} sections ({n_root} roots)")


if __name__ == "__main__":
    main()
