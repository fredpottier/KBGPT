#!/usr/bin/env python3
"""
P2: Detect Fragmented Concepts - Diagnostic Tool

Detecte les concepts fragmentes dans le KG:
- "Application Load Balancer" vs "Load Balancer"
- "SAP S/4HANA Cloud" vs "S/4HANA"

Fournit un rapport avec recommendations (merge vs SUBTYPE_OF).

Usage:
    python scripts/detect_fragmented_concepts.py                    # Analyse
    python scripts/detect_fragmented_concepts.py --fix              # Propose fixes
    python scripts/detect_fragmented_concepts.py --run-er           # Lance ER pipeline

Author: Claude Code
Date: 2026-01-07
Ref: doc/ongoing/ANALYSE_ECHEC_KG_FIRST_TEST.md
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from neo4j import GraphDatabase
from knowbase.config.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class FragmentCandidate:
    """Un candidat de fragmentation detecte."""
    short_name: str
    long_name: str
    short_id: str
    long_id: str
    short_relations: int
    long_relations: int
    similarity_type: str  # "containment" ou "embedding"
    recommendation: str  # "MERGE", "SUBTYPE_OF", "KEEP_SEPARATE"
    reason: str


@dataclass
class DetectionStats:
    """Statistiques de detection."""
    concepts_analyzed: int = 0
    containment_pairs: int = 0
    fragments_detected: int = 0
    merge_recommendations: int = 0
    subtype_recommendations: int = 0
    keep_separate: int = 0
    candidates: List[FragmentCandidate] = field(default_factory=list)


def get_neo4j_driver():
    """Cree un driver Neo4j."""
    settings = get_settings()
    return GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )


def detect_name_containment(
    driver,
    tenant_id: str = "default",
    min_name_length: int = 3
) -> List[Tuple[Dict, Dict]]:
    """
    Detecte les paires de concepts ou un nom contient l'autre.

    Ex: "Application Load Balancer" contient "Load Balancer"
    """
    query = """
    MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
    MATCH (c2:CanonicalConcept {tenant_id: $tenant_id})
    WHERE c1.canonical_id < c2.canonical_id
      AND size(c1.canonical_name) >= $min_len
      AND size(c2.canonical_name) >= $min_len
      AND (
        c1.canonical_name CONTAINS c2.canonical_name
        OR c2.canonical_name CONTAINS c1.canonical_name
      )

    // Compter les relations de chaque concept
    OPTIONAL MATCH (c1)-[r1]-(other1:CanonicalConcept)
    WHERE NOT type(r1) IN ['INSTANCE_OF', 'MERGED_INTO', 'CO_OCCURS']
    WITH c1, c2, count(DISTINCT r1) AS c1_rels

    OPTIONAL MATCH (c2)-[r2]-(other2:CanonicalConcept)
    WHERE NOT type(r2) IN ['INSTANCE_OF', 'MERGED_INTO', 'CO_OCCURS']

    RETURN
        c1.canonical_name AS name1,
        c1.canonical_id AS id1,
        c1.concept_type AS type1,
        c1_rels AS rels1,
        c2.canonical_name AS name2,
        c2.canonical_id AS id2,
        c2.concept_type AS type2,
        count(DISTINCT r2) AS rels2
    ORDER BY c1_rels + count(DISTINCT r2) DESC
    """

    with driver.session() as session:
        result = session.run(query, tenant_id=tenant_id, min_len=min_name_length)
        pairs = []
        for record in result:
            c1 = {
                "name": record["name1"],
                "id": record["id1"],
                "type": record["type1"],
                "relations": record["rels1"]
            }
            c2 = {
                "name": record["name2"],
                "id": record["id2"],
                "type": record["type2"],
                "relations": record["rels2"]
            }
            pairs.append((c1, c2))
        return pairs


def analyze_pair(c1: Dict, c2: Dict) -> FragmentCandidate:
    """
    Analyse une paire de concepts et recommande une action.
    """
    # Determiner lequel est le "short" et le "long"
    if len(c1["name"]) <= len(c2["name"]):
        short, long = c1, c2
    else:
        short, long = c2, c1

    # Logique de recommendation
    short_has_rels = short["relations"] > 0
    long_has_rels = long["relations"] > 0

    # Verifier si c'est une vraie containment (pas juste un mot commun)
    short_words = set(short["name"].lower().split())
    long_words = set(long["name"].lower().split())

    if not short_words.issubset(long_words):
        # Pas une vraie containment, juste un mot en commun
        return FragmentCandidate(
            short_name=short["name"],
            long_name=long["name"],
            short_id=short["id"],
            long_id=long["id"],
            short_relations=short["relations"],
            long_relations=long["relations"],
            similarity_type="partial_overlap",
            recommendation="KEEP_SEPARATE",
            reason="Overlap partiel, pas de containment complete"
        )

    # Cas 1: Short a des relations, Long n'en a pas -> MERGE Long into Short
    if short_has_rels and not long_has_rels:
        return FragmentCandidate(
            short_name=short["name"],
            long_name=long["name"],
            short_id=short["id"],
            long_id=long["id"],
            short_relations=short["relations"],
            long_relations=long["relations"],
            similarity_type="containment",
            recommendation="MERGE",
            reason=f"'{long['name']}' -> '{short['name']}' (short a {short['relations']} rels)"
        )

    # Cas 2: Les deux ont des relations -> SUBTYPE_OF
    if short_has_rels and long_has_rels:
        return FragmentCandidate(
            short_name=short["name"],
            long_name=long["name"],
            short_id=short["id"],
            long_id=long["id"],
            short_relations=short["relations"],
            long_relations=long["relations"],
            similarity_type="containment",
            recommendation="SUBTYPE_OF",
            reason=f"'{long['name']}' SUBTYPE_OF '{short['name']}' (les deux ont des rels)"
        )

    # Cas 3: Ni l'un ni l'autre n'a de relations -> MERGE (moins important)
    if not short_has_rels and not long_has_rels:
        return FragmentCandidate(
            short_name=short["name"],
            long_name=long["name"],
            short_id=short["id"],
            long_id=long["id"],
            short_relations=short["relations"],
            long_relations=long["relations"],
            similarity_type="containment",
            recommendation="MERGE",
            reason=f"Aucun n'a de relations - merger '{long['name']}' -> '{short['name']}'"
        )

    # Cas 4: Long a des relations, Short n'en a pas -> inverser le merge
    return FragmentCandidate(
        short_name=short["name"],
        long_name=long["name"],
        short_id=short["id"],
        long_id=long["id"],
        short_relations=short["relations"],
        long_relations=long["relations"],
        similarity_type="containment",
        recommendation="MERGE_INVERSE",
        reason=f"'{short['name']}' -> '{long['name']}' (long a {long['relations']} rels)"
    )


def run_detection(tenant_id: str = "default") -> DetectionStats:
    """Execute la detection complete."""
    stats = DetectionStats()
    driver = get_neo4j_driver()

    try:
        # Detecter les paires par containment
        logger.info("Recherche des paires par name containment...")
        pairs = detect_name_containment(driver, tenant_id)
        stats.containment_pairs = len(pairs)

        logger.info(f"  {len(pairs)} paires detectees")

        # Analyser chaque paire
        for c1, c2 in pairs:
            stats.concepts_analyzed += 2
            candidate = analyze_pair(c1, c2)
            stats.candidates.append(candidate)

            if candidate.recommendation == "MERGE" or candidate.recommendation == "MERGE_INVERSE":
                stats.merge_recommendations += 1
                stats.fragments_detected += 1
            elif candidate.recommendation == "SUBTYPE_OF":
                stats.subtype_recommendations += 1
            else:
                stats.keep_separate += 1

        return stats

    finally:
        driver.close()


def print_report(stats: DetectionStats, show_all: bool = False):
    """Affiche le rapport de detection."""
    print("\n" + "=" * 70)
    print("  OSMOSE - DETECTION CONCEPTS FRAGMENTES")
    print("=" * 70)
    print(f"  Paires analysees:         {stats.containment_pairs}")
    print(f"  Fragments detectes:       {stats.fragments_detected}")
    print("-" * 70)
    print(f"  Recommendations MERGE:    {stats.merge_recommendations}")
    print(f"  Recommendations SUBTYPE:  {stats.subtype_recommendations}")
    print(f"  A garder separes:         {stats.keep_separate}")
    print("=" * 70)

    # Afficher les candidates prioritaires (MERGE)
    merge_candidates = [c for c in stats.candidates if "MERGE" in c.recommendation]

    if merge_candidates:
        print("\n[MERGE RECOMMANDES - Action prioritaire]")
        print("-" * 70)
        for c in merge_candidates[:20]:  # Top 20
            print(f"  {c.long_name}")
            print(f"    -> {c.short_name}")
            print(f"    Raison: {c.reason}")
            print()

    # Afficher SUBTYPE si demande
    if show_all:
        subtype_candidates = [c for c in stats.candidates if c.recommendation == "SUBTYPE_OF"]
        if subtype_candidates:
            print("\n[SUBTYPE_OF RECOMMANDES]")
            print("-" * 70)
            for c in subtype_candidates[:10]:
                print(f"  {c.long_name} SUBTYPE_OF {c.short_name}")
                print(f"    ({c.long_relations} rels / {c.short_relations} rels)")
                print()


def export_json(stats: DetectionStats, output_path: str):
    """Exporte les resultats en JSON."""
    data = {
        "summary": {
            "containment_pairs": stats.containment_pairs,
            "fragments_detected": stats.fragments_detected,
            "merge_recommendations": stats.merge_recommendations,
            "subtype_recommendations": stats.subtype_recommendations,
        },
        "candidates": [
            {
                "short_name": c.short_name,
                "long_name": c.long_name,
                "short_id": c.short_id,
                "long_id": c.long_id,
                "short_relations": c.short_relations,
                "long_relations": c.long_relations,
                "recommendation": c.recommendation,
                "reason": c.reason,
            }
            for c in stats.candidates
        ]
    }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nResultats exportes: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Detecte les concepts fragmentes dans le KG"
    )
    parser.add_argument(
        "--tenant",
        default="default",
        help="Tenant ID (default: default)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Afficher tous les resultats (MERGE + SUBTYPE)"
    )
    parser.add_argument(
        "--export",
        type=str,
        help="Exporter en JSON (chemin du fichier)"
    )
    parser.add_argument(
        "--run-er",
        action="store_true",
        help="Lancer le pipeline Entity Resolution apres detection"
    )

    args = parser.parse_args()

    # Detection
    stats = run_detection(args.tenant)
    print_report(stats, show_all=args.all)

    # Export JSON
    if args.export:
        export_json(stats, args.export)

    # Lancer ER si demande
    if args.run_er:
        print("\n" + "=" * 70)
        print("  LANCEMENT ENTITY RESOLUTION PIPELINE")
        print("=" * 70)
        import subprocess
        subprocess.run([
            sys.executable,
            str(Path(__file__).parent / "run_corpus_er.py"),
            "--tenant", args.tenant,
            "--dry-run"
        ])


if __name__ == "__main__":
    main()
