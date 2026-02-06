# src/knowbase/claimfirst/axes/axis_detector.py
"""
ApplicabilityAxisDetector - Détection des axes d'applicabilité depuis le corpus.

C1/INV-25: Axis key neutre + display_name optionnel
C2: Retourne AxisObservation (pas validated_axes)
INV-26: Evidence obligatoire pour chaque valeur extraite

Architecture LLM-first (INV-25 Domain Agnosticism):
1. LLM Primary: Utilise la connaissance LLM des conventions de versioning
2. Pattern Fallback: Pour efficacité si LLM indisponible
3. Metadata: Propriétés document structurées
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from knowbase.claimfirst.models.applicability_axis import (
    ApplicabilityAxis,
    OrderingConfidence,
    OrderType,
)
from knowbase.claimfirst.models.axis_value import AxisValue, AxisValueType, EvidenceSpan
from knowbase.claimfirst.models.passage import Passage

logger = logging.getLogger(__name__)


@dataclass
class AxisObservation:
    """
    Observation d'un axe d'applicabilité (C2: pas validated_axes).

    C'est le LatestSelector/QueryEngine qui décide ensuite quoi utiliser.

    Attributes:
        axis_key: Clé neutre (release_id, year...)
        axis_display_name: Label textuel trouvé ("version", "release"...)
        values_extracted: Valeurs extraites
        evidence_spans: Références aux passages source (INV-26)
        orderability_confidence: Niveau de confiance dans l'ordonnabilité
        reliability: Source de l'extraction
    """

    axis_key: str
    axis_display_name: Optional[str] = None
    values_extracted: List[str] = field(default_factory=list)
    evidence_spans: List[EvidenceSpan] = field(default_factory=list)
    orderability_confidence: OrderingConfidence = OrderingConfidence.UNKNOWN
    reliability: Literal["metadata", "explicit_text", "inferred", "llm_extracted"] = "explicit_text"


# Fallback patterns (domain-agnostic) - utilisés SEULEMENT si LLM indisponible
# Ces patterns sont conservatifs et ne capturent que des cas évidents
FALLBACK_AXIS_PATTERNS: Dict[str, Tuple[re.Pattern, Optional[int]]] = {
    # year: Année calendaire (publication, copyright) - domain-agnostic
    "year": (
        re.compile(r"(?:copyright|©|\(c\)|published|publication)\s*(?:[\d\-,\s]*)(20\d{2})", re.IGNORECASE),
        1,
    ),
    # effective_date: Date d'entrée en vigueur - domain-agnostic
    "effective_date": (
        re.compile(
            r"(?:since|from|as\s+of|effective|valid\s+from)\s+(\d{4}[-/]\d{2}(?:[-/]\d{2})?)",
            re.IGNORECASE
        ),
        1,
    ),
    # edition: Édition produit - domain-agnostic (requires "Edition" keyword)
    "edition": (
        re.compile(
            r"\b(Enterprise|Standard|Professional|Private|Public|Cloud|On-Premise)\s+Edition\b",
            re.IGNORECASE
        ),
        1,
    ),
    # phase: Phase de déploiement - domain-agnostic
    "phase": (
        re.compile(
            r"(?:Phase|Stage)\s*(I{1,3}|IV|V|[1-5]|One|Two|Three|Four|Five)",
            re.IGNORECASE
        ),
        1,
    ),
}

# NOTE: Les axes discriminants spécifiques au domaine (version, génération, modèle, etc.)
# ne sont PAS dans les fallback patterns car les conventions varient par domaine.
# → Le LLM extrait ces infos avec sa connaissance du domaine (INV-25 agnostique)


class ApplicabilityAxisDetector:
    """
    Détecte les axes d'applicabilité depuis les passages du document.

    Architecture LLM-first (INV-25 Domain Agnosticism):
    - Le LLM comprend les conventions de versioning de chaque produit
    - Pas de hardcoding domain-specific (SAP, Oracle, etc.)
    - Patterns fallback conservatifs si LLM indisponible

    C1/INV-25: Utilise des clés neutres (release_id, year...) avec
    display_name optionnel capturant le terme trouvé.

    C2: Retourne AxisObservation, pas validated_axes.
    """

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        use_llm_extraction: bool = True,
        tenant_id: Optional[str] = None,
    ):
        """
        Initialise le détecteur.

        Args:
            llm_client: Client LLM (si None, utilise fallback patterns)
            use_llm_extraction: Activer l'extraction LLM-first (recommandé)
            tenant_id: Tenant ID pour injection contexte domaine
        """
        self.llm_client = llm_client
        self.use_llm_extraction = use_llm_extraction
        self.tenant_id = tenant_id

        self.stats = {
            "documents_processed": 0,
            "axes_detected": 0,
            "values_extracted": 0,
            "llm_extractions": 0,
            "fallback_extractions": 0,
            "metadata_matches": 0,
        }

    def detect(
        self,
        doc_id: str,
        tenant_id: str,
        passages: List[Passage],
        doc_title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[AxisObservation]:
        """
        Détecte les axes d'applicabilité pour un document.

        Architecture:
        1. LLM Primary: Extraction intelligente basée sur connaissance LLM
        2. Pattern Fallback: Si LLM indisponible ou échec
        3. Metadata: Enrichissement depuis propriétés structurées

        Args:
            doc_id: Document ID
            tenant_id: Tenant ID
            passages: Passages du document
            doc_title: Titre du document (optionnel)
            metadata: Métadonnées du document (optionnel)

        Returns:
            Liste d'AxisObservation (pas validated_axes - C2)
        """
        observations: Dict[str, AxisObservation] = {}

        # Niveau 1 (Primary): Extraction LLM
        if self.use_llm_extraction:
            llm_success = self._detect_llm_first(
                doc_id=doc_id,
                doc_title=doc_title,
                passages=passages,
                observations=observations,
            )
            if llm_success:
                self.stats["llm_extractions"] += 1

        # Niveau 2 (Fallback): Patterns conservatifs si LLM n'a rien trouvé
        if not observations or not self.use_llm_extraction:
            self._detect_fallback_patterns(passages, observations)

        # Niveau 3: Metadata (enrichissement, toujours exécuté)
        if doc_title:
            self._detect_from_title(doc_title, doc_id, observations)
        if metadata:
            self._detect_from_metadata(metadata, doc_id, observations)

        self.stats["documents_processed"] += 1
        self.stats["axes_detected"] += len(observations)

        result = list(observations.values())

        logger.debug(
            f"[OSMOSE:AxisDetector] Detected {len(result)} axes for doc {doc_id}: "
            f"{[(o.axis_key, o.values_extracted) for o in result]}"
        )

        return result

    def _detect_llm_first(
        self,
        doc_id: str,
        doc_title: Optional[str],
        passages: List[Passage],
        observations: Dict[str, AxisObservation],
    ) -> bool:
        """
        Extraction LLM-first des axes d'applicabilité.

        Utilise la connaissance du LLM sur les conventions de versioning
        de chaque produit/domaine (INV-25 agnostique).

        Returns:
            True si extraction réussie et axes trouvés
        """
        # Construire le contexte
        context_parts = []
        if doc_title:
            context_parts.append(f"TITRE DU DOCUMENT: {doc_title}")

        # Échantillon de passages (premiers paragraphes souvent informatifs)
        sample_passages = passages[:5]
        for i, passage in enumerate(sample_passages):
            text_preview = passage.text[:600] if len(passage.text) > 600 else passage.text
            context_parts.append(f"PASSAGE {i+1}:\n{text_preview}")

        context = "\n\n".join(context_parts)

        # Prompt LLM-first (100% domain-agnostic - INV-25)
        prompt = f"""Analyse ce document et identifie ses caractéristiques discriminantes.

{context}

OBJECTIF:
Extraire les caractéristiques qui permettent de DISTINGUER et COMPARER ce document avec d'autres documents traitant du même sujet. Ces axes sont essentiels pour répondre à des questions comme "depuis quand?", "encore applicable?", "quelle version?".

INSTRUCTIONS:
1. Identifie le SUJET PRINCIPAL du document (produit, service, norme, véhicule, médicament, etc.)
2. Utilise TA CONNAISSANCE des conventions de ce domaine pour extraire les axes pertinents
3. Chaque domaine a ses propres conventions (version, génération, année-modèle, dosage, etc.)

Pour chaque axe trouvé, retourne:
- axis_key: identifiant court et neutre (ex: "version", "generation", "year", "model", "dosage"...)
- display_name: le terme EXACT utilisé dans le document
- value: la valeur extraite COMPLÈTE (pas tronquée)
- evidence: extrait du texte source
- confidence: 0.0-1.0

Réponds en JSON:
{{
  "subject": "le sujet principal identifié",
  "domain": "le domaine (software, automotive, pharmaceutical, legal, etc.)",
  "axes": [
    {{
      "axis_key": "identifiant neutre",
      "display_name": "terme trouvé dans le doc",
      "value": "valeur complète",
      "evidence": "extrait source",
      "confidence": 0.95
    }}
  ]
}}

RÈGLES:
- Extrais UNIQUEMENT les axes explicitement présents dans le document
- Utilise ta connaissance du domaine pour identifier la convention de versioning appropriée
- La valeur doit être COMPLÈTE (ex: "6.0 EHP 8" pas juste "6.0")
- Si aucun axe discriminant trouvé, retourne {{"subject": "...", "domain": "...", "axes": []}}

IMPORTANT: Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."""

        try:
            response = self._call_llm(prompt)
            return self._parse_llm_response(response, doc_id, observations)

        except Exception as e:
            logger.warning(f"[OSMOSE:AxisDetector] LLM extraction failed: {e}")
            return False

    def _call_llm(self, prompt: str) -> str:
        """Appelle le LLM via le router."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        router = get_llm_router()
        messages = [
            {"role": "user", "content": prompt}
        ]
        response = router.complete(
            task_type=TaskType.FAST_CLASSIFICATION,
            messages=messages,
            temperature=0.0,
            max_tokens=500,
        )
        return response

    def _parse_llm_response(
        self,
        response: str,
        doc_id: str,
        observations: Dict[str, AxisObservation],
    ) -> bool:
        """Parse la réponse JSON du LLM (format domain-agnostic)."""
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

            # Extraire métadonnées (pour logging/debug)
            subject = data.get("subject", "unknown")
            domain = data.get("domain", "unknown")
            axes = data.get("axes", [])

            if not axes:
                logger.debug(
                    f"[OSMOSE:AxisDetector] No axes found for {doc_id} "
                    f"(subject={subject}, domain={domain})"
                )
                return False

            for axis_data in axes:
                axis_key = axis_data.get("axis_key")
                value = axis_data.get("value")
                display_name = axis_data.get("display_name")
                evidence_text = axis_data.get("evidence", "")
                confidence = float(axis_data.get("confidence", 0.8))

                if not axis_key or not value:
                    continue

                # INV-26: Créer evidence span
                evidence = EvidenceSpan(
                    passage_id=None,
                    snippet_ref=f"llm_extraction:{doc_id}",
                    text_snippet=evidence_text[:200] if evidence_text else "LLM extraction",
                    confidence=confidence,
                )

                # Créer ou mettre à jour l'observation
                if axis_key not in observations:
                    observations[axis_key] = AxisObservation(
                        axis_key=axis_key,
                        axis_display_name=display_name,
                        values_extracted=[str(value)],
                        evidence_spans=[evidence],
                        reliability="llm_extracted",
                    )
                else:
                    obs = observations[axis_key]
                    if str(value) not in obs.values_extracted:
                        obs.values_extracted.append(str(value))
                        obs.evidence_spans.append(evidence)

                self.stats["values_extracted"] += 1

            logger.info(
                f"[OSMOSE:AxisDetector] LLM extracted {len(axes)} axes for {doc_id} "
                f"(subject={subject}, domain={domain}): "
                f"{[(a.get('axis_key'), a.get('value')) for a in axes]}"
            )
            return len(axes) > 0

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"[OSMOSE:AxisDetector] Failed to parse LLM response: {e}")
            return False

    def _detect_fallback_patterns(
        self,
        passages: List[Passage],
        observations: Dict[str, AxisObservation],
    ) -> None:
        """
        Détecte les axes via patterns fallback (domain-agnostic).

        Utilisé UNIQUEMENT si LLM indisponible ou échec.
        Ces patterns sont conservatifs et ne capturent que des cas évidents.
        """
        for passage in passages:
            text = passage.text

            for axis_key, (pattern, value_group) in FALLBACK_AXIS_PATTERNS.items():
                matches = pattern.finditer(text)

                for match in matches:
                    value = match.group(value_group) if value_group else match.group(0)
                    value = value.strip()

                    if not value:
                        continue

                    # INV-26: Créer evidence span
                    evidence = EvidenceSpan(
                        passage_id=passage.passage_id,
                        snippet_ref=f"offset:{match.start()}",
                        text_snippet=text[max(0, match.start()-20):min(len(text), match.end()+20)],
                        confidence=0.85,
                    )

                    # Créer ou mettre à jour l'observation
                    if axis_key not in observations:
                        observations[axis_key] = AxisObservation(
                            axis_key=axis_key,
                            values_extracted=[value],
                            evidence_spans=[evidence],
                            reliability="explicit_text",
                        )
                    else:
                        obs = observations[axis_key]
                        if value not in obs.values_extracted:
                            obs.values_extracted.append(value)
                            obs.evidence_spans.append(evidence)

                    self.stats["fallback_extractions"] += 1
                    self.stats["values_extracted"] += 1

    def _detect_from_title(
        self,
        title: str,
        doc_id: str,
        observations: Dict[str, AxisObservation],
    ) -> None:
        """
        Enrichit les observations depuis le titre du document.

        Note: Ne fait PAS d'extraction release_id depuis le titre car
        c'est domain-specific. Le LLM-first s'en charge.
        """
        evidence = EvidenceSpan(
            passage_id=None,
            snippet_ref=f"title:{doc_id}",
            text_snippet=title[:200],
            confidence=0.95,
        )

        # Patterns domain-agnostic uniquement
        for axis_key, (pattern, value_group) in FALLBACK_AXIS_PATTERNS.items():
            # Skip si déjà détecté par LLM avec haute confiance
            if axis_key in observations:
                existing = observations[axis_key]
                if existing.reliability == "llm_extracted":
                    continue  # LLM a priorité

            match = pattern.search(title)
            if match:
                value = match.group(value_group) if value_group else match.group(0)
                value = value.strip()

                if not value:
                    continue

                if axis_key not in observations:
                    observations[axis_key] = AxisObservation(
                        axis_key=axis_key,
                        values_extracted=[value],
                        evidence_spans=[evidence],
                        reliability="metadata",
                    )
                else:
                    obs = observations[axis_key]
                    if value not in obs.values_extracted:
                        obs.values_extracted.append(value)
                        obs.evidence_spans.append(evidence)

                self.stats["metadata_matches"] += 1

    def _detect_from_metadata(
        self,
        metadata: Dict[str, Any],
        doc_id: str,
        observations: Dict[str, AxisObservation],
    ) -> None:
        """
        Détecte les axes depuis les métadonnées (domain-agnostic).
        """
        # Mapping métadonnées → axis_key (neutre, pas domain-specific)
        metadata_mapping = {
            "version": "release_id",
            "product_version": "release_id",
            "release": "release_id",
            "year": "year",
            "publication_year": "year",
            "edition": "edition",
            "effective_date": "effective_date",
        }

        evidence = EvidenceSpan(
            passage_id=None,
            snippet_ref=f"metadata:{doc_id}",
            text_snippet="document metadata",
            confidence=0.98,
        )

        for meta_key, axis_key in metadata_mapping.items():
            if meta_key in metadata and metadata[meta_key]:
                value = str(metadata[meta_key]).strip()

                # Skip si LLM a déjà extrait cet axe
                if axis_key in observations:
                    existing = observations[axis_key]
                    if existing.reliability == "llm_extracted":
                        continue  # LLM a priorité

                if axis_key not in observations:
                    observations[axis_key] = AxisObservation(
                        axis_key=axis_key,
                        axis_display_name=meta_key,
                        values_extracted=[value],
                        evidence_spans=[evidence],
                        reliability="metadata",
                    )
                else:
                    obs = observations[axis_key]
                    if value not in obs.values_extracted:
                        obs.values_extracted.append(value)
                        obs.evidence_spans.append(evidence)
                    obs.reliability = "metadata"

                self.stats["metadata_matches"] += 1

    def create_axes_from_observations(
        self,
        observations: List[AxisObservation],
        tenant_id: str,
        doc_id: str,
        order_inferrer: Optional["AxisOrderInferrer"] = None,
    ) -> List[ApplicabilityAxis]:
        """
        Crée des ApplicabilityAxis depuis les observations.

        Args:
            observations: Observations détectées
            tenant_id: Tenant ID
            doc_id: Document ID
            order_inferrer: Inferrer d'ordre (optionnel)

        Returns:
            Liste d'ApplicabilityAxis
        """
        from knowbase.claimfirst.axes.axis_order_inferrer import AxisOrderInferrer

        inferrer = order_inferrer or AxisOrderInferrer()
        axes = []

        for obs in observations:
            # Inférer l'ordre
            order_result = inferrer.infer_order(obs.axis_key, obs.values_extracted)

            axis = ApplicabilityAxis.create_new(
                tenant_id=tenant_id,
                axis_key=obs.axis_key,
                axis_display_name=obs.axis_display_name,
                doc_id=doc_id,
            )

            # Ajouter les valeurs
            for value in obs.values_extracted:
                axis.add_value(value, doc_id)

            # Configurer l'ordonnabilité
            axis.is_orderable = order_result.is_orderable
            axis.order_type = order_result.order_type
            axis.ordering_confidence = order_result.confidence
            axis.value_order = order_result.inferred_order

            axes.append(axis)

        return axes

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques de détection."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "documents_processed": 0,
            "axes_detected": 0,
            "values_extracted": 0,
            "llm_extractions": 0,
            "fallback_extractions": 0,
            "metadata_matches": 0,
        }


__all__ = [
    "ApplicabilityAxisDetector",
    "AxisObservation",
    "FALLBACK_AXIS_PATTERNS",
]
