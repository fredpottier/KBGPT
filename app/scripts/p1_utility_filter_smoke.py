#!/usr/bin/env python
"""
p1_utility_filter_smoke.py — SMOKE (read-only) du levier #3 "filtre utilité"
(check-worthiness) sur un échantillon de claims déjà en KG.

Volet 2 SOTA, lever #3 : la plus grosse part du sur-volume P1.3.5 n'est PAS de la
redondance (cf probe dédup = 13% seulement) mais du **boilerplate** (disclaimers
juridiques, notices, méta-document, énoncés vacants). On mesure ici quelle fraction
des claims est "jetable" — un LLM-judge (DeepSeek-V3.1, open-source via DeepInfra)
classe chaque claim KEEP (fait substantiel, vérifiable, répond à une vraie question)
vs DROP (boilerplate / disclaimer / méta / filler vide de contenu vérifiable).

GARDE-FOU IMPÉRATIF : un claim portant un identifiant protégé (ALL_CAPS, snake_case,
code, n° réglement, version) n'est JAMAIS jeté — même si le juge dit DROP, on override
en KEEP et on compte l'override (réutilise `protected_identifiers()` du probe dédup).

Le prompt est DOMAIN-AGNOSTIC (exemples neutres, aucune règle SAP). Read-only Neo4j,
aucune mutation, aucun burst.

Usage:
    docker compose exec app python scripts/p1_utility_filter_smoke.py
    docker compose exec app python scripts/p1_utility_filter_smoke.py --sample 150 --seed 42
    docker compose exec app python scripts/p1_utility_filter_smoke.py --workers 8
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("[OSMOSE] utility_filter")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "benchmark" / "dedup"
MODEL = os.getenv("UTILITY_JUDGE_MODEL", "deepseek-ai/DeepSeek-V3.1")
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

# réutilise le garde-fou identifiants du probe dédup (même dossier scripts/)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p1_dedup_tiered_probe import protected_identifiers  # noqa: E402

import re as _re


def specific_identifiers(text: str) -> List[str]:
    """Garde-fou SPÉCIFICITÉ-aware pour le filtre utilité.

    Plus strict que protected_identifiers() : on ne protège QUE les identifiants
    rares/précis qu'un utilisateur pourrait rechercher (snake_case, codes
    alphanumériques, chemins, n° réglement/version), PAS les acronymes courts
    ubiquitaires (SAP, HR, TM, EU...) ni les noms de produit — sinon le garde-fou
    sauve à tort le boilerplate qui cite le nom de l'éditeur.

    Domain-agnostic : heuristique de spécificité, aucun nom codé en dur.
    """
    out: List[str] = []
    for tok in protected_identifiers(text):
        has_digit = bool(_re.search(r"\d", tok))
        has_sep = ("_" in tok) or ("/" in tok) or ("." in tok) or ("-" in tok)
        # pure-alpha (issu d'un ALL_CAPS) : spécifique seulement si long (≥4)
        pure_alpha = tok.isalpha()
        if has_digit or has_sep:
            out.append(tok)
        elif pure_alpha and len(tok) >= 4:
            out.append(tok)
        # sinon (acronyme alpha ≤3 : sap, hr, tm, eu...) -> NON protégé
    return sorted(set(out))


# ──────────────────────────────────────────────────────────────────────────────
# Prompt juge — DOMAIN-AGNOSTIC
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You curate a knowledge base of atomic factual claims extracted \
from documents. Each claim is stored to later answer real user questions via retrieval. \
Your job: decide whether a single claim is WORTH STORING as a retrievable knowledge claim.

Label KEEP if the claim conveys substantive, checkable knowledge that could answer a \
genuine question about the subject matter: a fact, definition, rule, capability, \
constraint, procedure step, relationship, configuration, or numeric/identifier value.

Label DROP if the claim is NOT worth storing because it is one of:
- legal / liability / warranty / copyright / disclaimer boilerplate;
- document meta-statements (table of contents, "this document describes...", section \
navigation, formatting notes, version/date stamps with no standalone fact);
- generic marketing or filler with no checkable content;
- vacuous / contentless statements that assert almost nothing ("X enables the use of \
key features", "the solution provides many benefits", "this improves efficiency");
- pure cross-references ("see the section below", "refer to the guide").

DROP as "vacuous" ONLY when the statement has essentially no checkable content. If the \
claim names a specific feature, field, object, parameter, capability, actor, or a \
concrete relationship between named things — even briefly — prefer KEEP, not vacuous.

Be domain-neutral: apply the SAME criteria regardless of subject (software, medical, \
legal, engineering...). When a claim carries a concrete checkable detail, prefer KEEP. \
When in genuine doubt, prefer KEEP (recall matters).

Respond with STRICT JSON only:
{"label": "KEEP" | "DROP", "category": "<short tag>", "confidence": 0.0-1.0, "reason": "<=12 words"}

Categories for DROP: "legal_boilerplate", "doc_meta", "marketing_filler", \
"vacuous", "cross_reference". For KEEP: "factual", "definition", "rule", \
"capability", "procedure", "relationship", "identifier_value", "other"."""

EXAMPLES = [
    # (claim, expected label) — exemples NEUTRES, non liés au corpus de test
    ("The provider shall not be liable for any damages arising from the use of this material.",
     "DROP / legal_boilerplate"),
    ("This document is organized into five chapters covering installation and maintenance.",
     "DROP / doc_meta"),
    ("The platform delivers powerful capabilities that help organizations succeed.",
     "DROP / marketing_filler"),
    ("Water boils at 100 degrees Celsius at standard atmospheric pressure.",
     "KEEP / factual"),
    ("A booster dose is recommended six months after the second injection.",
     "KEEP / rule"),
]

USER_TEMPLATE = """Here are reference examples (claim -> expected decision):
{examples}

Now classify this claim:
\"\"\"{text}\"\"\"

JSON:"""


def build_user_prompt(text: str) -> str:
    ex = "\n".join(f'- "{c}" -> {lab}' for c, lab in EXAMPLES)
    return USER_TEMPLATE.format(examples=ex, text=text)


# ──────────────────────────────────────────────────────────────────────────────
# Données
# ──────────────────────────────────────────────────────────────────────────────

def load_sample(tenant_id: str, sample: int, seed: int) -> List[dict]:
    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        rows = [
            {"claim_id": r["claim_id"], "text": r["text"] or "",
             "doc_id": r["doc_id"], "claim_type": r["claim_type"]}
            for r in session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})
                RETURN c.claim_id AS claim_id, c.text AS text,
                       c.doc_id AS doc_id, c.claim_type AS claim_type
                ORDER BY c.claim_id
                """,
                tid=tenant_id,
            )
        ]
    driver.close()
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows[:sample]


# ──────────────────────────────────────────────────────────────────────────────
# Juge LLM
# ──────────────────────────────────────────────────────────────────────────────

def make_client():
    from openai import OpenAI

    key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if not key:
        raise SystemExit("DEEPINFRA_API_KEY manquant dans l'environnement du container")
    return OpenAI(api_key=key, base_url=DEEPINFRA_BASE_URL, max_retries=4, timeout=120.0)


def _parse_json(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except Exception:
        # tenter d'extraire le 1er objet {...}
        start, depth = text.find("{"), 0
        if start >= 0:
            for k in range(start, len(text)):
                depth += (text[k] == "{") - (text[k] == "}")
                if depth == 0:
                    try:
                        return json.loads(text[start:k + 1])
                    except Exception:
                        return None
        return None


def judge_one(client, claim: dict) -> dict:
    text = claim["text"]
    prot = specific_identifiers(text)
    rec = {
        "claim_id": claim["claim_id"], "text": text,
        "doc_id": claim.get("doc_id"), "claim_type": claim.get("claim_type"),
        "protected_ids": prot,
    }
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(text)},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        parsed = _parse_json(resp.choices[0].message.content)
    except Exception as exc:
        rec.update(judge_label="ERROR", final_label="KEEP", category="error",
                   confidence=0.0, reason=str(exc)[:120], guard_override=False)
        return rec

    if not parsed or "label" not in parsed:
        rec.update(judge_label="PARSE_FAIL", final_label="KEEP", category="parse_fail",
                   confidence=0.0, reason="json parse failed", guard_override=False)
        return rec

    judge_label = "DROP" if str(parsed.get("label", "")).upper() == "DROP" else "KEEP"
    # GARDE-FOU : identifiant protégé -> jamais DROP
    guard_override = judge_label == "DROP" and bool(prot)
    final_label = "KEEP" if guard_override else judge_label
    rec.update(
        judge_label=judge_label,
        final_label=final_label,
        category=str(parsed.get("category", ""))[:40],
        confidence=float(parsed.get("confidence", 0.0) or 0.0),
        reason=str(parsed.get("reason", ""))[:120],
        guard_override=guard_override,
    )
    return rec


# ──────────────────────────────────────────────────────────────────────────────
# Rapport
# ──────────────────────────────────────────────────────────────────────────────

def write_reports(payload: dict, stamp: str):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"utility_smoke_{stamp}.json"
    md_path = OUT_DIR / f"utility_smoke_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    s = payload["summary"]
    lines = [
        f"# Smoke filtre utilité (#3) — {stamp}",
        "",
        f"**Modèle juge** : {payload['config']['model']} (DeepInfra, open-source) | "
        f"échantillon **{s['n']}** claims (seed {payload['config']['seed']})",
        "",
        "## Mesure",
        f"- **DROP (jetable) : {s['n_drop']} = {s['pct_drop']}%**",
        f"- KEEP : {s['n_keep']} = {s['pct_keep']}%",
        f"- dont garde-fou override (juge DROP mais identifiant protégé -> KEEP) : "
        f"**{s['n_guard_override']}**",
        f"- juge DROP bruts (avant garde-fou) : {s['n_judge_drop']} = {s['pct_judge_drop']}%",
        f"- erreurs/parse-fail (forcés KEEP) : {s['n_error']}",
        "",
        f"- catégories DROP : {payload['drop_categories']}",
        f"- catégories KEEP : {payload['keep_categories']}",
        "",
        "> Extrapolation indicative sur 8530 claims : "
        f"~{round(s['pct_drop'] / 100 * 8530)} claims jetables.",
        "",
    ]

    drops = [r for r in payload["records"] if r["final_label"] == "DROP"]
    keeps = [r for r in payload["records"] if r["final_label"] == "KEEP"]
    overrides = [r for r in payload["records"] if r["guard_override"]]

    lines.append("## Exemples DROP (jetables)")
    for r in drops[:20]:
        lines.append(f"- [{r['category']} {r['confidence']:.2f}] « {r['text'][:150]} »")
    lines.append("")
    lines.append("## Exemples KEEP (utiles)")
    for r in keeps[:12]:
        lines.append(f"- [{r['category']} {r['confidence']:.2f}] « {r['text'][:150]} »")
    lines.append("")
    if overrides:
        lines.append("## Garde-fou : DROP du juge bloqués par identifiant")
        for r in overrides[:12]:
            lines.append(f"- ids={r['protected_ids']} | « {r['text'][:140]} »")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke filtre utilité (read-only)")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--sample", type=int, default=150)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger.info("Échantillon %d claims (seed %d)...", args.sample, args.seed)
    claims = load_sample(args.tenant_id, args.sample, args.seed)
    logger.info("Chargés : %d", len(claims))
    if not claims:
        logger.error("Aucun claim — abandon.")
        return

    client = make_client()
    logger.info("Juge : %s (concurrence %d)", MODEL, args.workers)

    records: List[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(judge_one, client, c): c for c in claims}
        for n, fut in enumerate(as_completed(futs), 1):
            records.append(fut.result())
            if n % 25 == 0:
                logger.info("  %d/%d (%.0fs)", n, len(claims), time.time() - t0)

    n = len(records)
    n_judge_drop = sum(1 for r in records if r["judge_label"] == "DROP")
    n_guard_override = sum(1 for r in records if r["guard_override"])
    n_drop = sum(1 for r in records if r["final_label"] == "DROP")
    n_keep = n - n_drop
    n_error = sum(1 for r in records if r["judge_label"] in ("ERROR", "PARSE_FAIL"))

    drop_cats = Counter(r["category"] for r in records if r["final_label"] == "DROP")
    keep_cats = Counter(r["category"] for r in records if r["final_label"] == "KEEP")

    payload = {
        "generated_at": stamp,
        "config": {"model": MODEL, "sample": args.sample, "seed": args.seed,
                   "tenant_id": args.tenant_id},
        "summary": {
            "n": n,
            "n_drop": n_drop, "pct_drop": round(100 * n_drop / n, 1),
            "n_keep": n_keep, "pct_keep": round(100 * n_keep / n, 1),
            "n_judge_drop": n_judge_drop, "pct_judge_drop": round(100 * n_judge_drop / n, 1),
            "n_guard_override": n_guard_override,
            "n_error": n_error,
            "elapsed_s": round(time.time() - t0, 1),
        },
        "drop_categories": dict(drop_cats.most_common()),
        "keep_categories": dict(keep_cats.most_common()),
        "records": records,
    }

    json_path, md_path = write_reports(payload, stamp)
    s = payload["summary"]
    logger.info("=" * 60)
    logger.info("DROP (jetable) : %d/%d = %.1f%% | garde-fou override : %d | erreurs : %d",
                s["n_drop"], n, s["pct_drop"], s["n_guard_override"], s["n_error"])
    logger.info("Rapport JSON : %s", json_path)
    logger.info("Rapport MD   : %s", md_path)


if __name__ == "__main__":
    main()
