# Plan d'Intégration Zep pour SAP Knowledge Base

## 📋 Vue d'ensemble

Ce document présente l'analyse et le plan d'intégration de **Zep** (self-hosted) dans l'application SAP Knowledge Base pour exploiter trois capacités clés :
- **Temporal Knowledge Graph (TKG)** : Historique et gestion des conflits documentaires
- **Knowledge Graph (KG)** : Relations entre entités SAP et concepts
- **Mémoire conversationnelle** : Sessions utilisateurs enrichies

**⚠️ PRÉREQUIS IDENTIFIÉ** : Implémentation d'un système multi-utilisateurs simple avant l'intégration Zep.

## 🏗️ Architecture Conceptuelle

### Rôle de Zep dans l'écosystème existant

```
┌─────────────────────────────────────────────────────────────────┐
│                    COUCHES APPLICATIVES                        │
├─────────────────────────────────────────────────────────────────┤
│  Redis (Queue/Cache)  │  Qdrant (Search)  │  Zep (Knowledge)   │
│  ─────────────────────│─────────────────────│─────────────────── │
│  • Jobs d'ingestion   │  • Embeddings       │  • Facts           │
│  • Cache temporaire   │  • Similarité       │  • Relations       │
│  • Sessions import    │  • Collections Q/A  │  • Conflits        │
│                       │  • Métadonnées      │  • Sessions users  │
└─────────────────────────────────────────────────────────────────┘
```

**Zep complète l'architecture** existante en ajoutant une couche sémantique et temporelle :

- **Redis** → Orchestration et cache temporaire
- **Qdrant** → Recherche vectorielle et stockage chunks
- **Zep** → Vérité documentaire, relations et mémoire conversationnelle

### Distinction fondamentale des données

#### 1. Document Facts (Autoritatifs)
```
Source : Documents SAP officiels
Stockage : Zep TKG + KG
Persistance : Permanente avec versioning
Modification : Uniquement via validation humaine des conflits
```

#### 2. Conversation Contexts (Éphémères)
```
Source : Interactions utilisateurs
Stockage : Zep Memory + Sessions
Persistance : Session-scoped (configurable)
Modification : Automatique via chat
```

## 🧠 Capacités Zep et cas d'usage

### 1. Temporal Knowledge Graph (TKG)

**Objectif** : Maintenir l'historique complet des faits documentaires avec détection automatique des contradictions.

**Fonctionnalités clés** :
- **Versioning des faits** : Chaque fait documentaire est horodaté et lié à sa source
- **Détection de conflits** : Algorithmes de détection automatique des contradictions
- **Non-écrasement** : Aucun fait n'est jamais remplacé automatiquement

**Exemples concrets** :
```
Fait 1 (Document A, 2024-01) : "SAP BTP Audit Log retention = 30 jours"
Fait 2 (Document B, 2024-06) : "SAP BTP Audit Log retention = 90 jours"
→ Conflit détecté : Rétention Audit Log BTP contradictoire
```

### 2. Knowledge Graph (KG)

**Objectif** : Créer un réseau de relations entre entités SAP pour améliorer la contextualisation.

**Types d'entités** :
- **Solutions** : SAP S/4HANA, SAP BTP, SAP SuccessFactors
- **Modules** : Audit Log Service, Identity Authentication
- **Attributs** : SLA, RTO, RPO, Retention, Compliance
- **Documents** : Slides, sections, chunks

**Relations typiques** :
```
SAP_BTP ─[CONTAINS]→ Audit_Log_Service
Audit_Log_Service ─[HAS_ATTRIBUTE]→ Retention_90_days
Document_Security_BTP ─[DESCRIBES]→ Audit_Log_Service
Slide_78 ─[EXPLAINS]→ Retention_Policy
```

### 3. Mémoire conversationnelle

**Objectif** : Maintenir le contexte des sessions utilisateurs pour des interactions plus intelligentes.

**Composants** :
- **Résumés de conversation** : Synthèse automatique des échanges
- **Entités mentionnées** : Tracking des concepts discutés
- **Documents consultés** : Historique des sources référencées
- **Questions implicites** : Résolution du contexte ("et pour la rétention ?")

## ⚖️ Stratégie de gestion des conflits

### Cycle de vie d'un conflit documentaire

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   DÉTECTION     │───→│  ENREGISTREMENT │───→│   VALIDATION    │
│                 │    │                 │    │                 │
│ • Ingestion doc │    │ • Stockage Zep  │    │ • Interface web │
│ • Comparaison   │    │ • API backend   │    │ • Choix humain  │
│ • Algorithmes   │    │ • État "open"   │    │ • Résolution    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
           │                       │                       │
           └───────────────────────┼───────────────────────┘
                                   ▼
                          ┌─────────────────┐
                          │   RÉSOLUTION    │
                          │                 │
                          │ • Fait choisi   │
                          │ • Historique    │
                          │ • État "closed" │
                          └─────────────────┘
```

### Types de conflits détectés

1. **Conflits de valeurs** : Même attribut, valeurs différentes
2. **Conflits temporels** : Évolutions non compatibles dans le temps
3. **Conflits de source** : Sources contradictoires sur même fait
4. **Conflits de scope** : Périmètres d'application différents

### Interface de résolution

**Page Frontend "Conflits documentaires"** :
- Liste des conflits ouverts avec priorité
- Détails du conflit (sources, dates, valeurs)
- Prévisualisation des documents sources
- Actions : Choisir fait A/B, Marquer non-conflit, Escalader

### Comportement du chat avec conflits

**Stratégie par défaut** : Mentionner l'existence du conflit
```
"D'après mes informations, la rétention des Audit Logs SAP BTP peut être
de 30 ou 90 jours selon les sources. Un conflit documentaire est en cours
de résolution. Consultez la page 'Conflits' pour plus de détails."
```

## 🔗 Exploitation du Knowledge Graph

### Enrichissement automatique des filtres Qdrant

**Scénario** : Utilisateur cherche "Azure + Audit Logs + Security"

**Processus d'enrichissement** :
1. **Expansion d'entités** : Azure → SAP BTP → Audit Log Service
2. **Relations découvertes** : Security → Compliance → Data Protection
3. **Filtres générés** :
   ```json
   {
     "must": [
       {"match": {"solution.main": "SAP Business Technology Platform"}},
       {"match": {"tags": ["audit", "security", "azure", "compliance"]}}
     ]
   }
   ```

### Assemblage de contexte intelligent

**Avant Zep** : Recherche basée uniquement sur similarité vectorielle
**Avec Zep** : Contexte enrichi par les relations du graphe

```
Question: "Quelle est la rétention pour BTP ?"
│
├─ Qdrant: Chunks similaires à "retention BTP"
├─ Zep KG: BTP ─[CONTAINS]→ Audit_Log_Service ─[HAS]→ Retention
└─ Contexte final: Chunks + Relations + Facts confirmés
```

## 💬 Mémoire conversationnelle détaillée

### Structure d'une session Zep

```json
{
  "session_id": "user_123_20241220",
  "summary": "Discussion sur SAP BTP security et audit logs",
  "entities": [
    {"name": "SAP BTP", "type": "solution", "mentioned_count": 5},
    {"name": "Audit Log Service", "type": "service", "mentioned_count": 3},
    {"name": "90 days retention", "type": "attribute", "mentioned_count": 2}
  ],
  "documents_consulted": [
    "SAP_BTP_Security_Compliance.pptx",
    "BTP_Audit_Configuration_Guide.pdf"
  ],
  "conversation_flow": [
    {"turn": 1, "user": "Comment configurer les audit logs BTP ?"},
    {"turn": 2, "assistant": "Les audit logs BTP se configurent via..."},
    {"turn": 3, "user": "Et pour la rétention ?"}  // Question implicite
  ]
}
```

### Résolution des questions implicites

**Question implicite** : "Et pour la rétention ?"
**Contexte Zep** : Dernière entité discutée = "Audit Log Service"
**Résolution** : "Rétention pour Audit Log Service BTP"

## 📊 Plan d'action en phases

### Phase 0 : Infrastructure Multi-Utilisateurs (2-3 semaines) 🆕

**Objectifs** :
- Implémenter un système multi-utilisateurs simple sans authentification complexe
- Préparer l'infrastructure backend et frontend pour la contextualisation par utilisateur
- Créer les fondations nécessaires aux sessions Zep individualisées

**Rationale** :
L'intégration Zep nécessite une gestion des sessions par utilisateur. Plutôt que d'implémenter un système d'authentification complet (qui peut évoluer vers SAP BTP), nous créons un sélecteur d'utilisateur simple permettant de basculer facilement entre différents contextes utilisateurs pour les tests et le développement.

**Livrables** :
- Modèle utilisateur simple (id, nom, rôle, dates)
- API backend CRUD utilisateurs (/api/users)
- Context React UserProvider avec localStorage persistence
- Composant UserSelector dans TopNavigation
- Migration des APIs existantes pour accepter le contexte utilisateur optionnel

**Architecture proposée** :
```typescript
interface User {
  id: string
  name: string
  email?: string
  role: 'admin' | 'expert' | 'user'
  created_at: string
  last_active: string
}

interface UserContext {
  currentUser: User | null
  availableUsers: User[]
  switchUser: (userId: string) => void
  createUser: (userData: Partial<User>) => Promise<User>
}
```

**Composants modifiés** :
- `TopNavigation.tsx` : Ajout UserSelector à droite
- `ChatPage.tsx` : Préparation persistence messages par utilisateur
- `api.ts` : Header `X-User-ID` automatique si utilisateur sélectionné
- Backend : Nouveaux endpoints + logging user context

**Gates de validation** :
- ✅ Tests manuels de changement d'utilisateur (fluidité UX)
- ✅ Vérification non-régression chat/ingestion existants
- ✅ Audit instrumentation : toutes les APIs propagent `X-User-ID`
- ✅ Preparation mapping utilisateur ↔ session Zep documentée
- ✅ Tests unitaires du CRUD utilisateurs

**Critères de succès** :
- ✅ Sélection et changement d'utilisateur fluide dans l'interface
- ✅ Persistence du choix utilisateur dans localStorage
- ✅ APIs prêtes pour contextualisation future (Zep sessions)
- ✅ Aucune régression sur fonctionnalités existantes
- ✅ Interface simple : dropdown + "Nouvel utilisateur" + suppression

### Phase 1 : Analyse & Design (3-4 semaines)

**Objectifs** :
- Modéliser les schémas de Facts, Relations, Conflicts, Sessions
- Définir les APIs d'intégration Zep ↔ Application
- Spécifier les algorithmes de détection de conflits

**Livrables** :
- Schémas de données Zep (Facts, Relations, Memory) avec modélisation JSON détaillée
- Matrice source → attribut : Mapping systématique documents SAP vers facts extraits
- Spécifications API backend pour gestion conflits
- Maquettes interface "Conflits documentaires"
- Documentation algorithmes détection conflits
- Plan de tests unitaires/fonctionnels pour les implémentations futures
- Backlog technique priorisé par risque/complexité

**Activités détaillées** :
1. **Audit de l'existant** : Analyser métadonnées actuelles (solution.main, tags, etc.)
2. **Inventaire sources SAP** : Catalogue des types documents et leur structure
3. **Modélisation Facts** : Définir structure facts documentaires avec source/timestamp
4. **Matrice extraction** : Document type → Entités → Attributs → Facts (mapping complet)
5. **Modélisation Relations** : Typer les relations entre entités SAP
6. **Design API** : Endpoints pour CRUD facts, détection conflits, sessions
7. **Spécification algorithmes** : Règles de détection de contradictions avec seuils
8. **Stratégie tests** : Plan tests automatisés pour chaque composant Zep

### Phase 2 : Déploiement Zep self-hosted (2-3 semaines)

**Objectifs** :
- Déployer Zep + Postgres/pgvector en Docker
- Configurer la persistence et les performances
- Tester la connectivité et les APIs de base

**Livrables** :
- Docker Compose avec Zep + Postgres configuré pour environnement dev
- Scripts d'initialisation base de données avec données de test
- Tests de connectivité et performance de base
- Documentation configuration POC (non production-ready)
- Plan de monitoring basique (logs, métriques essentielles)

**Configuration Docker** :
```yaml
services:
  zep-postgres:
    image: ankane/pgvector:v0.5.1
    environment:
      POSTGRES_DB: zep
      POSTGRES_USER: zep_user
      POSTGRES_PASSWORD: ${ZEP_POSTGRES_PASSWORD}
    volumes:
      - zep_postgres_data:/var/lib/postgresql/data

  zep:
    image: ghcr.io/getzep/zep:latest
    ports:
      - "8080:8080"
    environment:
      ZEP_STORE_TYPE: postgres
      ZEP_STORE_POSTGRES_DSN: postgres://zep_user:${ZEP_POSTGRES_PASSWORD}@zep-postgres:5432/zep
    depends_on:
      - zep-postgres
```

### Phase 3 : Pipeline documentaire → Zep (4-5 semaines)

**Objectifs** :
- Étendre les pipelines d'ingestion pour alimenter Zep
- Mapper chunks Qdrant vers Facts Zep
- Implémenter extraction d'entités et relations

**Livrables** :
- Pipeline enrichi : Document → Qdrant + Zep avec jobs asynchrones
- Service d'extraction d'entités SAP (regex, NER, règles métier)
- API de création Facts/Relations automatique
- Système de backfill pour traitement documents historiques existants
- Tests pipeline complet avec documents réels + gestion d'erreurs/retry
- Observabilité pipeline (logs détaillés, métriques de succès)

**Architecture pipeline** :
```
Document → Processing → {
  ├─ Qdrant (chunks + embeddings)
  └─ Zep (facts + entities + relations)
}
```

**Extraction d'entités** :
- Solutions SAP (regex + NER)
- Attributs techniques (SLA, RTO, retention, etc.)
- Relations implicites (module X dans solution Y)

### Phase 4 : Gestion des conflits (3-4 semaines)

**Objectifs** :
- Implémenter détection automatique conflits
- Développer API backend gestion conflits
- Créer page frontend résolution conflits

**Livrables** :
- Service de détection conflits documentaires
- API REST gestion conflits (list, get, resolve)
- Interface web résolution conflits
- Workflow validation humaine complet

**API Backend** :
```
GET /api/conflicts → Liste conflits ouverts
GET /api/conflicts/{id} → Détails conflit
POST /api/conflicts/{id}/resolve → Résolution conflit
GET /api/conflicts/stats → Métriques conflits
```

### Phase 5 : Exploitation KG pour recherche (4-5 semaines)

**Objectifs** :
- Enrichir requêtes Qdrant avec relations Zep
- Améliorer assemblage contexte RAG
- Optimiser performances recherche hybride

**Livrables** :
- Service d'expansion de requêtes via KG
- Assemblage contexte intelligent Facts + Chunks
- Tests A/B simples pour mesurer impact sur pertinence des réponses
- Optimisations performances (cache, indexation)
- Métriques qualité recherche améliorée avec baseline de référence

**Processus hybride** :
1. Question utilisateur → Extraction entités
2. Zep KG → Expansion entités + relations
3. Qdrant → Recherche vectorielle enrichie
4. Zep Facts → Validation informations
5. Synthèse → Contexte Facts + Chunks + Relations

### Phase 6 : Mémoire conversationnelle (3-4 semaines)

**Objectifs** :
- Implémenter sessions utilisateurs Zep (requiert Phase 0 complétée)
- Intégrer mémoire dans chat existant avec contexte utilisateur
- Gérer contexte multi-tours et entités par utilisateur individuel

**Livrables** :
- Service de gestion sessions Zep avec mapping utilisateur (Phase 0)
- Chat enrichi avec mémoire conversationnelle par utilisateur
- Résolution questions implicites basée sur contexte utilisateur
- Interface historique conversations segmentée par utilisateur
- Règles de purge/rétention configurables par type d'utilisateur

**Enrichissement chat** :
- Contexte session automatique
- Suggestions basées sur historique
- Détection entités mentionnées
- Personnalisation réponses

### Phase 7 : Monitoring & Gouvernance (2-3 semaines)

**Objectifs** :
- Métriques Zep intégrées au monitoring
- Tableaux de bord gouvernance données
- Alertes et maintenance automatisée

**Livrables** :
- Dashboard métriques Zep basique (facts, conflits, sessions)
- Alertes essentielles (conflits critiques, erreurs pipeline)
- KPIs POC mesurables avec baseline avant/après
- Procédures maintenance minimales pour environnement dev
- Logs structurés pour analyse et debug

**Métriques POC** :
- Nombre facts confirmés vs en conflit (ratio qualité)
- Taux résolution conflits dans délais raisonnables
- Précision extraction entités/relations (échantillon manuel)
- Latence assemblage contexte (< 200ms objectif)
- Taux utilisation mémoire conversationnelle par utilisateur
- Amélioration satisfaction utilisateur (avant/après questionnaire simple)

## 🏗️ Schéma d'architecture intégrée

```
                    ┌─────────────────────────────────────────────┐
                    │              FRONTEND NEXT.JS               │
                    │  ┌─────────────┐  ┌─────────────┐           │
                    │  │    Chat     │  │  Conflits   │           │
                    │  │  Interface  │  │ Management  │           │
                    │  └─────────────┘  └─────────────┘           │
                    └───────────────┬─────────────────────────────┘
                                    │ API Calls
                    ┌───────────────▼─────────────────────────────┐
                    │             BACKEND FASTAPI                 │
                    │                                             │
   ┌────────────────┼─── Chat Service ────────────────────────────┤
   │                │     │                                       │
   │  ┌─────────────▼─────▼──┐     ┌─────────────────────────────┐│
   │  │      ZEP MEMORY      │     │      ZEP KNOWLEDGE          ││
   │  │                      │     │                             ││
   │  │ • Sessions Users     │     │ • Document Facts            ││
   │  │ • Résumés           │ ◄──►│ • Temporal Graph            ││
   │  │ • Entités discutées │     │ • Relations SAP             ││
   │  │ • Contexte multi-tour│     │ • Détection conflits       ││
   │  └──────────────────────┘     └─────────────────────────────┘│
   │                │                           │                 │
   │    INGESTION    ▼                          │                 │
   │    PIPELINE     │                          │                 │
   │                 │              ┌───────────▼─────────────────┤
   │  ┌──────────────▼─────────────┐│       QDRANT VECTOR       ││
   │  │         REDIS             ││                            ││
   │  │                           ││ • Embeddings & Chunks      ││
   │  │ • Job Queue               ││ • Collections Q/A          ││
   │  │ • Cache temporaire        ││ • Métadonnées enrichies    ││
   │  │ • Import tracking         ││ • Recherche similarité     ││
   │  └───────────────────────────┘└─────────────────────────────┘│
   │                                                              │
   └──────────────────────────────────────────────────────────────┘

                    FLUX PRINCIPAL D'UNE REQUÊTE CHAT

┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ 1. Question │───►│2. Mémoire   │───►│3. KG Zep    │───►│4. Qdrant    │
│ Utilisateur │    │ Session     │    │ Expansion   │    │ Search      │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │                  │
       ▼                  ▼                  ▼                  ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│"Rétention?" │    │Dernière     │    │BTP →        │    │Filtres:     │
│             │    │entité:      │    │AuditLog →   │    │solution=BTP │
│             │    │"BTP Audit"  │    │Retention    │    │tags=audit   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                                │
       ┌─────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│5. Zep Facts │───►│6. Conflit   │───►│7. Synthèse  │───►│8. Réponse   │
│ Validation  │    │ Check       │    │ Contexte    │    │ Utilisateur │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │                  │
       ▼                  ▼                  ▼                  ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│Facts: 90j   │    │Conflit      │    │Facts +      │    │"La rétention│
│retention    │    │détecté?     │    │Chunks +     │    │est 90 jours │
│confirmed    │    │→ Mention    │    │Relations    │    │(confirmé)"  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

## 📊 Métriques et gouvernance

### Indicateurs de performance

**Qualité des données** :
- Ratio Facts confirmés / Facts en conflit
- Temps moyen de résolution des conflits
- Précision des relations extraites
- Couverture entités SAP identifiées

**Performance technique** :
- Latence assemblage contexte (< 200ms)
- Temps détection conflits (< 5s)
- Mémoire utilisée par session
- Throughput pipeline ingestion

**Usage utilisateurs** :
- Sessions actives avec mémoire
- Questions implicites résolues
- Satisfaction contextualisation
- Réduction reformulations

### Alertes et monitoring

**Conflits critiques** :
- Nouveau conflit sur attribut critique (SLA, sécurité)
- Accumulation conflits non résolus (> 10)
- Dégradation qualité relations (< 80%)

**Performance système** :
- Latence Zep excessive (> 500ms)
- Erreurs pipeline ingestion
- Espace disque Postgres critique

## 🚀 Points d'attention et risques

### Risques techniques

1. **Performance Zep** : Impact latence sur expérience utilisateur
   - **Mitigation** : Cache intelligent, optimisation requêtes

2. **Volume données** : Croissance Facts/Relations dans le temps
   - **Mitigation** : Archivage automatique, indexation optimisée

3. **Complexité pipeline** : Pipeline ingestion plus complexe
   - **Mitigation** : Tests automatisés, monitoring détaillé

### Risques fonctionnels

1. **Surinformation** : Trop de conflits détectés (faux positifs)
   - **Mitigation** : Seuils configurables, ML pour filtrage

2. **Adoption utilisateurs** : Interface conflits trop complexe
   - **Mitigation** : UX simple, priorisation intelligente

3. **Gouvernance** : Accumulation conflits non traités
   - **Mitigation** : Workflows automatisés, escalation

## ✅ Critères de succès

### Phase 0 (Multi-utilisateurs) ✅
- ✅ Sélecteur utilisateur fonctionnel dans TopNavigation
- ✅ CRUD utilisateurs via API backend
- ✅ Persistence choix utilisateur dans localStorage
- ✅ Headers `X-User-ID` automatiques dans requêtes API
- ✅ Aucune régression sur fonctionnalités existantes

### Phase pilote (après Phase 4)
- ✅ 100% des documents ingérés génèrent des Facts Zep
- ✅ Détection automatique de 3 types de conflits minimum
- ✅ Interface résolution conflits opérationnelle
- ✅ 0 perte de données dans migration pipeline

### Production complète (après Phase 7)
- ✅ < 200ms latence moyenne assemblage contexte
- ✅ > 90% des conflits résolus dans 48h
- ✅ 5000+ Facts documentaires confirmés
- ✅ Sessions utilisateurs avec mémoire > 70% des chats
- ✅ Amélioration satisfaction utilisateurs (+20% vs baseline)

---

*Ce plan d'intégration Zep transformera la SAP Knowledge Base en un système véritablement intelligent, capable de maintenir la cohérence documentaire, d'exploiter les relations sémantiques, et de fournir une expérience conversationnelle enrichie par la mémoire et le contexte.*