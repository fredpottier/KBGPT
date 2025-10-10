# Architecture Ontologies Neo4j - Analyse Complète

**Date** : 10 janvier 2025
**Sujet** : Faisabilité et stratégie d'isolation pour ontologies dans Neo4j

---

## 📋 État Actuel du Knowledge Graph

### Labels Neo4j Existants (KG Métier)
```cypher
// Actuellement utilisés pour données métier documents
:Entity        // Entités extraites des documents (SAP S/4HANA, Azure, etc.)
:Relation      // Relations entre entités
:Episode       // Unités de connaissance (slides/chunks)
:Fact          // Faits extraits
```

### Structure Entity Actuelle
```cypher
(:Entity {
    uuid: "...",
    name: "SAP S/4HANA Cloud",
    entity_type: "SOLUTION",
    status: "validated" | "pending",
    is_cataloged: true | false,
    tenant_id: "default",
    source_document: "doc_xyz.pptx",
    source_slide_number: 42,
    attributes: {...},  // JSON metadata
    created_at: datetime(),
    updated_at: datetime()
})
```

---

## 🎯 Stratégies d'Isolation KG Métier vs KG Ontologie

### **Option 1 : Labels Distincts (RECOMMANDÉ)**
**Principe** : Ontologies = labels Neo4j séparés

```cypher
// KG Ontologie (Référentiel)
(:OntologyEntity {
    entity_id: "S4HANA_CLOUD",           // ID catalogue
    canonical_name: "SAP S/4HANA Cloud",
    entity_type: "SOLUTION",
    category: "ERP",
    vendor: "SAP",
    confidence: 0.95,
    source: "llm_generated" | "manual",
    version: "2.1.0",
    created_at: datetime()
})

(:OntologyAlias {
    alias_id: "...",
    alias: "S/4HANA",
    normalized: "s/4hana"  // lowercase pour matching
})

// Relation ontologie → alias
(:OntologyEntity)-[:HAS_ALIAS]->(:OntologyAlias)

// KG Métier (Données documents - INCHANGÉ)
(:Entity {
    uuid: "...",
    name: "SAP S/4HANA Cloud",  // Normalisé via ontologie
    entity_type: "SOLUTION",
    status: "validated",
    catalog_id: "S4HANA_CLOUD",  // Référence ontologie
    ...
})
```

**Avantages** :
- ✅ **Isolation totale** : Queries métier ne touchent PAS ontologies
- ✅ **Performance** : Index séparés (pas de scan labels inutiles)
- ✅ **Sémantique claire** : :OntologyEntity vs :Entity
- ✅ **Évolution indépendante** : Modifier ontologies sans toucher données

**Queries Typiques** :
```cypher
// 1. Normalisation : Chercher ontologie par alias (RAPIDE avec index)
MATCH (alias:OntologyAlias {normalized: toLower($raw_name)})
      -[:BELONGS_TO]->(ont:OntologyEntity)
RETURN ont.entity_id, ont.canonical_name, ont.entity_type

// 2. KG Métier : Chercher entités documents (ne touche PAS ontologies)
MATCH (e:Entity {tenant_id: $tenant_id})
WHERE e.entity_type = 'SOLUTION'
RETURN e

// 3. Enrichissement : Joindre entités avec leur ontologie
MATCH (e:Entity {tenant_id: $tenant_id})
OPTIONAL MATCH (ont:OntologyEntity {entity_id: e.catalog_id})
RETURN e, ont
```

---

### **Option 2 : Propriété Discriminante (Déconseillé)**
**Principe** : Même label :Entity avec flag `is_ontology`

```cypher
// Ontologie
(:Entity {
    is_ontology: true,  // ← Flag discriminant
    entity_id: "S4HANA_CLOUD",
    canonical_name: "SAP S/4HANA Cloud",
    ...
})

// Données métier
(:Entity {
    is_ontology: false,  // ← Données réelles
    uuid: "...",
    name: "SAP S/4HANA Cloud",
    ...
})
```

**Problèmes** :
- ❌ **Pollution** : Queries métier doivent filtrer `is_ontology = false`
- ❌ **Performance** : Index pollués, scan inutile ontologies
- ❌ **Risque erreur** : Oublier filtre → résultats incorrects
- ❌ **Complexité requêtes** : WHERE clause systématique

**Verdict** : ❌ **À ÉVITER**

---

### **Option 3 : Database Séparée (Neo4j Enterprise)**
**Principe** : 2 databases Neo4j distinctes

```cypher
// Database "ontologies"
CREATE DATABASE ontologies

// Database "knowledge_graph" (défaut)
USE knowledge_graph
```

**Avantages** :
- ✅ **Isolation maximale** : Impossible de mélanger
- ✅ **Scaling indépendant** : Backup/restore séparés

**Inconvénients** :
- ❌ **Nécessite Neo4j Enterprise** (licence payante)
- ❌ **Pas de cross-database queries** (Neo4j 4.x limité)
- ❌ **Complexité opérationnelle** : 2 connexions, 2 migrations

**Verdict** : 🔵 **Optionnel si budget Enterprise**

---

## 🚀 Implémentation Recommandée : Labels Distincts

### **Phase 1 : Schéma Ontologie (1 semaine)**

#### **1.1 Créer Contraintes & Index**
```cypher
// Contraintes unicité
CREATE CONSTRAINT ont_entity_id_unique IF NOT EXISTS
FOR (ont:OntologyEntity) REQUIRE ont.entity_id IS UNIQUE;

CREATE CONSTRAINT ont_alias_unique IF NOT EXISTS
FOR (alias:OntologyAlias) REQUIRE (alias.normalized, alias.entity_type) IS UNIQUE;

// Index performance
CREATE INDEX ont_alias_normalized IF NOT EXISTS
FOR (alias:OntologyAlias) ON (alias.normalized);

CREATE INDEX ont_entity_type IF NOT EXISTS
FOR (ont:OntologyEntity) ON (ont.entity_type);

CREATE INDEX ont_canonical_lower IF NOT EXISTS
FOR (ont:OntologyEntity) ON (toLower(ont.canonical_name));
```

#### **1.2 Migration YAML → Neo4j**
```python
def migrate_yaml_to_neo4j():
    """Migre catalogues YAML vers Neo4j OntologyEntity."""

    driver = GraphDatabase.driver(...)

    for yaml_file in Path("config/ontologies").glob("*.yaml"):
        data = yaml.safe_load(yaml_file.read_text())

        for entity_type, entities in data.items():
            for entity_id, entity_data in entities.items():

                # Créer OntologyEntity
                with driver.session() as session:
                    session.run("""
                        MERGE (ont:OntologyEntity {entity_id: $entity_id})
                        SET ont.canonical_name = $canonical_name,
                            ont.entity_type = $entity_type,
                            ont.category = $category,
                            ont.vendor = $vendor,
                            ont.source = 'yaml_migrated',
                            ont.created_at = datetime()
                    """, {
                        "entity_id": entity_id,
                        "canonical_name": entity_data["canonical_name"],
                        "entity_type": entity_type,
                        "category": entity_data.get("category"),
                        "vendor": entity_data.get("vendor")
                    })

                    # Créer aliases
                    aliases = entity_data.get("aliases", [])
                    aliases.append(entity_data["canonical_name"])  # Canonical aussi alias

                    for alias in aliases:
                        session.run("""
                            MATCH (ont:OntologyEntity {entity_id: $entity_id})
                            MERGE (alias:OntologyAlias {
                                normalized: toLower($alias),
                                entity_type: $entity_type
                            })
                            SET alias.alias = $alias
                            MERGE (alias)-[:BELONGS_TO]->(ont)
                        """, {
                            "entity_id": entity_id,
                            "alias": alias,
                            "entity_type": entity_type
                        })
```

---

### **Phase 2 : Service Normalisation Neo4j (3-5 jours)**

#### **2.1 Nouveau EntityNormalizerNeo4j**
```python
class EntityNormalizerNeo4j:
    """Normalizer basé sur Neo4j Ontology."""

    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )

    def normalize_entity_name(
        self,
        raw_name: str,
        entity_type_hint: str = None  # Type LLM = hint, pas contrainte
    ) -> Tuple[str, str, str, bool]:
        """
        Normalise nom via ontologie Neo4j.

        Returns:
            (entity_id, canonical_name, entity_type, is_cataloged)
        """

        with self.driver.session() as session:
            # Cherche dans ontologie (index global, type optionnel)
            query = """
            MATCH (alias:OntologyAlias {normalized: toLower($raw_name)})
                  -[:BELONGS_TO]->(ont:OntologyEntity)
            """

            params = {"raw_name": raw_name}

            # Si type hint fourni, filtrer (mais pas bloquer)
            if entity_type_hint:
                query += "WHERE ont.entity_type = $entity_type_hint"
                params["entity_type_hint"] = entity_type_hint

            query += """
            RETURN ont.entity_id AS entity_id,
                   ont.canonical_name AS canonical_name,
                   ont.entity_type AS entity_type,
                   ont.category AS category,
                   ont.vendor AS vendor
            LIMIT 1
            """

            result = session.run(query, params)
            record = result.single()

            if record:
                # Trouvé dans ontologie
                return (
                    record["entity_id"],
                    record["canonical_name"],
                    record["entity_type"],
                    True  # is_cataloged
                )

            # Pas trouvé → retourner brut
            return (None, raw_name.strip(), entity_type_hint, False)
```

#### **2.2 Migration Changement Type**
```python
def migrate_entity_type(entity_id: str, new_type: str):
    """Change type d'une entité ontologie (ex: SOLUTION → SOFTWARE)."""

    with driver.session() as session:
        # Update type ontologie (simple property update)
        session.run("""
            MATCH (ont:OntologyEntity {entity_id: $entity_id})
            SET ont.entity_type = $new_type,
                ont.updated_at = datetime()
        """, {"entity_id": entity_id, "new_type": new_type})

        # Update aliases avec nouveau type (pour contrainte unicité)
        session.run("""
            MATCH (ont:OntologyEntity {entity_id: $entity_id})
                  <-[:BELONGS_TO]-(alias:OntologyAlias)
            SET alias.entity_type = $new_type
        """, {"entity_id": entity_id, "new_type": new_type})

        # ✅ Pas besoin de toucher :Entity (données métier)
        # Prochaine normalisation utilisera nouveau type automatiquement
```

---

### **Phase 3 : Sauvegarde Ontologies (2 jours)**

#### **3.1 Auto-Save après Normalisation**
```python
def save_ontology_after_merge(merge_groups: List[Dict], entity_type: str):
    """Sauvegarde ontologie générée par LLM dans Neo4j."""

    with driver.session() as session:
        for group in merge_groups:
            entity_id = group["canonical_key"]
            canonical_name = group["canonical_name"]

            # Créer/update OntologyEntity
            session.run("""
                MERGE (ont:OntologyEntity {entity_id: $entity_id})
                SET ont.canonical_name = $canonical_name,
                    ont.entity_type = $entity_type,
                    ont.source = 'llm_generated',
                    ont.confidence = $confidence,
                    ont.created_at = coalesce(ont.created_at, datetime()),
                    ont.updated_at = datetime()
            """, {
                "entity_id": entity_id,
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "confidence": group.get("confidence", 0.95)
            })

            # Créer aliases depuis entités mergées
            for entity in group["entities"]:
                if entity["name"].lower() != canonical_name.lower():
                    session.run("""
                        MATCH (ont:OntologyEntity {entity_id: $entity_id})
                        MERGE (alias:OntologyAlias {
                            normalized: toLower($alias),
                            entity_type: $entity_type
                        })
                        SET alias.alias = $alias
                        MERGE (alias)-[:BELONGS_TO]->(ont)
                    """, {
                        "entity_id": entity_id,
                        "alias": entity["name"],
                        "entity_type": entity_type
                    })
```

---

## 📊 Complexité d'Implémentation

### **Effort Estimé (Labels Distincts)**

| Phase | Tâche | Effort | Difficulté |
|-------|-------|--------|------------|
| **Phase 1** | Schéma Neo4j (contraintes/index) | 1 jour | ⭐ Facile |
| | Migration YAML → Neo4j | 2 jours | ⭐⭐ Moyen |
| | Tests migration | 1 jour | ⭐ Facile |
| **Phase 2** | Service EntityNormalizerNeo4j | 2 jours | ⭐⭐ Moyen |
| | Intégration pipeline ingestion | 1 jour | ⭐⭐ Moyen |
| | Tests unitaires + intégration | 2 jours | ⭐⭐ Moyen |
| **Phase 3** | Auto-save après normalisation | 1 jour | ⭐ Facile |
| | Migration changement type | 1 jour | ⭐⭐ Moyen |
| | Documentation | 1 jour | ⭐ Facile |
| **TOTAL** | | **12 jours** | ⭐⭐ **Moyen** |

### **Risques & Mitigations**

| Risque | Impact | Probabilité | Mitigation |
|--------|--------|-------------|------------|
| Migration YAML incomplète | 🔴 Élevé | Faible | Script validation post-migration + rollback |
| Performance lookup dégradée | 🟡 Moyen | Faible | Index optimisés + benchmark (déjà fait) |
| Doublons ontologie vs métier | 🟡 Moyen | Moyen | Labels distincts + contraintes unicité |
| Complexité queries | 🟢 Faible | Faible | Abstraction service + tests |

---

## 🔍 Comparaison Solutions

### **YAML vs SQLite vs Neo4j**

| Critère | YAML (Actuel) | SQLite | Neo4j Ontology |
|---------|---------------|--------|----------------|
| **Startup** | 4.8s (10K) 🔴 | 200ms ✅ | ~50ms ✅ |
| **Lookup** | 0.04 µs ✅ | 50 µs ⚠️ | ~1 µs ✅ |
| **Types dynamiques** | ❌ Fichiers hardcodés | ✅ Table flexible | ✅ Nodes flexibles |
| **Changement type** | ❌ Migration fichier | ✅ UPDATE SQL | ✅ SET property |
| **Versioning** | ❌ Git seulement | ✅ Migrations SQL | ✅ Properties versionnées |
| **Intégration KG** | ❌ Externe | ⚠️ Séparé | ✅ Même base |
| **Scalabilité** | ~15K max 🔴 | ~100K ✅ | Illimitée ✅ |
| **Complexité impl** | - | ⭐⭐ Moyen | ⭐⭐⭐ Moyen+ |
| **Maintenance** | ⭐ Simple | ⭐⭐ Moyen | ⭐⭐⭐ Complexe |

---

## ✅ Recommandation Finale

### **Partir DIRECTEMENT sur Neo4j Ontology ?**

**OUI, SI :**
- ✅ Vous avez **2-3 semaines** disponibles pour implémentation
- ✅ Équipe **confortable avec Neo4j** (déjà utilisé pour KG)
- ✅ Vision **long terme** (>12 mois, >50K entités)
- ✅ Besoin **forte intégration** ontologie ↔ KG métier

**NON, SI :**
- ❌ Besoin **quick win** (<1 semaine)
- ❌ Équipe **peu expérience Neo4j**
- ❌ Budget temps limité (préférer SQLite)
- ❌ Incertitude sur évolution architecture

### **Plan Hybride Recommandé**

**Phase 1 (1 semaine) : Quick Fix SQLite**
- Implémenter SQLite avec index global
- Résoudre problèmes types dynamiques + changements type
- Gagner temps pour préparer Neo4j

**Phase 2 (2-3 mois) : Migration Neo4j**
- Quand système stabilisé
- Migration progressive SQLite → Neo4j
- Dual-mode pendant transition

---

## 🎯 Réponse aux Questions

### **Q1 : Difficulté implémentation Neo4j ?**
**R** : **Moyennement complexe** (12 jours dev + tests)
- ⭐⭐ Migration YAML → Neo4j (patterns connus)
- ⭐⭐ Service normalisation (queries Cypher simples)
- ⭐ Auto-save ontologies (déjà fait pour :Entity)

### **Q2 : Comment éviter pollution KG métier ?**
**R** : **Labels distincts = isolation parfaite**
```cypher
// Ontologies (référentiel)
:OntologyEntity, :OntologyAlias
    ↓
// Relations
-[:HAS_ALIAS]-, -[:BELONGS_TO]-
    ↓
// KG Métier (données) - INCHANGÉ
:Entity, :Relation, :Episode, :Fact
```

**Avantages isolation** :
- ✅ Queries métier **jamais** scan ontologies
- ✅ Index séparés (performance)
- ✅ Évolution indépendante
- ✅ Backup/restore sélectif

---

## 📝 Conclusion

**Neo4j Ontology est la solution ultime MAIS nécessite investissement initial.**

**Recommandation pragmatique** :
1. **Court terme (maintenant)** : SQLite (1 semaine impl)
2. **Moyen terme (3-6 mois)** : Migration Neo4j (12 jours impl)
3. **Avantage** : SQLite valide architecture, Neo4j optimise long terme

**Si budget temps OK (3 semaines)** : Partir direct Neo4j ✅
**Si urgence (<1 semaine)** : SQLite puis migration ✅

