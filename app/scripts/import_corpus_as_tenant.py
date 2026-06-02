"""Importe un backup Neo4j (export JSON) sous un NOUVEAU tenant, SANS purger le KG.

Permet de faire coexister un corpus de référence (ex SAP) à côté du corpus courant
(ex aéro) pour le protocole de non-régression multi-corpus — cf
doc/ongoing/PROTOCOLE_NON_REGRESSION_MULTI_CORPUS.md.

Le restore natif (_restore_neo4j) PURGE tout le KG : inutilisable pour la coexistence.
Ici on réécrit `tenant_id` → <tenant cible> et on CREATE sans purge.

⚠️ Les contraintes d'unicité Neo4j sont GLOBALES (claim_id, entity_id…), pas
tenant-scopées. Le dry-run vérifie qu'AUCUN id du backup ne collisionne avec le KG
courant avant d'autoriser l'import.

Usage :
  # 1) dry-run (lecture seule : comptes + chevauchement d'ids)
  python scripts/import_corpus_as_tenant.py --export <dir>/neo4j_export.json --tenant sap_ref
  # 2) exécution
  python scripts/import_corpus_as_tenant.py --export <dir>/neo4j_export.json --tenant sap_ref --execute
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass"))

# Label → propriété d'id contrainte unique GLOBALE (risque de collision cross-tenant)
CONSTRAINED = {
    "Claim": "claim_id", "Entity": "entity_id", "CanonicalEntity": "canonical_entity_id",
    "ClaimCluster": "cluster_id", "Facet": "facet_id", "ApplicabilityAxis": "axis_id",
    "DocumentContext": "doc_id", "Document": "doc_id", "ComparableSubject": "subject_id",
    "Perspective": "perspective_id",
}
# Labels-registre dont l'id est DÉTERMINISTE/partagé entre corpus (thématique) → collisionne.
# On préfixe SEULEMENT ceux-là. NE PAS préfixer : claim_id (référencé par le gold-set CP
# involved_claims + citations), doc_id (supporting_doc_ids), entity_id — tous propres au
# corpus (hash) et sans collision observée. Les relations remappent par id interne, donc
# préfixer ces id-props est invisible au runtime/bench (filtre tenant_id + texte).
PREFIX_LABELS = {"CanonicalEntity", "Facet", "ApplicabilityAxis"}
TMP_LABEL = "_ImportTmp"


def _apply_id_prefix(nodes, tenant: str) -> int:
    """Préfixe l'id-prop des labels-registre (PREFIX_LABELS) par '<tenant>__'. Idempotent."""
    pref = f"{tenant}__"
    n_prefixed = 0
    for node in nodes:
        for label in (node.get("labels") or []):
            if label in PREFIX_LABELS and label in CONSTRAINED:
                idprop = CONSTRAINED[label]
                v = node["properties"].get(idprop)
                if isinstance(v, str) and not v.startswith(pref):
                    node["properties"][idprop] = pref + v
                    n_prefixed += 1
    return n_prefixed


def _q(label: str) -> str:
    return "`" + label.replace("`", "") + "`"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, type=Path, help="chemin neo4j_export.json")
    ap.add_argument("--tenant", required=True, help="tenant cible (ex sap_ref)")
    ap.add_argument("--execute", action="store_true", help="exécute l'import (sinon dry-run)")
    ap.add_argument("--batch", type=int, default=1000)
    args = ap.parse_args()

    if not args.export.exists():
        print(f"ERREUR: export introuvable: {args.export}"); return 2

    print(f"Chargement {args.export} ...")
    data = json.loads(args.export.read_text(encoding="utf-8"))
    nodes: List[Dict[str, Any]] = data.get("nodes", [])
    rels: List[Dict[str, Any]] = data.get("relationships", [])
    print(f"  nodes={len(nodes)} relationships={len(rels)}")

    by_labels: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for n in nodes:
        by_labels[tuple(n.get("labels") or [])].append(n)
    print("  par label:", {", ".join(k) or "(none)": len(v) for k, v in sorted(by_labels.items(), key=lambda x: -len(x[1]))})

    # Préfixe des id-props contraints (sauf doc_id) → garantit zéro collision globale.
    n_pref = _apply_id_prefix(nodes, args.tenant)
    print(f"  id-props préfixés par '{args.tenant}__' (sauf doc_id): {n_pref}")

    drv = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

    def run(cy, **kw):
        with drv.session() as s:
            return [r.data() for r in s.run(cy, **kw)]

    # ── Pré-check : collision d'ids contraints avec le KG courant ──
    print("\n=== PRÉ-CHECK collision d'ids (contraintes globales) ===")
    collisions = {}
    for label, idprop in CONSTRAINED.items():
        export_ids = {n["properties"].get(idprop) for n in by_labels.get((label,), []) if n["properties"].get(idprop)}
        # certains labels apparaissent en multi-label : balayer tous les groupes
        for lbls, group in by_labels.items():
            if label in lbls and lbls != (label,):
                export_ids |= {n["properties"].get(idprop) for n in group if n["properties"].get(idprop)}
        if not export_ids:
            continue
        existing = run(
            f"MATCH (n:{_q(label)}) WHERE n.{idprop} IS NOT NULL RETURN collect(n.{idprop}) AS ids"
        )
        live_ids = set(existing[0]["ids"]) if existing else set()
        overlap = export_ids & live_ids
        status = "OK" if not overlap else f"⚠️ {len(overlap)} COLLISIONS"
        print(f"  {label:18} export={len(export_ids):6} live={len(live_ids):6} {status}")
        if overlap:
            collisions[label] = list(overlap)[:5]

    # tenant déjà présent ?
    tcount = run("MATCH (n) WHERE n.tenant_id=$t RETURN count(n) AS n", t=args.tenant)[0]["n"]
    print(f"  tenant cible '{args.tenant}' contient déjà {tcount} nœuds", "(sera purgé avant import)" if tcount and args.execute else "")
    aero = run("MATCH (n) WHERE n.tenant_id='default' RETURN count(n) AS n")[0]["n"]
    print(f"  tenant 'default' (courant) : {aero} nœuds — doit rester INCHANGÉ")

    if collisions:
        print("\n❌ COLLISIONS d'ids avec le KG courant → import refusé (risque de violation de contrainte).")
        print("   Exemples:", collisions); drv.close(); return 1

    if not args.execute:
        print("\n[DRY-RUN] Pré-check OK, aucune collision. Relancer avec --execute pour importer.")
        drv.close(); return 0

    # ── Import ──
    t0 = time.time()
    # purge éventuelle du tenant cible (idempotence)
    if tcount:
        print(f"\nPurge du tenant '{args.tenant}' existant ({tcount} nœuds)...")
        run("MATCH (n) WHERE n.tenant_id=$t DETACH DELETE n", t=args.tenant)

    print("Création index temporaire...")
    run(f"CREATE INDEX import_tmp_idx IF NOT EXISTS FOR (n:{TMP_LABEL}) ON (n._imp_id)")

    print(f"Import des nœuds (tenant_id='{args.tenant}')...")
    for lbls, group in by_labels.items():
        label_str = "".join(f":{_q(l)}" for l in lbls) + f":{TMP_LABEL}"
        for i in range(0, len(group), args.batch):
            batch = group[i:i + args.batch]
            rows = [{"id": n["id"], "props": n["properties"]} for n in batch]
            run(
                f"UNWIND $rows AS row CREATE (n{label_str}) "
                f"SET n = row.props SET n.tenant_id = $t, n._imp_id = row.id",
                rows=rows, t=args.tenant,
            )
        print(f"  {','.join(lbls) or '(none)':40} {len(group)} nœuds")

    print(f"Import des {len(rels)} relations...")
    rels_by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rels:
        rels_by_type[r["type"]].append(r)
    for rtype, group in rels_by_type.items():
        created = 0
        for i in range(0, len(group), args.batch):
            batch = group[i:i + args.batch]
            rows = [{"s": r["start_id"], "e": r["end_id"], "props": r.get("properties", {})} for r in batch]
            res = run(
                f"UNWIND $rows AS row "
                f"MATCH (a:{TMP_LABEL} {{_imp_id: row.s}}), (b:{TMP_LABEL} {{_imp_id: row.e}}) "
                f"CREATE (a)-[rel:{_q(rtype)}]->(b) SET rel = row.props RETURN count(rel) AS c",
                rows=rows,
            )
            created += res[0]["c"] if res else 0
        print(f"  {rtype:30} {created}/{len(group)} relations")

    print("Nettoyage label/prop temporaires...")
    run(f"MATCH (n:{TMP_LABEL}) CALL {{ WITH n REMOVE n:{TMP_LABEL} REMOVE n._imp_id }} IN TRANSACTIONS OF 5000 ROWS")
    run("DROP INDEX import_tmp_idx IF EXISTS")

    # ── Vérification ──
    sap_n = run("MATCH (n) WHERE n.tenant_id=$t RETURN count(n) AS n", t=args.tenant)[0]["n"]
    sap_claims = run("MATCH (c:Claim) WHERE c.tenant_id=$t RETURN count(c) AS n", t=args.tenant)[0]["n"]
    aero_after = run("MATCH (n) WHERE n.tenant_id='default' RETURN count(n) AS n")[0]["n"]
    print(f"\n=== VÉRIFICATION ===")
    print(f"  tenant '{args.tenant}' : {sap_n} nœuds, {sap_claims} claims")
    print(f"  tenant 'default' (aéro) : {aero_after} nœuds (avant: {aero}) — {'INCHANGÉ ✅' if aero_after == aero else '⚠️ MODIFIÉ'}")
    print(f"  durée: {time.time()-t0:.0f}s")
    drv.close()
    return 0 if aero_after == aero else 1


if __name__ == "__main__":
    sys.exit(main())
