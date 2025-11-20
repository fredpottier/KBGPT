"""
Résumé global de deck PPTX pour extraction de métadonnées.

Module extrait de pptx_pipeline.py pour réutilisabilité.
"""

from typing import List, Dict, Any, Optional
import logging

from knowbase.common.llm_router import LLMRouter, TaskType
from knowbase.config.prompts_loader import load_prompts, select_prompt, render_prompt
from ..utils.text_utils import recursive_chunk


def summarize_large_pptx(
    slides_data: List[Dict[str, Any]],
    document_type: str = "default",
    llm_router: Optional[LLMRouter] = None,
    logger: Optional[logging.Logger] = None
) -> str:
    """
    Résume un deck PPTX trop volumineux en plusieurs passes GPT.

    Args:
        slides_data: Liste des slides extraits
        document_type: Type de document (pour sélection de prompts)
        llm_router: Instance LLMRouter (créée si None)
        logger: Logger optionnel

    Returns:
        str: Résumé global du deck

    Note:
        Utilise un chunking récursif pour les très grands decks
    """
    if llm_router is None:
        llm_router = LLMRouter()

    all_text = "\n\n".join(
        (slide.get("text", "") + "\n" + slide.get("notes", "")).strip()
        for slide in slides_data
    )

    # Si trop long, chunker et résumer progressivement
    max_chunk_len = 8000  # tokens
    if len(all_text) > max_chunk_len * 4:  # estimation caractères
        chunks = recursive_chunk(all_text, max_len=max_chunk_len)

        if logger:
            logger.info(f"📄 Deck trop volumineux, découpage en {len(chunks)} chunks")

        partial_summaries = []
        for i, chunk in enumerate(chunks, 1):
            try:
                prompt = f"Résume le contenu suivant (partie {i}/{len(chunks)}):\n\n{chunk}"
                summary = llm_router.complete(
                    prompt=prompt,
                    task_type=TaskType.SUMMARIZATION,
                    max_tokens=500
                )
                partial_summaries.append(summary)
            except Exception as e:
                if logger:
                    logger.warning(f"⚠️ Erreur résumé chunk {i}: {e}")

        # Combiner les résumés partiels
        combined = "\n\n".join(partial_summaries)

        # Résumé final
        try:
            final_prompt = f"Synthétise ces résumés en un résumé global cohérent:\n\n{combined}"
            final_summary = llm_router.complete(
                prompt=final_prompt,
                task_type=TaskType.SUMMARIZATION,
                max_tokens=1000
            )
            return final_summary
        except Exception as e:
            if logger:
                logger.error(f"❌ Erreur résumé final: {e}")
            return combined[:2000]  # Fallback: retourner les premiers résumés

    else:
        # Deck de taille raisonnable, résumé direct
        try:
            prompt = f"Résume le contenu suivant:\n\n{all_text}"
            summary = llm_router.complete(
                prompt=prompt,
                task_type=TaskType.SUMMARIZATION,
                max_tokens=1000
            )
            return summary
        except Exception as e:
            if logger:
                logger.error(f"❌ Erreur résumé: {e}")
            return all_text[:2000]  # Fallback
