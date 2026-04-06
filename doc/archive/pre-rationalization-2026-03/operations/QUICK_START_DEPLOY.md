# 🚀 Quick Start - Déploiement AWS en 5 Étapes

**Guide simplifié pour déployer KnowWhere OSMOSE sur AWS depuis Windows**

---

## ✅ Prérequis (à installer une seule fois)

- [ ] **Compte AWS** actif avec credentials configurées
- [ ] **Docker Desktop** installé (https://www.docker.com/products/docker-desktop/)
- [ ] **AWS CLI** installé (https://aws.amazon.com/cli/)
- [ ] **OpenSSH Client** (inclus dans Windows 10/11)

**Test rapide :**
```powershell
docker --version
aws sts get-caller-identity
ssh -V
```

---

## 📋 Les 5 Étapes

### **Étape 1 : Créer `.env.production` avec vos clés API** ⏱️ 5 min

```powershell
# Copier le template
Copy-Item .env.ecr.example .env.production

# Éditer le fichier
notepad .env.production
```

**Remplissez SEULEMENT ces 3 lignes :**

```env
# 1. Vos clés API (obligatoire)
OPENAI_API_KEY=sk-proj-VOTRE_VRAIE_CLÉ_ICI      # ⬅️ Mettez votre clé OpenAI
ANTHROPIC_API_KEY=sk-ant-VOTRE_VRAIE_CLÉ_ICI   # ⬅️ Mettez votre clé Anthropic

# 2. Mot de passe Neo4j (choisissez-en un fort)
NEO4J_PASSWORD=VotreMotDePasseSecurise123!      # ⬅️ Choisissez un mot de passe

# 3. IP EC2 (laissez localhost, sera mis à jour automatiquement)
FRONTEND_API_BASE_URL=http://localhost:8000     # ⬅️ Laissez localhost, ne changez pas !
```

**✨ IMPORTANT : Laissez `localhost` pour `FRONTEND_API_BASE_URL`**
Le script `deploy-ec2.ps1` le remplacera automatiquement par l'IP EC2 lors du déploiement !

**Sauvegardez et fermez le fichier.**

---

### **Étape 2 : Builder et pusher les images vers ECR** ⏱️ 15-30 min

```powershell
# Build toutes les images et push vers AWS ECR
.\scripts\build-and-push-ecr.ps1
```

**Ce que fait le script :**
- ✅ Build 4 images custom (app, worker, frontend, ui)
- ✅ Mirror 4 images third-party (neo4j, redis, qdrant, ngrok)
- ✅ Crée automatiquement les repositories ECR
- ✅ Push tout vers ECR

**Output attendu à la fin :**
```
✅ Build et push terminés avec succès !

Images disponibles dans ECR:
  - 715927975014.dkr.ecr.eu-west-1.amazonaws.com/sap-kb-app:abc123
  - ...
```

---

### **Étape 3 : Créer l'instance EC2** ⏱️ 5 min

**Via AWS Console :**

1. **Aller sur EC2 Dashboard** : https://console.aws.amazon.com/ec2/

2. **Cliquer "Launch Instance"**

3. **Configuration :**
   - **Name** : `knowbase-osmose-prod`
   - **AMI** : Ubuntu Server 22.04 LTS
   - **Instance type** : `t3.xlarge` (minimum recommandé)
   - **Key pair** : Créer ou sélectionner une clé SSH
     - ⚠️ **Téléchargez le fichier .pem** (ex: `knowbase-key.pem`)
     - Sauvegardez-le dans un dossier sûr (ex: `C:\Users\VotreNom\.ssh\`)

4. **Network settings - Security Group :**

   Créez un Security Group avec ces ports :

   | Port | Source | Description |
   |------|--------|-------------|
   | 22 | My IP | SSH |
   | 8000 | 0.0.0.0/0 | API Backend |
   | 3000 | 0.0.0.0/0 | Frontend |
   | 8501 | My IP | Streamlit UI |
   | 7474 | My IP | Neo4j Browser |
   | 6333 | My IP | Qdrant UI |

5. **Storage** :
   - Root : 30 GB gp3
   - Ajoutez un volume (optionnel) : 100 GB gp3

6. **Cliquer "Launch instance"**

7. **⚠️ IMPORTANT : Récupérer l'IP publique**

   Une fois l'instance lancée (statut = "Running"), notez l'IP publique :

   - Dans la liste des instances, cliquez sur votre instance
   - Copiez la **"Public IPv4 address"**
   - Exemple : `18.203.45.67`

**💡 Recommandation : Associer une Elastic IP (optionnel mais utile)**

Cela vous donne une IP fixe qui ne change pas au redémarrage :

```powershell
# Allouer une Elastic IP
aws ec2 allocate-address --region eu-west-1

# Associer à votre instance
aws ec2 associate-address `
  --instance-id i-xxxxxxxxx `
  --allocation-id eipalloc-xxxxxxxxx `
  --region eu-west-1
```

---

### **Étape 4 : Déployer sur EC2** ⏱️ 10-20 min (première fois)

```powershell
# Remplacez par votre IP EC2 et chemin de clé
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\Users\VotreNom\.ssh\knowbase-key.pem"
```

**✨ Le script fait TOUT automatiquement :**

1. ✅ Test connexion SSH
2. ✅ Installation Docker, Docker Compose, AWS CLI sur EC2
3. ✅ Configuration credentials AWS
4. ✅ **Mise à jour automatique de l'IP EC2 dans le .env** 🎉
5. ✅ Transfert docker-compose.yml et .env
6. ✅ Transfert config/*.yaml
7. ✅ Login ECR
8. ✅ Pull des images
9. ✅ Démarrage des 7 conteneurs
10. ✅ Healthcheck automatique

**Output attendu à la fin :**

```
✅ Déploiement terminé avec succès !

Services accessibles sur l'instance EC2:
  - API Backend:    http://18.203.45.67:8000/docs
  - Frontend:       http://18.203.45.67:3000
  - Streamlit UI:   http://18.203.45.67:8501
  - Neo4j Browser:  http://18.203.45.67:7474
  - Qdrant UI:      http://18.203.45.67:6333/dashboard
```

---

### **Étape 5 : Vérifier que tout fonctionne** ⏱️ 5 min

**Ouvrez votre navigateur et testez :**

1. **Frontend** : http://18.203.45.67:3000
   - Vous devriez voir l'interface KnowWhere

2. **API Backend** : http://18.203.45.67:8000/docs
   - Vous devriez voir la documentation Swagger

3. **Neo4j Browser** : http://18.203.45.67:7474
   - Login : `neo4j` / Mot de passe : celui que vous avez mis dans `.env.production`

4. **Tester l'upload d'un document :**
   - Aller sur le frontend
   - Upload un PDF ou PPTX
   - Vérifier qu'il est traité

**Si tout fonctionne :** ✅ Félicitations, votre KnowWhere OSMOSE est déployé !

---

## 🔄 Workflow pour les Mises à Jour

Après avoir modifié votre code localement :

```powershell
# 1. Rebuild seulement les images custom (rapide)
.\scripts\build-and-push-ecr.ps1 -SkipThirdParty

# 2. Redéployer sans refaire le setup (rapide)
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "18.203.45.67" `
  -KeyPath "C:\Users\VotreNom\.ssh\knowbase-key.pem" `
  -SkipSetup

# Durée totale: 10-15 minutes
```

---

## 🆘 Problèmes Courants

### ❌ "Connection timed out" lors du SSH

**Solution :**
1. Vérifiez que le Security Group autorise le port 22 depuis votre IP
2. Vérifiez que l'instance est bien en état "Running"
3. Vérifiez que la clé SSH correspond à l'instance

```powershell
# Tester la connexion SSH manuellement
ssh -i "C:\Users\VotreNom\.ssh\knowbase-key.pem" ubuntu@18.203.45.67
```

---

### ❌ "Frontend ne se charge pas" après déploiement

**Solution :**
1. Vérifiez que le Security Group autorise le port 3000
2. Attendez 1-2 minutes (démarrage peut être long)
3. Vérifiez les logs :

```powershell
ssh -i "C:\path\to\key.pem" ubuntu@18.203.45.67
cd /home/ubuntu/knowbase
docker-compose logs frontend
```

---

### ❌ "API Backend retourne 500 Internal Server Error"

**Causes possibles :**
- Clés API manquantes ou invalides
- Neo4j pas encore démarré

**Solution :**
```powershell
# Se connecter à l'instance
ssh -i "C:\path\to\key.pem" ubuntu@18.203.45.67

# Vérifier que toutes les clés API sont dans le .env
cd /home/ubuntu/knowbase
grep "OPENAI_API_KEY" .env
grep "ANTHROPIC_API_KEY" .env

# Vérifier les logs du backend
docker-compose logs app

# Redémarrer le service si nécessaire
docker-compose restart app
```

---

### ❌ "Images Docker ne se pullent pas depuis ECR"

**Solution :**
```powershell
# Sur l'instance EC2, re-login ECR
ssh -i "C:\path\to\key.pem" ubuntu@18.203.45.67

aws ecr get-login-password --region eu-west-1 | \
  docker login --username AWS --password-stdin \
  715927975014.dkr.ecr.eu-west-1.amazonaws.com

# Puis re-pull
cd /home/ubuntu/knowbase
docker-compose pull
docker-compose up -d
```

---

## 📊 Résumé des Coûts

### AWS Infrastructure (par mois)

| Instance | Prix | Usage |
|----------|------|-------|
| t3.xlarge (dev/test) | ~$60 | 10-50 docs/jour |
| t3.2xlarge (production) | ~$120 | 50-200 docs/jour |

### API LLM (variable selon usage)

- 100 docs/jour PDF simples : ~$25/mois
- 100 docs/jour PDF complexes : ~$77/mois
- 100 docs/jour PPTX graphiques : ~$197/mois

**Total estimé pour tests** : $85-100/mois (infrastructure + API)

---

## 🎓 Commandes Utiles

### Se connecter à l'instance

```powershell
ssh -i "C:\Users\VotreNom\.ssh\knowbase-key.pem" ubuntu@18.203.45.67
```

### Une fois connecté

```bash
# Aller dans le répertoire du projet
cd /home/ubuntu/knowbase

# Voir le statut des conteneurs
docker-compose ps

# Voir les logs en temps réel
docker-compose logs -f

# Voir les logs d'un service spécifique
docker-compose logs -f app
docker-compose logs -f worker

# Redémarrer un service
docker-compose restart app

# Arrêter tout
docker-compose down

# Redémarrer tout
docker-compose up -d
```

---

## 📚 Documentation Complète

- **Guide complet** : `doc/AWS_DEPLOYMENT_GUIDE.md`
- **Architecture technique** : `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`
- **Coûts détaillés** : `doc/etudes/ARCHITECTURE_AGENTIQUE_OSMOSE.md`

---

## ✅ Checklist Rapide

Avant de déployer, vérifiez :

- [ ] `.env.production` créé avec vos clés API
- [ ] Images buildées et pushées vers ECR
- [ ] Instance EC2 créée (t3.xlarge minimum)
- [ ] Security Group configuré (ports 22, 8000, 3000, etc.)
- [ ] Clé SSH (.pem) téléchargée et accessible
- [ ] IP publique EC2 récupérée

Pour déployer :

```powershell
.\scripts\deploy-ec2.ps1 `
  -InstanceIP "VOTRE_IP_EC2" `
  -KeyPath "C:\path\to\votre-key.pem"
```

**C'est tout ! 🎉**

---

**Questions ?** Consultez `doc/AWS_DEPLOYMENT_GUIDE.md` pour plus de détails.
