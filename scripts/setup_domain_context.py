"""
Script utilitaire : Configuration Domain Context

Permet de configurer le contexte métier pour un tenant sans passer par le frontend.

Usage:
    # Exemple SAP
    python scripts/setup_domain_context.py --tenant sap_sales --input "La solution sera utilisée par les collaborateurs de la société SAP..."

    # Exemple Pharma
    python scripts/setup_domain_context.py --tenant pharma_rd --input "We are a pharmaceutical R&D company..."

    # Lister profils existants
    python scripts/setup_domain_context.py --list

    # Supprimer profil
    python scripts/setup_domain_context.py --tenant sap_sales --delete
"""

import argparse
import asyncio
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.ontology.domain_context import DomainContextProfile
from knowbase.ontology.domain_context_extractor import extract_domain_context
from knowbase.ontology.domain_context_store import get_domain_context_store


async def setup_domain_context(tenant_id: str, user_text: str):
    """
    Configure contexte métier pour un tenant.

    Args:
        tenant_id: ID tenant
        user_text: Description libre domaine métier
    """
    print(f"\n🔍 Extraction profil contexte métier pour tenant '{tenant_id}'...")
    print(f"📝 Input text ({len(user_text)} chars):\n{user_text}\n")

    try:
        # Extraction via LLM
        profile = await extract_domain_context(user_text, tenant_id)

        print("✅ Profil extrait avec succès!\n")
        print("📊 Résumé:")
        print(f"  - Industry: {profile.industry}")
        print(f"  - Sub-domains: {', '.join(profile.sub_domains) if profile.sub_domains else 'N/A'}")
        print(f"  - Target users: {', '.join(profile.target_users) if profile.target_users else 'N/A'}")
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

        print(f"✅ Profil sauvegardé pour tenant '{tenant_id}'!")
        print(f"\nℹ️  Ce contexte sera automatiquement injecté dans tous les appels LLM (canonicalization, relations, etc.)")

    except Exception as e:
        print(f"❌ Erreur lors de l'extraction: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def list_profiles():
    """Liste tous les profils contexte."""
    print("\n📋 Profils contexte métier existants:\n")

    store = get_domain_context_store()
    profiles = store.list_all_profiles()

    if not profiles:
        print("  (Aucun profil configuré)")
        return

    for profile in profiles:
        print(f"  • Tenant: {profile.tenant_id}")
        print(f"    Industry: {profile.industry}")
        print(f"    Priority: {profile.context_priority}")
        print(f"    Acronyms: {len(profile.common_acronyms)}")
        print(f"    Created: {profile.created_at.strftime('%Y-%m-%d %H:%M')}")
        print()


def delete_profile(tenant_id: str):
    """Supprime profil contexte pour un tenant."""
    print(f"\n🗑️  Suppression profil pour tenant '{tenant_id}'...")

    store = get_domain_context_store()
    deleted = store.delete_profile(tenant_id)

    if deleted:
        print(f"✅ Profil supprimé pour tenant '{tenant_id}'")
        print(f"ℹ️  Le système utilisera maintenant le comportement domain-agnostic (générique)")
    else:
        print(f"⚠️  Aucun profil trouvé pour tenant '{tenant_id}'")


def main():
    parser = argparse.ArgumentParser(
        description="Configure domain context pour un tenant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:

  # Configuration contexte SAP
  python scripts/setup_domain_context.py --tenant sap_sales \\
    --input "La solution sera utilisée par les collaborateurs de SAP..."

  # Configuration contexte Pharma
  python scripts/setup_domain_context.py --tenant pharma_rd \\
    --input "We are a pharmaceutical R&D company..."

  # Lire depuis fichier
  python scripts/setup_domain_context.py --tenant sap_sales \\
    --input-file context_sap.txt

  # Lister profils
  python scripts/setup_domain_context.py --list

  # Supprimer profil
  python scripts/setup_domain_context.py --tenant sap_sales --delete
        """
    )

    parser.add_argument(
        "--tenant",
        type=str,
        help="Tenant ID (ex: sap_sales, pharma_rd, retail_marketing)"
    )

    parser.add_argument(
        "--input",
        type=str,
        help="Description libre du domaine métier (2-500 mots)"
    )

    parser.add_argument(
        "--input-file",
        type=str,
        help="Fichier contenant la description du domaine métier"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="Lister tous les profils existants"
    )

    parser.add_argument(
        "--delete",
        action="store_true",
        help="Supprimer profil pour le tenant spécifié"
    )

    args = parser.parse_args()

    # Mode liste
    if args.list:
        list_profiles()
        return

    # Mode suppression
    if args.delete:
        if not args.tenant:
            print("❌ Erreur: --tenant requis pour suppression")
            sys.exit(1)
        delete_profile(args.tenant)
        return

    # Mode configuration (requiert tenant + input)
    if not args.tenant:
        print("❌ Erreur: --tenant requis")
        parser.print_help()
        sys.exit(1)

    # Récupérer input text
    if args.input_file:
        try:
            with open(args.input_file, "r", encoding="utf-8") as f:
                user_text = f.read().strip()
        except FileNotFoundError:
            print(f"❌ Erreur: Fichier '{args.input_file}' introuvable")
            sys.exit(1)
    elif args.input:
        user_text = args.input.strip()
    else:
        print("❌ Erreur: --input ou --input-file requis")
        parser.print_help()
        sys.exit(1)

    # Validation input
    if len(user_text) < 10:
        print("❌ Erreur: Description trop courte (min 10 caractères)")
        sys.exit(1)

    if len(user_text) > 5000:
        print("❌ Erreur: Description trop longue (max 5000 caractères)")
        sys.exit(1)

    # Exécution async
    asyncio.run(setup_domain_context(args.tenant, user_text))


if __name__ == "__main__":
    main()
