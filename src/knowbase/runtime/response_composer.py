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

        # 3. Bloc métier modulable (resolved fourni pour SNAPSHOT.as_of, etc.)
        business_block = self._build_business_block(resolved, chunks, relations)

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
        self, resolved: ResolvedQuery, chunks: list[dict], relations: list[dict]
    ) -> dict:
        """Bloc métier modulable selon mode."""
        mode = resolved.mode

        if mode == ResponseMode.LOOKUP_FACTUAL:
            return {"type": "factual_value", "top_match": chunks[0] if chunks else None}

        if mode == ResponseMode.APPLICABILITY_QUERY:
            applicable = [c for c in chunks if c.get("lifecycle_status") in ("ACTIVE", None, "UNKNOWN")]
            withdrawn = [c for c in chunks if c.get("lifecycle_status") in ("WITHDRAWN", "DEPRECATED", "SUPERSEDED")]
            # Group by doc_id pour audit trail
            by_doc: dict[str, list[dict]] = {}
            for c in applicable:
                doc = c.get("doc_id", "unknown")
                by_doc.setdefault(doc, []).append(c)
            return {
                "type": "applicable_rules",
                "rules": applicable[:10],
                "withdrawn_excluded": [{"claim_id": c.get("claim_id"), "doc_id": c.get("doc_id"), "lifecycle": c.get("lifecycle_status")} for c in withdrawn[:5]],
                "by_document": {k: len(v) for k, v in by_doc.items()},
            }

        if mode == ResponseMode.SNAPSHOT_TEMPORAL:
            as_of_iso = resolved.temporal_anchor.isoformat() if resolved.temporal_anchor else None
            # Indicateur lifecycle au point T
            active_at_t = [c for c in chunks if c.get("lifecycle_status") not in ("WITHDRAWN", "REPEALED", "DEPRECATED")]
            return {
                "type": "snapshot",
                "as_of": as_of_iso,
                "claims_at_t": chunks[:10],
                "n_active_at_t": len(active_at_t),
                "n_total_valid": len(chunks),
            }

        if mode == ResponseMode.DIFF_EVOLUTION:
            introduced = [c for c in chunks if c.get("diff_change_type") == "introduced"]
            retired = [c for c in chunks if c.get("diff_change_type") == "retired"]
            modified = [c for c in chunks if c.get("diff_change_type") == "modified"]
            reaffirmed = [c for c in chunks if c.get("diff_change_type") == "reaffirmed"]
            period = None
            if resolved.temporal_range:
                period = {
                    "start": resolved.temporal_range[0].isoformat(),
                    "end": resolved.temporal_range[1].isoformat(),
                }
            return {
                "type": "diff",
                "period": period,
                "introduced": introduced,
                "retired": retired,
                "modified": modified,
                "reaffirmed": reaffirmed,
                "summary": {
                    "introduced": len(introduced),
                    "retired": len(retired),
                    "modified": len(modified),
                    "reaffirmed": len(reaffirmed),
                },
            }

        if mode == ResponseMode.CONFLICT_RISK:
            # Enrichi avec les 2 côtés (a / b) + reasoning + scope
            conflicts_all = [r for r in relations if r.get("type") == "CONFLICT"]
            conflicts_real = [r for r in conflicts_all if r.get("is_contradiction")]
            enriched = []
            for r in conflicts_real[:20]:
                enriched.append({
                    "claim_a": {
                        "claim_id": r.get("a_claim_id"),
                        "text": (r.get("a_text") or "")[:300],
                        "doc_id": r.get("a_doc_id"),
                    },
                    "claim_b": {
                        "claim_id": r.get("b_claim_id"),
                        "text": (r.get("b_text") or "")[:300],
                        "doc_id": r.get("b_doc_id"),
                    },
                    "confidence": r.get("confidence"),
                    "strength": r.get("strength"),
                    "scope_alignment": r.get("scope_alignment"),
                    "temporal_relation": r.get("temporal_relation"),
                    "reasoning": (r.get("reasoning") or "")[:400],
                })
            return {
                "type": "contradictions",
                "conflicts": enriched,
                "n_total_candidates": len(conflicts_all),
                "n_real_conflicts": len(conflicts_real),
            }

        if mode == ResponseMode.EXPLORATION_RELATIONAL:
            # Drill-down par type avec exemples top-3 par type
            by_type: dict[str, list[dict]] = {}
            for r in relations:
                t = r.get("type", "UNKNOWN")
                by_type.setdefault(t, []).append(r)
            type_breakdown = {}
            for t, rels in by_type.items():
                # tri par confidence desc + 3 examples
                rels_sorted = sorted(rels, key=lambda x: float(x.get("confidence", 0) or 0), reverse=True)
                type_breakdown[t] = {
                    "count": len(rels),
                    "examples": [
                        {
                            "claim_a_text": (r.get("a_text") or "")[:200],
                            "claim_b_text": (r.get("b_text") or "")[:200],
                            "confidence": r.get("confidence"),
                            "reasoning": (r.get("reasoning") or "")[:200],
                        }
                        for r in rels_sorted[:3]
                    ],
                }
            return {
                "type": "navigation",
                "relations_by_type": type_breakdown,
                "n_total_relations": len(relations),
            }

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
        """Section 3 : preuves verbatim (top-k chunks + 2 relations clés).

        Defensive : on coalesce les claim_id/doc_id null car Qdrant + KG peuvent
        retourner des metadata partielles selon les payloads d'ingestion.
        """
        citations = []
        for c in chunks[:top_k]:
            citations.append(EvidenceCitation(
                claim_id=str(c.get("claim_id") or "unknown"),
                text=c.get("text") or "",
                doc_id=str(c.get("doc_id") or "unknown"),
                publication_date=c.get("publication_date"),
                validity_start=c.get("validity_start"),
                validity_end=c.get("validity_end"),
                lifecycle_status=c.get("lifecycle_status"),
            ))
        # Top 2 relations comme evidences supplémentaires
        for r in (relations or [])[:2]:
            citations.append(EvidenceCitation(
                claim_id=str(r.get("a_claim_id") or "unknown"),
                text=f"[via {r.get('type')}] {(r.get('reasoning') or '')[:200]}",
                doc_id=str(r.get("a_doc_id") or "unknown"),
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
            # Liens drill-down par type présent
            seen_types = set()
            for r in relations[:20]:
                t = r.get("type")
                if t and t not in seen_types:
                    seen_types.add(t)
                    items.append({
                        "label": f"Filtrer relations {t}",
                        "url": f"/admin/relations?type={t}",
                    })
        if mode == ResponseMode.SNAPSHOT_TEMPORAL:
            items.append({
                "label": "Voir le KG completes au point T (Atlas)",
                "url": "/atlas",
            })
        if mode == ResponseMode.DIFF_EVOLUTION:
            items.append({
                "label": "Voir les SUPERSEDES dans le KG",
                "url": "/admin/relations?type=SUPERSEDES",
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
