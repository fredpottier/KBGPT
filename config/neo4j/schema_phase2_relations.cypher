// Phase 2 OSMOSE - Schema Relations Neo4j
// Metadata Layer pour 12 types relations

// ===================================================================
// CONSTRAINTS & INDEXES - RELATIONS TYPÉES
// ===================================================================

// Créer constraint pour propriétés obligatoires sur relations
CREATE CONSTRAINT rel_part_of_confidence IF NOT EXISTS
FOR ()-[r:PART_OF]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_subtype_of_confidence IF NOT EXISTS
FOR ()-[r:SUBTYPE_OF]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_requires_confidence IF NOT EXISTS
FOR ()-[r:REQUIRES]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_uses_confidence IF NOT EXISTS
FOR ()-[r:USES]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_integrates_with_confidence IF NOT EXISTS
FOR ()-[r:INTEGRATES_WITH]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_version_of_confidence IF NOT EXISTS
FOR ()-[r:VERSION_OF]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_precedes_confidence IF NOT EXISTS
FOR ()-[r:PRECEDES]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_replaces_confidence IF NOT EXISTS
FOR ()-[r:REPLACES]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_deprecates_confidence IF NOT EXISTS
FOR ()-[r:DEPRECATES]-() REQUIRE r.confidence IS NOT NULL;

// Phase 2.5 optionnels
CREATE CONSTRAINT rel_extends_confidence IF NOT EXISTS
FOR ()-[r:EXTENDS]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_enables_confidence IF NOT EXISTS
FOR ()-[r:ENABLES]-() REQUIRE r.confidence IS NOT NULL;

CREATE CONSTRAINT rel_alternative_to_confidence IF NOT EXISTS
FOR ()-[r:ALTERNATIVE_TO]-() REQUIRE r.confidence IS NOT NULL;

// ===================================================================
// INDEXES - PERFORMANCE QUERIES
// ===================================================================

// Index sur extraction_method pour filtrer par méthode
CREATE INDEX rel_part_of_extraction_method IF NOT EXISTS
FOR ()-[r:PART_OF]-() ON (r.extraction_method);

CREATE INDEX rel_subtype_of_extraction_method IF NOT EXISTS
FOR ()-[r:SUBTYPE_OF]-() ON (r.extraction_method);

CREATE INDEX rel_requires_extraction_method IF NOT EXISTS
FOR ()-[r:REQUIRES]-() ON (r.extraction_method);

CREATE INDEX rel_uses_extraction_method IF NOT EXISTS
FOR ()-[r:USES]-() ON (r.extraction_method);

// Index sur status pour filtrer actives/dépréciées
CREATE INDEX rel_part_of_status IF NOT EXISTS
FOR ()-[r:PART_OF]-() ON (r.status);

CREATE INDEX rel_requires_status IF NOT EXISTS
FOR ()-[r:REQUIRES]-() ON (r.status);

// Index temporel pour REPLACES, DEPRECATES
CREATE INDEX rel_replaces_timeline IF NOT EXISTS
FOR ()-[r:REPLACES]-() ON (r.timeline_position);

CREATE INDEX rel_deprecates_eol IF NOT EXISTS
FOR ()-[r:DEPRECATES]-() ON (r.eol_date);

// ===================================================================
// PROPRIÉTÉS ÉTENDUES - CONCEPTS CANONIQUES (Phase 2)
// ===================================================================

// Ajouter propriétés hiérarchiques (TaxonomyBuilder)
// Note: ALTER TABLE syntax n'existe pas en Cypher, juste définir ici les conventions

// Propriétés taxonomy sur CanonicalConcept:
// - taxonomy_path: STRING (ex: "SAP Solutions > Cloud ERP > S/4HANA")
// - hierarchy_level: INT (profondeur 0-5)
// - parent_id: STRING (ID concept parent)
// - children_count: INT (nombre enfants directs)

// Propriétés temporelles sur CanonicalConcept:
// - version_number: STRING (ex: "2.5", "2023.Q1")
// - release_date: DATE
// - valid_from: DATE
// - valid_until: DATE
// - is_current_version: BOOLEAN

// ===================================================================
// EXEMPLES RELATIONS TYPÉES (Documentation)
// ===================================================================

// Exemple 1: PART_OF avec metadata complet
// MATCH (fiori:CanonicalConcept {canonical_name: "SAP Fiori"})
// MATCH (s4:CanonicalConcept {canonical_name: "SAP S/4HANA Cloud"})
// CREATE (fiori)-[:PART_OF {
//   confidence: 0.92,
//   extraction_method: "pattern",
//   source_doc_id: "doc_12345",
//   source_chunk_ids: ["chunk_A", "chunk_B"],
//   language: "EN",
//   created_at: datetime(),
//   strength: "strong",
//   status: "active"
// }]->(s4)

// Exemple 2: REPLACES avec breaking_changes
// MATCH (new:CanonicalConcept {canonical_name: "SAP S/4HANA"})
// MATCH (old:CanonicalConcept {canonical_name: "SAP ECC"})
// CREATE (new)-[:REPLACES {
//   confidence: 0.95,
//   extraction_method: "hybrid",
//   source_doc_id: "doc_67890",
//   breaking_changes: ["Database migration required", "UI rewrite"],
//   migration_effort: "HIGH",
//   backward_compatible: false,
//   timeline_position: 2,
//   release_date: date("2015-02-01"),
//   status: "active"
// }]->(old)

// Exemple 3: VERSION_OF temporel
// MATCH (v20:CanonicalConcept {canonical_name: "SAP CCR 2020"})
// MATCH (ccr:CanonicalConcept {canonical_name: "SAP CCR"})
// CREATE (v20)-[:VERSION_OF {
//   confidence: 1.0,
//   extraction_method: "pattern",
//   source_doc_id: "doc_ccr_2020",
//   timeline_position: 1,
//   release_date: date("2020-01-15"),
//   status: "deprecated"
// }]->(ccr)

// ===================================================================
// QUERIES UTILES - VALIDATION & TESTS
// ===================================================================

// Query 1: Vérifier cycles PART_OF (doit retourner 0)
// MATCH (a:CanonicalConcept)-[:PART_OF*]->(a)
// RETURN count(a) as cycle_count

// Query 2: Lister relations par type
// MATCH ()-[r]->()
// RETURN type(r) as relation_type, count(r) as count
// ORDER BY count DESC

// Query 3: Relations avec confidence < 0.75 (nécessitent validation)
// MATCH (a)-[r]->(b)
// WHERE r.confidence < 0.75
// RETURN a.canonical_name, type(r), b.canonical_name, r.confidence
// ORDER BY r.confidence ASC
// LIMIT 20

// Query 4: Timeline évolution (via REPLACES + PRECEDES)
// MATCH path = (a:CanonicalConcept)-[:REPLACES|PRECEDES*]->(b:CanonicalConcept)
// WHERE a.canonical_name CONTAINS "CCR"
// RETURN path
// ORDER BY length(path) DESC
// LIMIT 1

// ===================================================================
// FIN Schema Phase 2 Relations
// ===================================================================
