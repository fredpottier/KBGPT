# 🚀 Guide d'Utilisation Rapide - Scripts AWS

**Comment utiliser les scripts depuis n'importe où**

---

## ✅ Bonne Nouvelle : Les Scripts se Repositionnent Automatiquement !

Vous pouvez exécuter les scripts depuis **n'importe quel répertoire** du projet. Les scripts détectent automatiquement la racine du projet et s'y positionnent.

---

## 📝 Trois Façons d'Exécuter les Scripts

### **Méthode 1 : Depuis la Racine du Projet** (Recommandé)

```powershell
cd C:\Project\SAP_KB
.\scripts\aws\build-and-push-ecr.ps1
.\scripts\aws\deploy-ec2.ps1 -InstanceIP "18.203.45.67" -KeyPath "key.pem"
```

✅ **Avantage :** Classique et clair

---

### **Méthode 2 : Depuis le Dossier scripts/aws/**

```powershell
cd C:\Project\SAP_KB\scripts\aws
.\build-and-push-ecr.ps1
.\deploy-ec2.ps1 -InstanceIP "18.203.45.67" -KeyPath "C:\path\to\key.pem"
```

**Ce qui se passe :**
```
⚠️  Repositionnement automatique à la racine du projet...
✓ Racine du projet trouvée: C:\Project\SAP_KB
📁 Répertoire de travail: C:\Project\SAP_KB
```

✅ **Avantage :** Les scripts remontent automatiquement à la racine

---

### **Méthode 3 : Depuis n'importe où avec Chemin Complet**

```powershell
cd C:\Users\VotreNom\Documents
C:\Project\SAP_KB\scripts\aws\build-and-push-ecr.ps1
```

✅ **Avantage :** Fonctionne de n'importe où

---

## 🎯 Exemples Concrets

### Exemple 1 : Build et Push (Première Fois)

```powershell
# Vous êtes n'importe où
cd C:\Project\SAP_KB

# Ou même dans scripts/aws/ :
cd scripts\aws

# Exécuter le build (se repositionne auto à la racine)
.\build-and-push-ecr.ps1

# Le script affichera :
# 📁 Répertoire de travail: C:\Project\SAP_KB
# >>> Build de l'image backend/worker (app)
# ...
```

---

### Exemple 2 : Déploiement

```powershell
# Depuis n'importe où dans le projet
.\scripts\aws\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\Users\VotreNom\.ssh\key.pem"

# Le script trouve automatiquement docker-compose.ecr.yml, .env.production, etc.
```

---

### Exemple 3 : Arrêter l'Instance (Économie)

```powershell
# Les scripts de gestion (stop/start/terminate) n'ont pas besoin de la racine
# Ils fonctionnent depuis n'importe où car ils appellent seulement AWS CLI

.\scripts\aws\aws-stop-instance.ps1 -InstanceName "knowbase-osmose-prod"
```

---

## ⚠️ Que Faire Si Vous Voyez une Erreur ?

### Erreur : "CreateFile app: The system cannot find the file specified"

**Cause :** Vous avez une ancienne version du script sans auto-repositionnement.

**Solution :**
```powershell
# Solution 1 : Se positionner manuellement
cd C:\Project\SAP_KB
.\scripts\aws\build-and-push-ecr.ps1

# Solution 2 : Mettre à jour le script (devrait déjà être fait)
git pull
```

---

### Erreur : "Impossible de trouver la racine du projet"

**Cause :** Vous êtes trop loin de la racine du projet (>3 niveaux).

**Solution :**
```powershell
# Se positionner explicitement à la racine
cd C:\Project\SAP_KB
.\scripts\aws\build-and-push-ecr.ps1
```

---

## 📊 Résumé des Scripts

| Script | Auto-Repositionnement | Depuis Où Exécuter |
|--------|----------------------|-------------------|
| `build-and-push-ecr.ps1` | ✅ Oui | N'importe où dans le projet |
| `deploy-ec2.ps1` | ✅ Oui | N'importe où dans le projet |
| `aws-stop-instance.ps1` | ⚠️ Non nécessaire | N'importe où (AWS CLI) |
| `aws-start-instance.ps1` | ⚠️ Non nécessaire | N'importe où (AWS CLI) |
| `aws-terminate-all.ps1` | ⚠️ Non nécessaire | N'importe où (AWS CLI) |

---

## 💡 Bonnes Pratiques

### ✅ Recommandé

```powershell
# Toujours depuis la racine pour plus de clarté
cd C:\Project\SAP_KB
.\scripts\aws\build-and-push-ecr.ps1
```

### ✅ Acceptable

```powershell
# Depuis scripts/aws/ (auto-repositionnement)
cd C:\Project\SAP_KB\scripts\aws
.\build-and-push-ecr.ps1
```

### ❌ À Éviter

```powershell
# Depuis un répertoire complètement externe
cd C:\Users\Ailleurs
C:\Project\SAP_KB\scripts\aws\build-and-push-ecr.ps1
# Fonctionne mais moins propre
```

---

## 🎓 Comprendre le Repositionnement Automatique

Quand vous exécutez un script, voici ce qui se passe :

```
1. Script vérifie : "Suis-je à la racine du projet ?"
   - Cherche : app/, src/, frontend/ (pour build-and-push)
   - Cherche : docker-compose.ecr.yml, config/ (pour deploy)

2. Si NON :
   - Remonte d'un niveau (max 3 fois)
   - Vérifie à nouveau
   - Se positionne dès qu'il trouve la racine

3. Si OUI :
   - Continue normalement

4. Si racine introuvable après 3 niveaux :
   - Affiche erreur avec instructions
```

---

## 🆘 Support

Si vous rencontrez des problèmes :

1. **Vérifiez votre structure de projet** :
```powershell
cd C:\Project\SAP_KB
ls
# Vous devez voir : app/, src/, frontend/, config/, docker-compose.ecr.yml
```

2. **Vérifiez depuis où vous exécutez** :
```powershell
pwd  # Affiche le répertoire actuel
```

3. **Positionnez-vous manuellement** :
```powershell
cd C:\Project\SAP_KB
.\scripts\aws\build-and-push-ecr.ps1
```

---

**Dernière mise à jour :** 2025-10-13
