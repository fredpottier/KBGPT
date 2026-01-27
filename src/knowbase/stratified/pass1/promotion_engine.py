"""
OSMOSE Pipeline V2 - Promotion Engine
======================================
Spec: ChatGPT "Two-pass Vision Evidence Contract" (2026-01-26)

Moteur de décision PROMOTE / ABSTAIN / REJECT pour les assertions.

Responsabilités:
1. Filtrer les meta-patterns (hard reject)
2. Vérifier l'ancrage DocItem
3. Appliquer la Promotion Policy par tier
4. Vérifier l'addressability (pivots)
5. Générer les logs d'audit

Architecture Patterns META (2026-01-27):
- Patterns externalisés en YAML: config/meta_patterns/
- Agnostiques au domaine par défaut
- Extensions domaine optionnelles
"""

import re
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import yaml

from knowbase.stratified.models.assertion_v1 import (
    AssertionV0,
    AssertionBatchV0,
    ResolvedAssertionV1,
    AssertionLogEntry,
    AssertionBatchV1,
    AnchorV1,
    PromotionDecision,
    PivotsV1,
    AssertionTypeV1,
    SupportTier,
    PromotionStatus,
    RuleUsed,
    AbstainReason,
    TYPE_TO_TIER,
    WHITELIST_TYPES_V1,
)

logger = logging.getLogger(__name__)


# ============================================================================
# META REJECT PATTERNS - Chargement depuis YAML (2026-01-27)
# ============================================================================
# Architecture: Patterns externalisés en config/meta_patterns/
# - structural_patterns.yaml: Patterns structurels par langue (agnostiques)
# - domain_extensions.yaml: Extensions domaine (désactivées par défaut)

# Fallback minimal si fichiers YAML absents
META_REJECT_PATTERNS_FALLBACK = [
    r"^this\s+(page|section)\s+(describes|shows)",
    r"^see\s+also\b",
    r"^refer\s+to\b",
    r"^copyright\b",
    r"^disclaimer\s*:",
    r"^note\s*:",
    r"^\d+\.\s*$",
]


def _load_meta_patterns() -> List[re.Pattern]:
    """
    Charge les patterns META depuis les fichiers YAML de configuration.

    Architecture:
    1. Charge structural_patterns.yaml (toujours)
    2. Charge domain_extensions.yaml si un domaine est actif

    Returns:
        Liste de patterns regex compilés
    """
    config_dir = Path(__file__).parents[4] / "config" / "meta_patterns"
    patterns: List[str] = []

    # 1. Charger patterns structurels (obligatoire)
    structural_path = config_dir / "structural_patterns.yaml"
    if structural_path.exists():
        try:
            with open(structural_path, 'r', encoding='utf-8') as f:
                structural = yaml.safe_load(f) or {}

            for lang, categories in structural.get('languages', {}).items():
                for category, pattern_list in categories.items():
                    if isinstance(pattern_list, list):
                        patterns.extend(pattern_list)

            logger.info(f"[OSMOSE] Patterns structurels chargés: {len(patterns)} patterns")
        except Exception as e:
            logger.error(f"[OSMOSE] Erreur chargement structural_patterns.yaml: {e}")
    else:
        logger.warning(f"[OSMOSE] Fichier patterns structurels non trouvé: {structural_path}")
        logger.warning("[OSMOSE] Utilisation du fallback minimal")
        patterns.extend(META_REJECT_PATTERNS_FALLBACK)

    # 2. Charger extensions domaine (optionnel)
    domain_path = config_dir / "domain_extensions.yaml"
    if domain_path.exists():
        try:
            with open(domain_path, 'r', encoding='utf-8') as f:
                domain_config = yaml.safe_load(f) or {}

            active = domain_config.get('active_domain')
            if active:
                domain_def = domain_config.get('domains', {}).get(active, {})
                additional = domain_def.get('additional_patterns', {})
                domain_pattern_count = 0
                for lang, categories in additional.items():
                    for category, pattern_list in categories.items():
                        if isinstance(pattern_list, list):
                            patterns.extend(pattern_list)
                            domain_pattern_count += len(pattern_list)
                logger.info(f"[OSMOSE] Domaine actif: {active} (+{domain_pattern_count} patterns)")
            else:
                logger.debug("[OSMOSE] Mode agnostique (aucun domaine actif)")
        except Exception as e:
            logger.error(f"[OSMOSE] Erreur chargement domain_extensions.yaml: {e}")

    # 3. Compiler les patterns
    compiled: List[re.Pattern] = []
    invalid_count = 0
    for p in patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error as e:
            logger.error(f"[OSMOSE] Pattern regex invalide: {p} - {e}")
            invalid_count += 1

    if invalid_count > 0:
        logger.warning(f"[OSMOSE] {invalid_count} patterns invalides ignorés")

    logger.info(f"[OSMOSE] {len(compiled)} patterns META compilés au total")
    return compiled


# Chargement au démarrage du module
_COMPILED_META_PATTERNS = _load_meta_patterns()

# Export pour compatibilité (déprécié, utiliser is_meta_pattern())
META_REJECT_PATTERNS = META_REJECT_PATTERNS_FALLBACK


# ============================================================================
# FRAGMENT DETECTION (ChatGPT Priority 2 - Assertion Minimale)
# ============================================================================

# Patterns de fragments (non-assertions)
FRAGMENT_PATTERNS = [
    # Glossaire / Définitions acronymes seuls
    r"^[A-Z][A-Za-z0-9\s\-]{0,30}\.$",  # "VPC Peering." - nom seul avec point
    r"^[A-Z][A-Za-z0-9\s\-]{0,20}$",  # "ISO 27001" - nom seul sans ponctuation
    r"^[A-Z]{2,6}$",  # Acronyme seul "VPC"
    # Titres / Headers
    r"^(section|chapter|part|appendix)\s+\d+",
    r"^\d+(\.\d+)*\s*$",  # "3.2.1" numérotation seule
    # Listes à puces incomplètes
    r"^[-•]\s*\w+$",  # "- Item" sans contexte
]
_COMPILED_FRAGMENT_PATTERNS = [re.compile(p, re.IGNORECASE) for p in FRAGMENT_PATTERNS]

# Verbes indicateurs d'assertion (EN + FR) - au moins un doit être présent
ASSERTION_VERB_PATTERNS = [
    # Anglais
    r"\b(is|are|was|were|has|have|had|will|shall|must|should|can|may|might|could|would)\b",
    r"\b(provides?|requires?|enables?|allows?|supports?|includes?|defines?|describes?)\b",
    r"\b(ensures?|maintains?|manages?|controls?|configures?|implements?|integrates?)\b",
    r"\b(encrypts?|protects?|secures?|validates?|verifies?|monitors?)\b",
    # Français
    r"\b(est|sont|a|ont|sera|seront|doit|doivent|peut|peuvent)\b",
    r"\b(fournit|requiert|permet|supporte|inclut|d[eé]finit|d[eé]crit)\b",
    r"\b(assure|maintient|g[eè]re|contr[oô]le|configure|impl[eé]mente)\b",
]
_COMPILED_VERB_PATTERNS = [re.compile(p, re.IGNORECASE) for p in ASSERTION_VERB_PATTERNS]


def is_fragment(text: str) -> bool:
    """
    Détecte si le texte est un fragment (non-assertion).

    Un fragment est:
    - Un acronyme seul
    - Un titre/header
    - Une liste à puce incomplète
    - Un texte sans verbe (pas de prédicat)

    Returns:
        True si c'est un fragment à rejeter
    """
    text = text.strip()

    # Trop court = fragment
    if len(text) < 15:
        return True

    # Peu de mots = probablement un fragment
    words = text.split()
    if len(words) < 3:
        return True

    # Match pattern fragment explicite
    for pattern in _COMPILED_FRAGMENT_PATTERNS:
        if pattern.match(text):
            return True

    # Pas de verbe = pas d'assertion (sauf définitions "X = Y")
    if " = " not in text and ": " not in text:
        has_verb = any(p.search(text) for p in _COMPILED_VERB_PATTERNS)
        if not has_verb:
            return True

    return False


# ============================================================================
# CONSTANTS
# ============================================================================

MIN_TEXT_LENGTH = 15  # Minimum characters for valid assertion
CONDITIONAL_CONFIDENCE_THRESHOLD = 0.7
RARELY_CONFIDENCE_THRESHOLD = 0.9


# ============================================================================
# PROMOTION ENGINE
# ============================================================================

class PromotionEngine:
    """
    Moteur de décision pour la promotion des assertions.

    Workflow:
    1. V0 → V1 : Résolution d'ancre + décision promotion
    2. Chaque assertion génère une entrée de log
    3. Seules les PROMOTED passent en Information
    """

    def __init__(
        self,
        strict_promotion: bool = False,
        tenant_id: str = "default"
    ):
        """
        Args:
            strict_promotion: Si True, seules ALWAYS sont promues.
                              Si False, inclut CONDITIONAL (>=0.7) et RARELY (>=0.9)
            tenant_id: ID du tenant
        """
        self.strict_promotion = strict_promotion
        self.tenant_id = tenant_id

    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================

    def process_batch(
        self,
        batch_v0: AssertionBatchV0,
        chunk_to_docitem_map: Dict[str, List[str]],
        concept_ids: Optional[List[str]] = None,
        theme_ids: Optional[List[str]] = None,
    ) -> AssertionBatchV1:
        """
        Traite un batch V0 et produit un batch V1.

        Args:
            batch_v0: Batch d'assertions brutes (chunk-level)
            chunk_to_docitem_map: Mapping chunk_id → [docitem_ids]
            concept_ids: IDs des concepts disponibles pour linking
            theme_ids: IDs des thèmes disponibles

        Returns:
            AssertionBatchV1 avec assertions résolues et logs
        """
        result = AssertionBatchV1(
            document_id=batch_v0.document_id,
            stats={
                "total": len(batch_v0.assertions),
                "promoted_linked": 0,
                "promoted_unlinked": 0,
                "rejected": 0,
                "abstained": 0,
                "meta_filtered": 0,
                "fragment_filtered": 0,  # ChatGPT Priority 2
                "text_too_short": 0,
                "anchor_failed": 0,
                "pivot_violation": 0,
            }
        )

        for assertion_v0 in batch_v0.assertions:
            resolved, log_entry = self._process_assertion(
                assertion_v0=assertion_v0,
                chunk_id=batch_v0.chunk_id,
                chunk_to_docitem_map=chunk_to_docitem_map,
                concept_ids=concept_ids,
                theme_ids=theme_ids,
            )

            result.assertion_log.append(log_entry)

            if resolved:
                result.resolved_assertions.append(resolved)

                # Update stats
                if resolved.promotion.status == PromotionStatus.PROMOTED_LINKED:
                    result.stats["promoted_linked"] += 1
                elif resolved.promotion.status == PromotionStatus.PROMOTED_UNLINKED:
                    result.stats["promoted_unlinked"] += 1

            else:
                # Count rejection/abstention reasons
                if log_entry.rule_used == RuleUsed.META_PATTERN_REJECT:
                    result.stats["meta_filtered"] += 1
                elif log_entry.rule_used == RuleUsed.FRAGMENT_REJECT:
                    result.stats["fragment_filtered"] += 1
                elif log_entry.rule_used == RuleUsed.TEXT_TOO_SHORT:
                    result.stats["text_too_short"] += 1
                elif log_entry.rule_used in (
                    RuleUsed.ANCHOR_NO_DOCITEM_MATCH,
                    RuleUsed.ANCHOR_AMBIGUOUS_SPAN,
                    RuleUsed.ANCHOR_CROSS_DOCITEM
                ):
                    result.stats["anchor_failed"] += 1
                elif log_entry.rule_used == RuleUsed.PIVOT_VIOLATION:
                    result.stats["pivot_violation"] += 1

                if log_entry.status == PromotionStatus.REJECTED:
                    result.stats["rejected"] += 1
                else:
                    result.stats["abstained"] += 1

        logger.info(
            f"[OSMOSE:Pass1:PromotionEngine] Batch processed: "
            f"{result.stats['promoted_linked']} linked, "
            f"{result.stats['promoted_unlinked']} unlinked, "
            f"{result.stats['rejected']} rejected, "
            f"{result.stats['abstained']} abstained "
            f"(meta={result.stats['meta_filtered']}, "
            f"fragment={result.stats['fragment_filtered']}, "
            f"short={result.stats['text_too_short']}, "
            f"anchor={result.stats['anchor_failed']})"
        )

        return result

    # =========================================================================
    # CORE PROCESSING
    # =========================================================================

    def _process_assertion(
        self,
        assertion_v0: AssertionV0,
        chunk_id: str,
        chunk_to_docitem_map: Dict[str, List[str]],
        concept_ids: Optional[List[str]],
        theme_ids: Optional[List[str]],
    ) -> Tuple[Optional[ResolvedAssertionV1], AssertionLogEntry]:
        """
        Traite une assertion V0 et retourne (V1 ou None, LogEntry).

        Workflow:
        1. Check meta-pattern → REJECTED
        2. Check text length → REJECTED
        3. Resolve anchor → ABSTAINED si échec
        4. Apply promotion policy → PROMOTED ou ABSTAINED
        5. Check addressability → ABSTAINED si PIVOT_VIOLATION
        """
        # Step 1: Meta-pattern check (includes questions, vision descriptions)
        if self._is_meta_pattern(assertion_v0.text):
            return None, self._create_log_entry(
                assertion_v0=assertion_v0,
                status=PromotionStatus.REJECTED,
                rule_used=RuleUsed.META_PATTERN_REJECT,
                docitem_id="",
                reason_detail="Matches meta-description pattern"
            )

        # Step 1b: Fragment check (ChatGPT Priority 2 - assertion minimale)
        if is_fragment(assertion_v0.text):
            return None, self._create_log_entry(
                assertion_v0=assertion_v0,
                status=PromotionStatus.REJECTED,
                rule_used=RuleUsed.FRAGMENT_REJECT,
                docitem_id="",
                reason_detail="Fragment without predicate/verb"
            )

        # Step 2: Text length check
        if len(assertion_v0.text.strip()) < MIN_TEXT_LENGTH:
            return None, self._create_log_entry(
                assertion_v0=assertion_v0,
                status=PromotionStatus.REJECTED,
                rule_used=RuleUsed.TEXT_TOO_SHORT,
                docitem_id="",
                reason_detail=f"Text length {len(assertion_v0.text)} < {MIN_TEXT_LENGTH}"
            )

        # Step 3: Resolve anchor
        anchor_result = self._resolve_anchor(
            chunk_id=chunk_id,
            span=assertion_v0.span,
            chunk_to_docitem_map=chunk_to_docitem_map,
        )

        if anchor_result is None:
            return None, self._create_log_entry(
                assertion_v0=assertion_v0,
                status=PromotionStatus.ABSTAINED,
                rule_used=RuleUsed.ANCHOR_NO_DOCITEM_MATCH,
                abstain_reason=AbstainReason.NO_DOCITEM_ANCHOR,
                docitem_id="",
                reason_detail=f"No DocItem found for chunk {chunk_id}"
            )

        anchor, anchor_rule = anchor_result

        # Step 4: Apply promotion policy
        promotion_result = self._apply_promotion_policy(
            assertion_type=assertion_v0.type,
            confidence=assertion_v0.confidence,
        )

        # Step 5: Check addressability (pivots)
        # For now, we'll do simple concept matching later
        # This is a placeholder - real linking happens in link_to_concepts
        pivots = PivotsV1()

        # If no pivots and strict, that's a PIVOT_VIOLATION
        # But we defer this check until after concept linking

        # Build resolved assertion
        resolved = ResolvedAssertionV1(
            assertion_id=assertion_v0.assertion_id,
            text=assertion_v0.text,
            type=assertion_v0.type,
            confidence=assertion_v0.confidence,
            anchor=anchor,
            promotion=promotion_result,
            pivots=pivots,
            exact_quote=assertion_v0.exact_quote,
            rhetorical_role=assertion_v0.rhetorical_role,
            value=assertion_v0.value,
        )

        # Build log entry
        log_entry = self._create_log_entry(
            assertion_v0=assertion_v0,
            status=promotion_result.status,
            rule_used=promotion_result.rule_used,
            abstain_reason=promotion_result.abstain_reason,
            docitem_id=anchor.docitem_id,
            concept_id=pivots.concept_id,
            theme_id=pivots.theme_id,
            reason_detail=None
        )

        # Return None for non-promoted assertions
        if promotion_result.status in (PromotionStatus.REJECTED, PromotionStatus.ABSTAINED):
            return None, log_entry

        return resolved, log_entry

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _is_meta_pattern(self, text: str) -> bool:
        """Check if text matches any meta-description pattern."""
        text_lower = text.lower().strip()
        for pattern in _COMPILED_META_PATTERNS:
            if pattern.match(text_lower):
                return True
        return False

    def _resolve_anchor(
        self,
        chunk_id: str,
        span: "SpanV0",
        chunk_to_docitem_map: Dict[str, List[str]],
    ) -> Optional[Tuple[AnchorV1, RuleUsed]]:
        """
        Resolve chunk + span to DocItem anchor.

        Returns:
            (AnchorV1, rule_used) or None if failed
        """
        docitem_ids = chunk_to_docitem_map.get(chunk_id, [])

        if not docitem_ids:
            return None

        # For now, take the first DocItem
        # TODO: Improve with span-based matching
        docitem_id = docitem_ids[0]

        anchor = AnchorV1(
            docitem_id=docitem_id,
            span_start=span.start,
            span_end=span.end,
        )

        return anchor, RuleUsed.ANCHOR_OK

    def _apply_promotion_policy(
        self,
        assertion_type: AssertionTypeV1,
        confidence: float,
    ) -> PromotionDecision:
        """
        Apply promotion policy based on type and confidence.

        Returns:
            PromotionDecision with status, tier, and rule_used
        """
        tier = TYPE_TO_TIER.get(assertion_type, SupportTier.RARELY)

        # ALWAYS tier
        if tier == SupportTier.ALWAYS:
            return PromotionDecision(
                status=PromotionStatus.PROMOTED_UNLINKED,  # Will be upgraded to LINKED later
                support_tier=tier,
                rule_used=RuleUsed.TYPE_ALWAYS,
            )

        # NEVER tier
        if tier == SupportTier.NEVER:
            return PromotionDecision(
                status=PromotionStatus.REJECTED,
                support_tier=tier,
                rule_used=RuleUsed.TYPE_NEVER_REJECT,
            )

        # CONDITIONAL tier
        if tier == SupportTier.CONDITIONAL:
            if not self.strict_promotion and confidence >= CONDITIONAL_CONFIDENCE_THRESHOLD:
                return PromotionDecision(
                    status=PromotionStatus.PROMOTED_UNLINKED,
                    support_tier=tier,
                    rule_used=RuleUsed.TYPE_CONDITIONAL_PASS,
                )
            else:
                return PromotionDecision(
                    status=PromotionStatus.ABSTAINED,
                    support_tier=tier,
                    rule_used=RuleUsed.TYPE_CONDITIONAL_FAIL,
                    abstain_reason=AbstainReason.GENERIC_TERM if self.strict_promotion else None,
                )

        # RARELY tier
        if tier == SupportTier.RARELY:
            if not self.strict_promotion and confidence >= RARELY_CONFIDENCE_THRESHOLD:
                return PromotionDecision(
                    status=PromotionStatus.PROMOTED_UNLINKED,
                    support_tier=tier,
                    rule_used=RuleUsed.TYPE_RARELY_PASS,
                )
            else:
                return PromotionDecision(
                    status=PromotionStatus.ABSTAINED,
                    support_tier=tier,
                    rule_used=RuleUsed.TYPE_RARELY_FAIL,
                    abstain_reason=AbstainReason.SINGLE_MENTION,
                )

        # Fallback (should not happen)
        return PromotionDecision(
            status=PromotionStatus.ABSTAINED,
            support_tier=SupportTier.RARELY,
            rule_used=RuleUsed.TYPE_RARELY_FAIL,
        )

    def _create_log_entry(
        self,
        assertion_v0: AssertionV0,
        status: PromotionStatus,
        rule_used: RuleUsed,
        docitem_id: str,
        abstain_reason: Optional[AbstainReason] = None,
        concept_id: Optional[str] = None,
        theme_id: Optional[str] = None,
        claimkey_id: Optional[str] = None,
        reason_detail: Optional[str] = None,
    ) -> AssertionLogEntry:
        """Create an audit log entry."""
        return AssertionLogEntry(
            log_id=f"log_{uuid.uuid4().hex[:12]}",
            assertion_id=assertion_v0.assertion_id,
            status=status,
            rule_used=rule_used,
            abstain_reason=abstain_reason,
            docitem_id=docitem_id,
            concept_id=concept_id,
            theme_id=theme_id,
            claimkey_id=claimkey_id,
            reason_detail=reason_detail,
            timestamp=datetime.utcnow(),
        )

    # =========================================================================
    # POST-LINKING UPDATE
    # =========================================================================

    def update_with_concept_links(
        self,
        batch_v1: AssertionBatchV1,
        concept_links: Dict[str, str],  # assertion_id → concept_id
    ) -> AssertionBatchV1:
        """
        Update assertions with concept links after semantic linking.

        Args:
            batch_v1: Batch with PROMOTED_UNLINKED assertions
            concept_links: Mapping assertion_id → concept_id

        Returns:
            Updated batch with PROMOTED_LINKED where applicable
        """
        for assertion in batch_v1.resolved_assertions:
            if assertion.assertion_id in concept_links:
                concept_id = concept_links[assertion.assertion_id]
                assertion.pivots.concept_id = concept_id

                # Upgrade status
                if assertion.promotion.status == PromotionStatus.PROMOTED_UNLINKED:
                    assertion.promotion.status = PromotionStatus.PROMOTED_LINKED
                    batch_v1.stats["promoted_unlinked"] -= 1
                    batch_v1.stats["promoted_linked"] += 1

        # Check addressability for remaining UNLINKED
        for assertion in batch_v1.resolved_assertions:
            if assertion.promotion.status == PromotionStatus.PROMOTED_UNLINKED:
                if not assertion.pivots.is_addressable():
                    # PIVOT_VIOLATION - demote to ABSTAINED
                    assertion.promotion.status = PromotionStatus.ABSTAINED
                    assertion.promotion.rule_used = RuleUsed.PIVOT_VIOLATION
                    assertion.promotion.abstain_reason = AbstainReason.NO_CONCEPT_MATCH
                    batch_v1.stats["promoted_unlinked"] -= 1
                    batch_v1.stats["abstained"] += 1
                    batch_v1.stats["pivot_violation"] += 1

        return batch_v1


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def is_meta_pattern(text: str) -> bool:
    """Check if text matches any meta-description pattern."""
    text_lower = text.lower().strip()
    for pattern in _COMPILED_META_PATTERNS:
        if pattern.match(text_lower):
            return True
    return False


def get_promotion_engine(
    strict_promotion: bool = False,
    tenant_id: str = "default"
) -> PromotionEngine:
    """Factory function for PromotionEngine."""
    return PromotionEngine(
        strict_promotion=strict_promotion,
        tenant_id=tenant_id,
    )


__all__ = [
    "PromotionEngine",
    "get_promotion_engine",
    "is_meta_pattern",
    "is_fragment",
    # Patterns externalisés en YAML (2026-01-27)
    "META_REJECT_PATTERNS",           # Fallback uniquement (déprécié)
    "META_REJECT_PATTERNS_FALLBACK",  # Fallback minimal
    "FRAGMENT_PATTERNS",
    "MIN_TEXT_LENGTH",
    "CONDITIONAL_CONFIDENCE_THRESHOLD",
    "RARELY_CONFIDENCE_THRESHOLD",
]
