# 📊 Rapports de Revue Nocturne

Ce répertoire contient les rapports de revue nocturne générés par Claude Code.

## 📁 Structure

```
reports/nightly/
├── nightly_review_20251009_220000.md    # Rapport du 9 Oct 2025 à 22h
├── nightly_review_20251010_220000.md    # Rapport du 10 Oct 2025 à 22h
└── ...
```

## 🔍 Format des Rapports

Chaque rapport contient :

### 📊 Résumé Exécutif
Vue d'ensemble des problèmes détectés

### 🤖 Code Review
- Issues critiques (bugs, sécurité, logique)
- Suggestions d'amélioration (performance, lisibilité)
- Opportunités de refactoring

### 🏗️ Analyse Architecture
- Forces et faiblesses
- Patterns détectés
- Anti-patterns
- Recommandations avec priorités

### 🧪 Analyse Tests
- Qualité des tests existants
- Tests manquants prioritaires
- Recommandations de stratégie de test

### 🔗 Analyse Knowledge Graph
- Entity System (extraction, normalisation)
- Entity Types Registry (cohérence SQLite ↔ Neo4j)
- Relations & Facts
- Graph Traversal (optimisation)

### 💡 Actions Recommandées
Liste priorisée par criticité

## 🚀 Comment Générer un Rapport

Dans Claude Code, tapez :
```
/nightly-review
```

Le rapport sera automatiquement sauvegardé ici.

## 📖 Lecture du Rapport

1. **Commencez par le Résumé Exécutif** pour vue d'ensemble
2. **Priorisez les Issues Critiques** (impact immédiat)
3. **Lisez les Recommandations** par priorité
4. **Posez des questions à Claude** pour clarifications

## 💾 Rétention

- Les rapports sont conservés indéfiniment
- Utilisez-les pour suivre l'évolution de la qualité du code
- Comparez les rapports pour mesurer les progrès

## 🔗 Ressources

- **Guide complet** : `REVUE_NOCTURNE_CLAUDE_CODE.md` (à la racine)
- **Slash command** : `.claude/commands/nightly-review.md`

---

*Rapports générés par Claude Code - Revue Nocturne SAP KB*
