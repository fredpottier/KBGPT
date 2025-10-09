# 🌙 Quick Start - Revue Nocturne avec Claude

Guide rapide pour lancer votre première revue nocturne intelligente avec Claude avant de vous coucher.

## ⚡ Nouveauté : Analyse Intelligente avec Claude

La revue nocturne utilise maintenant **l'API Claude (Anthropic)** pour des analyses contextuelles profondes :
- 🤖 **Claude Code Reviewer** : Détection intelligente de bugs et suggestions d'amélioration
- 🏗️ **Claude Architecte Senior** : Analyse architecturale avec compréhension du contexte SAP KB
- 🧪 **Claude QA Expert** : Analyse qualité des tests et suggestions de tests manquants

**Résultat** : Des insights bien plus profonds qu'une simple analyse statique !

## 🎯 En Bref

**Avant de vous coucher**, lancez cette commande :

### Windows
```cmd
scripts\run_nightly_review.cmd
```

### Linux/macOS
```bash
./scripts/run_nightly_review.sh
```

**Le matin**, consultez le rapport HTML généré automatiquement.

---

## 📖 Instructions Détaillées

### 1. Prérequis ✅

Assurez-vous que :
- [ ] Docker Desktop est démarré
- [ ] Les services sont lancés : `docker-compose ps`
- [ ] Python 3.8+ est installé
- [ ] **ANTHROPIC_API_KEY** est définie dans votre `.env`

**Important** : Pour bénéficier de l'analyse intelligente avec Claude, ajoutez dans votre `.env` :
```bash
ANTHROPIC_API_KEY=sk-ant-...votre_clé...
```

Sans cette clé, l'analyse sera limitée aux outils statiques (ruff, mypy).

### 2. Première Utilisation 🚀

**Ouvrez un terminal Windows (CMD ou PowerShell)** :

```cmd
cd C:\Project\SAP_KB
scripts\run_nightly_review.cmd
```

Le script va :
1. ✅ Créer des snapshots de vos bases de données (sécurité)
2. 🤖 Analyser la qualité de votre code **avec Claude** (analyse contextuelle + statique)
3. 🏗️ Analyser l'architecture **avec Claude Architecte** (patterns, anti-patterns, recommandations)
4. 🧪 Exécuter les tests et analyser la qualité **avec Claude QA**
5. ✅ Valider tous les endpoints API
6. ✅ Générer un rapport HTML interactif avec insights Claude
7. ✅ Ouvrir automatiquement le rapport dans votre navigateur

**Durée estimée** : 10-20 minutes (analyse Claude incluse)

### 3. Variations Rapides ⚡

#### Revue sans tests (plus rapide)
```cmd
scripts\run_nightly_review.cmd --skip-tests
```
⏱️ **Durée** : ~2 minutes

#### Revue sans ouvrir le navigateur
```cmd
scripts\run_nightly_review.cmd --no-browser
```
📄 **Rapport disponible dans** : `reports/nightly/`

#### Revue minimale (code only)
```cmd
scripts\run_nightly_review.cmd --skip-tests --skip-frontend
```
⏱️ **Durée** : ~1 minute

### 4. Consulter les Résultats 📊

Les rapports sont dans : **`reports/nightly/`**

Format du nom : `nightly_review_YYYYMMDD_HHMMSS.html`

**Exemple** : `nightly_review_20251008_220531.html`

### 5. Workflow Quotidien 🔄

#### Le Soir (avant de dormir)
```cmd
cd C:\Project\SAP_KB
scripts\run_nightly_review.cmd
```

Vous pouvez fermer le terminal et aller vous coucher. Le rapport sera prêt.

#### Le Matin (au réveil)
1. Ouvrir le dernier rapport dans `reports/nightly/`
2. Consulter les résumés en haut
3. Prioriser les problèmes selon les badges :
   - 🔴 **Erreur** : À corriger immédiatement
   - 🟡 **Warning** : À planifier
   - 🟢 **Info** : Optionnel

## 📁 Fichiers Créés

Après la première exécution, vous aurez :

```
reports/
└── nightly/
    ├── nightly_review_20251008_220531.html  (Rapport visuel)
    └── nightly_review_20251008_220531.json  (Données brutes)

backups/
└── nightly_review/
    ├── entity_types_registry_20251008_220531.db
    └── redis_dump_20251008_220531.rdb
```

## 🎨 Exemple de Rapport

Le rapport HTML contient 5 sections avec analyses Claude :

### 📋 Code Review (Statique + Claude)
- **Analyse statique** : Erreurs ruff/mypy détectées
- **🤖 Issues Claude** : Bugs potentiels, problèmes de logique, vulnérabilités
- **🤖 Suggestions** : Améliorations de lisibilité, maintenabilité, performance
- **🤖 Refactoring** : Opportunités d'amélioration du design

### 🏗️ Architecture (Claude Architecte)
- **🤖 Analyse structure** : Forces et faiblesses architecturales
- **🤖 Patterns détectés** : Design patterns identifiés et leur qualité
- **🤖 Anti-patterns** : God Objects, couplage fort, violations SOLID
- **🤖 Recommandations** : Actions concrètes pour améliorer l'architecture

### 🧪 Test Analysis (Exécution + Claude QA)
- **Exécution** : Tests réussis/échoués
- **Couverture** : % de code testé
- **🤖 Qualité tests** : Problèmes dans les tests existants
- **🤖 Tests manquants** : Suggestions de tests prioritaires avec scénarios

### 🌐 Frontend Validation
- **Services** : Statut Neo4j, Qdrant, Redis, etc.
- **API** : Tous les endpoints testés
- **Performance** : Temps de réponse

### 💾 DB Safety
- **Snapshots** : Sauvegardes créées
- **Intégrité** : Vérifications post-tests

## 🐛 Problèmes Courants

### "Docker services not running"
**Solution** :
```bash
docker-compose up -d
docker-compose ps  # Vérifier que tout est UP
```

### "Python not found"
**Solution** :
```cmd
python --version  # Vérifier l'installation
```

Si erreur, installer Python 3.8+ depuis python.org

### Rapport ne s'ouvre pas
**Solution** : Ouvrir manuellement dans `reports/nightly/`

### Tests trop longs
**Solution** : Utiliser `--skip-tests` pour une revue rapide

## 💡 Astuces

### Créer un raccourci Windows
1. Clic droit sur `run_nightly_review.cmd`
2. "Créer un raccourci"
3. Placer sur le bureau
4. Renommer en "🌙 Revue Nocturne"

Double-clic le soir avant de dormir !

### Planifier avec Task Scheduler (Windows)
1. Ouvrir Task Scheduler
2. "Créer une tâche de base"
3. Déclencheur : Quotidien à 22h
4. Action : `C:\Project\SAP_KB\scripts\run_nightly_review.cmd`

### Ajouter un alias bash (Linux/macOS)
```bash
echo 'alias nightly="cd ~/SAP_KB && ./scripts/run_nightly_review.sh"' >> ~/.bashrc
source ~/.bashrc
```

Puis simplement :
```bash
nightly
```

## 📚 Documentation Complète

Pour plus de détails, consultez :

📖 **Documentation complète** : `scripts/nightly_review/README.md`

---

## ✅ Checklist Premier Lancement

- [ ] Docker Desktop est démarré
- [ ] Services Docker sont lancés (`docker-compose ps`)
- [ ] Python 3.8+ est installé
- [ ] **ANTHROPIC_API_KEY** définie dans `.env`
- [ ] Ouvrir un terminal dans `C:\Project\SAP_KB`
- [ ] Lancer `.\scripts\run_nightly_review.cmd` (PowerShell) ou `scripts\run_nightly_review.cmd` (CMD)
- [ ] Attendre la fin (10-20 min avec analyse Claude)
- [ ] Consulter le rapport HTML ouvert automatiquement
- [ ] 🤖 Profiter des insights contextuels de Claude !

**Félicitations ! Votre première revue nocturne intelligente est terminée** 🎉

---

**Besoin d'aide ?** Consultez `scripts/nightly_review/README.md` ou le code source dans `scripts/nightly_review/modules/`
