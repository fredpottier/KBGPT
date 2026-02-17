#!/usr/bin/env python3
"""
Réparation rétroactive de l'ordonnancement des ApplicabilityAxis dans Neo4j.

Problème: Les axes accumulaient des known_values au fil des imports mais
l'AxisOrderInferrer n'était jamais re-déclenché après merge. Résultat:
value_order=None, is_orderable=false, ordering_confidence=unknown
même quand 2+ valeurs semver/numériques/années sont présentes.

Ce script relit les axes candidats, exécute AxisOrderInferrer.infer_order()
sur les known_values accumulées, et met à jour les propriétés d'ordonnancement.

Usage:
    # Mode dry-run (par défaut) — rapport sans modification
    docker-compose exec app python scripts/fix_axis_ordering.py

    # Mode exécution — corrige les axes
    docker-compose exec app python scripts/fix_axis_ordering.py --execute
"""

import argparse
import os
import sys

from neo4j import GraphDatabase


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def find_candidate_axes(driver):
    """
    Trouve les axes avec known_values >= 2 mais sans ordonnancement correct.

    Returns:
        Liste de dicts {axis_id, axis_key, known_values, is_orderable,
                        ordering_confidence, value_order}
    """
    query = """
    MATCH (ax:ApplicabilityAxis)
    WHERE size(coalesce(ax.known_values, [])) >= 2
      AND (
        ax.value_order IS NULL
        OR coalesce(ax.is_orderable, false) = false
        OR ax.ordering_confidence IN ['unknown', null]
      )
    RETURN ax.axis_id AS axis_id,
           ax.axis_key AS axis_key,
           ax.known_values AS known_values,
           ax.is_orderable AS is_orderable,
           ax.ordering_confidence AS ordering_confidence,
           ax.value_order AS value_order,
           ax.doc_count AS doc_count
    ORDER BY ax.axis_key
    """
    with driver.session() as session:
        result = session.run(query)
        return [dict(record) for record in result]


def find_already_ordered_axes(driver):
    """Trouve les axes déjà bien ordonnés (pour rapport)."""
    query = """
    MATCH (ax:ApplicabilityAxis)
    WHERE ax.value_order IS NOT NULL
      AND ax.is_orderable = true
      AND ax.ordering_confidence IN ['certain', 'inferred']
    RETURN ax.axis_id AS axis_id,
           ax.axis_key AS axis_key,
           ax.known_values AS known_values,
           ax.value_order AS value_order,
           ax.ordering_confidence AS confidence
    ORDER BY ax.axis_key
    """
    with driver.session() as session:
        result = session.run(query)
        return [dict(record) for record in result]


def fix_axis_ordering(driver, axis_id, order_result):
    """Met à jour un axe avec l'ordonnancement inféré."""
    query = """
    MATCH (ax:ApplicabilityAxis {axis_id: $axis_id})
    SET ax.is_orderable = $is_orderable,
        ax.order_type = $order_type,
        ax.ordering_confidence = $ordering_confidence,
        ax.value_order = $value_order
    RETURN ax.axis_id AS axis_id
    """
    with driver.session() as session:
        session.run(
            query,
            axis_id=axis_id,
            is_orderable=order_result.is_orderable,
            order_type=order_result.order_type.value,
            ordering_confidence=order_result.confidence.value,
            value_order=order_result.inferred_order,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Corrige l'ordonnancement des ApplicabilityAxis existants"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Applique les corrections (sans ce flag = dry-run)",
    )
    args = parser.parse_args()

    # Import tardif pour pouvoir tourner dans le container
    try:
        from knowbase.claimfirst.axes.axis_order_inferrer import AxisOrderInferrer
    except ImportError:
        # Fallback: ajouter src/ au path
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
        from knowbase.claimfirst.axes.axis_order_inferrer import AxisOrderInferrer

    driver = get_neo4j_driver()
    inferrer = AxisOrderInferrer()

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Fix Axis Ordering — Mode {mode}")
    print(f"{'='*60}\n")

    # 1. Rapport des axes déjà ordonnés
    ordered = find_already_ordered_axes(driver)
    print(f"Axes déjà ordonnés correctement: {len(ordered)}")
    for ax in ordered:
        print(f"  ✓ {ax['axis_key']}: {ax['value_order']} ({ax['confidence']})")

    # 2. Trouver les candidats
    candidates = find_candidate_axes(driver)
    print(f"\nAxes candidats à correction: {len(candidates)}")

    if not candidates:
        print("\nAucun axe à corriger.")
        driver.close()
        return

    # 3. Inférer et (optionnel) appliquer
    fixed = 0
    abstained = 0
    strategies_used = {}

    for ax in candidates:
        axis_id = ax["axis_id"]
        axis_key = ax["axis_key"]
        known_values = ax["known_values"] or []

        print(f"\n  Axe: {axis_key} (id={axis_id})")
        print(f"    known_values: {known_values}")
        print(f"    état actuel: is_orderable={ax['is_orderable']}, "
              f"confidence={ax['ordering_confidence']}, "
              f"value_order={ax['value_order']}")

        order_result = inferrer.infer_order(
            axis_key=axis_key,
            values=known_values,
        )

        if order_result.is_orderable and order_result.inferred_order:
            # Vérification: set(value_order) == set(known_values)
            if set(order_result.inferred_order) != set(known_values):
                print(f"    ⚠ SKIP: value_order != known_values "
                      f"({set(order_result.inferred_order)} vs {set(known_values)})")
                abstained += 1
                continue

            strategy = order_result.reason
            strategies_used[strategy] = strategies_used.get(strategy, 0) + 1

            print(f"    → ORDERABLE: {order_result.inferred_order} "
                  f"({order_result.confidence.value}, {strategy})")

            if args.execute:
                fix_axis_ordering(driver, axis_id, order_result)
                print(f"    ✓ CORRIGÉ")
            else:
                print(f"    (dry-run, pas de modification)")

            fixed += 1
        else:
            print(f"    → ABSTAIN: {order_result.reason}")
            abstained += 1

    # 4. Résumé
    print(f"\n{'='*60}")
    print(f"  RÉSUMÉ")
    print(f"{'='*60}")
    print(f"  Axes analysés:  {len(candidates)}")
    print(f"  Corrigés:       {fixed}")
    print(f"  Abstentions:    {abstained}")
    print(f"  Stratégies:")
    for strategy, count in sorted(strategies_used.items()):
        print(f"    {strategy}: {count}")

    if not args.execute and fixed > 0:
        print(f"\n  ℹ Pour appliquer: ajouter --execute")

    driver.close()


if __name__ == "__main__":
    main()
