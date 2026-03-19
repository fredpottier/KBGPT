"""Règle L2 — Déduplication acronyme ↔ nom complet.

100% déterministe. Résout les équivalences explicites dans le corpus :
pattern "NomComplet (ACRONYME)" + DomainContext common_acronyms.

Actions : MERGE_CANONICAL — auto-apply si confidence >= seuil, sinon PROPOSED.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from knowbase.claimfirst.models.canonical_entity import CanonicalEntity
from knowbase.claimfirst.models.entity import Entity
from knowbase.hygiene.acronym_map import AcronymEntry, AcronymMapBuilder
from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
)
from knowbase.hygiene.rules.base import HygieneRule

logger = logging.getLogger("[OSMOSE] kg_hygiene_acronym_dedup")

# Seuil par défaut d'auto-apply pour acronym dedup.
# >= 0.8 : entity name pattern (corpus explicite) → auto-apply
# >= 0.9 : domain context seul → auto-apply
# >= 1.0 : multi-source (corpus + domain context) → auto-apply
# < 0.8  : claim text inline, patterns rares → PROPOSED (review admin)
DEFAULT_AUTO_APPLY_THRESHOLD = 0.8


@dataclass
class AcronymCluster:
    """Cluster d'entités liées à un acronyme."""

    core: List[Tuple[dict, str]] = field(default_factory=list)
    """Entités fusionnables + match_type ('acronym_pure', 'expansion_pure', 'composite')."""

    variants: List[Tuple[dict, str]] = field(default_factory=list)
    """Entités liables mais pas fusionnées (ex: 'PCT level')."""


class AcronymDedupRule(HygieneRule):
    """Déduplication acronyme ↔ nom complet — 100% déterministe."""

    @property
    def name(self) -> str:
        return "acronym_dedup"

    @property
    def layer(self) -> int:
        return 2

    @property
    def description(self) -> str:
        return (
            "Détecte les entités représentant le même concept via "
            "équivalence acronyme/nom complet (corpus + domain context)"
        )

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
        auto_apply_threshold: float = DEFAULT_AUTO_APPLY_THRESHOLD,
    ) -> List[HygieneAction]:
        # 1. Construire l'AcronymMap
        builder = AcronymMapBuilder()
        acronym_map = builder.build(neo4j_driver, tenant_id)

        if not acronym_map:
            return []

        # 2. Charger toutes les entités + canonicals existants
        all_entities = self._load_entities(neo4j_driver, tenant_id)
        existing_canonicals = self._load_canonicals(neo4j_driver, tenant_id)
        existing_links = self._load_existing_links(neo4j_driver, tenant_id)

        # 3. Pour chaque AcronymEntry non-ambiguë
        actions: List[HygieneAction] = []
        processed_entities: Set[str] = set()

        for acr, entry in acronym_map.items():
            if entry.ambiguous:
                continue

            cluster = self._find_cluster(entry, all_entities)
            if len(cluster.core) < 2:
                continue

            # Déterminer le canonical target
            canonical = self._resolve_canonical(
                entry, cluster, existing_canonicals, tenant_id
            )
            if not canonical:
                continue

            # Proposer MERGE_CANONICAL pour chaque entité core sauf le canonical
            for entity, match_type in cluster.core:
                eid = entity["entity_id"]
                if eid in processed_entities:
                    continue
                # Skip si cette entité est déjà liée au même canonical
                if (eid, canonical["target_id"]) in existing_links:
                    continue
                # Skip si c'est l'entité qui porte le canonical
                if eid == canonical.get("source_entity_id"):
                    continue

                processed_entities.add(eid)

                # Auto-apply si confidence >= seuil (déterministe, haute confiance)
                if entry.confidence >= auto_apply_threshold:
                    status = HygieneActionStatus.APPLIED
                    decision_source = "rule_auto_apply"
                else:
                    status = HygieneActionStatus.PROPOSED
                    decision_source = "rule"

                action = HygieneAction(
                    action_type=HygieneActionType.MERGE_CANONICAL,
                    target_node_id=eid,
                    target_node_type="Entity",
                    layer=2,
                    confidence=entry.confidence,
                    reason=(
                        f"Acronyme '{entry.acronym}' = '{entry.primary_expansion}' "
                        f"(source: {entry.sources[0]})"
                    ),
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=status,
                    decision_source=decision_source,
                    tenant_id=tenant_id,
                    after_state={
                        "merge_target_id": canonical["target_id"],
                        "canonical_name": entry.primary_expansion,
                        "acronym": entry.acronym,
                        "target_name": entity["name"],
                        "resolution_reason": "acronym_map",
                        "resolution_source_type": _source_type(entry.sources[0]),
                        "resolution_confidence": entry.confidence,
                        "matched_pattern": match_type,
                        "evidence_span": entry.sources[0],
                        "all_sources": entry.sources,
                    },
                )
                actions.append(action)

        auto_applied = sum(
            1 for a in actions if a.status == HygieneActionStatus.APPLIED
        )
        proposed = len(actions) - auto_applied
        logger.info(
            f"  → {len(actions)} fusions acronyme/expansion "
            f"({auto_applied} auto-applied, {proposed} proposed) "
            f"(sur {len(acronym_map)} acronymes, "
            f"{sum(1 for e in acronym_map.values() if e.ambiguous)} ambigus)"
        )
        return actions

    def apply_action(self, neo4j_driver, action: HygieneAction) -> bool:
        """Applique un MERGE_CANONICAL via la méthode de base."""
        if action.action_type == HygieneActionType.MERGE_CANONICAL:
            return self._apply_merge_canonical(neo4j_driver, action)
        return False

    # ── Chargement Neo4j ──────────────────────────────────────────────

    def _load_entities(self, neo4j_driver, tenant_id: str) -> List[dict]:
        """Charge toutes les entités actives."""
        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {tenant_id: $tid})
                WHERE e._hygiene_status IS NULL
                RETURN e.entity_id AS entity_id,
                       e.name AS name,
                       e.normalized_name AS normalized_name,
                       e.entity_type AS entity_type
                """,
                tid=tenant_id,
            )
            return [dict(r) for r in result]

    def _load_canonicals(self, neo4j_driver, tenant_id: str) -> List[dict]:
        """Charge tous les CanonicalEntity actifs."""
        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (ce:CanonicalEntity {tenant_id: $tid})
                WHERE ce._hygiene_status IS NULL
                RETURN ce.canonical_entity_id AS canonical_entity_id,
                       ce.canonical_name AS canonical_name,
                       ce.entity_type AS entity_type
                """,
                tid=tenant_id,
            )
            return [dict(r) for r in result]

    def _load_existing_links(
        self, neo4j_driver, tenant_id: str
    ) -> Set[Tuple[str, str]]:
        """Charge les SAME_CANON_AS existants (entity_id, canonical_entity_id)."""
        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {tenant_id: $tid})-[:SAME_CANON_AS]->(ce:CanonicalEntity)
                RETURN e.entity_id AS eid, ce.canonical_entity_id AS ceid
                """,
                tid=tenant_id,
            )
            return {(r["eid"], r["ceid"]) for r in result}

    # ── Clustering ────────────────────────────────────────────────────

    def _find_cluster(
        self, entry: AcronymEntry, all_entities: List[dict]
    ) -> AcronymCluster:
        """Trouve le cluster d'entités liées à cet acronyme."""
        cluster = AcronymCluster()
        acr_upper = entry.acronym.upper()
        acr_norm = Entity.normalize(entry.acronym)
        expansion_norm = Entity.normalize(entry.primary_expansion)
        # Forme composite "Expansion (Acronyme)"
        composite_norms = {
            Entity.normalize(f"{entry.primary_expansion} ({entry.acronym})"),
            Entity.normalize(f"{entry.acronym} ({entry.primary_expansion})"),
        }

        for entity in all_entities:
            e_norm = entity.get("normalized_name") or Entity.normalize(entity["name"])
            e_name = entity["name"]

            # Match exact acronyme pur
            if e_norm == acr_norm or e_name.upper() == acr_upper:
                cluster.core.append((entity, "acronym_pure"))
                continue

            # Match exact expansion pure
            if e_norm == expansion_norm:
                cluster.core.append((entity, "expansion_pure"))
                continue

            # Match composite "Expansion (Acronyme)" ou "Acronyme (Expansion)"
            if e_norm in composite_norms:
                cluster.core.append((entity, "composite"))
                continue

            # Variantes (prefix match) — pas fusionnées dans N1
            if e_norm.startswith(acr_norm + " ") and len(e_norm) > len(acr_norm) + 1:
                cluster.variants.append((entity, "variant_prefix"))
            elif e_norm.startswith(expansion_norm + " ") and len(e_norm) > len(expansion_norm) + 1:
                cluster.variants.append((entity, "variant_prefix"))

        return cluster

    # ── Résolution du canonical target ────────────────────────────────

    def _resolve_canonical(
        self,
        entry: AcronymEntry,
        cluster: AcronymCluster,
        existing_canonicals: List[dict],
        tenant_id: str,
    ) -> Optional[dict]:
        """Détermine le CanonicalEntity cible.

        Priorité :
          1. CanonicalEntity existant aligné avec l'expansion pure
          2. Entity dont le nom = expansion pure normalisée → créer/utiliser son CE
          3. Génération d'un nouveau CE depuis l'expansion
        """
        expansion_norm = Entity.normalize(entry.primary_expansion)

        # Priorité 1 : CanonicalEntity existant aligné
        for ce in existing_canonicals:
            ce_norm = Entity.normalize(ce["canonical_name"])
            if ce_norm == expansion_norm:
                return {
                    "target_id": ce["canonical_entity_id"],
                    "canonical_name": ce["canonical_name"],
                    "source_entity_id": None,
                }

        # Priorité 2 : Entity expansion pure → utiliser son CE potentiel
        for entity, match_type in cluster.core:
            if match_type == "expansion_pure":
                ce_id = CanonicalEntity.make_id(tenant_id, entry.primary_expansion)
                return {
                    "target_id": ce_id,
                    "canonical_name": entry.primary_expansion,
                    "source_entity_id": entity["entity_id"],
                }

        # Priorité 3 : Générer un CE depuis l'expansion
        ce_id = CanonicalEntity.make_id(tenant_id, entry.primary_expansion)
        return {
            "target_id": ce_id,
            "canonical_name": entry.primary_expansion,
            "source_entity_id": None,
        }


def _source_type(source: str) -> str:
    """Extrait le type de source depuis le label."""
    if source.startswith("entity:"):
        return "entity_name"
    elif source.startswith("claim:"):
        return "claim_text"
    elif source.startswith("domain_context:"):
        return "domain_context"
    return "unknown"
