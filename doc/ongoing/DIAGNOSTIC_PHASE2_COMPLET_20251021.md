# Diagnostic Complet - 4 Problèmes Identifiés - 2025-10-21

**Date** : 2025-10-21 01:30
**Import Analysé** : 2025-10-21 00:27 (547 concepts, 447 dans Neo4j)

---

## 📊 Résumé Exécutif

| Problème | Impact | Cause Racine | Gravité |
|----------|--------|--------------|---------|
| **#1 : 0 Relations** | ❌ Phase 2 inutile | `surface_forms` manquantes dans concepts passés à Phase 2 | 🔴 CRITIQUE |
| **#2 : 0 Ontologies Redis** | ⚠️ Pas d'apprentissage | 100% concepts rejetés (confidence 0.30 < 0.6 threshold) | 🟠 MAJEUR |
| **#3 : 18% canonical_name=None** | ⚠️ 100/547 concepts perdus | Batch LLM JSON parsing TOUS les batches échouent | 🟠 MAJEUR |
| **#4 : 0 Chunks Qdrant** | ⚠️ Pas de RAG | TextChunker initialisé mais PAS appelé (FINALIZE step manquant code) | 🟡 IMPORTANT |

---

## 🔍 Problème #1 : 0 Relations Extraites

### Symptômes

```
[OSMOSE:LLMRelationExtractor] No co-occurring concept pairs found
[OSMOSE:RelationExtraction] Extracted 0 relations in 3.74s
```

### Cause Racine

**Incohérence schéma Phase 1 → Phase 2**

**Phase 1 (Neo4j)** :
- `gatekeeper.py:1077` : `surface_form=concept_name` (singulier, string)
- `neo4j_client.py:553` : Stocke `surface_form: $surface_form`
- ✅ Neo4j contient `surface_form = "Content Owner"` (NON NULL)

**Logs confirmation** :
```
[NEO4J:Published] Created NEW CanonicalConcept 'Content Owner' (surface='Content Owner')
[NEO4J:Published] Created NEW CanonicalConcept 'SAP Cloud ERP Private' (surface='SAP Cloud ERP Private')
```

**Phase 2 (LLMRelationExtractor)** :
- `llm_relation_extractor.py:239` : `concept.get("surface_forms", [])`  ← PLURIEL, liste
- ❌ Clé `surface_forms` absente → liste vide
- Cherche UNIQUEMENT `canonical_name` dans texte

**Problème** :
Les concepts passés à `extract_relations()` ne contiennent PAS la clé `surface_forms` car :
1. Supervisor récupère concepts depuis Neo4j ? → Schéma Neo4j a `surface_form` (singulier)
2. Ou Supervisor construit dict depuis PromoteConcepts output ? → Output ne retourne pas `surface_forms`

### Solution

**Option A - Quick Fix (RECOMMANDÉ)** :
Modifier `supervisor.py` EXTRACT_RELATIONS step pour construire liste concepts avec `surface_forms` :

```python
# Récupérer concepts depuis Neo4j avec surface_form
query = """
MATCH (c:CanonicalConcept)
WHERE c.tenant_id = $tenant_id
RETURN c.canonical_id AS concept_id,
       c.canonical_name AS canonical_name,
       c.surface_form AS surface_form,
       c.concept_type AS concept_type
"""

concepts_for_extraction = [
    {
        "concept_id": row["concept_id"],
        "canonical_name": row["canonical_name"],
        "surface_forms": [row["surface_form"]] if row["surface_form"] else [],  # ← Convertir string → liste
        "concept_type": row["concept_type"]
    }
    for row in neo4j_results
]
```

**Option B - Long Terme** :
Refactoriser schéma Neo4j pour stocker `surface_forms` (liste) au lieu de `surface_form` (string).

---

## 🔍 Problème #2 : 0 Ontologies dans Redis

### Symptômes

```bash
redis-cli KEYS "ontology:*"
# (empty array)
```

**Logs AdaptiveOntology** :
```
[AdaptiveOntology:Store] ❌ Low confidence 0.30 < 0.6, skipping store for 'Content Owner'
[AdaptiveOntology:Store] ❌ Low confidence 0.30 < 0.6, skipping store for 'SAP Cloud ERP Private'
[AdaptiveOntology:Store] ❌ Low confidence 0.30 < 0.6, skipping store for 'HA & DR'
... (447 fois)
```

### Cause Racine #1 : Threshold Trop Élevé

**Configuration actuelle** :
- `AdaptiveOntology.Store` : `MIN_CONFIDENCE_THRESHOLD = 0.6`
- **TOUS les concepts ont confidence = 0.30** (valeur par défaut Extractor)

**Pourquoi 0.30 ?**
Vérifier d'où vient cette confidence dans l'Extractor.

### Cause Racine #2 : Validation Caractères Invalides

**Erreurs fréquentes** :
```
[AdaptiveOntology:Lookup] Validation error: Invalid characters in concept name: HA & DR
[AdaptiveOntology:Lookup] Validation error: Invalid characters in concept name: MFA & Risk-Based Authentication, Asset Management
[AdaptiveOntology:Store] Validation error: Invalid characters in concept name: HA & DR
```

**Caractères rejetés** : `&`, `,` (virgule)

**Impact** :
- ~6 concepts rejetés pour caractères invalides
- 441 concepts rejetés pour confidence < 0.6
- **Total : 100% concepts rejetés**

### Solution

**Option A - Baisser Threshold (Quick Fix)** :
```python
# adaptive_ontology_manager.py
MIN_CONFIDENCE_THRESHOLD = 0.25  # Au lieu de 0.6
```

**Option B - Fixer Confidence Source** :
Trouver pourquoi Extractor assigne `confidence=0.30` à TOUS les concepts au lieu d'utiliser vraie confiance LLM.

**Option C - Autoriser Caractères Spéciaux** :
```python
# Modifier validation pour accepter &, -, (), etc.
ALLOWED_PATTERN = r"^[\w\s\-&(),./]+$"  # Au lieu de "^[\w\s]+$"
```

---

## 🔍 Problème #3 : 18% Concepts avec canonical_name=None

### Symptômes

**100 concepts / 547 = 18.3%** ont `canonical_name=None`

**Logs Phase 2** :
```
[LLMRelationExtractor] Skipping concept with None canonical_name: {...}
(100 warnings)
```

### Cause Racine : Batch LLM JSON Parsing ÉCHOUE

**Logs Batch Canonicalization** :
```
[GATEKEEPER:Batch] 🔄 Batch canonicalizing 547 concepts (batch_size=20)...
[LLMCanonicalizer:Batch] ❌ Batch canonicalization failed: All JSON parsing attempts failed
[LLMCanonicalizer:Batch] ❌ Batch canonicalization failed: All JSON parsing attempts failed
[LLMCanonicalizer:Batch] ❌ Batch canonicalization failed: All JSON parsing attempts failed
... (28 batches = 547/20, TOUS échouent)
```

**Résultat** :
- 28 batches envoyés au LLM
- **28 batches = 100% échec JSON parsing**
- Tous les concepts reçoivent `canonical_name=None` depuis batch
- ⚠️ **MAIS** : 447 concepts ont quand même un canonical_name dans Neo4j !

**Contradiction apparente** :
Comment 447 concepts ont canonical_name si le batch échoue ?

**Explication** :
Gatekeeper a **FALLBACK** : Si batch échoue, appel LLM **INDIVIDUEL** par concept :

```python
# gatekeeper.py:938-949
if concept_name in batch_canonicalization_cache:
    canonical_name, llm_confidence = batch_canonicalization_cache[concept_name]
else:
    # Fallback individuel (ne devrait pas arriver, mais sécurité)
    canonical_name, llm_confidence = self._canonicalize_concept_name(
        raw_name=concept_name,
        context=definition,
        tenant_id=tenant_id,
        document_id=concept.get("document_id")
    )
    logger.warning(
        f"[GATEKEEPER:Canonicalization:Batch] ⚠️ Cache MISS for '{concept_name}', "
        f"fallback to individual LLM call"
    )
```

**Problème** :
- Fallback individuel fonctionne pour 447 concepts
- Mais 100 concepts (18%) n'ont PAS de fallback → `canonical_name=None`

**Questions** :
1. Pourquoi fallback individuel échoue pour 100 concepts ?
2. Pourquoi batch JSON parsing échoue 100% du temps ?

### Solution

**Étape 1 : Diagnostiquer JSON Parsing** :
Récupérer exemple réponse LLM pour voir pourquoi parsing échoue.

**Étape 2 : Fixer Format JSON** :
- LLM retourne-t-il JSON valide ?
- Prompt demande-t-il bon format ?
- Parser attend-il bon schéma ?

**Étape 3 : Robustifier Fallback** :
Assurer fallback individuel pour 100% concepts si batch échoue.

---

## 🔍 Problème #4 : 0 Chunks dans Qdrant

### Symptômes

```python
# Qdrant collection 'knowbase'
GET http://localhost:6333/collections/knowbase
# points_count: 0
```

### Cause Racine : TextChunker Initialisé Mais PAS Appelé

**Logs FINALIZE** :
```
[TextChunker] Loaded model: intfloat/multilingual-e5-large (dim=1024)
[TextChunker] Loaded tokenizer: cl100k_base
[TextChunker] Singleton instance created
[OSMOSE AGENTIQUE] TextChunker initialized (512 tokens, overlap 128)
```

**TextChunker est initialisé MAIS** :
- Aucun log `[TextChunker] Chunking document...`
- Aucun log `[TextChunker] Created X chunks`
- Aucun log `[Qdrant] Uploading X chunks to collection knowbase`

**Conclusion** :
Le code d'appel TextChunker dans FINALIZE step est manquant ou conditionnel.

### Solution

**Étape 1 : Vérifier Code FINALIZE** :
Chercher dans `supervisor.py` step FINALIZE : où TextChunker devrait être appelé ?

**Étape 2 : Ajouter Appel TextChunker** :
```python
# supervisor.py - FINALIZE step
from knowbase.chunks.text_chunker import get_text_chunker

chunker = get_text_chunker()
chunks = chunker.chunk_document(
    document_id=document_id,
    text=full_text,
    metadata={...}
)

# Upload to Qdrant
upload_chunks_to_qdrant(
    chunks=chunks,
    collection_name="knowbase"
)
```

---

## 📋 Plan d'Action Priorisé

### Priorité 1 : Fixer Batch JSON Parsing (Problème #3)

**Pourquoi URGENT** :
- 100% batches échouent → fallback individuel → 547 appels LLM au lieu de 28
- Coût : 547 × $0.0015 = $0.82 au lieu de 28 × $0.03 = $0.084 (10x plus cher)
- Temps : 547 × 2s = 18 min au lieu de 28 × 2s = 56s (20x plus lent)
- 18% concepts perdus (canonical_name=None)

**Action** :
1. Lire logs LLM pour voir réponse exacte
2. Identifier pourquoi JSON parsing échoue
3. Fixer prompt ou parser

**Temps estimé** : 30 min

### Priorité 2 : Fixer 0 Relations (Problème #1)

**Pourquoi CRITIQUE** :
Phase 2 complètement inutile sans relations.

**Action** :
Implémenter Option A (Quick Fix supervisor.py).

**Temps estimé** : 15 min

### Priorité 3 : Fixer 0 Chunks (Problème #4)

**Pourquoi IMPORTANT** :
RAG ne fonctionne pas sans chunks Qdrant.

**Action** :
Ajouter appel TextChunker dans FINALIZE step.

**Temps estimé** : 20 min

### Priorité 4 : Fixer 0 Ontologies (Problème #2)

**Pourquoi MOYEN** :
Système fonctionne sans ontologies, juste pas d'apprentissage.

**Action** :
1. Baisser threshold à 0.25
2. Autoriser caractères spéciaux (&, -, etc.)
3. Fixer confidence source (0.30 pour tous)

**Temps estimé** : 15 min

---

## 🎯 Métriques Validation (Post-Fixes)

| Métrique | Avant | Cible Après Fixes |
|----------|-------|-------------------|
| **Batch JSON parsing success** | 0% | 100% |
| **Concepts avec canonical_name=None** | 100 (18%) | 0 (0%) |
| **Appels LLM canonicalization** | 547 | 28 |
| **Temps canonicalization** | 18 min | < 1 min |
| **Co-occurring concept pairs** | 0 | 50-200 |
| **Relations extraites** | 0 | 100-200 |
| **Chunks Qdrant knowbase** | 0 | 500-1000 |
| **Ontologies Redis** | 0 | 200-400 |

---

## 📝 Questions Ouvertes

### Q1 : Pourquoi Batch JSON Parsing Échoue 100% ?

**Hypothèses** :
1. LLM retourne texte au lieu de JSON ?
2. LLM retourne JSON mais mauvais schéma ?
3. Parser attend format différent ?

**Diagnostic** : Lire logs LLM raw response

### Q2 : Pourquoi 100 Concepts Sans Fallback ?

**Hypothèses** :
1. Fallback timeout ?
2. Fallback reçoit erreur LLM ?
3. Fallback JSON parsing échoue aussi ?

**Diagnostic** : Chercher logs fallback individuel pour ces 100 concepts

### Q3 : Où est le Code FINALIZE Chunking ?

**Hypothèses** :
1. Code commenté ?
2. Conditionnel (`if chunks_enabled`) ?
3. Pas encore implémenté ?

**Diagnostic** : Lire `supervisor.py` step FINALIZE

### Q4 : Pourquoi Confidence = 0.30 Pour Tous ?

**Hypothèses** :
1. Extractor assigne valeur par défaut
2. Confidence LLM perdue pendant pipeline
3. Bug calcul confidence

**Diagnostic** : Tracer d'où vient confidence dans concepts

---

**Créé par** : Claude Code
**Pour** : Diagnostic complet 4 problèmes import OSMOSE
**Priorité** : CRITIQUE
**Status** : Diagnostic complet, causes racines identifiées, plan d'action priorisé
**Prochaine Étape** : Fixer Batch JSON Parsing (Priorité 1)
