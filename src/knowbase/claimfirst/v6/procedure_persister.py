"""V6-J1 — Persistance Neo4j pour Procedure + ProcedureStep.

Module additif au pipeline ClaimFirst : il MERGE les Procedure et
ProcedureStep sans toucher aux Claims existants.

Idempotence : utilise MERGE sur les clés uniques (procedure_id pour
Procedure, "{procedure_id}#{step_number}" pour ProcedureStep). Lancer
l'extraction deux fois sur les mêmes sections recréera les mêmes
procedure_id (générés par UUID4 dans le schéma Pydantic) → produit
des doublons. La gestion d'idempotence côté ré-extraction se fait
en amont (purge des procedures du doc avant ré-extraction).

Relations créées :
- (:Procedure)-[:IN_DOCUMENT]->(:Document)
- (:Procedure)-[:HAS_STEP {order}]->(:ProcedureStep)
- (:Procedure)-[:EVIDENCE_IN]->(:V5Section)  # si la section existe déjà
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from knowbase.runtime_v6.schemas import Procedure

logger = logging.getLogger(__name__)


class ProcedurePersister:
    """Persiste les Procedure V6-J1 dans Neo4j.

    Usage :
        persister = ProcedurePersister(driver, tenant_id="default")
        persister.persist_one(doc_id, section_id, procedure)
        # ou
        persister.persist_batch(doc_id, [(section_id, proc), ...])
        stats = persister.stats
    """

    def __init__(self, driver, tenant_id: str = "default"):
        self.driver = driver
        self.tenant_id = tenant_id
        self.stats = {
            "procedures_persisted": 0,
            "steps_persisted": 0,
            "evidence_links_created": 0,
            "doc_links_created": 0,
            "errors": 0,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def persist_one(
        self,
        doc_id: str,
        section_id: str,
        procedure: Procedure,
        v5_section_label: str = "V5Section",
    ) -> None:
        """Persiste une seule Procedure et ses steps.

        v5_section_label : nom du label utilisé pour les sections V5.
        Le persister tente de lier EVIDENCE_IN ; si le label/node n'existe
        pas, le MATCH-MERGE est no-op (pas d'erreur).
        """
        try:
            with self.driver.session() as session:
                # 1. Document (au cas où il n'existerait pas — fallback)
                session.run(
                    "MERGE (d:Document {doc_id: $doc_id}) "
                    "ON CREATE SET d.tenant_id = $tenant_id, d.created_at = $now",
                    doc_id=doc_id,
                    tenant_id=self.tenant_id,
                    now=datetime.utcnow().isoformat(),
                )

                # 2. Procedure
                proc_props = {
                    "procedure_id": procedure.procedure_id,
                    "tenant_id": self.tenant_id,
                    "doc_id": doc_id,
                    "name": procedure.name,
                    "goal": procedure.goal,
                    "prerequisites": list(procedure.prerequisites or []),
                    "evidence_section_id": procedure.evidence_section_id or section_id,
                    "created_at": datetime.utcnow().isoformat(),
                }
                session.run(
                    """
                    MERGE (p:Procedure {procedure_id: $procedure_id})
                    SET p += $props
                    WITH p
                    MATCH (d:Document {doc_id: $doc_id})
                    MERGE (p)-[:IN_DOCUMENT]->(d)
                    """,
                    procedure_id=procedure.procedure_id,
                    doc_id=doc_id,
                    props=proc_props,
                )
                self.stats["procedures_persisted"] += 1
                self.stats["doc_links_created"] += 1

                # 3. Steps (UNWIND batch)
                steps_payload = [
                    {
                        "step_key": f"{procedure.procedure_id}#{s.step_number}",
                        "procedure_id": procedure.procedure_id,
                        "tenant_id": self.tenant_id,
                        "step_number": s.step_number,
                        "action": s.action,
                        "notes": s.notes,
                    }
                    for s in procedure.steps
                ]
                if steps_payload:
                    session.run(
                        """
                        UNWIND $steps AS step
                        MERGE (s:ProcedureStep {step_key: step.step_key})
                        SET s.procedure_id = step.procedure_id,
                            s.tenant_id    = step.tenant_id,
                            s.step_number  = step.step_number,
                            s.action       = step.action,
                            s.notes        = step.notes
                        WITH s, step
                        MATCH (p:Procedure {procedure_id: step.procedure_id})
                        MERGE (p)-[r:HAS_STEP]->(s)
                        SET r.order = step.step_number
                        """,
                        steps=steps_payload,
                    )
                    self.stats["steps_persisted"] += len(steps_payload)

                # 4. Evidence link vers V5Section (best-effort, no-op si absent)
                if section_id:
                    res = session.run(
                        f"""
                        MATCH (p:Procedure {{procedure_id: $procedure_id}})
                        OPTIONAL MATCH (sec:{v5_section_label} {{section_id: $section_id}})
                        WITH p, sec
                        WHERE sec IS NOT NULL
                        MERGE (p)-[:EVIDENCE_IN]->(sec)
                        RETURN count(sec) AS linked
                        """,
                        procedure_id=procedure.procedure_id,
                        section_id=section_id,
                    )
                    rec = res.single()
                    if rec and rec.get("linked", 0):
                        self.stats["evidence_links_created"] += int(rec["linked"])

        except Exception as exc:
            logger.error(
                "[V6-J1] persist_one failed for procedure %s (section %s): %s",
                procedure.procedure_id, section_id, exc,
            )
            self.stats["errors"] += 1

    def persist_batch(
        self,
        doc_id: str,
        items: list[tuple[str, Procedure]],
        v5_section_label: str = "V5Section",
    ) -> None:
        """Persiste une liste de (section_id, Procedure)."""
        for section_id, proc in items:
            self.persist_one(doc_id, section_id, proc, v5_section_label=v5_section_label)

    # ── Phase B (P1.3) — liens Claim ↔ Procedure ────────────────────────────────

    def persist_claim_links(
        self,
        step_of_links: list[tuple[str, str, int]],
        outcome_links: list[tuple[str, str]],
    ) -> dict[str, int]:
        """Persiste les relations claim-centric Phase B (ADR §3.3).

        Args:
            step_of_links : (claim_id, procedure_id, order) — (:Claim)-[:STEP_OF]->(:Procedure)
            outcome_links : (procedure_id, claim_id) — (:Procedure)-[:HAS_OUTCOME]->(:Claim)

        Les relations PREREQUISITE_OF (Claim→Claim) sont persistées par le flux
        relations ClaimFirst standard (générique), pas ici.
        """
        counts = {"step_of": 0, "has_outcome": 0, "errors": 0}
        try:
            with self.driver.session() as session:
                if step_of_links:
                    payload = [
                        {"claim_id": cid, "procedure_id": pid, "order": order}
                        for cid, pid, order in step_of_links
                    ]
                    res = session.run(
                        """
                        UNWIND $links AS link
                        MATCH (c:Claim {claim_id: link.claim_id})
                        MATCH (p:Procedure {procedure_id: link.procedure_id})
                        MERGE (c)-[r:STEP_OF]->(p)
                        SET r.order = link.order
                        RETURN count(r) AS n
                        """,
                        links=payload,
                    )
                    rec = res.single()
                    counts["step_of"] = int(rec["n"]) if rec else 0

                if outcome_links:
                    payload = [
                        {"procedure_id": pid, "claim_id": cid}
                        for pid, cid in outcome_links
                    ]
                    res = session.run(
                        """
                        UNWIND $links AS link
                        MATCH (p:Procedure {procedure_id: link.procedure_id})
                        MATCH (c:Claim {claim_id: link.claim_id})
                        MERGE (p)-[r:HAS_OUTCOME]->(c)
                        RETURN count(r) AS n
                        """,
                        links=payload,
                    )
                    rec = res.single()
                    counts["has_outcome"] = int(rec["n"]) if rec else 0
        except Exception as exc:
            logger.error("[V6-J1] persist_claim_links failed: %s", exc)
            counts["errors"] += 1
            self.stats["errors"] += 1

        self.stats.setdefault("step_of_links", 0)
        self.stats.setdefault("outcome_links", 0)
        self.stats["step_of_links"] += counts["step_of"]
        self.stats["outcome_links"] += counts["has_outcome"]
        return counts

    # ── Maintenance utilities ────────────────────────────────────────────────

    def delete_procedures_for_doc(
        self, doc_id: str, tenant_id: Optional[str] = None
    ) -> int:
        """Purge toutes les Procedure (+ leurs Steps) d'un doc.

        Utile avant ré-extraction pour éviter les doublons (procedure_id
        régénéré à chaque run par Pydantic UUID4).

        Returns: nombre de procedures supprimées.
        """
        tid = tenant_id or self.tenant_id
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (p:Procedure {doc_id: $doc_id, tenant_id: $tenant_id})
                OPTIONAL MATCH (p)-[:HAS_STEP]->(s:ProcedureStep)
                WITH p, collect(s) AS steps
                FOREACH (s IN steps | DETACH DELETE s)
                WITH p
                DETACH DELETE p
                RETURN count(p) AS deleted
                """,
                doc_id=doc_id,
                tenant_id=tid,
            )
            rec = result.single()
            n = int(rec["deleted"]) if rec else 0
            logger.info(
                "[V6-J1] deleted %d procedures for doc %s (tenant=%s)",
                n, doc_id, tid,
            )
            return n
