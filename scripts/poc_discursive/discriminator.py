"""
POC Discursive Relation Discrimination - Discriminateur LLM

Ce module implemente le discriminateur qui evalue si une relation
est de Type 1 (discursive) ou Type 2 (deduite).

ATTENTION: Code jetable, non destine a la production.
"""

import json
import os
import re
import sys
from typing import Optional

# Ajouter le chemin du projet pour les imports locaux
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from models import (
    TestCase, DiscriminationResult, Verdict, RejectReason, AbstainReason,
    Confidence, Citation
)

# Import du SDK Anthropic
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    print("Warning: anthropic SDK not available, using mock mode")


# =============================================================================
# CHECK DETERMINISTE POST-LLM (v2.1)
# =============================================================================

def deterministic_override(
    result: "DiscriminationResult",
    test_case: "TestCase"
) -> "DiscriminationResult":
    """
    Applique des checks deterministes post-LLM pour corriger les erreurs systematiques.

    Regle 1: Si le texte contient "X or Y" et le predicat est HAS_EXACT_*,
             alors REJECT (car on ne peut pas affirmer "exactement X" quand Y est possible).
    """
    # Ne s'applique qu'aux ACCEPT
    if result.verdict != Verdict.ACCEPT:
        return result

    relation = test_case.evidence_bundle.proposed_relation.upper()

    # Regle 1: HAS_EXACT + "or" dans le texte => REJECT
    if "HAS_EXACT" in relation:
        # Verifier si les extraits contiennent "or" (mot entier)
        all_texts = []
        for extract in test_case.evidence_bundle.concept_a.extracts:
            all_texts.append(extract.text)
        for extract in test_case.evidence_bundle.concept_b.extracts:
            all_texts.append(extract.text)

        combined_text = " ".join(all_texts)

        # Pattern: "or" comme mot entier (pas dans "for", "more", etc.)
        if re.search(r'\bor\b', combined_text, re.IGNORECASE):
            # Override: ACCEPT -> REJECT avec raison explicite
            return DiscriminationResult(
                test_case_id=result.test_case_id,
                verdict=Verdict.REJECT,
                citations=result.citations,
                referent_resolution=None,
                reject_reason=RejectReason.EXTERNAL_KNOWLEDGE,
                abstain_reason=None,
                confidence=Confidence.HIGH,
                raw_reasoning=(
                    f"[OVERRIDE DETERMINISTE] Le texte contient une alternative ('or') "
                    f"mais le predicat exige une valeur exacte (HAS_EXACT). "
                    f"Sans condition de selection explicite, on ne peut pas affirmer "
                    f"une valeur exacte. Verdict original LLM: ACCEPT. "
                    f"Raisonnement LLM: {result.raw_reasoning}"
                )
            )

    return result


SYSTEM_PROMPT = """Tu es un systeme de discrimination de relations.
Ta tache est de determiner si une relation proposee entre deux concepts
est DISCURSIVEMENT DETERMINEE par le texte (Type 1) ou si elle necessite
un RAISONNEMENT EXTERNE (Type 2).

## REGLES ABSOLUES

1. Tu ne peux justifier une relation qu'en CITANT EXACTEMENT les extraits fournis
2. Tu dois IGNORER toute connaissance que tu pourrais avoir sur SAP ou le domaine
3. Si tu ne peux pas justifier par citation textuelle exclusive -> REJECT ou ABSTAIN
4. Si le referent est ambigu ou rompu -> ABSTAIN
5. Si une chaine transitive est requise (A -> C -> B) -> REJECT
6. Si une connaissance externe au texte est requise -> REJECT

## SORTIES AUTORISEES

- ACCEPT : Relation discursive, justifiable par le texte seul
  - Le referent est clairement maintenu
  - Aucun concept intermediaire n'est requis
  - La relation decoule directement de la continuite du document

- REJECT : Relation necessitant raisonnement externe ou transitivite
  - Raisons: TRANSITIVE, EXTERNAL_KNOWLEDGE, CAUSAL, CONCEPT_MISSING

- ABSTAIN : Contexte insuffisant ou ambigu
  - Raisons: BROKEN_REFERENT, AMBIGUOUS, INSUFFICIENT

## FORMAT DE REPONSE (JSON strict)

{
  "verdict": "ACCEPT" | "REJECT" | "ABSTAIN",
  "citations": [
    {"extract_id": "A1", "quote": "citation exacte du texte"},
    {"extract_id": "B1", "quote": "citation exacte du texte"}
  ],
  "referent_resolution": "Explication de comment le referent est maintenu (si ACCEPT)",
  "reject_reason": "TRANSITIVE" | "EXTERNAL_KNOWLEDGE" | "CAUSAL" | "CONCEPT_MISSING" | null,
  "abstain_reason": "BROKEN_REFERENT" | "AMBIGUOUS" | "INSUFFICIENT" | null,
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "reasoning": "Explication detaillee du raisonnement"
}

## RAPPEL CRITIQUE

- Ne JAMAIS utiliser tes connaissances sur SAP, meme si le lien te semble evident
- Une relation "evidente pour un expert" n'est pas une relation textuelle
- Quand tu cites, utilise les MOTS EXACTS du texte
- En cas de doute, prefere ABSTAIN a ACCEPT"""


def build_user_prompt(test_case: TestCase) -> str:
    """Construit le prompt utilisateur pour un cas de test."""

    parts = []

    # En-tete
    parts.append("## ANALYSE DE RELATION")
    parts.append(f"\n**Relation proposee:** {test_case.evidence_bundle.proposed_relation}")

    # Scope (si present)
    if test_case.evidence_bundle.scope:
        parts.append("\n### CONTEXTE GLOBAL (Scope)")
        scope = test_case.evidence_bundle.scope
        parts.append(f"[{scope.id}] Source: {scope.source}, Section: {scope.section}")
        parts.append(f'"{scope.text}"')

    # Concept A
    parts.append(f"\n### CONCEPT A: {test_case.evidence_bundle.concept_a.name}")
    for extract in test_case.evidence_bundle.concept_a.extracts:
        parts.append(f"[{extract.id}] Source: {extract.source}, Section: {extract.section}")
        parts.append(f'"{extract.text}"')

    # Concept B
    parts.append(f"\n### CONCEPT B: {test_case.evidence_bundle.concept_b.name}")
    for extract in test_case.evidence_bundle.concept_b.extracts:
        parts.append(f"[{extract.id}] Source: {extract.source}, Section: {extract.section}")
        parts.append(f'"{extract.text}"')

    # Instruction finale
    parts.append("\n### QUESTION")
    parts.append("Cette relation est-elle DISCURSIVEMENT DETERMINEE par les extraits ci-dessus?")
    parts.append("Reponds en JSON selon le format specifie.")

    return "\n".join(parts)


def parse_llm_response(response_text: str) -> dict:
    """Parse la reponse JSON du LLM."""
    # Nettoyer la reponse (enlever markdown si present)
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    return json.loads(text.strip())


def create_result_from_response(
    test_case_id: str,
    parsed: dict
) -> DiscriminationResult:
    """Cree un DiscriminationResult depuis la reponse parsee."""

    # Mapper les citations
    citations = []
    for cit in parsed.get("citations", []):
        citations.append(Citation(
            extract_id=cit.get("extract_id", "?"),
            quote=cit.get("quote", "")
        ))

    # Mapper les enums
    verdict = Verdict(parsed["verdict"])

    reject_reason = None
    if parsed.get("reject_reason"):
        reject_reason = RejectReason(parsed["reject_reason"])

    abstain_reason = None
    if parsed.get("abstain_reason"):
        abstain_reason = AbstainReason(parsed["abstain_reason"])

    confidence = Confidence(parsed.get("confidence", "MEDIUM"))

    return DiscriminationResult(
        test_case_id=test_case_id,
        verdict=verdict,
        citations=citations,
        referent_resolution=parsed.get("referent_resolution"),
        reject_reason=reject_reason,
        abstain_reason=abstain_reason,
        confidence=confidence,
        raw_reasoning=parsed.get("reasoning", "")
    )


class DiscursiveDiscriminator:
    """Discriminateur de relations discursives vs deduites."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        """
        Initialise le discriminateur.

        Args:
            api_key: Cle API Anthropic (ou variable d'environnement ANTHROPIC_API_KEY)
            model: Modele Claude a utiliser
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model

        if HAS_ANTHROPIC and self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)
        else:
            self.client = None

    def discriminate(self, test_case: TestCase) -> DiscriminationResult:
        """
        Evalue un cas de test et retourne le resultat de discrimination.

        Args:
            test_case: Le cas de test a evaluer

        Returns:
            DiscriminationResult avec le verdict et les justifications
        """
        user_prompt = build_user_prompt(test_case)

        if self.client is None:
            # Mode mock pour tests sans API
            return self._mock_discriminate(test_case)

        try:
            # Appel au LLM
            response = self._call_llm(user_prompt)

            # Parser la reponse
            parsed = parse_llm_response(response)

            # Creer le resultat LLM
            llm_result = create_result_from_response(test_case.id, parsed)

            # Appliquer les checks deterministes post-LLM (v2.1)
            return deterministic_override(llm_result, test_case)

        except Exception as e:
            # En cas d'erreur, retourner un resultat d'erreur
            return DiscriminationResult(
                test_case_id=test_case.id,
                verdict=Verdict.ABSTAIN,
                citations=[],
                referent_resolution=None,
                reject_reason=None,
                abstain_reason=AbstainReason.INSUFFICIENT,
                confidence=Confidence.LOW,
                raw_reasoning=f"Error during discrimination: {str(e)}"
            )

    def _call_llm(self, user_prompt: str) -> str:
        """Appelle le LLM et retourne la reponse brute."""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        return message.content[0].text

    def _mock_discriminate(self, test_case: TestCase) -> DiscriminationResult:
        """Mode mock pour tests sans API."""
        # Retourne le verdict attendu (pour debug)
        return DiscriminationResult(
            test_case_id=test_case.id,
            verdict=test_case.expected_verdict,
            citations=[],
            referent_resolution="[MOCK MODE]" if test_case.expected_verdict == Verdict.ACCEPT else None,
            reject_reason=RejectReason.EXTERNAL_KNOWLEDGE if test_case.expected_verdict == Verdict.REJECT else None,
            abstain_reason=AbstainReason.AMBIGUOUS if test_case.expected_verdict == Verdict.ABSTAIN else None,
            confidence=Confidence.LOW,
            raw_reasoning="[MOCK MODE] - Aucun appel API effectue"
        )


# Test standalone
if __name__ == "__main__":
    from test_cases import TYPE1_CASES

    discriminator = DiscursiveDiscriminator()

    print("Test du discriminateur sur le premier cas Type 1:")
    print("-" * 60)

    test_case = TYPE1_CASES[0]
    print(f"Cas: {test_case.id} - {test_case.description}")
    print(f"Verdict attendu: {test_case.expected_verdict}")

    result = discriminator.discriminate(test_case)

    print(f"\nVerdict obtenu: {result.verdict}")
    print(f"Confiance: {result.confidence}")
    print(f"Raisonnement: {result.raw_reasoning[:200]}...")
