# Guide d'Implémentation : Migration Ontologies vers Neo4j

**Projet** : SAP Knowledge Base
**Date** : Janvier 2025
**Auteur** : Claude Code - Expert Architecture
**Durée estimée** : 12-15 jours (3 semaines)

---

## 📋 Table des Matières

1. [Vue d'Ensemble](#vue-densemble)
2. [Architecture Cible](#architecture-cible)
3. [Prérequis & Préparation](#prérequis--préparation)
4. [Phase 1 : Schéma Neo4j](#phase-1--schéma-neo4j)
5. [Phase 2 : Migration Données](#phase-2--migration-données)
6. [Phase 3 : Service Normalisation](#phase-3--service-normalisation)
7. [Phase 4 : Intégration Pipeline](#phase-4--intégration-pipeline)
8. [Phase 5 : Auto-Save Ontologies](#phase-5--auto-save-ontologies)
9. [Phase 6 : Tests & Validation](#phase-6--tests--validation)
10. [Phase 7 : Déploiement](#phase-7--déploiement)
11. [Annexes](#annexes)

---

## 🎯 Vue d'Ensemble

### **Objectif**
Migrer le système d'ontologies de fichiers YAML statiques vers Neo4j pour :
- ✅ Supporter types d'entités dynamiques (créés via frontend)
- ✅ Permettre changement de type sans migration manuelle
- ✅ Scalabilité illimitée (vs YAML limité à ~15K entités)
- ✅ Intégration native avec Knowledge Graph existant

### **Problèmes Résolus**
1. ❌ **Fichiers YAML hardcodés** → ✅ Ontologies flexibles Neo4j
2. ❌ **Couplage Type ↔ Fichier** → ✅ Index global indépendant du type
3. ❌ **Changement type = migration fichier** → ✅ Simple UPDATE property
4. ❌ **Startup lent (4.8s pour 10K)** → ✅ Lookup <1 µs
5. ❌ **Boucle feedback cassée** → ✅ Auto-save après normalisation

### **Stratégie d'Isolation KG**
- **Labels distincts** : `:OntologyEntity`, `:OntologyAlias` vs `:Entity`, `:Relation`
- **Aucune pollution** : Queries métier ne touchent jamais les ontologies
- **Index séparés** : Performance optimale pour chaque domaine

---

## 🏗️ Architecture Cible

### **Schéma Neo4j Complet**

```cypher
// ============================================
// ONTOLOGIES (Référentiel - NOUVEAU)
// ============================================

// Node 1 : OntologyEntity (Entité catalogue)
(:OntologyEntity {
    entity_id: String (UNIQUE),           // Ex: "S4HANA_CLOUD"
    canonical_name: String (NOT NULL),    // Ex: "SAP S/4HANA Cloud"
    entity_type: String (NOT NULL),       // Ex: "SOLUTION" (flexible)
    category: String,                     // Ex: "ERP"
    vendor: String,                       // Ex: "SAP"
    confidence: Float,                    // Ex: 0.95
    source: String,                       // "manual" | "llm_generated" | "yaml_migrated"
    version: String,                      // Ex: "2.1.0"
    description: String,
    created_at: DateTime (NOT NULL),
    updated_at: DateTime,
    created_by: String,                   // Email admin
    tenant_id: String (DEFAULT "default")
})

// Node 2 : OntologyAlias (Index normalization)
(:OntologyAlias {
    alias_id: String (UNIQUE),            // UUID auto
    alias: String (NOT NULL),             // Ex: "S/4HANA"
    normalized: String (NOT NULL, INDEX), // Ex: "s/4hana" (lowercase)
    entity_type: String (NOT NULL),       // Pour contrainte unique
    tenant_id: String (DEFAULT "default")
})

// Relation : OntologyEntity ←→ OntologyAlias
(:OntologyEntity)-[:HAS_ALIAS {
    added_at: DateTime,
    added_by: String
}]->(:OntologyAlias)

// ============================================
// KG MÉTIER (Données documents - INCHANGÉ)
// ============================================

(:Entity {
    uuid: String (UNIQUE),
    name: String,                         // Normalisé via ontologie
    entity_type: String,
    status: String,                       // "validated" | "pending"
    catalog_id: String,                   // Référence OntologyEntity.entity_id
    is_cataloged: Boolean,
    tenant_id: String,
    source_document: String,
    ...
})

(:Relation), (:Episode), (:Fact)         // Existant inchangé
```

### **Diagramme Architecture**

```
┌─────────────────────────────────────────────────────────┐
│                    Neo4j Database                        │
│                                                          │
│  ┌────────────────────────────────────────────────┐    │
│  │  ONTOLOGIES (Référentiel)                      │    │
│  │                                                 │    │
│  │  (:OntologyEntity)──[:HAS_ALIAS]→(:OntologyAlias) │
│  │       ↑                                         │    │
│  │       │ Index global (normalized)               │    │
│  │       │ Recherche O(1)                          │    │
│  └───────┼─────────────────────────────────────────┘    │
│          │                                               │
│          │ catalog_id (référence logique)               │
│          ↓                                               │
│  ┌──────────────────────────────────────────────┐      │
│  │  KG MÉTIER (Données documents)               │      │
│  │                                               │      │
│  │  (:Entity)──[:RELATED_TO]→(:Entity)          │      │
│  │      ↓                                        │      │
│  │  (:Relation), (:Episode), (:Fact)            │      │
│  └──────────────────────────────────────────────┘      │
│                                                          │
└─────────────────────────────────────────────────────────┘

Pipeline Ingestion :
1. LLM extrait "S/4HANA" type="SOLUTION"
2. EntityNormalizerNeo4j.normalize("S/4HANA")
3. Query: MATCH (a:OntologyAlias {normalized: "s/4hana"})-[:BELONGS_TO]->(ont)
4. Return: entity_id="S4HANA_CLOUD", canonical="SAP S/4HANA Cloud"
5. Create :Entity avec name="SAP S/4HANA Cloud", catalog_id="S4HANA_CLOUD"
```

---

## 🔧 Prérequis & Préparation

### **Checklist Avant Démarrage**

- [ ] **Neo4j accessible** (vérifier docker-compose ps)
- [ ] **Backup base actuelle** (Neo4j + YAML)
- [ ] **Branche Git dédiée** : `feat/neo4j-ontology`
- [ ] **Python packages** : `neo4j>=5.0`, `pyyaml>=6.0`
- [ ] **Tests existants OK** : `pytest tests/`
- [ ] **Documentation lue** : Ce guide complet

### **Commandes Préparation**

```bash
# 1. Créer branche
git checkout -b feat/neo4j-ontology

# 2. Backup Neo4j
docker compose exec neo4j neo4j-admin database dump neo4j --to-path=/backups
docker compose cp neo4j:/backups/neo4j.dump ./backups/neo4j_pre_ontology_$(date +%Y%m%d).dump

# 3. Backup YAML
tar -czf backups/ontologies_yaml_$(date +%Y%m%d).tar.gz config/ontologies/

# 4. Vérifier tests actuels
pytest tests/ -v

# 5. Créer répertoire travail
mkdir -p src/knowbase/ontology
mkdir -p tests/ontology
```

---

## 📐 Phase 1 : Schéma Neo4j (Jour 1-2)

### **Étape 1.1 : Créer Script Contraintes**

**Fichier** : `src/knowbase/ontology/neo4j_schema.py`

```python
"""
Schéma Neo4j pour Ontologies.

Contraintes, index et structure données.
"""
from neo4j import GraphDatabase
from typing import List
import logging

logger = logging.getLogger(__name__)


class OntologySchema:
    """Gestion schéma Neo4j ontologies."""

    def __init__(self, driver: GraphDatabase.driver):
        self.driver = driver

    def create_constraints(self) -> List[str]:
        """
        Crée toutes les contraintes nécessaires.

        Returns:
            Liste des contraintes créées
        """
        constraints = []

        with self.driver.session() as session:
            # 1. Contrainte unicité entity_id
            try:
                session.run("""
                    CREATE CONSTRAINT ont_entity_id_unique IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    REQUIRE ont.entity_id IS UNIQUE
                """)
                constraints.append("ont_entity_id_unique")
                logger.info("✅ Contrainte ont_entity_id_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte ont_entity_id_unique existe déjà: {e}")

            # 2. Contrainte unicité alias_id
            try:
                session.run("""
                    CREATE CONSTRAINT ont_alias_id_unique IF NOT EXISTS
                    FOR (alias:OntologyAlias)
                    REQUIRE alias.alias_id IS UNIQUE
                """)
                constraints.append("ont_alias_id_unique")
                logger.info("✅ Contrainte ont_alias_id_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte ont_alias_id_unique existe déjà: {e}")

            # 3. Contrainte unicité composite (normalized, entity_type, tenant_id)
            try:
                session.run("""
                    CREATE CONSTRAINT ont_alias_normalized_unique IF NOT EXISTS
                    FOR (alias:OntologyAlias)
                    REQUIRE (alias.normalized, alias.entity_type, alias.tenant_id) IS UNIQUE
                """)
                constraints.append("ont_alias_normalized_unique")
                logger.info("✅ Contrainte ont_alias_normalized_unique créée")
            except Exception as e:
                logger.warning(f"Contrainte ont_alias_normalized_unique existe déjà: {e}")

        return constraints

    def create_indexes(self) -> List[str]:
        """
        Crée tous les index pour performance.

        Returns:
            Liste des index créés
        """
        indexes = []

        with self.driver.session() as session:
            # 1. Index sur normalized (lookup principal)
            try:
                session.run("""
                    CREATE INDEX ont_alias_normalized_idx IF NOT EXISTS
                    FOR (alias:OntologyAlias)
                    ON (alias.normalized)
                """)
                indexes.append("ont_alias_normalized_idx")
                logger.info("✅ Index ont_alias_normalized_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_alias_normalized_idx existe déjà: {e}")

            # 2. Index sur entity_type (filtrage)
            try:
                session.run("""
                    CREATE INDEX ont_entity_type_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.entity_type)
                """)
                indexes.append("ont_entity_type_idx")
                logger.info("✅ Index ont_entity_type_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_entity_type_idx existe déjà: {e}")

            # 3. Index sur canonical_name (lowercase pour search)
            try:
                session.run("""
                    CREATE INDEX ont_canonical_lower_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.canonical_name)
                """)
                indexes.append("ont_canonical_lower_idx")
                logger.info("✅ Index ont_canonical_lower_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_canonical_lower_idx existe déjà: {e}")

            # 4. Index sur tenant_id (multi-tenancy)
            try:
                session.run("""
                    CREATE INDEX ont_tenant_idx IF NOT EXISTS
                    FOR (ont:OntologyEntity)
                    ON (ont.tenant_id)
                """)
                indexes.append("ont_tenant_idx")
                logger.info("✅ Index ont_tenant_idx créé")
            except Exception as e:
                logger.warning(f"Index ont_tenant_idx existe déjà: {e}")

        return indexes

    def validate_schema(self) -> dict:
        """
        Valide que le schéma est correctement créé.

        Returns:
            Dict avec statut validation
        """
        with self.driver.session() as session:
            # Vérifier contraintes
            result = session.run("SHOW CONSTRAINTS")
            constraints = [record["name"] for record in result]

            # Vérifier index
            result = session.run("SHOW INDEXES")
            indexes = [record["name"] for record in result]

            return {
                "constraints": constraints,
                "indexes": indexes,
                "valid": (
                    "ont_entity_id_unique" in constraints and
                    "ont_alias_normalized_idx" in indexes
                )
            }


def apply_ontology_schema(neo4j_uri: str, neo4j_user: str, neo4j_password: str):
    """
    Point d'entrée : applique schéma complet.

    Args:
        neo4j_uri: URI Neo4j
        neo4j_user: Username
        neo4j_password: Password
    """
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        schema = OntologySchema(driver)

        logger.info("🚀 Application schéma Neo4j ontologies...")

        # Créer contraintes
        constraints = schema.create_constraints()
        logger.info(f"✅ {len(constraints)} contraintes créées")

        # Créer index
        indexes = schema.create_indexes()
        logger.info(f"✅ {len(indexes)} index créés")

        # Valider
        validation = schema.validate_schema()
        if validation["valid"]:
            logger.info("✅ Schéma validé avec succès")
        else:
            logger.error("❌ Schéma invalide")
            logger.error(f"Contraintes: {validation['constraints']}")
            logger.error(f"Index: {validation['indexes']}")

        return validation

    finally:
        driver.close()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    apply_ontology_schema(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password")
    )
```

### **Étape 1.2 : Exécuter Création Schéma**

```bash
# Appliquer schéma
python src/knowbase/ontology/neo4j_schema.py

# Vérifier dans Neo4j Browser
docker compose exec neo4j cypher-shell -u neo4j -p password \
  "SHOW CONSTRAINTS"

docker compose exec neo4j cypher-shell -u neo4j -p password \
  "SHOW INDEXES"
```

**Résultat attendu** :
```
Contraintes:
- ont_entity_id_unique
- ont_alias_id_unique
- ont_alias_normalized_unique

Index:
- ont_alias_normalized_idx
- ont_entity_type_idx
- ont_canonical_lower_idx
- ont_tenant_idx
```

---

## 🔄 Phase 2 : Migration Données (Jour 3-4)

### **Étape 2.1 : Script Migration YAML → Neo4j**

**Fichier** : `src/knowbase/ontology/migrate_yaml_to_neo4j.py`

```python
"""
Migration ontologies YAML vers Neo4j.

Migre tous les fichiers config/ontologies/*.yaml vers :OntologyEntity + :OntologyAlias.
"""
from pathlib import Path
from typing import Dict, List
import yaml
import uuid
from datetime import datetime, timezone
from neo4j import GraphDatabase
import logging

logger = logging.getLogger(__name__)


class YAMLToNeo4jMigrator:
    """Migre ontologies YAML vers Neo4j."""

    def __init__(self, driver: GraphDatabase.driver, ontology_dir: Path):
        self.driver = driver
        self.ontology_dir = ontology_dir

    def migrate_all(self, tenant_id: str = "default") -> dict:
        """
        Migre tous les fichiers YAML vers Neo4j.

        Args:
            tenant_id: Tenant ID pour multi-tenancy

        Returns:
            Dict avec statistiques migration
        """
        stats = {
            "files_processed": 0,
            "entities_created": 0,
            "aliases_created": 0,
            "errors": []
        }

        yaml_files = list(self.ontology_dir.glob("*.yaml"))
        logger.info(f"🔍 Trouvé {len(yaml_files)} fichiers YAML à migrer")

        for yaml_file in yaml_files:
            # Skip fichiers spéciaux
            if yaml_file.name in ["uncataloged_entities.log", "README.md"]:
                continue

            try:
                logger.info(f"📄 Migration {yaml_file.name}...")
                file_stats = self._migrate_file(yaml_file, tenant_id)

                stats["files_processed"] += 1
                stats["entities_created"] += file_stats["entities"]
                stats["aliases_created"] += file_stats["aliases"]

                logger.info(
                    f"✅ {yaml_file.name}: {file_stats['entities']} entités, "
                    f"{file_stats['aliases']} aliases"
                )

            except Exception as e:
                error_msg = f"Erreur migration {yaml_file.name}: {e}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)

        return stats

    def _migrate_file(self, yaml_file: Path, tenant_id: str) -> dict:
        """
        Migre un fichier YAML vers Neo4j.

        Args:
            yaml_file: Chemin fichier YAML
            tenant_id: Tenant ID

        Returns:
            Dict avec stats fichier
        """
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        stats = {"entities": 0, "aliases": 0}

        # Structure attendue: {ENTITY_TYPE: {ENTITY_ID: {...}}}
        for entity_type_key, entities in data.items():
            if not isinstance(entities, dict):
                continue

            # entity_type_key peut être "SOLUTION", "SOLUTIONS", etc.
            # Normaliser vers singulier UPPERCASE
            entity_type = entity_type_key.rstrip('S').upper()

            for entity_id, entity_data in entities.items():
                # Créer OntologyEntity
                self._create_ontology_entity(
                    entity_id=entity_id,
                    canonical_name=entity_data["canonical_name"],
                    entity_type=entity_type,
                    category=entity_data.get("category"),
                    vendor=entity_data.get("vendor"),
                    description=entity_data.get("description"),
                    tenant_id=tenant_id
                )
                stats["entities"] += 1

                # Créer aliases
                aliases = entity_data.get("aliases", [])
                # Ajouter canonical_name comme alias aussi
                aliases.append(entity_data["canonical_name"])

                for alias in set(aliases):  # set() pour éviter doublons
                    self._create_alias(
                        entity_id=entity_id,
                        alias=alias,
                        entity_type=entity_type,
                        tenant_id=tenant_id
                    )
                    stats["aliases"] += 1

        return stats

    def _create_ontology_entity(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        category: str = None,
        vendor: str = None,
        description: str = None,
        tenant_id: str = "default"
    ):
        """Crée OntologyEntity dans Neo4j."""

        with self.driver.session() as session:
            session.run("""
                MERGE (ont:OntologyEntity {entity_id: $entity_id})
                SET ont.canonical_name = $canonical_name,
                    ont.entity_type = $entity_type,
                    ont.category = $category,
                    ont.vendor = $vendor,
                    ont.description = $description,
                    ont.source = 'yaml_migrated',
                    ont.version = '1.0.0',
                    ont.tenant_id = $tenant_id,
                    ont.created_at = coalesce(ont.created_at, datetime()),
                    ont.updated_at = datetime()
            """, {
                "entity_id": entity_id,
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "category": category,
                "vendor": vendor,
                "description": description,
                "tenant_id": tenant_id
            })

    def _create_alias(
        self,
        entity_id: str,
        alias: str,
        entity_type: str,
        tenant_id: str = "default"
    ):
        """Crée OntologyAlias et relation avec OntologyEntity."""

        alias_id = str(uuid.uuid4())
        normalized = alias.lower().strip()

        with self.driver.session() as session:
            session.run("""
                MATCH (ont:OntologyEntity {entity_id: $entity_id})
                MERGE (alias:OntologyAlias {
                    normalized: $normalized,
                    entity_type: $entity_type,
                    tenant_id: $tenant_id
                })
                ON CREATE SET
                    alias.alias_id = $alias_id,
                    alias.alias = $alias
                MERGE (ont)-[:HAS_ALIAS]->(alias)
            """, {
                "entity_id": entity_id,
                "alias_id": alias_id,
                "alias": alias,
                "normalized": normalized,
                "entity_type": entity_type,
                "tenant_id": tenant_id
            })

    def validate_migration(self) -> dict:
        """
        Valide que la migration est complète.

        Returns:
            Dict avec statistiques validation
        """
        with self.driver.session() as session:
            # Compter entités
            result = session.run("""
                MATCH (ont:OntologyEntity)
                RETURN count(ont) AS entities_count
            """)
            entities_count = result.single()["entities_count"]

            # Compter aliases
            result = session.run("""
                MATCH (alias:OntologyAlias)
                RETURN count(alias) AS aliases_count
            """)
            aliases_count = result.single()["aliases_count"]

            # Vérifier relations
            result = session.run("""
                MATCH (ont:OntologyEntity)-[:HAS_ALIAS]->(alias:OntologyAlias)
                RETURN count(*) AS relations_count
            """)
            relations_count = result.single()["relations_count"]

            # Entités sans alias (problème)
            result = session.run("""
                MATCH (ont:OntologyEntity)
                WHERE NOT (ont)-[:HAS_ALIAS]->()
                RETURN count(ont) AS orphan_count
            """)
            orphan_count = result.single()["orphan_count"]

            return {
                "entities": entities_count,
                "aliases": aliases_count,
                "relations": relations_count,
                "orphans": orphan_count,
                "valid": orphan_count == 0
            }


def run_migration(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    ontology_dir: Path,
    tenant_id: str = "default"
):
    """
    Point d'entrée migration.

    Args:
        neo4j_uri: URI Neo4j
        neo4j_user: Username
        neo4j_password: Password
        ontology_dir: Chemin répertoire ontologies YAML
        tenant_id: Tenant ID
    """
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        migrator = YAMLToNeo4jMigrator(driver, ontology_dir)

        logger.info("🚀 Démarrage migration YAML → Neo4j...")

        # Exécuter migration
        stats = migrator.migrate_all(tenant_id)

        logger.info("=" * 60)
        logger.info("📊 STATISTIQUES MIGRATION")
        logger.info(f"Fichiers traités   : {stats['files_processed']}")
        logger.info(f"Entités créées     : {stats['entities_created']}")
        logger.info(f"Aliases créés      : {stats['aliases_created']}")
        logger.info(f"Erreurs            : {len(stats['errors'])}")
        if stats['errors']:
            for error in stats['errors']:
                logger.error(f"  - {error}")
        logger.info("=" * 60)

        # Validation
        logger.info("🔍 Validation migration...")
        validation = migrator.validate_migration()

        logger.info("📊 VALIDATION")
        logger.info(f"Entités totales    : {validation['entities']}")
        logger.info(f"Aliases totaux     : {validation['aliases']}")
        logger.info(f"Relations          : {validation['relations']}")
        logger.info(f"Orphelins (erreur) : {validation['orphans']}")

        if validation["valid"]:
            logger.info("✅ Migration validée avec succès !")
        else:
            logger.error("❌ Migration incomplète (entités orphelines)")

        return stats, validation

    finally:
        driver.close()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    run_migration(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password"),
        ontology_dir=Path("config/ontologies"),
        tenant_id="default"
    )
```

### **Étape 2.2 : Exécuter Migration**

```bash
# 1. Migration
python src/knowbase/ontology/migrate_yaml_to_neo4j.py

# 2. Vérifier dans Neo4j Browser
docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (ont:OntologyEntity) RETURN count(ont)"

docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (alias:OntologyAlias) RETURN count(alias)"

# 3. Tester lookup
docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (alias:OntologyAlias {normalized: 's/4hana'})-[:BELONGS_TO]->(ont) RETURN ont.canonical_name"
```

**Résultat attendu** :
```
Entités créées : ~500
Aliases créés : ~2000
Relations : ~2000
Orphelins : 0
```

---

## 🔨 Phase 3 : Service Normalisation (Jour 5-7)

### **Étape 3.1 : EntityNormalizerNeo4j**

**Fichier** : `src/knowbase/ontology/entity_normalizer_neo4j.py`

```python
"""
EntityNormalizer basé sur Neo4j.

Remplace EntityNormalizer YAML pour normalisation via ontologies Neo4j.
"""
from typing import Tuple, Optional, Dict
from neo4j import GraphDatabase
import logging

logger = logging.getLogger(__name__)


class EntityNormalizerNeo4j:
    """
    Normalizer basé sur Neo4j Ontology.

    Recherche entités dans :OntologyEntity via :OntologyAlias.
    """

    def __init__(self, driver: GraphDatabase.driver):
        """
        Initialise normalizer.

        Args:
            driver: Neo4j driver
        """
        self.driver = driver

    def normalize_entity_name(
        self,
        raw_name: str,
        entity_type_hint: Optional[str] = None,
        tenant_id: str = "default"
    ) -> Tuple[Optional[str], str, Optional[str], bool]:
        """
        Normalise nom d'entité via ontologie Neo4j.

        Args:
            raw_name: Nom brut extrait par LLM
            entity_type_hint: Type suggéré par LLM (optionnel, pas contrainte)
            tenant_id: Tenant ID

        Returns:
            Tuple (entity_id, canonical_name, entity_type, is_cataloged)
            - entity_id: ID catalogue (ex: "S4HANA_CLOUD") ou None
            - canonical_name: Nom normalisé (ex: "SAP S/4HANA Cloud")
            - entity_type: Type découvert (peut différer du hint)
            - is_cataloged: True si trouvé dans ontologie
        """
        normalized_search = raw_name.strip().lower()

        with self.driver.session() as session:
            # Query ontologie (index global sur normalized)
            query = """
            MATCH (alias:OntologyAlias {
                normalized: $normalized,
                tenant_id: $tenant_id
            })-[:BELONGS_TO]->(ont:OntologyEntity)
            """

            params = {
                "normalized": normalized_search,
                "tenant_id": tenant_id
            }

            # Filtrer par type si hint fourni (mais pas bloquer si pas trouvé)
            if entity_type_hint:
                query += " WHERE ont.entity_type = $entity_type_hint"
                params["entity_type_hint"] = entity_type_hint

            query += """
            RETURN
                ont.entity_id AS entity_id,
                ont.canonical_name AS canonical_name,
                ont.entity_type AS entity_type,
                ont.category AS category,
                ont.vendor AS vendor,
                ont.confidence AS confidence
            LIMIT 1
            """

            result = session.run(query, params)
            record = result.single()

            if record:
                # Trouvé dans ontologie
                logger.debug(
                    f"✅ Normalisé: '{raw_name}' → '{record['canonical_name']}' "
                    f"(type={record['entity_type']}, id={record['entity_id']})"
                )

                return (
                    record["entity_id"],
                    record["canonical_name"],
                    record["entity_type"],
                    True  # is_cataloged
                )

            # Pas trouvé → essayer sans filtrage type
            if entity_type_hint:
                logger.debug(
                    f"⚠️ '{raw_name}' pas trouvé avec type={entity_type_hint}, "
                    "retry sans filtrage type..."
                )

                query_no_type = """
                MATCH (alias:OntologyAlias {
                    normalized: $normalized,
                    tenant_id: $tenant_id
                })-[:BELONGS_TO]->(ont:OntologyEntity)
                RETURN
                    ont.entity_id AS entity_id,
                    ont.canonical_name AS canonical_name,
                    ont.entity_type AS entity_type
                LIMIT 1
                """

                result = session.run(query_no_type, {
                    "normalized": normalized_search,
                    "tenant_id": tenant_id
                })
                record = result.single()

                if record:
                    logger.info(
                        f"✅ Normalisé (type corrigé): '{raw_name}' → "
                        f"'{record['canonical_name']}' "
                        f"(type LLM={entity_type_hint} → type réel={record['entity_type']})"
                    )

                    return (
                        record["entity_id"],
                        record["canonical_name"],
                        record["entity_type"],
                        True
                    )

            # Vraiment pas trouvé → retourner brut
            logger.debug(
                f"⚠️ Entité non cataloguée: '{raw_name}' (type={entity_type_hint})"
            )

            return (
                None,
                raw_name.strip(),
                entity_type_hint,
                False  # is_cataloged
            )

    def get_entity_metadata(
        self,
        entity_id: str,
        tenant_id: str = "default"
    ) -> Optional[Dict]:
        """
        Récupère métadonnées complètes d'une entité cataloguée.

        Args:
            entity_id: ID entité catalogue
            tenant_id: Tenant ID

        Returns:
            Dict avec metadata ou None si non trouvé
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (ont:OntologyEntity {
                    entity_id: $entity_id,
                    tenant_id: $tenant_id
                })
                RETURN ont
            """, {"entity_id": entity_id, "tenant_id": tenant_id})

            record = result.single()

            if record:
                ont = record["ont"]
                return dict(ont)

            return None

    def log_uncataloged_entity(
        self,
        raw_name: str,
        entity_type: str,
        tenant_id: str = "default"
    ):
        """
        Log entité non cataloguée pour review admin.

        OPTIONNEL : Peut créer node temporaire ou juste logger.

        Args:
            raw_name: Nom brut
            entity_type: Type suggéré
            tenant_id: Tenant ID
        """
        # Simple log pour maintenant
        logger.info(
            f"📝 Entité non cataloguée loggée: '{raw_name}' "
            f"(type={entity_type}, tenant={tenant_id})"
        )

        # OPTIONNEL : Créer node :UncatalogedEntity pour tracking
        # with self.driver.session() as session:
        #     session.run("""
        #         CREATE (u:UncatalogedEntity {
        #             raw_name: $raw_name,
        #             entity_type: $entity_type,
        #             tenant_id: $tenant_id,
        #             logged_at: datetime()
        #         })
        #     """, {
        #         "raw_name": raw_name,
        #         "entity_type": entity_type,
        #         "tenant_id": tenant_id
        #     })

    def close(self):
        """Ferme connexion Neo4j."""
        if self.driver:
            self.driver.close()


# Instance singleton (comme YAML actuel)
_normalizer_instance: Optional[EntityNormalizerNeo4j] = None


def get_entity_normalizer_neo4j(
    driver: GraphDatabase.driver = None
) -> EntityNormalizerNeo4j:
    """
    Retourne instance singleton du normalizer Neo4j.

    Args:
        driver: Neo4j driver (optionnel si déjà initialisé)

    Returns:
        EntityNormalizerNeo4j instance
    """
    global _normalizer_instance

    if _normalizer_instance is None:
        if driver is None:
            from knowbase.config.settings import get_settings
            settings = get_settings()

            driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )

        _normalizer_instance = EntityNormalizerNeo4j(driver)

    return _normalizer_instance


__all__ = ["EntityNormalizerNeo4j", "get_entity_normalizer_neo4j"]
```

### **Étape 3.2 : Tests Unitaires**

**Fichier** : `tests/ontology/test_entity_normalizer_neo4j.py`

```python
"""
Tests EntityNormalizerNeo4j.
"""
import pytest
from neo4j import GraphDatabase
from knowbase.ontology.entity_normalizer_neo4j import EntityNormalizerNeo4j


@pytest.fixture
def neo4j_driver():
    """Fixture Neo4j driver pour tests."""
    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", "password")
    )
    yield driver
    driver.close()


@pytest.fixture
def normalizer(neo4j_driver):
    """Fixture normalizer."""
    return EntityNormalizerNeo4j(neo4j_driver)


def test_normalize_exact_match(normalizer):
    """Test normalisation match exact."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "SAP S/4HANA Cloud",
        entity_type_hint="SOLUTION"
    )

    assert is_cataloged is True
    assert canonical == "SAP S/4HANA Cloud"
    assert entity_type == "SOLUTION"


def test_normalize_alias(normalizer):
    """Test normalisation via alias."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "S/4HANA",
        entity_type_hint="SOLUTION"
    )

    assert is_cataloged is True
    assert canonical == "SAP S/4HANA Cloud"  # Normalisé
    assert entity_id == "S4HANA_CLOUD"


def test_normalize_case_insensitive(normalizer):
    """Test normalisation case insensitive."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "s/4hana",  # Lowercase
        entity_type_hint="SOLUTION"
    )

    assert is_cataloged is True
    assert canonical == "SAP S/4HANA Cloud"


def test_normalize_wrong_type_correction(normalizer):
    """Test correction type si LLM se trompe."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "S/4HANA",
        entity_type_hint="SOFTWARE"  # Mauvais type
    )

    # Devrait trouver quand même et corriger le type
    assert is_cataloged is True
    assert canonical == "SAP S/4HANA Cloud"
    assert entity_type == "SOLUTION"  # Type corrigé


def test_normalize_not_found(normalizer):
    """Test entité non cataloguée."""
    entity_id, canonical, entity_type, is_cataloged = normalizer.normalize_entity_name(
        "Unknown Product XYZ",
        entity_type_hint="PRODUCT"
    )

    assert is_cataloged is False
    assert canonical == "Unknown Product XYZ"  # Retourné brut
    assert entity_type == "PRODUCT"
    assert entity_id is None


def test_get_entity_metadata(normalizer):
    """Test récupération metadata."""
    metadata = normalizer.get_entity_metadata("S4HANA_CLOUD")

    assert metadata is not None
    assert metadata["canonical_name"] == "SAP S/4HANA Cloud"
    assert metadata["category"] == "ERP"
    assert metadata["vendor"] == "SAP"
```

---

## 🔌 Phase 4 : Intégration Pipeline (Jour 8-9)

### **Étape 4.1 : Modifier KnowledgeGraphService**

**Fichier** : `src/knowbase/api/services/knowledge_graph_service.py`

```python
# Ligne 24 - REMPLACER import
# AVANT:
# from knowbase.common.entity_normalizer import get_entity_normalizer

# APRÈS:
from knowbase.ontology.entity_normalizer_neo4j import get_entity_normalizer_neo4j

# Ligne 46 - REMPLACER dans __init__
# AVANT:
# self.normalizer = get_entity_normalizer()

# APRÈS:
self.normalizer = get_entity_normalizer_neo4j(self.driver)

# Ligne 176-179 - MODIFIER appel normalize
# AVANT:
# entity_id, canonical_name, is_cataloged = self.normalizer.normalize_entity_name(
#     entity.name,
#     entity.entity_type
# )

# APRÈS:
entity_id, canonical_name, entity_type_corrected, is_cataloged = self.normalizer.normalize_entity_name(
    entity.name,
    entity_type_hint=entity.entity_type,
    tenant_id=entity.tenant_id
)

# Si type corrigé par ontologie, utiliser le type corrigé
if entity_type_corrected and entity_type_corrected != entity.entity_type:
    logger.info(
        f"🔄 Type corrigé par ontologie: {entity.entity_type} → {entity_type_corrected}"
    )
    entity.entity_type = entity_type_corrected
```

### **Étape 4.2 : Tests Intégration**

**Fichier** : `tests/integration/test_pipeline_neo4j_ontology.py`

```python
"""
Tests intégration pipeline avec Neo4j ontology.
"""
import pytest
from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
from knowbase.api.schemas.knowledge_graph import EntityCreate


@pytest.fixture
def kg_service():
    return KnowledgeGraphService(tenant_id="test")


def test_entity_normalized_on_creation(kg_service):
    """Test que entité est normalisée lors création."""

    entity_data = EntityCreate(
        name="S/4HANA",  # Alias
        entity_type="SOLUTION",
        description="Test",
        confidence=0.9,
        tenant_id="test"
    )

    # Créer entité
    entity = kg_service.get_or_create_entity(entity_data)

    # Vérifier normalisation
    assert entity.name == "SAP S/4HANA Cloud"  # Normalisé
    assert entity.status == "validated"  # Catalogué
    assert entity.is_cataloged is True


def test_entity_type_correction(kg_service):
    """Test correction type si LLM se trompe."""

    entity_data = EntityCreate(
        name="S/4HANA",
        entity_type="SOFTWARE",  # Mauvais type
        description="Test",
        confidence=0.9,
        tenant_id="test"
    )

    entity = kg_service.get_or_create_entity(entity_data)

    # Type corrigé par ontologie
    assert entity.entity_type == "SOLUTION"
    assert entity.name == "SAP S/4HANA Cloud"
```

---

## 💾 Phase 5 : Auto-Save Ontologies (Jour 10)

### **Étape 5.1 : Modifier Normalization Worker**

**Fichier** : `src/knowbase/api/workers/normalization_worker.py`

```python
# Ajouter après ligne 69 (après merge success)

def normalize_entities_task(...):
    # ... existing code jusqu'à ligne 69 ...

    # ✨ NOUVEAU : Sauvegarder ontologie dans Neo4j
    try:
        from knowbase.ontology.ontology_saver import save_ontology_to_neo4j

        save_ontology_to_neo4j(
            merge_groups=merge_groups,
            entity_type=type_name,
            tenant_id=tenant_id,
            source="llm_generated"
        )

        logger.info(f"✅ Ontologie sauvegardée dans Neo4j: {type_name}")

    except Exception as e:
        logger.error(f"⚠️ Erreur sauvegarde ontologie Neo4j: {e}")
        # Non-bloquant, continuer
```

### **Étape 5.2 : Service Sauvegarde Ontologie**

**Fichier** : `src/knowbase/ontology/ontology_saver.py`

```python
"""
Sauvegarde ontologies générées par LLM dans Neo4j.
"""
from typing import List, Dict
from datetime import datetime, timezone
from neo4j import GraphDatabase
import uuid
import logging

logger = logging.getLogger(__name__)


def save_ontology_to_neo4j(
    merge_groups: List[Dict],
    entity_type: str,
    tenant_id: str = "default",
    source: str = "llm_generated",
    neo4j_uri: str = None,
    neo4j_user: str = None,
    neo4j_password: str = None
):
    """
    Sauvegarde ontologie générée dans Neo4j.

    Args:
        merge_groups: Groupes validés par user
        entity_type: Type d'entité
        tenant_id: Tenant ID
        source: Source ontologie ("llm_generated" | "manual")
        neo4j_uri: URI Neo4j (optionnel)
        neo4j_user: User (optionnel)
        neo4j_password: Password (optionnel)
    """
    if not neo4j_uri:
        from knowbase.config.settings import get_settings
        settings = get_settings()
        neo4j_uri = settings.neo4j_uri
        neo4j_user = settings.neo4j_user
        neo4j_password = settings.neo4j_password

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        with driver.session() as session:
            for group in merge_groups:
                entity_id = group["canonical_key"]
                canonical_name = group["canonical_name"]
                confidence = group.get("confidence", 0.95)

                # Créer/update OntologyEntity
                session.run("""
                    MERGE (ont:OntologyEntity {entity_id: $entity_id})
                    SET ont.canonical_name = $canonical_name,
                        ont.entity_type = $entity_type,
                        ont.source = $source,
                        ont.confidence = $confidence,
                        ont.tenant_id = $tenant_id,
                        ont.created_at = coalesce(ont.created_at, datetime()),
                        ont.updated_at = datetime(),
                        ont.version = coalesce(ont.version, '1.0.0')
                """, {
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "entity_type": entity_type,
                    "source": source,
                    "confidence": confidence,
                    "tenant_id": tenant_id
                })

                # Créer aliases depuis entités mergées
                for entity in group["entities"]:
                    alias_name = entity["name"]

                    # Skip si alias == canonical (éviter doublon)
                    if alias_name.lower() == canonical_name.lower():
                        continue

                    alias_id = str(uuid.uuid4())
                    normalized = alias_name.lower().strip()

                    session.run("""
                        MATCH (ont:OntologyEntity {entity_id: $entity_id})
                        MERGE (alias:OntologyAlias {
                            normalized: $normalized,
                            entity_type: $entity_type,
                            tenant_id: $tenant_id
                        })
                        ON CREATE SET
                            alias.alias_id = $alias_id,
                            alias.alias = $alias
                        MERGE (ont)-[:HAS_ALIAS]->(alias)
                    """, {
                        "entity_id": entity_id,
                        "alias_id": alias_id,
                        "alias": alias_name,
                        "normalized": normalized,
                        "entity_type": entity_type,
                        "tenant_id": tenant_id
                    })

        logger.info(
            f"✅ Ontologie sauvegardée: {entity_type}, "
            f"{len(merge_groups)} groupes, {sum(len(g['entities']) for g in merge_groups)} aliases"
        )

    finally:
        driver.close()


__all__ = ["save_ontology_to_neo4j"]
```

---

## ✅ Phase 6 : Tests & Validation (Jour 11-12)

### **Étape 6.1 : Suite Tests Complète**

```bash
# 1. Tests unitaires normalizer
pytest tests/ontology/test_entity_normalizer_neo4j.py -v

# 2. Tests intégration pipeline
pytest tests/integration/test_pipeline_neo4j_ontology.py -v

# 3. Tests end-to-end
pytest tests/integration/test_ingestion_with_ontology.py -v

# 4. Coverage
pytest tests/ontology/ --cov=src/knowbase/ontology --cov-report=html
```

### **Étape 6.2 : Validation Manuelle**

**Checklist Validation** :

```bash
# 1. Vérifier ontologies chargées
docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (ont:OntologyEntity) RETURN ont.entity_type, count(*) ORDER BY ont.entity_type"

# 2. Tester normalisation
docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (alias:OntologyAlias {normalized: 's/4hana'})-[:BELONGS_TO]->(ont)
   RETURN ont.entity_id, ont.canonical_name, ont.entity_type"

# 3. Importer document test
curl -X POST http://localhost:8000/ingest/pptx \
  -F "file=@test_documents/test_sap.pptx"

# 4. Vérifier entités normalisées
docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (e:Entity {is_cataloged: true})
   RETURN e.name, e.catalog_id, e.entity_type LIMIT 10"

# 5. Générer + sauvegarder ontologie
curl -X POST http://localhost:8000/entity-types/INFRASTRUCTURE/generate-ontology
# Attendre job terminé
curl -X POST http://localhost:8000/entity-types/INFRASTRUCTURE/normalize-entities \
  -H "Content-Type: application/json" \
  -d '{"merge_groups": [...]}'

# 6. Vérifier ontologie sauvegardée
docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (ont:OntologyEntity {entity_type: 'INFRASTRUCTURE', source: 'llm_generated'})
   RETURN count(*)"
```

---

## 🚀 Phase 7 : Déploiement (Jour 13)

### **Étape 7.1 : Feature Flag (Rollout Progressif)**

**Fichier** : `.env`

```bash
# Feature flag migration Neo4j ontology
USE_NEO4J_ONTOLOGY=true  # false pour rollback vers YAML
```

**Fichier** : `src/knowbase/api/services/knowledge_graph_service.py`

```python
# __init__ avec feature flag

def __init__(self, tenant_id: str = "default"):
    # ...

    # Feature flag: Neo4j ou YAML
    use_neo4j = os.getenv("USE_NEO4J_ONTOLOGY", "true").lower() == "true"

    if use_neo4j:
        from knowbase.ontology.entity_normalizer_neo4j import get_entity_normalizer_neo4j
        self.normalizer = get_entity_normalizer_neo4j(self.driver)
        logger.info("✅ Utilisation Neo4j Ontology")
    else:
        from knowbase.common.entity_normalizer import get_entity_normalizer
        self.normalizer = get_entity_normalizer()
        logger.info("⚠️ Fallback YAML Ontology (legacy)")
```

### **Étape 7.2 : Monitoring & Alertes**

**Métriques à surveiller** :

```python
# src/knowbase/common/metrics.py (ajouter)

from prometheus_client import Counter, Histogram

# Métriques normalisation
ontology_lookup_total = Counter(
    'ontology_lookup_total',
    'Total lookups ontologie',
    ['source', 'result']  # source=neo4j/yaml, result=found/not_found
)

ontology_lookup_duration = Histogram(
    'ontology_lookup_duration_seconds',
    'Durée lookup ontologie',
    ['source']
)

# Dans EntityNormalizerNeo4j.normalize_entity_name()
start = time.perf_counter()
# ... lookup ...
duration = time.perf_counter() - start

ontology_lookup_duration.labels(source='neo4j').observe(duration)
ontology_lookup_total.labels(
    source='neo4j',
    result='found' if is_cataloged else 'not_found'
).inc()
```

**Dashboard Grafana** :

```yaml
# grafana/dashboards/ontology.json
{
  "panels": [
    {
      "title": "Ontology Lookups (Neo4j vs YAML)",
      "targets": [{
        "expr": "rate(ontology_lookup_total[5m])"
      }]
    },
    {
      "title": "Lookup Duration P95",
      "targets": [{
        "expr": "histogram_quantile(0.95, ontology_lookup_duration_seconds)"
      }]
    },
    {
      "title": "Cataloged vs Uncataloged Ratio",
      "targets": [{
        "expr": "ontology_lookup_total{result='found'} / ontology_lookup_total"
      }]
    }
  ]
}
```

### **Étape 7.3 : Rollout Plan**

```bash
# Jour 13 Matin : Déploiement staging
git checkout feat/neo4j-ontology
docker compose -f docker-compose.staging.yml up -d

# Test smoke staging
pytest tests/smoke/ -v

# Jour 13 Après-midi : Production (canary 10%)
# 1 worker sur 10 avec Neo4j
docker compose scale worker=10
# Worker 1 avec USE_NEO4J_ONTOLOGY=true

# Monitoring 2h
# Si OK → 50% workers
# Si OK → 100% workers

# Jour 14 : Monitoring continu
# Vérifier métriques Grafana
# Vérifier logs erreurs
```

---

## 📚 Annexes

### **Annexe A : Commandes Utiles**

```bash
# Cypher utiles

# 1. Stats ontologies
MATCH (ont:OntologyEntity)
RETURN ont.entity_type AS type,
       ont.source AS source,
       count(*) AS count
ORDER BY type, source

# 2. Top 10 entités avec plus d'aliases
MATCH (ont:OntologyEntity)-[:HAS_ALIAS]->(alias)
WITH ont, count(alias) AS alias_count
RETURN ont.canonical_name, ont.entity_type, alias_count
ORDER BY alias_count DESC
LIMIT 10

# 3. Entités orphelines (sans alias)
MATCH (ont:OntologyEntity)
WHERE NOT (ont)-[:HAS_ALIAS]->()
RETURN ont.entity_id, ont.canonical_name

# 4. Chercher entité par alias
MATCH (alias:OntologyAlias)
WHERE alias.normalized CONTAINS 's/4hana'
MATCH (alias)-[:BELONGS_TO]->(ont)
RETURN alias.alias, ont.canonical_name, ont.entity_type

# 5. Entités par type et source
MATCH (ont:OntologyEntity {entity_type: 'SOLUTION'})
RETURN ont.source, count(*) AS count
```

### **Annexe B : Troubleshooting**

**Problème** : Lookup lent (>10ms)

```cypher
-- Vérifier index
SHOW INDEXES

-- Si index manquant, recréer
CREATE INDEX ont_alias_normalized_idx IF NOT EXISTS
FOR (alias:OntologyAlias) ON (alias.normalized)

-- Forcer rebuild index
CALL db.index.fulltext.awaitEventuallyConsistentIndexRefresh()
```

**Problème** : Doublons aliases

```cypher
-- Trouver doublons
MATCH (alias:OntologyAlias)
WITH alias.normalized AS normalized,
     alias.entity_type AS entity_type,
     collect(alias) AS aliases
WHERE size(aliases) > 1
RETURN normalized, entity_type, size(aliases) AS count

-- Supprimer doublons (garder premier)
MATCH (alias:OntologyAlias)
WITH alias.normalized AS normalized,
     alias.entity_type AS entity_type,
     collect(alias) AS aliases
WHERE size(aliases) > 1
FOREACH (a IN tail(aliases) | DETACH DELETE a)
```

**Problème** : Migration incomplète

```bash
# Rollback migration
docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (ont:OntologyEntity {source: 'yaml_migrated'}) DETACH DELETE ont"

docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (alias:OntologyAlias) WHERE NOT ()-[:HAS_ALIAS]->(alias) DELETE alias"

# Re-run migration
python src/knowbase/ontology/migrate_yaml_to_neo4j.py
```

### **Annexe C : Rollback Plan**

```bash
# En cas de problème critique

# 1. Feature flag → YAML
echo "USE_NEO4J_ONTOLOGY=false" >> .env
docker compose restart app worker

# 2. Restore Neo4j backup
docker compose exec neo4j neo4j-admin database restore neo4j \
  --from-path=/backups/neo4j_pre_ontology_20250110.dump

# 3. Vérifier système
pytest tests/smoke/ -v
```

---

## ✅ Checklist Complète

**Phase 1 : Schéma** (Jour 1-2)
- [ ] Contraintes créées (ont_entity_id_unique, etc.)
- [ ] Index créés (ont_alias_normalized_idx, etc.)
- [ ] Validation schéma OK

**Phase 2 : Migration** (Jour 3-4)
- [ ] Script migration testé
- [ ] Données YAML → Neo4j (500+ entités)
- [ ] Validation migration (0 orphelins)

**Phase 3 : Service** (Jour 5-7)
- [ ] EntityNormalizerNeo4j implémenté
- [ ] Tests unitaires passent
- [ ] Feature flag ajouté

**Phase 4 : Intégration** (Jour 8-9)
- [ ] KnowledgeGraphService modifié
- [ ] Tests intégration passent
- [ ] Pipeline complet fonctionne

**Phase 5 : Auto-Save** (Jour 10)
- [ ] Ontology saver implémenté
- [ ] Worker modifié
- [ ] Test sauvegarde après normalisation

**Phase 6 : Tests** (Jour 11-12)
- [ ] Suite tests complète (coverage >80%)
- [ ] Tests E2E passent
- [ ] Validation manuelle OK

**Phase 7 : Déploiement** (Jour 13)
- [ ] Feature flag configuré
- [ ] Monitoring Grafana setup
- [ ] Rollout progressif (10% → 50% → 100%)
- [ ] Production stable

---

## 🎉 Conclusion

**Ce guide fournit** :
- ✅ Architecture complète Neo4j ontologies
- ✅ Scripts migration clés en main
- ✅ Services normalisation production-ready
- ✅ Tests validation exhaustifs
- ✅ Plan déploiement sécurisé

**Prochaines étapes** :
1. Lire ce guide attentivement
2. Valider chaque phase avant passage suivante
3. Me demander d'implémenter phase par phase
4. Valider ensemble à chaque étape

**Temps estimé total** : 12-15 jours
**Complexité** : Moyenne
**Risque** : Faible (rollback possible)

---

*Guide créé par Claude Code - Expert Architecture SAP KB*
*Dernière mise à jour : 10 janvier 2025*
