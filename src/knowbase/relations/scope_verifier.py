# ADR SCOPE Discursive Candidate Mining - Scope Verifier (Pass 3)
# Ref: doc/ongoing/ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md
#
# Ce module implémente le Verifier LLM pour les CandidatePairs SCOPE:
# - Prend un CandidatePair avec EvidenceBundle
# - Vérifie si une relation APPLIES_TO ou REQUIRES est justifiable
# - Retourne ASSERT ou ABSTAIN avec raison structurée
#
# Invariants respectés:
# - INV-SCOPE-02: Marquage DISCURSIVE + basis=["SCOPE"]
# - INV-SCOPE-04: ABSTAIN motivé au niveau Verifier
# - Whitelist V1: APPLIES_TO, REQUIRES uniquement

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple
from ulid import ULID

from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.relations.types import (
    AssertionKind,
    CandidatePair,
    CandidatePairStatus,
    DiscursiveAbstainReason,
    DiscursiveBasis,
    RawAssertion,
    RawAssertionFlags,
    RelationType,
    ScopeMiningConfig,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Prompt de vérification SCOPE (ultra-concis)
# =============================================================================

SCOPE_VERIFY_PROMPT = """You are validating a candidate relationship based on document scope co-presence.

Two concepts appear in the same document section. Determine if there is a DIRECT relationship.

CONTEXT (scope setter):
"{scope_setter_text}"

CONCEPT A: {concept_a}
Mentioned in: "{concept_a_text}"

CONCEPT B: {concept_b}
Mentioned in: "{concept_b_text}"

QUESTION:
Based ONLY on this evidence (no external knowledge), is there a direct relationship?

VALID relationships (pick one if applicable):
- APPLIES_TO: A applies to / is used in context of B (requires explicit marker: "for", "in", "applies to", "used in")
- REQUIRES: A requires / needs B (requires normative marker: "shall", "must", "required", "needs")

REJECT if:
- The concepts are just listed together without explicit connection
- The relationship would require inference beyond the text
- No explicit marker connects A to B

Answer format (JSON only):
{{"verdict": "ASSERT", "relation": "APPLIES_TO", "direction": "A_TO_B", "confidence": 0.8, "marker": "for"}}
or
{{"verdict": "ABSTAIN", "reason": "NO_EXPLICIT_MARKER"}}

Your answer:"""


# =============================================================================
# Types de résultat
# =============================================================================

@dataclass
class VerificationResult:
    """Résultat de la vérification d'un CandidatePair."""
    candidate_id: str
    verdict: str  # "ASSERT" ou "ABSTAIN"

    # Si ASSERT
    relation_type: Optional[RelationType] = None
    direction: Optional[str] = None  # "A_TO_B" ou "B_TO_A"
    confidence: float = 0.0
    marker_found: Optional[str] = None

    # Si ABSTAIN
    abstain_reason: Optional[DiscursiveAbstainReason] = None
    abstain_justification: Optional[str] = None

    # Traçabilité
    llm_raw_response: Optional[str] = None


@dataclass
class BatchVerificationResult:
    """Résultat de vérification en batch."""
    total: int = 0
    asserted: int = 0
    abstained: int = 0
    errors: int = 0
    results: List[VerificationResult] = None

    def __post_init__(self):
        if self.results is None:
            self.results = []


# =============================================================================
# Scope Verifier
# =============================================================================

class ScopeVerifier:
    """
    Vérificateur LLM pour CandidatePairs SCOPE.

    Ref: ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md - Section VERIFIER LLM (Pass 3)

    Ce vérificateur:
    - Prend des CandidatePairs avec EvidenceBundles
    - Appelle le LLM pour déterminer si une relation est justifiable
    - Respecte la whitelist SCOPE V1 (APPLIES_TO, REQUIRES)
    - Émet des ABSTAIN motivés (INV-SCOPE-04)
    """

    def __init__(
        self,
        llm_router=None,
        config: Optional[ScopeMiningConfig] = None,
    ):
        self.llm_router = llm_router or get_llm_router()
        self.config = config or ScopeMiningConfig()

        # Whitelist V1
        self.allowed_relations = set(self.config.allowed_relation_types)

    async def verify(self, candidate: CandidatePair) -> VerificationResult:
        """
        Vérifie un CandidatePair unique.

        Args:
            candidate: CandidatePair à vérifier

        Returns:
            VerificationResult avec ASSERT ou ABSTAIN
        """
        bundle = candidate.evidence_bundle

        # Extraire les textes du bundle
        scope_setter = bundle.get_scope_setter()
        mentions = bundle.get_mentions()

        if not scope_setter:
            return VerificationResult(
                candidate_id=candidate.candidate_id,
                verdict="ABSTAIN",
                abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE,
                abstain_justification="No scope_setter in bundle",
            )

        # Trouver les mentions pour pivot et other
        pivot_mention = None
        other_mention = None
        for m in mentions:
            if m.concept_id == candidate.pivot_concept_id:
                pivot_mention = m
            elif m.concept_id == candidate.other_concept_id:
                other_mention = m

        # Construire le prompt
        prompt = SCOPE_VERIFY_PROMPT.format(
            scope_setter_text=scope_setter.text_excerpt[:300],
            concept_a=candidate.pivot_surface_form,
            concept_a_text=pivot_mention.text_excerpt[:200] if pivot_mention else scope_setter.text_excerpt[:200],
            concept_b=candidate.other_surface_form,
            concept_b_text=other_mention.text_excerpt[:200] if other_mention else scope_setter.text_excerpt[:200],
        )

        try:
            # Utiliser SHORT_ENRICHMENT (claude-3-haiku) pour éviter les coûts OpenAI
            response = await self.llm_router.acomplete(
                task_type=TaskType.SHORT_ENRICHMENT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=150,
            )

            if not response:
                return VerificationResult(
                    candidate_id=candidate.candidate_id,
                    verdict="ABSTAIN",
                    abstain_reason=DiscursiveAbstainReason.AMBIGUOUS_PREDICATE,
                    abstain_justification="Empty LLM response",
                    llm_raw_response="",
                )

            return self._parse_response(candidate.candidate_id, response)

        except Exception as e:
            logger.error(f"[ScopeVerifier] LLM call failed: {e}")
            return VerificationResult(
                candidate_id=candidate.candidate_id,
                verdict="ABSTAIN",
                abstain_reason=DiscursiveAbstainReason.AMBIGUOUS_PREDICATE,
                abstain_justification=f"LLM error: {str(e)[:50]}",
            )

    async def verify_batch(
        self,
        candidates: List[CandidatePair],
        max_concurrent: int = 5,
    ) -> BatchVerificationResult:
        """
        Vérifie un batch de CandidatePairs.

        Args:
            candidates: Liste de CandidatePairs à vérifier
            max_concurrent: Nombre max d'appels LLM concurrents

        Returns:
            BatchVerificationResult avec stats et résultats
        """
        import asyncio

        batch_result = BatchVerificationResult(total=len(candidates))

        # Traiter par lots pour limiter la concurrence
        for i in range(0, len(candidates), max_concurrent):
            batch = candidates[i:i + max_concurrent]
            tasks = [self.verify(c) for c in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    batch_result.errors += 1
                    logger.error(f"[ScopeVerifier] Batch verification error: {result}")
                else:
                    batch_result.results.append(result)
                    if result.verdict == "ASSERT":
                        batch_result.asserted += 1
                    else:
                        batch_result.abstained += 1

        return batch_result

    def _parse_response(self, candidate_id: str, response: str) -> VerificationResult:
        """Parse la réponse JSON du LLM."""
        try:
            # Extraire le JSON de la réponse
            response_clean = response.strip()

            # Chercher le JSON dans la réponse
            start = response_clean.find("{")
            end = response_clean.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = response_clean[start:end]
                data = json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")

            verdict = data.get("verdict", "ABSTAIN").upper()

            if verdict == "ASSERT":
                relation_str = data.get("relation", "").upper()

                # Mapper vers RelationType
                relation_type = None
                if relation_str == "APPLIES_TO":
                    relation_type = RelationType.APPLIES_TO
                elif relation_str == "REQUIRES":
                    relation_type = RelationType.REQUIRES

                # Vérifier whitelist
                if relation_type and relation_type not in self.allowed_relations:
                    return VerificationResult(
                        candidate_id=candidate_id,
                        verdict="ABSTAIN",
                        abstain_reason=DiscursiveAbstainReason.WHITELIST_VIOLATION,
                        abstain_justification=f"Relation {relation_str} not in SCOPE V1 whitelist",
                        llm_raw_response=response,
                    )

                if not relation_type:
                    return VerificationResult(
                        candidate_id=candidate_id,
                        verdict="ABSTAIN",
                        abstain_reason=DiscursiveAbstainReason.AMBIGUOUS_PREDICATE,
                        abstain_justification=f"Unknown relation type: {relation_str}",
                        llm_raw_response=response,
                    )

                return VerificationResult(
                    candidate_id=candidate_id,
                    verdict="ASSERT",
                    relation_type=relation_type,
                    direction=data.get("direction", "A_TO_B"),
                    confidence=float(data.get("confidence", 0.7)),
                    marker_found=data.get("marker"),
                    llm_raw_response=response,
                )

            else:
                # ABSTAIN
                reason_str = data.get("reason", "AMBIGUOUS_PREDICATE")
                reason = self._map_abstain_reason(reason_str)

                return VerificationResult(
                    candidate_id=candidate_id,
                    verdict="ABSTAIN",
                    abstain_reason=reason,
                    abstain_justification=reason_str,
                    llm_raw_response=response,
                )

        except json.JSONDecodeError as e:
            logger.warning(f"[ScopeVerifier] JSON parse error: {e}")
            return VerificationResult(
                candidate_id=candidate_id,
                verdict="ABSTAIN",
                abstain_reason=DiscursiveAbstainReason.AMBIGUOUS_PREDICATE,
                abstain_justification=f"Invalid JSON response",
                llm_raw_response=response,
            )
        except Exception as e:
            logger.warning(f"[ScopeVerifier] Parse error: {e}")
            return VerificationResult(
                candidate_id=candidate_id,
                verdict="ABSTAIN",
                abstain_reason=DiscursiveAbstainReason.AMBIGUOUS_PREDICATE,
                abstain_justification=str(e)[:50],
                llm_raw_response=response,
            )

    def _map_abstain_reason(self, reason_str: str) -> DiscursiveAbstainReason:
        """Mappe une chaîne de raison vers l'enum."""
        reason_upper = reason_str.upper()

        if "TYPE2" in reason_upper or "INFERENCE" in reason_upper:
            return DiscursiveAbstainReason.TYPE2_RISK
        elif "MARKER" in reason_upper or "EXPLICIT" in reason_upper:
            return DiscursiveAbstainReason.AMBIGUOUS_PREDICATE
        elif "SCOPE" in reason_upper or "BREAK" in reason_upper:
            return DiscursiveAbstainReason.SCOPE_BREAK_LINGUISTIC
        else:
            return DiscursiveAbstainReason.AMBIGUOUS_PREDICATE


# =============================================================================
# Conversion CandidatePair → RawAssertion
# =============================================================================

def candidate_to_raw_assertion(
    candidate: CandidatePair,
    verification: VerificationResult,
    tenant_id: str = "default",
) -> Optional[RawAssertion]:
    """
    Convertit un CandidatePair vérifié en RawAssertion.

    Ref: ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md - Section WRITE

    Args:
        candidate: CandidatePair source
        verification: Résultat de la vérification LLM
        tenant_id: Tenant ID

    Returns:
        RawAssertion si ASSERT, None si ABSTAIN
    """
    if verification.verdict != "ASSERT":
        return None

    # Déterminer subject/object selon la direction
    if verification.direction == "B_TO_A":
        subject_id = candidate.other_concept_id
        object_id = candidate.pivot_concept_id
        subject_form = candidate.other_surface_form
        object_form = candidate.pivot_surface_form
    else:  # A_TO_B (default)
        subject_id = candidate.pivot_concept_id
        object_id = candidate.other_concept_id
        subject_form = candidate.pivot_surface_form
        object_form = candidate.other_surface_form

    # Construire l'evidence text depuis le bundle
    bundle = candidate.evidence_bundle
    scope_setter = bundle.get_scope_setter()
    evidence_text = scope_setter.text_excerpt if scope_setter else ""

    # Générer le fingerprint
    import hashlib
    fingerprint_data = f"{tenant_id}|{candidate.document_id}|{candidate.section_id}|{subject_id}|{object_id}|{verification.relation_type.value}|{evidence_text[:100]}"
    fingerprint = hashlib.sha1(fingerprint_data.encode()).hexdigest()[:16]

    return RawAssertion(
        raw_assertion_id=str(ULID()),
        tenant_id=tenant_id,
        raw_fingerprint=fingerprint,

        # Prédicat
        predicate_raw=verification.marker_found or verification.relation_type.value.lower(),
        predicate_norm=verification.relation_type.value.lower(),
        relation_type=verification.relation_type,
        type_confidence=verification.confidence,

        # Concepts
        subject_concept_id=subject_id,
        object_concept_id=object_id,
        subject_surface_form=subject_form,
        object_surface_form=object_form,

        # Evidence
        evidence_text=evidence_text,

        # Scores
        confidence_extractor=verification.confidence,
        quality_penalty=0.0,
        confidence_final=verification.confidence,

        # Flags
        flags=RawAssertionFlags(),

        # ADR SCOPE - Marquage obligatoire (INV-SCOPE-02)
        assertion_kind=AssertionKind.DISCURSIVE,
        discursive_basis=[DiscursiveBasis.SCOPE],

        # Source
        source_doc_id=candidate.document_id,
        source_chunk_id=candidate.section_id,

        # Traçabilité
        extractor_name="scope_verifier",
        extractor_version="v1.0.0",
        model_used="llm",
        schema_version="2.13.0",
    )


# =============================================================================
# Fonction utilitaire
# =============================================================================

def get_scope_verifier(
    llm_router=None,
    config: Optional[ScopeMiningConfig] = None,
) -> ScopeVerifier:
    """Factory pour obtenir un ScopeVerifier."""
    return ScopeVerifier(llm_router=llm_router, config=config)
