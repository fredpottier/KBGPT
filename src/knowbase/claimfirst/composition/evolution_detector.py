# src/knowbase/claimfirst/composition/evolution_detector.py
"""
Détection d'évolution temporelle entre documents — CRR Evolution Tracker.

Compare des documents successifs (même ComparableSubject, axes différents)
pour détecter les claims inchangées, modifiées, ajoutées ou supprimées.

Invariants architecturaux (review ChatGPT 2026-02-12) :
1. Paires adjacentes uniquement (pas O(n²))
2. ABSTAIN si axe ambigu (ordering_confidence == UNKNOWN ou value_order IS NULL)
3. Guard-rail multi-candidats S+P (skip si N>1 match dans un doc)
4. Stockage old_object_raw / new_object_raw (pas juste diff_summary)
5. Propriétés obligatoires pour method=version_evolution
6. V0 = S+P/O (fingerprint déterministe)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.entity import Entity

logger = logging.getLogger(__name__)

# Priorité des axes pour la détection "auto" — déterministe et stable
AXIS_PRIORITY = ["release_id", "version", "year", "effective_date", "edition", "phase"]


class ClaimEvolution(str, Enum):
    """Type d'évolution entre deux claims de versions successives."""

    UNCHANGED = "unchanged"
    """Même fingerprint S|P|O entre les deux versions."""

    MODIFIED = "modified"
    """Même S+P, objet différent entre les deux versions."""

    ADDED = "added"
    """Claim présente uniquement dans la version la plus récente."""

    REMOVED = "removed"
    """Claim présente uniquement dans la version la plus ancienne."""


@dataclass
class VersionPair:
    """Paire de documents adjacents représentant deux versions du même sujet."""

    subject_id: str
    subject_name: str
    old_doc_id: str
    new_doc_id: str
    old_value: str
    new_value: str
    axis_key: str
    # Niveau de confiance dans l'axe (reco ChatGPT)
    axis_confidence: str = "primary_axis"  # "primary_axis" | "heuristic" | "unknown"


@dataclass
class EvolutionLink:
    """Lien d'évolution détecté entre deux claims de versions successives."""

    source_claim_id: str  # claim dans old_doc ("" si ADDED)
    target_claim_id: str  # claim dans new_doc ("" si REMOVED)
    evolution_type: ClaimEvolution
    version_pair: VersionPair
    similarity_score: float  # 1.0 si unchanged
    diff_summary: str  # "object: X -> Y" si modified, "" sinon
    old_object_raw: str  # valeur brute objet ancien (reco ChatGPT)
    new_object_raw: str  # valeur brute objet nouveau (reco ChatGPT)


def _spo_fingerprint(sf: Dict[str, str]) -> str:
    """
    Fingerprint déterministe S|P|O pour comparaison exacte.

    Normalise sujet et objet via Entity.normalize(), uppercase le prédicat.
    """
    s = Entity.normalize(sf.get("subject", ""))
    p = sf.get("predicate", "").upper()
    o = Entity.normalize(sf.get("object", ""))
    return f"{s}|{p}|{o}"


def _sp_key(sf: Dict[str, str]) -> str:
    """Clé S+P pour détection de modifications (même sujet+prédicat, objet diff)."""
    s = Entity.normalize(sf.get("subject", ""))
    p = sf.get("predicate", "").upper()
    return f"{s}|{p}"


def validate_evolution_edge_props(props: Dict[str, Any]) -> None:
    """
    Valide que toutes les propriétés obligatoires sont présentes
    pour un edge CHAINS_TO method=version_evolution.

    Raises:
        ValueError: si un champ obligatoire manque.
    """
    required = [
        "method", "chain_type", "cross_doc",
        "comparable_subject_id", "axis_key",
        "old_axis_value", "new_axis_value",
        "evolution_type", "similarity_score",
    ]
    missing = [k for k in required if props.get(k) is None]
    if missing:
        raise ValueError(
            f"Propriétés obligatoires manquantes pour version_evolution: {missing}"
        )


class VersionEvolutionDetector:
    """
    Détecte l'évolution temporelle entre documents successifs.

    Usage :
        detector = VersionEvolutionDetector()
        pairs = detector.detect_version_pairs(session, tenant_id)
        for pair in pairs:
            old_claims = load_claims(pair.old_doc_id)
            new_claims = load_claims(pair.new_doc_id)
            links = detector.compare_claims(old_claims, new_claims, pair)
    """

    def __init__(self, axis_priority: Optional[List[str]] = None):
        self.axis_priority = axis_priority or AXIS_PRIORITY
        self._stats: Dict[str, int] = defaultdict(int)

    def get_stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def reset_stats(self) -> None:
        self._stats = defaultdict(int)

    # ---------------------------------------------------------------
    # Version Pair Detection
    # ---------------------------------------------------------------

    def detect_version_pairs(
        self,
        session,
        tenant_id: str,
    ) -> List[VersionPair]:
        """
        Détecte les paires de documents adjacents (versions successives).

        Algorithme (chaînage adjacent, pas O(n²)) :
        1. Trouver les ComparableSubject avec doc_count >= 2
        2. Pour chaque CS, charger les DocumentContext via ABOUT_COMPARABLE
        3. Choisir l'axe primaire (premier orderable dans axis_priority)
        4. ABSTAIN si pas d'axe orderable ou ordering_confidence == UNKNOWN
        5. Trier par valeur d'axe, générer paires adjacentes uniquement

        Args:
            session: Neo4j session
            tenant_id: Tenant ID

        Returns:
            Liste de VersionPair ordonnées
        """
        # Query : ComparableSubject → DocumentContext → HAS_AXIS_VALUE
        cypher = """
        MATCH (cs:ComparableSubject {tenant_id: $tid})
        WHERE cs.doc_count >= 2
        MATCH (dc:DocumentContext)-[:ABOUT_COMPARABLE]->(cs)
        OPTIONAL MATCH (dc)-[hav:HAS_AXIS_VALUE]->(ax:ApplicabilityAxis)
        RETURN cs.subject_id AS subject_id,
               cs.canonical_name AS subject_name,
               dc.doc_id AS doc_id,
               dc.qualifiers AS qualifiers,
               dc.temporal_scope AS temporal_scope,
               collect(DISTINCT {
                   axis_key: ax.axis_key,
                   is_orderable: ax.is_orderable,
                   ordering_confidence: ax.ordering_confidence,
                   value_order: ax.value_order,
                   scalar_value: hav.scalar_value
               }) AS axis_data
        ORDER BY cs.subject_id, dc.doc_id
        """

        result = session.run(cypher, tid=tenant_id)
        records = [dict(r) for r in result]

        if not records:
            return []

        # Grouper par subject_id
        subjects: Dict[str, List[Dict]] = defaultdict(list)
        for rec in records:
            subjects[rec["subject_id"]].append(rec)

        self._stats["comparable_subjects_found"] = len(subjects)

        pairs: List[VersionPair] = []

        for subject_id, docs in subjects.items():
            if len(docs) < 2:
                continue

            subject_name = docs[0]["subject_name"]

            # Chercher l'axe primaire (premier orderable dans axis_priority)
            chosen_axis = self._choose_primary_axis(docs)

            if chosen_axis is None:
                # Fallback heuristique : qualifiers["year"] ou temporal_scope
                fallback_pairs = self._fallback_year_heuristic(
                    docs, subject_id, subject_name
                )
                pairs.extend(fallback_pairs)
                self._stats["subjects_heuristic_fallback"] += 1
                continue

            axis_key, confidence = chosen_axis

            # Extraire (doc_id, scalar_value) pour l'axe choisi
            doc_values: List[Tuple[str, str]] = []
            for doc in docs:
                for ad in doc["axis_data"]:
                    if ad.get("axis_key") == axis_key and ad.get("scalar_value"):
                        doc_values.append((doc["doc_id"], ad["scalar_value"]))
                        break

            if len(doc_values) < 2:
                self._stats["subjects_insufficient_axis_values"] += 1
                continue

            # Trier par value_order de l'axe
            value_order = None
            for doc in docs:
                for ad in doc["axis_data"]:
                    if ad.get("axis_key") == axis_key and ad.get("value_order"):
                        value_order = ad["value_order"]
                        break
                if value_order:
                    break

            if value_order:
                # Tri par position dans value_order
                def sort_key(dv):
                    try:
                        return value_order.index(dv[1])
                    except ValueError:
                        return 999999  # valeur inconnue → à la fin

                doc_values.sort(key=sort_key)
            else:
                # Tri lexicographique (best effort pour "2021" < "2022")
                doc_values.sort(key=lambda dv: dv[1])

            # Vérifier unicité des valeurs (pas de tie)
            values_seen = [dv[1] for dv in doc_values]
            if len(set(values_seen)) < len(values_seen):
                # Tie : plusieurs docs avec la même valeur → ABSTAIN
                self._stats["subjects_tie_abstain"] += 1
                continue

            # Paires adjacentes uniquement
            for i in range(len(doc_values) - 1):
                old_doc_id, old_value = doc_values[i]
                new_doc_id, new_value = doc_values[i + 1]

                pair = VersionPair(
                    subject_id=subject_id,
                    subject_name=subject_name,
                    old_doc_id=old_doc_id,
                    new_doc_id=new_doc_id,
                    old_value=old_value,
                    new_value=new_value,
                    axis_key=axis_key,
                    axis_confidence=confidence,
                )
                pairs.append(pair)

        self._stats["version_pairs_detected"] = len(pairs)
        return pairs

    def _choose_primary_axis(
        self, docs: List[Dict]
    ) -> Optional[Tuple[str, str]]:
        """
        Choisit l'axe primaire selon axis_priority.

        Returns:
            (axis_key, confidence) ou None si aucun axe orderable.
            ABSTAIN si plusieurs axes de même priorité sont présents.
        """
        # Collecter tous les axes orderable trouvés dans les docs
        available_axes: Dict[str, str] = {}  # axis_key → ordering_confidence
        for doc in docs:
            for ad in doc["axis_data"]:
                ak = ad.get("axis_key")
                if not ak:
                    continue
                if not ad.get("is_orderable", False):
                    continue
                oc = ad.get("ordering_confidence", "unknown")
                # ABSTAIN si ordering_confidence == UNKNOWN
                if oc == "unknown":
                    continue
                available_axes[ak] = oc

        if not available_axes:
            return None

        # Choisir par priorité stable
        for priority_key in self.axis_priority:
            if priority_key in available_axes:
                return priority_key, available_axes[priority_key]

        # Aucun axe dans la liste de priorité → ABSTAIN
        # (reco ChatGPT : si plusieurs axes de priorité égale → ABSTAIN)
        self._stats["subjects_no_priority_axis"] += 1
        return None

    def _fallback_year_heuristic(
        self,
        docs: List[Dict],
        subject_id: str,
        subject_name: str,
    ) -> List[VersionPair]:
        """
        Fallback : utiliser qualifiers["year"] ou temporal_scope pour ordonner.

        Marque axis_confidence = "heuristic".
        """
        doc_years: List[Tuple[str, str]] = []
        for doc in docs:
            year = None
            qualifiers = doc.get("qualifiers")
            if isinstance(qualifiers, dict):
                year = qualifiers.get("year")
            if not year:
                ts = doc.get("temporal_scope", "")
                if ts:
                    # Essayer d'extraire une année 4 chiffres
                    import re
                    m = re.search(r"(20\d{2})", ts)
                    if m:
                        year = m.group(1)
            if year:
                doc_years.append((doc["doc_id"], year))

        if len(doc_years) < 2:
            return []

        # Trier par année
        doc_years.sort(key=lambda dy: dy[1])

        # Vérifier unicité
        years = [dy[1] for dy in doc_years]
        if len(set(years)) < len(years):
            self._stats["subjects_tie_abstain"] += 1
            return []

        # Paires adjacentes
        pairs = []
        for i in range(len(doc_years) - 1):
            pairs.append(VersionPair(
                subject_id=subject_id,
                subject_name=subject_name,
                old_doc_id=doc_years[i][0],
                new_doc_id=doc_years[i + 1][0],
                old_value=doc_years[i][1],
                new_value=doc_years[i + 1][1],
                axis_key="year_heuristic",
                axis_confidence="heuristic",
            ))
        return pairs

    # ---------------------------------------------------------------
    # Claim Comparison
    # ---------------------------------------------------------------

    def compare_claims(
        self,
        old_claims: List[Dict[str, Any]],
        new_claims: List[Dict[str, Any]],
        version_pair: VersionPair,
    ) -> List[EvolutionLink]:
        """
        Compare les claims entre deux versions d'un document.

        Algorithme V0 (fingerprint S|P|O déterministe) :
        1. UNCHANGED : même fingerprint(S,P,O) dans les deux docs
        2. MODIFIED : même S+P, objet différent (guard-rail : skip si >1 match)
        3. ADDED : claim uniquement dans new
        4. REMOVED : claim uniquement dans old

        Args:
            old_claims: Claims de l'ancienne version (avec structured_form)
            new_claims: Claims de la nouvelle version (avec structured_form)
            version_pair: Contexte de la paire de versions

        Returns:
            Liste d'EvolutionLink
        """
        links: List[EvolutionLink] = []
        matched_old_ids: set = set()
        matched_new_ids: set = set()

        # 1. Indexer par fingerprint SPO et par clé SP
        old_by_fp: Dict[str, List[Dict]] = defaultdict(list)
        new_by_fp: Dict[str, List[Dict]] = defaultdict(list)
        old_by_sp: Dict[str, List[Dict]] = defaultdict(list)
        new_by_sp: Dict[str, List[Dict]] = defaultdict(list)

        for c in old_claims:
            sf = c.get("structured_form")
            if not sf:
                continue
            fp = _spo_fingerprint(sf)
            sp = _sp_key(sf)
            old_by_fp[fp].append(c)
            old_by_sp[sp].append(c)

        for c in new_claims:
            sf = c.get("structured_form")
            if not sf:
                continue
            fp = _spo_fingerprint(sf)
            sp = _sp_key(sf)
            new_by_fp[fp].append(c)
            new_by_sp[sp].append(c)

        # 2. Phase 1 : UNCHANGED (fingerprint match exact)
        for fp in set(old_by_fp.keys()) & set(new_by_fp.keys()):
            old_group = old_by_fp[fp]
            new_group = new_by_fp[fp]

            # Apparier 1-1 (premier de chaque groupe)
            for i, (oc, nc) in enumerate(zip(old_group, new_group)):
                oc_id = oc["claim_id"]
                nc_id = nc["claim_id"]
                if oc_id in matched_old_ids or nc_id in matched_new_ids:
                    continue

                sf = oc["structured_form"]
                links.append(EvolutionLink(
                    source_claim_id=oc_id,
                    target_claim_id=nc_id,
                    evolution_type=ClaimEvolution.UNCHANGED,
                    version_pair=version_pair,
                    similarity_score=1.0,
                    diff_summary="",
                    old_object_raw=sf.get("object", ""),
                    new_object_raw=sf.get("object", ""),
                ))
                matched_old_ids.add(oc_id)
                matched_new_ids.add(nc_id)

        self._stats["unchanged"] += sum(
            1 for l in links if l.evolution_type == ClaimEvolution.UNCHANGED
        )

        # 3. Phase 2 : MODIFIED (même S+P, objet différent)
        for sp in set(old_by_sp.keys()) & set(new_by_sp.keys()):
            # Filtrer les claims déjà matched
            old_remaining = [
                c for c in old_by_sp[sp]
                if c["claim_id"] not in matched_old_ids
            ]
            new_remaining = [
                c for c in new_by_sp[sp]
                if c["claim_id"] not in matched_new_ids
            ]

            if not old_remaining or not new_remaining:
                continue

            # Guard-rail multi-candidats (reco ChatGPT) :
            # Si N>1 d'un côté → skip (pas de choix arbitraire)
            if len(old_remaining) != 1 or len(new_remaining) != 1:
                self._stats["modified_skipped_ambiguous"] += 1
                continue

            oc = old_remaining[0]
            nc = new_remaining[0]
            old_sf = oc["structured_form"]
            new_sf = nc["structured_form"]

            old_obj = old_sf.get("object", "")
            new_obj = new_sf.get("object", "")

            # Vérifier que l'objet est bien différent (sinon c'est unchanged via un path différent)
            if Entity.normalize(old_obj) == Entity.normalize(new_obj):
                continue

            links.append(EvolutionLink(
                source_claim_id=oc["claim_id"],
                target_claim_id=nc["claim_id"],
                evolution_type=ClaimEvolution.MODIFIED,
                version_pair=version_pair,
                similarity_score=0.7,
                diff_summary=f"object: {old_obj} -> {new_obj}",
                old_object_raw=old_obj,
                new_object_raw=new_obj,
            ))
            matched_old_ids.add(oc["claim_id"])
            matched_new_ids.add(nc["claim_id"])

        self._stats["modified"] += sum(
            1 for l in links if l.evolution_type == ClaimEvolution.MODIFIED
        )

        # 4. Phase 3 : ADDED / REMOVED (claims non appariées)
        for c in old_claims:
            sf = c.get("structured_form")
            if not sf:
                continue
            if c["claim_id"] not in matched_old_ids:
                links.append(EvolutionLink(
                    source_claim_id=c["claim_id"],
                    target_claim_id="",
                    evolution_type=ClaimEvolution.REMOVED,
                    version_pair=version_pair,
                    similarity_score=0.0,
                    diff_summary="",
                    old_object_raw=sf.get("object", ""),
                    new_object_raw="",
                ))

        for c in new_claims:
            sf = c.get("structured_form")
            if not sf:
                continue
            if c["claim_id"] not in matched_new_ids:
                links.append(EvolutionLink(
                    source_claim_id="",
                    target_claim_id=c["claim_id"],
                    evolution_type=ClaimEvolution.ADDED,
                    version_pair=version_pair,
                    similarity_score=0.0,
                    diff_summary="",
                    old_object_raw="",
                    new_object_raw=sf.get("object", ""),
                ))

        self._stats["added"] += sum(
            1 for l in links if l.evolution_type == ClaimEvolution.ADDED
        )
        self._stats["removed"] += sum(
            1 for l in links if l.evolution_type == ClaimEvolution.REMOVED
        )

        return links


__all__ = [
    "VersionEvolutionDetector",
    "VersionPair",
    "EvolutionLink",
    "ClaimEvolution",
    "validate_evolution_edge_props",
    "AXIS_PRIORITY",
]
