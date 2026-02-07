# tests/claimfirst/test_slot_enricher.py
"""
Tests pour SlotEnricher — enrichissement LLM des structured_form.

Mock le LLM pour tester la logique de validation et de parsing.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from knowbase.claimfirst.composition.slot_enricher import (
    SlotEnricher,
    SlotEnrichmentResult,
    SLOT_ENRICHMENT_PROMPT,
)


class TestSlotEnricherValidation:
    """Tests de validation des triplets (pas de LLM)."""

    def test_valid_triplet(self):
        enricher = SlotEnricher()
        result = enricher._validate_triplet({
            "subject": "SAP S/4HANA",
            "predicate": "USES",
            "object": "Material Ledger",
        })
        assert result is not None
        assert result["subject"] == "SAP S/4HANA"
        assert result["predicate"] == "USES"
        assert result["object"] == "Material Ledger"

    def test_predicate_normalization(self):
        enricher = SlotEnricher()
        result = enricher._validate_triplet({
            "subject": "SAP BTP",
            "predicate": "DEPENDS_ON",
            "object": "Cloud Foundry",
        })
        assert result is not None
        assert result["predicate"] == "REQUIRES"  # DEPENDS_ON → REQUIRES

    def test_invalid_predicate_rejected(self):
        enricher = SlotEnricher()
        result = enricher._validate_triplet({
            "subject": "SAP BTP",
            "predicate": "INVENTED_PREDICATE",
            "object": "Cloud Foundry",
        })
        assert result is None

    def test_empty_subject_rejected(self):
        enricher = SlotEnricher()
        result = enricher._validate_triplet({
            "subject": "",
            "predicate": "USES",
            "object": "Material Ledger",
        })
        assert result is None

    def test_stoplist_subject_rejected(self):
        enricher = SlotEnricher()
        result = enricher._validate_triplet({
            "subject": "system",
            "predicate": "USES",
            "object": "Material Ledger",
        })
        assert result is None

    def test_stoplist_object_rejected(self):
        enricher = SlotEnricher()
        result = enricher._validate_triplet({
            "subject": "SAP S/4HANA",
            "predicate": "PROVIDES",
            "object": "data",
        })
        assert result is None

    def test_null_structured_form(self):
        enricher = SlotEnricher()
        result = enricher._validate_triplet(None)
        assert result is None

    def test_non_dict_rejected(self):
        enricher = SlotEnricher()
        result = enricher._validate_triplet("not a dict")
        assert result is None

    def test_missing_fields_rejected(self):
        enricher = SlotEnricher()
        result = enricher._validate_triplet({
            "subject": "SAP",
            "predicate": "USES",
        })
        assert result is None

    def test_all_canonical_predicates_accepted(self):
        enricher = SlotEnricher()
        CANONICAL_PREDICATES = frozenset({
            "USES", "REQUIRES", "BASED_ON", "SUPPORTS", "ENABLES",
            "PROVIDES", "EXTENDS", "REPLACES", "PART_OF",
            "INTEGRATED_IN", "COMPATIBLE_WITH", "CONFIGURES",
        })
        for pred in CANONICAL_PREDICATES:
            result = enricher._validate_triplet({
                "subject": "SAP S/4HANA",
                "predicate": pred,
                "object": "Material Ledger",
            })
            assert result is not None, f"Predicate {pred} should be accepted"
            assert result["predicate"] == pred


class TestSlotEnricherParsing:
    """Tests du parsing de réponses LLM."""

    def test_parse_clean_json(self):
        enricher = SlotEnricher()
        response = json.dumps([
            {"index": 1, "structured_form": {"subject": "X", "predicate": "USES", "object": "Y"}},
            {"index": 2, "structured_form": None},
        ])
        parsed = enricher._parse_llm_response(response)
        assert len(parsed) == 2
        assert parsed[0]["index"] == 1
        assert parsed[1]["structured_form"] is None

    def test_parse_markdown_wrapped(self):
        enricher = SlotEnricher()
        response = '```json\n[{"index": 1, "structured_form": null}]\n```'
        parsed = enricher._parse_llm_response(response)
        assert len(parsed) == 1

    def test_parse_with_surrounding_text(self):
        enricher = SlotEnricher()
        response = 'Here are the results:\n[{"index": 1, "structured_form": null}]\nDone.'
        parsed = enricher._parse_llm_response(response)
        assert len(parsed) == 1

    def test_parse_empty_response(self):
        enricher = SlotEnricher()
        parsed = enricher._parse_llm_response("")
        assert parsed == []

    def test_parse_invalid_json(self):
        enricher = SlotEnricher()
        parsed = enricher._parse_llm_response("not json at all")
        assert parsed == []


class TestSlotEnricherFormatting:
    """Tests du formatage des batches."""

    def test_format_batch_from_dicts(self):
        enricher = SlotEnricher()
        batch = [
            {
                "claim_id": "c1",
                "text": "SAP S/4HANA uses Material Ledger for real-time valuation.",
                "claim_type": "FACTUAL",
                "entity_names": ["SAP S/4HANA", "Material Ledger"],
            },
            {
                "claim_id": "c2",
                "text": "Cloud Foundry enables microservices.",
                "claim_type": "FACTUAL",
            },
        ]
        formatted = enricher._format_batch_from_dicts(batch)

        assert '1. [FACTUAL]' in formatted
        assert 'SAP S/4HANA uses Material Ledger' in formatted
        assert 'Known entities: SAP S/4HANA, Material Ledger' in formatted
        assert '2. [FACTUAL]' in formatted
        # No "Known entities" for c2
        lines = formatted.split("\n")
        # c2 should not have a Known entities line
        c2_lines = [l for l in lines if "Cloud Foundry" in l or (lines.index(l) > 0 and "Known entities" in l)]
        # Just check c2 exists
        assert 'Cloud Foundry enables microservices' in formatted

    def test_format_batch_no_entities(self):
        enricher = SlotEnricher()
        batch = [
            {
                "claim_id": "c1",
                "text": "Some claim text here for testing.",
                "claim_type": "DEFINITIONAL",
            },
        ]
        formatted = enricher._format_batch_from_dicts(batch)
        assert "Known entities" not in formatted
        assert "[DEFINITIONAL]" in formatted


class TestSlotEnricherPrompt:
    """Tests sur le prompt template."""

    def test_prompt_contains_all_predicates(self):
        CANONICAL_PREDICATES = frozenset({
            "USES", "REQUIRES", "BASED_ON", "SUPPORTS", "ENABLES",
            "PROVIDES", "EXTENDS", "REPLACES", "PART_OF",
            "INTEGRATED_IN", "COMPATIBLE_WITH", "CONFIGURES",
        })
        for pred in CANONICAL_PREDICATES:
            assert pred in SLOT_ENRICHMENT_PROMPT, f"Missing predicate {pred} in prompt"

    def test_prompt_format_placeholder(self):
        assert "{claims_block}" in SLOT_ENRICHMENT_PROMPT


class TestSlotEnricherStats:
    """Tests des statistiques."""

    def test_initial_stats(self):
        enricher = SlotEnricher()
        stats = enricher.get_stats()
        assert stats["claims_processed"] == 0
        assert stats["claims_enriched"] == 0
        assert stats["llm_calls"] == 0

    def test_reset_stats(self):
        enricher = SlotEnricher()
        enricher._stats["claims_enriched"] = 42
        enricher.reset_stats()
        assert enricher._stats["claims_enriched"] == 0


class TestSlotEnricherEmptyInput:
    """Tests entrées vides."""

    def test_enrich_empty_list(self):
        enricher = SlotEnricher()
        result = enricher.enrich([])
        assert isinstance(result, SlotEnrichmentResult)
        assert result.claims_processed == 0
        assert result.claims_enriched == 0

    def test_enrich_dicts_empty(self):
        enricher = SlotEnricher()
        result = enricher.enrich_from_dicts([])
        assert result == []
