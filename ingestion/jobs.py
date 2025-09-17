"""Job payloads executed by the ingestion worker."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, Optional

# Ensure the parent directory of the scripts package is on sys.path.
CANDIDATE_SCRIPT_DIRS = [
    Path('/app/scripts'),
    Path('/scripts'),
]
for candidate in CANDIDATE_SCRIPT_DIRS:
    parent = candidate.parent
    if parent.exists():
        path_str = str(parent)
        if path_str not in sys.path:
            sys.path.append(path_str)


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
    from scripts import ingest_pptx_via_gpt as pptx_module

    path = _ensure_exists(Path(pptx_path))
    if meta_path:
        meta_file = Path(meta_path)
        if meta_file.exists():
            target = path.with_suffix(".meta.json")
            if meta_file != target:
                meta_file.replace(target)
    pptx_module.process_pptx(path, document_type=document_type)
    destination = pptx_module.DOCS_DONE / f"{path.stem}.pptx"
    return {"status": "completed", "output_path": str(destination)}


def ingest_pdf_job(*, pdf_path: str) -> dict[str, Any]:
    from scripts import ingest_pdf_via_gpt as pdf_module

    path = _ensure_exists(Path(pdf_path))
    pdf_module.process_pdf(path)
    destination = pdf_module.DOCS_DONE / f"{path.stem}.pdf"
    return {"status": "completed", "output_path": str(destination)}


def ingest_excel_job(
    *,
    xlsx_path: str,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from scripts import ingest_excel_via_gpt as excel_module

    path = _ensure_exists(Path(xlsx_path))
    meta_dict = meta or {}
    excel_module.process_excel_rfp(path, meta_dict)
    destination = excel_module.DOCS_DONE / path.name
    return {"status": "completed", "output_path": str(destination)}


def fill_excel_job(*, xlsx_path: str, meta_path: str) -> dict[str, Any]:
    from scripts.fill_empty_excel import main as fill_main

    path = _ensure_exists(Path(xlsx_path))
    meta_file = Path(meta_path)
    fill_main(path, meta_file)
    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / "public_files" / "presentations"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{path.stem}_filled.xlsx"
    shutil.move(str(path), destination)
    if meta_file.exists():
        meta_file.unlink()
    return {"status": "completed", "output_path": str(destination)}
