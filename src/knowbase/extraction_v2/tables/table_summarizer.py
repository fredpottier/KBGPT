"""
TableSummarizer - Génère des résumés en langage naturel pour les tableaux.

QW-1 de ADR_REDUCTO_PARSING_PRIMITIVES:
- Transforme les tableaux structurés en texte naturel pour améliorer le RAG
- Un résumé sémantique est beaucoup plus efficace pour l'embedding qu'un Markdown brut

Principe:
- Input: TableData avec headers et cells
- Output: Résumé en 2-4 phrases décrivant les insights clés du tableau
- Stockage: summary + raw Markdown conservés

Impact attendu: +50% hit-rate RAG sur questions impliquant des tableaux.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from knowbase.extraction_v2.models.elements import TableData
from knowbase.common.llm_router import LLMRouter, TaskType

logger = logging.getLogger(__name__)


# === Prompt pour résumé de tableau ===

TABLE_SUMMARY_SYSTEM_PROMPT = """You are a precise data analyst. Your task is to summarize tables into natural language.

RULES:
1. Describe ONLY what is explicitly present in the table - never infer or add information
2. Focus on key patterns, comparisons, and notable values
3. Use natural language that would match semantic search queries
4. Keep summaries concise: 2-4 sentences maximum
5. If the table has headers, mention what dimensions/metrics are shown
6. Highlight any trends, maximums, minimums, or significant comparisons
7. Do NOT start with "This table shows..." - be direct and informative

OUTPUT: A natural language summary in the same language as the table content."""

TABLE_SUMMARY_USER_TEMPLATE = """Summarize this table in natural language:

{table_markdown}

Remember: Be factual, concise (2-4 sentences), and describe key insights."""


@dataclass
class TableSummaryResult:
    """Résultat du résumé d'un tableau."""

    table_id: str
    summary: str
    raw_markdown: str
    success: bool
    error: Optional[str] = None

    # Métriques
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_id": self.table_id,
            "summary": self.summary,
            "raw_markdown": self.raw_markdown,
            "success": self.success,
            "error": self.error,
        }


class TableSummarizer:
    """
    Génère des résumés en langage naturel pour les tableaux.

    Usage:
        >>> summarizer = TableSummarizer()
        >>> result = await summarizer.summarize(table_data)
        >>> print(result.summary)
        "Revenue increased from $100M in 2022 to $120M in 2023,
         representing a 20% growth. Margin improved from 15% to 18%."

    Configuration:
        - min_cells: Nombre minimum de cellules pour déclencher le résumé
        - max_cells: Maximum de cellules (tables trop grandes tronquées)
        - skip_empty: Ignorer les tables vides
    """

    def __init__(
        self,
        llm_router: Optional[LLMRouter] = None,
        min_cells: int = 4,
        max_cells: int = 500,
        skip_empty: bool = True,
    ):
        """
        Initialise le TableSummarizer.

        Args:
            llm_router: Router LLM (créé si non fourni)
            min_cells: Minimum de cellules pour résumer (défaut: 4)
            max_cells: Maximum de cellules avant troncature (défaut: 500)
            skip_empty: Ignorer les tables vides (défaut: True)
        """
        self._llm_router = llm_router
        self.min_cells = min_cells
        self.max_cells = max_cells
        self.skip_empty = skip_empty

        logger.info(
            f"[TableSummarizer] Initialized: min_cells={min_cells}, "
            f"max_cells={max_cells}, skip_empty={skip_empty}"
        )

    @property
    def llm_router(self) -> LLMRouter:
        """Lazy init du LLM router."""
        if self._llm_router is None:
            self._llm_router = LLMRouter()
        return self._llm_router

    def _count_cells(self, table: TableData) -> int:
        """Compte le nombre de cellules dans un tableau."""
        header_cells = len(table.headers) if table.headers else 0
        data_cells = sum(len(row) for row in table.cells)
        return header_cells + data_cells

    def _should_summarize(self, table: TableData) -> tuple[bool, str]:
        """
        Détermine si un tableau doit être résumé.

        Returns:
            Tuple (should_summarize, reason)
        """
        cell_count = self._count_cells(table)

        # Table vide
        if cell_count == 0:
            if self.skip_empty:
                return False, "empty_table"
            return False, "empty_table"

        # Trop petite
        if cell_count < self.min_cells:
            return False, f"too_small ({cell_count} < {self.min_cells})"

        return True, "ok"

    def _truncate_table(self, table: TableData) -> TableData:
        """
        Tronque un tableau trop grand en gardant les premières lignes.

        Retourne une copie tronquée si nécessaire.
        """
        cell_count = self._count_cells(table)

        if cell_count <= self.max_cells:
            return table

        # Calculer combien de lignes garder
        header_cells = len(table.headers) if table.headers else 0
        cells_per_row = len(table.cells[0]) if table.cells else 1
        max_rows = (self.max_cells - header_cells) // cells_per_row

        # Créer une copie tronquée
        truncated = TableData(
            table_id=table.table_id,
            bbox=table.bbox,
            num_rows=min(table.num_rows, max_rows + 1),
            num_cols=table.num_cols,
            cells=table.cells[:max_rows],
            headers=table.headers,
            metadata={**table.metadata, "truncated": True, "original_rows": table.num_rows},
            is_structured=table.is_structured,
        )

        logger.debug(
            f"[TableSummarizer] Truncated table {table.table_id}: "
            f"{table.num_rows} → {max_rows} rows"
        )

        return truncated

    async def summarize(self, table: TableData) -> TableSummaryResult:
        """
        Génère un résumé en langage naturel pour un tableau.

        Args:
            table: Tableau à résumer

        Returns:
            TableSummaryResult avec summary et raw_markdown
        """
        # Vérifier si on doit résumer
        should_summarize, reason = self._should_summarize(table)

        if not should_summarize:
            logger.debug(f"[TableSummarizer] Skipping {table.table_id}: {reason}")
            return TableSummaryResult(
                table_id=table.table_id,
                summary="",
                raw_markdown=table.to_markdown(),
                success=False,
                error=f"skipped: {reason}",
            )

        # Tronquer si nécessaire
        table_to_process = self._truncate_table(table)
        raw_markdown = table_to_process.to_markdown()

        # Construire les messages pour le LLM
        messages = [
            {"role": "system", "content": TABLE_SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": TABLE_SUMMARY_USER_TEMPLATE.format(
                table_markdown=raw_markdown
            )},
        ]

        try:
            # Appeler le LLM (utilise SHORT_ENRICHMENT car c'est une tâche courte)
            response = await self.llm_router.acomplete(
                task_type=TaskType.SHORT_ENRICHMENT,
                messages=messages,
                temperature=0.3,  # Faible pour rester factuel
                max_tokens=300,   # Suffisant pour 2-4 phrases
            )

            summary = response.get("content", "").strip()

            # Validation basique
            if not summary or len(summary) < 10:
                return TableSummaryResult(
                    table_id=table.table_id,
                    summary="",
                    raw_markdown=raw_markdown,
                    success=False,
                    error="empty_response",
                )

            logger.debug(
                f"[TableSummarizer] Summarized {table.table_id}: "
                f"{len(summary)} chars"
            )

            return TableSummaryResult(
                table_id=table.table_id,
                summary=summary,
                raw_markdown=raw_markdown,
                success=True,
                input_tokens=response.get("usage", {}).get("prompt_tokens", 0),
                output_tokens=response.get("usage", {}).get("completion_tokens", 0),
            )

        except Exception as e:
            logger.warning(f"[TableSummarizer] Error summarizing {table.table_id}: {e}")
            return TableSummaryResult(
                table_id=table.table_id,
                summary="",
                raw_markdown=raw_markdown,
                success=False,
                error=str(e),
            )

    async def summarize_batch(
        self,
        tables: List[TableData],
        max_concurrent: int = 5,
    ) -> List[TableSummaryResult]:
        """
        Résume plusieurs tableaux en batch.

        Args:
            tables: Liste de tableaux à résumer
            max_concurrent: Nombre max d'appels LLM concurrents

        Returns:
            Liste de TableSummaryResult
        """
        import asyncio

        if not tables:
            return []

        # Créer un semaphore pour limiter la concurrence
        semaphore = asyncio.Semaphore(max_concurrent)

        async def summarize_with_limit(table: TableData) -> TableSummaryResult:
            async with semaphore:
                return await self.summarize(table)

        # Exécuter en parallèle avec limite
        results = await asyncio.gather(
            *[summarize_with_limit(t) for t in tables],
            return_exceptions=True
        )

        # Convertir les exceptions en résultats d'erreur
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(TableSummaryResult(
                    table_id=tables[i].table_id,
                    summary="",
                    raw_markdown=tables[i].to_markdown(),
                    success=False,
                    error=str(result),
                ))
            else:
                final_results.append(result)

        # Stats
        success_count = sum(1 for r in final_results if r.success)
        logger.info(
            f"[TableSummarizer] Batch complete: {success_count}/{len(tables)} succeeded"
        )

        return final_results


__all__ = ["TableSummarizer", "TableSummaryResult"]
