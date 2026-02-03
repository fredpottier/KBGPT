# src/knowbase/claimfirst/clustering/relation_detector.py
"""
RelationDetector - Détection de relations entre Claims.

Relations détectées:
- CONTRADICTS: Claims incompatibles sur même sujet
- REFINES: Claim A précise/détaille Claim B
- QUALIFIES: Claim A conditionne/nuance Claim B

INV-6: Règle d'abstention stricte.
Si pas sûr → pas de lien.
Faux positifs en contradiction détruisent la confiance.

Note: Les relations CONTRADICTS sont particulièrement sensibles.
Optionnel: POTENTIAL_CONFLICT pour review humain.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.result import ClaimRelation, RelationType, ClaimCluster

logger = logging.getLogger(__name__)


# Patterns de raffinement
REFINEMENT_PATTERNS = [
    (r"specifically", 0.8),
    (r"in particular", 0.8),
    (r"more precisely", 0.9),
    (r"for example", 0.7),
    (r"such as", 0.7),
    (r"including", 0.6),
    (r"namely", 0.8),
]

# Patterns de qualification
QUALIFICATION_PATTERNS = [
    (r"\bif\b", 0.7),
    (r"\bwhen\b", 0.6),
    (r"\bunless\b", 0.8),
    (r"\bexcept\b", 0.8),
    (r"\bprovided that\b", 0.9),
    (r"\bon condition\b", 0.9),
    (r"\bhowever\b", 0.7),
    (r"\balthough\b", 0.7),
]

# Patterns de contradiction
CONTRADICTION_INDICATORS = [
    (r"\bnot\b.*\brequired\b", r"\brequired\b"),
    (r"\bnot\b.*\bsupported\b", r"\bsupported\b"),
    (r"\bdisabled\b", r"\benabled\b"),
    (r"\bprohibited\b", r"\ballowed\b"),
    (r"\bforbidden\b", r"\bpermitted\b"),
    (r"\bmust not\b", r"\bmust\b"),
    (r"\bcannot\b", r"\bcan\b"),
]


class RelationDetector:
    """
    Détecteur de relations entre Claims.

    Détecte CONTRADICTS, REFINES, QUALIFIES.

    INV-6: Règle d'abstention stricte.
    Si pas sûr → pas de lien.
    """

    def __init__(
        self,
        min_confidence: float = 0.7,
        detect_contradicts: bool = True,
        detect_refines: bool = True,
        detect_qualifies: bool = True,
        flag_potential_conflicts: bool = True,
    ):
        """
        Initialise le détecteur.

        Args:
            min_confidence: Confiance minimale pour créer une relation
            detect_contradicts: Détecter les contradictions
            detect_refines: Détecter les raffinements
            detect_qualifies: Détecter les qualifications
            flag_potential_conflicts: Créer POTENTIAL_CONFLICT pour review
        """
        self.min_confidence = min_confidence
        self.detect_contradicts = detect_contradicts
        self.detect_refines = detect_refines
        self.detect_qualifies = detect_qualifies
        self.flag_potential_conflicts = flag_potential_conflicts

        self.stats = {
            "pairs_analyzed": 0,
            "contradicts_found": 0,
            "refines_found": 0,
            "qualifies_found": 0,
            "potential_conflicts": 0,
            "abstentions": 0,
        }

    def detect(
        self,
        claims: List[Claim],
        clusters: Optional[List[ClaimCluster]] = None,
        entities_by_claim: Optional[Dict[str, List[str]]] = None,
    ) -> List[ClaimRelation]:
        """
        Détecte les relations entre claims.

        Args:
            claims: Claims à analyser
            clusters: Clusters pour limiter la recherche (optionnel)
            entities_by_claim: Dict claim_id → [entity_ids] (optionnel)

        Returns:
            Liste de ClaimRelations
        """
        relations: List[ClaimRelation] = []

        # Si clusters fournis, analyser uniquement intra-cluster
        if clusters:
            pairs = self._get_cluster_pairs(claims, clusters)
        else:
            # Sinon, analyser toutes les pairs (coûteux!)
            pairs = [
                (claims[i], claims[j])
                for i in range(len(claims))
                for j in range(i + 1, len(claims))
            ]

        logger.info(
            f"[OSMOSE:RelationDetector] Analyzing {len(pairs)} claim pairs..."
        )

        for c1, c2 in pairs:
            self.stats["pairs_analyzed"] += 1

            # Skip si claims du même document et même passage
            # (pas de contradiction intra-passage normalement)
            if c1.doc_id == c2.doc_id and c1.passage_id == c2.passage_id:
                continue

            # Détecter les relations
            rel = self._detect_relation(c1, c2, entities_by_claim)
            if rel:
                relations.append(rel)

        logger.info(
            f"[OSMOSE:RelationDetector] Found {len(relations)} relations "
            f"({self.stats['contradicts_found']} contradicts, "
            f"{self.stats['refines_found']} refines, "
            f"{self.stats['qualifies_found']} qualifies)"
        )

        return relations

    def _get_cluster_pairs(
        self,
        claims: List[Claim],
        clusters: List[ClaimCluster],
    ) -> List[Tuple[Claim, Claim]]:
        """
        Génère les pairs de claims intra-cluster.

        Optimisation: ne comparer que les claims du même cluster.
        """
        pairs = []
        claim_index = {c.claim_id: c for c in claims}

        for cluster in clusters:
            cluster_claims = [
                claim_index[cid]
                for cid in cluster.claim_ids
                if cid in claim_index
            ]

            for i, c1 in enumerate(cluster_claims):
                for c2 in cluster_claims[i + 1:]:
                    pairs.append((c1, c2))

        return pairs

    def _detect_relation(
        self,
        c1: Claim,
        c2: Claim,
        entities_by_claim: Optional[Dict[str, List[str]]],
    ) -> Optional[ClaimRelation]:
        """
        Détecte la relation entre deux claims.

        Ordre de priorité:
        1. CONTRADICTS (le plus critique)
        2. REFINES
        3. QUALIFIES
        """
        # Vérifier overlap sujet (via entités ou tokens)
        if not self._have_common_subject(c1, c2, entities_by_claim):
            return None

        # 1. Détecter CONTRADICTS
        if self.detect_contradicts:
            rel = self._detect_contradiction(c1, c2)
            if rel:
                return rel

        # 2. Détecter REFINES
        if self.detect_refines:
            rel = self._detect_refinement(c1, c2)
            if rel:
                return rel

        # 3. Détecter QUALIFIES
        if self.detect_qualifies:
            rel = self._detect_qualification(c1, c2)
            if rel:
                return rel

        return None

    def _have_common_subject(
        self,
        c1: Claim,
        c2: Claim,
        entities_by_claim: Optional[Dict[str, List[str]]],
    ) -> bool:
        """
        Vérifie si deux claims ont un sujet commun.

        Prérequis pour toute relation.
        """
        # Via entités
        if entities_by_claim:
            e1 = set(entities_by_claim.get(c1.claim_id, []))
            e2 = set(entities_by_claim.get(c2.claim_id, []))
            if e1 and e2:
                return bool(e1 & e2)

        # Fallback: tokens communs significatifs
        tokens1 = self._extract_significant_tokens(c1.text)
        tokens2 = self._extract_significant_tokens(c2.text)

        # Au moins 2 tokens significatifs en commun
        common = tokens1 & tokens2
        return len(common) >= 2

    def _detect_contradiction(
        self,
        c1: Claim,
        c2: Claim,
    ) -> Optional[ClaimRelation]:
        """
        Détecte une contradiction entre deux claims.

        ATTENTION: Très sensible aux faux positifs!
        INV-6: Abstention si doute.
        """
        text1 = c1.text.lower()
        text2 = c2.text.lower()

        # Pattern 1: Indicateurs de contradiction directs
        for neg_pattern, pos_pattern in CONTRADICTION_INDICATORS:
            # c1 négatif, c2 positif
            if re.search(neg_pattern, text1) and re.search(pos_pattern, text2):
                if not re.search(neg_pattern, text2):  # c2 n'est pas aussi négatif
                    confidence = 0.8
                    if confidence >= self.min_confidence:
                        self.stats["contradicts_found"] += 1
                        return ClaimRelation(
                            source_claim_id=c1.claim_id,
                            target_claim_id=c2.claim_id,
                            relation_type=RelationType.CONTRADICTS,
                            confidence=confidence,
                            basis=f"Pattern: {neg_pattern} vs {pos_pattern}",
                        )

            # c2 négatif, c1 positif
            if re.search(neg_pattern, text2) and re.search(pos_pattern, text1):
                if not re.search(neg_pattern, text1):
                    confidence = 0.8
                    if confidence >= self.min_confidence:
                        self.stats["contradicts_found"] += 1
                        return ClaimRelation(
                            source_claim_id=c2.claim_id,
                            target_claim_id=c1.claim_id,
                            relation_type=RelationType.CONTRADICTS,
                            confidence=confidence,
                            basis=f"Pattern: {neg_pattern} vs {pos_pattern}",
                        )

        # Pattern 2: Modalités contradictoires (must vs must not)
        if self._have_opposing_modalities(text1, text2):
            confidence = 0.75
            if confidence >= self.min_confidence:
                self.stats["contradicts_found"] += 1
                return ClaimRelation(
                    source_claim_id=c1.claim_id,
                    target_claim_id=c2.claim_id,
                    relation_type=RelationType.CONTRADICTS,
                    confidence=confidence,
                    basis="Opposing modalities",
                )

        # Flag potential conflict pour review si doute
        if self.flag_potential_conflicts:
            if self._looks_like_potential_conflict(c1, c2):
                self.stats["potential_conflicts"] += 1
                # Ne pas créer de relation, juste logger
                logger.info(
                    f"[OSMOSE:RelationDetector] Potential conflict: "
                    f"{c1.claim_id} vs {c2.claim_id}"
                )

        self.stats["abstentions"] += 1
        return None

    def _detect_refinement(
        self,
        c1: Claim,
        c2: Claim,
    ) -> Optional[ClaimRelation]:
        """
        Détecte si c1 raffine (précise) c2.

        c1 REFINES c2 si c1 ajoute du détail à c2.
        """
        text1 = c1.text.lower()

        # c1 contient des marqueurs de raffinement
        for pattern, base_conf in REFINEMENT_PATTERNS:
            if re.search(pattern, text1):
                # c1 est plus spécifique si plus long et contient plus de détails
                if len(c1.text) > len(c2.text) * 1.2:  # 20% plus long
                    confidence = base_conf
                    if confidence >= self.min_confidence:
                        self.stats["refines_found"] += 1
                        return ClaimRelation(
                            source_claim_id=c1.claim_id,
                            target_claim_id=c2.claim_id,
                            relation_type=RelationType.REFINES,
                            confidence=confidence,
                        )

        return None

    def _detect_qualification(
        self,
        c1: Claim,
        c2: Claim,
    ) -> Optional[ClaimRelation]:
        """
        Détecte si c1 qualifie (conditionne) c2.

        c1 QUALIFIES c2 si c1 ajoute une condition à c2.
        """
        text1 = c1.text.lower()

        # c1 contient des marqueurs de qualification
        for pattern, base_conf in QUALIFICATION_PATTERNS:
            if re.search(pattern, text1):
                # c1 est une qualification si c2 est plus général
                if len(c2.text) < len(c1.text):
                    confidence = base_conf
                    if confidence >= self.min_confidence:
                        self.stats["qualifies_found"] += 1
                        return ClaimRelation(
                            source_claim_id=c1.claim_id,
                            target_claim_id=c2.claim_id,
                            relation_type=RelationType.QUALIFIES,
                            confidence=confidence,
                        )

        return None

    def _have_opposing_modalities(self, text1: str, text2: str) -> bool:
        """
        Vérifie si deux textes ont des modalités opposées.

        Ex: "must" vs "must not", "can" vs "cannot"
        """
        strong1 = any(re.search(rf"\b{w}\b", text1) for w in ["must", "shall", "required"])
        strong2 = any(re.search(rf"\b{w}\b", text2) for w in ["must", "shall", "required"])

        neg1 = bool(re.search(r"\bnot\b|\bcannot\b|\bcan't\b", text1))
        neg2 = bool(re.search(r"\bnot\b|\bcannot\b|\bcan't\b", text2))

        # Même modalité forte mais négation opposée
        if strong1 and strong2:
            return neg1 != neg2

        return False

    def _looks_like_potential_conflict(self, c1: Claim, c2: Claim) -> bool:
        """
        Heuristique pour détecter un conflit potentiel.

        Utilisé pour flagging, pas pour créer une relation.
        """
        # Même type de claim + entités communes + valeurs différentes
        if c1.claim_type != c2.claim_type:
            return False

        # Check si les valeurs numériques diffèrent
        nums1 = re.findall(r"\d+(?:\.\d+)?", c1.text)
        nums2 = re.findall(r"\d+(?:\.\d+)?", c2.text)

        if nums1 and nums2 and set(nums1) != set(nums2):
            return True

        return False

    def _extract_significant_tokens(self, text: str) -> Set[str]:
        """Extrait les tokens significatifs (non stop words, > 3 chars)."""
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "must", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "and", "or", "but", "if", "this", "that", "these",
            "those", "which", "who", "what",
        }
        tokens = re.findall(r"\b[a-z]+\b", text.lower())
        return {t for t in tokens if t not in stop_words and len(t) > 3}

    def get_stats(self) -> dict:
        """Retourne les statistiques de détection."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "pairs_analyzed": 0,
            "contradicts_found": 0,
            "refines_found": 0,
            "qualifies_found": 0,
            "potential_conflicts": 0,
            "abstentions": 0,
        }


__all__ = [
    "RelationDetector",
    "REFINEMENT_PATTERNS",
    "QUALIFICATION_PATTERNS",
]
