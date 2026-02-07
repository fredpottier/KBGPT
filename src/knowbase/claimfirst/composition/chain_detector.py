# src/knowbase/claimfirst/composition/chain_detector.py
"""
ChainDetector — Détection déterministe de chaînes S/P/O intra-document.

Algorithme (0 LLM) :
  Pour chaque document, si claim_A.object == claim_B.subject (normalisé),
  alors A CHAINS_TO B.

Garde-fous :
  - is_valid_entity_name + len >= 3 sur le join_key
  - Pas de self-loop (A == B)
  - Pas de cycle trivial (A.subject == B.object ET A.object == B.subject)
  - Anti-cartesian : max MAX_EDGES_PER_KEY edges par join_key par document
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.entity import Entity, is_valid_entity_name
from knowbase.claimfirst.models.result import ClaimRelation, RelationType

logger = logging.getLogger(__name__)

MAX_EDGES_PER_KEY = 10

# Prédicats canoniques — seuls les claims avec ces prédicats participent aux chaînes
_CANONICAL_PREDICATES = frozenset({
    "USES", "REQUIRES", "BASED_ON", "SUPPORTS", "ENABLES",
    "PROVIDES", "EXTENDS", "REPLACES", "PART_OF",
    "INTEGRATED_IN", "COMPATIBLE_WITH", "CONFIGURES",
})


@dataclass
class ChainLink:
    """Lien interne entre deux claims via un join S/P/O."""

    source_claim_id: str
    target_claim_id: str
    join_key: str
    source_predicate: str
    target_predicate: str
    doc_id: str
    join_key_freq: int = 0


class ChainDetector:
    """
    Détecte les chaînes compositionnelles S/P/O intra-document.

    Un concept central (ex: S/4HANA) PEUT et DOIT être dense —
    c'est fidèle au document. Le guard-fou correct est le cap par
    join_key (anti-cartesian), pas le skip par fréquence (anti-hub).
    """

    def __init__(self, max_edges_per_key: int = MAX_EDGES_PER_KEY):
        self.max_edges_per_key = max_edges_per_key
        self._stats = {
            "claims_with_sf": 0,
            "docs_processed": 0,
            "chains_detected": 0,
            "join_keys_found": 0,
            "join_keys_capped": 0,
        }

    def detect(self, claims: list) -> List[ClaimRelation]:
        """
        Détecte les chaînes S/P/O sur une liste de Claim objects.

        Args:
            claims: Liste de Claim (Pydantic models)

        Returns:
            Liste de ClaimRelation de type CHAINS_TO
        """
        claim_dicts = []
        for c in claims:
            sf = c.structured_form
            if not sf:
                continue
            claim_dicts.append({
                "claim_id": c.claim_id,
                "doc_id": c.doc_id,
                "structured_form": sf,
                "confidence": c.confidence,
            })

        return self.detect_from_dicts(claim_dicts)

    def detect_from_dicts(self, claim_dicts: List[Dict[str, Any]]) -> List[ClaimRelation]:
        """
        Détecte les chaînes S/P/O depuis des dicts (pour le script rétroactif).

        Chaque dict doit contenir :
          - claim_id: str
          - doc_id: str
          - structured_form: dict avec subject, predicate, object
          - confidence: float (optionnel, défaut 0.5)

        Args:
            claim_dicts: Liste de dicts représentant des claims

        Returns:
            Liste de ClaimRelation de type CHAINS_TO
        """
        # Filtrer les claims avec structured_form valide + prédicat canonique
        valid = []
        skipped_pred = 0
        for cd in claim_dicts:
            sf = cd.get("structured_form")
            if not sf:
                continue
            subj = sf.get("subject", "")
            pred = sf.get("predicate", "")
            obj = sf.get("object", "")
            if not (subj and pred and obj):
                continue
            # Rejeter les prédicats non-canoniques (MONITORS, CONNECTS_TO, etc.)
            if pred.upper() not in _CANONICAL_PREDICATES:
                skipped_pred += 1
                continue
            valid.append(cd)

        if skipped_pred:
            logger.info(f"[OSMOSE:ChainDetector] {skipped_pred} claims skipped (non-canonical predicate)")
        self._stats["claims_with_sf"] = len(valid)

        if not valid:
            return []

        # Grouper par doc_id (intra-doc uniquement)
        by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for cd in valid:
            by_doc[cd["doc_id"]].append(cd)

        self._stats["docs_processed"] = len(by_doc)

        all_relations: List[ClaimRelation] = []
        seen_pairs: set = set()

        for doc_id, doc_claims in by_doc.items():
            relations = self._detect_in_doc(doc_id, doc_claims, seen_pairs)
            all_relations.extend(relations)

        self._stats["chains_detected"] = len(all_relations)
        return all_relations

    def _detect_in_doc(
        self,
        doc_id: str,
        doc_claims: List[Dict[str, Any]],
        seen_pairs: set,
    ) -> List[ClaimRelation]:
        """Détecte les chaînes dans un seul document."""
        # Build indexes: normalized entity → [claims]
        object_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        subject_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for cd in doc_claims:
            sf = cd["structured_form"]
            obj_norm = Entity.normalize(sf["object"])
            subj_norm = Entity.normalize(sf["subject"])
            object_index[obj_norm].append(cd)
            subject_index[subj_norm].append(cd)

        # Trouver les join_keys (intersection des indexes)
        join_keys = set(object_index.keys()) & set(subject_index.keys())

        relations: List[ClaimRelation] = []

        for join_key in join_keys:
            # GARDE-FOU 1 : entity name valide et len >= 3
            if len(join_key) < 3 or not is_valid_entity_name(join_key):
                continue

            self._stats["join_keys_found"] += 1

            sources = object_index[join_key]  # claims dont object = join_key
            targets = subject_index[join_key]  # claims dont subject = join_key

            # Fréquence du join_key dans le doc (nombre de claims le touchant)
            all_claim_ids = set()
            for cd in sources:
                all_claim_ids.add(cd["claim_id"])
            for cd in targets:
                all_claim_ids.add(cd["claim_id"])
            freq = len(all_claim_ids)

            # GARDE-FOU 3 (anti-cartesian) : cap le nombre d'edges
            max_edges = self.max_edges_per_key
            total_possible = len(sources) * len(targets)

            if total_possible > max_edges:
                self._stats["join_keys_capped"] += 1
                # Garder les claims à plus haute confidence des deux côtés
                sources = sorted(
                    sources,
                    key=lambda c: c.get("confidence", 0.5),
                    reverse=True,
                )
                targets = sorted(
                    targets,
                    key=lambda c: c.get("confidence", 0.5),
                    reverse=True,
                )

            edges_emitted = 0

            for src in sources:
                if edges_emitted >= max_edges:
                    break
                for tgt in targets:
                    if edges_emitted >= max_edges:
                        break

                    src_id = src["claim_id"]
                    tgt_id = tgt["claim_id"]

                    # Pas de self-loop
                    if src_id == tgt_id:
                        continue

                    # Pas de cycle trivial
                    src_sf = src["structured_form"]
                    tgt_sf = tgt["structured_form"]
                    src_subj_norm = Entity.normalize(src_sf["subject"])
                    tgt_obj_norm = Entity.normalize(tgt_sf["object"])
                    if src_subj_norm == tgt_obj_norm and src_subj_norm == join_key:
                        continue

                    # Dédup des paires
                    pair_key = (src_id, tgt_id)
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    relation = ClaimRelation(
                        source_claim_id=src_id,
                        target_claim_id=tgt_id,
                        relation_type=RelationType.CHAINS_TO,
                        confidence=1.0,
                        basis=f"join_key={join_key}",
                    )
                    relations.append(relation)
                    edges_emitted += 1

        return relations

    def get_chain_links(self, claims: list) -> List[ChainLink]:
        """
        Version enrichie pour le script rétroactif.

        Retourne des ChainLink avec métadonnées (join_key_freq, predicates).
        """
        claim_dicts = []
        for c in claims:
            sf = c.structured_form
            if not sf:
                continue
            claim_dicts.append({
                "claim_id": c.claim_id,
                "doc_id": c.doc_id,
                "structured_form": sf,
                "confidence": c.confidence,
            })

        return self.get_chain_links_from_dicts(claim_dicts)

    def get_chain_links_from_dicts(
        self, claim_dicts: List[Dict[str, Any]]
    ) -> List[ChainLink]:
        """
        Version enrichie depuis dicts pour le script rétroactif.

        Retourne des ChainLink avec métadonnées complètes pour persistance Neo4j.
        """
        valid = []
        for cd in claim_dicts:
            sf = cd.get("structured_form")
            if not sf:
                continue
            subj = sf.get("subject", "")
            pred = sf.get("predicate", "")
            obj = sf.get("object", "")
            if not (subj and pred and obj):
                continue
            # Rejeter les prédicats non-canoniques
            if pred.upper() not in _CANONICAL_PREDICATES:
                continue
            valid.append(cd)

        if not valid:
            return []

        by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for cd in valid:
            by_doc[cd["doc_id"]].append(cd)

        all_links: List[ChainLink] = []
        seen_pairs: set = set()

        for doc_id, doc_claims in by_doc.items():
            links = self._get_links_in_doc(doc_id, doc_claims, seen_pairs)
            all_links.extend(links)

        return all_links

    def _get_links_in_doc(
        self,
        doc_id: str,
        doc_claims: List[Dict[str, Any]],
        seen_pairs: set,
    ) -> List[ChainLink]:
        """Génère des ChainLinks enrichis dans un seul document."""
        object_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        subject_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for cd in doc_claims:
            sf = cd["structured_form"]
            obj_norm = Entity.normalize(sf["object"])
            subj_norm = Entity.normalize(sf["subject"])
            object_index[obj_norm].append(cd)
            subject_index[subj_norm].append(cd)

        join_keys = set(object_index.keys()) & set(subject_index.keys())
        links: List[ChainLink] = []

        for join_key in join_keys:
            if len(join_key) < 3 or not is_valid_entity_name(join_key):
                continue

            sources = object_index[join_key]
            targets = subject_index[join_key]

            all_claim_ids = set()
            for cd in sources:
                all_claim_ids.add(cd["claim_id"])
            for cd in targets:
                all_claim_ids.add(cd["claim_id"])
            freq = len(all_claim_ids)

            max_edges = self.max_edges_per_key
            total_possible = len(sources) * len(targets)

            if total_possible > max_edges:
                sources = sorted(
                    sources,
                    key=lambda c: c.get("confidence", 0.5),
                    reverse=True,
                )
                targets = sorted(
                    targets,
                    key=lambda c: c.get("confidence", 0.5),
                    reverse=True,
                )

            edges_emitted = 0

            for src in sources:
                if edges_emitted >= max_edges:
                    break
                for tgt in targets:
                    if edges_emitted >= max_edges:
                        break

                    src_id = src["claim_id"]
                    tgt_id = tgt["claim_id"]

                    if src_id == tgt_id:
                        continue

                    src_sf = src["structured_form"]
                    tgt_sf = tgt["structured_form"]
                    src_subj_norm = Entity.normalize(src_sf["subject"])
                    tgt_obj_norm = Entity.normalize(tgt_sf["object"])
                    if src_subj_norm == tgt_obj_norm and src_subj_norm == join_key:
                        continue

                    pair_key = (src_id, tgt_id)
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    link = ChainLink(
                        source_claim_id=src_id,
                        target_claim_id=tgt_id,
                        join_key=join_key,
                        source_predicate=src_sf.get("predicate", ""),
                        target_predicate=tgt_sf.get("predicate", ""),
                        doc_id=doc_id,
                        join_key_freq=freq,
                    )
                    links.append(link)
                    edges_emitted += 1

        return links

    def get_stats(self) -> dict:
        return dict(self._stats)

    def reset_stats(self) -> None:
        for key in self._stats:
            self._stats[key] = 0
