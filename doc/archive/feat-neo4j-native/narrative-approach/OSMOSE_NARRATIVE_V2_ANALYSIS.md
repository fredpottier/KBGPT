# 🎯 OSMOSE - Narrative Detector V2 : Analyse Critique et Recommandations

**Projet:** KnowWhere - OSMOSE
**Document:** Analyse Architecture V2
**Date:** 2025-10-13
**Auteur:** Claude Code Analysis

---

## 📋 Résumé Exécutif

### Question Initiale

**"Que penses-tu de l'analyse OpenAI sur la situation ?"**

### Réponse Courte

**Note globale : 7.5/10**

L'analyse OpenAI est **techniquement excellente** mais :
- ✅ Diagnostic parfait (scan naïf, PPTX ignorés, confusion narratives)
- ✅ Solutions V2 architecturalement supérieures
- ✅ Approche incrémentale pragmatique (v1.5 → v2)
- ⚠️ Timeline optimiste (×1.5 réaliste)
- ⚠️ Sous-estime complexité (PPTX, multilang, performance)
- ⚠️ Ignore contraintes OSMOSE Phase 1 existantes

### Recommandation

**Implémenter V2 directement** (votre préférence exprimée)

Étant donné que vous :
1. N'avez pas de démo programmée immédiatement
2. Acceptez d'allonger le temps si nécessaire
3. Voulez construire la cible directement

➡️ **V2 complète est la bonne approche** (14 semaines au lieu de 10)

---

## 📊 Scoring Détaillé Analyse OpenAI

### 1. Diagnostic (10/10) - Parfait

**Points identifiés:**
- ✅ Scan global naïf → threads de 650 pages
- ✅ PPTX visuels ignorés
- ✅ Multiples narratives confondues
- ✅ LLM mal nourri (1500 chars sur 95k)
- ✅ Performance dégradée

**Verdict:** Impeccable, confirme exactement nos constats.

---

### 2. Approche Incrémentale (9/10) - Excellente

**v1.5 (hotfix rapide) → v2 (refonte complète)**

**Points positifs:**
- ✅ Pragmatique pour projets avec deadline
- ✅ Permet validation progressive
- ✅ Réduit risque échec massif

**Point négatif:**
- ⚠️ Ne s'applique PAS à votre cas (pas de deadline imminente)

**Conclusion:** Excellent en général, mais vous avez raison de **sauter à V2 directement**.

---

### 3. Solutions Techniques V2 (8/10) - Solides

#### Excellentes Idées

**Topic-First Segmentation (10/10)**
```python
Document → Sections → Windows → Embeddings → Clustering → Topics
```
✅ Résout pollution cross-sections
✅ Anchors limitent scope
✅ Cohesion = métrique qualité

**Event-as-First-Class (10/10)**
```python
NarrativeEvent {
    entity, change_type, value_before/after,
    date, cause, evidence_spans
}
```
✅ Structuré vs texte brut
✅ Evidence-based (pas de hallucination)
✅ Compatible Proto-KG

**Thread-as-Graph (9/10)**
```python
Events → Relations (PRECEDES, CAUSES, EVOLVES_TO) → Timeline
```
✅ Graphe > séquence linéaire
✅ Causalité explicite
✅ Cross-doc linking naturel

**PPTX Chart XML (9/10)**
```python
# Parse XML avant vision LLM
chart_data = parse_pptx_chart_xml(slide)
if chart_data:
    # Pas de coût vision
else:
    # Vision LLM sélective
```
✅ Brillant - réduit coût vision
✅ Données structurées déjà présentes

#### Points Faibles

**Clustering HDBSCAN (6/10)**
```python
embeddings = embed_batch(windows)
clusters = HDBSCAN().cluster(embeddings)
```
⚠️ HDBSCAN instable sur petits datasets
⚠️ Hyperparamètres difficiles à tuner
⚠️ Peut créer 0 ou 50 clusters (imprévisible)

**Mitigation:**
```python
# Fallback hiérarchique:
# 1. Tenter HDBSCAN
# 2. Si fail → utiliser sections structurelles
# 3. Si sections absentes → k-means avec k auto
```

**LLM Extraction Cost (7/10)**
```python
# 10 topics × 3000 chars × LLM extraction
# Sur 100 docs → $70 LLM calls
```
⚠️ Coût peut exploser sur gros volumes
⚠️ Latence (10 topics séquentiels = 80s si pas parallèle)

**Mitigation:**
- Pattern-first (80% des cas)
- LLM seulement si patterns insuffisants
- Batch parallèle (10 topics simultanés)

---

### 4. Architecture V2 (9/10) - Excellente Vision

**Pipeline:**
```
Text → Topics (cluster) → Events (extract) → Threads (graph) → Timeline
```

**Pourquoi c'est supérieur:**

1. **Contextuel** : Chaque event dans un topic sémantique
2. **Structuré** : Events = schéma Pydantic (validation)
3. **Explicable** : Evidence spans + confidence
4. **Évolutif** : Ajout easy de nouveaux patterns/LLM tasks
5. **Aligné OSMOSE** : Proto-KG native, Dual-Graph

**Seul bémol:**
- Complexité accrue (4 composants vs 1)
- Debugging plus difficile
- Tests end-to-end critiques

---

### 5. Timeline Implémentation (4/10) - Trop Optimiste

**Proposé OpenAI:**
```
Semaine 1-2 : v1.5 hotfix
Semaine 3-6 : v2 complète
Total: 6 semaines
```

**Réalité (mon estimation):**
```
Semaine 7-9   : TopicSegmenter + EventExtractor (Pattern + LLM)
Semaine 10-11 : VisionExtractor + ThreadBuilder
Semaine 12-13 : CrossDocFusion + Neo4j Integration
Semaine 14    : Multilang + Quality + Tests
Semaine 15    : Démo CRR Evolution

Total: 9 semaines (Semaines 7-15 OSMOSE)
```

**Facteur multiplicateur : 1.5x**

**Pourquoi sous-estimé:**
- PPTX XML parsing non trivial (beaucoup de types de charts)
- Vision LLM prompts itération nécessaire
- Entity canonicalization complexe (multilang)
- Neo4j schema changes + migration
- Tests qualité (precision/recall) = long
- Debugging clusters instables

**Recommandation:**
- Planifier **14 semaines** total (avec buffer 3 semaines)
- Checkpoints intermédiaires (toutes les 2 semaines)

---

### 6. Performance Targets (3/10) - Irréalistes

**Proposé:** `p95 < 10s pour 650 pages`

**Calcul réaliste:**

```python
Document 650 pages = 1,300,000 chars

Operations V2:
1. Segmentation
   - Structural parsing: 2s
   - Windowing (200 windows): 1s
   - Embeddings (200 × 1536 dims):
     * OpenAI API batch: 10s
     * Local model (optimistic): 5s
   - HDBSCAN clustering: 2s
   Subtotal: ~15s

2. Event Extraction (10 topics, parallel)
   - Pattern extraction: 3s (regex)
   - LLM extraction (parallel 10 calls):
     * Sequential: 80s (10 × 8s)
     * Parallel: 12s (max 8 concurrent)
   - Vision (3 slides PPTX): 5s
   Subtotal: ~20s (parallel) | ~88s (sequential)

3. Thread Building
   - Grouping: 1s
   - Relation identification: 2s
   - Timeline construction: 1s
   Subtotal: ~4s

4. Neo4j Staging
   - Create nodes/relations: 2s
   Subtotal: ~2s

Total V2 (best case, full parallel): ~41s ✅
Total V2 (realistic, partial parallel): ~55s ⚠️
Total V2 (worst case, sequential): ~104s ❌
```

**Recommandation:**
- **Target réaliste : <45s (p50), <60s (p95)**
- Parallélisation LLM obligatoire
- Cache embeddings essentiel
- Monitoring perf par étape

---

### 7. Data Model Proto-KG (7/10) - Bon mais Incomplet

**Proposé:**
```cypher
(:NarrativeTopic)-[:IN_TOPIC]->(:EventCandidate)
(:EventCandidate)-[:PRECEDES|CAUSES|EVOLVES_TO]->(:EventCandidate)
```

**Manquants:**
```cypher
// Provenance détaillée
(:EventCandidate)-[:EXTRACTED_FROM {
    method: "PATTERN|LLM|VISION",
    span_start: Int,
    span_end: Int,
    confidence: Float
}]->(:Segment)

(:Segment)-[:PART_OF]->(:Section)
(:Section)-[:PART_OF]->(:Document)

// Liens cross-doc
(:EventCandidate)-[:SAME_AS {
    similarity: Float,
    matching_algorithm: String
}]->(:EventCandidate)

// Contradictions
(:EventCandidate)-[:CONTRADICTS {
    conflict_type: String,  // "VALUE", "DATE", "CAUSAL"
    resolution: String?      // "DOC1_NEWER", "USER_CHOSE", etc.
}]->(:EventCandidate)

// Metadata timeline
(:NarrativeThread {
    thread_id: String,
    entity_canonical: String,
    start_date: String,
    end_date: String,
    event_count: Int,
    confidence_avg: Float,
    source_documents: [String],
    is_cross_document: Boolean
})

(:NarrativeThread)-[:CONTAINS]->(:EventCandidate)
```

**Conclusion:** Le schéma proposé est une bonne base, mais nécessite enrichissement.

---

### 8. Alignement OSMOSE (6/10) - Ignore Contraintes

**Contraintes non mentionnées:**

1. **Phase 1 Semaines 7-10 déjà planifiées**
   ```
   Semaine 7-8 : IntelligentSegmentationEngine
   Semaine 9   : DualStorageExtractor
   Semaine 10  : Tests + Démo
   ```
   V2 = 9 semaines → décale tout

2. **Budget LLM allocation existant**
   ```yaml
   # config/osmose_semantic_intelligence.yaml
   budget_allocation:
     default_per_doc: 2.0  # USD
   ```
   V2 avec embeddings + LLM events peut dépasser

3. **SemanticDocumentProfiler déjà implémenté**
   ```python
   # profiler.py fait déjà:
   - Complexity analysis (chunks 3000 chars)
   - Domain classification
   - Preliminary narrative detection
   ```
   → Peut servir de base pour TopicSegmenter !

4. **Proto-KG schema déjà défini**
   ```cypher
   (:CandidateEntity)-[:EXTRACTED_FROM]->(:Document)
   ```
   V2 doit s'intégrer (pas remplacer)

**Recommandation:** Réutiliser au maximum l'existant.

---

### 9. Faisabilité (5/10) - Sous-Estime Complexité

**Défis sous-estimés:**

#### PPTX Chart Parsing (Complexité : HIGH)

**Variété de formats:**
```python
# Types de charts supportés par python-pptx
- Bar charts (vertical, horizontal, stacked, 100% stacked)
- Line charts (line, line with markers, 100% stacked)
- Pie charts (pie, doughnut, exploded pie)
- Combo charts (bar + line, dual axis)
- Scatter plots
- Area charts
- Bubble charts

# Mais aussi:
- Excel embedded charts (données dans workbook.xml)
- SmartArt diagrams (structure complexe)
- Images de charts (screenshots) → Vision obligatoire
- Tables stylisées comme charts
```

**Taux de succès réaliste:**
- Charts natifs PPTX avec XML : 70% parsable
- Excel embedded : 40% parsable (XML workbook complexe)
- SmartArt : 10% parsable (trop de variations)
- Images : 0% parsable sans vision

**Conclusion:** Vision LLM sera nécessaire plus souvent que "3 slides max".

#### Multilanguage (Complexité : MEDIUM)

**Patterns multilingues:**
```python
# Pas juste traduire les mots!

# Anglais
"CRR was updated in March 2023 because ISO compliance"

# Français
"Le CRR a été mis à jour en mars 2023 en raison de la conformité ISO"
# Structure différente: "a été mis à jour" vs "was updated"

# Allemand
"CRR wurde im März 2023 aufgrund der ISO-Konformität aktualisiert"
# Ordre des mots différent!

# Italien
"Il CRR è stato aggiornato a marzo 2023 a causa della conformità ISO"
```

**Solution naïve:** Traduire keywords
```python
{"updated": ["mis à jour", "aktualisiert", "aggiornato"]}
```
❌ Ne fonctionne pas bien (faux positifs, structures différentes)

**Solution robuste:** LLM multilang
```python
# LLM comprend les structures linguistiques
# Fonctionne sur toutes langues sans patterns
# Coût: +$0.01/doc
```

#### Entity Canonicalization (Complexité : HIGH)

**Problème:**
```python
# Même concept, 15 variantes:
"CRR"
"Customer Retention Rate"
"Taux de Rétention Client"
"customer retention"
"retention rate"
"CRR metric"
"CRR %"
"CRR percentage"
"Client Retention Rate"
"Kundenerhaltungsrate"  # DE
"Tasso di Fidelizzazione Cliente"  # IT
```

**Solutions:**
1. **Dict statique** (maintenance enfer, 20% recall)
2. **Embeddings similarity** (coûteux, 70% recall)
3. **LLM entity linking** (optimal, 90% recall, coût acceptable)

**Recommandation:** Hybrid (dict + LLM fallback)

---

### 10. Business Impact (7/10) - Sauve Démo mais Décale Roadmap

**Impact positif:**
- ✅ USP démontrée (narratives cross-doc + timeline + PPTX)
- ✅ Différenciation vs Copilot claire
- ✅ Architecture scalable (Phase 2-3)

**Impact négatif:**
- ⚠️ Phase 1 rallongée : 10 → 15 semaines (+50%)
- ⚠️ Scope creep : Phase 2 features dans Phase 1
- ⚠️ Risque budget coût LLM

**Mitigation (votre approche):**
- ✅ Accepter rallongement (pas de deadline stricte)
- ✅ Construire cible directement
- ✅ Qualité > vitesse

**Verdict:** Aligné avec votre stratégie ✅

---

## 🎯 Ma Recommandation Finale

### Option Retenue : V2 Complète Directement

**Rationale:**

Vous avez exprimé :
1. "Pas de démo programmée ni de souci à revenir en arrière"
2. "Mon seul but est de construire la cible directement"
3. "Accepter allongement du temps si nécessaire"

➡️ **V2 complète est LA bonne approche**

### Plan Ajusté (14 Semaines)

#### Phase 1 : Fondations (Semaines 7-9)

**Semaine 7 : TopicSegmenter**
```
✓ Classe TopicSegmenter
✓ Structural segmentation (MegaParse sections)
✓ Semantic windowing (3000 chars, 25% overlap)
✓ Embeddings (OpenAI text-embedding-3-small)
✓ HDBSCAN clustering avec fallback sections
✓ Anchor extraction (spaCy NER + TF-IDF)
✓ Tests 100-200 pages

Réutilisation:
→ SemanticDocumentProfiler._analyze_complexity()
→ Déjà fait: chunking 3000 chars
```

**Semaine 8 : EventExtractor (Pattern + LLM)**
```
✓ Classe EventExtractor
✓ PatternBasedExtractor
  - Temporal patterns (multilang: EN, FR, DE, IT)
  - Version patterns (v1.0 → v2.0)
  - Causal patterns (because, parce que, weil, perché)
  - Value change patterns (72% → 82%)
✓ LLMBasedExtractor (structured output JSON)
✓ Event validation (evidence required, anchor match)
✓ Deduplication
✓ Tests extraction sur topics

Checkpoint Semaine 8:
→ Pattern extraction fonctionne multilang
→ LLM extraction structured output validé
→ Events avec evidence spans
```

**Semaine 9 : ThreadBuilder**
```
✓ Classe ThreadBuilder
✓ Entity canonicalization (dict + LLM fallback)
✓ Event grouping par (topic, entity)
✓ Temporal ordering (date parsing flexible)
✓ Relation identification
  - PRECEDES (temporal)
  - CAUSES (causal evidence)
  - EVOLVES_TO (version upgrade)
  - CONTRADICTS (conflict detection)
✓ Timeline construction (chronological + visual)
✓ Tests threads avec events réels

Checkpoint Semaine 9:
→ Threads construits correctement
→ Relations identifiées
→ Timeline ordonnée
```

#### Phase 2 : PPTX et Cross-Doc (Semaines 10-12)

**Semaine 10 : VisionBasedExtractor (PPTX) - CRITIQUE**
```
✓ Chart XML parsing (python-pptx)
  - Bar, line, pie charts natifs
  - Excel embedded (workbook.xml)
  - Fallback: échec gracieux
✓ Vision candidate detection
  - Title keywords (evolution, trend, CRR, KPI)
  - Slide layout analysis
  - Relevance scoring
✓ GPT-4V integration
  - Prompt timeline extraction
  - Structured output JSON
  - Error handling (vision fails)
✓ Event synthesis
  - Merge text + chart + vision data
  - High confidence multi-source
✓ Cost control
  - XML-first (évite vision si possible)
  - Cap 3-5 slides/deck (configurable)
  - Monitoring coût par deck
✓ Tests avec decks PPTX réels (10+)

Checkpoint Semaine 10:
→ PPTX charts extraits (XML 70% success)
→ Vision LLM fonctionne (20% slides)
→ Events PPTX confidence >0.80
→ Coût <$0.10/deck
```

**Semaine 11 : CrossDocumentFusion**
```
✓ Entity canonicalization (global)
  - Alias resolution ("CRR" = "Customer Retention Rate")
  - Multilang ("CRR" = "Taux Rétention Client")
  - LLM entity linking
✓ Event deduplication cross-doc
  - Same entity + date + value → 1 event
  - Provenance multiple sources
✓ Conflict resolution
  - Same entity + date, different values
  - Strategies: newest doc, highest confidence, user choice
✓ Master thread creation
  - Merge events chronologically
  - Rebuild relations cross-doc
  - Unified timeline
✓ Provenance tracking (source_documents list)
✓ Tests fusion 3-5 documents

Checkpoint Semaine 11:
→ Cross-doc threads fusionnés correctement
→ Entity linking fonctionne
→ Conflicts détectés et résolus
```

**Semaine 12 : Parallélisation et Performance**
```
✓ Multi-threading LLM calls
  - asyncio.gather() pour extraction parallèle
  - Batch embeddings (200 windows simultanés)
  - Semaphore limit (max 10 concurrent LLM)
✓ Cache embeddings
  - Hash texte → embedding dict
  - Évite recalcul sur docs similaires
✓ Performance profiling
  - Timer par étape (segmentation, extraction, etc.)
  - Bottleneck identification
✓ Optimisations
  - Pattern-first (skip LLM si patterns suffisants)
  - Clustering fallback (sections si HDBSCAN fail)
✓ Tests performance 650 pages

Checkpoint Semaine 12:
→ Performance <45s (p50) sur 650 pages
→ Performance <60s (p95)
→ LLM calls parallèles fonctionnent
→ Cache réduit coût 30%
```

#### Phase 3 : Proto-KG et Qualité (Semaines 13-14)

**Semaine 13 : Neo4j Integration**
```
✓ Schema update
  - :NarrativeTopic
  - :EventCandidate
  - :NarrativeThread
  - Relations (PRECEDES, CAUSES, EVOLVES_TO, CONTRADICTS)
✓ Staging implementation
  - Batch create nodes/relations
  - Conflict handling (duplicate IDs)
✓ Query narratives
  - Find thread by entity
  - Find events by date range
  - Find causal chains
✓ Provenance links
  - :EventCandidate → :Document
  - :EventCandidate → :Segment
✓ Tests Neo4j integration

Checkpoint Semaine 13:
→ Events stagés dans Proto-KG
→ Relations créées correctement
→ Queries fonctionnent
→ Provenance complète
```

**Semaine 14 : Quality Metrics et Tests**
```
✓ Annotation dataset
  - 50 documents annotés manuellement
  - Events ground truth
  - Relations ground truth
✓ Precision/Recall computation
  - Event detection: P/R
  - Relation detection: P/R
  - Timeline accuracy
✓ Error analysis
  - False positives causes
  - False negatives causes
  - Iteration prompts/patterns
✓ Tests end-to-end
  - 100+ documents variés
  - Multilang (EN, FR, DE, IT)
  - PPTX + PDF mixtes
✓ Documentation API

Checkpoint Semaine 14:
→ Precision ≥85%
→ Recall ≥80%
→ Timeline accuracy ≥90%
→ Tests passent sur 100 docs
```

#### Phase 4 : Démo CRR Evolution (Semaine 15)

**Semaine 15 : KILLER FEATURE Demo**
```
✓ Dataset démo
  - 5 documents CRR (PDF + PPTX)
  - Timeline 2022 → 2024
  - 3 versions (v1.0 → v2.0 → v3.0)
  - Causal links (audit → update → improvement)
✓ Query interface
  - "Comment CRR a évolué ?"
  - Response timeline structurée
  - Provenance visible
✓ Visualization
  - Timeline graphique
  - Relations causales (diagram)
  - Source documents links
✓ Copilot comparison
  - Même query sur Copilot
  - Side-by-side screenshot
  - Différenciation claire
✓ Documentation démo
  - Script démo
  - Screenshots
  - Video recording (5 min)

Checkpoint Semaine 15:
→ Démo CRR Evolution fonctionne parfaitement
→ Timeline correcte (3 versions)
→ Relations causales identifiées
→ PPTX charts inclus
→ USP vs Copilot démontrée ✅
```

---

### Timeline Visuelle

```
Semaine 7  : TopicSegmenter                      [████████]
Semaine 8  : EventExtractor (Pattern+LLM)        [████████]
Semaine 9  : ThreadBuilder                       [████████]
             └─ Checkpoint: Threads fonctionnent

Semaine 10 : VisionExtractor (PPTX) 🔥           [████████]
Semaine 11 : CrossDocFusion                      [████████]
Semaine 12 : Performance + Parallélisation       [████████]
             └─ Checkpoint: Performance <45s

Semaine 13 : Neo4j Integration                   [████████]
Semaine 14 : Quality Metrics + Tests             [████████]
             └─ Checkpoint: P≥85%, R≥80%

Semaine 15 : Démo CRR Evolution 🎯               [████████]
             └─ KILLER FEATURE démontrée

Total: 9 semaines (+ 5 semaines vs plan initial Phase 1)
```

---

### Budget et Ressources

**Coût par Document (V2):**
```
Embeddings (200 windows):      $0.003
LLM Extraction (10 topics):    $0.010
Vision PPTX (3 slides):        $0.039
Neo4j operations:              $0.001
─────────────────────────────────────
Total:                         $0.053 / doc

Budget OSMOSE: $2.00/doc → 37× marge ✅
```

**Coût 100 Documents (validation):**
```
100 docs × $0.053 = $5.30
Budget validation: $50 → OK ✅
```

**Performance Targets:**
```
Document 200 pages:  ~15s  (baseline)
Document 650 pages:  ~42s  (target <45s) ✅
Document 1000 pages: ~65s  (acceptable <90s)

p50: 25s
p95: 60s
p99: 90s
```

---

## 🚧 Risques et Mitigations

### Risques Techniques (HIGH)

| Risque | Impact | Prob | Mitigation |
|--------|--------|------|------------|
| **HDBSCAN clustering instable** | HIGH | MED | Fallback: sections structurelles |
| **LLM hallucinations events** | HIGH | MED | Evidence spans obligatoires + validation |
| **Vision LLM erreurs charts** | MED | MED | XML-first, vision selective, confiance ajustée |
| **Performance >60s** | MED | LOW | Parallélisation LLM + cache embeddings |
| **Entity linking <70% recall** | HIGH | MED | LLM fallback après dict |

### Risques Produit (MEDIUM)

| Risque | Impact | Prob | Mitigation |
|--------|--------|------|------------|
| **USP non différenciant vs Copilot** | CRIT | LOW | Tests comparatifs Semaine 15 |
| **Precision <80%** | HIGH | MED | Iteration prompts + annotation dataset |
| **PPTX coverage <60%** | MED | MED | Vision agressive (5 slides) + XML parsing |
| **Multilang quality variable** | MED | MED | Tests par langue + patterns spécifiques |

### Risques Planning (MEDIUM)

| Risque | Impact | Prob | Mitigation |
|--------|--------|------|------------|
| **Dépassement timeline 15 sem** | MED | MED | Checkpoints bi-hebdo + replanif agile |
| **Budget coût LLM dépassé** | LOW | LOW | Monitoring strict + pattern-first |
| **Complexité integration Neo4j** | MED | LOW | Tests early Semaine 13 |

---

## ✅ Critères de Succès Phase 1 Extended

### Fonctionnels (Must-Have)

- ✅ Détection événements sur docs 600+ pages sans pollution
- ✅ Support PPTX avec extraction graphiques/charts
- ✅ Timeline chronologique correcte (3+ événements)
- ✅ Relations causales identifiées (evidence-based)
- ✅ Cross-document fusion (même entité)
- ✅ Multilang (EN, FR, DE, IT)

### Techniques (Targets)

| Métrique | Target | Validation |
|----------|--------|------------|
| Precision événements | ≥85% | 50 docs annotés |
| Recall événements | ≥80% | Dataset ground truth |
| Timeline accuracy | ≥90% | Ordre chronologique |
| Cross-doc linking | ≥75% | Entité reliée |
| Performance p50 | <30s | Benchmark 100 docs |
| Performance p95 | <60s | Benchmark 100 docs |
| Cost per doc | <$0.10 | Monitoring 100 docs |
| PPTX coverage | ≥70% | % decks avec ≥1 event |

### Business (USP)

**Démo "CRR Evolution Tracker" fonctionne:**

```
Query: "Comment CRR a évolué dans nos documents ?"

Documents testés:
1. SAP_CRR_Methodology_v1_2022.pdf (45 pages)
2. SAP_CRR_Updated_Formula_2023.pdf (38 pages)
3. SAP_S4HANA_Guide_2023.pdf (650 pages)
4. SAP_Analytics_Q3_2023.pptx (45 slides)

Response:
┌────────────────────────────────────────┐
│ CRR Evolution Timeline (2022-2023)     │
├────────────────────────────────────────┤
│                                        │
│ 2022-01-15 │ CRR v1.0 Introduced      │
│            │ [Doc1, p.12]             │
│            │ ↓ EVOLVES_TO             │
│                                        │
│ 2022-11-20 │ Audit Gap Identified     │
│            │ [Doc3, p.287]            │
│            │ ↓ CAUSES                 │
│                                        │
│ 2023-03-15 │ CRR v2.0 Updated         │
│            │ ISO 23592 compliant      │
│            │ [Doc2, p.5]              │
│            │ ↓ CAUSES                 │
│                                        │
│ 2023-Q3    │ CRR +10% (72→82%)        │
│            │ [Doc4, Slide 5 - Chart] │
│            │                          │
└────────────────────────────────────────┘

✅ 4 événements
✅ 2 relations causales
✅ 4 sources (PDF + PPTX)
✅ Confidence: 0.88
```

**vs Copilot:** Pas de timeline, pas de causalité, pas de PPTX vision

**USP DÉMONTRÉE** ✅

---

## 📚 Réutilisation Existant OSMOSE

### SemanticDocumentProfiler

**Réutilisation pour TopicSegmenter:**

```python
# profiler.py:120-150 (déjà implémenté)
def _analyze_complexity(self, text: str) -> List[ComplexityZone]:
    # Déjà fait: chunking 3000 chars
    chunks = [text[i:i+3000] for i in range(0, len(text), 3000)]
    # ...

# Réutiliser dans TopicSegmenter:
class TopicSegmenter:
    def _create_windows(self, text: str):
        # Appeler profiler._analyze_complexity()
        # Au lieu de ré-implémenter chunking
        complexity_zones = profiler._analyze_complexity(text)
        return [Window(zone.text, zone.start, zone.end) for zone in complexity_zones]
```

**Bénéfice:** Évite duplication, windows déjà optimisés

### IntelligentSegmentationEngine (Sem 7-8 planifié)

**Fusion avec TopicSegmenter:**

```python
# Au lieu de 2 composants séparés:
# - TopicSegmenter (V2)
# - IntelligentSegmentationEngine (plan initial)

# → 1 composant unifié:
class IntelligentTopicSegmenter:
    """
    Combine:
    - Segmentation intelligente (budget-aware)
    - Topic clustering (semantic-aware)
    - Narrative-aware (preserve threads)
    """
```

**Bénéfice:** Moins de duplication, architecture cohérente

### DualStorageExtractor (Sem 9 planifié)

**Intégration avec EventExtractor:**

```python
# EventExtractor produit des NarrativeEvents
# DualStorageExtractor les stage dans:
# - Neo4j (EventCandidate nodes)
# - Qdrant (vectors avec payload narrative)

class DualStorageExtractor:
    async def stage_narrative_events(
        self,
        events: List[NarrativeEvent],
        threads: List[NarrativeThread]
    ):
        # Neo4j staging
        await self._stage_to_neo4j(events, threads)

        # Qdrant staging
        await self._stage_to_qdrant(events, threads)
```

**Bénéfice:** Réutilise infrastructure Proto-KG existante

---

## 🎯 Conclusion : Go V2 Directement

### Pourquoi V2 est le Bon Choix

**Alignement avec vos objectifs:**
1. ✅ Construire la cible directement (votre priorité)
2. ✅ Qualité > vitesse (pas de deadline imminente)
3. ✅ Architecture scalable pour Phase 2-3

**Avantages V2:**
- ✅ Résout tous les problèmes V1 identifiés
- ✅ USP KILLER FEATURE démontrable
- ✅ Support PPTX multimodal
- ✅ Multilang natif
- ✅ Performance acceptable (<45s)
- ✅ Coût contrôlé (<$0.10/doc)

**Inconvénients acceptables:**
- ⚠️ Timeline +5 semaines (15 vs 10)
- ⚠️ Complexité accrue (4 composants)
- ⚠️ Tests end-to-end critiques

### Décision Recommandée

**GO V2 COMPLÈTE - 15 SEMAINES**

**Justification:**
- Vous avez explicitement dit : "construire la cible directement même si cela doit allonger le temps"
- Pas de démo programmée immédiatement
- V1.5 (hotfix) ne s'applique pas à votre contexte
- V2 est architecturalement supérieure et pérenne

### Next Steps

1. **Valider plan 15 semaines** avec stakeholders
2. **Mettre à jour PHASE1_TRACKING.md** (10 → 15 semaines)
3. **Commencer Semaine 7 : TopicSegmenter**
4. **Checkpoints bi-hebdomadaires** (ajustements agiles)

---

**🌊 OSMOSE V2 : "La bonne architecture dès le départ, pour ne pas refaire 2 fois."**

**Status:** Analyse Complète - Ready for Decision
**Recommendation:** GO V2 (15 semaines)
**Confidence:** 9/10
