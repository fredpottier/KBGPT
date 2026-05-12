"""Enrichit gold_set_sap_v1.json :
- supporting_doc_ids : top-3 docs Qdrant pour chaque question
- exact_identifiers : extraction auto termes SAP des réponses"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")

from knowbase.common.clients.embeddings import get_embedding_manager
from knowbase.common.clients import get_qdrant_client

GOLDSET_PATH = Path("/app/benchmark/questions/gold_set_sap_v1.json")

# Patterns d'identifiers SAP courants
SAP_PATTERNS = [
    # Produits/modules avec slash, ex: S/4HANA, S/4HANA 2024
    r"S/4HANA(?:\s+(?:Cloud|2\d{3}|FPS\d{2}|SPS\d{2}|Private\s+Edition|Public\s+Edition))?",
    # Produits HANA
    r"HANA(?:\s+\d+\.\d+)?",
    # Acronymes 2-5 lettres majuscules
    r"\b[A-Z]{2,5}\b",
    # Versions SAP : 2024, FPS03, SPS04, EHP6
    r"\b(?:FPS|SPS|EHP)\d{1,2}\b",
    # Acronymes avec / : RISE-with-SAP, Cloud-ERP, etc.
    r"\b[A-Z][a-zA-Z]+(?:-[A-Za-z]+)+\b",
    # Termes SAP capitalisés multi-mots
    r"\b(?:SAP\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b",
]

# Stopwords pour filtrer le bruit
STOP_TERMS = {
    "Cette", "Voici", "Pour", "Plusieurs", "Comment", "Quel", "Quels", "Quelle",
    "Cloud", "Private", "Edition", "Le", "La", "Les", "Des", "Un", "Une",
    "And", "The", "Of", "To", "In", "On", "At", "By", "For", "With",
    "SAP", "Type", "Mode",
}

# Mots-clés SAP toujours intéressants (whitelist)
SAP_WHITELIST = {
    "S/4HANA", "HANA", "BTP", "SAC", "RISE", "GROW", "PCE",
    "ABAP", "RAP", "CDS", "OData", "Fiori",
    "GDPR", "FedRAMP", "GovCloud",
    "BW/4HANA", "Datasphere", "Cash Management", "Asset Accounting",
    "Business Partner", "Universal Journal",
    "EWM", "FI", "CO", "MM", "SD", "HR", "PP",
    "AWS", "Azure", "GCP",
    "ECC", "EHP6", "EHP7", "EHP8",
}


def extract_identifiers(text: str) -> list[str]:
    """Extrait les termes SAP-like d'un texte."""
    found = set()

    # 1. Termes du whitelist explicites
    for term in SAP_WHITELIST:
        if term.lower() in text.lower() or term in text:
            found.add(term)

    # 2. Acronymes majuscules
    for m in re.finditer(r"\b[A-Z][A-Z0-9/]{1,8}\b", text):
        t = m.group()
        if t not in STOP_TERMS and len(t) >= 2:
            found.add(t)

    # 3. Versions SAP
    for m in re.finditer(r"\b(?:FPS|SPS|EHP)\d{1,2}\b", text):
        found.add(m.group())

    # 4. Années 4 chiffres (2023, 2024, etc.)
    for m in re.finditer(r"\b20\d{2}\b", text):
        found.add(m.group())

    # 5. Produits multi-mots typiques (heuristique : "X Y" avec X et Y capitalisés)
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", text):
        t = m.group()
        if t not in STOP_TERMS and len(t.split()) >= 2 and not t.startswith("Le ") and not t.startswith("La "):
            found.add(t)

    # Limit to top-10 sorted by length desc (préférer termes longs/spécifiques)
    return sorted(found, key=lambda x: -len(x))[:10]


def get_top_doc_ids(em, qc, question: str, top_k: int = 3) -> list[str]:
    """Retrouve les top-K doc_ids uniques pour une question."""
    try:
        embedding = em.encode([question])[0]
        results = qc.search(
            collection_name="knowbase_chunks_v2",
            query_vector=embedding.tolist() if hasattr(embedding, "tolist") else list(embedding),
            limit=10,
            with_payload=True,
        )
        seen = []
        for hit in results:
            payload = hit.payload or {}
            doc_id = payload.get("doc_id") or payload.get("document_id")
            if doc_id and doc_id not in seen:
                seen.append(doc_id)
            if len(seen) >= top_k:
                break
        return seen
    except Exception as e:
        print(f"  retrieval error: {e}")
        return []


def main():
    em = get_embedding_manager()
    qc = get_qdrant_client()

    data = json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(data)} questions")

    for q in data:
        qid = q["id"]
        question = q["question"]
        answer = q.get("ground_truth", {}).get("answer", "")

        # 1. Enrich supporting_doc_ids if placeholder
        current_docs = q.get("ground_truth", {}).get("supporting_doc_ids", [])
        if not current_docs or any("<" in str(d) for d in current_docs):
            new_docs = get_top_doc_ids(em, qc, question, top_k=3)
            q["ground_truth"]["supporting_doc_ids"] = new_docs
            print(f"  {qid}: +{len(new_docs)} supporting_doc_ids")

        # 2. Enrich exact_identifiers if placeholder
        current_ids = q.get("ground_truth", {}).get("exact_identifiers", [])
        if not current_ids or any(isinstance(x, str) and "<" in x for x in current_ids):
            # Extract from answer (preferred) + question as fallback
            new_ids = extract_identifiers(answer + " " + question)
            q["ground_truth"]["exact_identifiers"] = new_ids
            print(f"  {qid}: +{len(new_ids)} exact_identifiers")

    GOLDSET_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ Written: {GOLDSET_PATH}")

    # Sample
    print("\n=== Sample enriched Q1.1 ===")
    q11 = next((q for q in data if q["id"] == "GOLD_SAP_Q1_1"), None)
    if q11:
        print(json.dumps(q11, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
