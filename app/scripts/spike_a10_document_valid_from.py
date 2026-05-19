"""Spike A1.0 — Extraction `document_valid_from` sur PDFs SAP représentatifs.

ADR_BITEMPOREL_CLAIMS.md §4.3 + §6.1 — Mitigation risque "taux extraction faible".

Teste 3 stratégies en cascade pour extraire la date d'effet/publication d'un document :

  S1 — Metadata PDF (/CreationDate, /ModDate via pypdf)
  S2 — Texte page 1 (regex multilingue FR/EN + mots-clés "Published", "Effective", etc.)
  S3 — Nom de fichier (regex année 4 chiffres ou version `_vX.Y_`)

Stocke résultats détaillés dans data/spike_a10_results.json.

Gate : taux extraction ≥80% → stratégie validée pour A1.3.
       Sinon : revoir stratégie (LLM fallback, regex enrichi).

Usage :
    docker exec knowbase-app python /app/scripts/spike_a10_document_valid_from.py \\
        --corpus-dir data/docs_done \\
        --output data/spike_a10_results.json
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import pypdf

logger = logging.getLogger("spike_a10")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ─────────────────────────────────────────────────────────────────────────────
# Stratégie 1 — Metadata PDF
# ─────────────────────────────────────────────────────────────────────────────

def parse_pdf_date_string(raw: str | None) -> str | None:
    """Parse "D:20230315120000+00'00'" ou "D:20230315120000Z" → "2023-03-15".

    Retourne ISO date string ou None si invalide.
    """
    if not raw or not isinstance(raw, str):
        return None
    m = re.match(r"^D?:?(\d{4})(\d{2})(\d{2})", raw.strip())
    if not m:
        return None
    year, month, day = m.group(1), m.group(2), m.group(3)
    try:
        # Valider la date (ex: pas de mois 13)
        datetime(int(year), int(month), int(day))
        return f"{year}-{month}-{day}"
    except (ValueError, TypeError):
        return None


def extract_from_metadata(pdf_path: Path) -> dict[str, Any]:
    """S1 : extraction depuis metadata PDF.

    Returns:
        {"found": bool, "value": str|None, "source": "creation_date|mod_date|None", "raw": dict}
    """
    result = {"found": False, "value": None, "source": None, "raw": {}}
    try:
        reader = pypdf.PdfReader(str(pdf_path))
        meta = reader.metadata or {}
        creation = parse_pdf_date_string(meta.get("/CreationDate"))
        mod = parse_pdf_date_string(meta.get("/ModDate"))
        result["raw"] = {"creation": meta.get("/CreationDate"), "mod": meta.get("/ModDate")}
        # Préférer CreationDate (date d'origine du document)
        if creation:
            result.update({"found": True, "value": creation, "source": "creation_date"})
        elif mod:
            result.update({"found": True, "value": mod, "source": "mod_date"})
    except Exception as e:
        result["error"] = str(e)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Stratégie 2 — Texte page 1
# ─────────────────────────────────────────────────────────────────────────────

# Mots-clés multilingues (sémantique = "date de publication/effet")
DATE_KEYWORDS = [
    # English
    "published", "publication date", "release date", "released",
    "effective", "effective date", "valid from", "version date",
    "document date", "date of issue", "issued", "approved",
    # French
    "publié", "date de publication", "date de parution",
    "date d'effet", "date d'application", "valable à compter",
    "date du document", "date d'édition",
]

# Patterns dates (ordre = priorité)
DATE_PATTERNS = [
    # ISO YYYY-MM-DD ou YYYY/MM/DD
    (r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b", "iso"),
    # DD Month YYYY (EN/FR full month)
    (
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})\b",
        "long_form",
    ),
    # Month YYYY (EN) — ex: "March 2023"
    (
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})\b",
        "month_year",
    ),
    # DD/MM/YYYY ou MM/DD/YYYY
    (r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", "slash"),
]

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}


def normalize_match(pattern_type: str, groups: tuple[str, ...]) -> str | None:
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
            return f"{y}-{m:02d}-01"  # Jour par défaut = 1
        if pattern_type == "slash":
            # Ambigu DD/MM vs MM/DD : on prend DD/MM (norme EU + France SAP)
            d, m, y = groups
            datetime(int(y), int(m), int(d))
            return f"{y}-{int(m):02d}-{int(d):02d}"
    except (ValueError, TypeError):
        return None
    return None


def extract_from_first_page(pdf_path: Path) -> dict[str, Any]:
    """S2 : extraction depuis texte page 1.

    Cherche d'abord les patterns dates **proches** d'un keyword (window ±100 chars).
    Sinon fallback sur première date trouvée dans la page.
    """
    result = {"found": False, "value": None, "source": None, "keyword_near": None}
    try:
        doc = fitz.open(str(pdf_path))
        if len(doc) == 0:
            return result
        page1_text = doc[0].get_text("text").lower()
        doc.close()

        # 1. Chercher dates proches d'un keyword
        for kw in DATE_KEYWORDS:
            kw_pos = page1_text.find(kw)
            if kw_pos == -1:
                continue
            window = page1_text[max(0, kw_pos - 50):kw_pos + 200]
            for pattern, ptype in DATE_PATTERNS:
                m = re.search(pattern, window)
                if m:
                    value = normalize_match(ptype, m.groups())
                    if value:
                        result.update({
                            "found": True, "value": value,
                            "source": f"page1_near_keyword:{kw}",
                            "keyword_near": kw,
                            "pattern": ptype,
                        })
                        return result

        # 2. Fallback : première date trouvée dans la page (sans keyword)
        for pattern, ptype in DATE_PATTERNS:
            m = re.search(pattern, page1_text)
            if m:
                value = normalize_match(ptype, m.groups())
                if value:
                    result.update({
                        "found": True, "value": value,
                        "source": f"page1_first_date:{ptype}",
                        "pattern": ptype,
                    })
                    return result
    except Exception as e:
        result["error"] = str(e)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Stratégie 3 — Nom de fichier
# ─────────────────────────────────────────────────────────────────────────────

FILENAME_YEAR_PATTERN = re.compile(r"(?<![\d/-])(20\d{2})(?![\d/-])")
FILENAME_VERSION_PATTERN = re.compile(r"_v?(\d+)\.(\d+)([_-]|$)", re.IGNORECASE)


def extract_from_filename(pdf_path: Path) -> dict[str, Any]:
    """S3 : extraction depuis nom de fichier (année 4 chiffres).

    Year-only → on suppose 1er janvier de cette année.
    """
    result = {"found": False, "value": None, "source": None, "raw_filename": pdf_path.name}
    name = pdf_path.stem
    # Chercher année
    matches = FILENAME_YEAR_PATTERN.findall(name)
    if matches:
        # Prendre la dernière (souvent la plus récente)
        year = matches[-1]
        try:
            datetime(int(year), 1, 1)
            result.update({
                "found": True, "value": f"{year}-01-01",
                "source": "filename_year",
                "year_extracted": year,
            })
        except (ValueError, TypeError):
            pass
    # Version (ex: v04-2026) — pour info, pas de date directe
    v_match = FILENAME_VERSION_PATTERN.search(name)
    if v_match:
        result["version_hint"] = f"v{v_match.group(1)}.{v_match.group(2)}"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Cascade
# ─────────────────────────────────────────────────────────────────────────────

def extract_document_valid_from(pdf_path: Path) -> dict[str, Any]:
    """Cascade S1 → S2 → S3 + agrégation détaillée.

    Returns:
        {
          "pdf": str, "size_mb": float,
          "found": bool, "value": str|None, "source": str|None,
          "strategies": {"s1_metadata": {...}, "s2_page1": {...}, "s3_filename": {...}},
        }
    """
    s1 = extract_from_metadata(pdf_path)
    s2 = extract_from_first_page(pdf_path)
    s3 = extract_from_filename(pdf_path)

    # Cascade priorité : S2 (page 1 avec keyword) > S1 (metadata) > S2 (page 1 sans kw) > S3 (filename)
    final_value, final_source = None, None
    if s2.get("found") and s2.get("keyword_near"):
        final_value, final_source = s2["value"], s2["source"]
    elif s1.get("found"):
        final_value, final_source = s1["value"], s1["source"]
    elif s2.get("found"):
        final_value, final_source = s2["value"], s2["source"]
    elif s3.get("found"):
        final_value, final_source = s3["value"], s3["source"]

    return {
        "pdf": pdf_path.name,
        "size_mb": round(pdf_path.stat().st_size / 1_000_000, 2),
        "found": final_value is not None,
        "value": final_value,
        "source": final_source,
        "strategies": {"s1_metadata": s1, "s2_page1": s2, "s3_filename": s3},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus-dir", default="data/docs_done", help="Dossier PDFs SAP")
    p.add_argument("--output", default="data/spike_a10_results.json", help="Fichier JSON résultats")
    p.add_argument("--limit", type=int, default=20, help="Max PDFs à traiter")
    args = p.parse_args()

    corpus_dir = Path(args.corpus_dir)
    pdfs = sorted(corpus_dir.glob("*.pdf"))[: args.limit]
    if not pdfs:
        logger.error(f"Aucun PDF trouvé dans {corpus_dir}")
        sys.exit(1)

    logger.info(f"Spike A1.0 : extraction document_valid_from sur {len(pdfs)} PDFs")
    results = []
    for i, pdf in enumerate(pdfs, 1):
        logger.info(f"[{i}/{len(pdfs)}] {pdf.name}")
        r = extract_document_valid_from(pdf)
        results.append(r)

    # Stats agrégées
    n = len(results)
    n_found = sum(1 for r in results if r["found"])
    rate = n_found / n if n > 0 else 0.0
    by_source: dict[str, int] = {}
    for r in results:
        src = r["source"] or "NO_SIGNAL"
        # Bucket coarse
        if src and src.startswith("page1_near_keyword"):
            bucket = "S2_page1_keyword"
        elif src and src.startswith("page1_first_date"):
            bucket = "S2_page1_fallback"
        elif src in ("creation_date", "mod_date"):
            bucket = "S1_metadata"
        elif src == "filename_year":
            bucket = "S3_filename"
        else:
            bucket = "NO_SIGNAL"
        by_source[bucket] = by_source.get(bucket, 0) + 1

    summary = {
        "spike": "A1.0",
        "corpus_dir": str(corpus_dir),
        "n_pdfs": n,
        "n_found": n_found,
        "extraction_rate": round(rate, 4),
        "gate_target": 0.80,
        "gate_passed": rate >= 0.80,
        "distribution_by_source": by_source,
        "executed_at": datetime.utcnow().isoformat(),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2, ensure_ascii=False)

    logger.info(f"Résultats : {output_path}")
    logger.info(f"Taux extraction : {n_found}/{n} = {rate:.1%}")
    logger.info(f"Gate (≥80%) : {'✅ PASS' if rate >= 0.80 else '❌ FAIL'}")
    logger.info(f"Distribution : {by_source}")


if __name__ == "__main__":
    main()
