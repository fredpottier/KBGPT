"""KG Query Operator (Cap2.C — CH-49 Phase 2).

Operator déterministe pour les questions STRUCTURELLES sur le graphe :
  - CHAIN : "supersession chain of <DOC_X>" / "lineage of <DOC_X>" / "what evolved into <DOC_Y>"
  - LIST_BY_STATUS : "list documents that are <STATUS>" / "active regulations"
  - COUNT : "how many documents are <STATUS>" / "number of <RELATION_TYPE>"

Architecture (charte ADR §1) :
  1. INTENT — LLM léger DeepSeek : {is_kg_query, query_type, ...}
  2. KG QUERY — Cypher template par query_type
  3. FORMATTING — composition déterministe avec citations + comptage

Charte :
  - Le LLM raisonne en concepts ("documents", "status", "chain") — il ne CONNAÎT PAS le schéma
  - L'operator traduit concepts → schéma KG (DocumentContext, lifecycle_status, LIFECYCLE_RELATION)
  - JAMAIS de regex/keywords métier dans le prompt LLM
  - Tous les exemples du prompt utilisent placeholders abstraits <DOC_X>, <STATUS>, <REL>

Domain-agnostic : le mapping concept→schéma est le seul lien avec le KG, pas le LLM.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


INTENT_DETECTION_PROMPT = """You analyze user questions to determine if they ask a STRUCTURAL question about a document graph (counting, listing by status, traversing a chain of relations between documents).

Return JSON only:
{
  "is_kg_query": <bool>,
  "query_type": "CHAIN" | "LIST_BY_STATUS" | "COUNT" | null,
  "target_concept": "document" | "relation" | "status_group" | null,
  "status_filter": "<STATUS>" | null,
  "subject_keywords": ["<key terms identifying anchor docs if any>"],
  "relation_hint": "supersession" | "evolution" | "reaffirmation" | null,
  "confidence": <float 0-1>,
  "reason": "<short explanation>"
}

Set is_kg_query=true ONLY if the question asks for a structural answer (a list / a number / a chain), NOT a fact or explanation.

query_type :
- "CHAIN" : the user wants to traverse a transitive chain of relations between documents
  (e.g. "supersession chain", "lineage", "what evolved into <DOC_Y>", "predecessors of <DOC_X> recursively")
- "LIST_BY_STATUS" : the user wants the list of documents matching a status
  (e.g. "all <STATUS> documents", "what is currently <STATUS>")
- "COUNT" : the user wants a number / count
  (e.g. "how many <STATUS> documents", "number of relations", "count of <REL>")

target_concept :
- "document" : if querying about documents themselves
- "relation" : if querying about relations between documents
- "status_group" : if querying about a group sharing a status

status_filter : status word the user uses (active, deprecated, repealed, current, in force, ...). Copy verbatim from the question.

relation_hint : semantic clue about what kind of evolution/replacement the user means
- "supersession" : replace, repeal, supersede, abrogate
- "evolution" : amend, modify, evolve
- "reaffirmation" : reaffirm, restate, confirm

Set is_kg_query=false for :
- direct factual questions ("What is the maximum X?")
- causal questions ("Why was X repealed?")
- explanation questions ("Explain Y")
- list-of-items-WITHIN-a-document questions ("List the items in <DOC_X>")

Examples (abstract — placeholders <DOC_X>, <STATUS>, <REL>):
- "What is the supersession chain of <DOC_X>?" → is_kg_query=true, query_type="CHAIN", subject_keywords=["<DOC_X>"], relation_hint="supersession"
- "How many <STATUS> regulations exist?" → is_kg_query=true, query_type="COUNT", target_concept="document", status_filter="<STATUS>"
- "List all <STATUS> documents" → is_kg_query=true, query_type="LIST_BY_STATUS", status_filter="<STATUS>"
- "How many <REL> relations are in the graph?" → is_kg_query=true, query_type="COUNT", target_concept="relation", relation_hint="<REL>"
- "What does <DOC_X> say about Y?" → is_kg_query=false (factual content)
- "Why was <DOC_X> repealed?" → is_kg_query=false (causal)
"""


# Mapping conceptuel → schéma KG (centralisé, JAMAIS dans le prompt LLM)
# Conformes au schéma OSMOSIS validé 10/05/2026.
_STATUS_SYNONYMS = {
    "active": ["active", "ACTIVE", "in_force", "current"],
    "deprecated": ["deprecated", "DEPRECATED", "repealed", "superseded", "obsolete"],
}


def _normalize_status(status_raw: Optional[str]) -> Optional[list[str]]:
    """Convertit un libellé utilisateur (active, deprecated, etc.) en valeurs schéma KG."""
    if not status_raw:
        return None
    s = status_raw.strip().lower()
    for canonical, synonyms in _STATUS_SYNONYMS.items():
        if s in [x.lower() for x in synonyms] or s == canonical:
            # Retourne les variantes attendues côté DB (le KG peut stocker en upper/lower)
            return synonyms
    return [status_raw]  # passthrough si pas dans la map


@dataclass
class KGQueryResult:
    triggered: bool
    answer: str = ""
    query_type: Optional[str] = None  # CHAIN | LIST_BY_STATUS | COUNT
    rows: list[dict] = field(default_factory=list)
    count_value: Optional[int] = None
    intent: dict = field(default_factory=dict)
    decision: str = "ABSTAIN"
    abstention_reason: Optional[str] = None
    fallback_path: str = "primary"
    latency_breakdown_ms: dict = field(default_factory=dict)


class KGQueryOperator:
    """Operator Cap2.C : queries structurelles sur le KG (CHAIN, LIST_BY_STATUS, COUNT)."""

    DEEPSEEK_MODEL = "deepseek-ai/DeepSeek-V3.1"
    DEEPSEEK_BASE_URL = "https://api.together.xyz/v1"

    GENERIC_KEYWORDS = {
        "document", "documents", "doc", "docs",
        "regulation", "regulations", "règlement", "règlements",
        "rule", "rules", "directive", "directives",
        "law", "laws", "act", "acts",
        "item", "items",
    }

    def __init__(
        self,
        neo4j_driver: Any,
        tenant_id: str = "default",
        timeout: float = 30.0,
    ) -> None:
        self.driver = neo4j_driver
        self.tenant_id = tenant_id
        self.timeout = timeout
        self.api_key = os.getenv("TOGETHER_API_KEY", "")

    # ---------------------------------------------------------------- Intent
    def detect_intent(self, question: str) -> dict:
        payload = {
            "model": self.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": INTENT_DETECTION_PROMPT},
                {"role": "user", "content": f"Question: {question}"},
            ],
            "temperature": 0.0,
            "max_tokens": 250,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=httpx.HTTPTransport(retries=0),
            ) as client:
                resp = client.post(
                    f"{self.DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload, headers=headers,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"KGQuery intent detection failed: {exc}")
            return {
                "is_kg_query": False,
                "query_type": None,
                "confidence": 0.0,
                "reason": f"intent_error: {exc}",
            }

    # ---------------------------------------------------------------- Cypher
    def query_chain(
        self,
        subject_keywords: list[str],
        relation_hint: Optional[str] = None,
        max_depth: int = 6,
    ) -> list[dict]:
        """Traverse une chaîne LIFECYCLE_RELATION (transitive) ancrée sur subject_keywords.

        Direction : depuis n'importe quel node matchant les keywords, on explore les
        deux sens (successeurs ET prédécesseurs) jusqu'à profondeur max_depth.

        Output : ordonné chronologiquement (publication_date) si dispo.
        """
        if not subject_keywords:
            return []
        rel_filter = ""
        if relation_hint == "supersession":
            rel_filter = " AND r.type = 'SUPERSEDES'"
        elif relation_hint == "evolution":
            rel_filter = " AND r.type = 'EVOLVES_FROM'"
        elif relation_hint == "reaffirmation":
            rel_filter = " AND r.type = 'REAFFIRMS'"

        cypher = f"""
            MATCH (anchor:DocumentContext)
            WHERE anchor.tenant_id = $tenant_id
              AND any(kw IN $keywords WHERE
                  toLower(coalesce(anchor.primary_subject, '')) CONTAINS toLower(kw)
                  OR toLower(coalesce(anchor.doc_id, '')) CONTAINS toLower(kw)
                  OR toLower(coalesce(anchor.full_doc_title, '')) CONTAINS toLower(kw)
              )
            CALL {{
                WITH anchor
                MATCH path = (anchor)-[r:LIFECYCLE_RELATION*1..{max_depth}]-(other:DocumentContext)
                WHERE all(rel IN r WHERE rel.tenant_id = $tenant_id{rel_filter})
                RETURN path, length(path) AS depth, other
                LIMIT 50
            }}
            RETURN
                anchor.doc_id AS anchor_doc_id,
                coalesce(anchor.full_doc_title, anchor.primary_subject, anchor.doc_id) AS anchor_title,
                other.doc_id AS other_doc_id,
                coalesce(other.full_doc_title, other.primary_subject, other.doc_id) AS other_title,
                other.publication_date AS other_date,
                depth,
                [rel IN relationships(path) | rel.type] AS rel_types,
                [rel IN relationships(path) | rel.evidence_quote] AS evidence_quotes
            ORDER BY depth ASC, other.publication_date ASC
            LIMIT 30
        """
        with self.driver.session(database="neo4j") as session:
            try:
                result = session.run(
                    cypher, tenant_id=self.tenant_id, keywords=subject_keywords,
                )
                return [dict(rec) for rec in result]
            except Exception as exc:  # noqa: BLE001
                logger.error(f"KGQuery query_chain failed: {exc}")
                return []

    def query_list_by_status(self, status_synonyms: list[str]) -> list[dict]:
        """Liste les DocumentContext dont lifecycle_status matche une variante."""
        if not status_synonyms:
            return []
        cypher = """
            MATCH (d:DocumentContext)
            WHERE d.tenant_id = $tenant_id
              AND d.lifecycle_status IS NOT NULL
              AND any(s IN $synonyms WHERE toLower(d.lifecycle_status) = toLower(s))
            RETURN d.doc_id AS doc_id,
                   coalesce(d.full_doc_title, d.primary_subject, d.doc_id) AS title,
                   d.lifecycle_status AS lifecycle_status,
                   d.publication_date AS publication_date,
                   d.primary_subject AS primary_subject
            ORDER BY d.publication_date DESC NULLS LAST
        """
        with self.driver.session(database="neo4j") as session:
            try:
                result = session.run(
                    cypher, tenant_id=self.tenant_id, synonyms=status_synonyms,
                )
                return [dict(rec) for rec in result]
            except Exception as exc:  # noqa: BLE001
                logger.error(f"KGQuery query_list_by_status failed: {exc}")
                return []

    def query_count(
        self,
        target_concept: Optional[str],
        status_synonyms: Optional[list[str]] = None,
        relation_hint: Optional[str] = None,
    ) -> Optional[int]:
        """COUNT :
        - target=document + status_synonyms : count DocumentContext filtré
        - target=relation + relation_hint : count LIFECYCLE_RELATION filtré
        """
        if target_concept == "document" and status_synonyms:
            cypher = """
                MATCH (d:DocumentContext)
                WHERE d.tenant_id = $tenant_id
                  AND any(s IN $synonyms WHERE toLower(d.lifecycle_status) = toLower(s))
                RETURN count(d) AS n
            """
            params = {"tenant_id": self.tenant_id, "synonyms": status_synonyms}
        elif target_concept == "relation" and relation_hint:
            rel_type_map = {
                "supersession": "SUPERSEDES",
                "evolution": "EVOLVES_FROM",
                "reaffirmation": "REAFFIRMS",
            }
            target_type = rel_type_map.get(relation_hint)
            if not target_type:
                return None
            cypher = """
                MATCH ()-[r:LIFECYCLE_RELATION]->()
                WHERE r.tenant_id = $tenant_id AND r.type = $type
                RETURN count(r) AS n
            """
            params = {"tenant_id": self.tenant_id, "type": target_type}
        elif target_concept == "document":
            cypher = """
                MATCH (d:DocumentContext)
                WHERE d.tenant_id = $tenant_id
                RETURN count(d) AS n
            """
            params = {"tenant_id": self.tenant_id}
        elif target_concept == "relation":
            cypher = """
                MATCH ()-[r:LIFECYCLE_RELATION]->()
                WHERE r.tenant_id = $tenant_id
                RETURN count(r) AS n
            """
            params = {"tenant_id": self.tenant_id}
        else:
            return None

        with self.driver.session(database="neo4j") as session:
            try:
                result = session.run(cypher, **params)
                rec = result.single()
                return int(rec["n"]) if rec else None
            except Exception as exc:  # noqa: BLE001
                logger.error(f"KGQuery query_count failed: {exc}")
                return None

    # ---------------------------------------------------------- Formatting
    @staticmethod
    def _format_chain(rows: list[dict], anchor_title: str) -> str:
        if not rows:
            return ""
        lines = [f"Chaîne lifecycle ancrée sur « {anchor_title} » ({len(rows)} relation(s)) :"]
        for r in rows[:10]:
            rel_path = " → ".join(r.get("rel_types") or [])
            other = r.get("other_title") or r.get("other_doc_id")
            other_id = r.get("other_doc_id")
            depth = r.get("depth")
            date = r.get("other_date") or "?"
            lines.append(
                f"- depth={depth}, [{rel_path}] → {other} ({date}) [doc={other_id}]"
            )
        # Première evidence_quote utile
        for r in rows:
            quotes = r.get("evidence_quotes") or []
            for q in quotes:
                if q:
                    lines.append(f"\nEvidence : « {q} »")
                    return "\n".join(lines)
        return "\n".join(lines)

    @staticmethod
    def _format_list_by_status(rows: list[dict], status_label: str) -> str:
        if not rows:
            return ""
        n = len(rows)
        lines = [f"{n} document(s) avec status « {status_label} » :"]
        for r in rows[:15]:
            title = r.get("title") or r.get("doc_id")
            doc_id = r.get("doc_id")
            date = r.get("publication_date") or "?"
            lines.append(f"- {title} ({date}) [doc={doc_id}]")
        if n > 15:
            lines.append(f"... et {n - 15} autre(s)")
        return "\n".join(lines)

    @staticmethod
    def _format_count(n: Optional[int], target: str, qualifier: str) -> str:
        if n is None:
            return ""
        return f"Comptage : {n} {target} {qualifier}".strip()

    # ---------------------------------------------------------- Public API
    def execute(self, question: str) -> KGQueryResult:
        timings: dict[str, int] = {}
        result = KGQueryResult(triggered=False)

        t0 = time.time()
        intent = self.detect_intent(question)
        timings["intent_ms"] = int((time.time() - t0) * 1000)
        result.intent = intent

        if not intent.get("is_kg_query"):
            result.decision = "NOT_APPLICABLE"
            result.abstention_reason = "intent_not_kg_query"
            result.latency_breakdown_ms = timings
            return result

        result.triggered = True
        query_type = intent.get("query_type")
        result.query_type = query_type
        keywords_raw = intent.get("subject_keywords") or []
        keywords = [
            k for k in keywords_raw
            if k and k.lower() not in self.GENERIC_KEYWORDS and len(k) > 1
        ]
        status_synonyms = _normalize_status(intent.get("status_filter"))
        relation_hint = intent.get("relation_hint")
        target_concept = intent.get("target_concept")

        if query_type == "CHAIN":
            if not keywords:
                result.decision = "ABSTAIN"
                result.abstention_reason = "chain_needs_anchor_keywords"
                result.fallback_path = "escalate"
                result.latency_breakdown_ms = timings
                return result
            t0 = time.time()
            rows = self.query_chain(keywords, relation_hint=relation_hint)
            timings["cypher_ms"] = int((time.time() - t0) * 1000)
            result.rows = rows
            if not rows:
                result.decision = "ABSTAIN"
                result.abstention_reason = "no_chain_found"
                result.fallback_path = "escalate"
                result.latency_breakdown_ms = timings
                return result
            anchor_title = rows[0].get("anchor_title") or " ".join(keywords)
            result.answer = self._format_chain(rows, anchor_title)
            result.decision = "ANSWER"

        elif query_type == "LIST_BY_STATUS":
            if not status_synonyms:
                result.decision = "ABSTAIN"
                result.abstention_reason = "list_needs_status_filter"
                result.fallback_path = "escalate"
                result.latency_breakdown_ms = timings
                return result
            t0 = time.time()
            rows = self.query_list_by_status(status_synonyms)
            timings["cypher_ms"] = int((time.time() - t0) * 1000)
            result.rows = rows
            if not rows:
                result.decision = "ABSTAIN"
                result.abstention_reason = "no_documents_match_status"
                result.fallback_path = "escalate"
                result.latency_breakdown_ms = timings
                return result
            result.answer = self._format_list_by_status(
                rows, intent.get("status_filter") or status_synonyms[0],
            )
            result.decision = "ANSWER"

        elif query_type == "COUNT":
            t0 = time.time()
            n = self.query_count(
                target_concept=target_concept,
                status_synonyms=status_synonyms,
                relation_hint=relation_hint,
            )
            timings["cypher_ms"] = int((time.time() - t0) * 1000)
            if n is None:
                result.decision = "ABSTAIN"
                result.abstention_reason = "count_underspecified"
                result.fallback_path = "escalate"
                result.latency_breakdown_ms = timings
                return result
            result.count_value = n
            qualifier_parts = []
            if status_synonyms:
                qualifier_parts.append(f"avec status {intent.get('status_filter') or status_synonyms[0]}")
            if relation_hint:
                qualifier_parts.append(f"de type {relation_hint}")
            qualifier = " ".join(qualifier_parts)
            target_label = target_concept or "élément(s)"
            result.answer = self._format_count(n, target_label, qualifier)
            result.decision = "ANSWER"

        else:
            result.decision = "ABSTAIN"
            result.abstention_reason = f"unknown_query_type:{query_type}"
            result.fallback_path = "escalate"

        result.latency_breakdown_ms = timings
        return result
