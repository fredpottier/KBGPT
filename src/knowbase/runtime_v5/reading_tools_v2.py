"""Reading Tools V2 — extension domain-agnostic (CH-52.4.4 / Sprint S3.4).

Ajoute 3 tools au POC initial :
- navigate_by_toc : existence check pour false_premise sur section nommée
- read_with_footnotes : lecture étendue avec footnotes structurelles
- find_cross_references : extrait + résout toutes les références internes d'une section

Charte domain-agnostic stricte (cf MEMORY) :
- Aucune référence à un domaine métier
- Heuristiques structurelles universelles uniquement
- Hints corpus-spécifiques → Domain Pack (hors scope ici)
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from knowbase.runtime_v5.reading_tools import (
    _section_summary,
    _trim,
    resolve_ref as _resolve_ref_handler,
)
from knowbase.runtime_v5.structure_loader import load_structure


# ─────────────────────────────────────────────────────────────────────────────
# Tool 8 — navigate_by_toc (existence check + suggestions)
# ─────────────────────────────────────────────────────────────────────────────


def navigate_by_toc(
    doc_id: str,
    target: str,
    max_suggestions: int = 5,
    similarity_threshold: float = 0.5,
) -> dict:
    """Vérifie qu'une section nommée existe dans le doc. Sinon, suggère des candidats proches.

    Use case ADR §3d : `false_premise` sur section nommée — l'utilisateur demande
    "What does section 25.A.42 say?" mais cette section n'existe pas. Au lieu de
    halluciner un contenu, l'agent appelle navigate_by_toc d'abord.

    Args:
        doc_id: identifiant document
        target: numbering ou title à chercher (ex: "3.2.1", "Annex I", "Getting Started")
        max_suggestions: nombre max de suggestions si non trouvé
        similarity_threshold: seuil minimal pour suggérer (0-1)

    Returns:
        {
          "doc_id": str,
          "target": str,
          "exists": bool,
          "matched_section": {section_id, title, numbering, ...} | None,
          "suggestions": [
            {section_id, title, numbering, similarity}
          ]
        }
    """
    struct = load_structure(doc_id)
    if struct is None:
        return {"error": f"Document {doc_id} not found", "exists": False}

    target_clean = (target or "").strip()
    if not target_clean:
        return {"doc_id": doc_id, "target": target,
                "exists": False, "suggestions": []}

    # Phase 1 : exact match par numbering
    matches = struct.find_by_numbering(target_clean)
    if matches:
        return {
            "doc_id": doc_id,
            "target": target_clean,
            "exists": True,
            "matched_section": _section_summary(matches[0], include_text=False),
            "suggestions": [],
            "match_type": "exact_numbering",
        }

    # Phase 2 : exact match par section_path
    by_path = struct.find_by_path(target_clean)
    if by_path:
        return {
            "doc_id": doc_id,
            "target": target_clean,
            "exists": True,
            "matched_section": _section_summary(by_path, include_text=False),
            "suggestions": [],
            "match_type": "exact_path",
        }

    # Phase 3 : exact substring dans title (case-insensitive)
    target_lower = target_clean.lower()
    title_matches = [
        s for s in struct.sections
        if target_lower in (s.get("title") or "").lower()
    ]
    if title_matches:
        return {
            "doc_id": doc_id,
            "target": target_clean,
            "exists": True,
            "matched_section": _section_summary(title_matches[0], include_text=False),
            "suggestions": [
                _section_summary(s, include_text=False)
                for s in title_matches[1:max_suggestions]
            ],
            "match_type": "title_substring",
        }

    # Phase 4 : pas d'exact match — fuzzy suggestions sur titles + numberings
    scored = []
    for s in struct.sections:
        title = (s.get("title") or "").lower()
        numbering = (s.get("numbering") or "").lower()
        score_title = SequenceMatcher(None, target_lower, title).ratio() if title else 0.0
        score_num = SequenceMatcher(None, target_lower, numbering).ratio() if numbering else 0.0
        best = max(score_title, score_num)
        if best >= similarity_threshold:
            scored.append((best, s))
    scored.sort(key=lambda x: x[0], reverse=True)

    suggestions = [
        {**_section_summary(s, include_text=False), "similarity": round(score, 3)}
        for score, s in scored[:max_suggestions]
    ]

    return {
        "doc_id": doc_id,
        "target": target_clean,
        "exists": False,
        "matched_section": None,
        "suggestions": suggestions,
        "match_type": "no_match",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 9 — read_with_footnotes (lecture + footnotes structurelles)
# ─────────────────────────────────────────────────────────────────────────────


def _detect_footnote_children(
    target: dict,
    struct,
    max_footnote_chars: int = 400,
) -> list[dict]:
    """Heuristique universelle pour détecter les footnotes structurelles.

    Une footnote = section enfant directe de `target` ET courte (< max_footnote_chars)
    ET sur la même page que le parent OU avec un marqueur de numérotation typique
    (`a)`, `(i)`, `*`, `note`, `footnote`).

    Domain-agnostic : aucune liste corpus-spécifique. On regarde uniquement la
    structure (level, page_range, longueur) et des patterns universels.

    Args:
        target: dict section parente
        struct: DocumentStructure
        max_footnote_chars: seuil de "courte"

    Returns:
        Liste des sections détectées comme footnotes (ordre du document)
    """
    target_page = (target.get("page_range") or [0, 0])[0]
    children_ids = target.get("children_ids") or []
    footnotes = []
    for cid in children_ids:
        child = struct.by_id.get(cid)
        if child is None:
            continue
        child_text = child.get("text") or ""
        if len(child_text) > max_footnote_chars:
            continue
        # Critère structurel : page proche du parent (±1)
        child_page = (child.get("page_range") or [0, 0])[0]
        if abs(child_page - target_page) > 1:
            continue
        footnotes.append(child)
    return footnotes


def read_with_footnotes(
    doc_id: str,
    section_path_or_numbering: str,
    max_chars: int = 8000,
    max_footnotes: int = 10,
) -> dict:
    """Lit le texte d'une section + identifie les footnotes structurellement liées.

    Use case ADR §3d : conditions/exceptions critiques (regulatory, médical,
    technique) où un footnote contient une nuance essentielle.

    Algorithme :
    1. Lit la section principale (logique read())
    2. Si la section a des enfants courts sur la même page → footnotes structurelles
    3. Retourne section + footnotes liées

    Args:
        doc_id: identifiant document
        section_path_or_numbering: chemin/numbering à lire
        max_chars: cap texte principal
        max_footnotes: limite N footnotes retournées

    Returns:
        {
          "section": {section_id, title, text, ...},
          "footnotes": [{section_id, title, text, ...}, ...],
          "n_footnotes": int
        }
    """
    struct = load_structure(doc_id)
    if struct is None:
        return {"error": f"Document {doc_id} not found"}

    target = struct.find_by_path(section_path_or_numbering)
    if target is None:
        matches = struct.find_by_numbering(section_path_or_numbering)
        if matches:
            target = matches[0]

    if target is None:
        q = section_path_or_numbering.lower().strip()
        candidates = [s for s in struct.sections if q in (s.get("title") or "").lower()]
        if candidates:
            target = candidates[0]

    if target is None:
        return {"error": f"Section '{section_path_or_numbering}' not found in {doc_id}"}

    text = target.get("text") or ""
    footnotes_raw = _detect_footnote_children(target, struct)[:max_footnotes]

    return {
        "section": {
            "section_id": target["section_id"],
            "level": target.get("level"),
            "numbering": target.get("numbering") or "",
            "title": target.get("title") or "",
            "section_path": target.get("section_path") or "",
            "text": _trim(text, max_chars),
            "text_chars_total": len(text),
        },
        "footnotes": [
            {
                "section_id": fn["section_id"],
                "level": fn.get("level"),
                "numbering": fn.get("numbering") or "",
                "title": fn.get("title") or "",
                "text": _trim(fn.get("text") or "", 1000),
            }
            for fn in footnotes_raw
        ],
        "n_footnotes": len(footnotes_raw),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 10 — find_cross_references (extrait + résout les "see §X.Y")
# ─────────────────────────────────────────────────────────────────────────────


# Patterns universels de cross-reference (charte domain-agnostic)
#   - "see 3.2" / "cf section 5" / "voir Annex I" / "see article 7(2)"
#   - "(see §X.Y)" / "[see §X.Y]"
#   - Numéros standalone après mot-clé universal : see, cf, voir, refer, vgl. (DE), véase (ES)
_REF_TRIGGER_WORDS = (
    r"see|cf|cf\.|refer\s+to|refers?\s+to|voir|vgl\.?|véase|vea|veasi"
)
# Match : "see 3.2", "voir Article 5", "cf section 7(2)"
_REF_PATTERN = re.compile(
    r"(?P<trigger>\b(?:" + _REF_TRIGGER_WORDS + r")\b)\s*"
    r"(?:(?P<keyword>\§|article|section|annex|chapter|paragraph|clause|appendix|table|figure)\s*)?"
    r"(?P<num>[IVX]{1,5}|\d+(?:\.\d+)+|\d+)"
    r"(?:\s*\((?P<sub>\w+)\))?",
    re.IGNORECASE,
)
# Match parenthèses : "(3.2)", "(see §5)", "[Annex I]"
_PAREN_REF_PATTERN = re.compile(
    r"[\(\[]\s*(?:(?P<trigger>see|cf|cf\.|voir|vgl\.?)\s+)?"
    r"(?:(?P<keyword>\§|article|section|annex|chapter|appendix|table|figure)\s*)?"
    r"(?P<num>[IVX]{1,5}|\d+(?:\.\d+)+|\d+)\s*[\)\]]",
    re.IGNORECASE,
)


def find_cross_references(
    doc_id: str,
    section_id: str,
    max_refs: int = 20,
    max_candidates_per_ref: int = 3,
) -> dict:
    """Extrait et résout toutes les références internes ("see §X.Y") d'une section.

    Patterns universels (domain-agnostic) :
    - "see 3.2" / "cf section 5" / "voir Annex I" / "vgl. §7"
    - "(3.2)" / "[Annex I]"

    Pour chaque référence extraite, tente resolve_ref pour obtenir les sections candidates.

    Args:
        doc_id: identifiant document
        section_id: section où chercher les références
        max_refs: limite N références extraites
        max_candidates_per_ref: limite candidats par référence résolue

    Returns:
        {
          "doc_id": str,
          "section_id": str,
          "n_refs_found": int,
          "references": [
            {
              "raw_text": "see Article 5(3)",
              "ref_offset": int,
              "candidates": [...]
            }
          ]
        }
    """
    struct = load_structure(doc_id)
    if struct is None:
        return {"error": f"Document {doc_id} not found"}

    target = struct.by_id.get(section_id)
    if target is None:
        return {"error": f"Section {section_id} not found"}

    text = target.get("text") or ""
    if not text:
        return {
            "doc_id": doc_id,
            "section_id": section_id,
            "n_refs_found": 0,
            "references": [],
        }

    # Extract all refs (deduplicated)
    seen = set()
    raw_refs = []
    for pat in (_REF_PATTERN, _PAREN_REF_PATTERN):
        for m in pat.finditer(text):
            raw = m.group(0).strip()
            key = (m.start(), raw.lower())
            if key in seen:
                continue
            seen.add(key)
            raw_refs.append({"raw_text": raw, "ref_offset": m.start()})
            if len(raw_refs) >= max_refs:
                break
        if len(raw_refs) >= max_refs:
            break

    # Sort by occurrence order
    raw_refs.sort(key=lambda r: r["ref_offset"])
    raw_refs = raw_refs[:max_refs]

    # Resolve each ref via resolve_ref existant
    references = []
    for ref in raw_refs:
        resolution = _resolve_ref_handler(doc_id, ref["raw_text"], section_id)
        candidates = resolution.get("matches", [])[:max_candidates_per_ref]
        references.append({
            "raw_text": ref["raw_text"],
            "ref_offset": ref["ref_offset"],
            "candidates_searched": resolution.get("candidates_searched", []),
            "n_candidates": len(candidates),
            "candidates": candidates,
        })

    return {
        "doc_id": doc_id,
        "section_id": section_id,
        "section_title": target.get("title") or "",
        "n_refs_found": len(references),
        "references": references,
    }
