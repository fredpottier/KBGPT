"""Remédiation étape 3 (REMPLACÉE) — LIER les débats jumeaux au lieu de fusionner.

Consensus (données + octopus 12/06) : la fusion de KeyPoints est NO-GO (union-find
collapse des débats distincts ; le cosinus ne sépare pas « même question » de
« question sœur »). À la place : arête RÉVERSIBLE `SAME_DEBATE_AS` entre débats
vraiment jumeaux (ex « minimizes health risk » / « minimizes health loss »),
candidats par cosinus ≥0.97 PAIRWISE (pas de transitivité), chaque paire
CONFIRMÉE par LLM (même dose/sexe/périmètre ?). Edge-only : zéro suppression de
nœud, zéro re-parentage de claim. L'affichage (appendice/Atlas) unit les jumeaux.

Garde-fous (vérifiés en fin) : is_debate inchangé, aucun nœud KeyPoint supprimé.

Usage : docker compose exec app python scripts/keypoint_link_debates.py --tenant alcohol_health
        --dry-run pour voir les candidats sans écrire.
"""
from __future__ import annotations
import argparse, json, os
import numpy as np
from neo4j import GraphDatabase

_SYS = """You decide if two normalized questions ask EXACTLY THE SAME thing — same
outcome, same population (age/sex), same dose/exposure, same scope. Twins like
"what level minimizes health risk?" / "what level minimizes health loss?" = SAME.
Siblings differing by dose ("2 drinks" vs "7 drinks"), sex (male vs female),
exposure (current vs lifetime smoking), or outcome (breast cancer vs cardiovascular)
= NOT same. Return ONLY {"same": true|false}."""


def driver():
    return GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="alcohol_health")
    ap.add_argument("--thr", type=float, default=0.97)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    drv = driver()

    with drv.session() as s:
        deb = [dict(r) for r in s.run(
            "MATCH (k:KeyPoint {tenant_id:$t, is_debate:true}) "
            "RETURN k.kp_id AS id, k.question AS q, coalesce(k.claim_count,0) AS n", t=args.tenant)]
        n_debate_before = len(deb)
        n_kp_before = s.run("MATCH (k:KeyPoint {tenant_id:$t}) RETURN count(k) AS n", t=args.tenant).single()["n"]
    print(f"{n_debate_before} débats, {n_kp_before} KeyPoints au total", flush=True)
    if len(deb) < 2:
        return

    from knowbase.common.clients.embeddings import EmbeddingModelManager
    embs = np.array(EmbeddingModelManager().encode([f"query: {d['q']}" for d in deb]), dtype=np.float32)
    embs /= (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    sim = embs @ embs.T

    # candidats PAIRWISE >= seuil (pas de transitivité)
    cands = [(i, j, float(sim[i, j])) for i in range(len(deb)) for j in range(i + 1, len(deb)) if sim[i, j] >= args.thr]
    print(f"{len(cands)} paires candidates (cosinus >= {args.thr}, pairwise) :", flush=True)
    for i, j, sc in cands:
        print(f"  {sc:.3f}  «{deb[i]['q'][:55]}»  ⟷  «{deb[j]['q'][:55]}»", flush=True)
    if not cands:
        print("Aucun jumeau de débat à lier.", flush=True)
        return

    # LLM-confirm chaque paire
    from knowbase.common.llm_router import get_llm_router, TaskType
    llm = get_llm_router()
    confirmed = []
    for i, j, sc in cands:
        try:
            resp = llm.complete(task_type=TaskType.FAST_CLASSIFICATION,
                messages=[{"role": "system", "content": _SYS},
                          {"role": "user", "content": f"Q1: {deb[i]['q']}\nQ2: {deb[j]['q']}\nJSON:"}],
                temperature=0.0, response_format={"type": "json_object"})
            same = bool(json.loads(resp if isinstance(resp, str) else json.dumps(resp)).get("same"))
        except Exception as e:
            print(f"  confirm err ({e}) → skip", flush=True); same = False
        print(f"  LLM same={same} : «{deb[i]['q'][:45]}» ⟷ «{deb[j]['q'][:45]}»", flush=True)
        if same:
            confirmed.append((deb[i]['id'], deb[j]['id'], sc))

    if args.dry_run:
        print(f"[dry-run] {len(confirmed)} liens confirmés, non écrits.", flush=True); return

    with drv.session() as s:
        for a, b, sc in confirmed:
            s.run("""MATCH (x:KeyPoint {kp_id:$a}), (y:KeyPoint {kp_id:$b})
                     MERGE (x)-[r:SAME_DEBATE_AS]-(y)
                     SET r.sim=$sc, r.confirmed_by='llm', r.created_at=datetime()""", a=a, b=b, sc=sc)
        # garde-fous
        n_debate_after = s.run("MATCH (k:KeyPoint {tenant_id:$t, is_debate:true}) RETURN count(k) AS n", t=args.tenant).single()["n"]
        n_kp_after = s.run("MATCH (k:KeyPoint {tenant_id:$t}) RETURN count(k) AS n", t=args.tenant).single()["n"]
        n_links = s.run("MATCH (:KeyPoint {tenant_id:$t})-[r:SAME_DEBATE_AS]-(:KeyPoint) RETURN count(r)/2 AS n", t=args.tenant).single()["n"]
    print(f"[OK] {len(confirmed)} liens SAME_DEBATE_AS écrits ({n_links} arêtes).", flush=True)
    print(f"GARDE-FOUS : is_debate {n_debate_before}->{n_debate_after} (doit être égal), "
          f"KeyPoints {n_kp_before}->{n_kp_after} (doit être égal).", flush=True)
    assert n_debate_after == n_debate_before and n_kp_after == n_kp_before, "GARDE-FOU VIOLÉ"
    drv.close()


if __name__ == "__main__":
    main()
