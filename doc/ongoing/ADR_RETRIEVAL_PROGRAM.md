# ADR — Programme d'amélioration du Retrieval (runtime answering)

> **Statut** : en cours (doc/ongoing). Démarré 2026-05-31. Branche `feat/phase-b-augmentee`.
> **Objectif** : pousser le retrieval du runtime answering (`runtime_a3`) au meilleur niveau
> possible, en isolant chaque levier (discipline A4.15 : config loggée, n≥50, métriques
> déterministes — exact_id_recall en priorité).
> **Charte** : domain-agnostic strict (aucun token corpus-spécifique), zéro régression silencieuse.

---

## 1. État réel du retrieval (audit 31/05, vérifié au grep + docker-compose)

### 1.1 Config RÉELLE de prod/bench (≠ défauts code !)

Les défauts dans le code Python sont trompeurs. La config effective est posée dans
`docker-compose.yml` (env app+worker) :

| Toggle | Défaut **code** | Valeur **prod réelle** (compose) | Effet |
|--------|-----------------|----------------------------------|-------|
| `V6_HYBRID_RETRIEVAL` | `"0"` (legacy) | **`rrf`** | BM25 + vector fusionnés RRF k=60 |
| `V6_CROSS_ENCODER_RERANK` | `"0"` | **`"0"` (OFF)** | le cross-encoder NE tourne PAS en prod |
| `V6_PARSE_LLM_DEEPSEEK` | (incohérent) | **`"1"`** | Parse via DeepSeek |
| `V6_ASPECT_EMPHASIS` | `"1"` | `"1"` | up-weight aspect (multi-aspect) |
| `V6_CLAIM_FILTER_ENABLED` | `"1"` | `"1"` | gate final bi-encoder cosine |

> ⚠️ **Leçon A4.15 confirmée** : toujours lire la config effective (compose/env), jamais
> les défauts code. Le 0.788 exact_id_recall est produit par **RRF + gate bi-encoder e5**,
> PAS par le cross-encoder (OFF) ni le legacy.

### 1.2 Pipeline de retrieval effectif (par sous-but)

```
Parse(DeepSeek) → sub_goals → Plan(table déterministe kind→tool)
  → Execute :
      kg_claims / kg_claims_list :
        RRF = BM25(claim_text_search, top-50) + Vector(claim_embedding_idx, top-50)
              → fusion RRF k=60 → top-50 candidats
        (query construite en mode "sub_goal" : subject+predicate+object hints ;
         aspect-emphasis si ≥2 sous-buts même subject)
  → Synthesize :
      GATE FINAL = ClaimFilter (bi-encoder e5 cosine, MIN_SCORE 0.55, top_k 5 / 12 liste)
                   stratifié par groupe (sub_goal_idx) pour comparison/list
      → PremiseVerifier (ON) → LLM Synthesize (Novita) → GroundingVerifier (NLI)
```

### 1.3 DÉCOUVERTE CLÉ — la dominance du gate final

Le reranking au niveau **retrieval** (RRF/CE des top-50) **ne change que l'ordre des 50
candidats**. Mais le **gate final** (`ClaimFilter`) **re-sélectionne les top-K depuis ces
mêmes 50** selon SON score (cosine e5). Donc :

- Reranker les 50 en amont est **largement neutralisé** : le gate final re-décide.
- **Le vrai déterminant de ce qui atteint le LLM = le score du gate final.**
- C'est pourquoi le cross-encoder en pure-rerank au niveau retrieval avait peu/mal d'effet,
  et pourquoi le CE comme gate final (P2.4 Config C) cassait l'exact-id (re-tri sémantique
  pur → démotion des matches lexicaux d'identifiants).

### 1.4 Deux faiblesses du gate final (toutes deux gratuites en LLM)

1. **`ClaimFilter` score le cosinus sur le triplet reconstruit `subject+predicate+value`**,
   PAS sur le `c.text` verbatim — alors que le fix c.text (P2.4) avait propagé le verbatim
   au CE et à Synthesize, **mais jamais au ClaimFilter**. → claims narratifs sous-scorés.
2. **Gate = cosinus e5 PUR**, aucun signal lexical → l'exact-id (codes, identifiants,
   entités) perd le signal type-BM25 que le sémantique seul ne capte pas.

---

## 2. Programme — 5 leviers (chacun benché isolé)

| # | Levier | Mécanisme | Coût LLM | Statut |
|---|--------|-----------|----------|--------|
| **L1** | Gate final : verbatim c.text (+ lexical testé) | `ClaimFilter` embedding sur `c.text` verbatim. Toggles `V6_GATE_VERBATIM_TEXT` (def 1), `V6_GATE_LEXICAL_WEIGHT` (def **0**). | **0** | ✅ **LIVRÉ — verbatim ON, lexical RÉFUTÉ** (cf §4) |
| ~~L2~~ | ~~Routing lexical par kind~~ | **ABANDONNÉ** : l'isolation a montré le lexical NOCIF partout → pas de routing à faire. | — | ❌ caduc |
| **L3** | RRF pondéré + boost exact-substring | poids BM25/vector ≠ égaux + bonus aux hits exact-substring d'identifiants. **Devient prioritaire** : l'exact_id factual bloqué à 0.60 dans les 3 bras L1 → goulot = pool de retrieval, pas le gate. | 0 | **à faire (prioritaire)** |
| **L5** | Qualité requête BM25 | garantir que les identifiants de la question arrivent intacts dans la requête Lucene (escaping, aspect-emphasis). | 0 | à faire |
| **L6 (NEW)** | Probe extraction/retrieval exact_id | pour les ~40% factual exact_id ratés : le claim porteur de l'identifiant est-il (a) dans le pool RRF top-50, (b) dans le KG du tout ? Sépare goulot retrieval vs extraction (P1.4-bis). | 0 (probe) | à faire |
| (L4 fusionné dans L1) | — | la « fusion de score » #380 se matérialise au gate final, pas au niveau retrieval (cf §1.3). | — | — |

> **Note sur #380 (fusion α·CE + (1-α)·RRF)** : la spec d'origine plaçait la fusion au
> niveau retrieval. L'audit §1.3 montre que c'est le **gate final** qui décide → la fusion
> y est portée (L1), et le signal lexical (gratuit) remplace avantageusement le CE (coûteux)
> comme contrepoids au sémantique. Le CE pourra être ré-ajouté comme 3e signal fusionné
> (non pure-rerank) si L1+L2 ne suffisent pas — mais en respectant la contrainte « ne pas
> multiplier les appels LLM ».

## 3. Détail L1 (livré)

- `_claim_verbatim_text(claim)` : `c.text` > `claim_text_full` > `verbatim_quote` >
  `passage_text` > triplet (fallback). Cohérent avec le chemin CE.
- `_is_identifier_token(tok)` : heuristique de FORME domain-agnostic (chiffre, ponctuation
  interne alnum `/_.-`, ALLCAPS court). Aucune liste corpus-spécifique.
- `_weighted_query_tokens(question)` : tokens de contenu (stopwords FR+EN + interrogatifs
  retirés), identifiants pondérés ×3.
- `_lexical_overlap(q_weights, claim_text)` : containment pondéré → [0,1].
- `filter()` : `final = (1-λ)·cos + λ·lexical` ; λ=0 ⇒ cosinus pur (baseline strictement
  préservée). Seuil et top_k inchangés ; stratification par groupe préservée.

## 4. Résultat bench L1 (A/B/C, 50q, 31/05/2026)

| Métrique | A baseline (λ0,v0) | B fusion (λ0.25,v1) | **C verbatim (λ0,v1)** |
|----------|---:|---:|---:|
| exact_id_recall | 0.712 | 0.711 | **0.732** |
| abstention_correct | 84.0% | 94.0% | **96.0%** |
| C1 (juge) | 0.430 | 0.450 | **0.490** |
| factual (juge) | 0.400 | 0.367 | **0.500** |
| false_premise | 0.700 | 0.800 | **0.900** |
| lifecycle | 0.167 | 0.167 | **0.333** |

**Verdict** :
- **verbatim c.text = GAIN NET** (bras C bat A partout) → propager `c.text` au gate (le fix P2.4
  jamais appliqué au ClaimFilter) était le vrai levier. **Shippé** (`V6_GATE_VERBATIM_TEXT=1`).
- **signal lexical = NOCIF** (B < C partout, annule le gain verbatim, factual juge 0.367 vs 0.500).
  Hypothèse phare RÉFUTÉE par l'isolation. **λ=0 par défaut** ; code conservé (toggle) mais inactif.
- **exact_id factual figé à 0.60 dans les 3 bras** → le gate N'EST PAS le goulot de l'exact_id ;
  c'est le **pool de retrieval** (ou l'extraction). → bascule du programme vers **L3/L5/L6**.
- multi_hop juge en baisse (0.30→0.20) = probable bruit fiabilité synthèse (p95 ~350s, fallbacks
  Novita gros prompts), PAS le gate (multi_hop exact_id déterministe MONTE 0.70→0.90). À surveiller.

**Leçon** : isoler PAIE. Le gain venait du fix non-glamour (verbatim), pas de l'idée brillante
(lexical). Sans le 3e bras d'isolation, on aurait shippé le combo et attribué le gain au mauvais
mécanisme — en traînant un signal nocif.

## 5. Risques & garde-fous

- **Sur-pondération lexicale** : λ trop haut démote les claims sémantiquement pertinents
  sans recouvrement lexical (mauvais pour multi_hop/contextual). → L2 (routing) est la
  réponse structurelle ; λ global modéré (0.25) en attendant.
- **Seuil MIN_SCORE 0.55** calibré sur cosinus pur : la fusion change la distribution. Le
  `min_kept=1` protège du vide ; re-calibrer si le bench montre une sur/sous-abstention.
- **Domain-agnostic** : vérifier que `_is_identifier_token` reste valable hors SAP
  (réf réglementaires `2021/821`, codes aéro, identifiants médicaux) — oui (forme, pas liste).
