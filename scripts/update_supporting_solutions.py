"""
Script autonome pour ajouter une solution à supporting_solutions
dans tous les chunks Qdrant liés à un fichier source donné.

Usage :
    python update_supporting_solutions.py <source_file_url> <solution_to_add>
Exemple :
    python update_supporting_solutions.py "https://sapkb.ngrok.app/static/presentations/monfichier__20240831.pptx" "SAP S/4HANA Private Cloud"
"""

import sys
from qdrant_client import QdrantClient

# === Variables à adapter si besoin ===
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "sap_kb"

def main():
    if len(sys.argv) != 3:
        print("Usage: python update_supporting_solutions.py <source_file_url> <solution_to_add>")
        sys.exit(1)

    source_file_url = sys.argv[1]
    solution_to_add = sys.argv[2]

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Récupérer tous les points liés au fichier source
    print(f"Recherche des chunks pour source_file_url = {source_file_url} ...")
    scroll_result = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter={
            "must": [
                {"key": "source_file_url", "match": {"value": source_file_url}}
            ]
        },
        with_payload=True,
        limit=10000  # augmente si besoin
    )

    points = scroll_result[0]
    print(f"Chunks trouvés : {len(points)}")

    updated = 0
    for point in points:
        payload = point.payload or {}
        supporting = payload.get("supporting_solutions", [])
        if solution_to_add not in supporting:
            supporting.append(solution_to_add)
            payload["supporting_solutions"] = supporting

            client.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    {
                        "id": point.id,
                        "vector": point.vector,
                        "payload": payload,
                    }
                ],
            )
            updated += 1

    print(f"Chunks modifiés : {updated}")

if __name__ == "__main__":