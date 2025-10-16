"""
Sauvegarde ontologies générées par LLM dans Neo4j.

P0.1 Sandbox Auto-Learning (2025-10-16):
- Auto-validation si confidence >= seuil adaptatif
- Notification admin si requires_validation=True
- Support status sandbox (pending/validated/manual)

P1.1 Seuils Adaptatifs (2025-10-16):
- Seuils ajustés selon contexte (domaine, source, langue)
- Profils: SAP_OFFICIAL_DOCS, INTERNAL_DOCS, COMMUNITY_CONTENT, etc.
"""
from typing import List, Dict, Optional
from datetime import datetime, timezone
from neo4j import GraphDatabase
import uuid
import logging

from knowbase.ontology.adaptive_thresholds import (
    get_adaptive_threshold_selector,
    DomainContext,
    SourceContext,
    LanguageContext,
    EntityTypeContext
)

logger = logging.getLogger(__name__)


def notify_admin_validation_required(
    canonical_name: str,
    entity_type: str,
    confidence: float,
    tenant_id: str
):
    """
    Notifie admin qu'une entité nécessite validation (P0.1 Sandbox).

    TODO Phase 2: Implémenter notification réelle (email, webhook, UI badge).

    Args:
        canonical_name: Nom entité
        entity_type: Type entité
        confidence: Score confidence
        tenant_id: Tenant ID
    """
    logger.warning(
        f"[ONTOLOGY:Sandbox] ⚠️  ADMIN VALIDATION REQUIRED: "
        f"'{canonical_name}' (type={entity_type}, confidence={confidence:.2f}, tenant={tenant_id})"
    )
    # TODO: Envoyer notification réelle (email, webhook, UI badge)


def save_ontology_to_neo4j(
    merge_groups: List[Dict],
    entity_type: str,
    tenant_id: str = "default",
    source: str = "llm_generated",
    neo4j_uri: str = None,
    neo4j_user: str = None,
    neo4j_password: str = None,
    domain: Optional[str] = None,
    source_context: Optional[str] = None,
    language: Optional[str] = None
):
    """
    Sauvegarde ontologie générée dans Neo4j.

    Args:
        merge_groups: Groupes validés par user
        entity_type: Type d'entité
        tenant_id: Tenant ID
        source: Source ontologie ("llm_generated" | "manual")
        neo4j_uri: URI Neo4j (optionnel)
        neo4j_user: User (optionnel)
        neo4j_password: Password (optionnel)
        domain: Domaine technique (P1.1 - sap_ecosystem, cloud_computing, etc.)
        source_context: Contexte source (P1.1 - official_documentation, internal_documentation, etc.)
        language: Contexte linguistique (P1.1 - french, english, multilingual, etc.)
    """
    if not neo4j_uri:
        from knowbase.config.settings import get_settings
        settings = get_settings()
        neo4j_uri = settings.neo4j_uri
        neo4j_user = settings.neo4j_user
        neo4j_password = settings.neo4j_password

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    # P1.1: Initialiser sélecteur seuils adaptatifs
    threshold_selector = get_adaptive_threshold_selector()

    # Convertir contextes en enums (si fournis)
    domain_ctx = DomainContext(domain) if domain else None
    source_ctx = SourceContext(source_context) if source_context else None
    lang_ctx = LanguageContext(language) if language else None
    entity_type_ctx = EntityTypeContext(entity_type) if entity_type in [e.value for e in EntityTypeContext] else None

    # Sélectionner profil de seuils
    threshold_profile = threshold_selector.select_profile(
        domain=domain_ctx,
        source=source_ctx,
        language=lang_ctx,
        entity_type=entity_type_ctx
    )

    logger.info(
        f"[ONTOLOGY:AdaptiveThresholds] Selected threshold profile: {threshold_profile.name} "
        f"(auto_validation={threshold_profile.auto_validation_threshold:.2f}, "
        f"require_human_below={threshold_profile.require_human_validation_below:.2f})"
    )

    try:
        with driver.session() as session:
            for group in merge_groups:
                entity_id = group["canonical_key"]
                canonical_name = group["canonical_name"]
                confidence = group.get("confidence", 0.95)

                # P0.1 Sandbox Auto-Learning: Déterminer status et validation
                logger.debug(
                    f"[ONTOLOGY:Sandbox] Processing '{canonical_name}' "
                    f"(source={source}, confidence={confidence:.2f}, profile={threshold_profile.name})"
                )

                if source == "llm_generated":
                    created_by = "auto_learning"
                elif source == "manual":
                    created_by = "admin"
                else:
                    created_by = source

                # P1.1: Auto-validation avec seuil adaptatif (au lieu de 0.95 fixe)
                auto_validation_threshold = threshold_profile.auto_validation_threshold
                require_human_threshold = threshold_profile.require_human_validation_below

                if confidence >= auto_validation_threshold:
                    status = "auto_learned_validated"
                    requires_admin_validation = False
                    validated_by = "auto_validated"

                    logger.info(
                        f"[ONTOLOGY:AdaptiveThresholds] ✅ AUTO-VALIDATED '{canonical_name}' "
                        f"(confidence={confidence:.2f} >= {auto_validation_threshold:.2f}, "
                        f"profile={threshold_profile.name}, status={status})"
                    )
                elif confidence >= require_human_threshold:
                    status = "auto_learned_pending"
                    requires_admin_validation = True
                    validated_by = None

                    logger.warning(
                        f"[ONTOLOGY:AdaptiveThresholds] ⏳ PENDING VALIDATION '{canonical_name}' "
                        f"(confidence={confidence:.2f} in [{require_human_threshold:.2f}, {auto_validation_threshold:.2f}), "
                        f"profile={threshold_profile.name}, requires_admin=True)"
                    )

                    # Notification admin pour validation
                    notify_admin_validation_required(
                        canonical_name=canonical_name,
                        entity_type=entity_type,
                        confidence=confidence,
                        tenant_id=tenant_id
                    )
                else:
                    # Confidence trop basse: rejeter ou marquer comme très faible confiance
                    status = "auto_learned_pending"
                    requires_admin_validation = True
                    validated_by = None

                    logger.error(
                        f"[ONTOLOGY:AdaptiveThresholds] ⚠️  LOW CONFIDENCE '{canonical_name}' "
                        f"(confidence={confidence:.2f} < {require_human_threshold:.2f}, "
                        f"profile={threshold_profile.name}, requires_admin=True, consider_rejection=True)"
                    )

                    # Notification admin pour validation
                    notify_admin_validation_required(
                        canonical_name=canonical_name,
                        entity_type=entity_type,
                        confidence=confidence,
                        tenant_id=tenant_id
                    )

                # Support création manuelle admin
                if created_by == "admin":
                    status = "manual"
                    requires_admin_validation = False
                    validated_by = "admin"

                    logger.info(
                        f"[ONTOLOGY:Sandbox] ✅ MANUAL CREATION '{canonical_name}' "
                        f"(created_by=admin, status=manual)"
                    )

                # Créer/update OntologyEntity avec champs sandbox
                session.run("""
                    MERGE (ont:OntologyEntity {entity_id: $entity_id})
                    SET ont.canonical_name = $canonical_name,
                        ont.entity_type = $entity_type,
                        ont.source = $source,
                        ont.confidence = $confidence,
                        ont.tenant_id = $tenant_id,
                        ont.created_at = coalesce(ont.created_at, datetime()),
                        ont.updated_at = datetime(),
                        ont.version = coalesce(ont.version, '1.0.0'),

                        ont.status = $status,
                        ont.requires_admin_validation = $requires_admin_validation,
                        ont.created_by = $created_by,
                        ont.validated_by = $validated_by,
                        ont.validated_at = CASE
                            WHEN $validated_by IS NOT NULL THEN datetime()
                            ELSE null
                        END
                """, {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                    "source": source,
                    "confidence": confidence,
                    "tenant_id": tenant_id,
                    "status": status,
                    "requires_admin_validation": requires_admin_validation,
                    "created_by": created_by,
                    "validated_by": validated_by
                })

                logger.debug(
                    f"[ONTOLOGY:Sandbox] Saved '{canonical_name}' "
                    f"(status={status}, confidence={confidence:.2f}, requires_validation={requires_admin_validation})"
                )

                # Créer aliases depuis entités mergées
                for entity in group["entities"]:
                    alias_name = entity["name"]

                    # Skip si alias == canonical (éviter doublon)
                    if alias_name.lower() == canonical_name.lower():
                        continue

                    alias_id = str(uuid.uuid4())
                    normalized = alias_name.lower().strip()

                    session.run("""
                        MATCH (ont:OntologyEntity {entity_id: $entity_id})
                        MERGE (alias:OntologyAlias {
                            normalized: $normalized,
                            entity_type: $entity_type,
                            tenant_id: $tenant_id
                        })
                        ON CREATE SET
                            alias.alias_id = $alias_id,
                            alias.alias = $alias
                        MERGE (ont)-[:HAS_ALIAS]->(alias)
                    """, {
                        "entity_id": entity_id,
                        "alias_id": alias_id,
                        "alias": alias_name,
                        "normalized": normalized,
                        "entity_type": entity_type,
                        "tenant_id": tenant_id
                    })

        logger.info(
            f"✅ Ontologie sauvegardée: {entity_type}, "
            f"{len(merge_groups)} groupes, {sum(len(g['entities']) for g in merge_groups)} aliases"
        )

    finally:
        driver.close()


__all__ = ["save_ontology_to_neo4j"]
