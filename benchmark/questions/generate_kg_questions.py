#!/usr/bin/env python3
"""
Generateur de questions depuis le Knowledge Graph (questions KG-derived).

Pour chaque tache, genere N questions avec ground truth
directement depuis les donnees Neo4j.

Usage:
    python benchmark/questions/generate_kg_questions.py --config benchmark/config.yaml
    python benchmark/questions/generate_kg_questions.py --config benchmark/config.yaml --task T1 --count 10
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("benchmark-questions")


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_neo4j_driver(config: dict):
    from neo4j import GraphDatabase

    neo4j_cfg = config["corpus"]["neo4j"]
    password = os.environ.get(neo4j_cfg["password_env"], "graphiti_neo4j_pass")
    return GraphDatabase.driver(
        neo4j_cfg["uri"],
        auth=(neo4j_cfg["user"], password),
    )


# ═══════════════════════════════════════════════════════════════════════
# TACHE 1 — Provenance & Citation
# ═══════════════════════════════════════════════════════════════════════


def generate_t1_provenance(driver, tenant_id: str, count: int, seed: int) -> List[Dict]:
    """Genere des questions de provenance depuis les claims du KG.

    Strategie : selectionner des claims avec verbatim, generer une question
    dont la reponse est le claim. Le ground truth = claim + verbatim + source.
    """
    random.seed(seed)

    with driver.session() as session:
        # Claims avec verbatim, lies a une entite (pour avoir un sujet)
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
            WHERE c.verbatim_quote IS NOT NULL AND c.verbatim_quote <> ''
              AND size(c.text) >= 40 AND size(c.text) <= 300
              AND e._hygiene_status IS NULL
            RETURN c.claim_id AS claim_id, c.text AS claim_text,
                   c.verbatim_quote AS verbatim, c.doc_id AS doc_id,
                   c.page_no AS page_no, c.claim_type AS claim_type,
                   e.name AS entity_name
            """,
            tid=tenant_id,
        )
        all_claims = [dict(r) for r in result]

    if len(all_claims) < count:
        logger.warning(f"T1: seulement {len(all_claims)} claims disponibles (demande: {count})")
        count = len(all_claims)

    selected = random.sample(all_claims, count)

    questions = []
    # Patterns de questions varies
    patterns = [
        "Que dit le corpus sur {entity} ?",
        "Quelle information est disponible concernant {entity} ?",
        "Que sait-on de {entity} dans la documentation ?",
        "Quel est le role de {entity} selon les documents ?",
        "Comment {entity} est-il decrit dans le corpus ?",
    ]

    for i, claim in enumerate(selected):
        pattern = patterns[i % len(patterns)]
        question = pattern.format(entity=claim["entity_name"])

        questions.append({
            "question_id": f"T1_KG_{i:04d}",
            "task": "T1_provenance",
            "source": "kg_derived",
            "question": question,
            "ground_truth": {
                "expected_claim": claim["claim_text"],
                "verbatim_quote": claim["verbatim"],
                "doc_id": claim["doc_id"],
                "page_no": claim["page_no"],
                "claim_id": claim["claim_id"],
                "entity_name": claim["entity_name"],
            },
            "grading_rules": {
                "citation_must_include_doc": claim["doc_id"],
                "answer_must_contain_fact": claim["claim_text"][:100],
                "verbatim_must_be_traceable": True,
            },
        })

    return questions


# ═══════════════════════════════════════════════════════════════════════
# TACHE 2 — Contradictions
# ═══════════════════════════════════════════════════════════════════════


def generate_t2_contradictions(driver, tenant_id: str, count: int, seed: int) -> List[Dict]:
    """Genere des questions sur les contradictions existantes dans le KG."""
    random.seed(seed)

    with driver.session() as session:
        result = session.run(
            """
            MATCH (c1:Claim {tenant_id: $tid})-[r:CONTRADICTS]-(c2:Claim)
            WHERE c1.claim_id < c2.claim_id
            OPTIONAL MATCH (c1)-[:ABOUT]->(e:Entity)
            WITH c1, c2, r, collect(DISTINCT e.name)[..3] AS entities
            RETURN c1.claim_id AS id1, c1.text AS text1, c1.doc_id AS doc1,
                   c1.verbatim_quote AS verbatim1,
                   c2.claim_id AS id2, c2.text AS text2, c2.doc_id AS doc2,
                   c2.verbatim_quote AS verbatim2,
                   coalesce(r.tension_nature, 'unclassified') AS tension_nature,
                   coalesce(r.tension_level, 'unknown') AS tension_level,
                   entities
            """,
            tid=tenant_id,
        )
        all_contradictions = [dict(r) for r in result]

    if not all_contradictions:
        logger.warning("T2: aucune contradiction trouvee dans le KG")
        return []

    # Si moins de contradictions que demande, dupliquer les questions avec des angles differents
    selected = []
    while len(selected) < count and all_contradictions:
        batch = random.sample(all_contradictions, min(count - len(selected), len(all_contradictions)))
        selected.extend(batch)

    questions = []
    patterns = [
        "Y a-t-il des informations contradictoires sur {topic} ?",
        "Les documents sont-ils coherents concernant {topic} ?",
        "Quelles tensions existent dans le corpus sur {topic} ?",
    ]

    for i, contra in enumerate(selected[:count]):
        topic = contra["entities"][0] if contra["entities"] else "ce sujet"
        pattern = patterns[i % len(patterns)]
        question = pattern.format(topic=topic)

        questions.append({
            "question_id": f"T2_KG_{i:04d}",
            "task": "T2_contradictions",
            "source": "kg_derived",
            "question": question,
            "ground_truth": {
                "claim1": {"id": contra["id1"], "text": contra["text1"],
                           "doc_id": contra["doc1"], "verbatim": contra["verbatim1"]},
                "claim2": {"id": contra["id2"], "text": contra["text2"],
                           "doc_id": contra["doc2"], "verbatim": contra["verbatim2"]},
                "tension_nature": contra["tension_nature"],
                "tension_level": contra["tension_level"],
                "entities": contra["entities"],
            },
            "grading_rules": {
                "must_surface_both_sides": True,
                "must_not_arbitrate_silently": True,
                "must_cite_both_sources": True,
                "expected_tension_type": contra["tension_nature"],
            },
        })

    return questions


# ═══════════════════════════════════════════════════════════════════════
# TACHE 3 — Temporal Drift
# ═══════════════════════════════════════════════════════════════════════


def generate_t3_temporal(driver, tenant_id: str, count: int, seed: int) -> List[Dict]:
    """Genere des questions sur la derive temporelle (versions)."""
    random.seed(seed)

    with driver.session() as session:
        # Entites presentes dans des docs avec des versions differentes
        result = session.run(
            """
            MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity)
            WHERE c.axis_release_id IS NOT NULL AND c.axis_release_id <> ''
              AND e._hygiene_status IS NULL
            WITH e.name AS entity, collect(DISTINCT c.axis_release_id) AS versions,
                 collect({text: c.text, version: c.axis_release_id, doc_id: c.doc_id})[..10] AS claims
            WHERE size(versions) >= 2
            RETURN entity, versions, claims
            """,
            tid=tenant_id,
        )
        all_temporal = [dict(r) for r in result]

    if not all_temporal:
        logger.warning("T3: aucune entite multi-version trouvee")
        return []

    selected = []
    while len(selected) < count and all_temporal:
        batch = random.sample(all_temporal, min(count - len(selected), len(all_temporal)))
        selected.extend(batch)

    questions = []
    patterns = [
        "Comment {entity} a-t-il evolue entre les versions {v1} et {v2} ?",
        "Quelles differences y a-t-il pour {entity} entre {v1} et {v2} ?",
        "{entity} fonctionne-t-il de la meme maniere en {v1} et {v2} ?",
    ]

    for i, temporal in enumerate(selected[:count]):
        versions = sorted(temporal["versions"])
        v1, v2 = versions[0], versions[-1]
        pattern = patterns[i % len(patterns)]
        question = pattern.format(entity=temporal["entity"], v1=v1, v2=v2)

        questions.append({
            "question_id": f"T3_KG_{i:04d}",
            "task": "T3_temporal",
            "source": "kg_derived",
            "question": question,
            "ground_truth": {
                "entity": temporal["entity"],
                "versions": versions,
                "claims_by_version": temporal["claims"],
            },
            "grading_rules": {
                "must_distinguish_versions": True,
                "must_not_mix_silently": True,
                "must_attribute_to_correct_version": True,
            },
        })

    return questions


# ═══════════════════════════════════════════════════════════════════════
# TACHE 4 — Audit & Completeness
# ═══════════════════════════════════════════════════════════════════════


def generate_t4_audit(driver, tenant_id: str, count: int, seed: int) -> List[Dict]:
    """Genere des requetes d'audit/export."""
    random.seed(seed)

    with driver.session() as session:
        # Entites avec beaucoup de claims (sujets riches)
        result = session.run(
            """
            MATCH (e:Entity {tenant_id: $tid})<-[:ABOUT]-(c:Claim)
            WHERE e._hygiene_status IS NULL
            WITH e, count(DISTINCT c) AS claim_count, count(DISTINCT c.doc_id) AS doc_count
            WHERE claim_count >= 5 AND doc_count >= 2
            OPTIONAL MATCH (c2:Claim)-[:ABOUT]->(e), (c2)-[r:CONTRADICTS]-(c3:Claim)
            WITH e, claim_count, doc_count, count(DISTINCT r) AS contradiction_count
            RETURN e.name AS entity, e.entity_id AS entity_id,
                   claim_count, doc_count, contradiction_count
            ORDER BY claim_count DESC
            LIMIT $limit
            """,
            tid=tenant_id,
            limit=count * 2,
        )
        all_entities = [dict(r) for r in result]

    selected = random.sample(all_entities, min(count, len(all_entities)))

    questions = []
    for i, entity in enumerate(selected):
        questions.append({
            "question_id": f"T4_KG_{i:04d}",
            "task": "T4_audit",
            "source": "kg_derived",
            "question": f"Exporte toutes les informations disponibles sur {entity['entity']}.",
            "ground_truth": {
                "entity": entity["entity"],
                "entity_id": entity["entity_id"],
                "expected_claim_count": entity["claim_count"],
                "expected_doc_count": entity["doc_count"],
                "expected_contradiction_count": entity["contradiction_count"],
            },
            "grading_rules": {
                "must_include_all_claims": True,
                "must_include_sources": True,
                "must_include_contradictions_if_exist": entity["contradiction_count"] > 0,
                "must_be_traceable_to_documents": True,
            },
        })

    return questions


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Generate KG-derived benchmark questions")
    parser.add_argument("--config", default="benchmark/config.yaml")
    parser.add_argument("--task", choices=["T1", "T2", "T3", "T4", "all"], default="all")
    parser.add_argument("--count", type=int, default=None, help="Override question count")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    tenant_id = config["corpus"]["tenant_id"]
    seed = config["questions"]["seed"]
    count = args.count or config["questions"]["per_task_kg"]
    output_dir = Path(args.output_dir or "benchmark/questions")
    output_dir.mkdir(parents=True, exist_ok=True)

    driver = get_neo4j_driver(config)

    generators = {
        "T1": ("task1_provenance_kg.json", generate_t1_provenance),
        "T2": ("task2_contradictions_kg.json", generate_t2_contradictions),
        "T3": ("task3_temporal_kg.json", generate_t3_temporal),
        "T4": ("task4_audit_kg.json", generate_t4_audit),
    }

    tasks = [args.task] if args.task != "all" else ["T1", "T2", "T3", "T4"]

    for task in tasks:
        filename, generator = generators[task]
        logger.info(f"Generating {task} questions ({count})...")

        questions = generator(driver, tenant_id, count, seed)

        output_path = output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "metadata": {
                    "task": task,
                    "source": "kg_derived",
                    "corpus": config["corpus"]["name"],
                    "count": len(questions),
                    "generated_at": datetime.utcnow().isoformat(),
                    "seed": seed,
                    "config": args.config,
                },
                "questions": questions,
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"  {task}: {len(questions)} questions -> {output_path}")

    driver.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
