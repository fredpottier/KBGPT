"""Phase B (P1.3) — pont Procedure ↔ Claims.

Relie l'extraction Procedure v6 (orpheline jusqu'ici) au pipeline ClaimFirst.
Conforme à ADR_PHASE_B_HYPER_RELATIONAL_CLAIMS §3.2/§3.3.

Stratégie (robuste, sans matching fragile pour la séquence ordonnée) :
1. Reconstruire les sections depuis les passages (group by section_id).
2. Pour chaque section contenant ≥1 claim PROCEDURAL, extraire les procédures
   via `ProcedureExtractor` (v6, DeepSeek-V3.1 ou EC2 Qwen2.5-14B en ré-ingestion).
3. Persister chaque :Procedure + :ProcedureStep (séquence ordonnée AUTORITATIVE,
   via ProcedurePersister — aucun matching requis).
4. Relier les claims PROCEDURAL de la section à leur :Procedure par recouvrement
   lexical (Jaccard) :
     - set claim.procedure_id / procedure_role="STEP" / step_index
     - relation (:Claim)-[:STEP_OF {order}]->(:Procedure)
5. Chaîner PREREQUISITE_OF entre claims-étapes consécutifs (par step_index).
6. HAS_OUTCOME : relier la :Procedure au claim décrivant son résultat (goal),
   best-effort par recouvrement lexical.

Le tool runtime `procedure_chain` (Phase 3 / P1.5) lit la séquence ordonnée
depuis les :ProcedureStep (autoritative), et utilise les claims (procedure_id)
comme points d'entrée retrievables.

Charte : domain-agnostic strict, aucun exemple corpus-spécifique.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from knowbase.claimfirst.models.claim import Claim, ClaimType
from knowbase.claimfirst.models.passage import Passage
from knowbase.claimfirst.models.result import ClaimRelation, RelationType
from knowbase.runtime_v6.schemas import Procedure

logger = logging.getLogger(__name__)


# Seuil de recouvrement lexical minimal pour relier une étape à un claim.
# Lenient : les claims PROCEDURAL décrivent exactement les étapes, donc un
# faible recouvrement (token Jaccard) suffit à associer sans bruit excessif.
_DEFAULT_MATCH_THRESHOLD = 0.18

_STOPWORDS = {
    "the", "a", "an", "to", "of", "and", "or", "in", "on", "for", "with",
    "is", "are", "be", "by", "as", "at", "from", "this", "that", "it", "you",
    "your", "will", "must", "can", "should", "then", "first", "next", "finally",
}


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
        if len(w) > 2 and w not in _STOPWORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


@dataclass
class _SectionData:
    section_id: str
    text: str
    procedural_claims: List[Claim] = field(default_factory=list)


@dataclass
class ProcedureLinkResult:
    """Artefacts produits par le linker (claims mutés in-place)."""

    procedures: List[Tuple[str, Procedure]] = field(default_factory=list)
    # (claim_id, procedure_id, order) — relation Claim-[:STEP_OF]->Procedure
    step_of_links: List[Tuple[str, str, int]] = field(default_factory=list)
    # (procedure_id, claim_id) — relation Procedure-[:HAS_OUTCOME]->Claim
    outcome_links: List[Tuple[str, str]] = field(default_factory=list)
    # PREREQUISITE_OF (Claim->Claim) — persistable via le flux relations standard
    prerequisite_relations: List[ClaimRelation] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


class ProcedureLinker:
    """Pont Procedure ↔ Claims (P1.3)."""

    def __init__(
        self,
        extractor,
        tenant_id: str = "default",
        match_threshold: float = _DEFAULT_MATCH_THRESHOLD,
        section_min_chars: int = 200,
    ):
        self.extractor = extractor
        self.tenant_id = tenant_id
        self.match_threshold = match_threshold
        self.section_min_chars = section_min_chars

    # ── Public API ────────────────────────────────────────────────────────────

    def link(
        self,
        claims: List[Claim],
        passages: List[Passage],
        doc_id: str,
    ) -> ProcedureLinkResult:
        """Extrait les procédures et relie les claims. Mute les claims in-place."""
        result = ProcedureLinkResult(stats={
            "sections_scanned": 0,
            "sections_with_procedural_claims": 0,
            "procedures_extracted": 0,
            "step_of_links": 0,
            "prerequisite_of": 0,
            "outcome_links": 0,
        })

        sections = self._reconstruct_sections(claims, passages)
        for section in sections.values():
            result.stats["sections_scanned"] += 1
            if not section.procedural_claims:
                continue
            if len(section.text) < self.section_min_chars:
                continue
            result.stats["sections_with_procedural_claims"] += 1

            procs = self.extractor.extract_for_section(
                doc_id=doc_id,
                section_id=section.section_id,
                section_title=None,
                section_text=section.text,
            )
            for proc in procs:
                self._link_procedure(proc, section, result)

        return result

    # ── Internal ──────────────────────────────────────────────────────────────

    def _reconstruct_sections(
        self, claims: List[Claim], passages: List[Passage]
    ) -> Dict[str, _SectionData]:
        """Regroupe passages + claims PROCEDURAL par section_id."""
        # passage_id → section_id
        pid_to_section: Dict[str, Optional[str]] = {
            p.passage_id: p.section_id for p in passages
        }

        # Reconstruire le texte de chaque section (passages ordonnés)
        sections: Dict[str, _SectionData] = {}
        ordered = sorted(passages, key=lambda p: p.reading_order_index)
        for p in ordered:
            sid = p.section_id or f"_nosection_{p.passage_id}"
            if sid not in sections:
                sections[sid] = _SectionData(section_id=sid, text="")
            if p.text:
                sections[sid].text += (p.text.strip() + "\n")

        # Attacher les claims PROCEDURAL à leur section
        for c in claims:
            if c.claim_type != ClaimType.PROCEDURAL:
                continue
            sid = pid_to_section.get(c.passage_id)
            if sid is None:
                sid = f"_nosection_{c.passage_id}"
            if sid in sections:
                sections[sid].procedural_claims.append(c)
        return sections

    def _link_procedure(
        self,
        proc: Procedure,
        section: _SectionData,
        result: ProcedureLinkResult,
    ) -> None:
        """Relie une procédure extraite aux claims PROCEDURAL de sa section."""
        result.procedures.append((section.section_id, proc))
        result.stats["procedures_extracted"] += 1

        # Matching étape → claim (greedy par meilleur score, claim unique)
        available = list(section.procedural_claims)
        matched: List[Tuple[int, Claim]] = []  # (step_index, claim)
        for step in sorted(proc.steps, key=lambda s: s.step_number):
            step_tokens = _tokens(step.action)
            best_claim: Optional[Claim] = None
            best_score = self.match_threshold
            for c in available:
                score = _jaccard(step_tokens, _tokens(c.text))
                if score >= best_score:
                    best_score = score
                    best_claim = c
            if best_claim is None:
                continue
            available.remove(best_claim)
            best_claim.procedure_id = proc.procedure_id
            best_claim.procedure_role = "STEP"
            best_claim.step_index = step.step_number
            result.step_of_links.append(
                (best_claim.claim_id, proc.procedure_id, step.step_number)
            )
            result.stats["step_of_links"] += 1
            matched.append((step.step_number, best_claim))

        # PREREQUISITE_OF : chaîne entre claims-étapes consécutifs
        matched.sort(key=lambda x: x[0])
        for (_, prev_c), (_, next_c) in zip(matched, matched[1:]):
            result.prerequisite_relations.append(
                ClaimRelation(
                    source_claim_id=prev_c.claim_id,
                    target_claim_id=next_c.claim_id,
                    relation_type=RelationType.PREREQUISITE_OF,
                    confidence=0.9,
                    basis=f"Consecutive steps in procedure '{proc.name}'",
                )
            )
            result.stats["prerequisite_of"] += 1

        # HAS_OUTCOME : claim décrivant le résultat (goal), best-effort
        goal_tokens = _tokens(proc.goal)
        best_outcome: Optional[Claim] = None
        best_score = self.match_threshold
        # privilégier un claim NON déjà étape
        step_ids = {c.claim_id for _, c in matched}
        for c in section.procedural_claims:
            if c.claim_id in step_ids:
                continue
            score = _jaccard(goal_tokens, _tokens(c.text))
            if score >= best_score:
                best_score = score
                best_outcome = c
        if best_outcome is not None:
            if best_outcome.procedure_role is None:
                best_outcome.procedure_role = "OUTCOME"
                best_outcome.procedure_id = proc.procedure_id
            result.outcome_links.append((proc.procedure_id, best_outcome.claim_id))
            result.stats["outcome_links"] += 1


__all__ = ["ProcedureLinker", "ProcedureLinkResult"]
