// ============================================================================
// OSMOSE Pipeline V2 - Schéma Neo4j
// ============================================================================
// Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md
// Date: 2026-01-23
// ============================================================================

// --------------------
// CONTRAINTES D'UNICITÉ (par tenant)
// --------------------

CREATE CONSTRAINT doc_unique IF NOT EXISTS
FOR (d:Document) REQUIRE (d.tenant_id, d.doc_id) IS UNIQUE;

CREATE CONSTRAINT section_unique IF NOT EXISTS
FOR (s:Section) REQUIRE (s.tenant_id, s.section_id) IS UNIQUE;

CREATE CONSTRAINT docitem_unique IF NOT EXISTS
FOR (i:DocItem) REQUIRE (i.tenant_id, i.docitem_id) IS UNIQUE;

CREATE CONSTRAINT subject_unique IF NOT EXISTS
FOR (s:Subject) REQUIRE (s.tenant_id, s.subject_id) IS UNIQUE;

CREATE CONSTRAINT theme_unique IF NOT EXISTS
FOR (t:Theme) REQUIRE (t.tenant_id, t.theme_id) IS UNIQUE;

CREATE CONSTRAINT concept_unique IF NOT EXISTS
FOR (c:Concept) REQUIRE (c.tenant_id, c.concept_id) IS UNIQUE;

CREATE CONSTRAINT info_unique IF NOT EXISTS
FOR (i:Information) REQUIRE (i.tenant_id, i.info_id) IS UNIQUE;

CREATE CONSTRAINT assertion_unique IF NOT EXISTS
FOR (a:AssertionLog) REQUIRE (a.tenant_id, a.assertion_id) IS UNIQUE;

// --------------------
// INDEXES DE LOOKUP
// --------------------

// Document
CREATE INDEX doc_by_hash IF NOT EXISTS
FOR (d:Document) ON (d.tenant_id, d.content_hash);

// Section
CREATE INDEX section_by_doc IF NOT EXISTS
FOR (s:Section) ON (s.tenant_id, s.doc_id);

// DocItem
CREATE INDEX docitem_by_doc IF NOT EXISTS
FOR (i:DocItem) ON (i.tenant_id, i.doc_id);

CREATE INDEX docitem_by_section IF NOT EXISTS
FOR (i:DocItem) ON (i.tenant_id, i.section_id);

CREATE INDEX docitem_by_charspan IF NOT EXISTS
FOR (i:DocItem) ON (i.tenant_id, i.doc_id, i.char_start, i.char_end);

// Theme
CREATE INDEX theme_by_doc IF NOT EXISTS
FOR (t:Theme) ON (t.tenant_id, t.doc_id);

// Concept
CREATE INDEX concept_by_doc IF NOT EXISTS
FOR (c:Concept) ON (c.tenant_id, c.doc_id);

CREATE INDEX concept_by_lexkey IF NOT EXISTS
FOR (c:Concept) ON (c.tenant_id, c.lex_key);

// Information
CREATE INDEX info_by_doc IF NOT EXISTS
FOR (i:Information) ON (i.tenant_id, i.doc_id);

// AssertionLog
CREATE INDEX log_by_doc IF NOT EXISTS
FOR (a:AssertionLog) ON (a.tenant_id, a.doc_id);

CREATE INDEX log_by_status IF NOT EXISTS
FOR (a:AssertionLog) ON (a.tenant_id, a.status);

CREATE INDEX log_by_reason IF NOT EXISTS
FOR (a:AssertionLog) ON (a.tenant_id, a.reason);

// --------------------
// SMOKE QUERIES (validation post-migration)
// --------------------

// Vérifier les contraintes
// SHOW CONSTRAINTS;

// Vérifier les indexes
// SHOW INDEXES;

// Compter les nodes par label (devrait être 0 après migration initiale)
// MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY count DESC;
