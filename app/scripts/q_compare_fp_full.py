"""Compare full 50q OFF vs ON (PremiseVerifier) — par type + global + régressions.

Usage : q_compare_fp_full.py <run_off.json> <run_on.json>
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

    def jmean(d, sub):
        return mean([d[i]["judge_score"] for i in sub])

    def eirmean(d, sub):
        return mean([d[i].get("exact_id_recall") for i in sub])

    # Global déterministe + juge
    ao, an = off["agg_50q"], on["agg_50q"]
    print(f"n={len(ids)}")
    print(f"\n{'MÉTRIQUE':<26}{'OFF':>8}{'ON':>8}{'delta':>8}")
    print("-" * 50)
    print(f"{'exact_id_recall ★':<26}{ao.get('exact_id_recall_mean',0):>8.3f}{an.get('exact_id_recall_mean',0):>8.3f}{(an.get('exact_id_recall_mean',0)-ao.get('exact_id_recall_mean',0))*100:>+8.1f}")
    print(f"{'abstention_correct ★':<26}{ao.get('abstention_correct_rate',0):>8.3f}{an.get('abstention_correct_rate',0):>8.3f}{(an.get('abstention_correct_rate',0)-ao.get('abstention_correct_rate',0))*100:>+8.1f}")
    print(f"{'C1 juge (global)':<26}{jmean(O,ids):>8.3f}{jmean(N,ids):>8.3f}{(jmean(N,ids)-jmean(O,ids))*100:>+8.1f}")

    # Par type (juge)
    types = sorted(set(O[i]["primary_type"] for i in ids))
    print(f"\n{'TYPE (juge C1)':<16}{'n':>3}{'OFF':>8}{'ON':>8}{'delta':>8}")
    print("-" * 43)
    for t in types:
        sub = [i for i in ids if O[i]["primary_type"] == t]
        o, n = jmean(O, sub), jmean(N, sub)
        flag = "  ←" if (o is not None and n is not None and n < o - 0.001) else ""
        print(f"{t:<16}{len(sub):>3}{(o or 0):>8.3f}{(n or 0):>8.3f}{((n or 0)-(o or 0))*100:>+8.1f}{flag}")

    # Questions où le vérificateur a fired (mode TEXT_ONLY + premise warning)
    fired = []
    for i in ids:
        w = N[i]["run"].get("synthesize_warnings") or []
        if any("premise" in x for x in w):
            fired.append(i)
    print(f"\nVérificateur a fired sur {len(fired)} questions :")
    for i in fired:
        print(f"  {i} ({O[i]['primary_type']}) judge {O[i]['judge_score']}→{N[i]['judge_score']} : {N[i]['question'][:70]}")

    # Régressions juge dont le vérificateur N'EST PAS la cause (variance)
    reg_verifier, reg_variance = [], []
    for i in ids:
        do, dn = O[i]["judge_score"], N[i]["judge_score"]
        if do is not None and dn is not None and dn < do - 0.001:
            (reg_verifier if i in fired else reg_variance).append((i, O[i]["primary_type"], do, dn))
    print(f"\nRégressions causées par le vérificateur : {len(reg_verifier)}")
    for i, t, do, dn in reg_verifier:
        print(f"  {i} ({t}) {do}→{dn}")
    print(f"Régressions = variance (vérificateur non-fired) : {len(reg_variance)}")
    for i, t, do, dn in reg_variance:
        print(f"  {i} ({t}) {do}→{dn}")

    print(f"\nlatence p50 : OFF {ao['latency_p50_s']:.0f}s → ON {an['latency_p50_s']:.0f}s | "
          f"p95 OFF {ao['latency_p95_s']:.0f}s → ON {an['latency_p95_s']:.0f}s")


if __name__ == "__main__":
    main()
