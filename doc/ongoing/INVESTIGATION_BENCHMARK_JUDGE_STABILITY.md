# Investigation : Instabilité du juge LLM sur les benchmarks T2/T5

*Date : 13 avril 2026*
*Statut : Problème confirmé, investigation en cours*

## Constat

5 runs T2/T5 sur le même corpus réglementaire (mêmes 80 questions, même KG) produisent des scores radicalement différents :

| Run | Date | both_sides | tension | Description |
|-----|------|-----------|---------|-------------|
| 1 | 13/04 00:40 | **83%** | 75% | Haiku synthèse + EC2 vLLM |
| 2 | 13/04 01:18 | **84%** | 69% | Haiku synthèse + EC2 vLLM |
| 3 | 13/04 01:58 | **7%** | 73% | Haiku dégradé (crédits en cours d'épuisement) |
| 4 | 13/04 06:06 | **0%** | 0% | Timeout (plus de LLM disponible) |
| 5 | 13/04 08:47 | **37%** | 90% | Haiku synthèse (crédits rechargés) |

Les runs 1, 2 et 5 sont les seuls avec un LLM de synthèse fonctionnel. Pourtant les scores varient de **37% à 84%** sur `both_sides_surfaced`.

## Preuve d'instabilité du juge

Même question, même juge (gpt-4o-mini), réponses de qualité comparable :

**Question** : "Le RGPD et la CCPA ont-ils la même approche du consentement ?"

| | Run 1 (00:40) | Run 5 (08:47) |
|---|---|---|
| Réponse | "approches différentes du consentement..." | "approches fondamentalement différentes..." |
| both_sides_surfaced | **1.0** | **0.0** |
| tension_mentioned | 1.0 | 1.0 |
| claim1_coverage | 0.231 | 0.462 |
| claim2_coverage | 0.167 | 0.333 |

Le Run 5 a une **meilleure** couverture des claims (0.462 vs 0.231) mais un score `both_sides` à 0 au lieu de 1. Le juge est incohérent.

## Causes identifiées

### 1. Non-déterminisme de gpt-4o-mini

Le juge LLM (gpt-4o-mini) est appelé avec `temperature=0` mais les API OpenAI ne garantissent pas le déterminisme même à temperature 0. Sur des réponses longues et nuancées (corpus réglementaire), le juge peut basculer entre "oui les deux côtés sont présents" et "non" selon l'appel.

### 2. Format de réponse variable

Les réponses OSMOSIS varient en format entre les runs :
- Run 1 : texte plat ("Le RGPD et la CCPA ont des approches différentes...")
- Run 5 : markdown structuré ("# Le RGPD et la CCPA : Des approches fondamentalement différentes\n## 1. Rôle struct...")

Le juge peut être sensible au format — un texte structuré avec des headers markdown peut être évalué différemment d'un texte plat, même si le contenu est identique.

### 3. Mode "hybrid" inconsistant

Le mode d'évaluation "hybrid" combine un score keyword (déterministe) et un score LLM judge (non-déterministe). Le Run 1 inclut `keyword_both_sides: 0.0` dans l'évaluation, le Run 5 ne l'a pas. La combinaison des deux signaux peut varier.

## Impact

**Le benchmark T2/T5 ne peut pas être utilisé de manière fiable pour évaluer l'impact d'un changement.** Un delta de +/-20 points peut être du bruit du juge, pas un signal réel. C'est incompatible avec l'objectif du benchmark : guider les modifications avec confiance.

## Pistes de solution

### Piste 1 : Moyenne sur N runs (palliatif)

Exécuter chaque benchmark 3 fois et prendre la moyenne. Réduit le bruit mais multiplie le coût par 3.

- Avantage : simple, pas de changement de code
- Inconvénient : 3x le coût, 3x le temps
- Fiabilité attendue : modérée (la variance reste)

### Piste 2 : Juge déterministe (keyword-only)

Supprimer le juge LLM et ne garder que le scoring par keywords. Déterministe à 100%.

- Avantage : reproductible, gratuit
- Inconvénient : moins précis (les keywords ne captent pas la nuance)
- Fiabilité attendue : haute (mais scores absolus plus bas)

### Piste 3 : Juge plus stable (Claude ou GPT-4o)

Remplacer gpt-4o-mini par un modèle plus capable (gpt-4o ou Claude Sonnet) qui est plus stable dans ses évaluations.

- Avantage : meilleure cohérence
- Inconvénient : coût significativement plus élevé
- Fiabilité attendue : haute

### Piste 4 : Prompt de juge structuré avec rubrique

Au lieu de demander au juge "est-ce que les deux côtés sont surfacés ? (0 ou 1)", lui donner une **rubrique détaillée** avec des critères vérifiables :

```
Critère "both_sides_surfaced" :
- Score 1.0 : La réponse mentionne explicitement le point de vue du document A ET du document B
- Score 0.5 : La réponse mentionne un seul point de vue mais fait allusion à une divergence
- Score 0.0 : La réponse ne présente qu'un seul point de vue sans mentionner de divergence

Vérification : extrais les passages qui correspondent à chaque document.
```

Le juge doit **justifier** son score en citant les passages → force la cohérence.

- Avantage : meilleure cohérence, pas de changement de modèle
- Inconvénient : plus de tokens en output (le juge doit justifier)
- Fiabilité attendue : haute

### Piste 5 : Double juge avec arbitrage

Deux juges (ex: gpt-4o-mini + Qwen vLLM) évaluent chaque sample. Si les scores divergent, un troisième appel tranche. Inspiré du "jury LLM" de la littérature.

- Avantage : très fiable
- Inconvénient : complexe, coût x2-3
- Fiabilité attendue : très haute

## Recommandation

**Piste 4 (prompt structuré avec rubrique)** est le meilleur rapport effort/fiabilité :
- Pas de changement de modèle (reste gpt-4o-mini)
- Coût quasi identique (~20 tokens de plus en output)
- Le juge doit **prouver** son évaluation → réduit l'aléatoire
- Compatible avec le mode hybrid existant

En complément, **Piste 1 (3 runs)** pour les benchmarks de référence (avant/après un changement majeur).

## Évolution stratégique (13-14 avril 2026)

### M-Prometheus-14B déployé sur Ollama local (RTX 5070 Ti)

Modèle d'évaluation multilingue (FR+EN), 9.1 GB en Q4_K_M. Tests initiaux :
- Test 1 (bonne réponse) : **90,85,70** → meilleur que tous les autres (nuancé)
- Test 2 (mauvaise réponse) : **0,0,0** → correct
- Test 3 (réponse partielle) : **100,100,100** → même faiblesse que les autres

Configuration : `T2T5_JUDGE_PROVIDER=ollama`, `T2T5_JUDGE_MODEL_NAME=m-prometheus-14b`

### Architecture recommandée : Evidence-based prompt + règles déterministes

Plutôt que de chercher un meilleur modèle, changer le **prompt** et la **logique de scoring** :

**Couche 1 — LLM extracteur** (M-Prometheus) :
```
Claims in corpus:
- Claim 1: "RGPD = 20M€ ou 4% CA mondial"
- Claim 2: "AI Act = 35M€ ou 7% CA mondial"
Answer: "..."
For each claim: is it covered? YES/NO
```

**Couche 2 — Code déterministe** :
```python
coverage = sum(covered) / len(claims)
if coverage < 1.0:
    both_sides = coverage * 0.5  # partiel = pénalisé
```

Avantage : LLM fait du oui/non (fiable), le code calcule le score (déterministe).

### Multi-judge (optionnel, pour les 20% de cas critiques)

Setup Ollama local (coût = 0, juste du temps) :
- **Judge A** : M-Prometheus-14B (principal, multilingue, 9.1 GB)
- **Judge B** : Prometheus-7B v2.0 (complémentaire, 4.4 GB)
- Ollama swap automatiquement entre les deux modèles
- Si Judge A et Judge B divergent significativement → flag le sample
- Temps estimé : ~40 min pour 80 questions (2x le temps single-judge)

Activation via env var : `T2T5_MULTI_JUDGE=true`

## Fichiers impactés

- `benchmark/evaluators/t2t5_diagnostic.py` — prompt du juge, support Ollama, multi-judge
- `docker-compose.yml` — variables T2T5_JUDGE_PROVIDER, T2T5_JUDGE_MODEL_NAME, OLLAMA_URL
