"""Mine des contradictions candidates DANS chaque KeyPoint (même question, stance
opposée, cross-doc), crée les arêtes :CONTRADICTS, puis délègue à l'adjudicateur
EXISTANT (passages sources + vote anti-variance).

C'est le chemin qui rattrape les contradictions que la détection actuelle rate :
elle apparie par tokens (Jaccard) + claim-key sujet|prédicat. Ici on apparie par
le KeyPoint (la question normalisée commune) — donc « zéro » vs « non-nul » sous
« quel niveau d'alcool minimise le risque ? » deviennent candidats.

Usage : docker compose exec app python scripts/keypoint_mine_contradictions.py --tenant alcohol_health
"""
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from itertools import combinations

from neo4j import GraphDatabase

OPPOSE = {frozenset({"increases", "decreases"}), frozenset({"affirms", "denies"})}
MAX_PAIRS_PER_KP = 30


def driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")),
    )


def opposing(a, b) -> bool:
    if (a.get("doc") or "") == (b.get("doc") or ""):
        return False  # contradictions = cross-doc
    sa, sb = a.get("stance") or "none", b.get("stance") or "none"
    if frozenset({sa, sb}) in OPPOSE:
        return True
    # même question, réponse « equals » des deux côtés mais valeurs différentes
    aa, ab = (a.get("answer") or "").strip().lower(), (b.get("answer") or "").strip().lower()
    if sa == "equals" and sb == "equals" and aa and ab and aa != ab:
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="alcohol_health")
    ap.add_argument("--no-adjudicate", action="store_true", help="créer les arêtes sans lancer l'adjudicateur")
    args = ap.parse_args()
    drv = driver()

    # KeyPoints multi-doc avec ≥2 claims
    with drv.session() as s:
        rows = [dict(r) for r in s.run(
            """MATCH (k:KeyPoint {tenant_id:$tid})<-[:ANSWERS_KEYPOINT]-(c:Claim)
               WITH k, c
               RETURN k.kp_id AS kp, k.question AS q, c.claim_id AS id,
                      c.kp_stance AS stance, c.kp_answer AS answer, split(c.doc_id,'_')[0] AS doc""",
            tid=args.tenant)]
    by_kp = defaultdict(list)
    for r in rows:
        by_kp[(r["kp"], r["q"])].append(r)

    candidates = []
    for (kp, q), members in by_kp.items():
        docs = {m["doc"] for m in members}
        if len(docs) < 2:
            continue
        pairs = []
        for a, b in combinations(members, 2):
            if opposing(a, b):
                pairs.append((a, b))
            if len(pairs) >= MAX_PAIRS_PER_KP:
                break
        for a, b in pairs:
            candidates.append((a["id"], b["id"], kp, q))

    print(f"[KP-Mine] {len(by_kp)} KeyPoints, {len(candidates)} paires candidates (stance opposée, cross-doc)", flush=True)

    # Créer les arêtes CONTRADICTS (adjudication NULL → reprises par l'adjudicateur)
    created = 0
    with drv.session() as s:
        for a_id, b_id, kp, q in candidates:
            res = s.run(
                """MATCH (a:Claim {claim_id:$a, tenant_id:$t}), (b:Claim {claim_id:$b, tenant_id:$t})
                   MERGE (a)-[r:CONTRADICTS]->(b)
                   ON CREATE SET r.method='keypoint_mined', r.marker_type='keypoint',
                       r.basis=$q, r.keypoint_id=$kp, r.detected_at=datetime(),
                       r.valid_from_relation=datetime(), r.confidence=0.6
                   RETURN CASE WHEN r.adjudication IS NULL THEN 1 ELSE 0 END AS fresh""",
                a=a_id, b=b_id, t=args.tenant, q=q, kp=kp)
            created += res.single()["fresh"]
    print(f"[KP-Mine] {created} arêtes CONTRADICTS à adjudiquer (non encore jugées)", flush=True)

    if args.no_adjudicate:
        drv.close()
        return

    # Déléguer à l'adjudicateur existant (passages + vote anti-variance)
    from knowbase.relations.contradiction_adjudicator import ContradictionAdjudicator
    adj = ContradictionAdjudicator()
    summary = adj.run(tenant_id=args.tenant, force=False)
    try:
        print(f"[KP-Mine] Adjudication terminée : {summary.by_verdict}", flush=True)
    except Exception:
        print(f"[KP-Mine] Adjudication terminée : {summary}", flush=True)
    drv.close()


if __name__ == "__main__":
    main()
