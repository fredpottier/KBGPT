"""
Tests de sécurité pour validation schémas Knowledge Graph.

Vérifie que les validations empêchent :
- Injection Cypher via entity_type/relation_type
- XSS via entity names
- Path traversal
- Types système réservés
"""
import pytest
from pydantic import ValidationError

from knowbase.api.schemas.knowledge_graph import EntityCreate, RelationCreate


class TestEntityTypeValidationSecurity:
    """Tests sécurité validation entity_type."""

    def test_valid_entity_types(self):
        """✅ Types valides acceptés."""
        valid_types = [
            "SOLUTION",
            "INFRASTRUCTURE",
            "LOAD_BALANCER",
            "API_GATEWAY",
            "S4HANA",
            "A",  # Min 1 char
            "X" * 50,  # Max 50 chars
        ]

        for entity_type in valid_types:
            entity = EntityCreate(
                name="Test Entity",
                entity_type=entity_type,
                description="Test description for validation",
                tenant_id="test"
            )
            # Auto-normalisé en UPPERCASE
            assert entity.entity_type == entity_type.upper()

    def test_entity_type_auto_uppercase(self):
        """✅ entity_type auto-normalisé en UPPERCASE."""
        entity = EntityCreate(
            name="Test",
            entity_type="infrastructure",  # lowercase
            description="Test description",
            tenant_id="test"
        )
        assert entity.entity_type == "INFRASTRUCTURE"

    def test_entity_type_too_long(self):
        """❌ entity_type > 50 chars rejeté."""
        with pytest.raises(ValidationError) as exc_info:
            EntityCreate(
                name="Test",
                entity_type="X" * 51,  # 51 chars
                description="Test description",
                tenant_id="test"
            )

        errors = exc_info.value.errors()
        assert any("entity_type" in str(err) for err in errors)

    def test_entity_type_invalid_characters(self):
        """❌ Caractères non alphanumériques rejetés (injection)."""
        invalid_types = [
            "SOLUTION' OR '1'='1",  # SQL injection
            "SOLUTION; DROP TABLE",  # Cypher injection
            "SOLUTION<script>",  # XSS
            "SOLUTION../../etc",  # Path traversal
            "SOLUTION\nINFRA",  # Newline injection
            "solution-type",  # Hyphen interdit
            "solution.type",  # Dot interdit
            "solution type",  # Space interdit
            "SOLUTION@TYPE",  # Special char
            "",  # Empty
        ]

        for invalid_type in invalid_types:
            with pytest.raises(ValidationError) as exc_info:
                EntityCreate(
                    name="Test",
                    entity_type=invalid_type,
                    description="Test description",
                    tenant_id="test"
                )

            errors = exc_info.value.errors()
            assert any(
                "entity_type" in str(err) or "ensure this value has at least 1" in str(err)
                for err in errors
            ), f"entity_type '{invalid_type}' devrait être rejeté"

    def test_entity_type_forbidden_prefixes(self):
        """❌ Préfixes système réservés rejetés."""
        # Types commençant par _ sont déjà bloqués par regex (doit commencer par lettre)
        # Donc on teste uniquement les préfixes SYSTEM_, ADMIN_, INTERNAL_
        forbidden_types = [
            "SYSTEM_TYPE",
            "ADMIN_CONFIG",
            "INTERNAL_CACHE",
        ]

        for forbidden_type in forbidden_types:
            with pytest.raises(ValidationError) as exc_info:
                EntityCreate(
                    name="Test",
                    entity_type=forbidden_type,
                    description="Test description",
                    tenant_id="test"
                )

            errors = exc_info.value.errors()
            error_msg = str(errors)
            assert "reserved prefixes" in error_msg.lower(), \
                f"Type '{forbidden_type}' devrait être rejeté (préfixe réservé)"

    def test_entity_type_must_start_uppercase_letter(self):
        """❌ entity_type doit commencer par lettre majuscule."""
        invalid_types = [
            "1SOLUTION",  # Commence par chiffre
            "_SOLUTION",  # Commence par underscore
            "9INFRASTRUCTURE",
        ]

        for invalid_type in invalid_types:
            with pytest.raises(ValidationError) as exc_info:
                EntityCreate(
                    name="Test",
                    entity_type=invalid_type,
                    description="Test description",
                    tenant_id="test"
                )

            errors = exc_info.value.errors()
            assert any("entity_type" in str(err) for err in errors)


class TestEntityNameValidationSecurity:
    """Tests sécurité validation entity name."""

    def test_valid_entity_names(self):
        """✅ Noms valides acceptés."""
        valid_names = [
            "SAP S/4HANA Cloud, Private Edition",
            "Load Balancer",
            "API Gateway (v2)",
            "Azure Virtual Network",
            "Nom-avec-tirets",
            "Entity_with_underscore",
            "Entity123",
        ]

        for name in valid_names:
            entity = EntityCreate(
                name=name,
                entity_type="SOLUTION",
                description="Test description for validation",
                tenant_id="test"
            )
            assert entity.name == name

    def test_entity_name_xss_rejected(self):
        """❌ Noms avec XSS rejetés."""
        xss_payloads = [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(1)>",
            "Test<script>alert('XSS')</script>",
            'Test"><script>alert(1)</script>',
            "Test`onerror=alert(1)`",
        ]

        for payload in xss_payloads:
            with pytest.raises(ValidationError) as exc_info:
                EntityCreate(
                    name=payload,
                    entity_type="SOLUTION",
                    description="Test description",
                    tenant_id="test"
                )

            errors = exc_info.value.errors()
            error_msg = str(errors)
            assert "forbidden characters" in error_msg.lower(), \
                f"XSS payload '{payload}' devrait être rejeté"

    def test_entity_name_path_traversal_rejected(self):
        """❌ Path traversal rejeté."""
        path_traversal_payloads = [
            "../../etc/passwd",
            "../../../secret",
            "/etc/passwd",
            "C:\\Windows\\System32",
            "Test../file",
            "..\\etc\\hosts",
        ]

        for payload in path_traversal_payloads:
            with pytest.raises(ValidationError) as exc_info:
                EntityCreate(
                    name=payload,
                    entity_type="SOLUTION",
                    description="Test description",
                    tenant_id="test"
                )

            errors = exc_info.value.errors()
            error_msg = str(errors)
            assert "path traversal" in error_msg.lower() or "forbidden characters" in error_msg.lower(), \
                f"Path traversal '{payload}' devrait être rejeté"

    def test_entity_name_special_chars_rejected(self):
        """❌ Caractères spéciaux dangereux rejetés."""
        dangerous_chars = [
            "Test\nEntity",  # Newline
            "Test\rEntity",  # Carriage return
            "Test\tEntity",  # Tab
            "Test\0Entity",  # Null byte
            'Test"Entity',  # Double quote
            "Test'Entity",  # Single quote
        ]

        for payload in dangerous_chars:
            with pytest.raises(ValidationError) as exc_info:
                EntityCreate(
                    name=payload,
                    entity_type="SOLUTION",
                    description="Test description",
                    tenant_id="test"
                )

            errors = exc_info.value.errors()
            error_msg = str(errors)
            assert "forbidden characters" in error_msg.lower()

    def test_entity_name_trimmed(self):
        """✅ Espaces début/fin trimés."""
        entity = EntityCreate(
            name="  Test Entity  ",
            entity_type="SOLUTION",
            description="Test description",
            tenant_id="test"
        )
        assert entity.name == "Test Entity"


class TestRelationTypeValidationSecurity:
    """Tests sécurité validation relation_type."""

    def test_valid_relation_types(self):
        """✅ Types relation valides acceptés."""
        valid_types = [
            "USES",
            "INTEGRATES_WITH",
            "PART_OF",
            "COMMUNICATES_WITH",
            "DEPLOYED_ON",
            "A",
            "X" * 50,
        ]

        for relation_type in valid_types:
            relation = RelationCreate(
                source="Entity A",
                target="Entity B",
                relation_type=relation_type,
                description="Test relation description",
                tenant_id="test"
            )
            assert relation.relation_type == relation_type.upper()

    def test_relation_type_auto_uppercase(self):
        """✅ relation_type auto-normalisé en UPPERCASE."""
        relation = RelationCreate(
            source="A",
            target="B",
            relation_type="uses",  # lowercase
            description="Test relation",
            tenant_id="test"
        )
        assert relation.relation_type == "USES"

    def test_relation_type_invalid_characters(self):
        """❌ Caractères non alphanumériques rejetés."""
        invalid_types = [
            "USES' OR '1'='1",
            "USES; DROP",
            "USES<script>",
            "uses-relation",
            "uses.relation",
            "uses relation",
            "",
        ]

        for invalid_type in invalid_types:
            with pytest.raises(ValidationError) as exc_info:
                RelationCreate(
                    source="A",
                    target="B",
                    relation_type=invalid_type,
                    description="Test relation",
                    tenant_id="test"
                )

            errors = exc_info.value.errors()
            assert any(
                "relation_type" in str(err) or "ensure this value has at least 1" in str(err)
                for err in errors
            )

    def test_relation_type_forbidden_prefixes(self):
        """❌ Préfixes système réservés rejetés."""
        # Types commençant par _ déjà bloqués par regex
        forbidden_types = [
            "SYSTEM_LINK",
            "ADMIN_CONNECTION",
            "INTERNAL_RELATION",
        ]

        for forbidden_type in forbidden_types:
            with pytest.raises(ValidationError) as exc_info:
                RelationCreate(
                    source="A",
                    target="B",
                    relation_type=forbidden_type,
                    description="Test relation",
                    tenant_id="test"
                )

            errors = exc_info.value.errors()
            error_msg = str(errors)
            assert "reserved prefixes" in error_msg.lower()


class TestRelationEntityNamesValidationSecurity:
    """Tests sécurité validation source/target relation."""

    def test_relation_entity_names_xss_rejected(self):
        """❌ XSS dans source/target rejeté."""
        xss_payloads = [
            "<script>alert(1)</script>",
            "Test<img src=x>",
        ]

        for payload in xss_payloads:
            # Test source
            with pytest.raises(ValidationError):
                RelationCreate(
                    source=payload,
                    target="Valid Target",
                    relation_type="USES",
                    description="Test relation",
                    tenant_id="test"
                )

            # Test target
            with pytest.raises(ValidationError):
                RelationCreate(
                    source="Valid Source",
                    target=payload,
                    relation_type="USES",
                    description="Test relation",
                    tenant_id="test"
                )


class TestFuzzingValidation:
    """Tests fuzzing pour robustesse validation."""

    def test_entity_type_fuzzing_extreme_lengths(self):
        """❌ Longueurs extrêmes rejetées."""
        extreme_types = [
            "",  # Empty
            "A" * 1000,  # Très long
            "A" * 10000,
        ]

        for extreme_type in extreme_types:
            with pytest.raises(ValidationError):
                EntityCreate(
                    name="Test",
                    entity_type=extreme_type,
                    description="Test description",
                    tenant_id="test"
                )

    def test_entity_name_fuzzing_unicode(self):
        """✅ Unicode supporté (noms internationaux)."""
        unicode_names = [
            "Système SAP",
            "Configuración",
            "系统",
            "Lösung",
        ]

        for name in unicode_names:
            entity = EntityCreate(
                name=name,
                entity_type="SOLUTION",
                description="Test description",
                tenant_id="test"
            )
            assert entity.name == name

    def test_mass_validation_performance(self):
        """✅ Validation rapide même avec masse données."""
        import time

        start = time.time()

        # Créer 1000 entités valides
        for i in range(1000):
            EntityCreate(
                name=f"Entity {i}",
                entity_type="SOLUTION",
                description="Test description for performance testing",
                tenant_id="test"
            )

        elapsed = time.time() - start

        # Validation doit être < 1s pour 1000 entités
        assert elapsed < 1.0, f"Validation trop lente: {elapsed:.2f}s pour 1000 entités"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
