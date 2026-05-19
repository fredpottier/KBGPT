# V6 — Protocole "Double Bench" comme baromètre

**Date** : 2026-05-15
**Issue** : `BAKEOFF_LLM_DOWNSIZE_2026-05-15.md` a révélé que le score V5.1 dépend massivement du LLM (Δ ≈ 60pp entre DS-V3.1 et Mistral-24B). Pour V6, on veut **mesurer l'amélioration intrinsèque du pipeline**, pas l'illusion donnée par un gros LLM.

## Principe

À chaque jalon V6 significatif, lancer **2 benchs en parallèle** :

| Modèle | Rôle |
|---|---|
| **DeepSeek-V3.1** (671B MoE) | Plafond — ce que le système **peut faire** avec un LLM excellent |
| **Qwen-2.5-72B-Instruct** (72B dense) | Robustesse — ce que le système fait quand le LLM **ne compense pas** |

**Métrique clé** : `Δ = score(DS31) − score(Qwen72)` → **dépendance au LLM**, à minimiser.

## Lecture des résultats

| Effet sur DS31 | Effet sur Qwen72 | Δ évolution | Diagnostic |
|---|---|---|---|
| +5pp | +15pp | ↘ rétrécit | ✅ **Vrai gain pipeline** — la modif rend l'extraction/structure meilleure |
| +2pp | +2pp | = constant | ⚠️ "Papier glacé" — joli sur DS31, pas de gain intrinsèque |
| 0pp | 0pp | = constant | 🟡 Neutre — pas de progrès |
| −5pp | −10pp | ↗ s'ouvre | ❌ **Régression** — la modif dégrade ET accroît la dépendance au LLM |
| +5pp | −5pp | ↗ s'ouvre | ❌ "Compensation LLM" — DS31 masque une régression réelle |

## Pourquoi Qwen-72B et pas Llama-70B comme paire

Le bake-off du 2026-05-15 a montré :
- DS-V3.1 : 0.600 (référence)
- **Qwen-2.5-72B : 0.420** ← choisi comme paire (mid-tier propre)
- Llama-3.3-70B : 0.350 (pattern abstention "low_confidence" rampant — quirk, pas représentatif)
- Qwen-14B AWQ : 0.250
- Mistral-24B : 0.000 (effondrement)

Qwen-72B = compromis entre "comportementalement neutre" (pas de quirk) et "ne compense pas comme DS-V3.1".

## Targets V6 (progressifs)

| Jalon V6 | DS-V3.1 (plafond) | Qwen-72B (robustesse) | Δ (dépendance LLM) | Statut |
|---|---|---|---|---|
| **Baseline V5.1 + V6 OFF** (2026-05-15) | **0.600** | **0.420** | **0.180** | mesuré |
| V6 jalon 1 (Procedure structurée) | ≥ 0.600 | ↑ 0.45-0.50 | ↘ 0.10-0.15 | cible |
| V6 jalon 2 (+ Reference typée) | ≥ 0.600 | ↑ 0.50-0.55 | ↘ 0.05-0.10 | cible |
| V6 jalon 3 (+ ConceptCard) | ≥ 0.620 | ↑ 0.55-0.60 | ↘ 0.05 | cible |
| V6 final | ≥ 0.650 | ≥ 0.600 | ≤ 0.05 | objectif |

**Guard rail** : si à un jalon le score DS-V3.1 **régresse** (< 0.580), on revert la modif. Le plafond ne doit pas baisser.

## Coût d'une mesure

- Bench DS-V3.1 50q : ~$0.30, ~30 min (DeepInfra)
- Bench Qwen-72B 50q : ~$0.30, ~30 min (DeepInfra)
- En parallèle : ~30 min total + scoring 5 min × 2 = ~10 min
- **Total : ~$1 et ~45 min par mesure**

Mode "micro" pour itérations rapides V6 :
- Bench 15q stratifié × 2 modèles = ~12 min × 2 = ~12 min en // + 3 min scoring
- Suffit pour détecter régressions > 10pp

## Outils

### Script unifié

`app/scripts/v6_double_bench.py` :
- Lance DS-V3.1 + Qwen-72B en parallèle sur 50q (ou --limit pour micro)
- Wait fin
- Score les 2 (Llama-70B judge DeepInfra)
- Affiche tableau comparatif + Δ
- Persist `benchmark/runs/v6_double_bench_<tag>_<ts>.json`

### Usage

```bash
# Bench complet (50q × 2 = 100q, ~45 min, ~$1)
docker exec knowbase-app python /app/scripts/v6_double_bench.py --tag v6_milestone_X

# Mode micro pour itération rapide (15q × 2 = 30q, ~15 min, ~$0.30)
docker exec knowbase-app python /app/scripts/v6_double_bench.py --tag v6_quick --limit 15

# Avec sous-set type-spécifique (ex: focus comparison)
docker exec knowbase-app python /app/scripts/v6_double_bench.py --tag v6_compare --limit 8 --types comparison
```

## Historique baseline pre-V6 (2026-05-15)

| Modèle | Mean 50q | Per shape référence |
|---|---|---|
| DS-V3.1 | 0.600 | comparison 0.375, lifecycle 0.250, factual 0.467 |
| Qwen-72B | 0.420 | comparison 0.312, lifecycle 0.000, factual 0.233 |
| **Δ** | **0.180** | lifecycle +0.250pp, factual +0.234pp, comparison +0.063pp |

**Insights** :
- Lifecycle = **+25pp gap** entre DS31 et Qwen72 → tableau de bord cible #1 pour V6 (Procedure structurée + lifecycle relations devraient rétrécir ce gap)
- Factual = **+23pp gap** → Qwen-72B rate factual sur 10/15 → indication forte que l'extraction des claims est sous-exploitée → V6 Reference typée + KG enrichi devraient aider
- Comparison reste difficile pour les 2 (0.375 vs 0.312) → pas seulement un problème de LLM, c'est aussi structurel

## Rappel : pourquoi ce protocole change la donne

**Avant** : on benchait avec DS-V3.1 et on pensait améliorer le pipeline. En réalité, on mesurait le LLM. Risque "Goodhart's Law" : optimiser pour DS-V3.1 alors que le pipeline reste fragile.

**Maintenant** : 2 LLM, 1 pipeline. Si V6 améliore vraiment l'extraction, Qwen-72B remonte (parce qu'il s'appuie sur des structures plus claires). Si V6 est cosmétique, Qwen-72B stagne.

C'est une mesure de **robustesse architecturale**, pas juste de score absolu.
