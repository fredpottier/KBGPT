"""DocumentValidFromExtractor — Extraction date de publication d'un document.

ADR_BITEMPOREL_CLAIMS.md §3.2 (Phase A1.3, cascade post-spike A1.0).

Cascade par défaut en 3 stratégies (S1 désactivé — voir décision 19/05/2026
ci-dessous) :

  S2 — Texte page 1 proche d'un keyword sémantique (Published, Effective, ...)
  S3 — Nom de fichier enrichi (year + month_year FR/EN + YYYYMMDD + version)
  S4 — LLM (evidence-locked, prompt page 1)
  Fallback — valid_from=null + marker=ingestion_fallback (préférable à une date inventée)

DÉCISION 19/05/2026 — S1 désactivé par défaut. La metadata /CreationDate
d'un PDF n'est PAS un signal de date de publication fiable :
  - Un fichier peut être copié, déplacé, dupliqué, re-saved par un portail à
    chaque téléchargement → la CreationDate reflète l'événement filesystem,
    pas la date intellectuelle du document.
  - Mettre `valid_from = today` quand on download un doc de 2019 induit un
    biais grave : le runtime supposera que le doc n'existait pas hier, ce qui
    fausse classification temporelle / supersession / filtres de fraîcheur.
  - `valid_from=null` (marker=ingestion_fallback) est un signal honnête :
    « date inconnue, à traiter comme non-filtrable temporellement ». Mille
    fois préférable à une date fausse.

S1 reste dans le code (opt-in via `enable_s1_metadata=True`) pour des
contextes maîtrisés où le corpus n'est PAS soumis à re-save (ex : génération
interne de PDFs avec CreationDate fiable). En production OSMOSE par défaut :
off.

Tous les chemins retournent un DocumentValidFromResult avec marker_type
explicite (utilisé en Phase A2 pour filtrer les claims avec valid_from non
fiable lors de la classification claim-vs-claim).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import fitz  # PyMuPDF
import httpx
import pypdf

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


class MarkerType(str, Enum):
    """Trace l'origine de l'extraction `valid_from` pour Phase A2."""

    EXPLICIT = "explicit"  # S2, S3, S4, ou S1 avec batch_check=OK
    DOCUMENT_INHERITED = "document_inherited"  # Claim hérite de document.valid_from
    INGESTION_FALLBACK = "ingestion_fallback"  # Aucun signal trouvé, fallback ingested_at


@dataclass
class DocumentValidFromResult:
    """Résultat de l'extraction. `value=None` n'est pas une erreur — signifie qu'aucun
    signal n'a été trouvé et que le caller doit utiliser le fallback ingested_at."""

    pdf_name: str
    value: Optional[str] = None  # Date ISO "YYYY-MM-DD" ou None
    marker_type: MarkerType = MarkerType.INGESTION_FALLBACK
    source: Optional[str] = None  # "s2_keyword:published", "s3_month_year", "s1_metadata", "s4_llm"
    strategies_tried: dict[str, Any] = field(default_factory=dict)
    warning: Optional[str] = None  # Ex: "batch_re_save_detected", "s4_llm_unavailable"


# ─────────────────────────────────────────────────────────────────────────────
# S2 — Page 1 avec keyword sémantique (pattern le plus fiable)
# ─────────────────────────────────────────────────────────────────────────────

# Mots-clés multilingues exprimant "date de publication/effet" (sémantique pure,
# pas de filtrage corpus-spécifique). Ordre = priorité.
DATE_KEYWORDS = [
    # English — keywords spécifiques testés EN PREMIER (priorité)
    "publication date", "release date", "effective date", "version date",
    "document date", "date of issue", "valid from",
    "published", "released", "effective", "approved", "issued",
    # French
    "date de publication", "date de parution", "date d'effet",
    "date d'application", "date du document", "date d'édition",
    "valable à compter", "publié", "en vigueur",
    # Cartouche d'en-tête (#457) — « date: » suivi de la date dans les
    # cartouches FAA/officiels (« Date:\n01/19/96 »). Placé en DERNIER pour
    # que les keywords spécifiques ci-dessus l'emportent. Le deux-points
    # restreint au libellé de champ (évite « as of the date », « at the date »).
    "date:", "date :",
]

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}

DATE_PATTERNS_PAGE1 = [
    # ISO YYYY-MM-DD ou YYYY/MM/DD
    (re.compile(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b"), "iso"),
    # DD Month YYYY (EN/FR full month)
    (
        re.compile(
            r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december|"
            r"janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})\b",
            re.IGNORECASE,
        ),
        "long_form",
    ),
    # Month YYYY (EN/FR)
    (
        re.compile(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
            r"janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})\b",
            re.IGNORECASE,
        ),
        "month_year",
    ),
    # D/M/YYYY ou M/D/YYYY (désambiguïsation par plausibilité dans _normalize_match)
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "slash"),
    # M/D/YY ou D/M/YY — format court à 2 chiffres d'année (#457, cartouches US
    # type « 01/19/96 »). Testé APRÈS le format 4 chiffres pour ne pas tronquer
    # une année pleine. Pivot de siècle dans _normalize_match.
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "slash_short"),
]


def _disambiguate_dmy(g1: int, g2: int) -> Optional[tuple[int, int]]:
    """Tranche (jour, mois) depuis deux composants ambigus par plausibilité.

    Retourne (day, month) ou None si impossible. Règle :
      - un composant > 12 ne peut être qu'un jour → l'autre est le mois ;
      - sinon (les deux ≤ 12) le format slash reste ambigu : on retient
        l'interprétation US M/D (g1=mois) car le format slash à année courte
        est très majoritairement nord-américain dans les cartouches officiels.
    """
    if g1 > 12 and g2 <= 12:
        return g1, g2  # D/M
    if g2 > 12 and g1 <= 12:
        return g2, g1  # M/D
    if g1 > 12 and g2 > 12:
        return None
    return g2, g1  # ambigu → US M/D (day=g2, month=g1)


def _normalize_match(pattern_type: str, groups: tuple[str, ...]) -> Optional[str]:
    """Convertit un match regex en ISO YYYY-MM-DD."""
    try:
        if pattern_type == "iso":
            y, m, d = groups
            datetime(int(y), int(m), int(d))
            return f"{y}-{int(m):02d}-{int(d):02d}"
        if pattern_type == "long_form":
            d, month_str, y = groups
            m = MONTH_MAP.get(month_str.lower())
            if not m:
                return None
            datetime(int(y), m, int(d))
            return f"{y}-{m:02d}-{int(d):02d}"
        if pattern_type == "month_year":
            month_str, y = groups
            m = MONTH_MAP.get(month_str.lower())
            if not m:
                return None
            return f"{y}-{m:02d}-01"
        if pattern_type == "slash":
            # Désambiguïsation par plausibilité (un composant > 12 = jour) ; à
            # défaut US M/D (cf _disambiguate_dmy). Année déjà sur 4 chiffres.
            g1, g2, y = int(groups[0]), int(groups[1]), int(groups[2])
            dm = _disambiguate_dmy(g1, g2)
            if not dm:
                return None
            d, m = dm
            datetime(y, m, d)
            return f"{y}-{m:02d}-{d:02d}"
        if pattern_type == "slash_short":
            # Format court : pivot de siècle (YY > 30 → 19YY, sinon 20YY — les
            # cartouches réglementaires sont passés/présent, jamais futur lointain).
            g1, g2, yy = int(groups[0]), int(groups[1]), int(groups[2])
            y = 1900 + yy if yy > 30 else 2000 + yy
            dm = _disambiguate_dmy(g1, g2)
            if not dm:
                return None
            d, m = dm
            datetime(y, m, d)
            return f"{y}-{m:02d}-{d:02d}"
    except (ValueError, TypeError):
        return None
    return None


def _extract_page1_text(pdf_path: Path) -> Optional[str]:
    """Lit la page 1 d'un PDF (lowercased), ou None si erreur. Wrapper PDF."""
    try:
        with fitz.open(str(pdf_path)) as doc:
            if len(doc) == 0:
                return None
            return doc[0].get_text("text").lower()
    except Exception as e:
        logger.warning(f"[OSMOSE:DocValidFrom] page1 extraction failed for {pdf_path.name}: {e}")
        return None


# Markers techniques injectés par l'extracteur Docling/V2 dans le full_text du cache.
# On les retire avant de chercher des dates car ils polluent les fenêtres autour des keywords.
_STRUCTURE_MARKERS_RE = re.compile(
    r"\[(?:PAGE|PARAGRAPH|SECTION|HEADER|TABLE|LIST|TITLE|FOOTER)[^]]*\]",
    re.IGNORECASE,
)


def _clean_structure_markers(text: str) -> str:
    """Retire les markers `[PAGE 0]`, `[PARAGRAPH]` etc. introduits par l'extracteur V2.
    Domain-agnostic : suppression de tokens techniques de structure, pas de domaine."""
    return _STRUCTURE_MARKERS_RE.sub(" ", text)


def _extract_s2_core(page1_text_lower: str) -> dict[str, Any]:
    """S2 — Logique pure sur texte page 1 lowercased (sans markers structure).

    Indépendant de la source (PDF binaire OU cache JSON).
    """
    result: dict[str, Any] = {"found": False, "value": None, "source": None}
    if not page1_text_lower:
        return result

    for kw in DATE_KEYWORDS:
        kw_pos = page1_text_lower.find(kw)
        if kw_pos == -1:
            continue
        window = page1_text_lower[max(0, kw_pos - 50) : kw_pos + 200]
        for pattern, ptype in DATE_PATTERNS_PAGE1:
            m = pattern.search(window)
            if not m:
                continue
            value = _normalize_match(ptype, m.groups())
            if value:
                result.update(
                    {
                        "found": True,
                        "value": value,
                        "source": f"s2_keyword:{kw}",
                        "pattern": ptype,
                    }
                )
                return result
    return result


def extract_s2_page1_keyword(pdf_path: Path) -> dict[str, Any]:
    """S2 — Wrapper PDF : lit page 1 puis délègue à `_extract_s2_core`."""
    page_text = _extract_page1_text(pdf_path)
    if not page_text:
        return {"found": False, "value": None, "source": None}
    return _extract_s2_core(_clean_structure_markers(page_text))


# ─────────────────────────────────────────────────────────────────────────────
# S3 — Nom de fichier enrichi
# ─────────────────────────────────────────────────────────────────────────────

# Année 4 chiffres seule, isolée
_FILENAME_YEAR = re.compile(r"(?<![\d/-])(20\d{2})(?![\d/-])")
# Mois (EN/FR) + année (`_may_2025_`, `_juin_2024_`, `_June 2025_`)
_FILENAME_MONTH_YEAR = re.compile(
    r"(?:^|[_\-\s])("
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre"
    r")[_\-\s]+(20\d{2})(?:[_\-\s]|$)",
    re.IGNORECASE,
)
# YYYYMMDD compact (ex: `20251010`)
_FILENAME_YYYYMMDD = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
# Version + année (ex: `v04-2026` → 2026-04-01)
_FILENAME_VERSION_DATE = re.compile(r"v\.?(\d{1,2})[-_](20\d{2})", re.IGNORECASE)


def _extract_s3_core(name: str) -> dict[str, Any]:
    """S3 — Logique pure sur stem de filename (sans extension).

    Indépendant de la source (PDF binaire OU cache JSON).
    """
    result: dict[str, Any] = {"found": False, "value": None, "source": None}
    if not name:
        return result

    # 1. Pattern YYYYMMDD compact (le plus précis)
    m = _FILENAME_YYYYMMDD.search(name)
    if m:
        y, mo, d = m.groups()
        try:
            datetime(int(y), int(mo), int(d))
            result.update({"found": True, "value": f"{y}-{mo}-{d}", "source": "s3_yyyymmdd"})
            return result
        except (ValueError, TypeError):
            pass

    # 2. Version + année (ex: v04-2026 → 2026-04-01)
    m = _FILENAME_VERSION_DATE.search(name)
    if m:
        version_num, y = m.groups()
        try:
            month = int(version_num)
            if 1 <= month <= 12:
                datetime(int(y), month, 1)
                result.update(
                    {
                        "found": True,
                        "value": f"{y}-{month:02d}-01",
                        "source": "s3_version_date",
                    }
                )
                return result
        except (ValueError, TypeError):
            pass

    # 3. Mois + année (ex: `_may_2025_`)
    m = _FILENAME_MONTH_YEAR.search(name)
    if m:
        month_str, y = m.groups()
        month = MONTH_MAP.get(month_str.lower())
        if month:
            result.update(
                {
                    "found": True,
                    "value": f"{y}-{month:02d}-01",
                    "source": "s3_month_year",
                }
            )
            return result

    # 4. Année seule (le moins précis : YYYY-01-01)
    years = _FILENAME_YEAR.findall(name)
    if years:
        # Dernière occurrence (souvent la plus récente/pertinente)
        y = years[-1]
        result.update({"found": True, "value": f"{y}-01-01", "source": "s3_year_only"})
    return result


def extract_s3_filename_enriched(pdf_path: Path) -> dict[str, Any]:
    """S3 — Wrapper PDF : extrait le stem et délègue à `_extract_s3_core`."""
    return _extract_s3_core(pdf_path.stem)


# ─────────────────────────────────────────────────────────────────────────────
# S1 — Metadata PDF avec détection batch re-save
# ─────────────────────────────────────────────────────────────────────────────


def _parse_pdf_date_string(raw: Optional[str]) -> Optional[str]:
    """Parse "D:20230315120000+00'00'" → "2023-03-15"."""
    if not raw or not isinstance(raw, str):
        return None
    m = re.match(r"^D?:?(\d{4})(\d{2})(\d{2})", raw.strip())
    if not m:
        return None
    y, mo, d = m.groups()
    try:
        datetime(int(y), int(mo), int(d))
        return f"{y}-{mo}-{d}"
    except (ValueError, TypeError):
        return None


def extract_s1_metadata(pdf_path: Path) -> dict[str, Any]:
    """S1 — Extraction /CreationDate ou /ModDate via pypdf."""
    result: dict[str, Any] = {"found": False, "value": None, "source": None, "raw": {}}
    try:
        reader = pypdf.PdfReader(str(pdf_path))
        meta = reader.metadata or {}
        creation = _parse_pdf_date_string(meta.get("/CreationDate"))
        mod = _parse_pdf_date_string(meta.get("/ModDate"))
        result["raw"] = {
            "creation": meta.get("/CreationDate"),
            "mod": meta.get("/ModDate"),
        }
        if creation:
            result.update({"found": True, "value": creation, "source": "s1_creation_date"})
        elif mod:
            result.update({"found": True, "value": mod, "source": "s1_mod_date"})
    except Exception as e:
        result["error"] = str(e)
    return result


def detect_batch_re_save(pdf_paths: list[Path], min_cluster_size: int = 3) -> set[str]:
    """Détecte les /CreationDate suspectes (≥ min_cluster_size docs partageant la même date).

    Retourne l'ensemble des dates ISO suspectes (à exclure de S1).
    """
    by_date: dict[str, list[str]] = {}
    for p in pdf_paths:
        s1 = extract_s1_metadata(p)
        if s1["found"]:
            by_date.setdefault(s1["value"], []).append(p.name)
    suspect = {d for d, pdfs in by_date.items() if len(pdfs) >= min_cluster_size}
    if suspect:
        logger.info(
            f"[OSMOSE:DocValidFrom] batch re-save detected — {len(suspect)} suspect "
            f"dates: {sorted(suspect)}"
        )
    return suspect


# ─────────────────────────────────────────────────────────────────────────────
# S4 — LLM Qwen2.5-14B AWQ via EC2 Burst (evidence-locked extraction)
# ─────────────────────────────────────────────────────────────────────────────

_S4_PROMPT_SYSTEM = """You are a document metadata analyst extracting the document's date.

You receive the FIRST PAGE TEXT of a PDF document (any language, any domain).

Your task: extract the date that best represents WHEN this document was produced,
published, dated, presented, released, issued, effective, or otherwise temporally
anchored. This is the date a librarian would use to file the document.

WHERE TO LOOK:
- Header or footer ("Document Version X.Y, March 2024", "v2.0 — 09/2023")
- Cover page below the title or under the author name (presentation/slide-deck date,
  typical pattern: "Author Name\\nMonth YYYY" or "Author, Org\\nQ3 2025")
- The signature/approval/issue date line
- Any standalone date that visibly anchors the document in time

ACCEPTED FORMATS (non-exhaustive — your job is to recognize date semantics, not
pattern-match a closed list):
- Full dates: "15 March 2024", "March 15, 2024", "15/03/2024", "2024-03-15"
- Month + year: "March 2024", "Mar 2024", "März 2024", "mars 2024"
- Compact: "03/2024", "2024-03", "Q1 2024", "FY24"
- Year only (only as last resort if nothing more precise)

You handle multilingual content (EN/FR/DE/ES/IT/...) and any domain. Trust the
semantic clue more than a specific keyword — a date placed prominently on a cover
slide IS the document date, even without an explicit "Published:" label.

CRITICAL — evidence-locked extraction:
- Extract ONLY a date that is EXPLICITLY written in the page
- Provide an evidence_quote that appears VERBATIM in the input text (case-insensitive
  but otherwise character-exact within the chosen span)
- If no date is visible at all on the page, return value=null
- Do NOT capture copyright year ranges from boilerplate footers (e.g. "© year-year
  [organization]") — they reflect the lifetime of the document family, not a single
  document's date. Only fall back to them if no other temporal anchor exists.
- Do NOT capture random dates from data tables, examples, or unrelated mentions

CRITICAL — distinguish the document's OWN date from dates the document MENTIONS:
The document's date is when this document was authored, published, issued, or
otherwise produced. It is NOT the same as dates the document discusses in its
content. Specifically, the following are NOT the document's date even when
prominent on page 1:
  - Dates describing events, products, contracts, regulations, cases, deadlines,
    or any subject the document is ABOUT
  - End-of-life, end-of-maintenance, sunset, expiry, deprecation dates of
    products, standards, services, agreements, etc. (e.g. "Support ends 2027")
  - Effective/applicable dates of an external object referenced in the document
    (e.g. "Applicable from 2024" describes a regulation, not the document)
  - Birth/death/incident/event dates mentioned in the narrative
  - Validity windows of described items (e.g. "Valid 2022–2025" attached to a
    product or license)
When the page contains ONLY such referenced/described dates (not the document's
own publication date), return value=null. **Returning null is correct and
expected — do NOT pick a referenced date as a fallback.** A false document date
is far worse for downstream consumers than no date at all.

NORMALIZATION (the system normalizes your output to ISO YYYY-MM-DD):
- Year+month → use YYYY-MM (system will set day=01)
- Year only → use YYYY (system will set month=01, day=01)
- Full date → use YYYY-MM-DD
- Quarter → resolve to first month of quarter (Q1=01, Q2=04, Q3=07, Q4=10) at YYYY-MM
- Fiscal year (FY24, FY2024) → use YYYY at January (unless context says otherwise)

Output JSON schema (strict):
{
  "value": "YYYY-MM-DD" | "YYYY-MM" | "YYYY" | null,
  "date_role": "publication" | "effective" | "version" | "issued" | "approved" | "presentation" | "other" | null,
  "evidence_quote": "..." | null,
  "confidence": "high" | "medium" | "low"
}

If `value` is non-null, `evidence_quote` MUST also be non-null and appear verbatim
in the input text."""


def _resolve_burst_vllm_url() -> str:
    """Résout l'URL vLLM via le burst state Redis (single source of truth).

    Le pipeline ClaimFirst route tous ses calls LLM via `LLM_Router.GATE` qui lit
    `osmose:burst:state.vllm_url`. S4 contourne le router (httpx direct → besoin
    de l'URL résolue à l'init). On lit la même source pour rester cohérent : si
    l'EC2 est respawn (nouvelle IP), il suffit de re-instancier S4LLMConfig.

    Fallback `http://localhost:8000` (qui pointera vers le container app — KO en
    pratique mais permet une init non-bloquante en mode dégradé).
    """
    try:
        from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
        state = get_burst_state_from_redis()
        if state and state.get("vllm_url"):
            return state["vllm_url"]
    except Exception as e:
        logger.debug(f"[S4LLMConfig] Burst state unavailable, falling back to localhost: {e}")
    return "http://localhost:8000"


@dataclass
class S4LLMConfig:
    """Configuration appel LLM Qwen2.5-14B AWQ EC2 Burst.

    `vllm_url` est résolu par défaut depuis le burst state Redis pour pointer
    automatiquement vers l'EC2 quand le burst mode est actif. À override manuellement
    pour tester sur localhost ou un autre vLLM.
    """

    vllm_url: str = field(default_factory=_resolve_burst_vllm_url)
    model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"
    timeout_s: float = 30.0
    max_chars_input: int = 6000  # ~1500 tokens page 1


def _extract_s4_core(page1_text: str, config: S4LLMConfig, doc_name: str = "") -> dict[str, Any]:
    """S4 — Logique pure : LLM evidence-locked sur texte page 1 (non lowercased).

    Indépendant de la source (PDF binaire OU cache JSON). `doc_name` est utilisé
    seulement pour les logs (jamais transmis au LLM).
    """
    result: dict[str, Any] = {"found": False, "value": None, "source": None}
    if not page1_text:
        result["error"] = "page1_text_empty"
        return result

    truncated = page1_text[: config.max_chars_input]
    user_msg = f"FIRST PAGE TEXT (truncated to {config.max_chars_input} chars):\n\n{truncated}"

    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": _S4_PROMPT_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }

    try:
        with httpx.Client(timeout=config.timeout_s) as client:
            r = client.post(
                f"{config.vllm_url.rstrip('/')}/v1/chat/completions",
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning(
            f"[OSMOSE:DocValidFrom] S4 LLM unavailable for {doc_name or '<unknown>'}: {e}"
        )
        result["error"] = f"vllm_unavailable: {e!r}"
        result["fallback"] = True
        return result

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        result["error"] = f"parse_error: {e!r}"
        return result

    value = parsed.get("value")
    evidence_quote = parsed.get("evidence_quote")

    # Validator evidence-locked : quote doit apparaître dans le texte source.
    # Comparaison case-insensitive sur texte page 1 lowercased.
    if value and evidence_quote:
        normalized_quote = evidence_quote.lower().strip()
        if normalized_quote not in truncated.lower():
            logger.warning(
                f"[OSMOSE:DocValidFrom] S4 quote not found verbatim for {doc_name or '<unknown>'}"
            )
            result["error"] = "quote_not_verbatim"
            return result

    # Normaliser value en ISO YYYY-MM-DD
    iso_value: Optional[str] = None
    if value:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            iso_value = value
        elif re.match(r"^\d{4}-\d{2}$", value):
            iso_value = f"{value}-01"
        elif re.match(r"^\d{4}$", value):
            iso_value = f"{value}-01-01"

    if iso_value:
        result.update(
            {
                "found": True,
                "value": iso_value,
                "source": "s4_llm",
                "date_role": parsed.get("date_role"),
                "confidence": parsed.get("confidence"),
                "evidence_quote": evidence_quote,
            }
        )
    return result


def extract_s4_llm(pdf_path: Path, config: S4LLMConfig) -> dict[str, Any]:
    """S4 — Wrapper PDF : lit page 1 puis délègue à `_extract_s4_core`."""
    page_text = _extract_page1_text(pdf_path)
    if not page_text:
        return {"found": False, "value": None, "source": None, "error": "page1_text_empty"}
    # _extract_page1_text retourne lowercased — on perd la casse pour S4 (qui veut le raw
    # pour evidence-locked). Conséquence : evidence_quote du LLM sera matchée lowercased
    # (cohérent avec normalized_quote dans le validator).
    return _extract_s4_core(page_text, config, doc_name=pdf_path.name)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers cache JSON — extraction page 1 + filename depuis le cache `.v5cache.json`
# ─────────────────────────────────────────────────────────────────────────────


def _page1_text_from_cache(cache_data: dict[str, Any]) -> Optional[str]:
    """Extrait le texte de la page 1 depuis le cache `.v5cache.json`.

    Le cache stocke `extraction.full_text` avec markers `[PAGE 0]`, `[PAGE 1]`, etc.
    et `extraction.page_index` avec les offsets. On isole la page 0 (= 1ère page humaine)
    via le 1er entry de `page_index`, puis on retire les markers structure.
    """
    extr = cache_data.get("extraction", {})
    full_text = extr.get("full_text", "")
    page_index = extr.get("page_index", [])

    if not full_text or not page_index:
        return None

    first_page = page_index[0] if isinstance(page_index, list) else None
    if not isinstance(first_page, dict):
        return None

    start = first_page.get("start_offset", 0)
    end = first_page.get("end_offset")
    if end is None or end <= start:
        return None

    page1_raw = full_text[start:end]
    return _clean_structure_markers(page1_raw)


def _filename_stem_from_cache(cache_data: dict[str, Any]) -> Optional[str]:
    """Extrait le stem du filename original depuis `extraction.source_path`."""
    extr = cache_data.get("extraction", {})
    source_path = extr.get("source_path", "")
    if not source_path:
        return None
    return Path(source_path).stem


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class DocumentValidFromExtractor:
    """Cascade par défaut : S2 → S3 → S4 LLM → Fallback NULL.

    S1 (PDF /CreationDate metadata) est désactivé par défaut depuis 2026-05-19
    (cf module docstring). Si opt-in via `enable_s1_metadata=True`, S1 est
    positionné en *last resort* (après S4) et marque toujours
    `warning="s1_low_reliability_metadata"` sur le résultat.

    Le fallback final retourne `value=None` (marker=ingestion_fallback) plutôt
    qu'une date arbitraire — voir ADR_BITEMPOREL_CLAIMS.md §9.3.

    Usage :

        extractor = DocumentValidFromExtractor()

        # Mode single doc (S1 désactivé même si enable_s1_metadata=True car batch_check off)
        result = extractor.extract(pdf_path)

        # Mode batch (batch_check S1 utile UNIQUEMENT si enable_s1_metadata=True)
        extractor = DocumentValidFromExtractor(enable_s1_metadata=True)
        extractor.precompute_batch_re_save([pdf1, pdf2, ...])
        for p in pdfs:
            result = extractor.extract(p)
    """

    def __init__(
        self,
        s4_config: Optional[S4LLMConfig] = None,
        enable_s4_llm: bool = True,
        enable_s1_metadata: bool = False,
    ):
        """
        Args:
            s4_config: configuration pour S4 LLM (vLLM URL, model, timeout).
            enable_s4_llm: active S4 (LLM evidence-locked sur page 1). Recommandé.
            enable_s1_metadata: active S1 (PDF /CreationDate). **OFF par défaut**.
                S1 utilise la metadata `/CreationDate` du PDF qui n'est pas fiable
                (re-save batch, copie, re-générée par portail). Voir module docstring
                pour le raisonnement complet. À activer uniquement sur un corpus
                maîtrisé (génération interne).
        """
        self.s4_config = s4_config or S4LLMConfig()
        self.enable_s4_llm = enable_s4_llm
        self.enable_s1_metadata = enable_s1_metadata
        self._suspect_dates: set[str] = set()

    def precompute_batch_re_save(self, pdf_paths: list[Path]) -> set[str]:
        """À appeler une fois avant `extract()` en mode batch ingestion."""
        self._suspect_dates = detect_batch_re_save(pdf_paths)
        return self._suspect_dates

    def extract(self, pdf_path: Path) -> DocumentValidFromResult:
        """Cascade complète, retourne DocumentValidFromResult."""
        result = DocumentValidFromResult(pdf_name=pdf_path.name)

        # S2 — Page 1 keyword (priorité 1)
        s2 = extract_s2_page1_keyword(pdf_path)
        result.strategies_tried["s2_page1_keyword"] = s2
        if s2["found"]:
            result.value = s2["value"]
            result.marker_type = MarkerType.EXPLICIT
            result.source = s2["source"]
            return result

        # S3 — Filename enriched (priorité 2)
        s3 = extract_s3_filename_enriched(pdf_path)
        result.strategies_tried["s3_filename"] = s3
        if s3["found"]:
            result.value = s3["value"]
            result.marker_type = MarkerType.EXPLICIT
            result.source = s3["source"]
            return result

        # S4 — LLM (priorité 3, evidence-locked sur le contenu page 1).
        # S4 lit le texte réel du document, donc la date qu'il trouve correspond à
        # ce que le document affiche explicitement. Si la page 1 ne contient pas
        # de date de publication explicite, S4 retourne None — c'est le bon
        # comportement (préférable à inventer une date).
        if self.enable_s4_llm:
            s4 = extract_s4_llm(pdf_path, self.s4_config)
            result.strategies_tried["s4_llm"] = s4
            if s4.get("fallback"):
                result.warning = (
                    result.warning + ";" if result.warning else ""
                ) + "s4_llm_unavailable"
            elif s4["found"]:
                result.value = s4["value"]
                result.marker_type = MarkerType.EXPLICIT
                result.source = s4["source"]
                return result

        # S1 — Metadata /CreationDate (LAST RESORT, OPT-IN UNIQUEMENT — décision 19/05/2026).
        # Volatile (copie, re-save batch, re-génération portail) → ne reflète pas la date
        # intellectuelle du document. Désactivé par défaut. Si l'opérateur a explicitement
        # opt-in `enable_s1_metadata=True` (corpus maîtrisé), S1 ne tranche qu'après
        # échec de S2/S3/S4, avec un warning systématique sur la fiabilité.
        if self.enable_s1_metadata:
            s1 = extract_s1_metadata(pdf_path)
            result.strategies_tried["s1_metadata"] = s1
            if s1["found"]:
                if s1["value"] in self._suspect_dates:
                    result.warning = (
                        result.warning + ";" if result.warning else ""
                    ) + f"s1_disqualified_batch_re_save:{s1['value']}"
                else:
                    result.value = s1["value"]
                    result.marker_type = MarkerType.EXPLICIT
                    result.source = s1["source"]
                    result.warning = (
                        result.warning + ";" if result.warning else ""
                    ) + "s1_low_reliability_metadata"
                    return result

        # Fallback ultime — aucun signal fiable trouvé. valid_from=null est intentionnel :
        # mieux que mettre une fausse date qui fausserait le runtime temporel.
        result.marker_type = MarkerType.INGESTION_FALLBACK
        return result

    def extract_from_cache(self, cache_data: dict[str, Any]) -> DocumentValidFromResult:
        """Cascade S2 → S3 → S4 → fallback NULL en partant d'un cache `.v5cache.json`.

        Le cache contient déjà tout ce dont la cascade a besoin :
          - `extraction.full_text` + `extraction.page_index` → texte page 1
          - `extraction.source_path` → filename original (basename)

        S1 (PDF metadata) est par construction impossible depuis le cache car nécessite
        le binaire PDF. Ce n'est pas une régression : S1 est désactivé par défaut (§9.2).

        Permet la (ré)ingestion ClaimFirst depuis le seul cache, sans accès au PDF original.
        Cohérent avec l'architecture cible « cache self-sufficient » (décision Fred 2026-05-20).
        """
        pdf_name = Path(cache_data.get("extraction", {}).get("source_path", "<from-cache>")).name
        result = DocumentValidFromResult(pdf_name=pdf_name)

        page1_text = _page1_text_from_cache(cache_data)
        filename_stem = _filename_stem_from_cache(cache_data)

        # S2 — Page 1 keyword
        if page1_text:
            s2 = _extract_s2_core(page1_text.lower())
            result.strategies_tried["s2_page1_keyword"] = s2
            if s2["found"]:
                result.value = s2["value"]
                result.marker_type = MarkerType.EXPLICIT
                result.source = s2["source"]
                return result

        # S3 — Filename enriched
        if filename_stem:
            s3 = _extract_s3_core(filename_stem)
            result.strategies_tried["s3_filename"] = s3
            if s3["found"]:
                result.value = s3["value"]
                result.marker_type = MarkerType.EXPLICIT
                result.source = s3["source"]
                return result

        # S4 — LLM evidence-locked
        if self.enable_s4_llm and page1_text:
            s4 = _extract_s4_core(page1_text, self.s4_config, doc_name=pdf_name)
            result.strategies_tried["s4_llm"] = s4
            if s4.get("fallback"):
                result.warning = (
                    result.warning + ";" if result.warning else ""
                ) + "s4_llm_unavailable"
            elif s4["found"]:
                result.value = s4["value"]
                result.marker_type = MarkerType.EXPLICIT
                result.source = s4["source"]
                return result

        # S1 impossible depuis le cache : on saute (warning informatif si opt-in tenté)
        if self.enable_s1_metadata:
            result.warning = (
                result.warning + ";" if result.warning else ""
            ) + "s1_skipped_no_pdf_in_cache"

        # Fallback NULL — signal honnête, conforme §9.1/§9.3
        result.marker_type = MarkerType.INGESTION_FALLBACK
        return result
