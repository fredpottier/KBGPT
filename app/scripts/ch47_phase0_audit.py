"""
CH-47 Phase 0 — Audit régression V3 → V4 + extraction candidats Mock R3.

Charge les 2 fichiers Robust (V3_S0_BASELINE et V4_CH46_POSTOPT), croise par question_id,
calcule delta = V3 - V4, filtre les régressions fortes (delta ≥ 0.3) sur catégories cibles
(causal_why, multi_hop, hypothetical, lifecycle_supersedes, conditional).

Pour chaque échec V4, pré-classifie le composant fautif via heuristiques sur metadata.

Output :
  - data/audit/ch47_audit_30q.json (audit complet 30q stratifié)
  - data/audit/ch47_mock_r3_top5.json (top 5 deltas pour mock manuel)
  - Markdown report sur stdout
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

V3_PATH = Path("/app/data/benchmark/results/robustness_run_20260505_163544_V3_S0_BASELINE.json")
V4_PATH = Path("/app/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json")

# Catégories cibles (régression > 20pp vs V3)
TARGET_CATEGORIES = {
    "causal_why": 8,
    "multi_hop": 8,
    "hypothetical": 6,
    "lifecycle_supersedes": 4,
    "conditional": 4,
}


def load_samples(path: Path) -> dict[str, dict]:
    """Charge per_sample indexé par question_id."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for s in data.get("per_sample", []):
        qid = s.get("question_id")
        if qid:
            out[qid] = s
    return out


def classify_failure(v4_sample: dict, v3_sample: dict, v3_score: float, v4_score: float) -> dict:
    """Pré-classifie le composant fautif via heuristiques sur metadata V4.

    Returns : {primary_suspect: str, secondary_suspect: str, reasons: list[str]}
    """
    suspects = []
    reasons = []

    ev = v4_sample.get("evaluation", {})
    v4_meta = v4_sample.get("v4_meta") or {}
    v4_answer = v4_sample.get("answer") or ""
    v3_answer = v3_sample.get("answer") or ""
    decision = v4_meta.get("decision") or ""
    regenerated = v4_meta.get("regenerated", False)
    faithfulness = v4_meta.get("faithfulness_score")
    sm = v4_sample.get("structured_metrics") or {}

    # (e) SelfCorrector retry — si regen=True et le retry n'a pas amélioré
    if regenerated:
        suspects.append("e_selfcorrector_retry")
        reasons.append(f"regenerated=True (retry triggé, peut avoir cassé la version initiale)")

    # (c) Verifier Channel 1 over-strict — ABSTAIN alors que V3 répondait
    if decision == "ABSTAIN" and v3_answer and "not found" not in v3_answer.lower() and "n'a pas été trouv" not in v3_answer.lower():
        suspects.append("c_verifier_too_strict")
        reasons.append(f"V4 ABSTAIN mais V3 répondait")

    # (b) Composer refuse de synthétiser — réponse très courte ou template
    answer_len = len(v4_answer)
    v3_len = len(v3_answer)
    if answer_len > 0 and v3_len > 0 and answer_len < v3_len * 0.4:
        suspects.append("b_composer_short")
        reasons.append(f"V4 answer très courte ({answer_len} chars vs V3 {v3_len})")

    # (h) Reasoning step manquant — réponse contient les facts mais pas le lien causal
    # Heuristique : si V3 contient des connecteurs causaux ("car", "donc", "parce que", "because", "therefore")
    # et V4 n'en contient pas → reasoning manquant
    causal_connectors_v3 = sum(1 for w in ["car ", "donc ", "parce que", "because", "therefore", "hence", "thus", "ainsi"]
                               if w in v3_answer.lower())
    causal_connectors_v4 = sum(1 for w in ["car ", "donc ", "parce que", "because", "therefore", "hence", "thus", "ainsi"]
                               if w in v4_answer.lower())
    if causal_connectors_v3 >= 2 and causal_connectors_v4 == 0 and len(v4_answer) > 50:
        suspects.append("h_reasoning_missing")
        reasons.append(f"V3 a {causal_connectors_v3} connecteurs causaux, V4 n'en a aucun")

    # (d) Channel 2 NLI rejette — faithfulness=0 mais réponse non vide
    if faithfulness is not None and faithfulness == 0.0 and len(v4_answer) > 30 and decision == "ANSWER":
        suspects.append("d_nli_rejected")
        reasons.append(f"faithfulness=0 mais ANSWER (NLI a rejeté)")

    # (a) Structurer extraction — exact_match très bas mais V3 répondait
    em_obj = sm.get("exact_match") if sm else None
    em = em_obj.get("score") if isinstance(em_obj, dict) else None
    if em is not None and em < 0.3 and v3_score > 0.6:
        suspects.append("a_structurer_extraction")
        reasons.append(f"exact_match={em} vs V3_score={v3_score} (V3 trouvait, V4 manque)")

    # (f) Retrieval manque evidence — n_chunks_retrieved = 0
    n_chunks = v4_meta.get("n_chunks_retrieved", -1)
    if n_chunks == 0:
        suspects.append("f_retrieval_empty")
        reasons.append(f"n_chunks_retrieved=0")

    # Si rien détecté
    if not suspects:
        suspects.append("unknown")
        reasons.append("aucune signature claire")

    return {
        "primary_suspect": suspects[0],
        "all_suspects": suspects,
        "reasons": reasons,
    }


def main():
    v3 = load_samples(V3_PATH)
    v4 = load_samples(V4_PATH)
    print(f"V3 samples: {len(v3)}")
    print(f"V4 samples: {len(v4)}")
    print(f"Common: {len(set(v3.keys()) & set(v4.keys()))}")

    # Croiser
    deltas = []
    for qid, v4s in v4.items():
        if qid not in v3:
            continue
        v3s = v3[qid]
        v3_score = v3s.get("evaluation", {}).get("score")
        v4_score = v4s.get("evaluation", {}).get("score")
        if v3_score is None or v4_score is None:
            continue
        delta = v3_score - v4_score
        cat = v3s.get("evaluation", {}).get("category", "unknown")
        deltas.append({
            "question_id": qid,
            "category": cat,
            "v3_score": v3_score,
            "v4_score": v4_score,
            "delta": delta,
        })

    # Tri par delta décroissant
    deltas.sort(key=lambda x: -x["delta"])

    # Stratification sur catégories cibles
    by_cat = defaultdict(list)
    for d in deltas:
        if d["category"] in TARGET_CATEGORIES and d["delta"] > 0.2:
            by_cat[d["category"]].append(d)

    selected = []
    for cat, n_target in TARGET_CATEGORIES.items():
        candidates = sorted(by_cat[cat], key=lambda x: -x["delta"])[:n_target]
        selected.extend(candidates)

    print(f"\nSélection : {len(selected)} questions sur {len(TARGET_CATEGORIES)} catégories\n")

    # Enrichir avec metadata + classification
    audit_full = []
    for d in selected:
        qid = d["question_id"]
        v3s, v4s = v3[qid], v4[qid]
        cls = classify_failure(v4s, v3s, d["v3_score"], d["v4_score"])
        item = {
            **d,
            "question": v4s.get("question", "")[:300],
            "v3_answer_preview": (v3s.get("answer") or "")[:400],
            "v4_answer_preview": (v4s.get("answer") or "")[:400],
            "v4_decision": (v4s.get("v4_meta") or {}).get("decision"),
            "v4_regenerated": (v4s.get("v4_meta") or {}).get("regenerated"),
            "v4_faithfulness": (v4s.get("v4_meta") or {}).get("faithfulness_score"),
            "v4_chunks_retrieved": (v4s.get("v4_meta") or {}).get("n_chunks_retrieved"),
            "structured_metrics": v4s.get("structured_metrics") or {},
            "classification": cls,
        }
        audit_full.append(item)

    # Stats par suspect
    suspect_counts = defaultdict(int)
    for item in audit_full:
        suspect_counts[item["classification"]["primary_suspect"]] += 1

    print("=== STATS PAR COMPOSANT FAUTIF (heuristique) ===")
    for s, c in sorted(suspect_counts.items(), key=lambda x: -x[1]):
        pct = c / len(audit_full) * 100
        print(f"  {s}: {c}/{len(audit_full)} ({pct:.0f}%)")

    print("\n=== STATS PAR CATÉGORIE ===")
    for cat in TARGET_CATEGORIES:
        items_cat = [x for x in audit_full if x["category"] == cat]
        if items_cat:
            avg_delta = sum(x["delta"] for x in items_cat) / len(items_cat)
            print(f"  {cat}: n={len(items_cat)}, mean_delta={avg_delta:.3f}")

    # Top 5 deltas absolus pour mock R3
    top5 = sorted(audit_full, key=lambda x: -x["delta"])[:5]
    print(f"\n=== TOP 5 (mock R3 manuel) ===")
    for i, item in enumerate(top5, 1):
        print(f"\n[{i}] {item['question_id']} ({item['category']}) Δ={item['delta']:.3f}")
        print(f"    Q: {item['question'][:150]}")
        print(f"    V3 ({item['v3_score']:.2f}): {item['v3_answer_preview'][:200]}")
        print(f"    V4 ({item['v4_score']:.2f}): {item['v4_answer_preview'][:200]}")
        print(f"    Suspects: {item['classification']['primary_suspect']}")
        for r in item['classification']['reasons'][:2]:
            print(f"      - {r}")

    # Persist
    out_dir = Path("/app/data/audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_path = out_dir / "ch47_audit_30q.json"
    audit_path.write_text(json.dumps(audit_full, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted full audit → {audit_path}")

    mock_path = out_dir / "ch47_mock_r3_top5.json"
    # Pour mock R3, on a besoin de plus de détail : facts_first du V4, ground_truth
    mock_data = []
    for item in top5:
        qid = item["question_id"]
        v3s, v4s = v3[qid], v4[qid]
        gt = v4s.get("ground_truth") or v3s.get("ground_truth") or {}
        mock_data.append({
            "question_id": qid,
            "category": item["category"],
            "delta": item["delta"],
            "question": v4s.get("question", ""),
            "ground_truth": gt,
            "v3_answer_full": v3s.get("answer", ""),
            "v3_score": item["v3_score"],
            "v4_answer_full": v4s.get("answer", ""),
            "v4_score": item["v4_score"],
            "v4_decision": item["v4_decision"],
            "v4_chunks_retrieved": item["v4_chunks_retrieved"],
            "v4_facts_first": (v4s.get("v4_meta") or {}).get("facts_first"),
            "v4_classification": item["classification"],
            "structured_metrics": item["structured_metrics"],
        })
    mock_path.write_text(json.dumps(mock_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Persisted mock R3 candidates → {mock_path}")


if __name__ == "__main__":
    main()
