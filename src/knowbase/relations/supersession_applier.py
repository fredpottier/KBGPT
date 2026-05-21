"""
SupersessionApplier — Application de la règle de supersession bitemporelle Phase A2.

Implémente la règle §9.4 (ADR_BITEMPOREL_CLAIMS) + ADR_RELATIONS_CLAIM_CLAIM §2.4
Phase C : décide si une relation classifiée (CONTRADICTS, EVOLUTION_OF) doit
matérialiser une supersession (`:SUPERSEDES` + `invalidated_at`) ou un conflit
non-résolu (`:ConflictPending`).

Règle de supersession §9.4 (rappel) :
  Précondition : contradiction sémantique mesurée entre claim_A et claim_B
                 (NLI ou structured eval, en amont)

  CAS 1 — Les deux dates explicites
    A.valid_from IS NOT NULL ET B.valid_from IS NOT NULL
    → SI B.valid_from > A.valid_from  : B supersede A
    → SI A.valid_from > B.valid_from  : A supersede B
    → SI égales                       : pas de supersession (concurrents)

  CAS 2 — A inconnue, B explicite
    A.valid_from IS NULL ET B.valid_from IS NOT NULL
    → SI B.valid_from > A.ingested_at : B supersede A
    → SINON                            : ambigu (ConflictPending)

  CAS 3 — A explicite, B inconnue
    A.valid_from IS NOT NULL ET B.valid_from IS NULL
    → ConflictPending (ambigu)

  CAS 4 — Les deux inconnues
    A.valid_from IS NULL ET B.valid_from IS NULL
    → ConflictPending (ambigu)

Usage :
    from knowbase.relations.supersession_applier import SupersessionApplier
    applier = SupersessionApplier(neo4j_driver, tenant_id="default")
    decision = applier.apply(
        claim_a_id="c1",
        claim_b_id="c2",
        relation_type="CONTRADICTS",  # ou "EVOLUTION_OF"
        evidence_a="...",
        evidence_b="...",
        confidence=0.92,
        marker_type="inferred",
        detection_method="embedding_nli",
        detection_source="c4_relations",
    )
    # decision.action ∈ {"supersedes", "evolution_of", "conflict_pending", "no_op"}
    # decision.invalidated_claim_id : str | None
    # decision.evolution_case : "CAS_1" | "CAS_2" | "CAS_3" | "CAS_4" | "CAS_1_EQUAL"

Domain-agnostic : aucun vocabulaire corpus-spécifique. Charte open-source : aucun
appel LLM (logique 100% déterministe basée sur les timestamps).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Modèles de décision
# ============================================================================


@dataclass
class SupersessionDecision:
    """Décision prise par SupersessionApplier.apply().

    Attributs :
        action : action appliquée
            - "supersedes"        : B invalide A (:SUPERSEDES créé + A.invalidated_at setté)
            - "evolution_of"      : B est l'évolution de A sans invalidation
                                    (:EVOLUTION_OF marker_type='prudence' + :ConflictPending)
            - "conflict_pending"  : ambigu, juste :ConflictPending créé
            - "no_op"             : relation ignorée (type non supporté, ou A/B introuvable)
        invalidated_claim_id : claim_id qui a été invalidé (loser), ou None
        winner_claim_id : claim_id qui supersede (winner), ou None
        evolution_case : étiquette §9.4 ("CAS_1"|"CAS_2"|"CAS_3"|"CAS_4"|"CAS_1_EQUAL")
        conflict_pending_id : UUID du node :ConflictPending créé, ou None
        reason : courte explication textuelle (pour debug + audit)
    """

    action: str  # "supersedes" | "evolution_of" | "conflict_pending" | "no_op"
    invalidated_claim_id: Optional[str] = None
    winner_claim_id: Optional[str] = None
    evolution_case: Optional[str] = None
    conflict_pending_id: Optional[str] = None
    reason: str = ""


@dataclass
class _ClaimTemporalSnapshot:
    """Snapshot temporel d'un claim (lu depuis Neo4j) pour appliquer §9.4."""

    claim_id: str
    valid_from: Optional[str]  # ISO datetime string ou None
    valid_from_marker: Optional[str]  # 'explicit' | 'document_inherited' | 'ingestion_fallback'
    ingested_at: Optional[str]  # ISO datetime string
    invalidated_at: Optional[str]  # déjà invalidé ?


# ============================================================================
# SupersessionApplier
# ============================================================================


# Types de relation traités par l'applier (les autres passent à travers en no_op)
_HANDLED_RELATIONS = {"CONTRADICTS", "EVOLUTION_OF"}


class SupersessionApplier:
    """Applique la règle §9.4 sur les relations classifiées.

    Logique déterministe basée sur les 4 timestamps bitemporels des claims.
    Pas d'appel LLM, pas de vocabulaire corpus-spécifique.

    Thread-safety : chaque appel `apply()` ouvre sa propre session Neo4j (idempotent
    via MERGE Cypher). OK pour appel depuis worker RQ.
    """

    def __init__(self, neo4j_driver, tenant_id: str = "default") -> None:
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------------

    def apply(
        self,
        claim_a_id: str,
        claim_b_id: str,
        relation_type: str,
        evidence_a: str = "",
        evidence_b: str = "",
        confidence: float = 0.0,
        marker_type: str = "inferred",
        detection_method: str = "embedding_nli",
        detection_source: str = "a2_mainline",
        reasoning: str = "",
    ) -> SupersessionDecision:
        """Applique la règle §9.4 pour la paire (A, B) avec le type de relation donné.

        Args :
            claim_a_id : claim_id de A (ancien candidat)
            claim_b_id : claim_id de B (nouveau candidat)
            relation_type : "CONTRADICTS" ou "EVOLUTION_OF" (autres → no_op)
            evidence_a, evidence_b : verbatim spans des deux claims (AX-1)
            confidence : score d'adjudication (cf marker_type pour seuils)
            marker_type : 'explicit' | 'inferred' | 'prudence'
            detection_method : 'embedding_nli' | 'cluster_jaccard' | 'pivot_entity' | ...
            detection_source : 'detect_contradictions' | 'c4_relations' | 'c6_pivots' | 'a2_mainline'
            reasoning : explication LLM (optionnel)

        Returns :
            SupersessionDecision détaillant l'action prise.
        """
        # Filtre type : seuls CONTRADICTS et EVOLUTION_OF déclenchent l'applier
        if relation_type not in _HANDLED_RELATIONS:
            return SupersessionDecision(
                action="no_op",
                reason=f"relation_type '{relation_type}' n'est pas géré par l'applier",
            )

        # Filtre marker_type : 'prudence' → pas de :SUPERSEDES (même si CAS 1/2 satisfait)
        # Le claim B n'a pas assez de confiance pour invalider A. On crée juste :ConflictPending.
        force_conflict_pending = marker_type == "prudence"

        # Lecture snapshots temporels
        try:
            snap_a = self._load_temporal_snapshot(claim_a_id)
            snap_b = self._load_temporal_snapshot(claim_b_id)
        except Exception as e:
            logger.warning(
                f"[SupersessionApplier] Lecture snapshot échouée pour ({claim_a_id}, {claim_b_id}): {e}"
            )
            return SupersessionDecision(
                action="no_op",
                reason=f"snapshot read failed: {e}",
            )

        if snap_a is None or snap_b is None:
            return SupersessionDecision(
                action="no_op",
                reason=f"claim introuvable: A={snap_a is not None}, B={snap_b is not None}",
            )

        # Skip si l'un des deux est déjà invalidé (la chaîne d'invalidation a déjà tranché)
        if snap_a.invalidated_at is not None or snap_b.invalidated_at is not None:
            return SupersessionDecision(
                action="no_op",
                reason=(
                    f"déjà invalidé (A.invalidated_at={snap_a.invalidated_at}, "
                    f"B.invalidated_at={snap_b.invalidated_at})"
                ),
            )

        # Classification CAS 1-4 §9.4
        case = self._classify_case(snap_a, snap_b)

        # Décision selon CAS + relation_type + force_conflict_pending
        if force_conflict_pending:
            return self._create_conflict_pending(
                snap_a,
                snap_b,
                relation_type,
                case,
                confidence,
                reasoning,
                detection_method,
                detection_source,
                conflict_type="low_confidence_classification",
                evolution_case_override=case,
            )

        if case == "CAS_1":
            # Les deux dates explicites
            return self._handle_cas_1(
                snap_a,
                snap_b,
                relation_type,
                evidence_a,
                evidence_b,
                confidence,
                marker_type,
                detection_method,
                detection_source,
                reasoning,
            )
        elif case == "CAS_2":
            # A inconnue, B explicite
            return self._handle_cas_2(
                snap_a,
                snap_b,
                relation_type,
                evidence_a,
                evidence_b,
                confidence,
                marker_type,
                detection_method,
                detection_source,
                reasoning,
            )
        elif case in ("CAS_1_EQUAL", "CAS_3", "CAS_4"):
            # Ambigu : ConflictPending
            # - CAS_1_EQUAL : dates strictement égales → impossible de désigner un winner temporel
            # - CAS_3, CAS_4 : un ou deux NULL → ordre temporel inconnaissable
            return self._create_conflict_pending(
                snap_a,
                snap_b,
                relation_type,
                case,
                confidence,
                reasoning,
                detection_method,
                detection_source,
                conflict_type=(
                    "contradiction" if relation_type == "CONTRADICTS" else "evolution_ambiguous"
                ),
                evolution_case_override=case,
            )

        # Cas non reconnu (théoriquement impossible)
        logger.warning(f"[SupersessionApplier] CAS inconnu {case} pour ({claim_a_id}, {claim_b_id})")
        return SupersessionDecision(
            action="no_op",
            evolution_case=case,
            reason=f"CAS inconnu: {case}",
        )

    # ------------------------------------------------------------------------
    # Classification §9.4
    # ------------------------------------------------------------------------

    @staticmethod
    def _classify_case(
        snap_a: _ClaimTemporalSnapshot,
        snap_b: _ClaimTemporalSnapshot,
    ) -> str:
        """Retourne CAS_1 | CAS_1_EQUAL | CAS_2 | CAS_3 | CAS_4 selon §9.4."""
        a_has_date = snap_a.valid_from is not None
        b_has_date = snap_b.valid_from is not None

        if a_has_date and b_has_date:
            if snap_a.valid_from == snap_b.valid_from:
                return "CAS_1_EQUAL"
            return "CAS_1"
        if not a_has_date and b_has_date:
            return "CAS_2"
        if a_has_date and not b_has_date:
            return "CAS_3"
        return "CAS_4"

    # ------------------------------------------------------------------------
    # CAS 1 — Les deux dates explicites
    # ------------------------------------------------------------------------

    def _handle_cas_1(
        self,
        snap_a: _ClaimTemporalSnapshot,
        snap_b: _ClaimTemporalSnapshot,
        relation_type: str,
        evidence_a: str,
        evidence_b: str,
        confidence: float,
        marker_type: str,
        detection_method: str,
        detection_source: str,
        reasoning: str,
    ) -> SupersessionDecision:
        """CAS 1 : A.valid_from et B.valid_from non-NULL.

        Détermine winner/loser selon ordre temporel, puis crée :SUPERSEDES.
        Si dates égales → :ConflictPending (CAS_1_EQUAL).
        """
        if snap_a.valid_from == snap_b.valid_from:
            return self._create_conflict_pending(
                snap_a,
                snap_b,
                relation_type,
                "CAS_1_EQUAL",
                confidence,
                reasoning,
                detection_method,
                detection_source,
                conflict_type=(
                    "contradiction" if relation_type == "CONTRADICTS" else "evolution_ambiguous"
                ),
            )

        # Ordre strict
        if snap_b.valid_from > snap_a.valid_from:
            winner, loser = snap_b, snap_a
        else:
            winner, loser = snap_a, snap_b

        return self._create_supersedes(
            winner,
            loser,
            evidence_a if loser.claim_id == snap_a.claim_id else evidence_b,
            evidence_b if winner.claim_id == snap_b.claim_id else evidence_a,
            confidence,
            marker_type,
            detection_method,
            detection_source,
            reasoning,
            evolution_case="CAS_1",
            relation_type=relation_type,
        )

    # ------------------------------------------------------------------------
    # CAS 2 — A inconnue, B explicite
    # ------------------------------------------------------------------------

    def _handle_cas_2(
        self,
        snap_a: _ClaimTemporalSnapshot,
        snap_b: _ClaimTemporalSnapshot,
        relation_type: str,
        evidence_a: str,
        evidence_b: str,
        confidence: float,
        marker_type: str,
        detection_method: str,
        detection_source: str,
        reasoning: str,
    ) -> SupersessionDecision:
        """CAS 2 : A.valid_from = NULL, B.valid_from explicite.

        Si B.valid_from > A.ingested_at → B supersede A (B forcément postérieur intellectuellement).
        Sinon → ambigu (B pourrait dater d'avant A) → :ConflictPending.
        """
        if snap_a.ingested_at is None or snap_b.valid_from is None:
            # Cas dégénéré (ne devrait pas arriver vu Phase A1.4 Gate-B)
            return self._create_conflict_pending(
                snap_a,
                snap_b,
                relation_type,
                "CAS_2",
                confidence,
                reasoning,
                detection_method,
                detection_source,
                conflict_type="contradiction",
            )

        # Comparaison strings ISO datetime — fonctionne car format lexicographiquement ordonné
        if snap_b.valid_from > snap_a.ingested_at:
            # B est forcément postérieur à A (même si A.valid_from inconnu)
            return self._create_supersedes(
                winner=snap_b,
                loser=snap_a,
                evidence_loser=evidence_a,
                evidence_winner=evidence_b,
                confidence=confidence,
                marker_type=marker_type,
                detection_method=detection_method,
                detection_source=detection_source,
                reasoning=reasoning,
                evolution_case="CAS_2",
                relation_type=relation_type,
            )

        # B.valid_from ≤ A.ingested_at : ambigu (B pourrait dater d'avant A)
        return self._create_conflict_pending(
            snap_a,
            snap_b,
            relation_type,
            "CAS_2",
            confidence,
            reasoning,
            detection_method,
            detection_source,
            conflict_type="contradiction",
        )

    # ------------------------------------------------------------------------
    # Écriture Neo4j : :SUPERSEDES
    # ------------------------------------------------------------------------

    def _create_supersedes(
        self,
        winner: _ClaimTemporalSnapshot,
        loser: _ClaimTemporalSnapshot,
        evidence_loser: str,
        evidence_winner: str,
        confidence: float,
        marker_type: str,
        detection_method: str,
        detection_source: str,
        reasoning: str,
        evolution_case: str,
        relation_type: str,
    ) -> SupersessionDecision:
        """Crée la relation `:SUPERSEDES` + setter `invalidated_at` sur le loser.

        Cypher idempotent (MERGE) : si la relation existe déjà, met à jour les props.
        Setter `loser.valid_until = winner.valid_from` (cf §9.5).
        """
        cypher = """
        MATCH (winner:Claim {claim_id: $winner_id, tenant_id: $tid})
        MATCH (loser:Claim {claim_id: $loser_id, tenant_id: $tid})
        // Setter invalidated_at sur loser (idempotent : ne re-écrit pas si déjà invalidé)
        SET loser.invalidated_at = coalesce(loser.invalidated_at, datetime()),
            loser.valid_until = coalesce(loser.valid_until, winner.valid_from),
            loser.invalidated_by = coalesce(loser.invalidated_by, winner.claim_id),
            loser.invalidation_reason = coalesce(
                loser.invalidation_reason,
                $invalidation_reason
            )
        // Créer :SUPERSEDES (MERGE pour idempotence)
        MERGE (winner)-[r:SUPERSEDES]->(loser)
        ON CREATE SET
            r.detected_at = datetime(),
            r.valid_from_relation = winner.valid_from,
            r.confidence = $confidence,
            r.marker_type = $marker_type,
            r.detection_method = $detection_method,
            r.detection_source = $detection_source,
            r.evidence_a = $evidence_loser,
            r.evidence_b = $evidence_winner,
            r.reasoning = $reasoning,
            r.evolution_case = $evolution_case,
            r.from_relation_type = $relation_type
        RETURN loser.invalidated_at AS inv_at, type(r) AS rel_type
        """

        # A2.9 — Cascade `invalidated_relation_at` sur toutes les relations cross-claim
        # attachées au loser (sauf :SUPERSEDES vers/depuis lui-même qui sont gérées par
        # le MERGE ci-dessus). Idempotent : ne réécrit pas si déjà setté.
        # A2.10 : EVOLVES_TO conservé dans le MATCH pour rétro-compat (anciennes relations
        # avant migration) — sera supprimé après audit final post-A2.12.
        cascade_cypher = """
        MATCH (loser:Claim {claim_id: $loser_id, tenant_id: $tid})
        WITH loser, loser.invalidated_at AS inv_at
        WHERE inv_at IS NOT NULL
        MATCH (loser)-[r:SAME_AS|EVOLUTION_OF|CONTRADICTS|REFINES|QUALIFIES|CHAINS_TO|COMPLEMENTS|SPECIALIZES|EVOLVES_TO]-(other:Claim)
        WHERE r.invalidated_relation_at IS NULL
        SET r.invalidated_relation_at = inv_at
        RETURN count(r) AS cascade_count
        """

        try:
            with self.driver.session() as session:
                record = session.run(
                    cypher,
                    winner_id=winner.claim_id,
                    loser_id=loser.claim_id,
                    tid=self.tenant_id,
                    invalidation_reason=f"supersession_by_{winner.claim_id}_via_{relation_type}",
                    confidence=confidence,
                    marker_type=marker_type,
                    detection_method=detection_method,
                    detection_source=detection_source,
                    evidence_loser=evidence_loser,
                    evidence_winner=evidence_winner,
                    reasoning=reasoning,
                    evolution_case=evolution_case,
                    relation_type=relation_type,
                ).single()

                # Cascade dans la même session
                cascade_record = session.run(
                    cascade_cypher,
                    loser_id=loser.claim_id,
                    tid=self.tenant_id,
                ).single()
                # Defensive .get() : permet mocks de test partiels + records absents
                try:
                    cascade_count = cascade_record.get("cascade_count", 0) if cascade_record else 0
                except (AttributeError, TypeError):
                    cascade_count = 0
                if cascade_count > 0:
                    logger.debug(
                        f"[SupersessionApplier] Cascade invalidated_relation_at sur {cascade_count} "
                        f"relations attachées à {loser.claim_id}"
                    )

            return SupersessionDecision(
                action="supersedes",
                invalidated_claim_id=loser.claim_id,
                winner_claim_id=winner.claim_id,
                evolution_case=evolution_case,
                reason=(
                    f"§9.4 {evolution_case}: {winner.claim_id} supersede {loser.claim_id} "
                    f"(via {relation_type})"
                ),
            )

        except Exception as e:
            logger.warning(
                f"[SupersessionApplier] _create_supersedes échec ({winner.claim_id} → {loser.claim_id}): {e}"
            )
            return SupersessionDecision(
                action="no_op",
                evolution_case=evolution_case,
                reason=f"create_supersedes failed: {e}",
            )

    # ------------------------------------------------------------------------
    # Écriture Neo4j : :ConflictPending
    # ------------------------------------------------------------------------

    def _create_conflict_pending(
        self,
        snap_a: _ClaimTemporalSnapshot,
        snap_b: _ClaimTemporalSnapshot,
        relation_type: str,
        case: str,
        confidence: float,
        reasoning: str,
        detection_method: str,
        detection_source: str,
        conflict_type: str = "contradiction",
        evolution_case_override: Optional[str] = None,
    ) -> SupersessionDecision:
        """Crée un node `:ConflictPending` reliant A et B via `:INVOLVES`.

        Schéma (cf ADR_RELATIONS_CLAIM_CLAIM §2.6).
        """
        conflict_id = str(uuid.uuid4())

        cypher = """
        MATCH (a:Claim {claim_id: $a_id, tenant_id: $tid})
        MATCH (b:Claim {claim_id: $b_id, tenant_id: $tid})
        CREATE (cp:ConflictPending {
            tenant_id: $tid,
            conflict_id: $conflict_id,
            created_at: datetime(),
            resolution_status: 'unresolved',
            conflict_type: $conflict_type,
            relation_classified: $relation_type,
            confidence: $confidence,
            detection_method: $detection_method,
            detection_source: $detection_source,
            evolution_case: $evolution_case,
            reasoning: $reasoning
        })
        CREATE (cp)-[:INVOLVES {role: 'A'}]->(a)
        CREATE (cp)-[:INVOLVES {role: 'B'}]->(b)
        RETURN cp.conflict_id AS conflict_id
        """

        try:
            with self.driver.session() as session:
                record = session.run(
                    cypher,
                    a_id=snap_a.claim_id,
                    b_id=snap_b.claim_id,
                    tid=self.tenant_id,
                    conflict_id=conflict_id,
                    conflict_type=conflict_type,
                    relation_type=relation_type,
                    confidence=confidence,
                    detection_method=detection_method,
                    detection_source=detection_source,
                    evolution_case=evolution_case_override or case,
                    reasoning=reasoning,
                ).single()

            return SupersessionDecision(
                action="conflict_pending",
                evolution_case=evolution_case_override or case,
                conflict_pending_id=conflict_id,
                reason=(
                    f"§9.4 {case} ambigu sur {relation_type} : ConflictPending créé "
                    f"({snap_a.claim_id} vs {snap_b.claim_id})"
                ),
            )

        except Exception as e:
            logger.warning(
                f"[SupersessionApplier] _create_conflict_pending échec ({snap_a.claim_id}, {snap_b.claim_id}): {e}"
            )
            return SupersessionDecision(
                action="no_op",
                evolution_case=evolution_case_override or case,
                reason=f"create_conflict_pending failed: {e}",
            )

    # ------------------------------------------------------------------------
    # Lecture snapshot temporel
    # ------------------------------------------------------------------------

    def _load_temporal_snapshot(self, claim_id: str) -> Optional[_ClaimTemporalSnapshot]:
        """Lit les 4 timestamps + marker d'un claim depuis Neo4j.

        Retourne None si le claim n'existe pas.
        """
        cypher = """
        MATCH (c:Claim {claim_id: $cid, tenant_id: $tid})
        RETURN
            c.claim_id AS claim_id,
            toString(c.valid_from) AS valid_from,
            c.valid_from_marker AS valid_from_marker,
            toString(c.ingested_at) AS ingested_at,
            toString(c.invalidated_at) AS invalidated_at
        """
        with self.driver.session() as session:
            record = session.run(cypher, cid=claim_id, tid=self.tenant_id).single()
            if record is None:
                return None
            return _ClaimTemporalSnapshot(
                claim_id=record["claim_id"],
                valid_from=record["valid_from"],
                valid_from_marker=record["valid_from_marker"],
                ingested_at=record["ingested_at"],
                invalidated_at=record["invalidated_at"],
            )
