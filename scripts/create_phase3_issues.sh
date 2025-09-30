#!/bin/bash
# Script to create Phase 3 Closure issues
# Run: bash scripts/create_phase3_issues.sh

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "❌ gh CLI not found. Please install it: https://cli.github.com/"
    echo "Or create issues manually using the templates below."
    exit 1
fi

echo "Creating 13 Phase 3 Closure issues..."

# Issue 1: RBAC for approve/reject/delete
gh issue create \
  --title "[P0][fix] RBAC for approve/reject/delete" \
  --body "**Priority**: P0 (Critical)
**Type**: fix
**Milestone**: M1

## Scope
Enforce role-based access (expert/admin) using \`UserContext\` for approve, reject, delete routes.

## Files
- \`src/knowbase/api/routers/facts_governance.py\`

## Acceptance Criteria
- [ ] Requests without sufficient role return 403 with clear message
- [ ] Existing unit/integration tests pass
- [ ] Add tests for 403 cases

## Notes
Role source is \`UserContextMiddleware\`; add small helper to assert roles.

## Related
Phase 3 Closure - Issue #1/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P0,bug,phase-3"

echo "✅ Issue 1 created"

# Issue 2: Persistent reject + audit
gh issue create \
  --title "[P0][fix] Persistent reject + audit" \
  --body "**Priority**: P0 (Critical)
**Type**: fix
**Milestone**: M1

## Scope
Add store method to persist \`status=rejected\` with \`rejection_reason\`, \`rejected_by\`, \`rejected_at\`, and keep audit episode.

## Files
- \`src/knowbase/common/graphiti/graphiti_store.py\`
- \`src/knowbase/api/services/facts_governance_service.py\`

## Acceptance Criteria
- [ ] After \`PUT /api/facts/{id}/reject\`, \`GET /api/facts/{id}\` reflects status rejected and metadata
- [ ] Add/extend tests for persisted reject

## Related
Phase 3 Closure - Issue #2/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P0,bug,phase-3"

echo "✅ Issue 2 created"

# Issue 3: Soft-delete flag + default exclusion
gh issue create \
  --title "[P0][feat] Soft-delete flag + default exclusion" \
  --body "**Priority**: P0 (Critical)
**Type**: feat
**Milestone**: M1

## Scope
Introduce \`deleted=true\` flag on facts; exclude by default from \`list_facts\`, optionally include via a filter.

## Files
- \`src/knowbase/common/graphiti/graphiti_store.py\`
- \`src/knowbase/api/services/facts_governance_service.py\`
- Router delete handler

## Acceptance Criteria
- [ ] \`DELETE /api/facts/{id}\` marks deleted and returns 204
- [ ] Item no longer appears in list
- [ ] Add tests for deletion visibility and optional include

## Related
Phase 3 Closure - Issue #3/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P0,enhancement,phase-3"

echo "✅ Issue 3 created"

# Issue 4: Conflict detection enrichment
gh issue create \
  --title "[P1][feat] Conflict detection enrichment" \
  --body "**Priority**: P1 (High)
**Type**: feat
**Milestone**: M2

## Scope
Enrich types (use store-provided type), implement \`TEMPORAL_OVERLAP\` via \`valid_from/valid_until\`, add simple contradiction rules.

## Files
- \`src/knowbase/common/graphiti/graphiti_store.py\`
- \`src/knowbase/api/services/facts_governance_service.py\`

## Acceptance Criteria
- [ ] \`/api/facts/conflicts/list\` returns populated \`by_type\` with multiple types
- [ ] Descriptions specific
- [ ] Unit/integration tests covering temporal overlap + value mismatch

## Related
Phase 3 Closure - Issue #4/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P1,enhancement,phase-3"

echo "✅ Issue 4 created"

# Issue 5: get_conflicts performance
gh issue create \
  --title "[P1][perf] get_conflicts performance" \
  --body "**Priority**: P1 (High)
**Type**: perf
**Milestone**: M2

## Scope
Reduce O(N × detect) patterns; implement batch detection or prefilter and cap.

## Files
- \`src/knowbase/api/services/facts_governance_service.py\`

## Acceptance Criteria
- [ ] With synthetic 500 facts, endpoint returns under ~1s locally
- [ ] Add simple timing assertion (marked slow)

## Related
Phase 3 Closure - Issue #5/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P1,performance,phase-3"

echo "✅ Issue 5 created"

# Issue 6: Frontend pending: real user IDs
gh issue create \
  --title "[P1][fix] Frontend pending: real user IDs" \
  --body "**Priority**: P1 (High)
**Type**: fix
**Milestone**: M2

## Scope
Replace placeholder \`\"current_user\"\` by actual user ID from frontend context/header.

## Files
- \`frontend/src/app/governance/pending/page.tsx\`

## Acceptance Criteria
- [ ] Approve/reject flows include correct \`approver_id\`/\`rejector_id\`

## Related
Phase 3 Closure - Issue #6/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P1,bug,phase-3,frontend"

echo "✅ Issue 6 created"

# Issue 7: Conflicts UI hardening
gh issue create \
  --title "[P2][feat] Conflicts UI hardening" \
  --body "**Priority**: P2 (Normal)
**Type**: feat
**Milestone**: M3

## Scope
Consume \`/api/facts/conflicts/list\`, show totals by type/severity, handle empty/error states, link to fact.

## Files
- \`frontend/src/app/governance/conflicts/page.tsx\`

## Acceptance Criteria
- [ ] UX shows counts and a list with navigation
- [ ] Empty state message present
- [ ] Errors surfaced

## Related
Phase 3 Closure - Issue #7/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P2,enhancement,phase-3,frontend"

echo "✅ Issue 7 created"

# Issue 8: UTF-8 normalization for FR content
gh issue create \
  --title "[P2][fix] UTF-8 normalization for FR content" \
  --body "**Priority**: P2 (Normal)
**Type**: fix
**Milestone**: M3

## Scope
Fix mojibake in French text (docstrings, log messages, UI labels) to proper UTF-8.

## Files
- Code/docstrings in Facts/KG services and schemas
- UI copy

## Acceptance Criteria
- [ ] No corrupted characters in UI and generated docs/logs

## Related
Phase 3 Closure - Issue #8/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P2,bug,phase-3,i18n"

echo "✅ Issue 8 created"

# Issue 9: Auto-create user group on demand
gh issue create \
  --title "[P2][feat] Auto-create user group on demand" \
  --body "**Priority**: P2 (Normal)
**Type**: feat
**Milestone**: M3

## Scope
Ensure \`set_group\` creates the group if it doesn't exist (idempotent), or verifies existence.

## Files
- \`src/knowbase/common/graphiti/graphiti_store.py\`

## Acceptance Criteria
- [ ] First call with a new \`X-User-ID\` works without pre-provisioning
- [ ] Add minimal test

## Related
Phase 3 Closure - Issue #9/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P2,enhancement,phase-3"

echo "✅ Issue 9 created"

# Issue 10: Deployment/docs for Graphiti
gh issue create \
  --title "[P2][doc] Deployment/docs for Graphiti" \
  --body "**Priority**: P2 (Normal)
**Type**: doc
**Milestone**: M3

## Scope
Document env variables, provide reference docker compose (if service mode), clarify Neo4j/API keys/timeouts.

## Files
- \`doc/GRAPHITI_INTEGRATION_PLAN.md\`
- \`doc/GRAPHITI_POC_ADDENDUM.md\`
- \`.env.example\`
- Compose file

## Acceptance Criteria
- [ ] Clear local setup guide
- [ ] Compose example runs
- [ ] Env keys listed in \`.env.example\`

## Related
Phase 3 Closure - Issue #10/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P2,documentation,phase-3"

echo "✅ Issue 10 created"

# Issue 11: Tests expansion Phase 3
gh issue create \
  --title "[P1][test] Tests expansion Phase 3" \
  --body "**Priority**: P1 (High)
**Type**: test
**Milestone**: M2

## Scope
Add tests for 403 RBAC, persisted reject, soft-delete, temporal conflict, perf (slow-marked).

## Files
- \`tests/integration/test_facts_governance.py\`

## Acceptance Criteria
- [ ] All tests pass locally
- [ ] No regression of existing suite

## Related
Phase 3 Closure - Issue #11/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P1,test,phase-3"

echo "✅ Issue 11 created"

# Issue 12: Validation script enhancements
gh issue create \
  --title "[P2][test] Validation script enhancements" \
  --body "**Priority**: P2 (Normal)
**Type**: test
**Milestone**: M3

## Scope
Add checks for enum usage in alerts and for \`by_type\` keyed by \`conflict_type.value\`.

## Files
- \`scripts/validate_phase3_facts.py\`

## Acceptance Criteria
- [ ] Script success on current repo
- [ ] Score ≥ 90% with new checks

## Related
Phase 3 Closure - Issue #12/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P2,test,phase-3"

echo "✅ Issue 12 created"

# Issue 13: Structured logging & governance metrics
gh issue create \
  --title "[P2][feat] Structured logging & governance metrics" \
  --body "**Priority**: P2 (Normal)
**Type**: feat
**Milestone**: M3

## Scope
Add structured logs (action, fact_id, group_id, user_id) and counters (approve/reject/conflict) to prepare Phase 5.

## Files
- Facts/Intelligence services

## Acceptance Criteria
- [ ] Logs visible during actions
- [ ] Simple counters derivable (manual or via hooks)

## Related
Phase 3 Closure - Issue #13/13
Source: \`status/PHASE3_CLOSURE_ISSUES.md\`" \
  --label "P2,enhancement,phase-3,observability"

echo "✅ Issue 13 created"

echo ""
echo "🎉 All 13 Phase 3 Closure issues created successfully!"
echo ""
echo "Milestones:"
echo "  M1 (P0): Issues #1-3"
echo "  M2 (P1): Issues #4-6, #11"
echo "  M3 (P2): Issues #7-10, #12-13"