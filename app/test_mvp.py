#!/usr/bin/env python
"""
Test script pour valider l'intégration MVP V1 dans le pipeline Pass 1.

Ce script:
1. Crée des données de test simulant un document avec patterns ClaimKey
2. Exécute Pass 1 avec enrichissement MVP V1
3. Persiste les résultats dans Neo4j
4. Vérifie que les InformationMVP et ClaimKey sont créés
5. Teste l'API Challenge contre ces données

Usage:
    docker exec knowbase-app python scripts/test_mvp_v1_pipeline.py
"""

import asyncio
import logging
import sys
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def create_test_document():
    """Crée un document de test avec patterns ClaimKey reconnus."""
    return {
        "doc_id": "test_mvp_v1_doc",
        "doc_title": "SAP S/4HANA Cloud Security Guide - Test Document",
        "content": """
# SAP S/4HANA Cloud Security Guide

## 1. Transport Layer Security

All communications must use TLS 1.2 or higher. TLS 1.3 is supported and recommended for
enhanced security. Legacy protocols such as SSL and TLS 1.0/1.1 are not supported.

The system enforces minimum TLS 1.2 for all API endpoints.

## 2. Service Level Agreement

SAP guarantees 99.95% availability for production systems under the standard SLA.
For enhanced SLA customers, availability reaches 99.99%.

The SLA excludes scheduled maintenance windows which are announced 7 days in advance.

## 3. Backup and Recovery

Backups are performed daily for all customer tenants. Full system backups run every
24 hours with incremental backups every 4 hours.

The retention period is 30 days for standard backups. Extended retention of 90 days
is available for compliance requirements.

Customer is responsible for application-level backup configurations.
SAP manages infrastructure backups automatically.

## 4. Encryption

All data is encrypted at rest using AES-256 encryption. Encryption in transit is
mandatory for all connections.

Database encryption is enabled by default and cannot be disabled.
        """,
        "chunks": {
            "chunk_001": "All communications must use TLS 1.2 or higher. TLS 1.3 is supported and recommended.",
            "chunk_002": "The system enforces minimum TLS 1.2 for all API endpoints.",
            "chunk_003": "SAP guarantees 99.95% availability for production systems under the standard SLA.",
            "chunk_004": "For enhanced SLA customers, availability reaches 99.99%.",
            "chunk_005": "Backups are performed daily for all customer tenants.",
            "chunk_006": "The retention period is 30 days for standard backups.",
            "chunk_007": "Customer is responsible for application-level backup configurations.",
            "chunk_008": "All data is encrypted at rest using AES-256 encryption.",
            "chunk_009": "Encryption in transit is mandatory for all connections.",
        }
    }


def create_mock_docitems(chunks: dict) -> dict:
    """Crée des DocItems mock pour les chunks."""
    from knowbase.stratified.models import DocItem

    docitems = {}
    for i, (chunk_id, text) in enumerate(chunks.items()):
        item_id = f"item_{i:03d}"
        docitems[item_id] = DocItem(
            item_id=item_id,
            label="text",
            text=text,
            level=0,
            prov=[],
        )
    return docitems


def run_pass1_test(doc_data: dict, neo4j_driver) -> dict:
    """Exécute Pass 1 avec enrichissement MVP V1."""
    from knowbase.stratified.pass1.orchestrator import Pass1OrchestratorV2
    from knowbase.stratified.pass1.persister import Pass1PersisterV2

    logger.info("=" * 60)
    logger.info("DÉMARRAGE TEST PIPELINE MVP V1")
    logger.info("=" * 60)

    # Créer les DocItems mock
    docitems = create_mock_docitems(doc_data["chunks"])

    # Créer le mapping chunk → docitem
    chunk_to_docitem_map = {}
    for i, chunk_id in enumerate(doc_data["chunks"].keys()):
        item_id = f"item_{i:03d}"
        chunk_to_docitem_map[chunk_id] = [f"default:{doc_data['doc_id']}:{item_id}"]

    # Créer le nœud Document dans Neo4j (prérequis)
    with neo4j_driver.session() as session:
        session.run("""
            MERGE (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
            SET d.title = $title,
                d.created_at = datetime()
        """, {
            "doc_id": doc_data["doc_id"],
            "tenant_id": "default",
            "title": doc_data["doc_title"]
        })
        logger.info(f"Document node créé: {doc_data['doc_id']}")

    # Exécuter Pass 1
    # Note: Sans LLM, on utilise allow_fallback=True pour les heuristiques
    orchestrator = Pass1OrchestratorV2(
        llm_client=None,  # Pas de LLM pour ce test
        allow_fallback=True,  # Utiliser les heuristiques
        tenant_id="default"
    )

    logger.info("Exécution Pass 1...")
    result = orchestrator.process(
        doc_id=doc_data["doc_id"],
        doc_title=doc_data["doc_title"],
        content=doc_data["content"],
        docitems=docitems,
        chunks=doc_data["chunks"],
        chunk_to_docitem_map=chunk_to_docitem_map
    )

    logger.info(f"Pass 1 terminé:")
    logger.info(f"  - Themes: {result.stats.themes_count}")
    logger.info(f"  - Concepts: {result.stats.concepts_count}")
    logger.info(f"  - Informations: {result.stats.assertions_promoted}")
    logger.info(f"  - InformationMVP: {len(result.informations_mvp)}")

    # Persister les résultats
    logger.info("Persistance dans Neo4j...")
    persister = Pass1PersisterV2(neo4j_driver=neo4j_driver, tenant_id="default")
    persist_stats = persister.persist(result)

    logger.info(f"Persistance terminée:")
    logger.info(f"  - InformationMVP créées: {persist_stats.get('informations_mvp', 0)}")
    logger.info(f"  - ClaimKeys créés: {persist_stats.get('claimkeys', 0)}")

    return {
        "pass1_result": result,
        "persist_stats": persist_stats
    }


def verify_neo4j_data(neo4j_driver) -> dict:
    """Vérifie les données créées dans Neo4j."""
    logger.info("=" * 60)
    logger.info("VÉRIFICATION NEO4J")
    logger.info("=" * 60)

    with neo4j_driver.session() as session:
        # Compter les InformationMVP
        result = session.run("""
            MATCH (i:InformationMVP {tenant_id: 'default'})
            RETURN count(i) as count
        """)
        info_count = result.single()["count"]
        logger.info(f"InformationMVP total: {info_count}")

        # Compter les ClaimKeys
        result = session.run("""
            MATCH (ck:ClaimKey {tenant_id: 'default'})
            RETURN count(ck) as count
        """)
        claimkey_count = result.single()["count"]
        logger.info(f"ClaimKey total: {claimkey_count}")

        # Compter les relations ANSWERS
        result = session.run("""
            MATCH (i:InformationMVP)-[:ANSWERS]->(ck:ClaimKey)
            WHERE i.tenant_id = 'default'
            RETURN count(*) as count
        """)
        answers_count = result.single()["count"]
        logger.info(f"Relations ANSWERS: {answers_count}")

        # Lister les InformationMVP avec leurs ClaimKeys
        result = session.run("""
            MATCH (i:InformationMVP {tenant_id: 'default'})
            OPTIONAL MATCH (i)-[:ANSWERS]->(ck:ClaimKey)
            RETURN i.information_id as id,
                   i.text as text,
                   i.value_raw as value,
                   i.promotion_status as status,
                   ck.claimkey_id as claimkey
            LIMIT 10
        """)

        logger.info("\nÉchantillon InformationMVP:")
        for record in result:
            logger.info(f"  - {record['id'][:30]}... | {record['status']} | CK: {record['claimkey']}")
            if record['value']:
                logger.info(f"    Value: {record['value']}")

        return {
            "informations_mvp": info_count,
            "claimkeys": claimkey_count,
            "answers_relations": answers_count
        }


async def test_challenge_api(neo4j_driver) -> dict:
    """Teste l'API Challenge contre les données créées."""
    from knowbase.api.services.challenge_service import TextChallenger

    logger.info("=" * 60)
    logger.info("TEST API CHALLENGE")
    logger.info("=" * 60)

    challenger = TextChallenger(neo4j_driver, tenant_id="default")

    # Test 1: TLS version
    test_texts = [
        "Our system requires TLS 1.2 minimum",
        "We guarantee 99.95% availability",
        "Backups are performed daily",
        "Data is encrypted at rest",
    ]

    results = []
    for text in test_texts:
        logger.info(f"\nChallenge: '{text}'")
        result = await challenger.challenge(text)

        for match in result.matches:
            logger.info(f"  → Status: {match.status}")
            logger.info(f"    ClaimKey: {match.claimkey_id}")
            if match.corpus_matches:
                logger.info(f"    Corpus: {match.corpus_matches[0].value_raw}")

        results.append({
            "text": text,
            "claims_found": result.claims_found,
            "matches": [
                {
                    "status": m.status.value,
                    "claimkey_id": m.claimkey_id,
                    "corpus_value": m.corpus_matches[0].value_raw if m.corpus_matches else None
                }
                for m in result.matches
            ]
        })

    return results


def cleanup_test_data(neo4j_driver):
    """Nettoie les données de test."""
    logger.info("Nettoyage des données de test...")

    with neo4j_driver.session() as session:
        # Supprimer les InformationMVP de test
        result = session.run("""
            MATCH (i:InformationMVP {document_id: 'test_mvp_v1_doc'})
            DETACH DELETE i
            RETURN count(*) as deleted
        """)
        deleted = result.single()["deleted"]
        logger.info(f"  InformationMVP supprimées: {deleted}")

        # Supprimer le document de test
        result = session.run("""
            MATCH (d:Document {doc_id: 'test_mvp_v1_doc'})
            DETACH DELETE d
            RETURN count(*) as deleted
        """)
        logger.info(f"  Document supprimé")

        # Note: On garde les ClaimKeys car ils sont partagés


async def main():
    """Point d'entrée principal."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    logger.info("=" * 60)
    logger.info("TEST MVP V1 PIPELINE - DÉMARRAGE")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # Connexion Neo4j
    neo4j_client = get_neo4j_client()
    driver = neo4j_client.driver

    try:
        # 1. Créer les données de test
        doc_data = create_test_document()

        # 2. Exécuter Pass 1
        test_results = run_pass1_test(doc_data, driver)

        # 3. Vérifier Neo4j
        neo4j_stats = verify_neo4j_data(driver)

        # 4. Tester l'API Challenge
        challenge_results = await test_challenge_api(driver)

        # Résumé
        logger.info("=" * 60)
        logger.info("RÉSUMÉ")
        logger.info("=" * 60)
        logger.info(f"InformationMVP créées: {neo4j_stats['informations_mvp']}")
        logger.info(f"ClaimKeys créés: {neo4j_stats['claimkeys']}")
        logger.info(f"Relations ANSWERS: {neo4j_stats['answers_relations']}")
        logger.info(f"Tests Challenge: {len(challenge_results)}")

        # Succès ?
        success = (
            neo4j_stats['informations_mvp'] > 0 and
            neo4j_stats['claimkeys'] > 0
        )

        if success:
            logger.info("\n✅ TEST MVP V1 PIPELINE: SUCCÈS")
        else:
            logger.error("\n❌ TEST MVP V1 PIPELINE: ÉCHEC")
            logger.error("Aucune InformationMVP ou ClaimKey créée")

        return success

    except Exception as e:
        logger.error(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Cleanup optionnel (commenté pour permettre l'inspection)
        # cleanup_test_data(driver)
        pass


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
