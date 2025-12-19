"""
Tests for Entity Types - src/knowbase/common/entity_types.py

Tests cover:
- EntityType enum values and behavior
- RelationType enum values and behavior
- Enum string representation
- Module exports (__all__)
"""
from __future__ import annotations

import pytest

from knowbase.common.entity_types import EntityType, RelationType


# ============================================
# Test EntityType Enum
# ============================================

class TestEntityType:
    """Tests for EntityType enum."""

    def test_solution_exists(self) -> None:
        """SOLUTION entity type should exist."""
        assert EntityType.SOLUTION is not None
        assert EntityType.SOLUTION.value == "SOLUTION"

    def test_component_exists(self) -> None:
        """COMPONENT entity type should exist."""
        assert EntityType.COMPONENT is not None
        assert EntityType.COMPONENT.value == "COMPONENT"

    def test_organization_exists(self) -> None:
        """ORGANIZATION entity type should exist."""
        assert EntityType.ORGANIZATION is not None
        assert EntityType.ORGANIZATION.value == "ORGANIZATION"

    def test_person_exists(self) -> None:
        """PERSON entity type should exist."""
        assert EntityType.PERSON is not None
        assert EntityType.PERSON.value == "PERSON"

    def test_technology_exists(self) -> None:
        """TECHNOLOGY entity type should exist."""
        assert EntityType.TECHNOLOGY is not None
        assert EntityType.TECHNOLOGY.value == "TECHNOLOGY"

    def test_concept_exists(self) -> None:
        """CONCEPT entity type should exist."""
        assert EntityType.CONCEPT is not None
        assert EntityType.CONCEPT.value == "CONCEPT"

    def test_all_entity_types_count(self) -> None:
        """Should have exactly 6 entity types."""
        all_types = list(EntityType)
        assert len(all_types) == 6

    def test_entity_type_is_str_enum(self) -> None:
        """EntityType should be a string enum."""
        assert isinstance(EntityType.SOLUTION, str)
        assert EntityType.SOLUTION == "SOLUTION"

    def test_entity_type_from_value(self) -> None:
        """EntityType should be constructible from value."""
        entity_type = EntityType("SOLUTION")
        assert entity_type == EntityType.SOLUTION

    def test_entity_type_invalid_value(self) -> None:
        """Invalid value should raise ValueError."""
        with pytest.raises(ValueError):
            EntityType("INVALID_TYPE")

    def test_entity_type_in_dict_key(self) -> None:
        """EntityType should work as dict key."""
        mapping = {
            EntityType.SOLUTION: "solutions",
            EntityType.COMPONENT: "components",
        }
        assert mapping[EntityType.SOLUTION] == "solutions"
        assert mapping[EntityType.COMPONENT] == "components"

    def test_entity_type_iteration(self) -> None:
        """Should be able to iterate over all entity types."""
        types = [t for t in EntityType]
        assert EntityType.SOLUTION in types
        assert EntityType.COMPONENT in types
        assert EntityType.ORGANIZATION in types
        assert EntityType.PERSON in types
        assert EntityType.TECHNOLOGY in types
        assert EntityType.CONCEPT in types

    def test_entity_type_comparison(self) -> None:
        """Entity types should be comparable."""
        assert EntityType.SOLUTION == EntityType.SOLUTION
        assert EntityType.SOLUTION != EntityType.COMPONENT

    def test_entity_type_string_comparison(self) -> None:
        """Entity types should compare equal to their string values."""
        assert EntityType.SOLUTION == "SOLUTION"
        assert EntityType.COMPONENT == "COMPONENT"

    def test_entity_type_name_attribute(self) -> None:
        """Entity types should have name attribute."""
        assert EntityType.SOLUTION.name == "SOLUTION"
        assert EntityType.PERSON.name == "PERSON"


# ============================================
# Test RelationType Enum
# ============================================

class TestRelationType:
    """Tests for RelationType enum."""

    def test_integrates_with_exists(self) -> None:
        """INTEGRATES_WITH relation type should exist."""
        assert RelationType.INTEGRATES_WITH is not None
        assert RelationType.INTEGRATES_WITH.value == "INTEGRATES_WITH"

    def test_part_of_exists(self) -> None:
        """PART_OF relation type should exist."""
        assert RelationType.PART_OF is not None
        assert RelationType.PART_OF.value == "PART_OF"

    def test_uses_exists(self) -> None:
        """USES relation type should exist."""
        assert RelationType.USES is not None
        assert RelationType.USES.value == "USES"

    def test_provides_exists(self) -> None:
        """PROVIDES relation type should exist."""
        assert RelationType.PROVIDES is not None
        assert RelationType.PROVIDES.value == "PROVIDES"

    def test_replaces_exists(self) -> None:
        """REPLACES relation type should exist."""
        assert RelationType.REPLACES is not None
        assert RelationType.REPLACES.value == "REPLACES"

    def test_requires_exists(self) -> None:
        """REQUIRES relation type should exist."""
        assert RelationType.REQUIRES is not None
        assert RelationType.REQUIRES.value == "REQUIRES"

    def test_interacts_with_exists(self) -> None:
        """INTERACTS_WITH relation type should exist."""
        assert RelationType.INTERACTS_WITH is not None
        assert RelationType.INTERACTS_WITH.value == "INTERACTS_WITH"

    def test_all_relation_types_count(self) -> None:
        """Should have exactly 7 relation types."""
        all_types = list(RelationType)
        assert len(all_types) == 7

    def test_relation_type_is_str_enum(self) -> None:
        """RelationType should be a string enum."""
        assert isinstance(RelationType.USES, str)
        assert RelationType.USES == "USES"

    def test_relation_type_from_value(self) -> None:
        """RelationType should be constructible from value."""
        relation_type = RelationType("USES")
        assert relation_type == RelationType.USES

    def test_relation_type_invalid_value(self) -> None:
        """Invalid value should raise ValueError."""
        with pytest.raises(ValueError):
            RelationType("INVALID_RELATION")

    def test_relation_type_in_dict_key(self) -> None:
        """RelationType should work as dict key."""
        mapping = {
            RelationType.USES: "uses_edge",
            RelationType.PART_OF: "part_of_edge",
        }
        assert mapping[RelationType.USES] == "uses_edge"
        assert mapping[RelationType.PART_OF] == "part_of_edge"

    def test_relation_type_iteration(self) -> None:
        """Should be able to iterate over all relation types."""
        types = [t for t in RelationType]
        assert RelationType.INTEGRATES_WITH in types
        assert RelationType.PART_OF in types
        assert RelationType.USES in types
        assert RelationType.PROVIDES in types
        assert RelationType.REPLACES in types
        assert RelationType.REQUIRES in types
        assert RelationType.INTERACTS_WITH in types

    def test_relation_type_comparison(self) -> None:
        """Relation types should be comparable."""
        assert RelationType.USES == RelationType.USES
        assert RelationType.USES != RelationType.PROVIDES

    def test_relation_type_string_comparison(self) -> None:
        """Relation types should compare equal to their string values."""
        assert RelationType.USES == "USES"
        assert RelationType.PART_OF == "PART_OF"


# ============================================
# Test Module Exports
# ============================================

class TestModuleExports:
    """Tests for module __all__ exports."""

    def test_entity_type_in_all(self) -> None:
        """EntityType should be in __all__."""
        from knowbase.common.entity_types import __all__
        assert "EntityType" in __all__

    def test_relation_type_in_all(self) -> None:
        """RelationType should be in __all__."""
        from knowbase.common.entity_types import __all__
        assert "RelationType" in __all__

    def test_all_exports_count(self) -> None:
        """__all__ should have exactly 2 exports."""
        from knowbase.common.entity_types import __all__
        assert len(__all__) == 2


# ============================================
# Test JSON Serialization
# ============================================

class TestJsonSerialization:
    """Tests for JSON serialization compatibility."""

    def test_entity_type_json_serializable(self) -> None:
        """EntityType should be JSON serializable via value."""
        import json
        data = {"type": EntityType.SOLUTION.value}
        json_str = json.dumps(data)
        assert "SOLUTION" in json_str

    def test_relation_type_json_serializable(self) -> None:
        """RelationType should be JSON serializable via value."""
        import json
        data = {"relation": RelationType.USES.value}
        json_str = json.dumps(data)
        assert "USES" in json_str

    def test_entity_type_direct_json(self) -> None:
        """EntityType (as str) should be directly JSON serializable."""
        import json
        # Since it inherits from str, it should work directly
        data = {"type": str(EntityType.SOLUTION)}
        json_str = json.dumps(data)
        assert "SOLUTION" in json_str


# ============================================
# Test Use Cases
# ============================================

class TestUseCases:
    """Tests for common use cases."""

    def test_entity_type_in_neo4j_label(self) -> None:
        """EntityType should work for Neo4j labels."""
        label = f":{EntityType.SOLUTION.value}"
        assert label == ":SOLUTION"

    def test_relation_type_in_neo4j_type(self) -> None:
        """RelationType should work for Neo4j relationship types."""
        rel_type = f"[:{RelationType.USES.value}]"
        assert rel_type == "[:USES]"

    def test_entity_type_in_query_filter(self) -> None:
        """EntityType should work in query filters."""
        query_params = {"type": EntityType.COMPONENT.value}
        assert query_params["type"] == "COMPONENT"

    def test_relation_type_in_query_filter(self) -> None:
        """RelationType should work in query filters."""
        query_params = {"relation": RelationType.PART_OF.value}
        assert query_params["relation"] == "PART_OF"

    def test_create_entity_type_mapping(self) -> None:
        """Should be able to create comprehensive entity type mapping."""
        mapping = {et: et.value.lower() for et in EntityType}
        assert len(mapping) == 6
        assert mapping[EntityType.SOLUTION] == "solution"
        assert mapping[EntityType.PERSON] == "person"

    def test_create_relation_type_mapping(self) -> None:
        """Should be able to create comprehensive relation type mapping."""
        mapping = {rt: rt.value.replace("_", " ").title() for rt in RelationType}
        assert len(mapping) == 7
        assert mapping[RelationType.INTEGRATES_WITH] == "Integrates With"
        assert mapping[RelationType.PART_OF] == "Part Of"


# ============================================
# Test Edge Cases
# ============================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_entity_type_hash(self) -> None:
        """EntityType should be hashable."""
        types_set = {EntityType.SOLUTION, EntityType.COMPONENT, EntityType.SOLUTION}
        assert len(types_set) == 2  # Solution appears once

    def test_relation_type_hash(self) -> None:
        """RelationType should be hashable."""
        types_set = {RelationType.USES, RelationType.PROVIDES, RelationType.USES}
        assert len(types_set) == 2  # Uses appears once

    def test_entity_type_membership(self) -> None:
        """Should be able to check membership."""
        assert "SOLUTION" in [e.value for e in EntityType]
        assert "INVALID" not in [e.value for e in EntityType]

    def test_relation_type_membership(self) -> None:
        """Should be able to check membership."""
        assert "USES" in [r.value for r in RelationType]
        assert "INVALID" not in [r.value for r in RelationType]

    def test_case_sensitivity(self) -> None:
        """Enum values should be case sensitive."""
        with pytest.raises(ValueError):
            EntityType("solution")  # lowercase should fail

        with pytest.raises(ValueError):
            RelationType("uses")  # lowercase should fail
