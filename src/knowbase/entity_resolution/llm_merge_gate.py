"""
LLM Merge Gate - Validation sémantique des fusions par LLM.

Filtre les mauvaises fusions détectées par similarité embeddings seule.
Utilise Qwen 14B (vLLM burst) si EC2 actif, sinon fallback OpenAI.
Traite les candidats par batch de 10-30 paires.

Exemples de fusions bloquées :
- SAP S/4HANA ↔ SAP HANA (ERP ≠ Base de données)
- Active-passive ↔ Active-active (architectures opposées)
- HTTPS inbound ↔ HTTPS outbound (directions opposées)

Author: Claude Code
Date: 2026-01-07
Spec: doc/ongoing/PLAN_LLM_MERGE_GATE_V1.md
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class LLMGateConfig:
    """Configuration du LLM Merge Gate."""
    enabled: bool = True
    batch_size: int = 20  # Paires par appel LLM

    # Seuils de confiance
    merge_confidence_threshold: float = 0.85   # Auto-merge si MERGE + conf >= 0.85
    distinct_confidence_threshold: float = 0.80  # Bloquer si DISTINCT + conf >= 0.80

    # Timeouts
    timeout_per_batch: int = 30  # secondes
    max_retries: int = 2


@dataclass
class LLMMergeVerdict:
    """Verdict du LLM pour une paire de concepts."""
    source_id: str
    target_id: str
    source_name: str
    target_name: str
    decision: str  # "MERGE" | "DISTINCT"
    confidence: float
    reason: str


@dataclass
class LLMGateResult:
    """Résultat global du LLM Merge Gate."""
    verdicts: List[LLMMergeVerdict] = field(default_factory=list)
    blocked_pairs: Set[Tuple[str, str]] = field(default_factory=set)
    low_confidence_pairs: Set[Tuple[str, str]] = field(default_factory=set)
    total_calls: int = 0
    total_latency_ms: float = 0.0
    errors: List[str] = field(default_factory=list)


class LLMMergeGate:
    """
    LLM Merge Gate pour Entity Resolution.

    Valide les candidats de fusion via un LLM (Qwen 14B ou GPT-4o-mini).
    Empêche les fausses fusions comme SAP S/4HANA → SAP HANA.
    """

    PROMPT_TEMPLATE = '''Tu es un expert en Entity Resolution pour un Knowledge Graph technique.
Pour chaque paire de concepts ci-dessous, détermine s'ils représentent LA MÊME entité (MERGE) ou des entités DISTINCTES.

RÈGLES DE DÉCISION:
- MERGE: Même entité avec variations mineures (typo, acronyme, ponctuation, casse, pluriel)
  Exemples: "Data-at-rest" ↔ "Data at rest", "WAF" ↔ "Web Application Firewall"
- DISTINCT: Entités différentes même si lexicalement proches. Exemples:
  - Produits différents (SAP S/4HANA ≠ SAP HANA)
  - Configurations opposées (active-passive ≠ active-active)
  - Directions opposées (inbound ≠ outbound)
  - Versions différentes (v1 ≠ v2)

PAIRES À ANALYSER:
{pairs_json}

Réponds UNIQUEMENT avec un array JSON valide (pas de texte avant/après):
[
  {{"pair_index": 0, "decision": "MERGE", "confidence": 0.95, "reason": "même entité, variation de ponctuation"}},
  {{"pair_index": 1, "decision": "DISTINCT", "confidence": 0.90, "reason": "produits différents: ERP vs database"}}
]'''

    def __init__(self, config: Optional[LLMGateConfig] = None):
        """Initialize LLM Merge Gate."""
        self.config = config or LLMGateConfig()
        self._llm_router = None

    @property
    def llm_router(self):
        """Lazy load LLM router."""
        if self._llm_router is None:
            from knowbase.common.llm_router import get_llm_router
            self._llm_router = get_llm_router()
        return self._llm_router

    def run(
        self,
        candidates: List[Dict[str, Any]],
        concepts_cache: Dict[str, Dict[str, Any]]
    ) -> LLMGateResult:
        """
        Exécute le LLM Gate sur les candidats.

        Args:
            candidates: Liste de candidats avec (id_a, id_b) ou {"id_a": ..., "id_b": ...}
            concepts_cache: Cache des concepts {id: {name, type_fine, ...}}

        Returns:
            LLMGateResult avec verdicts et paires bloquées
        """
        result = LLMGateResult()

        if not self.config.enabled or not candidates:
            return result

        start_time = datetime.utcnow()

        # Batching
        batches = self._create_batches(candidates, concepts_cache)
        logger.info(f"[LLM_GATE] Processing {len(candidates)} candidates in {len(batches)} batches")

        for batch_idx, batch in enumerate(batches):
            try:
                verdicts = self._process_batch(batch, batch_idx)
                result.verdicts.extend(verdicts)
                result.total_calls += 1

                # Classifier les verdicts selon les seuils
                for v in verdicts:
                    pair = (v.source_id, v.target_id)

                    if v.decision == "DISTINCT" and v.confidence >= self.config.distinct_confidence_threshold:
                        result.blocked_pairs.add(pair)
                        logger.info(
                            f"[LLM_GATE] BLOCKED: {v.source_name} ↔ {v.target_name} "
                            f"(conf={v.confidence:.2f}, reason={v.reason})"
                        )

                    elif v.decision == "MERGE" and v.confidence < self.config.merge_confidence_threshold:
                        result.low_confidence_pairs.add(pair)
                        logger.debug(
                            f"[LLM_GATE] LOW_CONF: {v.source_name} ↔ {v.target_name} "
                            f"(conf={v.confidence:.2f})"
                        )

            except Exception as e:
                error_msg = f"Batch {batch_idx} failed: {e}"
                result.errors.append(error_msg)
                logger.error(f"[LLM_GATE] {error_msg}")

        result.total_latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        logger.info(
            f"[LLM_GATE] Complete: {len(result.verdicts)} verdicts, "
            f"{len(result.blocked_pairs)} blocked, "
            f"{len(result.low_confidence_pairs)} low_conf, "
            f"{result.total_calls} calls, {result.total_latency_ms:.0f}ms"
        )

        return result

    def run_async_sync(
        self,
        candidates: List[Dict[str, Any]],
        concepts_cache: Dict[str, Dict[str, Any]],
        max_concurrent: int = 8
    ) -> LLMGateResult:
        """
        Version parallélisée avec wrapper synchrone.

        Utilise asyncio pour paralléliser les appels LLM.
        Compatible avec les appelants synchrones.

        Args:
            candidates: Liste de candidats
            concepts_cache: Cache des concepts
            max_concurrent: Nombre max d'appels LLM en parallèle

        Returns:
            LLMGateResult
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.run_async(candidates, concepts_cache, max_concurrent)
            )
        finally:
            loop.close()

    async def run_async(
        self,
        candidates: List[Dict[str, Any]],
        concepts_cache: Dict[str, Dict[str, Any]],
        max_concurrent: int = 8
    ) -> LLMGateResult:
        """
        Version async parallélisée du LLM Merge Gate.

        Traite les batches en parallèle (limité par semaphore).

        Args:
            candidates: Liste de candidats
            concepts_cache: Cache des concepts
            max_concurrent: Nombre max d'appels LLM en parallèle

        Returns:
            LLMGateResult
        """
        result = LLMGateResult()

        if not self.config.enabled or not candidates:
            return result

        start_time = datetime.utcnow()

        # Batching
        batches = self._create_batches(candidates, concepts_cache)
        logger.info(
            f"[LLM_GATE] Processing {len(candidates)} candidates in {len(batches)} batches "
            f"(max_concurrent={max_concurrent})"
        )

        # Semaphore pour contrôler la concurrence
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_batch_async(batch_idx: int, batch: List[Dict[str, Any]]) -> List[LLMMergeVerdict]:
            """Traite un batch avec contrôle de concurrence."""
            async with semaphore:
                try:
                    verdicts = await self._process_batch_async(batch, batch_idx)
                    return verdicts
                except Exception as e:
                    error_msg = f"Batch {batch_idx} failed: {e}"
                    logger.error(f"[LLM_GATE] {error_msg}")
                    # Fallback conservateur
                    return [
                        LLMMergeVerdict(
                            source_id=pair["id_a"],
                            target_id=pair["id_b"],
                            source_name=pair["name_a"],
                            target_name=pair["name_b"],
                            decision="MERGE",
                            confidence=0.5,
                            reason="Async error, defaulting to cautious"
                        )
                        for pair in batch
                    ]

        # Lancer tous les batches en parallèle
        tasks = [process_batch_async(idx, batch) for idx, batch in enumerate(batches)]
        batch_results = await asyncio.gather(*tasks)

        # Agréger les résultats
        for verdicts in batch_results:
            result.verdicts.extend(verdicts)
            result.total_calls += 1

            for v in verdicts:
                pair = (v.source_id, v.target_id)

                if v.decision == "DISTINCT" and v.confidence >= self.config.distinct_confidence_threshold:
                    result.blocked_pairs.add(pair)
                    logger.info(
                        f"[LLM_GATE] BLOCKED: {v.source_name} ↔ {v.target_name} "
                        f"(conf={v.confidence:.2f}, reason={v.reason})"
                    )

                elif v.decision == "MERGE" and v.confidence < self.config.merge_confidence_threshold:
                    result.low_confidence_pairs.add(pair)

        result.total_latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        logger.info(
            f"[LLM_GATE] Complete (parallel): {len(result.verdicts)} verdicts, "
            f"{len(result.blocked_pairs)} blocked, "
            f"{len(result.low_confidence_pairs)} low_conf, "
            f"{result.total_calls} calls, {result.total_latency_ms:.0f}ms"
        )

        return result

    async def _process_batch_async(
        self,
        batch: List[Dict[str, Any]],
        batch_idx: int
    ) -> List[LLMMergeVerdict]:
        """Version async de _process_batch."""
        from knowbase.common.llm_router import TaskType

        # Préparer le JSON des paires pour le prompt
        pairs_for_prompt = [
            {
                "index": i,
                "concept_a": {"name": p["name_a"], "type": p["type_a"]},
                "concept_b": {"name": p["name_b"], "type": p["type_b"]}
            }
            for i, p in enumerate(batch)
        ]

        pairs_json = json.dumps(pairs_for_prompt, indent=2, ensure_ascii=False)
        prompt = self.PROMPT_TEMPLATE.format(pairs_json=pairs_json)

        messages = [{"role": "user", "content": prompt}]

        logger.debug(f"[LLM_GATE] Batch {batch_idx}: {len(batch)} pairs, calling LLM async...")

        response = await self.llm_router.acomplete(
            task_type=TaskType.SHORT_ENRICHMENT,
            messages=messages,
            temperature=0.1,
            max_tokens=2000
        )

        return self._parse_llm_response(response, batch)

    def _create_batches(
        self,
        candidates: List[Dict[str, Any]],
        concepts_cache: Dict[str, Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """Crée des batches de paires enrichies pour le LLM."""
        enriched = []

        for c in candidates:
            # Support both dict and tuple formats
            if isinstance(c, dict):
                id_a = c.get("id_a") or c.get("source_id")
                id_b = c.get("id_b") or c.get("target_id")
            else:
                id_a, id_b = c[0], c[1]

            concept_a = concepts_cache.get(id_a, {})
            concept_b = concepts_cache.get(id_b, {})

            enriched.append({
                "id_a": id_a,
                "id_b": id_b,
                "name_a": concept_a.get("name", id_a),
                "name_b": concept_b.get("name", id_b),
                "type_a": concept_a.get("type_fine") or concept_a.get("concept_type", "unknown"),
                "type_b": concept_b.get("type_fine") or concept_b.get("concept_type", "unknown"),
            })

        # Split en batches
        batches = []
        for i in range(0, len(enriched), self.config.batch_size):
            batches.append(enriched[i:i + self.config.batch_size])

        return batches

    def _process_batch(
        self,
        batch: List[Dict[str, Any]],
        batch_idx: int
    ) -> List[LLMMergeVerdict]:
        """Traite un batch via le LLM."""
        from knowbase.common.llm_router import TaskType

        # Préparer le JSON des paires pour le prompt
        pairs_for_prompt = [
            {
                "index": i,
                "concept_a": {"name": p["name_a"], "type": p["type_a"]},
                "concept_b": {"name": p["name_b"], "type": p["type_b"]}
            }
            for i, p in enumerate(batch)
        ]

        pairs_json = json.dumps(pairs_for_prompt, indent=2, ensure_ascii=False)
        prompt = self.PROMPT_TEMPLATE.format(pairs_json=pairs_json)

        # Appel LLM via router (utilise burst si actif, sinon OpenAI)
        messages = [{"role": "user", "content": prompt}]

        logger.debug(f"[LLM_GATE] Batch {batch_idx}: {len(batch)} pairs, calling LLM...")

        response = self.llm_router.complete(
            task_type=TaskType.SHORT_ENRICHMENT,
            messages=messages,
            temperature=0.1,
            max_tokens=2000
        )

        # Parser la réponse JSON
        return self._parse_llm_response(response, batch)

    def _parse_llm_response(
        self,
        response: str,
        batch: List[Dict[str, Any]]
    ) -> List[LLMMergeVerdict]:
        """Parse la réponse JSON du LLM."""
        verdicts = []

        try:
            # Nettoyer la réponse - extraire le JSON
            response = response.strip()

            # Gérer les réponses markdown avec ```json
            if "```" in response:
                parts = response.split("```")
                for part in parts:
                    part = part.strip()
                    if part.startswith("json"):
                        part = part[4:].strip()
                    if part.startswith("["):
                        response = part
                        break

            # Trouver le début et fin du JSON array
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                response = response[start:end]

            data = json.loads(response)

            for item in data:
                idx = item.get("pair_index", 0)
                if idx < len(batch):
                    pair = batch[idx]
                    decision = item.get("decision", "DISTINCT").upper()

                    # Valider la décision
                    if decision not in ("MERGE", "DISTINCT"):
                        decision = "DISTINCT"

                    verdicts.append(LLMMergeVerdict(
                        source_id=pair["id_a"],
                        target_id=pair["id_b"],
                        source_name=pair["name_a"],
                        target_name=pair["name_b"],
                        decision=decision,
                        confidence=float(item.get("confidence", 0.5)),
                        reason=item.get("reason", "")
                    ))

        except json.JSONDecodeError as e:
            logger.error(f"[LLM_GATE] JSON parse error: {e}")
            logger.debug(f"[LLM_GATE] Raw response: {response[:500]}")

            # Fallback: marquer toutes les paires comme low-confidence MERGE
            # (conservateur - pas de blocage si erreur parsing)
            for pair in batch:
                verdicts.append(LLMMergeVerdict(
                    source_id=pair["id_a"],
                    target_id=pair["id_b"],
                    source_name=pair["name_a"],
                    target_name=pair["name_b"],
                    decision="MERGE",
                    confidence=0.5,  # Low confidence = pas d'auto-merge
                    reason="LLM parse error, defaulting to cautious"
                ))

        return verdicts


# ============================================================================
# Factory function
# ============================================================================

_gate_instance: Optional[LLMMergeGate] = None


def get_llm_merge_gate(config: Optional[LLMGateConfig] = None) -> LLMMergeGate:
    """Get LLM Merge Gate instance (singleton)."""
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = LLMMergeGate(config)
    return _gate_instance


def reset_llm_merge_gate():
    """Reset singleton (for testing)."""
    global _gate_instance
    _gate_instance = None
