"""Tool registry pour Layer 2 Orchestrator (CH-49 Phase 3, Cap3).

Wrapping des operators Cap2 + retrieval comme tools function-calling-compatibles
(format OpenAI/Together AI tool_calls).

Charte :
  - Pas de Cypher arbitraire exposé (sécurité)
  - Tools déterministes : leur exécution est code Python, pas LLM
  - Le LLM Layer 2 choisit QUAND appeler quel tool, pas COMMENT exécuter
  - Tools réutilisent les operators Cap2 existants (pas de duplication)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# Schemas OpenAI/Together AI tool_calls format
TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "vector_search",
            "description": (
                "Search for evidence chunks in the document corpus by semantic similarity. "
                "Returns text excerpts with their source doc_id. Use this to gather context "
                "for any factual question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Semantic search query"},
                    "top_k": {"type": "integer", "default": 10, "description": "Number of chunks to return (max 20)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "temporal_active_version",
            "description": (
                "Determine which version of a document was active at a given date. "
                "Use for 'which version applies at date X' questions. The operator is deterministic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Original question (the operator does its own intent extraction)"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lifecycle_resolution",
            "description": (
                "Find which document replaced/superseded another (or vice versa), or trace "
                "the lineage of evolution between document versions. Returns explicit "
                "lifecycle relations (SUPERSEDES, EVOLVES_FROM, REAFFIRMS) with evidence quotes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Original question with document identifiers"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kg_query",
            "description": (
                "Run a structural query on the document graph: count documents by status, "
                "list documents by status, traverse a supersession chain. Use ONLY for "
                "structural / quantitative questions, NOT for content questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Question describing the structural query"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reasoning_negation",
            "description": (
                "Find items explicitly EXCLUDED, EXEMPTED or NOT IN a scope. Use for "
                "negation/exclusion/exemption questions. Returns excluded items with "
                "evidence quotes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Original negation question"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_answer_from_chunks",
            "description": (
                "Given evidence chunks (from previous vector_search calls), extract a direct "
                "answer to the question. Use when chunks contain enough information."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The user question"},
                    "chunks_text": {"type": "string", "description": "Concatenated chunks as text"},
                },
                "required": ["question", "chunks_text"],
            },
        },
    },
]


@dataclass
class ToolCallResult:
    name: str
    arguments: dict
    result: dict  # JSON-serializable
    success: bool
    error: Optional[str] = None
    latency_ms: int = 0


class ToolRegistry:
    """Registre des tools accessibles au Layer 2 orchestrator.

    Chaque tool est une fonction Python qui prend des arguments JSON-décodés
    et retourne un résultat JSON-sérialisable.
    """

    def __init__(
        self,
        evidence_collector: Any,
        llm_client: Any,
        temporal_active_op: Optional[Any] = None,
        lifecycle_resolution_op: Optional[Any] = None,
        kg_query_op: Optional[Any] = None,
        set_reasoning_op: Optional[Any] = None,
    ) -> None:
        self.evidence_collector = evidence_collector
        self.llm_client = llm_client
        self.temporal_active_op = temporal_active_op
        self.lifecycle_resolution_op = lifecycle_resolution_op
        self.kg_query_op = kg_query_op
        self.set_reasoning_op = set_reasoning_op

    def get_tool_defs(self) -> list[dict]:
        """Retourne les définitions de tools (filtre selon les operators dispo)."""
        defs = []
        for d in TOOL_DEFS:
            name = d["function"]["name"]
            if name == "temporal_active_version" and self.temporal_active_op is None:
                continue
            if name == "lifecycle_resolution" and self.lifecycle_resolution_op is None:
                continue
            if name == "kg_query" and self.kg_query_op is None:
                continue
            if name == "set_reasoning_negation" and self.set_reasoning_op is None:
                continue
            defs.append(d)
        return defs

    def execute(self, name: str, arguments: dict) -> ToolCallResult:
        """Dispatche le tool call. Retourne result JSON-sérializable."""
        import time
        t0 = time.time()
        try:
            if name == "vector_search":
                result = self._tool_vector_search(arguments)
            elif name == "temporal_active_version":
                result = self._tool_temporal_active(arguments)
            elif name == "lifecycle_resolution":
                result = self._tool_lifecycle_resolution(arguments)
            elif name == "kg_query":
                result = self._tool_kg_query(arguments)
            elif name == "set_reasoning_negation":
                result = self._tool_set_reasoning(arguments)
            elif name == "extract_answer_from_chunks":
                result = self._tool_extract_answer(arguments)
            else:
                return ToolCallResult(
                    name=name, arguments=arguments,
                    result={"error": f"unknown_tool: {name}"},
                    success=False, error=f"unknown_tool: {name}",
                    latency_ms=int((time.time() - t0) * 1000),
                )
            return ToolCallResult(
                name=name, arguments=arguments, result=result,
                success=True, latency_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Tool {name} raised: {exc}")
            return ToolCallResult(
                name=name, arguments=arguments,
                result={"error": str(exc)},
                success=False, error=str(exc),
                latency_ms=int((time.time() - t0) * 1000),
            )

    # ----------------------------------------------------------- Tool impls
    def _tool_vector_search(self, args: dict) -> dict:
        query = args.get("query", "")
        top_k = min(int(args.get("top_k", 10)), 20)
        bundle = self.evidence_collector.collect(question=query, top_k=top_k, mode="single")
        chunks = []
        for c in bundle.claims[:top_k]:
            quote = (getattr(c, "quote", "") or "").strip()
            if quote:
                chunks.append({
                    "doc_id": c.doc_id,
                    "page": getattr(c, "page_no", None),
                    "text": quote[:600],
                })
        return {"n_chunks": len(chunks), "chunks": chunks}

    def _tool_temporal_active(self, args: dict) -> dict:
        question = args.get("question", "")
        result = self.temporal_active_op.execute(question)
        return {
            "decision": result.decision,
            "answer": result.answer,
            "active_doc_id": result.active_doc_id,
            "active_publication_date": result.active_publication_date,
            "n_hits": result.cypher_n_hits,
            "abstention_reason": result.abstention_reason,
        }

    def _tool_lifecycle_resolution(self, args: dict) -> dict:
        question = args.get("question", "")
        result = self.lifecycle_resolution_op.execute(question)
        return {
            "decision": result.decision,
            "answer": result.answer,
            "direction": result.direction,
            "n_hits": result.cypher_n_hits,
            "abstention_reason": result.abstention_reason,
        }

    def _tool_kg_query(self, args: dict) -> dict:
        question = args.get("question", "")
        result = self.kg_query_op.execute(question)
        return {
            "decision": result.decision,
            "answer": result.answer,
            "query_type": result.query_type,
            "count_value": result.count_value,
            "n_rows": len(result.rows),
            "abstention_reason": result.abstention_reason,
        }

    def _tool_set_reasoning(self, args: dict) -> dict:
        question = args.get("question", "")
        result = self.set_reasoning_op.execute(question)
        return {
            "decision": result.decision,
            "answer": result.answer,
            "polarity": result.polarity,
            "n_excluded": len(result.items_excluded),
            "abstention_reason": result.abstention_reason,
        }

    def _tool_extract_answer(self, args: dict) -> dict:
        question = args.get("question", "")
        chunks_text = args.get("chunks_text", "")
        prompt = """You are a documentary assistant. Answer the user's question using ONLY the evidence chunks provided.

Rules:
- Concise direct answer with [doc=ID] citations
- If chunks don't contain the answer, say "Information not found in available chunks"
- Stay under 3 sentences"""
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Question: {question}\n\nChunks:\n{chunks_text}\n\nAnswer:"},
        ]
        try:
            answer = self.llm_client.chat_completion(
                messages=messages, temperature=0.1, max_tokens=400,
            )
            return {"answer": answer.strip()}
        except Exception as exc:  # noqa: BLE001
            return {"answer": "", "error": str(exc)}
