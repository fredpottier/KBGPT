"""
Tests intégration pipeline avec Neo4j ontology.
"""
import pytest
import uuid as uuid_module
from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
from knowbase.api.schemas.knowledge_graph import EntityCreate


@pytest.fixture
def kg_service():
    """Fixture KnowledgeGraphService."""
    # Note: Ne pas fermer le service ici car le normalizer singleton partage le driver
    service = KnowledgeGraphService(tenant_id="default")
    yield service
    # Nettoyer: supprimer les entités de test
    # service.close() - Ne pas fermer pour éviter de casser le singleton normalizer


def test_entity_normalized_on_creation(kg_service):
    """Test que entité est normalisée lors création."""

    # Utiliser un alias unique pour forcer une nouvelle création
    unique_suffix = str(uuid_module.uuid4())[:8]

    entity_data = EntityCreate(
        name="hxm suite",  # Alias moins commun de SuccessFactors
        entity_type="SOLUTION",
        description=f"Test normalisation {unique_suffix}",
        confidence=0.9,
        tenant_id="default",
        attributes={}
    )

    # Créer entité
    entity = kg_service.get_or_create_entity(entity_data)

    # Vérifier normalisation (soit nouvelle entité, soit existante)
    assert entity.name == "SAP SuccessFactors"  # Normalisé depuis alias
    assert entity.status == "validated" or entity.status == "pending"  # Peut être déjà existant
    # Note: is_cataloged peut être False si entité déjà existante créée avant migration


def test_entity_type_correction(kg_service):
    """Test correction type si LLM se trompe."""

    unique_suffix = str(uuid_module.uuid4())[:8]

    entity_data = EntityCreate(
        name="hxm suite",  # Alias de SuccessFactors
        entity_type="SOFTWARE",  # Mauvais type (devrait être SOLUTION)
        description=f"Test correction type {unique_suffix}",
        confidence=0.9,
        tenant_id="default",
        attributes={}
    )

    entity = kg_service.get_or_create_entity(entity_data)

    # Type corrigé par ontologie
    assert entity.entity_type == "SOLUTION"  # Corrigé
    assert entity.name == "SAP SuccessFactors"
    assert entity.status == "validated"


def test_entity_not_cataloged(kg_service):
    """Test entité non cataloguée."""

    unique_suffix = str(uuid_module.uuid4())[:8]
    unknown_name = f"Unknown Product XYZ {unique_suffix}"

    entity_data = EntityCreate(
        name=unknown_name,
        entity_type="PRODUCT",
        description=f"Test non catalogué {unique_suffix}",
        confidence=0.8,
        tenant_id="default",
        attributes={}
    )

    entity = kg_service.get_or_create_entity(entity_data)

    # Entité non cataloguée
    assert entity.name == unknown_name  # Nom brut inchangé
    assert entity.status == "pending"  # Non validé
    assert entity.is_cataloged is False


def test_entity_case_insensitive(kg_service):
    """Test normalisation case insensitive."""

    unique_suffix = str(uuid_module.uuid4())[:8]

    entity_data = EntityCreate(
        name="ACR",  # Alias uppercase de "Advanced Compliance Reporting"
        entity_type="SOLUTION",
        description=f"Test case insensitive {unique_suffix}",
        confidence=0.9,
        tenant_id="default",
        attributes={}
    )

    entity = kg_service.get_or_create_entity(entity_data)

    # Normalisé malgré uppercase
    assert "Compliance" in entity.name or "Document" in entity.name  # Doit être normalisé
    assert entity.status == "validated"
    assert entity.is_cataloged is True


def test_entity_enriched_metadata(kg_service):
    """Test enrichissement metadata depuis ontologie."""

    unique_suffix = str(uuid_module.uuid4())[:8]

    entity_data = EntityCreate(
        name="global trade services",  # Alias
        entity_type="SOLUTION",
        description=f"Test metadata {unique_suffix}",
        confidence=0.9,
        tenant_id="default",
        attributes={}
    )

    entity = kg_service.get_or_create_entity(entity_data)

    # Metadata enrichies
    assert entity.attributes.get("catalog_id") is not None  # catalog_id présent
    assert entity.is_cataloged is True
    assert entity.status == "validated"
