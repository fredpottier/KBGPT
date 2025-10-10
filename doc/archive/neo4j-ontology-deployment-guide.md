# Guide Déploiement : Système Ontologies Neo4j

**Date** : Janvier 2025
**Version** : 1.0
**Statut** : ✅ Production Ready

---

## 📋 Vue d'ensemble

Migration complète du système d'ontologies de fichiers YAML statiques vers Neo4j pour :
- ✅ Support types d'entités dynamiques
- ✅ Scalabilité illimitée (vs limite ~15K entités YAML)
- ✅ Lookup O(1) via index Neo4j (<2ms)
- ✅ Boucle feedback fermée (auto-save après normalisation LLM)
- ✅ Correction automatique des types d'entités

---

## 🎯 État Actuel

### Ontologies Migrées
```
COMPONENT      : 4 entités (yaml_migrated)
CONCEPT        : 5 entités (yaml_migrated)
ORGANIZATION   : 4 entités (yaml_migrated)
PERSON         : 3 entités (yaml_migrated)
SOLUTION       : 38 entités (yaml_migrated)
TECHNOLOGIE    : 6 entités (yaml_migrated)
---
TOTAL          : 60 entités, 208 aliases
```

### Tests Validés
```
✓ Tests unitaires normalizer  : 8/8 passed (1.97s)
✓ Tests ontology_saver         : 2/2 passed (1.73s)
✓ Tests intégration pipeline   : 5/5 passed (33.09s)
---
TOTAL                          : 15/15 passed ✅
```

### Commits Implémentation
```
3bf1f67 - Phase 1: Schéma Neo4j (contraintes, index)
22f5776 - Phase 2: Migration YAML → Neo4j (60 entités)
6e3fc13 - Phase 3: EntityNormalizerNeo4j (lookup O(1))
89e8242 - Phase 4: Intégration pipeline (KnowledgeGraphService)
837f8b4 - Phase 5: Auto-save ontologies (boucle feedback)
```

---

## 🚀 Déploiement Production

### Prérequis

1. **Backup Complet**
```bash
# 1. Backup Neo4j
docker compose exec neo4j neo4j-admin database dump neo4j --to-path=/backups
docker compose cp neo4j:/backups/neo4j.dump ./backups/neo4j_pre_deployment_$(date +%Y%m%d).dump

# 2. Backup YAML (si rollback nécessaire)
tar -czf backups/ontologies_yaml_$(date +%Y%m%d).tar.gz config/ontologies/

# 3. Backup SQLite
cp data/entity_types_registry.db backups/entity_types_registry_$(date +%Y%m%d).db
```

2. **Tag Git Rollback Point**
```bash
git tag -a v1.0-pre-neo4j-ontology -m "Point de rollback avant déploiement ontologies Neo4j"
```

### Étape 1 : Merge Branch

```bash
# 1. Vérifier branche actuelle
git branch

# 2. Merge feat/neo4j-native dans main
git checkout main
git merge feat/neo4j-native

# 3. Vérifier pas de conflits
git status
```

### Étape 2 : Rebuild Containers

```bash
# 1. Rebuild app et worker (nouveau code ontology)
docker-compose build app ingestion-worker

# 2. Restart services
docker-compose up -d app ingestion-worker

# 3. Vérifier logs
docker-compose logs -f app | grep "ontology"
```

### Étape 3 : Validation Post-Déploiement

```bash
# 1. Vérifier ontologies chargées
docker compose exec neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "MATCH (ont:OntologyEntity) RETURN ont.entity_type, count(*) ORDER BY ont.entity_type"

# 2. Tester normalisation
curl -X POST http://localhost:8000/test-normalizer \
  -H "Content-Type: application/json" \
  -d '{"name": "SuccessFactors", "entity_type": "SOLUTION"}'

# 3. Vérifier auto-save (importer 1 document test)
# Observer logs worker pour "✅ Ontologie sauvegardée"
docker-compose logs -f ingestion-worker | grep "Ontologie"
```

---

## 🔄 Rollback

Si problèmes détectés, rollback immédiat possible.

### Option 1 : Rollback Git (Recommandé)

```bash
# 1. Revenir au tag pré-déploiement
git checkout v1.0-pre-neo4j-ontology

# 2. Rebuild containers avec ancien code
docker-compose build app ingestion-worker
docker-compose up -d app ingestion-worker

# 3. Vérifier normalizer YAML actif
docker-compose logs app | grep "entity_normalizer"
```

### Option 2 : Rollback Neo4j (Si données corrompues)

```bash
# 1. Arrêter Neo4j
docker-compose stop neo4j

# 2. Restaurer dump
docker compose cp ./backups/neo4j_pre_deployment_YYYYMMDD.dump neo4j:/backups/
docker compose exec neo4j neo4j-admin database load neo4j --from-path=/backups

# 3. Redémarrer
docker-compose start neo4j
```

### Option 3 : Rollback Partiel (Garder données, revenir YAML)

```bash
# 1. Modifier KnowledgeGraphService pour utiliser ancien normalizer
sed -i 's/from knowbase.ontology.entity_normalizer_neo4j/from knowbase.common.entity_normalizer/' \
  src/knowbase/api/services/knowledge_graph_service.py

sed -i 's/get_entity_normalizer_neo4j(self.driver)/get_entity_normalizer()/' \
  src/knowbase/api/services/knowledge_graph_service.py

# 2. Rebuild
docker-compose build app ingestion-worker
docker-compose up -d app ingestion-worker
```

---

## 📊 Monitoring

### Vérifications Quotidiennes

```bash
# 1. Compter ontologies créées aujourd'hui
docker compose exec neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "MATCH (ont:OntologyEntity)
   WHERE ont.created_at >= datetime() - duration('P1D')
   RETURN ont.source, count(*) AS created_today"

# 2. Vérifier lookup performance
docker compose exec neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "PROFILE MATCH (alias:OntologyAlias {normalized: 'successfactors'})
   RETURN alias LIMIT 1"
# Doit utiliser ont_alias_normalized_idx (index seek)

# 3. Détecter orphelins (ne devrait pas exister)
docker compose exec neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "MATCH (ont:OntologyEntity)
   WHERE NOT (ont)-[:HAS_ALIAS]->()
   RETURN count(ont) AS orphans"
# Résultat attendu: orphans = 0
```

### Alertes

**⚠️ Déclencher alerte si** :
- `orphans > 0` → Ontologies sans aliases (intégrité)
- Lookup > 10ms → Index Neo4j dégradé
- Auto-save échecs répétés → Logs worker

---

## 🐛 Troubleshooting

### Problème 1 : Normalisation ne fonctionne pas

**Symptômes** : Toutes entités `status=pending`, aucune `status=validated`

**Diagnostic** :
```bash
# Vérifier normalizer chargé
docker-compose logs app | grep "EntityNormalizerNeo4j"

# Vérifier connexion Neo4j
docker-compose exec app python -c "
from knowbase.ontology.entity_normalizer_neo4j import get_entity_normalizer_neo4j
normalizer = get_entity_normalizer_neo4j()
print(normalizer.normalize_entity_name('SuccessFactors', 'SOLUTION'))
"
```

**Solution** :
- Si erreur connexion → Vérifier NEO4J_URI, NEO4J_PASSWORD dans .env
- Si normalizer None → Rebuild app container

### Problème 2 : Auto-save échoue

**Symptômes** : Logs `⚠️ Erreur sauvegarde ontologie Neo4j`

**Diagnostic** :
```bash
# Vérifier logs worker
docker-compose logs ingestion-worker | grep "ontologie"

# Tester manuellement
docker-compose exec app python -c "
from knowbase.ontology.ontology_saver import save_ontology_to_neo4j
merge_groups = [{'canonical_key': 'TEST', 'canonical_name': 'Test', 'confidence': 0.9, 'entities': [{'name': 'Test'}]}]
save_ontology_to_neo4j(merge_groups, 'TEST_TYPE')
"
```

**Solution** :
- Si erreur contrainte → Doublon entity_id, utiliser MERGE au lieu de CREATE
- Si erreur permissions → Vérifier Neo4j user a write access

### Problème 3 : Lookup lent

**Symptômes** : Normalisation prend >100ms par entité

**Diagnostic** :
```bash
# Vérifier index utilisé
docker compose exec neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "PROFILE MATCH (alias:OntologyAlias {normalized: 'test'}) RETURN alias"
```

**Solution** :
- Si "NodeByLabelScan" au lieu de "NodeIndexSeek" → Index manquant
- Recréer index :
```bash
docker compose exec neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "CREATE INDEX ont_alias_normalized_idx IF NOT EXISTS
   FOR (alias:OntologyAlias) ON (alias.normalized)"
```

---

## 📈 Performance Attendue

### Normalisation
- **YAML (ancien)** : 4.8s startup, 0.56 µs/lookup @ 10K entités
- **Neo4j (nouveau)** : <50ms startup, <2ms/lookup, scalabilité infinie

### Auto-Save
- **Sauvegarde** : ~10ms par groupe (5 entités)
- **Non-bloquant** : Erreur ne fail pas le job normalisation

### Impact Production
- **Ingestion** : Aucun ralentissement observable
- **Mémoire** : -100MB (pas de chargement YAML en RAM)
- **CPU** : Identique (Neo4j index tree traversal optimisé)

---

## ✅ Checklist Déploiement Final

```markdown
Avant déploiement:
- [ ] Backup Neo4j créé
- [ ] Backup YAML créé
- [ ] Backup SQLite créé
- [ ] Tag Git rollback créé
- [ ] Tests 15/15 passent
- [ ] Documentation lue

Après déploiement:
- [ ] Services app + worker redémarrés
- [ ] Ontologies visibles dans Neo4j (60+)
- [ ] Test normalisation manuel OK
- [ ] Logs pas d'erreurs
- [ ] Import document test OK
- [ ] Auto-save fonctionnel

Monitoring J+1:
- [ ] Lookup performance <10ms
- [ ] Orphans = 0
- [ ] Auto-save créations visibles
- [ ] Aucune régression ingestion
```

---

## 📞 Support

**En cas de problème critique** :
1. Rollback Git immédiat (`git checkout v1.0-pre-neo4j-ontology`)
2. Rebuild containers
3. Analyser logs (`docker-compose logs app ingestion-worker`)
4. Consulter ce guide troubleshooting

**Références** :
- Guide implémentation : `doc/implementation-neo4j-ontology-guide.md`
- Architecture : `doc/architecture-ontology-neo4j-analysis.md`
- Commits : `feat/neo4j-native` branch

---

**Version** : 1.0
**Dernière mise à jour** : 2025-01-10
**Statut** : ✅ Production Ready
