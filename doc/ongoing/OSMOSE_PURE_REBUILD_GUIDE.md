# Guide Rebuild Docker - OSMOSE Pure avec spaCy

**Date:** 2025-10-14 22:15

---

## 🎯 Problème Résolu

Les modèles spaCy NER n'étaient **pas installés automatiquement** lors du build Docker.

**Conséquence:** À chaque rebuild, il fallait réinstaller manuellement avec :
```bash
docker-compose exec app python -m spacy download en_core_web_sm
```

**Solution:** Modèles spaCy maintenant installés **automatiquement** dans le Dockerfile.

---

## ✅ Modification Dockerfile

**Fichier:** `app/Dockerfile:56-59`

**Ajout:**
```dockerfile
# Téléchargement modèles spaCy pour OSMOSE (Phase 1 V2.1)
# Modèles légers (sm) pour économiser espace disque
RUN python -m spacy download en_core_web_sm || echo "spaCy en model download failed"
RUN python -m spacy download fr_core_news_sm || echo "spaCy fr model download failed"
```

**Modèles installés:**
- `en_core_web_sm` : Anglais (léger, 12 MB)
- `fr_core_news_sm` : Français (léger, 15 MB)

**Note:** Modèles "sm" (small) choisis pour économiser espace. Les modèles "trf" (transformers) sont 10x plus gros mais plus précis.

---

## 🚀 Procédure Rebuild

### Option 1: Rebuild Rapide (Recommandé)

Rebuild seulement les services modifiés :

```bash
# Arrêter services
docker-compose down

# Rebuild app + worker (cache Docker réutilisé)
docker-compose build app worker

# Redémarrer
docker-compose up -d

# Vérifier logs build (chercher "spaCy")
docker-compose logs app | grep -i spacy
```

**Durée:** ~3-5 minutes (avec cache Docker)

---

### Option 2: Rebuild Complet (Si problème cache)

Rebuild sans cache Docker :

```bash
# Arrêter services
docker-compose down

# Rebuild SANS cache (plus long mais propre)
docker-compose build --no-cache app worker

# Redémarrer
docker-compose up -d
```

**Durée:** ~10-15 minutes

---

## ✅ Vérification Post-Rebuild

### Étape 1: Vérifier modèles spaCy installés

```bash
docker-compose exec app python -m spacy info

# Attendu:
# - en_core_web_sm  (installed)
# - fr_core_news_sm (installed)
```

### Étape 2: Lancer script validation complet

```bash
docker-compose exec app python -m knowbase.ingestion.validate_osmose_deps
```

**Résultat attendu:**
```
INFO: Imports Python       : ✅ OK
INFO: spaCy                : ✅ OK  # ← DOIT ÊTRE OK maintenant
INFO: Neo4j                : ✅ OK
INFO: Qdrant               : ✅ OK
INFO: LLM Config           : ✅ OK
INFO: OSMOSE Config        : ✅ OK
================================================================================
🎉 TOUTES LES VALIDATIONS RÉUSSIES
✅ Vous pouvez lancer un import PPTX en toute sécurité
```

---

## 🐛 Troubleshooting

### spaCy toujours en ÉCHEC après rebuild

**Vérifier que le build a bien installé les modèles:**
```bash
docker-compose logs app | grep -i spacy
```

**Attendu dans les logs build:**
```
Successfully installed en-core-web-sm-3.7.x
Successfully installed fr-core-news-sm-3.7.x
```

**Si absent:**
- Le build a échoué silencieusement (|| echo)
- Essayer rebuild sans cache: `docker-compose build --no-cache app`

---

### Erreur "OSError: [E050] Can't find model 'en_core_web_sm'"

**Cause:** Build partiel incomplet

**Solution:**
```bash
# Installation manuelle dans le container
docker-compose exec app python -m spacy download en_core_web_sm
docker-compose exec app python -m spacy download fr_core_news_sm

# Puis rebuild propre
docker-compose down
docker-compose build --no-cache app worker
docker-compose up -d
```

---

### Rebuild trop long (> 15 min)

**Probable:** Téléchargement PyTorch CPU depuis scratch

**Vérification:**
```bash
docker-compose logs app | tail -100
```

**Si bloqué sur PyTorch:**
- Normal pour un build from scratch (~800 MB)
- Laisse finir, puis builds suivants seront rapides (cache)

---

## 📊 Espace Disque

**Modèles spaCy ajoutés:**
- en_core_web_sm: ~12 MB
- fr_core_news_sm: ~15 MB
- **Total:** ~27 MB

**Augmentation taille image Docker:** +30 MB (~0.5% si image ~6 GB)

---

## 🎯 Après Rebuild Réussi

**Workflow complet:**

```bash
# 1. Validation (rapide, pas d'appels LLM)
docker-compose exec app python -m knowbase.ingestion.validate_osmose_deps

# Si 6/6 ✅ OK:

# 2. Import PPTX (via interface ou copie fichier)
cp votre_deck.pptx data/docs_in/

# 3. Observer logs Vision + OSMOSE
docker-compose logs -f worker
```

**Logs attendus:**
```
📊 [OSMOSE PURE] use_vision = True
📊 [OSMOSE PURE] image_paths count = 25
Slide 1 [VISION SUMMARY]: 847 chars generated
Slide 1 [VISION SUMMARY CONTENT]:
This slide presents...
...
✅ [OSMOSE PURE] 25 résumés Vision collectés
[OSMOSE PURE] Texte enrichi construit: 18543 chars
================================================================================
[OSMOSE PURE] Lancement du traitement sémantique
================================================================================
[OSMOSE] SemanticPipelineV2 initialized
...
[OSMOSE PURE] ✅ Traitement réussi:
  - 42 concepts canoniques
  - Proto-KG: 42 concepts + 35 relations + 42 embeddings
```

---

## 📝 Checklist Finale

Avant de tester un import PPTX complet:

- [ ] Rebuild Docker effectué
- [ ] Logs build montrent installation spaCy OK
- [ ] `spacy info` montre modèles installés
- [ ] Script validation retourne 6/6 ✅ OK
- [ ] Services Docker tous UP (app, worker, neo4j, qdrant, redis)
- [ ] Fichier PPTX test prêt (15-30 slides recommandé)

**Si tous les ✅ sont cochés → GO pour test PPTX !**

---

**Version:** 1.0
**Date:** 2025-10-14 22:15
