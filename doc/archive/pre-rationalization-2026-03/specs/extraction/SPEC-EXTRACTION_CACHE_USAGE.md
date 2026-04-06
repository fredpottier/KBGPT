# 🔄 Extraction Cache System - Guide d'Utilisation

**Version:** V2.2
**Date:** 2025-10-17
**Objectif:** Économiser ressources/coûts lors développement et tests OSMOSE

---

## 🎯 Problème Résolu

Lors du développement/tests, **réimporter un document** nécessitait de **re-extraire le texte** (Vision LLM, MegaParse), ce qui était :

- **Coûteux**: $0.15-0.50 par document (appels Vision API)
- **Lent**: 30-90s pour extraction PDF/PPTX
- **Gourmand**: 80% CPU/RAM pour conversion images/OCR

Or, pendant le développement OSMOSE, on teste uniquement l'**analyse sémantique** (pas l'extraction).

---

## ✅ Solution : Format `.knowcache.json`

Système de cache automatique sauvegardant le **texte extrait** pour réutilisation instantanée.

### Architecture

```
Import Normal (1ère fois)
┌─────────────┐
│ Upload PDF  │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ Extraction Texte    │ ← Coûteux (Vision/MegaParse)
│ (Vision + MegaParse)│
└──────┬──────────────┘
       │
       ├──→ Sauvegarde .knowcache.json
       │    (data/extraction_cache/)
       │
       ▼
┌─────────────────────┐
│ OSMOSE Processing   │
└─────────────────────┘


Réimport avec Cache
┌────────────────────────┐
│ Upload .knowcache.json │
└──────┬─────────────────┘
       │
       ├──→ SKIP Extraction ✅
       │    (économie -90% temps, -80% coût)
       │
       ▼
┌─────────────────────┐
│ OSMOSE Processing   │ ← Direct
└─────────────────────┘
```

---

## 📋 Workflow Typique

### 1️⃣ Premier Import (création cache)

```bash
# Upload via frontend
http://localhost:3000/documents/import
→ Uploader: SAP_SDOL_Guide.pdf

# Résultat:
# - Extraction Vision (45s, $0.18)
# - Cache sauvegardé: data/extraction_cache/SAP_SDOL_Guide.knowcache.json
# - OSMOSE processing
```

### 2️⃣ Tests Itératifs OSMOSE (réutilisation cache)

```bash
# Modifier config OSMOSE (ex: min_concepts_per_topic: 8)
vim config/semantic_intelligence_v2.yaml

# Réimporter cache (skip extraction)
http://localhost:3000/documents/import
→ Uploader: SAP_SDOL_Guide.knowcache.json

# Résultat:
# - SKIP extraction (0s, $0)
# - OSMOSE processing avec nouvelle config
```

### 3️⃣ Économies

| Opération | Sans Cache | Avec Cache | Économie |
|-----------|------------|------------|----------|
| **Temps** | 90s | 8s | **-91%** |
| **Coût** | $0.18 | $0.00 | **-100%** |
| **CPU/RAM** | 80% usage | 10% usage | **-87%** |

---

## 🔧 Configuration

### Variables `.env`

```bash
# Activer système cache
ENABLE_EXTRACTION_CACHE=true

# Répertoire stockage caches
EXTRACTION_CACHE_DIR=/app/data/extraction_cache

# Expiration auto (jours)
CACHE_EXPIRY_DAYS=30

# Accepter upload .knowcache.json
ALLOW_CACHE_UPLOAD=true
```

### Structure Répertoire

```
data/
├── docs_in/              # Uploads originaux
├── docs_done/            # Traités
├── extraction_cache/     # NOUVEAU: Caches
│   ├── Document1.pdf.knowcache.json
│   ├── Document2.pptx.knowcache.json
│   └── ... (un cache par document)
└── public/
    └── slides_png/       # Images générées
```

---

## 📄 Format `.knowcache.json`

```json
{
  "version": "1.0",
  "metadata": {
    "source_file": "SAP_SDOL_Guide.pdf",
    "source_hash": "sha256:abc123...",
    "extraction_timestamp": "2025-10-17T15:30:00Z",
    "extraction_config": {
      "use_vision": true,
      "vision_model": "gpt-4o",
      "megaparse_version": "0.3.1"
    }
  },
  "document_metadata": {
    "title": "SAP Secure SDOL Guide",
    "pages": 12,
    "language": "en",
    "author": "SAP",
    "keywords": ["security", "SDOL", "DevSecOps"]
  },
  "extracted_text": {
    "full_text": "--- Page 1 ---\nThe Secure Software...",
    "length_chars": 39255,
    "pages": [
      {
        "page_number": 1,
        "text": "The Secure Software...",
        "image_path": "slides_png/SDOL_page_1.png"
      }
    ]
  },
  "extraction_stats": {
    "duration_seconds": 45.2,
    "vision_calls": 12,
    "cost_usd": 0.18
  }
}
```

---

## 🧪 Cas d'Usage

### Développement Agent OSMOSE

```bash
# Tester différents paramètres extraction
for min_concepts in 2 4 8 12; do
    # Modifier config
    sed -i "s/min_concepts_per_topic: .*/min_concepts_per_topic: $min_concepts/" \
        config/semantic_intelligence_v2.yaml

    # Réimporter AVEC cache (instantané)
    curl -F "file=@data/extraction_cache/Test_Doc.knowcache.json" \
        http://localhost:8000/upload

    # Analyser résultats
    # ...
done
```

### Tests Régression

```bash
# Dataset test fixe (5 documents)
TEST_CACHES=(
    "Technical_Manual.knowcache.json"
    "Product_Overview.knowcache.json"
    "Security_Policy.knowcache.json"
    "Architecture_Doc.knowcache.json"
    "Release_Notes.knowcache.json"
)

# Tests rapides (5x instantanés vs 5x 90s chacun)
for cache in "${TEST_CACHES[@]}"; do
    curl -F "file=@data/extraction_cache/$cache" \
        http://localhost:8000/upload
done

# Temps total: 40s (vs 450s sans cache)
```

### Debugging OSMOSE

```bash
# Problème: extraction pauvre sur un document
# Solution:
# 1. Récupérer cache existant
cp data/extraction_cache/Problem_Doc.knowcache.json /tmp/

# 2. Modifier paramètres OSMOSE (logs DEBUG, etc.)
# 3. Réimporter cache pour debug instantané
# 4. Itérer jusqu'à résolution
```

---

## ⚠️ Limitations

### 1. Invalidation Cache

Cache **invalide** si :
- Âge > `CACHE_EXPIRY_DAYS` (défaut: 30j)
- Version format incompatible
- Fichier corrompu

### 2. Modification Document Source

Si **document source modifié** :
- Hash changé → cache NOT réutilisé
- Nécessite nouvelle extraction

### 3. Changement Config Extraction

Cache créé avec config extraction spécifique.
Si changement majeur (ex: Vision ON → OFF), **recommencer extraction**.

---

## 🔍 Monitoring

### Vérifier Caches Disponibles

```bash
# Lister caches
ls -lh data/extraction_cache/

# Vérifier expiration
find data/extraction_cache/ -name "*.knowcache.json" -mtime +30
```

### Purge Caches Expirés

```bash
# Auto-purge (via code)
# Appelé automatiquement au boot worker

# Purge manuelle
find data/extraction_cache/ -name "*.knowcache.json" -mtime +30 -delete
```

### Statistiques Cache

```bash
# Nombre de caches
ls data/extraction_cache/*.knowcache.json | wc -l

# Taille totale
du -sh data/extraction_cache/

# Économies estimées
# (nombre_caches × $0.18 moyen par extraction)
```

---

## 📊 Impact Attendu

### Développement OSMOSE

**Avant Cache:**
- 10 tests/jour × 90s = **15 min/jour**
- 10 tests × $0.18 = **$1.80/jour**

**Avec Cache:**
- 1 extraction initiale (90s, $0.18)
- 9 réimports cache (72s total, $0)
- **Total: 162s (~2.7min), $0.18**

**Économie: -82% temps, -90% coût**

### Tests Régression

**Avant Cache:**
- 50 documents × 90s = **4,500s (~75 min)**
- 50 documents × $0.18 = **$9.00**

**Avec Cache:**
- Première exécution: 75 min, $9.00
- Exécutions suivantes: **~3 min, $0.00**

**Économie sur 10 exécutions: -96% temps, -90% coût**

---

## ✅ Checklist Utilisation

**Phase 1: Création Caches**
- [ ] Importer documents normalement (PDF/PPTX)
- [ ] Vérifier caches créés: `ls data/extraction_cache/`
- [ ] Télécharger caches si besoin (backup)

**Phase 2: Tests Itératifs**
- [ ] Modifier config OSMOSE selon besoins
- [ ] Uploader fichiers `.knowcache.json`
- [ ] Vérifier logs: `[CACHE] ✅ Cache loaded`
- [ ] Analyser résultats OSMOSE

**Phase 3: Production**
- [ ] Désactiver cache si besoin (`ENABLE_EXTRACTION_CACHE=false`)
- [ ] Ou conserver pour tests régression
- [ ] Purger caches expirés périodiquement

---

## 🎓 Bonnes Pratiques

### DO ✅

- Créer caches pour documents test récurrents
- Versionner caches importants (git LFS ou backup S3)
- Utiliser caches pour tests unitaires/intégration
- Nommer explicitement caches: `Test_Suite_Doc1.knowcache.json`

### DON'T ❌

- Ne PAS éditer manuellement `.knowcache.json` (corruption)
- Ne PAS partager caches contenant données sensibles
- Ne PAS réutiliser cache si document source modifié
- Ne PAS bypasser extraction pour documents production nouveaux

---

## 🔗 Références

- **Module Cache**: `src/knowbase/ingestion/extraction_cache.py`
- **Configuration**: `.env` (variables `EXTRACTION_CACHE_*`)
- **Intégration Pipeline**: `pdf_pipeline.py`, `pptx_pipeline.py`

---

**Dernière mise à jour:** 2025-10-17
**Version système:** V2.2 (Extraction Cache + Density Detection)
