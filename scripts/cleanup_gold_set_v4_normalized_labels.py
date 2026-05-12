#!/usr/bin/env python3
"""
Cleanup gold-set v4 — ajout `normalized_label_en` pour matching cross-lingual.

Pour chaque item de `list_items_expected` :
  - Si l'item a un label FR (ou tout autre langue ≠ EN), le pipeline extrait
    naturellement un label EN depuis le corpus (qui est en EN). Le matcher
    strict du bench ne peut alors pas matcher.
  - On ajoute un champ `normalized_label_en` qui est la forme canonique EN
    extraite via LLM depuis (label original + source.quote).

Le LLM reçoit le label + la quote source (qui est verbatim EN dans tous les
corpus aerospace + dualuse) et génère un label canonique EN court.

Ne touche PAS aux items qui ont déjà un label EN clair, ni aux questions T6
ancien format (list_items_expected = liste de strings).

Usage :
  python scripts/cleanup_gold_set_v4_normalized_labels.py --dry-run
  python scripts/cleanup_gold_set_v4_normalized_labels.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLD_SET_PATH = PROJECT_ROOT / "benchmark" / "questions" / "gold_set_v4.json"

DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
DEEPINFRA_MODEL = os.getenv("CLEANUP_MODEL", "Qwen/Qwen2.5-72B-Instruct")

# Heuristique simple : l'item est probablement déjà EN si pas d'accents et pas
# de mots FR courants comme "l'", "le", "la", "des", "et"
FR_MARKERS = re.compile(r"[àâäéèêëîïôöùûüÿç]|\b(?:l['’]|le |la |les |des |du |de |et |dans |entre |chaque |selon )", re.IGNORECASE)


def looks_french(text: str) -> bool:
    return bool(FR_MARKERS.search(text or ""))


def load_key() -> str:
    key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if key:
        return key
    env = PROJECT_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEEPINFRA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("DEEPINFRA_API_KEY missing")


SYSTEM_PROMPT = """You generate canonical English labels for benchmark items used to measure list-extraction recall in a multi-domain Q&A system.

Given an item with a label (possibly in French) and the verbatim English quote from which it was extracted, return a SHORT (2-6 words) canonical English form that a list-extraction pipeline would naturally produce from the same source.

Rules:
- Output JSON only: {"normalized_label_en": "<short English canonical form, lowercase>"}
- Use lowercase. No leading/trailing punctuation.
- Strip articles (the, a, an) and connectors.
- Match the wording style of the source quote when possible.
- If the label is already a perfect short EN form, return it as-is (lowercased).

Examples:
- label="Autorisation individuelle d'exportation", quote="Individual export authorisation is granted..."
  → {"normalized_label_en": "individual export authorisation"}
- label="Recherche scientifique fondamentale", quote="basic scientific research"
  → {"normalized_label_en": "basic scientific research"}
- label="0B005 — Plant for nuclear reactor fuel fabrication", quote="0B005 Plant specially designed..."
  → {"normalized_label_en": "0b005 plant for nuclear reactor fuel fabrication"}
"""


def call_llm(label: str, quote: str, item_type: str, api_key: str, timeout: float = 30.0) -> str | None:
    user = (
        f"LABEL: {label}\n"
        f"ITEM_TYPE: {item_type}\n"
        f"SOURCE QUOTE (verbatim EN): {quote[:400]}\n\n"
        "Output JSON only."
    )
    payload = {
        "model": DEEPINFRA_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        "temperature": 0.0, "max_tokens": 80,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(DEEPINFRA_URL, json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        return str(data.get("normalized_label_en") or "").strip().lower()
    except Exception as exc:
        logger.warning("LLM call failed for %r: %s", label[:50], exc)
        return None


def process_item(item: dict, api_key: str) -> dict | None:
    """Annote un item avec normalized_label_en si manquant."""
    if not isinstance(item, dict):
        return None
    if item.get("normalized_label_en"):
        return None  # déjà annoté
    label = item.get("label") or ""
    if not label:
        return None
    src = item.get("source") or {}
    quote = src.get("quote") or ""
    item_type = item.get("item_type") or "unknown"

    # Si label semble déjà EN clair, prendre normalized_label si présent ou label tel quel
    if not looks_french(label):
        ll = (item.get("normalized_label") or label).lower().strip()
        return {"item_ref": item, "normalized_label_en": ll, "via_llm": False}

    # Sinon, appel LLM
    en = call_llm(label, quote, item_type, api_key)
    if not en:
        return None
    return {"item_ref": item, "normalized_label_en": en, "via_llm": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()

    gold = json.loads(GOLD_SET_PATH.read_text(encoding="utf-8"))
    logger.info("Loaded gold-set: %d items", len(gold))

    # Collecter tous les items qui ont besoin d'être annotés
    targets: list[dict] = []
    for q in gold:
        if q.get("primary_type") != "list":
            continue
        gt = q.get("ground_truth") or {}
        items = gt.get("list_items_expected") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("normalized_label_en"):
                continue
            targets.append(it)

    logger.info("Targets to annotate: %d items", len(targets))
    if args.dry_run:
        logger.info("[DRY-RUN] no LLM calls")
        return 0
    if not targets:
        logger.info("Nothing to do")
        return 0

    api_key = load_key()
    n_done = 0
    n_via_llm = 0
    n_failed = 0

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_item, it, api_key): it for it in targets}
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception as exc:
                logger.warning("worker failed: %s", exc)
                n_failed += 1
                continue
            if not result:
                n_failed += 1
                continue
            it = result["item_ref"]
            it["normalized_label_en"] = result["normalized_label_en"]
            n_done += 1
            if result["via_llm"]:
                n_via_llm += 1
            if n_done % 20 == 0:
                logger.info("Annotated %d/%d", n_done, len(targets))

    GOLD_SET_PATH.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = time.time() - t0
    logger.info("Done : %d annotated (%d via LLM, %d direct), %d failed in %.1fs",
                n_done, n_via_llm, n_done - n_via_llm, n_failed, elapsed)
    logger.info("Updated %s", GOLD_SET_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
