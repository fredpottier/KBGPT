"""V5 Verifier — Claim segmenter (CH-52.8.1 / S7.1).

ADR V1.5 §3f §C3 : segmenter une réponse draft en claims atomiques pour
vérification individuelle vs citations.

Algorithm V1.5 minimal (sans LLM externe, déterministe) :
1. Split sentences sur ponctuation forte (. ! ? + fin)
2. Filter informational claims (skip vide/trop court/seul citation)
3. Enrich : extract citation refs `[doc=...]` ou `[Source N]` mentionnés dans/avant la phrase
4. Détecter claim_type basique (factual / opinion / numeric / temporal)

Pour la production, ajouter un LLM léger (Qwen-7B-instruct) qui décompose les
claims composés en atomiques. Interface compatible (LLMClaimSegmenter wrapper).

Charte domain-agnostic strict : split universel multilingue, pas de regex SAP/médical/etc.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ClaimType(str, Enum):
    """Catégorie d'un claim (heuristique universelle)."""
    FACTUAL = "factual"  # affirmation factuelle générique
    NUMERIC = "numeric"  # contient nombre + unité ou pourcentage
    TEMPORAL = "temporal"  # contient date/durée
    COMPARATIVE = "comparative"  # contient comparaison (more, less, vs)
    OPINION = "opinion"  # exprime opinion/recommandation (heuristique souple)
    META = "meta"  # claim méta sur la réponse (e.g. "based on...")


# Patterns universels (multilingue minimal)
_SENTENCE_SPLIT = re.compile(
    r"(?<=[.!?])\s+(?=[A-ZÀ-Ý\d])"  # split sur ponctuation forte + capital/digit suivant
)
_CITATION_INLINE = re.compile(
    r"\[(?:doc=([^\]\s]+)(?:\s+section=([^\]\s]+))?|Source\s+(\d+)|"
    r"(\d+))\]",
    re.IGNORECASE,
)
_NUMERIC_HINT = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|hours?|days?|months?|years?|GB|TB|MB|KB|"
    r"euros?|dollars?|EUR|USD|GBP|JPY|CHF|"
    r"\$|€|£|¥|minutes?|seconds?|ms)(?:\b|(?=\s)|$)",
    re.IGNORECASE,
)
_TEMPORAL_HINT = re.compile(
    r"\b(?:\d{4}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|since|until|after|before|"
    r"depuis|jusqu'?en?|avant|après|seit|bis|nach|vor)\b",
    re.IGNORECASE,
)
_COMPARATIVE_HINT = re.compile(
    r"\b(?:more|less|higher|lower|faster|slower|than|vs|versus|compared|"
    r"plus|moins|mieux|pire|que|comparé|verglichen|mehr|weniger)\b",
    re.IGNORECASE,
)
_OPINION_HINT = re.compile(
    r"\b(?:should|must|recommend|suggest|likely|probably|may|might|"
    r"devrait|doit|recommande|sugg|probablement|sollte|empfiehlt|"
    r"vermutlich)\b",
    re.IGNORECASE,
)


# ─── Pydantic Schemas ────────────────────────────────────────────────────────


class CitationRefExtracted(BaseModel):
    """Référence citation extraite d'un claim."""
    model_config = ConfigDict(extra="forbid")
    raw: str  # ex: "[doc=003_xxx section=sec_1]"
    doc_id: Optional[str] = None
    section_id: Optional[str] = None
    source_index: Optional[int] = None  # pour [Source 1]


class Claim(BaseModel):
    """Un claim atomique extrait d'une réponse."""
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1, max_length=4000)
    claim_type: ClaimType = ClaimType.FACTUAL
    citations: list[CitationRefExtracted] = Field(default_factory=list)
    span_start: int = Field(default=0, ge=0)
    span_end: int = Field(default=0, ge=0)
    has_citation: bool = False


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _extract_citations(sentence: str) -> list[CitationRefExtracted]:
    """Extrait les références citations [doc=X] / [Source N] d'une phrase."""
    refs = []
    for m in _CITATION_INLINE.finditer(sentence):
        raw = m.group(0)
        doc_id = m.group(1)
        section_id = m.group(2)
        source_idx_str = m.group(3) or m.group(4)
        source_index = int(source_idx_str) if source_idx_str else None
        refs.append(CitationRefExtracted(
            raw=raw,
            doc_id=doc_id,
            section_id=section_id,
            source_index=source_index,
        ))
    return refs


def _classify_claim(sentence: str) -> ClaimType:
    """Heuristique de classification (priorité numeric > temporal > comparative > opinion)."""
    if _NUMERIC_HINT.search(sentence):
        return ClaimType.NUMERIC
    if _TEMPORAL_HINT.search(sentence):
        return ClaimType.TEMPORAL
    if _COMPARATIVE_HINT.search(sentence):
        return ClaimType.COMPARATIVE
    if _OPINION_HINT.search(sentence):
        return ClaimType.OPINION
    return ClaimType.FACTUAL


def _is_meta_or_skip(sentence: str) -> bool:
    """Skip phrases vides ou très courtes (filter informational)."""
    cleaned = sentence.strip()
    if not cleaned or len(cleaned) < 10:
        return True
    # Skip phrases composées uniquement de citation
    if _CITATION_INLINE.fullmatch(cleaned):
        return True
    # Skip phrases méta génériques (heuristique souple)
    meta_starters = (
        "based on", "according to", "as shown in",
        "selon", "d'après", "comme indiqué",
        "basierend auf", "laut",
    )
    lower = cleaned.lower()
    if any(lower.startswith(m) for m in meta_starters) and len(cleaned) < 80:
        return True
    return False


# ─── ClaimSegmenter ──────────────────────────────────────────────────────────


class ClaimSegmenter:
    """Segmenter déterministe (sans LLM).

    Args:
        min_claim_chars : longueur minimale pour considérer un claim (default 10)
        max_claims : limite N claims retournés (default 50, évite explosion)
        skip_meta : skip phrases meta-informatives (default True)
    """

    def __init__(
        self,
        min_claim_chars: int = 10,
        max_claims: int = 50,
        skip_meta: bool = True,
    ):
        self.min_claim_chars = min_claim_chars
        self.max_claims = max_claims
        self.skip_meta = skip_meta

    def segment(self, answer_text: str) -> list[Claim]:
        """Segmente une réponse en claims atomiques.

        Args:
            answer_text : texte de la réponse draft

        Returns:
            Liste de Claim ordonnée par span_start
        """
        if not answer_text or not answer_text.strip():
            return []

        # Split phrases
        sentences = _SENTENCE_SPLIT.split(answer_text)
        claims = []
        offset = 0
        for raw_sent in sentences:
            sent = raw_sent.strip()
            if not sent:
                offset += len(raw_sent) + 1  # account for split space
                continue
            start = answer_text.find(sent, offset)
            if start < 0:
                start = offset
            end = start + len(sent)
            offset = end

            # Filter
            if len(sent) < self.min_claim_chars:
                continue
            if self.skip_meta and _is_meta_or_skip(sent):
                continue

            # Build claim
            citations = _extract_citations(sent)
            claim = Claim(
                text=sent,
                claim_type=_classify_claim(sent),
                citations=citations,
                span_start=start,
                span_end=end,
                has_citation=bool(citations),
            )
            claims.append(claim)
            if len(claims) >= self.max_claims:
                break

        return claims

    def stats(self, claims: list[Claim]) -> dict:
        """Stats sur la liste de claims (citation rate, types distrib)."""
        if not claims:
            return {
                "n_claims": 0,
                "citation_rate": 0.0,
                "by_type": {},
            }
        by_type = {}
        n_cited = 0
        for c in claims:
            by_type[c.claim_type.value] = by_type.get(c.claim_type.value, 0) + 1
            if c.has_citation:
                n_cited += 1
        return {
            "n_claims": len(claims),
            "citation_rate": n_cited / len(claims),
            "by_type": by_type,
        }
