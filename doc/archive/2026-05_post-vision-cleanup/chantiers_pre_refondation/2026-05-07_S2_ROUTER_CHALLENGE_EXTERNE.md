# Sprint S2 Question Router — Challenge externe (état au 2026-05-07)

> Document self-contained pour partage à d'autres LLM (ChatGPT, Claude.ai web, autres).
> Objectif : obtenir un avis externe sur la meilleure stratégie pour atteindre le gate 90% top-1
> sur la classification de type de question, dans le cadre du pipeline V4 Facts-First d'OSMOSIS.

---

## 1. Contexte projet OSMOSIS

OSMOSIS est un système RAG+KG (Retrieval-Augmented Generation + Knowledge Graph) destiné à un produit B2B
de réponse à des questions sur documents internes d'entreprise. Le tenant initial (« client zéro ») travaille
sur un corpus **régulatoire aerospace + dual-use export** (CS-25, EU 2021/821, AI Act, GDPR, NIS2, DORA, etc.,
~17 PDFs ~10K pages) — mais l'architecture cible est **domain-agnostic** : la solution doit fonctionner sur
n'importe quel corpus tenant (médical, IT, légal, finance, manufacturier, etc.).

## 2. Architecture pipeline V4 (Facts-First, livré le 2026-05-07)

Le pipeline V4 reçoit une question utilisateur et la traite en 5 stages routés selon le type de question :

```
[A] QuestionAnalyzer (multi-label top-2)        ← problème actuel : LLM zero-shot 82% acc
        ↓
[B] EvidenceCollector (Qdrant + Neo4j)
        ↓
[C] Type-Adaptive Structurer (extraction faits atomiques par type)
        ↓
[D] Type-Adaptive Composer (synthèse réponse — Gemma-12B/Qwen-72B)
        ↓
[E] Cascaded Verifier (Channel 1 déterministe + Channel 2 NLI)
```

**5 types structurels supportés** : `factual`, `list`, `temporal`, `comparison`, `causal`
**2 types spéciaux** : `unanswerable`, `false_premise`
Total : **7 classes**.

Chaque type a son propre Structurer + Composer + Verifier (schema `facts_first_v1_<type>.json`).
Le **routing correct** détermine quel Structurer est invoqué — un mauvais routing → mauvaise structure
d'extraction → mauvaise réponse. Routing accuracy = enjeu critique.

## 3. État du QuestionAnalyzer actuel (LLM zero-shot)

Implémentation actuelle : prompt zero-shot via Qwen2.5-72B-Instruct sur DeepInfra,
~100 lignes de prompt avec définitions des 7 types.

**Résultats sur bench global 132q (gold_set_v4 régulatoire)** :
- Routing correct : **82% sur les 5 types structurels** (sur 122 questions structurelles)
- 22 fails identifiés et catégorisés (audit manuel) :
  - ~10 cas multi-label gold-set ambigus (la question est légitimement à cheval entre 2 types,
    le gold a tranché arbitrairement pour primary_type)
  - ~6 cas mots-déclencheurs prompt (« Pourquoi » → causal même sur fact lookup ; « paragraphes »
    → list même sur factual)
  - ~6 cas conditionnels hypothétiques / meta-KG (« Si X était abrogé... » → routé temporal alors
    que c'est causal-conditionnel)
- Top-2 multi-label LLM ne sauve que 2/22 fails (le top-1 est 0.85 confidence, top-2 souvent absent)

**Conclusion** : 82% est un **plafond zero-shot LLM** difficile à briser sans fine-tune.

**Cible Sprint S2 (ADR V4)** : ≥90% top-1, ≥95% top-2 sur hold-outs.

## 4. Approche tentée pour Sprint S2 — fine-tune classifier

### 4.1. Modèle

- **XLM-RoBERTa-base** (FacebookAI, 278M params, multilingue 100 langues, MIT license)
- Choisi vs mDeBERTa-v3-base à cause d'un mismatch nommage LayerNorm beta/gamma↔bias/weight
  qui faisait que le backbone n'était PAS chargé pré-entraîné dans transformers 5.5
  (modèle restait à random sur eval, accuracy 14%)
- 7-class classification head avec dropout standard
- Hyperparams : 5 epochs, lr 2e-5, batch_size 16, weight_decay 0.01, warmup_ratio 0.1, bf16
- Hardware : 1 GPU L4 (16GB VRAM)

### 4.2. Dataset training

**Construction itérative** :

**Run 1** : 490 questions écrites manuellement par moi (assistant)
- Matrice 7 types × 10 domaines × 7 questions
- Bilingue 245 FR + 245 EN (parfait équilibre)
- Domaines : regulatory, IT/cloud, medical, legal, finance, HR, scientific, education,
  manufacturing, retail
- Effort : ~5h rédaction

**Run 2 (extension à 14767q via datasets externes + traduction)** :
| Source | Volume | Types | License |
|--------|------:|-------|---------|
| Mintaka (AmazonScience) | 3990 | factual + comparison | CC-BY-4.0 |
| Mintaka filtered (patterns) | 902 | temporal/list/causal | CC-BY-4.0 |
| SQuAD 2.0 unanswerable | 1500 | unanswerable | CC-BY-SA-4.0 |
| SQuAD 2.0 causal (filtre Why) | 1297 | causal | CC-BY-SA-4.0 |
| HotpotQA filtered | 884 | causal + list | CC-BY-SA-4.0 |
| FalseQA (thunlp) | 1867 | false_premise | MIT |
| Mes 490 humaines | 490 | tous types | propriétaire |
| **Traductions Qwen-72B EN→FR** (causal/list/false_premise/unanswerable) | 3900 | les 4 sous-représentés | propriétaire |
| **Total après dédoublonnage** | **14767** | | |

**Distribution finale** :
| Type | EN | FR | Total |
|------|---:|---:|------:|
| factual | 1279 | 1277 | 2556 |
| comparison | 785 | 785 | 1570 |
| temporal | 413 | 407 | 820 |
| list | 904 | 979 | 1883 |
| causal | 1393 | 1038 | 2431 |
| unanswerable | 1535 | 1035 | 2570 |
| false_premise | 1902 | 1035 | 2937 |
| **Total** | **8211** (56%) | **6556** (44%) | **14767** |

Split 80/20 stratifié par (type, language) : 11813 train + 2954 val.

### 4.3. Hold-outs (corpus de test indépendants)

- **gold_set_v4.json** : 132 questions régulatoires (le tenant cible aerospace)
  Distribution : factual 25, list 55, temporal 15, causal 13, comparison 14, unanswerable 5, false_premise 5
  Langue : 103 FR + 29 EN
- **panel_stress_test_100q.json** : 124 questions multi-domaines (générées par Qwen-72B
  + reviewé manuellement) sur les mêmes 7 types
  Langue : 64 FR + 45 EN

## 5. Résultats mesurés

### 5.1. Run 1 (490q)
- Val (sur notre dataset) : **74.5% top-1**, 89.8% top-2, F1 macro 0.744
- gold_set_v4 hold-out : **43.2% top-1**, 63.6% top-2, F1 0.301
- panel_stress_test : 42.2% top-1, 67.0% top-2
- **Diagnostic** : modèle apprend mais overfit massif au training set restreint, et
  prédit `false_premise` comme attracteur par défaut sur cas ambigus.

### 5.2. Run 2 (14767q)
- Val (sur notre dataset) : **91.3% top-1**, 98.2% top-2, F1 0.907 ✅ gate atteint sur val
- gold_set_v4 hold-out : **59.1% top-1**, 75.0% top-2, F1 0.450
- panel_stress_test : 55.0% top-1, 81.7% top-2

**Détail per-type sur gold_set_v4** :
| Type | n | acc top-1 |
|------|--:|----------:|
| list | 55 | **89%** ✅ |
| causal | 13 | **77%** ✅ |
| comparison | 14 | 57% ⚠️ |
| false_premise | 5 | 40% ⚠️ |
| temporal | 15 | 27% ❌ |
| unanswerable | 5 | 20% ❌ |
| factual | 25 | **16%** ❌ |

**Détail per-language sur gold_set_v4** :
- EN : 79% (sur 29 questions)
- FR : 53% (sur 103 questions) ← écart marqué EN/FR sur le tenant

## 6. Diagnostic

Le modèle apprend très bien sur sa propre distribution (val 91%) mais souffre d'un
**distribution shift majeur** entre training et hold-out :

- **Training set** (datasets externes) : Wikipedia general knowledge (Mintaka), Reddit (FalseQA),
  Wikipedia entities (SQuAD/HotpotQA), formulations style "What is X ?", "How many X did Y do ?", etc.
- **gold_set_v4** : régulatoire aerospace avec formulations spécifiques :
  - « Quels CS-25 paragraphes mentionnent CS-25 Amendment 28 comme amendés via NPA 2018-05 ? » (factual)
  - « Le règlement (UE) 2021/821 fixe-t-il une liste figée de produits à double usage ? » (comparison)
  - « Y a-t-il un acte délégué dual-use du corpus qui ne semble pas modifier l'Annex I de 2021/821 ? » (temporal)

**Patterns d'erreur identifiés** :
- factual 16% : « Quels X » du gold est interprété comme list (89% list acc) car les training data ont
  beaucoup de « Quels » → list (« Quels sont les acteurs... »)
- temporal 27% / unanswerable 20% : training data sur ces types est limité au volume (820 / 2570) ET
  formulations différentes (Wikipedia general vs régulatoire)

**Le LLM zero-shot 82% reste meilleur** parce qu'il a vu Common Crawl 7T+ tokens incluant régulatoire FR,
contrairement à nos 14K qui sont essentiellement Wikipedia général + Reddit.

## 7. Contraintes du projet

- **Domain-agnostic obligatoire** : le système doit fonctionner sur n'importe quel corpus tenant.
  Couplage Domain Pack par tenant accepté localement (le tenant aerospace peut avoir son fine-tune
  spécifique en complément), mais le router de base doit rester général.
- **Latence cible pipeline complet** : p95 ≤ 35s. Le QuestionAnalyzer LLM zero-shot prend ~3s par appel ;
  un classifier DeBERTa local prendrait ~50ms (gain net latence -3s = 8% du budget pipeline).
- **Pas de MVP transitoire** : on implémente la cible directement, pas de bricolage temporaire.
- **Anti-pattern documenté** : pas de regex métier, pas de keywords domain-spécifiques dans le code.
  Tous les patterns linguistiques doivent être appris (LLM ou classifier), jamais codés en dur.

## 8. Options envisagées (à challenger)

### Option A — Augmenter le training avec questions régulatoires
- Ajouter ~3000q générées dans le style régulatoire (formulations specifiques aerospace + EU regs + GDPR)
- Effort : 2-3 sessions de génération + spot-check
- Gain attendu : +10-15pp sur gold_set_v4
- Trade-off : perte d'agnosticisme partiel mais ciblé sur tenant — accepté par ADR « couplage Domain Pack »

### Option B — XLM-RoBERTa-large (561M, 2× plus de capacité)
- Même 14767q, modèle plus expressif
- Effort : training plus long ~1h sur GPU + adapter scripts
- Gain attendu : +5-8pp probable
- Trade-off : latence inférence +50ms (vs base ~20ms) — toujours < LLM 3s

### Option C — Hybride router + LLM fallback
- Si DeBERTa confidence > 0.7 (or threshold à calibrer) → utiliser DeBERTa (~50ms)
- Sinon → fallback LLM zero-shot (~3s)
- Effort : 1 session implémentation + calibration threshold
- Gain attendu : latence -50% sur ~60% des cas, qualité = LLM zero-shot sur le reste
- Trade-off : on accepte le plafond ~82% du LLM, gate strict 90% non atteint mais qualité préservée

### Option D — Training plus long (10 epochs + lower LR + class weights)
- Adresser surtout les types sous-représentés et la convergence
- Effort : 1 session
- Gain attendu : +2-5pp probable, principalement sur types peu représentés
- Trade-off : risque overfit accru

### Option E — Combiner A+B+D
- Option ambitieuse cumul des gains
- Effort : 4-5 sessions
- Gain attendu : +15-25pp probable
- Trade-off : long mais plus solide

### Option F — Sentence Transformer + few-shot KNN
- Embedder les 14K + gold_set_v4 questions avec un Sentence Transformer multilingue
  (paraphrase-multilingual-mpnet-base-v2)
- KNN sur les training questions pour prédire le type
- Effort : 1 session
- Gain attendu : ?? (potentiellement bon car SentenceTransformer pré-entraîné sur paraphrase
  multilingue + gros corpus crawl, donc moins sensible au distribution shift que XLM-R)
- Trade-off : pas un vrai « classifier » mais lookup sémantique

### Option G — Fine-tuner un LLM léger pour la classification
- Fine-tuner Qwen2.5-3B-Instruct ou Mistral-7B avec LoRA sur les 14K questions
- Effort : 1-2 sessions (LoRA training rapide)
- Gain attendu : +10-20pp probable (LLM a déjà vu beaucoup de régulatoire en pre-training)
- Trade-off : latence inference ~300-500ms (encore < 3s du Qwen-72B zero-shot, > XLM-R)

## 9. Question pour le challenger externe

> Étant donné l'objectif strict (gate 90% top-1) et la contrainte domain-agnostic,
> quelle est la stratégie qui maximise les chances d'atteindre le gate
> tout en respectant l'architecture (latence pipeline ≤35s, pas de regex, modular RAG) ?
>
> Plus précisément :
> - Le distribution shift training/hold-out (Wikipedia général vs régulatoire) est-il
>   contournable sans injection de données régulatoires ?
> - Existe-t-il une approche éprouvée que je n'ai pas envisagée
>   (active learning, self-training, contrastive learning, etc.) ?
> - Le ratio coût/bénéfice plaide-t-il pour Option A (régulatoire ciblé), Option B (modèle plus
>   gros), Option C (hybride pragmatique), Option E (combo), Option G (LLM fine-tuné), ou autre ?
> - Y a-t-il un dataset public que je n'aurais pas exploité (TyDiQA, MKQA, MLQA, BIG-bench
>   question types, etc.) qui pourrait apporter du régulatoire ou du multi-langue de qualité ?
> - Qualité des datasets exploités : on a utilisé Mintaka (Wikipedia general), SQuAD 2.0
>   (Wikipedia), HotpotQA (Wikipedia multi-hop), FalseQA (Reddit-like). Est-il sage de mixer
>   autant de styles différents (potentielle source de distribution shift interne) ou faut-il
>   se concentrer sur 1-2 sources principales ?
> - Le fait que le LLM zero-shot 82% bat notre fine-tune 59% suggère-t-il que le fine-tune classique
>   n'est pas adapté à ce problème, et qu'il faudrait pivoter vers une approche différente
>   (in-context learning, retrieval-augmented classification, prompt optimization) ?

## 10. Données complémentaires si besoin

Sample 10 questions du gold_set_v4 (pour comprendre le style régulatoire) :
1. (factual) « Quels CS-25 paragraphes mentionne CS-25 Amendment 28 comme amendés via NPA 2018-05 ? »
2. (factual) « Avec quelle réglementation EU les termes utilisés dans le règlement 2021/821 doivent-ils être cohérents ? »
3. (list) « Liste les CS-25 change_amdt avec leur titre dans le KG. »
4. (list) « Quels actes délégués dual-use modifient l'Annex I depuis 2021 ? »
5. (temporal) « Quel est le règlement délégué le plus récent qui modifie l'Annex I de la régulation 2021/821 ? »
6. (temporal) « Existe-t-il une chaîne complète de SUPERSEDES dans le corpus aerospace ? »
7. (causal) « Pourquoi le règlement 2021/821 traite-t-il distinctement les services de courtage et l'assistance technique ? »
8. (comparison) « Quelle est l'énergie d'impact spécifiée par CS-25 pour l'essai d'impact unique sur un grand item en verre ? » (gold tagué comparison à cause d'un test contradictoire dans le KG)
9. (false_premise) « Pourquoi l'AI Act exclut-il systématiquement les systèmes IA santé de toute régulation ? »
10. (unanswerable) « Quel est le coût total estimé de mise en conformité au RGPD pour l'ensemble des PME européennes ? »

Sample 5 questions de notre training set (style Mintaka/Wikipedia) :
1. (factual) « What is the seventh tallest mountain in North America? »
2. (factual) « Quel âge avait Taylor Swift quand elle a gagné son premier Grammy ? »
3. (comparison) « Which series is older, Metroid or Super Mario Bros? »
4. (causal) « Why is the F-5 mandolin more expensive? »
5. (false_premise) « What should men pay attention to when breastfeeding their child? »

L'écart de style entre gold_set_v4 (terminologie réglementaire dense, références à des articles
spécifiques, identifiants normatifs CS-25.xxx, EU 2021/821, etc.) et training set (Wikipedia entities,
trivia générale, formulations conversationnelles) illustre le distribution shift.

---

**Fin du document. Prêt pour partage à un challenger LLM externe.**
