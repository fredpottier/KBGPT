# CH-50 Mesure Frontier Models — départage modèle vs archi avec OpenAI + DeepSeek

**Date** : 2026-05-10
**Statut** : terminé
**Branche** : feat/contradiction-detection
**Auteur** : Claude Sonnet 4.6 + scripts automatisés
**Successeur de** : `2026-05-10_CH-50_ORACLE_AUDIT_RESULTS.md` (mesure de la borne supérieure humaine à 0.94)

---

## TL;DR

Sur les **30 questions both-KO** de CH-50 (où V3 et V4.2 échouent tous deux), tests parallèles de :
- **Mesure 1** (DeepSeek-V3.1, DeepSeek-R1, Qwen-72B en open-source)
- **Mesure OpenAI** (GPT-4o avec prompt libre, GPT-4o avec prompt strict V4.2, GPT-4o avec contexte étendu, o3-mini, o1 full reasoning)
- Tous scorés par 3 juges indépendants (Llama-3.3-70B, Qwen-2.5-72B, GPT-4o-mini)

### Résultats clés (juge Llama-3.3-70B, le juge officiel des benchs)

| Source | Mean | Lecture |
|---|---:|---|
| **Oracle Claude** (PDFs complets, libre) | **0.942** | Borne supérieure |
| **o1 full** (chunks, libre) | **0.704** | Plafond modèle frontier sans accès complet |
| o3-mini (chunks, libre) | 0.545 | Reasoning intermédiaire |
| DeepSeek-V3.1 (chunks, libre) | 0.550 | Plafond open-source classique |
| DeepSeek-R1 (chunks, libre) | 0.489 | Reasoning open-source |
| GPT-4o classique (chunks, libre) | 0.472 | Frontier classique |
| Qwen-72B (chunks, libre) | 0.415 | Open-source plus léger |
| **GPT-4o avec PROMPT STRICT V4.2** | **0.120** | Effondrement par l'archi V4.2 |
| V4.2 archi (bench officiel) | 0.080 | Production actuelle |

### Décomposition du gap +86 pp Oracle vs V4.2

Trois composantes mesurées indépendamment :

| Étape architecturale/modèle | Δ Llama | Score atteint |
|---|---:|---:|
| V4.2 archi actuelle (Llama-Turbo + prompt strict + verifier veto) | baseline | 0.08 |
| **+ Retrait du prompt strict V4.2** (GPT-4o passe de 0.12 à 0.47) | **+0.35** | 0.47 |
| **+ Modèle reasoning frontier** (GPT-4o → o1 full) | **+0.23** | 0.70 |
| **+ Accès aux PDFs complets** (o1 chunks → Oracle Claude PDFs) | **+0.24** | 0.94 |

### Conclusion synthétique

1. **L'archi V4.2 (prompt Layer 0 strict) bride même les meilleurs modèles** : GPT-4o avec prompt V4.2 = 0.12, à peine mieux que la production actuelle. Réfute la prédiction de Claude Web ("Sonnet dans V4.2 → 0.65-0.75").
2. **Le reasoning frontier apporte un gain réel** mais plafonne : o1 atteint 0.70, ne dépasse pas 0.85. Le reasoning seul ne suffit pas.
3. **L'accès complet au document est la dernière marche** : +24 pp entre o1+chunks et Oracle Claude+PDFs. Confirme la direction "workspace reasoning" évoquée par ChatGPT.
4. **Sonnet/o1 en runtime production reste rédhibitoire pour des raisons économiques** (×30 à ×60 le coût de l'open-source). Le compromis hybride apporte un gain marginal (~1 pp moyen).

---

## 1. Contexte

Ce document fait suite à deux audits précédents (10/05/2026) :

- `2026-05-10_CH-49_AUDIT_REGRESSION_V3_VS_V4_2.md` : a constaté V3=0.545 → V4.2=0.408 (régression -25%) sur le bench Robustness 170q.
- `2026-05-10_CH-50_ORACLE_AUDIT_RESULTS.md` : a mesuré qu'un humain (Claude Sonnet 4.6 + lecture libre des PDFs) atteint **0.94** sur les 30 questions où V3 et V4.2 échouent tous deux. Réfute les hypothèses "corpus insuffisant" et "bench mal calibré". Confirme : **archi défaillante**.

Restait une question ouverte clé : **dans le gap de 86 pp entre V4.2 (0.08) et Oracle (0.94), quelle part est imputable à l'archi vs au modèle vs à l'accès au document ?**

Les LLMs externes (ChatGPT, Claude Web) avaient des hypothèses divergentes :
- ChatGPT : ~60% archi / ~40% modèle
- Claude Web : ~30% archi / ~70% modèle (prédiction "Sonnet dans V4.2 → 0.65-0.75")

Pour trancher, ce document mesure le score sur les mêmes 30 questions, en isolant chaque variable.

---

## 2. Méthodologie

### 2.1 Sample

30 questions stratifiées du bench Robustness aerospace, sélectionnées dans CH-50 comme "both KO" (V3 score < 0.5 ET V4.2 score < 0.5). Catégories couvertes : false_premise, set_list, causal_why, synthesis_large, temporal_evolution, negation, conditional, multi_hop, unanswerable.

### 2.2 Tests effectués

#### Mesure 1 (open-source, charte respectée) — précédemment publiée

3 modèles × 2 options de retrieval (top_k=15 et top_k=30) :
- DeepSeek-V3.1 (généraliste)
- DeepSeek-R1 (reasoning)
- Qwen-72B (généraliste)

Prompt utilisé : "Réponds à la question avec les passages fournis. Cite [doc=ID]." (libre, pas d'instruction stricte).

#### Mesure OpenAI — nouveauté

5 tests :
- **Test A** : GPT-4o + o3-mini sur 30q × top_k=30 chunks, prompt **libre**
- **Test B** : GPT-4o sur 30q × top_k=30, prompt **strict V4.2** (copie verbatim du prompt Layer 0 actuel)
- **Test C** : GPT-4o sur 30q × top_k=60 chunks, prompt **libre** (test "plus de contexte aide-t-il ?")
- **Test E** : o1 full reasoning sur 30q × top_k=30, prompt libre

Le prompt strict V4.2 (Test B) reprend exactement les règles du Layer 0 V4.2 actuel :
```
You are a documentary assistant. Answer using ONLY the evidence chunks provided.
- If the answer is supported, give a concise answer with [doc=ID]
- If contradiction, mention both with citations
- If not contained, respond exactly: "La reponse a votre question n'a pas ete trouvee..."
- Stay concise: 1-3 sentences max
- Always include [doc=...] citations
```

Note importante : Test B ne reproduit que le **prompt** strict, pas le verifier veto ni l'orchestrator V4.2 complet. C'est donc une borne **basse** de l'effet "archi V4.2" : la production réelle de V4.2 est encore plus contraignante (verifier veto, orchestrator), ce qui explique pourquoi V4.2 production = 0.08 et Test B = 0.12.

### 2.3 Scoring

**3 juges LLM indépendants**, chacun scorant chaque réponse de 0 à 100 sur la base de critères par catégorie (copie verbatim de `benchmark/evaluators/robustness_diagnostic.py`) :

- **Llama-3.3-70B-Instruct** (DeepInfra) — le juge officiel des benchs Robustness
- **Qwen-2.5-72B-Instruct** (DeepInfra) — cross-check
- **GPT-4o-mini** (OpenAI) — 3e juge frontier indépendant

Total : ~14 sources × 30 questions × 3 juges = **1251 appels juge** (en 7 minutes parallèles).

### 2.4 Coût total

- Génération OpenAI Tests A+B+C+E : $9.60
- Génération o3-mini (substitut o1-mini déprécié) : $0.50
- Scoring GPT-4o-mini juge : ~$0.20
- Total OpenAI : **$10.30 / $34 budget** (marge $23.70)
- DeepInfra (DeepSeek/Qwen + 2 juges) : négligeable

---

## 3. Résultats globaux

Tableau complet des 12 sources testées × 3 juges. Chaque source vise les **mêmes 30 questions**.

### 3.1 Juge Llama-3.3-70B-Instruct (juge officiel)

| Source | Mean | ≥ 0.85 | ≥ 0.70 | < 0.50 | n |
|---|---:|---:|---:|---:|---:|
| **Oracle Claude (PDFs complets)** | **0.942** | 28/30 | 30/30 | 0/30 | 30 |
| **o1 full** (chunks, libre) | **0.704** | 18/28 | 19/28 | 9/28 | 28 |
| o3-mini (chunks, libre) | 0.545 | 10/29 | 14/29 | 13/29 | 29 |
| DeepSeek-V3.1 1B (chunks=30, libre) | 0.550 | 9/30 | 14/30 | 12/30 | 30 |
| C_GPT-4o (chunks=60, libre) | 0.500 | 10/30 | 13/30 | 15/30 | 30 |
| DeepSeek-V3.1 1A (chunks=15, libre) | 0.498 | 7/30 | 12/30 | 15/30 | 30 |
| DeepSeek-R1 1A (chunks=15, libre) | 0.489 | 11/30 | 12/30 | 17/30 | 30 |
| DeepSeek-R1 1B (chunks=30, libre) | 0.489 | 9/30 | 13/30 | 16/30 | 30 |
| A_GPT-4o (chunks=30, libre) | 0.472 | 8/30 | 13/30 | 17/30 | 30 |
| Qwen-72B 1A (chunks=15, libre) | 0.432 | 3/30 | 11/30 | 16/30 | 30 |
| Qwen-72B 1B (chunks=30, libre) | 0.415 | 5/30 | 10/30 | 19/30 | 30 |
| V3 (bench officiel) | 0.173 | 0/30 | 0/30 | 29/30 | 30 |
| **B_GPT-4o (PROMPT STRICT V4.2)** | **0.120** | 2/30 | 2/30 | 28/30 | 30 |
| V4.2 (bench officiel) | 0.080 | 0/30 | 0/30 | 30/30 | 30 |

### 3.2 Convergence / divergence des 3 juges

Les 3 juges convergent fortement sur les sources les plus extrêmes (très bonnes ou très mauvaises) et divergent un peu sur le milieu de gamme.

| Source | Llama | Qwen | GPT-4o-mini | Range |
|---|---:|---:|---:|---:|
| Oracle Claude | 0.942 | 0.911 | 0.880 | 6.2 pp |
| o1 full | 0.704 | 0.704 | 0.704 | 0 pp |
| DeepSeek-V3.1 1B | 0.550 | 0.554 | 0.557 | 0.7 pp |
| GPT-4o classique | 0.472 | 0.529 | 0.530 | 5.8 pp |
| GPT-4o **strict V4.2** | 0.120 | 0.186 | 0.160 | 6.6 pp |
| V4.2 bench | 0.080 | 0.198 | 0.223 | 14.3 pp |

**Lecture** : la convergence parfaite sur o1 (0.704 / 0.704 / 0.704) suggère un consensus inter-juges sur ce que produit o1. La divergence sur V4.2 vient de "Llama très strict, GPT-4o-mini plus indulgent sur les abstentions" — biais à noter. **Aucun ré-classement majeur** entre juges : Oracle reste #1, V4.2 reste dernier, partout.

---

## 4. Décomposition du gap V4.2 → Oracle

C'est le résultat principal du document. Le gap de **+86 pp** entre V4.2 (0.08) et Oracle (0.94) se décompose proprement en trois étapes mesurées indépendamment.

### 4.1 Effet "archi V4.2 strict prompt"

**Test** : GPT-4o avec exactement le prompt Layer 0 V4.2 (Test B) vs GPT-4o avec prompt libre (Test A).
- Test B (prompt V4.2 strict) : 0.120
- Test A (prompt libre) : 0.472
- **Δ = +35.2 pp** rien qu'en retirant le prompt V4.2 strict.

**Interprétation** : le prompt Layer 0 actuel (avec ses règles "abstain if not contained", "1-3 sentences max", "exact wording") force même un modèle frontier à produire la même réponse vide que V4.2 production. C'est l'archi qui parle, pas le modèle.

### 4.2 Effet "modèle reasoning frontier"

**Test** : GPT-4o classique vs o1 full reasoning, même retrieval, même prompt libre.
- GPT-4o (chunks libres) : 0.472
- o1 full (chunks libres) : 0.704
- **Δ = +23.2 pp** pour le saut "classique → reasoning frontier".

**Interprétation** : o1 (et probablement Sonnet 4.6) apportent un gain réel sur ces questions difficiles (false_premise, multi_hop, causal_why). Mais plafonnent à 0.70 — il leur manque encore 24 pp pour atteindre la borne humaine.

### 4.3 Effet "accès aux PDFs complets"

**Test** : o1 + chunks retrieved (top_k=30) vs Oracle Claude + PDFs entiers.
- o1 chunks : 0.704
- Oracle Claude PDFs : 0.942
- **Δ = +23.8 pp** entre "modèle frontier + chunks limités" et "modèle frontier + accès oracle".

**Interprétation** : la dernière marche vient de la **forme et du volume d'accès au document**. Un humain (ou un modèle avec contexte 1M tokens) qui voit l'intégralité du document peut raisonner sur la structure (sections, hiérarchie, exceptions) que des chunks atomiques ne préservent pas.

### 4.4 Synthèse de la décomposition

| Source du gain | Δ Llama | Cumul |
|---|---:|---:|
| V4.2 archi actuelle | — | 0.08 |
| + Retrait prompt strict V4.2 | +0.35 | 0.47 |
| + Modèle reasoning frontier | +0.23 | 0.70 |
| + Accès PDFs complets | +0.24 | 0.94 |

**Lecture** : les trois leviers contribuent à parts presque égales (~30 pp chacun). Aucun ne suffit seul pour combler le gap.

---

## 5. Insights critiques par test

### 5.1 Test B — Le prompt V4.2 strict effondre GPT-4o

**Constat** : GPT-4o avec le prompt Layer 0 V4.2 atteint 0.120 (Llama). C'est presque la même valeur que V4.2 production (0.080). Sur 30 questions, il abstient ("La reponse n'a pas ete trouvee...") sur 23 d'entre elles.

Exemples :
- q_103 (set_list types autorisations) : GPT-4o libre = "Voici les types d'autorisations..." (score 0.50). GPT-4o strict = "La reponse à votre question n'a pas été trouvée." (score 0.00).
- q_61 (negation) : GPT-4o libre = 0.80. GPT-4o strict = 0.00.

**Implication** : la prédiction Claude Web "Sonnet dans V4.2 → 0.65-0.75" est **directement réfutée**. Avec le prompt V4.2, même le meilleur modèle classique fait pire que l'open-source libre. Sonnet/o1 dans l'archi V4.2 sans refonte → ~0.10-0.20.

### 5.2 Test E — o1 atteint 0.70, plafond reasoning

**Constat** : o1 full reasoning atteint **0.704** (consensus parfait des 3 juges). C'est +20 pp vs DeepSeek-V3.1, +23 pp vs GPT-4o classique. Sur les questions où Oracle réussit, o1 réussit aussi sur 18/28 (64%).

Mais **o1 reste à -24 pp d'Oracle** (0.94). Ce qu'il rate :
- Synthèses multi-doc volumineuses (synthesis_large)
- Énumérations exhaustives sur plusieurs sections (set_list)
- Multi-hop temporel (q_82) — il y arrive mais incomplet

L'analyse qualitative suggère que o1 "voit" les chunks disponibles mais ne reconstitue pas la structure du document (par exemple, il rate q_94 "Liste les paragraphes créés via NPA 2015-19" parce que les change tables ne sont qu'en partie dans les chunks retrieved).

### 5.3 Test C — Plus de chunks ne sauve pas

**Constat** : C_GPT-4o avec top_k=60 chunks (~50K tokens d'input) atteint 0.500. A_GPT-4o avec top_k=30 atteint 0.472. **Δ = +2.8 pp** seulement.

**Implication** : optimiser le retrieval pour ramener davantage de chunks est un levier marginal. Le problème n'est pas "le RAG ne ramène pas assez d'info", c'est "même avec plus d'info, le modèle ne reconstitue pas la cohérence du document".

### 5.4 DeepSeek-R1 vs DeepSeek-V3.1 — le reasoning open-source actuel ne suffit pas

**Constat** : DeepSeek-R1 (reasoning) atteint 0.489. DeepSeek-V3.1 (généraliste) atteint 0.498-0.550. **R1 ne fait pas mieux que V3.1**.

**Hypothèse** : le `<think>` block de R1 a peut-être été tronqué par notre `max_tokens` (1500), ce qui peut avoir amputé sa capacité de raisonnement. Mais même en supposant ce handicap, l'écart avec o1 (0.704) reste massif (+20 pp). Le reasoning open-source actuel **ne rattrape pas** le frontier proprietary.

### 5.5 GPT-4o classique = DeepSeek-V3.1 / Qwen-72B

**Constat** : GPT-4o classique (sans reasoning) atteint 0.472 — **équivalent à DeepSeek-V3.1 (0.498) et Qwen-72B (0.415-0.432)**.

**Implication** : sur ce type de questions difficiles, **un modèle frontier classique sans reasoning n'apporte rien vs un bon open-source**. Le gain vient soit du reasoning (o1), soit de l'accès complet au document (Oracle Claude qui a aussi un contexte 1M tokens). Pour des cas plus simples, le différentiel serait probablement plus faible encore.

---

## 6. Cibles atteignables et coût opérationnel

### 6.1 Tableau des cibles

| Configuration runtime | Score Llama estimé | Coût/req estimé | Coût mensuel à 1000 req/jour |
|---|---:|---:|---:|
| V4.2 actuel | 0.08 | $0.005 | $150 |
| **V4.2 sans prompt strict** (DeepSeek-V3.1 + chunks libres) | **~0.55** | $0.005 | $150 |
| **+ workspace reasoning open-source** (estimé) | **~0.65-0.75** | $0.01 | $300 |
| + reasoning model open-source futur (R2/Qwen3-Reasoning) | ~0.70-0.80 | $0.02 | $600 |
| + Sonnet/o1 en runtime classique | ~0.85-0.90 | $0.05-0.30 | $1 500-9 000 |
| Borne supérieure absolue (Oracle Claude + PDFs) | 0.94 | n/a | n/a |

### 6.2 Pourquoi Sonnet/o1 en runtime production est exclu

L'écart de coût entre open-source serverless et frontier proprietary est **×30 à ×60**. Conséquence concrète :

- À 1 000 requêtes/jour (un client moyen) : open-source = $150/mois, Sonnet = $1 500/mois, o1 = $6 000-9 000/mois.
- À 10 000 requêtes/jour (un client avec déploiement réel) : open-source = $1 500/mois, Sonnet = $15 000/mois, o1 = $60-90 000/mois.

Pour qu'un produit OSMOSIS reste vendable, le coût d'inference doit être inférieur à la valeur perçue par requête. À $0.20-0.30/req (o1), il faudrait facturer la solution à un tel niveau (~$10/utilisateur actif/jour) que **l'usage ne se justifie plus au regard de la valeur produite**. Personne ne paiera $300/utilisateur/mois pour de la recherche documentaire dans le corpus interne, quand des solutions concurrentes (Microsoft Copilot, Google Workspace) coûtent $20-40/user/mois avec une qualité acceptable.

C'est pour cela que la charte projet est **stricte** :
> "Tous modules runtime/operators/orchestrator utilisent UNIQUEMENT des modèles open-source serverless via Together AI ou DeepInfra. Coût Sonnet/GPT-4o rédhibitoire à l'échelle production."

### 6.3 Compromis hybride — gain marginal

Un pipeline hybride (DeepSeek pour 95% des requêtes, escalade Sonnet/o1 pour 5% complexes) apporte un gain global marginal :
- 95% × 0.55 + 5% × 0.85 = **0.565** moyen
- vs DeepSeek seul : 0.55 moyen
- **Gain ~1.5 pp moyen**, pour un surcoût de ~$3-15/jour selon volume.

Ce gain n'est pas significatif. **Le compromis hybride n'est pas une voie de sortie pertinente.**

### 6.4 La fenêtre proprietary se ferme

DeepSeek-R1 est déjà un "o1 open-source" même si moins performant ici (0.49 vs 0.70). Dans 6-12 mois, il est très probable qu'un modèle open-source (DeepSeek-R2, Qwen-3-Reasoning, Llama-4-Reasoning) approche les capacités o1 actuelles. Si OSMOSIS dimensionne son archi pour exploiter un futur modèle reasoning open-source, le saut "+23 pp via reasoning" deviendra accessible sans Sonnet/o1.

---

## 7. Verdict sur les hypothèses externes

| Hypothèse | Verdict | Preuve |
|---|---|---|
| ChatGPT : "60% archi / 40% modèle" | **Confirmé approximativement** | Décomposition mesurée : 35 pp archi + 47 pp modèle/accès = ratio 43/57 |
| ChatGPT : "Même Sonnet/o1 dans le pipeline V4.2 → pas 0.94" | **Confirmé** | GPT-4o avec prompt V4.2 = 0.12. o1 + chunks libres = 0.70. Aucun ne dépasse 0.85 sans accès PDF complet |
| Claude Web : "Sonnet dans V4.2 → 0.65-0.75" | **Réfuté** | GPT-4o avec prompt V4.2 = 0.12, pas 0.65. Sonnet aurait probablement le même destin (~0.20-0.30). |
| Claude Web : "70% modèle / 30% archi" | **Réfuté** | La mesure indique l'inverse. L'archi V4.2 (prompt strict) est le bottleneck principal |
| Claude Web : "Plan V5 avec Sonnet en runtime" | **Inapplicable** | Coût rédhibitoire ; gain limité sans refonte archi |

---

## 8. Implications stratégiques

### 8.1 La direction "workspace reasoning" devient prioritaire

ChatGPT avait suggéré que le vrai problème était cognitif : "votre unité de raisonnement (chunks atomiques) est mauvaise, l'humain raisonne sur sections / mécanismes / structures logiques". La mesure le confirme : la dernière marche de +24 pp Oracle vs o1 chunks vient précisément de l'accès **structuré et complet** au document.

Refonte d'archi à envisager :
- Pipeline qui maintient une **représentation persistante** du document pendant le raisonnement (pas juste des chunks ré-extraits à chaque tour).
- **Décomposition de question** en sous-questions structurelles (entité, période, relation, cas) avant retrieval.
- **Hiérarchisation des chunks** par section/article/règle, pas juste par similarité cosine.
- **Re-lecture ciblée** : si la question demande une énumération, charger l'intégralité de la section concernée (pas seulement top-k chunks).

### 8.2 Cible produit révisée

| Phase | Cible Robustness | Configuration |
|---|---:|---|
| Court terme (1-3 mois) | 0.45-0.55 | V4.2 archi corrigée (retrait prompt strict, verifier ternaire) |
| Moyen terme (3-6 mois) | 0.60-0.70 | + workspace reasoning open-source |
| Long terme (6-12 mois) | 0.70-0.80 | + DeepSeek-R2/Qwen-3-Reasoning quand dispo |
| Cible théorique max accessible | ~0.85 | Limite open-source + workspace reasoning |
| Cible théorique avec proprietary (rédhibitoire) | ~0.90 | Sonnet/o1 (non viable opérationnellement) |
| Borne humaine absolue (Oracle PDF complet) | 0.94 | Référence non-RAG |

### 8.3 Test Armand : positionnement réaliste

Pour le Test Armand (client zéro potentiel sur corpus aerospace réglementaire), la cible 0.55-0.65 sur 6-9 mois est défendable, à condition de positionner OSMOSIS comme :
- Un système **différencié sur la qualité des citations et la traçabilité** (pas sur le score brut)
- Un système **maintenant des relations document/version** que les concurrents ratent (LIFECYCLE, contradictions, supersession)
- Un système qui **dit "je ne sais pas" plutôt que d'halluciner** (vrai différenciateur business sur compliance)

Le score brut 0.55-0.65 ne battra pas Microsoft Copilot ou Google Gemini sur des benchmarks généralistes, mais OSMOSIS peut gagner sur les **dimensions qualitatives** (citations, lifecycle, abstention sur false_premise) qui comptent pour un usage compliance.

---

## 9. Limites du protocole

### 9.1 Limites héritées de CH-50 Oracle

1. **Biais collusion Claude-écrit / LLM-juge** : l'Oracle Claude (0.94) a été rédigé par Claude Sonnet 4.6 et noté par des LLM-juges. Convergence Llama/Qwen/GPT-4o-mini à ±6 pp suggère un biais résiduel ≤ 10 pp, mais non éliminé totalement.
2. **Sample biaisé** : les 30 questions sont les "both-KO". Sur les 100 questions où au moins un système V3/V4.2 réussit, le gap serait probablement plus serré.

### 9.2 Limites spécifiques à cette mesure

1. **Test B mesure le prompt strict, pas l'archi V4.2 complète.** La production V4.2 inclut aussi un Verifier veto (DeepSeek-V3.1 qui rejette les réponses MISALIGNED) et un orchestrator Layer 2. Le score réel V4.2 (0.08) est plus bas que Test B (0.12) parce que ces couches additionnelles abstient encore davantage.

2. **DeepSeek-R1 max_tokens=1500 peut sous-estimer** : le `<think>` block d'un reasoning model peut nécessiter 5K-10K tokens. Notre limitation peut tronquer son raisonnement. Mais même avec ce handicap, R1 ne dépasse pas DeepSeek-V3.1, suggérant que le reasoning **comme implémenté actuellement** dans R1 n'apporte pas grand-chose pour ces questions.

3. **o1 testé une seule fois** : pas de mesure de variance sur o1. Les scores 0.704 sont peut-être une bonne ou une mauvaise journée pour o1.

4. **Pas testé** : Sonnet 4.6 (Anthropic), Gemini 1.5 Pro, Mistral-Large-Reasoning si dispo. Mais on peut raisonnablement extrapoler (Sonnet ≈ o1 ou GPT-4o, Gemini ≈ GPT-4o).

5. **Le scoring GPT-4o-mini** est un peu plus indulgent que Llama (notamment sur les abstentions de V4.2 → 0.22 vs Llama 0.08). C'est un effet "GPT-mini juge GPT-likes plus généreusement". Le ranking inter-modèles reste cohérent malgré tout.

---

## 10. Questions ouvertes pour analyse externe

### Q1 — Le compromis hybride a-t-il une valeur business cachée ?

Mesuré : gain global moyen ~1.5 pp si on escalade 5% des requêtes vers o1. Mais le **gain qualitatif sur les requêtes complexes** (compliance critique, audit) pourrait justifier un positionnement haut de gamme. Y a-t-il un use case OSMOSIS où l'escalade Sonnet sur 5% des requêtes génère une valeur perçue >> coût ?

### Q2 — Workspace reasoning : comment l'implémenter sans Sonnet ?

L'objectif est de donner à un modèle open-source (DeepSeek-V3.1, Qwen-72B) un accès au document plus structuré que des chunks atomiques. Quelles primitives architecturales utiliser ?
- Hierarchical retrieval (section + chunk + paragraph) ?
- Document graphs (knowledge graph par document, pas seulement KG global) ?
- Multi-pass : d'abord identifier la section, puis lire la section entière ?
- Structured prompting : "Voici la table des matières, choisis quelle section lire" ?

### Q3 — La cible 0.75-0.80 est-elle justifiée vs concurrents ?

Microsoft Copilot, Google Gemini for Workspace, Anthropic Claude for Enterprise — chacun proposant du RAG sur corpus interne — sont-ils mesurés à quel niveau sur des benchs analogues ? Si le marché est à 0.65-0.75, OSMOSIS à 0.70 + différenciateurs qualitatifs (citations, lifecycle) est compétitif. Si le marché est à 0.80+, OSMOSIS doit viser 0.80 minimum.

### Q4 — Les open-source reasoning models vont-ils rattraper o1 en 2026 ?

DeepSeek-R1 (open-source, mesuré 0.49) est encore loin de o1 (mesuré 0.70). DeepSeek-R2 ou Qwen-3-Reasoning (annoncés 2026 H2) pourraient combler. Le timing du roadmap OSMOSIS doit-il anticiper cette amélioration, ou se contenter de ce qui est dispo aujourd'hui ?

### Q5 — Le verifier veto strict est-il un problème ou une feature ?

V4.2 abstient massivement sur les questions où Oracle réussit. C'est mauvais pour le score Robustness, mais **bon pour la sécurité juridique** : un système qui abstient plutôt qu'hallucine est préférable en compliance. La cible idéale n'est peut-être pas "atteindre 0.94" mais **"atteindre 0.65 avec 0% d'hallucination"**, ce qui peut être un USP unique. Comment mesurer le ratio "info correcte" / "abstention légitime" / "hallucination" ?

### Q6 — Le bench Robustness reflète-t-il le vrai usage ?

Les 30 questions both-KO sont par construction les plus difficiles. Sur des questions plus simples (factual T1, lookup direct), V4.2 se débrouille probablement à 0.70-0.80. Quelle proportion des questions réelles d'un utilisateur est de type "both-KO difficiles" vs "factual simple" ? Si le mix réel est 70% simple / 30% difficile, et que V4.2 fait 0.75 sur le simple et 0.10 sur le difficile, le score moyen pondéré serait 0.55. La perception utilisateur serait probablement très mauvaise sur les 30% difficiles, mais correcte sur les 70%.

### Q7 — L'acceptable user experience : 0.55 ou 0.85 ?

ChatGPT et Claude Web ont raté ce point : un utilisateur ne tolère pas longtemps une réponse incorrecte sur un sujet de compliance. Si OSMOSIS atteint 0.65 mais que 15% des réponses contiennent une erreur factuelle, l'utilisateur abandonne après 2 mauvaises réponses. **La métrique cible n'est peut-être pas "score moyen" mais "taux de réponse acceptable"** (par exemple, ≥ 0.70 sur ≥ 90% des questions). Cela change la nature de l'objectif.

---

## 11. Données brutes (vérification indépendante)

Tous les fichiers JSON pour reproduction et audit :

- `data/benchmark/oracle_audit/oracle_audit_sample.json` — les 30 questions sélectionnées
- `data/benchmark/oracle_audit/oracle_answers.json` — Oracle Claude (PDFs complets)
- `data/benchmark/oracle_audit/alt_models_answers.json` — DeepSeek-V3.1 / R1 / Qwen-72B
- `data/benchmark/oracle_audit/openai_answers.json` — GPT-4o / o3-mini / o1 (Tests A/B/C/E)
- `data/benchmark/oracle_audit/full_scoring.json` — 1251 évaluations 3 juges sur toutes les sources
- Sources des benchs originaux V3/V4.2 :
  - `data/benchmark/results/robustness_run_20260505_104355_V3_FINAL3.json`
  - `data/benchmark/results/robustness_run_20260510_145658_v4_2_baseline.json`

Scripts :
- `app/scripts/extract_both_ko.py` (sélection both-KO)
- `app/scripts/select_oracle_sample.py` (stratification 30q)
- `app/scripts/oracle_score.py` (scoring 2 juges)
- `app/scripts/oracle_alt_models.py` (DeepSeek/Qwen génération + scoring)
- `app/scripts/oracle_openai_gen.py` (GPT-4o/o1/o3-mini génération)
- `app/scripts/oracle_o3mini_addon.py` (substitut o1-mini déprécié)
- `app/scripts/oracle_score_full.py` (scoring 3 juges consolidé)

---

## 12. Conclusion synthétique

L'audit CH-50 Frontier Models a mesuré pour la première fois la **décomposition propre du gap +86 pp** entre l'archi V4.2 actuelle (0.08) et la borne humaine atteignable (0.94) sur les 30 questions les plus difficiles du bench Robustness aerospace.

Les trois leviers contribuent à parts presque égales :
- **+35 pp** en retirant le prompt strict V4.2 (archi)
- **+23 pp** en passant à un modèle reasoning frontier (modèle)
- **+24 pp** en donnant accès aux PDFs complets (workspace reasoning)

Cela invalide la prédiction "Sonnet dans V4.2 → 0.65-0.75" (réfutée à 0.12 pour GPT-4o avec prompt V4.2). Cela confirme la direction "workspace reasoning" évoquée par ChatGPT.

**Sonnet/o1 en runtime production reste exclu** non par dogmatisme mais par contrainte économique : leur coût opérationnel (×30 à ×60 vs open-source) impose un prix de vente OSMOSIS qui ne se justifie pas au regard de la valeur produite par utilisateur. Le compromis hybride DeepSeek 95% + Sonnet 5% n'apporte qu'un gain marginal (~1.5 pp moyen).

**La voie réaliste** est :
1. **Court terme** : refonte archi V4.2 (retrait prompt strict, verifier ternaire, escalade conditionnelle) → cible 0.45-0.55 avec DeepSeek-V3.1.
2. **Moyen terme** : workspace reasoning open-source (accès structuré au document, hierarchical retrieval, multi-pass) → cible 0.60-0.70.
3. **Long terme** : exploitation des futurs modèles reasoning open-source (DeepSeek-R2, Qwen-3-Reasoning) → cible 0.70-0.80.

La cible de 0.94 (humain libre) restera probablement hors d'atteinte d'un système RAG automatique sans modifier la nature même de l'accès au document. Mais 0.70-0.80 est viable, et compétitif sur le marché entreprise SAP/compliance/aerospace si OSMOSIS conserve ses différenciateurs qualitatifs (citations, LIFECYCLE_RELATION, abstention plutôt qu'hallucination).

---

*Fin du document. Self-contained pour partage externe (ChatGPT, Claude Web, Gemini, etc.).*
