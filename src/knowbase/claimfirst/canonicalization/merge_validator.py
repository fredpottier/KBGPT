"""
LLM Merge Validator — conservation de la canonicalisation.

Applique la regle : les merges hors "variantes orthographiques strictes" DOIVENT
passer par le LLM (Qwen2.5-72B via DeepInfra). Pas de heuristique qui casse
silencieusement le KG.

Usage :
    validator = LLMMergeValidator()
    candidates = [MergeCandidate(group_id=0, members=[...]), ...]
    decisions = validator.validate_groups(candidates)
    approved = [d for d in decisions if d.decision == "merge"]
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("[OSMOSE] merge_validator")


# ── Variantes orthographiques evidentes (pas de LLM) ───────────────────

_NON_ALPHA_NUM = re.compile(r"[^a-z0-9]")


def is_obvious_variant(name_a: str, name_b: str) -> bool:
    """
    True ssi les deux noms sont identiques apres normalisation stricte
    (lowercase + suppression de tout caractere non alphanumerique).

    Capture :
      - Case variants : "PII" ≡ "pii"
      - Hyphenation : "fine-tuning" ≡ "fine tuning"
      - Ponctuation / whitespace : "Start-ups" ≡ "Startups"

    Ne capture PAS :
      - Acronyme vs forme longue : "GDPR" vs "General Data Protection Regulation"
      - Prefixe generique : "Data processing" vs "Processing"
      - Synonymes : "personal data" vs "personal information"
    Ces cas doivent passer par LLM.
    """
    if not name_a or not name_b:
        return False
    norm_a = _NON_ALPHA_NUM.sub("", name_a.lower())
    norm_b = _NON_ALPHA_NUM.sub("", name_b.lower())
    return bool(norm_a) and norm_a == norm_b


def group_is_all_obvious(member_names: List[str]) -> bool:
    """
    True ssi tous les noms d'un groupe sont des variantes orthographiques
    du meme token normalise. Dans ce cas : pas besoin de LLM.
    """
    if len(member_names) < 2:
        return True  # groupe trivial
    first = _NON_ALPHA_NUM.sub("", member_names[0].lower())
    if not first:
        return False
    for n in member_names[1:]:
        norm = _NON_ALPHA_NUM.sub("", n.lower())
        if norm != first:
            return False
    return True


# ── Dataclasses ────────────────────────────────────────────────────────


@dataclass
class MergeMember:
    """Un membre d'un groupe candidat."""

    entity_id: str
    name: str
    claim_count: int = 0
    entity_type: str = "other"


@dataclass
class MergeCandidate:
    """Un groupe candidat a la fusion (produit par le canonicalizer)."""

    group_id: int
    members: List[MergeMember]
    source_method: str = ""  # ex: "alias_identity" | "embedding_cluster"
    max_confidence: float = 0.0


@dataclass
class MergeDecision:
    """Decision LLM pour un groupe candidat."""

    group_id: int
    decision: str  # "merge" | "keep_separate" | "partial_merge"
    canonical: Optional[str] = None
    # Pour partial_merge : liste de sous-groupes a merger
    subgroups: List[List[str]] = field(default_factory=list)
    reason: str = ""
    # Entity IDs des membres approuves pour merge (utilise par les callers)
    approved_entity_ids: List[str] = field(default_factory=list)


# ── LLM Validator ──────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a knowledge graph canonicalization reviewer.

For each candidate merge group of entity names, decide:
  - merge : all members refer to the same concept/entity/institution
  - keep_separate : they are distinct concepts, even if linguistically similar
  - partial_merge : some members should merge but not all

BE CONSERVATIVE. When in doubt, keep_separate.

Merge examples:
  - "GDPR" + "General Data Protection Regulation" → merge (acronym expansion)
  - "policymakers" + "Policy-makers" → merge (spelling)
  - "personal data" + "personal information" → merge (synonymous legal terms)
  - "NIST" + "National Institute of Standards and Technology" → merge
  - "Italian DPA" + "Italian Data Protection Authority" → merge (same institution)

Keep_separate examples:
  - "Belgian DPA" + "French DPA" + "Italian DPA" → separate (distinct institutions)
  - "AI system" + "AI algorithm" + "AI developers" → separate (distinct concepts)
  - "biometric data" + "biometric systems" → separate (data vs technology)
  - "Processing" (generic) + "Data processing" (specific) → separate
  - "AIRA" + "FRIA" → separate (distinct acronyms)
  - "Privacy Directive" + "Privacy Regulation" → separate (distinct legal instruments)

For merge, provide the canonical name — prefer:
  1. The form with highest claim_count (most used in corpus)
  2. Full name over acronym unless acronym is dominant
  3. Shorter, cleanest form if claim counts are similar

For partial_merge, provide subgroups as lists of names.

Output STRICT JSON array, one object per input group:
{
  "group_id": 0,
  "decision": "merge" | "keep_separate" | "partial_merge",
  "canonical": "best canonical name" | null,
  "subgroups": [["name1", "name2"], ["name3"]] or [],
  "reason": "short factual justification"
}"""


class LLMMergeValidator:
    """Valide les groupes candidats via Qwen2.5-72B (DeepInfra)."""

    def __init__(self, batch_size: int = 8):
        self._batch_size = batch_size

    def validate_groups(
        self, candidates: List[MergeCandidate]
    ) -> List[MergeDecision]:
        """
        Valide une liste de candidats. Les groupes entierement "obvious"
        (orthographiques) sont approuves sans appel LLM.
        """
        if not candidates:
            return []

        # Pre-filtrage : groupes 100% orthographiques → approuves direct
        obvious_decisions: List[MergeDecision] = []
        needs_llm: List[MergeCandidate] = []
        for c in candidates:
            names = [m.name for m in c.members]
            if group_is_all_obvious(names):
                # canonical = variante la plus utilisee
                winner = max(c.members, key=lambda m: m.claim_count)
                obvious_decisions.append(
                    MergeDecision(
                        group_id=c.group_id,
                        decision="merge",
                        canonical=winner.name,
                        reason="obvious orthographic variants (case/hyphen/punct only)",
                        approved_entity_ids=[m.entity_id for m in c.members],
                    )
                )
            else:
                needs_llm.append(c)

        logger.info(
            f"[merge_validator] {len(obvious_decisions)} auto-approved "
            f"(obvious variants), {len(needs_llm)} need LLM validation"
        )

        # LLM validation par batches
        llm_decisions: List[MergeDecision] = []
        for i in range(0, len(needs_llm), self._batch_size):
            batch = needs_llm[i : i + self._batch_size]
            try:
                batch_decisions = self._validate_batch(batch)
                llm_decisions.extend(batch_decisions)
            except Exception as e:
                logger.exception(
                    f"[merge_validator] batch {i} LLM call failed: {e}"
                )
                # Fallback defensif : keep_separate pour ce batch
                for c in batch:
                    llm_decisions.append(
                        MergeDecision(
                            group_id=c.group_id,
                            decision="keep_separate",
                            reason=f"LLM error: {e}",
                        )
                    )

        return obvious_decisions + llm_decisions

    # ── Internals ──────────────────────────────────────────────────────

    def _validate_batch(
        self, batch: List[MergeCandidate]
    ) -> List[MergeDecision]:
        from knowbase.common.llm_router import complete_knowledge_extraction

        user_prompt = self._build_user_prompt(batch)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = complete_knowledge_extraction(
            messages=messages, temperature=0.1, max_tokens=3000
        )
        parsed = self._parse_response(response, batch)

        decisions: List[MergeDecision] = []
        members_by_group = {c.group_id: c.members for c in batch}
        for item in parsed:
            gid = item.get("group_id")
            dec = item.get("decision", "keep_separate")
            canonical = item.get("canonical") or None
            subgroups_raw = item.get("subgroups") or []
            reason = item.get("reason", "")

            members = members_by_group.get(gid, [])
            name_to_eid = {m.name: m.entity_id for m in members}

            approved_ids: List[str] = []
            if dec == "merge":
                approved_ids = [m.entity_id for m in members]
            elif dec == "partial_merge":
                # Premier sous-groupe = celui qu'on persiste (le plus large)
                if subgroups_raw:
                    best_sg = max(subgroups_raw, key=lambda sg: len(sg))
                    approved_ids = [
                        name_to_eid[n] for n in best_sg if n in name_to_eid
                    ]
                    if len(approved_ids) < 2:
                        approved_ids = []

            decisions.append(
                MergeDecision(
                    group_id=gid,
                    decision=dec,
                    canonical=canonical,
                    subgroups=subgroups_raw,
                    reason=reason,
                    approved_entity_ids=approved_ids,
                )
            )

        # Gerer les groups non retournes par le LLM : fallback keep_separate
        returned_gids = {d.group_id for d in decisions}
        for c in batch:
            if c.group_id not in returned_gids:
                decisions.append(
                    MergeDecision(
                        group_id=c.group_id,
                        decision="keep_separate",
                        reason="not returned by LLM",
                    )
                )

        return decisions

    def _build_user_prompt(self, batch: List[MergeCandidate]) -> str:
        """Construit le prompt utilisateur pour un batch de groupes."""
        parts = [f"Review these {len(batch)} candidate merge groups:\n"]
        for c in batch:
            parts.append(f"Group {c.group_id} (method={c.source_method}):")
            for m in c.members:
                parts.append(
                    f'  - "{m.name}" (claims={m.claim_count}, type={m.entity_type})'
                )
            parts.append("")
        parts.append(
            f"Return a JSON array with {len(batch)} objects, one per group. "
            "No markdown fences."
        )
        return "\n".join(parts)

    def _parse_response(
        self, response: str, batch: List[MergeCandidate]
    ) -> List[Dict[str, Any]]:
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(
                f"[merge_validator] JSON parse failed: {e}. "
                f"Response head: {text[:300]!r}"
            )
            return []

        if isinstance(data, dict):
            # Certains LLM wrapent en objet — tolerer
            for key in ("results", "decisions", "groups"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                data = [data]

        if not isinstance(data, list):
            return []

        return data
