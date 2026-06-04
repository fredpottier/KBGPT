#!/usr/bin/env python
"""
audit_gold_set_vs_kg.py — Vérifie qu'un gold-set est « raccord » avec le KG courant.

Pour chaque question du gold-set (schéma a38), contrôle :
  1. supporting_doc_ids : le document a-t-il encore des claims dans le KG ?
  2. exact_identifiers : chaque identifiant attendu apparaît-il verbatim dans au
     moins un claim du tenant (recherche substring insensible à la casse) ?
  3. (answerable seulement) — un signal lexical minimal : ≥1 claim contenant un
     des termes saillants de la réponse attendue.

Sortie : rapport par question (OK / WARN / BROKEN) + agrégats, et un JSON
détaillé pour le travail de nettoyage.

    docker exec knowbase-app python scripts/audit_gold_set_vs_kg.py \
        --gold benchmark/questions/gold_set_aero_150q.json --tenant default
"""

from __future__ import annotations

import argparse
import json
import re


def salient_tokens(text: str, max_n: int = 4) -> list[str]:
    """Tokens saillants d'une réponse attendue (codes, nombres, mots rares)."""
    if not text:
        return []
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-/]{3,}", text)
    # privilégier codes/nombres (contiennent chiffre ou MAJ multiples)
    scored = sorted(
        set(toks),
        key=lambda t: (any(c.isdigit() for c in t), len(t)),
        reverse=True,
    )
    return [t.lower() for t in scored[:max_n]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--out", default="/data/staging_new_docs/gold_set_audit.json")
    args = ap.parse_args()

    from knowbase.common.clients.neo4j_client import get_neo4j_client

    driver = get_neo4j_client().driver
    gold = json.load(open(args.gold, encoding="utf-8"))
    items = gold if isinstance(gold, list) else gold.get("questions", [])

    # Docs présents (avec claims) dans le tenant
    with driver.session() as s:
        docs_alive = {
            r["d"] for r in s.run(
                "MATCH (c:Claim {tenant_id: $t}) RETURN DISTINCT c.doc_id AS d",
                t=args.tenant,
            )
        }

    def claim_contains(substr: str) -> bool:
        with driver.session() as s:
            return s.run(
                "MATCH (c:Claim {tenant_id: $t}) "
                "WHERE toLower(c.text) CONTAINS toLower($x) "
                "RETURN count(c) > 0 AS ok",
                t=args.tenant, x=substr,
            ).single()["ok"]

    report = []
    counts = {"OK": 0, "WARN": 0, "BROKEN": 0}
    for q in items:
        gt = q.get("ground_truth", {})
        issues = []
        # 1. docs
        for d in gt.get("supporting_doc_ids") or []:
            if d not in docs_alive:
                issues.append(f"doc_absent:{d}")
        # 2. identifiants exacts — on extrait le token-cœur de chaque identifiant
        missing_ids = []
        for ident in gt.get("exact_identifiers") or []:
            toks = salient_tokens(ident, max_n=2)
            if toks and not any(claim_contains(t) for t in toks):
                missing_ids.append(ident)
        if missing_ids:
            issues.append(f"identifiants_absents:{missing_ids}")
        # 3. signal lexical de la réponse (answerable seulement)
        weak = False
        if (gt.get("answerability") == "answerable") and not missing_ids:
            toks = salient_tokens(gt.get("answer") or "", max_n=3)
            if toks and not any(claim_contains(t) for t in toks):
                weak = True
                issues.append("réponse_sans_écho_lexical")

        if any(i.startswith(("doc_absent", "identifiants_absents")) for i in issues):
            status = "BROKEN"
        elif issues:
            status = "WARN"
        else:
            status = "OK"
        counts[status] += 1
        report.append({
            "id": q.get("id"),
            "type": q.get("primary_type"),
            "answerability": gt.get("answerability"),
            "status": status,
            "issues": issues,
            "question": (q.get("question") or "")[:120],
        })

    print(f"AUDIT GOLD-SET vs KG (tenant={args.tenant}) — {len(items)} questions")
    print(f"  OK={counts['OK']}  WARN={counts['WARN']}  BROKEN={counts['BROKEN']}")
    for r in report:
        if r["status"] != "OK":
            print(f"  [{r['status']}] {r['id']} ({r['type']}/{r['answerability']}) — {r['issues']}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"rapport détaillé → {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
