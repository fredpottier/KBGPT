"""
Test script temporaire - Domain Context Extraction E2E
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from knowbase.ontology.domain_context_extractor import extract_domain_context
from knowbase.ontology.domain_context_store import get_domain_context_store


async def test_sap_extraction():
    """Test extraction contexte SAP."""

    text = """La solution sera utilisée par les collaborateurs de la société SAP qui édite des logiciels notamment cloud comme l'ERP S/4HANA, SuccessFactors, Concur, SAP Analytics Cloud (SAC), Business Technology Platform (BTP), etc. Les documents seront donc notamment techniques, marketing et fonctionnels en majorité. Les utilisateurs principaux sont les équipes commerciales, techniques et marketing. Acronymes courants : SAC (SAP Analytics Cloud), BTP (Business Technology Platform), CRM (Customer Relationship Management), ERP (Enterprise Resource Planning)."""

    print("\n🔍 Extraction profil contexte métier pour tenant 'sap_sales'...")
    print(f"📝 Input text ({len(text)} chars):\n{text}\n")

    try:
        # Extraction via LLM
        profile = await extract_domain_context(text, "sap_sales")

        print("✅ Profil extrait avec succès!\n")
        print("📊 Résumé:")
        print(f"  - Tenant ID: {profile.tenant_id}")
        print(f"  - Industry: {profile.industry}")
        print(f"  - Sub-domains: {', '.join(profile.sub_domains) if profile.sub_domains else 'N/A'}")
        print(f"  - Target users: {', '.join(profile.target_users) if profile.target_users else 'N/A'}")
        print(f"  - Document types: {', '.join(profile.document_types) if profile.document_types else 'N/A'}")
        print(f"  - Priority: {profile.context_priority}")
        print(f"  - Acronyms: {len(profile.common_acronyms)}")
        print(f"  - Key concepts: {len(profile.key_concepts)}")

        if profile.common_acronyms:
            print("\n🔤 Acronymes courants:")
            for acronym, expansion in list(profile.common_acronyms.items())[:10]:
                print(f"  - {acronym}: {expansion}")

        if profile.key_concepts:
            print("\n🎯 Concepts clés:")
            for concept in profile.key_concepts[:10]:
                print(f"  - {concept}")

        print(f"\n💬 LLM Injection Prompt:\n{profile.llm_injection_prompt}\n")

        # Sauvegarde
        print("💾 Sauvegarde dans Neo4j...")
        store = get_domain_context_store()
        store.save_profile(profile)

        print(f"✅ Profil sauvegardé pour tenant '{profile.tenant_id}'!")
        print(f"\nℹ️  Ce contexte sera automatiquement injecté dans tous les appels LLM (canonicalization, relations, etc.)")

    except Exception as e:
        print(f"❌ Erreur lors de l'extraction: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_sap_extraction())
