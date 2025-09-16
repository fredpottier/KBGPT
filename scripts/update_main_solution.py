"""
Script autonome pour remplacer la valeur du champ main_solution
dans tous les chunks Qdrant où main_solution contient
'RISE with SAP Cloud ERP Private' par
'RISE with SAP S/4HANA Cloud, private edition'.

Usage :
    python update_main_solution.py
"""

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

# === Variables à adapter si besoin ===
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "sap_kb"
OLD_VALUE = "RISE with SAP Cloud ERP Private"
NEW_VALUE = "RISE with SAP S/4HANA Cloud, private edition"


def main():
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    print(f"Recherche des chunks où main_solution contient '{OLD_VALUE}' ...")
    scroll_filter = Filter(
        must=[FieldCondition(key="main_solution", match=MatchValue(value=OLD_VALUE))]
    )
    scroll_result = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=scroll_filter,
        with_payload=True,
        with_vectors=True,
        limit=10000,
    )

    points = scroll_result[0]
    print(f"Chunks trouvés : {len(points)}")

    updated = 0
    for point in points:
        payload = point.payload or {}
        if payload.get("main_solution") == OLD_VALUE:
            client.set_payload(
                collection_name=COLLECTION_NAME,
                payload={"main_solution": NEW_VALUE},
                points=[point.id],
            )
            updated += 1

    print(f"Chunks modifiés : {updated}")


if __name__ == "__main__":
    main()
