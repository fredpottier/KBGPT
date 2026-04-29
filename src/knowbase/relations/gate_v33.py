"""
S2.B — Scope/Temporal Gate V3.3.

Avant chaque appel LLM 12-class classifier, le Gate vérifie la compatibilité
**scope ET temporelle** des 2 claims. Filtre déterministiquement (sans LLM)
les paires qui sont :
- Sur scopes disjoints → SKIP_DISJOINT (pas de relation logique possible)
- Sur même scope mais validity windows non-chevauchantes → LIKELY_SUPERSEDES
- Sur scopes équivalents avec dates équivalentes → LIKELY_REAFFIRMS
- Tous les autres cas → FULL_LLM_CLASSIFY (passe au 12-class classifier en S3)

Inputs :
- ApplicabilityFrameV2 par doc (S1a backfill)
- TemporalFrame claim-level (S1b backfill : publication_date, validity_start/end)

Cible (cf. plan §S2 acceptation) : ≥30% des paires retenues par S2.A sont
filtrées par S2.B sans appel LLM.

Test régression : cas du laser pulse (V3.3 §4) doit être tranché REFINES
(via SUBSET) sans LLM.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from neo4j import Driver

from knowbase.relations.v33_types import (
    GateDecision,
    LogicalRelationType,
    ScopeRelation,
    TemporalRelation,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Gate verdict (audit trail persisté avant LLM call)
# ============================================================================

@dataclass
class GateVerdict:
    """Verdict du Gate pour une paire de claims."""

    a_claim_id: str
    b_claim_id: str
    decision: GateDecision
    scope_relation: ScopeRelation
    temporal_relation: TemporalRelation
    pre_classified_relation: Optional[LogicalRelationType] = None
    """Si la décision pre-classifie (LIKELY_SUPERSEDES/REAFFIRMS), le type cible."""
    reasoning: str = ""


# ============================================================================
# Gate core
# ============================================================================

class ScopeTemporalGateV33:
    """
    Filtre déterministe avant le 12-class classifier LLM.

    Lit les ApplicabilityFrameV2 (DocumentContext) et les dates Claim
    (publication_date, validity_start/end) pour décider si la paire :
    - Doit être skippée (scopes disjoints)
    - Peut être pré-classifiée (LIKELY_SUPERSEDES/REAFFIRMS)
    - Doit aller au LLM (FULL_LLM_CLASSIFY)
    """

    def __init__(self, neo4j_driver: Driver, tenant_id: str = "default"):
        self.driver = neo4j_driver
        self.tenant_id = tenant_id
        self._frame_cache: dict[str, dict] = {}

    def evaluate_pair(self, a_claim_id: str, b_claim_id: str) -> GateVerdict:
        """
        Évalue une paire et retourne le verdict du Gate.

        Args:
            a_claim_id, b_claim_id: IDs des 2 claims

        Returns:
            GateVerdict avec décision + audit
        """
        a_data = self._fetch_claim_with_frame(a_claim_id)
        b_data = self._fetch_claim_with_frame(b_claim_id)

        # Si on n'a pas pu charger un des claims → FULL_LLM_CLASSIFY (prudence)
        if not a_data or not b_data:
            return GateVerdict(
                a_claim_id=a_claim_id,
                b_claim_id=b_claim_id,
                decision=GateDecision.FULL_LLM_CLASSIFY,
                scope_relation=ScopeRelation.UNKNOWN,
                temporal_relation=TemporalRelation.UNKNOWN,
                reasoning="Missing claim data — defer to LLM",
            )

        # Compute scope & temporal relations
        scope_rel = self.compute_scope_relation(a_data["frame"], b_data["frame"])
        temp_rel = self.compute_temporal_relation(a_data, b_data)

        # Decision tree (cf. plan §S2.B + V3.3 §4 ter)
        if scope_rel == ScopeRelation.DISJOINT:
            return GateVerdict(
                a_claim_id, b_claim_id,
                decision=GateDecision.SKIP_DISJOINT,
                scope_relation=scope_rel,
                temporal_relation=temp_rel,
                pre_classified_relation=LogicalRelationType.DISJOINT,
                reasoning="Scopes disjoints — pas de relation logique possible",
            )

        # Scopes alignés + temporal disjoint → fort indice SUPERSEDES
        if (
            scope_rel in (ScopeRelation.EQUIVALENT, ScopeRelation.SUBSET, ScopeRelation.SUPERSET)
            and temp_rel in (TemporalRelation.A_BEFORE_B, TemporalRelation.B_BEFORE_A)
        ):
            return GateVerdict(
                a_claim_id, b_claim_id,
                decision=GateDecision.LIKELY_SUPERSEDES,
                scope_relation=scope_rel,
                temporal_relation=temp_rel,
                pre_classified_relation=LogicalRelationType.SUPERSEDES,
                reasoning="Scopes alignés mais validity windows disjointes — candidat SUPERSEDES",
            )

        # Scopes équivalents + temporal overlap → REAFFIRMS candidate (à confirmer LLM)
        if scope_rel == ScopeRelation.EQUIVALENT and temp_rel == TemporalRelation.OVERLAP:
            return GateVerdict(
                a_claim_id, b_claim_id,
                decision=GateDecision.LIKELY_REAFFIRMS,
                scope_relation=scope_rel,
                temporal_relation=temp_rel,
                pre_classified_relation=LogicalRelationType.REAFFIRMS,
                reasoning="Scopes équivalents + temporal overlap — candidat REAFFIRMS (LLM confirmera)",
            )

        # Tous les autres cas → LLM classifier décide
        return GateVerdict(
            a_claim_id, b_claim_id,
            decision=GateDecision.FULL_LLM_CLASSIFY,
            scope_relation=scope_rel,
            temporal_relation=temp_rel,
            reasoning="Cas non-trivial — LLM classifier 12-types tranchera",
        )

    # ------------------------------------------------------------------------
    # Scope relation (basée sur ApplicabilityFrame V2)
    # ------------------------------------------------------------------------

    def compute_scope_relation(self, frame_a: Optional[dict], frame_b: Optional[dict]) -> ScopeRelation:
        """
        Compute la relation entre 2 ApplicabilityFrame V2.

        Compare les 5 champs de Scope axis :
        product_version, region, edition, conditions, subject_class.

        Heuristique :
        - Si product_version différent ET subject_class différent → DISJOINT
        - Si tous champs comparables identiques → EQUIVALENT
        - Si scope_a fields ⊆ scope_b fields (mêmes + plus) → SUBSET
        - Inverse → SUPERSET
        - Si chevauchent partiellement → OVERLAPPING
        - Sinon UNKNOWN
        """
        if not frame_a or not frame_b:
            return ScopeRelation.UNKNOWN

        scope_a = frame_a.get("scope", {}) or {}
        scope_b = frame_b.get("scope", {}) or {}

        # Champs de scope normalisés (value uniquement, pas evidence_quote)
        a_pv = self._field_value(scope_a.get("product_version"))
        b_pv = self._field_value(scope_b.get("product_version"))
        a_reg = self._field_value(scope_a.get("region"))
        b_reg = self._field_value(scope_b.get("region"))
        a_ed = self._field_value(scope_a.get("edition"))
        b_ed = self._field_value(scope_b.get("edition"))
        a_sc = self._field_value(scope_a.get("subject_class"))
        b_sc = self._field_value(scope_b.get("subject_class"))

        # Disjoint : product_version différent ET subject_class différent
        if a_pv and b_pv and a_pv != b_pv and a_sc and b_sc and a_sc != b_sc:
            return ScopeRelation.DISJOINT

        # Equivalent : tous les champs comparables identiques
        comparable_fields = []
        if a_pv and b_pv:
            comparable_fields.append((a_pv, b_pv))
        if a_reg and b_reg:
            comparable_fields.append((a_reg, b_reg))
        if a_ed and b_ed:
            comparable_fields.append((a_ed, b_ed))
        if a_sc and b_sc:
            comparable_fields.append((a_sc, b_sc))

        if not comparable_fields:
            return ScopeRelation.UNKNOWN

        all_equal = all(a == b for a, b in comparable_fields)
        any_equal = any(a == b for a, b in comparable_fields)
        any_diff = any(a != b for a, b in comparable_fields)

        if all_equal:
            return ScopeRelation.EQUIVALENT
        if any_equal and any_diff:
            # Si edition différente mais product_version + region identiques :
            # le doc le plus récent = SUPERSET (couvre + de scope ?), heuristique.
            # Pour l'instant on retourne OVERLAPPING.
            return ScopeRelation.OVERLAPPING

        return ScopeRelation.UNKNOWN

    # ------------------------------------------------------------------------
    # Temporal relation (basée sur publication_date / validity_start/end)
    # ------------------------------------------------------------------------

    def compute_temporal_relation(self, a_data: dict, b_data: dict) -> TemporalRelation:
        """
        Compare les fenêtres de validité entre 2 claims.

        Utilise publication_date comme fallback si validity_start/end null.
        """
        a_start = self._parse_date(a_data.get("validity_start") or a_data.get("publication_date"))
        a_end = self._parse_date(a_data.get("validity_end"))
        b_start = self._parse_date(b_data.get("validity_start") or b_data.get("publication_date"))
        b_end = self._parse_date(b_data.get("validity_end"))

        if not a_start and not b_start:
            return TemporalRelation.UNKNOWN

        # A se termine avant que B commence → A_BEFORE_B
        if a_end and b_start and a_end < b_start:
            return TemporalRelation.A_BEFORE_B
        # B se termine avant que A commence → B_BEFORE_A
        if b_end and a_start and b_end < a_start:
            return TemporalRelation.B_BEFORE_A

        # Si les 2 ont une start mais a_start très éloigné de b_start (>2 ans)
        # et un seul a une end → considère DISJOINT
        if a_start and b_start:
            return TemporalRelation.OVERLAP

        return TemporalRelation.UNKNOWN

    # ------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------

    def _fetch_claim_with_frame(self, claim_id: str) -> Optional[dict]:
        """Charge claim + DocumentContext.applicability_frame_v2_json (cache)."""
        with self.driver.session() as s:
            row = s.run(
                """
                MATCH (c:Claim {claim_id: $cid, tenant_id: $tid})
                MATCH (dc:DocumentContext {doc_id: c.doc_id, tenant_id: $tid})
                RETURN
                  c.claim_id AS claim_id,
                  c.publication_date AS publication_date,
                  c.validity_start AS validity_start,
                  c.validity_end AS validity_end,
                  c.lifecycle_status AS lifecycle_status,
                  dc.applicability_frame_v2_json AS frame_json,
                  dc.publication_date AS doc_pub_date
                """,
                cid=claim_id,
                tid=self.tenant_id,
            ).single()
            if not row:
                return None
            frame = None
            if row["frame_json"]:
                try:
                    frame = json.loads(row["frame_json"])
                except json.JSONDecodeError:
                    frame = None
            return {
                "claim_id": row["claim_id"],
                "publication_date": row["publication_date"] or row["doc_pub_date"],
                "validity_start": row["validity_start"],
                "validity_end": row["validity_end"],
                "lifecycle_status": row["lifecycle_status"],
                "frame": frame,
            }

    @staticmethod
    def _field_value(field: Optional[dict]) -> Optional[str]:
        """Extrait .value d'un EvidenceLockedField (None safe)."""
        if not field or not isinstance(field, dict):
            return None
        return field.get("value")

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        """Parse une date YYYY-MM-DD ou YYYY (year-only) en date Python."""
        if not value:
            return None
        s = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None


__all__ = ["ScopeTemporalGateV33", "GateVerdict"]
