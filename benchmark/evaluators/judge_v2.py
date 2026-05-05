#!/usr/bin/env python3
"""
Judge V2 — Évaluateur unifié pour les benchmarks aerospace V2 (T1/T2/T5/T6/T7).

Caractéristiques :
- Lit le format JSONL produit par `run_osmosis_v2.py` (1 result par ligne).
- Tape **exclusivement** sur DeepInfra (Qwen2.5-72B-Instruct par défaut).
  Pas de fallback OpenAI ni Anthropic — le bench ne doit jamais cross-pollute.
- Connaît les 5 tasks : T1_provenance, T2_contradictions, T5_cross_doc,
  T6_robustness, T7_v2_anchor.
- Produit un JSON consolidé : metadata + scores agrégés + jugements détaillés.

Usage :
    python benchmark/evaluators/judge_v2.py \\
      --results benchmark/results/smoke_v2_<ts>.jsonl \\
      --output benchmark/results/judge_smoke_v2.json \\
      [--model Qwen/Qwen2.5-72B-Instruct]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("judge-v2")

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
# CH-34 : Llama-3.3-70B-Instruct adopté comme juge officiel (calibration prouvée
# +0.687 vs Prometheus sur 30 cases — Prometheus sous-évaluait massivement).
# Audit le 04/05/2026 : 90% des questions étaient sous-jugées par Prometheus.
DEFAULT_JUDGE_MODEL = "meta-llama/Llama-3.3-70B-Instruct"

# Prometheus (m-prometheus-14b via llama.cpp). Endpoint host : 8082 → container 8000.
PROMETHEUS_BASE_URL = os.environ.get(
    "PROMETHEUS_BASE_URL", "http://localhost:8082/v1"
)
PROMETHEUS_MODEL = os.environ.get(
    "PROMETHEUS_MODEL", "M-Prometheus-14B.i1-Q4_K_M.gguf"
)

JUDGE_SYSTEM = (
    "Tu es un évaluateur rigoureux de systèmes question-réponse documentaire "
    "pour le domaine réglementaire aerospace (CS-25 EASA + dual-use EU). "
    "Tu évalues si une réponse est factuellement correcte, sourcée et complète "
    "par rapport à un ground truth. "
    "Réponds TOUJOURS en JSON valide avec UNIQUEMENT les champs demandés. "
    "Sois strict mais juste."
)


def _client(provider: str = "deepinfra"):
    """Crée un client OpenAI selon le provider :
    - "deepinfra"  → API DeepInfra (Qwen2.5-72B par défaut)
    - "llamacpp"   → Prometheus via llama.cpp local (m-prometheus-14b)

    Le judge bench officiel est Prometheus (CH-30.15/16). DeepInfra reste
    disponible en option de comparaison.
    """
    from openai import OpenAI
    if provider == "llamacpp":
        return OpenAI(api_key="local", base_url=PROMETHEUS_BASE_URL)
    api_key = os.environ.get("DEEPINFRA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "DEEPINFRA_API_KEY missing (provider=deepinfra). "
            "Utilise --judge-provider llamacpp pour Prometheus local."
        )
    return OpenAI(api_key=api_key, base_url=DEEPINFRA_BASE_URL)


# Provider courant (set par main()). Évite de propager le paramètre dans toutes
# les fonctions judge_t1/.../t7.
_PROVIDER: str = "deepinfra"


def call_judge(prompt: str, model: str, provider: str | None = None) -> Dict[str, Any]:
    """Appel LLM judge + parsing JSON robuste."""
    client = _client(provider=provider or _PROVIDER)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600,
            temperature=0,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or "{}"
        tokens = resp.usage.total_tokens if resp.usage else 0
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return {"result": json.loads(clean), "tokens": tokens, "error": None}
    except Exception as e:
        return {"result": {}, "tokens": 0, "error": str(e)}


def _build_doc_context(r: Dict) -> str:
    """Liste compacte des docs cités dans la réponse OSMOSIS V2."""
    docs = r.get("authoritative_doc_ids") or []
    if not docs:
        return "(aucun doc autoritaire cité)"
    return "\n".join(f"- {d}" for d in docs[:10])


# ──────────────────────────────────────────────────────────────────────────
# Juges par task
# ──────────────────────────────────────────────────────────────────────────

def judge_t1_provenance(r: Dict, model: str) -> Dict:
    gt_doc = r.get("ground_truth_doc_id") or "(none)"
    gt_ans = r.get("ground_truth_answer") or ""
    answer = r.get("answer") or ""
    doc_ctx = _build_doc_context(r)
    prompt = f"""Évalue la qualité de cette réponse de provenance (citation directe).

Question : {r.get('question', '')}

Réponse système :
{answer[:2000]}

Documents cités par le système :
{doc_ctx}

Ground truth :
- Document attendu : {gt_doc}
- Réponse de référence : {gt_ans[:500]}
- Citation verbatim attendue (si présente) : {r.get('verbatim_quote', '')[:300]}

Évalue en JSON UNIQUEMENT avec ces champs :
{{
  "factual_correctness": 0.0,
  "correct_doc_cited": false,
  "answer_relevant": false,
  "says_idk_when_info_exists": false,
  "answers_correctly": false,
  "reasoning": "explication courte"
}}

factual_correctness : 0.0-1.0 — la réponse contient-elle le sens du fait attendu (paraphrase OK) ?
correct_doc_cited : true si le doc attendu apparaît dans la liste des docs cités.
answer_relevant : la réponse répond-elle à la question (vs hors sujet) ?
says_idk_when_info_exists : true si le système dit "je ne sais pas" alors que le fait existe (ERREUR).
answers_correctly : synthèse globale — la réponse est-elle correcte ?"""
    return call_judge(prompt, model)


def judge_t2_contradictions(r: Dict, model: str) -> Dict:
    gt_ans = r.get("ground_truth_answer") or ""
    answer = r.get("answer") or ""
    doc_ctx = _build_doc_context(r)
    n_unresolved = r.get("n_conflicts_unresolved", 0)
    prompt = f"""Évalue comment cette réponse traite une potentielle contradiction documentaire.

Question : {r.get('question', '')}

Réponse système :
{answer[:2000]}

Documents cités : {doc_ctx}
Tensions non résolues détectées par le pipeline : {n_unresolved}

Ground truth (résolution attendue) : {gt_ans[:600]}

Évalue en JSON UNIQUEMENT avec ces champs :
{{
  "surfaces_both_sides": false,
  "distinguishes_lifecycle_from_conflict": false,
  "selects_active_value": false,
  "silent_arbitration": false,
  "answers_correctly": false,
  "reasoning": "explication courte"
}}

surfaces_both_sides : la réponse mentionne-t-elle les 2 valeurs/positions en jeu ?
distinguishes_lifecycle_from_conflict : la réponse distingue-t-elle "évolution réglementaire" (LIFECYCLE) d'une vraie contradiction ?
selects_active_value : si une valeur ACTIVE/récente est attendue, la réponse la sélectionne-t-elle ?
silent_arbitration : la réponse choisit-elle un côté sans le justifier (mauvais) ?
answers_correctly : synthèse globale."""
    return call_judge(prompt, model)


def judge_t5_cross_doc(r: Dict, model: str) -> Dict:
    gt_ans = r.get("ground_truth_answer") or ""
    answer = r.get("answer") or ""
    doc_ctx = _build_doc_context(r)
    n_docs = r.get("n_authoritative_docs", 0)
    prompt = f"""Évalue cette synthèse cross-document (chain de raisonnement multi-docs).

Question : {r.get('question', '')}

Réponse système :
{answer[:2500]}

Documents cités ({n_docs}) : {doc_ctx}

Ground truth (chain attendue) : {gt_ans[:800]}

Évalue en JSON UNIQUEMENT avec ces champs :
{{
  "covers_all_chain_elements": false,
  "min_2_docs_cited": false,
  "chronology_correct": false,
  "synthesis_quality": 0.0,
  "answers_correctly": false,
  "reasoning": "explication courte"
}}

covers_all_chain_elements : tous les éléments du ground truth sont-ils mentionnés ?
min_2_docs_cited : au moins 2 docs distincts cités explicitement ?
chronology_correct : si question chronologique, l'ordre est-il correct ?
synthesis_quality : 0.0-1.0 — qualité de la synthèse (cohérence, exhaustivité).
answers_correctly : synthèse globale."""
    return call_judge(prompt, model)


def judge_t6_robustness(r: Dict, model: str) -> Dict:
    answer = r.get("answer") or ""
    cat = r.get("category") or ""
    gt = r.get("ground_truth") or {}
    expected_behavior = gt.get("expected_behavior") if isinstance(gt, dict) else ""
    correct_fact = gt.get("correct_fact") if isinstance(gt, dict) else ""
    doc_ctx = _build_doc_context(r)
    prompt = f"""Évalue la robustesse de cette réponse (catégorie : {cat}).

Question : {r.get('question', '')}

Réponse système :
{answer[:2000]}

Documents cités : {doc_ctx}

Ground truth :
- Comportement attendu : {expected_behavior or 'N/A'}
- Fait correct : {correct_fact[:500] if correct_fact else 'N/A'}

Évalue en JSON UNIQUEMENT avec ces champs :
{{
  "appropriate_behavior": false,
  "factual_when_applicable": false,
  "no_hallucination": false,
  "handles_edge_case": false,
  "answers_correctly": false,
  "reasoning": "explication courte"
}}

appropriate_behavior : la réponse adopte-t-elle le comportement attendu (rejet de prémisse, abstention si unanswerable, raisonnement temporel correct, listage exhaustif, etc.) ?
factual_when_applicable : si une réponse factuelle est attendue, est-elle correcte ?
no_hallucination : la réponse n'invente-t-elle pas d'information absente du corpus ?
handles_edge_case : la réponse gère-t-elle le cas limite spécifique de la catégorie ?
answers_correctly : synthèse globale."""
    return call_judge(prompt, model)


def judge_t7_v2_anchor(r: Dict, model: str) -> Dict:
    answer = r.get("answer") or ""
    cat = r.get("category") or ""
    gt = r.get("ground_truth") or {}
    correct_fact = gt.get("correct_fact") if isinstance(gt, dict) else ""
    expected_anchor = gt.get("expected_anchor") if isinstance(gt, dict) else None
    expected_lifecycle = gt.get("expected_lifecycle_kind") if isinstance(gt, dict) else None
    doc_ctx = _build_doc_context(r)
    actual_anchor_type = r.get("anchor_type")
    actual_anchor_scope = r.get("anchor_scope") or {}
    prompt = f"""Évalue la qualité V2 anchor-driven de cette réponse (catégorie : {cat}).

Question : {r.get('question', '')}

Réponse système :
{answer[:2000]}

Métadonnées V2 :
- anchor_type : {actual_anchor_type}
- anchor_scope : {json.dumps(actual_anchor_scope, ensure_ascii=False)[:200]}
- Documents autoritaires : {doc_ctx}

Ground truth V2 :
- Fait correct : {correct_fact[:500] if correct_fact else 'N/A'}
- Anchor attendu : {expected_anchor or 'N/A'}
- Lifecycle kind attendu : {expected_lifecycle or 'N/A'}

Évalue en JSON UNIQUEMENT avec ces champs :
{{
  "correct_anchor_resolution": false,
  "lifecycle_aware": false,
  "filters_deprecated_correctly": false,
  "distinguishes_active_from_obsolete": false,
  "answers_correctly": false,
  "reasoning": "explication courte"
}}

correct_anchor_resolution : la réponse cite-t-elle le bon anchor (ou un anchor pertinent) ?
lifecycle_aware : la réponse traite-t-elle correctement la dimension lifecycle (SUPERSEDES, EVOLVES_FROM, ACTIVE/DEPRECATED) ?
filters_deprecated_correctly : la réponse évite-t-elle de citer des sources DEPRECATED comme applicables aujourd'hui ?
distinguishes_active_from_obsolete : la réponse distingue-t-elle clairement l'actif de l'obsolète ?
answers_correctly : synthèse globale."""
    return call_judge(prompt, model)


JUDGE_FN = {
    "T1_provenance": judge_t1_provenance,
    "T2_contradictions": judge_t2_contradictions,
    "T5_cross_doc": judge_t5_cross_doc,
    "T6_robustness": judge_t6_robustness,
    "T7_v2_anchor": judge_t7_v2_anchor,
}


# ──────────────────────────────────────────────────────────────────────────
# Agrégation des scores
# ──────────────────────────────────────────────────────────────────────────

def aggregate(judgments: List[Dict]) -> Dict[str, Any]:
    if not judgments:
        return {}
    by_task: Dict[str, List[Dict]] = {}
    for j in judgments:
        t = j.get("task") or "unknown"
        by_task.setdefault(t, []).append(j.get("judgment") or {})

    out: Dict[str, Any] = {"n_total": len(judgments)}
    for task, jl in by_task.items():
        n = len(jl)
        out[task] = {"n": n}
        # Calcul des moyennes / taux pour chaque champ booléen ou flottant
        if not jl:
            continue
        keys: set = set()
        for v in jl:
            if isinstance(v, dict):
                keys.update(v.keys())
        for k in sorted(keys):
            if k == "reasoning":
                continue
            vals = [v.get(k) for v in jl if isinstance(v, dict) and v.get(k) is not None]
            if not vals:
                continue
            if all(isinstance(x, bool) for x in vals):
                out[task][f"{k}_rate"] = sum(1 for x in vals if x) / len(vals)
            elif all(isinstance(x, (int, float)) for x in vals):
                out[task][f"{k}_avg"] = sum(vals) / len(vals)
    return out


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def main():
    global _PROVIDER
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, help="JSONL output from run_osmosis_v2.py")
    parser.add_argument("--output", required=True, help="Path to write the judgment JSON")
    parser.add_argument(
        "--judge-provider",
        choices=["deepinfra", "llamacpp"],
        default=os.environ.get("JUDGE_PROVIDER", "llamacpp"),
        help="Judge provider : llamacpp (Prometheus local, défaut) ou deepinfra (Qwen2.5-72B)",
    )
    parser.add_argument("--model", default=None,
                        help=f"Model id (default per provider: deepinfra={DEFAULT_JUDGE_MODEL}, llamacpp={PROMETHEUS_MODEL})")
    parser.add_argument("--rate-limit-ms", type=int, default=50,
                        help="Sleep between calls (default 50ms)")
    args = parser.parse_args()
    _PROVIDER = args.judge_provider
    if args.model is None:
        args.model = PROMETHEUS_MODEL if _PROVIDER == "llamacpp" else DEFAULT_JUDGE_MODEL

    in_path = Path(args.results)
    if not in_path.exists():
        raise SystemExit(f"Results file not found: {in_path}")

    rows: List[Dict] = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    logger.info("Loaded %d results from %s", len(rows), in_path)
    logger.info("Judge provider=%s model=%s", _PROVIDER, args.model)

    judgments: List[Dict] = []
    total_tokens = 0
    errors = 0

    for i, r in enumerate(rows, 1):
        task = r.get("task") or "T1_provenance"
        fn = JUDGE_FN.get(task)
        if fn is None:
            logger.warning("[%d/%d] %s — no judge for task %s, skipping", i, len(rows), r.get("question_id"), task)
            continue

        if r.get("error"):
            logger.warning("[%d/%d] %s — runner error, skipping: %s", i, len(rows), r.get("question_id"), r["error"])
            judgments.append({
                "question_id": r.get("question_id"),
                "task": task,
                "judgment": {},
                "error": f"runner_error: {r['error']}",
            })
            continue

        logger.info("[%d/%d] judging %s (task=%s)…", i, len(rows), r.get("question_id"), task)
        out = fn(r, args.model)
        if out.get("error"):
            errors += 1
            logger.warning("  judge error: %s", out["error"])
        total_tokens += out.get("tokens", 0)
        judgments.append({
            "question_id": r.get("question_id"),
            "task": task,
            "category": r.get("category"),
            "judgment": out["result"],
            "error": out.get("error"),
        })
        if args.rate_limit_ms:
            time.sleep(args.rate_limit_ms / 1000.0)

    scores = aggregate(judgments)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "metadata": {
            "judge_model": args.model,
            "judge_provider": _PROVIDER,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "source_results": str(in_path),
            "total_tokens": total_tokens,
            "n_results": len(rows),
            "n_judgments": len(judgments),
            "n_judge_errors": errors,
        },
        "scores": scores,
        "judgments": judgments,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("Saved → %s", out_path)
    logger.info("Tokens used (DeepInfra): %d", total_tokens)
    print("\n=== SCORES ===")
    for task, s in scores.items():
        if task == "n_total":
            print(f"n_total = {s}")
            continue
        print(f"\n[{task}] (n={s.get('n', 0)})")
        for k, v in sorted(s.items()):
            if k == "n":
                continue
            if isinstance(v, float):
                print(f"  {k:<48} {v:.3f}")
            else:
                print(f"  {k:<48} {v}")


if __name__ == "__main__":
    main()
