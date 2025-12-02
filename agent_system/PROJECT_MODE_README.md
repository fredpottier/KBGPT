# 🚀 Mode Projet Complet - KnowWhere Agent System

Le système d'agents supporte maintenant l'**exécution automatique de projets complets** depuis un document de spécification.

## 📋 Vue d'Ensemble

### Mode "Tâche Unique" (Existant)
```bash
# Execute UNE seule tâche
docker-compose -f docker-compose.agents.yml exec agent-orchestrator \
  python scripts/run_orchestrator.py \
  --task "Create a calculator function" \
  --priority medium
```

### Mode "Projet Complet" (NOUVEAU) ⭐
```bash
# Execute TOUT UN PROJET depuis un document
docker-compose -f docker-compose.agents.yml exec agent-orchestrator \
  python scripts/run_project.py \
  --document "specs/my_project.md" \
  --project-id "project_001"
```

## 🎯 Fonctionnalités

### ✅ Parse Automatique
- Analyse un document Markdown
- Extrait toutes les tâches
- Identifie les dépendances
- Détermine l'ordre d'exécution

### ✅ Exécution Complète
- Crée une branche Git dédiée
- Exécute chaque tâche dans l'ordre
- Gère les dépendances entre tâches
- Mode **full automatique** (pas de confirmation utilisateur)

### ✅ Checkpoint & Resume
- Sauvegarde des checkpoints après chaque tâche
- Reprendre un projet interrompu
- État persistant dans `data/projects/<project-id>/`

### ✅ Rollback Automatique
- Si une tâche échoue → abandon du projet
- Suppression automatique de la branche Git
- Retour sur la branche de base (main)

## 📝 Format du Document Projet

Votre document doit être en **Markdown** avec cette structure :

```markdown
# Project: Titre du Projet

## Overview
Description générale du projet en quelques phrases.

## Features to Implement

### Feature 1: Titre de la Feature
Description détaillée de ce qui doit être fait.

**Requirements**:
- Requirement 1
- Requirement 2

**Priority**: high

**Dependencies**: (optionnel)

### Feature 2: Autre Feature
...

## Global Requirements
- Requirement qui s'applique à tout le projet
- Autre requirement global
```

### Exemple Complet

Voir `specs/todo_api_example.md` pour un exemple complet.

## 🚀 Utilisation

### 1. Créer Votre Document Spec

```bash
# Créer un fichier markdown
vi specs/my_project.md
```

### 2. Exécuter le Projet

```bash
docker-compose -f docker-compose.agents.yml exec agent-orchestrator \
  python scripts/run_project.py \
  --document "specs/my_project.md" \
  --project-id "my_project_v1" \
  --base-branch "main"
```

### 3. Ce qui se Passe

1. **Parsing** : DocumentParserAgent analyse le document
2. **Planification** : Extraction de toutes les tâches + dépendances
3. **Branche Git** : Création de `project/my_project_v1`
4. **Exécution** : Pour chaque tâche :
   - Planning Agent décompose
   - Dev Agent implémente
   - Control Agent valide
   - Checkpoint sauvegardé
5. **Rapport** : Génération du rapport final

### 4. Consulter les Résultats

```bash
# Rapport YAML
cat data/projects/my_project_v1/project_report.yaml

# Rapport Markdown (plus lisible)
cat data/projects/my_project_v1/project_report.md

# Plan généré
cat data/projects/my_project_v1/project_plan.yaml

# Résumé du projet
cat data/projects/my_project_v1/project_summary.md
```

## 🔄 Reprendre un Projet Interrompu

Si l'exécution est interrompue (Ctrl+C, erreur réseau, etc.) :

```bash
docker-compose -f docker-compose.agents.yml exec agent-orchestrator \
  python scripts/run_project.py \
  --document "specs/my_project.md" \
  --project-id "my_project_v1" \
  --resume
```

Le système reprendra **exactement où il s'était arrêté**.

## ⚙️ Options Avancées

### Spécifier un Répertoire de Sortie

```bash
python scripts/run_project.py \
  --document "specs/project.md" \
  --project-id "proj_001" \
  --output-dir "/custom/path/output"
```

### Branche de Base Custom

```bash
python scripts/run_project.py \
  --document "specs/project.md" \
  --project-id "proj_001" \
  --base-branch "develop"
```

### Désactiver LangSmith Tracing

```bash
python scripts/run_project.py \
  --document "specs/project.md" \
  --project-id "proj_001" \
  --no-langsmith
```

## 📊 Structure des Outputs

```
data/projects/<project-id>/
├── project_plan.yaml           # Plan complet du projet
├── project_summary.md          # Résumé lisible
├── project_report.yaml         # Rapport final (YAML)
├── project_report.md           # Rapport final (Markdown)
└── checkpoint.yaml             # Checkpoint pour resume
```

## 🎬 Exemple Complet

### 1. Tester avec l'Exemple Fourni

```bash
# Lancer l'exemple Todo API
docker-compose -f docker-compose.agents.yml exec agent-orchestrator \
  python scripts/run_project.py \
  --document "specs/todo_api_example.md" \
  --project-id "todo_api_v1"
```

### 2. Observer le Déroulement

```
📋 Parsing document: specs/todo_api_example.md
✅ Plan sauvegardé
✅ Résumé généré
🌿 Création branche Git: project/todo_api_v1

🚀 Exécution de 5 tâches...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 Tâche 1/5: Todo Data Model
   ID: task_1
   Priorité: high
   ✅ Complete en 45.2s

📌 Tâche 2/5: In-Memory Storage
   ID: task_2
   Priorité: high
   ✅ Complete en 52.1s

[...]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Toutes les tâches complétées avec succès!

📊 RAPPORT FINAL
================================================================================
Project ID: todo_api_v1
Titre: Todo List API
Status: COMPLETED

Statistiques:
  - Total tâches: 5
  - Complétées: 5
  - Échouées: 0

Durée totale: 268.5s
Branche Git: project/todo_api_v1

✅ PROJET COMPLETE AVEC SUCCES!

Pour merge: git checkout main && git merge project/todo_api_v1
```

## 🔧 Gestion des Échecs

Si une tâche échoue :

1. **Arrêt immédiat** : Le projet s'arrête
2. **Rollback Git** : La branche `project/<id>` est supprimée
3. **Rapport d'échec** : Le rapport indique quelle tâche a échoué
4. **Logs détaillés** : `project_report.yaml` contient tous les logs

### Exemple d'Échec

```
📌 Tâche 3/5: Create Todo Endpoint
   ID: task_3
   Priorité: medium
   ❌ Échec: Validation failed for task task_3

❌ Echec du projet: Task task_3 failed: Validation failed
🔄 Rollback de la branche Git...
✅ Branche project/todo_api_v1 supprimée

❌ PROJET ECHOUE - ROLLBACK EFFECTUE
```

## 💡 Bonnes Pratiques

### 1. Nommer les Projets
```
# Bon
--project-id "auth_system_v2"

# Éviter
--project-id "test"
```

### 2. Spécifier les Dépendances

Dans votre document :
```markdown
### Feature 3: API Endpoint
**Dependencies**: task_1, task_2
```

### 3. Utiliser les Priorités

```markdown
**Priority**: critical  # Blocage complet
**Priority**: high      # Important
**Priority**: medium    # Normal (défaut)
**Priority**: low       # Nice-to-have
```

### 4. Requirements Clairs

```markdown
**Requirements**:
- Use FastAPI framework
- Add type hints to all functions
- Write unit tests with pytest
- Minimum 80% code coverage
```

## 🆚 Mode Projet vs Mode Tâche

| Aspect | Mode Tâche | Mode Projet |
|--------|------------|-------------|
| Input | Une description texte | Document Markdown |
| Tâches | 1 tâche | N tâches |
| Git | Pas de branche auto | Branche dédiée |
| Rollback | Manuel | Automatique |
| Checkpoint | Non | Oui |
| Resume | Non | Oui |

## 🎓 Next Steps

1. **Créer votre premier projet** avec 3-5 tâches simples
2. **Tester la reprise** : Interrompre puis `--resume`
3. **Observer les rapports** générés
4. **Merger la branche** si succès : `git merge project/<id>`

---

**Le mode projet transforme le système d'agents en véritable automation de développement ! 🚀**
