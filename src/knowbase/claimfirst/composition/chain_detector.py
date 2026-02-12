# src/knowbase/claimfirst/composition/chain_detector.py
"""
ChainDetector — Détection déterministe de chaînes S/P/O intra et cross-document.

Algorithme intra-doc (0 LLM) :
  Pour chaque document, si claim_A.object == claim_B.subject (normalisé),
  alors A CHAINS_TO B.

Algorithme cross-doc :
  Même logique mais ENTRE documents, avec :
  - Exclusion des hub entities (trop fréquentes)
  - Ranking déterministe (prédicat priority → IDF → tie-break claim_id)
  - Caps par join_key ET par paire de documents
  - Jointure par entity_id (robuste) avec fallback normalized_name

Garde-fous :
  - is_valid_entity_name + len >= 3 sur le join_key
  - Pas de self-loop (A == B)
  - Pas de cycle trivial (A.subject == B.object ET A.object == B.subject)
  - Anti-cartesian : max MAX_EDGES_PER_KEY edges par join_key par document
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from knowbase.claimfirst.models.entity import Entity, is_valid_entity_name
from knowbase.claimfirst.models.result import ClaimRelation, RelationType

logger = logging.getLogger(__name__)

MAX_EDGES_PER_KEY = 10
MAX_EDGES_PER_KEY_CROSS_DOC = 5
MAX_EDGES_PER_DOC_PAIR = 50

# Prédicats canoniques — seuls les claims avec ces prédicats participent aux chaînes
_CANONICAL_PREDICATES = frozenset({
    "USES", "REQUIRES", "BASED_ON", "SUPPORTS", "ENABLES",
    "PROVIDES", "EXTENDS", "REPLACES", "PART_OF",
    "INTEGRATED_IN", "COMPATIBLE_WITH", "CONFIGURES",
})

# Priorité des prédicats pour le ranking cross-doc
# Plus le score est haut, plus le prédicat est structurant
PREDICATE_PRIORITY = {
    "REQUIRES": 4, "REPLACES": 4, "PART_OF": 4, "INTEGRATED_IN": 4,
    "BASED_ON": 3, "EXTENDS": 3, "COMPATIBLE_WITH": 3,
    "USES": 2, "SUPPORTS": 2, "ENABLES": 2,
    "PROVIDES": 1, "CONFIGURES": 1,
}


@dataclass
class ChainLink:
    """Lien entre deux claims via un join S/P/O."""

    source_claim_id: str
    target_claim_id: str
    join_key: str
    source_predicate: str
    target_predicate: str
    doc_id: str
    join_key_freq: int = 0
    # Champs cross-doc (optionnels, rétro-compatible)
    source_doc_id: Optional[str] = None
    target_doc_id: Optional[str] = None
    is_cross_doc: bool = False
    join_key_idf: float = 0.0
    join_method: str = "normalized_name"
    # Nom lisible de l'entity de jointure (invariant de lisibilité durable)
    join_key_name: str = ""

    def __post_init__(self):
        if not self.join_key_name:
            self.join_key_name = self.join_key


class ChainDetector:
    """
    Détecte les chaînes compositionnelles S/P/O intra et cross-document.

    Intra-doc : un concept central (ex: S/4HANA) PEUT et DOIT être dense —
    c'est fidèle au document. Le guard-fou correct est le cap par
    join_key (anti-cartesian), pas le skip par fréquence (anti-hub).

    Cross-doc : les hub entities sont exclues car elles génèrent du bruit
    entre documents. Ranking déterministe pour sélectionner les liens
    les plus informatifs.
    """

    def __init__(
        self,
        max_edges_per_key: int = MAX_EDGES_PER_KEY,
        max_edges_per_key_cross_doc: int = MAX_EDGES_PER_KEY_CROSS_DOC,
        max_edges_per_doc_pair: int = MAX_EDGES_PER_DOC_PAIR,
    ):
        self.max_edges_per_key = max_edges_per_key
        self.max_edges_per_key_cross_doc = max_edges_per_key_cross_doc
        self.max_edges_per_doc_pair = max_edges_per_doc_pair
        self._stats = {
            "claims_with_sf": 0,
            "docs_processed": 0,
            "chains_detected": 0,
            "join_keys_found": 0,
            "join_keys_capped": 0,
        }
        self._cross_doc_stats = {
            "claims_with_sf": 0,
            "hubs_excluded": 0,
            "join_keys_found": 0,
            "join_keys_below_min_idf": 0,
            "join_keys_capped": 0,
            "chains_detected": 0,
            "duplicate_text_skipped": 0,
            "joins_by_entity_id": 0,
            "joins_by_normalized": 0,
            "doc_pairs_capped": 0,
        }

    # ---------------------------------------------------------------
    # Intra-doc (existant, inchangé)
    # ---------------------------------------------------------------

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
                        join_key_name=join_key,
                    )
                    links.append(link)
                    edges_emitted += 1

        return links

    # ---------------------------------------------------------------
    # Cross-doc
    # ---------------------------------------------------------------

    def detect_cross_doc(
        self,
        claim_dicts: List[Dict[str, Any]],
        hub_entities: Set[str],
        entity_index: Optional[Dict[str, str]] = None,
        idf_map: Optional[Dict[str, float]] = None,
        min_idf: float = 0.0,
    ) -> List[ChainLink]:
        """
        Détecte les chaînes S/P/O cross-document.

        Args:
            claim_dicts: Toutes les claims avec SF (multi-documents)
            hub_entities: Noms normalisés des entities hub à exclure
            entity_index: Mapping normalized_name → entity_id (optionnel)
            idf_map: Mapping join_key → IDF score (optionnel)

        Returns:
            Liste de ChainLink cross-doc enrichis
        """
        if entity_index is None:
            entity_index = {}
        if idf_map is None:
            idf_map = {}

        # Filtrer claims valides avec prédicat canonique
        valid = self._filter_valid_claims(claim_dicts)
        self._cross_doc_stats["claims_with_sf"] = len(valid)

        if not valid:
            return []

        # Construire les index object/subject SANS groupement par doc
        object_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        subject_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for cd in valid:
            sf = cd["structured_form"]
            obj_key, obj_method, obj_norm = self._resolve_join_key(
                sf["object"], entity_index
            )
            subj_key, subj_method, subj_norm = self._resolve_join_key(
                sf["subject"], entity_index
            )
            # Stocker la méthode de résolution sur le dict pour usage ultérieur
            cd["_obj_key"] = obj_key
            cd["_obj_method"] = obj_method
            cd["_obj_norm"] = obj_norm
            cd["_subj_key"] = subj_key
            cd["_subj_method"] = subj_method
            cd["_subj_norm"] = subj_norm

            object_index[obj_key].append(cd)
            subject_index[subj_key].append(cd)

        # Exclure les hub entities
        for hub in hub_entities:
            object_index.pop(hub, None)
            subject_index.pop(hub, None)
            # Aussi exclure par entity_id si le hub est résolu
            if hub in entity_index:
                eid = entity_index[hub]
                object_index.pop(eid, None)
                subject_index.pop(eid, None)
        self._cross_doc_stats["hubs_excluded"] = len(hub_entities)

        # Join keys = intersection des deux index
        join_keys = set(object_index.keys()) & set(subject_index.keys())

        # Générer toutes les paires candidates cross-doc
        all_candidates: List[Tuple[float, float, str, str, Dict, Dict, str, str]] = []

        for join_key in sorted(join_keys):
            if len(join_key) < 3 or not is_valid_entity_name(join_key):
                continue

            self._cross_doc_stats["join_keys_found"] += 1

            sources = object_index[join_key]
            targets = subject_index[join_key]

            # Fréquence du join_key (nombre de claims le touchant)
            all_claim_ids = set()
            for cd in sources:
                all_claim_ids.add(cd["claim_id"])
            for cd in targets:
                all_claim_ids.add(cd["claim_id"])
            freq = len(all_claim_ids)

            jk_idf = idf_map.get(join_key, 0.0)

            # FIX: Plancher IDF — rejeter les join_keys trop génériques
            if min_idf > 0 and jk_idf < min_idf:
                self._cross_doc_stats["join_keys_below_min_idf"] += 1
                continue

            # Paires candidates : uniquement cross-doc
            candidates_for_key: List[Tuple[float, float, str, str, Dict, Dict, str]] = []
            for src in sources:
                for tgt in targets:
                    if src["doc_id"] == tgt["doc_id"]:
                        continue
                    if src["claim_id"] == tgt["claim_id"]:
                        continue

                    # FIX: Exclure les paires de claims au texte identique
                    src_text = src.get("text", "")
                    tgt_text = tgt.get("text", "")
                    if src_text and tgt_text and src_text == tgt_text:
                        self._cross_doc_stats["duplicate_text_skipped"] += 1
                        continue

                    # Cycle trivial
                    src_sf = src["structured_form"]
                    tgt_sf = tgt["structured_form"]
                    src_subj_norm = Entity.normalize(src_sf["subject"])
                    tgt_obj_norm = Entity.normalize(tgt_sf["object"])
                    if src_subj_norm == tgt_obj_norm and src_subj_norm == join_key:
                        continue

                    # Score prédicat (max des deux)
                    src_pred_score = PREDICATE_PRIORITY.get(
                        src_sf["predicate"].upper(), 0
                    )
                    tgt_pred_score = PREDICATE_PRIORITY.get(
                        tgt_sf["predicate"].upper(), 0
                    )
                    pred_score = max(src_pred_score, tgt_pred_score)

                    # Méthode de jointure (entity_id si au moins un côté résolu)
                    method = "normalized_name"
                    if src.get("_obj_method") == "entity_id" or tgt.get("_subj_method") == "entity_id":
                        method = "entity_id"

                    candidates_for_key.append((
                        pred_score, jk_idf,
                        src["claim_id"], tgt["claim_id"],
                        src, tgt, method,
                    ))

            # Ranking déterministe : -pred_score (desc), -idf (desc), claim_ids (asc)
            candidates_for_key.sort(
                key=lambda c: (-c[0], -c[1], c[2], c[3])
            )

            # Cap per join_key
            if len(candidates_for_key) > self.max_edges_per_key_cross_doc:
                self._cross_doc_stats["join_keys_capped"] += 1
                candidates_for_key = candidates_for_key[:self.max_edges_per_key_cross_doc]

            for cand in candidates_for_key:
                all_candidates.append((*cand, join_key))

        # Appliquer le cap per doc_pair et dédup
        seen_pairs: set = set()
        doc_pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        links: List[ChainLink] = []

        # Trier globalement par ranking pour que le cap doc_pair prenne les meilleurs
        all_candidates.sort(
            key=lambda c: (-c[0], -c[1], c[2], c[3])
        )

        for (pred_score, jk_idf, src_id, tgt_id, src, tgt, method, join_key) in all_candidates:
            pair_key = (src_id, tgt_id)
            if pair_key in seen_pairs:
                continue

            # Cap per doc_pair (clé canonique triée pour bidirectionnel)
            dp = tuple(sorted((src["doc_id"], tgt["doc_id"])))
            if doc_pair_counts[dp] >= self.max_edges_per_doc_pair:
                self._cross_doc_stats["doc_pairs_capped"] += 1
                continue

            seen_pairs.add(pair_key)
            doc_pair_counts[dp] += 1

            # Fréquence du join_key
            freq = (
                len(object_index.get(join_key, []))
                + len(subject_index.get(join_key, []))
            )

            if method == "entity_id":
                self._cross_doc_stats["joins_by_entity_id"] += 1
            else:
                self._cross_doc_stats["joins_by_normalized"] += 1

            src_sf = src["structured_form"]
            tgt_sf = tgt["structured_form"]

            link = ChainLink(
                source_claim_id=src_id,
                target_claim_id=tgt_id,
                join_key=join_key,
                source_predicate=src_sf.get("predicate", ""),
                target_predicate=tgt_sf.get("predicate", ""),
                doc_id=f"{src['doc_id']}↔{tgt['doc_id']}",
                join_key_freq=freq,
                source_doc_id=src["doc_id"],
                target_doc_id=tgt["doc_id"],
                is_cross_doc=True,
                join_key_idf=jk_idf,
                join_method=method,
                join_key_name=src.get("_obj_norm", join_key),
            )
            links.append(link)

        self._cross_doc_stats["chains_detected"] = len(links)
        return links

    # ---------------------------------------------------------------
    # Utilitaires
    # ---------------------------------------------------------------

    @staticmethod
    def _filter_valid_claims(claim_dicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filtre les claims avec SF valide et prédicat canonique."""
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
            if pred.upper() not in _CANONICAL_PREDICATES:
                continue
            valid.append(cd)
        return valid

    @staticmethod
    def _resolve_join_key(
        name: str,
        entity_index: Dict[str, str],
    ) -> Tuple[str, str, str]:
        """
        Résout un nom d'entity vers sa clé de jointure.

        Si entity_index contient le nom normalisé → utilise entity_id (robuste).
        Sinon → fallback sur Entity.normalize(name).

        Returns:
            Tuple (join_key, method, normalized_name) — normalized_name toujours
            le nom lisible, même quand join_key est un entity_id.
        """
        norm = Entity.normalize(name)
        if norm in entity_index:
            return entity_index[norm], "entity_id", norm
        return norm, "normalized_name", norm

    @staticmethod
    def compute_idf(
        claim_dicts: List[Dict[str, Any]],
        entity_index: Optional[Dict[str, str]] = None,
    ) -> Dict[str, float]:
        """
        Calcule l'IDF (Inverse Document Frequency) pour chaque join_key.

        IDF = log(total_claims_with_sf / nb_claims_mentioning_key)
        Plus l'IDF est haut, plus le join_key est rare/informatif.

        Args:
            claim_dicts: Claims avec SF valides
            entity_index: Mapping normalized_name → entity_id (optionnel)

        Returns:
            Dict join_key → IDF score
        """
        if entity_index is None:
            entity_index = {}

        total = len(claim_dicts)
        if total == 0:
            return {}

        # Compter le nombre de claims mentionnant chaque key (sujet ou objet)
        key_claim_count: Dict[str, int] = defaultdict(int)

        for cd in claim_dicts:
            sf = cd.get("structured_form")
            if not sf:
                continue
            keys_in_claim: set = set()
            for field_name in ("subject", "object"):
                val = sf.get(field_name, "")
                if val:
                    norm = Entity.normalize(val)
                    if norm in entity_index:
                        keys_in_claim.add(entity_index[norm])
                    else:
                        keys_in_claim.add(norm)
            for key in keys_in_claim:
                key_claim_count[key] += 1

        idf_map: Dict[str, float] = {}
        for key, count in key_claim_count.items():
            idf_map[key] = math.log(total / count) if count > 0 else 0.0

        return idf_map

    def get_stats(self) -> dict:
        return dict(self._stats)

    def get_cross_doc_stats(self) -> dict:
        return dict(self._cross_doc_stats)

    def reset_stats(self) -> None:
        for key in self._stats:
            self._stats[key] = 0

    def reset_cross_doc_stats(self) -> None:
        for key in self._cross_doc_stats:
            self._cross_doc_stats[key] = 0
