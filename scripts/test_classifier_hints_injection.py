#!/usr/bin/env python3
"""Smoke test : injection des Domain Pack hints dans le 12-class classifier."""
import sys
sys.path.insert(0, "/app/src")

from knowbase.domain_packs.manifest import load_pack_manifest, get_classifier_hints
from knowbase.relations.logical_relation_classifier import LogicalRelationClassifier

# 1. Vérifier que les hints sont chargés
print("=== Pack aerospace_compliance — classifier_hints ===")
hints = get_classifier_hints("aerospace_compliance")
print(f"  N hints: {len(hints)}")
for k, v in hints.items():
    print(f"  - {k} : {v[:80]}...")

print("\n=== Pack regulatory — classifier_hints ===")
hints_reg = get_classifier_hints("regulatory")
print(f"  N hints: {len(hints_reg)}")
for k, v in hints_reg.items():
    print(f"  - {k} : {v[:80]}...")

# 2. Tester _format_domain_hints
print("\n=== Domain hints prose section (aerospace) ===")
clf = LogicalRelationClassifier()
section = clf._format_domain_hints(hints)
print(section[:1200] + "..." if len(section) > 1200 else section)

# 3. Vérifier que le system prompt complet est OK
print("\n=== System prompt size ===")
from knowbase.relations.logical_relation_classifier import PROMPT_SYSTEM_12CLASS
full = PROMPT_SYSTEM_12CLASS + "\n\n" + section
print(f"  Universal prompt   : {len(PROMPT_SYSTEM_12CLASS)} chars")
print(f"  Domain hints       : {len(section)} chars")
print(f"  Combined           : {len(full)} chars (~{len(full)//4} tokens)")

# 4. Pas de regex dans les hints (V3.3 anti-pattern check)
import re
def has_regex_pattern(s: str) -> bool:
    return bool(re.search(r"\\\w|\([?:].*\)|\[a-z\]|\$|\^|\\b", s))
print("\n=== V3.3 anti-pattern check ===")
violations = []
for k, v in hints.items():
    if has_regex_pattern(v):
        violations.append(k)
for k, v in hints_reg.items():
    if has_regex_pattern(v):
        violations.append(f"regulatory.{k}")
if violations:
    print(f"  ❌ Violations regex détectées dans : {violations}")
else:
    print(f"  ✓ Aucune syntaxe regex/keywords détectée — V3.3 conforme")
