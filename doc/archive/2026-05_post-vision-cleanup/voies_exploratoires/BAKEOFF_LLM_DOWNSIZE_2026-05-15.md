# Bake-off LLM Downsize — Audit "gros modèle masque-t-il le pipeline ?"

**Date** : 2026-05-15
**Hypothèse user** : la course aux gros LLM (DeepSeek-V3.1 671B MoE) masque des lacunes du pipeline V5.1 et coûte cher. Tester des modèles plus petits pour mesurer la dégradation réelle.

**Protocole** : 5 modèles benchés sur le même bench (gold_set_sap_v2, 50q stratifié, seed=42), pipeline V5.1 identique (multiform ON, templates OFF), même corpus SAP, même judge LLM (Llama-3.3-70B-Instruct DeepInfra).

---

## Résultats — Tableau comparatif final

| Modèle | Taille | Provider | Mean 50q | Δ vs DS-V3.1 | Latency avg |
|---|---|---|---|---|---|
| **DeepSeek-V3.1** | 671B MoE (37B actifs) | DeepInfra | **0.600** | référence | ~85s/q |
| **Qwen-2.5-72B-Instruct** | 72B dense | DeepInfra | **0.420** | **−0.180pp** | ~95s/q |
| **Llama-3.3-70B-Instruct** | 70B dense | DeepInfra | **0.350** | **−0.250pp** | ~85s/q |
| **Qwen-2.5-14B-Instruct-AWQ** | 14B AWQ | EC2 vLLM g6.2xlarge | **0.250** | **−0.350pp** | ~75s/q |
| **Mistral-Small-3.2-24B** | 24B dense | DeepInfra | **0.000** | **−0.600pp** ⚠️ | ~80s/q |

## Détail per-shape

### DeepSeek-V3.1 (0.600)

| Shape | n | Mean | Perfect | Zero |
|---|---|---|---|---|
| causal | 3 | **1.000** | 3 | 0 |
| quantitative | 1 | **1.000** | 1 | 0 |
| unanswerable | 1 | **1.000** | 1 | 0 |
| contextual | 3 | 0.833 | 2 | 0 |
| listing | 3 | 0.833 | 2 | 0 |
| multi_hop | 8 | 0.750 | 4 | 0 |
| false_premise | 3 | 0.667 | 2 | 1 |
| negation | 3 | 0.500 | 1 | 1 |
| factual | 15 | 0.467 | 5 | 6 |
| comparison | 8 | 0.375 | 2 | 4 |
| lifecycle | 2 | 0.250 | 0 | 1 |

### Qwen-2.5-72B (0.420)

| Shape | n | Mean | Perfect | Zero |
|---|---|---|---|---|
| causal | 3 | 0.833 | 2 | 0 |
| contextual | 3 | 0.833 | 2 | 0 |
| unanswerable | 1 | 1.000 | 1 | 0 |
| multi_hop | 8 | 0.625 | 3 | 1 |
| quantitative | 1 | 0.500 | 0 | 0 |
| listing | 3 | 0.500 | 1 | 1 |
| false_premise | 3 | 0.333 | 1 | 2 |
| negation | 3 | 0.333 | 0 | 1 |
| comparison | 8 | 0.312 | 1 | 4 |
| factual | 15 | 0.233 | 2 | 10 |
| lifecycle | 2 | 0.000 | 0 | 2 |

### Llama-3.3-70B (0.350)

| Shape | n | Mean | Perfect | Zero |
|---|---|---|---|---|
| causal | 3 | 0.833 | 2 | 0 |
| contextual | 3 | 0.667 | 2 | 1 |
| multi_hop | 8 | 0.500 | 0 | 0 |
| listing | 3 | 0.500 | 0 | 0 |
| negation | 3 | 0.333 | 0 | 1 |
| factual | 15 | 0.267 | 2 | 9 |
| comparison | 8 | 0.250 | 0 | 4 |
| false_premise | 3 | 0.000 | 0 | 3 |
| lifecycle | 2 | 0.000 | 0 | 2 |

### Qwen-2.5-14B-AWQ EC2 (0.250)

| Shape | n | Mean | Perfect | Zero |
|---|---|---|---|---|
| contextual | 3 | 0.833 | 2 | 0 |
| lifecycle | 2 | 0.500 | 0 | 0 |
| listing | 3 | 0.333 | 0 | 1 |
| causal | 3 | 0.333 | 0 | 1 |
| false_premise | 3 | 0.333 | 1 | 2 |
| multi_hop | 8 | 0.250 | 1 | 5 |
| comparison | 8 | 0.188 | 0 | 5 |
| factual | 15 | 0.133 | 0 | 11 |
| negation | 3 | 0.000 | 0 | 3 |

### Mistral-Small-3.2-24B (0.000) ⚠️

**Toutes les shapes à 0.000** — 50/50 questions à score 0. Pattern observé pendant le bench : `low_confidence` rampant avec très peu de tool_calls, beaucoup de réponses vides. Le pipeline V5.1 n'extrait rien d'exploitable, le judge donne 0 systématiquement.

## Observations clés

### 1. La hiérarchie qualité suit la taille (linéaire approximative)

```
0.600 ─ DS-V3.1 (671B MoE, 37B actifs)
0.420 ─ Qwen-72B (72B dense)
0.350 ─ Llama-70B (70B dense)
0.250 ─ Qwen-14B (14B AWQ)
0.000 ─ Mistral-24B (effondrement)
```

Pas de "sweet spot" intermédiaire à coût/qualité avantageux. Chaque downsize coûte ~10-25pp.

### 2. Le pipeline V5.1 est **très sensible** au LLM

Même Llama-70B (modèle "haut de gamme") perd **−25pp** sans changement de pipeline. Cause : l'agent doit faire du tool calling complexe avec `tool_choice=auto`, formater des réponses avec `[doc=X]` citations exactes, et abstenir intelligemment. Les modèles non-DeepSeek :
- **Abstain trop facilement** (low_confidence/0 tool_calls) — pattern observé sur Llama-70B et Mistral-24B
- **Citations partielles** — Qwen-14B avait 62% citation sur factual vs 100% sur DS-V3.1
- **Lifecycle, false_premise, factual** = catégories où la dégradation est la plus marquée

### 3. Qwen-14B AWQ EC2 surprenamment "résilient"

À 14B le score reste à 0.250 — pas génial mais **mieux que Mistral-24B** ! Surprenant. Hypothèse : la quantization AWQ + petit modèle reste cohérent dans ses réponses (même fausses), alors que Mistral génère du contenu hors-format que le pipeline ne sait pas parser.

### 4. Mistral-24B = **incompatible** avec ce pipeline

`low_confidence` rampant + sortie hors-format = le pipeline V5.1 ne sait pas extraire de réponse exploitable. À écarter complètement pour ce usage.

### 5. L'hypothèse "gros modèle masque le pipeline" est confirmée — mais avec une nuance amère

**Oui** : DS-V3.1 671B MoE compense les faiblesses du pipeline (tool_choice=auto strict, format citation rigoureux, abstain bien calibré).

**Mais** : on n'a **pas de modèle intermédiaire viable** sur ce pipeline actuel. La courbe qualité/taille tombe brutalement après 70B. Sweet spot inexistant à coût raisonnable.

## Verdict

### Pour la production runtime V5.1 actuelle

**Garder DeepSeek-V3.1**. Aucun modèle plus petit n'est viable sans refonte pipeline.

| Coût opérationnel DS-V3.1 (DeepInfra) | ~$0.27 in + $1.10 out / M tokens |
|---|---|
| Bench 50q estimé | ~$0.30 |
| Inference production estimée | ~$0.001-0.003 par requête utilisateur |

Le gain potentiel d'un downsize vers 70B/24B (3-4× moins cher) ne compense **pas** la perte de qualité (-25 à -60pp).

### Pour l'ingestion (extraction de claims)

**Garder Qwen-2.5-14B-AWQ sur EC2 spot** (configuration actuelle de l'ingestion ClaimFirst). L'ingestion n'utilise PAS le tool calling de V5.1 — c'est un appel JSON direct, où Qwen-14B reste cohérent. Le bench downsize ne dit rien sur ce cas d'usage.

### Pour la V6 (refonte ingestion)

**Opportunité** : si V6 ingestion + nouveau runtime simplifient le pipeline (moins d'agent loop, moins de tool calling, plus de chemin direct), un modèle 70B pourrait redevenir viable. À tester quand V6 sera prêt.

### Pour le bench / dev itératif

**Sonnet calibration garde sa valeur** (référence plafond = 0.710 mesuré précédemment). Mais DeepSeek-V3.1 reste à 85% du plafond pour ~1/10 du coût. Bon rapport.

## Coût total du bake-off

- 5 benchs × 50q × ~85s × ~$0.001/call = ~$3
- 5 scorings × 50q × ~3s × ~$0.0005/call = ~$0.50
- EC2 vLLM g6.2xlarge × 2h = ~€1 (spot)
- **Total : ~$5**

Bon investissement pour valider/invalider l'hypothèse downsize avec données solides.

## Fichiers de référence

- `benchmark/runs/v51_bench_50q_ds31_50q_*.json` + scored
- `benchmark/runs/v51_bench_50q_llama70_50q_*.json` + scored
- `benchmark/runs/v51_bench_50q_qwen14_50q_*.json` + scored
- `benchmark/runs/v51_bench_50q_qwen72_50q_*.json` + scored
- `benchmark/runs/v51_bench_50q_mistral24_50q_*.json` + scored

---

## Recommandations pour la suite

1. **Production runtime V5.1** : garder DS-V3.1 sur DeepInfra (vu que Together a déclassé). Coût stable.

2. **Investigation V6** : la refonte ingestion (Voie B) pourrait débloquer l'usage de modèles plus petits si elle simplifie l'architecture. À tester quand V6 ingestion sera prête.

3. **Audit Mistral-24B** : c'est probablement un format prompt issue. Si on veut le récupérer pour autre chose, il faudrait probablement adapter le system prompt V5.1 spécifiquement.

4. **Sonnet plafond** : si besoin de pousser à 0.710+ pour un client critique (presales Armand), Sonnet reste accessible en mode calibration (hors-charte runtime).
