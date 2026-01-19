"""
DomainContextExtractor - Extraction LLM

Extrait un profil contexte métier structuré depuis description textuelle libre.
Utilise LLM pour parsing intelligent et structuration.
"""

from typing import Optional
import logging
import json

from knowbase.ontology.domain_context import DomainContextProfile
from knowbase.common.llm_router import LLMRouter, TaskType, get_llm_router

logger = logging.getLogger(__name__)


DOMAIN_CONTEXT_EXTRACTION_PROMPT = """You are a domain context extraction expert.

Your task is to analyze a free-text description of a business domain and extract a structured profile.

# Input
User will provide a free-text description (2-500 words) of their business domain, including:
- Industry/sector
- Products/services
- Common acronyms
- User profiles
- Document types

# Output Format (JSON)

Return a JSON object with the following structure:

{
  "domain_summary": "1-2 sentence summary of the domain",
  "industry": "primary_industry (e.g., enterprise_software, pharmaceutical, retail, manufacturing, finance)",
  "sub_domains": ["sub-domain1", "sub-domain2"],
  "target_users": ["user_profile1", "user_profile2"],
  "document_types": ["type1", "type2"],
  "common_acronyms": {
    "ACRONYM1": "Full Expansion 1",
    "ACRONYM2": "Full Expansion 2"
  },
  "key_concepts": ["concept1", "concept2"],
  "context_priority": "low|medium|high",
  "llm_injection_prompt": "Contextual prompt for injection in other LLM calls"
}

# Guidelines

1. **domain_summary**: Concise 1-2 sentence summary
2. **industry**: Use standard industry codes (lowercase, underscore-separated)
3. **sub_domains**: Extract 2-10 sub-domains mentioned
4. **target_users**: Extract 1-5 user profiles mentioned
5. **document_types**: Extract 1-5 document types mentioned
6. **common_acronyms**: Extract ONLY acronyms EXPLICITLY mentioned by user (max 20)
   - DO NOT invent acronyms
   - Use exact expansions provided by user
7. **key_concepts**: Extract 3-10 key products/services/concepts mentioned
8. **context_priority**:
   - "high" if very specific domain with many acronyms/concepts
   - "medium" if moderate specificity
   - "low" if vague/generic description
9. **llm_injection_prompt**: Write a 50-150 word prompt that will be injected in other LLM system prompts
   - Start with: "You are analyzing documents from [domain]..."
   - Include key products/services
   - Include common acronyms and their meanings
   - Mention typical use cases
   - Keep neutral, factual tone

# Example

## Input:
"We are a pharmaceutical R&D company. Our documents concern clinical trials, drug development, and FDA approvals. Common acronyms: API (Active Pharmaceutical Ingredient), GMP (Good Manufacturing Practice), IND (Investigational New Drug). Main users are researchers and regulatory affairs teams."

## Output:
{
  "domain_summary": "Pharmaceutical R&D company focusing on clinical trials, drug development, and regulatory compliance",
  "industry": "pharmaceutical",
  "sub_domains": ["clinical_trials", "drug_development", "regulatory_affairs"],
  "target_users": ["researchers", "regulatory_affairs_teams"],
  "document_types": ["clinical_trial_protocols", "regulatory_submissions"],
  "common_acronyms": {
    "API": "Active Pharmaceutical Ingredient",
    "GMP": "Good Manufacturing Practice",
    "IND": "Investigational New Drug"
  },
  "key_concepts": ["Clinical Trials", "Drug Development", "FDA Approval", "Active Pharmaceutical Ingredient"],
  "context_priority": "high",
  "llm_injection_prompt": "You are analyzing documents from a pharmaceutical R&D organization. Focus areas include clinical trials, drug development, and FDA regulatory compliance. Common acronyms: API (Active Pharmaceutical Ingredient), GMP (Good Manufacturing Practice), IND (Investigational New Drug). When you encounter these acronyms, interpret them in pharmaceutical context unless clearly indicated otherwise. Typical document types include clinical trial protocols and regulatory submissions."
}

Now extract the domain context from the user's description.
"""


class DomainContextExtractor:
    """
    Extracteur LLM pour profil contexte métier.

    Convertit description textuelle libre en profil structuré DomainContextProfile.
    """

    def __init__(self, llm_router: Optional[LLMRouter] = None):
        """
        Initialise extracteur.

        Args:
            llm_router: LLMRouter instance (optionnel, créé si None)
        """
        self.llm_router = llm_router or get_llm_router()

    async def extract_from_text(
        self,
        user_text: str,
        tenant_id: str
    ) -> DomainContextProfile:
        """
        Extrait profil structuré depuis texte libre utilisateur.

        Args:
            user_text: Description libre du domaine métier (2-500 mots)
            tenant_id: ID tenant

        Returns:
            DomainContextProfile structuré

        Raises:
            ValueError: Si texte trop court/long ou extraction échoue

        Example:
            >>> extractor = DomainContextExtractor()
            >>> text = "We are SAP sales team. Docs about S/4HANA, SuccessFactors..."
            >>> profile = await extractor.extract_from_text(text, "sap_sales")
            >>> print(profile.common_acronyms)
            {"SAC": "SAP Analytics Cloud", ...}
        """
        # Validation input
        if len(user_text.strip()) < 10:
            raise ValueError(
                "user_text too short (min 10 characters). "
                "Provide a meaningful description of your business domain."
            )

        if len(user_text.strip()) > 5000:
            raise ValueError(
                "user_text too long (max 5000 characters). "
                "Please provide a concise description."
            )

        logger.info(
            f"[DomainContextExtractor] Extracting profile for tenant '{tenant_id}' "
            f"from {len(user_text)} chars"
        )

        # Appel LLM (synchrone, exécuté dans thread pool)
        try:
            import asyncio
            response = await asyncio.to_thread(
                self.llm_router.complete,
                task_type=TaskType.METADATA_EXTRACTION,  # Extraction structurée JSON
                messages=[
                    {"role": "system", "content": DOMAIN_CONTEXT_EXTRACTION_PROMPT},
                    {"role": "user", "content": f"User description:\n\n{user_text}"}
                ],
                temperature=0.0,  # Déterministe
                max_tokens=1500
            )

            # Parse JSON response
            extracted_data = self._parse_llm_response(response)

            # Créer DomainContextProfile
            profile = DomainContextProfile(
                tenant_id=tenant_id,
                domain_summary=extracted_data["domain_summary"],
                industry=extracted_data["industry"],
                sub_domains=extracted_data.get("sub_domains", []),
                target_users=extracted_data.get("target_users", []),
                document_types=extracted_data.get("document_types", []),
                common_acronyms=extracted_data.get("common_acronyms", {}),
                key_concepts=extracted_data.get("key_concepts", []),
                context_priority=extracted_data.get("context_priority", "medium"),
                llm_injection_prompt=extracted_data["llm_injection_prompt"]
            )

            logger.info(
                f"[DomainContextExtractor] ✅ Profile extracted: "
                f"industry={profile.industry}, "
                f"priority={profile.context_priority}, "
                f"{len(profile.common_acronyms)} acronyms, "
                f"{len(profile.key_concepts)} concepts"
            )

            return profile

        except Exception as e:
            logger.error(
                f"[DomainContextExtractor] ❌ Extraction failed: {e}",
                exc_info=True
            )
            raise ValueError(f"Failed to extract domain context: {e}")

    def _parse_llm_response(self, response: str) -> dict:
        """
        Parse réponse LLM JSON.

        Args:
            response: Réponse LLM (devrait contenir JSON)

        Returns:
            Dict avec données extraites

        Raises:
            ValueError: Si parsing JSON échoue
        """
        try:
            # Extraire JSON depuis réponse (au cas où LLM ajoute texte avant/après)
            start_idx = response.find("{")
            end_idx = response.rfind("}") + 1

            if start_idx == -1 or end_idx == 0:
                raise ValueError("No JSON object found in LLM response")

            json_str = response[start_idx:end_idx]
            data = json.loads(json_str)

            # Validation champs requis
            required_fields = ["domain_summary", "industry", "llm_injection_prompt"]
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")

            return data

        except json.JSONDecodeError as e:
            logger.error(
                f"[DomainContextExtractor] JSON parse error: {e}\n"
                f"Response: {response[:500]}"
            )
            raise ValueError(f"Invalid JSON in LLM response: {e}")


# Fonction helper pour usage simple
async def extract_domain_context(
    user_text: str,
    tenant_id: str,
    llm_router: Optional[LLMRouter] = None
) -> DomainContextProfile:
    """
    Helper function: extrait profil domaine depuis texte libre.

    Args:
        user_text: Description libre domaine métier
        tenant_id: ID tenant
        llm_router: LLMRouter instance (optionnel)

    Returns:
        DomainContextProfile structuré

    Example:
        >>> profile = await extract_domain_context(
        ...     "We are a SAP sales team...",
        ...     "sap_sales"
        ... )
    """
    extractor = DomainContextExtractor(llm_router)
    return await extractor.extract_from_text(user_text, tenant_id)


__all__ = ["DomainContextExtractor", "extract_domain_context"]
