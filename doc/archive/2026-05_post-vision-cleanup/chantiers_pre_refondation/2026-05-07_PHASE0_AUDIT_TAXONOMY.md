# Phase 0 — Audit taxonomique 54 fails router (2026-05-07)

**Owner** : S2.A.1.b.0 — décision gate 90% strict ou amendement ADR
**Méthode** : classification manuelle de 54 fails du DeBERTa run 2 sur gold_set_v4 (incluant les 22 fails du LLM zero-shot, mêmes patterns)

## Résultat global

| Catégorie | n | % | Implication |
|-----------|--:|--:|-------------|
| **`linguistic_pattern`** | 18 | **33%** | Attaquable par fine-tune avec données régulatoires ciblées |
| **`intrinsically_ambiguous`** | 19 | **35%** | Multi-label légitime — taxonomie à revoir OU top-2 acceptable |
| **`corpus_dependent`** | 17 | **31%** | **NON tranchable** sans accès au corpus/KG |

**Verdict** : **31% corpus_dependent ≥ 30% (seuil ChatGPT/Claude Web). Le gate 90% strict top-1 pré-retrieval est intrinsèquement non atteignable** sur cette taxonomie. Pivot architectural nécessaire.

## Détail par catégorie

### A. `linguistic_pattern` (18 fails — formulation devrait suffire)

Le modèle se trompe sur des questions où la formulation seule contient l'information du label. Ces cas sont attaquables par fine-tune ciblé.

Patterns dominants :
- **Mots-déclencheurs trompeurs** : « entry into force » → temporal alors que factual ; « février 2023 » → temporal alors que factual identification ; « catégorie » → list alors que factual de description
- **Négations** : « N'EST PAS requis » / « N'EST PAS soumis » → modèle prédit unanswerable au lieu de factual
- **Conditionnels** sans présupposition fausse : « Si transfert intra-Union concerne X… » → modèle prédit false_premise

Exemples :
- `T1_AERO_0004` « Which ED Decision corresponds to the entry into force of CS-25 Amendment 28? » (gold=factual, pred=temporal)
- `T1_AERO_0042` « Quelle catégorie d'équipements 1A006 décrit l'Annex I… » (gold=factual, pred=list)
- `NEG_006` « Selon le règlement 2021/821, qu'est-ce qui N'EST PAS requis… » (gold=factual, pred=unanswerable)
- `COND_007` « Si un dossier de certification CS-25 a été ouvert le 1er février 2024… » (gold=factual, pred=false_premise)

### B. `intrinsically_ambiguous` (19 fails — multi-label légitime)

Sur ces cas, **plusieurs labels sont défendables** selon l'interprétation. Le gold a tranché un seul, mais une autre lecture humaine pourrait choisir un autre type. Top-2 multi-label peut atténuer mais pas résoudre.

Patterns dominants :
- **« Quels X » multi-label list/factual** : « Quels CS-25 paragraphes mentionne CS-25 Amendment 28… » — la sortie est une liste mais le gold a tagué factual (volonté d'isoler la réponse)
- **Yes/No multi-label factual/temporal** : « Le règlement 428/2009 est-il toujours en vigueur ? » — yes/no = factual mais la réponse implique SUPERSESSION = temporal
- **Hypothétiques** : « Si CS-25 Amendment 28 était abrogé demain, quelle serait la version applicable ? » — peut être causal (raisonnement conditionnel) ou factual (lookup version)
- **Conditionnels métiers** : « Un avocat doit défendre la position d'un exportateur ayant exporté en 2020… » — gold=list (énumération arguments), aurait pu être causal ou temporal

Exemples :
- `T1_AERO_0029` « Which CS-25 paragraphs were amended via NPA 2014-02? » (gold=factual, pred=list — défendable)
- `T7_AERO_0006` « Le règlement 428/2009 est-il toujours en vigueur ? » (gold=temporal, pred=factual — yes/no)
- `HYP_002` « Si CS-25 Amendment 28 était abrogé demain… » (gold=causal, pred=false_premise)
- `MH_001` « Si une entreprise basée en France exporte vers le Japon… » (gold=list, pred=false_premise)

### C. `corpus_dependent` (17 fails — label nécessite le corpus)

**Le label ne peut PAS être déduit de la question seule.** Il dépend de signaux du KG ou du corpus. Aucun classifier pré-retrieval ne peut atteindre 100% sur ces cas.

Sous-types :

**C.1 `comparison émergent du KG`** (cas emblématique T2_AERO_0001) — 4 cas
- T2_0001 « Quelle est l'énergie d'impact spécifiée par CS-25 pour l'essai d'impact unique… »
  - Gold = `comparison` parce qu'il y a une SUPERSESSION 21J vs 3.5J dans le KG
  - La question seule = factual évident
- T2_0003, T2_0004, T2_0038 — patterns `kg_over_nuance_not_conflict` / `kg_over_apparent_tension` / `kg_over_complementary`

**C.2 `unanswerable réel` (info hors corpus)** — 4 cas
- UNA_004 « Quel est le nom du commissaire européen ayant signé le règlement délégué 2024/2547 ? » — la question est factual en forme, gold=unanswerable parce que l'info n'est pas dans le corpus tenant
- UNA_011, UNA_003, UNA_007 — patterns identiques

**C.3 `false_premise réel` (vérification corpus)** — 3 cas
- FP_009 « Pourquoi le règlement 2021/821 requiert-il l'unanimité du Conseil… ? » — la question est causal en forme, gold=false_premise parce que « unanimité » est factuellement faux selon le corpus
- FP_002, FP_007 — patterns identiques

**C.4 `meta-KG questions` (sur la structure du KG)** — 6 cas
- T7_0046 « Combien de SUPERSEDES sont matérialisées dans le KG aerospace ? » — meta-question
- T7_0032 « Existe-t-il une chaîne complète de SUPERSEDES dans le corpus aerospace ? »
- T7_0047, T7_0033, T7_0044 — patterns `LIFECYCLE_RELATION` / `EVOLVES_FROM` qui dépendent de l'introspection KG
- T6_SYN_007 « Donne une vue d'ensemble des LIFECYCLE_RELATION dans le KG… »

## Implications architecturales

### Implication 1 — Confirmation pivot taxonomie ChatGPT

Les 17 cas `corpus_dependent` (31%) prouvent empiriquement le point théorique de ChatGPT :
> « certains labels ne sont pas déductibles de la question seule »

C'est un **plafond épistémique structurel**. Aucun fine-tune, peu importe son volume, ne peut résoudre ces 17 cas avec un classifier pré-retrieval pur.

### Implication 2 — Gate 90% strict non atteignable

Sur 122 questions structurelles du gold_set_v4 :
- 17 sont corpus_dependent → max 122-17 = 105 questions tranchables pré-retrieval
- Plafond mécanique = 105/122 = **86%**, jamais 90%

Sauf à recompter les 17 cas comme « hors-scope du router pré-retrieval » via la refonte taxonomie en 2 axes.

### Implication 3 — La refonte taxonomie résoud structurellement le problème

| Décision | Décidable depuis la question | Tranchable post-retrieval |
|----------|:---:|:---:|
| `answer_shape` ∈ {scalar/factual, list, temporal, comparison_explicit, causal} | ✅ | — |
| `epistemic_status` partiel | partiel | ✅ |
| Promotion `comparison émergent` | ❌ | ✅ via `EvidenceRerouter` |
| Promotion `unanswerable réel` | ❌ | ✅ via `evidence.answerability_hint` |
| Promotion `false_premise vrai` | ❌ | ✅ via `premise_validator` |
| Décision sur `meta-KG questions` | ❌ | ✅ via classifier dédié post-retrieval |

Le **`EvidenceRerouter`** (CH-42.3 déjà livré) est la bonne brique pour gérer C.1, C.2, C.3, C.4.

## Décision recommandée

**Amender l'ADR S2** :

> Gate révisé : 90% top-1 sur `answer_shape` (5 classes pré-retrieval) + 90%+ effective sur la décision finale grâce au routing distribué (rerouter post-retrieval).

Justification empirique :
- 31% des fails actuels sont `corpus_dependent` → non tranchables pré-retrieval par construction
- L'architecture V4 a déjà la brique post-retrieval (`EvidenceRerouter` CH-42.3)
- Pivot conceptuel aligné avec l'état de l'art (modular RAG, adaptive routing, evidence-conditioned reasoning)

Bénéfices :
- Gate atteignable techniquement et honnêtement
- Architecture plus solide que classifier monolithique
- Latence préservée (router rapide pré-retrieval, rerouter sur les signaux KG déjà collectés)

## Plan de re-tag gold_set_v4

À faire avant Phase 1 (SetFit baseline) :
- Ajouter champ `gold_answer_shape` ∈ {scalar, list, temporal, comparison, causal}
- Ajouter champ `gold_epistemic_status` ∈ {answerable, unanswerable, false_premise}
- Ajouter champ `gold_corpus_signal_required` ∈ {none, contradiction, supersession, missing_info, premise_check, kg_meta}
- Garder `primary_type` pour rétro-compatibilité

Pour les 132q du gold_set_v4, je peux faire ce re-tag automatiquement à partir des stratum existants (stratum révèle souvent la catégorie) + spot-check.

---

**Conclusion** : Phase 0 confirme que ChatGPT et Claude Web ont raison. **Pivoter vers la refonte taxonomie en 2 axes est la bonne décision technique**. Probabilité d'atteindre le gate révisé (90% sur answer_shape + 90%+ effective) = ~85-90%. Probabilité de l'ancien gate strict = ≤86% (plafond mécanique).
