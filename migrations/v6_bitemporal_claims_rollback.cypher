// V6 Bitemporal Claims — ROLLBACK de la migration A1.2
//
// ADR_BITEMPOREL_CLAIMS.md §6.4 plan de rollback
//
// Cette procédure SUPPRIME les 4 propriétés ajoutées par v6_bitemporal_claims.cypher
// + le node :MigrationLog associé + les 3 indexes créés.
//
// La donnée originale `c.created_at` est PRÉSERVÉE (la migration ne l'a jamais touchée).
//
// Idempotent : peut être rejoué sans effet (REMOVE no-op si propriété absente,
// DROP IF EXISTS sur indexes, MATCH/DELETE no-op si pas de :MigrationLog).
//
// Usage :
//   docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
//     --format plain -f /tmp/v6_bitemporal_claims_rollback.cypher

// ─────────────────────────────────────────────────────────────────────────────
// 1. Count avant rollback (audit)
// ─────────────────────────────────────────────────────────────────────────────

MATCH (c:Claim)
WHERE c.valid_from IS NOT NULL
RETURN count(c) AS claims_with_timestamps_before_rollback;

// ─────────────────────────────────────────────────────────────────────────────
// 2. Retrait des 4 propriétés sur tous les Claims
// ─────────────────────────────────────────────────────────────────────────────

MATCH (c:Claim)
REMOVE c.valid_from, c.ingested_at, c.valid_until, c.invalidated_at
RETURN count(c) AS claims_rolled_back;

// ─────────────────────────────────────────────────────────────────────────────
// 3. Suppression du node :MigrationLog associé
// ─────────────────────────────────────────────────────────────────────────────

MATCH (m:MigrationLog {migration_id: 'v6_bitemporal_claims'})
DELETE m
RETURN 'MigrationLog deleted' AS log_status;

// ─────────────────────────────────────────────────────────────────────────────
// 4. Drop des 3 indexes
// ─────────────────────────────────────────────────────────────────────────────

DROP INDEX claim_active IF EXISTS;
DROP INDEX claim_event_time IF EXISTS;
DROP INDEX claim_ingested IF EXISTS;

// ─────────────────────────────────────────────────────────────────────────────
// 5. Audit final
// ─────────────────────────────────────────────────────────────────────────────

MATCH (c:Claim)
RETURN
  count(c) AS total_claims,
  count(c.valid_from) AS with_valid_from_after_rollback,
  count(c.created_at) AS with_created_at_preserved;
