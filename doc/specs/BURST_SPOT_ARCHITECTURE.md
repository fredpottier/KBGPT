# Architecture Mode Burst Spot - OSMOSE KnowWhere

*Spécification technique pour le mode Burst : compute LLM/Embeddings déporté sur EC2 Spot*

**Version:** 2.1 (Qwen 14B AWQ + Deep Learning AMI)
**Date:** 2025-12-27
**Statut:** Draft - En attente validation

---

## 1. Vue d'ensemble

### 1.1 Clarification fondamentale

**CE QUE BURST FAIT :**
- Déporter **uniquement le compute LLM + Embeddings** sur EC2 Spot
- Le pipeline d'ingestion **reste local**
- Qdrant/Neo4j **restent locaux**
- L'EC2 Spot expose des **endpoints API** que le local consomme

**CE QUE BURST NE FAIT PAS :**
- ❌ Ne déplace PAS les documents vers S3
- ❌ Ne fait PAS tourner le pipeline d'ingestion sur EC2
- ❌ Ne rend PAS Qdrant/Neo4j distants
- ❌ Ne modifie PAS le workflow existant (juste les providers)

### 1.2 Principe simple

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MODE NORMAL (actuel)                         │
│                                                                     │
│  Pipeline Local → OpenAI API (LLM) → GPU Local (Embeddings)        │
│       ↓                                                             │
│  Qdrant/Neo4j (local)                                               │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        MODE BURST (nouveau)                         │
│                                                                     │
│  Pipeline Local → EC2 Spot vLLM (LLM) → EC2 Spot GPU (Embeddings)  │
│       ↓                                                             │
│  Qdrant/Neo4j (local)  ← Même destination, différent provider      │
└─────────────────────────────────────────────────────────────────────┘
```

**L'EC2 Spot est un "remote provider" temporaire, pas un worker.**

### 1.3 Workflow simplifié

1. **Admin active Burst** → Demande instance Spot
2. **Attente capacité** → Normal pour Spot (secondes à minutes)
3. **Instance prête** → vLLM + Embeddings exposés via API
4. **LLMRouter bascule** → Pointe vers EC2 au lieu d'OpenAI
5. **Import batch local** → Pipeline existant, providers différents
6. **Fin** → Instance Spot terminée, retour mode normal

### 1.4 Économies attendues

| Coût | Mode Normal | Mode Burst (14B AWQ) | Économie |
|------|-------------|----------------------|----------|
| LLM (100 docs) | ~$15 (OpenAI) | ~$1.00 (Spot g6.2xlarge 1.5h) | **93%** |
| Embeddings | GPU local saturé | GPU EC2 dédié | Libère local |
| Vision GPT-4o | ~$3 (40 calls/doc) | ~$1.20 (gating 60%) | **60%** |

**Note:** Qwen 2.5 14B AWQ offre une qualité nettement supérieure au 7B pour un coût Spot légèrement plus élevé (~$0.70-0.90/h pour g6.2xlarge vs ~$0.32/h pour g5.xlarge), mais reste très économique face à OpenAI.

---

## 2. Architecture technique

### 2.1 Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────┐
│                         LOCAL (Machine User)                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    PIPELINE INGESTION                         │  │
│  │                    (INCHANGÉ)                                 │  │
│  │                                                               │  │
│  │  docs_in/ → pptx_pipeline.py → osmose_agentique.py →        │  │
│  │                                                               │  │
│  │  ┌─────────────────┐     ┌─────────────────────────────┐    │  │
│  │  │   LLMRouter     │     │   EmbeddingManager          │    │  │
│  │  │                 │     │                             │    │  │
│  │  │  Mode Normal:   │     │  Mode Normal:               │    │  │
│  │  │  → OpenAI API   │     │  → GPU local (RTX 5070 Ti)  │    │  │
│  │  │                 │     │                             │    │  │
│  │  │  Mode Burst:    │     │  Mode Burst:                │    │  │
│  │  │  → EC2 vLLM API │     │  → EC2 Embeddings API       │    │  │
│  │  └────────┬────────┘     └──────────────┬──────────────┘    │  │
│  │           │                             │                    │  │
│  └───────────┼─────────────────────────────┼────────────────────┘  │
│              │                             │                       │
│              │    ┌────────────────────────┘                       │
│              │    │                                                │
│              ▼    ▼                                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    STOCKAGE LOCAL                             │  │
│  │                                                               │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐ │  │
│  │  │   Qdrant   │  │   Neo4j    │  │  data/extraction_cache │ │  │
│  │  │   :6333    │  │   :7474    │  │  (cache LLM responses) │ │  │
│  │  └────────────┘  └────────────┘  └────────────────────────┘ │  │
│  │                                                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                 BURST ORCHESTRATOR                            │  │
│  │                                                               │  │
│  │  - Provision CloudFormation Spot Fleet                       │  │
│  │  - Wait for instance READY (healthchecks)                    │  │
│  │  - Configure providers (LLMRouter, EmbeddingManager)         │  │
│  │  - Monitor instance health                                    │  │
│  │  - Handle interruptions (retry/resume)                       │  │
│  │  - Teardown when done                                        │  │
│  │                                                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    │ HTTPS (API calls)
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         EC2 SPOT INSTANCE                           │
│                    (Provider de compute éphémère)                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Instance: g6.2xlarge / g6e.xlarge (NVIDIA L4 24GB)                │
│  Fallback: g5.2xlarge (NVIDIA A10G 24GB)                           │
│  AMI: Deep Learning AMI (PyTorch 2.5, Ubuntu 22.04)                │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                                                               │  │
│  │   ┌─────────────────────────┐  ┌──────────────────────────┐ │  │
│  │   │      vLLM Server        │  │   Embeddings Server      │ │  │
│  │   │                         │  │                          │ │  │
│  │   │  Model: Qwen2.5-14B-AWQ │  │  Model: E5-Large         │ │  │
│  │   │  Quantization: AWQ 4bit │  │  Port: 8001 (TEI 1.5)    │ │  │
│  │   │  Port: 8000             │  │                          │ │  │
│  │   │                         │  │                          │ │  │
│  │   │  API: OpenAI-compatible │  │  API: /embed endpoint    │ │  │
│  │   │  /v1/chat/completions   │  │                          │ │  │
│  │   │                         │  │                          │ │  │
│  │   └─────────────────────────┘  └──────────────────────────┘ │  │
│  │                                                               │  │
│  │   ┌──────────────────────────────────────────────────────┐   │  │
│  │   │                  Health Endpoint                      │   │  │
│  │   │                  GET /health → 200 OK                 │   │  │
│  │   │                  (Vérifie vLLM + Embeddings ready)    │   │  │
│  │   └──────────────────────────────────────────────────────┘   │  │
│  │                                                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  Spot Interruption Handler:                                        │
│  - Monitore http://169.254.169.254/latest/meta-data/spot/          │
│  - Signal 2 min avant terminaison                                  │
│  - Log + graceful shutdown                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Rôle de S3 (minimal)

S3 n'est **PAS** utilisé pour stocker les documents. Il sert uniquement à :

```
s3://knowwhere-burst-{account}/
├── state/
│   └── burst_state.json      # État du batch (pour reprise)
├── logs/
│   └── {batch_id}/           # Logs CloudWatch export
└── config/
    └── burst_config.json     # Config instance (models, etc.)
```

**Pas de staging de documents. Pas d'artifacts. Le pipeline reste 100% local.**

### 2.3 Structure des répertoires locaux (inchangée)

```
data/
├── burst/
│   └── pending/              # Documents à traiter en batch
│       ├── RISE_2025.pptx
│       └── SAP_Security.pdf
│
├── watch/                    # Mode normal (watcher actif) - INCHANGÉ
├── docs_in/                  # Queue import - INCHANGÉ
├── docs_done/                # Fichiers traités - INCHANGÉ
├── extraction_cache/         # Cache LLM - CRITIQUE pour reprise
└── public/                   # Assets générés
```

**Le cache `extraction_cache/` devient encore plus important** car il permet de reprendre après une interruption Spot sans refaire les appels LLM déjà effectués.

---

## 3. Basculement des providers

### 3.1 LLMRouter - Modification

```python
# src/knowbase/common/llm_router.py

class LLMRouter:
    """Routeur intelligent avec support mode Burst."""

    def __init__(self, config_path: Optional[Path] = None):
        # ... existing init ...
        self._burst_mode = False
        self._burst_endpoint = None

    def enable_burst_mode(self, vllm_url: str):
        """
        Active le mode Burst : redirige les appels LLM vers EC2.

        Args:
            vllm_url: URL du serveur vLLM (ex: http://ec2-xxx:8000)
        """
        self._burst_mode = True
        self._burst_endpoint = vllm_url

        # Créer client vLLM (OpenAI-compatible)
        from openai import OpenAI
        self._vllm_client = OpenAI(
            api_key="EMPTY",
            base_url=f"{vllm_url}/v1"
        )

        logger.info(f"[LLM_ROUTER] Burst mode ENABLED → {vllm_url}")

    def disable_burst_mode(self):
        """Désactive le mode Burst, retour aux providers normaux."""
        self._burst_mode = False
        self._burst_endpoint = None
        self._vllm_client = None

        logger.info("[LLM_ROUTER] Burst mode DISABLED → Normal providers")

    def complete(self, task_type: TaskType, messages: List[Dict], **kwargs) -> str:
        """Effectue un appel LLM, routé selon le mode."""

        # Vision reste sur GPT-4o (avec gating)
        if task_type == TaskType.VISION:
            return self._call_openai_vision(messages, **kwargs)

        # Mode Burst : utiliser vLLM distant
        if self._burst_mode and self._vllm_client:
            return self._call_vllm(messages, **kwargs)

        # Mode normal : providers habituels
        return self._call_normal_provider(task_type, messages, **kwargs)
```

### 3.2 EmbeddingManager - Modification

```python
# src/knowbase/common/clients/embeddings.py

class EmbeddingModelManager:
    """Manager embeddings avec support mode Burst."""

    def __init__(self):
        # ... existing init ...
        self._burst_mode = False
        self._burst_endpoint = None

    def enable_burst_mode(self, embeddings_url: str):
        """
        Active le mode Burst : embeddings calculés sur EC2.

        Args:
            embeddings_url: URL du service embeddings (ex: http://ec2-xxx:8001)
        """
        self._burst_mode = True
        self._burst_endpoint = embeddings_url

        # Décharger le modèle local pour libérer GPU
        self._unload_model()

        logger.info(f"[EMBEDDINGS] Burst mode ENABLED → {embeddings_url}")

    def disable_burst_mode(self):
        """Désactive le mode Burst, retour au GPU local."""
        self._burst_mode = False
        self._burst_endpoint = None

        logger.info("[EMBEDDINGS] Burst mode DISABLED → Local GPU")

    def encode(self, texts: List[str], **kwargs) -> np.ndarray:
        """Encode les textes, routé selon le mode."""

        if self._burst_mode and self._burst_endpoint:
            return self._encode_remote(texts)

        return self._encode_local(texts, **kwargs)

    def _encode_remote(self, texts: List[str]) -> np.ndarray:
        """Appel vers le service embeddings distant."""
        import requests

        response = requests.post(
            f"{self._burst_endpoint}/embed",
            json={"texts": texts},
            timeout=60
        )
        response.raise_for_status()

        embeddings = np.array(response.json()["embeddings"])
        return embeddings
```

### 3.3 Activation/Désactivation

```python
# src/knowbase/burst/provider_switch.py

def activate_burst_providers(vllm_url: str, embeddings_url: str):
    """
    Active les providers Burst pour le pipeline.
    Appelé par BurstOrchestrator quand l'instance EC2 est prête.
    """
    from knowbase.common.llm_router import get_llm_router
    from knowbase.common.clients.embeddings import get_embedding_manager

    llm_router = get_llm_router()
    embedding_manager = get_embedding_manager()

    llm_router.enable_burst_mode(vllm_url)
    embedding_manager.enable_burst_mode(embeddings_url)

    logger.info("[BURST] All providers switched to EC2 Spot")


def deactivate_burst_providers():
    """
    Désactive les providers Burst, retour mode normal.
    Appelé quand le batch est terminé ou sur erreur.
    """
    from knowbase.common.llm_router import get_llm_router
    from knowbase.common.clients.embeddings import get_embedding_manager

    llm_router = get_llm_router()
    embedding_manager = get_embedding_manager()

    llm_router.disable_burst_mode()
    embedding_manager.disable_burst_mode()

    logger.info("[BURST] All providers switched back to normal")
```

---

## 4. Gestion des interruptions Spot

### 4.1 Robustesse des appels API

```python
# src/knowbase/burst/resilient_client.py

import time
import requests
from typing import Optional

class ResilientBurstClient:
    """
    Client HTTP résilient pour appels vers EC2 Spot.
    Gère timeouts, retries, et détection d'interruption.
    """

    def __init__(
        self,
        base_url: str,
        max_retries: int = 3,
        timeout: int = 60,
        backoff_factor: float = 2.0
    ):
        self.base_url = base_url
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_factor = backoff_factor

    def post(self, endpoint: str, json: dict) -> dict:
        """POST avec retry et backoff exponentiel."""

        last_exception = None

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    f"{self.base_url}{endpoint}",
                    json=json,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()

            except requests.exceptions.Timeout:
                logger.warning(f"[BURST] Timeout attempt {attempt + 1}/{self.max_retries}")
                last_exception = TimeoutError("EC2 Spot timeout")

            except requests.exceptions.ConnectionError as e:
                # Possible interruption Spot
                logger.warning(f"[BURST] Connection error: {e}")
                last_exception = e

            except requests.exceptions.HTTPError as e:
                if e.response.status_code >= 500:
                    # Erreur serveur, retry
                    logger.warning(f"[BURST] Server error {e.response.status_code}")
                    last_exception = e
                else:
                    # Erreur client, pas de retry
                    raise

            # Backoff exponentiel
            if attempt < self.max_retries - 1:
                sleep_time = self.backoff_factor ** attempt
                logger.info(f"[BURST] Retry in {sleep_time}s...")
                time.sleep(sleep_time)

        # Tous les retries échoués
        raise BurstProviderUnavailable(
            f"EC2 Spot unreachable after {self.max_retries} attempts",
            last_exception
        )


class BurstProviderUnavailable(Exception):
    """Exception quand le provider Burst n'est plus accessible."""
    pass
```

### 4.2 Reprise via cache

Le `extraction_cache` existant permet la reprise automatique :

```python
# Workflow de reprise après interruption Spot

def process_document_with_cache(doc_path: Path):
    """
    Traite un document, utilise le cache si disponible.
    Permet la reprise après interruption Spot.
    """
    from knowbase.ingestion.extraction_cache import ExtractionCacheManager

    cache_manager = ExtractionCacheManager()

    # Vérifier si déjà dans le cache
    cached = cache_manager.get_cache_for_file(doc_path)

    if cached:
        logger.info(f"[BURST:CACHE] Using cached extraction for {doc_path.name}")
        return cached

    try:
        # Extraction via provider Burst
        result = extract_document(doc_path)

        # Sauvegarder dans le cache
        cache_manager.save_cache(doc_path, result)

        return result

    except BurstProviderUnavailable:
        # Interruption Spot probable
        logger.warning(f"[BURST] Provider unavailable for {doc_path.name}")
        raise  # Propagate pour que l'orchestrateur gère
```

### 4.3 États de l'orchestrateur

```python
class BurstStatus(str, Enum):
    """États du mode Burst."""

    IDLE = "idle"                       # Pas de batch actif
    REQUESTING_SPOT = "requesting_spot"  # CloudFormation en cours
    WAITING_CAPACITY = "waiting_capacity" # Attente allocation Spot
    INSTANCE_STARTING = "instance_starting" # Boot + init services
    READY = "ready"                     # Providers disponibles
    PROCESSING = "processing"           # Batch en cours
    INTERRUPTED = "interrupted"         # Spot perdu, reprise en cours
    RESUMING = "resuming"               # Nouvelle instance, reprise
    COMPLETED = "completed"             # Batch terminé
    FAILED = "failed"                   # Erreur fatale
```

---

## 5. Burst Orchestrator

### 5.1 Classe principale

```python
# src/knowbase/burst/orchestrator.py

import os
import time
import boto3
from typing import Optional, List, Dict
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime

from knowbase.burst.provider_switch import (
    activate_burst_providers,
    deactivate_burst_providers
)


@dataclass
class BurstState:
    """État persistant du mode Burst."""
    batch_id: str
    status: BurstStatus
    documents: List[str]
    documents_done: List[str]
    documents_failed: List[str]
    spot_fleet_id: Optional[str] = None
    instance_id: Optional[str] = None
    instance_ip: Optional[str] = None
    instance_type: Optional[str] = None
    started_at: Optional[str] = None
    interruption_count: int = 0
    events: List[Dict] = None


class BurstOrchestrator:
    """
    Orchestre le mode Burst :
    - Provision EC2 Spot
    - Bascule les providers
    - Gère les interruptions
    - Teardown à la fin
    """

    def __init__(self):
        self.state: Optional[BurstState] = None
        self.cf_client = boto3.client('cloudformation')
        self.ec2_client = boto3.client('ec2')

        # Config
        self.vllm_port = 8000
        self.embeddings_port = 8001
        self.health_check_interval = 10
        self.health_check_timeout = 600  # 10 min max pour boot

    def start_burst_batch(self, document_paths: List[Path]) -> str:
        """
        Démarre un batch en mode Burst.

        1. Crée le state
        2. Lance CloudFormation
        3. Attend instance ready
        4. Bascule providers
        5. Retourne batch_id pour suivi
        """
        batch_id = f"burst-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        self.state = BurstState(
            batch_id=batch_id,
            status=BurstStatus.REQUESTING_SPOT,
            documents=[str(p) for p in document_paths],
            documents_done=[],
            documents_failed=[],
            events=[]
        )

        self._add_event("batch_created", f"Batch créé avec {len(document_paths)} documents")

        try:
            # 1. Déployer CloudFormation
            self._deploy_spot_infrastructure(batch_id)

            # 2. Attendre instance ready
            self._wait_for_instance_ready()

            # 3. Basculer providers
            self._switch_to_burst_providers()

            self.state.status = BurstStatus.READY
            self._add_event("ready", "Instance prête, providers activés")

            return batch_id

        except Exception as e:
            self.state.status = BurstStatus.FAILED
            self._add_event("error", f"Échec démarrage: {e}", severity="error")
            self._cleanup()
            raise

    def process_batch(self):
        """
        Traite le batch de documents.
        Appelé après start_burst_batch.
        """
        if self.state.status != BurstStatus.READY:
            raise ValueError(f"Cannot process in status: {self.state.status}")

        self.state.status = BurstStatus.PROCESSING
        self.state.started_at = datetime.now().isoformat()

        pending = [d for d in self.state.documents
                   if d not in self.state.documents_done
                   and d not in self.state.documents_failed]

        for doc_path in pending:
            try:
                self._add_event("doc_started", f"Traitement: {Path(doc_path).name}")

                # Appeler le pipeline existant (qui utilisera les providers Burst)
                self._process_single_document(Path(doc_path))

                self.state.documents_done.append(doc_path)
                self._add_event("doc_completed", f"Terminé: {Path(doc_path).name}")

            except BurstProviderUnavailable:
                # Interruption Spot probable
                self._add_event("spot_interrupted", "Instance Spot interrompue", severity="warning")
                self.state.status = BurstStatus.INTERRUPTED
                self._handle_interruption()
                break

            except Exception as e:
                self.state.documents_failed.append(doc_path)
                self._add_event("doc_failed", f"Échec: {Path(doc_path).name} - {e}", severity="error")

        # Vérifier si tout est fait
        if len(self.state.documents_done) == len(self.state.documents):
            self._complete_batch()

    def _handle_interruption(self):
        """Gère une interruption Spot."""
        self.state.interruption_count += 1
        self._add_event("resuming", f"Tentative reprise #{self.state.interruption_count}")

        # Désactiver providers
        deactivate_burst_providers()

        # Nouvelle instance Spot
        self.state.status = BurstStatus.RESUMING

        try:
            # Attendre nouvelle instance (CloudFormation maintient la fleet)
            self._wait_for_instance_ready()
            self._switch_to_burst_providers()

            # Reprendre le traitement
            self.state.status = BurstStatus.READY
            self.process_batch()  # Recursive, reprend les pending

        except Exception as e:
            self._add_event("resume_failed", f"Échec reprise: {e}", severity="error")
            self.state.status = BurstStatus.FAILED

    def _complete_batch(self):
        """Finalise le batch."""
        self.state.status = BurstStatus.COMPLETED

        # Désactiver providers
        deactivate_burst_providers()

        # Teardown infrastructure
        self._teardown_infrastructure()

        self._add_event("batch_completed",
            f"Batch terminé: {len(self.state.documents_done)} réussis, "
            f"{len(self.state.documents_failed)} échecs, "
            f"{self.state.interruption_count} interruptions")

    def _deploy_spot_infrastructure(self, batch_id: str):
        """Déploie le stack CloudFormation."""
        self._add_event("cloudformation_started", "Déploiement infrastructure")

        stack_name = f"knowwhere-burst-{batch_id}"

        # Charger template
        template_path = Path(__file__).parent / "cloudformation" / "burst-spot.yaml"
        with open(template_path) as f:
            template_body = f.read()

        self.cf_client.create_stack(
            StackName=stack_name,
            TemplateBody=template_body,
            Parameters=[
                {"ParameterKey": "BatchId", "ParameterValue": batch_id},
                # ... autres params
            ],
            Capabilities=["CAPABILITY_IAM"]
        )

        # Attendre création
        self.state.status = BurstStatus.WAITING_CAPACITY
        self._add_event("spot_requested", "En attente de capacité Spot")

        waiter = self.cf_client.get_waiter('stack_create_complete')
        waiter.wait(StackName=stack_name)

        self.state.spot_fleet_id = stack_name
        self._add_event("cloudformation_completed", "Infrastructure déployée")

    def _wait_for_instance_ready(self):
        """Attend que l'instance soit prête (healthcheck)."""
        self.state.status = BurstStatus.INSTANCE_STARTING

        # Récupérer IP de l'instance
        self._update_instance_info()

        if not self.state.instance_ip:
            raise RuntimeError("No instance IP available")

        self._add_event("instance_starting",
            f"Instance {self.state.instance_id} ({self.state.instance_type}) démarrage")

        # Healthcheck loop
        vllm_url = f"http://{self.state.instance_ip}:{self.vllm_port}"
        embeddings_url = f"http://{self.state.instance_ip}:{self.embeddings_port}"

        start_time = time.time()

        while time.time() - start_time < self.health_check_timeout:
            try:
                # Check vLLM
                resp_vllm = requests.get(f"{vllm_url}/health", timeout=5)
                # Check embeddings
                resp_emb = requests.get(f"{embeddings_url}/health", timeout=5)

                if resp_vllm.ok and resp_emb.ok:
                    self._add_event("services_ready", "vLLM + Embeddings prêts")
                    return

            except requests.exceptions.RequestException:
                pass

            time.sleep(self.health_check_interval)

        raise TimeoutError("Instance not ready within timeout")

    def _switch_to_burst_providers(self):
        """Bascule les providers vers EC2."""
        vllm_url = f"http://{self.state.instance_ip}:{self.vllm_port}"
        embeddings_url = f"http://{self.state.instance_ip}:{self.embeddings_port}"

        activate_burst_providers(vllm_url, embeddings_url)

        self._add_event("providers_switched", "Providers basculés vers EC2 Spot")

    def _add_event(self, event_type: str, message: str, severity: str = "info"):
        """Ajoute un événement à la timeline."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "message": message,
            "severity": severity
        }
        self.state.events.append(event)
        logger.info(f"[BURST:{event_type.upper()}] {message}")

    # ... autres méthodes (_process_single_document, _teardown_infrastructure, etc.)
```

---

## 6. Services EC2 Spot

### 6.1 Configuration Qwen 2.5 14B AWQ

**Modèle choisi :** `Qwen/Qwen2.5-14B-Instruct-AWQ`
- Quantification AWQ 4-bit → ~8GB VRAM (vs 28GB pour FP16)
- Qualité supérieure au 7B, proche du 14B full precision
- Compatible avec GPU 24GB (L4, A10G)

**Configuration vLLM pour AWQ :**
```bash
# Paramètres obligatoires pour AWQ
--quantization awq      # Active le décodeur AWQ
--dtype half            # FP16 pour inférence quantifiée
--gpu-memory-utilization 0.85  # ~20GB sur 24GB (14B AWQ + TEI)
--max-model-len 8192    # Context window raisonnable
--max-num-seqs 32       # Limite concurrence pour stabilité
```

### 6.2 User Data (Deep Learning AMI)

Utilise AWS Deep Learning AMI avec NVIDIA drivers préinstallés (boot rapide):

```bash
#!/bin/bash
set -ex

# Variables injectées par CloudFormation
VLLM_MODEL="${VllmModel:-Qwen/Qwen2.5-14B-Instruct-AWQ}"
EMBEDDINGS_MODEL="${EmbeddingsModel:-intfloat/multilingual-e5-large}"
VLLM_QUANTIZATION="${VllmQuantization:-awq}"
VLLM_DTYPE="${VllmDtype:-half}"
VLLM_GPU_MEM="${VllmGpuMemoryUtilization:-0.85}"
VLLM_MAX_MODEL_LEN="${VllmMaxModelLen:-8192}"
VLLM_MAX_NUM_SEQS="${VllmMaxNumSeqs:-32}"

# Deep Learning AMI - Docker déjà installé, juste démarrer
systemctl start docker
systemctl enable docker

# Pull images en parallèle
docker pull vllm/vllm-openai:latest &
docker pull ghcr.io/huggingface/text-embeddings-inference:1.5 &
wait

# Construire les arguments vLLM
VLLM_ARGS="--model $VLLM_MODEL --max-model-len $VLLM_MAX_MODEL_LEN"
VLLM_ARGS="$VLLM_ARGS --gpu-memory-utilization $VLLM_GPU_MEM"
VLLM_ARGS="$VLLM_ARGS --max-num-seqs $VLLM_MAX_NUM_SEQS --trust-remote-code"

# Ajouter quantization si spécifié (AWQ)
if [ "$VLLM_QUANTIZATION" != "none" ]; then
    VLLM_ARGS="$VLLM_ARGS --quantization $VLLM_QUANTIZATION"
fi

# Ajouter dtype
VLLM_ARGS="$VLLM_ARGS --dtype $VLLM_DTYPE"

# Start vLLM (port 8000)
docker run -d --gpus all \
  -p 8000:8000 \
  --name vllm \
  -e HF_TOKEN="${HfToken:-}" \
  vllm/vllm-openai:latest \
  $VLLM_ARGS

# Start Embeddings TEI 1.5 (port 8001)
docker run -d --gpus all \
  -p 8001:80 \
  --name embeddings \
  ghcr.io/huggingface/text-embeddings-inference:1.5 \
  --model-id $EMBEDDINGS_MODEL

# Health check endpoint combiné
cat > /opt/health.py << 'HEALTHEOF'
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            vllm = requests.get("http://localhost:8000/health", timeout=5)
            emb = requests.get("http://localhost:8001/health", timeout=5)
            if vllm.ok and emb.ok:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "healthy", "vllm": "ok", "embeddings": "ok"}')
            else:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'{"status": "starting"}')
        except:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"status": "starting"}')

HTTPServer(("", 8080), HealthHandler).serve_forever()
HEALTHEOF

pip install requests  # Peut être absent de DLAMI
python3 /opt/health.py &

echo "Bootstrap complete - services starting"
```

**Temps de boot estimé :**
- Deep Learning AMI : ~2-3 min (vs 10+ min avec drivers à installer)
- Pull images : ~2-3 min (vLLM + TEI en parallèle)
- Chargement modèle 14B AWQ : ~3-5 min
- **Total : ~8-12 min** (vs 15-20 min avec AMI standard)

### 6.3 CloudFormation (résumé)

Le template CloudFormation complet (`burst-spot.yaml`) inclut :

```yaml
# Paramètres principaux
Parameters:
  VllmModel:
    Default: "Qwen/Qwen2.5-14B-Instruct-AWQ"
  VllmQuantization:
    Default: "awq"
    AllowedValues: ["awq", "gptq", "squeezellm", "none"]
  VllmDtype:
    Default: "half"
  VllmGpuMemoryUtilization:
    Default: "0.85"
  VllmMaxModelLen:
    Default: "8192"
  VllmMaxNumSeqs:
    Default: "32"
  EmbeddingsModel:
    Default: "intfloat/multilingual-e5-large"

# AMI Deep Learning via SSM (résolution dynamique)
ImageId: !Sub "{{resolve:ssm:/aws/service/deeplearning/ami/x86_64/oss-nvidia-driver-gpu-pytorch-2.5-ubuntu-22.04/latest/ami-id}}"

# Instances prioritaires (L4 GPU préféré)
LaunchTemplateOverrides:
  - InstanceType: g6.2xlarge   # L4 24GB - priorité 1
  - InstanceType: g6e.xlarge   # L4 24GB - priorité 2
  - InstanceType: g5.2xlarge   # A10G 24GB - fallback

# Stratégie Spot
AllocationStrategy: capacityOptimizedPrioritized
SpotMaxTotalPrice: "1.20"  # Max $1.20/h
```

**Points clés :**
- AMI résolu dynamiquement via SSM Parameter Store (toujours la dernière version)
- 3 types d'instances avec priorité (g6 préféré, g5 en fallback)
- Allocation optimisée par capacité avec priorité
- Budget max $1.20/h pour contrôle des coûts

---

## 7. Interface Admin (simplifiée)

### 7.1 États principaux

```
┌─────────────────────────────────────────────────────────────────────┐
│  Admin > Burst Mode                                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  STATUS: ⚪ IDLE / 🔄 PROCESSING / ⚠️ INTERRUPTED / ✅ DONE │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────┐  ┌────────────────────────────┐   │
│  │   FICHIERS PENDING          │  │   TIMELINE                 │   │
│  │   data/burst/pending/       │  │                            │   │
│  │                             │  │   14:30 Batch créé         │   │
│  │   📄 RISE_2025.pptx         │  │   14:31 Spot demandé       │   │
│  │   📄 SAP_Security.pdf       │  │   14:35 Instance allouée   │   │
│  │   📄 BTP_Overview.pptx      │  │   14:37 Services ready     │   │
│  │   ...                       │  │   14:38 Doc #1 started     │   │
│  │                             │  │   ...                      │   │
│  │   Total: 100 fichiers       │  │                            │   │
│  │                             │  │                            │   │
│  │   [🚀 Lancer Burst]         │  │                            │   │
│  └─────────────────────────────┘  └────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  PROGRESSION: ████████████░░░░░░░░░░  48/100                │   │
│  │  ✅ Done: 48  🔄 Current: 1  ⏳ Pending: 51  ❌ Failed: 0    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Instance: i-0abc123 (g5.xlarge) @ $0.32/h                         │
│  Interruptions: 0                                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.2 États spécifiques

**WAITING_CAPACITY:**
```
⏳ En attente de capacité Spot...
   Temps d'attente: 3 min 22 sec

   ℹ️ Normal pour Spot, peut prendre quelques minutes
```

**INTERRUPTED:**
```
⚠️ Instance Spot interrompue par AWS

   Documents traités: 48/100
   Tentative reprise: 2/5

   🔄 Demande nouvelle instance en cours...
```

---

## 8. Configuration

### 8.1 Variables d'environnement

```bash
# .env

# === Mode Burst ===
BURST_MODE_ENABLED=true

# === AWS ===
BURST_AWS_REGION=eu-west-1
BURST_VPC_ID=vpc-xxx
BURST_SUBNET_ID=subnet-xxx

# === Spot (g6 pour L4 GPU, g5 en fallback) ===
BURST_SPOT_MAX_PRICE=1.20
BURST_SPOT_INSTANCE_TYPES=g6.2xlarge,g6e.xlarge,g5.2xlarge

# === Models (sur EC2) ===
BURST_VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct-AWQ
BURST_EMBEDDINGS_MODEL=intfloat/multilingual-e5-large

# === vLLM AWQ Configuration ===
BURST_VLLM_QUANTIZATION=awq        # awq, gptq, squeezellm, none
BURST_VLLM_DTYPE=half              # FP16 pour AWQ
BURST_VLLM_GPU_MEMORY_UTILIZATION=0.85
BURST_VLLM_MAX_MODEL_LEN=8192
BURST_VLLM_MAX_NUM_SEQS=32

# === Deep Learning AMI ===
BURST_USE_DEEP_LEARNING_AMI=true
BURST_DEEP_LEARNING_AMI_OS=ubuntu-22.04  # ou amazon-linux-2023

# === Timeouts (augmentés pour 14B) ===
BURST_INSTANCE_BOOT_TIMEOUT=900    # 15 min (DLAMI + modèle 14B)
BURST_MODEL_LOAD_TIMEOUT=600       # 10 min pour le modèle seul
BURST_HEALTHCHECK_INTERVAL=15
BURST_HEALTHCHECK_TIMEOUT=10
BURST_MAX_RETRIES=3
BURST_MAX_INTERRUPTION_RETRIES=5
```

---

## 9. Plan d'implémentation

### Mise à jour v2.1 : Qwen 14B AWQ + Deep Learning AMI ✅ COMPLÉTÉ 2025-12-27

Suite à l'analyse de la configuration initiale, les modifications suivantes ont été apportées :

**1. Modèle upgradé de 7B à 14B AWQ :**
- `Qwen/Qwen2.5-7B-Instruct` → `Qwen/Qwen2.5-14B-Instruct-AWQ`
- Qualité nettement supérieure, même coût Spot grâce à la quantification AWQ

**2. Configuration vLLM pour AWQ ajoutée :**
- `--quantization awq` : Active le décodeur AWQ
- `--dtype half` : FP16 obligatoire pour AWQ
- `--gpu-memory-utilization 0.85` : Cohabitation avec TEI
- `--max-model-len 8192` : Context window
- `--max-num-seqs 32` : Limite concurrence

**3. Instances GPU optimisées :**
- `g5.xlarge` → `g6.2xlarge, g6e.xlarge, g5.2xlarge`
- L4 GPU (g6) préféré : plus récent, meilleur rapport performance/prix
- A10G (g5) en fallback pour disponibilité

**4. Deep Learning AMI :**
- AMI Amazon Linux 2023 → AWS Deep Learning AMI (PyTorch 2.5, Ubuntu 22.04)
- Résolution dynamique via SSM Parameter Store
- Drivers NVIDIA préinstallés → boot 5-10 min plus rapide

**5. Timeouts augmentés :**
- Boot timeout : 600s → 900s (modèle 14B plus long à charger)
- Model load timeout : 600s (nouveau paramètre)

**Fichiers modifiés :**
- `src/knowbase/ingestion/burst/types.py` : +nouveaux paramètres AWQ et AMI
- `src/knowbase/ingestion/burst/cloudformation/burst-spot.yaml` : Réécrit pour 14B AWQ

---

### Phase 1: Provider Switch (1-2 jours) ✅ COMPLÉTÉ 2025-12-27
- [x] Modifier `LLMRouter` pour support burst mode (+140 lignes)
- [x] Modifier `EmbeddingManager` pour support burst mode (+80 lignes)
- [x] Créer `provider_switch.py` (210 lignes)
- [x] Créer `resilient_client.py` (290 lignes)
- [x] Tests imports validés

**Fichiers modifiés/créés :**
- `src/knowbase/common/llm_router.py` : `enable_burst_mode()`, `disable_burst_mode()`, `_call_burst_vllm()`
- `src/knowbase/common/clients/embeddings.py` : `enable_burst_mode()`, `disable_burst_mode()`, `_encode_remote()`
- `src/knowbase/ingestion/burst/provider_switch.py` : activation/désactivation coordonnée
- `src/knowbase/ingestion/burst/resilient_client.py` : retry/backoff pour appels EC2

### Phase 2: Orchestrateur (2-3 jours) ✅ COMPLÉTÉ 2025-12-27
- [x] Créer `BurstOrchestrator` (550 lignes)
- [x] Créer `types.py` avec BurstState, BurstStatus, BurstConfig (250 lignes)
- [x] CloudFormation Spot Fleet template (340 lignes)
- [x] Healthcheck logic
- [x] Interruption handling avec reprise automatique
- [x] Timeline d'événements

**Fichiers créés :**
- `src/knowbase/ingestion/burst/types.py` : 12 états, dataclasses sérialisables
- `src/knowbase/ingestion/burst/orchestrator.py` : cycle de vie complet
- `src/knowbase/ingestion/burst/cloudformation/burst-spot.yaml` : template Spot Fleet

### Phase 3: Services EC2 (1-2 jours) ✅ INCLUS DANS PHASE 2
- [x] Script bootstrap (UserData dans CloudFormation)
- [x] Docker vLLM + TEI configuré
- [x] Health endpoint Python

### Phase 4: API & Admin (2 jours) ✅ COMPLÉTÉ 2025-12-27
- [x] Endpoints `/api/burst/*` (570 lignes)
  - GET /status - Statut actuel du mode Burst
  - GET /config - Configuration Burst
  - POST /prepare - Préparer un batch de documents
  - POST /start - Démarrer l'infrastructure Spot
  - POST /process - Lancer le traitement du batch
  - POST /cancel - Annuler le batch en cours
  - GET /events - Timeline des événements
  - GET /documents - Statut des documents du batch
  - GET /providers - Statut des providers (LLM/Embeddings)
- [x] Page admin simplifiée (550 lignes)
  - Dashboard avec statut, progression, statistiques
  - Actions: Préparer/Démarrer/Lancer/Annuler
  - Timeline événements temps réel
  - Liste documents avec statuts
  - Configuration affichée
- [x] Timeline events frontend avec auto-refresh 5s

**Fichiers créés:**
- `src/knowbase/api/routers/burst.py` : Endpoints API complets
- `frontend/src/app/admin/burst/page.tsx` : Page admin Chakra UI

### Phase 5: Tests E2E (1-2 jours) ⏳ À FAIRE
- [ ] Test batch complet
- [ ] Test interruption Spot
- [ ] Documentation

**Total estimé: 7-11 jours**
**Réalisé: Phases 1-4 en 2 sessions (env. 3-4h)**

---

## 10. Résumé

### Architecture

| Aspect | Avant (v1.0) | Après (v2.0/2.1) |
|--------|--------------|------------------|
| Documents | Upload S3 | Restent locaux |
| Pipeline | Sur EC2 | Local (inchangé) |
| EC2 Spot | Worker complet | Provider API |
| Qdrant/Neo4j | Import depuis S3 | Local direct |
| Complexité | Haute | Moyenne |
| S3 usage | Documents + artifacts | État minimal |

### Configuration v2.1

| Composant | Configuration |
|-----------|---------------|
| **Modèle LLM** | Qwen/Qwen2.5-14B-Instruct-AWQ (4-bit quantifié) |
| **Quantification** | AWQ avec dtype=half |
| **Embeddings** | intfloat/multilingual-e5-large (TEI 1.5) |
| **Instances** | g6.2xlarge (L4), g6e.xlarge, g5.2xlarge (fallback) |
| **AMI** | Deep Learning AMI PyTorch 2.5 Ubuntu 22.04 |
| **VRAM** | ~10GB vLLM + ~2GB TEI = ~12GB / 24GB |
| **Coût max** | $1.20/h (Spot) |
| **Boot time** | ~8-12 min (DLAMI optimisé) |

**L'EC2 Spot est un endpoint de compute temporaire, pas un worker.**

---

*Document v2.1 - Ajout support Qwen 14B AWQ + Deep Learning AMI*
