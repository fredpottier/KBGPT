"""Audit qualité A2.13 — vérifie l'amélioration du detect_contradictions avec le nouveau prompt.

Sample 5 exemples par type de relation produite (CONTRADICTS, REFINES, QUALIFIES) + ConflictPending,
puis affiche les paires (a_text, b_text, reasoning) pour audit manuel rapide.

Comparaison attendue vs A2.12 baseline :
  - CONTRADICTS  : avant 113 → attendu beaucoup moins (~10-30) car nouveau prompt + strict
  - REFINES      : avant 584 → attendu stable ou +
  - QUALIFIES    : avant 716 → attendu stable ou +
  - COMPATIBLE   : nouveau label non persisté (Cypher ne match que CONTRADICTS|REFINES|QUALIFIES) → on doit s'attendre à ce que le LLM produise plus de COMPATIBLE et donc MOINS de relations totales

Usage:
    docker exec knowbase-app sh -c 'python /app/scripts/audit_a2_13_quality.py --tenant default'
"""

from __future__ import annotations

import argparse
import sys

from neo4j import GraphDatabase


def sample_relations(driver, tenant_id: str, rel_type: str, limit: int = 5) -> list[dict]:
    """Échantillon de relations par type, avec texts + reasoning."""
    cypher = f"""
    MATCH (a:Claim {{tenant_id: $tid}})-[r:{rel_type}]->(b:Claim {{tenant_id: $tid}})
    WHERE coalesce(r.method, '') = 'post_import_cross_doc'
    RETURN
        substring(coalesce(a.text, ''), 0, 180) AS a_text,
        substring(coalesce(b.text, ''), 0, 180) AS b_text,
        substring(coalesce(a.doc_id, ''), 0, 50) AS a_doc,
        substring(coalesce(b.doc_id, ''), 0, 50) AS b_doc,
        coalesce(r.confidence, 0.0) AS confidence,
        substring(coalesce(r.basis, r.reasoning, ''), 0, 200) AS reason
    LIMIT {limit}
    """
    with driver.session() as session:
        return [dict(record) for record in session.run(cypher, tid=tenant_id)]


def count_by_type(driver, tenant_id: str) -> dict:
    """Compte global par type de relation issue de post_import_cross_doc."""
    cypher = """
    MATCH (a:Claim {tenant_id: $tid})-[r:CONTRADICTS|REFINES|QUALIFIES]->(b:Claim {tenant_id: $tid})
    WHERE coalesce(r.method, '') = 'post_import_cross_doc'
    RETURN type(r) AS rt, count(DISTINCT r) AS n
    """
    counts = {}
    with driver.session() as session:
        for r in session.run(cypher, tid=tenant_id):
            counts[r["rt"]] = r["n"]

        # ConflictPending + SUPERSEDES (sous-produits)
        r = session.run(
            "MATCH (cp:ConflictPending {tenant_id: $tid}) RETURN count(cp) AS n",
            tid=tenant_id,
        ).single()
        counts["ConflictPending"] = r["n"] if r else 0

        r = session.run(
            """
            MATCH ()-[r:SUPERSEDES]->() WHERE startNode(r).tenant_id = $tid OR endNode(r).tenant_id = $tid
            RETURN count(r) AS n
            """,
            tid=tenant_id,
        ).single()
        counts["SUPERSEDES"] = r["n"] if r else 0

        r = session.run(
            "MATCH (c:Claim {tenant_id: $tid}) WHERE c.invalidated_at IS NOT NULL RETURN count(c) AS n",
            tid=tenant_id,
        ).single()
        counts["claims_invalidated"] = r["n"] if r else 0

    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--bolt", default="bolt://neo4j:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="graphiti_neo4j_pass")
    parser.add_argument("--samples", type=int, default=5, help="Nombre d'exemples par type")
    args = parser.parse_args()

    print(f"=== Audit qualité A2.13 — tenant={args.tenant} ===\n")
    driver = GraphDatabase.driver(args.bolt, auth=(args.user, args.password))

    # Stats globales
    print("▶ COMPTAGES post-A2.13 (vs baseline A2.12) :")
    counts = count_by_type(driver, args.tenant)
    baseline = {
        "CONTRADICTS": 113,
        "REFINES": 584,
        "QUALIFIES": 716,
        "ConflictPending": 73,
        "SUPERSEDES": 27,
        "claims_invalidated": 27,
    }
    for k in ["CONTRADICTS", "REFINES", "QUALIFIES", "SUPERSEDES", "ConflictPending", "claims_invalidated"]:
        actual = counts.get(k, 0)
        delta = actual - baseline.get(k, 0)
        sign = "+" if delta >= 0 else ""
        print(f"    {k:<22}: {actual:>5} (baseline A2.12: {baseline[k]:>5}, delta {sign}{delta})")

    print()

    # Échantillons par type
    for rel_type in ["CONTRADICTS", "REFINES", "QUALIFIES"]:
        n_total = counts.get(rel_type, 0)
        if n_total == 0:
            print(f"=== {rel_type} (0 relations) — aucun échantillon ===\n")
            continue
        print(f"=== {rel_type} ({n_total} relations) — {args.samples} exemples ===")
        samples = sample_relations(driver, args.tenant, rel_type, limit=args.samples)
        for i, s in enumerate(samples, 1):
            print(f"\n-- Ex {i} (confidence={s['confidence']:.2f}) --")
            print(f"  A doc={s['a_doc']}")
            print(f"    {s['a_text']}")
            print(f"  B doc={s['b_doc']}")
            print(f"    {s['b_text']}")
            if s["reason"]:
                print(f"  reason: {s['reason']}")
        print()

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
