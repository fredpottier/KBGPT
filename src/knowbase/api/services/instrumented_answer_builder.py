"""
Builder pour InstrumentedAnswer (OSMOSE Assertion-Centric).

Ce module assemble tous les elements pour construire une reponse instrumentee:
- Assertions classifiees
- TruthContract
- ProofTickets pour les assertions cles
- Sources avec metadata

Orchestre les appels a assertion_generator et assertion_classifier.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from knowbase.api.schemas.instrumented import (
    Assertion,
    DocumentInfo,
    InstrumentedAnswer,
    LLMAssertionResponse,
    OpenPoint,
    ProofTicket,
    ProofTicketCTA,
    RetrievalStats,
    SourceLocator,
    SourceRef,
    SourcesDateRange,
    TruthContract,
)
from knowbase.api.services.assertion_generator import (
    generate_assertions,
    prepare_evidence_for_prompt,
    validate_assertion_references,
)
from knowbase.api.services.assertion_classifier import (
    classify_assertions,
    ClassificationConfig,
    ClassificationResult,
    DEFAULT_CONFIG,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTRUCTION DES SOURCES
# =============================================================================

def build_sources_from_chunks(
    chunks: List[Dict[str, Any]],
    max_sources: int = 15,
) -> List[SourceRef]:
    """
    Construit les SourceRef a partir des chunks de recherche.

    Args:
        chunks: Chunks recuperes par la recherche
        max_sources: Nombre max de sources a inclure

    Returns:
        Liste de SourceRef
    """
    sources = []

    for idx, chunk in enumerate(chunks[:max_sources], 1):
        source_id = f"S{idx}"

        # Extrait les informations du chunk
        source_file = chunk.get("source_file", "")
        slide_index = chunk.get("slide_index")
        text = chunk.get("text", "").strip()
        score = chunk.get("score", 0)
        rerank_score = chunk.get("rerank_score")
        slide_image_url = chunk.get("slide_image_url")

        # Determine le titre et type du document
        if source_file:
            doc_title = Path(source_file).stem
            extension = Path(source_file).suffix.lower()
            doc_type = {
                ".pptx": "PPTX",
                ".pdf": "PDF",
                ".docx": "DOCX",
                ".xlsx": "XLSX",
            }.get(extension, "OTHER")
        else:
            doc_title = "Document inconnu"
            doc_type = "OTHER"

        # Infere l'autorite
        authority = _infer_authority(source_file)

        # Extrait la date si disponible
        doc_date = chunk.get("document_date")

        # Construit le DocumentInfo
        document = DocumentInfo(
            id=f"DOC{idx}",
            title=doc_title,
            doc_type=doc_type,
            date=doc_date,
            authority=authority,
            uri=source_file,
        )

        # Construit le locator si slide_index disponible
        locator = None
        if slide_index:
            try:
                page_num = int(slide_index) if isinstance(slide_index, str) else slide_index
                locator = SourceLocator(page_or_slide=page_num)
            except (ValueError, TypeError):
                pass

        # Tronque l'excerpt si trop long
        excerpt = text
        if len(excerpt) > 500:
            excerpt = excerpt[:497] + "..."

        source_ref = SourceRef(
            id=source_id,
            document=document,
            locator=locator,
            excerpt=excerpt,
            thumbnail_url=slide_image_url,
            evidence_url=None,  # TODO: Generer l'URL avec highlight
        )

        sources.append(source_ref)

    return sources


def _infer_authority(source_file: str) -> str:
    """Infere le niveau d'autorite d'une source."""
    if not source_file:
        return "internal"

    source_lower = source_file.lower()

    if any(p in source_lower for p in ["official", "documentation", "reference", "whitepaper"]):
        return "official"
    if any(p in source_lower for p in ["partner", "consultant"]):
        return "partner"
    if any(p in source_lower for p in ["external", "third-party", "blog"]):
        return "external"

    return "internal"


# =============================================================================
# CONSTRUCTION DU TRUTH CONTRACT
# =============================================================================

def build_truth_contract(
    assertions: List[Assertion],
    sources: List[SourceRef],
) -> TruthContract:
    """
    Construit le TruthContract a partir des assertions classifiees.

    Args:
        assertions: Liste des assertions classifiees
        sources: Liste des sources utilisees

    Returns:
        TruthContract
    """
    # Compte les assertions par statut
    facts_count = sum(1 for a in assertions if a.status == "FACT")
    inferred_count = sum(1 for a in assertions if a.status == "INFERRED")
    fragile_count = sum(1 for a in assertions if a.status == "FRAGILE")
    conflict_count = sum(1 for a in assertions if a.status == "CONFLICT")

    # Compte les sources uniques utilisees
    used_source_ids = set()
    for a in assertions:
        used_source_ids.update(a.sources)
        used_source_ids.update(a.contradictions)

    sources_count = len(used_source_ids)

    # Calcule la plage de dates des sources
    dates = []
    for s in sources:
        if s.id in used_source_ids and s.document and s.document.date:
            try:
                year = s.document.date[:4]
                dates.append(year)
            except (IndexError, TypeError):
                pass

    sources_date_range = None
    if dates:
        sorted_dates = sorted(dates)
        sources_date_range = SourcesDateRange(
            from_year=sorted_dates[0],
            to_year=sorted_dates[-1],
        )

    return TruthContract(
        facts_count=facts_count,
        inferred_count=inferred_count,
        fragile_count=fragile_count,
        conflict_count=conflict_count,
        sources_count=sources_count,
        sources_date_range=sources_date_range,
    )


# =============================================================================
# CONSTRUCTION DES PROOF TICKETS
# =============================================================================

def build_proof_tickets(
    assertions: List[Assertion],
    sources: List[SourceRef],
    max_tickets: int = 5,
) -> List[ProofTicket]:
    """
    Genere les ProofTickets pour les assertions les plus importantes.

    Selection basee sur:
    - Priorite aux FACT avec fort support
    - Puis CONFLICT (important a signaler)
    - Puis FRAGILE si pertinent

    Args:
        assertions: Liste des assertions classifiees
        sources: Liste des sources
        max_tickets: Nombre max de tickets a generer

    Returns:
        Liste de ProofTicket
    """
    # Score de priorite pour le tri
    def priority_score(a: Assertion) -> float:
        base = {
            "FACT": 100,
            "CONFLICT": 80,
            "FRAGILE": 50,
            "INFERRED": 30,
        }.get(a.status, 0)

        # Bonus pour les assertions avec plus de sources
        source_bonus = len(a.sources) * 5

        # Bonus pour weighted_support si disponible
        support_bonus = 0
        if a.meta and a.meta.support:
            support_bonus = a.meta.support.weighted_support * 10

        return base + source_bonus + support_bonus

    # Trie par priorite decroissante
    sorted_assertions = sorted(assertions, key=priority_score, reverse=True)

    tickets = []
    for assertion in sorted_assertions[:max_tickets]:
        ticket = _build_ticket_for_assertion(assertion, sources)
        if ticket:
            tickets.append(ticket)

    return tickets


def _build_ticket_for_assertion(
    assertion: Assertion,
    sources: List[SourceRef],
) -> Optional[ProofTicket]:
    """Construit un ProofTicket pour une assertion."""

    # Genere le titre (premiere partie du texte)
    title = assertion.text_md
    if len(title) > 80:
        # Coupe au dernier mot complet avant 80 caracteres
        title = title[:77].rsplit(" ", 1)[0] + "..."

    # Genere le summary selon le statut
    if assertion.status == "FACT":
        num_sources = len(assertion.sources)
        if num_sources >= 2:
            summary = f"Confirme par {num_sources} sources distinctes."
        else:
            summary = "Explicitement present dans la documentation."

        # Ajoute info fraicheur si disponible
        if assertion.meta and assertion.meta.support:
            if assertion.meta.support.freshness == "fresh":
                summary += " Sources recentes."
            if assertion.meta.support.has_official:
                summary += " Source officielle."

    elif assertion.status == "CONFLICT":
        summary = f"Attention: sources contradictoires detectees ({len(assertion.contradictions)} contradiction(s))."

    elif assertion.status == "FRAGILE":
        reasons = []
        if assertion.meta and assertion.meta.support:
            if assertion.meta.support.supporting_sources_count == 1:
                reasons.append("source unique")
            if assertion.meta.support.freshness == "stale":
                reasons.append("documentation ancienne")
        summary = f"Support faible: {', '.join(reasons) if reasons else 'evidence limitee'}."

    elif assertion.status == "INFERRED":
        summary = f"Inference logique basee sur {len(assertion.derived_from)} fait(s) etabli(s)."

    else:
        summary = "Statut inconnu."

    # Genere le CTA
    cta = None
    if assertion.sources:
        primary_source_id = assertion.sources[0]
        cta = ProofTicketCTA(
            label="Voir la source",
            target_type="source",
            target_id=primary_source_id,
        )

    return ProofTicket(
        ticket_id=f"T{assertion.id[1:]}",  # A1 -> T1
        assertion_id=assertion.id,
        title=title,
        status=assertion.status,
        summary=summary,
        primary_sources=assertion.sources[:3],  # Max 3 sources
        cta=cta,
    )


# =============================================================================
# CONSTRUCTION DES OPEN POINTS
# =============================================================================

def build_open_points(
    llm_open_points: List[str],
    assertions: List[Assertion],
) -> List[OpenPoint]:
    """
    Construit les OpenPoints a partir des points ouverts du LLM
    et des assertions problematiques.

    Args:
        llm_open_points: Points ouverts identifies par le LLM
        assertions: Assertions classifiees

    Returns:
        Liste d'OpenPoint
    """
    open_points = []

    # Ajoute les points du LLM
    for idx, point in enumerate(llm_open_points, 1):
        open_points.append(OpenPoint(
            id=f"OP{idx}",
            description=point,
            reason="evidence_insufficient",
            related_assertions=[],
        ))

    # Ajoute un point pour les CONFLICT non resolus
    conflict_assertions = [a for a in assertions if a.status == "CONFLICT"]
    if conflict_assertions:
        conflict_ids = [a.id for a in conflict_assertions]
        open_points.append(OpenPoint(
            id=f"OP{len(open_points) + 1}",
            description="Des sources contradictoires ont ete detectees. Verification manuelle recommandee.",
            reason="conflict_unresolved",
            related_assertions=conflict_ids,
        ))

    return open_points


# =============================================================================
# BUILDER PRINCIPAL
# =============================================================================

def build_instrumented_answer(
    question: str,
    chunks: List[Dict[str, Any]],
    language: str = "fr",
    session_context: str = "",
    classification_config: Optional[ClassificationConfig] = None,
    retrieval_stats: Optional[Dict[str, Any]] = None,
) -> Tuple[InstrumentedAnswer, Dict[str, Any]]:
    """
    Construit une InstrumentedAnswer complete a partir de la question et des chunks.

    Orchestre:
    1. Construction des SourceRef
    2. Generation des assertions (LLM)
    3. Classification des assertions
    4. Construction du TruthContract
    5. Generation des ProofTickets
    6. Assemblage final

    Args:
        question: Question de l'utilisateur
        chunks: Chunks recuperes par la recherche
        language: Langue de la reponse
        session_context: Contexte conversationnel optionnel
        classification_config: Configuration de classification optionnelle
        retrieval_stats: Statistiques de recuperation optionnelles

    Returns:
        Tuple (InstrumentedAnswer, build_metadata)
    """
    start_time = time.time()
    config = classification_config or DEFAULT_CONFIG

    # 1. Construit les SourceRef
    sources = build_sources_from_chunks(chunks)

    if not sources:
        # Pas de sources -> reponse vide
        return InstrumentedAnswer(
            answer_id=str(uuid4()),
            generated_at=datetime.utcnow().isoformat(),
            truth_contract=TruthContract(),
            assertions=[],
            proof_tickets=[],
            sources=[],
            open_points=[OpenPoint(
                id="OP1",
                description="Aucune source pertinente trouvee pour repondre a cette question.",
                reason="no_sources",
                related_assertions=[],
            )],
        ), {"build_time_ms": 0, "no_sources": True}

    # 2. Genere les assertions via LLM
    llm_response, gen_metadata = generate_assertions(
        question=question,
        chunks=chunks,
        language=language,
        session_context=session_context,
    )

    # 3. Valide les references
    available_source_ids = [s.id for s in sources]
    validated_response = validate_assertion_references(llm_response, available_source_ids)

    # 4. Classifie les assertions
    classified_assertions, classification_results = classify_assertions(
        llm_response=validated_response,
        sources=sources,
        config=config,
    )

    # 5. Construit le TruthContract
    truth_contract = build_truth_contract(classified_assertions, sources)

    # 6. Genere les ProofTickets
    proof_tickets = build_proof_tickets(classified_assertions, sources)

    # 7. Construit les OpenPoints
    open_points = build_open_points(llm_response.open_points, classified_assertions)

    # 8. Assemble l'InstrumentedAnswer
    answer = InstrumentedAnswer(
        answer_id=str(uuid4()),
        generated_at=datetime.utcnow().isoformat(),
        truth_contract=truth_contract,
        assertions=classified_assertions,
        proof_tickets=proof_tickets,
        sources=sources,
        open_points=open_points,
    )

    elapsed_ms = (time.time() - start_time) * 1000

    build_metadata = {
        "build_time_ms": elapsed_ms,
        "generation_metadata": gen_metadata,
        "assertions_count": len(classified_assertions),
        "sources_count": len(sources),
        "proof_tickets_count": len(proof_tickets),
        "open_points_count": len(open_points),
        "classification_summary": {
            "FACT": truth_contract.facts_count,
            "INFERRED": truth_contract.inferred_count,
            "FRAGILE": truth_contract.fragile_count,
            "CONFLICT": truth_contract.conflict_count,
        },
    }

    logger.info(
        f"[BUILDER] Built InstrumentedAnswer in {elapsed_ms:.0f}ms: "
        f"{len(classified_assertions)} assertions, {len(sources)} sources"
    )

    return answer, build_metadata


__all__ = [
    "build_instrumented_answer",
    "build_sources_from_chunks",
    "build_truth_contract",
    "build_proof_tickets",
    "build_open_points",
]
