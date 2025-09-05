# scripts/migrations/update_applies_to_for_file.py
# Usage:
#   python scripts/migrations/update_applies_to_for_file.py \
#       --source-file-url "https://sapkb.ngrok.app/static/presentations/RISE_with_SAP_Cloud_ERP_Private__20250905_135400.pptx"
#
# Options:
#   --collection sap_kb                   # nom de la collection Qdrant (défaut: sap_kb)
#   --qdrant-url http://localhost:6333    # URL Qdrant (sinon via env QDRANT_URL)
#   --dry-run                             # n'écrit rien, affiche juste le comptage et le payload
#
# Effet:
#   Set payload applies_to = {
#     "generic_categories": ["SAP Cloud ERP", "RISE with SAP"],
#     "scope": ["product-specific"],
#     "is_all_sap_cloud": false,
#     "statement": "Applies to SAP S/4HANA Cloud, private edition (RISE). Guidance is product-specific even when shown across multiple hyperscalers."
#   }
#
# Remarque:
#   - Si tu passes plus tard au schéma "coverage", adapte le dict ci-dessus en conséquence.

import os
import argparse
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, PayloadSchemaType

DEFAULT_COLLECTION = "sap_kb"
DEFAULT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

APPLIES_TO_PAYLOAD = {
    "generic_categories": ["SAP Cloud ERP", "RISE with SAP"],
    "scope": ["product-specific"],
    "is_all_sap_cloud": False,
    "statement": (
        "Applies to SAP S/4HANA Cloud, private edition (RISE). Guidance is product-specific "
        "even when shown across multiple hyperscalers."
    ),
}


def main():
    parser = argparse.ArgumentParser(
        description="Update applies_to for all points of a given source_file_url."
    )
    parser.add_argument(
        "--collection", default=DEFAULT_COLLECTION, help="Qdrant collection name"
    )
    parser.add_argument(
        "--qdrant-url",
        default=DEFAULT_URL,
        help="Qdrant URL (e.g., http://localhost:6333)",
    )
    # parser.add_argument(
    #     "--source-file-url", required=True, help="Exact source_file_url to match"
    # )
    # Variable en dur pour la source_file_url
    SOURCE_FILE_URL = "https://sapkb.ngrok.app/static/presentations/RISE_with_SAP_Cloud_ERP_Private__20250905_135400.pptx"
    parser.add_argument(
        "--dry-run", action="store_true", help="Show count & payload without writing"
    )
    args = parser.parse_args([])

    client = QdrantClient(url=args.qdrant_url)

    # Filtre pour tous les points de ce fichier PPTX
    flt = Filter(
        must=[
            FieldCondition(
                key="source_file_url",
                match=MatchValue(value=SOURCE_FILE_URL),
            )
        ]
    )

    # Comptage préalable (utile en dry-run)
    try:
        cnt = client.count(
            collection_name=args.collection, count_filter=flt, exact=True
        ).count
    except Exception as e:
        print(f"[ERREUR] Impossible de compter les points: {e}")
        return

    print(f"[INFO] Points ciblés par source_file_url = {SOURCE_FILE_URL} : {cnt}")

    if cnt == 0:
        print("[INFO] Aucun point à mettre à jour. Sortie.")
        return

    print("[INFO] Payload applies_to qui sera appliqué :")
    print(APPLIES_TO_PAYLOAD)

    if args.dry_run:
        print("[DRY-RUN] Aucun changement écrit.")
        return

    # Mise à jour en une fois via filtre
    try:
        client.set_payload(
            collection_name=args.collection,
            payload={"applies_to": APPLIES_TO_PAYLOAD},
            points=flt,
        )
        print(f"[OK] Mise à jour effectuée pour {cnt} point(s).")
    except Exception as e:
        print(f"[ERREUR] Échec de la mise à jour: {e}")
        return

    # (Optionnel) créer des index de payload pour accélérer de futurs filtres
    try:
        client.create_payload_index(
            args.collection, "applies_to.is_all_sap_cloud", PayloadSchemaType.BOOL
        )
    except Exception:
        pass  # déjà créé ou version Qdrant non compatible

    try:
        client.create_payload_index(
            args.collection, "applies_to.scope", PayloadSchemaType.KEYWORD
        )
    except Exception:
        pass  # déjà créé

    try:
        client.create_payload_index(
            args.collection, "applies_to.generic_categories", PayloadSchemaType.KEYWORD
        )
    except Exception:
        pass  # déjà créé

    print("[INFO] Index de payload vérifiés/créés (si nécessaire).")


if __name__ == "__main__":
    main()
