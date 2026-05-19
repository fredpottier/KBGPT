"""V5 Reading Tools — Enregistrement V6 jalons additifs.

V6-J1 : find_procedures — récupère les Procedure multi-step persistées
        dans Neo4j (label :Procedure) à partir du jalon V6-J1.

Ce module est ADDITIF : il ne modifie pas les tools POC/V2 existants, il
ajoute un nouvel outil exposé à l'agent V5.1 sous le slot SEARCH.

Charte respectée :
- Outil universel (Procedure = archétype agnostique présent dans tout corpus
  structuré : technique, légal, médical, opérationnel, ...).
- Aucune référence corpus-spécifique (les noms/goals des procedures sont
  grounded sur les sections — ce sont les données qui portent la spécificité,
  pas le code de l'outil).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from knowbase.runtime_v5.tools.registry import (
    EvidenceType,
    ToolCategory,
    ToolRegistry,
    ToolSpec,
)

logger = logging.getLogger(__name__)


# ─── Handler ─────────────────────────────────────────────────────────────────


def find_procedures(
    doc_id: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 5,
    tenant_id: str = "default",
) -> dict:
    """Retourne les Procedure multi-step matching dans le KG.

    Args:
        doc_id : si fourni, restreint au document.
        query : si fourni, recherche fulltext sur name+goal via index
                ``procedure_name_search``. Sinon, lit toutes les procedures
                du doc ordonnées par nombre d'étapes décroissant.
        limit : nombre max de procedures retournées (default 5, max 30).
        tenant_id : tenant pour multi-tenant isolation.

    Returns:
        {"procedures": [{procedure_id, name, goal, prerequisites,
                         doc_id, section_id, steps:[{step_number,action,notes}]}, ...]}
        ou {"error": "..."} si Neo4j indisponible.
    """
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return {"error": "neo4j driver not available"}

    if limit < 1:
        limit = 1
    if limit > 30:
        limit = 30

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session() as s:
            if query and query.strip():
                # Fulltext search via index :procedure_name_search ON [name, goal]
                # Note: param Cypher nommé $q (et non $query) car le driver neo4j-python
                # réserve `query` comme nom de paramètre kw de session.run().
                cypher = """
                CALL db.index.fulltext.queryNodes('procedure_name_search', $q)
                YIELD node AS p, score
                WHERE p.tenant_id = $tenant_id
                  AND ($doc_id IS NULL OR p.doc_id = $doc_id)
                OPTIONAL MATCH (p)-[:HAS_STEP]->(st:ProcedureStep)
                WITH p, score, st ORDER BY p, st.step_number
                WITH p, score, collect({
                    step_number: st.step_number,
                    action: st.action,
                    notes: st.notes
                }) AS steps
                RETURN p.procedure_id  AS procedure_id,
                       p.name          AS name,
                       p.goal          AS goal,
                       p.prerequisites AS prerequisites,
                       p.doc_id        AS doc_id,
                       p.evidence_section_id AS section_id,
                       [s IN steps WHERE s.step_number IS NOT NULL] AS steps,
                       score
                ORDER BY score DESC
                LIMIT $limit
                """
                rows = s.run(
                    cypher,
                    q=query,
                    tenant_id=tenant_id,
                    doc_id=doc_id,
                    limit=limit,
                ).data()
            else:
                # Pas de query : lister procedures du doc (requis dans ce mode)
                if not doc_id:
                    return {
                        "error": "either 'query' or 'doc_id' must be provided",
                        "procedures": [],
                    }
                cypher = """
                MATCH (p:Procedure {doc_id: $doc_id, tenant_id: $tenant_id})
                OPTIONAL MATCH (p)-[:HAS_STEP]->(st:ProcedureStep)
                WITH p, st ORDER BY p, st.step_number
                WITH p, collect({
                    step_number: st.step_number,
                    action: st.action,
                    notes: st.notes
                }) AS steps
                RETURN p.procedure_id  AS procedure_id,
                       p.name          AS name,
                       p.goal          AS goal,
                       p.prerequisites AS prerequisites,
                       p.doc_id        AS doc_id,
                       p.evidence_section_id AS section_id,
                       [s IN steps WHERE s.step_number IS NOT NULL] AS steps
                ORDER BY size(steps) DESC
                LIMIT $limit
                """
                rows = s.run(
                    cypher, doc_id=doc_id, tenant_id=tenant_id, limit=limit
                ).data()

            # Sanitize : transformer les listes Neo4j en list Python propres
            cleaned: list[dict] = []
            for r in rows:
                cleaned.append({
                    "procedure_id": r.get("procedure_id"),
                    "name": r.get("name"),
                    "goal": r.get("goal"),
                    "prerequisites": list(r.get("prerequisites") or []),
                    "doc_id": r.get("doc_id"),
                    "section_id": r.get("section_id"),
                    "steps": [
                        {
                            "step_number": st.get("step_number"),
                            "action": st.get("action"),
                            "notes": st.get("notes"),
                        }
                        for st in (r.get("steps") or [])
                        if st and st.get("step_number") is not None
                    ],
                })

            return {
                "doc_id": doc_id,
                "query": query,
                "n_procedures": len(cleaned),
                "procedures": cleaned,
            }
    except Exception as exc:
        logger.error(f"[V6-J1] find_procedures failed: {exc}")
        return {"error": f"neo4j_query_failed: {exc}", "procedures": []}
    finally:
        driver.close()


# ─── ToolSpec ────────────────────────────────────────────────────────────────


def _find_procedures_spec() -> ToolSpec:
    return ToolSpec(
        name="find_procedures",
        category=ToolCategory.SEARCH,
        description=(
            "Returns the structured multi-step procedures persisted in the "
            "knowledge graph for a document, with their goal, ordered steps "
            "and prerequisites. Each procedure was extracted verbatim from a "
            "document section. Use this when the question is procedural "
            "('how to ...', 'what are the steps to ...', 'procedure to ...'). "
            "Either pass a free-text 'query' to fulltext-search by name/goal, "
            "or pass only 'doc_id' to list the procedures of that document."
        ),
        preferred_when=(
            "question is procedural (how-to / step-by-step), or you need the "
            "ordered steps of a known procedure"
        ),
        # Réutilise un EvidenceType existant : LINKED_SECTIONS sémantiquement
        # proche (procedures sont rattachées à leur evidence section).
        evidence_type_returned=EvidenceType.LINKED_SECTIONS,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "Document identifier. Optional if 'query' is provided.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Free-text query matched against procedure name+goal "
                        "via fulltext index. If omitted, lists all procedures "
                        "of doc_id (which then becomes required)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "default": 5,
                },
                "tenant_id": {
                    "type": "string",
                    "default": "default",
                },
            },
            "required": [],
        },
        handler=find_procedures,
    )


# ─── V6-J2 — find_references ─────────────────────────────────────────────────


def find_references(
    doc_id: Optional[str] = None,
    target_kind: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 10,
    tenant_id: str = "default",
) -> dict:
    """Retourne les Reference typées extraites pour un document.

    Args:
        doc_id : restreint au document (optionnel si `query` fourni).
        target_kind : filtre par type
            (internal_section|external_document|standard|regulation|url|other).
        query : recherche fulltext sur `reference_text` via index
                ``reference_text_search``.
        limit : nombre max (default 10, max 50).
        tenant_id : multi-tenant isolation.

    Returns:
        {"references": [{reference_id, reference_text, target_kind,
                         doc_id, section_id, resolved_target}, ...]}
        ou {"error": "..."} si Neo4j indisponible.
    """
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return {"error": "neo4j driver not available"}

    if limit < 1:
        limit = 1
    if limit > 50:
        limit = 50

    VALID_KINDS = {
        "internal_section", "external_document", "standard",
        "regulation", "url", "other",
    }
    if target_kind and target_kind not in VALID_KINDS:
        return {
            "error": f"invalid target_kind '{target_kind}', expected one of {sorted(VALID_KINDS)}",
            "references": [],
        }

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session() as s:
            if query and query.strip():
                cypher = """
                CALL db.index.fulltext.queryNodes('reference_text_search', $q)
                YIELD node AS r, score
                WHERE r.tenant_id = $tenant_id
                  AND ($doc_id IS NULL OR r.doc_id = $doc_id)
                  AND ($target_kind IS NULL OR r.target_kind = $target_kind)
                RETURN r.reference_id  AS reference_id,
                       r.reference_text AS reference_text,
                       r.target_kind    AS target_kind,
                       r.resolved_target AS resolved_target,
                       r.doc_id         AS doc_id,
                       r.evidence_section_id AS section_id,
                       score
                ORDER BY score DESC
                LIMIT $limit
                """
                rows = s.run(
                    cypher,
                    q=query,
                    tenant_id=tenant_id,
                    doc_id=doc_id,
                    target_kind=target_kind,
                    limit=limit,
                ).data()
            else:
                if not doc_id:
                    return {
                        "error": "either 'query' or 'doc_id' must be provided",
                        "references": [],
                    }
                cypher = """
                MATCH (r:Reference {doc_id: $doc_id, tenant_id: $tenant_id})
                WHERE ($target_kind IS NULL OR r.target_kind = $target_kind)
                RETURN r.reference_id  AS reference_id,
                       r.reference_text AS reference_text,
                       r.target_kind    AS target_kind,
                       r.resolved_target AS resolved_target,
                       r.doc_id         AS doc_id,
                       r.evidence_section_id AS section_id
                ORDER BY r.target_kind, r.reference_text
                LIMIT $limit
                """
                rows = s.run(
                    cypher,
                    doc_id=doc_id,
                    tenant_id=tenant_id,
                    target_kind=target_kind,
                    limit=limit,
                ).data()

            cleaned = [
                {
                    "reference_id": r.get("reference_id"),
                    "reference_text": r.get("reference_text"),
                    "target_kind": r.get("target_kind"),
                    "resolved_target": r.get("resolved_target"),
                    "doc_id": r.get("doc_id"),
                    "section_id": r.get("section_id"),
                }
                for r in rows
            ]
            return {
                "doc_id": doc_id,
                "target_kind": target_kind,
                "query": query,
                "n_references": len(cleaned),
                "references": cleaned,
            }
    except Exception as exc:
        logger.error(f"[V6-J2] find_references failed: {exc}")
        return {"error": f"neo4j_query_failed: {exc}", "references": []}
    finally:
        driver.close()


def _find_references_spec() -> ToolSpec:
    return ToolSpec(
        name="find_references",
        category=ToolCategory.SEARCH,
        description=(
            "Returns the typed cross-references extracted from a document : "
            "pointers to other sections, external documents, standards, "
            "regulations, or URLs cited in the text. Use this when the question "
            "asks about WHAT a section CITES or POINTS TO ('what does X reference', "
            "'which standards are mentioned', 'list all referenced documents'). "
            "Pass `target_kind` to filter by type, or `query` for fulltext search "
            "over reference_text."
        ),
        preferred_when=(
            "question is about cross-references, citations, or pointers to "
            "external information ('what does X cite', 'which regulations apply')"
        ),
        evidence_type_returned=EvidenceType.LINKED_SECTIONS,
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "Document identifier. Optional if 'query' is provided.",
                },
                "target_kind": {
                    "type": "string",
                    "enum": [
                        "internal_section", "external_document", "standard",
                        "regulation", "url", "other",
                    ],
                    "description": "Filter by reference target type. Optional.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Free-text query matched against reference_text via "
                        "fulltext index. If omitted, lists references of doc_id."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
                "tenant_id": {
                    "type": "string",
                    "default": "default",
                },
            },
            "required": [],
        },
        handler=find_references,
    )


# ─── Registration helper ─────────────────────────────────────────────────────


def register_v6_tools(registry: ToolRegistry, *, allow_replace: bool = False) -> dict:
    """Enregistre les outils V6 (J1 + à venir J2/J3) dans le registry.

    Returns:
        {"registered": [...], "errors": [...]}
    """
    specs = [
        _find_procedures_spec(),
        _find_references_spec(),    # V6-J2
        # _get_concept_card_spec(),   # V6-J3 (à venir)
    ]
    registered: list[str] = []
    errors: list[dict] = []
    for spec in specs:
        try:
            registry.register(spec, allow_replace=allow_replace)
            registered.append(spec.name)
        except Exception as e:
            errors.append({"name": spec.name, "error": str(e)})
    return {"registered": registered, "errors": errors}
