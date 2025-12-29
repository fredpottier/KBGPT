"""
OSMOSE Burst Resilient Client - Client HTTP résilient pour EC2 Spot

Gère les timeouts, retries avec backoff exponentiel, et détection d'interruption Spot.
Utilisé pour les appels vers vLLM et le service embeddings sur EC2.

Author: OSMOSE Burst Ingestion
Date: 2025-12
"""

import time
import logging
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


class BurstProviderUnavailable(Exception):
    """Exception levée quand le provider Burst n'est plus accessible."""

    def __init__(self, message: str, last_exception: Optional[Exception] = None):
        super().__init__(message)
        self.last_exception = last_exception


class SpotInterruptionDetected(Exception):
    """Exception levée quand une interruption Spot est détectée."""
    pass


@dataclass
class RetryConfig:
    """Configuration des retries pour le client résilient."""

    max_retries: int = 3
    timeout: int = 60
    backoff_factor: float = 2.0
    min_backoff: float = 1.0
    max_backoff: float = 30.0
    retry_on_5xx: bool = True
    retry_on_timeout: bool = True
    retry_on_connection_error: bool = True


class ResilientBurstClient:
    """
    Client HTTP résilient pour appels vers EC2 Spot.

    Gère :
    - Timeouts avec retry automatique
    - Backoff exponentiel entre les tentatives
    - Détection d'erreurs de connexion (possible interruption Spot)
    - Retry sur erreurs serveur (5xx)

    Usage:
        client = ResilientBurstClient("http://ec2-xxx:8000")
        result = client.post("/v1/chat/completions", json=payload)
    """

    def __init__(
        self,
        base_url: str,
        config: Optional[RetryConfig] = None
    ):
        """
        Initialise le client résilient.

        Args:
            base_url: URL de base du service (ex: http://ec2-xxx:8000)
            config: Configuration des retries (optionnel)
        """
        self.base_url = base_url.rstrip("/")
        self.config = config or RetryConfig()
        self._session = requests.Session()

    def post(
        self,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        POST avec retry et backoff exponentiel.

        Args:
            endpoint: Endpoint à appeler (ex: /v1/chat/completions)
            json: Payload JSON
            headers: Headers HTTP additionnels
            **kwargs: Arguments supplémentaires pour requests

        Returns:
            Réponse JSON parsée

        Raises:
            BurstProviderUnavailable: Si tous les retries échouent
        """
        return self._request_with_retry(
            method="POST",
            endpoint=endpoint,
            json=json,
            headers=headers,
            **kwargs
        )

    def get(
        self,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        GET avec retry et backoff exponentiel.

        Args:
            endpoint: Endpoint à appeler (ex: /health)
            headers: Headers HTTP additionnels
            **kwargs: Arguments supplémentaires pour requests

        Returns:
            Réponse JSON parsée

        Raises:
            BurstProviderUnavailable: Si tous les retries échouent
        """
        return self._request_with_retry(
            method="GET",
            endpoint=endpoint,
            headers=headers,
            **kwargs
        )

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Effectue une requête avec retry."""

        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None

        for attempt in range(self.config.max_retries):
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    json=json,
                    headers=headers,
                    timeout=self.config.timeout,
                    **kwargs
                )

                # Succès
                if response.ok:
                    return response.json()

                # Erreur serveur (5xx) - retry possible
                if response.status_code >= 500 and self.config.retry_on_5xx:
                    logger.warning(
                        f"[BURST:CLIENT] Server error {response.status_code} "
                        f"(attempt {attempt + 1}/{self.config.max_retries})"
                    )
                    last_exception = requests.exceptions.HTTPError(
                        f"Server error: {response.status_code}"
                    )
                else:
                    # Erreur client (4xx) - pas de retry
                    response.raise_for_status()

            except requests.exceptions.Timeout as e:
                if self.config.retry_on_timeout:
                    logger.warning(
                        f"[BURST:CLIENT] Timeout (attempt {attempt + 1}/{self.config.max_retries})"
                    )
                    last_exception = e
                else:
                    raise BurstProviderUnavailable(f"Timeout: {url}", e)

            except requests.exceptions.ConnectionError as e:
                if self.config.retry_on_connection_error:
                    logger.warning(
                        f"[BURST:CLIENT] Connection error (attempt {attempt + 1}/{self.config.max_retries}): {e}"
                    )
                    last_exception = e
                else:
                    # Possible interruption Spot
                    raise BurstProviderUnavailable(
                        f"Connection error (possible Spot interruption): {url}",
                        e
                    )

            except requests.exceptions.HTTPError as e:
                # Erreur non-retriable
                raise

            # Backoff exponentiel
            if attempt < self.config.max_retries - 1:
                sleep_time = min(
                    self.config.max_backoff,
                    max(
                        self.config.min_backoff,
                        self.config.backoff_factor ** attempt
                    )
                )
                logger.info(f"[BURST:CLIENT] Retry in {sleep_time:.1f}s...")
                time.sleep(sleep_time)

        # Tous les retries échoués
        raise BurstProviderUnavailable(
            f"EC2 Spot unreachable after {self.config.max_retries} attempts: {url}",
            last_exception
        )

    def health_check(self, timeout: int = 5) -> bool:
        """
        Vérifie si le service est accessible.

        Args:
            timeout: Timeout pour le healthcheck

        Returns:
            True si le service répond OK
        """
        try:
            response = self._session.get(
                f"{self.base_url}/health",
                timeout=timeout
            )
            return response.ok
        except Exception:
            return False

    def close(self):
        """Ferme la session HTTP."""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def create_resilient_vllm_client(
    vllm_url: str,
    max_retries: int = 3,
    timeout: int = 120
) -> ResilientBurstClient:
    """
    Crée un client résilient configuré pour vLLM.

    Args:
        vllm_url: URL du serveur vLLM
        max_retries: Nombre max de tentatives
        timeout: Timeout par requête (vLLM peut être lent)

    Returns:
        Client configuré pour vLLM
    """
    config = RetryConfig(
        max_retries=max_retries,
        timeout=timeout,
        backoff_factor=2.0,
        min_backoff=1.0,
        max_backoff=30.0
    )
    return ResilientBurstClient(vllm_url, config)


def create_resilient_embeddings_client(
    embeddings_url: str,
    max_retries: int = 3,
    timeout: int = 60
) -> ResilientBurstClient:
    """
    Crée un client résilient configuré pour le service embeddings.

    Args:
        embeddings_url: URL du service embeddings (TEI)
        max_retries: Nombre max de tentatives
        timeout: Timeout par requête

    Returns:
        Client configuré pour embeddings
    """
    config = RetryConfig(
        max_retries=max_retries,
        timeout=timeout,
        backoff_factor=1.5,
        min_backoff=0.5,
        max_backoff=15.0
    )
    return ResilientBurstClient(embeddings_url, config)
