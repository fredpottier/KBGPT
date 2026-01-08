# Plan de Nettoyage Documentation - Conformité CLAUDE.md

**Date** : 2025-10-20
**Contexte** : Audit de conformité avec les règles strictes de structure documentation

---

## 📋 Règles de Structure (Rappel)

### Structure UNIQUE Autorisée

```
doc/
├── README.md                                 # Guide navigation
├── OSMOSE_AMBITION_PRODUIT_ROADMAP.md       # Vision produit
├── OSMOSE_ARCHITECTURE_TECHNIQUE.md         # Architecture technique
├── OSMOSE_ROADMAP_INTEGREE.md               # Roadmap globale
│
├── phases/                                  # 1 fichier par phase (4 max)
│   ├── PHASE1_SEMANTIC_CORE.md
│   ├── PHASE2_INTELLIGENCE_AVANCEE.md
│   ├── PHASE3_PRODUCTION_KG.md
│   └── PHASE4_ADVANCED_FEATURES.md
│
├── ongoing/                                 # Docs temporaires/études
│   └── (tous les docs de travail)
│
└── archive/                                 # Archives historiques
```

### Règles ABSOLUES

1. **À la racine de `doc/` :**
   - ✅ UNIQUEMENT 4 fichiers permanents (README + 3 OSMOSE)
   - ❌ **JAMAIS** créer d'autres .md à la racine
   - ❌ **JAMAIS** créer de sous-dossiers sauf `phases/`, `ongoing/`, `archive/`

2. **Dans `doc/phases/` :**
   - ✅ EXACTEMENT 1 fichier par phase (4 max)
   - ❌ PAS de sous-dossiers

3. **Dans `doc/ongoing/` :**
   - ✅ Plans, études, snapshots
   - ✅ Sous-dossiers autorisés

---

## ❌ VIOLATIONS DÉTECTÉES

### 1. Fichiers à la Racine (Non Autorisés)

**Violation** : `doc/OSMOSE_EXTRACTION_QUALITY_ANALYSIS.md`
- **Type** : Analyse qualité extraction
- **Action Recommandée** : Déplacer vers `doc/ongoing/`
- **Raison** : Document d'analyse temporaire, pas un doc principal

```bash
mv doc/OSMOSE_EXTRACTION_QUALITY_ANALYSIS.md doc/ongoing/
```

### 2. Sous-Dossiers Non Autorisés à la Racine

#### A. `doc/phase1_osmose/`
**Contenu** : Documentation Phase 1 détaillée
- **Action Recommandée** :
  1. **Option A (RECOMMANDÉE)** : Archiver car Phase 1 terminée
     ```bash
     mv doc/phase1_osmose/ doc/archive/
     ```
  2. **Option B** : Consolider dans `doc/phases/PHASE1_SEMANTIC_CORE.md`

**Justification** : Phase 1 est COMPLÈTE (selon PHASE2_SESSION_STATUS.md). Le dossier `phase1_osmose/` contient probablement de la documentation de travail qui devrait être archivée.

#### B. `doc/phase2_osmose/`
**Contenu** : Documentation Phase 2 en cours
- **Action Recommandée** :
  1. **Créer** `doc/phases/PHASE2_INTELLIGENCE_AVANCEE.md` (fichier unique Phase 2)
  2. **Consolider** contenu de `phase2_osmose/` dans ce fichier
  3. **Archiver** `doc/phase2_osmose/` après consolidation
     ```bash
     # Après consolidation manuelle
     mv doc/phase2_osmose/ doc/archive/
     ```

**Justification** : Phase 2 en cours nécessite UN fichier dans `phases/`, pas un dossier séparé.

#### C. `doc/AWS Topics/`
**Contenu** : Documentation AWS (probablement étude infrastructure)
- **Action Recommandée** :
  ```bash
  mv "doc/AWS Topics/" doc/ongoing/aws_topics/
  ```

**Justification** : Études exploratoires doivent être dans `ongoing/`, et les espaces dans les noms de dossiers sont à éviter (Unix-unfriendly).

#### D. `doc/UserGuide/`
**Contenu** : Guide utilisateur
- **Action Recommandée** :
  1. **Si temporaire** : Déplacer vers `doc/ongoing/user_guide/`
  2. **Si permanent** : Demander confirmation utilisateur pour créer exception

```bash
mv doc/UserGuide/ doc/ongoing/user_guide/
```

**Justification** : Guide utilisateur n'est pas dans la liste autorisée des sous-dossiers racine.

---

## ✅ CONFORMITÉS ACTUELLES

1. **Fichiers racine OK** :
   - ✅ `README.md`
   - ✅ `OSMOSE_AMBITION_PRODUIT_ROADMAP.md`
   - ✅ `OSMOSE_ARCHITECTURE_TECHNIQUE.md`
   - ✅ `OSMOSE_ROADMAP_INTEGREE.md`

2. **Sous-dossiers autorisés OK** :
   - ✅ `doc/phases/` (existe)
   - ✅ `doc/ongoing/` (existe et bien utilisé)
   - ✅ `doc/archive/` (existe)

3. **Fichiers Phase 2 dans `ongoing/` ✅** :
   - ✅ `doc/ongoing/PHASE2_SESSION_STATUS.md` (créé hier)
   - ✅ `doc/ongoing/PHASE2_LOG_ANALYSIS_20251019.md` (créé hier)

---

## 📋 PLAN D'ACTION RECOMMANDÉ

### Étape 1 : Déplacements Simples (Sans Perte de Données)

```bash
# 1. Fichier racine → ongoing
mv doc/OSMOSE_EXTRACTION_QUALITY_ANALYSIS.md doc/ongoing/

# 2. Dossiers non autorisés → archive ou ongoing
mv doc/phase1_osmose/ doc/archive/
mv "doc/AWS Topics/" doc/ongoing/aws_topics/
mv doc/UserGuide/ doc/ongoing/user_guide/
```

### Étape 2 : Consolidation Phase 2 (Nécessite Travail Manuel)

**Objectif** : Créer `doc/phases/PHASE2_INTELLIGENCE_AVANCEE.md` unique

**Contenu à Inclure** :
1. Vue d'ensemble Phase 2
2. Architecture relation extraction
3. Status actuel (référence vers `ongoing/PHASE2_SESSION_STATUS.md`)
4. Problèmes résolus (référence vers `ongoing/PHASE2_LOG_ANALYSIS_20251019.md`)
5. Roadmap restante Phase 2

**Après Création** :
```bash
# Archiver ancien dossier Phase 2
mv doc/phase2_osmose/ doc/archive/
```

### Étape 3 : Vérification Finale

```bash
# Structure attendue
tree doc/ -L 2

# Devrait montrer :
# doc/
# ├── README.md
# ├── OSMOSE_AMBITION_PRODUIT_ROADMAP.md
# ├── OSMOSE_ARCHITECTURE_TECHNIQUE.md
# ├── OSMOSE_ROADMAP_INTEGREE.md
# ├── phases/
# │   ├── PHASE1_SEMANTIC_CORE.md
# │   └── PHASE2_INTELLIGENCE_AVANCEE.md  (à créer)
# ├── ongoing/
# │   ├── PHASE2_SESSION_STATUS.md
# │   ├── PHASE2_LOG_ANALYSIS_20251019.md
# │   ├── OSMOSE_EXTRACTION_QUALITY_ANALYSIS.md (déplacé)
# │   ├── aws_topics/ (déplacé)
# │   ├── user_guide/ (déplacé)
# │   └── etudes/
# └── archive/
#     ├── phase1_osmose/ (archivé)
#     └── phase2_osmose/ (archivé après consolidation)
```

---

## ⚠️ ACTIONS BLOQUÉES - AUTORISATION REQUISE

Les actions suivantes nécessitent l'autorisation explicite de l'utilisateur :

1. **Archivage `phase1_osmose/`** : Vérifier que Phase 1 est bien terminée et qu'aucune info n'est encore nécessaire

2. **Création `PHASE2_INTELLIGENCE_AVANCEE.md`** : Nécessite consolidation manuelle du contenu de `phase2_osmose/`

3. **Déplacement `UserGuide/`** : Confirmer si guide utilisateur est temporaire ou permanent

---

## 📊 Impact et Bénéfices

### Avant Nettoyage
```
doc/
├── 5 fichiers racine (1 violation)
├── 7 sous-dossiers racine (4 violations)
└── Structure confuse avec docs éparpillés
```

### Après Nettoyage
```
doc/
├── 4 fichiers racine (conformité 100%)
├── 3 sous-dossiers racine (conformité 100%)
└── Structure claire et maintenable
```

### Bénéfices
1. ✅ **Conformité totale** avec règles CLAUDE.md
2. ✅ **Navigation simplifiée** : 4 fichiers racine max
3. ✅ **Archivage propre** : Phases terminées dans `archive/`
4. ✅ **Séparation claire** : Permanent vs temporaire
5. ✅ **Maintenabilité** : Structure prévisible pour futures sessions

---

## 🚀 Prochaines Étapes

### Immédiat (Demander Autorisation)
1. Valider plan de nettoyage avec utilisateur
2. Confirmer que Phase 1 est archivable
3. Confirmer statut `UserGuide/`

### Court Terme (Après Autorisation)
1. Exécuter déplacements simples (Étape 1)
2. Créer `PHASE2_INTELLIGENCE_AVANCEE.md` consolidé
3. Archiver dossiers obsolètes

### Moyen Terme (Maintenance Continue)
1. Respecter strictement règles pour nouveaux docs
2. Réviser `ongoing/` régulièrement pour archivage
3. Créer `PHASE3_PRODUCTION_KG.md` quand Phase 3 démarre

---

**Note** : Ce plan respecte la règle **"JAMAIS créer à la racine sans confirmation explicite"** de CLAUDE.md. Toutes les actions sont proposées, aucune exécutée automatiquement.
