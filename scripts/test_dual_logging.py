#!/usr/bin/env python3
"""
Test du Dual LLM Logging - Benchmark OpenAI vs vLLM pendant import.

Usage:
    # Depuis le container app:
    python scripts/test_dual_logging.py --vllm-url http://<EC2_IP>:8000

    # Test rapide avec un chunk:
    python scripts/test_dual_logging.py --vllm-url http://<EC2_IP>:8000 --quick
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


async def test_dual_logging(vllm_url: str, quick: bool = False):
    """Test du dual logging avec extraction de concepts."""

    # Import après path setup
    from knowbase.common.dual_llm_logger import DualLLMLogger, enable_dual_logging
    from knowbase.common.llm_router import LLMRouter, TaskType

    logger.info("=" * 60)
    logger.info("TEST DUAL LLM LOGGING - OpenAI vs vLLM")
    logger.info("=" * 60)

    # Activer dual logging
    dual_logger = enable_dual_logging(vllm_url)
    logger.info(f"Dual logging activé → {vllm_url}")

    # LLM Router pour les appels OpenAI
    llm_router = LLMRouter()

    # Chunks de test
    test_chunks = [
        {
            "id": "chunk1",
            "text": """Les ransomwares représentent une menace croissante pour les entreprises.
            SAP S/4HANA Cloud offre des fonctionnalités de sauvegarde automatique qui peuvent
            aider à la récupération post-attaque. Le RGPD impose des obligations de notification
            en cas de violation de données, typiquement sous 72 heures."""
        },
        {
            "id": "chunk2",
            "text": """Azure Active Directory et SAP Identity Authentication Service permettent
            l'authentification fédérée via SAML 2.0. Cette intégration renforce la sécurité
            tout en simplifiant l'expérience utilisateur grâce au Single Sign-On (SSO).
            La conformité SOC 2 Type II certifie les contrôles de sécurité."""
        }
    ]

    if quick:
        test_chunks = test_chunks[:1]

    # Prompt d'extraction (simplifié du concept_extractor)
    EXTRACTION_PROMPT = """Extrait les concepts clés du texte suivant.

Pour chaque concept, identifie :
- name : le nom du concept (2-50 caractères)
- type : un parmi [ENTITY, PRACTICE, STANDARD, TOOL, ROLE]
- definition : une brève définition (1 phrase)
- relationships : liste de noms de concepts liés (max 3)

Texte à analyser :
---
{text}
---

Retourne un objet JSON avec cette structure exacte:
{{"concepts": [{{"name": "...", "type": "...", "definition": "...", "relationships": [...]}}]}}

Important : Retourne UNIQUEMENT le JSON, sans commentaires."""

    for chunk in test_chunks:
        logger.info(f"\n--- Test chunk: {chunk['id']} ---")
        logger.info(f"Texte: {chunk['text'][:100]}...")

        prompt = EXTRACTION_PROMPT.format(text=chunk["text"])
        messages = [{"role": "user", "content": prompt}]

        try:
            response = await dual_logger.dual_call_async(
                llm_router=llm_router,
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=messages,
                temperature=0.2,
                max_tokens=2048
            )
            logger.info(f"Réponse (OpenAI): {response[:200]}...")
        except Exception as e:
            logger.error(f"Erreur: {e}")

    # Afficher stats
    stats = dual_logger.get_stats()
    logger.info("\n" + "=" * 60)
    logger.info("STATISTIQUES DUAL LOGGING")
    logger.info("=" * 60)
    logger.info(json.dumps(stats, indent=2))

    # Désactiver
    dual_logger.disable()

    logger.info(f"\nRésultats sauvegardés dans: {stats['output_file']}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Test Dual LLM Logging")
    parser.add_argument(
        "--vllm-url",
        required=True,
        help="URL du serveur vLLM (ex: http://ec2-xxx:8000)"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Test rapide avec un seul chunk"
    )

    args = parser.parse_args()

    asyncio.run(test_dual_logging(args.vllm_url, args.quick))


if __name__ == "__main__":
    main()
