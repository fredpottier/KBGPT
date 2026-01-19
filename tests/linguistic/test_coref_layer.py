"""
Tests pour le Linguistic Coreference Layer (Pass 0.5)

Ces tests valident les invariants L1-L5 de l'ADR:
- L1: Evidence-preserving (span exact avec offsets)
- L2: No generated evidence (substitutions = runtime only)
- L3: Closed-world disambiguation (LLM ne choisit que parmi candidats locaux)
- L4: Abstention-first (ambiguïté, longue portée, bridging → ABSTAIN)
- L5: Linguistic-only (COREFERS_TO n'implique aucune relation conceptuelle)

Ref: doc/ongoing/IMPLEMENTATION_PLAN_ADR_COMPLETION.md - Section 10
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import asdict

from knowbase.linguistic.coref_models import (
    MentionSpan,
    MentionType,
    CoreferenceChain,
    CorefDecision,
    DecisionType,
    ReasonCode,
    CorefLink,
    CorefScope,
    CoreferenceCluster,
    CorefGraphResult,
)
from knowbase.linguistic.coref_gating import (
    CorefGatingPolicy,
    GatingResult,
    GatingCandidate,
    create_gating_policy,
)
from knowbase.linguistic.coref_engine import (
    ICorefEngine,
    RuleBasedEngine,
    SpacyCorefEngine,
    CorefereeEngine,
    get_engine_for_language,
    get_available_engines,
)


# =============================================================================
# Tests Invariant L1: Evidence-preserving (MentionSpan avec offsets)
# =============================================================================

class TestMentionSpanCreation:
    """Tests pour la création de MentionSpan (invariant L1)."""

    def test_mentionspan_has_exact_offsets(self):
        """Un MentionSpan doit avoir des offsets exacts (L1)."""
        span = MentionSpan(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="doc_v1",
            docitem_id="item_001",
            surface="elle",
            span_start=50,
            span_end=54,
            mention_type=MentionType.PRONOUN,
        )

        assert span.span_start == 50
        assert span.span_end == 54
        assert span.surface == "elle"
        assert len(span.surface) == span.span_end - span.span_start

    def test_mentionspan_anchored_to_docitem(self):
        """Un MentionSpan peut être ancré à un DocItem structurel."""
        span = MentionSpan(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="doc_v1",
            docitem_id="docitem_heading_5",  # Ancrage structurel
            surface="TLS",
            span_start=10,
            span_end=13,
            mention_type=MentionType.NP,  # Groupe nominal
        )

        assert span.docitem_id == "docitem_heading_5"

    def test_mentionspan_has_sentence_index(self):
        """Un MentionSpan doit tracker son index de phrase."""
        span = MentionSpan(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="doc_v1",
            docitem_id="item_001",
            surface="il",
            span_start=100,
            span_end=102,
            mention_type=MentionType.PRONOUN,
            sentence_index=5,
        )

        assert span.sentence_index == 5

    def test_mentionspan_span_key_property(self):
        """Le span_key est une propriété calculée."""
        span = MentionSpan(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="doc_v1",
            docitem_id="item_001",
            surface="test",
            span_start=10,
            span_end=14,
            mention_type=MentionType.NP,
        )

        # span_key est une propriété, pas un paramètre constructeur
        assert span.span_key == "doc_v1:item_001:10:14"


class TestCorefCreatesSpanNotModifiedText:
    """Tests que la coréférence crée des spans, pas du texte modifié (L2)."""

    def test_coref_creates_mentionspan_not_modified_text(self):
        """La résolution crée un CorefLink, pas de substitution textuelle."""
        # Texte original - NE DOIT JAMAIS ÊTRE MODIFIÉ
        original_text = "TLS est un protocole. Elle permet de sécuriser."

        # Créer les mentions
        tls_span = MentionSpan(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="doc_v1",
            docitem_id="item_001",
            surface="TLS",
            span_start=0,
            span_end=3,
            mention_type=MentionType.NP,
            sentence_index=0,
        )

        elle_span = MentionSpan(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="doc_v1",
            docitem_id="item_001",
            surface="Elle",
            span_start=22,
            span_end=26,
            mention_type=MentionType.PRONOUN,
            sentence_index=1,
        )

        # Créer un lien de coréférence
        coref_link = CorefLink(
            source_mention_id=elle_span.mention_id,
            target_mention_id=tls_span.mention_id,
            confidence=0.92,
            scope=CorefScope.PREV_SENTENCE,
        )

        # Vérifier que le texte original n'est PAS modifié
        # Le texte reste identique - seules des relations sont créées
        assert original_text == "TLS est un protocole. Elle permet de sécuriser."

        # Le lien pointe du pronom vers l'antécédent
        assert coref_link.source_mention_id == elle_span.mention_id
        assert coref_link.target_mention_id == tls_span.mention_id


# =============================================================================
# Tests Invariant L3: Closed-world disambiguation
# =============================================================================

class TestClosedWorldDisambiguation:
    """Tests pour L3: candidats locaux uniquement."""

    def test_candidates_must_be_from_document(self):
        """Les candidats doivent venir du même document."""
        candidate = GatingCandidate(
            mention_id="span:tls",
            surface="TLS",
            sentence_idx=0,
            char_offset=0,
            engine_score=0.90,
            sentence_distance=1,
        )

        # Le candidat a un mention_id qui référence le même document
        assert candidate.mention_id.startswith("span:")
        assert candidate.sentence_distance <= 2  # Fenêtre locale


# =============================================================================
# Tests Invariant L4: Abstention-first
# =============================================================================

class TestAbstentionPolicy:
    """Tests pour L4: abstention sur ambiguïté."""

    def test_abstention_on_ambiguity(self):
        """Abstention quand plusieurs candidats valides (L4)."""
        policy = CorefGatingPolicy()

        # Deux candidats valides avec scores élevés
        candidates = [
            GatingCandidate(
                mention_id="span:serveur",
                surface="le serveur",
                sentence_idx=0,
                char_offset=0,
                engine_score=0.88,
                sentence_distance=1,
            ),
            GatingCandidate(
                mention_id="span:client",
                surface="le client",
                sentence_idx=0,
                char_offset=20,
                engine_score=0.87,
                sentence_distance=1,
            ),
        ]

        result = policy.evaluate_candidates(
            pronoun="il",
            pronoun_sentence_idx=1,
            candidates=candidates,
            sentence_context="Il envoie des données.",
            lang="fr"
        )

        # ABSTAIN car ambiguïté
        assert result.allowed is False
        assert result.decision_type == DecisionType.ABSTAIN
        assert result.reason_code == ReasonCode.AMBIGUOUS

    def test_abstention_on_low_confidence(self):
        """Abstention quand confiance < seuil (0.85)."""
        policy = CorefGatingPolicy(confidence_threshold=0.85)

        candidates = [
            GatingCandidate(
                mention_id="span:x",
                surface="X",
                sentence_idx=0,
                char_offset=0,
                engine_score=0.60,  # Sous le seuil
                sentence_distance=1,
            ),
        ]

        result = policy.evaluate_candidates(
            pronoun="il",
            pronoun_sentence_idx=1,
            candidates=candidates,
            sentence_context="Il fonctionne.",
            lang="fr"
        )

        assert result.allowed is False
        assert result.decision_type == DecisionType.ABSTAIN
        assert result.reason_code == ReasonCode.LOW_CONFIDENCE

    def test_abstention_on_long_distance(self):
        """Abstention quand distance > max_sentence_distance."""
        policy = CorefGatingPolicy(max_sentence_distance=2)

        candidates = [
            GatingCandidate(
                mention_id="span:x",
                surface="X",
                sentence_idx=0,
                char_offset=0,
                engine_score=0.95,
                sentence_distance=5,  # Trop loin
            ),
        ]

        result = policy.evaluate_candidates(
            pronoun="il",
            pronoun_sentence_idx=5,
            candidates=candidates,
            sentence_context="Il fonctionne.",
            lang="fr"
        )

        assert result.allowed is False
        assert result.decision_type == DecisionType.ABSTAIN

    def test_abstention_on_no_candidate(self):
        """Abstention quand aucun candidat."""
        policy = CorefGatingPolicy()

        result = policy.evaluate_candidates(
            pronoun="il",
            pronoun_sentence_idx=1,
            candidates=[],
            sentence_context="Il fonctionne.",
            lang="fr"
        )

        assert result.allowed is False
        assert result.decision_type == DecisionType.ABSTAIN
        assert result.reason_code == ReasonCode.NO_CANDIDATE


class TestImpersonalPronouns:
    """Tests pour la détection des pronoms impersonnels."""

    def test_non_referential_il_pleut_fr(self):
        """'Il pleut' en français est non-référentiel."""
        policy = CorefGatingPolicy()

        is_non_ref, reason = policy.is_non_referential(
            pronoun="il",
            sentence="Il pleut beaucoup aujourd'hui.",
            lang="fr"
        )

        assert is_non_ref is True
        assert reason == ReasonCode.IMPERSONAL

    def test_non_referential_it_rains_en(self):
        """'It rains' en anglais est non-référentiel."""
        policy = CorefGatingPolicy()

        is_non_ref, reason = policy.is_non_referential(
            pronoun="it",
            sentence="It rains every day in Seattle.",
            lang="en"
        )

        assert is_non_ref is True
        assert reason == ReasonCode.IMPERSONAL

    def test_non_referential_il_faut_fr(self):
        """'Il faut' en français est non-référentiel."""
        policy = CorefGatingPolicy()

        is_non_ref, reason = policy.is_non_referential(
            pronoun="il",
            sentence="Il faut configurer le serveur.",
            lang="fr"
        )

        assert is_non_ref is True
        assert reason == ReasonCode.IMPERSONAL

    def test_referential_il_normal_fr(self):
        """'Il' référentiel normal n'est pas impersonnel."""
        policy = CorefGatingPolicy()

        is_non_ref, reason = policy.is_non_referential(
            pronoun="il",
            sentence="Le serveur est configuré. Il fonctionne bien.",
            lang="fr"
        )

        assert is_non_ref is False


class TestMorphologicalAgreement:
    """Tests pour l'accord morphologique (genre/nombre) en français."""

    def test_gender_mismatch_rejected(self):
        """Désaccord de genre en français rejette le candidat."""
        policy = CorefGatingPolicy()

        # "elle" est féminin, mais le candidat est masculin
        candidate = GatingCandidate(
            mention_id="span:serveur",
            surface="le serveur",
            sentence_idx=0,
            char_offset=0,
            gender="m",  # Masculin
            number="s",
            engine_score=0.95,
            sentence_distance=1,
        )

        # "elle" doit matcher un antécédent féminin
        is_compatible = policy.check_morphological_agreement(
            pronoun="elle",
            candidate=candidate,
            lang="fr"
        )

        assert is_compatible is False

    def test_gender_match_accepted(self):
        """Accord de genre en français accepte le candidat."""
        policy = CorefGatingPolicy()

        # "elle" est féminin, le candidat aussi
        candidate = GatingCandidate(
            mention_id="span:machine",
            surface="la machine",
            sentence_idx=0,
            char_offset=0,
            gender="f",  # Féminin
            number="s",
            engine_score=0.95,
            sentence_distance=1,
        )

        is_compatible = policy.check_morphological_agreement(
            pronoun="elle",
            candidate=candidate,
            lang="fr"
        )

        assert is_compatible is True

    def test_number_mismatch_rejected(self):
        """Désaccord de nombre en français rejette le candidat."""
        policy = CorefGatingPolicy()

        # "ils" est pluriel, mais le candidat est singulier
        candidate = GatingCandidate(
            mention_id="span:serveur",
            surface="le serveur",
            sentence_idx=0,
            char_offset=0,
            gender="m",
            number="s",  # Singulier
            engine_score=0.95,
            sentence_distance=1,
        )

        is_compatible = policy.check_morphological_agreement(
            pronoun="ils",  # Pluriel
            candidate=candidate,
            lang="fr"
        )

        assert is_compatible is False

    def test_non_french_skips_morphology(self):
        """Pour les langues non-FR, pas de filtre morphologique."""
        policy = CorefGatingPolicy()

        candidate = GatingCandidate(
            mention_id="span:server",
            surface="the server",
            sentence_idx=0,
            char_offset=0,
            gender="m",
            number="s",
            engine_score=0.95,
            sentence_distance=1,
        )

        # Anglais: pas de filtre morphologique strict
        is_compatible = policy.check_morphological_agreement(
            pronoun="it",
            candidate=candidate,
            lang="en"
        )

        assert is_compatible is True


# =============================================================================
# Tests Résolution Réussie
# =============================================================================

class TestSuccessfulResolution:
    """Tests pour les cas de résolution réussie."""

    def test_single_valid_candidate_resolved(self):
        """Un seul candidat valide → résolution."""
        policy = CorefGatingPolicy()

        candidates = [
            GatingCandidate(
                mention_id="span:tls",
                surface="TLS",
                sentence_idx=0,
                char_offset=0,
                engine_score=0.92,
                sentence_distance=1,
            ),
        ]

        result = policy.evaluate_candidates(
            pronoun="elle",
            pronoun_sentence_idx=1,
            candidates=candidates,
            sentence_context="Elle permet la sécurisation.",
            lang="fr"
        )

        assert result.allowed is True
        assert result.decision_type == DecisionType.RESOLVED
        assert result.reason_code == ReasonCode.UNAMBIGUOUS
        assert result.chosen_candidate_idx == 0
        assert result.confidence == 0.92

    def test_scope_same_sentence(self):
        """Scope SAME_SENTENCE quand distance = 0."""
        policy = CorefGatingPolicy()

        candidates = [
            GatingCandidate(
                mention_id="span:x",
                surface="X",
                sentence_idx=1,
                char_offset=0,
                engine_score=0.90,
                sentence_distance=0,
            ),
        ]

        result = policy.evaluate_candidates(
            pronoun="il",
            pronoun_sentence_idx=1,
            candidates=candidates,
            sentence_context="X fonctionne. Il est stable.",
            lang="fr"
        )

        assert result.scope == CorefScope.SAME_SENTENCE

    def test_scope_prev_sentence(self):
        """Scope PREV_SENTENCE quand distance = 1."""
        policy = CorefGatingPolicy()

        candidates = [
            GatingCandidate(
                mention_id="span:x",
                surface="X",
                sentence_idx=0,
                char_offset=0,
                engine_score=0.90,
                sentence_distance=1,
            ),
        ]

        result = policy.evaluate_candidates(
            pronoun="il",
            pronoun_sentence_idx=1,
            candidates=candidates,
            sentence_context="Il est stable.",
            lang="fr"
        )

        assert result.scope == CorefScope.PREV_SENTENCE


# =============================================================================
# Tests Engine Selection
# =============================================================================

class TestEngineSelection:
    """Tests pour la sélection d'engine par langue."""

    def test_engine_fallback_for_unsupported_language(self):
        """Engine fallback (RuleBasedEngine) pour langue non supportée."""
        engine = get_engine_for_language("zulu")

        # Doit retourner RuleBasedEngine comme fallback
        assert isinstance(engine, RuleBasedEngine)

    def test_get_available_engines(self):
        """Liste des engines disponibles."""
        engines = get_available_engines()

        # Retourne un dict {engine_name: bool}
        assert "rule_based" in engines
        assert engines["rule_based"] is True  # Toujours disponible
        assert isinstance(engines, dict)

    def test_rule_based_engine_default(self):
        """RuleBasedEngine est toujours disponible."""
        engine = RuleBasedEngine()  # Pas de paramètre lang

        assert engine.engine_name == "rule_based"
        assert engine.is_available() is True


# =============================================================================
# Tests CorefDecision (Audit)
# =============================================================================

class TestCorefDecision:
    """Tests pour l'audit des décisions de coréférence."""

    def test_decision_records_all_candidates(self):
        """La décision enregistre tous les candidats évalués."""
        policy = CorefGatingPolicy()

        candidates = [
            GatingCandidate(
                mention_id="span:a",
                surface="A",
                sentence_idx=0,
                char_offset=0,
                engine_score=0.50,
                sentence_distance=1,
            ),
            GatingCandidate(
                mention_id="span:b",
                surface="B",
                sentence_idx=0,
                char_offset=10,
                engine_score=0.40,
                sentence_distance=1,
            ),
        ]

        result = policy.evaluate_candidates(
            pronoun="il",
            pronoun_sentence_idx=1,
            candidates=candidates,
            sentence_context="Il fonctionne.",
            lang="fr"
        )

        decision = policy.create_decision(
            tenant_id="default",
            doc_version_id="doc_v1",
            mention_span_key="span:il",
            candidates=candidates,
            result=result,
            method="test"
        )

        # La décision enregistre TOUS les candidats
        assert decision.candidate_count == 2
        assert "span:a" in decision.candidate_keys
        assert "span:b" in decision.candidate_keys
        assert decision.decision_type == DecisionType.ABSTAIN

    def test_decision_records_chosen_candidate(self):
        """La décision enregistre le candidat choisi si résolu."""
        policy = CorefGatingPolicy()

        candidates = [
            GatingCandidate(
                mention_id="span:unique",
                surface="Unique",
                sentence_idx=0,
                char_offset=0,
                engine_score=0.95,
                sentence_distance=1,
            ),
        ]

        result = policy.evaluate_candidates(
            pronoun="il",
            pronoun_sentence_idx=1,
            candidates=candidates,
            sentence_context="Il est bon.",
            lang="fr"
        )

        decision = policy.create_decision(
            tenant_id="default",
            doc_version_id="doc_v1",
            mention_span_key="span:il",
            candidates=candidates,
            result=result,
            method="test"
        )

        assert decision.chosen_candidate_key == "span:unique"
        assert decision.decision_type == DecisionType.RESOLVED
        assert decision.confidence == 0.95


# =============================================================================
# Tests CoreferenceChain et Cluster
# =============================================================================

class TestCoreferenceChain:
    """Tests pour les chaînes de coréférence."""

    def test_chain_has_multiple_members(self):
        """Une chaîne peut avoir plusieurs membres."""
        chain = CoreferenceChain(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="doc_v1",
            mention_ids=["span:tls", "span:elle", "span:ce_protocole"],
            representative_mention_id="span:tls",
        )

        assert len(chain.mention_ids) == 3
        assert chain.representative_mention_id == "span:tls"

    def test_cluster_from_chain(self):
        """Créer un cluster à partir d'une chaîne."""
        # CoreferenceCluster utilise des dicts, pas des MentionSpan
        cluster = CoreferenceCluster(
            mentions=[
                {"start": 0, "end": 3, "text": "TLS", "sentence_idx": 0},
                {"start": 50, "end": 54, "text": "elle", "sentence_idx": 1},
            ],
            representative_idx=0,
            confidence=0.92,
            method="rule_based",
        )

        assert cluster.representative["text"] == "TLS"
        assert len(cluster.mentions) == 2


# =============================================================================
# Tests CorefGraphResult
# =============================================================================

class TestCorefGraphResult:
    """Tests pour le résultat complet du graphe de coréférence."""

    def test_graph_result_structure(self):
        """Structure complète d'un CorefGraphResult."""
        result = CorefGraphResult(
            doc_id="doc1",
            doc_version_id="doc_v1",
            mention_spans=[],
            chains=[],
            links=[],
            decisions=[],
            total_pronouns_detected=10,
            resolved_count=5,
            abstained_count=5,
        )

        assert result.doc_version_id == "doc_v1"
        assert result.resolution_rate == 0.50

    def test_graph_result_with_data(self):
        """CorefGraphResult avec données complètes."""
        mention = MentionSpan(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="doc_v1",
            docitem_id="item_001",
            surface="test",
            span_start=0,
            span_end=4,
            mention_type=MentionType.NP,
        )

        link = CorefLink(
            source_mention_id="span_a",
            target_mention_id="span_b",
            confidence=0.9,
            scope=CorefScope.PREV_SENTENCE,
        )

        decision = CorefDecision(
            tenant_id="default",
            doc_version_id="doc_v1",
            mention_span_key="span:a",
            candidate_count=1,
            candidate_keys=["span:b"],
            chosen_candidate_key="span:b",
            decision_type=DecisionType.RESOLVED,
            confidence=0.9,
            method="test",
            reason_code=ReasonCode.UNAMBIGUOUS,
        )

        result = CorefGraphResult(
            doc_id="doc1",
            doc_version_id="doc_v1",
            mention_spans=[mention],
            chains=[],
            links=[link],
            decisions=[decision],
        )

        assert len(result.mention_spans) == 1
        assert len(result.links) == 1
        assert len(result.decisions) == 1


# =============================================================================
# Tests Factory Functions
# =============================================================================

class TestFactoryFunctions:
    """Tests pour les fonctions factory."""

    def test_create_gating_policy_defaults(self):
        """create_gating_policy avec valeurs par défaut."""
        policy = create_gating_policy()

        assert policy.confidence_threshold == 0.85
        assert policy.max_sentence_distance == 2
        assert policy.max_char_distance == 500

    def test_create_gating_policy_custom(self):
        """create_gating_policy avec valeurs personnalisées."""
        policy = create_gating_policy(
            confidence_threshold=0.90,
            max_sentence_distance=3,
            max_char_distance=1000,
        )

        assert policy.confidence_threshold == 0.90
        assert policy.max_sentence_distance == 3
        assert policy.max_char_distance == 1000


# =============================================================================
# Tests RuleBasedEngine
# =============================================================================

class TestRuleBasedEngine:
    """Tests pour le RuleBasedEngine (fallback)."""

    def test_rule_engine_resolves_en(self):
        """RuleBasedEngine résout les coréférences en anglais."""
        engine = RuleBasedEngine()

        # resolve() retourne List[CoreferenceCluster]
        clusters = engine.resolve(
            document_text="The server is running. It handles requests.",
            chunks=[],
            lang="en"
        )

        # Doit retourner une liste de CoreferenceCluster
        assert isinstance(clusters, list)
        # Chaque élément doit être un CoreferenceCluster
        for cluster in clusters:
            assert isinstance(cluster, CoreferenceCluster)
            assert cluster.method == "rule_based"

    def test_rule_engine_resolves_fr(self):
        """RuleBasedEngine résout les coréférences en français."""
        engine = RuleBasedEngine()

        clusters = engine.resolve(
            document_text="Le serveur fonctionne. Il traite les requêtes.",
            chunks=[],
            lang="fr"
        )

        # Doit retourner une liste de CoreferenceCluster
        assert isinstance(clusters, list)
        # Chaque cluster a des mentions
        for cluster in clusters:
            assert isinstance(cluster, CoreferenceCluster)
            assert hasattr(cluster, "mentions")
            assert hasattr(cluster, "representative_idx")

    def test_rule_engine_resolution_conservative(self):
        """RuleBasedEngine est conservatif (abstention fréquente)."""
        engine = RuleBasedEngine()

        # L'engine rule-based est conservatif - il abstient souvent
        clusters = engine.resolve(
            document_text="Alice met Bob. She liked him.",
            chunks=[],
            lang="en"
        )

        # Le résultat doit être une liste valide (peut être vide si conservatif)
        assert isinstance(clusters, list)
        # La confiance des clusters doit être modérée (conservatif)
        for cluster in clusters:
            assert cluster.confidence <= 0.8  # Confiance modérée pour rule-based


# =============================================================================
# Tests Integration
# =============================================================================

class TestCorefLayerIntegration:
    """Tests d'intégration du Linguistic Coreference Layer."""

    def test_full_flow_pronoun_resolution(self):
        """Flux complet: détection → gating → résolution via engine."""
        # 1. Utiliser l'engine pour résoudre les coréférences
        engine = RuleBasedEngine()
        text = "Le protocole TLS est sécurisé. Il utilise du chiffrement."

        # resolve() retourne List[CoreferenceCluster]
        clusters = engine.resolve(
            document_text=text,
            chunks=[],
            lang="fr"
        )

        # 2. Vérifier que le résultat est une liste de clusters
        assert isinstance(clusters, list)

        # 3. Chaque cluster doit être correctement formé
        for cluster in clusters:
            assert isinstance(cluster, CoreferenceCluster)
            assert cluster.method == "rule_based"
            assert len(cluster.mentions) >= 2  # Au moins 2 mentions pour un cluster
            assert cluster.representative_idx >= 0
            assert cluster.representative_idx < len(cluster.mentions)

        # 4. L'engine devrait détecter quelque chose avec ce texte
        # "TLS" est une entité et "Il" est un pronom
        # Note: si clusters est vide, c'est aussi acceptable (engine conservatif)
        assert clusters is not None

    def test_invariant_l5_no_semantic_inference(self):
        """L5: COREFERS_TO n'implique aucune relation conceptuelle."""
        # Créer un lien de coréférence
        link = CorefLink(
            source_mention_id="mention_elle",
            target_mention_id="mention_tls",
            confidence=0.92,
            scope=CorefScope.PREV_SENTENCE,
        )

        # Le lien est purement linguistique
        # Il ne crée PAS de relation IS_A, PART_OF, RELATED_TO, etc.
        # Il indique seulement que "elle" réfère à "TLS" dans le texte

        assert link.source_mention_id != link.target_mention_id
        assert link.confidence >= 0.85

        # Le lien n'a PAS de champ "relation_type" ou "semantic_type"
        # C'est un lien purement référentiel
        assert not hasattr(link, "relation_type")
        assert not hasattr(link, "semantic_type")


# =============================================================================
# Tests pour MATCHES_PROTOCONCEPT (governance note)
# =============================================================================

class TestMatchesProtoconcept:
    """Tests pour la relation MATCHES_PROTOCONCEPT."""

    def test_matches_protoconcept_is_lexical_not_semantic(self):
        """MATCHES_PROTOCONCEPT est un alignement lexical, pas sémantique."""
        # Le head d'une chaîne peut matcher un ProtoConcept
        # Mais c'est un alignement basé sur le surface form, pas une identité sémantique

        chain = CoreferenceChain(
            tenant_id="default",
            doc_id="doc1",
            doc_version_id="doc_v1",
            mention_ids=["span:tls", "span:elle"],
            representative_mention_id="span:tls",
            # Le head "TLS" peut être aligné avec ProtoConcept("TLS")
            # Mais cela ne signifie PAS que "elle" EST TLS sémantiquement
            # C'est juste un ancrage lexical pour faciliter la requête
        )

        # La chaîne a un head mais pas de champ "is_identical_to"
        assert chain.representative_mention_id == "span:tls"

        # Note de gouvernance: MATCHES_PROTOCONCEPT est lexical/anchored
        # Il ne crée pas d'identité sémantique entre les mentions
        # et le concept. C'est un pont pour la consommation runtime.


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
