"""
DomainContextInjector - Middleware Injection

Injecte automatiquement le contexte métier dans tous les prompts LLM du système.
"""

from typing import Optional
import logging

from knowbase.ontology.domain_context_store import get_domain_context_store

logger = logging.getLogger(__name__)


class DomainContextInjector:
    """
    Middleware injection contexte métier dans prompts LLM.

    Récupère profil contexte pour un tenant et l'injecte automatiquement
    dans les prompts système LLM.
    """

    def __init__(self):
        """Initialise injector avec store."""
        self.store = get_domain_context_store()

    def inject_context(
        self,
        base_prompt: str,
        tenant_id: str = "default"
    ) -> str:
        """
        Injecte contexte métier dans prompt LLM.

        Args:
            base_prompt: Prompt système générique (domain-agnostic)
            tenant_id: ID tenant (défaut: "default")

        Returns:
            Prompt enrichi avec contexte métier si disponible, sinon prompt original

        Example:
            >>> injector = DomainContextInjector()
            >>> base = "You are a concept canonicalization expert..."
            >>> enriched = injector.inject_context(base, "sap_sales")
            >>> print(enriched)
            # → Prompt original + section [DOMAIN CONTEXT]
        """
        # Récupérer profil contexte
        profile = self.store.get_profile(tenant_id)

        # Si pas de profil ou priorité low, retourner prompt original
        if not profile:
            logger.debug(
                f"[DomainContextInjector] No profile for tenant '{tenant_id}', "
                "using generic prompt"
            )
            return base_prompt

        if profile.context_priority == "low":
            logger.debug(
                f"[DomainContextInjector] Priority LOW for tenant '{tenant_id}', "
                "skipping injection"
            )
            return base_prompt

        # Construire section contexte métier
        context_section = self._build_context_section(profile)

        # Injecter à la fin du prompt système
        enriched_prompt = base_prompt + "\n\n" + context_section

        logger.info(
            f"[DomainContextInjector] ✅ Context injected for tenant '{tenant_id}' "
            f"(priority={profile.context_priority}, industry={profile.industry})"
        )

        return enriched_prompt

    def _build_context_section(self, profile) -> str:
        """
        Construit section contexte métier pour injection.

        Args:
            profile: DomainContextProfile

        Returns:
            Texte section formatée
        """
        # Format acronymes
        acronyms_text = ""
        if profile.common_acronyms:
            acronyms_list = [
                f"- {acronym}: {expansion}"
                for acronym, expansion in list(profile.common_acronyms.items())[:15]  # Max 15
            ]
            acronyms_text = "\n".join(acronyms_list)

        # Format concepts clés
        concepts_text = ""
        if profile.key_concepts:
            concepts_text = ", ".join(profile.key_concepts[:10])  # Max 10

        # Construire section complète
        section = f"""[DOMAIN CONTEXT - Priority: {profile.context_priority.upper()}]
{profile.llm_injection_prompt}"""

        if acronyms_text:
            section += f"""

Common acronyms in this domain:
{acronyms_text}"""

        if concepts_text:
            section += f"""

Key concepts to recognize:
{concepts_text}"""

        section += """
[END DOMAIN CONTEXT]"""

        return section


# Instance singleton (usage simple)
_injector_instance: Optional[DomainContextInjector] = None


def get_domain_context_injector() -> DomainContextInjector:
    """
    Retourne instance singleton de l'injector.

    Returns:
        DomainContextInjector instance

    Example:
        >>> injector = get_domain_context_injector()
        >>> enriched = injector.inject_context(base_prompt, "sap_sales")
    """
    global _injector_instance

    if _injector_instance is None:
        _injector_instance = DomainContextInjector()

    return _injector_instance


__all__ = ["DomainContextInjector", "get_domain_context_injector"]
