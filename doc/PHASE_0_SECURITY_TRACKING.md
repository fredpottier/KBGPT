# Phase 0 : Security Hardening - Tracking

**Projet** : Back2Promise - SAP Knowledge Base
**Phase** : Phase 0 - Security Hardening
**Priorité** : P0 BLOQUANT PRODUCTION 🔴
**Statut** : 🚀 **EN COURS** (Démarré le 2025-10-09)
**Durée prévue** : 4 semaines
**Effort estimé** : 160 heures

---

## 🎯 Objectif

Sécuriser le système pour permettre un déploiement en production. Sans cette phase, le système présente des vulnérabilités critiques (Score : 6.5/10).

**Target** : Score sécurité > 8.5/10

---

## 📊 Avancement Global

| Métrique | Actuel | Target |
|----------|--------|--------|
| **Statut Phase** | EN COURS | COMPLÉTÉ |
| **Semaines écoulées** | 0/4 | 4/4 |
| **Tâches complétées** | 0/16 | 16/16 |
| **Tests sécurité coverage** | 0% | 85%+ |
| **Score sécurité** | 6.5/10 | 8.5+/10 |
| **Avancement estimé** | 0% | 100% |

---

## 📋 Tâches par Semaine

### ✅ Semaine 1 : Authentication & Authorization (0/4 tâches)

#### 1.1 JWT Authentication (RS256)
**Status** : ⏸️ PENDING
**Effort estimé** : 40h
**Effort réel** : -

**Sous-tâches** :
- [ ] Installer et configurer PyJWT avec RS256
- [ ] Générer paire de clés RSA (private/public key)
- [ ] Implémenter `generate_access_token()` et `generate_refresh_token()`
- [ ] Implémenter `verify_token()` avec validation claims
- [ ] Claims : `user_id`, `email`, `role`, `tenant_id`
- [ ] Gestion expiration (access: 1h, refresh: 7j)
- [ ] Endpoint `POST /auth/login` (email, password)
- [ ] Endpoint `POST /auth/refresh` (refresh token)
- [ ] Tests unitaires (15+ tests)

**Critères d'acceptance** :
- [ ] Tokens JWT valides générés
- [ ] Validation claims fonctionne
- [ ] Expiration respectée
- [ ] Tests passent

#### 1.2 Dependencies FastAPI
**Status** : ⏸️ PENDING
**Effort estimé** : 10h
**Effort réel** : -

**Sous-tâches** :
- [ ] Créer `get_current_user()` dependency
- [ ] Créer `require_admin()` dependency
- [ ] Créer `require_editor()` dependency
- [ ] Créer `get_tenant_id()` depuis JWT (pas query param)
- [ ] Tests dependencies (10+ tests)

**Critères d'acceptance** :
- [ ] Dependencies importables
- [ ] Erreurs 401/403 appropriées
- [ ] tenant_id extrait correctement

#### 1.3 Extraction tenant_id depuis JWT
**Status** : ⏸️ PENDING
**Effort estimé** : 5h
**Effort réel** : -

**Sous-tâches** :
- [ ] Remplacer tous les `tenant_id: str = Query(...)` par JWT claim
- [ ] Vérifier isolation multi-tenant dans queries
- [ ] Tests isolation (20+ scénarios)

**Critères d'acceptance** :
- [ ] Plus de tenant_id en query params
- [ ] Isolation multi-tenant garantie

#### 1.4 Tests Authentication E2E
**Status** : ⏸️ PENDING
**Effort estimé** : 5h
**Effort réel** : -

**Sous-tâches** :
- [ ] Test login success
- [ ] Test login échec (mauvais password)
- [ ] Test refresh token
- [ ] Test token expiré
- [ ] Test token invalide

---

### ✅ Semaine 2 : Input Validation & Sanitization (0/4 tâches)

#### 2.1 Validation entity_type et relation_type
**Status** : ⏸️ PENDING
**Effort estimé** : 20h
**Effort réel** : -

**Sous-tâches** :
- [ ] Regex validation : `^[A-Z][A-Z0-9_]{0,49}$`
- [ ] Blacklist types système (`_`, `SYSTEM_`)
- [ ] Validator Pydantic `EntityTypeValidator`
- [ ] Appliquer sur tous les endpoints
- [ ] Tests validation (30+ cas)

**Critères d'acceptance** :
- [ ] Types invalides → 400 Bad Request
- [ ] Types système bloqués
- [ ] Tests fuzzing passent

#### 2.2 Validation entity.name
**Status** : ⏸️ PENDING
**Effort estimé** : 15h
**Effort réel** : -

**Sous-tâches** :
- [ ] Interdire `<>'"` (XSS prevention)
- [ ] Interdire path traversal (`../`, `..\\`)
- [ ] Max length 200 chars
- [ ] Validator Pydantic
- [ ] Tests fuzzing (1000+ inputs malformés)

**Critères d'acceptance** :
- [ ] Injections bloquées
- [ ] Tests fuzzing 100% bloqués

#### 2.3 Sanitization logs
**Status** : ⏸️ PENDING
**Effort estimé** : 10h
**Effort réel** : -

**Sous-tâches** :
- [ ] Escape newlines dans logs
- [ ] Sanitize user inputs avant logging
- [ ] Tests injection logs

#### 2.4 Tests Fuzzing Globaux
**Status** : ⏸️ PENDING
**Effort estimé** : 15h
**Effort réel** : -

**Sous-tâches** :
- [ ] Suite fuzzing 1000+ inputs
- [ ] Vérifier aucune erreur 500
- [ ] Documenter patterns bloqués

---

### ✅ Semaine 3 : RBAC & Authorization (0/4 tâches)

#### 3.1 Définition des Rôles
**Status** : ⏸️ PENDING
**Effort estimé** : 10h
**Effort réel** : -

**Sous-tâches** :
- [ ] Enum Roles : `admin`, `editor`, `viewer`
- [ ] Matrice permissions (doc/RBAC_MATRIX.md)
- [ ] Modèle User PostgreSQL (id, email, password_hash, role, tenant_id)
- [ ] Modèle UserRole si multi-rôles

**Critères d'acceptance** :
- [ ] Rôles définis clairement
- [ ] Matrice documentée

#### 3.2 Implémentation RBAC
**Status** : ⏸️ PENDING
**Effort estimé** : 25h
**Effort réel** : -

**Sous-tâches** :
- [ ] Decorator `@require_role("admin")`
- [ ] Appliquer sur endpoints DELETE (admin only)
- [ ] Appliquer sur endpoints POST admin (admin only)
- [ ] Appliquer sur endpoints PUT (editor, admin)
- [ ] GET endpoints (viewer, editor, admin)

**Critères d'acceptance** :
- [ ] Admin peut tout faire
- [ ] Editor peut créer/modifier
- [ ] Viewer peut seulement lire

#### 3.3 Verify Entity Ownership
**Status** : ⏸️ PENDING
**Effort estimé** : 20h
**Effort réel** : -

**Sous-tâches** :
- [ ] Vérifier tenant_id sur toutes opérations
- [ ] Empêcher accès cross-tenant
- [ ] Tests isolation multi-tenant (50+ scénarios)

**Critères d'acceptance** :
- [ ] Isolation tenant garantie
- [ ] Tests passent

#### 3.4 Tests RBAC
**Status** : ⏸️ PENDING
**Effort estimé** : 15h
**Effort réel** : -

**Sous-tâches** :
- [ ] Tests 30+ scénarios
- [ ] Test admin peut DELETE
- [ ] Test editor ne peut pas DELETE
- [ ] Test viewer ne peut pas POST/PUT/DELETE
- [ ] Test cross-tenant bloqué

---

### ✅ Semaine 4 : Audit & Rate Limiting (0/4 tâches)

#### 4.1 Audit Service
**Status** : ⏸️ PENDING
**Effort estimé** : 20h
**Effort réel** : -

**Sous-tâches** :
- [ ] Table `audit_log` PostgreSQL (id, timestamp, user_id, action, resource_type, resource_id, details_json)
- [ ] AuditService.log_action()
- [ ] Logger toutes mutations (CREATE, UPDATE, DELETE, APPROVE)
- [ ] Endpoint `GET /admin/audit-log` (admin only)

**Critères d'acceptance** :
- [ ] Toutes mutations loggées
- [ ] Audit consultable

#### 4.2 UI Admin Audit Trail
**Status** : ⏸️ PENDING
**Effort estimé** : 15h
**Effort réel** : -

**Sous-tâches** :
- [ ] Page React `/admin/audit-log`
- [ ] Filtres (date, user, action)
- [ ] Pagination

#### 4.3 Rate Limiting
**Status** : ⏸️ PENDING
**Effort estimé** : 15h
**Effort réel** : -

**Sous-tâches** :
- [ ] Installer SlowAPI
- [ ] Rate limit DELETE : 5/min
- [ ] Rate limit READ : 100/min
- [ ] Tests rate limiting

**Critères d'acceptance** :
- [ ] Rate limits respectés
- [ ] Erreur 429 si dépassé

#### 4.4 Monitoring & Alertes
**Status** : ⏸️ PENDING
**Effort estimé** : 10h
**Effort réel** : -

**Sous-tâches** :
- [ ] Alerte si >50 deletes/heure
- [ ] Dashboard métriques sécurité

---

## ✅ Critères d'Acceptance Phase Complète

- [ ] JWT obligatoire sur tous endpoints sauf `/auth/login`
- [ ] RBAC testé pour 3 rôles (admin, editor, viewer)
- [ ] entity_type invalide → 400 Bad Request
- [ ] Audit trail complet sur mutations
- [ ] Rate limiting configuré
- [ ] Score sécurité > 8.5/10
- [ ] Tests sécurité coverage 85%+
- [ ] Documentation API mise à jour

---

## 📊 Métriques de Succès

| Métrique | Baseline | Target | Actuel |
|----------|----------|--------|--------|
| **Score sécurité** | 6.5/10 | 8.5+/10 | - |
| **JWT coverage** | 0% | 100% | - |
| **RBAC endpoints protégés** | 0% | 100% | - |
| **Audit trail mutations** | 0% | 100% | - |
| **Tests sécurité coverage** | 0% | 85%+ | - |
| **Validation stricte inputs** | 30% | 100% | - |

---

## 🚨 Risques Identifiés

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| JWT RS256 complexité key management | Moyen | Élevé | Utiliser PyJWT library éprouvée, doc claire |
| RBAC granularité insuffisante | Faible | Moyen | Matrice permissions extensible |
| Performance overhead JWT | Faible | Faible | Cache validation, < 10ms acceptable |
| Tests sécurité incomplets | Moyen | Élevé | Fuzzing automatisé, code review externe |

---

## 📝 Notes de Session

### 2025-10-09 - Démarrage Phase 0
- Phase 0 officiellement démarrée
- Document tracking créé
- Todo list initialisée
- Prochaine étape : Commencer Semaine 1 - JWT Authentication

---

## 🔗 Références

- `doc/BACK2PROMISE_MASTER_ROADMAP.md` - Roadmap complète
- `doc/SECURITY_AUDIT_DYNAMIC_TYPES.md` - Audit sécurité détaillé
- `doc/NORTH_STAR_NEO4J_NATIVE.md` - Architecture v2.1

---

*Dernière mise à jour : 2025-10-09*
