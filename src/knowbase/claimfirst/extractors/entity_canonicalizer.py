# src/knowbase/claimfirst/extractors/entity_canonicalizer.py
"""
EntityCanonicalizer - Canonicalisation LLM des entités extraites.

INV-25: Domain-agnostic - aucun vocabulaire spécifique hardcodé.

Ce composant prend les entités brutes extraites par EntityExtractor
et utilise un LLM pour :
1. Identifier les entités qui représentent la même chose
2. Choisir un nom canonique pour chaque groupe
3. Peupler les aliases avec les variantes

Exemple:
    Input:  ["S/4HANA", "SAP S/4HANA", "SAP S/4", "BTP", "Business Technology Platform"]
    Output: [
        Entity(name="SAP S/4HANA", aliases=["S/4HANA", "SAP S/4"]),
        Entity(name="SAP Business Technology Platform", aliases=["BTP", "Business Technology Platform"])
    ]
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from knowbase.claimfirst.models.entity import Entity, EntityType, strip_version_qualifier

logger = logging.getLogger(__name__)


# ============================================================================
# PROMPT CONTRACTUEL - Domain-Agnostic Entity Canonicalization
# ============================================================================

SYSTEM_PROMPT_CANONICALIZER = """You are an expert at identifying when different text strings refer to THE SAME real-world entity.

Your task is to GROUP entity names that represent the same thing, even if spelled differently.

────────────────────────────────────────
GROUPING RULES
────────────────────────────────────────

1. SAME ENTITY if:
   - One is an acronym of the other (e.g., "BTP" and "Business Technology Platform")
   - One is a shortened form (e.g., "S/4HANA" and "SAP S/4HANA")
   - Minor spelling variations (e.g., "S/4 HANA" and "S/4HANA")
   - With/without vendor prefix (e.g., "Analytics Cloud" and "SAP Analytics Cloud")

2. DIFFERENT ENTITIES if:
   - They refer to genuinely different things
   - Similar names but different contexts

3. VERSION SUFFIXES:
   - Version suffixes should be IGNORED for grouping (e.g., "Product 2023" and "Product" are the SAME entity)
   - "Product v1", "Product v2", "Product 2023" → all group under "Product"
   - The version is metadata, not part of the entity identity

4. CANONICAL NAME SELECTION:
   - Prefer the MOST COMPLETE and OFFICIAL form
   - Include vendor/company prefix if commonly used
   - Prefer expanded form over acronym (but keep acronym as alias)

────────────────────────────────────────
OUTPUT FORMAT
────────────────────────────────────────

Return ONLY valid JSON with this COMPACT structure:
{
  "entity_groups": [
    {
      "canonical_name": "The most official/complete name",
      "aliases": ["variant1", "variant2"],
      "entity_type": "product|service|concept|actor|standard|feature|legal_term|other"
    }
  ],
  "ungrouped": ["entities that don't match any group"]
}

IMPORTANT:
- Every input entity MUST appear exactly once (either as canonical_name, in aliases, or in ungrouped)
- Do NOT invent entities not in the input
- If unsure, keep entities separate (in ungrouped)
- Be CONCISE: do NOT add fields beyond canonical_name, aliases, entity_type
"""

USER_PROMPT_TEMPLATE = """Analyze these {count} entity names extracted from documents and group those that refer to the same thing:

ENTITIES:
{entities_json}

Return the JSON grouping. Remember:
- Group entities that are THE SAME thing (acronyms, abbreviations, spelling variants)
- Keep entities SEPARATE if they are genuinely different things
- Choose the most complete/official name as canonical
"""


class EntityGroup(BaseModel):
    """Groupe d'entités représentant la même chose."""

    canonical_name: str = Field(..., description="Nom canonique choisi")
    aliases: List[str] = Field(default_factory=list, description="Variantes/alias")
    entity_type: str = Field(default="concept", description="Type d'entité")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=200)


class CanonicalizationResult(BaseModel):
    """Résultat de la canonicalisation."""

    entity_groups: List[EntityGroup] = Field(default_factory=list)
    ungrouped: List[str] = Field(default_factory=list)


class EntityCanonicalizer:
    """
    Canonicalise les entités extraites via LLM.

    Domain-agnostic: utilise la connaissance générale du LLM
    pour identifier les variantes d'une même entité.
    """

    def __init__(
        self,
        tenant_id: str = "default",
        min_entities_for_llm: int = 5,
        batch_size: int = 30,
        max_concurrent: int = 3,
    ):
        """
        Initialise le canonicalizer.

        Args:
            tenant_id: Tenant ID pour injection contexte domaine
            min_entities_for_llm: Nombre min d'entités pour déclencher LLM
            batch_size: Taille max d'un batch pour le LLM
            max_concurrent: Nombre max d'appels LLM en parallèle
        """
        self.tenant_id = tenant_id
        self.min_entities_for_llm = min_entities_for_llm
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent

        self._stats = {
            "entities_input": 0,
            "entities_output": 0,
            "groups_created": 0,
            "aliases_added": 0,
            "llm_calls": 0,
            "llm_errors": 0,
        }

    def canonicalize(
        self,
        entities: List[Entity],
        claim_entity_map: Dict[str, List[str]],
    ) -> Tuple[List[Entity], Dict[str, List[str]]]:
        """
        Canonicalise les entités et met à jour les mappings.

        Args:
            entities: Entités brutes extraites
            claim_entity_map: Mapping claim_id → [entity_ids]

        Returns:
            Tuple (entities_canonicalized, claim_entity_map_updated)
        """
        self._stats["entities_input"] = len(entities)

        if len(entities) < self.min_entities_for_llm:
            logger.info(
                f"[EntityCanonicalizer] Skipping LLM: only {len(entities)} entities "
                f"(min: {self.min_entities_for_llm})"
            )
            self._stats["entities_output"] = len(entities)
            return entities, claim_entity_map

        # Pré-traitement : version stripping domain-agnostic
        # "S/4HANA 2023" → entity rename "S/4HANA", "2023" stocké en alias
        for entity in entities:
            base_name, version = strip_version_qualifier(entity.name)
            if version:
                original_name = entity.name
                object.__setattr__(entity, "name", base_name)
                object.__setattr__(entity, "normalized_name", Entity.normalize(base_name))
                if original_name not in entity.aliases:
                    entity.aliases.append(original_name)

        # Extraire les noms uniques pour le LLM
        entity_names = list({e.name for e in entities})

        # Appeler le LLM pour grouper
        result = self._call_llm_for_grouping(entity_names)

        if result is None:
            logger.warning("[EntityCanonicalizer] LLM failed, returning original entities")
            self._stats["entities_output"] = len(entities)
            return entities, claim_entity_map

        # Construire le mapping old_name → canonical_name
        name_to_canonical = self._build_name_mapping(result)

        # Fusionner les entités
        merged_entities, old_to_new_id = self._merge_entities(
            entities, name_to_canonical, result
        )

        # Mettre à jour claim_entity_map
        updated_map = self._update_claim_map(claim_entity_map, old_to_new_id)

        self._stats["entities_output"] = len(merged_entities)
        self._stats["groups_created"] = len(result.entity_groups)

        logger.info(
            f"[EntityCanonicalizer] Canonicalized {len(entities)} → {len(merged_entities)} entities "
            f"({self._stats['groups_created']} groups, {self._stats['aliases_added']} aliases)"
        )

        return merged_entities, updated_map

    def _call_llm_for_grouping(
        self,
        entity_names: List[str],
    ) -> Optional[CanonicalizationResult]:
        """
        Appelle le LLM pour grouper les entités en parallèle.

        Utilise asyncio.gather + semaphore pour paralléliser les appels LLM
        (même pattern que ClaimExtractor et SlotEnricher).
        """
        from knowbase.common.llm_router import get_llm_router, TaskType
        from knowbase.ontology.domain_context_injector import get_domain_context_injector

        injector = get_domain_context_injector()
        enriched_system_prompt = injector.inject_context(
            base_prompt=SYSTEM_PROMPT_CANONICALIZER,
            tenant_id=self.tenant_id,
        )

        # Préparer tous les batches
        batches: List[List[str]] = []
        for batch_start in range(0, len(entity_names), self.batch_size):
            batches.append(entity_names[batch_start:batch_start + self.batch_size])

        nb_batches = len(batches)
        logger.info(
            f"[EntityCanonicalizer] {len(entity_names)} entities → {nb_batches} batches "
            f"(parallel, max_concurrent={self.max_concurrent})"
        )

        # Exécuter tous les batches en parallèle
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    batch_results = pool.submit(
                        asyncio.run, self._process_all_batches_async(batches, enriched_system_prompt)
                    ).result()
            else:
                batch_results = asyncio.run(
                    self._process_all_batches_async(batches, enriched_system_prompt)
                )
        except RuntimeError:
            batch_results = asyncio.run(
                self._process_all_batches_async(batches, enriched_system_prompt)
            )

        # Agréger les résultats
        all_groups: List[EntityGroup] = []
        all_ungrouped: List[str] = []
        for br in batch_results:
            if br:
                all_groups.extend(br.entity_groups)
                all_ungrouped.extend(br.ungrouped)

        if not all_groups and not all_ungrouped:
            return None

        return CanonicalizationResult(
            entity_groups=all_groups,
            ungrouped=all_ungrouped,
        )

    async def _process_all_batches_async(
        self,
        batches: List[List[str]],
        system_prompt: str,
    ) -> List[Optional[CanonicalizationResult]]:
        """Exécute tous les batches en parallèle avec semaphore."""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        results: List[Optional[CanonicalizationResult]] = [None] * len(batches)

        async def process_batch(idx: int, names_batch: List[str]) -> None:
            async with semaphore:
                result = await self._call_batch_async(names_batch, system_prompt)
                results[idx] = result

        await asyncio.gather(
            *[process_batch(i, batch) for i, batch in enumerate(batches)]
        )
        return results

    async def _call_batch_async(
        self,
        names_batch: List[str],
        system_prompt: str,
    ) -> Optional[CanonicalizationResult]:
        """Appel LLM async pour un batch d'entités."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        self._stats["llm_calls"] += 1

        user_prompt = USER_PROMPT_TEMPLATE.format(
            count=len(names_batch),
            entities_json=json.dumps(names_batch, ensure_ascii=False, indent=2),
        )

        try:
            router = get_llm_router()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            response = await router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=messages,
                temperature=0.1,
                max_tokens=2500,
                response_format={"type": "json_object"},
            )

            batch_result = self._parse_response(response, names_batch)
            if batch_result:
                return batch_result
            else:
                return CanonicalizationResult(ungrouped=list(names_batch))

        except Exception as e:
            logger.error(f"[EntityCanonicalizer] Async LLM call failed: {e}")
            self._stats["llm_errors"] += 1
            return CanonicalizationResult(ungrouped=list(names_batch))

    def _parse_response(
        self,
        response_text: str,
        input_names: List[str],
    ) -> Optional[CanonicalizationResult]:
        """
        Parse la réponse JSON du LLM.

        Args:
            response_text: Réponse brute du LLM
            input_names: Noms d'entrée pour validation

        Returns:
            CanonicalizationResult ou None si parsing échoue
        """
        if not response_text:
            return None

        # Extraire le JSON
        json_match = re.search(
            r'\{[\s\S]*"entity_groups"[\s\S]*\}',
            response_text,
            re.DOTALL,
        )

        if not json_match:
            logger.warning("[EntityCanonicalizer] No JSON found in response")
            return None

        try:
            data = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            # Tentative de repair — JSON probablement tronqué par max_tokens
            data = self._try_repair_json(json_match.group(0))
            if data is None:
                logger.warning(
                    f"[EntityCanonicalizer] JSON repair failed (len={len(response_text)})"
                )
                return None
            logger.info(
                f"[EntityCanonicalizer] JSON repaired successfully "
                f"({len(data.get('entity_groups', []))} groups recovered)"
            )

        try:
            result = CanonicalizationResult(
                entity_groups=[EntityGroup(**g) for g in data.get("entity_groups", [])],
                ungrouped=data.get("ungrouped", []),
            )

            # Validation: tous les noms d'entrée doivent être présents
            output_names = set()
            for group in result.entity_groups:
                output_names.add(group.canonical_name)
                output_names.update(group.aliases)
            output_names.update(result.ungrouped)

            input_set = set(input_names)
            missing = input_set - output_names
            if missing:
                logger.warning(
                    f"[EntityCanonicalizer] LLM missed {len(missing)} entities, adding to ungrouped"
                )
                result.ungrouped.extend(missing)

            return result

        except Exception as e:
            logger.warning(f"[EntityCanonicalizer] Parse error: {e}")
            return None

    @staticmethod
    def _try_repair_json(raw: str) -> Optional[Dict[str, Any]]:
        """Tente de réparer un JSON tronqué par max_tokens.

        Stratégie : trouver le dernier objet complet dans entity_groups,
        tronquer le reste, fermer les structures ouvertes.
        """
        # Trouver la dernière accolade fermante complète dans un entity_group
        # Pattern: }, suivi potentiellement d'espaces/newlines
        last_complete = -1
        brace_depth = 0
        in_string = False
        escape_next = False

        for i, ch in enumerate(raw):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 1:
                    # On vient de fermer un objet au niveau 2 (un entity_group)
                    last_complete = i

        if last_complete <= 0:
            return None

        # Tronquer après le dernier groupe complet, fermer le JSON
        truncated = raw[:last_complete + 1]
        # Fermer entity_groups array + ungrouped vide + objet racine
        truncated += '], "ungrouped": []}'

        try:
            return json.loads(truncated)
        except json.JSONDecodeError:
            return None

    def _build_name_mapping(
        self,
        result: CanonicalizationResult,
    ) -> Dict[str, str]:
        """
        Construit le mapping name → canonical_name.

        Args:
            result: Résultat de canonicalisation

        Returns:
            Dict mapping chaque nom vers son canonical
        """
        mapping = {}

        for group in result.entity_groups:
            # Le canonical_name mappe vers lui-même
            mapping[group.canonical_name] = group.canonical_name
            # Les aliases mappent vers le canonical
            for alias in group.aliases:
                mapping[alias] = group.canonical_name

        # Les ungrouped mappent vers eux-mêmes
        for name in result.ungrouped:
            mapping[name] = name

        return mapping

    def _merge_entities(
        self,
        entities: List[Entity],
        name_to_canonical: Dict[str, str],
        result: CanonicalizationResult,
    ) -> Tuple[List[Entity], Dict[str, str]]:
        """
        Fusionne les entités selon le mapping.

        Args:
            entities: Entités originales
            name_to_canonical: Mapping name → canonical
            result: Résultat de canonicalisation (pour les types)

        Returns:
            Tuple (merged_entities, old_id_to_new_id)
        """
        # Index des groupes par canonical_name
        group_index = {g.canonical_name: g for g in result.entity_groups}

        # Regrouper les entités par canonical_name
        canonical_groups: Dict[str, List[Entity]] = {}
        for entity in entities:
            canonical = name_to_canonical.get(entity.name, entity.name)
            if canonical not in canonical_groups:
                canonical_groups[canonical] = []
            canonical_groups[canonical].append(entity)

        # Créer les entités fusionnées
        merged_entities = []
        old_to_new_id: Dict[str, str] = {}

        for canonical_name, group_entities in canonical_groups.items():
            # Utiliser l'ID de la première entité du groupe
            primary = group_entities[0]

            # Collecter tous les aliases
            aliases = set()
            total_mentions = 0
            all_source_docs = set()

            for e in group_entities:
                if e.name != canonical_name:
                    aliases.add(e.name)
                aliases.update(e.aliases)
                total_mentions += e.mention_count
                all_source_docs.update(e.source_doc_ids)
                # Mapper l'ancien ID vers le nouveau
                old_to_new_id[e.entity_id] = primary.entity_id

            # Retirer le canonical des aliases
            aliases.discard(canonical_name)

            # Déterminer le type depuis le groupe LLM si disponible
            entity_type = primary.entity_type
            if canonical_name in group_index:
                llm_type = group_index[canonical_name].entity_type
                try:
                    entity_type = EntityType(llm_type)
                except ValueError:
                    pass

            # Créer l'entité fusionnée
            merged = Entity(
                entity_id=primary.entity_id,
                tenant_id=primary.tenant_id,
                name=canonical_name,
                entity_type=entity_type,
                aliases=sorted(aliases),
                normalized_name=Entity.normalize(canonical_name),
                source_doc_ids=sorted(all_source_docs),
                mention_count=total_mentions,
            )
            merged_entities.append(merged)

            self._stats["aliases_added"] += len(aliases)

        return merged_entities, old_to_new_id

    def _update_claim_map(
        self,
        claim_entity_map: Dict[str, List[str]],
        old_to_new_id: Dict[str, str],
    ) -> Dict[str, List[str]]:
        """
        Met à jour le claim_entity_map avec les nouveaux IDs.

        Args:
            claim_entity_map: Mapping original
            old_to_new_id: Mapping ancien ID → nouveau ID

        Returns:
            Mapping mis à jour (dédupliqué)
        """
        updated = {}
        for claim_id, entity_ids in claim_entity_map.items():
            new_ids = set()
            for old_id in entity_ids:
                new_id = old_to_new_id.get(old_id, old_id)
                new_ids.add(new_id)
            updated[claim_id] = list(new_ids)
        return updated

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self._stats = {
            "entities_input": 0,
            "entities_output": 0,
            "groups_created": 0,
            "aliases_added": 0,
            "llm_calls": 0,
            "llm_errors": 0,
        }


__all__ = [
    "EntityCanonicalizer",
    "EntityGroup",
    "CanonicalizationResult",
    "SYSTEM_PROMPT_CANONICALIZER",
]
