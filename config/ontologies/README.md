# 📚 Catalogues d'Ontologies Knowledge Graph

Ce répertoire contient les catalogues de normalisation des entités du Knowledge Graph.

## 🎯 Objectif

Normaliser les noms d'entités extraites par LLM pour éviter les doublons :
- **"Load Balancer"** vs **"LoadBalancer"** vs **"LB"** → une seule entité canonique
- **"SAP Cloud ERP"** vs **"S/4HANA Cloud"** → `SAP S/4HANA Cloud, Public Edition`

## 📁 Structure des Catalogues

Chaque type d'entité dispose de son propre fichier YAML :

```
config/ontologies/
├── solutions.yaml       # EntityType.SOLUTION
├── components.yaml      # EntityType.COMPONENT
├── technologies.yaml    # EntityType.TECHNOLOGY
├── organizations.yaml   # EntityType.ORGANIZATION
├── persons.yaml         # EntityType.PERSON
├── concepts.yaml        # EntityType.CONCEPT
└── uncataloged_entities.log  # Entités non cataloguées (généré auto)
```

## 🧩 Format YAML

```yaml
ENTITY_TYPE_PLURAL:  # ex: SOLUTIONS, COMPONENTS, TECHNOLOGIES
  ENTITY_ID:         # Identifiant unique stable
    canonical_name: "Nom Canonique Officiel"
    aliases:
      - "Alias 1"
      - "Alias 2"
      - "alias-3"
    category: "Catégorie"  # Optionnel
    vendor: "Éditeur"      # Optionnel
```

### Exemple - solutions.yaml

```yaml
SOLUTIONS:
  S4HANA_PUBLIC:
    canonical_name: "SAP S/4HANA Cloud, Public Edition"
    aliases:
      - "SAP Cloud ERP"
      - "S/4HANA Cloud"
      - "S4 Public"
    category: "ERP"
    vendor: "SAP"

  KUBERNETES:
    canonical_name: "Kubernetes"
    aliases:
      - "K8s"
      - "k8s"
      - "Kube"
    category: "Container Orchestration"
    vendor: "CNCF"
```

## 🔧 Utilisation

### Dans le Code

```python
from knowbase.common.entity_normalizer import get_entity_normalizer
from knowbase.common.entity_types import EntityType

normalizer = get_entity_normalizer()

# Normaliser un nom d'entité
entity_id, canonical_name = normalizer.normalize_entity_name(
    "SAP Cloud ERP",
    EntityType.SOLUTION
)

# Résultat:
# entity_id = "S4HANA_PUBLIC"
# canonical_name = "SAP S/4HANA Cloud, Public Edition"
```

### Dans le Pipeline d'Ingestion

Le normalizer est appelé automatiquement lors de l'insertion d'entités dans Neo4j :

```python
# KnowledgeGraphService.get_or_create_entity()
# - Normalise le nom avant recherche/création
# - Enrichit les attributs avec catalog_id, category, vendor
# - Log les entités non cataloguées pour review admin
```

## 📊 Enrichissement Progressif

### 1. Analyser les Entités Non Cataloguées

```bash
cat config/ontologies/uncataloged_entities.log
```

Exemple de sortie :
```
2025-10-05 14:23:11 | COMPONENT | "Custom Load Balancer v2" | tenant=acme_corp
2025-10-05 14:24:33 | TECHNOLOGY | "React 18" | tenant=acme_corp
```

### 2. Ajouter les Entités Pertinentes

Si une entité apparaît fréquemment, l'ajouter au catalogue :

```yaml
# components.yaml
COMPONENTS:
  CUSTOM_LOAD_BALANCER:
    canonical_name: "Custom Load Balancer"
    aliases:
      - "Custom Load Balancer v2"
      - "CLB"
      - "custom-lb"
    category: "Infrastructure"
```

### 3. Redémarrer les Services

Les catalogues sont chargés en lazy loading (premier accès), donc :
- **Nouveau catalogue** : redémarrage nécessaire
- **Ajout entité à catalogue existant** : rechargement auto au prochain accès type

## 🚀 Performance

### Stratégie d'Optimisation

- **Lazy Loading** : Un catalogue n'est chargé que si une entité de ce type est rencontrée
- **Index Inverse O(1)** : Recherche alias → entity_id en temps constant (dict lookup)
- **Cache Mémoire** : Catalogues gardés en mémoire après premier chargement

### Temps Estimés

- Chargement 1 catalogue YAML (500 entités) : **~10-20ms**
- Recherche dans index : **<1ms**
- Normalisation complète : **<2ms**

### Seuil Migration Base de Données

Si un catalogue dépasse **5000 entités**, migrer vers PostgreSQL :

```sql
CREATE TABLE entity_catalog (
    entity_id VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    canonical_name VARCHAR(200) NOT NULL,
    alias VARCHAR(200) NOT NULL,
    metadata JSONB,
    UNIQUE(entity_type, alias)
);
CREATE INDEX idx_alias_lookup ON entity_catalog(entity_type, alias);
```

## 🎨 Bonnes Pratiques

### Nommage Entity ID

- **SNAKE_CASE_MAJUSCULES** : `LOAD_BALANCER`, `S4HANA_PUBLIC`
- Éviter caractères spéciaux sauf `_`
- Être descriptif mais concis

### Nommage Canonical Name

- **Forme officielle** : "SAP S/4HANA Cloud, Public Edition"
- **Lisible humain** : "Load Balancer" (pas "LoadBalancer")
- **Cohérent** : Même convention dans tout le catalogue

### Aliases

- Inclure **toutes les variantes** rencontrées :
  - Casse différente : "K8s", "k8s"
  - Abréviations : "LB", "Load Balancer"
  - Avec/sans tirets : "load-balancer", "load balancer"
- **Lowercase matching** : Recherche insensible à la casse automatique

### Catégories

Exemples par type :

**SOLUTION** :
- ERP, CRM, HR, Finance, Analytics, Procurement, Compliance, Architecture

**COMPONENT** :
- Infrastructure, Integration, Data, Security, Monitoring

**TECHNOLOGY** :
- Programming Language, Framework, Database, Container, Cloud

**ORGANIZATION** :
- Software Vendor, Cloud Provider, Technology Company, Consulting

**CONCEPT** :
- Architecture Pattern, Methodology, Design Pattern, Business Concept

## 🔄 Workflow Complet

1. **Ingestion Document** → LLM extrait entités brutes
2. **Normalisation** → EntityNormalizer cherche dans catalogues
3. **Catalogué** → Nom normalisé + metadata enrichies
4. **Non catalogué** → Log dans `uncataloged_entities.log`
5. **Review Admin** → Analyse logs, enrichit catalogues
6. **Prochaine Ingestion** → Nouvelles entités normalisées automatiquement

## 📈 Évolution Future

### Phase 2 - UI Admin (optionnel)

- Interface React Admin pour gérer catalogues
- CRUD entités/aliases via UI
- Statistiques d'usage par entité
- Détection doublons potentiels

### Phase 3 - Apprentissage Automatique

- Suggestions automatiques d'aliases basées sur fréquence
- Détection variations courantes (pluriel, casse, etc.)
- Clustering entités similaires pour fusion manuelle

---

**Dernière mise à jour** : 2025-10-05
**Auteur** : Migration SAP-specific → Agnostic System
