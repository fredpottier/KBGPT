# 🤖 Intégration Claude Code ↔ Logseq

## 🎯 Objectif

Utiliser **Claude Code** pour mettre à jour automatiquement le tracking Logseq pendant les sessions de développement.

---

## 🔄 Workflow Intégré

### Avant Session (Manuelle)
1. Ouvrir Logseq sur `project_notes/`
2. Créer journal du jour si inexistant
3. Noter objectifs dans Logseq

### Pendant Session (Claude Code)
Demander à Claude Code de :
- ✅ Marquer tâches en `DOING` quand commencées
- ✅ Marquer tâches en `DONE` quand terminées
- ✅ Ajouter notes techniques dans page de phase
- ✅ Créer ADR pour décisions importantes
- ✅ Logger blockers dans [[Project Blockers]]
- ✅ Mettre à jour effort réel vs estimé

### Fin Session (Semi-automatique)
Claude Code peut :
- ✅ Ajouter entrée dans journal du jour
- ✅ Résumer réalisations
- ✅ Mettre à jour dashboard
- ✅ Calculer avancement

---

## 💬 Commandes Utiles pour Claude Code

### Démarrer une Phase
```
Claude, je vais commencer la Phase 0 - Security Hardening.
Peux-tu mettre à jour Logseq :
- Marquer Phase 0 status:: [[IN_PROGRESS]]
- Créer entrée dans journal d'aujourd'hui
- Préparer les premières tâches
```

### Compléter une Tâche
```
Je viens de terminer l'implémentation du JWT RS256.
Mets à jour Logseq :
- Cocher la tâche "Implémenter JWT RS256" dans Phase 0
- Ajouter notes techniques dans la page Phase 0
- Noter l'effort réel (40h estimé, combien réel ?)
```

### Logger un Blocker
```
Je suis bloqué sur la configuration RBAC avec FastAPI.
Crée un blocker dans Logseq avec :
- Severity: HIGH
- Phase: Phase 0
- Description du problème
- Plan de résolution si tu as des idées
```

### Créer un ADR
```
On a décidé d'utiliser RS256 au lieu de HS256 pour JWT.
Crée un ADR dans Logseq qui documente :
- Le contexte
- La décision
- Les conséquences
- Les alternatives
```

### Fin de Session
```
Ma session de travail est terminée.
Peux-tu mettre à jour le journal d'aujourd'hui :
- Résumer ce qu'on a fait
- Noter les insights importants
- Lister les prochaines étapes
- Mettre à jour le dashboard avancement
```

---

## 📋 Templates pour Commandes

### Template Début Phase
```
Claude, on démarre [[Phase X - Nom Phase]].

Actions :
1. Mettre status:: [[IN_PROGRESS]]
2. Créer journal entry aujourd'hui
3. Lister les 3 premières tâches prioritaires
4. Vérifier les dépendances (phases précédentes complètes ?)
```

### Template Complétion Tâche
```
Tâche complétée : [Description tâche]

Phase : [[Phase X]]
Effort estimé : Xh
Effort réel : Yh
Notes techniques : [Détails implémentation]

→ Mettre à jour Logseq
```

### Template Blocker
```
BLOCKER détecté !

Phase : [[Phase X]]
Tâche : [Quelle tâche]
Problème : [Description]
Impact : [Conséquences]
Tentatives : [Ce qui a été essayé]

→ Logger dans [[Project Blockers]]
→ Proposer plan de résolution
```

### Template ADR
```
Décision architecture à documenter :

Titre : [Nom décision]
Contexte : [Pourquoi cette décision ?]
Décision : [Qu'avons-nous décidé ?]
Alternatives : [Quoi d'autre ?]

→ Créer ADR-XXX dans Logseq
```

---

## 🔍 Queries que Claude Peut Exécuter

### Lister Tâches En Cours
```
Claude, liste-moi toutes les tâches DOING actuellement dans Logseq
```

### Calculer Avancement Phase
```
Claude, calcule l'avancement de la Phase 0 :
- Combien de tâches complétées ?
- Effort réel vs estimé ?
- Critères d'acceptance validés ?
```

### Identifier Blockers
```
Claude, vérifie s'il y a des blockers actifs dans Logseq
et donne-moi un résumé
```

### Rapport Hebdomadaire
```
Claude, génère un rapport hebdomadaire depuis Logseq :
- Phases avancées
- Tâches complétées
- Effort consommé
- Blockers résolus
- Prochaines priorités
```

---

## 📊 Automation Possible

### Mise à Jour Automatique Dashboard
Claude peut parser les pages de phases et calculer :
- **Phases Complétées** : Compter status:: [[COMPLETED]]
- **Avancement Global** : (Tâches DONE / Total tâches) * 100
- **Effort Consommé** : Sommer effort réel des tâches DONE
- **Drift** : Comparer effort réel vs estimé

### Exemple Commande
```
Claude, mets à jour le dashboard [[Back2Promise Project]] :
1. Compte les phases complétées
2. Calcule l'avancement global
3. Identifie les blockers actifs
4. Liste les phases IN_PROGRESS
```

---

## 🎯 Workflow Complet Exemple

### Lundi Matin - Début Sprint
```
🧑 : Claude, nouvelle semaine. Je vais travailler sur Phase 0 cette semaine.
     Objectifs : JWT + RBAC.
     Peux-tu préparer Logseq ?

🤖 : [Claude crée entrée journal, liste tâches, marque Phase 0 IN_PROGRESS]
```

### Mardi Après-midi - Tâche Complétée
```
🧑 : JWT RS256 implémenté et testé. 45h réel vs 40h estimé.
     Mets à jour Logseq.

🤖 : [Claude coche tâche, note effort, ajoute notes techniques]
```

### Mercredi - Blocker
```
🧑 : Bloqué sur RBAC. FastAPI decorators ne marchent pas comme prévu.

🤖 : [Claude crée blocker, propose solutions, update journal]
```

### Jeudi - Décision Architecture
```
🧑 : On a décidé d'utiliser Pydantic models pour RBAC au lieu de decorators.
     Documente cette décision.

🤖 : [Claude crée ADR-004 avec contexte, décision, conséquences]
```

### Vendredi - Fin Sprint
```
🧑 : Fin de sprint. Résume la semaine dans Logseq.

🤖 : [Claude génère rapport, met à jour dashboard, calcule avancement]
```

---

## 💡 Tips

1. **Commit Logseq après chaque session** avec Claude
   ```bash
   cd project_notes
   git add .
   git commit -m "Session 2025-10-09 : Phase 0 JWT implémenté"
   ```

2. **Utiliser Claude pour la cohérence**
   - Claude maintient le format Logseq
   - Claude respecte les templates
   - Claude calcule les métriques

3. **Review régulière**
   - Chaque vendredi : demander rapport hebdo
   - Chaque mois : demander rapport mensuel
   - Ajuster estimations si drift important

4. **Itérer sur les commandes**
   - Créer vos propres templates
   - Affiner les prompts Claude
   - Automatiser ce qui est répétitif

---

## 🚀 Pour Commencer

**Commande suggérée pour démarrer** :
```
Claude, je veux commencer à utiliser Logseq pour tracker Back2Promise.
Le setup est dans project_notes/.
Peux-tu :
1. Vérifier que tout est en place
2. Me proposer de démarrer Phase 0 ou autre phase
3. Créer le journal d'aujourd'hui si inexistant
4. Préparer la première session
```

---

**Créé le** : 2025-10-09
**Statut** : ✅ Prêt à utiliser
**Intégration** : Claude Code + Logseq = 💪
