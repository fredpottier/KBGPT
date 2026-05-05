"""
Lifecycle Filter — CH-37 C.1.

Filtre sémantique qui démote les claims issus de docs DEPRECATED quand la
question demande un état COURANT (sans date passée explicite).

Pourquoi ? Sur des cas comme "Le règlement 428/2009 est-il toujours en vigueur ?",
la réponse correcte est "non, abrogé par 2021/821". Mais sans ce filtre, le
pipeline peut citer 428/2009 comme s'il était actif → bug régulatoire critique.

Stratégie :
1. Détecter "current intent" dans la question (heuristique multilingue)
2. Pour chaque claim, fetcher le lifecycle_status du doc_id (Neo4j cache)
3. Si current intent ET claim DEPRECATED → demote score
4. Resort

Domain-agnostic — pas de vocabulaire métier.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

LIFECYCLE_FILTER_ENABLED = os.getenv("RUNTIME_V2_LIFECYCLE_FILTER", "true").lower() == "true"
DEPRECATED_DEMOTE_FACTOR = float(os.getenv("RUNTIME_V2_DEPRECATED_DEMOTE", "0.3"))


# Heuristique multilingue (FR/EN/DE/ES/IT) : détecte une question demandant l'état courant
# Domain-agnostic — applicable à toute industrie (regulatory, software, medical, legal, retail).
_CURRENT_INTENT_MARKERS_FR = [
    "actuel", "actuellement", "aujourd hui", "ajourd hui",
    "en vigueur", "applicable", "en cours",
    "courant", "présent", "présente", "actuelles",
    "à ce jour", "en ce moment", "en effet",
    "la version actuelle", "la régulation actuelle",
    "toujours en vigueur", "valide", "à jour",
    "dernière version", "dernière édition",
]
_CURRENT_INTENT_MARKERS_EN = [
    "current", "currently", "today", "now",
    "in force", "in effect", "active",
    "applicable", "ongoing", "still in",
    "at present", "presently",
    "the current", "valid today", "up to date",
    "latest version", "latest edition", "still valid",
]
_CURRENT_INTENT_MARKERS_DE = [
    "aktuell", "derzeit", "heute", "jetzt",
    "in kraft", "anwendbar", "gültig",
    "aktuelle version", "neueste version",
]
_CURRENT_INTENT_MARKERS_ES = [
    "actual", "actualmente", "hoy", "ahora",
    "en vigor", "vigente", "aplicable",
    "versión actual", "última versión",
]
_CURRENT_INTENT_MARKERS_IT = [
    "attuale", "attualmente", "oggi",
    "in vigore", "applicabile",
    "versione attuale", "ultima versione",
]

_MONTHS_REGEX = (
    r"(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember|"
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|"
    r"gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)"
)
_PAST_DATE_PATTERN = re.compile(
    rf"\b(?:"
    r"en\s+\d{4}|in\s+\d{4}|"                           # en 2020, in 2020
    r"avant\s+\d{4}|before\s+\d{4}|"                    # avant 2020
    rf"(?:\d{{1,2}}(?:er|e)?\s+)?{_MONTHS_REGEX}\s+\d{{4}}|"  # mars 2020, 1er janvier 2022
    r"\d{1,2}/\d{1,2}/\d{4}|"                            # 01/01/2022
    r"depuis\s+\d{4}|since\s+\d{4}"                      # depuis 2009
    r")\b",
    re.IGNORECASE,
)

_PAST_TENSE_MARKERS = [
    # FR
    "était", "étaient", "fut", "furent",
    # EN
    "was", "were", "had",
    # DE
    "war", "waren",
    # ES
    "estaba", "estaban", "fue", "fueron",
    # IT
    "era", "erano", "fu", "furono",
]


def has_current_intent(question: str) -> bool:
    """Détecte si la question concerne l'état courant (sans date passée)."""
    if not question:
        return False
    # Normalise apostrophes pour catcher "aujourd'hui" / "aujourd hui"
    ql = question.lower().replace("'", " ")
    # Past tense + date → past intent (ex: "était en vigueur en 2022")
    has_past_tense = any(t in ql for t in _PAST_TENSE_MARKERS)
    has_past_date = bool(_PAST_DATE_PATTERN.search(question))
    if has_past_tense or has_past_date:
        # Si on a un marqueur past (tense OR date) → pas current intent
        return False
    # Chercher un marqueur present (toutes langues)
    all_markers = (
        _CURRENT_INTENT_MARKERS_FR + _CURRENT_INTENT_MARKERS_EN
        + _CURRENT_INTENT_MARKERS_DE + _CURRENT_INTENT_MARKERS_ES
        + _CURRENT_INTENT_MARKERS_IT
    )
    for m in all_markers:
        if m in ql:
            return True
    return False


_lifecycle_cache: dict[str, str] = {}


def fetch_lifecycle_statuses(doc_ids: list[str], driver, tenant_id: str = "default") -> dict[str, str]:
    """Charge les lifecycle_status pour une liste de doc_ids depuis Neo4j (cache local).

    Returns: dict doc_id → lifecycle_status (ACTIVE | DEPRECATED | UNKNOWN).
    """
    out = {}
    missing = []
    for did in doc_ids:
        if did in _lifecycle_cache:
            out[did] = _lifecycle_cache[did]
        else:
            missing.append(did)
    if missing:
        try:
            with driver.session() as session:
                rows = session.run(
                    """
                    MATCH (dc:DocumentContext)
                    WHERE dc.tenant_id = $tenant_id AND dc.doc_id IN $doc_ids
                    RETURN dc.doc_id AS doc_id, coalesce(dc.lifecycle_status, 'UNKNOWN') AS status
                    """,
                    tenant_id=tenant_id,
                    doc_ids=missing,
                ).data()
            for r in rows:
                _lifecycle_cache[r["doc_id"]] = r["status"]
                out[r["doc_id"]] = r["status"]
            # Pour les doc_ids non trouvés (pas dans Neo4j) : default UNKNOWN
            for did in missing:
                if did not in out:
                    _lifecycle_cache[did] = "UNKNOWN"
                    out[did] = "UNKNOWN"
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LIFECYCLE_FILTER] Neo4j fetch failed: %s", exc)
            for did in missing:
                out[did] = "UNKNOWN"
    return out


def apply_lifecycle_filter(
    question: str,
    claims: list[Any],
    driver,
    tenant_id: str = "default",
) -> dict:
    """Applique le filtre lifecycle si current intent détecté.

    Modifie les scores des claims DEPRECATED en les multipliant par DEPRECATED_DEMOTE_FACTOR
    et re-sort la liste. Garde les claims (ne les supprime pas) — la synthèse peut
    encore les utiliser pour expliquer "X est abrogé".

    Returns:
        {
          "applied": bool,
          "current_intent": bool,
          "n_deprecated_demoted": int,
          "claims": <re-sorted list>,
          "lifecycle_map": {doc_id: status},
        }
    """
    result = {
        "applied": False,
        "current_intent": False,
        "n_deprecated_demoted": 0,
        "claims": claims,
        "lifecycle_map": {},
    }

    if not LIFECYCLE_FILTER_ENABLED or not claims:
        return result

    current_intent = has_current_intent(question)
    result["current_intent"] = current_intent

    if not current_intent:
        return result

    doc_ids = list({getattr(c, "doc_id", None) or (c.get("doc_id") if isinstance(c, dict) else None) for c in claims})
    doc_ids = [d for d in doc_ids if d]
    lifecycle_map = fetch_lifecycle_statuses(doc_ids, driver, tenant_id)
    result["lifecycle_map"] = lifecycle_map

    n_demoted = 0
    for c in claims:
        did = getattr(c, "doc_id", None) or (c.get("doc_id") if isinstance(c, dict) else None)
        status = lifecycle_map.get(did or "", "UNKNOWN")
        if status == "DEPRECATED":
            # Demote score
            current_score = getattr(c, "score", None)
            if current_score is None and isinstance(c, dict):
                current_score = c.get("score", 0.5)
            new_score = (current_score or 0.5) * DEPRECATED_DEMOTE_FACTOR
            # Set back
            if hasattr(c, "score"):
                try:
                    c.score = new_score
                except Exception:
                    pass
            elif isinstance(c, dict):
                c["score"] = new_score
            n_demoted += 1

    result["n_deprecated_demoted"] = n_demoted
    result["applied"] = n_demoted > 0

    # Re-sort by score desc
    def _key(x):
        s = getattr(x, "score", None)
        if s is None and isinstance(x, dict):
            s = x.get("score", 0)
        return -(s or 0)
    sorted_claims = sorted(claims, key=_key)
    result["claims"] = sorted_claims

    if n_demoted > 0:
        logger.info(
            "[LIFECYCLE_FILTER] current_intent=true, demoted %d/%d DEPRECATED claims (factor=%.2f)",
            n_demoted, len(claims), DEPRECATED_DEMOTE_FACTOR,
        )

    return result
