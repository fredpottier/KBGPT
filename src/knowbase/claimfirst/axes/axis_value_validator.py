# src/knowbase/claimfirst/axes/axis_value_validator.py
"""
AxisValueValidator - Validation LLM des valeurs d'axes détectées.

Pattern "Extract-then-Validate":
1. Bootstrap patterns détectent des candidats (false positives possibles)
2. LLM valide/choisit la valeur appropriée pour le document
3. Maintient l'agnosticisme domaine (INV-25)

Ce composant est optionnel mais recommandé pour améliorer la précision.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from knowbase.claimfirst.axes.axis_detector import AxisObservation
from knowbase.claimfirst.models.passage import Passage

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Résultat de validation pour un axe."""

    axis_key: str
    selected_value: Optional[str]  # None si aucune valeur valide
    confidence: float
    reasoning: str
    was_validated: bool  # True si LLM a validé, False si bypass


class AxisValueValidator:
    """
    Valide les valeurs d'axes candidates via LLM.

    Pattern "Extract-then-Validate":
    - Reçoit les observations (candidats détectés par patterns)
    - Demande au LLM de choisir la valeur appropriée
    - Retourne les observations avec valeurs validées

    INV-25: Reste agnostique domaine (pas de hardcoding SAP/etc.)
    """

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        max_passages_sample: int = 3,
        min_candidates_for_validation: int = 1,
        tenant_id: Optional[str] = None,
    ):
        """
        Initialise le validateur.

        Args:
            llm_client: Client LLM (si None, bypass validation)
            max_passages_sample: Nombre max de passages à envoyer au LLM
            min_candidates_for_validation: Minimum de candidats pour déclencher validation
            tenant_id: Tenant ID pour injection contexte domaine
        """
        self.llm_client = llm_client
        self.max_passages_sample = max_passages_sample
        self.min_candidates_for_validation = min_candidates_for_validation
        self.tenant_id = tenant_id

        self.stats = {
            "validations_attempted": 0,
            "validations_succeeded": 0,
            "values_confirmed": 0,
            "values_rejected": 0,
            "values_bypassed": 0,
        }

    def validate(
        self,
        observations: List[AxisObservation],
        doc_title: Optional[str],
        passages: List[Passage],
    ) -> List[AxisObservation]:
        """
        Valide les observations d'axes via LLM.

        Args:
            observations: Observations candidates (sorties de AxisDetector)
            doc_title: Titre du document
            passages: Passages du document (pour contexte)

        Returns:
            Observations avec valeurs validées (peut réduire values_extracted)
        """
        if not self.llm_client:
            # Sans LLM, bypass validation
            for obs in observations:
                self.stats["values_bypassed"] += len(obs.values_extracted)
            return observations

        validated_observations = []

        for obs in observations:
            # Si une seule valeur et haute confiance metadata/title, bypass
            if (
                len(obs.values_extracted) == 1
                and obs.reliability == "metadata"
                and obs.evidence_spans
                and obs.evidence_spans[0].confidence >= 0.95
            ):
                self.stats["values_bypassed"] += 1
                validated_observations.append(obs)
                continue

            # Valider via LLM
            result = self._validate_axis_values(
                axis_key=obs.axis_key,
                axis_display_name=obs.axis_display_name,
                candidate_values=obs.values_extracted,
                evidence_spans=obs.evidence_spans,
                doc_title=doc_title,
                passages=passages,
            )

            self.stats["validations_attempted"] += 1

            if result.selected_value:
                # Créer une observation avec seulement la valeur validée
                validated_obs = AxisObservation(
                    axis_key=obs.axis_key,
                    axis_display_name=obs.axis_display_name,
                    values_extracted=[result.selected_value],
                    evidence_spans=[
                        ev for ev, val in zip(obs.evidence_spans, obs.values_extracted)
                        if val == result.selected_value
                    ][:1] or obs.evidence_spans[:1],
                    orderability_confidence=obs.orderability_confidence,
                    reliability="explicit_text" if result.was_validated else obs.reliability,
                )
                validated_observations.append(validated_obs)
                self.stats["validations_succeeded"] += 1
                self.stats["values_confirmed"] += 1
                self.stats["values_rejected"] += len(obs.values_extracted) - 1

                logger.debug(
                    f"[OSMOSE:AxisValidator] {obs.axis_key}: "
                    f"selected '{result.selected_value}' from {obs.values_extracted} "
                    f"(reason: {result.reasoning[:50]}...)"
                )
            else:
                # Aucune valeur valide - rejeter cet axe
                self.stats["values_rejected"] += len(obs.values_extracted)
                logger.debug(
                    f"[OSMOSE:AxisValidator] {obs.axis_key}: "
                    f"rejected all candidates {obs.values_extracted} "
                    f"(reason: {result.reasoning[:50]}...)"
                )

        return validated_observations

    def _validate_axis_values(
        self,
        axis_key: str,
        axis_display_name: Optional[str],
        candidate_values: List[str],
        evidence_spans,
        doc_title: Optional[str],
        passages: List[Passage],
    ) -> ValidationResult:
        """
        Valide les valeurs candidates pour un axe via LLM.

        Args:
            axis_key: Clé de l'axe (release_id, year, edition...)
            axis_display_name: Label textuel trouvé (version, release...)
            candidate_values: Valeurs candidates détectées
            evidence_spans: Evidences des valeurs
            doc_title: Titre du document
            passages: Passages pour contexte

        Returns:
            ValidationResult avec la valeur sélectionnée (ou None)
        """
        # Construire le contexte
        context_parts = []
        if doc_title:
            context_parts.append(f"Titre: {doc_title}")

        # Ajouter un échantillon de passages
        sample_passages = passages[:self.max_passages_sample]
        for i, passage in enumerate(sample_passages):
            text_preview = passage.text[:500] + "..." if len(passage.text) > 500 else passage.text
            context_parts.append(f"Passage {i+1}: {text_preview}")

        context = "\n\n".join(context_parts)

        # Construire les candidats avec leur evidence
        candidates_desc = []
        for i, (val, ev) in enumerate(zip(candidate_values, evidence_spans or [None] * len(candidate_values))):
            evidence_text = ev.text_snippet if ev else "N/A"
            candidates_desc.append(f"{i+1}. \"{val}\" (trouvé dans: \"{evidence_text}\")")

        candidates_str = "\n".join(candidates_desc)

        # Domain-agnostic: no hardcoded axis instructions (INV-25)
        # The Domain Context injection in _call_llm() provides domain-specific rules
        axis_specific_instructions = ""

        # Prompt de validation
        axis_desc = axis_display_name or axis_key
        prompt = f"""Analyse ce document et détermine quelle valeur de "{axis_desc}" s'applique GLOBALEMENT au document.

CONTEXTE DU DOCUMENT:
{context}

VALEURS CANDIDATES DÉTECTÉES pour l'axe "{axis_key}":
{candidates_str}

INSTRUCTIONS:
1. Détermine quelle valeur (si une) caractérise le document DANS SON ENSEMBLE
2. Une mention occasionnelle d'une valeur ne signifie pas que le document TRAITE de cette valeur
3. Si le document traite d'un sujet général et mentionne occasionnellement des éditions/versions spécifiques, ces mentions sont probablement des EXEMPLES, pas le sujet principal
{axis_specific_instructions}
Réponds en JSON:
{{
  "selected_value": "la valeur qui s'applique au document" ou null si aucune,
  "confidence": 0.0-1.0,
  "reasoning": "explication courte"
}}

IMPORTANT: Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."""

        try:
            response = self._call_llm(prompt)
            result = self._parse_validation_response(response, axis_key)
            return result

        except Exception as e:
            logger.warning(
                f"[OSMOSE:AxisValidator] LLM validation failed for axis "
                f"'{axis_key}' with {len(candidate_values)} candidates: {e}"
            )
            # Ne PAS deviner : retourner None pour éviter les faux positifs
            # (ex: "2.0" promu en release_id par erreur)
            return ValidationResult(
                axis_key=axis_key,
                selected_value=None,
                confidence=0.0,
                reasoning=f"LLM validation failed, no blind fallback: {str(e)[:80]}",
                was_validated=False,
            )

    def _call_llm(self, prompt: str) -> str:
        """Appelle le LLM via le router, enrichi du contexte métier."""
        from knowbase.common.llm_router import get_llm_router, TaskType
        from knowbase.ontology.domain_context_injector import get_domain_context_injector

        system_prompt = "You are an expert in document versioning axis validation."

        if self.tenant_id:
            try:
                injector = get_domain_context_injector()
                system_prompt = injector.inject_context(system_prompt, self.tenant_id)
            except Exception as e:
                logger.warning(f"[OSMOSE:AxisValidator] Domain context injection failed: {e}")

        router = get_llm_router()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        response = router.complete(
            task_type=TaskType.FAST_CLASSIFICATION,
            messages=messages,
            temperature=0.0,
            max_tokens=300,
        )
        return response

    def _parse_validation_response(
        self,
        response: str,
        axis_key: str,
    ) -> ValidationResult:
        """Parse la réponse JSON du LLM."""
        try:
            # Nettoyer la réponse
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

            data = json.loads(response)

            return ValidationResult(
                axis_key=axis_key,
                selected_value=data.get("selected_value"),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", ""),
                was_validated=True,
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"[OSMOSE:AxisValidator] Failed to parse response: {e}")
            return ValidationResult(
                axis_key=axis_key,
                selected_value=None,
                confidence=0.0,
                reasoning=f"Parse error: {str(e)[:50]}",
                was_validated=False,
            )

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques de validation."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "validations_attempted": 0,
            "validations_succeeded": 0,
            "values_confirmed": 0,
            "values_rejected": 0,
            "values_bypassed": 0,
        }


__all__ = [
    "AxisValueValidator",
    "ValidationResult",
]
