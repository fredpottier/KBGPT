#!/usr/bin/env python3
"""
CH-41.0 livrable D — Correction schéma gold-set v4 false_premise/unanswerable.

Bug constaté (Sprint S0) : Pearson juge ↔ structured = -0.94 sur false_premise
et -0.79 sur unanswerable. Cause : sur ces 2 types, la BONNE réponse est un
REJET / ABSTENTION qui ne contient ni `exact_identifiers` (du `correct_fact`)
ni `supporting_doc_ids` (de l'evidence du fait). Donc anti-corrélation totale
entre le structured (qui mesure presence des identifiers/docs) et le judge LLM
(qui mesure correctly_rejected).

Cf `feedback_gold_set_design_bug_false_premise.md` pour le diagnostic complet.

Solution : ajouter au ground_truth des 10 questions concernées 2 nouveaux
champs sémantiques multilingues (PAS de regex/keywords métier — charte anti-V2) :

  - `correct_premise_rejection_signals[]` : descriptions sémantiques de ce
    qu'une bonne réponse devrait contenir pour rejeter la prémisse fausse
  - `unanswerable_explicit_signals[]` : idem pour admettre l'absence d'info

Ces signaux servent à un nouveau métriques structured `correct_rejection_score`
qui remplace exact_match/citation_presence pour ces 2 types.

Usage :
  python scripts/fix_gold_set_v4_false_premise_unanswerable.py --dry-run
  python scripts/fix_gold_set_v4_false_premise_unanswerable.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
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
DEEPINFRA_MODEL = os.getenv("FIX_BOOTSTRAP_MODEL", "Qwen/Qwen2.5-72B-Instruct")

GENERATE_SIGNALS_SYSTEM = """You annotate semantic signals for benchmark questions on REJECTION / ABSTENTION behaviors.

Your job : given a QUESTION + ORIGINAL GROUND TRUTH, produce semantic descriptions
of what a CORRECT response should express to either :
- REJECT a false premise (the question contains an unsupported/contradicted assumption)
- ADMIT being unanswerable (the requested info is not in the corpus)

These are NOT regex patterns or keyword lists. They are SEMANTIC descriptions a
multilingual LLM-judge can use to verify the response correctly handled the case.

For false_premise :
- correct_premise_rejection_signals : 2-4 short semantic descriptions of what
  a correct rejection should contain (e.g. "The response explicitly contradicts
  the assumption that X by citing evidence Y", "The response does NOT confirm
  the false claim and instead clarifies the actual rule").

For unanswerable :
- unanswerable_explicit_signals : 2-4 short semantic descriptions of what a
  correct abstention should contain (e.g. "The response explicitly states that
  the information is not available in the indexed corpus", "The response does
  NOT fabricate or guess a value").

CRITICAL :
- Multilingual : signals must work across FR/EN (describe the SEMANTIC, not the
  language-specific phrasing).
- Domain-agnostic : no domain-specific keyword lists.
- Verifiable : a LLM-judge with the response should be able to check each signal.

Return STRICT JSON :
{
  "type": "false_premise | unanswerable",
  "correct_premise_rejection_signals": ["...", "..."],  // ONLY if false_premise
  "unanswerable_explicit_signals": ["...", "..."],       // ONLY if unanswerable
  "expected_response_summary": "1-line description of what the perfect answer looks like"
}
"""


def load_deepinfra_key() -> str:
    key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if key:
        return key
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEEPINFRA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("DEEPINFRA_API_KEY missing")


def call_llm(system: str, user: str, api_key: str, max_tokens: int = 800, timeout: float = 60.0) -> str | None:
    payload = {
        "model": DEEPINFRA_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(DEEPINFRA_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        return None


def annotate_one(q: dict, api_key: str) -> dict | None:
    """Génère les signaux sémantiques pour une question false_premise/unanswerable."""
    primary = q.get("primary_type")
    if primary not in {"false_premise", "unanswerable"}:
        return None
    gt = q.get("ground_truth", {})
    user = (
        f"QUESTION ({q.get('language', 'fr')}) : {q.get('question','')}\n\n"
        f"PRIMARY_TYPE : {primary}\n\n"
        f"ORIGINAL GROUND TRUTH :\n"
        f"  ground_truth_answer : {gt.get('ground_truth_answer','')[:400]}\n"
        f"  answerability       : {gt.get('answerability')}\n"
        f"  false_premise       : {gt.get('false_premise')}\n\n"
        "Generate the semantic signals. JSON only."
    )
    raw = call_llm(GENERATE_SIGNALS_SYSTEM, user, api_key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("JSON parse failed for %s", q.get("id"))
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan only")
    parser.add_argument("--limit", type=int, default=None, help="Limit N questions for test")
    args = parser.parse_args()

    if not GOLD_SET_PATH.exists():
        logger.error("Gold-set not found")
        return 1
    gold = json.loads(GOLD_SET_PATH.read_text(encoding="utf-8"))
    logger.info("Loaded gold-set : %d items", len(gold))

    fp_qs = [q for q in gold if q.get("primary_type") == "false_premise"]
    un_qs = [q for q in gold if q.get("primary_type") == "unanswerable"]
    logger.info("Concerned : %d false_premise + %d unanswerable = %d total", len(fp_qs), len(un_qs), len(fp_qs) + len(un_qs))

    targets = fp_qs + un_qs
    if args.limit:
        targets = targets[: args.limit]

    if args.dry_run:
        logger.info("[DRY-RUN] Would re-annotate %d questions with semantic signals", len(targets))
        return 0

    api_key = load_deepinfra_key()
    n_ok = 0
    n_failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(annotate_one, q, api_key): q for q in targets}
        for fut in as_completed(futures):
            q = futures[fut]
            ann = fut.result()
            if not ann:
                n_failed += 1
                continue
            # Inject signals into ground_truth
            primary = q.get("primary_type")
            if primary == "false_premise":
                q["ground_truth"]["correct_premise_rejection_signals"] = ann.get("correct_premise_rejection_signals", [])
            elif primary == "unanswerable":
                q["ground_truth"]["unanswerable_explicit_signals"] = ann.get("unanswerable_explicit_signals", [])
            q["ground_truth"]["expected_response_summary"] = ann.get("expected_response_summary", "")
            q["ground_truth"]["_phase_d_metadata"] = {
                "annotated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "annotator": DEEPINFRA_MODEL,
                "ch41_0_livrable": "D",
            }
            n_ok += 1

    elapsed = time.time() - t0
    logger.info("Annotated %d/%d in %.1fs (failed: %d)", n_ok, len(targets), elapsed, n_failed)

    GOLD_SET_PATH.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Updated gold-set persisted to %s", GOLD_SET_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
