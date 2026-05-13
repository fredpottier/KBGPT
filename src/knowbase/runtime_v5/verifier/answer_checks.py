"""V5 Verifier — Answer-level consistency checks (CH-52.8.3 / S7.3).

ADR V1.5 §3f §C3 (Codex Hebbia/Causaly pattern) :
- contradictory_citations : 2 claims citant 2 sections incompatibles
- version_mismatch : claims mélangeant doc versions différentes
- unsupported_numeric_transform : delta calculé sans compute_derived_metric cited
- missing_qualifier : claim global sans qualification présente dans sources

Charte domain-agnostic : patterns universels uniquement.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from knowbase.runtime_v5.verifier.claim_segmenter import Claim, ClaimType
from knowbase.runtime_v5.verifier.failure import (
    FailureReason,
    VerifierFailure,
    make_failure,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


_VERSION_TOKEN = re.compile(
    r"\b(?:v\d+(?:\.\d+)?|version\s+\d+(?:\.\d+)?|"
    r"2\d{3}|"  # year 20xx
    r"FPS\d+|SPS\d+|S/4HANA\s+\d+|"  # SAP specific accepté car patterns universels nom+nb
    r"release\s+\d+)\b",
    re.IGNORECASE,
)

# Patterns "numeric transform" — claim qui calcule une différence/ratio.
# Détection en 2 temps : keyword de transform + claim_type=NUMERIC (déjà vérifié
# par le caller). On accepte ici les variantes "improved 30 percent" comme "30
# percent improvement".
_NUMERIC_TRANSFORM_PATTERN = re.compile(
    r"\b(?:delta|difference|ratio|percent\s+change|percentage\s+change|"
    r"increased?|decreased?|improved?|improvement|reduced?|reduction|"
    r"compared\s+to|relative\s+to|"
    r"times\s+(?:more|less|faster|slower)|"
    r"\d+\s*(?:times|x)\s+(?:more|less|faster|slower|higher|lower))\b",
    re.IGNORECASE,
)

# Marqueurs de calcul cité (compute_derived_metric ou variants)
_COMPUTE_TOOL_NAMES = frozenset({
    "compute_derived_metric", "computed", "calculated", "calculé", "berechnet",
})


# ─── Check 1 : contradictory_citations ──────────────────────────────────────


def check_contradictory_citations(
    claims: list[Claim],
    nli_results: Optional[list] = None,
) -> list[VerifierFailure]:
    """Détecte 2 claims citant 2 sections différentes ET avec contenu opposé.

    Heuristique V1.5 : on identifie les paires de claims qui :
    - Ont des citations vers sections différentes
    - Contiennent des numerics opposés OU mots de négation/contradiction

    Pour la prod, ajouter NLI bidirectionnel entre claims.
    """
    failures = []
    # Group claims par section_id cité
    by_section: dict[str, list[tuple[int, Claim]]] = defaultdict(list)
    for i, c in enumerate(claims):
        for ref in c.citations:
            key = ref.section_id or ref.doc_id or ref.raw
            by_section[key].append((i, c))

    # Cherche les paires claim_i / claim_j avec citations différentes ET numeric divergent
    n = len(claims)
    for i in range(n):
        ci = claims[i]
        if ci.claim_type != ClaimType.NUMERIC:
            continue
        nums_i = _extract_numbers(ci.text)
        if not nums_i:
            continue
        for j in range(i + 1, n):
            cj = claims[j]
            if cj.claim_type != ClaimType.NUMERIC:
                continue
            nums_j = _extract_numbers(cj.text)
            if not nums_j:
                continue
            # Citations différentes ?
            keys_i = {(r.doc_id, r.section_id) for r in ci.citations}
            keys_j = {(r.doc_id, r.section_id) for r in cj.citations}
            if not (keys_i and keys_j) or keys_i == keys_j:
                continue
            # Same topic (heuristique : phrases sémantiquement proches via shared tokens)
            shared = _shared_significant_tokens(ci.text, cj.text)
            if len(shared) < 2:
                continue
            # Nombres divergents (>10% écart) → suspect
            if _numbers_diverge(nums_i, nums_j, rel_threshold=0.1):
                failures.append(make_failure(
                    reason=FailureReason.CONTRADICTORY_CITATIONS,
                    details=(
                        f"Claim {i} ({ci.text[:80]}...) and claim {j} "
                        f"({cj.text[:80]}...) cite different sources but have "
                        f"divergent numeric values: {nums_i} vs {nums_j}"
                    ),
                    affected_claim_text=cj.text,
                    affected_claim_index=j,
                ))
    return failures


# ─── Check 2 : version_mismatch ─────────────────────────────────────────────


def check_version_mismatch(claims: list[Claim]) -> list[VerifierFailure]:
    """Détecte claims qui mélangent doc versions différentes sans qualification."""
    failures = []
    versions_per_doc: dict[str, set[str]] = defaultdict(set)
    for c in claims:
        for ref in c.citations:
            if not ref.doc_id:
                continue
            # Extract version tokens from claim text
            versions = set(m.group(0).lower() for m in _VERSION_TOKEN.finditer(c.text))
            versions_per_doc[ref.doc_id] |= versions
    # Si une réponse mélange plusieurs versions sur un même doc_id : suspect
    for doc_id, versions in versions_per_doc.items():
        if len(versions) >= 2:
            failures.append(make_failure(
                reason=FailureReason.VERSION_CONFLICT,
                details=(
                    f"Document '{doc_id}' is cited with multiple versions in the "
                    f"same answer: {sorted(versions)}. Add qualification or split."
                ),
            ))
    return failures


# ─── Check 3 : unsupported_numeric_transform ────────────────────────────────


def check_unsupported_numeric_transform(
    claims: list[Claim],
    cited_tool_names: Optional[set[str]] = None,
) -> list[VerifierFailure]:
    """Détecte un claim "delta/ratio/percent_change" sans compute_derived_metric cited.

    Args:
        claims : liste de claims segmentés
        cited_tool_names : set des tools utilisés (par l'agent) pour générer la réponse.
                          Si None, on n'a pas de visibility → on flag les transforms suspects.
    """
    failures = []
    cited = cited_tool_names or set()
    compute_used = bool(cited & _COMPUTE_TOOL_NAMES)
    for i, c in enumerate(claims):
        if c.claim_type not in (ClaimType.NUMERIC, ClaimType.COMPARATIVE):
            continue
        if _NUMERIC_TRANSFORM_PATTERN.search(c.text) and not compute_used:
            failures.append(make_failure(
                reason=FailureReason.UNSUPPORTED_NUMERIC_TRANSFORM,
                details=(
                    f"Claim {i} mentions a numeric transform "
                    f"(delta/ratio/comparison with value) but no "
                    f"`compute_derived_metric` tool was cited."
                ),
                affected_claim_text=c.text,
                affected_claim_index=i,
            ))
    return failures


# ─── Check 4 : missing_qualifier ────────────────────────────────────────────


_QUALIFIER_TOKENS = re.compile(
    r"\b(?:since|until|under|when|if|except|"
    r"depuis|jusqu'?en?|sous|si|sauf|"
    r"seit|bis|wenn|außer|nur)\b",
    re.IGNORECASE,
)
_ABSOLUTE_TOKENS = re.compile(
    r"\b(?:always|never|all|every|none|"
    r"toujours|jamais|tous|aucun|"
    r"immer|nie|alle|kein)\b",
    re.IGNORECASE,
)


def check_missing_qualifier(claims: list[Claim]) -> list[VerifierFailure]:
    """Détecte claims absolus ("always", "never", "all") sans qualifier
    temporel/conditionnel.
    """
    failures = []
    for i, c in enumerate(claims):
        if _ABSOLUTE_TOKENS.search(c.text) and not _QUALIFIER_TOKENS.search(c.text):
            failures.append(make_failure(
                reason=FailureReason.MISSING_QUALIFIER,
                details=(
                    f"Claim {i} uses absolute terms (always/never/all) "
                    f"without temporal/conditional qualifier: '{c.text[:120]}'"
                ),
                affected_claim_text=c.text,
                affected_claim_index=i,
            ))
    return failures


# ─── Aggregate runner ────────────────────────────────────────────────────────


def run_answer_level_checks(
    claims: list[Claim],
    cited_tool_names: Optional[set[str]] = None,
) -> list[VerifierFailure]:
    """Lance les 4 checks et retourne toutes les failures détectées."""
    failures = []
    failures.extend(check_contradictory_citations(claims))
    failures.extend(check_version_mismatch(claims))
    failures.extend(check_unsupported_numeric_transform(claims, cited_tool_names))
    failures.extend(check_missing_qualifier(claims))
    return failures


# ─── Helpers ─────────────────────────────────────────────────────────────────


_NUMBER_PATTERN = re.compile(r"\b\d+(?:[.,]\d+)?\b")


def _extract_numbers(text: str) -> list[float]:
    """Extrait tous les nombres d'un texte."""
    nums = []
    for m in _NUMBER_PATTERN.finditer(text):
        try:
            nums.append(float(m.group(0).replace(",", ".")))
        except ValueError:
            pass
    return nums


def _numbers_diverge(
    a: list[float], b: list[float], rel_threshold: float = 0.1
) -> bool:
    """True si min(|ai - bj|/max(ai,bj)) > rel_threshold pour au moins une paire."""
    if not a or not b:
        return False
    for ai in a:
        for bj in b:
            if ai == 0 and bj == 0:
                continue
            denom = max(abs(ai), abs(bj))
            if denom > 0 and abs(ai - bj) / denom > rel_threshold:
                return True
    return False


def _shared_significant_tokens(t1: str, t2: str, min_len: int = 4) -> set[str]:
    """Tokens significatifs partagés (≥ min_len, lowercase, alphanumériques)."""
    tokens1 = set(re.findall(rf"\w{{{min_len},}}", t1.lower()))
    tokens2 = set(re.findall(rf"\w{{{min_len},}}", t2.lower()))
    return tokens1 & tokens2
