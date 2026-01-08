# Configuration Authentification pour Déploiement AWS

**Date:** 2025-10-24
**Contexte:** Ajout de la création automatique de l'utilisateur admin par défaut et configuration JWT pour déploiement AWS

---

## 🎯 Problème Identifié

Lors d'un précédent déploiement AWS, deux problèmes ont été identifiés :
1. **L'utilisateur admin par défaut n'était pas créé** (`admin@example.com` / `admin123`)
2. **La clé JWT n'était pas configurée** dans `.env.production`

---

## ✅ Solutions Implémentées

### 1. Ajout de JWT_SECRET dans .env.ecr.example

**Fichier:** `.env.ecr.example`

Ajout d'une nouvelle section pour l'authentification et la sécurité :

```bash
# =====================================================
# AUTHENTIFICATION & SÉCURITÉ
# =====================================================
# Clé secrète JWT (OBLIGATOIRE pour authentification)
# Générez une clé aléatoire sécurisée:
#   - Python: python -c "import secrets; print(secrets.token_urlsafe(32))"
#   - OpenSSL: openssl rand -base64 32
JWT_SECRET=your-jwt-secret-key-change-in-production

# Mot de passe Grafana admin (monitoring)
GRAFANA_ADMIN_PASSWORD=admin
```

**Action requise avant déploiement :**
- Générer une clé JWT sécurisée aléatoire
- Ajouter cette clé dans `.env.production`

### 2. Création Automatique Utilisateur Admin

**Fichier créé:** `src/knowbase/db/init_admin.py`

Script qui :
- Vérifie si l'utilisateur `admin@example.com` existe
- Si non, le crée avec le mot de passe `admin123`
- S'exécute automatiquement au démarrage de l'application

**Credentials par défaut :**
```
Email: admin@example.com
Password: admin123
Role: admin
Tenant: default
```

⚠️ **IMPORTANT:** Changez le mot de passe admin après le premier déploiement !

### 3. Ajout Fonctions Hash Password

**Fichier modifié:** `src/knowbase/common/auth.py`

Ajout de deux fonctions utilisant `bcrypt` :

```python
def hash_password(password: str) -> str:
    """Hash un mot de passe avec bcrypt."""
    ...

def verify_password(password: str, password_hash: str) -> bool:
    """Vérifie un mot de passe contre son hash."""
    ...
```

**Dépendance :** `bcrypt==4.0.1` (déjà dans `app/requirements.txt`)

### 4. Intégration au Démarrage Application

**Fichier modifié:** `src/knowbase/api/main.py`

Ajout de l'appel à l'initialisation admin dans la fonction `create_app()` :

```python
# Créer utilisateur admin par défaut si n'existe pas
from knowbase.db.init_admin import init_default_admin
init_default_admin()
logger.info("✅ Utilisateur admin vérifié/créé")
```

L'initialisation se fait juste après la création des tables SQLite et avant le démarrage de l'API.

---

## 📋 Checklist Déploiement AWS

Avant de déployer sur AWS avec le monitoring stack :

### Configuration .env.production

```bash
# 1. Générer JWT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 2. Ajouter dans .env.production
JWT_SECRET=<clé-générée>
GRAFANA_ADMIN_PASSWORD=<mot-de-passe-grafana>

# 3. Configurer les autres variables obligatoires
OPENAI_API_KEY=<votre-clé>
ANTHROPIC_API_KEY=<votre-clé>
NEO4J_PASSWORD=<mot-de-passe-neo4j>
AWS_ACCOUNT_ID=<votre-account-id>
AWS_REGION=eu-west-1
```

### Après Premier Déploiement

1. **Se connecter à l'interface** : `http://<IP_EC2>:3000`
2. **Login avec credentials par défaut** :
   - Email: `admin@example.com`
   - Password: `admin123`
3. **⚠️ CHANGER LE MOT DE PASSE IMMÉDIATEMENT** via l'interface ou l'API

### Changement Mot de Passe Admin

Via l'API (à implémenter si pas déjà fait) :

```bash
curl -X POST http://<IP_EC2>:8000/api/auth/change-password \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "current_password": "admin123",
    "new_password": "nouveau-mot-de-passe-sécurisé"
  }'
```

---

## 🔧 Fichiers Modifiés

| Fichier | Type de Modification | Description |
|---------|---------------------|-------------|
| `.env.ecr.example` | Ajout | Section authentification + JWT_SECRET |
| `src/knowbase/db/init_admin.py` | Création | Script initialisation admin |
| `src/knowbase/common/auth.py` | Ajout | Fonctions hash_password/verify_password |
| `src/knowbase/api/main.py` | Modification | Appel init_default_admin au startup |
| `src/knowbase/db/__init__.py` | Modification | Export init_default_admin |

---

## 🚀 Déploiement

Le déploiement se fait normalement avec les scripts existants :

```powershell
# Build et push des images vers ECR (si pas déjà fait)
.\scripts\aws\build-and-push-ecr.ps1

# Déploiement complet (app + monitoring)
.\scripts\aws\deploy-cloudformation.ps1 `
    -StackName "knowbase-prod" `
    -KeyPairName "my-key" `
    -KeyPath ".\my-key.pem"
```

L'utilisateur admin sera créé automatiquement au démarrage du conteneur `app`.

---

## 🔐 Sécurité

### Bonnes Pratiques

1. **JWT_SECRET**
   - Générer une clé aléatoire de 32+ caractères
   - Ne jamais commiter dans git
   - Différente pour chaque environnement (dev/staging/prod)

2. **Mot de Passe Admin**
   - Changer `admin123` immédiatement après premier déploiement
   - Utiliser un gestionnaire de mots de passe
   - Minimum 16 caractères avec chiffres/symboles

3. **Variables d'Environnement**
   - Stocker les secrets dans AWS Secrets Manager (optionnel)
   - Ne jamais logger JWT_SECRET ou mots de passe
   - Rotation régulière des clés API

### Rotation JWT_SECRET

Si vous devez changer le JWT_SECRET :

1. Mettre à jour `.env.production` sur EC2
2. Redémarrer le conteneur app : `docker-compose restart app`
3. Tous les tokens existants seront invalidés (utilisateurs devront se reconnecter)

---

## 📝 Notes Techniques

### Ordre d'Initialisation au Startup

```
1. configure_logging()
2. warm_clients()
3. init_db()              ← Crée tables SQLite
4. init_default_admin()   ← Crée utilisateur admin (NOUVEAU)
5. FastAPI app creation
6. Routes mounting
7. Uvicorn start
```

### Structure Base de Données Users

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    role TEXT DEFAULT 'viewer',  -- admin | editor | viewer
    tenant_id TEXT DEFAULT 'default',
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

L'utilisateur admin par défaut aura :
- `role='admin'` : Accès complet à tous les endpoints
- `tenant_id='default'` : Tenant par défaut
- `is_active=True` : Compte actif

---

## 🧪 Tests

Pour tester localement avant déploiement AWS :

```bash
# 1. Démarrer les services locaux
docker-compose up -d

# 2. Vérifier les logs de création admin
docker-compose logs app | grep "admin"

# Devrait afficher:
# ✅ Utilisateur admin créé avec succès: admin@example.com
# ⚠️  SÉCURITÉ: Changez le mot de passe admin après le premier déploiement !

# 3. Tester login via API
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "password": "admin123"
  }'

# Devrait retourner un token JWT
```

---

## 🐛 Troubleshooting

### Utilisateur admin non créé

**Symptômes :** Impossible de se connecter avec `admin@example.com`

**Solutions :**
1. Vérifier les logs : `docker-compose logs app | grep admin`
2. Vérifier que SQLite est bien initialisé : `docker-compose exec app ls -la /data/knowbase.db`
3. Exécuter manuellement : `docker-compose exec app python -m knowbase.db.init_admin`

### Erreur "JWT_SECRET not set"

**Symptômes :** Erreur au démarrage ou lors du login

**Solutions :**
1. Vérifier `.env.production` contient `JWT_SECRET=...`
2. Redémarrer le conteneur : `docker-compose restart app`
3. Vérifier variables d'env : `docker-compose exec app env | grep JWT`

### Mot de passe admin ne fonctionne pas

**Symptômes :** Login échoue avec `admin123`

**Solutions :**
1. Vérifier que bcrypt est bien installé : `docker-compose exec app pip list | grep bcrypt`
2. Recréer l'utilisateur :
   ```bash
   docker-compose exec app python -c "
   from knowbase.db.base import SessionLocal
   from knowbase.db.models import User
   db = SessionLocal()
   user = db.query(User).filter(User.email=='admin@example.com').first()
   print(f'User exists: {user is not None}')
   print(f'Password hash: {user.password_hash[:30]}...')
   db.close()
   "
   ```

---

**Auteur:** Claude Code
**Validation:** Tests locaux OK + Documentation complète
**Prochaine étape:** Déploiement AWS avec monitoring stack complet
