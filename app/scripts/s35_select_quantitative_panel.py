"""S3.5 — Sélection panel 10q quantitatives pour mini-POC.

ADR V1.5 §3d : Gate dur. 10 questions quantitatives échouées par V5 POC →
mesurer V5 + 5 tools quantitatifs vs V5 POC sans tools. Gain ≥15pp requis
sinon revoir extraction tables avant industrialisation full.

Sources candidates :
1. gold_set_sap_v2.json — primary_type='quantitative' (3 questions actuelles)
2. gold_set_sap_v2.json — questions dont ground_truth contient un pattern numérique
   + unité (universal patterns, charte domain-agnostic)
3. Backup SAP benchmark — extension si <10 candidates

Critères de sélection (domain-agnostic) :
- Réponse contient un nombre suivi d'une unité OU pourcentage OU comparaison numérique
- Question pose "how much", "what rate", "combien", "quel taux", "what's the X value"
- Exclure les questions où la réponse est juste oui/non sans valeur

Output :
- benchmark/questions/quantitative_panel_10q.json — panel à utiliser
- doc/ongoing/S3.5_PANEL_SELECTION.md — explication + scores attendus

Usage :
    docker exec knowbase-app python scripts/s35_select_quantitative_panel.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

# Patterns universels de signature quantitative (charte domain-agnostic)
# 1) Nombre + unité (espace ou collé) : "500 GB", "4h", "15%", "2.5 ms"
_QUANT_NUM_UNIT = re.compile(
    r"\b(\d{1,4}(?:[.,]\d+)?)\s?"
    r"(?:%|"
    r"hour|hours|hr|hrs|min|mins|minute|minutes|sec|secs|second|seconds|"
    r"ms|µs|ns|day|days|week|weeks|month|months|year|years|"
    r"gb|tb|mb|kb|byte|bytes|giga|tera|kilo|mega|"
    r"euros?|eur|usd|dollars?|"
    r"\$|€|£|"
    r"users?|nodes?|requests?|transactions?|sessions?"
    r")\b",
    re.IGNORECASE,
)

# 2) Question containing quantitative interrogation
_QUANT_QUESTION_WORDS = re.compile(
    r"\b(how\s+(?:much|many|long|fast|often)|"
    r"what(?:'s|\s+is)\s+the\s+(?:rate|amount|number|size|duration|cost|frequency|"
    r"value|percentage|delay|latency|throughput)|"
    r"combien|quel(?:le)?\s+(?:taux|nombre|montant|durée|fréquence|valeur|"
    r"pourcentage|délai|latence|débit)|"
    r"wie\s+(?:viel|lange|oft)|"
    r"cuánt[oa]s?)\b",
    re.IGNORECASE,
)


def has_quantitative_signal(question: str, answer: str) -> tuple[bool, list[str]]:
    """Retourne (is_quantitative, reasons[])."""
    reasons = []
    # Question pattern
    if _QUANT_QUESTION_WORDS.search(question or ""):
        reasons.append("question_words")
    # Answer contains number + unit
    if _QUANT_NUM_UNIT.search(answer or ""):
        reasons.append("answer_num_unit")
    # Answer contains percentage standalone
    if re.search(r"\b\d+(?:\.\d+)?\s*%", answer or ""):
        reasons.append("answer_percent")
    return (len(reasons) > 0, reasons)


def get_ground_truth_text(q: dict) -> str:
    """Extrait la réponse de référence depuis divers schémas gold_set."""
    if isinstance(q.get("ground_truth"), dict):
        gt = q["ground_truth"]
        return gt.get("answer") or gt.get("text") or ""
    return q.get("ground_truth_text") or q.get("expected_answer") or q.get("answer") or ""


def select_panel(
    source: Path,
    target_size: int = 10,
    min_quantitative_signal_count: int = 1,
) -> dict:
    """Sélectionne `target_size` questions quantitatives.

    Returns:
        {"selected": [...], "rejected_count": int, "stats": {...}}
    """
    data = json.loads(source.read_text(encoding="utf-8"))
    questions = data if isinstance(data, list) else data.get("questions", [])

    candidates = []
    rejected = 0
    for q in questions:
        question_text = q.get("question") or q.get("query") or ""
        answer_text = get_ground_truth_text(q)
        primary_type = (q.get("primary_type") or q.get("type") or "").lower()

        is_quant, reasons = has_quantitative_signal(question_text, answer_text)

        # Critère :
        # - primary_type='quantitative' → toujours candidat
        # - OU signal pattern + answer non-vide
        if primary_type == "quantitative":
            candidates.append({**q, "_select_reasons": ["primary_type"] + reasons, "_score": 3})
        elif is_quant and len(reasons) >= min_quantitative_signal_count and answer_text:
            candidates.append({**q, "_select_reasons": reasons, "_score": len(reasons)})
        else:
            rejected += 1

    # Sort par score (primary_type explicite > multi-signal > mono-signal)
    candidates.sort(key=lambda c: c["_score"], reverse=True)

    selected = candidates[:target_size]
    return {
        "selected": selected,
        "rejected_count": rejected,
        "total_input": len(questions),
        "candidates_count": len(candidates),
        "stats": {
            "by_primary_type": dict(Counter(
                (c.get("primary_type") or c.get("type") or "?") for c in selected
            )),
            "by_select_reason": dict(Counter(
                reason for c in selected for reason in c["_select_reasons"]
            )),
            "score_distribution": dict(Counter(c["_score"] for c in selected)),
        },
    }


def main():
    project_root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    source_v2 = project_root / "benchmark" / "questions" / "gold_set_sap_v2.json"
    source_v1 = project_root / "benchmark" / "questions" / "gold_set_sap_v1.json"
    if not source_v2.exists():
        print(f"ERROR: source not found: {source_v2}", file=sys.stderr)
        sys.exit(1)

    print(f"Source v2: {source_v2}")
    result = select_panel(source_v2, target_size=10)
    print(f"\nCandidates v2: {result['candidates_count']} / {result['total_input']}")

    # Extend with v1 if needed
    if len(result["selected"]) < 10 and source_v1.exists():
        print(f"\nExtending with v1 ({source_v1.name})...")
        result_v1 = select_panel(source_v1, target_size=10)
        already_qs = {(q.get("question") or "")[:80] for q in result["selected"]}
        for q in result_v1["selected"]:
            if len(result["selected"]) >= 10:
                break
            qkey = (q.get("question") or "")[:80]
            if qkey in already_qs:
                continue
            q["_source"] = "v1"
            result["selected"].append(q)
            already_qs.add(qkey)
        print(f"After v1 extension: {len(result['selected'])}")

    # Re-compute final stats
    selected = result["selected"]
    result["stats"] = {
        "by_primary_type": dict(Counter(
            (c.get("primary_type") or c.get("type") or "?") for c in selected
        )),
        "by_select_reason": dict(Counter(
            reason for c in selected for reason in c["_select_reasons"]
        )),
        "by_source": dict(Counter(c.get("_source", "v2") for c in selected)),
        "score_distribution": dict(Counter(c["_score"] for c in selected)),
    }
    print(f"Selected: {len(result['selected'])}")
    print(f"\nStats: {json.dumps(result['stats'], indent=2)}")

    # Persist panel
    panel_path = project_root / "benchmark" / "questions" / "quantitative_panel_10q.json"
    payload = {
        "_meta": {
            "source_primary": str(source_v2.name),
            "source_secondary": str(source_v1.name) if source_v1.exists() else None,
            "n_selected": len(result["selected"]),
            "selection_stats": result["stats"],
            "purpose": "S3.5 mini-POC quantitatif (ADR V1.5 §3d gate ≥15pp)",
        },
        "questions": result["selected"],
    }
    panel_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote panel: {panel_path}")

    # Preview
    print(f"\n─── Preview first 3 selected ───")
    for i, q in enumerate(result["selected"][:3]):
        print(f"\n[{i+1}] type={q.get('primary_type')} score={q['_score']} reasons={q['_select_reasons']}")
        print(f"     Q: {(q.get('question') or '')[:120]}...")
        gt = get_ground_truth_text(q)
        print(f"     A: {gt[:120]}...")

    if len(result["selected"]) < 10:
        print(f"\n⚠️  Only {len(result['selected'])} candidates found. Need to extend with SAP backup.")
        sys.exit(2)
    print(f"\n✅ Panel 10q ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
