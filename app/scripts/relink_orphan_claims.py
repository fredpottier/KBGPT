#!/usr/bin/env python3
"""
relink_orphan_claims.py — Rattrape les claims sans relation ABOUT vers une Entity.

Cause racine : le claim_persister faisait MATCH Entity par entity_id, mais le MERGE
Entity utilise normalized_name. Quand deux docs créent la même entité, le second doc
perd ses liens ABOUT car l'entity_id ne correspond plus au node Neo4j.

Ce script :
1. Charge toutes les claims sans ABOUT
2. Pour chaque claim, extrait les entités candidates (regex déterministe, même logique
   que EntityExtractor)
3. Pour chaque candidat, cherche l'Entity existante par normalized_name dans Neo4j
4. Crée la relation ABOUT si le match est trouvé
5. Log les stats (claims reliées, toujours orphelines, entités non trouvées)

Usage :
    docker compose exec app python scripts/relink_orphan_claims.py --dry-run
    docker compose exec app python scripts/relink_orphan_claims.py --execute
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from collections import Counter
from typing import Dict, List, Set, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("[OSMOSE] relink_orphan_claims")


# Patterns identiques à EntityExtractor
CAPITALIZED_TERM_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
ACRONYM_PATTERN = re.compile(r"\b([A-Z]{2,}(?:/[A-Z]+)?)\b")

# Articles/pronoms à filtrer en début de terme
_ARTICLES = {
    "the", "a", "an", "this", "that", "these", "those",
    "its", "their", "our", "your", "his", "her", "my",
    "le", "la", "les", "un", "une", "des", "ce", "cette", "ces",
}

# Termes trop courts ou trop génériques à ignorer
_MIN_LENGTH = 2
_MAX_WORDS = 6
_MAX_CHARS = 50


def get_neo4j_driver():
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def load_orphan_claims(session, tenant_id: str) -> List[dict]:
    """Charge les claims sans aucune relation ABOUT."""
    result = session.run("""
        MATCH (c:Claim {tenant_id: $tid})
        WHERE NOT EXISTS { MATCH (c)-[:ABOUT]->(:Entity) }
        RETURN c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id
    """, tid=tenant_id)
    return [dict(r) for r in result]


def load_entity_index(session, tenant_id: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Charge deux index pour les entités :
    - exact: normalized_name → entity_id (match exact)
    - acronym: acronyme contenu dans le nom → entity_id (pour GDPR, DSA, etc.)
    """
    result = session.run("""
        MATCH (e:Entity {tenant_id: $tid})
        RETURN e.normalized_name AS norm, e.entity_id AS eid, e.name AS name
    """, tid=tenant_id)

    exact: Dict[str, str] = {}
    acronym_index: Dict[str, str] = {}

    for r in result:
        norm = r["norm"]
        eid = r["eid"]
        name = r["name"] or ""
        if not norm:
            continue
        exact[norm] = eid

        # Extraire les acronymes entre parenthèses : "General Data Protection Regulation (GDPR)"
        import re as _re
        for acr_match in _re.finditer(r"\(([A-Z]{2,})\)", name):
            acr = acr_match.group(1).lower()
            if acr not in acronym_index:
                acronym_index[acr] = eid

    return exact, acronym_index


def load_stoplist() -> Set[str]:
    """Charge la stoplist d'entités."""
    try:
        from knowbase.claimfirst.models.entity import ENTITY_STOPLIST
        return ENTITY_STOPLIST
    except Exception:
        return set()


def is_valid_candidate(name: str, stoplist: Set[str]) -> bool:
    """Vérifie si un candidat est valide (même logique que EntityExtractor)."""
    if not name or len(name) < _MIN_LENGTH:
        return False

    normalized = name.lower().strip()

    if normalized in stoplist:
        return False

    if len(name) > _MAX_CHARS:
        return False

    if len(name.split()) > _MAX_WORDS:
        return False

    # Pas que des chiffres
    if normalized.replace("-", "").replace(" ", "").isdigit():
        return False

    # Commence par un article/pronom
    first_word = name.split()[0].lower()
    if first_word in _ARTICLES:
        return False

    # Fragment indicators
    try:
        from knowbase.claimfirst.models.entity import PHRASE_FRAGMENT_INDICATORS
        if first_word in PHRASE_FRAGMENT_INDICATORS:
            return False
    except Exception:
        pass

    return True


def extract_candidates(text: str, stoplist: Set[str]) -> List[str]:
    """Extrait les entités candidates depuis le texte d'une claim."""
    candidates = []
    seen = set()

    # Termes capitalisés multi-mots
    for match in CAPITALIZED_TERM_PATTERN.finditer(text):
        term = match.group(1)
        if is_valid_candidate(term, stoplist):
            norm = term.lower().strip()
            if norm not in seen:
                seen.add(norm)
                candidates.append(norm)

    # Acronymes
    for match in ACRONYM_PATTERN.finditer(text):
        acronym = match.group(1)
        if len(acronym) >= 2 and is_valid_candidate(acronym, stoplist):
            norm = acronym.lower().strip()
            if norm not in seen:
                seen.add(norm)
                candidates.append(norm)

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Re-lie les claims orphelines aux entités existantes")
    parser.add_argument("--execute", action="store_true", help="Exécuter (sinon dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier le KG")
    parser.add_argument("--tenant-id", default="default", help="Tenant ID")
    args = parser.parse_args()

    if not args.execute and not args.dry_run:
        print("Usage: --execute ou --dry-run")
        sys.exit(1)

    driver = get_neo4j_driver()
    stoplist = load_stoplist()
    logger.info(f"Stoplist: {len(stoplist)} termes")

    with driver.session() as session:
        # 1. Charger les orphelins
        orphans = load_orphan_claims(session, args.tenant_id)
        logger.info(f"Claims orphelines: {len(orphans)}")

        if not orphans:
            logger.info("Aucune claim orpheline, rien à faire.")
            return

        # 2. Charger l'index des entités
        entity_exact, entity_acronyms = load_entity_index(session, args.tenant_id)
        logger.info(f"Entités indexées: {len(entity_exact)} exact + {len(entity_acronyms)} acronymes")

    # 3. Pour chaque orphelin, extraire les candidats et matcher
    links_to_create: List[Tuple[str, str]] = []  # (claim_id, entity_id)
    claims_relinked = 0
    claims_still_orphan = 0
    entity_matches = Counter()
    entity_misses = Counter()

    for orphan in orphans:
        claim_id = orphan["claim_id"]
        text = orphan["text"] or ""

        candidates = extract_candidates(text, stoplist)

        matched = False
        for norm in candidates:
            # Match exact d'abord
            entity_id = entity_exact.get(norm)
            # Fallback : match par acronyme
            if not entity_id:
                entity_id = entity_acronyms.get(norm)
            # Fallback : pluriel/singulier
            if not entity_id and norm.endswith("s"):
                entity_id = entity_exact.get(norm[:-1])
            if not entity_id and not norm.endswith("s"):
                entity_id = entity_exact.get(norm + "s")
            if entity_id:
                links_to_create.append((claim_id, entity_id))
                entity_matches[norm] += 1
                matched = True
            else:
                entity_misses[norm] += 1

        if matched:
            claims_relinked += 1
        else:
            claims_still_orphan += 1

    logger.info(f"\n{'='*60}")
    logger.info(f"RÉSULTATS")
    logger.info(f"{'='*60}")
    logger.info(f"Claims orphelines analysées: {len(orphans)}")
    logger.info(f"Claims re-liées: {claims_relinked}")
    logger.info(f"Claims toujours orphelines: {claims_still_orphan}")
    logger.info(f"Liens ABOUT à créer: {len(links_to_create)}")

    logger.info(f"\nTop 15 entités matchées:")
    for norm, cnt in entity_matches.most_common(15):
        logger.info(f"  {norm:50s} {cnt:4d} liens")

    logger.info(f"\nTop 15 candidats sans entité (non trouvés dans le KG):")
    for norm, cnt in entity_misses.most_common(15):
        logger.info(f"  {norm:50s} {cnt:4d} occurrences")

    if args.dry_run:
        logger.info(f"\n=== DRY RUN — aucune modification ===")
        driver.close()
        return

    # 4. Persister les liens
    logger.info(f"\nCréation de {len(links_to_create)} liens ABOUT...")
    start = time.time()

    BATCH_SIZE = 500
    total_created = 0
    with driver.session() as session:
        for i in range(0, len(links_to_create), BATCH_SIZE):
            batch = [
                {"claim_id": cid, "entity_id": eid}
                for cid, eid in links_to_create[i:i + BATCH_SIZE]
            ]
            result = session.run("""
                UNWIND $batch AS item
                MATCH (c:Claim {claim_id: item.claim_id})
                MATCH (e:Entity {entity_id: item.entity_id})
                MERGE (c)-[r:ABOUT]->(e)
                ON CREATE SET r.method = 'relink_orphan'
                RETURN count(r) AS created
            """, batch=batch)
            created = result.single()["created"]
            total_created += created
            logger.info(f"  Batch {i//BATCH_SIZE + 1}: {created} liens créés")

    elapsed = time.time() - start
    logger.info(f"\nTerminé: {total_created} liens ABOUT créés en {elapsed:.1f}s")

    # 5. Vérification finale
    with driver.session() as session:
        result = session.run("""
            MATCH (c:Claim {tenant_id: $tid})
            WITH count(c) AS total,
                 sum(CASE WHEN EXISTS { MATCH (c)-[:ABOUT]->() } THEN 1 ELSE 0 END) AS linked
            RETURN total, linked, total - linked AS orphans,
                   round(100.0 * linked / total) AS pct_linked
        """, tid=args.tenant_id)
        r = result.single()
        logger.info(f"\nÉtat final du KG:")
        logger.info(f"  Total claims: {r['total']}")
        logger.info(f"  Claims liées: {r['linked']} ({r['pct_linked']}%)")
        logger.info(f"  Orphelines restantes: {r['orphans']}")

    driver.close()


if __name__ == "__main__":
    main()
