"""
🌊 OSMOSE Phase 2.3 - Living Ontology Manager

Gestionnaire du cycle de vie de l'ontologie dynamique.

Responsabilités:
1. Gestion des types découverts (pending → approved/rejected)
2. Promotion automatique basée sur confidence
3. Historique et versioning des changements
4. Synchronisation avec EntityTypeRegistry (SQLite)
5. Mise à jour du KG (Neo4j) avec nouveaux types

Workflow:
1. PatternDiscoveryService découvre patterns
2. LivingOntologyManager évalue et propose
3. Auto-promotion si confidence >= AUTO_PROMOTE_THRESHOLD
4. Sinon → pending pour review humain
5. Types approuvés → mise à jour KG + registry
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings
from knowbase.semantic.ontology.pattern_discovery import (
    DiscoveredPattern,
    PatternType,
    get_pattern_discovery_service,
)

settings = get_settings()
logger = setup_logging(settings.logs_dir, "living_ontology.log")


class ChangeType(str, Enum):
    """Types de changements ontologiques."""
    TYPE_ADDED = "type_added"             # Nouveau type ajouté
    TYPE_APPROVED = "type_approved"       # Type pending → approved
    TYPE_REJECTED = "type_rejected"       # Type pending → rejected
    TYPE_DEPRECATED = "type_deprecated"   # Type déprécié
    TYPE_MERGED = "type_merged"           # Deux types fusionnés
    HIERARCHY_UPDATED = "hierarchy_updated"  # Hiérarchie modifiée


@dataclass
class OntologyChange:
    """Enregistrement d'un changement ontologique."""
    change_id: str = field(default_factory=lambda: f"change_{uuid4().hex[:12]}")
    change_type: ChangeType = ChangeType.TYPE_ADDED

    # Détails
    type_name: str = ""
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Source
    source: str = "system"                # system | admin | auto_promote
    source_pattern_id: Optional[str] = None

    # Audit
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    tenant_id: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "change_id": self.change_id,
            "change_type": self.change_type.value,
            "type_name": self.type_name,
            "description": self.description,
            "metadata": self.metadata,
            "source": self.source,
            "source_pattern_id": self.source_pattern_id,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "tenant_id": self.tenant_id,
        }


@dataclass
class TypeProposal:
    """Proposition de nouveau type pour review."""
    proposal_id: str = field(default_factory=lambda: f"prop_{uuid4().hex[:12]}")

    # Type proposé
    type_name: str = ""
    description: str = ""
    parent_type: Optional[str] = None

    # Métriques
    confidence: float = 0.0
    occurrences: int = 0
    support_concepts: List[str] = field(default_factory=list)

    # Status
    status: str = "pending"               # pending | approved | rejected | auto_promoted
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    # Source
    source_pattern: Optional[DiscoveredPattern] = None

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    tenant_id: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "proposal_id": self.proposal_id,
            "type_name": self.type_name,
            "description": self.description,
            "parent_type": self.parent_type,
            "confidence": self.confidence,
            "occurrences": self.occurrences,
            "support_concepts": self.support_concepts[:5],
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat(),
            "tenant_id": self.tenant_id,
        }


class LivingOntologyManager:
    """
    Gestionnaire de l'ontologie vivante.

    Coordonne la découverte, validation et promotion des types.
    """

    # Seuils de promotion automatique
    AUTO_PROMOTE_THRESHOLD = 0.85         # Confidence >= 85% → auto-promote
    HIGH_CONFIDENCE_THRESHOLD = 0.7       # Confidence >= 70% → suggest strongly
    MIN_CONFIDENCE_THRESHOLD = 0.5        # Confidence < 50% → reject

    def __init__(self):
        self._neo4j_client = None
        self._pattern_service = None
        self._proposals: Dict[str, TypeProposal] = {}
        self._change_history: List[OntologyChange] = []

    @property
    def neo4j_client(self):
        """Lazy loading du client Neo4j."""
        if self._neo4j_client is None:
            from knowbase.neo4j_custom.client import get_neo4j_client
            self._neo4j_client = get_neo4j_client()
        return self._neo4j_client

    @property
    def pattern_service(self):
        """Lazy loading du PatternDiscoveryService."""
        if self._pattern_service is None:
            self._pattern_service = get_pattern_discovery_service()
        return self._pattern_service

    async def run_discovery_cycle(
        self,
        tenant_id: str = "default",
        auto_promote: bool = True
    ) -> Dict[str, Any]:
        """
        Exécute un cycle complet de découverte et proposition.

        1. Découvre patterns via PatternDiscoveryService
        2. Filtre patterns déjà connus
        3. Crée propositions pour nouveaux types
        4. Auto-promeut si confidence suffisante
        5. Retourne résumé

        Args:
            tenant_id: Tenant ID
            auto_promote: Si True, promeut automatiquement les high-confidence

        Returns:
            Résumé du cycle (patterns découverts, propositions, promotions)
        """
        logger.info(f"[OSMOSE] Starting discovery cycle for tenant {tenant_id}")

        # 1. Découvrir patterns
        discovery_results = await self.pattern_service.run_full_discovery(tenant_id)

        # 2. Créer propositions
        proposals_created = []
        auto_promoted = []
        rejected = []

        all_patterns = (
            discovery_results.get("new_entity_types", []) +
            discovery_results.get("type_refinements", [])
        )

        for pattern in all_patterns:
            # Vérifier si type déjà existant
            if await self._type_exists(pattern.suggested_name, tenant_id):
                logger.debug(f"[OSMOSE] Type already exists: {pattern.suggested_name}")
                continue

            # Créer proposition
            proposal = TypeProposal(
                type_name=pattern.suggested_name,
                description=pattern.description,
                parent_type=pattern.parent_type,
                confidence=pattern.confidence,
                occurrences=pattern.occurrences,
                support_concepts=pattern.support_concepts,
                source_pattern=pattern,
                tenant_id=tenant_id,
            )

            # Décider du status
            if pattern.confidence < self.MIN_CONFIDENCE_THRESHOLD:
                proposal.status = "rejected"
                proposal.rejection_reason = f"Confidence too low: {pattern.confidence:.2f}"
                rejected.append(proposal)
            elif auto_promote and pattern.confidence >= self.AUTO_PROMOTE_THRESHOLD:
                proposal.status = "auto_promoted"
                auto_promoted.append(proposal)
                await self._promote_type(proposal)
            else:
                proposal.status = "pending"
                proposals_created.append(proposal)

            self._proposals[proposal.proposal_id] = proposal

        # 3. Loguer résultats
        summary = {
            "tenant_id": tenant_id,
            "patterns_discovered": len(all_patterns),
            "proposals_created": len(proposals_created),
            "auto_promoted": len(auto_promoted),
            "rejected": len(rejected),
            "pending_review": [p.to_dict() for p in proposals_created],
            "promoted_types": [p.type_name for p in auto_promoted],
        }

        logger.info(
            f"[OSMOSE] Discovery cycle complete: "
            f"{len(all_patterns)} patterns, "
            f"{len(proposals_created)} pending, "
            f"{len(auto_promoted)} auto-promoted"
        )

        return summary

    async def _type_exists(self, type_name: str, tenant_id: str) -> bool:
        """Vérifie si un type existe déjà."""
        # Vérifier dans Neo4j
        cypher = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WHERE toUpper(c.type) = $type_name OR toUpper(c.concept_type) = $type_name
        RETURN count(c) > 0 AS exists
        """
        try:
            results = self.neo4j_client.execute_query(cypher, {
                "tenant_id": tenant_id,
                "type_name": type_name.upper()
            })
            if results and results[0].get("exists"):
                return True
        except Exception:
            pass

        # Vérifier dans proposals existantes
        for proposal in self._proposals.values():
            if proposal.type_name.upper() == type_name.upper() and proposal.tenant_id == tenant_id:
                return True

        return False

    async def _promote_type(self, proposal: TypeProposal) -> OntologyChange:
        """
        Promeut un type dans l'ontologie.

        1. Ajoute au EntityTypeRegistry (SQLite)
        2. Met à jour les concepts concernés dans Neo4j
        3. Enregistre le changement
        """
        logger.info(f"[OSMOSE] Promoting type: {proposal.type_name}")

        # 1. Ajouter au registry SQLite
        try:
            from knowbase.db.session import get_db
            from knowbase.api.services.entity_type_registry_service import EntityTypeRegistryService

            db = next(get_db())
            registry_service = EntityTypeRegistryService(db)

            # Créer type avec status approved
            registry_service.get_or_create_type(
                type_name=proposal.type_name,
                tenant_id=proposal.tenant_id,
                discovered_by="system"
            )

            # Approuver immédiatement
            registry_service.approve_type(
                type_name=proposal.type_name,
                admin_email="system@osmose.ai",
                tenant_id=proposal.tenant_id
            )

        except Exception as e:
            logger.error(f"[OSMOSE] Erreur ajout registry: {e}")

        # 2. Mettre à jour concepts dans Neo4j (optionnel - reclassification)
        if proposal.support_concepts:
            await self._reclassify_concepts(
                proposal.type_name,
                proposal.support_concepts,
                proposal.tenant_id
            )

        # 3. Enregistrer changement
        change = OntologyChange(
            change_type=ChangeType.TYPE_ADDED if proposal.status == "auto_promoted" else ChangeType.TYPE_APPROVED,
            type_name=proposal.type_name,
            description=f"Type '{proposal.type_name}' promoted from pattern discovery",
            metadata={
                "confidence": proposal.confidence,
                "occurrences": proposal.occurrences,
                "parent_type": proposal.parent_type,
            },
            source="auto_promote" if proposal.status == "auto_promoted" else "admin",
            source_pattern_id=proposal.source_pattern.pattern_id if proposal.source_pattern else None,
            tenant_id=proposal.tenant_id,
        )

        self._change_history.append(change)

        return change

    async def _reclassify_concepts(
        self,
        new_type: str,
        concept_names: List[str],
        tenant_id: str
    ) -> int:
        """
        Reclassifie les concepts avec le nouveau type.

        Args:
            new_type: Nouveau type à assigner
            concept_names: Noms des concepts à reclassifier
            tenant_id: Tenant ID

        Returns:
            Nombre de concepts reclassifiés
        """
        if not concept_names:
            return 0

        cypher = """
        UNWIND $names AS name
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WHERE c.canonical_name = name
        SET c.type = $new_type,
            c.concept_type = $new_type,
            c.reclassified_at = datetime(),
            c.reclassified_from = COALESCE(c.type, c.concept_type, 'entity')
        RETURN count(c) AS updated
        """

        try:
            results = self.neo4j_client.execute_query(cypher, {
                "names": concept_names[:50],  # Limiter
                "tenant_id": tenant_id,
                "new_type": new_type.lower()
            })
            updated = results[0].get("updated", 0) if results else 0
            logger.info(f"[OSMOSE] Reclassified {updated} concepts to type '{new_type}'")
            return updated
        except Exception as e:
            logger.error(f"[OSMOSE] Erreur reclassification: {e}")
            return 0

    async def approve_proposal(
        self,
        proposal_id: str,
        admin_email: str
    ) -> Optional[OntologyChange]:
        """
        Approuve manuellement une proposition.

        Args:
            proposal_id: ID de la proposition
            admin_email: Email de l'admin

        Returns:
            OntologyChange ou None si erreur
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            logger.warning(f"[OSMOSE] Proposal not found: {proposal_id}")
            return None

        if proposal.status != "pending":
            logger.warning(f"[OSMOSE] Proposal not pending: {proposal.status}")
            return None

        proposal.status = "approved"
        proposal.reviewed_by = admin_email
        proposal.reviewed_at = datetime.utcnow()

        change = await self._promote_type(proposal)
        change.created_by = admin_email
        change.source = "admin"

        return change

    async def reject_proposal(
        self,
        proposal_id: str,
        admin_email: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Rejette manuellement une proposition.

        Args:
            proposal_id: ID de la proposition
            admin_email: Email de l'admin
            reason: Raison du rejet

        Returns:
            True si rejeté, False si erreur
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            logger.warning(f"[OSMOSE] Proposal not found: {proposal_id}")
            return False

        if proposal.status != "pending":
            logger.warning(f"[OSMOSE] Proposal not pending: {proposal.status}")
            return False

        proposal.status = "rejected"
        proposal.reviewed_by = admin_email
        proposal.reviewed_at = datetime.utcnow()
        proposal.rejection_reason = reason

        # Enregistrer changement
        change = OntologyChange(
            change_type=ChangeType.TYPE_REJECTED,
            type_name=proposal.type_name,
            description=f"Type '{proposal.type_name}' rejected: {reason or 'No reason provided'}",
            source="admin",
            created_by=admin_email,
            tenant_id=proposal.tenant_id,
        )
        self._change_history.append(change)

        logger.info(f"[OSMOSE] Proposal rejected: {proposal.type_name} by {admin_email}")

        return True

    def list_pending_proposals(
        self,
        tenant_id: str = "default"
    ) -> List[TypeProposal]:
        """Liste les propositions en attente de review."""
        return [
            p for p in self._proposals.values()
            if p.status == "pending" and p.tenant_id == tenant_id
        ]

    def list_change_history(
        self,
        tenant_id: str = "default",
        limit: int = 50
    ) -> List[OntologyChange]:
        """Liste l'historique des changements."""
        changes = [
            c for c in self._change_history
            if c.tenant_id == tenant_id
        ]
        changes.sort(key=lambda c: c.created_at, reverse=True)
        return changes[:limit]

    async def get_ontology_stats(
        self,
        tenant_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Retourne statistiques de l'ontologie.

        Returns:
            Dictionnaire avec stats (types, concepts, proposals, etc.)
        """
        # Stats Neo4j
        cypher = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WITH
            COALESCE(c.type, c.concept_type, 'entity') AS type,
            count(c) AS count
        RETURN type, count
        ORDER BY count DESC
        """

        type_distribution = {}
        total_concepts = 0

        try:
            results = self.neo4j_client.execute_query(cypher, {"tenant_id": tenant_id})
            for r in results:
                type_distribution[r["type"]] = r["count"]
                total_concepts += r["count"]
        except Exception as e:
            logger.error(f"[OSMOSE] Erreur stats: {e}")

        return {
            "tenant_id": tenant_id,
            "total_concepts": total_concepts,
            "type_distribution": type_distribution,
            "unique_types": len(type_distribution),
            "pending_proposals": len(self.list_pending_proposals(tenant_id)),
            "total_changes": len([c for c in self._change_history if c.tenant_id == tenant_id]),
            "auto_promote_threshold": self.AUTO_PROMOTE_THRESHOLD,
        }


# Singleton
_living_ontology_manager: Optional[LivingOntologyManager] = None


def get_living_ontology_manager() -> LivingOntologyManager:
    """Retourne l'instance singleton du manager."""
    global _living_ontology_manager
    if _living_ontology_manager is None:
        _living_ontology_manager = LivingOntologyManager()
    return _living_ontology_manager


__all__ = [
    "LivingOntologyManager",
    "OntologyChange",
    "ChangeType",
    "TypeProposal",
    "get_living_ontology_manager",
]
