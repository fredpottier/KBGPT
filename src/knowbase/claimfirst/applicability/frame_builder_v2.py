"""
Layer C V2 — FrameBuilder V3.3 (3 axes orthogonaux + evidence-locked sémantique).

Différences vs V1 (frame_builder.py) :
1. Output : ApplicabilityFrameV2 (3 axes Scope/Temporality/Lifecycle) au lieu d'ApplicabilityFrame (fields plats)
2. Prompt 100% sémantique (anti-pattern lexical V3.3) — multilingue + domain-agnostic
3. Distinction explicite des 3 dates avec champ `date_role` (publication/effective/applicable_from/expiry/...)
4. Inputs : Tier1Hints (déterministe, prior fiable) + 5000 chars du full_text + primary_subject
5. Validator post-LLM appliqué automatiquement (evidence_validator_v2.validate_frame_v2)

Domain Pack hints sémantiques optionnels (pas de regex) : si un domain_context_prompt
est fourni, il est injecté comme contexte sémantique pour aider le LLM à comprendre
les conventions du domaine (ex: "EASA documents reference ED Decisions for effective
dates separately"). Ces hints sont des suggestions, pas des règles à matcher.

Anti-pattern V3.3 respecté : aucun keyword/regex spécifique langue ou domaine dans
le prompt système. Le LLM Qwen2.5-14B est multilingue + domain-agnostic par
construction et identifie les marqueurs sémantiques tout seul.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import httpx

from knowbase.claimfirst.applicability.evidence_validator_v2 import validate_frame_v2
from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrameV2,
    DateField,
    DateRole,
    EvidenceLockedField,
    FrameFieldConfidence,
    LifecycleAxis,
    LifecycleStatus,
    ScopeAxis,
    TemporalityAxis,
)
from knowbase.claimfirst.applicability.tier1_deterministic import Tier1Hints

logger = logging.getLogger(__name__)


# ============================================================================
# Prompt système V3.3 — sémantique pur (anti-pattern lexical)
# ============================================================================

PROMPT_SYSTEM_V33 = """You are a document analyst extracting an evidence-locked ApplicabilityFrame V2 from any kind of document (regulatory, technical, legal, medical, etc.) in any language.

The frame has 3 ORTHOGONAL axes:

## Axis 1: Scope (invariant — what the document/rules apply to)
- product_version: the named product/system/standard version this document concerns
- region: the geographical/jurisdictional area (e.g., EU, US, ICAO, global)
- edition: the version/amendment/revision number of THIS document
- conditions: list of textual conditions limiting applicability
- subject_class: a short domain class label (e.g., "aircraft_certification", "dual_use_export", "medical_device", "data_protection")

## Axis 2: Temporality — THREE DISTINCT DATES (do NOT confuse them)
- **publication_date**: when THIS document itself was authored/issued/published.
  This is the date the document came into existence as a written artifact.
  date_role MUST be "publication".

- **validity_start**: when the RULES described in this document BEGIN TO APPLY.
  This is the date from which compliance is required.
  Critical: this is OFTEN DIFFERENT from publication_date.
  A document published on 2024-10-12 may state that its rules apply from 2025-01-01.
  date_role MUST be "effective" or "applicable_from".

  IMPORTANT: do NOT use a "date of adoption" or "date of signature" as validity_start.
  In EU regulatory documents, "of [date]" in the title is typically the ADOPTION date,
  NOT the effective date. The effective date is stated in a separate clause
  (often "shall apply from", "enters into force on", or in any language equivalent).
  If the document does not explicitly state when its rules begin to apply, set
  validity_start.value = null. Unknown is better than wrong.

- **validity_end**: when the rules cease to apply (or null if still active or unstated).
  date_role MUST be "expiry".

For each date, provide a `date_role` field with the semantic role you identified:
- "adoption": political adoption/signing of the text
- "signature": individual signature
- "publication": official publication
- "effective": when rules become effective
- "applicable_from": synonymous with effective
- "expiry": cessation date
- "review_date": planned review (NOT a cessation)
- "unknown": cannot determine

Only "publication" populates publication_date. Only "effective"/"applicable_from"
populate validity_start. Only "expiry" populates validity_end.

## Axis 3: Lifecycle (current status of the document/rules)
- status: ACTIVE | PROVISIONAL | DEPRECATED | SUPERSEDED | RETIRED | WITHDRAWN | DRAFT | UNKNOWN
- supersedes: list of prior documents this replaces
- superseded_by: document that replaces this (or null — usually unknown from a single doc)
- evolves_from: predecessor document (or null)

## Output requirements (V3.3 evidence-locked)
For EVERY non-null value, provide an `evidence_quote` field with a verbatim citation
from the inputs (max 100 chars). The system will verify the quote is literally in
the source by substring match (case-insensitive, whitespace-collapsed).

If you cannot find a verbatim citation, the value MUST be null. No inferences,
no prior knowledge, no "plausible" guesses. Only what is explicitly written.

## Multilingual / multi-domain
You handle EN/FR/DE/ES/IT/... and any domain (regulatory/technical/medical/legal/IT/aerospace/...)
by understanding the SEMANTIC of the text. You do NOT rely on specific keyword patterns.
Different languages and domains express the same concepts differently — you understand them all.

## Output JSON schema

{
  "scope": {
    "product_version": {"value": "..." | null, "evidence_quote": "..." | null, "confidence": "high|medium|low"},
    "region": {"value": "..." | null, "evidence_quote": "..." | null, "confidence": "high|medium|low"},
    "edition": {"value": "..." | null, "evidence_quote": "..." | null, "confidence": "high|medium|low"},
    "conditions": [{"value": "...", "evidence_quote": "...", "confidence": "high|medium|low"}],
    "subject_class": {"value": "..." | null, "evidence_quote": "..." | null, "confidence": "high|medium|low"}
  },
  "temporality": {
    "publication_date": {"value": "YYYY" | "YYYY-MM-DD" | null, "date_role": "publication", "evidence_quote": "..." | null, "confidence": "high|medium|low"},
    "validity_start": {"value": "YYYY-MM-DD" | null, "date_role": "effective" | "applicable_from", "evidence_quote": "..." | null, "confidence": "high|medium|low"},
    "validity_end": {"value": "YYYY-MM-DD" | null, "date_role": "expiry", "evidence_quote": "..." | null, "confidence": "high|medium|low"},
    "publication_validity_relationship": "same_date" | "validity_after_publication" | "validity_before_publication" | "unknown"
  },
  "lifecycle": {
    "status": "ACTIVE" | "PROVISIONAL" | "DEPRECATED" | "SUPERSEDED" | "RETIRED" | "WITHDRAWN" | "DRAFT" | "UNKNOWN",
    "status_evidence_quote": "..." | null,
    "supersedes": [{"value": "...", "evidence_quote": "...", "confidence": "high|medium|low"}],
    "superseded_by": {"value": "..." | null, "evidence_quote": "..." | null, "confidence": "high|medium|low"},
    "evolves_from": {"value": "..." | null, "evidence_quote": "..." | null, "confidence": "high|medium|low"}
  }
}

If you cannot determine a value, omit it or set it to null. Never fabricate."""


# ============================================================================
# FrameBuilder V2 class
# ============================================================================

class FrameBuilderV2:
    """
    Layer C V2 — Construction du frame d'applicabilité V3.3.

    Pattern : Tier 1 hints (déterministe) → LLM Tier 2 (sémantique evidence-locked) → Validator.
    """

    def __init__(
        self,
        vllm_url: str = "http://localhost:8000",
        model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
        timeout_s: float = 90.0,
        full_text_window_chars: int = 5000,
    ):
        """
        Args:
            vllm_url: URL du serveur vLLM (EC2 ou local)
            model: Modèle vLLM à utiliser
            timeout_s: Timeout HTTP
            full_text_window_chars: Nombre de chars du full_text à passer au LLM
                (compromise input vs context window — 5000 = ~1500 tokens, OK pour Qwen2.5-14B)
        """
        self.vllm_url = vllm_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.full_text_window_chars = full_text_window_chars

    def build(
        self,
        doc_id: str,
        full_text: str,
        primary_subject: Optional[str] = None,
        document_type: Optional[str] = None,
        language: Optional[str] = None,
        tier1_hints: Optional[Tier1Hints] = None,
        domain_pack_hints: Optional[str] = None,
    ) -> ApplicabilityFrameV2:
        """
        Construit un ApplicabilityFrameV2 evidence-locked pour un document.

        Args:
            doc_id: Identifiant du document
            full_text: Texte complet (source d'autorité pour les evidence_quote)
            primary_subject: DocumentContext.primary_subject
            document_type: DocumentContext.document_type
            language: DocumentContext.language (info pour le LLM)
            tier1_hints: Hints déterministes (filename + cache markers) — recommandé
            domain_pack_hints: Prose contextuelle du Domain Pack actif (optionnel)

        Returns:
            ApplicabilityFrameV2 validé (evidence-locked + date_role correct)
        """
        # 1. Build Tier 1 fields (sans LLM)
        tier1_fields = self._build_tier1_fields(tier1_hints) if tier1_hints else None

        # 2. Call LLM Tier 2
        excerpt = full_text[: self.full_text_window_chars]
        try:
            llm_output = self._call_llm(
                doc_id=doc_id,
                full_text_excerpt=excerpt,
                primary_subject=primary_subject,
                document_type=document_type,
                language=language,
                tier1_hints=tier1_hints,
                domain_pack_hints=domain_pack_hints,
            )
        except Exception as e:
            logger.error(f"[OSMOSE:FrameBuilderV2] LLM call failed for {doc_id}: {e}")
            # Fallback : Tier 1 only
            return self._build_from_tier1_only(doc_id, tier1_fields)

        # 3. Parse LLM output into ApplicabilityFrameV2 (pas de merge Tier 1 ici)
        frame = self._parse_llm_output(doc_id, llm_output)

        # 4. Validate evidence-locked (peut reset LLM fields à None)
        frame = validate_frame_v2(frame, full_text)

        # 5. Apply Tier 1 fallback APRÈS validation
        # Si le LLM a été rejeté (field=None), on récupère depuis Tier 1 (déterministe).
        # Tier 1 fields ont source="tier1_filename" → exemptés du validator.
        if tier1_fields:
            self._apply_tier1_fallback(frame, tier1_fields)

        # 6. Annotate method
        if tier1_fields:
            frame.method = "tier1_deterministic+tier2_llm_evidence_locked"
        else:
            frame.method = "tier2_llm_evidence_locked_only"

        return frame

    # ------------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------------

    def _build_tier1_fields(self, hints: Tier1Hints) -> dict:
        """Convertit Tier1Hints en EvidenceLockedField/DateField."""
        out: dict[str, Any] = {}

        if hints.product_version:
            out["product_version"] = EvidenceLockedField(
                value=hints.product_version,
                evidence_quote=None,  # Pas requis pour Tier 1 (déterministe)
                source="tier1_filename",
                confidence=FrameFieldConfidence.HIGH,
            )
        if hints.region:
            out["region"] = EvidenceLockedField(
                value=hints.region,
                source="tier1_filename",
                confidence=FrameFieldConfidence.HIGH,
            )
        if hints.edition_label:
            out["edition"] = EvidenceLockedField(
                value=hints.edition_label,
                source="tier1_filename",
                confidence=FrameFieldConfidence.HIGH,
            )
        if hints.publication_year:
            out["publication_date"] = DateField(
                value=str(hints.publication_year),
                date_role=DateRole.PUBLICATION,
                source="tier1_filename",
                confidence=(
                    FrameFieldConfidence.HIGH if hints.confidence == "high"
                    else FrameFieldConfidence.MEDIUM if hints.confidence == "medium"
                    else FrameFieldConfidence.LOW
                ),
            )

        return out

    def _build_from_tier1_only(self, doc_id: str, tier1_fields: Optional[dict]) -> ApplicabilityFrameV2:
        """Fallback frame avec uniquement Tier 1 (LLM indisponible)."""
        frame = ApplicabilityFrameV2(doc_id=doc_id, method="tier1_deterministic_only")
        if not tier1_fields:
            return frame

        scope = ScopeAxis(
            product_version=tier1_fields.get("product_version"),
            region=tier1_fields.get("region"),
            edition=tier1_fields.get("edition"),
        )
        temporality = TemporalityAxis(
            publication_date=tier1_fields.get("publication_date"),
        )
        frame.scope = scope
        frame.temporality = temporality
        return frame

    def _call_llm(
        self,
        doc_id: str,
        full_text_excerpt: str,
        primary_subject: Optional[str],
        document_type: Optional[str],
        language: Optional[str],
        tier1_hints: Optional[Tier1Hints],
        domain_pack_hints: Optional[str],
    ) -> dict:
        """Appelle le vLLM endpoint et retourne le JSON parsé."""
        tier1_section = ""
        if tier1_hints:
            tier1_section = (
                "\n\n**Tier 1 deterministic hints** (extracted from filename and cache, "
                "to confirm/complement — must still be evidence-quoted in the full_text):\n"
                f"  - product_version: {tier1_hints.product_version}\n"
                f"  - region: {tier1_hints.region}\n"
                f"  - edition_label: {tier1_hints.edition_label}\n"
                f"  - publication_year (filename): {tier1_hints.raw_filename_year}\n"
                f"  - amdt_number (filename): {tier1_hints.raw_amdt_number}\n"
                f"  - cache markers years: {tier1_hints.cache_markers_years}\n"
                f"  - cache entity years: {tier1_hints.cache_entity_years}\n"
                f"  - sources_count: {tier1_hints.sources_count} ({tier1_hints.confidence})"
            )

        domain_section = ""
        if domain_pack_hints:
            domain_section = f"\n\n**Domain context hints** (semantic, not patterns):\n{domain_pack_hints}"

        user_prompt = f"""Document inputs (the ONLY sources of truth for evidence_quotes):

**doc_id (filename-derived)**: `{doc_id}`
**primary_subject (from KG)**: {primary_subject or 'N/A'}
**document_type**: {document_type or 'N/A'}
**language**: {language or 'unknown'}{tier1_section}{domain_section}

**First {self.full_text_window_chars} chars of full_text** (the AUTHORITATIVE source):
{full_text_excerpt}

Extract the evidence-locked ApplicabilityFrame V2 with 3 orthogonal axes.

Reminder of the 3 distinct dates and their roles:
- publication_date (date_role="publication"): when THIS document was authored
- validity_start (date_role="effective" or "applicable_from"): when its RULES begin to apply
- validity_end (date_role="expiry"): when its rules cease

DO NOT use date_role="adoption" or "signature" to populate validity_start.
DO NOT default validity_start to publication_date. If unstated, leave value=null."""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": PROMPT_SYSTEM_V33},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
        }

        t0 = time.time()
        r = httpx.post(f"{self.vllm_url}/v1/chat/completions", json=payload, timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json()
        elapsed = time.time() - t0
        usage = data.get("usage", {})
        logger.info(
            f"[OSMOSE:FrameBuilderV2] {doc_id}: LLM call {elapsed:.1f}s, "
            f"{usage.get('total_tokens', 0)} tokens"
        )
        content = data["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"[OSMOSE:FrameBuilderV2] LLM returned invalid JSON for {doc_id}: {e}")
            return {}

    def _apply_tier1_fallback(self, frame: ApplicabilityFrameV2, tier1_fields: dict) -> None:
        """
        Applique Tier 1 fallback APRÈS validation.

        Si le LLM a été rejeté (field=None) ou n'a rien proposé, récupère la
        valeur déterministe depuis Tier 1. Les Tier 1 fields ont source="tier1_filename"
        et sont exemptés du validator.

        Modifie le frame in-place.
        """
        if frame.scope.product_version is None and tier1_fields.get("product_version"):
            frame.scope.product_version = tier1_fields["product_version"]
        if frame.scope.region is None and tier1_fields.get("region"):
            frame.scope.region = tier1_fields["region"]
        if frame.scope.edition is None and tier1_fields.get("edition"):
            frame.scope.edition = tier1_fields["edition"]
        if (
            (frame.temporality.publication_date is None or frame.temporality.publication_date.value is None)
            and tier1_fields.get("publication_date")
        ):
            frame.temporality.publication_date = tier1_fields["publication_date"]

    def _parse_llm_output(
        self,
        doc_id: str,
        llm_data: dict,
    ) -> ApplicabilityFrameV2:
        """Parse JSON LLM en ApplicabilityFrameV2 (sans merge Tier 1 — appliqué après validation)."""
        scope = ScopeAxis()
        temporality = TemporalityAxis()
        lifecycle = LifecycleAxis()

        # Scope
        scope_data = llm_data.get("scope", {}) or {}
        scope.product_version = self._parse_locked_field(scope_data.get("product_version"))
        scope.region = self._parse_locked_field(scope_data.get("region"))
        scope.edition = self._parse_locked_field(scope_data.get("edition"))
        scope.subject_class = self._parse_locked_field(scope_data.get("subject_class"))
        scope.conditions = [
            self._parse_locked_field(c) for c in (scope_data.get("conditions") or []) if c
        ]
        scope.conditions = [c for c in scope.conditions if c is not None]

        # Temporality
        temp_data = llm_data.get("temporality", {}) or {}
        temporality.publication_date = self._parse_date_field(temp_data.get("publication_date"))
        temporality.validity_start = self._parse_date_field(temp_data.get("validity_start"))
        temporality.validity_end = self._parse_date_field(temp_data.get("validity_end"))
        temporality.publication_validity_relationship = temp_data.get(
            "publication_validity_relationship", "unknown"
        )

        # Lifecycle
        lc_data = llm_data.get("lifecycle", {}) or {}
        status_str = lc_data.get("status", "UNKNOWN")
        try:
            lifecycle.status = LifecycleStatus(status_str)
        except ValueError:
            lifecycle.status = LifecycleStatus.UNKNOWN
        lifecycle.status_evidence_quote = lc_data.get("status_evidence_quote")
        lifecycle.supersedes = [
            self._parse_locked_field(s) for s in (lc_data.get("supersedes") or []) if s
        ]
        lifecycle.supersedes = [s for s in lifecycle.supersedes if s is not None]
        lifecycle.superseded_by = self._parse_locked_field(lc_data.get("superseded_by"))
        lifecycle.evolves_from = self._parse_locked_field(lc_data.get("evolves_from"))

        # NB: Pas de merge Tier 1 ici. Le merge est fait APRÈS validation
        # via _apply_tier1_fallback() pour ne pas perdre Tier 1 quand le LLM
        # est rejeté par le validator.

        return ApplicabilityFrameV2(
            doc_id=doc_id,
            scope=scope,
            temporality=temporality,
            lifecycle=lifecycle,
        )

    def _parse_locked_field(self, data: Any) -> Optional[EvidenceLockedField]:
        """Parse un dict {value, evidence_quote, confidence} en EvidenceLockedField."""
        if not data:
            return None
        if isinstance(data, str):
            # Format inattendu : valeur seule sans dict
            return None
        if not isinstance(data, dict):
            return None
        value = data.get("value")
        if value is None or value == "":
            return None
        return EvidenceLockedField(
            value=str(value),
            evidence_quote=data.get("evidence_quote") or data.get("quote"),
            source="tier2_llm",
            confidence=self._parse_confidence(data.get("confidence")),
        )

    def _parse_date_field(self, data: Any) -> Optional[DateField]:
        """Parse un dict {value, date_role, evidence_quote, confidence} en DateField."""
        if not data:
            return None
        if not isinstance(data, dict):
            return None
        value = data.get("value")
        if value is None or value == "":
            return None
        date_role_str = (data.get("date_role") or "unknown").lower()
        try:
            date_role = DateRole(date_role_str)
        except ValueError:
            date_role = DateRole.UNKNOWN
        return DateField(
            value=str(value),
            date_role=date_role,
            evidence_quote=data.get("evidence_quote") or data.get("quote"),
            source="tier2_llm",
            confidence=self._parse_confidence(data.get("confidence")),
        )

    def _parse_confidence(self, val: Any) -> FrameFieldConfidence:
        if not val:
            return FrameFieldConfidence.MEDIUM
        try:
            return FrameFieldConfidence(str(val).lower())
        except ValueError:
            return FrameFieldConfidence.MEDIUM


__all__ = ["FrameBuilderV2", "PROMPT_SYSTEM_V33"]
