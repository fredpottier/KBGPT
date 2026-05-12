"""Extrait les questions où V3 ET V4.2 échouent tous les deux (both KO).

Mappe les question_id (q_X) aux T6_AERO_XXX_NNN du fichier source via index,
récupère ground_truth, et marque les questions méta-KG.

Output : /app/data/benchmark/oracle_audit/both_ko_extract.json
"""
import json
from collections import Counter
from pathlib import Path

V3 = "/app/data/benchmark/results/robustness_run_20260505_104355_V3_FINAL3.json"
V42 = "/app/data/benchmark/results/robustness_run_20260510_145658_v4_2_baseline.json"
SOURCE = "/app/benchmark/questions/aero_t6_robustness.json"
OUT_DIR = Path("/app/data/benchmark/oracle_audit")
OUT_DIR.mkdir(exist_ok=True, parents=True)
OUT = OUT_DIR / "both_ko_extract.json"

v3_data = json.load(open(V3))
v42_data = json.load(open(V42))
source = json.load(open(SOURCE))

v3_samples = v3_data["per_sample"]
v42_samples = v42_data["per_sample"]

# Map q_X → index. Souvent q_0 = source[0]
def by_qid(samples):
    return {s["question_id"]: s for s in samples}

v3_by_qid = by_qid(v3_samples)
v42_by_qid = by_qid(v42_samples)

# Inspecter clés disponibles dans V3 sample
if v3_samples:
    print(f"V3 sample keys: {list(v3_samples[0].keys())}")
if v42_samples:
    print(f"V4.2 sample keys: {list(v42_samples[0].keys())}")

# Mapping q_X → source par INDEX (q_0 → source[0])
def parse_qid_index(qid):
    if qid.startswith("q_"):
        try:
            return int(qid.split("_")[1])
        except Exception:
            return None
    return None

def get_source(qid):
    idx = parse_qid_index(qid)
    if idx is not None and 0 <= idx < len(source):
        return source[idx]
    return None

both = sorted(set(v3_by_qid) & set(v42_by_qid))
print(f"\nQuestions communes : {len(both)} (V3:{len(v3_samples)} V4.2:{len(v42_samples)} source:{len(source)})")

both_ko = []
for qid in both:
    a = v3_by_qid[qid]
    b = v42_by_qid[qid]
    sa = float((a.get("evaluation") or {}).get("score") or 0)
    sb = float((b.get("evaluation") or {}).get("score") or 0)
    if sa >= 0.5 or sb >= 0.5:
        continue

    src = get_source(qid)
    if src is None:
        continue

    # Validation : la question doit matcher
    src_q = (src.get("question") or "").strip()
    sample_q = (a.get("question") or "").strip()
    if src_q and sample_q and src_q[:50] != sample_q[:50]:
        # Mismatch index, skip
        continue

    gt = src.get("ground_truth") or {}
    evidence_doc = gt.get("evidence_doc")
    evidence_docs = gt.get("evidence_docs") or ([evidence_doc] if evidence_doc else [])
    evidence_docs = [d for d in evidence_docs if d]

    cat = src.get("category") or a.get("category")
    is_meta_kg = (not evidence_docs) and cat != "unanswerable"

    # Chunks éventuels dans V3 sample
    v3_chunks = []
    for k in ("chunks_used", "_chunks_used", "context_chunks", "retrieved_chunks", "context"):
        v = a.get(k)
        if v:
            v3_chunks = v
            break
    v42_chunks = []
    for k in ("chunks_used", "_chunks_used", "context_chunks", "retrieved_chunks", "context"):
        v = b.get(k)
        if v:
            v42_chunks = v
            break

    both_ko.append({
        "question_id": qid,
        "source_id": src.get("id"),
        "question": src_q,
        "category": cat,
        "language": a.get("language") or "fr",
        "ground_truth": gt,
        "evidence_docs": evidence_docs,
        "is_meta_kg": is_meta_kg,
        "v3": {
            "score": sa,
            "answer": a.get("answer") or "",
            "judge_reason": (a.get("evaluation") or {}).get("judge_reason") or "",
            "chunks_count": len(v3_chunks) if isinstance(v3_chunks, list) else 0,
            "chunks_sample": (v3_chunks[:3] if isinstance(v3_chunks, list) else []),
        },
        "v4_2": {
            "score": sb,
            "answer": b.get("answer") or "",
            "judge_reason": (b.get("evaluation") or {}).get("judge_reason") or "",
            "chunks_count": len(v42_chunks) if isinstance(v42_chunks, list) else 0,
            "chunks_sample": (v42_chunks[:3] if isinstance(v42_chunks, list) else []),
        },
    })

# Stats
print(f"\nBoth KO total : {len(both_ko)}")
print(f"  - auditables (evidence_docs présent OU unanswerable) : {sum(1 for q in both_ko if not q['is_meta_kg'])}")
print(f"  - méta-KG (evidence_doc null, non auditable via PDF) : {sum(1 for q in both_ko if q['is_meta_kg'])}")

cats_audit = Counter(q["category"] for q in both_ko if not q["is_meta_kg"])
print("\nAuditables par catégorie :")
for c, n in cats_audit.most_common():
    print(f"  {c:35s} : {n}")

cats_meta = Counter(q["category"] for q in both_ko if q["is_meta_kg"])
if cats_meta:
    print("\nMéta-KG (à exclure) par catégorie :")
    for c, n in cats_meta.most_common():
        print(f"  {c:35s} : {n}")

# Stats chunks
v3_with_chunks = sum(1 for q in both_ko if q["v3"]["chunks_count"] > 0)
v42_with_chunks = sum(1 for q in both_ko if q["v4_2"]["chunks_count"] > 0)
print(f"\nChunks exposés dans samples :")
print(f"  V3   : {v3_with_chunks}/{len(both_ko)}")
print(f"  V4.2 : {v42_with_chunks}/{len(both_ko)}")

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({
        "v3_run": V3,
        "v4_2_run": V42,
        "source": SOURCE,
        "both_ko_count": len(both_ko),
        "questions": both_ko,
    }, f, indent=2, ensure_ascii=False)

print(f"\nÉcrit : {OUT}")
