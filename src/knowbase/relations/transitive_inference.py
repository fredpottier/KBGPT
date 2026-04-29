"""
S4.A — Composabilité transitive V3.3 (cf. CONTRADICTION_DETECTION_ARCHITECTURE.md §3.G.4).

Promu de "optionnel" (V2) à feature de premier plan (V3) suite au challenge ChatGPT :
le KG passe de **graph de faits** (ce que le LLM a vu) à **graph de raisonnement**
(ce qui en découle).

Règles transitives universelles (cf. plan §S4.A) :

| Antécédent (A→B + B→C) | Conséquent (A→C) | Discount |
|---|---|---|
| SUBSET ∧ SUBSET           | SUBSET           | 0.9  |
| SUPERSET ∧ SUPERSET       | SUPERSET         | 0.9  |
| EQUIVALENT ∧ EQUIVALENT   | EQUIVALENT       | 0.95 |
| EXCEPTION ∧ SUBSET        | EXCEPTION        | 0.85 |
| DEFINITION_OF ∧ DEFINITION_OF | DEFINITION_OF | 0.95 |
| SUPERSEDES ∧ SUPERSEDES   | SUPERSEDES       | 0.9  |
| CONFLICT (A,B) ∧ EQUIVALENT (A,A') | CONFLICT (A',B) | 0.9 |
| EVOLVES_FROM ∧ EVOLVES_FROM | EVOLVES_FROM   | 0.85 |

Garde-fous critiques (V3.3 §3.G.4) :
- Borne hops ≤ 3 (au-delà, discount cumulatif rend confidence inutilisable)
- Marquer relations dérivées avec `derived: true` + `derivation_path: [edge_id_1, ..., edge_id_n]`
- Recompute incrémental (pas full) après chaque batch de classification
- Skip persistence si confidence_finale < 0.50 (bruit)

Pattern V3.3 :
- 100% déterministe (pas de LLM)
- Domain-agnostic (basé sur la typologie 12-types, pas sur du contenu textuel)
- Idempotent (MERGE Cypher avec ON CREATE / ON MATCH)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from neo4j import Driver

from knowbase.relations.v33_types import LogicalRelationType

logger = logging.getLogger(__name__)


# ============================================================================
# Règles transitives universelles
# ============================================================================
# Format : (rel_AB, rel_BC) → (rel_AC_inferred, discount_factor)
TRANSITIVITY_RULES: dict[tuple[str, str], tuple[str, float]] = {
    # Set-like (chains)
    ("SUBSET", "SUBSET"): ("SUBSET", 0.9),
    ("SUPERSET", "SUPERSET"): ("SUPERSET", 0.9),
    ("EQUIVALENT", "EQUIVALENT"): ("EQUIVALENT", 0.95),

    # EQUIVALENT propagation (heritage de relations)
    ("EQUIVALENT", "SUBSET"): ("SUBSET", 0.85),
    ("SUBSET", "EQUIVALENT"): ("SUBSET", 0.85),
    ("EQUIVALENT", "SUPERSET"): ("SUPERSET", 0.85),
    ("SUPERSET", "EQUIVALENT"): ("SUPERSET", 0.85),
    ("EQUIVALENT", "CONFLICT"): ("CONFLICT", 0.9),
    ("CONFLICT", "EQUIVALENT"): ("CONFLICT", 0.9),
    ("EQUIVALENT", "EXCEPTION"): ("EXCEPTION", 0.85),
    ("EXCEPTION", "EQUIVALENT"): ("EXCEPTION", 0.85),

    # Exception remonte via SUBSET
    ("EXCEPTION", "SUBSET"): ("EXCEPTION", 0.85),

    # Definition transitive
    ("DEFINITION_OF", "DEFINITION_OF"): ("DEFINITION_OF", 0.95),

    # Temporal succession
    ("SUPERSEDES", "SUPERSEDES"): ("SUPERSEDES", 0.9),
    ("EVOLVES_FROM", "EVOLVES_FROM"): ("EVOLVES_FROM", 0.85),
    ("SUPERSEDES", "EVOLVES_FROM"): ("SUPERSEDES", 0.8),
}

# Discount cumulatif (multiplicatif) selon profondeur
DEPTH_DISCOUNT = {1: 1.0, 2: 1.0, 3: 0.9}  # 1-hop = original, 2-hop = full discount règle, 3-hop = règle ×0.9

# Confidence floor : on persiste pas si confidence finale < ce seuil
CONFIDENCE_FLOOR = 0.50

# Hop limit absolu (cf. plan §S4.A)
MAX_HOPS = 3


@dataclass
class TransitiveInferenceResult:
    """Résultat d'un run de transitive inference."""

    derived_count: int = 0
    skipped_low_confidence: int = 0
    skipped_existing: int = 0
    elapsed_s: float = 0.0


class TransitiveInferenceEngine:
    """
    Moteur de matérialisation des relations transitives V3.3.

    Stratégie : itère sur les relations directes (non-derived), applique les règles
    transitives jusqu'à profondeur MAX_HOPS, persiste les nouvelles relations
    dérivées en MERGE idempotent.
    """

    def __init__(self, neo4j_driver: Driver, tenant_id: str = "default"):
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    def materialize(self, max_hops: int = MAX_HOPS, dry_run: bool = False) -> TransitiveInferenceResult:
        """
        Calcule + persiste les relations transitives jusqu'à profondeur max_hops.

        Args:
            max_hops: profondeur max (défaut 3, hard cap 3)
            dry_run: si True, calcule mais ne persiste pas

        Returns:
            TransitiveInferenceResult avec stats
        """
        if max_hops > MAX_HOPS:
            logger.warning(f"[V33:Transitive] max_hops={max_hops} > MAX_HOPS={MAX_HOPS}, capping")
            max_hops = MAX_HOPS

        result = TransitiveInferenceResult()
        t_start = time.time()

        # On itère par profondeur (depth=2 d'abord, puis depth=3)
        # Chaque itération exploite les relations directes + dérivées de profondeur précédente
        for depth in range(2, max_hops + 1):
            logger.info(f"\n--- Materializing depth={depth} ---")
            depth_result = self._materialize_depth(depth, dry_run)
            result.derived_count += depth_result.derived_count
            result.skipped_low_confidence += depth_result.skipped_low_confidence
            result.skipped_existing += depth_result.skipped_existing
            logger.info(
                f"  depth={depth}: +{depth_result.derived_count} derived, "
                f"-{depth_result.skipped_low_confidence} low-conf, "
                f"-{depth_result.skipped_existing} existing"
            )

        result.elapsed_s = time.time() - t_start
        return result

    def _materialize_depth(self, depth: int, dry_run: bool) -> TransitiveInferenceResult:
        """
        Matérialise les relations transitives à profondeur exactement `depth`.

        Pour depth=2 : on cherche les chemins A→B→C où A→B et B→C existent
        (directes ou déjà dérivées de depth précédent).
        """
        result = TransitiveInferenceResult()

        # Build chemins de longueur `depth-1` puis on cherche un chaînon supplémentaire
        # Pour simplifier : on fait depth=2 d'abord (chemins A-B-C de 2 hops),
        # puis on peut extender avec depth=3 en chaînant depth=2 + 1 hop.

        # Cypher : récupère TOUTES les paires (a,c) telles qu'il existe un chemin
        # A→B→C de longueur `depth`, sans qu'il y ait déjà une relation directe A→C
        # (on évite les doublons).
        if depth == 2:
            cypher = """
            MATCH (a:Claim {tenant_id: $tid})-[r1:LOGICAL_RELATION]->(b:Claim {tenant_id: $tid})-[r2:LOGICAL_RELATION]->(c:Claim {tenant_id: $tid})
            WHERE a <> c
              AND coalesce(r1.legacy, false) = false
              AND coalesce(r2.legacy, false) = false
              AND r1.type IN $allowed_types
              AND r2.type IN $allowed_types
            RETURN
              a.claim_id AS a_id, b.claim_id AS b_id, c.claim_id AS c_id,
              r1.type AS rel_ab, r1.confidence AS conf_ab,
              r2.type AS rel_bc, r2.confidence AS conf_bc,
              elementId(r1) AS r1_id, elementId(r2) AS r2_id
            """
        elif depth == 3:
            cypher = """
            MATCH (a:Claim {tenant_id: $tid})-[r1:LOGICAL_RELATION]->(b:Claim {tenant_id: $tid})-[r2:LOGICAL_RELATION]->(c:Claim {tenant_id: $tid})-[r3:LOGICAL_RELATION]->(d:Claim {tenant_id: $tid})
            WHERE a <> d AND a <> c AND b <> d
              AND coalesce(r1.legacy, false) = false
              AND coalesce(r2.legacy, false) = false
              AND coalesce(r3.legacy, false) = false
              AND r1.type IN $allowed_types
              AND r2.type IN $allowed_types
              AND r3.type IN $allowed_types
            RETURN
              a.claim_id AS a_id, b.claim_id AS b_id, c.claim_id AS c_id, d.claim_id AS d_id,
              r1.type AS rel_ab, r1.confidence AS conf_ab,
              r2.type AS rel_bc, r2.confidence AS conf_bc,
              r3.type AS rel_cd, r3.confidence AS conf_cd,
              elementId(r1) AS r1_id, elementId(r2) AS r2_id, elementId(r3) AS r3_id
            LIMIT 50000
            """
        else:
            return result

        allowed_types = [t for t in {a for a, b in TRANSITIVITY_RULES.keys()}.union(
            {b for a, b in TRANSITIVITY_RULES.keys()}
        )]

        with self.driver.session() as s:
            rows = s.run(cypher, tid=self.tenant_id, allowed_types=allowed_types).data()
            logger.info(f"  Found {len(rows)} candidate paths at depth={depth}")

            for row in rows:
                derived = self._infer_from_path(row, depth)
                if derived is None:
                    continue

                rel_type, confidence, derivation_path, src, dst = derived

                if confidence < CONFIDENCE_FLOOR:
                    result.skipped_low_confidence += 1
                    continue

                if dry_run:
                    result.derived_count += 1
                    continue

                # Persist (idempotent MERGE)
                created = self._persist_derived(s, src, dst, rel_type, confidence, derivation_path)
                if created:
                    result.derived_count += 1
                else:
                    result.skipped_existing += 1

        return result

    def _infer_from_path(self, row: dict, depth: int) -> Optional[tuple[str, float, list[str], str, str]]:
        """
        Applique les règles transitives à un chemin donné.

        Returns:
            (rel_type, confidence, derivation_path, src_claim_id, dst_claim_id) ou None
        """
        if depth == 2:
            rel_ab, rel_bc = row["rel_ab"], row["rel_bc"]
            conf_ab, conf_bc = float(row["conf_ab"] or 0), float(row["conf_bc"] or 0)
            rule_key = (rel_ab, rel_bc)
            if rule_key not in TRANSITIVITY_RULES:
                return None
            inferred_type, discount = TRANSITIVITY_RULES[rule_key]
            confidence = min(conf_ab, conf_bc) * discount * DEPTH_DISCOUNT[2]
            return (
                inferred_type,
                round(confidence, 3),
                [row["r1_id"], row["r2_id"]],
                row["a_id"],
                row["c_id"],
            )

        if depth == 3:
            rel_ab, rel_bc, rel_cd = row["rel_ab"], row["rel_bc"], row["rel_cd"]
            conf_ab = float(row["conf_ab"] or 0)
            conf_bc = float(row["conf_bc"] or 0)
            conf_cd = float(row["conf_cd"] or 0)

            # On compose en 2 étapes : (AB,BC) → AC, puis (AC,CD) → AD
            rule1 = TRANSITIVITY_RULES.get((rel_ab, rel_bc))
            if rule1 is None:
                return None
            ac_type, discount1 = rule1
            ac_conf = min(conf_ab, conf_bc) * discount1

            rule2 = TRANSITIVITY_RULES.get((ac_type, rel_cd))
            if rule2 is None:
                return None
            inferred_type, discount2 = rule2
            confidence = min(ac_conf, conf_cd) * discount2 * DEPTH_DISCOUNT[3]
            return (
                inferred_type,
                round(confidence, 3),
                [row["r1_id"], row["r2_id"], row["r3_id"]],
                row["a_id"],
                row["d_id"],
            )

        return None

    def _persist_derived(
        self,
        session,
        src: str,
        dst: str,
        rel_type: str,
        confidence: float,
        derivation_path: list[str],
    ) -> bool:
        """
        Persist une relation dérivée en MERGE idempotent.

        Returns True si nouvellement créée, False si déjà existante.
        """
        result = session.run(
            """
            MATCH (a:Claim {claim_id: $src, tenant_id: $tid})
            MATCH (b:Claim {claim_id: $dst, tenant_id: $tid})
            MERGE (a)-[r:LOGICAL_RELATION {type: $type, derived: true}]->(b)
            ON CREATE SET
                r.confidence = $confidence,
                r.strength = 'WEAK',
                r.derivation_path = $derivation_path,
                r.derivation_depth = $derivation_depth,
                r.is_contradiction = false,
                r.extracted_by = 'transitive_inference_v33',
                r.extracted_at = $ts,
                r.created_via = 'transitive'
            ON MATCH SET
                r.confidence = CASE WHEN $confidence > coalesce(r.confidence, 0.0) THEN $confidence ELSE r.confidence END
            RETURN
              CASE WHEN r.created_via = 'transitive' AND r.extracted_at = $ts THEN 1 ELSE 0 END AS created
            """,
            src=src,
            dst=dst,
            tid=self.tenant_id,
            type=rel_type,
            confidence=confidence,
            derivation_path=derivation_path,
            derivation_depth=len(derivation_path),
            ts=__import__("datetime").datetime.utcnow().isoformat(),
        ).single()
        return result["created"] == 1 if result else False

    def stats(self) -> dict:
        """Stats sur les relations dérivées actuelles."""
        with self.driver.session() as s:
            row = s.run(
                """
                MATCH ()-[r:LOGICAL_RELATION]->() WHERE r.derived = true AND coalesce(r.legacy, false) = false
                RETURN
                  count(r) AS total_derived,
                  count(DISTINCT r.type) AS distinct_types,
                  avg(r.confidence) AS avg_confidence
                """
            ).single()
            by_type = s.run(
                """
                MATCH ()-[r:LOGICAL_RELATION]->() WHERE r.derived = true AND coalesce(r.legacy, false) = false
                RETURN r.type AS type, count(r) AS count
                ORDER BY count DESC
                """
            ).data()
            return {
                "total_derived": row["total_derived"] if row else 0,
                "distinct_types": row["distinct_types"] if row else 0,
                "avg_confidence": float(row["avg_confidence"]) if row and row["avg_confidence"] else 0,
                "by_type": by_type,
            }


__all__ = [
    "TransitiveInferenceEngine",
    "TransitiveInferenceResult",
    "TRANSITIVITY_RULES",
    "MAX_HOPS",
    "CONFIDENCE_FLOOR",
]
