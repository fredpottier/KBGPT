"""
OSMOSIS Verify — Document Word Processor

Extrait le texte d'un .docx par paragraphe et annote le document
avec des commentaires de review bases sur les verdicts de verification.

Utilise python-docx >= 1.2.0 (support natif add_comment).

Author: Claude Code
Date: 2026-04-02
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any

from docx import Document
from docx.text.paragraph import Paragraph

logger = logging.getLogger(__name__)


# ── Structures de donnees V3-ready ─────────────────────────────────

@dataclass
class CorpusPosition:
    """Position d'un document du corpus sur un sujet."""
    doc_id: str = ""
    doc_title: str = ""
    claim_text: str = ""
    relation: str = ""  # CONFIRMS | CONTRADICTS | QUALIFIES | REFINES | EVOLVES_TO
    confidence: float = 0.0
    is_most_recent: bool = False


@dataclass
class AssertionVerdict:
    """Verdict structure — le KG decide, le LLM explique."""
    assertion_id: str = ""
    assertion_text: str = ""
    paragraph_index: int = 0

    # Verdict (deterministe)
    status: str = "unknown"  # confirmed | contradicted | qualified | outdated | incomplete | unknown
    severity: str = "medium"  # high | medium | low
    confidence: float = 0.0
    reasoning_type: str = ""  # exact_match | value_conflict | scope_mismatch | temporal_evolution

    # Positions corpus
    corpus_positions: list[CorpusPosition] = field(default_factory=list)

    # Entites
    entities: list[str] = field(default_factory=list)

    # Explication (LLM)
    explanation: str = ""

    # V1.5: coherence interne + blind spots (vides en V1)
    internal_conflicts: list[str] = field(default_factory=list)
    blind_spots: list[str] = field(default_factory=list)


@dataclass
class DocumentReviewResult:
    """Resultat complet de la review documentaire."""
    assertions: list[AssertionVerdict] = field(default_factory=list)
    reliability_score: float = 0.0
    total_confirmed: int = 0
    total_contradicted: int = 0
    total_qualified: int = 0
    total_unknown: int = 0
    high_severity_count: int = 0
    internal_contradictions: int = 0
    coverage_score: float = 0.0
    missing_dimensions: list[str] = field(default_factory=list)


# ── Status → commentaire Word ──────────────────────────────────────

STATUS_EMOJI = {
    "confirmed": "✅",
    "contradicted": "❌",
    "qualified": "⚠️",
    "outdated": "📅",
    "incomplete": "➕",
    "fallback": "📄",
    "unknown": "❓",
}

STATUS_LABEL = {
    "confirmed": "Confirme",
    "contradicted": "Contredit",
    "qualified": "Nuance",
    "outdated": "Obsolete",
    "incomplete": "Incomplete",
    "fallback": "Non structure",
    "unknown": "Non verifiable",
}

SEVERITY_LABEL = {
    "high": "Severite HAUTE",
    "medium": "",
    "low": "",
}


# ── Extraction texte ───────────────────────────────────────────────

def extract_paragraphs(doc: Document) -> list[dict[str, Any]]:
    """Extrait les paragraphes du document avec leur index et texte.

    Returns:
        Liste de {index, text, paragraph} pour chaque paragraphe non vide.
    """
    paragraphs = []
    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if text and len(text) > 10:  # ignorer les lignes vides/courtes
            paragraphs.append({
                "index": i,
                "text": text,
                "paragraph": para,
            })

    logger.info(f"[DOCX] Extracted {len(paragraphs)} paragraphs from document")
    return paragraphs


def chunk_paragraphs(paragraphs: list[dict], max_chars: int = 12000) -> list[list[dict]]:
    """Decoupe les paragraphes en chunks pour le traitement par batch.

    Chaque chunk fait au maximum max_chars caracteres.
    """
    chunks = []
    current_chunk = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para["text"])
        if current_size + para_size > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0

        current_chunk.append(para)
        current_size += para_size

    if current_chunk:
        chunks.append(current_chunk)

    logger.info(f"[DOCX] Split into {len(chunks)} chunks (max {max_chars} chars)")
    return chunks


# ── Annotation Word ────────────────────────────────────────────────

def _build_comment_text(verdict: AssertionVerdict) -> str:
    """Construit le texte du commentaire Word a partir du verdict."""
    emoji = STATUS_EMOJI.get(verdict.status, "❓")
    label = STATUS_LABEL.get(verdict.status, verdict.status)
    sev = SEVERITY_LABEL.get(verdict.severity, "")

    lines = [f"[OSMOSIS - {label}] {emoji}"]

    if sev:
        lines.append(sev)

    if verdict.explanation:
        lines.append("")
        lines.append(verdict.explanation)

    # Sources
    if verdict.corpus_positions:
        lines.append("")
        for pos in verdict.corpus_positions[:3]:
            rel_label = pos.relation.lower().replace("_", " ")
            lines.append(f"• {pos.doc_title}: {pos.claim_text[:100]} ({rel_label})")

    # Coherence interne (V1.5)
    if verdict.internal_conflicts:
        lines.append("")
        lines.append(f"⚠ Incoherence interne avec {len(verdict.internal_conflicts)} autre(s) affirmation(s)")

    return "\n".join(lines)


def _find_runs_for_assertion(paragraph: Paragraph, assertion_text: str):
    """Trouve les runs du paragraphe qui correspondent a l'assertion.

    Retourne paragraph.runs si l'assertion couvre tout le paragraphe,
    ou un subset de runs si possible.
    """
    # Simplification V1 : annoter tout le paragraphe
    # En V2 on pourra etre plus precis (match par position de caracteres)
    if paragraph.runs:
        return paragraph.runs
    return None


def annotate_document(
    doc: Document,
    paragraphs: list[dict],
    verdicts: list[AssertionVerdict],
    annotate_confirmed: bool = False,
) -> Document:
    """Ajoute des commentaires de review au document Word.

    Args:
        doc: Document python-docx ouvert
        paragraphs: Paragraphes extraits avec index
        verdicts: Verdicts de verification
        annotate_confirmed: Si True, annote aussi les assertions confirmees

    Returns:
        Le meme Document avec les commentaires ajoutes
    """
    # Indexer les paragraphes par index
    para_by_index = {p["index"]: p["paragraph"] for p in paragraphs}

    annotated = 0
    for verdict in verdicts:
        # Ne pas annoter les confirmees sauf si demande
        if verdict.status == "confirmed" and not annotate_confirmed:
            continue

        para = para_by_index.get(verdict.paragraph_index)
        if not para:
            continue

        runs = _find_runs_for_assertion(para, verdict.assertion_text)
        if not runs:
            continue

        comment_text = _build_comment_text(verdict)

        try:
            doc.add_comment(
                runs=runs,
                text=comment_text,
                author="OSMOSIS",
                initials="OS",
            )
            annotated += 1
        except Exception as e:
            logger.warning(f"[DOCX] Failed to add comment on paragraph {verdict.paragraph_index}: {e}")

    logger.info(f"[DOCX] Added {annotated} comments to document")
    return doc


def compute_review_metrics(verdicts: list[AssertionVerdict]) -> DocumentReviewResult:
    """Calcule les metriques globales de la review."""
    result = DocumentReviewResult(assertions=verdicts)

    for v in verdicts:
        if v.status == "confirmed":
            result.total_confirmed += 1
        elif v.status in ("contradicted", "outdated"):
            result.total_contradicted += 1
        elif v.status in ("qualified", "incomplete"):
            result.total_qualified += 1
        else:
            result.total_unknown += 1

        if v.severity == "high":
            result.high_severity_count += 1

        if v.internal_conflicts:
            result.internal_contradictions += 1

    total = len(verdicts)
    if total > 0:
        result.reliability_score = result.total_confirmed / total

    return result


def document_to_bytes(doc: Document) -> bytes:
    """Convertit un Document python-docx en bytes pour StreamingResponse."""
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()
