"""
🌊 OSMOSE Phase 1.8 - Document Context Generator

Génère un contexte document global pour améliorer l'extraction de concepts.

Résout le problème:
- Extraction incomplète: "S/4HANA Cloud" vs "SAP S/4HANA Cloud, Private Edition"
- Ambiguïtés: "CRM" peut être Salesforce, Microsoft Dynamics, ou SAP CRM selon contexte
- Acronymes non résolus: Besoin du contexte document pour expansion

Architecture:
- Génération contexte VIA LLM léger (gpt-4o-mini)
- Cache par document_id (évite régénération)
- Contexte contient: titre principal, thèmes dominants, acronymes/entités majeures

Phase 1.8 Sprint 1.8.1 - T1.8.1.0 (P0.1 CRITICAL)
Author: OSMOSE Team
Date: 2025-11-20
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import logging
import json
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class DocumentContext(BaseModel):
    """
    Contexte document global pour guider extraction de concepts.

    Utilisé par ConceptExtractor et LLMCanonicalizer pour améliorer précision.
    """

    document_id: str = Field(..., description="ID unique du document")
    title: Optional[str] = Field(None, description="Titre principal identifié")
    main_topics: list[str] = Field(default_factory=list, description="Thèmes dominants (3-5)")
    key_entities: list[str] = Field(default_factory=list, description="Entités clés (produits, organisations)")
    dominant_acronyms: Dict[str, str] = Field(
        default_factory=dict,
        description="Acronymes dominants avec expansion (ex: 'CRM' -> 'Salesforce CRM')"
    )
    language: str = Field(default="en", description="Langue dominante détectée")
    domain_hint: Optional[str] = Field(None, description="Domaine métier (SAP, pharma, legal, etc.)")

    # Résumé compact pour injection dans prompts
    summary: str = Field(..., description="Résumé compact 200-500 chars")

    # Métadonnées
    generated_at: datetime = Field(default_factory=datetime.now)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confiance génération")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    def to_prompt_context(self) -> str:
        """
        Formate contexte pour injection dans prompt LLM.

        Returns:
            str: Contexte formaté pour injection prompt

        Example:
            >>> context = DocumentContext(document_id="doc-123", ...)
            >>> context.to_prompt_context()
            "DOCUMENT CONTEXT:\\nTitle: SAP S/4HANA Cloud Migration\\nMain Topics: cloud migration, ERP, SAP solutions\\nKey Entities: SAP S/4HANA Cloud Private Edition, SAP BTP\\nAcronyms: CRM=SAP Customer Relationship Management, BTP=Business Technology Platform"
        """
        parts = ["DOCUMENT CONTEXT:"]

        if self.title:
            parts.append(f"Title: {self.title}")

        if self.main_topics:
            parts.append(f"Main Topics: {', '.join(self.main_topics)}")

        if self.key_entities:
            parts.append(f"Key Entities: {', '.join(self.key_entities[:5])}")  # Top 5

        if self.dominant_acronyms:
            acronyms_str = ", ".join([f"{k}={v}" for k, v in list(self.dominant_acronyms.items())[:5]])
            parts.append(f"Acronyms: {acronyms_str}")

        if self.domain_hint:
            parts.append(f"Domain: {self.domain_hint}")

        return "\n".join(parts)

    def to_short_summary(self) -> str:
        """
        Génère résumé ultra-court pour logs/debugging.

        Returns:
            str: Résumé 1 ligne
        """
        topics = ", ".join(self.main_topics[:3]) if self.main_topics else "N/A"
        entities_count = len(self.key_entities)
        acronyms_count = len(self.dominant_acronyms)

        return (
            f"[Context: {self.title or 'Untitled'} | "
            f"Topics: {topics} | "
            f"Entities: {entities_count} | "
            f"Acronyms: {acronyms_count}]"
        )


class DocumentContextGenerator:
    """
    Générateur de contexte document global via LLM léger.

    Utilise gpt-4o-mini pour analyser le document et extraire:
    - Titre principal
    - Thèmes dominants
    - Entités clés (produits, organisations)
    - Acronymes fréquents avec expansion

    Cache automatique par document_id (TTL: 1 heure).
    """

    def __init__(self, llm_router, cache_ttl_seconds: int = 3600):
        """
        Initialise le générateur de contexte.

        Args:
            llm_router: LLMRouter pour appels LLM
            cache_ttl_seconds: TTL cache contexte (défaut: 1h)
        """
        self.llm_router = llm_router
        self.cache_ttl_seconds = cache_ttl_seconds

        # Cache simple: {document_id: (context, expiry_time)}
        self._cache: Dict[str, tuple[DocumentContext, datetime]] = {}

        logger.info(
            f"[DocumentContextGenerator] Initialized (cache_ttl={cache_ttl_seconds}s)"
        )

    async def generate_context(
        self,
        document_id: str,
        full_text: str,
        max_sample_length: int = 3000,
        force_regenerate: bool = False
    ) -> Optional[DocumentContext]:
        """
        Génère contexte document global via LLM.

        Stratégie:
        1. Vérifier cache (si non force_regenerate)
        2. Échantillonner texte (début + milieu + fin pour couvrir document)
        3. Appeler LLM avec prompt structuré
        4. Parser résultat JSON
        5. Stocker dans cache

        Args:
            document_id: ID unique document
            full_text: Texte complet du document
            max_sample_length: Longueur max échantillon pour LLM (défaut: 3000 chars)
            force_regenerate: Force régénération (ignore cache)

        Returns:
            DocumentContext ou None si erreur

        Example:
            >>> generator = DocumentContextGenerator(llm_router)
            >>> context = await generator.generate_context(
            ...     document_id="doc-123",
            ...     full_text="SAP S/4HANA Cloud Private Edition is..."
            ... )
            >>> print(context.to_prompt_context())
        """
        # Vérifier cache
        if not force_regenerate and document_id in self._cache:
            cached_context, expiry = self._cache[document_id]

            if datetime.now() < expiry:
                logger.debug(
                    f"[DocumentContextGenerator] Cache HIT: {document_id} "
                    f"(expires in {(expiry - datetime.now()).seconds}s)"
                )
                return cached_context
            else:
                logger.debug(f"[DocumentContextGenerator] Cache EXPIRED: {document_id}")
                del self._cache[document_id]

        # Échantillonner texte (début + milieu + fin)
        sample_text = self._sample_text(full_text, max_sample_length)

        logger.info(
            f"[DocumentContextGenerator] Generating context for {document_id} "
            f"(text_len={len(full_text)}, sample_len={len(sample_text)})"
        )

        try:
            # Appel LLM
            context_data = await self._call_llm_for_context(sample_text)

            if not context_data:
                logger.warning(
                    f"[DocumentContextGenerator] Failed to generate context for {document_id}"
                )
                return None

            # Créer objet DocumentContext
            context = DocumentContext(
                document_id=document_id,
                **context_data
            )

            # Stocker dans cache
            expiry = datetime.now() + timedelta(seconds=self.cache_ttl_seconds)
            self._cache[document_id] = (context, expiry)

            logger.info(
                f"[DocumentContextGenerator] ✅ Context generated: {context.to_short_summary()}"
            )

            return context

        except Exception as e:
            logger.error(
                f"[DocumentContextGenerator] Error generating context for {document_id}: {e}",
                exc_info=True
            )
            return None

    def _sample_text(self, full_text: str, max_length: int) -> str:
        """
        Échantillonne texte pour LLM (début + milieu + fin).

        Stratégie:
        - Si texte < max_length: retourner tel quel
        - Sinon: début (40%) + milieu (30%) + fin (30%)

        Args:
            full_text: Texte complet
            max_length: Longueur max échantillon

        Returns:
            str: Texte échantillonné
        """
        if len(full_text) <= max_length:
            return full_text

        # Découpage intelligent
        start_len = int(max_length * 0.4)
        middle_len = int(max_length * 0.3)
        end_len = int(max_length * 0.3)

        start = full_text[:start_len]
        middle_start = len(full_text) // 2 - middle_len // 2
        middle = full_text[middle_start:middle_start + middle_len]
        end = full_text[-end_len:]

        sample = f"{start}\n\n[...middle section...]\n\n{middle}\n\n[...end section...]\n\n{end}"

        logger.debug(
            f"[DocumentContextGenerator] Sampled text: {len(full_text)} → {len(sample)} chars"
        )

        return sample

    async def _call_llm_for_context(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Appel LLM pour génération contexte document.

        Args:
            text: Texte échantillonné

        Returns:
            Dict avec champs DocumentContext ou None si erreur
        """
        prompt = self._build_context_extraction_prompt(text)

        try:
            from knowbase.common.llm_router import TaskType

            # Appel LLM async
            response_text = await self.llm_router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {
                        "role": "system",
                        "content": DOCUMENT_CONTEXT_SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.0,  # Déterministe
                response_format={"type": "json_object"},
                max_tokens=1000
            )

            # Parser JSON
            context_data = self._parse_json_robust(response_text)

            if not context_data:
                logger.warning("[DocumentContextGenerator] Failed to parse LLM response")
                return None

            # Valider champs requis
            required_fields = ["title", "main_topics", "key_entities", "summary"]
            for field in required_fields:
                if field not in context_data:
                    logger.warning(
                        f"[DocumentContextGenerator] Missing required field: {field}"
                    )
                    return None

            # Ajouter champs optionnels avec valeurs par défaut
            context_data.setdefault("dominant_acronyms", {})
            context_data.setdefault("language", "en")
            context_data.setdefault("domain_hint", None)
            context_data.setdefault("confidence", 0.85)

            return context_data

        except Exception as e:
            logger.error(f"[DocumentContextGenerator] LLM call failed: {e}", exc_info=True)
            return None

    def _build_context_extraction_prompt(self, text: str) -> str:
        """
        Construit prompt pour extraction contexte document.

        Args:
            text: Texte échantillonné

        Returns:
            str: Prompt formaté
        """
        return f"""Analyze the following document and extract a global context summary.

Document text:
{text}

Extract the following information:
1. **title**: Main title or subject of the document (1-100 chars)
2. **main_topics**: 3-5 dominant themes or topics
3. **key_entities**: Important entities (products, companies, technologies) mentioned frequently
4. **dominant_acronyms**: Common acronyms WITH their expansions (e.g., "CRM" -> "Customer Relationship Management" or "SAP CRM" if specified)
5. **language**: Dominant language (en, fr, de, es, etc.)
6. **domain_hint**: Business domain if identifiable (enterprise_software, healthcare, finance, legal, etc.)
7. **summary**: Compact summary in 200-500 characters explaining the document's purpose

Focus on:
- FULL product names (not abbreviations): "SAP S/4HANA Cloud Private Edition" not "S/4HANA Cloud"
- Acronym disambiguation: Prefer full expansions found in the text
- Domain-specific vocabulary: Capture technical terms, product names, methodologies

Return ONLY a JSON object with this structure:
{{
  "title": "...",
  "main_topics": ["topic1", "topic2", "topic3"],
  "key_entities": ["entity1", "entity2", ...],
  "dominant_acronyms": {{"ACRONYM": "Full Expansion", ...}},
  "language": "en",
  "domain_hint": "enterprise_software",
  "summary": "This document discusses...",
  "confidence": 0.9
}}"""

    def _parse_json_robust(self, response_text: str) -> Optional[Dict[str, Any]]:
        """
        Parse JSON robuste depuis réponse LLM.

        Supporte:
        - JSON avec texte avant/après
        - Code blocks markdown
        - JSON malformé (tentative correction)

        Args:
            response_text: Réponse LLM brute

        Returns:
            Dict parsé ou None si échec
        """
        try:
            # Nettoyer code blocks markdown
            response_text = re.sub(r'```json\s*', '', response_text)
            response_text = re.sub(r'```\s*', '', response_text)

            # Chercher JSON dans la réponse
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                logger.warning("[DocumentContextGenerator] No JSON found in response")
                return None

            json_str = json_match.group(0)
            data = json.loads(json_str)

            return data

        except json.JSONDecodeError as e:
            logger.error(f"[DocumentContextGenerator] JSON parse error: {e}")
            return None
        except Exception as e:
            logger.error(f"[DocumentContextGenerator] Error parsing response: {e}")
            return None

    def get_cached_context(self, document_id: str) -> Optional[DocumentContext]:
        """
        Récupère contexte depuis cache (si disponible et valide).

        Args:
            document_id: ID document

        Returns:
            DocumentContext ou None
        """
        if document_id in self._cache:
            context, expiry = self._cache[document_id]

            if datetime.now() < expiry:
                logger.debug(f"[DocumentContextGenerator] Cache HIT: {document_id}")
                return context
            else:
                logger.debug(f"[DocumentContextGenerator] Cache EXPIRED: {document_id}")
                del self._cache[document_id]

        return None

    def clear_cache(self, document_id: Optional[str] = None):
        """
        Vide cache (tout ou document spécifique).

        Args:
            document_id: Si fourni, vide seulement ce document. Sinon vide tout.
        """
        if document_id:
            if document_id in self._cache:
                del self._cache[document_id]
                logger.info(f"[DocumentContextGenerator] Cache cleared: {document_id}")
        else:
            self._cache.clear()
            logger.info("[DocumentContextGenerator] Cache cleared (all)")


# ═══════════════════════════════════════════════════
# PROMPT SYSTEM
# ═══════════════════════════════════════════════════

DOCUMENT_CONTEXT_SYSTEM_PROMPT = """You are a document analysis expert specialized in extracting global context summaries.

Your role:
- Analyze documents to identify main themes, key entities, and acronyms
- Extract FULL product names and technical terms (not abbreviations)
- Disambiguate acronyms using context (e.g., "CRM" could be Salesforce CRM, Microsoft Dynamics CRM, or SAP CRM)
- Identify the business domain (SAP, pharma, legal, finance, etc.)

Guidelines:
- ALWAYS prefer full names: "SAP S/4HANA Cloud Private Edition" not "S/4HANA Cloud"
- For acronyms: Use the expansion found in the text, or specify the vendor if mentioned (e.g., "CRM" -> "SAP Customer Relationship Management")
- Extract 3-5 main topics maximum
- List 5-10 key entities maximum
- Summary should be 200-500 characters

Output ONLY valid JSON. No explanations."""


# ═══════════════════════════════════════════════════
# FACTORY PATTERN
# ═══════════════════════════════════════════════════

_generator_instance: Optional[DocumentContextGenerator] = None


def get_document_context_generator(
    llm_router,
    cache_ttl_seconds: int = 3600
) -> DocumentContextGenerator:
    """
    Récupère instance singleton du générateur.

    Args:
        llm_router: LLMRouter pour appels LLM
        cache_ttl_seconds: TTL cache (défaut: 1h)

    Returns:
        DocumentContextGenerator instance
    """
    global _generator_instance

    if _generator_instance is None:
        _generator_instance = DocumentContextGenerator(
            llm_router=llm_router,
            cache_ttl_seconds=cache_ttl_seconds
        )

    return _generator_instance


__all__ = [
    "DocumentContext",
    "DocumentContextGenerator",
    "get_document_context_generator"
]
