"""Charge les structures Document Structure depuis JSON local.

Format attendu (cf scripts/poc_a_build_structures.py) :
{
  "doc_id": "...",
  "n_pages": int,
  "sections": [
    {"section_id": "...", "level": int, "numbering": str, "title": str,
     "text": str, "parent_id": str|None, "children_ids": [str], "section_path": str}
  ],
  "root_section_ids": [...]
}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


DEFAULT_STRUCTURES_DIR = Path("/app/data/poc_a/structures")


class DocumentStructure:
    """Wrapper pour accès O(1) sur sections par id, numbering, ou path."""

    def __init__(self, data: dict):
        self.doc_id: str = data["doc_id"]
        self.n_pages: int = data.get("n_pages", 0)
        self.sections: list[dict] = data["sections"]
        self.root_section_ids: list[str] = data.get("root_section_ids", [])
        # Index O(1)
        self.by_id: dict[str, dict] = {s["section_id"]: s for s in self.sections}
        # Index par numbering normalisé
        self.by_numbering: dict[str, list[dict]] = {}
        for s in self.sections:
            num = (s.get("numbering") or "").strip()
            if num:
                self.by_numbering.setdefault(num.lower(), []).append(s)
        # Index par index dans la liste (pour navigation séquentielle)
        self.section_index: dict[str, int] = {
            s["section_id"]: i for i, s in enumerate(self.sections)
        }

    def find_by_path(self, section_path: str) -> Optional[dict]:
        """Cherche une section par section_path (exact ou par suffixe)."""
        path_clean = section_path.strip().rstrip("/").lower()
        if not path_clean.startswith("/"):
            path_clean = "/" + path_clean
        # Match exact d'abord
        for s in self.sections:
            if (s.get("section_path") or "").lower() == path_clean:
                return s
        # Match suffixe (ex. "/Article 5" matche "/CHAPTER II/Article 5")
        for s in self.sections:
            sp = (s.get("section_path") or "").lower()
            if sp.endswith(path_clean) or sp.endswith(path_clean.lstrip("/")):
                return s
        return None

    def find_by_numbering(self, numbering: str) -> list[dict]:
        return self.by_numbering.get(numbering.strip().lower(), [])

    def neighbors(self, section_id: str, window: int = 1) -> dict:
        idx = self.section_index.get(section_id)
        if idx is None:
            return {"previous": [], "next": []}
        previous = self.sections[max(0, idx - window):idx]
        nxt = self.sections[idx + 1:idx + 1 + window]
        return {"previous": previous, "next": nxt}


def load_structure(doc_id: str, base_dir: Optional[Path] = None) -> Optional[DocumentStructure]:
    base = base_dir or DEFAULT_STRUCTURES_DIR
    f = base / f"{doc_id}.json"
    if not f.exists():
        return None
    return DocumentStructure(json.load(open(f)))


def list_available_doc_ids(base_dir: Optional[Path] = None) -> list[str]:
    base = base_dir or DEFAULT_STRUCTURES_DIR
    if not base.exists():
        return []
    return sorted(p.stem for p in base.glob("*.json"))
