# Plateforme RAG Hybride (Qdrant + Neo4j Native) — North Star

**Date** : 2025-10-03
**Version** : 2.0 (Neo4j Native)
**Statut** : 🟢 Architecture validée

> **Évolution majeure** : Migration de Graphiti vers Neo4j Native + Custom Layer pour gouvernance intelligente des facts métier.

---

## 1) Vision Produit (North Star)

### Proposition de Valeur Unique

**Plateforme RAG avec gouvernance intelligente des facts métier** permettant :

1. **Détection automatique de contradictions** sur données quantifiables
   - Exemple : "SLA = 99.7%" vs "SLA = 99.5%" → conflit détecté automatiquement

2. **Timeline temporelle complète** des valeurs métier
   - Traçabilité : Quelle valeur était vraie à quelle date ?

3. **Workflow de validation** avec approbation expert
   - Facts proposés → review → approuvés/rejetés

4. **Réponses directes fiables** (pas juste chunks pertinents)
   - "Quel est le SLA ?" → "99.7%" (avec source et confiance)

### Différenciateur Clé

❌ **Pas un RAG classique** : Recherche chunks + synthèse LLM
✅ **RAG Intelligent** : Facts structurés + Détection conflits + Gouvernance + Timeline

---

## 2) Principes d'Architecture (Non Négociables)

### A. Séparation Nette des Responsabilités

```
┌─────────────────────────────────────────────────────────────┐
│                    ARCHITECTURE CIBLE                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐      ┌──────────────┐     ┌───────────┐ │
│  │   QDRANT     │      │   NEO4J      │     │  POSTGRES │ │
│  │  (Vector DB) │      │ (Graph + KG) │     │ (Metadata)│ │
│  └──────────────┘      └──────────────┘     └───────────┘ │
│         │                      │                    │      │
│         └──────────────────────┼────────────────────┘      │
│                                │                           │
│  ┌─────────────────────────────▼────────────────────────┐  │
│  │          CUSTOM FACTS GOVERNANCE LAYER               │  │
│  │  • Facts structurés (subject, predicate, value)      │  │
│  │  • Détection conflits (CONTRADICTS, OVERRIDES, ...)  │  │
│  │  • Workflow proposed → approved                      │  │
│  │  • Timeline bi-temporelle (valid_from/until)         │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Qdrant** : Mémoire textuelle (chunks)
- Recherche sémantique vectorielle
- Schéma core stable (`text`, `language`, `document`, `chunk`)
- Extensibilité via `custom_metadata`

**Neo4j** : Sémantique métier + Facts structurés
- **Entities** : Concepts métier (ex: "SAP S/4HANA Cloud")
- **Relations** : Liens sémantiques (ex: "USES_INTERFACE")
- **Facts** (first-class nodes) : Assertions quantifiables structurées
  ```cypher
  (:Fact {
    subject: "SAP S/4HANA Cloud",
    predicate: "SLA_garantie",
    object: "99.7%",
    value: 99.7,
    unit: "%",
    fact_type: "SERVICE_LEVEL",
    status: "proposed",
    valid_from: datetime("2024-01-01"),
    valid_until: null
  })
  ```

**PostgreSQL** : Metadata applicative (futur)
- Historique imports
- Audit trail
- User management

---

### B. Facts comme First-Class Citizens

**Schéma Neo4j Facts** (structure canonique) :

```cypher
// Node Fact (entité indépendante)
CREATE (f:Fact {
  // Identification
  uuid: randomUUID(),
  tenant_id: "default",  // Multi-tenancy (CRITICAL: toujours filtrer sur ce champ)

  // Triplet RDF étendu
  subject: "SAP S/4HANA Cloud, Private Edition",
  predicate: "SLA_garantie",
  object: "99.7%",

  // Valeur structurée (pour comparaison directe)
  value: 99.7,
  unit: "%",
  value_type: "percentage",

  // Classification
  fact_type: "SERVICE_LEVEL",  // SERVICE_LEVEL, DATA_RETENTION, CAPACITY_LIMIT, COST, etc.

  // Gouvernance
  status: "proposed",  // proposed, approved, rejected, conflicted
  confidence: 0.95,

  // Temporalité (bi-temporelle)
  valid_from: datetime("2024-01-01"),  // Valid time (quand le fact est vrai métier)
  valid_until: null,
  created_at: datetime(),              // Transaction time (quand enregistré en base)
  updated_at: datetime(),

  // Traçabilité
  source_chunk_id: "chunk_uuid_123",
  source_document: "SAP_S4HANA_Cloud_SLA_2024.pptx",
  approved_by: null,
  approved_at: null,

  // Provenance
  extraction_method: "llm_vision",
  extraction_model: "claude-3-5-sonnet-20241022",
  extraction_prompt_id: "fact_extraction_v2"
})

// Relation vers Entity (séparation claire)
MATCH (e:Entity {name: "SAP S/4HANA Cloud, Private Edition"})
CREATE (f)-[:ABOUT]->(e)
```

**Index Neo4j** (performance + multi-tenancy) :
```cypher
// Index unicité
CREATE CONSTRAINT fact_uuid IF NOT EXISTS FOR (f:Fact) REQUIRE f.uuid IS UNIQUE;

// Index multi-tenancy (CRITICAL: performances isolation tenant)
CREATE INDEX fact_tenant IF NOT EXISTS FOR (f:Fact) ON (f.tenant_id);

// Index recherche rapide
CREATE INDEX fact_tenant_subject_predicate IF NOT EXISTS FOR (f:Fact) ON (f.tenant_id, f.subject, f.predicate);
CREATE INDEX fact_tenant_status IF NOT EXISTS FOR (f:Fact) ON (f.tenant_id, f.status);
CREATE INDEX fact_type IF NOT EXISTS FOR (f:Fact) ON (f.fact_type);

// Index temporel
CREATE INDEX fact_valid_from IF NOT EXISTS FOR (f:Fact) ON (f.valid_from);
```

---

### C. Détection Conflits Automatique

**Types de conflits** :

1. **CONTRADICTS** : Même période, valeurs différentes
   ```cypher
   // Fact 1: SLA = 99.7% (valid_from: 2024-01-01)
   // Fact 2: SLA = 99.5% (valid_from: 2024-01-01)
   // → CONTRADICTION (laquelle est correcte ?)
   ```

2. **OVERRIDES** : Nouvelle version temporelle
   ```cypher
   // Fact 1: SLA = 99.7% (valid_from: 2024-01-01)
   // Fact 2: SLA = 99.5% (valid_from: 2024-06-01)
   // → OVERRIDE (valeur changée légitimement)
   ```

3. **DUPLICATES** : Même valeur, sources multiples
   ```cypher
   // Fact 1: SLA = 99.7% (source: doc_A.pptx)
   // Fact 2: SLA = 99.7% (source: doc_B.pptx)
   // → DUPLICATE (consolidation possible)
   ```

4. **OUTDATED** : Fact passé non invalidé
   ```cypher
   // Fact ancien: SLA = 99.5% (valid_until: null)
   // Fact nouveau: SLA = 99.7% (valid_from: 2024-06-01)
   // → Fact ancien devrait avoir valid_until = 2024-05-31
   ```

**Requête détection conflits** (avec tenant_id) :
```cypher
// Détecter CONTRADICTS et OVERRIDES
MATCH (f1:Fact {status: "approved", tenant_id: $tenant_id})
MATCH (f2:Fact {status: "proposed", tenant_id: $tenant_id})
WHERE f1.subject = f2.subject
  AND f1.predicate = f2.predicate
  AND f1.value <> f2.value

// Calculer type conflit
WITH f1, f2,
     CASE
       WHEN f2.valid_from > f1.valid_from THEN "OVERRIDES"
       WHEN f2.valid_from = f1.valid_from THEN "CONTRADICTS"
       ELSE "OUTDATED"
     END as conflict_type,
     abs(f1.value - f2.value) / f1.value as value_diff_pct

WHERE conflict_type IN ["CONTRADICTS", "OVERRIDES"]

RETURN f1, f2, conflict_type, value_diff_pct
ORDER BY value_diff_pct DESC
```

**Performance** : < 50ms (index sur subject+predicate)

---

### D. Workflow Gouvernance

```
┌──────────────────────────────────────────────────────────┐
│                  WORKFLOW FACTS                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  1. EXTRACTION (Pipeline Ingestion)                     │
│     • LLM Vision extrait fact depuis slide              │
│     • Format structuré: {subject, predicate, value}     │
│     • Insertion Neo4j avec status="proposed"            │
│     • Lien chunk Qdrant ↔ Fact Neo4j                    │
│                                                          │
│  2. DÉTECTION CONFLITS (Automatique)                    │
│     • Requête Cypher détection conflits                 │
│     • Calcul type conflit + severity                    │
│     • Notification expert si conflit critique           │
│                                                          │
│  3. REVIEW EXPERT (UI Admin)                            │
│     • Fact proposé affiché avec contexte               │
│     • Si conflit: affichage side-by-side                │
│     • Actions possibles:                                │
│       - APPROVE: status → "approved"                    │
│       - REJECT: status → "rejected"                     │
│       - OVERRIDE: invalider ancien + approuver nouveau  │
│       - MERGE: fusionner duplicates                     │
│                                                          │
│  4. MISE À JOUR TIMELINE (Post-Approval)                │
│     • Si OVERRIDE: mettre valid_until sur ancien fact   │
│     • Backfill Qdrant related_facts                     │
│     • Indexation pour search                            │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

### E. Timeline Temporelle (Bi-Temporelle)

**Deux axes temporels** :

1. **Valid Time** (`valid_from`, `valid_until`)
   - Quand le fact est vrai dans le monde réel
   - Géré manuellement (business logic)
   - Exemples :
     - SLA 99.7% valide du 2024-01-01 au 2024-05-31
     - SLA 99.5% valide depuis 2024-06-01

2. **Transaction Time** (`created_at`, `updated_at`)
   - Quand le fact est enregistré/modifié en base
   - Géré automatiquement par Neo4j
   - Audit trail complet

**Requête point-in-time** :
```cypher
// Quel était le SLA au 2024-03-15 ?
MATCH (f:Fact {
  subject: "SAP S/4HANA Cloud",
  predicate: "SLA_garantie",
  status: "approved"
})
WHERE f.valid_from <= datetime("2024-03-15")
  AND (f.valid_until IS NULL OR f.valid_until > datetime("2024-03-15"))
RETURN f.value, f.unit, f.valid_from
```

**Timeline complète** :
```cypher
// Historique complet SLA
MATCH (f:Fact {
  subject: "SAP S/4HANA Cloud",
  predicate: "SLA_garantie",
  status: "approved"
})
RETURN f.value, f.valid_from, f.valid_until, f.source_document
ORDER BY f.valid_from DESC
```

---

## 3) Schéma Qdrant Cible (Compatible Neo4j Facts)

```json
{
  "text": "SAP S/4HANA Cloud offre un SLA de 99.7% avec support 24/7...",
  "language": "fr",
  "ingested_at": "2025-10-03T10:00:00Z",
  "title": "SLA & Performance",

  "document": {
    "source_name": "SAP_S4HANA_SLA_2024.pptx",
    "source_type": "pptx",
    "source_date_iso": "2024-01-15",
    "links": {
      "source_file_url": "https://.../presentations/SAP_S4HANA_SLA_2024.pptx",
      "slide_image_url": "https://.../thumbnails/SAP_S4HANA_SLA_2024_slide_5.jpg"
    }
  },

  "chunk": {
    "slide_index": 5
  },

  "custom_metadata": {
    "solution": {
      "id": "S4_PRIVATE",
      "name": "SAP S/4HANA Cloud, Private Edition"
    }
  },

  "sys": {
    "tags_tech": ["pptx", "neo4j_facts_v1"],
    "prompt_meta": {
      "prompt_id": "fact_extraction_v2",
      "version": "2024-10-03"
    }
  },

  // Liaisons Neo4j (UUIDs)
  "related_node_ids": {
    "candidates": ["entity_uuid_1", "entity_uuid_2"],
    "approved": ["entity_uuid_1"]
  },

  "related_facts": {
    "proposed": ["fact_uuid_1", "fact_uuid_2", "fact_uuid_3"],
    "approved": ["fact_uuid_1"]  // Pointe vers Facts Neo4j approuvés
  }
}
```

**Note** : `related_facts` contient UUIDs de Facts Neo4j (pas duplicata données)

---

## 4) Architecture Infrastructure

### Séparation Infra / App

**Infrastructure (Stateful)** - `docker-compose.infra.yml` :
```yaml
services:
  qdrant:
    image: qdrant/qdrant:v1.7.4
    ports: ["6333:6333"]
    volumes: ["qdrant_data:/qdrant/storage"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: ["redis_data:/data"]

  neo4j:
    image: neo4j:5.26.0
    ports: ["7474:7474", "7687:7687"]
    volumes: ["neo4j_data:/data"]
    environment:
      NEO4J_AUTH: neo4j/neo4j_password

  postgres:  # Futur (metadata applicative)
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    volumes: ["postgres_data:/var/lib/postgresql/data"]
```

**Application (Stateless)** - `docker-compose.app.yml` :
```yaml
services:
  app:
    build: ./app
    ports: ["8000:8000"]
    depends_on: [qdrant, redis, neo4j]
    volumes: ["./src:/app/src"]  # Dev hot-reload

  worker:
    build: ./app
    command: rq worker
    depends_on: [redis, qdrant, neo4j]

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on: [app]
    volumes: ["./frontend/src:/app/src"]  # Dev hot-reload
```

**Commandes** :
```bash
# Démarrer infra (1 fois au boot)
docker-compose -f docker-compose.infra.yml up -d

# Démarrer app (dev)
docker-compose -f docker-compose.app.yml up -d

# Redémarrer app uniquement (sans toucher infra)
docker-compose -f docker-compose.app.yml restart app

# Logs app
docker-compose -f docker-compose.app.yml logs -f app

# Tout arrêter
docker-compose -f docker-compose.infra.yml down
docker-compose -f docker-compose.app.yml down
```

---

## 5) Architecture Code

### Structure Cible

```
src/knowbase/
├── neo4j_custom/              # Neo4j native layer
│   ├── __init__.py
│   ├── client.py              # Neo4jCustomClient (wrapper driver)
│   ├── schemas.py             # Schémas Cypher (Facts, Entities)
│   ├── queries.py             # Requêtes Cypher réutilisables
│   └── migrations.py          # Schema migrations
│
├── facts/                     # Facts governance layer
│   ├── __init__.py
│   ├── service.py             # FactsService (CRUD + gouvernance)
│   ├── conflict_detector.py   # ConflictDetector
│   ├── timeline.py            # TimelineService
│   ├── schemas.py             # Pydantic (FactCreate, FactResponse, ConflictDetail)
│   └── validators.py          # Validation business rules
│
├── api/routers/
│   ├── facts.py               # Endpoints /api/facts/*
│   │   # GET    /api/facts
│   │   # POST   /api/facts
│   │   # GET    /api/facts/{id}
│   │   # PUT    /api/facts/{id}/approve
│   │   # PUT    /api/facts/{id}/reject
│   │   # GET    /api/facts/conflicts
│   │   # GET    /api/facts/timeline/{subject}/{predicate}
│   │
│   └── search.py              # Search hybride Qdrant + Neo4j Facts
│
├── ingestion/pipelines/
│   └── pptx_pipeline_neo4j.py # Pipeline extraction Facts → Neo4j
│
└── common/                    # Utilitaires (inchangés)
    ├── logging.py
    ├── metrics.py
    ├── auth.py
    └── ...
```

---

## 6) Workflows Principaux

### Workflow 1 : Ingestion Document

```
1. Upload PPTX
   ↓
2. Extract slides (MegaParse + Python-PPTX)
   ↓
3. LLM Vision analysis (1 appel/slide)
   ├→ Chunks (Qdrant)
   ├→ Entities (Neo4j)
   ├→ Relations (Neo4j)
   └→ Facts structurés (Neo4j, status="proposed")
   ↓
4. Détection conflits automatique
   ↓
5. Notification expert si conflits critiques
```

### Workflow 2 : Recherche Utilisateur

```
User Query: "Quel est le SLA de SAP S/4HANA Cloud ?"
   ↓
1. Query Understanding (intent detection)
   ├→ Intent: FACTUAL_LOOKUP
   └→ Entities: "SAP S/4HANA Cloud", "SLA"
   ↓
2. Router intelligent
   ├→ Neo4j Facts (search direct sur facts approuvés)
   │  Query: MATCH (f:Fact {subject: "...", predicate: "SLA_garantie", status: "approved"})
   │  Result: 99.7% (50ms)
   │
   └→ Qdrant (contexte additionnel)
      Query: chunks liés à SLA S/4HANA
      Result: 3 chunks (80ms)
   ↓
3. Synthèse réponse
   ├→ Fact direct: "99.7%"
   ├→ Source: "SAP_S4HANA_SLA_2024.pptx, slide 5"
   ├→ Confidence: 0.95
   ├→ Valid depuis: 2024-01-01
   └→ Contexte: chunks Qdrant pour détails
   ↓
4. Réponse structurée utilisateur
```

### Workflow 3 : Gouvernance Facts

```
Expert Admin UI: /governance/facts
   ↓
1. Liste facts proposés (status="proposed")
   ├→ Tri par: conflit détecté, confidence, date
   └→ Filtres: fact_type, source_document
   ↓
2. Sélection fact à reviewer
   ↓
3. Affichage contexte complet
   ├→ Fact proposé (valeur, source, date)
   ├→ Chunk Qdrant original (texte + slide image)
   ├→ Facts existants similaires
   └→ Conflits détectés (si applicable)
   ↓
4. Actions expert
   ├→ APPROVE
   │  ├→ UPDATE status="approved"
   │  ├→ Backfill Qdrant related_facts
   │  └→ Invalider anciens facts si OVERRIDE
   │
   ├→ REJECT
   │  └→ UPDATE status="rejected"
   │
   └→ RESOLVE CONFLICT
       ├→ Choisir fact correct
       ├→ Rejeter fact incorrect
       └→ Optionnel: éditer valeur manuellement
```

---

## 7) Métriques de Succès

### Performance

| Métrique | Objectif | Mesure |
|----------|----------|--------|
| **Détection conflits** | < 50ms | ___ ms |
| **Query fact direct** | < 50ms | ___ ms |
| **Timeline query** | < 100ms | ___ ms |
| **Search hybride** | < 200ms | ___ ms |
| **Ingestion fact** | < 10ms/fact | ___ ms |

### Qualité Gouvernance

| Métrique | Objectif | Mesure |
|----------|----------|--------|
| **Précision détection conflits** | > 95% | ___% |
| **Faux positifs conflits** | < 5% | ___% |
| **Facts approuvés** | > 80% proposés | ___% |
| **Temps review moyen** | < 30s/fact | ___s |

### Robustesse

| Métrique | Objectif | Mesure |
|----------|----------|--------|
| **Uptime Neo4j** | > 99.9% | ___% |
| **Uptime Qdrant** | > 99.9% | ___% |
| **Tests coverage** | > 80% | ___% |
| **Erreurs ingestion** | < 0.1% | ___% |

---

## 8) Prochaines Évolutions (Roadmap)

### Phase Future 1 : Canonicalisation Entities (Post-Migration)
- Dédoublonnage entities Neo4j
- Suggestions merge probabilistes
- UI Admin canonicalisation

### Phase Future 2 : Enrichissement Facts
- Extraction relations causales entre facts
- Prédiction valeurs futures (ML)
- Alertes proactives changements

### Phase Future 3 : Multi-Source Consolidation
- Agrégation facts multiples sources
- Score confiance composite
- Résolution contradictions automatique

---

## 9) Décisions Architecturales Clés

### ADR-001 : Neo4j Native vs Graphiti
**Date** : 2025-10-03
**Statut** : ✅ Accepté
**Décision** : Migrer de Graphiti vers Neo4j Native + Custom Layer
**Raison** : Graphiti incompatible avec facts structurés (facts = texte dans relations). Neo4j custom permet détection conflits directe (50ms vs 500ms) et gouvernance précise.

### ADR-002 : Séparation Docker Infra/App
**Date** : 2025-10-03
**Statut** : ✅ Accepté
**Décision** : Séparer `docker-compose.infra.yml` et `docker-compose.app.yml`
**Raison** : Éviter redémarrages inutiles Qdrant/Redis lors dev app. Startup 3x plus rapide.

### ADR-003 : Facts First-Class Nodes
**Date** : 2025-10-03
**Statut** : ✅ Accepté
**Décision** : Facts = Nodes Neo4j (pas propriétés relations)
**Raison** : Requêtes directes possibles, index performants, schema flexible.

---

## 10) Risques Architecturaux & Mitigation

### Risque 1 : Scalabilité Neo4j Community Edition ⚠️

**Impact** : Élevé (bloquant si > 2M facts)
**Probabilité** : Moyenne (dépend adoption)

**Seuils critiques** :
- **< 500k facts** : OK (RAM 4GB, config par défaut)
- **500k - 2M facts** : Optimisation requise (RAM 16GB, tuning `neo4j.conf`)
- **> 2M facts** : Migration Neo4j Aura/Enterprise nécessaire (clustering, sharding)

**Limitations Community** :
- Pas de clustering
- Pas de sharding horizontal
- Performances I/O limitées sur gros datasets

**Mitigation** :
- **Phase 0-3** : Sizing recommandé documenté (RAM/CPU, config Neo4j)
- **Phase 5** : Tests charge 1M facts (mesure p95/p99 latence)
- **Phase 6** : POC Neo4j Aura si projections dépassent 2M
- **Monitoring** : Alertes si nombre facts > 80% seuil critique

---

### Risque 2 : Désynchronisation Qdrant ↔ Neo4j ⚠️

**Impact** : Moyen (incohérence données)
**Probabilité** : Moyenne

**Scénarios** :
1. UUID Neo4j supprimé mais toujours référencé dans `related_facts` Qdrant
2. Fact approuvé Neo4j mais `related_facts` Qdrant pas backfillé
3. Chunck Qdrant supprimé mais fact Neo4j garde `source_chunk_id` orphelin

**Mitigation** :
- **Job validation périodique** (toutes les 6h) :
  ```python
  # Pseudo-code
  qdrant_uuids = get_all_related_facts_uuids()
  neo4j_uuids = get_all_fact_uuids()
  orphans = qdrant_uuids - neo4j_uuids
  if orphans:
      clean_qdrant_orphans(orphans)
      alert_if_drift_threshold_exceeded()
  ```
- **Transaction compensatoire** :
  - Neo4j delete fact → trigger backfill Qdrant
  - Qdrant delete chunk → trigger cleanup Neo4j `source_chunk_id`
- **Monitoring** : Alert si drift > 1% (métrique Prometheus)
- **Event-driven (phase future)** : Event bus (Redis Streams) pour sync temps réel

---

### Risque 3 : Adoption UI Gouvernance 🚨 CRITIQUE

**Impact** : Critique (différenciateur produit)
**Probabilité** : Moyenne (dépend UX)

**Facteurs échec** :
- UX complexe → experts n'utilisent pas l'outil
- Pas de side-by-side conflicts → décisions difficiles
- Temps review > 2min/fact → abandon workflow

**Mitigation** :
- **Phase 2** : Maquette Figma validée avec experts métier réels
- **Phase 3** : POC UI minimaliste (liste facts, approve/reject simple)
- **Phase 4** : UI complète avec :
  - Side-by-side conflicts visuels
  - Filtres avancés (fact_type, source, date)
  - Bulk actions (approve/reject multiples facts)
  - Historique timeline interactive
- **Métriques adoption** :
  - % facts reviewed (objectif > 80%)
  - Temps moyen review (objectif < 30s/fact)
  - Taux abandon workflow (objectif < 5%)

---

### Risque 4 : Complexité Temporalité Bi-Temporelle ⚠️

**Impact** : Moyen (bugs logique métier)
**Probabilité** : Moyenne

**Scénarios problématiques** :
- Ingestion concurrente (2 docs contradictoires même jour)
- Périodes chevauchantes (`valid_from`/`until` incohérents)
- Update manuel sans invalidation ancien fact

**Mitigation** :
- **Validateurs stricts** (`validators.py`) :
  ```python
  def validate_temporal_coherence(fact, existing_facts):
      # Vérifier pas de chevauchement périodes
      # Vérifier valid_from < valid_until
      # Vérifier pas de gap temporel
  ```
- **Lock optimiste** : Utiliser `updated_at` Neo4j pour détecter race conditions
- **Tests unitaires intensifs** : Scénarios edge cases (100+ tests temporalité)
- **Documentation claire** : Règles métier temporalité (wiki interne)

---

### Risque 5 : Monitoring & Observabilité Insuffisante ⚠️

**Impact** : Moyen (difficile debug production)
**Probabilité** : Élevée (si pas anticipé)

**Sans monitoring** :
- Impossible valider SLA "< 50ms"
- Pas de détection anomalies (ex : pics latence Neo4j)
- Pas d'alerte si desync Qdrant/Neo4j

**Mitigation** :
- **Stack observabilité** :
  - **Prometheus** : Métriques (latence queries, nb facts, drift sync)
  - **Grafana** : Dashboards (SLA, throughput, errors)
  - **Jaeger** : Traces distribuées (debug latence E2E)
  - **ELK/Loki** : Logs centralisés
- **Métriques clés** :
  - `neo4j_query_duration_ms{query="detect_conflicts"}` → p95 < 50ms
  - `qdrant_neo4j_drift_pct` → < 1%
  - `facts_approval_rate` → > 80%
- **Alertes** :
  - Neo4j p95 > 100ms → PagerDuty
  - Drift sync > 5% → Slack
  - Facts pending > 1000 → Email admin

---

### Risque 6 : Sécurité Multi-Tenant ⚠️

**Impact** : Critique (fuite données inter-tenant)
**Probabilité** : Faible (si discipline code)

**Neo4j n'a pas de contrôle multi-tenant natif** → isolation app-side obligatoire.

**Mitigation** :
- **Règle stricte** : Toute requête Cypher DOIT filtrer `WHERE tenant_id = $tenant_id`
- **Middleware FastAPI** : Inject `tenant_id` automatiquement (pas confiance user input)
- **Tests E2E isolation** : Vérifier tenant A ne voit jamais données tenant B
- **Code review systématique** : Vérifier tenant_id dans toutes queries
- **Audit trail** : Logger tous accès avec tenant_id (détection anomalies)

---

### Risque 7 : Migrations Schéma Neo4j ⚠️

**Impact** : Moyen (downtime si mal géré)
**Probabilité** : Moyenne

**Neo4j n'a pas de framework migration natif** comme Alembic (SQL).

**Mitigation** :
- **Système versioning custom** :
  ```cypher
  // Node versioning schéma
  CREATE (:SchemaVersion {version: 2, applied_at: datetime()})
  ```
- **Scripts migration** :
  ```
  migrations/
  ├── v1_initial_schema.cypher
  ├── v2_add_tenant_id.cypher
  ├── v3_add_indexes.cypher
  ```
- **Outil** : Liquigraph (Neo4j migration tool) ou script Python custom
- **Tests rollback** : Prévoir downgrade scripts si migration échoue
- **Blue/Green deployment** : Minimiser downtime migrations production

---

### Risque 8 : ConflictDetector Simpliste ⚠️

**Impact** : Moyen (faux positifs/négatifs)
**Probabilité** : Élevée (cas edge nombreux)

**Requête Cypher actuelle** : Détecte seulement valeurs exactes différentes.

**Cas non gérés** :
- Unités différentes (`99.7%` vs `0.997`)
- Valeurs proches (`99.7%` vs `99.69%` → arrondi ?)
- Sources multiples même valeur (consolidation ?)
- Comparaison non numérique (texte, dates)

**Mitigation** :
- **Architecture hybride** :
  - **Fast path (Cypher)** : 80% cas simples (< 50ms)
  - **Slow path (Python)** : 20% cas complexes (< 500ms)
- **ConflictDetector extensible** :
  ```python
  class ConflictDetector:
      def detect(self, fact1, fact2):
          # Normalisation unités
          # Tolérance valeurs proches
          # Logique custom par fact_type
  ```
- **Configuration tolérances** : `config/conflict_rules.yaml`
- **Machine Learning (phase future)** : Prédire type conflit (CONTRADICTS vs OVERRIDES)

---

### Résumé Risques (Priorisation)

| Risque | Impact | Probabilité | Priorité Mitigation |
|--------|--------|-------------|---------------------|
| **UI Gouvernance** | 🔴 Critique | Moyenne | 🔴 P0 (Phase 2-4) |
| **Scalabilité Neo4j** | 🔴 Élevé | Moyenne | 🟠 P1 (Phase 5-6) |
| **Sync Qdrant↔Neo4j** | 🟠 Moyen | Moyenne | 🟠 P1 (Phase 3-4) |
| **Monitoring** | 🟠 Moyen | Élevée | 🟡 P2 (Phase 4-5) |
| **Sécurité Multi-tenant** | 🔴 Critique | Faible | 🟡 P2 (Phase 1-2) |
| **Temporalité** | 🟠 Moyen | Moyenne | 🟡 P2 (Phase 2-3) |
| **ConflictDetector** | 🟠 Moyen | Élevée | 🟢 P3 (Phase 3-4) |
| **Migrations Schéma** | 🟠 Moyen | Moyenne | 🟢 P3 (Phase 5-6) |

---

**Créé le** : 2025-10-03
**Dernière mise à jour** : 2025-10-03
**Version** : 2.0 (Neo4j Native)
**Auteur** : Équipe SAP KB
