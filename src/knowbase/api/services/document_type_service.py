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
            # Vérifier quels types existent déjà
            from knowbase.db import EntityTypeRegistry

            existing_types = self.db.query(EntityTypeRegistry.type_name).filter(
                EntityTypeRegistry.tenant_id == data.tenant_id
            ).all()
            existing_types_set = {t[0] for t in existing_types}

            for entity_type_name in data.entity_types:
                # Créer le type s'il n'existe pas
                if entity_type_name not in existing_types_set:
                    logger.info(f"🆕 Création automatique entity type: {entity_type_name}")
                    new_type = EntityTypeRegistry(
                        type_name=entity_type_name,
                        status="approved",
                        discovered_by="admin",
                        approved_by=admin_email or "system",
                        approved_at=datetime.utcnow(),
                        tenant_id=data.tenant_id
                    )
                    self.db.add(new_type)
                    existing_types_set.add(entity_type_name)

                # Créer association
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

        # Construire prompt personnalisé avec extraction complète (concepts, facts, entities, relations)
        prompt = f"""Extract structured knowledge from this content.

**DOCUMENT CONTEXT**: {doc_type.context_prompt or doc_type.description or "Document " + doc_type.name}

**SUGGESTED ENTITY TYPES** (prioritize these):
{self._format_suggested_types(suggested_types)}

**CONTENT TO ANALYZE**:
{slide_content}

**INSTRUCTIONS** - Extract the following 4 types of knowledge:

1. **CONCEPTS** - Main ideas, definitions, explanations
   Each concept must contain:
   - `full_explanation`: string (detailed description of the concept)
   - `meta`: object with:
     - `type`: string (e.g., 'definition', 'process', 'architecture', 'feature')
     - `level`: number (importance: 1=critical, 2=important, 3=detail)
     - `topic`: string (main topic)

2. **FACTS** - Factual statements and assertions
   Each fact must contain:
   - `subject`: string (what the fact is about)
   - `predicate`: string (relationship or property)
   - `value`: string/number (value or target)
   - `confidence`: number (0-1, certainty level)
   - `fact_type`: string (e.g., 'specification', 'requirement', 'statistic')

3. **ENTITIES** - Named entities (products, technologies, components)
   Each entity must contain:
   - `name`: string (canonical name)
   - `entity_type`: string (UPPERCASE - prioritize suggested types above)
   - `description`: string (brief description, optional)
   - `confidence`: number (0-1, certainty level)

4. **RELATIONS** - Relationships between entities
   Each relation must contain:
   - `source`: string (source entity name)
   - `relation_type`: string (use one of these semantic types):
     * Structural: PART_OF, CONTAINS, HAS_MEMBER
     * Functional: USES, USED_BY, REQUIRES, PROVIDES
     * Implementation: IMPLEMENTS, SUPPORTS, EXTENDS
     * Reference: MENTIONS, RELATED_TO
     * Temporal: PRECEDES, FOLLOWS
     * Version: REPLACES, REPLACED_BY
     * Technical: INTEGRATES_WITH, DEPENDS_ON, COMPATIBLE_WITH
   - `target`: string (target entity name)
   - `description`: string (optional context explaining the relationship)

**JSON OUTPUT FORMAT**:
{{
  "concepts": [
    {{
      "full_explanation": "SAP S/4HANA is...",
      "meta": {{
        "type": "definition",
        "level": 1,
        "topic": "ERP"
      }}
    }}
  ],
  "facts": [
    {{
      "subject": "SAP HANA",
      "predicate": "supports",
      "value": "in-memory computing",
      "confidence": 0.95,
      "fact_type": "specification"
    }}
  ],
  "entities": [
    {{
      "name": "SAP HANA",
      "entity_type": "SOLUTION",
      "description": "Database platform",
      "confidence": 0.95
    }}
  ],
  "relations": [
    {{
      "source": "SAP S/4HANA",
      "relation_type": "USES",
      "target": "SAP HANA",
      "description": "S/4HANA runs on HANA database"
    }}
  ]
}}

**IMPORTANT**:
- **PRESERVE THE ORIGINAL LANGUAGE**: If the source content is in English, write all extracted content in English. If it's in French, write in French. If it's in Portuguese, write in Portuguese. Match the language of the source document.
- Extract ALL concepts, facts, entities, and relations present in the content
- Prioritize the suggested entity types but don't limit yourself to them
- All 4 keys (concepts, facts, entities, relations) are REQUIRED even if some arrays are empty
- Return ONLY the JSON, with no text before or after
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
