"""
Oracle Injection Test — isole retrieval/filter de la synthèse.

Pour chaque question :
1. Extrait les chunks pertinents depuis le cache full_text via search_terms (window ±400 chars)
2. Injecte les chunks directement dans ResponseSynthesizer (bypass retrieval, KG, LLM-filter)
3. Capture la réponse + compare au expected
4. Verdict humain : OK / PARTIAL / KO

Sortie : JSON détaillé + résumé console.
"""
from __future__ import annotations

import os
import sys
import json
import glob
import time
from datetime import datetime, timezone
from pathlib import Path

# Ajout du root projet au path (pour exécution standalone)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from test_cases import TEST_CASES  # noqa: E402

# Path is computed relative to KNOWBASE_DATA_DIR for container compat
import os as _os
CACHE_DIR = Path(_os.environ.get("KNOWBASE_DATA_DIR", r"C:/Projects/SAP_KB/data")) / "extraction_cache"
WINDOW_BEFORE = 200
WINDOW_AFTER = 600
MAX_CHUNKS_PER_DOC = 4

# ─── Build doc_id → cache file map ────────────────────────────────────────


def build_cache_map() -> dict[str, Path]:
    mapping = {}
    for f in glob.glob(str(CACHE_DIR / "*.v5cache.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
            doc_id = d.get("document_id") or d.get("extraction", {}).get("document_id")
            if doc_id:
                mapping[doc_id] = Path(f)
        except Exception as exc:
            print(f"  ⚠️  Cache load failed {f}: {exc}", file=sys.stderr)
    return mapping


def extract_chunks(full_text: str, search_terms: list[str]) -> list[str]:
    """Extrait les fenêtres de texte autour des matches (case-insensitive)."""
    chunks = []
    seen_offsets = set()
    ft_lower = full_text.lower()
    for term in search_terms:
        term_lower = term.lower()
        start = 0
        while True:
            idx = ft_lower.find(term_lower, start)
            if idx < 0:
                break
            # Évite chevauchements
            if any(abs(idx - o) < 200 for o in seen_offsets):
                start = idx + len(term)
                continue
            seen_offsets.add(idx)
            chunk_start = max(0, idx - WINDOW_BEFORE)
            chunk_end = min(len(full_text), idx + len(term) + WINDOW_AFTER)
            chunk = full_text[chunk_start:chunk_end].strip()
            chunks.append(chunk)
            start = idx + len(term)
            if len(chunks) >= MAX_CHUNKS_PER_DOC:
                break
        if len(chunks) >= MAX_CHUNKS_PER_DOC:
            break
    return chunks


# ─── Synthesis call ────────────────────────────────────────────────────────


def call_synthesizer(question: str, claims: list[dict]) -> tuple[str, dict]:
    """Appelle ResponseSynthesizer en mode standalone."""
    from knowbase.runtime_v2.synthesis import ResponseSynthesizer

    # vLLM EC2 ou DeepInfra fallback (RuntimeLLMClient gère)
    vllm_url = os.environ.get("VLLM_URL", "http://3.79.230.218:8000")
    synth = ResponseSynthesizer(
        vllm_url=vllm_url,
        model_id="Qwen/Qwen2.5-14B-Instruct-AWQ",
        temperature=0.2,
        max_tokens=350,
    )
    t0 = time.time()
    answer = synth.synthesize(question=question, claims=claims, max_claims_in_prompt=8)
    elapsed = time.time() - t0
    return answer, {"latency_s": elapsed, **synth.last_metrics}


# ─── Main ──────────────────────────────────────────────────────────────────


def run() -> dict:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] Building cache map...")
    cache_map = build_cache_map()
    print(f"  Found {len(cache_map)} cached docs")

    # Pre-load all caches (tiny dataset)
    cache_data = {}
    for doc_id, p in cache_map.items():
        cache_data[doc_id] = json.load(open(p, encoding="utf-8"))["extraction"]["full_text"]

    results = []
    for i, tc in enumerate(TEST_CASES):
        print(f"\n[{i+1}/20] {tc['qid']} | {tc['bench_source']}")
        print(f"  Q: {tc['question'][:100]}...")
        print(f"  Expected: {tc['expected'][:80]}")

        # Extract chunks from each doc
        claims = []
        for doc_id in tc["doc_ids"]:
            if doc_id not in cache_data:
                print(f"  ⚠️  doc_id {doc_id} not in cache, skipping")
                continue
            ft = cache_data[doc_id]
            chunks = extract_chunks(ft, tc["search_terms"])
            for j, ch in enumerate(chunks):
                claims.append({
                    "claim_id": f"{doc_id}::chunk_{j}",
                    "doc_id": doc_id,
                    "text": ch,
                    "score": 0.95 - 0.05 * j,
                })

        if not claims:
            print(f"  ❌ NO CHUNKS extracted (search terms ne matchent pas)")
            results.append({
                "qid": tc["qid"],
                "bench_source": tc["bench_source"],
                "question": tc["question"],
                "expected": tc["expected"],
                "n_chunks": 0,
                "answer": None,
                "metrics": {},
                "status": "NO_CHUNKS",
            })
            continue

        print(f"  Injected {len(claims)} chunks across {len(set(c['doc_id'] for c in claims))} docs")

        # Call synthesizer
        try:
            answer, metrics = call_synthesizer(tc["question"], claims)
            print(f"  Latency: {metrics.get('latency_s', 0):.1f}s")
            print(f"  A: {answer[:300]}")
            results.append({
                "qid": tc["qid"],
                "bench_source": tc["bench_source"],
                "question": tc["question"],
                "expected": tc["expected"],
                "doc_ids": tc["doc_ids"],
                "search_terms": tc["search_terms"],
                "n_chunks": len(claims),
                "claims_preview": [{"doc_id": c["doc_id"], "text": c["text"][:200]} for c in claims[:3]],
                "answer": answer,
                "metrics": metrics,
                "status": "OK",
            })
        except Exception as exc:
            print(f"  ❌ SYNTHESIS FAILED: {exc}")
            import traceback
            traceback.print_exc()
            results.append({
                "qid": tc["qid"],
                "bench_source": tc["bench_source"],
                "question": tc["question"],
                "expected": tc["expected"],
                "n_chunks": len(claims),
                "answer": None,
                "metrics": {},
                "status": f"FAILED: {exc}",
            })

    # Save
    out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(TEST_CASES),
        "n_with_chunks": sum(1 for r in results if r["n_chunks"] > 0),
        "n_with_answer": sum(1 for r in results if r["status"] == "OK"),
        "results": results,
    }
    out_path = Path(__file__).parent / f"injection_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Saved → {out_path}")
    return out


if __name__ == "__main__":
    run()
