# Évaluation Feedback OpenAI - Architecture North Star

**Date**: 30 septembre 2025
**Source**: Revue architecture par OpenAI
**Objectif**: Évaluer pertinence des recommandations et prioriser intégrations

---

## 📊 SYNTHÈSE ÉVALUATION

### Points Validés par OpenAI ✅

1. **Paradigme ontologie émergente** : Clair, argumenté, outillé
2. **Scoring multi-dimensionnel** : Evidence humaine = confiance
3. **Plan phasé North Star** : Gates et critères = très pro
4. **Extraction unifiée LLM** : Excellente optimisation coût/qualité

**Verdict**: Architecture solide dans ses fondations ✅

---

### Manques Structurants 🔴 (10 points critiques)

| # | Manque Identifié | Criticité | Priorité | Évaluation |
|---|-----------------|-----------|----------|------------|
| 1 | Stratégie "cold start / empty-KG" | 🔴 HAUTE | P0 | ✅ **VALIDE** - Bloquant multi-domaine |
| 2 | Multi-lingue / translit / locales | 🟡 MOYENNE | P1 | ✅ **VALIDE** - Essentiel international |
| 3 | Idempotence & déterminisme | 🔴 HAUTE | P0 | ✅ **VALIDE** - Production critique |
| 4 | Évolution des embeddings | 🟠 HAUTE | P1 | ✅ **VALIDE** - Maintenance long terme |
| 5 | Backfill Qdrant à grande échelle | 🔴 HAUTE | P0 | ✅ **VALIDE** - Performance critique |
| 6 | Gouvernance des "false-merge" | 🔴 HAUTE | P0 | ✅ **VALIDE** - Confiance utilisateur |
| 7 | Temporalité & versionning entités | 🟡 MOYENNE | P2 | ⚠️ **PARTIEL** - Nice-to-have Phase 6 |
| 8 | Tenancy & sécurité bout-en-bout | 🔴 HAUTE | P0 | ✅ **VALIDE** - Sécurité non-négociable |
| 9 | Évaluation offline & QA systématique | 🟠 HAUTE | P1 | ✅ **VALIDE** - Qualité mesurable |
| 10 | Stratégie d'échec extraction unifiée | 🔴 HAUTE | P0 | ✅ **VALIDE** - Résilience pipeline |

---

### Challenges Design & Ops 🟡 (4 points)

| # | Challenge | Criticité | Priorité | Évaluation |
|---|-----------|-----------|----------|------------|
| 1 | Extraction unifiée = single point of failure | 🟠 HAUTE | P1 | ✅ **VALIDE** - Découplage nécessaire |
| 2 | Seuils et règles de décision | 🟡 MOYENNE | P1 | ✅ **VALIDE** - Affiner heuristiques |
| 3 | Contexte graphe enrichi | 🟡 MOYENNE | P2 | ⚠️ **PARTIEL** - Optimisation Phase 6 |
| 4 | UI de gouvernance améliorée | 🟢 FAIBLE | P2 | ✅ **VALIDE** - UX importante |

---

### Risques + Parades 🟠 (5 points)

Tous **VALIDES** ✅ - À intégrer dans section Risques North Star

---

### Critères d'Acceptation 📏 (5 domaines)

Tous **VALIDES** ✅ - Critères mesurables et réalistes

---

### Quick Wins 🚀 (4 points)

Tous **VALIDES** ✅ - À implémenter dès Phase 1-2

---

## 🎯 PLAN D'INTÉGRATION PRIORISÉ

### Phase 0 (Immédiat - Avant Sprint 1)

#### 1. Stratégie Cold Start / Empty-KG 🔴 P0

**Problème**: KG vide au démarrage → queue infinie de "create new"

**Solution** :
```python
# src/knowbase/canonicalization/bootstrap.py

class KGBootstrapService:
    """Bootstrap automatique KG pour nouveau domaine"""

    async def auto_bootstrap_from_candidates(
        self,
        domain: str,
        group_id: str,
        min_occurrences: int = 10,
        min_confidence: float = 0.8
    ) -> BootstrapResult:
        """
        Crée entités "seed" depuis candidates fréquentes

        Règles:
        - Occurrences ≥ 10 chunks
        - Confidence ≥ 0.8
        - Status "proposed" → "approved" automatiquement

        Returns:
            Liste entités seed créées
        """

        # Récupérer candidates fréquentes
        candidates = await self.kg_service.get_entities(
            status="proposed",
            group_id=group_id,
            order_by="occurrences",
            limit=100
        )

        seed_entities = []

        for candidate in candidates:
            occurrences = await self.qdrant_service.count_chunks_with_entity(
                candidate.uuid
            )

            # Auto-approve si critères remplis
            if occurrences >= min_occurrences and candidate.confidence >= min_confidence:
                approved = await self.kg_service.promote_to_canonical(
                    candidate.uuid,
                    auto_approved=True,
                    reason=f"Auto-bootstrap: {occurrences} occurrences, conf={candidate.confidence}"
                )

                seed_entities.append(approved)

        return BootstrapResult(
            domain=domain,
            seed_count=len(seed_entities),
            entities=seed_entities
        )
```

**Intégration** :
- Ajouter section "Bootstrap Automatique" dans Phase 1 North Star
- Script `scripts/bootstrap_kg_domain.py` pour nouveau domaine
- Critère : ≥ 20 entités seed pour démarrer canonicalisation

---

#### 2. Idempotence & Déterminisme 🔴 P0

**Problème**: Merge/create non-rejouables, scores non reproductibles

**Solution** :

**A. Idempotence API**
```python
# src/knowbase/api/routers/governance.py

@router.post("/canonicalization/merge")
async def merge_candidate_to_canonical(
    request: MergeRequest,
    idempotency_key: Optional[str] = Header(None),  # 🆕
    user_context: Dict = Depends(get_user_context)
) -> MergeResponse:
    """
    Merge candidate → canonical (IDEMPOTENT)

    Headers:
        Idempotency-Key: uuid-client-generated

    Behavior:
        - Si merge déjà fait avec cette clé → retourne résultat existant
        - Sinon → exécute merge et stocke résultat
    """

    if idempotency_key:
        # Vérifier si déjà traité
        cached_result = await cache.get(f"merge:{idempotency_key}")
        if cached_result:
            return MergeResponse(**cached_result)

    # Exécuter merge
    result = await service.apply_merge(...)

    # Cacher résultat (TTL 24h)
    if idempotency_key:
        await cache.set(
            f"merge:{idempotency_key}",
            result.dict(),
            ttl=86400
        )

    return result
```

**B. Déterminisme Scoring**
```python
# src/knowbase/canonicalization/probabilistic_matcher.py

class ProbabilisticCanonicalizer:

    VERSION = "1.0.0"  # 🆕 Version algorithme
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # 🆕 Modèle figé

    async def suggest_canonical_matches(
        self,
        candidate: EntityCandidate,
        top_k: int = 5,
        group_id: str = None
    ) -> List[CanonicalSuggestion]:
        """Suggestions avec features persisted"""

        suggestions = []

        for canonical in canonical_entities:
            # Calcul features
            features = {
                "string_similarity": self._string_similarity(...),
                "semantic_similarity": self._semantic_similarity(...),
                "graph_context": self._graph_context_similarity(...)
            }

            final_score = (
                self.weights["string_similarity"] * features["string_similarity"] +
                self.weights["semantic_similarity"] * features["semantic_similarity"] +
                self.weights["graph_context"] * features["graph_context"]
            )

            suggestions.append(CanonicalSuggestion(
                canonical_entity_id=canonical.uuid,
                canonical_name=canonical.name,
                score=final_score,
                breakdown=features,
                # 🆕 Métadonnées déterminisme
                metadata={
                    "algorithm_version": self.VERSION,
                    "embedding_model": self.EMBEDDING_MODEL,
                    "weights": self.weights,
                    "computed_at": datetime.now(timezone.utc).isoformat(),
                    "features_hash": hashlib.sha256(
                        json.dumps(features, sort_keys=True).encode()
                    ).hexdigest()
                }
            ))

        # Persister features + score pour audit
        await self.db.log_canonicalization_features(
            candidate_id=candidate.uuid,
            suggestions=suggestions
        )

        return suggestions
```

**Intégration** :
- Ajouter section "Idempotence & Reproductibilité" dans Phase 4 North Star
- Critère : 100% opérations rejouables, scores reproductibles bit-à-bit

---

#### 3. Gouvernance False-Merge (Undo/Split) 🔴 P0

**Problème**: Merge erroné → pas de rollback

**Solution** :
```python
# src/knowbase/api/services/governance.py

class GovernanceService:

    async def undo_merge(
        self,
        merge_id: str,
        user_context: Dict
    ) -> UndoMergeResponse:
        """
        Annule un merge erroné (transactionnel)

        Actions:
        1. KG : Restaurer entité candidate (status proposed)
        2. Qdrant : Retirer canonical_id de related_node_ids.approved
        3. Audit : Logger undo avec raison

        Returns:
            Résultat undo avec nb chunks affectés
        """

        # 1️⃣ Récupérer historique merge
        merge_record = await self.db.get_merge_record(merge_id)

        if not merge_record:
            raise MergeNotFoundError(merge_id)

        # 2️⃣ Restaurer entité candidate dans KG
        await self.kg_service.restore_entity(
            entity_id=merge_record.candidate_id,
            status="proposed"
        )

        # 3️⃣ Retrouver chunks affectés (via audit log)
        affected_chunks = merge_record.affected_chunk_ids

        # 4️⃣ Rollback Qdrant
        for chunk_id in affected_chunks:
            chunk = await self.qdrant_service.get_chunk(chunk_id)

            # Retirer de approved, remettre dans candidates
            if merge_record.canonical_id in chunk.related_node_ids.get("approved", []):
                chunk.related_node_ids["approved"].remove(merge_record.canonical_id)

            if merge_record.candidate_id not in chunk.related_node_ids.get("candidates", []):
                chunk.related_node_ids.setdefault("candidates", []).append(merge_record.candidate_id)

            await self.qdrant_service.update_chunk_payload(
                chunk_id,
                {"related_node_ids": chunk.related_node_ids}
            )

        # 5️⃣ Audit undo
        await self.db.log_undo_merge(
            merge_id=merge_id,
            user_id=user_context["user_id"],
            reason=user_context.get("reason", "User-initiated undo"),
            chunks_reverted=len(affected_chunks)
        )

        return UndoMergeResponse(
            candidate_id=merge_record.candidate_id,
            canonical_id=merge_record.canonical_id,
            chunks_reverted=len(affected_chunks),
            message=f"Merge {merge_id} successfully undone"
        )
```

**Quarantaine avant backfill massif** :
```python
async def apply_merge(
    self,
    candidate_id: str,
    canonical_id: str,
    user_context: Dict
) -> MergeResponse:
    """Merge avec quarantaine 24h avant backfill Qdrant"""

    # 1️⃣ Merge dans KG immédiatement
    await self.kg_service.merge_entities(...)

    # 2️⃣ Planifier backfill Qdrant avec délai (quarantaine)
    await self.task_queue.schedule_delayed(
        task="backfill_qdrant_after_merge",
        params={
            "candidate_id": candidate_id,
            "canonical_id": canonical_id,
            "merge_id": merge_id
        },
        delay_seconds=86400  # 24h quarantaine
    )

    return MergeResponse(
        merged_entity_id=canonical_id,
        chunks_updated=0,  # Pas encore
        quarantine_until=datetime.now() + timedelta(days=1),
        message="Merge completed. Qdrant backfill scheduled in 24h (undo possible)"
    )
```

**Intégration** :
- Ajouter section "Undo/Split Transactionnel" dans Phase 4 North Star
- API `/canonicalization/undo-merge`
- Critère : 100% merges undoable avant backfill massif

---

#### 4. Backfill Qdrant à Grande Échelle 🔴 P0

**Problème**: Rétrofit 1000+ chunks peut timeout/échouer

**Solution** :
```python
# src/knowbase/tasks/backfill.py

class QdrantBackfillService:
    """Backfill Qdrant avec batching, retries, monitoring"""

    async def backfill_related_nodes_after_merge(
        self,
        candidate_id: str,
        canonical_id: str,
        batch_size: int = 100,
        max_retries: int = 3
    ) -> BackfillResult:
        """
        Mise à jour related_node_ids par batches

        Stratégie:
        - Fenêtrage par batch de 100 chunks
        - Retries exponentiels (1s, 2s, 4s)
        - Idempotency via chunk_id
        - Monitoring p95 latence
        """

        # 1️⃣ Récupérer tous chunks affectés (pagination)
        total_chunks = await self.qdrant_service.count_chunks_with_entity(
            candidate_id
        )

        logger.info(f"Backfill: {total_chunks} chunks to update")

        updated = 0
        failed = []

        # 2️⃣ Traitement par batches
        for offset in range(0, total_chunks, batch_size):
            batch_chunks = await self.qdrant_service.find_chunks_with_entity(
                candidate_id,
                limit=batch_size,
                offset=offset
            )

            # 3️⃣ Mise à jour batch avec retries
            for attempt in range(max_retries):
                try:
                    await self._update_batch(
                        batch_chunks,
                        candidate_id,
                        canonical_id
                    )

                    updated += len(batch_chunks)
                    break  # Success

                except Exception as e:
                    if attempt == max_retries - 1:
                        # Échec définitif
                        failed.extend([c.id for c in batch_chunks])
                        logger.error(f"Batch failed after {max_retries} retries: {e}")
                    else:
                        # Retry exponentiel
                        await asyncio.sleep(2 ** attempt)

            # 4️⃣ Monitoring progression
            progress = (offset + len(batch_chunks)) / total_chunks * 100
            await self.metrics.gauge("backfill_progress", progress)

        return BackfillResult(
            total_chunks=total_chunks,
            updated=updated,
            failed=failed,
            success_rate=updated / total_chunks if total_chunks > 0 else 1.0
        )

    async def _update_batch(
        self,
        chunks: List[Chunk],
        candidate_id: str,
        canonical_id: str
    ):
        """Mise à jour batch (idempotent)"""

        updates = []

        for chunk in chunks:
            # Retirer de candidates, ajouter à approved
            new_related_nodes = chunk.related_node_ids.copy()

            if candidate_id in new_related_nodes.get("candidates", []):
                new_related_nodes["candidates"].remove(candidate_id)

            if canonical_id not in new_related_nodes.get("approved", []):
                new_related_nodes.setdefault("approved", []).append(canonical_id)

            updates.append({
                "id": chunk.id,
                "payload": {"related_node_ids": new_related_nodes}
            })

        # Batch update Qdrant (transactionnel)
        await self.qdrant_service.batch_update_payloads(updates)
```

**Intégration** :
- Ajouter section "Backfill Scalable" dans Phase 4 North Star
- Critère : p95 latence <100ms/batch, success rate ≥99.9%, exactly-once

---

#### 5. Stratégie Échec Extraction Unifiée 🔴 P0

**Problème**: Appel LLM unifié échoue → perte chunks + entities

**Solution** :
```python
# src/knowbase/ingestion/pipelines/pptx_pipeline.py

async def process_slide_with_fallback(
    slide_index: int,
    slide_content: Dict,
    deck_context: Dict
) -> SlideProcessingResult:
    """
    Extraction avec fallback découplé

    Priorité:
    1. Tenter extraction unifiée (chunks + entities + relations)
    2. Si échec → fallback chunks seulement (critique)
    3. Planifier extraction entities en asynchrone (best effort)
    """

    try:
        # 🎯 Tentative extraction unifiée
        result = await ask_gpt_slide_analysis(
            slide_content,
            deck_context,
            extraction_mode="unified"
        )

        # Validation JSON
        chunks = result.get("chunks", [])
        entities = result.get("entities", [])
        relations = result.get("relations", [])

        # Vérifier intégrité
        if not chunks:
            raise ExtractionError("No chunks extracted")

        return SlideProcessingResult(
            chunks=chunks,
            entities=entities,
            relations=relations,
            extraction_status="unified_success"
        )

    except (TimeoutError, JSONDecodeError, ExtractionError) as e:
        logger.warning(
            f"Slide {slide_index}: unified extraction failed: {e}. "
            f"Falling back to chunks-only mode."
        )

        # 🆘 FALLBACK: Chunks seulement (critique)
        try:
            chunks_result = await ask_gpt_slide_analysis(
                slide_content,
                deck_context,
                extraction_mode="chunks_only"  # Prompt simplifié
            )

            chunks = chunks_result.get("chunks", [])

            # ⏰ Planifier extraction entities asynchrone
            await task_queue.enqueue(
                "extract_entities_async",
                {
                    "slide_index": slide_index,
                    "slide_content": slide_content,
                    "deck_context": deck_context,
                    "retry_count": 0
                }
            )

            return SlideProcessingResult(
                chunks=chunks,
                entities=[],
                relations=[],
                extraction_status="chunks_only_fallback",
                async_extraction_scheduled=True
            )

        except Exception as e2:
            logger.error(
                f"Slide {slide_index}: even chunks-only failed: {e2}. "
                f"Marking slide as failed."
            )

            return SlideProcessingResult(
                chunks=[],
                entities=[],
                relations=[],
                extraction_status="failed",
                error=str(e2)
            )
```

**Intégration** :
- Ajouter section "Fallback Découplé" dans Phase 3 North Star
- Critère : échec extraction <1%, fallback chunks-only fonctionne 100%

---

#### 6. Tenancy & Sécurité Bout-en-Bout 🔴 P0

**Problème**: RBAC mentionné mais non détaillé

**Solution** :

**A. Matrice RBAC**
```yaml
# config/rbac_matrix.yaml

roles:
  admin:
    permissions:
      - canonicalization:merge
      - canonicalization:create_new
      - canonicalization:reject
      - canonicalization:undo
      - entities:read_all_tenants
      - entities:delete

  expert:
    permissions:
      - canonicalization:merge  # Seulement son tenant
      - canonicalization:create_new
      - canonicalization:reject
      - entities:read_own_tenant

  user:
    permissions:
      - entities:read_own_tenant
      - search:execute

audit_events:
  - canonicalization:merge
  - canonicalization:undo
  - entities:delete
```

**B. Filtres obligatoires**
```python
# src/knowbase/api/dependencies.py

async def enforce_tenant_filter(
    user_context: Dict = Depends(get_user_context),
    requested_group_id: Optional[str] = Query(None)
) -> str:
    """
    Force group_id dans toutes les requêtes

    Rules:
    - User → seulement son tenant
    - Expert → seulement son tenant
    - Admin → tous tenants (mais doit spécifier)
    """

    user_role = user_context["role"]
    user_group_id = user_context["group_id"]

    if user_role in ["user", "expert"]:
        # Force leur tenant
        return user_group_id

    elif user_role == "admin":
        if not requested_group_id:
            raise HTTPException(
                status_code=400,
                detail="Admin must specify group_id explicitly"
            )
        return requested_group_id

    else:
        raise HTTPException(status_code=403, detail="Unknown role")


# Usage dans routes
@router.get("/canonicalization/queue")
async def get_canonicalization_queue(
    group_id: str = Depends(enforce_tenant_filter),  # 🔒 Obligatoire
    user_context: Dict = Depends(get_user_context)
):
    # group_id forcé, impossible de leak
    return await service.get_queue(group_id=group_id)
```

**C. Audit Trail**
```python
# src/knowbase/audit/logger.py

class AuditLogger:
    """Log toutes actions sensibles"""

    async def log_merge(
        self,
        user_id: str,
        group_id: str,
        candidate_id: str,
        canonical_id: str,
        chunks_affected: int
    ):
        await self.db.insert_audit_log({
            "event_type": "canonicalization:merge",
            "user_id": user_id,
            "group_id": group_id,
            "timestamp": datetime.now(timezone.utc),
            "payload": {
                "candidate_id": candidate_id,
                "canonical_id": canonical_id,
                "chunks_affected": chunks_affected
            },
            "ip_address": request.client.host
        })
```

**Intégration** :
- Ajouter section "RBAC & Audit" dans Phase 4 North Star
- Critère : tests isolement 100% OK, audit trail complet

---

### Phase 1 (Sprint 1-2)

#### 7. Multi-Lingue / Translit / Locales 🟡 P1

**Problème**: Normalisation limitée au latin

**Solution** :
```python
# src/knowbase/canonicalization/normalizer.py

from unidecode import unidecode
import unicodedata
import re

class LocaleAwareNormalizer:
    """Normalisation multi-lingue"""

    # Variantes locales connues
    LOCALE_VARIANTS = {
        "centre": "center",
        "colour": "color",
        "organisation": "organization",
        "aluminium": "aluminum",
    }

    # Symboles commerciaux
    COMMERCIAL_SYMBOLS = {
        "™": "",
        "®": "",
        "©": "",
        "℠": ""
    }

    def normalize(self, text: str) -> str:
        """
        Normalisation multi-étapes

        1. Lowercase
        2. Retirer symboles commerciaux
        3. Normaliser unicode (NFD)
        4. Translittération (unidecode)
        5. Variantes locales
        6. Espaces multiples
        """

        # 1. Lowercase
        text = text.lower()

        # 2. Symboles commerciaux
        for symbol, replacement in self.COMMERCIAL_SYMBOLS.items():
            text = text.replace(symbol, replacement)

        # 3. NFD (décompose accents)
        text = unicodedata.normalize("NFD", text)

        # 4. Translittération (CJK → latin)
        text = unidecode(text)

        # 5. Variantes locales
        words = text.split()
        normalized_words = [
            self.LOCALE_VARIANTS.get(word, word) for word in words
        ]
        text = " ".join(normalized_words)

        # 6. Espaces multiples
        text = re.sub(r"\s+", " ", text).strip()

        return text
```

**Intégration** :
- Ajouter section "Normalisation Multi-Lingue" dans Phase 4 North Star
- Critère : Support EN/FR/DE/ES/CJK, variantes locales couvertes

---

#### 8. Évolution des Embeddings 🟠 P1

**Problème**: Changement modèle embedding → dimension différente

**Solution** :
```python
# src/knowbase/canonicalization/embedding_migrator.py

class EmbeddingMigrator:
    """Migration vectorielle lors changement modèle"""

    async def migrate_embeddings(
        self,
        old_model: str,
        new_model: str
    ):
        """
        Double écriture temporaire + backfill asynchrone

        Étapes:
        1. Activer double-write (old + new embeddings)
        2. Backfill asynchrone entités existantes
        3. Basculer canonicalizer vers new_model
        4. Cleanup old embeddings
        """

        # 1️⃣ Activer double-write
        await self.config.enable_double_write(old_model, new_model)

        # 2️⃣ Backfill asynchrone
        entities = await self.kg_service.get_all_entities()

        for entity in entities:
            # Calculer nouveau embedding
            new_embedding = self.new_embedder.encode(
                f"{entity.name}. {entity.description}"
            )

            # Stocker à côté de l'ancien
            await self.kg_service.update_entity_embedding(
                entity.uuid,
                embedding_v2=new_embedding.tolist()
            )

        # 3️⃣ Basculer canonicalizer
        await self.canonicalizer.switch_embedding_model(new_model)

        # 4️⃣ Cleanup (après validation)
        await self.kg_service.drop_old_embeddings_column()
```

**Intégration** :
- Ajouter section "Migration Embeddings" dans Phase 6 North Star
- Critère : Double-write → backfill → switch sans downtime

---

#### 9. Évaluation Offline & QA Systématique 🟠 P1

**Problème**: Pas de benchmark qualité canonicalisation

**Solution** :
```python
# tests/benchmarks/canonicalization_benchmark.py

class CanonicalizationBenchmark:
    """Benchmark qualité suggestions"""

    async def evaluate_canonicalizer(
        self,
        test_set_path: str = "data/benchmark/canonicalization_500.jsonl"
    ) -> BenchmarkResults:
        """
        Évalue qualité sur set annoté

        Format test_set:
        {"candidate": "SAP Cloud ERP", "canonical": "SAP S/4HANA Cloud, Public Edition", "domain": "sap"}

        Métriques:
        - Top-1 Accuracy (suggestion #1 correcte)
        - Top-3 Accuracy (bonne réponse dans top-3)
        - ERR@k (Expected Reciprocal Rank)
        - NDCG@k (Normalized Discounted Cumulative Gain)
        """

        test_samples = self._load_test_set(test_set_path)

        top1_correct = 0
        top3_correct = 0
        reciprocal_ranks = []

        for sample in test_samples:
            # Calculer suggestions
            suggestions = await self.canonicalizer.suggest_canonical_matches(
                EntityCandidate(
                    raw_name=sample["candidate"],
                    entity_type="PRODUCT",
                    confidence=1.0
                ),
                top_k=5
            )

            # Trouver position bonne réponse
            correct_canonical = sample["canonical"]

            position = None
            for idx, sug in enumerate(suggestions):
                if sug.canonical_name == correct_canonical:
                    position = idx + 1
                    break

            # Métriques
            if position == 1:
                top1_correct += 1

            if position and position <= 3:
                top3_correct += 1

            if position:
                reciprocal_ranks.append(1.0 / position)
            else:
                reciprocal_ranks.append(0.0)

        return BenchmarkResults(
            total_samples=len(test_samples),
            top1_accuracy=top1_correct / len(test_samples),
            top3_accuracy=top3_correct / len(test_samples),
            err=sum(reciprocal_ranks) / len(reciprocal_ranks)
        )
```

**Intégration** :
- Ajouter section "Benchmark Qualité" dans Phase 4 North Star
- Critère : Top-1 ≥70%, Top-3 ≥90% sur 500 samples multi-domaine

---

### Phase 2 (Sprint 3-4)

#### 10. Seuils et Règles de Décision Affinées 🟡 P1

**Solution** :
```python
class EnhancedDecisionRules:
    """Règles de décision enrichies"""

    def recommend_action(
        self,
        candidate: Entity,
        suggestions: List[CanonicalSuggestion]
    ) -> Tuple[str, Optional[str]]:
        """
        Règles avec hystérésis + multi-signal

        Améliorations:
        - Hystérésis (0.75-0.85 au lieu de 0.8 fixe)
        - Exiger 2 signaux forts (semantic + graph)
        - Seuils dépendants du type d'entité
        """

        if not suggestions:
            return "CREATE_NEW", None

        best = suggestions[0]

        # Seuils par type d'entité
        thresholds = self._get_thresholds(candidate.entity_type)

        # Hystérésis : éviter oscillations
        if best.score >= thresholds["high"]:
            # Vérifier multi-signal (2 dimensions fortes)
            strong_signals = sum([
                1 for val in best.breakdown.values() if val >= 0.7
            ])

            if strong_signals >= 2:
                return "MERGE", best.canonical_entity_id
            else:
                return "REVIEW", None  # Score élevé mais 1 seul signal

        elif best.score >= thresholds["medium"]:
            return "REVIEW", None

        else:
            return "CREATE_NEW", None

    def _get_thresholds(self, entity_type: str) -> Dict[str, float]:
        """Seuils adaptés par type"""

        THRESHOLDS = {
            "PRODUCT": {"high": 0.85, "medium": 0.60},  # Strict
            "TECHNOLOGY": {"high": 0.80, "medium": 0.55},
            "PERSONA": {"high": 0.75, "medium": 0.50},  # Permissif
            "CONCEPT": {"high": 0.70, "medium": 0.45}
        }

        return THRESHOLDS.get(entity_type, {"high": 0.80, "medium": 0.55})
```

**Intégration** :
- Améliorer section Phase 4 avec règles affinées
- Critère : Réduction faux positifs −30% vs baseline

---

## 📊 RÉCAPITULATIF PRIORISATION

### P0 - Critique (Phase 0-1) 🔴

| # | Recommandation | Effort | Impact |
|---|---------------|--------|--------|
| 1 | Cold Start Bootstrap | 2 jours | 🔴 HAUTE |
| 3 | Idempotence & Déterminisme | 3 jours | 🔴 HAUTE |
| 5 | Backfill Scalable | 3 jours | 🔴 HAUTE |
| 6 | Undo/Split False-Merge | 2 jours | 🔴 HAUTE |
| 8 | Tenancy & RBAC | 3 jours | 🔴 HAUTE |
| 10 | Fallback Extraction | 2 jours | 🔴 HAUTE |

**Total P0**: ~15 jours effort

---

### P1 - Important (Phase 1-2) 🟠

| # | Recommandation | Effort | Impact |
|---|---------------|--------|--------|
| 2 | Multi-Lingue | 2 jours | 🟡 MOYENNE |
| 4 | Migration Embeddings | 3 jours | 🟠 HAUTE |
| 9 | Benchmark Qualité | 2 jours | 🟠 HAUTE |
| 11 | Règles Décision Affinées | 1 jour | 🟡 MOYENNE |

**Total P1**: ~8 jours effort

---

### P2 - Nice-to-Have (Phase 6) 🟢

| # | Recommandation | Effort | Impact |
|---|---------------|--------|--------|
| 7 | Temporalité Entités | 3 jours | 🟡 MOYENNE |
| 12 | Contexte Graphe Enrichi | 2 jours | 🟡 MOYENNE |
| 13 | UI Bulk Actions | 1 jour | 🟢 FAIBLE |

**Total P2**: ~6 jours effort

---

## ✅ RECOMMANDATIONS FINALES

### 1. Intégrer P0 (Critique) dans Phase 1-2

**Action immédiate** :
- Créer `doc/PRODUCTION_READINESS_CHECKLIST.md` avec 6 points P0
- Ajouter sections dédiées dans North Star
- Mettre à jour critères d'achèvement Phase 1-4

---

### 2. Documenter P1 (Important) pour Phase 2-3

**Action court terme** :
- Ajouter sections "Multi-Lingue" et "Benchmark" dans Phase 4
- Planifier migration embeddings pour Phase 6

---

### 3. Tracker P2 (Nice-to-Have) pour Phase 6

**Action long terme** :
- Backlog items pour optimisations avancées

---

## 🎯 VERDICT GLOBAL

**Feedback OpenAI = ✅ EXCELLENT et ACTIONNABLE**

**Points forts** :
- Identifie **vrais manques structurants** (cold start, idempotence, undo)
- Propose **solutions concrètes implémentables**
- Priorise **production-readiness** (sécurité, résilience, qualité)

**Recommandation** :
✅ **Intégrer 100% des points P0 avant Sprint 1**
✅ **Planifier P1 dans Sprint 2-3**
✅ **Tracker P2 pour Phase 6**

**Impact estimé** :
- Robustesse production : +50%
- Confiance utilisateurs : +40%
- Time-to-production : +2 semaines (mais qualité ++)

---

**Document de référence** pour évaluation feedback OpenAI et plan d'intégration.
