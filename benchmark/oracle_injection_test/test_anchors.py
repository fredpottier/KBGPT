"""Test rapide de l'extraction d'anchors."""
import sys
sys.path.insert(0, "/app/src")
import importlib.util

spec = importlib.util.spec_from_file_location("qsr_test", "/app/src/knowbase/runtime_v2/question_subject_resolver.py")
mod = importlib.util.module_from_spec(spec)
# Provide stub modules
import types
neo4j_stub = types.ModuleType("neo4j")
neo4j_stub.Driver = type("Driver", (), {})
sys.modules["neo4j"] = neo4j_stub
# Now load
try:
    spec.loader.exec_module(mod)
except Exception as e:
    print(f"Load error: {e}")
    raise

extract = mod._extract_anchors_from_question
matches = mod._doc_id_matches_anchor

tests = [
    "Quels CS-25 paragraphes amendés par l'amdt 27 sur CS 25.1309(c) ?",
    "Selon l'Article 8 du règlement 2021/821, quelle autorité ?",
    "Quel délégué dual-use était applicable juste avant 2024/2547 ?",
    "Le règlement 428/2009 était-il en vigueur le 1er janvier 2022 ?",
    "L'Annex I et l'Annex IV ont-ils le même périmètre ?",
    "NPA 2015-19 NPA 2014-02 changes amdt 28",
]
for q in tests:
    a = extract(q)
    print(f"{q[:70]:70s} → {a}")

print()
docs = ["cs25_amdt_27_992260a7", "cs25_amdt_25_a41bdc85", "dualuse_reg_2021_821_original_65eef5dc",
        "dualuse_reg_428_2009_original_372b7ac3", "dualuse_del_2024_2547_cb08f84b"]
test_q = "Quels CS-25 paragraphes amendés par l'amdt 27 sur CS 25.1309 ?"
ancs = extract(test_q)
print(f"Q: {test_q}")
print(f"anchors: {ancs}")
for d in docs:
    print(f"  {d:55s} match_count={matches(d, ancs)}")
