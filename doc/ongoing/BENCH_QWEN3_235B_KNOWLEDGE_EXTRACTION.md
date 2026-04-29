# Bench Qwen3-235B-A22B-Instruct-2507 vs Qwen2.5-72B-Instruct sur knowledge_extraction

> **Statut** : ✅ EXÉCUTÉ le 2026-04-27 09:43 — **Décision : KEEP Qwen2.5-72B**
> Résultats détaillés : `data/bench/bench_qwen3_235b_20260427_094306.json`

## Contexte

`knowledge_extraction` est l'usage LLM **le plus volumineux** du pipeline ClaimFirst : extraction de claims atomiques depuis chaque passage. La qualité de cet appel détermine la qualité du KG entier.

Lors de la migration Option B (27/04), 7/8 usages ont migré vers Qwen3-235B (économie ~50%) **sauf** `knowledge_extraction` qui reste sur Qwen2.5-72B en attente de ce bench.

| Modèle | $/M tokens (in/out) | Context | Mode |
|--------|---------------------|---------|------|
| Qwen2.5-72B-Instruct (baseline) | 0.36 / 0.40 | 32k | dense |
| Qwen3-235B-A22B-Instruct-2507 (challenger) | 0.071 / 0.10 | 256k | MoE 235B/22B |

## Méthodologie

- **N=15 passages** échantillonnés depuis Neo4j (passages avec 2-10 claims existants, len 200-2000 chars)
- Provenance : 4 docs déjà ingérés (cs25_amdt_23, cs25_amdt_24, dualuse_del_2023_996, dualuse_del_2024_2025)
- Prompt minimal reproduisant `CLAIM_EXTRACTION_PROMPT_TEMPLATE` (sans domain_context spécifique)
- Calls directs DeepInfra avec `temperature=0.1`, `max_tokens=2000`, `response_format=json_object`
- Juge Claude Sonnet 4.5 prévu mais **bloqué par crédits Anthropic épuisés**

## Résultats quantitatifs

```
BASELINE — Qwen/Qwen2.5-72B-Instruct
  calls=15 errors=0
  claims_total=33 valid=33 (100% valid)
  claims_avg/passage=2.2
  latency_avg=12.4s (median 12.3s, max 32s)
  tokens in=10318 out=3299
  cost=$0.0050 ($0.00034/passage)

CHALLENGER — Qwen/Qwen3-235B-A22B-Instruct-2507
  calls=12 errors=3 (3× HTTP 429 Too Many Requests)
  claims_total=33 valid=33 (100% valid sur 12 successful)
  claims_avg/passage=2.75 (sur 12 successful)
  latency_avg=30.6s (median 37.3s, max 61.7s)
  tokens in=8382 out=3873
  cost=$0.0010 ($0.00008/passage)

Cost savings if migrate: -77.3%
```

### Détail comparatif par sample

| # | Passage | Baseline claims | Challenger claims | Δ |
|---|---------|----------------|-------------------|---|
| 1 | cs25_amdt_23 | 2 | 2 | = |
| 2 | cs25_amdt_23 | 1 | 4 | +3 |
| 3 | dualuse_reg | 1 | 1 | = |
| 4 | cs25_amdt_24 | 4 | 4 | = |
| 5 | cs25_amdt_23 | 1 | (429 error) | – |
| 6 | cs25_amdt_23 | 3 | 4 | +1 |
| 7 | cs25_amdt_23 | 3 | 3 | = |
| 8 | cs25_amdt_24 | 1 | 4 | +3 |
| 9 | cs25_amdt_24 | 2 | 2 | = |
| 10 | cs25_amdt_24 | 4 | **0** | **-4 ⚠️** |
| 11 | cs25_amdt_23 | 5 | 5 | = |
| 12 | cs25_amdt_24 | 3 | 4 | +1 |
| 13 | dualuse_reg | 1 | (429 error) | – |
| 14 | cs25_amdt_24 | 1 | **0** | **-1 ⚠️** |
| 15 | dualuse_reg | 1 | (429 error) | – |

## Constats critiques

### ❌ Risque qualité — 17% de cas "0 claim"

Sur 12 samples challenger réussis, **2 cas (17%)** ont retourné 0 claims alors que la baseline en extrait 1-4. Latence ultra-courte sur ces cas (1.1-1.3s vs 30-60s normal) suggère **réponse JSON vide** ou parse fail :
- Sample 10 : passage `#/tables/21` (chunk type TABLE) — baseline 4 claims
- Sample 14 : passage `#/texts/20073` — baseline 1 claim

**Impact projeté** : sur un doc de ~3000 sub_chunks, ~510 passages "muets" en challenger. Inacceptable pour le test Armand où la complétude du KG est déterminante.

### ⚠️ Rate limiting DeepInfra (429)

- 3/15 calls challenger (20%) → HTTP 429 Too Many Requests
- 0/15 calls baseline (0%)

DeepInfra throttle Qwen3-235B beaucoup plus que Qwen2.5-72B (probablement infrastructure plus contrainte sur le MoE 235B). Sans retry/backoff dans le code production, le pipeline crashera régulièrement.

### ⚠️ Latence 2.5× plus lente

Médiane 37s (challenger) vs 12s (baseline). Pas un dealbreaker en théorie (pipeline parallèle 180 concurrents) mais combiné au rate limit, le throughput effectif sera dégradé.

### ✅ Schema validity équivalente

100% des claims extraits passent la validation `claim_text + claim_type + structured_form` valide.

### ✅ Exhaustivité légèrement meilleure (quand ça marche)

Dans 4/12 samples (33%), challenger extrait plus de claims que baseline (jusqu'à +3). Indique que le challenger est plus exhaustif sur les passages où il fonctionne.

## Décision : KEEP Qwen2.5-72B

**Pourquoi pas migrer** malgré l'économie -77% :
1. **Risque qualité KG** : 17% de "0-claim" sur des passages productifs = perte massive de rappel
2. **Robustesse** : 20% de 429 rate limit ingérable sans retry/backoff dans le code
3. **Pas d'avis qualitatif juge** (crédits Anthropic épuisés) — décision purement quanti, manque de finesse
4. **Échéance Armand** : pas le moment de prendre un risque qualité

**Conditions pour ré-évaluer** (à réessayer dans 2-4 semaines) :
- Recharger crédits Anthropic pour avoir l'avis Claude
- Tester avec le **prompt full ClaimFirst** (incluant `domain_context` + `predicates_table` du Domain Pack aerospace) — peut-être que le challenger est plus stable avec un prompt plus structuré
- Ajouter retry 429 dans le pipeline production (cf. Vague B Phase 8 — étendre aux calls knowledge_extraction)
- Tester en canary : migrer un seul doc orphelin (e.g. cs25_amdt_22) en challenger et comparer ratio claims/page vs cs25_amdt_23 (baseline)

## Bilan financier

Sur les 17 docs aerospace ingérés :
- Avec Qwen2.5-72B (statu quo) : ~$0.34 × ratio observé extraction × volume = à mesurer post-ingestion complète
- Si migration Qwen3-235B était sûre : économie ~$0.27 sur ce corpus seulement (négligeable au niveau test Armand)
- L'économie devient significative en production sur des milliers de docs : pour 1000 docs similaires aux CS-25, économie ~$15-20 par 1000 docs ingérés

L'économie ne justifie pas le risque qualité **avant** validation qualitative finale (test Armand).

## Annexe — modèles juge testés (tous échec crédit)

```
claude-sonnet-4-20250514          : 400 credit_balance_too_low
claude-3-5-sonnet-20241022        : 400 credit_balance_too_low
claude-sonnet-4-5-20250929        : 400 credit_balance_too_low
claude-3-haiku-20240307           : 400 credit_balance_too_low
```

Les noms de modèles sont valides ; le compte API n'a plus de crédits. À recharger pour ré-exécuter `scripts/rejudge_bench.py --input data/bench/bench_qwen3_235b_20260427_094306.json --model claude-sonnet-4-5-20250929`.
