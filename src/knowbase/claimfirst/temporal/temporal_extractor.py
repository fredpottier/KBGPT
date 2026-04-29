"""
TemporalExtractor V3.3 claim-level — LLM evidence-locked sémantique.

Pour un claim avec signal Tier 3, demande au LLM Qwen2.5-14B d'extraire
les dates claim-level (validity_start/end) avec leur date_role.

Pattern V3.3 :
- Prompt sémantique pur (anti-pattern lexical respecté)
- Multilingue + domain-agnostic
- Champ date_role explicite (adoption/publication/effective/applicable_from/expiry/...)
- Evidence_quote verbatim required
- Validator post-LLM rejette les quotes non présentes

NB : la pré-sélection des candidats (`has_temporal_signal`) utilise un regex
**numérique universel** (chiffres + délimiteurs de dates), pas de keywords
lexicaux EN. Cela respecte l'anti-pattern : on filtre juste pour économiser
le LLM, on n'extrait pas de sémantique au regex.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from knowbase.claimfirst.applicability.evidence_validator_v2 import (
    normalize_for_match,
    quote_is_present,
)
from knowbase.claimfirst.applicability.models import DateField, DateRole, FrameFieldConfidence

logger = logging.getLogger(__name__)


# ============================================================================
# Pre-filter : signal Tier 3 (regex universel — pas de keywords lexicaux)
# ============================================================================
# On capture toute trace numérique de date, dans toutes langues/domaines :
# - Années 19xx-20xx (universel, ne dépend ni langue ni domaine)
# - Dates ISO YYYY-MM-DD
# - Dates DD/MM/YYYY ou DD.MM.YYYY ou DD-MM-YYYY
# Le LLM filtrera sémantiquement ensuite.

_TEMPORAL_REGEX = re.compile(
    r"\b(19|20)[0-9]{2}\b"                # year 19xx-20xx
    r"|"
    r"\b\d{1,2}[./\-]\d{1,2}[./\-](19|20)?\d{2,4}\b"  # DD.MM.YYYY etc
)


def has_temporal_signal(passage_text: Optional[str]) -> bool:
    """
    Détecte si un passage_text contient au moins un signal numérique de date.

    Pattern universel (pas de keywords lexicaux). Sert de pré-filtre pour
    sélectionner les candidats Tier 4 LLM.
    """
    if not passage_text:
        return False
    return bool(_TEMPORAL_REGEX.search(passage_text))


# ============================================================================
# Result dataclass
# ============================================================================

@dataclass
class ClaimTemporalResult:
    """Résultat extraction TemporalFrame claim-level."""

    claim_id: str
    publication_date: Optional[DateField] = None
    validity_start: Optional[DateField] = None
    validity_end: Optional[DateField] = None
    rejected_fields: list[dict] = field(default_factory=list)
    method: str = "unknown"
    elapsed_s: float = 0.0
    tokens: dict = field(default_factory=dict)


# ============================================================================
# LLM prompt — sémantique pur, claim-level
# ============================================================================

PROMPT_SYSTEM_CLAIM_TEMPORAL = """You are a regulatory analyst extracting claim-level temporal information.

Given a single claim and its surrounding passage, extract the dates that apply
SPECIFICALLY to this claim's rule (NOT the document's publication date — that
is handled separately at the document level).

The 3 distinct dates and their roles:

- **publication_date**: rare at claim-level; only set if the passage explicitly
  attributes a publication/issue date to THIS particular rule (not the document).
  date_role = "publication".

- **validity_start**: when the rule described in this claim BEGINS to apply.
  Example: "rule X applies to certifications requested AFTER 31 December 2014"
  → validity_start = "2015-01-01", date_role = "applicable_from".
  date_role = "effective" or "applicable_from".

- **validity_end**: when the rule ceases to apply (or null).
  date_role = "expiry".

CRITICAL — multilingual + domain-agnostic:
- You handle EN/FR/DE/ES/IT/... and any domain
- Identify the SEMANTIC of dates by the surrounding context, not specific keywords
- "after [date]" / "from [date]" / "à compter du" / "à partir de" / "ab dem" / etc.
  all express the same applicability_from concept
- Do NOT hallucinate. If the passage does not explicitly attribute a date to this
  claim's applicability, return null for all fields.

Output JSON schema:
{
  "publication_date": {"value": "YYYY" | "YYYY-MM-DD" | null, "date_role": "publication", "evidence_quote": "..." | null, "confidence": "high|medium|low"},
  "validity_start": {"value": "YYYY-MM-DD" | null, "date_role": "effective" | "applicable_from", "evidence_quote": "..." | null, "confidence": "high|medium|low"},
  "validity_end": {"value": "YYYY-MM-DD" | null, "date_role": "expiry", "evidence_quote": "..." | null, "confidence": "high|medium|low"}
}

For EACH non-null value, provide an evidence_quote that appears VERBATIM in the
passage. The system will verify by substring match. If you cannot cite, set
the value to null."""


# ============================================================================
# TemporalExtractor class
# ============================================================================

class TemporalExtractor:
    """
    Layer C V3.3 claim-level — extraction temporelle evidence-locked.

    Pour les claims avec signal Tier 3, appelle le LLM avec un prompt sémantique
    pur et applique le validator V2 sur le résultat.
    """

    def __init__(
        self,
        vllm_url: str = "http://localhost:8000",
        model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
        timeout_s: float = 60.0,
    ):
        self.vllm_url = vllm_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    def extract(
        self,
        claim_id: str,
        claim_text: str,
        passage_text: str,
    ) -> ClaimTemporalResult:
        """
        Extrait validity_start/end claim-level depuis passage_text.

        Args:
            claim_id: Identifiant du claim
            claim_text: Texte synthétique du claim (input contextuel)
            passage_text: Source d'autorité pour les evidence_quote

        Returns:
            ClaimTemporalResult avec dates validées (ou None) + métadonnées
        """
        result = ClaimTemporalResult(claim_id=claim_id)
        if not passage_text:
            result.method = "no_passage"
            return result

        # 1. Call LLM
        try:
            llm_data, elapsed, tokens = self._call_llm(claim_text, passage_text)
            result.elapsed_s = elapsed
            result.tokens = tokens
        except Exception as e:
            logger.warning(f"[OSMOSE:TemporalExtractor] LLM failed for {claim_id}: {e}")
            result.method = "llm_failed"
            return result

        # 2. Parse output
        publication_date = self._parse_date_field(llm_data.get("publication_date"))
        validity_start = self._parse_date_field(llm_data.get("validity_start"))
        validity_end = self._parse_date_field(llm_data.get("validity_end"))

        # 3. Validate evidence-locked + date_role
        full_text_norm = normalize_for_match(passage_text)
        rejects: list[dict] = []

        result.publication_date = self._validate_date(
            publication_date, full_text_norm, "publication_date",
            {DateRole.PUBLICATION}, rejects,
        )
        result.validity_start = self._validate_date(
            validity_start, full_text_norm, "validity_start",
            {DateRole.EFFECTIVE, DateRole.APPLICABLE_FROM}, rejects,
        )
        result.validity_end = self._validate_date(
            validity_end, full_text_norm, "validity_end",
            {DateRole.EXPIRY}, rejects,
        )
        result.rejected_fields = rejects
        result.method = "tier4_llm_evidence_locked"

        return result

    def _call_llm(self, claim_text: str, passage_text: str) -> tuple[dict, float, dict]:
        """Appelle vLLM, retourne (parsed_dict, elapsed_s, tokens)."""
        # Tronquer passage_text si trop long (rester ~2000 tokens budget input)
        passage_excerpt = passage_text[:3000]

        user_prompt = f"""Claim text:
{claim_text}

Passage (the AUTHORITATIVE source for evidence_quotes — only what is here can be cited):
{passage_excerpt}

Extract claim-level temporal information (publication_date, validity_start, validity_end).
If the passage does not attribute specific dates to this claim's applicability, set values to null."""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": PROMPT_SYSTEM_CLAIM_TEMPORAL},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }

        t0 = time.time()
        r = httpx.post(f"{self.vllm_url}/v1/chat/completions", json=payload, timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json()
        elapsed = time.time() - t0
        content = data["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Tenter d'extraire un objet JSON
            m = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(m.group(0)) if m else {}
        return parsed, elapsed, data.get("usage", {})

    def _parse_date_field(self, data) -> Optional[DateField]:
        """Parse un dict {value, date_role, evidence_quote, confidence} en DateField."""
        if not data or not isinstance(data, dict):
            return None
        value = data.get("value")
        if value is None or value == "":
            return None
        date_role_str = (data.get("date_role") or "unknown").lower()
        try:
            date_role = DateRole(date_role_str)
        except ValueError:
            date_role = DateRole.UNKNOWN
        confidence_str = (data.get("confidence") or "medium").lower()
        try:
            conf = FrameFieldConfidence(confidence_str)
        except ValueError:
            conf = FrameFieldConfidence.MEDIUM
        return DateField(
            value=str(value),
            date_role=date_role,
            evidence_quote=data.get("evidence_quote") or data.get("quote"),
            source="tier4_llm",
            confidence=conf,
        )

    def _validate_date(
        self,
        field: Optional[DateField],
        full_text_norm: str,
        field_name: str,
        expected_roles: set[DateRole],
        rejects: list,
    ) -> Optional[DateField]:
        """Validate date evidence_quote + date_role. Returns cleaned field or None."""
        if field is None or field.value is None:
            return None
        if not quote_is_present(field.evidence_quote, full_text_norm):
            rejects.append({
                "field": field_name,
                "value": field.value,
                "quote": field.evidence_quote,
                "date_role": field.date_role.value,
                "reason": "quote not found in passage",
            })
            return None
        if field.date_role not in expected_roles:
            rejects.append({
                "field": field_name,
                "value": field.value,
                "quote": field.evidence_quote,
                "date_role": field.date_role.value,
                "reason": f"date_role {field.date_role.value} not allowed for {field_name}",
            })
            return None
        return field


__all__ = [
    "TemporalExtractor",
    "ClaimTemporalResult",
    "has_temporal_signal",
    "PROMPT_SYSTEM_CLAIM_TEMPORAL",
]
