#!/usr/bin/env python3
"""
Backfill V2-S1 — LIFECYCLE_RELATION Doc→Doc strict.

Conformément à VISION_RECENTREE_OSMOSIS_2026-04-30 §1bis et
ADR_LIFECYCLE_VS_LOGICAL_RELATIONS (version stricte) :
- Aucune inférence persistée
- Persistence UNIQUEMENT sur déclaration textuelle explicite
- LLM Qwen2.5-14B AWQ EC2 (sémantique pur)
- Validator post-LLM (substring match + target resolution)

Usage :
  # Dry-run sur 1 doc
  docker exec knowbase-app python scripts/backfill_lifecycle_relations_strict.py --doc dualuse_reg_2021_821_original_65eef5dc --dry-run

  # Run réel sur 1 doc
  docker exec knowbase-app python scripts/backfill_lifecycle_relations_strict.py --doc dualuse_reg_2021_821_original_65eef5dc

  # Run sur tous les docs
  docker exec knowbase-app python scripts/backfill_lifecycle_relations_strict.py --all

Variables d'env :
  VLLM_URL : URL vLLM EC2 (default http://18.199.218.46:8000)
  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

from knowbase.lifecycle import (
    LifecycleDeclarationExtractor,
    LifecycleDeclarationValidator,
    LifecyclePersister,
)
from knowbase.lifecycle.declaration_extractor import select_scan_windows
from knowbase.lifecycle.lifecycle_persister import ensure_lifecycle_indexes
from knowbase.lifecycle.models import LifecycleDeclarationCandidate, LifecycleExtractionResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_lifecycle_strict")


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

VLLM_URL = os.getenv("VLLM_URL", "http://18.199.218.46:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

CACHE_DIR = Path("/data/extraction_cache") if Path("/data").exists() else Path("data/extraction_cache")
FORENSICS_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
FORENSICS_DIR.mkdir(parents=True, exist_ok=True)


def list_documents(driver) -> list[dict]:
    """Liste les DocumentContext du tenant courant avec leur doc_id."""
    cypher = """
    MATCH (dc:DocumentContext)
    WHERE dc.tenant_id = $tenant_id
    RETURN dc.doc_id AS doc_id, dc.primary_subject AS subject
    ORDER BY dc.doc_id
    """
    with driver.session() as session:
        rows = session.run(cypher, tenant_id=TENANT_ID).data()
    return rows


def find_cache_file(doc_id: str) -> Path | None:
    """Trouve le cache .v5cache.json correspondant à un doc_id.

    Le doc_id se termine typiquement par les 8 premiers chars du source_file_hash.
    Sinon on scan tous les caches et on matche par cache.extraction.document_id.
    """
    # Tentative rapide : suffix doc_id == prefix hash
    parts = doc_id.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) >= 8:
        hash_prefix = parts[1]
        candidates = list(CACHE_DIR.glob(f"{hash_prefix}*.v5cache.json"))
        if candidates:
            return candidates[0]

    # Fallback : scan complet
    for cache_path in CACHE_DIR.glob("*.v5cache.json"):
        try:
            with cache_path.open() as f:
                data = json.load(f)
            ext = data.get("extraction", {})
            if ext.get("document_id") == doc_id or data.get("document_id") == doc_id:
                return cache_path
        except (json.JSONDecodeError, OSError):
            continue
    return None


def load_full_text(doc_id: str) -> str | None:
    """Charge le full_text d'un doc depuis le cache."""
    cache_path = find_cache_file(doc_id)
    if cache_path is None:
        logger.warning("No cache found for doc_id=%s", doc_id)
        return None
    try:
        with cache_path.open() as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Cannot read cache %s: %s", cache_path, exc)
        return None
    full_text = data.get("extraction", {}).get("full_text") or data.get("full_text")
    if not full_text:
        logger.warning("Empty full_text in cache for doc_id=%s", doc_id)
        return None
    return full_text


def load_domain_pack_hints() -> str | None:
    """Charge les classifier_hints du Domain Pack actif (lifecycle_extraction si défini).

    Hints sont en prose sémantique (pas de regex).
    """
    pack_root = Path("/app/src/knowbase/domain_packs") if Path("/app").exists() else Path("src/knowbase/domain_packs")
    # On essaie aerospace_compliance pour le corpus actuel
    manifest_path = pack_root / "aerospace_compliance" / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with manifest_path.open() as f:
            manifest = json.load(f)
        hints = manifest.get("classifier_hints", {})
        return hints.get("lifecycle_extraction")  # peut être None si non défini
    except (json.JSONDecodeError, OSError):
        return None


def process_doc(
    doc_id: str,
    extractor: LifecycleDeclarationExtractor,
    validator: LifecycleDeclarationValidator,
    persister: LifecyclePersister,
    dry_run: bool,
    domain_hints: str | None,
    window_chars: int = 12000,
    overlap_chars: int = 1500,
    max_head_windows: int = 12,
    tail_windows: int = 1,
) -> dict:
    """Traite un doc : scan multi-fenêtres LLM + validation + persistence (sauf dry-run).

    Pour les gros docs (typiquement >30K chars), les déclarations textuelles
    explicites peuvent se trouver dans des sections internes (ex: dispositions
    finales avec clause d'abrogation) hors d'une fenêtre tête naïve. On scan
    en fenêtres glissantes contigües depuis le début + 1 fenêtre de fin,
    puis on agrège + dédup les candidates avant validation.
    """
    full_text = load_full_text(doc_id)
    if full_text is None:
        return {"doc_id": doc_id, "status": "skipped", "reason": "no_cache_or_empty"}

    windows = select_scan_windows(
        full_text,
        window_chars=window_chars,
        overlap_chars=overlap_chars,
        max_head_windows=max_head_windows,
        tail_windows=tail_windows,
    )
    logger.info(
        "Extracting lifecycle declarations for %s (full_text=%d chars, %d window(s) of ~%d chars)",
        doc_id,
        len(full_text),
        len(windows),
        window_chars,
    )

    # Scan multi-fenêtres avec dédup (clé = type + target_doc_reference + quote_normalized)
    seen_keys: set[tuple[str, str, str]] = set()
    aggregated_candidates: list[LifecycleDeclarationCandidate] = []
    model_id_used = ""
    for i, window in enumerate(windows, 1):
        partial = extractor.extract(doc_id, window, domain_pack_hints=domain_hints)
        model_id_used = partial.model_id
        for cand in partial.declarations:
            key = (
                cand.type.value,
                cand.target_doc_reference.strip().lower(),
                cand.evidence_quote.strip().lower()[:200],
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            aggregated_candidates.append(cand)
        logger.debug(
            "  window %d/%d → %d new candidates (total %d)",
            i,
            len(windows),
            len(partial.declarations),
            len(aggregated_candidates),
        )

    extraction = LifecycleExtractionResult(
        source_doc_id=doc_id,
        declarations=aggregated_candidates,
        extraction_method=f"llm_evidence_locked_v2_strict_multi_window(n={len(windows)})",
        model_id=model_id_used or "unknown",
        extracted_at=partial.extracted_at if windows else "",
    )
    logger.info("LLM extracted %d unique candidate(s) across %d window(s)", len(extraction.declarations), len(windows))

    report = validator.validate_extraction(extraction, full_text)
    logger.info(
        "Validation: %d accepted, %d rejected",
        len(report.accepted),
        len(report.rejected),
    )
    for rej in report.rejected:
        logger.info(
            "  REJECTED [%s]: %s (target=%s, quote=%s)",
            rej["outcome"],
            rej["reason"],
            rej["candidate"]["target_doc_reference"],
            rej["candidate"]["evidence_quote"][:80],
        )

    # Dédup par (source, target, type) — garder highest confidence (meilleure preuve)
    # Plusieurs windows peuvent avoir extrait la même relation avec quotes différentes.
    # On préfère la quote avec la plus forte confidence (typiquement la déclaration explicite vs paraphrase).
    best_per_relation: dict[tuple, "object"] = {}
    for accepted in report.accepted:
        key = (accepted.source_doc_id, accepted.target_doc_id, accepted.type.value)
        prev = best_per_relation.get(key)
        if prev is None or accepted.confidence > prev.confidence:
            best_per_relation[key] = accepted
    deduped_accepted = list(best_per_relation.values())
    if len(deduped_accepted) < len(report.accepted):
        logger.info(
            "Deduped %d → %d unique relations (kept highest-confidence quote per (source,target,type))",
            len(report.accepted),
            len(deduped_accepted),
        )

    persistence_results = []
    if not dry_run:
        for accepted in deduped_accepted:
            try:
                result = persister.persist(accepted)
                persistence_results.append(result)
            except Exception as exc:  # noqa: BLE001
                logger.error("Persistence failed for %s: %s", doc_id, exc)
                persistence_results.append({"error": str(exc), "validated": accepted.model_dump()})
    else:
        for accepted in deduped_accepted:
            logger.info(
                "  [DRY-RUN] would persist %s -> %s [%s] (conf=%.2f, quote=%s)",
                accepted.source_doc_id,
                accepted.target_doc_id,
                accepted.type.value,
                accepted.confidence,
                accepted.evidence_quote[:80],
            )

    return {
        "doc_id": doc_id,
        "status": "ok",
        "n_candidates": len(extraction.declarations),
        "n_accepted": len(report.accepted),
        "n_rejected": len(report.rejected),
        "accepted": [a.model_dump() for a in report.accepted],
        "rejected": report.rejected,
        "persisted": persistence_results,
        "model_id": extraction.model_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="V2-S1 backfill LIFECYCLE_RELATION strict")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--doc", help="doc_id à traiter (un seul)")
    group.add_argument("--all", action="store_true", help="Traiter tous les DocumentContext")
    parser.add_argument("--dry-run", action="store_true", help="Pas de persistence Neo4j")
    parser.add_argument(
        "--no-hints",
        action="store_true",
        help="Désactiver les Domain Pack hints (test domain-agnostic pur)",
    )
    parser.add_argument(
        "--vllm-url",
        default=VLLM_URL,
        help=f"URL vLLM EC2 (default {VLLM_URL})",
    )
    args = parser.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # Ensure indexes (idempotent)
    if not args.dry_run:
        ensure_lifecycle_indexes(driver)

    extractor = LifecycleDeclarationExtractor(vllm_url=args.vllm_url, model_id=VLLM_MODEL)
    validator = LifecycleDeclarationValidator(driver=driver, tenant_id=TENANT_ID)
    persister = LifecyclePersister(driver=driver, tenant_id=TENANT_ID)

    domain_hints = None if args.no_hints else load_domain_pack_hints()
    if domain_hints:
        logger.info("Using Domain Pack lifecycle_extraction hints")

    if args.doc:
        targets = [args.doc]
    else:
        docs = list_documents(driver)
        targets = [d["doc_id"] for d in docs]
        logger.info("Found %d DocumentContext(s) in tenant %s", len(targets), TENANT_ID)

    results = []
    for doc_id in targets:
        try:
            result = process_doc(doc_id, extractor, validator, persister, args.dry_run, domain_hints)
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to process %s: %s", doc_id, exc, exc_info=True)
            results.append({"doc_id": doc_id, "status": "error", "error": str(exc)})

    # Forensics dump
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = FORENSICS_DIR / f"lifecycle_backfill_v2s1_{ts}{'_dryrun' if args.dry_run else ''}.json"
    with out_path.open("w") as f:
        json.dump(
            {
                "metadata": {
                    "vllm_url": args.vllm_url,
                    "model_id": VLLM_MODEL,
                    "dry_run": args.dry_run,
                    "domain_hints_used": bool(domain_hints),
                    "n_docs": len(targets),
                    "ts": ts,
                },
                "results": results,
            },
            f,
            indent=2,
            default=str,
        )
    logger.info("Forensics report saved to %s", out_path)

    # Résumé
    total_accepted = sum(r.get("n_accepted", 0) for r in results)
    total_rejected = sum(r.get("n_rejected", 0) for r in results)
    total_errors = sum(1 for r in results if r.get("status") == "error")
    logger.info(
        "DONE — %d docs processed, %d accepted, %d rejected, %d errors",
        len(targets),
        total_accepted,
        total_rejected,
        total_errors,
    )

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
