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
from knowbase.runtime_v5.observability.metrics import (
    MetricsRegistry,
    get_default_metrics,
)
from knowbase.runtime_v5.observability.tracer import (
    ObservabilityTracer,
    SpanContext,
    SpanStatus,
    get_default_tracer,
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
    verifier_report: Optional[dict] = None  # S7 passive mode (Mode A)

    def to_dict(self) -> dict:
        d = {
            "answer": self.answer,
            "epistemic_status": self.epistemic_status.value,
            "stop_reason": self.stop_reason,
            "latency_s": self.latency_s,
            "workspace_summary": self.workspace.summary(),
        }
        if self.verifier_report is not None:
            d["verifier_report"] = self.verifier_report
        return d


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
        tracer: Optional[ObservabilityTracer] = None,
        metrics: Optional[MetricsRegistry] = None,
        verifier=None,  # GroundingVerifier optional (Mode A passive S7.7)
    ):
        self.llm = llm_caller
        self.registry = registry or get_default_registry()
        self.sanitizer = sanitizer or ToolCallSanitizer(self.registry)
        self.max_message_history = max_message_history
        self.tracer = tracer or get_default_tracer()
        self.metrics = metrics or get_default_metrics()
        self.verifier = verifier  # None = skip verification
        # Pre-register metrics (low-cardinality SLO ADR §3g)
        self._m_agent_duration = self.metrics.histogram(
            "agent_answer_duration_s",
            help_text="End-to-end agent run duration (seconds)",
            label_keys=["shape", "epistemic_status"],
        )
        self._m_agent_iter = self.metrics.histogram(
            "agent_iterations",
            help_text="Iterations per run",
            label_keys=["shape"],
            buckets=(1, 2, 3, 5, 8, 12),
        )
        self._m_tool_calls = self.metrics.counter(
            "tool_calls_total",
            help_text="Total tool calls",
            label_keys=["tool", "outcome"],  # outcome=ok|repaired|error
        )
        self._m_tool_repair = self.metrics.counter(
            "tool_call_repair_total",
            help_text="Tool calls with sanitizer repair applied",
            label_keys=["tool"],
        )
        self._m_stop_reason = self.metrics.counter(
            "agent_stop_reason_total",
            help_text="Stop reason counters",
            label_keys=["reason"],
        )

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

        # Root span : gen_ai.agent.answer (ADR §3g hierarchy)
        # Géré manuellement (pas via SpanContext) car on l'end dans le finally
        # APRÈS récupération des stats finales.
        root_span = self.tracer.start_span(
            "gen_ai.agent.answer",
            attributes={
                "tenant_id": tenant_id,
                "answer_shape": answer_shape or "unknown",
                "request_id": workspace.request_id,
                # NOTE : question pas dans les attributs (PII tier3 only)
            },
        )

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

                # 4. LLM call (sub-span : gen_ai.inference)
                budgets.increment_iteration()
                tool_schemas = self.registry.to_llm_tools()
                with SpanContext(
                    self.tracer, "gen_ai.inference",
                    parent_span=root_span,
                    attributes={
                        "iter": budgets.iterations,
                        "n_tools": len(tool_schemas),
                    },
                ) as llm_span:
                    llm_resp = self.llm.call(messages, tool_schemas, max_tokens=2000)
                    if "error" in llm_resp:
                        llm_span.set_attribute("error", llm_resp["error"])
                        llm_span.set_status(SpanStatus.ERROR, llm_resp["error"])
                        stop_reason = f"llm_error:{llm_resp['error']}"
                        epistemic_status = EpistemicStatus.ABORTED
                        break

                    msg = llm_resp["message"]
                    usage = llm_resp.get("usage", {})
                    completion_tokens = usage.get("completion_tokens", 0)
                    llm_span.set_attributes({
                        "completion_tokens": completion_tokens,
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                    })
                budgets.add_output_tokens(completion_tokens)
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

                    # 6b. Execute tool (sub-span : gen_ai.execute_tool)
                    with SpanContext(
                        self.tracer, "gen_ai.execute_tool",
                        parent_span=root_span,
                        attributes={
                            "tool_name": fn_name,
                            "iter": iter_idx,
                            "repair_applied": repair_applied,
                        },
                    ) as tool_span:
                        t_tool = time.time()
                        try:
                            if spec.handler is None:
                                tool_result = {"error": f"tool '{fn_name}' has no handler"}
                            else:
                                tool_result = {"result": spec.handler(**tool_args_clean)}
                        except Exception as ex:
                            tool_result = {"error": f"{type(ex).__name__}: {ex}"}
                            tool_span.set_status(SpanStatus.ERROR, str(ex))
                        tool_latency_ms = (time.time() - t_tool) * 1000.0
                        tool_span.set_attribute("latency_ms", tool_latency_ms)
                    budgets.increment_tool_call()
                    # Metric counter
                    outcome = (
                        "error" if "error" in tool_result
                        else "repaired" if repair_applied
                        else "ok"
                    )
                    self._m_tool_calls.inc(labels={"tool": fn_name, "outcome": outcome})
                    if repair_applied:
                        self._m_tool_repair.inc(labels={"tool": fn_name})

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
            root_span.set_status(SpanStatus.ERROR, "cancelled")
            logger.info(f"[V51] {stop_reason}")
        except Exception as e:
            root_span.record_exception(e)
            raise

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

        # ─── S7 verifier passive mode (Mode A) ───────────────────────────────
        # Run verifier post-hoc to measure correlation outcome ↔ judge score.
        # Does NOT modify final_answer_content. Report stored in result.
        verifier_report = self._run_verifier_passive(
            workspace, final_answer_content, answer_shape,
        )

        # ─── Metrics + close root span ──────────────────────────────────────
        shape_label = answer_shape or "unknown"
        status_label = epistemic_status.value
        self._m_agent_duration.observe(latency_s, labels={
            "shape": shape_label, "epistemic_status": status_label,
        })
        self._m_agent_iter.observe(budgets.iterations, labels={"shape": shape_label})
        self._m_stop_reason.inc(labels={"reason": stop_reason[:60] or "concluded"})

        # Attribs finaux sur root span + close
        root_span.set_attributes({
            "epistemic_status": status_label,
            "stop_reason": stop_reason[:200],
            "n_iterations": budgets.iterations,
            "n_tool_calls": budgets.tool_calls,
            "n_evidence_items": len(workspace.evidence_collected),
            "latency_s": latency_s,
            "output_tokens": budgets.output_tokens,
            "retrieved_chars": budgets.retrieved_chars,
        })
        if root_span.status == SpanStatus.UNSET:
            root_span.set_status(
                SpanStatus.OK if epistemic_status not in
                (EpistemicStatus.ABORTED,) else SpanStatus.ERROR
            )
        self.tracer.end_span(root_span)

        return AgentRunResult(
            answer=final_answer_content or "",
            epistemic_status=epistemic_status,
            stop_reason=stop_reason,
            workspace=workspace,
            latency_s=latency_s,
            verifier_report=verifier_report,
        )

    # ─── Verifier passive (Mode A S7.7) ──────────────────────────────────────

    def _run_verifier_passive(
        self,
        workspace: Workspace,
        final_answer: str,
        answer_shape: Optional[str],
    ) -> Optional[dict]:
        """Run verifier post-hoc (Mode A). Does NOT modify final_answer.

        Returns compact dict with outcome + counts, or None if verifier disabled
        or answer empty.
        """
        if self.verifier is None:
            return None
        if not final_answer or not final_answer.strip():
            return None

        # Build evidence_by_citation from workspace.evidence_collected.
        # Key by doc_id AND section_id for citation matching.
        evidence_by_citation: dict[str, str] = {}
        for ev in workspace.evidence_collected:
            if ev.doc_id and ev.text_excerpt:
                # Doc-level key (concat if multiple sections for same doc)
                prev = evidence_by_citation.get(ev.doc_id, "")
                evidence_by_citation[ev.doc_id] = (
                    f"{prev}\n\n{ev.text_excerpt}" if prev else ev.text_excerpt
                )[:8000]
                if ev.section_id:
                    evidence_by_citation[ev.section_id] = ev.text_excerpt[:8000]

        try:
            report = self.verifier.verify(
                answer_text=final_answer,
                evidence_by_citation=evidence_by_citation,
                answer_shape=answer_shape,
                cited_tool_names=None,
            )
        except Exception as exc:
            logger.warning("[V51] verifier failed: %s", exc)
            return {"error": str(exc)[:200]}

        # Compact report (avoid large NLI claim details in API response)
        n_supported = sum(
            1 for r in report.nli_results if r.decision.value == "supported"
        )
        n_contradicted = sum(
            1 for r in report.nli_results if r.decision.value == "contradicted"
        )
        n_neutral = sum(
            1 for r in report.nli_results if r.decision.value == "neutral"
        )
        scores = [r.score for r in report.nli_results]
        return {
            "outcome": report.outcome.value if hasattr(report.outcome, "value") else str(report.outcome),
            "backend_name": report.backend_name,
            "n_claims": len(report.claims),
            "n_supported": n_supported,
            "n_contradicted": n_contradicted,
            "n_neutral": n_neutral,
            "n_failures": len(report.failures),
            "support_rate": (
                n_supported / len(report.nli_results) if report.nli_results else 0.0
            ),
            "mean_nli_score": (sum(scores) / len(scores)) if scores else 0.0,
            "min_nli_score": min(scores) if scores else 0.0,
            "latency_ms": report.latency_ms,
            "failure_reasons": [
                f.reason.value if hasattr(f.reason, "value") else str(f.reason)
                for f in report.failures
            ][:10],
        }

    # ─── Sync wrapper (compat) ───────────────────────────────────────────────

    def run(self, *args, **kwargs) -> AgentRunResult:
        """Wrapper synchrone — utilise asyncio.run en interne."""
        return asyncio.run(self.run_async(*args, **kwargs))

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_user_prompt(question: str, tenant_id: str, extra: str) -> str:
        # Listing enrichi (A6) + Domain Pack hints (A10).
        from knowbase.runtime_v5.doc_topics_loader import (
            format_available_docs_listing,
            load_doc_topics,
        )
        records = load_doc_topics(tenant_id=tenant_id)
        if records:
            docs_listing = format_available_docs_listing(records)
        else:
            from knowbase.runtime_v5.structure_loader import list_available_doc_ids
            try:
                docs = list_available_doc_ids()
            except Exception:
                docs = []
            docs_listing = (
                "\n".join(f"  - {d}" for d in docs) if docs else "  (corpus not indexed)"
            )

        # A10 Domain Pack hints (filtered by query terms)
        # Charte respectée : mécanisme générique, pack tenant-scoped.
        # Skip si désactivé via env (V5_DOMAIN_PACK_ENABLED=0).
        pack_hints_block = ""
        if os.getenv("V5_DOMAIN_PACK_ENABLED", "1") in ("1", "true", "True"):
            try:
                from knowbase.runtime_v5.domain_pack_loader import (
                    load_pack, filter_pack_for_query, format_hints_block,
                )
                pack = load_pack()  # default = enterprise_sap via env V5_DEFAULT_DOMAIN_PACK
                if pack:
                    hints = filter_pack_for_query(pack, question, max_items=12)
                    pack_hints_block = format_hints_block(hints)
            except Exception as exc:
                logger.warning("[V51] domain_pack hints failed: %s", exc)

        out = (
            f"Question: {question}\n\n"
            f"Tenant: {tenant_id}\n\n"
            f"available_docs:\n{docs_listing}\n"
        )
        if pack_hints_block:
            out += f"\n{pack_hints_block}\n"
        if extra:
            out += f"\n{extra}\n"
        out += (
            "\nUse the topics/terms above as routing hints to pick the most "
            "relevant document(s) BEFORE calling outline() or read().\n"
            "Plan your approach, use the reading tools to gather evidence, "
            "and produce a final answer with citations [doc=ID]."
        )
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
