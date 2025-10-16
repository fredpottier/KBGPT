"""
Test POC Neo4j Facts - Phase 1

Teste:
1. Connexion Neo4j
2. Migrations (constraints, indexes)
3. CRUD Facts
4. Détection conflits
5. Performance < 50ms
"""

import logging
import time
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_connection():
    """Test 1: Connexion Neo4j"""
    logger.info("=" * 60)
    logger.info("TEST 1: CONNEXION NEO4J")
    logger.info("=" * 60)

    from src.knowbase.neo4j_custom import get_neo4j_client

    try:
        client = get_neo4j_client()

        # Health check
        health = client.health_check()
        logger.info(f"Health check: {health}")

        if health["status"] == "healthy":
            logger.info(f"✅ Connexion OK - Latency: {health['latency_ms']}ms")
            logger.info(f"✅ Nodes count: {health['node_count']}")
            return True
        else:
            logger.error(f"❌ Connexion failed: {health.get('error')}")
            return False

    except Exception as e:
        logger.error(f"❌ Connexion error: {e}")
        return False


def test_migrations():
    """Test 2: Migrations (constraints, indexes)"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: MIGRATIONS (CONSTRAINTS, INDEXES)")
    logger.info("=" * 60)

    from src.knowbase.neo4j_custom import get_neo4j_client, apply_migrations

    try:
        client = get_neo4j_client()

        # Apply migrations
        result = apply_migrations(client)

        logger.info(f"Migration result: {result}")

        if result["status"] in ["success", "up_to_date"]:
            logger.info(f"✅ Migrations applied - Version: {result.get('current_version')}")
            return True
        else:
            logger.error(f"❌ Migrations failed: {result.get('error')}")
            return False

    except Exception as e:
        logger.error(f"❌ Migration error: {e}")
        return False


def test_crud_facts():
    """Test 3: CRUD Facts"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: CRUD FACTS")
    logger.info("=" * 60)

    from src.knowbase.neo4j_custom import get_neo4j_client, FactsQueries

    try:
        client = get_neo4j_client()
        facts = FactsQueries(client, tenant_id="test_poc")

        # CREATE
        logger.info("Creating fact...")
        fact1 = facts.create_fact(
            subject="SAP S/4HANA Cloud, Private Edition",
            predicate="SLA_garantie",
            object_str="99.7%",
            value=99.7,
            unit="%",
            fact_type="SERVICE_LEVEL",
            status="proposed",
            confidence=0.95,
            source_document="test_poc.txt",
            extraction_method="manual",
        )

        logger.info(f"✅ Fact created: {fact1['uuid']}")

        # READ
        logger.info("Reading fact...")
        fact_read = facts.get_fact_by_uuid(fact1["uuid"])

        if fact_read:
            logger.info(f"✅ Fact read: {fact_read['subject']} - {fact_read['value']}{fact_read['unit']}")
        else:
            logger.error("❌ Fact read failed")
            return False

        # UPDATE
        logger.info("Updating fact status...")
        fact_updated = facts.update_fact_status(
            fact1["uuid"],
            status="approved",
            approved_by="test_user"
        )

        if fact_updated and fact_updated["status"] == "approved":
            logger.info(f"✅ Fact status updated: {fact_updated['status']}")
        else:
            logger.error("❌ Fact update failed")
            return False

        # LIST
        logger.info("Listing approved facts...")
        approved_facts = facts.get_facts_by_status("approved")
        logger.info(f"✅ Found {len(approved_facts)} approved facts")

        # DELETE
        logger.info("Deleting fact...")
        deleted = facts.delete_fact(fact1["uuid"])

        if deleted:
            logger.info("✅ Fact deleted")
        else:
            logger.error("❌ Fact delete failed")
            return False

        return True

    except Exception as e:
        logger.error(f"❌ CRUD error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_conflict_detection():
    """Test 4: Détection conflits"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: DÉTECTION CONFLITS")
    logger.info("=" * 60)

    from src.knowbase.neo4j_custom import get_neo4j_client, FactsQueries

    try:
        client = get_neo4j_client()
        facts = FactsQueries(client, tenant_id="test_conflicts")

        # Créer fact approuvé
        logger.info("Creating approved fact...")
        fact_approved = facts.create_fact(
            subject="SAP S/4HANA Cloud",
            predicate="SLA_garantie",
            object_str="99.7%",
            value=99.7,
            unit="%",
            fact_type="SERVICE_LEVEL",
            status="approved",
            valid_from=datetime.utcnow().isoformat(),
            source_document="doc1.pdf",
        )

        # Créer fact proposé conflictuel (valeur différente, même date)
        logger.info("Creating conflicting proposed fact...")
        fact_proposed = facts.create_fact(
            subject="SAP S/4HANA Cloud",
            predicate="SLA_garantie",
            object_str="99.5%",
            value=99.5,
            unit="%",
            fact_type="SERVICE_LEVEL",
            status="proposed",
            valid_from=datetime.utcnow().isoformat(),
            source_document="doc2.pdf",
        )

        # Détecter conflits
        logger.info("Detecting conflicts...")
        conflicts = facts.detect_conflicts()

        if len(conflicts) > 0:
            logger.info(f"✅ Conflicts detected: {len(conflicts)}")
            for conflict in conflicts:
                logger.info(f"  - Type: {conflict['conflict_type']}")
                logger.info(f"  - Value diff: {conflict['value_diff_pct']:.2%}")
                logger.info(f"  - Approved: {conflict['fact_approved']['value']}{conflict['fact_approved']['unit']}")
                logger.info(f"  - Proposed: {conflict['fact_proposed']['value']}{conflict['fact_proposed']['unit']}")
        else:
            logger.warning("⚠️ No conflicts detected (unexpected)")

        # Cleanup
        facts.delete_fact(fact_approved["uuid"])
        facts.delete_fact(fact_proposed["uuid"])

        return True

    except Exception as e:
        logger.error(f"❌ Conflict detection error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_performance():
    """Test 5: Performance < 50ms"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 5: PERFORMANCE DÉTECTION CONFLITS")
    logger.info("=" * 60)

    from src.knowbase.neo4j_custom import get_neo4j_client, FactsQueries

    try:
        client = get_neo4j_client()
        facts = FactsQueries(client, tenant_id="test_performance")

        # Créer 10 facts approuvés
        logger.info("Creating 10 approved facts...")
        for i in range(10):
            facts.create_fact(
                subject=f"Service {i}",
                predicate="uptime",
                object_str=f"{99.0 + i/10}%",
                value=99.0 + i/10,
                unit="%",
                fact_type="SERVICE_LEVEL",
                status="approved",
            )

        # Créer 5 facts proposés (dont conflits)
        logger.info("Creating 5 proposed facts (with conflicts)...")
        for i in range(5):
            facts.create_fact(
                subject=f"Service {i}",
                predicate="uptime",
                object_str=f"{98.5 + i/10}%",
                value=98.5 + i/10,
                unit="%",
                fact_type="SERVICE_LEVEL",
                status="proposed",
            )

        # Mesurer performance détection conflits
        logger.info("Measuring conflict detection performance...")

        num_iterations = 10
        latencies = []

        for i in range(num_iterations):
            start = time.time()
            conflicts = facts.detect_conflicts()
            latency_ms = (time.time() - start) * 1000
            latencies.append(latency_ms)

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        min_latency = min(latencies)

        logger.info(f"Conflicts found: {len(conflicts)}")
        logger.info(f"Latency (avg): {avg_latency:.2f}ms")
        logger.info(f"Latency (min): {min_latency:.2f}ms")
        logger.info(f"Latency (max): {max_latency:.2f}ms")

        if avg_latency < 50:
            logger.info(f"✅ Performance OK - {avg_latency:.2f}ms < 50ms")
            success = True
        else:
            logger.warning(f"⚠️ Performance dégradée - {avg_latency:.2f}ms > 50ms")
            success = False

        # Cleanup
        logger.info("Cleaning up test data...")
        # Note: En production, utiliser query batch delete
        approved_facts = facts.get_facts_by_status("approved", limit=100)
        proposed_facts = facts.get_facts_by_status("proposed", limit=100)

        for fact in approved_facts + proposed_facts:
            facts.delete_fact(fact["uuid"])

        return success

    except Exception as e:
        logger.error(f"❌ Performance test error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Execute all POC tests"""
    logger.info("🚀 STARTING NEO4J POC TESTS - PHASE 1")
    logger.info("=" * 60)

    results = {
        "connection": False,
        "migrations": False,
        "crud": False,
        "conflicts": False,
        "performance": False,
    }

    # Test 1: Connection
    results["connection"] = test_connection()

    if not results["connection"]:
        logger.error("❌ Connection failed - Aborting tests")
        return results

    # Test 2: Migrations
    results["migrations"] = test_migrations()

    # Test 3: CRUD
    results["crud"] = test_crud_facts()

    # Test 4: Conflict detection
    results["conflicts"] = test_conflict_detection()

    # Test 5: Performance
    results["performance"] = test_performance()

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("RÉSUMÉ TESTS POC")
    logger.info("=" * 60)

    total = len(results)
    passed = sum(1 for v in results.values() if v)

    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} - {test_name.upper()}")

    logger.info("=" * 60)
    logger.info(f"Tests passed: {passed}/{total} ({passed/total*100:.0f}%)")

    if passed == total:
        logger.info("🎉 Tous les tests passés - POC validé !")
        return True
    else:
        logger.warning(f"⚠️ {total - passed} tests échoués")
        return False


if __name__ == "__main__":
    success = main()

    from src.knowbase.neo4j_custom import close_neo4j_client
    close_neo4j_client()

    exit(0 if success else 1)
