"""
Hallucination Guard — CH-36 B.4 / CH-37 C.3.

Garde-fou anti-hallucination régulatoire. Vérifie que les TOKENS FACTUELS
critiques (numéros de règlements, articles, valeurs numériques avec unité,
dates) présents dans la réponse synthétisée existent verbatim ou en quasi-
verbatim dans les chunks evidence.

Pourquoi pas le faithfulness judge LLM ? Le judge LLM est sémantique, peut
manquer un "1.5 J" inventé alors que les chunks parlent de "21 J" (les deux
sont "des valeurs d'énergie d'impact en J", le LLM peut les confondre).

Cette guard est **lexicale, déterministe, rapide** (~5ms). Elle attrape :
- Régulations EU inventées (2037/2000 alors que pas dans le corpus)
- Valeurs numériques inventées (1.5 J alors que les chunks disent 21 J)
- Articles inventés (Article 99)
- Dates inventées

Domain-agnostic : utilise des patterns structurels génériques, pas de
vocabulaire métier.

Sortie : liste de tokens hallucinés. Caller décide quoi faire (regen,
abstention, ou note d'avertissement à l'utilisateur).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Patterns de tokens factuels à vérifier (DOMAIN-AGNOSTIC, multilingues)
# Domain-specific patterns (cs_code, npa_ref) sont gérés par les Domain Packs
# (cf. CH-38 D.1 — Domain Pack hints) et ajoutés dynamiquement si pack actif.
_FACTUAL_TOKEN_PATTERNS = [
    # Numéros normés "X/Y" : régulations EU (2021/821), normes ISO/IEC 27001/2022,
    # standards W3C, brevets US 10/123456, code-barres EAN, etc.
    (re.compile(r"\b\d{1,5}/\d{2,5}\b"), "numbered_id"),
    # Articles, sections, paragraphes, clauses — universel legal/regulatory/contracts
    (re.compile(r"\b(?:article|art\.?|section|sect\.?|§|paragraph|para\.?|clause|chapter|chap\.?)\s*\d{1,4}(?:\.\d+)*(?:\([a-z\d]+\))?\b", re.IGNORECASE), "article_ref"),
    # Versions logiciel : v1.2.3, version 2.0, release 3.5 — IT/Tech
    (re.compile(r"\b(?:v(?:ersion)?|release|rev\.?)\s*\d+(?:\.\d+){1,3}(?:[a-z]+\d*)?\b", re.IGNORECASE), "version_id"),
    # Identifiants alphanumériques : CVE-2024-1234, ISO 27001, RFC 7231,
    # SKU ABC-123, ATC code A02BC02, ICD-10 J45, CAS-RN — flexible
    (re.compile(r"\b(?:CVE|ISO|IEC|IEEE|RFC|ANSI|DIN|EN|ASTM|ATC|ICD)[-\s]?\d+(?:[-\s/]\d+)*\b", re.IGNORECASE), "standard_id"),
    # Amendments / revisions / updates : Amendment 28, Rev. 3, Update 2.1
    (re.compile(r"\b(?:amendment|amdt|amd|revision|update)\s*\d{1,3}\b", re.IGNORECASE), "amendment_ref"),
    # Valeurs numériques avec unité — couvre :
    # - Énergie/temps/fréquence (J/kJ/ms/µs/MHz/...)
    # - Distance/masse (m/km/mm/g/kg/mg/ng)
    # - Volume (L/mL/µL)
    # - Température (°C/°F/K)
    # - Concentration (%/ppm/ppb/mol/mmol/mg/L)
    # - Tension/courant/puissance (V/mV/A/mA/W/mW/kW)
    # - Pression (Pa/kPa/MPa/bar/psi)
    # - Débit (Mbps/Gbps/RPM)
    # - Monétaire (USD/EUR/GBP/CHF/JPY)
    # - Temps (jours/days/heures/hours/minutes/secondes/seconds)
    (re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:"
                r"J|kJ|MJ|cal|kcal|"
                r"ms|µs|us|ns|s|min|h|"
                r"Hz|kHz|MHz|GHz|"
                r"°C|°F|K|"
                r"mm|cm|m|km|mi|in|ft|"
                r"mg|g|kg|t|µg|ng|"
                r"mL|L|cL|dL|µL|"
                r"%|ppm|ppb|"
                r"mol|mmol|µmol|"
                r"V|mV|A|mA|µA|W|mW|kW|MW|"
                r"Pa|kPa|MPa|bar|psi|atm|"
                r"bps|kbps|Mbps|Gbps|RPM|"
                r"USD|EUR|GBP|CHF|JPY|CNY|\$|€|£|¥|"
                r"jours?|days?|heures?|hours?|minutes?|secondes?|seconds?|semaines?|weeks?|mois|months?|ans?|years?"
                r")\b", re.IGNORECASE), "value_with_unit"),
    # Dates explicites multilingues — FR/EN/DE/ES/IT
    # FR : 15 décembre 2023
    (re.compile(r"\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}\b", re.IGNORECASE), "date_fr"),
    # EN : 15 December 2023, December 15, 2023
    (re.compile(r"\b(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:\d{1,2},\s+)?\d{4}\b", re.IGNORECASE), "date_en"),
    # DE : 15. Dezember 2023
    (re.compile(r"\b\d{1,2}\.\s*(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+\d{4}\b", re.IGNORECASE), "date_de"),
    # ES : 15 de diciembre de 2023
    (re.compile(r"\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+\d{4}\b", re.IGNORECASE), "date_es"),
    # IT : 15 dicembre 2023
    (re.compile(r"\b\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4}\b", re.IGNORECASE), "date_it"),
    # Format ISO 8601 et numérique : 2023-12-15, 15/12/2023, 12/15/2023
    (re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b"), "date_numeric"),
]

# DOMAIN-SPECIFIC patterns — chargés conditionnellement via Domain Pack
# Ces patterns ne sont PAS actifs par défaut. Ils s'ajoutent quand un pack est actif.
# Pour aerospace_compliance :
_DOMAIN_PATTERNS = {
    "aerospace_compliance": [
        # CS codes : CS 25.788, CS-25, CS 25.1309(c)
        (re.compile(r"\bCS[\s_-]?\d{1,3}(?:\.\d{1,4})?(?:\([a-z\d]+\))?\b", re.IGNORECASE), "cs_code"),
        # NPA references : NPA 2015-19
        (re.compile(r"\bNPA[\s_-]?\d{4}-\d{1,3}\b", re.IGNORECASE), "npa_ref"),
        # ED Decisions : ED Decision 2023/021/R
        (re.compile(r"\bED\s+Decision\s+\d{4}/\d{1,3}/[A-Z]\b", re.IGNORECASE), "ed_decision"),
    ],
    "biomedical": [
        # ATC codes : A02BC02, N06AB04
        (re.compile(r"\b[A-Z]\d{2}[A-Z]{2}\d{2}\b"), "atc_code"),
        # ICD-10 codes : J45, M54.5
        (re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b"), "icd10_code"),
        # Drug doses : 5 mg/kg, 200 mg/m²
        (re.compile(r"\b\d+(?:[.,]\d+)?\s*mg/(?:kg|m²|m2|day|jour)\b", re.IGNORECASE), "dose_per_weight"),
    ],
    "enterprise_sap": [
        # SAP transactions/notes : VA01, ME21N, /SCWM/MON, SAP Note 1234567
        (re.compile(r"\b(?:SAP\s+Note|note)\s+\d{6,8}\b", re.IGNORECASE), "sap_note"),
        (re.compile(r"\b[A-Z]{2,4}\d{1,3}[A-Z]?\b"), "sap_transaction"),
    ],
    "regulatory": [
        # Same as aerospace mostly — articles, regulations are common
        # Add specific GDPR/CCPA patterns if needed
    ],
}


def _get_active_patterns(domain: Optional[str] = None) -> list[tuple]:
    """Retourne les patterns à utiliser selon le domain actif.

    Args:
        domain: nom du Domain Pack actif (aerospace_compliance, biomedical, etc.)
                ou None pour utiliser uniquement les patterns génériques.
    """
    patterns = list(_FACTUAL_TOKEN_PATTERNS)
    if domain and domain in _DOMAIN_PATTERNS:
        patterns.extend(_DOMAIN_PATTERNS[domain])
    return patterns


# Tokens contextuels acceptables qu'il ne faut PAS considérer comme tokens factuels
# (utilisés couramment dans les phrases de structure, pas des affirmations factuelles)
_GENERIC_TOKENS = {
    "annex i", "annex ii", "annex iii", "annex iv", "annex v",  # mentions structurelles courantes
}

# Pattern pour identifier les "bare" cs_code (sans paragraphe spécifique = identifiant domaine)
# Ex: "CS-25", "CS 23" → générique. "CS 25.788" → spécifique, à vérifier.
_BARE_CS_PATTERN = re.compile(r"^cs[\s_-]?\d{1,3}$", re.IGNORECASE)


@dataclass
class HallucinatedToken:
    token: str
    token_type: str
    reason: str = ""


@dataclass
class HallucinationGuardReport:
    hallucinated: list[HallucinatedToken] = field(default_factory=list)
    n_total_factual: int = 0
    n_verified: int = 0
    n_hallucinated: int = 0
    has_hallucination: bool = False
    confidence: float = 1.0  # 1.0 = certain pas d'hallucination ; 0.0 = certaine hallucination


# Mapping mois FR↔EN pour cross-lingual date matching
_MONTH_FR_TO_EN = {
    "janvier": "january", "février": "february", "mars": "march", "avril": "april",
    "mai": "may", "juin": "june", "juillet": "july", "août": "august",
    "septembre": "september", "octobre": "october", "novembre": "november", "décembre": "december",
}
_MONTH_EN_TO_FR = {v: k for k, v in _MONTH_FR_TO_EN.items()}


def _normalize(s: str) -> str:
    """Normalise un token pour comparaison fuzzy."""
    s = s.lower().strip()
    # Unifier espaces et tirets
    s = re.sub(r"[\s_-]+", " ", s)
    # Unifier virgule/point décimal
    s = s.replace(",", ".")
    return s


def _expand_date_variants(token: str) -> list[str]:
    """Génère les variantes FR/EN d'une date pour cross-lingual matching."""
    tn = _normalize(token)
    variants = [tn]
    # Si contient un mois FR → ajouter version EN
    for fr, en in _MONTH_FR_TO_EN.items():
        if fr in tn:
            variants.append(tn.replace(fr, en))
    # Si contient un mois EN → ajouter version FR
    for en, fr in _MONTH_EN_TO_FR.items():
        if en in tn:
            variants.append(tn.replace(en, fr))
    return variants


def _expand_amendment_variants(token: str) -> list[str]:
    """Variantes amdt ↔ amendment ↔ amend pour cross-form matching."""
    tn = _normalize(token)
    variants = {tn}
    # Extraire le numéro
    m = re.search(r"\d+", tn)
    if m:
        num = m.group(0)
        for prefix in ["amendment", "amdt", "amend"]:
            variants.add(f"{prefix} {num}")
    return list(variants)


def _token_in_evidence(token: str, evidence_text: str, token_type: str = "") -> bool:
    """Vérifie si un token (normalisé) est présent dans l'evidence (case-insensitive,
    tolérant aux espaces, tirets, mois FR/EN, formes amdt↔amendment)."""
    en = _normalize(evidence_text)
    en_compact = re.sub(r"\s+", "", en)
    # Pour les dates et amendments : essayer toutes les variantes linguistiques/formes
    if token_type in ("date_fr", "date_en"):
        variants = _expand_date_variants(token)
    elif token_type == "amendment_ref":
        variants = _expand_amendment_variants(token)
    else:
        variants = [_normalize(token)]
    for tn in variants:
        if tn in en:
            return True
        tn_compact = re.sub(r"\s+", "", tn)
        if tn_compact in en_compact:
            return True
    return False


def check_hallucination(
    answer: str,
    claims: list[Any],
    skip_in_quotes: bool = True,
    domain: Optional[str] = None,
) -> HallucinationGuardReport:
    """Vérifie que les tokens factuels de l'answer sont supportés par les claims.

    Args:
        answer: réponse synthétisée
        claims: liste de claims avec attribut .text (ou dict avec key 'text')
        skip_in_quotes: si True, ignore les tokens à l'intérieur de citations directes
            (entre guillemets) — souvent ce sont des extraits verbatim
        domain: Domain Pack actif (aerospace_compliance, biomedical, enterprise_sap, ...)
            Active des patterns supplémentaires spécifiques au domaine.

    Returns:
        HallucinationGuardReport avec liste des tokens potentiellement hallucinés.
    """
    report = HallucinationGuardReport()

    if not answer or not claims:
        return report

    # Build evidence corpus (full text concatenated)
    evidence_parts = []
    for c in claims:
        text = getattr(c, "text", None) if not isinstance(c, dict) else c.get("text")
        if text:
            evidence_parts.append(text)
    evidence_corpus = "\n".join(evidence_parts)

    if not evidence_corpus.strip():
        return report

    # Strip citation tokens [doc=xxx] from answer for cleaner factual extraction
    answer_clean = re.sub(r"\[doc[^\]]*\]", " ", answer)

    # Optionally strip quoted segments (verbatim extracts shouldn't trigger guard)
    if skip_in_quotes:
        # FR « ... » and EN " ... "
        answer_clean = re.sub(r"«[^»]+»", " ", answer_clean)
        answer_clean = re.sub(r'"[^"]+"', " ", answer_clean)

    # Extract factual tokens from answer (génériques + domain-specific si pack actif)
    active_patterns = _get_active_patterns(domain)
    factual_tokens: list[tuple[str, str]] = []  # (token, type)
    seen = set()
    for pattern, token_type in active_patterns:
        for m in pattern.finditer(answer_clean):
            tok = m.group(0).strip()
            tok_norm = _normalize(tok)
            if tok_norm in _GENERIC_TOKENS or tok_norm in seen:
                continue
            # Skip bare cs_code (e.g. "CS-25" without paragraph) — c'est un identifiant
            # domaine générique, pas une affirmation factuelle vérifiable au token près
            if token_type == "cs_code" and _BARE_CS_PATTERN.match(tok_norm):
                continue
            # Skip bare amendment_ref sans contexte spécifique
            # (Amendment 28 est légitime en standalone, mais c'est aussi le cas dominant
            # donc on garde — souvent vérifiable dans les chunks)
            seen.add(tok_norm)
            factual_tokens.append((tok, token_type))

    report.n_total_factual = len(factual_tokens)

    if not factual_tokens:
        # Pas de token factuel dans l'answer → pas de risque d'hallucination chiffrée
        return report

    # Check each token against evidence
    for tok, ttype in factual_tokens:
        if _token_in_evidence(tok, evidence_corpus, ttype):
            report.n_verified += 1
        else:
            report.hallucinated.append(HallucinatedToken(
                token=tok,
                token_type=ttype,
                reason="not_found_in_evidence",
            ))
            report.n_hallucinated += 1

    report.has_hallucination = report.n_hallucinated > 0
    if report.n_total_factual > 0:
        report.confidence = report.n_verified / report.n_total_factual

    if report.has_hallucination:
        logger.warning(
            "[HALLU_GUARD] %d/%d factual tokens NOT found in evidence: %s",
            report.n_hallucinated, report.n_total_factual,
            [(t.token, t.token_type) for t in report.hallucinated[:5]],
        )
    else:
        logger.info(
            "[HALLU_GUARD] all %d factual tokens verified in evidence",
            report.n_total_factual,
        )

    return report


def build_hallucination_warning(report: HallucinationGuardReport) -> Optional[str]:
    """Construit un message d'avertissement utilisateur si hallucinations détectées."""
    if not report.has_hallucination:
        return None
    bullets = "\n".join(
        f"  - {t.token} (type: {t.token_type})" for t in report.hallucinated[:5]
    )
    return (
        f"⚠️ {report.n_hallucinated} valeur(s) de la réponse n'apparaissent pas "
        f"dans les sources et pourraient être inventées :\n{bullets}"
    )
