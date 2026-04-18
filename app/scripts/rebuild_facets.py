#!/usr/bin/env python3
"""
rebuild_facets.py — Reconstruit le FacetRegistry depuis les claims existantes dans Neo4j.

Utile en cas de crash du worker : les claims sont persistees doc par doc,
mais le FacetRegistry (en memoire) est perdu si le job ne termine pas.

Ce script :
1. Charge tous les doc_ids distincts depuis les Claims dans Neo4j
2. Pour chaque doc : collecte un echantillon de claims + le titre
3. Appelle FacetCandidateExtractor (1 appel LLM par doc, ~200-500 tokens)
4. Enregistre dans FacetRegistry (accumulation cross-doc)
5. Persiste les facettes dans Neo4j

Usage :
    docker compose exec app python app/scripts/rebuild_facets.py --dry-run
    docker compose exec app python app/scripts/rebuild_facets.py --execute
    docker compose exec app python app/scripts/rebuild_facets.py --execute --purge-old
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("[OSMOSE] rebuild_facets")


def get_neo4j_driver():
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def load_docs_from_claims(session, tenant_id: str) -> list:
    """
    Charge tous les doc_ids distincts depuis les Claims existantes.
    Pour chaque doc, recupere un echantillon de claims + le doc_id comme titre.
    """
    result = session.run(
        """
        MATCH (c:Claim {tenant_id: $tid})
        WITH c.doc_id AS doc_id, count(c) AS claim_count,
             collect(c.text)[..10] AS sample_claims
        RETURN doc_id, claim_count, sample_claims
        ORDER BY claim_count DESC
        """,
        tid=tenant_id,
    )
    docs = []
    for r in result:
        doc_id = r["doc_id"]
        if not doc_id:
            continue
        # Extraire un titre lisible depuis le doc_id (PMC..._titre_hash)
        title = doc_id
        parts = doc_id.split("_")
        if len(parts) > 2:
            # Enlever le hash final et le PMC ID initial
            title = " ".join(parts[1:-1]).replace("_", " ").title()

        docs.append({
            "doc_id": doc_id,
            "title": title,
            "claim_count": r["claim_count"] or 0,
            "sample_claims": [c for c in (r["sample_claims"] or []) if c],
        })
    return docs


def purge_old_facets(session, tenant_id: str) -> int:
    """Supprime les anciennes facettes du tenant."""
    result = session.run(
        "MATCH (f:Facet {tenant_id: $tid}) DETACH DELETE f RETURN count(f) AS deleted",
        tid=tenant_id,
    )
    record = result.single()
    return record["deleted"] if record else 0


def _consolidate_facets_llm(registry) -> int:
    """
    Consolide les facettes near-duplicates via pré-clustering embedding + validation LLM.

    Scalable : ne dépend pas de la taille totale de la liste.
    1. Encode tous les noms de facettes via sentence-transformers
    2. Pré-cluster par cosine similarity (seuil 0.75)
    3. Pour chaque cluster de 2+ candidats, demande au LLM de valider le merge
    4. Applique les merges validés dans le registre
    """
    from knowbase.common.llm_router import get_llm_router, TaskType
    import json as _json

    all_facets = registry.get_all_facets()
    if len(all_facets) < 2:
        return 0

    names = [f.facet_name for f in all_facets]
    keys = [f.domain for f in all_facets]
    logger.info(f"  Consolidation: {len(names)} facettes à analyser")

    # 1. Pré-cluster par similarité textuelle (SequenceMatcher)
    # Plus adapté que les embeddings pour les noms courts de facettes
    from difflib import SequenceMatcher
    SIMILARITY_THRESHOLD = 0.75

    parent = list(range(len(names)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            ratio = SequenceMatcher(None, names[i].lower(), names[j].lower()).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                union(i, j)

    # Construire les groupes
    from collections import defaultdict
    groups = defaultdict(list)
    for i in range(len(names)):
        groups[find(i)].append(i)

    merge_candidates = {k: v for k, v in groups.items() if len(v) >= 2}
    logger.info(f"  Pré-clustering: {len(merge_candidates)} groupes de near-duplicates")

    if not merge_candidates:
        return 0

    # 3. Validation LLM par groupe
    router = get_llm_router()
    total_merges = 0

    for group_id, members in merge_candidates.items():
        member_names = [names[i] for i in members]
        member_docs = [all_facets[i].source_doc_count for i in members]

        prompt_lines = [
            f'- "{member_names[j]}" (docs={member_docs[j]})'
            for j in range(len(members))
        ]

        try:
            result = router.complete(
                task_type=TaskType.METADATA_EXTRACTION,
                messages=[
                    {"role": "system", "content": (
                        "You consolidate near-duplicate facet names. "
                        "Given a group of similar names, decide if they should be merged. "
                        "If yes, pick the best canonical name. If some are distinct, keep them separate.\n\n"
                        "Output JSON only: {\"merge\": true/false, \"canonical\": \"Best Name\", "
                        "\"members_to_merge\": [0, 1, 2]} (indices in the input list)\n"
                        "If merge=false, output {\"merge\": false}"
                    )},
                    {"role": "user", "content": (
                        f"Should these {len(members)} facets be merged?\n\n"
                        + "\n".join(prompt_lines)
                    )},
                ],
                max_tokens=200,
                temperature=0.1,
            )

            text = result.text if hasattr(result, "text") else str(result)
            # Parse JSON from response
            text = text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = _json.loads(text.strip())

            if data.get("merge") and data.get("canonical"):
                canonical = data["canonical"]
                indices_to_merge = data.get("members_to_merge", list(range(len(members))))
                keys_to_merge = [keys[members[j]] for j in indices_to_merge if j < len(members)]
                target_key = keys[members[0]]

                # Appliquer le merge dans le registre
                for k in keys_to_merge:
                    if k != target_key:
                        registry.merge_facets(target_key, k, canonical_name=canonical)
                        total_merges += 1

                logger.info(
                    f"  Merge: {[member_names[j] for j in indices_to_merge]} "
                    f"→ \"{canonical}\""
                )
            else:
                logger.info(f"  No merge: {member_names[:3]}...")

        except Exception as e:
            logger.warning(f"  LLM merge check failed for {member_names[:2]}: {e}")

    return total_merges


def _consolidate_facets_levenshtein(registry) -> int:
    """Fallback : consolidation par Levenshtein si embeddings indisponibles."""
    from difflib import SequenceMatcher

    all_facets = registry.get_all_facets()
    names = [(f.dimension_key, f.canonical_name) for f in all_facets]
    merges = 0

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            ratio = SequenceMatcher(None, names[i][1].lower(), names[j][1].lower()).ratio()
            if ratio > 0.85:
                try:
                    registry.merge_facets(names[i][0], names[j][0], canonical_name=names[i][1])
                    merges += 1
                    logger.info(f"  Levenshtein merge: \"{names[j][1]}\" → \"{names[i][1]}\" (ratio={ratio:.2f})")
                except Exception:
                    pass
    return merges


def main():
    parser = argparse.ArgumentParser(description="Reconstruit le FacetRegistry depuis Neo4j")
    parser.add_argument("--execute", action="store_true", help="Executer (sinon dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (affiche sans executer)")
    parser.add_argument("--purge-old", action="store_true",
                        help="Supprimer les anciennes facettes avant reconstruction")
    parser.add_argument("--tenant-id", default="default", help="Tenant ID")
    args = parser.parse_args()

    if not args.execute and not args.dry_run:
        print("Usage: --execute pour executer, --dry-run pour simuler")
        sys.exit(1)

    driver = get_neo4j_driver()

    with driver.session() as session:
        docs = load_docs_from_claims(session, args.tenant_id)

    logger.info(f"Trouvé {len(docs)} documents avec claims dans Neo4j")

    if not docs:
        logger.info("Aucun document trouvé, rien à faire.")
        return

    # Afficher le resume
    total_claims = sum(d["claim_count"] for d in docs)
    logger.info(f"Total claims: {total_claims}")
    logger.info(f"Top 5 documents:")
    for d in docs[:5]:
        logger.info(f"  {d['doc_id'][:60]:60s} {d['claim_count']:4d} claims")

    if args.dry_run:
        logger.info("\n=== DRY RUN — pas d'execution ===")
        logger.info(f"Documents a traiter: {len(docs)}")
        logger.info(f"Appels LLM estimes: {len(docs)} (1 par doc, ~300 tokens chacun)")
        return

    # --- Execution ---
    from knowbase.claimfirst.linkers.facet_registry import FacetRegistry
    from knowbase.claimfirst.extractors.facet_candidate_extractor import FacetCandidateExtractor

    # Purger les anciennes facettes si demande
    if args.purge_old:
        with driver.session() as session:
            deleted = purge_old_facets(session, args.tenant_id)
            logger.info(f"Purge: {deleted} anciennes facettes supprimées")

    # Creer le registre et l'extracteur
    registry = FacetRegistry(args.tenant_id)
    # Ne pas charger les facettes existantes si on a purge
    if not args.purge_old:
        registry.load_from_neo4j(driver)
    extractor = FacetCandidateExtractor()

    # Traiter chaque document
    errors = 0
    for i, doc in enumerate(docs, 1):
        doc_id = doc["doc_id"]
        title = doc["title"]
        sample_claims = doc["sample_claims"]

        logger.info(f"[{i}/{len(docs)}] {doc_id[:60]}...")

        try:
            from knowbase.claimfirst.extractors.facet_candidate_extractor import (
                _build_user_prompt,
                _parse_llm_response,
                SYSTEM_PROMPT,
            )
            from knowbase.common.llm_router import get_llm_router, TaskType

            router = get_llm_router()
            user_prompt = _build_user_prompt(title, "", sample_claims)

            result = router.complete(
                task_type=TaskType.METADATA_EXTRACTION,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=500,
                temperature=0.3,
            )

            candidates = []
            if result:
                text = result.text if hasattr(result, 'text') else str(result)
                if text:
                    candidates = _parse_llm_response(text, doc_id)

            if candidates:
                registry.register_candidates(candidates)
                dims = [c.dimension_key for c in candidates]
                logger.info(f"  -> {len(candidates)} facettes: {dims}")
            else:
                logger.warning(f"  -> 0 facettes extraites")

            # Pause pour respecter les rate limits LLM
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"  -> Erreur: {e}")
            errors += 1

    # Phase 1.5 : Consolidation LLM des near-duplicates
    logger.info("\nConsolidation des facettes near-duplicates...")
    merge_count = _consolidate_facets_llm(registry)
    logger.info(f"  → {merge_count} merges appliqués")

    # Persister
    logger.info("\nPersistance des facettes dans Neo4j...")
    persisted = registry.persist_to_neo4j(driver)

    # Phase 2 : Matching claims → facettes validées
    validated = registry.get_validated_facets()
    facet_links_created = 0
    if validated:
        logger.info(f"\nMatching claims → {len(validated)} facettes validées...")
        facet_links_created = _match_claims_to_facets(driver, args.tenant_id, validated)
    else:
        logger.info("\nAucune facette validée — matching ignoré.")

    # Stats finales
    stats = registry.get_stats()
    logger.info(f"\n{'='*60}")
    logger.info(f"REBUILD FACETS TERMINE")
    logger.info(f"{'='*60}")
    logger.info(f"Documents traités: {len(docs)}")
    logger.info(f"Erreurs: {errors}")
    logger.info(f"Facettes persistees: {persisted}")
    logger.info(f"Total facettes: {stats['total']}")
    logger.info(f"Par lifecycle: {stats['by_lifecycle']}")
    logger.info(f"Par famille: {stats['by_family']}")
    logger.info(f"Near-duplicates: {stats['near_duplicates']}")
    logger.info(f"Liens claim→facette: {facet_links_created}")

    near_dups = registry.get_near_duplicate_queue()
    if near_dups:
        logger.info(f"\nNear-duplicates a revoir:")
        for k1, k2, score in near_dups[:20]:
            logger.info(f"  '{k1}' ~ '{k2}' (score={score:.2f})")

    driver.close()


def _match_claims_to_facets(driver, tenant_id: str, validated_facets) -> int:
    """Matche toutes les claims du KG aux facettes validées et persiste les liens."""
    from knowbase.claimfirst.linkers.facet_matcher import FacetMatcher
    from knowbase.claimfirst.models.claim import Claim

    matcher = FacetMatcher()

    with driver.session() as session:
        # Charger toutes les claims
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})
            RETURN c.claim_id AS claim_id, c.text AS text,
                   c.tenant_id AS tenant_id, c.doc_id AS doc_id,
                   c.claim_type AS claim_type,
                   c.verbatim_quote AS verbatim_quote,
                   c.passage_id AS passage_id
            """,
            tid=tenant_id,
        )

        claims = []
        for r in result:
            try:
                claims.append(Claim.model_construct(
                    claim_id=r["claim_id"],
                    text=r["text"] or "",
                    tenant_id=r["tenant_id"],
                    doc_id=r["doc_id"] or "unknown",
                    unit_ids=[],
                    claim_type=r["claim_type"] or "FACTUAL",
                    verbatim_quote=r["verbatim_quote"] or r["text"] or "",
                    passage_id=r["passage_id"] or "unknown",
                ))
            except Exception:
                continue

        logger.info(f"  Loaded {len(claims)} claims pour matching")

        # Matcher (mode post-import keyword-only — FacetMatcher detecte automatiquement
        # l'absence de doc_facet_ids et bascule sur _assign_keyword_only permissif).
        _, links = matcher.match(
            claims=claims,
            tenant_id=tenant_id,
            validated_facets=validated_facets,
        )

        logger.info(f"  Matched: {len(links)} liens claim→facet")

        # Persister les liens BELONGS_TO_FACET
        if links:
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()

            batch = [
                {"claim_id": cid, "facet_id": fid, "assigned_at": now_iso}
                for cid, fid in links
            ]

            for start in range(0, len(batch), 2000):
                chunk = batch[start:start + 2000]
                session.run("""
                    UNWIND $batch AS item
                    MATCH (c:Claim {claim_id: item.claim_id})
                    MATCH (f:Facet {facet_id: item.facet_id})
                    MERGE (c)-[r:BELONGS_TO_FACET]->(f)
                    SET r.assigned_at = item.assigned_at
                """, batch=chunk)

            logger.info(f"  → {len(links)} liens persistés dans Neo4j")

        return len(links)


if __name__ == "__main__":
    main()
