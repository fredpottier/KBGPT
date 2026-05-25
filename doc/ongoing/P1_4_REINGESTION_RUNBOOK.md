# Runbook P1.4 — Ré-ingestion Phase B (qualifiers + procedures)

> Statut : PRÊT — en attente EC2 Burst (V5_VLLM_URL)
> Date : 2026-05-25
> Branche : `feat/phase-b-augmentee`
> Prérequis livrés : P1.1 (schéma), P1.2 (prompt qualifiers), P1.3 (pont
> Procedure↔Claims), P1.5-tool (procedure_chain). Tous committés + testés.

## 0. Pré-flight (bloquant)

| Check | Commande | Attendu |
|---|---|---|
| EC2 Burst up | `docker exec knowbase-app sh -c 'echo $V5_VLLM_URL'` | URL non vide |
| vLLM santé | `curl -s $V5_VLLM_URL/health` | 200 |
| **Gate STOP Qwen** | `python app/scripts/p1_2_validate_qualifiers.py --provider vllm` | ≥20% claims qualifiés (idéal ≥30%) |

⚠️ **Si la gate STOP Qwen échoue (<20%)** : NE PAS ré-ingérer. Revoir le prompt
qualifiers (`claim_extractor.py`) avant de brûler l'EC2. DeepSeek-V3.1 validé à
70%/100% le 25/05 — si Qwen est très en-dessous, c'est un problème de capacité
modèle, arbitrer avec Fred (Qwen2.5-14B est le seul modèle dispo pour ré-ingestion
budget-wise).

## 1. Snapshot Neo4j (rollback 5 min)

```bash
# Snapshot avant ré-ingestion (rollback si régression)
docker exec knowbase-neo4j neo4j-admin database dump neo4j \
  --to-path=/backups/pre_phaseB_$(date +%Y%m%d)
```

## 2. Purge (PRÉSERVER extraction_cache !)

⚠️ **NE JAMAIS supprimer `data/extraction_cache/`** (cf CLAUDE.md). Les
`.knowcache.json` permettent de rejouer l'extraction Pass0 sans re-télécharger ni
re-OCR — indispensable pour ré-ingérer les 38 docs sans coût LLM Pass0.

Purge Neo4j + Qdrant + recréation schéma (inclut désormais `claim_procedure`,
`claim_procedure_role`, `:Procedure`/`:ProcedureStep` via purge_service) :

```bash
# Via l'endpoint purge (purge_schema=true recrée le schéma complet Phase B)
# OU scripts/reset_proto_kg.py selon le périmètre.
# Préserver docs_in/docs_done si on rejoue depuis extraction_cache.
```

## 3. Toggles env pour la ré-ingestion

Activer l'extraction de procédures (off par défaut) :

```bash
# Dans l'environnement du worker pour la ré-ingestion :
V6_PROCEDURE_EXTRACTION=1   # active Phase 6.7 (extract→link procedures)
# Le LLM d'extraction = EC2 vLLM Qwen2.5-14B (burst). Les qualifiers sont
# extraits par le prompt principal (toujours actif depuis P1.2).
```

Modèle d'extraction procédures : `procedure_extractor.py` lit `V6_EXTRACT_MODEL`
(défaut DeepSeek-V3.1). **Pour la ré-ingestion budget EC2, forcer le modèle burst**
ou laisser le router burst rediriger. À VÉRIFIER : le ProcedureExtractor utilise
`requests` direct DeepInfra/Together, PAS le llm_router burst. → Option :
positionner `V6_EXTRACT_MODEL` + un endpoint vLLM, OU accepter que les procédures
passent par DeepInfra (volume faible : ~1 appel par section procédurale, bien
inférieur à l'extraction de claims). **Décision à acter avec Fred avant P1.4.**

## 4. Ré-ingestion 5-10 docs test (gate P1.3 partielle)

Ré-ingérer d'abord 5-10 docs (dont ≥2 procéduraux : guides, operations) :

```bash
# Rejouer depuis extraction_cache → docs_in → pipeline ClaimFirst
```

Vérifier les compteurs (gate P1.3) :

```cypher
MATCH (p:Procedure {tenant_id:'default'}) RETURN count(p) AS n_proc;
MATCH (:Claim)-[r:STEP_OF]->(:Procedure) RETURN count(r) AS n_step_of;
MATCH (:Claim)-[r:PREREQUISITE_OF]->(:Claim) RETURN count(r) AS n_prereq;
MATCH (c:Claim) WHERE c.qualifiers_json IS NOT NULL RETURN count(c) AS n_qualified;
MATCH (c:Claim {tenant_id:'default'}) RETURN count(c) AS n_total;
```

Gate P1.3 (corpus complet) : ≥5 Procedure, ≥20 STEP_OF, ≥5 PREREQUISITE_OF.
Gate P1.2 qualifiers : ≥30% claims avec qualifiers_json non-null.

Smoke 25/05 (3 sections, DeepSeek) : 3 proc / 11 STEP_OF / 8 PREREQUISITE_OF →
gate atteignable. Sur 38 docs avec docs procéduraux, largement dépassé attendu.

## 5. Ré-ingestion complète 38 docs (si gate test OK)

Rejouer l'intégralité depuis extraction_cache. Re-vérifier les compteurs §4.

## 6. P1.5 — Bench 50q judge corrigé + procedure_chain

```bash
# Activer le tool procedure_chain au runtime
V6_PROCEDURE_CHAIN=1

# Bench 50q SAP + 30q ConflictPending, judge corrigé (anti-overfit abstention)
docker exec knowbase-app sh -c 'cd /app && python -u scripts/bench_a38_runtime_v6.py'
```

Gate P1.5 (ADR) : C1 multi_hop ≥ 0.25 (vs 0.10) ET C1 global ≥ 0.45 (vs 0.39).

Comparer par type (tableau pivot) vs baseline judge-corrigé 25/05 :
factual 0.433, comparison 0.400, multi_hop 0.100, lifecycle 0.167,
contextual 0.600, false_premise 0.500, unanswerable 1.000, **global 0.390**.

Effet attendu : qualifiers → lifecycle + comparison ; procedure_chain →
multi_hop (questions "comment faire / étape suivante / prérequis").

## 7. Rollback si régression

```bash
docker exec knowbase-neo4j neo4j-admin database load neo4j \
  --from-path=/backups/pre_phaseB_<date> --overwrite-destination
```

Toggles OFF (`V6_PROCEDURE_EXTRACTION=0`, `V6_PROCEDURE_CHAIN=0`) → retour
comportement pré-Phase B (claims sans qualifiers/procedures restent valides,
rétrocompat 100%).

---

## Point ouvert à acter avec Fred (avant P1.4)

**Modèle d'extraction des procédures sur EC2** : `ProcedureExtractor` appelle
DeepInfra/Together en direct (pas le router burst). Trois options :
1. Laisser les procédures passer par DeepInfra (volume faible, ~1 appel/section
   procédurale — coût marginal vs extraction claims qui, elle, va sur EC2).
2. Pointer `ProcedureExtractor` vers le endpoint vLLM EC2 (nécessite un petit
   patch pour router vers V5_VLLM_URL).
3. Désactiver `V6_PROCEDURE_EXTRACTION` à la ré-ingestion et extraire les
   procédures en passe séparée post-ingestion (DeepInfra), pour ne pas coupler
   le coût procédures au budget EC2.

Recommandation : **Option 1** (simplicité, coût procédures marginal). À confirmer.
