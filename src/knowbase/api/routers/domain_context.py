"""
Router API pour Domain Context.

Permet la configuration du contexte métier global de l'instance.
Ce contexte est injecté automatiquement dans tous les prompts LLM
pour améliorer la précision de l'extraction et de l'analyse.

Endpoints:
- GET /domain-context - Récupérer le contexte actuel
- POST /domain-context - Créer/mettre à jour le contexte
- DELETE /domain-context - Supprimer le contexte
- POST /domain-context/preview - Prévisualiser le prompt d'injection
"""

from fastapi import APIRouter, HTTPException, status
from datetime import datetime
import logging
import json
import re

from knowbase.api.schemas.domain_context import (
    DomainContextCreate,
    DomainContextResponse,
    DomainContextPreviewRequest,
    DomainContextPreviewResponse,
)
from knowbase.ontology.domain_context import DomainContextProfile
from knowbase.ontology.domain_context_store import get_domain_context_store
from knowbase.config.settings import get_settings
from knowbase.common.llm_router import LLMRouter, TaskType

settings = get_settings()
logger = logging.getLogger(__name__)

# LLM Router pour traduction
_llm_router = None

def get_local_llm_router() -> LLMRouter:
    """Utilise le singleton global du LLMRouter."""
    from knowbase.common.llm_router import get_llm_router as get_global_llm_router
    return get_global_llm_router()

router = APIRouter(prefix="/domain-context", tags=["domain-context"])

# Tenant ID fixe pour architecture "1 instance = 1 client"
DEFAULT_TENANT_ID = "default"


def _detect_language(text: str) -> str:
    """
    Détecte simplement si le texte est en français ou autre.
    Retourne 'fr', 'en', ou 'other'.
    """
    # Mots français courants pour détecter la langue
    french_indicators = [
        ' le ', ' la ', ' les ', ' des ', ' du ', ' de ', ' un ', ' une ',
        ' et ', ' ou ', ' pour ', ' dans ', ' sur ', ' avec ', ' qui ', ' que ',
        ' est ', ' sont ', ' nous ', ' notre ', ' votre ', ' cette ', ' ces ',
        "d'", "l'", "n'", "s'", "qu'",
        'é', 'è', 'ê', 'à', 'ù', 'ç', 'ô', 'î', 'û', 'ë', 'ï', 'ü'
    ]

    text_lower = text.lower()
    french_score = sum(1 for indicator in french_indicators if indicator in text_lower)

    if french_score >= 3:
        return 'fr'
    return 'en'


def _translate_content_to_english(
    domain_summary: str,
    sub_domains: list,
    key_concepts: list,
    common_acronyms: dict
) -> dict:
    """
    Traduit le contenu Domain Context en anglais via LLM si nécessaire.

    Returns:
        Dict avec les versions traduites
    """
    # Vérifier si traduction nécessaire
    content_to_check = f"{domain_summary} {' '.join(sub_domains)} {' '.join(key_concepts)}"
    detected_lang = _detect_language(content_to_check)

    if detected_lang == 'en':
        logger.debug("[DomainContext] Content already in English, skipping translation")
        return {
            'domain_summary': domain_summary,
            'sub_domains': sub_domains,
            'key_concepts': key_concepts,
            'common_acronyms': common_acronyms,
            'was_translated': False
        }

    logger.info(f"[DomainContext] Detected language: {detected_lang}, translating to English...")

    try:
        router = get_local_llm_router()

        # Préparer le contenu à traduire en un seul appel
        translation_input = {
            "domain_summary": domain_summary,
            "sub_domains": sub_domains,
            "key_concepts": key_concepts,
            # Les acronymes: traduire seulement les expansions, pas les clés
            "acronym_expansions": list(common_acronyms.values()) if common_acronyms else []
        }

        messages = [
            {
                "role": "system",
                "content": """You are a professional translator. Translate the provided JSON content from French to English.
Keep the same JSON structure. Translate only the text values, not the keys.
For technical terms, products, or proper nouns, keep them as-is or use their official English equivalent.
Return ONLY valid JSON, no explanations."""
            },
            {
                "role": "user",
                "content": f"Translate this to English:\n{json.dumps(translation_input, ensure_ascii=False)}"
            }
        ]

        response = router.complete(
            task_type=TaskType.TRANSLATION,
            messages=messages,
            temperature=0.1,
            max_tokens=2000
        )

        # Parser la réponse JSON
        # Nettoyer la réponse (enlever ```json si présent)
        cleaned_response = response.strip()
        if cleaned_response.startswith("```"):
            cleaned_response = re.sub(r'^```\w*\n?', '', cleaned_response)
            cleaned_response = re.sub(r'\n?```$', '', cleaned_response)

        translated = json.loads(cleaned_response)

        # Reconstruire les acronymes avec les expansions traduites
        translated_acronyms = {}
        if common_acronyms and 'acronym_expansions' in translated:
            acronym_keys = list(common_acronyms.keys())
            translated_expansions = translated.get('acronym_expansions', [])
            for i, key in enumerate(acronym_keys):
                if i < len(translated_expansions):
                    translated_acronyms[key] = translated_expansions[i]
                else:
                    translated_acronyms[key] = common_acronyms[key]
        else:
            translated_acronyms = common_acronyms

        logger.info("[DomainContext] Translation successful")

        return {
            'domain_summary': translated.get('domain_summary', domain_summary),
            'sub_domains': translated.get('sub_domains', sub_domains),
            'key_concepts': translated.get('key_concepts', key_concepts),
            'common_acronyms': translated_acronyms,
            'was_translated': True
        }

    except Exception as e:
        logger.warning(f"[DomainContext] Translation failed, using original content: {e}")
        return {
            'domain_summary': domain_summary,
            'sub_domains': sub_domains,
            'key_concepts': key_concepts,
            'common_acronyms': common_acronyms,
            'was_translated': False
        }


def _generate_prompt_via_llm(
    industry_label: str,
    domain_summary: str,
    sub_domains: list,
    key_concepts: list,
    common_acronyms: dict,
    context_priority: str,
    versioning_hints: str = "",
    identification_semantics: str = "",
) -> str:
    """
    Utilise un LLM pour générer un prompt d'injection structuré et intelligent.

    Le LLM analyse les données du domaine et produit un prompt optimisé
    pour contextualiser les extractions futures.

    Args:
        industry_label: Label lisible de l'industrie
        domain_summary: Résumé du domaine métier
        sub_domains: Liste des sous-domaines
        key_concepts: Liste des concepts clés
        common_acronyms: Dict acronymes → expansions
        context_priority: low/medium/high

    Returns:
        Prompt d'injection généré par le LLM
    """
    router = get_local_llm_router()

    # Token budget selon priorité
    token_budgets = {
        "low": 150,
        "medium": 300,
        "high": 500
    }
    max_tokens = token_budgets.get(context_priority, 300)

    # Préparer les données d'entrée
    domain_data = {
        "industry": industry_label,
        "business_summary": domain_summary,
        "sub_domains": sub_domains,
        "key_concepts": key_concepts,
        "acronyms": common_acronyms,
    }
    if versioning_hints:
        domain_data["versioning_hints"] = versioning_hints
    # identification_semantics est passé en paramètre mais injecté directement
    # dans le DomainContextInjector, pas dans le prompt de génération LLM
    if identification_semantics:
        domain_data["identification_semantics"] = identification_semantics

    system_prompt = """You are an expert prompt engineer. Your task is to generate a DOMAIN CONTEXT prompt that will be injected into other LLM prompts to help them better understand and process domain-specific documents.

The generated prompt must:
1. Start with [DOMAIN CONTEXT - {Industry}]
2. Be structured with clear sections (not a wall of text)
3. Include INTERPRETATION RULES that tell the LLM how to handle domain terminology
4. Group acronyms semantically by category (e.g., Regulatory, Clinical, Safety, etc.)
5. Highlight what to prioritize when extracting information
6. Be actionable and specific, not generic

Format to follow:
```
[DOMAIN CONTEXT - {Industry}]

INTERPRETATION RULES:
- Rule 1 about how to interpret specific terminology
- Rule 2 about disambiguation
- Rule 3 about priorities

DOMAIN VOCABULARY:
• Category1: ACRONYM1 (expansion), ACRONYM2 (expansion)
• Category2: ACRONYM3 (expansion), ACRONYM4 (expansion)

KEY CONCEPTS: concept1, concept2, concept3

BUSINESS CONTEXT: {summary}

EXTRACTION FOCUS: What to prioritize when analyzing documents
```

Output ONLY the prompt, no explanations. Keep it under {max_tokens} tokens."""

    user_prompt = f"""Generate a domain context injection prompt from this data:

{json.dumps(domain_data, indent=2, ensure_ascii=False)}

Priority level: {context_priority}
Maximum tokens: {max_tokens}

Remember: Output ONLY the structured prompt, nothing else."""

    messages = [
        {"role": "system", "content": system_prompt.replace("{max_tokens}", str(max_tokens))},
        {"role": "user", "content": user_prompt}
    ]

    try:
        response = router.complete(
            task_type=TaskType.TRANSLATION,  # Réutilise le même type pour cohérence
            messages=messages,
            temperature=0.3,  # Un peu de créativité mais reste cohérent
            max_tokens=max_tokens + 100  # Marge pour le formatage
        )

        generated_prompt = response.strip()

        # Nettoyer si le LLM a ajouté des backticks
        if generated_prompt.startswith("```"):
            generated_prompt = re.sub(r'^```\w*\n?', '', generated_prompt)
            generated_prompt = re.sub(r'\n?```$', '', generated_prompt)

        logger.info(f"[DomainContext] LLM-generated prompt: {len(generated_prompt)} chars")
        return generated_prompt

    except Exception as e:
        logger.error(f"[DomainContext] LLM prompt generation failed: {e}")
        # Fallback vers template simple
        return (
            f"[DOMAIN CONTEXT - {industry_label}]\n\n"
            f"BUSINESS CONTEXT: {domain_summary}\n\n"
            f"KEY DOMAINS: {', '.join(sub_domains[:5])}\n\n"
            f"KEY CONCEPTS: {', '.join(key_concepts[:8])}\n\n"
            "Use this context to correctly interpret domain-specific terminology."
        )


def _generate_llm_injection_prompt(
    domain_summary: str,
    industry: str,
    sub_domains: list,
    common_acronyms: dict,
    key_concepts: list,
    context_priority: str,
    auto_translate: bool = True,
    versioning_hints: str = "",
    identification_semantics: str = "",
) -> tuple[str, bool]:
    """
    Génère le prompt d'injection LLM à partir des paramètres.

    Utilise un LLM pour générer un prompt structuré et intelligent,
    adapté au domaine métier spécifique.

    Priority levels:
    - low: Prompt simple généré par template (économie de coût)
    - medium: Prompt structuré généré par LLM (~300 tokens)
    - high: Prompt complet généré par LLM (~500 tokens)

    Args:
        auto_translate: Si True, traduit automatiquement le contenu en anglais

    Returns:
        Tuple (prompt, was_translated)
    """
    was_translated = False

    # Traduction automatique si activée
    if auto_translate:
        translated = _translate_content_to_english(
            domain_summary=domain_summary,
            sub_domains=sub_domains,
            key_concepts=key_concepts,
            common_acronyms=common_acronyms
        )
        domain_summary = translated['domain_summary']
        sub_domains = translated['sub_domains']
        key_concepts = translated['key_concepts']
        common_acronyms = translated['common_acronyms']
        was_translated = translated['was_translated']

    # Mapping industrie vers label anglais lisible
    industry_labels = {
        'healthcare': 'Healthcare',
        'pharma_clinical': 'Pharmaceutical & Clinical Research',
        'pharmaceutical': 'Pharmaceutical / Life Sciences',
        'clinical_research': 'Clinical Research',
        'finance': 'Finance / Banking',
        'insurance': 'Insurance',
        'retail': 'Retail / Commerce',
        'manufacturing': 'Manufacturing / Industry',
        'technology': 'Technology / IT',
        'energy': 'Energy',
        'logistics': 'Logistics / Transportation',
        'education': 'Education',
        'government': 'Government / Public Sector',
        'legal': 'Legal',
        'other': 'General',
    }
    industry_label = industry_labels.get(industry, industry.replace('_', ' ').title())

    # === LOW PRIORITY: Template simple (pas de coût LLM) ===
    if context_priority == "low":
        prompt = (
            f"[DOMAIN CONTEXT - {industry_label}]\n\n"
            f"BUSINESS CONTEXT: {domain_summary}\n\n"
            "Use this context to interpret domain-specific terminology."
        )
        return prompt, was_translated

    # === MEDIUM/HIGH PRIORITY: Génération LLM intelligente ===
    prompt = _generate_prompt_via_llm(
        industry_label=industry_label,
        domain_summary=domain_summary,
        sub_domains=sub_domains,
        key_concepts=key_concepts,
        common_acronyms=common_acronyms,
        context_priority=context_priority,
        versioning_hints=versioning_hints,
        identification_semantics=identification_semantics,
    )

    return prompt, was_translated


def _estimate_tokens(text: str) -> int:
    """Estime le nombre de tokens (approximation: 4 chars = 1 token)."""
    return len(text) // 4


@router.get(
    "",
    response_model=DomainContextResponse,
    summary="Récupérer le Domain Context",
    description="Retourne le contexte métier configuré pour cette instance."
)
async def get_domain_context():
    """Récupère le Domain Context actuel."""
    try:
        store = get_domain_context_store()
        profile = store.get_profile(DEFAULT_TENANT_ID)

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aucun Domain Context configuré. Utilisez POST /domain-context pour en créer un."
            )

        return DomainContextResponse(
            tenant_id=profile.tenant_id,
            domain_summary=profile.domain_summary,
            industry=profile.industry,
            sub_domains=profile.sub_domains,
            target_users=profile.target_users,
            document_types=profile.document_types,
            common_acronyms=profile.common_acronyms,
            key_concepts=profile.key_concepts,
            context_priority=profile.context_priority,
            versioning_hints=profile.versioning_hints,
            identification_semantics=profile.identification_semantics,
            axis_reclassification_rules=profile.axis_reclassification_rules,
            llm_injection_prompt=profile.llm_injection_prompt,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DomainContext] Error getting context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du contexte: {str(e)}"
        )


@router.post(
    "",
    response_model=DomainContextResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer/Mettre à jour le Domain Context",
    description="Configure le contexte métier global. Si un contexte existe déjà, il sera remplacé."
)
async def create_or_update_domain_context(data: DomainContextCreate):
    """Crée ou met à jour le Domain Context."""
    try:
        # Générer le prompt d'injection (avec traduction auto si contenu non-anglais)
        llm_injection_prompt, was_translated = _generate_llm_injection_prompt(
            domain_summary=data.domain_summary,
            industry=data.industry,
            sub_domains=data.sub_domains,
            common_acronyms=data.common_acronyms,
            key_concepts=data.key_concepts,
            context_priority=data.context_priority,
            auto_translate=True,
            versioning_hints=data.versioning_hints,
            identification_semantics=data.identification_semantics,
        )

        if was_translated:
            logger.info("[DomainContext] Content was auto-translated to English for LLM injection")

        # Créer le profil
        now = datetime.utcnow()
        profile = DomainContextProfile(
            tenant_id=DEFAULT_TENANT_ID,
            domain_summary=data.domain_summary,
            industry=data.industry,
            sub_domains=data.sub_domains,
            target_users=data.target_users,
            document_types=data.document_types,
            common_acronyms=data.common_acronyms,
            key_concepts=data.key_concepts,
            context_priority=data.context_priority,
            versioning_hints=data.versioning_hints,
            identification_semantics=data.identification_semantics,
            axis_reclassification_rules=data.axis_reclassification_rules,
            llm_injection_prompt=llm_injection_prompt,
            created_at=now,
            updated_at=now,
        )

        # Sauvegarder
        store = get_domain_context_store()
        store.save_profile(profile)

        logger.info(f"[DomainContext] Context saved: industry={data.industry}")

        return DomainContextResponse(
            tenant_id=profile.tenant_id,
            domain_summary=profile.domain_summary,
            industry=profile.industry,
            sub_domains=profile.sub_domains,
            target_users=profile.target_users,
            document_types=profile.document_types,
            common_acronyms=profile.common_acronyms,
            key_concepts=profile.key_concepts,
            context_priority=profile.context_priority,
            versioning_hints=profile.versioning_hints,
            identification_semantics=profile.identification_semantics,
            axis_reclassification_rules=profile.axis_reclassification_rules,
            llm_injection_prompt=profile.llm_injection_prompt,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    except Exception as e:
        logger.error(f"[DomainContext] Error saving context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la sauvegarde du contexte: {str(e)}"
        )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer le Domain Context",
    description="Supprime le contexte métier. L'instance reviendra en mode générique (domain-agnostic)."
)
async def delete_domain_context():
    """Supprime le Domain Context."""
    try:
        store = get_domain_context_store()
        deleted = store.delete_profile(DEFAULT_TENANT_ID)

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aucun Domain Context à supprimer."
            )

        logger.info("[DomainContext] Context deleted")
        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DomainContext] Error deleting context: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression du contexte: {str(e)}"
        )


@router.post(
    "/preview",
    response_model=DomainContextPreviewResponse,
    summary="Prévisualiser le prompt d'injection",
    description="Génère un aperçu du prompt qui sera injecté dans les LLM sans sauvegarder."
)
async def preview_injection_prompt(data: DomainContextPreviewRequest):
    """Prévisualise le prompt d'injection LLM."""
    logger.info(
        f"[DomainContext] Preview request: priority={data.context_priority}, "
        f"sub_domains={len(data.sub_domains)}, key_concepts={len(data.key_concepts)}, "
        f"acronyms={len(data.common_acronyms)}"
    )
    llm_injection_prompt, was_translated = _generate_llm_injection_prompt(
        domain_summary=data.domain_summary,
        industry=data.industry,
        sub_domains=data.sub_domains,
        common_acronyms=data.common_acronyms,
        key_concepts=data.key_concepts,
        context_priority=data.context_priority,
        auto_translate=True,
        versioning_hints=data.versioning_hints,
        identification_semantics=data.identification_semantics,
    )

    if was_translated:
        logger.info("[DomainContext] Preview: content was auto-translated to English")

    return DomainContextPreviewResponse(
        llm_injection_prompt=llm_injection_prompt,
        estimated_tokens=_estimate_tokens(llm_injection_prompt)
    )
