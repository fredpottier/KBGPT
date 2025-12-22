#!/usr/bin/env python3
"""
Script de backup Neo4j vers JSON.

Exporte tous les noeuds et relations du tenant 'default' en fichiers JSON
pour pouvoir les restaurer plus tard.

Usage:
    docker-compose exec app python /app/scripts/backup_neo4j.py [--output-dir /data/backups]
"""

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from neo4j import GraphDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Neo4j Configuration
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")


def export_nodes(session, label: str) -> List[Dict[str, Any]]:
    """Exporte tous les noeuds d'un label donné."""
    query = f"""
    MATCH (n:{label})
    WHERE n.tenant_id = 'default' OR n.tenant_id IS NULL
    RETURN n, labels(n) as labels, elementId(n) as element_id
    """
    result = session.run(query)

    nodes = []
    for record in result:
        node = dict(record["n"])
        node["_labels"] = record["labels"]
        node["_element_id"] = record["element_id"]
        # Convertir datetime en string
        for key, value in node.items():
            if hasattr(value, 'isoformat'):
                node[key] = value.isoformat()
        nodes.append(node)

    return nodes


def export_relationships(session, rel_type: str) -> List[Dict[str, Any]]:
    """Exporte toutes les relations d'un type donné."""
    query = f"""
    MATCH (s)-[r:{rel_type}]->(t)
    WHERE (s.tenant_id = 'default' OR NOT exists(s.tenant_id))
    RETURN
        elementId(s) as source_id,
        elementId(t) as target_id,
        type(r) as rel_type,
        properties(r) as props
    """
    result = session.run(query)

    relationships = []
    for record in result:
        rel = {
            "source_id": record["source_id"],
            "target_id": record["target_id"],
            "type": record["rel_type"],
            "properties": dict(record["props"]) if record["props"] else {}
        }
        # Convertir datetime en string
        for key, value in rel["properties"].items():
            if hasattr(value, 'isoformat'):
                rel["properties"][key] = value.isoformat()
        relationships.append(rel)

    return relationships


def get_all_labels(session) -> List[str]:
    """Récupère tous les labels de noeuds."""
    result = session.run("CALL db.labels() YIELD label RETURN label")
    return [record["label"] for record in result]


def get_all_relationship_types(session) -> List[str]:
    """Récupère tous les types de relations."""
    result = session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")
    return [record["relationshipType"] for record in result]


def main():
    parser = argparse.ArgumentParser(description="Backup Neo4j to JSON")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="/data/backups",
        help="Output directory for backup files"
    )
    args = parser.parse_args()

    # Créer le répertoire de sortie
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Timestamp pour le backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = output_dir / f"neo4j_backup_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"=== Neo4j Backup to {backup_dir} ===")

    # Connexion
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    logger.info(f"Connected to {NEO4J_URI}")

    stats = {"nodes": {}, "relationships": {}}

    with driver.session() as session:
        # Exporter les labels
        labels = get_all_labels(session)
        logger.info(f"Found {len(labels)} node labels: {labels}")

        # Exporter chaque type de noeud
        all_nodes = {}
        for label in labels:
            nodes = export_nodes(session, label)
            if nodes:
                all_nodes[label] = nodes
                stats["nodes"][label] = len(nodes)
                logger.info(f"  Exported {len(nodes)} {label} nodes")

        # Sauvegarder les noeuds
        nodes_file = backup_dir / "nodes.json"
        with open(nodes_file, "w", encoding="utf-8") as f:
            json.dump(all_nodes, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved nodes to {nodes_file}")

        # Exporter les relations
        rel_types = get_all_relationship_types(session)
        logger.info(f"Found {len(rel_types)} relationship types: {rel_types}")

        all_relationships = {}
        for rel_type in rel_types:
            rels = export_relationships(session, rel_type)
            if rels:
                all_relationships[rel_type] = rels
                stats["relationships"][rel_type] = len(rels)
                logger.info(f"  Exported {len(rels)} {rel_type} relationships")

        # Sauvegarder les relations
        rels_file = backup_dir / "relationships.json"
        with open(rels_file, "w", encoding="utf-8") as f:
            json.dump(all_relationships, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved relationships to {rels_file}")

    # Sauvegarder les stats
    stats_file = backup_dir / "stats.json"
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "neo4j_uri": NEO4J_URI,
            "stats": stats,
            "total_nodes": sum(stats["nodes"].values()),
            "total_relationships": sum(stats["relationships"].values())
        }, f, ensure_ascii=False, indent=2)

    driver.close()

    # Résumé
    logger.info("\n" + "=" * 60)
    logger.info("BACKUP COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Location: {backup_dir}")
    logger.info(f"Total nodes: {sum(stats['nodes'].values())}")
    logger.info(f"Total relationships: {sum(stats['relationships'].values())}")
    for label, count in stats["nodes"].items():
        logger.info(f"  - {label}: {count} nodes")
    for rel_type, count in stats["relationships"].items():
        logger.info(f"  - {rel_type}: {count} relationships")


if __name__ == "__main__":
    main()
