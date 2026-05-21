"""Tests unitaires du module Parse — runtime_a3.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.1 + §3.1 + §3.1.1.

Stratégie :
    - Mock LLM via injection d'un client custom (`Parser(llm_client=...)`)
    - Couvrir : Pydantic validation, parsing JSON, fallback déterministe, troncature
    - 30 cas variés (factual, lifecycle, comparison, listing, unanswerable, false_premise)
    - Vérifier domain-agnostic : few-shot examples ne doivent pas contenir de tokens
      SAP / aerospace / médical / légal
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from knowbase.runtime_a3.parse import (
    Parser,
    parse,
    _build_system_prompt,
    _load_examples,
    _detect_language_naive,
    MAX_QUESTION_CHARS,
)
from knowbase.runtime_a3.schemas import (
    ParseInput,
    ParseOutput,
    SubGoal,
    ParseValidationError,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_mock_llm(response_json_str: str):
    """Crée un mock LLM client qui retourne le JSON donné."""
    client = MagicMock()
    client.complete.return_value = response_json_str
    return client


def _valid_response(
    sub_goals=None,
    entities=None,
    language="en",
    raw_question="test question",
    parse_confidence=0.9,
    parse_warnings=None,
):
    """Construit un JSON ParseOutput valide pour mocks."""
    return json.dumps({
        "sub_goals": sub_goals if sub_goals is not None else [{
            "kind": "fact_lookup",
            "subject_canonical": "test",
            "predicate_hint": "value",
            "object_hint": None,
            "expected_value_kind": "string",
            "time_filter": "current",
            "priority": 1,
        }],
        "entities": entities if entities is not None else ["test"],
        "language": language,
        "raw_question": raw_question,
        "parse_confidence": parse_confidence,
        "parse_warnings": parse_warnings if parse_warnings is not None else [],
        "schema_version": "a3.0",
    })


# ============================================================================
# Schémas Pydantic (validation directe)
# ============================================================================


class TestSchemas:
    def test_subgoal_minimal(self):
        sg = SubGoal(kind="fact_lookup")
        assert sg.kind == "fact_lookup"
        assert sg.subject_canonical is None
        assert sg.priority == 1
        assert sg.time_filter == "current"

    def test_subgoal_full(self):
        sg = SubGoal(
            kind="lifecycle_trace",
            subject_canonical="entity_x",
            predicate_hint="released_at",
            object_hint=None,
            expected_value_kind="date",
            time_filter="evolution",
            priority=2,
        )
        assert sg.kind == "lifecycle_trace"
        assert sg.priority == 2

    def test_subgoal_invalid_kind_rejected(self):
        with pytest.raises(Exception):
            SubGoal(kind="bogus_kind")

    def test_parseoutput_min(self):
        po = ParseOutput(
            sub_goals=[],
            entities=[],
            language="en",
            raw_question="?",
            parse_confidence=0.1,
        )
        assert po.schema_version == "a3.0"
        assert po.sub_goals == []

    def test_parseoutput_max_5_subgoals(self):
        with pytest.raises(Exception):
            ParseOutput(
                sub_goals=[SubGoal(kind="fact_lookup") for _ in range(6)],
                entities=[],
                language="en",
                raw_question="?",
                parse_confidence=0.5,
            )

    def test_parseoutput_confidence_bounds(self):
        with pytest.raises(Exception):
            ParseOutput(
                sub_goals=[],
                entities=[],
                language="en",
                raw_question="?",
                parse_confidence=1.5,
            )


# ============================================================================
# Few-shot examples
# ============================================================================


class TestFewShotExamples:
    def test_examples_load(self):
        examples = _load_examples()
        assert len(examples) >= 5
        for ex in examples:
            assert "question" in ex
            assert "expected" in ex

    def test_examples_validate_against_schema(self):
        """Chaque example.expected DOIT valider ParseOutput."""
        examples = _load_examples()
        for i, ex in enumerate(examples):
            try:
                ParseOutput.model_validate(ex["expected"])
            except Exception as e:
                pytest.fail(f"Example {i} failed validation: {e}")

    def test_examples_domain_agnostic(self):
        """Charte stricte — aucun token SAP/aerospace/médical/légal dans les examples."""
        examples = _load_examples()
        text = json.dumps(examples, ensure_ascii=False).lower()
        forbidden = ["sap", "s/4hana", "s4hana", "rise", "fiori", "hana ",
                     "aerospace", "ehs", "etops",
                     "icd-10", "icd10", "rcp", "fda",
                     "gdpr", "eu 2021"]
        for token in forbidden:
            assert token not in text, (
                f"Token domain-specific '{token}' trouvé dans parse_examples.json — "
                f"violation charte agnostique"
            )


# ============================================================================
# System prompt construction
# ============================================================================


class TestSystemPrompt:
    def test_system_prompt_contains_schema(self):
        prompt = _build_system_prompt()
        assert "sub_goals" in prompt
        assert "fact_lookup" in prompt
        assert "lifecycle_trace" in prompt
        assert "MAXIMUM 5 sub_goals" in prompt

    def test_system_prompt_contains_examples_section(self):
        prompt = _build_system_prompt()
        assert "## EXAMPLES" in prompt
        assert "### Example 1" in prompt
        assert "### Example 5" in prompt  # on a au moins 5 examples

    def test_system_prompt_cached(self):
        """Le system prompt est mémoizé (LRU cache) — 2 appels = même objet."""
        p1 = _build_system_prompt()
        p2 = _build_system_prompt()
        assert p1 is p2  # identité (cache)


# ============================================================================
# Parser — happy path
# ============================================================================


class TestParserHappyPath:
    def test_simple_factual(self):
        llm = _make_mock_llm(_valid_response(
            sub_goals=[{
                "kind": "fact_lookup",
                "subject_canonical": "product alpha",
                "predicate_hint": "max users",
                "object_hint": None,
                "expected_value_kind": "number",
                "time_filter": "current",
                "priority": 1,
            }],
            entities=["product alpha"],
            language="en",
            raw_question="What is max users for product alpha?",
            parse_confidence=0.92,
        ))
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(
            question="What is max users for product alpha?",
            tenant_id="default",
        ))
        assert isinstance(result, ParseOutput)
        assert len(result.sub_goals) == 1
        assert result.sub_goals[0].kind == "fact_lookup"
        assert result.parse_confidence == 0.92

    def test_lifecycle_trace(self):
        llm = _make_mock_llm(_valid_response(
            sub_goals=[{
                "kind": "lifecycle_trace",
                "subject_canonical": "module beta",
                "predicate_hint": "license strategy",
                "object_hint": None,
                "expected_value_kind": "string",
                "time_filter": "evolution",
                "priority": 1,
            }],
            language="fr",
        ))
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question="évolution licence module beta", tenant_id="default"))
        assert result.sub_goals[0].kind == "lifecycle_trace"
        assert result.sub_goals[0].time_filter == "evolution"

    def test_comparison_two_subgoals(self):
        llm = _make_mock_llm(_valid_response(
            sub_goals=[
                {"kind": "comparison", "subject_canonical": "x", "predicate_hint": "p", "object_hint": None,
                 "expected_value_kind": "string", "time_filter": "current", "priority": 1},
                {"kind": "comparison", "subject_canonical": "y", "predicate_hint": "p", "object_hint": None,
                 "expected_value_kind": "string", "time_filter": "current", "priority": 1},
            ],
        ))
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question="compare X vs Y", tenant_id="default"))
        assert len(result.sub_goals) == 2

    def test_unanswerable(self):
        llm = _make_mock_llm(_valid_response(
            sub_goals=[],
            entities=[],
            parse_confidence=0.15,
            parse_warnings=["out_of_scope_for_corpus"],
        ))
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question="What's the weather?", tenant_id="default"))
        assert result.sub_goals == []
        assert result.parse_confidence < 0.3
        assert "out_of_scope_for_corpus" in result.parse_warnings


# ============================================================================
# Parser — JSON fences tolérance
# ============================================================================


class TestParserMarkdownFences:
    def test_strips_markdown_fences(self):
        wrapped = "```json\n" + _valid_response() + "\n```"
        llm = _make_mock_llm(wrapped)
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question="test", tenant_id="default"))
        assert isinstance(result, ParseOutput)

    def test_strips_unfenced_markdown(self):
        wrapped = "```\n" + _valid_response() + "\n```"
        llm = _make_mock_llm(wrapped)
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question="test", tenant_id="default"))
        assert isinstance(result, ParseOutput)


# ============================================================================
# Parser — raw_question forcée
# ============================================================================


class TestParserRawQuestion:
    def test_raw_question_forced_to_original(self):
        """Si LLM paraphrase raw_question, on force la valeur originale."""
        llm = _make_mock_llm(_valid_response(raw_question="LLM paraphrase"))
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(
            question="Original question text",
            tenant_id="default",
        ))
        assert result.raw_question == "Original question text"


# ============================================================================
# Parser — retry + fallback
# ============================================================================


class TestParserRetry:
    def test_retry_on_invalid_json_then_success(self):
        llm = MagicMock()
        llm.complete.side_effect = [
            "not valid json {{{",     # 1er attempt fail
            _valid_response(),         # 2ème succès
        ]
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question="test", tenant_id="default"))
        assert isinstance(result, ParseOutput)
        assert llm.complete.call_count == 2

    def test_fallback_on_two_invalid_jsons(self):
        llm = MagicMock()
        llm.complete.side_effect = ["bogus1", "bogus2"]
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question="test", tenant_id="default"))
        # Fallback déterministe → parse_confidence=0.3 + warning
        assert result.parse_confidence == 0.3
        assert "parse_llm_failed_fallback_deterministic_used" in result.parse_warnings
        assert len(result.sub_goals) == 1
        assert result.sub_goals[0].kind == "fact_lookup"

    def test_fallback_on_pydantic_validation_failures(self):
        # 2 réponses qui sont du JSON valide mais ne matchent pas ParseOutput
        bad = json.dumps({"sub_goals": "not a list"})  # schema fail
        llm = MagicMock()
        llm.complete.side_effect = [bad, bad]
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question="test", tenant_id="default"))
        assert result.parse_confidence == 0.3


# ============================================================================
# Parser — troncature question longue
# ============================================================================


class TestParserTruncation:
    def test_long_question_truncated_with_warning(self):
        long_question = "X " * (MAX_QUESTION_CHARS + 100)  # > 5000 chars
        llm = _make_mock_llm(_valid_response(
            raw_question="should be overwritten",
        ))
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question=long_question, tenant_id="default"))
        assert "question_truncated" in result.parse_warnings
        # raw_question reste la question ORIGINALE (pas tronquée)
        assert result.raw_question == long_question

    def test_short_question_no_truncation(self):
        llm = _make_mock_llm(_valid_response())
        parser = Parser(llm_client=llm)
        result = parser.parse(ParseInput(question="short question", tenant_id="default"))
        assert "question_truncated" not in result.parse_warnings


# ============================================================================
# Detect language naive
# ============================================================================


class TestDetectLanguage:
    def test_french(self):
        assert _detect_language_naive("Quelle est la version du produit ?") == "fr"

    def test_english(self):
        assert _detect_language_naive("What is the version of the product?") == "en"

    def test_other_when_no_markers(self):
        # texte sans marker FR ni EN
        assert _detect_language_naive("123456 ABC") == "other"


# ============================================================================
# API top-level parse()
# ============================================================================


class TestTopLevelAPI:
    def test_parse_function_works(self):
        llm = _make_mock_llm(_valid_response())
        result = parse(
            ParseInput(question="test", tenant_id="default"),
            llm_client=llm,
        )
        assert isinstance(result, ParseOutput)


# ============================================================================
# Edge cases — 30q variées (smoke tests via parametrize)
# ============================================================================


# Liste de 30 questions variées (factual, lifecycle, comparison, listing, unanswerable,
# false_premise, contradiction_check) — domain-agnostic
SAMPLE_QUESTIONS = [
    # factual (10)
    "What is the maximum capacity of system X?",
    "Quelle version du module Y est utilisée dans le scenario Z ?",
    "When was product alpha released?",
    "Who maintains the open-source project P?",
    "What is the API endpoint for service S?",
    "Quelle est la taille maximum d'un fichier dans la solution A ?",
    "What permissions are required to run procedure P?",
    "Combien de processeurs sont nécessaires pour l'application X ?",
    "What is the default port for service S?",
    "Quelle est la fréquence de rafraîchissement du composant C ?",
    # lifecycle (5)
    "How has product X evolved between version 1.0 and version 3.0?",
    "Évolution de la stratégie de pricing pour solution Y entre 2020 et 2025",
    "What changes were introduced in v2.5 of system Z?",
    "Trace the changes to module M's licensing model over time",
    "Quelles fonctionnalités ont été dépréciées dans la dernière version ?",
    # comparison (4)
    "Compare features of system A vs system B for use case Z",
    "Différences entre approche X et approche Y pour scenario S",
    "Which is more performant: option Alpha or option Beta?",
    "Compare le coût de la solution X et celui de la solution Y",
    # listing (3)
    "List all available modules in product P",
    "Tous les composants supportés par la version 2.0",
    "Énumérer les types de licences disponibles",
    # contradiction_check (3)
    "Are there conflicting requirements between specifications A and B?",
    "Y a-t-il des contradictions sur la configuration recommandée ?",
    "Do documents D1 and D2 agree on the architecture?",
    # unanswerable / out-of-scope (3)
    "What's the weather like in Paris today?",
    "Combien de planètes y a-t-il dans le système solaire ?",
    "What is the meaning of life?",
    # false_premise (2)
    "Why does product X not support feature F (assuming it doesn't)?",
    "Quand product Y a-t-il été retiré du marché (alors qu'il est toujours disponible) ?",
]


@pytest.mark.parametrize("question", SAMPLE_QUESTIONS)
def test_30_questions_with_mock_llm(question):
    """Smoke test : pour chaque question, le parser doit retourner un ParseOutput valide
    quand le LLM mock répond avec un output minimal valide.

    Ne teste pas la qualité sémantique du parsing (ce serait A3.8 bench), juste que
    le pipeline parse() ne crashe pas sur des questions variées.
    """
    llm = _make_mock_llm(_valid_response(raw_question=question))
    result = parse(
        ParseInput(question=question, tenant_id="default"),
        llm_client=llm,
    )
    assert isinstance(result, ParseOutput)
    assert result.raw_question == question
    assert result.schema_version == "a3.0"
