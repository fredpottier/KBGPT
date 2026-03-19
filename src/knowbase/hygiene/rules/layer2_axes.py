"""Règle Layer 2 — Cohérence sémantique des axes."""

from __future__ import annotations

import json
import logging
from typing import List

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
    HygieneRunScope,
)
from knowbase.hygiene.rules.base import HygieneRule

logger = logging.getLogger("[OSMOSE] kg_hygiene_l2_axes")


class AxisCoherenceRule(HygieneRule):
    """Vérifie la cohérence sémantique des valeurs au sein d'un axe via LLM."""

    @property
    def name(self) -> str:
        return "axis_coherence"

    @property
    def layer(self) -> int:
        return 2

    @property
    def description(self) -> str:
        return "Vérifie l'homogénéité sémantique des valeurs d'un axe via LLM"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        axes = self._load_axes_with_values(neo4j_driver, tenant_id)

        if not axes:
            return []

        domain_summary = self._load_domain_summary(neo4j_driver, tenant_id)
        actions = []

        # Évaluer par batch
        batch_size = 10
        for i in range(0, len(axes), batch_size):
            batch = axes[i:i + batch_size]
            evaluations = self._evaluate_coherence_llm(batch, domain_summary)

            for axis, evaluation in zip(batch, evaluations):
                if evaluation.get("is_coherent", True):
                    continue

                action = HygieneAction(
                    action_type=HygieneActionType.SUPPRESS_AXIS,
                    target_node_id=axis["axis_id"],
                    target_node_type="ApplicabilityAxis",
                    layer=2,
                    confidence=evaluation.get("confidence", 0.5),
                    reason=evaluation.get(
                        "reason",
                        f"Axe incohérent: '{axis.get('axis_key')}'"
                    ),
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=HygieneActionStatus.PROPOSED,  # Toujours PROPOSED pour axes
                    decision_source="rule",
                    tenant_id=tenant_id,
                )
                actions.append(action)

        logger.info(f"  → {len(actions)} axes incohérents détectés")
        return actions

    def _load_axes_with_values(self, neo4j_driver, tenant_id: str) -> list:
        """Charge les axes avec leurs valeurs."""
        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (a:ApplicabilityAxis {tenant_id: $tid})
                WHERE a._hygiene_status IS NULL
                OPTIONAL MATCH (c:Claim)-[:HAS_AXIS]->(a)
                RETURN a.axis_id AS axis_id, a.axis_key AS axis_key,
                       a.values AS values, count(c) AS claim_count
                LIMIT 100
                """,
                tid=tenant_id,
            )
            axes = []
            for r in result:
                vals = r.get("values")
                if isinstance(vals, str):
                    vals = [vals]
                elif vals is None:
                    vals = []
                axes.append({
                    "axis_id": r["axis_id"],
                    "axis_key": r.get("axis_key", ""),
                    "values": vals,
                    "claim_count": r.get("claim_count", 0),
                })
            return axes

    def _load_domain_summary(self, neo4j_driver, tenant_id: str) -> str:
        with neo4j_driver.session() as session:
            result = session.run(
                "MATCH (dc:DomainContextProfile {tenant_id: $tid}) RETURN dc.domain_summary AS ds",
                tid=tenant_id,
            )
            record = result.single()
            return record["ds"] if record and record["ds"] else ""

    def _evaluate_coherence_llm(self, axes: list, domain_summary: str) -> List[dict]:
        """Évalue la cohérence des axes via LLM."""
        try:
            from knowbase.common.llm_router import get_llm_router, TaskType

            router = get_llm_router()

            axes_text = "\n".join(
                f"- Axis '{a['axis_key']}': values = {a['values'][:10]} "
                f"({a['claim_count']} claims)"
                for a in axes
            )

            prompt = f"""Evaluate the semantic coherence of these applicability axes from a knowledge graph. Domain: {domain_summary or 'general'}.

An axis is coherent if all its values belong to the same semantic category (e.g., all years, all product names, all versions).
An axis is incoherent if it mixes unrelated value types or contains nonsensical values.

Axes:
{axes_text}

Return a JSON array:
[{{"axis_key": "...", "is_coherent": true/false, "confidence": 0.0-1.0, "reason": "..."}}]"""

            response = router.complete(
                task_type=TaskType.METADATA_EXTRACTION,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )

            text = response if isinstance(response, str) else str(response)
            if "```" in text:
                import re
                match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
                if match:
                    text = match.group(1)

            results = json.loads(text.strip())
            if isinstance(results, list) and len(results) == len(axes):
                return results

        except Exception as e:
            logger.warning(f"LLM axis coherence evaluation failed: {e}")

        return [{"is_coherent": True, "confidence": 0.0, "reason": "LLM unavailable"}] * len(axes)
