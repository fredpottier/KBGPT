"""
Migration du contexte SAP vers tenant_id="default"
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from knowbase.ontology.domain_context_extractor import extract_domain_context
from knowbase.ontology.domain_context_store import get_domain_context_store


async def migrate_to_default():
    """Migre le contexte SAP vers tenant_id='default'."""

    text = """SAP est un éditeur allemand leader mondial des logiciels d'entreprise, connu pour son ERP S/4HANA, ses solutions analytiques SAP BW/4HANA et SAP Analytics Cloud (SAC), ainsi que sa plateforme d'intégration SAP BTP regroupant API Management, Integration Suite et services d'IA. L'entreprise propose aussi des solutions métiers comme SuccessFactors pour les RH, Ariba pour les achats, Concur pour les déplacements, ou SAP Customer Experience (CX) pour la relation client. Avec SAP S/4HANA Cloud, Private Edition (Rise with SAP) et SAP S/4HANA Cloud, Public Edition (Grow with SAP), elle accompagne les entreprises dans leur transformation vers le cloud en combinant ERP, services managés et outils de modernisation. SAP soutient ainsi la digitalisation end-to-end des organisations, du pilotage financier à la supply-chain, en passant par les ressources humaines et l'expérience client."""

    tenant_id = "default"  # ← Changé de "sap_sales" à "default"

    print("\n🔄 Migration du contexte SAP vers tenant_id='default'")
    print("="*70)
    print(f"📝 Tenant: {tenant_id}")
    print("="*70)

    try:
        # 1. Supprimer ancien profil "sap_sales" si existe
        print("\n🗑️  Suppression ancien profil 'sap_sales' (si existe)...")
        store = get_domain_context_store()
        deleted = store.delete_profile("sap_sales")
        if deleted:
            print("   ✅ Ancien profil 'sap_sales' supprimé")
        else:
            print("   ℹ️  Pas de profil 'sap_sales' existant")

        # 2. Extraction pour "default"
        print(f"\n🔍 Extraction du profil pour tenant '{tenant_id}'...")
        profile = await extract_domain_context(text, tenant_id)

        print("\n✅ Profil extrait avec succès!")
        print(f"  • Industry: {profile.industry}")
        print(f"  • Priority: {profile.context_priority}")
        print(f"  • Acronyms: {len(profile.common_acronyms)}")
        print(f"  • Key Concepts: {len(profile.key_concepts)}")

        # 3. Sauvegarde dans Neo4j
        print(f"\n💾 Sauvegarde dans Neo4j pour tenant '{tenant_id}'...")
        store.save_profile(profile)

        print(f"\n✅ Migration terminée !")
        print(f"\nℹ️  Le contexte SAP est maintenant sur tenant_id='default'")
        print(f"   Tous les documents importés utiliseront automatiquement ce contexte.")

        # 4. Vérification
        print(f"\n🔍 Vérification...")
        loaded_profile = store.get_profile("default")
        if loaded_profile:
            print(f"   ✅ Profil 'default' chargé avec succès")
            print(f"   • Industry: {loaded_profile.industry}")
            print(f"   • {len(loaded_profile.common_acronyms)} acronymes")
        else:
            print(f"   ❌ Erreur: Profil 'default' non trouvé après sauvegarde")

    except Exception as e:
        print(f"\n❌ Erreur lors de la migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(migrate_to_default())
