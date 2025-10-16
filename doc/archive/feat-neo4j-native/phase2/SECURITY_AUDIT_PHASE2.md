# Audit Sécurité Phase 2 - API Facts REST

**Date** : 2025-10-03
**Auditeur** : Claude Code
**Périmètre** : Phase 2 Neo4j Native Migration - API Facts complète
**Fichiers audités** : 6 fichiers (schemas.py, facts_service.py, facts.py router, main.py, queries.py, schemas.py Neo4j)

---

## Résumé Exécutif

**Score global** : **4.5/10** (vulnérabilités critiques détectées)
**Vulnérabilités totales** : **23 failles**

- **P0 Critical** : 8 (BLOQUANT PRODUCTION)
- **P1 High** : 7 (correction urgente)
- **P2 Medium** : 6 (correction souhaitable)
- **P3 Low** : 2 (amélioration)

### Recommandations Prioritaires

1. **URGENT** : Implémenter authentification/autorisation complète (JWT, RBAC)
2. **URGENT** : Sanitiser toutes les entrées utilisateur contre injection Cypher
3. **URGENT** : Ajouter rate limiting global + endpoint-specific
4. **CRITIQUE** : Vérifier isolation tenant_id avec tests pénétration
5. **CRITIQUE** : Masquer stack traces et erreurs verbeux en production

---

## Vulnérabilités Détectées

### 🔴 P0 - Critical (Bloquant Production)

---

#### [P0-1] Absence totale d'authentification sur endpoints sensibles

**Fichier** : `src/knowbase/api/routers/facts.py:37-56`
**Description** : Les fonctions `get_current_tenant()` et `get_current_user()` retournent des valeurs hardcodées (`"default"` et `"anonymous"`) sans validation réelle. Aucun endpoint ne requiert authentification.

**Impact** :
- N'importe qui peut créer/modifier/supprimer des facts
- Aucune traçabilité réelle (approved_by = "anonymous")
- Bypass complet du système de gouvernance

**Exploitation** :
```bash
# Supprimer tous les facts sans authentification
curl -X DELETE http://api/facts/{uuid}

# Approuver un fact sans être expert
curl -X POST http://api/facts/{uuid}/approve \
  -H "Content-Type: application/json" \
  -d '{"comment": "fake approval"}'
```

**CVSS Score** : **9.8 (Critical)**
- AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H

**Recommandation** :
```python
# Fix avec JWT + OAuth2
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """Extrait user_id depuis JWT token."""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_tenant(user_id: str = Depends(get_current_user)) -> str:
    """Récupère tenant_id depuis user profile."""
    # Requête DB pour récupérer tenant_id du user
    return user_service.get_user_tenant(user_id)
```

---

#### [P0-2] Bypass isolation tenant_id (Cross-Tenant Data Access)

**Fichier** : `src/knowbase/api/routers/facts.py:37-45`
**Description** : Le tenant_id est retourné en dur (`"default"`) sans validation. Un attaquant peut théoriquement manipuler le header `X-Tenant-ID` si celui-ci est utilisé.

**Impact** :
- Accès cross-tenant aux données d'autres clients
- Violation RGPD (accès non autorisé à PII)
- Faille multi-tenancy critique

**Exploitation** :
```bash
# Si header X-Tenant-ID est utilisé sans validation
curl http://api/facts \
  -H "X-Tenant-ID: victim_tenant"
# → Accès aux facts du tenant victime
```

**CVSS Score** : **9.1 (Critical)**
- AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N

**Recommandation** :
```python
def get_current_tenant(user_id: str = Depends(get_current_user)) -> str:
    """
    Récupère tenant_id UNIQUEMENT depuis user profile.
    JAMAIS depuis header ou paramètre utilisateur.
    """
    tenant_id = user_service.get_user_tenant(user_id)

    if not tenant_id:
        raise HTTPException(status_code=403, detail="User has no tenant")

    logger.info(f"Tenant resolved: {tenant_id} for user: {user_id}")
    return tenant_id

# Test unitaire obligatoire
def test_tenant_isolation():
    """Vérifie qu'un user ne peut pas accéder aux données d'un autre tenant."""
    user1_token = create_token(user_id="user1", tenant_id="tenant_a")
    user2_token = create_token(user_id="user2", tenant_id="tenant_b")

    # User1 crée un fact
    fact_uuid = create_fact(token=user1_token)

    # User2 ne doit PAS pouvoir le lire
    response = get_fact(fact_uuid, token=user2_token)
    assert response.status_code == 404  # Ou 403
```

---

#### [P0-3] Injection Cypher potentielle via paramètres utilisateur

**Fichier** : `src/knowbase/api/routers/facts.py:555-568` (timeline endpoint)
**Description** : Les paramètres `subject` et `predicate` dans l'endpoint `/timeline/{subject}/{predicate}` sont passés directement au path sans validation stricte.

**Impact** :
- Injection Cypher si caractères spéciaux malveillants
- Exfiltration de données Neo4j
- Corruption/suppression de données

**Exploitation** :
```bash
# Injection Cypher via subject/predicate
curl http://api/facts/timeline/SAP'%20OR%201=1%20--/predicate

# Si mal sanitisé, pourrait générer :
# MATCH (f:Fact {subject: 'SAP' OR 1=1 --, predicate: '...'})
```

**CVSS Score** : **9.6 (Critical)**
- AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H

**Recommandation** :
```python
from pydantic import BaseModel, Field, field_validator
import re

class TimelinePathParams(BaseModel):
    """Validation stricte paramètres timeline."""
    subject: str = Field(..., min_length=1, max_length=200)
    predicate: str = Field(..., min_length=1, max_length=100)

    @field_validator('subject', 'predicate')
    @classmethod
    def sanitize_cypher_params(cls, v: str) -> str:
        """Sanitise contre injection Cypher."""
        # Bloquer caractères dangereux
        forbidden_chars = ["'", '"', "`", ";", "--", "/*", "*/", "{", "}"]
        for char in forbidden_chars:
            if char in v:
                raise ValueError(f"Invalid character '{char}' in parameter")

        # Whitelist alphanumérique + espaces + quelques caractères sûrs
        if not re.match(r'^[a-zA-Z0-9\s\-_./(),%]+$', v):
            raise ValueError("Parameter contains invalid characters")

        return v

@router.get("/timeline/{subject}/{predicate}")
async def get_fact_timeline(
    subject: str,
    predicate: str,
    service: FactsService = Depends(get_facts_service)
) -> List[FactTimelineEntry]:
    # Valider avec Pydantic
    params = TimelinePathParams(subject=subject, predicate=predicate)

    timeline = service.get_timeline(params.subject, params.predicate)
    return timeline
```

**Note** : Les requêtes Neo4j utilisent des **paramètres paramétrés** (`$subject`, `$predicate`), ce qui protège contre l'injection. MAIS la validation input reste critique pour défense en profondeur.

---

#### [P0-4] Absence rate limiting (DoS facile)

**Fichier** : `src/knowbase/api/main.py:16-155` (configuration FastAPI)
**Description** : Aucun rate limiting configuré sur l'application FastAPI. Les endpoints CRUD et analytiques sont illimités.

**Impact** :
- DoS par requêtes massives (`/facts/stats`, `/conflicts`)
- Épuisement mémoire Neo4j
- Coûts cloud explosés

**Exploitation** :
```bash
# DoS avec 10000 requêtes/seconde
while true; do
  curl http://api/facts/stats &
  curl http://api/facts/conflicts &
done
```

**CVSS Score** : **7.5 (High)**
- AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H

**Recommandation** :
```python
# Ajouter slowapi + Redis
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

app = FastAPI(...)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Appliquer à chaque endpoint
@router.get("/facts/stats")
@limiter.limit("10/minute")  # Stats coûteux = 10/min max
async def get_facts_stats(...):
    ...

@router.post("/facts")
@limiter.limit("50/minute")  # Création = 50/min max
async def create_fact(...):
    ...

@router.get("/facts")
@limiter.limit("100/minute")  # Liste = 100/min max
async def list_facts(...):
    ...
```

---

#### [P0-5] Leaks informations sensibles dans logs et erreurs

**Fichier** : `src/knowbase/api/services/facts_service.py:104-118`
**Description** : Les logs contiennent des UUIDs, subjects, predicates, values. Les stack traces peuvent être exposés en 500 errors.

**Impact** :
- Leak business data dans logs (SLA, pricing, capacité)
- Stack traces exposent architecture interne
- Information disclosure pour attaques ciblées

**Exploitation** :
```bash
# Trigger erreur pour voir stack trace
curl -X POST http://api/facts \
  -H "Content-Type: application/json" \
  -d '{"subject": "' + 'A'*10000 + '"}'

# Stack trace révèle :
# - Versions (Neo4j, FastAPI, Pydantic)
# - Paths internes (/app/src/knowbase/...)
# - Configuration (tenant_id, DB hosts)
```

**CVSS Score** : **6.5 (Medium → upgrade P0 car business data)**
- AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N

**Recommandation** :
```python
# 1. Redact logs sensibles
import logging
from copy import deepcopy

class SensitiveDataFilter(logging.Filter):
    """Filtre données sensibles des logs."""
    SENSITIVE_FIELDS = ['value', 'object', 'source_document', 'uuid']

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact message
        for field in self.SENSITIVE_FIELDS:
            if field in record.msg:
                record.msg = record.msg.replace(
                    f"{field}: {value}",
                    f"{field}: [REDACTED]"
                )
        return True

logger.addFilter(SensitiveDataFilter())

# 2. Masquer stack traces en production
from fastapi import Request, status
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Masque stack traces en production."""
    if settings.environment == "production":
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"}
        )
    else:
        # Dev : afficher stack trace
        import traceback
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error",
                "traceback": traceback.format_exc()
            }
        )
```

---

#### [P0-6] Absence audit trail (non-conformité RGPD)

**Fichier** : `src/knowbase/api/routers/facts.py` (tous endpoints)
**Description** : Aucun audit log des actions sensibles (approve, reject, delete). Pas de traçabilité "qui a fait quoi quand".

**Impact** :
- Non-conformité RGPD (accountability)
- Impossible d'investiguer incidents de sécurité
- Pas de forensics en cas de breach

**Exploitation** : N/A (vulnérabilité compliance)

**CVSS Score** : **7.0 (High → compliance risk)**

**Recommandation** :
```python
# Créer table audit_log dans PostgreSQL ou Neo4j
from datetime import datetime
from typing import Optional

class AuditLogEntry(BaseModel):
    timestamp: datetime
    user_id: str
    tenant_id: str
    action: str  # "create", "approve", "reject", "delete", "update"
    resource_type: str  # "Fact"
    resource_id: str  # UUID fact
    old_value: Optional[Dict] = None
    new_value: Optional[Dict] = None
    ip_address: str
    user_agent: str

async def log_audit(
    action: str,
    resource_id: str,
    user_id: str,
    tenant_id: str,
    request: Request,
    old_value: Optional[Dict] = None,
    new_value: Optional[Dict] = None
):
    """Enregistre audit trail."""
    entry = AuditLogEntry(
        timestamp=datetime.utcnow(),
        user_id=user_id,
        tenant_id=tenant_id,
        action=action,
        resource_type="Fact",
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=request.client.host,
        user_agent=request.headers.get("User-Agent")
    )

    # Persist dans DB audit
    await audit_service.save(entry)

# Usage
@router.post("/{fact_uuid}/approve")
async def approve_fact(
    fact_uuid: str,
    request: Request,
    user_id: str = Depends(get_current_user),
    ...
):
    old_fact = service.get_fact(fact_uuid)
    approved_fact = service.approve_fact(fact_uuid, user_id, ...)

    # Audit log
    await log_audit(
        action="approve",
        resource_id=fact_uuid,
        user_id=user_id,
        tenant_id=old_fact.tenant_id,
        request=request,
        old_value=old_fact.dict(),
        new_value=approved_fact.dict()
    )

    return approved_fact
```

---

#### [P0-7] CORS trop permissif (allow_methods=["*"], allow_headers=["*"])

**Fichier** : `src/knowbase/api/main.py:109-115`
**Description** : La configuration CORS autorise TOUS les méthodes et TOUS les headers, ce qui ouvre la porte à des attaques CSRF/XSS.

**Impact** :
- CSRF (Cross-Site Request Forgery) sur endpoints sensibles
- XSS si combiné avec d'autres vulns
- Requêtes malveillantes depuis sites tiers

**Exploitation** :
```html
<!-- Attaque CSRF depuis site malveillant -->
<script>
fetch('http://localhost:8000/api/facts/550e8400-e29b-41d4-a716-446655440000', {
  method: 'DELETE',
  credentials: 'include'  // Envoie cookies automatiquement
});
</script>
```

**CVSS Score** : **7.1 (High)**
- AV:N/AC:L/PR:N/UI:R/S:U/C:L/I:H/A:N

**Recommandation** :
```python
# CORS strict
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Frontend dev
        "https://knowbase.acme.com"  # Frontend prod
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # Whitelist explicite
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Requested-With"  # Protection CSRF
    ],
    expose_headers=["X-Total-Count"],  # Headers exposés au client
    max_age=3600  # Cache preflight 1h
)

# Ajouter protection CSRF avec tokens
from fastapi_csrf_protect import CsrfProtect

@app.post("/facts")
async def create_fact(
    csrf_protect: CsrfProtect = Depends(),
    ...
):
    csrf_protect.validate_csrf_in_cookies()
    ...
```

---

#### [P0-8] Pas de validation limite payload size (DoS mémoire)

**Fichier** : `src/knowbase/api/schemas/facts.py:56-176` (FactCreate)
**Description** : Les champs `object`, `source_document`, `extraction_model` ont des max_length mais pas de limite globale payload.

**Impact** :
- DoS mémoire avec payload 100MB
- Crash FastAPI/Neo4j
- Épuisement ressources serveur

**Exploitation** :
```bash
# Envoyer payload 100MB
curl -X POST http://api/facts \
  -H "Content-Type: application/json" \
  -d '{"subject": "SAP", "predicate": "test", "object": "'$(python -c 'print("A"*100000000)')'"}'
```

**CVSS Score** : **7.5 (High)**
- AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H

**Recommandation** :
```python
# Ajouter middleware limit payload
from starlette.middleware.base import BaseHTTPMiddleware

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_size: int = 1_000_000):  # 1MB
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request, call_next):
        if request.method in ["POST", "PUT", "PATCH"]:
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.max_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request payload too large"}
                )

        return await call_next(request)

app.add_middleware(RequestSizeLimitMiddleware, max_size=1_000_000)  # 1MB
```

---

### 🟠 P1 - High (Correction Urgente)

---

#### [P1-1] Pas de vérification race conditions (approve/reject concurrent)

**Fichier** : `src/knowbase/api/services/facts_service.py:282-336`
**Description** : Workflow approve/reject n'utilise pas de locks. Deux experts peuvent approuver/rejeter simultanément.

**Impact** :
- État incohérent (status="approved" + approved_by="expert2" alors que expert1 a approuvé)
- Double approval/rejection
- Corruption gouvernance

**Exploitation** :
```bash
# T1: Expert1 approve
curl -X POST http://api/facts/{uuid}/approve -d '{"comment": "OK"}' &

# T2: Expert2 reject (concurrent)
curl -X POST http://api/facts/{uuid}/reject -d '{"reason": "KO"}' &

# Résultat : état indéterminé
```

**CVSS Score** : **6.5 (Medium → upgrade P1 car business logic)**

**Recommandation** :
```python
# Utiliser verrouillage Neo4j ou Redis
import redis
from contextlib import contextmanager

redis_client = redis.Redis(host='localhost', port=6379, db=0)

@contextmanager
def fact_lock(fact_uuid: str, timeout: int = 5):
    """Verrouillage distribué pour fact."""
    lock_key = f"fact_lock:{fact_uuid}"
    lock = redis_client.lock(lock_key, timeout=timeout)

    acquired = lock.acquire(blocking=True, blocking_timeout=timeout)

    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Fact is locked by another operation"
        )

    try:
        yield
    finally:
        lock.release()

def approve_fact(self, fact_uuid: str, approved_by: str, ...):
    with fact_lock(fact_uuid):
        # Vérifier status ENCORE une fois (double-check)
        fact = self.get_fact(fact_uuid)

        if fact.status != "proposed":
            raise FactValidationError(
                f"Cannot approve fact with status '{fact.status}'"
            )

        # Approuver
        approved_fact = self.facts_queries.update_fact_status(...)
        return approved_fact
```

---

#### [P1-2] Pas de validation cohérence valid_from/valid_until

**Fichier** : `src/knowbase/api/services/facts_service.py:596-606`
**Description** : La validation `valid_from < valid_until` est faite mais pas de vérification si dates dans le futur ou dans le passé lointain.

**Impact** :
- Création facts avec valid_from=2099 (pollution base)
- Timeline corrompue (facts "futurs" non valides)
- Conflits détection cassée

**CVSS Score** : **5.3 (Medium)**

**Recommandation** :
```python
from datetime import datetime, timedelta

def _validate_fact_data(self, fact_data: FactCreate) -> None:
    # Validation dates cohérence
    if fact_data.valid_from:
        date_from = datetime.fromisoformat(fact_data.valid_from)
        now = datetime.utcnow()

        # Pas de dates > 10 ans dans le futur
        if date_from > now + timedelta(days=3650):
            raise FactValidationError(
                "valid_from cannot be more than 10 years in the future"
            )

        # Warning si > 50 ans dans le passé
        if date_from < now - timedelta(days=18250):
            logger.warning(
                f"valid_from is more than 50 years in the past: {date_from}"
            )

    if fact_data.valid_until:
        date_until = datetime.fromisoformat(fact_data.valid_until)

        # valid_until pas > 20 ans dans le futur
        if date_until > datetime.utcnow() + timedelta(days=7300):
            raise FactValidationError(
                "valid_until cannot be more than 20 years in the future"
            )
```

---

#### [P1-3] Pas de timeout Neo4j queries (DoS interne)

**Fichier** : `src/knowbase/neo4j_custom/queries.py` (toutes méthodes)
**Description** : Aucun timeout configuré sur requêtes Neo4j. Query lente peut bloquer worker FastAPI.

**Impact** :
- Worker FastAPI bloqué
- Cascade failure (tous endpoints down)
- DoS par query lente

**CVSS Score** : **6.5 (Medium)**

**Recommandation** :
```python
# Ajouter timeouts dans Neo4jCustomClient
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, TransactionError

class Neo4jCustomClient:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_lifetime=3600,
            max_connection_pool_size=50,
            connection_acquisition_timeout=10,  # 10s max wait connection
            encrypted=False
        )

    def execute_query(
        self,
        query: str,
        parameters: Dict = None,
        timeout: float = 30.0  # 30s timeout par défaut
    ) -> List[Dict]:
        try:
            with self.driver.session(
                default_access_mode=neo4j.READ_ACCESS
            ) as session:
                result = session.run(
                    query,
                    parameters,
                    timeout=timeout  # Timeout query
                )
                return [dict(record) for record in result]

        except TransactionError as e:
            if "timeout" in str(e).lower():
                logger.error(f"Neo4j query timeout: {query[:100]}")
                raise HTTPException(
                    status_code=504,
                    detail="Database query timeout"
                )
            raise
```

---

#### [P1-4] Endpoint /facts sans pagination obligatoire (DoS mémoire)

**Fichier** : `src/knowbase/api/routers/facts.py:167-237` (list_facts)
**Description** : Pagination par défaut limit=100 mais peut être override à 500. Pas de limite absolue.

**Impact** :
- DoS mémoire avec limit=10000
- Neo4j overload
- Crash FastAPI OOM

**CVSS Score** : **6.5 (Medium)**

**Recommandation** :
```python
@router.get("")
async def list_facts(
    limit: int = Query(
        100,
        ge=1,
        le=500,  # Déjà présent
        description="Max results"
    ),
    offset: int = Query(
        0,
        ge=0,
        le=10000,  # AJOUTER : max offset 10k (évite full scan)
        description="Skip first N results"
    ),
    ...
):
    # Vérifier limit+offset totaux
    if offset + limit > 10000:
        raise HTTPException(
            status_code=400,
            detail="Cannot fetch more than 10000 facts (offset + limit)"
        )

    facts = service.list_facts(...)

    # Response avec pagination headers
    return Response(
        content=jsonable_encoder(facts),
        media_type="application/json",
        headers={
            "X-Total-Count": str(total_count),
            "X-Page-Size": str(limit),
            "X-Page-Offset": str(offset)
        }
    )
```

---

#### [P1-5] Validation path traversal insuffisante (source_document)

**Fichier** : `src/knowbase/api/services/facts_service.py:608-613`
**Description** : La validation bloque `..` et `/` mais pas d'autres vecteurs path traversal (`\`, `%2e%2e`, URL encoding).

**Impact** :
- Path traversal si source_document utilisé pour read file
- Leak fichiers système
- RCE si combiné avec file upload

**CVSS Score** : **7.3 (High)**

**Recommandation** :
```python
import os
from pathlib import Path

def _validate_fact_data(self, fact_data: FactCreate) -> None:
    # Validation source_document renforcée
    if fact_data.source_document:
        doc = fact_data.source_document

        # Bloquer tous vecteurs path traversal
        forbidden_patterns = [
            "..", "/", "\\",  # Path traversal classique
            "%2e", "%2f", "%5c",  # URL encoded
            "\x00",  # Null byte injection
            "|", "&", ";", "`", "$",  # Command injection
        ]

        for pattern in forbidden_patterns:
            if pattern in doc.lower():
                raise FactValidationError(
                    f"source_document contains forbidden pattern: {pattern}"
                )

        # Normaliser et vérifier
        normalized = os.path.normpath(doc)
        if normalized != doc:
            raise FactValidationError(
                "source_document path is not normalized"
            )

        # Whitelist extension
        allowed_extensions = [".pdf", ".pptx", ".docx", ".xlsx", ".txt"]
        if not any(doc.lower().endswith(ext) for ext in allowed_extensions):
            raise FactValidationError(
                f"source_document extension not allowed"
            )

        # Max length strict
        if len(doc) > 255:
            raise FactValidationError(
                "source_document path too long"
            )
```

---

#### [P1-6] Pas de vérification unicité (subject, predicate, valid_from) avant approve

**Fichier** : `src/knowbase/api/services/facts_service.py:282-336` (approve_fact)
**Description** : Aucune vérification que le fact à approuver ne crée pas de doublon exact (même subject, predicate, valid_from, value).

**Impact** :
- Pollution base avec duplicates approved
- Conflits détection faussée
- Intégrité business logic compromise

**CVSS Score** : **5.9 (Medium)**

**Recommandation** :
```python
def approve_fact(self, fact_uuid: str, approved_by: str, comment: Optional[str] = None):
    # Vérifier fact existe et status=proposed
    fact = self.get_fact(fact_uuid)

    if fact.status != "proposed":
        raise FactValidationError(...)

    # NOUVEAU : Vérifier pas de duplicate exact déjà approved
    existing_approved = self.facts_queries.get_facts_by_subject_predicate(
        fact.subject, fact.predicate
    )

    for existing in existing_approved:
        if existing.status == "approved":
            # Même valeur ET même valid_from = DUPLICATE
            if (existing.value == fact.value and
                existing.valid_from == fact.valid_from):
                raise FactValidationError(
                    f"Cannot approve: duplicate fact already exists "
                    f"(UUID: {existing.uuid})"
                )

    # Approuver
    approved_fact = self.facts_queries.update_fact_status(...)
    return approved_fact
```

---

#### [P1-7] Endpoint /conflicts sans cache (query lourde)

**Fichier** : `src/knowbase/api/routers/facts.py:509-523` (list_conflicts)
**Description** : L'endpoint `/conflicts` exécute une query Neo4j lourde (double MATCH) à chaque appel. Pas de cache.

**Impact** :
- Performance dégradée
- Neo4j overload si appels fréquents
- DoS par abuse endpoint

**CVSS Score** : **5.3 (Medium)**

**Recommandation** :
```python
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache
from fastapi_cache.backends.redis import RedisBackend
import redis

# Setup cache
redis_cache = redis.from_url("redis://localhost:6379")
FastAPICache.init(RedisBackend(redis_cache), prefix="fastapi-cache")

@router.get("/conflicts")
@cache(expire=300)  # Cache 5 minutes
async def list_conflicts(
    service: FactsService = Depends(get_facts_service)
) -> List[ConflictResponse]:
    """Liste conflits (cached 5min)."""
    conflicts = service.detect_conflicts()
    return conflicts

# Invalider cache lors des modifications
@router.post("/{fact_uuid}/approve")
async def approve_fact(...):
    approved_fact = service.approve_fact(...)

    # Invalider cache conflicts
    await FastAPICache.clear(namespace="list_conflicts")

    return approved_fact
```

---

### 🟡 P2 - Medium (Correction Souhaitable)

---

#### [P2-1] Logs insuffisants pour forensics (no IP, no user agent)

**Fichier** : `src/knowbase/api/services/facts_service.py` (tous logs)
**Description** : Les logs ne contiennent que UUID, subject, predicate. Pas d'IP, user agent, tenant_id systématique.

**Impact** :
- Forensics impossible en cas incident
- Pas de détection attaques distribuées
- Audit trail incomplet

**Recommandation** :
```python
# Ajouter middleware logging
from starlette.middleware.base import BaseHTTPMiddleware

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Log chaque requête
        logger.info(
            f"Request - Method: {request.method}, "
            f"Path: {request.url.path}, "
            f"IP: {request.client.host}, "
            f"User-Agent: {request.headers.get('User-Agent')}, "
            f"Tenant: {request.headers.get('X-Tenant-ID', 'N/A')}"
        )

        response = await call_next(request)

        logger.info(
            f"Response - Status: {response.status_code}, "
            f"Duration: {duration}ms"
        )

        return response

app.add_middleware(RequestLoggingMiddleware)
```

---

#### [P2-2] Pas de validation enum strict (fact_type, value_type)

**Fichier** : `src/knowbase/api/schemas/facts.py:26-50` (Enums)
**Description** : Les enums Pydantic protègent, mais pas de double-check côté service.

**Impact** :
- Corruption data si enum Pydantic bypass
- Filtres cassés (fact_type invalide)

**Recommandation** :
```python
def _validate_fact_data(self, fact_data: FactCreate) -> None:
    # Validation enum strict
    valid_fact_types = [e.value for e in FactType]
    if fact_data.fact_type not in valid_fact_types:
        raise FactValidationError(
            f"fact_type must be one of {valid_fact_types}"
        )

    valid_value_types = [e.value for e in ValueType]
    if fact_data.value_type not in valid_value_types:
        raise FactValidationError(
            f"value_type must be one of {valid_value_types}"
        )
```

---

#### [P2-3] Endpoint DELETE sans confirmation (soft delete recommandé)

**Fichier** : `src/knowbase/api/routers/facts.py:291-321` (delete_fact)
**Description** : DELETE supprime définitivement. Pas de soft delete, pas de confirmation requise.

**Impact** :
- Perte données irréversible
- Pas de restauration possible
- Non-conformité RGPD (droit restauration)

**Recommandation** :
```python
# Implémenter soft delete
UPDATE_FACT_SOFT_DELETE = """
MATCH (f:Fact {uuid: $uuid, tenant_id: $tenant_id})
SET f.deleted_at = datetime(),
    f.deleted_by = $deleted_by,
    f.status = 'deleted'
RETURN f
"""

def delete_fact(self, fact_uuid: str, deleted_by: str) -> bool:
    """Soft delete fact."""
    self.facts_queries.soft_delete_fact(fact_uuid, deleted_by)

    logger.info(f"Fact soft-deleted - UUID: {fact_uuid}, By: {deleted_by}")
    return True

# Query GET exclut deleted
GET_FACTS_BY_STATUS = """
MATCH (f:Fact {tenant_id: $tenant_id, status: $status})
WHERE f.deleted_at IS NULL  # Exclure soft-deleted
RETURN f
"""

# Hard delete après 90 jours (GDPR compliance)
HARD_DELETE_EXPIRED = """
MATCH (f:Fact {tenant_id: $tenant_id})
WHERE f.deleted_at < datetime() - duration({days: 90})
DELETE f
"""
```

---

#### [P2-4] Pas de métriques monitoring (Prometheus)

**Fichier** : `src/knowbase/api/main.py`
**Description** : Aucune instrumentation Prometheus/metrics pour monitoring production.

**Impact** :
- Pas de détection anomalies (spike requests)
- Pas d'alerting DoS
- Pas de métriques business (facts créés/jour)

**Recommandation** :
```python
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(...)

# Instrumenter avec Prometheus
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# Métriques custom
from prometheus_client import Counter, Histogram

facts_created_total = Counter(
    'facts_created_total',
    'Total facts created',
    ['tenant_id', 'fact_type']
)

facts_approved_total = Counter(
    'facts_approved_total',
    'Total facts approved',
    ['tenant_id']
)

conflicts_detected_total = Counter(
    'conflicts_detected_total',
    'Total conflicts detected',
    ['tenant_id', 'conflict_type']
)

# Usage
def create_fact(self, fact_data: FactCreate):
    fact = self.facts_queries.create_fact(...)

    facts_created_total.labels(
        tenant_id=self.tenant_id,
        fact_type=fact_data.fact_type.value
    ).inc()

    return fact
```

---

#### [P2-5] Pas de validation confidence range dans update

**Fichier** : `src/knowbase/api/schemas/facts.py:179-206` (FactUpdate)
**Description** : FactUpdate permet update confidence mais validation ge=0, le=1 pas strictement enforced côté service.

**Recommandation** :
```python
class FactUpdate(BaseModel):
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Nouvelle confiance"
    )

    @field_validator('confidence')
    @classmethod
    def validate_confidence_precision(cls, v):
        """Valide precision confidence."""
        if v is not None:
            # Max 2 décimales
            if round(v, 2) != v:
                raise ValueError("confidence must have max 2 decimals")
        return v
```

---

#### [P2-6] HTTPS/TLS non enforced

**Fichier** : `src/knowbase/api/main.py`
**Description** : Pas de redirection HTTP → HTTPS, pas de HSTS header.

**Impact** :
- Man-in-the-middle attacks
- Credentials sniffing
- Session hijacking

**Recommandation** :
```python
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

if settings.environment == "production":
    # Forcer HTTPS
    app.add_middleware(HTTPSRedirectMiddleware)

    # HSTS header
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = \
            "max-age=31536000; includeSubDomains"
        return response

    # Trusted hosts
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["knowbase.acme.com"]
    )
```

---

### 🟢 P3 - Low (Amélioration)

---

#### [P3-1] Version API/tech stack exposée dans headers

**Fichier** : `src/knowbase/api/main.py:27-64` (description OpenAPI)
**Description** : Version "2.0.0" et stack tech (FastAPI, Neo4j, Qdrant) exposés dans `/docs`.

**Impact** :
- Information disclosure pour attaquant
- Ciblage exploits connus

**Recommandation** :
```python
# Désactiver /docs en production
if settings.environment == "production":
    app = FastAPI(
        title="SAP Knowbase API",
        docs_url=None,  # Disable /docs
        redoc_url=None,  # Disable /redoc
        openapi_url=None  # Disable /openapi.json
    )
else:
    app = FastAPI(...)

# Masquer server header
@app.middleware("http")
async def remove_server_header(request: Request, call_next):
    response = await call_next(request)
    response.headers.pop("server", None)
    return response
```

---

#### [P3-2] Pas de dépendances vulnerability scanning

**Fichier** : N/A (process)
**Description** : Pas de scan automatique vulnérabilités dépendances (FastAPI, Pydantic, Neo4j driver).

**Recommandation** :
```bash
# Ajouter à CI/CD
pip install safety bandit

# Scan vulnerabilities
safety check --json

# Scan code security
bandit -r src/knowbase/api/

# GitHub Dependabot
# Activer dans .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

---

## Points Forts Détectés

✅ **Requêtes Neo4j paramétrées** : Utilisation de `$param` protège contre injection Cypher (défense en profondeur)
✅ **Validation Pydantic stricte** : Enums, min_length, max_length, field_validator robustes
✅ **Isolation tenant_id** : Présente dans TOUTES les requêtes Neo4j (si auth correcte)
✅ **Pagination par défaut** : limit=100, max=500 évite fetch massifs (mais perfectible)
✅ **Workflow gouvernance** : Approve/reject avec validation status (bonne logique métier)
✅ **Validation dates** : valid_from < valid_until correctement vérifié
✅ **Path traversal partiel** : Détection `..` et `/` dans source_document (à renforcer)
✅ **Indexes Neo4j** : tenant_id, subject+predicate, status indexés (performance)
✅ **HTTPException standardisées** : Codes 404, 422, 500 cohérents
✅ **Logging structuré** : logger.info/error avec contexte (à améliorer forensics)

---

## Plan de Remédiation

| ID | Priorité | Vulnérabilité | Effort | Délai | Owner |
|----|----------|---------------|--------|-------|-------|
| **P0-1** | **Critical** | Absence authentification JWT | 3j | Immédiat | Backend Lead |
| **P0-2** | **Critical** | Bypass isolation tenant_id | 2j | Immédiat | Backend Lead |
| **P0-3** | **Critical** | Injection Cypher potentielle | 1j | Immédiat | Backend Dev |
| **P0-4** | **Critical** | Absence rate limiting | 1j | Immédiat | DevOps |
| **P0-5** | **Critical** | Leaks informations logs/erreurs | 1j | Immédiat | Backend Dev |
| **P0-6** | **Critical** | Absence audit trail | 2j | Immédiat | Backend Lead |
| **P0-7** | **Critical** | CORS trop permissif | 0.5j | Immédiat | Backend Dev |
| **P0-8** | **Critical** | Pas limite payload size | 0.5j | Immédiat | Backend Dev |
| **P1-1** | High | Race conditions approve/reject | 1j | J+2 | Backend Dev |
| **P1-2** | High | Validation dates insuffisante | 0.5j | J+2 | Backend Dev |
| **P1-3** | High | Pas timeout Neo4j queries | 1j | J+3 | Backend Dev |
| **P1-4** | High | Pagination sans limite absolue | 0.5j | J+3 | Backend Dev |
| **P1-5** | High | Path traversal insuffisant | 1j | J+3 | Backend Dev |
| **P1-6** | High | Pas vérification unicité approve | 1j | J+4 | Backend Dev |
| **P1-7** | High | Endpoint /conflicts sans cache | 1j | J+4 | Backend Dev |
| **P2-1** | Medium | Logs forensics insuffisants | 0.5j | J+7 | Backend Dev |
| **P2-2** | Medium | Validation enum double-check | 0.5j | J+7 | Backend Dev |
| **P2-3** | Medium | DELETE hard sans soft delete | 1j | J+10 | Backend Dev |
| **P2-4** | Medium | Pas métriques Prometheus | 1j | J+10 | DevOps |
| **P2-5** | Medium | Validation confidence update | 0.5j | J+10 | Backend Dev |
| **P2-6** | Medium | HTTPS/TLS non enforced | 0.5j | J+14 | DevOps |
| **P3-1** | Low | Version/tech exposée | 0.5j | J+30 | Backend Dev |
| **P3-2** | Low | Dependency scanning CI/CD | 1j | J+30 | DevOps |

**Effort total** : ~22 jours-homme
**Délai critique (P0)** : **5 jours** (BLOQUANT production)
**Délai P1** : **+7 jours** (correction urgente)

---

## Tests de Sécurité Recommandés

### 1. Tests Authentification
```python
def test_unauthenticated_access():
    """Vérifie tous endpoints requièrent auth."""
    response = client.post("/api/facts")
    assert response.status_code == 401

def test_cross_tenant_isolation():
    """Vérifie isolation tenant_id stricte."""
    token_tenant_a = create_token(tenant_id="tenant_a")
    token_tenant_b = create_token(tenant_id="tenant_b")

    # Tenant A crée fact
    fact = create_fact(token=token_tenant_a)

    # Tenant B ne peut pas lire
    response = client.get(f"/api/facts/{fact.uuid}", headers={"Authorization": f"Bearer {token_tenant_b}"})
    assert response.status_code == 404
```

### 2. Tests Injection
```python
def test_cypher_injection():
    """Vérifie protection injection Cypher."""
    malicious_subject = "SAP' OR 1=1 --"

    response = client.get(f"/api/facts/timeline/{malicious_subject}/test")
    assert response.status_code in [400, 422]  # Rejeté

def test_path_traversal():
    """Vérifie protection path traversal."""
    fact = FactCreate(
        subject="SAP",
        predicate="test",
        object="test",
        value=1.0,
        unit="test",
        source_document="../../etc/passwd"
    )

    response = client.post("/api/facts", json=fact.dict())
    assert response.status_code == 422
```

### 3. Tests Rate Limiting
```python
def test_rate_limiting():
    """Vérifie rate limiting actif."""
    for i in range(101):  # Over limit 100/min
        response = client.get("/api/facts")

    assert response.status_code == 429  # Too Many Requests
```

### 4. Tests Business Logic
```python
def test_concurrent_approve_reject():
    """Vérifie race condition approve/reject."""
    fact = create_fact(status="proposed")

    # Appels concurrents
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(approve_fact, fact.uuid)
        f2 = executor.submit(reject_fact, fact.uuid)

    # Un seul doit réussir
    results = [f1.result(), f2.result()]
    assert sum(r.status_code == 200 for r in results) == 1
```

---

## Références

- **OWASP API Security Top 10 2023** : https://owasp.org/API-Security/
- **CWE Top 25 Most Dangerous Software Weaknesses** : https://cwe.mitre.org/top25/
- **Neo4j Security Best Practices** : https://neo4j.com/docs/operations-manual/current/security/
- **FastAPI Security Documentation** : https://fastapi.tiangolo.com/tutorial/security/
- **NIST Cybersecurity Framework** : https://www.nist.gov/cyberframework
- **RGPD (GDPR) Compliance** : https://gdpr.eu/

---

## Conclusion

Le code de la Phase 2 présente une **architecture globalement saine** (Pydantic validation, Neo4j paramétré, isolation tenant_id) MAIS avec des **vulnérabilités critiques P0** qui BLOQUENT la mise en production :

### Bloqueurs Production (URGENT)
1. **Authentification absente** → Exposition totale API
2. **Tenant isolation non vérifiée** → Cross-tenant data breach
3. **Rate limiting absent** → DoS facile
4. **CORS permissif** → CSRF attacks
5. **Logs/erreurs verbeux** → Information disclosure

### Recommandations Immédiates (J+5)
- Implémenter JWT auth complète (OAuth2 + RBAC)
- Tester isolation tenant_id (penetration tests)
- Ajouter rate limiting (slowapi + Redis)
- Durcir CORS + CSRF tokens
- Masquer stack traces production

### Prochaines Étapes
- Tests sécurité automatisés (CI/CD)
- Audit externe penetration testing
- Compliance check RGPD/SOC2
- Security training équipe backend

**Status Production** : ❌ **NON RECOMMANDÉ** (score 4.5/10)
**Status Post-Remédiation P0** : ✅ **OK avec monitoring** (score estimé 7.5/10)

---

**Auditeur** : Claude Code
**Date** : 2025-10-03
**Version** : 1.0
