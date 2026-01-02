"""
Hybrid Anchor Model - Fine Classifier (Pass 2)

Classification LLM fine-grained pour enrichissement Pass 2.
Affine les types heuristiques avec sous-types, confiance, justification.

Exécuté uniquement en Pass 2 (inline/background/scheduled selon config).

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2024-12
"""

import json
import logging
import re
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.config.feature_flags import get_hybrid_anchor_config

logger = logging.getLogger(__name__)


class ConceptTypeFine(str, Enum):
    """
    Types fins assignés en Pass 2.

    Plus granulaires que les types heuristiques Pass 1.
    """
    # Structural subtypes
    STRUCTURAL_ARTICLE = "structural_article"
    STRUCTURAL_SECTION = "structural_section"
    STRUCTURAL_ANNEX = "structural_annex"
    STRUCTURAL_DEFINITION = "structural_definition"

    # Regulatory subtypes
    REGULATORY_REQUIREMENT = "regulatory_requirement"
    REGULATORY_PROHIBITION = "regulatory_prohibition"
    REGULATORY_CONDITION = "regulatory_condition"
    REGULATORY_THRESHOLD = "regulatory_threshold"
    REGULATORY_EXEMPTION = "regulatory_exemption"

    # Procedural subtypes
    PROCEDURAL_PROCESS = "procedural_process"
    PROCEDURAL_METHOD = "procedural_method"
    PROCEDURAL_WORKFLOW = "procedural_workflow"
    PROCEDURAL_STEP = "procedural_step"

    # Entity subtypes
    ENTITY_ORGANIZATION = "entity_organization"
    ENTITY_SYSTEM = "entity_system"
    ENTITY_ROLE = "entity_role"
    ENTITY_PRODUCT = "entity_product"
    ENTITY_STANDARD = "entity_standard"

    # Abstract subtypes
    ABSTRACT_PRINCIPLE = "abstract_principle"
    ABSTRACT_CAPABILITY = "abstract_capability"
    ABSTRACT_RISK = "abstract_risk"
    ABSTRACT_METRIC = "abstract_metric"
    ABSTRACT_CATEGORY = "abstract_category"
    ABSTRACT_GENERAL = "abstract_general"


@dataclass
class FineClassificationResult:
    """Résultat de classification fine."""

    concept_id: str
    type_fine: ConceptTypeFine
    confidence: float
    justification: str
    type_heuristic_validated: bool  # True si Pass 2 confirme Pass 1


@dataclass
class FineClassificationBatch:
    """Résultat batch de classification fine."""

    results: List[FineClassificationResult] = field(default_factory=list)
    total_processed: int = 0
    type_changes: int = 0  # Nombre de corrections vs Pass 1


# =============================================================================
# Prompts LLM
# =============================================================================

FINE_CLASSIFICATION_SYSTEM_PROMPT = """You are OSMOSE Fine Concept Classifier (Pass 2).

Your task is to assign a precise type to concepts that were pre-classified heuristically in Pass 1.
You must validate or correct the heuristic classification with a fine-grained type.

## Fine Types Available

### Structural (document structure)
- structural_article: Numbered articles (e.g., "Article 35")
- structural_section: Numbered sections (e.g., "Section 4.2")
- structural_annex: Annexes, appendices
- structural_definition: Definition sections

### Regulatory (normative content)
- regulatory_requirement: Obligations (shall, must)
- regulatory_prohibition: Bans (shall not, prohibited)
- regulatory_condition: Conditions, prerequisites
- regulatory_threshold: Numeric thresholds, limits
- regulatory_exemption: Exceptions, exemptions

### Procedural (processes)
- procedural_process: High-level processes
- procedural_method: Specific methods
- procedural_workflow: Multi-step workflows
- procedural_step: Individual steps

### Entity (identifiable objects)
- entity_organization: Organizations, institutions
- entity_system: Systems, platforms, tools
- entity_role: Roles, actors, stakeholders
- entity_product: Products, services
- entity_standard: Standards, frameworks, certifications

### Abstract (concepts)
- abstract_principle: Principles, values
- abstract_capability: Capabilities, features
- abstract_risk: Risks, threats, vulnerabilities
- abstract_metric: Metrics, KPIs, measures
- abstract_category: Categories, classifications
- abstract_general: General concepts

## Output Format
Return JSON only:
```json
{
  "results": [
    {
      "id": "concept_id",
      "type_fine": "regulatory_requirement",
      "confidence": 0.92,
      "justification": "Contains 'shall' with clear obligation"
    }
  ]
}
```

## Rules
- Always provide a justification (brief, <30 words)
- Confidence 0.0-1.0 based on evidence strength
- Prefer the heuristic type if evidence is weak
- Do NOT invent information not in the context"""


FINE_CLASSIFICATION_USER_PROMPT = """Classify these concepts with fine-grained types.

## Concepts to classify
{concepts_json}

## Instructions
1. For each concept, assign the most specific fine type
2. Consider the label, definition, quote, and heuristic type from Pass 1
3. If heuristic type is correct, validate it with a subtype
4. If heuristic type is wrong, correct it

Return only valid JSON."""


class FineClassifier:
    """
    Classificateur LLM fine-grained pour Pass 2.

    Affine les types heuristiques avec:
    - Types précis (sous-types)
    - Confiance affinée
    - Justification

    Exécuté en Pass 2 uniquement (non bloquant).
    """

    def __init__(
        self,
        llm_router=None,
        tenant_id: str = "default",
        batch_size: int = 50  # Increased from 20 to 50 for faster processing
    ):
        """
        Initialise le classificateur.

        Args:
            llm_router: LLM Router instance
            tenant_id: ID tenant
            batch_size: Taille des batches LLM
        """
        self.llm_router = llm_router or get_llm_router()
        self.tenant_id = tenant_id
        self.batch_size = batch_size

        # Config
        self.config = get_hybrid_anchor_config("classification_config", tenant_id) or {}

        logger.info(
            f"[OSMOSE:FineClassifier] Initialized (batch_size={batch_size})"
        )

    async def classify_batch_async(
        self,
        concepts: List[Dict[str, Any]]
    ) -> FineClassificationBatch:
        """
        Classifie un batch de concepts en async.

        Args:
            concepts: Liste de concepts avec 'id', 'label', 'definition', 'quote', 'type_heuristic'

        Returns:
            FineClassificationBatch
        """
        if not concepts:
            return FineClassificationBatch()

        all_results: List[FineClassificationResult] = []
        type_changes = 0

        # Découper en batches
        for i in range(0, len(concepts), self.batch_size):
            batch = concepts[i:i + self.batch_size]

            try:
                batch_results = await self._classify_batch_llm(batch)
                all_results.extend(batch_results)

                # Compter les changements de type
                for concept, result in zip(batch, batch_results):
                    heuristic_type = concept.get("type_heuristic", "abstract")
                    if not result.type_fine.value.startswith(heuristic_type):
                        type_changes += 1

            except Exception as e:
                logger.error(f"[OSMOSE:FineClassifier] Batch {i//self.batch_size + 1} failed: {e}")
                # Fallback: garder types heuristiques
                for concept in batch:
                    all_results.append(self._fallback_result(concept))

        result = FineClassificationBatch(
            results=all_results,
            total_processed=len(all_results),
            type_changes=type_changes
        )

        logger.info(
            f"[OSMOSE:FineClassifier] Classification complete: "
            f"{result.total_processed} concepts, {result.type_changes} type changes"
        )

        return result

    async def _classify_batch_llm(
        self,
        batch: List[Dict[str, Any]]
    ) -> List[FineClassificationResult]:
        """Appelle LLM pour classification fine."""

        # Préparer JSON input
        # FIXED 2024-12-31: Gérer les valeurs None provenant de Neo4j
        # c.get("key", "") retourne None si la clé existe avec valeur None
        # Utiliser (c.get("key") or "") pour garantir une chaîne
        concepts_data = [
            {
                "id": c.get("id") or f"c_{i}",
                "label": (c.get("label") or "")[:200],
                "definition": (c.get("definition") or "")[:200],
                "quote": (c.get("quote") or "")[:200],
                "type_heuristic": c.get("type_heuristic") or "abstract"
            }
            for i, c in enumerate(batch)
        ]
        concepts_json = json.dumps(concepts_data, ensure_ascii=False, indent=2)

        # Construire prompt
        user_prompt = FINE_CLASSIFICATION_USER_PROMPT.format(
            concepts_json=concepts_json
        )

        # Appel LLM
        response = await self.llm_router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=[
                {"role": "system", "content": FINE_CLASSIFICATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )

        # Parser réponse
        return self._parse_response(response, batch)

    def _parse_response(
        self,
        response_text: str,
        batch: List[Dict[str, Any]]
    ) -> List[FineClassificationResult]:
        """Parse la réponse LLM."""

        try:
            # FIXED 2024-12-31: Gérer le cas où response_text est None
            if response_text is None:
                logger.warning("[OSMOSE:FineClassifier] Received None response from LLM")
                return [self._fallback_result(c) for c in batch]

            # Nettoyer markdown si présent
            text = response_text.strip()
            if text.startswith("```"):
                text = re.sub(r"```json?\n?", "", text)
                text = re.sub(r"\n?```$", "", text)

            # Parser JSON
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON found in response")

            data = json.loads(json_match.group(0))
            results_data = data.get("results", [])

            # Mapper vers objets
            results = []
            id_to_concept = {c.get("id", f"c_{i}"): c for i, c in enumerate(batch)}

            for item in results_data:
                concept_id = item.get("id", "")
                if concept_id not in id_to_concept:
                    continue

                try:
                    type_fine = ConceptTypeFine(item.get("type_fine", "abstract_general"))
                except ValueError:
                    type_fine = ConceptTypeFine.ABSTRACT_GENERAL

                concept = id_to_concept[concept_id]
                heuristic_type = concept.get("type_heuristic", "abstract")
                validated = type_fine.value.startswith(heuristic_type)

                results.append(FineClassificationResult(
                    concept_id=concept_id,
                    type_fine=type_fine,
                    confidence=float(item.get("confidence", 0.7)),
                    justification=item.get("justification", ""),
                    type_heuristic_validated=validated
                ))

            # Ajouter concepts manquants
            result_ids = {r.concept_id for r in results}
            for concept in batch:
                cid = concept.get("id", "")
                if cid not in result_ids:
                    results.append(self._fallback_result(concept))

            return results

        except Exception as e:
            logger.error(f"[OSMOSE:FineClassifier] Parse error: {e}")
            return [self._fallback_result(c) for c in batch]

    def _fallback_result(self, concept: Dict[str, Any]) -> FineClassificationResult:
        """Crée un résultat fallback basé sur le type heuristique."""

        heuristic_type = concept.get("type_heuristic", "abstract")

        # Mapper heuristic vers fine type
        type_mapping = {
            "structural": ConceptTypeFine.STRUCTURAL_SECTION,
            "regulatory": ConceptTypeFine.REGULATORY_REQUIREMENT,
            "procedural": ConceptTypeFine.PROCEDURAL_PROCESS,
            "abstract": ConceptTypeFine.ABSTRACT_GENERAL,
        }

        return FineClassificationResult(
            concept_id=concept.get("id", "unknown"),
            type_fine=type_mapping.get(heuristic_type, ConceptTypeFine.ABSTRACT_GENERAL),
            confidence=0.5,
            justification="Fallback to heuristic type",
            type_heuristic_validated=True
        )

    def classify_sync(
        self,
        concepts: List[Dict[str, Any]]
    ) -> FineClassificationBatch:
        """
        Version synchrone pour compatibilité.

        Args:
            concepts: Concepts à classifier

        Returns:
            FineClassificationBatch
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.classify_batch_async(concepts)
            )
        finally:
            loop.close()


# =============================================================================
# Factory Pattern
# =============================================================================

_classifier_instance: Optional[FineClassifier] = None


def get_fine_classifier(tenant_id: str = "default") -> FineClassifier:
    """
    Récupère l'instance singleton du classificateur.

    Args:
        tenant_id: ID tenant

    Returns:
        FineClassifier instance
    """
    global _classifier_instance

    if _classifier_instance is None:
        _classifier_instance = FineClassifier(tenant_id=tenant_id)

    return _classifier_instance
