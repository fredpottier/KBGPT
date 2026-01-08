# Requêtes Neo4j Utiles - KnowWhere/OSMOSE

**Dernière MAJ:** 2025-12-26 (ajout requêtes typed edges + profils visibilité)

---

## 🔗 Connexion

```
URL: http://localhost:7474
User: neo4j
Password: graphiti_neo4j_pass
```

---

## 📊 Visualisation du Graphe

### Graph CanonicalConcepts avec Relations (via RawAssertions)

```cypher
// Relations entre CanonicalConcepts (exclut ProtoConcepts)
MATCH path = (subject:CanonicalConcept {tenant_id: 'default'})<-[:HAS_SUBJECT]-(r:RawAssertion {tenant_id: 'default'})-[:HAS_OBJECT]->(object:CanonicalConcept)
RETURN path
LIMIT 2500
```

### Tous les CanonicalConcepts (y compris isolés) + Relations

```cypher
MATCH (c:CanonicalConcept {tenant_id: 'default'})
OPTIONAL MATCH path = (c)<-[:HAS_SUBJECT]-(r:RawAssertion {tenant_id: 'default'})-[:HAS_OBJECT]->(other:CanonicalConcept)
RETURN c, path
LIMIT 300
```

---

## 📈 Statistiques

### Comptage par type de noeud

```cypher
MATCH (n {tenant_id: 'default'})
RETURN labels(n)[0] AS type, count(*) AS count
ORDER BY count DESC
```

### Statistiques par type de prédicat (relations)

```cypher
MATCH (s:CanonicalConcept {tenant_id: 'default'})<-[:HAS_SUBJECT]-(r:RawAssertion {tenant_id: 'default'})-[:HAS_OBJECT]->(o:CanonicalConcept)
RETURN r.predicate_norm AS relation, count(*) AS count
ORDER BY count DESC
```

### Comptage CanonicalConcepts par type

```cypher
MATCH (c:CanonicalConcept {tenant_id: 'default'})
RETURN c.concept_type AS type, count(*) AS count
ORDER BY count DESC
```

---

## 🔍 Exploration

### Schéma de la base

```cypher
CALL db.schema.visualization()
```

### Tous les types de relations

```cypher
CALL db.relationshipTypes()
```

### Tous les labels (types de noeuds)

```cypher
CALL db.labels()
```

### Propriétés d'un type de noeud

```cypher
MATCH (c:CanonicalConcept)
RETURN keys(c) AS properties
LIMIT 1
```

---

## 📝 Requêtes Détaillées

### Liste des relations (format tableau)

```cypher
MATCH (s:CanonicalConcept {tenant_id: 'default'})<-[:HAS_SUBJECT]-(r:RawAssertion {tenant_id: 'default'})-[:HAS_OBJECT]->(o:CanonicalConcept)
RETURN
    s.canonical_name AS sujet,
    s.concept_type AS type_sujet,
    r.predicate_norm AS relation,
    o.canonical_name AS objet,
    o.concept_type AS type_objet
ORDER BY s.canonical_name
LIMIT 500
```

### Chercher un concept par nom

```cypher
MATCH (c:CanonicalConcept {tenant_id: 'default'})
WHERE c.canonical_name CONTAINS 'GDPR'
RETURN c
```

### Relations d'un concept spécifique

```cypher
MATCH (c:CanonicalConcept {tenant_id: 'default'})
WHERE c.canonical_name CONTAINS 'Ransomware'
OPTIONAL MATCH path = (c)<-[:HAS_SUBJECT|HAS_OBJECT]-(r:RawAssertion)-[:HAS_SUBJECT|HAS_OBJECT]->(other:CanonicalConcept)
RETURN c, path
```

---

## 🧹 Administration

### Voir les DeferredMerge (Entity Resolution)

```cypher
MATCH (d:DeferredMerge {tenant_id: 'default'})
RETURN d.concept_a_name, d.concept_b_name, d.similarity_score, d.status
ORDER BY d.similarity_score DESC
LIMIT 50
```

### Concepts en status PROVISIONAL

```cypher
MATCH (c:CanonicalConcept {tenant_id: 'default'})
WHERE c.status = 'PROVISIONAL'
RETURN c.canonical_name, c.concept_type, c.created_at
ORDER BY c.created_at DESC
LIMIT 100
```

---

## 🔗 Arêtes Typées Directes (Architecture Agnostique)

> **Note**: Depuis Phase 2.12, les arêtes typées sont créées pour TOUTES les relations
> (pas seulement VALIDATED). Voir `doc/ongoing/KG_AGNOSTIC_ARCHITECTURE.md`

**Types de relations disponibles:**
`REQUIRES`, `PART_OF`, `USES`, `CAUSES`, `ENABLES`, `ASSOCIATED_WITH`, `APPLIES_TO`, `INTEGRATES_WITH`, `EXTENDS`, `CONFLICTS_WITH`, `SUBTYPE_OF`, `PREVENTS`

### Graph avec arêtes typées directes (recommandé)

```cypher
// Visualisation navigable du KG avec arêtes directes
MATCH (s:CanonicalConcept)-[r]->(o:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH', 'APPLIES_TO', 'INTEGRATES_WITH', 'EXTENDS', 'CONFLICTS_WITH', 'SUBTYPE_OF', 'PREVENTS']
RETURN s, r, o
LIMIT 100
```

### Vue tabulaire avec métadonnées

```cypher
MATCH (s:CanonicalConcept)-[r]->(o:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH']
RETURN
    s.name AS subject,
    type(r) AS relation,
    r.maturity AS maturity,
    r.confidence AS confidence,
    o.name AS object
ORDER BY r.confidence DESC
LIMIT 50
```

### Filtrer par type de relation spécifique

```cypher
// Exemple: toutes les relations REQUIRES
MATCH (s:CanonicalConcept)-[r:REQUIRES]->(o:CanonicalConcept)
RETURN s, r, o
LIMIT 50
```

### Filtrer par confiance élevée (>= 0.9)

```cypher
MATCH (s:CanonicalConcept)-[r]->(o:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH']
  AND r.confidence >= 0.9
RETURN s, r, o
LIMIT 100
```

### Explorer le voisinage d'un concept

```cypher
// Remplacer le nom du concept recherché
MATCH (c:CanonicalConcept {name: "Artificial Intelligence Act"})-[r]-(neighbor:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH', 'APPLIES_TO', 'INTEGRATES_WITH', 'EXTENDS', 'CONFLICTS_WITH', 'SUBTYPE_OF', 'PREVENTS']
RETURN c, r, neighbor
```

### Statistiques par type de relation

```cypher
MATCH (s:CanonicalConcept)-[r]->(o:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH', 'APPLIES_TO', 'INTEGRATES_WITH', 'EXTENDS', 'CONFLICTS_WITH', 'SUBTYPE_OF', 'PREVENTS']
RETURN type(r) AS relation_type, count(r) AS count, avg(r.confidence) AS avg_confidence
ORDER BY count DESC
```

### Statistiques par maturité

```cypher
MATCH ()-[r]->()
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH']
RETURN r.maturity AS maturity, count(*) AS count
ORDER BY count DESC
```

### Concepts les plus connectés (centralité)

```cypher
MATCH (c:CanonicalConcept)-[r]-(:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH', 'APPLIES_TO', 'INTEGRATES_WITH', 'EXTENDS', 'CONFLICTS_WITH', 'SUBTYPE_OF', 'PREVENTS']
RETURN c.name AS concept, c.concept_type AS type, count(r) AS connections
ORDER BY connections DESC
LIMIT 20
```

---

## 🎯 Filtrage par Profil de Visibilité

> Ces requêtes correspondent aux 4 profils de visibilité définis dans l'architecture agnostique

### Profil "verified" (faits validés uniquement)

```cypher
// Seulement les relations avec 2+ sources et confiance >= 0.90
MATCH (s:CanonicalConcept)-[r]->(o:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH']
  AND r.maturity = 'VALIDATED'
  AND r.confidence >= 0.90
  AND r.source_count >= 2
RETURN s, r, o
```

### Profil "balanced" (défaut - équilibre qualité/quantité)

```cypher
// Relations validées ou candidates fiables (confiance >= 0.70)
MATCH (s:CanonicalConcept)-[r]->(o:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH']
  AND r.confidence >= 0.70
RETURN s, r, o
LIMIT 500
```

### Profil "exploratory" (maximum de connexions)

```cypher
// Toutes les relations avec confiance >= 0.40
MATCH (s:CanonicalConcept)-[r]->(o:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH']
  AND r.confidence >= 0.40
RETURN s, r, o
LIMIT 1000
```

### Profil "full_access" (admin - tout voir)

```cypher
// Accès complet sans filtre
MATCH (s:CanonicalConcept)-[r]->(o:CanonicalConcept)
WHERE type(r) IN ['REQUIRES', 'PART_OF', 'USES', 'CAUSES', 'ENABLES', 'ASSOCIATED_WITH', 'APPLIES_TO', 'INTEGRATES_WITH', 'EXTENDS', 'CONFLICTS_WITH', 'SUBTYPE_OF', 'PREVENTS']
RETURN s, r, o
LIMIT 2000
```

---

## ⚠️ Requêtes Dangereuses (avec précaution)

### Purge complète tenant (DANGER!)

```cypher
// NE PAS EXECUTER SANS CONFIRMATION
MATCH (n {tenant_id: 'default'})
DETACH DELETE n
```

### Supprimer un concept spécifique

```cypher
// Remplacer CONCEPT_ID par l'ID réel
MATCH (c:CanonicalConcept {canonical_id: 'CONCEPT_ID'})
DETACH DELETE c
```
