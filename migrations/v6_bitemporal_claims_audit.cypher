// V6 Bitemporal Claims — AUDIT post-migration A1.2
//
// ADR_BITEMPOREL_CLAIMS.md §3.3 (Tests Gate-B #1 et #2)
//
// Ce script vérifie que la migration A1.2 a bien été appliquée :
//   1. 100% des claims existants portent valid_from + ingested_at (champs obligatoires)
//   2. valid_until + invalidated_at sont NULL pour tous (cas nominal post-migration)
//   3. Le node :MigrationLog est présent
//   4. Les 3 indexes sont créés et online
//
// Critère Gate-B : tous les counts attendus matchent → migration validée.
//
// Usage :
//   docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
//     --format plain -f /tmp/v6_bitemporal_claims_audit.cypher

// ─────────────────────────────────────────────────────────────────────────────
// Test #1 — Tous les claims ont valid_from + ingested_at (Gate-B critère bloquant)
// ─────────────────────────────────────────────────────────────────────────────

MATCH (c:Claim)
WHERE c.tenant_id = 'default'
  AND (c.valid_from IS NULL OR c.ingested_at IS NULL)
RETURN count(c) AS missing_required_timestamps;
// Attendu : 0

// ─────────────────────────────────────────────────────────────────────────────
// Test #2 — Distribution des claims par état temporel
// ─────────────────────────────────────────────────────────────────────────────

MATCH (c:Claim)
WHERE c.tenant_id = 'default'
RETURN
  count(c) AS total,
  count(c.valid_from) AS with_valid_from,
  count(c.ingested_at) AS with_ingested_at,
  count(c.valid_until) AS with_valid_until,
  count(c.invalidated_at) AS with_invalidated_at;
// Attendu post-migration A1.2 : total = with_valid_from = with_ingested_at, with_valid_until = with_invalidated_at = 0

// ─────────────────────────────────────────────────────────────────────────────
// Test #3 — Cohérence : valid_from = ingested_at (post-migration fresh, avant A1.3)
// ─────────────────────────────────────────────────────────────────────────────

MATCH (c:Claim)
WHERE c.tenant_id = 'default'
  AND c.valid_from <> c.ingested_at
RETURN count(c) AS drift_count;
// Attendu : 0 (toute la migration les a alignés depuis created_at)

// ─────────────────────────────────────────────────────────────────────────────
// Test #4 — MigrationLog présent
// ─────────────────────────────────────────────────────────────────────────────

MATCH (m:MigrationLog {migration_id: 'v6_bitemporal_claims'})
RETURN
  toString(m.first_executed_at) AS first_executed_at,
  toString(m.last_executed_at) AS last_executed_at,
  m.run_count AS run_count,
  m.script_version AS version,
  m.applied_by AS applied_by,
  m.notes AS notes;
// Attendu : 1 ligne avec metadata correcte (run_count ≥ 1)

// ─────────────────────────────────────────────────────────────────────────────
// Test #5 — Indexes online
// ─────────────────────────────────────────────────────────────────────────────

SHOW INDEXES
YIELD name, state, type, entityType, labelsOrTypes, properties
WHERE name IN ['claim_active', 'claim_event_time', 'claim_ingested']
RETURN name, state, type, labelsOrTypes, properties;
// Attendu : 3 lignes, state = 'ONLINE'

// ─────────────────────────────────────────────────────────────────────────────
// Test #6 — Échantillon stratifié 10 claims point-in-time (Gate-B §3.3 test #3)
// ─────────────────────────────────────────────────────────────────────────────

// Échantillon : 2 claims par doc_type représentatif (5 types SAP)
// (cf §3.3 — sera étoffé en Gate-B avec doc_type aligné après A1.3 enrichi)
MATCH (c:Claim)
WHERE c.tenant_id = 'default'
WITH c LIMIT 10
RETURN c.claim_id AS id, c.doc_id AS doc, c.valid_from AS valid_from, c.ingested_at AS ingested_at, c.valid_until AS valid_until, c.invalidated_at AS invalidated_at;
