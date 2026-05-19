# Phase 4 — Sprint résilience ingestion (plan détaillé)

*Date : 30 avril 2026*
*Statut : Plan d'attaque pour le sprint résilience (4-6 sem en sessions dédiées)*

## Vue d'ensemble

Le pipeline d'ingestion actuel n'est pas résilient :
- Si le worker crash mid-ingestion → tout l'état du job est perdu (Redis in-memory)
- Si on relance, on ré-extrait tout depuis zéro (pas de checkpoint)
- Si on importe un même fichier 2 fois → duplicates dans le KG (pas idempotent)

Pour un test client (Armand) ou une mise en production, c'est un bloqueur. Mais pour le développement solo en chambre, c'est tolérable.

---

## P4.1 (L1) — JobManager + state per-doc Redis (#20)

### Objectif
Persister l'état de chaque doc en cours d'ingestion dans Redis avec TTL 24h, pour permettre la reprise au restart.

### Architecture
```python
class JobManager:
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def create_job(self, doc_id: str, file_path: str) -> JobState:
        """Crée un nouveau job. Si doc_id existe déjà avec state=processing → erreur."""
    
    def update_state(self, doc_id: str, state: str, checkpoint: dict | None = None):
        """SETEX 86400 sur osmose:job:<doc_id> avec JSON state."""
    
    def get_state(self, doc_id: str) -> JobState | None:
        """Renvoie le state actuel ou None."""
    
    def list_active_jobs(self) -> list[JobState]:
        """Tous les jobs avec state ∈ {pending, processing, paused}."""
    
    def cleanup_stale(self, ttl_hours: int = 48):
        """Supprime les jobs avec state=failed older than ttl."""

class JobState(BaseModel):
    doc_id: str
    file_path: str
    state: Literal["pending", "processing", "post_import", "done", "failed", "paused"]
    started_at: datetime
    last_checkpoint: dict  # ex: {phase: "extract", progress: 0.6, last_block: 12}
    error: str | None
    retries: int
```

### Fichiers à créer
- `src/knowbase/ingestion/resilience/job_manager.py`
- `src/knowbase/ingestion/resilience/job_state.py` (pydantic)

### Effort : 2-3 jours

---

## P4.2 (L2.A) — Refactor claim_persister granulaire (#22)

### Objectif
Décomposer claim_persister en méthodes atomiques idempotentes (MERGE Cypher), pour permettre la reprise mid-process.

### Pattern actuel (à refactorer)
```python
def persist_claims_for_block(block, claims):
    # Atomique : crée Claim + Chunk + Relations en bloc
    # Si crash → tout perdu, redo from scratch
```

### Pattern cible
```python
class ClaimPersister:
    def persist_claim(self, claim: Claim) -> str:  # MERGE atomique, idempotent
    def persist_chunk(self, chunk: TypeAwareChunk) -> str:  # MERGE
    def persist_about(self, claim_id, entity_id):  # MERGE
    def link_claim_to_chunk(self, claim_id, chunk_id):  # MERGE relation
```

### Fichiers
- Refactor `src/knowbase/claimfirst/persistence/claim_persister.py`

### Effort : 2-3 jours

---

## P4.3 (L2.B) — Callback on_block_complete (#23)

### Objectif
ClaimExtractor déclenche un callback à chaque bloc complété, qui met à jour Redis state + persiste partiellement.

### Pattern
```python
class ClaimExtractor:
    def __init__(self, on_block_complete: Callable[[BlockResult], None] | None = None):
        self.on_block_complete = on_block_complete
    
    def extract(self, doc):
        for i, block in enumerate(doc.blocks):
            result = self._process_block(block)
            if self.on_block_complete:
                self.on_block_complete(BlockResult(index=i, claims=result.claims, total_blocks=len(doc.blocks)))

# Dans orchestrator :
def on_block(result: BlockResult):
    job_manager.update_state(doc_id, "processing", checkpoint={
        "phase": "extract",
        "block": result.index,
        "total": result.total_blocks,
    })
    persister.persist_claims_atomic(result.claims)
```

### Fichiers
- Modifier `src/knowbase/claimfirst/extractors/claim_extractor.py`
- Modifier `src/knowbase/claimfirst/orchestrator.py`

### Effort : 2 jours

---

## P4.4 (L2.C) — Logique reprise + 3 checkpoints orchestrator (#24)

### Objectif
Au démarrage du worker, scanner les jobs en `state=processing` et reprendre à partir du dernier checkpoint.

### 3 checkpoints
1. **Post-extract** : extraction terminée, claims pas encore persistés
2. **Post-claim-persist** : claims dans Neo4j, post-import (cross-doc) pas encore lancé
3. **Post-cross-doc** : analyse cross-doc faite, état final

### Logique
```python
def resume_or_start(doc_id: str, job: JobState):
    cp = job.last_checkpoint
    if cp.get("phase") == "extract":
        # Reprendre extract à partir du bloc cp["block"]
        ...
    elif cp.get("phase") == "post_extract":
        # Skip extract, faire claim_persist
        ...
    # etc.
```

### Effort : 3-4 jours

---

## P4.5 (L3) — Cross-doc finalize en job RQ séparé (#21)

### Objectif
Découpler le post-import (cross-doc analysis : facets, clusters, relations) en job RQ séparé. Permet de relancer le post-import sans re-extraire les claims.

### Architecture
```
Job principal "ingest_doc" (orchestrator)
  └─ extract → persist claims
  └─ enqueue "post_import_doc" (RQ separate queue)

Job "post_import_doc"
  └─ canonical entities, clustering, facets, BELONGS_TO_FACET, ABOUT_SUBJECT, LOGICAL_RELATION C12
```

### Bénéfices
- Relance post-import sans re-extraire
- Permet le post-import batch (ex: tous les docs nouveaux ensemble)

### Effort : 2-3 jours

---

## P4.6 (L4) — Pipeline V2 résilience (#26)

### Objectif
Intégrer L1+L2.A+L2.B+L2.C+L3 dans un orchestrateur cohérent.

### Effort : 2-3 jours (intégration + tests bout-en-bout)

---

## P4.7 (L5) — Tests résilience + idempotence (#25)

### Objectif
Tests automatisés validant la résilience.

### Tests à écrire
1. **Kill mid-extract** : worker tué pendant extract → restart → reprise au checkpoint
2. **Kill mid-persist** : worker tué pendant persist → restart → idempotent (pas de duplicate Claim)
3. **Double import** : import du même fichier 2× → 0 duplicate
4. **3 docs simultanés** : pipeline parallèle sans interférence

### Effort : 2-3 jours

---

## Total P4 : 4-6 semaines

Le sprint résilience est gros. Il devrait être attaqué dans une série de sessions dédiées, pas en parallèle d'autres chantiers (risque de bugs subtils).

### Ordre suggéré
P4.1 (L1) → P4.2 (L2.A) → P4.3 (L2.B) → P4.4 (L2.C) → P4.5 (L3) → P4.6 (L4) → P4.7 (L5)

### Acceptation finale du sprint
- Kill worker mid-import → reprise auto au restart, claims complets
- Re-import du même fichier → idempotent (count Claim inchangé)
- 3 docs simultanés → pas d'interférence cross-doc

### Décision actuelle
Sprint résilience **déféré jusqu'à scénario de validation production**. Pour le développement solo en chambre, le risque de crash worker est acceptable (relance manuelle suffisante).
