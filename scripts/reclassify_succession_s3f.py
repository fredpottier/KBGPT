#!/usr/bin/env python3
"""S3.F-4 — Re-classifier les paires de succession régulatoire avec Domain Pack hints.

Stratégie ciblée (V3.3-conforming) :
1. Pour chaque paire de docs (doc_old, doc_new) connue de la metadata du corpus,
   identifier les claims "smoking gun" : claims dans doc_new qui mentionnent
   l'identifiant canonique de doc_old.
2. Pour chaque claim pointer, identifier l'anchor de doc_old : claim de doc_old
   qui contient son propre identifiant canonique (preamble/scope/article central).
3. Lancer le 12-class classifier avec les hints aerospace_compliance injectés.
4. Persister les nouvelles relations LOGICAL_RELATION (focus SUPERSEDES,
   REAFFIRMS, EVOLVES_FROM).

Note V3.3 : la recherche substring sur l'identifiant canonique (ex: '428/2009',
'2021/821', 'Amendment 27') n'est PAS un anti-pattern lexical — c'est une
identification de référence structurée (équivalent d'un cross-reference key),
pas une heuristique sémantique de langage. Le LLM reste l'unique moteur de
classification.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

from knowbase.domain_packs.manifest import get_classifier_hints
from knowbase.relations.logical_relation_classifier import LogicalRelationClassifier
from knowbase.relations.v33_types import (
    LogicalRelationType,
    RelationStrength,
    ScopeRelation,
    TemporalRelation,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("S3F-4")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
VLLM_URL = os.getenv("VLLM_URL", "http://3.79.236.241:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")


# ============================================================================
# Paires de succession connues (metadata corpus, pas du langage interprété)
# ============================================================================

# Format : (doc_old, identifier_old, doc_new, identifier_new)
# Les "identifiers" sont les références canoniques utilisées dans les textes
# (ex: "428/2009" pour Council Regulation (EC) No 428/2009).

SUCCESSION_PAIRS = [
    # Dual-use export controls
    (
        "dualuse_reg_428_2009_original_372b7ac3", "428/2009",
        "dualuse_reg_2021_821_original_65eef5dc", "2021/821",
    ),
    (
        "dualuse_reg_2021_821_original_65eef5dc", "2021/821",
        "dualuse_del_2023_66_cdc2b691", "2023/66",
    ),
    (
        "dualuse_reg_2021_821_original_65eef5dc", "2021/821",
        "dualuse_del_2023_996_3616a044", "2023/996",
    ),
    (
        "dualuse_reg_2021_821_original_65eef5dc", "2021/821",
        "dualuse_del_2024_2547_cb08f84b", "2024/2547",
    ),
    (
        "dualuse_reg_2021_821_original_65eef5dc", "2021/821",
        "dualuse_del_2024_2025_908a03cf", "2024/2025",
    ),
    # CS-25 amendments successifs (pour REAFFIRMS / EVOLVES_FROM detection)
    ("cs25_amdt_22_8e69026c", "Amendment 22", "cs25_amdt_23_0869bab2", "Amendment 23"),
    ("cs25_amdt_23_0869bab2", "Amendment 23", "cs25_amdt_24_86b11545", "Amendment 24"),
    ("cs25_amdt_24_86b11545", "Amendment 24", "cs25_amdt_25_a41bdc85", "Amendment 25"),
    ("cs25_amdt_25_a41bdc85", "Amendment 25", "cs25_amdt_26_6450b31e", "Amendment 26"),
    ("cs25_amdt_26_6450b31e", "Amendment 26", "cs25_amdt_27_992260a7", "Amendment 27"),
    ("cs25_amdt_27_992260a7", "Amendment 27", "cs25_amdt_28_32f1a9ac", "Amendment 28"),
]


# ============================================================================
# Mining des paires "smoking gun"
# ============================================================================


def find_pointer_claims(driver, doc_new: str, identifier_old: str, limit: int = 10) -> list[dict]:
    """Claims dans doc_new qui mentionnent l'identifiant canonique de doc_old.

    Note : substring match sur identifier canonique (ID structurée), pas sur
    du langage. Pas un anti-pattern lexical.
    """
    with driver.session() as s:
        rows = s.run(
            """
            MATCH (c:Claim)
            WHERE c.tenant_id = 'default' AND c.doc_id = $doc
              AND c.text CONTAINS $ident
            RETURN c.claim_id AS claim_id, c.text AS text, c.publication_date AS pub
            ORDER BY size(c.text) ASC
            LIMIT $lim
            """,
            doc=doc_new, ident=identifier_old, lim=limit,
        ).data()
    return rows


def find_anchor_claim(driver, doc_id: str, identifier: str) -> dict | None:
    """Anchor d'un doc : claim contenant son propre identifiant canonique
    avec le texte le plus court (probablement preamble/scope)."""
    with driver.session() as s:
        rows = s.run(
            """
            MATCH (c:Claim)
            WHERE c.tenant_id = 'default' AND c.doc_id = $doc
              AND c.text CONTAINS $ident
            RETURN c.claim_id AS claim_id, c.text AS text, c.publication_date AS pub
            ORDER BY size(c.text) ASC
            LIMIT 1
            """,
            doc=doc_id, ident=identifier,
        ).data()
    return rows[0] if rows else None


def find_anchor_via_neo4j_first_claim(driver, doc_id: str) -> dict | None:
    """Fallback : si aucun anchor trouvé via identifier, prendre simplement
    le premier claim alphabétique du doc (souvent le préambule)."""
    with driver.session() as s:
        rows = s.run(
            """
            MATCH (c:Claim)
            WHERE c.tenant_id = 'default' AND c.doc_id = $doc
            RETURN c.claim_id AS claim_id, c.text AS text, c.publication_date AS pub
            ORDER BY c.claim_id ASC
            LIMIT 1
            """,
            doc=doc_id,
        ).data()
    return rows[0] if rows else None


# ============================================================================
# Persistence
# ============================================================================


def relation_already_exists(driver, a_claim_id: str, b_claim_id: str, type_: str) -> bool:
    """Skip si la relation existe déjà (idempotent)."""
    with driver.session() as s:
        row = s.run(
            """
            MATCH (a:Claim {claim_id: $a})-[r:LOGICAL_RELATION {type: $t}]->(b:Claim {claim_id: $b})
            WHERE coalesce(r.legacy, false) = false
            RETURN count(r) AS n
            """,
            a=a_claim_id, b=b_claim_id, t=type_,
        ).single()
    return (row["n"] or 0) > 0


def persist_relation(
    driver,
    a_claim_id: str,
    b_claim_id: str,
    relation_type: str,
    strength: str,
    confidence: float,
    reasoning: str,
    derivation_path: str,
):
    """Crée une LOGICAL_RELATION non-legacy entre deux claims."""
    with driver.session() as s:
        s.run(
            """
            MATCH (a:Claim {claim_id: $a, tenant_id: 'default'}),
                  (b:Claim {claim_id: $b, tenant_id: 'default'})
            MERGE (a)-[r:LOGICAL_RELATION {type: $t}]->(b)
            ON CREATE SET
              r.strength = $strength,
              r.confidence = $confidence,
              r.is_contradiction = ($t = 'CONFLICT'),
              r.reasoning = $reasoning,
              r.derivation_path = $derivation_path,
              r.derived = false,
              r.legacy = false,
              r.model_id = $model_id,
              r.extracted_at = datetime()
            ON MATCH SET
              r.confidence = CASE WHEN r.confidence < $confidence THEN $confidence ELSE r.confidence END
            """,
            a=a_claim_id, b=b_claim_id, t=relation_type,
            strength=strength, confidence=confidence,
            reasoning=reasoning[:2000],
            derivation_path=derivation_path,
            model_id=VLLM_MODEL,
        )


# ============================================================================
# Main
# ============================================================================


def main() -> int:
    # Charger les hints du pack aerospace_compliance (couvre le corpus actuel)
    hints = get_classifier_hints("aerospace_compliance")
    logger.info(f"Loaded {len(hints)} classifier_hints from aerospace_compliance pack.")

    classifier = LogicalRelationClassifier(vllm_url=VLLM_URL, model=VLLM_MODEL, timeout_s=60.0)
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    audit = {
        "timestamp_start": datetime.utcnow().isoformat() + "Z",
        "succession_pairs_processed": [],
        "relations_persisted": [],
        "relations_skipped_already_exist": 0,
        "relations_unrelated": 0,
        "errors": [],
    }

    try:
        for doc_old, ident_old, doc_new, ident_new in SUCCESSION_PAIRS:
            logger.info(f"=== {doc_old[:35]}({ident_old}) → {doc_new[:35]}({ident_new}) ===")
            pair_audit = {
                "doc_old": doc_old, "ident_old": ident_old,
                "doc_new": doc_new, "ident_new": ident_new,
                "n_pointers": 0, "n_classified": 0, "n_persisted": 0,
                "relations_by_type": {},
            }

            # 1. Anchor du doc_old (claim "central" qui définit son scope)
            anchor_old = find_anchor_claim(driver, doc_old, ident_old)
            if not anchor_old:
                anchor_old = find_anchor_via_neo4j_first_claim(driver, doc_old)
            if not anchor_old:
                logger.warning(f"  Aucun claim trouvé dans {doc_old}, skip")
                continue

            # 2. Pointer claims dans doc_new (mentionnent ident_old)
            pointers = find_pointer_claims(driver, doc_new, ident_old, limit=10)
            pair_audit["n_pointers"] = len(pointers)
            logger.info(f"  Anchor old: [{anchor_old['claim_id'][:25]}] {anchor_old['text'][:80]}...")
            logger.info(f"  {len(pointers)} pointer claims trouvés dans {doc_new[:30]}")

            if not pointers:
                logger.info("  Aucun pointer → skip cette paire")
                audit["succession_pairs_processed"].append(pair_audit)
                continue

            # 3. Pour chaque pointer, classifier (pointer dans doc_new) → (anchor dans doc_old)
            # Note : LOGICAL_RELATION est dirigée. Pour SUPERSEDES, A→B veut dire A remplace B.
            # Donc on classifie (claim_new, claim_old) — le LLM dira si c'est SUPERSEDES (claim_new
            # dit que claim_old est repealed) ou autre.
            for pointer in pointers:
                if relation_already_exists(driver, pointer["claim_id"], anchor_old["claim_id"], "SUPERSEDES"):
                    audit["relations_skipped_already_exist"] += 1
                    continue

                # Classifier
                output = classifier.classify(
                    claim_a_text=pointer["text"],
                    claim_b_text=anchor_old["text"],
                    publication_date_a=pointer.get("pub"),
                    publication_date_b=anchor_old.get("pub"),
                    doc_role_a="successor",
                    doc_role_b="predecessor",
                    domain_hints=hints,
                )

                if not output:
                    audit["errors"].append({
                        "pointer": pointer["claim_id"],
                        "anchor": anchor_old["claim_id"],
                        "error": "LLM call failed or invalid JSON",
                    })
                    continue

                pair_audit["n_classified"] += 1
                rel_type = output.relation.value if hasattr(output.relation, "value") else str(output.relation)
                pair_audit["relations_by_type"][rel_type] = pair_audit["relations_by_type"].get(rel_type, 0) + 1

                if rel_type == "UNRELATED":
                    audit["relations_unrelated"] += 1
                    continue

                # Persist
                strength = output.strength.value if hasattr(output.strength, "value") else str(output.strength)
                persist_relation(
                    driver,
                    a_claim_id=pointer["claim_id"],
                    b_claim_id=anchor_old["claim_id"],
                    relation_type=rel_type,
                    strength=strength,
                    confidence=float(output.confidence or 0.0),
                    reasoning=output.reasoning or "",
                    derivation_path=f"S3F-4 succession: {doc_old}→{doc_new}",
                )
                pair_audit["n_persisted"] += 1
                audit["relations_persisted"].append({
                    "pointer": pointer["claim_id"],
                    "anchor": anchor_old["claim_id"],
                    "type": rel_type,
                    "confidence": float(output.confidence or 0.0),
                })
                logger.info(
                    f"    + {rel_type} (conf={output.confidence:.2f}) "
                    f"[{pointer['claim_id'][:20]}] → [{anchor_old['claim_id'][:20]}]"
                )

            audit["succession_pairs_processed"].append(pair_audit)
            logger.info(
                f"  → classified={pair_audit['n_classified']}, "
                f"persisted={pair_audit['n_persisted']}, "
                f"types={pair_audit['relations_by_type']}"
            )
    finally:
        driver.close()

    audit["timestamp_end"] = datetime.utcnow().isoformat() + "Z"

    # Output rapport
    out = Path("/data/forensics/reclassify_s3f_" + datetime.utcnow().strftime("%Y%m%dT%H%M%S") + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")

    # Résumé
    n_persisted = sum(p["n_persisted"] for p in audit["succession_pairs_processed"])
    n_classified = sum(p["n_classified"] for p in audit["succession_pairs_processed"])
    logger.info("\n" + "=" * 70)
    logger.info("Synthèse")
    logger.info("=" * 70)
    logger.info(f"  Pairs of docs processed : {len(audit['succession_pairs_processed'])}")
    logger.info(f"  Pointer claims totales  : {sum(p['n_pointers'] for p in audit['succession_pairs_processed'])}")
    logger.info(f"  LLM classifications     : {n_classified}")
    logger.info(f"  Relations persisted     : {n_persisted}")
    logger.info(f"  Skipped (already exist) : {audit['relations_skipped_already_exist']}")
    logger.info(f"  UNRELATED (no relation) : {audit['relations_unrelated']}")
    logger.info(f"  Errors                  : {len(audit['errors'])}")
    logger.info(f"\n✅ Rapport JSON : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
