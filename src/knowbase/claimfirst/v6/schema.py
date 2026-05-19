"""V6-J1 — Schéma Neo4j additif pour Procedure / ProcedureStep.

Ce module définit les contraintes et indexes Neo4j pour les nouveaux
labels V6, SANS toucher au schéma ClaimFirst existant. Il peut être
appliqué de manière idempotente (`CREATE ... IF NOT EXISTS`).

Modèle de graphe ajouté :

    (:Procedure {procedure_id, tenant_id, name, goal, doc_id})
        -[:HAS_STEP {order}]-> (:ProcedureStep {procedure_id, step_number,
                                                action, notes, tenant_id})
        -[:EVIDENCE_IN]-> (:V5Section {section_id})       # si V5 schéma actif
        -[:IN_DOCUMENT]-> (:Document {doc_id})           # shortcut pour query

Le label :ProcedureStep utilise une clé composite (procedure_id,
step_number) pour permettre la coexistence de plusieurs procedures.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ─── Constraints (IF NOT EXISTS — idempotent) ─────────────────────────────────

_CONSTRAINTS = [
    # Procedure : unicité par procedure_id (UUID interne, globalement unique)
    "CREATE CONSTRAINT procedure_unique IF NOT EXISTS "
    "FOR (p:Procedure) REQUIRE p.procedure_id IS UNIQUE",

    # ProcedureStep : node-key composite (procedure_id, step_number)
    # Note : Neo4j Community ne supporte pas NODE KEY → on utilise une
    # contrainte d'existence + index unique sur la clé composite stringifiée
    # `step_key = "{procedure_id}#{step_number}"`. La construction est faite
    # par le persister.
    "CREATE CONSTRAINT procedure_step_unique IF NOT EXISTS "
    "FOR (s:ProcedureStep) REQUIRE s.step_key IS UNIQUE",

    # V6-J2 — Reference : unicité par reference_id (UUID)
    "CREATE CONSTRAINT reference_unique IF NOT EXISTS "
    "FOR (r:Reference) REQUIRE r.reference_id IS UNIQUE",
]


# ─── Indexes ──────────────────────────────────────────────────────────────────

_INDEXES = [
    # Procedure : filtre par tenant + doc fréquent
    "CREATE INDEX procedure_tenant IF NOT EXISTS "
    "FOR (p:Procedure) ON (p.tenant_id)",
    "CREATE INDEX procedure_doc IF NOT EXISTS "
    "FOR (p:Procedure) ON (p.doc_id)",
    "CREATE INDEX procedure_doc_tenant IF NOT EXISTS "
    "FOR (p:Procedure) ON (p.doc_id, p.tenant_id)",

    # Search by name (fulltext pour matching procédures par mots-clés)
    "CREATE FULLTEXT INDEX procedure_name_search IF NOT EXISTS "
    "FOR (p:Procedure) ON EACH [p.name, p.goal]",

    # ProcedureStep : navigation par procedure_id
    "CREATE INDEX procedure_step_procedure_id IF NOT EXISTS "
    "FOR (s:ProcedureStep) ON (s.procedure_id)",
    "CREATE INDEX procedure_step_tenant IF NOT EXISTS "
    "FOR (s:ProcedureStep) ON (s.tenant_id)",

    # V6-J2 — Reference indexes
    "CREATE INDEX reference_tenant IF NOT EXISTS "
    "FOR (r:Reference) ON (r.tenant_id)",
    "CREATE INDEX reference_doc IF NOT EXISTS "
    "FOR (r:Reference) ON (r.doc_id)",
    "CREATE INDEX reference_doc_tenant IF NOT EXISTS "
    "FOR (r:Reference) ON (r.doc_id, r.tenant_id)",
    "CREATE INDEX reference_target_kind IF NOT EXISTS "
    "FOR (r:Reference) ON (r.target_kind)",
    # Fulltext sur reference_text pour matching par mots-clés
    "CREATE FULLTEXT INDEX reference_text_search IF NOT EXISTS "
    "FOR (r:Reference) ON EACH [r.reference_text]",
]


@dataclass
class V6Schema:
    """Schéma Neo4j additif V6 (Procedure + ProcedureStep).

    Usage :
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(...)
        V6Schema().ensure(driver)
    """

    def ensure(self, driver) -> dict[str, int]:
        """Crée constraints + indexes (idempotent). Returns un compteur."""
        stats = {"constraints_applied": 0, "indexes_applied": 0, "errors": 0}
        with driver.session() as session:
            for ddl in _CONSTRAINTS:
                try:
                    session.run(ddl)
                    stats["constraints_applied"] += 1
                except Exception as exc:
                    logger.error("[V6-J1] constraint failed: %s — %s", ddl, exc)
                    stats["errors"] += 1
            for ddl in _INDEXES:
                try:
                    session.run(ddl)
                    stats["indexes_applied"] += 1
                except Exception as exc:
                    logger.error("[V6-J1] index failed: %s — %s", ddl, exc)
                    stats["errors"] += 1
        logger.info(
            "[V6-J1] V6 schema ensured: %d constraints, %d indexes, %d errors",
            stats["constraints_applied"], stats["indexes_applied"], stats["errors"],
        )
        return stats


def ensure_v6_schema(driver) -> dict[str, int]:
    """Helper standalone : crée le schéma V6 sur un driver Neo4j actif."""
    return V6Schema().ensure(driver)
