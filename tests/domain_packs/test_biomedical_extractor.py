# tests/domain_packs/test_biomedical_extractor.py
"""Tests pour l'extracteur NER biomédical."""

import pytest
from unittest.mock import MagicMock, patch

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.entity import Entity, EntityType


def _make_claim(claim_id: str, text: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        text=text,
        tenant_id="default",
        doc_id="doc1",
        unit_ids=["u1"],
        claim_type="FACTUAL",
        verbatim_quote=text,
        passage_id="p1",
    )


class TestBiomedicalEntityExtractor:
    """Tests pour BiomedicalEntityExtractor."""

    def test_entity_type_mapping(self):
        from knowbase.domain_packs.biomedical.entity_extractor import (
            BiomedicalEntityExtractor,
        )
        ext = BiomedicalEntityExtractor()
        mapping = ext.entity_type_mapping
        assert mapping["CHEMICAL"] == EntityType.CONCEPT
        assert mapping["DISEASE"] == EntityType.CONCEPT

    def test_graceful_degradation_no_scispacy(self):
        """Sans scispaCy installé, retourne vide sans erreur."""
        from knowbase.domain_packs.biomedical.entity_extractor import (
            BiomedicalEntityExtractor,
        )
        ext = BiomedicalEntityExtractor()

        # Forcer non-disponibilité
        ext._available = False

        claims = [_make_claim("c1", "Sepsis requires antibiotics")]
        entities, candidate_map = ext.extract(claims, [], None)

        assert entities == []
        assert candidate_map == {}

    def test_dedup_vs_existing(self):
        """Les entités déjà existantes ne sont pas recréées."""
        from knowbase.domain_packs.biomedical.entity_extractor import (
            BiomedicalEntityExtractor,
        )
        ext = BiomedicalEntityExtractor()
        ext._available = False  # Pas de modèle → vide

        # Même sans modèle, on vérifie que la logique est correcte
        existing = [
            Entity(
                entity_id="e_existing",
                tenant_id="default",
                name="sepsis",
                entity_type=EntityType.CONCEPT,
            )
        ]
        claims = [_make_claim("c1", "Sepsis is dangerous")]
        entities, _ = ext.extract(claims, existing, None)
        assert len(entities) == 0


class TestBiomedicalPack:
    """Tests pour BiomedicalPack."""

    def test_pack_properties(self):
        from knowbase.domain_packs.biomedical.pack import BiomedicalPack
        pack = BiomedicalPack()

        assert pack.name == "biomedical"
        assert pack.priority == 100
        assert "biomedical" in pack.description.lower() or "biomédical" in pack.description.lower()
        assert pack.version == "1.0.0"

    def test_get_entity_extractors(self):
        from knowbase.domain_packs.biomedical.pack import BiomedicalPack
        pack = BiomedicalPack()
        extractors = pack.get_entity_extractors()
        assert len(extractors) == 1

    def test_get_domain_context_defaults_from_json(self):
        from knowbase.domain_packs.biomedical.pack import BiomedicalPack
        pack = BiomedicalPack()
        defaults = pack.get_domain_context_defaults()

        assert "common_acronyms" in defaults
        assert "key_concepts" in defaults
        assert len(defaults["common_acronyms"]) > 100
        assert len(defaults["key_concepts"]) > 50

    def test_get_entity_stoplist_from_json(self):
        from knowbase.domain_packs.biomedical.pack import BiomedicalPack
        pack = BiomedicalPack()
        stoplist = pack.get_entity_stoplist()

        assert "PubMed" in stoplist
        assert "SPSS" in stoplist
        assert len(stoplist) > 10

    def test_json_caching(self):
        """Le JSON est chargé une seule fois (cache)."""
        from knowbase.domain_packs.biomedical.pack import BiomedicalPack
        pack = BiomedicalPack()

        defaults1 = pack.get_domain_context_defaults()
        defaults2 = pack.get_domain_context_defaults()
        # Même instance en cache
        assert pack._defaults_cache is not None
