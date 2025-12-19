# Phase 2.5 : Memory Layer - Mémoire Conversationnelle

**Version:** 1.1
**Date:** 2025-12-17
**Dernière MAJ:** 2025-12-19
**Status:** 🟢 COMPLÉTÉ - 100% (Étapes 1-6 + UI Fixes)
**Durée estimée:** 3-4 semaines (Semaines 25-28)
**Prérequis:** Phase 2 complète (Intelligence Relationnelle)

---

## Table des Matières

1. [Vision et Objectifs](#1-vision-et-objectifs)
2. [Architecture Technique](#2-architecture-technique)
3. [Composants Principaux](#3-composants-principaux)
4. [Schéma Neo4j](#4-schéma-neo4j)
5. [APIs Backend](#5-apis-backend)
6. [Context Resolver](#6-context-resolver)
7. [Intelligent Summarizer](#7-intelligent-summarizer)
8. [Export PDF](#8-export-pdf)
9. [Planning Détaillé](#9-planning-détaillé)
10. [KPIs de Succès](#10-kpis-de-succès)
11. [Risques et Mitigation](#11-risques-et-mitigation)

---

## 1. Vision et Objectifs

### 1.1 Vision

> **"Une mémoire conversationnelle qui ne repart jamais de zéro."**

KnowWhere doit se souvenir du contexte des échanges précédents pour éviter l'effet "atomique cloisonné" où chaque question est traitée indépendamment. La Memory Layer permet une expérience conversationnelle continue et contextuelle.

### 1.2 Problème Résolu

**Sans Memory Layer :**
```
👤 "Quelles sont les implications de sécurité pour migrer vers S/4HANA Cloud ?"
🤖 [Réponse détaillée sur IAS, RBAC, Cloud Connector...]

👤 "Et pour la rétention des logs ?"
🤖 "Pouvez-vous préciser le contexte de votre question ?"  ❌ FRUSTRANT
```

**Avec Memory Layer :**
```
👤 "Quelles sont les implications de sécurité pour migrer vers S/4HANA Cloud ?"
🤖 [Réponse détaillée sur IAS, RBAC, Cloud Connector...]

👤 "Et pour la rétention des logs ?"
🤖 "Dans le contexte de la sécurité S/4HANA Cloud, la rétention ✅ INTELLIGENT
    des logs d'audit est configurée via SAP Audit Log Service..."
```

### 1.3 Objectifs Stratégiques

| Objectif | Description | Métrique |
|----------|-------------|----------|
| **Continuité** | Maintenir le contexte entre les questions | Résolution implicite > 90% |
| **Mémoire** | Se souvenir des sessions passées | Reprise session fonctionnelle |
| **Synthèse** | Générer des comptes-rendus intelligents | Satisfaction > 4/5 |
| **Traçabilité** | Retrouver l'historique par utilisateur | Recherche historique < 2s |
| **Export** | Produire des livrables exploitables | Export PDF fonctionnel |

### 1.4 Scope Phase 2.5

**INCLUS :**
- Gestion des sessions de conversation
- Mémoire utilisateur (single context)
- Résolution de questions implicites
- Historique des conversations
- Génération de résumés intelligents
- Export PDF des sessions

**EXCLU (Phase ultérieure) :**
- Multi-projets par utilisateur
- Partage de sessions entre utilisateurs
- Collaboration temps réel
- Synchronisation multi-devices

---

## 2. Architecture Technique

### 2.1 Vue d'Ensemble

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MEMORY LAYER                                   │
│                                                                          │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────┐ │
│  │   Session      │  │    User        │  │   Intelligent              │ │
│  │   Manager      │  │    Profile     │  │   Summarizer               │ │
│  │                │  │                │  │                            │ │
│  │ • Create/Load  │  │ • Preferences  │  │ • LLM-powered             │ │
│  │ • Messages     │  │ • History      │  │ • Business-oriented       │ │
│  │ • Graph State  │  │ • Interests    │  │ • Action extraction       │ │
│  └───────┬────────┘  └───────┬────────┘  └───────────┬────────────────┘ │
│          │                   │                       │                   │
│          └───────────────────┼───────────────────────┘                   │
│                              │                                           │
│                    ┌─────────▼─────────┐                                │
│                    │  Context Resolver  │                                │
│                    │                    │                                │
│                    │ • Implicit query   │                                │
│                    │ • Entity tracking  │                                │
│                    │ • Topic detection  │                                │
│                    └─────────┬─────────┘                                │
│                              │                                           │
├──────────────────────────────┼───────────────────────────────────────────┤
│                              │                                           │
│                    ┌─────────▼─────────┐                                │
│                    │      Neo4j        │                                │
│                    │  (Conversational  │                                │
│                    │     Memory)       │                                │
│                    └───────────────────┘                                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Stack Technologique

| Couche | Technologie | Justification |
|--------|-------------|---------------|
| **Storage** | Neo4j (existant) | Graph natif, relations temporelles |
| **Backend** | FastAPI (existant) | Endpoints mémoire |
| **Cache** | Redis (existant) | Cache sessions actives |
| **LLM** | Claude/GPT | Génération résumés intelligents |
| **PDF** | WeasyPrint / ReportLab | Génération PDF |

### 2.3 Pourquoi Neo4j (et pas Zep)

**Historique :** Le projet avait initialement prévu d'utiliser Zep pour la mémoire conversationnelle, mais ce choix a été abandonné pour les raisons suivantes :

| Critère | Zep | Neo4j Natif |
|---------|-----|-------------|
| **Flexibilité schéma** | ⚠️ Pré-défini | ✅ Personnalisable |
| **Intégration KG** | ❌ Séparé | ✅ Même base |
| **Requêtes complexes** | ⚠️ Limitées | ✅ Cypher complet |
| **Maintenance** | ⚠️ Dépendance externe | ✅ Contrôle total |
| **Coût** | ⚠️ Cloud payant | ✅ Self-hosted |

**Décision :** Implémenter nativement dans Neo4j pour une intégration parfaite avec le Knowledge Graph existant.

---

## 3. Composants Principaux

### 3.1 Session Manager

Gère le cycle de vie des sessions de conversation.

```python
# src/knowbase/memory/session_manager.py

class SessionManager:
    """Gestionnaire de sessions conversationnelles."""

    async def create_session(
        self,
        user_id: str,
        title: Optional[str] = None
    ) -> Session:
        """Créer une nouvelle session."""
        pass

    async def get_session(self, session_id: str) -> Session:
        """Récupérer une session existante."""
        pass

    async def list_sessions(
        self,
        user_id: str,
        limit: int = 10
    ) -> List[SessionSummary]:
        """Lister les sessions d'un utilisateur."""
        pass

    async def add_message(
        self,
        session_id: str,
        message: Message
    ) -> Message:
        """Ajouter un message à la session."""
        pass

    async def update_graph_state(
        self,
        session_id: str,
        graph_state: GraphState
    ) -> None:
        """Mettre à jour l'état du Living Graph."""
        pass

    async def close_session(self, session_id: str) -> None:
        """Fermer une session (soft close)."""
        pass
```

### 3.2 User Profile

Stocke les préférences et l'historique utilisateur.

```python
# src/knowbase/memory/user_profile.py

class UserProfile:
    """Profil utilisateur avec préférences et historique."""

    user_id: str
    display_name: str
    created_at: datetime

    # Préférences
    preferences: UserPreferences

    # Statistiques
    total_sessions: int
    total_questions: int
    concepts_explored: List[str]  # IDs des concepts fréquemment explorés

    # Contexte actif
    active_session_id: Optional[str]

class UserPreferences:
    """Préférences utilisateur pour l'UI."""

    expert_mode: bool = False
    graph_expansion_depth: int = 2
    confidence_threshold: float = 0.7
    max_sources: int = 10
    preferred_layout: str = "force"  # force, hierarchical, radial
    show_labels_always: bool = True
```

### 3.3 Conversation History

Stocke et indexe l'historique des conversations.

```python
# src/knowbase/memory/conversation_history.py

class ConversationHistory:
    """Historique des conversations avec recherche."""

    async def search_history(
        self,
        user_id: str,
        query: str,
        limit: int = 10
    ) -> List[HistoryMatch]:
        """Rechercher dans l'historique utilisateur."""
        pass

    async def get_related_sessions(
        self,
        session_id: str,
        limit: int = 5
    ) -> List[SessionSummary]:
        """Trouver les sessions similaires."""
        pass

    async def get_concept_history(
        self,
        user_id: str,
        concept_id: str
    ) -> List[ConceptInteraction]:
        """Historique des interactions avec un concept."""
        pass
```

---

## 4. Schéma Neo4j

### 4.1 Nœuds Memory Layer

```cypher
// User - Utilisateur du système
CREATE CONSTRAINT user_id IF NOT EXISTS
FOR (u:User) REQUIRE u.user_id IS UNIQUE;

(:User {
    user_id: String,           // ID unique utilisateur
    display_name: String,      // Nom affiché
    email: String,             // Email (optionnel)
    created_at: DateTime,      // Date création
    last_active: DateTime,     // Dernière activité

    // Préférences (JSON sérialisé)
    preferences: String,

    // Statistiques
    total_sessions: Integer,
    total_questions: Integer
})

// Session - Session de conversation
CREATE CONSTRAINT session_id IF NOT EXISTS
FOR (s:Session) REQUIRE s.session_id IS UNIQUE;

(:Session {
    session_id: String,        // ID unique session
    title: String,             // Titre auto-généré ou manuel
    created_at: DateTime,      // Date création
    updated_at: DateTime,      // Dernière modification
    closed_at: DateTime,       // Date fermeture (null si active)

    // Statistiques
    message_count: Integer,
    concept_count: Integer,

    // État du Living Graph (JSON)
    graph_state: String,

    // Contexte détecté
    detected_topics: [String], // Topics identifiés

    // Résumé (si généré)
    summary: String,
    summary_generated_at: DateTime
})

// Message - Message dans une session
CREATE CONSTRAINT message_id IF NOT EXISTS
FOR (m:Message) REQUIRE m.message_id IS UNIQUE;

(:Message {
    message_id: String,        // ID unique message
    role: String,              // "user" | "assistant"
    content: String,           // Contenu du message
    created_at: DateTime,      // Timestamp

    // Pour les messages assistant
    confidence: Float,         // Score confiance réponse
    sources_count: Integer,    // Nombre de sources utilisées

    // Concepts détectés/utilisés
    concept_ids: [String],     // IDs des concepts impliqués

    // Query analysis (pour questions user)
    detected_concepts: String, // JSON des concepts détectés
    expanded_concepts: String  // JSON des concepts après expansion
})

// SessionContext - Contexte actif d'une session
(:SessionContext {
    context_id: String,

    // Entités actives (client, projet, etc.)
    active_entities: String,   // JSON {type: value}

    // Topics actifs
    active_topics: [String],

    // Dernier sujet abordé
    last_topic: String,
    last_concept_id: String,

    // Score de confiance du contexte
    confidence: Float
})
```

### 4.2 Relations Memory Layer

```cypher
// User -> Session
(u:User)-[:HAS_SESSION {created_at: DateTime}]->(s:Session)

// Session -> Messages (ordonnés)
(s:Session)-[:HAS_MESSAGE {order: Integer}]->(m:Message)

// Message -> Message (chaînage)
(m1:Message)-[:FOLLOWED_BY]->(m2:Message)

// Message -> Concept (concepts utilisés)
(m:Message)-[:MENTIONS_CONCEPT {
    role: String,           // "query" | "used" | "suggested"
    confidence: Float
}]->(c:Concept)

// Session -> Concept (concepts explorés dans session)
(s:Session)-[:EXPLORED_CONCEPT {
    first_seen: DateTime,
    last_seen: DateTime,
    interaction_count: Integer
}]->(c:Concept)

// Session -> SessionContext
(s:Session)-[:HAS_CONTEXT]->(ctx:SessionContext)

// User -> Concept (intérêts utilisateur)
(u:User)-[:INTERESTED_IN {
    score: Float,           // Score d'intérêt calculé
    interaction_count: Integer,
    last_interaction: DateTime
}]->(c:Concept)

// Session -> Session (sessions liées)
(s1:Session)-[:RELATED_TO {
    similarity: Float,
    common_concepts: Integer
}]->(s2:Session)
```

### 4.3 Index et Contraintes

```cypher
// Index pour recherche rapide
CREATE INDEX user_email IF NOT EXISTS FOR (u:User) ON (u.email);
CREATE INDEX session_created IF NOT EXISTS FOR (s:Session) ON (s.created_at);
CREATE INDEX session_user IF NOT EXISTS FOR (s:Session) ON (s.user_id);
CREATE INDEX message_created IF NOT EXISTS FOR (m:Message) ON (m.created_at);

// Index full-text pour recherche historique
CREATE FULLTEXT INDEX message_content IF NOT EXISTS
FOR (m:Message) ON EACH [m.content];

CREATE FULLTEXT INDEX session_title IF NOT EXISTS
FOR (s:Session) ON EACH [s.title, s.summary];
```

### 4.4 Exemples de Requêtes

```cypher
// Récupérer les sessions récentes d'un utilisateur
MATCH (u:User {user_id: $user_id})-[:HAS_SESSION]->(s:Session)
WHERE s.closed_at IS NULL OR s.closed_at > datetime() - duration('P7D')
RETURN s
ORDER BY s.updated_at DESC
LIMIT 10;

// Récupérer le contexte actif d'une session
MATCH (s:Session {session_id: $session_id})-[:HAS_CONTEXT]->(ctx:SessionContext)
RETURN ctx;

// Trouver les concepts fréquemment explorés par l'utilisateur
MATCH (u:User {user_id: $user_id})-[r:INTERESTED_IN]->(c:Concept)
WHERE r.interaction_count > 3
RETURN c, r.score, r.interaction_count
ORDER BY r.score DESC
LIMIT 20;

// Rechercher dans l'historique des messages
CALL db.index.fulltext.queryNodes('message_content', $search_query)
YIELD node, score
MATCH (s:Session)-[:HAS_MESSAGE]->(node)
MATCH (u:User {user_id: $user_id})-[:HAS_SESSION]->(s)
RETURN s.session_id, s.title, node.content, score
ORDER BY score DESC
LIMIT 10;
```

---

## 5. APIs Backend

### 5.1 Endpoints Sessions

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/memory/sessions` | GET | Liste des sessions utilisateur |
| `/api/memory/sessions` | POST | Créer nouvelle session |
| `/api/memory/sessions/{id}` | GET | Détail d'une session |
| `/api/memory/sessions/{id}` | PUT | Mettre à jour session (titre, etc.) |
| `/api/memory/sessions/{id}` | DELETE | Supprimer session |
| `/api/memory/sessions/{id}/messages` | GET | Messages d'une session |
| `/api/memory/sessions/{id}/graph-state` | GET/PUT | État du Living Graph |

### 5.2 Endpoints Context

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/memory/sessions/{id}/context` | GET | Contexte actif |
| `/api/memory/context/resolve` | POST | Résoudre question implicite |

### 5.3 Endpoints Summary

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/memory/sessions/{id}/summary` | POST | Générer résumé |
| `/api/memory/sessions/{id}/summary` | GET | Récupérer résumé existant |
| `/api/memory/sessions/{id}/export` | GET | Exporter en PDF |

### 5.4 Endpoints User Profile

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/memory/user/profile` | GET | Profil utilisateur |
| `/api/memory/user/profile` | PUT | Mettre à jour profil |
| `/api/memory/user/preferences` | GET/PUT | Préférences |
| `/api/memory/user/history` | GET | Recherche historique |

### 5.5 Spécifications API Détaillées

#### POST `/api/memory/sessions`

**Request:**
```json
{
  "title": "Migration S/4HANA Security",  // Optionnel
  "initial_context": {                    // Optionnel
    "client": "Acme Corp",
    "project": "Cloud Migration"
  }
}
```

**Response:**
```json
{
  "session_id": "sess_abc123",
  "title": "Migration S/4HANA Security",
  "created_at": "2025-12-17T10:00:00Z",
  "context": {
    "active_entities": {"client": "Acme Corp", "project": "Cloud Migration"},
    "active_topics": [],
    "confidence": 1.0
  }
}
```

#### POST `/api/memory/context/resolve`

**Request:**
```json
{
  "session_id": "sess_abc123",
  "query": "Et pour la rétention des logs ?"
}
```

**Response:**
```json
{
  "resolved_query": "Dans le contexte de la sécurité S/4HANA Cloud, quelles sont les options de rétention des logs ?",
  "context_used": {
    "topic": "S/4HANA Security",
    "last_concepts": ["IAS", "RBAC", "Cloud Connector"],
    "confidence": 0.92
  },
  "disambiguation_needed": false,
  "suggestions": []
}
```

#### POST `/api/memory/sessions/{id}/summary`

**Request:**
```json
{
  "format": "business",  // "business" | "technical" | "actions_only"
  "include_sources": true,
  "include_actions": true,
  "language": "fr"
}
```

**Response:**
```json
{
  "summary_id": "sum_xyz789",
  "session_id": "sess_abc123",
  "generated_at": "2025-12-17T11:00:00Z",
  "content": {
    "title": "Migration S/4HANA Security - Synthèse",
    "context": "Recherche sur les aspects sécurité de la migration...",
    "key_points": [
      {
        "topic": "Architecture Sécurité",
        "content": "IAS est le point central...",
        "sources": ["doc1", "doc2"]
      }
    ],
    "actions": [
      "Configurer IAS avec AD corporate",
      "Mapper rôles SAP GUI vers Business Roles Cloud"
    ],
    "uncovered_areas": [
      "Audit et logging des accès",
      "Chiffrement des données"
    ],
    "sources_used": [
      {"id": "doc1", "title": "SAP S/4HANA Security Guide", "citations": 15}
    ]
  },
  "word_count": 450,
  "export_available": true
}
```

---

## 6. Context Resolver

### 6.1 Fonctionnement

Le Context Resolver analyse les questions pour détecter le contexte implicite et enrichir la requête.

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONTEXT RESOLVER                              │
│                                                                  │
│  Input: "Et pour la rétention ?"                                │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. ANALYSE SYNTAXIQUE                                    │    │
│  │    - Détection référence implicite ("Et pour")          │    │
│  │    - Extraction sujet incomplet ("rétention")           │    │
│  │    - Identification lacune contextuelle                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 2. RÉCUPÉRATION CONTEXTE                                 │    │
│  │    - Session context: {topic: "S/4HANA Security"}       │    │
│  │    - Last concepts: [IAS, RBAC, Cloud Connector]        │    │
│  │    - Active entities: {client: "Acme Corp"}             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 3. RÉSOLUTION                                            │    │
│  │    - Match "rétention" + "Security" → "log retention"   │    │
│  │    - Enrichissement avec contexte S/4HANA Cloud         │    │
│  │    - Score confiance: 0.92                              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  Output: "Dans le contexte de la sécurité S/4HANA Cloud,        │
│           quelles sont les options de rétention des logs ?"      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Patterns de Résolution

| Pattern | Exemple | Résolution |
|---------|---------|------------|
| **Référence directe** | "Et pour X ?" | Ajoute contexte session |
| **Pronom implicite** | "Comment le configurer ?" | Résout "le" → dernier concept |
| **Continuation** | "Plus de détails" | Étend dernière réponse |
| **Comparaison** | "Et en Cloud ?" | Compare avec contexte On-Prem |
| **Action passée** | "Les actions qu'on avait prévues" | Recherche historique |

### 6.3 Implémentation

```python
# src/knowbase/memory/context_resolver.py

class ContextResolver:
    """Résout les questions implicites en utilisant le contexte."""

    async def resolve(
        self,
        session_id: str,
        query: str
    ) -> ResolvedQuery:
        """Résoudre une question potentiellement implicite."""

        # 1. Analyser la syntaxe
        analysis = self._analyze_query(query)

        if not analysis.needs_context:
            return ResolvedQuery(
                original=query,
                resolved=query,
                context_used=None,
                confidence=1.0
            )

        # 2. Récupérer le contexte
        context = await self._get_session_context(session_id)

        # 3. Résoudre
        resolved = await self._resolve_with_context(
            query,
            analysis,
            context
        )

        return resolved

    def _analyze_query(self, query: str) -> QueryAnalysis:
        """Analyse syntaxique pour détecter les références implicites."""

        implicit_patterns = [
            r"^et (pour|concernant|sur)",  # "Et pour X ?"
            r"^(le|la|les|ce|cette|ces) ",  # Pronoms
            r"^comment (le|la|les) ",        # "Comment le configurer ?"
            r"^plus de (détails|info)",      # Continuation
            r"qu'on avait (dit|prévu|vu)",   # Référence passée
        ]

        # ... détection patterns

    async def _get_session_context(
        self,
        session_id: str
    ) -> SessionContext:
        """Récupérer le contexte actif de la session."""

        # Depuis Neo4j
        context = await self.neo4j.get_session_context(session_id)

        # Enrichir avec derniers messages
        recent_messages = await self.neo4j.get_recent_messages(
            session_id,
            limit=5
        )

        return SessionContext(
            active_topics=context.active_topics,
            active_entities=context.active_entities,
            last_concepts=self._extract_concepts(recent_messages),
            last_topic=context.last_topic,
            confidence=context.confidence
        )

    async def _resolve_with_context(
        self,
        query: str,
        analysis: QueryAnalysis,
        context: SessionContext
    ) -> ResolvedQuery:
        """Résoudre la question avec le contexte."""

        # Utiliser LLM pour reformulation naturelle
        prompt = f"""
        Question originale: {query}

        Contexte de la conversation:
        - Sujet principal: {context.active_topics}
        - Derniers concepts: {context.last_concepts}
        - Entités actives: {context.active_entities}

        Reformule la question de manière complète et autonome,
        en intégrant le contexte nécessaire.
        """

        resolved = await self.llm.generate(prompt)

        return ResolvedQuery(
            original=query,
            resolved=resolved,
            context_used=context,
            confidence=self._calculate_confidence(analysis, context)
        )
```

### 6.4 Gestion de l'Ambiguïté

Quand le contexte est ambigu, le système demande une clarification :

```python
class ContextResolver:
    async def resolve(self, session_id: str, query: str) -> ResolvedQuery:
        # ... analyse et contexte ...

        if context.confidence < 0.7:
            # Contexte ambigu → proposer des options
            return ResolvedQuery(
                original=query,
                resolved=None,
                disambiguation_needed=True,
                suggestions=[
                    "Dans le contexte S/4HANA Cloud sécurité ?",
                    "Dans le contexte migration on-premise ?",
                    "Pour le client Acme Corp ?"
                ]
            )
```

---

## 7. Intelligent Summarizer

### 7.1 Objectif

Générer un **compte-rendu métier structuré**, pas une transcription. Le résumé doit être exploitable pour un décideur ou un consultant.

### 7.2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   INTELLIGENT SUMMARIZER                         │
│                                                                  │
│  Input: Session avec N messages + graphe exploré                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. EXTRACTION                                            │    │
│  │    - Topics principaux                                   │    │
│  │    - Points clés par topic                               │    │
│  │    - Actions identifiées                                 │    │
│  │    - Sources utilisées                                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 2. STRUCTURATION                                         │    │
│  │    - Regroupement thématique                             │    │
│  │    - Priorisation par importance                         │    │
│  │    - Identification des gaps                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 3. GÉNÉRATION LLM                                        │    │
│  │    - Rédaction fluide et professionnelle                 │    │
│  │    - Format adapté (business/technical)                  │    │
│  │    - Ton neutre et factuel                               │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  Output: Synthèse structurée + Actions + Sources                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 Prompt Template

```python
SUMMARY_PROMPT = """
Tu es un assistant qui génère des synthèses professionnelles de sessions de recherche documentaire.

CONTEXTE DE LA SESSION:
- Utilisateur: {user_name}
- Date: {session_date}
- Durée: {duration}
- Nombre de questions: {question_count}
- Concepts explorés: {concepts_explored}

CONVERSATION:
{conversation_transcript}

CONSIGNES:
1. Génère une synthèse MÉTIER, pas une transcription
2. Structure en sections claires:
   - CONTEXTE: Objectif de recherche identifié
   - POINTS CLÉS: 3-5 insights principaux, avec sources
   - ACTIONS: Actions concrètes identifiées (si mentionnées)
   - ZONES NON EXPLORÉES: Sujets pertinents non abordés
3. Cite les sources entre crochets [Source X]
4. Utilise un ton professionnel et factuel
5. Maximum 500 mots

FORMAT DE SORTIE:
{output_format}
"""
```

### 7.4 Implémentation

```python
# src/knowbase/memory/intelligent_summarizer.py

class IntelligentSummarizer:
    """Génère des résumés intelligents de sessions."""

    async def generate_summary(
        self,
        session_id: str,
        format: SummaryFormat = SummaryFormat.BUSINESS
    ) -> SessionSummary:
        """Générer un résumé intelligent."""

        # 1. Charger la session complète
        session = await self.session_manager.get_session(session_id)
        messages = await self.session_manager.get_messages(session_id)

        # 2. Extraire les données structurées
        extracted = await self._extract_session_data(session, messages)

        # 3. Générer le résumé via LLM
        summary_text = await self._generate_with_llm(
            session=session,
            extracted=extracted,
            format=format
        )

        # 4. Parser et structurer
        summary = self._parse_summary(summary_text, extracted)

        # 5. Sauvegarder
        await self._save_summary(session_id, summary)

        return summary

    async def _extract_session_data(
        self,
        session: Session,
        messages: List[Message]
    ) -> ExtractedData:
        """Extraire les données structurées de la session."""

        return ExtractedData(
            topics=self._identify_topics(messages),
            key_concepts=self._extract_key_concepts(messages),
            sources_used=self._collect_sources(messages),
            actions_mentioned=self._detect_actions(messages),
            questions_asked=[m.content for m in messages if m.role == "user"],
            graph_state=session.graph_state
        )

    def _detect_actions(self, messages: List[Message]) -> List[str]:
        """Détecter les actions mentionnées dans la conversation."""

        action_patterns = [
            r"il (faut|faudrait|faudra)",
            r"on (doit|devra|devrait)",
            r"à faire:",
            r"action(s)?:",
            r"recommand",
            r"prévoir de",
        ]

        # ... extraction via patterns et LLM
```

---

## 8. Export PDF

### 8.1 Template PDF

Le PDF généré suit une mise en page professionnelle :

```
┌─────────────────────────────────────────────────────────────────┐
│  [LOGO KnowWhere]                                               │
│                                                                  │
│  ════════════════════════════════════════════════════════════   │
│         SYNTHÈSE DE SESSION                                      │
│  ════════════════════════════════════════════════════════════   │
│                                                                  │
│  Date: 17 décembre 2025                                         │
│  Utilisateur: Jean Dupont                                       │
│  Durée: 45 minutes (14 questions)                               │
│                                                                  │
│  ────────────────────────────────────────────────────────────   │
│  TABLE DES MATIÈRES                                              │
│  ────────────────────────────────────────────────────────────   │
│  1. Contexte ................................................ 2  │
│  2. Points Clés ............................................. 3  │
│  3. Actions Identifiées ..................................... 5  │
│  4. Zones Non Explorées ..................................... 6  │
│  5. Sources ................................................. 7  │
│  Annexe: Graphe de Session .................................. 8  │
│                                                                  │
│  ────────────────────────────────────────────────────────────   │
│                                                                  │
│  1. CONTEXTE                                                     │
│                                                                  │
│  Objectif de recherche identifié:                               │
│  Migration sécurisée vers SAP S/4HANA Cloud                     │
│                                                                  │
│  Périmètre couvert:                                             │
│  • Authentification et identité (IAS, SAML)                     │
│  • Contrôle d'accès (RBAC, Authorization Objects)               │
│  • Connectivité hybride (Cloud Connector)                       │
│                                                                  │
│  ...                                                             │
│                                                                  │
│  ────────────────────────────────────────────────────────────   │
│                      Page 1 sur 8                                │
│           Généré par KnowWhere - Le Cortex Documentaire          │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Implémentation

```python
# src/knowbase/memory/pdf_exporter.py

class PDFExporter:
    """Génère des exports PDF professionnels."""

    def __init__(self):
        self.template_path = "templates/session_summary.html"

    async def export_session(
        self,
        session_id: str,
        include_graph: bool = True
    ) -> bytes:
        """Exporter une session en PDF."""

        # 1. Récupérer ou générer le résumé
        summary = await self.summarizer.get_or_generate(session_id)

        # 2. Préparer les données
        data = {
            "session": summary.session,
            "content": summary.content,
            "sources": summary.sources,
            "graph_image": None
        }

        # 3. Générer l'image du graphe si demandé
        if include_graph:
            data["graph_image"] = await self._render_graph_image(
                summary.session.graph_state
            )

        # 4. Rendre le HTML
        html = await self._render_template(data)

        # 5. Convertir en PDF
        pdf = await self._html_to_pdf(html)

        return pdf

    async def _render_graph_image(
        self,
        graph_state: dict
    ) -> str:
        """Rendre le graphe en image PNG base64."""

        # Utiliser matplotlib ou plotly pour générer l'image
        # Retourner en base64 pour inclusion dans HTML
        pass

    async def _html_to_pdf(self, html: str) -> bytes:
        """Convertir HTML en PDF avec WeasyPrint."""

        from weasyprint import HTML, CSS

        pdf = HTML(string=html).write_pdf(
            stylesheets=[CSS(filename='templates/pdf_styles.css')]
        )

        return pdf
```

---

## 9. Planning Détaillé

### 9.1 Vue d'Ensemble

```
Semaine 25 │████████████████████│ Schéma Neo4j + Session Manager
Semaine 26 │████████████████████│ Context Resolver + User Profile
Semaine 27 │████████████████████│ Intelligent Summarizer
Semaine 28 │████████████████████│ Export PDF + Intégration + Tests
```

### 9.2 Semaine 25 : Fondations (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J1 | Schéma Neo4j Memory | Contraintes + Index | 4h |
| J1 | Scripts migration | `setup_memory_schema.py` | 4h |
| J2 | SessionManager base | CRUD sessions | 6h |
| J2 | Tests SessionManager | pytest | 2h |
| J3 | Endpoints sessions API | `/api/memory/sessions/*` | 6h |
| J3 | Tests API | pytest + httpx | 2h |
| J4 | Message management | Add/list messages | 6h |
| J4 | Graph state persistence | JSON Neo4j | 2h |
| J5 | Intégration chat existant | Modifier chat endpoint | 4h |
| J5 | Tests intégration | End-to-end | 4h |

**Checkpoint Sem 25 :**
- ✅ Schéma Neo4j déployé
- ✅ Sessions créables/récupérables
- ✅ Messages persistés
- ✅ Living Graph state sauvegardé

### 9.3 Semaine 26 : Context & Profile (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J6 | Context model Neo4j | SessionContext node | 3h |
| J6 | ContextResolver base | Analyse syntaxique | 5h |
| J7 | Pattern matching | Détection références implicites | 6h |
| J7 | Tests patterns | Couverture patterns | 2h |
| J8 | Context enrichment | Récupération contexte session | 4h |
| J8 | LLM reformulation | Intégration Claude | 4h |
| J9 | UserProfile model | Neo4j + Pydantic | 4h |
| J9 | Preferences system | CRUD préférences | 4h |
| J10 | API context resolve | `/api/memory/context/resolve` | 4h |
| J10 | Tests Context Resolver | Cas nominaux + edge cases | 4h |

**Checkpoint Sem 26 :**
- ✅ Context Resolver fonctionnel
- ✅ Questions implicites résolues (>80%)
- ✅ User Profile persisté
- ✅ Préférences sauvegardées

### 9.4 Semaine 27 : Intelligent Summarizer (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J11 | Data extractor | Extract topics/concepts/sources | 6h |
| J11 | Action detector | Pattern + LLM extraction | 2h |
| J12 | Prompt engineering | Template summary optimisé | 4h |
| J12 | LLM integration | Generate summary | 4h |
| J13 | Output parser | Structure JSON du résumé | 4h |
| J13 | Quality checks | Validation output | 4h |
| J14 | API summary | `/api/memory/sessions/{id}/summary` | 4h |
| J14 | Caching summaries | Neo4j storage | 4h |
| J15 | Tests summarizer | Différents types sessions | 6h |
| J15 | Tuning prompts | Amélioration qualité | 2h |

**Checkpoint Sem 27 :**
- ✅ Résumés générés automatiquement
- ✅ Format business professionnel
- ✅ Actions extraites correctement
- ✅ Qualité résumés > 4/5

### 9.5 Semaine 28 : Export & Finition (5 jours)

| Jour | Tâche | Livrable | Effort |
|------|-------|----------|--------|
| J16 | HTML template | Template session summary | 4h |
| J16 | CSS styling | Styles PDF professionnels | 4h |
| J17 | WeasyPrint integration | HTML → PDF | 4h |
| J17 | Graph image render | matplotlib/plotly | 4h |
| J18 | API export | `/api/memory/sessions/{id}/export` | 3h |
| J18 | Download handling | Content-Disposition | 1h |
| J18 | History search | Full-text search Neo4j | 4h |
| J19 | Session history API | `/api/memory/user/history` | 4h |
| J19 | Related sessions | Similarité sessions | 4h |
| J20 | Tests E2E complets | Tous les flows | 4h |
| J20 | Documentation | README + docstrings | 4h |

**Checkpoint Sem 28 (FINAL) :**
- ✅ Export PDF fonctionnel
- ✅ Recherche historique opérationnelle
- ✅ Tous tests passent
- ✅ Documentation complète
- ✅ Prêt pour Phase 3.5 (Frontend)

---

## 10. KPIs de Succès

### 10.1 KPIs Techniques

| KPI | Target | Mesure |
|-----|--------|--------|
| **Temps création session** | < 100ms | P95 latency |
| **Temps résolution contexte** | < 500ms | P95 latency |
| **Temps génération résumé** | < 10s | P95 latency |
| **Temps export PDF** | < 5s | P95 latency |
| **Couverture tests** | > 80% | Jest/pytest coverage |

### 10.2 KPIs Fonctionnels

| KPI | Target | Mesure |
|-----|--------|--------|
| **Taux résolution implicite** | > 90% | Questions correctement résolues |
| **Pertinence contexte** | > 85% | Évaluation humaine |
| **Qualité résumés** | > 4/5 | User feedback |
| **Complétude actions** | > 80% | Actions détectées vs mentionnées |

### 10.3 KPIs Business

| KPI | Target | Mesure |
|-----|--------|--------|
| **Adoption sessions** | > 70% users | Analytics |
| **Reprise sessions** | > 30% | Sessions reprises vs nouvelles |
| **Exports PDF** | > 20% sessions | Download count |
| **Satisfaction globale** | > 4/5 | User survey |

---

## 11. Risques et Mitigation

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Schéma Neo4j complexe** | Medium | Medium | Commencer simple, itérer |
| **LLM hallucinations résumés** | Medium | High | Validation sources, prompts stricts |
| **Context resolution ambiguë** | High | Medium | Demander clarification user |
| **Performance avec historique large** | Medium | High | Index, pagination, archivage |
| **Qualité PDF rendering** | Low | Medium | Tests visuels, fallback HTML |
| **RGPD données conversationnelles** | Medium | High | Retention policy, anonymisation |

---

## 12. Considérations RGPD

### 12.1 Données Stockées

| Donnée | Classification | Rétention |
|--------|---------------|-----------|
| user_id | Identifiant | Durée compte |
| display_name | PII | Durée compte |
| Messages | Contenu | Configurable (défaut 1 an) |
| Résumés | Dérivé | Idem messages |
| Préférences | Non-PII | Durée compte |

### 12.2 Droits Utilisateurs

```python
# src/knowbase/memory/gdpr.py

class GDPRManager:
    """Gestion des droits RGPD."""

    async def export_user_data(self, user_id: str) -> bytes:
        """Droit à la portabilité - Export toutes données."""
        pass

    async def delete_user_data(self, user_id: str) -> None:
        """Droit à l'oubli - Suppression complète."""
        pass

    async def anonymize_session(self, session_id: str) -> None:
        """Anonymiser une session (garder stats, supprimer PII)."""
        pass
```

---

## 13. Prochaines Étapes

1. **Validation de ce document** avec l'équipe
2. **Setup Neo4j schema** - Script de migration
3. **Développement Session Manager** - Core functionality
4. **Phase 3.5 Frontend** - Intégration UI après completion

---

**Version:** 1.1
**Auteur:** Claude Code
**Date:** 2025-12-17
**Dernière MAJ:** 2025-12-19
**Statut:** 🟢 IN PROGRESS

---

## 14. Tracking Implémentation

### Vue d'Ensemble Progress

```
Phase 2.5 : Memory Layer
════════════════════════════════════════════
Progress Global : [████████████████████] 100%

Étapes :
├─ 🟢 Étape 1 : Session Context dans Search    : ✅ COMPLÉTÉ (100%)
├─ 🟢 Étape 2 : Session Entity Resolver        : ✅ COMPLÉTÉ (100%)
├─ 🟢 Étape 3 : Citation Sources Fix           : ✅ COMPLÉTÉ (100%)
├─ 🟢 Étape 4 : Session Manager complet        : ✅ COMPLÉTÉ (100%) - EXISTANT
├─ 🟢 Étape 5 : Context Resolver               : ✅ COMPLÉTÉ (100%) - EXISTANT
├─ 🟢 Étape 6 : Intelligent Summarizer         : ✅ COMPLÉTÉ (100%)
├─ 🟢 Étape 6b: UI Fixes (header/modal)        : ✅ COMPLÉTÉ (100%)
└─ ⏸️ Étape 7 : Export PDF                     : ⏸️ OPTIONNEL (future)
```

### 🟢 Étape 1 : Session Context dans Search (COMPLÉTÉ - 2025-12-18)

**Objectif :** Injecter le contexte de conversation dans la recherche et synthèse.

**Fichiers créés/modifiés :**
- `src/knowbase/api/services/search.py` : Ajout récupération session context
- `src/knowbase/api/services/synthesis.py` : Prompt enrichi avec contexte session
- `frontend/src/lib/api.ts` : Paramètre `session_id` dans chat.send()

**Fonctionnalités :**
- ✅ Récupération des 5 derniers messages de session
- ✅ Enrichissement de la requête vectorielle avec contexte thématique
- ✅ Passage du contexte au prompt de synthèse LLM
- ✅ Compréhension des références implicites ("cela", "cette personne", etc.)

### 🟢 Étape 2 : Session Entity Resolver (COMPLÉTÉ - 2025-12-19)

**Objectif :** Utiliser le Knowledge Graph pour les questions de suivi sur des entités mentionnées.

**Fichier créé :**
- `src/knowbase/api/services/session_entity_resolver.py` (359 lignes)

**Fonctionnalités :**
- ✅ Extraction d'entités des messages de session (noms propres, termes techniques)
- ✅ Recherche fuzzy des concepts KG correspondants (Cypher)
- ✅ Récupération des chunks liés aux concepts identifiés
- ✅ Intégration dans le flux de recherche (ajout chunks KG aux résultats)

**Architecture :**
```
Question suivi: "Sur quelle étude a travaillé Richard Davies?"
       ↓
SessionEntityResolver
       ↓
1. Extraction entités session → ["Richard Davies", "COVID", ...]
2. Match fuzzy Neo4j → CanonicalConcept(canonical_id=xxx)
3. Récupération chunks Qdrant via concept → [chunk1, chunk2, ...]
4. Injection dans résultats recherche
```

### 🟢 Étape 3 : Citation Sources Fix (COMPLÉTÉ - 2025-12-19)

**Objectif :** Corriger le problème "Document inconnu" dans les citations.

**Cause racine identifiée :**
- `build_response_payload()` cherchait `source_file_url` (n'existe pas)
- Les chunks OSMOSE utilisent `document_name` à la place

**Fix appliqué :**
- `src/knowbase/api/services/search.py:34-38` : Ajout fallback vers `document_name`

```python
source_file_url = (
    document.get("source_file_url") or
    payload.get("source_file_url") or
    payload.get("document_name", "")  # Nouveau fallback
)
```

**Note :** Les liens de téléchargement des sources ne sont pas encore fonctionnels.
Ceci sera traité dans une phase ultérieure (connecteurs sources).

### 🟢 Étape 4 : Session Manager complet (EXISTANT - Découvert 2025-12-19)

**Objectif :** Gestion CRUD complète des sessions de conversation.

**DÉCOUVERTE :** Le Session Manager était **déjà implémenté** avec PostgreSQL (pas Neo4j comme prévu initialement dans la spec).

**Fichiers existants :**
- `src/knowbase/memory/session_manager.py` (730 lignes) - SessionManager complet
- `src/knowbase/api/routers/sessions.py` (579 lignes) - REST API complète
- `src/knowbase/api/schemas/sessions.py` (166 lignes) - Pydantic schemas
- `src/knowbase/db/models.py` - SQLAlchemy models (Session, SessionMessage)

**Fonctionnalités implémentées :**
- ✅ Session CRUD (create, get, list, archive, delete, update_title)
- ✅ Messages management (add, get, get_recent)
- ✅ LangChain Memory integration (ConversationSummaryBufferMemory)
- ✅ Context metadata management
- ✅ Feedback system (thumbs up/down)
- ✅ Auto-title generation via LLM
- ✅ Multi-tenancy support

**Intégration Frontend :**
- `frontend/src/components/chat/SessionSelector.tsx` - UI session selector
- `frontend/src/app/chat/page.tsx` - Full chat page with sessions
- `frontend/src/lib/api.ts` - API client avec endpoints sessions

### 🟢 Étape 5 : Context Resolver (EXISTANT - Découvert 2025-12-19)

**Objectif :** Résoudre les références implicites dans les questions de suivi.

**DÉCOUVERTE :** Le Context Resolver était **déjà implémenté**.

**Fichier existant :**
- `src/knowbase/memory/context_resolver.py` (476 lignes) - ContextResolver complet

**Fonctionnalités implémentées :**
- ✅ Résolution de pronoms (il, elle, ils, elles, ça, cela, ce document...)
- ✅ Résolution de références documents (le premier document, le PDF mentionné...)
- ✅ Résolution de références entités (cette personne, l'auteur, le responsable...)
- ✅ Résolution d'ordinaux (le premier, le deuxième, le dernier...)
- ✅ Patterns regex configurables
- ✅ Gestion du contexte avec entités/documents récents

**Note :** Ce Context Resolver utilise des patterns regex plutôt qu'un LLM.
Une version LLM-powered pourrait être ajoutée ultérieurement si les patterns
s'avèrent insuffisants.

### 🟢 Étape 6 : Intelligent Summarizer (COMPLÉTÉ - 2025-12-19)

**Objectif :** Générer des comptes-rendus métier structurés des sessions.

**Fichiers créés :**
- `src/knowbase/memory/intelligent_summarizer.py` (~400 lignes)
- `frontend/src/components/chat/SessionSummary.tsx` (~280 lignes)

**Fichiers modifiés :**
- `src/knowbase/memory/__init__.py` - Export du summarizer
- `src/knowbase/api/schemas/sessions.py` - Schemas Summary
- `src/knowbase/api/routers/sessions.py` - Endpoints summary
- `frontend/src/lib/api.ts` - API client summary
- `frontend/src/app/chat/page.tsx` - Intégration bouton résumé

**Fonctionnalités implémentées :**
- ✅ 3 formats de résumé: Business, Technical, Executive
- ✅ Extraction automatique des topics et concepts
- ✅ Détection des actions via patterns regex
- ✅ Points clés avec sources documentaires
- ✅ Zones non explorées suggérées
- ✅ API POST/GET `/sessions/{id}/summary`
- ✅ Composant frontend avec modal et sélecteur de format

**Architecture :**
```
IntelligentSummarizer
├── _extract_session_data()    → Topics, concepts, sources, actions
├── _format_conversation_transcript()  → Formatage pour LLM
├── _generate_with_llm()       → Appel LLM avec prompt adapté
└── _parse_summary()           → Structure SessionSummary
```

### 🟢 Étape 6b : UI Fixes (COMPLÉTÉ - 2025-12-19)

**Objectif :** Corriger les problèmes d'UX du chat et du résumé.

**Fichiers modifiés :**
- `frontend/src/components/layout/MainLayout.tsx` - Fix header sticky
- `frontend/src/components/chat/SessionSummary.tsx` - Fix modal comportement
- `frontend/src/app/chat/page.tsx` - Ajustements Flex layout
- `src/knowbase/api/openapi.json` → `openapi.json.bak` - Suppression fichier statique

**Corrections appliquées :**
- ✅ **Header sticky** : Le conteneur principal utilise maintenant `h="calc(100vh - 64px)"` avec `overflow="hidden"` pour créer un contexte de scroll. Le header du chat reste toujours visible.
- ✅ **Modal summary** : L'ouverture du modal n'exécute plus automatiquement la génération. L'utilisateur peut d'abord choisir le format (Business/Technique/Executive) via des cartes cliquables, puis cliquer "Générer".
- ✅ **OpenAPI dynamique** : Suppression du fichier `openapi.json` statique obsolète qui masquait les nouveaux endpoints (dont `/sessions/{id}/summary`).

### ⏸️ Étapes Suivantes (Optionnel)

| Étape | Description | Effort | Priorité |
|-------|-------------|--------|----------|
| **7** | Export PDF | 2 jours | LOW |

### Journal des Sessions

#### 2025-12-19 : Intelligent Summarizer + UI Fixes
- ✅ Création `intelligent_summarizer.py` avec 3 formats
- ✅ Endpoints API `/sessions/{id}/summary` (GET/POST)
- ✅ Composant frontend `SessionSummary.tsx`
- ✅ Intégration dans la page chat
- ✅ Fix header sticky: `MainLayout.tsx` avec `h="calc(100vh - 64px)"` et `overflow="hidden"`
- ✅ Fix modal summary: ouverture sans génération auto, sélection format d'abord
- ✅ Suppression `openapi.json` statique obsolète pour permettre génération dynamique FastAPI

#### 2025-12-19 : Session Entity Resolver + Citation Fix
- ✅ Création `session_entity_resolver.py`
- ✅ Intégration dans `search.py`
- ✅ Diagnostic et fix "Document inconnu" (fallback `document_name`)
- ⏳ Liens sources à traiter ultérieurement

#### 2025-12-19 : Session Manager EXISTANT découvert
- ✅ `session_manager.py` (730 lignes) - PostgreSQL
- ✅ `context_resolver.py` (476 lignes) - Patterns regex
- ✅ API complète `/api/sessions/*`
- ✅ Frontend `SessionSelector.tsx` + chat integration

#### 2025-12-18 : Session Context Integration
- ✅ Modification `search.py` pour contexte session
- ✅ Modification `synthesis.py` pour prompt enrichi
- ✅ API `session_id` paramètre ajouté

---

> **"Une mémoire qui ne repart jamais de zéro, pour une intelligence qui s'enrichit à chaque échange."**
