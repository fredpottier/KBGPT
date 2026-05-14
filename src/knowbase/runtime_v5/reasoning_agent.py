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
TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "").strip()

# Modèle agent par défaut (charte open-source respectée)
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3.1"

# Provider priority: Together AI (rapide ×6) > DeepInfra (fallback)
def _llm_endpoint_and_key():
    if TOGETHER_KEY:
        return "https://api.together.xyz/v1/chat/completions", TOGETHER_KEY, "together"
    return "https://api.deepinfra.com/v1/openai/chat/completions", DEEPINFRA_KEY, "deepinfra"

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


SYSTEM_PROMPT = """You are an EFFICIENT research agent answering questions by navigating structured documents.

You have access to reading tools: outline, read, find_in, resolve_ref, expand_context, compare_sections, list_versions.

**EFFICIENCY MANDATE — read this carefully:**

Your goal is to answer the question WELL with the MINIMUM number of tool calls necessary. Most questions need only 2-4 tool calls. Over-exploration is a defect, not a virtue.

**Decision rules (apply at every step):**

1. **Did you just read a section that contains the answer?** → STOP exploring, write the final answer NOW (no more tools).
2. **Have you read 3+ sections without finding new useful information?** → STOP, conclude with what you have OR state the corpus doesn't contain the answer.
3. **Are you about to call the same tool with similar arguments?** → STOP, this is a loop. Conclude.

**Typical efficient patterns:**
  - Factual question : outline → read → CONCLUDE (2-3 tool calls)
  - Comparison      : outline → read each → CONCLUDE (3-4 calls)
  - Multi-hop       : outline → read sec A → resolve_ref → read sec B → CONCLUDE (4-5 calls)
  - False premise   : read most relevant section → check premise → CONCLUDE
  - Unanswerable    : 1-2 read attempts → CONCLUDE with explicit "not in corpus"

**Anti-patterns (forbidden):**
  - Reading many sections "just in case" → wasteful
  - Re-reading a section already read → forbidden
  - Calling outline on the same doc twice → forbidden
  - Continuing to explore after you have a complete answer → forbidden
  - "Let me also check..." after a complete answer is found → forbidden

**When you have an answer (even partial), output it as plain text WITHOUT calling any tool.**
Final message format: plain prose with citations [doc=DOC_ID/SECTION_PATH] after each factual claim.

**If the corpus doesn't contain the answer after 3 sections explored**: explicitly state "The available documents do not contain X" and STOP.

Begin by understanding the question. Note any false premise. Then act minimally — early stopping is rewarded."""


# ─────────────────────────────────────────────────────────────────────────────
# Agent loop
# ─────────────────────────────────────────────────────────────────────────────

def call_llm(messages: list[dict], tools: list[dict], model: str = DEFAULT_MODEL,
             max_tokens: int = 1500, max_retries: int = 3) -> dict:
    """Appel LLM avec tools. Priorité Together AI > DeepInfra (cf charte CH-48)."""
    endpoint, key, provider = _llm_endpoint_and_key()
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    # Fix Together AI : ne pas passer tool_choice avec tools=[] (400 error)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
                timeout=300,
            )
            r.raise_for_status()
            data = r.json()
            data["_provider"] = provider
            return data
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

    # Stop rules state tracking (NEW)
    sections_read: set = set()           # section_ids LUS via read/read_with_footnotes/compare_sections (lecture pleine, pas indexation)
    iter_without_new_section = 0          # compteur stagnation
    STAGNATION_MAX = 2                    # 2 iter sans nouvelle section lue → break
    STAGNATION_MIN_READS = 1              # min 1 section lue avant de pouvoir stagnate (sinon laisser l'agent commencer)
    ANTI_LOOP_HARD = 3                    # 3× même call → break
    force_break = False                   # flag pour sortir de la boucle for externe
    # Tools qui comptent comme "vraie lecture" (vs indexation)
    READ_TOOLS = {"read", "read_with_footnotes", "expand_context", "compare_sections", "summarize_subtree"}

    for iteration in range(1, max_iterations + 1):
        if force_break:
            break
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

        # Track new sections discovered this iteration
        new_sections_this_iter = 0

        # Execute tool calls in parallel sequence
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                fn_args = {}
            sig = f"{fn_name}({json.dumps(fn_args, sort_keys=True)})"

            # Anti-loop HARD : si même signature 3×, on injecte stop + break iter loop
            same_call_signatures.append(sig)
            recent_count = same_call_signatures.count(sig)
            if recent_count >= ANTI_LOOP_HARD:
                if verbose:
                    print(f"[ANTI-LOOP HARD] {sig[:80]} repeated {recent_count}× — forcing break")
                stopped_reason = "stuck_loop"
                # Inject minimal valid tool result then break outer
                tool_result = {"error": "stop_loop_detected",
                               "hint": "Forced break: conclude now with current evidence."}
                # Pop the assistant message we just added (avoid dangling tool_calls)
                # Actually we keep it but provide tool result, then break iter loop
                result_str = json.dumps(tool_result, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})
                force_break = True
                break  # break tool_calls loop
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
            new_section_ids: list = []
            # On ne compte comme "vraie lecture" que les tools dans READ_TOOLS
            # (read, read_with_footnotes, compare_sections, expand_context, summarize_subtree)
            # Les tools d'indexation (outline, find_in, resolve_ref) retournent juste des refs
            is_read_tool = fn_name in READ_TOOLS
            if "result" in tool_result and isinstance(tool_result["result"], dict) and is_read_tool:
                r = tool_result["result"]
                result_summary = f"keys={list(r.keys())[:6]}"
                # Extract section_ids from tool result for stagnation tracking
                if "section_id" in r:
                    new_section_ids.append(r["section_id"])
                if "sections" in r and isinstance(r["sections"], list):
                    for s in r["sections"]:
                        if isinstance(s, dict) and "section_id" in s:
                            new_section_ids.append(s["section_id"])
            elif "result" in tool_result and isinstance(tool_result["result"], dict):
                # Index tools : on récupère juste un summary mais pas de section_ids
                r = tool_result["result"]
                result_summary = f"index={fn_name} keys={list(r.keys())[:4]}"

            # Count truly new sections (not already in sections_read)
            for sid in new_section_ids:
                if sid and sid not in sections_read:
                    sections_read.add(sid)
                    new_sections_this_iter += 1

            trace_entry = {
                "iter": iteration,
                "tool": fn_name,
                "args": fn_args,
                "result_summary": result_summary,
                "result_size": len(result_str),
                "new_sections": len([s for s in new_section_ids if s in sections_read]),
            }
            trace.append(trace_entry)
            workspace["tool_calls_log"].append(trace_entry)

            if verbose:
                print(f"  → result {len(result_str)} chars, summary: {result_summary[:80]}")

        # STAGNATION CHECK (NEW) : si N iter sans nouvelle section utile → break
        # MAIS seulement si l'agent a déjà exploré suffisamment (≥ STAGNATION_MIN_SECTIONS)
        if new_sections_this_iter == 0:
            iter_without_new_section += 1
            if verbose:
                print(f"[STAGNATION] iter {iteration} brought 0 new sections (stagnation count={iter_without_new_section}, total sections={len(sections_read)})")
            if iter_without_new_section >= STAGNATION_MAX and len(sections_read) >= STAGNATION_MIN_READS:
                if verbose:
                    print(f"[BREAK STAGNATION] {STAGNATION_MAX} iter without new reads AND {len(sections_read)} sections read — forcing conclude")
                stopped_reason = "stagnation"
                force_break = True
            elif iter_without_new_section >= STAGNATION_MAX and len(sections_read) < STAGNATION_MIN_READS:
                if verbose:
                    print(f"[STAGNATION HOLD] {iter_without_new_section} iter without new reads but only {len(sections_read)} reads done — letting agent continue")
        else:
            iter_without_new_section = 0
            if verbose:
                print(f"[NEW SECTIONS] {new_sections_this_iter} new sections this iter (total {len(sections_read)})")

    else:
        # Loop exhausted without break
        stopped_reason = "max_iter"
        if verbose:
            print(f"[MAX_ITER] Forcing final synthesis...")

    # FINAL SYNTHESIS : si pas de final_answer (max_iter, stagnation, stuck_loop)
    if not workspace.get("final_answer") and stopped_reason in ("max_iter", "stagnation", "stuck_loop"):
        if verbose:
            print(f"[FORCED SYNTH] reason={stopped_reason}")
        # Strip dangling tool_calls (assistant messages with tool_calls but no corresponding tool response)
        # Together AI may reject conversations ending mid-tool-call
        synth_messages = list(messages) + [
            {"role": "user", "content": (
                "You've gathered evidence through your tool calls. "
                "Now produce your FINAL ANSWER to the original question, with citations [doc=ID]. "
                "Even if your evidence is partial, give your best synthesis. "
                "Output plain text only — do not call any more tools."
            )}
        ]
        final_resp = call_llm(synth_messages, [], model=model, max_tokens=2000)
        synth_content = ""
        if "error" not in final_resp:
            final_msg = final_resp["choices"][0]["message"]
            synth_content = final_msg.get("content", "") or ""
            tokens_total += final_resp.get("usage", {}).get("total_tokens", 0)
        # Fallback : si forced synthesis retourne vide, prendre le dernier assistant content non-vide
        if not synth_content.strip():
            for m in reversed(messages):
                if m.get("role") == "assistant" and (m.get("content") or "").strip():
                    synth_content = m["content"]
                    if verbose:
                        print(f"[FALLBACK] Using last assistant content ({len(synth_content)} chars)")
                    break
        # Dernier recours : produire un message d'abstention factuel basé sur le workspace
        if not synth_content.strip():
            n_tools = len(workspace.get("tool_calls_log", []))
            synth_content = (
                f"Après {n_tools} appels d'outils sur les documents disponibles, "
                "je n'ai pas pu rassembler suffisamment d'évidence pour fournir une réponse précise et sourcée."
            )
            if verbose:
                print(f"[LAST RESORT] Using abstention message")
        workspace["final_answer"] = synth_content

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
