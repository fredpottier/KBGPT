# Dashboard OSMOSE Phase 1.8 - Extraction Metrics

Dashboard Grafana dédié au monitoring de la Phase 1.8 (LLM Hybrid Intelligence).

## 📊 Vue d'ensemble

**Dashboard:** `phase_1_8_metrics.json`
**URL Grafana:** http://localhost:3001/d/osmose-phase18
**Refresh:** Auto-refresh toutes les 10 secondes
**Tags:** `osmose`, `phase1.8`, `extraction`, `llm`

## 🎯 Panels du Dashboard

### Ligne 1 : Métriques Clés (Gauges)

#### 1. 🎯 Concept Recall
- **Type:** Gauge
- **Métrique:** Pourcentage de concepts détectés vs attendus
- **Seuils:**
  - 🔴 Rouge : < 70%
  - 🟠 Orange : 70-80%
  - 🟡 Jaune : 80-85%
  - 🟢 Vert : ≥ 85%
- **LogQL:**
  ```logql
  {service="app"} |~ "\\[OSMOSE.*Recall" | pattern "<_> Recall: <recall>%" | unwrap recall
  ```
- **Objectif Phase 1.8:** Passer de 70% → 85%

#### 2. 🎯 Concept Precision
- **Type:** Gauge
- **Métrique:** Précision des concepts extraits (true positives / total extraits)
- **Seuils:**
  - 🔴 Rouge : < 75%
  - 🟠 Orange : 75-85%
  - 🟡 Jaune : 85-90%
  - 🟢 Vert : ≥ 90%
- **LogQL:**
  ```logql
  {service="app"} |~ "\\[OSMOSE.*Precision" | pattern "<_> Precision: <precision>%" | unwrap precision
  ```
- **Objectif Phase 1.8:** Maintenir ≥ 85%

#### 3. 💰 Cost per Document (AVEC ALERTE)
- **Type:** Gauge avec alerte
- **Métrique:** Coût d'extraction LLM par document (USD)
- **Seuils:**
  - 🟢 Vert : < $0.08
  - 🟡 Jaune : $0.08 - $0.10
  - 🔴 Rouge : ≥ $0.10
- **Alerte:**
  - **Condition:** Moyenne > $0.10 pendant 5 minutes
  - **Action:** Notification (à configurer dans Grafana)
  - **Message:** "⚠️ Cost per document exceeds $0.10 threshold"
- **LogQL:**
  ```logql
  {service="app"} |~ "\\[OSMOSE.*cost_per_doc" | pattern "<_> cost_per_doc=<cost>" | unwrap cost
  ```
- **Objectif Phase 1.8:** < $0.10/doc

#### 4. ⏱️ Extraction Latency
- **Type:** Time series (ligne)
- **Métrique:** Latence d'extraction par document (secondes)
- **Seuil:** 20 secondes (ligne rouge)
- **Aggregations:** Moyenne + Maximum
- **LogQL:**
  ```logql
  {service="app"} |~ "\\[OSMOSE.*extraction_latency" | pattern "<_> extraction_latency=<latency>s" | unwrap latency
  ```
- **Objectif Phase 1.8:** < 20s/doc

### Ligne 2 : Logs Phase 1.8

#### 5. 📋 Phase 1.8 Extraction Logs
- **Type:** Logs
- **Filtre:** Logs contenant `[OSMOSE:Phase1.8]` ou `[EXTRACTOR:Phase1.8]`
- **LogQL:**
  ```logql
  {service="app"} |~ "\\[OSMOSE:Phase1\\.8\\]|\\[EXTRACTOR:Phase1\\.8\\]"
  ```
- **Utilité:** Debugging et monitoring en temps réel

### Ligne 3 : Détections & Validations

#### 6. 🔍 LOW_QUALITY_NER Detections
- **Type:** Time series (barres empilées)
- **Métrique:** Compteur de segments LOW_QUALITY_NER détectés
- **LogQL:**
  ```logql
  sum by (route) (count_over_time({service="app"} |~ "LOW_QUALITY_NER detected" [$__interval]))
  ```
- **Utilité:** Valider que le routing hybrid fonctionne

#### 7. ⚖️ LLM-as-a-Judge Validations
- **Type:** Time series (barres empilées)
- **Métriques:**
  - **Approved:** Clusters approuvés (✅ ACCEPT)
  - **Rejected:** Clusters rejetés (❌ REJECT)
- **LogQL:**
  ```logql
  # Approved
  sum(count_over_time({service="app"} |~ "\\[OSMOSE:LLM-Judge\\] ✅ ACCEPT" [$__interval]))

  # Rejected
  sum(count_over_time({service="app"} |~ "\\[OSMOSE:LLM-Judge\\] ❌ REJECT" [$__interval]))
  ```
- **Utilité:** Monitorer l'efficacité de la validation LLM-as-a-Judge

### Ligne 4 : Statistiques Globales

#### 8. 🔴 Errors (Last $__range)
- **Type:** Stat (nombre)
- **Métrique:** Compteur d'erreurs Phase 1.8
- **Seuils:**
  - 🟢 Vert : < 5
  - 🟡 Jaune : 5-10
  - 🔴 Rouge : ≥ 10
- **LogQL:**
  ```logql
  sum(count_over_time({service="app"} |~ "\\[OSMOSE:Phase1\\.8\\]|\\[EXTRACTOR:Phase1\\.8\\]" | level = "ERROR" [$__range]))
  ```

#### 9. 📄 Documents Processed
- **Type:** Stat (nombre)
- **Métrique:** Total de documents traités avec contexte Phase 1.8
- **LogQL:**
  ```logql
  sum(count_over_time({service="app"} |~ "Document context generated" [$__range]))
  ```

#### 10. 🤖 SMALL LLM Routes
- **Type:** Stat (nombre)
- **Métrique:** Segments routés vers SMALL LLM (gpt-4o-mini)
- **LogQL:**
  ```logql
  sum(count_over_time({service="app"} |~ "route.*SMALL" |~ "Phase1\\.8" [$__range]))
  ```

#### 11. 🎯 Canonical Concepts
- **Type:** Stat (nombre)
- **Métrique:** Concepts canoniques créés
- **LogQL:**
  ```logql
  sum(count_over_time({service="app"} |~ "canonical concepts created" [$__range]))
  ```

## 🚨 Alertes Configurées

### Alerte 1 : High Extraction Cost
- **Panel:** Cost per Document (#3)
- **Condition:** Moyenne > $0.10 pendant 5 minutes
- **Fréquence check:** Toutes les 1 minute
- **Message:** "⚠️ Cost per document exceeds $0.10 threshold"
- **État si pas de données:** `no_data`
- **État si erreur:** `alerting`

**Action recommandée si alerte:**
1. Vérifier routing : trop de segments vers BIG LLM ?
2. Vérifier longueur prompts : trop verbeux ?
3. Ajuster feature flag `enable_hybrid_extraction` si nécessaire

## 📝 Prérequis Logging

Pour que le dashboard fonctionne, le code doit logger les métriques au format attendu :

### Format Recall/Precision
```python
logger.info(f"[OSMOSE] Extraction complete - Recall: 87.5%")
logger.info(f"[OSMOSE] Extraction complete - Precision: 92.3%")
```

### Format Cost
```python
logger.info(f"[OSMOSE] Document processed - cost_per_doc=0.045")
```

### Format Latency
```python
logger.info(f"[OSMOSE] Extraction completed - extraction_latency=12.4s")
```

### Format Détections
```python
logger.info(f"[EXTRACTOR:Phase1.8] LOW_QUALITY_NER detected: {entity_count} entities but {word_count} tokens")
```

### Format Validations LLM-Judge
```python
logger.info(f"[OSMOSE:LLM-Judge] ✅ ACCEPT cluster: {concept_names}")
logger.warning(f"[OSMOSE:LLM-Judge] ❌ REJECT cluster: {concept_names}")
```

## 🛠️ Installation

### 1. Dashboard déjà provisionné automatiquement
Le dashboard est auto-provisionné via `monitoring/grafana-dashboards.yml`.

### 2. Accès manuel
Si besoin d'import manuel :
1. Ouvrir Grafana : http://localhost:3001
2. Aller dans **Dashboards** → **New** → **Import**
3. Uploader `monitoring/dashboards/phase_1_8_metrics.json`
4. Sélectionner datasource **Loki**
5. Cliquer **Import**

### 3. Configuration alertes (optionnel)
Pour activer les notifications d'alertes :

1. **Grafana UI** → **Alerting** → **Contact points**
2. Ajouter canal Slack/Email :
   ```yaml
   name: phase-1-8-alerts
   type: slack
   settings:
     url: https://hooks.slack.com/services/YOUR/WEBHOOK/URL
     channel: #phase-1-8
   ```
3. Lier au dashboard via **Notification channels**

## 🔧 Maintenance

### Modifier le dashboard
1. Éditer `monitoring/dashboards/phase_1_8_metrics.json`
2. Redémarrer Grafana :
   ```bash
   docker-compose restart grafana
   ```

### Vérifier provisioning
```bash
docker exec knowbase-grafana ls -la /etc/grafana/provisioning/dashboards/
```

## 📈 Utilisation Recommandée

### Workflow monitoring quotidien
1. **Matin :** Vérifier métriques globales (Recall, Precision, Cost)
2. **Pendant ingestion :** Monitorer latency + erreurs temps réel
3. **Fin journée :** Analyser validations LLM-Judge (taux rejection)

### Debugging
- **Recall < 85% :** Checker logs LOW_QUALITY_NER → segments manqués ?
- **Cost > $0.10 :** Checker routing SMALL vs BIG → optimiser prompts ?
- **Latency > 20s :** Checker logs latency → bottleneck LLM API ?
- **Erreurs :** Panel #8 → cliquer pour voir logs détaillés

## 🎯 Success Criteria Phase 1.8

Le dashboard permet de valider les critères de succès :

- [ ] ✅ Recall ≥ 85% (Panel #1)
- [ ] ✅ Precision ≥ 85% (Panel #2)
- [ ] ✅ Cost < $0.10/doc (Panel #3)
- [ ] ✅ Latency < 20s/doc (Panel #4)
- [ ] ✅ Pas d'erreurs critiques (Panel #8)
- [ ] ✅ Validations LLM-Judge fonctionnelles (Panel #7)

---

**Version:** 1.0
**Date:** 2025-11-20
**Phase:** 1.8 - LLM Hybrid Intelligence
