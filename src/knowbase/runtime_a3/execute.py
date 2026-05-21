"""Module Execute — exécution Cypher / Qdrant déterministe (cf ADR §2.3 + §4).

100% déterministe : pour chaque ToolCall planifié par Plan, on lance la requête
correspondante avec **filtres bitemporels obligatoires** (cf ADR_BITEMPOREL §4.4).

Side-effect critique (§2.6) :
    Après les ToolCall principaux, collecte tous les `claim_ids` retournés et lance
    une seule requête `conflict_pending_surface` pour attacher les :ConflictPending
    adjacents à chaque ToolResult — cela expose la transparence au Synthesize.

Domain-agnostic : aucun token, regex ou prédicat corpus-spécifique.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from knowbase.runtime_a3.schemas import (
    ClaimSummary,
    ConflictPendingSummary,
    CoverageSignal,
    ExecuteOutput,
    ParseInput,
    ParseOutput,
    PlanOutput,
    RelationSummary,
    SectionSummary,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger("knowbase.runtime_a3.execute")


# ============================================================================
# Cypher templates (cf ADR §4)
# ============================================================================


# §4.1 kg_claims — fact_lookup, definition_lookup
CYPHER_KG_CLAIMS = """
MATCH (c:Claim {tenant_id: $tenant_id})
WHERE c.subject_canonical = $subject
  AND ($predicate IS NULL OR c.predicate = $predicate)
  AND c.invalidated_at IS NULL
  AND (c.valid_from IS NULL OR c.valid_from <= datetime($as_of))
  AND (c.valid_until IS NULL OR c.valid_until >= datetime($as_of))
OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(s:Section)
RETURN c, collect(s) AS sections
LIMIT 50
"""

# §4.2 kg_claims_list — list_enumeration
CYPHER_KG_CLAIMS_LIST = """
MATCH (c:Claim {tenant_id: $tenant_id})
WHERE ($subject_filter IS NULL OR c.subject_canonical = $subject_filter)
  AND ($predicate IS NULL OR c.predicate = $predicate)
  AND c.invalidated_at IS NULL
  AND (c.valid_from IS NULL OR c.valid_from <= datetime($as_of))
  AND (c.valid_until IS NULL OR c.valid_until >= datetime($as_of))
OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(s:Section)
RETURN c, collect(s) AS sections
ORDER BY coalesce(c.confidence, 0.0) DESC
LIMIT 100
"""

# §4.3 lifecycle_query — pas de filtre bitemporel (on veut toute la timeline)
CYPHER_LIFECYCLE = """
MATCH (c:Claim {tenant_id: $tenant_id, subject_canonical: $subject})
OPTIONAL MATCH path = (c)-[r:EVOLUTION_OF|SUPERSEDES*0..5]-(other:Claim)
WITH collect(DISTINCT c) + collect(DISTINCT other) AS claims_set, collect(DISTINCT r) AS rels
UNWIND claims_set AS c
WITH DISTINCT c, rels
WHERE c IS NOT NULL
OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(s:Section)
RETURN c, collect(s) AS sections, rels
ORDER BY coalesce(c.valid_from, c.ingested_at)
"""

# §4.4 contradiction_surface
CYPHER_CONTRADICTIONS = """
MATCH (a:Claim {tenant_id: $tenant_id})-[r:CONTRADICTS]-(b:Claim {tenant_id: $tenant_id})
WHERE (a.subject_canonical = $subject OR b.subject_canonical = $subject)
  AND a.invalidated_at IS NULL AND b.invalidated_at IS NULL
OPTIONAL MATCH (a)-[:EVIDENCED_BY]->(sa:Section)
OPTIONAL MATCH (b)-[:EVIDENCED_BY]->(sb:Section)
RETURN a, b, r, collect(DISTINCT sa) AS sections_a, collect(DISTINCT sb) AS sections_b
LIMIT 20
"""

# §4.5 conflict_pending_surface — transversal
CYPHER_CONFLICT_PENDING = """
MATCH (cp:ConflictPending {tenant_id: $tenant_id})
WHERE cp.resolution_status = 'unresolved'
  AND EXISTS {
      MATCH (cp)-[:INVOLVES]->(c:Claim)
      WHERE c.claim_id IN $returned_claim_ids
  }
MATCH (cp)-[:INVOLVES]->(involved:Claim)
RETURN cp, collect(involved.claim_id) AS involved_claim_ids
"""

# Section embeddings collection (par défaut)
DEFAULT_QDRANT_COLLECTION = "knowbase_chunks_v2"

# Limites de protection
MAX_TEXT_EXCERPT_CHARS = 500


# ============================================================================
# Executor
# ============================================================================


class Executor:
    """Exécute un PlanOutput contre Neo4j + Qdrant.

    Injection de dépendances pour testabilité :
        - `neo4j_client` : objet exposant `.execute_query(query, **params) -> List[Dict]`
        - `qdrant_search` : callable signature `(collection, query_vector, tenant_id, limit, score_threshold) -> List[Dict]`
        - `embedder` : callable signature `(query_text) -> List[float]`

    En production, `neo4j_client = get_neo4j_client()`, etc. En tests, mocks.
    """

    def __init__(
        self,
        neo4j_client: Any = None,
        qdrant_search: Optional[Callable] = None,
        embedder: Optional[Callable] = None,
        qdrant_collection: str = DEFAULT_QDRANT_COLLECTION,
    ):
        self._neo4j = neo4j_client
        self._qdrant_search = qdrant_search
        self._embedder = embedder
        self._qdrant_collection = qdrant_collection

    # ------------------------------------------------------------------
    # Lazy default clients (only when not injected)
    # ------------------------------------------------------------------

    def _get_neo4j(self):
        if self._neo4j is None:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            self._neo4j = get_neo4j_client()
        return self._neo4j

    def _get_qdrant_search(self):
        if self._qdrant_search is None:
            from knowbase.common.clients.qdrant_client import search_with_tenant_filter
            self._qdrant_search = search_with_tenant_filter
        return self._qdrant_search

    def _get_embedder(self):
        if self._embedder is None:
            from knowbase.common.clients.embeddings import EmbeddingModelManager
            mgr = EmbeddingModelManager()
            self._embedder = lambda text: mgr.encode([text])[0].tolist()
        return self._embedder

    # ------------------------------------------------------------------
    # Top-level
    # ------------------------------------------------------------------

    def execute(
        self,
        parse_input: ParseInput,
        plan_output: PlanOutput,
    ) -> ExecuteOutput:
        """Exécute tous les ToolCall + side-effect ConflictPending."""
        t0 = time.perf_counter()
        results: List[ToolResult] = []

        # 1) Exécuter chaque ToolCall séquentiellement (parallélisation v2)
        for tc in plan_output.tool_calls:
            result = self._execute_tool_call(tc, parse_input, plan_output)
            results.append(result)

        # 2) Side-effect §2.6 : charger les :ConflictPending adjacents aux claims retournés
        self._attach_conflict_pendings(results, parse_input.tenant_id)

        return ExecuteOutput(
            results=results,
            total_duration_s=time.perf_counter() - t0,
            schema_version="a3.0",
        )

    # ------------------------------------------------------------------
    # Dispatch par tool
    # ------------------------------------------------------------------

    def _execute_tool_call(
        self,
        tc: ToolCall,
        parse_input: ParseInput,
        plan_output: PlanOutput,
    ) -> ToolResult:
        """Dispatch sur le bon handler en capturant les erreurs."""
        t0 = time.perf_counter()
        try:
            if tc.tool == "kg_claims":
                claims, sections = self._call_kg_claims(tc.params)
                relations: List[RelationSummary] = []
            elif tc.tool == "kg_claims_list":
                claims, sections = self._call_kg_claims_list(tc.params)
                relations = []
            elif tc.tool == "lifecycle_query":
                claims, sections, relations = self._call_lifecycle(tc.params)
            elif tc.tool == "contradiction_surface":
                claims, sections, relations = self._call_contradictions(tc.params)
            elif tc.tool == "qdrant_sections":
                claims, sections = self._call_qdrant(tc.params)
                relations = []
            elif tc.tool == "comparison_query":
                # Convention Plan v1.0 : comparison décomposé en kg_claims côté Plan,
                # donc Execute ne devrait jamais recevoir comparison_query directement.
                # Si jamais (pour V2 future), on traite comme kg_claims du subject.
                claims, sections = self._call_kg_claims(tc.params)
                relations = []
            else:
                return ToolResult(
                    sub_goal_idx=tc.sub_goal_idx,
                    tool=tc.tool,
                    coverage_signal="empty",
                    duration_s=time.perf_counter() - t0,
                    error=f"unknown_tool:{tc.tool}",
                )

            # Calcul coverage_signal
            priority = self._sub_goal_priority(plan_output, tc.sub_goal_idx, parse_input)
            coverage = self._compute_coverage_signal(len(claims), priority)

            return ToolResult(
                sub_goal_idx=tc.sub_goal_idx,
                tool=tc.tool,
                claims=claims,
                sections=sections,
                relations_traced=relations,
                coverage_signal=coverage,
                duration_s=time.perf_counter() - t0,
            )

        except Exception as exc:
            logger.exception(
                "execute: tool=%s sub_goal=%d failed", tc.tool, tc.sub_goal_idx,
            )
            return ToolResult(
                sub_goal_idx=tc.sub_goal_idx,
                tool=tc.tool,
                coverage_signal="empty",
                duration_s=time.perf_counter() - t0,
                error=str(exc)[:500],
            )

    # ------------------------------------------------------------------
    # Coverage signal (cf §2.3, P0-6)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_coverage_signal(n_claims: int, sub_goal_priority: int) -> CoverageSignal:
        if n_claims == 0:
            return "empty"
        if sub_goal_priority == 1:
            return "full" if n_claims >= 3 else "partial"
        return "full" if n_claims >= 1 else "partial"

    @staticmethod
    def _sub_goal_priority(
        plan_output: PlanOutput,
        sub_goal_idx: int,
        parse_input: ParseInput,
    ) -> int:
        """Récupère la priorité du sub_goal à partir de l'index."""
        # ParseInput ne porte pas la liste des sub_goals, mais sub_goal_idx pointe
        # dans ParseOutput.sub_goals (le ParseOutput n'est pas dispo ici).
        # On laisse une valeur sentinelle = 1 (essentiel) par défaut.
        # Le caller (execute()) peut récupérer la priorité réelle via parse_output.
        # → cette méthode sera surchargée par le caller via param injectionn.
        return 1  # sera surchargé dans execute() ci-dessous (cf _execute_with_priority)

    # ------------------------------------------------------------------
    # Handlers par tool
    # ------------------------------------------------------------------

    def _call_kg_claims(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary]]:
        rows = self._get_neo4j().execute_query(CYPHER_KG_CLAIMS, **params)
        return self._parse_claim_rows(rows)

    def _call_kg_claims_list(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary]]:
        rows = self._get_neo4j().execute_query(CYPHER_KG_CLAIMS_LIST, **params)
        return self._parse_claim_rows(rows)

    def _call_lifecycle(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary], List[RelationSummary]]:
        rows = self._get_neo4j().execute_query(CYPHER_LIFECYCLE, **params)
        claims, sections = self._parse_claim_rows(rows)
        relations = self._parse_relation_rows(rows)
        return claims, sections, relations

    def _call_contradictions(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary], List[RelationSummary]]:
        rows = self._get_neo4j().execute_query(CYPHER_CONTRADICTIONS, **params)
        claims: List[ClaimSummary] = []
        sections: List[SectionSummary] = []
        relations: List[RelationSummary] = []
        seen_claim_ids: set = set()
        for row in rows:
            for side_key, sections_key in (("a", "sections_a"), ("b", "sections_b")):
                node = row.get(side_key)
                # Neo4j Node a .get() mais n'est pas un dict (vs Python dict
                # accepté aussi pour tests mock).
                if node is not None and hasattr(node, "get"):
                    cid = node.get("claim_id")
                    if cid and cid not in seen_claim_ids:
                        seen_claim_ids.add(cid)
                        claims.append(self._claim_from_node(node))
                    for s in row.get(sections_key, []) or []:
                        if s:
                            sec = self._section_from_node(s)
                            if sec is not None:
                                sections.append(sec)
            rel = row.get("r")
            a = row.get("a")
            b = row.get("b")
            a_cid = a.get("claim_id") if a is not None and hasattr(a, "get") else None
            b_cid = b.get("claim_id") if b is not None and hasattr(b, "get") else None
            if rel is not None and a_cid and b_cid:
                rel_props = rel if hasattr(rel, "get") else {}
                relations.append(self._relation_from_data(
                    rel_type="CONTRADICTS",
                    from_id=a_cid,
                    to_id=b_cid,
                    rel_props=rel_props,
                ))
        return claims, sections, relations

    def _call_qdrant(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary]]:
        query_text = params.get("query") or ""
        tenant_id = params.get("tenant_id", "default")
        limit = int(params.get("limit", 20))
        score_threshold = params.get("score_threshold")

        vector = self._get_embedder()(query_text)
        hits = self._get_qdrant_search()(
            collection_name=self._qdrant_collection,
            query_vector=vector,
            tenant_id=tenant_id,
            limit=limit,
            score_threshold=score_threshold,
        )
        sections: List[SectionSummary] = []
        for h in hits:
            payload = h.get("payload", {}) or {}
            sec_id = payload.get("section_id") or str(h.get("id", ""))
            text = payload.get("text") or payload.get("content") or ""
            if text and len(text) > MAX_TEXT_EXCERPT_CHARS:
                text = text[:MAX_TEXT_EXCERPT_CHARS] + "..."
            sections.append(SectionSummary(
                section_id=str(sec_id),
                document_id=payload.get("document_id") or payload.get("doc_id"),
                heading=payload.get("heading") or payload.get("title"),
                text_excerpt=text or None,
                score=h.get("score"),
            ))
        # qdrant_sections ne retourne pas de Claim — retrieval brut
        return [], sections

    # ------------------------------------------------------------------
    # ConflictPending side-effect (§2.6)
    # ------------------------------------------------------------------

    def _attach_conflict_pendings(
        self,
        results: List[ToolResult],
        tenant_id: str,
    ) -> None:
        """Charge les :ConflictPending adjacents aux claims retournés."""
        all_claim_ids = set()
        for r in results:
            for c in r.claims:
                if c.claim_id:
                    all_claim_ids.add(c.claim_id)
        if not all_claim_ids:
            return

        try:
            rows = self._get_neo4j().execute_query(
                CYPHER_CONFLICT_PENDING,
                tenant_id=tenant_id,
                returned_claim_ids=list(all_claim_ids),
            )
        except Exception:
            logger.exception("execute: conflict_pending lookup failed (non-fatal)")
            return

        # Map: claim_id → list of CP qui le concernent
        cp_by_claim: Dict[str, List[ConflictPendingSummary]] = {}
        for row in rows:
            cp_node = row.get("cp") or {}
            if not isinstance(cp_node, dict):
                continue
            involved = row.get("involved_claim_ids", []) or []
            summary = ConflictPendingSummary(
                conflict_id=str(cp_node.get("conflict_id") or cp_node.get("id") or ""),
                resolution_status=cp_node.get("resolution_status", "unresolved"),
                involved_claim_ids=[str(x) for x in involved if x],
                reason=cp_node.get("reason"),
            )
            for claim_id in involved:
                cp_by_claim.setdefault(str(claim_id), []).append(summary)

        # Attacher à chaque ToolResult les CP qui touchent ses claims
        for r in results:
            seen_cp_ids: set = set()
            for c in r.claims:
                for cp in cp_by_claim.get(c.claim_id, []):
                    if cp.conflict_id in seen_cp_ids:
                        continue
                    seen_cp_ids.add(cp.conflict_id)
                    r.conflict_pendings.append(cp)

    # ------------------------------------------------------------------
    # Parsing utilities
    # ------------------------------------------------------------------

    def _parse_claim_rows(
        self, rows: List[Dict[str, Any]]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary]]:
        claims: List[ClaimSummary] = []
        all_sections: List[SectionSummary] = []
        seen_section_ids: set = set()
        for row in rows:
            # Le Cypher peut retourner soit "c" (kg_claims/kg_claims_list) soit
            # "cl" — supporter les deux + Neo4j Node (qui n'est PAS un dict mais
            # supporte .get() comme un dict).
            node = row.get("c") if "c" in row else row.get("cl")
            if node is not None and hasattr(node, "get"):
                claims.append(self._claim_from_node(node))
            for s in row.get("sections", []) or []:
                if not s:
                    continue
                sec = self._section_from_node(s)
                if sec is None:
                    continue
                if sec.section_id and sec.section_id in seen_section_ids:
                    continue
                if sec.section_id:
                    seen_section_ids.add(sec.section_id)
                all_sections.append(sec)
        return claims, all_sections

    def _parse_relation_rows(self, rows: List[Dict[str, Any]]) -> List[RelationSummary]:
        relations: List[RelationSummary] = []
        for row in rows:
            for rel in row.get("rels", []) or []:
                if not isinstance(rel, dict):
                    continue
                rtype = rel.get("type") or rel.get("_relation_type") or "EVOLUTION_OF"
                from_id = rel.get("start_claim_id") or rel.get("from_claim_id")
                to_id = rel.get("end_claim_id") or rel.get("to_claim_id")
                if not (from_id and to_id):
                    continue
                relations.append(self._relation_from_data(
                    rel_type=str(rtype),
                    from_id=str(from_id),
                    to_id=str(to_id),
                    rel_props=rel,
                ))
        return relations

    @staticmethod
    def _claim_from_node(node: Dict[str, Any]) -> ClaimSummary:
        # Mapping props Neo4j → ClaimSummary (cf POST_A38_ROOT_CAUSE_AUDIT §6).
        # Le KG stocke en `object_canonical` (dénormalisé de structured_form.object)
        # — on le mappe sur le champ Pydantic `value` (output ADR §2.3).
        # `value_normalized` reste optionnel pour cas futurs.
        return ClaimSummary(
            claim_id=str(node.get("claim_id") or node.get("id") or ""),
            subject_canonical=node.get("subject_canonical"),
            predicate=node.get("predicate"),
            value=node.get("object_canonical") or node.get("value") or node.get("object_value"),
            value_normalized=node.get("value_normalized"),
            confidence=node.get("confidence"),
            valid_from=node.get("valid_from"),
            valid_until=node.get("valid_until"),
            ingested_at=node.get("ingested_at"),
            invalidated_at=node.get("invalidated_at"),
            marker_type=node.get("marker_type"),
            source_doc_id=node.get("source_doc_id") or node.get("doc_id") or node.get("document_id"),
        )

    @staticmethod
    def _section_from_node(node: Any) -> Optional[SectionSummary]:
        # Supporte Neo4j Node (qui a .get() mais n'est PAS un dict)
        if node is None or not hasattr(node, "get"):
            return None
        sec_id = node.get("section_id") or node.get("id")
        if not sec_id:
            return None
        text = node.get("text") or node.get("content") or node.get("text_content")
        if text and len(text) > MAX_TEXT_EXCERPT_CHARS:
            text = text[:MAX_TEXT_EXCERPT_CHARS] + "..."
        return SectionSummary(
            section_id=str(sec_id),
            document_id=node.get("document_id") or node.get("doc_id"),
            heading=node.get("heading") or node.get("title"),
            text_excerpt=text or None,
        )

    @staticmethod
    def _relation_from_data(
        rel_type: str,
        from_id: str,
        to_id: str,
        rel_props: Dict[str, Any],
    ) -> RelationSummary:
        return RelationSummary(
            relation_type=rel_type,
            from_claim_id=from_id,
            to_claim_id=to_id,
            confidence=rel_props.get("confidence"),
            detected_at=rel_props.get("detected_at") or rel_props.get("created_at"),
        )


# ============================================================================
# Top-level API — priorité par sub_goal via overlay
# ============================================================================


def execute(
    parse_input: ParseInput,
    parse_output: ParseOutput,
    plan_output: PlanOutput,
    executor: Optional[Executor] = None,
) -> ExecuteOutput:
    """Exécute le plan et calibre `coverage_signal` avec la priorité réelle de ParseOutput.sub_goals.

    L'Executor de base ne connaît pas ParseOutput, donc cette fonction wrap la
    sortie pour re-calculer coverage_signal correctement avec la priorité du sub_goal.
    """
    ex = executor or Executor()
    out = ex.execute(parse_input, plan_output)

    # Recalcul coverage_signal avec la vraie priorité
    for result in out.results:
        if result.sub_goal_idx < len(parse_output.sub_goals):
            priority = parse_output.sub_goals[result.sub_goal_idx].priority
            result.coverage_signal = Executor._compute_coverage_signal(
                n_claims=len(result.claims),
                sub_goal_priority=priority,
            )
    return out
