#!/usr/bin/env python3
"""Smoke test du LLM classifier sémantique (V3.3-conforming, no regex)."""
import sys
sys.path.insert(0, "/app/src")

from knowbase.runtime.query_resolver import QueryResolver

resolver = QueryResolver()

# Cas couvrant les 7 modes + multilingue + variations qui cassaient les regex
test_queries = [
    # FR — formulations variées qui cassaient le regex énumère[snrz]?
    ("Énumérez toutes les relations ÉQUIVALENTES définies dans le corpus", "EXPLORATION_RELATIONAL"),
    ("Listez tous les SUBSET dans le corpus", "EXPLORATION_RELATIONAL"),
    ("Quelles sont les exceptions à la règle 25.1309 ?", "APPLICABILITY_QUERY"),  # piège: "exceptions" mais c'est applicability
    # EN
    ("List all the EQUIVALENT relations in the corpus", "EXPLORATION_RELATIONAL"),
    ("What is the impact energy required for a 51mm ball?", "LOOKUP_FACTUAL"),
    ("What rules apply to lasers above 0.002 J?", "APPLICABILITY_QUERY"),
    # DE — non couvert par les anciens regex
    ("Welche Regeln gelten für Laser über 0,002 J pro Puls?", "APPLICABILITY_QUERY"),
    # Temporel
    ("What was the rule for Halon 1301 in 2018?", "SNAPSHOT_TEMPORAL"),
    ("Quelle était la règle pour le Halon 1301 en 2018 ?", "SNAPSHOT_TEMPORAL"),
    ("What changed between 2009 and 2021 in dual-use exports?", "DIFF_EVOLUTION"),
    # Conflict
    ("What contradictions exist in the corpus on ETOPS?", "CONFLICT_RISK"),
    ("Y a-t-il des incohérences sur les déviations ETOPS ?", "CONFLICT_RISK"),
    # Synthesis
    ("Summarize the dual-use export controls", "SYNTHESIS_SUMMARY"),
    ("Donne-moi une vue d'ensemble du règlement 2021/821", "SYNTHESIS_SUMMARY"),
]

correct = 0
for q, expected in test_queries:
    r = resolver.resolve(q)
    actual = r.mode.value
    ok = actual == expected
    if ok:
        correct += 1
    status = "OK" if ok else "KO"
    anchor = r.temporal_anchor.isoformat() if r.temporal_anchor else "-"
    rng = f"{r.temporal_range[0]}→{r.temporal_range[1]}" if r.temporal_range else "-"
    print(f"  [{status}] {actual:25s} (exp={expected:25s} conf={r.confidence:.2f} anchor={anchor} range={rng}) | {q[:65]}")

print(f"\nScore : {correct}/{len(test_queries)} = {100*correct//len(test_queries)}%")
