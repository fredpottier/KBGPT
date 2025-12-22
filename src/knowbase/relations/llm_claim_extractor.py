# Phase 2.11 OSMOSE - LLM Claim Extractor
# Extraction d'assertions unaires (Subject → Attribut = Valeur)

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ulid import ULID

from .types import (
    ClaimValueType,
    RawClaim,
    RawClaimFlags,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Prompts V1 - Extraction Claims
# =============================================================================

CLAIM_EXTRACTION_SYSTEM_PROMPT = """Tu es un expert en extraction d'informations factuelles depuis des documents techniques.

Ta tâche : Extraire les CLAIMS (assertions de faits) depuis un texte.

Un CLAIM est une information UNAIRE : un SUJET possède un ATTRIBUT avec une VALEUR.

## Exemples de Claims

| Texte | Sujet | Type | Valeur |
|-------|-------|------|--------|
| "Le SLA de S/4HANA est 99.7%" | S/4HANA | SLA_AVAILABILITY | 99.7% |
| "RAM minimum : 64 Go" | [contexte] | THRESHOLD | 64 Go |
| "CRR Q4 2023 = 92%" | CRR | METRIC | 92% |
| "Prix : 500€/user/mois" | [contexte] | PRICING | 500€/user/mois |
| "Certifié ISO 27001" | [contexte] | CERTIFICATION | ISO 27001 |
| "Version actuelle : 2024.1" | [contexte] | VERSION | 2024.1 |
| "Temps de réponse < 200ms" | [contexte] | SLA_RESPONSE_TIME | < 200ms |

## Types de Claims Reconnus

- SLA_AVAILABILITY : Disponibilité garantie (percentage)
- SLA_RESPONSE_TIME : Temps de réponse garanti (duration)
- THRESHOLD : Seuil technique (number)
- PRICING : Tarification (currency)
- VERSION : Version actuelle (version)
- CAPACITY : Capacité maximale (number)
- CERTIFICATION : Certification obtenue (text)
- METRIC : Métrique business quantitative (number/percentage)
- FEATURE_FLAG : Disponibilité d'une feature (boolean)
- COMPATIBILITY : Compatibilité système (text)

## SCOPE : Contexte d'Applicabilité

Le scope qualifie QUAND/OÙ le claim s'applique.

Exemples de scope_struct :
- "avec le package premium" → {"package": "premium"}
- "en région Europe" → {"region": "Europe"}
- "depuis la version 2.0" → {"version": "2.0+"}
- "édition Enterprise" → {"edition": "Enterprise"}
- "pour les clients Gold" → {"tier": "Gold"}

Si pas de scope explicite → scope_struct: {}

## FLAGS à Détecter

- negated: assertion négative ("n'est PAS 99%", "ne supporte pas")
- hedged: incertitude ("environ", "approximativement", "jusqu'à")
- conditional: condition explicite ("si option X activée", "quand configuré")
- ambiguous_scope: scope pas clairement défini

## NE PAS Extraire

- Relations entre deux concepts (utiliser extraction relations)
- Opinions ou jugements subjectifs ("excellent", "performant")
- Informations génériques sans valeur précise mesurable
- Phrases purement descriptives sans assertion quantifiable

## Format de Sortie

Retourne un JSON avec la structure suivante :
```json
{
  "claims": [
    {
      "subject_concept_id": "string (ID du catalogue ou UNKNOWN)",
      "subject_surface_form": "texte original",
      "claim_type": "SLA_AVAILABILITY|THRESHOLD|PRICING|...",
      "value_raw": "99.7%",
      "value_type": "percentage|number|currency|boolean|text|duration|version|date",
      "scope_raw": "texte libre du contexte",
      "scope_struct": {"key": "value"},
      "valid_time_hint": "Q4 2023 ou null",
      "evidence": "citation exacte du texte source",
      "confidence": 0.0-1.0,
      "flags": {
        "negated": false,
        "hedged": false,
        "conditional": false,
        "ambiguous_scope": false
      }
    }
  ]
}
```
"""

CLAIM_EXTRACTION_USER_PROMPT = """## Catalogue de Concepts Disponibles

{catalogue_json}

## Texte à Analyser

{text}

## Instructions

Extrais les claims factuels (assertions unaires) du texte ci-dessus.

Pour chaque claim trouvé :
1. Identifie le sujet (concept du catalogue ou UNKNOWN si non trouvé)
2. Détermine le type de claim approprié
3. Extrait la valeur brute et son type
4. Parse le scope si présent
5. Note l'indication temporelle si présente
6. Évalue ta confiance

Retourne UNIQUEMENT le JSON, sans texte avant ou après.
"""


# =============================================================================
# Dataclasses Extraction
# =============================================================================

@dataclass
class ExtractedClaimV1:
    """Claim extrait par le LLM avant transformation en RawClaim"""
    subject_concept_id: str
    subject_surface_form: str
    claim_type: str
    value_raw: str
    value_type: str
    scope_raw: str = ""
    scope_struct: Dict[str, str] = field(default_factory=dict)
    valid_time_hint: Optional[str] = None
    evidence: str = ""
    confidence: float = 0.7
    flags: Dict[str, bool] = field(default_factory=dict)


@dataclass
class ClaimExtractionResult:
    """Résultat complet d'une extraction de claims"""
    claims: List[RawClaim]
    raw_response: str
    extraction_time_seconds: float
    model_used: str
    prompt_hash: str
    errors: List[str] = field(default_factory=list)


# =============================================================================
# Utilitaires
# =============================================================================

def compute_scope_key(scope_struct: Dict[str, str]) -> str:
    """Calcule un hash canonique du scope_struct pour groupement."""
    if not scope_struct:
        return "default"
    # Tri des clés pour stabilité
    sorted_items = sorted(scope_struct.items())
    canonical = json.dumps(sorted_items, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(canonical.encode()).hexdigest()[:12]


def compute_claim_fingerprint(
    tenant_id: str,
    doc_id: str,
    subject_id: str,
    claim_type: str,
    scope_key: str,
    value_raw: str,
) -> str:
    """Calcule le fingerprint unique d'un claim pour déduplication."""
    parts = [tenant_id, doc_id, subject_id, claim_type, scope_key, value_raw]
    combined = "|".join(parts)
    return hashlib.sha1(combined.encode()).hexdigest()


def parse_value_type(value_type_str: str) -> ClaimValueType:
    """Parse le value_type string en enum."""
    mapping = {
        "percentage": ClaimValueType.PERCENTAGE,
        "number": ClaimValueType.NUMBER,
        "currency": ClaimValueType.CURRENCY,
        "boolean": ClaimValueType.BOOLEAN,
        "text": ClaimValueType.TEXT,
        "duration": ClaimValueType.DURATION,
        "version": ClaimValueType.VERSION,
        "date": ClaimValueType.DATE,
    }
    return mapping.get(value_type_str.lower(), ClaimValueType.TEXT)


def extract_numeric_value(value_raw: str, value_type: ClaimValueType) -> Optional[float]:
    """Extrait la valeur numérique si applicable."""
    if value_type not in (ClaimValueType.PERCENTAGE, ClaimValueType.NUMBER, ClaimValueType.CURRENCY):
        return None

    # Patterns pour extraction numérique
    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*%",           # 99.7%
        r"(\d+(?:[.,]\d+)?)\s*(?:€|\$|£)",  # 500€
        r"(?:€|\$|£)\s*(\d+(?:[.,]\d+)?)",  # €500
        r"[<>≤≥]?\s*(\d+(?:[.,]\d+)?)",     # < 200, ≥ 64
        r"(\d+(?:[.,]\d+)?)",               # Simple number
    ]

    for pattern in patterns:
        match = re.search(pattern, value_raw)
        if match:
            num_str = match.group(1).replace(",", ".")
            try:
                return float(num_str)
            except ValueError:
                continue
    return None


def extract_unit(value_raw: str, value_type: ClaimValueType) -> Optional[str]:
    """Extrait l'unité de la valeur."""
    if value_type == ClaimValueType.PERCENTAGE:
        return "%"

    # Patterns pour unités courantes
    unit_patterns = [
        (r"\d+\s*(Go|GB|Mo|MB|To|TB)", "storage"),
        (r"\d+\s*(ms|s|min|h|j|days?|hours?)", "time"),
        (r"(€|EUR|\$|USD|£|GBP)", "currency"),
        (r"\d+\s*(users?|utilisateurs?)", "count"),
    ]

    for pattern, _ in unit_patterns:
        match = re.search(pattern, value_raw, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


# =============================================================================
# Extracteur Principal
# =============================================================================

class LLMClaimExtractor:
    """
    Extracteur de claims utilisant un LLM (Phase 2.11).

    Extrait les assertions unaires (Subject → Attribut = Valeur) depuis du texte.
    """

    def __init__(
        self,
        llm_client: Any,
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        tenant_id: str = "default",
    ):
        self.llm_client = llm_client
        self.model = model
        self.temperature = temperature
        self.tenant_id = tenant_id
        self.extractor_version = "v1.0.0"

    def _build_catalogue_json(self, concepts: List[Dict[str, Any]]) -> str:
        """Construit le JSON du catalogue pour le prompt."""
        if not concepts:
            return "[]"

        # Format simplifié pour le prompt
        catalogue = []
        for c in concepts[:50]:  # Limite pour token budget
            catalogue.append({
                "id": c.get("concept_id", c.get("id", "UNKNOWN")),
                "name": c.get("name", c.get("label", "")),
                "type": c.get("type", "GENERIC"),
            })

        return json.dumps(catalogue, ensure_ascii=False, indent=2)

    def _parse_llm_response(self, response_text: str) -> List[ExtractedClaimV1]:
        """Parse la réponse JSON du LLM en claims."""
        claims = []

        # Extraction du JSON
        try:
            # Cherche le JSON dans la réponse
            json_match = re.search(r'\{[\s\S]*"claims"[\s\S]*\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(response_text)

            for item in data.get("claims", []):
                claim = ExtractedClaimV1(
                    subject_concept_id=item.get("subject_concept_id", "UNKNOWN"),
                    subject_surface_form=item.get("subject_surface_form", ""),
                    claim_type=item.get("claim_type", "UNKNOWN"),
                    value_raw=item.get("value_raw", ""),
                    value_type=item.get("value_type", "text"),
                    scope_raw=item.get("scope_raw", ""),
                    scope_struct=item.get("scope_struct", {}),
                    valid_time_hint=item.get("valid_time_hint"),
                    evidence=item.get("evidence", ""),
                    confidence=item.get("confidence", 0.7),
                    flags=item.get("flags", {}),
                )
                claims.append(claim)

        except json.JSONDecodeError as e:
            logger.warning(f"[OSMOSE] Claim extraction JSON parse error: {e}")
        except Exception as e:
            logger.error(f"[OSMOSE] Claim extraction error: {e}")

        return claims

    def _convert_to_raw_claims(
        self,
        extracted: List[ExtractedClaimV1],
        doc_id: str,
        chunk_id: str,
        segment_id: Optional[str] = None,
        model_used: Optional[str] = None,
    ) -> List[RawClaim]:
        """Convertit les claims extraits en RawClaim."""
        raw_claims = []

        for ec in extracted:
            value_type = parse_value_type(ec.value_type)
            scope_key = compute_scope_key(ec.scope_struct)

            fingerprint = compute_claim_fingerprint(
                tenant_id=self.tenant_id,
                doc_id=doc_id,
                subject_id=ec.subject_concept_id,
                claim_type=ec.claim_type,
                scope_key=scope_key,
                value_raw=ec.value_raw,
            )

            flags = RawClaimFlags(
                negated=ec.flags.get("negated", False),
                hedged=ec.flags.get("hedged", False),
                conditional=ec.flags.get("conditional", False),
                ambiguous_scope=ec.flags.get("ambiguous_scope", False),
            )

            raw_claim = RawClaim(
                raw_claim_id=str(ULID()),
                tenant_id=self.tenant_id,
                raw_fingerprint=fingerprint,
                subject_concept_id=ec.subject_concept_id,
                subject_surface_form=ec.subject_surface_form or None,
                claim_type=ec.claim_type,
                value_raw=ec.value_raw,
                value_type=value_type,
                value_numeric=extract_numeric_value(ec.value_raw, value_type),
                unit=extract_unit(ec.value_raw, value_type),
                scope_raw=ec.scope_raw,
                scope_struct=ec.scope_struct,
                scope_key=scope_key,
                valid_time_hint=ec.valid_time_hint,
                source_doc_id=doc_id,
                source_chunk_id=chunk_id,
                source_segment_id=segment_id,
                evidence_text=ec.evidence,
                confidence=ec.confidence,
                flags=flags,
                extractor_name="llm_claim_extractor",
                extractor_version=self.extractor_version,
                model_used=model_used or self.model,
            )
            raw_claims.append(raw_claim)

        return raw_claims

    async def extract_claims(
        self,
        text: str,
        doc_id: str,
        chunk_id: str,
        concepts: List[Dict[str, Any]],
        segment_id: Optional[str] = None,
    ) -> ClaimExtractionResult:
        """
        Extrait les claims depuis un texte.

        Args:
            text: Texte à analyser
            doc_id: ID du document source
            chunk_id: ID du chunk
            concepts: Catalogue de concepts disponibles
            segment_id: ID du segment optionnel

        Returns:
            ClaimExtractionResult avec les RawClaims extraits
        """
        import time
        start_time = time.time()
        errors = []

        # Construction du prompt
        catalogue_json = self._build_catalogue_json(concepts)
        user_prompt = CLAIM_EXTRACTION_USER_PROMPT.format(
            catalogue_json=catalogue_json,
            text=text,
        )

        # Hash du prompt pour traçabilité
        prompt_hash = hashlib.sha1(
            (CLAIM_EXTRACTION_SYSTEM_PROMPT + user_prompt).encode()
        ).hexdigest()[:12]

        # Appel LLM
        try:
            response = await self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": CLAIM_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )

            raw_response = response.choices[0].message.content or ""
            model_used = response.model

        except Exception as e:
            logger.error(f"[OSMOSE] LLM claim extraction failed: {e}")
            errors.append(str(e))
            return ClaimExtractionResult(
                claims=[],
                raw_response="",
                extraction_time_seconds=time.time() - start_time,
                model_used=self.model,
                prompt_hash=prompt_hash,
                errors=errors,
            )

        # Parse response
        extracted = self._parse_llm_response(raw_response)

        # Convert to RawClaims
        raw_claims = self._convert_to_raw_claims(
            extracted=extracted,
            doc_id=doc_id,
            chunk_id=chunk_id,
            segment_id=segment_id,
            model_used=model_used,
        )

        extraction_time = time.time() - start_time
        logger.info(
            f"[OSMOSE] Extracted {len(raw_claims)} claims from chunk {chunk_id} "
            f"in {extraction_time:.2f}s"
        )

        return ClaimExtractionResult(
            claims=raw_claims,
            raw_response=raw_response,
            extraction_time_seconds=extraction_time,
            model_used=model_used,
            prompt_hash=prompt_hash,
            errors=errors,
        )

    def extract_claims_sync(
        self,
        text: str,
        doc_id: str,
        chunk_id: str,
        concepts: List[Dict[str, Any]],
        segment_id: Optional[str] = None,
    ) -> ClaimExtractionResult:
        """Version synchrone de extract_claims."""
        import asyncio
        return asyncio.run(self.extract_claims(
            text=text,
            doc_id=doc_id,
            chunk_id=chunk_id,
            concepts=concepts,
            segment_id=segment_id,
        ))


# =============================================================================
# Factory
# =============================================================================

_claim_extractor_instance: Optional[LLMClaimExtractor] = None


def get_claim_extractor(
    llm_client: Any = None,
    model: str = "gpt-4o-mini",
    tenant_id: str = "default",
) -> LLMClaimExtractor:
    """Factory pour obtenir un extracteur de claims."""
    global _claim_extractor_instance

    if _claim_extractor_instance is None or llm_client is not None:
        if llm_client is None:
            raise ValueError("llm_client required for first initialization")
        _claim_extractor_instance = LLMClaimExtractor(
            llm_client=llm_client,
            model=model,
            tenant_id=tenant_id,
        )

    return _claim_extractor_instance
