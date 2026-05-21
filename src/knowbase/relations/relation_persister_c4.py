"""
C4 RelationPersister — Persistance des relations adjudiquees dans Neo4j.

Stage 3 du pipeline C4 Relations Evidence-First.

Chaque relation est persistee comme arete typee (CONTRADICTS, QUALIFIES, REFINES)
entre deux Claim nodes, avec les proprietes evidence obligatoires (INV-PROOF-01).

Phase A2 (2026-05-21) : après chaque persistance d'une relation `CONTRADICTS`
ou `EVOLVES_TO`, on appelle `SupersessionApplier` qui applique la règle bitemporelle
§9.4 CAS 1-4 (ADR_BITEMPOREL §9 + ADR_RELATIONS_CLAIM_CLAIM §2.4). Selon le résultat
(supersedes / conflict_pending / no_op), un `:SUPERSEDES` est créé et le claim loser
est invalidé, OU un `:ConflictPending` est créé pour exposition runtime.

Usage :
    from knowbase.relations.relation_persister_c4 import RelationPersisterC4
    persister = RelationPersisterC4(neo4j_driver)
    stats = persister.persist_batch(adjudication_results)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from knowbase.relations.nli_adjudicator import AdjudicationResult
from knowbase.relations.supersession_applier import SupersessionApplier

logger = logging.getLogger(__name__)


# Types de relation qui déclenchent l'application de la règle §9.4 supersession
# (les autres types — REFINES, QUALIFIES, SAME_AS, COMPLEMENTS, SPECIALIZES — ne
# déclenchent pas d'invalidation par construction, cf ADR_RELATIONS_CLAIM_CLAIM §2.1)
# A2.10 : EVOLVES_TO renommé EVOLUTION_OF. On garde EVOLVES_TO dans la liste pour
# accepter les anciens AdjudicationResult (rétro-compat lecture), mais les
# nouvelles persistances utilisent EVOLUTION_OF.
_SUPERSESSION_TRIGGERING_RELATIONS = {"CONTRADICTS", "EVOLUTION_OF", "EVOLVES_TO"}


@dataclass
class PersistenceStats:
    """Statistiques de persistance."""
    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    # A2.8 : compteurs de supersession appliquée
    supersedes_created: int = 0
    conflict_pending_created: int = 0
    supersession_skipped: int = 0  # no_op (relation déjà invalidée, type non handled, etc.)


# Relations symétriques (A ↔ B) vs directionnelles (B → A) selon ADR §2.1
# La règle de défaut `valid_from_relation` diffère (cf ADR §2.3) :
#   - symétriques : max(A.valid_from, B.valid_from), NULL si l'un est NULL
#   - directionnelles : B.valid_from (source de la relation) — strictement
# A2.10 : EVOLVES_TO supprimé, harmonisé sur EVOLUTION_OF (cf ADR §2.2)
_SYMMETRIC_RELATIONS = {"SAME_AS", "CONTRADICTS"}
_DIRECTIONAL_RELATIONS = {"EVOLUTION_OF", "SUPERSEDES", "REFINES", "QUALIFIES", "COMPLEMENTS", "SPECIALIZES"}


def _make_merge_cypher(rel_type: str) -> str:
    """Genere le Cypher MERGE pour un type de relation.

    Phase A2.9 (2026-05-21) : ajoute les 3 timestamps systématiques (`detected_at`,
    `valid_from_relation`, `invalidated_relation_at`) selon la règle §2.3 ADR_RELATIONS_CLAIM_CLAIM :
    - symétriques : `valid_from_relation = max(A.valid_from, B.valid_from)`, NULL si l'un NULL
    - directionnelles : `valid_from_relation = B.valid_from` (c2.valid_from car c1→c2 dans la convention persister)

    NOTE convention persister : ici `c1` est la SOURCE de l'arête (winner), `c2` la CIBLE (loser).
    Cf ADR §2.1 direction canonique "nouveau vers ancien".
    """
    is_symmetric = rel_type in _SYMMETRIC_RELATIONS

    if is_symmetric:
        valid_from_expr = """CASE
                WHEN c1.valid_from IS NOT NULL AND c2.valid_from IS NOT NULL THEN
                    CASE WHEN c1.valid_from > c2.valid_from THEN c1.valid_from ELSE c2.valid_from END
                ELSE NULL
            END"""
    else:
        # Directionnelle : c1 = source (winner / plus récent / plus précis)
        valid_from_expr = "c1.valid_from"

    return f"""
        MATCH (c1:Claim {{claim_id: $c1id, tenant_id: $tid}})
        MATCH (c2:Claim {{claim_id: $c2id, tenant_id: $tid}})
        MERGE (c1)-[r:{rel_type}]->(c2)
        ON CREATE SET
            r.confidence = $conf,
            r.method = $method,
            r.evidence_a = $ev_a,
            r.evidence_b = $ev_b,
            r.reasoning = $reasoning,
            r.doc_a_title = $doc_a,
            r.doc_b_title = $doc_b,
            r.pivot_entity = $pivot,
            r.marker_type = coalesce($marker_type, 'inferred'),
            r.created_at = datetime(),
            r.detected_at = datetime(),
            r.valid_from_relation = {valid_from_expr},
            r.invalidated_relation_at = coalesce(c1.invalidated_at, c2.invalidated_at)
        ON MATCH SET
            r.confidence = CASE WHEN $conf > r.confidence THEN $conf ELSE r.confidence END,
            r.method = CASE WHEN $conf > r.confidence THEN $method ELSE r.method END,
            r.evidence_a = CASE WHEN $conf > r.confidence THEN $ev_a ELSE r.evidence_a END,
            r.evidence_b = CASE WHEN $conf > r.confidence THEN $ev_b ELSE r.evidence_b END,
            r.reasoning = CASE WHEN $conf > r.confidence THEN $reasoning ELSE r.reasoning END,
            r.pivot_entity = CASE WHEN $pivot IS NOT NULL THEN $pivot ELSE r.pivot_entity END,
            r.marker_type = CASE WHEN $marker_type IS NOT NULL THEN $marker_type ELSE r.marker_type END,
            r.invalidated_relation_at = coalesce(r.invalidated_relation_at, c1.invalidated_at, c2.invalidated_at),
            r.updated_at = datetime()
        RETURN type(r) AS rel_type
    """


# Cypher par type de relation — MERGE pour upsert
# A2.10 : EVOLVES_TO renommé EVOLUTION_OF (cf ADR_RELATIONS_CLAIM_CLAIM §2.2 harmonisation)
CYPHER_BY_TYPE = {
    "CONTRADICTS": _make_merge_cypher("CONTRADICTS"),
    "QUALIFIES": _make_merge_cypher("QUALIFIES"),
    "REFINES": _make_merge_cypher("REFINES"),
    "COMPLEMENTS": _make_merge_cypher("COMPLEMENTS"),
    "EVOLUTION_OF": _make_merge_cypher("EVOLUTION_OF"),
    "SPECIALIZES": _make_merge_cypher("SPECIALIZES"),
}


class RelationPersisterC4:
    """Persiste les relations adjudiquees dans Neo4j avec preuves verbatim."""

    def __init__(self, neo4j_driver, tenant_id: str = "default", apply_supersession: bool = True):
        """Args :
            neo4j_driver : driver Neo4j
            tenant_id : tenant
            apply_supersession : si True (défaut Phase A2), applique la règle §9.4
                après chaque persistance de CONTRADICTS / EVOLVES_TO. Mettre False
                pour désactiver (tests, migration, etc.).
        """
        self.driver = neo4j_driver
        self.tenant_id = tenant_id
        self.apply_supersession = apply_supersession
        self._supersession_applier = (
            SupersessionApplier(neo4j_driver, tenant_id=tenant_id) if apply_supersession else None
        )

    def persist_batch(
        self,
        results: list,
        on_progress: callable = None,
    ) -> PersistenceStats:
        """Persiste un batch de relations adjudiquees (C4 ou C6).

        Phase A2.8 : après persistance d'une relation CONTRADICTS ou EVOLVES_TO,
        applique la règle §9.4 via SupersessionApplier. Décision possible :
        - supersedes      : :SUPERSEDES créé + claim loser invalidé
        - conflict_pending: :ConflictPending node créé (ambigu §9.4 CAS 3/4)
        - no_op           : relation conservée telle quelle (déjà invalidée, etc.)

        Args:
            results: Liste de AdjudicationResult ou PivotAdjudicationResult
            on_progress: Callback(done, total) pour progression

        Returns:
            PersistenceStats avec compteurs (incl. supersedes_created, conflict_pending_created)
        """
        start = time.time()
        stats = PersistenceStats(total=len(results))

        for i, result in enumerate(results):
            if on_progress and (i + 1) % 10 == 0:
                on_progress(i + 1, len(results))

            # A2.10 — rétro-compat : remap EVOLVES_TO → EVOLUTION_OF côté persistance
            # (les anciens AdjudicationResult ou pivot adjudicators peuvent encore retourner
            # relation='EVOLVES_TO' ; on les route vers le Cypher EVOLUTION_OF)
            normalized_relation = "EVOLUTION_OF" if result.relation == "EVOLVES_TO" else result.relation
            cypher = CYPHER_BY_TYPE.get(normalized_relation)
            if not cypher:
                stats.skipped += 1
                continue

            # 1) Persistance Cypher classique (session courte, idempotent MERGE)
            # A2.9 : marker_type calculé pour la relation persistée (cohérent avec
            # le marker_type qu'on passera à SupersessionApplier ci-dessous)
            persist_marker_type = "inferred" if result.confidence >= 0.85 else "prudence"
            try:
                with self.driver.session() as session:
                    session.run(
                        cypher,
                        c1id=result.claim_a_id,
                        c2id=result.claim_b_id,
                        tid=self.tenant_id,
                        conf=result.confidence,
                        method=result.detection_method,
                        ev_a=result.evidence_a,
                        ev_b=result.evidence_b,
                        reasoning=result.reasoning,
                        doc_a=result.doc_a_title,
                        doc_b=result.doc_b_title,
                        pivot=getattr(result, 'pivot_entity', ''),
                        marker_type=persist_marker_type,
                    ).single()

                stats.created += 1

            except Exception as e:
                stats.errors += 1
                logger.debug(f"[C4:PERSIST] Failed for {result.claim_a_id}: {e}")
                continue  # ne pas appliquer supersession si la persistance a échoué

            # 2) A2.8 — Application règle §9.4 supersession (uniquement pour CONTRADICTS / EVOLVES_TO)
            if not self.apply_supersession or self._supersession_applier is None:
                continue
            if result.relation not in _SUPERSESSION_TRIGGERING_RELATIONS:
                continue

            try:
                # Marker_type : on prend confidence comme heuristique de seuil
                # (cf ADR §2.1 — explicit/inferred/prudence selon confidence)
                if result.confidence >= 0.85:
                    marker_type = "inferred"  # 'explicit' nécessite détection de marker linguistique, pour A2.10
                else:
                    marker_type = "prudence"

                # Mappage relation_type pour applier — A2.10 : EVOLVES_TO rétro-compat
                # (les anciens AdjudicationResult peuvent encore avoir relation="EVOLVES_TO" ;
                # la persistance Cypher passe par CYPHER_BY_TYPE qui n'a plus EVOLVES_TO, donc
                # il faut aussi remapper en amont — voir patch ci-dessous ON CREATE)
                applier_relation_type = "EVOLUTION_OF" if result.relation == "EVOLVES_TO" else result.relation

                decision = self._supersession_applier.apply(
                    claim_a_id=result.claim_a_id,
                    claim_b_id=result.claim_b_id,
                    relation_type=applier_relation_type,
                    evidence_a=result.evidence_a,
                    evidence_b=result.evidence_b,
                    confidence=result.confidence,
                    marker_type=marker_type,
                    detection_method=result.detection_method,
                    detection_source="c4_relations",
                    reasoning=result.reasoning,
                )

                if decision.action == "supersedes":
                    stats.supersedes_created += 1
                    logger.debug(
                        f"[C4:SUPERSESSION] {decision.winner_claim_id} supersede "
                        f"{decision.invalidated_claim_id} ({decision.evolution_case})"
                    )
                elif decision.action == "conflict_pending":
                    stats.conflict_pending_created += 1
                    logger.debug(
                        f"[C4:CONFLICT_PENDING] {result.claim_a_id} vs {result.claim_b_id} "
                        f"({decision.evolution_case}): {decision.conflict_pending_id}"
                    )
                else:
                    stats.supersession_skipped += 1

            except Exception as e:
                logger.warning(
                    f"[C4:SUPERSESSION] Apply échoué pour {result.claim_a_id} vs {result.claim_b_id}: {e}"
                )
                stats.supersession_skipped += 1

        duration = time.time() - start
        logger.info(
            f"[C4:PERSIST] Persisted {stats.created} new + {stats.updated} updated "
            f"({stats.errors} errors, {stats.skipped} skipped) in {duration:.1f}s "
            f"| supersession: {stats.supersedes_created} supersedes, "
            f"{stats.conflict_pending_created} conflict_pending, "
            f"{stats.supersession_skipped} skipped"
        )

        return stats

    def get_relation_counts(self) -> dict[str, int]:
        """Retourne le nombre de relations par type."""
        query = """
        MATCH (a:Claim {tenant_id: $tid})-[r:CONTRADICTS|QUALIFIES|REFINES|COMPLEMENTS|EVOLVES_TO|SPECIALIZES]->(b:Claim)
        RETURN type(r) AS rel_type, count(r) AS cnt
        """
        with self.driver.session() as session:
            result = session.run(query, tid=self.tenant_id)
            counts = {r["rel_type"]: r["cnt"] for r in result}

        counts["total"] = sum(counts.values())
        return counts

    def get_c4_relations(self) -> list[dict[str, Any]]:
        """Retourne les relations creees par C4 (method=embedding_nli)."""
        query = """
        MATCH (a:Claim {tenant_id: $tid})-[r:CONTRADICTS|QUALIFIES|REFINES]->(b:Claim)
        WHERE r.method = 'embedding_nli'
        RETURN a.claim_id AS a_id, a.text AS a_text,
               type(r) AS rel_type, r.confidence AS conf,
               r.evidence_a AS ev_a, r.evidence_b AS ev_b,
               r.reasoning AS reasoning,
               b.claim_id AS b_id, b.text AS b_text,
               r.doc_a_title AS doc_a, r.doc_b_title AS doc_b
        ORDER BY r.confidence DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tid=self.tenant_id)
            return [dict(r) for r in result]
