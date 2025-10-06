# Prochaines Étapes - Phase 1 Complétée à 87.5%

**Date** : 2025-10-06
**Statut** : ✅ Phase 1 quasi-complète (7/8 tâches)

---

## 🎯 Ce Qui a Été Fait

### ✅ Complété (7 tâches)
1. **Audit sécurité complet** - `doc/SECURITY_AUDIT_DYNAMIC_TYPES.md` (40+ pages)
2. **Validation regex types** - Protection injection Cypher/XSS/path-traversal
3. **Champs status/is_cataloged** - Schémas Pydantic mis à jour
4. **Entity normalizer adapté** - Retourne `is_cataloged` boolean
5. **Service Neo4j** - Stocke `status`/`is_cataloged` dans graphe
6. **API /entities/pending** - Liste entités non cataloguées
7. **Tests sécurité** - 19/19 tests PASS ✅

### ⏳ Restant (1 tâche)
8. **Tests intégration API** - Nécessite rebuild Docker

---

## 🚀 Actions Immédiates

### 1. Rebuild Docker Worker (OBLIGATOIRE)

Les modifications code doivent être appliquées dans le container :

```bash
# Rebuild image worker avec nouveau code
docker compose -f docker-compose.yml build ingestion-worker

# Redémarrer worker
docker compose -f docker-compose.yml restart ingestion-worker

# Vérifier démarrage OK
docker compose logs ingestion-worker --tail 50
```

### 2. Rebuild App (Optionnel mais Recommandé)

Si tu veux tester l'API `/entities/pending` immédiatement :

```bash
# Rebuild API backend
docker compose -f docker-compose.yml build app

# Redémarrer API
docker compose -f docker-compose.yml restart app

# Vérifier API disponible
curl http://localhost:8000/docs
```

### 3. Purge Databases (Pour Test Propre)

**⚠️ ATTENTION** : Supprime toutes les données Neo4j + Qdrant

```bash
# Script Windows
scripts\clean_all_databases.cmd

# OU manuellement
docker compose exec -T neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass "MATCH (n) DETACH DELETE n"
docker compose exec -T qdrant curl -X DELETE http://localhost:6333/collections/knowbase/points?wait=true -d '{"filter":{"must":[{"key":"tenant_id","match":{"value":"default"}}]}}'
```

### 4. Test Import Document

Import un document pour valider le workflow complet :

1. **Via Frontend** : http://localhost:3000/documents/import
2. **Uploader un PPTX** avec entités variées (solutions SAP + infrastructure)
3. **Attendre fin import**
4. **Vérifier logs** :
```bash
docker compose logs ingestion-worker -f
```

**Rechercher dans logs** :
- ✅ `✅ Entité normalisée via catalogue` - Entités cataloguées (status=validated)
- ⚠️ `⚠️ Entité non cataloguée` - Entités pending (status=pending)
- ✅ `status=validated` ou `status=pending` dans logs

### 5. Tester API /entities/pending

```bash
# Lister toutes les entités pending
curl http://localhost:8000/api/entities/pending

# Filtrer par type INFRASTRUCTURE
curl "http://localhost:8000/api/entities/pending?entity_type=INFRASTRUCTURE"

# Avec pagination
curl "http://localhost:8000/api/entities/pending?limit=10&offset=0"

# Liste types découverts
curl http://localhost:8000/api/entities/types/discovered
```

**Résultat Attendu** :
```json
{
  "entities": [
    {
      "uuid": "...",
      "name": "Azure VNET",
      "entity_type": "INFRASTRUCTURE",
      "status": "pending",
      "is_cataloged": false,
      "created_at": "2025-10-06T...",
      "source_document": "proposal.pptx",
      "source_slide_number": 45
    }
  ],
  "total": 523,
  "entity_type_filter": "INFRASTRUCTURE"
}
```

### 6. Vérifier Neo4j

Interface Neo4j Browser : http://localhost:7474

```cypher
// Compter entités par status
MATCH (e:Entity {tenant_id: 'default'})
RETURN e.status AS status, count(e) AS count
ORDER BY count DESC;

// Lister entités pending INFRASTRUCTURE
MATCH (e:Entity {tenant_id: 'default'})
WHERE e.status = 'pending' AND e.entity_type = 'INFRASTRUCTURE'
RETURN e.name, e.is_cataloged, e.created_at
LIMIT 10;

// Voir types découverts
MATCH (e:Entity {tenant_id: 'default'})
WITH e.entity_type AS type, count(e) AS total
RETURN type, total
ORDER BY total DESC;
```

---

## 📋 Checklist Validation Phase 1

### Tests Fonctionnels
- [ ] Rebuild Docker worker complété sans erreurs
- [ ] Import document réussit
- [ ] Logs montrent mix `status=validated` et `status=pending`
- [ ] API `/entities/pending` retourne entités non cataloguées
- [ ] API `/entities/types/discovered` liste types avec comptages
- [ ] Neo4j contient propriétés `status` et `is_cataloged`

### Tests Sécurité
- [x] 19/19 tests validation sécurité PASS ✅
- [ ] Types malveillants rejetés (ex: `SOLUTION' OR '1'='1`)
- [ ] Noms XSS rejetés (ex: `<script>alert(1)</script>`)
- [ ] Préfixes système rejetés (ex: `SYSTEM_CONFIG`)

### Tests Performance
- [ ] Import document standard (50 slides) < 5min
- [ ] API `/entities/pending` (1000 entités) < 500ms
- [ ] Normalisation 1000 entités < 1s

---

## 🐛 Troubleshooting

### Erreur : "Module entities not found"

**Symptôme** :
```
ImportError: cannot import name 'entities' from 'knowbase.api.routers'
```

**Solution** :
```bash
# Vérifier fichier existe
ls src/knowbase/api/routers/entities.py

# Rebuild app
docker compose build app && docker compose restart app
```

### Erreur : "Field status not found in Neo4j"

**Symptôme** :
```
KeyError: 'status'
```

**Solution** :
Entités créées AVANT modification → backward compatibility active
- Anciennes entités : `status` défaut `"pending"`, `is_cataloged` défaut `False`
- Nouvelles entités : valeurs définies automatiquement

### Erreur : "ValidationError entity_type must be UPPERCASE"

**Symptôme** :
```
pydantic.ValidationError: entity_type must be UPPERCASE alphanumeric
```

**Cause** : LLM retourne type invalide (ex: `infrastructure` lowercase, `SOLUTION-TYPE` avec tiret)

**Solution** : Code normalise automatiquement en UPPERCASE. Si erreur persiste, vérifier prompt LLM.

---

## 📊 Métriques Attendues Après Import

### Entités
- **Total entités** : 150-200 (selon document)
- **Status validated** : 60-70% (entités cataloguées)
- **Status pending** : 30-40% (entités non cataloguées)

### Types Découverts
- **Types bootstrap** : SOLUTION, COMPONENT, TECHNOLOGY, ORGANIZATION, PERSON, CONCEPT
- **Types nouveaux** : INFRASTRUCTURE, NETWORK, DATABASE, etc.

### API Performance
- GET `/entities/pending` : < 200ms (100 entités)
- GET `/entities/types/discovered` : < 100ms

---

## 🔄 Si Problème Majeur - Rollback

```bash
# Revenir au code précédent (avant Phase 1)
git stash

# Rebuild containers
docker compose build app ingestion-worker
docker compose restart app ingestion-worker

# Vérifier système fonctionne
curl http://localhost:8000/status
```

---

## 📞 Support

Si blocage :
1. Vérifier logs : `docker compose logs app ingestion-worker -f`
2. Lire `doc/PHASE1_COMPLETION_REPORT.md` (détails complets)
3. Lire `doc/SECURITY_AUDIT_DYNAMIC_TYPES.md` (sécurité)

---

## ✅ Validation Finale Phase 1

**Critères** :
- [x] Code écrit et testé (19/19 tests sécurité PASS)
- [ ] Docker rebuild sans erreurs
- [ ] Import document fonctionne avec mix status validated/pending
- [ ] API `/entities/pending` retourne données correctes
- [ ] Neo4j stocke `status` et `is_cataloged`

**Une fois validé → Continuer Phase 2** (PostgreSQL entity_types_registry)

---

**Temps Estimé Validation** : 30min - 1h
**Prochaine Phase** : Phase 2 (3-4h)
