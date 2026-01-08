# Analyse et Centralisation des Timeouts - Pipeline d'Import

**Problème identifié:** Documents de 230 slides prennent jusqu'à 45 minutes à traiter, mais les timeouts actuels ne supportent que 30 minutes maximum.

**Objectif:** Centraliser la configuration des timeouts pour permettre le traitement de documents complexes (45+ minutes) avec une seule variable de configuration.

---

## 📊 Mapping Complet des Timeouts (Hiérarchie)

### **Niveau 1 - RQ Job Queue (Timeout Global)**
**Fichier:** `src/knowbase/ingestion/queue/connection.py:10`

```python
DEFAULT_JOB_TIMEOUT = int(os.getenv("INGESTION_JOB_TIMEOUT", "7200"))  # 2 heures par défaut
```

**Rôle:** Timeout maximum pour l'exécution complète d'un job d'ingestion (niveau worker RQ)
- **Valeur actuelle:** 7200s (2 heures) ✅ SUFFISANT pour 45 min
- **Impact:** Si dépassé → job killed par RQ, marqué comme failed
- **Usage:** `docker-compose.yml` ne définit pas cette variable → utilise défaut 2h

---

### **Niveau 2 - OSMOSE Pipeline (Timeout Adaptatif)**

#### **2.1 Configuration Centrale**
**Fichier:** `src/knowbase/config/settings.py:81`

```python
osmose_timeout_seconds: int = Field(default=3600, alias="OSMOSE_TIMEOUT_SECONDS")
```

**Valeur actuelle dans `docker-compose.yml:95`:**
```yaml
OSMOSE_TIMEOUT_SECONDS: "1800"  # 30 minutes
```

#### **2.2 Calcul Adaptatif**
**Fichier:** `src/knowbase/ingestion/osmose_agentique.py:283-325`

```python
def _calculate_adaptive_timeout(self, num_segments: int) -> int:
    """
    Formule adaptive timeout:
    base_time = 120s (2 min)
    time_per_segment = 90s
    fsm_overhead = 120s (2 min)

    calculated_timeout = base_time + (time_per_segment * num_segments) + fsm_overhead

    Bornes:
    - min_timeout = 900s (15 minutes) ⚠️ TROP BAS pour 45 min
    - max_timeout = OSMOSE_TIMEOUT_SECONDS (1800s = 30 min) ⚠️ TROP BAS pour 45 min

    Exemples:
    - 1 segment:  120 + 90 + 120 = 330s → clamped à min=900s
    - 10 segments: 120 + 900 + 120 = 1140s (19 min)
    - 60 segments: 120 + 5400 + 120 = 5640s → clamped à max=1800s (30 min)
    """
    configured_timeout = int(os.getenv("OSMOSE_TIMEOUT_SECONDS", "3600"))
    min_timeout = 900  # 15 minutes
    max_timeout = configured_timeout

    adaptive_timeout = max(min_timeout, min(calculated_timeout, max_timeout))
    return adaptive_timeout
```

**Rôle:** Timeout adaptatif pour le processing OSMOSE complet
- **Valeur actuelle:** min=900s, max=1800s ❌ INSUFFISANT pour 45 min (2700s)
- **Impact:** Si dépassé → `Exception: OSMOSE processing failed: Timeout or max steps reached`
- **Utilisation:** Assigné à `state.timeout_seconds` dans le SupervisorAgent FSM

---

### **Niveau 3 - Agent State (Timeout FSM)**
**Fichier:** `src/knowbase/agents/base.py:71`

```python
timeout_seconds: int = 3600  # 60 min/doc (nécessaire pour gros documents 200+ slides)
```

**Fichier:** `src/knowbase/agents/base.py:162`

```python
if elapsed > state.timeout_seconds:
    # Timeout FSM dépassé
```

**Rôle:** Timeout pour l'exécution de la FSM (Finite State Machine) de l'agent
- **Valeur par défaut:** 3600s (1h) ✅ SUFFISANT pour 45 min
- **Mais:** Cette valeur est ÉCRASÉE par `adaptive_timeout` dans `osmose_agentique.py:471` et `osmose_agentique.py:495`
- **Impact:** Si dépassé → FSM s'arrête, retourne erreur

---

### **Niveau 4 - Semantic Operations (Timeouts Par Opération)**
**Fichier:** `src/knowbase/semantic/config.py:162-165`

```python
topic_segmentation_timeout: int = 60      # 1 minute
concept_extraction_timeout: int = 120     # 2 minutes
indexing_timeout: int = 90                # 1.5 minutes
linking_timeout: int = 60                 # 1 minute
```

**Rôle:** Timeouts pour opérations sémantiques individuelles (OSMOSE Phase 1.5)
- **Valeur actuelle:** 60-120s par opération
- **Impact:** Timeouts courts pour opérations atomiques, ne bloquent pas documents longs
- **À conserver:** Ces timeouts sont pour des opérations unitaires, pas pour le document complet

---

### **Niveau 5 - Clients Externes (Timeouts Connexion/Requête)**

#### **5.1 Qdrant (Vector DB)**
**Fichier:** `src/knowbase/common/clients/qdrant_client.py:33-34`

```python
return QdrantClient(url=settings.qdrant_url, timeout=300)  # 5 minutes
```

**Rôle:** Timeout pour requêtes Qdrant (upsert, search)
- **Valeur:** 300s (5 min)
- **Impact:** Si dépassé → QdrantException
- **À conserver:** Opération unitaire, 5 min suffisant

#### **5.2 Neo4j (Graph DB)**
**Fichier:** `src/knowbase/common/clients/neo4j_client.py:63`

```python
connection_acquisition_timeout=120  # 2 minutes
```

**Fichier:** `src/knowbase/neo4j_custom/client.py:52`

```python
connection_timeout: float = 30.0  # 30 secondes
```

**Rôle:** Timeout acquisition connexion Neo4j
- **Valeur:** 120s ou 30s selon client
- **Impact:** Si dépassé → Neo4jException
- **À conserver:** Opération connexion rapide

#### **5.3 Redis (Queue/Cache)**
**Fichier:** `src/knowbase/common/clients/redis_client.py:60-61`

```python
socket_timeout=5,
socket_connect_timeout=5  # 5 secondes
```

**Rôle:** Timeout socket Redis
- **Valeur:** 5s
- **Impact:** Reconnexion automatique si dépassé
- **À conserver:** Opération réseau rapide

---

### **Niveau 6 - Subprocess (Timeouts Conversion/Extraction)**

#### **6.1 PPTX → PDF Conversion**
**Fichier:** `src/knowbase/ingestion/components/converters/pptx_to_pdf.py:117`

```python
result = run_cmd(command, timeout=600, env=env)  # 10 minutes
```

**Rôle:** Timeout conversion PPTX → PDF (LibreOffice)
- **Valeur:** 600s (10 min)
- **Impact:** Si dépassé → TimeoutError, fallback sans PDF
- **À ajuster?** 10 min suffisant pour 230 slides, mais dépend de la complexité

#### **6.2 Subprocess Général**
**Fichier:** `src/knowbase/ingestion/components/utils/subprocess_utils.py:13`

```python
def run_cmd(cmd: List[str], timeout: int = 120, ...):
    # timeout par défaut: 2 minutes
```

**Rôle:** Timeout pour subprocess génériques
- **Valeur:** 120s (2 min) par défaut
- **À conserver:** Opérations courtes

---

### **Niveau 7 - API Jobs (Timeouts RQ Spécifiques)**
**Fichier:** `src/knowbase/api/routers/entity_types.py`

```python
# Ligne 1074
job_timeout="10m"  # Jobs canonicalization

# Lignes 1448, 1602
job_timeout="30m"  # Jobs bulk operations
```

**Rôle:** Timeouts spécifiques pour jobs API (différents de l'ingestion)
- **Valeur:** 10-30 min
- **À conserver:** Scope différent (API background jobs)

---

### **Niveau 8 - Circuit Breakers (Timeouts Résilience)**
**Fichier:** `src/knowbase/common/circuit_breaker.py:52`

```python
recovery_timeout: int = 60  # 60 secondes
```

**Fichier:** `src/knowbase/ontology/llm_canonicalizer.py:45`

```python
def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
```

**Rôle:** Timeout recovery pour circuit breakers (résilience LLM)
- **Valeur:** 60s
- **À conserver:** Mécanisme de résilience, indépendant du document

---

## 🎯 Analyse de la Chaîne Critique (45 Minutes Document)

### **Chemin d'Exécution Typique pour Document 230 Slides**

```
RQ Job (INGESTION_JOB_TIMEOUT = 7200s) ✅ OK
  │
  ├─> PPTX Pipeline (process_pptx)
  │    │
  │    ├─> PPTX → PDF Conversion (timeout=600s) ✅ OK (10 min suffisant)
  │    │
  │    ├─> OSMOSE Agentique Processing ⚠️ GOULOT D'ÉTRANGLEMENT
  │    │    │
  │    │    ├─> Adaptive Timeout Calculation
  │    │    │    └─> min=900s, max=OSMOSE_TIMEOUT_SECONDS=1800s ❌ TROP BAS (30 min < 45 min)
  │    │    │
  │    │    ├─> SupervisorAgent FSM (state.timeout_seconds = adaptive_timeout)
  │    │    │    │
  │    │    │    ├─> Segmentation Phase (multiple LLM calls)
  │    │    │    ├─> Extraction Phase (LLM + Neo4j + Qdrant ops)
  │    │    │    ├─> Indexation Phase
  │    │    │    └─> Verification Phase
  │    │    │
  │    │    └─> Timeout Check (agents/base.py:162)
  │    │         └─> if elapsed > state.timeout_seconds → ❌ FAIL à 30 min
  │    │
  │    └─> Qdrant Upsert (timeout=300s) ✅ OK (opération unitaire)
  │
  └─> Neo4j Storage (connection_timeout=120s) ✅ OK
```

### **Problème Identifié**

**Le goulot d'étranglement est à Niveau 2 (OSMOSE):**

1. **`OSMOSE_TIMEOUT_SECONDS=1800s` (30 min) dans docker-compose.yml**
   - Utilisé comme `max_timeout` dans le calcul adaptatif
   - Document 230 slides prend 45 min → timeout à 30 min → FAIL

2. **`min_timeout=900s` (15 min) dans osmose_agentique.py**
   - Même avec peu de segments, garantit 15 min minimum
   - Mais insuffisant pour documents complexes

3. **Timeout adaptatif écrase `agents/base.py:71` (3600s = 1h)**
   - La valeur par défaut de 1h serait suffisante
   - Mais elle est remplacée par `adaptive_timeout` (max 30 min)

### **Solution Requise**

Pour supporter 45 minutes de processing:
- **OSMOSE_TIMEOUT_SECONDS doit être >= 2700s (45 min)**
- **Recommandation: 3600s (1h)** pour avoir une marge

---

## 🔧 Proposition de Centralisation

### **Approche 1: Variable Centrale Unique (SIMPLE) ✅ RECOMMANDÉ**

**Principe:** Une seule variable d'environnement contrôle tous les timeouts de pipeline.

#### **Configuration `.env` / `docker-compose.yml`**

```yaml
# Dans docker-compose.yml (service: ingestion-worker)
environment:
  # ========== TIMEOUT CENTRAL ==========
  # Durée maximale de traitement d'un document (en secondes)
  # Recommandation: 3600s (1h) pour documents jusqu'à 300 slides
  # Peut être augmenté pour documents très complexes (ex: 5400s = 1h30)
  MAX_DOCUMENT_PROCESSING_TIME: "3600"  # 1 heure

  # ========== TIMEOUTS DÉRIVÉS (calculés automatiquement) ==========
  # RQ Job Timeout = MAX_DOCUMENT_PROCESSING_TIME * 1.5 (buffer 50%)
  INGESTION_JOB_TIMEOUT: "5400"  # Auto: 3600 * 1.5

  # OSMOSE Timeout = MAX_DOCUMENT_PROCESSING_TIME
  OSMOSE_TIMEOUT_SECONDS: "3600"  # Auto: MAX_DOCUMENT_PROCESSING_TIME
```

#### **Modifications Code**

**1. `src/knowbase/config/settings.py`**

```python
# Ajout timeout central
class Settings(BaseSettings):
    # Timeout central (défaut 1h)
    max_document_processing_time: int = Field(
        default=3600,
        alias="MAX_DOCUMENT_PROCESSING_TIME",
        description="Durée maximale de traitement d'un document (secondes)"
    )

    # Timeouts dérivés (calculés si non fournis)
    @property
    def ingestion_job_timeout(self) -> int:
        """RQ job timeout avec buffer 50%"""
        env_value = os.getenv("INGESTION_JOB_TIMEOUT")
        if env_value:
            return int(env_value)
        return int(self.max_document_processing_time * 1.5)

    @property
    def osmose_timeout_seconds(self) -> int:
        """OSMOSE timeout = max document time"""
        env_value = os.getenv("OSMOSE_TIMEOUT_SECONDS")
        if env_value:
            return int(env_value)
        return self.max_document_processing_time
```

**2. `src/knowbase/ingestion/queue/connection.py`**

```python
from knowbase.config.settings import get_settings

settings = get_settings()
DEFAULT_JOB_TIMEOUT = settings.ingestion_job_timeout  # Utilise property
```

**3. `src/knowbase/ingestion/osmose_agentique.py`**

```python
def _calculate_adaptive_timeout(self, num_segments: int) -> int:
    settings = get_settings()

    # Formule adaptative
    base_time = 120
    time_per_segment = 90
    fsm_overhead = 120
    calculated_timeout = base_time + (time_per_segment * num_segments) + fsm_overhead

    # Bornes avec timeout central
    min_timeout = 600  # 10 minutes (réduit, car max_timeout augmenté)
    max_timeout = settings.osmose_timeout_seconds  # Utilise property (3600s par défaut)

    adaptive_timeout = max(min_timeout, min(calculated_timeout, max_timeout))

    logger.info(
        f"⏱️ Adaptive timeout: {adaptive_timeout}s "
        f"(calculated={calculated_timeout}s, max={max_timeout}s, segments={num_segments})"
    )
    return adaptive_timeout
```

**4. `docker-compose.yml`**

```yaml
# SERVICE: ingestion-worker
environment:
  # ========== CONFIGURATION TIMEOUT CENTRALISÉE ==========
  # ⚙️ Ajuster cette valeur unique pour contrôler tous les timeouts de pipeline
  # Recommandations:
  #   - 3600s (1h)   → Documents standards (< 300 slides)
  #   - 5400s (1h30) → Documents complexes (300-500 slides)
  #   - 7200s (2h)   → Documents très complexes (> 500 slides)
  MAX_DOCUMENT_PROCESSING_TIME: "3600"  # 🎯 VARIABLE CENTRALE

  # Les timeouts ci-dessous sont OPTIONNELS (calculés auto si absents)
  # Décommenter uniquement pour override manuel:
  # INGESTION_JOB_TIMEOUT: "5400"       # RQ job timeout (auto: MAX * 1.5)
  # OSMOSE_TIMEOUT_SECONDS: "3600"      # OSMOSE timeout (auto: MAX)
```

#### **Avantages Approche 1**

✅ **Simplicité:** 1 seule variable à modifier (`MAX_DOCUMENT_PROCESSING_TIME`)
✅ **Cohérence:** Tous les timeouts dérivés calculés automatiquement
✅ **Documentation:** Valeurs recommandées claires dans docker-compose.yml
✅ **Backward compatible:** Variables explicites (`OSMOSE_TIMEOUT_SECONDS`) peuvent override
✅ **Flexibilité:** Peut augmenter ponctuellement pour documents très complexes

---

### **Approche 2: Profils de Timeout (COMPLEXE)**

**Principe:** Profils prédéfinis (small, medium, large, xlarge) avec timeouts configurés.

**Configuration `.env`**

```bash
TIMEOUT_PROFILE=large  # Options: small, medium, large, xlarge, custom
```

**Mapping Profils**

```python
TIMEOUT_PROFILES = {
    "small": {
        "max_document_time": 1800,    # 30 min
        "rq_job_timeout": 2700,       # 45 min
        "osmose_timeout": 1800,       # 30 min
    },
    "medium": {
        "max_document_time": 3600,    # 1h
        "rq_job_timeout": 5400,       # 1h30
        "osmose_timeout": 3600,       # 1h
    },
    "large": {
        "max_document_time": 5400,    # 1h30
        "rq_job_timeout": 8100,       # 2h15
        "osmose_timeout": 5400,       # 1h30
    },
    "xlarge": {
        "max_document_time": 7200,    # 2h
        "rq_job_timeout": 10800,      # 3h
        "osmose_timeout": 7200,       # 2h
    },
}
```

**Inconvénients:**
❌ Complexité ajoutée sans bénéfice clair
❌ Moins flexible que variable unique
❌ Nécessite maintenance des profils

---

## 🚀 Recommandation Finale

### **Solution Immédiate (Quick Fix)**

**Pour résoudre le problème actuel (45 min timeout):**

**Modifier `docker-compose.yml` ligne 95:**

```yaml
# AVANT
OSMOSE_TIMEOUT_SECONDS: "1800"  # 30 minutes ❌ TROP BAS

# APRÈS
OSMOSE_TIMEOUT_SECONDS: "3600"  # 1 heure ✅ SUFFISANT pour 45 min
```

**Puis redémarrer le worker:**

```bash
docker-compose restart ingestion-worker
```

**Impact:** Documents jusqu'à 1h seront supportés.

---

### **Solution Long Terme (Architecture Centralisée)**

**Implémenter Approche 1:**

1. **Ajouter variable centrale dans `config/settings.py`**
   - `max_document_processing_time` avec properties dérivées

2. **Modifier `queue/connection.py`**
   - Utiliser `settings.ingestion_job_timeout`

3. **Modifier `osmose_agentique.py`**
   - Utiliser `settings.osmose_timeout_seconds`
   - Réduire `min_timeout` de 900s à 600s (car max_timeout augmenté)

4. **Documenter dans `docker-compose.yml`**
   - Variable `MAX_DOCUMENT_PROCESSING_TIME` avec recommandations

5. **Tests de validation**
   - Tester avec document 230 slides (45 min attendu)
   - Vérifier logs timeout adaptatif
   - Valider que RQ job timeout ne kill pas avant OSMOSE timeout

---

## 📝 Timeouts à NE PAS Toucher

Ces timeouts sont pour des opérations atomiques et doivent rester inchangés:

- **Clients (Qdrant, Neo4j, Redis):** Opérations individuelles rapides
- **Subprocess conversions:** 10 min suffisant pour PPTX → PDF
- **Semantic operations (60-120s):** Opérations sémantiques unitaires
- **Circuit breakers (60s):** Mécanisme résilience
- **API jobs (10-30m):** Scope différent (pas ingestion documents)

---

## 🔍 Validation Post-Implémentation

### **Tests à Exécuter**

1. **Document court (< 50 slides, ~5 min attendu)**
   - Vérifier timeout adaptatif calculé correctement
   - Confirmer aucun timeout prématuré

2. **Document moyen (100-150 slides, ~20 min attendu)**
   - Vérifier logs timeout adaptatif
   - Confirmer traitement complet

3. **Document complexe (230 slides, ~45 min attendu)**
   - **Test critique:** Doit compléter sans timeout
   - Vérifier logs: `adaptive_timeout` doit être >= 2700s
   - Confirmer RQ job timeout >= OSMOSE timeout

### **Logs à Surveiller**

```
⏱️ Adaptive timeout: 3600s (calculated=5640s, max=3600s, segments=60)
```

Si `adaptive_timeout < temps_réel_processing` → Ajuster `MAX_DOCUMENT_PROCESSING_TIME`

---

**Date:** 2025-11-17
**Auteur:** Claude Code
**Contexte:** Migration OSMOSE Phase 2 - Support documents complexes (230+ slides)
