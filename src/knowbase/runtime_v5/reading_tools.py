"""Reading Tools générique — POC CH-51 (domain-agnostic strict).

7 outils universels pour navigation documentaire. Aucun vocabulaire métier
(pas de "amendment", "exception", "premise"...). Utilisable sur tout corpus
structuré (aerospace, SAP, médical, technique).

Tous les tools sont stateless et exposent une signature simple, conçue pour
être appelable via tool use LLM.
"""
from __future__ import annotations

import re
from difflib import unified_diff
from typing import Optional

from knowbase.runtime_v5.structure_loader import (
    DocumentStructure,
    load_structure,
    list_available_doc_ids,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _trim(text: str, max_chars: int = 5000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[... TRUNCATED, total {len(text)} chars ...]"


def _section_summary(s: dict, include_text: bool = False) -> dict:
    out = {
        "section_id": s["section_id"],
        "level": s.get("level"),
        "numbering": s.get("numbering") or "",
        "title": s.get("title") or "",
        "section_path": s.get("section_path") or "",
        "text_chars": len(s.get("text") or ""),
    }
    if include_text:
        out["text"] = _trim(s.get("text") or "", 5000)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1 — outline
# ─────────────────────────────────────────────────────────────────────────────

def outline(doc_id: str, max_sections: int = 80, min_text_chars: int = 0) -> dict:
    """Retourne la table des matières structurée du document.

    Args:
        doc_id: identifiant document (sans extension)
        max_sections: limite de sections retournées (priorise sections substantielles)
        min_text_chars: filtre les sections avec moins de N chars de texte

    Returns:
        {
          "doc_id": str,
          "n_pages": int,
          "n_sections_total": int,
          "outline": [
             {section_id, level, numbering, title, section_path, text_chars}
          ]
        }
    """
    struct = load_structure(doc_id)
    if struct is None:
        return {"error": f"Document {doc_id} not found", "available": list_available_doc_ids()}

    candidates = [
        s for s in struct.sections
        if len(s.get("text") or "") >= min_text_chars
    ]
    # Si trop de sections, priorise celles avec numbering détecté ou texte substantiel
    if len(candidates) > max_sections:
        scored = sorted(
            candidates,
            key=lambda s: (
                bool(s.get("numbering")),  # avec numbering en priorité
                len(s.get("text") or ""),  # texte substantiel ensuite
            ),
            reverse=True,
        )
        candidates = scored[:max_sections]
        # Re-trier par index original pour préserver l'ordre de lecture
        candidates.sort(key=lambda s: struct.section_index.get(s["section_id"], 0))

    return {
        "doc_id": struct.doc_id,
        "n_pages": struct.n_pages,
        "n_sections_total": len(struct.sections),
        "outline": [_section_summary(s) for s in candidates],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2 — read
# ─────────────────────────────────────────────────────────────────────────────

def read(doc_id: str, section_path_or_numbering: str, max_chars: int = 8000) -> dict:
    """Lit le texte intégral d'une section.

    Args:
        doc_id: identifiant document
        section_path_or_numbering: chemin "/X/Y" OU numbering ("Article 5", "3.2.1", "Annex I")
        max_chars: cap sur la taille du texte retourné

    Returns:
        {section_id, level, numbering, title, section_path, text, text_chars_total}
    """
    struct = load_structure(doc_id)
    if struct is None:
        return {"error": f"Document {doc_id} not found"}

    target = struct.find_by_path(section_path_or_numbering)
    if target is None:
        # Try by numbering
        matches = struct.find_by_numbering(section_path_or_numbering)
        if matches:
            target = matches[0]

    if target is None:
        # Fuzzy match : substring dans titre
        q = section_path_or_numbering.lower().strip()
        candidates = [s for s in struct.sections if q in (s.get("title") or "").lower()]
        if candidates:
            target = candidates[0]

    if target is None:
        return {"error": f"Section '{section_path_or_numbering}' not found in {doc_id}",
                "hint": "use outline(doc_id) to see available sections"}

    text = target.get("text") or ""
    return {
        "section_id": target["section_id"],
        "level": target.get("level"),
        "numbering": target.get("numbering") or "",
        "title": target.get("title") or "",
        "section_path": target.get("section_path") or "",
        "text": _trim(text, max_chars),
        "text_chars_total": len(text),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3 — find_in
# ─────────────────────────────────────────────────────────────────────────────

def find_in(doc_id: str, query: str, max_results: int = 10, snippet_chars: int = 400) -> dict:
    """Recherche string/regex dans un document spécifique. Retourne sections + extraits.

    Args:
        doc_id: identifiant document
        query: chaîne ou regex (case-insensitive)
        max_results: nombre max de sections retournées
        snippet_chars: taille de l'extrait autour du match
    """
    struct = load_structure(doc_id)
    if struct is None:
        return {"error": f"Document {doc_id} not found"}

    try:
        pat = re.compile(query, re.IGNORECASE)
    except re.error:
        # Si pas un regex valide, treat as literal
        pat = re.compile(re.escape(query), re.IGNORECASE)

    hits = []
    for s in struct.sections:
        text = s.get("text") or ""
        m = pat.search(text)
        if m:
            start = max(0, m.start() - snippet_chars // 2)
            end = min(len(text), m.end() + snippet_chars // 2)
            snippet = text[start:end]
            hits.append({
                **_section_summary(s),
                "match_offset": m.start(),
                "snippet": snippet,
            })
        if len(hits) >= max_results:
            break

    return {
        "doc_id": doc_id,
        "query": query,
        "n_hits": len(hits),
        "hits": hits,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 4 — resolve_ref
# ─────────────────────────────────────────────────────────────────────────────

def resolve_ref(doc_id: str, ref_text: str, current_section_id: Optional[str] = None) -> dict:
    """Résout une référence interne (ex: "see Article 5(3)", "cf section 3.2", "voir paragraphe 7").

    Patterns universels :
      - numérotation explicite : "5(3)", "3.2.1", "1.1"
      - "Article N", "Section N", "Annex N", "Chapter N" (génériques, applicables à
        tout corpus avec sections numérotées par mot+nombre)
      - "(N)" ou "[N]" en sous-numérotation
    """
    struct = load_structure(doc_id)
    if struct is None:
        return {"error": f"Document {doc_id} not found"}

    ref_clean = ref_text.strip()

    # Patterns multiples (ordre = priorité)
    candidates_num = []
    # 1) Numérotation pure : 3.2.1, 5
    m = re.search(r"\b(\d+(?:\.\d+)+|\d+)\b", ref_clean)
    if m:
        candidates_num.append(m.group(1))
    # 2) Mot + nombre : "Article 5", "Section 3", "Annex I", "Chapter 2"
    m = re.search(r"\b([A-Z][A-Za-zé]*)\s+(\d+|[IVXLCDM]+)\b", ref_clean)
    if m:
        candidates_num.append(f"{m.group(1)} {m.group(2)}")
    # 3) "5(3)" pattern
    m = re.search(r"\b(\d+)\s*\(([\w]+)\)", ref_clean)
    if m:
        candidates_num.append(f"{m.group(1)}({m.group(2)})")

    matches = []
    for cand in candidates_num:
        m = struct.find_by_numbering(cand)
        for sec in m:
            matches.append({
                **_section_summary(sec, include_text=False),
                "matched_on": cand,
            })

    return {
        "doc_id": doc_id,
        "ref_text": ref_text,
        "candidates_searched": candidates_num,
        "n_matches": len(matches),
        "matches": matches[:5],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 5 — expand_context
# ─────────────────────────────────────────────────────────────────────────────

def expand_context(doc_id: str, section_id: str, window: int = 2) -> dict:
    """Retourne le contexte structurel autour d'une section :
    parent (si dispo), voisins (window précédent/suivant), enfants directs.
    """
    struct = load_structure(doc_id)
    if struct is None:
        return {"error": f"Document {doc_id} not found"}

    target = struct.by_id.get(section_id)
    if target is None:
        return {"error": f"Section {section_id} not found"}

    parent = struct.by_id.get(target.get("parent_id")) if target.get("parent_id") else None
    children = [struct.by_id[cid] for cid in target.get("children_ids", []) if cid in struct.by_id]
    nb = struct.neighbors(section_id, window=window)

    return {
        "doc_id": doc_id,
        "section": _section_summary(target, include_text=False),
        "parent": _section_summary(parent, include_text=False) if parent else None,
        "previous_siblings": [_section_summary(s) for s in nb["previous"]],
        "next_siblings": [_section_summary(s) for s in nb["next"]],
        "children": [_section_summary(c) for c in children[:10]],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 6 — compare_sections
# ─────────────────────────────────────────────────────────────────────────────

def compare_sections(
    doc_a: str, section_a_ref: str,
    doc_b: str, section_b_ref: str,
    max_chars: int = 4000,
) -> dict:
    """Compare le texte de deux sections (potentiellement de docs différents).
    Retourne diff structuré + textes côte à côte.
    """
    res_a = read(doc_a, section_a_ref, max_chars=max_chars)
    res_b = read(doc_b, section_b_ref, max_chars=max_chars)
    if "error" in res_a or "error" in res_b:
        return {"error": "one or both sections not found",
                "section_a_result": res_a, "section_b_result": res_b}

    # Diff naïf line-based
    a_lines = (res_a["text"] or "").splitlines()
    b_lines = (res_b["text"] or "").splitlines()
    diff = list(unified_diff(a_lines, b_lines,
                              fromfile=f"{doc_a}/{section_a_ref}",
                              tofile=f"{doc_b}/{section_b_ref}",
                              lineterm="", n=2))[:200]

    return {
        "section_a": {"doc_id": doc_a, "title": res_a["title"], "text": res_a["text"]},
        "section_b": {"doc_id": doc_b, "title": res_b["title"], "text": res_b["text"]},
        "unified_diff": "\n".join(diff),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool 7 — list_versions (utilise KG existant LIFECYCLE_RELATION)
# ─────────────────────────────────────────────────────────────────────────────

def list_versions(doc_subject: str, tenant_id: str = "default") -> dict:
    """Retourne la chaîne de versions/évolutions d'un sujet documentaire,
    via les relations LIFECYCLE_RELATION du KG (SUPERSEDES, EVOLVES_FROM, etc.).

    Domain-agnostic : ces relations existent pour tout corpus versionné
    (releases SAP, amendements réglementaires, révisions médicales, etc.).
    """
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return {"error": "neo4j driver not available"}

    driver = GraphDatabase.driver("bolt://neo4j:7687", auth=("neo4j", "graphiti_neo4j_pass"))
    try:
        with driver.session() as s:
            # Cherche tous les Documents/DocumentContexts liés par LIFECYCLE_RELATION
            # impliquant doc_subject (substring sur doc_id ou title)
            q = """
            MATCH (a)-[r:LIFECYCLE_RELATION]->(b)
            WHERE a.tenant_id = $tid AND b.tenant_id = $tid
              AND (
                toLower(coalesce(a.doc_id, a.id, '')) CONTAINS toLower($sub)
                OR toLower(coalesce(b.doc_id, b.id, '')) CONTAINS toLower($sub)
                OR toLower(coalesce(a.subject, '')) CONTAINS toLower($sub)
                OR toLower(coalesce(b.subject, '')) CONTAINS toLower($sub)
              )
            RETURN
              coalesce(a.doc_id, a.id) AS source,
              type(r) AS rel_type,
              r.lifecycle_type AS lifecycle_type,
              coalesce(b.doc_id, b.id) AS target,
              r.published_at AS published_at
            LIMIT 30
            """
            rows = s.run(q, tid=tenant_id, sub=doc_subject).data()
            return {
                "doc_subject": doc_subject,
                "n_relations": len(rows),
                "relations": rows,
            }
    finally:
        driver.close()


# ─────────────────────────────────────────────────────────────────────────────
# Tool registry pour l'agent
# ─────────────────────────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "outline": outline,
    "read": read,
    "find_in": find_in,
    "resolve_ref": resolve_ref,
    "expand_context": expand_context,
    "compare_sections": compare_sections,
    "list_versions": list_versions,
}


def list_doc_ids() -> list[str]:
    """Helper pour l'agent : connaître les docs disponibles."""
    return list_available_doc_ids()
