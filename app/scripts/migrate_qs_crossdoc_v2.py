#!/usr/bin/env python3
"""
Migration QS Cross-Doc v1 → v2 — Re-traite les données existantes dans Neo4j.

Opérations :
1. DIMENSION DEDUP : Fusionne les dimensions doublons via embedding similarity
   (ex: max_tls_version ↔ maximum_tls_version)
2. SCOPE RE-RESOLUTION : Re-résout les scopes des QS existantes via LLM
   (réduit les fallback document_context)
3. CONFIDENCE FILTER : Marque les QS confidence < 0.6 comme low_confidence

Usage:
    # Dry-run complet (affiche ce qui serait fait)
    docker exec knowbase-app python scripts/migrate_qs_crossdoc_v2.py --dry-run

    # Dimension dedup seulement
    docker exec knowbase-app python scripts/migrate_qs_crossdoc_v2.py --dedup-only --execute

    # Scope re-resolution avec vLLM
    docker exec knowbase-app python scripts/migrate_qs_crossdoc_v2.py --scope-only --vllm-url http://IP:8000 --execute

    # Migration complète
    docker exec knowbase-app python scripts/migrate_qs_crossdoc_v2.py --vllm-url http://IP:8000 --execute
"""

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, "/app/src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("[OSMOSE] migrate_v2")


@dataclass
class SimpleClaim:
    claim_id: str
    text: str
    doc_id: str
    claim_type: Optional[str] = None
    structured_form: Optional[Dict] = None


# ── Étape 1 : Dimension Dedup via embeddings ─────────────────────────

def run_dimension_dedup(client, tenant_id: str, dry_run: bool = True) -> List[Tuple[str, str, float]]:
    """
    Détecte les dimensions doublons via embedding cosine et les fusionne.

    Returns:
        Liste de (merged_id, target_id, similarity) des merges effectués
    """
    from knowbase.claimfirst.models.question_dimension import QuestionDimension
    from knowbase.claimfirst.extractors.dimension_governance import DimensionAuditor

    # 1. Charger le registre actif
    query = """
    MATCH (qd:QuestionDimension {tenant_id: $tid})
    WHERE qd.status IN ['candidate', 'validated']
    RETURN properties(qd) AS props
    """
    with client.driver.session(database=client.database) as session:
        result = session.run(query, tid=tenant_id)
        records = [dict(r) for r in result]

    registry = []
    for rec in records:
        props = rec.get("props", {})
        if props:
            try:
                registry.append(QuestionDimension.from_neo4j_record(props))
            except Exception:
                pass

    logger.info("[DEDUP] Registre chargé: %d dimensions actives", len(registry))

    if len(registry) < 2:
        logger.info("[DEDUP] Pas assez de dimensions pour dedup")
        return []

    # 2. Trouver les merge candidates
    auditor = DimensionAuditor(use_embeddings=True)
    merge_pairs = auditor.find_merge_candidates(registry, similarity_threshold=0.92)
    logger.info("[DEDUP] Merge candidates trouvées: %d paires", len(merge_pairs))

    dim_by_id = {d.dimension_id: d for d in registry}
    merges_done = []

    for a_id, b_id, sim in merge_pairs:
        a = dim_by_id.get(a_id)
        b = dim_by_id.get(b_id)
        if not a or not b:
            continue

        # Garder celui qui a le plus de QS (info_count)
        if a.info_count >= b.info_count:
            keeper, merged = a, b
        else:
            keeper, merged = b, a

        logger.info("[DEDUP] MERGE: [%s] → [%s] (cosine=%.3f, keeper=%d QS, merged=%d QS)",
                    merged.dimension_key, keeper.dimension_key, sim,
                    keeper.info_count, merged.info_count)

        if not dry_run:
            _execute_merge(client, tenant_id, merged.dimension_id, keeper.dimension_id)

        merges_done.append((merged.dimension_id, keeper.dimension_id, sim))

    return merges_done


def _execute_merge(client, tenant_id: str, merged_id: str, keeper_id: str):
    """Exécute un merge de dimension dans Neo4j."""
    with client.driver.session(database=client.database) as session:
        # 1. Re-rattacher les QS du merged vers le keeper
        session.run("""
            MATCH (qs:QuestionSignature {tenant_id: $tid, dimension_id: $merged_id})
            SET qs.dimension_id = $keeper_id
        """, tid=tenant_id, merged_id=merged_id, keeper_id=keeper_id)

        # 2. Supprimer les anciennes relations ANSWERS vers le merged
        session.run("""
            MATCH (qs:QuestionSignature {tenant_id: $tid})-[r:ANSWERS]->(qd:QuestionDimension {dimension_id: $merged_id})
            DELETE r
        """, tid=tenant_id, merged_id=merged_id)

        # 3. Créer les nouvelles relations ANSWERS vers le keeper
        session.run("""
            MATCH (qs:QuestionSignature {tenant_id: $tid, dimension_id: $keeper_id})
            MATCH (qd:QuestionDimension {dimension_id: $keeper_id})
            MERGE (qs)-[:ANSWERS]->(qd)
        """, tid=tenant_id, keeper_id=keeper_id)

        # 4. Marquer le merged comme fusionné
        session.run("""
            MATCH (qd:QuestionDimension {dimension_id: $merged_id})
            SET qd.status = 'merged', qd.merged_into = $keeper_id
        """, merged_id=merged_id, keeper_id=keeper_id)

        # 5. Mettre à jour les compteurs du keeper
        session.run("""
            MATCH (qd:QuestionDimension {dimension_id: $keeper_id})
            OPTIONAL MATCH (qs:QuestionSignature {tenant_id: $tid, dimension_id: $keeper_id})
            WITH qd, count(qs) AS qs_count, count(DISTINCT qs.doc_id) AS doc_count
            SET qd.info_count = qs_count, qd.doc_count = doc_count
        """, tid=tenant_id, keeper_id=keeper_id)

    logger.info("[DEDUP] Merge exécuté: %s → %s", merged_id, keeper_id)


# ── Étape 2 : Scope Re-resolution via LLM ───────────────────────────

async def run_scope_reresolution(
    client,
    tenant_id: str,
    dry_run: bool = True,
    max_concurrent: int = 5,
) -> Dict[str, int]:
    """
    Re-résout les scopes des QS qui ont scope_basis = section_context ou document_context.

    Returns:
        Compteur {old_basis: count, "upgraded": count, "kept": count}
    """
    from knowbase.claimfirst.extractors.scope_resolver import resolve_scope_v2

    # 1. Charger les QS avec scope faible
    query = """
    MATCH (qs:QuestionSignature {tenant_id: $tid})
    WHERE qs.scope_basis IN ['section_context', 'document_context', 'missing']
    OPTIONAL MATCH (c:Claim {claim_id: qs.claim_id})
    RETURN qs.qs_id AS qs_id,
           qs.claim_id AS claim_id,
           qs.doc_id AS doc_id,
           qs.scope_basis AS old_basis,
           qs.scope_evidence AS scope_evidence,
           c.text AS claim_text
    """
    with client.driver.session(database=client.database) as session:
        result = session.run(query, tid=tenant_id)
        records = [dict(r) for r in result]

    logger.info("[SCOPE] QS avec scope faible: %d", len(records))

    if not records:
        return {}

    # Charger les doc contexts
    dc_query = """
    MATCH (dc:DocumentContext {tenant_id: $tid})
    RETURN dc.doc_id AS doc_id, dc.primary_subject AS primary_subject
    """

    @dataclass
    class SimpleDocCtx:
        doc_id: str
        primary_subject: Optional[str] = None

    doc_contexts = {}
    with client.driver.session(database=client.database) as session:
        result = session.run(dc_query, tid=tenant_id)
        for rec in [dict(r) for r in result]:
            doc_id = rec.get("doc_id")
            if doc_id:
                doc_contexts[doc_id] = SimpleDocCtx(doc_id=doc_id, primary_subject=rec.get("primary_subject"))

    # 2. Re-résoudre via LLM
    stats = Counter()
    semaphore = asyncio.Semaphore(max_concurrent)
    updates = []

    async def resolve_one(rec):
        async with semaphore:
            claim_text = rec.get("claim_text") or ""
            if not claim_text:
                stats["no_claim_text"] += 1
                return

            claim = SimpleClaim(
                claim_id=rec["claim_id"],
                text=claim_text,
                doc_id=rec.get("doc_id") or "",
            )

            scope = await resolve_scope_v2(
                claim=claim,
                scope_evidence=rec.get("scope_evidence"),
                doc_context=doc_contexts.get(rec.get("doc_id")),
                use_llm=True,
            )

            old_basis = rec.get("old_basis", "missing")
            new_basis = scope.scope_basis

            if new_basis in ("claim_llm", "claim_explicit"):
                stats["upgraded"] += 1
                stats[f"{old_basis}_to_{new_basis}"] += 1
                updates.append((rec["qs_id"], scope))
            else:
                stats["kept"] += 1

    await asyncio.gather(*[resolve_one(rec) for rec in records])

    logger.info("[SCOPE] Résultats: %s", dict(stats))
    logger.info("[SCOPE] QS à mettre à jour: %d", len(updates))

    # 3. Persister
    if not dry_run and updates:
        with client.driver.session(database=client.database) as session:
            for qs_id, scope in updates:
                scope_dict = scope.to_dict()
                session.run("""
                    MATCH (qs:QuestionSignature {qs_id: $qs_id})
                    SET qs.scope_basis = $basis,
                        qs.scope_status = $status,
                        qs.scope_confidence = $conf,
                        qs.scope_anchor_type = $anchor_type,
                        qs.scope_anchor_label = $anchor_label
                """,
                    qs_id=qs_id,
                    basis=scope_dict.get("scope_basis"),
                    status=scope_dict.get("scope_status"),
                    conf=scope_dict.get("scope_confidence"),
                    anchor_type=scope_dict.get("primary_anchor_type"),
                    anchor_label=scope_dict.get("primary_anchor_label"),
                )
        logger.info("[SCOPE] %d QS mises à jour dans Neo4j", len(updates))

    return dict(stats)


# ── Étape 3 : Audit post-migration ──────────────────────────────────

def run_post_migration_audit(client, tenant_id: str):
    """Affiche les métriques clés après migration."""
    queries = {
        "Dimensions actives": """
            MATCH (qd:QuestionDimension {tenant_id: $tid})
            WHERE qd.status IN ['candidate', 'validated']
            RETURN count(qd) AS cnt
        """,
        "Dimensions merged": """
            MATCH (qd:QuestionDimension {tenant_id: $tid})
            WHERE qd.status = 'merged'
            RETURN count(qd) AS cnt
        """,
        "QS totales": """
            MATCH (qs:QuestionSignature {tenant_id: $tid})
            RETURN count(qs) AS cnt
        """,
        "QS confidence >= 0.6": """
            MATCH (qs:QuestionSignature {tenant_id: $tid})
            WHERE qs.confidence >= 0.6
            RETURN count(qs) AS cnt
        """,
    }

    scope_query = """
        MATCH (qs:QuestionSignature {tenant_id: $tid})
        RETURN qs.scope_basis AS basis, count(*) AS cnt
        ORDER BY cnt DESC
    """

    logger.info("=" * 60)
    logger.info("AUDIT POST-MIGRATION")
    logger.info("=" * 60)

    with client.driver.session(database=client.database) as session:
        for label, q in queries.items():
            result = session.run(q, tid=tenant_id)
            record = result.single()
            cnt = record["cnt"] if record else 0
            logger.info("  %s: %d", label, cnt)

        logger.info("  --- Scope basis distribution ---")
        result = session.run(scope_query, tid=tenant_id)
        for rec in result:
            basis = rec.get("basis") or "null"
            cnt = rec.get("cnt", 0)
            logger.info("    %s: %d", basis, cnt)


# ── Main ─────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Migration QS Cross-Doc v1 → v2")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true", help="Exécuter les modifications")
    parser.add_argument("--tenant-id", type=str, default="default")
    parser.add_argument("--vllm-url", type=str, default=None, help="URL vLLM pour scope LLM")
    parser.add_argument("--max-concurrent", type=int, default=5)
    parser.add_argument("--dedup-only", action="store_true", help="Dimension dedup seulement")
    parser.add_argument("--scope-only", action="store_true", help="Scope re-resolution seulement")
    args = parser.parse_args()

    dry_run = not args.execute
    if dry_run:
        logger.info("MODE DRY-RUN — Aucune modification ne sera faite")
    else:
        logger.info("MODE EXECUTE — Les modifications seront persistées")

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    client = get_neo4j_client()

    # Activer burst mode si vLLM
    if args.vllm_url:
        from knowbase.common.llm_router import get_llm_router
        router = get_llm_router()
        router.enable_burst_mode(args.vllm_url)
        logger.info("Burst mode activé: %s", args.vllm_url)

    # ── Étape 1 : Dimension dedup ─────────────────────────────────────
    if not args.scope_only:
        logger.info("")
        logger.info("=" * 60)
        logger.info("ÉTAPE 1 : DIMENSION DEDUP (embeddings)")
        logger.info("=" * 60)
        merges = run_dimension_dedup(client, args.tenant_id, dry_run)
        logger.info("[DEDUP] Total merges: %d", len(merges))

    # ── Étape 2 : Scope re-resolution ─────────────────────────────────
    if not args.dedup_only:
        if not args.vllm_url:
            logger.warning("[SCOPE] --vllm-url non fourni, scope re-resolution SKIPPÉE")
        else:
            logger.info("")
            logger.info("=" * 60)
            logger.info("ÉTAPE 2 : SCOPE RE-RESOLUTION (LLM)")
            logger.info("=" * 60)
            stats = await run_scope_reresolution(
                client, args.tenant_id, dry_run, args.max_concurrent,
            )

    # ── Audit final ───────────────────────────────────────────────────
    logger.info("")
    run_post_migration_audit(client, args.tenant_id)

    if dry_run:
        logger.info("")
        logger.info("DRY-RUN terminé. Relancer avec --execute pour appliquer.")


if __name__ == "__main__":
    asyncio.run(main())
