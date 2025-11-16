"""
LLM Canonicalizer Service

Utilise LLM léger (GPT-4o-mini) pour trouver le nom canonique officiel
d'un concept extrait du texte.

Phase 1.6+ : Adaptive Ontology - Zero-Config Intelligence
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import json
import logging
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# SIMPLE CIRCUIT BREAKER (P0 - DoS Protection)
# ═══════════════════════════════════════════════════

class CircuitBreakerOpenError(Exception):
    """Exception when circuit breaker is open."""
    pass


class SimpleCircuitBreaker:
    """
    Circuit breaker simple pour LLM calls (P0 - DoS protection).

    États:
    - CLOSED: Normal, appels passent
    - OPEN: Circuit ouvert, appels bloqués (fallback)
    - HALF_OPEN: Test si service récupéré

    Transitions:
    - CLOSED → OPEN: après failure_threshold échecs consécutifs
    - OPEN → HALF_OPEN: après recovery_timeout secondes
    - HALF_OPEN → CLOSED: après 1 succès
    - HALF_OPEN → OPEN: après 1 échec
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        """
        Args:
            failure_threshold: Nombre d'échecs avant ouverture circuit
            recovery_timeout: Secondes avant tentative récupération
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def call(self, func, *args, **kwargs):
        """Execute function avec circuit breaker protection."""

        # Si circuit OPEN, vérifier si on peut passer à HALF_OPEN
        if self.state == "OPEN":
            if self.last_failure_time and \
               (datetime.now() - self.last_failure_time).total_seconds() >= self.recovery_timeout:
                logger.info("[CircuitBreaker] OPEN → HALF_OPEN (recovery timeout elapsed)")
                self.state = "HALF_OPEN"
            else:
                remaining = self.recovery_timeout - (datetime.now() - self.last_failure_time).total_seconds()
                raise CircuitBreakerOpenError(
                    f"Circuit breaker OPEN (failures={self.failure_count}, "
                    f"recovery in {remaining:.0f}s)"
                )

        # Tenter appel
        try:
            result = func(*args, **kwargs)

            # Succès → reset failure count
            if self.state == "HALF_OPEN":
                logger.info("[CircuitBreaker] HALF_OPEN → CLOSED (call succeeded)")
                self.state = "CLOSED"

            self.failure_count = 0
            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = datetime.now()

            logger.warning(
                f"[CircuitBreaker] Call failed ({self.failure_count}/{self.failure_threshold}): {e}"
            )

            # Si HALF_OPEN, échec immédiat → OPEN
            if self.state == "HALF_OPEN":
                logger.error("[CircuitBreaker] HALF_OPEN → OPEN (call failed)")
                self.state = "OPEN"
                raise CircuitBreakerOpenError("Circuit breaker re-opened after test failure")

            # Si seuil atteint → OPEN
            if self.failure_count >= self.failure_threshold:
                logger.error(
                    f"[CircuitBreaker] CLOSED → OPEN (failures={self.failure_count} >= {self.failure_threshold})"
                )
                self.state = "OPEN"
                raise CircuitBreakerOpenError(f"Circuit breaker opened after {self.failure_count} failures")

            # Re-raise erreur originale
            raise


class CanonicalizationResult(BaseModel):
    """Résultat de canonicalisation LLM."""

    canonical_name: str = Field(..., description="Nom canonique officiel trouvé")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Score confiance (0-1)")
    reasoning: str = Field(..., description="Explication décision LLM")
    aliases: List[str] = Field(default_factory=list, description="Aliases/variantes reconnues")
    concept_type: Optional[str] = Field(None, description="Type de concept (Product, Acronym, etc.)")
    domain: Optional[str] = Field(None, description="Domaine (enterprise_software, legal, etc.)")
    ambiguity_warning: Optional[str] = Field(None, description="Avertissement si ambiguïté détectée")
    possible_matches: List[str] = Field(default_factory=list, description="Autres canonical_names possibles si ambiguïté")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées additionnelles")


class LLMCanonicalizer:
    """Service de canonicalisation via LLM léger."""

    def __init__(self, llm_router):
        """
        Args:
            llm_router: Instance de LLMRouter pour appels LLM
        """
        self.llm_router = llm_router
        self.model = "gpt-4o-mini"  # Modèle léger (~$0.0001/concept)

        # P0: Circuit breaker (5 échecs → ouvert 60s)
        self.circuit_breaker = SimpleCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60
        )

        logger.info(
            f"[LLMCanonicalizer] Initialized with model={self.model}, "
            f"circuit_breaker(failures={self.circuit_breaker.failure_threshold}, "
            f"recovery={self.circuit_breaker.recovery_timeout}s)"
        )

    def canonicalize(
        self,
        raw_name: str,
        context: Optional[str] = None,
        domain_hint: Optional[str] = None,
        timeout: int = 10
    ) -> CanonicalizationResult:
        """
        Canonicalise un nom via LLM.

        Args:
            raw_name: Nom brut extrait (ex: "S/4HANA Cloud's")
            context: Contexte textuel autour de la mention (optionnel)
            domain_hint: Indice domaine (ex: "enterprise_software")
            timeout: Timeout max LLM call en secondes (P0 - DoS protection)

        Returns:
            CanonicalizationResult avec canonical_name et métadonnées

        Example:
            >>> result = canonicalizer.canonicalize(
            ...     raw_name="S/4HANA Cloud's",
            ...     context="Our ERP runs on SAP S/4HANA Cloud's public edition",
            ...     domain_hint="enterprise_software"
            ... )
            >>> result.canonical_name
            "SAP S/4HANA Cloud, Public Edition"
        """

        logger.debug(
            f"[LLMCanonicalizer] Canonicalizing '{raw_name}' "
            f"(context_len={len(context) if context else 0}, domain={domain_hint})"
        )

        # Construire prompt LLM
        prompt = self._build_canonicalization_prompt(
            raw_name=raw_name,
            context=context,
            domain_hint=domain_hint
        )

        try:
            # P0: Appel LLM via circuit breaker avec protection DoS
            def _llm_call():
                # Import TaskType
                from knowbase.common.llm_router import TaskType

                # Appel LLM via router (synchrone)
                response_content = self.llm_router.complete(
                    task_type=TaskType.CANONICALIZATION,
                    messages=[
                        {"role": "system", "content": CANONICALIZATION_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,  # Déterministe
                    response_format={"type": "json_object"}
                )

                # Parse résultat JSON (robust parsing)
                result_json = self._parse_json_robust(response_content)
                return CanonicalizationResult(**result_json)

            # Appel via circuit breaker
            result = self.circuit_breaker.call(_llm_call)

            logger.info(
                f"[LLMCanonicalizer] ✅ '{raw_name}' → '{result.canonical_name}' "
                f"(confidence={result.confidence:.2f}, type={result.concept_type})"
            )

            return result

        except CircuitBreakerOpenError as cb_err:
            # Circuit breaker ouvert → fallback immédiat
            logger.warning(
                f"[LLMCanonicalizer] ⚠️ Circuit breaker OPEN for '{raw_name}': {cb_err}, "
                f"falling back to title case"
            )

            return CanonicalizationResult(
                canonical_name=raw_name.strip().title(),
                confidence=0.5,
                reasoning=f"Circuit breaker open, fallback to title case: {str(cb_err)}",
                aliases=[],
                concept_type="Unknown",
                domain=None,
                ambiguity_warning="LLM service temporarily unavailable (circuit breaker open)",
                possible_matches=[],
                metadata={"error": "circuit_breaker_open", "state": self.circuit_breaker.state}
            )

        except Exception as e:
            logger.error(f"[LLMCanonicalizer] ❌ Error canonicalizing '{raw_name}': {e}")

            # Fallback: retourner résultat basique
            return CanonicalizationResult(
                canonical_name=raw_name.strip().title(),
                confidence=0.5,
                reasoning=f"LLM error, fallback to title case: {str(e)}",
                aliases=[],
                concept_type="Unknown",
                domain=None,
                ambiguity_warning="LLM canonicalization failed",
                possible_matches=[],
                metadata={"error": str(e)}
            )

    def canonicalize_batch(
        self,
        concepts: List[Dict[str, str]],
        timeout: int = 30
    ) -> List[CanonicalizationResult]:
        """
        Canonicalise un batch de concepts via LLM (batch processing).

        Args:
            concepts: Liste de dicts avec clés {raw_name, context, domain_hint}
            timeout: Timeout max LLM call en secondes

        Returns:
            Liste de CanonicalizationResult (même ordre que concepts)

        Example:
            >>> batch = [
            ...     {"raw_name": "S/4HANA Cloud's", "context": "...", "domain_hint": None},
            ...     {"raw_name": "MFA", "context": "...", "domain_hint": None}
            ... ]
            >>> results = canonicalizer.canonicalize_batch(batch)
            >>> results[0].canonical_name
            "SAP S/4HANA Cloud"
        """
        if not concepts:
            return []

        logger.debug(
            f"[LLMCanonicalizer:Batch] Canonicalizing batch of {len(concepts)} concepts"
        )

        # Construire prompt batch
        prompt = self._build_batch_canonicalization_prompt(concepts)

        try:
            # P0: Appel LLM via circuit breaker
            def _llm_call():
                from knowbase.common.llm_router import TaskType

                # Appel LLM via router
                response_content = self.llm_router.complete(
                    task_type=TaskType.CANONICALIZATION,
                    messages=[
                        {"role": "system", "content": CANONICALIZATION_BATCH_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,
                    max_tokens=8000,  # Fix 2025-10-21: Batch de 20 concepts nécessite ~4000 tokens
                    response_format={"type": "json_object"}
                )

                # Fix 2025-10-21: Diagnostic + strip whitespace
                logger.info(
                    f"[LLMCanonicalizer:Batch] 🔍 RAW LLM response "
                    f"(type={type(response_content)}, len={len(response_content if response_content else '')}):\n"
                    f"{response_content[:1000] if response_content else '(EMPTY)'}"
                )

                # Strip whitespace before parsing
                response_content = response_content.strip() if response_content else ""

                if not response_content:
                    raise ValueError("LLM returned empty response")

                # Parse résultat JSON
                result_json = self._parse_json_robust(response_content)

                # Extraire résultats pour chaque concept
                results = []
                concepts_results = result_json.get("concepts", [])

                for idx, concept_result in enumerate(concepts_results):
                    try:
                        results.append(CanonicalizationResult(**concept_result))
                    except Exception as e:
                        logger.error(
                            f"[LLMCanonicalizer:Batch] Failed to parse result {idx}: {e}, "
                            f"using fallback for '{concepts[idx]['raw_name']}'"
                        )
                        # Fallback pour ce concept
                        results.append(CanonicalizationResult(
                            canonical_name=concepts[idx]["raw_name"].strip().title(),
                            confidence=0.5,
                            reasoning="Batch parsing failed, fallback to title case",
                            aliases=[],
                            concept_type="Unknown",
                            domain=None,
                            ambiguity_warning="Batch canonicalization partial failure",
                            possible_matches=[],
                            metadata={"error": str(e)}
                        ))

                return results

            # Appel via circuit breaker
            results = self.circuit_breaker.call(_llm_call)

            logger.info(
                f"[LLMCanonicalizer:Batch] ✅ Batch completed: {len(results)} concepts canonicalized"
            )

            return results

        except CircuitBreakerOpenError as cb_err:
            # Circuit breaker ouvert → fallback pour TOUS les concepts
            logger.warning(
                f"[LLMCanonicalizer:Batch] ⚠️ Circuit breaker OPEN, "
                f"falling back to title case for {len(concepts)} concepts"
            )

            return [
                CanonicalizationResult(
                    canonical_name=concept["raw_name"].strip().title(),
                    confidence=0.5,
                    reasoning=f"Circuit breaker open: {str(cb_err)}",
                    aliases=[],
                    concept_type="Unknown",
                    domain=None,
                    ambiguity_warning="LLM service temporarily unavailable",
                    possible_matches=[],
                    metadata={"error": "circuit_breaker_open"}
                )
                for concept in concepts
            ]

        except Exception as e:
            logger.error(f"[LLMCanonicalizer:Batch] ❌ Batch canonicalization failed: {e}")

            # Fallback: retourner résultats basiques pour TOUS
            return [
                CanonicalizationResult(
                    canonical_name=concept["raw_name"].strip().title(),
                    confidence=0.5,
                    reasoning=f"Batch LLM error: {str(e)}",
                    aliases=[],
                    concept_type="Unknown",
                    domain=None,
                    ambiguity_warning="Batch canonicalization failed",
                    possible_matches=[],
                    metadata={"error": str(e)}
                )
                for concept in concepts
            ]

    async def canonicalize_batch_async(
        self,
        concepts: List[Dict[str, str]],
        timeout: int = 30
    ) -> List[CanonicalizationResult]:
        """
        Canonicalise un batch de concepts via LLM async (batch processing parallèle).

        Version async pour utilisation dans boucle événementielle asyncio.

        Args:
            concepts: Liste de dicts avec clés {raw_name, context, domain_hint}
            timeout: Timeout max LLM call en secondes

        Returns:
            Liste de CanonicalizationResult (même ordre que concepts)

        Example:
            >>> batch = [
            ...     {"raw_name": "S/4HANA Cloud's", "context": "...", "domain_hint": None},
            ...     {"raw_name": "MFA", "context": "...", "domain_hint": None}
            ... ]
            >>> results = await canonicalizer.canonicalize_batch_async(batch)
            >>> results[0].canonical_name
            "SAP S/4HANA Cloud"
        """
        if not concepts:
            return []

        logger.debug(
            f"[LLMCanonicalizer:BatchAsync] Canonicalizing batch of {len(concepts)} concepts"
        )

        # Construire prompt batch (même que sync)
        prompt = self._build_batch_canonicalization_prompt(concepts)

        try:
            # Appel LLM async via router
            from knowbase.common.llm_router import TaskType

            # Utiliser acomplete du router (version async)
            response_content = await self.llm_router.acomplete(
                task_type=TaskType.CANONICALIZATION,
                messages=[
                    {"role": "system", "content": CANONICALIZATION_BATCH_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=8000,
                response_format={"type": "json_object"}
            )

            # Log diagnostic
            logger.info(
                f"[LLMCanonicalizer:BatchAsync] 🔍 RAW LLM response "
                f"(type={type(response_content)}, len={len(response_content if response_content else '')}):\n"
                f"{response_content[:1000] if response_content else '(EMPTY)'}"
            )

            # Strip whitespace
            response_content = response_content.strip() if response_content else ""

            if not response_content:
                raise ValueError("LLM returned empty response")

            # Parse résultat JSON
            result_json = self._parse_json_robust(response_content)

            # Extraire résultats pour chaque concept
            results = []
            concepts_results = result_json.get("concepts", [])

            for idx, concept_result in enumerate(concepts_results):
                try:
                    results.append(CanonicalizationResult(**concept_result))
                except Exception as e:
                    logger.error(
                        f"[LLMCanonicalizer:BatchAsync] Failed to parse result {idx}: {e}, "
                        f"using fallback for '{concepts[idx]['raw_name']}'"
                    )
                    # Fallback pour ce concept
                    results.append(CanonicalizationResult(
                        canonical_name=concepts[idx]["raw_name"].strip().title(),
                        confidence=0.5,
                        reasoning="Batch parsing failed, fallback to title case",
                        aliases=[],
                        concept_type="Unknown",
                        domain=None,
                        ambiguity_warning="Batch canonicalization partial failure",
                        possible_matches=[],
                        metadata={"error": str(e)}
                    ))

            logger.info(
                f"[LLMCanonicalizer:BatchAsync] ✅ Batch completed: {len(results)} concepts canonicalized"
            )

            return results

        except Exception as e:
            logger.error(f"[LLMCanonicalizer:BatchAsync] ❌ Batch canonicalization failed: {e}")

            # Fallback: retourner résultats basiques pour TOUS
            return [
                CanonicalizationResult(
                    canonical_name=concept["raw_name"].strip().title(),
                    confidence=0.5,
                    reasoning=f"Batch LLM error: {str(e)}",
                    aliases=[],
                    concept_type="Unknown",
                    domain=None,
                    ambiguity_warning="Batch canonicalization failed",
                    possible_matches=[],
                    metadata={"error": str(e)}
                )
                for concept in concepts
            ]

    def _build_batch_canonicalization_prompt(
        self,
        concepts: List[Dict[str, str]]
    ) -> str:
        """Construit prompt batch pour LLM."""
        concept_lines = []

        for idx, concept in enumerate(concepts, 1):
            raw_name = concept.get("raw_name", "")
            context = concept.get("context", "")
            domain_hint = concept.get("domain_hint")

            line = f"{idx}. **Name:** {raw_name}"

            if context:
                context_snippet = self._truncate_context(context, max_length=200)
                line += f" | **Context:** {context_snippet}"

            if domain_hint:
                line += f" | **Domain:** {domain_hint}"

            concept_lines.append(line)

        concepts_text = "\n".join(concept_lines)

        return f"""
**Task:** Canonicalize the following {len(concepts)} concepts.

{concepts_text}

Return a JSON object with format:
{{
  "concepts": [
    {{"canonical_name": "...", "confidence": 0.95, "reasoning": "...", ...}},
    ...
  ]
}}

IMPORTANT: Return results in SAME ORDER as input (1-{len(concepts)}).
"""

    def _parse_json_robust(self, response_content: str) -> Dict[str, Any]:
        """
        Parse JSON de manière robuste avec fallback sur erreurs.

        Gère:
        - JSON valide standard
        - JSON avec trailing commas
        - JSON malformé → fallback valeurs par défaut

        Args:
            response_content: Réponse LLM (string JSON attendu)

        Returns:
            Dict parsé ou dict fallback si erreur
        """
        try:
            # Essai parsing JSON standard
            return json.loads(response_content)
        except json.JSONDecodeError as e:
            logger.warning(f"[LLMCanonicalizer] JSON parse error: {e}, attempting fixes...")

            # Tentative fix 1: Supprimer trailing commas
            try:
                import re
                # Supprimer virgules avant } ou ]
                fixed_json = re.sub(r',\s*([}\]])', r'\1', response_content)
                return json.loads(fixed_json)
            except json.JSONDecodeError:
                pass

            # Tentative fix 2: Extraire JSON d'un markdown code block
            try:
                import re
                # Chercher JSON dans ```json ... ``` ou ```...```
                match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_content, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
            except (json.JSONDecodeError, AttributeError):
                pass

            # Échec complet → lever exception pour trigger fallback
            logger.error(f"[LLMCanonicalizer] Failed to parse JSON after all attempts: {response_content[:200]}")
            raise json.JSONDecodeError("All JSON parsing attempts failed", response_content, 0)

    def _truncate_context(self, context: str, max_length: int = 500) -> str:
        """
        Tronque contexte intelligemment sans couper mots (P2.3).

        Args:
            context: Contexte original
            max_length: Longueur max caractères

        Returns:
            Contexte tronqué sans mots coupés
        """
        if len(context) <= max_length:
            return context

        # Tronquer à max_length, puis chercher dernier espace pour ne pas couper mot
        truncated = context[:max_length]

        # Trouver dernier espace/ponctuation
        last_space = max(
            truncated.rfind(' '),
            truncated.rfind('.'),
            truncated.rfind(','),
            truncated.rfind(';')
        )

        if last_space > 0:
            # Couper au dernier espace trouvé
            return truncated[:last_space] + "..."
        else:
            # Aucun espace trouvé, garder brut avec ...
            return truncated + "..."

    def _build_canonicalization_prompt(
        self,
        raw_name: str,
        context: Optional[str],
        domain_hint: Optional[str]
    ) -> str:
        """Construit prompt pour LLM."""

        parts = [
            f"**Concept Name:** {raw_name}",
        ]

        if context:
            # P2.3: Limiter contexte à 500 chars SANS couper mots
            context_snippet = self._truncate_context(context, max_length=500)
            parts.append(f"**Context:** {context_snippet}")

        if domain_hint:
            parts.append(f"**Domain Hint:** {domain_hint}")

        parts.append("\n**Task:** Find the official canonical name for this concept.")

        return "\n\n".join(parts)


# ═══════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════

CANONICALIZATION_SYSTEM_PROMPT = """You are a concept canonicalization expert.

Your task is to find the OFFICIAL CANONICAL NAME for concepts extracted from documents.

# Guidelines

1. **Official Names**: Use official product/company/standard names
   - Example: "S/4HANA Cloud's" → "SAP S/4HANA Cloud, Public Edition"
   - Example: "iPhone 15 Pro Max's camera" → "Apple iPhone 15 Pro Max"

2. **Acronyms**: Expand acronyms to full official names
   - Example: "SLA" → "Service Level Agreement"
   - Example: "CEE" → "Communauté Économique Européenne" (if French context)

3. **Possessives**: Remove possessive forms ('s, 's)
   - Example: "SAP's solution" → "SAP"

4. **Casing**: Preserve official casing
   - Acronyms: SAP, ERP, CRM (all caps)
   - Products: "SAP S/4HANA" (mixed case as official)

5. **Variants**: List common aliases/variants

6. **Ambiguity**: If uncertain, set ambiguity_warning and list possible_matches
   - Example: "S/4HANA Cloud" without context → could be Public OR Private Edition

7. **Type Detection**: Classify concept type
   - Product, Service, Organization, Acronym, Standard, Person, Location, etc.

# Output Format (JSON)

{
  "canonical_name": "Official canonical name",
  "confidence": 0.95,
  "reasoning": "Brief explanation of decision",
  "aliases": ["variant1", "variant2"],
  "concept_type": "Product|Acronym|Organization|...",
  "domain": "enterprise_software|legal|medical|...",
  "ambiguity_warning": "Warning if ambiguous or null",
  "possible_matches": ["Alternative1", "Alternative2"] or [],
  "metadata": {
    "vendor": "SAP",
    "version": "Cloud",
    "edition": "Public"
  }
}

# Examples

## Input: "S/4HANA Cloud's"
## Context: "Our public cloud ERP solution"
## Output:
{
  "canonical_name": "SAP S/4HANA Cloud, Public Edition",
  "confidence": 0.92,
  "reasoning": "Context mentions 'public cloud', official SAP product name",
  "aliases": ["S/4HANA Cloud Public", "S4 Cloud"],
  "concept_type": "Product",
  "domain": "enterprise_software",
  "ambiguity_warning": null,
  "possible_matches": [],
  "metadata": {"vendor": "SAP", "edition": "Public"}
}

## Input: "SLA"
## Context: "99.9% SLA guarantees"
## Output:
{
  "canonical_name": "Service Level Agreement",
  "confidence": 0.98,
  "reasoning": "Standard IT acronym",
  "aliases": ["SLA", "SLAs"],
  "concept_type": "Acronym",
  "domain": "it_operations",
  "ambiguity_warning": null,
  "possible_matches": [],
  "metadata": {}
}

## Input: "S/4HANA Cloud"
## Context: "We use S/4HANA Cloud for accounting"
## Output:
{
  "canonical_name": "SAP S/4HANA Cloud",
  "confidence": 0.65,
  "reasoning": "Cannot determine Public vs Private edition from context alone",
  "aliases": ["S/4HANA Cloud", "S4 Cloud"],
  "concept_type": "Product",
  "domain": "enterprise_software",
  "ambiguity_warning": "Cannot determine Public vs Private edition",
  "possible_matches": [
    "SAP S/4HANA Cloud, Public Edition",
    "SAP S/4HANA Cloud, Private Edition"
  ],
  "metadata": {"vendor": "SAP"}
}
"""

CANONICALIZATION_BATCH_SYSTEM_PROMPT = """You are a concept canonicalization expert specialized in batch processing.

Your task is to find the OFFICIAL CANONICAL NAME for multiple concepts extracted from documents.

# Guidelines (same as single canonicalization)

1. **Official Names**: Use official product/company/standard names
2. **Acronyms**: Expand acronyms to full official names
3. **Possessives**: Remove possessive forms ('s, 's)
4. **Casing**: Preserve official casing
5. **Variants**: List common aliases/variants
6. **Ambiguity**: If uncertain, set ambiguity_warning and list possible_matches
7. **Type Detection**: Classify concept type

# Batch Output Format (JSON)

{
  "concepts": [
    {
      "canonical_name": "Official name 1",
      "confidence": 0.95,
      "reasoning": "Brief explanation",
      "aliases": ["variant1", "variant2"],
      "concept_type": "Product|Acronym|...",
      "domain": "enterprise_software|...",
      "ambiguity_warning": null,
      "possible_matches": [],
      "metadata": {}
    },
    {
      "canonical_name": "Official name 2",
      ...
    }
  ]
}

CRITICAL: Return results in SAME ORDER as input concepts. The array "concepts" must have EXACTLY the same number of elements as the input.
"""
