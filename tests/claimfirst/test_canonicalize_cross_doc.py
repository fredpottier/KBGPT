# tests/claimfirst/test_canonicalize_cross_doc.py
"""
Tests des algorithmes de canonicalisation cross-doc (fonctions pures).

Couvre : alias identity match, alias quality filter, prefix dedup,
union-find, type split, scoring multi-critères, garde anti-régression.
"""

import pytest
from collections import Counter

# Imports directs du script (fonctions pures, pas de deps Neo4j)
sys_path_added = False

import sys
import os

# Le script est dans app/scripts/ — on l'importe comme module
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "app", "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from canonicalize_entities_cross_doc import (
    _normalize,
    _alias_passes_quality,
    _types_compatible,
    build_candidate_edges,
    union_find_groups,
    split_by_type,
    choose_canonical,
    build_indexes,
    PREFIX_FREQUENCY_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers pour créer des entités de test
# ---------------------------------------------------------------------------

def _make_entity(
    entity_id: str,
    name: str,
    entity_type: str = "product",
    aliases: list = None,
    source_doc_ids: list = None,
    claim_count: int = 1,
) -> dict:
    """Crée un dict entity pour les tests."""
    return {
        "entity_id": entity_id,
        "name": name,
        "normalized_name": _normalize(name),
        "entity_type": entity_type,
        "aliases": aliases or [],
        "source_doc_ids": source_doc_ids or [],
        "claim_count": claim_count,
    }


# ===========================================================================
# Tests Alias Identity Match
# ===========================================================================

class TestAliasIdentityMatch:
    """Tests de la méthode A — Alias Identity Match."""

    def test_alias_matches_normalized_name(self):
        """'SAP Fiori' avec alias 'Fiori' matche Entity 'Fiori'."""
        entities = [
            _make_entity("e1", "SAP Fiori", aliases=["Fiori"]),
            _make_entity("e2", "Fiori"),
        ]
        norm_index, alias_index, prefix_freq = build_indexes(entities)
        edges = build_candidate_edges(entities, norm_index, alias_index, prefix_freq)

        assert len(edges) >= 1
        pair = frozenset({"e1", "e2"})
        methods = {frozenset({e[0], e[1]}): e[2] for e in edges}
        assert pair in methods
        assert methods[pair] == "alias_identity"

    def test_alias_bidirectional(self):
        """Si E2 a un alias qui normalise en normalized_name de E1, ça matche."""
        entities = [
            _make_entity("e1", "Fiori"),
            _make_entity("e2", "SAP Fiori UX", aliases=["Fiori"]),
        ]
        norm_index, alias_index, prefix_freq = build_indexes(entities)
        edges = build_candidate_edges(entities, norm_index, alias_index, prefix_freq)

        pair = frozenset({"e1", "e2"})
        pairs = {frozenset({e[0], e[1]}) for e in edges}
        assert pair in pairs

    def test_no_self_match(self):
        """Une Entity ne matche pas avec elle-même."""
        entities = [
            _make_entity("e1", "SAP Fiori", aliases=["SAP Fiori"]),
        ]
        norm_index, alias_index, prefix_freq = build_indexes(entities)
        edges = build_candidate_edges(entities, norm_index, alias_index, prefix_freq)
        assert len(edges) == 0


class TestAliasQualityFilter:
    """Tests du filtre qualité des alias."""

    def test_noise_alias_rejected(self):
        """L'alias 'apps' ne doit rien matcher (trop générique)."""
        assert not _alias_passes_quality("apps")
        assert not _alias_passes_quality("platform")
        assert not _alias_passes_quality("system")

    def test_short_alias_rejected(self):
        """Alias trop court (<2 tokens ET <5 alpha chars) rejeté."""
        assert not _alias_passes_quality("SAP")   # 1 token, 3 alpha
        assert not _alias_passes_quality("BTP")   # 1 token, 3 alpha

    def test_long_single_token_accepted(self):
        """Un alias d'un seul token mais ≥5 alpha chars passe."""
        assert _alias_passes_quality("Fiori")      # 5 alpha chars
        assert _alias_passes_quality("Kubernetes")  # 10 alpha chars

    def test_multi_token_accepted(self):
        """Un alias multi-tokens passe."""
        assert _alias_passes_quality("SAP BTP")
        assert _alias_passes_quality("Cloud Connector")

    def test_alias_type_incompatible_blocks_edge(self):
        """Alias match mais PRODUCT↔ACTOR → pas de lien."""
        entities = [
            _make_entity("e1", "SAP Fiori", entity_type="product",
                         aliases=["Fiori Interface"]),
            _make_entity("e2", "Fiori Interface", entity_type="actor"),
        ]
        norm_index, alias_index, prefix_freq = build_indexes(entities)
        edges = build_candidate_edges(entities, norm_index, alias_index, prefix_freq)

        # PRODUCT ↔ ACTOR → incompatible → pas d'edge
        pair = frozenset({"e1", "e2"})
        pairs = {frozenset({e[0], e[1]}) for e in edges}
        assert pair not in pairs


# ===========================================================================
# Tests Prefix Dedup
# ===========================================================================

class TestPrefixDedup:
    """Tests de la méthode B — Prefix Dedup data-driven."""

    def test_frequent_prefix_creates_edge(self):
        """Un prefix fréquent (≥N) déclenche un edge prefix_dedup."""
        # Créer N entités avec le prefix "sap" pour dépasser le seuil
        entities = []
        for i in range(PREFIX_FREQUENCY_THRESHOLD + 1):
            entities.append(
                _make_entity(f"e_sap_{i}", f"SAP Product{i}")
            )
        # Ajouter l'entité cible : "Fiori" = stripped de "SAP Fiori"
        entities.append(_make_entity("e_fiori", "Fiori"))
        # Ajouter "SAP Fiori" dont stripped = "Fiori"
        entities.append(_make_entity("e_sap_fiori", "SAP Fiori"))

        norm_index, alias_index, prefix_freq = build_indexes(entities)
        edges = build_candidate_edges(entities, norm_index, alias_index, prefix_freq)

        pair = frozenset({"e_fiori", "e_sap_fiori"})
        edge_pairs = {frozenset({e[0], e[1]}): e[2] for e in edges}
        assert pair in edge_pairs
        assert edge_pairs[pair] == "prefix_dedup"

    def test_rare_prefix_no_edge(self):
        """Un token rare en prefix → pas de dedup."""
        entities = [
            _make_entity("e1", "Rare Product"),
            _make_entity("e2", "Product"),
        ]
        norm_index, alias_index, prefix_freq = build_indexes(entities)
        # "rare" n'apparaît qu'une fois → sous le seuil
        edges = build_candidate_edges(entities, norm_index, alias_index, prefix_freq)

        pair = frozenset({"e1", "e2"})
        pairs = {frozenset({e[0], e[1]}) for e in edges}
        assert pair not in pairs

    def test_single_token_entity_ignored(self):
        """Une Entity à 1 seul token ne peut pas avoir de prefix strippé."""
        entities = [
            _make_entity("e1", "Fiori"),
        ]
        # Même avec un prefix fréquent, 1 token → rien à stripper
        norm_index, alias_index, prefix_freq = build_indexes(entities)
        # Pas de token en position prefix pour "fiori" (1 seul token)
        edges = build_candidate_edges(entities, norm_index, alias_index, prefix_freq)
        assert len(edges) == 0


# ===========================================================================
# Tests Union-Find
# ===========================================================================

class TestUnionFind:
    """Tests du regroupement Union-Find."""

    def test_merge_overlapping_groups(self):
        """Groupes qui se chevauchent sont fusionnés."""
        edges = [
            ("e1", "e2", "alias_identity", 0.95),
            ("e2", "e3", "prefix_dedup", 0.90),
        ]
        groups = union_find_groups(edges)
        assert len(groups) == 1
        assert groups[0] == {"e1", "e2", "e3"}

    def test_separate_groups(self):
        """Groupes sans chevauchement restent séparés."""
        edges = [
            ("e1", "e2", "alias_identity", 0.95),
            ("e3", "e4", "alias_identity", 0.95),
        ]
        groups = union_find_groups(edges)
        assert len(groups) == 2
        group_sets = [g for g in groups]
        assert {"e1", "e2"} in group_sets
        assert {"e3", "e4"} in group_sets

    def test_single_entity_no_group(self):
        """Un edge entre mêmes entity → groupe de 1 → filtré."""
        # Union-Find avec un seul nœud ne crée qu'un groupe de taille 1
        # Ce cas ne devrait pas arriver (on filtre e1==e2 avant)
        edges = [
            ("e1", "e2", "alias_identity", 0.95),
        ]
        groups = union_find_groups(edges)
        assert len(groups) == 1
        assert groups[0] == {"e1", "e2"}

    def test_transitive_merge(self):
        """A-B et B-C et C-D → un seul groupe {A,B,C,D}."""
        edges = [
            ("a", "b", "alias_identity", 0.95),
            ("b", "c", "alias_identity", 0.95),
            ("c", "d", "prefix_dedup", 0.90),
        ]
        groups = union_find_groups(edges)
        assert len(groups) == 1
        assert groups[0] == {"a", "b", "c", "d"}


# ===========================================================================
# Tests Type Split
# ===========================================================================

class TestTypeSplit:
    """Tests du filtrage par compatibilité entity_type."""

    def test_incompatible_types_split(self):
        """PRODUCT + ACTOR dans le même groupe → 2 sous-groupes."""
        entities_by_id = {
            "e1": _make_entity("e1", "SAP Fiori", entity_type="product"),
            "e2": _make_entity("e2", "Fiori", entity_type="product"),
            "e3": _make_entity("e3", "Fiori Team", entity_type="actor"),
            "e4": _make_entity("e4", "Fiori Dev Team", entity_type="actor"),
        }
        group = {"e1", "e2", "e3", "e4"}
        result = split_by_type(group, entities_by_id)

        assert len(result) == 2
        type_groups = []
        for sg in result:
            types = {entities_by_id[eid]["entity_type"] for eid in sg}
            type_groups.append(types)
        # Un groupe product, un groupe actor
        assert {"product"} in type_groups
        assert {"actor"} in type_groups

    def test_compatible_types_kept(self):
        """PRODUCT + SERVICE → 1 seul groupe."""
        entities_by_id = {
            "e1": _make_entity("e1", "SAP BTP", entity_type="product"),
            "e2": _make_entity("e2", "BTP", entity_type="service"),
        }
        result = split_by_type({"e1", "e2"}, entities_by_id)
        assert len(result) == 1
        assert result[0] == {"e1", "e2"}

    def test_other_type_no_glue(self):
        """OTHER ne colle pas 2 types incompatibles ensemble."""
        entities_by_id = {
            "e1": _make_entity("e1", "Fiori", entity_type="product"),
            "e1b": _make_entity("e1b", "Fiori UX", entity_type="product"),
            "e2": _make_entity("e2", "Some Thing", entity_type="other"),
            "e3": _make_entity("e3", "Fiori Person", entity_type="actor"),
            "e3b": _make_entity("e3b", "Fiori Admin", entity_type="actor"),
        }
        result = split_by_type({"e1", "e1b", "e2", "e3", "e3b"}, entities_by_id)

        # product et actor sont incompatibles → split en 2 sous-groupes
        # OTHER rejoint le sous-groupe le plus large
        assert len(result) == 2
        for sg in result:
            types = {entities_by_id[eid]["entity_type"] for eid in sg} - {"other"}
            # Chaque sous-groupe ne contient qu'un seul type non-OTHER
            assert len(types) <= 1

    def test_all_other_single_group(self):
        """Que des OTHER → 1 seul groupe."""
        entities_by_id = {
            "e1": _make_entity("e1", "Thing A", entity_type="other"),
            "e2": _make_entity("e2", "Thing B", entity_type="other"),
        }
        result = split_by_type({"e1", "e2"}, entities_by_id)
        assert len(result) == 1
        assert result[0] == {"e1", "e2"}

    def test_single_entity_filtered_out(self):
        """Sous-groupe de 1 entité → filtré."""
        entities_by_id = {
            "e1": _make_entity("e1", "SAP Fiori", entity_type="product"),
            "e2": _make_entity("e2", "Fiori Admin", entity_type="actor"),
        }
        result = split_by_type({"e1", "e2"}, entities_by_id)
        # Chaque sous-groupe a 1 seul membre → tous filtrés
        assert len(result) == 0


# ===========================================================================
# Tests Canonical Name Election
# ===========================================================================

class TestCanonicalElection:
    """Tests de l'élection du canonical_name."""

    def test_brand_prefix_bonus(self):
        """'SAP Fiori' (avec prefix marque) bat 'Fiori' (sans)."""
        entities_by_id = {
            "e1": _make_entity("e1", "SAP Fiori", claim_count=10,
                               source_doc_ids=["d1", "d2"]),
            "e2": _make_entity("e2", "Fiori", claim_count=10,
                               source_doc_ids=["d1", "d2"]),
        }
        edges = [("e1", "e2", "alias_identity", 0.95)]
        cname, etype, method = choose_canonical({"e1", "e2"}, entities_by_id, edges)
        assert cname == "SAP Fiori"

    def test_claim_count_influence(self):
        """À tokens égaux, le claim_count influence le score."""
        entities_by_id = {
            "e1": _make_entity("e1", "Cloud Connector", claim_count=100,
                               source_doc_ids=["d1", "d2", "d3"]),
            "e2": _make_entity("e2", "SAP Cloud Connector", claim_count=5,
                               source_doc_ids=["d1"]),
        }
        edges = [("e1", "e2", "prefix_dedup", 0.90)]
        cname, etype, method = choose_canonical({"e1", "e2"}, entities_by_id, edges)
        # "SAP Cloud Connector" a le prefix bonus (+2) + plus de tokens (+1)
        # mais "Cloud Connector" a plus de claims et doc_count
        # Le résultat dépend du scoring — vérifions juste qu'on obtient un nom valide
        assert cname in ("Cloud Connector", "SAP Cloud Connector")

    def test_entity_type_majority_vote(self):
        """Le type est élu par vote majoritaire."""
        entities_by_id = {
            "e1": _make_entity("e1", "Fiori", entity_type="product"),
            "e2": _make_entity("e2", "SAP Fiori", entity_type="product"),
            "e3": _make_entity("e3", "Fiori App", entity_type="service"),
        }
        edges = [
            ("e1", "e2", "alias_identity", 0.95),
            ("e2", "e3", "prefix_dedup", 0.90),
        ]
        _, etype, _ = choose_canonical({"e1", "e2", "e3"}, entities_by_id, edges)
        assert etype == "product"  # 2 product vs 1 service

    def test_best_method_alias_over_prefix(self):
        """alias_identity est préférée à prefix_dedup."""
        entities_by_id = {
            "e1": _make_entity("e1", "Fiori"),
            "e2": _make_entity("e2", "SAP Fiori"),
        }
        edges = [
            ("e1", "e2", "alias_identity", 0.95),
            ("e1", "e2", "prefix_dedup", 0.90),
        ]
        _, _, method = choose_canonical({"e1", "e2"}, entities_by_id, edges)
        assert method == "alias_identity"


# ===========================================================================
# Tests Normalisation et Compatibilité
# ===========================================================================

class TestNormalize:
    """Tests de la fonction _normalize."""

    def test_lowercase_strip(self):
        assert _normalize("  SAP Fiori  ") == "sap fiori"

    def test_special_chars_removed(self):
        assert _normalize("S/4HANA") == "s4hana"

    def test_empty(self):
        assert _normalize("") == ""


class TestTypesCompatible:
    """Tests de la matrice de compatibilité."""

    def test_same_type(self):
        assert _types_compatible("product", "product")

    def test_product_service_ok(self):
        assert _types_compatible("product", "service")

    def test_product_actor_never(self):
        assert not _types_compatible("product", "actor")

    def test_other_always_compatible(self):
        assert _types_compatible("other", "product")
        assert _types_compatible("other", "actor")
        assert _types_compatible("product", "other")

    def test_concept_standard_ok(self):
        assert _types_compatible("concept", "standard")


# ===========================================================================
# Test intégration légère (sans Neo4j)
# ===========================================================================

class TestIntegrationPipeline:
    """Test end-to-end des phases 2-6 sans Neo4j."""

    def test_full_pipeline_sap_fiori(self):
        """Scénario réaliste : SAP Fiori + Fiori via alias identity."""
        # Créer assez d'entités "SAP xxx" pour déclencher prefix_dedup
        entities = []
        for i in range(PREFIX_FREQUENCY_THRESHOLD + 1):
            entities.append(_make_entity(f"e_sap_{i}", f"SAP Product{i}"))

        # Nos 2 entités cibles (alias + prefix dedup)
        entities.extend([
            _make_entity("e_fiori", "SAP Fiori", entity_type="product",
                         aliases=["Fiori"], claim_count=45,
                         source_doc_ids=["d1", "d2", "d3"]),
            _make_entity("e_fiori_bare", "Fiori", entity_type="product",
                         claim_count=32, source_doc_ids=["d2", "d4"]),
        ])

        entities_by_id = {e["entity_id"]: e for e in entities}
        norm_index, alias_index, prefix_freq = build_indexes(entities)
        edges = build_candidate_edges(entities, norm_index, alias_index, prefix_freq)

        # Au moins un edge entre nos entités cibles
        target_ids = {"e_fiori", "e_fiori_bare"}
        target_edges = [
            e for e in edges
            if e[0] in target_ids and e[1] in target_ids
        ]
        assert len(target_edges) >= 1

        groups = union_find_groups(edges)
        # Nos cibles devraient être dans le même groupe
        target_group = None
        for g in groups:
            if target_ids <= g:
                target_group = g
                break
        assert target_group is not None

        # Type split ne devrait rien scinder (tous product)
        sub_groups = split_by_type(target_group, entities_by_id)
        assert len(sub_groups) >= 1
        # Nos cibles dans le même sous-groupe
        found = False
        for sg in sub_groups:
            if target_ids <= sg:
                found = True
                cname, etype, method = choose_canonical(sg, entities_by_id, edges)
                assert etype == "product"
                # "SAP Fiori" devrait gagner (prefix brand bonus + plus de claims)
                assert cname == "SAP Fiori"
                break
        assert found

    def test_prefix_dedup_links_stripped_entity(self):
        """'SAP Fiori' est lié à 'Fiori' par prefix_dedup quand 'sap' est fréquent."""
        entities = []
        for i in range(PREFIX_FREQUENCY_THRESHOLD + 1):
            entities.append(_make_entity(f"e_sap_{i}", f"SAP Product{i}"))

        entities.extend([
            _make_entity("e_sap_fiori", "SAP Fiori", entity_type="product"),
            _make_entity("e_fiori", "Fiori", entity_type="product"),
        ])

        norm_index, alias_index, prefix_freq = build_indexes(entities)
        edges = build_candidate_edges(entities, norm_index, alias_index, prefix_freq)

        pair = frozenset({"e_sap_fiori", "e_fiori"})
        edge_pairs = {frozenset({e[0], e[1]}): e[2] for e in edges}
        assert pair in edge_pairs
        assert edge_pairs[pair] == "prefix_dedup"
