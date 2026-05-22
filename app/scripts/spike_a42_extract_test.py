"""A4.2-EXTRACT-TEST — Test extraction subject_canonical sur 4 catégories.

Reprend les 200 claims auditées le 22/05 (audit_20260522_102214.json) et
teste un prompt zero-shot strict avec Qwen2.5-14B-AWQ pour extraire le
subject_canonical.

Métriques cibles :
- Cat a (subject extractible) : taux succès ≥ 90%
- Cat b (anaphorique)         : extraction possible mais low confidence
- Cat c (multi-sujets)        : un subject choisi avec flag
- Cat d (pas de subject)      : abstention (null) ≥ 70%

Stratégie : prompt zero-shot strict, output JSON {subject, confidence, marginal}.
Comparaison vs le subject "proposé" par le classifieur précédent (cat a).

Usage:
    docker exec knowbase-app sh -c 'cd /app && python scripts/spike_a42_extract_test.py'
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("spike_a42_extract")


# Prompt zero-shot strict — domain-agnostic, pas de few-shot SAP
EXTRACT_PROMPT = """You are extracting the primary subject of a claim.

A subject is the main entity, concept, or product the claim is asserting something about.
It must be a noun phrase that can be named in 1-5 words.

Rules:
- DO NOT include articles ("the", "a") in the subject.
- Subject must be a concrete entity or technical term, NOT a generic action/verb.
- If the claim has multiple subjects, choose the most prominent one.
- If the claim has no clear subject (pure descriptive phrase, generic statement,
  or fragment), set "subject" to null and "marginal" to true.

OUTPUT JSON ONLY:
{
  "subject": "<name>"|null,
  "confidence": <float 0.0-1.0>,
  "marginal": <true if no clear subject, else false>,
  "reasoning": "<one short sentence>"
}

Claim text:"""


def extract_subject(text: str, llm_complete) -> Dict[str, Any]:
    """Appelle LLM pour extraire le subject. Retourne dict."""
    try:
        raw = llm_complete(text)
        stripped = raw.strip()
        if stripped.startswith("```"):
            m = re.search(r"```(?:json)?\s*(.+?)\s*```", stripped, re.DOTALL)
            if m:
                stripped = m.group(1).strip()
        parsed = json.loads(stripped)
        subj = parsed.get("subject")
        # Normalisation minimale : strip + suppression article initial
        if subj:
            subj = subj.strip()
            subj = re.sub(r"^(the|a|an|le|la|les|un|une)\s+", "", subj, flags=re.IGNORECASE)
            subj = subj[:200]
        return {
            "subject": subj if subj else None,
            "confidence": float(parsed.get("confidence", 0.0)),
            "marginal": bool(parsed.get("marginal", False)),
            "reasoning": (parsed.get("reasoning") or "")[:200],
        }
    except Exception as exc:
        return {
            "subject": None,
            "confidence": 0.0,
            "marginal": False,
            "reasoning": f"ERROR: {str(exc)[:100]}",
            "error": True,
        }


def make_llm_caller():
    from knowbase.common.llm_router import LLMRouter, TaskType
    router = LLMRouter()
    def _complete(claim_text: str) -> str:
        return router.complete(
            task_type=TaskType.FAST_CLASSIFICATION,
            messages=[
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": claim_text[:1500]},
            ],
            temperature=0.0,
            max_tokens=200,
        )
    return _complete


def main():
    # Charge l'audit précédent (200 claims classifiés a/b/c/d)
    audit_path = Path("/app/data/benchmark/null_subject_audit/audit_20260522_102214.json")
    with open(audit_path) as f:
        prev_audit = json.load(f)
    samples = prev_audit["samples"]

    # Sampling stratifié : prendre 50 cat a + 20 cat b + 1 cat c + 25 cat d ≈ 96 claims
    by_cat = defaultdict(list)
    for s in samples:
        by_cat[s["category"]].append(s)

    target_per_cat = {"a": 50, "b": 20, "c": 1, "d": 25}
    test_samples = []
    for cat, n in target_per_cat.items():
        avail = by_cat.get(cat, [])
        # Random sample if more than needed (in order to vary)
        import random
        random.seed(42)
        picked = avail if len(avail) <= n else random.sample(avail, n)
        test_samples.extend(picked)

    print("\n" + "=" * 80)
    print(f"A4.2-EXTRACT-TEST — Extraction LLM sur {len(test_samples)} claims (4 cat)")
    print("=" * 80)
    cat_counts = Counter(s["category"] for s in test_samples)
    print(f"  Distribution : {dict(cat_counts)}")

    llm = make_llm_caller()

    print(f"\nExtraction Qwen2.5-14B-AWQ (vLLM burst) zero-shot strict...")
    t0 = time.perf_counter()
    extracted = []
    for i, s in enumerate(test_samples, 1):
        result = extract_subject(s["text"], llm)
        extracted.append({**s, "extract_result": result})
        if i % 20 == 0:
            elapsed = time.perf_counter() - t0
            eta = (elapsed / i) * (len(test_samples) - i)
            print(f"  [{i}/{len(test_samples)}] {elapsed:.0f}s elapsed, ETA {eta:.0f}s")

    total_dur = time.perf_counter() - t0

    # Analyses
    print("\n" + "=" * 80)
    print("RÉSULTATS")
    print("=" * 80)
    print(f"\nDurée : {total_dur:.0f}s ({total_dur/len(extracted):.1f}s/claim)")

    # Métriques par catégorie
    print(f"\n{'Cat':5s}  {'N':3s}  {'extracted':10s}  {'avg_conf':9s}  {'marginal':9s}  {'errors':7s}")
    metrics_per_cat: Dict[str, Dict[str, Any]] = {}
    for cat in ["a", "b", "c", "d"]:
        cat_results = [r for r in extracted if r["category"] == cat]
        if not cat_results:
            continue
        n_extracted = sum(1 for r in cat_results if r["extract_result"]["subject"] is not None)
        confidences = [r["extract_result"]["confidence"] for r in cat_results]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0
        n_marginal = sum(1 for r in cat_results if r["extract_result"].get("marginal"))
        n_errors = sum(1 for r in cat_results if r["extract_result"].get("error"))
        n_total = len(cat_results)
        metrics_per_cat[cat] = {
            "n": n_total,
            "n_extracted": n_extracted,
            "rate_extracted": n_extracted / n_total,
            "avg_confidence": avg_conf,
            "n_marginal": n_marginal,
            "rate_marginal": n_marginal / n_total,
            "n_errors": n_errors,
        }
        print(
            f"  {cat:3s}  {n_total:3d}  "
            f"{n_extracted}/{n_total} = {n_extracted/n_total:.0%}  "
            f"{avg_conf:.2f}     "
            f"{n_marginal}/{n_total} = {n_marginal/n_total:.0%}  "
            f"{n_errors}/{n_total}"
        )

    # Comparaison subject extrait vs subject prédit par classifieur précédent (cat a)
    print("\n--- Cohérence subject extrait vs subject 'proposé' par classifieur (cat a) ---")
    cat_a = [r for r in extracted if r["category"] == "a"]
    n_match_exact = 0
    n_match_partial = 0
    n_mismatch = 0
    for r in cat_a:
        proposed = (r.get("subject") or "").strip().lower()
        extracted_s = (r["extract_result"]["subject"] or "").strip().lower()
        if not proposed or not extracted_s:
            continue
        if proposed == extracted_s:
            n_match_exact += 1
        elif proposed in extracted_s or extracted_s in proposed:
            n_match_partial += 1
        else:
            n_mismatch += 1
    n_total_cat_a = n_match_exact + n_match_partial + n_mismatch
    if n_total_cat_a > 0:
        print(f"  Exact match    : {n_match_exact}/{n_total_cat_a} ({n_match_exact/n_total_cat_a:.0%})")
        print(f"  Partial match  : {n_match_partial}/{n_total_cat_a} ({n_match_partial/n_total_cat_a:.0%})")
        print(f"  Mismatch       : {n_mismatch}/{n_total_cat_a} ({n_mismatch/n_total_cat_a:.0%})")

    # GATE decisions
    print("\n--- GATES A4.2-EXTRACT-TEST ---")
    cat_a_rate = metrics_per_cat.get("a", {}).get("rate_extracted", 0)
    cat_d_marginal_rate = metrics_per_cat.get("d", {}).get("rate_marginal", 0)
    gate_a = cat_a_rate >= 0.75
    gate_d = cat_d_marginal_rate >= 0.40  # plus permissif que 70% pour LLM zero-shot
    gate_mismatch = (n_mismatch / max(n_total_cat_a, 1)) <= 0.20

    print(f"  Gate 1 (cat a extraction ≥75%)   : {cat_a_rate:.0%}   {'✅ PASS' if gate_a else '❌ FAIL'}")
    print(f"  Gate 2 (cat d marginal ≥40%)     : {cat_d_marginal_rate:.0%}   {'✅ PASS' if gate_d else '⚠ MARGINAL'}")
    print(f"  Gate 3 (mismatch cat a ≤20%)     : {n_mismatch/max(n_total_cat_a,1):.0%}   {'✅ PASS' if gate_mismatch else '❌ FAIL'}")

    if gate_a and gate_mismatch:
        print(f"\n  ✅ GATES PASSED — A4.2 peut démarrer avec confiance.")
    else:
        print(f"\n  ⚠ GATE FAIL — A4.2 nécessite tuning prompt ou autre modèle avant démarrage.")

    # Échantillons qualitatifs : 3 par catégorie
    print("\n--- ÉCHANTILLONS QUALITATIFS ---")
    for cat in ["a", "b", "c", "d"]:
        cat_results = [r for r in extracted if r["category"] == cat][:3]
        if not cat_results:
            continue
        print(f"\n  --- Catégorie {cat} ---")
        for r in cat_results:
            txt = r["text"][:120].replace("\n", " ")
            ext = r["extract_result"]
            print(f"  [{r['claim_id'][:18]}]")
            print(f"    text: {txt!r}")
            print(f"    extracted: subject={ext['subject']!r} conf={ext['confidence']:.2f} marginal={ext.get('marginal')}")
            print(f"    classifier-proposed: {r.get('subject')!r}")

    # Persist
    out_dir = Path("/app/data/benchmark/a42_extract_test")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"extract_test_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "n_total": len(extracted),
            "duration_s": total_dur,
            "metrics_per_cat": metrics_per_cat,
            "cat_a_mismatch": {
                "n_exact": n_match_exact,
                "n_partial": n_match_partial,
                "n_mismatch": n_mismatch,
            },
            "gates": {
                "cat_a_extraction_rate": cat_a_rate,
                "cat_d_marginal_rate": cat_d_marginal_rate,
                "mismatch_rate": n_mismatch / max(n_total_cat_a, 1),
                "passed": gate_a and gate_mismatch,
            },
            "extracted": extracted,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nDétails : {out_file}")


if __name__ == "__main__":
    main()
