# Addendum — POC Graphiti, Interfaces et Endpoints Minimaux

Ce document complète `doc/GRAPHITI_INTEGRATION_PLAN.md` avec un POC cadré (Phase 0‑bis), des critères GO/NO‑GO, des interfaces d’abstraction (`GraphStore`, `FactsRepository`, `MemoryRepository`) et la liste d’endpoints minimaux à exposer pour démarrer rapidement l’implémentation.

## 1) Phase 0‑bis — POC Graphiti (Validation avant engagement)

Objectifs
- Valider multi‑tenant (`group_id`), CRUD relations, sous‑graphe (k‑hop), facts MVP (`proposed`→`approved`), mémoire sessions.
- Mesurer une baseline de performance et de ressources.

Périmètre POC
- Groupes: `enterprise` + 1 groupe utilisateur de test (mappé depuis `X-User-ID`).
- KG: create/list/delete relations, `GET subgraph(entity_id, depth=2..3)`.
- Facts MVP: création (proposed), approbation (approved), requêtes simples (`category`, `status`, `at`).
- Mémoire: sessions, turns, contexte récent.

Livrables
- `src/knowbase/graph_store/interfaces.py` (interfaces) + `GraphitiStore` (POC) + `InMemoryStore` (tests).
- Endpoints POC minimaux (section 3 ci‑dessous).
- `docker-compose.poc.yml` (Graphiti + Postgres si requis) + healthchecks.
- Script bench `scripts/bench_graph_store.py`.

Métriques baseline
- KG: `subgraph(depth=3) < 2s` (p95), création relation < 300 ms (médiane).
- Facts: POST/GET < 300 ms (médiane).
- Mémoire: contexte récent < 300 ms (médiane).
- Ressources: CPU/RAM stables sous 10–20 RPS.

GO/NO‑GO
- GO si multi‑tenant OK, perfs conformes, intégration Python claire.
- NO‑GO si instabilité API/doc, latences imprévisibles ou manques bloquants.

Checklist POC
- [ ] Interfaces créées (GraphStore/FactsRepository/MemoryRepository)
- [ ] Impl `GraphitiStore` + `InMemoryStore`
- [ ] Endpoints POC exposés
- [ ] Compose POC + healthchecks
- [ ] Bench exécuté + métriques consignées
- [ ] Décision GO/NO‑GO documentée

## 2) Interfaces d’Abstraction (Esquisse Python)

```python
# src/knowbase/graph_store/interfaces.py
from typing import Protocol, List, Optional, Dict, Any

class RelationCreate(Dict[str, Any]):
    ...

class RelationFilters(Dict[str, Any]):
    ...

class SubgraphResponse(Dict[str, Any]):
    ...

class FactCreate(Dict[str, Any]):
    ...

class FactQuery(Dict[str, Any]):
    ...

class SessionCreate(Dict[str, Any]):
    ...

class GraphStore(Protocol):
    def health(self) -> bool: ...
    def set_group(self, group_id: str) -> None: ...
    def upsert_entity(self, entity: Dict[str, Any]) -> str: ...
    def create_relation(self, relation: RelationCreate) -> str: ...
    def delete_relation(self, relation_id: str) -> bool: ...
    def list_relations(self, filters: Optional[RelationFilters] = None) -> List[Dict[str, Any]]: ...
    def get_subgraph(self, entity_id: str, depth: int = 2) -> SubgraphResponse: ...

class FactsRepository(Protocol):
    def set_group(self, group_id: str) -> None: ...
    def create_fact(self, fact: FactCreate) -> str: ...
    def list_facts(self, query: Optional[FactQuery] = None) -> List[Dict[str, Any]]: ...
    def approve_fact(self, fact_id: str, approver_id: str) -> bool: ...
    def detect_conflicts(self, fact: Dict[str, Any]) -> List[Dict[str, Any]]: ...

class MemoryRepository(Protocol):
    def set_group(self, group_id: str) -> None: ...
    def create_session(self, payload: SessionCreate) -> str: ...
    def append_turn(self, session_id: str, role: str, text: str, meta: Optional[Dict[str, Any]] = None) -> str: ...
    def get_recent_context(self, session_id: str, k: int = 5) -> List[Dict[str, Any]]: ...
```

Switch par configuration (env)

```
# .env
GRAPH_BACKEND=graphiti   # graphiti | neo4j | in_memory
FACTS_BACKEND=graphiti   # graphiti | postgres | in_memory
```

## 3) Endpoints POC Minimaux (FastAPI)

- KG
  - `POST /api/knowledge-graph/relations` — créer relation
  - `GET  /api/knowledge-graph/relations` — lister (filtres type/entity/propriétés)
  - `GET  /api/knowledge-graph/subgraph?entity_id=&depth=` — sous‑graphe k‑hop

- Facts (MVP)
  - `POST /api/facts` — créer en `status=proposed`
  - `POST /api/facts/{id}/approve` — transition en `approved`
  - `GET  /api/facts?category=&status=&at=` — requêtes simples (temps optionnel)

- Mémoire
  - `POST /api/memory/sessions` — créer une session
  - `POST /api/memory/sessions/{id}/turns` — ajouter un tour
  - `GET  /api/memory/sessions/{id}/context?k=` — contexte récent

Notes
- Propagation `X-User-ID` → `group_id` côté stores.
- Schémas Pydantic minimaux pour POC; affinements ultérieurs.

## 4) Compose POC (esquisse)

```
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: graphiti
      POSTGRES_USER: graphiti
      POSTGRES_PASSWORD: ${GRAPHITI_DB_PASSWORD}
    ports:
      - "5434:5432"
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "graphiti"]
      interval: 5s
      timeout: 3s
      retries: 20

  graphiti:
    image: ghcr.io/<org>/graphiti:latest
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      GRAPHITI_DB_DSN: postgresql://graphiti:${GRAPHITI_DB_PASSWORD}@postgres:5432/graphiti
    ports:
      - "8300:8300"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8300/healthz"]
      interval: 10s
      timeout: 3s
      retries: 20
```

## 5) Bench Minimal (cible métriques)

- 100× `POST /relations`, 10× `GET /subgraph?depth=3`, 100× `POST /facts`, 100× `GET /facts?...`.
- Attendus: `subgraph(depth=3) < 2s`; CRUD < 300 ms (médiane); mémoire < 300 ms (médiane).

