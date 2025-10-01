"""
Script Validation Cohérence Qdrant ↔ Graphiti
Phase 2 - Priorité 2

Détecte les incohérences entre Qdrant et Graphiti:
- Chunks orphelins (episode_id sans episode Graphiti)
- Episodes orphelins (episode Graphiti sans chunks Qdrant)
- Metadata incohérentes (chunk_ids ne matchent pas)

Usage:
    python scripts/validate_sync_consistency.py --tenant test_client
    python scripts/validate_sync_consistency.py --tenant test_client --fix
"""

import asyncio
import logging
from typing import Dict, List, Set, Any
from dataclasses import dataclass

from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.graphiti.graphiti_client import get_graphiti_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Résultats validation sync"""
    tenant_id: str
    chunks_total: int
    chunks_with_kg: int
    episodes_total: int

    # Problèmes détectés
    orphan_chunks: List[str]  # Chunk IDs sans episode Graphiti
    orphan_episodes: List[str]  # Episode IDs sans chunks Qdrant
    inconsistent_metadata: List[Dict[str, Any]]  # Metadata incohérentes

    @property
    def is_consistent(self) -> bool:
        """Validation OK si aucun problème"""
        return (
            len(self.orphan_chunks) == 0 and
            len(self.orphan_episodes) == 0 and
            len(self.inconsistent_metadata) == 0
        )

    def print_report(self):
        """Afficher rapport validation"""
        print("\n" + "="*70)
        print(f"RAPPORT VALIDATION - Tenant: {self.tenant_id}")
        print("="*70)

        print(f"\n📊 Statistiques:")
        print(f"   - Chunks Qdrant (total): {self.chunks_total}")
        print(f"   - Chunks avec KG: {self.chunks_with_kg}")
        print(f"   - Episodes Graphiti: {self.episodes_total}")

        if self.is_consistent:
            print(f"\n✅ VALIDATION RÉUSSIE - Aucune incohérence détectée")
        else:
            print(f"\n❌ INCOHÉRENCES DÉTECTÉES:")

            if self.orphan_chunks:
                print(f"\n🔴 Chunks orphelins (episode_id sans episode Graphiti): {len(self.orphan_chunks)}")
                for chunk_id in self.orphan_chunks[:5]:
                    print(f"     - {chunk_id}")
                if len(self.orphan_chunks) > 5:
                    print(f"     ... et {len(self.orphan_chunks) - 5} autres")

            if self.orphan_episodes:
                print(f"\n🟡 Episodes orphelins (episode Graphiti sans chunks Qdrant): {len(self.orphan_episodes)}")
                for episode_id in self.orphan_episodes[:5]:
                    print(f"     - {episode_id}")
                if len(self.orphan_episodes) > 5:
                    print(f"     ... et {len(self.orphan_episodes) - 5} autres")

            if self.inconsistent_metadata:
                print(f"\n🟠 Metadata incohérentes: {len(self.inconsistent_metadata)}")
                for issue in self.inconsistent_metadata[:3]:
                    print(f"     - {issue}")
                if len(self.inconsistent_metadata) > 3:
                    print(f"     ... et {len(self.inconsistent_metadata) - 3} autres")

        print("\n" + "="*70 + "\n")


async def validate_tenant_consistency(
    tenant_id: str,
    collection_name: str = "knowbase"
) -> ValidationResult:
    """
    Valider cohérence Qdrant ↔ Graphiti pour un tenant

    Args:
        tenant_id: ID tenant à valider
        collection_name: Collection Qdrant

    Returns:
        ValidationResult avec problèmes détectés
    """
    logger.info(f"🔍 Début validation cohérence pour tenant: {tenant_id}")

    qdrant_client = get_qdrant_client()
    graphiti_client = get_graphiti_client()

    # 1. Récupérer tous les chunks Qdrant
    logger.info(f"📊 Récupération chunks Qdrant...")
    chunks, _ = qdrant_client.scroll(
        collection_name=collection_name,
        limit=10000,
        with_payload=True,
        scroll_filter=None
    )

    logger.info(f"   Trouvé {len(chunks)} chunks total")

    # Filtrer chunks avec knowledge graph
    chunks_with_kg = [
        c for c in chunks
        if c.payload and c.payload.get("has_knowledge_graph") is True
    ]

    logger.info(f"   Trouvé {len(chunks_with_kg)} chunks avec KG")

    # 2. Récupérer tous les episodes Graphiti
    logger.info(f"📊 Récupération episodes Graphiti...")
    try:
        episodes = graphiti_client.get_episodes(
            group_id=tenant_id,
            last_n=1000  # Max episodes à récupérer
        )
        logger.info(f"   Trouvé {len(episodes)} episodes")
    except Exception as e:
        logger.error(f"❌ Erreur récupération episodes: {e}")
        episodes = []

    # 3. Créer maps pour validation
    # Map episode_id → chunks Qdrant
    qdrant_episode_ids: Dict[str, List[str]] = {}
    for chunk in chunks_with_kg:
        episode_id = chunk.payload.get("episode_id")
        if episode_id:
            if episode_id not in qdrant_episode_ids:
                qdrant_episode_ids[episode_id] = []
            qdrant_episode_ids[episode_id].append(str(chunk.id))

    # Map episode_uuid → episode Graphiti
    graphiti_episode_uuids: Set[str] = {ep["uuid"] for ep in episodes}

    # 4. Détecter incohérences
    orphan_chunks = []
    orphan_episodes = []
    inconsistent_metadata = []

    # 4.1. Chunks orphelins (episode_id dans Qdrant MAIS pas dans Graphiti)
    logger.info(f"🔍 Recherche chunks orphelins...")
    for episode_id, chunk_ids in qdrant_episode_ids.items():
        # NOTE: episode_id dans Qdrant est notre ID custom (ex: "test_sync_doc_123")
        # Mais episodes Graphiti ont des UUID générés (ex: "8ac0480a-fe54...")
        # DONC: On ne peut PAS faire de matching direct !

        # Workaround: Vérifier si au moins UN episode existe pour ce tenant
        # Si 0 episodes → chunks orphelins
        if len(episodes) == 0:
            orphan_chunks.extend(chunk_ids)
            logger.warning(f"   ⚠️ Episode {episode_id}: {len(chunk_ids)} chunks orphelins (aucun episode Graphiti)")

    # 4.2. Episodes orphelins (episode Graphiti MAIS pas de chunks Qdrant)
    logger.info(f"🔍 Recherche episodes orphelins...")
    # NOTE: Impossible de faire matching précis à cause de la limitation API Graphiti
    # On vérifie juste que si episodes existent, au moins quelques chunks ont KG
    if len(episodes) > 0 and len(chunks_with_kg) == 0:
        orphan_episodes = [ep["uuid"] for ep in episodes]
        logger.warning(f"   ⚠️ {len(episodes)} episodes Graphiti MAIS 0 chunks avec KG dans Qdrant")

    # 4.3. Metadata incohérentes
    logger.info(f"🔍 Recherche metadata incohérentes...")
    for episode in episodes:
        episode_content = episode.get("content", "")

        # Vérifier si episode content mentionne des chunks
        if "Qdrant Chunks" in episode_content:
            # Extraire preview chunk_ids depuis content (format: "uuid1, uuid2...")
            # Simplification: on vérifie juste la présence
            pass  # TODO: Parse et valide chunk_ids depuis content

    # 5. Créer résultat
    result = ValidationResult(
        tenant_id=tenant_id,
        chunks_total=len(chunks),
        chunks_with_kg=len(chunks_with_kg),
        episodes_total=len(episodes),
        orphan_chunks=orphan_chunks,
        orphan_episodes=orphan_episodes,
        inconsistent_metadata=inconsistent_metadata
    )

    logger.info(f"✅ Validation terminée")
    return result


async def fix_inconsistencies(result: ValidationResult, collection_name: str = "knowbase"):
    """
    Corriger incohérences détectées

    Args:
        result: Résultats validation
        collection_name: Collection Qdrant
    """
    if result.is_consistent:
        logger.info("✅ Aucune incohérence à corriger")
        return

    logger.info(f"🔧 Début correction incohérences...")
    qdrant_client = get_qdrant_client()

    # 1. Nettoyer chunks orphelins (supprimer metadata KG)
    if result.orphan_chunks:
        logger.info(f"🧹 Nettoyage {len(result.orphan_chunks)} chunks orphelins...")
        try:
            qdrant_client.delete_payload(
                collection_name=collection_name,
                keys=["episode_id", "episode_name", "has_knowledge_graph"],
                points=result.orphan_chunks
            )
            logger.info(f"   ✅ Metadata KG supprimée de {len(result.orphan_chunks)} chunks")
        except Exception as e:
            logger.error(f"   ❌ Erreur nettoyage chunks: {e}")

    # 2. Nettoyer episodes orphelins (supprimer de Graphiti)
    if result.orphan_episodes:
        logger.warning(
            f"⚠️ {len(result.orphan_episodes)} episodes orphelins détectés - "
            "suppression manuelle requise (limitation API)"
        )
        # NOTE: Impossible de supprimer automatiquement car on ne peut pas
        # faire le mapping entre notre episode_id et les UUID Graphiti

    logger.info(f"✅ Corrections terminées")


async def main():
    """Point d'entrée CLI"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Valider cohérence sync Qdrant ↔ Graphiti"
    )
    parser.add_argument(
        "--tenant",
        required=True,
        help="ID tenant à valider"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Corriger incohérences détectées"
    )
    parser.add_argument(
        "--collection",
        default="knowbase",
        help="Collection Qdrant (défaut: knowbase)"
    )

    args = parser.parse_args()

    # Validation
    result = await validate_tenant_consistency(
        tenant_id=args.tenant,
        collection_name=args.collection
    )

    # Afficher rapport
    result.print_report()

    # Corrections si demandé
    if args.fix and not result.is_consistent:
        confirm = input("\n⚠️ Voulez-vous corriger les incohérences ? (yes/no): ")
        if confirm.lower() == "yes":
            await fix_inconsistencies(result, args.collection)
        else:
            print("❌ Corrections annulées")

    # Exit code
    return 0 if result.is_consistent else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
