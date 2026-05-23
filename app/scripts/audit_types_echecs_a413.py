"""A4.13 — Audit échecs par type runtime_v6 (post-bench 50q RRF).

Pour chaque type problématique (multi_hop, comparison, false_premise),
extrait du JSON bench les questions échouées avec :
- ground_truth, answer_text, judge_score, judge_reasoning
- claims cités, mode Synthesize, terminated_reason
- Eventuels claims oracle expected (par hash doc + match texte)

Output Markdown structuré pour analyse Fred.

Usage :
    docker exec knowbase-app python scripts/audit_types_echecs_a413.py
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("audit_a413")


BENCH_PATH = Path("data/benchmark/a38_runtime_v6/run_20260523_070724.json")
GOLD_SET_PATH = Path("benchmark/questions/gold_set_a38_50q.json")
OUTPUT_PATH = Path("doc/ongoing/A413_AUDIT_TYPES_ECHECS.md")

# Types à auditer (prioritaires : C1 < 0.20)
TARGET_TYPES = ["multi_hop", "comparison", "false_premise"]

# Types témoins (bonnes performances pour comparaison)
WITNESS_TYPES = ["factual", "lifecycle", "unanswerable"]

_CITATION_RE = re.compile(r"\[claim_id=([a-zA-Z0-9_]+)\]")


def load_bench() -> List[Dict[str, Any]]:
    with open(BENCH_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("results_50q") or data.get("results") or []


def load_gold_set() -> Dict[str, Dict[str, Any]]:
    with open(GOLD_SET_PATH, "r", encoding="utf-8") as f:
        gold = json.load(f)
    return {q["id"]: q for q in gold}


def extract_cited_ids(answer_text: str) -> List[str]:
    return _CITATION_RE.findall(answer_text or "")


def get_question_type(gold_q: Dict[str, Any]) -> str:
    """Récupère le primary_type d'une question gold-set."""
    return gold_q.get("primary_type", "unknown")


def get_last_iteration(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dernière iteration trace pour avoir verdict Evaluate + execute trace."""
    iterations = result.get("run", {}).get("iterations_trace", [])
    if not iterations:
        return None
    return iterations[-1]


def render_question_audit(
    result: Dict[str, Any], gold_q: Dict[str, Any], idx: int
) -> str:
    """Markdown détaillé pour une question."""
    qid = result["id"]
    primary_type = gold_q.get("primary_type", "unknown")
    question = gold_q["question"]
    gt = gold_q.get("ground_truth", {})
    gt_answer = gt.get("answer", "")
    exact_ids = gt.get("exact_identifiers", []) or []

    run = result.get("run", {})
    answer = run.get("answer_text", "")
    mode = run.get("mode", "?")
    terminated = run.get("terminated_reason", "?")
    judge_score = result.get("judge_score", 0.0)
    judge_reasoning = result.get("judge_reasoning", "")

    cited_ids = extract_cited_ids(answer)

    last_it = get_last_iteration(result)
    eval_verdict = None
    eval_reasoning = None
    n_claims_execute = 0
    if last_it:
        eo = last_it.get("evaluate_output", {})
        if isinstance(eo, dict):
            eval_verdict = eo.get("verdict")
            eval_reasoning = (eo.get("reasoning") or "")[:200]
        exec_o = last_it.get("execute_output", {})
        if isinstance(exec_o, dict):
            for r in exec_o.get("results", []):
                n_claims_execute += len(r.get("claims", []))

    out = []
    out.append(f"### #{idx} {qid} (judge={judge_score})")
    out.append(f"**Q** : {question}")
    out.append(f"**Type** : {primary_type}")
    out.append(f"**Ground truth** : {gt_answer[:300]}")
    if exact_ids:
        out.append(f"**Exact identifiers attendus** : {exact_ids}")
    out.append("")
    out.append(f"- **Mode Synthesize** : {mode}")
    out.append(f"- **Terminated reason** : {terminated}")
    out.append(f"- **Eval verdict** : {eval_verdict}")
    if eval_reasoning:
        out.append(f"- **Eval reasoning** : {eval_reasoning}")
    out.append(f"- **N claims Execute** : {n_claims_execute}")
    out.append(f"- **N claims cités** : {len(cited_ids)}")
    out.append(f"- **Judge reasoning** : {judge_reasoning[:200]}")
    out.append("")
    out.append(f"**Answer produit** :")
    out.append(f"> {answer[:500]}...")
    out.append("")
    out.append("---")
    out.append("")
    return "\n".join(out)


def main():
    logger.info("Chargement bench %s", BENCH_PATH)
    bench = load_bench()
    gold = load_gold_set()
    logger.info("  bench: %d résultats", len(bench))
    logger.info("  gold-set: %d questions", len(gold))

    # Stratifier par type + filtrer échecs/succès
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for r in bench:
        gold_q = gold.get(r["id"])
        if not gold_q:
            continue
        t = get_question_type(gold_q)
        by_type.setdefault(t, []).append(r)

    # Rapport markdown
    md = []
    md.append("# A4.13 — Audit échecs par type runtime_v6 (post-bench 50q RRF)")
    md.append("")
    md.append("**Source** : `data/benchmark/a38_runtime_v6/run_20260523_070724.json` (V6_HYBRID_RETRIEVAL=rrf, 50q stratifié)")
    md.append("")
    md.append("## ⚠️ Cadre domain-agnostic")
    md.append("OSMOSE doit fonctionner identiquement sur médical/réglementaire/aerospace. Les exemples SAP cités servent uniquement à illustrer les patterns d'échec sur le corpus de test actuel.")
    md.append("")
    md.append("## Récap performances par type (bench 50q RRF)")
    md.append("")
    md.append("| Type | N | C1 mean | Verdict |")
    md.append("|---|---|---|---|")
    for t in TARGET_TYPES + WITNESS_TYPES:
        results = by_type.get(t, [])
        if not results:
            continue
        scores = [r.get("judge_score", 0.0) for r in results]
        mean = sum(scores) / len(scores) if scores else 0
        if mean < 0.20:
            verdict = "❌ PROBLÉMATIQUE"
        elif mean < 0.50:
            verdict = "⚠ MOYEN"
        else:
            verdict = "✅ OK"
        md.append(f"| {t} | {len(results)} | {mean:.3f} | {verdict} |")
    md.append("")

    # Audit par type problématique
    for t in TARGET_TYPES:
        results = by_type.get(t, [])
        if not results:
            continue
        # Échecs : judge_score < 0.5
        failures = [r for r in results if r.get("judge_score", 0.0) < 0.5]
        successes = [r for r in results if r.get("judge_score", 0.0) >= 0.5]
        md.append(f"## 🔍 Type : `{t}` (n={len(results)}, échecs={len(failures)}, succès={len(successes)})")
        md.append("")
        # Audit ALL failures (max 5)
        md.append(f"### Échecs (top {min(5, len(failures))})")
        md.append("")
        for i, r in enumerate(failures[:5], 1):
            gold_q = gold.get(r["id"], {})
            md.append(render_question_audit(r, gold_q, i))
        # Si succès, 1 ou 2 pour comparaison
        if successes:
            md.append(f"### Succès (top {min(2, len(successes))} pour comparaison)")
            md.append("")
            for i, r in enumerate(successes[:2], 1):
                gold_q = gold.get(r["id"], {})
                md.append(render_question_audit(r, gold_q, i))
        md.append("")

    # Audit type témoin (factual = 0.333 — pas la fête mais OK)
    md.append("## 🟢 Type témoin : `factual` (échantillon)")
    md.append("")
    results = by_type.get("factual", [])
    failures = [r for r in results if r.get("judge_score", 0.0) < 0.5][:3]
    successes = [r for r in results if r.get("judge_score", 0.0) >= 0.5][:2]
    md.append("### Échecs factual (3 premiers)")
    md.append("")
    for i, r in enumerate(failures, 1):
        gold_q = gold.get(r["id"], {})
        md.append(render_question_audit(r, gold_q, i))
    md.append("### Succès factual (2 premiers)")
    md.append("")
    for i, r in enumerate(successes, 1):
        gold_q = gold.get(r["id"], {})
        md.append(render_question_audit(r, gold_q, i))

    md.append("")
    md.append("## 📋 Diagnostic à compléter manuellement")
    md.append("")
    md.append("Pour chaque type problématique, identifier le pattern principal :")
    md.append("- **A** : retrieval rate (Execute claims ne correspondent pas)")
    md.append("- **B** : Synthesize hallucine ou ignore claims")
    md.append("- **C** : Evaluate verdict trop sévère (INSUFFICIENT alors que claims existent)")
    md.append("- **D** : Architecture pipeline (multi_hop nécessite raisonnement explicite, false_premise nécessite détecteur dédié)")
    md.append("")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    logger.info("Wrote %s (%d lines)", OUTPUT_PATH, len(md))


if __name__ == "__main__":
    main()
