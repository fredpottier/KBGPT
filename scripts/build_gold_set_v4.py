#!/usr/bin/env python3
"""
CH-40.0 — Build gold-set v4 stratifié pour OSMOSIS V4 Sprint S0.

Sélectionne 100 questions brownfield depuis aero_t1-t7, appelle Qwen-72B DeepInfra
pour bootstrap les annotations criterion-level, persiste benchmark/questions/gold_set_v4.json.

Stratification (100 q total) :
  - 20 factual (T1)
  - 15 list (T6 set_list + synthesis_large)
  - 15 temporal (T7 lifecycle_supersedes/evolves_from + T6 temporal_evolution)
  - 10 causal (T6 causal_why)
  - 10 comparison (T2 diversifié)
  - 10 false_premise + unanswerable (T6 mix)
  -  8 ambiguës (multi-type)
  -  8 piégeuses (false_premise subtile, classifier_false_positive)
  -  9 KG-overinterpretation (apparent_tension, nuance_not_conflict, lifecycle_not_conflict)

Le LLM bootstrap construit ground_truth_answer (si manquant) + annotations criterion-level
selon le schéma V4 (cf doc/ongoing/ADR_OSMOSIS_V4_ARCHITECTURE.md D11).

Usage :
  python scripts/build_gold_set_v4.py --dry-run         # sélection seulement
  python scripts/build_gold_set_v4.py --limit 10         # process 10 items (test)
  python scripts/build_gold_set_v4.py                    # full run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "benchmark" / "questions"
OUTPUT_PATH = PROJECT_ROOT / "benchmark" / "questions" / "gold_set_v4.json"

DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
DEEPINFRA_MODEL = os.getenv("GOLD_SET_BOOTSTRAP_MODEL", "Qwen/Qwen2.5-72B-Instruct")

# Seed fixe pour reproductibilité de la sélection
RANDOM_SEED = 20260505


def load_deepinfra_key() -> str:
    """Récupère DEEPINFRA_API_KEY depuis env ou .env (cohérent avec audit_judge_calibration.py)."""
    key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if key:
        return key
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEEPINFRA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("DEEPINFRA_API_KEY manquant (ni env ni .env)")


def load_source(name: str) -> list[dict]:
    p = SOURCE_DIR / name
    return json.loads(p.read_text(encoding="utf-8"))


def detect_language(text: str) -> str:
    """Heuristique légère FR/EN sur tokens fréquents."""
    text_low = text.lower()
    fr_markers = sum(1 for m in [" le ", " la ", " les ", " du ", " des ", " est ", " quel", " quelle", "pourquoi", "comment", "à"] if m in text_low)
    en_markers = sum(1 for m in [" the ", " what ", " which ", " how ", " why ", " is ", " are ", " of ", " for "] if m in text_low)
    return "en" if en_markers > fr_markers else "fr"


# ──────────────────────────────────────────────────────────────────────────
# Selection — strates explicites
# ──────────────────────────────────────────────────────────────────────────

def stratify(t1: list, t2: list, t5: list, t6: list, t7: list) -> list[dict]:
    """Sélectionne 100 questions stratifiées avec primary_type/secondary_type/stratum."""
    rng = random.Random(RANDOM_SEED)
    selected: list[dict] = []
    used_ids: set[str] = set()

    def pick(items: list, n: int, primary: str, stratum: str, secondary: str | None = None) -> None:
        candidates = [it for it in items if it.get("id") not in used_ids]
        rng.shuffle(candidates)
        for it in candidates[:n]:
            used_ids.add(it["id"])
            selected.append({
                "_source": it,
                "primary_type": primary,
                "secondary_type": secondary,
                "stratum": stratum,
            })

    # ── Stratum 1 : factual (20) — T1 mix FR/EN ──────────────────────────
    # Garde les 6 EN + 14 FR
    en_t1 = [it for it in t1 if detect_language(it.get("question", "")) == "en"]
    fr_t1 = [it for it in t1 if detect_language(it.get("question", "")) != "en"]
    pick(en_t1[:6], 6, "factual", "factual_T1_en")
    pick(fr_t1, 14, "factual", "factual_T1_fr")

    # ── Stratum 2 : list (15) — T6 set_list + synthesis_large ────────────
    set_list = [it for it in t6 if it.get("category") == "set_list"]
    synth_large = [it for it in t6 if it.get("category") == "synthesis_large"]
    pick(set_list, 12, "list", "list_T6_set_list")
    pick(synth_large, 3, "list", "list_T6_synthesis_large")

    # ── Stratum 3 : temporal (15) — T7 lifecycle + T6 temporal ───────────
    super_seded = [it for it in t7 if it.get("category") == "lifecycle_supersedes"]
    evolves_from = [it for it in t7 if it.get("category") == "lifecycle_evolves_from"]
    temporal_evo = [it for it in t6 if it.get("category") == "temporal_evolution"]
    pick(super_seded, 5, "temporal", "temporal_T7_supersedes")
    pick(evolves_from, 5, "temporal", "temporal_T7_evolves_from")
    pick(temporal_evo, 5, "temporal", "temporal_T6_evolution")

    # ── Stratum 4 : causal (10) — T6 causal_why ──────────────────────────
    causal = [it for it in t6 if it.get("category") == "causal_why"]
    pick(causal, 10, "causal", "causal_T6_why")

    # ── Stratum 5 : comparison (10) — T2 diversifié (true tensions) ──────
    real_tensions = [
        it for it in t2
        if it.get("ground_truth", {}).get("has_real_tension") is True
        and it.get("category") not in {"lifecycle_not_conflict", "nuance_not_conflict"}
    ]
    pick(real_tensions, 10, "comparison", "comparison_T2_real_tension")

    # ── Stratum 6 : false_premise + unanswerable (10) — T6 ───────────────
    fp = [it for it in t6 if it.get("category") == "false_premise"]
    una = [it for it in t6 if it.get("category") == "unanswerable"]
    pick(fp, 5, "false_premise", "false_premise_T6")
    pick(una, 5, "unanswerable", "unanswerable_T6")

    # ── Stratum 7 : ambiguës multi-type (8) ──────────────────────────────
    # Multi-hop T6 (chaining = list+causal+temporal) + T6 hypothetical (causal+factual)
    multi_hop = [it for it in t6 if it.get("category") == "multi_hop"]
    hypothetical = [it for it in t6 if it.get("category") == "hypothetical"]
    pick(multi_hop, 5, "list", "ambiguous_multi_hop", secondary="temporal")
    pick(hypothetical, 3, "causal", "ambiguous_hypothetical", secondary="factual")

    # ── Stratum 8 : piégeuses (8) ────────────────────────────────────────
    # T2 classifier_false_positive (le KG dit conflit mais c'est une evolution)
    cfp = [it for it in t2 if it.get("category") == "classifier_false_positive"]
    # T6 negation (formulation trompeuse)
    negation = [it for it in t6 if it.get("category") == "negation"]
    # T6 conditional (réponse dépend de condition)
    conditional = [it for it in t6 if it.get("category") == "conditional"]
    pick(cfp, 3, "comparison", "trap_classifier_false_positive")
    pick(negation, 3, "factual", "trap_negation")
    pick(conditional, 2, "factual", "trap_conditional", secondary="causal")

    # ── Stratum 9 : KG-overinterpretation (9) ────────────────────────────
    # T2 où has_real_tension=False (le KG/classifier risque de sur-interpréter)
    ko_lifecycle = [it for it in t2 if it.get("category") == "lifecycle_not_conflict"]
    ko_nuance = [it for it in t2 if it.get("category") == "nuance_not_conflict"]
    ko_apparent = [it for it in t2 if it.get("category") == "apparent_tension_resolved"]
    ko_complementary = [it for it in t2 if it.get("category") in {"complementary_documents", "complementary_distinct_object", "complementary_distinct_scope", "complementary_not_conflict"}]
    ko_disjoint = [it for it in t2 if it.get("category") in {"disjoint_requirements", "disjoint_scopes_no_conflict", "different_regulatory_domains"}]
    pick(ko_lifecycle, 2, "comparison", "kg_over_lifecycle_not_conflict")
    pick(ko_nuance, 2, "comparison", "kg_over_nuance_not_conflict")
    pick(ko_apparent, 2, "comparison", "kg_over_apparent_tension")
    pick(ko_complementary, 2, "comparison", "kg_over_complementary")
    pick(ko_disjoint, 1, "comparison", "kg_over_disjoint")

    return selected


# ──────────────────────────────────────────────────────────────────────────
# LLM bootstrap — DeepInfra Qwen-72B
# ──────────────────────────────────────────────────────────────────────────

BOOTSTRAP_PROMPT = """You are an expert annotator preparing a gold-set for a regulatory Q&A system.

For each question, you receive:
- The question (in FR or EN)
- The original ground_truth structure (which varies: T1=ground_truth_answer/verbatim_quote, T2=claim_a/claim_b/tension, T6=expected_behavior/correct_fact/evidence, T7=expected_anchor/lifecycle)
- The expected primary_type (factual|list|temporal|causal|comparison|false_premise|unanswerable)

Your job: produce a STRICT JSON annotation following this schema:

{
  "ground_truth_answer": "<full reference answer in same language as question, ready for RAGAS FactualCorrectness>",
  "answerability": "answerable|partial|unanswerable",
  "false_premise": true|false,
  "exact_identifiers": ["<critical IDs/dates/values that MUST appear verbatim>"],
  "list_items_expected": null | ["<item1>", "<item2>"],
  "supporting_doc_ids": ["<doc_id_1>", "<doc_id_2>"],
  "contradiction_vs_supersession": null | "CONTRADICTION" | "SUPERSESSION",
  "causal_chain": null | ["<step 1>", "<step 2>"],
  "answer_language": "fr"|"en",
  "annotation_confidence": 0.0..1.0
}

CRITICAL RULES:
1. ground_truth_answer = synthesize from the original ground_truth fields. If T1 has ground_truth_answer, use it as base. If T2/T6/T7 only has correct_fact + evidence_claim, COMPOSE a complete answer.
2. exact_identifiers = ONLY identifiers that the system MUST reproduce verbatim (regulation numbers like "2021/821", dates like "20 May 2021", numeric values like "21 J", code refs like "CS 25.1309(c)"). NOT generic words.
3. supporting_doc_ids = extract from original ground_truth (evidence_doc, claim_a.doc_id, expected_anchor, etc.). Empty list if unanswerable.
4. list_items_expected = ONLY for primary_type=list. Items the system should enumerate. null for non-list.
5. contradiction_vs_supersession = ONLY for primary_type=comparison. CONTRADICTION = real conflict, SUPERSESSION = lifecycle replacement, null = false tension.
6. causal_chain = ONLY for primary_type=causal. List 2-4 reasoning steps. null for non-causal.
7. answer_language = match the question language.
8. annotation_confidence = 0.5 if you had to invent ground_truth_answer because original was incomplete; 0.9 if everything was clearly in source.

Return ONLY the JSON object, no commentary, no markdown fences.
"""


def bootstrap_one(item: dict, api_key: str, timeout: float = 60.0) -> dict | None:
    """Appelle DeepInfra Qwen-72B pour bootstrap une annotation."""
    src = item["_source"]
    question = src.get("question", "")
    primary_type = item["primary_type"]
    user_msg = (
        f"PRIMARY_TYPE: {primary_type}\n"
        f"QUESTION ({detect_language(question)}): {question}\n\n"
        f"ORIGINAL GROUND TRUTH:\n{json.dumps({k: v for k, v in src.items() if k not in {'task', 'id', 'question'}}, ensure_ascii=False, indent=2)}\n\n"
        "Produce the JSON annotation following the schema."
    )
    payload = {
        "model": DEEPINFRA_MODEL,
        "messages": [
            {"role": "system", "content": BOOTSTRAP_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.1,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(DEEPINFRA_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bootstrap] failed for %s: %s", src.get("id"), exc)
        return None


def build_gold_item(item: dict, annotation: dict | None) -> dict:
    """Compose l'item final gold-set v4."""
    src = item["_source"]
    question = src.get("question", "")
    lang = detect_language(question)
    return {
        "id": f"GOLD_v4_{src.get('id', 'UNKNOWN')}",
        "source_id": src.get("id"),
        "source_task": src.get("task"),
        "source_category": src.get("category"),
        "question": question,
        "language": lang,
        "primary_type": item["primary_type"],
        "secondary_type": item.get("secondary_type"),
        "stratum": item["stratum"],
        "ground_truth": annotation if annotation else {
            "ground_truth_answer": "",
            "answerability": "unknown",
            "false_premise": None,
            "exact_identifiers": [],
            "list_items_expected": None,
            "supporting_doc_ids": [],
            "contradiction_vs_supersession": None,
            "causal_chain": None,
            "answer_language": lang,
            "annotation_confidence": 0.0,
            "_bootstrap_failed": True,
        },
        "annotation_meta": {
            "annotator": "claude_human_review",
            "bootstrap_source": DEEPINFRA_MODEL,
            "bootstrap_succeeded": annotation is not None,
            "reviewed_at": None,  # à remplir lors de la review humaine
            "reviewer_confidence": None,
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Sélection seulement, pas d'appel LLM")
    parser.add_argument("--limit", type=int, default=None, help="Limite N items (test)")
    parser.add_argument("--concurrency", type=int, default=5, help="DeepInfra concurrency (default 5)")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH), help="Output path")
    parser.add_argument("--validate-only", action="store_true", help="Validate existing gold-set JSON")
    args = parser.parse_args()

    output_path = Path(args.output)

    # Mode validate-only : vérifier le fichier gold-set existant
    if args.validate_only:
        if not output_path.exists():
            logger.error("File not found: %s", output_path)
            return 1
        data = json.loads(output_path.read_text(encoding="utf-8"))
        n = len(data)
        types = {}
        langs = {}
        strata = {}
        for it in data:
            types[it.get("primary_type", "?")] = types.get(it.get("primary_type", "?"), 0) + 1
            langs[it.get("language", "?")] = langs.get(it.get("language", "?"), 0) + 1
            strata[it.get("stratum", "?")] = strata.get(it.get("stratum", "?"), 0) + 1
        print(f"=== Gold-set v4 validation ===")
        print(f"Total: {n} questions")
        print(f"Primary types: {types}")
        print(f"Languages: {langs}")
        print(f"Strata: {strata}")
        return 0 if n >= 90 else 1

    # Mode normal : selection + bootstrap
    logger.info("Loading source files...")
    t1 = load_source("aero_t1_provenance.json")
    t2 = load_source("aero_t2_contradictions.json")
    t5 = load_source("aero_t5_cross_doc.json")
    t6 = load_source("aero_t6_robustness.json")
    t7 = load_source("aero_t7_v2_anchor.json")
    logger.info("Loaded T1=%d T2=%d T5=%d T6=%d T7=%d", len(t1), len(t2), len(t5), len(t6), len(t7))

    logger.info("Stratifying selection (seed=%d)...", RANDOM_SEED)
    selected = stratify(t1, t2, t5, t6, t7)
    logger.info("Selected %d questions", len(selected))

    if args.limit:
        selected = selected[: args.limit]
        logger.info("Limited to %d (--limit)", len(selected))

    # Stats avant bootstrap
    type_counts: dict[str, int] = {}
    stratum_counts: dict[str, int] = {}
    for it in selected:
        type_counts[it["primary_type"]] = type_counts.get(it["primary_type"], 0) + 1
        stratum_counts[it["stratum"]] = stratum_counts.get(it["stratum"], 0) + 1
    logger.info("Distribution by primary_type: %s", type_counts)
    logger.info("Distribution by stratum: %s", stratum_counts)

    if args.dry_run:
        logger.info("[DRY-RUN] No LLM calls. Persisting selection skeleton.")
        skeleton = [build_gold_item(it, None) for it in selected]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Wrote %d skeleton items to %s", len(skeleton), output_path)
        return 0

    # Bootstrap LLM en parallèle
    api_key = load_deepinfra_key()
    logger.info("Bootstrapping %d items via DeepInfra %s (concurrency=%d)...", len(selected), DEEPINFRA_MODEL, args.concurrency)

    annotations: dict[int, dict | None] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        future_map = {executor.submit(bootstrap_one, it, api_key): i for i, it in enumerate(selected)}
        completed = 0
        for fut in as_completed(future_map):
            i = future_map[fut]
            try:
                annotations[i] = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[bootstrap %d] exception: %s", i, exc)
                annotations[i] = None
            completed += 1
            if completed % 10 == 0:
                elapsed = time.time() - t0
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (len(selected) - completed) / rate if rate > 0 else 0
                logger.info("[bootstrap] %d/%d (%.1f q/s, ETA %.0fs)", completed, len(selected), rate, eta)

    # Compose final gold-set
    gold_items = [build_gold_item(it, annotations.get(i)) for i, it in enumerate(selected)]
    n_succeeded = sum(1 for g in gold_items if g["annotation_meta"]["bootstrap_succeeded"])
    n_failed = len(gold_items) - n_succeeded
    logger.info("Bootstrap done: %d succeeded, %d failed (%.1f%% success)", n_succeeded, n_failed, 100 * n_succeeded / max(len(gold_items), 1))

    # Persist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(gold_items, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %d items to %s", len(gold_items), output_path)
    logger.info("Total elapsed: %.1fs", time.time() - t0)

    # README cohérent
    readme_path = output_path.parent / "GOLD_SET_V4_README.md"
    readme_content = f"""# Gold-set v4 — OSMOSIS V4 Sprint S0

Construit par `scripts/build_gold_set_v4.py` (CH-40.0).

## Source
Brownfield depuis les 5 fichiers `aero_t1-t7` (290 questions sources).
Bootstrap automatique via DeepInfra `{DEEPINFRA_MODEL}`.
Review humaine : Claude (assistant), à compléter dans `annotation_meta.reviewed_at`.

## Stratification
| Stratum | Count |
|---------|-------|
""" + "\n".join(f"| {k} | {v} |" for k, v in sorted(stratum_counts.items())) + f"""

Total : {len(gold_items)} questions
Bootstrap success rate : {100 * n_succeeded / max(len(gold_items), 1):.1f}%

## Schéma
Chaque item suit le schéma défini dans ADR_OSMOSIS_V4_ARCHITECTURE.md décision D11.
Champs critiques :
- `ground_truth.ground_truth_answer` : référence pour RAGAS FactualCorrectness
- `ground_truth.exact_identifiers` : IDs/dates/valeurs critiques pour exact_match metric
- `ground_truth.supporting_doc_ids` : doc_ids pour citation_presence_rate metric
- `ground_truth.list_items_expected` : items pour item_level_recall metric

## Validation
```bash
python scripts/build_gold_set_v4.py --validate-only
```

## Régénération
Seed fixe (RANDOM_SEED=20260505) — la sélection est reproductible.
"""
    readme_path.write_text(readme_content, encoding="utf-8")
    logger.info("Wrote README to %s", readme_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
