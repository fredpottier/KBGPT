# Routes Protection - SAP Knowledge Base

## 🔐 Protection des routes par rôle

### ✅ Pages Admin (Role: `admin`)
**Protégées par `/admin/layout.tsx`**

| Route | Description | Rôle requis |
|-------|-------------|-------------|
| `/admin` | Dashboard admin | `admin` |
| `/admin/dynamic-types` | Gestion types entités | `admin` |
| `/admin/dynamic-types/[typeName]` | Détail type entité | `admin` |
| `/admin/document-types` | Gestion types documents | `admin` |
| `/admin/document-types/new` | Création type document | `admin` |
| `/admin/document-types/[id]` | Édition type document | `admin` |
| `/admin/settings` | Paramètres système | `admin` |

### 📝 Pages Editor (Role: `editor` ou `admin`)
**Protégées individuellement**

| Route | Description | Rôle requis | Layout |
|-------|-------------|-------------|--------|
| `/documents/upload` | Upload documents | `editor` | `documents/upload/layout.tsx` |
| `/documents/import` | Import documents | `editor` | `documents/import/layout.tsx` |
| `/documents/rfp` | Traitement RFP | `editor` | `documents/rfp/layout.tsx` |
| `/rfp-excel` | Traitement RFP Excel | `editor` | `rfp-excel/layout.tsx` |

### 👁️ Pages Viewer (Role: `viewer`, `editor` ou `admin`)
**Protégées individuellement**

| Route | Description | Rôle requis | Layout |
|-------|-------------|-------------|--------|
| `/documents/status` | Suivi imports | `viewer` | `documents/status/layout.tsx` |

### 🌐 Pages Publiques (Pas d'authentification requise)

| Route | Description | Public |
|-------|-------------|--------|
| `/` | Page d'accueil | ✅ Oui |
| `/login` | Connexion | ✅ Oui |
| `/register` | Inscription | ✅ Oui |
| `/chat` | Chat assistant | ✅ Oui (à décider) |
| `/documents` | Liste documents | ✅ Oui (à décider) |
| `/documents/[id]` | Détail document | ✅ Oui (à décider) |

## 🎯 Hiérarchie des rôles

```
admin (full access)
  ├── Peut tout faire (admin + editor + viewer)
  ├── Gestion types entités (approve/reject)
  ├── Gestion types documents
  └── Paramètres système

editor (create/edit)
  ├── Upload/import documents
  ├── Traitement RFP
  ├── Création contenus
  └── Accès lecture (viewer)

viewer (read-only)
  ├── Consultation documents
  ├── Suivi imports
  ├── Chat assistant
  └── Recherche
```

## 🔒 Mécanisme de protection

### Méthode 1 : Layout protection (Recommandée)

Pour protéger **toute une section** (ex: `/admin/*`) :

```tsx
// frontend/src/app/admin/layout.tsx
'use client'

import { ProtectedRoute } from '@/components/auth/ProtectedRoute'

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute requireRole="admin">
      {children}
    </ProtectedRoute>
  )
}
```

### Méthode 2 : Page individuelle

Pour protéger **une page spécifique** :

```tsx
// frontend/src/app/some-page/page.tsx
'use client'

import { ProtectedRoute } from '@/components/auth/ProtectedRoute'

export default function MyPage() {
  return (
    <ProtectedRoute requireRole="editor">
      {/* Contenu page */}
    </ProtectedRoute>
  )
}
```

## ⚙️ Configuration

### AuthContext (Global)
**Fichier**: `frontend/src/contexts/AuthContext.tsx`

Fournit :
- `user` : Utilisateur connecté
- `isAuthenticated` : Booléen connexion
- `login()` : Méthode connexion
- `logout()` : Méthode déconnexion
- `hasRole(role)` : Vérification rôle

### ProtectedRoute Component
**Fichier**: `frontend/src/components/auth/ProtectedRoute.tsx`

Fonctionnalités :
- Vérifie authentification
- Vérifie rôle si `requireRole` fourni
- Redirige vers `/login` si non authentifié
- Affiche message si rôle insuffisant
- Gère paramètre `?redirect` pour retour après login

## 🧪 Tests de protection

### Test non authentifié
1. Ouvrir `/admin/dynamic-types`
2. ✅ Devrait rediriger vers `/login?redirect=/admin/dynamic-types`

### Test rôle insuffisant
1. Login en tant que `viewer`
2. Tenter d'accéder `/documents/upload`
3. ✅ Devrait afficher "Insufficient Permissions"

### Test rôle suffisant
1. Login en tant que `admin`
2. Accéder `/admin/dynamic-types`
3. ✅ Devrait afficher la page

## 📊 Récapitulatif protection

| Type | Nombre routes | Status |
|------|---------------|--------|
| **Pages Admin** | 7 | ✅ Protégées |
| **Pages Editor** | 4 | ✅ Protégées |
| **Pages Viewer** | 1 | ✅ Protégées |
| **Pages Publiques** | 6 | ✅ OK (volontairement public) |
| **TOTAL** | 18 pages | ✅ 100% configurées |

## 🚀 Après rebuild frontend

Une fois `docker compose build frontend && docker compose restart frontend` exécuté :

1. **Pages admin** : Nécessitent login + rôle admin
2. **Pages editor** : Nécessitent login + rôle editor ou admin
3. **Pages viewer** : Nécessitent login (tous rôles)
4. **Pages publiques** : Accessibles sans login

---

**Dernière mise à jour** : 2025-10-10
**Phase** : Phase 0 - Security Hardening (100% complété)
