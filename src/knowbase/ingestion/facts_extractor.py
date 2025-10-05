"""
Module extraction facts structurés depuis slides PPTX.

Utilise LLM Vision (GPT-4 Vision / Claude 3.5 Sonnet) pour extraire
facts métier mesurables (SLA, capacity, pricing, compliance) depuis
texte + images slides.
"""

from __future__ import annotations

import json
from typing import List, Dict, Any, Optional
from pathlib import Path

from pydantic import ValidationError

from knowbase.api.schemas.facts import FactCreate, FactType, ValueType
from knowbase.common.llm_router import LLMRouter, TaskType
from knowbase.common.logging import setup_logging
from knowbase.config.prompts_loader import select_prompt, render_prompt
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "facts_extractor.log")


async def extract_facts_from_slide(
    slide_data: Dict[str, Any],
    slide_image_base64: Optional[str],
    source_document: str,
    chunk_id: str,
    deck_summary: str = "",
    llm_router: Optional[LLMRouter] = None,
) -> List[FactCreate]:
    """
    Extrait facts structurés depuis un slide PPTX via LLM Vision.

    Args:
        slide_data: Dict contenant texte slide (text, notes, megaparse_content, slide_index)
        slide_image_base64: Image slide encodée base64 (optionnel)
        source_document: Nom document source (ex: "proposal_2024_q1.pptx")
        chunk_id: UUID chunk Qdrant pour traçabilité
        deck_summary: Résumé global deck pour contexte
        llm_router: Instance LLMRouter (créée si None)

    Returns:
        List[FactCreate]: Facts extraits validés Pydantic
    """

    # Init LLM Router si non fourni
    if llm_router is None:
        llm_router = LLMRouter()

    # Récupérer prompt depuis config
    try:
        prompt_config = select_prompt("facts", "extract_pptx")
    except Exception as e:
        logger.error(f"❌ Prompt 'facts.extract_pptx' introuvable: {e}")
        return []

    # Construire contexte prompt
    slide_number = slide_data.get("slide_index", 0)
    megaparse_content = slide_data.get("megaparse_content", "")
    text = slide_data.get("text", "")
    notes = slide_data.get("notes", "")

    # Rendu prompt avec variables
    context = {
        "slide_number": slide_number,
        "source_document": source_document,
        "megaparse_content": megaparse_content or text,  # Fallback si MegaParse absent
        "text": text,
        "notes": notes or "Aucune note",
        "image_attached": "Oui (analyse visuelle requise)" if slide_image_base64 else "Non",
        "deck_summary": deck_summary or "Non disponible",
    }

    system_prompt = render_prompt(prompt_config["system"], context)
    user_prompt = render_prompt(prompt_config["user"], context)

    # Construire messages pour LLM Vision
    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # Ajouter image si disponible (format multi-modal)
    if slide_image_base64:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{slide_image_base64}",
                        "detail": "high"  # Analyse détaillée pour tableaux/diagrammes
                    }
                }
            ]
        })
    else:
        # Texte seul
        messages.append({
            "role": "user",
            "content": user_prompt
        })

    # Appel LLM Vision
    try:
        logger.debug(f"🔍 Extraction facts slide {slide_number} ({source_document})")

        response = await llm_router.route(
            task_type=TaskType.VISION if slide_image_base64 else TaskType.CHAT,
            messages=messages,
            response_format={"type": "json_object"},  # Force JSON
            temperature=0.0,  # Déterministe pour extraction
            max_tokens=3000,
        )

        # Parser JSON réponse
        response_text = response.get("content", "")
        facts_raw = json.loads(response_text)

        # Valider structure {"facts": [...]}
        if not isinstance(facts_raw, dict) or "facts" not in facts_raw:
            logger.warning(f"⚠️ Réponse LLM sans clé 'facts': {response_text[:200]}")
            return []

        facts_list = facts_raw.get("facts", [])

        if not facts_list:
            logger.debug(f"✅ Slide {slide_number}: 0 facts extraits (slide vide/générique)")
            return []

        # Valider et enrichir facts avec Pydantic
        validated_facts = []

        for i, fact_data in enumerate(facts_list, 1):
            try:
                # Enrichir métadonnées traçabilité
                fact_enriched = {
                    **fact_data,
                    "source_chunk_id": chunk_id,
                    "source_document": source_document,
                    "extraction_method": "llm_vision" if slide_image_base64 else "llm_text",
                    "extraction_model": response.get("model", "unknown"),
                    "extraction_prompt_id": prompt_config.get("id", "extract_facts_pptx_v1"),
                }

                # Normaliser fact_type si absent
                if "fact_type" not in fact_enriched:
                    fact_enriched["fact_type"] = FactType.GENERAL

                # Normaliser value_type si absent
                if "value_type" not in fact_enriched:
                    # Inférer depuis type Python de value
                    value = fact_enriched.get("value")
                    if isinstance(value, (int, float)):
                        fact_enriched["value_type"] = ValueType.NUMERIC
                    elif isinstance(value, bool):
                        fact_enriched["value_type"] = ValueType.BOOLEAN
                    else:
                        fact_enriched["value_type"] = ValueType.TEXT

                # Validation Pydantic
                fact = FactCreate(**fact_enriched)
                validated_facts.append(fact)

                logger.debug(
                    f"  ✅ Fact {i}/{len(facts_list)}: {fact.subject} | "
                    f"{fact.predicate} = {fact.value}{fact.unit} "
                    f"(confidence: {fact.confidence:.2f})"
                )

            except ValidationError as e:
                logger.warning(
                    f"  ⚠️ Fact {i} validation échouée: {e.errors()[0]['msg']} | "
                    f"Data: {fact_data}"
                )
                continue
            except Exception as e:
                logger.error(f"  ❌ Erreur fact {i}: {e} | Data: {fact_data}")
                continue

        logger.info(
            f"✅ Slide {slide_number}: {len(validated_facts)}/{len(facts_list)} facts validés "
            f"({source_document})"
        )

        return validated_facts

    except json.JSONDecodeError as e:
        logger.warning(
            f"⚠️ Slide {slide_number}: JSON invalide LLM - {e} | "
            f"Response: {response.get('content', '')[:300]}"
        )
        return []

    except Exception as e:
        logger.error(
            f"❌ Slide {slide_number}: Extraction échouée - {e.__class__.__name__}: {e}"
        )
        return []


async def insert_facts_to_neo4j(
    facts: List[FactCreate],
    tenant_id: str = "default",
) -> List[str]:
    """
    Insère facts dans Neo4j avec status='proposed'.

    Args:
        facts: Liste facts à insérer
        tenant_id: ID tenant pour multi-tenancy

    Returns:
        List[str]: UUIDs facts insérés avec succès
    """
    from knowbase.api.services.facts_service import FactsService

    if not facts:
        logger.debug("✅ Aucun fact à insérer")
        return []

    facts_service = FactsService(tenant_id=tenant_id)
    inserted_uuids = []

    for fact in facts:
        try:
            fact_response = facts_service.create_fact(fact)
            inserted_uuids.append(fact_response.uuid)

            logger.info(
                f"  ✅ Fact inserted: {fact_response.uuid[:8]}... | "
                f"{fact.subject} → {fact.predicate} = {fact.value}{fact.unit}"
            )

        except Exception as e:
            logger.error(
                f"  ❌ Insertion échouée: {e.__class__.__name__} | "
                f"{fact.subject} → {fact.predicate}"
            )
            continue

    success_rate = len(inserted_uuids) / len(facts) * 100 if facts else 0
    logger.info(
        f"📊 Facts insérés: {len(inserted_uuids)}/{len(facts)} "
        f"({success_rate:.1f}% success)"
    )

    return inserted_uuids


async def detect_and_log_conflicts(
    inserted_fact_uuids: List[str],
    tenant_id: str = "default",
    threshold_pct: float = 0.05,
) -> List[Dict[str, Any]]:
    """
    Détecte conflits pour facts nouvellement insérés.

    Args:
        inserted_fact_uuids: UUIDs facts à vérifier
        tenant_id: ID tenant
        threshold_pct: Seuil différence critique (default 5%)

    Returns:
        List[Dict]: Conflits critiques détectés
    """
    from knowbase.api.services.facts_service import FactsService

    if not inserted_fact_uuids:
        logger.debug("✅ Aucun fact à vérifier pour conflits")
        return []

    facts_service = FactsService(tenant_id=tenant_id)

    try:
        # Détection globale conflits
        all_conflicts = facts_service.detect_conflicts()

        # Filtrer conflits impliquant facts nouvellement insérés
        relevant_conflicts = [
            c for c in all_conflicts
            if c.fact_proposed.uuid in inserted_fact_uuids
        ]

        if not relevant_conflicts:
            logger.info("✅ Aucun conflit détecté pour nouveaux facts")
            return []

        # Filtrer conflits critiques (> seuil)
        critical_conflicts = [
            c for c in relevant_conflicts
            if c.value_diff_pct > threshold_pct
        ]

        # Logger conflits
        for conflict in relevant_conflicts:
            emoji = "🚨" if conflict.value_diff_pct > threshold_pct else "⚠️"
            logger.warning(
                f"{emoji} CONFLICT {conflict.conflict_type} | "
                f"{conflict.fact_proposed.subject} → {conflict.fact_proposed.predicate} | "
                f"Proposed: {conflict.fact_proposed.value}{conflict.fact_proposed.unit} | "
                f"Approved: {conflict.fact_approved.value}{conflict.fact_approved.unit} | "
                f"Diff: {conflict.value_diff_pct * 100:.1f}%"
            )

        logger.info(
            f"📊 Conflits détectés: {len(relevant_conflicts)} total, "
            f"{len(critical_conflicts)} critiques (>{threshold_pct*100}%)"
        )

        # Convertir en dict pour notification
        return [
            {
                "conflict_type": c.conflict_type,
                "value_diff_pct": c.value_diff_pct,
                "fact_proposed": {
                    "uuid": c.fact_proposed.uuid,
                    "subject": c.fact_proposed.subject,
                    "predicate": c.fact_proposed.predicate,
                    "value": c.fact_proposed.value,
                    "unit": c.fact_proposed.unit,
                },
                "fact_approved": {
                    "uuid": c.fact_approved.uuid,
                    "subject": c.fact_approved.subject,
                    "predicate": c.fact_approved.predicate,
                    "value": c.fact_approved.value,
                    "unit": c.fact_approved.unit,
                },
            }
            for c in critical_conflicts
        ]

    except Exception as e:
        logger.error(f"❌ Détection conflits échouée: {e}")
        return []


__all__ = [
    "extract_facts_from_slide",
    "insert_facts_to_neo4j",
    "detect_and_log_conflicts",
]
