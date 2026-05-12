"""
S3.A — 12-class LogicalRelation classifier (V3.3 §3.C).

Pivot conceptuel V2 (cf. CONTRADICTION_DETECTION_ARCHITECTURE.md §3) :
au lieu de demander au LLM "are these contradictory ?", on lui demande de
**classifier la relation logique** sur une typologie fermée 12-types.

La contradiction devient un **cas particulier** d'une typologie plus large.

Inputs :
- claim_a, claim_b (textes)
- scope_relation, temporal_relation (output Gate V3.3)
- doc_role_a, doc_role_b (optionnels, depuis Domain Pack role_mapping)
- evidence_quote_a, evidence_quote_b (optionnels)

Output : LogicalRelationOutput
- relation ∈ 12 types
- strength : STRONG/WEAK/UNCERTAIN
- confidence ∈ [0, 1]
- reasoning structuré
- is_contradiction : décision déterministe (V3.3 §3.D)
- alternatives : top-2 si delta < 0.15 (multi-label V3.3 §3.G.5)

Pattern V3.3 :
- Prompt sémantique pur (anti-pattern lexical respecté)
- Multilingue + domain-agnostic
- Skip persistence si UNRELATED (V3.3 §3.G.3)
- Confidence threshold différencié par type (V3.3 §3.G.2)
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

import httpx

from knowbase.relations.v33_types import (
    CONFIDENCE_THRESHOLDS,
    LogicalRelationOutput,
    LogicalRelationType,
    RelationStrength,
    ScopeRelation,
    TemporalRelation,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Prompt système V3.3 — sémantique pur, 12-class
# ============================================================================

PROMPT_SYSTEM_12CLASS = """You are a logical relation classifier for regulatory and technical documents.

Given two claims (each with optional scope and temporal context), classify the
LOGICAL relation between them on a closed typology of 12 types.

You handle ANY language (EN/FR/DE/ES/IT/...) and ANY domain (regulatory,
technical, legal, medical, IT, etc.) by understanding the SEMANTIC of the
text, NOT specific keywords.

## The 12 Logical Relations (closed typology)

### Set-like (between scopes)
- **SUBSET**: A is a strict particular case of B (A's range is inside B's range)
  Example: "pulse 1ps-1ns" ⊂ "pulse ≤ 0.25s"
- **SUPERSET**: B is a strict particular case of A (inverse of SUBSET)
- **EQUIVALENT**: A and B express the same rule (same scope, same assertion)
- **OVERLAP**: A and B share scope partially, neither is subset of the other
- **DISJOINT**: A and B do NOT apply to the same things

### Logical (between assertions)
- **CONFLICT**: A and B make INCOMPATIBLE assertions on IDENTICAL or overlapping scope.
  This is the TRUE contradiction. Example: "limit 73 passengers" vs "limit 48 passengers" same context.
  Use CONFLICT only when there's a real contradiction on the SAME scope.
- **EXCEPTION**: A derogates B under specific conditions. Example: "X is required, EXCEPT for medical devices".
- **DEFINITION_OF**: A defines a term used in B (or vice-versa).

### Temporal (between document versions)
- **SUPERSEDES**: A replaces B (B's validity_end is before A's validity_start, scopes aligned).
- **EVOLVES_FROM**: A descends from B without necessarily replacing it.
- **REAFFIRMS**: A re-states the same rule as B (without conflict, same effective period).

### Default
- **UNRELATED**: No meaningful logical relation between A and B.

## Decision rules

1. If scope_relation = DISJOINT (different things), prefer DISJOINT (or UNRELATED if the claims don't even share concepts).

2. If scope_relation = SUBSET/SUPERSET (one is more specific), prefer SUBSET/SUPERSET.

3. If temporal_relation = A_BEFORE_B (validity windows non-overlap, A precedes B) AND scopes aligned, prefer SUPERSEDES.

4. If scope_relation = EQUIVALENT and assertions match, prefer REAFFIRMS or EQUIVALENT.

5. CONFLICT requires ALL of:
   - **Direct factual incompatibility**: contradictory numerical values (e.g., "73 passengers" vs "48 passengers" same scope), mutually exclusive states (e.g., "is solid" vs "is liquid"), or directly opposing assertions (e.g., "must be encrypted" vs "must NOT be encrypted")
   - SAME or overlapping scope (not just "same product family")
   - Active validity windows (both in force)
   A simple phrasing difference, a typographic variation, or citing the same external authority is NOT a conflict.

6. **CRITICAL false-positive guards** (universal, language- and domain-agnostic):

   a. **Same external citation** : two claims citing the same external document/standard/regulation (by name or identifier) are EQUIVALENT or REAFFIRMS, NOT CONFLICT. They reference the same authority, they do not contradict it.

   b. **Different units expressing same value** : numerically identical with different units (e.g., units of measurement equivalence, language translations) → EQUIVALENT, NOT CONFLICT.

   c. **Typographic / phrasing variation only** : same content with different word order, punctuation, capitalisation, or quote style → EQUIVALENT, NOT CONFLICT.

   d. **Different enumerated entries of the same standard/document** (CRITICAL — the most common false positive):
      Normative documents (regulations, standards, technical specs, list-based control schemes) frequently contain MULTIPLE enumerated items, sections, sub-paragraphs, or table rows that each define independent rules with different threshold values, conditions, or specifications.
      For example, an item "Category A: threshold > 0.002" and an item "Category B: threshold > 0.1" are NOT in conflict — they define independent applicability rules for distinct categories.
      Without explicit textual evidence that BOTH claims target the EXACT SAME enumerated entry / section / configuration / category, prefer OVERLAP or DISJOINT, NOT CONFLICT.
      Indicators of "different enumerated entries" : different section IDs, different category labels, different sub-item references, distinct list positions.

   e. **Temporal succession evidence** : if the two source documents have publication dates differing significantly (typically more than 1 year for regulatory/normative texts) AND share an evident document-family relationship (versioning convention, replacement clauses, predecessor-successor naming), prefer SUPERSEDES, NOT CONFLICT. Successor rules replace predecessor rules; they don't contradict them. Look for : explicit "repealed by" / "replaces" / "supersedes" language, or strong family/numbering pattern (e.g., a 2009 doc and a 2021 doc that clearly belong to the same regulatory line).

   f. **Different specific items within a list of similar entities** : two claims that exclude or include different specific items (different materials, different sub-categories, different model numbers) → DISJOINT or OVERLAP, NOT CONFLICT. They make independent assertions about different entities.

   g. **Different categorical thresholds within a graduated scheme** : graduated schemes often define multiple thresholds (e.g., severity levels, distance categories, performance tiers) that coexist independently. Different threshold values from a graduated scheme → OVERLAP, NOT CONFLICT, unless explicitly stated to be the SAME tier with different values.

   h. **One claim is a more detailed restatement of the other** : same assertion with extra qualifying clause → EQUIVALENT or SUBSET, NOT CONFLICT.

When in doubt between CONFLICT and OVERLAP/SUPERSEDES, prefer the non-CONFLICT option. False CONFLICTs are the worst-case error in this system — they pollute the dashboard with noise. The bar for CONFLICT is high: BOTH claims must explicitly target the SAME identified scope/entry/configuration AND make incompatible assertions, with no plausible alternative interpretation.

NOTE FOR FUTURE EXTENSIONS: domain-specific contextual hints (regulatory family conventions, standard-specific versioning patterns, etc.) should be injected at runtime via the active Domain Pack, not hardcoded in this generic prompt. The principles here are deliberately universal.

## Strength

For the chosen relation, also provide a strength:
- **STRONG**: clear logic, little ambiguity
- **WEAK**: interpretive, depends on context
- **UNCERTAIN**: borderline, could justifiably be another type

## Output JSON

{
  "relation": "<one of the 12 types>",
  "strength": "STRONG" | "WEAK" | "UNCERTAIN",
  "confidence": 0.0-1.0,
  "reasoning": "<structured explanation citing the specific words/concepts that justify the choice>",
  "alternatives": [{"type": "...", "confidence": 0.X}]  // optional, only if top-2 within 0.15
}

If you genuinely cannot decide, choose UNRELATED with low confidence. Do NOT fabricate."""


# ============================================================================
# Classifier class
# ============================================================================

class LogicalRelationClassifier:
    """12-class LLM-as-extractor classifier (V3.3 §3.C)."""

    def __init__(
        self,
        vllm_url: str = "http://localhost:8000",
        model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
        timeout_s: float = 60.0,
    ):
        self.vllm_url = vllm_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    def classify(
        self,
        claim_a_text: str,
        claim_b_text: str,
        scope_relation: Optional[ScopeRelation] = None,
        temporal_relation: Optional[TemporalRelation] = None,
        doc_role_a: Optional[str] = None,
        doc_role_b: Optional[str] = None,
        publication_date_a: Optional[str] = None,
        publication_date_b: Optional[str] = None,
        validity_start_a: Optional[str] = None,
        validity_start_b: Optional[str] = None,
        domain_hints: Optional[dict] = None,
    ) -> Optional[LogicalRelationOutput]:
        """
        Classifie la relation logique entre 2 claims.

        Args:
            domain_hints: optionnel, dict des classifier_hints du Domain Pack
                          actif (ex: {"context_summary": "...",
                          "succession_patterns": "...", ...}). Injecté en prose
                          dans le system prompt — V3.3-conforming, pas de regex.

        Returns None si appel LLM échoue ou JSON invalide.
        """
        scope_str = scope_relation.value if scope_relation else "unknown"
        temporal_str = temporal_relation.value if temporal_relation else "unknown"

        # System prompt : universal + domain hints (V3.3 §3.G.4)
        system_prompt = PROMPT_SYSTEM_12CLASS
        if domain_hints:
            domain_section = self._format_domain_hints(domain_hints)
            if domain_section:
                system_prompt = system_prompt + "\n\n" + domain_section

        # User prompt
        user_prompt = f"""## Claim A
text: {claim_a_text}
doc_role: {doc_role_a or 'unknown'}
publication_date: {publication_date_a or 'unknown'}
validity_start: {validity_start_a or 'unknown'}

## Claim B
text: {claim_b_text}
doc_role: {doc_role_b or 'unknown'}
publication_date: {publication_date_b or 'unknown'}
validity_start: {validity_start_b or 'unknown'}

## Pre-computed alignments (from Gate V3.3 deterministic analysis)
scope_relation: {scope_str}
temporal_relation: {temporal_str}

Classify the logical relation between A and B."""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 600,
            "response_format": {"type": "json_object"},
        }

        t0 = time.time()
        try:
            r = httpx.post(f"{self.vllm_url}/v1/chat/completions", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"[V33:Classifier] LLM call failed: {e}")
            return None

        elapsed = time.time() - t0
        data = r.json()
        content = data["choices"][0]["message"]["content"]

        # Parse JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if not m:
                logger.warning(f"[V33:Classifier] No JSON in LLM output: {content[:200]}")
                return None
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError as e:
                logger.warning(f"[V33:Classifier] JSON parse failed: {e}")
                return None

        # Build output
        return self._build_output(parsed, scope_relation, temporal_relation, elapsed)

    def _build_output(
        self,
        parsed: dict,
        scope_relation: Optional[ScopeRelation],
        temporal_relation: Optional[TemporalRelation],
        elapsed: float,
    ) -> Optional[LogicalRelationOutput]:
        """Convertit le JSON LLM en LogicalRelationOutput typé."""
        # relation
        relation_str = (parsed.get("relation") or "UNRELATED").upper()
        try:
            relation = LogicalRelationType(relation_str)
        except ValueError:
            logger.warning(f"[V33:Classifier] Unknown relation: {relation_str}, defaulting to UNRELATED")
            relation = LogicalRelationType.UNRELATED

        # strength
        strength_str = (parsed.get("strength") or "STRONG").upper()
        try:
            strength = RelationStrength(strength_str)
        except ValueError:
            strength = RelationStrength.UNCERTAIN

        # confidence
        confidence = parsed.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        # Apply threshold downgrade : si confidence < threshold pour ce type → UNCERTAIN
        threshold = CONFIDENCE_THRESHOLDS.get(relation, 0.65)
        if confidence < threshold and strength == RelationStrength.STRONG:
            strength = RelationStrength.UNCERTAIN

        # Décision déterministe is_contradiction (V3.3 §3.D)
        is_contradiction = (
            relation == LogicalRelationType.CONFLICT
            and confidence >= CONFIDENCE_THRESHOLDS[LogicalRelationType.CONFLICT]
            and scope_relation in (ScopeRelation.EQUIVALENT, ScopeRelation.OVERLAPPING, ScopeRelation.SUBSET, ScopeRelation.SUPERSET)
        )
        if relation == LogicalRelationType.CONFLICT:
            if is_contradiction:
                contradiction_reason = "true_conflict_high_confidence_aligned_scope"
            elif confidence < CONFIDENCE_THRESHOLDS[LogicalRelationType.CONFLICT]:
                contradiction_reason = "confidence_below_threshold"
            else:
                contradiction_reason = "scope_not_aligned"
        elif relation == LogicalRelationType.SUBSET or relation == LogicalRelationType.SUPERSET:
            contradiction_reason = "subset_relation_not_contradiction"
        elif relation == LogicalRelationType.EXCEPTION:
            contradiction_reason = "exception_relation_not_contradiction"
        elif relation == LogicalRelationType.DEFINITION_OF:
            contradiction_reason = "definition_relation_not_contradiction"
        else:
            contradiction_reason = f"relation_{relation.value}"

        # Alternatives
        alternatives = parsed.get("alternatives", []) or []

        return LogicalRelationOutput(
            relation=relation,
            strength=strength,
            confidence=confidence,
            reasoning=parsed.get("reasoning", "")[:1000],
            scope_alignment=scope_relation,
            temporal_relation=temporal_relation,
            is_contradiction=is_contradiction,
            contradiction_reason=contradiction_reason,
            alternatives=alternatives if isinstance(alternatives, list) else [],
        )


    @staticmethod
    def _format_domain_hints(hints: dict) -> str:
        """Transforme les classifier_hints du Domain Pack en section prose
        injectable dans le system prompt.

        V3.3-conforming : on traite chaque entry comme un paragraphe sémantique,
        sans transformation lexicale. Le LLM reçoit la prose telle quelle.
        """
        if not isinstance(hints, dict) or not hints:
            return ""

        ordered_keys = [
            "context_summary",
            "succession_patterns",
            "transitional_provisions",
            "annex_correspondence",
            "cross_references",
            "graduated_schemes_warning",
            "enumerated_entries_warning",
            "repeal_evidence",
        ]
        seen = set()
        sections = []
        for key in ordered_keys:
            if key in hints and isinstance(hints[key], str) and hints[key].strip():
                sections.append(hints[key].strip())
                seen.add(key)
        # Ajouter les autres clés non listées (fallback)
        for key, value in hints.items():
            if key in seen:
                continue
            if isinstance(value, str) and value.strip():
                sections.append(value.strip())

        if not sections:
            return ""

        body = "\n\n".join(sections)
        return (
            "## Domain context (provided by the active Domain Pack)\n\n"
            "The following paragraphs describe semantic conventions specific to "
            "the domain of the documents being classified. Use them as additional "
            "context when interpreting the claims. They do NOT override the universal "
            "decision rules above; they refine the priors for this corpus.\n\n"
            f"{body}"
        )


__all__ = ["LogicalRelationClassifier", "PROMPT_SYSTEM_12CLASS"]
