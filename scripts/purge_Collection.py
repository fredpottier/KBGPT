from qdrant_client import QdrantClient

# Configuration
client = QdrantClient(host="localhost", port=6333)
collection_name = "sap_kb"  # ⚠️ adapte le nom si tu en utilises un autre

# Suppression
if client.collection_exists(collection_name):
    client.delete_collection(collection_name)
    print(f"✅ Collection '{collection_name}' supprimée.")
else:
    print(f"ℹ️ Collection '{collection_name}' introuvable.")
