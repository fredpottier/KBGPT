"""V5.1 Domain Pack loader (lightweight, sans dépendance V2 PackRegistry/sidecar).

Lit directement `context_defaults.json` du pack via env V5_DEFAULT_DOMAIN_PACK
(default = 'enterprise_sap'). Cache process-level.

Charte domain-agnostic respectée :
- Mécanisme générique (load JSON, filtre par query) : valide tout domaine
- Le pack lui-même (enterprise_sap, aerospace_compliance, biomedical, ...) est
  tenant-scoped, externe au core
- Filtre : on n'injecte QUE les termes mentionnés dans la query courante
  (évite la pollution du prompt avec 200 acronymes)

Format extrait :
- common_acronyms : dict {ACR → expansion} (200+ pour enterprise_sap)
- canonical_aliases : dict {alias → canonical name}
- key_concepts : list (thèmes high-level du domaine)

Usage runtime :
    relevant = filter_pack_for_query(load_pack(tenant_id), question)
    if relevant:
        prompt += format_glossary(relevant)
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Default pack name (env override)
DEFAULT_PACK_NAME = os.getenv("V5_DEFAULT_DOMAIN_PACK", "enterprise_sap")

# Cache : pack_name → DomainPackData
_PACK_CACHE: dict[str, "DomainPackData"] = {}


@dataclass
class DomainPackData:
    """Snapshot lightweight d'un Domain Pack pour usage prompt runtime."""
    pack_name: str
    domain_summary: str = ""
    common_acronyms: dict[str, str] = field(default_factory=dict)
    canonical_aliases: dict[str, str] = field(default_factory=dict)
    key_concepts: list[str] = field(default_factory=list)


def _pack_path(pack_name: str) -> Path:
    """Trouve le path du context_defaults.json du pack."""
    # Container path d'abord, fallback dev
    candidates = [
        Path("/app/src/knowbase/domain_packs") / pack_name / "context_defaults.json",
        Path(__file__).resolve().parents[2] / "knowbase" / "domain_packs" / pack_name / "context_defaults.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]  # return first even if not exists (load returns None)


def load_pack(pack_name: str = DEFAULT_PACK_NAME) -> Optional[DomainPackData]:
    """Charge le Domain Pack en mémoire (cache). None si introuvable."""
    if pack_name in _PACK_CACHE:
        return _PACK_CACHE[pack_name]
    path = _pack_path(pack_name)
    if not path.exists():
        logger.warning("[domain_pack] pack %s not found at %s", pack_name, path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pack = DomainPackData(
            pack_name=pack_name,
            domain_summary=data.get("domain_summary", "") or "",
            common_acronyms=dict(data.get("common_acronyms", {}) or {}),
            canonical_aliases=dict(data.get("canonical_aliases", {}) or {}),
            key_concepts=list(data.get("key_concepts", []) or []),
        )
        _PACK_CACHE[pack_name] = pack
        logger.info(
            "[domain_pack] loaded %s — %d acronyms, %d aliases, %d concepts",
            pack_name, len(pack.common_acronyms), len(pack.canonical_aliases),
            len(pack.key_concepts),
        )
        return pack
    except Exception as exc:
        logger.warning("[domain_pack] load failed for %s: %s", pack_name, exc)
        return None


# Tokenization avec word boundaries strictes (\b) — capture tokens avec case
# preserved. ALL-CAPS et mixed-case nécessaires pour matcher les acronymes
# techniques comme ABAP, IDoc, S/4HANA, CGSADM, /SAPAPO/OM03.
_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9/_-]*\b")


@dataclass
class PackHints:
    """Hints filtrés pertinents pour la query courante."""
    acronyms: list[tuple[str, str]] = field(default_factory=list)
    aliases: list[tuple[str, str]] = field(default_factory=list)


def _match_acronym_in_query(acro: str, raw_tokens: set[str]) -> bool:
    """Match acronym contre les tokens (case preserved).

    Heuristiques :
    - ALL-CAPS (RFC, EHS, ABAP) : match strict case-sensitive (sinon "le"
      français matcherait "LE" acronyme = bruit massif).
    - Mixed-case (IDoc, SolMan, IS-U, S/4) : match case-insensitive.
    - Très courts (≤2 chars) : exigent ALL-CAPS strict (évite "po"=PO, "is"=IS-U).
    """
    if len(acro) <= 2:
        # Très courts : ALL-CAPS strict obligatoire
        return acro.isupper() and acro in raw_tokens
    if acro.isupper():
        # ALL-CAPS : case-sensitive strict
        return acro in raw_tokens
    # Mixed-case : case-insensitive sur token original
    acro_lower = acro.lower()
    return any(t.lower() == acro_lower for t in raw_tokens)


def _match_alias_in_query(alias: str, query: str) -> bool:
    """Match alias dans la query avec word boundaries (évite po dans 'Pour')."""
    if not alias:
        return False
    # Pattern : alias entouré de word boundaries (ou début/fin de string)
    # Échapper l'alias (contient espaces, /, -, etc.)
    # \b ne marche pas avec / : on utilise lookarounds (?<![a-z0-9]) (?![a-z0-9])
    pattern = re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    return bool(pattern.search(query))


def filter_pack_for_query(pack: DomainPackData, query: str, max_items: int = 12) -> PackHints:
    """Extrait les entrées du pack pertinentes pour la query.

    Filtre strict (anti faux-positifs) :
    - Acronymes courts (≤2) : ALL-CAPS exact obligatoire
    - Acronymes ALL-CAPS (RFC) : case-sensitive
    - Acronymes mixed (IDoc) : case-insensitive
    - Aliases : word boundaries (lookarounds), case-insensitive
    """
    if not pack or not query:
        return PackHints()
    raw_tokens = set(_TOKEN_RE.findall(query))
    if not raw_tokens:
        return PackHints()

    matched_acro: list[tuple[str, str]] = []
    for acro, expansion in pack.common_acronyms.items():
        if _match_acronym_in_query(acro, raw_tokens):
            matched_acro.append((acro, expansion))

    # Set of expansions déjà capturés (évite doublons aliases redondants)
    acro_keys = {a for a, _ in matched_acro}

    matched_aliases: list[tuple[str, str]] = []
    for alias, canonical in pack.canonical_aliases.items():
        # Skip si déjà dans matched_acro (ex: BTP = BTP)
        if alias in acro_keys:
            continue
        if _match_alias_in_query(alias, query):
            matched_aliases.append((alias, canonical))

    # Trier par longueur descendante (les plus spécifiques d'abord)
    matched_acro.sort(key=lambda x: -len(x[0]))
    matched_aliases.sort(key=lambda x: -len(x[0]))

    # Cap chaque catégorie indépendamment
    cap_acro = max(4, max_items - len(matched_aliases))
    cap_alias = max(4, max_items - len(matched_acro))
    return PackHints(
        acronyms=matched_acro[:cap_acro],
        aliases=matched_aliases[:cap_alias],
    )


def format_hints_block(hints: PackHints) -> str:
    """Formate les hints en bloc texte compact pour injection prompt."""
    if not hints.acronyms and not hints.aliases:
        return ""
    lines = []
    if hints.acronyms:
        lines.append("acronyms found in question:")
        for acro, exp in hints.acronyms[:8]:
            lines.append(f"  - {acro} = {exp}")
    if hints.aliases:
        lines.append("known terms found in question:")
        for alias, canonical in hints.aliases[:6]:
            if alias != canonical:
                lines.append(f"  - {alias} → canonical: {canonical}")
    return "\n".join(lines)


def clear_cache() -> None:
    _PACK_CACHE.clear()
