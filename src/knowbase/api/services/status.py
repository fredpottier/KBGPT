from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from knowbase.config.settings import get_settings
from knowbase.ingestion.queue import fetch_job

PUBLIC_URL = os.getenv("PUBLIC_URL", "sapkb.ngrok.app")


def job_status(uid: str) -> dict[str, Any]:
    job = fetch_job(uid)
    if job is None:
        return {"action": "unknown", "status": "not_found"}

    job_type = str(job.meta.get("job_type", "unknown"))
    status = job.get_status(refresh=True)

    if job.is_failed:
        return {"action": job_type, "status": "error", "message": job.exc_info}

    if job.is_finished:
        result = job.result if isinstance(job.result, dict) else {}
        response: dict[str, Any] = {"action": job_type, "status": "done"}
        output_path = result.get("output_path")
        if output_path:
            filename = os.path.basename(output_path)
            response["download_url"] = f"https://{PUBLIC_URL}/static/presentations/{filename}"
        if result:
            response["result"] = result
        return response

    if status in {"started", "queued", "deferred"}:
        return {"action": job_type, "status": "processing"}

    return {"action": job_type, "status": status}


__all__ = ["job_status"]
