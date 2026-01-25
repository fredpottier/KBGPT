# src/knowbase/api/services/challenge_service.py
"""
Service TextChallenger pour MVP V1.

Challenge un texte utilisateur contre le corpus documentaire.
INVARIANT 2: Chaque claim produit une réponse (jamais de silence).

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from __future__ import annotations
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from knowbase.stratified.claimkey.patterns import get_claimkey_patterns, PatternMatch
from knowbase.stratified.pass1.value_extractor import get_value_extractor

logger = logging.getLogger(__name__)


class ChallengeStatus(str, Enum):
    """Statuts possibles pour un claim challengé."""
    CONFIRMED = "CONFIRMED"          # Validé par le corpus
    CONTRADICTED = "CONTRADICTED"    # Contredit par le corpus
    PARTIAL = "PARTIAL"              # Trouvé mais non comparable
    MISSING = "MISSING"              # Sujet documenté, valeur absente
    UNMAPPED = "UNMAPPED"            # Pas de pattern reconnu (INVARIANT 2)


class TensionLevel(str, Enum):
    """Niveaux de tension pour contradictions."""
    NONE = "none"
    SOFT = "soft"    # Compatible mais différent (ex: TLS 1.3 vs min 1.2)
    HARD = "hard"    # Incompatible


class CorpusMatch(BaseModel):
    """Match trouvé dans le corpus."""
    information_id: str
    document_id: str
    document_title: Optional[str] = None
    exact_quote: str
    value_raw: Optional[str] = None
    value_normalized: Optional[str] = None
    context_edition: Optional[str] = None
    context_region: list[str] = Field(default_factory=list)
    page: Optional[int] = None


class ChallengeMatch(BaseModel):
    """Résultat pour un claim individuel."""
    claim_text: str
    status: ChallengeStatus
    tension_level: TensionLevel = TensionLevel.NONE
    claimkey_id: Optional[str] = None
    claimkey_question: Optional[str] = None
    user_value_raw: Optional[str] = None
    user_value_normalized: Optional[str] = None
    corpus_matches: list[CorpusMatch] = Field(default_factory=list)
    explanation: str = ""


class ChallengeResponse(BaseModel):
    """Réponse complète du challenge."""
    request_id: str
    text_original: str
    claims_found: int
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    matches: list[ChallengeMatch] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class TextChallenger:
    """
    Service de challenge de texte contre le corpus.

    Responsabilités:
    - Segmenter le texte en claims
    - Inférer les ClaimKeys
    - Rechercher dans le corpus
    - Comparer les valeurs
    - Retourner les résultats structurés

    INVARIANT 2: Chaque claim produit une réponse (jamais de silence).
    INVARIANT 3: Préférer les faux négatifs aux faux positifs.
    """

    def __init__(self, neo4j_driver, tenant_id: str):
        self.neo4j_driver = neo4j_driver
        self.tenant_id = tenant_id
        self.claimkey_patterns = get_claimkey_patterns()
        self.value_extractor = get_value_extractor()

    async def challenge(
        self,
        text: str,
        context: Optional[dict] = None,
        include_missing: bool = True
    ) -> ChallengeResponse:
        """
        Challenge un texte utilisateur contre le corpus.

        Args:
            text: Texte à challenger
            context: Contexte optionnel (edition, region, product)
            include_missing: Inclure les claims non documentés

        Returns:
            ChallengeResponse avec tous les résultats
        """
        context = context or {}
        request_id = f"challenge_{uuid.uuid4().hex[:12]}"

        # 1. Segmenter le texte en claims
        claims = self._segment_text(text)

        # 2. Traiter chaque claim
        matches: list[ChallengeMatch] = []
        for claim in claims:
            match = await self._process_claim(claim, context)
            # INVARIANT 2: Chaque claim produit une réponse
            matches.append(match)

        # 3. Calculer le résumé
        summary = self._compute_summary(matches)

        logger.info(
            f"[CHALLENGE] {request_id}: {len(claims)} claims, "
            f"{summary.get('confirmed', 0)} confirmed, "
            f"{summary.get('contradicted', 0)} contradicted"
        )

        return ChallengeResponse(
            request_id=request_id,
            text_original=text,
            claims_found=len(claims),
            matches=matches,
            summary=summary
        )

    def _segment_text(self, text: str) -> list[str]:
        """
        Segmente le texte en claims individuels.

        Stratégie:
        1. Split par phrase (., !, ?) en évitant les décimales (99.9)
        2. Split par conjonctions (and, or, but) si phrase contient plusieurs claims
        3. Filtrer les segments vides ou trop courts
        """
        # Split par phrase - évite de couper les nombres décimaux
        # Pattern: point suivi d'espace ou fin de chaîne, pas de chiffre après
        sentences = re.split(r'(?<!\d)[.!?]+(?:\s|$)|(?<=\d)[.!?]+(?=\s+[A-Z]|$)', text)

        claims = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue

            # Si contient des conjonctions, split aussi
            if re.search(r'\b(and|or|but|,)\b', sentence.lower()):
                sub_claims = re.split(r'\b(and|or|but)\b|,', sentence, flags=re.IGNORECASE)
                for sub in sub_claims:
                    sub = sub.strip() if sub else ""
                    if len(sub) >= 10:
                        claims.append(sub)
            else:
                claims.append(sentence)

        return claims

    async def _process_claim(
        self,
        claim: str,
        context: dict
    ) -> ChallengeMatch:
        """
        Traite un claim individuel.

        INVARIANT 2: Retourne TOUJOURS un ChallengeMatch, jamais None.
        """
        # 1. Tenter d'inférer un ClaimKey
        pattern_match = self.claimkey_patterns.infer_claimkey(claim, context)

        if not pattern_match:
            # INVARIANT 2: Pas de pattern → UNMAPPED (pas de silence)
            return ChallengeMatch(
                claim_text=claim,
                status=ChallengeStatus.UNMAPPED,
                explanation="No ClaimKey pattern matched for this claim"
            )

        # 2. Extraire la valeur du claim utilisateur
        user_value = self.value_extractor.extract(claim)

        # 3. Rechercher dans le corpus
        corpus_matches = await self._search_corpus(
            claimkey_id=pattern_match.claimkey_id,
            claimkey_key=pattern_match.key,
            context=context
        )

        # 4. Comparer et déterminer le statut
        return self._compare_with_corpus(
            claim_text=claim,
            pattern_match=pattern_match,
            user_value=user_value,
            corpus_matches=corpus_matches
        )

    async def _search_corpus(
        self,
        claimkey_id: str,
        claimkey_key: str,
        context: dict
    ) -> list[CorpusMatch]:
        """
        Recherche les Informations liées à un ClaimKey dans le corpus.

        INVARIANT: Seules les PROMOTED_LINKED sont retournées.
        """
        with self.neo4j_driver.session() as session:
            # Recherche par claimkey_id OU par key (fuzzy)
            # FIX: Parenthèses pour priorité AND/OR correcte
            result = session.run("""
                MATCH (i:InformationMVP)-[:ANSWERS]->(ck:ClaimKey)
                WHERE (ck.claimkey_id = $ck_id OR ck.key CONTAINS $key_part)
                  AND i.tenant_id = $tenant_id
                  AND i.promotion_status = 'PROMOTED_LINKED'
                OPTIONAL MATCH (i)-[:EXTRACTED_FROM]->(d:Document)
                RETURN i, d, ck
                ORDER BY i.confidence DESC
                LIMIT 10
            """,
                ck_id=claimkey_id,
                key_part=claimkey_key.split("_")[0],  # Premier segment de la clé
                tenant_id=self.tenant_id
            )

            matches = []
            for record in result:
                info = record["i"]
                doc = record.get("d")

                matches.append(CorpusMatch(
                    information_id=info["information_id"],
                    document_id=info["document_id"],
                    document_title=doc["title"] if doc else None,
                    exact_quote=info.get("exact_quote", info.get("text", "")),
                    value_raw=info.get("value_raw"),
                    value_normalized=str(info.get("value_normalized")) if info.get("value_normalized") else None,
                    context_edition=info.get("context_edition"),
                    context_region=info.get("context_region", []),
                    page=info.get("span_page")
                ))

            return matches

    def _compare_with_corpus(
        self,
        claim_text: str,
        pattern_match: PatternMatch,
        user_value,
        corpus_matches: list[CorpusMatch]
    ) -> ChallengeMatch:
        """
        Compare le claim utilisateur avec le corpus.

        Retourne le statut approprié:
        - CONFIRMED: Valeur identique
        - CONTRADICTED: Valeur différente (avec tension soft/hard)
        - PARTIAL: Trouvé mais non comparable
        - MISSING: ClaimKey existe mais pas de valeur
        """
        claimkey_question = self.claimkey_patterns.get_canonical_question(
            pattern_match.claimkey_id
        )

        user_value_raw = user_value.raw if user_value else None
        user_value_normalized = str(user_value.normalized) if user_value and user_value.normalized else None

        if not corpus_matches:
            # Pas de match dans le corpus
            return ChallengeMatch(
                claim_text=claim_text,
                status=ChallengeStatus.MISSING,
                claimkey_id=pattern_match.claimkey_id,
                claimkey_question=claimkey_question,
                user_value_raw=user_value_raw,
                user_value_normalized=user_value_normalized,
                explanation=f"ClaimKey '{pattern_match.key}' exists but no corpus data found"
            )

        # Vérifier si une valeur corpus match
        if not user_value or not user_value.normalized:
            # Utilisateur n'a pas de valeur → PARTIAL
            return ChallengeMatch(
                claim_text=claim_text,
                status=ChallengeStatus.PARTIAL,
                claimkey_id=pattern_match.claimkey_id,
                claimkey_question=claimkey_question,
                corpus_matches=corpus_matches,
                explanation="Claim found in corpus but no comparable value in user text"
            )

        # Comparer avec chaque match corpus
        for corpus_match in corpus_matches:
            if not corpus_match.value_normalized:
                continue

            # Comparer les valeurs normalisées
            comparison = self._compare_values(
                user_value=user_value,
                corpus_value_normalized=corpus_match.value_normalized
            )

            if comparison == "equal":
                return ChallengeMatch(
                    claim_text=claim_text,
                    status=ChallengeStatus.CONFIRMED,
                    tension_level=TensionLevel.NONE,
                    claimkey_id=pattern_match.claimkey_id,
                    claimkey_question=claimkey_question,
                    user_value_raw=user_value_raw,
                    user_value_normalized=user_value_normalized,
                    corpus_matches=[corpus_match],
                    explanation=f"Value confirmed: {user_value_raw} matches corpus"
                )

            elif comparison == "soft_conflict":
                # INVARIANT 4: Soft conflict pour over-compliance
                return ChallengeMatch(
                    claim_text=claim_text,
                    status=ChallengeStatus.CONTRADICTED,
                    tension_level=TensionLevel.SOFT,
                    claimkey_id=pattern_match.claimkey_id,
                    claimkey_question=claimkey_question,
                    user_value_raw=user_value_raw,
                    user_value_normalized=user_value_normalized,
                    corpus_matches=[corpus_match],
                    explanation=f"Soft conflict: user claims {user_value_raw}, corpus has {corpus_match.value_raw} (over-compliance)"
                )

            elif comparison == "hard_conflict":
                return ChallengeMatch(
                    claim_text=claim_text,
                    status=ChallengeStatus.CONTRADICTED,
                    tension_level=TensionLevel.HARD,
                    claimkey_id=pattern_match.claimkey_id,
                    claimkey_question=claimkey_question,
                    user_value_raw=user_value_raw,
                    user_value_normalized=user_value_normalized,
                    corpus_matches=[corpus_match],
                    explanation=f"Hard conflict: user claims {user_value_raw}, corpus has {corpus_match.value_raw}"
                )

        # Pas de valeur comparable dans le corpus
        return ChallengeMatch(
            claim_text=claim_text,
            status=ChallengeStatus.PARTIAL,
            claimkey_id=pattern_match.claimkey_id,
            claimkey_question=claimkey_question,
            user_value_raw=user_value_raw,
            user_value_normalized=user_value_normalized,
            corpus_matches=corpus_matches,
            explanation="No comparable value in corpus matches"
        )

    def _compare_values(
        self,
        user_value,
        corpus_value_normalized: str
    ) -> str:
        """
        Compare deux valeurs normalisées.

        Returns:
            "equal", "soft_conflict", "hard_conflict", ou "incomparable"
        """
        user_normalized = user_value.normalized
        user_operator = user_value.operator

        # Tenter de parser la valeur corpus
        try:
            corpus_val = float(corpus_value_normalized)
        except (ValueError, TypeError):
            # Comparaison string
            if str(user_normalized).lower() == corpus_value_normalized.lower():
                return "equal"
            return "hard_conflict"

        # Comparaison numérique
        try:
            user_val = float(user_normalized)
        except (ValueError, TypeError):
            return "incomparable"

        # Comparaison selon opérateur
        if user_operator == "=":
            if abs(user_val - corpus_val) < 0.001:
                return "equal"
            return "hard_conflict"

        elif user_operator == ">=":
            if user_val <= corpus_val:
                return "equal"
            # User claims minimum X, corpus has less → soft conflict (over-compliance)
            return "soft_conflict"

        elif user_operator == "<=":
            if user_val >= corpus_val:
                return "equal"
            return "soft_conflict"

        elif user_operator == ">":
            if user_val < corpus_val:
                return "equal"
            return "soft_conflict"

        elif user_operator == "<":
            if user_val > corpus_val:
                return "equal"
            return "soft_conflict"

        return "incomparable"

    def _compute_summary(self, matches: list[ChallengeMatch]) -> dict:
        """Calcule le résumé des résultats."""
        total = len(matches)
        if total == 0:
            return {
                "total_claims": 0,
                "confirmed": 0,
                "contradicted": 0,
                "partial": 0,
                "missing": 0,
                "unmapped": 0,
                "unmapped_rate": 0.0
            }

        confirmed = sum(1 for m in matches if m.status == ChallengeStatus.CONFIRMED)
        contradicted = sum(1 for m in matches if m.status == ChallengeStatus.CONTRADICTED)
        partial = sum(1 for m in matches if m.status == ChallengeStatus.PARTIAL)
        missing = sum(1 for m in matches if m.status == ChallengeStatus.MISSING)
        unmapped = sum(1 for m in matches if m.status == ChallengeStatus.UNMAPPED)

        return {
            "total_claims": total,
            "confirmed": confirmed,
            "contradicted": contradicted,
            "partial": partial,
            "missing": missing,
            "unmapped": unmapped,
            "unmapped_rate": unmapped / total if total > 0 else 0.0,
            "soft_conflicts": sum(1 for m in matches if m.tension_level == TensionLevel.SOFT),
            "hard_conflicts": sum(1 for m in matches if m.tension_level == TensionLevel.HARD)
        }
