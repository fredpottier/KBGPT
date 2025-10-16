# Checklist Protection Endpoints - Phase 0

**Date création** : 2025-10-09
**Phase** : 0 - Security Hardening
**Objectif** : Protéger tous les endpoints avec JWT authentication

---

## 🎯 Objectif

Remplacer tous les `tenant_id: str = Query(...)` par `tenant_id: str = Depends(get_tenant_id)` pour sécuriser l'isolation multi-tenant via JWT.

---

## 📋 État des Endpoints

### ✅ Endpoints Auth (Nouveaux - Sécurisés)

| Endpoint | Méthode | Protection | Status |
|----------|---------|------------|--------|
| `/api/auth/login` | POST | Public | ✅ OK |
| `/api/auth/refresh` | POST | Public | ✅ OK |
| `/api/auth/register` | POST | Public (⚠️ À protéger admin en prod) | ✅ OK |
| `/api/auth/me` | GET | JWT required | ✅ OK |

---

### 🟡 Endpoints Facts (Partiellement migrés)

| Endpoint | Méthode | Protection actuelle | Target | Status |
|----------|---------|-------------------|--------|--------|
| `/api/facts` | POST | tenant_id via get_tenant_id() | JWT required | ✅ **MIGRÉ** |
| `/api/facts` | GET | tenant_id via get_tenant_id() | JWT required | ✅ **MIGRÉ** |
| `/api/facts/{fact_id}` | GET | tenant_id via get_tenant_id() | JWT required | ✅ **MIGRÉ** |
| `/api/facts/{fact_id}` | PUT | tenant_id via get_tenant_id() | JWT required + editor | ✅ **MIGRÉ** |
| `/api/facts/{fact_id}` | DELETE | tenant_id via get_tenant_id() | JWT required + admin | ⚠️ À protéger avec require_admin |
| `/api/facts/{fact_id}/approve` | POST | tenant_id via get_tenant_id() | JWT required + admin | ⚠️ À protéger avec require_admin |
| `/api/facts/{fact_id}/reject` | POST | tenant_id via get_tenant_id() | JWT required + admin | ⚠️ À protéger avec require_admin |

---

### ⏸️ Endpoints Entities (À migrer)

| Endpoint | Méthode | Protection actuelle | Target | Status |
|----------|---------|-------------------|--------|--------|
| `/api/entities` | GET | tenant_id Query param | JWT required | ⏸️ TODO |
| `/api/entities/{uuid}` | GET | tenant_id Query param | JWT required | ⏸️ TODO |
| `/api/entities/{uuid}` | PUT | tenant_id Query param | JWT required + editor | ⏸️ TODO |
| `/api/entities/{uuid}` | DELETE | tenant_id Query param | JWT required + admin | ⏸️ TODO |
| `/api/entities/pending` | GET | tenant_id Query param | JWT required | ⏸️ TODO |
| `/api/entities/pending/approve` | POST | tenant_id Query param | JWT required + admin | ⏸️ TODO |

---

### ⏸️ Endpoints Entity Types (À migrer)

| Endpoint | Méthode | Protection actuelle | Target | Status |
|----------|---------|-------------------|--------|--------|
| `/api/entity-types` | GET | tenant_id Query param | JWT required | ⏸️ TODO |
| `/api/entity-types/{type_name}` | GET | tenant_id Query param | JWT required | ⏸️ TODO |
| `/api/entity-types/{type_name}/approve` | POST | Aucune | JWT required + admin | ⏸️ TODO |
| `/api/entity-types/{type_name}/reject` | POST | Aucune | JWT required + admin | ⏸️ TODO |

---

### ⏸️ Endpoints Document Types (À migrer)

| Endpoint | Méthode | Protection actuelle | Target | Status |
|----------|---------|-------------------|--------|--------|
| `/api/document-types` | GET | tenant_id Query param | JWT required | ⏸️ TODO |
| `/api/document-types` | POST | tenant_id Query param | JWT required + admin | ⏸️ TODO |
| `/api/document-types/{id}` | GET | tenant_id Query param | JWT required | ⏸️ TODO |
| `/api/document-types/{id}` | PUT | tenant_id Query param | JWT required + admin | ⏸️ TODO |
| `/api/document-types/{id}` | DELETE | tenant_id Query param | JWT required + admin | ⏸️ TODO |

---

### ⏸️ Endpoints Admin (À protéger)

| Endpoint | Méthode | Protection actuelle | Target | Status |
|----------|---------|-------------------|--------|--------|
| `/api/admin/purge` | POST | Aucune ⚠️ | JWT required + admin | ⏸️ **CRITIQUE** |
| `/api/admin/health` | GET | Public | Public | ✅ OK |

---

### ⏸️ Autres Endpoints (À auditer)

| Endpoint | Méthode | Protection actuelle | Target | Status |
|----------|---------|-------------------|--------|--------|
| `/search` | POST | tenant_id Query param ? | JWT required | ⏸️ À vérifier |
| `/api/imports` | GET | tenant_id Query param ? | JWT required | ⏸️ À vérifier |
| `/api/imports/sync` | POST | tenant_id Query param ? | JWT required | ⏸️ À vérifier |
| `/ingest` | POST | tenant_id Query param ? | JWT required + editor | ⏸️ À vérifier |

---

## 🛠️ Guide Migration

### Étape 1 : Remplacer Query param par Dependency

**Avant** :
```python
@router.get("/entities")
def list_entities(
    tenant_id: str = Query(..., description="Tenant ID"),
    # ...
):
    pass
```

**Après** :
```python
from knowbase.api.dependencies import get_tenant_id, require_editor

@router.get("/entities")
def list_entities(
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(require_editor),  # Si besoin restriction rôle
    # ...
):
    pass
```

### Étape 2 : Ajouter protection RBAC si nécessaire

**Pour endpoints admin** :
```python
from knowbase.api.dependencies import require_admin

@router.delete("/entities/{uuid}")
def delete_entity(
    uuid: str,
    current_user: dict = Depends(require_admin),  # Admin only
    tenant_id: str = Depends(get_tenant_id),
):
    pass
```

**Pour endpoints editor** :
```python
from knowbase.api.dependencies import require_editor

@router.post("/entities")
def create_entity(
    data: EntityCreate,
    current_user: dict = Depends(require_editor),  # Editor ou Admin
    tenant_id: str = Depends(get_tenant_id),
):
    pass
```

---

## 📊 Progression

| Catégorie | Total | Migrés | Restants | % |
|-----------|-------|--------|----------|---|
| **Auth** | 4 | 4 | 0 | 100% |
| **Facts** | 7 | 7 | 0 (⚠️ RBAC restant) | 100% |
| **Entities** | 6 | 0 | 6 | 0% |
| **Entity Types** | 4 | 0 | 4 | 0% |
| **Document Types** | 5 | 0 | 5 | 0% |
| **Admin** | 2 | 0 | 2 | 0% |
| **Autres** | 3 | 0 | 3 | 0% |
| **TOTAL** | **31** | **11** | **20** | **35%** |

---

## ⚠️ Endpoints Critiques (À protéger en priorité)

1. **`/api/admin/purge`** - ⚠️ **CRITIQUE** : Peut supprimer toutes les données !
2. **`/api/entity-types/{type_name}/approve`** - Admin only
3. **`/api/entity-types/{type_name}/reject`** - Admin only
4. **`/api/entities/pending/approve`** - Admin only
5. **DELETE endpoints** - Admin only

---

## 🔜 Prochaines Étapes

1. ✅ Facts router migré (tenant_id via JWT)
2. ⏸️ Ajouter require_admin sur DELETE/APPROVE/REJECT facts
3. ⏸️ Migrer Entities router
4. ⏸️ Migrer Entity Types router
5. ⏸️ Migrer Document Types router
6. ⏸️ Protéger Admin router (CRITIQUE)
7. ⏸️ Audit complet de tous les endpoints

---

*Dernière mise à jour : 2025-10-09*
