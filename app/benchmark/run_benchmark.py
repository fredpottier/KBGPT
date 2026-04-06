#!/usr/bin/env python3
"""
Orchestrateur principal du benchmark OSMOSIS vs RAG.

Lance toutes les etapes en sequence :
1. Generation des questions (KG-derived)
2. Execution OSMOSIS
3. Execution RAG baseline(s)
4. Evaluation LLM-as-judge
5. Comparaison et rapport

Usage:
    # Test rapide (10 questions, T1 seulement)
    python benchmark/run_benchmark.py --quick

    # Benchmark complet (100 questions, toutes taches)
    python benchmark/run_benchmark.py --full

    # Tache specifique
    python benchmark/run_benchmark.py --task T1 --count 50
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [BENCH] %(message)s")
logger = logging.getLogger("benchmark")


def run_step(description: str, cmd: list, env: dict = None) -> bool:
    """Execute une etape du benchmark."""
    logger.info(f"{'='*60}")
    logger.info(f"STEP: {description}")
    logger.info(f"{'='*60}")

    full_env = {**os.environ, **(env or {})}

    try:
        result = subprocess.run(
            cmd,
            cwd=str(Path(__file__).parent.parent),
            env=full_env,
            timeout=7200,  # 2h max par step (OSMOSIS peut etre lent sans burst)
            capture_output=False,
        )
        if result.returncode != 0:
            logger.error(f"FAILED: {description} (exit code {result.returncode})")
            return False
        logger.info(f"OK: {description}")
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"TIMEOUT: {description}")
        return False
    except Exception as e:
        logger.error(f"ERROR: {description} — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="OSMOSIS Benchmark Orchestrator")
    parser.add_argument("--quick", action="store_true", help="Test rapide (10 questions, T1)")
    parser.add_argument("--full", action="store_true", help="Benchmark complet (100 questions, T1-T4)")
    parser.add_argument("--task", choices=["T1", "T2", "T3", "T4"], default=None)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--config", default="benchmark/config.yaml")
    parser.add_argument("--skip-generate", action="store_true", help="Skip question generation")
    parser.add_argument("--skip-osmosis", action="store_true", help="Skip OSMOSIS run")
    parser.add_argument("--skip-rag", action="store_true", help="Skip RAG baseline run")
    parser.add_argument("--skip-judge", action="store_true", help="Skip LLM judge evaluation")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for OSMOSIS runner")
    parser.add_argument("--include-human", action="store_true", help="Include human-derived questions (doc-only, no KG)")
    parser.add_argument("--human-only", action="store_true", help="Run ONLY human-derived questions")
    args = parser.parse_args()

    python = sys.executable
    config = args.config
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results_dir = Path("benchmark/results") / timestamp
    results_dir.mkdir(parents=True, exist_ok=True)

    # Determiner les parametres
    if args.quick:
        tasks = ["T1"]
        count = 10
    elif args.full:
        tasks = ["T1", "T2", "T4"]  # T3 exclu si pas de donnees temporelles
        count = 100
    else:
        tasks = [args.task] if args.task else ["T1"]
        count = args.count or 20

    # Env avec OPENAI_API_KEY
    env = {}
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                env["OPENAI_API_KEY"] = line.split("=", 1)[1].strip()
            elif line.startswith("ANTHROPIC_API_KEY="):
                env["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()
    env["USERNAME"] = os.environ.get("USERNAME", os.environ.get("USER", "benchmark"))

    logger.info(f"Benchmark: tasks={tasks}, count={count}, results={results_dir}")

    for task in tasks:
        # Determiner quels sets de questions traiter
        question_sets = []
        if not args.human_only:
            question_sets.append(("kg", _task_filename(task, "kg")))
        if args.include_human or args.human_only:
            question_sets.append(("human", _task_filename(task, "human")))

        for q_source, q_filename in question_sets:
            suffix = f"{task}_{q_source}"
            questions_file = f"benchmark/questions/{q_filename}"
            osm_results = str(results_dir / f"osmosis_{suffix}.json")
            rag_results = str(results_dir / f"rag_claim_{suffix}.json")
            osm_judge = str(results_dir / f"judge_osmosis_{suffix}.json")
            rag_judge = str(results_dir / f"judge_rag_claim_{suffix}.json")

            # Step 1: Generate questions
            if not args.skip_generate:
                if q_source == "kg":
                    ok = run_step(
                        f"Generate {task} KG questions ({count})",
                        [python, "benchmark/questions/generate_kg_questions.py",
                         "--config", config, "--task", task, "--count", str(count)],
                        env,
                    )
                else:
                    ok = run_step(
                        f"Generate {task} human questions ({count})",
                        [python, "benchmark/questions/generate_human_questions.py",
                         "--config", config, "--task", task, "--count", str(count)],
                        env,
                    )
                if not ok:
                    logger.warning(f"Skipping {suffix} — question generation failed")
                    continue

            # Verifier que les questions existent
            if not Path(questions_file).exists():
                logger.warning(f"Skipping {suffix} — {questions_file} not found")
                continue

            # Step 2: Run OSMOSIS
            if not args.skip_osmosis:
                run_step(
                    f"Run OSMOSIS on {suffix} ({count} questions)",
                    [python, "benchmark/runners/run_osmosis.py",
                     "--config", config, "--questions", questions_file,
                     "--output", osm_results, "--workers", str(args.workers)],
                    env,
                )

            # Step 3: Run RAG baseline
            if not args.skip_rag:
                run_step(
                    f"Run RAG-claim baseline on {suffix}",
                    [python, "benchmark/baselines/rag_baseline.py",
                     "--config", config, "--questions", questions_file,
                     "--baseline", "rag_claim", "--output", rag_results],
                    env,
                )

            # Step 4: LLM Judge
            if not args.skip_judge:
                if Path(osm_results).exists():
                    run_step(
                        f"LLM Judge — OSMOSIS {suffix}",
                        [python, "benchmark/evaluators/llm_judge.py",
                         "--results", osm_results, "--output", osm_judge],
                        env,
                    )
                if Path(rag_results).exists():
                    run_step(
                        f"LLM Judge — RAG {suffix}",
                        [python, "benchmark/evaluators/llm_judge.py",
                         "--results", rag_results, "--output", rag_judge],
                        env,
                    )

            # Step 5: Compare
            if Path(osm_judge).exists() and Path(rag_judge).exists():
                report_path = str(results_dir / f"report_{suffix}.md")
                run_step(
                    f"Compare OSMOSIS vs RAG — {suffix}",
                    [python, "benchmark/analysis/compare.py",
                     "--osmosis", osm_judge, "--baseline", rag_judge,
                     "--output", report_path],
                    env,
                )

    logger.info(f"\n{'='*60}")
    logger.info(f"BENCHMARK COMPLETE — Results in {results_dir}")
    logger.info(f"{'='*60}")


def _task_filename(task: str, source: str = "kg") -> str:
    mapping_kg = {
        "T1": "task1_provenance_kg.json",
        "T2": "task2_contradictions_kg.json",
        "T3": "task3_temporal_kg.json",
        "T4": "task4_audit_kg.json",
    }
    mapping_human = {
        "T1": "task1_provenance_human.json",
        "T2": "task2_contradictions_human.json",
        "T4": "task4_audit_human.json",
    }
    if source == "human":
        return mapping_human.get(task, f"task_{task.lower()}_human.json")
    return mapping_kg.get(task, f"task_{task.lower()}_kg.json")


if __name__ == "__main__":
    main()
