from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

# Configuration
client = QdrantClient(host="localhost", port=6333)
collection_name = "sap_kb"
source_to_delete = "rfp_qa"

# Suppression des points avec le champ source correspondant
deleted = client.delete(
    collection_name,
    points_selector=Filter(
        must=[FieldCondition(key="type", match=MatchValue(value=source_to_delete))]
    ),
)

num_deleted = getattr(deleted, "operation_count", "inconnu")

print(
    f"✅ Chunks avec type '{source_to_delete}' supprimés. Nombre supprimés : {num_deleted}. Résultat Qdrant : {deleted}"
)
