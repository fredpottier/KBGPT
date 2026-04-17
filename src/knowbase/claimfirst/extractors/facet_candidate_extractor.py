# src/knowbase/claimfirst/extractors/facet_candidate_extractor.py
"""
FacetCandidateExtractor — Tier 1 du Facet Registry émergent.

1 appel LLM par document → extraire 3 à 6 facettes candidates.
Pattern identique à qs_llm_extractor.py : lazy import, _build_with_llm + _parse_llm_response.

Input : DocumentContext (titre, résumé, premiers claims textes)
Output : List[FacetCandidate]
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from knowbase.claimfirst.models.document_context import DocumentContext
    from knowbase.claimfirst.models.claim import Claim

logger = logging.getLogger("[OSMOSE] facet_candidate_extractor")

# Labels vagues interdits
_VAGUE_LABELS = {
    "general", "other", "miscellaneous", "various", "diverse",
    "introduction", "conclusion", "summary", "overview", "appendix",
    "misc", "n/a", "none", "unknown",
}

# Limite du nombre de facettes par document
MAX_FACETS_PER_DOC = 6
MIN_FACETS_PER_DOC = 1


@dataclass
class FacetCandidate:
    """Facette candidate extraite par LLM depuis un document."""

    canonical_name: str
    dimension_key: str
    facet_family: str  # thematic | normative | operational
    keywords: List[str] = field(default_factory=list)
    confidence: float = 0.8
    source_doc_id: str = ""


SYSTEM_PROMPT = """You are a knowledge graph taxonomy analyst. Your job is to identify the
CROSS-CUTTING THEMATIC DIMENSIONS present in a document, based on its actual content.

A dimension is a recurring TOPIC that appears across multiple documents in a corpus.
Dimensions are discovered from the content — not from a predefined list.

WHAT TO DO:
- Read the sample claims below
- Identify 3-6 thematic dimensions that these claims belong to
- Each dimension should be specific enough to be meaningful but general enough to appear in other documents on similar topics
- Name each dimension with a clear, descriptive 2-4 word label

WHAT NOT TO DO:
- Do NOT use document titles, product names, or version numbers as dimensions
- Do NOT use generic labels like "General", "Other", "Miscellaneous", "Overview"
- Do NOT use single words that are too vague ("Data", "System", "Process")

RULES:
1. Each facet must be a thematic dimension discovered FROM the claims
2. dimension_key: format "domain.sub_domain", lowercase, snake_case, max 2 levels
3. facet_family: "thematic" (content topic), "normative" (compliance/obligations), "operational" (ops/procedures)
4. keywords: 5-10 MULTI-WORD keywords found in the claims for matching (e.g. "data subject rights" not just "rights")
5. Return 3-6 facets, each representing a DIFFERENT dimension
6. confidence: 0.0-1.0 based on how strongly this dimension appears in the claims

Respond in JSON:
{
  "facets": [
    {
      "canonical_name": "Example Dimension Name",
      "dimension_key": "example.dimension",
      "facet_family": "thematic",
      "keywords": ["multi-word keyword 1", "multi-word keyword 2", "multi-word keyword 3"],
      "confidence": 0.90
    }
  ]
}"""


def _build_user_prompt(
    doc_title: str,
    doc_summary: str,
    sample_claims: List[str],
) -> str:
    """Construit le prompt utilisateur pour l'extraction."""
    claims_text = ""
    if sample_claims:
        claims_sample = sample_claims[:10]
        claims_text = "\n".join(f"- {c[:200]}" for c in claims_sample)

    return f"""Document title: {doc_title}

Document summary:
{doc_summary[:500] if doc_summary else "(no summary available)"}

Sample claims from this document:
{claims_text if claims_text else "(no claims available)"}

Classify this document into 3-6 UNIVERSAL cross-cutting dimensions.
Remember: dimensions must be reusable across many documents (like "Security", "Compliance", "Operations"), NOT specific to this document."""


def _normalize_dimension_key(raw: str) -> str:
    """Normalise une dimension_key : lowercase, snake_case, max 3 niveaux."""
    key = raw.strip().lower()
    # Remplacer espaces et tirets par underscore
    key = re.sub(r"[\s\-]+", "_", key)
    # Ne garder que alphanum, underscore, point
    key = re.sub(r"[^a-z0-9_.]", "", key)
    # Max 3 niveaux
    parts = key.split(".")
    if len(parts) > 3:
        parts = parts[:3]
    # Pas de parties vides
    parts = [p for p in parts if p]
    return ".".join(parts) if parts else ""


def _parse_llm_response(
    raw_text: str,
    source_doc_id: str,
) -> List[FacetCandidate]:
    """
    Parse la réponse LLM et retourne les FacetCandidates validés.

    Filtre les labels vagues, normalise les dimension_keys.
    """
    # Extraire le JSON
    text = raw_text.strip()
    # Retirer les blocs markdown ```json ... ```
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"[OSMOSE:FacetExtractor] JSON invalide: {text[:200]}")
        return []

    facets_raw = data.get("facets", [])
    if not isinstance(facets_raw, list):
        logger.warning("[OSMOSE:FacetExtractor] 'facets' n'est pas une liste")
        return []

    candidates = []
    seen_keys = set()

    for item in facets_raw:
        if not isinstance(item, dict):
            continue

        name = item.get("canonical_name", "").strip()
        dim_key = _normalize_dimension_key(item.get("dimension_key", ""))
        family = item.get("facet_family", "thematic").strip().lower()
        keywords = item.get("keywords", [])
        confidence = item.get("confidence", 0.8)

        # Validations
        if not name or not dim_key:
            continue

        # Rejeter labels vagues
        if dim_key.split(".")[-1] in _VAGUE_LABELS:
            logger.debug(f"[OSMOSE:FacetExtractor] Label vague rejeté: {dim_key}")
            continue

        if name.lower() in _VAGUE_LABELS:
            continue

        # Valider family
        if family not in ("thematic", "normative", "operational"):
            family = "thematic"

        # Valider confidence
        if not isinstance(confidence, (int, float)):
            confidence = 0.8
        confidence = max(0.0, min(1.0, float(confidence)))

        # Valider keywords — garder jusqu'à 10, préférer les multi-mots
        if not isinstance(keywords, list):
            keywords = []
        keywords = [str(k).strip().lower() for k in keywords if k][:10]

        # Dédup par dimension_key
        if dim_key in seen_keys:
            continue
        seen_keys.add(dim_key)

        candidates.append(FacetCandidate(
            canonical_name=name,
            dimension_key=dim_key,
            facet_family=family,
            keywords=keywords,
            confidence=confidence,
            source_doc_id=source_doc_id,
        ))

        if len(candidates) >= MAX_FACETS_PER_DOC:
            break

    return candidates


class FacetCandidateExtractor:
    """
    Tier 1 — Extraction LLM de facettes candidates depuis un document.

    1 appel LLM par document, ~200-500 tokens.
    """

    def __init__(self):
        self.stats = {
            "docs_processed": 0,
            "candidates_extracted": 0,
            "llm_calls": 0,
            "llm_errors": 0,
        }

    def extract(
        self,
        doc_context: "DocumentContext",
        claims: Optional[List["Claim"]] = None,
        doc_title: str = "",
        doc_summary: str = "",
    ) -> List[FacetCandidate]:
        """
        Extrait les facettes candidates d'un document.

        Args:
            doc_context: Contexte du document
            claims: Claims déjà extraites (pour échantillon)
            doc_title: Titre du document (override)
            doc_summary: Résumé du document (override)

        Returns:
            Liste de FacetCandidate (3-6 par document)
        """
        self.stats["docs_processed"] += 1

        # Construire les inputs
        title = doc_title or getattr(doc_context, "doc_id", "Unknown")
        summary = doc_summary or ""

        # Extraire des titres / sujets depuis le context si dispo
        if not summary and hasattr(doc_context, "raw_subjects"):
            summary = ", ".join(doc_context.raw_subjects or [])

        sample_claims = []
        if claims:
            sample_claims = [c.text for c in claims[:10] if c.text]

        # Appel LLM
        try:
            raw_response = self._build_with_llm(title, summary, sample_claims)
            if not raw_response:
                return []
        except Exception as e:
            logger.error(f"[OSMOSE:FacetExtractor] LLM error: {e}")
            self.stats["llm_errors"] += 1
            return []

        self.stats["llm_calls"] += 1

        # Parser la réponse
        candidates = _parse_llm_response(raw_response, doc_context.doc_id)
        self.stats["candidates_extracted"] += len(candidates)

        logger.info(
            f"[OSMOSE:FacetExtractor] {len(candidates)} candidates from doc "
            f"{doc_context.doc_id[:40]}"
        )

        return candidates

    def _build_with_llm(
        self,
        doc_title: str,
        doc_summary: str,
        sample_claims: List[str],
    ) -> Optional[str]:
        """Appelle le LLM via llm_router (lazy import)."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()
        user_prompt = _build_user_prompt(doc_title, doc_summary, sample_claims)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        result = router.complete(
            task_type=TaskType.METADATA_EXTRACTION,
            messages=messages,
            max_tokens=500,
            temperature=0.3,
        )

        return result if isinstance(result, str) else None

    def get_stats(self) -> dict:
        return dict(self.stats)


__all__ = [
    "FacetCandidate",
    "FacetCandidateExtractor",
]
