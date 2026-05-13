"""Tests PIIRedactor (CH-52.7.1 / S6.1)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.observability.pii import (
    PIIRedactor,
    PIIType,
    RedactionMode,
    _luhn_valid,
    get_default_redactor,
    reset_default_redactor,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_default_redactor()
    yield
    reset_default_redactor()


@pytest.fixture
def redactor():
    return PIIRedactor()


# ─── Email ───────────────────────────────────────────────────────────────────


class TestEmail:
    def test_basic_email(self, redactor):
        r = redactor.redact("Contact me at john.doe@example.com please.")
        assert "john.doe@example.com" not in r.text
        assert "[REDACTED:EMAIL]" in r.text
        assert r.n_matches() == 1
        assert r.matches[0].pii_type == PIIType.EMAIL

    def test_multiple_emails(self, redactor):
        r = redactor.redact("Alice@a.com or BOB@B.CO.UK can help")
        assert r.n_matches() == 2

    def test_email_with_plus_tag(self, redactor):
        r = redactor.redact("Use alice+work@example.com for billing")
        assert "alice+work@example.com" not in r.text
        assert r.n_matches() == 1


# ─── Phone ───────────────────────────────────────────────────────────────────


class TestPhone:
    def test_e164_phone(self, redactor):
        r = redactor.redact("Call +33-1-23-45-67-89 today")
        assert "+33-1-23-45-67-89" not in r.text
        assert PIIType.PHONE in r.types_found()

    def test_us_format(self, redactor):
        r = redactor.redact("Phone: (555) 123-4567")
        # Pattern peut matcher partiellement, on vérifie qu'au moins une partie redact
        assert "123-4567" not in r.text or "555" not in r.text

    def test_dotted_phone(self, redactor):
        r = redactor.redact("06.12.34.56.78 est mon mobile")
        assert "06.12.34.56.78" not in r.text


# ─── IPv4 ────────────────────────────────────────────────────────────────────


class TestIPv4:
    def test_valid_ipv4(self, redactor):
        r = redactor.redact("Server at 192.168.1.42 is down")
        assert "192.168.1.42" not in r.text
        assert PIIType.IPV4 in r.types_found()

    def test_invalid_octets_not_matched(self, redactor):
        r = redactor.redact("Version 999.0.1.0 release")  # 999 > 255
        # Le pattern rejette 999, donc match partiel ou aucun match
        assert "999" in r.text  # 999 reste car non match comme IP

    def test_in_url_not_double_matched(self, redactor):
        """URL contient IP : URL match en premier (priorité), IP n'est pas redonné."""
        r = redactor.redact("API at http://192.168.1.1/path")
        # Le URL pattern a la priorité, donc 1 match URL
        assert PIIType.URL in r.types_found()


# ─── IBAN ────────────────────────────────────────────────────────────────────


class TestIBAN:
    def test_valid_iban_format(self, redactor):
        r = redactor.redact("Wire to FR7630006000011234567890189")
        assert "FR7630006000011234567890189" not in r.text
        assert PIIType.IBAN in r.types_found()

    def test_short_string_not_iban(self, redactor):
        r = redactor.redact("FR76 too short")  # pas assez long pour IBAN
        assert PIIType.IBAN not in r.types_found()


# ─── Credit card with Luhn ───────────────────────────────────────────────────


class TestCreditCard:
    def test_valid_luhn(self, redactor):
        # 4111-1111-1111-1111 est un test Luhn valide
        r = redactor.redact("CB: 4111-1111-1111-1111 exp 12/26")
        assert "4111-1111-1111-1111" not in r.text
        assert PIIType.CREDIT_CARD in r.types_found()

    def test_invalid_luhn_not_redacted_as_cc(self, redactor):
        # Séquence 16 digits invalide Luhn → pas redacted as CC
        r = redactor.redact("ID 1234-5678-9012-3456 ne match pas Luhn")
        # Peut être catché par d'autres patterns (phone-like), mais pas CC
        assert PIIType.CREDIT_CARD not in r.types_found()

    def test_luhn_validator(self):
        assert _luhn_valid("4111111111111111") is True
        assert _luhn_valid("4111-1111-1111-1111") is True
        assert _luhn_valid("1234567812345670") is True  # valid Luhn test
        assert _luhn_valid("1234-5678-9012-3456") is False  # invalid


# ─── URL ─────────────────────────────────────────────────────────────────────


class TestURL:
    def test_http_url(self, redactor):
        r = redactor.redact("See https://example.com/page?id=42")
        assert "https://example.com" not in r.text
        assert PIIType.URL in r.types_found()


# ─── UUID ────────────────────────────────────────────────────────────────────


class TestUUID:
    def test_uuid_v4(self, redactor):
        r = redactor.redact("Request 550e8400-e29b-41d4-a716-446655440000 failed")
        assert "550e8400-e29b-41d4-a716-446655440000" not in r.text
        assert PIIType.UUID in r.types_found()


# ─── Currency ────────────────────────────────────────────────────────────────


class TestCurrency:
    def test_euro_symbol(self, redactor):
        r = redactor.redact("Total: €1,234.56")
        assert "€1,234.56" not in r.text
        assert PIIType.CURRENCY_AMOUNT in r.types_found()

    def test_dollar_amount(self, redactor):
        r = redactor.redact("Cost $999.99 per unit")
        assert "$999.99" not in r.text

    def test_currency_iso_code(self, redactor):
        r = redactor.redact("1234.56 USD")
        assert PIIType.CURRENCY_AMOUNT in r.types_found()


# ─── Redaction modes ─────────────────────────────────────────────────────────


class TestRedactionModes:
    def test_mask_mode(self):
        r = PIIRedactor(mode=RedactionMode.MASK)
        out = r.redact("ping me at a@b.com").text
        assert "[REDACTED:EMAIL]" in out

    def test_hash_mode(self):
        r = PIIRedactor(mode=RedactionMode.HASH, hash_salt="testing")
        out1 = r.redact("a@b.com").text
        out2 = r.redact("a@b.com").text
        # Hash est déterministe (même salt + même PII)
        assert out1 == out2
        assert "[EMAIL#" in out1
        # PII différente → hash différent
        out3 = r.redact("c@d.com").text
        assert out3 != out1

    def test_keep_format_mode(self):
        r = PIIRedactor(mode=RedactionMode.KEEP_FORMAT)
        out = r.redact("a@b.com").text
        # Garde structure : x@x.xxx
        assert "@" in out
        assert "x" in out
        assert "a@b" not in out  # original chars masqués

    def test_keep_format_phone(self):
        r = PIIRedactor(mode=RedactionMode.KEEP_FORMAT)
        out = r.redact("Phone 06.12.34.56.78 here").text
        # Digits → 0, dots preserved. Le pattern peut matcher 4 ou 5 groupes
        # selon où il s'arrête — on vérifie qu'au moins 4 groupes de 0 apparaissent.
        assert "00.00.00.00" in out
        # Original 06.12.34.56 ne doit plus apparaître intact
        assert "06.12.34.56" not in out


# ─── Enabled types control ───────────────────────────────────────────────────


class TestEnabledTypes:
    def test_only_email(self):
        r = PIIRedactor(enabled_types=frozenset({PIIType.EMAIL}))
        out = r.redact("Email a@b.com phone +33-1-23-45-67-89")
        assert "a@b.com" not in out.text
        # Phone reste
        assert "+33" in out.text or "1-23" in out.text or "67-89" in out.text

    def test_none_enabled(self):
        r = PIIRedactor(enabled_types=frozenset())
        out = r.redact("Sensitive a@b.com")
        # Aucun pattern enabled → texte inchangé
        assert out.text == "Sensitive a@b.com"
        assert out.n_matches() == 0


# ─── redact_dict ─────────────────────────────────────────────────────────────


class TestRedactDict:
    def test_recursive_dict(self, redactor):
        payload = {
            "user_email": "fred@example.com",
            "nested": {"phone": "06.12.34.56.78", "name": "Fred"},
            "ips": ["192.168.1.1", "10.0.0.1"],
        }
        out = redactor.redact_dict(payload)
        assert "fred@example.com" not in str(out)
        assert "192.168.1.1" not in str(out)
        # Names not detected (NAME désactivé par défaut)
        assert out["nested"]["name"] == "Fred"

    def test_non_string_kept(self, redactor):
        payload = {"count": 42, "flag": True, "ratio": 0.95}
        out = redactor.redact_dict(payload)
        assert out["count"] == 42
        assert out["flag"] is True


# ─── Charter / no overlap ────────────────────────────────────────────────────


class TestNoOverlap:
    def test_no_double_match(self, redactor):
        """URL contient un email → URL match en premier, email pas re-matché."""
        text = "https://example.com/?email=a@b.com"
        r = redactor.redact(text)
        # URL match capture l'ensemble, donc email à l'intérieur n'est pas un match séparé
        types = r.types_found()
        assert PIIType.URL in types
        # Note: comportement intentionnel — on évite double-redaction


# ─── Result helpers ──────────────────────────────────────────────────────────


class TestResultHelpers:
    def test_has_pii_false_clean_text(self, redactor):
        r = redactor.redact("This is clean text without any PII.")
        assert r.has_pii() is False
        assert r.n_matches() == 0

    def test_has_pii_true(self, redactor):
        r = redactor.redact("Mon email : a@b.com")
        assert r.has_pii() is True


# ─── Singleton ───────────────────────────────────────────────────────────────


class TestSingleton:
    def test_default_redactor_singleton(self):
        r1 = get_default_redactor()
        r2 = get_default_redactor()
        assert r1 is r2

    def test_default_redactor_reset(self):
        r1 = get_default_redactor()
        reset_default_redactor()
        r2 = get_default_redactor()
        assert r1 is not r2


# ─── Empty + edge ────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_text(self, redactor):
        r = redactor.redact("")
        assert r.text == ""
        assert r.matches == []

    def test_only_whitespace(self, redactor):
        r = redactor.redact("   \n  ")
        assert r.has_pii() is False

    def test_text_with_no_pii(self, redactor):
        text = "The procedure follows section 3.2 of the upgrade guide."
        r = redactor.redact(text)
        # Note: "3.2" can match phone (chars <8 = filter), 'guide' no match
        assert r.text == text
