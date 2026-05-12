## Re-challenge ADR V5.1 V1.1 — Codex final pass

### 1. Verdict
- Maturity score V1.1: **8.4 / 10** (was **6.8 / 10** in V1.0)
- Final: **ACCEPT WITH MINOR EDITS**

V1.1 is materially stronger. The team did not just add prose; they converted most of the prior objections into explicit controls, gates, and rollout mechanics. The ADR is now broadly production-credible.

The remaining issues are not architecture-breaking, but a few points are still not fully closed: the capacity math is not yet internally consistent, the V4.2 contextual regression is mitigated rather than eliminated, and migration/cache behavior still needs one more layer of operational precision.

### 2. Concern-by-concern resolution table

| # | Concern V1.0 | Section V1.1 addressing it | Status | Remaining gap |
|---|---|---|---|---|
| 1 | Multi-tenant Neo4j isolation insufficient | `3b`, `3i.3`, `8.5` (lines 188-258, 600-604, 789-793) | **RESOLVED ✓** | Composite keys, `TenantQueryGuard`, cross-tenant CI tests, purge procedure, and audit logging close the original gap. |
| 2 | API streaming/cancel/async under-specified | `3h`, `3a` (lines 481-584, 160) | **RESOLVED ✓** | SSE event model, async job mode, cancel endpoint, typed lifecycle, idempotency key, and error taxonomy are now explicit enough for implementation. |
| 3 | Verifier hand-wavy, no claim segmentation / answer consistency | `3f`, `8.1`, `7.R2/R9/R15` (lines 363-417, 777-782, 739/746/752) | **RESOLVED ✓** | Claim segmentation, answer-level checks, shape-calibrated thresholds, typed failures, and limited retry policy address the core concern. |
| 4 | Reading tools insufficient for quantitative gap | `3a`, `3d`, `5` (lines 121-129, 308-312, 688-690) | **RESOLVED ✓** | The numeric toolchain is now explicit: `find_quantitative`, `get_table`, `extract_numeric_evidence`, `compute_derived_metric`, plus a mandatory mini-POC gate. |
| 5 | Tool zoo risk not prevented by JSON Schema alone | `3d`, `7.R10`, `8.4` (lines 294-329, 747, 787) | **RESOLVED ✓** | Public registry cap, `experimental_*` namespace, proposal-time confusion matrix, live selection metrics, and removal gate go beyond schema hygiene. |
| 6 | Scaling `1000 req/h × 50 tenants` not quantitatively defended | `3a.2`, `4`, `8.2-8.3` (lines 168-186, 648-650, 783-787) | **PARTIALLY ADDRESSED ⚠** | There is real capacity planning now, but the math is not fully coherent. `17 req/min` implies ~`1000 req/h` aggregate, not `1000 req/h × 50 tenants`. More importantly, token demand is stated as `66M tok/h sustained` while the hard cap is `50M tok/h`. That needs reconciliation. |
| 7 | Prompt injection via documents not addressed | `3i.1`, `7.R13`, `8.5` (lines 589-594, 750, 789-793) | **RESOLVED ✓** | Treating document content as untrusted, wrapping tool output, prompt rules, tool-call gating, and red-team PDFs are the right controls at ADR level. |
| 8 | DeepSeek vendor risk: sanctions / deprecation / drift | `3i.7`, `3e`, `7.R3`, `8.6` (lines 630-634, 359, 740, 813) | **PARTIALLY ADDRESSED ⚠** | Better than V1.0: configurable primary, fallback model, golden tests, circuit breaker, monitoring. Still missing: day-0 hot standby posture and a defined switchover runbook/SLO if DeepSeek becomes unavailable immediately. "`< 1 semaine`" is mitigation, not full resilience. |
| 9 | “Domain-agnostic” enforcement weak | `3i.6`, `8.9`, `7.R8` (lines 619-628, 804, 745) | **RESOLVED ✓** | AST-based audits of prompts, tools, few-shots, and metric aliases with CI blocking is a meaningful upgrade over grep. |
| 10 | Verifier Goodharting risk, no prod-time citation faithfulness measurement | `3g`, `7.R9`, `8.1`, `8.6` (lines 452-458, 746, 781, 795) | **RESOLVED ✓** | Production-time citation faithfulness is now explicitly measured through sampled human adjudication and promoted to a release gate. |
| 11 | Regression on V4.2 strengths, especially contextual `-10pp` | `4.1`, `7.R18`, `8.1`, `5` (lines 677-680, 755, 780, 691) | **PARTIALLY ADDRESSED ⚠** | This is now acknowledged and operationalized, but not fully retired. The ADR accepts recovery to `0.78` and allows up to `5pp` residual regression versus V4.2. That is defensible, but it means the issue is mitigated, not solved. |
| 12 | Migration risks: cache invalidation, ID stability | `3c`, `4.1`, `7.R5/R16/R21/R23` (lines 260-292, 663-668, 742/753/758/760) | **PARTIALLY ADDRESSED ⚠** | Stable hash-based `section_id`, alias map, two-phase publish, and shadow deployment help a lot. What remains underspecified is cache invalidation/versioning across runtime caches and clients after atomic flip. The ADR names the risk, but does not yet define cache key versioning or stale-read expiry rules. |

### 3. Top 3 remaining concerns

**1. Capacity planning is improved but still not fully defensible.**  
`3a.2` is a major step forward, but the target statement and the budget table do not line up cleanly. If the intended load is aggregate across 50 tenants, say so explicitly. If it is truly `1000 req/h × 50 tenants`, the sizing is far too small. Separately, the token row currently states a sustained requirement above the hard cap. That is the main remaining “architecture confidence” issue.

**2. The contextual regression is controlled, not fully cured.**  
`4.1` and `8.1` make this far better than V1.0 because the regression is now a tracked deployment gate with rollback triggers. Still, the proposed acceptance criterion tolerates a residual loss against V4.2. That may be acceptable commercially, but it should be framed as an explicit business tradeoff, not as a fully closed technical issue.

**3. Migration/cache semantics need one more operational pass.**  
`3c` solves the dangerous part of data publication, and the alias map is the right move for ID drift. But the ADR still does not define how any in-process cache, Redis dedup state, UI workspace snapshot, or retrieval cache is invalidated or version-scoped after a document flip. That is the kind of omission that causes subtle production bugs after an otherwise clean migration.

### 4. Specific improvements to reach ≥9/10

1. In `3a.2`, rewrite the load target unambiguously as either aggregate or per-tenant, then reconcile every row in the sizing table against that exact assumption. Fix the `66M tok/h` vs `50M tok/h` contradiction.
2. Add a short “cache/versioning contract” in `3c`: cache key schema, invalidation trigger on atomic flip, TTL rules, and whether `request_id`/workspace views are pinned to a document version.
3. Strengthen `3i.7` from “Qwen configurable as primary in <1 week” to “Qwen validated as warm standby at release,” with a tested switchover procedure and recovery SLO.
4. In `4.1`, tighten the contextual gate from “recover 8pp” to a direct requirement expressed versus V4.2 per tenant or per corpus, so the tolerated regression is explicit and measurable.
5. In `3g`, define the minimum production sampling rate for citation-faithfulness adjudication, so the anti-Goodharting control is not left to operator discretion.

### 5. Final go/no-go recommendation

This ADR is no longer in “mandatory rework” territory. V1.1 closes most of the substantive objections from the prior review: tenant isolation is now credible, the API is production-shaped, the verifier is much more rigorous, the quantitative gap is addressed with actual tooling, and the threat model is no longer missing.

My recommendation is **go with ACCEPT WITH MINOR EDITS**. I would not block implementation on the remaining items, but I would require the capacity-plan correction and the cache/versioning note before treating the ADR as fully hardened. If those are tightened, this document is comfortably in the **9/10-class** range.
tokens used
26 621
## Re-challenge ADR V5.1 V1.1 — Codex final pass

### 1. Verdict
- Maturity score V1.1: **8.4 / 10** (was **6.8 / 10** in V1.0)
- Final: **ACCEPT WITH MINOR EDITS**

V1.1 is materially stronger. The team did not just add prose; they converted most of the prior objections into explicit controls, gates, and rollout mechanics. The ADR is now broadly production-credible.

The remaining issues are not architecture-breaking, but a few points are still not fully closed: the capacity math is not yet internally consistent, the V4.2 contextual regression is mitigated rather than eliminated, and migration/cache behavior still needs one more layer of operational precision.

### 2. Concern-by-concern resolution table

| # | Concern V1.0 | Section V1.1 addressing it | Status | Remaining gap |
|---|---|---|---|---|
| 1 | Multi-tenant Neo4j isolation insufficient | `3b`, `3i.3`, `8.5` (lines 188-258, 600-604, 789-793) | **RESOLVED ✓** | Composite keys, `TenantQueryGuard`, cross-tenant CI tests, purge procedure, and audit logging close the original gap. |
| 2 | API streaming/cancel/async under-specified | `3h`, `3a` (lines 481-584, 160) | **RESOLVED ✓** | SSE event model, async job mode, cancel endpoint, typed lifecycle, idempotency key, and error taxonomy are now explicit enough for implementation. |
| 3 | Verifier hand-wavy, no claim segmentation / answer consistency | `3f`, `8.1`, `7.R2/R9/R15` (lines 363-417, 777-782, 739/746/752) | **RESOLVED ✓** | Claim segmentation, answer-level checks, shape-calibrated thresholds, typed failures, and limited retry policy address the core concern. |
| 4 | Reading tools insufficient for quantitative gap | `3a`, `3d`, `5` (lines 121-129, 308-312, 688-690) | **RESOLVED ✓** | The numeric toolchain is now explicit: `find_quantitative`, `get_table`, `extract_numeric_evidence`, `compute_derived_metric`, plus a mandatory mini-POC gate. |
| 5 | Tool zoo risk not prevented by JSON Schema alone | `3d`, `7.R10`, `8.4` (lines 294-329, 747, 787) | **RESOLVED ✓** | Public registry cap, `experimental_*` namespace, proposal-time confusion matrix, live selection metrics, and removal gate go beyond schema hygiene. |
| 6 | Scaling `1000 req/h × 50 tenants` not quantitatively defended | `3a.2`, `4`, `8.2-8.3` (lines 168-186, 648-650, 783-787) | **PARTIALLY ADDRESSED ⚠** | There is real capacity planning now, but the math is not fully coherent. `17 req/min` implies ~`1000 req/h` aggregate, not `1000 req/h × 50 tenants`. More importantly, token demand is stated as `66M tok/h sustained` while the hard cap is `50M tok/h`. That needs reconciliation. |
| 7 | Prompt injection via documents not addressed | `3i.1`, `7.R13`, `8.5` (lines 589-594, 750, 789-793) | **RESOLVED ✓** | Treating document content as untrusted, wrapping tool output, prompt rules, tool-call gating, and red-team PDFs are the right controls at ADR level. |
| 8 | DeepSeek vendor risk: sanctions / deprecation / drift | `3i.7`, `3e`, `7.R3`, `8.6` (lines 630-634, 359, 740, 813) | **PARTIALLY ADDRESSED ⚠** | Better than V1.0: configurable primary, fallback model, golden tests, circuit breaker, monitoring. Still missing: day-0 hot standby posture and a defined switchover runbook/SLO if DeepSeek becomes unavailable immediately. "`< 1 semaine`" is mitigation, not full resilience. |
| 9 | “Domain-agnostic” enforcement weak | `3i.6`, `8.9`, `7.R8` (lines 619-628, 804, 745) | **RESOLVED ✓** | AST-based audits of prompts, tools, few-shots, and metric aliases with CI blocking is a meaningful upgrade over grep. |
| 10 | Verifier Goodharting risk, no prod-time citation faithfulness measurement | `3g`, `7.R9`, `8.1`, `8.6` (lines 452-458, 746, 781, 795) | **RESOLVED ✓** | Production-time citation faithfulness is now explicitly measured through sampled human adjudication and promoted to a release gate. |
| 11 | Regression on V4.2 strengths, especially contextual `-10pp` | `4.1`, `7.R18`, `8.1`, `5` (lines 677-680, 755, 780, 691) | **PARTIALLY ADDRESSED ⚠** | This is now acknowledged and operationalized, but not fully retired. The ADR accepts recovery to `0.78` and allows up to `5pp` residual regression versus V4.2. That is defensible, but it means the issue is mitigated, not solved. |
| 12 | Migration risks: cache invalidation, ID stability | `3c`, `4.1`, `7.R5/R16/R21/R23` (lines 260-292, 663-668, 742/753/758/760) | **PARTIALLY ADDRESSED ⚠** | Stable hash-based `section_id`, alias map, two-phase publish, and shadow deployment help a lot. What remains underspecified is cache invalidation/versioning across runtime caches and clients after atomic flip. The ADR names the risk, but does not yet define cache key versioning or stale-read expiry rules. |

### 3. Top 3 remaining concerns

**1. Capacity planning is improved but still not fully defensible.**  
`3a.2` is a major step forward, but the target statement and the budget table do not line up cleanly. If the intended load is aggregate across 50 tenants, say so explicitly. If it is truly `1000 req/h × 50 tenants`, the sizing is far too small. Separately, the token row currently states a sustained requirement above the hard cap. That is the main remaining “architecture confidence” issue.

**2. The contextual regression is controlled, not fully cured.**  
`4.1` and `8.1` make this far better than V1.0 because the regression is now a tracked deployment gate with rollback triggers. Still, the proposed acceptance criterion tolerates a residual loss against V4.2. That may be acceptable commercially, but it should be framed as an explicit business tradeoff, not as a fully closed technical issue.

**3. Migration/cache semantics need one more operational pass.**  
`3c` solves the dangerous part of data publication, and the alias map is the right move for ID drift. But the ADR still does not define how any in-process cache, Redis dedup state, UI workspace snapshot, or retrieval cache is invalidated or version-scoped after a document flip. That is the kind of omission that causes subtle production bugs after an otherwise clean migration.

### 4. Specific improvements to reach ≥9/10

1. In `3a.2`, rewrite the load target unambiguously as either aggregate or per-tenant, then reconcile every row in the sizing table against that exact assumption. Fix the `66M tok/h` vs `50M tok/h` contradiction.
2. Add a short “cache/versioning contract” in `3c`: cache key schema, invalidation trigger on atomic flip, TTL rules, and whether `request_id`/workspace views are pinned to a document version.
3. Strengthen `3i.7` from “Qwen configurable as primary in <1 week” to “Qwen validated as warm standby at release,” with a tested switchover procedure and recovery SLO.
4. In `4.1`, tighten the contextual gate from “recover 8pp” to a direct requirement expressed versus V4.2 per tenant or per corpus, so the tolerated regression is explicit and measurable.
5. In `3g`, define the minimum production sampling rate for citation-faithfulness adjudication, so the anti-Goodharting control is not left to operator discretion.

### 5. Final go/no-go recommendation

This ADR is no longer in “mandatory rework” territory. V1.1 closes most of the substantive objections from the prior review: tenant isolation is now credible, the API is production-shaped, the verifier is much more rigorous, the quantitative gap is addressed with actual tooling, and the threat model is no longer missing.

My recommendation is **go with ACCEPT WITH MINOR EDITS**. I would not block implementation on the remaining items, but I would require the capacity-plan correction and the cache/versioning note before treating the ADR as fully hardened. If those are tightened, this document is comfortably in the **9/10-class** range.
