#!/usr/bin/env python3
"""
Re-trigger ClaimFirst sur les docs qui ont fini V2 sans chaining.

Détecte automatiquement les "orphans" en croisant :
- docs_done sur disque (V2 a fini)
- DocumentContext + Claims présents en Neo4j (ClaimFirst a tourné)
→ La différence = orphans à re-traiter.

Usage:
    docker compose exec app python scripts/retrigger_orphan_claimfirst.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("retrigger_orphan_cf")


def list_done_docs() -> list[str]:
    """Liste les docs présents dans docs_done (V2 a fini, file = display name)."""
    candidates = [
        Path(os.getenv("KNOWBASE_DATA_DIR", "/data")) / "docs_done",
        Path("/data/docs_done"),
        Path(os.getenv("DATA_DIR", "/app/data")) / "docs_done",
        Path("data/docs_done"),
    ]
    p = next((c for c in candidates if c.exists()), None)
    if not p:
        raise FileNotFoundError(f"docs_done not found in any of: {candidates}")
    return [f.stem for f in p.iterdir() if f.is_file() and f.suffix.lower() in (".pdf", ".pptx", ".docx", ".xlsx", ".md")]


def list_kg_docs(driver) -> set[str]:
    """Liste les docs présents en Neo4j (ClaimFirst a tourné = DocumentContext + au moins 1 Claim).

    Schema actuel : Claim porte la propriete doc_id directement (pas de relation Passage/DOCUMENTED_IN).
    """
    with driver.session() as s:
        rows = s.run(
            """
            MATCH (d:DocumentContext)
            OPTIONAL MATCH (c:Claim) WHERE c.doc_id = d.doc_id
            WITH d, count(c) AS n_claims
            WHERE n_claims > 0
            RETURN d.doc_id AS doc_id
            """
        ).data()
    out = set()
    for r in rows:
        if r.get("doc_id"):
            stem = r["doc_id"].rsplit("_", 1)[0] if "_" in r["doc_id"] else r["doc_id"]
            out.add(stem)
    return out


def find_doc_id_for_stem(driver, stem: str) -> str | None:
    """Cherche un DocumentContext.doc_id correspondant au stem (V2 l'a créé)."""
    with driver.session() as s:
        rows = s.run(
            "MATCH (d:DocumentContext) WHERE d.doc_id STARTS WITH $stem RETURN d.doc_id AS doc_id LIMIT 1",
            stem=stem + "_",
        ).data()
    return rows[0]["doc_id"] if rows else None


def find_doc_id_from_cache(stem: str) -> str | None:
    """Cherche le doc_id (extraction.document_id) dans les .v5cache.json correspondant au stem.

    Utilise pour les orphelins ClaimFirst : V2 a fait le cache mais ClaimFirst n'a
    pas encore tourne donc pas de DocumentContext en Neo4j. Le doc_id vrai est stocke
    dans le cache JSON (champ extraction.document_id).
    """
    import json
    cache_candidates = [
        Path("/data/extraction_cache"),
        Path(os.getenv("KNOWBASE_DATA_DIR", "/data")) / "extraction_cache",
        Path("data/extraction_cache"),
    ]
    cache_dir = next((c for c in cache_candidates if c.exists()), None)
    if not cache_dir:
        return None
    for cache_file in cache_dir.glob("*.v5cache.json"):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                # Read just enough to get document_id
                data = json.load(f)
            doc_id = (data.get("extraction") or {}).get("document_id") or data.get("document_id")
            if doc_id and doc_id.startswith(stem + "_"):
                return doc_id
        except Exception:
            continue
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tenant-id", default="default")
    args = p.parse_args()

    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))

    done_stems = list_done_docs()
    kg_stems = list_kg_docs(driver)
    log.info(f"docs_done sur disque : {len(done_stems)} → {sorted(done_stems)[:10]}...")
    log.info(f"docs avec claims en KG : {len(kg_stems)} → {sorted(kg_stems)[:10]}...")

    orphans = sorted(set(done_stems) - kg_stems)
    log.info(f"Orphans (V2 fini, ClaimFirst manquant) : {len(orphans)}")
    for o in orphans:
        log.info(f"  - {o}")

    if not orphans:
        log.info("Aucun orphan, rien à faire.")
        driver.close()
        return

    if args.dry_run:
        log.info("[dry-run] Pas de re-enqueue.")
        driver.close()
        return

    # Re-enqueue ClaimFirst pour chaque orphan
    from knowbase.ingestion.queue.dispatcher import enqueue_claimfirst_process
    triggered = []
    for stem in orphans:
        # Strategy 1 : doc_id dans Neo4j (DocumentContext present mais sans Claims persistes)
        doc_id = find_doc_id_for_stem(driver, stem)
        # Strategy 2 (vrais orphelins) : lire doc_id depuis le cache V2 .v5cache.json
        if not doc_id:
            doc_id = find_doc_id_from_cache(stem)
        if not doc_id:
            log.warning(f"  [skip] Pas de doc_id trouvable pour {stem} (Neo4j ni cache)")
            continue
        try:
            job = enqueue_claimfirst_process(doc_ids=[doc_id], tenant_id=args.tenant_id)
            log.info(f"  [enqueued] {doc_id} → cf_job={job.id}")
            triggered.append((stem, doc_id, job.id))
        except Exception as e:
            log.error(f"  [error] {stem}: {e}")

    log.info(f"Triggered {len(triggered)} ClaimFirst jobs")
    driver.close()


if __name__ == "__main__":
    main()
