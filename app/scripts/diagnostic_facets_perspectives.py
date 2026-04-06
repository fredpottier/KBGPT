"""
Phase 0 — Diagnostic Facets pour la couche Perspective.

Verifie que la matiere premiere (Facets sur les Claims) est suffisante
pour construire des Perspectives thematiques par ComparableSubject.

Usage (dans Docker):
    python scripts/diagnostic_facets_perspectives.py

Output:
    - Rapport console detaille
    - diagnostic_facets_report.json (dans le repertoire courant)

Criteres GO/NO-GO:
    >= 75% claims avec facet  → GO normal  (facet_weight=0.5)
    60-74%                    → GO prudent (facet_weight=0.3)
    < 60%                     → NO-GO facet-first, embedding-first
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter, defaultdict

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def get_subjects(session, tenant_id: str) -> list[dict]:
    """Recupere les SubjectAnchors avec leur nombre de claims.

    Le KG utilise SubjectAnchors (via ABOUT_SUBJECT) plutot que ComparableSubjects
    pour la plupart des sujets. Le chemin est :
        SubjectAnchor <-[:ABOUT_SUBJECT]- DocumentContext (doc_id)
        Claim (doc_id) — jointure par propriete doc_id
    """
    # Recuperer les paires SubjectAnchor -> doc_ids
    # Note: tenant_id peut etre None sur les SubjectAnchors existants
    result = session.run("""
        MATCH (sa:SubjectAnchor)<-[:ABOUT_SUBJECT]-(dc:DocumentContext)
        RETURN sa.subject_id AS subject_id,
               sa.canonical_name AS name,
               'SubjectAnchor' AS subject_type,
               collect(DISTINCT dc.doc_id) AS doc_ids
    """)
    sa_rows = [dict(r) for r in result]

    # Recuperer le claim count par doc_id (1 requete)
    result = session.run("""
        MATCH (c:Claim {tenant_id: $tid})
        RETURN c.doc_id AS doc_id, count(c) AS cnt
    """, tid=tenant_id)
    claims_per_doc = {r["doc_id"]: r["cnt"] for r in result}

    # Calculer claim_count par sujet cote Python
    subjects = []
    for row in sa_rows:
        claim_count = sum(claims_per_doc.get(did, 0) for did in row["doc_ids"])
        if claim_count >= 10:
            subjects.append({
                "subject_id": row["subject_id"],
                "name": row["name"],
                "subject_type": row["subject_type"],
                "claim_count": claim_count,
                "doc_count": len(row["doc_ids"]),
                "doc_ids": row["doc_ids"],
            })

    # Aussi les ComparableSubjects
    result = session.run("""
        MATCH (cs:ComparableSubject {tenant_id: $tid})<-[:ABOUT_COMPARABLE]-(dc:DocumentContext)
        RETURN cs.subject_id AS subject_id,
               cs.canonical_name AS name,
               'ComparableSubject' AS subject_type,
               collect(DISTINCT dc.doc_id) AS doc_ids
    """, tid=tenant_id)
    for row in result:
        row = dict(row)
        claim_count = sum(claims_per_doc.get(did, 0) for did in row["doc_ids"])
        if claim_count >= 10:
            subjects.append({
                "subject_id": row["subject_id"],
                "name": row["name"],
                "subject_type": row["subject_type"],
                "claim_count": claim_count,
                "doc_count": len(row["doc_ids"]),
                "doc_ids": row["doc_ids"],
            })

    # Dedupliquer par nom (un SubjectAnchor et ComparableSubject peuvent avoir le meme nom)
    seen = set()
    unique = []
    for s in sorted(subjects, key=lambda x: -x["claim_count"]):
        if s["name"] not in seen:
            seen.add(s["name"])
            unique.append(s)

    return unique


def analyze_subject_facets(session, tenant_id: str, subject_id: str, subject_type: str) -> dict:
    """Analyse la couverture facets pour un sujet donne."""

    # 1. Trouver les doc_ids du sujet
    if subject_type == "ComparableSubject":
        doc_result = session.run("""
            MATCH (cs:ComparableSubject {subject_id: $sid})
                  <-[:ABOUT_COMPARABLE]-(dc:DocumentContext)
            RETURN collect(DISTINCT dc.doc_id) AS doc_ids
        """, sid=subject_id)
    else:
        doc_result = session.run("""
            MATCH (sa:SubjectAnchor {subject_id: $sid})
                  <-[:ABOUT_SUBJECT]-(dc:DocumentContext)
            RETURN collect(DISTINCT dc.doc_id) AS doc_ids
        """, sid=subject_id)

    doc_ids = doc_result.single()["doc_ids"]
    if not doc_ids:
        return {
            "subject_id": subject_id,
            "total_claims": 0,
            "claims_with_facets": 0,
            "orphan_ratio": 1.0,
            "avg_facets_per_claim": 0.0,
            "top_facets": [],
            "facet_distribution": {},
            "doc_ids": [],
            "verdict": "NO_DATA",
        }

    # 2. Recuperer tous les claims de ces docs avec leurs facets
    result = session.run("""
        UNWIND $doc_ids AS did
        MATCH (c:Claim {tenant_id: $tid, doc_id: did})
        OPTIONAL MATCH (c)-[:BELONGS_TO_FACET]->(f:Facet)
        RETURN c.claim_id AS claim_id,
               c.text AS claim_text,
               c.claim_type AS claim_type,
               c.doc_id AS doc_id,
               collect(DISTINCT f.facet_name) AS facet_names,
               collect(DISTINCT f.facet_id) AS facet_ids
    """, doc_ids=doc_ids, tid=tenant_id)

    claims = [dict(r) for r in result]
    total_claims = len(claims)

    if total_claims == 0:
        return {
            "subject_id": subject_id,
            "total_claims": 0,
            "claims_with_facets": 0,
            "coverage_pct": 0.0,
            "orphan_ratio": 1.0,
            "avg_facets_per_claim": 0.0,
            "top_facets": [],
            "facet_distribution": {},
            "doc_ids": [],
            "doc_count": 0,
            "facet_groups_count": 0,
            "facet_groups_preview": {},
            "orphan_claims_count": 0,
            "orphan_claims_preview": [],
            "verdict": "NO_DATA",
            "recommended_weights": "N/A",
        }

    # 2. Compter les claims avec/sans facets
    claims_with_facets = sum(1 for c in claims if c["facet_names"])
    orphan_ratio = 1.0 - (claims_with_facets / total_claims)

    # 3. Distribution du nombre de facets par claim
    facets_per_claim = [len(c["facet_ids"]) for c in claims]
    avg_facets = sum(facets_per_claim) / total_claims

    # 4. Top facets
    facet_counter = Counter()
    for c in claims:
        for fn in c["facet_names"]:
            facet_counter[fn] += 1
    top_facets = facet_counter.most_common(10)

    # 5. Distribution par nombre de facets
    dist = Counter(facets_per_claim)
    facet_distribution = {str(k): v for k, v in sorted(dist.items())}

    # 6. Documents couverts
    doc_ids = list(set(c["doc_id"] for c in claims if c["doc_id"]))

    # 7. Clustering manuel : grouper les claims par facet dominante
    facet_groups = defaultdict(list)
    orphan_claims = []
    for c in claims:
        if c["facet_names"]:
            primary_facet = c["facet_names"][0]
            facet_groups[primary_facet].append(c["claim_text"][:120])
        else:
            orphan_claims.append(c["claim_text"][:120])

    # 8. Verdict
    coverage_pct = claims_with_facets / total_claims * 100
    if coverage_pct >= 75:
        verdict = "GO_NORMAL"
        recommended_weights = "facet_weight=0.5, embedding_weight=0.5"
    elif coverage_pct >= 60:
        verdict = "GO_PRUDENT"
        recommended_weights = "facet_weight=0.3, embedding_weight=0.7"
    else:
        verdict = "NO_GO_FACET_FIRST"
        recommended_weights = "facet_weight=0.0, embedding_weight=1.0"

    return {
        "subject_id": subject_id,
        "total_claims": total_claims,
        "claims_with_facets": claims_with_facets,
        "coverage_pct": round(coverage_pct, 1),
        "orphan_ratio": round(orphan_ratio, 3),
        "avg_facets_per_claim": round(avg_facets, 2),
        "top_facets": [{"name": n, "count": c} for n, c in top_facets],
        "facet_distribution": facet_distribution,
        "doc_ids": doc_ids,
        "doc_count": len(doc_ids),
        "facet_groups_count": len(facet_groups),
        "facet_groups_preview": {
            k: v[:3] for k, v in sorted(
                facet_groups.items(), key=lambda x: -len(x[1])
            )[:5]
        },
        "orphan_claims_count": len(orphan_claims),
        "orphan_claims_preview": orphan_claims[:5],
        "verdict": verdict,
        "recommended_weights": recommended_weights,
    }


def run_diagnostic(tenant_id: str = "default", top_n: int = 5):
    """Execute le diagnostic complet."""
    driver = get_neo4j_driver()

    with driver.session() as session:
        # 1. Contexte global
        r = session.run("MATCH (c:Claim {tenant_id: $tid}) RETURN count(c) AS cnt", tid=tenant_id)
        total_claims = r.single()["cnt"]
        r = session.run("MATCH (c:Claim {tenant_id: $tid})-[:BELONGS_TO_FACET]->(f:Facet) RETURN count(DISTINCT c) AS cnt", tid=tenant_id)
        total_with_facet = r.single()["cnt"]
        r = session.run("MATCH (f:Facet {tenant_id: $tid}) RETURN count(f) AS cnt", tid=tenant_id)
        total_facets = r.single()["cnt"]

        logger.info(f"{'='*70}")
        logger.info(f"DIAGNOSTIC FACETS — COUCHE PERSPECTIVE")
        logger.info(f"{'='*70}")
        logger.info(f"Tenant: {tenant_id}")
        logger.info(f"Claims totaux:         {total_claims}")
        logger.info(f"Claims avec facet:     {total_with_facet} ({total_with_facet/max(total_claims,1)*100:.1f}%)")
        logger.info(f"Facets totales:        {total_facets}")

        # Lister les sujets
        subjects = get_subjects(session, tenant_id)
        logger.info(f"Sujets avec >= 10 claims: {len(subjects)}")

        if not subjects:
            logger.info("Aucun ComparableSubject trouve. Verifiez le KG.")
            driver.close()
            return

        # Top N sujets par nombre de claims
        top_subjects = subjects[:top_n]
        logger.info(f"\nTop {len(top_subjects)} sujets par volume de claims:")
        for s in top_subjects:
            logger.info(f"  - {s['name']} [{s['subject_type']}] ({s['claim_count']} claims, {s['doc_count']} docs)")

        # 2. Analyser chaque sujet
        reports = []
        for s in top_subjects:
            logger.info(f"\n{'─'*60}")
            logger.info(f"SUJET: {s['name']} (id={s['subject_id']})")
            logger.info(f"{'─'*60}")

            report = analyze_subject_facets(session, tenant_id, s["subject_id"], s["subject_type"])
            report["subject_name"] = s["name"]
            reports.append(report)

            logger.info(f"  Claims totaux:      {report['total_claims']}")
            logger.info(f"  Claims avec facet:  {report['claims_with_facets']} ({report['coverage_pct']}%)")
            logger.info(f"  Orphelins:          {report['orphan_claims_count']} ({report['orphan_ratio']*100:.1f}%)")
            logger.info(f"  Avg facets/claim:   {report['avg_facets_per_claim']}")
            logger.info(f"  Documents:          {report['doc_count']}")
            logger.info(f"  Groupes facets:     {report['facet_groups_count']}")
            logger.info(f"  VERDICT:            {report['verdict']}")
            logger.info(f"  Poids recommandes:  {report['recommended_weights']}")

            if report["top_facets"]:
                logger.info(f"\n  Top facets:")
                for f in report["top_facets"][:5]:
                    logger.info(f"    - {f['name']} ({f['count']} claims)")

            if report["facet_groups_preview"]:
                logger.info(f"\n  Apercu des groupes (top 3 claims par groupe):")
                for group_name, claims_preview in report["facet_groups_preview"].items():
                    logger.info(f"    [{group_name}]")
                    for cp in claims_preview:
                        logger.info(f"      • {cp}")

            if report["orphan_claims_preview"]:
                logger.info(f"\n  Orphelins (apercu):")
                for oc in report["orphan_claims_preview"][:3]:
                    logger.info(f"      ? {oc}")

    driver.close()

    # 3. Verdict global
    logger.info(f"\n{'='*70}")
    logger.info("VERDICT GLOBAL")
    logger.info(f"{'='*70}")

    verdicts = [r["verdict"] for r in reports if r["total_claims"] > 0]
    coverages = [r["coverage_pct"] for r in reports if r["total_claims"] > 0]
    avg_coverage = sum(coverages) / len(coverages) if coverages else 0

    logger.info(f"  Couverture moyenne:  {avg_coverage:.1f}%")
    logger.info(f"  Verdicts par sujet:  {Counter(verdicts)}")

    if avg_coverage >= 75:
        global_verdict = "GO_NORMAL"
        logger.info(f"\n  >>> VERDICT: GO NORMAL — facet_weight=0.5, embedding_weight=0.5")
    elif avg_coverage >= 60:
        global_verdict = "GO_PRUDENT"
        logger.info(f"\n  >>> VERDICT: GO PRUDENT — facet_weight=0.3, embedding_weight=0.7")
    else:
        global_verdict = "NO_GO_FACET_FIRST"
        logger.info(f"\n  >>> VERDICT: NO-GO FACET-FIRST — basculer embedding-first (facet_weight=0.0)")

    # 4. Sauvegarder le rapport JSON
    full_report = {
        "tenant_id": tenant_id,
        "total_comparable_subjects": len(subjects),
        "analyzed_subjects": len(reports),
        "avg_coverage_pct": round(avg_coverage, 1),
        "global_verdict": global_verdict,
        "subjects": reports,
    }

    output_path = "diagnostic_facets_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2)
    logger.info(f"\n  Rapport sauvegarde: {output_path}")


if __name__ == "__main__":
    tenant = sys.argv[1] if len(sys.argv) > 1 else "default"
    run_diagnostic(tenant)
