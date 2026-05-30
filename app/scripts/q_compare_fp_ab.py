"""Compare A/B PremiseVerifier OFF vs ON sur le subset faux-présupposés.

Usage : q_compare_fp_ab.py <run_off.json> <run_on.json>
Mesure : amélioration sur false_premise + régression éventuelle sur les normaux.
"""
import json
import statistics as st
import sys


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def main():
    off = json.load(open(sys.argv[1]))
    on = json.load(open(sys.argv[2]))
    O = {r["id"]: r for r in off["results_50q"]}
    N = {r["id"]: r for r in on["results_50q"]}
    ids = [i for i in O if i in N]

    fp = [i for i in ids if O[i]["primary_type"] == "false_premise"]
    norm = [i for i in ids if O[i]["primary_type"] != "false_premise"]

    def jmean(d, sub):
        return mean([d[i]["judge_score"] for i in sub])

    print(f"n={len(ids)}  (false_premise={len(fp)}, normaux={len(norm)})")
    print(f"\n{'GROUPE':<16}{'OFF':>8}{'ON':>8}{'delta':>8}")
    print("-" * 40)
    for label, sub in [("false_premise", fp), ("normaux", norm), ("GLOBAL", ids)]:
        o, n = jmean(O, sub), jmean(N, sub)
        if o is None or n is None:
            print(f"{label:<16}{'--':>8}{'--':>8}")
            continue
        print(f"{label:<16}{o:>8.3f}{n:>8.3f}{(n - o) * 100:>+8.1f}")

    # détail false_premise (le coeur)
    print("\n=== DÉTAIL false_premise ===")
    for i in fp:
        o, n = O[i], N[i]
        print(f"\n{i}  judge OFF={o['judge_score']} → ON={n['judge_score']}  | mode {o['run'].get('mode')}→{n['run'].get('mode')}")
        print(f"  Q : {o['question'][:90]}")
        print(f"  ON answer: {(n['run'].get('answer_text') or '')[:220]}")

    # régressions sur normaux (judge baisse de >0)
    print("\n=== RÉGRESSIONS sur normaux (judge ON < OFF) ===")
    any_reg = False
    for i in norm:
        do, dn = O[i]["judge_score"], N[i]["judge_score"]
        if do is not None and dn is not None and dn < do:
            any_reg = True
            print(f"  {i} ({O[i]['primary_type']}): {do} → {dn}  | mode {O[i]['run'].get('mode')}→{N[i]['run'].get('mode')}")
    if not any_reg:
        print("  AUCUNE régression sur les normaux ✓")

    # latence
    print(f"\nlatence p50 : OFF {off['agg_50q']['latency_p50_s']:.0f}s → ON {on['agg_50q']['latency_p50_s']:.0f}s")


if __name__ == "__main__":
    main()
