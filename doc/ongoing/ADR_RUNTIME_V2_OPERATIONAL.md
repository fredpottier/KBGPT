# ADR — Runtime V2 operational (SLA, monitoring, disaster recovery)

*Date : 30 avril 2026*
*Statut : Proposé pour test client*

## Contexte

Le Runtime V2 anchor-driven (Vision recentrée 30/04/2026) est validé fonctionnellement à 94% sur 18 questions cross-domain. Pour un test client, il faut définir les engagements opérationnels et la stratégie de récupération en cas d'incident.

## Décision

### SLA target (internal, non-contractuel)

| Métrique | Target | Mesure |
|---|---|---|
| **Latency P50** | < 8s par question | Histogram sur 100 questions |
| **Latency P95** | < 20s | idem |
| **Disponibilité endpoint** | 99% (en heures ouvrées) | Monitoring `/api/runtime_v2/health` |
| **Précision Test 1** | ≥ 90% (Vision §7) | Bench mensuel |
| **Précision Test 2** | 100% | idem |
| **Précision Test 3** | timeline cohérente | idem |

### Monitoring obligatoire

3 dashboards Grafana à mettre en place :

#### Dashboard 1 — Latency
- p50, p95 latency par étape pipeline (anchor extract, anchor filter, current resolver, retrieval, conflict detector, synthesis)
- Identifier le bottleneck dynamiquement

#### Dashboard 2 — Quality
- Distribution des decisions (answered_authoritative / scoped / evolution / escalate / not_found)
- Trust score moyen par jour
- Taux d'escalation user (proxy de qualité Subject Resolver / Anchor Filter)

#### Dashboard 3 — Dependencies
- Status vLLM EC2 (up/down via health probe 1×/min)
- Status Qdrant
- Status Neo4j
- Alerte si > 5 min down

### Disaster recovery

#### Scénarios

| Scénario | Détection | Recovery |
|---|---|---|
| **vLLM EC2 spot eviction** | curl health check fail | Auto-relance via `/api/burst/start` (déjà existant) |
| **Neo4j corruption** | Cypher errors massives | Restore from latest dump (`docker-compose.infra.yml` volume) |
| **Qdrant collection perdue** | Search returns 0 | Re-build depuis Neo4j claims (script `rebuild_qdrant_from_neo4j.py` à créer) |
| **Caches `data/extraction_cache/` perdus** | Files absents | **❌ pas de recovery automatique** — re-ingestion manuelle des PDFs |

#### Backups réguliers

- **Neo4j dump** : quotidien automatisé, retention 7 jours
- **Qdrant snapshot** : quotidien via Qdrant API
- **Caches `data/extraction_cache/`** : protection critique (cf. CLAUDE.md), backup hebdomadaire externe
- **Domain Packs manifests** : git versioned

### Mode dégradé

Si vLLM down → pipeline V2 entre en **mode dégradé** :
- Anchor Extractor LLM → fallback `current_default`
- Synthesizer LLM → fallback "extrait brut depuis [doc_id]"
- Current Resolver, Anchor Filter, Conflict Detector continuent (déterministes)
- L'UI affiche un badge "Mode dégradé — synthèse LLM indisponible"

User peut continuer à interroger le KG avec qualité réduite.

### Logs structurés

Chaque réponse pipeline génère un log JSON :
```json
{
  "ts": "2026-04-30T13:25:01Z",
  "request_id": "...",
  "question": "...",
  "decision": "answered_authoritative",
  "anchor_type": "current_default",
  "n_authoritative_docs": 1,
  "n_claims": 5,
  "n_conflicts": 0,
  "trust_score": 1.0,
  "latency_ms": 6432,
  "vllm_calls": 2,
  "qdrant_calls": 2,
  "neo4j_calls": 4
}
```

Centralisé dans Loki, requêtable via Grafana.

## Conséquences

✅ Engagements clairs pour test client
✅ Detection rapide des incidents
✅ Mode dégradé maintient le service en cas de vLLM down (cas vu dans la session du 30/04)
⚠️ Investissement infra : 1 sem pour les 3 dashboards Grafana
⚠️ Maintenance : checks de cohérence backups réguliers

## Alternatives rejetées

- **Pas de SLA** : incompatible avec test client réel
- **HA full-stack (vLLM redondant)** : coût prohibitif (24/7 GPU), spot eviction tolérable en mode dégradé
- **Logs non-structurés** : impossible à requêter en production

## Migration

1. Créer dashboards Grafana (provisioning JSON dans `monitoring/grafana/dashboards/`)
2. Ajouter logging structuré dans `runtime_v2/pipeline.py` (logger.info avec extra dict)
3. Configurer scrape Promtail pour les logs structurés
4. Documenter procédure backup Neo4j dans `doc/operational/BACKUP_RESTORE.md`
5. Tester le mode dégradé manuellement (kill vLLM → vérifier UI badge)
