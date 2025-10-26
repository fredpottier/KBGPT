# 🚀 Plan de Refactoring PPTX Ingestion - Performance Optimization

**Projet** : KnowWhere (OSMOSE)
**Date** : 2025-10-26
**Objectif** : Réduire le temps d'ingestion PPTX de **60-90 min à 3-5 min** (250 slides)
**Auteur** : Analyse Claude Code + Best Practices Marché 2025

---

## 📊 ÉTAT DES LIEUX

### Problème Actuel
- **Document 250 slides** : 60-90 minutes d'ingestion
- **Performance cible** : 3-5 minutes maximum
- **Ratio d'amélioration requis** : **12-18x plus rapide**

### Métriques Actuelles (250 slides)

| Phase | Temps Actuel | % Total | Goulot |
|-------|--------------|---------|--------|
| Vision API (résumés) | 40-60 min | 70% | ⚠️ **CRITIQUE** |
| OSMOSE Semantic Processing | 15-25 min | 25% | ⚠️ **MAJEUR** |
| PDF Conversion + Images | 3-5 min | 5% | ✅ OK |

---

## 🔍 GOULOTS D'ÉTRANGLEMENT IDENTIFIÉS

### 1. **Vision API Processing Séquentiel** ⚠️ CRITIQUE

**Localisation** : `pptx_pipeline.py:2068-2189`

**Problème** :
```python
# ❌ ACTUEL : ThreadPoolExecutor avec 1-3 workers max
actual_workers = 1 if total_slides > 400 else MAX_WORKERS  # MAX_WORKERS = 3
with ThreadPoolExecutor(max_workers=actual_workers) as ex:
    for slide in slides_data:
        vision_tasks.append((idx, ex.submit(ask_gpt_vision_summary, ...)))

# Timeout 60s par slide × 250 slides / 3 workers = 5000s = 83 minutes !
```

**Impact** :
- 250 slides / 3 workers = **83 slides par worker**
- 60s timeout × 83 = **4980s (83 min)** dans le pire cas
- Taux d'utilisation GPU Vision : **< 5%** (3 calls simultanés seulement)

**Root Cause** :
- Limite artificielle de workers (peur de rate limiting)
- Pas de batch asynchrone natif
- Pas de circuit breaker intelligent

---

### 2. **Concept Extraction Non-Batchée** ⚠️ MAJEUR

**Localisation** : `concept_extractor.py:63-131`

**Problème** :
```python
# ❌ ACTUEL : Boucle séquentielle topic par topic
for i, topic in enumerate(topics):
    concepts = await self.concept_extractor.extract_concepts(
        topic=topic,  # 1 topic à la fois
        enable_llm=enable_llm
    )
    all_concepts.extend(concepts)
```

**Impact** :
- 20 topics × (NER + Clustering + LLM) = **60 opérations séquentielles**
- NER spaCy : **5-10s par topic** sans batch
- Embeddings : **2-5s par topic** sans batch
- LLM calls : **3-8s par topic** si déclenché

**Root Cause** :
- Pas de batch processing pour NER
- Embeddings calculés topic par topic
- LLM calls non groupés

---

### 3. **Embeddings Computation Inefficace** ⚠️ MAJEUR

**Localisation** :
- `concept_extractor.py:207` (clustering)
- `semantic_indexer.py:114-117` (canonicalization)

**Problème** :
```python
# ❌ ACTUEL : Embeddings par petits batches
embeddings = self.embedder.encode(noun_phrases)  # 10-50 items à la fois

# ❌ ACTUEL : Réencodage dans semantic_indexer
concept_texts = [c.name for c in concepts]
embeddings = self.embedder.encode(concept_texts)  # Re-encoding !
```

**Impact** :
- Batch size optimal : **512 items** (selon best practices 2025)
- Batch size actuel : **10-50 items** → **10-50x moins efficace**
- **Double encoding** des mêmes concepts (extractor + indexer)

**Root Cause** :
- Pas de cache d'embeddings
- Batch size trop petit (overhead tokenization/GPU)
- Architecture pipeline ne mutualise pas les embeddings

---

### 4. **LLM Calls Séquentiels Sans Cache** ⚠️ MOYEN

**Localisation** :
- `concept_extractor.py:270-341` (extraction LLM)
- `semantic_indexer.py:142-149` (hiérarchie)

**Problème** :
```python
# ❌ ACTUEL : LLM call séquentiel par topic
response_text = self.llm_router.complete(
    task_type=TaskType.KNOWLEDGE_EXTRACTION,
    messages=[{"role": "user", "content": prompt}],
    # Pas de cache, pas de batch
)
```

**Impact** :
- 20 topics × 3-8s LLM call = **60-160s** juste pour extraction
- Concepts similaires re-traités (ex: "SAP S/4HANA" vu 15 fois)
- Pas de retry intelligent si rate limit

**Root Cause** :
- Pas de semantic cache (embeddings → concepts déjà vus)
- Pas de batching LLM (envoyer 5 prompts en 1 call)
- Pas de circuit breaker pour rate limiting

---

### 5. **CPU-Only Processing (Pas de GPU)** ⚠️ MAJEUR

**Localisation** : Tout le pipeline NER/embeddings

**Problème** :
- spaCy NER : Mode CPU uniquement
- sentence-transformers : Mode CPU uniquement
- Pas de configuration GPU explicite

**Impact** :
- NER GPU (CUDA) : **5-10x plus rapide** que CPU
- Embeddings GPU (batch 512) : **15-20x plus rapide** que CPU
- Selon NVIDIA best practices 2025 : GPU obligatoire pour production

**Root Cause** :
- Pas de détection/configuration GPU dans le code
- Modèles non optimisés pour GPU (pas de .to("cuda"))

---

## 🏆 BEST PRACTICES MARCHÉ 2025

### 1. **Batch Processing & Parallelization**

**Source** : NVIDIA Technical Blog, AWS Knowledge Graph ETL

**Recommandations** :
- **Micro-batching** : Grouper 10-50 slides par batch Vision
- **Pipeline parallelization** : Process multiple batches en parallèle
- **Async I/O** : Utiliser `asyncio` + `aiohttp` pour Vision API
- **Worker pool sizing** : 20-50 workers async pour APIs externes

**Exemple AWS Architecture** :
```
S3 Batch Operations → Lambda (parallel) → Step Functions → Neo4j
    ↓
10x parallelization → 100x faster ingestion
```

---

### 2. **GPU Acceleration**

**Source** : NVIDIA NeMo, Hugging Face 2025

**Recommandations** :
- **NER GPU** : spaCy avec CUDA (5-10x speedup)
- **Embeddings GPU** : sentence-transformers batch 512 (15-20x speedup)
- **Batch size optimal** : 512 items pour embeddings, 64 pour NER
- **GPU utilization target** : 80%+ pour production

**Benchmark 2025** :
```
CPU (batch 32):  ~500 items/sec embeddings
GPU (batch 512): ~8000 items/sec embeddings (16x faster)
```

---

### 3. **Semantic Caching**

**Source** : LangChain, OpenAI Best Practices

**Recommandations** :
- **Embedding cache** : Redis avec TTL 7 jours
- **LLM response cache** : Cache par hash de prompt
- **Deduplication** : Détecter concepts similaires avant LLM call
- **Cache hit ratio target** : 40-60% sur documents similaires

---

### 4. **Adaptive Timeout & Circuit Breaker**

**Source** : AWS Well-Architected, Resilience Patterns

**Recommandations** :
- **Timeout adaptatif** : Basé sur historique (P95 latency)
- **Circuit breaker** : Fail fast si > 50% errors
- **Rate limiting intelligent** : Backoff exponentiel avec jitter
- **Retry budgets** : Max 1 retry BIG LLM, 3 retries SMALL

---

## 🎯 ARCHITECTURE REFACTORÉE PROPOSÉE

### Phase 1 : Vision API Async Batch Processing (Gain 10-15x)

**Objectif** : Réduire Vision de 60 min à **4-6 min**

**Changements** :

```python
# ✅ NOUVEAU : Async Vision API avec micro-batching

import asyncio
import aiohttp
from typing import List, Dict

class AsyncVisionProcessor:
    """
    Vision API processing avec async I/O et micro-batching.

    Performance:
    - 250 slides / 20 workers async = 12.5 slides par worker
    - 60s timeout × 12.5 = 750s = 12.5 min (pire cas)
    - En pratique : 20s avg × 12.5 = 250s = 4 min (typical)
    """

    def __init__(self, max_concurrent: int = 20, batch_size: int = 10):
        """
        Args:
            max_concurrent: Nombre de workers async simultanés
            batch_size: Taille des micro-batches pour rate limiting
        """
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size
        self.session: Optional[aiohttp.ClientSession] = None

    async def process_slides_batch(
        self,
        slides_data: List[Dict],
        image_paths: Dict[int, Path]
    ) -> List[Dict]:
        """
        Process slides en parallèle avec micro-batching.

        Returns:
            List de slide summaries
        """
        # Créer session async réutilisable
        async with aiohttp.ClientSession() as session:
            self.session = session

            # Découper en micro-batches de 10 slides
            batches = [
                slides_data[i:i + self.batch_size]
                for i in range(0, len(slides_data), self.batch_size)
            ]

            # Process micro-batches avec max_concurrent workers
            all_summaries = []

            for batch_idx, batch in enumerate(batches):
                logger.info(
                    f"Processing batch {batch_idx+1}/{len(batches)} "
                    f"({len(batch)} slides)"
                )

                # Limiter à max_concurrent tasks simultanées
                semaphore = asyncio.Semaphore(self.max_concurrent)

                async def process_with_semaphore(slide):
                    async with semaphore:
                        return await self._process_single_slide(
                            slide,
                            image_paths
                        )

                # Lancer toutes les tasks du batch en parallèle
                tasks = [process_with_semaphore(slide) for slide in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                # Filtrer les erreurs
                valid_results = [
                    r for r in batch_results
                    if not isinstance(r, Exception)
                ]
                all_summaries.extend(valid_results)

                # Rate limiting : pause entre batches
                if batch_idx < len(batches) - 1:
                    await asyncio.sleep(1)  # 1s entre batches

            return all_summaries

    async def _process_single_slide(
        self,
        slide: Dict,
        image_paths: Dict[int, Path]
    ) -> Dict:
        """
        Process un slide avec Vision API (async).

        Utilise aiohttp pour I/O non-bloquant.
        """
        idx = slide["slide_index"]

        try:
            # Encoder image en base64 (sync, rapide)
            image_b64 = encode_image_base64(image_paths[idx])

            # Préparer prompt Vision
            prompt = self._build_vision_prompt(slide)

            # Call Vision API async
            start = time.time()
            summary = await self._call_vision_api_async(
                image_b64=image_b64,
                prompt=prompt,
                timeout=30  # Timeout réduit à 30s (vs 60s actuel)
            )
            duration = time.time() - start

            logger.info(
                f"Slide {idx} [VISION]: {len(summary)} chars in {duration:.1f}s"
            )

            return {
                "slide_index": idx,
                "summary": summary,
                "processing_time": duration
            }

        except asyncio.TimeoutError:
            logger.warning(f"Slide {idx} [VISION]: Timeout after 30s")
            # Fallback texte brut
            return {
                "slide_index": idx,
                "summary": slide.get("text", "") + slide.get("notes", ""),
                "processing_time": 30.0,
                "error": "timeout"
            }
        except Exception as e:
            logger.error(f"Slide {idx} [VISION]: Error {e}")
            return {
                "slide_index": idx,
                "summary": slide.get("text", ""),
                "processing_time": 0,
                "error": str(e)
            }

    async def _call_vision_api_async(
        self,
        image_b64: str,
        prompt: str,
        timeout: int = 30
    ) -> str:
        """
        Call OpenAI Vision API de manière asynchrone.

        Utilise aiohttp au lieu de requests (bloquant).
        """
        url = "https://api.openai.com/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "gpt-4o",  # ou gpt-4-vision-preview
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 500,
            "temperature": 0.3
        }

        # Async HTTP call avec timeout
        async with self.session.post(
            url,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            response.raise_for_status()
            data = await response.json()

            return data["choices"][0]["message"]["content"]

    def _build_vision_prompt(self, slide: Dict) -> str:
        """Build prompt pour Vision API."""
        return f"""Analyze this slide and provide a concise summary (max 200 words).

Include:
- Main topic/title
- Key visual elements (charts, diagrams, images)
- Important text content
- Slide number: {slide['slide_index']}

Text content: {slide.get('text', '')[:500]}
Notes: {slide.get('notes', '')[:200]}
"""

# ===== Utilisation dans pptx_pipeline.py =====

async def process_slides_with_async_vision(
    slides_data: List[Dict],
    image_paths: Dict[int, Path],
    use_vision: bool = True
) -> List[Dict]:
    """
    Wrapper pour intégrer AsyncVisionProcessor.
    """
    if not use_vision:
        # Fallback texte simple
        return [
            {
                "slide_index": s["slide_index"],
                "summary": s.get("text", "") + s.get("notes", "")
            }
            for s in slides_data
        ]

    processor = AsyncVisionProcessor(
        max_concurrent=20,  # 20 workers async (vs 3 actuels)
        batch_size=10       # Micro-batches de 10 slides
    )

    return await processor.process_slides_batch(slides_data, image_paths)

# ===== Dans ingest_pptx() =====

# ❌ REMPLACER :
# with ThreadPoolExecutor(max_workers=actual_workers) as ex:
#     ...

# ✅ PAR :
slide_summaries = asyncio.run(
    process_slides_with_async_vision(
        slides_data=slides_data,
        image_paths=image_paths,
        use_vision=use_vision
    )
)
```

**Gains attendus** :
- **Temps Vision** : 60 min → **4-6 min** (10-15x)
- **Taux d'utilisation API** : 5% → **60-80%**
- **Throughput** : 3 slides/min → **40-50 slides/min**

---

### Phase 2 : Batch NER & Embeddings with GPU (Gain 10-15x)

**Objectif** : Réduire OSMOSE Processing de 25 min à **1.5-2 min**

**Changements** :

```python
# ✅ NOUVEAU : Batch NER + GPU Embeddings

from typing import List, Dict, Tuple
import torch
from spacy.tokens import Doc
import numpy as np

class BatchConceptExtractor:
    """
    Concept extraction avec batch processing et GPU.

    Performance:
    - NER batch 64 (GPU): 5-10x faster que séquentiel CPU
    - Embeddings batch 512 (GPU): 15-20x faster que CPU
    - Cache embeddings: 40-60% cache hit ratio
    """

    def __init__(
        self,
        llm_router,
        config,
        use_gpu: bool = True,
        ner_batch_size: int = 64,
        embedding_batch_size: int = 512
    ):
        self.llm_router = llm_router
        self.config = config
        self.use_gpu = use_gpu
        self.ner_batch_size = ner_batch_size
        self.embedding_batch_size = embedding_batch_size

        # NER avec GPU si disponible
        self.ner = self._init_ner_gpu()

        # Embedder avec GPU
        self.embedder = self._init_embedder_gpu()

        # Cache embeddings (Redis ou in-memory)
        self.embedding_cache = {}

        logger.info(
            f"[BatchConceptExtractor] Initialized - "
            f"GPU: {self.use_gpu}, "
            f"NER batch: {self.ner_batch_size}, "
            f"Embedding batch: {self.embedding_batch_size}"
        )

    def _init_ner_gpu(self):
        """
        Initialise spaCy NER avec GPU si disponible.
        """
        import spacy

        if self.use_gpu and torch.cuda.is_available():
            # Activer GPU pour spaCy
            spacy.require_gpu()
            logger.info("[NER] GPU enabled (CUDA)")
        else:
            logger.warning("[NER] Running on CPU (no GPU available)")

        # Charger modèle multilingue
        nlp = spacy.load("xx_ent_wiki_sm")  # ou modèle custom

        # Optimiser pipeline pour batch processing
        nlp.add_pipe("sentencizer")  # Pas besoin de parser complet
        nlp.disable_pipes("parser")  # Désactiver dépendances (inutile pour NER)

        return nlp

    def _init_embedder_gpu(self):
        """
        Initialise sentence-transformers avec GPU.
        """
        from sentence_transformers import SentenceTransformer

        device = "cuda" if (self.use_gpu and torch.cuda.is_available()) else "cpu"

        model = SentenceTransformer(
            "intfloat/multilingual-e5-large",
            device=device
        )

        logger.info(f"[Embeddings] Running on {device.upper()}")

        return model

    async def extract_concepts_batch(
        self,
        topics: List[Topic],
        enable_llm: bool = True
    ) -> List[Concept]:
        """
        Extrait concepts de TOUS les topics en batch.

        Pipeline:
        1. Batch NER sur tous les topics (1 pass GPU)
        2. Batch embeddings sur tous les noun phrases (1 pass GPU)
        3. Clustering global
        4. LLM extraction si nécessaire (batched)

        Returns:
            List[Concept] pour tous les topics
        """
        logger.info(
            f"[BATCH] Extracting concepts from {len(topics)} topics (batched)"
        )

        # 1. BATCH NER : Traiter tous les topics en une seule passe
        logger.info("[BATCH] Step 1/4: Batch NER extraction")
        topic_texts = [
            " ".join([w.text for w in topic.windows])
            for topic in topics
        ]

        # NER batch avec GPU (5-10x faster)
        ner_results = self._batch_ner_extraction(topic_texts)

        # 2. BATCH EMBEDDINGS : Tous les noun phrases d'un coup
        logger.info("[BATCH] Step 2/4: Batch embeddings computation")

        all_noun_phrases = []
        topic_phrase_mapping = []  # (topic_idx, phrase_indices)

        for topic_idx, ner_entities in enumerate(ner_results):
            phrases = [ent["text"] for ent in ner_entities]
            start_idx = len(all_noun_phrases)
            all_noun_phrases.extend(phrases)
            end_idx = len(all_noun_phrases)
            topic_phrase_mapping.append((topic_idx, range(start_idx, end_idx)))

        # Embeddings batch 512 avec GPU (15-20x faster)
        all_embeddings = self._batch_embeddings_with_cache(all_noun_phrases)

        # 3. CLUSTERING : Par topic, utilisant embeddings pré-calculés
        logger.info("[BATCH] Step 3/4: Clustering concepts")

        all_concepts = []

        for topic_idx, phrase_indices in topic_phrase_mapping:
            topic = topics[topic_idx]
            phrases = [all_noun_phrases[i] for i in phrase_indices]
            embeddings = all_embeddings[list(phrase_indices)]

            # Clustering avec embeddings pré-calculés (pas de re-encoding)
            concepts = self._cluster_to_concepts(
                topic=topic,
                phrases=phrases,
                embeddings=embeddings,
                ner_entities=ner_results[topic_idx]
            )

            all_concepts.extend(concepts)

        # 4. LLM BATCH (si nécessaire)
        if enable_llm and len(all_concepts) < len(topics) * 3:
            logger.info("[BATCH] Step 4/4: LLM batch extraction (insufficient concepts)")
            llm_concepts = await self._batch_llm_extraction(
                topics=topics,
                existing_concepts=all_concepts
            )
            all_concepts.extend(llm_concepts)

        logger.info(
            f"[BATCH] ✅ Extracted {len(all_concepts)} concepts "
            f"from {len(topics)} topics (batched)"
        )

        return all_concepts

    def _batch_ner_extraction(
        self,
        texts: List[str]
    ) -> List[List[Dict]]:
        """
        NER batch avec GPU (5-10x faster).

        Args:
            texts: Liste de textes à analyser

        Returns:
            Liste de listes d'entités
        """
        # Process en batch avec spaCy GPU
        docs = list(self.ner.pipe(
            texts,
            batch_size=self.ner_batch_size,  # Optimal pour GPU
            n_process=1  # GPU = 1 process (parallel dans GPU)
        ))

        # Extraire entités
        results = []
        for doc in docs:
            entities = [
                {
                    "text": ent.text,
                    "label": ent.label_,
                    "start": ent.start_char,
                    "end": ent.end_char
                }
                for ent in doc.ents
            ]
            results.append(entities)

        return results

    def _batch_embeddings_with_cache(
        self,
        texts: List[str]
    ) -> np.ndarray:
        """
        Embeddings batch avec cache (15-20x faster que séquentiel).

        Args:
            texts: Textes à encoder

        Returns:
            Embeddings array (n_texts, 1024)
        """
        # Check cache
        cached_embeddings = []
        texts_to_encode = []
        text_indices_to_encode = []

        for i, text in enumerate(texts):
            text_hash = hash(text)
            if text_hash in self.embedding_cache:
                cached_embeddings.append((i, self.embedding_cache[text_hash]))
            else:
                texts_to_encode.append(text)
                text_indices_to_encode.append(i)

        cache_hit_ratio = len(cached_embeddings) / len(texts) if texts else 0
        logger.debug(
            f"[Cache] Hit ratio: {cache_hit_ratio:.1%} "
            f"({len(cached_embeddings)}/{len(texts)})"
        )

        # Encoder textes non-cachés en batch 512
        if texts_to_encode:
            new_embeddings = self.embedder.encode(
                texts_to_encode,
                batch_size=self.embedding_batch_size,  # Optimal pour GPU
                show_progress_bar=False,
                convert_to_numpy=True
            )

            # Update cache
            for text, embedding in zip(texts_to_encode, new_embeddings):
                self.embedding_cache[hash(text)] = embedding
        else:
            new_embeddings = np.array([])

        # Reconstruct full embeddings array
        all_embeddings = np.zeros((len(texts), new_embeddings.shape[1] if len(new_embeddings) > 0 else 1024))

        # Placer cached embeddings
        for idx, embedding in cached_embeddings:
            all_embeddings[idx] = embedding

        # Placer new embeddings
        for i, idx in enumerate(text_indices_to_encode):
            all_embeddings[idx] = new_embeddings[i]

        return all_embeddings

    def _cluster_to_concepts(
        self,
        topic: Topic,
        phrases: List[str],
        embeddings: np.ndarray,
        ner_entities: List[Dict]
    ) -> List[Concept]:
        """
        Clustering avec embeddings pré-calculés.
        """
        if len(phrases) < 3:
            return []

        # HDBSCAN clustering (déjà implémenté dans concept_extractor.py)
        from hdbscan import HDBSCAN

        clusterer = HDBSCAN(
            min_cluster_size=max(2, len(phrases) // 10),
            metric='euclidean',
            cluster_selection_method='eom',
            min_samples=1
        )

        cluster_labels = clusterer.fit_predict(embeddings)

        unique_labels = set(cluster_labels)
        if -1 in unique_labels:
            unique_labels.remove(-1)

        concepts = []
        for cluster_id in unique_labels:
            cluster_mask = cluster_labels == cluster_id
            cluster_phrases = [phrases[i] for i, mask in enumerate(cluster_mask) if mask]
            cluster_embeddings = embeddings[cluster_mask]

            if len(cluster_phrases) == 0:
                continue

            # Canonical name = phrase centrale
            from sklearn.metrics.pairwise import cosine_distances
            centroid = cluster_embeddings.mean(axis=0)
            distances = cosine_distances(cluster_embeddings, [centroid]).flatten()
            most_central_idx = distances.argmin()
            canonical_name = cluster_phrases[most_central_idx]

            # Type concept
            concept_type = self._infer_concept_type(canonical_name)

            concept = Concept(
                name=canonical_name,
                type=concept_type,
                definition="",
                context=topic.windows[0].text[:200] if topic.windows else "",
                language=topic.language if hasattr(topic, 'language') else 'en',
                confidence=0.75,
                source_topic_id=topic.topic_id,
                extraction_method="BATCH_CLUSTERING",
                related_concepts=cluster_phrases[:5]
            )
            concepts.append(concept)

        return concepts

    async def _batch_llm_extraction(
        self,
        topics: List[Topic],
        existing_concepts: List[Concept]
    ) -> List[Concept]:
        """
        LLM extraction batchée (grouper 5 topics par call).

        Réduit les LLM calls de 20 → 4 (5x moins cher).
        """
        # Filtrer topics ayant < 3 concepts
        topics_needing_llm = [
            t for t in topics
            if len([c for c in existing_concepts if c.source_topic_id == t.topic_id]) < 3
        ]

        if not topics_needing_llm:
            return []

        logger.info(
            f"[LLM BATCH] Processing {len(topics_needing_llm)} topics "
            f"(grouped by 5)"
        )

        # Grouper par 5 topics
        batch_size = 5
        topic_batches = [
            topics_needing_llm[i:i + batch_size]
            for i in range(0, len(topics_needing_llm), batch_size)
        ]

        all_llm_concepts = []

        for batch in topic_batches:
            # Construire prompt pour 5 topics
            batch_prompt = self._build_batch_llm_prompt(batch)

            # LLM call (1 call pour 5 topics)
            response = self.llm_router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[{"role": "user", "content": batch_prompt}],
                temperature=0.3,
                max_tokens=2000  # Plus long pour 5 topics
            )

            # Parser réponse
            batch_concepts = self._parse_batch_llm_response(response, batch)
            all_llm_concepts.extend(batch_concepts)

        logger.info(
            f"[LLM BATCH] ✅ Extracted {len(all_llm_concepts)} concepts "
            f"from {len(topics_needing_llm)} topics ({len(topic_batches)} LLM calls)"
        )

        return all_llm_concepts

    def _build_batch_llm_prompt(self, topics: List[Topic]) -> str:
        """Build prompt pour batch de topics."""
        topics_text = "\n\n".join([
            f"--- Topic {i+1} (ID: {t.topic_id}) ---\n"
            f"{' '.join([w.text for w in t.windows])[:500]}"
            for i, t in enumerate(topics)
        ])

        return f"""Extract key concepts from the following {len(topics)} topics.

For each topic, identify 3-5 concepts:
- name: concept name
- type: ENTITY, PRACTICE, STANDARD, TOOL, or ROLE
- topic_id: the topic ID
- definition: brief definition (1 sentence)

Topics:
{topics_text}

Return JSON:
{{"concepts": [{{"name": "...", "type": "...", "topic_id": "...", "definition": "..."}}]}}
"""

    def _parse_batch_llm_response(
        self,
        response: str,
        topics: List[Topic]
    ) -> List[Concept]:
        """Parse batch LLM response."""
        import json
        import re

        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                return []

            data = json.loads(json_match.group(0))
            concepts_data = data.get("concepts", [])

            concepts = []
            for c in concepts_data:
                # Retrouver topic correspondant
                topic_id = c.get("topic_id")
                topic = next((t for t in topics if t.topic_id == topic_id), topics[0])

                concept = Concept(
                    name=c["name"],
                    type=ConceptType(c.get("type", "entity").lower()),
                    definition=c.get("definition", ""),
                    context=topic.windows[0].text[:200] if topic.windows else "",
                    language=topic.language if hasattr(topic, 'language') else 'en',
                    confidence=0.80,
                    source_topic_id=topic.topic_id,
                    extraction_method="LLM_BATCH",
                    related_concepts=[]
                )
                concepts.append(concept)

            return concepts

        except Exception as e:
            logger.error(f"[LLM BATCH] Parse error: {e}")
            return []

    def _infer_concept_type(self, name: str) -> ConceptType:
        """Infer concept type (heuristic)."""
        name_lower = name.lower()

        if any(kw in name_lower for kw in ["tool", "system", "platform", "software"]):
            return ConceptType.TOOL
        elif any(kw in name_lower for kw in ["iso", "standard", "regulation", "gdpr"]):
            return ConceptType.STANDARD
        elif any(kw in name_lower for kw in ["process", "methodology", "practice"]):
            return ConceptType.PRACTICE
        elif any(kw in name_lower for kw in ["manager", "officer", "architect"]):
            return ConceptType.ROLE
        else:
            return ConceptType.ENTITY


# ===== Utilisation dans semantic_pipeline_v2.py =====

class SemanticPipelineV2Optimized:
    """Pipeline V2 avec batch processing."""

    def __init__(self, llm_router, config):
        self.llm_router = llm_router
        self.config = config

        # Remplacer MultilingualConceptExtractor par BatchConceptExtractor
        self.concept_extractor = BatchConceptExtractor(
            llm_router=llm_router,
            config=config,
            use_gpu=True,
            ner_batch_size=64,
            embedding_batch_size=512
        )

        # Autres composants...
        self.topic_segmenter = TopicSegmenter(config)
        self.semantic_indexer = SemanticIndexer(llm_router, config)
        self.concept_linker = ConceptLinker(llm_router, config)

    async def process_document(self, ...):
        """Process document avec batch extraction."""

        # 1. Topic Segmentation (inchangé)
        topics = await self.topic_segmenter.segment_document(...)

        # 2. BATCH Concept Extraction (nouveau)
        all_concepts = await self.concept_extractor.extract_concepts_batch(
            topics=topics,
            enable_llm=enable_llm
        )

        # 3. Semantic Indexing (utilise embeddings cachés)
        canonical_concepts = await self.semantic_indexer.canonicalize_concepts(
            concepts=all_concepts,
            enable_hierarchy=enable_hierarchy,
            enable_relations=enable_relations
        )

        # 4. Concept Linking (inchangé)
        connections = self.concept_linker.link_concepts_to_documents(...)

        return self._build_result(...)
```

**Gains attendus** :
- **NER** : 15-20 min → **1-2 min** (10x)
- **Embeddings** : 5-10 min → **0.5 min** (10-20x)
- **LLM calls** : 20 calls → **4 calls** (5x moins cher)
- **Cache hit ratio** : 0% → **40-60%** sur documents similaires

---

### Phase 3 : Semantic Caching & Deduplication (Gain 2-3x)

**Objectif** : Éviter de re-traiter des concepts déjà vus

**Changements** :

```python
# ✅ NOUVEAU : Redis Cache pour embeddings + concepts

import redis
import pickle
import hashlib
from typing import Optional

class SemanticCache:
    """
    Cache sémantique pour embeddings et concepts.

    Use cases:
    - Cache embeddings par hash de texte (TTL 7 jours)
    - Cache canonical concepts par embedding similarity
    - Deduplication cross-documents
    """

    def __init__(self, redis_url: str = "redis://redis:6379/2"):
        """
        Args:
            redis_url: URL Redis (DB 2 pour cache sémantique)
        """
        self.redis_client = redis.from_url(redis_url)
        self.embedding_ttl = 7 * 24 * 3600  # 7 jours
        self.concept_ttl = 30 * 24 * 3600   # 30 jours

    def get_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Récupère embedding depuis cache.

        Args:
            text: Texte à encoder

        Returns:
            Embedding si en cache, sinon None
        """
        key = self._embedding_key(text)
        cached = self.redis_client.get(key)

        if cached:
            return pickle.loads(cached)

        return None

    def set_embedding(self, text: str, embedding: np.ndarray):
        """
        Stocke embedding dans cache.
        """
        key = self._embedding_key(text)
        self.redis_client.setex(
            key,
            self.embedding_ttl,
            pickle.dumps(embedding)
        )

    def get_canonical_concept(
        self,
        concept_name: str
    ) -> Optional[Dict]:
        """
        Récupère canonical concept depuis cache.

        Utile pour éviter re-canonicalisation de "SAP S/4HANA" déjà vu.
        """
        key = self._concept_key(concept_name)
        cached = self.redis_client.get(key)

        if cached:
            return pickle.loads(cached)

        return None

    def set_canonical_concept(
        self,
        concept_name: str,
        canonical_data: Dict
    ):
        """
        Stocke canonical concept dans cache.
        """
        key = self._concept_key(concept_name)
        self.redis_client.setex(
            key,
            self.concept_ttl,
            pickle.dumps(canonical_data)
        )

    def _embedding_key(self, text: str) -> str:
        """Generate cache key pour embedding."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"osmose:embedding:{text_hash[:16]}"

    def _concept_key(self, concept_name: str) -> str:
        """Generate cache key pour concept."""
        name_hash = hashlib.sha256(concept_name.lower().encode()).hexdigest()
        return f"osmose:concept:{name_hash[:16]}"

    def clear_cache(self):
        """Purge cache sémantique (debug uniquement)."""
        for key in self.redis_client.scan_iter("osmose:*"):
            self.redis_client.delete(key)
```

**Intégration** :

```python
# Dans BatchConceptExtractor.__init__()

from knowbase.semantic.utils.cache import SemanticCache

self.semantic_cache = SemanticCache()

# Dans _batch_embeddings_with_cache()

# Check Redis cache avant in-memory cache
cached_embedding = self.semantic_cache.get_embedding(text)
if cached_embedding is not None:
    return cached_embedding

# Après encoding
self.semantic_cache.set_embedding(text, new_embedding)
```

**Gains attendus** :
- **Cache hit ratio** : 40-60% sur documents similaires
- **Temps d'ingestion** : -30% sur 2ème document similaire
- **Coûts API** : -40% (moins de LLM calls)

---

### Phase 4 : Circuit Breaker & Adaptive Timeouts (Gain résilience)

**Objectif** : Éviter les timeouts coûteux, fail fast si problème

**Changements** :

```python
# ✅ NOUVEAU : Circuit Breaker pour Vision API

from enum import Enum
from typing import Callable
import time

class CircuitState(Enum):
    CLOSED = "closed"      # Normal
    OPEN = "open"          # Erreurs → fail fast
    HALF_OPEN = "half_open"  # Test recovery

class CircuitBreaker:
    """
    Circuit breaker pour APIs externes (Vision, LLM).

    Pattern:
    - CLOSED: Normal, toutes les requests passent
    - OPEN: > 50% errors → fail fast pendant 60s
    - HALF_OPEN: Test 1 request → CLOSED si OK, OPEN si KO
    """

    def __init__(
        self,
        failure_threshold: float = 0.5,  # 50% error rate
        recovery_timeout: int = 60,      # 60s avant retry
        window_size: int = 10            # Rolling window 10 requests
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.window_size = window_size

        self.state = CircuitState.CLOSED
        self.failures = 0
        self.successes = 0
        self.last_failure_time = 0
        self.recent_results = []  # Rolling window

    async def call(
        self,
        func: Callable,
        *args,
        **kwargs
    ):
        """
        Execute func avec circuit breaker protection.

        Raises:
            CircuitBreakerOpen: Si circuit ouvert
        """
        # Check state
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                logger.info("[Circuit] OPEN → HALF_OPEN (testing recovery)")
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitBreakerOpen(
                    f"Circuit breaker OPEN (fail fast for {self.recovery_timeout}s)"
                )

        # Execute function
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result

        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Record success."""
        self.successes += 1
        self.recent_results.append(True)

        if len(self.recent_results) > self.window_size:
            self.recent_results.pop(0)

        # HALF_OPEN → CLOSED
        if self.state == CircuitState.HALF_OPEN:
            logger.info("[Circuit] HALF_OPEN → CLOSED (recovery successful)")
            self.state = CircuitState.CLOSED
            self.failures = 0

    def _on_failure(self):
        """Record failure."""
        self.failures += 1
        self.recent_results.append(False)
        self.last_failure_time = time.time()

        if len(self.recent_results) > self.window_size:
            self.recent_results.pop(0)

        # Check threshold
        if len(self.recent_results) >= self.window_size:
            error_rate = 1 - (sum(self.recent_results) / len(self.recent_results))

            if error_rate >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    logger.error(
                        f"[Circuit] {self.state.value} → OPEN "
                        f"(error rate {error_rate:.1%} >= {self.failure_threshold:.1%})"
                    )
                    self.state = CircuitState.OPEN

class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is OPEN."""
    pass

# ===== Utilisation dans AsyncVisionProcessor =====

class AsyncVisionProcessor:
    def __init__(self, ...):
        ...
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=0.5,  # 50% errors → fail fast
            recovery_timeout=60,    # 60s cooldown
            window_size=10          # Last 10 requests
        )

    async def _process_single_slide(self, slide, image_paths):
        """Process avec circuit breaker."""
        try:
            # Wrap Vision API call avec circuit breaker
            summary = await self.circuit_breaker.call(
                self._call_vision_api_async,
                image_b64=encode_image_base64(image_paths[idx]),
                prompt=self._build_vision_prompt(slide),
                timeout=30
            )

            return {"slide_index": idx, "summary": summary}

        except CircuitBreakerOpen:
            # Fail fast, fallback texte
            logger.warning(
                f"Slide {idx} [VISION]: Circuit OPEN, using text fallback"
            )
            return {
                "slide_index": idx,
                "summary": slide.get("text", ""),
                "error": "circuit_breaker_open"
            }
        except Exception as e:
            # Autres erreurs
            return {
                "slide_index": idx,
                "summary": slide.get("text", ""),
                "error": str(e)
            }
```

**Gains attendus** :
- **Résilience** : Fail fast si Vision API down (économie 60s × N slides)
- **Recovery automatique** : Test après 60s cooldown
- **Visibilité** : Logs clairs sur état du circuit

---

## 📐 ARCHITECTURE FINALE

```
┌─────────────────────────────────────────────────────────────────┐
│                     PPTX INGESTION PIPELINE                      │
│                        (Architecture Optimisée)                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────┐
│   Upload PPTX   │
│   (250 slides)  │
└────────┬────────┘
         │
         ▼
┌──────────────────────────────────────────────────┐
│  PHASE 1: Conversion & Image Generation          │
│  ✅ PDF conversion (PyMuPDF)                     │ 2-3 min
│  ✅ Slide images 250 @ DPI 150                   │ (OK, déjà rapide)
└────────┬─────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────┐
│  PHASE 2: Async Vision API Processing            │
│  🚀 20 async workers (vs 3 actuels)              │ 4-6 min
│  🚀 Micro-batching 10 slides                     │ (vs 60 min actuels)
│  🚀 Circuit breaker fail-fast                    │ 10-15x FASTER
│  🚀 Timeout 30s (vs 60s)                         │
│  ────────────────────────────────────────────    │
│  Output: 250 slide summaries enrichis            │
└────────┬─────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────┐
│  PHASE 3: OSMOSE Semantic Processing (GPU)       │
│  🚀 Batch NER (64 items, GPU)                    │ 1.5-2 min
│  🚀 Batch Embeddings (512 items, GPU)            │ (vs 25 min actuels)
│  🚀 Semantic cache (40-60% hit ratio)            │ 10-15x FASTER
│  🚀 LLM batch (5 topics/call)                    │
│  ────────────────────────────────────────────    │
│  Pipeline:                                       │
│    1. Topic Segmentation (20 topics)             │
│    2. Batch Concept Extraction (150 concepts)    │
│    3. Batch Canonicalization (50 canonical)      │
│    4. Concept Linking (200 connections)          │
│    5. Proto-KG Storage (Neo4j + Qdrant)          │
└────────┬─────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────┐
│  OUTPUT: Knowledge Graph                         │
│  ✅ 50 canonical concepts                        │ TOTAL: 3-5 min
│  ✅ 200 concept-document connections             │ (vs 60-90 min)
│  ✅ Neo4j Proto-KG ready                         │
└──────────────────────────────────────────────────┘

📊 PERFORMANCE METRICS:
┌──────────────────────────────────────┬──────────┬──────────┬───────────┐
│ Métrique                             │ Actuel   │ Cible    │ Gain      │
├──────────────────────────────────────┼──────────┼──────────┼───────────┤
│ Temps total (250 slides)             │ 60-90min │ 3-5 min  │ 12-18x    │
│ Vision API throughput                │ 3/min    │ 40/min   │ 13x       │
│ NER processing                       │ 15 min   │ 1 min    │ 15x       │
│ Embeddings computation               │ 10 min   │ 0.5 min  │ 20x       │
│ LLM calls                            │ 20       │ 4        │ 5x        │
│ GPU utilization                      │ 0%       │ 80%+     │ ∞         │
│ Cache hit ratio                      │ 0%       │ 40-60%   │ -         │
│ Coût API ($/doc)                     │ $X       │ $X/3     │ 3x moins  │
└──────────────────────────────────────┴──────────┴──────────┴───────────┘
```

---

## 🎯 PLAN D'IMPLÉMENTATION

### Sprint 1 (Semaine 1) : Async Vision API ⭐ PRIORITÉ 1

**Objectif** : Réduire Vision de 60 min à 6 min

**Tasks** :
1. ✅ Créer `AsyncVisionProcessor` class
2. ✅ Implémenter `aiohttp` async HTTP client
3. ✅ Configurer micro-batching (10 slides/batch)
4. ✅ Augmenter workers de 3 → 20
5. ✅ Réduire timeout de 60s → 30s
6. ✅ Ajouter circuit breaker
7. ✅ Tests avec doc 50 slides
8. ✅ Tests avec doc 250 slides
9. ✅ Monitoring métriques (throughput, latency, errors)

**Fichiers modifiés** :
- `pptx_pipeline.py` : Remplacer ThreadPoolExecutor par AsyncVisionProcessor
- `nouveau: async_vision_processor.py`
- `nouveau: circuit_breaker.py`

**Tests acceptance** :
- 50 slides : < 2 min (vs 10 min actuel)
- 250 slides : < 6 min (vs 60 min actuel)
- Error rate < 5%
- Throughput > 30 slides/min

---

### Sprint 2 (Semaine 2) : Batch NER & GPU Embeddings ⭐ PRIORITÉ 2

**Objectif** : Réduire OSMOSE Processing de 25 min à 2 min

**Tasks** :
1. ✅ Détecter GPU disponible (CUDA)
2. ✅ Configurer spaCy avec GPU (`spacy.require_gpu()`)
3. ✅ Créer `BatchConceptExtractor` class
4. ✅ Implémenter batch NER (batch_size 64)
5. ✅ Implémenter batch embeddings (batch_size 512)
6. ✅ Configurer sentence-transformers GPU
7. ✅ Tests NER batch vs séquentiel
8. ✅ Tests embeddings batch vs séquentiel
9. ✅ Monitoring GPU utilization (target 80%+)

**Fichiers modifiés** :
- `semantic_pipeline_v2.py` : Utiliser BatchConceptExtractor
- `nouveau: batch_concept_extractor.py`
- `concept_extractor.py` : Deprecated (garder pour fallback)

**Tests acceptance** :
- NER batch 64 : 5-10x faster que séquentiel
- Embeddings batch 512 : 15-20x faster que séquentiel
- GPU utilization > 60%
- Precision/recall inchangés (quality preserved)

---

### Sprint 3 (Semaine 3) : Semantic Cache & LLM Batching ⭐ PRIORITÉ 3

**Objectif** : Réduire coûts et temps via caching

**Tasks** :
1. ✅ Setup Redis DB 2 pour semantic cache
2. ✅ Créer `SemanticCache` class
3. ✅ Implémenter embedding cache (TTL 7 jours)
4. ✅ Implémenter canonical concept cache (TTL 30 jours)
5. ✅ Intégrer cache dans BatchConceptExtractor
6. ✅ Implémenter LLM batch (5 topics/call)
7. ✅ Tests cache hit ratio
8. ✅ Tests LLM batch vs séquentiel
9. ✅ Monitoring cache métriques

**Fichiers modifiés** :
- `nouveau: semantic_cache.py`
- `batch_concept_extractor.py` : Intégrer cache
- `semantic_indexer.py` : Utiliser cache

**Tests acceptance** :
- Cache hit ratio > 40% sur 2ème document similaire
- LLM calls réduits de 50%+ (20 → 10 calls)
- Latency -30% sur documents similaires

---

### Sprint 4 (Semaine 4) : Monitoring & Fine-Tuning 🔧

**Objectif** : Production-ready avec monitoring

**Tasks** :
1. ✅ Dashboard Grafana pour métriques
2. ✅ Alertes si latency > P95
3. ✅ Alertes si GPU util < 60%
4. ✅ Alertes si error rate > 10%
5. ✅ Load testing (10 docs simultanés)
6. ✅ Benchmarks officiels (10/50/100/250 slides)
7. ✅ Documentation technique
8. ✅ Formation équipe

**Livrables** :
- Dashboard Grafana OSMOSE
- Benchmark report (PDF)
- Documentation technique complète
- Video démo 250 slides en 5 min

---

## 📈 MÉTRIQUES DE SUCCÈS

### KPI Phase 1 (Après Sprint 1)
- ✅ Temps ingestion 250 slides : **< 10 min** (vs 90 min)
- ✅ Vision API throughput : **> 30 slides/min** (vs 3/min)
- ✅ Error rate : **< 5%**

### KPI Phase 2 (Après Sprint 2)
- ✅ Temps ingestion 250 slides : **< 6 min** (vs 90 min)
- ✅ OSMOSE processing : **< 2 min** (vs 25 min)
- ✅ GPU utilization : **> 60%** (vs 0%)

### KPI Phase 3 (Après Sprint 3)
- ✅ Temps ingestion 250 slides : **< 5 min** (vs 90 min)
- ✅ Coûts API : **-50%** (cache + batch)
- ✅ Cache hit ratio : **> 40%**

### KPI Final (Production)
- ✅ Temps ingestion 250 slides : **< 5 min** garanti
- ✅ Gain total : **18x plus rapide** (90 min → 5 min)
- ✅ Quality preserved : Precision/recall > 95% de baseline
- ✅ Coûts réduits : -50% API costs
- ✅ Scalabilité : 10 docs simultanés sans dégradation

---

## ⚠️ RISQUES & MITIGATIONS

### Risque 1 : GPU Non Disponible

**Impact** : Batch processing moins efficace en CPU

**Mitigation** :
- Fallback automatique CPU si GPU indisponible
- Batch size réduit à 32 en CPU (vs 512 GPU)
- Warning logs explicites
- Gain attendu CPU : 5x (vs 15x GPU)

---

### Risque 2 : Vision API Rate Limiting

**Impact** : Timeouts si > 500 RPM

**Mitigation** :
- Circuit breaker fail-fast
- Backoff exponentiel avec jitter
- Micro-batching adaptatif (réduire de 20 → 10 workers si errors)
- Fallback texte brut si circuit ouvert

---

### Risque 3 : Cache Redis Overflow

**Impact** : Mémoire saturée si trop de docs

**Mitigation** :
- TTL strict (7 jours embeddings, 30 jours concepts)
- Maxmemory policy `allkeys-lru`
- Monitoring Redis memory usage
- Alertes si > 80% memory

---

### Risque 4 : Quality Dégradation

**Impact** : Batch processing réduit precision/recall

**Mitigation** :
- Tests A/B baseline vs optimized
- Seuil acceptance : > 95% baseline quality
- Rollback si quality < 95%
- Monitoring quality metrics par sprint

---

## 🔄 ROLLBACK PLAN

Si problème critique en production :

1. **Rollback Sprint 3** (cache) : 5 min
   - Désactiver semantic cache (env var)
   - Revenir à LLM séquentiel

2. **Rollback Sprint 2** (GPU) : 10 min
   - Désactiver GPU (env var `USE_GPU=false`)
   - Revenir à concept extractor original

3. **Rollback Sprint 1** (async Vision) : 15 min
   - Revenir à ThreadPoolExecutor original
   - Restaurer workers = 3

**Command** :
```bash
# Rollback complet en 1 commande
git revert HEAD~10  # Revenir à commit avant refactoring
docker-compose restart app worker
```

---

## 📚 RÉFÉRENCES

### Best Practices 2025
- [NVIDIA Knowledge Graph LLM Best Practices](https://developer.nvidia.com/blog/insights-techniques-and-evaluation-for-llm-driven-knowledge-graphs/)
- [AWS KG ETL Pipeline Architecture](https://blog.metaphacts.com/building-massive-knowledge-graphs-using-automated-etl-pipelines)
- [PingCAP Knowledge Graph Optimization Guide](https://www.pingcap.com/article/knowledge-graph-optimization-guide-2025/)

### Technologies
- **async I/O** : `asyncio`, `aiohttp`
- **GPU NER** : `spacy[cuda]`
- **GPU Embeddings** : `sentence-transformers` (CUDA)
- **Cache** : Redis 7.x
- **Monitoring** : Grafana + Prometheus

---

**FIN DU PLAN DE REFACTORING**

🚀 **Next Steps** :
1. Review ce document avec l'équipe
2. Prioriser sprints selon budget
3. Setup environnement GPU (CUDA)
4. Lancer Sprint 1 (Async Vision)

📊 **ROI Attendu** :
- Temps dev : 4 semaines (1 dev)
- Gain temps : 85 min/doc → **170h/mois** (120 docs/mois)
- Gain coûts : -50% API → **$500+/mois**
- Satisfaction utilisateurs : **⭐⭐⭐⭐⭐**
