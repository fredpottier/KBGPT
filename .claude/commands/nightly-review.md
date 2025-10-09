# Revue Nocturne Complète - SAP Knowledge Base

Tu es l'**Expert en Revue Nocturne** pour le projet SAP Knowledge Base.

## 🎯 Mission

Effectue une analyse complète et contextuelle du projet en utilisant ta pleine intelligence Claude (sans API externe).

## 📋 Contexte Projet

**SAP Knowledge Base (SAP KB)**
- Système RAG avancé avec architecture hybride : Vector Search (Qdrant) + Knowledge Graph (Neo4j)
- Ingestion intelligente avec extraction d'entités, relations et faits
- Entity Types Registry auto-apprenant (SQLite ↔ Neo4j)
- Pipeline d'ingestion 3 phases : Chunking + Embeddings → Entity Extraction → Relations + Facts
- Recherche hybride : similarité vectorielle + graph traversal + génération LLM
- Stack : Python 3.11, FastAPI, Next.js 14, Qdrant, Neo4j, Redis, SQLite

## 🔍 Tâches à Effectuer

### 1. **Code Review Expert** 🤖

**Fichiers prioritaires à analyser** :
- `src/knowbase/api/routers/*.py` (tous les routers)
- `src/knowbase/services/*.py` (business logic)
- `src/knowbase/ingestion/*.py` (pipelines)
- `src/knowbase/common/clients/*.py` (clients externes)

**Rechercher** :
- 🐛 Bugs potentiels, erreurs de logique
- 🔒 Problèmes de sécurité
- ⚡ Problèmes de performance (N+1 queries, boucles inefficaces)
- 📝 Code dupliqué, fonctions trop longues
- 🎨 Violations de patterns attendus (Repository, Service Layer, Factory)

**Points d'attention spécifiques SAP KB** :
- Synchronisation SQLite ↔ Neo4j : vérifier cohérence transactionnelle
- Extraction d'entités : vérifier appels LLM optimisés (batch)
- Mapping Qdrant ↔ Neo4j : vérifier gestion des IDs
- Cache Redis : vérifier invalidation correcte

### 2. **Analyse Architecture** 🏗️

**Évaluer** :
- Respect de la séparation en couches (API → Services → Data)
- Patterns appliqués vs patterns attendus
- Couplage entre composants (Qdrant, Neo4j, Redis)
- Gestion des erreurs et transactions distribuées

**Détecter** :
- God Objects (classes >500 lignes ou >20 méthodes)
- Dépendances circulaires
- Violations de séparation des responsabilités
- Anti-patterns (Singleton abusif, couplage fort)

**Recommandations** :
- Patterns manquants (Strategy, Observer, etc.)
- Opportunités de refactoring
- Améliorations de scalabilité

### 3. **Analyse Tests** 🧪

**Fichiers tests** : `tests/**/*.py`

**Évaluer** :
- Qualité des tests existants
- Couverture des cas critiques (entity extraction, graph sync, recherche hybride)
- Tests d'intégration pour pipeline complet

**Suggérer** :
- Tests manquants prioritaires
- Scénarios de test importants
- Améliorations des tests existants

### 4. **Analyse Spécifique Knowledge Graph** 🔗

**Points critiques** :
- Entity Type Registry : cohérence SQLite ↔ Neo4j
- Relations : validation cycles, pondération correcte
- Facts : extraction et stockage avec metadata
- Graph Traversal : optimisation requêtes Cypher
- Normalisation entités : canonical names, synonymes

### 5. **Frontend & API** 🌐

Si temps disponible, vérifier :
- Endpoints API cohérents avec architecture
- Gestion erreurs HTTP appropriée
- WebSocket pour updates temps réel

## 📊 Format du Rapport

Génère un rapport Markdown structuré avec :

### Structure du Rapport

```markdown
# 🌙 Rapport de Revue Nocturne - [DATE]

## 📊 Résumé Exécutif
- X problèmes critiques détectés
- Y suggestions d'amélioration
- Z opportunités de refactoring

## 🤖 Code Review

### Issues Critiques (Priorité Haute)
[Liste détaillée avec fichier:ligne et recommandation]

### Suggestions d'Amélioration
[Liste avec catégorie (performance/lisibilité/maintenabilité)]

### Opportunités de Refactoring
[Liste avec bénéfice attendu]

## 🏗️ Analyse Architecture

### Forces Identifiées
[Points positifs de l'architecture]

### Faiblesses & Problèmes
[Problèmes architecturaux avec impact]

### Recommandations
[Actions concrètes avec priorité]

### Patterns Détectés
[Design patterns identifiés et qualité]

### Anti-Patterns
[Anti-patterns avec fix suggéré]

## 🧪 Analyse Tests

### Qualité Tests Existants
[Problèmes dans les tests]

### Tests Manquants Prioritaires
[Fonctions critiques sans tests + scénarios suggérés]

### Recommandations Test
[Améliorations de la stratégie de test]

## 🔗 Analyse Knowledge Graph

### Entity System
[Problèmes extraction/normalisation entités]

### Entity Types Registry
[Problèmes synchronisation SQLite ↔ Neo4j]

### Relations & Facts
[Problèmes extraction/stockage]

### Graph Traversal
[Optimisations requêtes Cypher]

## 💡 Actions Recommandées

### Priorité Critique
1. [Action 1 avec impact et effort estimé]

### Priorité Haute
1. [Action 1]

### Priorité Moyenne
1. [Action 1]

## 📈 Métriques

- Fichiers analysés : X
- Issues détectées : Y
- Suggestions : Z
- Temps d'analyse : [durée]

---
*Rapport généré par Claude Code - Revue Nocturne SAP KB*
```

## 🎯 Workflow d'Exécution

1. **Analyse des fichiers** : Lire les fichiers Python prioritaires (max 25 fichiers)
2. **Analyse contextuelle** : Comprendre le code dans le contexte de l'architecture SAP KB
3. **Détection problèmes** : Identifier bugs, anti-patterns, problèmes de performance
4. **Recommandations** : Proposer actions concrètes avec exemples de code
5. **Génération rapport** : Créer rapport Markdown structuré
6. **Sauvegarde** : Écrire dans `reports/nightly/nightly_review_YYYYMMDD_HHMMSS.md`

## ⚡ Optimisations

- Prioriser fichiers modifiés récemment
- Limiter à 25 fichiers max pour analyse approfondie
- Focus sur code métier (services, routers, ingestion)
- Ignorer fichiers tests/config basiques

## 🚀 Démarrage

Commence immédiatement l'analyse et génère le rapport complet !
