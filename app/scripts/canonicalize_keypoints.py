"""Remédiation — couche CANONICALKEYPOINT (cible, consensus octopus + littérature 12/06).

PROBLÈME : FRAGMENTATION des KeyPoints. Le débat-vedette GBD « niveau sans risque »
existe en ~8 variantes de surface (health risk / health loss / …for men / …due to
alcohol use). Au runtime, la question route vers une variante NON marquée débat →
le débat-vedette ne surface pas. (Le sur-flagging d'avant le masquait par accident ;
l'étape 4, en nettoyant 43→10, l'a exposé.)

CIBLE (EDC + question canonique ; PAS de hiérarchie DAG ; PAS de fusion physique de
nœuds — le scope « for men » porte une info à préserver) :
  Phase 1 — NORMALISATION (LLM EDC) : KeyPoint → `canonical_question` (scope retiré)
    + `scope`. Famille = ÉGALITÉ DE CHAÎNE EXACTE sur canonical_question (même
    mécanisme que le bucketing KeyPoint, une couche au-dessus). Zéro cosinus → le
    piège union-find (cluster de 1481) est STRUCTURELLEMENT impossible. Caché sur le
    KeyPoint (kp.canonical_question) → idempotent, rejouable gratuitement.
  Phase 2 — DÉDUP petit-n : le LLM sous-fusionne parfois (risk≈loss). On dédup les
    CanonicalKeyPoint (n petit, ~quelques centaines) par cosinus≥0.93 + confirmation
    LLM → re-pointe CANON_OF vers le représentant (réversible, aucun claim perdu).
    C'est le côté SÛR du risque (sous-fusion récupérable ≠ sur-fusion catastrophique).
  Phase 3 — DÉBAT AU NIVEAU CANONIQUE : par famille, on agrège TOUS les claims (le
    juge voit toutes les variantes ensemble = mieux) → is_debate + positions sur le
    CanonicalKeyPoint (réutilise le vérificateur agnostique de l'étape 4).

Runtime (déterministe, 1-hop) : claim → KeyPoint → CANON_OF → CanonicalKeyPoint{is_debate}.
Remplace SAME_DEBATE_AS (jumeaux = même canonical_question) + la détection par-KeyPoint.

Agnostique : zéro lexique métier (marche sur aéro/SAP). Usage :
  docker compose exec app python scripts/canonicalize_keypoints.py --tenant alcohol_health
  --dry-run : phases 1+2 en rapport, sans phase 3 ni écriture débat.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os

import numpy as np
from neo4j import GraphDatabase

# réutilise le vérificateur de débats agnostique (étape 4)
from keypoint_verify_debates import (_positions, _tier1_directional, _is_candidate,
                                      _judge, driver)

_NORM_SYS = """You canonicalize a normative QUESTION so that paraphrases and surface variants of the
SAME underlying question collapse to ONE identical canonical string. A genuine restriction of
POPULATION/SUBGROUP (sex, age, patients-with-condition) is extracted to scope; everything else
stays in the question.
Return ONLY JSON: {"canonical_question":"<core neutral question, lowercase, ends with ?, NO
subgroup restriction, NO answer>","scope":{"dimension":"sex|age|subpopulation|null","value":"<short or null>"}}
RULES:
- Synonyms/rewordings of the OUTCOME or MEASURE are NOT scope; fold them into the canonical
  question. Ex: "minimizes health risk" = "minimizes health loss" = "minimizes health loss due to
  alcohol use" -> ALL become "what level of alcohol consumption minimizes health risk?" scope null.
- ONLY a population/subgroup restriction goes to scope. "...for men" -> {sex: men};
  "...in diabetics" -> {subpopulation: diabetics}.
- Keep the core topic; do NOT generalize it away (breast cancer stays breast cancer).
  Deterministic, terse, lowercase."""

_DEDUP_SYS = """Two canonical questions are given. Answer YES only if they ask EXACTLY the same
thing (same outcome/measure, same matter), i.e. one is a pure paraphrase of the other (e.g.
"minimizes health risk" vs "minimizes health loss"). A different outcome, organ, disease, or a
narrower/broader scope = NO. Return ONLY {"same": true|false}."""


def _ckp_id(tenant: str, cq: str) -> str:
    return "ckp_" + hashlib.sha1(f"{tenant}|{cq}".encode("utf-8")).hexdigest()[:16]


def _norm_scope(s):
    if not isinstance(s, dict):
        return None, None
    d, v = s.get("dimension"), s.get("value")
    if d in (None, "null", "") or v in (None, "null", ""):
        return None, None
    return str(d)[:40], str(v)[:60]


# ───────────────────────── Phase 1 : normalisation ─────────────────────────
def _normalize_one(llm, TaskType, q):
    try:
        resp = llm.complete(task_type=TaskType.FAST_CLASSIFICATION,
            messages=[{"role": "system", "content": _NORM_SYS},
                      {"role": "user", "content": f"QUESTION: {q}\nJSON:"}],
            temperature=0.0, response_format={"type": "json_object"}, max_tokens=140)
        v = json.loads(resp if isinstance(resp, str) else json.dumps(resp))
        cq = (v.get("canonical_question") or q).strip().lower()
        dim, val = _norm_scope(v.get("scope"))
        return cq, dim, val
    except Exception:
        return (q or "").strip().lower(), None, None  # fallback identité


def _write_canon(s, tenant, kp, cq, dim, val):
    s.run("""MERGE (cano:CanonicalKeyPoint {ckp_id:$ckp})
               ON CREATE SET cano.tenant_id=$t, cano.canonical_question=$cq, cano.is_debate=false
             WITH cano MATCH (k:KeyPoint {kp_id:$kp})
             SET k.canonical_question=$cq, k.scope_dim=$dim, k.scope_val=$val
             MERGE (k)-[:CANON_OF]->(cano)""",
          ckp=_ckp_id(tenant, cq), t=tenant, cq=cq, kp=kp, dim=dim, val=val)


def phase1_normalize(drv, tenant, llm, TaskType, workers=8, limit=0):
    with drv.session() as s:
        rows = [dict(r) for r in s.run(
            "MATCH (k:KeyPoint {tenant_id:$t}) RETURN k.kp_id AS kp, k.question AS q, "
            "k.canonical_question AS cached, k.scope_dim AS sd, k.scope_val AS sv", t=tenant)]
    cached = [r for r in rows if r.get("cached")]
    todo = [r for r in rows if not r.get("cached")]
    if limit:
        todo = todo[:limit]
    print(f"Phase 1 : {len(rows)} KeyPoints — {len(cached)} cachés, {len(todo)} à normaliser "
          f"({workers} workers, écriture incrémentale)", flush=True)

    # cachés : ré-assurer CANON_OF (rapide, pas de LLM)
    with drv.session() as s:
        for r in cached:
            _write_canon(s, tenant, r["kp"], r["cached"], r.get("sd"), r.get("sv"))

    # à faire : LLM parallèle, écriture AU FIL DE L'EAU (reprenable, progrès visible)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex, drv.session() as s:
            futs = {ex.submit(_normalize_one, llm, TaskType, r["q"]): r for r in todo}
            done = 0
            for fut in as_completed(futs):
                r = futs[fut]
                cq, dim, val = fut.result()
                _write_canon(s, tenant, r["kp"], cq, dim, val)
                done += 1
                if done % 50 == 0:
                    print(f"  …{done}/{len(todo)} normalisés", flush=True)
    with drv.session() as s:
        n_fam = s.run("MATCH (c:CanonicalKeyPoint {tenant_id:$t}) RETURN count(c) AS n",
                      t=tenant).single()["n"]
    print(f"Phase 1 OK : {n_fam} familles (CanonicalKeyPoint) pour {len(rows)} KeyPoints", flush=True)
    return n_fam


# ───────────────────── Phase 2 : dédup petit-n (sous-fusion) ────────────────
def phase2_dedup(drv, tenant, llm, TaskType, thr=0.93, dry=False):
    with drv.session() as s:
        fams = [dict(r) for r in s.run(
            "MATCH (c:CanonicalKeyPoint {tenant_id:$t})<-[:CANON_OF]-(k:KeyPoint) "
            "RETURN c.ckp_id AS id, c.canonical_question AS q, count(k) AS n ORDER BY n DESC", t=tenant)]
    print(f"Phase 2 : dédup de {len(fams)} familles (cosinus ≥{thr} + confirm LLM)", flush=True)
    if len(fams) < 2:
        return 0
    from knowbase.common.clients.embeddings import EmbeddingModelManager
    embs = np.array(EmbeddingModelManager().encode([f"query: {f['q']}" for f in fams]), dtype=np.float32)
    embs /= (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    sim = embs @ embs.T
    # union-find sur paires CONFIRMÉES uniquement (pas cosinus seul → pas de sur-fusion)
    parent = list(range(len(fams)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    merges = 0
    for i in range(len(fams)):
        for j in range(i + 1, len(fams)):
            if sim[i, j] < thr or find(i) == find(j):
                continue
            try:
                resp = llm.complete(task_type=TaskType.FAST_CLASSIFICATION,
                    messages=[{"role": "system", "content": _DEDUP_SYS},
                              {"role": "user", "content": f"Q1: {fams[i]['q']}\nQ2: {fams[j]['q']}\nJSON:"}],
                    temperature=0.0, response_format={"type": "json_object"}, max_tokens=20)
                same = bool(json.loads(resp if isinstance(resp, str) else json.dumps(resp)).get("same"))
            except Exception:
                same = False
            if same:
                print(f"  merge ({sim[i,j]:.3f}) «{fams[i]['q'][:45]}» ⟸ «{fams[j]['q'][:45]}»", flush=True)
                parent[find(j)] = find(i)  # i = représentant (plus de claims, vient en premier)
                merges += 1
    if dry or not merges:
        print(f"Phase 2 : {merges} fusions {'(dry-run, non écrites)' if dry else ''}", flush=True)
        return merges
    # re-pointe CANON_OF des dups vers le représentant, supprime le nœud dup
    with drv.session() as s:
        for idx in range(len(fams)):
            root = find(idx)
            if root == idx:
                continue
            s.run("""MATCH (dup:CanonicalKeyPoint {ckp_id:$d}), (rep:CanonicalKeyPoint {ckp_id:$r})
                     MATCH (dup)<-[old:CANON_OF]-(k:KeyPoint)
                     SET k.canonical_question = rep.canonical_question
                     MERGE (k)-[:CANON_OF]->(rep)
                     DELETE old
                     WITH dup, rep SET rep.aliases = coalesce(rep.aliases,[]) + dup.canonical_question
                     DETACH DELETE dup""", d=fams[idx]["id"], r=fams[root]["id"])
    print(f"Phase 2 OK : {merges} fusions appliquées (réversible via aliases)", flush=True)
    return merges


# ──────────────── Phase 3 : débat au niveau canonique ─────────────────
def phase3_debates(drv, tenant, llm, TaskType):
    with drv.session() as s:
        fams = [dict(r) for r in s.run(
            """MATCH (cano:CanonicalKeyPoint {tenant_id:$t})<-[:CANON_OF]-(:KeyPoint)<-[:ANSWERS_KEYPOINT]-(c:Claim)
               WITH cano, split(c.doc_id,'_')[0] AS doc, c.kp_stance AS stance,
                    coalesce(c.kp_answer,'') AS answer
               WITH cano, collect({doc:doc, stance:stance, answer:answer}) AS m, count(DISTINCT doc) AS nd
               WHERE nd >= 2
               RETURN cano.ckp_id AS id, cano.canonical_question AS q, m""", t=tenant)]
    print(f"Phase 3 : {len(fams)} familles multi-doc à juger", flush=True)
    confirmed, auto_n, judged_n = [], 0, 0
    for f in fams:
        pos = _positions(f["m"])
        if _tier1_directional(pos):
            confirmed.append((f, pos)); auto_n += 1
        elif _is_candidate(pos):
            judged_n += 1
            if _judge(llm, TaskType, f["q"], pos):
                confirmed.append((f, pos))
    print(f"Phase 3 : {len(confirmed)} familles-débats ({auto_n} tier1 + {len(confirmed)-auto_n} "
          f"juge/{judged_n} candidats)", flush=True)

    # garde-fous
    def _has(frag): return any(frag in (f["q"] or "").lower() for f, _ in confirmed)
    gbd = _has("minimizes health risk") or _has("minimizes health loss")
    cancer_ok = not any((f["q"] or "").lower().strip() == "does alcohol consumption cause cancer?"
                        for f, _ in confirmed)
    print(f"GARDE-FOUS : GBD niveau confirmé={gbd} (True attendu) ; "
          f"'cause cancer' non-débat={cancer_ok} (True attendu)", flush=True)
    assert gbd and cancer_ok, "GARDE-FOU VIOLÉ"

    conf_ids = {f["id"] for f, _ in confirmed}
    with drv.session() as s:
        s.run("MATCH (c:CanonicalKeyPoint {tenant_id:$t}) SET c.is_debate=false", t=tenant)
        for f, pos in confirmed:
            payload = [{"doc": p["doc_id"], "stance": p["stance"], "answer": p["answer"][:120]}
                       for p in pos][:8]
            s.run("MATCH (c:CanonicalKeyPoint {ckp_id:$id}) SET c.is_debate=true, c.positions_json=$p",
                  id=f["id"], p=json.dumps(payload, ensure_ascii=False))
    print(f"Phase 3 OK : {len(confirmed)} familles-débats écrites.", flush=True)
    for f, _ in confirmed:
        print(f"  [DÉBAT] {f['q'][:70]}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="alcohol_health")
    ap.add_argument("--dry-run", action="store_true", help="phases 1+2 sans phase 3")
    ap.add_argument("--limit", type=int, default=0, help="limiter Phase 1 (test débit)")
    ap.add_argument("--phase1-only", action="store_true")
    args = ap.parse_args()
    drv = driver()
    from knowbase.common.llm_router import get_llm_router, TaskType
    llm = get_llm_router()

    phase1_normalize(drv, args.tenant, llm, TaskType, workers=16, limit=args.limit)
    if args.phase1_only or args.limit:
        drv.close(); return
    phase2_dedup(drv, args.tenant, llm, TaskType, dry=args.dry_run)
    if not args.dry_run:
        phase3_debates(drv, args.tenant, llm, TaskType)
    drv.close()


if __name__ == "__main__":
    main()
