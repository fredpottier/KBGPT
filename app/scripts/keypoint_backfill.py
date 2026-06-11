"""Backfill de la couche KeyPoint sur un tenant existant + construction des nœuds.

Pour chaque claim porteur de sens, calcule via LLM (burst) la `normative_question`
neutre qu'il adresse (+ stance + answer + predicate/object), puis :
  - écrit ces champs sur le :Claim,
  - crée/relie des nœuds :KeyPoint (bucket EXACT sur la question normalisée),
    via une relation réversible (:Claim)-[:ANSWERS_KEYPOINT]->(:KeyPoint).

Idempotent (skip claims déjà traités sauf --force), concurrent, resumable.

Usage (dans le conteneur app) :
  docker compose exec app python scripts/keypoint_backfill.py --tenant alcohol_health
  options : --limit N  --force  --workers 10  --priority-docs GBD2018,GBD2020,Ronksley,Biddinger,...
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from neo4j import GraphDatabase

from knowbase.claimfirst.keypoints.extractor import KeyPointExtractor, normalize_question

PRIORITY_DEFAULT = "GBD2018,GBD2020,Ronksley,Biddinger,Holmes,MVP,Stockwell,Zhao,CCSA,2022_alcohol-atrial,2024_alcohol-hypertension"


def driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")),
    )


def load_claims(drv, tenant, force, limit, priority):
    where_done = "" if force else "AND c.normative_question IS NULL"
    q = f"""
    MATCH (c:Claim {{tenant_id:$tid}})
    WHERE c.text IS NOT NULL {where_done}
    RETURN c.claim_id AS id, c.text AS text, c.subject_canonical AS subject,
           c.predicate AS predicate, c.object_canonical AS object,
           c.passage_text AS passage, c.doc_id AS doc_id
    """
    with drv.session() as s:
        rows = [dict(r) for r in s.run(q, tid=tenant)]
    # tri : docs prioritaires d'abord (pour valider la paire GBD tôt)
    pri = [p.strip() for p in priority.split(",") if p.strip()]

    def rank(doc_id):
        doc_id = doc_id or ""
        for i, p in enumerate(pri):
            if doc_id.startswith(p) or p in doc_id:
                return i
        return len(pri) + 1

    rows.sort(key=lambda r: rank(r["doc_id"]))
    if limit:
        rows = rows[:limit]
    return rows


def persist_claim(drv, cid, sig):
    with drv.session() as s:
        s.run(
            """
            MATCH (c:Claim {claim_id:$id})
            SET c.normative_question = $q,
                c.kp_stance = $stance,
                c.kp_answer = $answer,
                c.kp_confidence = $conf,
                c.predicate = CASE WHEN (c.predicate IS NULL OR c.predicate='') AND $pred<>'' THEN $pred ELSE c.predicate END,
                c.object_canonical = CASE WHEN (c.object_canonical IS NULL OR c.object_canonical='') AND $obj<>'' THEN $obj ELSE c.object_canonical END,
                c.keypoint_backfilled_at = datetime()
            """,
            id=cid, q=sig.normative_question, stance=sig.stance, answer=sig.answer,
            conf=sig.confidence, pred=sig.predicate or "", obj=sig.object or "",
        )


def build_keypoints(drv, tenant):
    """Crée les :KeyPoint à partir des normative_question (bucket exact) + liens."""
    with drv.session() as s:
        # nettoyer les liens KeyPoint existants pour ce tenant (rebuild propre)
        s.run("MATCH (k:KeyPoint {tenant_id:$tid}) DETACH DELETE k", tid=tenant)
        # créer les KeyPoint + relier les claims
        res = s.run(
            """
            MATCH (c:Claim {tenant_id:$tid})
            WHERE c.normative_question IS NOT NULL AND c.normative_question <> ''
              AND coalesce(c.kp_confidence,0) >= 0.55
            WITH c.normative_question AS q, collect(c) AS claims
            WITH q, claims, [x IN claims | split(x.doc_id,'_')[0]] AS docs
            CREATE (k:KeyPoint {
                tenant_id:$tid,
                kp_id: 'kp_'+apoc.util.md5([$tid,q]),
                question: q,
                claim_count: size(claims),
                doc_count: size(apoc.coll.toSet(docs)),
                stances: apoc.coll.toSet([x IN claims | x.kp_stance]),
                created_at: datetime()
            })
            WITH k, claims
            UNWIND claims AS c
            MERGE (c)-[:ANSWERS_KEYPOINT]->(k)
            RETURN count(DISTINCT k) AS n_kp
            """,
            tid=tenant,
        )
        n = res.single()["n_kp"]
    return n


def build_keypoints_no_apoc(drv, tenant):
    """Fallback sans APOC (md5/toSet) — fait le groupement côté Python."""
    with drv.session() as s:
        s.run("MATCH (k:KeyPoint {tenant_id:$tid}) DETACH DELETE k", tid=tenant)
        rows = [dict(r) for r in s.run(
            """MATCH (c:Claim {tenant_id:$tid})
               WHERE c.normative_question IS NOT NULL AND c.normative_question<>''
                 AND coalesce(c.kp_confidence,0) >= 0.55
               RETURN c.claim_id AS id, c.normative_question AS q,
                      c.kp_stance AS stance, split(c.doc_id,'_')[0] AS doc""",
            tid=tenant)]
    import hashlib
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[r["q"]].append(r)
    with drv.session() as s:
        for q, members in groups.items():
            kp_id = "kp_" + hashlib.md5(f"{tenant}|{q}".encode()).hexdigest()[:16]
            docs = sorted({m["doc"] for m in members})
            stances = sorted({m["stance"] for m in members if m["stance"]})
            s.run(
                """CREATE (k:KeyPoint {tenant_id:$tid, kp_id:$kid, question:$q,
                     claim_count:$cc, doc_count:$dc, stances:$st, created_at:datetime()})""",
                tid=tenant, kid=kp_id, q=q, cc=len(members), dc=len(docs), st=stances,
            )
            s.run(
                """UNWIND $ids AS cid
                   MATCH (c:Claim {claim_id:cid}), (k:KeyPoint {kp_id:$kid})
                   MERGE (c)-[:ANSWERS_KEYPOINT]->(k)""",
                ids=[m["id"] for m in members], kid=kp_id,
            )
    return len(groups)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="alcohol_health")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--priority-docs", default=PRIORITY_DEFAULT)
    ap.add_argument("--skip-extract", action="store_true", help="seulement (re)construire les KeyPoint")
    args = ap.parse_args()

    drv = driver()
    if not args.skip_extract:
        rows = load_claims(drv, args.tenant, args.force, args.limit, args.priority_docs)
        print(f"[KeyPoint] {len(rows)} claims à traiter (tenant={args.tenant})", flush=True)
        ex = KeyPointExtractor()
        done = ok = 0
        t0 = time.time()

        def work(r):
            sig = ex.extract(
                claim_text=r["text"], subject=r.get("subject"), predicate=r.get("predicate"),
                obj=r.get("object"), passage=r.get("passage"), tenant_id=args.tenant,
            )
            return r["id"], sig

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(work, r) for r in rows]
            for f in as_completed(futs):
                cid, sig = f.result()
                done += 1
                if sig is not None:
                    persist_claim(drv, cid, sig)
                    if sig.normative_question:
                        ok += 1
                if done % 50 == 0:
                    rate = done / max(1e-9, time.time() - t0)
                    print(f"  {done}/{len(rows)} traités, {ok} avec question "
                          f"({rate:.1f}/s, ETA {(len(rows)-done)/max(rate,1e-9)/60:.0f}min)", flush=True)
        print(f"[KeyPoint] extraction terminée : {ok}/{len(rows)} avec normative_question", flush=True)

    # Construire les KeyPoint
    try:
        n = build_keypoints(drv, args.tenant)
        print(f"[KeyPoint] {n} KeyPoint créés (APOC)", flush=True)
    except Exception as e:
        print(f"[KeyPoint] APOC indispo ({e}) → fallback Python", flush=True)
        n = build_keypoints_no_apoc(drv, args.tenant)
        print(f"[KeyPoint] {n} KeyPoint créés (fallback)", flush=True)
    drv.close()


if __name__ == "__main__":
    main()
