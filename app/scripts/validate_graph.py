#!/usr/bin/env python3
"""
OSMOSE Navigation Layer - Graph Validation CLI

Valide la séparation entre couche navigation et couche sémantique.

Usage:
    python scripts/validate_graph.py
    python scripts/validate_graph.py --tenant production
    python scripts/validate_graph.py --verbose
    python scripts/validate_graph.py --stats

ADR: doc/ongoing/ADR_NAVIGATION_LAYER.md

Author: Claude Code
Date: 2026-01-01
"""

import argparse
import sys
import json

# Docker path
sys.path.insert(0, '/app')
# Local dev path
sys.path.insert(0, 'src')

from knowbase.navigation import validate_graph, GraphLinter


def main():
    parser = argparse.ArgumentParser(
        description="Valide le graphe OSMOSE (navigation vs sémantique)",
        epilog="""
Règles validées:
  NAV-001: Pas de navigation edges Concept→Concept
  NAV-002: Pas de sémantique vers ContextNode
  NAV-003: Pas de sémantique depuis ContextNode
  NAV-004: MENTIONED_IN a les propriétés requises

Retourne exit code 0 si succès, 1 si violations.
        """
    )
    parser.add_argument(
        "--tenant",
        default="default",
        help="Tenant ID (default: 'default')"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Afficher les détails des violations"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Afficher les statistiques de la Navigation Layer"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Sortie au format JSON"
    )

    args = parser.parse_args()

    # Exécuter la validation
    try:
        result = validate_graph(tenant_id=args.tenant)
    except Exception as e:
        print(f"Erreur de connexion Neo4j: {e}", file=sys.stderr)
        sys.exit(2)

    # Afficher les stats si demandé
    if args.stats:
        try:
            linter = GraphLinter(tenant_id=args.tenant)
            stats = linter.get_navigation_stats()

            if args.json:
                print(json.dumps({"stats": stats}, indent=2))
            else:
                print("\n=== Navigation Layer Statistics ===")
                for key, value in stats.items():
                    print(f"  {key}: {value}")
                print()

        except Exception as e:
            print(f"Erreur stats: {e}", file=sys.stderr)

    # Sortie JSON
    if args.json:
        output = result.to_dict()
        print(json.dumps(output, indent=2))
        sys.exit(0 if result.success else 1)

    # Sortie texte
    if result.success:
        print("✓ All lint rules passed!")
        print(f"  Rules checked: {len(result.stats)}")
        print(f"  Violations: 0")
        sys.exit(0)
    else:
        print(f"Found {len(result.violations)} violation(s):")
        print()

        for v in result.violations:
            severity_icon = "" if v.severity == "ERROR" else ""
            print(f"  [{v.rule_id.value}] {severity_icon} {v.message}")

            if args.verbose and v.details:
                for key, value in v.details.items():
                    print(f"      {key}: {value}")

        print()
        print("Run with --verbose for more details")
        sys.exit(1)


if __name__ == "__main__":
    main()
