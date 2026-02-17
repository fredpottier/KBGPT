# src/knowbase/claimfirst/composition/slot_enricher.py
"""
SlotEnricher — Enrichissement LLM des structured_form manquants.

Pour les claims existantes sans triplet S/P/O, envoie un prompt focalisé
au LLM pour extraire {subject, predicate, object} ou null.

Validation post-LLM :
  - normalize_predicate(pred) doit réussir
  - is_valid_entity_name(subject) et is_valid_entity_name(object) doivent être vrais
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.entity import is_valid_entity_name

# ============================================================================
# Prédicats canoniques — copie locale pour éviter l'import lourd de
# claim_extractor (qui tire assertion_unit_indexer → structural → yaml, etc.)
# Source of truth : claim_extractor.CANONICAL_PREDICATES
# ============================================================================

_CANONICAL_PREDICATES = frozenset({
    "USES", "REQUIRES", "BASED_ON", "SUPPORTS", "ENABLES",
    "PROVIDES", "EXTENDS", "REPLACES", "PART_OF",
    "INTEGRATED_IN", "COMPATIBLE_WITH", "CONFIGURES",
})

_PREDICATE_NORMALIZATION_MAP = {
    "USE": "USES", "CAN_USE": "USES", "LEVERAGES": "USES",
    "ADOPTS": "USES", "USED_FOR": "USES", "ARE_USED_TO": "USES",
    "CAN_BE_USED_VIA": "USES", "ACHIEVED_VIA": "USES",
    "DEPENDS_ON": "REQUIRES", "RELIES_ON": "REQUIRES", "NEEDS": "REQUIRES",
    "COMPLIES_WITH": "REQUIRES",
    "IS_BASED_ON": "BASED_ON", "RUNS_ON": "BASED_ON",
    "RUNS_IN": "BASED_ON", "HOSTED_IN": "BASED_ON",
    "SUPPORTED_BY": "SUPPORTS",
    "ACTIVATES": "ENABLES", "ALLOW": "ENABLES", "ALLOWS": "ENABLES",
    "ENABLING": "ENABLES",
    "OFFERS": "PROVIDES", "DELIVERS": "PROVIDES", "BRINGS": "PROVIDES",
    "IS_OFFERED_BY": "PROVIDES", "OFFERED_BY": "PROVIDES",
    "IS_PROVIDED_BY": "PROVIDES",
    "IS_INTEGRATED_IN": "INTEGRATED_IN", "INTEGRATES": "INTEGRATED_IN",
    "INTEGRATED_WITH": "INTEGRATED_IN", "INTEGRATES_WITH": "INTEGRATED_IN",
    "EMBEDDED_IN": "INTEGRATED_IN", "INSTALLED_ON": "INTEGRATED_IN",
    "IS_PART_OF": "PART_OF", "IS_A_MODULE_IN": "PART_OF",
    "IS_A_COMPONENT_OF": "PART_OF", "INCLUDED_IN": "PART_OF",
    "IS_INCLUDED_IN": "PART_OF", "IS_A_FEATURE_IN": "PART_OF",
    "IS_A_FEATURE_OF": "PART_OF", "ARE_FEATURES_OF": "PART_OF",
    "IS_A_NEW_FEATURE_IN": "PART_OF", "FOUND_IN": "PART_OF",
    "SUPERSEDES": "REPLACES", "MIGRATES": "REPLACES",
    "CAN_BE_MIGRATED_TO": "REPLACES", "CONVERTED_TO": "REPLACES",
    "IS_AN_ADD_ON_FOR": "EXTENDS",
    "CO-DEPLOYED_WITH": "COMPATIBLE_WITH", "CONNECTS_WITH": "COMPATIBLE_WITH",
    "MANAGED_BY": "CONFIGURES", "MANAGES": "CONFIGURES",
}


def _normalize_predicate(raw_predicate: str) -> Optional[str]:
    """Normalise un prédicat vers la whitelist canonique."""
    pred = raw_predicate.strip().upper().replace(" ", "_")
    if pred in _CANONICAL_PREDICATES:
        return pred
    mapped = _PREDICATE_NORMALIZATION_MAP.get(pred)
    if mapped:
        return mapped
    return None

logger = logging.getLogger(__name__)

BATCH_SIZE = 15
MAX_CONCURRENT = 5

SLOT_ENRICHMENT_PROMPT = """Extract structured triplets from claims. Return ONLY a JSON array, no extra text or explanation.

## Predicates (CLOSED list, 12 only)

| Predicate | Meaning |
|-----------|---------|
| USES | X explicitly uses Y |
| REQUIRES | X needs Y to function |
| BASED_ON | X is built on or derived from Y |
| SUPPORTS | X supports or is designed for Y |
| ENABLES | X makes possible capability Y |
| PROVIDES | X provides, delivers, or offers Y |
| EXTENDS | X extends or adds functionality to Y |
| REPLACES | X replaces, supersedes, or succeeds Y |
| PART_OF | X is a module, component, or feature of Y |
| INTEGRATED_IN | X is integrated or embedded in Y |
| COMPATIBLE_WITH | X is compatible with or works alongside Y |
| CONFIGURES | X configures, manages, or controls Y |

RULES:
- Subject and object must be proper nouns or technical terms, NOT descriptions.
- If no clear relation between two named entities → null.
- If the predicate does not fit any of the 12 → null.
- Prefer null over invention.
- Use "Known entities" when listed. Do NOT invent entities not in the claim.

## Claims

{claims_block}

## Response — ONLY a JSON array, one entry per claim, no comments:
[{{"index":1,"structured_form":{{"subject":"SAP S/4HANA","predicate":"USES","object":"SAP HANA"}}}},{{"index":2,"structured_form":null}}]"""


@dataclass
class SlotEnrichmentResult:
    """Résultat d'un enrichissement de slots."""

    claims_processed: int = 0
    claims_enriched: int = 0
    claims_null: int = 0
    claims_rejected: int = 0
    llm_calls: int = 0
    llm_tokens_used: int = 0


class SlotEnricher:
    """
    Enrichit les claims sans structured_form via un prompt LLM focalisé.

    Batch de BATCH_SIZE claims par appel LLM, avec validation post-LLM.
    """

    def __init__(
        self,
        batch_size: int = BATCH_SIZE,
        max_concurrent: int = MAX_CONCURRENT,
    ):
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self._stats = {
            "claims_processed": 0,
            "claims_enriched": 0,
            "claims_null": 0,
            "claims_rejected": 0,
            "llm_calls": 0,
        }

    def enrich(
        self,
        claims: list,
        entity_names_by_claim: Optional[Dict[str, List[str]]] = None,
    ) -> SlotEnrichmentResult:
        """
        Enrichit les claims sans structured_form (sync wrapper).

        Args:
            claims: Liste de Claim objects sans structured_form
            entity_names_by_claim: Dict claim_id → [entity_names] (optionnel)

        Returns:
            SlotEnrichmentResult avec les statistiques
        """
        if not claims:
            return SlotEnrichmentResult()

        entity_names_by_claim = entity_names_by_claim or {}

        # Préparer les batches
        batches = self._prepare_batches(claims, entity_names_by_claim)

        # Exécuter async
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, self._enrich_all_async(batches, claims)
                    ).result()
            else:
                result = asyncio.run(self._enrich_all_async(batches, claims))
        except RuntimeError:
            result = asyncio.run(self._enrich_all_async(batches, claims))

        return result

    def enrich_from_dicts(
        self,
        claim_dicts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Enrichit des dicts de claims (pour le script rétroactif).

        Chaque dict doit contenir :
          - claim_id: str
          - text: str
          - claim_type: str (optionnel)
          - entity_names: List[str] (optionnel)

        Returns:
            Liste de dicts enrichis : {claim_id, structured_form}
        """
        if not claim_dicts:
            return []

        batches = self._prepare_batches_from_dicts(claim_dicts)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    enriched = pool.submit(
                        asyncio.run, self._enrich_dicts_async(batches)
                    ).result()
            else:
                enriched = asyncio.run(self._enrich_dicts_async(batches))
        except RuntimeError:
            enriched = asyncio.run(self._enrich_dicts_async(batches))

        return enriched

    def _prepare_batches(
        self,
        claims: list,
        entity_names_by_claim: Dict[str, List[str]],
    ) -> List[List[Tuple[int, Any, List[str]]]]:
        """Prépare les batches : (index_in_batch, claim, entity_names)."""
        items = []
        for claim in claims:
            entities = entity_names_by_claim.get(claim.claim_id, [])
            items.append((claim, entities))

        batches = []
        for i in range(0, len(items), self.batch_size):
            batch = []
            for j, (claim, entities) in enumerate(items[i:i + self.batch_size]):
                batch.append((j + 1, claim, entities))
            batches.append(batch)

        return batches

    def _prepare_batches_from_dicts(
        self,
        claim_dicts: List[Dict[str, Any]],
    ) -> List[List[Dict[str, Any]]]:
        """Prépare les batches depuis des dicts."""
        batches = []
        for i in range(0, len(claim_dicts), self.batch_size):
            batches.append(claim_dicts[i:i + self.batch_size])
        return batches

    async def _enrich_all_async(
        self,
        batches: List[List[Tuple[int, Any, List[str]]]],
        claims: list,
    ) -> SlotEnrichmentResult:
        """Enrichit tous les batches en parallèle."""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        result = SlotEnrichmentResult()
        result.claims_processed = sum(len(b) for b in batches)

        # Index claim par position pour mise à jour in-place
        claim_list = list(claims)

        global_index = 0
        tasks = []

        for batch in batches:
            # Construire le claims_block
            claims_block = self._format_batch(batch)
            batch_claim_refs = [(item[1], item[0]) for item in batch]  # (claim, index)
            tasks.append(
                self._process_batch_async(
                    semaphore, claims_block, batch_claim_refs, result
                )
            )

        await asyncio.gather(*tasks)

        self._stats["claims_processed"] += result.claims_processed
        self._stats["claims_enriched"] += result.claims_enriched
        self._stats["claims_null"] += result.claims_null
        self._stats["claims_rejected"] += result.claims_rejected
        self._stats["llm_calls"] += result.llm_calls

        return result

    async def _enrich_dicts_async(
        self,
        batches: List[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Enrichit des dicts de claims en parallèle."""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        all_enriched: List[Dict[str, Any]] = []
        lock = asyncio.Lock()

        async def process_batch(batch: List[Dict[str, Any]]) -> None:
            async with semaphore:
                claims_block = self._format_batch_from_dicts(batch)
                try:
                    response = await self._call_llm_async(claims_block)
                    self._stats["llm_calls"] += 1
                    parsed = self._parse_llm_response(response)

                    for item in parsed:
                        idx = item.get("index")
                        sf = item.get("structured_form")
                        if idx is None or idx < 1 or idx > len(batch):
                            continue

                        claim_dict = batch[idx - 1]
                        if sf is None:
                            self._stats["claims_null"] += 1
                            continue

                        validated = self._validate_triplet(sf)
                        if validated:
                            self._stats["claims_enriched"] += 1
                            async with lock:
                                all_enriched.append({
                                    "claim_id": claim_dict["claim_id"],
                                    "structured_form": validated,
                                })
                        else:
                            self._stats["claims_rejected"] += 1

                except Exception as e:
                    logger.error(f"[OSMOSE:SlotEnricher] Batch failed: {e}")

        await asyncio.gather(*[process_batch(b) for b in batches])
        return all_enriched

    async def _process_batch_async(
        self,
        semaphore: asyncio.Semaphore,
        claims_block: str,
        batch_claim_refs: List[Tuple[Any, int]],
        result: SlotEnrichmentResult,
    ) -> None:
        """Traite un batch de claims."""
        async with semaphore:
            try:
                response = await self._call_llm_async(claims_block)
                result.llm_calls += 1
                parsed = self._parse_llm_response(response)

                for item in parsed:
                    idx = item.get("index")
                    sf = item.get("structured_form")
                    if idx is None or idx < 1 or idx > len(batch_claim_refs):
                        continue

                    claim, _ = batch_claim_refs[idx - 1]
                    if sf is None:
                        result.claims_null += 1
                        continue

                    validated = self._validate_triplet(sf)
                    if validated:
                        claim.structured_form = validated
                        result.claims_enriched += 1
                    else:
                        result.claims_rejected += 1

            except Exception as e:
                logger.error(f"[OSMOSE:SlotEnricher] Batch failed: {e}")

    def _format_batch(self, batch: List[Tuple[int, Any, List[str]]]) -> str:
        """Formate un batch de (index, claim, entities) pour le prompt."""
        lines = []
        for idx, claim, entities in batch:
            claim_type = claim.claim_type.value if hasattr(claim.claim_type, 'value') else str(claim.claim_type)
            lines.append(f'{idx}. [{claim_type}] "{claim.text}"')
            if entities:
                lines.append(f"   Known entities: {', '.join(entities)}")
        return "\n".join(lines)

    def _format_batch_from_dicts(self, batch: List[Dict[str, Any]]) -> str:
        """Formate un batch de dicts pour le prompt."""
        lines = []
        for i, cd in enumerate(batch, 1):
            claim_type = cd.get("claim_type", "FACTUAL")
            text = cd.get("text", "")
            lines.append(f'{i}. [{claim_type}] "{text}"')
            entities = cd.get("entity_names", [])
            if entities:
                lines.append(f"   Known entities: {', '.join(entities)}")
        return "\n".join(lines)

    async def _call_llm_async(self, claims_block: str) -> str:
        """Appel LLM async via le router."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()
        prompt = SLOT_ENRICHMENT_PROMPT.format(claims_block=claims_block)

        messages = [
            {"role": "user", "content": prompt},
        ]

        response = await router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=0.1,
            max_tokens=1500,
        )

        return response

    def _parse_llm_response(self, response: str) -> List[Dict[str, Any]]:
        """Parse la réponse JSON du LLM (robuste, avec récupération partielle)."""
        if not response:
            return []

        text = response.strip()

        # Gérer le markdown ```json ... ```
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("["):
                    text = part
                    break

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

        # Essayer d'extraire un array JSON
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start:end + 1])
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Récupération partielle : JSON tronqué (max_tokens atteint)
        if start >= 0:
            truncated = text[start:]
            recovered = self._recover_truncated_json(truncated)
            if recovered:
                logger.warning(
                    f"[OSMOSE:SlotEnricher] Recovered {len(recovered)} items from truncated JSON "
                    f"(response len={len(response)})"
                )
                return recovered

        logger.warning(
            f"[OSMOSE:SlotEnricher] Failed to parse LLM response as JSON array "
            f"(len={len(response)}, starts_with={repr(response[:80])})"
        )
        return []

    def _recover_truncated_json(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """Récupère les éléments complets d'un JSON array tronqué."""
        import re
        # Trouver tous les objets complets {...} dans le texte
        items = []
        pattern = re.compile(r'\{[^{}]*\}')
        for match in pattern.finditer(text):
            try:
                obj = json.loads(match.group())
                if "index" in obj:
                    items.append(obj)
            except json.JSONDecodeError:
                continue
        return items if items else None

    def _validate_triplet(self, sf: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Valide un triplet S/P/O retourné par le LLM.

        Returns:
            Dict {subject, predicate, object} validé, ou None si invalide.
        """
        if not isinstance(sf, dict):
            return None

        subject = str(sf.get("subject", "")).strip()
        predicate = str(sf.get("predicate", "")).strip()
        obj = str(sf.get("object", "")).strip()

        if not subject or not predicate or not obj:
            return None

        # Normaliser le prédicat
        canonical_pred = _normalize_predicate(predicate)
        if not canonical_pred:
            return None

        # Valider subject et object
        if not is_valid_entity_name(subject):
            return None
        if not is_valid_entity_name(obj):
            return None

        return {
            "subject": subject,
            "predicate": canonical_pred,
            "object": obj,
        }

    def get_stats(self) -> dict:
        return dict(self._stats)

    def reset_stats(self) -> None:
        for key in self._stats:
            self._stats[key] = 0
