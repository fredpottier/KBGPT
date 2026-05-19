"""S0.6 Diagnostic Gap EKX — analyse des questions V5 < EKX.

Identifie les 10q où V5 score < EKX, extrait les paires (question, V5 answer, EKX answer)
pour audit qualitatif des causes (retrieval / reasoning / completeness / citation / domain external).

Run : python app/scripts/s06_gap_ekx_analysis.py
Output : doc/ongoing/S0.6_GAP_EKX_ANALYSIS.md
"""
from __future__ import annotations

import json
from pathlib import Path

V5_RESULTS = Path("benchmark/results/gold_set_sap_v1_v5_judged.json")
EKX_RESULTS = Path("benchmark/results/gold_set_sap_v1_ekx_judged.json")
GOLDSET = Path("benchmark/questions/gold_set_sap_v1.json")
OUT = Path("doc/ongoing/S0.6_GAP_EKX_ANALYSIS.md")


def load_results():
    with open(V5_RESULTS, encoding="utf-8") as f:
        v5 = json.load(f)
    with open(EKX_RESULTS, encoding="utf-8") as f:
        ekx = json.load(f)
    with open(GOLDSET, encoding="utf-8") as f:
        gold = json.load(f)
    return v5, ekx, gold


def main():
    v5, ekx, gold = load_results()

    v5_by_id = {s["id"]: s for s in v5["per_sample"]}
    ekx_by_id = {s["id"]: s for s in ekx["per_sample"]}
    gold_by_id = {q["id"]: q for q in gold}

    # Identify questions where V5 < EKX
    gaps = []
    for qid, v5_sample in v5_by_id.items():
        v5_score = v5_sample["judge"].get("score", -1)
        ekx_score = ekx_by_id.get(qid, {}).get("judge", {}).get("score", -1)
        if ekx_score > v5_score:
            gaps.append(
                {
                    "id": qid,
                    "category": v5_sample.get("primary_type"),
                    "question": v5_sample.get("question"),
                    "v5_score": v5_score,
                    "ekx_score": ekx_score,
                    "delta": ekx_score - v5_score,
                    "v5_answer": v5_sample.get("osmosis_answer", ""),
                    "ekx_answer": ekx_by_id[qid].get("osmosis_answer", ""),
                    "reference_answer": gold_by_id[qid].get("ground_truth", {}).get("answer", ""),
                    "expected_identifiers": gold_by_id[qid].get("ground_truth", {}).get("exact_identifiers", []),
                    "supporting_doc_ids": gold_by_id[qid].get("ground_truth", {}).get("supporting_doc_ids", []),
                    "v5_meta": v5_sample.get("osmosis_meta", {}),
                }
            )
    gaps.sort(key=lambda x: -x["delta"])

    # Generate audit document
    lines = [
        "# S0.6 — Diagnostic Gap EKX (V5 < EKX questions)",
        "",
        "*Tâche : CH-52.1 S0.6*",
        f"*Date : 2026-05-13*",
        f"*Source : `{V5_RESULTS}` + `{EKX_RESULTS}` + `{GOLDSET}`*",
        "",
        "## Vue d'ensemble",
        "",
        f"- **{len(gaps)} questions** où V5 < EKX (sur 30 total)",
        f"- Gap moyen sur ces questions : **{sum(g['delta'] for g in gaps) / len(gaps):.3f}**",
        f"- Gap maximum : **{max(g['delta'] for g in gaps):.2f}** (question {gaps[0]['id']})",
        "",
        "## Distribution par catégorie",
        "",
    ]

    by_cat: dict[str, int] = {}
    for g in gaps:
        by_cat[g["category"]] = by_cat.get(g["category"], 0) + 1
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"- **{cat}** : {n} questions")
    lines.append("")

    lines.extend([
        "## Causes possibles (à classifier par audit ci-dessous)",
        "",
        "Selon §3j ADR V1.4 — hypothèses causales à valider :",
        "",
        "- **H1 — Qualité KG EKX** : EKX a un KG SAP mature (REFINES, QUALIFIES) plus dense",
        "- **H2 — Modèle LLM EKX** : EKX propriétaire (Anthropic Claude ou OpenAI ?), edge reasoning",
        "- **H3 — Verifier / grounding EKX** : leur citation accuracy diff (mais V5 CP = 0.43 > EKX 0.21)",
        "- **H4 — Extraction structurelle EKX** : structures sémantiques plus riches que Docling",
        "- **H5 — Coverage corpus** : EKX corpus SAP plus large, doublons/versions absents OSMOSIS",
        "",
        "Pour chaque question ci-dessous, classer la cause perçue : `retrieval` / `reasoning` / `completeness` / `citation` / `domain_external`",
        "",
        "---",
        "",
        "## Audit détaillé question par question",
        "",
    ])

    for i, g in enumerate(gaps, 1):
        v5_ans = g["v5_answer"][:1500] + ("..." if len(g["v5_answer"]) > 1500 else "")
        ekx_ans = g["ekx_answer"][:1500] + ("..." if len(g["ekx_answer"]) > 1500 else "")
        ref = g["reference_answer"][:800] + ("..." if len(g["reference_answer"]) > 800 else "")

        lines.extend([
            f"### Q{i:02d}. {g['id']} [{g['category']}] — delta +{g['delta']:.2f}",
            "",
            f"**Score V5** : {g['v5_score']:.2f} | **Score EKX** : {g['ekx_score']:.2f}",
            "",
            f"**Question** : {g['question']}",
            "",
            f"**Réponse de référence (gold-set Fred)** :",
            "",
            "```",
            ref,
            "```",
            "",
            f"**Expected identifiers** : {g['expected_identifiers']}",
            f"**Supporting doc_ids** : {g['supporting_doc_ids']}",
            "",
            f"**Réponse V5** ({g['v5_meta'].get('n_iterations', '?')} iter, {g['v5_meta'].get('tokens_total', '?')} tokens) :",
            "",
            "```",
            v5_ans,
            "```",
            "",
            f"**Réponse EKX** :",
            "",
            "```",
            ekx_ans,
            "```",
            "",
            "**Cause perçue** (à remplir par audit) : `_____` (retrieval / reasoning / completeness / citation / domain_external)",
            "",
            "**Commentaire** : _____",
            "",
            "---",
            "",
        ])

    lines.extend([
        "## Synthèse à compléter post-audit",
        "",
        "### Distribution des causes",
        "",
        "| Cause | Nb questions | % |",
        "|---|---:|---:|",
        "| retrieval (V5 n'a pas trouvé la bonne section) | — | — |",
        "| reasoning (V5 trouvé section mais raisonné incorrect) | — | — |",
        "| completeness (V5 réponse partielle/incomplète) | — | — |",
        "| citation (V5 cite mais imprécis) | — | — |",
        "| domain_external (info hors corpus OSMOSIS) | — | — |",
        "",
        "### Cause #1 et décision",
        "",
        "- Cause prédominante : ____",
        "- Action V5.1 (Phase 1 ou Phase 2) : ____",
        "- Mini-POC ciblé à exécuter sur 5 questions de la cause #1 : ____",
        "- Gate : gain ≥ 10pp post-mitigation cause #1 ?",
        "",
        "### Recommandation pour ADR V1.4 §3j",
        "",
        "- Hypothèse causale principale validée : H1 / H2 / H3 / H4 / H5",
        "- Si H2 (LLM propriétaire) : non-actionnable charte, re-prioriser cause #2",
        "- Si H1/H4 : enrichissement KG ou meilleur extracteur — possible Phase 2",
        "- Si H3 : déjà adressé par bake-off S7",
        "- Si H5 : hors scope V5, ajouter docs SAP manquants en parallèle",
        "",
    ])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ Audit document généré : {OUT}")
    print(f"  {len(gaps)} questions V5 < EKX à auditer")
    print(f"  Gap moyen : {sum(g['delta'] for g in gaps) / len(gaps):.3f}")
    print(f"  Distribution par catégorie :")
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"    {cat:18s} : {n}")


if __name__ == "__main__":
    main()
