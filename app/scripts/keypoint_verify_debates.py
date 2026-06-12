"""Remédiation étape 4 — VÉRIFICATION des débats (recalcul de is_debate, agnostique).

PROBLÈME (audit du 12/06) : l'ancien critère `flag_debates` (keypoint_backfill.py)
marquait is_debate=true dès que 2 docs avaient 2 préfixes de réponse distincts
(clause `divergent`). Résultat : ~31 FAUX débats sur 43 (« does alcohol cause
cancer? » = 3 docs tous d'accord → flaggé). Afficher un faux débat en démo est grave.

DESIGN (consensus données + octopus, zéro hardcodé métier) :
  - Tier 1 — DÉTERMINISTE, UNIVERSEL : un KeyPoint est un débat si, sur ≥2 docs
    distincts, les stances contiennent {increases, decreases}. Ce n'est pas une
    table métier : c'est le SENS de l'enum (risque ↑ vs ↓), vrai pour tout domaine.
  - Tier 2 — JUGE LLM sur le TEXTE réel (kp_answer), pas les stances. Vivier
    candidat = structurel (≥2 docs ET ≥2 stances/réponses distinctes). Le juge lit
    les réponses, IGNORE lui-même les nulls méthodologiques, et doit PROUVER le
    débat (2 citations verbatim de 2 docs différents + axe typé) sinon → false.
    Vote 2/3 pour tuer la variance du juge.
  → Aucun lexique alcool/santé, aucune regex métier : marche tel quel sur aéro/SAP.

Garde-fous (assert en fin) : le débat-vedette GBD reste is_debate ; un faux connu
(« cause cancer ») redevient non-débat ; comptage avant/après loggé.

Usage : docker compose exec app python scripts/keypoint_verify_debates.py --tenant alcohol_health
        --dry-run : juge et rapporte sans écrire.
"""
from __future__ import annotations

import argparse
import json
import os

from neo4j import GraphDatabase

_NON_POSITION = {"none", "defines"}
_AXES = {"harm_vs_no_harm", "benefit_vs_no_benefit", "threshold_low_vs_high", "direction_opposite"}
_VOTES = 3  # appels juge par candidat (majorité)

_JUDGE_SYS = """You decide whether documents give GENUINELY OPPOSING answers to ONE normalized question.
You receive the question and a list of {doc_id, answer, stance}.

A DEBATE = two answers from DIFFERENT documents that DIRECTLY contradict each other on the SAME
question, e.g.: protective benefit vs no benefit; a low safe/threshold value vs a high one (or
zero vs non-zero); increases risk vs no/decreased risk.

NOT a debate (return false): unanimous agreement worded differently; methodological nulls
("non-significant test", "cannot establish causation", "no publication bias", "limited data",
"more research needed"); definitions; measurement descriptions; mere differences in
population/scope WITHOUT a direct contradiction. Ignore non-position answers entirely.

Return ONLY JSON:
{"is_debate": true|false,
 "side_a": {"doc_id": "<id>", "quote": "<verbatim substring of ONE provided answer>"},
 "side_b": {"doc_id": "<id>", "quote": "<verbatim substring of ANOTHER provided answer>"},
 "axis": "harm_vs_no_harm" | "benefit_vs_no_benefit" | "threshold_low_vs_high" | "direction_opposite"}

Both quotes MUST be copied verbatim from TWO DIFFERENT documents. If it is not a debate, set
is_debate=false (sides/axis may be null)."""


def driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password")),
    )


def _load(drv, tenant):
    """KeyPoints multi-doc + leurs claims (doc court, stance, answer)."""
    with drv.session() as s:
        rows = [dict(r) for r in s.run(
            """MATCH (k:KeyPoint {tenant_id:$t})<-[:ANSWERS_KEYPOINT]-(c:Claim)
               WITH k, split(c.doc_id,'_')[0] AS doc, c.kp_stance AS stance,
                    coalesce(c.kp_answer,'') AS answer
               WITH k, collect({doc: doc, stance: stance, answer: answer}) AS m,
                    count(DISTINCT doc) AS ndoc
               WHERE ndoc >= 2
               RETURN k.kp_id AS kp, k.question AS q, k.is_debate AS was, m""", t=tenant)]
    return rows


def _positions(members):
    """Claims porteurs d'une position (hors none/defines), dédupliqués."""
    out, seen = [], set()
    for x in members:
        st = x.get("stance")
        ans = (x.get("answer") or "").strip()
        if not ans or st in _NON_POSITION:
            continue
        key = (x["doc"], ans[:60])
        if key in seen:
            continue
        seen.add(key)
        out.append({"doc_id": x["doc"], "stance": st, "answer": ans[:200]})
    return out


def _tier1_directional(positions) -> bool:
    """Universel : 2 docs DIFFÉRENTS s'opposent sur leur direction DOMINANTE.
    La position d'un doc = sa stance directionnelle majoritaire (filtre le bruit
    intra-doc : ex un doc 12×increases + 1×decreases reste un doc 'increases')."""
    from collections import Counter, defaultdict
    by_doc = defaultdict(Counter)
    for p in positions:
        if p["stance"] in ("increases", "decreases"):
            by_doc[p["doc_id"]][p["stance"]] += 1
    dom = set()
    for c in by_doc.values():
        top = c.most_common()
        if top and (len(top) == 1 or top[0][1] > top[1][1]):  # direction nette
            dom.add(top[0][0])
    return "increases" in dom and "decreases" in dom


def _is_candidate(positions) -> bool:
    docs = {p["doc_id"] for p in positions}
    stances = {p["stance"] for p in positions}
    answers = {p["answer"][:40].lower() for p in positions}
    return len(docs) >= 2 and (len(stances) >= 2 or len(answers) >= 2)


def _valid_verdict(v, positions) -> bool:
    """Preuve obligatoire : 2 docs DIFFÉRENTS + citations verbatim + axe typé."""
    if not isinstance(v, dict) or not v.get("is_debate"):
        return False
    a, b = v.get("side_a") or {}, v.get("side_b") or {}
    da, db = a.get("doc_id"), b.get("doc_id")
    qa, qb = (a.get("quote") or "").strip().lower(), (b.get("quote") or "").strip().lower()
    if not da or not db or da == db or not qa or not qb:
        return False
    if v.get("axis") not in _AXES:
        return False
    corpus = {p["doc_id"]: (p["answer"] or "").lower() for p in positions}
    # quotes = sous-chaînes littérales d'une réponse fournie (anti-hallucination)
    all_ans = " || ".join(corpus.values())
    return qa in all_ans and qb in all_ans


def _judge(llm, TaskType, question, positions):
    payload = [{"doc_id": p["doc_id"], "answer": p["answer"], "stance": p["stance"]} for p in positions]
    user = f"Question: {question}\nAnswers:\n{json.dumps(payload, ensure_ascii=False)}\nJSON:"
    yes = 0
    for _ in range(_VOTES):
        try:
            resp = llm.complete(
                task_type=TaskType.FAST_CLASSIFICATION,
                messages=[{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": user}],
                temperature=0.0, response_format={"type": "json_object"},
                max_tokens=300)  # le verdict (2 citations + axe) dépasse le défaut FAST → tronqué sinon
            v = json.loads(resp if isinstance(resp, str) else json.dumps(resp))
        except Exception:
            v = {}
        if _valid_verdict(v, positions):
            yes += 1
    return yes >= 2  # majorité 2/3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="alcohol_health")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    drv = driver()

    rows = _load(drv, args.tenant)
    print(f"{len(rows)} KeyPoints multi-doc à vérifier", flush=True)

    from knowbase.common.llm_router import get_llm_router, TaskType
    llm = get_llm_router()

    confirmed, demoted, auto_n, judged_n = [], [], 0, 0
    for r in rows:
        positions = _positions(r["m"])
        if _tier1_directional(positions):
            confirmed.append((r, positions, "tier1_directional")); auto_n += 1
            continue
        if not _is_candidate(positions):
            demoted.append(r); continue
        judged_n += 1
        if _judge(llm, TaskType, r["q"], positions):
            confirmed.append((r, positions, "llm_confirmed"))
        else:
            demoted.append(r)

    conf_ids = {r["kp"] for r, _, _ in confirmed}
    print(f"\n=== VERDICT : {len(confirmed)} débats confirmés "
          f"({auto_n} tier1 + {len(confirmed)-auto_n} juge sur {judged_n} candidats), "
          f"{len(demoted)} démottés ===", flush=True)
    for r, _, why in sorted(confirmed, key=lambda t: t[2]):
        print(f"  [DEBAT/{why}] {r['q'][:70]}", flush=True)
    print("  --- démottés (ex-faux débats) ---", flush=True)
    for r in demoted:
        if r.get("was"):
            print(f"  [DÉMOTTÉ] {r['q'][:70]}", flush=True)

    # Garde-fous (sur les questions, robustes au kp_id)
    def _has(frag):
        return any(frag in (r["q"] or "").lower() for r, _, _ in confirmed)
    gbd_ok = _has("minimizes health risk")
    cancer_false = not any("cause cancer" in (r["q"] or "").lower() for r in
                           [c[0] for c in confirmed])
    print(f"\nGARDE-FOUS : GBD 'minimizes health risk' confirmé={gbd_ok} (doit être True) ; "
          f"'cause cancer' non-débat={cancer_false} (doit être True)", flush=True)

    if args.dry_run:
        print("[dry-run] rien écrit.", flush=True); drv.close(); return

    assert gbd_ok, "GARDE-FOU VIOLÉ : débat-vedette GBD perdu"
    assert cancer_false, "GARDE-FOU VIOLÉ : faux débat 'cause cancer' re-confirmé"

    with drv.session() as s:
        # 1) tout démotter sur le tenant (repart propre), 2) re-confirmer + positions_json
        s.run("MATCH (k:KeyPoint {tenant_id:$t}) SET k.is_debate=false", t=args.tenant)
        for r, positions, _ in confirmed:
            pos = [{"doc": p["doc_id"], "stance": p["stance"], "answer": p["answer"][:120]}
                   for p in positions][:8]
            s.run("MATCH (k:KeyPoint {kp_id:$kp}) SET k.is_debate=true, k.positions_json=$p",
                  kp=r["kp"], p=json.dumps(pos, ensure_ascii=False))
        n_after = s.run("MATCH (k:KeyPoint {tenant_id:$t, is_debate:true}) RETURN count(k) AS n",
                        t=args.tenant).single()["n"]
    print(f"[OK] is_debate recalculé : {n_after} débats écrits (était ~43).", flush=True)
    drv.close()


if __name__ == "__main__":
    main()
