# Rapport d'Audit de Sécurité - KnowWhere/OSMOSE

**Date:** 2025-10-22
**Auditeur:** Claude Code
**Portée:** Analyse complète du code source pour identification des vulnérabilités et recommandations de durcissement
**Méthodologie:** Audit de code statique, analyse de configuration, revue des dépendances

---

## Résumé Exécutif

### Niveau de Sécurité Actuel: **MOYEN** ⚠️

L'application KnowWhere/OSMOSE présente une **base de sécurité solide** avec l'implémentation de plusieurs bonnes pratiques (JWT RS256, RBAC, validation des entrées, rate limiting). Cependant, plusieurs **vulnérabilités critiques et moyennes** ont été identifiées qui nécessitent un durcissement avant le déploiement en production.

### Vulnérabilités Critiques Identifiées: 5
### Vulnérabilités Moyennes: 12
### Bonnes Pratiques Observées: 8

---

## 🔴 Vulnérabilités CRITIQUES (Priorité Haute)

### 1. Endpoint d'Inscription Public Sans Protection

**Fichier:** `src/knowbase/api/routers/auth.py:201`

**Description:**
L'endpoint `/api/auth/register` permet à n'importe qui de créer un compte utilisateur sans restriction. Un attaquant peut créer des comptes admin/editor en masse.

```python
@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_data: UserCreate,
    db: Session = Depends(get_db)
) -> UserResponse:
    """
    ⚠️ En production, cet endpoint devrait être protégé (admin only)
    ou désactivé selon la politique d'inscription.
    """
```

**Impact:**
- Création de comptes non autorisés
- Escalade de privilèges (si rôle non validé)
- Épuisement des ressources (création massive de comptes)

**Recommandations:**
1. ✅ **Protéger avec `require_admin` dependency**
2. ✅ **Implémenter un système d'invitation par email**
3. ✅ **Ajouter un flag `ALLOW_PUBLIC_REGISTRATION` dans settings** (défaut: false)
4. ✅ **Forcer le rôle "viewer" pour les inscriptions publiques** (si activées)
5. ✅ **Ajouter CAPTCHA** pour prévenir l'automatisation

---

### 2. Bases de Données Exposées Sans Authentification Forte

**Fichiers:**
- `docker-compose.yml:5-22` (Qdrant)
- `docker-compose.yml:24-35` (Redis)
- `.env.example:20-23` (Neo4j)

**Description:**
Les bases de données critiques sont exposées avec des configurations faibles:

- **Qdrant** (port 6333): Exposé publiquement sans API key
- **Redis** (port 6379): Pas de mot de passe (`redis-server --appendonly yes`)
- **Neo4j**: Mot de passe par défaut `neo4j_password` dans `.env.example`

**Impact:**
- Accès direct aux données vectorielles (Qdrant)
- Manipulation de la queue de jobs (Redis)
- Lecture/écriture dans le knowledge graph (Neo4j)
- Vol de données sensibles
- Injection de données malveillantes

**Recommandations:**

**Qdrant:**
```yaml
# docker-compose.yml
qdrant:
  environment:
    - QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY}
```

**Redis:**
```yaml
redis:
  command: >
    redis-server
    --requirepass ${REDIS_PASSWORD}
    --appendonly yes
```

**Neo4j:**
```bash
# Générer mot de passe fort
openssl rand -base64 32
```

---

### 3. Pas de Validation de Type MIME pour les Uploads

**Fichier:** `src/knowbase/api/services/ingestion.py:331-332, 401-402, 478-479`

**Description:**
La validation des fichiers uploadés se base uniquement sur l'extension du nom de fichier, facilement contournable:

```python
if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
    raise HTTPException(status_code=400, detail="Fichier Excel (.xlsx/.xls) requis")
```

**Impact:**
- Upload de fichiers malveillants déguisés (ex: `malware.exe` → `malware.exe.xlsx`)
- Exécution de code via vulnérabilités dans parsers (openpyxl, PyMuPDF, python-pptx)
- ZIP bombs dans fichiers Office (XLSX/PPTX sont des archives ZIP)

**Recommandations:**
1. ✅ **Valider le type MIME réel** avec `python-magic`:
```python
import magic

def validate_file_type(file: UploadFile, allowed_mimes: list[str]) -> bool:
    """Valide le type MIME réel du fichier."""
    file_content = file.file.read(2048)  # Lire les premiers octets
    file.file.seek(0)  # Reset file pointer

    mime = magic.from_buffer(file_content, mime=True)

    if mime not in allowed_mimes:
        raise HTTPException(
            status_code=400,
            detail=f"Type de fichier non autorisé: {mime}"
        )

    return True

# Usage
ALLOWED_EXCEL_MIMES = [
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
    'application/vnd.ms-excel'  # .xls
]

validate_file_type(file, ALLOWED_EXCEL_MIMES)
```

2. ✅ **Ajouter limite de taille de fichier**:
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

async def validate_file_size(file: UploadFile):
    file.file.seek(0, 2)  # Seek to end
    size = file.file.tell()
    file.file.seek(0)  # Reset

    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux: {size} bytes (max: {MAX_FILE_SIZE})"
        )
```

3. ✅ **Scanner les fichiers uploadés** avec ClamAV:
```python
import clamd

def scan_file_for_viruses(file_path: Path) -> bool:
    """Scan fichier avec ClamAV."""
    cd = clamd.ClamdUnixSocket()
    result = cd.scan(str(file_path))

    if result[str(file_path)][0] == 'FOUND':
        raise HTTPException(
            status_code=400,
            detail="Fichier infecté détecté"
        )

    return True
```

---

### 4. Pas de Rate Limiting sur les Endpoints d'Authentification

**Fichier:** `src/knowbase/api/routers/auth.py:33-110`

**Description:**
Les endpoints de login et refresh ne sont pas protégés par un rate limiting spécifique, permettant des attaques par brute force sur les mots de passe.

**Impact:**
- Attaques par brute force sur les mots de passe
- Énumération d'emails valides
- Épuisement des ressources serveur

**Recommandations:**

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")  # Max 5 tentatives par minute
async def login(
    request: Request,  # Nécessaire pour slowapi
    login_data: LoginRequest,
    db: Session = Depends(get_db)
) -> LoginResponse:
    # ...
```

**Également implémenter:**
- ✅ **Account lockout** après 5 tentatives échouées
- ✅ **CAPTCHA** après 3 tentatives échouées
- ✅ **Délai exponentiel** entre tentatives

---

### 5. Secrets Stockés en Clair dans Variables d'Environnement

**Fichiers:**
- `.env` (non versionné, mais présent en production)
- `src/knowbase/config/settings.py:47-59`

**Description:**
Les secrets critiques (API keys, passwords) sont stockés en clair dans des variables d'environnement sans chiffrement:

```python
openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
neo4j_password: str = Field(default="graphiti_neo4j_pass", alias="NEO4J_PASSWORD")
```

**Impact:**
- Exposition des secrets si accès au système de fichiers
- Fuite via logs de conteneurs
- Compromission des services externes (OpenAI, Anthropic)

**Recommandations:**

1. ✅ **Utiliser un Secrets Manager** (AWS Secrets Manager, HashiCorp Vault, Azure Key Vault):
```python
import boto3
from botocore.exceptions import ClientError

def get_secret(secret_name: str) -> str:
    """Récupère secret depuis AWS Secrets Manager."""
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name='eu-west-1'
    )

    try:
        response = client.get_secret_value(SecretId=secret_name)
        return response['SecretString']
    except ClientError as e:
        logger.error(f"Erreur récupération secret {secret_name}: {e}")
        raise

# Usage
openai_api_key = get_secret('knowwhere/openai-api-key')
```

2. ✅ **Chiffrer les secrets au repos** si Secrets Manager non disponible:
```python
from cryptography.fernet import Fernet

def decrypt_secret(encrypted_secret: str, key: bytes) -> str:
    """Déchiffre un secret avec Fernet."""
    f = Fernet(key)
    return f.decrypt(encrypted_secret.encode()).decode()
```

3. ✅ **Rotation automatique des secrets** (ex: tous les 90 jours)

4. ✅ **Audit logging** pour accès aux secrets

---

## 🟠 Vulnérabilités MOYENNES (Priorité Moyenne)

### 6. CORS Trop Permissif

**Fichier:** `src/knowbase/api/main.py:140-153`

**Description:**
La configuration CORS autorise tous les methods et headers avec credentials:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8501",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # ⚠️ Trop permissif
    allow_headers=["*"],  # ⚠️ Trop permissif
)
```

**Recommandations:**

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,  # Configurable par environnement
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],  # Explicite
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Tenant-ID",
        "X-User-ID"
    ],  # Explicite
    max_age=3600,  # Cache preflight requests
)
```

---

### 7. Pas de Protection CSRF

**Fichier:** `src/knowbase/api/main.py`

**Description:**
Aucune protection CSRF n'est implémentée pour les endpoints modifiant des données.

**Recommandations:**

```python
from fastapi_csrf_protect import CsrfProtect

@app.post("/api/documents/upload")
async def upload(
    request: Request,
    csrf_protect: CsrfProtect = Depends()
):
    await csrf_protect.validate_csrf(request)
    # ...
```

---

### 8. Headers de Sécurité HTTP Manquants

**Fichier:** `src/knowbase/api/main.py`

**Description:**
Absence de headers de sécurité critiques:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy`
- `Strict-Transport-Security`

**Recommandations:**

```python
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self'"
        )

        return response

app.add_middleware(SecurityHeadersMiddleware)
```

---

### 9. Swagger UI Exposé en Production

**Fichier:** `src/knowbase/api/main.py:38-133`

**Description:**
L'interface Swagger UI (`/docs`) expose la structure complète de l'API en production, facilitant la reconnaissance.

**Recommandations:**

```python
def create_app() -> FastAPI:
    settings = get_settings()

    # Désactiver docs en production
    docs_url = "/docs" if settings.debug_mode else None
    redoc_url = "/redoc" if settings.debug_mode else None

    app = FastAPI(
        title="SAP Knowbase API",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url="/openapi.json" if settings.debug_mode else None
    )
```

---

### 10. Pas de Politique de Complexité des Mots de Passe

**Fichier:** `src/knowbase/api/routers/auth.py:233`

**Description:**
Aucune validation de la complexité des mots de passe lors de l'inscription.

**Recommandations:**

```python
import re

def validate_password_strength(password: str) -> bool:
    """
    Valide la force d'un mot de passe.

    Règles:
    - Minimum 12 caractères
    - Au moins 1 majuscule
    - Au moins 1 minuscule
    - Au moins 1 chiffre
    - Au moins 1 caractère spécial
    """
    if len(password) < 12:
        raise ValueError("Mot de passe trop court (min 12 caractères)")

    if not re.search(r'[A-Z]', password):
        raise ValueError("Mot de passe doit contenir au moins 1 majuscule")

    if not re.search(r'[a-z]', password):
        raise ValueError("Mot de passe doit contenir au moins 1 minuscule")

    if not re.search(r'[0-9]', password):
        raise ValueError("Mot de passe doit contenir au moins 1 chiffre")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValueError("Mot de passe doit contenir au moins 1 caractère spécial")

    return True

# Dans schemas/auth.py
from pydantic import field_validator

class UserCreate(BaseModel):
    email: EmailStr
    password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        validate_password_strength(v)
        return v
```

---

### 11. Tokens JWT Non Révocables

**Fichier:** `src/knowbase/api/services/auth_service.py`

**Description:**
Une fois émis, les tokens JWT restent valides jusqu'à expiration même si l'utilisateur se déconnecte ou est désactivé.

**Recommandations:**

```python
# Implémenter une blacklist Redis pour les tokens révoqués

from redis import Redis

class TokenBlacklist:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    def revoke_token(self, token: str, expires_at: datetime):
        """Ajoute token à la blacklist jusqu'à son expiration."""
        ttl = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        self.redis.setex(f"blacklist:{token}", ttl, "1")

    def is_revoked(self, token: str) -> bool:
        """Vérifie si token est révoqué."""
        return self.redis.exists(f"blacklist:{token}") > 0

# Dans dependencies.py
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    auth_service = get_auth_service()
    token = credentials.credentials

    # Vérifier blacklist
    if token_blacklist.is_revoked(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token révoqué"
        )

    claims = auth_service.verify_access_token(token)
    return claims
```

---

### 12. Fichiers Temporaires Non Nettoyés en Cas d'Erreur

**Fichier:** `src/knowbase/api/services/ingestion.py:482-541`

**Description:**
En cas d'erreur lors du traitement d'un fichier Excel uploadé, le fichier temporaire peut ne pas être supprimé:

```python
try:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as temp_file:
        contents = await file.read()
        temp_file.write(contents)
        temp_path = temp_file.name

    # ... traitement ...

    Path(temp_path).unlink()  # ⚠️ Peut ne jamais être atteint si exception
```

**Recommandations:**

```python
from contextlib import contextmanager

@contextmanager
def secure_temp_file(suffix: str):
    """Context manager pour fichiers temporaires avec nettoyage garanti."""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = temp_file.name

    try:
        yield temp_file, temp_path
    finally:
        temp_file.close()
        try:
            Path(temp_path).unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Erreur suppression fichier temporaire: {e}")

# Usage
async def analyze_excel_file(...):
    async with secure_temp_file('.xlsx') as (temp_file, temp_path):
        contents = await file.read()
        temp_file.write(contents)
        temp_file.flush()

        # Traitement...
        # Fichier sera supprimé automatiquement même si exception
```

---

### 13. Pas de Limite sur la Taille des Payloads JSON

**Fichier:** `src/knowbase/api/main.py`

**Description:**
Aucune limite de taille pour les payloads JSON, permettant des attaques DoS par JSON bombing.

**Recommandations:**

```python
from fastapi import Request
from fastapi.exceptions import RequestValidationError

MAX_JSON_SIZE = 10 * 1024 * 1024  # 10 MB

@app.middleware("http")
async def validate_json_size(request: Request, call_next):
    if request.headers.get("content-type") == "application/json":
        content_length = request.headers.get("content-length")

        if content_length and int(content_length) > MAX_JSON_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Payload JSON trop volumineux"
            )

    return await call_next(request)
```

---

### 14. Requêtes Cypher avec Concaténation de Strings

**Fichier:** `src/knowbase/common/clients/neo4j_client.py:215-228`

**Description:**
Construction de requêtes Cypher avec concaténation de strings, potentiel risque d'injection:

```python
where_clause = " AND ".join(filters)

query = f"""
MATCH (c:ProtoConcept)
WHERE {where_clause}
RETURN c.concept_id AS concept_id,
       ...
"""
```

**Impact Actuel:** ✅ **MITIGÉ** - Les filtres sont construits côté application et les valeurs sont paramétrées, donc pas d'injection directe.

**Recommandations de Durcissement:**

```python
# Toujours utiliser des requêtes paramétrées avec query builder
from neo4j.graph import Graph

def get_proto_concepts_safe(...):
    # Utiliser un query builder ou valider strictement les filtres
    allowed_filter_keys = ["tenant_id", "segment_id", "document_id", "concept_type"]

    for key in params.keys():
        if key not in allowed_filter_keys:
            raise ValueError(f"Filtre non autorisé: {key}")

    # ...
```

---

### 15. Exposition d'Informations Sensibles dans les Logs

**Fichier:** Plusieurs fichiers de logging

**Description:**
Bien que `log_sanitizer.py` soit implémenté, il n'est pas utilisé systématiquement dans tous les modules.

**Recommandations:**

```python
from knowbase.common.log_sanitizer import sanitize_for_log, sanitize_sensitive_fields

# Toujours sanitiser avant logging
logger.info(f"User login: {sanitize_for_log(email)}")

# Pour les dicts avec données sensibles
log_data = sanitize_sensitive_fields(user_data)
logger.info(f"User created: {log_data}")
```

---

### 16. Pas de Chiffrement des Connexions aux Bases de Données

**Fichiers:**
- `src/knowbase/common/clients/neo4j_client.py:54-61`
- `src/knowbase/config/settings.py:51-58`

**Description:**
Les connexions aux bases de données (Neo4j, Qdrant, Redis) n'utilisent pas de chiffrement TLS/SSL.

**Recommandations:**

**Neo4j:**
```python
self.driver = GraphDatabase.driver(
    uri.replace('bolt://', 'bolt+s://'),  # TLS
    auth=(user, password),
    encrypted=True,
    trust=TRUST_SYSTEM_CA_SIGNED_CERTIFICATES
)
```

**Redis:**
```python
redis_client = Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    password=settings.redis_password,
    ssl=True,
    ssl_cert_reqs='required',
    ssl_ca_certs='/path/to/ca.pem'
)
```

**Qdrant:**
```python
qdrant_client = QdrantClient(
    url=settings.qdrant_url.replace('http://', 'https://'),
    api_key=settings.qdrant_api_key,
    https=True,
    verify=True
)
```

---

### 17. Containers Docker Run as Root

**Fichier:** `app/Dockerfile`, `frontend/Dockerfile`

**Description:**
Les containers Docker s'exécutent probablement en tant que root (non vérifié explicitement dans les Dockerfiles).

**Recommandations:**

```dockerfile
# app/Dockerfile
FROM python:3.11-slim

# Créer utilisateur non-root
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Installer dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier code
COPY --chown=appuser:appuser . /app
WORKDIR /app

# Changer vers utilisateur non-root
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## ✅ Bonnes Pratiques Observées

### 1. Authentification JWT avec RS256 ✅

**Fichier:** `src/knowbase/api/services/auth_service.py:24`

Utilisation de JWT avec algorithme asymétrique RS256 (plus sécurisé que HS256).

---

### 2. Hashing des Mots de Passe avec Bcrypt ✅

**Fichier:** `src/knowbase/api/services/auth_service.py:20`

```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

---

### 3. Validation Stricte des Entrées ✅

**Fichier:** `src/knowbase/api/validators.py`

Validation complète contre SQL injection, XSS, path traversal, etc.

---

### 4. Rate Limiting Global ✅

**Fichier:** `src/knowbase/api/main.py:36`

```python
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
```

---

### 5. RBAC (Role-Based Access Control) ✅

**Fichier:** `src/knowbase/api/dependencies.py:74-166`

Implémentation complète de RBAC avec rôles admin/editor/viewer.

---

### 6. Multi-Tenancy ✅

**Fichier:** `src/knowbase/api/dependencies.py:168-191`

Isolation des données par tenant_id dans les JWT tokens.

---

### 7. Audit Logging ✅

**Fichier:** `src/knowbase/db/models.py:548-639`

Table `AuditLog` pour tracer les actions sensibles.

---

### 8. Log Sanitization ✅

**Fichier:** `src/knowbase/common/log_sanitizer.py`

Fonctions complètes de sanitization des logs (à utiliser systématiquement).

---

## 📊 Analyse des Dépendances

### Dépendances avec Vulnérabilités Potentielles

**Fichier:** `app/requirements.txt`

| Package | Version | Vulnérabilités Connues | Recommandation |
|---------|---------|------------------------|----------------|
| PyJWT | 2.9.0 | ⚠️ Vérifier CVE récents | Mettre à jour si CVE |
| fastapi | 0.116.1 | ✅ Pas de CVE critiques connues | OK |
| pdfminer.six | 20231228 | ⚠️ Vulnérabilités parsing PDF | Mettre à jour |
| PyMuPDF | >=1.23.0 | ⚠️ Vulnérabilités parsing PDF | Mettre à jour |
| unstructured | 0.15.0 | ⚠️ Dépendances lourdes | Auditer régulièrement |

**Recommandations:**
1. ✅ **Activer Dependabot** sur GitHub pour scanning automatique
2. ✅ **Utiliser `pip-audit`** dans CI/CD:
```bash
pip install pip-audit
pip-audit --desc
```
3. ✅ **Scanner avec Snyk**:
```bash
snyk test --file=app/requirements.txt
```

---

## 🐳 Durcissement Docker

### Recommandations de Configuration

**Fichier:** `docker-compose.yml`

```yaml
version: '3.8'

services:
  qdrant:
    image: qdrant/qdrant:v1.15.1
    container_name: knowbase-qdrant
    ports:
      - "127.0.0.1:6333:6333"  # ✅ Bind sur localhost uniquement
    environment:
      - QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY}  # ✅ Authentification
    networks:
      - knowbase_internal  # ✅ Network privé
    user: "1000:1000"  # ✅ Run as non-root
    read_only: true  # ✅ Filesystem read-only
    security_opt:
      - no-new-privileges:true  # ✅ Empêcher escalade privilèges
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE

  redis:
    image: redis:7.2
    container_name: knowbase-redis
    ports:
      - "127.0.0.1:6379:6379"  # ✅ Bind sur localhost uniquement
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}  # ✅ Authentification
      --appendonly yes
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
    networks:
      - knowbase_internal
    user: "999:999"  # ✅ Run as redis user
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true

  app:
    build:
      context: .
      dockerfile: ./app/Dockerfile
    image: sap-kb-app:latest
    container_name: knowbase-app
    environment:
      PYTHONPATH: /app:/app/src
      # ✅ Ne pas exposer DEBUG_APP en production
    ports:
      - "127.0.0.1:8000:8000"  # ✅ Bind sur localhost uniquement
    networks:
      - knowbase_internal
    user: "1000:1000"  # ✅ Run as non-root
    read_only: true  # ✅ Filesystem read-only
    tmpfs:
      - /tmp
      - /app/.cache
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE

networks:
  knowbase_internal:
    driver: bridge
    internal: false  # Mettre true si pas besoin d'accès internet
    driver_opts:
      com.docker.network.bridge.name: knowbase_br0
    ipam:
      config:
        - subnet: 172.28.0.0/16
```

---

## 🔒 Plan de Durcissement Recommandé

### Phase 1: Critiques (Sprint 1 - 2 semaines)

1. ✅ **Protéger endpoint /register** (admin only ou désactiver)
2. ✅ **Ajouter authentification sur Qdrant, Redis, Neo4j**
3. ✅ **Implémenter validation de type MIME** pour uploads
4. ✅ **Ajouter rate limiting** sur endpoints auth
5. ✅ **Migrer secrets vers Secrets Manager**

### Phase 2: Moyennes (Sprint 2 - 2 semaines)

6. ✅ **Durcir configuration CORS**
7. ✅ **Ajouter headers de sécurité HTTP**
8. ✅ **Implémenter politique de complexité des mots de passe**
9. ✅ **Implémenter révocation de tokens JWT** (blacklist Redis)
10. ✅ **Désactiver Swagger en production**

### Phase 3: Améliorations (Sprint 3 - 2 semaines)

11. ✅ **Activer TLS/SSL** pour connexions DB
12. ✅ **Durcir configuration Docker** (non-root, read-only, etc.)
13. ✅ **Implémenter scanning automatique** des dépendances
14. ✅ **Ajouter tests de sécurité** dans CI/CD
15. ✅ **Implémenter monitoring de sécurité** (SIEM)

### Phase 4: Conformité & Audits (Continu)

16. ✅ **Pentest externe** par experts
17. ✅ **Audit de conformité** (RGPD, SOC2, ISO27001)
18. ✅ **Formation sécurité** pour développeurs
19. ✅ **Bug bounty program**
20. ✅ **Revue de code sécurité** systématique

---

## 🧪 Tests de Sécurité Recommandés

### Tests à Ajouter dans CI/CD

```python
# tests/security/test_authentication.py

def test_login_rate_limiting():
    """Vérifie que le rate limiting fonctionne sur /login."""
    for i in range(6):
        response = client.post("/api/auth/login", json={
            "email": "test@example.com",
            "password": "wrongpassword"
        })

    # 6ème requête doit être bloquée
    assert response.status_code == 429

def test_register_requires_admin():
    """Vérifie que /register nécessite authentification admin."""
    response = client.post("/api/auth/register", json={
        "email": "hacker@evil.com",
        "password": "password123",
        "role": "admin"
    })

    # Doit être refusé sans auth
    assert response.status_code == 401

def test_file_upload_validates_mime_type():
    """Vérifie que les uploads valident le type MIME."""
    # Créer fichier malveillant avec extension .xlsx
    malicious_file = ("malware.xlsx", b"MZ\x90\x00", "application/octet-stream")

    response = client.post(
        "/api/documents/upload-excel-qa",
        files={"file": malicious_file}
    )

    # Doit être rejeté
    assert response.status_code == 400
    assert "Type de fichier non autorisé" in response.json()["detail"]

def test_jwt_token_revocation():
    """Vérifie que les tokens révoqués sont refusés."""
    # Login
    login_response = client.post("/api/auth/login", json={
        "email": "test@example.com",
        "password": "password123"
    })
    token = login_response.json()["access_token"]

    # Révoquer token
    client.post("/api/auth/logout", headers={
        "Authorization": f"Bearer {token}"
    })

    # Utiliser token révoqué doit échouer
    response = client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {token}"
    })

    assert response.status_code == 401
    assert "Token révoqué" in response.json()["detail"]
```

---

## 📋 Checklist de Déploiement en Production

### Avant le Déploiement

- [ ] **Secrets**: Tous les secrets sont dans un Secrets Manager (pas de .env)
- [ ] **Auth**: Endpoint /register désactivé ou protégé admin only
- [ ] **DB**: Qdrant, Redis, Neo4j avec authentification forte
- [ ] **Docker**: Containers run as non-root avec read-only filesystem
- [ ] **TLS**: Toutes les connexions DB utilisent TLS/SSL
- [ ] **CORS**: Restricted aux domaines de production uniquement
- [ ] **Swagger**: Documentation API désactivée (/docs, /redoc, /openapi.json)
- [ ] **Headers**: Headers de sécurité HTTP activés
- [ ] **Logs**: Log sanitization utilisé partout
- [ ] **Rate Limiting**: Configuré sur tous les endpoints sensibles
- [ ] **File Uploads**: Validation MIME + limite taille + scan antivirus
- [ ] **Passwords**: Politique de complexité activée
- [ ] **Dependencies**: Scan de vulnérabilités passé (pip-audit, Snyk)
- [ ] **Tests**: Suite de tests de sécurité verte
- [ ] **Monitoring**: SIEM configuré pour alertes sécurité
- [ ] **Backup**: Backups chiffrés et testés
- [ ] **Incident Response**: Plan de réponse aux incidents documenté
- [ ] **Audit**: Logs d'audit activés et archivés

---

## 🎯 Scores de Sécurité

| Catégorie | Score Actuel | Score Cible | Delta |
|-----------|--------------|-------------|-------|
| Authentification | 6/10 ⚠️ | 9/10 ✅ | +3 |
| Autorisation | 7/10 ⚠️ | 9/10 ✅ | +2 |
| Validation des Entrées | 8/10 ✅ | 9/10 ✅ | +1 |
| Gestion des Secrets | 4/10 🔴 | 9/10 ✅ | +5 |
| Sécurité DB | 3/10 🔴 | 9/10 ✅ | +6 |
| Sécurité Docker | 5/10 ⚠️ | 9/10 ✅ | +4 |
| Upload de Fichiers | 4/10 🔴 | 9/10 ✅ | +5 |
| Headers HTTP | 3/10 🔴 | 9/10 ✅ | +6 |
| Logging | 7/10 ⚠️ | 9/10 ✅ | +2 |
| Dépendances | 6/10 ⚠️ | 9/10 ✅ | +3 |
| **GLOBAL** | **5.3/10** ⚠️ | **9.0/10** ✅ | **+3.7** |

---

## 📚 Références et Ressources

### Standards de Sécurité
- **OWASP Top 10 2021**: https://owasp.org/www-project-top-ten/
- **OWASP API Security Top 10**: https://owasp.org/www-project-api-security/
- **CWE Top 25**: https://cwe.mitre.org/top25/

### Outils Recommandés
- **Bandit**: Static analysis pour Python - `pip install bandit`
- **Safety**: Check vulnérabilités dépendances - `pip install safety`
- **Snyk**: Scanning vulnérabilités - https://snyk.io
- **OWASP ZAP**: Pentest automatisé - https://www.zaproxy.org/
- **Trivy**: Scanner Docker images - https://aquasecurity.github.io/trivy/

### Documentation FastAPI Sécurité
- **FastAPI Security**: https://fastapi.tiangolo.com/tutorial/security/
- **JWT Best Practices**: https://datatracker.ietf.org/doc/html/rfc8725

---

## 🔚 Conclusion

L'application **KnowWhere/OSMOSE** présente une base de sécurité correcte avec plusieurs bonnes pratiques implémentées (JWT RS256, RBAC, validation des entrées). Cependant, **5 vulnérabilités critiques** nécessitent une attention immédiate avant tout déploiement en production, notamment:

1. Endpoint d'inscription public non protégé
2. Bases de données sans authentification forte
3. Validation de type MIME insuffisante pour les uploads
4. Pas de rate limiting sur les endpoints d'auth
5. Secrets stockés en clair

Le **plan de durcissement en 4 phases** proposé permettra d'atteindre un score de sécurité de **9/10** en 6 semaines environ, rendant l'application prête pour un déploiement en production sécurisé.

**Priorité absolue:** Implémenter les corrections des vulnérabilités critiques (Phase 1) avant tout déploiement.

---

**Rapport généré le:** 2025-10-22
**Version:** 1.0
**Confidentialité:** Interne
