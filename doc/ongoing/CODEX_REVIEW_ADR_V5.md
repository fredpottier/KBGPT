## 1. Executive verdict

- **Maturity score: 6.8 / 10**
- **Top 3 strengths**
  - The ADR correctly abandons V4.2 instead of trying to patch a broken retrieval-first architecture.
  - The core bet in `3a/3d/3e` is coherent: single-agent, structured tools, persistent document graph, mandatory citations, external verifier.
  - The authors are unusually disciplined about production concerns for a draft ADR: schema, observability, migration, verifier, rate limit, and release gates are all at least named.

- **Top 5 weaknesses (ranked)**
  - **1. `3b` multi-tenant data isolation is not production-safe as written.** `tenant_id` as a property plus a few composite indexes is not a security boundary. A single bad Cypher query or tool bug can cross tenants.
  - **2. `3h` API is under-specified for a long-running agent.** No streaming, no cancellation, no async job mode, no partial results, no idempotency key. That will become an operational problem before it becomes a product problem.
  - **3. `3f` verifier design is underspecified and partly hand-wavy.** “threshold(shape)” is not a method. “1 retry max” prevents infinite loops, but the rerun policy still lacks a formal state machine and failure semantics.
  - **4. `3d` toolset is still too thin for the stated quantitative gap.** `find_quantitative` + `get_table` help, but they do not cover unit normalization, cross-table joins, derived values, temporal deltas, or footnote-dependent numbers.
  - **5. `3a/3c` scaling assumptions are not defended.** 1000 req/h × 50 tenants with p95 < 60s is plausible only if you control concurrency, queueing, provider backpressure, graph hot paths, and ingestion contention. The ADR does not yet prove that.

- **Go / no-go: proceed with mandatory amendments**

The direction is right. The production hardening is not yet sufficient.

## 2. Architecture review (per-section findings)

### `3a` Architecture target
**Solid**
- The split is understandable and operable.
- Single-LLM with tools is a sane complexity ceiling.
- Separating `ReasoningAgent`, `ReadingTools`, `DSG`, `Qdrant`, and `Verifier` is the right fault-domain decomposition.

**Weak**
- The real bottleneck is the `ReasoningAgent` provider dependency, not Neo4j. At the target throughput, model concurrency and provider throttling will dominate.
- `QuestionRouter` is another critical-path inference stage. You are adding latency and another model failure domain before the main agent.
- `GroundingVerifier` is a serial post-step. That hurts tail latency unless you stream the draft answer or verify incrementally.
- No explicit queue/admission-control layer. With 50 tenants, “10 req/min/tenant” still permits synchronized bursts.

**Amendment**
- Add an explicit **request lifecycle**: `accepted -> queued -> running -> verifying -> completed/cancelled/failed`.
- Add **tenant-aware concurrency budgets** and a **global admission controller**.
- Make the router optional: bypass it when caller supplies `answer_shape_hint` with sufficient confidence.
- Define cold-start behavior for DeepSeek/Qwen provider failover and verifier warm pools.

### `3b` DSG Neo4j multi-tenant schema
**Solid**
- `Document` / `Section` / `Table` is the right minimum graph.
- Preserving `section_id` for back-compat is practical.

**Weak**
- `UNIQUE Section.section_id` is wrong for multi-tenant unless `section_id` is globally unique forever. The ADR does not prove that.
- Property-based tenancy is not enough. Query discipline will fail over time.
- Storing full `Section.text` in Neo4j for every section may inflate heap and page cache pressure. Neo4j is the graph index here, not necessarily the best large-text store.
- No answer for document-level ACL evolution, retention, or tenant deletion.

**Amendment**
- Change uniqueness to `(tenant_id, doc_id, section_id)` or use an opaque globally unique internal ID plus tenant-scoped business keys.
- Enforce tenancy in every relationship and tool query, not just node properties.
- Consider storing **canonical text outside Neo4j** and keeping only searchable snippets, spans, and pointers in graph nodes.
- Add deletion and re-ingestion semantics: what happens to orphaned Qdrant points, stale section IDs, and cached workspaces?

### `3c` Ingestion pipeline
**Solid**
- Adding structure extraction at `2.5` is the correct insertion point.
- Extractor versioning is necessary.

**Weak**
- No concurrency model for parallel imports of the same doc, same doc version, or same tenant bulk load.
- No statement about idempotency keys or dedupe.
- No explicit transactional boundary across Neo4j + Qdrant. Partial success creates split-brain state.
- Page-based fallback is acceptable as a rescue path, but using it silently can poison quality metrics.

**Amendment**
- Add **ingestion idempotency** on `(tenant_id, source_uri, content_hash, extractor_version)`.
- Define a **two-phase publish model**: write to staging, validate counts/checksums, then atomically mark active.
- Emit extractor quality flags into the runtime so the agent knows when it is operating on degraded structure.
- Block concurrent “active version” flips per document.

### `3d` Reading tools
Covered in section 3 below.

### `3e` ReasoningAgent V5.1
**Solid**
- Adaptive budget is good.
- Forced plan for multi-hop/comparison/lifecycle is a sensible constraint.
- Workspace schema versioning is exactly right.

**Weak**
- “same_section_revisited > 2” is too naive. Revisiting a hub section is often correct.
- No distinction between **reasoning budget**, **tool budget**, and **token budget**.
- No policy for partial completion when the evidence is mixed but non-empty.
- No formal guard against tool-call oscillation across semantically equivalent arguments.

**Amendment**
- Track a richer loop signature: `(tool, normalized_args, evidence_gain, novelty_score)`.
- Separate hard caps for iterations, tool calls, retrieved chars, and output tokens.
- Add a planner/executor state machine and require the planner to declare an expected evidence shape.

### `3f` GroundingVerifier
Covered in section 4 below.

### `3g` Observability
Covered in section 5 below.

### `3h` API
**Solid**
- The response includes citations, epistemic status, metrics, and versioning.
- `trace_id` correlation is good.

**Weak**
- This contract is not sufficient for 30-90s agentic calls.
- Missing: `stream=true`, `request_id`, `idempotency_key`, `cancel`, `resume`, `partial`, `debug level`, `workspace inline excerpt`, and structured error taxonomy.
- `200 OK` for all outcomes is too coarse. Long-running systems need asynchronous semantics.

**Amendment**
- Support two modes:
  - **Synchronous SSE streaming** for interactive chat.
  - **Async job API** for long reads.
- Add `POST /answer`, `GET /answer/{request_id}`, `POST /answer/{request_id}/cancel`.
- Return partial outputs: current plan, sections read, provisional citations, verifier pending state.

## 3. Reading tools review

The four new tools in `3d` are directionally correct but **not sufficient** to close a quantitative gap from `0.57` to `0.83` by themselves.

`find_quantitative` and `get_table` solve only first-order lookup. EKX-class systems usually win quantitative questions on five harder cases:
- unit normalization across tables/sections,
- derived values (`delta`, `% change`, ratios, min/max over ranges),
- temporal/version comparison,
- footnote-conditioned interpretation,
- entity disambiguation around the metric name.

You are missing at least three tool capabilities:
- **`extract_numeric_evidence(section_id | table_id)`**: returns normalized quantities with unit, entity, time scope, comparator, confidence, and source span.
- **`compute_derived_metric(operation, operands[])`**: deterministic calculator over cited numeric evidence.
- **`resolve_unit_or_alias(metric, unit, context)`**: maps “ARR”, “annual recurring revenue”, “M€”, “million EUR”, etc., through Domain Pack or generic normalization.

On tool-zoo risk: the ADR names the risk, but the design does not yet prevent it. “Strict JSON Schema” and “namespacing” reduce syntax errors. They do **not** reduce semantic overlap. Today `find_in`, `navigate_by_toc`, `expand_context`, and `summarize_subtree` still overlap enough to cause policy ambiguity.

Concrete fix:
- Each tool should declare **when it is the preferred first choice** and **what evidence type it returns**.
- Add offline evaluation for **tool selection accuracy**, **unnecessary tool-call rate**, and **evidence gain per tool**.
- Require every new tool proposal to show a confusion-matrix reduction against existing tools.

One more issue in `3d`: “aucun tool ne retourne du texte synthétisé” is a good principle, but `summarize_subtree` explicitly returns a summary. That is a contradiction. Either allow bounded deterministic summarization or rename the tool and state its trust model clearly.

## 4. Verifier review

The verifier choice in `3f` is reasonable, but not yet convincing enough for a critical production gate.

`HHEM-2.1-Open` is still a strong low-latency baseline, and publicly documented by Vectara as their factual consistency model. `MiniCheck` remains an important comparator because it was designed specifically for efficient grounding/fact-checking on source documents. Public OTel/Phoenix references are current; verifier SOTA is more fragmented, so I would not write “state of the art” so confidently without a bake-off. Relevant references: OpenTelemetry GenAI conventions, Phoenix OTEL support, Vectara HHEM docs/blog, and the MiniCheck paper.[1][2][3][4][5]

Problems with the ADR:
- **Threshold-by-shape is not a method.** It needs calibration data, confidence intervals, and a per-shape ROC/PR tradeoff.
- **Claim segmentation is underspecified.** Verifier quality depends heavily on claim splitting granularity.
- **Citation-scoped NLI is necessary but not sufficient.** A claim can be individually supported yet globally misleading if the answer omits a qualifying section or mixes versions.
- **Rerun semantics are weak.** “re-read these specific sections” may simply reinforce a wrong local optimum.

Recommended changes:
- Run an explicit bake-off: `HHEM-2.1-Open` vs `MiniCheck` vs your Lynx option on your own claim-level validation set, segmented by `answer_shape`.
- Add **answer-level consistency checks** in addition to claim-level entailment:
  - contradictory citations,
  - version mismatch,
  - unsupported numeric transform,
  - missing qualifier detection.
- Formalize rerun:
  - one retry max,
  - retry only if failure mode is `missing evidence` or `citation mismatch`,
  - no retry for `version conflict`, `cross-tenant`, `tool error`, or `cost cap exceeded`.
- Do not present Lynx fallback as settled unless you have measured it on your data.

## 5. Observability review

`3g` picks the right direction but not the full production shape.

Using OpenTelemetry GenAI conventions is sensible, but the current OTel GenAI semantic conventions are still marked **Development**, with migration guidance around versioning/dual emission. That means you should avoid hard-coding your whole observability contract to a moving spec without a compatibility plan.[1][5] Phoenix is a good fit for tracing and evaluation workflows, but it is better at AI debugging than at being your sole high-scale operational telemetry backend.[2][3]

Main issues:
- Cardinality risk: `question`, raw `tenant_id`, `doc_ids`, `section_id`, and tool args can explode traces and metrics cost.
- No separation between **trace data**, **high-cardinality debug events**, and **SLO metrics**.
- Missing production metrics:
  - queue wait time,
  - cancellation rate,
  - provider failover rate,
  - verifier false-negative/false-positive rate from adjudicated samples,
  - tool selection accuracy,
  - citation faithfulness rate,
  - evidence sufficiency rate,
  - degraded-structure answer rate,
  - tenant fairness / throttling saturation.

Yes, `tool_selection_accuracy` and `citation_faithfulness_rate` should be tracked in production, but not only as offline evals. They should exist as:
- online sampled evaluations,
- daily adjudicated batch jobs,
- release gates.

Amendment:
- Use Phoenix for trace inspection, replay, eval datasets, and prompt iteration.
- Export SLO metrics to your normal metrics stack as low-cardinality counters/histograms.
- Define sampling tiers: 100% SLO metrics, sampled traces, and full-content trace capture only for opted-in tenants/admin replay.

## 6. Risks not seen (10+ items)

1. **Cross-tenant leakage through graph/query bugs**. The ADR treats tenancy as a property, not an isolation model.
2. **Prompt injection from documents**. A section can instruct the agent to ignore policy or call tools in a targeted way.
3. **Tool-mediated data exfiltration**. `list_versions` and broad `find_in` are dangerous if argument validation is weak.
4. **Version conflation**. The agent may cite one version while answering about another.
5. **Stale Qdrant / Neo4j divergence** after partial ingestion or rollback.
6. **Cost runaway below the 150k cap**. You can still blow budget with many 80k-token requests if concurrency spikes.
7. **Regression on V4.2 strengths**. V5 may improve multi-hop while becoming worse on cheap factual queries.
8. **Silent degradation from page-based fallback**. Users will not know the system answered on poor structure.
9. **Verifier Goodharting**. The agent may learn to produce verifier-friendly wording rather than user-correct answers.
10. **Provider drift/deprecation risk on DeepSeek-V3.1**. Capability drift, geopolitical restrictions, safety policy changes, or endpoint removal are real operational risks.
11. **Backfill migration downtime and cache invalidation**. Workspace replays and historical benchmarks can break if IDs or spans shift.
12. **“Domain-agnostic” is only partially enforced.** Grep gates catch words, not assumptions embedded in prompts, heuristics, examples, or metric aliases.
13. **Concurrency contention during ingestion and serving** on the same graph/vector infra.
14. **Abstention calibration risk**. “low_confidence” can become a UX dead zone if overused.
15. **No red-team path** for adversarial docs, malformed tables, OCR poison, or deeply nested TOCs.

## 7. Concrete amendments to integrate

1. **Harden multi-tenant isolation in `3b`.** Tenant-scoped keys, mandatory tenant filters in all tool queries, and explicit security review of Cypher generation.
2. **Redesign `3h` as sync-streaming + async-job API.** Add cancellation, idempotency, partial responses, and request lifecycle.
3. **Add numeric evidence tooling.** `extract_numeric_evidence`, unit normalization, and deterministic derived-metric computation.
4. **Formalize verifier policy.** Claim segmentation, calibrated thresholds by shape, typed failure reasons, and a measured bake-off.
5. **Introduce admission control.** Per-tenant concurrency quotas, global queue, cost budget enforcement, and provider circuit breakers.
6. **Make ingestion atomic at publish time.** Stage Neo4j/Qdrant writes, validate, then flip active version.
7. **Track production quality metrics.** `tool_selection_accuracy`, `citation_faithfulness_rate`, `evidence_sufficiency_rate`, and `degraded_structure_rate`.
8. **Add prompt-injection defenses.** Treat document text as untrusted input, prohibit instruction following from retrieved content, and log suspected injection patterns.
9. **Separate cheap vs hard query path.** Keep a low-cost fast path for straightforward factual queries to protect latency and spend.
10. **Replace grep-only domain-agnostic enforcement with policy tests.** Audit prompts, tool descriptions, few-shots, and metric alias maps.

## 8. State-of-the-art alternatives the ADR may have missed

The ADR is right to reject generic “more RAG” thinking, but it misses a few patterns worth borrowing:

- **Hierarchical evidence planning** rather than only ReAct. First choose document/subtree, then section, then span, then synthesis.
- **Deterministic evidence programs** for quantitative questions. Enterprise systems increasingly separate numeric extraction from answer generation.
- **Incremental verification** during reasoning, not only at the end.
- **Hybrid graph + columnar evidence store** for tables, where numeric retrieval is not forced through the same path as prose retrieval.
- **Small specialized planners** or policy models for tool selection, instead of making the main LLM learn all tool policy implicitly.
- **Asynchronous agent UX** with traceable intermediate artifacts as first-class product output.

The ADR has the right backbone. It is not yet production-credible until tenancy, API lifecycle, verifier calibration, and quantitative evidence handling are tightened.

**Sources**
- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OpenTelemetry GenAI spans/metrics](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/) and [metrics](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/)
- [Arize Phoenix docs](https://arize.com/docs/phoenix/)
- [Vectara HHEM-2.1](https://www.vectara.com/blog/hhem-2-1-a-better-hallucination-detection-model)
- [MiniCheck paper page](https://huggingface.co/papers/2404.10774)

[1]: https://opentelemetry.io/docs/specs/semconv/gen-ai/
[2]: https://arize.com/docs/phoenix/
[3]: https://www.vectara.com/blog/hhem-2-1-a-better-hallucination-detection-model
[4]: https://huggingface.co/papers/2404.10774
[5]: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/
