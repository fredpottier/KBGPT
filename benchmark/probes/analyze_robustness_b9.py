"""
Comparaison des 4 runs Robustness : PRE V17 / POST Perspective / POST_PROMPT_B8 / POST_PROMPT_B9.
Evaluation de l'efficacite du fix B9.
"""
import json
import re

PRE = "/app/data/benchmark/results/robustness_run_20260402_140940_V17_PREMISE_VERIF.json"
POST_PL = "/app/data/benchmark/results/robustness_run_20260407_131617_POST_PerspectiveLayer.json"
POST_B8 = "/app/data/benchmark/results/robustness_run_20260408_083959_POST_PROMPT_B8.json"
POST_B9 = "/app/data/benchmark/results/robustness_run_20260408_121925_POST_PROMPT_B9.json"

PATTERNS_IDK = [
    r"ne fournissent pas", r"ne contiennent pas",
    r"avertissement pr[eé]alable", r"constat pr[eé]liminaire",
    r"faible (couverture|pertinence)", r"pertinence faible",
    r"note sur la pertinence", r"ne traitent pas",
    r"absence d['e] (information|precision)",
]
RE_IDK = re.compile("|".join(f"(?:{p})" for p in PATTERNS_IDK), re.IGNORECASE)


def has_idk(t):
    return bool(t) and bool(RE_IDK.search(t))


def starts_with_meta_header(t):
    if not t:
        return False
    fl = t.lstrip().split("\n")[0].strip().lower()
    if not fl.startswith("#"):
        return False
    return any(kw in fl for kw in ["reponse", "réponse", "analyse", "synthese", "synthèse", "question", "comprendre"])


def main():
    pre = json.load(open(PRE))
    pl = json.load(open(POST_PL))
    b8 = json.load(open(POST_B8))
    b9 = json.load(open(POST_B9))

    keys = [
        "global_score", "causal_why_score", "conditional_score", "false_premise_score",
        "hypothetical_score", "multi_hop_score", "negation_score", "set_list_score",
        "synthesis_large_score", "temporal_evolution_score", "unanswerable_score",
    ]

    print(f"{'category':<24} {'PRE':>8} {'POST_PL':>9} {'POST_B8':>9} {'POST_B9':>9} {'B9vB8':>8} {'B9vPRE':>9}")
    print("-" * 80)
    critical = ("causal_why_score", "conditional_score", "temporal_evolution_score")
    for k in keys:
        p = pre["scores"].get(k, 0)
        l = pl["scores"].get(k, 0)
        a = b8["scores"].get(k, 0)
        n = b9["scores"].get(k, 0)
        delta_b8 = n - a
        delta_pre = n - p
        tag = " <--" if k in critical else ""
        print(f"{k:<24} {p:>8.4f} {l:>9.4f} {a:>9.4f} {n:>9.4f} {delta_b8:>+8.4f} {delta_pre:>+9.4f}{tag}")

    print()
    print("=" * 80)
    print("Analyse qualitative B9 — patterns 'manque info' et meta-headers")
    print("=" * 80)

    pre_by = {s["question_id"]: s for s in pre["per_sample"]}
    b8_by = {s["question_id"]: s for s in b8["per_sample"]}
    b9_by = {s["question_id"]: s for s in b9["per_sample"]}

    cats = ("causal_why", "conditional", "temporal_evolution")
    all_q = [q for q in sorted(set(pre_by) & set(b8_by) & set(b9_by))
             if pre_by[q].get("category") in cats]

    pre_idk = sum(1 for q in all_q if has_idk(pre_by[q].get("answer", "")))
    b8_idk = sum(1 for q in all_q if has_idk(b8_by[q].get("answer", "")))
    b9_idk = sum(1 for q in all_q if has_idk(b9_by[q].get("answer", "")))

    pre_mh = sum(1 for q in all_q if starts_with_meta_header(pre_by[q].get("answer", "")))
    b8_mh = sum(1 for q in all_q if starts_with_meta_header(b8_by[q].get("answer", "")))
    b9_mh = sum(1 for q in all_q if starts_with_meta_header(b9_by[q].get("answer", "")))

    print(f"\nSur {len(all_q)} questions dans les 3 categories critiques :")
    print(f"  Pattern 'manque info' : PRE={pre_idk:>3}  B8={b8_idk:>3}  B9={b9_idk:>3}")
    print(f"  Meta-header debut    : PRE={pre_mh:>3}  B8={b8_mh:>3}  B9={b9_mh:>3}")

    print()
    print("Par categorie :")
    for cat in cats:
        cat_qs = [q for q in all_q if pre_by[q].get("category") == cat]
        pre_avg = sum(pre_by[q].get("evaluation", {}).get("score", 0) for q in cat_qs) / max(len(cat_qs), 1)
        b8_avg = sum(b8_by[q].get("evaluation", {}).get("score", 0) for q in cat_qs) / max(len(cat_qs), 1)
        b9_avg = sum(b9_by[q].get("evaluation", {}).get("score", 0) for q in cat_qs) / max(len(cat_qs), 1)
        pre_idk_c = sum(1 for q in cat_qs if has_idk(pre_by[q].get("answer", "")))
        b9_idk_c = sum(1 for q in cat_qs if has_idk(b9_by[q].get("answer", "")))
        pre_mh_c = sum(1 for q in cat_qs if starts_with_meta_header(pre_by[q].get("answer", "")))
        b9_mh_c = sum(1 for q in cat_qs if starts_with_meta_header(b9_by[q].get("answer", "")))
        print(f"  {cat:<22} n={len(cat_qs):>3} | PRE={pre_avg:.3f} B8={b8_avg:.3f} B9={b9_avg:.3f}")
        print(f"    idk PRE={pre_idk_c} B9={b9_idk_c}  meta-headers PRE={pre_mh_c} B9={b9_mh_c}")

    # Sample remaining regressions in causal_why
    print()
    print("=" * 80)
    print("Regressions causal_why PERSISTANTES (score B9 < 0.7 alors que PRE >= 0.7)")
    print("=" * 80)
    cat_qs = [q for q in all_q if pre_by[q].get("category") == "causal_why"]
    persistent = []
    for q in cat_qs:
        ps = pre_by[q].get("evaluation", {}).get("score", 0)
        bs = b9_by[q].get("evaluation", {}).get("score", 0)
        if ps >= 0.7 and bs < 0.7:
            persistent.append((q, ps, bs))
    print(f"Total : {len(persistent)}")
    for q, ps, bs in sorted(persistent, key=lambda x: x[2] - x[1])[:3]:
        print()
        print(f"{q}: PRE={ps:.2f} -> B9={bs:.2f}")
        print(f"  Q: {pre_by[q].get('question','')[:110]}")
        pa = pre_by[q].get("answer", "") or ""
        ba = b9_by[q].get("answer", "") or ""
        print(f"  PRE first line: {pa.lstrip().split(chr(10))[0][:110]}")
        print(f"  B9  first line: {ba.lstrip().split(chr(10))[0][:110]}")
        print(f"  PRE idk={has_idk(pa)} meta_header={starts_with_meta_header(pa)}")
        print(f"  B9  idk={has_idk(ba)} meta_header={starts_with_meta_header(ba)}")


if __name__ == "__main__":
    main()
