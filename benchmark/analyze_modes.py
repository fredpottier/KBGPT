"""
Analyse les modes declenches par OSMOSIS pendant un benchmark.

Parse les logs Docker `app` pour extraire les decisions PERSPECTIVE/DIRECT
de chaque question, et croise avec les resultats du benchmark si fournis.

Usage:
    # Analyse standalone (juste les modes des dernieres N lignes de logs)
    python benchmark/analyze_modes.py --tail 5000

    # Croisement avec un fichier de resultats
    python benchmark/analyze_modes.py --tail 5000 --results path/to/judge_xxx.json

Sortie:
    - Compte global PERSPECTIVE / DIRECT / TENSION / STRUCTURED_FACT / fallback
    - Si --results fourni : separation des metriques par mode
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Optional


# Patterns log
RE_DETECT = re.compile(r"\[PERSPECTIVE:STRATEGY\] strategy=(\w+) confidence=(\w+)")
RE_DECISION = re.compile(r"\[PERSPECTIVE:DECISION\] (\w+)")
RE_FALLBACK_REASON = re.compile(r"veto=(\w+)")
RE_MODE_LOG = re.compile(r"\[OSMOSIS:MODE\] candidate=(\w+) resolved=(\w+)")
RE_QUESTION = re.compile(r"question='([^']{0,80})")


def fetch_docker_logs(tail: int = 5000) -> List[str]:
    """Recupere les logs du container app."""
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.infra.yml",
             "-f", "docker-compose.yml", "logs", "app", "--tail", str(tail)],
            capture_output=True, text=True, timeout=60,
        )
        return result.stdout.split("\n")
    except Exception as e:
        print(f"Error fetching logs: {e}", file=sys.stderr)
        return []


def parse_mode_decisions(log_lines: List[str]) -> List[Dict]:
    """Parse les decisions de mode question par question.

    Une decision est constituee de :
    - PERSPECTIVE:STRATEGY (decision LLM brute)
    - PERSPECTIVE:DECISION (decision finale apres veto)
    - OSMOSIS:MODE candidate=X resolved=Y (mode final retenu)

    On regroupe par fenetre temporelle : chaque "OSMOSIS:MODE" cloture une question.
    """
    decisions = []
    current = {}

    for line in log_lines:
        if not line.strip():
            continue

        # Strategy decision (brute LLM)
        m = RE_DETECT.search(line)
        if m:
            current["strategy_raw"] = m.group(1)
            current["strategy_confidence"] = m.group(2)
            continue

        # Decision finale apres veto
        m = RE_DECISION.search(line)
        if m:
            current["strategy_final"] = m.group(1)
            veto_m = RE_FALLBACK_REASON.search(line)
            current["veto"] = veto_m.group(1) if veto_m else None
            continue

        # Mode global resolu
        m = RE_MODE_LOG.search(line)
        if m:
            current["candidate_mode"] = m.group(1)
            current["resolved_mode"] = m.group(2)
            # Fin de question — flush
            if current:
                decisions.append(dict(current))
                current = {}
            continue

    # Flush final
    if current:
        decisions.append(dict(current))

    return decisions


def summarize_modes(decisions: List[Dict]) -> Dict:
    """Synthese des modes declenches."""
    resolved_modes = Counter()
    candidate_modes = Counter()
    strategy_raw = Counter()
    strategy_final = Counter()
    confidence_dist = Counter()
    vetoes = Counter()

    for d in decisions:
        if "resolved_mode" in d:
            resolved_modes[d["resolved_mode"]] += 1
        if "candidate_mode" in d:
            candidate_modes[d["candidate_mode"]] += 1
        if "strategy_raw" in d:
            strategy_raw[d["strategy_raw"]] += 1
        if "strategy_final" in d:
            strategy_final[d["strategy_final"]] += 1
        if "strategy_confidence" in d:
            confidence_dist[d["strategy_confidence"]] += 1
        if d.get("veto") and d["veto"] != "None":
            vetoes[d["veto"]] += 1

    return {
        "total_decisions": len(decisions),
        "resolved_modes": dict(resolved_modes),
        "candidate_modes": dict(candidate_modes),
        "strategy_raw": dict(strategy_raw),
        "strategy_final": dict(strategy_final),
        "confidence_dist": dict(confidence_dist),
        "vetoes": dict(vetoes),
    }


def main():
    parser = argparse.ArgumentParser(description="Analyse modes OSMOSIS pendant benchmark")
    parser.add_argument("--tail", type=int, default=5000, help="Nombre de lignes de logs a parser")
    parser.add_argument("--results", help="Fichier de resultats benchmark a croiser (optionnel)")
    args = parser.parse_args()

    print(f"Fetching last {args.tail} log lines from app container...")
    logs = fetch_docker_logs(args.tail)
    print(f"Got {len(logs)} log lines")

    decisions = parse_mode_decisions(logs)
    print(f"Parsed {len(decisions)} mode decisions")

    summary = summarize_modes(decisions)

    print()
    print("=" * 70)
    print("MODE DECISIONS SUMMARY")
    print("=" * 70)
    print(f"Total decisions parsed : {summary['total_decisions']}")
    print()
    print("Resolved modes (final):")
    for mode, count in sorted(summary["resolved_modes"].items(), key=lambda x: -x[1]):
        pct = count / max(summary["total_decisions"], 1) * 100
        print(f"  {mode:<20} : {count:>4} ({pct:>5.1f}%)")
    print()
    print("Strategy LLM (raw):")
    for s, c in sorted(summary["strategy_raw"].items(), key=lambda x: -x[1]):
        print(f"  {s:<20} : {c}")
    print()
    print("Confidence distribution:")
    for conf, c in sorted(summary["confidence_dist"].items(), key=lambda x: -x[1]):
        print(f"  {conf:<20} : {c}")
    if summary["vetoes"]:
        print()
        print("Vetoes triggered:")
        for v, c in sorted(summary["vetoes"].items(), key=lambda x: -x[1]):
            print(f"  {v:<20} : {c}")

    # Croisement avec resultats si fourni
    if args.results:
        print()
        print("=" * 70)
        print(f"CROSS-ANALYSIS WITH RESULTS : {args.results}")
        print("=" * 70)
        try:
            with open(args.results, encoding="utf-8") as f:
                results_data = json.load(f)
            print("(Note: cross-analysis necessite que le runner capture le mode par question.")
            print("Utilise plutot la repartition globale ci-dessus pour interpretation.)")
        except Exception as e:
            print(f"Could not load results: {e}")


if __name__ == "__main__":
    main()
