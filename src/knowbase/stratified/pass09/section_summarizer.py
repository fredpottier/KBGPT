"""
OSMOSE Pipeline V2 - Pass 0.9 Section Summarizer
=================================================
Résume chaque section du document via LLM.
"""

import asyncio
import logging
import threading
from typing import Dict, List, Optional, Tuple

from knowbase.stratified.pass09.models import Pass09Config, SectionSummary

logger = logging.getLogger(__name__)


# Prompt pour le résumé de section
SECTION_SUMMARY_SYSTEM_PROMPT = """Tu es un expert en analyse documentaire pour OSMOSE.
Tu dois produire un résumé INFORMATIF d'une section de document technique.

RÈGLES:
- Maximum {max_chars} caractères pour le résumé
- Identifier les CONCEPTS clés mentionnés (termes techniques, entités)
- Noter les TYPES d'assertions présentes (definitional, prescriptive, factual, procedural)
- Préserver les VALEURS spécifiques (versions, pourcentages, limites, durées)
- NE PAS interpréter, seulement résumer fidèlement le contenu
- Utiliser un style neutre et factuel"""

SECTION_SUMMARY_USER_PROMPT = """SECTION: {section_title}
NIVEAU: {level} (1=chapitre principal, 2=sous-section, 3=sous-sous-section, etc.)

CONTENU:
{section_text}

Réponds avec ce JSON (et UNIQUEMENT ce JSON, sans markdown):
{{
  "summary": "Résumé de la section (max {max_chars} chars)",
  "concepts": ["concept1", "concept2", "concept3"],
  "assertion_types": ["definitional", "prescriptive", "factual"],
  "key_values": ["TLS 1.2", "99.95%", "30 days"]
}}"""


class SectionSummarizer:
    """Résume les sections du document via LLM."""

    def __init__(
        self,
        llm_client,
        config: Optional[Pass09Config] = None,
    ):
        """
        Initialise le SectionSummarizer.

        Args:
            llm_client: Client LLM (OpenAI, vLLM, etc.)
            config: Configuration Pass 0.9
        """
        self.llm_client = llm_client
        self.config = config or Pass09Config()
        self._stats_lock = threading.Lock()
        self._stats = {
            "sections_processed": 0,
            "sections_skipped": 0,
            "sections_verbatim": 0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "errors": [],
        }

    async def summarize_sections(
        self,
        sections: List[Dict],
        section_texts: Dict[str, str],
    ) -> Dict[str, SectionSummary]:
        """
        Résume toutes les sections en parallèle.

        Args:
            sections: Liste des sections (avec id, title, level)
            section_texts: Mapping section_id -> texte de la section

        Returns:
            Dict[section_id, SectionSummary]
        """
        logger.info(f"[OSMOSE:Pass0.9] Summarizing {len(sections)} sections...")

        # Préparer les tâches de résumé
        tasks = []
        for section in sections:
            section_id = section.get("id") or section.get("section_id")
            section_title = section.get("title") or section.get("name", "Sans titre")
            level = section.get("level", 1)
            text = section_texts.get(section_id, "")

            tasks.append(
                self._summarize_one_section(
                    section_id=section_id,
                    section_title=section_title,
                    level=level,
                    text=text,
                )
            )

        # Exécuter en parallèle avec limite de concurrence
        semaphore = asyncio.Semaphore(self.config.max_concurrent_summaries)

        async def limited_task(task):
            async with semaphore:
                return await task

        results = await asyncio.gather(
            *[limited_task(t) for t in tasks],
            return_exceptions=True,
        )

        # Collecter les résultats
        summaries = {}
        for i, result in enumerate(results):
            section_id = sections[i].get("id") or sections[i].get("section_id")

            if isinstance(result, Exception):
                logger.warning(f"[OSMOSE:Pass0.9] Error summarizing {section_id}: {result}")
                self._stats["errors"].append(str(result))
                continue

            if result:
                summaries[section_id] = result

        logger.info(
            f"[OSMOSE:Pass0.9] Summarized {len(summaries)}/{len(sections)} sections "
            f"(skipped: {self._stats['sections_skipped']}, verbatim: {self._stats['sections_verbatim']})"
        )

        return summaries

    async def _summarize_one_section(
        self,
        section_id: str,
        section_title: str,
        level: int,
        text: str,
    ) -> Optional[SectionSummary]:
        """
        Résume une seule section.

        Stratégie:
        - Si texte < min_chars_to_summarize: skip ou verbatim
        - Si texte < max_chars_for_verbatim: copie verbatim
        - Sinon: résumé LLM
        """
        char_count_original = len(text)

        # Section trop courte pour être résumée
        if char_count_original < self.config.section_min_chars_to_summarize:
            self._stats["sections_skipped"] += 1
            return SectionSummary(
                section_id=section_id,
                section_title=section_title,
                level=level,
                summary=text.strip() if text.strip() else "(section vide)",
                char_count_original=char_count_original,
                char_count_summary=len(text.strip()),
                method="skipped",
            )

        # Section assez courte pour copie verbatim
        if char_count_original < self.config.section_max_chars_for_verbatim:
            self._stats["sections_verbatim"] += 1
            return SectionSummary(
                section_id=section_id,
                section_title=section_title,
                level=level,
                summary=text.strip(),
                char_count_original=char_count_original,
                char_count_summary=len(text.strip()),
                method="verbatim",
            )

        # Résumé LLM nécessaire
        try:
            summary_data = await self._call_llm_summary(
                section_title=section_title,
                level=level,
                text=text,
            )

            self._stats["sections_processed"] += 1

            return SectionSummary(
                section_id=section_id,
                section_title=section_title,
                level=level,
                summary=summary_data.get("summary", ""),
                concepts_mentioned=summary_data.get("concepts", []),
                assertion_types=summary_data.get("assertion_types", []),
                key_values=summary_data.get("key_values", []),
                char_count_original=char_count_original,
                char_count_summary=len(summary_data.get("summary", "")),
                method="llm",
            )

        except Exception as e:
            logger.warning(f"[OSMOSE:Pass0.9] LLM error for {section_id}, using truncation: {e}")
            # Fallback: troncature simple
            truncated = text[: self.config.fallback_chars_per_section]
            if len(text) > self.config.fallback_chars_per_section:
                truncated += "..."

            return SectionSummary(
                section_id=section_id,
                section_title=section_title,
                level=level,
                summary=truncated,
                char_count_original=char_count_original,
                char_count_summary=len(truncated),
                method="truncated",
            )

    async def _call_llm_summary(
        self,
        section_title: str,
        level: int,
        text: str,
    ) -> Dict:
        """
        Appelle le LLM pour résumer une section.

        Returns:
            Dict avec summary, concepts, assertion_types, key_values
        """
        import json

        system_prompt = SECTION_SUMMARY_SYSTEM_PROMPT.format(
            max_chars=self.config.section_summary_max_chars
        )

        user_prompt = SECTION_SUMMARY_USER_PROMPT.format(
            section_title=section_title,
            level=level,
            section_text=text[:8000],  # Limite le texte envoyé au LLM
            max_chars=self.config.section_summary_max_chars,
        )

        # Appel LLM
        if hasattr(self.llm_client, "chat"):
            # OpenAI-style client
            response = await self._call_openai_style(system_prompt, user_prompt)
        elif hasattr(self.llm_client, "generate"):
            # vLLM-style client
            response = await self._call_vllm_style(system_prompt, user_prompt)
        else:
            # Fallback synchrone
            response = self._call_sync(system_prompt, user_prompt)

        # Parser la réponse JSON
        try:
            # Nettoyer la réponse (enlever markdown si présent)
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            cleaned = cleaned.strip()

            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(f"[OSMOSE:Pass0.9] Failed to parse JSON response, extracting manually")
            # Extraire manuellement le résumé
            return {
                "summary": response[:self.config.section_summary_max_chars],
                "concepts": [],
                "assertion_types": [],
                "key_values": [],
            }

    async def _call_openai_style(self, system_prompt: str, user_prompt: str) -> str:
        """Appel style OpenAI (async)."""
        response = await self.llm_client.chat.completions.create(
            model="gpt-4o-mini",  # Modèle économique pour résumés
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return response.choices[0].message.content

    async def _call_vllm_style(self, system_prompt: str, user_prompt: str) -> str:
        """Appel style vLLM (async)."""
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response = await self.llm_client.generate(
            prompt=full_prompt,
            max_tokens=500,
            temperature=0.3,
        )
        return response.text if hasattr(response, "text") else str(response)

    def _call_sync(self, system_prompt: str, user_prompt: str) -> str:
        """Appel synchrone fallback."""
        if hasattr(self.llm_client, "complete"):
            response = self.llm_client.complete(
                prompt=f"{system_prompt}\n\n{user_prompt}",
                max_tokens=500,
            )
            return response.text if hasattr(response, "text") else str(response)
        raise ValueError("LLM client does not support any known interface")

    def summarize_one_section_sync(
        self,
        section_id: str,
        section_title: str,
        level: int,
        text: str,
    ) -> Optional[SectionSummary]:
        """
        Résume une section de façon synchrone via LLMRouter (Pass1LLMWrapper).

        Utilise l'interface .generate() du wrapper qui appelle LLMRouter.complete()
        → route vers vLLM/Qwen en burst, GPT-4o-mini sinon.
        """
        import json

        char_count_original = len(text)

        # Section trop courte
        if char_count_original < self.config.section_min_chars_to_summarize:
            with self._stats_lock:
                self._stats["sections_skipped"] += 1
            return SectionSummary(
                section_id=section_id,
                section_title=section_title,
                level=level,
                summary=text.strip() if text.strip() else "(section vide)",
                char_count_original=char_count_original,
                char_count_summary=len(text.strip()),
                method="skipped",
            )

        # Section assez courte pour copie verbatim
        if char_count_original < self.config.section_max_chars_for_verbatim:
            with self._stats_lock:
                self._stats["sections_verbatim"] += 1
            return SectionSummary(
                section_id=section_id,
                section_title=section_title,
                level=level,
                summary=text.strip(),
                char_count_original=char_count_original,
                char_count_summary=len(text.strip()),
                method="verbatim",
            )

        # Résumé LLM via .generate() (synchrone, burst-aware via LLMRouter)
        try:
            system_prompt = SECTION_SUMMARY_SYSTEM_PROMPT.format(
                max_chars=self.config.section_summary_max_chars
            )
            user_prompt = SECTION_SUMMARY_USER_PROMPT.format(
                section_title=section_title,
                level=level,
                section_text=text[:8000],
                max_chars=self.config.section_summary_max_chars,
            )

            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=500,
                temperature=0.3,
            )

            # Parser la réponse JSON
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            cleaned = cleaned.strip()

            try:
                summary_data = json.loads(cleaned)
            except json.JSONDecodeError:
                summary_data = {
                    "summary": response[:self.config.section_summary_max_chars],
                    "concepts": [],
                    "assertion_types": [],
                    "key_values": [],
                }

            with self._stats_lock:
                self._stats["sections_processed"] += 1

            return SectionSummary(
                section_id=section_id,
                section_title=section_title,
                level=level,
                summary=summary_data.get("summary", ""),
                concepts_mentioned=summary_data.get("concepts", []),
                assertion_types=summary_data.get("assertion_types", []),
                key_values=summary_data.get("key_values", []),
                char_count_original=char_count_original,
                char_count_summary=len(summary_data.get("summary", "")),
                method="llm",
            )

        except Exception as e:
            logger.warning(f"[OSMOSE:Pass0.9] LLM sync error for {section_id}, using truncation: {e}")
            truncated = text[: self.config.fallback_chars_per_section]
            if len(text) > self.config.fallback_chars_per_section:
                truncated += "..."

            return SectionSummary(
                section_id=section_id,
                section_title=section_title,
                level=level,
                summary=truncated,
                char_count_original=char_count_original,
                char_count_summary=len(truncated),
                method="truncated",
            )

    @property
    def stats(self) -> Dict:
        """Retourne les statistiques de traitement."""
        return self._stats.copy()
