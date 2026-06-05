#!/usr/bin/env python
"""
reanchor_gold_candidates.py — Prépare le ré-ancrage du gold-set sur le wording staged.

Contexte : après la ré-ingestion staged (P1.4-bis), les claims du KG ont un
wording différent (décomposition minimaliste + décontextualisation). Le juge
LLM compare la réponse du runtime à `ground_truth.answer` rédigé sur le wording
LEGACY → C1 chute alors que exact_id_recall tient (ex : multi_hop 0.79 / 0.385).

Pour chaque question answerable, ce script :
  1. mesure la COUVERTURE des tokens saillants de `ground_truth.answer` dans
     les claims staged du tenant (écho lexical token par token) ;
  2. récupère les claims-ancres candidats (claims contenant les identifiants
     exacts et/ou les tokens saillants de la réponse) ;
  3. classe la question : ANCHORED (couverture forte) / DRIFT (couverture
     partielle — réponse à ré-ancrer) / ORPHAN (aucun écho — candidate
     unanswerable ou question à revoir).

Sortie : JSON de travail avec, par question DRIFT/ORPHAN, le top des claims
candidats (texte verbatim) pour réécrire `ground_truth.answer` a minima.

    docker exec knowbase-app python scripts/reanchor_gold_candidates.py \
        --gold benchmark/questions/gold_set_aero_150q.json --tenant default
"""

from __future__ import annotations

import argparse
import json
import re

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "has", "have", "been", "must", "shall", "should", "will", "which", "when",
    "where", "their", "they", "these", "those", "than", "then", "into", "such",
    "each", "other", "also", "may", "can", "not", "but", "all", "any", "its",
    "according", "document", "section", "amendment", "requirements", "requirement",
}


def salient_tokens(text: str, max_n: int = 10) -> list[str]:
    """Tokens saillants d'une réponse (codes, nombres, mots porteurs)."""
    if not text:
        return []
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-/]{3,}", text)
    out, seen = [], set()
    for t in toks:
        tl = t.lower().strip(".-/")
        if tl in STOPWORDS or tl in seen or len(tl) < 4:
            continue
        seen.add(tl)
        out.append(tl)
    # codes/nombres d'abord (plus discriminants), puis mots longs
    out.sort(key=lambda t: (any(c.isdigit() for c in t), len(t)), reverse=True)
    return out[:max_n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--out", default="/data/staging_new_docs/gold_reanchor_candidates.json")
    ap.add_argument("--top-claims", type=int, default=8)
    args = ap.parse_args()

    from knowbase.common.clients.neo4j_client import get_neo4j_client
    driver = get_neo4j_client().driver

    gold = json.load(open(args.gold, encoding="utf-8"))
    items = gold if isinstance(gold, list) else gold.get("questions", [])

    def claims_matching(tokens: list[str], limit: int) -> list[dict]:
        """Claims contenant le plus de tokens (scoring par nb de tokens présents)."""
        if not tokens:
            return []
        with driver.session() as s:
            rows = s.run(
                """
                MATCH (c:Claim {tenant_id: $t})
                WITH c, [tok IN $toks WHERE toLower(c.text) CONTAINS tok] AS hits
                WHERE size(hits) > 0
                RETURN c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id,
                       size(hits) AS n_hits, hits AS hits,
                       c.invalidated_at IS NOT NULL AS invalidated,
                       c.lifecycle_status_current AS lifecycle
                ORDER BY n_hits DESC
                LIMIT $lim
                """,
                t=args.tenant, toks=tokens, lim=limit,
            )
            return [dict(r) for r in rows]

    report, agg = [], {"ANCHORED": 0, "DRIFT": 0, "ORPHAN": 0, "SKIP": 0}
    for q in items:
        gt = q.get("ground_truth", {}) or {}
        if gt.get("answerability") != "answerable":
            agg["SKIP"] += 1
            continue
        answer = gt.get("answer") or ""
        toks = salient_tokens(answer)
        ids = gt.get("exact_identifiers") or []
        id_toks = [t for i in ids for t in salient_tokens(i, max_n=2)]
        cands = claims_matching(list(dict.fromkeys(toks + id_toks)), args.top_claims)

        covered = set()
        for c in cands:
            covered.update(c["hits"])
        coverage = (len([t for t in toks if t in covered]) / len(toks)) if toks else 1.0

        if coverage >= 0.6:
            status = "ANCHORED"
        elif cands:
            status = "DRIFT"
        else:
            status = "ORPHAN"
        agg[status] += 1
        entry = {
            "id": q.get("id"),
            "type": q.get("primary_type"),
            "status": status,
            "coverage": round(coverage, 2),
            "question": q.get("question"),
            "gold_answer": answer,
            "missing_tokens": [t for t in toks if t not in covered],
        }
        if status != "ANCHORED":
            entry["candidate_claims"] = [
                {k: c[k] for k in ("claim_id", "text", "doc_id", "n_hits", "invalidated", "lifecycle")}
                for c in cands
            ]
        report.append(entry)

    print(f"RÉ-ANCRAGE GOLD vs KG staged (tenant={args.tenant})")
    print(f"  ANCHORED={agg['ANCHORED']}  DRIFT={agg['DRIFT']}  ORPHAN={agg['ORPHAN']}  (skip non-answerable={agg['SKIP']})")
    for r in report:
        if r["status"] != "ANCHORED":
            print(f"  [{r['status']} cov={r['coverage']}] {r['id']} ({r['type']}) — manquants: {r['missing_tokens'][:6]}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"détail → {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
