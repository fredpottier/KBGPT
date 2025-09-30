#!/usr/bin/env python3
"""
Script pour corriger les noms de solutions SAP non-canoniques dans Qdrant.
Remplace "SAP Cloud ERP" et "SAP S/4HANA Cloud" par "SAP S/4HANA Cloud, Public Edition"

Usage:
    python scripts/fix_qdrant_solutions_names.py --dry-run  # Voir ce qui serait modifié
    python scripts/fix_qdrant_solutions_names.py           # Appliquer les modifications
"""

import argparse
import sys
from pathlib import Path

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowbase.common.clients import get_qdrant_client
from knowbase.config.settings import Settings
from knowbase.common.sap.normalizer import normalize_solution_name


def fix_solution_names(dry_run: bool = True):
    """Corrige les noms de solutions dans Qdrant."""

    settings = Settings()
    client = get_qdrant_client()

    collection_name = settings.qdrant_collection

    print(f"🔍 Scan de la collection '{collection_name}'...")
    print(f"Mode: {'DRY-RUN (aucune modification)' if dry_run else 'CORRECTION ACTIVE'}")
    print()

    # Noms problématiques à corriger
    problematic_names = ["SAP Cloud ERP", "SAP S/4HANA Cloud"]
    correct_name = "SAP S/4HANA Cloud, Public Edition"
    correct_id = "S4HANA_PUBLIC"

    # Statistiques
    stats = {
        "total_points": 0,
        "points_with_main_solution": 0,
        "points_corrected_main": 0,
        "points_corrected_supporting": 0,
        "points_corrected_mentioned": 0,
    }

    # Récupérer tous les points
    offset = None
    batch_size = 100

    while True:
        # Scroll par batch
        scroll_result = client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )

        points, next_offset = scroll_result

        if not points:
            break

        stats["total_points"] += len(points)

        for point in points:
            point_id = point.id
            payload = point.payload or {}

            modified = False
            new_payload = payload.copy()

            # Gérer la structure imbriquée solution{main, supporting, mentioned}
            solution_dict = payload.get("solution")
            if isinstance(solution_dict, dict):
                new_solution = solution_dict.copy()

                # Vérifier solution.main
                main_solution = solution_dict.get("main")
                if main_solution:
                    stats["points_with_main_solution"] += 1

                    if main_solution in problematic_names:
                        print(f"📝 Point {point_id}: solution.main '{main_solution}' → '{correct_name}'")
                        new_solution["main"] = correct_name
                        stats["points_corrected_main"] += 1
                        modified = True

                # Vérifier solution.supporting
                supporting = solution_dict.get("supporting", [])
                if supporting and isinstance(supporting, list):
                    new_supporting = []
                    supporting_modified = False

                    for sol in supporting:
                        if sol in problematic_names:
                            new_supporting.append(correct_name)
                            supporting_modified = True
                            print(f"📝 Point {point_id}: solution.supporting '{sol}' → '{correct_name}'")
                        else:
                            new_supporting.append(sol)

                    if supporting_modified:
                        # Dédupliquer
                        new_solution["supporting"] = list(set(new_supporting))
                        stats["points_corrected_supporting"] += 1
                        modified = True

                # Vérifier solution.mentioned
                mentioned = solution_dict.get("mentioned", [])
                if mentioned and isinstance(mentioned, list):
                    new_mentioned = []
                    mentioned_modified = False

                    for sol in mentioned:
                        if sol in problematic_names:
                            new_mentioned.append(correct_name)
                            mentioned_modified = True
                            print(f"📝 Point {point_id}: solution.mentioned '{sol}' → '{correct_name}'")
                        else:
                            new_mentioned.append(sol)

                    if mentioned_modified:
                        # Dédupliquer
                        new_solution["mentioned"] = list(set(new_mentioned))
                        stats["points_corrected_mentioned"] += 1
                        modified = True

                if modified:
                    new_payload["solution"] = new_solution

            # Appliquer les modifications si nécessaire
            if modified and not dry_run:
                client.set_payload(
                    collection_name=collection_name,
                    payload=new_payload,
                    points=[point_id]
                )

        # Offset pour le prochain batch
        if next_offset is None:
            break
        offset = next_offset

        print(f"  ... Traité {stats['total_points']} points")

    # Résumé
    print()
    print("=" * 60)
    print("📊 RÉSUMÉ")
    print("=" * 60)
    print(f"Total points scannés: {stats['total_points']}")
    print(f"Points avec main_solution: {stats['points_with_main_solution']}")
    print(f"Points corrigés (main_solution): {stats['points_corrected_main']}")
    print(f"Points corrigés (supporting_solutions): {stats['points_corrected_supporting']}")
    print(f"Points corrigés (mentioned_solutions): {stats['points_corrected_mentioned']}")
    print()

    total_corrections = (
        stats["points_corrected_main"] +
        stats["points_corrected_supporting"] +
        stats["points_corrected_mentioned"]
    )

    if dry_run:
        print(f"⚠️  MODE DRY-RUN: {total_corrections} corrections seraient appliquées")
        print("Relancer sans --dry-run pour appliquer les corrections")
    else:
        print(f"✅ {total_corrections} corrections appliquées avec succès!")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Corrige les noms de solutions SAP non-canoniques dans Qdrant"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode simulation: affiche ce qui serait modifié sans appliquer les changements"
    )

    args = parser.parse_args()

    try:
        stats = fix_solution_names(dry_run=args.dry_run)
        return 0
    except Exception as e:
        print(f"❌ Erreur: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())