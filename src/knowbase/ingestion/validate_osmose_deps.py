"""
Script de validation des dépendances OSMOSE Pure.

À exécuter AVANT de lancer un import PPTX pour éviter de gaspiller des appels LLM.

Usage:
    docker-compose exec app python -m knowbase.ingestion.validate_osmose_deps
"""

import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def test_imports():
    """Test tous les imports critiques."""
    logger.info("=" * 80)
    logger.info("🔍 Test 1/6: Imports modules Python")
    logger.info("=" * 80)

    errors = []

    # Test 1: Semantic modules
    try:
        from knowbase.semantic import (
            SemanticProfile,
            ComplexityZone,
            CandidateEntity,
            CandidateRelation,
            Concept,
            CanonicalConcept,
            Topic,
            ConceptConnection,
            DocumentRole,
        )
        logger.info("✅ knowbase.semantic modules OK")
    except ImportError as e:
        errors.append(f"❌ knowbase.semantic: {e}")

    # Test 2: Semantic pipeline
    try:
        from knowbase.semantic.semantic_pipeline_v2 import SemanticPipelineV2, process_document_semantic_v2
        logger.info("✅ semantic_pipeline_v2 OK")
    except ImportError as e:
        errors.append(f"❌ semantic_pipeline_v2: {e}")

    # Test 3: OSMOSE integration
    try:
        from knowbase.ingestion.osmose_integration import process_document_with_osmose
        logger.info("✅ osmose_integration OK")
    except ImportError as e:
        errors.append(f"❌ osmose_integration: {e}")

    # Test 4: Clients
    try:
        from knowbase.common.clients.qdrant_client import get_qdrant_client
        logger.info("✅ qdrant_client OK")
    except ImportError as e:
        errors.append(f"❌ qdrant_client: {e}")

    try:
        from knowbase.common.llm_router import get_llm_router
        logger.info("✅ llm_router OK")
    except ImportError as e:
        errors.append(f"❌ llm_router: {e}")

    # Test 5: Services
    try:
        from knowbase.api.services.proto_kg_service import ProtoKGService
        logger.info("✅ proto_kg_service OK")
    except ImportError as e:
        errors.append(f"❌ proto_kg_service: {e}")

    if errors:
        logger.error("\n❌ ERREURS D'IMPORT DÉTECTÉES:")
        for err in errors:
            logger.error(f"  {err}")
        return False

    logger.info("\n✅ Tous les imports Python OK\n")
    return True


def test_spacy():
    """Test spaCy et modèles."""
    logger.info("=" * 80)
    logger.info("🔍 Test 2/6: spaCy et modèles NER")
    logger.info("=" * 80)

    try:
        import spacy
        logger.info("✅ spaCy installé")

        # Tester au moins un modèle
        try:
            nlp = spacy.load("en_core_web_sm")
            logger.info("✅ Modèle en_core_web_sm chargé")
            return True
        except OSError:
            logger.warning("⚠️  Modèle en_core_web_sm non trouvé")
            logger.warning("   Installation: docker-compose exec app python -m spacy download en_core_web_sm")
            return False

    except ImportError:
        logger.error("❌ spaCy non installé")
        logger.error("   Installation: docker-compose exec app pip install spacy>=3.7.2")
        return False


def test_neo4j_connection():
    """Test connexion Neo4j."""
    logger.info("=" * 80)
    logger.info("🔍 Test 3/6: Connexion Neo4j")
    logger.info("=" * 80)

    try:
        from neo4j import GraphDatabase
        from knowbase.config.settings import get_settings

        settings = get_settings()

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )

        with driver.session() as session:
            result = session.run("RETURN 1 as test")
            record = result.single()
            if record and record["test"] == 1:
                logger.info(f"✅ Neo4j connecté: {settings.neo4j_uri}")
                driver.close()
                return True

        driver.close()
        logger.error("❌ Neo4j: réponse invalide")
        return False

    except Exception as e:
        logger.error(f"❌ Neo4j connexion échouée: {e}")
        logger.error("   Vérifier: docker-compose ps neo4j")
        return False


def test_qdrant_connection():
    """Test connexion Qdrant."""
    logger.info("=" * 80)
    logger.info("🔍 Test 4/6: Connexion Qdrant")
    logger.info("=" * 80)

    try:
        from knowbase.common.clients.qdrant_client import get_qdrant_client

        client = get_qdrant_client()
        collections = client.get_collections()

        logger.info(f"✅ Qdrant connecté")
        logger.info(f"   Collections: {len(collections.collections)} trouvées")

        # Vérifier collection concepts_proto existe ou peut être créée
        collection_names = [c.name for c in collections.collections]
        if "concepts_proto" in collection_names:
            logger.info("✅ Collection 'concepts_proto' existe")
        else:
            logger.warning("⚠️  Collection 'concepts_proto' n'existe pas encore (sera créée)")

        return True

    except Exception as e:
        logger.error(f"❌ Qdrant connexion échouée: {e}")
        logger.error("   Vérifier: docker-compose ps qdrant")
        return False


def test_llm_config():
    """Test configuration LLM."""
    logger.info("=" * 80)
    logger.info("🔍 Test 5/6: Configuration LLM")
    logger.info("=" * 80)

    try:
        from knowbase.config.settings import get_settings

        settings = get_settings()

        if not settings.openai_api_key:
            logger.error("❌ OPENAI_API_KEY non configurée")
            logger.error("   Vérifier: .env contient OPENAI_API_KEY=sk-...")
            return False

        logger.info("✅ OPENAI_API_KEY configurée")
        logger.info(f"   Modèle Vision: {settings.model_vision}")
        logger.info(f"   Modèle Fast: {settings.model_fast}")

        return True

    except Exception as e:
        logger.error(f"❌ Configuration LLM échouée: {e}")
        return False


def test_osmose_config():
    """Test configuration OSMOSE."""
    logger.info("=" * 80)
    logger.info("🔍 Test 6/6: Configuration OSMOSE")
    logger.info("=" * 80)

    try:
        from knowbase.ingestion.osmose_integration import OsmoseIntegrationConfig

        config = OsmoseIntegrationConfig.from_env()

        logger.info("✅ Configuration OSMOSE chargée")
        logger.info(f"   OSMOSE activé: {config.enable_osmose}")
        logger.info(f"   OSMOSE pour PPTX: {config.osmose_for_pptx}")
        logger.info(f"   OSMOSE pour PDF: {config.osmose_for_pdf}")
        logger.info(f"   Proto-KG collection: {config.proto_kg_collection}")
        logger.info(f"   Timeout: {config.timeout_seconds}s")

        return True

    except Exception as e:
        logger.error(f"❌ Configuration OSMOSE échouée: {e}")
        return False


def main():
    """Exécute tous les tests."""
    logger.info("\n")
    logger.info("🌊 OSMOSE Pure - Validation Dépendances")
    logger.info("=" * 80)
    logger.info("Ce script vérifie que toutes les dépendances sont OK")
    logger.info("AVANT de lancer un import PPTX (pour éviter appels LLM inutiles)")
    logger.info("=" * 80)
    logger.info("\n")

    results = {
        "Imports Python": test_imports(),
        "spaCy": test_spacy(),
        "Neo4j": test_neo4j_connection(),
        "Qdrant": test_qdrant_connection(),
        "LLM Config": test_llm_config(),
        "OSMOSE Config": test_osmose_config(),
    }

    logger.info("\n")
    logger.info("=" * 80)
    logger.info("📊 RÉSUMÉ VALIDATION")
    logger.info("=" * 80)

    all_ok = True
    for test_name, result in results.items():
        status = "✅ OK" if result else "❌ ÉCHEC"
        logger.info(f"{test_name:20s} : {status}")
        if not result:
            all_ok = False

    logger.info("=" * 80)

    if all_ok:
        logger.info("\n🎉 TOUTES LES VALIDATIONS RÉUSSIES")
        logger.info("✅ Vous pouvez lancer un import PPTX en toute sécurité")
        logger.info("\n")
        return 0
    else:
        logger.error("\n❌ CERTAINES VALIDATIONS ONT ÉCHOUÉ")
        logger.error("⚠️  NE PAS LANCER D'IMPORT PPTX - Corrigez d'abord les erreurs ci-dessus")
        logger.error("   (évite de gaspiller des appels LLM Vision)")
        logger.error("\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
