"""
Phase 2.12 - Candidate Finder

Generates merge candidates using blocking strategies to avoid O(N²).

Blocking Pipeline:
1. Lexical: acronym families, normalized prefix
2. Semantic: embedding similarity > 0.75 (Qdrant)

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple, Any

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.common.clients import get_qdrant_client
from knowbase.common.clients.embeddings import get_embedding_manager
from knowbase.config.settings import get_settings

from .types import ConceptType, MergeCandidate, SignalBreakdown
from .config import BLOCKING_CONFIG

logger = logging.getLogger(__name__)


def normalize_for_blocking(text: str) -> str:
    """Normalize text for blocking comparison."""
    if not text:
        return ""
    # Lowercase, remove punctuation, normalize whitespace
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = ' '.join(text.split())
    return text


def extract_acronym(text: str) -> Optional[str]:
    """Extract acronym if text looks like an acronym."""
    text = text.strip()
    # Check if all uppercase and short
    if text.isupper() and 2 <= len(text) <= 10:
        return text
    # Check if parenthetical acronym: "General Data Protection Regulation (GDPR)"
    match = re.search(r'\(([A-Z]{2,10})\)$', text)
    if match:
        return match.group(1)
    return None


def is_acronym_of(acronym: str, full_text: str) -> bool:
    """Check if acronym matches full text."""
    if not acronym or not full_text:
        return False

    acronym = acronym.upper()
    words = full_text.split()

    # Simple check: first letters
    if len(words) >= len(acronym):
        initials = ''.join(w[0].upper() for w in words if w)
        if acronym in initials:
            return True

    return False


class CandidateFinder:
    """
    Finds merge candidates using blocking strategies.

    Blocking reduces O(N²) to O(N * K) where K << N.
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        qdrant_client: Optional[QdrantClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialize CandidateFinder.

        Args:
            neo4j_client: Neo4j client
            qdrant_client: Qdrant client
            tenant_id: Tenant ID
        """
        if neo4j_client is None:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        self.neo4j_client = neo4j_client
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.tenant_id = tenant_id
        self._embedding_manager = None

        # Acronym lookup table (built lazily)
        self._acronym_index: Dict[str, List[str]] = {}
        self._prefix_index: Dict[str, List[str]] = {}

    @property
    def embedding_manager(self):
        """Lazy load embedding manager."""
        if self._embedding_manager is None:
            self._embedding_manager = get_embedding_manager()
        return self._embedding_manager

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def _load_concepts(self, concept_type: Optional[ConceptType] = None) -> List[Dict[str, Any]]:
        """Load concepts from Neo4j."""
        type_filter = ""
        if concept_type:
            type_filter = "AND c.concept_type = $concept_type"

        query = f"""
        MATCH (c:CanonicalConcept {{tenant_id: $tenant_id}})
        WHERE c.status IN ['active', 'PROVISIONAL'] {type_filter}
        RETURN c.canonical_id AS id,
               c.canonical_name AS name,
               c.concept_type AS type,
               c.surface_forms AS surface_forms,
               c.definition AS definition
        """
        params = {"tenant_id": self.tenant_id}
        if concept_type:
            params["concept_type"] = concept_type.value

        return self._execute_query(query, params)

    def _build_blocking_indices(self, concepts: List[Dict[str, Any]]) -> None:
        """Build blocking indices for fast lookup."""
        self._acronym_index.clear()
        self._prefix_index.clear()

        for concept in concepts:
            concept_id = concept["id"]
            name = concept["name"] or ""

            # Acronym index
            acronym = extract_acronym(name)
            if acronym:
                if acronym not in self._acronym_index:
                    self._acronym_index[acronym] = []
                self._acronym_index[acronym].append(concept_id)

            # Prefix index (first 3+ chars)
            normalized = normalize_for_blocking(name)
            if len(normalized) >= BLOCKING_CONFIG["prefix_min_length"]:
                prefix = normalized[:BLOCKING_CONFIG["prefix_min_length"]]
                if prefix not in self._prefix_index:
                    self._prefix_index[prefix] = []
                self._prefix_index[prefix].append(concept_id)

        logger.info(
            f"[CandidateFinder] Built indices: "
            f"{len(self._acronym_index)} acronym groups, "
            f"{len(self._prefix_index)} prefix groups"
        )

    def _find_lexical_candidates(
        self,
        concept: Dict[str, Any],
        all_concepts: Dict[str, Dict[str, Any]]
    ) -> Set[str]:
        """Find candidates using lexical blocking."""
        candidates = set()
        concept_id = concept["id"]
        name = concept["name"] or ""

        # Acronym blocking
        if BLOCKING_CONFIG["enable_acronym_blocking"]:
            acronym = extract_acronym(name)
            if acronym and acronym in self._acronym_index:
                for other_id in self._acronym_index[acronym]:
                    if other_id != concept_id:
                        candidates.add(other_id)

            # Check if this concept is an expansion of an acronym
            for acr, ids in self._acronym_index.items():
                if is_acronym_of(acr, name):
                    for other_id in ids:
                        if other_id != concept_id:
                            candidates.add(other_id)

        # Prefix blocking
        if BLOCKING_CONFIG["enable_prefix_blocking"]:
            normalized = normalize_for_blocking(name)
            if len(normalized) >= BLOCKING_CONFIG["prefix_min_length"]:
                prefix = normalized[:BLOCKING_CONFIG["prefix_min_length"]]
                if prefix in self._prefix_index:
                    for other_id in self._prefix_index[prefix]:
                        if other_id != concept_id:
                            candidates.add(other_id)

        return candidates

    def _find_semantic_candidates(
        self,
        concept_id: str,
        concept_name: str,
        concept_type: str,
        collection_name: str = "concepts_proto"
    ) -> Set[str]:
        """Find candidates using semantic similarity (Qdrant)."""
        candidates = set()

        # v1.1: Use type-specific top-K caps
        type_upper = concept_type.upper()
        top_k = BLOCKING_CONFIG.get("top_k_by_type", {}).get(
            type_upper,
            BLOCKING_CONFIG["qdrant_top_k"]  # fallback
        )

        try:
            # Get embedding for concept name
            embedding = self.embedding_manager.encode([concept_name])[0]
            if embedding is None:
                return candidates

            # Search for similar concepts using vector
            results = self.qdrant_client.search(
                collection_name=collection_name,
                query_vector=embedding.tolist(),
                limit=top_k,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=self.tenant_id)
                        ),
                        FieldCondition(
                            key="concept_type",
                            match=MatchValue(value=concept_type)
                        )
                    ]
                ),
                score_threshold=BLOCKING_CONFIG["embedding_threshold"]
            )

            for hit in results:
                other_id = hit.payload.get("neo4j_concept_id")
                if other_id and other_id != concept_id:
                    candidates.add(other_id)

        except Exception as e:
            logger.warning(f"[CandidateFinder] Qdrant search failed: {e}")

        return candidates

    def find_candidates(
        self,
        concept_type: Optional[ConceptType] = None,
        target_concept_id: Optional[str] = None
    ) -> List[MergeCandidate]:
        """
        Find merge candidates using blocking.

        Args:
            concept_type: Filter by concept type (None = all types)
            target_concept_id: Find candidates for specific concept only

        Returns:
            List of merge candidates
        """
        logger.info(
            f"[CandidateFinder] Finding candidates "
            f"(type={concept_type}, target={target_concept_id})"
        )

        # Load concepts
        concepts = self._load_concepts(concept_type)
        logger.info(f"[CandidateFinder] Loaded {len(concepts)} concepts")

        if not concepts:
            return []

        # Build lookup
        concepts_by_id = {c["id"]: c for c in concepts}

        # Build blocking indices
        self._build_blocking_indices(concepts)

        # Find candidates
        candidates_map: Dict[str, MergeCandidate] = {}
        processed_pairs: Set[str] = set()

        # If targeting specific concept
        if target_concept_id:
            concepts_to_process = [concepts_by_id.get(target_concept_id)]
            concepts_to_process = [c for c in concepts_to_process if c]
        else:
            concepts_to_process = concepts

        for concept in concepts_to_process:
            concept_id = concept["id"]
            concept_name = concept["name"] or ""
            concept_type_str = concept["type"] or "ENTITY"

            # Find lexical candidates
            lexical_candidates = self._find_lexical_candidates(concept, concepts_by_id)

            # Find semantic candidates
            semantic_candidates = self._find_semantic_candidates(
                concept_id, concept_name, concept_type_str
            )

            # Combine candidates
            all_candidate_ids = lexical_candidates | semantic_candidates

            for other_id in all_candidate_ids:
                # Skip if already processed (pair is order-independent)
                pair_key = "|".join(sorted([concept_id, other_id]))
                if pair_key in processed_pairs:
                    continue
                processed_pairs.add(pair_key)

                other = concepts_by_id.get(other_id)
                if not other:
                    continue

                # Skip if different types
                if concept["type"] != other["type"]:
                    continue

                # Create candidate
                candidate = self._create_candidate(
                    concept, other,
                    is_lexical=other_id in lexical_candidates,
                    is_semantic=other_id in semantic_candidates
                )
                candidates_map[pair_key] = candidate

        candidates = list(candidates_map.values())
        logger.info(
            f"[CandidateFinder] Found {len(candidates)} candidates "
            f"(from {len(processed_pairs)} pairs)"
        )

        return candidates

    def _create_candidate(
        self,
        concept_a: Dict[str, Any],
        concept_b: Dict[str, Any],
        is_lexical: bool,
        is_semantic: bool
    ) -> MergeCandidate:
        """Create a merge candidate from two concepts."""
        name_a = concept_a["name"] or ""
        name_b = concept_b["name"] or ""

        # Check for exact match
        has_exact = normalize_for_blocking(name_a) == normalize_for_blocking(name_b)

        # Check for acronym match
        has_acronym = (
            is_acronym_of(name_a, name_b) or
            is_acronym_of(name_b, name_a)
        )

        # Find shared surface forms
        forms_a = set(concept_a.get("surface_forms") or [])
        forms_b = set(concept_b.get("surface_forms") or [])
        shared_forms = list(forms_a & forms_b)

        # Initial signals (will be refined by scorer)
        signals = SignalBreakdown(
            exact_match=1.0 if has_exact else 0.0,
            acronym_expansion=1.0 if has_acronym else 0.0,
            alias_overlap=len(shared_forms) / max(len(forms_a | forms_b), 1) if forms_a or forms_b else 0.0,
        )

        # Rough initial score
        initial_score = signals.weighted_score()

        return MergeCandidate(
            concept_a_id=concept_a["id"],
            concept_b_id=concept_b["id"],
            concept_a_name=name_a,
            concept_b_name=name_b,
            concept_type=ConceptType.from_string(concept_a["type"]),
            similarity_score=initial_score,
            signals=signals,
            has_exact_match=has_exact,
            has_acronym_match=has_acronym,
            has_definition_match=False,  # To be computed by scorer
            shared_surface_forms=shared_forms,
        )

    def find_candidates_for_new_concept(
        self,
        concept_id: str,
        concept_name: str,
        concept_type: ConceptType
    ) -> List[MergeCandidate]:
        """
        Find merge candidates for a newly added concept.

        Called after document ingestion to check for duplicates.

        Args:
            concept_id: New concept ID
            concept_name: New concept name
            concept_type: Concept type

        Returns:
            List of merge candidates
        """
        return self.find_candidates(
            concept_type=concept_type,
            target_concept_id=concept_id
        )


# Singleton
_finder_instance: Optional[CandidateFinder] = None


def get_candidate_finder(tenant_id: str = "default") -> CandidateFinder:
    """Get or create CandidateFinder instance."""
    global _finder_instance
    if _finder_instance is None or _finder_instance.tenant_id != tenant_id:
        _finder_instance = CandidateFinder(tenant_id=tenant_id)
    return _finder_instance
