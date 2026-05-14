// V5 DSG (Document Structure Graph) — Setup constraints + indexes
//
// ADR §3b : Multi-tenant isolation forte par composite keys + TenantQueryGuard.
// Préfixe V5* sur les labels pour éviter collision avec le KG anchor-driven existant.
//
// Idempotent : utilise IF NOT EXISTS sur toutes les operations.
//
// Usage :
//   docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
//     --format plain -f /tmp/v5_dsg_setup.cypher

// ─────────────────────────────────────────────────────────────────────────────
// CONSTRAINTS — Multi-tenant composite keys
// ─────────────────────────────────────────────────────────────────────────────

// Document : unique par (tenant_id, doc_id) + doc_internal_id opaque global
CREATE CONSTRAINT v5_doc_tenant_unique IF NOT EXISTS
FOR (d:V5Document) REQUIRE (d.tenant_id, d.doc_id) IS UNIQUE;

CREATE CONSTRAINT v5_doc_internal_unique IF NOT EXISTS
FOR (d:V5Document) REQUIRE d.doc_internal_id IS UNIQUE;

// Section : unique par (tenant_id, section_id) — composite key obligatoire
CREATE CONSTRAINT v5_section_tenant_unique IF NOT EXISTS
FOR (s:V5Section) REQUIRE (s.tenant_id, s.section_id) IS UNIQUE;

// Table : unique par (tenant_id, table_id)
CREATE CONSTRAINT v5_table_tenant_unique IF NOT EXISTS
FOR (t:V5Table) REQUIRE (t.tenant_id, t.table_id) IS UNIQUE;

// ─────────────────────────────────────────────────────────────────────────────
// INDEXES — Recherche performante
// ─────────────────────────────────────────────────────────────────────────────

// Full-text sur Section title + text_snippet (pour find_in)
CREATE FULLTEXT INDEX v5_section_fulltext IF NOT EXISTS
FOR (s:V5Section) ON EACH [s.title, s.text_snippet];

// Full-text sur Table caption
CREATE FULLTEXT INDEX v5_table_fulltext IF NOT EXISTS
FOR (t:V5Table) ON EACH [t.caption];

// Index composite pour lookups numbering (navigate_by_toc)
CREATE INDEX v5_section_numbering IF NOT EXISTS
FOR (s:V5Section) ON (s.tenant_id, s.doc_id, s.numbering);

// Index level + parent pour navigation hierarchique
CREATE INDEX v5_section_level IF NOT EXISTS
FOR (s:V5Section) ON (s.tenant_id, s.doc_id, s.level);

// Index doc_id pour filter rapide
CREATE INDEX v5_section_doc IF NOT EXISTS
FOR (s:V5Section) ON (s.tenant_id, s.doc_id);

// Index Document active_status pour filtrer versions actives
CREATE INDEX v5_doc_active_status IF NOT EXISTS
FOR (d:V5Document) ON (d.tenant_id, d.active_status);
