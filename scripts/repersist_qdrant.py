"""
Re-persist Qdrant Layer R depuis les caches existants.

Utilise les TypeAwareChunks des caches v5 et les passe par le rechunker
(avec tous les fixes A/B/C/D/cross-page) puis embed + upsert dans Qdrant.

Ne touche PAS a Neo4j — uniquement Qdrant.

Usage (dans le container):
    python -m scripts.repersist_qdrant
    python -m scripts.repersist_qdrant --doc 027  # un seul doc
    python -m scripts.repersist_qdrant --dry-run   # simuler sans ecrire
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Re-persist Qdrant from caches")
    parser.add_argument("--doc", type=str, help="Filtrer par doc_id (substring match)")
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans ecrire")
    parser.add_argument("--cache-dir", default="/data/extraction_cache", help="Repertoire caches")
    parser.add_argument("--target-chars", type=int, default=1500)
    parser.add_argument("--overlap-chars", type=int, default=200)
    args = parser.parse_args()

    from knowbase.retrieval.rechunker import rechunk_for_retrieval
    from knowbase.retrieval.qdrant_layer_r import (
        delete_doc_from_layer_r,
        ensure_layer_r_collection,
        upsert_layer_r,
    )
    from knowbase.common.clients.embeddings import get_embedding_manager
    from knowbase.structural.models import TypeAwareChunk, ChunkKind, TextOrigin
    import numpy as np

    # Lister les caches
    cache_files = sorted(glob.glob(os.path.join(args.cache_dir, "*.json")))
    logger.info(f"Found {len(cache_files)} cache files")

    ensure_layer_r_collection()
    manager = get_embedding_manager()

    total_points = 0
    total_time = 0

    for cache_file in cache_files:
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)

        ext = data.get("extraction", {})
        doc_id = ext.get("document_id", data.get("document_id", ""))
        source = ext.get("source_path", "")
        file_type = ext.get("file_type", "")
        stats = ext.get("stats", {})
        sg = stats.get("structural_graph", {})
        chunks_data = sg.get("chunks", [])

        if not chunks_data:
            continue

        if args.doc and args.doc not in doc_id and args.doc not in source:
            continue

        basename = os.path.basename(source) or doc_id
        logger.info(f"Processing: {basename} ({len(chunks_data)} chunks, type={file_type})")

        start = time.time()

        # Reconstruire les TypeAwareChunks
        tac_list = []
        for c in chunks_data:
            try:
                kind = ChunkKind(c["kind"])
            except (ValueError, KeyError):
                kind = ChunkKind.NARRATIVE_TEXT
            origin = None
            if c.get("text_origin"):
                try:
                    origin = TextOrigin(c["text_origin"])
                except ValueError:
                    pass
            tac = TypeAwareChunk(
                chunk_id=c["chunk_id"],
                tenant_id="default",
                doc_id=doc_id,
                doc_version_id=c.get("doc_version_id", "v1"),
                kind=kind,
                text=c["text"],
                page_no=c.get("page_no", 0),
                section_id=c.get("section_id"),
                item_ids=c.get("item_ids", []),
                is_relation_bearing=c.get("is_relation_bearing", False),
                text_origin=origin,
                page_span_min=c.get("page_no", 0),
                page_span_max=c.get("page_no", 0),
            )
            tac_list.append(tac)

        # Rechunker avec tous les fixes
        sub_chunks = rechunk_for_retrieval(
            tac_list, "default", doc_id,
            target_chars=args.target_chars,
            overlap_chars=args.overlap_chars,
        )

        if not sub_chunks:
            logger.warning(f"  No sub-chunks after rechunking, skipping")
            continue

        # Prefixe contextuel (sauf si deja present)
        for sc in sub_chunks:
            if not sc.text.startswith("[Document:"):
                prefix_parts = []
                if sc.section_title:
                    prefix_parts.append(f"Section: {sc.section_title}")
                elif sc.section_id:
                    prefix_parts.append(f"Section: {sc.section_id}")
                if sc.page_no:
                    prefix_parts.append(f"Page {sc.page_no}")
                if prefix_parts:
                    sc.text = "[" + " | ".join(prefix_parts) + "]\n\n" + sc.text

        logger.info(f"  {len(tac_list)} chunks -> {len(sub_chunks)} sub-chunks")

        if args.dry_run:
            lengths = sorted([len(s.text) for s in sub_chunks])
            logger.info(f"  [DRY RUN] median={lengths[len(lengths)//2]}, min={lengths[0]}, max={lengths[-1]}")
            continue

        # Supprimer les anciens points
        try:
            delete_doc_from_layer_r(doc_id, "default")
        except Exception as e:
            logger.debug(f"  Delete skipped: {e}")

        # Embeddings
        texts = [sc.text for sc in sub_chunks]
        embeddings = manager.encode(texts)

        if embeddings is None or len(embeddings) == 0:
            logger.warning(f"  No embeddings generated")
            continue

        # Filtrer zero-vectors
        pairs = []
        for sc, emb in zip(sub_chunks, embeddings):
            if isinstance(emb, np.ndarray):
                emb_list = emb.tolist()
            elif isinstance(emb, list):
                emb_list = emb
            else:
                emb_list = list(emb)
            if any(v != 0.0 for v in emb_list[:10]):
                pairs.append((sc, emb_list))

        n = upsert_layer_r(pairs, tenant_id="default")
        elapsed = time.time() - start
        total_points += n
        total_time += elapsed
        logger.info(f"  -> {n} points upserted in {elapsed:.1f}s")

    logger.info(f"Done: {total_points} total points in {total_time:.1f}s")


if __name__ == "__main__":
    main()
