"""
Phase 2.12 v1.1 - Pair Similarity Scorer

Computes pairwise similarity scores using cross-encoder and lexical signals.

Signal Pipeline:
1. Lexical: exact match, acronym, alias overlap
2. Semantic: embedding cosine similarity
3. Cross-encoder: pairwise relevance score (with cheap guards v1.1)

v1.1 Improvements:
- Cheap guards before cross-encoder to avoid expensive calls on low-quality pairs
- Early exit when lexical signals are definitive

Author: Claude Code
Date: 2025-12-26
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple, Dict, Any

import numpy as np

from knowbase.common.clients.embeddings import get_embedding_manager
from knowbase.config.settings import get_settings

from .types import MergeCandidate, SignalBreakdown
from .score_cache import ScoreCache, get_score_cache
from .config import CROSS_ENCODER_CONFIG

logger = logging.getLogger(__name__)


# =============================================================================
# v1.1: Cheap Guards Configuration
# =============================================================================

CHEAP_GUARDS_CONFIG = {
    # Minimum combined tokens to consider cross-encoder
    "min_tokens_total": 4,

    # Minimum common token ratio (Jaccard on tokens)
    "min_common_token_ratio": 0.2,

    # If lexical signals exceed this, skip cross-encoder (already high confidence)
    "skip_if_lexical_above": 0.95,

    # If embedding similarity below this, skip cross-encoder (too different)
    "skip_if_embedding_below": 0.5,

    # Stopwords to ignore in token analysis
    "stopwords": {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
        "be", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "shall", "can",
        "le", "la", "les", "un", "une", "des", "du", "de", "et", "ou",
        "en", "dans", "sur", "pour", "par", "avec", "sans", "est", "sont",
    },
}


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())


def extract_meaningful_tokens(text: str) -> set:
    """Extract tokens excluding stopwords (for cheap guards)."""
    if not text:
        return set()
    normalized = normalize_text(text)
    tokens = set(normalized.split())
    stopwords = CHEAP_GUARDS_CONFIG["stopwords"]
    return tokens - stopwords


def compute_exact_match(name_a: str, name_b: str) -> float:
    """Check if two names are exactly the same (normalized)."""
    norm_a = normalize_text(name_a)
    norm_b = normalize_text(name_b)
    if not norm_a or not norm_b:
        return 0.0
    return 1.0 if norm_a == norm_b else 0.0


def extract_acronym(text: str) -> Optional[str]:
    """Extract acronym from text."""
    text = text.strip()
    # All uppercase and short
    if text.isupper() and 2 <= len(text) <= 10:
        return text
    # Parenthetical: "General Data Protection Regulation (GDPR)"
    match = re.search(r'\(([A-Z]{2,10})\)$', text)
    if match:
        return match.group(1)
    return None


def is_acronym_expansion(acronym: str, expansion: str) -> bool:
    """Check if expansion matches acronym."""
    if not acronym or not expansion:
        return False

    acronym = acronym.upper()
    words = [w for w in expansion.split() if w and len(w) > 1]

    if len(words) < len(acronym):
        return False

    # Check first letters
    initials = ''.join(w[0].upper() for w in words)
    return acronym in initials


def compute_acronym_score(name_a: str, name_b: str) -> float:
    """Compute acronym-expansion match score."""
    acr_a = extract_acronym(name_a)
    acr_b = extract_acronym(name_b)

    # Both are acronyms and match
    if acr_a and acr_b and acr_a == acr_b:
        return 1.0

    # One is acronym, other is expansion
    if acr_a and is_acronym_expansion(acr_a, name_b):
        return 1.0
    if acr_b and is_acronym_expansion(acr_b, name_a):
        return 1.0

    return 0.0


def compute_alias_overlap(forms_a: List[str], forms_b: List[str]) -> float:
    """Compute overlap between surface forms."""
    if not forms_a or not forms_b:
        return 0.0

    set_a = set(normalize_text(f) for f in forms_a if f)
    set_b = set(normalize_text(f) for f in forms_b if f)

    if not set_a or not set_b:
        return 0.0

    intersection = set_a & set_b
    union = set_a | set_b

    return len(intersection) / len(union) if union else 0.0


class PairSimilarityScorer:
    """
    Computes similarity scores for merge candidates.

    Uses:
    - Lexical signals (exact, acronym, alias)
    - Semantic signals (embedding similarity)
    - Cross-encoder (optional, for high-precision scoring)
    """

    def __init__(
        self,
        use_cross_encoder: bool = True,
        cache: Optional[ScoreCache] = None
    ):
        """
        Initialize PairSimilarityScorer.

        Args:
            use_cross_encoder: Whether to use cross-encoder (slower but more accurate)
            cache: Score cache (uses default if None)
        """
        self.use_cross_encoder = use_cross_encoder
        self.cache = cache or get_score_cache()
        self._cross_encoder = None
        self._embedding_manager = None

    @property
    def cross_encoder(self):
        """Lazy load cross-encoder model."""
        if self._cross_encoder is None and self.use_cross_encoder:
            try:
                from sentence_transformers import CrossEncoder
                model_name = CROSS_ENCODER_CONFIG["model_name"]
                self._cross_encoder = CrossEncoder(model_name)
                logger.info(f"[PairScorer] Loaded cross-encoder: {model_name}")
            except Exception as e:
                logger.warning(f"[PairScorer] Could not load cross-encoder: {e}")
                self._cross_encoder = False  # Mark as unavailable
        return self._cross_encoder if self._cross_encoder else None

    @property
    def embedding_manager(self):
        """Get embedding manager."""
        if self._embedding_manager is None:
            self._embedding_manager = get_embedding_manager()
        return self._embedding_manager

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding for text."""
        try:
            embedding = self.embedding_manager.encode([text])[0]
            return embedding
        except Exception as e:
            logger.warning(f"[PairScorer] Embedding failed: {e}")
            return None

    def _compute_embedding_similarity(
        self,
        name_a: str,
        name_b: str
    ) -> float:
        """Compute cosine similarity between embeddings."""
        emb_a = self._get_embedding(name_a)
        emb_b = self._get_embedding(name_b)

        if emb_a is None or emb_b is None:
            return 0.0

        # Cosine similarity
        norm_a = np.linalg.norm(emb_a)
        norm_b = np.linalg.norm(emb_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(np.dot(emb_a, emb_b) / (norm_a * norm_b))

    def _should_use_cross_encoder(
        self,
        name_a: str,
        name_b: str,
        lexical_score: float,
        embedding_sim: float
    ) -> Tuple[bool, str]:
        """
        v1.1: Cheap guards before expensive cross-encoder call.

        Returns:
            Tuple of (should_use, skip_reason)
        """
        # Guard 1: Skip if lexical signals are already definitive
        if lexical_score >= CHEAP_GUARDS_CONFIG["skip_if_lexical_above"]:
            return False, "lexical_sufficient"

        # Guard 2: Skip if embedding similarity is too low
        if embedding_sim < CHEAP_GUARDS_CONFIG["skip_if_embedding_below"]:
            return False, "embedding_too_low"

        # Guard 3: Check meaningful token overlap
        tokens_a = extract_meaningful_tokens(name_a)
        tokens_b = extract_meaningful_tokens(name_b)

        total_tokens = len(tokens_a) + len(tokens_b)
        if total_tokens < CHEAP_GUARDS_CONFIG["min_tokens_total"]:
            return False, "too_few_tokens"

        # Guard 4: Check common token ratio (Jaccard)
        if tokens_a and tokens_b:
            intersection = tokens_a & tokens_b
            union = tokens_a | tokens_b
            jaccard = len(intersection) / len(union) if union else 0

            if jaccard < CHEAP_GUARDS_CONFIG["min_common_token_ratio"]:
                return False, "low_token_overlap"

        return True, ""

    def _compute_cross_encoder_score(
        self,
        name_a: str,
        name_b: str,
        definition_a: Optional[str] = None,
        definition_b: Optional[str] = None
    ) -> float:
        """Compute cross-encoder pairwise score."""
        if not self.cross_encoder:
            return 0.0

        try:
            # Prepare texts
            text_a = name_a
            text_b = name_b
            if definition_a:
                text_a = f"{name_a}: {definition_a}"
            if definition_b:
                text_b = f"{name_b}: {definition_b}"

            # Score
            score = self.cross_encoder.predict([(text_a, text_b)])
            # Normalize to [0, 1] (cross-encoder outputs can vary)
            score = float(score[0])
            # Sigmoid normalization
            score = 1 / (1 + np.exp(-score))
            return score
        except Exception as e:
            logger.warning(f"[PairScorer] Cross-encoder failed: {e}")
            return 0.0

    def score_candidate(
        self,
        candidate: MergeCandidate,
        surface_forms_a: Optional[List[str]] = None,
        surface_forms_b: Optional[List[str]] = None,
        definition_a: Optional[str] = None,
        definition_b: Optional[str] = None,
        use_cache: bool = True
    ) -> MergeCandidate:
        """
        Score a merge candidate.

        Args:
            candidate: The merge candidate
            surface_forms_a: Surface forms for concept A
            surface_forms_b: Surface forms for concept B
            definition_a: Definition for concept A
            definition_b: Definition for concept B
            use_cache: Whether to use score cache

        Returns:
            Updated MergeCandidate with computed scores
        """
        # Check cache
        if use_cache:
            cached = self.cache.get(candidate.concept_a_id, candidate.concept_b_id)
            if cached:
                score, signals = cached
                candidate.similarity_score = score
                candidate.signals = signals
                return candidate

        # Compute signals
        signals = self._compute_signals(
            candidate.concept_a_name,
            candidate.concept_b_name,
            surface_forms_a or [],
            surface_forms_b or [],
            definition_a,
            definition_b
        )

        # Compute final score
        final_score = signals.weighted_score()

        # Update candidate
        candidate.signals = signals
        candidate.similarity_score = final_score
        candidate.has_exact_match = signals.exact_match > 0.9
        candidate.has_acronym_match = signals.acronym_expansion > 0.9
        candidate.has_definition_match = self._check_definition_match(
            definition_a, definition_b
        )

        # Cache result
        if use_cache:
            self.cache.set(
                candidate.concept_a_id,
                candidate.concept_b_id,
                final_score,
                signals
            )

        return candidate

    def _compute_signals(
        self,
        name_a: str,
        name_b: str,
        forms_a: List[str],
        forms_b: List[str],
        definition_a: Optional[str],
        definition_b: Optional[str]
    ) -> SignalBreakdown:
        """Compute all similarity signals."""
        # Lexical signals
        exact = compute_exact_match(name_a, name_b)
        acronym = compute_acronym_score(name_a, name_b)
        alias = compute_alias_overlap(forms_a, forms_b)

        # Semantic signals
        embedding_sim = self._compute_embedding_similarity(name_a, name_b)

        # v1.1: Cross-encoder with cheap guards
        cross_score = 0.0
        if self.use_cross_encoder:
            # Compute lexical aggregate for guard decision
            lexical_max = max(exact, acronym, alias)

            # Check cheap guards before expensive cross-encoder call
            should_use, skip_reason = self._should_use_cross_encoder(
                name_a, name_b, lexical_max, embedding_sim
            )

            if should_use:
                cross_score = self._compute_cross_encoder_score(
                    name_a, name_b, definition_a, definition_b
                )
            else:
                logger.debug(
                    f"[PairScorer] Skipped cross-encoder for '{name_a[:30]}' vs "
                    f"'{name_b[:30]}': {skip_reason}"
                )

        return SignalBreakdown(
            exact_match=exact,
            acronym_expansion=acronym,
            alias_overlap=alias,
            embedding_similarity=embedding_sim,
            cross_encoder_score=cross_score,
            same_document=0.0  # Not used for identity (per spec)
        )

    def _check_definition_match(
        self,
        definition_a: Optional[str],
        definition_b: Optional[str]
    ) -> bool:
        """Check if definitions match (for CONCEPT type AUTO conditions)."""
        if not definition_a or not definition_b:
            return False

        # Simple fingerprint: first 100 chars normalized
        fp_a = normalize_text(definition_a[:100])
        fp_b = normalize_text(definition_b[:100])

        if not fp_a or not fp_b:
            return False

        # High similarity threshold
        return fp_a == fp_b or self._compute_embedding_similarity(
            definition_a, definition_b
        ) > 0.95

    def score_batch(
        self,
        candidates: List[MergeCandidate],
        concepts_data: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> List[MergeCandidate]:
        """
        Score a batch of candidates.

        Args:
            candidates: List of merge candidates
            concepts_data: Optional dict with concept metadata (forms, definitions)

        Returns:
            List of scored candidates
        """
        if not candidates:
            return []

        logger.info(f"[PairScorer] Scoring {len(candidates)} candidates")

        scored = []
        for candidate in candidates:
            # Get metadata if available
            forms_a = []
            forms_b = []
            def_a = None
            def_b = None

            if concepts_data:
                data_a = concepts_data.get(candidate.concept_a_id, {})
                data_b = concepts_data.get(candidate.concept_b_id, {})
                forms_a = data_a.get("surface_forms", [])
                forms_b = data_b.get("surface_forms", [])
                def_a = data_a.get("definition")
                def_b = data_b.get("definition")

            scored_candidate = self.score_candidate(
                candidate,
                surface_forms_a=forms_a,
                surface_forms_b=forms_b,
                definition_a=def_a,
                definition_b=def_b
            )
            scored.append(scored_candidate)

        logger.info(
            f"[PairScorer] Scored {len(scored)} candidates, "
            f"avg score: {sum(c.similarity_score for c in scored) / len(scored):.3f}"
        )

        return scored


# Singleton
_scorer_instance: Optional[PairSimilarityScorer] = None


def get_pair_scorer(use_cross_encoder: bool = True) -> PairSimilarityScorer:
    """Get or create PairSimilarityScorer instance."""
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = PairSimilarityScorer(use_cross_encoder=use_cross_encoder)
    return _scorer_instance
