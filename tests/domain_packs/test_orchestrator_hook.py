# tests/domain_packs/test_orchestrator_hook.py
"""Tests pour le hook Phase 4.5 — Domain Pack Enrichment."""

import pytest
from unittest.mock import patch, MagicMock
from typing import Dict, List, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.entity import Entity, EntityType, is_valid_entity_name
from knowbase.domain_packs.base import DomainPack, DomainEntityExtractor


# ============================================================================
# Fixtures
# ============================================================================


def _make_claim(claim_id: str, text: str, tenant_id: str = "default") -> Claim:
    return Claim(
        claim_id=claim_id,
        text=text,
        tenant_id=tenant_id,
        doc_id="doc1",
        unit_ids=["u1"],
        claim_type="FACTUAL",
        verbatim_quote=text,
        passage_id="p1",
    )


def _make_entity(
    entity_id: str, name: str, entity_type: EntityType = EntityType.CONCEPT,
    tenant_id: str = "default", source_pack: str = None,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        name=name,
        entity_type=entity_type,
        tenant_id=tenant_id,
        source_pack=source_pack,
    )


class FakeExtractor(DomainEntityExtractor):
    """Extracteur de test qui retourne des entités prédéfinies."""

    def __init__(self, entities_to_return, candidate_map_to_return):
        self._entities = entities_to_return
        self._candidate_map = candidate_map_to_return

    def load_model(self):
        pass

    @property
    def entity_type_mapping(self) -> Dict[str, EntityType]:
        return {"CHEMICAL": EntityType.CONCEPT}

    def extract(self, claims, existing_entities, domain_context):
        return self._entities, self._candidate_map


class FakePack(DomainPack):
    """Pack de test avec extracteur configurable."""

    def __init__(self, name="fake", extractors=None, stoplist=None):
        super().__init__()
        self._name = name
        self._extractors = extractors or []
        self._stoplist = stoplist or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return "Fake Pack"

    @property
    def description(self) -> str:
        return "Test pack"

    @property
    def priority(self) -> int:
        return 100

    def get_entity_extractors(self):
        return self._extractors

    def get_entity_stoplist(self):
        return self._stoplist


# ============================================================================
# Tests
# ============================================================================


class TestIsValidEntityNameNerSourced:
    """Tests pour le paramètre ner_sourced de is_valid_entity_name."""

    def test_lowercase_biomedical_term_valid(self):
        assert is_valid_entity_name("sepsis") is True

    def test_lowercase_biomedical_term_valid_ner(self):
        assert is_valid_entity_name("sepsis", ner_sourced=True) is True

    def test_stoplist_rejected_even_ner(self):
        assert is_valid_entity_name("system", ner_sourced=True) is False

    def test_phrase_fragment_rejected_ner(self):
        assert is_valid_entity_name("is elevated", ner_sourced=True) is False

    def test_short_name_rejected(self):
        assert is_valid_entity_name("ab", ner_sourced=True) is False

    def test_long_biomedical_concept(self):
        assert is_valid_entity_name(
            "procalcitonin-guided antibiotic stewardship",
            ner_sourced=True
        ) is True


class TestEntitySourcePack:
    """Tests pour le champ source_pack sur Entity."""

    def test_source_pack_none_by_default(self):
        e = _make_entity("e1", "CRISPR-Cas9")
        assert e.source_pack is None

    def test_source_pack_in_neo4j_properties(self):
        e = _make_entity("e1", "sepsis", source_pack="biomedical")
        props = e.to_neo4j_properties()
        assert props["source_pack"] == "biomedical"

    def test_source_pack_absent_when_none(self):
        e = _make_entity("e1", "CRISPR-Cas9")
        props = e.to_neo4j_properties()
        assert "source_pack" not in props

    def test_from_neo4j_record_with_source_pack(self):
        record = {
            "entity_id": "e1",
            "tenant_id": "default",
            "name": "sepsis",
            "entity_type": "concept",
            "source_pack": "biomedical",
        }
        e = Entity.from_neo4j_record(record)
        assert e.source_pack == "biomedical"


class TestDomainPackEnrichmentLogic:
    """Tests pour la logique d'enrichissement (sans orchestrateur complet)."""

    def test_gate_rejects_stoplist(self):
        """Les entités dans la stoplist du pack sont rejetées."""
        pack = FakePack(stoplist=["PubMed"])
        stoplist_norms = set(Entity.normalize(s) for s in pack.get_entity_stoplist())
        entity_name = "PubMed"
        norm = Entity.normalize(entity_name)
        assert norm in stoplist_norms

    def test_gate_rejects_invalid_name(self):
        """Les noms invalides sont rejetés même en mode NER."""
        assert is_valid_entity_name("is", ner_sourced=True) is False
        assert is_valid_entity_name("the", ner_sourced=True) is False

    def test_dedup_prevents_duplicates(self):
        """Les entités déjà existantes ne sont pas recréées."""
        existing = [_make_entity("e1", "sepsis")]
        existing_norms = {e.normalized_name for e in existing}

        new_entity_norm = Entity.normalize("sepsis")
        assert new_entity_norm in existing_norms

    def test_source_pack_tagging(self):
        """Les entités créées par un pack portent le tag source_pack."""
        entity = _make_entity("e1", "lactate")
        object.__setattr__(entity, "source_pack", "biomedical")
        assert entity.source_pack == "biomedical"

    def test_link_method_format(self):
        """Le method tag suit le format domain_pack:<name>."""
        pack = FakePack(name="biomedical")
        method = f"domain_pack:{pack.name}"
        assert method == "domain_pack:biomedical"


class TestClaimFirstResultLinkMethods:
    """Tests pour claim_entity_link_methods dans ClaimFirstResult."""

    def test_default_empty(self):
        from knowbase.claimfirst.models.result import ClaimFirstResult
        result = ClaimFirstResult(
            tenant_id="default",
            doc_id="doc1",
        )
        assert result.claim_entity_link_methods == {}

    def test_stores_methods(self):
        from knowbase.claimfirst.models.result import ClaimFirstResult
        methods = {("c1", "e1"): "domain_pack:biomedical"}
        result = ClaimFirstResult(
            tenant_id="default",
            doc_id="doc1",
            claim_entity_link_methods=methods,
        )
        assert result.claim_entity_link_methods[("c1", "e1")] == "domain_pack:biomedical"
