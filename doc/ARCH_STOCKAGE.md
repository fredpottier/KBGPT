# Architecture Stockage OSMOSIS

> **Niveau de fiabilité** : Code-verified (Mars 2026). Schémas, collections et configuration vérifiés contre le code et les fichiers Docker Compose.

*Document consolidé — Mars 2026*

---

## 1. Vue d'ensemble

OSMOSIS repose sur quatre systèmes de stockage complémentaires avec des responsabilités distinctes :

| Système | Rôle | Principe |
|---------|------|----------|
| **Neo4j** | Knowledge Graph — vérité documentaire | Source de vérité unique pour faits, relations, ancres |
| **Qdrant** | Base vectorielle — projection retrieval | Index de récupération par similarité, jamais source de vérité |
| **PostgreSQL** | Métadonnées système | Registry entity types, sessions, audit trail |
| **Redis** | Queue & cache | Task queue RQ, état burst, cache temporaire |

**Principe directeur** :
> Neo4j = vérité documentaire contextualisée.
> Qdrant = index de récupération (retrieval projection), filtrable par structure, concept-aware.

Qdrant n'est jamais une source de vérité. C'est une projection optimisée pour le retrieval par similarité sémantique.

---

## 2. Neo4j — Knowledge Graph

### Connexion

Configuration dans `src/knowbase/common/clients/neo4j_client.py` :

```
URI:      bolt://graphiti-neo4j:7687  (via NEO4J_URI)
User:     neo4j                       (via NEO4J_USER)
Password: graphiti_neo4j_pass         (via NEO4J_PASSWORD)
Database: neo4j
```

Pooling : `max_connection_pool_size=50`, `max_connection_lifetime=3600s`, `connection_acquisition_timeout=120s`.

Container : `knowbase-neo4j` (Neo4j 5.26.0), ports 7474 (HTTP) + 7687 (Bolt).

Mémoire (docker-compose.infra.yml) :
- Heap : 2g initial, 4g max
- Page cache : 2g
- Transaction max : 2g

Plugins : APOC + Graph Data Science (Community).

### Types de noeuds principaux (ClaimFirst)

Le pipeline ClaimFirst persiste via `ClaimPersister` (`src/knowbase/claimfirst/persistence/claim_persister.py`) :

| Noeud | Description |
|-------|-------------|
| `Document` | Document source |
| `DocumentContext` | Contexte d'applicabilité (INV-8) |
| `SubjectAnchor` | Sujet canonique avec aliases typés (INV-9) |
| `ComparableSubject` | Sujet comparable entre documents |
| `ApplicabilityAxis` | Axe de comparaison (version, édition, etc.) |
| `Passage` | Unité de texte source |
| `Claim` | Assertion documentée |
| `Entity` | Ancre de navigation (produit, service, feature, concept, etc.) |
| `CanonicalEntity` | Entité canonicalisée (post-fusion LLM) |
| `Facet` | Axe de navigation thématique |
| `ClaimCluster` | Groupe de claims similaires |

### Types de noeuds (Pipeline stratifié legacy)

| Noeud | Description |
|-------|-------------|
| `ProtoConcept` | Concept extrait brut (Proto-KG) |
| `CanonicalConcept` | Concept promu et consolidé (Published-KG) |
| `SectionContext` | Contexte de section du document |
| `MarkerMention` | Mention brute de marqueur de version |
| `CanonicalMarker` | Marqueur normalisé |
| `MentionSpan` | Span de coréférence |
| `CorefChain` | Chaîne de coréférence |

### Relations principales

| Relation | De -> Vers |
|----------|------------|
| `HAS_CONTEXT` | Document -> DocumentContext |
| `ABOUT_SUBJECT` | DocumentContext -> SubjectAnchor |
| `HAS_AXIS_VALUE` | DocumentContext -> ApplicabilityAxis |
| `FROM` | Passage -> Document |
| `SUPPORTED_BY` | Claim -> Passage |
| `IN_DOCUMENT` | Claim -> Document |
| `ABOUT` | Claim -> Entity |
| `BELONGS_TO_FACET` | Claim -> Facet |
| `IN_CLUSTER` | Claim -> ClaimCluster |
| `CONTRADICTS` | Claim -> Claim |
| `REFINES` | Claim -> Claim |
| `QUALIFIES` | Claim -> Claim |
| `INSTANCE_OF` | ProtoConcept -> CanonicalConcept |
| `CANONICALIZES_TO` | MarkerMention -> CanonicalMarker |

### Contraintes et index (depuis le code)

Contraintes d'unicité déclarées dans le code :

```cypher
-- Faits (neo4j_custom/schemas.py)
CREATE CONSTRAINT fact_uuid_unique FOR (f:Fact) REQUIRE f.uuid IS UNIQUE

-- Coréférence (linguistic/coref_persist.py)
CREATE CONSTRAINT mentionspan_unique FOR (m:MentionSpan) REQUIRE m.mention_id IS UNIQUE
CREATE CONSTRAINT corefchain_unique FOR (c:CorefChain) REQUIRE c.chain_id IS UNIQUE
CREATE CONSTRAINT corefdecision_unique FOR (d:CorefDecision) REQUIRE d.decision_id IS UNIQUE

-- Normalisation (consolidation/normalization/normalization_store.py)
CREATE CONSTRAINT cm_unique FOR (cm:CanonicalMarker) REQUIRE cm.id IS UNIQUE

-- Ontologie (ontology/neo4j_schema.py)
CREATE CONSTRAINT ont_entity_id_unique FOR (e:OntEntity) REQUIRE e.entity_id IS UNIQUE
CREATE CONSTRAINT ont_alias_id_unique FOR (a:OntAlias) REQUIRE a.alias_id IS UNIQUE
CREATE CONSTRAINT ont_alias_normalized_unique FOR (a:OntAlias) REQUIRE a.normalized IS UNIQUE

-- Documents (ontology/document_schema.py)
CREATE CONSTRAINT doc_id_unique FOR (d:Document) REQUIRE d.doc_id IS UNIQUE
CREATE CONSTRAINT doc_version_id_unique FOR (v:DocVersion) REQUIRE v.version_id IS UNIQUE
CREATE CONSTRAINT doc_version_checksum_unique FOR (v:DocVersion) REQUIRE v.checksum IS UNIQUE
CREATE CONSTRAINT doc_source_path_unique FOR (d:Document) REQUIRE d.source_path IS UNIQUE
```

Index de performance principaux :

```cypher
-- Faits
CREATE INDEX fact_tenant_idx FOR (f:Fact) ON (f.tenant_id)
CREATE INDEX fact_tenant_subject_predicate_idx FOR (f:Fact) ON (f.tenant_id, f.subject, f.predicate)
CREATE INDEX fact_source_document_idx FOR (f:Fact) ON (f.source_document)

-- Assertions (consolidation/assertion_store.py)
CREATE INDEX document_id FOR (a:Assertion) ON (a.document_id)
CREATE INDEX proto_tenant FOR (p:ProtoConcept) ON (p.tenant_id, p.lex_key)

-- Marqueurs
CREATE INDEX marker_value FOR (m:Marker) ON (m.value)
CREATE INDEX marker_kind FOR (m:Marker) ON (m.kind)

-- Normalisation
CREATE INDEX mm_raw_text FOR (mm:MarkerMention) ON (mm.raw_text)
CREATE INDEX cm_canonical_form FOR (cm:CanonicalMarker) ON (cm.canonical_form)

-- Ontologie
CREATE INDEX ont_alias_normalized_idx FOR (a:OntAlias) ON (a.normalized)
CREATE INDEX ont_entity_type_idx FOR (e:OntEntity) ON (e.entity_type)
```

### Dual-Graph : Proto-KG vs Published-KG

Architecture héritée du pipeline stratifié (toujours active) :

- **Proto-KG** : concepts extraits non-validés (`ProtoConcept`, `SectionContext`), peuplé en Pass 1
- **Published-KG** : concepts promus et enrichis (`CanonicalConcept`), peuplé en Pass 2.0+
- Promotion unidirectionnelle via `INSTANCE_OF` avec audit trail

---

## 3. Qdrant — Base vectorielle

### Connexion

Configuration dans `src/knowbase/common/clients/qdrant_client.py` :

```
URL:     http://qdrant:6333   (via QDRANT_URL)
API Key: optionnel             (via QDRANT_API_KEY)
Timeout: 300s (pour gros batch uploads)
```

Container : `knowbase-qdrant` (Qdrant v1.15.1), port 6333 (HTTP) + 6334 (gRPC).

Singleton client via `@lru_cache(maxsize=1)`.

### Collections

| Collection | Usage | Dimension | Distance | Source |
|------------|-------|-----------|----------|--------|
| `knowbase_chunks_v2` | **Layer R** — retrieval principal | 1024 | Cosine | TypeAwareChunks du cache Pass 0 |
| `knowbase` | Legacy — chunks ancienne pipeline | 768 | Cosine | Burst artifact importer |
| `rfp_qa` | Q/A RFP dédiées | configurable | Cosine | Import Excel Q/A |

### Layer R — Retrieval (`src/knowbase/retrieval/qdrant_layer_r.py`)

Collection `knowbase_chunks_v2`, vecteurs 1024D (multilingual-e5-large via TEI sur EC2).

**ID des points** : `hash_stable(tenant_id + doc_id + chunk_id + sub_index)` — déterministe et idempotent.

**Payload par point** :

```json
{
  "tenant_id": "default",
  "doc_id": "014_SAP_S4HANA_...",
  "section_id": "default:014_...:sec_3.2",
  "chunk_id": "chunk_abc123",
  "sub_index": 0,
  "parent_chunk_id": "chunk_abc123",
  "kind": "NARRATIVE_TEXT",
  "page_no": 42,
  "page_span_min": 42,
  "page_span_max": 43,
  "item_ids": ["item_1", "item_2"],
  "text_origin": "docling",
  "text": "Le texte original du sous-chunk"
}
```

**Usages servis** :
- Mode TEXT_ONLY : RAG classique quand le graphe ne permet pas de répondre
- Mode ANCHORED : retrieval filtré par `doc_id` / `section_id`
- Writing Companion : recherche par similarité avec le texte utilisateur
- Fallback zones non couvertes par le KG

### Layer P — Precision (non implémenté)

Architecture définie pour recherche précise sur des unités sémantiques validées et concept-aware. Non encore implémenté.

### Modèle d'embedding

- **Modèle** : `intfloat/multilingual-e5-large` (configuré dans `settings.py` via `EMB_MODEL_NAME`)
- **Dimension** : 1024D pour Layer R, 768D pour les collections legacy
- **Infrastructure** : TEI (Text Embeddings Inference v1.5) sur EC2 Spot g6.2xlarge, port 8001
- **Distance** : Cosine

---

## 4. PostgreSQL — Métadonnées

### Connexion

Container : `knowbase-postgres` (pgvector/pgvector:pg16), port 5432.

```
Database: knowbase
User:     knowbase
Password: via POSTGRES_PASSWORD (défaut: knowbase_secure_pass)
```

### Modèles SQLAlchemy (`src/knowbase/db/models.py`)

**EntityTypeRegistry** :

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer PK | Auto-increment |
| `type_name` | String(50) | Nom du type (UPPERCASE) |
| `status` | String(20) | pending / approved / rejected |
| `first_seen` | DateTime | Date première découverte |
| `discovered_by` | String(20) | llm / admin / system |
| `entity_count` | Integer | Nombre d'entités de ce type dans Neo4j |
| `pending_entity_count` | Integer | Entités en attente |

Workflow : LLM découvre nouveau type -> status=pending -> Admin review -> approved/rejected.

### Rôle

PostgreSQL stocke les métadonnées système qui ne relèvent ni du graphe de connaissance (Neo4j) ni de la recherche vectorielle (Qdrant) : registry des types d'entités, sessions, audit trail, historique d'imports.

---

## 5. Redis — Queue & Cache

### Connexion

Container : `knowbase-redis` (Redis 7.2-alpine), port 6379.

```
URL: redis://redis:6379/0   (via REDIS_URL)
```

Configuration : `appendonly yes`, `maxmemory 512mb`, `maxmemory-policy allkeys-lru`.

### Task Queue (RQ)

Redis sert de broker pour Python RQ (Redis Queue) :

- Le service `ingestion-worker` (`knowbase-worker`) consomme les jobs de la queue
- Entrypoint : `python -m knowbase.ingestion.queue`
- Configuration timeout : `MAX_DOCUMENT_PROCESSING_TIME` (défaut 3600s = 1h)
- `INGESTION_JOB_TIMEOUT` = `MAX_DOCUMENT_PROCESSING_TIME * 1.5` (buffer RQ)

### État Burst

Le mode burst (import en masse) stocke son état dans Redis :

- Clé : `osmose:burst:state`
- TTL : 86400 secondes (SETEX obligatoire)
- Concurrence : `BURST_MAX_CONCURRENT_DOCS=2` (configurable)

### Attention

- Les jobs en mémoire du Wiki store sont **in-memory** — tout restart app détruit les batch jobs en cours
- **Ne jamais purger** la queue Redis sans vérifier les workers actifs

---

## 6. Cache d'extraction

### Format `.knowcache.json`

Le cache d'extraction sauvegarde le texte extrait pour réutilisation instantanée, évitant de re-parser les documents (économie -90% temps, -80% coût).

**Chemin** : `data/extraction_cache/`

**Versions** :
- v1.0 : format legacy (pages + full_text)
- v4/v5 : format actuel avec DocItems, TypeAwareChunks, VisionObservations, sections, etc.

Le `CacheLoadResult` (`src/knowbase/stratified/pass0/cache_loader.py`) charge le cache et produit :

| Champ | Description |
|-------|-------------|
| `pass0_result` | Résultat Pass0 complet (DocItems, chunks, sections) |
| `full_text` | Contenu textuel complet (avec enrichissement vision) |
| `doc_title` | Titre du document |
| `vision_observations` | Observations vision séparées du KG (ADR-20260126) |
| `retrieval_embeddings` | Métadonnées sub-chunks pour Layer R |
| `file_type` | "pdf", "pptx", "docx" |

### REGLE VITALE

**NE JAMAIS SUPPRIMER `data/extraction_cache/`**. Ces fichiers sont précieux :
- Ils évitent de re-extraire les documents (économise temps/coûts)
- Ils permettent de rejouer les imports après une purge système

---

## 7. Modèle de déploiement

### Principe : 1 instance = 1 client

OSMOSIS utilise une architecture d'**instances dédiées par client** plutôt qu'un multi-tenancy logique :

- Isolation physique des données (bases séparées)
- Audit conformité simple et évident
- Personnalisation via fichiers de configuration

### Architecture multi-compose

Trois fichiers Docker Compose séparant les responsabilités :

**`docker-compose.infra.yml`** — Infrastructure stateful (rarement redémarrée) :

| Service | Container | Image | Ports |
|---------|-----------|-------|-------|
| `qdrant` | knowbase-qdrant | qdrant/qdrant:v1.15.1 | 6333, 6334 |
| `redis` | knowbase-redis | redis:7.2-alpine | 6379 |
| `neo4j` | knowbase-neo4j | neo4j:5.26.0 | 7474, 7687 |
| `postgres` | knowbase-postgres | pgvector/pgvector:pg16 | 5432 |

**`docker-compose.yml`** — Application stateless :

| Service | Container | Description |
|---------|-----------|-------------|
| `app` | knowbase-app | FastAPI backend (port 8000) |
| `ingestion-worker` | knowbase-worker | Worker RQ avec GPU (NVIDIA) |
| `folder-watcher` | knowbase-watcher | Surveillance dossier docs_in |
| `frontend` | knowbase-frontend | Next.js (port 3000) |

**`docker-compose.monitoring.yml`** — Monitoring :

- Grafana (port 3001)
- Loki (port 3101)
- Promtail

### Réseau

Tous les services partagent le réseau bridge `knowbase_network` (name: `knowbase_net`).

### Volumes nommés

```
knowbase_qdrant_data    — Données Qdrant
knowbase_redis_data     — Données Redis
knowbase_neo4j_data     — Données Neo4j
knowbase_neo4j_logs     — Logs Neo4j
knowbase_neo4j_plugins  — Plugins Neo4j (APOC, GDS)
knowbase_postgres_data  — Données PostgreSQL
knowbase_frontend_node_modules
knowbase_frontend_next_build
```

### Worker GPU

Le `ingestion-worker` a accès à 1 GPU NVIDIA :

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

`shm_size: 2gb` nécessaire pour OnnxTR/PyTorch.

---

## 8. Configuration

### Feature Flags (`config/feature_flags.yaml`)

Fichier unique pour les flags fonctionnels. Sections principales :

| Section | Flags clés |
|---------|-----------|
| `stratified_pipeline_v2` | `enabled`, `max_concepts_per_document`, `enable_pointer_mode`, `llm_calibration` |
| `hybrid_intelligence` | `enable_hybrid_extraction`, `enable_document_context` |

Lecture via : `from knowbase.config.feature_flags import is_feature_enabled`

### Settings centralisés (`src/knowbase/config/settings.py`)

Classe `Settings` (Pydantic BaseSettings) avec variables d'environnement :

| Variable | Défaut | Description |
|----------|--------|-------------|
| `NEO4J_URI` | `bolt://graphiti-neo4j:7687` | URI Neo4j |
| `NEO4J_USER` | `neo4j` | Utilisateur Neo4j |
| `NEO4J_PASSWORD` | `graphiti_neo4j_pass` | Mot de passe Neo4j |
| `QDRANT_URL` | `http://qdrant:6333` | URL Qdrant |
| `QDRANT_COLLECTION` | `knowbase_chunks_v2` | Collection principale |
| `QDRANT_QA_COLLECTION` | `rfp_qa` | Collection Q/A RFP |
| `EMB_MODEL_NAME` | `intfloat/multilingual-e5-large` | Modèle embedding |
| `REDIS_HOST` | `redis` | Host Redis |
| `REDIS_PORT` | `6379` | Port Redis |
| `MAX_DOCUMENT_PROCESSING_TIME` | `3600` | Timeout traitement document (secondes) |
| `MODEL_VISION` | `gpt-4o` | Modèle vision |
| `MODEL_LONG_TEXT` | `claude-sonnet-4-20250514` | Modèle texte long |
| `MODEL_ENRICHMENT` | `claude-3-haiku-20240307` | Modèle enrichissement |
| `GPU_UNLOAD_TIMEOUT_MINUTES` | `10` | Timeout déchargement modèle embedding GPU |

### Configuration LLM (`config/llm_models.yaml`)

Configuration multi-provider des modèles LLM.

### Prompts (`config/prompts.yaml`)

Prompts personnalisables par famille, séparés du code.

---

## 9. Références archive

Les documents sources de cette consolidation sont archivés dans `doc/archive/pre-rationalization-2026-03/` :

| Document archivé | Section couverte |
|-------------------|-----------------|
| `architecture/OSMOSE_ARCHITECTURE_TECHNIQUE.md` | Sections 1, 2 (vue d'ensemble, dual-graph) |
| `architecture/ARCHITECTURE_DEPLOIEMENT.md` | Section 7 (modèle de déploiement) |
| `architecture/OSMOSIS_ARCHITECTURE_CIBLE_V2.md` | Section 1 (principes pipeline extraction) |
| `adr/ADR_STRUCTURAL_GRAPH_FROM_DOCLING.md` | Section 2 (schema Neo4j) |
| `specs/extraction/SPEC-EXTRACTION_CACHE_USAGE.md` | Section 6 (cache d'extraction) |
| `ongoing/ADR_QDRANT_RETRIEVAL_PROJECTION_V2.md` | Section 3 (Qdrant dual-layer) |
