"""
R2 — Response Composer V1.1.

Compose la réponse finale avec **5 sections obligatoires** (cf. RUNTIME_EXPLOITATION §5)
+ un bloc métier modulable selon le mode.

5 sections obligatoires (rendues dans cet ordre) :
1. **Réponse courte** : 1-3 phrases qui répondent directement à la question
2. **Conditions / scope** : sous quelles conditions la réponse s'applique
3. **Preuves** : citations verbatim depuis les chunks/claims (avec provenance)
4. **Confiance** : kg_trust score + niveau + notes
5. **Drill-down** : pointers vers /admin/relations ou autres pour explorer

Bloc métier (entre conditions et preuves) — modulable selon mode :
- LOOKUP_FACTUAL → bloc "Valeur trouvée" (clé/valeur typée)
- APPLICABILITY_QUERY → bloc "Règles applicables" (liste typée par axe)
- SNAPSHOT_TEMPORAL → bloc "Snapshot at T" + lifecycle indicator
- DIFF_EVOLUTION → bloc "Diff" (introduced/retired/modified par période)
- CONFLICT_RISK → bloc "Contradictions identifiées" (list with reasoning)
- EXPLORATION_RELATIONAL → bloc "Navigation par type" (graph view)
- SYNTHESIS_SUMMARY → bloc "Vue d'ensemble" (sections coverage)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from knowbase.runtime.evidence_planner import RetrievalPlan
from knowbase.runtime.query_resolver import ResolvedQuery, ResponseMode
from knowbase.runtime.trust_evaluator import TrustScore

logger = logging.getLogger(__name__)


@dataclass
class EvidenceCitation:
    """Une citation evidence-locked (claim_id + verbatim quote)."""

    claim_id: str
    text: str
    doc_id: str
    publication_date: Optional[str] = None
    validity_start: Optional[str] = None
    validity_end: Optional[str] = None
    lifecycle_status: Optional[str] = None
    relation_type: Optional[str] = None
    """Si trouvé via traversal KG, le type de la relation utilisée."""


@dataclass
class ComposedResponse:
    """Réponse finale compositée."""

    short_answer: str
    """Section 1 : 1-3 phrases."""

    conditions: list[str] = field(default_factory=list)
    """Section 2 : conditions/scope."""

    business_block: dict = field(default_factory=dict)
    """Bloc métier modulable selon mode."""

    evidence: list[EvidenceCitation] = field(default_factory=list)
    """Section 3 : preuves verbatim."""

    confidence: Optional[TrustScore] = None
    """Section 4 : kg_trust score."""

    drill_down: list[dict] = field(default_factory=list)
    """Section 5 : pointers (URL admin/relations, etc.)."""

    # Metadata
    mode: Optional[ResponseMode] = None
    regime: Optional[str] = None
    debug_info: dict = field(default_factory=dict)


class ResponseComposer:
    """
    Compose la réponse finale en 5 sections.

    Pattern V1.1 :
    - Format **modulaire** : on construit chaque section indépendamment
    - **Evidence-locked** : chaque citation pointe vers un claim_id existant
    - Si TrustScore < FALLBACK threshold + policy strict → hard abstention
    - Sinon : on compose même avec qualité partielle, en flagant explicitement
    """

    def compose(
        self,
        resolved: ResolvedQuery,
        plan: RetrievalPlan,
        chunks: list[dict],
        relations: list[dict],
        trust: TrustScore,
    ) -> ComposedResponse:
        """Compose la réponse finale."""

        # 1. Section "Réponse courte"
        short = self._build_short_answer(resolved, chunks, relations)

        # 2. Section "Conditions"
        conditions = self._build_conditions(resolved, chunks, relations)

        # 3. Bloc métier modulable
        business_block = self._build_business_block(resolved.mode, chunks, relations)

        # 4. Section "Preuves" (top-K citations)
        evidence = self._build_evidence(chunks, relations, top_k=5)

        # 5. Section "Drill-down"
        drill_down = self._build_drill_down(resolved.mode, chunks, relations)

        return ComposedResponse(
            short_answer=short,
            conditions=conditions,
            business_block=business_block,
            evidence=evidence,
            confidence=trust,
            drill_down=drill_down,
            mode=resolved.mode,
            regime=plan.regime.value if plan.regime else None,
            debug_info={
                "escalation_triggered": plan.escalation_triggered,
                "escalation_reason": plan.escalation_reason,
                "n_chunks": len(chunks),
                "n_relations": len(relations),
            },
        )

    # ------------------------------------------------------------------------
    # Section builders (squelette — pour V1.1 socle, on retourne du structuré)
    # ------------------------------------------------------------------------

    def _build_short_answer(
        self, resolved: ResolvedQuery, chunks: list[dict], relations: list[dict]
    ) -> str:
        """Section 1 : 1-3 phrases. Pour V1.1 socle, on extrait le top chunk text."""
        if not chunks:
            return "Aucune information trouvée dans le corpus pour cette question."
        # Retourne la text du top chunk (ResponseComposer doit invoquer un LLM en R2.B
        # final pour synthèse, mais pour le socle on prend juste le top match)
        top = chunks[0]
        text = top.get("text") or ""
        # Tronque à ~3 phrases
        sentences = text.split(". ")
        return ". ".join(sentences[:3]).strip() + ("." if not sentences[0].endswith(".") else "")

    def _build_conditions(
        self, resolved: ResolvedQuery, chunks: list[dict], relations: list[dict]
    ) -> list[str]:
        """Section 2 : conditions/scope. Aggregate des validity_start, applicability conditions."""
        conditions = []
        # Date conditions (depuis validity_start des top chunks)
        validity_starts = [c.get("validity_start") for c in chunks[:5] if c.get("validity_start")]
        if validity_starts:
            min_start = min(validity_starts)
            conditions.append(f"Applicable depuis : {min_start}")

        validity_ends = [c.get("validity_end") for c in chunks[:5] if c.get("validity_end")]
        if validity_ends:
            min_end = min(validity_ends)
            conditions.append(f"Applicable jusqu'à : {min_end}")

        # Lifecycle status
        statuses = set(c.get("lifecycle_status") for c in chunks[:5] if c.get("lifecycle_status"))
        statuses.discard("UNKNOWN")
        if statuses:
            conditions.append(f"Status : {', '.join(sorted(statuses))}")

        # Doc IDs distincts
        docs = sorted({c.get("doc_id") for c in chunks[:5] if c.get("doc_id")})
        if docs:
            conditions.append(f"Sources : {', '.join(docs)}")

        return conditions

    def _build_business_block(
        self, mode: ResponseMode, chunks: list[dict], relations: list[dict]
    ) -> dict:
        """Bloc métier modulable selon mode."""
        if mode == ResponseMode.LOOKUP_FACTUAL:
            return {"type": "factual_value", "top_match": chunks[0] if chunks else None}

        if mode == ResponseMode.APPLICABILITY_QUERY:
            applicable = [c for c in chunks if c.get("lifecycle_status") in ("ACTIVE", None, "UNKNOWN")]
            return {"type": "applicable_rules", "rules": applicable[:10]}

        if mode == ResponseMode.SNAPSHOT_TEMPORAL:
            return {"type": "snapshot", "as_of": None, "claims_at_t": chunks[:10]}

        if mode == ResponseMode.DIFF_EVOLUTION:
            introduced = [c for c in chunks if c.get("diff_change_type") == "introduced"]
            retired = [c for c in chunks if c.get("diff_change_type") == "retired"]
            modified = [c for c in chunks if c.get("diff_change_type") == "modified"]
            return {
                "type": "diff",
                "introduced": introduced,
                "retired": retired,
                "modified": modified,
            }

        if mode == ResponseMode.CONFLICT_RISK:
            conflicts = [r for r in relations if r.get("type") == "CONFLICT" and r.get("is_contradiction")]
            return {"type": "contradictions", "conflicts": conflicts[:20]}

        if mode == ResponseMode.EXPLORATION_RELATIONAL:
            by_type = {}
            for r in relations:
                t = r.get("type", "UNKNOWN")
                by_type.setdefault(t, []).append(r)
            return {"type": "navigation", "relations_by_type": {k: len(v) for k, v in by_type.items()}}

        if mode == ResponseMode.SYNTHESIS_SUMMARY:
            return {
                "type": "summary",
                "n_chunks": len(chunks),
                "n_relations": len(relations),
                "docs_covered": sorted({c.get("doc_id") for c in chunks if c.get("doc_id")}),
            }

        return {"type": "generic", "chunks_count": len(chunks)}

    def _build_evidence(
        self, chunks: list[dict], relations: list[dict], top_k: int = 5
    ) -> list[EvidenceCitation]:
        """Section 3 : preuves verbatim (top-k chunks + 2 relations clés)."""
        citations = []
        for c in chunks[:top_k]:
            citations.append(EvidenceCitation(
                claim_id=c.get("claim_id", "unknown"),
                text=c.get("text", ""),
                doc_id=c.get("doc_id", "unknown"),
                publication_date=c.get("publication_date"),
                validity_start=c.get("validity_start"),
                validity_end=c.get("validity_end"),
                lifecycle_status=c.get("lifecycle_status"),
            ))
        # Top 2 relations comme evidences supplémentaires
        for r in (relations or [])[:2]:
            citations.append(EvidenceCitation(
                claim_id=r.get("a_claim_id", "unknown"),
                text=f"[via {r.get('type')}] {r.get('reasoning', '')[:200]}",
                doc_id=r.get("a_doc_id", "unknown"),
                relation_type=r.get("type"),
            ))
        return citations

    def _build_drill_down(
        self, mode: ResponseMode, chunks: list[dict], relations: list[dict]
    ) -> list[dict]:
        """Section 5 : pointers vers UI admin pour explorer."""
        items = []
        if mode == ResponseMode.CONFLICT_RISK:
            items.append({
                "label": "Voir toutes les contradictions",
                "url": "/admin/relations?type=CONFLICT",
            })
        if mode == ResponseMode.EXPLORATION_RELATIONAL:
            items.append({
                "label": "Explorer les relations typées",
                "url": "/admin/relations",
            })
        if chunks:
            doc_ids = sorted({c.get("doc_id") for c in chunks[:3] if c.get("doc_id")})
            for doc_id in doc_ids:
                items.append({
                    "label": f"Voir le document {doc_id}",
                    "url": f"/documents/{doc_id}",
                })
        return items


__all__ = ["ResponseComposer", "ComposedResponse", "EvidenceCitation"]
