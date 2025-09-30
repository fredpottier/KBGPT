"""
Service Facts Gouvernées - Phase 3
Gestion du cycle de vie des faits avec validation humaine et détection de conflits
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from collections import defaultdict

from knowbase.common.graphiti.graphiti_store import GraphitiStore
from knowbase.common.graphiti.config import GraphitiConfig
from knowbase.common.interfaces.graph_store import FactStatus as StoreFactStatus
from knowbase.api.schemas.facts_governance import (
    FactCreate, FactResponse, FactUpdate, FactFilters,
    FactStatus, ConflictDetail, ConflictType,
    FactApprovalRequest, FactRejectionRequest,
    FactTimelineEntry, FactTimelineResponse,
    FactsListResponse, ConflictsListResponse, FactStats
)

logger = logging.getLogger(__name__)

# Groupe par défaut
CORPORATE_GROUP_ID = "corporate"


class FactsGovernanceService:
    """
    Service de gestion des faits gouvernés avec validation humaine

    Fonctionnalités:
    - Création de faits avec statut "proposed"
    - Détection automatique de conflits
    - Workflow d'approbation/rejet
    - Historique temporel complet
    - Multi-tenant via group_id
    """

    def __init__(self):
        """Initialise le service avec le store Graphiti"""
        config = GraphitiConfig.from_env()
        self.store = GraphitiStore(config=config)
        self._initialized = False
        self._current_group_id = CORPORATE_GROUP_ID

    async def _ensure_initialized(self):
        """Garantit l'initialisation du store"""
        if not self._initialized:
            await self.store.initialize()
            await self.store.set_group(self._current_group_id)
            self._initialized = True

    async def set_group(self, group_id: str):
        """Définit le groupe multi-tenant courant"""
        self._current_group_id = group_id
        await self._ensure_initialized()
        await self.store.set_group(group_id)

    async def create_fact(self, fact: FactCreate, created_by: Optional[str] = None) -> FactResponse:
        """
        Crée un nouveau fait avec statut "proposed"

        Args:
            fact: Données du fait à créer
            created_by: Identifiant de l'utilisateur créateur

        Returns:
            Fait créé avec statut "proposed"
        """
        await self._ensure_initialized()

        try:
            # Préparer les données du fait
            fact_data = {
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": fact.object,
                "confidence": fact.confidence,
                "source": fact.source,
                "tags": fact.tags,
                "metadata": fact.metadata,
                "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
                "valid_until": fact.valid_until.isoformat() if fact.valid_until else None,
                "created_by": created_by or "system",
                "created_at": datetime.utcnow().isoformat(),
                "version": 1
            }

            # Créer le fait avec statut "proposed"
            fact_id = await self.store.create_fact(
                fact=fact_data,
                status=StoreFactStatus.PROPOSED,
                group_id=self._current_group_id
            )

            # Construire la réponse
            return FactResponse(
                uuid=fact_id,
                subject=fact.subject,
                predicate=fact.predicate,
                object=fact.object,
                confidence=fact.confidence,
                source=fact.source,
                tags=fact.tags,
                metadata=fact.metadata,
                status=FactStatus.PROPOSED,
                created_at=datetime.utcnow(),
                created_by=created_by,
                valid_from=fact.valid_from,
                valid_until=fact.valid_until,
                version=1,
                group_id=self._current_group_id
            )

        except Exception as e:
            logger.error(f"Erreur création fait: {e}")
            raise

    async def approve_fact(self, fact_id: str, approval: FactApprovalRequest) -> FactResponse:
        """
        Approuve un fait proposé

        Args:
            fact_id: Identifiant du fait
            approval: Requête d'approbation

        Returns:
            Fait approuvé
        """
        await self._ensure_initialized()

        try:
            # Approuver via le store
            success = await self.store.approve_fact(fact_id, approval.approver_id)

            if not success:
                raise ValueError(f"Impossible d'approuver le fait {fact_id}")

            # Récupérer le fait mis à jour
            fact = await self.get_fact(fact_id)
            if not fact:
                raise ValueError(f"Fait {fact_id} introuvable après approbation")

            # Mettre à jour le statut
            fact.status = FactStatus.APPROVED
            fact.approved_by = approval.approver_id
            fact.approved_at = datetime.utcnow()

            logger.info(f"Fait {fact_id} approuvé par {approval.approver_id}")

            return fact

        except Exception as e:
            logger.error(f"Erreur approbation fait {fact_id}: {e}")
            raise

    async def reject_fact(self, fact_id: str, rejection: FactRejectionRequest) -> FactResponse:
        """
        Rejette un fait proposé

        Args:
            fact_id: Identifiant du fait
            rejection: Requête de rejet

        Returns:
            Fait rejeté
        """
        await self._ensure_initialized()

        try:
            # Note: Le store Graphiti n'a pas de méthode reject_fact native
            # On simule avec une mise à jour du statut via metadata

            # Créer un épisode de rejet
            await self.store.create_episode(
                group_id=self._current_group_id,
                content=f"Rejet du fait {fact_id}: {rejection.reason}",
                episode_type="rejection",
                metadata={
                    "action": "reject_fact",
                    "fact_id": fact_id,
                    "rejector_id": rejection.rejector_id,
                    "reason": rejection.reason,
                    "comment": rejection.comment,
                    "rejected_at": datetime.utcnow().isoformat()
                }
            )

            # Récupérer le fait et mettre à jour le statut
            fact = await self.get_fact(fact_id)
            if not fact:
                raise ValueError(f"Fait {fact_id} introuvable")

            fact.status = FactStatus.REJECTED
            fact.rejected_by = rejection.rejector_id
            fact.rejected_at = datetime.utcnow()
            fact.rejection_reason = rejection.reason

            logger.info(f"Fait {fact_id} rejeté par {rejection.rejector_id}: {rejection.reason}")

            return fact

        except Exception as e:
            logger.error(f"Erreur rejet fait {fact_id}: {e}")
            raise

    async def get_fact(self, fact_id: str) -> Optional[FactResponse]:
        """
        Récupère un fait par son ID

        Args:
            fact_id: Identifiant du fait

        Returns:
            Fait trouvé ou None
        """
        await self._ensure_initialized()

        try:
            # Rechercher le fait dans le store
            facts = await self.store.search_facts(fact_id, group_id=self._current_group_id)

            if not facts:
                return None

            # Prendre le premier résultat (devrait être unique)
            fact_data = facts[0]

            # Mapper vers FactResponse
            return self._map_fact_data_to_response(fact_data)

        except Exception as e:
            logger.error(f"Erreur récupération fait {fact_id}: {e}")
            return None

    async def list_facts(self, filters: FactFilters) -> FactsListResponse:
        """
        Liste les faits avec filtres

        Args:
            filters: Filtres de recherche

        Returns:
            Liste paginée de faits
        """
        await self._ensure_initialized()

        try:
            # Rechercher les faits dans le store
            query = filters.subject or filters.predicate or ""
            all_facts = await self.store.search_facts(query, group_id=self._current_group_id)

            # Appliquer les filtres
            filtered_facts = []
            for fact_data in all_facts:
                if filters.status and fact_data.get("status") != filters.status.value:
                    continue
                if filters.created_by and fact_data.get("created_by") != filters.created_by:
                    continue
                if filters.tags and not any(tag in fact_data.get("tags", []) for tag in filters.tags):
                    continue

                filtered_facts.append(self._map_fact_data_to_response(fact_data))

            # Pagination
            total = len(filtered_facts)
            start = filters.offset
            end = start + filters.limit
            paginated_facts = filtered_facts[start:end]
            has_more = end < total

            return FactsListResponse(
                facts=paginated_facts,
                total=total,
                limit=filters.limit,
                offset=filters.offset,
                has_more=has_more
            )

        except Exception as e:
            logger.error(f"Erreur listage faits: {e}")
            raise

    async def detect_conflicts(self, proposed_fact: FactCreate) -> List[ConflictDetail]:
        """
        Détecte les conflits pour un fait proposé

        Args:
            proposed_fact: Fait à vérifier

        Returns:
            Liste des conflits détectés
        """
        await self._ensure_initialized()

        try:
            # Utiliser la détection de conflits du store
            fact_data = {
                "subject": proposed_fact.subject,
                "predicate": proposed_fact.predicate,
                "object": proposed_fact.object
            }

            conflicts_raw = await self.store.detect_conflicts(fact_data)

            # Mapper vers ConflictDetail
            conflicts = []
            for conflict_raw in conflicts_raw:
                existing_fact_data = conflict_raw.get("existing_fact", {})
                existing_fact = self._map_fact_data_to_response(existing_fact_data)

                conflict_detail = ConflictDetail(
                    conflict_type=ConflictType.VALUE_MISMATCH,
                    existing_fact=existing_fact,
                    proposed_fact=proposed_fact,
                    description=f"Le fait existant a une valeur différente pour {proposed_fact.subject} {proposed_fact.predicate}",
                    severity="high",
                    resolution_suggestions=[
                        "Vérifier la source du fait existant",
                        "Créer une nouvelle version avec période de validité",
                        "Rejeter le fait proposé si obsolète"
                    ]
                )
                conflicts.append(conflict_detail)

            logger.info(f"Détection conflits: {len(conflicts)} conflits trouvés")

            return conflicts

        except Exception as e:
            logger.error(f"Erreur détection conflits: {e}")
            return []

    async def get_conflicts(self) -> ConflictsListResponse:
        """
        Liste tous les conflits actifs

        Returns:
            Liste des conflits non résolus
        """
        await self._ensure_initialized()

        try:
            # Récupérer tous les facts proposed/conflicted
            filters_proposed = FactFilters(status=FactStatus.PROPOSED, limit=1000)
            filters_conflicted = FactFilters(status=FactStatus.CONFLICTED, limit=1000)

            facts_proposed = await self.list_facts(filters_proposed)
            facts_conflicted = await self.list_facts(filters_conflicted)

            all_facts = facts_proposed.facts + facts_conflicted.facts

            # Détecter les conflits entre tous ces facts
            conflicts_detected = []
            for fact in all_facts[:100]:  # Limiter pour performance
                fact_create = FactCreate(
                    subject=fact.subject,
                    predicate=fact.predicate,
                    object=fact.object,
                    confidence=fact.confidence,
                    source=fact.source,
                    tags=fact.tags,
                    metadata=fact.metadata
                )
                conflicts = await self.detect_conflicts(fact_create)
                if conflicts:
                    conflicts_detected.extend(conflicts)

            # Dédupliquer par description
            unique_conflicts = []
            seen_descriptions = set()
            for conflict in conflicts_detected:
                if conflict.description not in seen_descriptions:
                    unique_conflicts.append(conflict)
                    seen_descriptions.add(conflict.description)

            # Calculer statistiques
            by_type = {}
            by_severity = {}
            for conflict in unique_conflicts:
                by_type[conflict.conflict_type.value] = by_type.get(conflict.conflict_type.value, 0) + 1
                by_severity[conflict.severity] = by_severity.get(conflict.severity, 0) + 1

            return ConflictsListResponse(
                conflicts=unique_conflicts[:50],  # Top 50
                total_conflicts=len(unique_conflicts),
                by_type=by_type,
                by_severity=by_severity
            )

        except Exception as e:
            logger.error(f"Erreur récupération conflits: {e}")
            raise

    async def get_timeline(self, entity_id: str) -> FactTimelineResponse:
        """
        Récupère l'historique temporel complet d'une entité

        Args:
            entity_id: Identifiant de l'entité

        Returns:
            Timeline avec toutes les versions
        """
        await self._ensure_initialized()

        try:
            # Requête temporelle via le store
            facts_data = await self.store.query_facts_temporal(entity_id)

            # Construire la timeline
            timeline = []
            for fact_data in facts_data:
                fact = self._map_fact_data_to_response(fact_data)

                entry = FactTimelineEntry(
                    fact=fact,
                    action="created",
                    performed_by=fact.created_by or "system",
                    performed_at=fact.created_at
                )
                timeline.append(entry)

            # Trier par date
            timeline.sort(key=lambda e: e.performed_at)

            current_version = timeline[-1].fact if timeline else None

            return FactTimelineResponse(
                entity_id=entity_id,
                timeline=timeline,
                total_versions=len(timeline),
                current_version=current_version
            )

        except Exception as e:
            logger.error(f"Erreur récupération timeline {entity_id}: {e}")
            raise

    async def get_stats(self) -> FactStats:
        """
        Calcule les statistiques sur les faits

        Returns:
            Statistiques complètes
        """
        await self._ensure_initialized()

        try:
            # Récupérer tous les faits
            all_facts = await self.store.search_facts("", group_id=self._current_group_id)

            # Calculer statistiques
            total_facts = len(all_facts)
            by_status = defaultdict(int)
            pending_approval = 0

            for fact_data in all_facts:
                status = fact_data.get("status", "proposed")
                by_status[status] += 1
                if status == "proposed":
                    pending_approval += 1

            # Compter les conflits (simplified - comptage conflicts_count simple)
            conflicts_count = by_status.get("conflicted", 0)

            # Calculer temps moyen d'approbation (approximation basée sur les données disponibles)
            approved_facts = [f for f in all_facts if f.get("status") == "approved" and f.get("approved_at") and f.get("created_at")]
            if approved_facts:
                approval_times = []
                for f in approved_facts:
                    try:
                        created = datetime.fromisoformat(f["created_at"].replace('Z', '+00:00'))
                        approved = datetime.fromisoformat(f["approved_at"].replace('Z', '+00:00'))
                        hours_diff = (approved - created).total_seconds() / 3600
                        approval_times.append(hours_diff)
                    except:
                        pass
                avg_approval_time = sum(approval_times) / len(approval_times) if approval_times else None
            else:
                avg_approval_time = None

            # Top contributeurs
            contributors = {}
            for f in all_facts:
                creator = f.get("created_by")
                if creator:
                    contributors[creator] = contributors.get(creator, 0) + 1

            top_contributors = [
                {"user_id": user, "count": count}
                for user, count in sorted(contributors.items(), key=lambda x: x[1], reverse=True)[:10]
            ]

            return FactStats(
                total_facts=total_facts,
                by_status=dict(by_status),
                pending_approval=pending_approval,
                conflicts_count=conflicts_count,
                avg_approval_time_hours=avg_approval_time,
                top_contributors=top_contributors,
                group_id=self._current_group_id
            )

        except Exception as e:
            logger.error(f"Erreur calcul statistiques: {e}")
            raise

    def _map_fact_data_to_response(self, fact_data: Dict[str, Any]) -> FactResponse:
        """
        Mappe les données brutes du store vers FactResponse

        Args:
            fact_data: Données brutes du fait

        Returns:
            FactResponse structuré
        """
        return FactResponse(
            uuid=fact_data.get("uuid", fact_data.get("id", "unknown")),
            subject=fact_data.get("subject", ""),
            predicate=fact_data.get("predicate", ""),
            object=fact_data.get("object", ""),
            confidence=fact_data.get("confidence", 0.8),
            source=fact_data.get("source"),
            tags=fact_data.get("tags", []),
            metadata=fact_data.get("metadata", {}),
            status=FactStatus(fact_data.get("status", "proposed")),
            created_at=datetime.fromisoformat(fact_data["created_at"]) if "created_at" in fact_data else datetime.utcnow(),
            created_by=fact_data.get("created_by"),
            approved_by=fact_data.get("approved_by"),
            approved_at=datetime.fromisoformat(fact_data["approved_at"]) if "approved_at" in fact_data else None,
            rejected_by=fact_data.get("rejected_by"),
            rejected_at=datetime.fromisoformat(fact_data["rejected_at"]) if "rejected_at" in fact_data else None,
            rejection_reason=fact_data.get("rejection_reason"),
            valid_from=datetime.fromisoformat(fact_data["valid_from"]) if "valid_from" in fact_data and fact_data["valid_from"] else None,
            valid_until=datetime.fromisoformat(fact_data["valid_until"]) if "valid_until" in fact_data and fact_data["valid_until"] else None,
            version=fact_data.get("version", 1),
            group_id=fact_data.get("group_id", self._current_group_id)
        )