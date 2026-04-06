"""
OSMOSIS Signal Policy — Transforme un SignalReport en instructions concretes.

Architecture V3 : 4 modes de reponse (DIRECT, AUGMENTED, TENSION, STRUCTURED_FACT).
Le KG ne parle pas au LLM — il contraint ce que le LLM a le droit de dire.

Mode Resolver 2 etages :
  Etage A : signaux PROPOSENT un mode candidat
  Etage B : qualite des preuves AUTORISE ou fallback DIRECT
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum

from .kg_signal_detector import SignalReport

logger = logging.getLogger(__name__)

# Limite de tokens KG injectes dans le prompt (lecon Sprint 0 test v2)
MAX_KG_INJECTION_TOKENS = 150


class ResponseMode(str, Enum):
    """Les 5 modes de reponse OSMOSIS."""
    DIRECT = "DIRECT"              # RAG pur, zero KG dans le prompt
    AUGMENTED = "AUGMENTED"        # KG guide le retrieval (doc expansion) sans texte narratif
    TENSION = "TENSION"            # Template Position A / Position B, contraintes courtes
    STRUCTURED_FACT = "STRUCTURED_FACT"  # Faits structures reformules par le LLM
    PERSPECTIVE = "PERSPECTIVE"    # Preuves groupees par axes thematiques (questions ouvertes)


@dataclass
class SignalPolicy:
    """Instructions concretes pour le pipeline, derivees des signaux KG."""

    # Chunk manipulation
    fetch_missing_tension_docs: bool = False
    tension_doc_ids: set[str] = field(default_factory=set)
    reorder_by_tensions: bool = False

    # Context injection (pour le prompt de synthese)
    inject_kg_enrichment: bool = False
    inject_kg_traversal: bool = False
    inject_qs_crossdoc: bool = False

    # Instructions supplementaires pour le prompt LLM
    synthesis_additions: list[str] = field(default_factory=list)

    # Negative rejection (question-context gap)
    unanswerable: bool = False
    unanswerable_reason: str = ""
    unanswerable_missing_terms: list[str] = field(default_factory=list)

    # Response mode (V3 architecture)
    response_mode: ResponseMode = ResponseMode.DIRECT
    candidate_mode: ResponseMode = ResponseMode.DIRECT
    response_mode_confidence: float = 0.0
    response_mode_reason: str = ""
    kg_trust_score: float = 0.0
    forced_fallback_to_direct: bool = False

    @property
    def is_passthrough(self) -> bool:
        """Si True, RAG pur sans aucune modification."""
        return not any([
            self.fetch_missing_tension_docs,
            self.reorder_by_tensions,
            self.inject_kg_enrichment,
            self.inject_kg_traversal,
            self.inject_qs_crossdoc,
            self.unanswerable,
        ])


def _compute_kg_trust_score(
    kg_claims: list[dict],
    retrieval_doc_ids: set[str],
    report: SignalReport,
    candidate_mode: ResponseMode,
) -> float:
    """Score 0-1 de fiabilite du KG pour cette query + mode candidat.

    4 facteurs :
    - doc_score : nombre de docs distincts dans les claims
    - bridge_score : proportion de claims avec bridge chunk (preuve textuelle)
    - overlap_score : docs KG aussi dans le RAG (coherence)
    - specificity_score : les signaux sont-ils specifiques au mode ?
    """
    if not kg_claims:
        return 0.0

    distinct_docs = len(set(c.get("doc_id") or c.get("source_file", "") for c in kg_claims))
    claims_with_chunks = sum(1 for c in kg_claims if c.get("chunk_ids"))
    kg_doc_ids = set(c.get("doc_id") or c.get("source_file", "") for c in kg_claims)
    overlap = len(kg_doc_ids & retrieval_doc_ids) if retrieval_doc_ids else 0

    doc_score = min(distinct_docs / 3, 1.0)
    bridge_score = claims_with_chunks / len(kg_claims) if kg_claims else 0
    overlap_score = min(overlap / 2, 1.0)

    # Specificity : les signaux sont-ils pertinents pour le mode ?
    specificity = 0.0
    signals = report.signals if report else []
    if candidate_mode == ResponseMode.TENSION:
        tension_signals = [s for s in signals if s.type == "tension"]
        specificity = max((s.strength for s in tension_signals), default=0)
    elif candidate_mode == ResponseMode.STRUCTURED_FACT:
        exact_signals = [s for s in signals if s.type == "exactness"]
        specificity = max((s.strength for s in exact_signals), default=0)
    elif candidate_mode == ResponseMode.AUGMENTED:
        kg_signals = [s for s in signals if s.type in ("temporal_evolution", "coverage_gap")]
        specificity = max((s.strength for s in kg_signals), default=0)

    return round(0.25 * doc_score + 0.30 * bridge_score + 0.20 * overlap_score + 0.25 * specificity, 3)


def _check_paired_tension_evidence(kg_claims: list[dict]) -> bool:
    """Verifie qu'au moins 2 claims partagent une entite SPECIFIQUE ET viennent de docs distincts.

    Exclut les entites trop generiques (SAP, S/4HANA, etc.) qui matchent tout.
    """
    GENERIC_ENTITIES = {
        "sap", "sap s/4hana", "s/4hana", "sap s/4hana cloud",
        "sap s/4hana cloud private edition", "sap cloud erp",
        "abap", "abap platform", "fiori", "sap fiori",
        "hana", "sap hana",
    }
    entity_docs: dict[str, set[str]] = {}
    for claim in kg_claims:
        doc_id = claim.get("doc_id") or claim.get("source_file", "")
        for entity in claim.get("entity_names", []):
            if entity and entity.lower().strip() not in GENERIC_ENTITIES:
                entity_docs.setdefault(entity, set()).add(doc_id)
    return any(len(docs) >= 2 for docs in entity_docs.values())


def _check_comparable_facts(qs_crossdoc_data: list[dict] | None) -> int:
    """Compte les faits comparables (meme axe/dimension)."""
    if not qs_crossdoc_data:
        return 0
    axes = {}
    for entry in qs_crossdoc_data:
        axis = entry.get("comparison_axis") or entry.get("question_dimension", "")
        if axis:
            axes[axis] = axes.get(axis, 0) + 1
    return max(axes.values()) if axes else len(qs_crossdoc_data)


def build_policy(
    report: SignalReport,
    kg_claims: list[dict] | None = None,
    retrieval_doc_ids: set[str] | None = None,
    qs_crossdoc_data: list[dict] | None = None,
    question: str = "",
    embedding_model=None,
) -> SignalPolicy:
    """
    Construit une SignalPolicy a partir d'un SignalReport.

    V3 : Mode Resolver 2 etages.
      Etage A : signaux proposent un mode candidat
      Etage B : qualite des preuves autorise ou fallback DIRECT

    Args:
        report: SignalReport avec les signaux detectes
        kg_claims: claims KG recuperes (pour trust scoring)
        retrieval_doc_ids: doc_ids des chunks RAG (pour overlap)
        qs_crossdoc_data: donnees QS cross-doc (pour STRUCTURED_FACT)
    """
    if report.is_silent:
        logger.info("[POLICY] Passthrough — no signals, RAG pure")
        return SignalPolicy(response_mode_reason="no_signals")

    policy = SignalPolicy()

    # Signal tension → chercher chunks des docs en tension + enrichir + reordonner
    tension = report.get_signal("tension")
    if tension:
        tension_doc_ids = tension.evidence.get("tension_doc_ids", set())
        policy.fetch_missing_tension_docs = bool(tension_doc_ids)
        policy.tension_doc_ids = tension_doc_ids if isinstance(tension_doc_ids, set) else set(tension_doc_ids)
        policy.reorder_by_tensions = True
        policy.inject_kg_enrichment = True
        policy.inject_kg_traversal = True
        policy.synthesis_additions.append(
            "IMPORTANT: Sources contain DIVERGENCES on this topic. "
            "Present BOTH positions with their sources. Do NOT silently pick one side."
        )

    # Signal evolution temporelle → activer le traversal pour les chains temporelles
    evolution = report.get_signal("temporal_evolution")
    if evolution:
        policy.inject_kg_traversal = True
        entity_names = list(evolution.evidence.get("multi_doc_entities", {}).keys())[:3]
        if entity_names:
            policy.synthesis_additions.append(
                f"NOTE: The topic '{', '.join(entity_names)}' appears across multiple document versions. "
                "Distinguish what was true in earlier versions vs what is current."
            )

    # Signal couverture → elargir le retrieval aux docs manquants
    coverage = report.get_signal("coverage_gap")
    if coverage:
        missing = coverage.evidence.get("missing_doc_ids", set())
        if missing:
            policy.fetch_missing_tension_docs = True  # reutilise le meme mecanisme
            policy.tension_doc_ids = policy.tension_doc_ids | (missing if isinstance(missing, set) else set(missing))

    # Signal exactitude → injecter les QS cross-doc
    exactness = report.get_signal("exactness")
    if exactness:
        policy.inject_qs_crossdoc = True
        matches = exactness.evidence.get("matches", [])
        if matches:
            first = matches[0]
            policy.synthesis_additions.append(
                f"A structured value is available: {first.get('canonical_question', '')} "
                f"= {first.get('extracted_value', '')} (source: {first.get('doc_id', '')}). "
                "Lead with this exact value in your answer."
            )

    # Signal 5 — Question-Context Gap (negative rejection)
    gap = report.get_signal("question_context_gap")
    if gap:
        gap_score = gap.evidence.get("gap_score", 0)
        max_chunk_score = gap.evidence.get("max_chunk_score", 0)
        missing_terms = gap.evidence.get("missing_terms", [])

        # DESACTIVE — le hard reject cause trop de faux positifs en contexte multilingue
        # (questions FR avec corpus EN : les termes specifiques ne matchent jamais)
        # Voir doc/ongoing/ANALYSE_NEGATIVE_REJECTION_STRATEGY.md pour l'analyse complete
        # TODO: reactiver quand le gap signal supportera le cross-lingue (lemmatisation, embeddings de termes)
        #
        # if gap_score >= 1.0 and not has_exactness:
        #     policy.unanswerable = True
        #     ...

        # Soft signal gap DESACTIVE — cause des degradations cross-lingue.
        # Le QA-Class gere le negative rejection, le gap soft est inutile.
        # if gap_score >= 0.6:
        #     policy.synthesis_additions.append(...)
        pass

    # Signal 6 — Dense Answerability
    # CONSTAT : les scores denses ne discriminent PAS answerable vs unanswerable
    # sur un corpus thematique (toute question "SAP" a un score dense > 0.75).
    # Le signal dense ne sert que pour les questions TOTALEMENT hors-domaine
    # (ex: "recette de gateau" sur un corpus SAP → dense < 0.3).
    # Pour les questions dans le domaine mais hors-scope (prix, salaires),
    # le score dense est trop eleve pour etre utile.
    # TODO: explorer cross-encoder re-ranking ou NLI question-chunk pour discriminer.
    dense = report.get_signal("dense_answerability")
    if dense:
        max_dense = dense.evidence.get("max_dense_score", 0)
        if max_dense < 0.25:
            policy.unanswerable = True
            policy.unanswerable_reason = (
                f"Aucun document du corpus ne semble lié à cette question "
                f"(meilleur score de similarite : {max_dense:.0%})."
            )
            logger.info(f"[POLICY] UNANSWERABLE (dense) — max_dense={max_dense:.3f}")

    # Signal 7 — QA-Class Answerability (Qwen/vLLM, hard reject fiable)
    # C'est le SEUL signal qui peut faire un hard reject sans faux positifs.
    # Historique : 4 approches testees et eliminees (prompt, lexical, dense).
    # Le QA-Class est multilingue, domain-agnostic, et evalue directement
    # "ce chunk permet-il de repondre ?" au lieu d'utiliser des proxies.
    qa = report.get_signal("qa_answerability")
    if qa and not policy.unanswerable:  # ne pas overrider un UNANSWERABLE dense
        votes = qa.evidence.get("votes", [])
        # Hard reject seulement si TOUS les votes sont NO (pas PARTIAL, pas UNKNOWN)
        all_no = all(v == "NO" for v in votes) and len(votes) >= 2
        if all_no:
            policy.unanswerable = True
            policy.unanswerable_reason = (
                "Aucun des documents recuperes ne contient d'information "
                "permettant de repondre a cette question."
            )
            logger.info(f"[POLICY] UNANSWERABLE (QA-Class) — votes={votes}")

    # Guard-rail : limiter le nombre d'instructions ajoutees
    if len(policy.synthesis_additions) > 3:
        policy.synthesis_additions = policy.synthesis_additions[:3]

    active = []
    if policy.fetch_missing_tension_docs:
        active.append("fetch_missing_docs")
    if policy.reorder_by_tensions:
        active.append("reorder_tensions")
    if policy.inject_kg_enrichment:
        active.append("kg_enrichment")
    if policy.inject_kg_traversal:
        active.append("kg_traversal")
    if policy.inject_qs_crossdoc:
        active.append("qs_crossdoc")

    logger.info(f"[POLICY] Active: {active}, additions: {len(policy.synthesis_additions)}")

    # ══════════════════════════════════════════════════════════════
    # V3 Mode Resolver — 2 etages
    # ══════════════════════════════════════════════════════════════

    # Feature flags
    modes_enabled = os.environ.get("OSMOSIS_RESPONSE_MODES", "false").lower() == "true"
    if not modes_enabled:
        policy.response_mode_reason = "feature_flag_off"
        return policy

    tension_enabled = os.environ.get("MODE_TENSION_ENABLED", "true").lower() == "true"
    augmented_enabled = os.environ.get("MODE_AUGMENTED_ENABLED", "true").lower() == "true"
    structured_enabled = os.environ.get("MODE_STRUCTURED_FACT_ENABLED", "true").lower() == "true"

    _kg_claims = kg_claims or []
    _retrieval_docs = retrieval_doc_ids or set()

    # ── Etage A : Candidat mode ──────────────────────────────────
    # PRINCIPE : DIRECT par defaut. On ne quitte DIRECT que si la QUESTION
    # demande explicitement quelque chose que le RAG seul ne peut pas fournir.
    # Les signaux KG sont trop frequents sur un corpus dense pour servir de gate.
    # On utilise donc des heuristiques sur la QUESTION, validees par les signaux.
    candidate = ResponseMode.DIRECT
    confidence = 0.0
    reason = "default_direct"

    # Seuils de declenchement
    TENSION_MIN_STRENGTH = 0.6
    TENSION_MIN_TEXTS = 3
    EXACTNESS_MIN_STRENGTH = 0.5

    # Classification de la question par embedding similarity (multilingue)
    question_mode = "DIRECT"
    question_mode_confidence = 0.0
    if question and embedding_model is not None:
        try:
            from .mode_classifier import get_mode_classifier
            classifier = get_mode_classifier()
            question_mode, question_mode_confidence = classifier.classify(question, embedding_model)
        except Exception as e:
            logger.warning(f"[MODE_CLASSIFIER] Classification failed (fallback DIRECT): {e}")

    # Mode TENSION : le classificateur detecte une intention tension ET le KG confirme
    if tension and tension_enabled and question_mode == "TENSION":
        n_tensions = len(tension.evidence.get("tension_texts", []))
        if tension.strength >= TENSION_MIN_STRENGTH and n_tensions >= TENSION_MIN_TEXTS:
            candidate = ResponseMode.TENSION
            confidence = tension.strength
            reason = f"tension: classifier={question_mode_confidence:.2f} + {n_tensions} cross-doc (strength={tension.strength:.2f})"
        else:
            reason = f"tension_classified_but_weak: classifier={question_mode_confidence:.2f}, {n_tensions} texts, strength={tension.strength:.2f}"

    # Mode STRUCTURED_FACT : le classificateur detecte une intention structuree ET QS disponibles
    if candidate == ResponseMode.DIRECT and exactness and structured_enabled and question_mode == "STRUCTURED_FACT":
        if exactness.strength >= EXACTNESS_MIN_STRENGTH:
            candidate = ResponseMode.STRUCTURED_FACT
            confidence = exactness.strength
            reason = f"structured: classifier={question_mode_confidence:.2f} + exactness={exactness.strength:.2f}"

    # Mode PERSPECTIVE : question ouverte/panoramique + Perspectives disponibles
    perspective_enabled = os.environ.get("MODE_PERSPECTIVE_ENABLED", "true").lower() == "true"
    if candidate == ResponseMode.DIRECT and perspective_enabled:
        try:
            from knowbase.perspectives.runtime import should_activate_perspectives
            if should_activate_perspectives(question or "", _kg_claims, []):
                candidate = ResponseMode.PERSPECTIVE
                confidence = 0.6
                reason = "perspective: open_question_detected"
        except Exception as e:
            logger.debug(f"[MODE_PERSPECTIVE] Detection failed (non-blocking): {e}")

    # Mode AUGMENTED : reserve pour override admin ou calibration auto future

    policy.candidate_mode = candidate

    # ── Etage B : Validation par qualite des preuves ─────────────
    kg_trust = _compute_kg_trust_score(_kg_claims, _retrieval_docs, report, candidate)
    fallback = False

    if candidate == ResponseMode.TENSION:
        kg_doc_ids = set(c.get("doc_id") or c.get("source_file", "") for c in _kg_claims)
        tension_doc_ids_from_claims = kg_doc_ids  # docs dans les claims KG
        distinct_tension_docs = len(tension_doc_ids_from_claims)
        paired = _check_paired_tension_evidence(_kg_claims)
        if distinct_tension_docs < 2 or not paired or kg_trust < 0.4:
            candidate = ResponseMode.DIRECT
            fallback = True
            reason += f" -> FALLBACK (docs={distinct_tension_docs}, paired={paired}, trust={kg_trust:.2f})"

    elif candidate == ResponseMode.STRUCTURED_FACT:
        comparable = _check_comparable_facts(qs_crossdoc_data)
        if comparable < 2 or kg_trust < 0.5:
            candidate = ResponseMode.DIRECT
            fallback = True
            reason += f" -> FALLBACK (comparable={comparable}, trust={kg_trust:.2f})"

    elif candidate == ResponseMode.PERSPECTIVE:
        # Validation legere : on verifie juste que des Perspectives existent
        # La validation complete (>= 2 Perspectives, couverture) est faite dans runtime.py
        # qui peut fallback DIRECT de maniere transparente
        pass

    elif candidate == ResponseMode.AUGMENTED:
        kg_doc_ids = set(c.get("doc_id") or c.get("source_file", "") for c in _kg_claims)
        new_docs = kg_doc_ids - _retrieval_docs
        if len(new_docs) == 0 or kg_trust < 0.3:
            candidate = ResponseMode.DIRECT
            fallback = True
            reason += f" -> FALLBACK (new_docs={len(new_docs)}, trust={kg_trust:.2f})"

    # ── Etage B' : KG Override — DIRECT invalidable ────────────
    # Le KG ne doit pas enrichir une reponse simple.
    # Il doit empecher qu'une reponse simple soit FAUSSE.
    #
    # Override DIRECT → TENSION uniquement si :
    # 1. Contradiction forte (confidence >= 0.85)
    # 2. Le RAG ne retourne qu'un cote (doc contradictoire absent)
    # 3. Paired evidence (meme entite, docs distincts)
    # 4. TENSION est resolvable (les deux cotes existent dans le KG)
    KG_OVERRIDE_MIN_CONFIDENCE = 0.85

    if candidate == ResponseMode.DIRECT and tension and tension_enabled and not fallback:
        tension_texts = tension.evidence.get("tension_texts", [])
        tension_doc_ids_set = tension.evidence.get("tension_doc_ids", set())
        if not isinstance(tension_doc_ids_set, set):
            tension_doc_ids_set = set(tension_doc_ids_set)

        # Les docs en tension qui ne sont PAS dans les resultats RAG
        missing_tension_docs = tension_doc_ids_set - _retrieval_docs

        # Override si : contradiction forte + RAG incomplet + preuves pairees
        if (tension.strength >= KG_OVERRIDE_MIN_CONFIDENCE
                and len(missing_tension_docs) >= 1
                and len(tension_doc_ids_set) >= 2
                and _check_paired_tension_evidence(_kg_claims)):
            candidate = ResponseMode.TENSION
            confidence = tension.strength
            reason = (
                f"kg_override: strong contradiction (strength={tension.strength:.2f}) "
                f"+ RAG missing {len(missing_tension_docs)} tension doc(s) "
                f"→ answer would be misleading without both sides"
            )
            # Stocker les docs manquants pour injection dans search.py
            policy.tension_doc_ids = policy.tension_doc_ids | missing_tension_docs
            policy.fetch_missing_tension_docs = True
            logger.info(
                f"[OSMOSIS:MODE:OVERRIDE] DIRECT → TENSION "
                f"(missing docs: {[d[:30] for d in missing_tension_docs]})"
            )

    policy.response_mode = candidate
    policy.response_mode_confidence = confidence
    policy.response_mode_reason = reason
    policy.kg_trust_score = kg_trust
    policy.forced_fallback_to_direct = fallback

    logger.info(
        f"[OSMOSIS:MODE] candidate={policy.candidate_mode.value} "
        f"resolved={policy.response_mode.value} "
        f"kg_trust={kg_trust:.2f} fallback={fallback} "
        f"reason=\"{reason}\""
    )

    return policy
