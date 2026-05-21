"""Rétro-application A2.8 SupersessionApplier sur les relations existantes du KG.

Cf ADR_RELATIONS_CLAIM_CLAIM §2.4 Phase C + ADR_BITEMPOREL §9.4.

Contexte : le pipeline post-import du 20/05/2026 a créé des relations
:CONTRADICTS / :REFINES / :QUALIFIES via `_run_detect_contradictions` (étape #7)
SANS appliquer le setter `invalidated_at` sur les claims cibles. Le SupersessionApplier
(A2.8) a été ajouté APRÈS — il faut donc rétro-appliquer la règle §9.4 sur
les relations déjà persistées.

Ce script :
  1. Liste les relations CONTRADICTS / EVOLUTION_OF / EVOLVES_TO existantes
  2. Pour chacune, appelle SupersessionApplier.apply() qui :
     - Lit les snapshots temporels A et B
     - Classifie CAS 1/2/3/4 §9.4
     - Crée :SUPERSEDES + invalide loser (CAS 1, CAS 2)
     - OU crée :ConflictPending (CAS 1_EQUAL, 3, 4)
  3. Idempotent (skip si claim déjà invalidé)

Aucun appel LLM. Logique 100% déterministe basée sur les 4 timestamps des claims.

Usage:
    docker exec knowbase-app sh -c 'python /app/scripts/apply_supersession_existing_contradicts.py --tenant default [--dry-run]'
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

from neo4j import GraphDatabase

from knowbase.relations.supersession_applier import SupersessionApplier


# Relations CROSS-CLAIM qui peuvent déclencher la règle de supersession.
# (REFINES / QUALIFIES n'invalident pas par construction — cf ADR §2.1 — donc exclus)
SUPERSESSION_TRIGGERING_RELATIONS = ["CONTRADICTS", "EVOLUTION_OF", "EVOLVES_TO"]


def list_supersession_triggering_relations(driver, tenant_id: str) -> list[dict]:
    """Retourne toutes les paires (A, B, relation_type) candidates à supersession."""
    rel_union = "|".join(SUPERSESSION_TRIGGERING_RELATIONS)
    cypher = f"""
    MATCH (a:Claim {{tenant_id: $tid}})-[r:{rel_union}]-(b:Claim {{tenant_id: $tid}})
    WHERE a.claim_id < b.claim_id  // évite les doubles pour symétriques (CONTRADICTS)
    RETURN
        type(r) AS relation_type,
        a.claim_id AS claim_a_id,
        b.claim_id AS claim_b_id,
        coalesce(r.evidence_a, '') AS evidence_a,
        coalesce(r.evidence_b, '') AS evidence_b,
        coalesce(r.confidence, 0.0) AS confidence,
        coalesce(r.marker_type, 'inferred') AS marker_type,
        coalesce(r.method, 'unknown') AS detection_method,
        coalesce(r.reasoning, r.basis, '') AS reasoning
    """
    with driver.session() as session:
        return [dict(record) for record in session.run(cypher, tid=tenant_id)]


def count_supersedes_before(driver, tenant_id: str) -> dict:
    """État avant : nb de :SUPERSEDES, claims invalidés, ConflictPending."""
    with driver.session() as session:
        r1 = session.run(
            "MATCH ()-[r:SUPERSEDES]->() WHERE r IS NOT NULL RETURN count(r) AS n"
        ).single()
        r2 = session.run(
            "MATCH (c:Claim {tenant_id: $tid}) WHERE c.invalidated_at IS NOT NULL RETURN count(c) AS n",
            tid=tenant_id,
        ).single()
        r3 = session.run(
            "MATCH (cp:ConflictPending {tenant_id: $tid}) RETURN count(cp) AS n",
            tid=tenant_id,
        ).single()
    return {
        "supersedes": r1["n"] if r1 else 0,
        "claims_invalidated": r2["n"] if r2 else 0,
        "conflict_pending": r3["n"] if r3 else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Rétro-application A2.8 SupersessionApplier sur relations existantes")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--dry-run", action="store_true", help="Affiche le plan sans écrire")
    parser.add_argument("--bolt", default="bolt://neo4j:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="graphiti_neo4j_pass")
    parser.add_argument("--limit", type=int, default=None, help="Limite (pour tests)")
    args = parser.parse_args()

    print(f"=== Rétro-application A2.8 — tenant={args.tenant} dry_run={args.dry_run} ===")
    driver = GraphDatabase.driver(args.bolt, auth=(args.user, args.password))

    print()
    print("▶ État du KG AVANT :")
    before = count_supersedes_before(driver, args.tenant)
    print(f"    :SUPERSEDES existantes  : {before['supersedes']}")
    print(f"    Claims invalidated_at   : {before['claims_invalidated']}")
    print(f"    :ConflictPending nodes  : {before['conflict_pending']}")

    print()
    print("▶ Énumération des paires candidates...")
    pairs = list_supersession_triggering_relations(driver, args.tenant)
    print(f"    {len(pairs)} paires (A, B, relation_type) trouvées")

    # Distribution par relation_type
    distrib = Counter(p["relation_type"] for p in pairs)
    for rt, n in distrib.most_common():
        print(f"      {rt}: {n}")

    if args.limit:
        pairs = pairs[: args.limit]
        print(f"    [limit appliqué : {len(pairs)} paires retenues]")

    if args.dry_run:
        print()
        print(f"✅ DRY-RUN : aucune écriture. {len(pairs)} paires seraient soumises au SupersessionApplier.")
        driver.close()
        return 0

    print()
    print("▶ Application SupersessionApplier sur chaque paire...")
    start = time.time()
    applier = SupersessionApplier(driver, tenant_id=args.tenant)
    actions = Counter()
    cases = Counter()
    errors = 0

    for i, p in enumerate(pairs, start=1):
        if i % 100 == 0:
            print(f"    [{i}/{len(pairs)}] actions: {dict(actions)} cases: {dict(cases)}")
        try:
            # Normaliser EVOLVES_TO → EVOLUTION_OF côté applier (rétro-compat A2.10)
            relation_for_applier = "EVOLUTION_OF" if p["relation_type"] == "EVOLVES_TO" else p["relation_type"]
            decision = applier.apply(
                claim_a_id=p["claim_a_id"],
                claim_b_id=p["claim_b_id"],
                relation_type=relation_for_applier,
                evidence_a=p["evidence_a"],
                evidence_b=p["evidence_b"],
                confidence=p["confidence"],
                marker_type=p["marker_type"],
                detection_method=p["detection_method"],
                detection_source="retro_apply_a2_8",
                reasoning=p["reasoning"],
            )
            actions[decision.action] += 1
            if decision.evolution_case:
                cases[decision.evolution_case] += 1
        except Exception as e:
            errors += 1
            print(f"    ERR pair {p['claim_a_id']} vs {p['claim_b_id']}: {e}")

    duration = time.time() - start

    print()
    print(f"=== Rétro-application terminée en {duration:.1f}s ===")
    print(f"    Paires traitées      : {len(pairs)}")
    print(f"    Actions :")
    for action, count in actions.most_common():
        print(f"      {action}: {count}")
    print(f"    CAS §9.4 distribution :")
    for case, count in cases.most_common():
        print(f"      {case}: {count}")
    print(f"    Erreurs              : {errors}")

    print()
    print("▶ État du KG APRÈS :")
    after = count_supersedes_before(driver, args.tenant)
    print(f"    :SUPERSEDES             : {after['supersedes']} (+{after['supersedes'] - before['supersedes']})")
    print(f"    Claims invalidated_at   : {after['claims_invalidated']} (+{after['claims_invalidated'] - before['claims_invalidated']})")
    print(f"    :ConflictPending nodes  : {after['conflict_pending']} (+{after['conflict_pending'] - before['conflict_pending']})")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
