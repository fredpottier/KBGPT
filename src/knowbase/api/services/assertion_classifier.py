"""
Service de classification des assertions (OSMOSE Assertion-Centric).

Ce module prend les assertions candidates du LLM et les classifie
selon leur degre de verite en utilisant:

1. Similarite semantique (cross-encoder) assertion <-> source
2. Detection de contradiction (NLI)
3. Fraicheur des sources
4. Autorite des sources

Les 4 statuts finaux:
- FACT: Fortement supporte par les sources
- INFERRED: Deduit logiquement de FACTs
- FRAGILE: Faiblement supporte (1 source, ancien, ambigu)
- CONFLICT: Sources contradictoires detectees
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from knowbase.api.schemas.instrumented import (
    Assertion,
    AssertionCandidate,
    AssertionMeta,
    AssertionSupport,
    AssertionStatus,
    Freshness,
    LLMAssertionResponse,
    SourceRef,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION - Seuils de classification
# =============================================================================

@dataclass
class ClassificationConfig:
    """Configuration des seuils de classification."""

    # Support score (similarite semantique)
    SUPPORT_FORT: float = 0.78  # >= seuil pour FACT fort
    SUPPORT_MOYEN: float = 0.65  # >= seuil pour compter comme supportant
    SUPPORT_FAIBLE: float = 0.65  # < seuil → ne compte pas

    # Fraicheur des sources (en mois)
    FRESH_MONTHS: int = 36   # doc_date >= now - 36 mois
    STALE_MONTHS: int = 60   # doc_date < now - 60 mois

    # Poids d'autorite
    AUTHORITY_WEIGHTS: Dict[str, float] = field(default_factory=lambda: {
        "official": 1.0,
        "internal": 0.8,
        "partner": 0.7,
        "external": 0.6,
    })

    # Contradiction
    CONTRADICTION_THRESHOLD: float = 0.75

    # Seuil de weighted_support pour FACT "plein" vs FRAGILE
    WEIGHTED_SUPPORT_THRESHOLD: float = 0.9


# Configuration par defaut
DEFAULT_CONFIG = ClassificationConfig()


# =============================================================================
# STRUCTURES DE DONNEES
# =============================================================================

@dataclass
class SourceEvidence:
    """Evidence d'une source pour une assertion."""
    source_id: str
    source_ref: SourceRef
    similarity_score: float  # Similarite assertion <-> excerpt
    contradiction_score: float = 0.0  # Score NLI de contradiction
    authority_weight: float = 1.0
    freshness: Freshness = "mixed"
    document_age_months: Optional[int] = None


@dataclass
class ClassificationResult:
    """Resultat de classification pour une assertion."""
    assertion_id: str
    final_status: AssertionStatus
    supporting_sources: List[SourceEvidence]
    contradicting_sources: List[SourceEvidence]
    weighted_support: float
    freshness: Freshness
    has_official: bool
    classification_reasons: List[str] = field(default_factory=list)


# =============================================================================
# CALCUL DE SIMILARITE
# =============================================================================

def compute_support_score(
    assertion_text: str,
    excerpt_text: str,
) -> float:
    """
    Calcule le score de support entre une assertion et un extrait source.

    Utilise une similarite semantique simple. Pour une vraie production,
    utiliser un cross-encoder (sentence-transformers).

    Args:
        assertion_text: Texte de l'assertion
        excerpt_text: Texte de l'extrait source

    Returns:
        Score de similarite entre 0 et 1
    """
    # Version simple: overlap de mots normalise
    # TODO: Remplacer par cross-encoder en production

    assertion_words = set(assertion_text.lower().split())
    excerpt_words = set(excerpt_text.lower().split())

    if not assertion_words or not excerpt_words:
        return 0.0

    # Jaccard similarity avec bonus pour mots longs (plus significatifs)
    intersection = assertion_words & excerpt_words
    union = assertion_words | excerpt_words

    if not union:
        return 0.0

    # Jaccard de base
    jaccard = len(intersection) / len(union)

    # Bonus pour overlap sur mots longs (>= 5 caracteres)
    long_words_assertion = {w for w in assertion_words if len(w) >= 5}
    long_words_excerpt = {w for w in excerpt_words if len(w) >= 5}
    long_intersection = long_words_assertion & long_words_excerpt

    if long_words_assertion:
        long_overlap = len(long_intersection) / len(long_words_assertion)
    else:
        long_overlap = 0.0

    # Score final: 60% Jaccard + 40% overlap mots longs
    score = 0.6 * jaccard + 0.4 * long_overlap

    # Boost si l'assertion est courte et bien couverte
    if len(assertion_words) <= 15 and len(intersection) >= len(assertion_words) * 0.6:
        score = min(score * 1.2, 1.0)

    return score


def compute_support_score_batch(
    assertion_text: str,
    excerpts: List[Tuple[str, str]],  # List of (source_id, excerpt_text)
) -> Dict[str, float]:
    """
    Calcule les scores de support pour plusieurs excerpts.

    Args:
        assertion_text: Texte de l'assertion
        excerpts: Liste de (source_id, excerpt_text)

    Returns:
        Dict source_id -> score
    """
    return {
        source_id: compute_support_score(assertion_text, excerpt_text)
        for source_id, excerpt_text in excerpts
    }


# =============================================================================
# DETECTION DE CONTRADICTION
# =============================================================================

def detect_contradiction(
    assertion_text: str,
    excerpt_text: str,
) -> float:
    """
    Detecte si un extrait contredit une assertion.

    Version simple basee sur des patterns de negation.
    Pour production, utiliser un modele NLI (Natural Language Inference).

    Args:
        assertion_text: Texte de l'assertion
        excerpt_text: Texte de l'extrait

    Returns:
        Score de contradiction entre 0 et 1
    """
    # Patterns de negation
    negation_patterns = [
        "not ", "n't ", "no ", "never ", "none ", "neither ",
        "ne pas ", "ne plus ", "jamais ", "aucun ", "pas de ",
    ]

    assertion_lower = assertion_text.lower()
    excerpt_lower = excerpt_text.lower()

    # Detecte si l'extrait a une negation que l'assertion n'a pas
    assertion_has_negation = any(p in assertion_lower for p in negation_patterns)
    excerpt_has_negation = any(p in excerpt_lower for p in negation_patterns)

    # Si l'un a une negation et pas l'autre, potentielle contradiction
    if assertion_has_negation != excerpt_has_negation:
        # Verifie qu'ils parlent du meme sujet (overlap de mots)
        assertion_words = set(assertion_lower.split())
        excerpt_words = set(excerpt_lower.split())
        overlap = assertion_words & excerpt_words

        # Filtre les mots communs non significatifs
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                    "le", "la", "les", "un", "une", "des", "est", "sont", "de"}
        meaningful_overlap = {w for w in overlap if w not in stopwords and len(w) > 2}

        if len(meaningful_overlap) >= 3:
            # Contradiction probable
            return 0.7 + 0.1 * min(len(meaningful_overlap) - 3, 3)

    # Patterns de contradiction explicite
    contradiction_markers = [
        ("however", 0.3), ("but", 0.2), ("although", 0.3),
        ("cependant", 0.3), ("mais", 0.2), ("toutefois", 0.3),
        ("contrairement", 0.5), ("contrary", 0.5),
    ]

    for marker, score in contradiction_markers:
        if marker in excerpt_lower and marker not in assertion_lower:
            return max(0.4, score)

    return 0.0


# =============================================================================
# EVALUATION FRAICHEUR
# =============================================================================

def evaluate_freshness(
    document_date: Optional[str],
    config: ClassificationConfig = DEFAULT_CONFIG,
) -> Tuple[Freshness, Optional[int]]:
    """
    Evalue la fraicheur d'une source.

    Args:
        document_date: Date du document (format YYYY-MM ou YYYY)
        config: Configuration des seuils

    Returns:
        Tuple (freshness_status, age_in_months)
    """
    if not document_date:
        return "mixed", None

    try:
        # Parse la date
        if len(document_date) == 7:  # YYYY-MM
            doc_dt = datetime.strptime(document_date, "%Y-%m")
        elif len(document_date) == 4:  # YYYY
            doc_dt = datetime.strptime(document_date, "%Y")
        else:
            return "mixed", None

        now = datetime.now()
        age_months = (now.year - doc_dt.year) * 12 + (now.month - doc_dt.month)

        if age_months <= config.FRESH_MONTHS:
            return "fresh", age_months
        elif age_months >= config.STALE_MONTHS:
            return "stale", age_months
        else:
            return "mixed", age_months

    except (ValueError, TypeError):
        return "mixed", None


# =============================================================================
# ALGORITHME DE CLASSIFICATION PRINCIPAL
# =============================================================================

def classify_assertion(
    candidate: AssertionCandidate,
    sources: List[SourceRef],
    source_excerpts: Dict[str, str],  # source_id -> excerpt
    all_assertions: Dict[str, Assertion],  # assertion_id -> Assertion (pour INFERRED)
    config: ClassificationConfig = DEFAULT_CONFIG,
) -> ClassificationResult:
    """
    Classifie une assertion candidate en FACT/INFERRED/FRAGILE/CONFLICT.

    Algorithme en 4 etapes:
    1. Verifier si FACT possible
    2. Detecter CONFLICT
    3. Evaluer FRAGILE
    4. Evaluer INFERRED

    Args:
        candidate: Assertion candidate du LLM
        sources: Liste des SourceRef disponibles
        source_excerpts: Mapping source_id -> excerpt text
        all_assertions: Assertions deja classifiees (pour les INFERRED)
        config: Configuration des seuils

    Returns:
        ClassificationResult avec le statut final
    """
    reasons = []

    # Cree un mapping source_id -> SourceRef
    source_map = {s.id: s for s in sources}

    # --- ETAPE 1: Calculer les scores de support ---

    supporting_evidences: List[SourceEvidence] = []
    contradicting_evidences: List[SourceEvidence] = []

    # Pour chaque source referencee par le LLM
    for source_id in candidate.evidence_used:
        if source_id not in source_map:
            reasons.append(f"Source {source_id} non trouvee")
            continue

        source_ref = source_map[source_id]
        excerpt = source_excerpts.get(source_id, source_ref.excerpt)

        # Calcule la similarite
        sim_score = compute_support_score(candidate.text_md, excerpt)

        # Calcule la contradiction
        contradiction_score = detect_contradiction(candidate.text_md, excerpt)

        # Evalue la fraicheur
        doc_date = source_ref.document.date if source_ref.document else None
        freshness, age_months = evaluate_freshness(doc_date, config)

        # Determine le poids d'autorite
        authority = source_ref.document.authority if source_ref.document else "internal"
        authority_weight = config.AUTHORITY_WEIGHTS.get(authority, 0.8)

        evidence = SourceEvidence(
            source_id=source_id,
            source_ref=source_ref,
            similarity_score=sim_score,
            contradiction_score=contradiction_score,
            authority_weight=authority_weight,
            freshness=freshness,
            document_age_months=age_months,
        )

        # Classe comme supportante ou contradictoire
        if contradiction_score >= config.CONTRADICTION_THRESHOLD:
            contradicting_evidences.append(evidence)
        elif sim_score >= config.SUPPORT_MOYEN:
            supporting_evidences.append(evidence)

    # --- ETAPE 2: Detecter CONFLICT ---

    if supporting_evidences and contradicting_evidences:
        # Verifie que les contradictions viennent de documents differents
        supporting_docs = {e.source_ref.document.id for e in supporting_evidences if e.source_ref.document}
        contradicting_docs = {e.source_ref.document.id for e in contradicting_evidences if e.source_ref.document}

        if supporting_docs != contradicting_docs:
            reasons.append(f"CONFLICT: {len(supporting_evidences)} sources supportent, {len(contradicting_evidences)} contredisent")
            return ClassificationResult(
                assertion_id=candidate.id,
                final_status="CONFLICT",
                supporting_sources=supporting_evidences,
                contradicting_sources=contradicting_evidences,
                weighted_support=_compute_weighted_support(supporting_evidences, config),
                freshness=_aggregate_freshness(supporting_evidences),
                has_official=any(e.source_ref.document.authority == "official" for e in supporting_evidences if e.source_ref.document),
                classification_reasons=reasons,
            )

    # --- ETAPE 3: Evaluer si FACT possible ---

    weighted_support = _compute_weighted_support(supporting_evidences, config)
    has_strong_support = any(e.similarity_score >= config.SUPPORT_FORT for e in supporting_evidences)
    has_multi_source = len(supporting_evidences) >= 2

    is_fact_candidate = has_strong_support or has_multi_source

    if is_fact_candidate:
        # Verifie les conditions de FRAGILE
        is_fragile = False

        # FRAGILE si 1 seule source et stale
        if len(supporting_evidences) == 1:
            single_evidence = supporting_evidences[0]
            if single_evidence.freshness == "stale":
                is_fragile = True
                reasons.append("FRAGILE: source unique et ancienne")

        # FRAGILE si weighted_support trop faible
        if weighted_support < config.WEIGHTED_SUPPORT_THRESHOLD:
            is_fragile = True
            reasons.append(f"FRAGILE: weighted_support={weighted_support:.2f} < {config.WEIGHTED_SUPPORT_THRESHOLD}")

        # FRAGILE si source externe uniquement sans corroboration
        all_external = all(
            e.source_ref.document.authority == "external"
            for e in supporting_evidences
            if e.source_ref.document
        )
        if all_external and len(supporting_evidences) == 1:
            is_fragile = True
            reasons.append("FRAGILE: source externe unique")

        if is_fragile:
            return ClassificationResult(
                assertion_id=candidate.id,
                final_status="FRAGILE",
                supporting_sources=supporting_evidences,
                contradicting_sources=[],
                weighted_support=weighted_support,
                freshness=_aggregate_freshness(supporting_evidences),
                has_official=any(e.source_ref.document.authority == "official" for e in supporting_evidences if e.source_ref.document),
                classification_reasons=reasons,
            )

        # FACT valide
        reasons.append(f"FACT: {len(supporting_evidences)} sources, weighted={weighted_support:.2f}")
        return ClassificationResult(
            assertion_id=candidate.id,
            final_status="FACT",
            supporting_sources=supporting_evidences,
            contradicting_sources=[],
            weighted_support=weighted_support,
            freshness=_aggregate_freshness(supporting_evidences),
            has_official=any(e.source_ref.document.authority == "official" for e in supporting_evidences if e.source_ref.document),
            classification_reasons=reasons,
        )

    # --- ETAPE 4: Evaluer INFERRED ---

    if candidate.kind == "INFERRED" and candidate.derived_from:
        # Verifie que tous les parents sont FACT (pas FRAGILE/CONFLICT)
        parents_valid = True
        for parent_id in candidate.derived_from:
            parent = all_assertions.get(parent_id)
            if parent and parent.status not in ("FACT",):
                parents_valid = False
                reasons.append(f"INFERRED invalide: parent {parent_id} est {parent.status}")
                break
            if not parent:
                parents_valid = False
                reasons.append(f"INFERRED invalide: parent {parent_id} introuvable")
                break

        if parents_valid:
            reasons.append(f"INFERRED: derive de {candidate.derived_from}")
            return ClassificationResult(
                assertion_id=candidate.id,
                final_status="INFERRED",
                supporting_sources=[],
                contradicting_sources=[],
                weighted_support=0.0,
                freshness="mixed",
                has_official=False,
                classification_reasons=reasons,
            )

    # --- Fallback: FRAGILE ---

    reasons.append("FRAGILE: pas assez de support pour FACT, INFERRED invalide")
    return ClassificationResult(
        assertion_id=candidate.id,
        final_status="FRAGILE",
        supporting_sources=supporting_evidences,
        contradicting_sources=[],
        weighted_support=weighted_support,
        freshness=_aggregate_freshness(supporting_evidences),
        has_official=False,
        classification_reasons=reasons,
    )


def _compute_weighted_support(
    evidences: List[SourceEvidence],
    config: ClassificationConfig,
) -> float:
    """Calcule le support pondere par autorite."""
    if not evidences:
        return 0.0

    return sum(
        e.similarity_score * e.authority_weight
        for e in evidences
    )


def _aggregate_freshness(evidences: List[SourceEvidence]) -> Freshness:
    """Agregge la fraicheur de plusieurs sources."""
    if not evidences:
        return "mixed"

    freshnesses = [e.freshness for e in evidences]

    if all(f == "fresh" for f in freshnesses):
        return "fresh"
    elif all(f == "stale" for f in freshnesses):
        return "stale"
    else:
        return "mixed"


# =============================================================================
# CLASSIFICATION EN BATCH
# =============================================================================

def classify_assertions(
    llm_response: LLMAssertionResponse,
    sources: List[SourceRef],
    config: ClassificationConfig = DEFAULT_CONFIG,
    kg_relations: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Assertion], List[ClassificationResult]]:
    """
    Classifie toutes les assertions d'une reponse LLM.

    Args:
        llm_response: Reponse du LLM avec les assertions candidates
        sources: Liste des sources disponibles
        config: Configuration des seuils
        kg_relations: Relations KG confirmees (optionnel) pour booster la classification

    Returns:
        Tuple (List[Assertion], List[ClassificationResult])
    """
    # Prepare le mapping source_id -> excerpt
    source_excerpts = {s.id: s.excerpt for s in sources}

    # Prepare les relations KG pour matching rapide
    kg_concepts = set()
    kg_relation_pairs = []
    if kg_relations:
        for rel in kg_relations:
            source_concept = rel.get("source", "").lower()
            target_concept = rel.get("concept", "").lower()
            relation_type = rel.get("relation", "")
            confidence = rel.get("confidence", 0.5)
            if source_concept and target_concept and confidence >= 0.7:
                kg_concepts.add(source_concept)
                kg_concepts.add(target_concept)
                kg_relation_pairs.append({
                    "source": source_concept,
                    "target": target_concept,
                    "relation": relation_type,
                    "confidence": confidence,
                    "evidence_quote": rel.get("evidence_quote"),
                    "evidence_count": rel.get("evidence_count", 0),
                })
        if kg_relation_pairs:
            logger.info(
                f"[CLASSIFIER] Using {len(kg_relation_pairs)} KG relations for classification boost"
            )

    # Classifie les assertions une par une (ordre important pour INFERRED)
    classified_assertions: Dict[str, Assertion] = {}
    classification_results: List[ClassificationResult] = []

    for candidate in llm_response.assertions:
        # Classifie
        result = classify_assertion(
            candidate=candidate,
            sources=sources,
            source_excerpts=source_excerpts,
            all_assertions=classified_assertions,
            config=config,
        )

        classification_results.append(result)

        # Construit l'Assertion finale
        assertion = Assertion(
            id=candidate.id,
            text_md=candidate.text_md,
            status=result.final_status,
            scope="paragraph",  # Par defaut
            sources=[e.source_id for e in result.supporting_sources],
            contradictions=[e.source_id for e in result.contradicting_sources],
            derived_from=candidate.derived_from if result.final_status == "INFERRED" else [],
            inference_note=candidate.notes if result.final_status == "INFERRED" else None,
            meta=AssertionMeta(
                support=AssertionSupport(
                    supporting_sources_count=len(result.supporting_sources),
                    weighted_support=result.weighted_support,
                    freshness=result.freshness,
                    has_official=result.has_official,
                )
            ),
        )

        classified_assertions[assertion.id] = assertion

    final_assertions = list(classified_assertions.values())

    # 🌊 OSMOSE: Boost KG - Reclassifier les assertions FRAGILE soutenues par des relations KG
    kg_boosted_count = 0
    if kg_relation_pairs:
        for assertion in final_assertions:
            if assertion.status == "FRAGILE":
                assertion_text_lower = assertion.text_md.lower()
                # Vérifier si l'assertion mentionne des concepts liés par une relation KG
                for rel in kg_relation_pairs:
                    source_in = rel["source"] in assertion_text_lower
                    target_in = rel["target"] in assertion_text_lower
                    if source_in and target_in:
                        # Cette assertion est soutenue par une relation KG confirmée
                        assertion.status = "FACT"
                        assertion.meta.support.kg_relation = rel["relation"]
                        assertion.meta.support.kg_confidence = rel["confidence"]
                        assertion.meta.support.kg_evidence_quote = rel.get("evidence_quote")
                        assertion.meta.support.kg_source_count = rel.get("evidence_count", 1)
                        kg_boosted_count += 1
                        logger.debug(
                            f"[CLASSIFIER:KG_BOOST] Upgraded '{assertion.id}' to FACT "
                            f"(KG: {rel['source']} --[{rel['relation']}]--> {rel['target']})"
                        )
                        break  # Une seule relation suffit

        if kg_boosted_count > 0:
            logger.info(
                f"[CLASSIFIER:KG_BOOST] Upgraded {kg_boosted_count} assertions from FRAGILE to FACT "
                f"using KG relations"
            )

    logger.info(
        f"[CLASSIFIER] Classified {len(final_assertions)} assertions: "
        f"FACT={sum(1 for a in final_assertions if a.status == 'FACT')}, "
        f"INFERRED={sum(1 for a in final_assertions if a.status == 'INFERRED')}, "
        f"FRAGILE={sum(1 for a in final_assertions if a.status == 'FRAGILE')}, "
        f"CONFLICT={sum(1 for a in final_assertions if a.status == 'CONFLICT')}"
    )

    return final_assertions, classification_results


__all__ = [
    "ClassificationConfig",
    "DEFAULT_CONFIG",
    "SourceEvidence",
    "ClassificationResult",
    "compute_support_score",
    "detect_contradiction",
    "evaluate_freshness",
    "classify_assertion",
    "classify_assertions",
]
