# Documentation Guide

Bienvenue dans le dossier `/documentation`. Il complète le dossier historique `/doc` en offrant une vue exhaustive et structurée de Knowbase pour les lecteurs humains et les IA génératives.

## Structure

- `OVERVIEW.md` – architecture globale de la plateforme, description des principaux composants et cartographie des dossiers.
- `BACKEND_APIS.md` – catalogue détaillé de toutes les routes FastAPI, avec schémas de requêtes/réponses, services sous-jacents et dépendances externes.
- `EXECUTION_FLOW.md` – scénarios d’exécution majeurs illustrés par des diagrammes Mermaid (ingestion, recherche, Graphiti, gouvernance des facts, etc.).
- `MODULES.md` – tableau de référence listant chaque module Python avec son rôle, ses fonctions clés, ses dépendances et ses effets de bord.
- `registry.json` – registre exploitable par une IA décrivant inputs/outputs/dépendances de chaque fonction ou endpoint exposé.
- `AI_GUIDE.md` – conventions et bonnes pratiques pour les IA génératives amenées à étendre le projet.

## Comment utiliser cette documentation

1. **Prise en main rapide** : commencez par `OVERVIEW.md` pour comprendre l’architecture macro et identifier les sous-systèmes pertinents.
2. **Implémentation ou debug backend** : utilisez `BACKEND_APIS.md` et `EXECUTION_FLOW.md` pour suivre la circulation des données depuis l’API jusqu’aux pipelines d’ingestion ou au graph de connaissances.
3. **Analyse détaillée** : consultez `MODULES.md` pour localiser les fonctions/classes nécessaires et repérer les effets de bord (accès disque, Qdrant, Redis, etc.).
4. **Automatisation/IA** : pointez votre agent sur `registry.json` et `AI_GUIDE.md` pour récupérer rapidement les signatures, conventions et dépendances critiques.

Chaque fichier est maintenu en Markdown/JSON standard pour favoriser l’ingestion automatique, l’indexation vectorielle ou la génération de documentation dynamique.
