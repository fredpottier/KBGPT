"""
Phase 1.8.3 - LLM Smart Relation Enrichment

Enrichit les relations dans la "zone grise" (0.4-0.6 confidence) via LLM.
Objectif: Precision relations 60% → 80%, Rappel 50% → 70%

Architecture:
1. Filter: Identifier relations en zone grise
2. Batch: Grouper par type pour appels LLM efficaces
3. Validate: LLM valide/enrichit chaque relation
4. Update: Mettre à jour confidence et metadata
"""

import logging
import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from knowbase.relations.types import (
    TypedRelation,
    RelationType,
    RelationMetadata,
    ExtractionMethod,
    RelationStrength,
    RelationStatus
)
from knowbase.common.llm_router import LLMRouter, TaskType
from knowbase.config.feature_flags import is_feature_enabled, get_feature_config

logger = logging.getLogger(__name__)


# =========================================================================
# Prompt for Relation Enrichment
# =========================================================================

RELATION_ENRICHMENT_SYSTEM_PROMPT = """You are a relation validation specialist for knowledge graphs.

Your task is to validate semantic relations between concepts and determine if they are:
1. VALID: The relation is correct and well-defined
2. INVALID: The relation is incorrect or unsupported by evidence
3. UNCERTAIN: More context needed to determine validity

For each relation, analyze:
- The source and target concepts
- The relation type and its definition
- The evidence text supporting the relation
- The document context"""


RELATION_ENRICHMENT_USER_PROMPT = """Validate the following relations between concepts.

DOCUMENT CONTEXT:
{document_context}

RELATIONS TO VALIDATE:
{relations_batch}

RELATION TYPE DEFINITIONS:
- PART_OF: A is a component/part of B
- SUBTYPE_OF: A is a type/subclass of B
- REQUIRES: A mandatorily needs B
- USES: A optionally uses B
- INTEGRATES_WITH: A integrates/interfaces with B
- VERSION_OF: A is a version of B
- PRECEDES: A comes before B chronologically
- REPLACES: A replaces/supersedes B
- DEPRECATES: A makes B obsolete

For each relation, respond with:
1. relation_index: The index of the relation (0-based)
2. verdict: "VALID", "INVALID", or "UNCERTAIN"
3. confidence: New confidence score (0.0-1.0)
4. reasoning: Brief explanation for your decision
5. suggested_type: If the relation type is wrong, suggest the correct one (optional)

Respond ONLY in valid JSON format:
```json
{{
  "validations": [
    {{
      "relation_index": 0,
      "verdict": "VALID",
      "confidence": 0.92,
      "reasoning": "Evidence clearly shows X uses Y",
      "suggested_type": null
    }}
  ]
}}
```"""


class RelationEnricher:
    """
    LLM-based relation enrichment for gray zone relations.

    Phase 1.8.3: Améliore precision relations de 60% → 80%
    en validant les relations avec confidence 0.4-0.6 via LLM.
    """

    def __init__(
        self,
        llm_router: Optional[LLMRouter] = None,
        model: str = "gpt-4o-mini",
        batch_size: int = 50,
        max_batches: int = 20,
        tenant_id: str = "default"
    ):
        """
        Initialize RelationEnricher.

        Args:
            llm_router: LLM router instance
            model: Model to use for validation
            batch_size: Number of relations per LLM call
            max_batches: Maximum batches to process (budget cap)
            tenant_id: Tenant ID for feature flags
        """
        self.llm_router = llm_router or LLMRouter()
        self.model = model
        self.batch_size = batch_size
        self.max_batches = max_batches
        self.tenant_id = tenant_id

        # Load config from feature flags
        self._load_config()

        logger.info(
            f"[OSMOSE:RelationEnricher] Initialized "
            f"(model={model}, batch_size={batch_size}, max_batches={max_batches})"
        )

    def _load_config(self):
        """Load configuration from feature flags."""
        config = get_feature_config("relation_enrichment", self.tenant_id)

        self.min_confidence = config.get("min_confidence", 0.4)
        self.max_confidence = config.get("max_confidence", 0.6)
        self.batch_size = config.get("batch_size", self.batch_size)
        self.max_batches = config.get("max_batches", self.max_batches)

    def is_in_gray_zone(self, relation: TypedRelation) -> bool:
        """
        Check if relation is in the gray zone (needs LLM validation).

        Args:
            relation: Relation to check

        Returns:
            True if relation confidence is in [min_confidence, max_confidence]
        """
        confidence = relation.metadata.confidence
        return self.min_confidence <= confidence <= self.max_confidence

    def filter_gray_zone_relations(
        self,
        relations: List[TypedRelation]
    ) -> List[TypedRelation]:
        """
        Filter relations that need LLM validation (gray zone).

        Args:
            relations: All extracted relations

        Returns:
            Relations with confidence in gray zone
        """
        gray_zone = [r for r in relations if self.is_in_gray_zone(r)]

        logger.info(
            f"[OSMOSE:RelationEnricher] Filtered {len(gray_zone)}/{len(relations)} "
            f"relations in gray zone [{self.min_confidence}, {self.max_confidence}]"
        )

        return gray_zone

    def enrich_relations(
        self,
        relations: List[TypedRelation],
        document_context: str = "",
        concepts_map: Optional[Dict[str, Dict]] = None
    ) -> List[TypedRelation]:
        """
        Enrich relations via LLM validation.

        Args:
            relations: Relations to validate (should be gray zone)
            document_context: Document context for disambiguation
            concepts_map: Mapping concept_id → concept details

        Returns:
            Enriched relations with updated confidence
        """
        if not is_feature_enabled("enable_llm_relation_enrichment", self.tenant_id):
            logger.info(
                "[OSMOSE:RelationEnricher] LLM relation enrichment disabled, "
                "returning original relations"
            )
            return relations

        if not relations:
            return []

        # Batch relations
        batches = self._create_batches(relations)

        # Limit to max_batches
        if len(batches) > self.max_batches:
            logger.warning(
                f"[OSMOSE:RelationEnricher] Limiting batches from {len(batches)} "
                f"to {self.max_batches} (budget cap)"
            )
            batches = batches[:self.max_batches]

        logger.info(
            f"[OSMOSE:RelationEnricher] Processing {len(relations)} relations "
            f"in {len(batches)} batches"
        )

        # Process batches
        enriched_relations = []

        for batch_idx, batch in enumerate(batches):
            try:
                batch_results = self._process_batch(
                    batch=batch,
                    batch_idx=batch_idx,
                    total_batches=len(batches),
                    document_context=document_context,
                    concepts_map=concepts_map
                )
                enriched_relations.extend(batch_results)

            except Exception as e:
                logger.error(
                    f"[OSMOSE:RelationEnricher] Batch {batch_idx + 1} failed: {e}",
                    exc_info=True
                )
                # Keep original relations on failure
                enriched_relations.extend(batch)

        logger.info(
            f"[OSMOSE:RelationEnricher] ✅ Enriched {len(enriched_relations)} relations"
        )

        return enriched_relations

    def _create_batches(
        self,
        relations: List[TypedRelation]
    ) -> List[List[TypedRelation]]:
        """Create batches of relations for LLM processing."""
        batches = []
        for i in range(0, len(relations), self.batch_size):
            batch = relations[i:i + self.batch_size]
            batches.append(batch)
        return batches

    def _process_batch(
        self,
        batch: List[TypedRelation],
        batch_idx: int,
        total_batches: int,
        document_context: str = "",
        concepts_map: Optional[Dict[str, Dict]] = None
    ) -> List[TypedRelation]:
        """
        Process a batch of relations via LLM.

        Returns:
            Enriched relations with updated confidence
        """
        # Format relations for prompt
        relations_text = self._format_relations_for_prompt(batch, concepts_map)

        # Build prompt
        user_prompt = RELATION_ENRICHMENT_USER_PROMPT.format(
            document_context=document_context[:2000] if document_context else "Not provided",
            relations_batch=relations_text
        )

        # Call LLM
        try:
            response_text = self.llm_router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {"role": "system", "content": RELATION_ENRICHMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                model_preference=self.model
            )

            # Parse response
            result = json.loads(response_text)
            validations = result.get("validations", [])

            # Update relations based on validations
            enriched = self._apply_validations(batch, validations)

            logger.info(
                f"[OSMOSE:RelationEnricher] Batch {batch_idx + 1}/{total_batches}: "
                f"validated {len(validations)} relations"
            )

            return enriched

        except json.JSONDecodeError as e:
            logger.error(f"[OSMOSE:RelationEnricher] JSON parse error: {e}")
            return batch
        except Exception as e:
            logger.error(f"[OSMOSE:RelationEnricher] LLM error: {e}")
            return batch

    def _format_relations_for_prompt(
        self,
        relations: List[TypedRelation],
        concepts_map: Optional[Dict[str, Dict]] = None
    ) -> str:
        """Format relations for LLM prompt."""
        lines = []

        for idx, rel in enumerate(relations):
            # Get concept names if available
            source_name = rel.source_concept
            target_name = rel.target_concept

            if concepts_map:
                source_info = concepts_map.get(rel.source_concept, {})
                target_info = concepts_map.get(rel.target_concept, {})
                source_name = source_info.get("canonical_name", rel.source_concept)
                target_name = target_info.get("canonical_name", rel.target_concept)

            lines.append(
                f"{idx}. [{rel.relation_type.value}] "
                f"\"{source_name}\" → \"{target_name}\" "
                f"(confidence: {rel.metadata.confidence:.2f})\n"
                f"   Evidence: \"{rel.evidence[:150]}...\""
            )

        return "\n\n".join(lines)

    def _apply_validations(
        self,
        relations: List[TypedRelation],
        validations: List[Dict[str, Any]]
    ) -> List[TypedRelation]:
        """
        Apply LLM validations to relations.

        Updates confidence and marks invalid relations.
        """
        # Create index map for quick lookup
        validation_map = {v["relation_index"]: v for v in validations}

        enriched = []
        for idx, rel in enumerate(relations):
            validation = validation_map.get(idx)

            if validation:
                new_confidence = validation.get("confidence", rel.metadata.confidence)
                verdict = validation.get("verdict", "UNCERTAIN")
                reasoning = validation.get("reasoning", "")
                suggested_type = validation.get("suggested_type")

                # Update relation based on verdict
                if verdict == "INVALID":
                    # Mark as inactive
                    rel.metadata.status = RelationStatus.INACTIVE
                    rel.metadata.confidence = new_confidence
                    logger.debug(
                        f"[OSMOSE:RelationEnricher] Relation {idx} marked INVALID: {reasoning}"
                    )
                elif verdict == "VALID":
                    rel.metadata.confidence = new_confidence
                    rel.metadata.require_validation = False
                    # Update type if suggested
                    if suggested_type:
                        try:
                            rel.relation_type = RelationType(suggested_type)
                        except ValueError:
                            pass
                else:  # UNCERTAIN
                    rel.metadata.require_validation = True

                # Store reasoning in context
                if rel.context:
                    try:
                        ctx = json.loads(rel.context)
                        ctx["llm_validation"] = {
                            "verdict": verdict,
                            "reasoning": reasoning
                        }
                        rel.context = json.dumps(ctx)
                    except json.JSONDecodeError:
                        rel.context = json.dumps({
                            "llm_validation": {
                                "verdict": verdict,
                                "reasoning": reasoning
                            }
                        })
                else:
                    rel.context = json.dumps({
                        "llm_validation": {
                            "verdict": verdict,
                            "reasoning": reasoning
                        }
                    })

            enriched.append(rel)

        return enriched

    def get_enrichment_stats(
        self,
        original_relations: List[TypedRelation],
        enriched_relations: List[TypedRelation]
    ) -> Dict[str, Any]:
        """
        Calculate statistics about enrichment process.

        Returns:
            Dict with stats (validated, invalidated, confidence changes, etc.)
        """
        stats = {
            "total_original": len(original_relations),
            "total_enriched": len(enriched_relations),
            "validated": 0,
            "invalidated": 0,
            "uncertain": 0,
            "avg_confidence_before": 0.0,
            "avg_confidence_after": 0.0,
            "confidence_improved": 0,
            "confidence_lowered": 0
        }

        if not original_relations:
            return stats

        # Calculate averages
        stats["avg_confidence_before"] = sum(
            r.metadata.confidence for r in original_relations
        ) / len(original_relations)

        for orig, enriched in zip(original_relations, enriched_relations):
            # Check status
            if enriched.metadata.status == RelationStatus.INACTIVE:
                stats["invalidated"] += 1
            elif enriched.metadata.require_validation:
                stats["uncertain"] += 1
            else:
                stats["validated"] += 1

            # Compare confidence
            if enriched.metadata.confidence > orig.metadata.confidence:
                stats["confidence_improved"] += 1
            elif enriched.metadata.confidence < orig.metadata.confidence:
                stats["confidence_lowered"] += 1

        if enriched_relations:
            stats["avg_confidence_after"] = sum(
                r.metadata.confidence for r in enriched_relations
                if r.metadata.status == RelationStatus.ACTIVE
            ) / max(1, sum(1 for r in enriched_relations if r.metadata.status == RelationStatus.ACTIVE))

        return stats


# =========================================================================
# Integration Helper Functions
# =========================================================================

def enrich_relations_if_enabled(
    relations: List[TypedRelation],
    document_context: str = "",
    concepts_map: Optional[Dict[str, Dict]] = None,
    tenant_id: str = "default"
) -> List[TypedRelation]:
    """
    Convenience function to enrich relations if feature enabled.

    Args:
        relations: Relations to potentially enrich
        document_context: Document context
        concepts_map: Concept details map
        tenant_id: Tenant for feature flags

    Returns:
        Enriched relations (or original if disabled)
    """
    if not is_feature_enabled("enable_llm_relation_enrichment", tenant_id):
        return relations

    enricher = RelationEnricher(tenant_id=tenant_id)

    # Filter gray zone relations
    gray_zone = enricher.filter_gray_zone_relations(relations)

    if not gray_zone:
        logger.info("[OSMOSE:RelationEnricher] No relations in gray zone, skipping enrichment")
        return relations

    # Enrich gray zone relations
    enriched_gray = enricher.enrich_relations(
        relations=gray_zone,
        document_context=document_context,
        concepts_map=concepts_map
    )

    # Merge: keep high-confidence relations as-is, replace gray zone with enriched
    gray_zone_ids = {r.relation_id for r in gray_zone}
    enriched_map = {r.relation_id: r for r in enriched_gray}

    result = []
    for rel in relations:
        if rel.relation_id in gray_zone_ids:
            result.append(enriched_map.get(rel.relation_id, rel))
        else:
            result.append(rel)

    return result
