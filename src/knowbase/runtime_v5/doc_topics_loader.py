"""Loader pour les DocumentContext enrichis (doc_title, doc_summary, key_topics, key_terms).

⚠️ DEPRECATED (A3.6, 2026-05-21) — Réf ADR_PARSE_EVALUATE_RUNTIME §10.2.

Ce module sera supprimé une fois :
- Bench A3.8 validé (gates GA3-5/6/7 atteints)
- Phase B cross-domain validée
- V5.1 retiré comme endpoint de référence

Remplacé par : lookup canonical entities via Execute kg_claims (runtime_a3).
Le routage par doc agrégé n'est plus nécessaire dans le pipeline déterministe V6.

⚠️ NE PAS étendre. Pour nouveaux développements, voir runtime_a3/.

---

Lit depuis Neo4j la liste des documents disponibles avec leurs métadonnées de routage.
Utilisé par reasoning_agent_v51._build_user_prompt pour donner à l'agent un signal
discriminant entre les docs (vs juste les doc_ids opaques).

Charte domain-agnostic stricte :
- Champs neutres : key_topics, key_terms (pas SAP-specific)
- Naming réutilisable sur tout corpus (légal, médical, aerospace, etc.)

Cache in-memory simple : refresh sur restart api (les DocumentContext changent
lors de ré-ingestion / enrichissement offline, pas en runtime).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Warning DEPRECATED (A3.6, 2026-05-21) — émis une fois par import
if not globals().get("_DEPRECATED_WARNED", False):
    logger.warning(
        "⚠️ DEPRECATED module loaded: runtime_v5.doc_topics_loader. "
        "Replaced by canonical entities lookup via runtime_a3 Execute. "
        "Removal scheduled post-A3.8. "
        "See doc/ongoing/POST_A36_V51_SUPPRESSIONS_AUDIT_2026-05-21.md"
    )
    _DEPRECATED_WARNED = True


@dataclass
class DocTopicsRecord:
    """Snapshot enrichi d'un document pour le routage agent."""
    doc_id: str
    doc_title: str = ""
    doc_summary: str = ""
    key_topics: list[str] = field(default_factory=list)
    key_terms: list[str] = field(default_factory=list)


# Cache in-memory (clé : tenant_id → list[DocTopicsRecord])
_CACHE: dict[str, list[DocTopicsRecord]] = {}


def _get_neo4j_driver():
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://knowbase-neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, pwd))


def load_doc_topics(tenant_id: str = "default", force_refresh: bool = False) -> list[DocTopicsRecord]:
    """Charge la liste des DocumentContext enrichis pour le tenant.

    Args:
        tenant_id : tenant à filtrer (default = 'default')
        force_refresh : ignore le cache et recharge depuis Neo4j

    Returns:
        list[DocTopicsRecord] — un par doc, ordonné par doc_id
    """
    if not force_refresh and tenant_id in _CACHE:
        return _CACHE[tenant_id]

    records: list[DocTopicsRecord] = []
    try:
        driver = _get_neo4j_driver()
        with driver.session() as session:
            query = """
            MATCH (dc:DocumentContext)
            WHERE coalesce(dc.tenant_id, 'default') = $tenant_id
            RETURN dc.doc_id AS doc_id,
                   coalesce(dc.doc_title, '') AS doc_title,
                   coalesce(dc.doc_summary, '') AS doc_summary,
                   coalesce(dc.key_topics, []) AS key_topics,
                   coalesce(dc.key_terms, []) AS key_terms
            ORDER BY dc.doc_id
            """
            result = session.run(query, tenant_id=tenant_id)
            for row in result:
                records.append(DocTopicsRecord(
                    doc_id=row["doc_id"],
                    doc_title=row["doc_title"] or "",
                    doc_summary=row["doc_summary"] or "",
                    key_topics=list(row["key_topics"] or []),
                    key_terms=list(row["key_terms"] or []),
                ))
        driver.close()
    except Exception as exc:
        logger.warning("[doc_topics_loader] failed to load: %s", exc)
        return []

    _CACHE[tenant_id] = records
    logger.info(
        "[doc_topics_loader] loaded %d DocumentContext for tenant=%s",
        len(records), tenant_id,
    )
    return records


def format_available_docs_listing(
    records: list[DocTopicsRecord],
    max_topics_per_doc: int = 4,
    max_terms_per_doc: int = 8,
) -> str:
    """Formate la liste de docs en bloc texte pour injection dans user prompt.

    Format compact mais informatif :
      - doc_id — title
        topics: t1, t2, t3
        terms: term1, term2, term3, ...

    Si un doc n'a pas d'enrichissement (champs vides), affiche juste doc_id.
    """
    if not records:
        return "  (corpus not indexed)"

    lines = []
    for r in records:
        # Format de base : doc_id (toujours présent, indispensable pour les tool args)
        if r.doc_title:
            lines.append(f"  - {r.doc_id} — {r.doc_title}")
        else:
            lines.append(f"  - {r.doc_id}")
        # Sous-lignes enrichissement (si dispo)
        if r.key_topics:
            topics = ", ".join(r.key_topics[:max_topics_per_doc])
            lines.append(f"      topics: {topics}")
        if r.key_terms:
            terms = ", ".join(r.key_terms[:max_terms_per_doc])
            lines.append(f"      terms: {terms}")
    return "\n".join(lines)


def clear_cache(tenant_id: Optional[str] = None) -> None:
    """Invalide le cache. Si tenant_id=None, vide tout."""
    if tenant_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(tenant_id, None)
