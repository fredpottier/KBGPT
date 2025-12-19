#!/usr/bin/env python3
"""
🌊 OSMOSE - Reset Domain Specialization

Script pour réinitialiser complètement la spécialisation domaine de l'instance.
Permet de revenir à un état "vierge" (domain-agnostic) pour:
- Changer de client/domaine
- Tester une nouvelle configuration
- Livraison client neuve

Usage:
    # Reset standard (données uniquement, préserve extraction_cache)
    docker-compose exec app python scripts/reset_domain.py

    # Reset complet incluant le schéma Neo4j
    docker-compose exec app python scripts/reset_domain.py --full

    # Reset avec purge des caches d'extraction (ATTENTION: devra re-parser tous les documents)
    docker-compose exec app python scripts/reset_domain.py --purge-extraction-cache

    # Dry-run: afficher ce qui serait fait sans rien exécuter
    docker-compose exec app python scripts/reset_domain.py --dry-run

Options:
    --full                    Purge complète incluant schéma Neo4j (constraints/indexes)
    --purge-extraction-cache  Supprime aussi data/extraction_cache/ (économise disque mais force re-extraction)
    --keep-domain-context     Conserve le Domain Context configuré (seulement données apprises)
    --dry-run                 Affiche les actions sans les exécuter
    -y, --yes                 Skip confirmation (pour scripts automatisés)

Ce que ce script SUPPRIME:
- Neo4j: CandidateEntity, CandidateRelation, CanonicalEntity, DocumentNode, tous les nodes appris
- Qdrant: Collections knowbase, rfp_qa, knowwhere_proto
- Redis: Caches et queues (job queue vidée)
- Files: data/docs_done/*, data/status/*.status

Ce que ce script PRÉSERVE (par défaut):
- data/extraction_cache/ : Caches d'extraction LLM (économise coûts re-parsing)
- config/ : Fichiers configuration (ontologies vides restent vides)
- Domain Context : Profil métier configuré (option --keep-domain-context)
"""

import asyncio
import argparse
import sys
import os
import shutil
from pathlib import Path
from typing import List, Optional

# Ajouter le path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from neo4j import AsyncGraphDatabase
except ImportError:
    AsyncGraphDatabase = None
    print("⚠️  neo4j driver non disponible - Neo4j sera skippé")

try:
    from qdrant_client import QdrantClient
except ImportError:
    QdrantClient = None
    print("⚠️  qdrant_client non disponible - Qdrant sera skippé")

try:
    import redis
except ImportError:
    redis = None
    print("⚠️  redis non disponible - Redis sera skippé")


class DomainResetter:
    """Gestionnaire de reset domain avec options configurables."""

    def __init__(
        self,
        full: bool = False,
        purge_extraction_cache: bool = False,
        keep_domain_context: bool = False,
        dry_run: bool = False
    ):
        self.full = full
        self.purge_extraction_cache = purge_extraction_cache
        self.keep_domain_context = keep_domain_context
        self.dry_run = dry_run
        self.stats = {
            "neo4j_nodes_deleted": 0,
            "qdrant_collections_deleted": [],
            "redis_keys_deleted": 0,
            "files_deleted": 0,
            "errors": []
        }

        # Chemins
        self.base_path = Path(__file__).parent.parent
        self.data_path = self.base_path / "data"

    def _action(self, message: str):
        """Affiche une action (préfixée [DRY-RUN] si dry_run)."""
        prefix = "[DRY-RUN] " if self.dry_run else ""
        print(f"   {prefix}{message}")

    async def reset_neo4j(self) -> bool:
        """Reset Neo4j: supprime toutes les données apprises."""
        if AsyncGraphDatabase is None:
            print("⏭️  Neo4j skippé (driver non disponible)")
            return True

        print("🗄️  Reset Neo4j...")

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

        try:
            driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

            async with driver.session() as session:
                # 1. Compter les nodes par label
                labels_to_delete = [
                    "CandidateEntity",
                    "CandidateRelation",
                    "CanonicalEntity",
                    "DocumentNode",
                    "ConceptNode",
                    "EntityNode",
                    "Chunk"
                ]

                # Ajouter DomainContext si on ne le garde pas
                if not self.keep_domain_context:
                    labels_to_delete.append("DomainContext")

                total_count = 0
                for label in labels_to_delete:
                    result = await session.run(
                        f"MATCH (n:{label}) RETURN count(n) as c"
                    )
                    record = await result.single()
                    count = record["c"] if record else 0
                    if count > 0:
                        self._action(f"Suppression {count} nodes :{label}")
                        total_count += count

                        if not self.dry_run:
                            # Supprimer par batch pour éviter OOM
                            await session.run(f"""
                                MATCH (n:{label})
                                CALL {{
                                    WITH n
                                    DETACH DELETE n
                                }} IN TRANSACTIONS OF 1000 ROWS
                            """)

                self.stats["neo4j_nodes_deleted"] = total_count

                # 2. Reset complet: supprimer constraints/indexes
                if self.full:
                    print("   🔧 Reset schéma Neo4j (constraints/indexes)...")

                    # Lister tous les constraints
                    result = await session.run("SHOW CONSTRAINTS")
                    constraints = [record["name"] async for record in result]

                    for constraint_name in constraints:
                        if constraint_name and "candidate" in constraint_name.lower():
                            self._action(f"DROP CONSTRAINT {constraint_name}")
                            if not self.dry_run:
                                try:
                                    await session.run(f"DROP CONSTRAINT {constraint_name} IF EXISTS")
                                except Exception as e:
                                    self.stats["errors"].append(f"Constraint {constraint_name}: {e}")

                    # Lister tous les indexes
                    result = await session.run("SHOW INDEXES")
                    indexes = [record["name"] async for record in result]

                    for index_name in indexes:
                        if index_name and "candidate" in index_name.lower():
                            self._action(f"DROP INDEX {index_name}")
                            if not self.dry_run:
                                try:
                                    await session.run(f"DROP INDEX {index_name} IF EXISTS")
                                except Exception as e:
                                    self.stats["errors"].append(f"Index {index_name}: {e}")

                if total_count > 0:
                    print(f"   ✅ {total_count} nodes Neo4j supprimés")
                else:
                    print("   ℹ️  Aucune donnée Neo4j à supprimer")

            await driver.close()
            return True

        except Exception as e:
            print(f"   ❌ Erreur Neo4j: {e}")
            self.stats["errors"].append(f"Neo4j: {e}")
            return False

    def reset_qdrant(self) -> bool:
        """Reset Qdrant: supprime toutes les collections de documents."""
        if QdrantClient is None:
            print("⏭️  Qdrant skippé (client non disponible)")
            return True

        print("📊 Reset Qdrant...")

        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))

        try:
            client = QdrantClient(host=qdrant_host, port=qdrant_port)

            # Collections à supprimer
            collections_to_delete = [
                "knowbase",           # Base de connaissances principale
                "rfp_qa",             # Questions/Réponses RFP
                "knowwhere_proto",    # Proto-KG OSMOSE
                "documents",          # Documents indexés
            ]

            # Récupérer les collections existantes
            existing = client.get_collections()
            existing_names = [c.name for c in existing.collections]

            deleted = []
            for collection in collections_to_delete:
                if collection in existing_names:
                    self._action(f"Suppression collection '{collection}'")
                    if not self.dry_run:
                        client.delete_collection(collection)
                    deleted.append(collection)

            self.stats["qdrant_collections_deleted"] = deleted

            if deleted:
                print(f"   ✅ {len(deleted)} collections Qdrant supprimées: {', '.join(deleted)}")
            else:
                print("   ℹ️  Aucune collection Qdrant à supprimer")

            return True

        except Exception as e:
            print(f"   ❌ Erreur Qdrant: {e}")
            self.stats["errors"].append(f"Qdrant: {e}")
            return False

    def reset_redis(self) -> bool:
        """Reset Redis: vide les caches et queues."""
        if redis is None:
            print("⏭️  Redis skippé (client non disponible)")
            return True

        print("🔴 Reset Redis...")

        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))

        try:
            client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)

            # Compter les clés
            keys_count = client.dbsize()

            self._action(f"FLUSHDB ({keys_count} clés)")

            if not self.dry_run and keys_count > 0:
                client.flushdb()

            self.stats["redis_keys_deleted"] = keys_count

            if keys_count > 0:
                print(f"   ✅ {keys_count} clés Redis supprimées")
            else:
                print("   ℹ️  Redis déjà vide")

            return True

        except Exception as e:
            print(f"   ❌ Erreur Redis: {e}")
            self.stats["errors"].append(f"Redis: {e}")
            return False

    def reset_files(self) -> bool:
        """Reset fichiers: docs_done, status, et optionnellement extraction_cache."""
        print("📁 Reset fichiers...")

        dirs_to_clean = [
            ("docs_done", self.data_path / "docs_done"),
            ("docs_in", self.data_path / "docs_in"),
            ("status", self.data_path / "status"),
        ]

        # Optionnel: extraction_cache
        if self.purge_extraction_cache:
            dirs_to_clean.append(("extraction_cache", self.data_path / "extraction_cache"))

        files_deleted = 0

        for name, dir_path in dirs_to_clean:
            if dir_path.exists():
                # Compter les fichiers
                files = list(dir_path.glob("*"))
                file_count = len([f for f in files if f.is_file()])

                if file_count > 0:
                    self._action(f"Nettoyage {name}/ ({file_count} fichiers)")

                    if not self.dry_run:
                        for f in files:
                            if f.is_file():
                                f.unlink()
                            elif f.is_dir() and name != "extraction_cache":
                                # Garder les sous-dossiers sauf pour extraction_cache
                                shutil.rmtree(f)

                    files_deleted += file_count

        # Nettoyer public/slides et public/thumbnails si présents
        public_dirs = [
            ("public/slides", self.data_path / "public" / "slides"),
            ("public/thumbnails", self.data_path / "public" / "thumbnails"),
        ]

        for name, dir_path in public_dirs:
            if dir_path.exists():
                files = list(dir_path.glob("*"))
                file_count = len(files)
                if file_count > 0:
                    self._action(f"Nettoyage {name}/ ({file_count} fichiers)")
                    if not self.dry_run:
                        for f in files:
                            if f.is_file():
                                f.unlink()
                            elif f.is_dir():
                                shutil.rmtree(f)
                    files_deleted += file_count

        self.stats["files_deleted"] = files_deleted

        if files_deleted > 0:
            print(f"   ✅ {files_deleted} fichiers supprimés")
        else:
            print("   ℹ️  Aucun fichier à supprimer")

        return True

    async def run(self) -> bool:
        """Exécute le reset complet."""
        print()
        print("=" * 70)
        print("🌊 OSMOSE - Reset Domain Specialization")
        print("=" * 70)
        print()

        # Résumé des options
        print("📋 Configuration:")
        print(f"   • Mode: {'COMPLET (incluant schéma)' if self.full else 'DONNÉES SEULEMENT'}")
        print(f"   • Dry-run: {'OUI' if self.dry_run else 'NON'}")
        print(f"   • Purge extraction_cache: {'OUI (devra re-parser!)' if self.purge_extraction_cache else 'NON (préservé)'}")
        print(f"   • Conserver Domain Context: {'OUI' if self.keep_domain_context else 'NON'}")
        print()

        # Exécution
        success = True

        # 1. Neo4j
        if not await self.reset_neo4j():
            success = False
        print()

        # 2. Qdrant
        if not self.reset_qdrant():
            success = False
        print()

        # 3. Redis
        if not self.reset_redis():
            success = False
        print()

        # 4. Fichiers
        if not self.reset_files():
            success = False
        print()

        # Résumé final
        print("=" * 70)
        if self.dry_run:
            print("📝 RÉSUMÉ DRY-RUN (aucune modification effectuée)")
        else:
            print("📊 RÉSUMÉ DES ACTIONS")
        print("=" * 70)
        print(f"   • Neo4j nodes supprimés: {self.stats['neo4j_nodes_deleted']}")
        print(f"   • Qdrant collections supprimées: {', '.join(self.stats['qdrant_collections_deleted']) or 'aucune'}")
        print(f"   • Redis clés supprimées: {self.stats['redis_keys_deleted']}")
        print(f"   • Fichiers supprimés: {self.stats['files_deleted']}")

        if self.stats["errors"]:
            print()
            print("⚠️  ERREURS RENCONTRÉES:")
            for error in self.stats["errors"]:
                print(f"   • {error}")
            success = False

        print()
        if success and not self.dry_run:
            print("✅ Reset domain terminé avec succès!")
            print()
            print("📌 PROCHAINES ÉTAPES:")
            print("   1. Configurer le nouveau Domain Context via le frontend")
            print("   2. Importer les documents du nouveau domaine")
            print("   3. La spécialisation s'opérera progressivement")
        elif self.dry_run:
            print("ℹ️  Mode dry-run: aucune modification effectuée")
            print("   Relancer sans --dry-run pour exécuter réellement")
        else:
            print("⚠️  Reset terminé avec des erreurs (voir ci-dessus)")

        print("=" * 70)
        print()

        return success


async def main():
    parser = argparse.ArgumentParser(
        description="🌊 OSMOSE - Reset Domain Specialization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python scripts/reset_domain.py                       # Reset standard (préserve extraction_cache)
  python scripts/reset_domain.py --dry-run             # Voir ce qui serait fait
  python scripts/reset_domain.py --full                # Reset complet incluant schéma Neo4j
  python scripts/reset_domain.py --purge-extraction-cache  # Purge tout (force re-parsing)
  python scripts/reset_domain.py --keep-domain-context # Garde le profil métier configuré

⚠️  ATTENTION:
  - Ce script supprime TOUTES les données apprises (concepts, relations, embeddings)
  - Par défaut, extraction_cache est PRÉSERVÉ (économise coûts LLM au re-import)
  - Utiliser --purge-extraction-cache pour tout supprimer (libère disque)
        """
    )

    parser.add_argument(
        '--full',
        action='store_true',
        help='Reset complet incluant schéma Neo4j (constraints/indexes)'
    )

    parser.add_argument(
        '--purge-extraction-cache',
        action='store_true',
        help='Supprime aussi data/extraction_cache/ (économise disque mais force re-extraction)'
    )

    parser.add_argument(
        '--keep-domain-context',
        action='store_true',
        help='Conserve le Domain Context configuré (seulement données apprises)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Affiche les actions sans les exécuter'
    )

    parser.add_argument(
        '-y', '--yes',
        action='store_true',
        help='Skip confirmation (pour scripts automatisés)'
    )

    args = parser.parse_args()

    # Confirmation sauf si --yes ou --dry-run
    if not args.yes and not args.dry_run:
        print()
        print("⚠️  ATTENTION: Cette opération va supprimer TOUTES les données apprises!")
        print()
        print("   Cela inclut:")
        print("   - Tous les concepts et relations extraits (Neo4j)")
        print("   - Tous les embeddings et index de recherche (Qdrant)")
        print("   - Tous les caches de session (Redis)")
        print("   - Tous les documents traités (docs_done/)")
        print()

        if args.purge_extraction_cache:
            print("   🚨 --purge-extraction-cache est activé:")
            print("   - Les caches d'extraction LLM seront aussi supprimés")
            print("   - Le re-import nécessitera de re-parser tous les documents (coûteux!)")
            print()

        confirm = input("Continuer? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes", "oui"):
            print("Annulé.")
            sys.exit(0)

    # Exécution
    resetter = DomainResetter(
        full=args.full,
        purge_extraction_cache=args.purge_extraction_cache,
        keep_domain_context=args.keep_domain_context,
        dry_run=args.dry_run
    )

    success = await resetter.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
