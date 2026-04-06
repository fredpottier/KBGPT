#!/usr/bin/env python3
"""Test borne superieure V2 : reconstruction structurelle des passages.

Strategie : extraire la PAGE qui contient le terme cle,
puis couper autour du terme avec un contexte de +/- 800 chars
en respectant les frontieres de paragraphes.
Prefixer avec le titre du document et le numero de page.
"""
import json
import os
import re
import glob
import sys
import time

# Charger tous les caches
caches = {}
for cache_file in glob.glob("data/extraction_cache/*.v5cache.json"):
    try:
        data = json.load(open(cache_file, encoding="utf-8"))
        ft = data.get("extraction", {}).get("full_text", "")
        src = data.get("metadata", {}).get("source_file", "")
        if ft:
            caches[cache_file] = {"ft": ft, "src": src}
    except Exception:
        pass

print(f"Caches loaded: {len(caches)}")


def find_best_passage(anchor, context_chars=800):
    """Trouve le meilleur passage autour de l'ancre dans tous les caches.

    Utilise les tags [PAGE N] pour limiter au contenu de la page,
    puis prend un window autour du terme.
    """
    best = ""
    best_meta = ""

    for cache_file, cache_data in caches.items():
        ft = cache_data["ft"]
        src = cache_data["src"]

        # Split par page
        pages = re.split(r'\[PAGE (\d+)\]', ft)

        for i in range(1, len(pages), 2):
            page_no = pages[i]
            content = pages[i + 1] if i + 1 < len(pages) else ""

            # Chercher l'ancre dans cette page
            idx = content.lower().find(anchor.lower())
            if idx < 0:
                continue

            # Nettoyer les tags mais garder les sauts de paragraphe
            clean = re.sub(r'\[e\d+\|[^\]]*\]\s*"[^"]*"', '', content)  # vision elements
            clean = re.sub(r'\[VISUAL_ENRICHMENT[^\]]*\]', '', clean)
            clean = re.sub(r'\[PARAGRAPH\]', '\n', clean)
            clean = re.sub(r'\[TITLE[^\]]*\]', '\n## ', clean)
            clean = re.sub(r'\[TABLE[^\]]*\]', '\n', clean)
            clean = re.sub(r'\[/?[A-Z_]+[^\]]*\]', '', clean)  # remaining tags
            clean = re.sub(r'\n{3,}', '\n\n', clean)
            clean = re.sub(r'  +', ' ', clean)
            clean = clean.strip()

            # Retrouver l'ancre dans le texte nettoye
            idx_clean = clean.lower().find(anchor.lower())
            if idx_clean < 0:
                continue

            # Window autour de l'ancre
            start = max(0, idx_clean - context_chars)
            end = min(len(clean), idx_clean + context_chars)

            # Ajuster aux frontieres de ligne
            while start > 0 and clean[start] != '\n':
                start -= 1
            while end < len(clean) - 1 and clean[end] != '\n':
                end += 1

            passage = clean[start:end].strip()

            # Prefixer avec metadata
            doc_name = src or os.path.basename(cache_file)[:40]
            prefixed = f"[Document: {doc_name} | Page {page_no}]\n\n{passage}"

            if len(prefixed) > len(best):
                best = prefixed
                best_meta = f"page {page_no}, {len(passage)} chars"

    return best[:2000], best_meta


# Questions PPTX
questions = [
    {"qid": "T1_HUM_0040", "q": "Qu'est-ce que Joule dans le contexte SAP S/4HANA Cloud 2025 ?", "anchor": "super orchestrator", "expected": "copilote,orchestrat,Business AI"},
    {"qid": "T1_HUM_0041", "q": "Quels partenaires AI sont listes dans l'ecosysteme SAP Business Data Cloud 2025 ?", "anchor": "ALEPH ALPHA", "expected": "Anthropic,Aleph Alpha,Cohere"},
    {"qid": "T1_HUM_0042", "q": "Que permet la fonctionnalite Create Purchase Requisitions de Joule ?", "anchor": "Create Purchase Requisition", "expected": "purchase requisition,material,service"},
    {"qid": "T1_HUM_0043", "q": "Qu'est-ce que le Production Planning Optimizer (PPO) ?", "anchor": "Production Planning Optimizer", "expected": "PPO,constraint,linear programming"},
    {"qid": "T1_HUM_0044", "q": "Combien de pays de l'UE couverts par Intrastat dans S/4HANA ?", "anchor": "Intrastat processing", "expected": "27,member states"},
    {"qid": "T1_HUM_0045", "q": "Validite d'un permis de travail de niveau 1 dans Oil and Gas ?", "anchor": "work permit", "expected": "level 1,shift,permit"},
    {"qid": "T1_HUM_0052", "q": "Avantage de l'EWM embarque dans S/4HANA ?", "anchor": "eliminat", "expected": "embedded,duplication,synchronization"},
    {"qid": "T1_HUM_0053", "q": "Combien de Lines of Business couvertes par S/4HANA 1809 ?", "anchor": "Lines of Business", "expected": "10,Lines of Business"},
    {"qid": "T1_HUM_0063", "q": "Comment S/4HANA utilise la recherche fuzzy HANA pour la classification ?", "anchor": "fuzzy search", "expected": "fuzzy,tariff,classification"},
    {"qid": "T1_HUM_0064", "q": "Les 12 steps du WIP management avec MES integration ?", "anchor": "WIP management", "expected": "MES,staging,warehouse"},
    {"qid": "T1_HUM_0070", "q": "SAP product ID pour S/4HANA Reinsurance for Assumed Risk ?", "anchor": "7019930", "expected": "7019930,Reinsurance,Assumed Risk"},
    {"qid": "T1_HUM_0075", "q": "Comment fonctionne l'Advanced ATP (aATP) dans S/4HANA 1809 ?", "anchor": "backorder processing", "expected": "aATP,backorder,delivery"},
    {"qid": "T1_HUM_0081", "q": "Modeles de licensing pour S/4HANA Enterprise Management ?", "anchor": "Enhanced LoB", "expected": "Enterprise Management,Enhanced LoB,Industry"},
]

PROMPT = (
    "You are a precise assistant. Answer the question using ONLY the provided source. "
    "Be specific: include names, numbers, values, technical terms. "
    "If the information is partially available, answer with what you have. "
    "If the answer is not in the source at all, say 'information not available'. "
    "Answer in the SAME LANGUAGE as the question."
)


def test_answer(answer, expected_str):
    terms = [t.strip().lower() for t in expected_str.split(",") if len(t.strip()) > 2]
    found = sum(1 for t in terms if t in answer.lower())
    return found / max(len(terms), 1), found, len(terms)


# Reconstruire les passages
print("\nReconstruction des passages...")
reconstructed = []
for q in questions:
    passage, meta = find_best_passage(q["anchor"])
    if not passage:
        # Fallback : chercher avec un ancre alternative
        passage, meta = find_best_passage(q["anchor"].split()[0])
    reconstructed.append({
        "qid": q["qid"],
        "question": q["q"],
        "expected": q["expected"],
        "chunk": passage,
        "meta": meta,
    })
    status = "OK" if passage else "EMPTY"
    chars = len(passage)
    print(f"  {q['qid']}: {chars} chars ({meta})")


# Test Claude Sonnet
print("\n=== CLAUDE SONNET ===")
try:
    import anthropic
    client = anthropic.Anthropic()
    claude_results = []
    for r in reconstructed:
        if not r["chunk"]:
            claude_results.append({"qid": r["qid"], "status": "EMPTY", "score": 0})
            continue
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            system=PROMPT,
            messages=[{"role": "user", "content": f"Source:\n{r['chunk']}\n\nQuestion: {r['question']}"}],
            temperature=0,
        )
        answer = resp.content[0].text if resp.content else ""
        score, found, total = test_answer(answer, r["expected"])
        status = "OK" if score >= 0.5 else "FAIL"
        claude_results.append({"qid": r["qid"], "status": status, "score": score, "answer": answer[:200]})
        preview = answer[:120].encode("ascii", "replace").decode().replace("\n", " ")
        print(f"  [{status}] {r['qid']}: {found}/{total} terms")
        print(f"    {preview}")
        time.sleep(0.5)
    claude_ok = sum(1 for r in claude_results if r["status"] == "OK")
    print(f"\nClaude: {claude_ok}/13 ({100 * claude_ok / 13:.0f}%)")
except Exception as e:
    print(f"Claude error: {e}")
    claude_ok = 0

# Test Qwen 14B
print("\n=== QWEN 14B ===")
try:
    from openai import OpenAI
    qwen_client = OpenAI(
        api_key="EMPTY",
        base_url=os.environ.get("VLLM_URL", "http://18.194.28.167:8000") + "/v1",
    )
    qwen_results = []
    for r in reconstructed:
        if not r["chunk"]:
            qwen_results.append({"qid": r["qid"], "status": "EMPTY", "score": 0})
            continue
        resp = qwen_client.chat.completions.create(
            model="Qwen/Qwen2.5-14B-Instruct-AWQ",
            max_tokens=400,
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": f"Source:\n{r['chunk']}\n\nQuestion: {r['question']}"},
            ],
            temperature=0,
        )
        answer = resp.choices[0].message.content or ""
        score, found, total = test_answer(answer, r["expected"])
        status = "OK" if score >= 0.5 else "FAIL"
        qwen_results.append({"qid": r["qid"], "status": status, "score": score, "answer": answer[:200]})
        preview = answer[:120].encode("ascii", "replace").decode().replace("\n", " ")
        print(f"  [{status}] {r['qid']}: {found}/{total} terms")
        print(f"    {preview}")
        time.sleep(0.3)
    qwen_ok = sum(1 for r in qwen_results if r["status"] == "OK")
    print(f"\nQwen: {qwen_ok}/13 ({100 * qwen_ok / 13:.0f}%)")
except Exception as e:
    print(f"Qwen error: {e}")
    qwen_ok = 0

print(f"\n{'=' * 50}")
print(f"BORNE SUPERIEURE V2 (reconstruction structurelle)")
print(f"  Claude Sonnet:             {claude_ok}/13 ({100 * claude_ok / 13:.0f}%)")
print(f"  Qwen 14B:                  {qwen_ok}/13 ({100 * qwen_ok / 13:.0f}%)")
print(f"  Actuel (chunks atomiques): 2/13 (15%)")
print(f"{'=' * 50}")
