# Analyse : Gestion Dynamique des Types d'Entités - Vision vs Implémentation Actuelle

**Date** : 2025-10-06
**Objectif** : Comparer la vision fonctionnelle cible avec l'implémentation actuelle et identifier les écarts

---

## 🎯 Vision Fonctionnelle Cible

### 1. Gestion des Entity Types

#### État Initial (Bootstrap)
- ✅ Le système **peut** posséder des types d'entités de base (non obligatoire)
- ✅ Types stockés dans enum `EntityType` pour bootstrap uniquement
- ✅ Types actuels : SOLUTION, COMPONENT, ORGANIZATION, PERSON, TECHNOLOGY, CONCEPT

#### Découverte Dynamique de Nouveaux Types
Lors de l'import d'un document :

1. **LLM identifie une entité avec un type** (ex: `entity_type: "INFRASTRUCTURE"`)

2. **Système vérifie si le type existe déjà** :
   - ✅ **Si type existe** → rattacher l'entité à ce type
   - ❌ **Si type n'existe PAS** → **créer automatiquement le nouveau type** et y rattacher l'entité

3. **Stockage des types dynamiques** :
   - ❓ À définir : YAML, BDD (Neo4j/PostgreSQL), JSON ?
   - Chaque type doit avoir : `name`, `status` (pending/approved), `created_at`, `entity_count`

#### Workflow de Validation (Frontend Admin)

**Page : Types d'Entités**
- Afficher tous les types (validés + pending)
- Pour chaque type en attente :

  **Option 1 : Accepter**
  - Type devient "official/approved"
  - Entités associées passent de "pending" → "validated"

  **Option 2 : Fusionner (Redondant)**
  - Sélectionner un type existant cible
  - Transférer toutes les entités vers le type cible
  - Supprimer le type en doublon

  **Option 3 : Rejeter**
  - Supprimer le type
  - **Cascade delete** : supprimer toutes les entités et relations associées

---

### 2. Gestion des Entités (avec Normalisation)

#### Pipeline d'Insertion

1. **LLM extrait entité** : `{name: "S/4HANA PCE", entity_type: "SOLUTION"}`

2. **Normalisation du nom** (via `entity_normalizer.py`) :
   - Recherche dans dictionnaire d'ontologie du type (`config/ontologies/solutions.yaml`)
   - Si alias trouvé → utiliser `canonical_name` (`"SAP S/4HANA Cloud, Private Edition"`)
   - Si non trouvé → utiliser nom brut LLM + **marquer entité comme `status: "pending"`**

3. **Vérification unicité dans Neo4j** :
   - Critère : `(canonical_name, entity_type, tenant_id)`
   - Si existe déjà → **réutiliser l'entité existante** (pas de duplication)
   - Si n'existe pas → créer nouvelle entité

4. **Mise à jour des relations** :
   - Les relations utilisent toujours les noms canoniques
   - Si entité réutilisée, relations sont créées normalement

#### Workflow de Validation (Frontend Admin)

**Page : Entités en Attente de Validation**

**Filtres** :
- Par type d'entité (SOLUTION, INFRASTRUCTURE, etc.)
- Status : pending uniquement (exclure entités normalisées automatiquement)

**Pour chaque entité pending** :

**Option 1 : Valider**
- Passer `status: "pending"` → `"validated"`
- Ajouter à l'ontologie YAML correspondante

**Option 2 : Fusionner**
- Sélectionner une entité existante cible
- Transférer toutes les relations vers entité cible
- Supprimer entité en doublon

**Option 3 : Rejeter**
- Supprimer l'entité
- **Cascade delete** : supprimer relations associées

---

## 🔍 Implémentation Actuelle

### ✅ Ce qui fonctionne déjà

#### 1. Types Dynamiques (depuis dernière session)
```python
# src/knowbase/api/schemas/knowledge_graph.py:25
entity_type: str  # Accepte n'importe quel type (pas d'enum strict)
```
✅ Le LLM peut renvoyer `INFRASTRUCTURE`, `NETWORK`, etc. → accepté

#### 2. Normalisation des Noms
```python
# src/knowbase/common/entity_normalizer.py:38-81
def normalize_entity_name(raw_name: str, entity_type: EntityType) -> Tuple[Optional[str], str]:
    # Retourne (entity_id, canonical_name)
    # Si pas dans dictionnaire → (None, raw_name.strip())
```
✅ Fonctionne avec dictionnaires YAML d'ontologie
✅ Log des entités non cataloguées dans `uncataloged_entities.log`

#### 3. Get or Create (Éviter Doublons)
```python
# src/knowbase/api/services/knowledge_graph_service.py:141-300
def get_or_create_entity(entity: EntityCreate) -> EntityResponse:
    # MATCH sur (name, entity_type, tenant_id)
    # Si existe → retourne entité existante
    # Sinon → CREATE nouvelle entité
```
✅ Réutilise entités existantes correctement

#### 4. Relations sur Entités Réutilisées
```python
# src/knowbase/api/services/knowledge_graph_service.py:304-384
def create_relation(relation: RelationCreate) -> RelationResponse:
    # MATCH sur (source_name, target_name, tenant_id)
    # CREATE relation entre entités (existantes ou nouvelles)
```
✅ Relations créées même si entités pré-existantes

---

### ❌ Écarts et Manques Critiques

#### 1. **Gestion des Entity Types Dynamiques**

**Problème** :
- ✅ Types dynamiques acceptés (string au lieu d'enum)
- ❌ **Aucun stockage structuré des types découverts**
- ❌ **Pas de statut `pending/approved` sur les types**
- ❌ **Impossible de lister les types existants**

**Impact** :
- Impossible de savoir quels types ont été découverts
- Impossible de valider/rejeter un type
- Impossible de fusionner types redondants

**Solution requise** :
```python
# Nouvelle table/collection : entity_types_registry
{
    "type_name": "INFRASTRUCTURE",
    "status": "pending",  # pending | approved | rejected
    "first_seen": "2025-10-06T10:30:00Z",
    "entity_count": 40,
    "created_by": "llm",  # llm | admin
    "approved_by": null,
    "approved_at": null
}
```

**Stockage possible** :
- **Option A** : Table PostgreSQL `entity_types`
- **Option B** : Nodes Neo4j `:EntityType`
- **Option C** : Fichier YAML dynamique `config/ontologies/discovered_types.yaml`

---

#### 2. **Statut `pending` sur Entités**

**Problème** :
- ✅ Normalisation identifie entités non cataloguées
- ✅ Log dans `uncataloged_entities.log`
- ❌ **Aucun champ `status` dans EntityCreate/EntityResponse**
- ❌ **Impossible de distinguer dans Neo4j** :
  - Entités normalisées automatiquement (ex: "S/4HANA PCE" → canonical)
  - Entités non cataloguées en attente validation (ex: "Azure VNET" nouveau)

**Impact** :
- Frontend ne peut pas afficher uniquement les entités "pending"
- Impossible de filtrer/valider les entités non cataloguées

**Solution requise** :
```python
# src/knowbase/api/schemas/knowledge_graph.py
class EntityCreate(BaseModel):
    # ... champs existants ...
    status: str = Field(
        default="pending",  # pending | validated | rejected
        description="Statut validation entité"
    )
    is_cataloged: bool = Field(
        default=False,
        description="True si trouvé dans ontologie YAML"
    )
```

**Modification service** :
```python
# src/knowbase/api/services/knowledge_graph_service.py:141-195
def get_or_create_entity(entity: EntityCreate) -> EntityResponse:
    # Normaliser
    entity_id, canonical_name = self.normalizer.normalize_entity_name(...)

    if entity_id:
        entity.status = "validated"  # Trouvé dans ontologie
        entity.is_cataloged = True
    else:
        entity.status = "pending"    # Non catalogué
        entity.is_cataloged = False

    # Reste du code...
```

---

#### 3. **API de Gestion des Types (Backend)**

**Manque** : Endpoints FastAPI pour admin frontend

**Requis** :
```python
# src/knowbase/api/routers/entity_types.py (nouveau fichier)

@router.get("/entity-types", response_model=List[EntityTypeResponse])
async def list_entity_types(
    status: Optional[str] = None,  # pending | approved
    tenant_id: str = "default"
):
    """Liste tous les types d'entités (découverts + bootstrap)."""
    pass

@router.post("/entity-types/{type_name}/approve")
async def approve_entity_type(type_name: str, tenant_id: str = "default"):
    """Valide un type découvert → status = approved."""
    pass

@router.post("/entity-types/{type_name}/merge")
async def merge_entity_type(
    type_name: str,
    target_type: str,
    tenant_id: str = "default"
):
    """Fusionne type redondant vers type existant."""
    # 1. Transférer toutes les entités vers target_type
    # 2. Supprimer type_name
    pass

@router.delete("/entity-types/{type_name}")
async def reject_entity_type(type_name: str, tenant_id: str = "default"):
    """Rejette type → cascade delete entités/relations."""
    pass
```

---

#### 4. **API de Gestion des Entités (Backend)**

**Manque** : Endpoints pour entités pending

**Requis** :
```python
# src/knowbase/api/routers/entities.py (nouveau fichier)

@router.get("/entities/pending", response_model=List[EntityResponse])
async def list_pending_entities(
    entity_type: Optional[str] = None,
    tenant_id: str = "default"
):
    """Liste entités en attente de validation (status=pending)."""
    pass

@router.post("/entities/{entity_uuid}/approve")
async def approve_entity(entity_uuid: str):
    """Valide entité → status = validated + ajout ontologie YAML."""
    pass

@router.post("/entities/{entity_uuid}/merge")
async def merge_entity(
    entity_uuid: str,
    target_entity_uuid: str
):
    """Fusionne entité vers entité existante."""
    # 1. Transférer relations vers target
    # 2. Supprimer entité source
    pass

@router.delete("/entities/{entity_uuid}")
async def reject_entity(entity_uuid: str):
    """Rejette entité → cascade delete relations."""
    pass
```

---

#### 5. **Requêtes Neo4j Manquantes**

**Pour types** :
```cypher
// Lister types découverts avec comptage
MATCH (e:Entity)
WHERE e.tenant_id = $tenant_id
RETURN DISTINCT e.entity_type AS type_name,
       COUNT(e) AS entity_count
ORDER BY entity_count DESC;

// Supprimer type + cascade
MATCH (e:Entity {entity_type: $type_name, tenant_id: $tenant_id})
OPTIONAL MATCH (e)-[r:RELATION]-()
DELETE r, e;
```

**Pour entités** :
```cypher
// Lister entités pending
MATCH (e:Entity)
WHERE e.status = 'pending' AND e.tenant_id = $tenant_id
RETURN e;

// Fusionner entités (transférer relations)
MATCH (source:Entity {uuid: $source_uuid})
MATCH (target:Entity {uuid: $target_uuid})
MATCH (source)-[r:RELATION]-(other)
CREATE (target)-[r2:RELATION {r}]-(other)
DELETE r, source;
```

---

#### 6. **Frontend Admin (Pages Manquantes)**

**Page 1 : Gestion Types d'Entités** (`/admin/entity-types`)
- Tableau : type_name | status | entity_count | first_seen | actions
- Filtres : status (pending/approved)
- Actions : Approve | Merge → Type | Delete

**Page 2 : Gestion Entités Pending** (`/admin/entities/pending`)
- Tableau : name | entity_type | source_document | created_at | actions
- Filtres : entity_type
- Actions : Approve | Merge → Entity | Delete

**Page 3 : Dictionnaires Ontologie** (`/admin/ontologies`)
- Édition YAML des dictionnaires
- Ajout manuel aliases
- Preview canonicalisation

---

## 📋 Plan de Migration

### Phase 1 : Stockage Types Dynamiques (Backend)
1. ✅ Accepter types string (FAIT dans session précédente)
2. ❌ Ajouter table/collection `entity_types_registry`
3. ❌ Modifier `get_or_create_entity` pour enregistrer types découverts

### Phase 2 : Statut Entités (Backend)
1. ❌ Ajouter champs `status`, `is_cataloged` à EntityCreate/Response
2. ❌ Modifier Neo4j CREATE queries pour stocker status
3. ❌ Modifier `entity_normalizer` pour définir status selon catalogage

### Phase 3 : API Administration (Backend)
1. ❌ Router `/entity-types` (CRUD types)
2. ❌ Router `/entities/pending` (CRUD entités)
3. ❌ Service Neo4j pour merge/cascade delete

### Phase 4 : Frontend Admin
1. ❌ Page gestion types (`/admin/entity-types`)
2. ❌ Page gestion entités pending (`/admin/entities/pending`)
3. ❌ Page édition ontologies (`/admin/ontologies`)

---

## 🚨 Impacts sur Fonctionnement Actuel

### Ce qui fonctionne correctement
✅ Normalisation noms via ontologies YAML
✅ Get or create évite doublons
✅ Relations créées sur entités réutilisées
✅ Types dynamiques acceptés (INFRASTRUCTURE, etc.)

### Ce qui NE fonctionne PAS comme attendu
❌ **Entités normalisées stockées sans distinction** :
   - "S/4HANA PCE" → "SAP S/4HANA Cloud, Private Edition" (OK)
   - "Azure VNET" → "Azure VNET" (pas de statut pending)

❌ **Types découverts non trackés** :
   - INFRASTRUCTURE créé mais pas enregistré comme nouveau type

❌ **Impossible de valider/rejeter** :
   - Pas d'interface admin
   - Pas de requêtes Neo4j adaptées

---

## ✅ Recommandations

### Approche 1 : Migration Complète (Recommandée)
- Implémenter Phases 1-4 complètes
- Durée estimée : 3-4 jours
- Bénéfice : Système conforme à vision complète

### Approche 2 : Incrémentale (Pragmatique)
1. **Court terme** (1j) :
   - Ajouter champ `status` entités
   - Modifier normalizer pour définir status
   - API simple pour lister pending

2. **Moyen terme** (2j) :
   - Stockage types découverts
   - API gestion types

3. **Long terme** (2j) :
   - Frontend admin complet
   - Workflow validation/merge

### Approche 3 : Report
- Continuer avec système actuel
- Log dans `uncataloged_entities.log`
- Migration admin plus tard

---

## 📊 Résumé Écarts

| Fonctionnalité | Vision | Actuel | Écart |
|---------------|--------|--------|-------|
| Types dynamiques acceptés | ✅ | ✅ | ✅ OK |
| Stockage types découverts | ✅ | ❌ | 🔴 Manquant |
| Statut pending entités | ✅ | ❌ | 🔴 Manquant |
| Normalisation noms | ✅ | ✅ | ✅ OK |
| Get or create | ✅ | ✅ | ✅ OK |
| Relations sur réutilisées | ✅ | ✅ | ✅ OK |
| API admin types | ✅ | ❌ | 🔴 Manquant |
| API admin entités | ✅ | ❌ | 🔴 Manquant |
| Frontend admin | ✅ | ❌ | 🔴 Manquant |
| Merge/cascade delete | ✅ | ❌ | 🔴 Manquant |

**Score conformité : 4/10** ✅
**Éléments critiques manquants : 6/10** 🔴

---

**Prochaine étape recommandée** : Valider l'approche de stockage des types (PostgreSQL vs Neo4j vs YAML) avant d'implémenter Phase 1.
