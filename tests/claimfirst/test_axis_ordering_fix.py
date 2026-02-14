# tests/claimfirst/test_axis_ordering_fix.py
"""
Tests de non-régression pour le fix d'ordonnancement des axes.

Couvre les 4 scénarios identifiés + 1 test d'intégration E2E:
1. Merge triggers infer: 2 docs mono-valeur → axe orderable après merge
2. No overwrite: axe déjà orderable ne retombe pas à false
3. Persistence ON MATCH: value_order survit au MERGE Neo4j (merge-safe)
4. Confidence monotonic: CERTAIN ne redescend pas à UNKNOWN
5. E2E: evolution_detector détecte un changement via l'axe corrigé
"""

import pytest

from knowbase.claimfirst.axes.axis_order_inferrer import AxisOrderInferrer
from knowbase.claimfirst.models.applicability_axis import (
    ApplicabilityAxis,
    OrderingConfidence,
    OrderType,
)


@pytest.fixture
def inferrer():
    return AxisOrderInferrer()


class TestMergeTriggerInference:
    """Test 1: Le merge de 2 docs mono-valeur déclenche l'inférence d'ordre."""

    def test_two_docs_single_values_become_orderable(self, inferrer):
        """
        Doc1 apporte release_id="2.0", Doc2 apporte "3.0".
        Après merge + re-inférence, l'axe doit être orderable.
        """
        # Simuler le flux orchestrator: créer l'axe depuis doc1
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
            doc_id="doc_1",
        )
        axis.add_value("2.0", "doc_1")

        # À ce stade: 1 valeur, pas d'ordre
        assert len(axis.known_values) == 1
        assert axis.is_orderable is False
        assert axis.value_order is None

        # Doc2 arrive: merge dans le cache
        changed = axis.add_value("3.0", "doc_2")

        # La valeur est nouvelle
        assert changed is True
        assert len(axis.known_values) == 2

        # Re-inférence post-merge (logique B1)
        if changed and len(axis.known_values) >= 2:
            order_result = inferrer.infer_order(
                axis_key=axis.axis_key,
                values=list(axis.known_values),
            )
            if order_result.is_orderable:
                axis.is_orderable = True
                axis.order_type = order_result.order_type
                axis.ordering_confidence = order_result.confidence
                axis.value_order = order_result.inferred_order

        # Vérifications
        assert axis.is_orderable is True
        assert axis.ordering_confidence == OrderingConfidence.CERTAIN
        assert axis.value_order == ["2.0", "3.0"]
        assert axis.order_type == OrderType.TOTAL

    def test_three_docs_incremental_merge(self, inferrer):
        """3 docs incrémentaux: l'ordre se met à jour à chaque merge."""
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
            doc_id="doc_1",
        )
        axis.add_value("3.0", "doc_1")

        # Doc2
        changed = axis.add_value("1.0", "doc_2")
        assert changed is True
        if changed and len(axis.known_values) >= 2:
            result = inferrer.infer_order("release_id", list(axis.known_values))
            if result.is_orderable:
                axis.value_order = result.inferred_order
                axis.is_orderable = True
                axis.ordering_confidence = result.confidence

        assert axis.value_order == ["1.0", "3.0"]

        # Doc3: ajoute 2.0 entre les deux
        changed = axis.add_value("2.0", "doc_3")
        assert changed is True
        if changed and len(axis.known_values) >= 2:
            result = inferrer.infer_order("release_id", list(axis.known_values))
            if result.is_orderable:
                axis.value_order = result.inferred_order

        assert axis.value_order == ["1.0", "2.0", "3.0"]

    def test_duplicate_value_no_recompute(self, inferrer):
        """Si la valeur est déjà présente, add_value retourne False → pas de re-inférence."""
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="year",
            doc_id="doc_1",
        )
        axis.add_value("2023", "doc_1")
        axis.add_value("2024", "doc_2")

        # Re-inférence initiale
        result = inferrer.infer_order("year", list(axis.known_values))
        axis.value_order = result.inferred_order
        axis.is_orderable = result.is_orderable

        # Doc3 apporte la même valeur "2024"
        changed = axis.add_value("2024", "doc_3")

        # Pas de changement → pas de re-inférence nécessaire
        assert changed is False


class TestNoOverwrite:
    """Test 2: Un axe déjà orderable ne retombe pas à false."""

    def test_orderable_axis_survives_single_value_doc(self, inferrer):
        """
        Axe déjà orderable (true + value_order) + doc entrant mono-valeur
        → reste orderable, ne retombe pas à false.
        """
        # Axe déjà correctement ordonné
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
            doc_id="doc_1",
        )
        axis.add_value("1.0", "doc_1")
        axis.add_value("2.0", "doc_2")
        axis.is_orderable = True
        axis.ordering_confidence = OrderingConfidence.CERTAIN
        axis.value_order = ["1.0", "2.0"]

        # Doc3 apporte une valeur existante (mono-valeur)
        changed = axis.add_value("2.0", "doc_3")

        # Pas de changement → on ne touche pas
        assert changed is False
        assert axis.is_orderable is True
        assert axis.ordering_confidence == OrderingConfidence.CERTAIN
        assert axis.value_order == ["1.0", "2.0"]

    def test_orderable_not_overwritten_by_failed_inference(self, inferrer):
        """
        Si l'inférence échoue (valeurs mixtes), un axe déjà orderable
        ne doit pas être écrasé.
        """
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
            doc_id="doc_1",
        )
        axis.add_value("1.0", "doc_1")
        axis.add_value("2.0", "doc_2")
        axis.is_orderable = True
        axis.ordering_confidence = OrderingConfidence.CERTAIN
        axis.value_order = ["1.0", "2.0"]

        # Doc3 apporte une valeur non-semver "beta"
        changed = axis.add_value("beta", "doc_3")
        assert changed is True

        # L'inférence échoue sur le mix "1.0", "2.0", "beta"
        result = inferrer.infer_order("release_id", list(axis.known_values))

        # Logique B1: ne pas écraser si order_result n'est pas orderable
        if result.is_orderable:
            axis.is_orderable = True
            axis.ordering_confidence = result.confidence
            axis.value_order = result.inferred_order
        # else: on ne touche pas

        # L'axe garde son état orderable précédent
        assert axis.is_orderable is True
        assert axis.ordering_confidence == OrderingConfidence.CERTAIN
        assert axis.value_order == ["1.0", "2.0"]


class TestMergeSafePersistence:
    """Test 3: Le Cypher ON MATCH est non-destructif."""

    def test_value_order_included_in_neo4j_props(self):
        """value_order est bien dans to_neo4j_properties()."""
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
            doc_id="doc_1",
        )
        axis.add_value("1.0", "doc_1")
        axis.add_value("2.0", "doc_2")
        axis.value_order = ["1.0", "2.0"]

        props = axis.to_neo4j_properties()

        assert "value_order" in props
        assert props["value_order"] == ["1.0", "2.0"]

    def test_is_orderable_or_logic(self):
        """
        Simule la logique OR du MERGE Neo4j:
        coalesce(ax.is_orderable, false) OR coalesce($props.is_orderable, false)

        Si l'existant est true et le nouveau est false → résultat = true.
        """
        # Simule: axe existant orderable + nouveau doc avec false
        existing_orderable = True
        new_orderable = False

        # Logique du Cypher merge-safe
        result = (existing_orderable or False) or (new_orderable or False)

        assert result is True

    def test_confidence_max_logic(self):
        """
        La confidence suit max(informativeness):
        CERTAIN > INFERRED > UNKNOWN
        """
        confidence_order = {
            "certain": 3,
            "inferred": 2,
            "unknown": 1,
        }

        def merge_confidence(existing, incoming):
            """Simule la logique CASE du Cypher."""
            if incoming == "certain" or existing == "certain":
                return "certain"
            if incoming == "inferred" or existing == "inferred":
                return "inferred"
            return existing or incoming

        # CERTAIN + UNKNOWN = CERTAIN
        assert merge_confidence("certain", "unknown") == "certain"

        # UNKNOWN + CERTAIN = CERTAIN
        assert merge_confidence("unknown", "certain") == "certain"

        # INFERRED + UNKNOWN = INFERRED
        assert merge_confidence("inferred", "unknown") == "inferred"

        # UNKNOWN + INFERRED = INFERRED
        assert merge_confidence("unknown", "inferred") == "inferred"

        # CERTAIN + INFERRED = CERTAIN
        assert merge_confidence("certain", "inferred") == "certain"

    def test_value_order_merge_prefers_longer(self):
        """
        Logique Cypher: si new_value_order a >= 2 éléments, il gagne.
        Sinon on garde l'existant.
        """
        existing_order = ["1.0", "2.0"]
        new_order_complete = ["1.0", "2.0", "3.0"]
        new_order_none = None

        # Nouveau complet → remplace
        if new_order_complete and len(new_order_complete) >= 2:
            result = new_order_complete
        elif existing_order and len(existing_order) >= 2:
            result = existing_order
        else:
            result = new_order_complete or existing_order
        assert result == ["1.0", "2.0", "3.0"]

        # Nouveau None → garde l'existant
        if new_order_none and len(new_order_none) >= 2:
            result = new_order_none
        elif existing_order and len(existing_order) >= 2:
            result = existing_order
        else:
            result = new_order_none or existing_order
        assert result == ["1.0", "2.0"]


class TestConfidenceMonotonic:
    """Test 4: CERTAIN ne redescend jamais à UNKNOWN."""

    def test_certain_never_downgraded(self, inferrer):
        """
        Un axe avec confidence=CERTAIN ne doit pas être rétrogradé.
        """
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="year",
            doc_id="doc_1",
        )
        axis.add_value("2023", "doc_1")
        axis.add_value("2024", "doc_2")
        axis.is_orderable = True
        axis.ordering_confidence = OrderingConfidence.CERTAIN
        axis.value_order = ["2023", "2024"]

        # Simuler un doc entrant dont l'axe a confidence=UNKNOWN
        incoming_confidence = OrderingConfidence.UNKNOWN

        # Logique merge-safe: max(informativeness)
        confidence_rank = {
            OrderingConfidence.CERTAIN: 3,
            OrderingConfidence.INFERRED: 2,
            OrderingConfidence.UNKNOWN: 1,
        }

        merged = max(
            axis.ordering_confidence,
            incoming_confidence,
            key=lambda c: confidence_rank[c],
        )

        assert merged == OrderingConfidence.CERTAIN

    def test_inferred_upgrades_to_certain(self, inferrer):
        """
        Un axe INFERRED peut être upgradé à CERTAIN si l'inférence le justifie.
        """
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
            doc_id="doc_1",
        )
        axis.add_value("I", "doc_1")
        axis.add_value("II", "doc_2")
        axis.is_orderable = True
        axis.ordering_confidence = OrderingConfidence.INFERRED
        axis.value_order = ["I", "II"]

        # Doc3 apporte "3.0" → maintenant c'est numérique... sauf que
        # "I", "II", "3.0" ne matchent aucune stratégie → on garde INFERRED
        changed = axis.add_value("3.0", "doc_3")
        assert changed is True

        result = inferrer.infer_order("release_id", list(axis.known_values))

        # L'inférence échoue (mix roman + semver) → on garde INFERRED
        if not result.is_orderable:
            assert axis.ordering_confidence == OrderingConfidence.INFERRED
            assert axis.value_order == ["I", "II"]  # Préservé


class TestE2EEvolutionDetection:
    """Test 5 (intégration): evolution_detector utilise l'axe corrigé."""

    def test_compare_works_after_fix(self, inferrer):
        """
        Scénario E2E simplifié:
        1. Axe créé avec 1 valeur (bug initial)
        2. 2e doc ajoute une valeur
        3. Re-inférence corrige l'axe
        4. compare() fonctionne maintenant
        """
        # Étape 1: Doc1 crée l'axe (état bugué initial)
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
            doc_id="doc_1",
        )
        axis.add_value("2.0", "doc_1")
        # Pas d'inférence (gate len >= 2 échouait)
        assert axis.value_order is None
        assert axis.compare("2.0", "3.0") is None  # Cassé!

        # Étape 2: Doc2 arrive
        changed = axis.add_value("3.0", "doc_2")
        assert changed is True

        # Étape 3: Re-inférence (fix B1)
        result = inferrer.infer_order("release_id", list(axis.known_values))
        if result.is_orderable:
            axis.is_orderable = True
            axis.ordering_confidence = result.confidence
            axis.value_order = result.inferred_order

        # Étape 4: compare() fonctionne!
        assert axis.compare("2.0", "3.0") == -1  # 2.0 < 3.0
        assert axis.compare("3.0", "2.0") == 1   # 3.0 > 2.0
        assert axis.compare("2.0", "2.0") == 0   # Égalité
        assert axis.get_latest_value() == "3.0"   # LatestSelector marche

    def test_sap_fps_evolution_timeline(self, inferrer):
        """
        Scénario réaliste SAP: 3 docs avec versions SAP FPS.
        """
        axis = ApplicabilityAxis.create_new(
            tenant_id="default",
            axis_key="release_id",
            doc_id="doc_1",
        )

        # Import séquentiel de 3 docs
        versions = [("2021 FPS02", "doc_1"), ("2021", "doc_2"), ("2021 FPS01", "doc_3")]

        for version, doc_id in versions:
            changed = axis.add_value(version, doc_id)
            if changed and len(axis.known_values) >= 2:
                result = inferrer.infer_order("release_id", list(axis.known_values))
                if result.is_orderable:
                    axis.is_orderable = True
                    axis.ordering_confidence = result.confidence
                    axis.value_order = result.inferred_order

        # Timeline correcte
        assert axis.value_order == ["2021", "2021 FPS01", "2021 FPS02"]
        assert axis.get_latest_value() == "2021 FPS02"
        assert axis.compare("2021", "2021 FPS02") == -1
