# src/knowbase/stratified/pass1/promotion_policy.py
"""
Politique de promotion Information-First pour MVP V1.

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from __future__ import annotations
import re
from typing import Tuple, Optional

from ..models.information import (
    InformationType,
    RhetoricalRole,
    PromotionStatus,
)


class PromotionPolicy:
    """
    Politique de promotion Information-First.

    Règles:
    - ALWAYS_PROMOTE: Types et rôles qui sont toujours promus
    - REJECT_PATTERNS: Patterns de texte méta à rejeter
    - Défaut: PROMOTED_UNLINKED (jamais de rejet silencieux)
    """

    # Types toujours promus
    ALWAYS_PROMOTE_TYPES = [
        InformationType.PRESCRIPTIVE,
        InformationType.DEFINITIONAL,
    ]

    # Rôles toujours promus avec ClaimKey
    ALWAYS_PROMOTE_ROLES = [
        RhetoricalRole.FACT,
        RhetoricalRole.DEFINITION,
        RhetoricalRole.INSTRUCTION,
    ]

    # Rôles promus mais sans ClaimKey
    PROMOTE_NO_CLAIMKEY_ROLES = [
        RhetoricalRole.EXAMPLE,
        RhetoricalRole.CAUTION,
    ]

    # Patterns de texte méta à rejeter
    REJECT_PATTERNS = [
        r"^this\s+(page|section|chapter|document)\s+(describes|shows|presents|explains|covers)",
        r"^see\s+also\b",
        r"^refer\s+to\b",
        r"^for\s+more\s+information",
        r"^note\s*:",
        r"^disclaimer\s*:",
        r"^copyright\b",
        r"^table\s+of\s+contents",
        r"^\d+\.\s*$",  # Numéros de section seuls
    ]

    def evaluate(
        self,
        assertion: dict
    ) -> Tuple[PromotionStatus, str]:
        """
        Évalue une assertion et retourne son statut de promotion.

        Args:
            assertion: Dict avec keys: text, type, rhetorical_role, value, confidence

        Returns:
            (PromotionStatus, reason)
        """
        text = assertion.get("text") or ""
        text = text.strip()
        text_lower = text.lower()
        assertion_type = assertion.get("type")
        rhetorical_role = assertion.get("rhetorical_role")
        has_value = assertion.get("value") is not None

        # 1. Rejet explicite par pattern
        for pattern in self.REJECT_PATTERNS:
            if re.match(pattern, text_lower, re.IGNORECASE):
                return PromotionStatus.REJECTED, f"meta_pattern:{pattern[:30]}"

        # 2. Rejet si texte trop court
        if len(text) < 15:
            return PromotionStatus.REJECTED, "text_too_short"

        # 3. Promotion automatique par type
        if assertion_type:
            try:
                info_type = InformationType(assertion_type)
                if info_type in self.ALWAYS_PROMOTE_TYPES:
                    return PromotionStatus.PROMOTED_LINKED, f"type:{info_type.value}"
            except ValueError:
                pass

        # 4. Promotion automatique par rôle
        if rhetorical_role:
            try:
                role = RhetoricalRole(rhetorical_role)
                if role in self.ALWAYS_PROMOTE_ROLES:
                    return PromotionStatus.PROMOTED_LINKED, f"role:{role.value}"
                if role in self.PROMOTE_NO_CLAIMKEY_ROLES:
                    return PromotionStatus.PROMOTED_UNLINKED, f"role_no_claimkey:{role.value}"
            except ValueError:
                pass

        # 5. Promotion si valeur présente
        if has_value:
            return PromotionStatus.PROMOTED_LINKED, "has_value"

        # 6. Défaut: PROMOTED_UNLINKED (jamais de rejet silencieux)
        return PromotionStatus.PROMOTED_UNLINKED, "no_clear_category"


# Instance singleton
_promotion_policy: Optional[PromotionPolicy] = None


def get_promotion_policy() -> PromotionPolicy:
    """Retourne l'instance singleton."""
    global _promotion_policy
    if _promotion_policy is None:
        _promotion_policy = PromotionPolicy()
    return _promotion_policy
