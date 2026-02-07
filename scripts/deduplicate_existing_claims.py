#!/usr/bin/env python3
"""
Déduplication rétroactive des Claims existantes dans Neo4j.

Applique la même logique que la Phase 1.5 de l'orchestrateur sur les claims
déjà persistées, sans nécessiter de ré-import.

Deux niveaux :
  1. Texte exact : même text normalisé (lowercase+strip) dans le même doc_id
     → garder la claim avec la meilleure confidence
  2. Triplet S/P/O : même structured_form (subject+predicate+object normalisés)
     dans le même doc_id → garder la meilleure confidence

Calcule aussi content_fingerprint sur toutes les claims survivantes.

Usage (dans le conteneur Docker) :
    python -m scripts.deduplicate_existing_claims [--dry-run] [--tenant default]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def compute_content_fingerprint(text: str, scope_key: str) -> str:
    """Même logique que Claim.compute_content_fingerprint()."""
    components = [text.lower().strip(), scope_key]
    content = ":".join(components)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def build_scope_key(record: dict) -> str:
    """Reconstruit le scope_key depuis les propriétés Neo4j."""
    parts = [
        record.get("scope_version") or "any",
        record.get("scope_region") or "any",
        record.get("scope_edition") or "any",
    ]
    conditions = record.get("scope_conditions")
    if conditions:
        if isinstance(conditions, list):
            parts.append(":".join(sorted(conditions)))
        else:
            parts.append(str(conditions))
    return "|".join(parts)


def load_all_claims(session, tenant_id: str) -> List[dict]:
    """Charge toutes les claims d'un tenant depuis Neo4j."""
    result = session.run(
        """
        MATCH (c:Claim {tenant_id: $tenant_id})
        RETURN c
        ORDER BY c.doc_id, c.confidence DESC
        """,
        tenant_id=tenant_id,
    )
    claims = []
    for record in result:
        claims.append(dict(record["c"]))
    return claims


def deduplicate_claims(
    claims: List[dict],
) -> Tuple[List[str], List[dict], Dict[str, int]]:
    """
    Applique la dédup sur une liste de claims (même logique que l'orchestrateur).

    Returns:
        Tuple[claim_ids_to_delete, claims_to_keep, stats_per_doc]
    """
    # Grouper par doc_id
    by_doc: Dict[str, List[dict]] = defaultdict(list)
    for c in claims:
        by_doc[c["doc_id"]].append(c)

    ids_to_delete: List[str] = []
    claims_to_keep: List[dict] = []
    stats_per_doc: Dict[str, dict] = {}

    for doc_id, doc_claims in by_doc.items():
        initial = len(doc_claims)

        # Niveau 1 : Texte exact
        best_by_text: Dict[str, dict] = {}
        for c in doc_claims:
            key = c["text"].lower().strip()
            existing = best_by_text.get(key)
            if existing is None or c.get("confidence", 0) > existing.get("confidence", 0):
                best_by_text[key] = c

        after_text = list(best_by_text.values())
        after_text_ids = {c["claim_id"] for c in after_text}
        removed_text = initial - len(after_text)

        # Niveau 2 : Triplet S/P/O
        best_by_spo: Dict[Tuple[str, str, str], dict] = {}
        no_spo: List[dict] = []

        for c in after_text:
            sf_json = c.get("structured_form_json")
            sf = None
            if sf_json:
                try:
                    sf = json.loads(sf_json)
                except (json.JSONDecodeError, TypeError):
                    pass

            if sf and sf.get("subject") and sf.get("predicate") and sf.get("object"):
                key = (
                    str(sf["subject"]).lower().strip(),
                    str(sf["predicate"]).lower().strip(),
                    str(sf["object"]).lower().strip(),
                )
                existing = best_by_spo.get(key)
                if existing is None or c.get("confidence", 0) > existing.get("confidence", 0):
                    best_by_spo[key] = c
            else:
                no_spo.append(c)

        after_spo = list(best_by_spo.values()) + no_spo
        after_spo_ids = {c["claim_id"] for c in after_spo}
        removed_spo = len(after_text) - len(after_spo)

        # Collecter les IDs à supprimer
        all_ids = {c["claim_id"] for c in doc_claims}
        doc_ids_to_delete = all_ids - after_spo_ids
        ids_to_delete.extend(doc_ids_to_delete)
        claims_to_keep.extend(after_spo)

        if removed_text > 0 or removed_spo > 0:
            stats_per_doc[doc_id] = {
                "initial": initial,
                "removed_text": removed_text,
                "removed_spo": removed_spo,
                "kept": len(after_spo),
            }

    return ids_to_delete, claims_to_keep, stats_per_doc


def delete_claims_batch(session, claim_ids: List[str], batch_size: int = 500) -> int:
    """Supprime les claims et leurs relations par batch."""
    total_deleted = 0
    for i in range(0, len(claim_ids), batch_size):
        batch = claim_ids[i : i + batch_size]
        # Supprimer les relations sortantes et entrantes, puis le nœud
        result = session.run(
            """
            UNWIND $ids AS cid
            MATCH (c:Claim {claim_id: cid})
            OPTIONAL MATCH (c)-[r_out]->()
            OPTIONAL MATCH ()-[r_in]->(c)
            DELETE r_out, r_in, c
            RETURN count(DISTINCT cid) AS deleted
            """,
            ids=batch,
        )
        deleted = result.single()["deleted"]
        total_deleted += deleted
        logger.info(f"  Batch {i // batch_size + 1}: {deleted} claims supprimées")
    return total_deleted


def set_content_fingerprints(session, claims: List[dict], batch_size: int = 500) -> int:
    """Calcule et persiste content_fingerprint sur les claims survivantes."""
    updates = []
    for c in claims:
        scope_key = build_scope_key(c)
        fp = compute_content_fingerprint(c["text"], scope_key)
        updates.append({"claim_id": c["claim_id"], "content_fingerprint": fp})

    total_updated = 0
    for i in range(0, len(updates), batch_size):
        batch = updates[i : i + batch_size]
        result = session.run(
            """
            UNWIND $updates AS u
            MATCH (c:Claim {claim_id: u.claim_id})
            SET c.content_fingerprint = u.content_fingerprint
            RETURN count(c) AS updated
            """,
            updates=batch,
        )
        updated = result.single()["updated"]
        total_updated += updated
    return total_updated


def cleanup_orphan_passages(session, tenant_id: str) -> int:
    """Supprime les Passages orphelins (plus aucune Claim SUPPORTED_BY)."""
    result = session.run(
        """
        MATCH (p:Passage {tenant_id: $tenant_id})
        WHERE NOT EXISTS {
            MATCH (:Claim)-[:SUPPORTED_BY]->(p)
        }
        OPTIONAL MATCH (p)-[r]-()
        DELETE r, p
        RETURN count(DISTINCT p) AS deleted
        """,
        tenant_id=tenant_id,
    )
    return result.single()["deleted"]


def main():
    parser = argparse.ArgumentParser(description="Déduplication rétroactive des Claims Neo4j")
    parser.add_argument("--dry-run", action="store_true", help="Afficher sans modifier")
    parser.add_argument("--tenant", default="default", help="Tenant ID (default: 'default')")
    parser.add_argument("--skip-fingerprint", action="store_true", help="Ne pas calculer content_fingerprint")
    args = parser.parse_args()

    # Connexion Neo4j
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        with driver.session() as session:
            # 1. Charger les claims
            logger.info(f"[OSMOSE] Chargement des claims (tenant={args.tenant})...")
            claims = load_all_claims(session, args.tenant)
            logger.info(f"  → {len(claims)} claims chargées")

            if not claims:
                logger.info("Aucune claim à traiter.")
                return

            # 2. Calculer la dédup
            logger.info("[OSMOSE] Calcul de la déduplication...")
            ids_to_delete, claims_to_keep, stats_per_doc = deduplicate_claims(claims)

            # 3. Afficher le résumé
            total_removed = len(ids_to_delete)
            total_kept = len(claims_to_keep)
            logger.info(f"\n{'='*60}")
            logger.info(f"RÉSUMÉ DÉDUPLICATION")
            logger.info(f"{'='*60}")
            logger.info(f"Claims initiales : {len(claims)}")
            logger.info(f"Claims à supprimer: {total_removed} ({100*total_removed/len(claims):.1f}%)")
            logger.info(f"Claims conservées : {total_kept}")
            logger.info(f"Documents affectés: {len(stats_per_doc)}")

            if stats_per_doc:
                logger.info(f"\nDétail par document (top 10):")
                sorted_docs = sorted(
                    stats_per_doc.items(),
                    key=lambda x: x[1]["removed_text"] + x[1]["removed_spo"],
                    reverse=True,
                )
                for doc_id, s in sorted_docs[:10]:
                    doc_short = doc_id[:60] + "..." if len(doc_id) > 60 else doc_id
                    logger.info(
                        f"  {doc_short}: {s['initial']} → {s['kept']} "
                        f"(-{s['removed_text']} texte, -{s['removed_spo']} SPO)"
                    )

            if args.dry_run:
                logger.info("\n[DRY-RUN] Aucune modification effectuée.")
                return

            # 4. Supprimer les doublons
            if ids_to_delete:
                logger.info(f"\n[OSMOSE] Suppression de {total_removed} claims doublons...")
                deleted = delete_claims_batch(session, ids_to_delete)
                logger.info(f"  → {deleted} claims supprimées de Neo4j")

                # 5. Nettoyer les passages orphelins
                logger.info("[OSMOSE] Nettoyage des passages orphelins...")
                orphans = cleanup_orphan_passages(session, args.tenant)
                logger.info(f"  → {orphans} passages orphelins supprimés")
            else:
                logger.info("\nAucun doublon trouvé — base déjà propre.")

            # 6. Calculer content_fingerprint
            if not args.skip_fingerprint:
                logger.info(f"[OSMOSE] Calcul content_fingerprint sur {total_kept} claims...")
                updated = set_content_fingerprints(session, claims_to_keep)
                logger.info(f"  → {updated} claims mises à jour avec content_fingerprint")

            logger.info("\n[OSMOSE] Déduplication terminée.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
