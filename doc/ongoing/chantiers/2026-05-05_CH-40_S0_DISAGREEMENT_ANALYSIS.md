# V4 S0 — Analyse désaccords judge vs structured metrics

_Généré : 2026-05-05 16:51 UTC_
_Source rapport : robustness_run_20260505_163544_V3_S0_BASELINE.json_
_Tag : `V3_S0_BASELINE`_
_Juge : `meta-llama/Llama-3.3-70B-Instruct`_

## Vue d'ensemble

- **Total samples avec disagreement calculé** : 63
- **judge_overscored** (Claude dit 'bon' mais structured 'mauvais') : 20 (31.7%)
- **judge_underscored** (Claude rate ce que structured voit) : 12 (19.0%)
- **aligned** : 31 (49.2%)

**Interprétation** : un taux élevé de `judge_overscored` indique que le LLM-juge sur-évalue les réponses qui ont l'air structurées/cohérentes mais qui manquent les faits critiques (style over substance). C'est l'angle mort principal de l'overfit Claude-juge identifié dans l'ADR_OSMOSIS_V4_ARCHITECTURE.md.

---

## Distribution par primary_type

| primary_type | overscored | underscored | aligned | overscored % |
|---|---:|---:|---:|---:|
| causal | 6 | 4 | 3 | 46.2% |
| factual | 1 | 0 | 4 | 20.0% |
| false_premise | 0 | 1 | 4 | 0.0% |
| list | 5 | 4 | 11 | 25.0% |
| temporal | 4 | 2 | 9 | 26.7% |
| unanswerable | 4 | 1 | 0 | 80.0% |

## Distribution par catégorie source

| catégorie | overscored | underscored | aligned |
|---|---:|---:|---:|
| causal_why | 4 | 3 | 3 |
| conditional | 1 | 0 | 1 |
| false_premise | 0 | 1 | 4 |
| hypothetical | 2 | 1 | 0 |
| lifecycle_evolves_from | 1 | 0 | 4 |
| lifecycle_supersedes | 2 | 1 | 2 |
| multi_hop | 3 | 0 | 2 |
| negation | 0 | 0 | 3 |
| set_list | 0 | 4 | 8 |
| synthesis_large | 2 | 0 | 1 |
| temporal_evolution | 1 | 1 | 3 |
| unanswerable | 4 | 1 | 0 |

---

## Top-20 judge_overscored (style over substance — STYLE OF JUDGE)

_Ces cas sont les plus pédagogiques : Claude-juge dit 'bon' mais les structured metrics montrent que les faits critiques manquent. À examiner pour calibrer le bake-off A/B/C (CH-40.4)._

### 1. T6_AERO_UNA_003 — unanswerable / unanswerable

**Question** : Combien d'autorisations d'export ont été délivrées par la France en 2023 selon le règlement 2021/821 ?

- judge_score = **1.00** | structured_avg = **0.00** | disagreement = **1.00**
- citation_rate : 0.0 (unsupported : 1/1)
- judge reason : _Correctly states the answer is unavailable due to lack of information._

### 2. T6_AERO_CAUS_002 — causal_why / causal

**Question** : Pourquoi l'Annex I du règlement 2021/821 doit-elle être régulièrement mise à jour ?

- judge_score = **0.90** | structured_avg = **0.25** | disagreement = **0.65**
- exact_match : 1/6 (missing : `['Wassenaar', 'MTCR', 'NSG', 'Australia Group', 'CWC']`)
- citation_rate : 0.333 (unsupported : 2/3)
- judge reason : _Answer is grounded in sources and explains the reason for updates._

### 3. T6_AERO_CAUS_011 — causal_why / causal

**Question** : Pourquoi les autorisations doivent-elles être valides sur l'ensemble du territoire douanier de l'Union ?

- judge_score = **0.90** | structured_avg = **0.25** | disagreement = **0.65**
- exact_match : 0/1 (missing : `['2021/821']`)
- citation_rate : 0.5 (unsupported : 1/2)
- judge reason : _Answer is grounded in sources and explains the reason for uniform validity._

### 4. T6_AERO_SYN_010 — synthesis_large / list

**Question** : Synthétise les exigences CS-25 sur la sécurité passagers en croisant les paragraphes pertinents (CS 25.561 crash, CS 25.785 seats, CS 25.795 security).

- judge_score = **0.90** | structured_avg = **0.39** | disagreement = **0.51**
- item_recall : 0/4 matched (missing : `["CS 25.561 (conditions d'atterrissage d'urgence)", 'CS 25.785 (sièges, ceintures de sécurité et retenues — amendé par NPA 2013-11)', 'CS 25.795 (sécurité — amendé par NPA 2015-11)', "CS 25.788 (dispositions d'urgence en cabine — créé par NPA 2015-19)"]`)
- exact_match : 3/7 (missing : `['CS 25.788', 'NPA 2013-11', 'NPA 2015-11', 'NPA 2015-19']`)
- citation_rate : 0.75 (unsupported : 1/4)
- judge reason : _Comprehensive overview of CS-25 requirements with relevant sources._

### 5. T7_AERO_0032 — lifecycle_supersedes / temporal

**Question** : Existe-t-il une chaîne complète de SUPERSEDES dans le corpus aerospace ?

- judge_score = **0.50** | structured_avg = **0.00** | disagreement = **0.50**
- exact_match : 0/2 (missing : `['2021/821', '428/2009']`)
- citation_rate : 0.0 (unsupported : 2/2)
- judge reason : _Partially relevant but misses the key point of citing explicit repeal._

### 6. T6_AERO_UNA_006 — unanswerable / unanswerable

**Question** : Quelle est la position de la Russie sur le règlement 2021/821 ?

- judge_score = **1.00** | structured_avg = **0.50** | disagreement = **0.50**
- exact_match : 1/1 (missing : `[]`)
- citation_rate : 0.0 (unsupported : 1/1)
- judge reason : _Correctly states that the information is unavailable._

### 7. T6_AERO_UNA_007 — unanswerable / unanswerable

**Question** : Quel est le coût d'une autorisation d'export individuelle au titre du règlement 2021/821 ?

- judge_score = **1.00** | structured_avg = **0.50** | disagreement = **0.50**
- exact_match : 1/1 (missing : `[]`)
- citation_rate : 0.0 (unsupported : 1/1)
- judge reason : _Correctly states the answer is unavailable due to lack of information._

### 8. T6_AERO_UNA_011 — unanswerable / unanswerable

**Question** : Le règlement 2021/821 a-t-il été traduit dans les 24 langues officielles de l'UE ?

- judge_score = **1.00** | structured_avg = **0.50** | disagreement = **0.50**
- exact_match : 1/1 (missing : `[]`)
- citation_rate : 0.0 (unsupported : 1/1)
- judge reason : _Answer correctly states unavailability of information._

### 9. T6_AERO_COND_011 — conditional / factual

**Question** : Si un transfert intra-Union concerne un item listé en Partie 2 de l'Annex IV (sous 428/2009), une autorisation générale est-elle suffisante ?

- judge_score = **0.90** | structured_avg = **0.50** | disagreement = **0.40**
- exact_match : 1/2 (missing : `["Partie 2 de l'Annex IV"]`)
- citation_rate : 0.5 (unsupported : 1/2)
- judge reason : _Answer is mostly correct and grounded in sources._

### 10. T6_AERO_HYP_002 — hypothetical / causal

**Question** : Si CS-25 Amendment 28 était abrogé demain, quelle serait la version applicable ?

- judge_score = **0.90** | structured_avg = **0.50** | disagreement = **0.40**
- exact_match : 1/2 (missing : `['2021-11-24']`)
- citation_rate : 0.5 (unsupported : 1/2)
- judge reason : _Answer is correct and grounded in documented evidence._

### 11. T6_AERO_MH_001 — multi_hop / list

**Question** : Si une entreprise basée en France exporte vers le Japon un 'network access controller' tel que défini dans le délégué 2024/2547, quelle est la base juridique principale qui exige une autorisation et a

- judge_score = **0.90** | structured_avg = **0.50** | disagreement = **0.40**
- item_recall : 0/2 matched (missing : `['Article du règlement (UE) 2021/821', 'autorité française désignée pour les autorisations dual-use']`)
- exact_match : 1/2 (missing : `['2024/2547']`)
- citation_rate : 1.0 (unsupported : 0/3)
- judge reason : _Answer is mostly correct and well-grounded in relevant sources._

### 12. T6_AERO_SYN_006 — synthesis_large / list

**Question** : Résume la chaîne de causalité réglementaire des items dual-use depuis les régimes internationaux jusqu'à l'autorisation finale d'un exportateur EU.

- judge_score = **0.80** | structured_avg = **0.44** | disagreement = **0.36**
- item_recall : 0/5 matched (missing : `['Régimes internationaux (Wassenaar, MTCR, NSG, Australia Group, CWC)', 'Décisions sur items contrôlés', 'Transposition EU via délégués modifiant Annex I de 2021/821', "Mécanisme d'autorisation national de l'État membre", "Décision de l'autorité compétente (10 jours + extension max 30)"]`)
- exact_match : 1/3 (missing : `['10 jours', '30']`)
- citation_rate : 1.0 (unsupported : 0/4)
- judge reason : _Good coverage of regulatory chain with relevant sources._

### 13. T7_AERO_0006 — lifecycle_supersedes / temporal

**Question** : Le règlement 428/2009 est-il toujours en vigueur ?

- judge_score = **0.90** | structured_avg = **0.58** | disagreement = **0.32**
- exact_match : 2/3 (missing : `['DEPRECATED']`)
- citation_rate : 0.5 (unsupported : 1/2)
- judge reason : _Correctly identifies replacement regulation with evidence._

### 14. T7_AERO_0044 — lifecycle_evolves_from / temporal

**Question** : L'EVOLVES_FROM du délégué 2023/66 vers 2021/821 implique-t-il que 2021/821 est DEPRECATED ?

- judge_score = **0.90** | structured_avg = **0.58** | disagreement = **0.32**
- exact_match : 2/3 (missing : `['Annex I']`)
- citation_rate : 0.5 (unsupported : 1/2)
- judge reason : _Answer correctly identifies modification and parent regulation._

### 15. T6_AERO_CAUS_008 — causal_why / causal

**Question** : Pourquoi le règlement 2021/821 confère-t-il à la Commission le pouvoir d'adopter des actes délégués pour modifier l'Annex I ?

- judge_score = **0.80** | structured_avg = **0.50** | disagreement = **0.30**
- exact_match : 1/2 (missing : `['Annex I']`)
- citation_rate : 0.5 (unsupported : 1/2)
- judge reason : _Answer is mostly correct and grounded in sources._

### 16. T6_AERO_TMP_007 — temporal_evolution / temporal

**Question** : Le règlement 428/2009 était-il en vigueur le 1er janvier 2022 ?

- judge_score = **0.90** | structured_avg = **0.62** | disagreement = **0.28**
- exact_match : 3/4 (missing : `['2021-06-11']`)
- citation_rate : 0.5 (unsupported : 1/2)
- judge reason : _Answer correctly identifies replacement rule with source._

### 17. T6_AERO_CAUS_012 — causal_why / causal

**Question** : Pourquoi CS-25 exige-t-elle que la conformité aux exigences de caractéristiques de vol soit démontrée avec CS 25.671 et 25.672 si un système de stabilisation augmentée est utilisé ?

- judge_score = **0.90** | structured_avg = **0.62** | disagreement = **0.28**
- exact_match : 3/4 (missing : `['CS 25.672']`)
- citation_rate : 0.5 (unsupported : 1/2)
- judge reason : _Answer is grounded in sources and explains the reason for CS-25 requirements._

### 18. T6_AERO_MH_012 — multi_hop / list

**Question** : Si une question est posée 'Quelles sources fiables pour les exigences dual-use applicables aujourd'hui ?', quelle cascade OSMOSIS V2 produit-il ?

- judge_score = **0.60** | structured_avg = **0.33** | disagreement = **0.27**
- item_recall : 0/2 matched (missing : `['2021/821', '2024/2547']`)
- exact_match : 0/2 (missing : `['2021/821', '2024/2547']`)
- citation_rate : 1.0 (unsupported : 0/1)
- judge reason : _Partially relevant but lacks logical connection to dual-use requirements._

### 19. T6_AERO_MH_007 — multi_hop / list

**Question** : Un avocat doit défendre la position d'un exportateur ayant exporté un item en 2020 sur la base du règlement 428/2009 (alors en vigueur). En 2024, est-ce contestable ?

- judge_score = **0.70** | structured_avg = **0.45** | disagreement = **0.26**
- item_recall : 0/4 matched (missing : `['428/2009 était la base juridique applicable en 2020', "2021/821 n'a abrogé qu'en juin 2021", "L'application rétroactive de 2021/821 n'est pas la règle", 'La défense doit invoquer le principe de sécurité juridique']`)
- exact_match : 2/3 (missing : `['juin 2021']`)
- citation_rate : 0.667 (unsupported : 1/3)
- judge reason : _Answer is partially correct but lacks direct reference to non-retroactivity._

### 20. T6_AERO_HYP_010 — hypothetical / causal

**Question** : Si CS-25 Amendment 28 contenait une erreur de spécification (ex: 21 J au lieu de 12 J), comment serait-elle corrigée ?

- judge_score = **0.80** | structured_avg = **0.55** | disagreement = **0.25**
- exact_match : 3/5 (missing : `['CS-25 Amendment 22', 'CS 25.951(c)']`)
- citation_rate : 0.5 (unsupported : 1/2)
- judge reason : _Answer is mostly correct and grounded in sources, but lacks direct reference to NPA + ED Decision._

---

## Top-20 judge_underscored (Claude trop strict)

_Ces cas montrent où le judge LLM est plus strict que les structured metrics. Plus rare. Peut signaler que le prompt judge a un critère implicite que le gold-set ne capture pas._

### 1. T6_AERO_UNA_004 — unanswerable
- judge_score = **0.00** | structured_avg = **1.00**
- judge reason : _Answer fabricates information not present in the corpus._

### 2. T6_AERO_FP_007 — false_premise
- judge_score = **0.00** | structured_avg = **1.00**
- judge reason : _Answer accepts the false premise without correction._

### 3. T6_AERO_CAUS_006 — causal_why
- judge_score = **0.00** | structured_avg = **0.50**
- judge reason : _Answer claims lack of evidence, failing to provide a causal explanation._

### 4. T6_AERO_CAUS_009 — causal_why
- judge_score = **0.00** | structured_avg = **0.50**
- judge reason : _Answer claims lack of information, ignoring provided reference evidence._

### 5. T7_AERO_0034 — lifecycle_supersedes
- judge_score = **0.30** | structured_avg = **0.75**
- judge reason : _Misses the key point of total repeal._

### 6. T6_AERO_TMP_012 — temporal_evolution
- judge_score = **0.20** | structured_avg = **0.62**
- judge reason : _Answer is incorrect, citing Amendment 27 as in effect in June 2021._

### 7. T6_AERO_SET_006 — set_list
- judge_score = **0.00** | structured_avg = **0.39**
- judge reason : _Answer is completely wrong and irrelevant._

### 8. T6_AERO_SET_005 — set_list
- judge_score = **0.20** | structured_avg = **0.56**
- judge reason : _Answer is partially relevant but misses the key exemptions._

### 9. T6_AERO_SET_009 — set_list
- judge_score = **0.00** | structured_avg = **0.33**
- judge reason : _Answer is completely irrelevant to the question._

### 10. T6_AERO_SET_008 — set_list
- judge_score = **0.00** | structured_avg = **0.33**
- judge reason : _Answer lists unrelated documents, misses the only correct DEPRECATED document._

### 11. T6_AERO_HYP_003 — hypothetical
- judge_score = **0.20** | structured_avg = **0.50**
- judge reason : _Fails to apply hypothetical reasoning based on provided evidence._

### 12. T6_AERO_CAUS_010 — causal_why
- judge_score = **0.00** | structured_avg = **0.25**
- judge reason : _Answer claims lack of information instead of providing causal explanation._
