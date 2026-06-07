"""kg_snapshot.py — Photographie structurelle d'un tenant du KG (déterministe).

Capture l'état mesurable d'un tenant pour comparer DEUX imports (ancien `default`
vs nouveau `aero`) après une ré-ingestion. À lancer AVANT la purge sur l'ancien,
puis après l'import sur le nouveau — même méthode, comparaison honnête.

Le volume seul ne juge RIEN (la sur-extraction gonfle les compteurs) : ce snapshot
sert à lire les ÉCARTS (couverture de dates, richesse relationnelle, granularité,
grounding) en complément du bench end-to-end et de l'inspection d'échantillons.

Usage :
    docker-compose exec app python //app/scripts/kg_snapshot.py --tenant default
    docker-compose exec app python //app/scripts/kg_snapshot.py --tenant aero
    # comparer deux snapshots :
    docker-compose exec app python //app/scripts/kg_snapshot.py --compare \\
        /data/staging_new_docs/kg_snapshot_default_*.json \\
        /data/staging_new_docs/kg_snapshot_aero_*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

OUT_DIR = Path("/data/staging_new_docs")

# Relations claim-à-claim sémantiques (cœur de valeur) — hors marqueurs pipeline.
_SEMANTIC_RELS = [
    "REFINES", "COMPLEMENTS", "SPECIALIZES", "QUALIFIES", "CHAINS_TO",
    "EVOLUTION_OF", "EVOLVES_TO", "CONTRADICTS", "SUPERSEDES",
    "STEP_OF", "PREREQUISITE_OF", "HAS_OUTCOME",
]


def _driver():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    return get_neo4j_client().driver


def snapshot(tenant: str) -> Dict[str, Any]:
    drv = _driver()
    out: Dict[str, Any] = {
        "tenant": tenant,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    with drv.session() as s:
        scalar = lambda q, **p: s.run(q, tenant=tenant, **p).single()[0]

        # ── Volume ──────────────────────────────────────────────────────────
        out["n_claims"] = scalar("MATCH (c:Claim {tenant_id:$tenant}) RETURN count(c)")
        out["n_entities"] = scalar("MATCH (e:Entity {tenant_id:$tenant}) RETURN count(e)")
        out["n_procedures"] = scalar("MATCH (p:Procedure {tenant_id:$tenant}) RETURN count(p)")
        out["n_documents"] = scalar(
            "MATCH (c:Claim {tenant_id:$tenant}) WHERE c.doc_id IS NOT NULL "
            "RETURN count(DISTINCT c.doc_id)")

        # ── Distributions claim ─────────────────────────────────────────────
        out["claim_type"] = {r["k"]: r["n"] for r in s.run(
            "MATCH (c:Claim {tenant_id:$tenant}) RETURN c.claim_type AS k, count(c) AS n "
            "ORDER BY n DESC", tenant=tenant)}
        out["quality_status"] = {str(r["k"]): r["n"] for r in s.run(
            "MATCH (c:Claim {tenant_id:$tenant}) RETURN c.quality_status AS k, count(c) AS n "
            "ORDER BY n DESC", tenant=tenant)}
        out["marginal"] = {str(r["k"]): r["n"] for r in s.run(
            "MATCH (c:Claim {tenant_id:$tenant}) RETURN c.marginal AS k, count(c) AS n",
            tenant=tenant)}
        # couverture date AU NIVEAU CLAIM (explicit vs ingestion_fallback)
        out["valid_from_marker"] = {str(r["k"]): r["n"] for r in s.run(
            "MATCH (c:Claim {tenant_id:$tenant}) RETURN c.valid_from_marker AS k, count(c) AS n "
            "ORDER BY n DESC", tenant=tenant)}

        # ── Granularité (longueur du texte de claim) ───────────────────────
        g = s.run(
            "MATCH (c:Claim {tenant_id:$tenant}) WHERE c.text IS NOT NULL "
            "WITH size(c.text) AS L "
            "RETURN min(L) AS mn, max(L) AS mx, avg(L) AS avg, "
            "percentileCont(L,0.5) AS p50, percentileCont(L,0.9) AS p90",
            tenant=tenant).single()
        out["claim_text_len"] = {
            "min": g["mn"], "p50": g["p50"], "avg": round(g["avg"], 1) if g["avg"] else None,
            "p90": g["p90"], "max": g["mx"],
        }

        # ── Grounding moyen (depuis quality_scores_json) ────────────────────
        # parse côté python (champ JSON string)
        scores = []
        for r in s.run(
            "MATCH (c:Claim {tenant_id:$tenant}) WHERE c.quality_scores_json IS NOT NULL "
            "RETURN c.quality_scores_json AS q", tenant=tenant):
            try:
                d = json.loads(r["q"])
                if "grounding_entail" in d:
                    scores.append(float(d["grounding_entail"]))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        out["grounding_entail"] = {
            "n": len(scores),
            "avg": round(sum(scores) / len(scores), 4) if scores else None,
        }

        # ── Relations par type (claim-à-claim, dirigées) ────────────────────
        rels: Dict[str, int] = {}
        for rt in _SEMANTIC_RELS:
            n = scalar(
                f"MATCH (a:Claim {{tenant_id:$tenant}})-[r:{rt}]->(b:Claim {{tenant_id:$tenant}}) "
                "RETURN count(r)")
            if n:
                rels[rt] = n
        out["claim_relations"] = rels
        out["n_claim_relations_total"] = sum(rels.values())

        # ── Lignée document ────────────────────────────────────────────────
        out["n_supersedes_doc"] = scalar(
            "MATCH (:Document {tenant_id:$tenant})-[r:SUPERSEDES_DOC]->(:Document) RETURN count(r)")
        out["n_declares_supersession"] = scalar(
            "MATCH (c:Claim {tenant_id:$tenant})-[r:DECLARES_SUPERSESSION]->() RETURN count(r)")

        # ── Contradictions adjugées ────────────────────────────────────────
        out["contradictions_by_verdict"] = {str(r["k"] or "NON_ADJUGÉ"): r["n"] for r in s.run(
            "MATCH (:Claim {tenant_id:$tenant})-[r:CONTRADICTS]->(:Claim {tenant_id:$tenant}) "
            "RETURN r.adjudication AS k, count(r)/2 AS n ORDER BY n DESC", tenant=tenant)}

        # ── Couverture de dates AU NIVEAU DOCUMENT (proxy domain context) ──
        # modal valid_from par doc (même règle que la frise du Référentiel)
        rows = list(s.run(
            "MATCH (c:Claim {tenant_id:$tenant}) WHERE c.doc_id IS NOT NULL "
            "WITH c.doc_id AS doc, toString(c.valid_from) AS vf, count(*) AS n "
            "ORDER BY doc, (vf IS NULL), n DESC "
            "WITH doc, collect(vf)[0] AS modal "
            "RETURN doc, modal", tenant=tenant))
        dated = sum(1 for r in rows if r["modal"])
        out["doc_date_coverage"] = {
            "docs_total": len(rows), "docs_dated": dated,
            "docs_undated": len(rows) - dated,
            "pct_dated": round(100 * dated / len(rows), 1) if rows else None,
        }

        # ── Par document : volume + date (détail pour diff fin) ─────────────
        out["per_doc"] = sorted(
            [{"doc_id": r["doc"], "n_claims": r["n"], "dated": bool(r["modal"]),
              "date": (r["modal"] or "")[:10] or None}
             for r in s.run(
                "MATCH (c:Claim {tenant_id:$tenant}) WHERE c.doc_id IS NOT NULL "
                "WITH c.doc_id AS doc, count(c) AS n, "
                "     collect(toString(c.valid_from))[0] AS modal "
                "RETURN doc, n, modal", tenant=tenant)],
            key=lambda x: -x["n_claims"])

    return out


def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    flat = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            flat.update(_flatten(v, key + "."))
        elif isinstance(v, (int, float)) or v is None:
            flat[key] = v
    return flat


def compare(path_a: Path, path_b: Path) -> None:
    a = json.loads(path_a.read_text(encoding="utf-8"))
    b = json.loads(path_b.read_text(encoding="utf-8"))
    fa, fb = _flatten(a), _flatten(b)
    keys = [k for k in fa if k in fb and not k.startswith("per_doc")]
    print(f"\n{'MÉTRIQUE':40} {a['tenant']:>14} {b['tenant']:>14} {'Δ':>12}")
    print("-" * 84)
    for k in keys:
        va, vb = fa[k], fb[k]
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = vb - va
            sign = "+" if delta > 0 else ""
            print(f"{k:40} {va:>14} {vb:>14} {sign}{delta:>11}")
    # docs apparus/disparus
    da = {x["doc_id"] for x in a.get("per_doc", [])}
    db = {x["doc_id"] for x in b.get("per_doc", [])}
    if da - db:
        print(f"\nDocs présents dans {a['tenant']} mais absents de {b['tenant']} : {sorted(da - db)}")
    if db - da:
        print(f"Docs présents dans {b['tenant']} mais absents de {a['tenant']} : {sorted(db - da)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--compare", nargs=2, metavar=("SNAP_A", "SNAP_B"))
    args = ap.parse_args()

    if args.compare:
        compare(Path(args.compare[0]), Path(args.compare[1]))
        return

    snap = snapshot(args.tenant)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"kg_snapshot_{args.tenant}_{stamp}.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")

    # résumé console
    print(f"snapshot tenant '{args.tenant}' -> {out}")
    print(f"  claims={snap['n_claims']}  entities={snap['n_entities']}  "
          f"docs={snap['n_documents']}  procedures={snap['n_procedures']}")
    print(f"  relations claim-claim={snap['n_claim_relations_total']} {snap['claim_relations']}")
    print(f"  lignées SUPERSEDES_DOC={snap['n_supersedes_doc']}  "
          f"DECLARES_SUPERSESSION={snap['n_declares_supersession']}")
    print(f"  dates docs : {snap['doc_date_coverage']}")
    print(f"  marginal : {snap['marginal']}")
    print(f"  grounding moyen : {snap['grounding_entail']}")


if __name__ == "__main__":
    main()
