"""
Script de migration pour créer les document types par défaut.

Phase 6 - Document Types Management

Crée les 3 types de documents historiques:
- Technical
- Functional
- Marketing
"""
import sys
from pathlib import Path

# Ajouter le répertoire racine au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parents[4]))

from sqlalchemy.orm import Session
from knowbase.db import init_db, get_db, DocumentType, DocumentTypeEntityType
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "migrate_document_types.log")


DEFAULT_DOCUMENT_TYPES = [
    {
        "name": "Technical Documentation",
        "slug": "technical",
        "description": "Documentation technique détaillant architectures, API, et implémentations",
        "context_prompt": "Document technique présentant des solutions technologiques avec focus sur l'architecture, les composants système, et les intégrations.",
        "entity_types": ["SOLUTION", "INFRASTRUCTURE", "COMPONENT", "TECHNOLOGY"],
        "is_active": True,
    },
    {
        "name": "Functional Documentation",
        "slug": "functional",
        "description": "Documentation fonctionnelle décrivant processus métier et cas d'usage",
        "context_prompt": "Document fonctionnel décrivant les processus métier, workflows, et fonctionnalités utilisateur.",
        "entity_types": ["SOLUTION", "COMPONENT", "ORGANIZATION"],
        "is_active": True,
    },
    {
        "name": "Marketing Material",
        "slug": "marketing",
        "description": "Matériel marketing : brochures, présentations produits, cas clients",
        "context_prompt": "Matériel marketing présentant des produits, leurs avantages, et témoignages clients.",
        "entity_types": ["SOLUTION", "ORGANIZATION", "INFRASTRUCTURE", "TECHNOLOGY"],
        "is_active": True,
    },
]


def migrate():
    """Créer les document types par défaut."""
    logger.info("🚀 Début migration document types par défaut")

    # Initialiser DB
    init_db()

    # Obtenir session
    db_generator = get_db()
    db: Session = next(db_generator)

    try:
        created_count = 0
        skipped_count = 0

        for doc_type_data in DEFAULT_DOCUMENT_TYPES:
            slug = doc_type_data["slug"]

            # Vérifier si existe déjà
            existing = db.query(DocumentType).filter(
                DocumentType.slug == slug,
                DocumentType.tenant_id == "default"
            ).first()

            if existing:
                logger.info(f"⏭️ Document type '{slug}' existe déjà, skip")
                skipped_count += 1
                continue

            # Créer document type
            doc_type = DocumentType(
                name=doc_type_data["name"],
                slug=doc_type_data["slug"],
                description=doc_type_data["description"],
                context_prompt=doc_type_data["context_prompt"],
                is_active=doc_type_data["is_active"],
                tenant_id="default",
                usage_count=0
            )

            db.add(doc_type)
            db.flush()  # Pour obtenir l'ID

            # Ajouter entity types
            for entity_type_name in doc_type_data["entity_types"]:
                association = DocumentTypeEntityType(
                    document_type_id=doc_type.id,
                    entity_type_name=entity_type_name,
                    source="template",
                    validated_by="system",
                    tenant_id="default"
                )
                db.add(association)

            db.commit()
            created_count += 1
            logger.info(
                f"✅ Document type créé: {doc_type.name} (slug={slug}, "
                f"{len(doc_type_data['entity_types'])} entity types)"
            )

        logger.info(
            f"✅ Migration terminée: {created_count} créés, {skipped_count} existants"
        )

    except Exception as e:
        logger.error(f"❌ Erreur migration: {e}")
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    migrate()
