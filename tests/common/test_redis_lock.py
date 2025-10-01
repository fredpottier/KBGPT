"""
Tests Lock Distribué Redis - Phase 0.5 Durcissement P0.2
"""
import pytest
import redis
import time
import uuid
from knowbase.common.redis_lock import RedisLock, create_lock


@pytest.fixture
def redis_client():
    """Client Redis pour tests (DB 5 isolé)"""
    client = redis.Redis(host="redis", port=6379, db=5, decode_responses=False)
    # Cleanup avant tests
    client.flushdb()
    yield client
    # Cleanup après tests
    client.flushdb()
    client.close()


class TestRedisLockBasic:
    """Tests fonctionnalités de base du lock"""

    def test_lock_acquire_and_release(self, redis_client):
        """
        Test acquisition et release normal

        Expected: Lock acquis puis libéré avec succès
        """
        lock = RedisLock(redis_client, "test:lock:basic", ttl_seconds=60)

        # Acquire
        acquired = lock.acquire(timeout=5)
        assert acquired is True
        assert lock.is_held() is True

        # Vérifier clé Redis existe
        assert redis_client.exists("lock:test:lock:basic") == 1

        # Release
        released = lock.release()
        assert released is True
        assert lock.is_held() is False

        # Vérifier clé Redis supprimée
        assert redis_client.exists("lock:test:lock:basic") == 0
        print("OK: Lock acquire/release")

    def test_lock_auto_expire_ttl(self, redis_client):
        """
        Test auto-expiration du lock si TTL atteint

        Expected: Lock expire après TTL même sans release
        """
        lock = RedisLock(redis_client, "test:lock:ttl", ttl_seconds=2)

        acquired = lock.acquire(timeout=5)
        assert acquired is True

        # Attendre expiration TTL
        time.sleep(3)

        # Vérifier clé Redis supprimée automatiquement
        assert redis_client.exists("lock:test:lock:ttl") == 0
        print("OK: Lock auto-expire après TTL")

    def test_lock_context_manager(self, redis_client):
        """
        Test context manager avec auto-release

        Expected: Lock acquis dans context, libéré automatiquement après
        """
        lock = RedisLock(redis_client, "test:lock:context", ttl_seconds=60)

        with lock.context(timeout=5):
            assert lock.is_held() is True
            assert redis_client.exists("lock:test:lock:context") == 1

        # Après context, lock libéré
        assert lock.is_held() is False
        assert redis_client.exists("lock:test:lock:context") == 0
        print("OK: Context manager auto-release")


class TestRedisLockConcurrency:
    """Tests race conditions et concurrence"""

    def test_lock_prevents_concurrent_access(self, redis_client):
        """
        Test mutex: 2nd holder bloqué si 1st holder détient lock

        Expected: lock1 acquis, lock2 timeout
        """
        lock1 = RedisLock(redis_client, "test:lock:mutex", ttl_seconds=60, holder_id="holder1")
        lock2 = RedisLock(redis_client, "test:lock:mutex", ttl_seconds=60, holder_id="holder2")

        # Lock1 acquiert
        acquired1 = lock1.acquire(timeout=5)
        assert acquired1 is True

        # Lock2 tente acquisition (doit échouer car lock1 détient)
        acquired2 = lock2.acquire(timeout=2)
        assert acquired2 is False

        # Release lock1
        lock1.release()

        # Lock2 peut maintenant acquérir
        acquired2_retry = lock2.acquire(timeout=5)
        assert acquired2_retry is True

        lock2.release()
        print("OK: Lock mutex prevents concurrent access")

    def test_lock_reacquire_after_release(self, redis_client):
        """
        Test réacquisition après release

        Expected: Même holder peut réacquérir lock après release
        """
        lock = RedisLock(redis_client, "test:lock:reacquire", ttl_seconds=60)

        # 1ère acquisition
        acquired1 = lock.acquire(timeout=5)
        assert acquired1 is True
        lock.release()

        # 2ème acquisition (même holder)
        acquired2 = lock.acquire(timeout=5)
        assert acquired2 is True
        lock.release()

        print("OK: Lock reacquire after release")

    def test_lock_cannot_release_other_holder_lock(self, redis_client):
        """
        Test sécurité: holder A ne peut pas release lock de holder B

        Expected: lock2.release() échoue si lock détenu par lock1
        """
        lock1 = RedisLock(redis_client, "test:lock:security", ttl_seconds=60, holder_id="holder1")
        lock2 = RedisLock(redis_client, "test:lock:security", ttl_seconds=60, holder_id="holder2")

        # Lock1 acquiert
        lock1.acquire(timeout=5)

        # Lock2 tente release (doit échouer)
        released = lock2.release()
        assert released is False

        # Lock toujours détenu par lock1
        assert redis_client.exists("lock:test:lock:security") == 1

        # Vérifier holder_id
        holder = redis_client.get("lock:test:lock:security").decode()
        assert holder == "holder1"

        lock1.release()
        print("OK: Lock security prevents cross-holder release")


class TestRedisLockEdgeCases:
    """Tests cas limites et edge cases"""

    def test_lock_extend_ttl(self, redis_client):
        """
        Test prolongation TTL pour opérations longues

        Expected: TTL prolongé si lock détenu par holder
        """
        lock = RedisLock(redis_client, "test:lock:extend", ttl_seconds=5)

        lock.acquire(timeout=5)

        # Prolonger TTL
        extended = lock.extend_ttl(additional_seconds=10)
        assert extended is True

        # Vérifier nouveau TTL ~15s (5 initial + 10 extended)
        ttl = redis_client.ttl("lock:test:lock:extend")
        assert ttl > 12  # Au moins 12s restants (marge pour latence)

        lock.release()
        print("OK: Lock extend TTL")

    def test_lock_timeout_returns_false(self, redis_client):
        """
        Test timeout si lock non acquis avant délai

        Expected: acquire() retourne False après timeout
        """
        lock1 = RedisLock(redis_client, "test:lock:timeout", ttl_seconds=60, holder_id="holder1")
        lock2 = RedisLock(redis_client, "test:lock:timeout", ttl_seconds=60, holder_id="holder2")

        # Lock1 acquiert
        lock1.acquire(timeout=5)

        # Lock2 timeout rapide (1s)
        start = time.time()
        acquired2 = lock2.acquire(timeout=1)
        elapsed = time.time() - start

        assert acquired2 is False
        assert 1.0 <= elapsed <= 1.5  # Timeout respecté (~1s)

        lock1.release()
        print(f"OK: Lock timeout after {elapsed:.2f}s")

    def test_lock_context_timeout_raises_error(self, redis_client):
        """
        Test context manager raise TimeoutError si acquisition échoue

        Expected: TimeoutError si lock non acquis
        """
        lock1 = RedisLock(redis_client, "test:lock:ctx_timeout", ttl_seconds=60, holder_id="holder1")
        lock2 = RedisLock(redis_client, "test:lock:ctx_timeout", ttl_seconds=60, holder_id="holder2")

        # Lock1 acquiert
        lock1.acquire(timeout=5)

        # Lock2 context avec timeout (doit raise TimeoutError)
        with pytest.raises(TimeoutError):
            with lock2.context(timeout=1):
                pass

        lock1.release()
        print("OK: Context manager raises TimeoutError")

    def test_lock_release_after_ttl_expire(self, redis_client):
        """
        Test release après expiration TTL (graceful)

        Expected: release() retourne False mais pas d'erreur
        """
        lock = RedisLock(redis_client, "test:lock:release_expired", ttl_seconds=1)

        lock.acquire(timeout=5)

        # Attendre expiration TTL
        time.sleep(2)

        # Release (lock déjà expiré)
        released = lock.release()
        assert released is False  # False car lock déjà expiré
        assert lock.is_held() is False

        print("OK: Release after TTL expire (graceful)")


class TestRedisLockFactory:
    """Tests factory function create_lock"""

    def test_create_lock_from_url(self):
        """
        Test création lock depuis URL Redis

        Expected: Lock fonctionnel créé depuis URL
        """
        lock = create_lock(
            redis_url="redis://redis:6379/5",
            lock_key="test:factory:lock",
            ttl_seconds=60
        )

        acquired = lock.acquire(timeout=5)
        assert acquired is True

        lock.release()
        print("OK: create_lock from URL")

    def test_create_lock_with_custom_holder_id(self):
        """
        Test création lock avec holder_id custom

        Expected: holder_id custom utilisé
        """
        custom_id = f"custom_{uuid.uuid4().hex[:8]}"
        lock = create_lock(
            redis_url="redis://redis:6379/5",
            lock_key="test:factory:custom_holder",
            holder_id=custom_id
        )

        lock.acquire(timeout=5)

        # Vérifier holder_id dans Redis
        redis_client = redis.Redis(host="redis", port=6379, db=5, decode_responses=False)
        holder = redis_client.get("lock:test:factory:custom_holder").decode()
        assert holder == custom_id

        lock.release()
        redis_client.close()
        print("OK: create_lock with custom holder_id")
