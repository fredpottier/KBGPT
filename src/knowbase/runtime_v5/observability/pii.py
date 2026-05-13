"""V5 PII Redactor — patterns universels (CH-52.7.1 / S6.1).

ADR V1.5 §3g §Y8 : layer Presidio entre OTel SDK et Phoenix exporter.

⚠️ V1.5 minimal : implémentation **maison patterns universels** (regex
domain-agnostic). Presidio reste l'option production future (nécessite
rebuild Docker — différé). L'interface `PIIRedactor.redact()` est compatible
Presidio (drop-in remplacement plus tard).

Patterns détectés (charte domain-agnostic, multilingue) :
- EMAIL : RFC 5322-like simple
- PHONE : E.164 + national formats EN/FR/DE/IT/ES (universal pattern)
- IPV4 / IPV6 : adresses IP
- IBAN : code-banking universel
- CREDIT_CARD : 13-19 chiffres + Luhn checksum
- SSN-LIKE : pattern 9-12 chiffres avec séparateurs (US SSN, FR NIR, etc.)
- CURRENCY_AMOUNT : montants avec devise (€, $, £)
- URL : http(s):// et www.
- UUID : UUID v1-v5
- NAME : PROPER_NOUN heuristic (mot capitalisé seul ou suivi d'un autre)
  → Désactivé par défaut (faux positifs élevés sur SAP/doc technique)

Limitations connues V1.5 maison :
- Pas d'analyse NER profonde (Presidio fait mieux)
- Pas de contexte sémantique (un nombre peut être PII ou pas)
- Conservatisme : on préfère redact-too-much vs leak

Mode redaction :
- `mask` : "[REDACTED:EMAIL]" (default)
- `hash` : sha256 8 chars → traçable pour debug sans révéler
- `keep_format` : "x@xx.xx" garder structure visuelle
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PIIType(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    IBAN = "iban"
    CREDIT_CARD = "credit_card"
    SSN_LIKE = "ssn_like"
    CURRENCY_AMOUNT = "currency_amount"
    URL = "url"
    UUID = "uuid"
    NAME = "name"


class RedactionMode(str, Enum):
    MASK = "mask"  # "[REDACTED:TYPE]"
    HASH = "hash"  # sha256 8 chars
    KEEP_FORMAT = "keep_format"  # "x@xx.xx" structure préservée


# ─── Patterns universels (domain-agnostic) ───────────────────────────────────

# RFC 5322 simplifié (suffisant pour PII detection)
_EMAIL_PATTERN = re.compile(
    r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    re.IGNORECASE,
)

# Phone E.164 + national formats : +33-1-23-45-67-89 / 06.12.34.56.78 / (555) 123-4567
# Au moins 8 chiffres consécutifs (avec séparateurs autorisés), souvent précédé de +
_PHONE_PATTERN = re.compile(
    r"(?:(?<![\w.])|^)"
    r"(?:\+\d{1,3}[-.\s]?)?"  # country code optional
    r"(?:\(?\d{1,4}\)?[-.\s]?)?"  # area code optional
    r"\d{2,4}[-.\s]?\d{2,4}[-.\s]?\d{2,4}(?:[-.\s]?\d{2,4})?"
    r"(?![\w.])",
)

# IPv4 : 0-255 dans chaque octet
_IPV4_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)

# IPv6 simplifié
_IPV6_PATTERN = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
    r"|\b(?:[0-9a-fA-F]{1,4}:){1,7}:\b"
    r"|\b::(?:[0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4}\b"
)

# IBAN : 2 lettres + 2 chiffres + 11-30 alphanum
_IBAN_PATTERN = re.compile(
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"
)

# Credit card : 13-19 chiffres (avec séparateurs)
_CREDIT_CARD_PATTERN = re.compile(
    r"\b(?:\d{4}[-.\s]?){3}\d{1,7}\b"
)

# SSN-like : 3 groupes de chiffres séparés (US 3-2-4, FR 13 chiffres, etc.)
_SSN_LIKE_PATTERN = re.compile(
    r"\b\d{3}[-.\s]\d{2}[-.\s]\d{4}\b"  # US SSN
    r"|\b[12]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}(?:\s?\d{2})?\b"  # FR NIR
)

# Currency amount : 1234.56 € / $1,234.56 / £1234
_CURRENCY_PATTERN = re.compile(
    r"(?:[€$£¥]\s?\d{1,3}(?:[,.\s]?\d{3})*(?:[.,]\d{2})?)"
    r"|(?:\d{1,3}(?:[,.\s]?\d{3})*(?:[.,]\d{2})?\s?(?:[€$£¥]|EUR|USD|GBP|JPY|CHF))"
)

# URL : http(s):// + www.
_URL_PATTERN = re.compile(
    r"\bhttps?://[\w.-]+(?:/[\w./~%?#&=+-]*)?",
    re.IGNORECASE,
)

# UUID v1-v5
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


# Ordre d'application (priorité haute en premier — évite double matches)
_PATTERNS_ORDERED: list[tuple[PIIType, re.Pattern]] = [
    (PIIType.URL, _URL_PATTERN),  # URL avant IPV4 (URL peut contenir IP)
    (PIIType.EMAIL, _EMAIL_PATTERN),
    (PIIType.UUID, _UUID_PATTERN),
    (PIIType.IBAN, _IBAN_PATTERN),
    (PIIType.CREDIT_CARD, _CREDIT_CARD_PATTERN),
    (PIIType.SSN_LIKE, _SSN_LIKE_PATTERN),
    (PIIType.CURRENCY_AMOUNT, _CURRENCY_PATTERN),
    (PIIType.IPV4, _IPV4_PATTERN),
    (PIIType.IPV6, _IPV6_PATTERN),
    (PIIType.PHONE, _PHONE_PATTERN),
]


# ─── Result types ────────────────────────────────────────────────────────────


@dataclass
class PIIMatch:
    """Détection d'une PII dans un texte."""
    pii_type: PIIType
    start: int
    end: int
    original: str
    redacted: str


@dataclass
class RedactionResult:
    """Résultat d'une redaction."""
    text: str  # texte après redaction
    matches: list[PIIMatch] = field(default_factory=list)

    def has_pii(self) -> bool:
        return bool(self.matches)

    def n_matches(self) -> int:
        return len(self.matches)

    def types_found(self) -> set[PIIType]:
        return {m.pii_type for m in self.matches}


# ─── PIIRedactor ─────────────────────────────────────────────────────────────


class PIIRedactor:
    """Détection + redaction PII via regex universels.

    Args:
        enabled_types : set des PIIType actifs (default = tous sauf NAME)
        mode : RedactionMode (default MASK)
        hash_salt : salt pour mode HASH (config OSMOSE)
    """

    DEFAULT_ENABLED = frozenset({
        PIIType.EMAIL,
        PIIType.PHONE,
        PIIType.IPV4,
        PIIType.IPV6,
        PIIType.IBAN,
        PIIType.CREDIT_CARD,
        PIIType.SSN_LIKE,
        PIIType.CURRENCY_AMOUNT,
        PIIType.URL,
        PIIType.UUID,
    })

    def __init__(
        self,
        enabled_types: Optional[frozenset[PIIType]] = None,
        mode: RedactionMode = RedactionMode.MASK,
        hash_salt: str = "v5_pii_redactor",
    ):
        # NOTE : frozenset() vide est valide (désactive tout) — utiliser `is None` check
        self.enabled_types = (
            self.DEFAULT_ENABLED if enabled_types is None else enabled_types
        )
        self.mode = mode
        self.hash_salt = hash_salt

    def _redact_match(self, pii_type: PIIType, original: str) -> str:
        """Applique le mode de redaction à un match."""
        if self.mode == RedactionMode.MASK:
            return f"[REDACTED:{pii_type.value.upper()}]"
        if self.mode == RedactionMode.HASH:
            digest = hashlib.sha256((self.hash_salt + original).encode("utf-8")).hexdigest()[:8]
            return f"[{pii_type.value.upper()}#{digest}]"
        if self.mode == RedactionMode.KEEP_FORMAT:
            # Replace alphanum chars : digits → 0, letters → x, keep punct/space
            out = []
            for c in original:
                if c.isdigit():
                    out.append("0")
                elif c.isalpha():
                    out.append("x")
                else:
                    out.append(c)
            return "".join(out)
        return original

    def redact(self, text: str) -> RedactionResult:
        """Redact toutes les PII détectées dans `text`.

        Note : passes multiples sur le texte (1 par pattern), mais sur le
        texte ORIGINAL (pas le texte déjà redacted) pour éviter les overlaps.
        Les matches sont consolidés en un seul rebuild final.

        Returns:
            RedactionResult avec texte redacted + liste des matches détectés
        """
        if not text:
            return RedactionResult(text="", matches=[])

        # Pass 1 : collect all (start, end, type, original) sans overlap
        all_matches: list[tuple[int, int, PIIType, str]] = []
        used_ranges: list[tuple[int, int]] = []

        def _overlaps(start: int, end: int) -> bool:
            for s, e in used_ranges:
                if not (end <= s or start >= e):
                    return True
            return False

        for pii_type, pattern in _PATTERNS_ORDERED:
            if pii_type not in self.enabled_types:
                continue
            for m in pattern.finditer(text):
                s, e = m.start(), m.end()
                # Skip si overlap avec un match déjà détecté (priorité haute first)
                if _overlaps(s, e):
                    continue
                # Skip si match vide ou trop court (faux positif phones courts)
                matched = m.group(0)
                if pii_type == PIIType.PHONE and len(re.sub(r"\D", "", matched)) < 8:
                    continue
                # CREDIT_CARD : valide Luhn (anti-faux-positif IDs longs)
                if pii_type == PIIType.CREDIT_CARD and not _luhn_valid(matched):
                    continue
                all_matches.append((s, e, pii_type, matched))
                used_ranges.append((s, e))

        # Pass 2 : trie par position + rebuild
        all_matches.sort(key=lambda x: x[0])
        out_parts = []
        prev_end = 0
        matches_record: list[PIIMatch] = []
        for s, e, pii_type, original in all_matches:
            out_parts.append(text[prev_end:s])
            redacted = self._redact_match(pii_type, original)
            out_parts.append(redacted)
            matches_record.append(PIIMatch(
                pii_type=pii_type, start=s, end=e,
                original=original, redacted=redacted,
            ))
            prev_end = e
        out_parts.append(text[prev_end:])

        return RedactionResult(
            text="".join(out_parts),
            matches=matches_record,
        )

    def redact_dict(self, payload: dict) -> dict:
        """Redact récursif sur un dict (utile pour OTel attribute values)."""
        return _redact_recursive(payload, self)


def _redact_recursive(value: object, redactor: PIIRedactor) -> object:
    if isinstance(value, str):
        return redactor.redact(value).text
    if isinstance(value, dict):
        return {k: _redact_recursive(v, redactor) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_recursive(v, redactor) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_recursive(v, redactor) for v in value)
    return value


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _luhn_valid(card_number: str) -> bool:
    """Algorithme de Luhn pour valider une carte bancaire (anti-faux-positif).

    Reject les séquences qui ne sont pas une vraie CB.
    """
    digits = [int(c) for c in card_number if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ─── Singleton helper ────────────────────────────────────────────────────────


_default_redactor: Optional[PIIRedactor] = None


def get_default_redactor() -> PIIRedactor:
    global _default_redactor
    if _default_redactor is None:
        _default_redactor = PIIRedactor()
    return _default_redactor


def reset_default_redactor() -> None:
    global _default_redactor
    _default_redactor = None
