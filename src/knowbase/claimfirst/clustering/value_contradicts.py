# src/knowbase/claimfirst/clustering/value_contradicts.py
"""
Value-level CONTRADICTS detection — module standalone.

Architecture 5 couches :
1. ClaimKey (bucket via canonical_entity_id | PREDICATE)
2. ContextGate (callback scope-aware, futur cross-doc)
3. ValueFrame (parse NUMBER/VERSION, tout le reste → UNTYPED)
4. FormalComparator (optimisation : COMPATIBLE/INCOMPARABLE, jamais CONTRADICTS)
5. LLM Arbiter (seul décideur de CONTRADICTS — dans relation_detector.py)

Ce module couvre les couches 1-4. La couche 5 (LLM) reste dans
relation_detector.py pour éviter les imports lourds.

Design rules:
- Imports légers uniquement (Entity model, re, dataclasses, enum)
- Testable sans Docker/Neo4j/LLM
- Le comparateur formel ne produit JAMAIS de verdict CONTRADICTS (GF-3)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.entity import Entity

logger = logging.getLogger(__name__)


# =============================================================================
# 1. ClaimKey — Modif A + GF-1 + GF-2
# =============================================================================


def build_claim_key(
    structured_form: Dict[str, str],
    claim_id: str = "",
    entities_by_claim: Optional[Dict[str, List[str]]] = None,
    entity_index: Optional[Dict[str, object]] = None,
) -> Optional[str]:
    """
    ClaimKey = subject_canonical_id|PREDICATE

    Priority pour le subject (GF-1: score-based best match):
    1. canonical entity_id avec meilleur score (exact=2, alias=1)
    2. Entity.normalize(subject) (fallback textuel)

    Returns None si structured_form incomplet.
    """
    if not structured_form:
        return None
    subject_raw = structured_form.get("subject", "")
    predicate = structured_form.get("predicate", "")
    if not subject_raw or not predicate:
        return None

    subject_key = _resolve_subject_key(
        subject_raw, claim_id, entities_by_claim, entity_index
    )
    return f"{subject_key}|{predicate.upper()}"


def _resolve_subject_key(
    subject_raw: str,
    claim_id: str,
    entities_by_claim: Optional[Dict[str, List[str]]],
    entity_index: Optional[Dict[str, object]],
) -> str:
    """
    Résout le subject vers un ID canonical par scoring (GF-1).

    Score: exact normalized_name match → 2, alias match → 1
    Prend le meilleur score. Si aucun > 0 → fallback normalize(text).
    """
    subject_normalized = Entity.normalize(subject_raw)

    if entities_by_claim and entity_index and claim_id:
        entity_ids = entities_by_claim.get(claim_id, [])
        best_eid: Optional[str] = None
        best_score = 0

        for eid in entity_ids:
            entity = entity_index.get(eid)
            if not entity:
                continue
            # Score 2: exact match sur normalized_name
            if getattr(entity, "normalized_name", "") == subject_normalized:
                if 2 > best_score:
                    best_score = 2
                    best_eid = eid
            else:
                # Score 1: match sur alias
                for alias in getattr(entity, "aliases", []):
                    if Entity.normalize(alias) == subject_normalized:
                        if 1 > best_score:
                            best_score = 1
                            best_eid = eid
                        break

        if best_eid:
            return best_eid

    # Fallback textuel
    return subject_normalized


def have_comparable_claim_keys(
    c1,
    c2,
    entities_by_claim: Optional[Dict[str, List[str]]] = None,
    entity_index: Optional[Dict[str, object]] = None,
) -> bool:
    """
    Vérifie si deux claims sont comparables (GF-2: fallback entity overlap).

    1. ClaimKey identique → True (chemin principal)
    2. Sinon: même predicate ET au moins 1 entity_id en commun → True (fallback)
    3. Sinon → False
    """
    sf1 = getattr(c1, "structured_form", None) or {}
    sf2 = getattr(c2, "structured_form", None) or {}
    if not sf1 or not sf2:
        return False

    claim_id_1 = getattr(c1, "claim_id", "")
    claim_id_2 = getattr(c2, "claim_id", "")

    # Chemin principal : ClaimKey identique
    key1 = build_claim_key(sf1, claim_id_1, entities_by_claim, entity_index)
    key2 = build_claim_key(sf2, claim_id_2, entities_by_claim, entity_index)
    if key1 and key2 and key1 == key2:
        return True

    # Fallback GF-2 : même predicate + entity overlap
    pred1 = sf1.get("predicate", "").upper()
    pred2 = sf2.get("predicate", "").upper()
    if pred1 != pred2 or not pred1:
        return False

    if entities_by_claim:
        e1 = set(entities_by_claim.get(claim_id_1, []))
        e2 = set(entities_by_claim.get(claim_id_2, []))
        if e1 and e2 and (e1 & e2):
            return True

    return False


# =============================================================================
# 2. ValueFrame — Modif B : regex NUMBER/VERSION uniquement
# =============================================================================


class ValueType(str, Enum):
    NUMBER = "number"
    VERSION = "version"
    UNTYPED = "untyped"


@dataclass
class ValueFrame:
    value_type: ValueType
    raw_text: str
    parsed_value: object  # float pour NUMBER, tuple pour VERSION, None pour UNTYPED
    unit: Optional[str]


# Regex cross-langue (chiffres et ponctuation uniquement)
VERSION_STRICT = re.compile(r"^v?(\d+(?:\.\d+)+)$", re.IGNORECASE)
NUMBER_WITH_UNIT = re.compile(
    r"^(\d+(?:[.,]\d+)?)\s*"
    r"(GB|MB|KB|TB|GiB|MiB|%|ms|s|min|hrs?|days?|months?|years?)?\s*$",
    re.IGNORECASE,
)


def parse_value_frame(object_text: str) -> ValueFrame:
    """
    Parse structured_form.object en ValueFrame.

    Regex UNIQUEMENT pour NUMBER et VERSION (cross-langue, 0 dette lexicale).
    Tout le reste → UNTYPED (sera traité par LLM arbiter).
    """
    text = object_text.strip()
    if not text:
        return ValueFrame(ValueType.UNTYPED, object_text, None, None)

    # 1. VERSION stricte : digits.digits(.digits)*
    ver_match = VERSION_STRICT.match(text)
    if ver_match:
        parts = tuple(int(p) for p in ver_match.group(1).split("."))
        return ValueFrame(ValueType.VERSION, object_text, parts, None)

    # 2. NUMBER avec unité optionnelle
    num_match = NUMBER_WITH_UNIT.match(text)
    if num_match:
        raw_num = num_match.group(1).replace(",", ".")
        value = float(raw_num)
        unit = num_match.group(2)
        return ValueFrame(ValueType.NUMBER, object_text, value, unit)

    # 3. Tout le reste → UNTYPED
    return ValueFrame(ValueType.UNTYPED, object_text, None, None)


# =============================================================================
# 3. FormalComparator — optimisation uniquement (GF-3)
# =============================================================================


class ContradictionVerdict(str, Enum):
    COMPATIBLE = "compatible"
    NEED_LLM = "need_llm"
    INCOMPARABLE = "incomparable"


@dataclass
class ContradictionResult:
    verdict: ContradictionVerdict
    confidence: float
    basis: str
    value_type: ValueType


def compare_values(vf1: ValueFrame, vf2: ValueFrame) -> ContradictionResult:
    """
    Comparaison formelle — OPTIMISATION uniquement.

    GF-3 : Ne produit JAMAIS de verdict CONTRADICTS.
    Rôle : filtrer les COMPATIBLE (éviter appel LLM inutile) et INCOMPARABLE.
    Tout diff ou untyped → NEED_LLM (le LLM est le seul décideur pour CONTRADICTS).
    """
    # Types différents → incomparable
    if vf1.value_type != vf2.value_type:
        return ContradictionResult(
            ContradictionVerdict.INCOMPARABLE,
            0.0,
            f"type mismatch: {vf1.value_type.value} vs {vf2.value_type.value}",
            vf1.value_type,
        )

    vtype = vf1.value_type

    # NUMBER
    if vtype == ValueType.NUMBER:
        u1 = (vf1.unit or "").lower()
        u2 = (vf2.unit or "").lower()
        if u1 and u2 and u1 != u2:
            return ContradictionResult(
                ContradictionVerdict.INCOMPARABLE,
                0.0,
                f"unit mismatch: {vf1.unit} vs {vf2.unit}",
                vtype,
            )
        if vf1.parsed_value == vf2.parsed_value:
            return ContradictionResult(
                ContradictionVerdict.COMPATIBLE,
                0.95,
                f"number: {vf1.raw_text} == {vf2.raw_text}",
                vtype,
            )
        return ContradictionResult(
            ContradictionVerdict.NEED_LLM,
            0.0,
            f"number diff: {vf1.raw_text} vs {vf2.raw_text}",
            vtype,
        )

    # VERSION
    if vtype == ValueType.VERSION:
        if vf1.parsed_value == vf2.parsed_value:
            return ContradictionResult(
                ContradictionVerdict.COMPATIBLE,
                0.95,
                f"version: {vf1.raw_text} == {vf2.raw_text}",
                vtype,
            )
        return ContradictionResult(
            ContradictionVerdict.NEED_LLM,
            0.0,
            f"version diff: {vf1.raw_text} vs {vf2.raw_text}",
            vtype,
        )

    # UNTYPED: toujours LLM
    return ContradictionResult(
        ContradictionVerdict.NEED_LLM,
        0.0,
        "untyped values: needs LLM arbitration",
        vtype,
    )


# =============================================================================
# 4. Fonction principale — détection value-level (couches 1-4)
# =============================================================================

# Type pour le ContextGate callback
ContextGateFn = Callable[[object, object], bool]


def detect_value_contradictions(
    claim_pairs: List[Tuple],
    entities_by_claim: Optional[Dict[str, List[str]]] = None,
    entity_index: Optional[Dict[str, object]] = None,
    context_gate: Optional[ContextGateFn] = None,
) -> Tuple[
    List[Tuple[str, str, ContradictionResult]],  # verdicts formels (COMPATIBLE)
    List[Tuple[object, object]],  # paires NEED_LLM
    Dict[str, int],  # stats
]:
    """
    Détecte contradictions value-level. Retourne:
    1. Verdicts formels (COMPATIBLE/INCOMPARABLE — jamais CONTRADICTS)
    2. Paires nécessitant LLM (NEED_LLM) — le caller appelle le LLM
    3. Stats de filtrage

    Le LLM arbiter N'EST PAS dans ce module (dépendance lourde).
    """
    formal_results: List[Tuple[str, str, ContradictionResult]] = []
    need_llm_pairs: List[Tuple[object, object]] = []
    stats = {
        "pairs_in": 0,
        "no_sf": 0,
        "key_mismatch": 0,
        "gate_filtered": 0,
        "formal_compatible": 0,
        "incomparable": 0,
        "need_llm": 0,
    }

    for c1, c2 in claim_pairs:
        stats["pairs_in"] += 1
        sf1 = getattr(c1, "structured_form", None) or {}
        sf2 = getattr(c2, "structured_form", None) or {}

        # Gate 1: structured_form requis
        if not sf1 or not sf2:
            stats["no_sf"] += 1
            continue

        # Gate 2: Comparable claim keys (GF-2: fallback entity overlap)
        if not have_comparable_claim_keys(c1, c2, entities_by_claim, entity_index):
            stats["key_mismatch"] += 1
            continue

        # Gate 3: ContextGate (callback, default=True)
        if context_gate and not context_gate(c1, c2):
            stats["gate_filtered"] += 1
            continue

        # Parse ValueFrames
        vf1 = parse_value_frame(sf1.get("object", ""))
        vf2 = parse_value_frame(sf2.get("object", ""))

        # Compare formellement
        result = compare_values(vf1, vf2)

        claim_id_1 = getattr(c1, "claim_id", "")
        claim_id_2 = getattr(c2, "claim_id", "")

        if result.verdict == ContradictionVerdict.COMPATIBLE:
            stats["formal_compatible"] += 1
            formal_results.append((claim_id_1, claim_id_2, result))
        elif result.verdict == ContradictionVerdict.INCOMPARABLE:
            stats["incomparable"] += 1
            formal_results.append((claim_id_1, claim_id_2, result))
        elif result.verdict == ContradictionVerdict.NEED_LLM:
            stats["need_llm"] += 1
            need_llm_pairs.append((c1, c2))

    return formal_results, need_llm_pairs, stats


__all__ = [
    "ValueType",
    "ValueFrame",
    "ContradictionVerdict",
    "ContradictionResult",
    "ContextGateFn",
    "build_claim_key",
    "have_comparable_claim_keys",
    "parse_value_frame",
    "compare_values",
    "detect_value_contradictions",
]
