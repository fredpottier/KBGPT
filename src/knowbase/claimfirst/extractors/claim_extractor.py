# src/knowbase/claimfirst/extractors/claim_extractor.py
"""
ClaimExtractor - Extraction de Claims documentées.

Réutilise AssertionUnitIndexer pour le mode pointer (verbatim garanti).

Charte de la "bonne Claim" (non négociable):
1. Dit UNE chose précise
2. Supportée par passage(s) verbatim exact(s)
3. Jamais exhaustive par défaut
4. Contextuelle (scope, conditions, version)
5. N'infère rien (pas de déduction)
6. Comparable (compatible/contradictoire/disjointe)
7. Peut NE PAS exister si le document est vague
8. Révisable par addition, jamais par réécriture

INV-1: La preuve d'une Claim est `unit_ids`, pas `passage_id`.
       Le LLM POINTE vers une unité au lieu de COPIER le texte.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

from knowbase.claimfirst.models.claim import Claim, ClaimType, ClaimScope
from knowbase.claimfirst.models.entity import is_valid_entity_name
from knowbase.claimfirst.models.passage import Passage
from knowbase.stratified.pass1.assertion_unit_indexer import (
    AssertionUnitIndexer,
    UnitIndexResult,
    AssertionUnit,
    format_units_for_llm,
)

logger = logging.getLogger(__name__)


# ============================================================================
# PRÉDICATS CANONIQUES — Liste fermée pour structured_form
# ============================================================================

CANONICAL_PREDICATES = frozenset({
    "USES", "REQUIRES", "BASED_ON", "SUPPORTS", "ENABLES",
    "PROVIDES", "EXTENDS", "REPLACES", "PART_OF",
    "INTEGRATED_IN", "COMPATIBLE_WITH", "CONFIGURES",
})

# Mapping statique pour synonymes évidents (Layer B)
# Le prompt durci (Layer A) devrait capturer 90%+, ceci rattrape le reste
PREDICATE_NORMALIZATION_MAP = {
    # → USES
    "USE": "USES", "CAN_USE": "USES", "LEVERAGES": "USES",
    "ADOPTS": "USES", "USED_FOR": "USES", "ARE_USED_TO": "USES",
    "CAN_BE_USED_VIA": "USES", "ACHIEVED_VIA": "USES",
    # → REQUIRES
    "DEPENDS_ON": "REQUIRES", "RELIES_ON": "REQUIRES", "NEEDS": "REQUIRES",
    "COMPLIES_WITH": "REQUIRES",
    # → BASED_ON
    "IS_BASED_ON": "BASED_ON", "RUNS_ON": "BASED_ON",
    "RUNS_IN": "BASED_ON", "HOSTED_IN": "BASED_ON",
    # → SUPPORTS
    "SUPPORTED_BY": "SUPPORTS",
    # → ENABLES
    "ACTIVATES": "ENABLES", "ALLOW": "ENABLES", "ALLOWS": "ENABLES",
    "ENABLING": "ENABLES",
    # → PROVIDES
    "OFFERS": "PROVIDES", "DELIVERS": "PROVIDES", "BRINGS": "PROVIDES",
    "IS_OFFERED_BY": "PROVIDES", "OFFERED_BY": "PROVIDES",
    "IS_PROVIDED_BY": "PROVIDES",
    # → INTEGRATED_IN
    "IS_INTEGRATED_IN": "INTEGRATED_IN", "INTEGRATES": "INTEGRATED_IN",
    "INTEGRATED_WITH": "INTEGRATED_IN", "INTEGRATES_WITH": "INTEGRATED_IN",
    "EMBEDDED_IN": "INTEGRATED_IN", "INSTALLED_ON": "INTEGRATED_IN",
    # → PART_OF
    "IS_PART_OF": "PART_OF", "IS_A_MODULE_IN": "PART_OF",
    "IS_A_COMPONENT_OF": "PART_OF", "INCLUDED_IN": "PART_OF",
    "IS_INCLUDED_IN": "PART_OF", "IS_A_FEATURE_IN": "PART_OF",
    "IS_A_FEATURE_OF": "PART_OF", "ARE_FEATURES_OF": "PART_OF",
    "IS_A_NEW_FEATURE_IN": "PART_OF", "FOUND_IN": "PART_OF",
    # → REPLACES
    "SUPERSEDES": "REPLACES", "MIGRATES": "REPLACES",
    "CAN_BE_MIGRATED_TO": "REPLACES", "CONVERTED_TO": "REPLACES",
    # → EXTENDS
    "IS_AN_ADD_ON_FOR": "EXTENDS",
    # → COMPATIBLE_WITH
    "CO-DEPLOYED_WITH": "COMPATIBLE_WITH", "CONNECTS_WITH": "COMPATIBLE_WITH",
    # → CONFIGURES
    "MANAGED_BY": "CONFIGURES", "MANAGES": "CONFIGURES",
}


def normalize_predicate(raw_predicate: str) -> Optional[str]:
    """
    Normalise un prédicat vers la whitelist canonique (Layer B).

    Returns:
        Le prédicat canonique, ou None si non mappable.
    """
    pred = raw_predicate.strip().upper().replace(" ", "_")
    if pred in CANONICAL_PREDICATES:
        return pred
    mapped = PREDICATE_NORMALIZATION_MAP.get(pred)
    if mapped:
        return mapped
    return None


# ============================================================================
# PROMPT V2.1 — Prédicats contraints (Layer A)
# ============================================================================

# Note: Les {{ et }} sont échappés pour str.format()
CLAIM_EXTRACTION_PROMPT_TEMPLATE = """You are an expert in structured knowledge extraction from documents.

You receive numbered text units (U1, U2, etc.) from a document.
Your task is to identify CLAIMS — precise, documented assertions useful
for building a knowledge graph.

{domain_context}
## Document context

Title: {doc_title}
Type: {doc_type}
Primary subject: {doc_subject}
Current section: {section_title}
Key concepts in this section: {section_concepts}

## Value grid (IMPORTANT)

Not all claims have the same value. Prioritize in this order:

**HIGH VALUE** — Relational claims between two named entities:
- X uses / is based on / requires Y
- X replaces / succeeds Y
- X is integrated in / embedded in Y
- X is compatible with / supports Y
→ For these claims, fill the `structured_form` field.

**MEDIUM VALUE** — Specific factual claims with an identifiable subject:
- X offers a specific capability
- X has a specific limitation / constraint
→ `structured_form` = null

**DO NOT EXTRACT**:
- Fragments without a verb or identifiable subject ("reduce costs", "improve tracking")
- Generic user actions without specificity ("You can define...", "Users can create...")
  UNLESS they reveal a specific technical capability
- Reformulations of section titles
- Legal texts, disclaimers, copyrights

## Claim types

- FACTUAL: Verifiable factual assertion
- PRESCRIPTIVE: Obligation or prohibition
- DEFINITIONAL: Definition or description
- CONDITIONAL: Conditional assertion
- PERMISSIVE: Permission or authorization
- PROCEDURAL: Step or process

## Response format (JSON)

[
  {{
    "claim_text": "Self-contained synthetic formulation of the claim",
    "claim_type": "FACTUAL",
    "unit_id": "U1",
    "confidence": 0.95,
    "scope": {{"version": null, "region": null, "edition": null, "conditions": []}},
    "structured_form": {{
      "subject": "Name of the subject entity",
      "predicate": "USES",
      "object": "Name of the object entity"
    }}
  }}
]

## STRICT CONSTRAINT — structured_form predicates

You MUST choose EXACTLY one predicate from this CLOSED list (12 predicates):

| Predicate | Meaning |
|-----------|---------|
| USES | X explicitly uses Y as a tool, technology, or component |
| REQUIRES | X needs Y to function (includes "depends on") |
| BASED_ON | X is built on, derived from, or runs on Y |
| SUPPORTS | X supports or is designed for Y |
| ENABLES | X makes possible a specific named capability Y |
| PROVIDES | X provides, delivers, or offers Y |
| EXTENDS | X extends or adds functionality to Y |
| REPLACES | X replaces, supersedes, or succeeds Y |
| PART_OF | X is a module, component, or feature of Y |
| INTEGRATED_IN | X is integrated or embedded in Y |
| COMPATIBLE_WITH | X is compatible with or works alongside Y |
| CONFIGURES | X configures, manages, or controls Y |

**RULES:**
- NEVER invent a predicate outside this list. No IS_A_FEATURE_IN, no OFFERS, no INCLUDES.
- If the relationship does not fit any predicate above, set "structured_form": null.
- USES: Only when X explicitly uses Y. NOT for "users use X" or "X can be used".
- ENABLES: Only when X enables a specific named capability Y. NOT for "enables users to...".
- Subject and object must be proper nouns or technical terms, NOT descriptions or clauses.
- If no clear relation between two named entities → "structured_form": null.

## Rules

- DO NOT copy the text. Point to unit_ids only.
- If a unit does not contain a useful claim, IGNORE it.
- The claim must be self-contained and understandable without reading the source unit.
- Prefer abstention over invention. Prefer precision over quantity.
- IMPORTANT: Write all claim_text in the SAME LANGUAGE as the source document units.

## Units to analyze

{units_text}

Return ONLY the JSON array, no explanation."""


def build_claim_extraction_prompt(
    units_text: str,
    doc_title: str,
    doc_type: str,
    doc_subject: str = "",
    section_title: str = "",
    section_concepts: str = "",
    domain_context: str = "",
) -> str:
    """Construit le prompt d'extraction de claims (V2 enrichi)."""
    return CLAIM_EXTRACTION_PROMPT_TEMPLATE.format(
        units_text=units_text,
        doc_title=doc_title,
        doc_type=doc_type,
        doc_subject=doc_subject or "Unknown",
        section_title=section_title or "N/A",
        section_concepts=section_concepts or "N/A",
        domain_context=domain_context,
    )


# Nombre max d'appels LLM en parallèle (évite de surcharger vLLM/OpenAI)
MAX_CONCURRENT_LLM_CALLS = 10


@dataclass
class BatchTask:
    """Tâche de batch pour extraction parallèle."""
    batch_id: int
    units: List[AssertionUnit]
    passage: Passage
    unit_result: UnitIndexResult
    tenant_id: str
    doc_id: str
    doc_title: str
    doc_type: str
    doc_subject: str = ""
    section_title: str = ""
    section_concepts: str = ""
    domain_context: str = ""


class ClaimExtractor:
    """
    Extracteur de Claims documentées.

    Utilise AssertionUnitIndexer pour segmenter le texte en unités,
    puis le LLM pour identifier les claims en mode pointer.

    Le verbatim est GARANTI car reconstruit depuis l'index d'unités.

    Les appels LLM sont parallélisés pour optimiser les performances.
    """

    def __init__(
        self,
        llm_client: Any,
        min_unit_length: int = 30,
        max_unit_length: int = 500,
        batch_size: int = 10,
        max_concurrent: int = MAX_CONCURRENT_LLM_CALLS,
    ):
        """
        Initialise l'extracteur.

        Args:
            llm_client: Client LLM pour l'extraction (non utilisé, gardé pour compatibilité)
            min_unit_length: Longueur minimale d'une unité
            max_unit_length: Longueur maximale d'une unité
            batch_size: Nombre d'unités par batch LLM
            max_concurrent: Nombre max d'appels LLM en parallèle
        """
        self.llm_client = llm_client
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent

        # Indexer pour segmentation
        self.unit_indexer = AssertionUnitIndexer(
            min_unit_length=min_unit_length,
            max_unit_length=max_unit_length,
        )

        # Stats
        self.stats = {
            "units_indexed": 0,
            "llm_calls": 0,
            "tokens_used": 0,
            "claims_extracted": 0,
            "claims_rejected": 0,
            "predicates_canonical": 0,
            "predicates_normalized": 0,
            "predicates_retried": 0,
            "predicates_dropped": 0,
            "sf_dropped_invalid_entity": 0,
        }

    def extract(
        self,
        passages: List[Passage],
        tenant_id: str,
        doc_id: str,
        doc_title: str = "",
        doc_type: str = "technical",
        doc_subject: str = "",
        domain_context: str = "",
    ) -> Tuple[List[Claim], Dict[str, UnitIndexResult]]:
        """
        Extrait les Claims des passages.

        Args:
            passages: Liste de Passages à traiter
            tenant_id: Tenant ID
            doc_id: Document ID
            doc_title: Titre du document (contexte)
            doc_type: Type de document (contexte)
            doc_subject: Sujet principal du document (contexte V2)
            domain_context: Bloc de contexte métier injecté dans le prompt (V2)

        Returns:
            Tuple (claims, unit_index) où unit_index permet de retrouver le verbatim
        """
        claims: List[Claim] = []
        unit_index: Dict[str, UnitIndexResult] = {}

        # Phase 1: Indexer tous les passages en unités
        logger.info(f"[OSMOSE:ClaimExtractor] Indexing {len(passages)} passages...")
        for passage in passages:
            result = self.unit_indexer.index_docitem(
                docitem_id=passage.passage_id,
                text=passage.text,
                item_type=passage.item_type,
            )
            if result.units:
                unit_index[passage.passage_id] = result
                self.stats["units_indexed"] += len(result.units)

        logger.info(
            f"[OSMOSE:ClaimExtractor] Indexed {self.stats['units_indexed']} units "
            f"from {len(unit_index)} passages"
        )

        # Phase 2: Collecter tous les batches à traiter
        batch_tasks: List[BatchTask] = []
        batch_id = 0

        for passage_id, unit_result in unit_index.items():
            passage = next((p for p in passages if p.passage_id == passage_id), None)
            if not passage:
                continue

            # Créer une tâche par batch
            for i in range(0, len(unit_result.units), self.batch_size):
                batch_units = unit_result.units[i:i + self.batch_size]
                batch_tasks.append(BatchTask(
                    batch_id=batch_id,
                    units=batch_units,
                    passage=passage,
                    unit_result=unit_result,
                    tenant_id=tenant_id,
                    doc_id=doc_id,
                    doc_title=doc_title,
                    doc_type=doc_type,
                    doc_subject=doc_subject,
                    section_title=passage.section_title or "",
                    section_concepts="",
                    domain_context=domain_context,
                ))
                batch_id += 1

        logger.info(
            f"[OSMOSE:ClaimExtractor] Processing {len(batch_tasks)} batches "
            f"with max {self.max_concurrent} concurrent LLM calls..."
        )

        # Phase 3: Exécuter tous les batches en parallèle
        if batch_tasks:
            claims = asyncio.run(self._extract_all_batches_async(batch_tasks))
        else:
            claims = []

        logger.info(
            f"[OSMOSE:ClaimExtractor] Extracted {len(claims)} claims "
            f"({self.stats['llm_calls']} LLM calls)"
        )

        return claims, unit_index

    async def _extract_all_batches_async(
        self,
        batch_tasks: List[BatchTask],
    ) -> List[Claim]:
        """
        Exécute tous les batches en parallèle avec un semaphore.

        Args:
            batch_tasks: Liste des tâches de batch

        Returns:
            Liste de toutes les claims extraites
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)
        all_claims: List[Claim] = []
        lock = asyncio.Lock()

        async def process_batch(task: BatchTask) -> None:
            async with semaphore:
                try:
                    claims = await self._extract_claims_from_units_async(task)
                    async with lock:
                        all_claims.extend(claims)
                except Exception as e:
                    logger.error(f"[OSMOSE:ClaimExtractor] Batch {task.batch_id} failed: {e}")

        # Lancer toutes les tâches en parallèle
        await asyncio.gather(*[process_batch(task) for task in batch_tasks])

        return all_claims

    async def _extract_claims_from_units_async(
        self,
        task: BatchTask,
    ) -> List[Claim]:
        """
        Version async de _extract_claims_from_units.

        Utilise le LLM Router async pour bénéficier de la parallélisation.
        """
        if not task.units:
            return []

        # Formatter les unités pour le LLM
        units_text = format_units_for_llm(task.units)

        # Construire le prompt V2 (enrichi avec contexte)
        prompt = build_claim_extraction_prompt(
            units_text=units_text,
            doc_title=task.doc_title or "Unknown",
            doc_type=task.doc_type,
            doc_subject=task.doc_subject,
            section_title=task.section_title,
            section_concepts=task.section_concepts,
            domain_context=task.domain_context,
        )

        # Appel LLM async
        try:
            response = await self._call_llm_async(prompt)
            self.stats["llm_calls"] += 1

            # Parser la réponse JSON
            raw_claims = self._parse_llm_response(response)

        except Exception as e:
            logger.error(f"[OSMOSE:ClaimExtractor] LLM error: {e}")
            return []

        # Construire les Claims avec verbatim garanti
        claims = []
        claims_needing_retry: List[Tuple[Claim, str]] = []  # (claim, raw_predicate)

        for raw in raw_claims:
            try:
                claim, needs_retry = self._build_claim_with_predicate_check(
                    raw=raw,
                    units=task.units,
                    unit_result=task.unit_result,
                    passage=task.passage,
                    tenant_id=task.tenant_id,
                    doc_id=task.doc_id,
                )
                if claim:
                    claims.append(claim)
                    self.stats["claims_extracted"] += 1
                    if needs_retry:
                        claims_needing_retry.append((claim, needs_retry))
                else:
                    self.stats["claims_rejected"] += 1
            except Exception as e:
                logger.warning(f"[OSMOSE:ClaimExtractor] Failed to build claim: {e}")
                self.stats["claims_rejected"] += 1

        # Layer C: Retry LLM pour les prédicats non canoniques
        if claims_needing_retry:
            await self._retry_predicates_async(claims_needing_retry)

        return claims

    async def _retry_predicates_async(
        self,
        claims_to_fix: List[Tuple[Claim, str]],
    ) -> None:
        """
        Layer C — Retry LLM batch pour remapper les prédicats non canoniques.

        Envoie un seul appel LLM avec toutes les claims à corriger,
        puis met à jour les structured_form in-place.
        Gratuit sur vLLM (EC2), seul le temps compte.
        """
        predicates_list = ", ".join(sorted(CANONICAL_PREDICATES))

        items_text = "\n".join(
            f'{i+1}. Claim: "{c.text[:120]}" | '
            f'Subject: {c.structured_form["subject"]} | '
            f'Predicate: {raw_pred} | '
            f'Object: {c.structured_form["object"]}'
            for i, (c, raw_pred) in enumerate(claims_to_fix)
        )

        prompt = f"""The following claims have predicates NOT in the allowed list.
For each, choose the CLOSEST valid predicate from: {predicates_list}

If no predicate fits at all, reply "NONE" for that claim.

Claims to fix:
{items_text}

Reply ONLY with a JSON array, one entry per claim:
[{{"index": 1, "predicate": "PART_OF"}}, {{"index": 2, "predicate": "NONE"}}]"""

        try:
            response = await self._call_llm_async(prompt)
            self.stats["llm_calls"] += 1
            fixes = self._parse_llm_response(response)

            if isinstance(fixes, list):
                for fix in fixes:
                    idx = fix.get("index")
                    new_pred = fix.get("predicate", "").strip().upper()
                    if not idx or not isinstance(idx, int):
                        continue
                    if idx < 1 or idx > len(claims_to_fix):
                        continue

                    claim, raw_pred = claims_to_fix[idx - 1]

                    if new_pred in CANONICAL_PREDICATES:
                        claim.structured_form["predicate"] = new_pred
                        self.stats["predicates_retried"] += 1
                        logger.debug(
                            f"[OSMOSE:ClaimExtractor] Predicate retry: "
                            f"{raw_pred} → {new_pred}"
                        )
                        # Valider S/O après correction du prédicat
                        subj = claim.structured_form["subject"]
                        obj = claim.structured_form["object"]
                        if not is_valid_entity_name(subj) or not is_valid_entity_name(obj):
                            claim.structured_form = None
                            self.stats["sf_dropped_invalid_entity"] += 1
                    else:
                        # NONE ou invalide → drop le structured_form
                        claim.structured_form = None
                        self.stats["predicates_dropped"] += 1
                        logger.debug(
                            f"[OSMOSE:ClaimExtractor] Predicate dropped after retry: "
                            f"{raw_pred}"
                        )

        except Exception as e:
            logger.warning(f"[OSMOSE:ClaimExtractor] Predicate retry failed: {e}")
            # En cas d'échec du retry, drop tous les structured_form non canoniques
            for claim, raw_pred in claims_to_fix:
                claim.structured_form = None
                self.stats["predicates_dropped"] += 1

    async def _call_llm_async(self, prompt: str) -> str:
        """
        Version async de _call_llm.

        Utilise le LLM Router async pour la parallélisation.
        """
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()

        messages = [
            {"role": "system", "content": "You are an expert in structured knowledge extraction."},
            {"role": "user", "content": prompt}
        ]

        # Appel async via le router (utilise vLLM si burst mode actif)
        response = await router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=0.1,
            max_tokens=1500,
        )

        return response

    def _extract_claims_from_units(
        self,
        units: List[AssertionUnit],
        passage: Passage,
        unit_result: UnitIndexResult,
        tenant_id: str,
        doc_id: str,
        doc_title: str,
        doc_type: str,
        doc_subject: str = "",
        section_title: str = "",
        section_concepts: str = "",
        domain_context: str = "",
    ) -> List[Claim]:
        """
        Extrait les claims d'un batch d'unités via LLM.

        Le LLM retourne des unit_ids, pas du texte.
        Le verbatim est reconstruit depuis l'index (GARANTI).
        """
        if not units:
            return []

        # Formatter les unités pour le LLM
        units_text = format_units_for_llm(units)

        # Construire le prompt V2 (enrichi avec contexte)
        prompt = build_claim_extraction_prompt(
            units_text=units_text,
            doc_title=doc_title or "Unknown",
            doc_type=doc_type,
            doc_subject=doc_subject,
            section_title=section_title,
            section_concepts=section_concepts,
            domain_context=domain_context,
        )

        # Appel LLM
        try:
            response = self._call_llm(prompt)
            self.stats["llm_calls"] += 1

            # Parser la réponse JSON
            raw_claims = self._parse_llm_response(response)

        except Exception as e:
            logger.error(f"[OSMOSE:ClaimExtractor] LLM error: {e}")
            return []

        # Construire les Claims avec verbatim garanti
        claims = []
        for raw in raw_claims:
            try:
                claim = self._build_claim(
                    raw=raw,
                    units=units,
                    unit_result=unit_result,
                    passage=passage,
                    tenant_id=tenant_id,
                    doc_id=doc_id,
                )
                if claim:
                    claims.append(claim)
                    self.stats["claims_extracted"] += 1
                else:
                    self.stats["claims_rejected"] += 1
            except Exception as e:
                logger.warning(f"[OSMOSE:ClaimExtractor] Failed to build claim: {e}")
                self.stats["claims_rejected"] += 1

        return claims

    def _call_llm(self, prompt: str) -> str:
        """
        Appelle le LLM pour extraire les claims.

        Utilise le LLM Router pour bénéficier du mode Burst (vLLM sur EC2).
        """
        # Utiliser le LLM Router pour le mode Burst
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()

        messages = [
            {"role": "system", "content": "You are an expert in structured knowledge extraction."},
            {"role": "user", "content": prompt}
        ]

        # Appel via le router (utilise vLLM si burst mode actif)
        response = router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=0.1,  # Déterministe
            max_tokens=1500,
        )

        return response

    def _parse_llm_response(self, response: str) -> List[dict]:
        """
        Parse la réponse JSON du LLM.

        Gère les formats malformés et les erreurs.
        """
        if not response:
            return []

        # Nettoyer la réponse
        response = response.strip()

        # Extraire le JSON si encapsulé
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if end > start:
                response = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end > start:
                response = response[start:end].strip()

        try:
            data = json.loads(response)

            # Gérer différents formats de réponse
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # Le LLM peut encapsuler dans {"claims": [...]}
                if "claims" in data:
                    return data["claims"]
                # Ou retourner un seul objet claim
                else:
                    return [data]
            else:
                return []

        except json.JSONDecodeError as e:
            logger.warning(f"[OSMOSE:ClaimExtractor] JSON parse error: {e}")
            return []

    def _build_claim_with_predicate_check(
        self,
        raw: dict,
        units: List[AssertionUnit],
        unit_result: UnitIndexResult,
        passage: Passage,
        tenant_id: str,
        doc_id: str,
    ) -> Tuple[Optional[Claim], Optional[str]]:
        """
        Construit une Claim avec normalisation de prédicat (Layer A+B).

        Returns:
            (claim, raw_predicate_for_retry)
            - Si prédicat canonique ou normalisé → (claim, None)
            - Si prédicat non mappable → (claim avec structured_form intact, raw_predicate)
              Le caller async enverra un retry LLM (Layer C).
            - Si claim invalide → (None, None)
        """
        claim = self._build_claim_core(raw, units, unit_result, passage, tenant_id, doc_id)
        if not claim:
            return None, None

        # Pas de structured_form → rien à normaliser
        if not claim.structured_form:
            return claim, None

        raw_pred = claim.structured_form["predicate"]

        # Layer B: normalisation statique
        canonical = normalize_predicate(raw_pred)
        if canonical:
            if raw_pred.upper() in CANONICAL_PREDICATES:
                self.stats["predicates_canonical"] += 1
            else:
                self.stats["predicates_normalized"] += 1
                logger.debug(
                    f"[OSMOSE:ClaimExtractor] Predicate normalized: "
                    f"{raw_pred} → {canonical}"
                )
            claim.structured_form["predicate"] = canonical

            # Layer B.5: validation sujet/objet (stoplist, fragments de phrase)
            subj = claim.structured_form["subject"]
            obj = claim.structured_form["object"]
            if not is_valid_entity_name(subj) or not is_valid_entity_name(obj):
                self.stats["sf_dropped_invalid_entity"] += 1
                logger.debug(
                    f"[OSMOSE:ClaimExtractor] SF dropped — invalid entity: "
                    f"S={subj!r} O={obj!r}"
                )
                claim.structured_form = None

            return claim, None

        # Non mappable → marquer pour retry LLM (Layer C)
        return claim, raw_pred

    def _build_claim(
        self,
        raw: dict,
        units: List[AssertionUnit],
        unit_result: UnitIndexResult,
        passage: Passage,
        tenant_id: str,
        doc_id: str,
    ) -> Optional[Claim]:
        """
        Construit une Claim avec normalisation (Layer A+B, sans retry).

        Utilisé par le path synchrone. Les prédicats non mappables
        entraînent le drop du structured_form.
        """
        claim, needs_retry = self._build_claim_with_predicate_check(
            raw, units, unit_result, passage, tenant_id, doc_id,
        )
        if claim and needs_retry:
            # Path sync: pas de retry, on drop le structured_form
            logger.debug(
                f"[OSMOSE:ClaimExtractor] Predicate dropped (sync): {needs_retry}"
            )
            claim.structured_form = None
            self.stats["predicates_dropped"] += 1
        return claim

    def _build_claim_core(
        self,
        raw: dict,
        units: List[AssertionUnit],
        unit_result: UnitIndexResult,
        passage: Passage,
        tenant_id: str,
        doc_id: str,
    ) -> Optional[Claim]:
        """
        Construit une Claim depuis la sortie LLM (logique commune).

        Le verbatim est GARANTI car reconstruit depuis l'index d'unités.
        """
        # Extraire les champs
        claim_text = raw.get("claim_text", "").strip()
        unit_id = raw.get("unit_id", "").strip()
        claim_type_str = raw.get("claim_type", "FACTUAL").upper()
        confidence = float(raw.get("confidence", 0.8))

        # Valider les champs obligatoires
        if not claim_text or len(claim_text) < 10:
            logger.debug(f"[OSMOSE:ClaimExtractor] Rejected: claim_text too short")
            return None

        if not unit_id:
            logger.debug(f"[OSMOSE:ClaimExtractor] Rejected: no unit_id")
            return None

        # Retrouver l'unité source
        unit = unit_result.get_unit_by_local_id(unit_id)
        if not unit:
            logger.debug(f"[OSMOSE:ClaimExtractor] Rejected: unit {unit_id} not found")
            return None

        # VERBATIM GARANTI: reconstruit depuis l'index
        verbatim_quote = unit.text

        # Parser le type de claim
        try:
            claim_type = ClaimType(claim_type_str)
        except ValueError:
            claim_type = ClaimType.FACTUAL

        # Parser le scope
        scope_data = raw.get("scope", {})
        scope = ClaimScope(
            version=scope_data.get("version"),
            region=scope_data.get("region"),
            edition=scope_data.get("edition"),
            conditions=scope_data.get("conditions", []),
        )

        # Parser le structured_form
        structured_form = None
        sf_raw = raw.get("structured_form")
        if sf_raw and isinstance(sf_raw, dict):
            subj = sf_raw.get("subject", "").strip()
            pred = sf_raw.get("predicate", "").strip()
            obj = sf_raw.get("object", "").strip()
            if subj and pred and obj:
                structured_form = {
                    "subject": subj,
                    "predicate": pred,
                    "object": obj,
                }

        # Générer l'ID unique
        claim_id = f"claim_{uuid.uuid4().hex[:12]}"

        # Construire la Claim
        return Claim(
            claim_id=claim_id,
            tenant_id=tenant_id,
            doc_id=doc_id,
            text=claim_text,
            claim_type=claim_type,
            scope=scope,
            verbatim_quote=verbatim_quote,
            passage_id=passage.passage_id,
            unit_ids=[unit.unit_global_id],
            confidence=confidence,
            structured_form=structured_form,
        )

    def get_stats(self) -> dict:
        """Retourne les statistiques d'extraction."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "units_indexed": 0,
            "llm_calls": 0,
            "tokens_used": 0,
            "claims_extracted": 0,
            "claims_rejected": 0,
            "predicates_canonical": 0,
            "predicates_normalized": 0,
            "predicates_retried": 0,
            "predicates_dropped": 0,
            "sf_dropped_invalid_entity": 0,
        }


class MockLLMClient:
    """
    Client LLM mock pour les tests.

    Retourne des réponses prédéfinies basées sur le contenu.
    """

    def generate(self, prompt: str) -> str:
        """Génère une réponse mock."""
        # Détecter les patterns dans le prompt pour générer des claims
        claims = []

        # Pattern: TLS version
        if "tls" in prompt.lower() or "encryption" in prompt.lower():
            claims.append({
                "claim_text": "TLS 1.2 or higher is required for all connections",
                "claim_type": "PRESCRIPTIVE",
                "unit_id": "U1",
                "confidence": 0.9,
                "scope": {"version": None, "region": None, "edition": None, "conditions": []}
            })

        # Pattern: backup
        if "backup" in prompt.lower():
            claims.append({
                "claim_text": "Daily backups are performed automatically",
                "claim_type": "FACTUAL",
                "unit_id": "U1",
                "confidence": 0.85,
                "scope": {"version": None, "region": None, "edition": None, "conditions": []}
            })

        return json.dumps(claims)


__all__ = [
    "ClaimExtractor",
    "MockLLMClient",
    "build_claim_extraction_prompt",
    "CANONICAL_PREDICATES",
    "normalize_predicate",
]
