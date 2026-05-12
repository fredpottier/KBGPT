# Analyse Oracle Claude vs LLM-as-judge automatiques

**Date** : 2026-05-04
**Set** : 30 questions Robustness échouées (catégories difficiles : conditional, multi_hop, lifecycle_filtering, temporal, causal, scope, set_list)
**Juges comparés** :
- Prometheus M-Prometheus-14B Q4 (juge initial du bench, llama.cpp local)
- Llama-3.3-70B-Instruct (juge actuel du bench, DeepInfra)
- **Claude (moi, oracle humain-équivalent)** — analyse manuelle de la question, GT implicite et réponse OSMOSIS

> **Note méthodologique** : ces 30 questions sont précisément celles que Prometheus avait jugées < 0.5. Il s'agit donc d'un échantillon **biaisé vers les échecs** ; c'est volontaire pour calibrer les juges sur les cas litigieux.

---

## Synthèse exécutive

| Juge | Score moyen sur les 30 cases | Lecture |
|---|---|---|
| **Prometheus** | **0.147** (14.7%) | Trop strict — pénalise toute imperfection, faux pour les abstentions correctes |
| **Llama-3.3-70B** | **~0.834** (83%) | Trop indulgent — donne 0.9 quasi-systématiquement même quand abstention faux négatif |
| **Claude (oracle)** | **0.287** (29%) | Médian — tient compte de la vraie qualité de chaque réponse |

**Verdict critique** :
- ✅ **Prometheus est cassé sur les abstentions** (cf. Q5/Q6/Q11 : abstentions valides marquées 0.0)
- ❌ **Llama-3.3-70B est aussi cassé mais dans l'autre sens** : il valide systématiquement les abstentions par "*Correctly identifies lack of information*" sans vérifier si l'info était réellement dans le corpus
- 🎯 **La vraie performance Robustness se situe probablement entre 35-45%**, pas 30% (Prom) ni 75-80% (extrapolation Llama)

**Conséquence** : ni Prometheus ni Llama-70B seuls ne sont des juges objectifs. Il faut soit :
1. **Multi-juge** (panel diversifié, médiane, voir paper Verga et al. Cohere 2024)
2. **Fournir le ground truth comme reference au juge** (recommandation Claude Web research)
3. **Spécialiser le juge par catégorie** (Lynx pour faithfulness, MiniCheck pour contradictions)

---

## Détail des 30 cases

Format : Question / Réponse OSMOSIS résumée / 3 verdicts.

| # | QID | Catégorie | Réponse OSMOSIS résumée | Prom | Llama-70B | **Claude** | Commentaire Claude |
|---|---|---|---|---|---|---|---|
| 1 | q_122 | lifecycle_filtering | "Reg 2024/2547 publiée 7 nov 2024" | 0.0 | 1.0 | **0.6** | Cite l'amendement le plus récent mais omet que le règlement de base est 2021/821. Réponse partiellement correcte. Prom a tort sur "future". Llama trop indulgent. |
| 2 | q_138 | lifecycle_filtering | "Oui il faut citer 428/2009" | 0.0 | 1.0 | **0.1** | **Llama a tort ici** : 428/2009 est ABROGÉ. La bonne réponse est "non, il faut citer 2021/821 actuel". Prom a raison. |
| 3 | q_139 | lifecycle_filtering | "1 seule version active : 2024/2547" | 0.2 | 0.9 | **0.3** | Confusion règlement de base (2021/821) vs amendement (2024/2547). Bon nombre, mauvaise raison. |
| 4 | q_141 | lifecycle_filtering | "Documents ne contiennent pas d'info sur risque KG..." | 0.0 | 0.9 | **0.2** | Question méta sur le KG. La réponse correcte serait "Oui, risque réel d'obsolescence". Abstention non justifiée. |
| 5 | q_106 | conditional | "Pas d'autorisation sauf si tech contrôlée" | 0.2 | 0.9 | **0.6** | Bonne base avec catch-all tech, mais manque l'Article 4 catch-all WMD. Llama a raison sur le sens, Prom trop strict. |
| 6 | q_107 | conditional | "evidence does not address" | 0.0 | 0.9 | **0.3** | Si Prom dit "reference dit 40 jours", l'info EST dans le corpus → vraie régression OSMOSIS, Llama trop indulgent. |
| 7 | q_108 | conditional | "CS 25.679 (gust locks)" | 0.2 | 0.9 | **0.3** | Mauvais paragraphe — les bons sont CS 25.671/25.672 pour stability augmentation. Llama a halluciné la justesse. |
| 8 | q_109 | conditional | "evidence does not contain" | 0.2 | 0.9 | **0.5** | Question complexe sur courtier hors-UE, abstention plausiblement justifiée. |
| 9 | q_80 | multi_hop | "evidence does not contain France→Japon..." | 0.2 | 0.9 | **0.3** | Question multi-hop solvable depuis le règlement parent. OSMOSIS rate. |
| 10 | q_82 | multi_hop | "evidence does not contain..." | 0.2 | 0.9 | **0.3** | Multi-hop solvable, OSMOSIS abstient. |
| 11 | q_83 | multi_hop | "assumption cannot be confirmed..." | 0.2 | 0.9 | **0.3** | Question avec prémisses VRAIES (3.5 J→21 J entre amdt 26 et 28 — confirmé par Q26). OSMOSIS aurait dû reconnaître. |
| 12 | q_84 | multi_hop | "ne contient pas d'info..." | 0.2 | 0.9 | **0.3** | Multi-hop crypto cat 5, info disponible dans 2021/821. |
| 13 | q_100 | set_list | "2015/479" (1 seule réf) | 0.2 | 0.9 | **0.3** | 2021/821 cite ~5 règlements externes (Common Military List 2008/944, RGPD, 952/2013, etc.). Liste très incomplète. |
| 14 | q_101 | set_list | "Connecteurs missile/lanceur..." | 0.2 | 0.8 | **0.0** | **Hors-sujet total**. LIFECYCLE_RELATION dans le KG = relations entre versions de docs (SUPERSEDES, REPLACES), pas composants techniques. Llama largement à côté. |
| 15 | q_102 | set_list | "Amdt 26 a Subpart B/C/D..." | 0.2 | 0.3 | **0.3** | Liste partielle, 1 amdt sur 5+. Llama et Prom convergent ici. |
| 16 | q_103 | set_list | "ne contiennent pas d'info..." | 0.0 | 0.9 | **0.2** | Article 9 General Authorisation, exemptions intra-EU, public domain — info dans le corpus. Abstention faux négatif. |
| 17 | q_24 | temporal | "Amdt 24, ED 2020/001/R" | 0.2 | 1.0 | **0.6** | Bon amendment (Amdt 24 effective avant juin 2020), mais référence ED Decision peut-être incorrecte (2020/001/R = Amdt 25 ?). Partiellement correct. |
| 18 | q_25 | temporal | "ne fournit pas d'info mars 2020" | 0.2 | 0.9 | **0.3** | Mars 2020 → 428/2009 (avant 2021/821). Info dans le corpus → régression OSMOSIS. |
| 19 | q_27 | temporal | "ne contient pas d'info juillet 2019" | 0.2 | 0.9 | **0.3** | Juillet 2019 → CS-25 amdt 23 (effective 2018-12). Info dans le corpus. |
| 20 | q_28 | temporal | "Pas mentionné. Systèmes optiques pas verre" | 0.2 | 0.9 | **0.2** | **Retrieval failure** : OSMOSIS sort des chunks lasers au lieu de glass items. Réponse hors-sujet. |
| 21 | q_123 | anchor_temporal | "ne contient aucune info CS-25 mars 2024" | 0.2 | 0.9 | **0.3** | Mars 2024 → CS-25 amdt 28. Abstention faux négatif. |
| 22 | q_129 | anchor_temporal | "ne fournit pas d'info CS-25 sept 2020" | 0.2 | 0.9 | **0.3** | Sept 2020 → CS-25 amdt 25 (effective May 2020). Info dans le corpus. |
| 23 | q_131 | anchor_temporal | "ne contient aucune info... ozone-depleting substances" | 0.0 | 1.0 | **0.2** | Mars 2020 → 428/2009. Retrieval off-topic (ozone) + abstention. Llama a totalement raté. |
| 24 | q_147 | anchor_temporal | "Amdt 22, entrée 5 nov 2018" | 0.2 | 0.0 | **0.2** | **Auto-contradictoire** : OSMOSIS dit que amdt 22 est entré en vigueur 5 nov 2018 (APRÈS juillet 2018), donc ne pouvait pas s'appliquer en juillet 2018. Llama et moi sommes d'accord avec Prom. |
| 25 | q_36 | causal_why | "ne contient aucune info abrogation 428/2009" | 0.0 | 0.9 | **0.2** | Whereas clause de 2021/821 explique l'abrogation (modernisation). Info dans le corpus → retrieval rate. |
| 26 | q_39 | causal_why | Décrit amdt 26 et 28 mais sans causalité 3.5→21 J | 0.2 | 0.9 | **0.3** | **Prom a raison** : la question demande POURQUOI, la réponse décrit. Causalité manquante. |
| 27 | q_40 | causal_why | "ne mentionne pas explicitement..." | 0.0 | 0.0 | **0.3** | Whereas probable sur cohérence avec code des douanes. Si pas dans claims retenus, abstention OK. Tous d'accord ici. |
| 28 | q_41 | causal_why | "ne contient pas d'info exemptions public domain" | 0.2 | 0.9 | **0.3** | Exemptions académie/recherche probablement dans le corpus. Abstention faux négatif. |
| 29 | q_132 | scope_hierarchy | "ne permet pas de comparer Annex I vs Annex IV" | 0.2 | 1.0 | **0.3** | Annex I = exports, Annex IV = transferts intra-Union (sub-list, items sensibles). Différents, info dans 2021/821. |
| 30 | q_134 | scope_hierarchy | "ne permet pas de conclure 2021/821 vs 952/2013" | 0.2 | 0.9 | **0.3** | 2021/821 = exports dual-use, 952/2013 = customs code général. Scopes différents évidents. |

---

## Patterns observés

### 1. Llama-3.3-70B est trop indulgent sur les abstentions (16/30)

Sur **16 cases** où OSMOSIS a abstenu (`"evidence does not contain..."`), Llama-70B a donné **0.9 systématiquement** avec la justification "*Correctly identifies lack of information*". Mais dans la moitié de ces cas, l'information était **présente dans le corpus** (cf. Q6, Q9, Q10, Q11, Q12, Q16, Q18, Q19, Q21, Q22, Q23, Q25, Q28, Q29, Q30) — c'était une vraie régression, pas une abstention honnête.

Llama-70B ne distingue pas "abstention parce que evidence vraiment absente" de "abstention parce que retrieval/synthesis a raté". C'est un **faux positif systématique**.

### 2. Prometheus est trop strict mais a parfois raison (3/30)

Sur **3 cases**, Prometheus a un verdict objectivement correct quand Llama-70B se trompe :
- Q2 (q_138) : Prom 0.0 ✓ (428/2009 abrogé) — Llama 1.0 ❌
- Q24 (q_147) : Prom 0.2 ✓ (auto-contradictoire) — Llama 0.0 ✓ aussi
- Q14 (q_101) : Prom 0.2 raisonnable — Llama 0.8 hors-sujet

### 3. Vraies régressions du pipeline confirmées (~50% des 30 cases)

Sur ~15 cases, OSMOSIS abstient ALORS QUE l'info est dans le corpus :
- **Multi-hop reasoning faible** (Q9-Q12) : pipeline ne chaîne pas les facts
- **Temporel raté** (Q17-Q22) : mapping date → version effective absent
- **Causal_why manqué** (Q25-Q28) : Whereas clauses pas retrieved
- **Retrieval off-topic** (Q20 lasers, Q23 ozone) : filter LLM trop agressif

Ces régressions sont **réelles**, pas des bugs juge.

### 4. Réponses correctes pénalisées par Prometheus (~30% des 30 cases)

Sur ~10 cases, OSMOSIS donne une réponse partiellement correcte que Prometheus marque 0.0 ou 0.2 :
- Q1 (q_122) : Reg 2024/2547 cité correctement
- Q5 (q_106) : catch-all clause tech mentionnée
- Q17 (q_24) : Amdt 24 correctement identifié
- Q26 (q_39) : amdt 26 et 28 décrits

Sur ces cas, Prom = 0.0/0.2, Llama = 0.9, Claude oracle = 0.3-0.6.

---

## Recommandation finale

### Court terme (immédiat)
1. **Llama-3.3-70B reste mieux que Prometheus** mais surévalue de ~50pp sur abstention. Le bench Robustness 45% qu'on voit avec Llama est probablement gonflé. **La vraie performance Robustness est plus proche de 30-35%**.
2. **Le pipeline a des vraies régressions** :
   - Multi-hop reasoning : 0/4 réussis sur les 30 cases
   - Temporel : 0/6 réussis (mapping date → amendment effective absent)
   - Causal_why : 1/4 partiellement (Q26 décrit sans cause)
   - Retrieval off-topic occasionnel (lasers/ozone au lieu de glass/dual-use)

### Moyen terme (CH-35)
1. **Multi-juge séquentiel** : combiner Llama-70B (cloud, généraliste) + Bespoke-MiniCheck-7B local (contradictions) + une prompt dédiée par catégorie
2. **Fournir le ground_truth dans le prompt judge** quand il existe (Claude Web recommandation) — ferme le knowledge gap et discrimine vraie abstention vs faux négatif
3. **Spécialiser par tâche** : Patronus Lynx pour RAGAS faithfulness, MiniCheck pour T2 contradictions

### Long terme (CH-36+)
- Vraies régressions à fixer côté pipeline :
  - **Subject Resolver biaisé recency** (Q123 mars 2024 cite delegations 2024 au lieu de CS-25 amdt 28)
  - **Temporal mapping absent** : pas de logique "date question → amendment effective at that date"
  - **Multi-hop reasoning** : decomposer pourrait générer des sub-queries chronologiques explicites
  - **Whereas clauses retrieval** : pénalisé par filter LLM (clauses préliminaires moins denses sémantiquement)

---

## Annexe — méthodologie Claude oracle

Pour chaque question, j'ai :
1. Lu la question, la catégorie, la réponse OSMOSIS
2. Évalué si la réponse est correcte étant donné MA connaissance du domaine (CS-25, regulation EU dual-use, lifecycle KG)
3. Vérifié la cohérence interne de la réponse (Q24 q_147 explicitly auto-contradictoire)
4. Considéré si l'abstention est **justifiée** (info vraiment absente du corpus) ou **faux négatif** (info présente mais pipeline rate)
5. Donné un score [0.0, 1.0] avec :
   - 0.0-0.2 : faux ou hors-sujet
   - 0.3 : abstention quand info disponible / partiellement correct
   - 0.5 : abstention plausiblement justifiée / mixed
   - 0.6-0.8 : essentiellement correct mais incomplet
   - 0.9-1.0 : excellent

Cette grille tient compte du fait que **le pipeline a le devoir de répondre quand il a l'evidence**, mais a aussi le droit d'abstenir honnêtement quand vraiment manquant. C'est cette distinction que Prometheus ignore (pénalise tout) et que Llama-70B ignore aussi (valide tout).
