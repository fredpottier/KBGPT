"""
Service Facts - Logique métier gestion Facts Neo4j

Fournit interface métier pour manipulation facts avec validation,
détection conflits, et gouvernance.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from knowbase.neo4j_custom import get_neo4j_client, FactsQueries
from knowbase.api.schemas.facts import (
    FactCreate, FactUpdate, FactResponse,
    ConflictResponse, FactsStats, FactTimelineEntry,
    ConflictType
)

logger = logging.getLogger(__name__)


class FactsServiceError(Exception):
    """Erreur service Facts."""
    pass


class FactNotFoundError(FactsServiceError):
    """Fact non trouvé."""
    pass


class FactValidationError(FactsServiceError):
    """Erreur validation fact."""
    pass


class FactsService:
    """
    Service métier pour gestion Facts Neo4j.

    Provides business logic for:
    - CRUD operations on facts
    - Validation métier renforcée
    - Conflict detection et resolution
    - Governance workflow (approve/reject)
    - Timeline et analytics
    """

    def __init__(self, tenant_id: str):
        """
        Initialise service Facts pour un tenant.

        Args:
            tenant_id: ID tenant (isolation multi-tenancy)
        """
        self.tenant_id = tenant_id
        self.client = get_neo4j_client()
        self.facts_queries = FactsQueries(self.client, tenant_id=tenant_id)

        logger.debug(f"FactsService initialized for tenant: {tenant_id}")

    # ===================================
    # CRUD METHODS
    # ===================================

    def create_fact(self, fact_data: FactCreate) -> FactResponse:
        """
        Crée nouveau fact dans Neo4j.

        Args:
            fact_data: Données fact à créer

        Returns:
            Fact créé avec UUID

        Raises:
            FactValidationError: Si validation métier échoue
            FactsServiceError: Si erreur création
        """
        try:
            # Validation métier supplémentaire
            self._validate_fact_data(fact_data)

            # Créer fact via FactsQueries
            fact_dict = self.facts_queries.create_fact(
                subject=fact_data.subject,
                predicate=fact_data.predicate,
                object_str=fact_data.object,
                value=fact_data.value,
                unit=fact_data.unit,
                value_type=fact_data.value_type.value,
                fact_type=fact_data.fact_type.value,
                status=fact_data.status.value,
                confidence=fact_data.confidence,
                valid_from=fact_data.valid_from,
                valid_until=fact_data.valid_until,
                source_chunk_id=fact_data.source_chunk_id,
                source_document=fact_data.source_document,
                extraction_method=fact_data.extraction_method,
                extraction_model=fact_data.extraction_model,
                extraction_prompt_id=fact_data.extraction_prompt_id,
            )

            logger.info(
                f"Fact created - UUID: {fact_dict['uuid']}, "
                f"Subject: {fact_data.subject}, "
                f"Predicate: {fact_data.predicate}"
            )

            return FactResponse(**fact_dict)

        except ValueError as e:
            logger.error(f"Fact validation failed: {e}")
            raise FactValidationError(str(e)) from e

        except Exception as e:
            logger.error(f"Failed to create fact: {e}")
            raise FactsServiceError(f"Create fact failed: {e}") from e

    def get_fact(self, fact_uuid: str) -> FactResponse:
        """
        Récupère fact par UUID.

        Args:
            fact_uuid: UUID fact

        Returns:
            Fact trouvé

        Raises:
            FactNotFoundError: Si fact non trouvé
        """
        try:
            fact_dict = self.facts_queries.get_fact_by_uuid(fact_uuid)

            if not fact_dict:
                raise FactNotFoundError(f"Fact not found: {fact_uuid}")

            return FactResponse(**fact_dict)

        except FactNotFoundError:
            raise

        except Exception as e:
            logger.error(f"Failed to get fact {fact_uuid}: {e}")
            raise FactsServiceError(f"Get fact failed: {e}") from e

    def list_facts(
        self,
        status: Optional[str] = None,
        fact_type: Optional[str] = None,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[FactResponse]:
        """
        Liste facts avec filtres et pagination.

        Args:
            status: Filtrer par statut (proposed, approved, etc.)
            fact_type: Filtrer par type (SERVICE_LEVEL, etc.)
            subject: Filtrer par subject (contient)
            predicate: Filtrer par predicate (exact)
            limit: Nombre max résultats
            offset: Offset pagination

        Returns:
            Liste facts

        Note:
            Pagination implémentée côté Neo4j (SKIP/LIMIT)
        """
        try:
            # Filtrage par statut
            if status:
                facts = self.facts_queries.get_facts_by_status(status, limit=limit)
            # Filtrage par subject+predicate
            elif subject and predicate:
                facts = self.facts_queries.get_facts_by_subject_predicate(
                    subject, predicate
                )
            # Liste complète
            else:
                # TODO: Implémenter list_all avec pagination dans FactsQueries
                facts = self.facts_queries.get_facts_by_status("approved", limit=limit)

            # Filtrage additionnel (fact_type, subject contains)
            # TODO: Implémenter filtres avancés dans Cypher pour performance

            return [FactResponse(**f) for f in facts]

        except Exception as e:
            logger.error(f"Failed to list facts: {e}")
            raise FactsServiceError(f"List facts failed: {e}") from e

    def update_fact(self, fact_uuid: str, fact_update: FactUpdate) -> FactResponse:
        """
        Met à jour fact (partiel).

        Args:
            fact_uuid: UUID fact
            fact_update: Champs à mettre à jour

        Returns:
            Fact mis à jour

        Raises:
            FactNotFoundError: Si fact non trouvé
        """
        try:
            # Vérifier fact existe
            self.get_fact(fact_uuid)

            # Mise à jour status si fourni
            if fact_update.status:
                updated_fact = self.facts_queries.update_fact_status(
                    fact_uuid,
                    status=fact_update.status.value,
                )

                if not updated_fact:
                    raise FactsServiceError("Update fact status failed")

                logger.info(
                    f"Fact status updated - UUID: {fact_uuid}, "
                    f"Status: {fact_update.status.value}"
                )

                return FactResponse(**updated_fact)

            # TODO: Implémenter update autres champs (confidence, valid_until)

            # Si aucun champ modifié, retourner fact inchangé
            return self.get_fact(fact_uuid)

        except FactNotFoundError:
            raise

        except Exception as e:
            logger.error(f"Failed to update fact {fact_uuid}: {e}")
            raise FactsServiceError(f"Update fact failed: {e}") from e

    def delete_fact(self, fact_uuid: str) -> bool:
        """
        Supprime fact.

        Args:
            fact_uuid: UUID fact

        Returns:
            True si supprimé

        Raises:
            FactNotFoundError: Si fact non trouvé
        """
        try:
            # Vérifier fact existe
            self.get_fact(fact_uuid)

            # Supprimer
            deleted = self.facts_queries.delete_fact(fact_uuid)

            if not deleted:
                raise FactsServiceError("Delete fact failed")

            logger.info(f"Fact deleted - UUID: {fact_uuid}")

            return True

        except FactNotFoundError:
            raise

        except Exception as e:
            logger.error(f"Failed to delete fact {fact_uuid}: {e}")
            raise FactsServiceError(f"Delete fact failed: {e}") from e

    # ===================================
    # GOVERNANCE METHODS
    # ===================================

    def approve_fact(
        self,
        fact_uuid: str,
        approved_by: str,
        comment: Optional[str] = None
    ) -> FactResponse:
        """
        Approuve fact proposé (workflow gouvernance).

        Args:
            fact_uuid: UUID fact à approuver
            approved_by: User ID approbateur
            comment: Commentaire approbation (optionnel)

        Returns:
            Fact approuvé

        Raises:
            FactNotFoundError: Si fact non trouvé
            FactValidationError: Si fact déjà approuvé ou status invalide
        """
        try:
            # Vérifier fact existe et status=proposed
            fact = self.get_fact(fact_uuid)

            if fact.status != "proposed":
                raise FactValidationError(
                    f"Cannot approve fact with status '{fact.status}' "
                    f"(must be 'proposed')"
                )

            # Approuver
            approved_fact = self.facts_queries.update_fact_status(
                fact_uuid,
                status="approved",
                approved_by=approved_by
            )

            if not approved_fact:
                raise FactsServiceError("Approve fact failed")

            logger.info(
                f"Fact approved - UUID: {fact_uuid}, "
                f"By: {approved_by}, "
                f"Comment: {comment}"
            )

            return FactResponse(**approved_fact)

        except (FactNotFoundError, FactValidationError):
            raise

        except Exception as e:
            logger.error(f"Failed to approve fact {fact_uuid}: {e}")
            raise FactsServiceError(f"Approve fact failed: {e}") from e

    def reject_fact(
        self,
        fact_uuid: str,
        rejected_by: str,
        reason: str,
        comment: Optional[str] = None
    ) -> FactResponse:
        """
        Rejette fact proposé (workflow gouvernance).

        Args:
            fact_uuid: UUID fact à rejeter
            rejected_by: User ID rejet
            reason: Raison rejet (requis)
            comment: Commentaire additionnel (optionnel)

        Returns:
            Fact rejeté

        Raises:
            FactNotFoundError: Si fact non trouvé
            FactValidationError: Si fact déjà approuvé ou status invalide
        """
        try:
            # Vérifier fact existe et status=proposed
            fact = self.get_fact(fact_uuid)

            if fact.status not in ["proposed", "conflicted"]:
                raise FactValidationError(
                    f"Cannot reject fact with status '{fact.status}' "
                    f"(must be 'proposed' or 'conflicted')"
                )

            # Rejeter (status=rejected, pas d'approved_by)
            rejected_fact = self.facts_queries.update_fact_status(
                fact_uuid,
                status="rejected",
                approved_by=None  # Pas d'approbateur pour rejet
            )

            if not rejected_fact:
                raise FactsServiceError("Reject fact failed")

            logger.info(
                f"Fact rejected - UUID: {fact_uuid}, "
                f"By: {rejected_by}, "
                f"Reason: {reason}, "
                f"Comment: {comment}"
            )

            return FactResponse(**rejected_fact)

        except (FactNotFoundError, FactValidationError):
            raise

        except Exception as e:
            logger.error(f"Failed to reject fact {fact_uuid}: {e}")
            raise FactsServiceError(f"Reject fact failed: {e}") from e

    # ===================================
    # CONFLICT DETECTION
    # ===================================

    def detect_conflicts(self) -> List[ConflictResponse]:
        """
        Détecte conflits entre facts approved et proposed.

        Returns:
            Liste conflits avec détails

        Note:
            Conflict types:
            - CONTRADICTS: Same valid_from, different values
            - OVERRIDES: Newer valid_from, different value
            - OUTDATED: Older valid_from, different value
        """
        try:
            conflicts_raw = self.facts_queries.detect_conflicts()

            conflicts = []
            for c in conflicts_raw:
                conflicts.append(ConflictResponse(
                    conflict_type=ConflictType(c["conflict_type"]),
                    value_diff_pct=c["value_diff_pct"],
                    fact_approved=FactResponse(**c["fact_approved"]),
                    fact_proposed=FactResponse(**c["fact_proposed"])
                ))

            logger.info(f"Conflicts detected: {len(conflicts)}")

            return conflicts

        except Exception as e:
            logger.error(f"Failed to detect conflicts: {e}")
            raise FactsServiceError(f"Detect conflicts failed: {e}") from e

    def detect_duplicates(self) -> List[ConflictResponse]:
        """
        Détecte duplicates (même valeur, sources différentes).

        Returns:
            Liste duplicates
        """
        try:
            duplicates_raw = self.facts_queries.detect_duplicates()

            duplicates = []
            for d in duplicates_raw:
                duplicates.append(ConflictResponse(
                    conflict_type=ConflictType.DUPLICATE,
                    value_diff_pct=0.0,  # Same value
                    fact_approved=FactResponse(**d["fact_approved"]),
                    fact_proposed=FactResponse(**d["fact_proposed"])
                ))

            logger.info(f"Duplicates detected: {len(duplicates)}")

            return duplicates

        except Exception as e:
            logger.error(f"Failed to detect duplicates: {e}")
            raise FactsServiceError(f"Detect duplicates failed: {e}") from e

    # ===================================
    # TIMELINE & ANALYTICS
    # ===================================

    def get_timeline(self, subject: str, predicate: str) -> List[FactTimelineEntry]:
        """
        Timeline complète d'un fact (historique valeurs).

        Args:
            subject: Sujet fact
            predicate: Prédicat fact

        Returns:
            Liste entrées timeline (tri DESC par valid_from)
        """
        try:
            timeline_raw = self.facts_queries.get_fact_timeline(subject, predicate)

            timeline = [FactTimelineEntry(**entry) for entry in timeline_raw]

            logger.info(
                f"Timeline retrieved - Subject: {subject}, "
                f"Predicate: {predicate}, "
                f"Entries: {len(timeline)}"
            )

            return timeline

        except Exception as e:
            logger.error(f"Failed to get timeline: {e}")
            raise FactsServiceError(f"Get timeline failed: {e}") from e

    def get_fact_at_date(
        self,
        subject: str,
        predicate: str,
        target_date: str
    ) -> Optional[FactResponse]:
        """
        Point-in-time query : fact valide à une date donnée.

        Args:
            subject: Sujet fact
            predicate: Prédicat fact
            target_date: Date cible (ISO format)

        Returns:
            Fact valide à cette date ou None
        """
        try:
            fact_dict = self.facts_queries.get_fact_at_date(
                subject, predicate, target_date
            )

            if fact_dict:
                return FactResponse(**fact_dict)

            return None

        except Exception as e:
            logger.error(f"Failed to get fact at date: {e}")
            raise FactsServiceError(f"Get fact at date failed: {e}") from e

    def get_stats(self) -> FactsStats:
        """
        Statistiques facts (par statut, type, conflits).

        Returns:
            Stats agrégées
        """
        try:
            by_status = self.facts_queries.count_facts_by_status()
            by_type = self.facts_queries.count_facts_by_type()
            conflicts_count = self.facts_queries.get_conflicts_count()

            total_facts = sum(by_status.values())

            # TODO: Implémenter latest_fact_created_at dans FactsQueries

            stats = FactsStats(
                total_facts=total_facts,
                by_status=by_status,
                by_type=by_type,
                conflicts_count=conflicts_count,
                latest_fact_created_at=None  # TODO
            )

            logger.info(f"Stats retrieved - Total facts: {total_facts}")

            return stats

        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            raise FactsServiceError(f"Get stats failed: {e}") from e

    # ===================================
    # VALIDATION HELPERS
    # ===================================

    def _validate_fact_data(self, fact_data: FactCreate) -> None:
        """
        Validation métier supplémentaire (au-delà de Pydantic).

        Args:
            fact_data: Données fact à valider

        Raises:
            FactValidationError: Si validation échoue
        """
        # Validation longueur subject/predicate
        if len(fact_data.subject) < 3:
            raise FactValidationError(
                "subject must be at least 3 characters"
            )

        if len(fact_data.predicate) < 2:
            raise FactValidationError(
                "predicate must be at least 2 characters"
            )

        # Validation value_type vs value
        if fact_data.value_type == "numeric":
            if not isinstance(fact_data.value, (int, float)):
                raise FactValidationError(
                    "value must be numeric for value_type='numeric'"
                )

        # Validation confidence (0.0-1.0) - déjà fait par Pydantic
        # Mais double check par sécurité
        if not 0.0 <= fact_data.confidence <= 1.0:
            raise FactValidationError(
                "confidence must be between 0.0 and 1.0"
            )

        # Validation dates (valid_from < valid_until)
        if fact_data.valid_from and fact_data.valid_until:
            try:
                date_from = datetime.fromisoformat(fact_data.valid_from)
                date_until = datetime.fromisoformat(fact_data.valid_until)

                if date_from >= date_until:
                    raise FactValidationError(
                        "valid_from must be before valid_until"
                    )
            except ValueError as e:
                raise FactValidationError(f"Invalid date format: {e}")

        # Validation source_document (pas de path traversal)
        if fact_data.source_document:
            if ".." in fact_data.source_document or "/" in fact_data.source_document:
                raise FactValidationError(
                    "source_document contains invalid characters (path traversal)"
                )

        logger.debug("Fact data validation passed")
