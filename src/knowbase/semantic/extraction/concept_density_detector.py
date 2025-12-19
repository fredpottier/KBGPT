"""
🌊 OSMOSE Semantic Intelligence V2.2 - Concept Density Detector

Détecte la densité conceptuelle d'un texte pour optimiser la méthode d'extraction.

**Problème Résolu:**
- spaCy NER sous-performe sur vocabulaire technique dense (SDOL, BISO, DPCE, etc.)
- Perte de temps/tokens à tenter NER sur texte dense → mieux aller directement au LLM

**Heuristiques:**
1. Acronymes (ISO XXXX, RFC XXXX, SAP XXX, etc.)
2. Termes techniques (patterns spécialisés)
3. Vocabulaire rare (absents dictionnaire courant)
4. Ratio entités NER rapide / tokens

**Décision:**
- LOW density (0.0-0.3): NER_ONLY (rapide, efficace)
- MEDIUM density (0.3-0.6): NER_LLM_HYBRID (flow standard)
- HIGH density (0.6-1.0): LLM_FIRST (skip NER inefficace)

Phase 1 V2.2 - Semaine 10+ (Optimisation Extraction)
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re
import logging
from collections import Counter

logger = logging.getLogger(__name__)


class ExtractionMethod(str, Enum):
    """Méthode d'extraction recommandée."""
    NER_ONLY = "NER_ONLY"              # Texte simple, NER suffit
    NER_LLM_HYBRID = "NER_LLM_HYBRID"  # Standard flow (NER + LLM si insuffisant)
    LLM_FIRST = "LLM_FIRST"            # Texte dense, LLM d'emblée


@dataclass
class DensityProfile:
    """Profil de densité conceptuelle d'un texte."""

    density_score: float  # 0-1 (0=faible, 1=très dense)
    recommended_method: ExtractionMethod
    confidence: float  # 0-1 (confiance dans la recommandation)

    # Indicateurs détaillés
    acronym_density: float  # Acronymes par 100 mots
    technical_pattern_count: int  # Patterns techniques détectés
    rare_vocab_ratio: float  # Ratio mots rares / total
    ner_preview_ratio: float  # Entités NER sur échantillon / tokens

    # Métadonnées
    sample_length: int  # Longueur échantillon analysé
    indicators: Dict[str, any]  # Signaux détectés


class ConceptDensityDetector:
    """
    Détecteur de densité conceptuelle pour optimisation extraction.

    Analyse rapide (< 100ms) d'un échantillon de texte pour déterminer
    la méthode d'extraction optimale (NER vs LLM).

    **Usage:**
    ```python
    detector = ConceptDensityDetector()
    profile = detector.analyze_density(topic_text[:2000])

    if profile.recommended_method == ExtractionMethod.LLM_FIRST:
        # Skip NER, aller direct au LLM
        concepts = await self._extract_via_llm(topic, language)
    else:
        # Flow standard NER + LLM hybrid
        concepts = await self._extract_via_ner(topic, language)
    ```
    """

    # Patterns techniques génériques (domain-agnostic)
    # Détecte les structures formelles communes à tous les domaines techniques
    TECHNICAL_PATTERNS = [
        r'\b[A-Z]{2,}[-/][A-Z0-9]+\b',          # Acronymes composés: ERP/CRM, CI/CD, COVID-19
        r'\b[A-Z]{3,}\b(?=\s|$|[,.])',          # Acronymes 3+ lettres: SAST, FDA, HANA
        r'\b[A-Z]+\s+\d{4,}(?:-\d+)?\b',        # Standards avec numéros: ISO 27001, RFC 2616
        r'\b\d+\.\d+(?:\.\d+)?\b',              # Versions/numéros: 2.0, 3.1.4
        r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b',     # CamelCase: SuccessFactors, NetWeaver
    ]

    # Mots génériques indiquant un texte technique (domain-agnostic)
    # Ces mots sont communs à TOUS les domaines techniques, pas spécifiques à un vertical
    TECHNICAL_KEYWORDS = {
        # Structure documentaire technique
        "implementation", "configuration", "integration", "specification",
        "architecture", "infrastructure", "optimization", "documentation",

        # Processus/Méthodologie générique
        "methodology", "framework", "compliance", "governance", "workflow",
        "procedure", "protocol", "standard", "requirement", "specification",

        # Analyse/Évaluation générique
        "analysis", "assessment", "evaluation", "validation", "verification",
        "benchmark", "performance", "metrics", "criteria", "threshold",
    }

    def __init__(self, ner_manager=None):
        """
        Initialise le détecteur.

        Args:
            ner_manager: (Optionnel) NERManager pour test NER preview
        """
        self.ner_manager = ner_manager

        # Compiler patterns pour performance
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.TECHNICAL_PATTERNS
        ]

        logger.info("[OSMOSE] ConceptDensityDetector initialized")

    def analyze_density(
        self,
        text: str,
        sample_size: int = 2000,
        language: str = "en",
        technical_density_hint: float = 0.0
    ) -> DensityProfile:
        """
        Analyse la densité conceptuelle d'un texte.

        Phase 1.8.2: Intègre technical_density_hint du LLM (domain-agnostic).
        Le hint LLM permet d'ajuster la détection pour n'importe quel domaine
        sans avoir à maintenir des patterns spécifiques par vertical métier.

        Args:
            text: Texte à analyser (utilise échantillon début)
            sample_size: Taille échantillon (chars)
            language: Langue du texte
            technical_density_hint: Hint LLM 0-1 (0=simple, 1=très technique)

        Returns:
            DensityProfile avec recommandation méthode extraction
        """
        # Échantillon début du texte (concepts clés souvent au début)
        sample = text[:sample_size]

        if len(sample) < 200:
            # Texte trop court → analyse non fiable, utiliser hybrid
            # Mais si hint LLM fort, respecter le hint
            if technical_density_hint >= 0.6:
                logger.debug("[OSMOSE] Text too short but LLM hint is high, using LLM_FIRST")
                return DensityProfile(
                    density_score=technical_density_hint,
                    recommended_method=ExtractionMethod.LLM_FIRST,
                    confidence=0.7,
                    acronym_density=0.0,
                    technical_pattern_count=0,
                    rare_vocab_ratio=0.0,
                    ner_preview_ratio=0.0,
                    sample_length=len(sample),
                    indicators={"reason": "text_too_short_but_llm_hint_high", "llm_hint": technical_density_hint}
                )
            logger.debug("[OSMOSE] Text too short for density analysis, defaulting to HYBRID")
            return DensityProfile(
                density_score=0.5,
                recommended_method=ExtractionMethod.NER_LLM_HYBRID,
                confidence=0.3,
                acronym_density=0.0,
                technical_pattern_count=0,
                rare_vocab_ratio=0.0,
                ner_preview_ratio=0.0,
                sample_length=len(sample),
                indicators={"reason": "text_too_short"}
            )

        # 1. Acronym Density
        acronym_density = self._calculate_acronym_density(sample)

        # 2. Technical Patterns
        technical_pattern_count = self._count_technical_patterns(sample)

        # 3. Rare Vocabulary Ratio
        rare_vocab_ratio = self._calculate_rare_vocab_ratio(sample)

        # 4. NER Preview (si NER disponible)
        ner_preview_ratio = self._test_ner_preview(sample, language) if self.ner_manager else 0.0

        # Calcul score densité (pondération des indicateurs heuristiques)
        heuristic_score = self._calculate_density_score(
            acronym_density=acronym_density,
            technical_pattern_count=technical_pattern_count,
            rare_vocab_ratio=rare_vocab_ratio,
            ner_preview_ratio=ner_preview_ratio
        )

        # Phase 1.8.2: Combiner score heuristique avec hint LLM
        # Si hint > 0, il a été fourni par le LLM lors de l'analyse document
        # Pondération: 40% heuristique + 60% LLM hint (le LLM comprend mieux le domaine)
        if technical_density_hint > 0:
            density_score = (0.4 * heuristic_score) + (0.6 * technical_density_hint)
            logger.info(
                f"[OSMOSE] Density score combined: heuristic={heuristic_score:.2f} + "
                f"LLM_hint={technical_density_hint:.2f} → final={density_score:.2f}"
            )
        else:
            density_score = heuristic_score

        # Recommandation méthode
        recommended_method, confidence = self._recommend_method(density_score)

        # Construire profil
        profile = DensityProfile(
            density_score=density_score,
            recommended_method=recommended_method,
            confidence=confidence,
            acronym_density=acronym_density,
            technical_pattern_count=technical_pattern_count,
            rare_vocab_ratio=rare_vocab_ratio,
            ner_preview_ratio=ner_preview_ratio,
            sample_length=len(sample),
            indicators={
                "acronym_density": acronym_density,
                "technical_patterns": technical_pattern_count,
                "rare_vocab_ratio": rare_vocab_ratio,
                "ner_preview_ratio": ner_preview_ratio,
                "llm_hint": technical_density_hint,
                "heuristic_score": heuristic_score
            }
        )

        logger.info(
            f"[OSMOSE] Density Analysis: score={density_score:.2f}, "
            f"method={recommended_method.value}, confidence={confidence:.2f}"
        )
        logger.debug(
            f"[OSMOSE] Indicators: acronyms={acronym_density:.1f}/100w, "
            f"tech_patterns={technical_pattern_count}, rare_vocab={rare_vocab_ratio:.2f}, "
            f"ner_preview={ner_preview_ratio:.2f}, llm_hint={technical_density_hint:.2f}"
        )

        return profile

    def _calculate_acronym_density(self, text: str) -> float:
        """
        Calcule densité acronymes (acronymes par 100 mots).

        Détecte:
        - Mots 3+ majuscules consécutives (SAST, ISO, ERP)
        - Mots avec chiffres (S/4HANA, RFC2616)
        """
        # Tokeniser mots simples
        words = re.findall(r'\b\w+\b', text)

        if not words:
            return 0.0

        # Détecter acronymes
        acronym_pattern = re.compile(r'^[A-Z]{3,}$|^[A-Z]+\d+[A-Z]*$|^[A-Z]+[-/][A-Z0-9]+$')
        acronyms = [w for w in words if acronym_pattern.match(w)]

        # Acronymes par 100 mots
        density = (len(acronyms) / len(words)) * 100

        return density

    def _count_technical_patterns(self, text: str) -> int:
        """
        Compte patterns techniques (ISO XXXX, RFC XXXX, etc.).
        """
        count = 0
        for pattern in self.compiled_patterns:
            matches = pattern.findall(text)
            count += len(matches)

        return count

    def _calculate_rare_vocab_ratio(self, text: str) -> float:
        """
        Calcule ratio vocabulaire rare / total.

        "Rare" = mots longs (8+ chars) ou absents liste mots courants.
        Approximation simple sans dictionnaire externe pour performance.
        """
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())

        if not words:
            return 0.0

        # Mots "rares" = 8+ caractères (souvent techniques)
        # + présence dans TECHNICAL_KEYWORDS
        rare_words = [
            w for w in words
            if len(w) >= 8 or w in self.TECHNICAL_KEYWORDS
        ]

        ratio = len(rare_words) / len(words)

        return ratio

    def _test_ner_preview(self, sample: str, language: str) -> float:
        """
        Test NER sur échantillon court (500 chars) pour estimer efficacité.

        Returns:
            Ratio entités détectées / tokens (0-1)
        """
        if not self.ner_manager:
            return 0.0

        # Prendre sous-échantillon pour rapidité
        test_sample = sample[:500]

        try:
            # Extraction NER rapide
            entities = self.ner_manager.extract_entities(test_sample, language=language)

            # Compter tokens
            words = re.findall(r'\b\w+\b', test_sample)

            if not words:
                return 0.0

            # Ratio entités / tokens
            ratio = len(entities) / len(words)

            return ratio

        except Exception as e:
            logger.warning(f"[OSMOSE] NER preview failed: {e}")
            return 0.0

    def _calculate_density_score(
        self,
        acronym_density: float,
        technical_pattern_count: int,
        rare_vocab_ratio: float,
        ner_preview_ratio: float
    ) -> float:
        """
        Calcule score densité global (0-1).

        Pondération:
        - Acronym density: 30%
        - Technical patterns: 25%
        - Rare vocab: 25%
        - NER preview: 20%
        """
        # Normaliser inputs
        # Acronym density: 0-15 acronymes/100w → 0-1
        norm_acronym = min(acronym_density / 15.0, 1.0)

        # Technical patterns: 0-10 patterns → 0-1
        norm_patterns = min(technical_pattern_count / 10.0, 1.0)

        # Rare vocab: déjà 0-1
        norm_rare_vocab = rare_vocab_ratio

        # NER preview: faible ratio → haute densité (inverse)
        # Si NER trouve < 10% entités → texte dense
        norm_ner = 1.0 - (ner_preview_ratio * 10)  # Inverser + amplifier
        norm_ner = max(0.0, min(norm_ner, 1.0))

        # Score pondéré
        score = (
            0.30 * norm_acronym +
            0.25 * norm_patterns +
            0.25 * norm_rare_vocab +
            0.20 * norm_ner
        )

        return score

    def _recommend_method(
        self,
        density_score: float
    ) -> Tuple[ExtractionMethod, float]:
        """
        Recommande méthode extraction basée sur density score.

        Seuils (Phase 1.8.2 - Optimisé pour docs techniques/scientifiques):
        - 0.0-0.25: NER_ONLY (texte très simple, marketing, etc.)
        - 0.25-0.40: NER_LLM_HYBRID (standard business docs)
        - 0.40-1.0: LLM_FIRST (texte technique/scientifique) ← ABAISSÉ de 0.55

        Rationale: Les documents techniques (médicaux, scientifiques, SAP) ont
        souvent une densité > 0.40 et NER spaCy sous-performe sur ce vocabulaire.
        Mieux vaut aller au LLM directement pour meilleur recall.

        Returns:
            (method, confidence)
        """
        if density_score < 0.25:  # Abaissé de 0.30
            # Faible densité → NER efficace (textes simples)
            confidence = 0.8 + (0.25 - density_score) * 0.6
            return ExtractionMethod.NER_ONLY, confidence

        elif density_score < 0.40:  # Abaissé de 0.55 à 0.40
            # Densité moyenne → Hybrid standard
            distance_from_center = abs(density_score - 0.325)  # Center of 0.25-0.40
            confidence = 0.6 + distance_from_center  # 0.6-0.75
            return ExtractionMethod.NER_LLM_HYBRID, confidence

        else:
            # Haute densité → LLM first (textes techniques/scientifiques)
            # Seuil abaissé de 0.55 à 0.40 pour capturer plus de textes techniques
            confidence = 0.75 + (density_score - 0.40) * 0.4
            return ExtractionMethod.LLM_FIRST, confidence
