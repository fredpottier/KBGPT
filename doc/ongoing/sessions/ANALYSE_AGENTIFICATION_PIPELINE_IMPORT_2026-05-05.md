# Analyse — Agentification du pipeline d'import (cache, ClaimFirst, post-import)

_Date: 2026-05-05_

## TL;DR

Oui, c'est faisable et pertinent : le pipeline actuel est majoritairement **séquentiel par document** dans `claimfirst_process_job`, avec des sections lourdes (LLM, persistance, embeddings, bridge) qui peuvent être découpées en tâches agentiques idempotentes. Le gain attendu est fort sur le wall-clock global (surtout batch multi-docs), à condition d'ajouter une orchestration explicite des dépendances et des garde-fous de cohérence.

## 1) État actuel observé (code)

## 1.1 Génération cache / import V2

- `ingest_document_v2_job` exécute une chaîne linéaire : extraction V2, (optionnel) OSMOSE V2 legacy, dédup, move fichier, puis enqueue ClaimFirst. Le ClaimFirst est donc déjà découplé, mais **pas les étapes internes**. (`src/knowbase/ingestion/queue/jobs_v2.py`)
- ClaimFirst est enqueued dans la queue `reprocess` via `enqueue_claimfirst_process(...)`. (`src/knowbase/ingestion/queue/dispatcher.py`)

## 1.2 Claim-first

- `claimfirst_process_job` traite la liste `doc_ids` **dans une boucle for**, document après document. (`src/knowbase/claimfirst/worker_job.py`)
- Un seul `ClaimFirstOrchestrator` est partagé sur le run, ce qui favorise le cache local (ex: registry) mais force un comportement mono-flux pour la progression fonctionnelle. (`src/knowbase/claimfirst/worker_job.py`)
- `process_and_persist` enchaîne extraction, persist Neo4j, classification tensions, persist Qdrant, bridge claim↔chunk, en mode majoritairement séquentiel intra-document. (`src/knowbase/claimfirst/orchestrator.py`)

## 1.3 Post-import

- Le cockpit décrit un pipeline `post-import` dynamique par étapes (canonicalize, facets, clustering, chains, contradictions, embeddings, bridge, etc.), ce qui suggère des blocs déjà conceptualisés comme tâches. (`cockpit/pipeline_defs.yaml`)
- Le worker principal reste basé sur `SimpleWorker` avec écoute de 3 queues (`ingestion`, `reprocess`, `benchmark`) : parallélisme horizontal possible en multipliant les workers/containers, mais sans DAG explicite inter-étapes. (`src/knowbase/ingestion/queue/worker.py`)

## 2) Où sont les goulots majeurs

1. **Boucle séquentielle multi-docs ClaimFirst** : un doc très gros bloque l'avancement du lot.
2. **Étapes longues intra-doc** (LLM extraction/quality gates, Qdrant upsert volumineux, bridge) non pipelinées.
3. **Post-import dynamiques** vraisemblablement déclenchées en série alors qu'une partie des étapes est parallélisable par nature.
4. **Concurrence implicite limitée** à l'échelle queue/worker, sans granularité “tâche métier” ni backpressure fine par type d'action.

## 3) Proposition d'agentification (DAG de tâches)

## 3.1 Granularité recommandée

### Niveau A — `doc-level` (priorité immédiate)
Découper un import en tâches indépendantes par document :

- `cache.load_or_build(doc)`
- `claimfirst.extract(doc)`
- `claimfirst.persist_graph(doc)`
- `claimfirst.persist_qdrant(doc)`
- `claimfirst.bridge_claim_chunks(doc)`
- `postimport.doc_local(doc)` (ex: validations/doc health)

=> Permet de traiter N documents en parallèle avec scheduling + retry par document.

### Niveau B — `phase-level` cross-doc
Pour les phases corpus:

- `postimport.canonicalize_entities(batch)`
- `postimport.cluster_cross_doc(batch)`
- `postimport.detect_contradictions(batch)`
- `postimport.claim_embeddings(batch_partition_i)`

=> Ajout de partitions (par hash entity/claim) pour paralléliser sans collision.

## 3.2 Dépendances minimales (ordre)

- `extract(doc)` -> `persist_graph(doc)` -> `[persist_qdrant(doc), bridge(doc)]`
- `postimport.cluster_cross_doc` dépend de `persist_graph` terminé sur le batch cible.
- `detect_contradictions` dépend de clusters/relations de base.
- `claim_embeddings` peut souvent tourner en parallèle avec une partie des tâches post-import si elle n'écrit pas les mêmes champs.

## 3.3 Idempotence (obligatoire)

L'agentification est viable si chaque tâche est rejouable sans effets de bord:

- clés d'idempotence = `(tenant_id, doc_id, phase, version)`
- write patterns MERGE/UPSERT (déjà partiellement vrai côté Neo4j/Qdrant)
- checkpoints persistants par tâche (pas seulement par job global)
- statut terminal clair: `done|failed_retryable|failed_fatal|skipped`

## 4) Plan d'implémentation pragmatique

## Sprint 1 (faible risque, gain rapide)

1. **Un job ClaimFirst par document** au lieu d'un job multi-doc séquentiel.
2. Ajouter un orchestrateur batch léger qui ne fait que fan-out + suivi d'état.
3. Limites de concurrence distinctes par type:
   - LLM-heavy
   - Neo4j-write
   - Qdrant-write
4. Cockpit: afficher progression par doc + agrégat batch.

## Sprint 2 (agentification intra-doc)

1. Découper `process_and_persist` en sous-tâches durables.
2. Introduire un mini-DAG executor (state machine Redis).
3. Retry ciblé par sous-tâche (ex: Qdrant down n'oblige pas à relancer extraction).

## Sprint 3 (post-import distribué)

1. Transformer les étapes dynamiques post-import en tâches explicitement adressables.
2. Partitionner clustering/embeddings et merger les résultats.
3. Garde-fous de verrouillage logique (advisory lock tenant + phase).

## 5) Gains attendus / risques

## Gains

- Réduction du wall-clock sur lots volumineux (parallélisme doc-level).
- Meilleure résilience (reprise fine par étape).
- Meilleure observabilité opérationnelle (DAG + états tâche).

## Risques

- Sur-concurrence LLM (rate limits, coûts).
- Contention Neo4j/Qdrant si write burst non contrôlé.
- Complexité de debug si DAG sans contrat d'idempotence strict.

## 6) Recommandations concrètes

1. **Démarrer par doc-level fan-out** (ROI maximal / complexité minimale).
2. **Conserver le cache Pass0 comme pivot immutable** entre tâches.
3. **Séparer les pools de workers** par nature de charge (LLM vs DB).
4. **Mesurer avant/après**: p50/p95 par phase, throughput docs/h, retry rate.
5. **Ne pas paralléliser agressivement les phases cross-doc** avant d'avoir des partitions stables.

## 7) Conclusion

Le pipeline est déjà proche d'un modèle agentique (queues, états Redis, checkpoints partiels), mais il manque la granularité de tâches et un DAG explicite. La transformation est réaliste sans refonte complète : commencer par “1 doc = 1 job ClaimFirst” puis ajouter un découpage intra-doc pour les phases coûteuses.
