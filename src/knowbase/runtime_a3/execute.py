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
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from knowbase.runtime_a3.schemas import (
    AuthorityConflictSummary,
    ClaimSummary,
    ConflictPendingSummary,
    CoverageSignal,
    DocLineageSummary,
    ExecuteOutput,
    ParseInput,
    ParseOutput,
    PlanOutput,
    PredicateResolverResult,
    ProcedureChainSummary,
    RelationSummary,
    ResolverResult,
    SectionSummary,
    ToolCall,
    ToolResult,
)
from knowbase.runtime_a3.predicate_resolver import PredicateResolver
from knowbase.runtime_a3.subject_resolver import SubjectResolver

logger = logging.getLogger("knowbase.runtime_a3.execute")


# ============================================================================
# Helpers — Lucene escaping (A4.9 Hybrid retrieval BM25)
# ============================================================================

# Lucene query syntax special chars (domain-agnostic, applicable tout corpus)
_LUCENE_SPECIAL_CHARS = set('+-&|!(){}[]^"~*?:\\/')


def _escape_lucene_query(text: str) -> str:
    """Échappe les caractères spéciaux Lucene pour query full-text Neo4j.

    Sans cela, les questions contenant des codes/identifiants avec slashes,
    parenthèses, etc. (ex `/SAPAPO/OM03`, `(2021/821)`, `<P>`) cassent la query.
    """
    out_chars = []
    for ch in text:
        if ch in _LUCENE_SPECIAL_CHARS:
            out_chars.append("\\" + ch)
        else:
            out_chars.append(ch)
    return "".join(out_chars).strip()


# ============================================================================
# Cypher templates (cf ADR §4)
# ============================================================================


# §4.1 kg_claims — fact_lookup, definition_lookup
CYPHER_KG_CLAIMS = """
MATCH (c:Claim {tenant_id: $tenant_id})
WHERE c.subject_canonical = $subject
  AND ($predicate IS NULL OR c.predicate = $predicate)
  AND ($include_history OR (
        c.invalidated_at IS NULL
        AND (c.valid_from IS NULL OR date(c.valid_from) <= date($as_of))
        AND (c.valid_until IS NULL OR date(c.valid_until) >= date($as_of))))
OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(s:Section)
RETURN c, collect(s) AS sections
LIMIT 50
"""

# A4.9 (Piste A — Hybrid retrieval BM25 + ClaimFilter vector existant)
# Bottleneck A4.7 verrouillé : filtre exact `c.subject_canonical = $subject` rate
# 18/18 questions (retrieval recall=0.00). Mode hybride contourne le filtre strict :
# BM25 full-text sur `c.text` via index `claim_text_search` (déjà ONLINE) →
# top-50 candidats → ClaimFilter A3.11 cosine sur question prend le relai top-5.
# Domain-agnostic strict : BM25 capture identifiants formels (codes, refs) sur tout corpus.
# Activé via env V6_HYBRID_RETRIEVAL=1.
CYPHER_KG_CLAIMS_HYBRID = """
CALL db.index.fulltext.queryNodes('claim_text_search', $query_text)
YIELD node AS c, score AS bm25_score
WHERE c.tenant_id = $tenant_id
  AND ($include_history OR (
        c.invalidated_at IS NULL
        AND (c.valid_from IS NULL OR date(c.valid_from) <= date($as_of))
        AND (c.valid_until IS NULL OR date(c.valid_until) >= date($as_of))))
WITH c, bm25_score
ORDER BY bm25_score DESC
LIMIT 50
OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(s:Section)
RETURN c, collect(s) AS sections
"""

# A4.9-ter (23/05/2026) — RRF hybrid : BM25 + vector parallèles, fusion rank-based.
# Pattern littérature 2026 (cf doc A47 §3.3) : recall +48% vs BM25 seul.
# Requirement : Vector Index `claim_embedding_idx` (1024d cosine) ONLINE.
CYPHER_KG_CLAIMS_BM25_ONLY = """
CALL db.index.fulltext.queryNodes('claim_text_search', $query_text)
YIELD node AS c, score AS bm25_score
WHERE c.tenant_id = $tenant_id
  AND ($include_history OR (
        c.invalidated_at IS NULL
        AND (c.valid_from IS NULL OR date(c.valid_from) <= date($as_of))
        AND (c.valid_until IS NULL OR date(c.valid_until) >= date($as_of))))
RETURN c.claim_id AS claim_id, bm25_score AS score
ORDER BY bm25_score DESC
LIMIT 50
"""

CYPHER_KG_CLAIMS_VECTOR_ONLY = """
CALL db.index.vector.queryNodes('claim_embedding_idx', 50, $query_embedding)
YIELD node AS c, score AS vec_score
WHERE c.tenant_id = $tenant_id
  AND ($include_history OR (
        c.invalidated_at IS NULL
        AND (c.valid_from IS NULL OR date(c.valid_from) <= date($as_of))
        AND (c.valid_until IS NULL OR date(c.valid_until) >= date($as_of))))
RETURN c.claim_id AS claim_id, vec_score AS score
ORDER BY vec_score DESC
"""

# Cypher pour charger les claims fusionnés par RRF (après calcul rank Python)
CYPHER_LOAD_CLAIMS_BY_IDS = """
MATCH (c:Claim {tenant_id: $tenant_id})
WHERE c.claim_id IN $claim_ids
OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(s:Section)
RETURN c, collect(s) AS sections
"""

# §4.2 kg_claims_list — list_enumeration
CYPHER_KG_CLAIMS_LIST = """
MATCH (c:Claim {tenant_id: $tenant_id})
WHERE ($subject_filter IS NULL OR c.subject_canonical = $subject_filter)
  AND ($predicate IS NULL OR c.predicate = $predicate)
  AND ($include_history OR (
        c.invalidated_at IS NULL
        AND (c.valid_from IS NULL OR date(c.valid_from) <= date($as_of))
        AND (c.valid_until IS NULL OR date(c.valid_until) >= date($as_of))))
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

# Side-effect lignée de DOCUMENT (#443) — chaîne SUPERSEDES_DOC des docs retrouvés
CYPHER_DOC_LINEAGE = """
UNWIND $doc_ids AS did
MATCH (d:Document {tenant_id: $tenant_id, doc_id: did})
WHERE (d)-[:SUPERSEDES_DOC]-()
OPTIONAL MATCH (head:Document)-[:SUPERSEDES_DOC*0..]->(d)
  WHERE NOT ( (:Document)-[:SUPERSEDES_DOC]->(head) )
WITH did, d, collect(DISTINCT head.reg_key) AS heads
OPTIONAL MATCH (d)-[:SUPERSEDES_DOC*1..]->(old:Document)
WITH did, d, heads, collect(DISTINCT old.reg_key) AS superseded
OPTIONAL MATCH (d)-[:SUPERSEDES_DOC]->(direct:Document)<-[:DECLARES_SUPERSESSION]-(cl:Claim)
RETURN did AS doc_id, d.reg_key AS reg_key, heads, superseded,
       collect(DISTINCT cl.text)[..3] AS evidence,
       collect(DISTINCT cl.claim_id)[..3] AS evidence_claim_ids
"""

# Side-effect contradictions inter-autorités (#440) — CONTRADICTS adjacents aux claims retrouvés
CYPHER_CLAIM_CONTRADICTIONS = """
UNWIND $claim_ids AS cid
MATCH (a:Claim {tenant_id: $tenant_id, claim_id: cid})-[r:CONTRADICTS]-(b:Claim {tenant_id: $tenant_id})
WHERE a.invalidated_at IS NULL AND b.invalidated_at IS NULL
  AND (NOT $confirmed_only
       OR r.adjudication IS NULL
       OR r.adjudication = 'CONFIRMED')
RETURN a.claim_id AS a_id, a.doc_id AS a_doc, a.subject_canonical AS subj, a.text AS a_text,
       b.claim_id AS b_id, b.doc_id AS b_doc, b.text AS b_text, r.confidence AS conf
"""
# NOTE adjudication (#446, 06/06/2026) : avec V6_AUTHORITY_CONFLICT_CONFIRMED_ONLY=1
# (défaut), seules les arêtes adjugées CONFIRMED (vraie contradiction vérifiée en
# contexte) — ou pas encore adjugées (corpus sans pipeline d'adjudication) — sont
# surfacées. Les arêtes démotées (DIFFERENT_SCOPE/COMPLEMENTARY/EQUIVALENT) ne
# portent JAMAIS le bandeau divergence (éval 06/06 : 281 paires → 95% démotées,
# le bandeau affichait des faux positifs PERSUASIFS).

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

# Phase B (P1.5) — chaîne procédurale. Pour les claims retrouvés portant un
# procedure_id, récupère la :Procedure + séquence ordonnée de :ProcedureStep
# (autoritative) + prérequis. Les entry_claim_ids = claims retrouvés membres.
CYPHER_PROCEDURE_CHAIN = """
MATCH (c:Claim)
WHERE c.claim_id IN $returned_claim_ids AND c.procedure_id IS NOT NULL
WITH collect(DISTINCT c.procedure_id) AS proc_ids
UNWIND proc_ids AS pid
MATCH (p:Procedure {procedure_id: pid})
OPTIONAL MATCH (p)-[hs:HAS_STEP]->(s:ProcedureStep)
WITH p, pid, s ORDER BY coalesce(s.step_number, hs.order)
WITH p, pid, collect(DISTINCT {order: coalesce(s.step_number, 0), action: s.action}) AS steps
OPTIONAL MATCH (entry:Claim {procedure_id: pid})
WHERE entry.claim_id IN $returned_claim_ids
RETURN p, pid AS procedure_id, steps,
       collect(DISTINCT entry.claim_id) AS entry_claim_ids
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
        subject_resolver: Optional[SubjectResolver] = None,
        subject_resolver_enabled: Optional[bool] = None,
        predicate_resolver: Optional[PredicateResolver] = None,
        predicate_resolver_enabled: Optional[bool] = None,
    ):
        self._neo4j = neo4j_client
        self._qdrant_search = qdrant_search
        self._embedder = embedder
        self._qdrant_collection = qdrant_collection
        self._subject_resolver = subject_resolver
        self._predicate_resolver = predicate_resolver
        # Toggles env var pour rollback safe (cf A3.9 / A3.9-bis)
        if subject_resolver_enabled is None:
            self._subject_resolver_enabled = (
                os.getenv("V6_SUBJECT_RESOLVER_ENABLED", "1") == "1"
            )
        else:
            self._subject_resolver_enabled = subject_resolver_enabled
        if predicate_resolver_enabled is None:
            self._predicate_resolver_enabled = (
                os.getenv("V6_PREDICATE_RESOLVER_ENABLED", "1") == "1"
            )
        else:
            self._predicate_resolver_enabled = predicate_resolver_enabled
        # Trace par sub_goal du subject résolu (pour observability)
        # Map sub_goal_idx → ResolverResult / PredicateResolverResult
        self._last_resolutions: Dict[int, ResolverResult] = {}
        self._last_predicate_resolutions: Dict[int, PredicateResolverResult] = {}

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

    def _get_subject_resolver(self) -> SubjectResolver:
        """Lazy init du subject resolver (réutilise les mêmes clients neo4j/qdrant/embedder)."""
        if self._subject_resolver is None:
            self._subject_resolver = SubjectResolver(
                neo4j_client=self._neo4j,
                qdrant_search=self._qdrant_search,
                embedder=self._embedder,
                qdrant_collection=self._qdrant_collection,
            )
        return self._subject_resolver

    def _get_predicate_resolver(self) -> PredicateResolver:
        """Lazy init du predicate resolver (A3.9-bis)."""
        if self._predicate_resolver is None:
            # Embedder predicates : batch List[str] → List[List[float]]
            embedder_batch: Optional[Callable] = None
            if self._embedder is not None:
                # self._embedder est typé (text: str) -> List[float]
                # On wrappe pour accepter une liste
                _per_text = self._embedder
                embedder_batch = lambda texts: [_per_text(t) for t in texts]
            self._predicate_resolver = PredicateResolver(
                neo4j_client=self._neo4j,
                embedder=embedder_batch,
            )
        return self._predicate_resolver

    def _build_query_text_for_call(self, tc: "ToolCall", parse_input: "ParseInput") -> str:
        """A4.9-bis — construit query Lucene depuis le sub_goal correspondant au ToolCall.

        Stratégie :
        - Si V6_HYBRID_QUERY_MODE=sub_goal (défaut) : utilise subject+predicate+object_hint
          du sub_goal. Si tous vides, fallback question entière.
        - Si V6_HYBRID_QUERY_MODE=question : utilise toujours parse_input.question.

        Domain-agnostic : utilise uniquement les champs structurés du sub_goal,
        pas de regex ou règle métier.
        """
        mode = os.getenv("V6_HYBRID_QUERY_MODE", "sub_goal").lower()
        question = (parse_input.question or "").strip()

        if mode == "question":
            return question

        # Mode sub_goal : récupérer le sub_goal depuis _current_parse_output
        po = getattr(self, "_current_parse_output", None)
        if po is None:
            return question
        try:
            sub_goal = po.sub_goals[tc.sub_goal_idx]
        except (AttributeError, IndexError):
            return question

        parts: List[str] = []
        if sub_goal.subject_canonical:
            parts.append(str(sub_goal.subject_canonical))
        if sub_goal.predicate_hint:
            # UPPER_SNAKE → "lower words" pour matching Lucene plus naturel
            parts.append(str(sub_goal.predicate_hint).replace("_", " ").lower())
        if sub_goal.object_hint:
            parts.append(str(sub_goal.object_hint))

        if not parts:
            return question
        return " ".join(parts).strip()

    def _aspect_emphasized_query(self, tc: "ToolCall") -> Optional[str]:
        """Requête EMPHASÉE sur l'aspect pour les questions multi-aspect.

        Quand ≥2 sous-buts partagent le même subject (ex « Que disent les docs sur X,
        incluant A, B, C »), requêter avec la question entière (ou subject+aspect) laisse
        le SUJET dominant noyer l'aspect → tous les sous-buts récupèrent les mêmes claims
        génériques. Ici on up-weight l'aspect (predicate_hint/object_hint) du sous-but
        (répété + en tête, sujet en contexte de scope) pour remonter les claims de CET
        aspect. Retourne None si pas multi-aspect (→ comportement habituel conservé).

        Toggle V6_ASPECT_EMPHASIS (défaut "1"). Domain-agnostic.
        """
        if os.getenv("V6_ASPECT_EMPHASIS", "1") != "1":
            return None
        po = getattr(self, "_current_parse_output", None)
        if po is None:
            return None
        try:
            sub_goals = po.sub_goals
            sg = sub_goals[tc.sub_goal_idx]
        except (AttributeError, IndexError):
            return None
        subj = (sg.subject_canonical or "").strip()
        if not subj:
            return None
        # multi-aspect : au moins 2 sous-buts partagent ce subject
        same = sum(1 for x in sub_goals if (x.subject_canonical or "").strip() == subj)
        if same < 2:
            return None
        aspect_parts: List[str] = []
        if sg.predicate_hint:
            aspect_parts.append(str(sg.predicate_hint).replace("_", " ").lower())
        if getattr(sg, "object_hint", None):
            aspect_parts.append(str(sg.object_hint))
        aspect = " ".join(aspect_parts).strip()
        if not aspect:
            return None
        # Up-weight l'aspect (en tête + répété), sujet en contexte de scope.
        return f"{aspect} {aspect} {subj}".strip()

    def _resolve_subject_for_call(
        self,
        tc: ToolCall,
        subject_param_key: str = "subject",
    ) -> Dict[str, Any]:
        """Applique le subject resolver sur les params d'un ToolCall, retourne les
        params éventuellement modifiés.

        Si le resolver est désactivé OU si le subject est absent du params OU si
        le resolver abstient (confidence trop basse), retourne les params inchangés
        (graceful fallback).
        """
        params = dict(tc.params)

        if not self._subject_resolver_enabled:
            # On résout quand même le predicate (toggle indépendant)
            return self._resolve_predicate_in_params(
                params, sub_goal_idx=tc.sub_goal_idx,
            )

        original_subject = params.get(subject_param_key)
        if not original_subject:
            # Pas de subject à résoudre, mais on traite le predicate
            return self._resolve_predicate_in_params(
                params, sub_goal_idx=tc.sub_goal_idx,
            )

        predicate_hint = params.get("predicate")
        tenant_id = params.get("tenant_id", "default")

        try:
            result = self._get_subject_resolver().resolve(
                user_subject=original_subject,
                tenant_id=tenant_id,
                predicate_hint=predicate_hint,
            )
        except Exception:
            logger.exception(
                "execute: subject_resolver failed for tool=%s sub_goal=%d, "
                "falling back to original subject",
                tc.tool, tc.sub_goal_idx,
            )
            # Le subject échoue mais on poursuit avec le predicate_resolver
            return self._resolve_predicate_in_params(
                params, sub_goal_idx=tc.sub_goal_idx,
            )

        # Trace pour observability
        self._last_resolutions[tc.sub_goal_idx] = result

        if result.resolved is None:
            logger.info(
                "execute: subject_resolver abstained for '%s' (reason=%s); "
                "fallback to original subject",
                original_subject, result.abstain_reason,
            )
            # On garde le subject brut, mais on traite le predicate
            return self._resolve_predicate_in_params(
                params, sub_goal_idx=tc.sub_goal_idx,
            )

        if result.resolved != original_subject:
            logger.info(
                "execute: subject_resolver mapped '%s' -> '%s' (conf=%.2f, method=%s)",
                original_subject, result.resolved, result.confidence, result.method,
            )
            params[subject_param_key] = result.resolved

        # A3.9-bis : résoudre aussi le predicate_hint (user-words → KG UPPER_SNAKE)
        # si présent. Le toggle env est indépendant du subject resolver.
        params = self._resolve_predicate_in_params(
            params, sub_goal_idx=tc.sub_goal_idx,
        )
        return params

    def _resolve_predicate_in_params(
        self,
        params: Dict[str, Any],
        sub_goal_idx: int,
    ) -> Dict[str, Any]:
        """Applique le predicate_resolver sur params["predicate"] si présent.

        Comportement fail-open : si le resolver abstient (low confidence),
        on POSITIONNE params["predicate"]=None (= no filter en Cypher).
        Cela évite de filtrer sur un predicate user-words qui ne matchera
        jamais le canonical KG (cf cause racine post-A3.9 smoke).

        Si le toggle est désactivé, le predicate brut du Parse est conservé.
        """
        if not self._predicate_resolver_enabled:
            return params
        original_pred = params.get("predicate")
        # Si déjà None/absent, rien à faire
        if original_pred is None or not str(original_pred).strip():
            return params

        tenant_id = params.get("tenant_id", "default")
        try:
            result = self._get_predicate_resolver().resolve(
                predicate_hint=original_pred,
                tenant_id=tenant_id,
            )
        except Exception:
            logger.exception(
                "execute: predicate_resolver failed for sub_goal=%d, "
                "falling back to None (no filter)",
                sub_goal_idx,
            )
            # Fail-open : pas de filter
            params["predicate"] = None
            return params

        # Trace pour observability
        self._last_predicate_resolutions[sub_goal_idx] = result

        if result.resolved is None:
            logger.info(
                "execute: predicate_resolver abstained on '%s' (method=%s) → predicate=None (no filter)",
                original_pred, result.method,
            )
            params["predicate"] = None
            return params

        if result.resolved != original_pred:
            logger.info(
                "execute: predicate_resolver mapped '%s' -> '%s' (conf=%.2f, method=%s)",
                original_pred, result.resolved, result.confidence, result.method,
            )
            params["predicate"] = result.resolved
        return params

    # ------------------------------------------------------------------
    # Top-level
    # ------------------------------------------------------------------

    def execute(
        self,
        parse_input: ParseInput,
        plan_output: PlanOutput,
        parse_output: Optional["ParseOutput"] = None,
    ) -> ExecuteOutput:
        """Exécute tous les ToolCall + side-effect ConflictPending.

        A4.9-bis : parse_output optionnel pour permettre query BM25 par sub_goal.
        """
        t0 = time.perf_counter()
        results: List[ToolResult] = []
        # A4.9-bis : stocker temporairement parse_output pour accès depuis _build_query_text_for_call
        self._current_parse_output = parse_output

        # 1) Exécuter les ToolCall — en parallèle (C-latence 29/05/2026).
        # B1 (planner multi-aspect) génère N sous-buts → N ToolCall indépendants ;
        # les lancer en parallèle (I/O-bound : Neo4j + embeddings) réduit fortement
        # la latence (p95). Ordre des résultats préservé par index. Toggle de repli
        # V6_EXECUTE_PARALLEL=0 → séquentiel.
        tool_calls = plan_output.tool_calls
        parallel = (
            os.getenv("V6_EXECUTE_PARALLEL", "1") == "1" and len(tool_calls) > 1
        )
        if parallel:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            indexed: List[Tuple[int, ToolResult]] = []
            max_workers = min(len(tool_calls), 6)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(self._execute_tool_call, tc, parse_input, plan_output): i
                    for i, tc in enumerate(tool_calls)
                }
                for fut in as_completed(futures):
                    indexed.append((futures[fut], fut.result()))
            results = [r for _, r in sorted(indexed, key=lambda x: x[0])]
        else:
            for tc in tool_calls:
                results.append(self._execute_tool_call(tc, parse_input, plan_output))

        # 2) Side-effect §2.6 : charger les :ConflictPending adjacents aux claims retournés
        self._attach_conflict_pendings(results, parse_input.tenant_id)

        # 3) Side-effect Phase B (P1.5) : charger la chaîne procédurale complète
        # pour les claims retrouvés membres d'une :Procedure (toggle, off défaut).
        if os.getenv("V6_PROCEDURE_CHAIN", "0") == "1":
            self._attach_procedure_chains(results, parse_input.tenant_id)

        # 4) Side-effect lignée de document (#443) : chaîne SUPERSEDES_DOC en vigueur.
        if os.getenv("V6_LINEAGE_SURFACE", "1") == "1":
            self._attach_lineage(results, parse_input.tenant_id)

        # 5) Side-effect contradictions inter-autorités (#440) : FAA vs EASA, etc.
        if os.getenv("V6_AUTHORITY_CONFLICT", "1") == "1":
            self._attach_authority_conflicts(results, parse_input.tenant_id)

        return ExecuteOutput(
            results=results,
            total_duration_s=time.perf_counter() - t0,
            schema_version="a3.0",
        )

    # ------------------------------------------------------------------
    # Dispatch par tool
    # ------------------------------------------------------------------

    def _include_history_for_call(self, tc: ToolCall) -> bool:
        """ADR_RESOLUTION_CONTRADICTIONS §5.2 (moitié runtime) — portée temporelle.

        Les claims invalidés par lignée (`invalidated_at` + `valid_until`) sont
        l'HISTOIRE du corpus : ils doivent rester accessibles aux questions
        lifecycle/évolution/point-in-time, sinon le runtime abstient à tort sur
        « comment X a-t-il évolué ? » (constaté au bench du 05/06 : 5 abstentions
        à tort lifecycle après la résolution par lignée).
        """
        po = getattr(self, "_current_parse_output", None)
        try:
            sg = po.sub_goals[tc.sub_goal_idx] if po and po.sub_goals else None
        except (IndexError, AttributeError):
            sg = None
        if sg is None:
            return False
        return sg.kind == "lifecycle_trace" or sg.time_filter in ("evolution", "as_of")

    def _execute_tool_call(
        self,
        tc: ToolCall,
        parse_input: ParseInput,
        plan_output: PlanOutput,
    ) -> ToolResult:
        """Dispatch sur le bon handler en capturant les erreurs."""
        t0 = time.perf_counter()
        try:
            # A3.9 : résoudre le subject_canonical avant les Cypher KG.
            # kg_claims_list utilise `subject_filter`, les autres `subject`.
            # qdrant_sections n'a pas de subject (passe par query texte).
            if tc.tool == "kg_claims":
                resolved_params = self._resolve_subject_for_call(tc, "subject")
                # A4.9 — query_text injecté pour mode hybride BM25.
                # A4.9-bis (23/05/2026) : query par sub_goal au lieu de question entière.
                # Si Parse a produit un sub_goal précis (subject/predicate/object_hint),
                # on construit query Lucene depuis ces champs → recherche plus ciblée
                # qu'avec la question complète. Fallback question si sub_goal vide.
                # Multi-aspect → requête emphasée sur l'aspect ; sinon subject+aspect habituel.
                resolved_params["query_text"] = (
                    self._aspect_emphasized_query(tc)
                    or self._build_query_text_for_call(tc, parse_input)
                )
                resolved_params["include_history"] = self._include_history_for_call(tc)
                claims, sections = self._call_kg_claims(resolved_params)
                relations: List[RelationSummary] = []
            elif tc.tool == "kg_claims_list":
                resolved_params = self._resolve_subject_for_call(tc, "subject_filter")
                # P3.1 (28/05/2026) — les réponses-liste sont dispersées sur des
                # claims atomiques aux subjects/predicates hétérogènes ; l'exact-match
                # subject_canonical+predicate ne peut pas les rassembler (recall 0,
                # cf probe p1_probe_list_retrieval). On requête sur la question entière
                # (signal sémantique le plus riche pour énumérer) en mode hybride.
                # EXCEPTION multi-aspect : si ≥2 sous-buts partagent le subject, la question
                # entière est subject-dominée et tous les aspects récupèrent les mêmes claims
                # génériques → on emphase l'aspect du sous-but (cf _aspect_emphasized_query).
                resolved_params["query_text"] = (
                    self._aspect_emphasized_query(tc)
                    or (parse_input.question or "").strip()
                )
                resolved_params["include_history"] = self._include_history_for_call(tc)
                claims, sections = self._call_kg_claims_list(resolved_params)
                relations = []
            elif tc.tool == "lifecycle_query":
                resolved_params = self._resolve_subject_for_call(tc, "subject")
                claims, sections, relations = self._call_lifecycle(resolved_params)
            elif tc.tool == "contradiction_surface":
                resolved_params = self._resolve_subject_for_call(tc, "subject")
                claims, sections, relations = self._call_contradictions(resolved_params)
            elif tc.tool == "qdrant_sections":
                # Pas de subject (query texte direct), pas de resolver
                claims, sections = self._call_qdrant(tc.params)
                relations = []
            elif tc.tool == "comparison_query":
                # Convention Plan v1.0 : comparison décomposé en kg_claims côté Plan,
                # donc Execute ne devrait jamais recevoir comparison_query directement.
                # Si jamais (pour V2 future), on traite comme kg_claims du subject.
                resolved_params = self._resolve_subject_for_call(tc, "subject")
                resolved_params["include_history"] = self._include_history_for_call(tc)
                claims, sections = self._call_kg_claims(resolved_params)
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
        # A4.9 — toggle Hybrid retrieval. Valeurs supportées :
        #   "0" / unset : legacy filtre exact subject_canonical
        #   "1" / "bm25" : BM25 only via fulltext (A4.9, A4.9-bis)
        #   "rrf" : RRF parallel BM25 + vector cosine (A4.9-ter winner A4.11)
        #   "rrf_ce" : RRF + Cross-Encoder re-rank top-50 (A4.12 Étape B)
        #   "vector" : Vector-only direct via Neo4j Vector Index (Choix 2)
        mode = os.getenv("V6_HYBRID_RETRIEVAL", "0").lower()
        if mode == "vector":
            return self._call_kg_claims_vector_only(params)
        if mode == "rrf_ce":
            return self._call_kg_claims_rrf_ce(params)
        if mode == "rrf":
            return self._call_kg_claims_rrf(params)
        if mode in ("1", "bm25"):
            return self._call_kg_claims_hybrid(params)
        rows = self._get_neo4j().execute_query(CYPHER_KG_CLAIMS, **params)
        return self._parse_claim_rows(rows)

    def _call_kg_claims_rrf_ce(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary]]:
        """A4.12 Étape B — RRF parallèle + Cross-Encoder re-rank.

        Étape 1 : reuse `_call_kg_claims_rrf` pour obtenir top-50 RRF fusionnés.
        Étape 2 : cross-encoder BGE-reranker-v2-m3 (multilingue) sur (question, claim_text)
                  pour les 50 → re-tri par rerank score descendant.

        Pattern littérature 2026 : cross-encoder re-rank ajoute +5-10pp NDCG@10
        après hybrid retrieval. Domain-agnostic (modèle multilingue 100+ langues).
        """
        # Étape 1 : RRF top-50
        claims, sections = self._call_kg_claims_rrf(params)
        if not claims:
            return claims, sections

        query_text = (params.get("query_text") or "").strip()
        if not query_text:
            return claims, sections

        # Étape 2 : Cross-Encoder re-rank
        try:
            from knowbase.common.clients.reranker import get_cross_encoder
            ce_model_name = os.getenv("V6_CE_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
            # device=None → auto-détection (CUDA si dispo, sinon CPU). Le conteneur
            # app a accès au GPU ; cohérent avec le chemin synthesize ClaimReranker.
            ce = get_cross_encoder(model_name=ce_model_name, device=None)
        except Exception as e:
            logger.warning("rrf_ce: cross-encoder load failed (%s), fallback RRF only", e)
            return claims, sections

        # Construire les pairs (question, claim_text) — utiliser le texte le plus riche
        # disponible : c.text > verbatim_quote > subject+predicate+value concat
        def _claim_to_rerank_text(c: ClaimSummary) -> str:
            # extra=allow → c peut avoir des champs additionnels du KG
            extras = c.model_dump()
            for key in ("text", "claim_text_full", "verbatim_quote", "passage_text"):
                val = extras.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
            parts: List[str] = []
            if c.subject_canonical:
                parts.append(c.subject_canonical)
            if c.predicate:
                parts.append(c.predicate.replace("_", " ").lower())
            v = c.value or c.value_normalized
            if v:
                parts.append(str(v))
            return " ".join(parts).strip()

        rerank_texts = [_claim_to_rerank_text(c) for c in claims]
        valid_idx = [i for i, t in enumerate(rerank_texts) if t]
        if not valid_idx:
            return claims, sections
        pairs = [(query_text, rerank_texts[i]) for i in valid_idx]
        try:
            scores = ce.predict(pairs)
        except Exception as e:
            logger.warning("rrf_ce: cross-encoder predict failed (%s), fallback RRF only", e)
            return claims, sections

        # Re-tri descendant par score CE
        idx_score = list(zip(valid_idx, (float(s) for s in scores)))
        idx_score.sort(key=lambda x: x[1], reverse=True)
        # Réordonner claims selon le nouveau classement
        reordered_claims = [claims[i] for i, _ in idx_score]
        # On garde sections inchangées (associées par claim_id côté ClaimFilter)
        return reordered_claims, sections

    def _call_kg_claims_vector_only(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary]]:
        """Choix 2 — Vector-first retrieval direct (bypass entity linking).

        Pattern Direct Fact Retrieval (arxiv 2305.12416). Élimine 2 maillons fragiles
        (SubjectResolver + PredicateResolver). Domain-agnostic : embedding cosine
        fonctionne identiquement quel que soit le domaine du corpus.
        """
        query_text = (params.get("query_text") or "").strip()
        if not query_text:
            return self._call_kg_claims_hybrid(params)
        try:
            emb = self._get_embedder()(f"query: {query_text}")
        except Exception:
            logger.warning("vector_only: embedder failed, fallback hybrid")
            return self._call_kg_claims_hybrid(params)
        try:
            rows = self._get_neo4j().execute_query(
                CYPHER_KG_CLAIMS_VECTOR_ONLY,
                query_embedding=emb,
                tenant_id=params["tenant_id"],
                as_of=params["as_of"],
                include_history=params.get("include_history", False),
            )
        except Exception as e:
            logger.warning("vector_only: vector query failed (%s), fallback hybrid", e)
            return self._call_kg_claims_hybrid(params)
        # Charger full claims pour les IDs retournés
        claim_ids = [r["claim_id"] for r in rows]
        if not claim_ids:
            return [], []
        load_rows = self._get_neo4j().execute_query(
            CYPHER_LOAD_CLAIMS_BY_IDS,
            claim_ids=claim_ids, tenant_id=params["tenant_id"],
        )
        return self._parse_claim_rows(load_rows)

    def _call_kg_claims_rrf(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary]]:
        """A4.9-ter — RRF parallèle BM25 + vector cosine via Neo4j Vector Index.

        Strategy :
        1. Encode query_text en vector e5-large
        2. BM25 top-50 + Vector top-50 (Cypher parallel)
        3. RRF fusion k=60 → top-50 unifié
        4. Load full claims via batch Cypher
        5. ClaimFilter A3.11 prend le relai top-5 final
        """
        query_text = (params.get("query_text") or "").strip()
        if not query_text:
            return self._call_kg_claims_hybrid(params)

        # 1. Encode query (e5-large convention : "query: " prefix)
        try:
            emb = self._get_embedder()(f"query: {query_text}")
        except Exception:
            logger.warning("rrf: embedder failed, fallback BM25-only")
            return self._call_kg_claims_hybrid(params)

        escaped = _escape_lucene_query(query_text)
        base_params = {
            "tenant_id": params["tenant_id"],
            "as_of": params["as_of"],
            "include_history": params.get("include_history", False),
        }

        # 2. BM25 + Vector queries (séquentiel pour simplicité — Neo4j n'autorise
        # pas le parallel intra-tx ; mais latence faible donc OK)
        try:
            bm25_rows = self._get_neo4j().execute_query(
                CYPHER_KG_CLAIMS_BM25_ONLY,
                query_text=escaped, **base_params,
            )
        except Exception as e:
            logger.warning("rrf: BM25 failed (%s), fallback hybrid", e)
            return self._call_kg_claims_hybrid(params)

        try:
            vec_rows = self._get_neo4j().execute_query(
                CYPHER_KG_CLAIMS_VECTOR_ONLY,
                query_embedding=emb, **base_params,
            )
        except Exception as e:
            logger.warning("rrf: vector query failed (%s), fallback to BM25-only", e)
            vec_rows = []

        # 3. RRF fusion k=60 (paramètre standard littérature)
        rrf_k = 60
        scores: Dict[str, float] = {}
        for rank_i, r in enumerate(bm25_rows):
            cid = r["claim_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank_i + 1)
        for rank_i, r in enumerate(vec_rows):
            cid = r["claim_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank_i + 1)
        # Top-50 par score RRF descendant
        sorted_ids = [cid for cid, _ in sorted(scores.items(), key=lambda x: -x[1])[:50]]
        if not sorted_ids:
            return [], []

        # 4. Charger full claims pour les top-50 IDs
        rows = self._get_neo4j().execute_query(
            CYPHER_LOAD_CLAIMS_BY_IDS,
            claim_ids=sorted_ids, tenant_id=params["tenant_id"],
        )
        return self._parse_claim_rows(rows)

    def _call_kg_claims_hybrid(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary]]:
        """Mode hybride A4.9 — BM25 full-text sur claim.text via Neo4j fulltext index.

        Params attendus : query_text, tenant_id, as_of. Subject/predicate ignorés
        (le ClaimFilter cosine post-hoc fait le re-ranking sémantique).
        """
        query_text = (params.get("query_text") or "").strip()
        if not query_text:
            logger.warning("hybrid: empty query_text, falling back to legacy exact-match")
            rows = self._get_neo4j().execute_query(CYPHER_KG_CLAIMS, **params)
            return self._parse_claim_rows(rows)
        # Échapper Lucene chars : + - && || ! ( ) { } [ ] ^ " ~ * ? : \ /
        escaped = _escape_lucene_query(query_text)
        hybrid_params = {
            "query_text": escaped,
            "tenant_id": params["tenant_id"],
            "as_of": params["as_of"],
            "include_history": params.get("include_history", False),
        }
        try:
            rows = self._get_neo4j().execute_query(CYPHER_KG_CLAIMS_HYBRID, **hybrid_params)
        except Exception as e:
            logger.warning("hybrid: BM25 query failed (%s), falling back to legacy", e)
            rows = self._get_neo4j().execute_query(CYPHER_KG_CLAIMS, **params)
        return self._parse_claim_rows(rows)

    def _call_kg_claims_list(
        self, params: Dict[str, Any]
    ) -> Tuple[List[ClaimSummary], List[SectionSummary]]:
        # P3.1 (28/05/2026) — même politique de retrieval que kg_claims (cf A4.9).
        # list_enumeration via exact-match subject_canonical+predicate ratait
        # systématiquement les items dispersés (recall 0, cf probe). En mode hybride
        # on requête claim.text (BM25 + vector RRF) pour agréger les claims atomiques
        # formant la liste, quels que soient leurs subject/predicate individuels.
        mode = os.getenv("V6_HYBRID_RETRIEVAL", "0").lower()
        query_text = (params.get("query_text") or "").strip()
        if query_text and mode != "0":
            if mode == "vector":
                return self._call_kg_claims_vector_only(params)
            if mode == "rrf_ce":
                return self._call_kg_claims_rrf_ce(params)
            if mode == "rrf":
                return self._call_kg_claims_rrf(params)
            if mode in ("1", "bm25"):
                return self._call_kg_claims_hybrid(params)
        # Legacy exact-match (mode=0 ou query_text absent) : query_text n'est pas un
        # paramètre Cypher de CYPHER_KG_CLAIMS_LIST, on le retire avant l'appel.
        legacy_params = {k: v for k, v in params.items() if k != "query_text"}
        rows = self._get_neo4j().execute_query(CYPHER_KG_CLAIMS_LIST, **legacy_params)
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
    # Procedure chain side-effect (Phase B, P1.5)
    # ------------------------------------------------------------------

    def _attach_procedure_chains(
        self,
        results: List[ToolResult],
        tenant_id: str,
    ) -> None:
        """Charge la chaîne procédurale des claims retrouvés membres d'une Procedure.

        Pour tout claim retrouvé avec procedure_id, récupère la :Procedure +
        sa séquence ordonnée de :ProcedureStep (autoritative) + prérequis, et
        l'attache au ToolResult contenant un claim de cette procédure.
        """
        all_claim_ids = set()
        for r in results:
            for c in r.claims:
                if c.claim_id:
                    all_claim_ids.add(c.claim_id)
        if not all_claim_ids:
            return

        try:
            rows = self._get_neo4j().execute_query(
                CYPHER_PROCEDURE_CHAIN,
                returned_claim_ids=list(all_claim_ids),
            )
        except Exception:
            logger.exception("execute: procedure_chain lookup failed (non-fatal)")
            return

        # Map: procedure_id → summary + son ensemble d'entry_claim_ids
        chains: Dict[str, ProcedureChainSummary] = {}
        for row in rows:
            pid = row.get("procedure_id")
            if not pid:
                continue
            p_node = row.get("p") or {}
            p_get = p_node.get if hasattr(p_node, "get") else (lambda *_: None)
            # Étapes ordonnées (filtre les steps vides)
            ordered_steps = []
            for s in row.get("steps", []) or []:
                if not isinstance(s, dict):
                    continue
                action = s.get("action")
                if not action:
                    continue
                ordered_steps.append({"order": int(s.get("order") or 0), "action": action})
            ordered_steps.sort(key=lambda x: x["order"])
            prereqs = p_get("prerequisites") or []
            entry_ids = [str(x) for x in (row.get("entry_claim_ids", []) or []) if x]
            chains[pid] = ProcedureChainSummary(
                procedure_id=str(pid),
                name=p_get("name"),
                goal=p_get("goal"),
                ordered_steps=ordered_steps,
                prerequisites=[str(x) for x in prereqs if x],
                entry_claim_ids=entry_ids,
            )

        if not chains:
            return

        # claim_id → procedure_id (pour attacher au bon ToolResult)
        claim_to_proc: Dict[str, str] = {}
        for pid, chain in chains.items():
            for cid in chain.entry_claim_ids:
                claim_to_proc[cid] = pid

        for r in results:
            seen_pids: set = set()
            for c in r.claims:
                pid = claim_to_proc.get(c.claim_id)
                if pid and pid not in seen_pids:
                    seen_pids.add(pid)
                    r.procedure_chains.append(chains[pid])

    # ------------------------------------------------------------------
    # Lignée de document side-effect (#443)
    # ------------------------------------------------------------------

    def _attach_lineage(self, results: List[ToolResult], tenant_id: str) -> None:
        """Attache la chaîne SUPERSEDES_DOC (version en vigueur + superséd és +
        preuve) pour les documents des claims retrouvés qui participent à une lignée.
        """
        doc_ids = {
            c.source_doc_id
            for r in results
            for c in r.claims
            if getattr(c, "source_doc_id", None)
        }
        if not doc_ids:
            return
        try:
            rows = self._get_neo4j().execute_query(
                CYPHER_DOC_LINEAGE, tenant_id=tenant_id, doc_ids=list(doc_ids)
            )
        except Exception:
            logger.exception("execute: doc lineage lookup failed (non-fatal)")
            return

        lineages: Dict[str, DocLineageSummary] = {}
        for row in rows:
            did = row.get("doc_id")
            if not did:
                continue
            reg_key = row.get("reg_key")
            heads = [h for h in (row.get("heads") or []) if h]
            in_force = heads[0] if heads else reg_key
            lineages[did] = DocLineageSummary(
                doc_id=did,
                reg_key=reg_key,
                in_force_reg_key=in_force,
                is_in_force=(in_force == reg_key),
                superseded=[s for s in (row.get("superseded") or []) if s],
                evidence=[t for t in (row.get("evidence") or []) if t][:3],
                evidence_claim_ids=[c for c in (row.get("evidence_claim_ids") or []) if c][:3],
            )
        if not lineages:
            return
        for r in results:
            seen: set = set()
            for c in r.claims:
                did = getattr(c, "source_doc_id", None)
                if did and did in lineages and did not in seen:
                    seen.add(did)
                    r.doc_lineages.append(lineages[did])

    # ------------------------------------------------------------------
    # Contradictions inter-autorités side-effect (#440)
    # ------------------------------------------------------------------

    def _attach_authority_conflicts(self, results: List[ToolResult], tenant_id: str) -> None:
        """Attache les contradictions CONTRADICTS où les deux claims proviennent
        de documents d'AUTORITÉS différentes (ex. FAA vs EASA), avec attribution.
        """
        from knowbase.relations.explicit_lineage_detector import regulatory_authority

        claim_ids = {c.claim_id for r in results for c in r.claims if c.claim_id}
        if not claim_ids:
            return
        try:
            rows = self._get_neo4j().execute_query(
                CYPHER_CLAIM_CONTRADICTIONS, tenant_id=tenant_id, claim_ids=list(claim_ids),
                confirmed_only=os.getenv("V6_AUTHORITY_CONFLICT_CONFIRMED_ONLY", "1") == "1",
            )
        except Exception:
            logger.exception("execute: authority conflict lookup failed (non-fatal)")
            return

        by_claim: Dict[str, List[AuthorityConflictSummary]] = {}
        seen_pairs: set = set()
        for row in rows:
            aut_a = regulatory_authority(row.get("a_doc"))
            aut_b = regulatory_authority(row.get("b_doc"))
            if not (aut_a and aut_b and aut_a != aut_b):
                continue  # on n'expose QUE les contradictions inter-autorités
            pair_key = tuple(sorted([row.get("a_id") or "", row.get("b_id") or ""]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            summ = AuthorityConflictSummary(
                subject=row.get("subj"),
                authority_a=aut_a,
                doc_a=row.get("a_doc"),
                text_a=(row.get("a_text") or "")[:300],
                authority_b=aut_b,
                doc_b=row.get("b_doc"),
                text_b=(row.get("b_text") or "")[:300],
                confidence=row.get("conf"),
            )
            by_claim.setdefault(row.get("a_id"), []).append(summ)
        if not by_claim:
            return
        for r in results:
            seen: set = set()
            for c in r.claims:
                for summ in by_claim.get(c.claim_id, []):
                    k = (summ.doc_a, summ.doc_b, summ.text_a[:40])
                    if k in seen:
                        continue
                    seen.add(k)
                    r.authority_conflicts.append(summ)

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
        #
        # FIX BUG #1 — Option ε (24/05/2026) :
        #   On expose aussi `text` (verbatim Claim) en extra Pydantic (extra="allow")
        #   pour que le cross-encoder reranker (P2.2) puisse l'utiliser. Sans ce
        #   champ, le reranker tombait sur un fallback "subject+predicate+value"
        #   qui ne contenait pas l'identifiant clé (ex: WWI Monitor → CG5Z).
        #   Confirmé sur HUM_0028 : avec c.text, le claim CG5Z = BM25 rank 1 +
        #   Vector rank 1 ; sans c.text, le CE ne peut pas matcher la question
        #   sur l'identifiant rare. Pattern littérature 2026 : cross-encoder
        #   doit voir le verbatim complet, pas un triplet reconstruit minimaliste.
        #
        # Conversion temporels Neo4j → Python natif (ADR §7) : avec
        # include_history=True, les claims invalidés remontent désormais et
        # leur `invalidated_at` (posé par lineage_resolution via datetime())
        # arrive en neo4j.time.DateTime que Pydantic rejette. Avant l'ADR ce
        # champ était toujours NULL côté retrieval (claims filtrés).
        def _native(v: Any) -> Any:
            return v.to_native() if hasattr(v, "to_native") else v

        return ClaimSummary(
            claim_id=str(node.get("claim_id") or node.get("id") or ""),
            subject_canonical=node.get("subject_canonical"),
            predicate=node.get("predicate"),
            value=node.get("object_canonical") or node.get("value") or node.get("object_value"),
            value_normalized=node.get("value_normalized"),
            confidence=node.get("confidence"),
            valid_from=_native(node.get("valid_from")),
            valid_until=_native(node.get("valid_until")),
            ingested_at=_native(node.get("ingested_at")),
            invalidated_at=_native(node.get("invalidated_at")),
            marker_type=node.get("marker_type"),
            source_doc_id=node.get("source_doc_id") or node.get("doc_id") or node.get("document_id"),
            # Extra (Pydantic extra="allow") — verbatim Claim text pour cross-encoder
            text=node.get("text"),
            # Extra — statut lifecycle (ADR §7.D/§7.F) : 'withdrawn' = marqueur
            # ÉPISTÉMIQUE (doc porteur annulé, successeur muet) → caveat en synthèse
            # + tie-breaker de rang, JAMAIS un filtre dur.
            lifecycle_status=node.get("lifecycle_status_current"),
            lifecycle_reason=node.get("lifecycle_status_reason"),
            invalidation_reason=node.get("invalidation_reason"),
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
        # Coercition temporels Neo4j → datetime Python natif : les props de
        # relation (detected_at, posé via datetime() en Cypher) arrivent en
        # neo4j.time.DateTime que Pydantic (Optional[datetime]) rejette →
        # ValidationError qui faisait perdre le surfaçage de contradictions
        # sur certaines questions (cf #463).
        detected = rel_props.get("detected_at") or rel_props.get("created_at")
        if detected is not None and hasattr(detected, "to_native"):
            detected = detected.to_native()
        return RelationSummary(
            relation_type=rel_type,
            from_claim_id=from_id,
            to_claim_id=to_id,
            confidence=rel_props.get("confidence"),
            detected_at=detected,
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
    out = ex.execute(parse_input, plan_output, parse_output=parse_output)

    # Recalcul coverage_signal avec la vraie priorité
    for result in out.results:
        if result.sub_goal_idx < len(parse_output.sub_goals):
            priority = parse_output.sub_goals[result.sub_goal_idx].priority
            result.coverage_signal = Executor._compute_coverage_signal(
                n_claims=len(result.claims),
                sub_goal_priority=priority,
            )
    return out
