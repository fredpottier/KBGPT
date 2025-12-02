// ========================================
// Validation Proto-KG : Requêtes Cypher
// ========================================
// Exécuter depuis cypher-shell ou Neo4j Browser

// ========================================
// 1. STATISTIQUES GLOBALES
// ========================================

// Compter tous les noeuds par type
MATCH (n)
RETURN labels(n) as Type, count(n) as Count
ORDER BY Count DESC;

// Compter toutes les relations par type
MATCH ()-[r]->()
RETURN type(r) as RelationType, count(r) as Count
ORDER BY Count DESC;

// ========================================
// 2. VALIDATION CONCEPTS
// ========================================

// Concepts sans nom (ERREUR critique)
MATCH (p:ProtoConcept)
WHERE p.name IS NULL OR p.name = ""
RETURN count(p) as ConceptsWithoutName;

// Concepts avec noms suspects (trop courts)
MATCH (p:ProtoConcept)
WHERE length(p.name) < 3
RETURN p.name, p.concept_id
LIMIT 20;

// Concepts avec noms suspects (trop longs - possibles phrases)
MATCH (p:ProtoConcept)
WHERE length(p.name) > 100
RETURN p.name, length(p.name) as NameLength
LIMIT 20;

// Distribution longueur des noms
MATCH (p:ProtoConcept)
RETURN
  min(length(p.name)) as MinLength,
  max(length(p.name)) as MaxLength,
  avg(length(p.name)) as AvgLength,
  percentileCont(length(p.name), 0.5) as MedianLength;

// ========================================
// 3. VALIDATION CANONICALISATION
// ========================================

// ProtoConcepts SANS forme canonique (potentiel problème)
MATCH (p:ProtoConcept)
WHERE NOT EXISTS((p)-[:CANONICAL_FORM]->(:CanonicalConcept))
RETURN count(p) as ConceptsWithoutCanonical;

// Exemples de ProtoConcepts sans canonique
MATCH (p:ProtoConcept)
WHERE NOT EXISTS((p)-[:CANONICAL_FORM]->(:CanonicalConcept))
RETURN p.name, p.concept_id
LIMIT 20;

// CanonicalConcepts avec le plus de variations
MATCH (p:ProtoConcept)-[:CANONICAL_FORM]->(c:CanonicalConcept)
WITH c, collect(p.name) as Variations, count(p) as VariationCount
WHERE VariationCount > 1
RETURN c.name as CanonicalName, VariationCount, Variations
ORDER BY VariationCount DESC
LIMIT 20;

// Canonicalisation 1:1 (pas de fusion - possiblement normal)
MATCH (p:ProtoConcept)-[:CANONICAL_FORM]->(c:CanonicalConcept)
WITH c, count(p) as VariationCount
WHERE VariationCount = 1
RETURN count(c) as SingletonCanonicals;

// ========================================
// 4. VALIDATION TYPES DE CONCEPTS
// ========================================

// Distribution par type de concept
MATCH (p:ProtoConcept)
RETURN p.concept_type as ConceptType, count(p) as Count
ORDER BY Count DESC;

// Concepts sans type (possible problème)
MATCH (p:ProtoConcept)
WHERE p.concept_type IS NULL OR p.concept_type = ""
RETURN count(p) as ConceptsWithoutType;

// Vérifier types attendus (PRODUCT, FEATURE, TECHNOLOGY, etc.)
MATCH (p:ProtoConcept)
WHERE p.concept_type IN ["PRODUCT", "FEATURE", "TECHNOLOGY", "PROCESS", "ROLE", "BENEFIT"]
RETURN p.concept_type, count(p) as Count
ORDER BY Count DESC;

// ========================================
// 5. VALIDATION DOMAINES
// ========================================

// Distribution par domaine
MATCH (p:ProtoConcept)
RETURN p.domain as Domain, count(p) as Count
ORDER BY Count DESC;

// Concepts multi-domaines (enrichissement)
MATCH (p:ProtoConcept)
WHERE size(split(p.domain, ",")) > 1
RETURN p.name, p.domain, size(split(p.domain, ",")) as DomainCount
LIMIT 20;

// ========================================
// 6. VALIDATION RELATIONS
// ========================================

// Relations LLM extraites (hors CANONICAL_FORM)
MATCH (p1:ProtoConcept)-[r]->(p2:ProtoConcept)
WHERE type(r) <> "CANONICAL_FORM"
RETURN type(r) as RelationType, count(r) as Count
ORDER BY Count DESC;

// Exemples de relations extraites
MATCH (p1:ProtoConcept)-[r]->(p2:ProtoConcept)
WHERE type(r) <> "CANONICAL_FORM"
RETURN p1.name, type(r), p2.name, r.confidence
LIMIT 20;

// Relations avec confiance faible (< 0.5)
MATCH (p1:ProtoConcept)-[r]->(p2:ProtoConcept)
WHERE r.confidence IS NOT NULL AND r.confidence < 0.5
RETURN p1.name, type(r), p2.name, r.confidence
ORDER BY r.confidence ASC
LIMIT 20;

// ========================================
// 7. VALIDATION PROVENANCE
// ========================================

// Concepts par document source
MATCH (p:ProtoConcept)
WHERE p.document_id IS NOT NULL
RETURN p.document_id as DocumentID, count(p) as ConceptCount;

// Vérifier que tous les concepts ont un document source
MATCH (p:ProtoConcept)
WHERE p.document_id IS NULL
RETURN count(p) as ConceptsWithoutDocument;

// ========================================
// 8. VALIDATION DESCRIPTIONS
// ========================================

// Concepts SANS description (peut être normal)
MATCH (p:ProtoConcept)
WHERE p.description IS NULL OR p.description = ""
RETURN count(p) as ConceptsWithoutDescription;

// Descriptions trop courtes (< 20 chars)
MATCH (p:ProtoConcept)
WHERE p.description IS NOT NULL AND length(p.description) < 20
RETURN p.name, p.description
LIMIT 20;

// ========================================
// 9. DÉTECTION DOUBLONS POTENTIELS
// ========================================

// Noms identiques dans ProtoConcepts (doublons exacts)
MATCH (p:ProtoConcept)
WITH p.name as ConceptName, collect(p) as Concepts
WHERE size(Concepts) > 1
RETURN ConceptName, size(Concepts) as DuplicateCount
ORDER BY DuplicateCount DESC
LIMIT 20;

// Noms similaires (case-insensitive)
MATCH (p1:ProtoConcept), (p2:ProtoConcept)
WHERE toLower(p1.name) = toLower(p2.name) AND id(p1) < id(p2)
RETURN p1.name, p2.name, p1.concept_id, p2.concept_id
LIMIT 20;

// ========================================
// 10. EXEMPLES REPRÉSENTATIFS
// ========================================

// Top 20 concepts les plus connectés (hubs)
MATCH (p:ProtoConcept)
OPTIONAL MATCH (p)-[r]-()
WITH p, count(r) as ConnectionCount
WHERE ConnectionCount > 0
RETURN p.name, p.concept_type, ConnectionCount
ORDER BY ConnectionCount DESC
LIMIT 20;

// Concepts isolés (sans relations)
MATCH (p:ProtoConcept)
WHERE NOT EXISTS((p)-[]-())
RETURN count(p) as IsolatedConcepts;

// Exemples concepts avec contexte complet
MATCH (p:ProtoConcept)-[:CANONICAL_FORM]->(c:CanonicalConcept)
OPTIONAL MATCH (p)-[r:RELATES_TO|PART_OF|ENABLES]->(p2:ProtoConcept)
RETURN
  p.name as ProtoName,
  c.name as CanonicalName,
  p.concept_type as Type,
  p.domain as Domain,
  collect(DISTINCT {rel: type(r), target: p2.name}) as Relations
LIMIT 10;

// ========================================
// 11. VALIDATION QUALITÉ GLOBALE
// ========================================

// Score qualité global (heuristique)
MATCH (p:ProtoConcept)
OPTIONAL MATCH (p)-[:CANONICAL_FORM]->()
OPTIONAL MATCH (p)-[r]-()
RETURN
  count(p) as TotalConcepts,
  sum(CASE WHEN p.name IS NOT NULL AND p.name <> "" THEN 1 ELSE 0 END) * 100.0 / count(p) as PercentWithName,
  sum(CASE WHEN p.concept_type IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / count(p) as PercentWithType,
  sum(CASE WHEN p.description IS NOT NULL AND p.description <> "" THEN 1 ELSE 0 END) * 100.0 / count(p) as PercentWithDescription,
  sum(CASE WHEN EXISTS((p)-[:CANONICAL_FORM]->()) THEN 1 ELSE 0 END) * 100.0 / count(p) as PercentCanonicalized;

// ========================================
// FIN
// ========================================
