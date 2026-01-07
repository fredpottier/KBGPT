"""
Candidate Mining pour extraction de marqueurs contextuels.

Ce module extrait les candidats de marqueurs de maniere DETERMINISTE
(sans LLM) a partir de:
- Filename
- Premieres pages (cover/title)
- Headers/footers
- Blocs revision/history

Les candidats sont ensuite enrichis avec analyse structurelle (PR6)
et valides par le LLM (anti-hallucination).

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 3.1
Spec: doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md - Section 4.3
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from pathlib import Path
import re
import logging

if TYPE_CHECKING:
    from knowbase.extraction_v2.context.structural import (
        StructuralAnalysis,
        ContextualCues,
        StructuralConfidence,
    )

logger = logging.getLogger(__name__)


# === PHASE 1: FILTRES UNIVERSELS (CandidateGate) ===
# Ces patterns ELIMINENT les faux positifs avant scoring
# Principe: Safe-by-default - en cas de doute, rejeter le candidat

# Formats de dates explicites - ces 4 chiffres sont des DATES, pas des versions
DATE_FORMAT_PATTERNS = [
    # Formats explicites: 05/23/2019, 2019-05-23, 23.05.2019
    r'(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.])(\d{4})',  # MM/DD/YYYY ou DD/MM/YYYY
    r'(\d{4})[/\-\.](?:\d{1,2}[/\-\.]\d{1,2})',  # YYYY-MM-DD
    r'(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.])(\d{2})\b',  # MM/DD/YY
]

# Trimestres avec annee - contexte calendaire pur
QUARTER_PATTERNS = [
    r'[Qq][1-4][,\s]*(\d{4})',  # Q4,2023
    r'(\d{4})[,\s]*[Qq][1-4]',  # 2023 Q4
    r'[Qq][1-4]\s+(\d{4})',  # Q4 2023
]

# Copyright et mentions legales
COPYRIGHT_PATTERNS = [
    r'(?:©|\(c\)|[Cc]opyright)[,\s]*(\d{4})',  # © 2023
    r'(?:©|\(c\)|[Cc]opyright)[,\s]*(\d{4})\s*[-–—]\s*(\d{4})',  # © 2019-2023
    r'[Aa]ll\s+[Rr]ights\s+[Rr]eserved.*?(\d{4})',  # All rights reserved 2023
]

# Mois + annee - contexte calendaire
MONTH_YEAR_PATTERNS = [
    r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|'
    r'July?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    r'[,\s]+(\d{4})',  # January 2023
    r'(\d{4})[,\s]+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|'
    r'July?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)',  # 2023 January
    # Mois abreges avec point
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.\s*(\d{4})',  # Jan. 2023
]

# Fiscal years
FISCAL_YEAR_PATTERNS = [
    r'FY[,\s]*(\d{4})',  # FY2023
    r'FY[,\s]*(\d{2})\b',  # FY23
    r'[Ff]iscal\s+[Yy]ear\s+(\d{4})',  # Fiscal Year 2023
]

# References temporelles
TEMPORAL_REFERENCE_PATTERNS = [
    r'(?:[Ss]ince|[Aa]s\s+of|[Uu]ntil|[Bb]y)[,\s]*(\d{4})',  # since 2019
    r'(?:[Ii]n|[Dd]uring)\s+(\d{4})',  # in 2023
    r'(\d{4})\s*[-–—]\s*(\d{4})',  # 2019-2023 (plage)
    r'(\d{4})\s*[-–—]\s*(?:present|now|today)',  # 2019-present
]

# Unites de mesure - si un nombre est suivi d'une unite, c'est une mesure
UNIT_PATTERNS = [
    r'(\d+)\s*(?:mm|cm|m|km|in|ft|yd|mi)\b',  # Longueur
    r'(\d+)\s*(?:g|kg|lb|oz|ton)\b',  # Masse
    r'(\d+)\s*(?:ml|l|L|gal|pt|qt)\b',  # Volume
    r'(\d+)\s*(?:kW|MW|GW|hp|HP)\b',  # Puissance
    r'(\d+)\s*(?:kWh|MWh|GWh|Wh)\b',  # Energie
    r'(\d+)\s*(?:Hz|kHz|MHz|GHz)\b',  # Frequence
    r'(\d+)\s*(?:KB|MB|GB|TB|PB)\b',  # Donnees
    r'(\d+)\s*(?:bps|kbps|Mbps|Gbps)\b',  # Debit
    r'(\d+)\s*[%€$£¥]\b',  # Pourcentage/Monnaie
    r'[€$£¥]\s*(\d+)',  # Monnaie prefixe
]

# Exemples et illustrations - contexte didactique
EXAMPLE_CONTEXT_PATTERNS = [
    r'(?:[Ee]\.g\.|[Ff]or\s+example|[Ff]or\s+instance|[Ss]uch\s+as)[,:\s]+[^.]*?(\d{4})',
    r'(?:[Ee]xample|[Ss]ample|[Dd]emo|[Tt]est)[:\s]+[^.]*?(\d+)',
    r'(?:\([Ee]xample\)|\([Ss]ample\))[^.]*?(\d+)',
]

# SAP Notes, tickets, IDs - ces numeros sont des REFERENCES, pas des versions
REFERENCE_ID_PATTERNS = [
    r'(?:[Nn]ote|[Tt]icket|[Cc]ase|ID|#)\s*:?\s*(\d{5,})',  # Note 123456
    r'(?:KBA|SAP\s+[Nn]ote)\s*:?\s*(\d+)',  # KBA/SAP Note
    r'[A-Z]{2,4}-(\d{4,})',  # JIRA-1234, SNOW-12345
]

# Numeros de pages, slides, figures
PAGE_REFERENCE_PATTERNS = [
    r'(?:[Pp]age|[Pp]\.|[Ss]lide|[Ff]ig(?:ure)?\.?)\s*(\d+)',  # Page 23
    r'(\d+)\s+of\s+\d+',  # 23 of 100
]


# =============================================================================
# STRUCTURE NUMBERING DETECTION - Patterns (Plan v2.1 - ChatGPT validated)
# Detection agnostique de numerotation structurelle sans listes de mots
# =============================================================================

# Patterns indiquant une position de titre/section (debut de ligne + ponctuation)
# Utilise pour Signal S2 du StructureNumberingGate
SECTION_POSITION_PATTERNS = [
    r'^([A-Z][a-zA-Z]*)\s+(\d{1,2})\s*[:\.\-–—]',  # "PUBLIC 3:" ou "PUBLIC 3."
    r'^([A-Z][a-zA-Z]*)\s+(\d{1,2})\s*$',          # "PUBLIC 3" seul sur ligne
]


# === PHASE 2: PATTERNS STRUCTURELS AGNOSTIQUES ===
# Formes universelles qui indiquent une version/variante dans N'IMPORTE quel domaine

# Semantic Versioning (SemVer) - universel
SEMVER_PATTERNS = [
    r'\bv?(\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?(?:\+[a-zA-Z0-9.]+)?)\b',  # v1.2.3-beta+build
    r'\bv?(\d+\.\d+)\b',  # v1.2
    r'\b[Vv](\d+)\b',  # V3, v5
]

# Forme "Entity + Numeral" - Pattern universel
# Ex: "ModelX 2023", "iPhone 15", "Windows 11", "S/4HANA 2023"
ENTITY_NUMERAL_PATTERNS = [
    r'\b([A-Z][a-zA-Z0-9/]*)\s+(\d{4})\b',  # ProductName 2023
    r'\b([A-Z][a-zA-Z0-9/]*)\s+(\d{1,2})\b',  # iPhone 15
    r'\b([A-Z][a-zA-Z0-9/]*)\s+[Vv]?(\d+(?:\.\d+)?)\b',  # Windows v10, MacOS 14.0
]

# Formes de release universelles
RELEASE_FORM_PATTERNS = [
    r'\b[Rr]elease\s+(\d+(?:\.\d+)?)\b',  # Release 3.0
    r'\b[Ee]dition\s+(\d+)\b',  # Edition 2
    r'\b[Gg]eneration\s+(\d+)\b',  # Generation 5
    r'\b[Mm]odel\s+(\d+)\b',  # Model 3
    r'\b[Ss]eries\s+(\d+)\b',  # Series 9
    r'\b[Mm]ark\s+([IVXLCDM]+|\d+)\b',  # Mark III, Mark 3
    r'\b[Pp]hase\s+(\d+)\b',  # Phase 2
    r'\b[Ii]teration\s+(\d+)\b',  # Iteration 4
]

# Codes alphanumeriques structurels (sans hardcoding de domaine)
STRUCTURED_CODE_PATTERNS = [
    r'\b([A-Z]{1,3}\d{2,4})\b',  # L23, AB12, XY2023 (mais pas de PCE, FPS etc.)
]

# Blacklist minimale - uniquement les faux positifs evidents
# Aucun terme metier specifique ici!
MARKER_BLACKLIST = {
    # Versions trop generiques
    "v1", "v2", "1.0", "2.0", "0.0",
    # Codes trop courts
    "v", "r", "m",
}


# === SCOPE LANGUAGE (multilingue) ===
# Ces patterns detectent le LANGAGE de scope, pas les marqueurs eux-memes

SCOPE_LANGUAGE_TRIGGERS = {
    # Anglais
    "en": [
        r'\b(?:applies?\s+to|valid\s+for|available\s+(?:in|for|from))\b',
        r'\b(?:version|release|edition|as\s+of|from|since)\b',
        r'\b(?:all\s+versions?|any\s+version|every\s+release)\b',
        r'\b(?:starting\s+(?:with|from)|beginning\s+(?:with|in))\b',
        r'\b(?:new\s+in|introduced\s+in|added\s+in)\b',
        r'\b(?:removed\s+in|deprecated\s+(?:in|from)|obsolete)\b',
        r'\b(?:only\s+(?:in|for)|exclusively\s+(?:in|for))\b',
    ],
    # Francais
    "fr": [
        r'\b(?:applicable\s+[àa]|valide\s+pour|disponible\s+(?:dans|pour|depuis))\b',
        r'\b(?:version|release|[ée]dition|[àa]\s+partir\s+de|depuis)\b',
        r'\b(?:toutes?\s+(?:les\s+)?versions?|chaque\s+version)\b',
        r'\b(?:nouveau\s+dans|introduit\s+dans|ajout[ée]\s+dans)\b',
        r'\b(?:supprim[ée]\s+dans|obsol[èe]te)\b',
        r'\b(?:uniquement\s+(?:dans|pour)|exclusivement)\b',
    ],
    # Allemand
    "de": [
        r'\b(?:gilt\s+f[üu]r|verf[üu]gbar\s+(?:in|f[üu]r|ab))\b',
        r'\b(?:Version|Release|Ausgabe|ab|seit)\b',
        r'\b(?:alle\s+Versionen|jede\s+Version)\b',
        r'\b(?:neu\s+in|eingef[üu]hrt\s+in)\b',
        r'\b(?:entfernt\s+in|veraltet)\b',
    ],
}

# Patterns de conflit/comparaison (indicateurs de MIXED)
CONFLICT_PATTERNS = [
    r'\bvs\.?\b',
    r'\bversus\b',
    r'\bunlike\b',
    r'\bin\s+contrast\s+(?:to|with)\b',
    r'\bcompared\s+(?:to|with)\b',
    r'\bdiffers?\s+from\b',
    r'\bwhereas\b',
    r'\bwhile\s+.*\s+(?:has|does|is)\b',
    r'\bbut\s+in\s+\w+\s+version\b',
    r'\bcontrairement\s+[àa]\b',  # FR
    r'\bim\s+Gegensatz\s+zu\b',  # DE
]


# =============================================================================
# PHASE 1: CANDIDATE GATE - Filtrage Universel
# =============================================================================

@dataclass
class GateResult:
    """
    Resultat du filtrage par CandidateGate.

    Attributes:
        passed: True si le candidat a passe le filtrage
        rejected_by: Nom du filtre qui a rejete (None si passed=True)
        rejection_context: Contexte qui a declenche le rejet
    """
    passed: bool
    rejected_by: Optional[str] = None
    rejection_context: str = ""


class CandidateGate:
    """
    Filtre universel pour eliminer les faux positifs AVANT scoring.

    Principe: Safe-by-default - en cas de doute, rejeter le candidat.
    Un faux negatif (marker non detecte) est acceptable.
    Un faux positif (bruit traite comme marker) est TOXIQUE.

    Filtres appliques dans l'ordre:
    1. DATE_FORMAT - dates explicites (MM/DD/YYYY, etc.)
    2. QUARTER - trimestres calendaires (Q4 2023)
    3. COPYRIGHT - mentions legales (© 2023)
    4. MONTH_YEAR - mois + annee (January 2023)
    5. FISCAL_YEAR - annees fiscales (FY2023)
    6. TEMPORAL_REF - references temporelles (since 2019)
    7. UNIT - mesures avec unites (100 kg)
    8. EXAMPLE - contexte didactique (e.g., example)
    9. REFERENCE_ID - tickets/notes/IDs (Note 123456)
    10. PAGE_REF - numeros de pages/slides (Page 23)

    Usage:
        >>> gate = CandidateGate()
        >>> result = gate.check(candidate_value="2023", evidence="Q4,2023 results")
        >>> result.passed  # False
        >>> result.rejected_by  # "QUARTER"
    """

    def __init__(self):
        """Compile tous les patterns de filtrage."""
        self._filters: List[Tuple[str, List[re.Pattern]]] = [
            ("DATE_FORMAT", [re.compile(p, re.IGNORECASE) for p in DATE_FORMAT_PATTERNS]),
            ("QUARTER", [re.compile(p, re.IGNORECASE) for p in QUARTER_PATTERNS]),
            ("COPYRIGHT", [re.compile(p, re.IGNORECASE) for p in COPYRIGHT_PATTERNS]),
            ("MONTH_YEAR", [re.compile(p, re.IGNORECASE) for p in MONTH_YEAR_PATTERNS]),
            ("FISCAL_YEAR", [re.compile(p, re.IGNORECASE) for p in FISCAL_YEAR_PATTERNS]),
            ("TEMPORAL_REF", [re.compile(p, re.IGNORECASE) for p in TEMPORAL_REFERENCE_PATTERNS]),
            ("UNIT", [re.compile(p, re.IGNORECASE) for p in UNIT_PATTERNS]),
            ("EXAMPLE", [re.compile(p, re.IGNORECASE) for p in EXAMPLE_CONTEXT_PATTERNS]),
            ("REFERENCE_ID", [re.compile(p, re.IGNORECASE) for p in REFERENCE_ID_PATTERNS]),
            ("PAGE_REF", [re.compile(p, re.IGNORECASE) for p in PAGE_REFERENCE_PATTERNS]),
        ]

    def check(self, candidate_value: str, evidence: str) -> GateResult:
        """
        Verifie si un candidat passe le filtrage universel.

        Args:
            candidate_value: Valeur du marqueur candidat (ex: "2023")
            evidence: Contexte textuel autour du candidat (ex: "Q4,2023 results")

        Returns:
            GateResult indiquant si le candidat passe ou est rejete
        """
        if not candidate_value or not evidence:
            return GateResult(passed=True)

        # === FILTRAGE DIRECT SUR LA VALEUR DU CANDIDAT ===
        # Certains patterns peuvent etre detectes directement sur la valeur

        # Pattern trimestre: Q1-Q4 + nombre (ex: "Q4 2023")
        if re.match(r'^[Qq][1-4]\s+\d{4}$', candidate_value):
            return GateResult(
                passed=False,
                rejected_by="QUARTER_VALUE",
                rejection_context=candidate_value,
            )

        # Pattern document ID: XXX-NNN ou XXX NNN (ex: "SAP 008", "SAP-008")
        if re.match(r'^[A-Z]{2,4}[\s\-]\d{2,4}$', candidate_value):
            return GateResult(
                passed=False,
                rejected_by="DOCUMENT_ID",
                rejection_context=candidate_value,
            )

        # === FILTRAGE VIA EVIDENCE (contexte) ===
        # Verifier chaque filtre dans l'ordre
        for filter_name, patterns in self._filters:
            for pattern in patterns:
                match = pattern.search(evidence)
                if match:
                    matched_full = match.group(0)
                    matched_groups = match.groups()

                    # Methode 1: La valeur est dans un groupe capture
                    for group in matched_groups:
                        if group and candidate_value in group:
                            logger.debug(
                                f"[CandidateGate] REJECTED '{candidate_value}' by {filter_name}: "
                                f"'{matched_full}'"
                            )
                            return GateResult(
                                passed=False,
                                rejected_by=filter_name,
                                rejection_context=matched_full[:50],
                            )

                    # Methode 2: Le match complet contient la valeur
                    # (pour cas comme "Q4 2023" ou le match est "Q4 2023" mais groupe est "2023")
                    if candidate_value in matched_full or matched_full in candidate_value:
                        logger.debug(
                            f"[CandidateGate] REJECTED '{candidate_value}' by {filter_name} (overlap): "
                            f"'{matched_full}'"
                        )
                        return GateResult(
                            passed=False,
                            rejected_by=filter_name,
                            rejection_context=matched_full[:50],
                        )

        # Tous les filtres passes
        return GateResult(passed=True)

    def filter_candidates(
        self,
        candidates: List["MarkerCandidate"],
    ) -> Tuple[List["MarkerCandidate"], List["MarkerCandidate"]]:
        """
        Filtre une liste de candidats.

        Args:
            candidates: Liste de MarkerCandidate a filtrer

        Returns:
            Tuple (survivors, rejected) - candidats qui passent et rejetes
        """
        survivors = []
        rejected = []

        for candidate in candidates:
            result = self.check(candidate.value, candidate.evidence)
            if result.passed:
                survivors.append(candidate)
            else:
                # Marquer le candidat comme rejete (pour debug)
                candidate._gate_rejected = True
                candidate._gate_rejected_by = result.rejected_by
                rejected.append(candidate)

        logger.info(
            f"[CandidateGate] Filtered {len(candidates)} candidates: "
            f"{len(survivors)} passed, {len(rejected)} rejected"
        )

        return survivors, rejected


# Singleton pour reutilisation
_candidate_gate: Optional[CandidateGate] = None


def get_candidate_gate() -> CandidateGate:
    """Retourne l'instance singleton du CandidateGate."""
    global _candidate_gate
    if _candidate_gate is None:
        _candidate_gate = CandidateGate()
    return _candidate_gate


# =============================================================================
# STRUCTURE NUMBERING GATE - Plan v2.1 (ChatGPT validated 2026-01-07)
# Detection agnostique basee sur signaux S1/S2/S3
# =============================================================================

@dataclass
class StructureGateConfig:
    """
    Configuration du StructureNumberingGate.

    Parametres valides par ChatGPT - Plan v2.1.
    """
    # Seuil de sequence pour HARD_REJECT (default: 3 consecutifs)
    sequence_threshold: int = 3

    # Action pour SOFT_FLAG: "llm" (passe au LLM) ou "weak_marker" (conserve comme weak)
    soft_flag_action: str = "llm"

    # Max weak markers en fallback si document devient silencieux
    fallback_max_markers: int = 3

    # Activer/desactiver le gate
    enabled: bool = True

    # Logging des changements de config
    log_config_changes: bool = True


@dataclass
class SequenceDetectionResult:
    """
    Resultat de detection de sequence pour un prefixe.

    Ex: Si on trouve "PUBLIC 1", "PUBLIC 2", "PUBLIC 3" dans le document,
    c'est une sequence de numerotation structurelle (3 consecutifs).
    """
    prefix: str
    numbers_found: List[int]
    max_consecutive: int  # Longueur de la plus longue sequence consecutive
    is_sequence: bool     # True si max_consecutive >= 2
    evidence: str = ""


class StructureNumberingGate:
    """
    Detection agnostique de numerotation structurelle.

    Implemente les pistes A + B + C validees par ChatGPT (Plan v2.1):
    - S1: Sequentialite (X 1/2/3... meme prefixe)
    - S2: Position structurelle (debut ligne + ponctuation)
    - S3: Prefixe quasi-toujours numerote

    Decisions:
    - HARD_REJECT: Seq >= 3 ET (S2 ou S3)
    - SOFT_FLAG: Seq = 2 OU signal isole
    - LOW: Aucun signal

    100% agnostique - fonctionne pour PUBLIC, Chapter, Module, Resources...
    sans les connaitre a l'avance.
    """

    def __init__(self, config: Optional[StructureGateConfig] = None):
        """Initialise le gate avec configuration."""
        self.config = config or StructureGateConfig()
        self._section_patterns = [
            re.compile(p, re.MULTILINE) for p in SECTION_POSITION_PATTERNS
        ]

    def detect_sequences(
        self,
        candidates: List["MarkerCandidate"],
    ) -> Dict[str, SequenceDetectionResult]:
        """
        Detecte les sequences de numerotation pour chaque prefixe (Signal S1).

        Contrainte: Meme prefixe X avec numeros consecutifs uniquement.
        Ex: "PUBLIC 1", "PUBLIC 2", "PUBLIC 3" -> sequence de 3

        Args:
            candidates: Liste de candidats entity_numeral

        Returns:
            Dict[prefix] -> SequenceDetectionResult
        """
        # Grouper les numeros par prefixe (entity_numeral seulement)
        prefix_numbers: Dict[str, List[int]] = {}

        for c in candidates:
            if c.lexical_shape != "entity_numeral":
                continue

            # Extraire prefixe et numero du format "PREFIX NUM"
            parts = c.value.rsplit(" ", 1)
            if len(parts) != 2:
                continue

            prefix, num_str = parts
            try:
                num = int(num_str)
                # Ne traiter que les numeros 1-2 digits (1-99)
                if 1 <= num <= 99:
                    if prefix not in prefix_numbers:
                        prefix_numbers[prefix] = []
                    prefix_numbers[prefix].append(num)
            except ValueError:
                continue

        # Calculer sequences pour chaque prefixe
        results = {}
        for prefix, numbers in prefix_numbers.items():
            numbers_sorted = sorted(set(numbers))

            # Calculer la plus longue sequence consecutive
            max_consec = 1
            current_consec = 1

            for i in range(1, len(numbers_sorted)):
                if numbers_sorted[i] == numbers_sorted[i - 1] + 1:
                    current_consec += 1
                    max_consec = max(max_consec, current_consec)
                else:
                    current_consec = 1

            results[prefix] = SequenceDetectionResult(
                prefix=prefix,
                numbers_found=numbers_sorted,
                max_consecutive=max_consec if len(numbers_sorted) > 1 else 1,
                is_sequence=max_consec >= 2,
                evidence=f"Found {prefix} with numbers: {numbers_sorted}",
            )

        return results

    def check_position_indicator(
        self,
        candidate_value: str,
        full_text: str,
    ) -> bool:
        """
        Verifie si le candidat apparait en position de titre/section (Signal S2).

        Args:
            candidate_value: Valeur du candidat (ex: "PUBLIC 3")
            full_text: Texte complet du document

        Returns:
            True si le candidat apparait en position structurelle
        """
        lines = full_text.split('\n')

        for line in lines:
            line_stripped = line.strip()
            if candidate_value not in line_stripped:
                continue

            # Seul sur la ligne = indicateur fort
            if line_stripped == candidate_value:
                return True

            # Quasi-seul (+ quelques caracteres)
            if line_stripped.startswith(candidate_value) and len(line_stripped) < len(candidate_value) + 5:
                return True

            # Debut de ligne + ponctuation
            for pattern in self._section_patterns:
                if pattern.match(line_stripped):
                    return True

        return False

    def check_prefix_mostly_numbered(
        self,
        prefix: str,
        full_text: str,
    ) -> bool:
        """
        Verifie si le prefixe apparait quasi-toujours avec des numeros (Signal S3).

        Definition robuste (ChatGPT):
        - count(X + number) >= 3 ET
        - count(X standalone) <= 1 ET
        - distinct_numbers >= 2

        Args:
            prefix: Le prefixe a verifier (ex: "PUBLIC")
            full_text: Texte complet du document

        Returns:
            True si le prefixe est principalement utilise avec des numeros
        """
        # Pattern pour "PREFIX N" (1-2 digits)
        pattern_numbered = re.compile(
            rf'\b{re.escape(prefix)}\s+\d{{1,2}}\b',
            re.IGNORECASE
        )
        matches_numbered = pattern_numbered.findall(full_text)
        count_numbered = len(matches_numbered)

        # Pattern pour PREFIX standalone (pas suivi d'un numero)
        pattern_standalone = re.compile(
            rf'\b{re.escape(prefix)}\b(?!\s+\d)',
            re.IGNORECASE
        )
        count_standalone = len(pattern_standalone.findall(full_text))

        # Distinct numbers
        distinct_numbers = len(set(
            int(m.split()[-1]) for m in matches_numbered
            if m.split()[-1].isdigit()
        )) if matches_numbered else 0

        return (
            count_numbered >= 3 and
            count_standalone <= 1 and
            distinct_numbers >= 2
        )

    def compute_structure_risk(
        self,
        candidate: "MarkerCandidate",
        sequences: Dict[str, SequenceDetectionResult],
        full_text: str,
    ) -> Tuple[str, str]:
        """
        Calcule le niveau de risque structurel pour un candidat.

        Matrice de decision (Plan v2.1):
        - HARD_REJECT: Seq >= 3 ET (S2 ou S3)
        - SOFT_FLAG: Seq = 2 OU signal isole avec S2+S3
        - LOW: Aucun signal significatif

        Args:
            candidate: Le candidat a evaluer
            sequences: Resultats de detection de sequences
            full_text: Texte complet du document

        Returns:
            Tuple (decision, reason)
            decision: "HARD_REJECT", "SOFT_FLAG", ou "LOW"
            reason: Explication pour debug/LLM
        """
        if candidate.lexical_shape != "entity_numeral":
            return ("LOW", "Not entity_numeral pattern")

        # Extraire prefixe
        parts = candidate.value.rsplit(" ", 1)
        if len(parts) != 2:
            return ("LOW", "Cannot parse prefix")

        prefix, num_str = parts

        # Verifier si c'est un numero 1-2 digits
        try:
            num = int(num_str)
            if num >= 100:  # 3+ digits = probablement annee/version, pas section
                return ("LOW", "Number >= 100, likely version not section")
        except ValueError:
            return ("LOW", "Not a valid number")

        # === Evaluer les 3 signaux ===
        # S1: Sequentialite
        seq_result = sequences.get(prefix)
        seq_count = seq_result.max_consecutive if seq_result else 0

        # S2: Position structurelle
        s2_position = self.check_position_indicator(candidate.value, full_text)

        # S3: Prefixe quasi-toujours numerote
        s3_prefix = self.check_prefix_mostly_numbered(prefix, full_text)

        # === Appliquer la matrice de decision ===

        # HARD_REJECT: Seq >= threshold ET (S2 ou S3)
        if seq_count >= self.config.sequence_threshold:
            if s2_position or s3_prefix:
                reason = (
                    f"HARD: sequence={seq_count} (>={self.config.sequence_threshold}), "
                    f"S2_position={s2_position}, S3_prefix={s3_prefix}"
                )
                return ("HARD_REJECT", reason)

        # SOFT_FLAG: Seq = 2 OU (signal isole avec contexte)
        if seq_count == 2:
            reason = f"SOFT: sequence=2, S2_position={s2_position}, S3_prefix={s3_prefix}"
            return ("SOFT_FLAG", reason)

        if seq_count == 1 and s2_position and s3_prefix:
            reason = f"SOFT: sequence=1 but S2+S3 both true"
            return ("SOFT_FLAG", reason)

        # LOW: Aucun signal fort
        return ("LOW", f"No strong signals: seq={seq_count}, S2={s2_position}, S3={s3_prefix}")

    def filter_candidates(
        self,
        candidates: List["MarkerCandidate"],
        full_text: str,
        doc_id: str = "",
    ) -> Tuple[List["MarkerCandidate"], List["MarkerCandidate"], List["MarkerCandidate"]]:
        """
        Filtre les candidats selon les signaux structurels.

        Args:
            candidates: Liste de candidats a filtrer
            full_text: Texte complet du document
            doc_id: ID du document (pour logging)

        Returns:
            Tuple (survivors, soft_flagged, hard_rejected)
        """
        if not self.config.enabled:
            return (candidates, [], [])

        # Detecter les sequences
        sequences = self.detect_sequences(candidates)

        survivors = []
        soft_flagged = []
        hard_rejected = []

        for candidate in candidates:
            decision, reason = self.compute_structure_risk(candidate, sequences, full_text)

            # Stocker le resultat dans le candidat
            candidate.structure_risk = decision
            candidate.structure_risk_reason = reason

            if decision == "HARD_REJECT":
                hard_rejected.append(candidate)
                logger.debug(
                    f"[StructureNumberingGate] HARD_REJECT '{candidate.value}': {reason}"
                )
            elif decision == "SOFT_FLAG":
                soft_flagged.append(candidate)
                logger.debug(
                    f"[StructureNumberingGate] SOFT_FLAG '{candidate.value}': {reason}"
                )
            else:
                survivors.append(candidate)

        # Log summary
        if hard_rejected or soft_flagged:
            logger.info(
                f"[StructureNumberingGate] Doc '{doc_id}': "
                f"{len(survivors)} pass, {len(soft_flagged)} soft, {len(hard_rejected)} hard_reject"
            )

        return (survivors, soft_flagged, hard_rejected)

    def apply_fallback_if_silent(
        self,
        final_markers: List["MarkerCandidate"],
        rejected: List["MarkerCandidate"],
        doc_id: str,
    ) -> List["MarkerCandidate"]:
        """
        Si tous les markers sont rejetes, conserver K weak markers en fallback.

        Evite les documents "silencieux" par erreur.

        Args:
            final_markers: Markers survivants
            rejected: Markers rejetes (HARD + SOFT non recuperes)
            doc_id: ID du document

        Returns:
            Liste finale avec eventuels fallback markers
        """
        if len(final_markers) > 0 or len(rejected) == 0:
            return final_markers

        # Document silencieux - appliquer fallback
        logger.warning(
            f"[StructureNumberingGate] Doc '{doc_id}' silencieux! "
            f"Rejected: {[c.value for c in rejected]}"
        )

        # Selectionner top K par frequence + dispersion
        fallback = sorted(
            rejected,
            key=lambda c: (c.occurrences, c.pages_covered),
            reverse=True
        )[:self.config.fallback_max_markers]

        # Taguer comme fallback
        for m in fallback:
            m.structure_fallback = True
            m.structure_risk = "FALLBACK"

        logger.info(
            f"[StructureNumberingGate] Fallback markers: {[m.value for m in fallback]}"
        )

        return fallback


# Singleton
_structure_numbering_gate: Optional[StructureNumberingGate] = None


def get_structure_numbering_gate(
    config: Optional[StructureGateConfig] = None
) -> StructureNumberingGate:
    """Retourne l'instance singleton du StructureNumberingGate."""
    global _structure_numbering_gate
    if _structure_numbering_gate is None or config is not None:
        _structure_numbering_gate = StructureNumberingGate(config)
    return _structure_numbering_gate


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class EvidenceSample:
    """
    Un echantillon d'evidence avec contexte de zone.

    Spec: ADR_DOCUMENT_STRUCTURAL_AWARENESS.md - Section 4.3
    """
    page: int
    zone: str  # 'top', 'main', 'bottom'
    text: str  # 20-120 chars

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page": self.page,
            "zone": self.zone,
            "text": self.text[:120] if self.text else "",
        }


@dataclass
class MarkerCandidate:
    """
    Un candidat de marqueur extrait par mining deterministe.

    Version enrichie (PR6) avec features structurelles pour validation LLM.

    Attributes:
        value: Valeur du marqueur
        source: Source d'extraction (filename, cover, header, body, revision)
        position: Position dans le document (0=debut, 1=milieu, 2=fin)
        evidence: Contexte textuel autour du marqueur (legacy)
        lexical_shape: Forme lexicale (numeric_4, alphanumeric, semantic_token)
                       JAMAIS utilise pour inferer le sens (ADR regle 3)
        occurrences: Nombre d'occurrences dans le document

    Attributes structurels (PR6):
        zone_distribution: Distribution par zone {'top': N, 'main': N, 'bottom': N}
        dominant_zone: Zone dominante ('top', 'main', 'bottom')
        positional_stability: Score 0-1 de stabilite positionnelle
        template_likelihood: Score 0-1 de probabilite template
        is_in_template_fragment: True si dans un fragment template detecte
        evidence_samples: Liste d'echantillons avec zone/page
        pages_covered: Nombre de pages couvertes
        pages_covered_ratio: Ratio de pages couvertes
    """
    # === Identite ===
    value: str
    source: str  # filename, cover, header, body, revision
    position: int = 0  # 0=cover, 1=early, 2=body
    evidence: str = ""  # Legacy - contexte brut
    lexical_shape: str = ""  # numeric_4, alphanumeric, semantic_token (ex pattern_type)
    occurrences: int = 1

    # === Structure Numbering Gate (Plan v2.1) ===
    is_weak_candidate: bool = False      # True si entity_numeral \d{1,2}
    structure_risk: str = "LOW"          # "HARD_REJECT", "SOFT_FLAG", "LOW", "FALLBACK"
    structure_risk_reason: str = ""      # Raison du risque (pour debug/LLM)
    structure_fallback: bool = False     # True si conserve en fallback doc silencieux

    # === Distribution (PR6) ===
    pages_covered: int = 0
    pages_covered_ratio: float = 0.0

    # === Zones (PR6) ===
    zone_distribution: Dict[str, int] = field(default_factory=lambda: {"top": 0, "main": 0, "bottom": 0})
    dominant_zone: str = "main"
    positional_stability: float = 0.0

    # === Template detection (PR6) ===
    template_likelihood: float = 0.0
    is_in_template_fragment: bool = False

    # === Evidence enrichie (PR6) ===
    evidence_samples: List[EvidenceSample] = field(default_factory=list)

    # === Linguistic cues (set by enrichment) ===
    _contextual_cues: Optional[Any] = field(default=None, repr=False)

    # === Structural confidence (set by enrichment) ===
    _structural_confidence: Optional[str] = field(default=None, repr=False)

    @property
    def pattern_type(self) -> str:
        """Alias legacy pour lexical_shape."""
        return self.lexical_shape

    @pattern_type.setter
    def pattern_type(self, value: str):
        self.lexical_shape = value

    def to_dict(self) -> Dict[str, Any]:
        """Serialise en dictionnaire (version legacy)."""
        return {
            "value": self.value,
            "source": self.source,
            "position": self.position,
            "evidence": self.evidence[:100] if self.evidence else "",
            "pattern_type": self.lexical_shape,  # Legacy name
            "occurrences": self.occurrences,
        }

    def to_dict_enriched(self) -> Dict[str, Any]:
        """Serialise en dictionnaire avec features structurelles (PR6) et risque structurel (Plan v2.1)."""
        result = {
            "value": self.value,
            "lexical_shape": self.lexical_shape,
            "occurrences": self.occurrences,
            "pages_covered": self.pages_covered,
            "pages_covered_ratio": round(self.pages_covered_ratio, 2),
            "zone_distribution": self.zone_distribution,
            "dominant_zone": self.dominant_zone,
            "positional_stability": round(self.positional_stability, 2),
            "template_likelihood": round(self.template_likelihood, 2),
            "is_in_template_fragment": self.is_in_template_fragment,
            "evidence_samples": [s.to_dict() for s in self.evidence_samples[:5]],
        }
        if self._contextual_cues:
            result["contextual_cues"] = self._contextual_cues.to_dict()
        if self._structural_confidence:
            result["structural_confidence"] = self._structural_confidence

        # Plan v2.1: Inclure risque structurel pour arbitrage LLM
        if self.structure_risk and self.structure_risk != "LOW":
            result["structure_risk"] = self.structure_risk
            result["structure_risk_reason"] = self.structure_risk_reason
        if self.is_weak_candidate:
            result["is_weak_candidate"] = True
        if self.structure_fallback:
            result["structure_fallback"] = True

        return result


@dataclass
class MiningResult:
    """
    Resultat du mining de candidats.

    Attributes:
        candidates: Liste des candidats extraits
        scope_language_hits: Nombre de hits de scope language
        conflict_hits: Nombre de hits de patterns de conflit
        source_coverage: Sources couvertes (filename, cover, etc.)
        _rejected_candidates: Candidats rejetés par CandidateGate (debug)
        _soft_flag_candidates: Candidats SOFT_FLAG par StructureNumberingGate (pour LLM)
    """
    candidates: List[MarkerCandidate] = field(default_factory=list)
    scope_language_hits: int = 0
    conflict_hits: int = 0
    source_coverage: Set[str] = field(default_factory=set)

    # === Debug/Analysis fields (Plan v2.1) ===
    _rejected_candidates: List[MarkerCandidate] = field(default_factory=list)
    _soft_flag_candidates: List[MarkerCandidate] = field(default_factory=list)

    def get_unique_values(self) -> Set[str]:
        """Retourne les valeurs uniques des candidats."""
        return {c.value for c in self.candidates}

    def get_by_source(self, source: str) -> List[MarkerCandidate]:
        """Retourne les candidats par source."""
        return [c for c in self.candidates if c.source == source]

    def merge_duplicates(self) -> "MiningResult":
        """
        Fusionne les doublons en incrementant occurrences.

        Garde la source la plus fiable (filename > cover > header > body).
        """
        source_priority = {"filename": 0, "cover": 1, "header": 2, "revision": 3, "body": 4}
        merged: Dict[str, MarkerCandidate] = {}

        for c in self.candidates:
            if c.value in merged:
                existing = merged[c.value]
                existing.occurrences += c.occurrences
                # Garder la source la plus fiable
                if source_priority.get(c.source, 99) < source_priority.get(existing.source, 99):
                    existing.source = c.source
                    existing.evidence = c.evidence
                    existing.position = c.position
            else:
                merged[c.value] = MarkerCandidate(
                    value=c.value,
                    source=c.source,
                    position=c.position,
                    evidence=c.evidence,
                    lexical_shape=c.lexical_shape,
                    occurrences=c.occurrences,
                )

        return MiningResult(
            candidates=list(merged.values()),
            scope_language_hits=self.scope_language_hits,
            conflict_hits=self.conflict_hits,
            source_coverage=self.source_coverage,
        )


class CandidateMiner:
    """
    Extracteur deterministe de marqueurs candidats avec architecture AGNOSTIQUE.

    Pipeline en 2 etapes:
    1. Extraction via patterns structurels universels (SemVer, Entity+Numeral, etc.)
    2. Filtrage via CandidateGate pour eliminer les faux positifs

    Les patterns sont independants du domaine (fonctionne pour SAP, auto, pharma, etc.)

    Usage:
        >>> miner = CandidateMiner()
        >>> result = miner.mine_document(filename, pages_text, metadata)
    """

    def __init__(
        self,
        languages: List[str] = None,
        custom_patterns: List[str] = None,
        blacklist_additions: Set[str] = None,
        use_gate: bool = True,
        structure_gate_config: Optional[StructureGateConfig] = None,
    ):
        """
        Initialise le miner.

        Args:
            languages: Langues pour scope language detection (default: ["en", "fr", "de"])
            custom_patterns: Patterns additionnels a utiliser
            blacklist_additions: Marqueurs additionnels a ignorer
            use_gate: Utiliser le CandidateGate pour filtrer (default: True)
            structure_gate_config: Config pour StructureNumberingGate (Plan v2.1)
        """
        self.languages = languages or ["en", "fr", "de"]
        self.custom_patterns = custom_patterns or []
        self.blacklist = MARKER_BLACKLIST.copy()
        if blacklist_additions:
            self.blacklist.update(blacklist_additions)
        self.use_gate = use_gate
        self.structure_gate_config = structure_gate_config

        # === PHASE 2: PATTERNS STRUCTURELS AGNOSTIQUES ===
        # Ces patterns detectent des formes universelles, pas des termes metier

        # SemVer: v1.2.3, 1.2, v3
        self._semver_patterns = [re.compile(p, re.IGNORECASE) for p in SEMVER_PATTERNS]

        # Entity + Numeral: "ProductName 2023", "iPhone 15"
        self._entity_numeral_patterns = [re.compile(p) for p in ENTITY_NUMERAL_PATTERNS]

        # Release forms: Release 3, Edition 2, Generation 5
        self._release_form_patterns = [re.compile(p, re.IGNORECASE) for p in RELEASE_FORM_PATTERNS]

        # Codes alphanumeriques: L23, AB12
        self._structured_code_patterns = [re.compile(p) for p in STRUCTURED_CODE_PATTERNS]

        # Patterns de conflit (indicateurs de MIXED)
        self._conflict_patterns = [re.compile(p, re.IGNORECASE) for p in CONFLICT_PATTERNS]

        # Scope language patterns par langue
        self._scope_patterns: Dict[str, List[re.Pattern]] = {}
        for lang in self.languages:
            if lang in SCOPE_LANGUAGE_TRIGGERS:
                self._scope_patterns[lang] = [
                    re.compile(p, re.IGNORECASE)
                    for p in SCOPE_LANGUAGE_TRIGGERS[lang]
                ]

        # CandidateGate pour filtrage Phase 1
        self._gate = get_candidate_gate() if use_gate else None

        # StructureNumberingGate pour filtrage faux positifs numérotation (Plan v2.1)
        self._structure_gate = (
            StructureNumberingGate(structure_gate_config or StructureGateConfig())
            if use_gate else None
        )

    def mine_document(
        self,
        filename: str,
        pages_text: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MiningResult:
        """
        Mine un document complet pour extraire les candidats.

        Args:
            filename: Nom du fichier (avec extension)
            pages_text: Liste de textes par page (index 0 = premiere page)
            metadata: Metadonnees additionnelles (headers, footers, etc.)

        Returns:
            MiningResult avec tous les candidats
        """
        result = MiningResult()

        # 1. Miner le filename
        filename_candidates = self._mine_filename(filename)
        result.candidates.extend(filename_candidates)
        if filename_candidates:
            result.source_coverage.add("filename")

        # 2. Miner les premieres pages (cover/title)
        cover_pages = min(3, len(pages_text))  # Max 3 premieres pages
        for i in range(cover_pages):
            source = "cover" if i == 0 else "header"
            page_candidates = self._mine_text(
                pages_text[i],
                source=source,
                position=0 if i == 0 else 1,
            )
            result.candidates.extend(page_candidates)
            if page_candidates:
                result.source_coverage.add(source)

        # 3. Miner les metadonnees (headers/footers si disponibles)
        if metadata:
            if "headers" in metadata:
                for header in metadata["headers"]:
                    header_candidates = self._mine_text(header, source="header", position=0)
                    result.candidates.extend(header_candidates)
                    if header_candidates:
                        result.source_coverage.add("header")

            if "revision_block" in metadata:
                rev_candidates = self._mine_text(
                    metadata["revision_block"],
                    source="revision",
                    position=0,
                )
                result.candidates.extend(rev_candidates)
                if rev_candidates:
                    result.source_coverage.add("revision")

        # 4. Scanner le body pour comptage d'occurrences (pages 3+)
        body_text = "\n".join(pages_text[3:]) if len(pages_text) > 3 else ""
        if body_text:
            body_candidates = self._mine_text(body_text, source="body", position=2)
            # Pour le body, on compte juste les occurrences, pas de nouveaux candidats
            existing_values = {c.value for c in result.candidates}
            for bc in body_candidates:
                if bc.value in existing_values:
                    # Incrementer le compteur du candidat existant
                    for c in result.candidates:
                        if c.value == bc.value:
                            c.occurrences += 1
                            break

        # 5. Compter les hits de scope language
        full_text = "\n".join(pages_text[:5])  # Premiers 5 pages
        result.scope_language_hits = self._count_scope_language_hits(full_text)

        # 6. Compter les patterns de conflit
        result.conflict_hits = self._count_conflict_hits(full_text)

        # 7. Fusionner les doublons
        result = result.merge_duplicates()

        # 8. PHASE 1: Filtrer via CandidateGate
        if self._gate and self.use_gate:
            survivors, rejected = self._gate.filter_candidates(result.candidates)
            result.candidates = survivors
            # Stocker les rejetes pour debug/analyse
            result._rejected_candidates = rejected

        # 9. PHASE 2 (Plan v2.1): StructureNumberingGate - Filtrer faux positifs numérotation
        full_text = "\n".join(pages_text)  # Texte complet pour analyse structurelle
        doc_id = Path(filename).stem if filename else "unknown"

        if self._structure_gate and self.use_gate:
            # Appliquer le gate de numérotation structurelle
            gate_survivors, gate_rejected, gate_soft = self._structure_gate.filter_candidates(
                result.candidates, full_text, doc_id
            )

            # Log des décisions
            if gate_rejected:
                logger.info(
                    f"[StructureNumberingGate] Doc '{doc_id}' HARD_REJECT: "
                    f"{[c.value for c in gate_rejected]}"
                )
            if gate_soft:
                logger.info(
                    f"[StructureNumberingGate] Doc '{doc_id}' SOFT_FLAG: "
                    f"{[c.value for c in gate_soft]}"
                )

            # Décider du traitement des SOFT_FLAG selon config
            config = self.structure_gate_config or StructureGateConfig()

            if config.soft_flag_action == "llm":
                # Inclure les SOFT_FLAG dans les candidats pour arbitrage LLM
                # Le LLM verra structure_risk="SOFT_FLAG" et sera extra skeptical
                result.candidates = gate_survivors + gate_soft
            elif config.soft_flag_action == "weak_marker":
                # Conserver les SOFT_FLAG comme weak_markers (pas d'appel LLM)
                # Ils seront traités comme weak_markers par défaut
                result.candidates = gate_survivors + gate_soft
            else:
                # Default: seulement les survivants
                result.candidates = gate_survivors

            # Stocker les SOFT_FLAG pour référence/debug
            result._soft_flag_candidates = gate_soft

            # Appliquer fallback si document silencieux (tous rejets HARD)
            if len(result.candidates) == 0 and gate_rejected:
                fallback_markers = self._structure_gate.apply_fallback_if_silent(
                    final_markers=result.candidates,
                    rejected=gate_rejected,
                    doc_id=doc_id,
                )
                if fallback_markers:
                    result.candidates = fallback_markers
                    logger.warning(
                        f"[StructureNumberingGate] Doc '{doc_id}' silencieux - "
                        f"Fallback: {[c.value for c in fallback_markers]}"
                    )

        logger.info(
            f"[CandidateMiner] Final: {len(result.candidates)} candidates "
            f"(scope_lang={result.scope_language_hits}, conflicts={result.conflict_hits})"
        )

        return result

    def _mine_filename(self, filename: str) -> List[MarkerCandidate]:
        """Extrait les candidats du nom de fichier avec patterns structurels."""
        candidates = []
        name = Path(filename).stem

        # Nettoyer le nom (remplacer separateurs par espaces)
        name_clean = re.sub(r'[-_.]', ' ', name)

        # PHASE 2: Patterns structurels agnostiques
        for pattern_type, patterns in [
            ("semver", self._semver_patterns),
            ("entity_numeral", self._entity_numeral_patterns),
            ("release_form", self._release_form_patterns),
            ("structured_code", self._structured_code_patterns),
        ]:
            for pattern in patterns:
                for match in pattern.finditer(name_clean):
                    # Pour entity_numeral, extraire le combo entity+number
                    if pattern_type == "entity_numeral" and len(match.groups()) >= 2:
                        entity = match.group(1)
                        numeral = match.group(2)
                        value = f"{entity} {numeral}"
                    else:
                        value = match.group(1) if match.groups() else match.group(0)

                    value = value.strip()

                    if self._is_valid_marker(value):
                        # Plan v2.1: Marquer entity_numeral avec 1-2 chiffres comme weak
                        is_weak = False
                        if pattern_type == "entity_numeral":
                            # Vérifier si le numéro a 1-2 chiffres (pattern \d{1,2})
                            num_part = numeral if len(match.groups()) >= 2 else value.split()[-1]
                            if num_part.isdigit() and len(num_part) <= 2:
                                is_weak = True

                        candidates.append(MarkerCandidate(
                            value=value,
                            source="filename",
                            position=0,
                            evidence=name,
                            lexical_shape=pattern_type,
                            is_weak_candidate=is_weak,
                        ))

        return candidates

    def _mine_text(
        self,
        text: str,
        source: str,
        position: int,
    ) -> List[MarkerCandidate]:
        """Extrait les candidats d'un bloc de texte avec patterns structurels."""
        candidates = []

        if not text or len(text) < 3:
            return candidates

        # PHASE 2: Patterns structurels agnostiques
        for pattern_type, patterns in [
            ("semver", self._semver_patterns),
            ("entity_numeral", self._entity_numeral_patterns),
            ("release_form", self._release_form_patterns),
            ("structured_code", self._structured_code_patterns),
        ]:
            for pattern in patterns:
                for match in pattern.finditer(text):
                    # Pour entity_numeral, extraire le combo entity+number
                    if pattern_type == "entity_numeral" and len(match.groups()) >= 2:
                        entity = match.group(1)
                        numeral = match.group(2)
                        value = f"{entity} {numeral}"
                    else:
                        value = match.group(1) if match.groups() else match.group(0)

                    value = value.strip()

                    if self._is_valid_marker(value):
                        # Extraire le contexte autour du match (plus large pour CandidateGate)
                        start = max(0, match.start() - 50)
                        end = min(len(text), match.end() + 50)
                        evidence = text[start:end].strip()

                        # Plan v2.1: Marquer entity_numeral avec 1-2 chiffres comme weak
                        is_weak = False
                        if pattern_type == "entity_numeral":
                            # Vérifier si le numéro a 1-2 chiffres (pattern \d{1,2})
                            num_part = numeral if len(match.groups()) >= 2 else value.split()[-1]
                            if num_part.isdigit() and len(num_part) <= 2:
                                is_weak = True

                        candidates.append(MarkerCandidate(
                            value=value,
                            source=source,
                            position=position,
                            evidence=evidence,
                            lexical_shape=pattern_type,
                            is_weak_candidate=is_weak,
                        ))

        return candidates

    def _is_valid_marker(self, value: str) -> bool:
        """Verifie si un marqueur est valide (pas dans blacklist)."""
        if not value or len(value) < 2:
            return False

        value_lower = value.lower()
        if value_lower in self.blacklist:
            return False

        # Ignorer les nombres trop generiques
        if value.isdigit() and len(value) < 4:
            return False

        return True

    def _count_scope_language_hits(self, text: str) -> int:
        """Compte les hits de scope language dans le texte."""
        hits = 0
        for lang, patterns in self._scope_patterns.items():
            for pattern in patterns:
                hits += len(pattern.findall(text))
        return hits

    def _count_conflict_hits(self, text: str) -> int:
        """Compte les patterns de conflit/comparaison."""
        hits = 0
        for pattern in self._conflict_patterns:
            hits += len(pattern.findall(text))
        return hits

    def compute_signals(self, result: MiningResult, total_pages: int) -> Dict[str, float]:
        """
        Calcule les signaux de scoring a partir du resultat de mining.

        Args:
            result: Resultat du mining
            total_pages: Nombre total de pages du document

        Returns:
            Dict avec les 5 signaux normalises [0, 1]
        """
        # Marker Position Score: valeur plus haute si marqueurs en cover/header
        position_score = 0.0
        if result.candidates:
            cover_count = sum(1 for c in result.candidates if c.source in ("filename", "cover"))
            header_count = sum(1 for c in result.candidates if c.source == "header")
            position_score = min(1.0, (cover_count * 0.4 + header_count * 0.3) / len(result.candidates))

        # Marker Repeat Score: valeur plus haute si marqueurs repetes
        repeat_score = 0.0
        if result.candidates:
            max_occurrences = max(c.occurrences for c in result.candidates)
            repeat_score = min(1.0, max_occurrences / 10.0)

        # Scope Language Score
        scope_score = min(1.0, result.scope_language_hits / 5.0)

        # Marker Diversity Score (haut = potentiellement MIXED)
        unique_values = result.get_unique_values()
        diversity_score = min(1.0, len(unique_values) / 5.0) if unique_values else 0.0

        # Conflict Score
        conflict_score = min(1.0, result.conflict_hits / 3.0)

        return {
            "marker_position_score": round(position_score, 2),
            "marker_repeat_score": round(repeat_score, 2),
            "scope_language_score": round(scope_score, 2),
            "marker_diversity_score": round(diversity_score, 2),
            "conflict_score": round(conflict_score, 2),
        }


def enrich_candidates_with_structural_analysis(
    candidates: List[MarkerCandidate],
    structural_analysis: "StructuralAnalysis",
    linguistic_detector: Optional[Any] = None,
) -> List[MarkerCandidate]:
    """
    Enrichit les candidats avec l'analyse structurelle (PR6).

    Args:
        candidates: Liste de MarkerCandidate basiques
        structural_analysis: Resultat de TemplateDetector.analyze()
        linguistic_detector: Instance de LinguisticCueDetector (optionnel)

    Returns:
        Liste de MarkerCandidate enrichis avec features structurelles
    """
    from knowbase.extraction_v2.context.structural import (
        LinguisticCueDetector,
        get_linguistic_cue_detector,
    )

    if linguistic_detector is None:
        linguistic_detector = get_linguistic_cue_detector()

    total_pages = structural_analysis.total_pages
    enriched = []

    for candidate in candidates:
        # 1. Zone distribution
        zone_dist = structural_analysis.get_zone_distribution_for_value(candidate.value)
        candidate.zone_distribution = zone_dist

        # 2. Dominant zone
        if zone_dist:
            max_zone = max(zone_dist, key=zone_dist.get)
            candidate.dominant_zone = max_zone

        # 3. Pages covered
        pages_with_value = set()
        for pz in structural_analysis.pages_zones:
            for line in pz.get_all_lines():
                if candidate.value.lower() in line.text.lower():
                    pages_with_value.add(pz.page_index)

        candidate.pages_covered = len(pages_with_value)
        candidate.pages_covered_ratio = (
            len(pages_with_value) / total_pages if total_pages > 0 else 0.0
        )

        # 4. Positional stability
        total_occurrences = sum(zone_dist.values())
        if total_occurrences > 0:
            max_zone_count = max(zone_dist.values())
            candidate.positional_stability = max_zone_count / total_occurrences

        # 5. Template detection
        template = structural_analysis.get_template_for_value(candidate.value)
        if template:
            candidate.is_in_template_fragment = True
            candidate.template_likelihood = template.template_likelihood
        else:
            candidate.is_in_template_fragment = False
            # Calculer une likelihood basee sur les features
            # High positional stability + bottom zone = likely template
            if candidate.dominant_zone == "bottom" and candidate.positional_stability > 0.7:
                candidate.template_likelihood = 0.6 * candidate.positional_stability
            else:
                candidate.template_likelihood = 0.1

        # 6. Evidence samples
        evidence_samples = []
        for pz in structural_analysis.pages_zones:
            for line in pz.get_all_lines():
                if candidate.value.lower() in line.text.lower():
                    evidence_samples.append(EvidenceSample(
                        page=pz.page_index,
                        zone=line.zone.value,
                        text=line.text[:120],
                    ))
                    if len(evidence_samples) >= 5:
                        break
            if len(evidence_samples) >= 5:
                break
        candidate.evidence_samples = evidence_samples

        # 7. Linguistic cues
        if evidence_samples:
            samples_for_scoring = [
                {"text": s.text, "page": s.page, "zone": s.zone}
                for s in evidence_samples
            ]
            cues = linguistic_detector.score_evidence_samples(samples_for_scoring)
            candidate._contextual_cues = cues

        # 8. Structural confidence
        candidate._structural_confidence = structural_analysis.structural_confidence.value

        enriched.append(candidate)

    logger.info(
        f"[CandidateMiner] Enriched {len(enriched)} candidates with structural features"
    )

    return enriched


__all__ = [
    # Main classes
    "CandidateMiner",
    "MarkerCandidate",
    "MiningResult",
    "EvidenceSample",
    # Phase 1: CandidateGate
    "CandidateGate",
    "GateResult",
    "get_candidate_gate",
    # Phase 2 (Plan v2.1): StructureNumberingGate
    "StructureNumberingGate",
    "StructureGateConfig",
    "SequenceDetectionResult",
    "get_structure_numbering_gate",
    # Functions
    "enrich_candidates_with_structural_analysis",
]
