# Optimisation Performance - Traitement Mono-Document

**Date:** 2025-10-24
**Objectif:** Accélérer considérablement le traitement d'un **seul document** via parallélisation interne

---

## 🎯 Problème Identifié

**Situation actuelle:** Le traitement d'un document PPTX de 50 slides prend ~120-180 secondes

**Cause:** Traitement **100% séquentiel** des segments/chunks :
```python
# Actuel dans extractor/orchestrator.py (ligne 164)
for idx, segment in enumerate(state.segments):  # ❌ SÉQUENTIEL !
    # Extraction LLM (~5-10s par segment)
    prepass_result = await prepass_analyzer.execute(...)
    extraction_result = await extraction_agent.execute(...)
```

**Impact:** Pour un document avec 10 segments → 10 × 10s = **100 secondes** d'attente !

---

## 🚀 Solution: Parallélisation Interne

### Gain Attendu

| Métrique | Actuel (Séquentiel) | Optimisé (Parallèle) | Amélioration |
|----------|---------------------|----------------------|--------------|
| 10 segments × 10s | 100s | 15-20s | **5-7x plus rapide** |
| Document 50 slides | 150-180s | 30-40s | **4-5x plus rapide** |
| Utilisation CPU | 10-20% | 70-90% | Meilleur ROI |

---

## 📊 Analyse du Pipeline Actuel

### Flux de Traitement (Séquentiel)

```
Document PPTX
    ↓
Segmentation (rapide, ~2s)
    ↓
Pour chaque segment (SÉQUENTIEL ❌):
    ↓
    Prepass Analysis (~3-5s)  ← Appel LLM
    ↓
    Extraction (~5-10s)       ← Appel LLM
    ↓
    Save to Proto-KG (~1s)    ← I/O Neo4j
    ↓
Total: N segments × 10s = 100-150s
```

### Goulots d'Étranglement

1. **Extractor Orchestrator** (`src/knowbase/agents/extractor/orchestrator.py:164`)
   ```python
   for idx, segment in enumerate(state.segments):  # ❌ SÉQUENTIEL
       prepass_result = await prepass_analyzer.execute(...)
       extraction_result = await extraction_agent.execute(...)
   ```

2. **Miner Relations** (`src/knowbase/agents/miner/miner.py:270`)
   ```python
   for topic_id, segment_concepts in segments.items():  # ❌ SÉQUENTIEL
       # Création relations entre concepts
   ```

3. **Chunking + Embedding** (`src/knowbase/agents/supervisor/supervisor.py:459`)
   ```python
   for i, chunk in enumerate(chunks):  # ❌ SÉQUENTIEL
       points.append({"embedding": chunk.embedding, ...})
   ```

---

## 🛠️ Optimisations à Implémenter

### Niveau 1: Paralléliser Extraction par Segment ⭐⭐⭐

**Impact:** **5-7x plus rapide** pour l'extraction

#### Modification: `src/knowbase/agents/extractor/orchestrator.py`

**Avant (ligne 164):**
```python
for idx, segment in enumerate(state.segments):
    logger.debug(f"[EXTRACTOR] Processing segment {idx+1}/{len(state.segments)}")

    # Prepass Analysis
    prepass_input = PrepassAnalyzerInput(...)
    prepass_result = await prepass_analyzer.execute(prepass_input)

    # Extraction
    extraction_input = ExtractionInput(...)
    extraction_result = await extraction_agent.execute(extraction_input)

    # Save to Proto-KG
    self._save_to_proto_kg(extraction_result, segment_id)
```

**Après (parallélisé avec `asyncio.gather`):**
```python
import asyncio
from typing import List, Tuple

async def _process_segment(
    self,
    idx: int,
    segment: dict,
    state: AgentState,
    prepass_analyzer,
    extraction_agent
) -> Tuple[int, dict]:
    """Traite un segment en parallèle."""
    logger.debug(f"[EXTRACTOR] Processing segment {idx+1}")

    # Prepass Analysis
    prepass_input = PrepassAnalyzerInput(
        segment_text=segment.get("text", ""),
        segment_id=segment.get("segment_id"),
        topic_label=segment.get("topic_label", "unknown"),
        tenant_id=state.tenant_id
    )
    prepass_result = await prepass_analyzer.execute(prepass_input)

    # Extraction
    extraction_input = ExtractionInput(
        segment_text=segment.get("text", ""),
        segment_id=segment.get("segment_id"),
        prepass_context=prepass_result.model_dump(),
        tenant_id=state.tenant_id
    )
    extraction_result = await extraction_agent.execute(extraction_input)

    return idx, extraction_result


# Dans execute() - remplacer la boucle for par:
logger.info(f"[EXTRACTOR] 🚀 Processing {len(state.segments)} segments IN PARALLEL")

# Créer toutes les tâches d'extraction
extraction_tasks = [
    self._process_segment(idx, segment, state, prepass_analyzer, extraction_agent)
    for idx, segment in enumerate(state.segments)
]

# Exécuter TOUTES les extractions en parallèle
segment_results = await asyncio.gather(*extraction_tasks)

# Sauvegarder tous les résultats (peut aussi être parallélisé)
logger.info(f"[EXTRACTOR] ✅ {len(segment_results)} segments extracted, saving to Proto-KG")
for idx, extraction_result in segment_results:
    segment_id = state.segments[idx].get("segment_id")
    self._save_to_proto_kg(extraction_result, segment_id, state)
```

**Gain:** Si vous avez 10 segments de 10s chacun :
- Avant: 10 × 10s = **100s**
- Après: max(10s) + overhead = **15s** (avec rate limiting LLM)

---

### Niveau 2: Paralléliser Embeddings Qdrant ⭐⭐

**Impact:** **3-4x plus rapide** pour l'indexation

#### Modification: `src/knowbase/agents/supervisor/supervisor.py`

**Avant (ligne 459):**
```python
points = []
for i, chunk in enumerate(chunks):
    points.append({
        "id": chunk.get("chunk_id"),
        "vector": chunk.get("embedding", []),
        "payload": {...}
    })
```

**Après (batch parallèle):**
```python
from concurrent.futures import ThreadPoolExecutor
import asyncio

def _create_point(chunk, state):
    """Crée un point Qdrant (peut être CPU-intensif)."""
    return {
        "id": chunk.get("chunk_id"),
        "vector": chunk.get("embedding", []),
        "payload": {
            "tenant_id": state.tenant_id,
            "document_id": state.document_id,
            "text": chunk.get("text", ""),
            # ... autres champs
        }
    }

# Paralléliser la création des points avec ThreadPoolExecutor
loop = asyncio.get_event_loop()
with ThreadPoolExecutor(max_workers=8) as executor:
    points = await asyncio.gather(*[
        loop.run_in_executor(executor, _create_point, chunk, state)
        for chunk in chunks
    ])

logger.info(f"[SUPERVISOR] ✅ {len(points)} points created in parallel")

# Uploader par batches
batch_size = 100
for i in range(0, len(points), batch_size):
    batch = points[i:i+batch_size]
    qdrant_client.upsert(collection_name=collection, points=batch)
```

**Gain:** 100 chunks
- Avant: 100 × 0.1s = **10s**
- Après: 100 / 8 cores = **1.5s**

---

### Niveau 3: Paralléliser Requêtes Neo4j ⭐

**Impact:** **2-3x plus rapide** pour les sauvegardes

#### Modification: `src/knowbase/agents/extractor/orchestrator.py`

**Problème:** Sauvegardes Neo4j séquentielles dans `_save_to_proto_kg()`

**Solution:** Utiliser transactions batch Neo4j

```python
def _save_all_to_proto_kg_batch(
    self,
    extraction_results: List[dict],
    state: AgentState
) -> None:
    """Sauvegarde tous les concepts en une seule transaction batch."""

    # Préparer tous les concepts
    all_concepts = []
    for result in extraction_results:
        concepts = result.get("concepts", [])
        all_concepts.extend(concepts)

    if not all_concepts:
        return

    # Transaction batch unique avec UNWIND
    query = """
    UNWIND $concepts AS concept
    MERGE (c:ProtoConcept {
        canonical_name: concept.canonical_name,
        tenant_id: $tenant_id
    })
    SET c.concept_type = concept.concept_type,
        c.surface_form = concept.surface_form,
        c.definition = concept.definition,
        c.confidence = concept.confidence,
        c.document_id = $document_id,
        c.segment_id = concept.segment_id,
        c.updated_at = datetime()
    """

    with self.neo4j_client.session() as session:
        session.run(
            query,
            concepts=all_concepts,
            tenant_id=state.tenant_id,
            document_id=state.document_id
        )

    logger.info(f"[EXTRACTOR] ✅ {len(all_concepts)} concepts saved in SINGLE batch transaction")
```

**Gain:** 100 concepts
- Avant: 100 × 0.05s = **5s**
- Après: 1 transaction = **0.3s**

---

## 🎛️ Configuration Infrastructure

### Variables d'Environnement Optimisées

**Fichier:** `.env.production`

```bash
# =====================================================
# PERFORMANCE - TRAITEMENT MONO-DOCUMENT
# =====================================================

# LLM Rate Limits (augmenter pour parallélisation)
OPENAI_MAX_RPM=500           # Requêtes par minute (tier 1: 500, tier 5: 10000)
ANTHROPIC_MAX_RPM=100        # Requêtes par minute

# Parallélisation Extraction
MAX_PARALLEL_SEGMENTS=10     # Nombre de segments traités en parallèle (NOUVEAU)
                              # Limité par rate limits LLM

# Neo4j Connection Pool
NEO4J_MAX_CONNECTION_POOL_SIZE=50   # Connexions simultanées
NEO4J_MAX_TRANSACTION_RETRY_TIME=30 # Timeout transactions

# Qdrant Batch Processing
QDRANT_BATCH_SIZE=100        # Taille des batches upload
QDRANT_UPLOAD_PARALLELISM=4  # Uploads parallèles (NOUVEAU)

# ThreadPoolExecutor
MAX_WORKER_THREADS=8         # Threads I/O (embeddings, parsing)
```

### Instance EC2 Recommandée

Pour maximiser la parallélisation **interne** d'un document :

**Optimal:** `c5.4xlarge`
- 16 vCPU (nécessaire pour paralléliser 10+ segments)
- 32 GB RAM
- Réseau: 10 Gbps
- **Coût:** ~$0.68/heure

**Pourquoi plus de vCPU ?**
- 10 segments en parallèle = 10 appels LLM simultanés
- Chaque appel LLM = 1 thread d'attente + parsing JSON
- Plus de vCPU = meilleure gestion concurrence asyncio

---

## 📈 Gains Cumulés

### Scénario: Document PPTX 50 Slides

**Pipeline actuel (séquentiel):**
```
Segmentation:        5s
Extraction (10 seg): 100s   ← GOULOT
Mining:              10s
Gatekeeper:          15s
Chunking:            10s
Embedding + Upload:  20s    ← GOULOT
----------------------------
TOTAL:               160s
```

**Pipeline optimisé (parallèle):**
```
Segmentation:        5s
Extraction (10 seg): 15s    ← 7x plus rapide (parallèle)
Mining:              3s     ← 3x plus rapide (batch Neo4j)
Gatekeeper:          15s
Chunking:            5s
Embedding + Upload:  5s     ← 4x plus rapide (ThreadPool)
----------------------------
TOTAL:               48s    ← 3.3x AMÉLIORATION GLOBALE
```

**Amélioration:** **160s → 48s** = **Gain de 112 secondes (70%)** 🚀

---

## 🔧 Guide d'Implémentation

### Étape 1: Ajouter Parallélisation Extraction

**Fichier:** `src/knowbase/agents/extractor/orchestrator.py`

1. Ajouter méthode `_process_segment()` (voir code Niveau 1)
2. Remplacer boucle `for` par `asyncio.gather()`
3. Ajouter variable env `MAX_PARALLEL_SEGMENTS`

**Test:**
```bash
# Vérifier parallélisation dans logs
docker-compose logs -f ingestion-worker | grep "Processing segment"

# Devrait afficher tous les segments presque simultanément
# Au lieu de : segment 1 → segment 2 → segment 3...
# Voir : segment 1, 2, 3... (tous ensemble)
```

### Étape 2: Ajouter ThreadPoolExecutor pour Embeddings

**Fichier:** `src/knowbase/agents/supervisor/supervisor.py`

1. Ajouter `ThreadPoolExecutor` pour création points Qdrant
2. Utiliser `loop.run_in_executor()` pour I/O
3. Configurer `max_workers=8`

**Test:**
```python
import time

start = time.time()
# Votre code d'embedding...
duration = time.time() - start

logger.info(f"Embedding {len(chunks)} chunks took {duration:.2f}s")
# Avant: ~20s pour 100 chunks
# Après: ~5s pour 100 chunks
```

### Étape 3: Optimiser Transactions Neo4j

**Fichier:** `src/knowbase/agents/extractor/orchestrator.py`

1. Remplacer `_save_to_proto_kg()` par `_save_all_to_proto_kg_batch()`
2. Utiliser `UNWIND` pour batch insert
3. Une seule transaction pour tous les concepts

**Test:**
```cypher
// Vérifier temps d'insertion
PROFILE
UNWIND $concepts AS concept
MERGE (c:ProtoConcept {canonical_name: concept.name, tenant_id: 'default'})
SET c += concept.properties
```

### Étape 4: Configurer Variables d'Environnement

**Fichier:** `.env.production`

```bash
# Ajuster selon vos rate limits LLM
MAX_PARALLEL_SEGMENTS=10
OPENAI_MAX_RPM=500
ANTHROPIC_MAX_RPM=100

# Optimiser I/O
MAX_WORKER_THREADS=8
NEO4J_MAX_CONNECTION_POOL_SIZE=50
QDRANT_BATCH_SIZE=100
```

### Étape 5: Déployer et Tester

```powershell
# 1. Rebuild images (car modifications code)
docker-compose build app ingestion-worker

# 2. Push vers ECR
.\scripts\aws\build-and-push-ecr.ps1

# 3. Détruire stack
.\scripts\aws\destroy-cloudformation.ps1 -StackName "knowbase-test"

# 4. Redéployer avec instance boostée
.\scripts\aws\deploy-cloudformation.ps1 `
    -StackName "knowbase-perf" `
    -InstanceType "c5.4xlarge" `
    -KeyPairName "my-key" `
    -KeyPath ".\my-key.pem"
```

### Étape 6: Mesurer les Performances

**Script de test:**
```bash
#!/bin/bash
# test-single-doc-perf.sh

DOC_PATH="test-50-slides.pptx"
EC2_IP="<IP_EC2>"

echo "Testing single document performance..."
start_time=$(date +%s)

curl -X POST http://$EC2_IP:8000/ingest/pptx \
  -F "file=@$DOC_PATH" \
  -w "\nHTTP Status: %{http_code}\nTotal Time: %{time_total}s\n"

end_time=$(date +%s)
duration=$((end_time - start_time))

echo "Total duration: ${duration}s"
```

**Métriques à surveiller:**
```bash
# 1. Logs extraction parallèle
ssh ubuntu@<IP> "docker-compose logs ingestion-worker | grep 'Processing segment' | tail -20"

# 2. Utilisation CPU (devrait être élevée pendant extraction)
ssh ubuntu@<IP> "docker stats --no-stream | grep knowbase-worker"

# 3. Nombre de requêtes LLM simultanées (Redis)
ssh ubuntu@<IP> "docker exec knowbase-redis redis-cli INFO stats | grep instantaneous_ops"
```

---

## ⚠️ Limites et Précautions

### 1. Rate Limits LLM

**Problème:** OpenAI Tier 1 = 500 RPM (requêtes par minute)

**Impact sur parallélisation:**
- 10 segments en parallèle = 20 requêtes (prepass + extraction)
- Si 1 requête = 10s → 20 requêtes en parallèle OK
- Si trop de requêtes simultanées → erreur 429 (rate limit)

**Solution:**
```python
import asyncio
from asyncio import Semaphore

# Limiter nombre de requêtes LLM simultanées
MAX_CONCURRENT_LLM_CALLS = 5  # Ajuster selon tier
llm_semaphore = Semaphore(MAX_CONCURRENT_LLM_CALLS)

async def _process_segment_with_limit(self, segment, ...):
    async with llm_semaphore:
        # Seulement 5 appels LLM simultanés max
        result = await self._process_segment(segment, ...)
    return result
```

### 2. Mémoire RAM

**Problème:** 10 segments en parallèle = 10× la mémoire

**Recommandation:**
- c5.4xlarge (32 GB RAM) : 10-15 segments parallèles OK
- t3.2xlarge (32 GB RAM) : 5-8 segments max

**Monitoring:**
```bash
# Surveiller utilisation mémoire
watch -n 1 'docker stats --no-stream | grep knowbase-worker'
```

### 3. Coûts LLM

**Attention:** Parallélisation = plus de requêtes/minute

**Impact coûts:** Si vous avez 100 documents/jour :
- Avant: Traitement étalé sur 3-4 heures
- Après: Traitement concentré sur 1 heure → plus de RPM

**Vérifier quotas:**
- OpenAI: https://platform.openai.com/account/limits
- Anthropic: https://console.anthropic.com/settings/limits

---

## 🎯 Résumé Configuration Recommandée

### Pour c5.4xlarge (16 vCPU, 32 GB RAM)

**docker-compose.ecr.yml:**
```yaml
ingestion-worker:
  # PAS de replicas (1 seul worker pour traiter 1 doc à la fois)
  deploy:
    resources:
      limits:
        cpus: '12.0'  # Allouer plus de CPU pour parallélisation interne
        memory: 16G   # Plus de RAM pour segments en parallèle
```

**.env.production:**
```bash
# Parallélisation INTERNE d'un document
MAX_PARALLEL_SEGMENTS=10
MAX_WORKER_THREADS=8

# Rate limits
OPENAI_MAX_RPM=500
ANTHROPIC_MAX_RPM=100

# Neo4j & Qdrant optimisés
NEO4J_MAX_CONNECTION_POOL_SIZE=50
QDRANT_BATCH_SIZE=100
```

**Modifications code:**
- ✅ `extractor/orchestrator.py` : `asyncio.gather()` pour segments
- ✅ `supervisor/supervisor.py` : `ThreadPoolExecutor` pour embeddings
- ✅ `extractor/orchestrator.py` : Batch Neo4j avec `UNWIND`

**Gain attendu:** **3-4x plus rapide** pour un document unique 🚀

---

## 📚 Références

- [asyncio.gather() documentation](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather)
- [ThreadPoolExecutor](https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor)
- [Neo4j Batch Operations](https://neo4j.com/docs/cypher-manual/current/clauses/unwind/)
- [OpenAI Rate Limits](https://platform.openai.com/docs/guides/rate-limits)

---

**Auteur:** Claude Code
**Version:** 1.0
**Prochaine étape:** Implémenter parallélisation extraction (Niveau 1) pour gain immédiat de 5-7x
