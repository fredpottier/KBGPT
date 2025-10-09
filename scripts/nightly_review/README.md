# 🌙 Système de Revue Nocturne

Système complet d'analyse automatique du projet SAP KB pour assurer la qualité du code, la couverture des tests, et la santé de l'infrastructure.

## 📋 Fonctionnalités

### 1. **Code Reviewer** 📋
- Détection de code mort (dead code)
- Analyse de qualité (ruff, mypy)
- Complexité cyclomatique
- Imports inutilisés
- Bonnes pratiques

### 2. **Test Analyzer** 🧪
- Exécution des tests avec couverture
- Détection de fonctions sans tests
- Analyse de la qualité des tests
- Rapport de couverture détaillé

### 3. **Frontend Validator** 🌐
- Test de tous les endpoints API
- Vérification de la santé des services
- Validation des routes frontend
- Temps de réponse

### 4. **DB Safety** 💾
- Snapshots automatiques (SQLite, Redis, Qdrant)
- Vérification d'intégrité
- Mode READ-ONLY pour tests
- Restauration automatique si nécessaire

### 5. **Report Generator** 📊
- Rapport HTML interactif
- Export JSON pour intégration
- Statistiques et graphiques
- Historique des revues

## 🚀 Utilisation

### Windows

Double-cliquez sur le fichier ou exécutez dans un terminal :

```cmd
scripts\run_nightly_review.cmd
```

Avec options :

```cmd
scripts\run_nightly_review.cmd --skip-tests
scripts\run_nightly_review.cmd --skip-frontend
scripts\run_nightly_review.cmd --no-browser
```

### Linux / macOS

```bash
chmod +x scripts/run_nightly_review.sh
./scripts/run_nightly_review.sh
```

Avec options :

```bash
./scripts/run_nightly_review.sh --skip-tests
./scripts/run_nightly_review.sh --skip-frontend
./scripts/run_nightly_review.sh --no-browser
```

### Python Direct

```bash
python scripts/nightly_review.py
```

## 🎯 Scénarios d'Usage

### 1. **Avant de se coucher** 🌙
Lancez la revue complète pour avoir un rapport complet au réveil :

```cmd
scripts\run_nightly_review.cmd
```

Durée estimée : **5-15 minutes** selon la taille du projet

### 2. **Revue rapide sans tests** ⚡
Si vous voulez juste vérifier la qualité du code rapidement :

```cmd
scripts\run_nightly_review.cmd --skip-tests --skip-frontend
```

Durée estimée : **1-3 minutes**

### 3. **Revue complète avec snapshot** 💾
Pour une revue avec sécurité maximale :

```cmd
scripts\run_nightly_review.cmd
```

Les snapshots sont automatiquement créés avant les tests.

### 4. **Revue sans ouvrir le navigateur** 📄
Si vous voulez juste le rapport dans le dossier :

```cmd
scripts\run_nightly_review.cmd --no-browser
```

Le rapport sera dans `reports/nightly/`

## 📊 Rapports Générés

### Rapport HTML
- **Localisation** : `reports/nightly/nightly_review_YYYYMMDD_HHMMSS.html`
- **Format** : Page web interactive avec graphiques
- **Ouverture** : Automatique dans le navigateur par défaut

### Rapport JSON
- **Localisation** : `reports/nightly/nightly_review_YYYYMMDD_HHMMSS.json`
- **Format** : Données structurées pour intégration
- **Usage** : Scripts automatiques, dashboards, CI/CD

### Snapshots DB
- **Localisation** : `backups/nightly_review/`
- **Contenu** :
  - `entity_types_registry_YYYYMMDD_HHMMSS.db` (SQLite)
  - `redis_dump_YYYYMMDD_HHMMSS.rdb` (Redis)
  - Snapshots Qdrant (via API)

## 🔧 Options Disponibles

| Option | Description | Effet |
|--------|-------------|-------|
| `--skip-tests` | Skip l'exécution des tests | Plus rapide, pas de couverture |
| `--skip-frontend` | Skip la validation API/Frontend | Pas de test des endpoints |
| `--skip-db-safety` | Skip les snapshots DB | Pas de sauvegarde |
| `--no-browser` | Ne pas ouvrir le rapport | Rapport généré mais pas ouvert |
| `--help` | Afficher l'aide | Liste toutes les options |

## 📂 Structure des Modules

```
scripts/nightly_review/
├── modules/
│   ├── __init__.py
│   ├── code_reviewer.py       # Analyse qualité code
│   ├── test_analyzer.py       # Analyse tests & couverture
│   ├── frontend_validator.py  # Validation API/Frontend
│   ├── db_safety.py           # Snapshots & sécurité
│   └── report_generator.py    # Génération rapports
└── README.md                  # Cette documentation
```

## 🎨 Exemple de Rapport

Le rapport HTML contient :

### 1. Résumé Exécutif
- 📋 **Qualité du Code** : Nombre de problèmes
- 🧪 **Couverture Tests** : Pourcentage couvert
- 🌐 **Santé API** : Endpoints fonctionnels
- 💾 **Snapshots** : Bases sauvegardées

### 2. Sections Détaillées

#### Code Review
- Liste du code mort
- Problèmes de qualité (ruff/mypy)
- Fonctions trop complexes
- Imports inutilisés

#### Test Analysis
- Résultats d'exécution (succès/échecs)
- Barre de progression couverture
- Fonctions sans tests
- Qualité des tests existants

#### Frontend Validation
- Santé des services (Neo4j, Qdrant, Redis, etc.)
- Tableau des endpoints API
- Codes de retour HTTP
- Temps de réponse

#### DB Safety
- Liste des snapshots créés
- Tailles des sauvegardes
- Vérifications d'intégrité

## ⚡ Performances

| Analyse | Durée Estimée | Description |
|---------|---------------|-------------|
| Code Review | 30s - 1min | Ruff + Mypy + AST analysis |
| Test Analysis | 2-5min | Pytest + Coverage |
| Frontend Validation | 30s - 1min | API calls + health checks |
| DB Safety | 10-30s | Snapshots création |
| **Total Complet** | **5-15min** | Selon taille projet |

### Optimisations

- **`--skip-tests`** : Divise le temps par 3-4
- **`--skip-frontend`** : Économise 1-2 minutes
- **`--skip-db-safety`** : Économise 30 secondes

## 🔒 Sécurité

### Mode READ-ONLY
- Tous les tests s'exécutent en mode lecture seule
- Aucune modification de données de production
- Snapshots créés AVANT toute analyse

### Snapshots Automatiques
- SQLite : Copie complète du fichier `.db`
- Redis : `SAVE` + copie `dump.rdb`
- Qdrant : Snapshot via API REST

### Vérification Intégrité
- `PRAGMA integrity_check` pour SQLite
- Comparaison tailles avant/après
- Alerte si différence > 10MB

## 📅 Planification Manuelle

### Workflow Recommandé

**Avant de se coucher** :
```cmd
scripts\run_nightly_review.cmd
```

**Au réveil** :
1. Ouvrir `reports/nightly/` (dernier fichier HTML)
2. Consulter les résultats
3. Prioriser les corrections selon les badges (erreur > warning > info)

### Fréquence Suggérée

- **Tous les soirs** : Si développement actif
- **Hebdomadaire** : Si maintenance
- **Avant chaque release** : Obligatoire

## 🐛 Troubleshooting

### Erreur "Python not found"
**Solution** : Installer Python 3.8+ et ajouter au PATH

### Erreur "Docker services not running"
**Solution** : Démarrer les services Docker :
```bash
docker-compose up -d
```

### Rapport vide ou incomplet
**Solution** : Vérifier que tous les services sont démarrés :
```bash
docker-compose ps
```

### Timeout sur les tests
**Solution** : Utiliser `--skip-tests` pour une revue rapide

## 📚 Ressources

- **Documentation Claude Code** : https://docs.claude.com/claude-code
- **Pytest Documentation** : https://docs.pytest.org
- **Ruff Documentation** : https://docs.astral.sh/ruff

## 🎯 Roadmap Future

- [ ] Intégration GitHub Actions
- [ ] Notifications Slack/Email
- [ ] Dashboard temps réel
- [ ] Comparaison historique
- [ ] Suggestions automatiques de fix
- [ ] Export PDF des rapports

## 📝 Notes

- Le système est **totalement autonome** après lancement
- Aucune intervention requise pendant l'exécution
- Les rapports sont **persistants** et consultables à tout moment
- Les snapshots restent dans `backups/` pour référence

---

**Dernière mise à jour** : 2025-10-08
**Version** : 1.0.0
**Auteur** : Équipe SAP KB
