"""
🌊 OSMOSE - Load Domain Context Profile into Neo4j

Script pour charger un DomainContextProfile depuis JSON vers Neo4j.

Usage:
    python scripts/load_domain_context.py domain_context_sap_global.json
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.ontology.domain_context import DomainContextProfile
from knowbase.ontology.domain_context_store import DomainContextStore


async def load_domain_context(json_path: str):
    """
    Charge un DomainContextProfile depuis un fichier JSON.

    Args:
        json_path: Chemin vers le fichier JSON
    """
    print(f"🌊 OSMOSE - Loading Domain Context from {json_path}")

    # Lire le JSON
    json_file = Path(json_path)
    if not json_file.exists():
        print(f"❌ Fichier non trouvé: {json_path}")
        sys.exit(1)

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"✅ JSON chargé: tenant_id={data.get('tenant_id')}")

    # Créer le profil
    try:
        profile = DomainContextProfile(**data)
        print(f"✅ DomainContextProfile créé et validé (Pydantic)")
    except Exception as e:
        print(f"❌ Erreur validation Pydantic: {e}")
        sys.exit(1)

    # Sauvegarder dans Neo4j
    store = DomainContextStore()

    try:
        await store.save_profile(profile)
        print(f"✅ DomainContextProfile sauvegardé dans Neo4j")
        print(f"   - Tenant: {profile.tenant_id}")
        print(f"   - Industry: {profile.industry}")
        print(f"   - Sub-domains: {len(profile.sub_domains)}")
        print(f"   - Acronyms: {len(profile.common_acronyms)}")
        print(f"   - Key Concepts: {len(profile.key_concepts)}")
        print(f"   - Priority: {profile.context_priority}")
    except Exception as e:
        print(f"❌ Erreur sauvegarde Neo4j: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Vérifier la sauvegarde
    try:
        loaded = await store.get_profile(profile.tenant_id)
        if loaded:
            print(f"✅ Vérification: DomainContextProfile bien présent dans Neo4j")
        else:
            print(f"⚠️ Vérification échouée: profil non trouvé après sauvegarde")
    except Exception as e:
        print(f"⚠️ Erreur vérification: {e}")

    print("\n🎯 Domain Context prêt à être utilisé par DomainContextInjector")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/load_domain_context.py <json_file>")
        print("Exemple: python scripts/load_domain_context.py domain_context_sap_global.json")
        sys.exit(1)

    json_path = sys.argv[1]
    asyncio.run(load_domain_context(json_path))
