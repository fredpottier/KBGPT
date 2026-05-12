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
import math
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
    """Extrait la reference (ground truth) si disponible.

    Supporte 3 formats :
    1. Gold-set v4 (CH-40.0) : item['ground_truth']['ground_truth_answer']
    2. T1 historique : item['ground_truth_answer'] (à la racine)
    3. V5 chain : item['ground_truth']['chain'][].text
    4. Legacy : item['expected_answer'] / item['reference']
    """
    # Format gold-set v4 : nested ground_truth_answer
    gt = item.get("ground_truth")
    if isinstance(gt, dict):
        # Gold-set v4 : ground_truth.ground_truth_answer
        if gt.get("ground_truth_answer"):
            return gt["ground_truth_answer"]
        # Format V5 : ground_truth.chain[].text
        chain = gt.get("chain", [])
        if chain:
            return " ".join(c.get("text", "") for c in chain if c.get("text"))
        # Fallback : ground_truth.text ou ground_truth.answer
        return gt.get("text", gt.get("answer", ""))
    # Format T1 historique : ground_truth_answer à la racine
    if item.get("ground_truth_answer"):
        return item["ground_truth_answer"]
    # Legacy : expected_answer / reference
    return item.get("expected_answer", item.get("reference", "")) or ""


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
            # CH-40.1 — utilise _extract_reference() pour supporter gold-set v4 schema
            reference = _extract_reference(q_item)

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
    use_reference: bool | None = None,
) -> dict[str, Any]:
    """Execute l'evaluation RAGAS sur les samples.

    Utilise le scoring direct par sample (score/batch_score) au lieu de
    evaluate() qui n'est pas compatible avec les collections metrics v0.4.

    CH-40.1 : si `use_reference=None` (default), FactualCorrectness est
    auto-activé quand au moins 1 sample contient une reference non-vide.
    Pour forcer ON/OFF, passer `use_reference=True` ou `False`.
    """
    from ragas.metrics.collections import (
        Faithfulness,
        ContextRelevance,
        FactualCorrectness,
    )

    llm, embeddings = _get_ragas_providers()

    # CH-40.1 — auto-détection FactualCorrectness depuis les références présentes
    n_with_reference = sum(1 for s in samples if (s.get("reference") or "").strip())
    if use_reference is None:
        use_reference = n_with_reference >= 1
        if use_reference:
            logger.info(
                f"[CH-40.1] FactualCorrectness auto-activé : {n_with_reference}/{len(samples)} samples ont une reference"
            )
        else:
            logger.info(
                "[CH-40.1] FactualCorrectness désactivé : aucun sample avec reference. "
                "Passe `use_reference=True` ou utilise un fichier de questions avec ground_truth_answer."
            )
    elif use_reference and n_with_reference == 0:
        logger.warning(
            "[CH-40.1] FactualCorrectness forcé à True mais 0 sample avec reference — "
            "tous les scores factual_correctness retourneront None"
        )

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
                # CH-40.1 fix : FactualCorrectness.ascore() prend (response, reference)
                # uniquement — pas user_input.
                all_kwargs.append({
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
            # CH-30.18 — filtrer NaN/None pour ne pas propager dans la moyenne
            valid = score is not None and not (isinstance(score, float) and math.isnan(score))
            per_sample[i][metric_name] = round(score, 4) if valid else None
            if valid:
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
            valid = score is not None and not (isinstance(score, float) and math.isnan(score))
            per_sample[idx]["faithfulness_total"] = round(score, 4) if valid else None
            if valid:
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

    Providers pour le juge :
    - "deepinfra" (DEFAUT, CH-09) : Qwen2.5-72B-Instruct via DeepInfra (cohérent avec judge V2)
    - "openai" : gpt-4o-mini via API OpenAI (legacy, à éviter)
    - "ollama" : M-Prometheus-14B via Ollama
    - "llamacpp" : llama.cpp server local

    Embeddings :
    - DeepInfra/Ollama/llamacpp → multilingual-e5-large local (HF)
    - OpenAI → text-embedding-3-small

    Le client est reutilise entre les evaluations OSMOSIS et RAG pour eviter
    l'epuisement du pool de connexions httpx.
    """
    global _ragas_client
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.embeddings import OpenAIEmbeddings

    # CH-09 — défaut DeepInfra pour cohérence avec judge_v2 + éviter OpenAI/Anthropic
    judge_provider = os.getenv("RAGAS_JUDGE_PROVIDER", "deepinfra")

    if judge_provider == "deepinfra":
        # CH-09 — DeepInfra (compatible OpenAI API). Modèle juge : Qwen2.5-72B-Instruct
        # (même que judge_v2.py — cohérent et fail-fast si DEEPINFRA_API_KEY manque).
        di_key = os.environ.get("DEEPINFRA_API_KEY", "").strip()
        if not di_key:
            raise RuntimeError(
                "DEEPINFRA_API_KEY missing. RAGAS_JUDGE_PROVIDER=deepinfra requires the key."
            )
        ragas_model = os.getenv("RAGAS_JUDGE_MODEL", "Qwen/Qwen2.5-72B-Instruct")
        if _ragas_client is None:
            _ragas_client = AsyncOpenAI(
                base_url="https://api.deepinfra.com/v1/openai",
                api_key=di_key,
                max_retries=3,
                timeout=120.0,
            )
        logger.info(f"[RAGAS] Using DeepInfra judge: {ragas_model}")
    elif judge_provider == "ollama":
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

    # Embeddings : local e5-large par défaut (CH-09 — éviter OpenAI), OpenAI uniquement si forcé
    if judge_provider in ("deepinfra", "ollama", "llamacpp"):
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings as LCHFEmb
            from ragas.embeddings import LangchainEmbeddingsWrapper
            emb_model = os.getenv("RAGAS_EMBEDDINGS_MODEL", "intfloat/multilingual-e5-large")
            hf_emb = LCHFEmb(model_name=emb_model)
            embeddings = LangchainEmbeddingsWrapper(hf_emb)
            logger.info(f"[RAGAS] Using local embeddings: {emb_model}")
        except Exception as e:
            # Fallback : refuser plutôt que retomber sur OpenAI (politique CH-09)
            if judge_provider == "deepinfra":
                raise RuntimeError(
                    f"Local embeddings (multilingual-e5-large) failed: {e}. "
                    "RAGAS_JUDGE_PROVIDER=deepinfra refuse OpenAI embeddings fallback. "
                    "Install langchain_community + sentence-transformers, ou utiliser RAGAS_JUDGE_PROVIDER=openai explicitement."
                )
            logger.warning(f"[RAGAS] Local embeddings failed ({e}), falling back to OpenAI")
            embeddings_client = AsyncOpenAI(max_retries=3, timeout=30.0)
            embeddings = OpenAIEmbeddings(client=embeddings_client, model="text-embedding-3-small")
    else:
        # judge_provider == "openai" (legacy explicite)
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
        # CH-40.1 — utilise _extract_reference() pour supporter gold-set v4
        answer = _extract_reference(q)
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
        "label": "Quick (T1 — 50q)",
        "tasks": [
            {
                "name": "T1 Provenance",
                "questions_file": "benchmark/questions/aero_t1_provenance.json",
                "api_search": True,
            },
        ],
    },
    "standard": {
        "label": "Standard (T1 + T5 — 80q)",
        "tasks": [
            {
                "name": "T1 Provenance",
                "questions_file": "benchmark/questions/aero_t1_provenance.json",
                "api_search": True,
            },
            {
                "name": "T5 Cross-doc",
                "questions_file": "benchmark/questions/aero_t5_cross_doc.json",
                "api_search": True,
            },
        ],
    },
    "full": {
        "label": "Full (T1 + T2 + T5 + T6 + T7 — 290q)",
        "tasks": [
            {
                "name": "T1 Provenance",
                "questions_file": "benchmark/questions/aero_t1_provenance.json",
                "api_search": True,
            },
            {
                "name": "T2 Contradictions",
                "questions_file": "benchmark/questions/aero_t2_contradictions.json",
                "api_search": True,
            },
            {
                "name": "T5 Cross-doc",
                "questions_file": "benchmark/questions/aero_t5_cross_doc.json",
                "api_search": True,
            },
            {
                "name": "T6 Robustness",
                "questions_file": "benchmark/questions/aero_t6_robustness.json",
                "api_search": True,
            },
            {
                "name": "T7 V2 anchor",
                "questions_file": "benchmark/questions/aero_t7_v2_anchor.json",
                "api_search": True,
            },
        ],
    },
    # CH-40.1 — gold-set v4 stratifié multilingue avec ground_truth_answer pour
    # FactualCorrectness. 97 questions stratifiées (cf scripts/build_gold_set_v4.py).
    "gold_v4": {
        "label": "Gold-set V4 (S0 calibration — 97q stratifiées)",
        "tasks": [
            {
                "name": "Gold-set V4",
                "questions_file": "benchmark/questions/gold_set_v4.json",
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


def _build_v2_graph_context_text(response_data: dict) -> str:
    """CH-09 — synthétise un `graph_context_text` à partir de la réponse runtime V2.

    Le but : donner au juge RAGAS un contexte enrichi par le KG (claims supplémentaires,
    conflicts détectés, evolution lifecycle, insight hints) pour que `faithfulness_total`
    reflète bien la qualité OSMOSIS V2 sans biais structurel.
    """
    parts: list[str] = []
    claims = response_data.get("claims") or []
    if claims:
        parts.append("KG claims (top retrieved):")
        for c in claims[:5]:
            text = (c.get("text") or "")[:300]
            doc_id = c.get("doc_id", "?")
            pub = c.get("publication_date") or "?"
            parts.append(f"  - [{doc_id}, {pub}] {text}")

    conflicts = response_data.get("conflicts") or []
    if conflicts:
        parts.append("\nKG conflicts (intra-anchor):")
        for cf in conflicts[:3]:
            doc_a = cf.get("doc_a_id", "?")
            doc_b = cf.get("doc_b_id", "?")
            resolved = cf.get("is_resolved_by_lifecycle")
            kind = cf.get("lifecycle_resolution_type")
            tag = f"resolved_by_{kind}" if resolved and kind else "unresolved"
            parts.append(f"  - {doc_a} vs {doc_b} [{tag}]")

    hints = response_data.get("insight_hints") or []
    if hints:
        parts.append("\nKG insights:")
        for h in hints[:5]:
            parts.append(f"  - [{h.get('type', '?')}] {h.get('message', '')[:200]}")

    return "\n".join(parts)


def _call_runtime_v2_api(
    question: str,
    api_base: str,
    token_mgr,
    audit_mode: bool = False,
) -> dict:
    """CH-09 — Call runtime V2 anchor-driven API.
    CH-39 — switch sur runtime V3 si env RUNTIME_VERSION=v3.

    Retourne la même structure que `_call_osmosis_api()` pour rester compatible
    avec le pipeline RAGAS.
    """
    runtime_version = os.getenv("RUNTIME_VERSION", "v2").lower()
    headers = {
        "Authorization": f"Bearer {token_mgr.get()}",
        "Content-Type": "application/json",
    }

    if runtime_version in ("v3", "v4", "v4_2"):
        # V3 / V4 / V4.2 endpoints partagent le même schéma de réponse (rétro-compatible V3)
        endpoint_seg = "v4_2" if runtime_version == "v4_2" else runtime_version
        endpoint_path = f"/api/runtime_{endpoint_seg}/answer"
        # CH-46 L4 — top_k V4 : 20→12 par défaut, override V4_TOP_K_CLAIMS
        top_k_v4 = int(os.getenv("V4_TOP_K_CLAIMS", "12"))
        payload_top_k = top_k_v4 if runtime_version in ("v4", "v4_2") else 10
        payload = {"question": question, "top_k_claims": payload_top_k}
        resp = requests.post(
            f"{api_base}{endpoint_path}",
            json=payload, headers=headers, timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data.get("answer") or ""
        doc_ids = data.get("doc_ids_cited") or []
        # V3/V4 exposent chunks_used (= claims top-K post-rerank, source pour RAGAS contexts)
        # V4.2 retourne chunks_used vide → fallback : pas de contexts pour RAGAS
        chunks_used = data.get("chunks_used") or []
        contexts = [(c.get("text") or "")[:1500] for c in chunks_used[:10] if c.get("text")]
        return {
            "question": question,
            "contexts": contexts,
            "answer": answer,
            "graph_context_text": "",  # V3/V4/V4.2 pas de KG context séparé
            "response_mode": data.get("decision", "ANSWER"),
            "metadata": {
                "doc_ids": doc_ids,
                "decision": data.get("decision"),
                "confidence": data.get("confidence"),
                "false_premise_detected": data.get("false_premise_detected"),
                "faithfulness_score_v3": data.get("faithfulness_score"),
                "faithfulness_verdict_v3": data.get("faithfulness_verdict"),
                "regenerated": data.get("regenerated"),
                "use_kg": True,
                "runtime": runtime_version,
                # V4-specific extras
                "primary_type": data.get("primary_type"),
                "routing_decision": data.get("routing_decision"),
                "rerouter_promoted": data.get("rerouter_promoted"),
                "rerouter_promoted_to": data.get("rerouter_promoted_to"),
                # V4.2-specific extras
                "layer": data.get("layer"),
                "abstention_reason": data.get("abstention_reason"),
                "abstain_category": data.get("abstain_category"),
                "qa_alignment": data.get("qa_alignment"),
                "escalation_reason": data.get("escalation_reason"),
            },
        }

    # Default V2
    payload = {
        "question": question,
        "audit_mode": audit_mode,
        "top_k_claims": 10,
    }
    resp = requests.post(
        f"{api_base}/api/runtime_v2/answer",
        json=payload, headers=headers, timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    # Pour le scoring "chunks-only" classique, on utilise les claims top-K comme contexts
    # (équivalent V2 des chunks Qdrant — sans le contexte KG dérivé).
    claims = data.get("claims") or []
    contexts = [(c.get("text") or "")[:1500] for c in claims[:10] if c.get("text")]

    answer = data.get("synthesized_answer") or ""
    graph_context_text = _build_v2_graph_context_text(data)

    return {
        "question": question,
        "contexts": contexts,
        "answer": answer,
        "graph_context_text": graph_context_text,
        "response_mode": data.get("decision", "ANSWERED"),
        "metadata": {
            "doc_ids": list(data.get("authoritative_doc_ids") or []),
            "anchor_type": (data.get("anchor") or {}).get("anchor_type"),
            "trust_score": data.get("trust_score"),
            "synthesis_entropy": data.get("synthesis_entropy"),
            "answer_gap_classification": data.get("answer_gap_classification"),
            "n_conflicts": len(data.get("conflicts") or []),
            "n_insight_hints": len(data.get("insight_hints") or []),
            "has_kg_context": bool(graph_context_text),
            "use_kg": True,
            "runtime": "v2",
        },
    }


def _call_osmosis_api(
    question: str,
    api_base: str,
    token_mgr,
    use_kg: bool = True,
) -> dict:
    """LEGACY V1.1 — appelle /api/search.

    NOTE CH-30.14 : kept here as the comparative RAG baseline (use_kg=False)
    used by RAGAS to mesure OSMOSIS V2 vs RAG pur. Pour les calls "OSMOSIS V2",
    utiliser `_call_runtime_v2_api` à la place.
    """
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
    api_concurrency = int(os.getenv("BENCHMARK_CONCURRENCY", "3"))
    logger.info(f"[RAGAS:BENCH] Collecting {total} samples via API (use_kg={use_kg}, phase={phase_label}, concurrency={api_concurrency})")

    samples = []
    _progress = [0]

    # CH-09 / CH-30.12 — runtime V2 par défaut (anchor-driven). Pour repasser
    # sur /api/search V1.1, définir RAGAS_USE_RUNTIME_V2=false.
    use_runtime_v2 = os.getenv("RAGAS_USE_RUNTIME_V2", "true").lower() == "true"
    runtime_version = os.getenv("RUNTIME_VERSION", "v2").lower()
    if use_runtime_v2 and use_kg:
        if runtime_version == "v4_2":
            logger.info("[RAGAS:BENCH] Using runtime V4.2 API (/api/runtime_v4_2/answer)")
        elif runtime_version == "v4":
            logger.info("[RAGAS:BENCH] Using runtime V4 API (/api/runtime_v4/answer)")
        elif runtime_version == "v3":
            logger.info("[RAGAS:BENCH] Using runtime V3 API (/api/runtime_v3/answer)")
        else:
            logger.info("[RAGAS:BENCH] Using runtime V2 API (/api/runtime_v2/answer)")

    def _collect_one(i, q_item):
        question = q_item.get("question", q_item.get("query", ""))
        if not question:
            return None

        try:
            if use_runtime_v2 and use_kg:
                sample = _call_runtime_v2_api(question, api_base, token_mgr)
            else:
                sample = _call_osmosis_api(question, api_base, token_mgr, use_kg=use_kg)
            # CH-30.9 / CH-40.1 — supporte aero V2 flat + gold-set v4 nested
            reference = (
                q_item.get("ground_truth_answer")
                or q_item.get("expected_answer")
                or q_item.get("ground_truth", "")
                or q_item.get("verbatim_quote", "")
            )
            if isinstance(reference, dict):
                # CH-40.1 — gold-set v4 : ground_truth.ground_truth_answer (priorité haute)
                if reference.get("ground_truth_answer"):
                    reference = reference["ground_truth_answer"]
                else:
                    chain = reference.get("chain", [])
                    if chain:
                        reference = " ".join(c.get("text", "") for c in chain if c.get("text"))
                    else:
                        # T2 aero format : ground_truth.{claim_a, claim_b}
                        a = reference.get("claim_a") or reference.get("claim1") or {}
                        b = reference.get("claim_b") or reference.get("claim2") or {}
                        if a or b:
                            reference = " | ".join(
                                (x.get("text") if isinstance(x, dict) else str(x or "")) for x in [a, b] if x
                            )
                        else:
                            reference = (
                                reference.get("correct_fact")
                                or reference.get("text")
                                or reference.get("answer", "")
                            )
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
