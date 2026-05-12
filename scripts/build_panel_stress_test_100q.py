#!/usr/bin/env python3
"""
CH-41.0 livrable C — Construire panel_stress_test_100q.json multi-domaines.

But : valider HFF5 (≥ 95% du trafic tombe dans un type avec confidence ≥ 0.5)
sur un panel diversifié couvrant 5 domaines hors-aerospace.

Référence : doc/ongoing/chantiers/2026-05-06_CH-41_STRESS_TEST_PANEL_SPEC.md (D-FF12)

Stratification cible (5 domaines × 20q = 100q) :
  - médical, juridique, software docs, RH, produit
Distribution par primary_type attendu (par domaine) :
  - 5 factual, 4 list, 3 temporal, 3 comparison, 3 causal, 2 unanswerable/false_premise

Inclusions explicites (sur les 100) :
  - 10 multi-label naturelles (ex list+temporal)
  - 5 méta-questions (test fallback EAV)
  - 5 ambiguës (stress test seuil 0.5)

GARDE-FOU D-FF12 : ce panel ne sert PAS à mesurer la qualité de réponse
end-to-end. Uniquement la couverture typologique HFF5.

Usage :
  python scripts/build_panel_stress_test_100q.py --dry-run
  python scripts/build_panel_stress_test_100q.py
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
OUTPUT_PATH = PROJECT_ROOT / "benchmark" / "questions" / "panel_stress_test_100q.json"

DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
DEEPINFRA_MODEL = os.getenv("STRESS_TEST_BOOTSTRAP_MODEL", "Qwen/Qwen2.5-72B-Instruct")

RANDOM_SEED = 20260506

DOMAINS = {
    "medical": "Medical / clinical knowledge — drug interactions, contraindications, dosages, clinical protocols, validation studies, side effects.",
    "legal": "Legal / regulatory — articles of law, jurisprudence, contractual clauses, applicability across jurisdictions, statute of limitations, exemptions.",
    "software": "Software documentation — API specs, configuration parameters, troubleshooting steps, versioning, dependencies, breaking changes.",
    "hr": "HR / corporate policy — internal procedures, employee rights, onboarding processes, diversity policies, leave policies, compensation.",
    "product": "Product / e-commerce — technical specifications, product comparisons, availability, warranties, return policies, customer service contacts.",
}

# Stratification par primary_type, par domaine
STRATIFICATION = {
    "factual": 5,
    "list": 4,
    "temporal": 3,
    "comparison": 3,
    "causal": 3,
    "unanswerable_or_false_premise": 2,
}
# Total par domaine = 20

# Cas limites globaux à inclure (sur les 100 totales, en bonus)
EDGE_CASES = {
    "multi_label_natural": 10,   # ex list+temporal
    "meta_question": 5,          # méta sur le système, hors-typologie
    "ambiguous": 5,              # formulations floues
}


GENERATE_DOMAIN_QUESTIONS_SYSTEM = """You generate benchmark questions for a multi-domain Q&A system.

Generate realistic user questions that someone would ask a documentation system in the given DOMAIN.

For each question, provide :
- question : in the requested LANGUAGE (fr 60% / en 40%)
- expected_primary_type : one of [factual, list, temporal, comparison, causal, unanswerable, false_premise]
- expected_secondary_type : null or one of the same set (if multi-label)
- expected_difficulty : "easy" | "normal" | "hard"
- expected_to_trigger_eav : true | false (true if question is ambiguous, meta, or hors-typologie)
- rationale : one short sentence explaining the type classification

Each question must :
1. Be realistic (something a user would actually ask)
2. Be specific enough to be answerable from documentation
3. Match the expected primary_type structurally
4. Be in the requested language

Return STRICT JSON :
{"questions": [...]}
"""


GENERATE_DOMAIN_USER_TEMPLATE = """DOMAIN : {domain_name}
DOMAIN_DESCRIPTION : {domain_description}

Generate {n_questions} questions stratified by primary_type :
- {n_factual} factual (single fact lookup)
- {n_list} list (enumeration of items)
- {n_temporal} temporal (versioning, dates, evolutions)
- {n_comparison} comparison (≥2 sources/positions compared)
- {n_causal} causal (why questions, mechanisms)
- {n_unanswerable} unanswerable or false_premise (edge cases)

Language mix : 60% French, 40% English.
Output JSON only."""


GENERATE_EDGE_CASES_SYSTEM = """You generate edge-case benchmark questions for testing a Q&A router.

Generate questions that are intentionally :
- multi_label_natural : naturally fit 2 primary_types (e.g. "what changed between v1 and v2" = list + temporal)
- meta_question : about the system itself or its capabilities (e.g. "how do you handle contradictions?")
- ambiguous : multiple plausible interpretations or unclear intent

Output JSON :
{"questions": [{"question": "...", "edge_case_kind": "...", "rationale": "...", "language": "fr|en"}]}
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


def call_llm(system: str, user: str, api_key: str, max_tokens: int = 2500, timeout: float = 180.0) -> str | None:
    payload = {
        "model": DEEPINFRA_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
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


def parse_questions(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, dict):
        for k in ("questions", "items", "data"):
            if k in data and isinstance(data[k], list):
                return data[k]
    if isinstance(data, list):
        return data
    return []


def build_domain_panel(domain: str, domain_description: str, api_key: str) -> list[dict]:
    """Génère 20 questions pour un domaine donné."""
    user = GENERATE_DOMAIN_USER_TEMPLATE.format(
        domain_name=domain,
        domain_description=domain_description,
        n_questions=sum(STRATIFICATION.values()),
        n_factual=STRATIFICATION["factual"],
        n_list=STRATIFICATION["list"],
        n_temporal=STRATIFICATION["temporal"],
        n_comparison=STRATIFICATION["comparison"],
        n_causal=STRATIFICATION["causal"],
        n_unanswerable=STRATIFICATION["unanswerable_or_false_premise"],
    )
    raw = call_llm(GENERATE_DOMAIN_QUESTIONS_SYSTEM, user, api_key, max_tokens=3500)
    if not raw:
        return []
    qs = parse_questions(raw)
    # Enrichir avec metadata
    for q in qs:
        q["domain"] = domain
        q["edge_case_kind"] = None  # pour les non-edge-cases
    return qs


def build_edge_cases(api_key: str) -> list[dict]:
    """Génère les 20 cas limites globaux."""
    edge_cases = []
    for kind, n in EDGE_CASES.items():
        user = (
            f"Generate {n} questions of edge_case_kind = '{kind}'. "
            f"Spread across domains (medical, legal, software, hr, product). "
            f"Language mix : 60% French, 40% English."
        )
        raw = call_llm(GENERATE_EDGE_CASES_SYSTEM, user, api_key, max_tokens=2000)
        if not raw:
            continue
        items = parse_questions(raw)
        for q in items[:n]:
            q["edge_case_kind"] = kind
            # expected_primary_type depends on kind
            if kind == "meta_question":
                q.setdefault("expected_primary_type", "unanswerable")
                q.setdefault("expected_to_trigger_eav", True)
            elif kind == "multi_label_natural":
                # primary/secondary types restent à inférer
                q.setdefault("expected_to_trigger_eav", False)
            elif kind == "ambiguous":
                q.setdefault("expected_to_trigger_eav", True)
        edge_cases.extend(items[:n])
    return edge_cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan only")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH))
    args = parser.parse_args()

    output_path = Path(args.output)

    plan_summary = {
        "domains": list(DOMAINS.keys()),
        "questions_per_domain": sum(STRATIFICATION.values()),
        "stratification": STRATIFICATION,
        "edge_cases": EDGE_CASES,
        "total_target": len(DOMAINS) * sum(STRATIFICATION.values()) + sum(EDGE_CASES.values()),
    }
    logger.info("Plan : %s", json.dumps(plan_summary, indent=2))

    if args.dry_run:
        logger.info("[DRY-RUN] No LLM calls")
        return 0

    api_key = load_deepinfra_key()

    # Generate domain panels (5 domaines × 20q)
    all_questions: list[dict] = []
    t0 = time.time()
    for domain, desc in DOMAINS.items():
        logger.info("Generating panel for domain : %s", domain)
        qs = build_domain_panel(domain, desc, api_key)
        all_questions.extend(qs)
        logger.info("  %s : %d questions generated", domain, len(qs))

    # Generate edge cases (20q across 3 kinds)
    logger.info("Generating edge cases")
    edge_qs = build_edge_cases(api_key)
    all_questions.extend(edge_qs)
    logger.info("  edge cases : %d questions", len(edge_qs))

    elapsed = time.time() - t0
    logger.info("Total generation : %d questions in %.1fs", len(all_questions), elapsed)

    # Stamp + IDs
    for i, q in enumerate(all_questions, 1):
        q["id"] = f"STRESS_v1_{i:03d}"
        q.setdefault("annotation_meta", {})["bootstrap_source"] = DEEPINFRA_MODEL
        q.setdefault("annotation_meta", {})["generated_at"] = "2026-05-06"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(all_questions, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %d questions to %s", len(all_questions), output_path)

    # Final stats
    from collections import Counter
    domains_dist = Counter(q.get("domain", "edge") for q in all_questions)
    types_dist = Counter(q.get("expected_primary_type", "?") for q in all_questions)
    langs_dist = Counter(q.get("language", "?") for q in all_questions)
    edge_dist = Counter(q.get("edge_case_kind", "none") for q in all_questions)
    logger.info("=== Distributions ===")
    logger.info("  Domains : %s", dict(domains_dist))
    logger.info("  Types   : %s", dict(types_dist))
    logger.info("  Langs   : %s", dict(langs_dist))
    logger.info("  Edge    : %s", dict(edge_dist))
    return 0


if __name__ == "__main__":
    sys.exit(main())
