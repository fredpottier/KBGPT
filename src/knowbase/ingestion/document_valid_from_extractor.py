"""DocumentValidFromExtractor — Extraction date de publication d'un document.

ADR_BITEMPOREL_CLAIMS.md §3.2 (Phase A1.3, cascade post-spike A1.0).

Cascade en 4 stratégies, du plus fiable au moins fiable selon les findings du
spike A1.0 (cf doc/ongoing/sessions/A1.0_SPIKE_DOCUMENT_VALID_FROM.md) :

  S2 — Texte page 1 proche d'un keyword sémantique (Published, Effective, ...)
  S3 — Nom de fichier enrichi (year + month_year FR/EN + YYYYMMDD + version)
  S1 — Metadata /CreationDate avec WARNING si batch re-save détecté
  S4 — LLM Qwen2.5-14B AWQ EC2 Burst (evidence-locked, prompt page 1)
  Fallback — ingestion_fallback marker (jamais d'erreur bloquante)

Le S1 est en 3e position (pas 1ère) parce que le spike A1.0 a montré que sur
le corpus SAP, /CreationDate est massivement pourrie par les re-save batch
locaux lors du téléchargement (9/15 PDFs avec date identique).

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
    # English
    "publication date", "release date", "effective date", "version date",
    "document date", "date of issue", "valid from",
    "published", "released", "effective", "approved", "issued",
    # French
    "date de publication", "date de parution", "date d'effet",
    "date d'application", "date du document", "date d'édition",
    "valable à compter", "publié", "en vigueur",
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
    # DD/MM/YYYY
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "slash"),
]


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
            # Hypothèse EU : DD/MM/YYYY (corpus SAP majoritairement FR + EN-UK)
            d, m, y = groups
            datetime(int(y), int(m), int(d))
            return f"{y}-{int(m):02d}-{int(d):02d}"
    except (ValueError, TypeError):
        return None
    return None


def _extract_page1_text(pdf_path: Path) -> Optional[str]:
    """Renvoie le texte de la page 1 lowercased, ou None si erreur."""
    try:
        with fitz.open(str(pdf_path)) as doc:
            if len(doc) == 0:
                return None
            return doc[0].get_text("text").lower()
    except Exception as e:
        logger.warning(f"[OSMOSE:DocValidFrom] page1 extraction failed for {pdf_path.name}: {e}")
        return None


def extract_s2_page1_keyword(pdf_path: Path) -> dict[str, Any]:
    """S2 — Cherche une date dans une fenêtre proche d'un keyword sémantique page 1."""
    result: dict[str, Any] = {"found": False, "value": None, "source": None}
    page_text = _extract_page1_text(pdf_path)
    if not page_text:
        return result

    for kw in DATE_KEYWORDS:
        kw_pos = page_text.find(kw)
        if kw_pos == -1:
            continue
        window = page_text[max(0, kw_pos - 50) : kw_pos + 200]
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


def extract_s3_filename_enriched(pdf_path: Path) -> dict[str, Any]:
    """S3 — Patterns enrichis sur nom de fichier."""
    name = pdf_path.stem
    result: dict[str, Any] = {"found": False, "value": None, "source": None}

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
- Do NOT capture copyright years from boilerplate ("© 2010-2024 SAP SE") unless that
  is the only temporal anchor on the page
- Do NOT capture random dates from data tables, examples, or unrelated mentions

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


@dataclass
class S4LLMConfig:
    """Configuration appel LLM Qwen2.5-14B AWQ EC2 Burst."""

    vllm_url: str = "http://localhost:8000"
    model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"
    timeout_s: float = 30.0
    max_chars_input: int = 6000  # ~1500 tokens page 1


def extract_s4_llm(pdf_path: Path, config: S4LLMConfig) -> dict[str, Any]:
    """S4 — Appel LLM evidence-locked, fallback gracieux si vLLM indisponible."""
    result: dict[str, Any] = {"found": False, "value": None, "source": None}
    page_text = _extract_page1_text(pdf_path)
    if not page_text:
        result["error"] = "page1_text_empty"
        return result

    truncated = page_text[: config.max_chars_input]
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
            f"[OSMOSE:DocValidFrom] S4 LLM unavailable for {pdf_path.name}: {e}"
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

    # Validator evidence-locked : quote doit apparaître dans le texte source
    if value and evidence_quote:
        normalized_quote = evidence_quote.lower().strip()
        if normalized_quote not in page_text:
            logger.warning(
                f"[OSMOSE:DocValidFrom] S4 quote not found verbatim for {pdf_path.name}"
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


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class DocumentValidFromExtractor:
    """Cascade S2 > S3 > S1 (avec batch-check) > S4 LLM > Fallback.

    Usage :

        extractor = DocumentValidFromExtractor()

        # Mode single doc (S1 batch-check désactivé)
        result = extractor.extract(pdf_path)

        # Mode batch (S1 batch-check activé sur le dossier)
        extractor.precompute_batch_re_save([pdf1, pdf2, ...])
        for p in pdfs:
            result = extractor.extract(p)
    """

    def __init__(
        self,
        s4_config: Optional[S4LLMConfig] = None,
        enable_s4_llm: bool = True,
    ):
        self.s4_config = s4_config or S4LLMConfig()
        self.enable_s4_llm = enable_s4_llm
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

        # S1 — Metadata avec batch-check (priorité 3)
        s1 = extract_s1_metadata(pdf_path)
        result.strategies_tried["s1_metadata"] = s1
        if s1["found"]:
            if s1["value"] in self._suspect_dates:
                result.warning = f"s1_disqualified_batch_re_save:{s1['value']}"
                # Continue vers S4
            else:
                result.value = s1["value"]
                result.marker_type = MarkerType.EXPLICIT
                result.source = s1["source"]
                return result

        # S4 — LLM Qwen2.5-14B AWQ EC2 Burst (priorité 4, opt-in)
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

        # Fallback ultime — aucun signal trouvé
        result.marker_type = MarkerType.INGESTION_FALLBACK
        return result
