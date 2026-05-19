// V6 Bitemporal Claims — Migration ajout 4 timestamps sur :Claim
//
// ADR_BITEMPOREL_CLAIMS.md §3.1 (Phase A1.2)
// Source de vérité existante : `c.created_at` (string ISO 8601, présent sur 14 417/14 417 claims SAP)
//
// Cette migration AJOUTE 4 propriétés sur tous les :Claim :
//   - valid_from     : DateTime — event time start (fallback = datetime(c.created_at))
//   - valid_until    : DateTime — event time end (NULL par défaut, encore actif)
//   - ingested_at    : DateTime — transaction time start (= datetime(c.created_at), conserve `created_at` original)
//   - invalidated_at : DateTime — transaction time end (NULL par défaut, encore actif)
//
// Idempotent : WHERE c.valid_from IS NULL → rejouable sans effet.
// Multi-tenant safe : ne filtre pas par tenant_id, applique à tous (tenant_id reste sur les indexes).
// Conserve `c.created_at` original (pas de rename) — `ingested_at` est dérivé pour respecter le contrat ADR §2.1.
//
// Usage :
//   docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
//     --format plain -f /tmp/v6_bitemporal_claims.cypher

// ─────────────────────────────────────────────────────────────────────────────
// 1. Count avant migration (audit baseline)
// ─────────────────────────────────────────────────────────────────────────────

MATCH (c:Claim)
RETURN count(c) AS total_claims_before;

// ─────────────────────────────────────────────────────────────────────────────
// 2. Migration des claims sans valid_from (idempotent)
// ─────────────────────────────────────────────────────────────────────────────

MATCH (c:Claim)
WHERE c.valid_from IS NULL
SET c.valid_from = datetime(c.created_at),
    c.ingested_at = datetime(c.created_at),
    c.valid_until = NULL,
    c.invalidated_at = NULL
RETURN count(c) AS migrated_count;

// ─────────────────────────────────────────────────────────────────────────────
// 3. Log de migration (audit trail persistant) — idempotent via MERGE
//    1 seul node :MigrationLog par migration_id ; chaque rejouage met à jour
//    last_executed_at et incrémente run_count.
// ─────────────────────────────────────────────────────────────────────────────

MERGE (m:MigrationLog {migration_id: 'v6_bitemporal_claims'})
ON CREATE SET
  m.first_executed_at = datetime(),
  m.last_executed_at = datetime(),
  m.run_count = 1,
  m.script_version = '1.0',
  m.applied_by = 'A1.2',
  m.source_field = 'created_at',
  m.notes = 'valid_from = ingested_at = datetime(created_at) ; valid_until = invalidated_at = NULL'
ON MATCH SET
  m.last_executed_at = datetime(),
  m.run_count = coalesce(m.run_count, 1) + 1
RETURN m.run_count AS total_executions, toString(m.last_executed_at) AS last_run;

// ─────────────────────────────────────────────────────────────────────────────
// 4. Count après migration (vérification)
// ─────────────────────────────────────────────────────────────────────────────

MATCH (c:Claim)
RETURN
  count(c) AS total_claims_after,
  count(c.valid_from) AS with_valid_from,
  count(c.ingested_at) AS with_ingested_at,
  count(c.valid_until) AS with_valid_until,
  count(c.invalidated_at) AS with_invalidated_at;

// ─────────────────────────────────────────────────────────────────────────────
// 5. Création des 3 indexes composites (multi-tenant safe)
// ─────────────────────────────────────────────────────────────────────────────

// Index sparse sur invalidated_at — claims actifs (NULL) accédés très souvent
CREATE INDEX claim_active IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.invalidated_at);

// Index point-in-time queries — couvre valid_from + valid_until
CREATE INDEX claim_event_time IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.valid_from, c.valid_until);

// Index audit trail — historique d'ingestion par tenant
CREATE INDEX claim_ingested IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.ingested_at);

// ─────────────────────────────────────────────────────────────────────────────
// 6. Vérification indexes créés
// ─────────────────────────────────────────────────────────────────────────────

SHOW INDEXES WHERE name IN ['claim_active', 'claim_event_time', 'claim_ingested'];
