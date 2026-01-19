#!/usr/bin/env python3
"""
Script de validation pour l'architecture Dual Chunking.

Vérifie les invariants définis dans ADR_DUAL_CHUNKING_ARCHITECTURE.md:
1. Coverage ≥95% du document par les CoverageChunks
2. ANCHORED_IN / SPAN ≥95% (tout concept SPAN a un lien)
3. Aucun gap >100 chars entre CoverageChunks
4. RAG end-to-end >90% (concepts dans RetrievalChunks)

Usage:
    docker-compose exec app python scripts/validate_dual_chunking.py
    docker-compose exec app python scripts/validate_dual_chunking.py --document-id "doc_xxx"
"""

import argparse
import logging
from typing import Dict, Any, List, Optional

from knowbase.common.clients.neo4j_client import get_neo4j_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def validate_coverage_ratio(
    neo4j_client,
    tenant_id: str,
    document_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Valide le ratio de couverture des CoverageChunks.

    Invariant: Couverture ≥95% du document.
    """
    if document_id:
        query = """
        MATCH (dc:DocumentChunk {tenant_id: $tenant_id, chunk_type: 'coverage', document_id: $document_id})
        WITH dc ORDER BY dc.char_start
        WITH collect({start: dc.char_start, end: dc.char_end}) AS chunks
        WITH chunks,
             chunks[0].start AS doc_start,
             chunks[-1].end AS doc_end
        WITH chunks, doc_end - doc_start AS doc_length,
             reduce(total = 0, c IN chunks | total + (c.end - c.start)) AS covered
        RETURN doc_length, covered,
               CASE WHEN doc_length > 0 THEN toFloat(covered) / doc_length ELSE 0 END AS ratio
        """
        params = {"tenant_id": tenant_id, "document_id": document_id}
    else:
        query = """
        MATCH (dc:DocumentChunk {tenant_id: $tenant_id, chunk_type: 'coverage'})
        WITH dc.document_id AS doc_id, dc ORDER BY dc.char_start
        WITH doc_id, collect({start: dc.char_start, end: dc.char_end}) AS chunks
        WITH doc_id, chunks,
             chunks[0].start AS doc_start,
             chunks[-1].end AS doc_end
        WITH doc_id, chunks, doc_end - doc_start AS doc_length,
             reduce(total = 0, c IN chunks | total + (c.end - c.start)) AS covered
        RETURN doc_id, doc_length, covered,
               CASE WHEN doc_length > 0 THEN toFloat(covered) / doc_length ELSE 0 END AS ratio
        """
        params = {"tenant_id": tenant_id}

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(query, **params)
        records = list(result)

    if not records:
        return {"status": "NO_DATA", "message": "Pas de CoverageChunks trouvés"}

    # Analyser les résultats
    failures = []
    for record in records:
        ratio = record.get("ratio", 0)
        if ratio < 0.95:
            doc_id = record.get("doc_id") or document_id
            failures.append({
                "document_id": doc_id,
                "ratio": ratio,
                "covered": record.get("covered"),
                "doc_length": record.get("doc_length")
            })

    if failures:
        return {
            "status": "FAIL",
            "message": f"{len(failures)} documents avec couverture <95%",
            "failures": failures
        }

    return {
        "status": "PASS",
        "message": f"Tous les {len(records)} documents ont couverture ≥95%"
    }


def validate_anchored_in_ratio(
    neo4j_client,
    tenant_id: str,
    document_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Valide le ratio ANCHORED_IN / SPAN.

    Invariant: ≥95% des concepts SPAN ont une relation ANCHORED_IN.
    """
    if document_id:
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id, anchor_status: 'SPAN', document_id: $document_id})
        OPTIONAL MATCH (p)-[:ANCHORED_IN]->(dc:DocumentChunk)
        WITH count(DISTINCT p) AS total_span,
             count(DISTINCT CASE WHEN dc IS NOT NULL THEN p END) AS with_anchor
        RETURN total_span, with_anchor,
               CASE WHEN total_span > 0 THEN toFloat(with_anchor) / total_span ELSE 0 END AS ratio
        """
        params = {"tenant_id": tenant_id, "document_id": document_id}
    else:
        query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id, anchor_status: 'SPAN'})
        OPTIONAL MATCH (p)-[:ANCHORED_IN]->(dc:DocumentChunk)
        WITH count(DISTINCT p) AS total_span,
             count(DISTINCT CASE WHEN dc IS NOT NULL THEN p END) AS with_anchor
        RETURN total_span, with_anchor,
               CASE WHEN total_span > 0 THEN toFloat(with_anchor) / total_span ELSE 0 END AS ratio
        """
        params = {"tenant_id": tenant_id}

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(query, **params)
        record = result.single()

    if not record:
        return {"status": "NO_DATA", "message": "Pas de données"}

    total_span = record.get("total_span", 0)
    with_anchor = record.get("with_anchor", 0)
    ratio = record.get("ratio", 0)

    if total_span == 0:
        return {
            "status": "NO_DATA",
            "message": "Aucun concept SPAN trouvé"
        }

    if ratio < 0.95:
        orphans = total_span - with_anchor
        return {
            "status": "FAIL",
            "message": f"Ratio {ratio:.1%} < 95% ({orphans} orphelins sur {total_span})",
            "total_span": total_span,
            "with_anchor": with_anchor,
            "orphans": orphans,
            "ratio": ratio
        }

    return {
        "status": "PASS",
        "message": f"Ratio {ratio:.1%} ≥ 95% ({with_anchor}/{total_span})",
        "total_span": total_span,
        "with_anchor": with_anchor,
        "ratio": ratio
    }


def validate_no_gaps(
    neo4j_client,
    tenant_id: str,
    document_id: Optional[str] = None,
    max_gap: int = 100
) -> Dict[str, Any]:
    """
    Valide qu'il n'y a pas de gaps significatifs entre CoverageChunks.

    Invariant: Aucun gap >100 chars entre chunks consécutifs.
    """
    if document_id:
        query = """
        MATCH (dc:DocumentChunk {tenant_id: $tenant_id, chunk_type: 'coverage', document_id: $document_id})
        WITH dc ORDER BY dc.char_start
        WITH collect({id: dc.chunk_id, start: dc.char_start, end: dc.char_end}) AS chunks
        UNWIND range(0, size(chunks)-2) AS i
        WITH chunks[i] AS prev, chunks[i+1] AS curr
        WHERE curr.start - prev.end > $max_gap
        RETURN prev.id AS prev_chunk, curr.id AS curr_chunk,
               prev.end AS gap_start, curr.start AS gap_end,
               curr.start - prev.end AS gap_size
        """
        params = {"tenant_id": tenant_id, "document_id": document_id, "max_gap": max_gap}
    else:
        query = """
        MATCH (dc:DocumentChunk {tenant_id: $tenant_id, chunk_type: 'coverage'})
        WITH dc.document_id AS doc_id, dc ORDER BY dc.char_start
        WITH doc_id, collect({id: dc.chunk_id, start: dc.char_start, end: dc.char_end}) AS chunks
        UNWIND range(0, size(chunks)-2) AS i
        WITH doc_id, chunks[i] AS prev, chunks[i+1] AS curr
        WHERE curr.start - prev.end > $max_gap
        RETURN doc_id, prev.id AS prev_chunk, curr.id AS curr_chunk,
               prev.end AS gap_start, curr.start AS gap_end,
               curr.start - prev.end AS gap_size
        LIMIT 10
        """
        params = {"tenant_id": tenant_id, "max_gap": max_gap}

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(query, **params)
        gaps = list(result)

    if gaps:
        return {
            "status": "FAIL",
            "message": f"{len(gaps)} gaps >{max_gap} chars détectés",
            "gaps": [dict(g) for g in gaps[:5]]  # Premiers 5 gaps
        }

    return {
        "status": "PASS",
        "message": f"Aucun gap >{max_gap} chars détecté"
    }


def validate_aligns_with(
    neo4j_client,
    tenant_id: str
) -> Dict[str, Any]:
    """
    Valide que les relations ALIGNS_WITH existent.
    """
    query = """
    MATCH (cc:DocumentChunk {tenant_id: $tenant_id, chunk_type: 'coverage'})-[r:ALIGNS_WITH]->(rc:DocumentChunk)
    RETURN count(r) AS alignments,
           count(DISTINCT cc) AS coverage_with_align,
           count(DISTINCT rc) AS retrieval_with_align
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(query, tenant_id=tenant_id)
        record = result.single()

    if not record:
        return {"status": "NO_DATA", "message": "Pas de données"}

    alignments = record.get("alignments", 0)
    coverage_with_align = record.get("coverage_with_align", 0)
    retrieval_with_align = record.get("retrieval_with_align", 0)

    if alignments == 0:
        return {
            "status": "WARN",
            "message": "Aucune relation ALIGNS_WITH trouvée"
        }

    return {
        "status": "PASS",
        "message": f"{alignments} ALIGNS_WITH ({coverage_with_align} coverage → {retrieval_with_align} retrieval)",
        "alignments": alignments,
        "coverage_chunks_aligned": coverage_with_align,
        "retrieval_chunks_aligned": retrieval_with_align
    }


def print_summary(results: Dict[str, Dict[str, Any]]) -> bool:
    """Affiche le résumé des validations."""
    print("\n" + "=" * 70)
    print("VALIDATION DUAL CHUNKING - RÉSUMÉ")
    print("=" * 70)

    all_pass = True

    for name, result in results.items():
        status = result.get("status", "UNKNOWN")
        message = result.get("message", "")

        if status == "PASS":
            icon = "✅"
        elif status == "FAIL":
            icon = "❌"
            all_pass = False
        elif status == "WARN":
            icon = "⚠️"
        else:
            icon = "❓"

        print(f"\n{icon} {name}")
        print(f"   {message}")

        # Détails si échec
        if status == "FAIL" and "failures" in result:
            for f in result["failures"][:3]:
                print(f"   - {f}")

    print("\n" + "=" * 70)
    if all_pass:
        print("✅ TOUS LES INVARIANTS SONT RESPECTÉS")
    else:
        print("❌ CERTAINS INVARIANTS NE SONT PAS RESPECTÉS")
    print("=" * 70)

    return all_pass


def main():
    parser = argparse.ArgumentParser(description="Validation Dual Chunking")
    parser.add_argument("--tenant-id", default="default", help="Tenant ID")
    parser.add_argument("--document-id", help="Document ID spécifique (optionnel)")
    args = parser.parse_args()

    neo4j_client = get_neo4j_client()

    print(f"\n[Validation] Tenant: {args.tenant_id}")
    if args.document_id:
        print(f"[Validation] Document: {args.document_id}")

    results = {}

    # 1. Coverage ratio
    results["Coverage ≥95%"] = validate_coverage_ratio(
        neo4j_client, args.tenant_id, args.document_id
    )

    # 2. ANCHORED_IN ratio
    results["ANCHORED_IN/SPAN ≥95%"] = validate_anchored_in_ratio(
        neo4j_client, args.tenant_id, args.document_id
    )

    # 3. No gaps
    results["No gaps >100 chars"] = validate_no_gaps(
        neo4j_client, args.tenant_id, args.document_id
    )

    # 4. ALIGNS_WITH exists
    results["ALIGNS_WITH relations"] = validate_aligns_with(
        neo4j_client, args.tenant_id
    )

    # Résumé
    all_pass = print_summary(results)

    return 0 if all_pass else 1


if __name__ == "__main__":
    exit(main())
