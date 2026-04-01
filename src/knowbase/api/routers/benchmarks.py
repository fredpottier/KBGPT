"""API endpoint pour les resultats de benchmark."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import redis
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BENCHMARK_REDIS_KEY = "osmose:benchmark:state"
T2T5_REDIS_KEY = "osmose:benchmark:t2t5:state"

RESULTS_DIR = Path("data/benchmark/results")
# Fallback paths
RESULTS_DIR_ALT = Path("/data/benchmark/results")
RESULTS_DIR_LOCAL = Path("benchmark/results")


def _get_results_dir() -> Path:
    for d in [RESULTS_DIR, RESULTS_DIR_ALT, RESULTS_DIR_LOCAL]:
        if d.exists():
            return d
    return RESULTS_DIR


def _get_all_results_dirs() -> list[Path]:
    """Retourne toutes les directories de resultats qui existent."""
    return [d for d in [RESULTS_DIR, RESULTS_DIR_ALT, RESULTS_DIR_LOCAL] if d.exists()]


@router.get("")
async def get_benchmark_runs() -> dict[str, Any]:
    """Liste les runs de benchmark disponibles avec leurs scores."""
    results_dir = _get_results_dir()

    if not results_dir.exists():
        return {"runs": []}

    runs = []
    # Chercher les sous-dossiers (YYYYMMDD_HHMMSS ou YYYYMMDD_label)
    run_dirs = sorted(
        [d for d in results_dir.iterdir() if d.is_dir() and d.name[:8].isdigit()],
        reverse=True,
    )

    for run_dir in run_dirs[:5]:
        # Primary judge files (not .claude.json)
        judge_files = sorted(
            f for f in run_dir.glob("judge_*.json")
            if ".claude." not in f.name
        )
        if not judge_files:
            continue

        # Secondary judge files (.claude.json) for cross-validation
        claude_files = {f.name.replace(".claude.json", ".json"): f
                        for f in run_dir.glob("judge_*.claude.json")}

        tasks = []
        for jf in judge_files:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                parts = jf.stem.replace("judge_", "").split("_")
                task_match = next((p for p in parts if p.startswith("T") and len(p) == 2), None)
                valid_sources = ("kg", "human", "additional", "pptx")
                source = parts[-1] if parts[-1] in valid_sources else "kg"
                system = "_".join(parts[:parts.index(task_match)]) if task_match and task_match in parts else "unknown"

                scores = data.get("scores", {})

                # Cross-validation : comparer avec le juge Claude si disponible
                divergences: dict[str, Any] = {}
                claude_file = claude_files.get(jf.name)
                if claude_file and claude_file.exists():
                    try:
                        claude_data = json.loads(claude_file.read_text(encoding="utf-8"))
                        claude_scores = claude_data.get("scores", {})
                        for metric, value in scores.items():
                            if metric == "total_evaluated" or not isinstance(value, (int, float)):
                                continue
                            claude_val = claude_scores.get(metric)
                            if isinstance(claude_val, (int, float)):
                                delta = abs(value - claude_val)
                                if delta > 0.15:  # Seuil de divergence significative
                                    divergences[metric] = {
                                        "primary": round(value, 3),
                                        "secondary": round(claude_val, 3),
                                        "delta": round(delta, 3),
                                        "secondary_judge": claude_data.get("metadata", {}).get("judge_model", "claude"),
                                    }
                    except Exception:
                        pass

                task_entry: dict[str, Any] = {
                    "task": task_match or data.get("metadata", {}).get("task", "?"),
                    "source": source,
                    "system": system,
                    "scores": scores,
                    "metadata": data.get("metadata", {}),
                    "judgments_count": len(data.get("judgments", [])),
                }
                if divergences:
                    task_entry["divergences"] = divergences

                tasks.append(task_entry)
            except Exception as e:
                logger.warning(f"Error reading {jf}: {e}")

        if tasks:
            runs.append({"timestamp": run_dir.name, "tasks": tasks})

    return {"runs": runs}


# ── RAGAS Diagnostic Reports ──────────────────────────────────────────


def _compute_ragas_diagnostic(scores: dict[str, float]) -> dict[str, Any]:
    """Calcule un diagnostic a partir des scores RAGAS."""
    faith = scores.get("faithfulness")
    ctx = scores.get("context_relevance")
    factual = scores.get("factual_correctness")

    level = "unknown"
    message = "Donnees insuffisantes pour un diagnostic."
    color = "gray"

    if faith is not None and ctx is not None:
        if faith >= 0.8 and ctx >= 0.8:
            level = "good"
            message = "Retrieval ET generation sont performants."
            color = "green"
        elif faith >= 0.8 and ctx < 0.8:
            level = "retrieval_issue"
            message = (
                "Le LLM genere fidelement a partir du contexte, "
                "mais le retrieval ne ramene pas les bons passages. "
                "Priorite : ameliorer le chunking ou le retrieval."
            )
            color = "orange"
        elif faith < 0.8 and ctx >= 0.8:
            level = "generation_issue"
            message = (
                "Le retrieval ramene les bons passages, "
                "mais le LLM hallucine ou deforme les faits. "
                "Priorite : ameliorer le prompt de synthese ou changer de modele."
            )
            color = "red"
        else:
            level = "both_issues"
            message = (
                "Probleme double : le retrieval est faible ET le LLM hallucine. "
                "Commencer par ameliorer le retrieval, puis la generation."
            )
            color = "red"

    return {"level": level, "message": message, "color": color}


def _parse_ragas_report(filepath: Path) -> dict[str, Any] | None:
    """Parse un fichier ragas_*.json et retourne un resume structure."""
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Erreur lecture RAGAS {filepath}: {e}")
        return None

    timestamp = data.get("timestamp", "")
    result: dict[str, Any] = {
        "filename": filepath.name,
        "timestamp": timestamp,
        "tag": data.get("tag", ""),
        "description": data.get("description", ""),
        "synthesis_model": data.get("synthesis_model", ""),
        "profile": data.get("profile", ""),
        "systems": {},
    }

    for system_key in ("osmosis", "baseline"):
        sys_data = data.get(system_key)
        if sys_data is None:
            continue

        scores = sys_data.get("scores", {})
        per_sample = sys_data.get("per_sample", [])

        # Worst 5 by faithfulness — exclude null (eval failure, not system quality)
        valid_samples = [s for s in per_sample if s.get("faithfulness") is not None]
        sorted_samples = sorted(valid_samples, key=lambda s: s["faithfulness"])
        worst_5 = sorted_samples[:5]

        diagnostic = _compute_ragas_diagnostic(scores)

        result["systems"][system_key] = {
            "label": sys_data.get("label", system_key),
            "sample_count": sys_data.get("sample_count", len(per_sample)),
            "duration_s": sys_data.get("duration_s"),
            "scores": scores,
            "diagnostic": diagnostic,
            "worst_samples": worst_5,
        }

    return result


@router.get("/ragas")
async def get_ragas_reports() -> dict[str, Any]:
    """Liste les rapports RAGAS disponibles (10 plus recents)."""
    # Deduplication par filename (meme fichier peut etre dans plusieurs dirs)
    seen: dict[str, Path] = {}
    for results_dir in _get_all_results_dirs():
        for f in results_dir.glob("ragas_*.json"):
            if f.name not in seen:
                seen[f.name] = f

    if not seen:
        return {"reports": []}

    reports = []
    for filepath in seen.values():
        report = _parse_ragas_report(filepath)
        if report:
            reports.append(report)

    # Trier par timestamp decroissant
    reports.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

    return {"reports": reports[:10]}


# ── RAGAS Benchmark Run Endpoints ────────────────────────────────────
# NOTE: Ces routes /ragas/run, /ragas/progress, /ragas/compare DOIVENT
# etre declarees AVANT /ragas/{filename} pour eviter que FastAPI ne
# matche "progress"/"compare"/"run" comme un {filename}.


def _get_redis_client() -> redis.Redis:
    """Obtient un client Redis pour les operations benchmark."""
    return redis.from_url(REDIS_URL, decode_responses=True)


class RagasRunRequest(BaseModel):
    profile: str = "standard"  # quick | standard | full
    compare_rag: bool = False
    tag: str = ""  # Tag pour identifier le rapport (ex: "BASELINE_PRE_C4")
    description: str = ""  # Description libre du test


@router.post("/ragas/run")
async def run_ragas_benchmark(
    req: RagasRunRequest,
) -> dict[str, Any]:
    """Lance un benchmark RAGAS via le worker RQ (process stable, pas de timeout).

    Profiles:
    - quick: 25 questions (T5 KG Differentiators)
    - standard: 100 questions (T1 Human)
    - full: 275 questions (T1 Human + T2 Contradictions + T4 Audit + T1 KG)
    """
    from benchmark.evaluators.ragas_diagnostic import PROFILES

    if req.profile not in PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Profile inconnu: {req.profile}. Valides: {list(PROFILES.keys())}",
        )

    # Verifier qu'aucun run n'est deja en cours
    try:
        rc = _get_redis_client()
        raw = rc.get(BENCHMARK_REDIS_KEY)
        if raw:
            state = json.loads(raw)
            if state.get("status") == "running":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Un benchmark est deja en cours "
                        f"(profile={state.get('profile')}, phase={state.get('phase')}). "
                        f"Attendez qu'il se termine."
                    ),
                )
    except redis.RedisError as e:
        logger.warning(f"[RAGAS:BENCH] Redis check failed: {e}")

    job_id = str(uuid.uuid4())[:8]
    logger.info(
        f"[RAGAS:BENCH] Launching benchmark job_id={job_id} "
        f"profile={req.profile} compare_rag={req.compare_rag}"
    )

    # Initialiser l'etat Redis
    try:
        rc = _get_redis_client()
        rc.setex(
            BENCHMARK_REDIS_KEY,
            7200,
            json.dumps({
                "status": "starting",
                "job_id": job_id,
                "profile": req.profile,
                "phase": "init",
                "progress": 0,
                "total": 0,
            }),
        )
    except redis.RedisError as e:
        logger.warning(f"[RAGAS:BENCH] Redis init failed: {e}")

    # Enqueue dans le worker RQ (process stable, pas de timeout BackgroundTasks)
    from rq import Queue as RQQueue
    q = RQQueue("benchmark", connection=rc)
    rq_job = q.enqueue(
        "benchmark.evaluators.ragas_diagnostic.run_benchmark_job",
        kwargs={
            "profile": req.profile,
            "compare_rag": req.compare_rag,
            "redis_url": REDIS_URL,
            "tag": req.tag,
            "description": req.description,
        },
        job_id=job_id,
        job_timeout=7200,  # 2h max
        result_ttl=3600,
    )

    prof = PROFILES[req.profile]
    return {
        "job_id": job_id,
        "profile": req.profile,
        "label": prof["label"],
        "compare_rag": req.compare_rag,
        "message": f"Benchmark RAGAS lance ({prof['label']})",
    }


@router.get("/ragas/progress")
async def get_ragas_progress() -> dict[str, Any]:
    """Retourne la progression du benchmark RAGAS en cours."""
    try:
        rc = _get_redis_client()
        raw = rc.get(BENCHMARK_REDIS_KEY)
        if not raw:
            return {"status": "idle", "message": "Aucun benchmark en cours ou recent"}

        state = json.loads(raw)
        return state

    except redis.RedisError as e:
        logger.warning(f"[RAGAS:BENCH] Redis read failed: {e}")
        return {"status": "unknown", "error": str(e)}


@router.get("/ragas/compare")
async def compare_ragas_runs(
    a: str = Query(..., description="Nom du premier fichier de rapport"),
    b: str = Query(..., description="Nom du deuxieme fichier de rapport"),
) -> dict[str, Any]:
    """Compare deux rapports RAGAS. a et b sont des noms de fichiers."""
    # Securite
    for fname in (a, b):
        if "/" in fname or "\\" in fname or ".." in fname:
            raise HTTPException(status_code=400, detail=f"Nom de fichier invalide: {fname}")

    def _load_report(filename: str) -> dict:
        for results_dir in _get_all_results_dirs():
            filepath = results_dir / filename
            if filepath.exists():
                return json.loads(filepath.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail=f"Rapport {filename} introuvable")

    report_a = _load_report(a)
    report_b = _load_report(b)

    # Extraire les scores (format ragas_run_*.json ou ragas_diagnostic_*.json)
    scores_a = report_a.get("scores_osmosis") or report_a.get("osmosis", {}).get("scores", {})
    scores_b = report_b.get("scores_osmosis") or report_b.get("osmosis", {}).get("scores", {})

    # Calculer les deltas par metrique
    all_metrics = set(list(scores_a.keys()) + list(scores_b.keys()))
    metric_deltas = {}
    for m in all_metrics:
        va = scores_a.get(m)
        vb = scores_b.get(m)
        if va is not None and vb is not None:
            metric_deltas[m] = {
                "a": round(va, 4),
                "b": round(vb, 4),
                "delta": round(vb - va, 4),
            }

    # Comparer per_sample par faithfulness pour trouver regressions/ameliorations
    per_sample_a = report_a.get("per_sample") or report_a.get("osmosis", {}).get("per_sample", [])
    per_sample_b = report_b.get("per_sample") or report_b.get("osmosis", {}).get("per_sample", [])

    # Indexer par question
    map_a = {s.get("question", ""): s for s in per_sample_a}
    map_b = {s.get("question", ""): s for s in per_sample_b}

    sample_deltas = []
    for q in set(map_a.keys()) | set(map_b.keys()):
        sa = map_a.get(q, {})
        sb = map_b.get(q, {})
        fa = sa.get("faithfulness")
        fb = sb.get("faithfulness")
        if fa is not None and fb is not None:
            sample_deltas.append({
                "question": q,
                "faithfulness_a": round(fa, 4),
                "faithfulness_b": round(fb, 4),
                "delta": round(fb - fa, 4),
            })

    # Top 5 regressions (delta le plus negatif) et ameliorations (delta le plus positif)
    sample_deltas.sort(key=lambda x: x["delta"])
    top_regressions = sample_deltas[:5]
    top_improvements = sample_deltas[-5:][::-1]

    return {
        "file_a": a,
        "file_b": b,
        "timestamp_a": report_a.get("timestamp", ""),
        "timestamp_b": report_b.get("timestamp", ""),
        "metric_deltas": metric_deltas,
        "top_regressions": top_regressions,
        "top_improvements": top_improvements,
    }


@router.delete("/ragas/{filename}")
async def delete_ragas_report(filename: str) -> dict[str, Any]:
    """Supprime un rapport RAGAS."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")

    deleted = False
    for results_dir in _get_all_results_dirs():
        filepath = results_dir / filename
        if filepath.exists():
            filepath.unlink()
            deleted = True
            logger.info(f"[RAGAS:BENCH] Deleted report: {filepath}")

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Rapport {filename} introuvable")

    return {"deleted": filename, "message": "Rapport supprime"}


# ── RAGAS Report Detail (DOIT etre apres /ragas/run, /ragas/progress, /ragas/compare) ──


@router.get("/ragas/{filename}")
async def get_ragas_report_detail(filename: str) -> dict[str, Any]:
    """Retourne le detail complet d'un rapport RAGAS."""
    # Securite : empecher path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")

    for results_dir in _get_all_results_dirs():
        filepath = results_dir / filename
        if filepath.exists():
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                return {"filename": filename, "data": data}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Erreur lecture: {e}")

    raise HTTPException(status_code=404, detail=f"Rapport {filename} introuvable")


# ═══════════════════════════════════════════════════════════════════════
# T2/T5 Diagnostic Benchmark Endpoints
# ═══════════════════════════════════════════════════════════════════════


class T2T5RunRequest(BaseModel):
    profile: str = "standard"  # quick | standard | full
    tag: str = ""  # Tag pour identifier le rapport (ex: "BASELINE_PRE_C4")
    description: str = ""  # Description libre du test
    compare_rag: bool = False  # Si True, execute aussi en mode RAG pur


@router.post("/t2t5/run")
async def run_t2t5_benchmark(
    req: T2T5RunRequest,
) -> dict[str, Any]:
    """Lance un benchmark T2/T5 deterministe via le worker RQ.

    Profiles:
    - quick: 25 questions (T5 KG Differentiators)
    - standard: 50 questions (T2 Expert + T5 KG Differentiators)
    - full: 175 questions (T2 Expert + T2 KG + T5 KG Differentiators)
    """
    from benchmark.evaluators.t2t5_diagnostic import T2T5_PROFILES

    if req.profile not in T2T5_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Profile inconnu: {req.profile}. Valides: {list(T2T5_PROFILES.keys())}",
        )

    # Verifier qu'aucun run T2T5 n'est deja en cours
    try:
        rc = _get_redis_client()
        raw = rc.get(T2T5_REDIS_KEY)
        if raw:
            state = json.loads(raw)
            if state.get("status") == "running":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Un benchmark T2/T5 est deja en cours "
                        f"(profile={state.get('profile')}, phase={state.get('phase')}). "
                        f"Attendez qu'il se termine."
                    ),
                )
    except redis.RedisError as e:
        logger.warning(f"[T2T5:BENCH] Redis check failed: {e}")

    job_id = str(uuid.uuid4())[:8]
    logger.info(
        f"[T2T5:BENCH] Launching benchmark job_id={job_id} profile={req.profile}"
    )

    # Initialiser l'etat Redis
    try:
        rc = _get_redis_client()
        rc.setex(
            T2T5_REDIS_KEY,
            7200,
            json.dumps({
                "status": "starting",
                "job_id": job_id,
                "profile": req.profile,
                "phase": "init",
                "progress": 0,
                "total": 0,
            }),
        )
    except redis.RedisError as e:
        logger.warning(f"[T2T5:BENCH] Redis init failed: {e}")

    # Enqueue dans le worker RQ (queue benchmark)
    from rq import Queue as RQQueue
    q = RQQueue("benchmark", connection=rc)
    rq_job = q.enqueue(
        "benchmark.evaluators.t2t5_diagnostic.run_benchmark_job",
        kwargs={
            "profile": req.profile,
            "redis_url": REDIS_URL,
            "tag": req.tag,
            "description": req.description,
            "compare_rag": req.compare_rag,
        },
        job_id=job_id,
        job_timeout=7200,
        result_ttl=3600,
    )

    prof = T2T5_PROFILES[req.profile]
    return {
        "job_id": job_id,
        "profile": req.profile,
        "label": prof["label"],
        "message": f"Benchmark T2/T5 lance ({prof['label']})",
    }


@router.get("/t2t5/progress")
async def get_t2t5_progress() -> dict[str, Any]:
    """Retourne la progression du benchmark T2/T5 en cours."""
    try:
        rc = _get_redis_client()
        raw = rc.get(T2T5_REDIS_KEY)
        if not raw:
            return {"status": "idle", "message": "Aucun benchmark T2/T5 en cours ou recent"}

        state = json.loads(raw)
        return state

    except redis.RedisError as e:
        logger.warning(f"[T2T5:BENCH] Redis read failed: {e}")
        return {"status": "unknown", "error": str(e)}


@router.get("/t2t5")
async def get_t2t5_reports() -> dict[str, Any]:
    """Liste les rapports T2/T5 disponibles (10 plus recents)."""
    seen: dict[str, Path] = {}
    for results_dir in _get_all_results_dirs():
        for f in results_dir.glob("t2t5_*.json"):
            if f.name not in seen:
                seen[f.name] = f

    if not seen:
        return {"reports": []}

    reports = []
    for filepath in seen.values():
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            reports.append({
                "filename": filepath.name,
                "timestamp": data.get("timestamp", ""),
                "tag": data.get("tag", ""),
                "description": data.get("description", ""),
                "synthesis_model": data.get("synthesis_model", ""),
                "profile": data.get("profile", ""),
                "profile_label": data.get("profile_label", ""),
                "duration_s": data.get("duration_s"),
                "scores": data.get("scores", {}),
                "total_evaluated": data.get("scores", {}).get("total_evaluated", 0),
                "errors": data.get("errors", 0),
            })
        except Exception as e:
            logger.warning(f"Erreur lecture T2T5 {filepath}: {e}")

    reports.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return {"reports": reports[:10]}


@router.get("/t2t5/{filename}")
async def get_t2t5_report_detail(filename: str) -> dict[str, Any]:
    """Retourne le detail complet d'un rapport T2/T5."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")

    for results_dir in _get_all_results_dirs():
        filepath = results_dir / filename
        if filepath.exists():
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                return {"filename": filename, "data": data}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Erreur lecture: {e}")

    raise HTTPException(status_code=404, detail=f"Rapport {filename} introuvable")


@router.delete("/t2t5/{filename}")
async def delete_t2t5_report(filename: str) -> dict[str, Any]:
    """Supprime un rapport T2/T5."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")

    deleted = False
    for results_dir in _get_all_results_dirs():
        filepath = results_dir / filename
        if filepath.exists():
            filepath.unlink()
            deleted = True
            logger.info(f"[T2T5:BENCH] Deleted report: {filepath}")

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Rapport {filename} introuvable")

    return {"deleted": filename, "message": "Rapport supprime"}


# ════════════════════════════════════════════════════════════════════════
# ── ROBUSTESSE ENDPOINTS ───────────────────────────────────────────────
# ════════════════════════════════════════════════════════════════════════


@router.get("/robustness")
async def get_robustness_reports() -> dict[str, Any]:
    """Liste les rapports robustesse (10 plus recents)."""
    seen: dict[str, Path] = {}
    for results_dir in _get_all_results_dirs():
        for f in results_dir.glob("robustness_run_*.json"):
            if f.name not in seen:
                seen[f.name] = f

    reports = []
    for filepath in seen.values():
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            reports.append({
                "filename": filepath.name,
                "timestamp": data.get("timestamp", ""),
                "tag": data.get("tag", ""),
                "description": data.get("description", ""),
                "synthesis_model": data.get("synthesis_model", ""),
                "duration_s": data.get("duration_s"),
                "scores": data.get("scores", {}),
                "errors": data.get("errors", 0),
            })
        except Exception as e:
            logger.warning(f"Erreur lecture robustness {filepath}: {e}")

    reports.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return {"reports": reports[:10]}


@router.get("/robustness/progress")
async def get_robustness_progress():
    """Progression du benchmark robustesse en cours."""
    try:
        rc = _get_redis_client()
        state_raw = rc.get("osmose:benchmark:robustness:state")
        if state_raw:
            return json.loads(state_raw)
    except Exception:
        pass
    return {"status": "idle"}


@router.get("/robustness/{filename}")
async def get_robustness_report_detail(filename: str) -> dict[str, Any]:
    """Detail complet d'un rapport robustesse (avec per_sample)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    for results_dir in _get_all_results_dirs():
        filepath = results_dir / filename
        if filepath.exists():
            return json.loads(filepath.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail=f"Rapport {filename} introuvable")


@router.delete("/robustness/{filename}")
async def delete_robustness_report(filename: str) -> dict[str, Any]:
    """Supprime un rapport robustesse."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    for results_dir in _get_all_results_dirs():
        filepath = results_dir / filename
        if filepath.exists():
            filepath.unlink()
            return {"deleted": filename}
    raise HTTPException(status_code=404, detail=f"Rapport {filename} introuvable")


class RobustnessRunRequest(BaseModel):
    tag: str = ""
    description: str = ""


@router.post("/robustness/run")
async def run_robustness_benchmark(req: RobustnessRunRequest):
    """Lance un benchmark robustesse via RQ worker."""
    rc = _get_redis_client()
    try:
        state_raw = rc.get("osmose:benchmark:robustness:state")
        if state_raw:
            state = json.loads(state_raw)
            if state.get("status") == "running":
                raise HTTPException(status_code=409, detail="Benchmark robustesse deja en cours")
    except redis.RedisError:
        pass

    job_id = os.urandom(4).hex()
    rc.setex("osmose:benchmark:robustness:state", 7200, json.dumps({
        "status": "starting", "job_id": job_id, "progress": 0, "total": 0,
    }))

    from rq import Queue as RQQueue
    q = RQQueue("benchmark", connection=rc)
    q.enqueue(
        "benchmark.evaluators.robustness_diagnostic.run_benchmark_job",
        kwargs={"redis_url": REDIS_URL, "tag": req.tag, "description": req.description},
        job_id=job_id, job_timeout=7200, result_ttl=3600,
    )
    return {"job_id": job_id, "message": "Benchmark robustesse lance"}
