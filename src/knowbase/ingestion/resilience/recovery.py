"""
Recovery — Reprise des jobs interrompus au démarrage worker.

P4 polish — utilise JobManager pour scanner les jobs en {pending, processing,
post_import, paused} et les ré-enqueue dans RQ pour reprise depuis le dernier
checkpoint sauvegardé.

Usage :
  # Au démarrage worker, ou via cron / one-shot
  python -m knowbase.ingestion.resilience.recovery --tenant default
"""
from __future__ import annotations

import logging
from typing import Optional

from knowbase.ingestion.resilience.job_manager import JobManager
from knowbase.ingestion.resilience.job_state import JobState, JobStateEnum

logger = logging.getLogger(__name__)


def list_recoverable_jobs(
    job_manager: Optional[JobManager] = None,
    max_age_hours: int = 24,
) -> list[JobState]:
    """Liste les jobs candidats à la reprise.

    Critères :
    - state ∈ {pending, processing, post_import, paused}
    - updated_at < max_age_hours (sinon trop vieux, considéré abandonné)
    - retries < 3 (anti-loop)
    """
    from datetime import datetime, timedelta

    job_manager = job_manager or JobManager()
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    active = job_manager.list_active_jobs()

    candidates = []
    for job in active:
        if job.retries >= 3:
            logger.info(f"[Recovery] Skip {job.doc_id} — max retries reached ({job.retries})")
            continue
        try:
            updated = datetime.fromisoformat(job.updated_at.rstrip("Z"))
        except ValueError:
            continue
        if updated < cutoff:
            logger.info(f"[Recovery] Skip {job.doc_id} — too old (updated {job.updated_at})")
            continue
        candidates.append(job)

    return candidates


def determine_resume_strategy(job: JobState) -> str:
    """Détermine quoi faire avec un job interrompu.

    Returns une string décrivant la stratégie :
    - 'restart_full' : reprendre depuis l'extraction (rien de persisté)
    - 'persist_only' : extraction faite, juste relancer le persist
    - 'post_import_only' : claims persistés, juste relancer le post-import
    - 'requeue_initial' : pending → simplement re-enqueue
    """
    cp = job.last_checkpoint

    if job.state == JobStateEnum.PENDING:
        return "requeue_initial"

    if cp is None:
        return "restart_full"

    phase = cp.phase
    if phase == "extract":
        return "restart_full"
    elif phase == "post_extract":
        return "persist_only"
    elif phase == "post_claim_persist":
        return "post_import_only"
    elif phase == "done":
        return "noop"
    else:
        return "restart_full"


def recover_all(
    job_manager: Optional[JobManager] = None,
    dry_run: bool = False,
    max_age_hours: int = 24,
) -> dict:
    """Boucle de reprise.

    Pour chaque job actif candidat, appelle determine_resume_strategy et
    affiche/applique la décision.

    Si dry_run=True : affiche seulement, pas d'enqueue.

    Returns dict {n_candidates, n_requeued, n_skipped, by_strategy}.
    """
    job_manager = job_manager or JobManager()
    candidates = list_recoverable_jobs(job_manager, max_age_hours=max_age_hours)

    stats = {
        "n_candidates": len(candidates),
        "n_requeued": 0,
        "n_skipped": 0,
        "by_strategy": {},
    }

    for job in candidates:
        strategy = determine_resume_strategy(job)
        stats["by_strategy"][strategy] = stats["by_strategy"].get(strategy, 0) + 1
        cp_phase = job.last_checkpoint.phase if job.last_checkpoint else "(none)"
        logger.info(
            f"[Recovery] {job.doc_id} state={job.state.value} "
            f"checkpoint={cp_phase} → strategy={strategy}"
        )

        if dry_run:
            stats["n_skipped"] += 1
            continue

        if strategy == "noop":
            stats["n_skipped"] += 1
            continue

        try:
            from knowbase.ingestion.queue.dispatcher import enqueue_claimfirst_process

            # Increment retries pour anti-loop
            job.retries += 1
            job_manager.update_state(
                job.doc_id, JobStateEnum.PENDING,
                checkpoint=job.last_checkpoint,
            )

            # Pour l'instant, requeue full ClaimFirst (l'orchestrator gère ses propres
            # checkpoints idempotents via MERGE Cypher). Strategy fine sera implémentée
            # en P4 fermeture si besoin.
            cf_job = enqueue_claimfirst_process(
                doc_ids=[job.doc_id],
                tenant_id="default",
            )
            logger.info(
                f"[Recovery] Re-enqueued {job.doc_id} as RQ job {cf_job.id} "
                f"(retry {job.retries})"
            )
            stats["n_requeued"] += 1
        except Exception as exc:
            logger.error(f"[Recovery] Failed to requeue {job.doc_id}: {exc}")
            stats["n_skipped"] += 1

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-age-hours", type=int, default=24)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    stats = recover_all(dry_run=args.dry_run, max_age_hours=args.max_age_hours)
    print(f"\n=== Recovery summary (dry_run={args.dry_run}) ===")
    print(f"  candidates  : {stats['n_candidates']}")
    print(f"  re-enqueued : {stats['n_requeued']}")
    print(f"  skipped     : {stats['n_skipped']}")
    if stats["by_strategy"]:
        print(f"  strategies  :")
        for s, n in stats["by_strategy"].items():
            print(f"    - {s}: {n}")


if __name__ == "__main__":
    main()
