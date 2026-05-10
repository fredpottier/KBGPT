"""Reasoning Agent CH-51 — DeepSeek-V3.1 + tool use itératif + workspace cognitif.

Domain-agnostic strict : prompt système, workspace, tool descriptions n'utilisent
aucun vocabulaire corpus-spécifique.

Architecture :
  question → init workspace → loop (max N iter) [LLM decides tool] → synthesize answer
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

import requests

from knowbase.runtime_v5.reading_tools import (
    TOOL_REGISTRY, list_doc_ids,
)


DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()

# Modèle agent par défaut (charte open-source respectée)
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3.1"

# Schémas OpenAI tool format pour les 7 reading tools
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "outline",
            "description": "Returns the structured table of contents of a document. Use first to discover what sections exist before reading specifics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "Document identifier (use exact ID from available_docs)"},
                    "max_sections": {"type": "integer", "default": 80},
                    "min_text_chars": {"type": "integer", "default": 0, "description": "Filter sections with less than N chars of text"},
                },
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Reads the full text of a specific section. Pass either a section_path (like '/X/Y'), a numbering ('Article 5', '3.2.1'), or a section title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "section_path_or_numbering": {"type": "string", "description": "Section identifier — path or numbering or title"},
                    "max_chars": {"type": "integer", "default": 8000},
                },
                "required": ["doc_id", "section_path_or_numbering"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_in",
            "description": "Searches a string or regex inside a specific document. Returns sections matching the query with snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 10},
                    "snippet_chars": {"type": "integer", "default": 400},
                },
                "required": ["doc_id", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_ref",
            "description": "Resolves an internal reference like 'see Article 5(3)' or 'cf section 3.2' to the actual section path. Pass the reference as found in text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "ref_text": {"type": "string"},
                    "current_section_id": {"type": "string"},
                },
                "required": ["doc_id", "ref_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "expand_context",
            "description": "Returns the structural context around a section: parent section, neighboring sections (before/after), direct children. Useful when you need contextual surroundings of a specific section.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "section_id": {"type": "string", "description": "Section ID returned by outline/read/find_in"},
                    "window": {"type": "integer", "default": 2},
                },
                "required": ["doc_id", "section_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_sections",
            "description": "Compares text of two sections (potentially in different documents). Returns side-by-side text + unified diff.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_a": {"type": "string"},
                    "section_a_ref": {"type": "string"},
                    "doc_b": {"type": "string"},
                    "section_b_ref": {"type": "string"},
                },
                "required": ["doc_a", "section_a_ref", "doc_b", "section_b_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_versions",
            "description": "Returns the chain of related document versions (predecessors / successors / variants) for a document subject. Useful for temporal questions about which version applied at a given date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_subject": {"type": "string", "description": "Subject identifier (e.g. document name fragment)"},
                },
                "required": ["doc_subject"],
            },
        },
    },
]


SYSTEM_PROMPT = """You are a careful research agent who answers questions by navigating structured documents.

You have access to a set of reading tools that let you:
  - List the table of contents of a document (outline)
  - Read specific sections by their identifier or numbering (read)
  - Search inside a document (find_in)
  - Resolve internal references like "see Article 5(3)" (resolve_ref)
  - Get structural context around a section (expand_context)
  - Compare sections from different documents (compare_sections)
  - Find related versions / variants of a document (list_versions)

Your approach:
  1. Begin by understanding the question carefully. Note any embedded assumption that might be wrong (the question might contain a false premise that needs correction).
  2. Identify which document(s) are relevant. Use available_docs from the user prompt.
  3. Use outline first if you don't know the structure of a relevant doc.
  4. Read specific sections (full text) rather than guessing — never assume content you haven't read.
  5. Resolve any cross-references you encounter ("see X", "cf Y").
  6. Maintain awareness of what you've collected vs what's still missing.
  7. When you have enough evidence, write a final answer with citations.

Citations format: [doc=DOC_ID/SECTION_PATH] after each factual claim.

Anti-patterns to avoid:
  - Never abstain ("answer not found") when you haven't actually read the relevant sections.
  - Never invent details that you haven't verified by reading.
  - Don't repeat the same tool call with the same parameters more than twice.
  - Don't conclude prematurely if your collected evidence is shallow.

When ready, produce a final answer in plain text. Do not call any tool in your final message."""


# ─────────────────────────────────────────────────────────────────────────────
# Agent loop
# ─────────────────────────────────────────────────────────────────────────────

def call_llm(messages: list[dict], tools: list[dict], model: str = DEFAULT_MODEL,
             max_tokens: int = 1500, max_retries: int = 3) -> dict:
    """Appel DeepInfra avec tools."""
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                headers={"Authorization": f"Bearer {DEEPINFRA_KEY}", "Content-Type": "application/json"},
                json=payload,
                timeout=300,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
    return {"error": str(last_err)}


def execute_tool(tool_name: str, tool_args: dict) -> dict:
    """Exécute un tool depuis le registry. Retourne dict {"result": ...} ou {"error": ...}."""
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        result = fn(**tool_args)
        return {"result": result}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def run_agent(
    question: str,
    available_doc_ids: Optional[list[str]] = None,
    max_iterations: int = 8,
    model: str = DEFAULT_MODEL,
    verbose: bool = True,
) -> dict:
    """Exécute l'agent Reading Agent sur une question.

    Returns:
      {
        "question": str,
        "answer": str,
        "workspace": {...},   # state final
        "trace": [{iter, tool_call, tool_result_summary}, ...],
        "n_iterations": int,
        "stopped_reason": "concluded" | "max_iter" | "stuck_loop" | "error",
        "tokens_total": int
      }
    """
    if available_doc_ids is None:
        available_doc_ids = list_doc_ids()

    docs_listing = "\n".join(f"  - {d}" for d in available_doc_ids)
    user_prompt = f"""Question: {question}

available_docs:
{docs_listing}

Plan your approach, use the reading tools to gather evidence, and produce a final answer with citations."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    workspace = {
        "question": question,
        "tool_calls_log": [],     # liste des (iter, tool, args, result_summary)
        "facts_collected": [],    # extraits factuels indexés
        "final_answer": "",
    }
    trace = []
    tokens_total = 0
    same_call_signatures = []
    stopped_reason = "concluded"

    for iteration in range(1, max_iterations + 1):
        if verbose:
            print(f"\n--- ITER {iteration} ---")
        resp = call_llm(messages, TOOL_SCHEMAS, model=model)
        if "error" in resp:
            stopped_reason = "error"
            workspace["error"] = resp["error"]
            break
        msg = resp["choices"][0]["message"]
        usage = resp.get("usage", {})
        tokens_total += usage.get("total_tokens", 0)

        # Add assistant message to history
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        content = msg.get("content") or ""

        if not tool_calls:
            # Agent has produced final answer (no tool call)
            workspace["final_answer"] = content
            if verbose:
                print(f"[CONCLUDE] {content[:200]}")
            break

        # Execute tool calls in parallel sequence
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                fn_args = {}
            sig = f"{fn_name}({json.dumps(fn_args, sort_keys=True)})"

            # Anti-loop : si même signature appelée 3 fois, force conclude
            same_call_signatures.append(sig)
            recent_count = same_call_signatures.count(sig)
            if recent_count >= 3:
                if verbose:
                    print(f"[ANTI-LOOP] same call {sig[:80]} repeated {recent_count}x")
                # Force tool result with hint
                tool_result = {"error": "duplicate_call_skipped",
                               "hint": "This same tool+args was called multiple times. Try different parameters or conclude."}
            else:
                if verbose:
                    print(f"[TOOL] {sig[:120]}")
                tool_result = execute_tool(fn_name, fn_args)

            # Compress result for LLM (avoid huge text in context)
            result_str = json.dumps(tool_result, ensure_ascii=False)
            if len(result_str) > 12000:
                result_str = result_str[:12000] + "\n... [TRUNCATED]"

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_str,
            })

            # Trace summary
            result_summary = ""
            if "result" in tool_result and isinstance(tool_result["result"], dict):
                r = tool_result["result"]
                result_summary = f"keys={list(r.keys())[:6]}"
            trace_entry = {
                "iter": iteration,
                "tool": fn_name,
                "args": fn_args,
                "result_summary": result_summary,
                "result_size": len(result_str),
            }
            trace.append(trace_entry)
            workspace["tool_calls_log"].append(trace_entry)

            if verbose:
                print(f"  → result {len(result_str)} chars, summary: {result_summary[:80]}")

    else:
        # Loop exhausted without break
        stopped_reason = "max_iter"
        # Force a final synthesis call without tools
        if verbose:
            print(f"[MAX_ITER] Forcing final synthesis...")
        synth_messages = messages + [
            {"role": "user", "content": "You've reached max iterations. Now produce your final answer based on what you've collected. Do not call any tool."}
        ]
        final_resp = call_llm(synth_messages, [], model=model)
        if "error" not in final_resp:
            final_msg = final_resp["choices"][0]["message"]
            workspace["final_answer"] = final_msg.get("content", "")
            tokens_total += final_resp.get("usage", {}).get("total_tokens", 0)

    return {
        "question": question,
        "answer": workspace.get("final_answer", ""),
        "workspace": workspace,
        "trace": trace,
        "n_iterations": iteration,
        "stopped_reason": stopped_reason,
        "tokens_total": tokens_total,
        "model": model,
    }
