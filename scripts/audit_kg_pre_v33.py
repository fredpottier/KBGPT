#!/usr/bin/env python3
"""
Audit KG pre-V3.3 (read-only, Phase A — Cypher only).

Produit un rapport sur l'état du KG existant avant le chantier
contradiction detection V3.3, pour affiner les estimations S0/S1.

Usage (depuis le container app ou worker) :
    docker exec knowbase-app python /app/scripts/audit_kg_pre_v33.py

Output :
    - data/forensics/audit_kg_pre_v33_<ts>.md
    - data/forensics/audit_kg_pre_v33_<ts>.json
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TS = datetime.now().strftime("%Y%m%d_%H%M%S")
JSON_PATH = OUTPUT_DIR / f"audit_kg_pre_v33_{TS}.json"
MD_PATH = OUTPUT_DIR / f"audit_kg_pre_v33_{TS}.md"


def run(session, query: str, **params) -> list[dict]:
    return [dict(r) for r in session.run(query, **params)]


def one(session, query: str, **params) -> Any:
    rows = run(session, query, **params)
    if not rows:
        return None
    first_row = rows[0]
    if len(first_row) == 1:
        return list(first_row.values())[0]
    return first_row


def main() -> None:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    report: dict[str, Any] = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "tenant_id": TENANT_ID,
            "neo4j_uri": NEO4J_URI,
        }
    }

    with driver.session() as s:
        # 1. Counts globaux
        print("[1/12] Counts globaux...")
        report["counts"] = {
            "total_claims": one(s, "MATCH (c:Claim) WHERE c.tenant_id=$t RETURN count(c)", t=TENANT_ID),
            "total_doc_contexts": one(s, "MATCH (dc:DocumentContext) WHERE dc.tenant_id=$t RETURN count(dc)", t=TENANT_ID),
            "total_documents": one(s, "MATCH (d:Document) WHERE d.tenant_id=$t RETURN count(d)", t=TENANT_ID),
            "total_passages": one(s, "MATCH (p:Passage) WHERE p.tenant_id=$t RETURN count(p)", t=TENANT_ID),
            "total_canonical_entities": one(s, "MATCH (ce:CanonicalEntity) WHERE ce.tenant_id=$t RETURN count(ce)", t=TENANT_ID),
            "total_clusters": one(s, "MATCH (cl:ClaimCluster) WHERE cl.tenant_id=$t RETURN count(cl)", t=TENANT_ID),
            "total_facets": one(s, "MATCH (f:Facet) WHERE f.tenant_id=$t RETURN count(f)", t=TENANT_ID),
            "total_apply_axes": one(s, "MATCH (a:ApplicabilityAxis) WHERE a.tenant_id=$t RETURN count(a)", t=TENANT_ID),
            "total_subject_anchors": one(s, "MATCH (sa:SubjectAnchor) WHERE sa.tenant_id=$t RETURN count(sa)", t=TENANT_ID),
            "total_comparable_subjects": one(s, "MATCH (cs:ComparableSubject) WHERE cs.tenant_id=$t RETURN count(cs)", t=TENANT_ID),
        }

        # 2. Edges baseline (V0 à migrer)
        print("[2/12] Edges baseline (V0 à migrer)...")
        report["edges_baseline"] = {
            "CONTRADICTS": one(s, "MATCH ()-[r:CONTRADICTS]->() RETURN count(r)"),
            "REFINES": one(s, "MATCH ()-[r:REFINES]->() RETURN count(r)"),
            "QUALIFIES": one(s, "MATCH ()-[r:QUALIFIES]->() RETURN count(r)"),
            "COMPLEMENTS": one(s, "MATCH ()-[r:COMPLEMENTS]->() RETURN count(r)"),
            "EVOLVES_TO": one(s, "MATCH ()-[r:EVOLVES_TO]->() RETURN count(r)"),
            "SPECIALIZES": one(s, "MATCH ()-[r:SPECIALIZES]->() RETURN count(r)"),
            "LOGICAL_RELATION_v33": one(s, "MATCH ()-[r:LOGICAL_RELATION]->() RETURN count(r)"),
            "CHAINS_TO": one(s, "MATCH ()-[r:CHAINS_TO]->() RETURN count(r)"),
            "ABOUT": one(s, "MATCH ()-[r:ABOUT]->() RETURN count(r)"),
            "BELONGS_TO_FACET": one(s, "MATCH ()-[r:BELONGS_TO_FACET]->() RETURN count(r)"),
            "HAS_AXIS_VALUE": one(s, "MATCH ()-[r:HAS_AXIS_VALUE]->() RETURN count(r)"),
            "IN_CLUSTER": one(s, "MATCH ()-[r:IN_CLUSTER]->() RETURN count(r)"),
        }

        # 3. Markers C4_SCANNED / C6_SCANNED
        print("[3/12] Markers idempotence (C4_SCANNED / C6_SCANNED)...")
        # Ce sont possiblement des labels OU des relations - testons les 2
        try:
            c4_label = one(s, "MATCH (c:C4_SCANNED) RETURN count(c)")
        except Exception:
            c4_label = None
        try:
            c4_rel = one(s, "MATCH ()-[r:C4_SCANNED]->() RETURN count(r)")
        except Exception:
            c4_rel = None
        try:
            c6_label = one(s, "MATCH (c:C6_SCANNED) RETURN count(c)")
        except Exception:
            c6_label = None
        try:
            c6_rel = one(s, "MATCH ()-[r:C6_SCANNED]->() RETURN count(r)")
        except Exception:
            c6_rel = None
        report["markers_scanned"] = {
            "C4_SCANNED_as_label": c4_label,
            "C4_SCANNED_as_relation": c4_rel,
            "C6_SCANNED_as_label": c6_label,
            "C6_SCANNED_as_relation": c6_rel,
        }

        # 4. Distribution Claims par doc
        print("[4/12] Distribution Claims par doc...")
        report["claims_per_doc"] = run(s, """
            MATCH (c:Claim) WHERE c.tenant_id=$t
            RETURN c.doc_id AS doc_id, count(c) AS claim_count
            ORDER BY claim_count DESC
        """, t=TENANT_ID)

        # 5. Passage_text disponibilité (S1b dépend de ça pour Tier 3)
        print("[5/12] Passage_text disponibilité...")
        report["passage_text_coverage"] = one(s, """
            MATCH (c:Claim) WHERE c.tenant_id=$t
            RETURN
              count(c) AS total,
              count(c.passage_text) AS with_passage_text,
              avg(coalesce(size(c.passage_text), 0)) AS avg_passage_size,
              percentileCont(coalesce(size(c.passage_text), 0), 0.5) AS median_passage_size
        """, t=TENANT_ID)

        # 6. DocumentContext applicability_frame_json + temporal_scope
        print("[6/12] DocumentContext metadata existante...")
        report["doc_context_v1_coverage"] = one(s, """
            MATCH (dc:DocumentContext) WHERE dc.tenant_id=$t
            RETURN
              count(dc) AS total,
              count(dc.applicability_frame_json) AS with_apply_frame_v1,
              count(dc.temporal_scope) AS with_temporal_scope,
              count(dc.axis_values) AS with_axis_values,
              count(dc.qualifiers) AS with_qualifiers,
              count(dc.primary_subject) AS with_primary_subject,
              count(dc.language) AS with_language
        """, t=TENANT_ID)

        # 7. ApplicabilityAxis details
        print("[7/12] ApplicabilityAxis details...")
        report["applicability_axes"] = run(s, """
            MATCH (a:ApplicabilityAxis) WHERE a.tenant_id=$t
            RETURN
              a.axis_key AS axis_key,
              a.axis_display_name AS display_name,
              a.order_type AS order_type,
              a.ordering_confidence AS ordering_confidence,
              size(coalesce(a.known_values, [])) AS known_values_count,
              size(coalesce(a.value_order, [])) AS value_order_size,
              a.doc_count AS doc_count,
              a.known_values AS known_values
            ORDER BY a.doc_count DESC
        """, t=TENANT_ID)

        # 8. HAS_AXIS_VALUE coverage
        print("[8/12] HAS_AXIS_VALUE coverage par doc...")
        report["has_axis_value_per_doc"] = run(s, """
            MATCH (dc:DocumentContext) WHERE dc.tenant_id=$t
            OPTIONAL MATCH (dc)-[r:HAS_AXIS_VALUE]->(a:ApplicabilityAxis)
            RETURN dc.doc_id AS doc_id, count(r) AS axis_value_count
            ORDER BY axis_value_count DESC
        """, t=TENANT_ID)

        # 9. Temporal signals (Tier 2 regex on temporal_scope strings)
        print("[9/12] Temporal scope strings (Tier 2 input)...")
        report["temporal_scope_samples"] = run(s, """
            MATCH (dc:DocumentContext)
            WHERE dc.tenant_id=$t AND dc.temporal_scope IS NOT NULL
            RETURN dc.doc_id AS doc_id, dc.temporal_scope AS temporal_scope
            LIMIT 30
        """, t=TENANT_ID)

        # 10. Tier 3 heuristique : claims avec marqueurs lexicaux dans passage_text
        # NB: \b word boundaries cassent via Python→Cypher escape, on utilise des regex sans
        # word boundaries (acceptable car les patterns sont assez spécifiques)
        print("[10/12] Tier 3 heuristique sur passage_text...")
        report["tier3_lexical_signals"] = one(s, """
            MATCH (c:Claim) WHERE c.tenant_id=$t AND c.passage_text IS NOT NULL
            WITH c,
              c.passage_text =~ '(?s).*(19|20)[0-9]{2}.*' AS has_year,
              c.passage_text =~ '(?si).*(effective|valid until|valid from|in force|enters into force|repealed|superseded|amended|amendment|revision).*' AS has_temporal_keyword
            RETURN
              count(c) AS total_claims_with_passage,
              sum(CASE WHEN has_year THEN 1 ELSE 0 END) AS with_year_in_text,
              sum(CASE WHEN has_temporal_keyword THEN 1 ELSE 0 END) AS with_temporal_keyword,
              sum(CASE WHEN has_year OR has_temporal_keyword THEN 1 ELSE 0 END) AS with_any_signal
        """, t=TENANT_ID)

        # 11. Ordered axes (lifecycle hint candidates)
        print("[11/12] Ordered axes pour Lifecycle hints (S1b.B)...")
        report["ordered_axes_for_lifecycle"] = run(s, """
            MATCH (a:ApplicabilityAxis)
            WHERE a.tenant_id=$t
              AND a.order_type IN ['TOTAL', 'PARTIAL']
              AND a.value_order IS NOT NULL
              AND size(a.value_order) >= 2
            RETURN
              a.axis_key AS axis_key,
              a.value_order AS value_order,
              a.doc_count AS doc_count,
              a.ordering_confidence AS ordering_confidence
            ORDER BY a.doc_count DESC
        """, t=TENANT_ID)

        # 12. Sample des CONTRADICTS pour audit qualité (10 random)
        print("[12/12] Sample CONTRADICTS edges (10 random pour inspection)...")
        report["contradicts_samples"] = run(s, """
            MATCH (a:Claim)-[r:CONTRADICTS]->(b:Claim)
            WHERE a.tenant_id=$t
            RETURN
              a.claim_id AS a_id,
              substring(a.text, 0, 200) AS a_text,
              a.doc_id AS a_doc,
              b.claim_id AS b_id,
              substring(b.text, 0, 200) AS b_text,
              b.doc_id AS b_doc,
              r.confidence AS confidence,
              r.basis AS basis
            ORDER BY rand()
            LIMIT 10
        """, t=TENANT_ID)

    driver.close()

    # === Write outputs ===
    JSON_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n✅ JSON: {JSON_PATH}")

    # === Markdown report ===
    md_lines: list[str] = []
    md_lines.append(f"# Audit KG pre-V3.3 — {TS}")
    md_lines.append("")
    md_lines.append(f"**Tenant** : `{TENANT_ID}` · **Neo4j** : `{NEO4J_URI}`")
    md_lines.append("")

    # Counts
    md_lines.append("## 1. Counts globaux")
    md_lines.append("")
    md_lines.append("| Label | Count |")
    md_lines.append("|---|---:|")
    for k, v in report["counts"].items():
        md_lines.append(f"| {k} | {v:,} |" if isinstance(v, int) else f"| {k} | {v} |")
    md_lines.append("")

    # Edges baseline
    md_lines.append("## 2. Edges baseline (V0 → à migrer en V3.3)")
    md_lines.append("")
    md_lines.append("| Relation | Count | Statut V3.3 |")
    md_lines.append("|---|---:|---|")
    eb = report["edges_baseline"]
    md_lines.append(f"| `:CONTRADICTS` | {eb['CONTRADICTS']:,} | À marker `legacy=true` puis purge S3.F |")
    md_lines.append(f"| `:REFINES` | {eb['REFINES']:,} | À marker `legacy=true` puis purge S3.F |")
    md_lines.append(f"| `:QUALIFIES` | {eb['QUALIFIES']:,} | À marker `legacy=true` puis purge S3.F |")
    md_lines.append(f"| `:COMPLEMENTS` (C6) | {eb['COMPLEMENTS']:,} | À marker `legacy=true` |")
    md_lines.append(f"| `:EVOLVES_TO` (C6) | {eb['EVOLVES_TO']:,} | À marker `legacy=true` |")
    md_lines.append(f"| `:SPECIALIZES` (C6) | {eb['SPECIALIZES']:,} | À marker `legacy=true` |")
    md_lines.append(f"| `:LOGICAL_RELATION` (V3.3 cible) | {eb['LOGICAL_RELATION_v33']:,} | Devrait = 0 avant S3 |")
    md_lines.append(f"| `:CHAINS_TO` | {eb['CHAINS_TO']:,} | Conservé (orthogonal au chantier) |")
    md_lines.append(f"| `:ABOUT` (Claim→Entity) | {eb['ABOUT']:,} | Conservé |")
    md_lines.append(f"| `:BELONGS_TO_FACET` | {eb['BELONGS_TO_FACET']:,} | Conservé |")
    md_lines.append(f"| `:HAS_AXIS_VALUE` | {eb['HAS_AXIS_VALUE']:,} | Conservé (input ApplicabilityFrame V2) |")
    md_lines.append(f"| `:IN_CLUSTER` | {eb['IN_CLUSTER']:,} | Conservé |")
    md_lines.append("")
    legacy_total = sum(eb[k] or 0 for k in ["CONTRADICTS", "REFINES", "QUALIFIES", "COMPLEMENTS", "EVOLVES_TO", "SPECIALIZES"])
    md_lines.append(f"**Total edges legacy à migrer** : {legacy_total:,}")
    md_lines.append("")

    # Markers
    md_lines.append("## 3. Markers idempotence")
    md_lines.append("")
    md_lines.append("| Marker | Type label | Type relation |")
    md_lines.append("|---|---:|---:|")
    m = report["markers_scanned"]
    md_lines.append(f"| C4_SCANNED | {m['C4_SCANNED_as_label']} | {m['C4_SCANNED_as_relation']} |")
    md_lines.append(f"| C6_SCANNED | {m['C6_SCANNED_as_label']} | {m['C6_SCANNED_as_relation']} |")
    md_lines.append("")

    # Claims per doc
    md_lines.append("## 4. Distribution Claims par doc")
    md_lines.append("")
    md_lines.append("| doc_id | claims |")
    md_lines.append("|---|---:|")
    for r in report["claims_per_doc"]:
        md_lines.append(f"| `{r['doc_id']}` | {r['claim_count']:,} |")
    md_lines.append("")

    # Passage text coverage
    md_lines.append("## 5. Passage_text disponibilité (input cascade Tier 3)")
    md_lines.append("")
    pt = report["passage_text_coverage"]
    total = pt["total"] or 0
    with_pt = pt["with_passage_text"] or 0
    coverage = (with_pt / total * 100) if total else 0
    md_lines.append(f"- Total claims : **{total:,}**")
    md_lines.append(f"- Avec `passage_text` non-null : **{with_pt:,}** ({coverage:.1f}%)")
    md_lines.append(f"- Taille moyenne `passage_text` : {pt['avg_passage_size']:.0f} chars" if pt['avg_passage_size'] else "- Taille moyenne : N/A")
    md_lines.append(f"- Taille médiane : {pt['median_passage_size']:.0f} chars" if pt['median_passage_size'] else "- Taille médiane : N/A")
    md_lines.append("")

    # DocContext V1 coverage
    md_lines.append("## 6. DocumentContext metadata V1 (input S1a backfill V2)")
    md_lines.append("")
    dc = report["doc_context_v1_coverage"]
    total_dc = dc["total"] or 0
    md_lines.append("| Champ | Coverage | % |")
    md_lines.append("|---|---:|---:|")
    for k in ["with_apply_frame_v1", "with_temporal_scope", "with_axis_values", "with_qualifiers", "with_primary_subject", "with_language"]:
        v = dc[k] or 0
        pct = (v / total_dc * 100) if total_dc else 0
        md_lines.append(f"| {k} | {v}/{total_dc} | {pct:.0f}% |")
    md_lines.append("")

    # Applicability axes
    md_lines.append("## 7. ApplicabilityAxis détails")
    md_lines.append("")
    md_lines.append("| axis_key | display_name | order_type | ordering_conf | known_values | doc_count |")
    md_lines.append("|---|---|---|---|---:|---:|")
    for r in report["applicability_axes"]:
        kv = r["known_values"] or []
        kv_preview = ", ".join(str(v) for v in kv[:5]) + ("..." if len(kv) > 5 else "")
        md_lines.append(f"| `{r['axis_key']}` | {r['display_name'] or '—'} | {r['order_type']} | {r['ordering_confidence']} | {r['known_values_count']} ({kv_preview}) | {r['doc_count']} |")
    md_lines.append("")

    # HAS_AXIS_VALUE per doc
    md_lines.append("## 8. HAS_AXIS_VALUE par doc (input ApplicabilityFrame V2)")
    md_lines.append("")
    md_lines.append("| doc_id | axis_values |")
    md_lines.append("|---|---:|")
    for r in report["has_axis_value_per_doc"]:
        md_lines.append(f"| `{r['doc_id']}` | {r['axis_value_count']} |")
    md_lines.append("")

    # Temporal scope samples
    md_lines.append("## 9. Temporal_scope strings (échantillon, input Tier 2)")
    md_lines.append("")
    if report["temporal_scope_samples"]:
        md_lines.append("| doc_id | temporal_scope |")
        md_lines.append("|---|---|")
        for r in report["temporal_scope_samples"][:30]:
            ts_clean = (r['temporal_scope'] or '')[:120].replace('|', '\\|').replace('\n', ' ')
            md_lines.append(f"| `{r['doc_id']}` | {ts_clean} |")
    else:
        md_lines.append("Aucun DocumentContext n'a `temporal_scope` populé. Tier 2 sera vide → fallback Tier 3+4 systématique.")
    md_lines.append("")

    # Tier 3 lexical
    md_lines.append("## 10. Tier 3 heuristique lexicale (regex sur passage_text)")
    md_lines.append("")
    t3 = report["tier3_lexical_signals"]
    if t3:
        total_pt = t3["total_claims_with_passage"] or 0
        md_lines.append(f"- Claims avec passage_text : **{total_pt:,}**")
        if total_pt:
            md_lines.append(f"- Avec année 19xx-20xx détectée : **{t3['with_year_in_text']:,}** ({t3['with_year_in_text']/total_pt*100:.1f}%)")
            md_lines.append(f"- Avec mot-clé temporel (effective/valid/amended/...) : **{t3['with_temporal_keyword']:,}** ({t3['with_temporal_keyword']/total_pt*100:.1f}%)")
            md_lines.append(f"- Avec **au moins un signal** Tier 3 : **{t3['with_any_signal']:,}** ({t3['with_any_signal']/total_pt*100:.1f}%)")
            tier4_estimated = total_pt - (t3['with_any_signal'] or 0)
            md_lines.append(f"- **Estimation candidates Tier 4 (LLM)** : {tier4_estimated:,} claims (si Tier 1+2 ne couvrent pas)")
    md_lines.append("")

    # Ordered axes for lifecycle
    md_lines.append("## 11. Axes ordonnés (input Lifecycle hint S1b.B)")
    md_lines.append("")
    if report["ordered_axes_for_lifecycle"]:
        md_lines.append("| axis_key | value_order | doc_count | confidence |")
        md_lines.append("|---|---|---:|---|")
        for r in report["ordered_axes_for_lifecycle"]:
            vo = r["value_order"] or []
            vo_preview = " → ".join(str(v) for v in vo[:6]) + ("..." if len(vo) > 6 else "")
            md_lines.append(f"| `{r['axis_key']}` | {vo_preview} | {r['doc_count']} | {r['ordering_confidence']} |")
    else:
        md_lines.append("Aucun axe ordonné disponible. LifecycleStatus ne pourra pas être inféré heuristiquement → tout sera UNKNOWN par défaut.")
    md_lines.append("")

    # Contradicts samples
    md_lines.append("## 12. Sample CONTRADICTS edges (10 random — qualité actuelle)")
    md_lines.append("")
    for i, r in enumerate(report["contradicts_samples"], 1):
        md_lines.append(f"### Paire {i} — confidence={r['confidence']}")
        md_lines.append(f"- **A** (`{r['a_doc']}` / `{r['a_id']}`): {(r['a_text'] or '').strip()}")
        md_lines.append(f"- **B** (`{r['b_doc']}` / `{r['b_id']}`): {(r['b_text'] or '').strip()}")
        md_lines.append(f"- basis: `{r['basis']}`")
        md_lines.append("")

    # Synthèse pour S0/S1
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## Synthèse pour calibrage S0/S1")
    md_lines.append("")
    md_lines.append(f"- **Total claims à backfiller** (S1b) : {report['counts']['total_claims']:,}")
    md_lines.append(f"- **Total DocumentContext à backfiller** (S1a) : {report['counts']['total_doc_contexts']:,}")
    md_lines.append(f"- **Total edges legacy à dump+marquer en S0** : {legacy_total:,}")
    if t3 and total_pt:
        tier4_estimated = total_pt - (t3['with_any_signal'] or 0)
        md_lines.append(f"- **Estimation Tier 4 LLM (S1b.A)** : ~{tier4_estimated:,} claims")
    md_lines.append("")
    md_lines.append("**Phase B (LLM sample)** à lancer ensuite pour :")
    md_lines.append("1. Calibrer la qualité Tier 4 sur 100 claims sample")
    md_lines.append("2. Dry-run FrameBuilder V2 sur 3 docs représentatifs")
    md_lines.append("")

    MD_PATH.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"✅ Markdown: {MD_PATH}")
    print(f"\n=== Counts ===")
    for k, v in report["counts"].items():
        print(f"  {k}: {v:,}" if isinstance(v, int) else f"  {k}: {v}")
    print(f"\n=== Edges legacy total ===")
    print(f"  {legacy_total:,}")


if __name__ == "__main__":
    main()
