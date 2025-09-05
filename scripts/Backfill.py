# Ce script permet de backfiller le champ applies_to pour les points existants.
# Usage : python scripts/migrations/backfill_applies_to.py

import tqdm
from qdrant_client import QdrantClient

COLLECTION = "sap_kb"  # adapte si besoin


def validate_applies_to(applies_to):
    # Validation simple du champ applies_to
    if not isinstance(applies_to, dict):
        return {
            "generic_categories": [],
            "scope": [],
            "is_all_sap_cloud": None,
            "statement": "",
        }
    out = {}
    out["generic_categories"] = (
        applies_to.get("generic_categories")
        if isinstance(applies_to.get("generic_categories"), list)
        else []
    )
    out["scope"] = (
        applies_to.get("scope") if isinstance(applies_to.get("scope"), list) else []
    )
    out["is_all_sap_cloud"] = (
        bool(applies_to.get("is_all_sap_cloud"))
        if "is_all_sap_cloud" in applies_to
        else None
    )
    out["statement"] = (
        applies_to.get("statement")
        if isinstance(applies_to.get("statement"), str)
        else ""
    )
    return out


def backfill():
    client = QdrantClient(url="http://localhost:6333")
    # Récupère tous les points (adapte limit si besoin)
    points, _ = client.scroll(COLLECTION, limit=10000)
    count = 0
    for pt in tqdm.tqdm(points):
        payload = pt.payload or {}
        applies_to = payload.get("applies_to", None)
        # Si le champ manque ou est vide, on le backfill
        if not applies_to:
            new_applies_to = validate_applies_to({})
            client.set_payload(
                collection_name=COLLECTION,
                points=[pt.id],
                payload={"applies_to": new_applies_to},
            )
            count += 1
    print(f"Backfill terminé : {count} points mis à jour.")


if __name__ == "__main__":
    backfill()
