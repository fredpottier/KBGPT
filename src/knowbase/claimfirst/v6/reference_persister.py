"""V6-J2 — Persistance Neo4j pour Reference typée.

Module additif au pipeline ClaimFirst : MERGE les Reference du schéma
V6 sans toucher aux Claims / Procedures existants.

Relations créées :
- (:Reference)-[:IN_DOCUMENT]->(:Document)
- (:Reference)-[:EVIDENCE_IN]->(:V5Section)         # si la section existe
- (:Reference)-[:POINTS_TO]->(...)                  # si resolved_target connu
                                                     (post-extraction, non livré J2)

Idempotence par MERGE sur reference_id (UUID4). Pour ré-extraire un doc
proprement : utiliser `delete_references_for_doc(doc_id)` au préalable.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from knowbase.runtime_v6.schemas import Reference

logger = logging.getLogger(__name__)


class ReferencePersister:
    """Persiste les Reference V6-J2 dans Neo4j."""

    def __init__(self, driver, tenant_id: str = "default"):
        self.driver = driver
        self.tenant_id = tenant_id
        self.stats = {
            "references_persisted": 0,
            "evidence_links_created": 0,
            "doc_links_created": 0,
            "errors": 0,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def persist_one(
        self,
        doc_id: str,
        section_id: str,
        reference: Reference,
        v5_section_label: str = "V5Section",
    ) -> None:
        """Persiste une seule Reference."""
        try:
            with self.driver.session() as session:
                # 1. Document fallback
                session.run(
                    "MERGE (d:Document {doc_id: $doc_id}) "
                    "ON CREATE SET d.tenant_id = $tenant_id, d.created_at = $now",
                    doc_id=doc_id,
                    tenant_id=self.tenant_id,
                    now=datetime.utcnow().isoformat(),
                )

                # 2. Reference + IN_DOCUMENT
                props = {
                    "reference_id": reference.reference_id,
                    "tenant_id": self.tenant_id,
                    "doc_id": doc_id,
                    "reference_text": reference.reference_text,
                    "target_kind": reference.target_kind,
                    "resolved_target": reference.resolved_target,
                    "evidence_section_id": reference.evidence_section_id or section_id,
                    "created_at": datetime.utcnow().isoformat(),
                }
                session.run(
                    """
                    MERGE (r:Reference {reference_id: $reference_id})
                    SET r += $props
                    WITH r
                    MATCH (d:Document {doc_id: $doc_id})
                    MERGE (r)-[:IN_DOCUMENT]->(d)
                    """,
                    reference_id=reference.reference_id,
                    doc_id=doc_id,
                    props=props,
                )
                self.stats["references_persisted"] += 1
                self.stats["doc_links_created"] += 1

                # 3. Evidence link (best-effort)
                if section_id:
                    res = session.run(
                        f"""
                        MATCH (r:Reference {{reference_id: $reference_id}})
                        OPTIONAL MATCH (sec:{v5_section_label} {{section_id: $section_id}})
                        WITH r, sec WHERE sec IS NOT NULL
                        MERGE (r)-[:EVIDENCE_IN]->(sec)
                        RETURN count(sec) AS linked
                        """,
                        reference_id=reference.reference_id,
                        section_id=section_id,
                    )
                    rec = res.single()
                    if rec and rec.get("linked", 0):
                        self.stats["evidence_links_created"] += int(rec["linked"])

        except Exception as exc:
            logger.error(
                "[V6-J2] persist_one failed for reference %s (section %s): %s",
                reference.reference_id, section_id, exc,
            )
            self.stats["errors"] += 1

    def persist_batch(
        self,
        doc_id: str,
        items: list[tuple[str, Reference]],
        v5_section_label: str = "V5Section",
    ) -> None:
        for section_id, ref in items:
            self.persist_one(doc_id, section_id, ref, v5_section_label=v5_section_label)

    # ── Maintenance utilities ────────────────────────────────────────────────

    def delete_references_for_doc(
        self, doc_id: str, tenant_id: Optional[str] = None
    ) -> int:
        """Purge toutes les Reference d'un doc (utile avant ré-extraction)."""
        tid = tenant_id or self.tenant_id
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (r:Reference {doc_id: $doc_id, tenant_id: $tenant_id})
                DETACH DELETE r
                RETURN count(r) AS deleted
                """,
                doc_id=doc_id,
                tenant_id=tid,
            )
            rec = result.single()
            n = int(rec["deleted"]) if rec else 0
            logger.info(
                "[V6-J2] deleted %d references for doc %s (tenant=%s)",
                n, doc_id, tid,
            )
            return n
