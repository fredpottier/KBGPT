"""Audit 200 claims NULL subject_canonical — catégorisation a/b/c/d.

Vise à trancher empiriquement : 'un claim doit-il avoir un subject_canonical
par nature, ou est-ce normal d'en avoir sans ?' (cf échange 22/05/2026).

Sampling stratifié proportionnel par claim_type :
- FACTUAL ~174 (87%)
- PRESCRIPTIVE ~18 (9%)
- DEFINITIONAL ~7 (3.5%)
- PERMISSIVE/PROCEDURAL/CONDITIONAL ~1

Classification par Qwen2.5-14B-AWQ (vLLM burst) :
- a) Subject extractible — sujet clairement identifiable
- b) Subject contextuel/anaphorique — pronom, nécessite contexte
- c) Multi-sujets — plusieurs entités simultanées
- d) Pas de subject naturel — fragment, descriptif sans assertion subject

Output : JSON détaillé + résumé stats.

Usage:
    docker exec knowbase-app sh -c 'cd /app && python scripts/audit_null_subject_canonical.py'
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("audit_null_subject")


SAMPLING_PLAN = {
    "FACTUAL": 174,
    "PRESCRIPTIVE": 18,
    "DEFINITIONAL": 7,
    "PERMISSIVE": 1,
    # PROCEDURAL=4 et CONDITIONAL=2 : on prend ce qu'il y a
    "PROCEDURAL": 0,
    "CONDITIONAL": 0,
}


CLASSIFY_PROMPT = """You are auditing claims extracted from documents to determine if each claim has an identifiable subject.

Categorize the claim into exactly ONE of:
- "a" — Subject extractible: the claim has a clearly identifiable subject (an entity, concept, or product) that can be named in a few words
- "b" — Subject contextual/anaphoric: the subject uses pronouns ("it", "they", "these") or requires surrounding context to resolve
- "c" — Multi-subjects: the claim asserts something about 2+ entities simultaneously (e.g., "A and B both support X")
- "d" — No natural subject: fragment, abstract enumeration, descriptive phrase without a clear assertion-subject

If category is "a", also extract the subject (the canonical name you would use).

OUTPUT JSON ONLY:
{"category": "a"|"b"|"c"|"d", "subject": "<name>"|null, "reasoning": "<one short sentence>"}

Claim text:"""


def classify_claim(text: str, llm_complete) -> Dict[str, Any]:
    """Appelle LLM pour classer un claim. Retourne dict avec catégorie."""
    try:
        raw = llm_complete(text)
        # Strip markdown fences
        stripped = raw.strip()
        if stripped.startswith("```"):
            import re
            m = re.search(r"```(?:json)?\s*(.+?)\s*```", stripped, re.DOTALL)
            if m:
                stripped = m.group(1).strip()
        parsed = json.loads(stripped)
        cat = parsed.get("category", "?")
        if cat not in {"a", "b", "c", "d"}:
            cat = "?"
        return {
            "category": cat,
            "subject": parsed.get("subject"),
            "reasoning": parsed.get("reasoning", "")[:200],
        }
    except Exception as exc:
        return {
            "category": "ERROR",
            "subject": None,
            "reasoning": f"LLM_error: {str(exc)[:100]}",
        }


def make_llm_caller():
    from knowbase.common.llm_router import LLMRouter, TaskType
    router = LLMRouter()
    def _complete(claim_text: str) -> str:
        return router.complete(
            task_type=TaskType.FAST_CLASSIFICATION,
            messages=[
                {"role": "system", "content": CLASSIFY_PROMPT},
                {"role": "user", "content": claim_text[:1500]},
            ],
            temperature=0.0,
            max_tokens=200,
        )
    return _complete


def sample_claims(neo4j, claim_type: str, n: int) -> List[Dict[str, Any]]:
    if n == 0:
        return []
    rows = neo4j.execute_query(
        """
        MATCH (c:Claim {tenant_id: $tid})
        WHERE c.subject_canonical IS NULL AND c.claim_type = $ct
        WITH c, rand() AS r
        ORDER BY r
        LIMIT $n
        RETURN c.claim_id AS claim_id,
               c.claim_type AS claim_type,
               coalesce(c.text, c.verbatim_quote, '') AS text
        """,
        tid="default",
        ct=claim_type,
        n=n,
    )
    return rows


def main():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    neo = get_neo4j_client()
    llm = make_llm_caller()

    print("\n" + "=" * 80)
    print("AUDIT 200 CLAIMS NULL subject_canonical (catégorisation a/b/c/d)")
    print("=" * 80)

    all_samples: List[Dict[str, Any]] = []
    for ctype, n in SAMPLING_PLAN.items():
        rows = sample_claims(neo, ctype, n)
        all_samples.extend(rows)
        print(f"  {ctype}: sampled {len(rows)} (planned {n})")

    print(f"\nTotal sampled: {len(all_samples)}")
    print(f"\nClassifying via LLM Qwen2.5-14B (vLLM burst)...")

    t0 = time.perf_counter()
    results: List[Dict[str, Any]] = []
    for i, sample in enumerate(all_samples, 1):
        classification = classify_claim(sample["text"], llm)
        results.append({**sample, **classification})
        if i % 20 == 0:
            elapsed = time.perf_counter() - t0
            eta = (elapsed / i) * (len(all_samples) - i)
            print(f"  [{i}/{len(all_samples)}] {elapsed:.0f}s elapsed, ETA {eta:.0f}s")

    total_dur = time.perf_counter() - t0

    # Aggregate
    from collections import Counter
    cat_counter = Counter(r["category"] for r in results)
    cat_by_type: Dict[str, Counter] = {}
    for r in results:
        cat_by_type.setdefault(r["claim_type"], Counter())[r["category"]] += 1

    print("\n" + "=" * 80)
    print("RÉSULTATS")
    print("=" * 80)
    print(f"\nDistribution globale (n={len(results)}, durée={total_dur:.0f}s):")
    for cat in ["a", "b", "c", "d", "?", "ERROR"]:
        n = cat_counter.get(cat, 0)
        pct = (n / len(results) * 100) if results else 0
        label = {
            "a": "Subject extractible",
            "b": "Subject contextuel/anaphorique",
            "c": "Multi-sujets",
            "d": "Pas de subject naturel",
            "?": "Catégorie invalide",
            "ERROR": "LLM error",
        }[cat]
        print(f"  {cat}) {label:35s} n={n:3d}  {pct:5.1f}%")

    print("\nPar claim_type:")
    for ctype, counter in cat_by_type.items():
        total = sum(counter.values())
        print(f"  {ctype} (n={total}):")
        for cat in ["a", "b", "c", "d"]:
            n = counter.get(cat, 0)
            pct = (n / total * 100) if total else 0
            print(f"    {cat}) {n:3d}  {pct:5.1f}%")

    # Persist
    out_dir = Path("/app/data/benchmark/null_subject_audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"audit_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "n_total": len(results),
            "duration_s": total_dur,
            "distribution_global": dict(cat_counter),
            "distribution_by_type": {k: dict(v) for k, v in cat_by_type.items()},
            "samples": results,
        }, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nDétails : {out_file}")

    # Sample qualitatif : 3 cas par catégorie pour audit manuel rapide
    print("\n" + "=" * 80)
    print("ÉCHANTILLON QUALITATIF (3 cas par catégorie pour validation manuelle)")
    print("=" * 80)
    for cat in ["a", "b", "c", "d"]:
        cat_samples = [r for r in results if r["category"] == cat][:3]
        print(f"\n--- Catégorie {cat} ({len(cat_samples)} affichés / total {cat_counter.get(cat,0)}) ---")
        for r in cat_samples:
            txt = r["text"][:200].replace("\n", " ")
            subj = r.get("subject") or "—"
            print(f"  [{r['claim_id'][:20]}] {r['claim_type']}")
            print(f"    text: {txt!r}")
            print(f"    subject extracted: {subj!r}")
            print(f"    reasoning: {r['reasoning']!r}")


if __name__ == "__main__":
    main()
