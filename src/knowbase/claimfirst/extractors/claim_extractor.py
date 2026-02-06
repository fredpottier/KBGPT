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
from knowbase.claimfirst.models.passage import Passage
from knowbase.stratified.pass1.assertion_unit_indexer import (
    AssertionUnitIndexer,
    UnitIndexResult,
    AssertionUnit,
    format_units_for_llm,
)

logger = logging.getLogger(__name__)


# Prompt pour extraction de claims (pointer mode)
# Note: Les {{ et }} sont échappés pour str.format()
CLAIM_EXTRACTION_PROMPT_TEMPLATE = """Tu es un expert en extraction d'assertions documentées.

Tu reçois des unités de texte numérotées (U1, U2, etc.) provenant d'un document.
Ta tâche est d'identifier les CLAIMS - des affirmations précises et documentées.

## Charte de la bonne Claim

1. Dit UNE chose précise (pas de liste, pas de généralité)
2. Supportée par le texte verbatim (tu POINTES vers l'unité, tu ne COPIES PAS)
3. Jamais exhaustive (mieux vaut plusieurs claims précises qu'une vague)
4. Contextuelle si applicable (version, région, édition)
5. N'infère rien (ne déduis pas ce qui n'est pas dit explicitement)
6. Peut NE PAS exister si le texte est trop vague

## Types de Claims

- FACTUAL: Assertion factuelle vérifiable ("TLS 1.2 is supported")
- PRESCRIPTIVE: Obligation/interdiction ("Customers must enable MFA")
- DEFINITIONAL: Définition/description ("SAP BTP is a platform...")
- CONDITIONAL: Assertion conditionnelle ("If data exceeds 1TB, then...")
- PERMISSIVE: Permission ("Customers may configure...")
- PROCEDURAL: Étape/processus ("To enable SSO, first configure...")

## Format de réponse (JSON)

Retourne un tableau JSON de claims. Exemple:
[
  {{
    "claim_text": "Formulation synthétique de la claim",
    "claim_type": "FACTUAL",
    "unit_id": "U1",
    "confidence": 0.95,
    "scope": {{"version": null, "region": null, "edition": null, "conditions": []}}
  }}
]

## Règles STRICTES

- NE COPIE JAMAIS le texte. Utilise UNIQUEMENT les unit_ids.
- Si une unité ne contient pas de claim claire, IGNORE-LA.
- Si le texte est vague ou générique, retourne un tableau vide [].
- Préfère l'abstention à l'invention.

## Unités à analyser

{units_text}

## Contexte du document

Titre: {doc_title}
Type: {doc_type}

Retourne UNIQUEMENT le tableau JSON, sans explication."""


def build_claim_extraction_prompt(units_text: str, doc_title: str, doc_type: str) -> str:
    """Construit le prompt d'extraction de claims."""
    return CLAIM_EXTRACTION_PROMPT_TEMPLATE.format(
        units_text=units_text,
        doc_title=doc_title,
        doc_type=doc_type,
    )


# Nombre max d'appels LLM en parallèle (évite de surcharger vLLM/OpenAI)
MAX_CONCURRENT_LLM_CALLS = 20


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
        }

    def extract(
        self,
        passages: List[Passage],
        tenant_id: str,
        doc_id: str,
        doc_title: str = "",
        doc_type: str = "technical",
    ) -> Tuple[List[Claim], Dict[str, UnitIndexResult]]:
        """
        Extrait les Claims des passages.

        Args:
            passages: Liste de Passages à traiter
            tenant_id: Tenant ID
            doc_id: Document ID
            doc_title: Titre du document (contexte)
            doc_type: Type de document (contexte)

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

        # Construire le prompt
        prompt = build_claim_extraction_prompt(
            units_text=units_text,
            doc_title=task.doc_title or "Unknown",
            doc_type=task.doc_type,
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
        for raw in raw_claims:
            try:
                claim = self._build_claim(
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
                else:
                    self.stats["claims_rejected"] += 1
            except Exception as e:
                logger.warning(f"[OSMOSE:ClaimExtractor] Failed to build claim: {e}")
                self.stats["claims_rejected"] += 1

        return claims

    async def _call_llm_async(self, prompt: str) -> str:
        """
        Version async de _call_llm.

        Utilise le LLM Router async pour la parallélisation.
        """
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()

        messages = [
            {"role": "system", "content": "Tu es un expert en extraction d'assertions."},
            {"role": "user", "content": prompt}
        ]

        # Appel async via le router (utilise vLLM si burst mode actif)
        response = await router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=0.1,
            max_tokens=2000,
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

        # Construire le prompt
        prompt = build_claim_extraction_prompt(
            units_text=units_text,
            doc_title=doc_title or "Unknown",
            doc_type=doc_type,
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
            {"role": "system", "content": "Tu es un expert en extraction d'assertions."},
            {"role": "user", "content": prompt}
        ]

        # Appel via le router (utilise vLLM si burst mode actif)
        response = router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=0.1,  # Déterministe
            max_tokens=2000,
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
        Construit une Claim depuis la sortie LLM.

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
]
