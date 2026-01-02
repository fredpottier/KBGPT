"""
Corpus-Level Entity Resolution Pipeline

Orchestrates cross-document Entity Resolution to merge duplicate
CanonicalConcepts across the entire corpus.

Pipeline Flow (v2 with PATCH-ER-04/05/06):
1. Load all active CanonicalConcepts
2. Compute lex_keys if missing
3. Find candidates via blocking (lexical + semantic + acronym)
4. Score candidates (lex, sem, compat)
5. PATCH-ER-04: Prune candidates (Top-K + mutual best)
6. PATCH-ER-05: Decide v2 (AUTO_MERGE, PROPOSE_ONLY, REJECT)
7. PATCH-ER-06: Cap proposals (budget)
8. Execute AUTO_MERGE via MergeStore
9. Store proposals for manual review

Author: Claude Code
Date: 2026-01-01
Spec: doc/ongoing/SPEC_CORPUS_CONSOLIDATION.md + ChatGPT PATCH-ER-04/05/06
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any, Set, Tuple, NamedTuple
from collections import defaultdict

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.common.clients import get_qdrant_client
from knowbase.common.clients.embeddings import get_embedding_manager
from knowbase.config.settings import get_settings

from .types import (
    DecisionType, MergeProposal, MergeResult, MergeScores,
    CorpusERConfig, CorpusERStats, ERStatus, RejectReason
)
from .lex_utils import compute_lex_key, lex_score, extract_acronym, is_acronym_of
from .merge_store import MergeStore, get_merge_store

logger = logging.getLogger(__name__)


class ScoredCandidate(NamedTuple):
    """A scored merge candidate."""
    id_a: str
    id_b: str
    scores: MergeScores


class DecisionResult(NamedTuple):
    """Result of a merge decision."""
    source_id: str
    target_id: str
    scores: MergeScores
    decision: DecisionType
    reason: str


class CorpusERPipeline:
    """
    Entity Resolution Pipeline for corpus-level deduplication.

    Implements PATCH-ER-04/05/06 for production-ready ER.
    """

    def __init__(
        self,
        tenant_id: str = "default",
        config: Optional[CorpusERConfig] = None
    ):
        """Initialize CorpusERPipeline."""
        self.tenant_id = tenant_id
        self.config = config or CorpusERConfig()

        # Clients
        settings = get_settings()
        self.neo4j = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )
        self.qdrant = get_qdrant_client()
        self._embedding_manager = None

        # Store
        self.merge_store = get_merge_store(tenant_id)

        # Caches
        self._concepts_cache: Dict[str, Dict[str, Any]] = {}
        self._embeddings_cache: Dict[str, list] = {}

    @property
    def embedding_manager(self):
        """Lazy load embedding manager."""
        if self._embedding_manager is None:
            self._embedding_manager = get_embedding_manager()
        return self._embedding_manager

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j.driver:
            raise RuntimeError("Neo4j driver not connected")

        with self.neo4j.driver.session(database="neo4j") as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def _execute_write(self, query: str, params: Dict[str, Any]) -> Any:
        """Execute a write query."""
        if not self.neo4j.driver:
            raise RuntimeError("Neo4j driver not connected")

        with self.neo4j.driver.session(database="neo4j") as session:
            result = session.run(query, params)
            return result.single()

    def run(self, dry_run: bool = False, limit: Optional[int] = None) -> CorpusERStats:
        """
        Run corpus-level Entity Resolution.

        Args:
            dry_run: If True, don't execute merges (only generate proposals)
            limit: Max concepts to process (None = all)

        Returns:
            CorpusERStats with results
        """
        stats = CorpusERStats()
        start_time = datetime.utcnow()

        try:
            # Step 1: Load active concepts
            logger.info(f"[CorpusER] Starting corpus ER v2 (dry_run={dry_run}, limit={limit})")
            concepts = self._load_active_concepts(limit)
            stats.concepts_analyzed = len(concepts)

            if not concepts:
                logger.info("[CorpusER] No concepts to process")
                stats.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                return stats

            # Step 2: Compute/update lex_keys
            self._ensure_lex_keys(concepts)

            # Step 3: Build blocking index
            lex_key_index = self._build_lex_key_index(concepts)

            # Step 4: Find candidates via blocking
            raw_candidates = self._find_candidates(concepts, lex_key_index)
            stats.candidates_generated = len(raw_candidates)
            logger.info(f"[CorpusER] Blocking: {stats.candidates_generated} raw candidates")

            if not raw_candidates:
                logger.info("[CorpusER] No candidates found")
                stats.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                return stats

            # Step 5: Score all candidates
            scored = self._score_all_candidates(raw_candidates)
            stats.candidates_scored = len(scored)

            # Step 6: PATCH-ER-04 - Prune candidates (Top-K + mutual best)
            pruned = self._prune_candidates_topk(scored, stats)
            stats.candidates_after_mutual = len(pruned)
            logger.info(
                f"[CorpusER] Pruning: {stats.candidates_scored} -> "
                f"topK={stats.candidates_after_topk} -> "
                f"mutual={stats.candidates_after_mutual}"
            )

            # Step 7: PATCH-ER-05 - Decision v2
            decisions = self._decide_all(pruned, stats)

            # Step 8: PATCH-ER-06 - Cap proposals
            decisions = self._cap_proposals(decisions, stats)

            # Step 9: Execute decisions
            self._execute_decisions(decisions, stats, dry_run)

            # Log summary
            logger.info(f"[CorpusER] {stats.log_summary()}")
            logger.info(
                f"[CorpusER] Complete: "
                f"concepts={stats.concepts_analyzed}, "
                f"candidates={stats.candidates_generated}->{stats.candidates_after_mutual}, "
                f"auto={stats.auto_merges}, proposals={stats.proposals_created}, "
                f"rejected={stats.rejections}, dropped={stats.proposals_dropped_by_cap}"
            )

        except Exception as e:
            error_msg = f"Pipeline error: {e}"
            logger.error(f"[CorpusER] {error_msg}")
            stats.errors.append(error_msg)
            import traceback
            traceback.print_exc()

        stats.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        return stats

    # =========================================================================
    # Loading and Preparation
    # =========================================================================

    def _load_active_concepts(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Load active (non-merged) CanonicalConcepts."""
        limit_clause = f"LIMIT {limit}" if limit else ""

        query = f"""
        MATCH (c:CanonicalConcept {{tenant_id: $tenant_id}})
        WHERE c.er_status IS NULL OR c.er_status = 'STANDALONE'
        RETURN c.canonical_id AS id,
               c.canonical_name AS name,
               c.canonical_key AS key,
               c.lex_key AS lex_key,
               c.type_fine AS type_fine,
               c.concept_type AS concept_type
        ORDER BY c.canonical_name
        {limit_clause}
        """

        concepts = self._execute_query(query, {"tenant_id": self.tenant_id})
        self._concepts_cache = {c["id"]: c for c in concepts}

        logger.info(f"[CorpusER] Loaded {len(concepts)} active concepts")
        return concepts

    def _ensure_lex_keys(self, concepts: List[Dict[str, Any]]) -> int:
        """Compute and store lex_keys for concepts that don't have them."""
        to_update = []

        for concept in concepts:
            if not concept.get("lex_key"):
                lex_key = compute_lex_key(concept["name"])
                to_update.append({"id": concept["id"], "lex_key": lex_key})
                concept["lex_key"] = lex_key

        if to_update:
            query = """
            UNWIND $updates AS u
            MATCH (c:CanonicalConcept {canonical_id: u.id, tenant_id: $tenant_id})
            SET c.lex_key = u.lex_key
            """
            self._execute_write(query, {
                "updates": to_update,
                "tenant_id": self.tenant_id
            })
            logger.info(f"[CorpusER] Updated {len(to_update)} lex_keys")

        return len(to_update)

    def _build_lex_key_index(self, concepts: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Build index of lex_key -> concept_ids for blocking."""
        index: Dict[str, List[str]] = defaultdict(list)

        for concept in concepts:
            lex_key = concept.get("lex_key") or compute_lex_key(concept["name"])
            if lex_key:
                index[lex_key].append(concept["id"])

        logger.info(f"[CorpusER] Built lex_key index with {len(index)} unique keys")
        return index

    # =========================================================================
    # Blocking (Candidate Finding)
    # =========================================================================

    def _find_candidates(
        self,
        concepts: List[Dict[str, Any]],
        lex_key_index: Dict[str, List[str]]
    ) -> List[Tuple[str, str]]:
        """Find merge candidates using blocking strategies."""
        candidates: Set[Tuple[str, str]] = set()
        processed_pairs: Set[str] = set()

        # 1. Exact lex_key match
        for lex_key, ids in lex_key_index.items():
            if len(ids) > 1:
                for i, id_a in enumerate(ids):
                    for id_b in ids[i+1:]:
                        pair_key = "|".join(sorted([id_a, id_b]))
                        if pair_key not in processed_pairs:
                            candidates.add((id_a, id_b))
                            processed_pairs.add(pair_key)

        # 2. Similar lex_keys (Jaro-Winkler >= 0.85)
        lex_keys = list(lex_key_index.keys())
        for i, key_a in enumerate(lex_keys):
            for key_b in lex_keys[i+1:]:
                if abs(len(key_a) - len(key_b)) > 5:
                    continue

                sim = lex_score(key_a, key_b)
                if sim >= 0.85:
                    for id_a in lex_key_index[key_a]:
                        for id_b in lex_key_index[key_b]:
                            pair_key = "|".join(sorted([id_a, id_b]))
                            if pair_key not in processed_pairs:
                                candidates.add((id_a, id_b))
                                processed_pairs.add(pair_key)

        # 3. Acronym matching
        acronym_index: Dict[str, List[str]] = defaultdict(list)
        for concept in concepts:
            acronym = extract_acronym(concept["name"])
            if acronym:
                acronym_index[acronym].append(concept["id"])

        for acronym, acronym_ids in acronym_index.items():
            for concept in concepts:
                if concept["id"] in acronym_ids:
                    continue
                if is_acronym_of(acronym, concept["name"]):
                    for acr_id in acronym_ids:
                        pair_key = "|".join(sorted([acr_id, concept["id"]]))
                        if pair_key not in processed_pairs:
                            candidates.add((acr_id, concept["id"]))
                            processed_pairs.add(pair_key)

        return list(candidates)

    # =========================================================================
    # Scoring
    # =========================================================================

    def _score_all_candidates(
        self,
        candidates: List[Tuple[str, str]]
    ) -> List[ScoredCandidate]:
        """Score all candidates."""
        results = []

        for id_a, id_b in candidates:
            concept_a = self._concepts_cache.get(id_a)
            concept_b = self._concepts_cache.get(id_b)

            if not concept_a or not concept_b:
                continue

            scores = self._compute_scores(concept_a, concept_b)
            results.append(ScoredCandidate(id_a, id_b, scores))

        return results

    def _compute_scores(
        self,
        concept_a: Dict[str, Any],
        concept_b: Dict[str, Any]
    ) -> MergeScores:
        """Compute lex, sem, compat scores for a pair."""
        # Lexical score
        key_a = concept_a.get("lex_key") or compute_lex_key(concept_a["name"])
        key_b = concept_b.get("lex_key") or compute_lex_key(concept_b["name"])
        lex = lex_score(key_a, key_b)

        # Semantic score
        sem = self._compute_sem_score(concept_a["name"], concept_b["name"])

        # Compatibility score
        type_a = concept_a.get("type_fine") or concept_a.get("concept_type") or ""
        type_b = concept_b.get("type_fine") or concept_b.get("concept_type") or ""
        compat = self.config.get_type_compat(type_a, type_b)

        return MergeScores(lex_score=lex, sem_score=sem, compat_score=compat)

    def _compute_sem_score(self, name_a: str, name_b: str) -> float:
        """Compute semantic similarity using embeddings."""
        try:
            if name_a not in self._embeddings_cache:
                emb = self.embedding_manager.encode([name_a])[0]
                self._embeddings_cache[name_a] = emb.tolist() if emb is not None else None

            if name_b not in self._embeddings_cache:
                emb = self.embedding_manager.encode([name_b])[0]
                self._embeddings_cache[name_b] = emb.tolist() if emb is not None else None

            emb_a = self._embeddings_cache.get(name_a)
            emb_b = self._embeddings_cache.get(name_b)

            if emb_a is None or emb_b is None:
                return 0.0

            import numpy as np
            a = np.array(emb_a)
            b = np.array(emb_b)
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

        except Exception as e:
            logger.warning(f"[CorpusER] Semantic scoring failed: {e}")
            return 0.0

    # =========================================================================
    # PATCH-ER-04: Candidate Pruning (Top-K + Mutual Best)
    # =========================================================================

    def _prune_candidates_topk(
        self,
        scored: List[ScoredCandidate],
        stats: CorpusERStats
    ) -> List[ScoredCandidate]:
        """
        PATCH-ER-04: Prune candidates using Top-K + mutual best.

        For each concept, keep only TopK candidates by ranking_score.
        Then apply mutual best rule.
        """
        cfg = self.config

        # Step 1: Filter by compat and ranking_score
        filtered = [
            c for c in scored
            if c.scores.compat_score >= cfg.min_compat_for_topk
            and c.scores.ranking_score >= cfg.min_ranking_score
        ]

        # Step 2: Build TopK per concept
        topk_a: Dict[str, List[ScoredCandidate]] = defaultdict(list)
        topk_b: Dict[str, List[ScoredCandidate]] = defaultdict(list)

        for c in filtered:
            topk_a[c.id_a].append(c)
            topk_b[c.id_b].append(c)

        # Sort and keep TopK
        for concept_id in topk_a:
            topk_a[concept_id] = sorted(
                topk_a[concept_id],
                key=lambda x: x.scores.ranking_score,
                reverse=True
            )[:cfg.topk_per_concept]

        for concept_id in topk_b:
            topk_b[concept_id] = sorted(
                topk_b[concept_id],
                key=lambda x: x.scores.ranking_score,
                reverse=True
            )[:cfg.topk_per_concept]

        # Collect all TopK candidates
        topk_set: Set[Tuple[str, str]] = set()
        for candidates in topk_a.values():
            for c in candidates:
                topk_set.add((c.id_a, c.id_b))
        for candidates in topk_b.values():
            for c in candidates:
                topk_set.add((c.id_a, c.id_b))

        after_topk = [c for c in filtered if (c.id_a, c.id_b) in topk_set]
        stats.candidates_after_topk = len(after_topk)

        # Step 3: Mutual best rule
        # A pair (A,B) is kept if:
        #   - B is in topK(A) AND A is in topK(B)
        #   - OR lex >= lex_bypass_mutual (quasi-identique)

        mutual_best: List[ScoredCandidate] = []

        for c in after_topk:
            # Check if lex bypasses mutual
            if c.scores.lex_score >= cfg.lex_bypass_mutual:
                mutual_best.append(c)
                continue

            # Check mutual best
            a_in_topk_b = any(
                x.id_a == c.id_a for x in topk_b.get(c.id_b, [])
            )
            b_in_topk_a = any(
                x.id_b == c.id_b for x in topk_a.get(c.id_a, [])
            )

            if a_in_topk_b and b_in_topk_a:
                mutual_best.append(c)

        return mutual_best

    # =========================================================================
    # PATCH-ER-05: Decision v2 (gates + vraie zone REJECT)
    # =========================================================================

    def _decide_all(
        self,
        candidates: List[ScoredCandidate],
        stats: CorpusERStats
    ) -> List[DecisionResult]:
        """Apply decision v2 to all candidates."""
        results = []

        for c in candidates:
            decision, reason = self._decide_v2(c.scores)

            # Update stats based on rejection reason
            if decision == DecisionType.REJECT:
                stats.rejections += 1
                if "compat" in reason.lower():
                    stats.reject_compat_low += 1
                elif "lex_sem" in reason.lower():
                    stats.reject_lex_sem_low += 1
                else:
                    stats.reject_not_proposal += 1
                continue  # Don't add to results

            # Pick source/target
            source_id, target_id = self._pick_source_target(
                self._concepts_cache[c.id_a],
                self._concepts_cache[c.id_b]
            )

            results.append(DecisionResult(
                source_id=source_id,
                target_id=target_id,
                scores=c.scores,
                decision=decision,
                reason=reason
            ))

        return results

    def _decide_v2(self, scores: MergeScores) -> Tuple[DecisionType, str]:
        """
        PATCH-ER-05: Decision function v2.

        Returns (decision, reason).
        """
        cfg = self.config
        lex = scores.lex_score
        sem = scores.sem_score
        compat = scores.compat_score
        combined = scores.combined

        # REJECT Gate 1: compat too low
        if compat < cfg.min_compat:
            # Exception: quasi-identical lex -> PROPOSE
            if lex >= 0.985:
                return DecisionType.PROPOSE_ONLY, f"lex_exact_low_compat ({lex:.3f}/{compat:.3f})"
            return DecisionType.REJECT, f"compat_too_low ({compat:.3f})"

        # AUTO 1: quasi-identique lexical
        if lex >= cfg.auto_lex_strict:
            return DecisionType.AUTO_MERGE, f"auto_lex_strict ({lex:.3f})"

        # AUTO 2: fort accord lex + sem
        if lex >= cfg.auto_lex and sem >= cfg.auto_sem:
            return DecisionType.AUTO_MERGE, f"auto_lex_sem ({lex:.3f}/{sem:.3f})"

        # AUTO 3: combined très haut (avec guards)
        if combined >= cfg.auto_combined and sem >= 0.90 and lex >= 0.90:
            return DecisionType.AUTO_MERGE, f"auto_combined ({combined:.3f})"

        # REJECT Gate 2: lex et sem pas assez
        if sem < cfg.reject_sem_floor and lex < cfg.reject_lex_floor:
            return DecisionType.REJECT, f"lex_sem_too_low ({lex:.3f}/{sem:.3f})"

        # PROPOSE 1: lex fort + sem ok
        if lex >= cfg.propose_lex and sem >= 0.88:
            return DecisionType.PROPOSE_ONLY, f"propose_lex ({lex:.3f}/{sem:.3f})"

        # PROPOSE 2: combined élevé
        if combined >= cfg.propose_combined:
            return DecisionType.PROPOSE_ONLY, f"propose_combined ({combined:.3f})"

        # Default REJECT
        return DecisionType.REJECT, f"not_in_proposal_zone ({lex:.3f}/{sem:.3f}/{combined:.3f})"

    # =========================================================================
    # PATCH-ER-06: Cap Proposals (Budget)
    # =========================================================================

    def _cap_proposals(
        self,
        decisions: List[DecisionResult],
        stats: CorpusERStats
    ) -> List[DecisionResult]:
        """
        PATCH-ER-06: Cap proposals to MAX_PROPOSALS_TOTAL.

        Keep top proposals by combined score, drop the rest.
        """
        auto = [d for d in decisions if d.decision == DecisionType.AUTO_MERGE]
        proposals = [d for d in decisions if d.decision == DecisionType.PROPOSE_ONLY]

        if len(proposals) <= self.config.max_proposals_total:
            return decisions

        # Sort by combined score descending
        proposals.sort(key=lambda x: x.scores.combined, reverse=True)

        # Keep top N
        kept = proposals[:self.config.max_proposals_total]
        dropped = len(proposals) - len(kept)

        stats.proposals_dropped_by_cap = dropped
        logger.info(
            f"[CorpusER] Proposal cap: {len(proposals)} -> {len(kept)} "
            f"(dropped {dropped})"
        )

        return auto + kept

    # =========================================================================
    # Execution
    # =========================================================================

    def _execute_decisions(
        self,
        decisions: List[DecisionResult],
        stats: CorpusERStats,
        dry_run: bool
    ) -> None:
        """Execute merge decisions."""
        for d in decisions:
            if d.decision == DecisionType.AUTO_MERGE:
                if not dry_run:
                    result = self.merge_store.execute_merge(
                        source_id=d.source_id,
                        target_id=d.target_id,
                        lex_score=d.scores.lex_score,
                        sem_score=d.scores.sem_score,
                        compat_score=d.scores.compat_score,
                        merge_reason=d.reason
                    )
                    if result.success:
                        stats.auto_merges += 1
                        stats.edges_rewired += result.edges_rewired
                        stats.instance_of_rewired += result.instance_of_rewired
                    else:
                        stats.errors.append(result.error or "Unknown merge error")
                else:
                    stats.auto_merges += 1

            elif d.decision == DecisionType.PROPOSE_ONLY:
                proposal = MergeProposal(
                    proposal_id=f"mp_{uuid.uuid4().hex[:12]}",
                    source_id=d.source_id,
                    target_id=d.target_id,
                    source_name=self._concepts_cache[d.source_id]["name"],
                    target_name=self._concepts_cache[d.target_id]["name"],
                    lex_score=d.scores.lex_score,
                    sem_score=d.scores.sem_score,
                    compat_score=d.scores.compat_score,
                    decision=d.decision,
                    decision_reason=d.reason,
                    tenant_id=self.tenant_id,
                )
                self.merge_store.store_proposal(proposal)
                stats.proposals_created += 1

    def _pick_source_target(
        self,
        concept_a: Dict[str, Any],
        concept_b: Dict[str, Any]
    ) -> Tuple[str, str]:
        """Pick which concept is source (merged) and which is target (kept)."""
        name_a = concept_a["name"]
        name_b = concept_b["name"]

        # Prefer shorter name as target
        if len(name_a) < len(name_b):
            return concept_b["id"], concept_a["id"]
        elif len(name_b) < len(name_a):
            return concept_a["id"], concept_b["id"]

        # Same length: prefer without parentheses
        if "(" in name_a and "(" not in name_b:
            return concept_a["id"], concept_b["id"]
        elif "(" in name_b and "(" not in name_a:
            return concept_b["id"], concept_a["id"]

        # Default: alphabetical
        if name_a < name_b:
            return concept_b["id"], concept_a["id"]
        else:
            return concept_a["id"], concept_b["id"]

    def get_stats(self) -> Dict[str, Any]:
        """Get current merge statistics."""
        return self.merge_store.get_merge_stats()

    def close(self):
        """Close connections."""
        self.neo4j.close()


# Singleton
_pipeline_instance: Optional[CorpusERPipeline] = None


def get_corpus_er_pipeline(
    tenant_id: str = "default",
    config: Optional[CorpusERConfig] = None
) -> CorpusERPipeline:
    """Get or create CorpusERPipeline instance."""
    global _pipeline_instance
    if _pipeline_instance is None or _pipeline_instance.tenant_id != tenant_id:
        _pipeline_instance = CorpusERPipeline(tenant_id=tenant_id, config=config)
    return _pipeline_instance
