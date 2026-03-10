#!/usr/bin/env python3
"""
Sweep rétroactif des SubjectAnchors — validation LLM + nettoyage NOISE.

Passe la validation LLM sur tous les SubjectAnchors existants en base
et supprime ceux classifiés NOISE. Les sujets référencés par ≥N documents
sont automatiquement skippés (probablement légitimes).

Usage (dans le conteneur Docker) :
    # Dry-run (défaut) — affiche le rapport sans rien toucher
    python scripts/sweep_subject_anchors.py --dry-run --tenant default

    # Exécuter les suppressions
    python scripts/sweep_subject_anchors.py --execute --tenant default

    # Avec options
    python scripts/sweep_subject_anchors.py --dry-run --tenant default --limit 50 --batch-size 20 --min-docs 3
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def load_subject_anchors(session, tenant_id: str, limit: int = 0) -> List[dict]:
    """Charge les SubjectAnchors avec le nombre de DocumentContexts liés."""
    # SubjectAnchors peuvent avoir tenant_id=NULL ou absent
    query = """
        MATCH (sa:SubjectAnchor)
        WHERE sa.tenant_id = $tenant_id OR sa.tenant_id IS NULL
        OPTIONAL MATCH (dc:DocumentContext)-[:ABOUT_SUBJECT]->(sa)
        RETURN sa.subject_id AS subject_id,
               sa.canonical_name AS canonical_name,
               sa.source_doc_ids AS source_doc_ids,
               count(DISTINCT dc) AS linked_doc_count
    """
    if limit > 0:
        query += f"\n        LIMIT {limit}"

    result = session.run(query, tenant_id=tenant_id)
    anchors = []
    for record in result:
        anchors.append({
            "subject_id": record["subject_id"],
            "canonical_name": record["canonical_name"],
            "source_doc_ids": record["source_doc_ids"] or [],
            "linked_doc_count": record["linked_doc_count"],
        })
    return anchors


def get_subject_stats(session, tenant_id: str) -> dict:
    """Retourne les stats totales des SubjectAnchors."""
    result = session.run(
        """
        MATCH (sa:SubjectAnchor)
        WHERE sa.tenant_id = $tenant_id OR sa.tenant_id IS NULL
        OPTIONAL MATCH (dc:DocumentContext)-[:ABOUT_SUBJECT]->(sa)
        WITH sa, count(DISTINCT dc) AS doc_count
        RETURN count(sa) AS total,
               sum(CASE WHEN doc_count = 0 THEN 1 ELSE 0 END) AS orphans,
               sum(CASE WHEN doc_count = 1 THEN 1 ELSE 0 END) AS single_doc,
               sum(CASE WHEN doc_count >= 2 THEN 1 ELSE 0 END) AS multi_doc
        """,
        tenant_id=tenant_id,
    )
    record = result.single()
    if record:
        return {
            "total": record["total"],
            "orphans": record["orphans"],
            "single_doc": record["single_doc"],
            "multi_doc": record["multi_doc"],
        }
    return {"total": 0, "orphans": 0, "single_doc": 0, "multi_doc": 0}


def validate_batch_llm(subjects: List[dict], batch_size: int) -> Dict[str, dict]:
    """
    Valide les sujets par batches via LLM.

    Returns:
        dict {subject_id: {"verdict": "VALID|NOISE|UNCERTAIN", "reason": str}}
    """
    from knowbase.common.llm_router import get_llm_router, TaskType

    router = get_llm_router()
    all_verdicts: Dict[str, dict] = {}

    for batch_start in range(0, len(subjects), batch_size):
        batch = subjects[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(subjects) + batch_size - 1) // batch_size
        logger.info(f"  → Batch {batch_num}/{total_batches} ({len(batch)} sujets)...")

        subjects_text = "\n".join(
            f'{i+1}. "{s["canonical_name"]}" ({s["linked_doc_count"]} docs)'
            for i, s in enumerate(batch)
        )

        prompt = f"""Classify each candidate subject name as VALID, NOISE, or UNCERTAIN.

VALID = legitimate document subject (product name, technology, standard, concept, methodology, specification, regulation)
NOISE = clearly NOT a subject (sentence fragment, action phrase, generic description, vague term, layout artifact)
UNCERTAIN = ambiguous, could be either

For each subject, the number of documents referencing it is shown. More docs = more likely valid.

Candidate subjects:
{subjects_text}

Return JSON: {{"results": [{{"index": 1, "verdict": "VALID", "reason": "product name"}}]}}"""

        try:
            response = router.complete(
                task_type=TaskType.METADATA_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
                response_format={"type": "json_object"},
            ).strip()

            data = json.loads(response)
            results = data.get("results", [])

            for entry in results:
                idx = entry.get("index")
                if isinstance(idx, int) and 1 <= idx <= len(batch):
                    subj = batch[idx - 1]
                    all_verdicts[subj["subject_id"]] = {
                        "verdict": entry.get("verdict", "VALID"),
                        "reason": entry.get("reason", ""),
                    }

            # Sujets sans verdict dans cette batch → VALID par défaut (fail-open)
            for s in batch:
                if s["subject_id"] not in all_verdicts:
                    all_verdicts[s["subject_id"]] = {
                        "verdict": "VALID",
                        "reason": "no LLM verdict (fail-open)",
                    }

        except Exception as e:
            logger.warning(
                f"[OSMOSE] Batch {batch_num} LLM failed (fail-open): {e}"
            )
            # Fail-open : tous les sujets de cette batch → VALID
            for s in batch:
                if s["subject_id"] not in all_verdicts:
                    all_verdicts[s["subject_id"]] = {
                        "verdict": "VALID",
                        "reason": f"LLM error (fail-open): {e}",
                    }

    return all_verdicts


def cleanup_doc_context_refs(session, subject_id: str, tenant_id: str) -> int:
    """Nettoie la propriété subject_ids dans les DocumentContext."""
    result = session.run(
        """
        MATCH (dc:DocumentContext {tenant_id: $tenant_id})
        WHERE $subject_id IN dc.subject_ids
        SET dc.subject_ids = [x IN dc.subject_ids WHERE x <> $subject_id]
        RETURN count(dc) AS updated
        """,
        subject_id=subject_id,
        tenant_id=tenant_id,
    )
    record = result.single()
    return record["updated"] if record else 0


def delete_subject_anchor(session, subject_id: str, tenant_id: str) -> bool:
    """Supprime un SubjectAnchor et ses relations."""
    result = session.run(
        """
        MATCH (sa:SubjectAnchor {subject_id: $subject_id})
        WHERE sa.tenant_id = $tenant_id OR sa.tenant_id IS NULL
        DETACH DELETE sa
        RETURN count(*) AS deleted
        """,
        subject_id=subject_id,
        tenant_id=tenant_id,
    )
    record = result.single()
    return bool(record and record["deleted"] > 0)


def main():
    parser = argparse.ArgumentParser(
        description="Sweep rétroactif des SubjectAnchors — validation LLM + nettoyage NOISE"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher le rapport sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les suppressions")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limiter le nombre de sujets à traiter (0 = tous)")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="Taille des batches LLM (default: 20)")
    parser.add_argument("--min-docs", type=int, default=3,
                        help="Skip les sujets référencés par >=N docs (default: 3)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Stats initiales
            logger.info(f"[OSMOSE] Stats SubjectAnchors (tenant={args.tenant})...")
            stats = get_subject_stats(session, args.tenant)
            logger.info(f"  → Total       : {stats['total']}")
            logger.info(f"  → Orphelins   : {stats['orphans']} (0 doc lié)")
            logger.info(f"  → Single-doc  : {stats['single_doc']} (1 doc)")
            logger.info(f"  → Multi-doc   : {stats['multi_doc']} (≥2 docs)")

            if stats["total"] == 0:
                logger.info("Aucun SubjectAnchor trouvé.")
                return

            # 2. Charger les SubjectAnchors
            logger.info(f"[OSMOSE] Chargement des SubjectAnchors...")
            all_anchors = load_subject_anchors(session, args.tenant, args.limit)
            logger.info(f"  → {len(all_anchors)} sujets chargés")

            # 3. Filtrer : skip si linked_doc_count >= min_docs
            to_validate = [
                a for a in all_anchors if a["linked_doc_count"] < args.min_docs
            ]
            skipped = len(all_anchors) - len(to_validate)
            logger.info(
                f"  → {skipped} sujets skippés (≥{args.min_docs} docs liés)"
            )
            logger.info(f"  → {len(to_validate)} sujets à valider")

            if not to_validate:
                logger.info("Aucun sujet à valider après filtrage.")
                return

            # 4. Validation LLM par batches
            n_batches = (len(to_validate) + args.batch_size - 1) // args.batch_size
            logger.info(
                f"\n[OSMOSE] Validation LLM ({n_batches} batches de {args.batch_size})..."
            )
            verdicts = validate_batch_llm(to_validate, args.batch_size)

            # 5. Rapport
            noise = []
            uncertain = []
            valid = []
            for subj in to_validate:
                sid = subj["subject_id"]
                v = verdicts.get(sid, {"verdict": "VALID", "reason": "missing"})
                entry = {
                    "subject_id": sid,
                    "canonical_name": subj["canonical_name"],
                    "linked_doc_count": subj["linked_doc_count"],
                    "verdict": v["verdict"],
                    "reason": v["reason"],
                }
                verdict_upper = v["verdict"].upper()
                if verdict_upper == "NOISE":
                    noise.append(entry)
                elif verdict_upper == "UNCERTAIN":
                    uncertain.append(entry)
                else:
                    valid.append(entry)

            logger.info(f"\n{'='*70}")
            logger.info("RAPPORT DE VALIDATION")
            logger.info(f"{'='*70}")
            logger.info(f"Total validés : {len(to_validate)}")
            logger.info(f"Skippés (≥{args.min_docs} docs) : {skipped}")
            logger.info(f"VALID         : {len(valid)}")
            logger.info(f"NOISE         : {len(noise)}")
            logger.info(f"UNCERTAIN     : {len(uncertain)}")

            if noise:
                logger.info(f"\n--- NOISE ({len(noise)}) — à supprimer ---")
                for e in noise:
                    logger.info(
                        f"  ✗ \"{e['canonical_name']}\" "
                        f"({e['linked_doc_count']} docs) — {e['reason']}"
                    )

            if uncertain:
                logger.info(f"\n--- UNCERTAIN ({len(uncertain)}) — conservés ---")
                for e in uncertain:
                    logger.info(
                        f"  ? \"{e['canonical_name']}\" "
                        f"({e['linked_doc_count']} docs) — {e['reason']}"
                    )

            logger.info(f"\n--- VALID ({len(valid)}) ---")
            for e in valid:
                logger.info(
                    f"  ✓ \"{e['canonical_name']}\" "
                    f"({e['linked_doc_count']} docs) — {e['reason']}"
                )

            # 6. Exécution ou dry-run
            if args.dry_run:
                logger.info(f"\n{'='*70}")
                logger.info("[DRY-RUN] Aucune modification effectuée.")
                logger.info(f"  → {len(noise)} sujets NOISE seraient supprimés")
                logger.info("  → Relancer avec --execute pour appliquer.")
                logger.info(f"{'='*70}")
                return

            # Mode --execute
            if not noise:
                logger.info("\nAucun sujet NOISE à supprimer.")
                return

            logger.info(f"\n[OSMOSE] Suppression de {len(noise)} sujets NOISE...")
            deleted_count = 0
            refs_cleaned = 0

            for e in noise:
                sid = e["subject_id"]
                # D'abord nettoyer les références dans DocumentContext
                updated = cleanup_doc_context_refs(session, sid, args.tenant)
                refs_cleaned += updated
                # Puis supprimer le noeud SubjectAnchor
                if delete_subject_anchor(session, sid, args.tenant):
                    deleted_count += 1
                    logger.info(
                        f"  ✗ Supprimé: \"{e['canonical_name']}\" "
                        f"({updated} refs nettoyées)"
                    )

            # Stats finales
            after_stats = get_subject_stats(session, args.tenant)
            logger.info(f"\n{'='*70}")
            logger.info("RÉSUMÉ SWEEP")
            logger.info(f"{'='*70}")
            logger.info(f"Avant  : {stats['total']} SubjectAnchors")
            logger.info(f"Après  : {after_stats['total']} SubjectAnchors")
            logger.info(f"Supprimés : {deleted_count}")
            logger.info(f"Refs DC nettoyées : {refs_cleaned}")
            logger.info("\n[OSMOSE] Sweep terminé.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
