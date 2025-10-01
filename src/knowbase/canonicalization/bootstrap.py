"""
Service de bootstrap automatique Knowledge Graph
Auto-promotion d'entités candidates fréquentes en entités seed canoniques
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict

from knowbase.canonicalization.schemas import (
    EntityCandidate,
    EntityCandidateStatus,
    BootstrapConfig,
    BootstrapResult,
    BootstrapProgress
)
from knowbase.common.redis_lock import create_lock

logger = logging.getLogger(__name__)


class KGBootstrapService:
    """
    Service de bootstrap automatique du Knowledge Graph

    Promeut automatiquement les entités candidates fréquentes (≥min_occurrences)
    et confiantes (≥min_confidence) en entités seed canoniques.
    """

    def __init__(self):
        """Initialise le service bootstrap"""
        # Lazy import pour éviter import circulaire
        from knowbase.api.services.knowledge_graph import KnowledgeGraphService
        self.kg_service = KnowledgeGraphService()
        self._progress: Optional[BootstrapProgress] = None

    async def get_candidates(
        self,
        group_id: Optional[str] = None,
        entity_types: Optional[List[str]] = None,
        status: EntityCandidateStatus = EntityCandidateStatus.CANDIDATE
    ) -> List[EntityCandidate]:
        """
        Récupère les entités candidates depuis le KG

        Args:
            group_id: Filtrer par groupe (None = tous)
            entity_types: Filtrer par types d'entités
            status: Filtrer par statut

        Returns:
            Liste d'entités candidates

        Note:
            PHASE 3 TODO: Actuellement retourne liste vide car extraction auto
            n'est pas encore implémentée. Cette méthode sera remplacée par
            une vraie requête vers le système d'extraction quand Phase 3 sera faite.
        """
        # TODO PHASE 3: Remplacer par vraie requête vers système extraction
        # Pour l'instant, retourne liste vide car extraction non implémentée
        logger.warning(
            "get_candidates() retourne liste vide - "
            "Phase 3 (Extraction Auto Entités) non encore implémentée"
        )
        return []

    async def auto_bootstrap_from_candidates(
        self,
        config: BootstrapConfig
    ) -> BootstrapResult:
        """
        Bootstrap automatique: promeut candidates fréquentes en seeds

        Logique:
            - Récupère toutes les candidates avec status=CANDIDATE
            - Filtre selon min_occurrences et min_confidence
            - Promeut les entités qualifiées en status=SEED
            - Crée les entités canoniques correspondantes dans le KG

        P0.2 PROTECTION: Lock distribué Redis prévient double bootstrap concurrent

        Args:
            config: Configuration bootstrap (seuils, filtres, dry_run)

        Returns:
            Résultat du bootstrap avec statistiques

        Raises:
            ValueError: Si configuration invalide
            RuntimeError: Si erreur durant le bootstrap
            TimeoutError: Si lock non acquis (bootstrap déjà en cours ailleurs)
        """
        start_time = datetime.utcnow()

        logger.info(
            f"Démarrage bootstrap: min_occ={config.min_occurrences}, "
            f"min_conf={config.min_confidence}, dry_run={config.dry_run}"
        )

        # P0.2: Acquérir lock distribué pour éviter bootstrap concurrent
        # TTL 10min (bootstrap peut prendre plusieurs minutes si 10k+ candidates)
        lock = create_lock(
            redis_url="redis://redis:6379/5",
            lock_key="bootstrap:global",
            ttl_seconds=600  # 10min
        )

        # Initialiser la progression
        self._progress = BootstrapProgress(
            status="running",
            processed=0,
            total=0,
            promoted=0,
            started_at=start_time
        )

        # Utiliser context manager pour auto-release même si exception
        with lock.context(timeout=30):
            logger.info("🔒 Lock bootstrap acquis - début traitement")

            try:
                # 1. Récupérer les candidates
                candidates = await self.get_candidates(
                    group_id=config.group_id,
                    entity_types=config.entity_types,
                    status=EntityCandidateStatus.CANDIDATE
                )

                self._progress.total = len(candidates)
                logger.info(f"Candidates récupérées: {len(candidates)}")

                # 2. Filtrer les candidates qualifiées
                qualified = [
                    c for c in candidates
                    if c.occurrences >= config.min_occurrences
                    and c.confidence >= config.min_confidence
                ]

                logger.info(
                    f"Candidates qualifiées pour promotion: {len(qualified)} "
                    f"(sur {len(candidates)} analysées)"
                )

                # 3. Promouvoir les candidates en seeds
                promoted_ids = []
                by_type: Dict[str, int] = defaultdict(int)

                for idx, candidate in enumerate(qualified):
                    self._progress.processed = idx + 1
                    self._progress.current_entity = candidate.name

                    try:
                        if not config.dry_run:
                            # Créer l'entité canonique dans le KG
                            seed_id = await self._promote_to_seed(candidate)
                            promoted_ids.append(seed_id)
                            by_type[candidate.entity_type] += 1
                            self._progress.promoted += 1

                            logger.info(
                                f"Seed promue: {candidate.name} ({candidate.entity_type}) "
                                f"[occ={candidate.occurrences}, conf={candidate.confidence:.2f}]"
                            )
                        else:
                            # Mode dry-run: simuler seulement
                            promoted_ids.append(f"dry_run_{candidate.name}")
                            by_type[candidate.entity_type] += 1
                            self._progress.promoted += 1

                            logger.info(
                                f"[DRY RUN] Seed promue: {candidate.name} ({candidate.entity_type})"
                            )

                    except Exception as e:
                        logger.error(
                            f"Erreur promotion candidate {candidate.name}: {e}",
                            exc_info=True
                        )
                        # Continue avec les autres candidates

                # 4. Finaliser
                duration = (datetime.utcnow() - start_time).total_seconds()

                self._progress.status = "completed"

                result = BootstrapResult(
                    total_candidates=len(candidates),
                    promoted_seeds=len(promoted_ids),
                    seed_ids=promoted_ids,
                    duration_seconds=duration,
                    dry_run=config.dry_run,
                    by_entity_type=dict(by_type)
                )

                logger.info(
                    f"✅ Bootstrap terminé: {len(promoted_ids)} seeds promues "
                    f"en {duration:.2f}s (dry_run={config.dry_run})"
                )
                logger.info("🔓 Lock bootstrap libéré automatiquement")

                return result

            except Exception as e:
                self._progress.status = "failed"
                logger.error(f"Erreur durant bootstrap: {e}", exc_info=True)
                logger.info("🔓 Lock bootstrap libéré automatiquement (après erreur)")
                raise RuntimeError(f"Bootstrap échoué: {e}") from e

    async def _promote_to_seed(self, candidate: EntityCandidate) -> str:
        """
        Promeut une candidate en seed canonique dans le KG

        Args:
            candidate: Entité candidate à promouvoir

        Returns:
            ID de l'entité seed créée

        Raises:
            ValueError: Si type d'entité invalide
            RuntimeError: Si erreur création entité
        """
        # Lazy imports pour éviter import circulaire
        from knowbase.api.schemas.knowledge_graph import EntityCreate, EntityType

        # Mapper le type string vers EntityType enum
        try:
            entity_type_enum = EntityType(candidate.entity_type.lower())
        except ValueError:
            # Fallback vers CONCEPT si type inconnu
            logger.warning(
                f"Type d'entité inconnu '{candidate.entity_type}', "
                f"fallback vers CONCEPT"
            )
            entity_type_enum = EntityType.CONCEPT

        # Créer l'entité dans le KG avec attributs bootstrap
        entity_create = EntityCreate(
            name=candidate.name,
            entity_type=entity_type_enum,
            description=candidate.description or f"Entité seed auto-promue (bootstrap)",
            attributes={
                **candidate.attributes,
                "bootstrap": True,
                "bootstrap_confidence": candidate.confidence,
                "bootstrap_occurrences": candidate.occurrences,
                "bootstrap_date": datetime.utcnow().isoformat(),
                "source_chunks": candidate.source_chunks
            }
        )

        # Créer l'entité via le KG service
        entity_response = await self.kg_service.create_entity(entity_create)

        # TODO PHASE 3: Marquer la candidate comme SEED dans le système d'extraction
        # Pour l'instant, juste logger
        logger.debug(
            f"Candidate {candidate.name} promue en seed avec ID {entity_response.uuid}"
        )

        return entity_response.uuid

    def get_progress(self) -> Optional[BootstrapProgress]:
        """
        Récupère la progression du bootstrap en cours

        Returns:
            Progression actuelle ou None si aucun bootstrap en cours
        """
        return self._progress

    async def estimate_bootstrap(self, config: BootstrapConfig) -> Dict[str, Any]:
        """
        Estime le nombre d'entités qui seraient promues (sans modifier)

        Args:
            config: Configuration bootstrap (avec dry_run=True)

        Returns:
            Dict avec estimation {
                "qualified_candidates": int,
                "by_entity_type": Dict[str, int],
                "estimated_duration_seconds": float
            }
        """
        # Forcer dry_run pour estimation
        config_dict = config.model_dump()
        config_dict["dry_run"] = True
        config_estimate = BootstrapConfig(**config_dict)

        result = await self.auto_bootstrap_from_candidates(config_estimate)

        return {
            "qualified_candidates": result.promoted_seeds,
            "by_entity_type": result.by_entity_type,
            "estimated_duration_seconds": result.duration_seconds
        }
