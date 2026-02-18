"""
OSMOSE Burst Orchestrator - Orchestration du mode Burst EC2 Spot

Orchestre le cycle de vie complet d'un batch en mode Burst :
1. Provisioning EC2 Spot via CloudFormation
2. Attente et healthcheck des services
3. Basculement des providers
4. Gestion du traitement avec reprise sur interruption
5. Teardown à la fin

Author: OSMOSE Burst Ingestion
Date: 2025-12
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

import requests

from .types import (
    BurstStatus,
    BurstState,
    BurstConfig,
    BurstEvent,
    DocumentStatus,
    EventSeverity
)
from .provider_switch import (
    activate_burst_providers,
    deactivate_burst_providers,
    check_burst_providers_health
)
from .resilient_client import BurstProviderUnavailable

logger = logging.getLogger(__name__)

# Import conditionnel boto3
try:
    import boto3
    from botocore.exceptions import ClientError, WaiterError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("[BURST] boto3 not available - CloudFormation features disabled")


class BurstOrchestrationError(Exception):
    """Erreur d'orchestration du mode Burst."""
    pass


class BurstOrchestrator:
    """
    Orchestre le mode Burst :
    - Provision EC2 Spot
    - Bascule les providers
    - Gère les interruptions
    - Teardown à la fin

    Usage:
        orchestrator = BurstOrchestrator()

        # Préparer un batch
        batch_id = orchestrator.prepare_batch(document_paths)

        # Démarrer l'infrastructure
        orchestrator.start_infrastructure()

        # Traiter les documents (callback par document)
        orchestrator.process_batch(process_document_callback)

        # Cleanup automatique à la fin
    """

    def __init__(self, config: Optional[BurstConfig] = None):
        """
        Initialise l'orchestrateur.

        Args:
            config: Configuration du mode Burst (défaut: depuis env)
        """
        self.config = config or BurstConfig.from_env()
        self.state: Optional[BurstState] = None

        # Clients AWS (lazy init)
        self._cf_client = None
        self._ec2_client = None

        # Callback pour traitement document
        self._document_processor: Optional[Callable] = None

        logger.info("[BURST:ORCHESTRATOR] Initialized")

    @property
    def cf_client(self):
        """Client CloudFormation lazy."""
        if self._cf_client is None and BOTO3_AVAILABLE:
            self._cf_client = boto3.client(
                'cloudformation',
                region_name=self.config.aws_region
            )
        return self._cf_client

    @property
    def ec2_client(self):
        """Client EC2 lazy."""
        if self._ec2_client is None and BOTO3_AVAILABLE:
            self._ec2_client = boto3.client(
                'ec2',
                region_name=self.config.aws_region
            )
        return self._ec2_client

    # =========================================================================
    # Reconnexion à une infrastructure existante
    # =========================================================================

    def reconnect_to_stack(self, stack_name: str) -> bool:
        """
        Reconnecte l'orchestrator à une stack CloudFormation existante.

        Utilisé après un redémarrage du container pour récupérer l'état.

        Args:
            stack_name: Nom de la stack CloudFormation

        Returns:
            True si reconnexion réussie
        """
        if not BOTO3_AVAILABLE:
            raise BurstOrchestrationError("boto3 not available")

        try:
            # 1. Récupérer les infos de la stack
            response = self.cf_client.describe_stacks(StackName=stack_name)
            stack = response['Stacks'][0]

            if stack['StackStatus'] != 'CREATE_COMPLETE':
                raise BurstOrchestrationError(
                    f"Stack not ready: {stack['StackStatus']}"
                )

            outputs = {o['OutputKey']: o['OutputValue'] for o in stack.get('Outputs', [])}
            spot_fleet_id = outputs.get('SpotFleetId')

            if not spot_fleet_id:
                raise BurstOrchestrationError("SpotFleetId not found in stack outputs")

            # 2. Récupérer l'instance
            response = self.ec2_client.describe_spot_fleet_instances(
                SpotFleetRequestId=spot_fleet_id
            )
            instances = response.get('ActiveInstances', [])

            if not instances:
                raise BurstOrchestrationError("No active instances in SpotFleet")

            instance_id = instances[0]['InstanceId']

            # 3. Détails de l'instance
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            instance = response['Reservations'][0]['Instances'][0]

            if instance['State']['Name'] != 'running':
                raise BurstOrchestrationError(
                    f"Instance not running: {instance['State']['Name']}"
                )

            public_ip = instance.get('PublicIpAddress')
            if not public_ip:
                raise BurstOrchestrationError("Instance has no public IP")

            instance_type = instance['InstanceType']

            # 4. Extraire batch_id du stack_name (format: knowwhere-burst-{batch_id})
            batch_id = stack_name.replace("knowwhere-burst-", "")

            # 5. Créer l'état restauré
            self.state = BurstState(
                batch_id=batch_id,
                status=BurstStatus.READY,
                stack_name=stack_name,
                spot_fleet_id=spot_fleet_id,
                instance_id=instance_id,
                instance_ip=public_ip,
                instance_type=instance_type,
                vllm_url=f"http://{public_ip}:{self.config.vllm_port}",
                embeddings_url=f"http://{public_ip}:{self.config.embeddings_port}",
                created_at=datetime.now(timezone.utc).isoformat(),
                config=self.config.to_dict()
            )

            # 6. Vérifier les services
            health = check_burst_providers_health(
                vllm_url=self.state.vllm_url,
                embeddings_url=self.state.embeddings_url,
                timeout=self.config.healthcheck_timeout
            )

            if not health['ready']:
                self.state.status = BurstStatus.INSTANCE_STARTING
                self._add_event(
                    "reconnected_waiting",
                    f"Reconnecté à {stack_name}, services en attente",
                    details=health
                )
            else:
                # 7. Activer les providers
                activate_burst_providers(
                    vllm_url=self.state.vllm_url,
                    embeddings_url=self.state.embeddings_url
                )
                self._add_event(
                    "reconnected_ready",
                    f"Reconnecté à {stack_name}, prêt",
                    details={"instance_ip": public_ip, "instance_type": instance_type}
                )

            logger.info(
                f"[BURST:ORCHESTRATOR] Reconnected to stack {stack_name} "
                f"(instance {instance_id} @ {public_ip})"
            )

            return True

        except ClientError as e:
            raise BurstOrchestrationError(f"AWS error during reconnection: {e}")

    def find_active_burst_stacks(self) -> List[Dict[str, Any]]:
        """
        Trouve les stacks Burst actives.

        Returns:
            Liste des stacks avec leurs détails
        """
        if not BOTO3_AVAILABLE:
            return []

        try:
            response = self.cf_client.describe_stacks()
            active_stacks = []

            for stack in response.get('Stacks', []):
                name = stack['StackName']
                status = stack['StackStatus']

                # Filtrer les stacks burst actives
                if name.startswith('knowwhere-burst-') and status == 'CREATE_COMPLETE':
                    outputs = {
                        o['OutputKey']: o['OutputValue']
                        for o in stack.get('Outputs', [])
                    }
                    active_stacks.append({
                        'stack_name': name,
                        'status': status,
                        'created': stack.get('CreationTime'),
                        'spot_fleet_id': outputs.get('SpotFleetId'),
                    })

            return active_stacks

        except ClientError as e:
            logger.error(f"[BURST:ORCHESTRATOR] Error listing stacks: {e}")
            return []

    # =========================================================================
    # Préparation du batch
    # =========================================================================

    def prepare_batch(
        self,
        document_paths: List[Path],
        batch_id: Optional[str] = None
    ) -> str:
        """
        Prépare un batch de documents pour traitement.

        Args:
            document_paths: Liste des chemins de documents
            batch_id: ID optionnel (généré si non fourni)

        Returns:
            batch_id du batch créé
        """
        if not document_paths:
            raise ValueError("No documents provided")

        # Générer batch_id
        if batch_id is None:
            batch_id = f"burst-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        # Créer documents status
        documents = []
        for path in document_paths:
            path = Path(path)
            if not path.exists():
                logger.warning(f"[BURST] Document not found: {path}")
                continue

            documents.append(DocumentStatus(
                path=str(path.absolute()),
                name=path.name,
                status="pending"
            ))

        if not documents:
            raise ValueError("No valid documents found")

        # Créer état initial
        self.state = BurstState(
            batch_id=batch_id,
            status=BurstStatus.PREPARING,
            documents=documents,
            total_documents=len(documents),
            created_at=datetime.now(timezone.utc).isoformat(),
            config=self.config.to_dict()
        )

        self._add_event(
            "batch_created",
            f"Batch créé avec {len(documents)} documents",
            details={"document_count": len(documents)}
        )

        logger.info(f"[BURST:ORCHESTRATOR] Batch prepared: {batch_id} ({len(documents)} docs)")

        return batch_id

    # =========================================================================
    # Infrastructure EC2
    # =========================================================================

    def start_infrastructure(self) -> bool:
        """
        Démarre l'infrastructure EC2 Spot.

        Optimisation 2024-12-30: Réutilise un fleet existant en veille (capacity=0)
        pour un démarrage plus rapide (~1-2 min vs ~5-7 min).

        1. Vérifie si une stack existante peut être réutilisée
        2. Si fleet en veille (capacity=0), scale up à 1
        3. Sinon, déploie CloudFormation
        4. Attend l'instance
        5. Attend les services (healthcheck)
        6. Bascule les providers

        Returns:
            True si infrastructure prête
        """
        if self.state is None:
            raise BurstOrchestrationError("No batch prepared. Call prepare_batch() first.")

        if not BOTO3_AVAILABLE:
            raise BurstOrchestrationError("boto3 not available. Cannot manage EC2.")

        try:
            # 0. Vérifier si une stack existante peut être réutilisée
            existing_stacks = self.find_active_burst_stacks()
            if existing_stacks:
                stack = existing_stacks[0]
                self.state.stack_name = stack['stack_name']
                self.state.spot_fleet_id = stack['spot_fleet_id']

                # Vérifier si le fleet est en veille (capacity=0)
                fleet_capacity = self._get_fleet_target_capacity(stack['spot_fleet_id'])

                if fleet_capacity == 0:
                    # Fleet en veille - scale up rapide!
                    logger.info(
                        f"[BURST:ORCHESTRATOR] ⚡ Fast start: scaling up existing fleet "
                        f"{stack['spot_fleet_id']} (0→1)"
                    )
                    self._add_event(
                        "fleet_scale_up",
                        f"Redémarrage rapide du fleet {stack['spot_fleet_id']}",
                        details={"previous_capacity": 0, "new_capacity": 1}
                    )

                    self.ec2_client.modify_spot_fleet_request(
                        SpotFleetRequestId=stack['spot_fleet_id'],
                        TargetCapacity=1
                    )
                    self.state.status = BurstStatus.INSTANCE_STARTING

                else:
                    # Fleet déjà actif - vérifier instance existante
                    logger.info(
                        f"[BURST:ORCHESTRATOR] Réutilisation de la stack existante: {stack['stack_name']} "
                        f"(capacity={fleet_capacity})"
                    )
                    self._add_event(
                        "reusing_existing_stack",
                        f"Réutilisation de {stack['stack_name']}",
                        details=stack
                    )
                    self.state.status = BurstStatus.INSTANCE_STARTING
            else:
                # 1. Déployer CloudFormation (nouvelle stack)
                self._deploy_spot_infrastructure()

            # 2. Attendre l'instance
            self._wait_for_instance()

            # 3. Attendre les services
            self._wait_for_services()

            # 4. Basculer les providers
            self._switch_to_burst_providers()

            self.state.status = BurstStatus.READY
            self._add_event("infrastructure_ready", "Infrastructure prête")

            return True

        except Exception as e:
            self.state.status = BurstStatus.FAILED
            self._add_event(
                "infrastructure_failed",
                f"Échec démarrage infrastructure: {e}",
                EventSeverity.ERROR
            )
            logger.error(f"[BURST:ORCHESTRATOR] Infrastructure failed: {e}")
            self._cleanup_on_failure()
            raise BurstOrchestrationError(f"Infrastructure start failed: {e}")

    def _get_fleet_target_capacity(self, spot_fleet_id: str) -> int:
        """Récupère la TargetCapacity actuelle d'un Spot Fleet."""
        try:
            response = self.ec2_client.describe_spot_fleet_requests(
                SpotFleetRequestIds=[spot_fleet_id]
            )
            configs = response.get('SpotFleetRequestConfigs', [])
            if configs:
                return configs[0].get('SpotFleetRequestConfig', {}).get('TargetCapacity', 0)
        except ClientError as e:
            logger.warning(f"[BURST] Failed to get fleet capacity: {e}")
        return 0

    def _deploy_spot_infrastructure(self):
        """Déploie le stack CloudFormation Spot Fleet."""
        self.state.status = BurstStatus.REQUESTING_SPOT
        self._add_event("cloudformation_starting", "Déploiement CloudFormation")

        stack_name = f"knowwhere-burst-{self.state.batch_id}"
        self.state.stack_name = stack_name

        # Charger template
        template_path = Path(__file__).parent / "cloudformation" / "burst-spot.yaml"

        if not template_path.exists():
            # Utiliser template inline si fichier non présent
            template_body = self._get_inline_cloudformation_template()
        else:
            with open(template_path, "r") as f:
                template_body = f.read()

        # Paramètres CloudFormation
        parameters = [
            {"ParameterKey": "BatchId", "ParameterValue": self.state.batch_id},
            {"ParameterKey": "VllmModel", "ParameterValue": self.config.vllm_model},
            {"ParameterKey": "EmbeddingsModel", "ParameterValue": self.config.embeddings_model},
            {"ParameterKey": "SpotMaxPrice", "ParameterValue": str(self.config.spot_max_price)},
            {"ParameterKey": "VllmPort", "ParameterValue": str(self.config.vllm_port)},
            {"ParameterKey": "EmbeddingsPort", "ParameterValue": str(self.config.embeddings_port)},
            # Paramètres vLLM additionnels
            {"ParameterKey": "VllmGpuMemoryUtilization", "ParameterValue": str(self.config.vllm_gpu_memory_utilization)},
            {"ParameterKey": "VllmQuantization", "ParameterValue": self.config.vllm_quantization},
            {"ParameterKey": "VllmDtype", "ParameterValue": self.config.vllm_dtype},
            {"ParameterKey": "VllmMaxModelLen", "ParameterValue": str(self.config.vllm_max_model_len)},
            {"ParameterKey": "VllmMaxNumSeqs", "ParameterValue": str(self.config.vllm_max_num_seqs)},
            # Optimisations vLLM (2026-01-27)
            {"ParameterKey": "VllmEnablePrefixCaching", "ParameterValue": "true" if self.config.vllm_enable_prefix_caching else "false"},
            {"ParameterKey": "VllmEnableChunkedPrefill", "ParameterValue": "true" if self.config.vllm_enable_chunked_prefill else "false"},
            {"ParameterKey": "VllmMaxNumBatchedTokens", "ParameterValue": str(self.config.vllm_max_num_batched_tokens)},
        ]

        # Ajouter VPC/Subnet si configurés
        if self.config.vpc_id:
            parameters.append({"ParameterKey": "VpcId", "ParameterValue": self.config.vpc_id})
        if self.config.subnet_id:
            parameters.append({"ParameterKey": "SubnetId", "ParameterValue": self.config.subnet_id})

        # Ajouter CallbackUrl pour notifications d'interruption Spot
        if self.config.callback_url:
            parameters.append({"ParameterKey": "CallbackUrl", "ParameterValue": self.config.callback_url})

        try:
            self.cf_client.create_stack(
                StackName=stack_name,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=["CAPABILITY_NAMED_IAM"],
                Tags=[
                    {"Key": "Project", "Value": "KnowWhere"},
                    {"Key": "Component", "Value": "Burst"},
                    {"Key": "BatchId", "Value": self.state.batch_id}
                ]
            )

            self._add_event("cloudformation_submitted", f"Stack {stack_name} soumis")
            logger.info(f"[BURST:ORCHESTRATOR] CloudFormation stack submitted: {stack_name}")

            # Attendre création du stack
            self.state.status = BurstStatus.WAITING_CAPACITY
            self._add_event("waiting_spot", "En attente de capacité Spot")

            waiter = self.cf_client.get_waiter('stack_create_complete')
            waiter.wait(
                StackName=stack_name,
                WaiterConfig={'Delay': 15, 'MaxAttempts': 60}  # 15min max
            )

            self._add_event("cloudformation_complete", "Stack CloudFormation créé")
            logger.info(f"[BURST:ORCHESTRATOR] CloudFormation stack created: {stack_name}")

        except WaiterError as e:
            raise BurstOrchestrationError(f"CloudFormation timeout: {e}")
        except ClientError as e:
            raise BurstOrchestrationError(f"CloudFormation error: {e}")

    def _wait_for_instance(self):
        """Attend que l'instance EC2 soit running et récupère son IP."""
        self.state.status = BurstStatus.INSTANCE_STARTING
        self._add_event("waiting_instance", "Attente démarrage instance")

        # Récupérer les outputs du stack
        try:
            response = self.cf_client.describe_stacks(StackName=self.state.stack_name)
            stack = response['Stacks'][0]
            outputs = {o['OutputKey']: o['OutputValue'] for o in stack.get('Outputs', [])}

            self.state.spot_fleet_id = outputs.get('SpotFleetId')

        except ClientError as e:
            raise BurstOrchestrationError(f"Failed to get stack outputs: {e}")

        # Attendre instance running avec IP
        start_time = time.time()
        timeout = self.config.instance_boot_timeout

        while time.time() - start_time < timeout:
            instance_info = self._get_spot_fleet_instance()

            if instance_info:
                self.state.instance_id = instance_info['instance_id']
                self.state.instance_ip = instance_info['public_ip']
                self.state.instance_type = instance_info['instance_type']
                self.state.instance_launch_time = instance_info.get('launch_time')  # Vrai AWS launch time

                self._add_event(
                    "instance_running",
                    f"Instance {self.state.instance_id} ({self.state.instance_type}) running",
                    details=instance_info
                )
                logger.info(
                    f"[BURST:ORCHESTRATOR] Instance running: {self.state.instance_id} "
                    f"@ {self.state.instance_ip}"
                )
                return

            time.sleep(self.config.healthcheck_interval)

        raise BurstOrchestrationError(f"Instance not ready within {timeout}s")

    def _get_spot_fleet_instance(self) -> Optional[Dict[str, Any]]:
        """Récupère l'instance du Spot Fleet si disponible."""
        if not self.state.spot_fleet_id:
            return None

        try:
            # Lister instances du Spot Fleet
            response = self.ec2_client.describe_spot_fleet_instances(
                SpotFleetRequestId=self.state.spot_fleet_id
            )

            instances = response.get('ActiveInstances', [])
            if not instances:
                return None

            instance_id = instances[0]['InstanceId']

            # Détails de l'instance
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            reservations = response.get('Reservations', [])

            if not reservations or not reservations[0].get('Instances'):
                return None

            instance = reservations[0]['Instances'][0]

            if instance['State']['Name'] != 'running':
                return None

            public_ip = instance.get('PublicIpAddress')
            if not public_ip:
                return None

            return {
                'instance_id': instance_id,
                'instance_type': instance['InstanceType'],
                'public_ip': public_ip,
                'private_ip': instance.get('PrivateIpAddress'),
                'launch_time': instance['LaunchTime'].isoformat()
            }

        except ClientError as e:
            logger.warning(f"[BURST] Failed to get instance info: {e}")
            return None

    def _wait_for_services(self):
        """Attend que les services vLLM et Embeddings soient prêts (healthcheck)."""
        if not self.state.instance_ip:
            raise BurstOrchestrationError("No instance IP available")

        vllm_url = f"http://{self.state.instance_ip}:{self.config.vllm_port}"
        embeddings_url = f"http://{self.state.instance_ip}:{self.config.embeddings_port}"

        self.state.vllm_url = vllm_url
        self.state.embeddings_url = embeddings_url

        self._add_event("waiting_services", "Attente démarrage services")

        start_time = time.time()
        timeout = self.config.instance_boot_timeout

        while time.time() - start_time < timeout:
            health = check_burst_providers_health(
                vllm_url,
                embeddings_url,
                timeout=self.config.healthcheck_timeout
            )

            if health['all_healthy']:
                self._add_event(
                    "services_ready",
                    "Services vLLM et Embeddings prêts"
                )
                logger.info("[BURST:ORCHESTRATOR] Services ready")
                return

            elapsed = int(time.time() - start_time)
            logger.debug(f"[BURST] Waiting for services... ({elapsed}s)")

            time.sleep(self.config.healthcheck_interval)

        raise BurstOrchestrationError(f"Services not ready within {timeout}s")

    def _switch_to_burst_providers(self):
        """Bascule les providers vers EC2."""
        result = activate_burst_providers(
            vllm_url=self.state.vllm_url,
            embeddings_url=self.state.embeddings_url,
            vllm_model=self.config.vllm_model,
            dual_logging=self.state.dual_logging
        )

        if not result['llm_router'] or not result['embedding_manager']:
            raise BurstOrchestrationError(f"Provider switch failed: {result['errors']}")

        if self.state.dual_logging:
            self._add_event("dual_logging_enabled", "Mode dual-logging activé: OpenAI + vLLM")
        else:
            self._add_event("providers_switched", "Providers basculés vers EC2")

    # =========================================================================
    # Traitement du batch
    # =========================================================================

    def process_batch(
        self,
        document_processor: Callable[[Path], Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Traite le batch de documents.

        Args:
            document_processor: Callback(path) -> {"success": bool, "chunks": int, "error": str}

        Returns:
            Statistiques de traitement
        """
        if self.state is None:
            raise BurstOrchestrationError("No batch prepared")

        if self.state.status != BurstStatus.READY:
            raise BurstOrchestrationError(
                f"Cannot process in status: {self.state.status}. "
                "Call start_infrastructure() first."
            )

        self._document_processor = document_processor
        self.state.status = BurstStatus.PROCESSING
        self.state.started_at = datetime.now(timezone.utc).isoformat()

        self._add_event("processing_started", "Traitement du batch démarré")

        try:
            self._process_pending_documents()

        except BurstProviderUnavailable:
            # Interruption Spot probable
            self._handle_interruption()

        except Exception as e:
            self._add_event(
                "processing_error",
                f"Erreur pendant traitement: {e}",
                EventSeverity.ERROR
            )
            logger.error(f"[BURST:ORCHESTRATOR] Processing error: {e}")
            raise

        finally:
            # Cleanup si tout est traité
            if self._all_documents_processed():
                self._complete_batch()

        return self.state.get_progress()

    def _check_for_spot_interruption(self) -> bool:
        """
        Vérifie si une interruption Spot est imminente via le health endpoint.

        Returns:
            True si interruption détectée, False sinon
        """
        if not self.state or not self.state.instance_ip:
            return False

        try:
            from .provider_switch import check_instance_health_with_spot

            health = check_instance_health_with_spot(self.state.instance_ip)

            if health.get("spot_interruption"):
                logger.warning(
                    f"[BURST:ORCHESTRATOR] ⚠️ Spot interruption detected: {health['spot_interruption']}"
                )
                return True

        except Exception as e:
            logger.debug(f"[BURST] Spot check error (non-fatal): {e}")

        return False

    def _process_pending_documents(self):
        """Traite les documents en attente."""
        pending = self.state.get_pending_documents()
        last_spot_check = time.time()
        SPOT_CHECK_INTERVAL = 30  # Vérifier toutes les 30 secondes

        for doc in pending:
            # Vérifier périodiquement si une interruption Spot est imminente
            if time.time() - last_spot_check > SPOT_CHECK_INTERVAL:
                if self._check_for_spot_interruption():
                    # Interruption détectée - sauvegarder et arrêter
                    self._add_event(
                        "spot_warning_detected",
                        "⚠️ Interruption Spot détectée via health check - sauvegarde en cours",
                        EventSeverity.WARNING
                    )
                    self.initiate_graceful_shutdown()
                    raise BurstProviderUnavailable("Spot interruption imminent")
                last_spot_check = time.time()

            try:
                doc.status = "processing"
                doc.started_at = datetime.now(timezone.utc).isoformat()

                self._add_event(
                    "doc_started",
                    f"Traitement: {doc.name}",
                    details={"path": doc.path}
                )

                # Appeler le processor
                result = self._document_processor(Path(doc.path))

                if result.get("success", False):
                    doc.status = "completed"
                    doc.chunks_count = result.get("chunks", 0)
                    self.state.documents_done += 1

                    self._add_event(
                        "doc_completed",
                        f"Terminé: {doc.name} ({doc.chunks_count} chunks)"
                    )
                else:
                    doc.status = "failed"
                    doc.error = result.get("error", "Unknown error")
                    self.state.documents_failed += 1

                    self._add_event(
                        "doc_failed",
                        f"Échec: {doc.name} - {doc.error}",
                        EventSeverity.ERROR
                    )

                doc.completed_at = datetime.now(timezone.utc).isoformat()

            except BurstProviderUnavailable:
                # Interruption - propager
                doc.status = "pending"  # Remettre en attente
                raise

            except Exception as e:
                doc.status = "failed"
                doc.error = str(e)
                doc.completed_at = datetime.now(timezone.utc).isoformat()
                self.state.documents_failed += 1

                self._add_event(
                    "doc_failed",
                    f"Échec: {doc.name} - {e}",
                    EventSeverity.ERROR
                )

    def _handle_interruption(self):
        """Gère une interruption Spot."""
        self.state.interruption_count += 1
        self.state.status = BurstStatus.INTERRUPTED

        self._add_event(
            "spot_interrupted",
            f"Instance Spot interrompue (tentative {self.state.interruption_count})",
            EventSeverity.WARNING
        )

        logger.warning(
            f"[BURST:ORCHESTRATOR] Spot interrupted "
            f"(attempt {self.state.interruption_count}/{self.config.max_interruption_retries})"
        )

        # Désactiver les providers
        deactivate_burst_providers()

        # Vérifier limite de retries
        if self.state.interruption_count >= self.config.max_interruption_retries:
            self.state.status = BurstStatus.FAILED
            self._add_event(
                "max_interruptions",
                f"Nombre maximum d'interruptions atteint ({self.config.max_interruption_retries})",
                EventSeverity.ERROR
            )
            raise BurstOrchestrationError("Max interruption retries exceeded")

        # Tenter reprise
        self._resume_after_interruption()

    def _resume_after_interruption(self):
        """Reprend le traitement après une interruption Spot."""
        self.state.status = BurstStatus.RESUMING
        self._add_event("resuming", "Tentative de reprise après interruption")

        try:
            # Le Spot Fleet devrait maintenir la capacité target
            # Attendre une nouvelle instance
            self._wait_for_instance()
            self._wait_for_services()
            self._switch_to_burst_providers()

            self.state.status = BurstStatus.READY
            self._add_event("resume_success", "Reprise réussie")

            # Reprendre le traitement
            self._process_pending_documents()

        except Exception as e:
            self._add_event(
                "resume_failed",
                f"Échec reprise: {e}",
                EventSeverity.ERROR
            )
            raise

    def _all_documents_processed(self) -> bool:
        """Vérifie si tous les documents sont traités."""
        pending = self.state.get_pending_documents()
        return len(pending) == 0

    def _complete_batch(self):
        """Finalise le batch."""
        self.state.status = BurstStatus.COMPLETED
        self.state.completed_at = datetime.now(timezone.utc).isoformat()

        # Désactiver providers
        deactivate_burst_providers()

        # Teardown infrastructure
        self._teardown_infrastructure()

        progress = self.state.get_progress()
        self._add_event(
            "batch_completed",
            f"Batch terminé: {progress['done']} réussis, "
            f"{progress['failed']} échecs, "
            f"{self.state.interruption_count} interruptions"
        )

        logger.info(f"[BURST:ORCHESTRATOR] Batch completed: {progress}")

    # =========================================================================
    # Teardown
    # =========================================================================

    def _teardown_infrastructure(self, keep_fleet: bool = True):
        """
        Arrête l'infrastructure EC2.

        Args:
            keep_fleet: Si True, réduit TargetCapacity à 0 au lieu de supprimer la stack.
                       Cela permet un redémarrage plus rapide au prochain batch.
                       (défaut: True - optimisation 2024-12-30)
        """
        if not self.state.stack_name:
            return

        try:
            if keep_fleet and self.state.spot_fleet_id:
                # Optimisation: réduire capacity à 0 au lieu de supprimer
                # Cela garde le fleet, security group, IAM roles pour réutilisation
                self._add_event("teardown_scale_down", "Réduction capacity fleet à 0")

                self.ec2_client.modify_spot_fleet_request(
                    SpotFleetRequestId=self.state.spot_fleet_id,
                    TargetCapacity=0
                )

                logger.info(
                    f"[BURST:ORCHESTRATOR] Fleet capacity set to 0: {self.state.spot_fleet_id} "
                    f"(stack kept for fast restart)"
                )

                self._add_event(
                    "teardown_complete",
                    "Infrastructure mise en veille (fleet capacity=0)"
                )
            else:
                # Suppression complète de la stack
                self._add_event("teardown_started", "Suppression infrastructure")

                self.cf_client.delete_stack(StackName=self.state.stack_name)

                logger.info(f"[BURST:ORCHESTRATOR] Stack deletion initiated: {self.state.stack_name}")

                self._add_event("teardown_initiated", "Suppression stack initiée")

        except ClientError as e:
            self._add_event(
                "teardown_error",
                f"Erreur teardown: {e}",
                EventSeverity.WARNING
            )
            logger.warning(f"[BURST:ORCHESTRATOR] Teardown error: {e}")

    def _cleanup_on_failure(self):
        """Nettoyage en cas d'échec."""
        deactivate_burst_providers()
        self._teardown_infrastructure()

    def cancel(self):
        """Annule le batch en cours et détruit l'infrastructure."""
        if self.state is None:
            return

        self.state.status = BurstStatus.CANCELLED
        self._add_event("batch_cancelled", "Batch annulé par l'utilisateur (infrastructure détruite)")

        deactivate_burst_providers()
        self._teardown_infrastructure()

        logger.info("[BURST:ORCHESTRATOR] Batch cancelled with infrastructure teardown")

    def cancel_processing_only(self):
        """
        Annule le traitement en cours SANS détruire l'infrastructure.

        L'instance EC2 reste active et les providers restent configurés.
        Permet de relancer un nouveau batch immédiatement sans attendre le boot.
        """
        if self.state is None:
            return

        # Sauvegarder les infos d'infrastructure
        instance_ip = self.state.instance_ip
        instance_type = self.state.instance_type
        vllm_url = self.state.vllm_url
        embeddings_url = self.state.embeddings_url
        stack_name = self.state.stack_name

        self._add_event(
            "processing_cancelled",
            "Traitement annulé (infrastructure conservée)",
            EventSeverity.WARNING
        )

        # Remettre le statut à READY pour permettre un nouveau traitement
        self.state.status = BurstStatus.READY
        self.state.documents = []
        self.state.total_documents = 0
        self.state.documents_done = 0
        self.state.documents_failed = 0

        # Conserver les infos d'infrastructure
        self.state.instance_ip = instance_ip
        self.state.instance_type = instance_type
        self.state.vllm_url = vllm_url
        self.state.embeddings_url = embeddings_url
        self.state.stack_name = stack_name

        logger.info("[BURST:ORCHESTRATOR] Processing cancelled - infrastructure kept active")

    def initiate_graceful_shutdown(self):
        """
        Déclenche un arrêt gracieux suite à une notification d'interruption Spot.

        Actions:
        1. Marque le batch comme interrompu
        2. Sauvegarde l'état actuel dans un fichier
        3. Termine proprement les jobs en cours (si possible)
        4. Prépare la reprise pour le prochain démarrage
        """
        if self.state is None:
            logger.warning("[BURST] graceful_shutdown called but no state")
            return

        logger.warning("[BURST:ORCHESTRATOR] Initiating graceful shutdown...")

        # Marquer le statut
        self.state.status = BurstStatus.INTERRUPTED
        self._add_event(
            "graceful_shutdown_started",
            "Arrêt gracieux initié - sauvegarde état en cours",
            EventSeverity.WARNING
        )

        # Sauvegarder l'état pour reprise
        try:
            self._save_state_for_resume()
            self._add_event(
                "state_saved",
                f"État sauvegardé pour reprise ({self._get_state_file_path()})"
            )
        except Exception as e:
            logger.error(f"[BURST] Failed to save state: {e}")
            self._add_event(
                "state_save_failed",
                f"Échec sauvegarde état: {e}",
                EventSeverity.ERROR
            )

        # Désactiver les providers pour éviter de nouveaux appels
        deactivate_burst_providers()

        logger.warning("[BURST:ORCHESTRATOR] Graceful shutdown complete - ready for resume")

    def _get_state_file_path(self) -> Path:
        """Retourne le chemin du fichier de sauvegarde d'état."""
        state_dir = Path("/app/data/burst_state") if Path("/app").exists() else Path("data/burst_state")
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"burst_state_{self.state.batch_id}.json"

    def _save_state_for_resume(self):
        """Sauvegarde l'état du batch pour une reprise ultérieure."""
        if not self.state:
            return

        state_file = self._get_state_file_path()

        # Préparer les données à sauvegarder
        state_data = {
            "batch_id": self.state.batch_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "status": self.state.status.value,
            "documents": [
                {
                    "name": doc.name,
                    "path": doc.path,
                    "status": doc.status,
                    "hash": doc.hash,
                    "chunks_count": doc.chunks_count,
                    "error": doc.error,
                    "started_at": doc.started_at,
                    "completed_at": doc.completed_at,
                }
                for doc in self.state.documents
            ],
            "progress": self.state.get_progress(),
            "interruption_count": self.state.interruption_count,
            "stack_name": self.state.stack_name,
            "spot_fleet_id": self.state.spot_fleet_id,
        }

        import json
        with open(state_file, "w") as f:
            json.dump(state_data, f, indent=2)

        logger.info(f"[BURST] State saved to {state_file}")

    def load_saved_state(self) -> Optional[Dict]:
        """
        Charge un état sauvegardé pour reprise.

        Returns:
            Dict avec l'état sauvegardé ou None si aucun état trouvé
        """
        state_dir = Path("/app/data/burst_state") if Path("/app").exists() else Path("data/burst_state")

        if not state_dir.exists():
            return None

        # Trouver le fichier d'état le plus récent
        state_files = list(state_dir.glob("burst_state_*.json"))
        if not state_files:
            return None

        latest_file = max(state_files, key=lambda f: f.stat().st_mtime)

        import json
        with open(latest_file) as f:
            state_data = json.load(f)

        logger.info(f"[BURST] Loaded saved state from {latest_file}")
        return state_data

    def get_resumable_documents(self) -> List[str]:
        """
        Retourne la liste des documents à reprendre (non complétés).

        Returns:
            Liste des chemins de fichiers à retraiter
        """
        saved_state = self.load_saved_state()
        if not saved_state:
            return []

        # Documents qui n'ont pas été complétés avec succès
        resumable = [
            doc["path"]
            for doc in saved_state.get("documents", [])
            if doc["status"] not in ("completed", "done")
        ]

        return resumable

    def clear_saved_state(self, batch_id: Optional[str] = None):
        """Supprime l'état sauvegardé après reprise réussie."""
        state_dir = Path("/app/data/burst_state") if Path("/app").exists() else Path("data/burst_state")

        if batch_id:
            state_file = state_dir / f"burst_state_{batch_id}.json"
            if state_file.exists():
                state_file.unlink()
                logger.info(f"[BURST] Cleared saved state: {state_file}")
        else:
            # Supprimer tous les états
            for f in state_dir.glob("burst_state_*.json"):
                f.unlink()
            logger.info("[BURST] Cleared all saved states")

    # =========================================================================
    # État et événements
    # =========================================================================

    def _add_event(
        self,
        event_type: str,
        message: str,
        severity: EventSeverity = EventSeverity.INFO,
        details: Optional[Dict[str, Any]] = None
    ):
        """Ajoute un événement à la timeline."""
        if self.state:
            self.state.add_event(event_type, message, severity, details)
        logger.log(
            logging.WARNING if severity == EventSeverity.ERROR else logging.INFO,
            f"[BURST:{event_type.upper()}] {message}"
        )

    def get_state(self) -> Optional[BurstState]:
        """Retourne l'état actuel."""
        return self.state

    def get_status(self) -> Dict[str, Any]:
        """Retourne un résumé du statut."""
        if self.state is None:
            return {"status": "no_batch", "batch_id": None}

        return {
            "batch_id": self.state.batch_id,
            "status": self.state.status.value,
            "progress": self.state.get_progress(),
            "instance_id": self.state.instance_id,
            "instance_ip": self.state.instance_ip,
            "interruption_count": self.state.interruption_count,
            "events_count": len(self.state.events),
            "last_event": self.state.events[-1].message if self.state.events else None
        }

    # =========================================================================
    # CloudFormation Template (inline fallback)
    # =========================================================================

    def _get_inline_cloudformation_template(self) -> str:
        """Template CloudFormation inline (fallback si fichier non présent)."""
        return '''
AWSTemplateFormatVersion: '2010-09-09'
Description: 'OSMOSE Burst - EC2 Spot for LLM/Embeddings compute'

Parameters:
  BatchId:
    Type: String
  VllmModel:
    Type: String
    Default: "Qwen/Qwen2.5-14B-Instruct-AWQ"
  EmbeddingsModel:
    Type: String
    Default: "intfloat/multilingual-e5-large"
  SpotMaxPrice:
    Type: String
    Default: "0.80"
  VllmPort:
    Type: Number
    Default: 8000
  EmbeddingsPort:
    Type: Number
    Default: 8001
  VpcId:
    Type: String
    Default: ""
  SubnetId:
    Type: String
    Default: ""

Conditions:
  UseDefaultVpc: !Equals [!Ref VpcId, ""]

Resources:
  SecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: Burst compute instance
      VpcId: !If [UseDefaultVpc, !Ref "AWS::NoValue", !Ref VpcId]
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: !Ref VllmPort
          ToPort: !Ref VllmPort
          CidrIp: 0.0.0.0/0
        - IpProtocol: tcp
          FromPort: !Ref EmbeddingsPort
          ToPort: !Ref EmbeddingsPort
          CidrIp: 0.0.0.0/0
        - IpProtocol: tcp
          FromPort: 22
          ToPort: 22
          CidrIp: 0.0.0.0/0
      Tags:
        - Key: Name
          Value: !Sub "knowwhere-burst-${BatchId}"

  SpotFleetRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: spotfleet.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AmazonEC2SpotFleetTaggingRole

  InstanceRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: ec2.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess

  InstanceProfile:
    Type: AWS::IAM::InstanceProfile
    Properties:
      Roles:
        - !Ref InstanceRole

  SpotFleet:
    Type: AWS::EC2::SpotFleet
    Properties:
      SpotFleetRequestConfigData:
        IamFleetRole: !GetAtt SpotFleetRole.Arn
        TargetCapacity: 1
        AllocationStrategy: capacityOptimized
        Type: maintain
        TerminateInstancesWithExpiration: true
        SpotPrice: !Ref SpotMaxPrice
        LaunchSpecifications:
          - InstanceType: g5.xlarge
            ImageId: !Sub "{{resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64}}"
            SecurityGroups:
              - GroupId: !Ref SecurityGroup
            IamInstanceProfile:
              Arn: !GetAtt InstanceProfile.Arn
            UserData:
              Fn::Base64: !Sub |
                #!/bin/bash
                set -ex

                # Variables
                VLLM_MODEL="${VllmModel}"
                EMBEDDINGS_MODEL="${EmbeddingsModel}"
                VLLM_PORT="${VllmPort}"
                EMB_PORT="${EmbeddingsPort}"

                # Install Docker
                yum update -y
                yum install -y docker
                systemctl start docker
                systemctl enable docker

                # Install nvidia-docker
                yum install -y nvidia-driver-latest-dkms

                # AMI Golden : containers déjà configurés, attendre qu'ils soient prêts
                echo "AMI Golden - waiting for auto-started containers..."
                for i in $(seq 1 12); do
                  docker ps | grep -q vllm && docker ps | grep -q embeddings && break
                  sleep 5
                done
                docker ps

                echo "Bootstrap complete"

Outputs:
  SpotFleetId:
    Value: !Ref SpotFleet
  SecurityGroupId:
    Value: !Ref SecurityGroup
'''


# Instance globale de l'orchestrateur
_orchestrator_instance: Optional[BurstOrchestrator] = None


def get_burst_orchestrator() -> BurstOrchestrator:
    """Obtient l'instance singleton de l'orchestrateur."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = BurstOrchestrator()
    return _orchestrator_instance


def reset_burst_orchestrator():
    """Reset l'instance singleton (pour tests)."""
    global _orchestrator_instance
    _orchestrator_instance = None
