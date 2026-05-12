"""Mesure 1 — isolation modèle × archi sur les 30 questions Oracle.

Pour chaque question, exécute 2 options de retrieval × 4 modèles :
  - Option 1A "archi V4.2-équivalent" : top_k=15 chunks (proche de top_k=12 V4.2)
  - Option 1B "accès large"          : top_k=50 chunks (simulant accès oracle)

Modèles testés (open-source, charte respectée) :
  - DeepSeek-V3.1 (rapide, généraliste)
  - DeepSeek-R1   (reasoning model)
  - Qwen2.5-72B   (généraliste reférence)
  - Llama-3.1-405B (très grand modèle)

Output :
  - /app/data/benchmark/oracle_audit/alt_models_answers.json
  - /app/data/benchmark/oracle_audit/alt_models_scoring.json (après scoring)
"""
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

from knowbase.config.settings import get_settings
from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.runtime_v3.retriever import ClaimRetriever
from knowbase.facts_first.evidence_collector import EvidenceCollector

SAMPLE = "/app/data/benchmark/oracle_audit/oracle_audit_sample.json"
OUT_ANS = Path("/app/data/benchmark/oracle_audit/alt_models_answers.json")
OUT_SCORES = Path("/app/data/benchmark/oracle_audit/alt_models_scoring.json")

DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()
if not DEEPINFRA_KEY:
    print("ERROR: DEEPINFRA_API_KEY not set", file=sys.stderr)
    sys.exit(1)

# Modèles à tester (ID DeepInfra) — Llama-3.1-405B retiré (>3min/appel = budget temps insuffisant)
MODELS = {
    "deepseek-v3-1": "deepseek-ai/DeepSeek-V3.1",
    "deepseek-r1": "deepseek-ai/DeepSeek-R1",
    "qwen-72b": "Qwen/Qwen2.5-72B-Instruct",
}
# Bornes max_tokens : R1 a besoin de plus pour son <think> (reasoning) interne
MODEL_MAX_TOKENS = {
    "deepseek-v3-1": 800,
    "deepseek-r1": 1500,
    "qwen-72b": 800,
}

JUDGES = {
    "llama-3.3-70b": "meta-llama/Llama-3.3-70B-Instruct",
    "qwen-2.5-72b": "Qwen/Qwen2.5-72B-Instruct",
}

# Prompt minimaliste (sans instructions strictes)
ANSWER_PROMPT = """Réponds à la question suivante en utilisant les passages fournis. Cite tes sources avec [doc=ID].

Question : {question}

Passages disponibles :
{chunks}

Réponse :"""

# Critères du judge (copie de robustness_diagnostic.py)
CATEGORY_JUDGE_CRITERIA = {
    "false_premise": "The question contains a FALSE premise. A good answer should CORRECT the false premise and provide the correct information from the sources. A bad answer accepts the false premise without questioning it.",
    "temporal_evolution": "The question asks about how something CHANGED between document versions. A good answer identifies specific changes and cites both versions. A bad answer is vague or doesn't compare versions.",
    "causal_why": "The question asks WHY something is done. A good answer explains the reason based on documented facts. A bad answer gives generic reasons not grounded in the sources.",
    "negation": "The question asks what is NOT possible/supported. A good answer identifies the limitation or restriction from the sources. A bad answer fails to address the negation.",
    "synthesis_large": "The question asks for a comprehensive overview. A good answer covers multiple aspects from multiple documents. A bad answer is too narrow or misses major aspects.",
    "conditional": "The question asks about a specific condition or prerequisite. A good answer identifies and explains the condition from the sources. A bad answer misses the conditional aspect.",
    "set_list": "The question asks to LIST or ENUMERATE items. A good answer lists the correct items from the sources. A bad answer misses items or lists wrong ones.",
    "multi_hop": "The question requires CHAINING facts from multiple sources. A good answer connects the facts logically. A bad answer only addresses part of the chain.",
    "unanswerable": "The question asks for information that does NOT exist in the corpus. A good answer abstains, says it cannot find the information, or explains why the answer is unavailable. A bad answer fabricates an answer.",
}

JUDGE_PROMPT_TEMPLATE = """You are a strict benchmark evaluator for a document analysis system.

Question: "{question}"
Category: {category}
Expected behavior: {expected}
{evidence_line}

Evaluation criteria: {criteria}

Actual answer:
"{answer}"

Rate the answer from 0 to 100:
- 0-20: Completely wrong, irrelevant, or hallucinates
- 20-50: Partially relevant but misses the key point
- 50-70: Addresses the topic but incomplete
- 70-90: Good, mostly correct and grounded in sources
- 90-100: Excellent, fully addresses with evidence

Reply in this exact format on two lines:
SCORE: <number 0-100>
REASON: <one short sentence explaining the score, max 25 words>"""


def call_deepinfra(model_id: str, prompt: str, max_tokens: int = 800, max_retries: int = 3) -> dict:
    """Appel DeepInfra avec retry. Pour DeepSeek-R1, on capture aussi le raw avant nettoyage."""
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPINFRA_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.0,
                },
                timeout=300,  # DeepSeek-R1 + Llama-405B peuvent être lents
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"].get("content", "") or ""
            reasoning = data["choices"][0]["message"].get("reasoning_content", "")
            # Pour DeepSeek-R1 : si content vide mais reasoning rempli, prendre reasoning
            if not text.strip() and reasoning:
                text = reasoning
            # Strip <think>...</think> blocks éventuels
            text_clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return {"text": text_clean, "raw": text, "error": None}
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"    [retry {attempt+1}/{max_retries}] {type(e).__name__}: {str(e)[:120]} — wait {wait}s")
                time.sleep(wait)
    return {"text": "", "raw": "", "error": str(last_error)}


def format_chunks(claims) -> str:
    """Formate les claims en texte concis avec doc_id.

    Le champ texte sur EvidenceClaim est `quote` (verbatim Neo4j enrichi ou chunk Qdrant).
    """
    parts = []
    for i, c in enumerate(claims[:60]):
        text = (
            getattr(c, "quote", None)
            or getattr(c, "verbatim_quote", None)
            or getattr(c, "claim_text", None)
            or getattr(c, "text", None)
            or ""
        )
        doc_id = (
            getattr(c, "doc_id", None)
            or getattr(c, "source_doc", None)
            or getattr(c, "source", None)
            or "unknown"
        )
        if not text:
            continue
        text_short = text[:800]
        parts.append(f"[doc={doc_id}] {text_short}")
    return "\n\n".join(parts)


def collect_evidence(collector: EvidenceCollector, question: str, top_k: int):
    """Collecte chunks pour la question via EvidenceCollector V4.2."""
    bundle = collector.collect(question=question, top_k=top_k, mode="single")
    return bundle.claims if hasattr(bundle, "claims") else []


def generation_phase():
    """Phase 1 : génération des réponses par 4 modèles × 2 options × 30 questions."""
    sample = json.load(open(SAMPLE))
    questions = sample["questions"]

    # Setup retriever V4.2-compatible
    settings = get_settings()
    qdrant = get_qdrant_client()
    embedder = get_sentence_transformer(settings.embeddings_model, cache_folder=str(settings.hf_home))
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    tenant_id = os.getenv("TENANT_ID", "default")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    retriever = ClaimRetriever(
        qdrant_client=qdrant, embedder=embedder, driver=driver,
        collection_name="knowbase_chunks_v2", tenant_id=tenant_id,
    )
    collector = EvidenceCollector(retriever=retriever, neo4j_driver=driver, tenant_id=tenant_id)

    # Reprise depuis fichier existant si présent
    if OUT_ANS.exists():
        results = json.load(open(OUT_ANS))
        print(f"[resume] Chargé {len(results.get('per_question', []))} questions déjà traitées")
    else:
        results = {"per_question": [], "_models": MODELS, "_options": ["1A_topk15", "1B_topk50"]}

    done_qids = {q["question_id"] for q in results["per_question"]}
    questions_todo = [q for q in questions if q["question_id"] not in done_qids]
    print(f"À traiter : {len(questions_todo)}/30 questions")

    t0 = time.time()
    for i, q in enumerate(questions_todo):
        qid = q["question_id"]
        question = q["question"]
        print(f"\n[{i+1}/{len(questions_todo)}] {qid} | {q['category']}")

        # Retrieval pour 1A et 1B (1B réduit à 30 pour limiter latence DeepSeek-V3.1 sur gros ctx)
        try:
            claims_1a = collect_evidence(collector, question, top_k=15)
            chunks_1a = format_chunks(claims_1a)
        except Exception as e:
            print(f"  retrieval 1A error: {e}")
            chunks_1a = ""
        try:
            claims_1b = collect_evidence(collector, question, top_k=30)
            chunks_1b = format_chunks(claims_1b)
        except Exception as e:
            print(f"  retrieval 1B error: {e}")
            chunks_1b = ""

        print(f"  retrieval 1A : {len(chunks_1a)} chars / 1B : {len(chunks_1b)} chars")

        per_q = {
            "question_id": qid,
            "category": q["category"],
            "question": question,
            "ground_truth_correct_fact": (q.get("ground_truth") or {}).get("correct_fact", "")[:300],
            "v3_score_bench": q["v3"]["score"],
            "v4_2_score_bench": q["v4_2"]["score"],
            "answers": {},  # {model_name: {"1A": text, "1B": text}}
            "retrieval_stats": {
                "1A_topk15_chars": len(chunks_1a),
                "1B_topk50_chars": len(chunks_1b),
            },
        }

        # Parallèle 3 modèles × 2 options = 6 appels concurrents par question
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def gen_one(model_name, model_id, option, chunks):
            if not chunks:
                return (model_name, option, {"text": "", "error": "no_chunks", "latency_ms": 0})
            prompt = ANSWER_PROMPT.format(question=question, chunks=chunks[:60000])
            mt = MODEL_MAX_TOKENS.get(model_name, 800)
            tg0 = time.time()
            out = call_deepinfra(model_id, prompt, max_tokens=mt)
            tg = int((time.time() - tg0) * 1000)
            return (model_name, option, {"text": out["text"], "latency_ms": tg, "error": out["error"]})

        for model_name in MODELS.keys():
            per_q["answers"][model_name] = {}

        tasks = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for model_name, model_id in MODELS.items():
                for option, chunks in [("1A", chunks_1a), ("1B", chunks_1b)]:
                    tasks.append(pool.submit(gen_one, model_name, model_id, option, chunks))
            for fut in as_completed(tasks):
                model_name, option, res = fut.result()
                if res.get("error"):
                    print(f"  {model_name} {option} ERROR: {res['error']}")
                else:
                    print(f"  {model_name} {option} ({res['latency_ms']}ms): {res['text'][:60]}...")
                per_q["answers"][model_name][option] = res

        results["per_question"].append(per_q)

        # Sauvegarde incrémentale
        with open(OUT_ANS, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t0
    print(f"\n=== Phase 1 (génération) terminée. {elapsed:.0f}s ===\n")
    print(f"Saved to {OUT_ANS}")
    return results


def call_judge(model_id: str, prompt: str, max_retries: int = 3) -> dict:
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPINFRA_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                    "temperature": 0.0,
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            score_m = re.search(r"SCORE\s*:\s*(\d+)", text, re.IGNORECASE)
            reason_m = re.search(r"REASON\s*:\s*(.+?)(?:$|\n)", text, re.IGNORECASE | re.DOTALL)
            if score_m:
                score = int(score_m.group(1)) / 100.0
            else:
                m = re.search(r"\d+", text)
                score = (int(m.group()) / 100.0) if m else 0.0
            score = max(0.0, min(1.0, score))
            reason = reason_m.group(1).strip() if reason_m else ""
            return {"score": score, "reason": reason, "error": None}
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
    return {"score": None, "reason": "", "error": str(last_error)}


def scoring_phase(results: dict):
    """Phase 2 : scoring des réponses générées."""
    sample = json.load(open(SAMPLE))
    sample_by_qid = {q["question_id"]: q for q in sample["questions"]}

    if OUT_SCORES.exists():
        scoring = json.load(open(OUT_SCORES))
    else:
        scoring = {"per_question": [], "_judges": JUDGES}

    done_qids = {q["question_id"] for q in scoring["per_question"]}
    todo = [q for q in results["per_question"] if q["question_id"] not in done_qids]
    print(f"\n=== Phase 2 (scoring) — {len(todo)} questions à scorer ===\n")

    t0 = time.time()
    for i, q in enumerate(todo):
        qid = q["question_id"]
        sq = sample_by_qid.get(qid, {})
        gt = sq.get("ground_truth") or {}
        category = q["category"]
        expected = gt.get("expected_behavior", "")
        evidence = gt.get("correct_fact") or gt.get("evidence_claim") or ""
        criteria = CATEGORY_JUDGE_CRITERIA.get(category, "")
        evidence_line = f'Reference evidence: "{evidence[:300]}"' if evidence else ""

        per_q = {"question_id": qid, "category": category, "scoring": {}}

        for model_name, options in q["answers"].items():
            per_q["scoring"][model_name] = {}
            for option, ans_data in options.items():
                ans_text = ans_data.get("text", "")
                if not ans_text or ans_data.get("error"):
                    per_q["scoring"][model_name][option] = {"empty": True}
                    continue
                judges_out = {}
                for judge_name, judge_id in JUDGES.items():
                    judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
                        question=q["question"][:200],
                        category=category,
                        expected=expected,
                        evidence_line=evidence_line,
                        criteria=criteria,
                        answer=ans_text[:3000],
                    )
                    j_out = call_judge(judge_id, judge_prompt)
                    judges_out[judge_name] = j_out
                per_q["scoring"][model_name][option] = judges_out

                # Print summary
                ll = judges_out.get("llama-3.3-70b", {}).get("score")
                qw = judges_out.get("qwen-2.5-72b", {}).get("score")
                ll_s = f"{ll:.2f}" if ll is not None else "ERR"
                qw_s = f"{qw:.2f}" if qw is not None else "ERR"
                print(f"  [{i+1}/{len(todo)}] {qid} {model_name} {option} → Llama={ll_s} Qwen={qw_s}")

        scoring["per_question"].append(per_q)
        with open(OUT_SCORES, "w", encoding="utf-8") as f:
            json.dump(scoring, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t0
    print(f"\n=== Phase 2 terminée. {elapsed:.0f}s ===")
    return scoring


def aggregate(scoring: dict):
    """Calcul agrégats : moyenne par modèle × option × juge."""
    by_combo = defaultdict(list)
    by_cat = defaultdict(lambda: defaultdict(list))

    for q in scoring["per_question"]:
        cat = q["category"]
        for model_name, options in q["scoring"].items():
            for option, judges_out in options.items():
                if isinstance(judges_out, dict) and "empty" in judges_out:
                    continue
                for judge_name, jdata in judges_out.items():
                    s = jdata.get("score") if isinstance(jdata, dict) else None
                    if s is None:
                        continue
                    key = f"{model_name}_{option}_{judge_name}"
                    by_combo[key].append(s)
                    by_cat[cat][key].append(s)

    overall = {}
    for k, vs in by_combo.items():
        overall[k] = {
            "mean": round(sum(vs) / len(vs), 3),
            "n": len(vs),
            "geq_0_85": sum(1 for v in vs if v >= 0.85),
            "geq_0_70": sum(1 for v in vs if v >= 0.70),
            "lt_0_50": sum(1 for v in vs if v < 0.50),
        }

    print("\n" + "=" * 100)
    print("RÉSUMÉ — Mesure 1 : isolation modèle × option × juge")
    print("=" * 100)
    print(f"{'Combination':<55} {'mean':>8} {'≥0.85':>8} {'≥0.70':>8} {'<0.50':>8} {'n':>4}")
    for k in sorted(overall.keys()):
        v = overall[k]
        print(f"{k:<55} {v['mean']:>8.3f} {v['geq_0_85']:>8} {v['geq_0_70']:>8} {v['lt_0_50']:>8} {v['n']:>4}")

    # Comparaison avec Oracle Claude (référence) : 0.938 Llama, 0.911 Qwen
    print("\n" + "=" * 100)
    print("COMPARAISON par modèle, option 1B (top_k=50), juge Llama-3.3-70B")
    print("Oracle Claude Sonnet 4.6 = 0.938 (référence)")
    print("V4.2 dans bench officiel  = 0.087 (référence)")
    print("=" * 100)
    for model in MODELS.keys():
        for option in ["1A", "1B"]:
            for judge in ["llama-3.3-70b", "qwen-2.5-72b"]:
                key = f"{model}_{option}_{judge}"
                m = overall.get(key, {}).get("mean")
                if m is not None:
                    print(f"  {model:<20} {option}  {judge:<20} {m:.3f}")
        print()

    return {"overall": overall, "by_category": {c: dict(d) for c, d in by_cat.items()}}


if __name__ == "__main__":
    print(f"Modèles : {list(MODELS.keys())}")
    print(f"Options : 1A (top_k=15) + 1B (top_k=50)")
    print(f"Total appels génération : 30 q × 3 modèles × 2 options = 180 (parallèle 6)")
    print(f"Total appels scoring    : 180 × 2 juges = 360")
    print()

    results = generation_phase()
    scoring = scoring_phase(results)
    agg = aggregate(scoring)
    scoring["aggregates"] = agg
    with open(OUT_SCORES, "w", encoding="utf-8") as f:
        json.dump(scoring, f, indent=2, ensure_ascii=False)
    print(f"\nFichier final : {OUT_SCORES}")
