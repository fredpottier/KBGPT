# Phase 1.5 - Recommandations & Actions Concrètes

**Date**: 2025-10-16
**Version**: 1.0.0
**Statut**: 🔴 **ACTIONS REQUISES POUR GO/NO-GO**

---

## 🎯 Priorité P0 - Actions Bloquantes GO/NO-GO

### Action 1: Préparer Corpus Test Pilote Scénario A

**Status**: 🔴 **BLOQUEUR - EN ATTENTE**
**Urgence**: CRITIQUE
**Deadline**: Avant exécution pilote

**Tâches**:
1. Préparer 50 PDF textuels simples dans `data/pilot_docs/`
   - Sources recommandées:
     - Documentation SAP officielle (10-15 docs)
     - Product datasheets (10-15 docs)
     - Technical specifications (10-15 docs)
     - Training materials (10-15 docs)
   - Critères documents:
     - Textual content (pas de tables/images complexes)
     - 5-10 pages/doc (~250 pages total)
     - Mix EN/FR si possible (validation multilingue)

2. Créer répertoire si nécessaire:
   ```bash
   mkdir -p data/pilot_docs
   ```

3. Copier documents dans répertoire:
   ```bash
   cp /path/to/source/*.pdf data/pilot_docs/
   ```

**Effort**: 1-2 heures (collecte + organisation)

---

### Action 2: Installer Dépendances Worker Docker

**Status**: 🟡 **BLOQUEUR DÉPLOIEMENT**
**Urgence**: HAUTE
**Deadline**: Avant exécution pilote

**Problème**: `sentence-transformers` + `networkx` non installés dans worker → cascade hybride inactive

**Solution**:

**Option A: Installation directe (rapide)**:
```bash
# Terminal 1: Installer dépendances
docker-compose exec ingestion-worker pip install sentence-transformers==2.2.2 networkx==3.1

# Terminal 2: Redémarrer worker
docker-compose restart ingestion-worker

# Terminal 3: Vérifier logs de démarrage
docker-compose logs -f ingestion-worker | grep "GATEKEEPER\|GraphCentrality\|Embeddings"
```

**Logs attendus (succès)**:
```
[GATEKEEPER] GraphCentralityScorer initialisé
[GATEKEEPER] EmbeddingsContextualScorer initialisé
[GATEKEEPER] Initialized with default profile 'BALANCED' (contextual_filtering=ON)
```

**Option B: Modification requirements.txt (propre)**:
```bash
# 1. Modifier requirements.txt
echo "sentence-transformers==2.2.2" >> requirements.txt
echo "networkx==3.1" >> requirements.txt

# 2. Rebuild worker
docker-compose build ingestion-worker

# 3. Redémarrer stack
docker-compose up -d
```

**Effort**: 30 minutes - 1 heure

---

### Action 3: Exécuter Pilote Scénario A

**Status**: ⏳ **EN ATTENTE (Actions 1-2 complétées)**
**Urgence**: CRITIQUE
**Deadline**: Avant GO/NO-GO Phase 2

**Pré-requis**:
- [x] Action 1 complétée (50 PDF dans `data/pilot_docs/`)
- [x] Action 2 complétée (dépendances worker installées)
- [x] Services Docker actifs (Redis, Neo4j, Qdrant)

**Commandes**:

```bash
# 1. Vérifier services actifs
docker-compose ps

# 2. Exécuter pilote
python scripts/pilot_scenario_a.py data/pilot_docs --max-documents 50

# 3. Suivre progression (Terminal 2)
docker-compose logs -f ingestion-worker | grep "OSMOSE\|GATEKEEPER\|SUPERVISOR"
```

**Durée estimée**: 25-40 minutes (30s/doc × 50 docs)

**Résultats attendus**:
- CSV: `pilot_scenario_a_results.csv` (détails par document)
- Logs: Stats agrégées + validation critères
- Console: Validation GO/NO-GO automatique

---

### Action 4: Analyser Résultats Pilote A

**Status**: ⏳ **EN ATTENTE (Action 3 complétée)**
**Urgence**: CRITIQUE
**Deadline**: Même jour que Action 3

**Tâches**:

**1. Vérifier CSV résultats**:
```bash
# Ouvrir CSV
cat pilot_scenario_a_results.csv

# Statistiques rapides
python -c "
import pandas as pd
df = pd.read_csv('pilot_scenario_a_results.csv')
print('Total docs:', len(df))
print('Success rate:', df['success'].mean())
print('Avg cost/doc:', df['cost'].mean())
print('P95 duration:', df['duration_seconds'].quantile(0.95))
print('Avg promotion rate:', df['promotion_rate'].mean())
"
```

**2. Vérifier logs console**:
```
=== Results ===
Total documents: 50
Successful: 48
Failed: 2
Total cost: $10.50
Avg cost/doc: $0.22
Median cost/doc: $0.21
P95 duration: 28.5s
P99 duration: 32.1s
Avg promotion rate: 35.2%

=== Criteria Validation ===
Cost target: ✅ PASS ($0.22 < $0.25)
Performance P95: ✅ PASS (28.5s < 30s)
Promotion rate: ✅ PASS (35.2% > 30%)
```

**3. Vérifier 8 critères GO/NO-GO**:

| Critère | Cible | Résultat | Status |
|---------|-------|----------|--------|
| Cost target | ≤ $0.25/doc | $X.XX | ✅/❌ |
| Processing time P95 | < 30s | X.Xs | ✅/❌ |
| Promotion rate | ≥ 30% | XX% | ✅/❌ |
| Rate limit violations | 0 | X | ✅/❌ |
| Circuit breaker trips | 0 | X | ✅/❌ |
| Multi-tenant isolation | 100% | X% | ✅/❌ |
| Budget caps respected | Oui | Oui/Non | ✅/❌ |
| Graceful degradation | Oui | Oui/Non | ✅/❌ |

**Décision**:
- ✅ **GO Phase 2**: Si ≥ 6/8 critères validés
- ❌ **NO-GO**: Si < 6/8 critères validés → Optimisation Phase 1.5

**Effort**: 2-3 heures (analyse + rapport)

---

## 🟢 Priorité P1 - Améliorations Production

### Action 5: Archiver Rapports Journaliers Complétés

**Status**: 🟢 **NON BLOQUANT**
**Urgence**: BASSE
**Deadline**: Avant Phase 2

**Tâches**:

```bash
# 1. Créer répertoire archive
mkdir -p doc/archive/feat-neo4j-native/phase1.5/

# 2. Déplacer rapports journaliers complétés
mv doc/phase1_osmose/PHASE1.5_DAY4_INFRASTRUCTURE_REPORT.md \
   doc/archive/feat-neo4j-native/phase1.5/

mv doc/phase1_osmose/PHASE1.5_DAY5_REPORT.md \
   doc/archive/feat-neo4j-native/phase1.5/

mv doc/phase1_osmose/PHASE1.5_DAY6_BEST_PRACTICES_INTEGRATION_REPORT.md \
   doc/archive/feat-neo4j-native/phase1.5/

mv doc/phase1_osmose/PHASE1.5_DAYS7-9_CONTEXTUAL_FILTERING_REPORT.md \
   doc/archive/feat-neo4j-native/phase1.5/

# 3. Commit
git add doc/archive/feat-neo4j-native/phase1.5/
git commit -m "docs(phase1.5): Archiver rapports journaliers (Jours 4-9)"
```

**Résultat**: Réduction duplication documentation, référence unique = PHASE1.5_TRACKING_V2.md

**Effort**: 15 minutes

---

### Action 6: Supprimer Fichiers Obsolètes

**Status**: 🟢 **NON BLOQUANT**
**Urgence**: BASSE
**Deadline**: Avant Phase 2

**Tâches**:

```bash
# 1. Supprimer fichiers obsolètes
rm doc/phase1_osmose/READINESS_ANALYSIS_FOR_FIRST_TEST.md  # Remplacé par CRITICAL_PATH
rm doc/phase1_osmose/IMPLEMENTATION_STATUS_CLARIFICATION.md  # Consolidé dans TRACKING_V2
rm doc/phase1_osmose/ANALYSE_PROBLEMES_NEO4J_CONCEPTS.md    # Problèmes résolus Jour 11

# 2. Commit
git add doc/phase1_osmose/
git commit -m "docs(phase1.5): Supprimer fichiers obsolètes (remplacés/résolus)"
```

**Effort**: 10 minutes

---

### Action 7: Créer Dashboard Grafana 10 KPIs (Semaine 12)

**Status**: 🟡 **À VENIR**
**Urgence**: MOYENNE
**Deadline**: Semaine 12 (après Pilote A)

**Pré-requis**:
- [ ] Pilote A complété
- [ ] GO Phase 1.5 validé

**Tâches**:

**1. Setup Grafana**:
```bash
# docker-compose.yml (ajouter service)
grafana:
  image: grafana/grafana:latest
  ports:
    - "3001:3000"
  volumes:
    - grafana-storage:/var/lib/grafana
    - ./config/grafana:/etc/grafana/provisioning
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
```

**2. Créer 10 KPIs**:
1. **Cost per document** (avg, median, P95)
2. **Processing time** (avg, median, P95, P99)
3. **LLM calls distribution** (NO_LLM, SMALL, BIG, VISION)
4. **Promotion rate** (avg, min, max)
5. **Budget remaining** (SMALL, BIG, VISION)
6. **Concepts extracted** (avg, total)
7. **Canonical concepts promoted** (avg, total)
8. **Rate limit violations** (count, last 24h)
9. **Circuit breaker trips** (count, last 24h)
10. **Error rate** (%, sliding window)

**3. Data Sources**:
- Redis (budgets, quotas)
- PostgreSQL (résultats pilote)
- Prometheus (métriques Docker)

**Effort**: 2-3 jours

---

## 📅 Planning Semaine 11 Fin - Semaine 13

### Semaine 11 Fin (Jour 12 - Aujourd'hui/Demain)

**Matin (3-4h)**:
- [x] ✅ Action 1: Préparer 50 PDF test (1-2h)
- [x] ✅ Action 2: Installer dépendances worker (30min-1h)
- [x] ✅ Action 3: Exécuter Pilote Scénario A (25-40 min)

**Après-midi (2-3h)**:
- [x] ✅ Action 4: Analyser résultats Pilote A (2-3h)
- [x] ✅ Décision GO/NO-GO Phase 1.5

---

### Semaine 12 (Jours 13-14)

**Si GO Phase 1.5**:

**Jour 13 (Pilote B)**:
- [ ] Préparer 30 PDF complexes (multi-column, tables)
- [ ] Exécuter Pilote B
- [ ] Analyser résultats Pilote B

**Jour 14 (Pilote C + Dashboard)**:
- [ ] Préparer 20 PPTX (images, slides)
- [ ] Exécuter Pilote C
- [ ] Analyser résultats Pilote C
- [ ] Début dashboard Grafana

**Si NO-GO Phase 1.5**:
- [ ] Analyser causes échec critères
- [ ] Optimisation budgets (ajustement seuils routing)
- [ ] Optimisation performance (bottlenecks)
- [ ] Re-exécution Pilote A (après optimisations)

---

### Semaine 13 (Jour 15)

**Objectifs**:
- [ ] Analyse résultats pilotes (A, B, C)
- [ ] Rapport technique 20 pages
- [ ] Validation 8 critères de succès (finale)
- [ ] Décision GO/NO-GO Phase 2 (finale)
- [ ] Présentation stakeholders

**Deliverables**:
- [ ] `PHASE1.5_FINAL_REPORT.pdf` (20 pages)
- [ ] `PHASE1.5_PILOT_RESULTS.xlsx` (métriques détaillées)
- [ ] `PHASE1.5_DECISION_GO_NOGO.md` (justification décision)
- [ ] Présentation PowerPoint (15-20 slides)

---

## 🚨 Alertes & Points d'Attention

### Alerte 1: Budget Caps Trop Restrictifs

**Symptômes**:
- Documents complexes épuisent budget BIG (8 calls/doc)
- Fallback SMALL donne résultats qualité inférieure
- Promotion rate < 30%

**Solutions**:
1. Augmenter cap BIG: 8 → 12 calls/doc
2. Ajuster seuils routing: 3/8 → 3/10 entities
3. Activer mode PERMISSIVE (min_confidence: 0.60)

**Fichier**: `config/agents/budget_limits.yaml`

---

### Alerte 2: Rate Limit Violations (429 Errors)

**Symptômes**:
- Logs: `[DISPATCHER] Rate limit exceeded, waiting...`
- Latence excessive (>1 min/doc)
- Circuit breaker trips

**Solutions**:
1. Réduire concurrency: 10 → 5 calls simultanées
2. Augmenter timeout: 120s → 180s
3. Activer priority queue P0 (RETRY) en priorité

**Fichier**: `src/knowbase/agents/dispatcher/dispatcher.py`

---

### Alerte 3: Neo4j Doublons Persistent

**Symptômes**:
- Query: `MATCH (c:CanonicalConcept {canonical_name: "X"}) RETURN count(c)` → > 1
- Relations dupliquées

**Solutions**:
1. Vérifier paramètre `deduplicate=True` dans `promote_to_published()`
2. Exécuter cleanup manuel:
   ```cypher
   // Trouver doublons
   MATCH (c:CanonicalConcept)
   WITH c.canonical_name AS name, c.tenant_id AS tenant, collect(c) AS concepts
   WHERE size(concepts) > 1
   RETURN name, tenant, size(concepts)

   // Merger doublons (manuel, choisir canonical_id)
   MATCH (old:CanonicalConcept {canonical_name: "X", tenant_id: "Y"})
   MATCH (new:CanonicalConcept {canonical_name: "X", tenant_id: "Y"})
   WHERE id(old) < id(new)
   MATCH (proto:ProtoConcept)-[r:PROMOTED_TO]->(old)
   CREATE (proto)-[:PROMOTED_TO {deduplication: true}]->(new)
   DELETE r
   DELETE old
   ```

---

## 📞 Contact & Support

### Escalade Problèmes

**P0 - Bloqueurs**: Contacter immédiatement équipe OSMOSE
**P1 - Urgents**: Slack #osmose-dev
**P2 - Non critiques**: Issue GitHub

### Ressources Utiles

**Documentation**:
- Architecture: `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`
- Roadmap: `doc/OSMOSE_ROADMAP_INTEGREE.md`
- Tracking: `doc/phase1_osmose/PHASE1.5_TRACKING_V2.md`
- Executive Summary: `doc/phase1_osmose/PHASE1.5_EXECUTIVE_SUMMARY.md`

**Tests Locaux**:
- Tests unitaires: `pytest tests/agents/`
- Tests E2E: `pytest tests/integration/ -m slow`
- Tests Redis: `pytest tests/common/clients/test_redis_client.py`

**Logs Utiles**:
```bash
# Worker ingestion
docker-compose logs -f ingestion-worker | grep "OSMOSE\|GATEKEEPER\|SUPERVISOR"

# Neo4j
docker-compose logs -f knowbase-neo4j

# Redis
docker-compose logs -f redis

# Qdrant
docker-compose logs -f qdrant
```

---

## ✅ Checklist Actions Prioritaires

### Aujourd'hui (Jour 12)
- [ ] Action 1: Préparer 50 PDF test (1-2h)
- [ ] Action 2: Installer dépendances worker (30min-1h)
- [ ] Action 3: Exécuter Pilote Scénario A (25-40 min)
- [ ] Action 4: Analyser résultats Pilote A (2-3h)
- [ ] Décision GO/NO-GO Phase 1.5

### Cette Semaine (Jours 13-14)
- [ ] Si GO: Pilotes B&C + Dashboard Grafana
- [ ] Si NO-GO: Optimisations + Re-exécution Pilote A

### Semaine Prochaine (Jour 15)
- [ ] Analyse finale + Rapport 20 pages
- [ ] Décision GO/NO-GO Phase 2
- [ ] Présentation stakeholders

### Nettoyage (Non bloquant)
- [ ] Action 5: Archiver rapports journaliers (15 min)
- [ ] Action 6: Supprimer fichiers obsolètes (10 min)

---

**Dernière mise à jour**: 2025-10-16
**Version**: 1.0.0
**Auteur**: Claude Code + Équipe OSMOSE
**Status**: 🔴 **ACTIONS REQUISES POUR GO/NO-GO**
