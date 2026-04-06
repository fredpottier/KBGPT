#!/usr/bin/env python3
"""Test borne superieure : chunks reconstruits + Claude Sonnet + Qwen 14B.

Verifie que les faits sont extractibles depuis des chunks de ~1500 chars
reconstruits a partir du full_text du cache (pas des DocItems atomiques).
"""
import json
import os
import re
import glob
import time

# Charger tous les caches
caches = {}
for cache_file in glob.glob("data/extraction_cache/*.v5cache.json"):
    try:
        data = json.load(open(cache_file, encoding="utf-8"))
        ft = data.get("extraction", {}).get("full_text", "")
        if ft:
            caches[cache_file] = ft
    except Exception:
        pass

print(f"Caches loaded: {len(caches)}")

# Questions PPTX avec ancre de localisation et termes attendus
questions = [
    {"qid": "T1_HUM_0040", "q": "Qu'est-ce que Joule dans le contexte SAP S/4HANA Cloud 2025 ?", "anchor": "Joule", "expected": "copilote,orchestrat,Business AI"},
    {"qid": "T1_HUM_0041", "q": "Quels partenaires AI sont listes dans l'ecosysteme SAP Business Data Cloud 2025 ?", "anchor": "ALEPH ALPHA", "expected": "Anthropic,Aleph Alpha,Cohere"},
    {"qid": "T1_HUM_0042", "q": "Que permet la fonctionnalite Create Purchase Requisitions de Joule ?", "anchor": "purchase requisitions", "expected": "purchase requisition,Joule,material"},
    {"qid": "T1_HUM_0043", "q": "Qu'est-ce que le Production Planning Optimizer (PPO) ?", "anchor": "Production Planning Optimizer", "expected": "PPO,constraint,linear programming"},
    {"qid": "T1_HUM_0044", "q": "Combien de pays de l'UE couverts par Intrastat dans S/4HANA ?", "anchor": "Intrastat", "expected": "27,member states,EU"},
    {"qid": "T1_HUM_0045", "q": "Validite d'un permis de travail de niveau 1 dans Oil and Gas ?", "anchor": "Work Permit", "expected": "level 1,shift,permit"},
    {"qid": "T1_HUM_0052", "q": "Avantage de l'EWM embarque dans S/4HANA ?", "anchor": "Extended Warehouse Management", "expected": "embedded,duplication,synchronization"},
    {"qid": "T1_HUM_0053", "q": "Combien de Lines of Business couvertes par S/4HANA 1809 ?", "anchor": "Lines of Business", "expected": "10,Lines of Business,Sales"},
    {"qid": "T1_HUM_0063", "q": "Comment S/4HANA utilise la recherche fuzzy HANA pour la classification ?", "anchor": "fuzzy", "expected": "fuzzy,tariff,classification"},
    {"qid": "T1_HUM_0064", "q": "Les 12 steps du WIP management avec MES integration ?", "anchor": "WIP", "expected": "MES,staging,warehouse"},
    {"qid": "T1_HUM_0070", "q": "SAP product ID pour S/4HANA Reinsurance for Assumed Risk ?", "anchor": "7019930", "expected": "7019930,Reinsurance,Assumed Risk"},
    {"qid": "T1_HUM_0075", "q": "Comment fonctionne l'Advanced ATP (aATP) dans S/4HANA 1809 ?", "anchor": "Advanced ATP", "expected": "aATP,backorder,delivery"},
    {"qid": "T1_HUM_0081", "q": "Modeles de licensing pour S/4HANA Enterprise Management ?", "anchor": "Enterprise Management", "expected": "Enterprise Management,Enhanced LoB,Industry"},
]

PROMPT = (
    "You are a precise assistant. Answer the question using ONLY the provided source. "
    "Be specific: include names, numbers, values. "
    "If the answer is not in the source, say 'information not available'. "
    "Answer in the SAME LANGUAGE as the question."
)

# Reconstruire les passages (~1500 chars autour de l'ancre)
reconstructed = []
for q in questions:
    best_context = ""
    for _, ft in caches.items():
        idx = ft.lower().find(q["anchor"].lower())
        if idx >= 0:
            start = max(0, idx - 500)
            end = min(len(ft), idx + 1000)
            ctx = ft[start:end]
            ctx_clean = re.sub(
                r"\[PARAGRAPH\]|\[PAGE \d+\]|\[TITLE[^\]]*\]|\[VISUAL[^\]]*\]|\[TABLE[^\]]*\]",
                " ", ctx,
            )
            ctx_clean = re.sub(r"\n{3,}", "\n\n", ctx_clean).strip()
            ctx_clean = re.sub(r"  +", " ", ctx_clean)
            if len(ctx_clean) > len(best_context):
                best_context = ctx_clean

    reconstructed.append({
        "qid": q["qid"],
        "question": q["q"],
        "expected_terms": [t.strip().lower() for t in q["expected"].split(",") if len(t.strip()) > 2],
        "chunk": best_context[:1500],
        "chunk_len": len(best_context[:1500]),
    })


def test_answer(answer, expected_terms):
    """Score simple : combien de termes attendus sont dans la reponse."""
    answer_lower = answer.lower()
    found = sum(1 for t in expected_terms if t in answer_lower)
    score = found / max(len(expected_terms), 1)
    return score, found


def test_claude(reconstructed):
    """Test avec Claude Sonnet."""
    import anthropic
    client = anthropic.Anthropic()
    results = []
    for r in reconstructed:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            system=PROMPT,
            messages=[{"role": "user", "content": f"Source:\n{r['chunk']}\n\nQuestion: {r['question']}"}],
            temperature=0,
        )
        answer = resp.content[0].text if resp.content else ""
        score, found = test_answer(answer, r["expected_terms"])
        status = "OK" if score >= 0.5 else "FAIL"
        results.append({"qid": r["qid"], "status": status, "score": score, "answer": answer[:150]})
        preview = answer[:100].replace("\n", " ")
        print(f"  [{status}] {r['qid']}: {found}/{len(r['expected_terms'])} terms ({r['chunk_len']} chars)")
        print(f"    {preview}...")
        time.sleep(0.5)
    return results


def test_qwen(reconstructed):
    """Test avec Qwen 14B via vLLM."""
    from openai import OpenAI
    client = OpenAI(api_key="EMPTY", base_url=os.environ.get("VLLM_URL", "http://18.194.28.167:8000") + "/v1")
    results = []
    for r in reconstructed:
        resp = client.chat.completions.create(
            model="Qwen/Qwen2.5-14B-Instruct-AWQ",
            max_tokens=400,
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": f"Source:\n{r['chunk']}\n\nQuestion: {r['question']}"},
            ],
            temperature=0,
        )
        answer = resp.choices[0].message.content or ""
        score, found = test_answer(answer, r["expected_terms"])
        status = "OK" if score >= 0.5 else "FAIL"
        results.append({"qid": r["qid"], "status": status, "score": score, "answer": answer[:150]})
        preview = answer[:100].replace("\n", " ")
        print(f"  [{status}] {r['qid']}: {found}/{len(r['expected_terms'])} terms ({r['chunk_len']} chars)")
        print(f"    {preview}...")
        time.sleep(0.3)
    return results


if __name__ == "__main__":
    print("\n=== CLAUDE SONNET ===")
    claude = test_claude(reconstructed)
    claude_ok = sum(1 for r in claude if r["status"] == "OK")
    print(f"\nClaude: {claude_ok}/13 ({100*claude_ok/13:.0f}%)")

    print("\n=== QWEN 14B ===")
    qwen = test_qwen(reconstructed)
    qwen_ok = sum(1 for r in qwen if r["status"] == "OK")
    print(f"\nQwen: {qwen_ok}/13 ({100*qwen_ok/13:.0f}%)")

    print(f"\n{'='*50}")
    print(f"COMPARAISON BORNE SUPERIEURE")
    print(f"  Claude Sonnet:           {claude_ok}/13 ({100*claude_ok/13:.0f}%)")
    print(f"  Qwen 14B:                {qwen_ok}/13 ({100*qwen_ok/13:.0f}%)")
    print(f"  Actuel (chunks atomiques): 2/13 (15%)")
    print(f"{'='*50}")

    # Sauvegarder
    json.dump({"claude": claude, "qwen": qwen}, open("benchmark/results/upper_bound_test.json", "w"), indent=2)
