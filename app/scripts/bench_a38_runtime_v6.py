"""Bench A3.8 — Runtime V6 sur gold-set 50q SAP + 30q ConflictPending.

Mesure les gates ADR §7.1 :
    GA3-5 : C1 ≥ 0.75 sur 50q SAP stratifiées
    GA3-6 : C3 ≥ 0.50 sur sous-set lifecycle (contingence ≥ 0.40)
    GA3-7 : Latence p50 < 30s, p95 < 60s
    GA3-9 : conflict_exposure_rate ≥ 5% sur 30q CP

GA3-3 (filtres bitemporels) déjà couvert par tests unitaires Cypher (test_execute.py).
GA3-4 (CP exposés correctement) sous-test du 30q CP run.

Usage:
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a38_runtime_v6.py'
    docker exec knowbase-app sh -c 'cd /app && python scripts/bench_a38_runtime_v6.py --limit 5'
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("bench_a38")


# ============================================================================
# LLM-judge for C1/C3 (correctness vs ground_truth)
# ============================================================================


JUDGE_SYSTEM_PROMPT = """You are an impartial benchmark judge for a factual QA system over technical documentation.

Compare a candidate ANSWER against a REFERENCE ground truth, given the QUESTION.
Judge ONLY whether the candidate conveys the SAME KEY FACTS as the reference
(identifiers, codes, values, names, conclusions). The candidate need NOT match the
reference in wording, structure, length, or order.

Score guide — RECALL-ORIENTED (key facts present?), NOT style:
- 1.0 : the candidate states ALL the key facts of the reference. Paraphrase, different
        phrasing/order, and ADDITIONAL CORRECT detail are fully acceptable and MUST NOT
        lower the score.
- 0.5 : the candidate states SOME key facts correctly but MISSES at least one important
        reference fact, OR contains a minor inaccuracy alongside otherwise-correct core facts.
- 0.0 : the candidate states WRONG key facts, contradicts the reference, hallucinates,
        or misses essentially all key facts.

RULES (critical):
- Do NOT penalize extra information, added context, verbosity, or stylistic differences,
  as long as they do not CONTRADICT the reference. More correct detail is GOOD, not a fault.
- Exact identifiers matter: reward transaction codes / object names / numbers / dates that
  match the reference; penalize a WRONG or SUBSTITUTED identifier.
- Judge factual content only — never presentation, tone, or completeness of phrasing.

OUTPUT JSON ONLY:
{"score": 0.0|0.5|1.0, "reasoning": "<short: which key facts matched / which missed>"}
"""


_JUDGE_SCORE_REGEX = re.compile(r'"score"\s*:\s*([0-9]*\.?[0-9]+)')


def _parse_judge_response(text: str) -> Optional[Dict[str, Any]]:
    """Parse robuste de la réponse judge.

    Stratégie :
      1. Strip markdown fences
      2. json.loads strict
      3. Si échoue : regex `"score"\s*:\s*<float>` fallback (extrait score même si JSON malformé)

    Returns:
      - {"score": float, "reasoning": str} si parsing OK
      - None si tout a échoué
    """
    if not text or not text.strip():
        return None

    stripped = text.strip()

    # Strip markdown fences
    if stripped.startswith("```"):
        m = re.search(r"```(?:json)?\s*(.+?)\s*```", stripped, re.DOTALL)
        if m:
            stripped = m.group(1).strip()

    # Tentative JSON strict
    try:
        parsed = json.loads(stripped)
        if "score" in parsed:
            score = float(parsed["score"])
            score = max(0.0, min(1.0, score))
            return {"score": score, "reasoning": parsed.get("reasoning", "")}
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Fallback regex sur le score (tolère JSON malformé / texte autour)
    m = _JUDGE_SCORE_REGEX.search(stripped)
    if m:
        try:
            score = float(m.group(1))
            score = max(0.0, min(1.0, score))
            return {"score": score, "reasoning": "[regex_extract] " + stripped[:200]}
        except (ValueError, TypeError):
            pass

    return None


def _judge_call_once(task_type, question: str, answer: str, ground_truth: str) -> Optional[str]:
    """Un seul appel LLM judge. Retourne raw text ou None si exception."""
    try:
        from knowbase.common.llm_router import LLMRouter
        router = LLMRouter()
        user = (
            f"QUESTION: {question}\n\n"
            f"REFERENCE (ground truth): {ground_truth}\n\n"
            f"CANDIDATE ANSWER: {answer}\n\n"
            "Respond with JSON only."
        )
        return router.complete(
            task_type=task_type,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=200,
        )
    except Exception as exc:
        logger.debug("judge call exception: %s", exc)
        return None


_ABSTENTION_MARKERS = (
    "documents indexés contiennent des informations proches",
    "documents indexés ne",
    "aucune information",
    "no relevant claim",
    "ne peut être fournie",
    "prémisse que les documents",
    "risquerait d'être inexact",
)


def _is_abstention(answer: str, mode: Optional[str]) -> bool:
    """Détecte si la réponse candidate est une abstention.

    Priorité au mode pipeline (ABSTENTION), fallback sur marqueurs texte.
    """
    if mode == "ABSTENTION":
        return True
    if not answer:
        return False
    low = answer.lower()
    return any(m.lower() in low for m in _ABSTENTION_MARKERS)


def llm_judge(question: str, answer: str, ground_truth: str,
              answerability: str = "answerable", false_premise: bool = False,
              mode: Optional[str] = None) -> Dict[str, Any]:
    """LLM-judge C1/C3 score (P0.1 + fix anti-overfit abstention 25/05/2026).

    RÈGLE DÉTERMINISTE ANTI-OVERFIT (avant LLM) :
      Une abstention n'est récompensée (1.0) QUE si la question est légitimement
      non-répondable (answerability != "answerable" OU false_premise). Sinon,
      abstenir sur une question répondable = 0.0 (le système n'a pas fait son
      travail). Évite le mirage où le pipeline gagne en abstenant + judge laxiste.

    Stratégie LLM (cas non-abstention) :
      1. 3 tentatives primary LLM (FAST_CLASSIFICATION) — backoff 1s/3s
      2. Si échouent : 1 fallback LLM (LONG_TEXT_SUMMARY = DeepSeek-V3.1)
      3. Si tout échoue : score=None (exclu de l'agrégation)

    Returns:
      {"score": float|None, "reasoning": str, "attempts": int, "used_fallback": bool}
    """
    from knowbase.common.llm_router import TaskType

    # --- Règle déterministe abstention (anti-overfit) ---
    if _is_abstention(answer, mode):
        legitimate_abstention = (answerability != "answerable") or bool(false_premise)
        if legitimate_abstention:
            return {"score": 1.0, "attempts": 0, "used_fallback": False,
                    "reasoning": f"[deterministic] Legitimate abstention "
                                 f"(answerability={answerability}, false_premise={false_premise})"}
        else:
            return {"score": 0.0, "attempts": 0, "used_fallback": False,
                    "reasoning": "[deterministic] Abstention on an ANSWERABLE question "
                                 "(answerability=answerable, not false_premise) → system "
                                 "failed to answer. Score 0.0 (anti-overfit guard)."}

    # Tentatives primary LLM avec backoff exponentiel
    backoffs = [0, 1, 3]  # 1ère tentative immédiate, puis 1s, puis 3s
    for attempt in range(3):
        if backoffs[attempt] > 0:
            time.sleep(backoffs[attempt])
        raw = _judge_call_once(TaskType.FAST_CLASSIFICATION, question, answer, ground_truth)
        if raw is None:
            continue
        parsed = _parse_judge_response(raw)
        if parsed is not None:
            return {
                "score": parsed["score"],
                "reasoning": parsed["reasoning"],
                "attempts": attempt + 1,
                "used_fallback": False,
            }
        logger.debug("judge primary attempt %d/3 unparseable: %r", attempt + 1, raw[:120])

    # Fallback LLM (DeepSeek-V3.1 plus stable sur JSON strict)
    logger.warning("llm_judge: primary 3/3 failed, trying fallback DeepSeek-V3.1")
    raw = _judge_call_once(TaskType.LONG_TEXT_SUMMARY, question, answer, ground_truth)
    if raw is not None:
        parsed = _parse_judge_response(raw)
        if parsed is not None:
            return {
                "score": parsed["score"],
                "reasoning": "[fallback_deepseek] " + parsed["reasoning"],
                "attempts": 4,
                "used_fallback": True,
            }

    # Tout a échoué — return None (exclu de l'agrégation)
    logger.warning("llm_judge failed all 4 attempts (primary + fallback)")
    return {
        "score": None,
        "reasoning": "judge_error_all_attempts_failed",
        "attempts": 4,
        "used_fallback": True,
    }


# ============================================================================
# Conflict exposure check (GA3-9)
# ============================================================================


def has_conflict_exposure(answer_text: str, conflict_pending_warning: Optional[str]) -> bool:
    """Détecte si la réponse expose au moins une contradiction.

    Au moins UN des signaux suivants : warning explicite OU mention ⚠ dans le texte
    OU mots-clés génériques.
    """
    if conflict_pending_warning:
        return True
    if not answer_text:
        return False
    markers = [
        "⚠",
        "conflicting",
        "contradict",
        "divergent",
        "different sources",
        "conflict_pending",
        "non résolu",
        "contradictoire",
    ]
    low = answer_text.lower()
    return any(m.lower() in low for m in markers)


# ============================================================================
# Métriques DÉTERMINISTES (A1) — anti-bruit juge LLM
# ============================================================================

import re as _re

_CODE_RE = _re.compile(r"[A-Z0-9/_]{3,}")
_STOPCODES = {"SAP", "THE", "AND", "FOR", "WITH", "ARE", "NOT", "API", "URL"}


def extract_id_codes(identifiers: List[str]) -> List[str]:
    """Extrait les tokens-codes (CG5Z, /SAPAPO/OM13, P_RCF_STAT, 066, WWI...) des
    `exact_identifiers` du gold-set, en ignorant les mots Title-case et stopwords."""
    out: List[str] = []
    seen = set()
    for s in identifiers or []:
        for tok in _CODE_RE.findall(s or ""):
            t = tok.strip("/_")
            if len(t) < 3 or t.upper() in _STOPCODES:
                continue
            # garde : contient chiffre/_/ OU all-caps ≥4 (code), pas un mot Title-case
            is_code = any(c.isdigit() for c in t) or "_" in tok or "/" in tok or (t.isupper() and len(t) >= 4)
            if is_code and tok.lower() not in seen:
                seen.add(tok.lower())
                out.append(tok)
    return out


def deterministic_metrics(q: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    """exact_id_recall (identifiants attendus présents dans la réponse) + abstention_correct.

    Reproductible, zéro LLM. exact_id_recall=None si la question n'a pas d'identifiant attendu.
    """
    gt = q.get("ground_truth", {}) or {}
    codes = extract_id_codes(gt.get("exact_identifiers"))
    answer = (run.get("answer_text") or "").lower()
    if codes:
        found = [c for c in codes if c.lower() in answer]
        exact_id_recall = len(found) / len(codes)
    else:
        exact_id_recall = None

    # key_term_recall (#442) : recall des PHRASES-clés attendues par substring
    # COMPLET (pas seulement les codes). Ancre déterministe pour les types sans
    # identifiant (contextual/list) ET signal « a-t-il cité les deux côtés ? » sur
    # comparison/contradiction (ex: « 3 inches » ET « 6 inches »). Préfère
    # expected_key_terms, repli sur exact_identifiers (phrase entière).
    key_terms = [str(k).strip() for k in
                 (gt.get("expected_key_terms") or gt.get("exact_identifiers") or [])
                 if str(k).strip()]
    if key_terms:
        kfound = [k for k in key_terms if k.lower() in answer]
        key_term_recall = len(kfound) / len(key_terms)
    else:
        key_term_recall = None

    # abstention_correct : abstention OK ssi unanswerable ; sinon abstention = échec
    answerability = gt.get("answerability", "answerable")
    is_abstention = (run.get("mode") == "ABSTENTION")
    if answerability == "unanswerable":
        abstention_correct = is_abstention
    else:
        abstention_correct = (not is_abstention)

    return {
        "exact_id_recall": exact_id_recall,
        "n_expected_ids": len(codes),
        "key_term_recall": key_term_recall,
        "n_key_terms": len(key_terms),
        "abstention_correct": abstention_correct,
    }


# ============================================================================
# Run a single question via Orchestrator
# ============================================================================


def run_question(orch, question: str, tenant_id: str = "default") -> Dict[str, Any]:
    """Run one question via Orchestrator and capture metrics."""
    t0 = time.perf_counter()
    try:
        result = orch.run(
            question=question,
            tenant_id=tenant_id,
            as_of_date=datetime.now(timezone.utc),
            response_mode="structured",
        )
        dt = time.perf_counter() - t0
        synth = result.synthesize_output
        return {
            "ok": True,
            "duration_s": dt,
            "answer_text": synth.answer_text,
            "mode": synth.mode,
            "n_iterations": len(result.iterations),
            "terminated_reason": result.terminated_reason,
            "conflict_pending_warning": synth.conflict_pending_warning,
            "uncovered_sub_goals_warning": synth.uncovered_sub_goals_warning,
            "citation_coverage_rate": synth.citation_coverage_rate,
            "n_cited_claims": len(synth.cited_claims),
            "synthesize_warnings": synth.synthesize_warnings,
            # Trace minimale par iteration
            "iterations_trace": [it.to_dict() for it in result.iterations],
        }
    except Exception as exc:
        dt = time.perf_counter() - t0
        logger.exception("run_question failed")
        return {
            "ok": False,
            "duration_s": dt,
            "error": str(exc)[:300],
            "answer_text": "",
            "mode": "ERROR",
            "n_iterations": 0,
            "terminated_reason": "exception",
        }


# ============================================================================
# Bench runner
# ============================================================================


def run_bench_50q(orch, gold_path: Path, limit: Optional[int], tenant_id: str = "default") -> List[Dict[str, Any]]:
    with open(gold_path, "r", encoding="utf-8") as f:
        questions = json.load(f)
    if limit:
        questions = questions[:limit]
    logger.info("Bench 50q: %d questions to run (tenant=%s)", len(questions), tenant_id)

    results: List[Dict[str, Any]] = []
    for i, q in enumerate(questions, 1):
        logger.info("[50q %d/%d] type=%s id=%s", i, len(questions),
                    q.get("primary_type"), q.get("id"))
        run = run_question(orch, q["question"], tenant_id)
        # LLM-judge C1 vs ground_truth.answer (+ métadonnées anti-overfit abstention)
        gt = q.get("ground_truth", {})
        gt_answer = gt.get("answer", "")
        if gt_answer and run.get("ok"):
            judge = llm_judge(
                q["question"], run["answer_text"], gt_answer,
                answerability=gt.get("answerability", "answerable"),
                false_premise=gt.get("false_premise", False),
                mode=run.get("mode"),
            )
        else:
            judge = {"score": 0.0, "reasoning": "no_ground_truth_or_run_failed"}
        det = deterministic_metrics(q, run)
        results.append({
            "id": q["id"],
            "primary_type": q.get("primary_type"),
            "language": q.get("language"),
            "question": q["question"],
            "ground_truth_answer": gt_answer,
            "run": run,
            "judge_score": judge["score"],
            "judge_reasoning": judge["reasoning"],
            "judge_attempts": judge.get("attempts"),
            "judge_used_fallback": judge.get("used_fallback", False),
            # A1 — métriques déterministes (décisionnelles, anti-bruit juge)
            "exact_id_recall": det["exact_id_recall"],
            "n_expected_ids": det["n_expected_ids"],
            "key_term_recall": det["key_term_recall"],
            "n_key_terms": det["n_key_terms"],
            "abstention_correct": det["abstention_correct"],
        })
    return results


def run_bench_30q_cp(orch, gold_path: Path, limit: Optional[int], tenant_id: str = "default") -> List[Dict[str, Any]]:
    with open(gold_path, "r", encoding="utf-8") as f:
        questions = json.load(f)
    if limit:
        questions = questions[:limit]
    logger.info("Bench 30q CP: %d questions to run (tenant=%s)", len(questions), tenant_id)

    results: List[Dict[str, Any]] = []
    for i, q in enumerate(questions, 1):
        logger.info("[30q-CP %d/%d] cp_id=%s", i, len(questions), q.get("cp_id"))
        run = run_question(orch, q["question"], tenant_id)
        cp_exposed = has_conflict_exposure(
            run.get("answer_text", ""),
            run.get("conflict_pending_warning"),
        )
        results.append({
            "id": q["id"],
            "cp_id": q.get("cp_id"),
            "question": q["question"],
            "involved_claim_ids": [c.get("claim_id") for c in q.get("involved_claims", [])],
            "run": run,
            "conflict_exposed": cp_exposed,
        })
    return results


# ============================================================================
# Metrics aggregation + gates
# ============================================================================


def aggregate_50q(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcule C1 global + C3 (sous-set lifecycle) + latence + citation.

    P0.1 (23/05/2026) — exclut les judge_score=None (judge a échoué tous attempts)
    de l'agrégation pour éviter le biais 0.0 systématique. Reporte n_judge_failed
    et taux d'erreur pour visibilité.
    """
    n = len(results)
    # Séparer les scores valides (non-None) des judge failures
    valid_scores = [r["judge_score"] for r in results if r["judge_score"] is not None]
    n_judge_failed = sum(1 for r in results if r["judge_score"] is None)
    n_judge_fallback = sum(1 for r in results if r.get("judge_used_fallback"))

    durations = [r["run"]["duration_s"] for r in results if r["run"]["ok"]]
    cit_rates = [r["run"]["citation_coverage_rate"] for r in results
                 if r["run"]["ok"] and r["run"].get("citation_coverage_rate") is not None]

    # Lifecycle sous-set (scores valides seulement)
    lifecycle_scores = [r["judge_score"] for r in results
                        if r.get("primary_type") == "lifecycle"
                        and r["judge_score"] is not None]

    # Per-type (scores valides seulement)
    by_type: Dict[str, List[float]] = {}
    by_type_failures: Dict[str, int] = {}
    for r in results:
        t = r.get("primary_type", "unknown")
        if r["judge_score"] is not None:
            by_type.setdefault(t, []).append(r["judge_score"])
        else:
            by_type_failures[t] = by_type_failures.get(t, 0) + 1
    per_type = {
        t: {
            "n": len(s),
            "mean": statistics.mean(s) if s else 0.0,
            "n_judge_failed": by_type_failures.get(t, 0),
        }
        for t, s in by_type.items()
    }

    # A1 — métriques déterministes (anti-bruit juge)
    id_recalls = [r["exact_id_recall"] for r in results
                  if r.get("exact_id_recall") is not None]
    exact_id_recall_mean = statistics.mean(id_recalls) if id_recalls else None
    abstention_correct_rate = (
        sum(1 for r in results if r.get("abstention_correct")) / n if n else 0.0
    )
    # exact_id_recall par type
    det_by_type: Dict[str, List[float]] = {}
    for r in results:
        if r.get("exact_id_recall") is not None:
            det_by_type.setdefault(r.get("primary_type", "unknown"), []).append(
                r["exact_id_recall"]
            )
    exact_id_recall_per_type = {
        t: {"n": len(v), "mean": statistics.mean(v)} for t, v in det_by_type.items()
    }

    # key_term_recall (#442) — ancre déterministe sur phrases-clés (types sans
    # identifiant + signal « cite-t-il les deux côtés » sur comparison/contradiction)
    kt_recalls = [r["key_term_recall"] for r in results
                  if r.get("key_term_recall") is not None]
    key_term_recall_mean = statistics.mean(kt_recalls) if kt_recalls else None
    kt_by_type: Dict[str, List[float]] = {}
    for r in results:
        if r.get("key_term_recall") is not None:
            kt_by_type.setdefault(r.get("primary_type", "unknown"), []).append(r["key_term_recall"])
    key_term_recall_per_type = {
        t: {"n": len(v), "mean": statistics.mean(v)} for t, v in kt_by_type.items()
    }

    return {
        "n_total": n,
        "n_judge_valid": len(valid_scores),
        "n_judge_failed": n_judge_failed,
        "judge_failure_rate": n_judge_failed / n if n else 0.0,
        "n_judge_fallback_used": n_judge_fallback,
        # Métriques DÉTERMINISTES (décisionnelles)
        "exact_id_recall_mean": exact_id_recall_mean,
        "n_with_expected_ids": len(id_recalls),
        "exact_id_recall_per_type": exact_id_recall_per_type,
        "key_term_recall_mean": key_term_recall_mean,
        "n_with_key_terms": len(kt_recalls),
        "key_term_recall_per_type": key_term_recall_per_type,
        "abstention_correct_rate": abstention_correct_rate,
        # Juge LLM (diagnostic secondaire — bruité)
        "C1_mean": statistics.mean(valid_scores) if valid_scores else 0.0,
        "C3_lifecycle_mean": (statistics.mean(lifecycle_scores)
                              if lifecycle_scores else None),
        "n_lifecycle": len(lifecycle_scores),
        "latency_p50_s": statistics.median(durations) if durations else 0.0,
        "latency_p95_s": (sorted(durations)[int(len(durations) * 0.95)]
                          if len(durations) >= 20
                          else (max(durations) if durations else 0.0)),
        "latency_max_s": max(durations) if durations else 0.0,
        "citation_coverage_mean": statistics.mean(cit_rates) if cit_rates else None,
        "n_run_ok": sum(1 for r in results if r["run"]["ok"]),
        "n_run_failed": sum(1 for r in results if not r["run"]["ok"]),
        "per_type": per_type,
    }


def aggregate_30q_cp(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(results)
    exposed = sum(1 for r in results if r["conflict_exposed"])
    return {
        "n_total": n,
        "n_conflict_exposed": exposed,
        "conflict_exposure_rate": (exposed / n) if n else 0.0,
        "n_run_ok": sum(1 for r in results if r["run"]["ok"]),
        "n_run_failed": sum(1 for r in results if not r["run"]["ok"]),
    }


def compute_gates(agg_50q: Dict[str, Any], agg_30q_cp: Dict[str, Any]) -> Dict[str, Any]:
    """Compute pass/fail for each gate."""
    c1 = agg_50q["C1_mean"]
    c3 = agg_50q.get("C3_lifecycle_mean")
    p50 = agg_50q["latency_p50_s"]
    p95 = agg_50q["latency_p95_s"]
    cp_rate = agg_30q_cp["conflict_exposure_rate"]

    gates = {
        "GA3-5_C1": {
            "value": c1,
            "threshold": 0.75,
            "passed": c1 >= 0.75,
        },
        "GA3-6_C3_lifecycle": {
            "value": c3,
            "threshold": 0.50,
            "contingency_threshold": 0.40,
            "passed": (c3 >= 0.50) if c3 is not None else None,
            "passed_with_contingency": (c3 >= 0.40) if c3 is not None else None,
        },
        "GA3-7_latency": {
            "p50_s": p50,
            "p95_s": p95,
            "thresholds": {"p50_s": 30.0, "p95_s": 60.0},
            "passed_p50": p50 < 30.0,
            "passed_p95": p95 < 60.0,
            "passed": (p50 < 30.0) and (p95 < 60.0),
        },
        "GA3-9_conflict_exposure": {
            "value": cp_rate,
            "threshold": 0.05,
            "passed": cp_rate >= 0.05,
        },
    }
    return gates


# ============================================================================
# Main
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="A3.8 bench runtime_v6")
    parser.add_argument("--gold-50q", type=Path,
                        default=Path("benchmark/questions/gold_set_a38_50q.json"))
    parser.add_argument("--gold-30q-cp", type=Path,
                        default=Path("benchmark/questions/gold_set_a38_30q_cp.json"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("data/benchmark/a38_runtime_v6"))
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit n questions per set (smoke test)")
    parser.add_argument("--skip-50q", action="store_true")
    parser.add_argument("--skip-30q-cp", action="store_true")
    # Protocole non-régression multi-corpus : tenant (corpus chargé) + label corpus.
    parser.add_argument("--tenant", default="default",
                        help="Tenant KG à interroger (corpus). Permet de benchmarker plusieurs corpus coexistants.")
    parser.add_argument("--corpus", default="",
                        help="Label lisible du corpus (ex: aero_seats, sap_presales). Défaut = valeur de --tenant.")
    args = parser.parse_args()

    corpus_label = args.corpus or args.tenant

    # Empreinte du CODE (git sha) — clé du protocole : attribuer une régression au
    # code (même corpus, sha différent) vs au corpus (même sha, corpus différent).
    def _git_sha() -> str:
        # Le conteneur /app n'a pas de .git → priorité à l'env GIT_SHA passé depuis l'hôte
        # (ex: docker exec -e GIT_SHA=$(git rev-parse --short HEAD) …), fallback git local.
        import os as _os, subprocess
        env_sha = _os.getenv("GIT_SHA")
        if env_sha:
            return env_sha.strip()
        for cwd in ("/app", "/app/src", "."):
            try:
                return subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"], cwd=cwd, text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            except Exception:
                continue
        return "unknown"
    git_sha = _git_sha()

    from knowbase.runtime_a3.orchestrator import Orchestrator
    orch = Orchestrator()

    t0 = time.perf_counter()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    results_50q: List[Dict[str, Any]] = []
    results_30q_cp: List[Dict[str, Any]] = []

    if not args.skip_50q:
        results_50q = run_bench_50q(orch, args.gold_50q, args.limit, args.tenant)
    if not args.skip_30q_cp:
        results_30q_cp = run_bench_30q_cp(orch, args.gold_30q_cp, args.limit, args.tenant)

    agg_50q = aggregate_50q(results_50q) if results_50q else {}
    agg_30q_cp = aggregate_30q_cp(results_30q_cp) if results_30q_cp else {}
    gates = compute_gates(agg_50q, agg_30q_cp) if (agg_50q and agg_30q_cp) else {}

    total_duration = time.perf_counter() - t0

    # Print report
    print("\n" + "=" * 70)
    print(f"A3.8 BENCH RUNTIME_V6 — {timestamp}")
    print("=" * 70)
    if agg_50q:
        print("\n50Q SAP STRATIFIÉ:")
        print(f"  n={agg_50q['n_total']} run_ok={agg_50q['n_run_ok']} failed={agg_50q['n_run_failed']}")
        # DÉTERMINISTE (décisionnel)
        eir = agg_50q.get('exact_id_recall_mean')
        if eir is not None:
            print(f"  ★ exact_id_recall : {eir:.3f}  (n={agg_50q['n_with_expected_ids']} q avec identifiants attendus) [DÉTERMINISTE]")
        print(f"  ★ abstention_correct_rate : {agg_50q.get('abstention_correct_rate', 0):.1%} [DÉTERMINISTE]")
        if agg_50q.get('exact_id_recall_per_type'):
            parts = [f"{t}={d['mean']:.2f}(n{d['n']})" for t, d in sorted(agg_50q['exact_id_recall_per_type'].items())]
            print(f"    exact_id_recall/type : {', '.join(parts)}")
        ktr = agg_50q.get('key_term_recall_mean')
        if ktr is not None:
            print(f"  ★ key_term_recall : {ktr:.3f}  (n={agg_50q['n_with_key_terms']} q avec phrases-clés) [DÉTERMINISTE #442]")
            if agg_50q.get('key_term_recall_per_type'):
                parts = [f"{t}={d['mean']:.2f}(n{d['n']})" for t, d in sorted(agg_50q['key_term_recall_per_type'].items())]
                print(f"    key_term_recall/type : {', '.join(parts)}")
        # JUGE LLM (diagnostic secondaire, bruité)
        print(f"  C1 (LLM-judge, bruité) : {agg_50q['C1_mean']:.3f}  [valid={agg_50q['n_judge_valid']}/{agg_50q['n_total']}, judge_failed={agg_50q['n_judge_failed']} ({agg_50q['judge_failure_rate']:.1%}), fallback_used={agg_50q['n_judge_fallback_used']}]")
        if agg_50q['C3_lifecycle_mean'] is not None:
            print(f"  C3 lifecycle ({agg_50q['n_lifecycle']}q) : {agg_50q['C3_lifecycle_mean']:.3f}")
        print(f"  Latency : p50={agg_50q['latency_p50_s']:.1f}s p95={agg_50q['latency_p95_s']:.1f}s max={agg_50q['latency_max_s']:.1f}s")
        if agg_50q.get('citation_coverage_mean') is not None:
            print(f"  Citation coverage : {agg_50q['citation_coverage_mean']:.1%}")
        print("  Per type:")
        for t, st in sorted(agg_50q["per_type"].items()):
            jf = st.get("n_judge_failed", 0)
            jf_suffix = f" judge_failed={jf}" if jf > 0 else ""
            print(f"    {t:20s} n={st['n']:2d} mean={st['mean']:.3f}{jf_suffix}")

    if agg_30q_cp:
        print("\n30Q ConflictPending:")
        print(f"  n={agg_30q_cp['n_total']} exposed={agg_30q_cp['n_conflict_exposed']}")
        print(f"  conflict_exposure_rate : {agg_30q_cp['conflict_exposure_rate']:.1%}")

    if gates:
        print("\nGATES:")
        for k, v in gates.items():
            ok = v.get("passed")
            marker = "✓" if ok is True else ("?" if ok is None else "✗")
            print(f"  {marker} {k}: {v}")

    print(f"\nTotal duration: {total_duration:.1f}s")

    # Persist
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_file = args.output_dir / f"run_{timestamp}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "corpus": corpus_label,
            "tenant": args.tenant,
            "git_sha": git_sha,
            "gold_50q_file": str(args.gold_50q),
            "total_duration_s": total_duration,
            "agg_50q": agg_50q,
            "agg_30q_cp": agg_30q_cp,
            "gates": gates,
            "results_50q": results_50q,
            "results_30q_cp": results_30q_cp,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults: {out_file}")

    # Exit code: 0 si tous gates principaux ✓, 1 sinon
    main_gates = ["GA3-5_C1", "GA3-7_latency", "GA3-9_conflict_exposure"]
    if all(gates.get(g, {}).get("passed") for g in main_gates):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
