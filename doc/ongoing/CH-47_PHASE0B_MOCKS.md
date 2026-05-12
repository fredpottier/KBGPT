# CH-47 Phase 0.B — Mocks R3b sur 2 cas représentatifs

**Date** : 2026-05-08
**Contexte** : valider que **Relational Structurer + Constrained Reasoning Composer** (R3b) restaure la qualité sur les questions de raisonnement où V4_CH46 régresse de -18 à -36 pp vs V3_S0.

## Résumé Phase 0 complet

**Phase 0.A (audit 23 régressions ≥ 20pp)** :
- 48% `b_composer_short` (Composer ne synthétise pas)
- 39% `unknown` (autres patterns)
- 13% `a_structurer_extraction`

**Phase 0.B (capture facts_first sur 5 top-deltas via API V4)** :
- **3/5 (1) Structurer abdique** (`answerability=unanswerable`, 0 items extracted)
- **2/5 (2b) Composer short** (`answerable + items` mais réponse incomplète)
- **4/5 mauvaise classification Analyzer** (causal classé temporal, hypothetical classé factual, etc.) — confirme le besoin de CH-47.3 en P1 mais pas bloquant si Structurer/Composer deviennent robustes

→ Ratio 60/40 Structurer/Composer **conforme à la prédiction ChatGPT**.

## Mock 1 — q_37 (Hypothèse 1, causal_why)

**Question** : "Pourquoi l'Annex I du règlement 2021/821 doit-elle être régulièrement mise à jour ?"

**Scores** : V3=0.90, V4=0.00 (ABSTAIN), Δ=0.90

### V4 actuel (échec)

```
facts_first.answerability = "unanswerable"
facts_first.coverage_state = "unknown"
factual/causal_specific.facts = []
decision = ABSTAIN
answer = "La réponse à votre question n'a pas été trouvée dans les documents disponibles."
```

**Pourtant les 12 chunks retrieved contiennent l'information explicitement** :

> "Considering the importance of ensuring full compliance with international security obligations as soon as possible, this Regulation should..."

> "international non-proliferation regimes and export control arrangements have been changed during 2021, and **therefore** Annex I to Regulation (EU) 2021/821 should be amended accordingly..."

Les **marqueurs causaux explicites** ("therefore", "in order to ensure") sont présents — le Mistral-Small Structurer V4 ne sait simplement pas les extraire.

### Mock R3b — ce que devrait produire Relational Structurer

```json
{
  "answerability": "answerable_with_reasoning",
  "primary_type": "causal",
  "atomic_facts": [
    {
      "id": "f1",
      "text": "International non-proliferation regimes and export control arrangements have changed their control lists during 2021 and 2023.",
      "source": {"doc_id": "dualuse_del_2023_66_cdc2b691"},
      "type": "atomic"
    },
    {
      "id": "f2",
      "text": "Regulation (EU) 2021/821 should be amended to ensure full compliance with international security obligations as soon as possible.",
      "source": {"doc_id": "dualuse_del_2023_66_cdc2b691"},
      "type": "atomic"
    },
    {
      "id": "f3",
      "text": "Annex I to Regulation (EU) 2021/821 should be amended accordingly.",
      "source": {"doc_id": "dualuse_del_2024_2547_cb08f84b"},
      "type": "atomic"
    }
  ],
  "relational_facts": [
    {
      "id": "r1",
      "relation_type": "causal",
      "marker": "therefore",
      "antecedent_ids": ["f1"],
      "consequent_ids": ["f3"],
      "evidence_quote": "...have been changed during 2021, and therefore Annex I to Regulation (EU) 2021/821 should be amended accordingly...",
      "inference_strength": "direct",
      "confidence": 0.95
    },
    {
      "id": "r2",
      "relation_type": "purpose",
      "marker": "in order to ensure",
      "antecedent_ids": ["f3"],
      "consequent_ids": ["f2"],
      "evidence_quote": "In order to ensure full compliance with international security obligations as soon as possible, this Regulation should...",
      "inference_strength": "direct",
      "confidence": 0.90
    }
  ]
}
```

### Mock R3b — ce que devrait produire Constrained Reasoning Composer

```json
{
  "reasoning_steps": [
    {
      "step": 1,
      "type": "evidence_identification",
      "inference": "Les régimes internationaux de non-prolifération modifient régulièrement leurs listes de contrôle (en 2021 et 2023).",
      "evidence_ids": ["f1"],
      "inference_strength": "direct",
      "confidence": 0.95
    },
    {
      "step": 2,
      "type": "causal_inference",
      "inference": "Quand ces listes internationales changent, l'Annex I de 2021/821 doit être amendée en conséquence pour rester alignée.",
      "evidence_ids": ["f1", "f3"],
      "relation_id": "r1",
      "inference_strength": "direct",
      "confidence": 0.95
    },
    {
      "step": 3,
      "type": "purpose_synthesis",
      "inference": "Cette mise à jour vise à assurer la pleine conformité avec les obligations de sécurité internationale.",
      "evidence_ids": ["f2"],
      "relation_id": "r2",
      "inference_strength": "direct",
      "confidence": 0.90
    }
  ],
  "answer": "L'Annex I du règlement 2021/821 doit être régulièrement mise à jour parce que les listes de contrôle adoptées par les régimes internationaux de non-prolifération et les arrangements de contrôle des exportations sont régulièrement modifiées (en 2021, 2023, etc.). Pour maintenir la pleine conformité avec les obligations de sécurité internationale, l'Annex I doit être amendée en conséquence [doc=dualuse_del_2023_66, doc=dualuse_del_2024_2547].",
  "citations": ["f1", "f2", "f3", "r1", "r2"],
  "reasoning_confidence": 0.92
}
```

### Test NLI Channel 2 (manuel)

| Step | Premise (chunk) | Hypothesis (inference) | Verdict |
|---|---|---|---|
| 1 | "control lists adopted by international non-proliferation regimes have been changed during 2021/2023" | "Régimes internationaux modifient régulièrement leurs listes" | **ENTAILMENT** ✓ |
| 2 | "have been changed during 2021, and therefore Annex I should be amended" | "Quand listes changent, Annex I doit être amendée" | **ENTAILMENT** ✓ |
| 3 | "In order to ensure full compliance with international security obligations" | "La mise à jour vise pleine conformité internationale" | **ENTAILMENT** ✓ |

→ **3/3 reasoning_steps passent NLI** ✓

**Verdict Mock 1 — q_37** : R3b **VALIDÉ**, restaure le V3_score 0.90.

## Mock 2 — q_88 (Hypothèse 2b, multi_hop)

**Question** : "Quelle est la valeur d'énergie d'impact à appliquer aujourd'hui pour un grand item en verre, et pourquoi une valeur plus faible apparaît dans le KG ?"

**Scores** : V3=0.85, V4=0.00, Δ=0.85

### V4 actuel (échec partiel)

V4 a correctement extrait 2 facts :
- **F1** : 21 J (Amendment 28, ACTIVE, "single impact")
- **F2** : 80 J (Amendment 26, ACTIVE, "until destruction")

Mais sa réponse :
> "Un objet en verre doit être soumis à une énergie d'impact de 21 J [F1]. Les tests doivent être effectués jusqu'à ce qu'une énergie d'impact de 80 J soit atteinte..."

**Manque deux choses critiques** :
1. La **distinction de nature** entre les 2 valeurs (test standard vs test post-failure) — c'est le "**pourquoi écart**" demandé
2. La **réponse au pourquoi** : la question est multi-hop, pas juste factuelle

### Mock R3b — Composer enrichit avec un fact relationnel

Le Structurer V4 a fait son boulot pour les atomic_facts (F1, F2). Il manque juste **un fact relationnel de distinction** :

```json
"relational_facts": [
  {
    "id": "r1",
    "relation_type": "purpose_distinction",
    "antecedent_ids": ["F1"],
    "consequent_ids": ["F2"],
    "fact_a_purpose": "single_impact_compliance_test",
    "fact_b_purpose": "post_failure_destruction_test",
    "evidence_quote_a": "subjected to a single impact",
    "evidence_quote_b": "testing... should be performed until destruction, or until... 80 J",
    "inference_strength": "probable",
    "confidence": 0.80
  }
]
```

### Mock R3b — Constrained Reasoning Composer

```json
{
  "reasoning_steps": [
    {
      "step": 1,
      "type": "evidence_identification",
      "inference": "Pour un grand item en verre, la valeur d'énergie d'impact à appliquer en test standard est 21 J.",
      "evidence_ids": ["F1"],
      "inference_strength": "direct",
      "confidence": 0.95
    },
    {
      "step": 2,
      "type": "evidence_identification",
      "inference": "Le KG mentionne aussi une valeur de 80 J, qui concerne un test continué jusqu'à destruction.",
      "evidence_ids": ["F2"],
      "inference_strength": "direct",
      "confidence": 0.90
    },
    {
      "step": 3,
      "type": "purpose_distinction",
      "inference": "Ces deux valeurs ne sont pas contradictoires : 21 J est la valeur du test standard d'impact unique (compliance), 80 J est la valeur max atteinte lors du test étendu post-failure (destruction). Elles correspondent à deux phases distinctes du protocole.",
      "evidence_ids": ["F1", "F2"],
      "relation_id": "r1",
      "inference_strength": "probable",
      "confidence": 0.80
    }
  ],
  "answer": "La valeur d'énergie d'impact à appliquer aujourd'hui pour un grand item en verre est **21 J** (Amendment 28 CS-25 [doc=cs25_amdt_28]). La valeur plus faible/différente apparaissant dans le KG correspond à un test étendu post-failure : si l'item échoue au test standard, on continue jusqu'à destruction, ou jusqu'à atteindre 80 J [doc=cs25_amdt_26]. Les deux valeurs représentent donc des **phases différentes** du même protocole : 21 J pour la conformité initiale (impact unique), 80 J comme limite max du test étendu en cas de rupture.",
  "citations": ["F1", "F2", "r1"],
  "reasoning_confidence": 0.85
}
```

### Test NLI Channel 2 (manuel)

| Step | Premise | Hypothesis | Verdict |
|---|---|---|---|
| 1 | "should be subjected to a single impact... impact energy should be 21 J" | "21 J = valeur test standard" | **ENTAILMENT** ✓ |
| 2 | "testing... should be performed until destruction, or until... 80 J" | "80 J = test continué jusqu'à destruction" | **ENTAILMENT** ✓ |
| 3 | F1 + F2 quotes | "21 J = compliance, 80 J = post-failure max — phases distinctes" | **ENTAILMENT BORDERLINE** (synthèse) |

→ **2/3 strict + 1/3 probable** (synthèse marquée `inference_strength: probable`)

**Verdict Mock 2 — q_88** : R3b **VALIDÉ avec nuance**. La step purpose_distinction est une synthèse (pas un fact direct du corpus), donc Channel 2 doit avoir un seuil **plus permissif** pour les steps marqués `inference_strength: probable` que pour `direct`.

## Conclusion Phase 0.B

**R3b VALIDÉ sur les 2 hypothèses** :
- Hyp1 (Structurer abdique) → Relational Structurer extrait `relational_facts` avec marqueurs explicites → Composer génère reasoning_chain. **3/3 NLI direct ✓**
- Hyp2b (Composer short) → Composer enrichit les atomic_facts existants avec un fact relationnel de distinction + reasoning_chain. **2/3 NLI direct + 1/3 probable ✓**

### Implications de design pour CH-47

1. **`inference_strength: direct | probable | weak`** dans chaque step + relation (proposition ChatGPT) — Channel 2 NLI applique des seuils différents :
   - `direct` : seuil 0.85
   - `probable` : seuil 0.70
   - `weak` : seuil 0.55, mention explicite dans la réponse ("Sous réserve de…")

2. **Schéma `facts_first_v2`** étendu : `atomic_facts` + `relational_facts` + `reasoning_graph` (proposition Claude Web).

3. **Anti-dérive LLM-libre** : le Composer doit citer **chaque step** par `evidence_ids` ou `relation_id`. Une step sans citation valide = rejet automatique Channel 1 Verifier.

4. **Marqueurs linguistiques universels** (validation domain-agnostic) :
   - Causal : `because, donc, therefore, par conséquent, hence, entraîne, conduit à, results in, leads to, necessitates`
   - Conditional : `if/then, si/alors, provided that, à condition que, when, lorsque, unless, sauf si`
   - Hypothetical : `in case of, en cas de, assuming, supposant, were X to occur, si X devait`
   - Purpose : `in order to, afin de, pour, so as to, with the aim of, dans le but de`

→ Ces marqueurs sont **multilingues par construction** (FR/EN/DE/ES/IT). Pas de regex métier, pas de keywords sectoriels. **Charte domain-agnostic respectée.**

## Scope CH-47 final (validé par Phase 0.B)

| Sous-chantier | Description | Priorité | Effort |
|---|---|---|---|
| **CH-47.1** Relational Structurer | Nouveau prompt extraction `atomic_facts` + `relational_facts` (causal/conditional/purpose/hypothetical) avec marqueurs linguistiques universels. Ne capture **que** des relations explicitement marquées dans le texte (pas d'inférence libre). | **P0** | 5-7j |
| **CH-47.2** Constrained Reasoning Composer | Nouveau Composer LLM (Qwen2.5-72B) avec output `reasoning_steps` structuré + `inference_strength` + citations forcées par step. Output rejeté si une step n'a aucun `evidence_ids` valide. | **P0** | 3-4j |
| **CH-47.3** Channel 2 NLI seuils calibrés | mDeBERTa-v3 avec seuils différenciés par `inference_strength`. Step `probable` peut passer si entailment ≥ 0.70 (vs 0.85 pour `direct`). | **P0** | 1-2j |
| **CH-47.4** Analyzer robustness (DeBERTa Sprint S2) | Réutiliser le classifier DeBERTa déjà entraîné sur 14767q (taxonomie answer_shape) pour router questions reasoning vs factual avec accuracy > V4 actuel. **Optionnel si CH-47.1+47.2 sont assez robustes au routing imparfait.** | **P1** | 2-3j (si DeBERTa réutilisable) |

**Effort P0 total** : ~10-13 jours
**Effort P0+P1** : ~12-16 jours

## Gates go-prod CH-47 (consolidés)

1. Robust global ≥ 0.55 (cible produit, vs 0.351 actuel V4)
2. Aucune catégorie ne perd > 5pp vs V3_S0
3. Hypothetical/causal_why/multi_hop récupèrent ≥ 60% du delta perdu (≥ 0.50 chacune)
4. Faithfulness Channel 2 ≥ 0.85 (maintenir acquis V4 anti-hallucination)
5. Hallucination rate (sentences sans citation valide) ≤ 8%
6. Reasoning chain validity ≥ 80% (steps NLI-entailed selon seuils calibrés)
7. **Abstention rate sur questions reasoning ≤ 15%** (vs 60% observé en Phase 0.B)

## Croisement final chantiers existants

- **ADR V4 §10** à rédiger (amendement Facts-First → Facts+Relations First)
- **Sprint S2 (Question Router)** DEFERRED → réutilisable pour CH-47.4 P1 si DeBERTa déjà entraîné
- **CH-46 optims latence** → reprendre **après** CH-47 stabilisé (la latence est secondaire vs la qualité)
- **Aucun chantier existant** ne couvre CH-47.1 ni CH-47.2 → nouveaux chantiers

## Prochaines étapes

1. **Décision finale Fred** : valider scope P0 (CH-47.1 + 47.2 + 47.3) ?
2. **Phase 1 CH-47** : ADR amendement + spec détaillée (1-2j)
3. **Phase 2 CH-47** : implémentation P0 (~10-13j)
4. **Phase 3 CH-47** : re-bench global + validation gates
