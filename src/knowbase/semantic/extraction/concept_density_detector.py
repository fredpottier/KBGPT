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

    # Patterns techniques (ISO, RFC, SAP, etc.)
    TECHNICAL_PATTERNS = [
        r'\bISO\s+\d{4,5}(?:-\d+)?\b',          # ISO 27001, ISO/IEC 27034-1
        r'\bRFC\s+\d{3,5}\b',                    # RFC 2616
        r'\bSAP\s+[A-Z0-9/]+\b',                 # SAP S/4HANA, SAP ECC
        r'\b[A-Z]{2,}[-/][A-Z0-9]+\b',          # ERP/CRM, CI/CD
        r'\b[A-Z]{3,}\b(?=\s|$|[,.])',          # SAST, DAST, CVSS (3+ majuscules)
        r'\bCVE-\d{4}-\d{4,7}\b',               # CVE-2021-12345
        r'\bCWE-\d{1,4}\b',                      # CWE-79
        r'\bOWASP\s+Top\s+\d+\b',               # OWASP Top 10
        r'\b(?:GDPR|SOC\s*2|HIPAA|PCI\s*DSS)\b',  # Standards compliance
    ]

    # Mots techniques courants (enrichir au besoin)
    TECHNICAL_KEYWORDS = {
        # Security
        "penetration", "vulnerability", "exploit", "malware", "phishing",
        "authentication", "authorization", "encryption", "cryptography",
        "firewall", "intrusion", "detection", "prevention", "remediation",

        # DevOps/SDLC
        "deployment", "pipeline", "orchestration", "containerization",
        "microservices", "kubernetes", "docker", "jenkins", "gitlab",

        # SAP Specific
        "fiori", "hana", "netweaver", "bapi", "idoc", "abap",

        # Standards/Frameworks
        "compliance", "audit", "governance", "framework", "methodology",
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
        language: str = "en"
    ) -> DensityProfile:
        """
        Analyse la densité conceptuelle d'un texte.

        Args:
            text: Texte à analyser (utilise échantillon début)
            sample_size: Taille échantillon (chars)
            language: Langue du texte

        Returns:
            DensityProfile avec recommandation méthode extraction
        """
        # Échantillon début du texte (concepts clés souvent au début)
        sample = text[:sample_size]

        if len(sample) < 200:
            # Texte trop court → analyse non fiable, utiliser hybrid
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

        # Calcul score densité (pondération des indicateurs)
        density_score = self._calculate_density_score(
            acronym_density=acronym_density,
            technical_pattern_count=technical_pattern_count,
            rare_vocab_ratio=rare_vocab_ratio,
            ner_preview_ratio=ner_preview_ratio
        )

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
                "ner_preview_ratio": ner_preview_ratio
            }
        )

        logger.info(
            f"[OSMOSE] Density Analysis: score={density_score:.2f}, "
            f"method={recommended_method.value}, confidence={confidence:.2f}"
        )
        logger.debug(
            f"[OSMOSE] Indicators: acronyms={acronym_density:.1f}/100w, "
            f"tech_patterns={technical_pattern_count}, rare_vocab={rare_vocab_ratio:.2f}, "
            f"ner_preview={ner_preview_ratio:.2f}"
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

        Seuils:
        - 0.0-0.30: NER_ONLY (texte simple)
        - 0.30-0.55: NER_LLM_HYBRID (standard)
        - 0.55-1.0: LLM_FIRST (texte dense) ← ABAISSÉ pour docs techniques

        Returns:
            (method, confidence)
        """
        if density_score < 0.35:
            # Faible densité → NER efficace
            confidence = 0.8 + (0.35 - density_score) * 0.5  # 0.8-1.0
            return ExtractionMethod.NER_ONLY, confidence

        elif density_score < 0.65:
            # Densité moyenne → Hybrid standard
            # Confiance plus faible au milieu de la zone
            distance_from_center = abs(density_score - 0.5)
            confidence = 0.6 + distance_from_center  # 0.6-0.75
            return ExtractionMethod.NER_LLM_HYBRID, confidence

        else:
            # Haute densité → LLM first
            confidence = 0.7 + (density_score - 0.65) * 0.85  # 0.7-1.0
            return ExtractionMethod.LLM_FIRST, confidence
