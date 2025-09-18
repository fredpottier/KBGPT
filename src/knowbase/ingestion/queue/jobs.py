from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from knowbase.config.settings import get_settings
from knowbase.ingestion.pipelines import (
    excel_pipeline,
    fill_excel_pipeline,
    pdf_pipeline,
    pptx_pipeline,
)


SETTINGS = get_settings()
PRESENTATIONS_DIR = SETTINGS.presentations_dir


def _ensure_exists(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path


def ingest_pptx_job(
    *,
    pptx_path: str,
    document_type: str = "default",
    meta_path: Optional[str] = None,
) -> dict[str, Any]:
    path = _ensure_exists(Path(pptx_path))
    if meta_path:
        meta_file = Path(meta_path)
        if meta_file.exists():
            target = path.with_suffix(".meta.json")
            if meta_file != target:
                meta_file.replace(target)
    pptx_pipeline.process_pptx(path, document_type=document_type)
    destination = pptx_pipeline.DOCS_DONE / f"{path.stem}.pptx"
    return {"status": "completed", "output_path": str(destination)}


def ingest_pdf_job(*, pdf_path: str) -> dict[str, Any]:
    path = _ensure_exists(Path(pdf_path))
    pdf_pipeline.process_pdf(path)
    destination = pdf_pipeline.DOCS_DONE / f"{path.stem}.pdf"
    return {"status": "completed", "output_path": str(destination)}


def ingest_excel_job(
    *,
    xlsx_path: str,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    path = _ensure_exists(Path(xlsx_path))
    meta_dict = meta or {}
    excel_pipeline.process_excel_rfp(path, meta_dict)
    destination = excel_pipeline.DOCS_DONE / path.name
    return {"status": "completed", "output_path": str(destination)}


def fill_excel_job(*, xlsx_path: str, meta_path: str) -> dict[str, Any]:
    path = _ensure_exists(Path(xlsx_path))
    meta_file = Path(meta_path)
    fill_excel_pipeline.main(path, meta_file)
    output_dir = PRESENTATIONS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{path.stem}_filled.xlsx"
    path.replace(destination)
    if meta_file.exists():
        meta_file.unlink()
    return {"status": "completed", "output_path": str(destination)}


__all__ = [
    "ingest_pptx_job",
    "ingest_pdf_job",
    "ingest_excel_job",
    "fill_excel_job",
]
