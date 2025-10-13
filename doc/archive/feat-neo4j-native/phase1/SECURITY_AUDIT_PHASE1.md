# Audit Sécurité Phase 1 - Module Neo4j Custom

**Date** : 2025-10-03
**Scope** : Phase 1 - Module `neo4j_custom` (Facts governance)
**Fichiers analysés** :
- `src/knowbase/neo4j_custom/client.py`
- `src/knowbase/neo4j_custom/queries.py`
- `src/knowbase/neo4j_custom/schemas.py`
- `src/knowbase/neo4j_custom/migrations.py`
- `test_neo4j_poc.py`
- `.env` (configuration Neo4j)

**Sévérité** : 🔴 Critique | 🟠 Élevée | 🟡 Moyenne | 🟢 Faible

---

## 📋 Résumé Exécutif

**Failles identifiées** : 22 vulnérabilités
- 🔴 **Critiques (P0)** : 6
- 🟠 **Élevées (P1)** : 8
- 🟡 **Moyennes (P2)** : 6
- 🟢 **Faibles (P3)** : 2

**Score sécurité global** : **4.2/10** ⚠️ CRITIQUE

**Recommandation** : **Durcissement URGENT requis avant passage Phase 2**

**Points positifs** :
- ✅ Utilisation de paramètres Cypher (prévention injection partielle)
- ✅ Gestion d'erreurs basique
- ✅ Validation `tenant_id` présent dans queries

**Points critiques** :
- 🔴 Chiffrement désactivé (`encrypted: False`)
- 🔴 Credentials en variables d'environnement non sécurisées
- 🔴 Absence totale de RBAC (Role-Based Access Control)
- 🔴 Logs contenant données sensibles
- 🔴 Injection Cypher possible dans certains contextes
- 🔴 Pas d'audit trail

---

## 🔴 VULNÉRABILITÉS CRITIQUES (P0)

### SEC-PHASE1-01: Chiffrement TLS Désactivé 🔴

**Fichier** : `src/knowbase/neo4j_custom/client.py:81`

**Problème** :
```python
self._driver_config = {
    "max_connection_lifetime": max_connection_lifetime,
    "max_connection_pool_size": max_connection_pool_size,
    "connection_timeout": connection_timeout,
    "encrypted": False,  # ❌ True en production avec TLS
}
```

**Impact** :
- ✅ Credentials Neo4j transmis en clair sur le réseau (bolt://)
- ✅ Données Facts interceptables par attaquant (man-in-the-middle)
- ✅ Session hijacking possible
- ✅ Violation GDPR/compliance (données non chiffrées en transit)

**Scénario d'exploitation** :
```bash
# Attaquant sniffe trafic réseau
tcpdump -i eth0 -A 'port 7687'
# Capture:
# AUTH: user=neo4j password=neo4j_password
# QUERY: MATCH (f:Fact {tenant_id: 'acme'}) ...
```

**CVSS Score** : **9.1** (Critique)
- **Attack Vector** : Network
- **Attack Complexity** : Low
- **Privileges Required** : None
- **User Interaction** : None
- **Confidentiality** : High
- **Integrity** : High
- **Availability** : None

**Correctif** :

```python
# src/knowbase/neo4j_custom/client.py
self._driver_config = {
    "max_connection_lifetime": max_connection_lifetime,
    "max_connection_pool_size": max_connection_pool_size,
    "connection_timeout": connection_timeout,
    "encrypted": True,  # ✅ TLS obligatoire
    "trust": "TRUST_SYSTEM_CA_SIGNED_CERTIFICATES",  # ✅ Valider certificat
}

# .env
NEO4J_URI=neo4j+s://graphiti-neo4j:7687  # ✅ Protocole sécurisé
# ou
NEO4J_URI=bolt+s://graphiti-neo4j:7687   # ✅ Bolt avec TLS
```

**Configuration Neo4j** :
```yaml
# docker-compose.infra.yml
neo4j:
  environment:
    - NEO4J_dbms_connector_bolt_tls__level=REQUIRED
    - NEO4J_dbms_ssl_policy_bolt_enabled=true
  volumes:
    - ./certs:/var/lib/neo4j/certificates:ro  # Certificats TLS
```

**Priorité** : **P0 - URGENT** (à corriger avant Phase 2)

---

### SEC-PHASE1-02: Credentials Loggés en Clair 🔴

**Fichier** : `src/knowbase/neo4j_custom/client.py:84-87`

**Problème** :
```python
logger.info(
    f"Neo4jCustomClient initialized - URI: {self.uri}, "
    f"User: {self.user}, Database: {self.database}"
    # ❌ Username loggué (password non loggué mais risque)
)
```

**Impact** :
- ✅ Logs contiennent username Neo4j
- ✅ Logs contiennent URI complète (hostname, port)
- ✅ Information disclosure facilitant reconnaissance
- ✅ Risque de logger accidentellement password dans futures modifications

**Scénario d'exploitation** :
```python
# Attaquant accède aux logs
docker logs knowbase-app 2>&1 | grep "Neo4jCustomClient initialized"
# Capture:
# 2025-10-03 INFO Neo4jCustomClient initialized - URI: bolt://graphiti-neo4j:7687, User: neo4j, Database: neo4j
# → Attaquant connaît maintenant: hostname, port, username
```

**CVSS Score** : **7.5** (Élevé)

**Correctif** :

```python
# src/knowbase/neo4j_custom/client.py
logger.info(
    f"Neo4jCustomClient initialized - Database: {self.database}"
    # ✅ Pas d'URI, pas d'username
)

# Logs debug uniquement (jamais en production)
logger.debug(
    f"Neo4j connection details - URI: {self._sanitize_uri(self.uri)}, User: ***"
)

def _sanitize_uri(self, uri: str) -> str:
    """Redact hostname from URI for logging."""
    # bolt://graphiti-neo4j:7687 → bolt://***:7687
    import re
    return re.sub(r'://(.*?):', r'://***:', uri)
```

**Politique logging** :
```python
# src/knowbase/common/logging.py
import logging
import re

class SensitiveDataFilter(logging.Filter):
    """Filtre automatique données sensibles des logs."""

    PATTERNS = [
        (re.compile(r'password[=:]\s*["\']?([^"\'\s]+)["\']?', re.IGNORECASE), r'password=***'),
        (re.compile(r'api[_-]?key[=:]\s*["\']?([^"\'\s]+)["\']?', re.IGNORECASE), r'api_key=***'),
        (re.compile(r'token[=:]\s*["\']?([^"\'\s]+)["\']?', re.IGNORECASE), r'token=***'),
        (re.compile(r'neo4j://([^@]+)@', re.IGNORECASE), r'neo4j://***@'),
    ]

    def filter(self, record):
        msg = record.getMessage()
        for pattern, replacement in self.PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        return True

# Appliquer à tous les loggers
logging.getLogger().addFilter(SensitiveDataFilter())
```

**Priorité** : **P0 - URGENT**

---

### SEC-PHASE1-03: Absence Totale de RBAC (Isolation Multi-Tenant Faible) 🔴

**Fichier** : `src/knowbase/neo4j_custom/queries.py:25-27`

**Problème** :
```python
def __init__(self, client: Neo4jCustomClient, tenant_id: str = "default"):
    self.client = client
    self.tenant_id = tenant_id
    # ❌ Pas de validation tenant_id
    # ❌ Tenant peut être modifié arbitrairement
    # ❌ Aucune vérification ACL (Access Control List)
```

**Impact** :
- ✅ Utilisateur tenant "acme" peut potentiellement lire données tenant "contoso"
- ✅ Pas de distinction read-only vs read-write users
- ✅ Pas d'audit trail "qui a accédé à quoi"
- ✅ Violation compliance (accès non autorisés)

**Scénario d'exploitation** :
```python
# Utilisateur malveillant modifie tenant_id
facts = FactsQueries(client, tenant_id="victim_tenant")  # ❌ Pas de vérification

# Exfiltre toutes les données
all_facts = facts.get_facts_by_status("approved", limit=10000)
# → Accès non autorisé aux Facts d'un autre tenant
```

**CVSS Score** : **8.8** (Critique)
- **Attack Complexity** : Low (simple modification paramètre)
- **Privileges Required** : Low (utilisateur authentifié)
- **Confidentiality** : High (accès tous tenants)
- **Integrity** : High (modification possible)

**Correctif** :

**Option A : Validation stricte tenant_id** (court terme)
```python
# src/knowbase/neo4j_custom/queries.py
from typing import Set

class FactsQueries:
    """Helper class pour requêtes Facts Neo4j."""

    # Registry tenants autorisés (à charger depuis config/DB)
    ALLOWED_TENANTS: Set[str] = {"default", "acme", "contoso"}

    def __init__(
        self,
        client: Neo4jCustomClient,
        tenant_id: str = "default",
        user_id: Optional[str] = None,  # ✅ Identifier utilisateur
        user_roles: Optional[List[str]] = None,  # ✅ Roles utilisateur
    ):
        # ✅ Validation tenant_id
        if not tenant_id or tenant_id not in self.ALLOWED_TENANTS:
            raise ValueError(f"Invalid tenant_id: {tenant_id}")

        # ✅ Validation format tenant_id (prevent injection)
        if not re.match(r'^[a-zA-Z0-9_-]+$', tenant_id):
            raise ValueError(f"Invalid tenant_id format: {tenant_id}")

        self.client = client
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.user_roles = user_roles or []

        # ✅ Logger accès (audit trail)
        logger.info(
            f"FactsQueries initialized - tenant: {tenant_id}, user: {user_id or 'anonymous'}"
        )

    def _check_permission(self, action: str) -> None:
        """Vérifie permissions utilisateur pour action."""
        required_roles = {
            "create_fact": ["admin", "writer"],
            "delete_fact": ["admin"],
            "update_fact_status": ["admin", "approver"],
        }

        if action in required_roles:
            allowed = required_roles[action]
            if not any(role in self.user_roles for role in allowed):
                raise PermissionError(
                    f"User {self.user_id} lacks permission for {action} "
                    f"(requires: {allowed}, has: {self.user_roles})"
                )

    def create_fact(self, **kwargs) -> Dict[str, Any]:
        """Crée un nouveau fact (avec vérification permission)."""
        # ✅ Vérifier permission
        self._check_permission("create_fact")

        # ✅ Forcer tenant_id (empêcher override)
        kwargs["tenant_id"] = self.tenant_id

        # ✅ Tracer auteur
        kwargs.setdefault("created_by", self.user_id)

        # ... reste de l'implémentation
```

**Option B : Neo4j Enterprise RBAC** (production)
```cypher
-- Créer roles Neo4j
CREATE ROLE tenant_acme_reader;
CREATE ROLE tenant_acme_writer;
CREATE ROLE tenant_acme_admin;

-- Restreindre accès par tenant
GRANT MATCH {tenant_id: 'acme'} ON GRAPH * NODES Fact TO tenant_acme_reader;
GRANT CREATE, DELETE ON GRAPH * NODES Fact TO tenant_acme_admin;

-- Créer user lié au tenant
CREATE USER acme_api_user SET PASSWORD 'secure_pass' CHANGE NOT REQUIRED;
GRANT ROLE tenant_acme_reader TO acme_api_user;
```

**Option C : Application-level ACL** (recommandé court terme)
```python
# src/knowbase/security/acl.py
from typing import Dict, List, Optional
from enum import Enum

class Permission(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    APPROVE = "approve"

class ACL:
    """Access Control List pour Facts."""

    def __init__(self):
        # Charger depuis config/database
        self.permissions: Dict[str, Dict[str, List[Permission]]] = {
            "user_123": {
                "tenant_acme": [Permission.READ, Permission.WRITE],
                "tenant_default": [Permission.READ],
            },
            "admin_456": {
                "*": [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.APPROVE],
            },
        }

    def check(
        self,
        user_id: str,
        tenant_id: str,
        permission: Permission
    ) -> bool:
        """Vérifie si user a permission sur tenant."""
        user_perms = self.permissions.get(user_id, {})

        # Wildcard admin
        if "*" in user_perms and permission in user_perms["*"]:
            return True

        # Tenant spécifique
        tenant_perms = user_perms.get(tenant_id, [])
        return permission in tenant_perms

# Usage
acl = ACL()
if not acl.check(user_id, tenant_id, Permission.DELETE):
    raise PermissionError("Not authorized")
```

**Priorité** : **P0 - CRITIQUE** (implémenter ACL basique avant Phase 2)

---

### SEC-PHASE1-04: Injection Cypher dans Migrations (Dynamic SQL) 🔴

**Fichier** : `src/knowbase/neo4j_custom/migrations.py:222-227`

**Problème** :
```python
def drop_all_constraints(self) -> None:
    """⚠️ DANGER: Supprime tous les constraints."""
    constraints = self.list_constraints()

    for constraint in constraints:
        constraint_name = constraint.get("name")
        if constraint_name:
            try:
                query = f"DROP CONSTRAINT {constraint_name} IF EXISTS"  # ❌ F-string sans sanitization
                self.client.execute_write_query(query)
```

**Impact** :
- ✅ Si `constraint_name` contient caractères malveillants → injection Cypher
- ✅ Attaquant peut exécuter queries arbitraires
- ✅ Élévation privilèges possible

**Scénario d'exploitation** :
```python
# Attaquant compromet source constraint names
# Via Neo4j browser ou manipulation registry
constraint = {
    "name": "fact_uuid_unique; MATCH (n) DETACH DELETE n; --"
}

# Résultat:
# DROP CONSTRAINT fact_uuid_unique; MATCH (n) DETACH DELETE n; -- IF EXISTS
# → Supprime tous les nodes !
```

**CVSS Score** : **8.6** (Élevé/Critique)

**Correctif** :

```python
# src/knowbase/neo4j_custom/migrations.py
import re

def drop_all_constraints(self) -> None:
    """⚠️ DANGER: Supprime tous les constraints."""
    logger.warning("⚠️ Dropping all constraints...")

    constraints = self.list_constraints()

    for constraint in constraints:
        constraint_name = constraint.get("name")
        if constraint_name:
            # ✅ Validation stricte nom constraint
            if not self._is_valid_constraint_name(constraint_name):
                logger.error(f"Invalid constraint name: {constraint_name}")
                continue

            try:
                # ✅ Paramètre plutôt que f-string (si supporté par Neo4j)
                # Sinon: whitelist validation
                query = f"DROP CONSTRAINT {constraint_name} IF EXISTS"
                self.client.execute_write_query(query)
                logger.info(f"  ✅ Dropped constraint: {constraint_name}")

            except Exception as e:
                logger.error(f"  ❌ Failed to drop constraint {constraint_name}: {e}")

def _is_valid_constraint_name(self, name: str) -> bool:
    """Valide format nom constraint (prévention injection)."""
    # Neo4j constraint names: alphanumeric + underscore uniquement
    pattern = r'^[a-zA-Z_][a-zA-Z0-9_]{0,200}$'
    if not re.match(pattern, name):
        return False

    # Blacklist keywords dangereux
    dangerous_keywords = [
        'DROP', 'DELETE', 'DETACH', 'REMOVE', 'MATCH',
        'CREATE', 'SET', 'MERGE', ';', '--', '/*', '*/'
    ]
    name_upper = name.upper()
    if any(keyword in name_upper for keyword in dangerous_keywords):
        return False

    return True
```

**Même correctif pour `drop_all_indexes()`** :
```python
def drop_all_indexes(self) -> None:
    """⚠️ DANGER: Supprime tous les indexes."""
    indexes = self.list_indexes()

    for index in indexes:
        index_name = index.get("name")
        # Ne pas supprimer indexes système
        if index_name and not index_name.startswith("__"):
            # ✅ Validation stricte
            if not self._is_valid_index_name(index_name):
                logger.error(f"Invalid index name: {index_name}")
                continue

            # ... reste
```

**Priorité** : **P0 - URGENT** (validation stricte requise)

---

### SEC-PHASE1-05: Logs de Queries Exposant Données Sensibles 🔴

**Fichier** : `src/knowbase/neo4j_custom/client.py:195-198`

**Problème** :
```python
logger.debug(
    f"Query executed - Records: {len(records)}, "
    f"Query: {query[:100]}..."  # ❌ Logs 100 premiers chars query
)
```

**Impact** :
- ✅ Queries Cypher contiennent données sensibles (values, tenant_id)
- ✅ Logs persistent sur disque → exposition long terme
- ✅ Log aggregation (ELK) → centralisé mais non sécurisé
- ✅ Violation GDPR (PII dans logs)

**Exemple log dangereux** :
```log
2025-10-03 DEBUG Query executed - Records: 1, Query: MATCH (f:Fact {tenant_id: 'acme', subject: 'SAP Revenue 2024', value: 35000000})...
# → Revenue confidentiel loggué !
```

**CVSS Score** : **7.2** (Élevé)

**Correctif** :

```python
# src/knowbase/neo4j_custom/client.py
def execute_query(
    self,
    query: str,
    parameters: Optional[Dict[str, Any]] = None,
    database: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Exécute query Cypher et retourne résultats."""
    params = parameters or {}

    try:
        with self.session(database=database) as session:
            result = session.run(query, params)

            records = []
            for record in result:
                records.append(dict(record))

            # ✅ Log minimaliste (pas de query, pas de données)
            logger.debug(
                f"Query executed - Records: {len(records)}, "
                f"Database: {database or self.database}"
                # ❌ Pas de query loggée
            )

            # ✅ Log query uniquement en mode TRACE (jamais activé en prod)
            if logger.isEnabledFor(logging.NOTSET):  # NOTSET = 0 (jamais activé)
                logger.log(5, f"Query details: {self._sanitize_query(query)}")  # Level 5 < DEBUG

            return records

    except TransientError as e:
        logger.error(f"Transient error executing query")  # ✅ Pas de détails query
        raise Neo4jQueryError(f"Transient error: {e}") from e

    except Exception as e:
        logger.error(f"Error executing query")  # ✅ Pas de détails query
        raise Neo4jQueryError(f"Query failed: {e}") from e

def _sanitize_query(self, query: str) -> str:
    """Redact valeurs sensibles de la query pour logging."""
    import re
    # Remplacer values par ***
    query = re.sub(r'value:\s*[0-9.]+', 'value: ***', query)
    query = re.sub(r'tenant_id:\s*["\']([^"\']+)["\']', 'tenant_id: "***"', query)
    query = re.sub(r'subject:\s*["\']([^"\']+)["\']', 'subject: "***"', query)
    return query
```

**Configuration logging production** :
```python
# config/logging.yaml
version: 1
loggers:
  knowbase.neo4j_custom:
    level: INFO  # ✅ Pas de DEBUG en production
    handlers:
      - console
      - file
    propagate: false

handlers:
  file:
    class: logging.handlers.RotatingFileHandler
    filename: /var/log/app/neo4j.log
    maxBytes: 10485760  # 10MB
    backupCount: 3
    formatter: json
    filters:
      - sensitive_data_filter  # ✅ Filtre automatique

filters:
  sensitive_data_filter:
    (): knowbase.common.logging.SensitiveDataFilter
```

**Priorité** : **P0 - URGENT**

---

### SEC-PHASE1-06: Absence d'Audit Trail 🔴

**Fichier** : Tous les fichiers `neo4j_custom/`

**Problème** :
- ❌ Aucun enregistrement "qui a fait quoi, quand"
- ❌ Impossible de tracer modifications Facts (accountability)
- ❌ Impossible de détecter accès non autorisés
- ❌ Violation compliance (SOX, GDPR Article 30)

**Impact** :
- ✅ Incident sécurité → impossible d'identifier attaquant
- ✅ Modification frauduleuse Fact → pas de trace
- ✅ Audit compliance échoue
- ✅ Pas de forensics possible

**CVSS Score** : **7.8** (Élevé)

**Correctif** :

**Option A : Audit Trail Neo4j Node** (simple)
```python
# src/knowbase/neo4j_custom/queries.py
def create_fact(self, **kwargs) -> Dict[str, Any]:
    """Crée un nouveau fact avec audit trail."""
    # ... validation

    fact_uuid = str(uuid.uuid4())

    # ✅ Créer fact + audit entry
    query = """
    CREATE (f:Fact {
        uuid: $uuid,
        tenant_id: $tenant_id,
        // ... autres propriétés
    })

    // ✅ Créer audit trail entry
    CREATE (audit:AuditLog {
        uuid: randomUUID(),
        timestamp: datetime(),
        action: 'CREATE_FACT',
        entity_type: 'Fact',
        entity_uuid: $uuid,
        tenant_id: $tenant_id,
        user_id: $user_id,
        ip_address: $ip_address,
        user_agent: $user_agent,
        changes: null  // Pour CREATE, pas de diff
    })

    // Relation audit → fact
    CREATE (audit)-[:AUDITS]->(f)

    RETURN f
    """

    parameters = {
        "uuid": fact_uuid,
        "tenant_id": self.tenant_id,
        "user_id": self.user_id or "anonymous",
        "ip_address": self._get_client_ip(),
        "user_agent": self._get_user_agent(),
        # ... autres params
    }

    results = self.client.execute_write_query(query, parameters)
    # ...

def update_fact_status(
    self,
    fact_uuid: str,
    status: str,
    approved_by: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Met à jour statut avec audit trail."""
    # ✅ Récupérer état avant modification
    old_fact = self.get_fact_by_uuid(fact_uuid)

    # Modifier
    query = """
    MATCH (f:Fact {uuid: $uuid, tenant_id: $tenant_id})

    // ✅ Audit trail avec diff
    CREATE (audit:AuditLog {
        uuid: randomUUID(),
        timestamp: datetime(),
        action: 'UPDATE_FACT_STATUS',
        entity_type: 'Fact',
        entity_uuid: $uuid,
        tenant_id: $tenant_id,
        user_id: $user_id,
        changes: $changes  // JSON diff before/after
    })
    CREATE (audit)-[:AUDITS]->(f)

    // Update fact
    SET f.status = $status,
        f.updated_at = datetime(),
        f.approved_by = $approved_by,
        f.approved_at = CASE WHEN $status = 'approved' THEN datetime() ELSE f.approved_at END

    RETURN f
    """

    changes = {
        "field": "status",
        "old_value": old_fact.get("status"),
        "new_value": status,
    }

    results = self.client.execute_write_query(
        query,
        {
            "uuid": fact_uuid,
            "tenant_id": self.tenant_id,
            "status": status,
            "approved_by": approved_by,
            "user_id": self.user_id or "anonymous",
            "changes": json.dumps(changes),
        }
    )
    # ...
```

**Option B : Audit Trail Table PostgreSQL** (recommandé production)
```python
# src/knowbase/security/audit.py
from sqlalchemy import create_engine, Column, String, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    action = Column(String, nullable=False, index=True)
    entity_type = Column(String, index=True)
    entity_uuid = Column(String, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    user_id = Column(String, index=True)
    ip_address = Column(String)
    changes = Column(JSON)

    # Immutable: pas de UPDATE/DELETE
    __table_args__ = {'schema': 'audit'}

class AuditLogger:
    """Logger centralisé audit trail."""

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)

    def log(
        self,
        action: str,
        entity_type: str,
        entity_uuid: str,
        tenant_id: str,
        user_id: str,
        changes: Optional[Dict] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """Enregistre action audit (append-only)."""
        with self.engine.begin() as conn:
            audit = AuditLog(
                id=str(uuid.uuid4()),
                action=action,
                entity_type=entity_type,
                entity_uuid=entity_uuid,
                tenant_id=tenant_id,
                user_id=user_id,
                ip_address=ip_address,
                changes=changes,
            )
            conn.add(audit)

        # ✅ Log structuré pour SIEM
        logger.info(
            "AUDIT",
            extra={
                "action": action,
                "entity": entity_type,
                "tenant": tenant_id,
                "user": user_id,
            }
        )

# Usage
audit = AuditLogger(os.getenv("AUDIT_DB_URL"))

def create_fact(self, **kwargs):
    # ... créer fact

    # ✅ Audit trail
    audit.log(
        action="CREATE_FACT",
        entity_type="Fact",
        entity_uuid=fact_uuid,
        tenant_id=self.tenant_id,
        user_id=self.user_id,
        ip_address=request.client.host if request else None,
    )

    return fact
```

**Queries audit** :
```python
# Qui a modifié ce fact ?
SELECT user_id, timestamp, action, changes
FROM audit.audit_logs
WHERE entity_uuid = 'fact-uuid-123'
ORDER BY timestamp DESC;

# Toutes les actions d'un user sur un tenant
SELECT action, entity_type, timestamp
FROM audit.audit_logs
WHERE tenant_id = 'acme' AND user_id = 'john@acme.com'
ORDER BY timestamp DESC
LIMIT 100;

# Détection anomalies (trop de DELETE)
SELECT user_id, COUNT(*) as delete_count
FROM audit.audit_logs
WHERE action = 'DELETE_FACT' AND timestamp > NOW() - INTERVAL '1 hour'
GROUP BY user_id
HAVING COUNT(*) > 10;  -- Alert si > 10 delete/heure
```

**Compliance GDPR** :
```python
# Article 30: Register of processing activities
def export_audit_trail_gdpr(tenant_id: str, start_date: str, end_date: str):
    """Exporte audit trail GDPR-compliant."""
    return {
        "tenant_id": tenant_id,
        "period": f"{start_date} to {end_date}",
        "activities": [
            {
                "timestamp": log.timestamp.isoformat(),
                "action": log.action,
                "user": log.user_id,
                "entity": log.entity_type,
                "lawful_basis": "Legitimate interest (Art. 6.1.f)",
            }
            for log in query_audit_logs(tenant_id, start_date, end_date)
        ]
    }
```

**Priorité** : **P0 - CRITIQUE** (implémenter audit basique avant Phase 2)

---

## 🟠 VULNÉRABILITÉS ÉLEVÉES (P1)

### SEC-PHASE1-07: Pas de Timeouts Explicites (DoS) 🟠

**Fichier** : `src/knowbase/neo4j_custom/client.py:52-53`

**Problème** :
```python
connection_timeout: float = 30.0,
max_retry_attempts: int = 3,
# ❌ Pas de query_timeout
# ❌ Pas de transaction_timeout
```

**Impact** :
- ✅ Query longue → blocage connexion indéfiniment
- ✅ Attaquant envoie query coûteuse → DoS
- ✅ Connection pool exhausted
- ✅ Cascade failures

**Scénario d'exploitation** :
```cypher
// Attaquant envoie query O(n²) coûteuse
MATCH (f1:Fact), (f2:Fact)
WHERE f1.value < f2.value
RETURN count(*)
// → Peut prendre minutes/heures sur grand dataset
```

**CVSS Score** : **7.5** (Élevé)

**Correctif** :

```python
# src/knowbase/neo4j_custom/client.py
def __init__(
    self,
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    database: str = "neo4j",
    max_connection_lifetime: int = 3600,
    max_connection_pool_size: int = 50,
    connection_timeout: float = 30.0,
    max_retry_attempts: int = 3,
    max_transaction_retry_time: float = 30.0,  # ✅ Timeout transaction
):
    # ...

    self._driver_config = {
        "max_connection_lifetime": max_connection_lifetime,
        "max_connection_pool_size": max_connection_pool_size,
        "connection_timeout": connection_timeout,
        "max_transaction_retry_time": max_transaction_retry_time,  # ✅ 30s max retry
        "encrypted": True,
        "trust": "TRUST_SYSTEM_CA_SIGNED_CERTIFICATES",
    }

def execute_query(
    self,
    query: str,
    parameters: Optional[Dict[str, Any]] = None,
    database: Optional[str] = None,
    timeout: float = 10.0,  # ✅ Timeout query (10s par défaut)
) -> List[Dict[str, Any]]:
    """Exécute query Cypher avec timeout."""
    params = parameters or {}

    try:
        with self.session(database=database) as session:
            # ✅ Query timeout via transaction config
            with session.begin_transaction(timeout=timeout) as tx:
                result = tx.run(query, params)

                records = []
                for record in result:
                    records.append(dict(record))

                tx.commit()

            logger.debug(f"Query executed - Records: {len(records)}")
            return records

    except Exception as e:
        logger.error(f"Query timeout or error: {e}")
        raise Neo4jQueryError(f"Query failed: {e}") from e
```

**Configuration Neo4j** :
```yaml
# docker-compose.infra.yml
neo4j:
  environment:
    # ✅ Timeouts serveur
    - NEO4J_db_transaction_timeout=30s
    - NEO4J_dbms_transaction_timeout=30s
    - NEO4J_db_lock_acquisition_timeout=10s
```

**Monitoring queries lentes** :
```cypher
// Identifier slow queries
CALL dbms.listQueries()
YIELD query, elapsedTimeMillis, allocatedBytes
WHERE elapsedTimeMillis > 5000  // > 5s
RETURN query, elapsedTimeMillis, allocatedBytes
ORDER BY elapsedTimeMillis DESC;

// Kill query lente
CALL dbms.killQuery('query-123');
```

**Priorité** : **P1 - Élevé**

---

### SEC-PHASE1-08: Connection Pool Non Sécurisé (Resource Exhaustion) 🟠

**Fichier** : `src/knowbase/neo4j_custom/client.py:51`

**Problème** :
```python
max_connection_pool_size: int = 50,
# ❌ Pas de idle_timeout
# ❌ Pas de max_connection_age
# ❌ Pas de validation connexion avant usage
```

**Impact** :
- ✅ Connexions mortes persistent dans pool
- ✅ Attaquant ouvre 50 connexions → pool exhausted → DoS
- ✅ Pas de retry intelligent
- ✅ Cascade failures

**CVSS Score** : **6.5** (Moyen/Élevé)

**Correctif** :

```python
# src/knowbase/neo4j_custom/client.py
self._driver_config = {
    "max_connection_lifetime": 3600,  # 1h max lifetime
    "max_connection_pool_size": 50,
    "connection_timeout": 30.0,
    "connection_acquisition_timeout": 60.0,  # ✅ Timeout acquisition connexion
    "max_transaction_retry_time": 30.0,
    "keep_alive": True,  # ✅ TCP keepalive
    "encrypted": True,
    "trust": "TRUST_SYSTEM_CA_SIGNED_CERTIFICATES",
}

def execute_query(self, query: str, **kwargs) -> List[Dict[str, Any]]:
    """Exécute query avec retry intelligent."""
    max_retries = 3
    retry_delay = 1.0  # secondes

    for attempt in range(1, max_retries + 1):
        try:
            # ✅ Vérifier connectivité avant query
            if not self.verify_connectivity():
                logger.warning("Neo4j connectivity lost, reconnecting...")
                self.close()
                self.connect()

            with self.session(**kwargs) as session:
                result = session.run(query, kwargs.get("parameters", {}))
                records = [dict(record) for record in result]
                return records

        except TransientError as e:
            if attempt == max_retries:
                raise Neo4jQueryError(f"Query failed after {max_retries} retries") from e

            logger.warning(f"TransientError, retry {attempt}/{max_retries}: {e}")
            time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff

        except ServiceUnavailable as e:
            logger.error(f"Neo4j service unavailable: {e}")
            # ✅ Reconnect
            self.close()
            self.connect()

            if attempt == max_retries:
                raise Neo4jConnectionError("Service unavailable") from e

    raise Neo4jQueryError("Unexpected retry exhaustion")
```

**Monitoring pool** :
```python
def get_pool_stats(self) -> Dict[str, Any]:
    """Retourne statistiques connection pool."""
    if self._driver is None:
        return {"status": "disconnected"}

    # Note: Neo4j driver ne expose pas directement pool stats
    # Workaround: metrics custom
    return {
        "max_pool_size": self._driver_config["max_connection_pool_size"],
        "active_connections": self._active_connections,  # À tracker manuellement
        "idle_connections": self._idle_connections,
        "pool_exhausted_count": self._pool_exhausted_count,
    }

def _track_connection_usage(self):
    """Tracking usage pool (méthode helper)."""
    self._active_connections += 1

    if self._active_connections >= self._driver_config["max_connection_pool_size"]:
        self._pool_exhausted_count += 1
        logger.warning(
            f"Connection pool exhausted - "
            f"Active: {self._active_connections}/{self._driver_config['max_connection_pool_size']}"
        )
```

**Priorité** : **P1 - Élevé**

---

### SEC-PHASE1-09: Validation Insuffisante Paramètres Fact 🟠

**Fichier** : `src/knowbase/neo4j_custom/queries.py:76-86`

**Problème** :
```python
# Validation applicative (Neo4j Community ne supporte pas contraintes Enterprise)
VALID_STATUSES = ["proposed", "approved", "rejected", "conflicted"]

if not subject or not predicate:
    raise ValueError("subject and predicate are required")

if not self.tenant_id:
    raise ValueError("tenant_id is required")

if status not in VALID_STATUSES:
    raise ValueError(f"status must be one of {VALID_STATUSES}, got: {status}")

# ❌ Pas de validation format subject/predicate
# ❌ Pas de validation range value
# ❌ Pas de validation unit (% vs percent vs ...)
# ❌ Pas de sanitization injection
```

**Impact** :
- ✅ `subject` peut contenir caractères malveillants → injection Cypher potentielle
- ✅ `value` peut être négatif/infini → données incohérentes
- ✅ `unit` non standardisé → comparaison impossible
- ✅ Pas de validation longueur → DoS mémoire

**CVSS Score** : **6.8** (Moyen/Élevé)

**Correctif** :

```python
# src/knowbase/neo4j_custom/validators.py
from pydantic import BaseModel, Field, validator, root_validator
from typing import Optional, Literal
import re
from datetime import datetime

class FactCreate(BaseModel):
    """Schéma validation création Fact (Pydantic)."""

    subject: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Sujet du fact"
    )
    predicate: str = Field(
        ...,
        min_length=1,
        max_length=200,
        regex=r'^[a-zA-Z_][a-zA-Z0-9_]*$',  # ✅ Snake_case uniquement
        description="Prédicat (snake_case)"
    )
    object_str: str = Field(..., max_length=1000, alias="object")

    value: float = Field(
        ...,
        ge=-1e15,  # ✅ Range réaliste
        le=1e15,
        description="Valeur numérique"
    )

    unit: str = Field(
        ...,
        max_length=50,
        description="Unité (standardisée)"
    )

    value_type: Literal["numeric", "text", "date", "boolean"] = "numeric"

    fact_type: Literal[
        "SERVICE_LEVEL",
        "CAPACITY",
        "PERFORMANCE",
        "PRICING",
        "COMPLIANCE",
        "GENERAL"
    ] = "GENERAL"

    status: Literal["proposed", "approved", "rejected", "conflicted"] = "proposed"

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    valid_from: Optional[str] = None
    valid_until: Optional[str] = None

    source_chunk_id: Optional[str] = Field(None, max_length=100)
    source_document: Optional[str] = Field(None, max_length=500)

    extraction_method: Optional[str] = Field(None, max_length=100)
    extraction_model: Optional[str] = Field(None, max_length=100)
    extraction_prompt_id: Optional[str] = Field(None, max_length=100)

    @validator('subject')
    def validate_subject(cls, v: str) -> str:
        """Sanitize subject (prévention injection)."""
        # ✅ Blacklist caractères dangereux
        dangerous_chars = ['{', '}', '$', '`', ';', '--', '/*', '*/']
        if any(char in v for char in dangerous_chars):
            raise ValueError(f"Subject contient caractères interdits: {dangerous_chars}")

        # ✅ Trim whitespace
        v = v.strip()

        # ✅ Normaliser Unicode (éviter homoglyphe attacks)
        import unicodedata
        v = unicodedata.normalize('NFKC', v)

        return v

    @validator('predicate')
    def validate_predicate(cls, v: str) -> str:
        """Valide format predicate."""
        # ✅ Snake_case strict
        if not re.match(r'^[a-z_][a-z0-9_]*$', v):
            raise ValueError("Predicate doit être snake_case (ex: sla_garantie)")

        return v

    @validator('unit')
    def normalize_unit(cls, v: str) -> str:
        """Normalise unité (standardisation)."""
        # ✅ Mapping unités standardisées
        unit_mapping = {
            '%': '%',
            'percent': '%',
            'percentage': '%',
            'pct': '%',
            'gb': 'GB',
            'gigabyte': 'GB',
            'gigabytes': 'GB',
            'mb': 'MB',
            'tb': 'TB',
            'ms': 'ms',
            'millisecond': 'ms',
            'milliseconds': 'ms',
            's': 's',
            'second': 's',
            'seconds': 's',
            'eur': 'EUR',
            'euro': 'EUR',
            'euros': 'EUR',
            'usd': 'USD',
            'dollar': 'USD',
            'dollars': 'USD',
        }

        v_lower = v.strip().lower()
        if v_lower in unit_mapping:
            return unit_mapping[v_lower]

        # ✅ Si unité inconnue, accepter mais logger warning
        if not re.match(r'^[a-zA-Z/%]+$', v):
            raise ValueError(f"Unit format invalide: {v}")

        return v.strip()

    @validator('valid_from', 'valid_until')
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        """Valide format date ISO 8601."""
        if v is None:
            return None

        try:
            # ✅ Parser ISO format strict
            datetime.fromisoformat(v.replace('Z', '+00:00'))
            return v
        except ValueError:
            raise ValueError(f"Date doit être ISO 8601 format: {v}")

    @root_validator
    def validate_date_range(cls, values):
        """Valide cohérence valid_from < valid_until."""
        valid_from = values.get('valid_from')
        valid_until = values.get('valid_until')

        if valid_from and valid_until:
            dt_from = datetime.fromisoformat(valid_from.replace('Z', '+00:00'))
            dt_until = datetime.fromisoformat(valid_until.replace('Z', '+00:00'))

            if dt_from >= dt_until:
                raise ValueError("valid_from doit être < valid_until")

        return values

    @root_validator
    def validate_value_unit_consistency(cls, values):
        """Valide cohérence value/unit (ex: % doit être 0-100)."""
        value = values.get('value')
        unit = values.get('unit')

        if unit == '%' and not (0 <= value <= 100):
            raise ValueError(f"Value {value}% doit être entre 0 et 100")

        if unit in ['GB', 'MB', 'TB'] and value < 0:
            raise ValueError(f"Capacité {value}{unit} ne peut être négative")

        return values

# Usage dans queries.py
def create_fact(self, **kwargs) -> Dict[str, Any]:
    """Crée un nouveau fact (avec validation Pydantic)."""
    # ✅ Validation stricte
    try:
        validated = FactCreate(**kwargs)
    except ValidationError as e:
        logger.error(f"Fact validation failed: {e}")
        raise ValueError(f"Invalid fact data: {e}") from e

    # ✅ Forcer tenant_id (empêcher override)
    parameters = validated.dict(by_alias=True)
    parameters["tenant_id"] = self.tenant_id
    parameters["uuid"] = str(uuid.uuid4())

    # ... reste implémentation
```

**Tests validation** :
```python
# tests/neo4j_custom/test_validators.py
def test_subject_injection_prevention():
    """Test prévention injection Cypher dans subject."""
    with pytest.raises(ValueError, match="caractères interdits"):
        FactCreate(
            subject="SAP S/4HANA'; DROP DATABASE; --",
            predicate="sla",
            object="99%",
            value=99,
            unit="%"
        )

def test_predicate_snake_case_required():
    """Test format predicate snake_case."""
    with pytest.raises(ValueError, match="snake_case"):
        FactCreate(
            subject="SAP",
            predicate="SLA Garantie",  # ❌ Pas snake_case
            object="99%",
            value=99,
            unit="%"
        )

def test_unit_normalization():
    """Test normalisation unités."""
    fact = FactCreate(
        subject="SAP",
        predicate="sla",
        object="99 percent",
        value=99,
        unit="percent"  # → Normalisé en "%"
    )
    assert fact.unit == "%"

def test_percentage_range_validation():
    """Test validation range % (0-100)."""
    with pytest.raises(ValueError, match="entre 0 et 100"):
        FactCreate(
            subject="SAP",
            predicate="sla",
            object="150%",
            value=150,  # ❌ > 100
            unit="%"
        )
```

**Priorité** : **P1 - Élevé**

---

### SEC-PHASE1-10: Pas de Rate Limiting sur Queries 🟠

**Fichier** : Tous les fichiers `neo4j_custom/`

**Problème** :
- ❌ Utilisateur peut créer 1000 facts/seconde → DoS
- ❌ Pas de throttling par tenant
- ❌ Pas de circuit breaker si Neo4j slow

**Impact** :
- ✅ Attaquant flood database → DoS
- ✅ Coût infra (CPU, RAM)
- ✅ Impact autres tenants (noisy neighbor)

**CVSS Score** : **6.5** (Moyen/Élevé)

**Correctif** :

```python
# src/knowbase/security/rate_limiter.py
from redis import Redis
from datetime import datetime, timedelta
from typing import Optional
import hashlib

class RateLimiter:
    """Rate limiter Redis-based pour Neo4j queries."""

    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    def check_rate_limit(
        self,
        identifier: str,  # tenant_id + user_id
        action: str,      # "create_fact", "delete_fact"
        limit: int,       # Max operations
        window: int,      # Période (secondes)
    ) -> bool:
        """
        Vérifie rate limit (sliding window).

        Returns:
            True si autorisé, False si rate limit exceeded
        """
        key = f"ratelimit:{action}:{identifier}"

        now = datetime.utcnow().timestamp()
        window_start = now - window

        # Redis sorted set: score = timestamp
        pipeline = self.redis.pipeline()

        # 1. Supprimer entrées expirées
        pipeline.zremrangebyscore(key, 0, window_start)

        # 2. Compter entrées dans fenêtre
        pipeline.zcard(key)

        # 3. Ajouter nouvelle entrée
        pipeline.zadd(key, {str(now): now})

        # 4. Expiration clé (cleanup)
        pipeline.expire(key, window + 60)

        results = pipeline.execute()
        count = results[1]  # Nombre requêtes dans fenêtre

        if count >= limit:
            logger.warning(
                f"Rate limit exceeded - "
                f"Action: {action}, Identifier: {identifier}, "
                f"Limit: {limit}/{window}s, Current: {count}"
            )
            return False

        return True

    def get_remaining_quota(
        self,
        identifier: str,
        action: str,
        limit: int,
        window: int,
    ) -> int:
        """Retourne quota restant."""
        key = f"ratelimit:{action}:{identifier}"

        now = datetime.utcnow().timestamp()
        window_start = now - window

        # Supprimer expirés + compter
        self.redis.zremrangebyscore(key, 0, window_start)
        count = self.redis.zcard(key)

        return max(0, limit - count)

# Intégration dans FactsQueries
class FactsQueries:
    def __init__(
        self,
        client: Neo4jCustomClient,
        tenant_id: str = "default",
        user_id: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self.client = client
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.rate_limiter = rate_limiter

    def create_fact(self, **kwargs) -> Dict[str, Any]:
        """Crée fact avec rate limiting."""
        # ✅ Rate limiting
        if self.rate_limiter:
            identifier = f"{self.tenant_id}:{self.user_id or 'anonymous'}"

            if not self.rate_limiter.check_rate_limit(
                identifier=identifier,
                action="create_fact",
                limit=100,  # Max 100 facts
                window=60,  # Par minute
            ):
                raise RateLimitExceeded(
                    "Rate limit exceeded: 100 facts/minute. "
                    f"Remaining: {self.rate_limiter.get_remaining_quota(identifier, 'create_fact', 100, 60)}"
                )

        # ... créer fact
```

**Configuration rate limits** :
```python
# config/rate_limits.yaml
rate_limits:
  create_fact:
    limit: 100
    window: 60  # secondes

  delete_fact:
    limit: 10
    window: 60

  detect_conflicts:
    limit: 20
    window: 60

  # Rate limits par tenant tier
  tenant_tiers:
    free:
      create_fact_daily: 1000
    pro:
      create_fact_daily: 10000
    enterprise:
      create_fact_daily: 100000
```

**Priorité** : **P1 - Élevé**

---

### SEC-PHASE1-11: Singleton Global Non Thread-Safe 🟠

**Fichier** : `src/knowbase/neo4j_custom/client.py:326-345`

**Problème** :
```python
# Singleton global client (lazy initialized)
_global_client: Optional[Neo4jCustomClient] = None

def get_neo4j_client() -> Neo4jCustomClient:
    """Retourne client Neo4j singleton."""
    global _global_client

    if _global_client is None:
        _global_client = Neo4jCustomClient()
        _global_client.connect()  # ❌ Race condition si threads concurrents

    return _global_client
```

**Impact** :
- ✅ Race condition: 2 threads créent 2 clients simultanément
- ✅ Connection leaks
- ✅ État partagé mutable → bugs subtils
- ✅ Impossible de mocker pour tests

**CVSS Score** : **5.5** (Moyen)

**Correctif** :

```python
# src/knowbase/neo4j_custom/client.py
import threading

# ✅ Thread-safe singleton avec lock
_global_client: Optional[Neo4jCustomClient] = None
_client_lock = threading.Lock()

def get_neo4j_client() -> Neo4jCustomClient:
    """
    Retourne client Neo4j singleton (thread-safe).

    Usage:
        client = get_neo4j_client()
        with client.session() as session:
            ...
    """
    global _global_client

    if _global_client is None:
        with _client_lock:  # ✅ Lock pour thread-safety
            # Double-check pattern
            if _global_client is None:
                _global_client = Neo4jCustomClient()
                _global_client.connect()

    return _global_client

def close_neo4j_client() -> None:
    """Ferme client Neo4j singleton (thread-safe)."""
    global _global_client

    if _global_client is not None:
        with _client_lock:
            if _global_client is not None:
                _global_client.close()
                _global_client = None
```

**Meilleure approche: Dependency Injection** (recommandé)
```python
# src/knowbase/api/dependencies.py
from fastapi import Depends
from typing import Generator

_client_pool: Optional[Neo4jCustomClient] = None

def get_neo4j_client_pool() -> Neo4jCustomClient:
    """Initialise pool Neo4j (startup app)."""
    global _client_pool
    if _client_pool is None:
        _client_pool = Neo4jCustomClient()
        _client_pool.connect()
    return _client_pool

def get_neo4j_session() -> Generator:
    """Dependency FastAPI pour session Neo4j."""
    client = get_neo4j_client_pool()
    with client.session() as session:
        yield session

# Usage dans API
@app.post("/api/facts")
async def create_fact(
    fact_data: FactCreate,
    session: Session = Depends(get_neo4j_session),
    current_user: User = Depends(get_current_user),
):
    """Crée fact avec dependency injection."""
    facts = FactsQueries(
        client=session.client,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )
    return facts.create_fact(**fact_data.dict())
```

**Priorité** : **P1 - Élevé**

---

### SEC-PHASE1-12: Pas de Validation Source Document Path Traversal 🟠

**Fichier** : `src/knowbase/neo4j_custom/queries.py:107`

**Problème** :
```python
"source_document": source_document,  # ❌ Pas de validation path
```

**Impact** :
- ✅ Path traversal: `source_document = "../../../etc/passwd"`
- ✅ Information disclosure (si paths loggués/affichés)
- ✅ Confusion dans audit trail

**CVSS Score** : **6.2** (Moyen)

**Correctif** :

```python
# src/knowbase/neo4j_custom/validators.py
import os
from pathlib import Path

@validator('source_document')
def validate_source_document(cls, v: Optional[str]) -> Optional[str]:
    """Valide source_document (prévention path traversal)."""
    if v is None:
        return None

    # ✅ Normaliser path
    normalized = os.path.normpath(v)

    # ✅ Rejeter path traversal
    if '..' in normalized or normalized.startswith('/'):
        raise ValueError(f"Invalid source_document path: {v}")

    # ✅ Extraire uniquement basename (pas de répertoire)
    basename = os.path.basename(normalized)

    # ✅ Validation extension autorisée
    allowed_extensions = ['.pdf', '.docx', '.pptx', '.txt', '.md']
    if not any(basename.lower().endswith(ext) for ext in allowed_extensions):
        raise ValueError(f"Unsupported document type: {basename}")

    return basename
```

**Priorité** : **P1 - Élevé**

---

### SEC-PHASE1-13: Migrations Sans Backup Automatique 🟠

**Fichier** : `src/knowbase/neo4j_custom/migrations.py:122-171`

**Problème** :
```python
def apply_all(self) -> Dict[str, Any]:
    """Applique toutes les migrations."""
    # ❌ Pas de backup avant migration
    # ❌ Pas de rollback en cas d'échec partiel
    # ❌ Pas de dry-run mode
```

**Impact** :
- ✅ Migration échoue → données corrompues
- ✅ Pas de rollback possible
- ✅ Downtime non planifié

**CVSS Score** : **6.0** (Moyen)

**Correctif** :

```python
# src/knowbase/neo4j_custom/migrations.py
def apply_all(
    self,
    dry_run: bool = False,
    auto_backup: bool = True,
) -> Dict[str, Any]:
    """
    Applique toutes les migrations (avec backup).

    Args:
        dry_run: Si True, simule sans appliquer
        auto_backup: Si True, backup automatique avant migration
    """
    logger.info("🚀 Starting Neo4j migrations...")

    current_version = self.get_current_version()
    target_version = 1

    if current_version >= target_version:
        logger.info(f"Schema already up to date (v{current_version})")
        return {"status": "up_to_date", "current_version": current_version}

    # ✅ Backup automatique
    if auto_backup and not dry_run:
        logger.info("📦 Creating backup before migration...")
        backup_path = self._create_backup()
        logger.info(f"✅ Backup created: {backup_path}")

    # ✅ Dry-run mode
    if dry_run:
        logger.info("🔍 DRY-RUN MODE - Simulating migrations...")
        return {
            "status": "dry_run",
            "would_apply": {
                "constraints": len(schemas.CONSTRAINTS),
                "indexes": len(schemas.INDEXES),
            },
        }

    try:
        # Appliquer constraints
        self.apply_constraints()

        # Appliquer indexes
        self.apply_indexes()

        # Mettre à jour version
        self.set_version(target_version)

        logger.info(f"✅ Migrations completed (v{current_version} → v{target_version})")

        return {
            "status": "success",
            "previous_version": current_version,
            "current_version": target_version,
            "backup_path": backup_path if auto_backup else None,
        }

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")

        # ✅ Rollback automatique si backup existe
        if auto_backup:
            logger.warning("⚠️ Attempting automatic rollback...")
            self._restore_backup(backup_path)

        return {
            "status": "failed",
            "error": str(e),
            "current_version": current_version,
        }

def _create_backup(self) -> str:
    """Crée backup Neo4j (dump)."""
    import subprocess
    from datetime import datetime

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"/backups/neo4j_{timestamp}"

    try:
        # Neo4j dump (nécessite neo4j-admin)
        subprocess.run(
            [
                "neo4j-admin", "database", "dump",
                f"--to-path={backup_dir}",
                "--database=neo4j",
            ],
            check=True,
            capture_output=True,
        )

        logger.info(f"✅ Backup created: {backup_dir}")
        return backup_dir

    except subprocess.CalledProcessError as e:
        logger.error(f"Backup failed: {e.stderr}")
        raise MigrationError(f"Backup failed: {e}") from e

def _restore_backup(self, backup_path: str) -> None:
    """Restore backup Neo4j."""
    import subprocess

    try:
        subprocess.run(
            [
                "neo4j-admin", "database", "load",
                f"--from-path={backup_path}",
                "--database=neo4j",
                "--overwrite-destination=true",
            ],
            check=True,
            capture_output=True,
        )

        logger.info(f"✅ Backup restored: {backup_path}")

    except subprocess.CalledProcessError as e:
        logger.error(f"Restore failed: {e.stderr}")
        raise MigrationError(f"Restore failed: {e}") from e
```

**Priorité** : **P1 - Élevé**

---

### SEC-PHASE1-14: Test POC Cleanup Non Garanti 🟠

**Fichier** : `test_neo4j_poc.py:291-298`

**Problème** :
```python
# Cleanup
logger.info("Cleaning up test data...")
approved_facts = facts.get_facts_by_status("approved", limit=100)
proposed_facts = facts.get_facts_by_status("proposed", limit=100)

for fact in approved_facts + proposed_facts:
    facts.delete_fact(fact["uuid"])
# ❌ Si exception avant cleanup → données orphelines
# ❌ Pas de finally block
```

**Impact** :
- ✅ Tests laissent données résiduelles
- ✅ Pollution database
- ✅ Tests non idempotents

**CVSS Score** : **4.5** (Moyen/Faible)

**Correctif** :

```python
# test_neo4j_poc.py
import pytest
from contextlib import contextmanager

@contextmanager
def cleanup_tenant(tenant_id: str):
    """Context manager pour cleanup automatique tenant tests."""
    from src.knowbase.neo4j_custom import get_neo4j_client

    client = get_neo4j_client()

    try:
        yield tenant_id
    finally:
        # ✅ Cleanup garanti (même si exception)
        logger.info(f"Cleaning up test tenant: {tenant_id}")

        cleanup_query = """
        MATCH (f:Fact {tenant_id: $tenant_id})
        DETACH DELETE f
        """

        try:
            client.execute_write_query(cleanup_query, {"tenant_id": tenant_id})
            logger.info(f"✅ Tenant {tenant_id} cleaned up")
        except Exception as e:
            logger.error(f"❌ Cleanup failed: {e}")

def test_performance():
    """Test 5: Performance < 50ms."""
    logger.info("TEST 5: PERFORMANCE")

    # ✅ Tenant unique par test
    tenant_id = f"test_performance_{uuid.uuid4().hex[:8]}"

    # ✅ Context manager garantit cleanup
    with cleanup_tenant(tenant_id):
        client = get_neo4j_client()
        facts = FactsQueries(client, tenant_id=tenant_id)

        # ... tests

        # ✅ Cleanup automatique en finally

# Ou pytest fixture
@pytest.fixture
def test_tenant():
    """Fixture pytest pour tenant tests."""
    tenant_id = f"test_{uuid.uuid4().hex[:8]}"

    yield tenant_id

    # ✅ Teardown automatique
    client = get_neo4j_client()
    cleanup_query = "MATCH (f:Fact {tenant_id: $tenant_id}) DETACH DELETE f"
    client.execute_write_query(cleanup_query, {"tenant_id": tenant_id})

def test_crud_facts(test_tenant):
    """Test CRUD avec fixture."""
    client = get_neo4j_client()
    facts = FactsQueries(client, tenant_id=test_tenant)

    # ... tests

    # ✅ Cleanup automatique par fixture
```

**Priorité** : **P1 - Moyen**

---

## 🟡 VULNÉRABILITÉS MOYENNES (P2)

### SEC-PHASE1-15: Pas de Monitoring Détection Anomalies 🟡

**Fichier** : Tous les fichiers

**Problème** :
- ❌ Pas de détection anomalies (ex: 1000 deletes/minute)
- ❌ Pas d'alertes si pattern suspect
- ❌ Pas de metrics Prometheus/Grafana

**Impact** :
- ✅ Attaque en cours → pas détectée
- ✅ Pas de visibility opérationnelle

**CVSS Score** : **5.0** (Moyen)

**Correctif** :

```python
# src/knowbase/monitoring/anomaly_detector.py
from typing import Dict, List
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class Anomaly:
    """Anomalie détectée."""
    timestamp: datetime
    anomaly_type: str
    severity: str  # "low", "medium", "high", "critical"
    description: str
    metadata: Dict

class AnomalyDetector:
    """Détecteur anomalies Facts operations."""

    def __init__(self, redis_client):
        self.redis = redis_client

    def check_anomalies(
        self,
        tenant_id: str,
        action: str,
        user_id: str,
    ) -> List[Anomaly]:
        """Détecte anomalies comportement utilisateur."""
        anomalies = []

        # ✅ Détection delete spike
        if action == "delete_fact":
            delete_count = self._get_action_count(tenant_id, user_id, "delete_fact", window=300)

            if delete_count > 50:  # > 50 deletes en 5min
                anomalies.append(Anomaly(
                    timestamp=datetime.utcnow(),
                    anomaly_type="delete_spike",
                    severity="critical",
                    description=f"User {user_id} deleted {delete_count} facts in 5min",
                    metadata={"tenant": tenant_id, "user": user_id, "count": delete_count},
                ))

        # ✅ Détection accès multi-tenant suspect
        accessed_tenants = self._get_accessed_tenants(user_id, window=3600)
        if len(accessed_tenants) > 5:  # Accès > 5 tenants en 1h
            anomalies.append(Anomaly(
                timestamp=datetime.utcnow(),
                anomaly_type="multi_tenant_access",
                severity="high",
                description=f"User {user_id} accessed {len(accessed_tenants)} tenants in 1h",
                metadata={"user": user_id, "tenants": accessed_tenants},
            ))

        # ✅ Détection brute-force conflict detection
        conflict_checks = self._get_action_count(tenant_id, user_id, "detect_conflicts", window=60)
        if conflict_checks > 100:  # > 100 checks/min
            anomalies.append(Anomaly(
                timestamp=datetime.utcnow(),
                anomaly_type="conflict_detection_spam",
                severity="medium",
                description=f"User {user_id} ran {conflict_checks} conflict checks in 1min",
                metadata={"tenant": tenant_id, "user": user_id, "count": conflict_checks},
            ))

        return anomalies

    def _get_action_count(self, tenant_id: str, user_id: str, action: str, window: int) -> int:
        """Compte actions dans fenêtre temporelle."""
        key = f"actions:{tenant_id}:{user_id}:{action}"

        now = datetime.utcnow().timestamp()
        window_start = now - window

        self.redis.zremrangebyscore(key, 0, window_start)
        return self.redis.zcard(key)

    def alert_anomaly(self, anomaly: Anomaly) -> None:
        """Envoie alerte anomalie."""
        logger.warning(
            f"ANOMALY DETECTED - Type: {anomaly.anomaly_type}, "
            f"Severity: {anomaly.severity}, "
            f"Description: {anomaly.description}"
        )

        # ✅ Envoyer notification (Slack, PagerDuty, etc.)
        if anomaly.severity in ["critical", "high"]:
            self._send_slack_alert(anomaly)

        # ✅ Stocker anomaly pour investigation
        self._store_anomaly(anomaly)

    def _send_slack_alert(self, anomaly: Anomaly):
        """Envoie alerte Slack."""
        # Implementation Slack webhook
        pass

    def _store_anomaly(self, anomaly: Anomaly):
        """Stocke anomaly pour investigation."""
        # Implementation stockage PostgreSQL/MongoDB
        pass
```

**Priorité** : **P2 - Moyen**

---

### SEC-PHASE1-16: Pas de Chiffrement At-Rest Facts 🟡

**Fichier** : N/A (configuration Neo4j)

**Problème** :
- ❌ Données Facts stockées en clair sur disque
- ❌ Backup non chiffrés
- ❌ Risque si disque volé/compromis

**Impact** :
- ✅ Attaquant accède disque → lit tous Facts
- ✅ Violation compliance GDPR

**CVSS Score** : **5.5** (Moyen)

**Correctif** :

**Option A : Neo4j Enterprise Encryption at Rest**
```yaml
# docker-compose.infra.yml (Neo4j Enterprise requis)
neo4j:
  environment:
    - NEO4J_dbms_security_encryption__at__rest_enabled=true
    - NEO4J_dbms_security_encryption__at__rest_provider=aes-256-gcm
  volumes:
    - ./encryption_keys:/var/lib/neo4j/encryption_keys:ro
```

**Option B : Chiffrement Filesystem (LUKS, dm-crypt)**
```bash
# Chiffrer volume Docker Neo4j
cryptsetup luksFormat /dev/sdb1
cryptsetup luksOpen /dev/sdb1 neo4j_encrypted
mkfs.ext4 /dev/mapper/neo4j_encrypted
mount /dev/mapper/neo4j_encrypted /var/lib/neo4j
```

**Option C : Application-level Encryption** (Neo4j Community)
```python
# src/knowbase/security/field_encryption.py
from cryptography.fernet import Fernet
import os

class FieldEncryption:
    """Chiffrement champs sensibles Facts."""

    def __init__(self):
        # Clé chiffrement depuis secrets manager
        key = os.getenv("FIELD_ENCRYPTION_KEY")
        if not key:
            raise ValueError("FIELD_ENCRYPTION_KEY not set")

        self.fernet = Fernet(key.encode())

    def encrypt_value(self, value: str) -> str:
        """Chiffre valeur."""
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt_value(self, encrypted: str) -> str:
        """Déchiffre valeur."""
        return self.fernet.decrypt(encrypted.encode()).decode()

# Usage
encryption = FieldEncryption()

def create_fact(self, **kwargs):
    # ✅ Chiffrer champs sensibles
    if kwargs.get("object_str"):
        kwargs["object_str"] = encryption.encrypt_value(kwargs["object_str"])

    # ... créer fact
```

**Priorité** : **P2 - Moyen** (P1 si données très sensibles)

---

### SEC-PHASE1-17: Pas de Content Security Policy Headers 🟡

**Fichier** : N/A (API FastAPI)

**Problème** :
- ❌ Pas de headers sécurité (CSP, HSTS, X-Frame-Options)
- ❌ Vulnérable clickjacking, XSS

**Impact** :
- ✅ XSS si données Facts affichées sans sanitization
- ✅ Clickjacking possible

**CVSS Score** : **5.0** (Moyen)

**Correctif** :

```python
# src/knowbase/api/middleware/security_headers.py
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware ajoutant security headers."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # ✅ Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )

        # ✅ HSTS (HTTPS strict)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

        # ✅ Anti-clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # ✅ Anti-MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # ✅ XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # ✅ Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # ✅ Permissions policy
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        return response

# src/knowbase/api/main.py
from fastapi import FastAPI
app = FastAPI()

# ✅ Ajouter middleware
app.add_middleware(SecurityHeadersMiddleware)
```

**Priorité** : **P2 - Moyen**

---

### SEC-PHASE1-18: Pas de Validation Schema Version Migrations 🟡

**Fichier** : `src/knowbase/neo4j_custom/migrations.py:36-59`

**Problème** :
```python
def get_current_version(self) -> int:
    """Retourne version schéma actuelle."""
    query = """
    MATCH (v:SchemaVersion)
    RETURN v.version as version
    ORDER BY v.version DESC
    LIMIT 1
    """
    # ❌ Pas de validation version (int positif)
    # ❌ Pas de détection version incohérente
```

**Impact** :
- ✅ Version corrompue → migrations échouent
- ✅ Rollback impossible

**CVSS Score** : **4.5** (Moyen/Faible)

**Correctif** :

```python
def get_current_version(self) -> int:
    """Retourne version schéma actuelle (avec validation)."""
    query = """
    MATCH (v:SchemaVersion)
    RETURN v.version as version
    ORDER BY v.version DESC
    LIMIT 1
    """

    try:
        results = self.client.execute_query(query)
        if results:
            version = results[0]["version"]

            # ✅ Validation type
            if not isinstance(version, int):
                raise MigrationError(f"Invalid version type: {type(version)}")

            # ✅ Validation range
            if version < 0 or version > 1000:
                raise MigrationError(f"Invalid version number: {version}")

            return version

        return 0

    except Exception as e:
        logger.warning(f"No schema version found: {e}")
        return 0

def set_version(self, version: int) -> None:
    """Enregistre version schéma (avec validation)."""
    # ✅ Validation version
    if not isinstance(version, int) or version < 0:
        raise ValueError(f"Invalid version: {version}")

    # ✅ Vérifier cohérence (version + 1)
    current = self.get_current_version()
    if version != current + 1 and version != 0:
        logger.warning(
            f"Version jump detected: {current} → {version} "
            "(expected {current + 1})"
        )

    query = """
    CREATE (v:SchemaVersion {
      version: $version,
      applied_at: datetime(),
      applied_by: $applied_by
    })
    RETURN v
    """

    try:
        self.client.execute_write_query(
            query,
            {
                "version": version,
                "applied_by": os.getenv("USER", "unknown"),
            }
        )
        logger.info(f"✅ Schema version set to {version}")

    except Exception as e:
        logger.error(f"Failed to set schema version: {e}")
        raise MigrationError(f"Failed to set version: {e}") from e
```

**Priorité** : **P2 - Moyen**

---

### SEC-PHASE1-19: Credentials Default Fallback Insecure 🟡

**Fichier** : `src/knowbase/neo4j_custom/client.py:68-70`

**Problème** :
```python
self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
self.user = user or os.getenv("NEO4J_USER", "neo4j")
self.password = password or os.getenv("NEO4J_PASSWORD", "neo4j_password")
# ❌ Fallback "neo4j_password" faible
```

**Impact** :
- ✅ Si .env non défini → credentials faibles par défaut
- ✅ Facilite attaques

**CVSS Score** : **6.5** (Moyen/Élevé)

**Correctif** :

```python
# src/knowbase/neo4j_custom/client.py
def __init__(self, ...):
    self.uri = uri or os.getenv("NEO4J_URI")
    self.user = user or os.getenv("NEO4J_USER")
    self.password = password or os.getenv("NEO4J_PASSWORD")

    # ✅ Validation credentials requis
    if not self.uri:
        raise ValueError("NEO4J_URI is required (no default)")

    if not self.user:
        raise ValueError("NEO4J_USER is required (no default)")

    if not self.password:
        raise ValueError("NEO4J_PASSWORD is required (no default)")

    # ✅ Validation force password (longueur min)
    if len(self.password) < 16:
        raise ValueError(
            f"NEO4J_PASSWORD too weak (min 16 chars, got {len(self.password)})"
        )

    # ... reste
```

**Priorité** : **P2 - Moyen**

---

### SEC-PHASE1-20: Pas de Secrets Rotation 🟡

**Fichier** : `.env`

**Problème** :
- ❌ Credentials Neo4j jamais changés
- ❌ Pas de rotation automatique

**Impact** :
- ✅ Credentials compromis → persistance long terme
- ✅ Violation compliance (rotation 90j requise)

**CVSS Score** : **5.0** (Moyen)

**Correctif** :

```python
# scripts/rotate_neo4j_password.py
"""Script rotation password Neo4j (à exécuter tous les 90j)."""
import os
import secrets
import string
from neo4j import GraphDatabase

def generate_strong_password(length: int = 32) -> str:
    """Génère password sécurisé."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def rotate_neo4j_password():
    """Rotate Neo4j password."""
    # Connexion avec ancien password
    old_password = os.getenv("NEO4J_PASSWORD")
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, old_password))

    # Générer nouveau password
    new_password = generate_strong_password()

    # Changer password Neo4j
    with driver.session() as session:
        session.run(
            f"ALTER USER {user} SET PASSWORD $new_password",
            new_password=new_password
        )

    driver.close()

    # ✅ Mettre à jour .env (ou secrets manager)
    print(f"✅ Password rotated. New password: {new_password}")
    print("⚠️ Update .env or secrets manager with new password")

    # ✅ Notifier ops team
    send_notification(f"Neo4j password rotated for user {user}")

if __name__ == "__main__":
    rotate_neo4j_password()
```

**Automatisation rotation** :
```yaml
# .github/workflows/rotate-secrets.yml
name: Rotate Neo4j Credentials
on:
  schedule:
    - cron: '0 0 1 */3 *'  # Tous les 3 mois

jobs:
  rotate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Rotate Neo4j password
        run: python scripts/rotate_neo4j_password.py
      - name: Update AWS Secrets Manager
        run: |
          aws secretsmanager update-secret \
            --secret-id neo4j-password \
            --secret-string $NEW_PASSWORD
```

**Priorité** : **P2 - Moyen**

---

## 🟢 VULNÉRABILITÉS FAIBLES (P3)

### SEC-PHASE1-21: Logs Verbeux en Debug Mode 🟢

**Fichier** : `src/knowbase/neo4j_custom/client.py:195-198`

**Problème** :
```python
logger.debug(f"Query executed - Records: {len(records)}, Query: {query[:100]}...")
# ✅ DEBUG level ok, mais attention en production
```

**Impact** :
- ✅ Si DEBUG activé en production → logs excessifs

**CVSS Score** : **3.0** (Faible)

**Correctif** : Configuration logging stricte (déjà couvert SEC-PHASE1-05)

**Priorité** : **P3 - Faible**

---

### SEC-PHASE1-22: Pas de Version Module dans __init__.py 🟢

**Fichier** : `src/knowbase/neo4j_custom/__init__.py:33`

**Problème** :
```python
__version__ = "1.0.0"
# ❌ Version hardcodée, pas de tracking
```

**Impact** :
- ✅ Difficulté tracking versions déployées
- ✅ Pas de compatibility check

**CVSS Score** : **2.0** (Faible)

**Correctif** :

```python
# src/knowbase/neo4j_custom/__init__.py
import importlib.metadata

try:
    __version__ = importlib.metadata.version("knowbase")
except importlib.metadata.PackageNotFoundError:
    __version__ = "1.0.0-dev"

# Version checking
MIN_NEO4J_VERSION = "5.0.0"

def check_neo4j_version(client):
    """Vérifie compatibilité version Neo4j."""
    info = client.get_server_info()
    server_version = info.get("versions", ["unknown"])[0]

    if server_version < MIN_NEO4J_VERSION:
        raise RuntimeError(
            f"Neo4j version {server_version} not supported "
            f"(min: {MIN_NEO4J_VERSION})"
        )
```

**Priorité** : **P3 - Faible**

---

## 📊 Priorisation Correctifs

### Phase Immédiate (Avant Phase 2 - 1 jour)

1. 🔴 **SEC-PHASE1-01** : Activer TLS (`encrypted: True`)
2. 🔴 **SEC-PHASE1-02** : Retirer credentials des logs
3. 🔴 **SEC-PHASE1-03** : Implémenter ACL basique (validation tenant_id)
4. 🔴 **SEC-PHASE1-04** : Validation stricte noms constraints/indexes
5. 🔴 **SEC-PHASE1-05** : Désactiver logs queries (ou sanitize)
6. 🔴 **SEC-PHASE1-06** : Implémenter audit trail basique

**Temps estimé** : **1 jour**

---

### Phase Court Terme (Phase 2-3 - 2-3 jours)

7. 🟠 **SEC-PHASE1-07** : Ajouter timeouts queries
8. 🟠 **SEC-PHASE1-08** : Sécuriser connection pool
9. 🟠 **SEC-PHASE1-09** : Validation Pydantic stricte Facts
10. 🟠 **SEC-PHASE1-10** : Rate limiting Redis
11. 🟠 **SEC-PHASE1-11** : Thread-safe singleton
12. 🟠 **SEC-PHASE1-12** : Validation path traversal
13. 🟠 **SEC-PHASE1-13** : Backup automatique migrations
14. 🟠 **SEC-PHASE1-14** : Cleanup tests garanti

**Temps estimé** : **2-3 jours**

---

### Phase Moyen Terme (Phase 4-5 - 1 semaine)

15. 🟡 **SEC-PHASE1-15** : Monitoring anomalies
16. 🟡 **SEC-PHASE1-16** : Chiffrement at-rest (si requis)
17. 🟡 **SEC-PHASE1-17** : Security headers API
18. 🟡 **SEC-PHASE1-18** : Validation schema version
19. 🟡 **SEC-PHASE1-19** : Retirer fallback credentials
20. 🟡 **SEC-PHASE1-20** : Secrets rotation

**Temps estimé** : **1 semaine**

---

### Phase Long Terme (Phase 6+ - Continu)

21. 🟢 **SEC-PHASE1-21** : Configuration logging production
22. 🟢 **SEC-PHASE1-22** : Version tracking

**Temps estimé** : **Continu**

---

## 🛡️ Checklist Durcissement Phase 1

### Authentification & Autorisation

- [ ] TLS activé (`encrypted: True`)
- [ ] Credentials complexes (> 16 chars)
- [ ] Pas de fallback credentials faibles
- [ ] ACL/RBAC implémenté
- [ ] Validation tenant_id stricte
- [ ] Audit trail complet

### Validation Données

- [ ] Validation Pydantic Facts
- [ ] Sanitization injection Cypher
- [ ] Path traversal prevention
- [ ] Range validation values
- [ ] Unit normalization

### Infrastructure

- [ ] Timeouts queries configurés
- [ ] Connection pool sécurisé
- [ ] Rate limiting activé
- [ ] Thread-safe singleton
- [ ] Resource limits

### Monitoring & Logging

- [ ] Logs sans données sensibles
- [ ] Anomaly detection
- [ ] Métriques Prometheus
- [ ] Alertes critiques
- [ ] Audit trail queryable

### Backups & Recovery

- [ ] Backup automatique migrations
- [ ] Rollback testé
- [ ] Chiffrement at-rest (si requis)
- [ ] Disaster recovery plan

---

## 🔧 Fichiers Correctifs à Créer

1. `src/knowbase/neo4j_custom/validators.py` (Pydantic validation)
2. `src/knowbase/security/acl.py` (Access Control List)
3. `src/knowbase/security/audit.py` (Audit trail)
4. `src/knowbase/security/rate_limiter.py` (Rate limiting)
5. `src/knowbase/security/field_encryption.py` (Chiffrement champs)
6. `src/knowbase/monitoring/anomaly_detector.py` (Détection anomalies)
7. `scripts/rotate_neo4j_password.py` (Rotation credentials)
8. `config/rate_limits.yaml` (Configuration rate limits)
9. `config/logging_production.yaml` (Logging production)
10. `docs/SECURITY_POLICY_PHASE1.md` (Politique sécurité)

---

## 📚 Références

- **Neo4j Security Best Practices** : https://neo4j.com/docs/operations-manual/current/security/
- **OWASP Top 10** : https://owasp.org/www-project-top-ten/
- **CWE-89 (SQL Injection)** : https://cwe.mitre.org/data/definitions/89.html
- **NIST Cybersecurity Framework** : https://www.nist.gov/cyberframework
- **GDPR Compliance** : https://gdpr.eu/

---

**Créé le** : 2025-10-03
**Auteur** : Audit Sécurité Phase 1 - Module Neo4j Custom
**Version** : 1.0
**Statut** : 🔴 ACTION REQUISE URGENTE

**Prochaines étapes** :
1. Implémenter correctifs P0 (1 jour)
2. Review code avec équipe sécurité
3. Tests sécurité automatisés
4. Audit externe Phase 2 après correctifs
