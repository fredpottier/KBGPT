"""
Log Sanitization - Phase 0 Security Hardening - Semaine 2.3.

Prévient les log injection attacks en sanitisant les inputs avant logging.
"""
import re
from typing import Any, Optional


# Regex pour détecter les caractères de contrôle dangereux
CONTROL_CHARS_REGEX = re.compile(r'[\x00-\x1f\x7f]')

# Max length pour les valeurs loggées (prévient log flooding)
MAX_LOG_VALUE_LENGTH = 500


def sanitize_for_log(value: Any, max_length: Optional[int] = None) -> str:
    """
    Sanitize une valeur avant de la logger.

    Prévient les log injection attacks en :
    - Remplaçant les newlines par \\n
    - Remplaçant les tabs par \\t
    - Remplaçant les caractères de contrôle par [CTRL]
    - Tronquant à max_length chars

    Args:
        value: La valeur à sanitiser (sera convertie en string)
        max_length: Longueur maximale (défaut: MAX_LOG_VALUE_LENGTH)

    Returns:
        str: La valeur sanitisée, safe pour logging

    Examples:
        >>> sanitize_for_log("Hello\\nWorld")
        'Hello\\\\nWorld'

        >>> sanitize_for_log("User\\x00Admin")
        'User[CTRL]Admin'

        >>> sanitize_for_log("A" * 1000)
        'AAA...[truncated 500 chars]'
    """
    if value is None:
        return "None"

    # Convertir en string
    str_value = str(value)

    # Remplacer newlines et tabs AVANT de remplacer les control chars
    str_value = str_value.replace('\n', '\\n')
    str_value = str_value.replace('\r', '\\r')
    str_value = str_value.replace('\t', '\\t')

    # Remplacer autres caractères de contrôle par [CTRL]
    str_value = CONTROL_CHARS_REGEX.sub('[CTRL]', str_value)

    # Tronquer si trop long
    if max_length is None:
        max_length = MAX_LOG_VALUE_LENGTH

    if len(str_value) > max_length:
        str_value = f"{str_value[:max_length]}...[truncated {len(str_value) - max_length} chars]"

    return str_value


def sanitize_dict_for_log(data: dict, max_length: Optional[int] = None) -> dict:
    """
    Sanitize récursivement un dict pour logging.

    Args:
        data: Le dict à sanitiser
        max_length: Longueur max par valeur

    Returns:
        dict: Dict avec toutes les valeurs sanitisées
    """
    sanitized = {}
    for key, value in data.items():
        key_sanitized = sanitize_for_log(key, max_length=50)  # Keys plus courtes

        if isinstance(value, dict):
            sanitized[key_sanitized] = sanitize_dict_for_log(value, max_length)
        elif isinstance(value, (list, tuple)):
            sanitized[key_sanitized] = [sanitize_for_log(v, max_length) for v in value]
        else:
            sanitized[key_sanitized] = sanitize_for_log(value, max_length)

    return sanitized


def sanitize_sensitive_fields(data: dict, sensitive_fields: Optional[list] = None) -> dict:
    """
    Masque les champs sensibles dans un dict avant logging.

    Args:
        data: Le dict à sanitiser
        sensitive_fields: Liste des noms de champs sensibles (défaut: mots-clés communs)

    Returns:
        dict: Dict avec champs sensibles masqués
    """
    if sensitive_fields is None:
        sensitive_fields = [
            'password', 'password_hash', 'token', 'access_token', 'refresh_token',
            'api_key', 'secret', 'private_key', 'apikey', 'auth', 'authorization'
        ]

    sanitized = {}
    for key, value in data.items():
        key_lower = key.lower()

        # Masquer si clé sensible
        if any(sensitive in key_lower for sensitive in sensitive_fields):
            sanitized[key] = '***REDACTED***'
        elif isinstance(value, dict):
            sanitized[key] = sanitize_sensitive_fields(value, sensitive_fields)
        else:
            sanitized[key] = value

    return sanitized


def safe_log_message(template: str, **kwargs) -> str:
    """
    Construit un message de log sécurisé en sanitisant tous les paramètres.

    Args:
        template: Template du message (style f-string avec {placeholders})
        **kwargs: Paramètres à insérer dans le template

    Returns:
        str: Message de log sanitisé

    Examples:
        >>> safe_log_message("User {user} logged in from {ip}", user="admin\\n[FAKE]", ip="127.0.0.1")
        'User admin\\\\n[FAKE] logged in from 127.0.0.1'
    """
    # Sanitiser tous les kwargs
    sanitized_kwargs = {
        key: sanitize_for_log(value)
        for key, value in kwargs.items()
    }

    # Format avec les valeurs sanitisées
    try:
        return template.format(**sanitized_kwargs)
    except (KeyError, ValueError) as e:
        # Fallback si template invalide
        return f"[LOG ERROR: {e}] {template} | params: {sanitized_kwargs}"


def sanitize_exception_for_log(exc: Exception, include_traceback: bool = False) -> dict:
    """
    Sanitize une exception pour logging sécurisé.

    Args:
        exc: L'exception à sanitiser
        include_traceback: Inclure le traceback (False par défaut pour éviter leakage)

    Returns:
        dict: Exception sanitisée avec type, message, et optionnellement traceback
    """
    import traceback as tb

    result = {
        'type': exc.__class__.__name__,
        'message': sanitize_for_log(str(exc), max_length=1000)
    }

    if include_traceback:
        result['traceback'] = sanitize_for_log(
            ''.join(tb.format_exception(type(exc), exc, exc.__traceback__)),
            max_length=5000
        )

    return result


# Alias pour compatibilité
escape_for_log = sanitize_for_log
