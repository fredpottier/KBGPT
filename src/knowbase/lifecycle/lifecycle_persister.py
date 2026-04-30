"""
Persister Neo4j pour LIFECYCLE_RELATION Doc→Doc V2-S1 strict.

Conformément à ADR_LIFECYCLE_VS_LOGICAL_RELATIONS (version stricte) :
- Schéma additif (n'écrase rien)
- Aucun champ `*_score` (les scores sont runtime, pas KG)
- evidence_quote OBLIGATOIRE pour audit
- evidence_claim_ids peuplé par les claims du source contenant la quote (preuve traçable)
"""
from __future__ import annotations

import logging
from datetime import datetime

from neo4j import Driver

from knowbase.lifecycle.models import ValidatedLifecycleRelation

logger = logging.getLogger(__name__)


class LifecyclePersister:
    """Persiste les ValidatedLifecycleRelation dans Neo4j.

    Idempotent : MERGE sur (source, target, type) — re-run safe.
    """

    def __init__(self, driver: Driver, tenant_id: str = "default") -> None:
        self.driver = driver
        self.tenant_id = tenant_id

    def persist(self, validated: ValidatedLifecycleRelation) -> dict:
        """Persiste une relation validée. Renvoie {created: bool, source: ..., target: ...}.

        Étapes :
        1. Trouve les claim_ids du source contenant l'evidence_quote (pour evidence_claim_ids)
        2. MERGE LIFECYCLE_RELATION avec props strictes
        """
        evidence_claim_ids = self._find_claims_with_quote(
            validated.source_doc_id, validated.evidence_quote
        )

        cypher = """
        MATCH (src:DocumentContext {doc_id: $source_doc_id, tenant_id: $tenant_id})
        MATCH (tgt:DocumentContext {doc_id: $target_doc_id, tenant_id: $tenant_id})
        MERGE (src)-[r:LIFECYCLE_RELATION {type: $type}]->(tgt)
        ON CREATE SET
            r.confidence = $confidence,
            r.evidence_quote = $evidence_quote,
            r.evidence_claim_ids = $evidence_claim_ids,
            r.reasoning = $reasoning,
            r.derivation_path = $derivation_path,
            r.model_id = $model_id,
            r.extracted_at = $extracted_at,
            r.tenant_id = $tenant_id,
            r._created = true
        ON MATCH SET
            r.confidence = $confidence,
            r.evidence_quote = $evidence_quote,
            r.evidence_claim_ids = $evidence_claim_ids,
            r.reasoning = $reasoning,
            r.derivation_path = $derivation_path,
            r.model_id = $model_id,
            r.extracted_at = $extracted_at,
            r._created = false
        WITH r, r._created AS created
        REMOVE r._created
        RETURN created
        """
        params = {
            "source_doc_id": validated.source_doc_id,
            "target_doc_id": validated.target_doc_id,
            "tenant_id": self.tenant_id,
            "type": validated.type.value,
            "confidence": validated.confidence,
            "evidence_quote": validated.evidence_quote,
            "evidence_claim_ids": evidence_claim_ids,
            "reasoning": validated.reasoning,
            "derivation_path": validated.derivation_path,
            "model_id": validated.model_id,
            "extracted_at": datetime.utcnow().isoformat() + "Z",
        }
        with self.driver.session() as session:
            row = session.run(cypher, **params).single()
        created = bool(row and row["created"])
        logger.info(
            "LIFECYCLE_RELATION %s: %s --[%s]--> %s (evidence_claims=%d)",
            "CREATED" if created else "UPDATED",
            validated.source_doc_id,
            validated.type.value,
            validated.target_doc_id,
            len(evidence_claim_ids),
        )
        return {
            "created": created,
            "source_doc_id": validated.source_doc_id,
            "target_doc_id": validated.target_doc_id,
            "type": validated.type.value,
            "evidence_claim_ids": evidence_claim_ids,
        }

    def _find_claims_with_quote(self, source_doc_id: str, quote: str) -> list[str]:
        """Cherche les claims du source dont le passage_text contient la quote.

        Utilisé pour peupler evidence_claim_ids (preuve traçable au runtime).
        Si aucun claim ne matche (cas où la quote est dans un préambule non-claimifié),
        on stocke une liste vide — ce n'est pas un échec de validation.
        """
        # Match insensible à la casse + tolérant aux whitespaces multiples (LIKE-like)
        # Extrait les 60 premiers chars de la quote pour matching robuste (full quote
        # peut être trop long et contenir des artefacts d'extraction PDF)
        quote_prefix = quote.strip()[:60].lower()
        if len(quote_prefix) < 10:
            return []

        cypher = """
        MATCH (c:Claim)
        WHERE c.tenant_id = $tenant_id AND c.doc_id = $doc_id
          AND toLower(coalesce(c.passage_text, c.text, '')) CONTAINS $quote_prefix
        RETURN c.claim_id AS claim_id
        LIMIT 5
        """
        with self.driver.session() as session:
            rows = session.run(
                cypher,
                tenant_id=self.tenant_id,
                doc_id=source_doc_id,
                quote_prefix=quote_prefix,
            ).data()
        return [r["claim_id"] for r in rows if r.get("claim_id")]


def ensure_lifecycle_indexes(driver: Driver) -> None:
    """Crée les index nécessaires pour LIFECYCLE_RELATION (idempotent)."""
    statements = [
        "CREATE INDEX lifecycle_relation_type IF NOT EXISTS "
        "FOR ()-[r:LIFECYCLE_RELATION]-() ON (r.type)",
        "CREATE INDEX lifecycle_relation_confidence IF NOT EXISTS "
        "FOR ()-[r:LIFECYCLE_RELATION]-() ON (r.confidence)",
        "CREATE INDEX lifecycle_relation_tenant IF NOT EXISTS "
        "FOR ()-[r:LIFECYCLE_RELATION]-() ON (r.tenant_id)",
    ]
    with driver.session() as session:
        for stmt in statements:
            session.run(stmt)
            logger.info("Index ensured: %s", stmt.split("FOR")[0].strip())
