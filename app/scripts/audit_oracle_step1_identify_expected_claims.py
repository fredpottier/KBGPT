"""A4.7 Step 1 — Identifier les expected_claim_ids pour les 20 premières questions
du gold-set 50q SAP A3.8.

Protocole :
  1. Lire les 20 premières questions
  2. Pour chaque q, MATCH dans Neo4j tous les Claim ayant source_doc_id IN supporting_doc_ids
  3. Scorer chaque candidat par similarité embedding (question vs subject+predicate+value+claim_text)
  4. Sortir top-K candidats par question dans oracle_expected_claims_20q.json

Output structure (par question) :
{
  "id": "V2_T1_T1_HUM_0097",
  "question": "...",
  "ground_truth_answer": "...",
  "exact_identifiers": [...],
  "supporting_doc_ids": [...],
  "n_claims_in_supporting_docs": 142,
  "top_candidates": [
    {"claim_id": "...", "claim_text": "...", "score": 0.87, "subject_canonical": "...", ...},
    ...
  ]
}

Usage :
    docker exec knowbase-app python scripts/audit_oracle_step1_identify_expected_claims.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("audit_oracle_step1")


GOLD_SET_PATH = Path("benchmark/questions/gold_set_a38_50q.json")
OUTPUT_PATH = Path("data/benchmark/a47_oracle_audit/oracle_expected_claims_20q.json")
TOP_K = 10  # 10 candidats par question (large pour annotation manuelle ensuite)
LIMIT = 20


def load_questions() -> List[Dict[str, Any]]:
    with open(GOLD_SET_PATH, "r", encoding="utf-8") as f:
        all_q = json.load(f)
    return all_q[:LIMIT]


def _extract_doc_hash(doc_id: str) -> Optional[str]:
    """Extrait le hash suffixe stable d'un doc_id (8 derniers chars après dernier _).

    Le gold-set utilise des noms de docs antérieurs à la ré-ingestion A2.12 ;
    le hash content_fingerprint reste stable, on matche dessus.
    """
    if not doc_id:
        return None
    parts = doc_id.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) == 8 and all(c in "0123456789abcdef" for c in parts[1].lower()):
        return parts[1].lower()
    return None


def fetch_claims_for_doc_ids(neo4j_client, doc_ids: List[str]) -> List[Dict[str, Any]]:
    """Récupère tous les claims dont doc_id matche par hash suffixe.

    Note KG : la propriété est `doc_id` (pas source_doc_id). Le runtime_v6 expose
    via le champ Pydantic source_doc_id par convention.

    Matching par hash suffixe car le gold-set utilise des noms de docs anciens
    (pré-ré-ingestion A2.12) — seul le hash reste stable.
    """
    if not doc_ids:
        return []
    hashes = [h for h in (_extract_doc_hash(d) for d in doc_ids) if h]
    if not hashes:
        logger.warning("  → no extractable doc hash from %s", doc_ids)
        return []

    cypher = """
    MATCH (c:Claim)
    WHERE c.tenant_id = 'default'
      AND ANY(h IN $hashes WHERE c.doc_id ENDS WITH ('_' + h))
    RETURN c.claim_id AS claim_id,
           c.subject_canonical AS subject_canonical,
           c.predicate AS predicate,
           c.object_canonical AS value,
           c.confidence AS confidence,
           c.doc_id AS doc_id,
           c.text AS claim_text_full,
           c.verbatim_quote AS verbatim_quote,
           c.structured_form_json AS structured_form_json,
           c.page_no AS page_no
    """
    rows = neo4j_client.execute_query(cypher, hashes=hashes)
    result = [dict(r) for r in rows]
    if result:
        logger.info("  → matched hashes %s → %d claims (resolved doc_id: %s)",
                    hashes, len(result), result[0].get("doc_id"))
    return result


def claim_to_text(claim: Dict[str, Any]) -> str:
    """Texte du claim pour scoring embedding.

    Priorité : claim.text (texte complet du claim) > verbatim_quote > S+P+V.
    """
    txt = claim.get("claim_text_full") or claim.get("verbatim_quote")
    if txt and str(txt).strip():
        return str(txt).strip()
    # Fallback : concat S+P+V
    parts = []
    if claim.get("subject_canonical"):
        parts.append(claim["subject_canonical"])
    if claim.get("predicate"):
        parts.append(claim["predicate"].replace("_", " ").lower())
    val = claim.get("value")
    if val:
        parts.append(str(val))
    return " ".join(parts).strip()


def score_candidates(
    question: str,
    exact_identifiers: List[str],
    claims: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Score chaque claim par cosine(question + identifiers, claim_text)."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("intfloat/multilingual-e5-large")

    # Encode query : question + exact_identifiers joint
    query_text = question
    if exact_identifiers:
        query_text += " | " + " | ".join(exact_identifiers)
    # E5 convention : "query: " prefix
    query_emb = model.encode([f"query: {query_text}"], normalize_embeddings=True)

    # Encode candidates : "passage: " prefix
    claim_texts = [claim_to_text(c) for c in claims]
    valid_indices = [i for i, t in enumerate(claim_texts) if t]
    if not valid_indices:
        return []
    valid_texts = [f"passage: {claim_texts[i]}" for i in valid_indices]
    claim_embs = model.encode(valid_texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)

    # Cosine similarity
    import numpy as np

    sims = (query_emb @ claim_embs.T)[0]  # shape (n,)

    # Build sorted candidates
    scored = []
    for rank_i, sim in enumerate(sims):
        ci = valid_indices[rank_i]
        c = claims[ci]
        scored.append({
            "claim_id": c["claim_id"],
            "claim_text": claim_texts[ci],
            "score": float(sim),
            "subject_canonical": c.get("subject_canonical"),
            "predicate": c.get("predicate"),
            "value": c.get("value"),
            "doc_id": c.get("doc_id"),
            "page_no": c.get("page_no"),
            "verbatim_quote": c.get("verbatim_quote"),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:TOP_K]


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    questions = load_questions()
    logger.info("Loaded %d questions (limit=%d)", len(questions), LIMIT)

    # Connect Neo4j
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    neo4j_client = get_neo4j_client()

    results = []
    for i, q in enumerate(questions, 1):
        gt = q.get("ground_truth", {})
        supporting = gt.get("supporting_doc_ids", []) or []
        exact_ids = gt.get("exact_identifiers", []) or []

        logger.info("[%d/%d] %s — %d supporting docs", i, len(questions), q["id"], len(supporting))

        if not supporting:
            logger.warning("  → no supporting_doc_ids, skipping candidate scoring")
            results.append({
                "id": q["id"],
                "question": q["question"],
                "primary_type": q.get("primary_type"),
                "ground_truth_answer": gt.get("answer", ""),
                "exact_identifiers": exact_ids,
                "supporting_doc_ids": supporting,
                "answerability": gt.get("answerability"),
                "false_premise": gt.get("false_premise", False),
                "n_claims_in_supporting_docs": 0,
                "top_candidates": [],
                "note": "no_supporting_doc_ids",
            })
            continue

        claims = fetch_claims_for_doc_ids(neo4j_client, supporting)
        logger.info("  → %d claims in supporting docs", len(claims))

        if not claims:
            results.append({
                "id": q["id"],
                "question": q["question"],
                "primary_type": q.get("primary_type"),
                "ground_truth_answer": gt.get("answer", ""),
                "exact_identifiers": exact_ids,
                "supporting_doc_ids": supporting,
                "answerability": gt.get("answerability"),
                "false_premise": gt.get("false_premise", False),
                "n_claims_in_supporting_docs": 0,
                "top_candidates": [],
                "note": "no_claims_in_supporting_docs",
            })
            continue

        top = score_candidates(q["question"], exact_ids, claims)
        results.append({
            "id": q["id"],
            "question": q["question"],
            "primary_type": q.get("primary_type"),
            "ground_truth_answer": gt.get("answer", ""),
            "exact_identifiers": exact_ids,
            "supporting_doc_ids": supporting,
            "answerability": gt.get("answerability"),
            "false_premise": gt.get("false_premise", False),
            "n_claims_in_supporting_docs": len(claims),
            "top_candidates": top,
        })

    # Note: neo4j_client is a singleton — pas de .close() ici

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    logger.info("Wrote %s", OUTPUT_PATH)

    # Summary
    n_with_claims = sum(1 for r in results if r["n_claims_in_supporting_docs"] > 0)
    n_no_supporting = sum(1 for r in results if r.get("note") == "no_supporting_doc_ids")
    n_no_claims = sum(1 for r in results if r.get("note") == "no_claims_in_supporting_docs")
    logger.info("=" * 60)
    logger.info("Summary: %d/%d questions with ≥1 candidate claim", n_with_claims, len(results))
    logger.info("  - %d questions with no supporting_doc_ids", n_no_supporting)
    logger.info("  - %d questions with supporting docs but no claims found", n_no_claims)


if __name__ == "__main__":
    main()
