# 🌊 OSMOSE - Scripts d'Administration

Scripts utilitaires pour gérer l'infrastructure OSMOSE Proto-KG.

## 📋 Scripts Disponibles

### `reset_proto_kg.py` - Reset Proto-KG

Script pour purger et réinitialiser le Proto-KG OSMOSE (Neo4j + Qdrant).

**Cas d'usage typiques** :
- Vous testez l'ingestion et voulez repartir de zéro
- Vous avez modifié le schéma et voulez le recréer
- Vous voulez nettoyer les données de développement

---

## 🚀 Usage

### Reset Complet (RECOMMANDÉ)

```bash
docker-compose exec app python scripts/reset_proto_kg.py
```

**Ce que ça fait** :
1. ✅ Supprime tous les CandidateEntity/CandidateRelation de Neo4j
2. ✅ Supprime la collection Qdrant `knowwhere_proto`
3. ✅ Recrée le schéma Neo4j (constraints + indexes)
4. ✅ Recrée la collection Qdrant

**Parfait pour** : Recommencer vos tests à zéro en gardant le schéma.

---

### Purge Données Seulement

```bash
docker-compose exec app python scripts/reset_proto_kg.py --data-only
```

**Ce que ça fait** :
- Supprime les données mais **garde** les constraints/indexes Neo4j

**Parfait pour** : Nettoyer rapidement sans recréer le schéma.

---

### Reset COMPLET (données + schéma)

```bash
docker-compose exec app python scripts/reset_proto_kg.py --full
```

**Ce que ça fait** :
1. Supprime toutes les données
2. Supprime **tous** les constraints Neo4j
3. Supprime **tous** les indexes Neo4j
4. Supprime la collection Qdrant
5. Recrée tout de A à Z

**Parfait pour** : Migration de schéma, ou si vous avez modifié les contraintes.

---

### Purge Sans Réinitialisation

```bash
docker-compose exec app python scripts/reset_proto_kg.py --skip-reinit
```

**Ce que ça fait** :
- Purge tout
- **Ne recrée rien**

**Parfait pour** : Debugging, ou si vous voulez recréer manuellement après.

---

## 🔧 Workflow Typique de Développement

### Scénario 1 : Tests d'Ingestion

```bash
# 1. Ingérer des documents
docker-compose exec app python -m knowbase.ingestion.process_document doc.pdf

# 2. Tester les résultats dans Neo4j/Qdrant
# ...

# 3. Purger et recommencer
docker-compose exec app python scripts/reset_proto_kg.py

# 4. Réingérer avec les modifications
docker-compose exec app python -m knowbase.ingestion.process_document doc.pdf
```

### Scénario 2 : Modification du Schéma

```bash
# 1. Modifier setup_infrastructure.py (ajouter index, etc.)

# 2. Purge complète + réinit
docker-compose exec app python scripts/reset_proto_kg.py --full

# 3. Vérifier que le nouveau schéma est OK
docker-compose exec app pytest tests/semantic/test_infrastructure.py
```

---

## ⚠️ Avertissements

- **ATTENTION** : Ces scripts **suppriment TOUTES les données** du Proto-KG
- En production, utilisez avec précaution (surtout `--full`)
- Les données du KG principal (hors Proto-KG) ne sont **pas affectées**
- Pensez à backup si vous avez des données importantes

---

## 🎓 Options Détaillées

| Option | Description | Use Case |
|--------|-------------|----------|
| *(aucune)* | Reset complet (données + reinit) | Usage quotidien, tests |
| `--data-only` | Garde le schéma, supprime les données | Nettoyage rapide |
| `--full` | Supprime schéma + données, puis reinit | Migration schéma |
| `--skip-reinit` | Purge sans recréer | Debugging avancé |

---

## 📊 Exemple de Sortie

```
======================================================================
🌊 OSMOSE Proto-KG - Reset
======================================================================

📋 Mode: PURGE DONNÉES

🗑️  Purge données Neo4j Proto-KG...
   ✅ 150 nodes supprimés (CandidateEntity/CandidateRelation)
🗑️  Purge collection Qdrant...
   ✅ Collection 'knowwhere_proto' supprimée

🔧 Réinitialisation infrastructure...
[OSMOSE] Setup Neo4j Proto-KG Schema...
  ✅ Constraint CandidateEntity.candidate_id créée
  ✅ Constraint CandidateRelation.candidate_id créée
  ... (6 constraints/indexes)

======================================================================
✅ Proto-KG réinitialisé avec succès !
======================================================================
```

---

## 🐛 Troubleshooting

### "Neo4j not available"
→ Vérifiez que Neo4j est démarré : `docker-compose ps neo4j`

### "Qdrant connection refused"
→ Vérifiez que Qdrant est démarré : `docker-compose ps qdrant`

### "Collection n'existe pas"
→ Normal si c'est la première fois, le script skip automatiquement

---

## 🔗 Voir Aussi

- `src/knowbase/semantic/setup_infrastructure.py` - Script d'initialisation
- `tests/semantic/test_infrastructure.py` - Tests infrastructure
- `config/osmose_semantic_intelligence.yaml` - Configuration OSMOSE
