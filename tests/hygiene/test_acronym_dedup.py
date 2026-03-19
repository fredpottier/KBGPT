"""Tests Acronym Concept Dedup — AcronymMapBuilder + AcronymDedupRule."""

import pytest
from unittest.mock import MagicMock, patch

from knowbase.hygiene.acronym_map import (
    FULL_NAME_THEN_ACRONYM,
    ACRONYM_THEN_FULL_NAME,
    NOISE_PARENS,
    AcronymEntry,
    AcronymMapBuilder,
    _is_plausible_acronym,
    _is_plausible_expansion,
    _normalize_expansion,
)
from knowbase.hygiene.rules.acronym_dedup import (
    AcronymCluster,
    AcronymDedupRule,
    _source_type,
)
from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
)


# ═══════════════════════════════════════════════════════════════════════
# REGEX TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestFullNameThenAcronym:
    """Tests pour le pattern 'NomComplet (ACRONYME)'."""

    @pytest.mark.parametrize("text,expansion,acronym", [
        ("Procalcitonin (PCT)", "Procalcitonin", "PCT"),
        ("C-Reactive Protein (CRP)", "C-Reactive Protein", "CRP"),
        ("Fecal Microbiota Transplantation (FMT)", "Fecal Microbiota Transplantation", "FMT"),
        ("Business Technology Platform (BTP)", "Business Technology Platform", "BTP"),
        ("General Data Protection Regulation (GDPR)", "General Data Protection Regulation", "GDPR"),
        ("SAP Analytics Cloud (SAC)", "SAP Analytics Cloud", "SAC"),
        ("CRISPR-Cas9 (CC9)", "CRISPR-Cas9", "CC9"),
        ("Intensive Care Unit (ICU)", "Intensive Care Unit", "ICU"),
    ])
    def test_matches(self, text, expansion, acronym):
        m = FULL_NAME_THEN_ACRONYM.match(text)
        assert m is not None
        assert m.group(1).strip() == expansion
        assert m.group(2).strip() == acronym

    @pytest.mark.parametrize("text", [
        "PCT",                      # pas de parenthèses
        "(PCT)",                    # pas d'expansion
        "AB (x)",                   # expansion trop courte
        "Test (ab)",                # acronyme minuscule
        "A (PCT)",                  # expansion <3 chars
    ])
    def test_no_match(self, text):
        assert FULL_NAME_THEN_ACRONYM.match(text) is None


class TestAcronymThenFullName:
    """Tests pour le pattern 'ACRONYME (NomComplet)'."""

    @pytest.mark.parametrize("text,acronym,expansion", [
        ("PCT (Procalcitonin)", "PCT", "Procalcitonin"),
        ("CRP (C-Reactive Protein)", "CRP", "C-Reactive Protein"),
        ("BTP (Business Technology Platform)", "BTP", "Business Technology Platform"),
    ])
    def test_matches(self, text, acronym, expansion):
        m = ACRONYM_THEN_FULL_NAME.match(text)
        assert m is not None
        assert m.group(1).strip() == acronym
        assert m.group(2).strip() == expansion

    @pytest.mark.parametrize("text", [
        "pct (Procalcitonin)",      # acronyme minuscule
        "P (Procalcitonin)",        # acronyme trop court
    ])
    def test_no_match(self, text):
        assert ACRONYM_THEN_FULL_NAME.match(text) is None


class TestNoiseParens:
    """Tests pour le filtre de bruit dans les parenthèses."""

    @pytest.mark.parametrize("text", [
        "(mg/L)",
        "(n=42)",
        "(p<0.05)",
        "(95%)",
        "(Fig. 3)",
        "(Table 1)",
        "(see above)",
        "(e.g.)",
        "(i.e.)",
        "(ref. 12)",
        "(cf.)",
        "(2010-2020)",
    ])
    def test_noise_detected(self, text):
        assert NOISE_PARENS.match(text) is not None

    @pytest.mark.parametrize("text", [
        "(PCT)",
        "(CRP)",
        "(GDPR)",
    ])
    def test_not_noise(self, text):
        assert NOISE_PARENS.match(text) is None


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


class TestPlausibility:
    """Tests pour les fonctions de validation."""

    @pytest.mark.parametrize("text,expected", [
        ("PCT", True),
        ("CRP", True),
        ("GDPR", True),
        ("BTP", True),
        ("CC9", True),
        ("A", False),               # trop court
        ("pct", False),             # minuscule
        ("ABCDEFGHIJKL", False),    # trop long
        ("123", False),             # chiffres seuls
    ])
    def test_is_plausible_acronym(self, text, expected):
        assert _is_plausible_acronym(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("Procalcitonin", True),
        ("C-Reactive Protein", True),
        ("AB", False),              # trop court
        ("x" * 61, False),          # trop long
        ("123", False),             # pas assez de lettres
    ])
    def test_is_plausible_expansion(self, text, expected):
        assert _is_plausible_expansion(text) == expected


class TestSourceType:
    """Tests pour _source_type."""

    def test_entity(self):
        assert _source_type("entity:Procalcitonin (PCT)") == "entity_name"

    def test_claim(self):
        assert _source_type("claim:PCT (Procalcitonin)") == "claim_text"

    def test_domain_context(self):
        assert _source_type("domain_context:PCT=Procalcitonin") == "domain_context"

    def test_unknown(self):
        assert _source_type("something") == "unknown"


# ═══════════════════════════════════════════════════════════════════════
# ACRONYM MAP BUILDER
# ═══════════════════════════════════════════════════════════════════════


def _mock_neo4j_driver(entity_names=None, claim_texts=None, acronyms_dict=None):
    """Crée un mock Neo4j driver pour les tests AcronymMapBuilder."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    def mock_run(query, **kwargs):
        result = MagicMock()

        if "Entity" in query and "CONTAINS '('" in query:
            records = [_DictRecord(name=n) for n in (entity_names or [])]
            result.__iter__ = MagicMock(return_value=iter(records))
            return result

        if "Claim" in query and "CONTAINS '('" in query:
            records = [_DictRecord(text=t) for t in (claim_texts or [])]
            result.__iter__ = MagicMock(return_value=iter(records))
            return result

        if "DomainContextProfile" in query:
            import json
            if acronyms_dict:
                rec = _DictRecord(acronyms=json.dumps(acronyms_dict))
                result.single.return_value = rec
            else:
                result.single.return_value = None
            return result

        # Default
        result.__iter__ = MagicMock(return_value=iter([]))
        result.single.return_value = None
        return result

    session.run = mock_run
    return driver


class TestAcronymMapBuilder:
    """Tests pour AcronymMapBuilder."""

    def test_entity_name_source(self):
        driver = _mock_neo4j_driver(entity_names=["Procalcitonin (PCT)"])
        builder = AcronymMapBuilder()
        result = builder.build(driver, "default")

        assert "PCT" in result
        entry = result["PCT"]
        assert entry.primary_expansion == "Procalcitonin"
        assert entry.confidence == 1.0
        assert not entry.ambiguous

    def test_multiple_entities(self):
        driver = _mock_neo4j_driver(
            entity_names=[
                "Procalcitonin (PCT)",
                "C-Reactive Protein (CRP)",
                "Fecal Microbiota Transplantation (FMT)",
            ]
        )
        builder = AcronymMapBuilder()
        result = builder.build(driver, "default")

        assert len(result) == 3
        assert "PCT" in result
        assert "CRP" in result
        assert "FMT" in result

    def test_domain_context_source(self):
        driver = _mock_neo4j_driver(
            acronyms_dict={"BTP": "Business Technology Platform"}
        )
        builder = AcronymMapBuilder()
        result = builder.build(driver, "default")

        assert "BTP" in result
        assert result["BTP"].primary_expansion == "Business Technology Platform"
        assert result["BTP"].confidence == 0.9

    def test_multi_source_boost(self):
        """Corpus + DomainContext → confidence = 1.0."""
        driver = _mock_neo4j_driver(
            entity_names=["Procalcitonin (PCT)"],
            acronyms_dict={"PCT": "Procalcitonin"},
        )
        builder = AcronymMapBuilder()
        result = builder.build(driver, "default")

        assert "PCT" in result
        assert result["PCT"].confidence == 1.0
        assert len(result["PCT"].sources) == 2

    def test_ambiguous_acronym(self):
        """Un acronyme avec 2 expansions différentes → ambiguous=True."""
        driver = _mock_neo4j_driver(
            entity_names=[
                "Polymerase Chain Reaction (PCR)",
            ],
            acronyms_dict={"PCR": "Patient Clinical Record"},
        )
        builder = AcronymMapBuilder()
        result = builder.build(driver, "default")

        assert "PCR" in result
        assert result["PCR"].ambiguous is True

    def test_noise_filtered(self):
        """Les parenthèses avec unités/refs ne génèrent pas d'entrées."""
        driver = _mock_neo4j_driver(
            entity_names=["Some Value (mg/L)"]
        )
        builder = AcronymMapBuilder()
        result = builder.build(driver, "default")

        # "mg/L" ne matche pas _is_plausible_acronym (minuscule)
        assert len(result) == 0

    def test_claim_text_inline(self):
        """Extraction inline depuis claim text."""
        driver = _mock_neo4j_driver(
            claim_texts=[
                "Procalcitonin (PCT) levels were measured."
            ]
        )
        builder = AcronymMapBuilder()
        result = builder.build(driver, "default")

        assert "PCT" in result
        assert "Procalcitonin" in result["PCT"].primary_expansion
        assert result["PCT"].confidence == 0.8

    def test_empty_corpus(self):
        driver = _mock_neo4j_driver()
        builder = AcronymMapBuilder()
        result = builder.build(driver, "default")
        assert len(result) == 0

    def test_same_expansion_dedup(self):
        """Même acronyme dans entity et claim → pas de doublon d'expansion."""
        driver = _mock_neo4j_driver(
            entity_names=["Procalcitonin (PCT)"],
            claim_texts=["Procalcitonin (PCT) was used."],
        )
        builder = AcronymMapBuilder()
        result = builder.build(driver, "default")

        assert "PCT" in result
        assert len(result["PCT"].expansions) == 1
        assert len(result["PCT"].sources) == 2


# ═══════════════════════════════════════════════════════════════════════
# ACRONYM DEDUP RULE
# ═══════════════════════════════════════════════════════════════════════


class _DictRecord(dict):
    """Record qui se comporte comme un dict ET supporte r['key'] et dict(r)."""
    pass


def _mock_driver_for_rule(
    entities=None,
    canonicals=None,
    links=None,
    entity_names=None,
    claim_texts=None,
    acronyms_dict=None,
):
    """Mock driver pour AcronymDedupRule.scan()."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    entities = entities or []
    canonicals = canonicals or []
    links = links or []
    entity_names_for_map = entity_names or []
    claim_texts_for_map = claim_texts or []

    def mock_run(query, **kwargs):
        result = MagicMock()

        # AcronymMapBuilder queries — entity names (has CONTAINS '(')
        if "Entity" in query and "CONTAINS '('" in query:
            records = [_DictRecord(name=n) for n in entity_names_for_map]
            result.__iter__ = MagicMock(return_value=iter(records))
            return result

        # AcronymMapBuilder queries — claim texts
        if "Claim" in query and "CONTAINS '('" in query:
            records = [_DictRecord(text=t) for t in claim_texts_for_map]
            result.__iter__ = MagicMock(return_value=iter(records))
            return result

        if "DomainContextProfile" in query:
            import json
            if acronyms_dict:
                rec = _DictRecord(acronyms=json.dumps(acronyms_dict))
                result.single.return_value = rec
            else:
                result.single.return_value = None
            return result

        # AcronymDedupRule — load entities (no CONTAINS, has entity_id + normalized_name)
        if "Entity" in query and "_hygiene_status IS NULL" in query and "normalized_name" in query:
            records = [_DictRecord(e) for e in entities]
            result.__iter__ = MagicMock(return_value=iter(records))
            return result

        # AcronymDedupRule — load canonicals
        if "CanonicalEntity" in query and "canonical_entity_id" in query and "_hygiene_status IS NULL" in query:
            records = [_DictRecord(ce) for ce in canonicals]
            result.__iter__ = MagicMock(return_value=iter(records))
            return result

        # AcronymDedupRule — load existing SAME_CANON_AS links
        if "SAME_CANON_AS" in query:
            records = [_DictRecord(eid=eid, ceid=ceid) for eid, ceid in links]
            result.__iter__ = MagicMock(return_value=iter(records))
            return result

        # Default
        result.__iter__ = MagicMock(return_value=iter([]))
        result.single.return_value = None
        return result

    session.run = mock_run
    return driver


class TestAcronymDedupRule:
    """Tests pour AcronymDedupRule."""

    def test_basic_cluster_merge(self):
        """PCT + Procalcitonin + Procalcitonin (PCT) → 2 MERGE_CANONICAL auto-applied."""
        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct", "entity_type": "concept"},
            {"entity_id": "e2", "name": "Procalcitonin", "normalized_name": "procalcitonin", "entity_type": "concept"},
            {"entity_id": "e3", "name": "Procalcitonin (PCT)", "normalized_name": "procalcitonin pct", "entity_type": "concept"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            entity_names=["Procalcitonin (PCT)"],
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")

        assert len(actions) == 2
        assert all(a.action_type == HygieneActionType.MERGE_CANONICAL for a in actions)
        # Entity name source → confidence=1.0 → auto-applied
        assert all(a.status == HygieneActionStatus.APPLIED for a in actions)
        assert all(a.decision_source == "rule_auto_apply" for a in actions)

        # Vérifier que l'expansion pure (Procalcitonin) n'est pas la cible du merge
        target_ids = {a.target_node_id for a in actions}
        assert "e2" not in target_ids  # expansion pure = canonical source

    def test_no_merge_single_entity(self):
        """Un seul entity pour l'acronyme → pas de merge."""
        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct", "entity_type": "concept"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            entity_names=["Procalcitonin (PCT)"],
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")
        assert len(actions) == 0

    def test_ambiguous_no_merge(self):
        """Acronyme ambigu → pas de merge."""
        entities = [
            {"entity_id": "e1", "name": "CAR", "normalized_name": "car", "entity_type": "concept"},
            {"entity_id": "e2", "name": "Chimeric Antigen Receptor", "normalized_name": "chimeric antigen receptor", "entity_type": "concept"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            entity_names=["Chimeric Antigen Receptor (CAR)"],
            acronyms_dict={"CAR": "Computer Assisted Radiology"},
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")
        assert len(actions) == 0

    def test_idempotence_skip_existing_links(self):
        """Entité déjà liée au canonical → skip."""
        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct", "entity_type": "concept"},
            {"entity_id": "e2", "name": "Procalcitonin", "normalized_name": "procalcitonin", "entity_type": "concept"},
        ]
        # e1 déjà lié au canonical
        from knowbase.claimfirst.models.canonical_entity import CanonicalEntity
        ce_id = CanonicalEntity.make_id("default", "Procalcitonin")
        links = [("e1", ce_id)]

        driver = _mock_driver_for_rule(
            entities=entities,
            entity_names=["Procalcitonin (PCT)"],
            links=links,
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")
        assert len(actions) == 0

    def test_after_state_trace(self):
        """Vérifie la tracabilité dans after_state."""
        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct", "entity_type": "concept"},
            {"entity_id": "e2", "name": "Procalcitonin", "normalized_name": "procalcitonin", "entity_type": "concept"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            entity_names=["Procalcitonin (PCT)"],
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")

        assert len(actions) == 1
        a = actions[0]
        assert a.status == HygieneActionStatus.APPLIED
        assert a.after_state["canonical_name"] == "Procalcitonin"
        assert a.after_state["acronym"] == "PCT"
        assert "merge_target_id" in a.after_state
        assert "evidence_span" in a.after_state
        assert "all_sources" in a.after_state
        assert a.after_state["resolution_source_type"] == "entity_name"

    def test_existing_canonical_reused(self):
        """Si un CanonicalEntity existe déjà pour l'expansion → l'utiliser."""
        from knowbase.claimfirst.models.canonical_entity import CanonicalEntity
        ce_id = CanonicalEntity.make_id("default", "Procalcitonin")

        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct", "entity_type": "concept"},
            {"entity_id": "e2", "name": "Procalcitonin", "normalized_name": "procalcitonin", "entity_type": "concept"},
        ]
        canonicals = [
            {"canonical_entity_id": ce_id, "canonical_name": "Procalcitonin", "entity_type": "concept"},
        ]
        # e2 déjà lié au canonical
        links = [("e2", ce_id)]

        driver = _mock_driver_for_rule(
            entities=entities,
            canonicals=canonicals,
            links=links,
            entity_names=["Procalcitonin (PCT)"],
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")

        assert len(actions) == 1
        assert actions[0].target_node_id == "e1"
        assert actions[0].after_state["merge_target_id"] == ce_id

    def test_domain_context_only(self):
        """Merge depuis DomainContext seul."""
        entities = [
            {"entity_id": "e1", "name": "BTP", "normalized_name": "btp", "entity_type": "product"},
            {"entity_id": "e2", "name": "Business Technology Platform", "normalized_name": "business technology platform", "entity_type": "product"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            acronyms_dict={"BTP": "Business Technology Platform"},
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")

        assert len(actions) == 1
        assert actions[0].after_state["resolution_source_type"] == "domain_context"

    def test_variants_not_merged(self):
        """'PCT level' n'est pas fusionné (variante, hors scope N1)."""
        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct", "entity_type": "concept"},
            {"entity_id": "e2", "name": "Procalcitonin", "normalized_name": "procalcitonin", "entity_type": "concept"},
            {"entity_id": "e3", "name": "PCT level", "normalized_name": "pct level", "entity_type": "concept"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            entity_names=["Procalcitonin (PCT)"],
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")

        # Seul e1 (PCT pur) doit être mergé
        merged_ids = {a.target_node_id for a in actions}
        assert "e1" in merged_ids
        assert "e3" not in merged_ids  # variante, pas merge

    def test_impact_not_match_pct(self):
        """'IMPACT' ne doit pas matcher avec 'PCT'."""
        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct", "entity_type": "concept"},
            {"entity_id": "e2", "name": "Procalcitonin", "normalized_name": "procalcitonin", "entity_type": "concept"},
            {"entity_id": "e4", "name": "IMPACT", "normalized_name": "impact", "entity_type": "concept"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            entity_names=["Procalcitonin (PCT)"],
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")

        merged_ids = {a.target_node_id for a in actions}
        assert "e4" not in merged_ids

    def test_auto_apply_entity_source(self):
        """Entity name source (confidence=1.0) → auto-applied par défaut."""
        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct", "entity_type": "concept"},
            {"entity_id": "e2", "name": "Procalcitonin", "normalized_name": "procalcitonin", "entity_type": "concept"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            entity_names=["Procalcitonin (PCT)"],
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")

        assert len(actions) == 1
        assert actions[0].status == HygieneActionStatus.APPLIED
        assert actions[0].decision_source == "rule_auto_apply"

    def test_auto_apply_domain_context(self):
        """Domain context source (confidence=0.9) → auto-applied par défaut (seuil=0.8)."""
        entities = [
            {"entity_id": "e1", "name": "BTP", "normalized_name": "btp", "entity_type": "product"},
            {"entity_id": "e2", "name": "Business Technology Platform", "normalized_name": "business technology platform", "entity_type": "product"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            acronyms_dict={"BTP": "Business Technology Platform"},
        )

        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")

        assert len(actions) == 1
        assert actions[0].status == HygieneActionStatus.APPLIED

    def test_proposed_when_below_threshold(self):
        """Confidence sous le seuil → PROPOSED (review admin)."""
        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct", "entity_type": "concept"},
            {"entity_id": "e2", "name": "Procalcitonin", "normalized_name": "procalcitonin", "entity_type": "concept"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            entity_names=["Procalcitonin (PCT)"],
        )

        rule = AcronymDedupRule()
        # Seuil très élevé → force PROPOSED
        actions = rule.scan(
            driver, "default", "batch1", "tenant",
            auto_apply_threshold=1.5,
        )

        assert len(actions) == 1
        assert actions[0].status == HygieneActionStatus.PROPOSED
        assert actions[0].decision_source == "rule"

    def test_custom_threshold(self):
        """Seuil personnalisé à 0.95 → domain context seul (0.9) = PROPOSED."""
        entities = [
            {"entity_id": "e1", "name": "BTP", "normalized_name": "btp", "entity_type": "product"},
            {"entity_id": "e2", "name": "Business Technology Platform", "normalized_name": "business technology platform", "entity_type": "product"},
        ]
        driver = _mock_driver_for_rule(
            entities=entities,
            acronyms_dict={"BTP": "Business Technology Platform"},
        )

        rule = AcronymDedupRule()
        actions = rule.scan(
            driver, "default", "batch1", "tenant",
            auto_apply_threshold=0.95,
        )

        assert len(actions) == 1
        assert actions[0].status == HygieneActionStatus.PROPOSED

    def test_rule_properties(self):
        rule = AcronymDedupRule()
        assert rule.name == "acronym_dedup"
        assert rule.layer == 2
        assert rule.description != ""

    def test_empty_graph(self):
        driver = _mock_driver_for_rule()
        rule = AcronymDedupRule()
        actions = rule.scan(driver, "default", "batch1", "tenant")
        assert len(actions) == 0


# ═══════════════════════════════════════════════════════════════════════
# FIND CLUSTER UNIT TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestFindCluster:
    """Tests unitaires pour _find_cluster."""

    def _make_entry(self, acronym="PCT", expansion="Procalcitonin"):
        return AcronymEntry(
            acronym=acronym,
            expansions=[expansion],
            sources=[f"entity:{expansion} ({acronym})"],
            confidence=1.0,
        )

    def test_core_includes_acronym_and_expansion(self):
        rule = AcronymDedupRule()
        entry = self._make_entry()
        entities = [
            {"entity_id": "e1", "name": "PCT", "normalized_name": "pct"},
            {"entity_id": "e2", "name": "Procalcitonin", "normalized_name": "procalcitonin"},
        ]

        cluster = rule._find_cluster(entry, entities)
        assert len(cluster.core) == 2
        match_types = {mt for _, mt in cluster.core}
        assert "acronym_pure" in match_types
        assert "expansion_pure" in match_types

    def test_composite_in_core(self):
        rule = AcronymDedupRule()
        entry = self._make_entry()
        entities = [
            {"entity_id": "e1", "name": "Procalcitonin (PCT)", "normalized_name": "procalcitonin pct"},
        ]

        cluster = rule._find_cluster(entry, entities)
        assert len(cluster.core) == 1
        assert cluster.core[0][1] == "composite"

    def test_variant_not_in_core(self):
        rule = AcronymDedupRule()
        entry = self._make_entry()
        entities = [
            {"entity_id": "e1", "name": "PCT level", "normalized_name": "pct level"},
            {"entity_id": "e2", "name": "Procalcitonin testing", "normalized_name": "procalcitonin testing"},
        ]

        cluster = rule._find_cluster(entry, entities)
        assert len(cluster.core) == 0
        assert len(cluster.variants) == 2

    def test_no_false_positive_substring(self):
        """Un mot contenant l'acronyme comme sous-chaîne ne doit pas matcher."""
        rule = AcronymDedupRule()
        entry = self._make_entry(acronym="PCT", expansion="Procalcitonin")
        entities = [
            {"entity_id": "e1", "name": "IMPACT Study", "normalized_name": "impact study"},
            {"entity_id": "e2", "name": "Spectrum", "normalized_name": "spectrum"},
        ]

        cluster = rule._find_cluster(entry, entities)
        assert len(cluster.core) == 0
        assert len(cluster.variants) == 0
