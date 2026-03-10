# src/knowbase/claimfirst/extractors/question_signature_extractor.py
"""
QuestionSignature Extractor — Level A (patterns regex déterministes).

Extrait des QuestionSignatures depuis les claims en utilisant des patterns
regex. Précision ~100%, zéro coût LLM.

Patterns couverts (IT/infra) :
- Minimum/maximum version, RAM, connections, etc.
- Requires protocol/technology
- Default values
- Deprecated/end-of-support
- Supported platforms/databases
- Timeout/retention/limit values
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.question_signature import (
    QuestionSignature,
    QSExtractionLevel,
    QSValueType,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Pattern definitions
# =============================================================================


@dataclass
class QSPattern:
    """Définition d'un pattern Level A."""

    name: str
    regex: re.Pattern
    dimension_key: str
    question_template: str  # {subject}, {value}, {unit} placeholders
    value_type: QSValueType
    value_group: int = 1  # Groupe regex pour la valeur extraite
    subject_group: int = 0  # 0 = pas de groupe sujet (utiliser structured_form)


# Patterns Level A — ~12 patterns IT/infra

LEVEL_A_PATTERNS: List[QSPattern] = [
    # --- Version requirements ---
    QSPattern(
        name="minimum_version",
        regex=re.compile(
            r"(?:minimum|min\.?)\s+(?:required\s+)?version\s+(?:is\s+)?[\"']?(\d[\w.]+)[\"']?",
            re.IGNORECASE,
        ),
        dimension_key="min_version",
        question_template="What is the minimum version of {subject}?",
        value_type=QSValueType.VERSION,
    ),
    QSPattern(
        name="minimum_version_required",
        regex=re.compile(
            r"(\d[\w.]+)\s+is\s+the\s+minimum\s+(?:required\s+)?version",
            re.IGNORECASE,
        ),
        dimension_key="min_version",
        question_template="What is the minimum version of {subject}?",
        value_type=QSValueType.VERSION,
    ),
    QSPattern(
        name="requires_version",
        regex=re.compile(
            r"requires?\s+(?:at\s+least\s+)?(?:version\s+)?(\d[\w.]+)",
            re.IGNORECASE,
        ),
        dimension_key="required_version",
        question_template="What version does {subject} require?",
        value_type=QSValueType.VERSION,
    ),

    # --- Numeric requirements (RAM, connections, etc.) ---
    QSPattern(
        name="minimum_ram",
        regex=re.compile(
            r"(?:minimum|min\.?)\s+(?:required\s+)?(?:RAM|memory)\s+(?:is\s+)?(\d+)\s*(GB|MB|TB|GiB)",
            re.IGNORECASE,
        ),
        dimension_key="min_ram",
        question_template="What is the minimum RAM for {subject}?",
        value_type=QSValueType.NUMBER,
        value_group=1,
    ),
    QSPattern(
        name="minimum_ram_reverse",
        regex=re.compile(
            r"(\d+)\s*(GB|MB|TB|GiB)\s+(?:of\s+)?(?:RAM|memory)\s+(?:is\s+)?(?:required|minimum|needed)",
            re.IGNORECASE,
        ),
        dimension_key="min_ram",
        question_template="What is the minimum RAM for {subject}?",
        value_type=QSValueType.NUMBER,
        value_group=1,
    ),
    QSPattern(
        name="maximum_connections",
        regex=re.compile(
            r"(?:maximum|max\.?)\s+(?:number\s+of\s+)?(?:concurrent\s+)?connections?\s+(?:is\s+)?(\d[\d,]*)",
            re.IGNORECASE,
        ),
        dimension_key="max_connections",
        question_template="What is the maximum number of connections for {subject}?",
        value_type=QSValueType.NUMBER,
    ),
    QSPattern(
        name="maximum_value_generic",
        regex=re.compile(
            r"(?:maximum|max\.?)\s+(\w[\w\s]{2,20}?)\s+(?:is|of)\s+(\d[\d,.]*)\s*(\w+)?",
            re.IGNORECASE,
        ),
        dimension_key="max_{dim}",
        question_template="What is the maximum {dim} for {subject}?",
        value_type=QSValueType.NUMBER,
        value_group=2,
    ),

    # --- Protocol/technology requirements ---
    QSPattern(
        name="requires_protocol",
        regex=re.compile(
            r"requires?\s+(TLS|SSL|HTTPS?|SSH|SFTP|LDAPS?|OAuth\s*2?\.?0?|SAML|Kerberos)\s*(\d[\d.]*)?",
            re.IGNORECASE,
        ),
        dimension_key="required_protocol",
        question_template="What protocol does {subject} require?",
        value_type=QSValueType.STRING,
    ),

    # --- Default values ---
    QSPattern(
        name="default_value",
        regex=re.compile(
            r"(?:the\s+)?default\s+(?:value\s+)?(?:is|=)\s+[\"']?(\w[\w\s./-]{0,30}?)[\"']?(?:\s*[.,;)]|$)",
            re.IGNORECASE,
        ),
        dimension_key="default_value",
        question_template="What is the default value for {subject}?",
        value_type=QSValueType.STRING,
    ),
    QSPattern(
        name="default_port",
        regex=re.compile(
            r"default\s+port\s+(?:(?:is|of)\s+)?(\d{2,5})",
            re.IGNORECASE,
        ),
        dimension_key="default_port",
        question_template="What is the default port for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Deprecation/end-of-support ---
    QSPattern(
        name="deprecated_since",
        regex=re.compile(
            r"deprecated\s+(?:since|as\s+of|in)\s+(\w[\w\s./-]{2,20})",
            re.IGNORECASE,
        ),
        dimension_key="deprecated_since",
        question_template="Since when is {subject} deprecated?",
        value_type=QSValueType.STRING,
    ),
    QSPattern(
        name="end_of_support",
        regex=re.compile(
            r"end\s+of\s+(?:mainstream\s+)?(?:support|maintenance|life)\s*(?::|is|date)?\s*(\w[\w\s./-]{2,20})",
            re.IGNORECASE,
        ),
        dimension_key="end_of_support",
        question_template="When is the end of support for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Timeout/retention ---
    QSPattern(
        name="timeout_value",
        regex=re.compile(
            r"(?:session\s+)?timeout\s+(?:is\s+)?(?:set\s+to\s+)?(\d+)\s*(seconds?|minutes?|hours?|ms|s|min|hrs?)",
            re.IGNORECASE,
        ),
        dimension_key="timeout",
        question_template="What is the timeout for {subject}?",
        value_type=QSValueType.NUMBER,
    ),
    QSPattern(
        name="retention_period",
        regex=re.compile(
            r"(?:data\s+)?retention\s+(?:period\s+)?(?:is\s+)?(\d+)\s*(days?|months?|years?|weeks?)",
            re.IGNORECASE,
        ),
        dimension_key="retention_period",
        question_template="What is the retention period for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Limit values ---
    QSPattern(
        name="limit_generic",
        regex=re.compile(
            r"(?:hard|soft)?\s*limit\s+(?:is\s+|of\s+)?(\d[\d,.]*)\s*(\w+)?",
            re.IGNORECASE,
        ),
        dimension_key="limit",
        question_template="What is the limit for {subject}?",
        value_type=QSValueType.NUMBER,
    ),
]


# =============================================================================
# Extractor
# =============================================================================


MAX_QS_PER_DOC = 50


def extract_question_signatures_level_a(
    claims: List[Any],
    doc_id: str,
    tenant_id: str = "default",
) -> List[QuestionSignature]:
    """
    Extrait des QuestionSignatures Level A (regex) depuis une liste de claims.

    Args:
        claims: Liste de claims (doivent avoir .claim_id, .text, .structured_form)
        doc_id: ID du document
        tenant_id: Tenant ID

    Returns:
        Liste de QuestionSignatures (max MAX_QS_PER_DOC par document)
    """
    results: List[QuestionSignature] = []
    seen_keys: set = set()  # Déduplicate dimension_key+value par doc

    for claim in claims:
        text = getattr(claim, "text", "") or ""
        claim_id = getattr(claim, "claim_id", "")
        sf = getattr(claim, "structured_form", None) or {}

        if not text or len(text) < 20:
            continue

        subject = sf.get("subject", "")

        for pattern in LEVEL_A_PATTERNS:
            match = pattern.regex.search(text)
            if not match:
                continue

            # Extraire la valeur
            try:
                raw_value = match.group(pattern.value_group).strip()
            except (IndexError, AttributeError):
                continue

            if not raw_value or len(raw_value) > 50:
                continue

            # Dimension key (résoudre {dim} pour les patterns génériques)
            dim_key = pattern.dimension_key
            if "{dim}" in dim_key:
                dim_part = match.group(1).strip().lower()
                dim_part = re.sub(r"[^a-z0-9]+", "_", dim_part).strip("_")[:30]
                dim_key = dim_key.replace("{dim}", dim_part)

            # Déduplication par dimension_key + valeur
            dedup_key = f"{dim_key}:{raw_value}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            # Construire la question
            question = pattern.question_template.replace("{subject}", subject or "this component")
            if "{dim}" in question:
                dim_label = match.group(1).strip() if match.lastindex >= 1 else ""
                question = question.replace("{dim}", dim_label)

            qs = QuestionSignature(
                qs_id=f"qs_{claim_id}_{pattern.name}",
                claim_id=claim_id,
                doc_id=doc_id,
                tenant_id=tenant_id,
                question=question,
                dimension_key=dim_key,
                value_type=pattern.value_type,
                extracted_value=raw_value,
                extraction_level=QSExtractionLevel.LEVEL_A,
                pattern_name=pattern.name,
                confidence=1.0,
                scope_subject=subject or None,
            )
            results.append(qs)

            if len(results) >= MAX_QS_PER_DOC:
                logger.info(
                    f"[OSMOSE:QS] Cap atteint: {MAX_QS_PER_DOC} QS pour doc {doc_id}"
                )
                return results

    logger.info(
        f"[OSMOSE:QS] Extracted {len(results)} QuestionSignatures (Level A) "
        f"from doc {doc_id}"
    )
    return results


__all__ = [
    "LEVEL_A_PATTERNS",
    "QSPattern",
    "MAX_QS_PER_DOC",
    "extract_question_signatures_level_a",
]
