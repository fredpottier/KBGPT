"""
OSMOSE Pass 2 - Segment-First Relation Extractor (ADR-Compliant)

Extraction de relations au niveau SEGMENT avec:
- Scoring des segments (anchor density, concept diversity, section type)
- Budgets stricts: 8 relations/segment, 150/document
- Evidence obligatoire: quote + chunk_id + span
- 12 prédicats fermés uniquement
- Fuzzy matching >= 70% (approximate si < 85%)
- Observabilité par segment

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2025-01
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

from rapidfuzz import fuzz

from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.relations.raw_assertion_writer import get_raw_assertion_writer
from knowbase.relations.types import RelationType, RawAssertionFlags
from knowbase.relations.conflict_verifier import verify_conflict
from knowbase.semantic.anchor_resolver import _find_best_match, FuzzyMatchResult

logger = logging.getLogger(__name__)


# =============================================================================
# Proto → Canonical ID Resolution Cache
# =============================================================================

_proto_to_canonical_cache: Dict[str, Optional[str]] = {}


def resolve_proto_to_canonical(
    proto_ids: List[str],
    tenant_id: str = "default"
) -> Dict[str, Optional[str]]:
    """
    Résout les IDs de ProtoConcepts vers les IDs de CanonicalConcepts.

    Utilise la relation INSTANCE_OF dans Neo4j:
    (ProtoConcept {concept_id: pc_xxx})-[:INSTANCE_OF]->(CanonicalConcept {canonical_id: cc_xxx})

    Args:
        proto_ids: Liste des IDs de ProtoConcepts (format pc_xxx)
        tenant_id: Tenant ID

    Returns:
        Dict mapping proto_id → canonical_id (ou None si pas trouvé)
    """
    global _proto_to_canonical_cache

    # Filtrer les IDs déjà en cache
    to_resolve = [pid for pid in proto_ids if pid not in _proto_to_canonical_cache]

    if to_resolve:
        try:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )

            # Requête batch pour résoudre les IDs
            query = """
            UNWIND $proto_ids AS pid
            OPTIONAL MATCH (pc:ProtoConcept {concept_id: pid, tenant_id: $tenant_id})
                          -[:INSTANCE_OF]->(cc:CanonicalConcept)
            RETURN pid AS proto_id, cc.canonical_id AS canonical_id
            """

            database = getattr(neo4j_client, 'database', 'neo4j')
            with neo4j_client.driver.session(database=database) as session:
                result = session.run(query, {"proto_ids": to_resolve, "tenant_id": tenant_id})

                for record in result:
                    pid = record["proto_id"]
                    cid = record["canonical_id"]
                    _proto_to_canonical_cache[pid] = cid

            neo4j_client.close()

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2] Failed to resolve proto IDs: {e}")
            # Marquer comme non résolus
            for pid in to_resolve:
                _proto_to_canonical_cache[pid] = None

    # Retourner les mappings demandés
    return {pid: _proto_to_canonical_cache.get(pid) for pid in proto_ids}


# =============================================================================
# ADR Constants
# =============================================================================

# 12 prédicats fermés (ADR Hybrid Anchor Model)
ADR_PREDICATES = {
    "defines", "requires", "enables", "prevents", "causes", "applies_to",
    "part_of", "depends_on", "mitigates", "conflicts_with", "example_of", "governed_by"
}

# Mapping prédicat -> RelationType
PREDICATE_TO_RELATION_TYPE: Dict[str, RelationType] = {
    "defines": RelationType.DEFINES,
    "requires": RelationType.REQUIRES,
    "enables": RelationType.ENABLES,
    "prevents": RelationType.PREVENTS,
    "causes": RelationType.CAUSES,
    "applies_to": RelationType.APPLIES_TO,
    "part_of": RelationType.PART_OF,
    "depends_on": RelationType.REQUIRES,  # Alias
    "mitigates": RelationType.MITIGATES,
    "conflicts_with": RelationType.CONFLICTS_WITH,
    "example_of": RelationType.EXAMPLE_OF,
    "governed_by": RelationType.GOVERNED_BY,
}

# Budgets ADR
MAX_RELATIONS_PER_SEGMENT = 8
MAX_RELATIONS_PER_DOCUMENT = 150
MAX_QUOTE_WORDS = 30
MIN_QUOTE_WORDS = 8  # PATCH-01: minimum quote length

# PATCH-01: Seuils spécifiques pour conflicts_with
CONFLICTS_WITH_MIN_CONFIDENCE = 0.85
CONFLICTS_WITH_MIN_FUZZY = 90

# Seuils de scoring segment
SEGMENT_SCORE_EXTRACT_ALWAYS = 50
SEGMENT_SCORE_EXTRACT_IF_BUDGET = 35
SEGMENT_SCORE_SKIP = 35

# PATCH-03: Top-K fallback pour couverture minimale
MIN_ELIGIBLE_SEGMENTS = 10  # Minimum de segments à traiter par document
SEGMENT_SCORE_FALLBACK_FLOOR = 25  # Plancher absolu pour fallback

# Poids section pour scoring
SECTION_WEIGHTS = {
    "requirements": 25,
    "process": 25,
    "architecture": 25,
    "rules": 25,
    "scope": 15,
    "obligations": 15,
    "controls": 15,
    "definition": 5,
    "introduction": -20,
    "summary": -20,
    "annex": -20,
    "foreword": -20,
}


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class SegmentScore:
    """Score d'un segment pour décider si on extrait."""
    segment_id: str
    document_id: str
    score: int  # 0-100
    anchor_density: float
    concept_count: int
    section_type: str
    eligible: bool  # score >= 35


@dataclass
class SegmentContext:
    """Contexte d'un segment pour extraction."""
    segment_id: str
    document_id: str
    chunks: List[Dict[str, Any]]  # Chunks du segment
    window_text: str  # Texte combiné des chunks
    concepts: List[Dict[str, Any]]  # anchored_concepts uniques
    score: SegmentScore


@dataclass
class ValidatedRelation:
    """Relation validée prête pour persistance."""
    subject_id: str
    object_id: str
    predicate: str  # Un des 12
    quote: str
    chunk_id: str
    span_start: int
    span_end: int
    confidence: float
    fuzzy_score: float
    approximate: bool


@dataclass
class SegmentObservability:
    """Métriques par segment (ADR required)."""
    segment_id: str
    relations_proposed: int = 0
    relations_validated: int = 0
    relations_rejected: int = 0
    rejection_reasons: Dict[str, int] = field(default_factory=dict)
    fuzzy_match_rate: float = 0.0

    def add_rejection(self, reason: str):
        """Ajoute une raison de rejet."""
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1
        self.relations_rejected += 1


# =============================================================================
# LLM Prompt (ADR-Compliant)
# =============================================================================

ADR_PROMPT_SYSTEM = """You are OSMOSE Relation Extractor (Pass 2).

Your task: Extract factual relations between concepts from a text segment.

## CRITICAL REQUIREMENTS

### 1. Predicates (CLOSED SET - ONLY USE THESE 12)
- defines: A defines/establishes B (definitional)
- requires: A requires/needs B (hard dependency)
- enables: A enables/allows B (facilitation)
- prevents: A prevents/blocks B (blocking)
- causes: A causes/leads_to B (causality)
- applies_to: A applies_to/governs B (scope)
- part_of: A is_part_of B (composition)
- depends_on: A depends_on B (soft dependency)
- mitigates: A mitigates/reduces B (risk reduction)
- conflicts_with: A conflicts_with B (STRICT - see section 4)
- example_of: A is_example_of B (instance)
- governed_by: A governed_by B (regulation)

### 2. DO NOT EXTRACT IF (co-occurrence is NOT a relation)
Do NOT extract a relation if the quote only shows:
- Co-occurrence / being mentioned in the same paragraph
- An enumeration or list of items (e.g., "A, B, and C")
- "followed by / includes / such as" without a causal/constraint link
- "A and B are linked/related" without specifying the nature of the link
If unsure → output NO relation.

### 3. Evidence Requirements (MANDATORY)
- Every relation MUST have a quote (min 8 words, max 30 words)
- The quote must DIRECTLY support the relation
- The quote should contain both concepts (or clear references to them)
- Self-check: verify the quote would prove the relation if read alone (no extra context)
- If no textual evidence exists, do NOT create the relation

### 4. STRICT RULES FOR conflicts_with (RARE PREDICATE - WILL BE VERIFIED)
conflicts_with denotes a HARD INCOMPATIBILITY where:
- A and B cannot be simultaneously true, applied, enabled, or implemented
- Choosing A necessarily excludes B
- The conflict would still exist even if tone and sentiment were removed

Before using conflicts_with, ask yourself:
"If A is true, is B logically impossible at the same time?"
If the answer is not clearly yes → do NOT use conflicts_with.

DO NOT use conflicts_with for:
- Threat targeting something (use "prevents" or "mitigates" instead)
- Loss, weakness, limitation, difficulty (use "causes" instead)
- Comparison, frequency difference, ranking (no relation)
- Concepts that are simply different (e.g., "DDoS" vs "Ransomware")
- Negative outcomes or tensions (use "causes" or "prevents")

### 5. Quality Rules
- Maximum 8 relations per response
- Confidence must be >= 0.6
- No self-relations (subject != object)
- No duplicate relations
- Use concept IDs exactly as provided

## Output Format
Return ONLY valid JSON:
```json
{
  "relations": [
    {
      "subject_id": "cc_xxx",
      "object_id": "cc_yyy",
      "predicate": "requires",
      "quote": "exact text from source supporting this relation",
      "confidence": 0.85
    }
  ]
}
```
"""

ADR_PROMPT_USER = """## TEXT SEGMENT
{segment_text}

## CONCEPT CATALOG (use ONLY these IDs)
{concept_catalog}

Extract relations between concepts. Maximum 8 relations. Only output JSON."""


# =============================================================================
# Segment Scoring
# =============================================================================

def score_segment(
    segment_id: str,
    document_id: str,
    chunks: List[Dict[str, Any]]
) -> SegmentScore:
    """
    Score un segment pour décider si on extrait des relations.

    Formule ADR:
    score = (anchor_score) + (diversity_score) + (section_weight)

    Thresholds:
    - score >= 50 : extraire systématiquement
    - score 35-49 : extraire si budget disponible
    - score < 35 : skip
    """
    # Calculer métriques
    total_chars = 0
    total_anchors = 0
    unique_concepts = set()
    section_type = "unknown"

    for chunk in chunks:
        text = chunk.get("text", "")
        total_chars += len(text)

        anchored = chunk.get("anchored_concepts", [])
        total_anchors += len(anchored)

        for anchor in anchored:
            concept_id = anchor.get("concept_id")
            if concept_id:
                unique_concepts.add(concept_id)

        # Récupérer section type du premier chunk
        if section_type == "unknown":
            section_type = chunk.get("section_type", "unknown").lower()

    # Anchor density (0-45 points)
    anchor_density = total_anchors / max(1, total_chars / 100)  # anchors per 100 chars
    anchor_score = min(int(anchor_density * 15), 45)

    # Concept diversity (0-30 points)
    concept_count = len(unique_concepts)
    diversity_score = min(concept_count * 10, 30)

    # Section weight (-20 to +25 points)
    section_weight = SECTION_WEIGHTS.get(section_type, 0)

    # Narrative penalty
    narrative_penalty = -20 if (total_anchors <= 1 and concept_count <= 1) else 0

    # Total score
    total_score = anchor_score + diversity_score + section_weight + narrative_penalty
    total_score = max(0, min(100, total_score))

    eligible = total_score >= SEGMENT_SCORE_EXTRACT_IF_BUDGET

    return SegmentScore(
        segment_id=segment_id,
        document_id=document_id,
        score=total_score,
        anchor_density=anchor_density,
        concept_count=concept_count,
        section_type=section_type,
        eligible=eligible
    )


# =============================================================================
# Segment Retrieval from Qdrant
# =============================================================================

async def get_document_segments(
    document_id: str,
    tenant_id: str = "default",
    collection_name: str = "knowbase"
) -> List[SegmentContext]:
    """
    Récupère tous les segments d'un document depuis Qdrant.

    1. Récupère tous les chunks du document
    2. Groupe par segment_id
    3. Score chaque segment
    4. Retourne segments éligibles (score >= 35) triés par score desc
    """
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    client = get_qdrant_client()

    # Scroll tous les chunks du document
    query_filter = Filter(must=[
        FieldCondition(key="document_id", match=MatchValue(value=document_id)),
        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))
    ])

    all_chunks = []
    offset = None

    while True:
        scroll_result = client.scroll(
            collection_name=collection_name,
            scroll_filter=query_filter,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )

        points, next_offset = scroll_result
        for point in points:
            chunk_data = {
                "chunk_id": str(point.id),
                "text": point.payload.get("text", ""),
                "segment_id": point.payload.get("segment_id", "default"),
                "section_type": point.payload.get("section_type", "unknown"),
                "chunk_index": point.payload.get("chunk_index", 0),
                "char_start": point.payload.get("char_start", 0),
                "char_end": point.payload.get("char_end", 0),
                "anchored_concepts": point.payload.get("anchored_concepts", []),
            }
            all_chunks.append(chunk_data)

        if next_offset is None:
            break
        offset = next_offset

    if not all_chunks:
        logger.warning(f"[OSMOSE:Pass2] No chunks found for document {document_id}")
        return []

    # Grouper par segment_id
    segments_map: Dict[str, List[Dict]] = {}
    for chunk in all_chunks:
        seg_id = chunk["segment_id"]
        if seg_id not in segments_map:
            segments_map[seg_id] = []
        segments_map[seg_id].append(chunk)

    # Trier chunks par index dans chaque segment
    for seg_id in segments_map:
        segments_map[seg_id].sort(key=lambda c: c.get("chunk_index", 0))

    # PATCH-03: Scorer TOUS les segments, puis appliquer Top-K fallback
    all_scored_segments: List[Tuple[str, List[Dict], SegmentScore]] = []

    for seg_id, chunks in segments_map.items():
        score = score_segment(seg_id, document_id, chunks)
        all_scored_segments.append((seg_id, chunks, score))

    # Trier par score décroissant
    all_scored_segments.sort(key=lambda x: x[2].score, reverse=True)

    # PATCH-03: Séparer eligible et fallback candidates
    eligible_segments: List[Tuple[str, List[Dict], SegmentScore]] = []
    fallback_candidates: List[Tuple[str, List[Dict], SegmentScore]] = []

    for seg_id, chunks, score in all_scored_segments:
        if score.score >= SEGMENT_SCORE_EXTRACT_IF_BUDGET:
            eligible_segments.append((seg_id, chunks, score))
        elif score.score >= SEGMENT_SCORE_FALLBACK_FLOOR:
            # Candidats fallback: score entre 25 et 34
            fallback_candidates.append((seg_id, chunks, score))
        else:
            logger.debug(
                f"[OSMOSE:Pass2] Segment {seg_id} excluded (score={score.score} < floor)"
            )

    # PATCH-03: Compléter avec fallback si pas assez de segments éligibles
    selected_segments = eligible_segments.copy()

    if len(selected_segments) < MIN_ELIGIBLE_SEGMENTS and fallback_candidates:
        needed = MIN_ELIGIBLE_SEGMENTS - len(selected_segments)
        fallback_to_add = fallback_candidates[:needed]  # Déjà triés par score desc
        selected_segments.extend(fallback_to_add)

        if fallback_to_add:
            logger.info(
                f"[OSMOSE:Pass2] PATCH-03 Top-K fallback: added {len(fallback_to_add)} segments "
                f"(scores: {[s[2].score for s in fallback_to_add]})"
            )

    # Construire SegmentContext pour les segments sélectionnés
    segments: List[SegmentContext] = []

    for seg_id, chunks, score in selected_segments:
        # Construire window_text
        window_text = "\n\n".join([c["text"] for c in chunks])

        # Collecter concepts uniques
        unique_concepts: Dict[str, Dict] = {}
        for chunk in chunks:
            for anchor in chunk.get("anchored_concepts", []):
                cid = anchor.get("concept_id")
                if cid and cid not in unique_concepts:
                    unique_concepts[cid] = {
                        "concept_id": cid,
                        "label": anchor.get("label", ""),
                        "role": anchor.get("role", "context"),
                    }

        segments.append(SegmentContext(
            segment_id=seg_id,
            document_id=document_id,
            chunks=chunks,
            window_text=window_text,
            concepts=list(unique_concepts.values()),
            score=score
        ))

    # Log stats
    fallback_count = len(selected_segments) - len(eligible_segments)
    logger.info(
        f"[OSMOSE:Pass2] Document {document_id}: "
        f"{len(segments)} segments selected ({len(eligible_segments)} eligible + {fallback_count} fallback) "
        f"of {len(segments_map)} total"
    )

    return segments


# =============================================================================
# Relation Validation
# =============================================================================

def validate_relation(
    rel_data: Dict[str, Any],
    segment: SegmentContext
) -> Tuple[Optional[ValidatedRelation], Optional[str]]:
    """
    Valide une relation extraite par le LLM.

    Note: conflicts_with passe une validation supplémentaire via le
    ConflictVerifier dans persist_relations() (pattern Verify-to-Persist).

    Returns:
        (ValidatedRelation, None) si valide
        (None, rejection_reason) si rejetée

    Rejection reasons:
        - "confidence_below_threshold": confidence < 0.60 (ou < 0.85 pour conflicts_with)
        - "invalid_predicate": pas dans les 12 autorisés
        - "quote_not_found": fuzzy score < 85 (ou < 90 pour conflicts_with)
        - "quote_too_short": < 8 mots
        - "quote_too_long": > 30 mots
        - "missing_fields": champs requis manquants
        - "self_relation": subject == object
        - "concept_not_in_catalog": concept pas dans le segment
    """
    # Extraire champs
    subject_id = rel_data.get("subject_id", "")
    object_id = rel_data.get("object_id", "")
    predicate = rel_data.get("predicate", "").lower()
    quote = rel_data.get("quote", "")
    confidence = rel_data.get("confidence", 0)

    # Vérifier champs requis
    if not subject_id or not object_id or not predicate or not quote:
        return None, "missing_fields"

    # Vérifier self-relation
    if subject_id == object_id:
        return None, "self_relation"

    # Vérifier prédicat
    if predicate not in ADR_PREDICATES:
        return None, "invalid_predicate"

    # Vérifier longueur quote (min et max)
    word_count = len(quote.split())
    if word_count < MIN_QUOTE_WORDS:
        return None, "quote_too_short"
    if word_count > MAX_QUOTE_WORDS:
        # Tronquer plutôt que rejeter
        quote = " ".join(quote.split()[:MAX_QUOTE_WORDS])

    # Seuils différenciés selon le prédicat
    # conflicts_with: pré-filtre avant Verify-to-Persist
    if predicate == "conflicts_with":
        if confidence < CONFLICTS_WITH_MIN_CONFIDENCE:
            return None, "confidence_below_threshold"
    else:
        if confidence < 0.60:
            return None, "confidence_below_threshold"

    # Vérifier que les concepts sont dans le catalogue
    catalog_ids = {c["concept_id"] for c in segment.concepts}
    if subject_id not in catalog_ids:
        return None, "concept_not_in_catalog"
    if object_id not in catalog_ids:
        return None, "concept_not_in_catalog"

    # Fuzzy match quote dans le texte du segment
    match_result = _find_best_match(quote, segment.window_text)

    # PATCH-01: Seuil fuzzy différencié
    min_fuzzy = CONFLICTS_WITH_MIN_FUZZY if predicate == "conflicts_with" else 85
    if match_result is None or match_result.score < min_fuzzy:
        return None, "quote_not_found"

    # Déterminer le chunk source pour le span
    chunk_id = None
    span_start = match_result.start
    span_end = match_result.end

    # Trouver le chunk contenant la quote
    cumulative_offset = 0
    for chunk in segment.chunks:
        chunk_text = chunk["text"]
        chunk_len = len(chunk_text)

        if cumulative_offset <= span_start < cumulative_offset + chunk_len:
            chunk_id = chunk["chunk_id"]
            # Ajuster span relatif au chunk
            span_start = span_start - cumulative_offset
            span_end = min(span_end - cumulative_offset, chunk_len)
            break

        cumulative_offset += chunk_len + 2  # +2 pour le "\n\n" entre chunks

    if not chunk_id:
        # Fallback: utiliser le premier chunk
        chunk_id = segment.chunks[0]["chunk_id"]
        span_start = 0
        span_end = min(len(quote), len(segment.chunks[0]["text"]))

    approximate = match_result.score < 85

    return ValidatedRelation(
        subject_id=subject_id,
        object_id=object_id,
        predicate=predicate,
        quote=match_result.matched_text,
        chunk_id=chunk_id,
        span_start=span_start,
        span_end=span_end,
        confidence=confidence,
        fuzzy_score=match_result.score,
        approximate=approximate
    ), None


# =============================================================================
# LLM Extraction
# =============================================================================

async def extract_segment_relations(
    segment: SegmentContext,
    llm_router=None,
    max_per_segment: int = MAX_RELATIONS_PER_SEGMENT
) -> Tuple[List[ValidatedRelation], SegmentObservability]:
    """
    Extrait les relations pour UN segment.

    Returns:
        - Liste des relations validées (max 8)
        - Observabilité du segment
    """
    if llm_router is None:
        llm_router = get_llm_router()

    observability = SegmentObservability(segment_id=segment.segment_id)

    # Vérifier qu'on a au moins 2 concepts
    if len(segment.concepts) < 2:
        logger.debug(
            f"[OSMOSE:Pass2] Segment {segment.segment_id} skipped: < 2 concepts"
        )
        return [], observability

    # Construire le catalogue de concepts
    catalog_lines = []
    for c in segment.concepts[:50]:  # Limite 50 concepts
        catalog_lines.append(f"- [{c['concept_id']}] {c['label']} ({c.get('role', 'context')})")

    concept_catalog = "\n".join(catalog_lines)

    # Construire le prompt
    user_prompt = ADR_PROMPT_USER.format(
        segment_text=segment.window_text[:6000],  # Limite tokens
        concept_catalog=concept_catalog
    )

    # Appel LLM
    try:
        response = await llm_router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=[
                {"role": "system", "content": ADR_PROMPT_SYSTEM},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=1500
        )
    except Exception as e:
        logger.error(f"[OSMOSE:Pass2] LLM call failed for segment {segment.segment_id}: {e}")
        return [], observability

    # Parser la réponse
    raw_relations = _parse_llm_response(response)
    observability.relations_proposed = len(raw_relations)

    # Valider chaque relation
    validated: List[ValidatedRelation] = []
    fuzzy_successes = 0

    for rel_data in raw_relations:
        if len(validated) >= max_per_segment:
            observability.add_rejection("budget_exceeded")
            continue

        result, rejection_reason = validate_relation(rel_data, segment)

        if result:
            validated.append(result)
            observability.relations_validated += 1
            if result.fuzzy_score >= 70:
                fuzzy_successes += 1
        else:
            observability.add_rejection(rejection_reason)

    # Calculer fuzzy match rate
    if observability.relations_proposed > 0:
        observability.fuzzy_match_rate = fuzzy_successes / observability.relations_proposed

    logger.info(
        f"[OSMOSE:Pass2] Segment {segment.segment_id}: "
        f"proposed={observability.relations_proposed}, "
        f"validated={observability.relations_validated}, "
        f"rejected={observability.relations_rejected}"
    )

    return validated, observability


def _parse_llm_response(response_text: str) -> List[Dict[str, Any]]:
    """Parse la réponse JSON du LLM."""
    if not response_text:
        return []

    try:
        # Nettoyer markdown si présent
        text = response_text.strip()
        if text.startswith("```"):
            text = re.sub(r"```json?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        # Trouver le JSON
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if not json_match:
            return []

        data = json.loads(json_match.group(0))
        return data.get("relations", [])

    except Exception as e:
        logger.warning(f"[OSMOSE:Pass2] Failed to parse LLM response: {e}")
        return []


# =============================================================================
# Document-Level Extraction
# =============================================================================

async def extract_document_relations(
    document_id: str,
    tenant_id: str = "default",
    max_per_document: int = MAX_RELATIONS_PER_DOCUMENT
) -> Tuple[List[ValidatedRelation], List[SegmentObservability]]:
    """
    Extrait les relations pour un document complet.

    1. Récupère et score les segments
    2. Pour chaque segment éligible (par score décroissant):
       - Si budget document atteint: stop
       - Extraire relations du segment
       - Accumuler observabilité
    """
    llm_router = get_llm_router()

    # Récupérer segments éligibles
    segments = await get_document_segments(document_id, tenant_id)

    all_relations: List[ValidatedRelation] = []
    all_observability: List[SegmentObservability] = []

    for segment in segments:
        # Vérifier budget document
        remaining_budget = max_per_document - len(all_relations)
        if remaining_budget <= 0:
            logger.info(
                f"[OSMOSE:Pass2] Document budget reached ({max_per_document})"
            )
            break

        # Extraire pour ce segment
        segment_budget = min(MAX_RELATIONS_PER_SEGMENT, remaining_budget)
        relations, obs = await extract_segment_relations(
            segment,
            llm_router=llm_router,
            max_per_segment=segment_budget
        )

        all_relations.extend(relations)
        all_observability.append(obs)

    logger.info(
        f"[OSMOSE:Pass2] Document {document_id}: "
        f"{len(all_relations)} relations extracted from {len(all_observability)} segments"
    )

    return all_relations, all_observability


# =============================================================================
# Persistence with ADR Guardrails + Verify-to-Persist for conflicts_with
# =============================================================================

def get_concept_labels(
    proto_ids: List[str],
    tenant_id: str = "default"
) -> Dict[str, str]:
    """
    Récupère les labels des ProtoConcepts depuis Neo4j.

    Args:
        proto_ids: Liste des IDs de ProtoConcepts
        tenant_id: Tenant ID

    Returns:
        Dict mapping proto_id → label
    """
    if not proto_ids:
        return {}

    try:
        settings = get_settings()
        neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )

        query = """
        UNWIND $proto_ids AS pid
        MATCH (pc:ProtoConcept {concept_id: pid, tenant_id: $tenant_id})
        RETURN pid AS proto_id, pc.label AS label
        """

        database = getattr(neo4j_client, 'database', 'neo4j')
        labels = {}

        with neo4j_client.driver.session(database=database) as session:
            result = session.run(query, {"proto_ids": proto_ids, "tenant_id": tenant_id})
            for record in result:
                labels[record["proto_id"]] = record["label"] or "Unknown"

        neo4j_client.close()
        return labels

    except Exception as e:
        logger.error(f"[OSMOSE:Pass2] Failed to get concept labels: {e}")
        return {pid: "Unknown" for pid in proto_ids}


async def persist_relations(
    relations: List[ValidatedRelation],
    doc_id: str,
    tenant_id: str = "default",
    llm_router=None
) -> int:
    """
    Persiste les relations validées avec guardrails ADR.

    IMPORTANT: Inclut le pattern Verify-to-Persist pour conflicts_with.
    Les relations conflicts_with passent par un 2ème appel LLM de vérification
    avant d'être persistées.

    GUARDRAILS (rejet + log si violé):
    - evidence_text non vide
    - source_chunk_id non vide
    - evidence_span_start/end non null
    - confidence >= 0.60
    - concept_id résolu vers canonical_id
    - conflicts_with: vérifié par LLM séparé
    """
    if not relations:
        logger.info(f"[OSMOSE:Pass2] No relations to persist for {doc_id}")
        return 0

    if llm_router is None:
        llm_router = get_llm_router()

    # Collecter tous les proto_ids uniques
    proto_ids = set()
    for rel in relations:
        proto_ids.add(rel.subject_id)
        proto_ids.add(rel.object_id)

    proto_ids_list = list(proto_ids)

    # Résoudre proto_id → canonical_id
    proto_to_canonical = resolve_proto_to_canonical(proto_ids_list, tenant_id)

    # Récupérer les labels pour la vérification conflicts_with
    proto_to_label = get_concept_labels(proto_ids_list, tenant_id)

    # Log résolution stats
    resolved_count = sum(1 for cid in proto_to_canonical.values() if cid is not None)
    logger.info(
        f"[OSMOSE:Pass2] Resolved {resolved_count}/{len(proto_ids)} proto IDs to canonical IDs"
    )

    writer = get_raw_assertion_writer(tenant_id)
    written = 0
    skipped_unresolved = 0
    conflicts_verified = 0
    conflicts_rejected = 0

    for rel in relations:
        # GUARDRAIL: Vérification ADR avant écriture
        if not rel.quote:
            logger.error(f"[ADR_VIOLATION] Missing evidence for {rel.subject_id} -> {rel.object_id}")
            continue
        if not rel.chunk_id:
            logger.error(f"[ADR_VIOLATION] Missing chunk_id for {rel.subject_id} -> {rel.object_id}")
            continue
        if rel.span_start is None or rel.span_end is None:
            logger.error(f"[ADR_VIOLATION] Missing span for {rel.subject_id} -> {rel.object_id}")
            continue
        if rel.confidence < 0.60:
            logger.error(f"[ADR_VIOLATION] Confidence {rel.confidence} < 0.60")
            continue

        # Résoudre proto_id → canonical_id
        subject_canonical = proto_to_canonical.get(rel.subject_id)
        object_canonical = proto_to_canonical.get(rel.object_id)

        if not subject_canonical or not object_canonical:
            logger.warning(
                f"[OSMOSE:Pass2] Skipped relation: unresolved concept(s) - "
                f"subject={rel.subject_id}→{subject_canonical}, object={rel.object_id}→{object_canonical}"
            )
            skipped_unresolved += 1
            continue

        # =================================================================
        # VERIFY-TO-PERSIST: Vérification spéciale pour conflicts_with
        # =================================================================
        if rel.predicate == "conflicts_with":
            subject_label = proto_to_label.get(rel.subject_id, "Unknown")
            object_label = proto_to_label.get(rel.object_id, "Unknown")

            # 2ème appel LLM de vérification
            is_valid = await verify_conflict(
                subject_label=subject_label,
                object_label=object_label,
                quote=rel.quote,
                llm_router=llm_router
            )

            if not is_valid:
                logger.info(
                    f"[OSMOSE:Pass2] conflicts_with REJECTED by verifier: "
                    f"'{subject_label}' <-> '{object_label}'"
                )
                conflicts_rejected += 1
                continue
            else:
                logger.info(
                    f"[OSMOSE:Pass2] conflicts_with VERIFIED: "
                    f"'{subject_label}' <-> '{object_label}'"
                )
                conflicts_verified += 1

        # Mapper prédicat vers RelationType
        relation_type = PREDICATE_TO_RELATION_TYPE.get(rel.predicate, RelationType.ASSOCIATED_WITH)

        try:
            assertion_id = writer.write_assertion(
                subject_concept_id=subject_canonical,
                object_concept_id=object_canonical,
                predicate_raw=rel.predicate,
                evidence_text=rel.quote,
                source_doc_id=doc_id,
                source_chunk_id=rel.chunk_id,
                confidence=rel.confidence,
                evidence_span_start=rel.span_start,
                evidence_span_end=rel.span_end,
                relation_type=relation_type,
                type_confidence=rel.confidence,
                flags=RawAssertionFlags(
                    is_negated=False,
                    is_hedged=False,
                    is_conditional=False,
                    cross_sentence=False
                )
            )

            if assertion_id:
                written += 1
                logger.debug(
                    f"[OSMOSE:Pass2] Persisted: {rel.subject_id[:12]} --{rel.predicate}--> {rel.object_id[:12]}"
                )

        except Exception as e:
            logger.error(f"[OSMOSE:Pass2] Failed to persist relation: {e}")

    # Log final avec stats conflicts_with
    logger.info(
        f"[OSMOSE:Pass2] Persisted {written}/{len(relations)} relations for {doc_id} "
        f"(skipped {skipped_unresolved} unresolved, "
        f"conflicts_with: {conflicts_verified} verified, {conflicts_rejected} rejected)"
    )
    return written
