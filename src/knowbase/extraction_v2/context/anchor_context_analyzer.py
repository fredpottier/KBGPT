"""
AnchorContextAnalyzer - Analyse de contexte pour les anchors.

Orchestre l'analyse de contexte en deux etapes:
1. Heuristics: detection deterministe de polarity, markers, overrides
2. LLM Validation: appel LLM uniquement si necessaire (ambiguity)

Le resultat est un AnchorContext qui enrichit l'anchor.

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 3.3
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import json
import re
import logging

from knowbase.extraction_v2.context.anchor_models import (
    Polarity,
    AssertionScope,
    OverrideType,
    QualifierSource,
    LocalMarker,
    AnchorContext,
    ProtoConceptContext,
)
from knowbase.extraction_v2.context.heuristics import (
    PassageHeuristics,
    HeuristicResult,
)
from knowbase.extraction_v2.context.models import (
    DocScope,
    DocContextFrame,
)

logger = logging.getLogger(__name__)


# Prompts pour LLM (si necessaire)
ANCHOR_ANALYSIS_SYSTEM_PROMPT = """You are analyzing a text passage to determine its assertion context.

Your task:
1. Determine the polarity (positive, negative, future, deprecated, conditional)
2. Identify any version/edition markers in the passage
3. Detect if the passage overrides document-level context

Respond with valid JSON only."""


ANCHOR_ANALYSIS_USER_PROMPT = """## Passage to analyze:
```
{passage}
```

## Document context (for reference):
- Document markers: {doc_markers}
- Document scope: {doc_scope}

## Pre-computed heuristics:
{heuristics}

## Output format:
{{
  "polarity": "positive|negative|future|deprecated|conditional|unknown",
  "local_markers": [{{"value": "...", "evidence": "quote"}}],
  "is_override": true|false,
  "override_type": "switch|range|generalization|null",
  "confidence": 0.0,
  "evidence": ["quote1"]
}}"""


class AnchorContextAnalyzer:
    """
    Analyseur de contexte pour anchors.

    Utilise les heuristiques en premier, appelle le LLM si necessaire.

    Usage:
        >>> analyzer = AnchorContextAnalyzer()
        >>> context = await analyzer.analyze(
        ...     passage="This feature is not available in 1809",
        ...     doc_context=doc_context_frame,
        ... )
        >>> print(context.polarity)  # Polarity.NEGATIVE
    """

    def __init__(
        self,
        use_llm: bool = True,
        llm_temperature: float = 0.0,
        llm_max_tokens: int = 512,
    ):
        """
        Initialise l'analyseur.

        Args:
            use_llm: Utiliser le LLM pour cas ambigus
            llm_temperature: Temperature pour le LLM
            llm_max_tokens: Max tokens pour la reponse LLM
        """
        self.use_llm = use_llm
        self.llm_temperature = llm_temperature
        self.llm_max_tokens = llm_max_tokens

        # Heuristiques
        self._heuristics = PassageHeuristics()

        # LLM Router (lazy init)
        self._llm_router = None

    def _get_llm_router(self):
        """Lazy init du LLM Router."""
        if self._llm_router is None:
            from knowbase.common.llm_router import get_llm_router
            self._llm_router = get_llm_router()
        return self._llm_router

    async def analyze(
        self,
        passage: str,
        doc_context: Optional[DocContextFrame] = None,
    ) -> AnchorContext:
        """
        Analyse un passage et retourne son contexte d'anchor.

        Args:
            passage: Texte du passage (quote de l'anchor)
            doc_context: Contexte documentaire (si disponible)

        Returns:
            AnchorContext avec polarity, scope, markers
        """
        if not passage or len(passage) < 5:
            return AnchorContext.neutral()

        # === ETAPE 1: Heuristiques ===
        heuristic_result = self._heuristics.analyze(passage)

        logger.debug(
            f"[AnchorContextAnalyzer] Heuristics: polarity={heuristic_result.polarity.value}, "
            f"markers={[m.value for m in heuristic_result.local_markers]}, "
            f"override={heuristic_result.is_override}, needs_llm={heuristic_result.needs_llm}"
        )

        # === ETAPE 2: LLM si necessaire ===
        if self.use_llm and heuristic_result.needs_llm:
            try:
                context = await self._analyze_with_llm(
                    passage=passage,
                    doc_context=doc_context,
                    heuristic_result=heuristic_result,
                )
                return context
            except Exception as e:
                logger.warning(
                    f"[AnchorContextAnalyzer] LLM failed: {e}, using heuristics only"
                )

        # === Construire le contexte depuis heuristiques ===
        return self._build_context_from_heuristics(
            heuristic_result=heuristic_result,
            doc_context=doc_context,
        )

    def analyze_sync(
        self,
        passage: str,
        doc_context: Optional[DocContextFrame] = None,
    ) -> AnchorContext:
        """
        Analyse synchrone (heuristiques uniquement).

        Args:
            passage: Texte du passage
            doc_context: Contexte documentaire

        Returns:
            AnchorContext
        """
        if not passage or len(passage) < 5:
            return AnchorContext.neutral()

        heuristic_result = self._heuristics.analyze(passage)

        return self._build_context_from_heuristics(
            heuristic_result=heuristic_result,
            doc_context=doc_context,
        )

    def _build_context_from_heuristics(
        self,
        heuristic_result: HeuristicResult,
        doc_context: Optional[DocContextFrame],
    ) -> AnchorContext:
        """
        Construit un AnchorContext depuis les heuristiques.

        Applique la matrice d'heritage si doc_context disponible.
        """
        # Determiner le scope
        scope, qualifier_source = self._determine_scope(
            heuristic_result=heuristic_result,
            doc_context=doc_context,
        )

        # Calculer la confiance
        confidence = self._compute_confidence(
            heuristic_result=heuristic_result,
            scope=scope,
            qualifier_source=qualifier_source,
        )

        return AnchorContext(
            polarity=heuristic_result.polarity,
            scope=scope,
            local_markers=heuristic_result.local_markers,
            is_override=heuristic_result.is_override,
            override_type=heuristic_result.override_type,
            confidence=confidence,
            qualifier_source=qualifier_source,
            evidence=heuristic_result.polarity_evidence[:2],
        )

    def _determine_scope(
        self,
        heuristic_result: HeuristicResult,
        doc_context: Optional[DocContextFrame],
    ) -> tuple:
        """
        Determine le scope de l'anchor selon la matrice d'heritage.

        Retourne (scope, qualifier_source).

        Regles (ADR Section 3.4):
        - Si override: utiliser marqueurs locaux
        - Si doc_scope=VARIANT_SPECIFIC et strong_markers: heriter
        - Si doc_scope=MIXED: pas d'heritage par defaut
        - Si doc_scope=GENERAL: scope=general
        """
        # Cas 1: Override detecte -> utiliser marqueurs locaux
        if heuristic_result.is_override and heuristic_result.local_markers:
            return (AssertionScope.CONSTRAINED, QualifierSource.EXPLICIT)

        # Cas 2: Marqueurs locaux sans override -> explicit
        if heuristic_result.local_markers:
            return (AssertionScope.CONSTRAINED, QualifierSource.EXPLICIT)

        # Cas 3: Pas de doc_context -> unknown
        if doc_context is None:
            return (AssertionScope.UNKNOWN, QualifierSource.NONE)

        # Cas 4: Appliquer la matrice d'heritage
        if doc_context.doc_scope == DocScope.GENERAL:
            return (AssertionScope.GENERAL, QualifierSource.NONE)

        if doc_context.doc_scope == DocScope.VARIANT_SPECIFIC:
            if doc_context.strong_markers:
                return (AssertionScope.CONSTRAINED, QualifierSource.INHERITED_STRONG)
            elif doc_context.weak_markers:
                return (AssertionScope.CONSTRAINED, QualifierSource.INHERITED_WEAK)

        if doc_context.doc_scope == DocScope.MIXED:
            # MIXED = pas d'heritage par defaut
            return (AssertionScope.UNKNOWN, QualifierSource.NONE)

        return (AssertionScope.UNKNOWN, QualifierSource.NONE)

    def _compute_confidence(
        self,
        heuristic_result: HeuristicResult,
        scope: AssertionScope,
        qualifier_source: QualifierSource,
    ) -> float:
        """Calcule la confiance globale."""
        base_confidence = heuristic_result.polarity_confidence

        # Ajuster selon la source du qualificateur
        if qualifier_source == QualifierSource.EXPLICIT:
            return min(1.0, base_confidence * 1.0)
        elif qualifier_source == QualifierSource.INHERITED_STRONG:
            return min(1.0, base_confidence * 0.95)
        elif qualifier_source == QualifierSource.INHERITED_WEAK:
            return min(1.0, base_confidence * 0.85)
        else:
            return base_confidence * 0.8

    async def _analyze_with_llm(
        self,
        passage: str,
        doc_context: Optional[DocContextFrame],
        heuristic_result: HeuristicResult,
    ) -> AnchorContext:
        """
        Analyse avec LLM pour cas ambigus.
        """
        from knowbase.common.llm_router import TaskType

        # Preparer le contexte document
        doc_markers = []
        doc_scope = "UNKNOWN"
        if doc_context:
            doc_markers = doc_context.strong_markers + doc_context.weak_markers
            doc_scope = doc_context.doc_scope.value

        # Preparer les heuristiques
        heuristics_str = json.dumps({
            "polarity": heuristic_result.polarity.value,
            "polarity_confidence": heuristic_result.polarity_confidence,
            "local_markers": [m.value for m in heuristic_result.local_markers],
            "is_override": heuristic_result.is_override,
            "override_type": heuristic_result.override_type.value,
        }, indent=2)

        # Construire le prompt
        user_prompt = ANCHOR_ANALYSIS_USER_PROMPT.format(
            passage=passage[:500],  # Limiter la taille
            doc_markers=doc_markers,
            doc_scope=doc_scope,
            heuristics=heuristics_str,
        )

        messages = [
            {"role": "system", "content": ANCHOR_ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # Appeler le LLM
        router = self._get_llm_router()
        response = await router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=self.llm_temperature,
            max_tokens=self.llm_max_tokens,
        )

        # Parser la reponse
        return self._parse_llm_response(response, heuristic_result, doc_context)

    def _parse_llm_response(
        self,
        response: str,
        heuristic_result: HeuristicResult,
        doc_context: Optional[DocContextFrame],
    ) -> AnchorContext:
        """Parse la reponse LLM et construit l'AnchorContext."""
        # Nettoyer la reponse
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response = "\n".join(lines)

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # Essayer d'extraire le JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
            else:
                # Fallback aux heuristiques
                return self._build_context_from_heuristics(heuristic_result, doc_context)

        # Parser les champs
        polarity_str = data.get("polarity", "unknown").lower()
        try:
            polarity = Polarity(polarity_str)
        except ValueError:
            polarity = heuristic_result.polarity

        # Parser les marqueurs locaux
        local_markers = []
        for m in data.get("local_markers", []):
            if isinstance(m, dict) and "value" in m:
                local_markers.append(LocalMarker(
                    value=m["value"],
                    evidence=m.get("evidence", ""),
                    confidence=0.9,
                ))

        # Si pas de marqueurs du LLM, garder ceux des heuristiques
        if not local_markers:
            local_markers = heuristic_result.local_markers

        is_override = data.get("is_override", heuristic_result.is_override)

        override_type_str = data.get("override_type", "null")
        try:
            override_type = OverrideType(override_type_str)
        except ValueError:
            override_type = heuristic_result.override_type

        confidence = data.get("confidence", 0.7)

        # Determiner scope
        scope, qualifier_source = self._determine_scope(
            HeuristicResult(
                polarity=polarity,
                local_markers=local_markers,
                is_override=is_override,
                override_type=override_type,
            ),
            doc_context,
        )

        return AnchorContext(
            polarity=polarity,
            scope=scope,
            local_markers=local_markers,
            is_override=is_override,
            override_type=override_type,
            confidence=confidence,
            qualifier_source=qualifier_source,
            evidence=data.get("evidence", [])[:2],
        )

    async def analyze_batch(
        self,
        passages: List[str],
        doc_context: Optional[DocContextFrame] = None,
    ) -> List[AnchorContext]:
        """
        Analyse un batch de passages.

        Args:
            passages: Liste de passages
            doc_context: Contexte documentaire

        Returns:
            Liste d'AnchorContext
        """
        results = []
        for passage in passages:
            context = await self.analyze(passage, doc_context)
            results.append(context)
        return results

    def analyze_batch_sync(
        self,
        passages: List[str],
        doc_context: Optional[DocContextFrame] = None,
    ) -> List[AnchorContext]:
        """
        Analyse synchrone d'un batch de passages.
        """
        results = []
        for passage in passages:
            context = self.analyze_sync(passage, doc_context)
            results.append(context)
        return results


# Singleton
_analyzer_instance: Optional[AnchorContextAnalyzer] = None


def get_anchor_context_analyzer() -> AnchorContextAnalyzer:
    """Retourne l'instance singleton de l'analyseur."""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = AnchorContextAnalyzer()
    return _analyzer_instance


__all__ = [
    "AnchorContextAnalyzer",
    "get_anchor_context_analyzer",
]
