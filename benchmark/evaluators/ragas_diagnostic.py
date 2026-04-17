#!/usr/bin/env python3
"""
RAGAS Diagnostic — Evaluation structurelle retrieval vs generation.

Objectif : repondre a LA question "le probleme est-il dans le retrieval ou la synthese ?"
sans les biais des juges LLM custom.

Metriques calculees :
- Faithfulness     : la reponse est-elle fidele au contexte fourni ? (detecte hallucinations)
- ContextPrecision : les chunks retrieves contiennent-ils l'info utile ? (diagnostic retrieval)
- FactualCorrectness : la reponse est-elle factuellement correcte vs reference ?
- AnswerRelevancy  : la reponse repond-elle a la question posee ?

Interpretation :
- context_precision haute + faithfulness basse → probleme synthese (LLM hallucine)
- context_precision basse + faithfulness haute → probleme retrieval (mauvais chunks)
- les deux basses → probleme fondamental (chunks ET synthese)
- les deux hautes → systeme fonctionnel

Usage :
    # Depuis un fichier de resultats existant (output du runner)
    python benchmark/evaluators/ragas_diagnostic.py --results data/benchmark/results/osmosis_T1.json

    # Comparaison OSMOSIS vs RAG
    python benchmark/evaluators/ragas_diagnostic.py --results data/benchmark/results/osmosis_T1.json --baseline data/benchmark/results/rag_T1.json

    # Live : interroge l'API et evalue
    python benchmark/evaluators/ragas_diagnostic.py --live --questions benchmark/questions/task1_provenance_kg.json

    # Avec ground truth pour FactualCorrectness
    python benchmark/evaluators/ragas_diagnostic.py --results ... --ground-truth benchmark/questions/task1_provenance_kg.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [RAGAS] %(message)s")
logger = logging.getLogger("ragas-diagnostic")

# ═══════════════════════════════════════════════════════════════════════
# 1. Data Loading — Extraire les triplets (question, contexts, answer)
# ═══════════════════════════════════════════════════════════════════════


def load_results_file(path: str) -> list[dict]:
    """Charge un fichier de resultats benchmark et extrait les triplets."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data if isinstance(data, list) else data.get("results", data.get("questions", []))

    samples = []
    for item in results:
        question = item.get("question", item.get("query", ""))
        if not question:
            continue

        # Extraire les contextes retrieves
        contexts = _extract_contexts(item)
        # Extraire la reponse generee
        answer = _extract_answer(item)
        # Extraire la reference (ground truth) si disponible
        reference = _extract_reference(item)

        if not answer:
            continue

        samples.append({
            "question": question,
            "contexts": contexts,
            "answer": answer,
            "reference": reference,
            "metadata": {
                "doc_ids": _extract_doc_ids(item),
                "scores": _extract_scores(item),
                "has_kg_context": bool(item.get("graph_context")),
            },
        })

    logger.info(f"Loaded {len(samples)} samples from {path}")
    return samples


def _extract_contexts(item: dict) -> list[str]:
    """Extrait les textes des chunks retrieves.

    Supporte plusieurs formats :
    - V5 run: item.response.results[].text
    - Runner direct: item.chunks[].text
    - Live API: item.results[].text
    """
    # Format V5 run (response contient les results)
    resp = item.get("response", {})
    if isinstance(resp, dict):
        results = resp.get("results", [])
        if results and isinstance(results[0], dict):
            return [r.get("text", "") for r in results if r.get("text")]

    # Format runner direct
    chunks = item.get("chunks", item.get("results", []))
    if chunks and isinstance(chunks, list) and chunks and isinstance(chunks[0], dict):
        return [c.get("text", "") for c in chunks if c.get("text")]

    # Format avec context string
    context = item.get("context", item.get("retrieved_context", ""))
    if context:
        return [context] if isinstance(context, str) else context

    return []


def _extract_answer(item: dict) -> str:
    """Extrait la reponse generee.

    Supporte :
    - V5 run: item.response.answer ou item.response.native_synthesis
    - Runner direct: item.answer ou item.native_synthesis
    """
    # Format V5 run (response dict)
    resp = item.get("response", {})
    if isinstance(resp, dict):
        # Preferer native_synthesis (full-pipeline OSMOSIS reel)
        answer = resp.get("native_synthesis") or resp.get("answer", "")
        if answer:
            return answer

    # Format runner direct
    answer = item.get("native_synthesis", "") or item.get("answer", "")
    if answer:
        return answer

    # Fallback string response
    resp_str = item.get("response", "")
    if isinstance(resp_str, str):
        return resp_str

    return ""


def _extract_reference(item: dict) -> str:
    """Extrait la reference (ground truth) si disponible."""
    gt = item.get("ground_truth", item.get("expected_answer", item.get("reference", "")))
    if isinstance(gt, dict):
        # Format V5 : ground_truth.chain[].text
        chain = gt.get("chain", [])
        if chain:
            return " ".join(c.get("text", "") for c in chain if c.get("text"))
        return gt.get("text", gt.get("answer", ""))
    return gt or ""


def _extract_doc_ids(item: dict) -> list[str]:
    """Extrait les IDs de documents impliques."""
    resp = item.get("response", {})
    if isinstance(resp, dict):
        results = resp.get("results", [])
        return list(set(r.get("doc_id", r.get("source_file", "")) for r in results if isinstance(r, dict)))
    chunks = item.get("chunks", [])
    return list(set(c.get("doc_id", c.get("source_file", "")) for c in chunks if isinstance(c, dict)))


def _extract_scores(item: dict) -> list[float]:
    """Extrait les scores de retrieval."""
    resp = item.get("response", {})
    if isinstance(resp, dict):
        results = resp.get("results", [])
        return [r.get("score", 0) for r in results if isinstance(r, dict)]
    chunks = item.get("chunks", [])
    return [c.get("score", 0) for c in chunks if isinstance(c, dict)]


# ═══════════════════════════════════════════════════════════════════════
# 2. Live Collection — Interroger l'API directement
# ═══════════════════════════════════════════════════════════════════════


def collect_live(questions_path: str, api_base: str = "http://localhost:8000") -> list[dict]:
    """Interroge l'API OSMOSIS en live et collecte les triplets."""
    with open(questions_path, "r", encoding="utf-8") as f:
        questions_data = json.load(f)

    questions = questions_data if isinstance(questions_data, list) else questions_data.get("questions", [])

    # Auth (token auto-refresh)
    from benchmark.evaluators._auth import TokenManager
    token_mgr = TokenManager(api_base)

    samples = []
    for i, q_item in enumerate(questions):
        question = q_item.get("question", q_item.get("query", ""))
        if not question:
            continue

        logger.info(f"[{i + 1}/{len(questions)}] {question[:80]}...")

        try:
            headers = {
                "Authorization": f"Bearer {token_mgr.get()}",
                "Content-Type": "application/json",
            }
            resp = requests.post(
                f"{api_base}/api/search",
                json={
                    "question": question,
                    "use_graph_context": True,
                    "graph_enrichment_level": "standard",
                    "use_graph_first": True,
                    "use_kg_traversal": True,
                    "use_latest": True,
                },
                headers=headers,
                timeout=120,
            )

            if resp.status_code != 200:
                logger.warning(f"  HTTP {resp.status_code}")
                continue

            data = resp.json()
            results = data.get("results", [])
            contexts = [r.get("text", "") for r in results[:10] if r.get("text")]
            answer = data.get("synthesis", {}).get("synthesized_answer", "")
            reference = q_item.get("expected_answer", q_item.get("ground_truth", ""))

            samples.append({
                "question": question,
                "contexts": contexts,
                "answer": answer,
                "reference": reference,
                "metadata": {
                    "doc_ids": list(set(r.get("source_file", "") for r in results)),
                    "scores": [r.get("score", 0) for r in results[:10]],
                    "has_kg_context": bool(data.get("graph_context")),
                },
            })

        except Exception as e:
            logger.warning(f"  Error: {e}")
            continue

    logger.info(f"Collected {len(samples)} samples from live API")
    return samples


def _get_token(api_base: str) -> str:
    resp = requests.post(
        f"{api_base}/api/auth/login",
        json={"email": "admin@example.com", "password": "admin123"},
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.json().get("access_token", "")
    raise RuntimeError(f"Auth failed: {resp.status_code}")


# ═══════════════════════════════════════════════════════════════════════
# 3. RAGAS Evaluation
# ═══════════════════════════════════════════════════════════════════════


def run_ragas_evaluation(
    samples: list[dict],
    label: str = "OSMOSIS",
    use_reference: bool = False,
) -> dict[str, Any]:
    """Execute l'evaluation RAGAS sur les samples.

    Utilise le scoring direct par sample (score/batch_score) au lieu de
    evaluate() qui n'est pas compatible avec les collections metrics v0.4.
    """
    from ragas.metrics.collections import (
        Faithfulness,
        ContextRelevance,
        FactualCorrectness,
    )

    llm, embeddings = _get_ragas_providers()

    # Construire les metrics
    # ContextRelevance : evalue si les chunks retrieves sont pertinents pour la question
    # Signature : ascore(user_input, retrieved_contexts) — pas besoin de response ni reference
    # Faithfulness : evalue si la reponse est fidele au contexte fourni (detecte hallucinations)
    # Signature : ascore(user_input, response, retrieved_contexts)
    metrics_map: dict[str, Any] = {
        "faithfulness": Faithfulness(llm=llm),
        "context_relevance": ContextRelevance(llm=llm),
    }
    if use_reference:
        metrics_map["factual_correctness"] = FactualCorrectness(llm=llm)

    # Filtrer les samples valides
    valid_samples = [s for s in samples if s.get("contexts") and s.get("answer")]
    if not valid_samples:
        logger.error("No valid samples for RAGAS evaluation")
        return {}

    logger.info(
        f"Running RAGAS evaluation: {len(valid_samples)} samples, "
        f"{len(metrics_map)} metrics, label={label}"
    )

    start = time.time()
    # Concurrency pour les appels OpenAI juge — plus conservateur que pour
    # les appels API OSMOSIS car la lib openai fait des retries exponentiels
    # qui deadlock avec trop de concurrency (observe empiriquement a 15)
    concurrency = int(os.getenv("RAGAS_CONCURRENCY", "5"))

    # Evaluer chaque metrique en parallele sur tous les samples
    # NOTE: on stocke question + answer complets + quelques metadonnees pour
    # permettre une analyse post-mortem fidele. Pas de troncature arbitraire.
    per_sample = [
        {
            "question_id": s.get("question_id") or s.get("_task_name", "") + f"_{i}",
            "question": s["question"],
            "answer": s.get("answer", ""),
            "answer_length": len(s.get("answer", "")),
            "reference": s.get("reference", ""),
            "sources_used": s.get("metadata", {}).get("doc_ids", []) if isinstance(s.get("metadata"), dict) else [],
            "response_mode": s.get("response_mode", "DIRECT"),
            "has_graph_context": bool(s.get("graph_context_text")),
            "_task_name": s.get("_task_name", ""),
        }
        for i, s in enumerate(valid_samples)
    ]
    metric_totals: dict[str, list[float]] = {k: [] for k in metrics_map}

    # Tronquer les reponses longues pour eviter max_tokens GPT-4o-mini (3072 output)
    MAX_RESPONSE_CHARS = 2000
    MAX_CONTEXT_CHARS = 1500  # par chunk

    for metric_name, metric in metrics_map.items():
        logger.info(f"  Evaluating {metric_name} on {len(valid_samples)} samples (concurrency={concurrency})...")

        all_kwargs = []
        for s in valid_samples:
            response = s["answer"]
            if len(response) > MAX_RESPONSE_CHARS:
                response = response[:MAX_RESPONSE_CHARS] + "..."
            contexts = [c[:MAX_CONTEXT_CHARS] for c in s["contexts"]]

            if metric_name == "context_relevance":
                all_kwargs.append({
                    "user_input": s["question"],
                    "retrieved_contexts": contexts,
                })
            elif metric_name == "factual_correctness":
                all_kwargs.append({
                    "user_input": s["question"],
                    "response": response,
                    "reference": s.get("reference", ""),
                })
            else:
                all_kwargs.append({
                    "user_input": s["question"],
                    "response": response,
                    "retrieved_contexts": contexts,
                })

        scores = asyncio.run(_eval_metric_parallel(metric, all_kwargs, concurrency, metric_name))

        for i, score in enumerate(scores):
            per_sample[i][metric_name] = round(score, 4) if score is not None else None
            if score is not None:
                metric_totals[metric_name].append(score)

        ok_count = sum(1 for s in scores if s is not None)
        logger.info(f"  {metric_name}: {ok_count}/{len(valid_samples)} OK")

    # ── Piste 2 : faithfulness_total (chunks + graph_context_text) ────────
    # Uniquement pour les samples OSMOSIS (pas RAG baseline) qui ont du graph context
    samples_with_kg = [s for s in valid_samples if s.get("graph_context_text")]
    if samples_with_kg and label == "OSMOSIS":
        logger.info(
            f"  [PISTE2] Evaluating faithfulness_total on {len(samples_with_kg)} samples "
            f"with graph context (chunks + KG as evidence)..."
        )
        from ragas.metrics.collections import Faithfulness
        faith_total_metric = Faithfulness(llm=llm)

        # Construire les kwargs avec contexts etendus (chunks + graph_context_text)
        total_kwargs = []
        total_indices = []  # indices dans valid_samples
        for i, s in enumerate(valid_samples):
            if not s.get("graph_context_text"):
                continue
            response = s["answer"]
            if len(response) > MAX_RESPONSE_CHARS:
                response = response[:MAX_RESPONSE_CHARS] + "..."
            # Contextes etendus : chunks + graph_context_text comme contexte additionnel
            contexts = [c[:MAX_CONTEXT_CHARS] for c in s["contexts"]]
            kg_text = s["graph_context_text"][:3000]  # cap pour eviter explosion tokens
            contexts_total = contexts + [kg_text]

            total_kwargs.append({
                "user_input": s["question"],
                "response": response,
                "retrieved_contexts": contexts_total,
            })
            total_indices.append(i)

        total_scores = asyncio.run(
            _eval_metric_parallel(faith_total_metric, total_kwargs, concurrency, "faithfulness_total")
        )

        faith_total_values = []
        for j, score in enumerate(total_scores):
            idx = total_indices[j]
            per_sample[idx]["faithfulness_total"] = round(score, 4) if score is not None else None
            if score is not None:
                faith_total_values.append(score)

        if faith_total_values:
            avg_faith_total = round(sum(faith_total_values) / len(faith_total_values), 4)
            metric_totals["faithfulness_total"] = faith_total_values
            logger.info(
                f"  [PISTE2] faithfulness_total: {avg_faith_total:.4f} "
                f"(vs faithfulness_chunks: {metric_totals.get('faithfulness', [0])[0] if metric_totals.get('faithfulness') else '?'}) "
                f"on {len(faith_total_values)} samples with KG context"
            )

    duration = time.time() - start
    logger.info(f"Total RAGAS evaluation: {duration:.0f}s ({duration/len(valid_samples):.1f}s/sample)")

    # Calculer les moyennes
    avg_scores = {}
    for name, values in metric_totals.items():
        if values:
            avg_scores[name] = round(sum(values) / len(values), 4)

    logger.info(f"RAGAS evaluation completed in {duration:.1f}s — scores: {avg_scores}")

    return {
        "label": label,
        "sample_count": len(valid_samples),
        "duration_s": round(duration, 1),
        "scores": avg_scores,
        "per_sample": per_sample,
    }


async def _eval_metric_parallel(
    metric,
    all_kwargs: list[dict],
    concurrency: int,
    metric_name: str,
) -> list[float | None]:
    """Evalue une metrique RAGAS sur N samples en parallele avec semaphore.

    Fallback automatique sur GPT-4o si GPT-4o-mini echoue (max_tokens).
    """
    semaphore = asyncio.Semaphore(concurrency)
    results: list[float | None] = [None] * len(all_kwargs)
    done_count = 0
    fallback_count = 0

    # Configurable via RAGAS_SAMPLE_TIMEOUT (defaut 300s pour judges 14B locaux)
    SAMPLE_TIMEOUT = int(os.getenv("RAGAS_SAMPLE_TIMEOUT", "300"))

    async def eval_one(idx: int, kwargs: dict):
        nonlocal done_count, fallback_count
        async with semaphore:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(metric.score, **kwargs),
                    timeout=SAMPLE_TIMEOUT,
                )
                score = result.value if hasattr(result, "value") else float(result)
                results[idx] = score
            except asyncio.TimeoutError:
                logger.warning(f"  {metric_name}[{idx}] timeout ({SAMPLE_TIMEOUT}s)")
                results[idx] = None
            except Exception as e:
                err_msg = str(e)
                # Detecter les echecs max_tokens → fallback GPT-4o
                if "max_tokens" in err_msg or "incomplete" in err_msg:
                    try:
                        fallback_metric = _get_fallback_metric(metric, metric_name)
                        if fallback_metric:
                            result = await asyncio.to_thread(fallback_metric.score, **kwargs)
                            score = result.value if hasattr(result, "value") else float(result)
                            results[idx] = score
                            fallback_count += 1
                            logger.info(f"  {metric_name}[{idx}] recovered via GPT-4o fallback")
                        else:
                            results[idx] = None
                    except Exception as e2:
                        logger.warning(f"  {metric_name}[{idx}] fallback also failed: {str(e2)[:80]}")
                        results[idx] = None
                else:
                    logger.warning(f"  {metric_name}[{idx}] failed: {err_msg[:120]}")
                    results[idx] = None
            finally:
                done_count += 1
                if done_count % 10 == 0:
                    logger.info(f"  {metric_name}: {done_count}/{len(all_kwargs)} done...")

    tasks = [eval_one(i, kw) for i, kw in enumerate(all_kwargs)]
    await asyncio.gather(*tasks)

    if fallback_count > 0:
        logger.info(f"  {metric_name}: {fallback_count} samples recovered via GPT-4o fallback")

    return results


# Cache pour les metrics fallback (evite de recreer a chaque sample)
_fallback_metrics_cache: dict[str, Any] = {}


def _get_fallback_metric(original_metric, metric_name: str):
    """Cree une metrique identique mais avec un modele plus capable pour les cas longs.

    En mode cloud : GPT-4o (plus de tokens que gpt-4o-mini).
    En mode Ollama : pas de fallback (meme modele, retourne None).
    """
    if metric_name in _fallback_metrics_cache:
        return _fallback_metrics_cache[metric_name]

    # Pas de fallback en mode Ollama (un seul modele local)
    if os.getenv("RAGAS_JUDGE_PROVIDER", "openai") == "ollama":
        return None

    try:
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
        from ragas.metrics.collections import Faithfulness, ContextRelevance, FactualCorrectness

        client = AsyncOpenAI()
        llm_4o = llm_factory("gpt-4o", client=client)

        metric_classes = {
            "faithfulness": Faithfulness,
            "context_relevance": ContextRelevance,
            "factual_correctness": FactualCorrectness,
        }

        cls = metric_classes.get(metric_name)
        if cls:
            fallback = cls(llm=llm_4o)
            _fallback_metrics_cache[metric_name] = fallback
            logger.info(f"  Created GPT-4o fallback for {metric_name}")
            return fallback
    except Exception as e:
        logger.warning(f"  Could not create fallback metric: {e}")

    return None


_ragas_client = None  # singleton pour eviter l'epuisement du pool de connexions


def _get_ragas_providers():
    """Configure le LLM et embeddings pour RAGAS v0.4+.

    Supporte deux providers pour le juge :
    - "openai" (defaut) : gpt-4o-mini via API OpenAI
    - "ollama" : M-Prometheus-14B via Ollama (API OpenAI-compatible)

    Le client est reutilise entre les evaluations OSMOSIS et RAG pour eviter
    l'epuisement du pool de connexions httpx.

    Les embeddings restent sur OpenAI (text-embedding-3-small) en V1 — cout
    negligeable (~$0.01/benchmark). Migration vers e5-large local en V2.
    """
    global _ragas_client
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.embeddings import OpenAIEmbeddings

    judge_provider = os.getenv("RAGAS_JUDGE_PROVIDER", "openai")

    if judge_provider == "ollama":
        # Mode local : Ollama expose une API OpenAI-compatible sur /v1
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        ragas_model = os.getenv("RAGAS_JUDGE_MODEL", "m-prometheus-14b")
        if _ragas_client is None:
            _ragas_client = AsyncOpenAI(
                base_url=f"{ollama_url}/v1",
                api_key="ollama",  # Ollama n'exige pas de clé
                max_retries=3,
                timeout=120.0,  # Ollama est plus lent que gpt-4o-mini
            )
        logger.info(f"[RAGAS] Using Ollama judge: {ragas_model} at {ollama_url}")
    elif judge_provider == "llamacpp":
        # Mode local : llama.cpp server (ghcr.io/ggml-org/llama.cpp:server-cuda)
        # expose une API OpenAI-compatible sur /v1 sans les limitations d'Ollama
        # (batch eficient, pas de timeout sur modeles >13B).
        llamacpp_url = os.getenv("LLAMACPP_URL", "http://prometheus-judge:8000")
        ragas_model = os.getenv("RAGAS_JUDGE_MODEL", "m-prometheus-14b")
        if _ragas_client is None:
            _ragas_client = AsyncOpenAI(
                base_url=f"{llamacpp_url}/v1",
                api_key="local",
                max_retries=3,
                timeout=300.0,  # 5min pour judge 14B sous contention GPU
            )
        logger.info(f"[RAGAS] Using llama.cpp judge: {ragas_model} at {llamacpp_url}")
    else:
        # Mode cloud : OpenAI standard
        ragas_model = os.getenv("RAGAS_JUDGE_MODEL", "gpt-4o-mini")
        if _ragas_client is None:
            _ragas_client = AsyncOpenAI(
                max_retries=5,
                timeout=60.0,
            )

    llm = llm_factory(ragas_model, client=_ragas_client)

    # Embeddings : local e5-large en mode local (ollama/llamacpp), OpenAI sinon
    if judge_provider in ("ollama", "llamacpp"):
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings as LCHFEmb
            from ragas.embeddings import LangchainEmbeddingsWrapper
            emb_model = os.getenv("RAGAS_EMBEDDINGS_MODEL", "intfloat/multilingual-e5-large")
            hf_emb = LCHFEmb(model_name=emb_model)
            embeddings = LangchainEmbeddingsWrapper(hf_emb)
            logger.info(f"[RAGAS] Using local embeddings: {emb_model}")
        except Exception as e:
            logger.warning(f"[RAGAS] Local embeddings failed ({e}), falling back to OpenAI")
            embeddings_client = AsyncOpenAI(max_retries=3, timeout=30.0)
            embeddings = OpenAIEmbeddings(client=embeddings_client, model="text-embedding-3-small")
    else:
        embeddings = OpenAIEmbeddings(client=_ragas_client, model="text-embedding-3-small")

    return llm, embeddings




# ═══════════════════════════════════════════════════════════════════════
# 4. Diagnostic Report
# ═══════════════════════════════════════════════════════════════════════


def generate_report(
    osmosis_result: dict,
    baseline_result: dict | None = None,
    output_path: str | None = None,
) -> str:
    """Genere un rapport diagnostic lisible."""
    lines = [
        "# RAGAS Diagnostic Report",
        f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
    ]

    # Scores OSMOSIS
    lines.append(f"## {osmosis_result['label']} ({osmosis_result['sample_count']} samples)")
    lines.append("")
    scores = osmosis_result["scores"]
    lines.append("| Metrique | Score | Interpretation |")
    lines.append("|----------|-------|----------------|")
    for metric, score in scores.items():
        interp = _interpret_score(metric, score)
        lines.append(f"| {metric} | **{score:.3f}** | {interp} |")
    lines.append("")

    # Diagnostic
    lines.append("### Diagnostic")
    ctx_prec = scores.get("context_relevance", scores.get("context_precision", 0))
    faith = scores.get("faithfulness", scores.get("Faithfulness", 0))
    lines.append(_diagnose(ctx_prec, faith))
    lines.append("")

    # Comparaison si baseline
    if baseline_result:
        lines.append(f"## Comparaison : {osmosis_result['label']} vs {baseline_result['label']}")
        lines.append("")
        lines.append("| Metrique | OSMOSIS | RAG | Delta |")
        lines.append("|----------|---------|-----|-------|")
        for metric in scores:
            osm = scores.get(metric, 0)
            rag = baseline_result["scores"].get(metric, 0)
            delta = osm - rag
            sign = "+" if delta > 0 else ""
            lines.append(f"| {metric} | {osm:.3f} | {rag:.3f} | **{sign}{delta:.3f}** |")
        lines.append("")

    # Worst samples (diagnostic des echecs)
    per_sample = osmosis_result.get("per_sample", [])
    if per_sample:
        faith_key = "faithfulness" if "faithfulness" in per_sample[0] else "Faithfulness"
        sorted_by_faith = sorted(per_sample, key=lambda x: x.get(faith_key) if x.get(faith_key) is not None else 1.0)
        lines.append("### 5 pires cas (faithfulness la plus basse)")
        lines.append("")
        for s in sorted_by_faith[:5]:
            val = s.get(faith_key)
            val_str = f"{val:.2f}" if val is not None else "N/A"
            lines.append(f"- **{val_str}** — {s['question']}")
        lines.append("")

    report = "\n".join(lines)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info(f"Report saved to {output_path}")

    return report


def _interpret_score(metric: str, score: float) -> str:
    m = metric.lower()
    if "faithful" in m:
        if score >= 0.8:
            return "Reponses fideles au contexte"
        elif score >= 0.6:
            return "Quelques hallucinations"
        else:
            return "Hallucinations frequentes"
    elif "context_precision" in m or "contextprecision" in m:
        if score >= 0.7:
            return "Retrieval trouve les bons chunks"
        elif score >= 0.5:
            return "Retrieval moyen — chunks partiellement pertinents"
        else:
            return "Retrieval faible — mauvais chunks"
    elif "relevancy" in m or "relevance" in m:
        if score >= 0.7:
            return "Reponses pertinentes"
        elif score >= 0.5:
            return "Reponses partiellement hors-sujet"
        else:
            return "Reponses hors-sujet"
    elif "factual" in m:
        if score >= 0.7:
            return "Factuellement correct"
        elif score >= 0.5:
            return "Partiellement correct"
        else:
            return "Erreurs factuelles frequentes"
    return ""


def _diagnose(ctx_precision: float, faithfulness: float) -> str:
    if ctx_precision >= 0.7 and faithfulness >= 0.7:
        return (
            "> **Systeme fonctionnel.** Le retrieval trouve les bons chunks "
            "ET la synthese est fidele. Ameliorations = marginal tuning."
        )
    elif ctx_precision >= 0.7 and faithfulness < 0.7:
        return (
            "> **Probleme de SYNTHESE.** Le retrieval fournit les bons chunks "
            "mais le LLM hallucine ou ignore le contexte. "
            "Actions : ameliorer le prompt, changer de LLM, reduire le contexte."
        )
    elif ctx_precision < 0.7 and faithfulness >= 0.7:
        return (
            "> **Probleme de RETRIEVAL.** Le LLM est fidele a ce qu'il recoit "
            "mais recoit les mauvais chunks. "
            "Actions : ameliorer le chunking, activer hybrid BM25, reranker."
        )
    else:
        return (
            "> **Probleme FONDAMENTAL.** Mauvais chunks ET hallucinations. "
            "Actions : d'abord corriger le retrieval (chunking, embeddings), "
            "puis la synthese."
        )


# ═══════════════════════════════════════════════════════════════════════
# 5. Main
# ═══════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="RAGAS Diagnostic — Retrieval vs Generation")
    parser.add_argument("--results", help="Fichier de resultats OSMOSIS (JSON)")
    parser.add_argument("--baseline", help="Fichier de resultats RAG baseline (JSON) pour comparaison")
    parser.add_argument("--live", action="store_true", help="Mode live : interroger l'API")
    parser.add_argument("--questions", help="Fichier de questions (pour mode live)")
    parser.add_argument("--ground-truth", help="Fichier avec expected_answer pour FactualCorrectness")
    parser.add_argument("--api", default="http://localhost:8000", help="URL API OSMOSIS")
    parser.add_argument("--output", help="Chemin de sortie pour le rapport markdown")
    parser.add_argument("--limit", type=int, help="Limiter le nombre de samples evalues")
    args = parser.parse_args()

    # Collecter les samples
    if args.live:
        if not args.questions:
            parser.error("--questions requis en mode --live")
        samples = collect_live(args.questions, args.api)
    elif args.results:
        samples = load_results_file(args.results)
    else:
        parser.error("--results ou --live requis")

    if args.limit:
        samples = samples[: args.limit]

    # Enrichir avec ground truth si fourni
    use_reference = False
    if args.ground_truth:
        _merge_ground_truth(samples, args.ground_truth)
        use_reference = any(s.get("reference") for s in samples)

    # Evaluer OSMOSIS
    osmosis_result = run_ragas_evaluation(samples, label="OSMOSIS", use_reference=use_reference)
    if not osmosis_result:
        logger.error("RAGAS evaluation failed")
        sys.exit(1)

    # Evaluer baseline si fourni
    baseline_result = None
    if args.baseline:
        baseline_samples = load_results_file(args.baseline)
        if args.limit:
            baseline_samples = baseline_samples[: args.limit]
        baseline_result = run_ragas_evaluation(baseline_samples, label="RAG", use_reference=use_reference)

    # Generer le rapport
    output_path = args.output or f"data/benchmark/results/ragas_diagnostic_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    report = generate_report(osmosis_result, baseline_result, output_path)
    print(report)

    # Sauvegarder aussi en JSON pour exploitation programmatique
    json_path = output_path.replace(".md", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"osmosis": osmosis_result, "baseline": baseline_result, "timestamp": datetime.now(timezone.utc).isoformat()},
            f,
            indent=2,
            ensure_ascii=False,
        )
    logger.info(f"JSON saved to {json_path}")


def _merge_ground_truth(samples: list[dict], gt_path: str):
    """Fusionne les expected_answer depuis le fichier de questions."""
    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)
    gt_list = gt_data if isinstance(gt_data, list) else gt_data.get("questions", [])
    gt_map = {}
    for q in gt_list:
        question = q.get("question", q.get("query", ""))
        answer = q.get("expected_answer", q.get("ground_truth", ""))
        if question and answer:
            gt_map[question.strip().lower()] = answer

    matched = 0
    for s in samples:
        key = s["question"].strip().lower()
        if key in gt_map and not s.get("reference"):
            s["reference"] = gt_map[key]
            matched += 1

    logger.info(f"Merged {matched}/{len(samples)} ground truth references from {gt_path}")


# ═══════════════════════════════════════════════════════════════════════
# 6. Benchmark Job — Execution pilotee par l'API avec progression Redis
# ═══════════════════════════════════════════════════════════════════════

PROFILES: dict[str, dict] = {
    "quick": {
        "label": "Quick (25q)",
        "tasks": [
            {
                "name": "T5 KG Differentiators",
                "questions_file": "benchmark/questions/task5_kg_differentiators.json",
                "api_search": True,
            },
        ],
    },
    "standard": {
        "label": "Standard (100q)",
        "tasks": [
            {
                "name": "T1 Human",
                "questions_file": "benchmark/questions/task1_provenance_human.json",
                "api_search": True,
            },
        ],
    },
    "full": {
        "label": "Full (275q)",
        "tasks": [
            {
                "name": "T1 Human",
                "questions_file": "benchmark/questions/task1_provenance_human.json",
                "api_search": True,
            },
            {
                "name": "T2 Contradictions",
                "questions_file": "benchmark/questions/task2_contradictions_human_v2.json",
                "api_search": True,
            },
            {
                "name": "T4 Audit",
                "questions_file": "benchmark/questions/task4_audit_human.json",
                "api_search": True,
            },
            {
                "name": "T1 KG",
                "questions_file": "benchmark/questions/task1_provenance_kg.json",
                "api_search": True,
            },
        ],
    },
}

REDIS_KEY = "osmose:benchmark:state"
REDIS_TTL = 7200  # 2h


_redis_client = None


def _get_redis(redis_url: str):
    """Singleton Redis client pour eviter de recreer la connexion a chaque appel."""
    global _redis_client
    if _redis_client is None:
        import redis as redis_lib
        _redis_client = redis_lib.from_url(redis_url, decode_responses=True)
    return _redis_client


def _update_redis_state(redis_url: str, state: dict):
    """Met a jour l'etat du benchmark dans Redis avec TTL."""
    try:
        rc = _get_redis(redis_url)
        rc.setex(REDIS_KEY, REDIS_TTL, json.dumps(state, default=str))
    except Exception as e:
        logger.error(f"[RAGAS:BENCH] Redis update failed: {type(e).__name__}: {e}")


def _call_osmosis_api(
    question: str,
    api_base: str,
    token_mgr,
    use_kg: bool = True,
) -> dict:
    """Call OSMOSIS search API and return {question, contexts, answer, metadata}."""
    payload = {
        "question": question,
        "use_graph_context": use_kg,
        "graph_enrichment_level": "standard" if use_kg else "none",
        "use_graph_first": use_kg,
        "use_kg_traversal": use_kg,
        "use_latest": True,
        "skip_tension_summary": True,  # Benchmark : pas besoin des résumés de tensions
    }
    headers = {
        "Authorization": f"Bearer {token_mgr.get()}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{api_base}/api/search",
        json=payload,
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results", [])
    contexts = [r.get("text", "") for r in results[:10] if r.get("text")]
    synthesis = data.get("synthesis", {})
    answer = synthesis.get("synthesized_answer", "") if isinstance(synthesis, dict) else ""

    # Capturer le graph_context_text injecte dans le prompt (piste 2 RAGAS)
    graph_context_text = data.get("graph_context_text", "")
    response_mode = data.get("response_mode", "DIRECT")

    return {
        "question": question,
        "contexts": contexts,
        "answer": answer,
        "graph_context_text": graph_context_text,
        "response_mode": response_mode,
        "metadata": {
            "doc_ids": list(set(r.get("source_file", "") for r in results if isinstance(r, dict))),
            "scores": [r.get("score", 0) for r in results[:10] if isinstance(r, dict)],
            "has_kg_context": bool(graph_context_text),
            "response_mode": response_mode,
            "use_kg": use_kg,
        },
    }


def _get_api_token(api_base: str) -> str:
    """Obtient un token d'authentification depuis l'API OSMOSIS."""
    resp = requests.post(
        f"{api_base}/api/auth/login",
        json={"email": "admin@example.com", "password": "admin123"},
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.json().get("access_token", "")
    raise RuntimeError(f"[RAGAS:BENCH] Auth failed: {resp.status_code}")


def _collect_api_samples(
    tasks: list[dict],
    api_base: str,
    token_mgr,
    redis_url: str,
    use_kg: bool = True,
    phase_label: str = "api_call",
) -> list[dict]:
    """Collecte les samples via l'API OSMOSIS pour toutes les tasks d'un profil."""
    # Charger toutes les questions
    all_questions: list[dict] = []
    for task in tasks:
        qfile = task["questions_file"]
        try:
            with open(qfile, "r", encoding="utf-8") as f:
                qdata = json.load(f)
            qlist = qdata if isinstance(qdata, list) else qdata.get("questions", [])
            for q in qlist:
                q["_task_name"] = task["name"]
            all_questions.extend(qlist)
        except FileNotFoundError:
            logger.warning(f"[RAGAS:BENCH] Questions file not found: {qfile}")
        except Exception as e:
            logger.warning(f"[RAGAS:BENCH] Error loading {qfile}: {e}")

    total = len(all_questions)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    api_concurrency = int(os.getenv("BENCHMARK_CONCURRENCY", "15"))
    logger.info(f"[RAGAS:BENCH] Collecting {total} samples via API (use_kg={use_kg}, phase={phase_label}, concurrency={api_concurrency})")

    samples = []
    _progress = [0]

    def _collect_one(i, q_item):
        question = q_item.get("question", q_item.get("query", ""))
        if not question:
            return None

        try:
            sample = _call_osmosis_api(question, api_base, token_mgr, use_kg=use_kg)
            reference = q_item.get("expected_answer", q_item.get("ground_truth", ""))
            if isinstance(reference, dict):
                chain = reference.get("chain", [])
                if chain:
                    reference = " ".join(c.get("text", "") for c in chain if c.get("text"))
                else:
                    reference = reference.get("text", reference.get("answer", ""))
            sample["reference"] = reference or ""
            sample["_task_name"] = q_item.get("_task_name", "")

            _progress[0] += 1
            if _progress[0] % 5 == 0 or _progress[0] == total:
                _update_redis_state(redis_url, {
                    "status": "running",
                    "phase": phase_label,
                    "progress": _progress[0],
                    "total": total,
                    "current_question": question[:100],
                })
            return sample
        except Exception as e:
            logger.warning(f"[RAGAS:BENCH] API call failed for q={question[:60]}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=api_concurrency) as executor:
        futures = {
            executor.submit(_collect_one, i, q): i
            for i, q in enumerate(all_questions)
        }
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                samples.append(result)

    logger.info(f"[RAGAS:BENCH] Collected {len(samples)}/{total} samples")
    return samples


def run_benchmark_job(
    profile: str = "standard",
    compare_rag: bool = False,
    redis_url: str = "redis://localhost:6379/0",
    tag: str = "",
    description: str = "",
):
    """Execute un benchmark RAGAS complet en arriere-plan.

    Parametres:
        profile: "quick" | "standard" | "full"
        compare_rag: si True, execute aussi le baseline RAG (sans KG)
        tag: Tag optionnel pour identifier le rapport (ex: "BASELINE_PRE_C4")
        description: Description libre du test (ex: "Apres ajout C4 relations")
        redis_url: URL Redis pour les mises a jour de progression
    """
    job_start = time.time()
    api_base = os.getenv("OSMOSIS_API_URL", "http://localhost:8000")

    prof = PROFILES.get(profile)
    if not prof:
        _update_redis_state(redis_url, {
            "status": "failed",
            "error": f"Unknown profile: {profile}",
        })
        return

    logger.info(f"[RAGAS:BENCH] Starting benchmark job — profile={profile} ({prof['label']}), compare_rag={compare_rag}")

    try:
        # ── Phase 0 : Auth ──────────────────────────────────────────
        _update_redis_state(redis_url, {
            "status": "running",
            "profile": profile,
            "phase": "auth",
            "progress": 0,
            "total": 0,
        })
        from benchmark.evaluators._auth import TokenManager
        token_mgr = TokenManager(api_base)
        token_mgr.get()  # force initial fetch to fail fast if creds are wrong

        # ══════════════════════════════════════════════════════════════
        # COLLECTE-FIRST : toutes les collectes d'abord, évaluations ensuite.
        # Cela minimise les swaps de modèle Ollama en mode local :
        #   Collectes (synthèse Qwen) → 1 seul swap → Évaluations (juge M-Prometheus)
        # ══════════════════════════════════════════════════════════════

        # ── Phase 1 : Collecte OSMOSIS (synthèse) ───────────────────
        osmosis_samples = _collect_api_samples(
            tasks=prof["tasks"],
            api_base=api_base,
            token_mgr=token_mgr,
            redis_url=redis_url,
            use_kg=True,
            phase_label="api_call_osmosis",
        )

        if not osmosis_samples:
            _update_redis_state(redis_url, {
                "status": "failed",
                "error": "No samples collected from API",
            })
            return

        # ── Phase 2 : Collecte RAG baseline (même modèle, pas de swap) ─
        rag_samples = None
        if compare_rag:
            _update_redis_state(redis_url, {
                "status": "running",
                "profile": profile,
                "phase": "api_call_rag",
                "progress": 0,
                "total": len(osmosis_samples),
                "current_question": "Collecting RAG baseline...",
            })

            # Force token refresh (le token a pu expirer pendant la collecte OSMOSIS)
            token_mgr._token = None
            logger.info("[RAGAS:BENCH] Token refreshed before RAG baseline collection")

            # Concurrence réduite pour le baseline
            import os as _os
            saved_concurrency = _os.environ.get("BENCHMARK_CONCURRENCY")
            _os.environ["BENCHMARK_CONCURRENCY"] = "5"

            rag_samples = _collect_api_samples(
                tasks=prof["tasks"],
                api_base=api_base,
                token_mgr=token_mgr,
                redis_url=redis_url,
                use_kg=False,
                phase_label="api_call_rag",
            )

            # Restaurer la concurrence
            if saved_concurrency:
                _os.environ["BENCHMARK_CONCURRENCY"] = saved_concurrency
            else:
                _os.environ.pop("BENCHMARK_CONCURRENCY", None)

        # ── Phase 3 : Évaluation OSMOSIS (juge — swap Ollama ici) ──
        _update_redis_state(redis_url, {
            "status": "running",
            "profile": profile,
            "phase": "ragas_eval_osmosis",
            "progress": 0,
            "total": len(osmosis_samples),
            "current_question": "Evaluating OSMOSIS samples...",
        })

        use_reference = any(s.get("reference") for s in osmosis_samples)
        try:
            osmosis_result = run_ragas_evaluation(
                osmosis_samples,
                label="OSMOSIS",
                use_reference=use_reference,
            )
        except Exception as eval_err:
            logger.error(f"[RAGAS:BENCH] OSMOSIS evaluation failed: {eval_err}")
            osmosis_result = {"scores": {}, "per_sample": [], "error": str(eval_err)[:200]}

        # ── Phase 4 : Évaluation RAG (même juge, pas de swap) ──────
        rag_result = None
        if compare_rag and rag_samples:
            import time as _time
            _time.sleep(2)  # Stabiliser le pool httpx entre les deux évaluations

            _update_redis_state(redis_url, {
                "status": "running",
                "profile": profile,
                "phase": "ragas_eval_rag",
                "progress": 0,
                "total": len(rag_samples),
                "current_question": "Evaluating RAG baseline...",
            })
            try:
                rag_result = run_ragas_evaluation(
                    rag_samples,
                    label="RAG",
                    use_reference=use_reference,
                )
            except Exception as eval_err:
                logger.error(f"[RAGAS:BENCH] RAG evaluation failed: {eval_err}")
                rag_result = {"scores": {}, "per_sample": [], "error": str(eval_err)[:200]}

        # ── Phase 4 : Report ────────────────────────────────────────
        _update_redis_state(redis_url, {
            "status": "running",
            "profile": profile,
            "phase": "report",
            "progress": 0,
            "total": 1,
            "current_question": "Generating report...",
        })

        duration_s = round(time.time() - job_start, 1)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tag_suffix = f"_{tag}" if tag else ""
        report_filename = f"ragas_run_{ts}{tag_suffix}.json"

        results_dir = Path("data/benchmark/results")
        results_dir.mkdir(parents=True, exist_ok=True)
        report_path = results_dir / report_filename

        synthesis_model = os.getenv("OSMOSIS_SYNTHESIS_MODEL", "")
        synthesis_provider = os.getenv("OSMOSIS_SYNTHESIS_PROVIDER", "anthropic")
        if not synthesis_model:
            synthesis_model = "claude-haiku-4-5-20251001" if synthesis_provider == "anthropic" else "gpt-4o-mini"

        # V2 config snapshot (reproductibilite benchmark)
        config_snapshot = None
        try:
            from knowbase.common.llm_config import get_usage_config_store
            config_snapshot = get_usage_config_store().snapshot()
        except Exception:
            pass

        report_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "profile": profile,
            "profile_label": prof["label"],
            "tag": tag or "",
            "description": description or "",
            "synthesis_model": synthesis_model,
            "synthesis_provider": synthesis_provider,
            "duration_s": duration_s,
            "config_snapshot": config_snapshot,
            # Format legacy (compatibilité)
            "scores_osmosis": osmosis_result.get("scores", {}),
            "scores_rag": rag_result.get("scores", {}) if rag_result else None,
            "osmosis": osmosis_result,
            "baseline": rag_result,
            "per_sample": osmosis_result.get("per_sample", []),
            # Format frontend (systems.osmosis / systems.baseline)
            "systems": {
                "osmosis": osmosis_result,
                "baseline": rag_result,
            } if rag_result else {
                "osmosis": osmosis_result,
            },
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        logger.info(f"[RAGAS:BENCH] Report saved to {report_path}")

        # ── Termine ─────────────────────────────────────────────────
        _update_redis_state(redis_url, {
            "status": "completed",
            "profile": profile,
            "phase": "report",
            "progress": 1,
            "total": 1,
            "report_file": report_filename,
            "duration_s": duration_s,
            "scores_osmosis": osmosis_result.get("scores", {}),
            "scores_rag": rag_result.get("scores", {}) if rag_result else None,
        })

        logger.info(
            f"[RAGAS:BENCH] Benchmark completed in {duration_s}s — "
            f"OSMOSIS scores: {osmosis_result.get('scores', {})}"
        )

    except Exception as e:
        logger.error(f"[RAGAS:BENCH] Benchmark job failed: {e}", exc_info=True)
        _update_redis_state(redis_url, {
            "status": "failed",
            "profile": profile,
            "error": str(e)[:500],
        })


if __name__ == "__main__":
    main()
