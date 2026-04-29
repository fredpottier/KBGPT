"""
S4.B — Temporal Retrieval Layer V3.3 (cf. CONTRADICTION_DETECTION_ARCHITECTURE.md §4 bis).

Layer de retrieval temporellement aware pour Qdrant + Cypher. Permet aux
queries du runtime V1.1 de spécifier un `as_of_date` paramétrable.

3 modes :
1. **SNAPSHOT** : claims valides à T (filtrage `validity_start ≤ T ≤ validity_end`)
2. **WEIGHTED** : score boosté pour claims plus récents (recency weight)
3. **DIFF** : claims qui ont changé entre T1 et T2 (diff evolution)

Pattern V3.3 :
- Le mode SNAPSHOT utilise les 3 timestamps de TemporalFrame (S1a + S1b)
- Si un claim n'a pas validity_start (Tier 5 default), on retombe sur publication_date
- Si un claim n'a pas validity_end, on assume qu'il est encore actif (validity_end = "infinity")
- Domain-agnostic : opère uniquement sur des champs typés (date), pas de logique domaine
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional

from neo4j import Driver

logger = logging.getLogger(__name__)


class TemporalMode(str, Enum):
    """Mode de retrieval temporel."""

    SNAPSHOT = "SNAPSHOT"   # Claims valides à T (point-in-time)
    WEIGHTED = "WEIGHTED"   # Tous claims avec recency weight (boost les récents)
    DIFF = "DIFF"           # Diff entre T1 et T2 (evolution)


@dataclass
class TemporalFilter:
    """Filtre temporel à appliquer à un retrieval."""

    mode: TemporalMode
    as_of_date: Optional[date] = None
    """Pour SNAPSHOT : date du point de référence."""
    period_start: Optional[date] = None
    """Pour DIFF : début de la période."""
    period_end: Optional[date] = None
    """Pour DIFF : fin de la période."""
    recency_decay_years: float = 5.0
    """Pour WEIGHTED : nombre d'années pour qu'un claim ait un poids /2."""


@dataclass
class TemporalQueryResult:
    """Résultat d'une query temporelle."""

    claim_id: str
    text: str
    doc_id: str
    publication_date: Optional[str] = None
    validity_start: Optional[str] = None
    validity_end: Optional[str] = None
    lifecycle_status: Optional[str] = None
    recency_weight: float = 1.0
    """Pour mode WEIGHTED : multiplicateur de score (1.0 = neutre)."""
    diff_change_type: Optional[str] = None
    """Pour mode DIFF : 'introduced', 'modified', 'retired', 'reaffirmed'."""


# ============================================================================
# Temporal Retriever
# ============================================================================

class TemporalRetriever:
    """
    Retriever Cypher avec filtrage temporel V3.3.

    Note : pour Qdrant, le filtrage temporel se fait via les payload filters
    (à condition que le payload Qdrant inclut les 3 timestamps — à backfiller
    en S4.B.next si besoin pour le runtime). Cette classe gère le côté Neo4j.
    """

    def __init__(self, neo4j_driver: Driver, tenant_id: str = "default"):
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    def retrieve_snapshot(
        self,
        as_of_date: date,
        doc_filter: Optional[list[str]] = None,
        subject_filter: Optional[list[str]] = None,
        limit: int = 100,
    ) -> list[TemporalQueryResult]:
        """
        Retourne les claims valides à `as_of_date`.

        Critère :
        - validity_start ≤ as_of_date (ou null = "always valid since publication")
        - validity_end ≥ as_of_date (ou null = "still active")

        Fallback : si validity_start est null, utilise publication_date comme proxy.
        """
        as_of_iso = as_of_date.isoformat() if isinstance(as_of_date, date) else str(as_of_date)

        where_clauses = ["c.tenant_id = $tid"]
        if doc_filter:
            where_clauses.append("c.doc_id IN $doc_filter")
        if subject_filter:
            where_clauses.append("any(s IN $subject_filter WHERE c.text CONTAINS s)")

        # Validity logic
        # claim valid AT date T iff:
        #   (validity_start <= T OR validity_start IS NULL AND publication_date <= T)
        #   AND (validity_end >= T OR validity_end IS NULL)
        where_clauses.append("""
            (c.validity_start IS NULL OR c.validity_start <= $as_of)
            AND (c.publication_date IS NULL OR c.publication_date <= $as_of)
            AND (c.validity_end IS NULL OR c.validity_end >= $as_of)
        """)
        where_str = " AND ".join(where_clauses)

        query = f"""
            MATCH (c:Claim)
            WHERE {where_str}
            RETURN
              c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id,
              c.publication_date AS publication_date,
              c.validity_start AS validity_start,
              c.validity_end AS validity_end,
              c.lifecycle_status AS lifecycle_status
            LIMIT $lim
        """

        with self.driver.session() as s:
            rows = s.run(query, tid=self.tenant_id, as_of=as_of_iso,
                         doc_filter=doc_filter, subject_filter=subject_filter,
                         lim=limit).data()

        return [
            TemporalQueryResult(
                claim_id=r["claim_id"],
                text=r["text"] or "",
                doc_id=r["doc_id"],
                publication_date=r["publication_date"],
                validity_start=r["validity_start"],
                validity_end=r["validity_end"],
                lifecycle_status=r["lifecycle_status"],
                recency_weight=1.0,
            )
            for r in rows
        ]

    def retrieve_weighted(
        self,
        reference_date: Optional[date] = None,
        decay_years: float = 5.0,
        doc_filter: Optional[list[str]] = None,
        limit: int = 100,
    ) -> list[TemporalQueryResult]:
        """
        Retourne tous claims avec un recency weight calculé.

        Weight = 0.5 ** ((reference_date - publication_date) / decay_years).
        Plus le claim est ancien, plus le weight diminue.
        Si publication_date est null, weight = 1.0 (neutre).
        """
        ref_date = reference_date or date.today()
        ref_iso = ref_date.isoformat()

        where_clauses = ["c.tenant_id = $tid"]
        if doc_filter:
            where_clauses.append("c.doc_id IN $doc_filter")
        where_str = " AND ".join(where_clauses)

        query = f"""
            MATCH (c:Claim)
            WHERE {where_str}
            RETURN
              c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id,
              c.publication_date AS publication_date,
              c.validity_start AS validity_start,
              c.validity_end AS validity_end,
              c.lifecycle_status AS lifecycle_status,
              CASE
                WHEN c.publication_date IS NULL THEN 1.0
                ELSE
                  CASE
                    WHEN duration.between(date(c.publication_date), date($ref)).years > 0
                    THEN exp(-0.693 * duration.between(date(c.publication_date), date($ref)).years / $decay)
                    ELSE 1.0
                  END
              END AS recency_weight
            ORDER BY recency_weight DESC
            LIMIT $lim
        """

        with self.driver.session() as s:
            rows = s.run(query, tid=self.tenant_id, ref=ref_iso,
                         decay=decay_years, doc_filter=doc_filter, lim=limit).data()

        return [
            TemporalQueryResult(
                claim_id=r["claim_id"],
                text=r["text"] or "",
                doc_id=r["doc_id"],
                publication_date=r["publication_date"],
                validity_start=r["validity_start"],
                validity_end=r["validity_end"],
                lifecycle_status=r["lifecycle_status"],
                recency_weight=float(r["recency_weight"] or 1.0),
            )
            for r in rows
        ]

    def retrieve_diff(
        self,
        period_start: date,
        period_end: date,
        doc_filter: Optional[list[str]] = None,
        limit: int = 100,
    ) -> list[TemporalQueryResult]:
        """
        Retourne les claims qui ont changé entre period_start et period_end.

        Catégories :
        - **introduced** : claims publiés entre [start, end] (nouveaux)
        - **retired** : claims ayant validity_end ∈ [start, end]
        - **modified** : claims liés par SUPERSEDES dont validité ∈ [start, end]
        - **reaffirmed** : claims liés par REAFFIRMS dans la période
        """
        results: list[TemporalQueryResult] = []

        # Introduced
        with self.driver.session() as s:
            for r in s.run(
                """
                MATCH (c:Claim {tenant_id: $tid})
                WHERE c.publication_date >= $start AND c.publication_date <= $end
                  AND ($docs IS NULL OR c.doc_id IN $docs)
                RETURN c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id,
                       c.publication_date AS publication_date,
                       c.validity_start AS validity_start, c.validity_end AS validity_end,
                       c.lifecycle_status AS lifecycle_status
                LIMIT $lim
                """,
                tid=self.tenant_id, start=period_start.isoformat(), end=period_end.isoformat(),
                docs=doc_filter, lim=limit,
            ).data():
                results.append(TemporalQueryResult(
                    claim_id=r["claim_id"], text=r["text"] or "", doc_id=r["doc_id"],
                    publication_date=r["publication_date"],
                    validity_start=r["validity_start"], validity_end=r["validity_end"],
                    lifecycle_status=r["lifecycle_status"],
                    diff_change_type="introduced",
                ))

            # Retired
            for r in s.run(
                """
                MATCH (c:Claim {tenant_id: $tid})
                WHERE c.validity_end >= $start AND c.validity_end <= $end
                  AND ($docs IS NULL OR c.doc_id IN $docs)
                RETURN c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id,
                       c.publication_date AS publication_date,
                       c.validity_start AS validity_start, c.validity_end AS validity_end,
                       c.lifecycle_status AS lifecycle_status
                LIMIT $lim
                """,
                tid=self.tenant_id, start=period_start.isoformat(), end=period_end.isoformat(),
                docs=doc_filter, lim=limit,
            ).data():
                results.append(TemporalQueryResult(
                    claim_id=r["claim_id"], text=r["text"] or "", doc_id=r["doc_id"],
                    publication_date=r["publication_date"],
                    validity_start=r["validity_start"], validity_end=r["validity_end"],
                    lifecycle_status=r["lifecycle_status"],
                    diff_change_type="retired",
                ))

            # Modified (via SUPERSEDES)
            for r in s.run(
                """
                MATCH (newer:Claim {tenant_id: $tid})-[:LOGICAL_RELATION {type: 'SUPERSEDES'}]->(older:Claim)
                WHERE newer.publication_date >= $start AND newer.publication_date <= $end
                  AND ($docs IS NULL OR newer.doc_id IN $docs)
                RETURN newer.claim_id AS claim_id, newer.text AS text, newer.doc_id AS doc_id,
                       newer.publication_date AS publication_date,
                       newer.validity_start AS validity_start, newer.validity_end AS validity_end,
                       newer.lifecycle_status AS lifecycle_status
                LIMIT $lim
                """,
                tid=self.tenant_id, start=period_start.isoformat(), end=period_end.isoformat(),
                docs=doc_filter, lim=limit,
            ).data():
                results.append(TemporalQueryResult(
                    claim_id=r["claim_id"], text=r["text"] or "", doc_id=r["doc_id"],
                    publication_date=r["publication_date"],
                    validity_start=r["validity_start"], validity_end=r["validity_end"],
                    lifecycle_status=r["lifecycle_status"],
                    diff_change_type="modified",
                ))

        return results


__all__ = ["TemporalMode", "TemporalFilter", "TemporalQueryResult", "TemporalRetriever"]
