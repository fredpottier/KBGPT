"""
Current Resolver — V2-S3.

Algorithme déterministe en 3 phases (Vision §4.3) :

  Phase 1 — Filtrage strict sur faits documentés (Cypher)
            * lifecycle_status = ACTIVE (ou NULL traité comme ACTIVE par défaut)
            * validity_start ≤ today < (validity_end OR ∞)
            * exclure docs avec successeur EXPLICITEMENT déclaré actif (LIFECYCLE_RELATION SUPERSEDES)

  Phase 2 — Ranking par heuristiques runtime (jamais persistées)
            * recency : (date - oldest)/(newest - oldest)
            * version_ordering : si numéros extractibles, plus haut = score plus haut
            * kg_centrality : sum(relations entrantes + sortantes) normalisé
            * trust_score : default 0.5 (override possible si propriété sur DocumentContext)

  Phase 3 — Politique graduée seuils 0.85/0.55
            * 1 candidat            → auto-pick
            * top ≥ 0.85            → auto-pick high confidence
            * 0.55 ≤ top < 0.85     → suggérer + alternatives
            * top < 0.55            → escalade au user
            * 0 candidat            → not_found

Domain-agnostic :
- Lifecycle ACTIVE par défaut (NULL traité comme ACTIVE)
- Version ordering : extraction structurelle de numéros (digit-only tokenization
  cohérente avec V2-S1/V2-S2)
- KG centrality : count brut des relations (ne dépend pas du type de relation)
"""
from __future__ import annotations

import logging
import re
from datetime import date as date_cls
from datetime import datetime
from typing import Optional

from neo4j import Driver

from knowbase.current.models import (
    ConfidenceWeights,
    CurrentCandidate,
    CurrentResolverDecision,
    CurrentResolverResult,
)

logger = logging.getLogger(__name__)


def _digit_run_tokens(text: str) -> list[int]:
    """Extrait les runs de chiffres d'un texte (pour version ordering).

    "CS-25 Amendment 28" → [25, 28]
    "v3.2.1" → [3, 2, 1]
    "1809" → [1809]
    "2021/821" → [2021, 821]
    "no version here" → []
    """
    if not text:
        return []
    return [int(m.group(0)) for m in re.finditer(r"\d+", text)]


def _parse_iso_date(d: Optional[str]) -> Optional[date_cls]:
    """Parse une date ISO (YYYY-MM-DD ou YYYY) tolérante."""
    if not d:
        return None
    d = d.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(d, fmt).date()
        except ValueError:
            continue
    return None


class CurrentResolver:
    """Résout le doc autoritaire pour un sujet (anchor=CURRENT_DEFAULT)."""

    def __init__(
        self,
        driver: Driver,
        tenant_id: str = "default",
        weights: Optional[ConfidenceWeights] = None,
    ) -> None:
        self.driver = driver
        self.tenant_id = tenant_id
        self.weights = weights or ConfidenceWeights()

    def resolve(
        self,
        subject_id: Optional[str] = None,
        candidate_doc_ids: Optional[list[str]] = None,
        as_of: Optional[date_cls] = None,
    ) -> CurrentResolverResult:
        """Résout le doc current pour un sujet.

        Args:
            subject_id: hash de subject (cf. DocumentContext.subject_ids[]) — optional.
            candidate_doc_ids: alternativement, liste explicite de doc_ids à évaluer
                (typiquement passée par AnchorFilter pour CURRENT_DEFAULT).
            as_of: date de référence pour la résolution (default = today). Permet de
                résoudre "current at past date" sans modifier le KG.

        Si subject_id ET candidate_doc_ids sont None, on évalue TOUS les
        DocumentContext du tenant (peu utile en runtime mais cohérent en test).

        Returns:
            CurrentResolverResult avec la décision et les candidats rankés.
        """
        if as_of is None:
            as_of = date_cls.today()

        # Phase 1 — Filtrage strict
        candidates_p1 = self._phase1_filter(subject_id, candidate_doc_ids, as_of)

        if not candidates_p1:
            return CurrentResolverResult(
                decision=CurrentResolverDecision.NOT_FOUND,
                n_filtered_in_phase1=0,
                weights_used=self.weights,
                reasoning="Phase 1 returned 0 candidates (no active docs matching the constraints).",
            )

        # Phase 2 — Ranking heuristiques
        ranked = self._phase2_rank(candidates_p1)

        # Phase 3 — Politique graduée
        return self._phase3_policy(ranked)

    # ------------------------------------------------------------------
    # Phase 1 — Filtrage strict
    # ------------------------------------------------------------------

    def _phase1_filter(
        self,
        subject_id: Optional[str],
        candidate_doc_ids: Optional[list[str]],
        as_of: date_cls,
    ) -> list[dict]:
        """Filtre les DocumentContext sur lifecycle + validity + absence de successeur déclaré.

        - lifecycle_status NULL est traité comme ACTIVE (default V3.3 : statut non extrait
          = pas une raison de l'exclure).
        - validity_start NULL : on assume valid since publication_date.
        - validity_end NULL : on assume toujours valide.
        """
        params = {
            "tenant_id": self.tenant_id,
            "as_of": as_of.isoformat(),
        }
        cypher = ["MATCH (dc:DocumentContext)", "WHERE dc.tenant_id = $tenant_id"]
        if subject_id is not None:
            cypher.append(
                "  AND ($subject_id IN coalesce(dc.subject_ids, []) "
                "       OR dc.primary_subject = $subject_id)"
            )
            params["subject_id"] = subject_id
        if candidate_doc_ids is not None:
            cypher.append("  AND dc.doc_id IN $candidate_doc_ids")
            params["candidate_doc_ids"] = candidate_doc_ids

        # lifecycle_status : NULL ou ACTIVE acceptés
        cypher.append(
            "  AND (dc.lifecycle_status IS NULL "
            "       OR dc.lifecycle_status = 'ACTIVE')"
        )

        # validity_start ≤ as_of, avec fallback runtime sur publication_date
        # (cf. VISION_RECENTREE §4.2 : convention runtime — claim/doc sans validity_start
        # hérite de publication_date pour le filtrage temporel).
        # Si publication_date est aussi null → considéré intemporel (pas de contrainte).
        cypher.append(
            "  AND ("
            "    (dc.validity_start IS NULL AND dc.publication_date IS NULL) "
            "    OR (dc.validity_start IS NOT NULL "
            "        AND date(dc.validity_start) <= date($as_of)) "
            "    OR (dc.validity_start IS NULL "
            "        AND dc.publication_date IS NOT NULL "
            "        AND date(dc.publication_date) <= date($as_of))"
            "  )"
        )

        # validity_end > as_of OR NULL
        cypher.append(
            "  AND (dc.validity_end IS NULL "
            "       OR date(dc.validity_end) > date($as_of))"
        )

        cypher.append("WITH dc")

        # Exclure les docs avec successeur SUPERSEDES ACTIF à as_of
        # Convention runtime identique : si succ.validity_start est NULL, on hérite de
        # succ.publication_date pour décider si le successeur est déjà actif à as_of.
        cypher.append(
            "OPTIONAL MATCH (dc)<-[:LIFECYCLE_RELATION {type: 'SUPERSEDES'}]-(succ:DocumentContext)"
        )
        cypher.append(
            "  WHERE ("
            "    (succ.validity_start IS NULL AND succ.publication_date IS NULL) "
            "    OR (succ.validity_start IS NOT NULL "
            "        AND date(succ.validity_start) <= date($as_of)) "
            "    OR (succ.validity_start IS NULL "
            "        AND succ.publication_date IS NOT NULL "
            "        AND date(succ.publication_date) <= date($as_of))"
            "  )"
        )
        cypher.append(
            "    AND (succ.validity_end IS NULL OR date(succ.validity_end) > date($as_of))"
        )
        cypher.append("WITH dc, succ")
        cypher.append("WHERE succ IS NULL")

        # Compute KG centrality basique (count relations entrantes + sortantes du DocumentContext)
        cypher.append("OPTIONAL MATCH (dc)-[r_out]-()")
        cypher.append("WITH dc, count(DISTINCT r_out) AS centrality_count")

        cypher.append(
            "RETURN dc.doc_id AS doc_id, "
            "       dc.publication_date AS publication_date, "
            "       coalesce(dc.primary_subject, '') AS primary_subject, "
            "       centrality_count AS centrality_count, "
            "       coalesce(dc.trust_score, 0.5) AS trust_score"
        )

        with self.driver.session() as session:
            rows = session.run("\n".join(cypher), **params).data()

        # Vérifier post-fetch : LIFECYCLE_RELATION SUPERSEDES inverse côté target
        # (déjà géré dans la Cypher mais on garde le doc parent visible)

        results = []
        for row in rows:
            results.append(
                {
                    "doc_id": row["doc_id"],
                    "publication_date": row.get("publication_date"),
                    "primary_subject": row.get("primary_subject", ""),
                    "centrality_count": int(row.get("centrality_count") or 0),
                    "trust_score": float(row.get("trust_score") or 0.5),
                }
            )
        logger.info(
            "CurrentResolver Phase 1: %d candidate(s) post-filter (subject=%s, n_provided=%s, as_of=%s)",
            len(results),
            subject_id,
            len(candidate_doc_ids) if candidate_doc_ids else None,
            as_of,
        )
        return results

    # ------------------------------------------------------------------
    # Phase 2 — Ranking heuristiques runtime
    # ------------------------------------------------------------------

    def _phase2_rank(self, candidates: list[dict]) -> list[CurrentCandidate]:
        """Calcule les sub-scores et score agrégé pour chaque candidate.

        Toutes les heuristiques sont calculées par rapport au SET courant des
        candidats (normalisation locale, pas globale au KG).
        """
        if len(candidates) == 1:
            # Un seul candidat → score trivial = 1.0
            row = candidates[0]
            return [
                CurrentCandidate(
                    doc_id=row["doc_id"],
                    publication_date=row.get("publication_date"),
                    score_recency=1.0,
                    score_version_ordering=1.0,
                    score_kg_centrality=1.0,
                    score_trust=row["trust_score"],
                    confidence=1.0,
                    diagnostic={"single_candidate": True},
                )
            ]

        # Recency
        dates = [(_parse_iso_date(c.get("publication_date")), c) for c in candidates]
        dates_sorted = sorted([d for d, _ in dates if d is not None])
        oldest = dates_sorted[0] if dates_sorted else None
        newest = dates_sorted[-1] if dates_sorted else None

        # Version ordering : extraire le tuple de runs de chiffres du primary_subject + doc_id
        # et comparer lexicographiquement (plus haut = score plus haut).
        version_tuples = []
        for c in candidates:
            tokens = _digit_run_tokens(
                (c.get("primary_subject", "") or "") + " " + c.get("doc_id", "")
            )
            version_tuples.append(tuple(tokens))

        # Pour le ranking version : trier les tuples, le plus grand = 1.0, le plus petit = 0.0
        unique_versions_sorted = sorted(set(version_tuples))
        if len(unique_versions_sorted) > 1:
            v_rank = {v: i for i, v in enumerate(unique_versions_sorted)}
            v_rank_max = len(unique_versions_sorted) - 1
        else:
            v_rank = {}
            v_rank_max = 0

        # KG centrality : normalisation locale
        centralities = [c["centrality_count"] for c in candidates]
        c_max = max(centralities) if centralities else 0
        c_min = min(centralities) if centralities else 0

        ranked: list[CurrentCandidate] = []
        for idx, c in enumerate(candidates):
            # Recency
            d = _parse_iso_date(c.get("publication_date"))
            if d is None or oldest is None or newest is None or oldest == newest:
                score_recency = 0.5  # Indéterminé → milieu
            else:
                span_days = (newest - oldest).days or 1
                score_recency = (d - oldest).days / span_days

            # Version ordering
            vt = version_tuples[idx]
            if v_rank_max > 0 and vt in v_rank:
                score_version = v_rank[vt] / v_rank_max
            else:
                score_version = 0.5  # Pas d'ordre détectable → milieu

            # KG centrality
            if c_max > c_min:
                score_centrality = (c["centrality_count"] - c_min) / (c_max - c_min)
            else:
                score_centrality = 0.5

            # Trust
            score_trust = max(0.0, min(1.0, c["trust_score"]))

            # Score agrégé pondéré
            confidence = (
                self.weights.recency * score_recency
                + self.weights.version_ordering * score_version
                + self.weights.kg_centrality * score_centrality
                + self.weights.trust_score * score_trust
            )

            ranked.append(
                CurrentCandidate(
                    doc_id=c["doc_id"],
                    publication_date=c.get("publication_date"),
                    score_recency=round(score_recency, 4),
                    score_version_ordering=round(score_version, 4),
                    score_kg_centrality=round(score_centrality, 4),
                    score_trust=round(score_trust, 4),
                    confidence=round(confidence, 4),
                    diagnostic={
                        "centrality_count": c["centrality_count"],
                        "version_tuple": list(vt),
                    },
                )
            )

        ranked.sort(key=lambda x: x.confidence, reverse=True)
        return ranked

    # ------------------------------------------------------------------
    # Phase 3 — Politique graduée
    # ------------------------------------------------------------------

    def _phase3_policy(self, ranked: list[CurrentCandidate]) -> CurrentResolverResult:
        """Applique la politique seuils auto_pick / suggest / escalate."""
        if not ranked:
            return CurrentResolverResult(
                decision=CurrentResolverDecision.NOT_FOUND,
                n_filtered_in_phase1=0,
                weights_used=self.weights,
            )

        if len(ranked) == 1:
            return CurrentResolverResult(
                decision=CurrentResolverDecision.AUTO_PICK_SINGLE_CANDIDATE,
                top_candidate=ranked[0],
                alternatives=[],
                n_filtered_in_phase1=1,
                weights_used=self.weights,
                reasoning="Only one candidate in Phase 1 — auto-picked.",
            )

        top = ranked[0]
        alts = ranked[1:]

        if top.confidence >= self.weights.auto_pick_threshold:
            return CurrentResolverResult(
                decision=CurrentResolverDecision.AUTO_PICK_HIGH_CONFIDENCE,
                top_candidate=top,
                alternatives=alts,
                n_filtered_in_phase1=len(ranked),
                weights_used=self.weights,
                reasoning=f"Top confidence {top.confidence:.2f} ≥ auto_pick_threshold {self.weights.auto_pick_threshold:.2f}.",
            )

        if top.confidence >= self.weights.suggest_threshold:
            return CurrentResolverResult(
                decision=CurrentResolverDecision.SUGGEST_WITH_ALTERNATIVES,
                top_candidate=top,
                alternatives=alts,
                n_filtered_in_phase1=len(ranked),
                weights_used=self.weights,
                reasoning=f"Top confidence {top.confidence:.2f} ∈ [{self.weights.suggest_threshold:.2f}, {self.weights.auto_pick_threshold:.2f}) — suggest with alternatives.",
            )

        return CurrentResolverResult(
            decision=CurrentResolverDecision.ESCALATE_AMBIGUOUS,
            top_candidate=top,
            alternatives=alts,
            n_filtered_in_phase1=len(ranked),
            weights_used=self.weights,
            reasoning=f"Top confidence {top.confidence:.2f} < suggest_threshold {self.weights.suggest_threshold:.2f} — escalate to user.",
        )
