"""V5.1 Reasoning Agent — orchestration des modules S4.

CH-52.5.6 (intégration S4) : remplace le POC reasoning_agent.py par une
implémentation qui utilise les 5 building blocks industrialisés :
- LoopSignatureTracker (S4.1) : anti-thrash novelty-based + duplicate
- BudgetTracker (S4.2) : 4 budgets indépendants + hard caps absolus
- ExecutionPlan (S4.3) : plan-then-execute pour shapes complexes (optional)
- CancellationToken (S4.4) : user-cancel propagable
- Workspace (S4.7) : trace versionnée Pydantic réplayable

Le POC initial `reasoning_agent.py` reste intact pour comparaison.

Architecture (cohérente ADR V1.5 §3e) :

    question + (optional) answer_shape + cancellation_token
        │
        ▼
    Init : Workspace + BudgetTracker(shape) + LoopSignatureTracker
        │
        ▼
    Loop until stop :
        1. cancellation.check_async()
        2. budget.check_soft_caps() → if exceeded → conclude
        3. call_llm(messages, tool_schemas) [budget.add_output_tokens]
        4. for each tool_call :
             a. sanitizer.sanitize() [registry validation]
             b. execute tool [budget.add_retrieved_chars]
             c. tracker.record(...) → check should_stop() → conclude if thrash
             d. workspace.record_tool_call / add_evidence
        5. budget.increment_iteration
        6. enforce_hard_caps()
    ▼
    Final synthesis if needed (forced answer) + workspace.finalize()
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from knowbase.runtime_v5.agent.budgets import (
    BudgetExceeded,
    BudgetTracker,
    get_shape_budget,
)
from knowbase.runtime_v5.agent.cancellation import (
    NULL_TOKEN,
    CancellationRequested,
    CancellationToken,
)
from knowbase.runtime_v5.agent.execution_plan import (
    ExecutionPlan,
    is_plan_required,
)
from knowbase.runtime_v5.agent.loop_signature import LoopSignatureTracker
from knowbase.runtime_v5.agent.workspace import (
    EpistemicStatus,
    Workspace,
)
from knowbase.runtime_v5.tools.registry import (
    EvidenceType,
    ToolRegistry,
    get_default_registry,
)
from knowbase.runtime_v5.tools.sanitizer import (
    ToolCallError,
    ToolCallSanitizer,
)

logger = logging.getLogger(__name__)


# ─── Result wrapper ──────────────────────────────────────────────────────────


@dataclass
class AgentRunResult:
    """Résultat final d'un run agent V5.1."""
    answer: str
    epistemic_status: EpistemicStatus
    stop_reason: str
    workspace: Workspace
    latency_s: float

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "epistemic_status": self.epistemic_status.value,
            "stop_reason": self.stop_reason,
            "latency_s": self.latency_s,
            "workspace_summary": self.workspace.summary(),
        }


# ─── LLM call interface (abstrait pour tests) ────────────────────────────────


class LLMCaller:
    """Interface minimale pour appeler le LLM.

    Implémentation production : Together AI / DeepInfra (chat completions).
    Implémentation tests : MockLLMCaller (scriptable).
    """

    def call(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2000,
    ) -> dict:
        """Returns dict avec keys : 'message' (dict avec content + tool_calls), 'usage' (dict)."""
        raise NotImplementedError


# ─── ReasoningAgentV51 ───────────────────────────────────────────────────────


class ReasoningAgentV51:
    """Orchestre les modules S4 pour un cycle agent itératif.

    Args:
        llm_caller : impl LLMCaller (production OU mock)
        registry : ToolRegistry à utiliser (default singleton)
        sanitizer : ToolCallSanitizer (default = wrap registry)
        max_message_history : limite messages gardés (default 60)
    """

    def __init__(
        self,
        llm_caller: LLMCaller,
        registry: Optional[ToolRegistry] = None,
        sanitizer: Optional[ToolCallSanitizer] = None,
        max_message_history: int = 60,
    ):
        self.llm = llm_caller
        self.registry = registry or get_default_registry()
        self.sanitizer = sanitizer or ToolCallSanitizer(self.registry)
        self.max_message_history = max_message_history

    # ─── Async entrypoint (recommandé production) ────────────────────────────

    async def run_async(
        self,
        question: str,
        tenant_id: str = "default",
        answer_shape: Optional[str] = None,
        cancellation: Optional[CancellationToken] = None,
        plan: Optional[ExecutionPlan] = None,
        doc_version_snapshot: Optional[dict[str, int]] = None,
        system_prompt: str = "",
        user_prompt_extra: str = "",
    ) -> AgentRunResult:
        """Execute l'agent de manière async (avec cancellation token).

        Args:
            question : requête utilisateur
            tenant_id : tenant isolation key
            answer_shape : shape du classifier S0.5 (configure budgets adaptatifs)
            cancellation : token user-cancel (default NULL_TOKEN)
            plan : ExecutionPlan optionnel (pour shapes complexes)
            doc_version_snapshot : pinned doc versions pour audit reproducibility
            system_prompt : prompt système (sinon défault EFFICIENCY MANDATE)
            user_prompt_extra : info supplémentaire injectée dans le user prompt
        """
        token = cancellation or NULL_TOKEN
        t_start = time.time()

        # ─── Init Workspace + Budgets + LoopTracker ──────────────────────────
        workspace = Workspace(
            tenant_id=tenant_id,
            question=question,
            answer_shape=answer_shape,
            plan=plan,
            doc_version_snapshot=doc_version_snapshot or {},
        )
        budgets = BudgetTracker(shape=answer_shape)
        loop_tracker = LoopSignatureTracker(
            novelty_window=3,
            novelty_threshold=0.10,
            duplicate_signatures_threshold=3,
        )

        # ─── Init messages ───────────────────────────────────────────────────
        sys_p = system_prompt or _DEFAULT_SYSTEM_PROMPT
        user_p = self._build_user_prompt(question, tenant_id, user_prompt_extra)
        messages = [
            {"role": "system", "content": sys_p},
            {"role": "user", "content": user_p},
        ]

        # ─── Main loop ───────────────────────────────────────────────────────
        stop_reason = "concluded"
        epistemic_status = EpistemicStatus.COMPLETE
        final_answer_content = ""

        try:
            while True:
                # 1. Cancellation check
                await token.check_async()

                # 2. Budget soft cap check
                exceeded, axis = budgets.check_soft_caps()
                if exceeded:
                    stop_reason = f"budget_soft_cap_{axis}"
                    epistemic_status = EpistemicStatus.PARTIAL
                    logger.info(f"[V51] {stop_reason} — forcing conclude")
                    break

                # 3. Loop tracker stop check (anti-thrash)
                should_stop_thrash, thrash_reason = loop_tracker.should_stop()
                if should_stop_thrash:
                    stop_reason = f"thrash:{thrash_reason}"
                    epistemic_status = EpistemicStatus.PARTIAL
                    logger.info(f"[V51] {stop_reason}")
                    break

                # 4. LLM call
                budgets.increment_iteration()
                tool_schemas = self.registry.to_llm_tools()
                llm_resp = self.llm.call(messages, tool_schemas, max_tokens=2000)
                if "error" in llm_resp:
                    stop_reason = f"llm_error:{llm_resp['error']}"
                    epistemic_status = EpistemicStatus.ABORTED
                    break

                msg = llm_resp["message"]
                usage = llm_resp.get("usage", {})
                budgets.add_output_tokens(usage.get("completion_tokens", 0))
                messages.append(msg)

                tool_calls = msg.get("tool_calls") or []
                content = msg.get("content") or ""

                # 5. No tool call → conclude
                if not tool_calls:
                    final_answer_content = content
                    break

                # 6. Execute each tool call
                for tc in tool_calls:
                    await token.check_async()  # check between tool calls
                    iter_idx = budgets.iterations - 1
                    fn_name = tc["function"]["name"]
                    try:
                        fn_args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        fn_args = {}

                    # 6a. Sanitize via ToolCallSanitizer
                    try:
                        sanitized = self.sanitizer.sanitize(fn_name, fn_args)
                        tool_args_clean = sanitized.args
                        spec = sanitized.spec
                        repair_applied = sanitized.report.has_repairs()
                    except ToolCallError as e:
                        # Tool inconnu / retired / invalid → record + inject error
                        workspace.record_tool_call(
                            iter_idx=iter_idx, tool_name=fn_name,
                            args=fn_args, error=str(e), repair_applied=False,
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps({"error": str(e),
                                                   "error_type": e.error_type}),
                        })
                        budgets.increment_tool_call()
                        continue

                    # 6b. Execute tool
                    t_tool = time.time()
                    try:
                        if spec.handler is None:
                            tool_result = {"error": f"tool '{fn_name}' has no handler"}
                        else:
                            tool_result = {"result": spec.handler(**tool_args_clean)}
                    except Exception as ex:
                        tool_result = {"error": f"{type(ex).__name__}: {ex}"}
                    tool_latency_ms = (time.time() - t_tool) * 1000.0
                    budgets.increment_tool_call()

                    # 6c. Compress + inject result
                    result_str = json.dumps(tool_result, ensure_ascii=False)
                    result_chars = len(result_str)
                    budgets.add_retrieved_chars(result_chars)
                    truncated = result_str
                    if len(result_str) > 12000:
                        truncated = result_str[:12000] + "\n... [TRUNCATED]"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": truncated,
                    })

                    # 6d. Record loop signature (anti-thrash)
                    extracted_text = self._extract_evidence_text(tool_result)
                    loop_tracker.record(
                        tool=fn_name,
                        args=tool_args_clean,
                        new_evidence_text=extracted_text,
                        prior_evidence_chars=budgets.retrieved_chars - result_chars,
                        iter_idx=iter_idx,
                    )

                    # 6e. Record in workspace
                    workspace.record_tool_call(
                        iter_idx=iter_idx, tool_name=fn_name,
                        args=tool_args_clean, result_summary=extracted_text[:300],
                        result_chars=result_chars,
                        latency_ms=tool_latency_ms,
                        error=tool_result.get("error"),
                        repair_applied=repair_applied,
                    )
                    # Add evidence if successful
                    if "result" in tool_result and isinstance(tool_result["result"], dict):
                        self._extract_and_add_evidence(
                            workspace, tool_result["result"],
                            evidence_type=spec.evidence_type_returned,
                            source_tool=fn_name, iter_idx=iter_idx,
                        )

                # 7. Enforce hard caps (raise if absolute limit hit)
                try:
                    budgets.enforce_hard_caps()
                except BudgetExceeded as be:
                    stop_reason = f"hard_cap_exceeded:{be.budget_name}"
                    epistemic_status = EpistemicStatus.ABORTED
                    logger.warning(f"[V51] {stop_reason}")
                    break

                # 8. Trim message history if huge (anti-OOM)
                if len(messages) > self.max_message_history:
                    # Keep system + user + last (N-2)
                    messages = messages[:2] + messages[-(self.max_message_history - 2):]

        except CancellationRequested as ce:
            stop_reason = f"cancelled:{ce.source}:{ce.reason}"[:300]
            epistemic_status = EpistemicStatus.ABORTED
            logger.info(f"[V51] {stop_reason}")

        # ─── Forced synthesis if no final answer ─────────────────────────────
        if not final_answer_content.strip() and epistemic_status != EpistemicStatus.ABORTED:
            final_answer_content = await self._forced_synthesis(
                messages, token, budgets, stop_reason,
            )

        # ─── Finalize workspace ──────────────────────────────────────────────
        # Copy loop signatures + budget snapshot to workspace
        for sig in loop_tracker.history:
            workspace.record_loop_signature(
                iter_idx=sig.iter_idx, tool=sig.tool,
                normalized_args=sig.normalized_args,
                evidence_gain=sig.evidence_gain,
                novelty_score=sig.novelty_score,
            )
        snap = budgets.snapshot()
        workspace.budgets_snapshot.shape = snap["shape"]
        workspace.budgets_snapshot.iterations = snap["counters"]["iterations"]
        workspace.budgets_snapshot.tool_calls = snap["counters"]["tool_calls"]
        workspace.budgets_snapshot.retrieved_chars = snap["counters"]["retrieved_chars"]
        workspace.budgets_snapshot.output_tokens = snap["counters"]["output_tokens"]
        workspace.budgets_snapshot.soft_caps = snap["soft_caps"]
        workspace.budgets_snapshot.hard_caps = snap["hard_caps"]
        workspace.cancellation_snapshot = token.snapshot() if token is not NULL_TOKEN else None

        latency_s = time.time() - t_start
        # Adjust epistemic_status if forced synthesis but completed
        if epistemic_status == EpistemicStatus.COMPLETE and not final_answer_content.strip():
            epistemic_status = EpistemicStatus.ABSTAIN
        workspace.finalize(
            final_answer=final_answer_content or "",
            epistemic_status=epistemic_status,
            stop_reason=stop_reason,
            latency_s=latency_s,
        )

        return AgentRunResult(
            answer=final_answer_content or "",
            epistemic_status=epistemic_status,
            stop_reason=stop_reason,
            workspace=workspace,
            latency_s=latency_s,
        )

    # ─── Sync wrapper (compat) ───────────────────────────────────────────────

    def run(self, *args, **kwargs) -> AgentRunResult:
        """Wrapper synchrone — utilise asyncio.run en interne."""
        return asyncio.run(self.run_async(*args, **kwargs))

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_user_prompt(question: str, tenant_id: str, extra: str) -> str:
        out = f"Question: {question}\n\nTenant: {tenant_id}\n"
        if extra:
            out += f"\n{extra}\n"
        out += "\nUse the reading tools to gather evidence, then provide your final answer with citations [doc=ID]."
        return out

    @staticmethod
    def _extract_evidence_text(tool_result: dict) -> str:
        """Extrait du texte représentatif du résultat (pour novelty_score)."""
        if "error" in tool_result:
            return ""
        r = tool_result.get("result")
        if not isinstance(r, dict):
            return str(r)[:1000]
        # Heuristique : champs texte communs
        for key in ("text", "section_text", "answer", "content"):
            v = r.get(key)
            if isinstance(v, str) and v:
                return v[:2000]
        # Si liste de sections, concat les titres + snippets
        if isinstance(r.get("hits"), list):
            parts = []
            for h in r["hits"][:10]:
                if isinstance(h, dict):
                    parts.append(
                        (h.get("title") or "") + " " + (h.get("snippet") or "")
                    )
            return " ".join(parts)[:2000]
        if isinstance(r.get("outline"), list):
            return " ".join(s.get("title", "") for s in r["outline"][:30])[:2000]
        if isinstance(r.get("section"), dict):
            return (r["section"].get("text") or "")[:2000]
        # Fallback : str(r) truncated
        return json.dumps(r, ensure_ascii=False)[:1500]

    @staticmethod
    def _extract_and_add_evidence(
        workspace: Workspace,
        result: dict,
        evidence_type: EvidenceType,
        source_tool: str,
        iter_idx: int,
    ) -> None:
        """Ajoute au workspace les evidence items extraits du résultat de tool."""
        # Single section (read, read_with_footnotes)
        doc_id = result.get("doc_id") or "?"
        if "section" in result and isinstance(result["section"], dict):
            sec = result["section"]
            workspace.add_evidence(
                evidence_type=evidence_type, doc_id=doc_id,
                section_id=sec.get("section_id"),
                text_excerpt=(sec.get("text") or "")[:2000],
                source_tool=source_tool, iter_idx=iter_idx,
            )
            return
        if "section_id" in result and "text" in result:
            workspace.add_evidence(
                evidence_type=evidence_type, doc_id=doc_id,
                section_id=result.get("section_id"),
                text_excerpt=(result.get("text") or "")[:2000],
                source_tool=source_tool, iter_idx=iter_idx,
            )
            return
        # Hits list (find_in)
        if isinstance(result.get("hits"), list):
            for h in result["hits"][:5]:
                if isinstance(h, dict):
                    workspace.add_evidence(
                        evidence_type=evidence_type, doc_id=doc_id,
                        section_id=h.get("section_id"),
                        text_excerpt=(h.get("snippet") or "")[:1000],
                        source_tool=source_tool, iter_idx=iter_idx,
                    )

    async def _forced_synthesis(
        self,
        messages: list[dict],
        token: CancellationToken,
        budgets: BudgetTracker,
        stop_reason: str,
    ) -> str:
        """Forces une synthèse finale quand max_iter / stagnation / budget."""
        await token.check_async()
        synth_messages = list(messages) + [{
            "role": "user",
            "content": (
                "You've gathered evidence through your tool calls. Now produce "
                "your FINAL ANSWER to the original question, with citations "
                "[doc=ID]. Even if your evidence is partial, give your best "
                "synthesis. Output plain text only — do not call any more tools."
            ),
        }]
        try:
            resp = self.llm.call(synth_messages, tools=[], max_tokens=2000)
            if "error" in resp:
                return ""
            content = (resp["message"].get("content") or "").strip()
            if not content:
                # Fallback : last assistant content
                for m in reversed(messages):
                    if m.get("role") == "assistant" and (m.get("content") or "").strip():
                        return m["content"]
                # Last resort
                return (
                    f"Insufficient evidence after {budgets.tool_calls} tool calls "
                    f"(stop_reason: {stop_reason})."
                )
            return content
        except CancellationRequested:
            return ""


# ─── Default system prompt (EFFICIENCY MANDATE, ADR §3e) ─────────────────────


_DEFAULT_SYSTEM_PROMPT = """You are an EFFICIENT research agent answering questions by navigating structured documents.

EFFICIENCY MANDATE :
- Use the FEWEST tool calls necessary to gather sufficient evidence
- If evidence is sufficient after 1-2 reads → CONCLUDE immediately
- NEVER re-read a section you already read
- NEVER call outline() twice on the same doc
- AVOID 'just in case' exploration

PATTERNS BY ANSWER SHAPE :
- factual : 1 find_in + 1 read should suffice
- listing : 1 outline + 1-2 reads on key sections
- multi_hop : plan-then-execute (2-3 reads on linked sections)
- comparison : compare_sections directly when both targets are known
- false_premise : navigate_by_toc to verify existence FIRST

FORBIDDEN :
- Re-reading the same section
- Outline twice on same doc
- Speculative exploration without hypothesis

Output answers with citations [doc=DOC_ID] for each claim."""
