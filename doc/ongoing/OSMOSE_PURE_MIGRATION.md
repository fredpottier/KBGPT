# 🌊 Migration OSMOSE Pure - Phase 1.5

**Date:** 2025-10-14
**Status:** ✅ Architecture implémentée - Tests requis

---

## 🎯 Objectif

**Remplacer complètement l'ingestion legacy par OSMOSE Pure** pour simplifier l'architecture et activer l'USP différenciateur de KnowWhere.

---

## 📊 Architecture - Avant vs Après

### ❌ AVANT (Legacy - Complexe)

```
Document (PDF/PPTX)
      ↓
  Extraction Texte
  (MegaParse / pptx-parser)
      ↓
  Ingestion Legacy
  ├── Qdrant "knowbase" (chunks textuels)
  ├── Qdrant "rfp_qa" (Q&A RFP)
  └── Neo4j (entities/relations directes)
```

**Problèmes** :
- ❌ Pas de concepts canoniques cross-linguals
- ❌ Pas de relations cross-documents
- ❌ Duplication si OSMOSE ajouté en parallèle
- ❌ Pas d'USP vs Copilot/Gemini

---

### ✅ APRÈS (OSMOSE Pure - Simplifié)

```
Document (PDF/PPTX)
      ↓
  Extraction Texte
  (MegaParse / pptx-parser)
      ↓
  OSMOSE Pipeline V2.1
  ├── TopicSegmenter
  ├── ConceptExtractor (NER + Clustering + LLM)
  ├── SemanticIndexer (canonicalisation cross-lingual)
  └── ConceptLinker (DocumentRole)
      ↓
  Proto-KG UNIQUEMENT
  ├── Neo4j (concepts canoniques + relations sémantiques)
  └── Qdrant "concepts_proto" (embeddings concepts)
```

**Avantages** :
- ✅ Concepts canoniques cross-linguals (FR "authentification" = EN "authentication")
- ✅ Relations cross-documents avec DocumentRole
- ✅ Hiérarchies de concepts (parent-child)
- ✅ Une seule source de vérité (Proto-KG)
- ✅ USP établi vs concurrents

---

## 🛠️ Implémentation

### Fichiers Créés

#### 1. `src/knowbase/ingestion/osmose_integration.py` (500 lignes)
**Service d'intégration OSMOSE avec les pipelines d'ingestion**

**Composants** :
- `OsmoseIntegrationConfig` : Configuration feature flags
- `OsmoseIntegrationService` : Orchestration pipeline OSMOSE
- `OsmoseIntegrationResult` : Résultats avec métriques
- `_store_osmose_results()` : Stockage Proto-KG (Neo4j + Qdrant)

**Features** :
- Feature flags (`ENABLE_OSMOSE_PIPELINE`, `OSMOSE_FOR_PPTX`, `OSMOSE_FOR_PDF`)
- Filtres (min/max text length)
- Timeout configurable
- Métriques détaillées
- Gestion d'erreurs gracieuse

**Stockage Proto-KG** :
```python
# Neo4j: Concepts canoniques + relations
await proto_kg_service.create_canonical_concept(
    canonical_name="authentication",
    concept_type="PRACTICE",
    unified_definition="Unified definition across languages...",
    aliases=["authentification", "Authentifizierung"],
    languages=["en", "fr", "de"],
    source_documents=[document_id],
    parent_concept="security",
    quality_score=0.92
)

# Qdrant concepts_proto: Embeddings multilingues
embedding = embedder.encode([f"{canonical_name}. {definition}"])
qdrant_client.upsert(collection_name="concepts_proto", points=[point])
```

---

#### 2. `src/knowbase/api/services/proto_kg_service.py` (350 lignes)
**Service Neo4j pour gérer le Proto-KG**

**Méthodes** :
- `create_canonical_concept()` : Créer nœud CanonicalConcept
- `create_concept_relation()` : Créer relation sémantique
- `_create_parent_child_relation()` : Hiérarchie concepts
- `get_concept_by_name()` : Récupérer concept
- `get_concept_relations()` : Récupérer relations (depth-first)

**Schema Neo4j** :
```cypher
// Nœud Concept Canonique
(c:CanonicalConcept {
    canonical_name: "authentication",
    tenant_id: "default",
    concept_type: "PRACTICE",
    unified_definition: "...",
    aliases: ["authentification", "..."],
    languages: ["en", "fr", "de"],
    source_documents: ["doc_123", "doc_456"],
    quality_score: 0.92,
    created_at: datetime()
})

// Relations
(parent:CanonicalConcept)-[:PARENT_OF]->(child:CanonicalConcept)
(source:CanonicalConcept)-[:RELATED_TO {document_ids: [...], document_roles: [...]}]->(target:CanonicalConcept)
```

---

### Pipelines Modifiés

#### 3. `src/knowbase/ingestion/pipelines/pdf_pipeline.py`
**Ligne ~1086-1147 : Ajout OSMOSE Pure**

**Modifications** :
- ❌ **Supprimé** : Ingestion Qdrant "knowbase" (commenté pour l'instant)
- ❌ **Supprimé** : Ingestion Neo4j entities/relations (commenté)
- ✅ **Ajouté** : Appel OSMOSE après extraction texte
- ✅ **Ajouté** : Logging détaillé résultats OSMOSE
- ✅ **Ajouté** : Gestion d'erreurs (raise si OSMOSE échoue)

**Flux** :
```
PDF → MegaParse (text) → OSMOSE Pipeline → Proto-KG
```

---

#### 4. `src/knowbase/ingestion/pipelines/pptx_pipeline.py`
**À MODIFIER : Ligne ~1816-2198 (PHASE 3)**

**Plan de modification** (voir `pptx_pipeline_osmose.py`) :
1. Construire texte complet depuis `slides_data`
2. Appeler OSMOSE au lieu de Phase 3 legacy
3. Supprimer ingestion Qdrant `ingest_chunks()` (ligne 1803)
4. Supprimer toute la Phase 3 Neo4j (lignes 1818-2198)

**Flux** :
```
PPTX → Slides Text → OSMOSE Pipeline → Proto-KG
```

---

## 🔧 Configuration

### Variables d'Environnement

```bash
# .env

# OSMOSE Feature Flags
ENABLE_OSMOSE_PIPELINE=true       # Activer OSMOSE globalement
OSMOSE_FOR_PPTX=true              # OSMOSE sur PPTX
OSMOSE_FOR_PDF=true               # OSMOSE sur PDF

# Filtres
OSMOSE_MIN_TEXT_LENGTH=500        # Skip si < 500 chars
OSMOSE_MAX_TEXT_LENGTH=1000000    # Skip si > 1M chars

# Performance
OSMOSE_TIMEOUT_SECONDS=300        # 5 minutes max par document
OSMOSE_ENABLE_HIERARCHY=true      # Construire hiérarchies
OSMOSE_ENABLE_RELATIONS=true      # Extraire relations

# Storage
OSMOSE_STORE_PROTO_KG=true        # Stocker dans Proto-KG
OSMOSE_PROTO_KG_COLLECTION=concepts_proto  # Collection Qdrant

# Multi-tenancy
OSMOSE_DEFAULT_TENANT=default     # Tenant par défaut

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

---

## 📈 Avantages OSMOSE Pure

### Fonctionnel
- ✅ **Cross-lingual unification** : FR "authentification" = EN "authentication" = DE "Authentifizierung"
- ✅ **Relations cross-documents** : Savoir quels documents DEFINES vs IMPLEMENTS vs AUDITS un concept
- ✅ **Hiérarchies automatiques** : "Two-Factor Authentication" → "Authentication" → "Security"
- ✅ **Quality scoring** : Filtrage concepts de qualité pour promotion vers KG production

### Technique
- ✅ **Architecture simplifiée** : Une seule source de vérité (Proto-KG)
- ✅ **Pas de duplication** : Pas de Qdrant "knowbase" + "concepts_proto"
- ✅ **Performance** : Un seul passage sur le document
- ✅ **Maintenance** : Moins de code legacy à maintenir

### Business
- ✅ **USP KnowWhere** : Différenciation claire vs Microsoft Copilot / Google Gemini
- ✅ **Language-agnostic** : Recherche unifiée FR/EN/DE/etc.
- ✅ **Intelligence sémantique** : Comprend les concepts, pas juste les mots-clés

---

## 🧪 Tests Requis

### 1. Tests Unitaires

**À créer :**
- `tests/ingestion/test_osmose_integration.py`
  - Configuration loading
  - Feature flags
  - Text length filters
  - Error handling

**Commande** :
```bash
docker-compose exec app pytest tests/ingestion/test_osmose_integration.py -v
```

---

### 2. Tests Intégration PDF

**À créer :**
- `tests/ingestion/test_pdf_osmose_integration.py`
  - PDF simple (< 10 pages)
  - PDF multilingual (FR + EN content)
  - PDF long (> 100 pages avec timeout)
  - Validation Proto-KG storage

**Test manuel** :
```bash
# Ajouter un PDF test dans data/docs_in/
cp test.pdf data/docs_in/

# Traiter avec OSMOSE
docker-compose exec app python -m knowbase.ingestion.pipelines.pdf_pipeline

# Vérifier Neo4j
docker-compose exec neo4j cypher-shell -u neo4j -p password
> MATCH (c:CanonicalConcept) RETURN count(c);
> MATCH (c:CanonicalConcept)-[r]->(c2) RETURN type(r), count(r);

# Vérifier Qdrant
curl http://localhost:6333/collections/concepts_proto
```

---

### 3. Tests Intégration PPTX

**À créer :**
- `tests/ingestion/test_pptx_osmose_integration.py`
  - PPTX simple (< 10 slides)
  - PPTX multilingual
  - PPTX avec Vision vs Text-only
  - Validation Proto-KG storage

**Test manuel** :
```bash
# Ajouter un PPTX test dans data/docs_in/
cp test.pptx data/docs_in/

# Traiter avec OSMOSE (après modification pptx_pipeline.py)
docker-compose exec app python -m knowbase.ingestion.pipelines.pptx_pipeline

# Vérifier Proto-KG (même commandes que PDF)
```

---

### 4. Tests End-to-End

**Scénarios critiques** :
1. **Cross-lingual unification** :
   - Ingérer 3 docs (FR, EN, DE) mentionnant "authentication"
   - Vérifier qu'un seul concept canonique "authentication" existe
   - Vérifier que les 3 documents sont liés au concept

2. **DocumentRole classification** :
   - Ingérer un standard ("ISO 27001 defines authentication")
   - Ingérer un projet ("Project X implements authentication")
   - Ingérer un audit ("Audit Y validates authentication")
   - Vérifier les 3 DocumentRole différents

3. **Hiérarchie concepts** :
   - Vérifier relations PARENT_OF automatiques
   - Ex: "2FA" → "Authentication" → "Security"

---

## 🚀 Prochaines Étapes

### Phase 1.5.1 : Validation (En cours)

- [x] Créer `osmose_integration.py` (500 lignes)
- [x] Créer `proto_kg_service.py` (350 lignes)
- [x] Modifier `pdf_pipeline.py` (OSMOSE Pure ajouté)
- [ ] Modifier `pptx_pipeline.py` (code prêt dans `pptx_pipeline_osmose.py`)
- [ ] Créer tests unitaires
- [ ] Tests manuels PDF (1 document)
- [ ] Tests manuels PPTX (1 document)
- [ ] Validation Proto-KG storage (Neo4j + Qdrant)

**Durée estimée** : 2-3 jours

---

### Phase 1.5.2 : API de Recherche (Semaine prochaine)

**Objectif** : Adapter l'API de recherche pour utiliser Proto-KG au lieu de Qdrant "knowbase"

**Modifications** :
- `src/knowbase/api/routers/search.py` : Recherche dans "concepts_proto"
- `src/knowbase/api/services/search_service.py` : Utiliser concepts canoniques
- Nouveau endpoint : `/search/concepts` (recherche sémantique concepts)
- Nouveau endpoint : `/concepts/{name}/relations` (graph traversal)

**Tests** :
- Recherche cross-lingual : Query "authentification" → trouve concept "authentication"
- Recherche avec DocumentRole : Filter "only documents that DEFINE this concept"
- Graph traversal : Trouver concepts liés (depth 2)

**Durée estimée** : 3-4 jours

---

### Phase 1.5.3 : Production (Semaine +2)

**Objectif** : Déploiement production + Documentation

**Tasks** :
- Documentation API Proto-KG
- Guide migration pour utilisateurs
- Métriques Prometheus/Grafana
- Monitoring Neo4j + Qdrant
- Cleanup collections legacy (optionnel)

**Durée estimée** : 2-3 jours

---

## 📝 Documentation Complémentaire

### Fichiers de Référence

- **Phase 1 Complete** : `doc/phases/PHASE1_SEMANTIC_CORE.md`
- **Intégration Plan** : `doc/INTEGRATION_INGESTION_OSMOSE.md` (obsolète - remplacé par ce fichier)
- **Architecture Technique** : `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md`
- **Roadmap Globale** : `doc/OSMOSE_ROADMAP_INTEGREE.md`

---

## 🎯 Métriques de Succès

### Objectifs Phase 1.5

- ✅ **Architecture simplifiée** : 1 seul système de storage (Proto-KG)
- ✅ **Cross-lingual unification** : >90% accuracy sur test set multilingual
- ✅ **Performance** : <30s/document sur documents moyens (10-50 pages)
- ✅ **Quality Score** : >85% concepts avec score >0.8
- ✅ **Relations** : >5 relations/concept en moyenne

---

## ⚠️ Points d'Attention

### Collections Legacy

**Les collections Qdrant suivantes sont obsolètes** :
- `knowbase` : Chunks textuels (remplacé par concepts_proto)
- `rfp_qa` : Q&A RFP (à migrer vers Proto-KG si nécessaire)

**Action recommandée** :
- Garder temporairement pour backward compatibility
- Ajouter warning dans logs si utilisées
- Plan de dépréciation : 3-6 mois

---

### Neo4j Schema

**Anciens nœuds** (Phase 3 legacy) :
- `Entity` : Entités extraites directement (remplacé par CanonicalConcept)
- `Relation` : Relations directes (remplacé par relations sémantiques)
- `Fact` : Facts extraits (à voir si conservation nécessaire)
- `Episode` : Épisodes d'ingestion (obsolète)

**Action recommandée** :
- Cleanup Neo4j database (DROP anciens nœuds)
- Seuls nœuds conservés : CanonicalConcept + relations sémantiques

---

## 🔧 Troubleshooting

### Erreur: "OSMOSE processing failed: Text too short"

**Cause** : Document < 500 chars (filtre `OSMOSE_MIN_TEXT_LENGTH`)

**Solution** :
- Vérifier extraction texte (MegaParse / pptx-parser)
- Ajuster `OSMOSE_MIN_TEXT_LENGTH` si nécessaire
- Skip documents trop courts (normal)

---

### Erreur: "Proto-KG storage failed"

**Causes possibles** :
1. Neo4j non disponible (vérifier `docker-compose ps`)
2. Qdrant "concepts_proto" non créé (vérifier `/collections`)
3. Timeout LLM (augmenter `OSMOSE_TIMEOUT_SECONDS`)

**Debug** :
```bash
# Vérifier Neo4j
docker-compose logs neo4j | tail -100

# Vérifier Qdrant
curl http://localhost:6333/collections/concepts_proto

# Tester connexion Neo4j
docker-compose exec neo4j cypher-shell -u neo4j -p password
> RETURN "Connection OK";
```

---

### Performance: >60s/document

**Optimisations possibles** :
1. Réduire `OSMOSE_ENABLE_HIERARCHY=false` (skip hiérarchie)
2. Réduire `OSMOSE_ENABLE_RELATIONS=false` (skip relations)
3. Augmenter workers LLM (parallélisation)
4. Utiliser modèle plus rapide (gpt-4o-mini au lieu de gpt-4)

---

**Version:** 1.0
**Date:** 2025-10-14
**Status:** Architecture implémentée - Validation requise
**Prochaine étape:** Tests unitaires + Tests manuels PDF/PPTX
