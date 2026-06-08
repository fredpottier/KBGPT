"""relabel_gold_post_aero.py — Re-relabel #451 : questions gold ressuscitées par l'import aero.

18 questions du gold-set 150q ont été passées answerable→unanswerable parce que
leur ancre factuelle avait disparu du KG staged (#450). Les gardes #450 +
le contexte corrigé + #457 devraient en ressusciter une partie dans le tenant
`aero`. Ce script ne décide PAS seul : pour chaque candidate il cherche dans
`aero` les claims qui contiennent l'ancre/les mots-clés et AFFICHE les preuves
→ décision humaine (Fred) sur le re-relabel answerable.

Mode --apply : applique les re-relabels listés dans un fichier de décisions
(une question_id par ligne) — JAMAIS automatique.

Usage :
    docker exec app python //app/scripts/relabel_gold_post_aero.py            # rapport
    docker exec app python //app/scripts/relabel_gold_post_aero.py --apply ids.txt
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

GOLD = Path("benchmark/questions/gold_set_aero_150q.json")
TENANT = "aero"


def _driver():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    return get_neo4j_client().driver


def _candidates(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for q in questions:
        gt = q.get("ground_truth", {})
        rev = q.get("revision") or {}
        if gt.get("answerability") == "unanswerable" and rev.get("previous_answerability") == "answerable":
            out.append(q)
    return out


def _keywords(q: Dict[str, Any]) -> List[str]:
    """Mots-clés de recherche : identifiants exacts + tokens entre quotes de la raison."""
    gt = q.get("ground_truth", {})
    kws = list(gt.get("exact_identifiers") or [])
    reason = (q.get("revision") or {}).get("reason") or ""
    # phrases entre quotes simples/typographiques dans la raison
    for m in re.findall(r"['‘’\"]([^'‘’\"]{4,60})['‘’\"]", reason):
        kws.append(m)
    # dédoublonnage en gardant l'ordre
    seen, uniq = set(), []
    for k in kws:
        k = k.strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            uniq.append(k)
    return uniq


def report() -> None:
    questions = json.loads(GOLD.read_text(encoding="utf-8"))
    cands = _candidates(questions)
    drv = _driver()
    print(f"# Re-relabel #451 — {len(cands)} candidates (tenant {TENANT})\n")
    with drv.session() as s:
        for q in cands:
            kws = _keywords(q)
            print(f"## {q['id']}  [{q.get('primary_type')}]")
            print(f"   Q: {q['question'][:100]}")
            print(f"   mots-clés: {kws}")
            found_any = False
            for kw in kws[:4]:
                rows = list(s.run(
                    "MATCH (c:Claim {tenant_id:$t}) WHERE toLower(c.text) CONTAINS toLower($kw) "
                    "RETURN c.doc_id AS doc, c.text AS text LIMIT 2", t=TENANT, kw=kw))
                if rows:
                    found_any = True
                    for r in rows:
                        print(f"     ✓ '{kw}' → [{r['doc']}] {r['text'][:110]}")
            print(f"   VERDICT proposé: {'RESSUSCITÉE → answerable ?' if found_any else 'toujours absente → garder unanswerable'}\n")


def apply(ids_file: Path) -> None:
    ids = {ln.strip() for ln in ids_file.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}
    questions = json.loads(GOLD.read_text(encoding="utf-8"))
    n = 0
    for q in questions:
        if q["id"] in ids:
            gt = q.setdefault("ground_truth", {})
            gt["answerability"] = "answerable"
            rev = q.setdefault("revision", {})
            rev["relabel_aero"] = {"date": "2026-06-08", "reason": "ancre ressuscitée par l'import aero (#451)"}
            n += 1
    GOLD.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{n} questions re-relabellisées answerable (sur {len(ids)} demandées).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", metavar="IDS_FILE")
    args = ap.parse_args()
    if args.apply:
        apply(Path(args.apply))
    else:
        report()


if __name__ == "__main__":
    main()
