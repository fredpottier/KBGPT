#!/usr/bin/env python3
"""
Script de migration Qdrant vers Graphiti
Importe les données existantes vers le Knowledge Graph Enterprise
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Ajouter le chemin racine pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.api.services.knowledge_graph import KnowledgeGraphService
from knowbase.api.schemas.knowledge_graph import (
    EntityCreate, RelationCreate, EntityType, RelationType
)

# Configuration logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class QdrantToGraphitiMigrator:
    """Migrateur de données Qdrant vers Graphiti"""

    def __init__(self):
        self.qdrant_client = get_qdrant_client()
        self.kg_service = KnowledgeGraphService()
        self.collection_names = ["knowbase", "rfp_qa"]  # Collections à migrer

        # Compteurs de migration
        self.stats = {
            "documents_processed": 0,
            "entities_created": 0,
            "relations_created": 0,
            "errors": 0,
            "skipped": 0
        }

    async def migrate_all(self) -> Dict[str, Any]:
        """
        Lance la migration complète de toutes les collections

        Returns:
            Rapport de migration avec statistiques
        """
        logger.info("🚀 Démarrage migration Qdrant -> Graphiti Enterprise")
        start_time = datetime.now()

        try:
            # Initialiser le service KG
            await self.kg_service._ensure_initialized()
            logger.info("✅ Knowledge Graph Enterprise initialisé")

            # Migrer chaque collection
            for collection_name in self.collection_names:
                logger.info(f"📂 Migration collection '{collection_name}'")
                await self._migrate_collection(collection_name)

            # Créer des relations inter-documents si possible
            logger.info("🔗 Création relations inter-documents")
            await self._create_document_relations()

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            # Rapport final
            report = {
                "status": "success",
                "duration_seconds": duration,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "collections_migrated": self.collection_names,
                "statistics": self.stats,
                "summary": f"Migration terminée: {self.stats['entities_created']} entités, "
                          f"{self.stats['relations_created']} relations créées"
            }

            logger.info("✅ Migration terminée avec succès!")
            logger.info(f"📊 Statistiques: {json.dumps(self.stats, indent=2)}")

            return report

        except Exception as e:
            logger.error(f"❌ Erreur migration: {e}")
            return {
                "status": "error",
                "error": str(e),
                "statistics": self.stats
            }

    async def _migrate_collection(self, collection_name: str):
        """Migre une collection Qdrant spécifique"""
        try:
            # Récupérer tous les documents de la collection
            documents = self._get_all_documents(collection_name)
            logger.info(f"📄 {len(documents)} documents trouvés dans '{collection_name}'")

            for doc_data in documents:
                try:
                    await self._process_document(doc_data, collection_name)
                    self.stats["documents_processed"] += 1

                except Exception as e:
                    logger.warning(f"⚠️ Erreur traitement document {doc_data.get('id', 'unknown')}: {e}")
                    self.stats["errors"] += 1
                    continue

        except Exception as e:
            logger.error(f"❌ Erreur migration collection {collection_name}: {e}")
            raise

    def _get_all_documents(self, collection_name: str) -> List[Dict[str, Any]]:
        """Récupère tous les documents d'une collection Qdrant"""
        try:
            # Faire une recherche large pour récupérer tous les documents
            search_result = self.qdrant_client.scroll(
                collection_name=collection_name,
                limit=10000,  # Limite élevée pour récupérer beaucoup de documents
                with_payload=True,
                with_vectors=False  # Pas besoin des vecteurs pour la migration
            )

            documents = []
            for point in search_result[0]:  # search_result est un tuple (points, next_page_offset)
                doc = {
                    "id": str(point.id),
                    "payload": point.payload
                }
                documents.append(doc)

            return documents

        except Exception as e:
            logger.error(f"Erreur récupération documents {collection_name}: {e}")
            return []

    async def _process_document(self, doc_data: Dict[str, Any], collection_name: str):
        """Traite un document individuel pour extraction d'entités"""
        payload = doc_data.get("payload", {})
        doc_id = doc_data.get("id")

        # Extraire les métadonnées importantes (structure réelle Qdrant)
        # Payload keys: text, language, document, solution, chunk, deck_summary, prompt_meta
        document_ref = payload.get("document", f"Document_{doc_id}")
        content = payload.get("text", payload.get("content", ""))
        solution = payload.get("solution", "")
        chunk_raw = payload.get("chunk", 0)

        # Convertir en types appropriés (peuvent être dict, str, int, etc.)
        document_ref = str(document_ref) if document_ref else f"Document_{doc_id}"
        solution = str(solution) if solution and solution != "" else ""

        # Chunk peut être dict, int ou autre - le convertir en int si possible
        try:
            chunk_id = int(chunk_raw) if chunk_raw else 0
        except (TypeError, ValueError):
            chunk_id = 0  # Fallback si conversion impossible

        # Construire un titre lisible
        title = f"{solution} - {document_ref}" if solution else document_ref

        # Déterminer le type d'entité basé sur la collection et les métadonnées
        entity_type = self._determine_entity_type(collection_name, payload)

        # Créer l'entité document
        try:
            entity = EntityCreate(
                name=f"{title} (chunk {chunk_id})" if chunk_id > 0 else title,
                entity_type=entity_type,
                description=self._generate_entity_description(payload, content),
                attributes={
                    "original_id": doc_id,
                    "collection": collection_name,
                    "document": document_ref,
                    "solution": solution,
                    "chunk_id": chunk_id,
                    "language": payload.get("language", ""),
                    "deck_summary": payload.get("deck_summary", ""),
                    "content_preview": content[:200] + "..." if len(content) > 200 else content,
                }
            )

            created_entity = await self.kg_service.create_entity(entity)
            self.stats["entities_created"] += 1
            logger.debug(f"✅ Entité créée: {created_entity.name}")

            # Extraire et créer des entités/relations additionnelles si pertinent
            await self._extract_additional_entities(created_entity, payload, content)

        except Exception as e:
            logger.error(f"❌ Erreur création entité pour document {doc_id}: {e}")
            raise

    def _determine_entity_type(self, collection_name: str, payload: Dict[str, Any]) -> EntityType:
        """Détermine le type d'entité basé sur la collection et métadonnées"""

        # Logique basée sur la collection
        if collection_name == "rfp_qa":
            return EntityType.PROCESS  # Q/A RFP = processus métier

        # Logique basée sur le champ solution ou document (peuvent être dict ou str)
        solution = payload.get("solution", "")
        document = payload.get("document", "")

        # Convertir en string si nécessaire
        solution_str = str(solution).lower() if solution else ""
        document_str = str(document).lower() if document else ""

        # Si une solution SAP est identifiée
        if solution_str and "sap" in solution_str:
            return EntityType.SOLUTION

        # Basé sur l'extension du document
        if any(ext in document_str for ext in [".pptx", ".ppt", ".pdf", ".docx", ".doc"]):
            return EntityType.DOCUMENT

        # Par défaut
        return EntityType.CONCEPT

    def _generate_entity_description(self, payload: Dict[str, Any], content: str) -> str:
        """Génère une description pour l'entité"""
        # Utiliser la structure réelle: document, solution, deck_summary
        document = payload.get("document", "")
        solution = payload.get("solution", "")
        deck_summary = payload.get("deck_summary", "")
        language = payload.get("language", "")

        # Convertir en strings si nécessaire
        document = str(document) if document else ""
        solution = str(solution) if solution else ""
        deck_summary = str(deck_summary) if deck_summary else ""
        language = str(language) if language else ""

        desc_parts = []

        if solution:
            desc_parts.append(f"Solution: {solution}")

        if document:
            try:
                desc_parts.append(f"Document: {Path(document).name}")
            except:
                desc_parts.append(f"Document: {document}")

        if deck_summary:
            desc_parts.append(f"Résumé: {deck_summary[:100]}")
        elif content:
            # Aperçu du contenu si pas de résumé
            content_preview = content.strip()[:150]
            if content_preview:
                desc_parts.append(f"Contenu: {content_preview}...")

        if language:
            desc_parts.append(f"Langue: {language}")

        return " | ".join(desc_parts) or "Document migré depuis Qdrant"

    async def _extract_additional_entities(self,
                                         main_entity,
                                         payload: Dict[str, Any],
                                         content: str):
        """Extrait des entités additionnelles du contenu si possible"""

        # Pour l'instant, logique simple d'extraction
        # Peut être étendu avec NLP plus avancé

        try:
            # Rechercher des mentions de solutions SAP dans le contenu
            sap_solutions = self._extract_sap_solutions(content)

            for solution_name in sap_solutions[:3]:  # Limiter à 3 pour éviter le spam
                try:
                    # Créer l'entité solution
                    solution_entity = EntityCreate(
                        name=solution_name,
                        entity_type=EntityType.SOLUTION,
                        description=f"Solution SAP mentionnée dans {main_entity.name}",
                        attributes={
                            "extracted_from": main_entity.uuid,
                            "extraction_method": "keyword_matching"
                        }
                    )

                    created_solution = await self.kg_service.create_entity(solution_entity)
                    self.stats["entities_created"] += 1

                    # Créer une relation "references"
                    relation = RelationCreate(
                        source_entity_id=main_entity.uuid,
                        target_entity_id=created_solution.uuid,
                        relation_type=RelationType.REFERENCES,
                        description=f"Le document fait référence à la solution {solution_name}",
                        confidence=0.7  # Confiance modérée pour extraction automatique
                    )

                    await self.kg_service.create_relation(relation)
                    self.stats["relations_created"] += 1

                except Exception as e:
                    logger.debug(f"⚠️ Erreur création entité solution {solution_name}: {e}")
                    continue

        except Exception as e:
            logger.debug(f"⚠️ Erreur extraction entités additionnelles: {e}")
            # Non critique, continuer

    def _extract_sap_solutions(self, content: str) -> List[str]:
        """Extrait des noms de solutions SAP du contenu"""
        solutions = []
        content_lower = content.lower()

        # Liste de solutions SAP communes
        sap_solutions = [
            "SAP S/4HANA", "SAP ECC", "SAP HANA", "SAP BW", "SAP BI", "SAP CRM",
            "SAP SRM", "SAP SCM", "SAP PLM", "SAP GRC", "SAP HCM", "SAP SuccessFactors",
            "SAP Concur", "SAP Ariba", "SAP Fieldglass", "SAP Analytics Cloud",
            "SAP ABAP", "SAP Fiori", "SAP UI5", "SAP Cloud Platform"
        ]

        for solution in sap_solutions:
            if solution.lower() in content_lower:
                solutions.append(solution)

        return list(set(solutions))  # Dédupliquer

    async def _create_document_relations(self):
        """Crée des relations entre documents basées sur leur similarité"""
        try:
            # Pour l'instant, une logique simple basée sur les sources
            # Peut être étendu avec de la similarité vectorielle plus tard

            # Récupérer toutes les relations existantes pour voir les documents
            relations = await self.kg_service.list_relations(limit=1000)

            # Grouper par source pour créer des relations "part_of"
            source_groups: Dict[str, List[str]] = {}

            for relation in relations:
                # Récupérer l'entité source pour analyser ses attributs
                entity = await self.kg_service.get_entity(relation.source_entity_id)
                if entity and entity.attributes.get("source"):
                    source = Path(entity.attributes["source"]).stem  # Nom fichier sans extension
                    if source not in source_groups:
                        source_groups[source] = []
                    source_groups[source].append(entity.uuid)

            # Créer des relations "part_of" entre documents du même fichier
            for source, entity_ids in source_groups.items():
                if len(entity_ids) > 1:  # Au moins 2 entités du même fichier
                    # Créer des relations entre les chunks
                    for i, source_id in enumerate(entity_ids):
                        for target_id in entity_ids[i+1:]:
                            try:
                                relation = RelationCreate(
                                    source_entity_id=source_id,
                                    target_entity_id=target_id,
                                    relation_type=RelationType.SIMILAR_TO,
                                    description=f"Documents provenant du même fichier: {source}",
                                    confidence=0.8
                                )

                                await self.kg_service.create_relation(relation)
                                self.stats["relations_created"] += 1

                            except Exception as e:
                                logger.debug(f"⚠️ Erreur création relation similarité: {e}")
                                continue

            logger.info(f"🔗 Relations inter-documents créées pour {len(source_groups)} fichiers")

        except Exception as e:
            logger.warning(f"⚠️ Erreur création relations documents: {e}")
            # Non critique


async def main():
    """Point d'entrée principal du script"""
    try:
        migrator = QdrantToGraphitiMigrator()

        print("🚀 Migration Qdrant vers Graphiti Enterprise")
        print("=" * 50)

        # Lancer la migration
        report = await migrator.migrate_all()

        # Afficher le rapport final
        print("\n📊 RAPPORT DE MIGRATION")
        print("=" * 50)
        print(f"Status: {report['status']}")

        if report["status"] == "success":
            print(f"Durée: {report['duration_seconds']:.1f} secondes")
            print(f"Collections: {', '.join(report['collections_migrated'])}")
            print("\n📈 Statistiques:")
            for key, value in report["statistics"].items():
                print(f"  {key}: {value}")
            print(f"\n✅ {report['summary']}")
        else:
            print(f"❌ Erreur: {report.get('error', 'Erreur inconnue')}")
            return 1

        return 0

    except KeyboardInterrupt:
        print("\n⚠️ Migration interrompue par l'utilisateur")
        return 130

    except Exception as e:
        print(f"❌ Erreur critique: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))