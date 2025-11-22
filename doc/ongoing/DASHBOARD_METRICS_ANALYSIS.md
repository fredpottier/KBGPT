# 📊 Analyse Dashboard Grafana - Métriques Manquantes

## Dashboard Actuel : "🌊 OSMOSE Phase 1.8 - Extraction Metrics"

### ❌ Problème : Nom Non-Pérenne
**Titre actuel** : "OSMOSE Phase 1.8 - Extraction Metrics"
- ⚠️ Référence spécifique à Phase 1.8 (temporaire)
- ❌ Ne reflétera plus la réalité après Phase 1.8

**Proposition nouveau titre** :
- Option 1: **"🌊 OSMOSE Semantic Intelligence - Extraction & Quality Metrics"**
- Option 2: **"🌊 KnowWhere - Semantic Extraction Dashboard"**
- Option 3: **"🌊 OSMOSE - Concept Extraction & Fusion Monitoring"**

---

## 📊 État des Métriques (11 panels)

### ✅ Panel 1 : 🎯 Concept Recall
**Query Loki** : `{service="app"} |~ "\\[OSMOSE.*Recall" | pattern "<_> Recall: <recall>%" | unwrap recall`

**Status** : ❌ **NON GÉNÉRÉ**
**Log attendu** : `[OSMOSE] Recall: 85%`

**Localisation probable** :
- `src/knowbase/agents/extractor/orchestrator.py` ou
- `src/knowbase/semantic/extraction/concept_extractor.py`

**À implémenter** : Calculer recall après extraction vs concepts attendus/gold standard

---

### ✅ Panel 2 : 🎯 Concept Precision
**Query Loki** : `{service="app"} |~ "\\[OSMOSE.*Precision" | pattern "<_> Precision: <precision>%" | unwrap precision`

**Status** : ❌ **NON GÉNÉRÉ**
**Log attendu** : `[OSMOSE] Precision: 92%`

**Localisation probable** : Même que Recall

**À implémenter** : Calculer precision (vrais positifs / total extraits)

---

### ✅ Panel 3 : 💰 Cost per Document
**Query Loki** : `{service="app"} |~ "\\[OSMOSE.*cost_per_doc" | pattern "<_> cost_per_doc=<cost>" | unwrap cost`

**Status** : ⚠️ **PARTIELLEMENT GÉNÉRÉ**
**Log attendu** : `[OSMOSE] cost_per_doc=0.0234`

**Situation actuelle** :
- ✅ Token tracking existe (`data/logs/token_usage.jsonl`)
- ❌ Pas de log consolidé "cost_per_doc"

**À implémenter** :
- Calculer coût total par document à la fin de l'extraction
- Logger au format attendu par Grafana

**Fichier** : `src/knowbase/ingestion/osmose_agentique.py` (fin de `run_osmose_extraction`)

---

### ✅ Panel 4 : ⏱️ Extraction Latency
**Query Loki** : `{service="app"} |~ "\\[OSMOSE.*extraction_latency" | pattern "<_> extraction_latency=<latency>s" | unwrap latency`

**Status** : ⚠️ **PARTIELLEMENT GÉNÉRÉ**
**Log actuel** : `processed successfully: 509 concepts promoted in 3592.4s`
**Log attendu** : `[OSMOSE] extraction_latency=3592.4s`

**À implémenter** : Reformater log existant au format structuré

**Fichier** : `src/knowbase/ingestion/osmose_agentique.py`

---

### ✅ Panel 5 : 📋 Phase 1.8 Extraction Logs
**Query Loki** : `{service="app"} |~ "\\[OSMOSE:Phase1\\.8\\]|\\[EXTRACTOR:Phase1\\.8\\]"`

**Status** : ✅ **GÉNÉRÉ** (si logs existent)
**Note** : Pattern spécifique Phase 1.8 → À GÉNÉRALISER

**À modifier** : Changer pattern vers `[OSMOSE]|[EXTRACTOR]` (sans Phase1.8)

---

### ✅ Panel 6 : 🔍 LOW_QUALITY_NER Detections
**Query Loki** : `count_over_time({service="app"} |~ "LOW_QUALITY_NER detected" [$__interval])`

**Status** : ⚠️ **DÉPEND DU PIPELINE**
**Log attendu** : `[OSMOSE] LOW_QUALITY_NER detected for segment XYZ`

**Situation** :
- ✅ Détection existe dans `concept_density_detector.py`
- ❌ Log pas forcément au bon format
- ⚠️ Concept "LOW_QUALITY_NER" deprecated en Phase 1.8.1d

**À adapter** : Remplacer par "Dense text detected" ou équivalent

---

### ✅ Panel 7 : ⚖️ LLM-as-a-Judge Validations
**Query Loki** :
- Approved: `{service="app"} |~ "\\[OSMOSE:LLM-Judge\\] ✅ ACCEPT"`
- Rejected: `{service="app"} |~ "\\[OSMOSE:LLM-Judge\\] ❌ REJECT"`

**Status** : ❌ **NON GÉNÉRÉ**
**Log attendu** :
- `[OSMOSE:LLM-Judge] ✅ ACCEPT cluster concept_123`
- `[OSMOSE:LLM-Judge] ❌ REJECT cluster concept_456`

**Situation** :
- ⚠️ LLM-as-a-Judge existe mais n'est plus utilisé en Phase 1.8.1d
- ✅ Remplacé par heuristiques + Gatekeeper

**À adapter** :
- Option 1: Logger approvals/rejets du Gatekeeper
- Option 2: Supprimer ce panel (obsolète)

---

### ✅ Panel 8 : 🔴 Errors (Last $__range)
**Query Loki** : `{service="app"} |~ "\\[OSMOSE:Phase1\\.8\\]|\\[EXTRACTOR:Phase1\\.8\\]" | level = "ERROR"`

**Status** : ✅ **GÉNÉRÉ** (si erreurs)
**Note** : Pattern Phase 1.8 spécifique

**À modifier** : Généraliser pattern

---

### ✅ Panel 9 : 📄 Documents Processed
**Query Loki** : `count_over_time({service="app"} |~ "Document context generated" [$__range])`

**Status** : ✅ **GÉNÉRÉ**
**Log actuel** : Existe déjà

---

### ✅ Panel 10 : 🤖 SMALL LLM Routes
**Query Loki** : `{service="app"} |~ "route.*SMALL" |~ "Phase1\\.8"`

**Status** : ⚠️ **PARTIELLEMENT GÉNÉRÉ**
**Note** : Pattern Phase 1.8 spécifique

**À modifier** : Retirer référence Phase 1.8

---

### ✅ Panel 11 : 🎯 Canonical Concepts
**Query Loki** : `count_over_time({service="app"} |~ "canonical concepts created" [$__range])`

**Status** : ❌ **NON GÉNÉRÉ**
**Log attendu** : `[OSMOSE] 301 canonical concepts created`

**Situation actuelle** :
- ✅ Concepts créés dans Neo4j
- ❌ Pas de log explicite

**À implémenter** : Logger nombre de CanonicalConcepts après fusion

**Fichier** : `src/knowbase/semantic/fusion/smart_concept_merger.py` ou `osmose_agentique.py`

---

## 📊 Résumé État Actuel

| Panel | Métrique | Status | Priorité |
|-------|----------|--------|----------|
| 1 | Concept Recall | ❌ Non généré | 🔴 Haute |
| 2 | Concept Precision | ❌ Non généré | 🔴 Haute |
| 3 | Cost per Document | ⚠️ Partiel | 🟡 Moyenne |
| 4 | Extraction Latency | ⚠️ Partiel | 🟡 Moyenne |
| 5 | Extraction Logs | ✅ OK | - |
| 6 | LOW_QUALITY_NER | ⚠️ Obsolète | 🟣 À adapter |
| 7 | LLM-Judge | ❌ Obsolète | 🟣 À supprimer/remplacer |
| 8 | Errors | ✅ OK | - |
| 9 | Documents Processed | ✅ OK | - |
| 10 | SMALL LLM Routes | ⚠️ Partiel | 🟢 Basse |
| 11 | Canonical Concepts | ❌ Non généré | 🟡 Moyenne |

**Métriques fonctionnelles** : 3/11 (27%)
**Métriques partielles** : 3/11 (27%)
**Métriques manquantes** : 3/11 (27%)
**Métriques obsolètes** : 2/11 (18%)

---

## 🎯 Plan d'Implémentation

### Phase 1 : Métriques Critiques (Priorité Haute)

#### 1.1 Cost per Document
**Fichier** : `src/knowbase/ingestion/osmose_agentique.py`
**Implémentation** :
```python
# À la fin de run_osmose_extraction()
total_cost = sum([call["cost"] for call in token_usage_data])
cost_per_doc = total_cost / 1.0  # 1 doc
logger.info(f"[OSMOSE:Metrics] cost_per_doc={cost_per_doc:.4f}")
```

#### 1.2 Extraction Latency
**Fichier** : `src/knowbase/ingestion/osmose_agentique.py`
**Implémentation** :
```python
# À la fin de run_osmose_extraction()
duration_seconds = (end_time - start_time).total_seconds()
logger.info(f"[OSMOSE:Metrics] extraction_latency={duration_seconds:.1f}s")
```

#### 1.3 Canonical Concepts Count
**Fichier** : `src/knowbase/ingestion/osmose_agentique.py` (après fusion)
**Implémentation** :
```python
# Après SmartConceptMerger
canonical_count = len(canonical_concepts)
logger.info(f"[OSMOSE:Metrics] {canonical_count} canonical concepts created")
```

### Phase 2 : Métriques Qualité (Priorité Moyenne)

#### 2.1 Concept Recall & Precision
**Note** : Nécessite ground truth / gold standard
**Options** :
- Option A : Comparer avec extraction NER baseline
- Option B : Créer dataset annoté (manuel, coûteux)
- Option C : Utiliser heuristique (concepts promus vs total extraits)

**Implémentation heuristique** :
```python
# Dans osmose_agentique.py après Gatekeeper
total_extracted = len(all_concepts_before_gate)
promoted = len(concepts_after_gate)
recall_heuristic = (promoted / total_extracted) * 100
logger.info(f"[OSMOSE:Metrics] Recall: {recall_heuristic:.1f}%")
logger.info(f"[OSMOSE:Metrics] Precision: {precision_estimate:.1f}%")
```

### Phase 3 : Nettoyage & Adaptation (Priorité Basse)

#### 3.1 Supprimer Panels Obsolètes
- ❌ Panel 6 : LOW_QUALITY_NER (concept deprecated)
- ❌ Panel 7 : LLM-Judge (remplacé par Gatekeeper)

#### 3.2 Généraliser Patterns Logs
- Retirer références "Phase1.8" spécifiques
- Utiliser `[OSMOSE]` générique

#### 3.3 Ajouter Nouveaux Panels
**Suggestions** :
- 🎨 SmartConceptMerger Fusion Rate (concepts fusionnés vs préservés)
- 🌊 DomainContext Injection Count
- 🔄 Gatekeeper Promotion Rate
- 📊 Concepts by Type Distribution (ENTITY, PRODUCT, TECHNOLOGY)

---

## 🚀 Nouveau Titre Proposé

**Recommandation finale** :
### **"🌊 OSMOSE - Semantic Extraction & Quality Dashboard"**

**Rationale** :
- ✅ Nom pérenne (pas de référence Phase 1.8)
- ✅ Décrit fonctionnalité réelle (extraction + qualité)
- ✅ Identité OSMOSE claire
- ✅ Suffisamment générique pour évolutions futures

**Alternative concise** :
### **"🌊 OSMOSE Extraction Monitoring"**

---

## 📝 Checklist Actions

- [ ] Implémenter logs manquants (cost, latency, canonical concepts)
- [ ] Ajouter métriques qualité (recall/precision heuristique)
- [ ] Renommer dashboard (retirer "Phase 1.8")
- [ ] Généraliser patterns logs (retirer Phase1.8 des queries)
- [ ] Supprimer panels obsolètes (LLM-Judge, LOW_QUALITY_NER)
- [ ] Ajouter nouveaux panels (Fusion, DomainContext, Gatekeeper)
- [ ] Tester dashboard avec import réel
- [ ] Documenter format logs attendus
