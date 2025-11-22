# Scripts Utilitaires OSMOSE

Scripts pour gérer les données, exports/imports, et maintenance du système KnowWhere/OSMOSE.

## 🗑️ Purge Système Complète

Le script `purge_system.py` permet de purger TOUTES les données du système en une seule commande.

### Usage

```bash
# Depuis l'hôte (avec confirmation interactive)
python scripts/purge_system.py

# Depuis le conteneur
docker-compose exec app python scripts/purge_system.py

# Purge d'un tenant spécifique Neo4j
python scripts/purge_system.py --tenant myorg
```

### Ce qui est purgé

- ✅ **Redis** : TOUTES les clés (FLUSHDB) - queues d'imports, jobs RQ, cache
- ✅ **Qdrant** : Collections `knowbase` et `rfp_qa` complètement supprimées
- ✅ **Neo4j** : Tous les nodes du tenant `default` (ou spécifié)
- ✅ **Fichiers** : `data/docs_done/*` et `data/status/*.status`

### Ce qui est PRÉSERVÉ

- ⚠️ **Cache d'extraction** : `data/extraction_cache/*.knowcache.json` (JAMAIS touché)
- ⚠️ **Documents source** : `data/docs_in/*` (non purgés par défaut)
- ⚠️ **Schéma Neo4j** : Constraints et indexes (restent en place)

### Pourquoi ce script ?

Après une purge système, la queue Redis des imports terminés ne reflète plus la réalité des données en base. Ce script assure une purge **cohérente** de tous les composants.

---

## 📦 Scripts d'Export/Import de Documents

Ces scripts permettent de sauvegarder et restaurer des documents traités pour éviter de refaire les appels LLM coûteux.

## 🚀 Export d'un document traité

```bash
# Export simple
python scripts/export_document.py "RISE_with_SAP_Cloud_ERP_Private__20250927_154402"

# Export vers un répertoire spécifique
python scripts/export_document.py "SAP_BTP_-_Security_and_Compliance__20250926_163141" ./backups/

# Lister les documents disponibles
ls data/docs_done/
```

**Le script exporte automatiquement :**
- ✅ Le fichier PPTX/PDF original
- ✅ Le PDF généré (si PPTX → PDF)
- ✅ Toutes les images slides/thumbnails
- ✅ Tous les chunks Qdrant associés
- ✅ Les métadonnées Redis (statut import, etc.)

## 📥 Import d'un document depuis un ZIP

### Import d'un fichier unique
```bash
# Import simple
python scripts/import_document.py exports/document_export_20250927_143000.zip

# Import avec écrasement des fichiers existants
python scripts/import_document.py document_export.zip --force

# Simulation d'import (pour tester)
python scripts/import_document.py document_export.zip --dry-run
```

### Import de tous les ZIP du répertoire courant
```bash
# Import de tous les fichiers ZIP (avec confirmation)
python scripts/import_document.py

# Import de tous les fichiers ZIP avec écrasement
python scripts/import_document.py --force

# Simulation d'import de tous les fichiers ZIP
python scripts/import_document.py --dry-run
```

**Le script restaure automatiquement :**
- ✅ Le fichier dans `data/docs_done/`
- ✅ Le PDF dans `data/public/slides/`
- ✅ Les images dans `data/public/slides/` et `data/public/thumbnails/`
- ✅ Les chunks dans Qdrant
- ✅ Les métadonnées dans Redis

## 🔄 Workflow typique de test

### Test d'un document unique
1. **Sauvegarder un document traité :**
   ```bash
   python scripts/export_document.py "mon_document__20250927_154402"
   ```

2. **Purger pour test :**
   ```bash
   # Supprimer de Qdrant via l'interface ou API
   # Vider la queue Redis si nécessaire
   ```

3. **Restaurer après test :**
   ```bash
   python scripts/import_document.py exports/mon_document_export_20250927_154402.zip
   ```

### Test avec sauvegarde/restauration massive
1. **Sauvegarder tous les documents traités :**
   ```bash
   # Dans le répertoire exports/
   cd exports/
   for doc in $(python ../scripts/list_documents.py | grep "✅" | cut -d' ' -f2); do
       python ../scripts/export_document.py "$doc" .
   done
   ```

2. **Purger complètement :**
   ```bash
   # Vider Qdrant, Redis, etc.
   ```

3. **Restaurer tout :**
   ```bash
   cd exports/
   python ../scripts/import_document.py --force
   ```

## 📋 Structure du ZIP d'export

```
document_export_timestamp.zip
├── manifest.json              # Métadonnées de l'export
├── source/
│   └── document.pptx         # Fichier original
├── pdf/
│   └── document.pdf          # PDF généré
├── slides/
│   ├── document_slide_1.jpg  # Images slides
│   └── document_slide_2.jpg
├── thumbnails/
│   ├── document_slide_1.jpg  # Miniatures
│   └── document_slide_2.jpg
├── qdrant_chunks.json        # Export des chunks vectoriels
└── redis_metadata.json       # Métadonnées Redis
```

## ⚠️ Notes importantes

- **Nom de fichier** : Utilisez le nom sans extension (stem), par exemple `"document__20250927_154402"` et non `"document.pptx"`
- **Conflits** : Par défaut, l'import s'arrête si des fichiers existent. Utilisez `--force` pour écraser
- **Dry-run** : Utilisez `--dry-run` pour tester un import sans rien modifier
- **Logs** : Les logs détaillés sont dans `data/logs/export_debug.log` et `import_debug.log`

## 🛠️ Dépannage

### Export échoue
```bash
# Vérifier que le document existe
ls data/docs_done/ | grep "mon_document"

# Vérifier les logs
tail -f data/logs/export_debug.log
```

### Import échoue
```bash
# Vérifier le ZIP
python scripts/import_document.py mon_export.zip --dry-run

# Forcer l'import
python scripts/import_document.py mon_export.zip --force
```

### Services non disponibles
```bash
# Vérifier les services
docker-compose ps

# Vérifier Qdrant
curl http://localhost:6333/collections

# Vérifier Redis
docker-compose exec redis redis-cli ping
```