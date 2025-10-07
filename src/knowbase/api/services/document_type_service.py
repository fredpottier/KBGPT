"""
Service pour gestion des Document Types.

Phase 6 - Document Types Management
"""
import json
from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_

from knowbase.db.models import DocumentType, DocumentTypeEntityType
from knowbase.api.schemas.document_types import (
    DocumentTypeCreate,
    DocumentTypeUpdate,
    DocumentTypeResponse,
    AddEntityTypesRequest,
)
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "document_type_service.log")


class DocumentTypeService:
    """Service pour gestion des types de documents."""

    def __init__(self, db: Session):
        """
        Initialize service.

        Args:
            db: Session SQLAlchemy
        """
        self.db = db

    def create(
        self,
        data: DocumentTypeCreate,
        admin_email: Optional[str] = None
    ) -> DocumentType:
        """
        Créer un nouveau document type.

        Args:
            data: Données de création
            admin_email: Email admin créateur

        Returns:
            DocumentType créé
        """
        logger.info(f"📝 Création document type: {data.name} (slug: {data.slug})")

        # Créer document type
        doc_type = DocumentType(
            name=data.name,
            slug=data.slug,
            description=data.description,
            context_prompt=data.context_prompt,
            is_active=data.is_active,
            tenant_id=data.tenant_id
        )

        self.db.add(doc_type)
        self.db.flush()  # Pour obtenir l'ID

        # Ajouter entity types si fournis
        if data.entity_types:
            for entity_type_name in data.entity_types:
                association = DocumentTypeEntityType(
                    document_type_id=doc_type.id,
                    entity_type_name=entity_type_name,
                    source="manual",
                    validated_by=admin_email,
                    validated_at=datetime.utcnow() if admin_email else None,
                    tenant_id=data.tenant_id
                )
                self.db.add(association)

        self.db.commit()
        self.db.refresh(doc_type)

        logger.info(f"✅ Document type créé: {doc_type.id}")
        return doc_type

    def get_by_id(self, document_type_id: str, tenant_id: str = "default") -> Optional[DocumentType]:
        """
        Récupérer document type par ID.

        Args:
            document_type_id: ID du document type
            tenant_id: Tenant ID

        Returns:
            DocumentType ou None
        """
        return self.db.query(DocumentType).filter(
            and_(
                DocumentType.id == document_type_id,
                DocumentType.tenant_id == tenant_id
            )
        ).first()

    def get_by_slug(self, slug: str, tenant_id: str = "default") -> Optional[DocumentType]:
        """
        Récupérer document type par slug.

        Args:
            slug: Slug du document type
            tenant_id: Tenant ID

        Returns:
            DocumentType ou None
        """
        return self.db.query(DocumentType).filter(
            and_(
                DocumentType.slug == slug,
                DocumentType.tenant_id == tenant_id
            )
        ).first()

    def list_all(
        self,
        tenant_id: str = "default",
        is_active: Optional[bool] = None
    ) -> List[DocumentType]:
        """
        Lister tous les document types.

        Args:
            tenant_id: Tenant ID
            is_active: Filtrer par statut actif (None = tous)

        Returns:
            Liste de DocumentType
        """
        query = self.db.query(DocumentType).filter(
            DocumentType.tenant_id == tenant_id
        )

        if is_active is not None:
            query = query.filter(DocumentType.is_active == is_active)

        return query.order_by(DocumentType.created_at.desc()).all()

    def update(
        self,
        document_type_id: str,
        data: DocumentTypeUpdate,
        tenant_id: str = "default"
    ) -> Optional[DocumentType]:
        """
        Mettre à jour document type.

        Args:
            document_type_id: ID du document type
            data: Données à mettre à jour
            tenant_id: Tenant ID

        Returns:
            DocumentType mis à jour ou None
        """
        doc_type = self.get_by_id(document_type_id, tenant_id)
        if not doc_type:
            return None

        # Mettre à jour champs fournis
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(doc_type, key, value)

        self.db.commit()
        self.db.refresh(doc_type)

        logger.info(f"✅ Document type mis à jour: {document_type_id}")
        return doc_type

    def delete(
        self,
        document_type_id: str,
        tenant_id: str = "default"
    ) -> bool:
        """
        Supprimer document type.

        Args:
            document_type_id: ID du document type
            tenant_id: Tenant ID

        Returns:
            True si supprimé, False sinon
        """
        doc_type = self.get_by_id(document_type_id, tenant_id)
        if not doc_type:
            return False

        # Vérifier si utilisé
        if doc_type.usage_count > 0:
            logger.warning(
                f"⚠️ Tentative suppression document type avec usage_count={doc_type.usage_count}: {document_type_id}"
            )
            return False

        self.db.delete(doc_type)
        self.db.commit()

        logger.info(f"✅ Document type supprimé: {document_type_id}")
        return True

    def get_suggested_entity_types(
        self,
        document_type_id: str,
        tenant_id: str = "default"
    ) -> List[str]:
        """
        Récupérer liste des entity types suggérés.

        Args:
            document_type_id: ID du document type
            tenant_id: Tenant ID

        Returns:
            Liste des entity_type_names
        """
        associations = self.db.query(DocumentTypeEntityType).filter(
            and_(
                DocumentTypeEntityType.document_type_id == document_type_id,
                DocumentTypeEntityType.tenant_id == tenant_id
            )
        ).all()

        return [assoc.entity_type_name for assoc in associations]

    def add_entity_types(
        self,
        document_type_id: str,
        entity_type_names: List[str],
        source: str = "manual",
        validated_by: Optional[str] = None,
        confidence: Optional[float] = None,
        examples: Optional[Dict[str, List[str]]] = None,
        tenant_id: str = "default"
    ) -> int:
        """
        Ajouter entity types à un document type.

        Args:
            document_type_id: ID du document type
            entity_type_names: Liste des types à ajouter
            source: Source (manual, llm_discovered, template)
            validated_by: Email admin validateur
            confidence: Confidence score (pour llm_discovered)
            examples: Dict {entity_type_name: [examples]}
            tenant_id: Tenant ID

        Returns:
            Nombre de types ajoutés
        """
        added_count = 0

        for entity_type_name in entity_type_names:
            # Vérifier si déjà existant
            existing = self.db.query(DocumentTypeEntityType).filter(
                and_(
                    DocumentTypeEntityType.document_type_id == document_type_id,
                    DocumentTypeEntityType.entity_type_name == entity_type_name,
                    DocumentTypeEntityType.tenant_id == tenant_id
                )
            ).first()

            if existing:
                logger.info(f"⏭️ Entity type déjà associé: {entity_type_name}")
                continue

            # Créer association
            examples_json = None
            if examples and entity_type_name in examples:
                examples_json = json.dumps(examples[entity_type_name])

            association = DocumentTypeEntityType(
                document_type_id=document_type_id,
                entity_type_name=entity_type_name,
                source=source,
                confidence=confidence,
                validated_by=validated_by,
                validated_at=datetime.utcnow() if validated_by else None,
                examples=examples_json,
                tenant_id=tenant_id
            )

            self.db.add(association)
            added_count += 1

        if added_count > 0:
            self.db.commit()
            logger.info(f"✅ {added_count} entity types ajoutés au document type {document_type_id}")

        return added_count

    def remove_entity_type(
        self,
        document_type_id: str,
        entity_type_name: str,
        tenant_id: str = "default"
    ) -> bool:
        """
        Retirer entity type d'un document type.

        Args:
            document_type_id: ID du document type
            entity_type_name: Type à retirer
            tenant_id: Tenant ID

        Returns:
            True si retiré, False sinon
        """
        association = self.db.query(DocumentTypeEntityType).filter(
            and_(
                DocumentTypeEntityType.document_type_id == document_type_id,
                DocumentTypeEntityType.entity_type_name == entity_type_name,
                DocumentTypeEntityType.tenant_id == tenant_id
            )
        ).first()

        if not association:
            return False

        self.db.delete(association)
        self.db.commit()

        logger.info(
            f"✅ Entity type retiré: {entity_type_name} du document type {document_type_id}"
        )
        return True

    def increment_usage(
        self,
        document_type_id: str,
        tenant_id: str = "default"
    ) -> None:
        """
        Incrémenter compteur d'usage.

        Args:
            document_type_id: ID du document type
            tenant_id: Tenant ID
        """
        doc_type = self.get_by_id(document_type_id, tenant_id)
        if doc_type:
            doc_type.usage_count += 1
            self.db.commit()

    def generate_extraction_prompt(
        self,
        document_type_id: str,
        slide_content: str,
        tenant_id: str = "default"
    ) -> str:
        """
        Générer prompt d'extraction adapté au document type.

        Args:
            document_type_id: ID du document type
            slide_content: Contenu de la slide/page
            tenant_id: Tenant ID

        Returns:
            Prompt formaté pour le LLM
        """
        doc_type = self.get_by_id(document_type_id, tenant_id)
        if not doc_type:
            # Fallback vers prompt générique
            return self._get_generic_extraction_prompt(slide_content)

        suggested_types = self.get_suggested_entity_types(document_type_id, tenant_id)

        # Construire prompt personnalisé
        prompt = f"""Analyse ce contenu et extrait les entités pertinentes.

**CONTEXTE DU DOCUMENT**: {doc_type.context_prompt or doc_type.description or "Document " + doc_type.name}

**TYPES D'ENTITÉS SUGGÉRÉS** (à privilégier):
{self._format_suggested_types(suggested_types)}

**AUTRES TYPES POSSIBLES**:
Tu peux aussi identifier d'autres types d'entités si pertinents, mais privilégie les types suggérés ci-dessus.

**CONTENU À ANALYSER**:
{slide_content}

**INSTRUCTIONS**:
1. Extrait les entités des types suggérés en priorité
2. Si tu identifies des entités d'autres types pertinents, inclus-les aussi
3. Pour chaque entité, fournis:
   - name: Nom de l'entité
   - entity_type: Type (UPPERCASE)
   - description: Description courte
   - confidence: Score de confiance (0.0-1.0)

**FORMAT DE SORTIE JSON**:
{{
  "entities": [
    {{
      "name": "SAP HANA",
      "entity_type": "SOLUTION",
      "description": "Database platform",
      "confidence": 0.95
    }},
    ...
  ]
}}

Retourne UNIQUEMENT le JSON, sans texte avant/après.
"""
        return prompt

    def _format_suggested_types(self, types: List[str]) -> str:
        """Formater liste de types suggérés."""
        if not types:
            return "Aucun type spécifique suggéré"

        return "\n".join([f"- {t}" for t in types])

    def _get_generic_extraction_prompt(self, content: str) -> str:
        """Prompt générique si pas de document type."""
        return f"""Analyse ce contenu et extrait les entités.

**CONTENU**:
{content}

Extrait les entités avec leur type, description et confidence.
Format JSON attendu.
"""


__all__ = ["DocumentTypeService"]
