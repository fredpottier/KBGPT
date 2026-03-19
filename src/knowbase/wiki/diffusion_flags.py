"""
Diffusion flags — Table P1 du plan Contradiction Intelligence.

Déduit les flags show_in_article, show_in_chat, show_in_homepage,
requires_review à partir de tension_nature et tension_level.

Ces flags sont déduits par code (PAS par le LLM).
"""

from __future__ import annotations

from typing import Optional, Tuple


def derive_diffusion_flags(
    tension_nature: Optional[str],
    tension_level: Optional[str],
) -> Tuple[bool, bool]:
    """
    Retourne (show_in_article, show_in_chat) selon la table P1.

    Si tension_nature/tension_level sont None (non classifié),
    on affiche par défaut dans l'article uniquement.
    """
    if tension_level == "none":
        return False, False

    if tension_nature is None or tension_level is None:
        # Non classifié → afficher dans l'article par prudence
        return True, False

    return _DIFFUSION_TABLE.get(
        (tension_nature, tension_level),
        (True, False),  # Default
    )


def derive_full_diffusion_flags(
    tension_nature: Optional[str],
    tension_level: Optional[str],
) -> dict:
    """
    Retourne le dict complet des flags de diffusion selon la table P1.
    """
    if tension_level == "none":
        return {
            "show_in_article": False,
            "show_in_chat": False,
            "show_in_homepage": False,
            "requires_review": False,
        }

    if tension_nature is None or tension_level is None:
        return {
            "show_in_article": False,
            "show_in_chat": False,
            "show_in_homepage": False,
            "requires_review": True,
        }

    return _FULL_DIFFUSION_TABLE.get(
        (tension_nature, tension_level),
        {"show_in_article": True, "show_in_chat": False, "show_in_homepage": False, "requires_review": False},
    )


# Table P1 — (tension_nature, tension_level) → (show_in_article, show_in_chat)
_DIFFUSION_TABLE: dict[Tuple[str, str], Tuple[bool, bool]] = {
    ("value_conflict", "hard"): (True, True),
    ("value_conflict", "soft"): (True, False),
    ("value_conflict", "unknown"): (True, False),
    ("scope_conflict", "hard"): (True, True),
    ("scope_conflict", "soft"): (False, False),
    ("scope_conflict", "unknown"): (True, False),
    ("temporal_conflict", "hard"): (True, False),
    ("temporal_conflict", "soft"): (True, False),
    ("temporal_conflict", "unknown"): (True, False),
    ("methodological", "hard"): (False, False),
    ("methodological", "soft"): (False, False),
    ("methodological", "unknown"): (False, False),
    ("complementary", "hard"): (True, False),
    ("complementary", "soft"): (True, False),
    ("complementary", "unknown"): (True, False),
    ("unknown", "hard"): (False, False),
    ("unknown", "soft"): (False, False),
    ("unknown", "unknown"): (False, False),
}

# Table P1 complète — pour la persistance Neo4j
_FULL_DIFFUSION_TABLE: dict[Tuple[str, str], dict] = {
    ("value_conflict", "hard"): {
        "show_in_article": True, "show_in_chat": True,
        "show_in_homepage": True, "requires_review": False,
    },
    ("value_conflict", "soft"): {
        "show_in_article": True, "show_in_chat": False,
        "show_in_homepage": False, "requires_review": False,
    },
    ("scope_conflict", "hard"): {
        "show_in_article": True, "show_in_chat": True,
        "show_in_homepage": False, "requires_review": False,
    },
    ("scope_conflict", "soft"): {
        "show_in_article": False, "show_in_chat": False,
        "show_in_homepage": True, "requires_review": False,
    },
    ("temporal_conflict", "hard"): {
        "show_in_article": True, "show_in_chat": False,
        "show_in_homepage": False, "requires_review": False,
    },
    ("temporal_conflict", "soft"): {
        "show_in_article": True, "show_in_chat": False,
        "show_in_homepage": False, "requires_review": False,
    },
    ("methodological", "hard"): {
        "show_in_article": False, "show_in_chat": False,
        "show_in_homepage": True, "requires_review": False,
    },
    ("methodological", "soft"): {
        "show_in_article": False, "show_in_chat": False,
        "show_in_homepage": True, "requires_review": False,
    },
    ("complementary", "hard"): {
        "show_in_article": True, "show_in_chat": False,
        "show_in_homepage": False, "requires_review": False,
    },
    ("complementary", "soft"): {
        "show_in_article": True, "show_in_chat": False,
        "show_in_homepage": False, "requires_review": False,
    },
    ("unknown", "hard"): {
        "show_in_article": False, "show_in_chat": False,
        "show_in_homepage": False, "requires_review": True,
    },
    ("unknown", "soft"): {
        "show_in_article": False, "show_in_chat": False,
        "show_in_homepage": False, "requires_review": True,
    },
    ("unknown", "unknown"): {
        "show_in_article": False, "show_in_chat": False,
        "show_in_homepage": False, "requires_review": True,
    },
}
