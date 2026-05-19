"""Prépare un fichier workbench pour rédaction Claude des 23 T4 ground truths.

Pour chaque question T4 avec _needs_redaction=True :
1. Charge les structures DSG des expected_docs
2. Identifie les sections pertinentes (mot-clé entity, top 5/doc)
3. Construit un extrait concis (1500 chars max/section)

Output : t4_redact_workbench.json avec context complet pour rédaction Claude.

Run :
    docker exec knowbase-app bash -c "cd /app && python scripts/prepare_t4_redaction.py"
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GOLDSET = Path("/app/benchmark/questions/gold_set_sap_v2.json")
STRUCTURES_DIR = Path("/app/data/poc_a/structures")
OUT = Path("/app/benchmark/questions/t4_redact_workbench.json")

MAX_SECTIONS_PER_DOC = 5
MAX_SECTION_CHARS = 1500


def load_structure(doc_id: str) -> dict | None:
    """Load DSG structure by doc_id (suffix match)."""
    candidates = list(STRUCTURES_DIR.glob(f"*{doc_id[-8:]}*.json"))
    if not candidates:
        candidates = list(STRUCTURES_DIR.glob(f"*{doc_id}*.json"))
    if not candidates:
        return None
    with open(candidates[0], encoding="utf-8") as f:
        return json.load(f)


def normalize_for_search(text: str) -> str:
    """Lowercase + collapse whitespace for keyword matching."""
    return re.sub(r"\s+", " ", text.lower())


def find_relevant_sections(struct: dict, entity: str, max_n: int) -> list[dict]:
    """Trouve top-N sections contenant les mots-clés de entity (split + match)."""
    sections = struct.get("sections", [])
    if not entity or not sections:
        return sections[:max_n]
    # Extract keywords (≥4 chars, no stopwords)
    stopwords = {"avec", "sans", "pour", "dans", "sur", "and", "the", "for", "with"}
    keywords = [w for w in re.split(r"[\s/_-]+", entity.lower()) if len(w) >= 4 and w not in stopwords]
    if not keywords:
        return sections[:max_n]
    # Score sections by keyword count
    scored = []
    for sec in sections:
        text_norm = normalize_for_search(sec.get("text", "") + " " + sec.get("title", ""))
        score = sum(1 for kw in keywords if kw in text_norm)
        if score > 0:
            scored.append((score, sec))
    scored.sort(key=lambda x: -x[0])
    relevant = [sec for _, sec in scored[:max_n]]
    # If nothing matched, fallback first N
    if not relevant:
        return sections[:max_n]
    return relevant


def truncate_section(sec: dict, max_chars: int) -> dict:
    """Truncate section text to max_chars while preserving structure."""
    text = sec.get("text", "")
    if len(text) > max_chars:
        text = text[:max_chars] + "...[truncated]"
    return {
        "section_id": sec.get("section_id"),
        "numbering": sec.get("numbering"),
        "title": sec.get("title"),
        "page_range": sec.get("page_range"),
        "text": text,
    }


def main():
    questions = json.loads(GOLDSET.read_text(encoding="utf-8"))
    to_redact = [q for q in questions if q.get("_needs_redaction")]
    logger.info(f"Found {len(to_redact)} questions needing redaction")

    workbench = []
    for q in to_redact:
        gt = q.get("ground_truth", {})
        entity = gt.get("entity", "")
        expected_docs = gt.get("supporting_doc_ids", [])
        expected_claim_count = gt.get("expected_claim_count", 0)
        expected_contradiction_count = gt.get("expected_contradiction_count", 0)

        doc_contexts = []
        for doc_id in expected_docs:
            struct = load_structure(doc_id)
            if struct is None:
                logger.warning(f"  No structure found for {doc_id}")
                continue
            relevant = find_relevant_sections(struct, entity, MAX_SECTIONS_PER_DOC)
            truncated = [truncate_section(s, MAX_SECTION_CHARS) for s in relevant]
            doc_contexts.append({
                "doc_id": doc_id,
                "doc_name": struct.get("doc_name", doc_id),
                "n_pages": struct.get("n_pages"),
                "sections": truncated,
            })

        workbench.append({
            "id": q["id"],
            "question": q["question"],
            "primary_type": q["primary_type"],
            "entity": entity,
            "expected_claim_count": expected_claim_count,
            "expected_contradiction_count": expected_contradiction_count,
            "supporting_doc_ids": expected_docs,
            "doc_contexts": doc_contexts,
            "claude_redacted_answer": None,  # to be filled
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(workbench, indent=2, ensure_ascii=False), encoding="utf-8")
    total_sections = sum(len(d["sections"]) for q in workbench for d in q["doc_contexts"])
    logger.info(f"Written: {OUT}")
    logger.info(f"  {len(workbench)} questions, {total_sections} sections total")
    logger.info(f"  Average sections per question: {total_sections / len(workbench):.1f}")


if __name__ == "__main__":
    main()
