"""Validation A1.3.A — Tester DocumentValidFromExtractor sur PDFs SAP réels.

Compare cascade complète (S2>S3>S1+batch_check>S4) vs spike A1.0 naïf.

Usage :
    docker exec knowbase-app python /app/scripts/validate_a13_extractor.py \\
        --corpus-dir /data/docs_done --no-llm
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

from knowbase.ingestion.document_valid_from_extractor import (
    DocumentValidFromExtractor,
    MarkerType,
    S4LLMConfig,
)

logger = logging.getLogger("validate_a13")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus-dir", default="/data/docs_done")
    p.add_argument("--no-llm", action="store_true", help="Désactiver S4 LLM (test cascade sans vLLM)")
    p.add_argument("--vllm-url", default="http://localhost:8000", help="URL vLLM si --no-llm absent")
    p.add_argument("--output", default="/data/a13_validation_results.json")
    args = p.parse_args()

    pdfs = sorted(Path(args.corpus_dir).glob("*.pdf"))
    if not pdfs:
        logger.error(f"Aucun PDF trouvé dans {args.corpus_dir}")
        return

    extractor = DocumentValidFromExtractor(
        s4_config=S4LLMConfig(vllm_url=args.vllm_url),
        enable_s4_llm=not args.no_llm,
    )

    logger.info(f"Validation A1.3.A sur {len(pdfs)} PDFs (S4 LLM {'OFF' if args.no_llm else 'ON'})")

    # 1. Pre-pass batch re-save detection
    suspect = extractor.precompute_batch_re_save(pdfs)
    logger.info(f"Batch re-save : {len(suspect)} dates suspectes détectées")

    # 2. Cascade par PDF
    results = []
    for i, p_path in enumerate(pdfs, 1):
        logger.info(f"[{i}/{len(pdfs)}] {p_path.name}")
        r = extractor.extract(p_path)
        results.append(r)

    # 3. Stats agrégées
    by_marker = Counter(r.marker_type.value for r in results)
    by_source = Counter(r.source or "no_signal" for r in results)
    n_found = sum(1 for r in results if r.value is not None)
    n = len(results)

    print()
    print("=" * 70)
    print(f"Validation A1.3.A — {n} PDFs, S4 LLM {'OFF' if args.no_llm else 'ON'}")
    print("=" * 70)
    print(f"Signal trouvé : {n_found}/{n} = {n_found/n:.1%}")
    print(f"Batch re-save dates suspectes : {sorted(suspect)}")
    print()
    print("Distribution marker_type :")
    for k, v in by_marker.most_common():
        print(f"  {k:25s} {v:3d}")
    print()
    print("Distribution source :")
    for k, v in by_source.most_common():
        print(f"  {k:30s} {v:3d}")
    print()
    print("Détails par PDF :")
    for r in results:
        warn = f" ⚠️ {r.warning}" if r.warning else ""
        print(f"  {r.pdf_name[:60]:60s} → {r.value or 'NULL':12s} ({r.source or '-'}){warn}")

    # 4. Persist
    output = {
        "n_pdfs": n,
        "n_found": n_found,
        "rate": n_found / n,
        "s4_llm_enabled": not args.no_llm,
        "suspect_dates": sorted(suspect),
        "by_marker_type": dict(by_marker),
        "by_source": dict(by_source),
        "results": [
            {
                "pdf": r.pdf_name,
                "value": r.value,
                "marker_type": r.marker_type.value,
                "source": r.source,
                "warning": r.warning,
            }
            for r in results
        ],
        "executed_at": datetime.utcnow().isoformat(),
    }
    Path(args.output).write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Résultats : {args.output}")


if __name__ == "__main__":
    main()
