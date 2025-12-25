"""
OSMOSE Concept Kind Classifier

Phase 2.9.2: Classification domain-agnostic des concepts.
Utilise un LLM pour classifier chaque concept en entity/abstract/rule_like/structural/generic/fragment.

Architecture:
- Batch processing pour efficacité
- Prompt strict JSON-only
- Heuristiques pour cas évidents (pas d'appel LLM)
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional
import asyncio

from knowbase.common.llm_router import TaskType
from .types import (
    ConceptKind,
    ConceptClassification,
    ClassificationBatchResult,
    ConceptForClassification,
    KEEPABLE_KINDS
)

logger = logging.getLogger(__name__)


# Heuristiques pour classification rapide sans LLM
STRUCTURAL_PATTERNS = [
    r"^(section|chapter|article|annex|appendix|figure|table|scope|definitions?)\b",
    r"\b(section|chapter|article|annex)\s*\d+",
    r"^(part|title|subtitle|heading)\s+\d*",
]

FRAGMENT_PATTERNS = [
    r"^(to|for|with|by|in|on|at|the|a|an)\s+",  # Starts with preposition/article
    r"^[a-z]",  # Starts with lowercase (likely incomplete)
    r"\.\.\.$",  # Ends with ellipsis
]

GENERIC_TERMS = {
    # Termes universellement génériques (domain-agnostic)
    # Note: Le LLM classifier gère la classification contextuelle
    # Ces termes sont filtrés UNIQUEMENT s'ils apparaissent seuls (1-2 mots)
    "market", "compliance", "decision making", "decision-making", "process",
    "system", "data", "information", "management", "service", "solution",
    "approach", "method", "framework", "model", "policy", "procedure",
    "activity", "action", "operation", "function", "task", "step",
}


CLASSIFICATION_SYSTEM_PROMPT = """You are OSMOSE Concept Classifier. Your job is to assign a universal concept_kind to each extracted concept.
Be domain-agnostic: you must not use industry-specific ontologies. Use only the definitions below.

DEFINITIONS (must follow strictly):
- entity: an identifiable thing (person, organization, system, product, component, place, artifact, named institution, role).
- abstract: a stable definable notion (principle, property, capability, risk, method, metric, concept, category, classification).
- rule_like: prescriptive/constraint-like content (requirement, condition, obligation, prohibition, threshold, rule, policy, "must/shall/should" type).
- structural: document/logical structure (chapter, section, annex, article, table, figure, title headings, scope section, definitions section).
- generic: too vague/transversal to be useful as a node (e.g., "market", "compliance", "decision making" without specificity).
- fragment: non-autonomous phrase fragment, incomplete definition piece, overly long clause, or text chunk that is not a standalone concept.

OUTPUT RULES:
- Return ONLY valid JSON. No markdown, no code blocks, no commentary.
- For each concept: choose exactly one concept_kind.
- Provide confidence in [0.0, 1.0].
- Provide is_keepable: true if the concept should remain as a node in the core KG (entity/abstract/rule_like); false otherwise (structural/generic/fragment).
- If the input label is generic/fragment/structural but can be salvaged, set relabel_suggestion to a better canonical label (short, noun phrase). Otherwise null.
- Do not invent new concepts. Do not add commentary.

HEURISTICS:
- If label contains "Section", "Chapter", "Article", "Annex", "Figure", "Table", "Scope", "Definitions" => structural.
- If label expresses an obligation/condition/requirement/ban/threshold => rule_like.
- If label is a lone broad word with unclear referent => generic.
- If label is a clause-like fragment (starts with a verb, or too long >10 words, or sounds like a partial sentence) => fragment.
- Prefer abstract over generic when the notion is stable and definable (e.g., "data security" = abstract, "AI governance" = abstract).
- Prefer entity when it's a named institution, system, role, product, or clearly bounded object (e.g., "European Commission" = entity, "Provider" = entity)."""


CLASSIFICATION_USER_PROMPT_TEMPLATE = """Classify the following concepts.
You may use the optional "context" field if present; otherwise classify from label alone.

INPUT:
{input_json}

Return JSON in this exact shape (no markdown):
{{"results": [{{"id": "...", "concept_kind": "entity|abstract|rule_like|structural|generic|fragment", "confidence": 0.0, "is_keepable": true, "relabel_suggestion": null}}]}}"""


class ConceptKindClassifier:
    """
    Classificateur de concepts domain-agnostic.

    Stratégie:
    1. Heuristiques rapides pour cas évidents (structural, fragment évidents)
    2. Batch LLM pour le reste
    3. Post-processing pour validation
    """

    def __init__(
        self,
        llm_router: Any = None,
        model: str = "gpt-4o-mini",
        batch_size: int = 30,
        use_heuristics: bool = True
    ):
        """
        Initialise le classifier.

        Args:
            llm_router: Router LLM pour appels API
            model: Modèle à utiliser (gpt-4o-mini recommandé pour coût)
            batch_size: Taille des batches pour classification LLM
            use_heuristics: Utiliser heuristiques pour cas évidents
        """
        self.llm_router = llm_router
        self.model = model
        self.batch_size = batch_size
        self.use_heuristics = use_heuristics

        # Compiler patterns
        self.structural_patterns = [re.compile(p, re.IGNORECASE) for p in STRUCTURAL_PATTERNS]
        self.fragment_patterns = [re.compile(p, re.IGNORECASE) for p in FRAGMENT_PATTERNS]

        logger.info(
            f"[CLASSIFIER] Initialized ConceptKindClassifier "
            f"(model={model}, batch_size={batch_size}, heuristics={use_heuristics})"
        )

    def _apply_heuristics(self, concept: ConceptForClassification) -> Optional[ConceptClassification]:
        """
        Applique heuristiques rapides pour classification évidente.

        Returns:
            ConceptClassification si heuristique match, None sinon
        """
        label = concept.label.strip()
        label_lower = label.lower()

        # Check structural patterns
        for pattern in self.structural_patterns:
            if pattern.search(label):
                return ConceptClassification(
                    id=concept.id,
                    concept_kind=ConceptKind.STRUCTURAL,
                    confidence=0.95,
                    is_keepable=False,
                    relabel_suggestion=None
                )

        # Check fragment patterns (trop long ou commence mal)
        word_count = len(label.split())
        if word_count > 12:
            return ConceptClassification(
                id=concept.id,
                concept_kind=ConceptKind.FRAGMENT,
                confidence=0.90,
                is_keepable=False,
                relabel_suggestion=None
            )

        for pattern in self.fragment_patterns:
            if pattern.match(label) and word_count > 5:
                return ConceptClassification(
                    id=concept.id,
                    concept_kind=ConceptKind.FRAGMENT,
                    confidence=0.85,
                    is_keepable=False,
                    relabel_suggestion=None
                )

        # Check generic terms (exact match only)
        if label_lower in GENERIC_TERMS and word_count <= 2:
            return ConceptClassification(
                id=concept.id,
                concept_kind=ConceptKind.GENERIC,
                confidence=0.85,
                is_keepable=False,
                relabel_suggestion=None
            )

        # Pas de match heuristique
        return None

    async def classify_batch_async(
        self,
        concepts: List[ConceptForClassification]
    ) -> ClassificationBatchResult:
        """
        Classifie un batch de concepts de manière asynchrone.

        Args:
            concepts: Liste de concepts à classifier

        Returns:
            ClassificationBatchResult avec tous les résultats
        """
        if not concepts:
            return ClassificationBatchResult()

        results: List[ConceptClassification] = []
        concepts_for_llm: List[ConceptForClassification] = []

        # Étape 1: Appliquer heuristiques
        if self.use_heuristics:
            for concept in concepts:
                heuristic_result = self._apply_heuristics(concept)
                if heuristic_result:
                    results.append(heuristic_result)
                    logger.debug(
                        f"[CLASSIFIER:Heuristic] {concept.label[:30]}... -> {heuristic_result.concept_kind.value}"
                    )
                else:
                    concepts_for_llm.append(concept)

            logger.info(
                f"[CLASSIFIER] Heuristics: {len(results)} classified, "
                f"{len(concepts_for_llm)} need LLM"
            )
        else:
            concepts_for_llm = concepts

        # Étape 2: Classifier via LLM par batches
        if concepts_for_llm and self.llm_router:
            llm_results = await self._classify_with_llm_async(concepts_for_llm)
            results.extend(llm_results)

        # Étape 3: Construire résultat final
        keepable_count = sum(1 for r in results if r.is_keepable)
        non_keepable_count = len(results) - keepable_count

        batch_result = ClassificationBatchResult(
            results=results,
            total_processed=len(results),
            keepable_count=keepable_count,
            non_keepable_count=non_keepable_count
        )

        logger.info(
            f"[CLASSIFIER] Batch complete: {batch_result.total_processed} concepts, "
            f"{batch_result.keepable_count} keepable, {batch_result.non_keepable_count} filtered"
        )

        return batch_result

    async def _classify_with_llm_async(
        self,
        concepts: List[ConceptForClassification]
    ) -> List[ConceptClassification]:
        """
        Classifie concepts via LLM en batches.

        Args:
            concepts: Concepts à classifier

        Returns:
            Liste de classifications
        """
        all_results: List[ConceptClassification] = []

        # Découper en batches
        num_batches = (len(concepts) + self.batch_size - 1) // self.batch_size

        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(concepts))
            batch = concepts[start_idx:end_idx]

            logger.debug(
                f"[CLASSIFIER:LLM] Processing batch {batch_idx + 1}/{num_batches} "
                f"({len(batch)} concepts)"
            )

            try:
                batch_results = await self._call_llm_for_batch(batch)
                all_results.extend(batch_results)
            except Exception as e:
                logger.error(f"[CLASSIFIER:LLM] Batch {batch_idx + 1} failed: {e}")
                # Fallback: marquer comme abstract avec confiance faible
                for concept in batch:
                    all_results.append(ConceptClassification(
                        id=concept.id,
                        concept_kind=ConceptKind.ABSTRACT,
                        confidence=0.5,
                        is_keepable=True,
                        relabel_suggestion=None
                    ))

        return all_results

    async def _call_llm_for_batch(
        self,
        batch: List[ConceptForClassification]
    ) -> List[ConceptClassification]:
        """
        Appelle le LLM pour classifier un batch.

        Args:
            batch: Batch de concepts

        Returns:
            Liste de classifications
        """
        # Préparer input JSON
        input_data = {
            "concepts": [
                {
                    "id": c.id,
                    "label": c.label,
                    "context": c.context[:200] if c.context else None
                }
                for c in batch
            ]
        }
        input_json = json.dumps(input_data, ensure_ascii=False)

        # Construire prompt
        user_prompt = CLASSIFICATION_USER_PROMPT_TEMPLATE.format(input_json=input_json)

        # Appel LLM (utilise FAST_CLASSIFICATION pour classification rapide de concepts)
        response = await self.llm_router.acomplete(
            task_type=TaskType.FAST_CLASSIFICATION,
            messages=[
                {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=2000
        )

        # Parser réponse JSON
        try:
            # Nettoyer la réponse (enlever markdown si présent)
            response_text = response.strip()
            if response_text.startswith("```"):
                response_text = re.sub(r"```json?\n?", "", response_text)
                response_text = re.sub(r"\n?```$", "", response_text)

            parsed = json.loads(response_text)
            results_data = parsed.get("results", [])

            # Mapper aux objets
            results = []
            id_to_concept = {c.id: c for c in batch}

            for item in results_data:
                concept_id = item.get("id", "")
                if concept_id not in id_to_concept:
                    continue

                try:
                    kind = ConceptKind(item.get("concept_kind", "abstract"))
                except ValueError:
                    kind = ConceptKind.ABSTRACT

                results.append(ConceptClassification(
                    id=concept_id,
                    concept_kind=kind,
                    confidence=float(item.get("confidence", 0.7)),
                    is_keepable=item.get("is_keepable", kind in KEEPABLE_KINDS),
                    relabel_suggestion=item.get("relabel_suggestion")
                ))

            # Vérifier concepts manquants
            classified_ids = {r.id for r in results}
            for concept in batch:
                if concept.id not in classified_ids:
                    logger.warning(f"[CLASSIFIER:LLM] Concept {concept.id} not in response, defaulting to abstract")
                    results.append(ConceptClassification(
                        id=concept.id,
                        concept_kind=ConceptKind.ABSTRACT,
                        confidence=0.5,
                        is_keepable=True,
                        relabel_suggestion=None
                    ))

            return results

        except json.JSONDecodeError as e:
            logger.error(f"[CLASSIFIER:LLM] JSON parse error: {e}, response: {response_text[:200]}")
            # Fallback
            return [
                ConceptClassification(
                    id=c.id,
                    concept_kind=ConceptKind.ABSTRACT,
                    confidence=0.5,
                    is_keepable=True,
                    relabel_suggestion=None
                )
                for c in batch
            ]

    def classify_concepts_sync(
        self,
        concepts: List[Dict[str, Any]]
    ) -> ClassificationBatchResult:
        """
        Version synchrone pour intégration dans pipeline existant.

        Args:
            concepts: Liste de dicts avec 'concept_id', 'name', 'definition'

        Returns:
            ClassificationBatchResult
        """
        # Convertir en ConceptForClassification
        concepts_for_classification = [
            ConceptForClassification(
                id=c.get("concept_id") or c.get("id", f"c_{i}"),
                label=c.get("name") or c.get("label", ""),
                context=c.get("definition") or c.get("context")
            )
            for i, c in enumerate(concepts)
        ]

        # Exécuter async
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self.classify_batch_async(concepts_for_classification)
            )
            return result
        finally:
            loop.close()


def enrich_concepts_with_kind(
    concepts: List[Dict[str, Any]],
    classification_result: ClassificationBatchResult
) -> List[Dict[str, Any]]:
    """
    Enrichit les concepts avec leur classification.

    Args:
        concepts: Liste de concepts originaux
        classification_result: Résultats de classification

    Returns:
        Concepts enrichis avec concept_kind et is_keepable
    """
    id_to_classification = {r.id: r for r in classification_result.results}

    enriched = []
    for concept in concepts:
        concept_id = concept.get("concept_id") or concept.get("id", "")
        classification = id_to_classification.get(concept_id)

        enriched_concept = concept.copy()
        if classification:
            enriched_concept["concept_kind"] = classification.concept_kind.value
            enriched_concept["is_keepable"] = classification.is_keepable
            enriched_concept["kind_confidence"] = classification.confidence
            if classification.relabel_suggestion:
                enriched_concept["relabel_suggestion"] = classification.relabel_suggestion
        else:
            # Default: abstract, keepable
            enriched_concept["concept_kind"] = ConceptKind.ABSTRACT.value
            enriched_concept["is_keepable"] = True
            enriched_concept["kind_confidence"] = 0.5

        enriched.append(enriched_concept)

    return enriched
