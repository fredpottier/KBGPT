"""Comparatif tête-à-tête OSMOSIS (runtime_v6) vs RAG classique sur le même gold-set.

Usage : p3_compare_osmosis_vs_rag.py <osmosis_run.json> <rag_run.json>
"""
import json
import statistics as st
import sys


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def main():
    osm = json.load(open(sys.argv[1]))
    rag = json.load(open(sys.argv[2]))
    O = {r["id"]: r for r in osm["results_50q"]}
    R = {r["id"]: r for r in rag["results_50q"]}
    ids = [i for i in O if i in R]

    def eir(run):
        return mean([run[i]["exact_id_recall"] for i in ids])

    def abst(run):
        return sum(1 for i in ids if run[i]["abstention_correct"]) / len(ids)

    def c1(run):
        return mean([run[i]["judge_score"] for i in ids])

    print(f"n aligned = {len(ids)}")
    print(f"{'METRIC':<22}{'OSMOSIS':>10}{'RAG':>10}{'delta_pp':>10}")
    print("-" * 52)
    for name, f in [("exact_id_recall *", eir), ("abstention_correct *", abst), ("C1 judge (bruite)", c1)]:
        o, r = f(O), f(R)
        print(f"{name:<22}{o:>10.3f}{r:>10.3f}{(o - r) * 100:>+10.1f}")
    print("  (* = deterministe, decisionnel)")

    types = sorted(set(O[i]["primary_type"] for i in ids))
    print()
    print("PAR TYPE")
    print(f"{'type':<14}{'n':>3}   exact_id_recall O/R/d      C1 juge O/R/d")
    print("-" * 64)
    for t in types:
        tids = [i for i in ids if O[i]["primary_type"] == t]
        oe = mean([O[i]["exact_id_recall"] for i in tids])
        re = mean([R[i]["exact_id_recall"] for i in tids])
        oc = mean([O[i]["judge_score"] for i in tids])
        rc = mean([R[i]["judge_score"] for i in tids])
        if oe is not None and re is not None:
            eirs = f"{oe:.2f}/{re:.2f}/{(oe - re) * 100:+4.0f}"
        else:
            eirs = "   (no ids)    "
        print(f"{t:<14}{len(tids):>3}   {eirs:<24}  {oc:.2f}/{rc:.2f}/{(oc - rc) * 100:+4.0f}")

    print()
    oa, ra = osm["agg_50q"], rag["agg_50q"]
    print(f"latence p50 : OSMOSIS {oa['latency_p50_s']:.0f}s   RAG {ra['latency_p50_s']:.0f}s")
    print(f"latence p95 : OSMOSIS {oa['latency_p95_s']:.0f}s   RAG {ra['latency_p95_s']:.0f}s")

    # Abstention breakdown : OSMOSIS vs RAG, qui abstient quand ?
    def abst_detail(run):
        over = sum(1 for i in ids if run[i]["run"].get("mode") == "ABSTENTION"
                   and run[i]["abstention_correct"] is False)
        return over
    print()
    print(f"abstentions a tort (answerable) : OSMOSIS {abst_detail(O)}   RAG {abst_detail(R)}")


if __name__ == "__main__":
    main()
