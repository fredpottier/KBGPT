# Requires: PowerShell 5+ and a GitHub token with repo scope in $env:GITHUB_TOKEN
# Usage:
#   $env:GITHUB_TOKEN = "ghp_..."    # set your token
#   ./scripts/create_phase3_github_issues.ps1 -Repo "fredpottier/KBGPT"

[CmdletBinding()] param(
  [Parameter(Mandatory=$true)][string]$Repo
)

if (-not $env:GITHUB_TOKEN) {
  Write-Error "GITHUB_TOKEN env var is not set. Please export a token with 'repo' scope."; exit 1
}

$Headers = @{ 
  Authorization = "token $($env:GITHUB_TOKEN)"
  Accept        = "application/vnd.github+json"
  "X-GitHub-Api-Version" = "2022-11-28"
}

function Invoke-GHApi {
  param([string]$Method, [string]$Path, [object]$Body)
  $uri = "https://api.github.com/repos/$Repo$Path"
  if ($null -ne $Body) {
    $json = $Body | ConvertTo-Json -Depth 10
    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $Headers -ContentType 'application/json' -Body $json
  } else {
    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $Headers
  }
}

function Ensure-Label {
  param([string]$Name, [string]$Color = '6a5acd', [string]$Description = '')
  try {
    $existing = Invoke-GHApi -Method GET -Path "/labels/$Name" -Body $null
    if ($existing) { return $existing }
  } catch { }
  return Invoke-GHApi -Method POST -Path "/labels" -Body @{ name=$Name; color=$Color; description=$Description }
}

function Ensure-Milestone {
  param([string]$Title, [string]$Description='')
  $existing = Invoke-GHApi -Method GET -Path "/milestones" -Body $null | Where-Object { $_.title -eq $Title }
  if ($existing) { return $existing }
  return Invoke-GHApi -Method POST -Path "/milestones" -Body @{ title=$Title; state='open'; description=$Description }
}

Write-Host "Preparing labels and milestones for $Repo ..."

# Core labels
$labels = @(
  @{ n='P0'; c='d73a4a'; d='Critical priority' },
  @{ n='P1'; c='fbca04'; d='High priority' },
  @{ n='P2'; c='0e8a16'; d='Normal priority' },
  @{ n='backend'; c='1d76db'; d='Backend work' },
  @{ n='frontend'; c='a2eeef'; d='Frontend work' },
  @{ n='docs'; c='c5def5'; d='Documentation' },
  @{ n='perf'; c='5319e7'; d='Performance' },
  @{ n='test'; c='fef2c0'; d='Testing' },
  @{ n='tooling'; c='bfd4f2'; d='Tooling / scripts' },
  @{ n='observability'; c='5319e7'; d='Logging/metrics' },
  @{ n='phase3'; c='0052cc'; d='Phase 3 Closure' }
)
$labels | ForEach-Object { Ensure-Label -Name $_.n -Color $_.c -Description $_.d | Out-Null }

$m1 = Ensure-Milestone -Title 'Phase 3 — M1 (P0)' -Description 'Critical closure items for Phase 3'
$m2 = Ensure-Milestone -Title 'Phase 3 — M2 (P1)' -Description 'High priority closure items for Phase 3'
$m3 = Ensure-Milestone -Title 'Phase 3 — M3 (P2)' -Description 'Normal priority closure items for Phase 3'

function New-Issue {
  param([string]$Title,[string]$Body,[string[]]$Labels,[int]$Milestone)
  Invoke-GHApi -Method POST -Path "/issues" -Body @{ title=$Title; body=$Body; labels=$Labels; milestone=$Milestone } | Out-Null
  Write-Host "Created: $Title"
}

Write-Host "Creating Phase 3 issues ..."

# 1) RBAC
New-Issue -Title "RBAC for approve/reject/delete" -Body @'
Enforce role-based access (expert/admin) using UserContext for approve/reject/delete routes.

Files: src/knowbase/api/routers/facts_governance.py
Acceptance:
- Unauthorized role -> 403
- Add tests for 403; no regressions
'@ -Labels @('P0','backend','phase3') -Milestone $m1.number

# 2) Persistent reject + audit
New-Issue -Title "Persisted reject + audit trail" -Body @'
Persist status=rejected with metadata in store; keep audit episode for traceability.

Files: src/knowbase/common/graphiti/graphiti_store.py, src/knowbase/api/services/facts_governance_service.py
Acceptance:
- GET /api/facts/{id} shows rejected state post-API
- Tests for persisted reject
'@ -Labels @('P0','backend','phase3') -Milestone $m1.number

# 3) Soft-delete flag
New-Issue -Title "Soft-delete flag and list exclusion" -Body @'
Introduce deleted=true flag for facts; exclude by default from listings; optional include via filter.

Files: store, service, delete route
Acceptance:
- DELETE marks deleted, 204
- Not listed by default; tests added
'@ -Labels @('P0','backend','phase3') -Milestone $m1.number

# 4) Conflict detection enrichment
New-Issue -Title "Conflict detection: types + temporal overlap" -Body @'
Use store-provided conflict types; add TEMPORAL_OVERLAP using valid_from/valid_until and contradiction rules.

Files: store + service
Acceptance:
- /api/facts/conflicts/list returns multiple types, accurate by_type
- Tests for overlap + mismatch
'@ -Labels @('P1','backend','phase3') -Milestone $m2.number

# 5) get_conflicts performance
New-Issue -Title "Optimize get_conflicts performance" -Body @'
Reduce O(N × detect) pattern; batch detection or efficient prefiltering.

Files: src/knowbase/api/services/facts_governance_service.py
Acceptance: 500 facts -> < ~1s locally (slow test ok)
'@ -Labels @('P1','backend','perf','phase3') -Milestone $m2.number

# 6) Pending UI: real user IDs
New-Issue -Title "Pending UI uses real user IDs" -Body @'
Replace "current_user" placeholder by actual user ID from context/header.

File: frontend/src/app/governance/pending/page.tsx
Acceptance: approve/reject includes correct approver_id/rejector_id
'@ -Labels @('P1','frontend','phase3') -Milestone $m2.number

# 7) Conflicts UI
New-Issue -Title "Conflicts UI hardening" -Body @'
Consume /api/facts/conflicts/list, show totals by type/severity, handle empty/error states, link to fact.

File: frontend/src/app/governance/conflicts/page.tsx
Acceptance: UX with counts/list/navigation; empty/error handled
'@ -Labels @('P2','frontend','phase3') -Milestone $m3.number

# 8) UTF-8 normalization
New-Issue -Title "UTF-8 normalization (FR text)" -Body @'
Fix mojibake in docstrings/logs/UI labels to proper UTF-8.

Files: schemas/services/UI copy
Acceptance: no corrupted characters
'@ -Labels @('P2','backend','frontend','docs','phase3') -Milestone $m3.number

# 9) Auto-create user group
New-Issue -Title "Auto-create user group on set_group" -Body @'
Ensure set_group creates group if missing (idempotent) so first use works without provisioning.

File: src/knowbase/common/graphiti/graphiti_store.py
Acceptance: first call with new X-User-ID succeeds; minimal test
'@ -Labels @('P2','backend','phase3') -Milestone $m3.number

# 10) Deployment/docs for Graphiti
New-Issue -Title "Graphiti deployment/docs (.env, compose)" -Body @'
Document env vars; add reference docker-compose; clarify Neo4j/API keys/timeouts.

Files: docs + .env.example
Acceptance: clear local setup guide; example compose runs
'@ -Labels @('P2','docs','tooling','phase3') -Milestone $m3.number

# 11) Tests expansion Phase 3
New-Issue -Title "Expand tests: RBAC, reject, soft-delete, temporal conflicts" -Body @'
Add tests for 403 RBAC, persisted reject, soft-delete, temporal overlap; optional perf (slow-marked).

File: tests/integration/test_facts_governance.py
Acceptance: tests pass; no regressions
'@ -Labels @('P1','test','backend','phase3') -Milestone $m2.number

# 12) Validation script enhancements
New-Issue -Title "Validation script: enum + by_type checks" -Body @'
Extend validate_phase3_facts.py to check enum usage in alerts and by_type keyed by conflict_type.value.

File: scripts/validate_phase3_facts.py
Acceptance: score ≥ 90% with new checks
'@ -Labels @('P2','tooling','test','phase3') -Milestone $m3.number

# 13) Structured logging & governance metrics
New-Issue -Title "Structured logging + governance metrics" -Body @'
Add structured logs (action, fact_id, group_id, user_id) and counters (approve/reject/conflict) in services to prep Phase 5.

Files: Facts/Intelligence services
Acceptance: logs visible and counters derivable
'@ -Labels @('P2','backend','observability','phase3') -Milestone $m3.number

Write-Host "All Phase 3 issues created."
