# src/knowbase/stratified/claimkey/patterns.py
"""
Patterns ClaimKey Niveau A pour MVP V1.
Inférence déterministe sans LLM.

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class PatternMatch:
    """Résultat d'un match de pattern."""
    claimkey_id: str
    key: str
    domain: str
    canonical_question: str
    value_kind: str
    match_text: str
    inference_method: str = "pattern_level_a"


class ClaimKeyPatterns:
    """
    Patterns lexicaux pour inference ClaimKey Niveau A.

    Pas de LLM - patterns déterministes uniquement.
    """

    PATTERNS = [
        # SLA / Availability
        {
            "pattern": r"(\d+(?:\.\d+)?)\s*%\s*(sla|availability|uptime)",
            "key_template": "sla_{context}_availability",
            "domain": "sla.availability",
            "question": "What is the SLA availability percentage?",
            "value_kind": "percent"
        },

        # TLS / Encryption
        {
            "pattern": r"tls\s*(\d+(?:\.\d+)?)",
            "key_template": "tls_min_version",
            "domain": "security.encryption",
            "question": "What is the minimum TLS version required?",
            "value_kind": "version"
        },
        {
            "pattern": r"(?:encryption|encrypted)\s*(at\s*rest)",
            "key_template": "encryption_at_rest",
            "domain": "security.encryption",
            "question": "Is encryption at rest enabled?",
            "value_kind": "boolean"
        },
        {
            "pattern": r"(?:encryption|encrypted)\s*(in\s*transit)",
            "key_template": "encryption_in_transit",
            "domain": "security.encryption",
            "question": "Is encryption in transit enabled?",
            "value_kind": "boolean"
        },

        # Backup / Retention
        {
            "pattern": r"backup[s]?\s*(?:are\s*)?(?:performed\s*)?(daily|weekly|hourly|every\s*\d+\s*hours?)",
            "key_template": "backup_frequency",
            "domain": "operations.backup",
            "question": "How often are backups performed?",
            "value_kind": "enum"
        },
        {
            "pattern": r"(daily|weekly|hourly)\s*backup[s]?",
            "key_template": "backup_frequency",
            "domain": "operations.backup",
            "question": "How often are backups performed?",
            "value_kind": "enum"
        },
        {
            "pattern": r"retention\s*(?:period)?\s*(?:of|:)?\s*(\d+)\s*(days?|months?|years?)",
            "key_template": "data_retention_period",
            "domain": "compliance.retention",
            "question": "What is the data retention period?",
            "value_kind": "number"
        },

        # Data Residency
        {
            "pattern": r"data\s*(?:must|shall)?\s*(?:remain|stay|stored?)\s*(?:in|within)\s*(\w+)",
            "key_template": "data_residency_{country}",
            "domain": "compliance.residency",
            "question": "Must data remain in {country}?",
            "value_kind": "boolean"
        },

        # Size Thresholds
        {
            "pattern": r"(?:above|over|exceeds?|greater\s+than)\s*(\d+)\s*(tib|tb|gb)",
            "key_template": "{context}_size_threshold",
            "domain": "infrastructure.sizing",
            "question": "What is the size threshold for {context}?",
            "value_kind": "number"
        },

        # Responsibility
        {
            "pattern": r"(customer|sap|vendor)\s*(?:is)?\s*(?:responsible|responsibility|manages?)",
            "key_template": "{topic}_responsibility",
            "domain": "operations.responsibility",
            "question": "Who is responsible for {topic}?",
            "value_kind": "enum"
        },

        # Version Requirements
        {
            "pattern": r"(?:minimum|required|supported)\s*version\s*:?\s*(\d+(?:\.\d+)*)",
            "key_template": "{product}_min_version",
            "domain": "compatibility.version",
            "question": "What is the minimum version required for {product}?",
            "value_kind": "version"
        },

        # Patch / Update
        {
            "pattern": r"(?:patch(?:es)?|update[s]?)\s*(?:are\s*)?(?:applied|installed)?\s*(daily|weekly|monthly|quarterly)",
            "key_template": "patch_frequency",
            "domain": "operations.patching",
            "question": "How often are patches applied?",
            "value_kind": "enum"
        },
        {
            "pattern": r"(daily|weekly|monthly|quarterly)\s*(?:patch(?:es)?|update[s]?)",
            "key_template": "patch_frequency",
            "domain": "operations.patching",
            "question": "How often are patches applied?",
            "value_kind": "enum"
        },

        # RTO / RPO (Recovery objectives)
        {
            "pattern": r"rto\s*(?:of|:)?\s*(\d+)\s*(hours?|minutes?|seconds?)",
            "key_template": "rto_target",
            "domain": "sla.recovery",
            "question": "What is the Recovery Time Objective (RTO)?",
            "value_kind": "number"
        },
        {
            "pattern": r"rpo\s*(?:of|:)?\s*(\d+)\s*(hours?|minutes?|seconds?)",
            "key_template": "rpo_target",
            "domain": "sla.recovery",
            "question": "What is the Recovery Point Objective (RPO)?",
            "value_kind": "number"
        },
    ]

    # Questions canoniques pour claimkeys connus
    CANONICAL_QUESTIONS = {
        "tls_min_version": "What is the minimum TLS version required?",
        "sla_availability": "What is the SLA availability percentage?",
        "backup_frequency": "How often are backups performed?",
        "data_retention_period": "What is the data retention period?",
        "data_residency_china": "Must data remain in China?",
        "patch_frequency": "How often are patches applied?",
        "encryption_at_rest": "Is encryption at rest enabled?",
        "encryption_in_transit": "Is encryption in transit enabled?",
        "rto_target": "What is the Recovery Time Objective (RTO)?",
        "rpo_target": "What is the Recovery Point Objective (RPO)?",
    }

    def infer_claimkey(
        self,
        text: str,
        context: dict
    ) -> Optional[PatternMatch]:
        """
        Tente d'inférer un ClaimKey depuis le texte.

        Args:
            text: Texte à analyser
            context: Contexte (product, topic, etc.)

        Returns:
            PatternMatch ou None si pas de match
        """
        text_lower = text.lower()

        for pattern_def in self.PATTERNS:
            match = re.search(pattern_def["pattern"], text_lower, re.IGNORECASE)
            if match:
                # Résoudre le template
                key = self._resolve_template(
                    pattern_def["key_template"],
                    match,
                    context
                )
                claimkey_id = f"ck_{key}"

                # Résoudre la question
                question = self._resolve_question(
                    pattern_def["question"],
                    match,
                    context
                )

                return PatternMatch(
                    claimkey_id=claimkey_id,
                    key=key,
                    domain=pattern_def["domain"],
                    canonical_question=question,
                    value_kind=pattern_def["value_kind"],
                    match_text=match.group(0)
                )

        return None

    def _resolve_template(
        self,
        template: str,
        match: re.Match,
        context: dict
    ) -> str:
        """Résout un template de clé."""
        result = template

        # {context} → product ou "general"
        if "{context}" in result:
            ctx = context.get("product", "general").lower()
            ctx = re.sub(r"[^a-z0-9]", "_", ctx)
            result = result.replace("{context}", ctx)

        # {country} → groupe capturé ou "unknown"
        if "{country}" in result:
            country = "unknown"
            for group in match.groups():
                if group and re.match(r"^[a-z]+$", group.lower()):
                    country = group.lower()
                    break
            result = result.replace("{country}", country)

        # {match} → premier groupe non-numérique
        if "{match}" in result:
            for group in match.groups():
                if group and not group.replace(".", "").isdigit():
                    clean = re.sub(r"[^a-z]", "_", group.lower())
                    result = result.replace("{match}", clean)
                    break

        # {topic} → theme courant ou "general"
        if "{topic}" in result:
            topic = context.get("current_theme", "general").lower()
            topic = re.sub(r"[^a-z0-9]", "_", topic)
            result = result.replace("{topic}", topic)

        # {product} → product ou "unknown"
        if "{product}" in result:
            product = context.get("product", "unknown").lower()
            product = re.sub(r"[^a-z0-9]", "_", product)
            result = result.replace("{product}", product)

        return result

    def _resolve_question(
        self,
        template: str,
        match: re.Match,
        context: dict
    ) -> str:
        """Résout un template de question."""
        result = template

        # Mêmes substitutions que _resolve_template
        for placeholder in ["{context}", "{country}", "{match}", "{topic}", "{product}"]:
            if placeholder in result:
                key = placeholder[1:-1]
                value = context.get(key, "")
                if not value and match.groups():
                    for group in match.groups():
                        if group:
                            value = group
                            break
                result = result.replace(placeholder, value or "unknown")

        return result

    def get_canonical_question(self, claimkey_id: str) -> str:
        """Retourne la question canonique pour un ClaimKey."""
        key = claimkey_id.replace("ck_", "")
        return self.CANONICAL_QUESTIONS.get(key, f"Question for {claimkey_id}")


# Instance singleton
_claimkey_patterns: Optional[ClaimKeyPatterns] = None


def get_claimkey_patterns() -> ClaimKeyPatterns:
    """Retourne l'instance singleton."""
    global _claimkey_patterns
    if _claimkey_patterns is None:
        _claimkey_patterns = ClaimKeyPatterns()
    return _claimkey_patterns
