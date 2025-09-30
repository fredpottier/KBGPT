# Plan de Pivot et d'Integration Graphiti

Note POC: voir aussi `doc/GRAPHITI_POC_ADDENDUM.md` pour la Phase 0-bis (POC), les interfaces d'abstraction (`GraphStore`, `FactsRepository`, `MemoryRepository`) et la liste des endpoints minimaux a implementer.

Ce document formalise le changement de cap: abandon de Zep Community Edition (CE, depreciee) et adoption de Graphiti pour atteindre les objectifs fonctionnels initiaux du projet SAP Knowledge Base (KG relationnel, base de faits gouvernee/bi-temporelle, memoire conversationnelle), en coherence avec l'architecture existante (Qdrant, FastAPI, Redis/RQ) et la couche multi-utilisateur deja en place.

## 1. Contexte et Decision

- Zep CE est depreciee; l'API Facts n'a jamais existe et n'existera pas. Risques de securite/maintenance a terme.
- L'ambition initiale: un systeme intelligent et evolutif combinant KG, facts versionnes/gouvernes, et memoire de chat.
- Decision: remplacer Zep par Graphiti (framework open-source oriente graphe/memoire) et completer avec nos briques existantes.

## 2. Objectifs Fonctionnels Cibles (rappel)

- Knowledge Graph relationnel (multi-hop, sous-graphes, expansion de requete).
- Base de "facts" versionnee et gouvernee (proposition auto, validation humaine, conflits/versions, requetes temporelles/metadata).
- Memoire/sessions conversationnelles multi-utilisateurs.
- Deux KGs distincts: KG d'entreprise immuable (source de verite) et KG par utilisateur (persiste), avec arbitrage "l'entreprise prime en cas de conflit".
- Integration Python/FastAPI; ingestion vers Qdrant; Redis/RQ pour jobs.

## 3. Architecture Cible (vue d'ensemble)

- Qdrant: stockage des chunks/embeddings (inchange).
- Graphiti: couche graphe/temporalite/memoire.
  - Multi-tenant par `group_id`: un groupe "enterprise" (immutable) et un groupe par utilisateur.
  - Relations, entites, evenements temporels; support des sessions/memoire.
- Postgres (optionnel selon deploiement Graphiti): persistance sous-jacente; JSON/JSONB pour metadonnees.
- Redis/RQ: queues et cache court terme.
- FastAPI: APIs `/api/knowledge-graph/*`, `/api/facts/*`, `/api/memory/*` (adaptees pour Graphiti).
- Frontend: UI admin gouvernance et gestion utilisateurs (reutilisable).

Politique de resolution: lors d'une requete, agreger KG "enterprise" + KG "user", en cas de contradiction un fait/relation du KG enterprise l'emporte.

## 4. Perimetre Multi-Utilisateur (reutilisable)

Reutilisables (existant dans la branche Zep):
- Backend
  - Service gestion des utilisateurs (fichier `users.json` auto-cree, CRUD, activite, utilisateur par defaut).
  - Router FastAPI `/api/users` complet (+ endpoints specifiques `/activity`, `/set-default`).
  - Schemas Pydantic (UserRole, User, UserCreate/Update).
  - Tests d'integration CRUD utilisateurs.
- Frontend
  - `UserProvider` React (persistance locale `sap-kb-current-user`).
  - UI de selection utilisateur (barre superieure, modale, actions default/delete).
  - Client Axios attachant `X-User-ID` automatiquement.

Adaptations necessaires pour Graphiti:
- Propager reellement `X-User-ID` cote backend vers le client Graphiti (selection du bon `group_id`).
- Etendre le modele utilisateur (+ `graphiti_group_id`, autres metadonnees Graphiti) dans schemas et `users.json`.
- Adapter services/jobs d'ingestion pour transmettre le contexte utilisateur vers Graphiti.

## 5. Interfaces & Points d'Insertion

- Remplacer `src/knowbase/common/zep_client_real.py` par un adaptateur Graphiti: `src/knowbase/common/graphiti_client.py`.
- Services au-dessus stables: `knowledge_graph_service.py`, `facts_service.py`, `facts_governance_service.py` restent inchanges si l'adaptateur expose des methodes equivalentes.
- Endpoints FastAPI existants continuent d'orchestrer ingestion/extraction/gouvernance.

## 6. Plan de Mise en Place (phases tracables)

### Phase 0-bis (POC Graphiti) - **EN COURS** 🔧

**STATUT ACTUEL**: Phase 0-bis en cours d'exécution - voir `doc/GRAPHITI_POC_TRACKING.md` pour le suivi détaillé.

Cette phase POC détaillée valide la faisabilité technique avant le déploiement complet:
- Infrastructures Docker Graphiti ✅ VALIDÉ
- SDK graphiti-core et interfaces d'abstraction ⚠️ BLOQUÉ (problème installation container)
- Endpoints wrapper `/api/graphiti/*` 🔧 CRÉÉS mais désactivés
- Multi-tenant et health checks ✅ VALIDÉ

**📋 SUIVI**: Consulter `doc/GRAPHITI_POC_TRACKING.md` pour l'état exact des 5 critères de la Phase 0.

### Phase 0 - Preparation & Validation de base (APRÈS POC)
- Choix deploiement Graphiti (librairie + Postgres ou service Docker dedie).
- Variables d'environnement et secrets (`GRAPHITI_URL`, `GRAPHITI_API_KEY`, timeouts, retries).
- Ajout des champs `graphiti_group_id` dans schemas utilisateurs + migration des donnees `users.json`.
- Sante: ping Graphiti + verification creation/lecture d'un groupe `enterprise` et d'un groupe de test utilisateur.

Livrables
- `src/knowbase/common/graphiti_client.py` (squelette + health).
- Mise a jour `users.json` et modeles Pydantic.
- Documentation d'installation/config.

### Phase 1 - KG Entreprise (immutable)
- Creation du groupe `enterprise`. Schema de noeuds/relations (Entity, Document, Attribute, etc.).
- Endpoints CRUD relations: create/list/delete, sous-graphes, expansion basique.
- Import initial des relations existantes (si export Zep dispo) vers Graphiti.

Livrables
- `knowledge_graph_service.py` branche sur Graphiti.
- Endpoints `/api/knowledge-graph/*` operationnels.
- Script `scripts/migrate_relations_to_graphiti.py` (idempotent).

### Phase 2 - KG Utilisateur (multi-tenant)
- Mapping `X-User-ID` vers `graphiti_group_id`.
- Creation automatique du groupe utilisateur a la premiere action.
- CRUD relations/faits utilisateur isoles par groupe.

Livrables
- Propagation de contexte dans services/jobs.
- Tests d'integration multi-utilisateur (entreprise vs utilisateur).

### Phase 3 - Facts & Gouvernance
- Modelisation facts (proposed/approved/rejected), conflict detection, journal d'audit.
- Extraction adaptative: stockage en `status=proposed` + ecran de validation.
- Regles: "no overlap" en approved; overlap tolere en proposed -> conflit a resoudre.

Livrables
- `/api/facts/*` (create/list/approve/reject/query by time/metadata).
- UI admin gouvernance mise a jour (categories officielles, promotion, metriques).

### Phase 4 - Memoire Conversationnelle
- Sessions/turns stockes via Graphiti (ou Postgres si plus adapte au deploiement choisi).
- Recuperation contexte multi-tours; liens avec entites/documents.

Livrables
- `/api/memory/*` (create session, append turn, get recent, summarize optionnel).
- Integration dans le chat existant.

### Phase 5 - Observabilite, Securite, Tests
- Metriques Prometheus: extraction, gouvernance, latences KG/memory.
- Logs structures JSON.
- Tests d'integration E2E (KG/Facts/Memory) multi-utilisateur.
- Revue securite (authN/Z, limites rate, validation inputs).

## 7. Backlog & Checklists

Checklist Phase 0 - Preparation
- [ ] Decision mode deploiement Graphiti (service vs lib)
- [ ] Variables d'environnement documentees
- [ ] `graphiti_group_id` ajoute (schemas + `users.json`)
- [ ] Client `graphiti_client.py` (health, auth, retries)

Checklist Phase 1 - KG Entreprise
- [ ] Groupe `enterprise` cree
- [ ] CRUD relations + sous-graphes
- [ ] Script migration relations existantes
- [ ] Tests integration KG (base)

Checklist Phase 2 - KG Utilisateur
- [ ] Mapping `X-User-ID` vers `group_id`
- [ ] Creation auto groupe utilisateur
- [ ] Isolation stricte des donnees
- [ ] Tests multi-utilisateur

Checklist Phase 3 - Facts & Gouvernance
- [ ] Modele facts + conflits + audit
- [ ] Endpoints `/api/facts/*`
- [ ] UI validation/promotion
- [ ] Metriques gouvernance (coverage, promotion velocity)

Checklist Phase 4 - Memoire
- [ ] Endpoints `/api/memory/*`
- [ ] Integration chat
- [ ] Tests de performance (dizaines d'utilisateurs)

Checklist Phase 5 - Obs/Tests
- [ ] Metriques + logs structures
- [ ] Tests E2E (KG/Facts/Memory)
- [ ] Revue securite

## 8. Decisions & Contraintes

- Deux niveaux de KG: `enterprise` (immutable) et `user` (par groupe), priorisation entreprise en cas de conflit.
- Conservation de Qdrant pour retrieval; Graphiti pour graphe/memoire/temporalite.
- Python/FastAPI maintenus; Docker Compose pour l'orchestration.
- Eviter le lock-in cloud: solution on-premise uniquement.

## 9. Journal des Actions

Format: `AAAA-MM-JJ HH:MM - Description - Fichiers impactes`

- 2025-09-29 00:00 - Creation plan de pivot Graphiti - `doc/GRAPHITI_INTEGRATION_PLAN.md`
- (a completer au fil de l'eau)

## 10. Mapping Technique (Zep vers Graphiti)

- Client d'acces
  - Zep: `src/knowbase/common/zep_client_real.py`
  - Graphiti: `src/knowbase/common/graphiti_client.py` (a creer)
- Services
  - `knowledge_graph_service.py` -> branchement Graphiti
  - `facts_service.py`, `facts_governance_service.py` -> stockage/logic via Graphiti (ou Postgres si choisi pour facts)
- Multi-utilisateur
  - `X-User-ID` -> `graphiti_group_id`
  - `users.json` enrichi

## 11. Variables & Configuration (brouillon)

```
# .env (exemple)
GRAPHITI_URL=http://localhost:8300
GRAPHITI_API_KEY=change-me
GRAPHITI_TIMEOUT_SECONDS=10

# Multi-tenant
GRAPHITI_ENTERPRISE_GROUP_ID=enterprise
```

```
# docker-compose (esquisse - a adapter selon packaging Graphiti)
services:
  graphiti:
    image: ghcr.io/<org>/graphiti:latest
    environment:
      - GRAPHITI_DB_DSN=postgresql://graphiti:***@postgres:5432/graphiti
    ports:
      - "8300:8300"
    depends_on:
      - postgres
```

## 12. KPIs & Validation

- KG: temps sous-graphe < 2s (depth <= 3); creation relation < 1s.
- Facts: flux "proposed -> approved/rejected" operationnel; conflits detectes; requetes temporelles OK.
- Memoire: recuperation contexte < 100 ms (cache), < 300 ms (persistant).
- Multi-utilisateur: isolation verifiee; priorisation entreprise en cas de conflit.
- Tests: E2E couvrant KG/Facts/Memory multi-tenant.

## 13. Risques & Mitigations

- Emballage Graphiti (service/lib) variable -> valider le mode d'integration le plus simple pour notre stack.
- Gouvernance temporelle/facts: si fonctionnalites Graphiti insuffisantes, completer cote Postgres (bi-temporel) derriere nos services.
- Perfs: index cote Qdrant/Graphiti; cache Redis; pagination stricte.
- Securite: auth API, controle acces par groupe, validation des entrees.

---

Annexe A - Notes "reutilisables" (branche Zep)
- Reutiliser: gestion utilisateurs, header `X-User-ID`, UI React, tests CRUD.
- A faire: propager `X-User-ID` vers client Graphiti; ajouter `graphiti_group_id` aux modeles/`users.json`; mettre a jour la doc/roadmap.

Annexe B - Politique de Conflit (entreprise vs utilisateur)
- Agregation des deux KGs pour fournir une reponse.
- Si contradiction: privilegier la relation/le fait issu du groupe `enterprise` et marquer le conflit (journal + metriques de gouvernance).