# V4 S0 — Sanity Check Externe Fred

_Généré : 2026-05-05 16:51 UTC_
_Source rapport : robustness_run_20260505_163544_V3_S0_BASELINE.json_
_Sélection : 9 questions stratifiées (FR=9, EN=0)_

## Instructions

Pour chaque question, vous voyez :
- La question (FR ou EN)
- La réponse V3 OSMOSIS
- Le score du LLM-judge (Llama-3.3-70B)
- Le score structured metrics (item_recall + exact_match + citation)
- Les éventuels gaps détectés

**Émettez un verdict ternaire pour chacune** :
- ✅ **OK** : la réponse est correcte / acceptable pour un compliance officer
- ❌ **KO** : la réponse contient une erreur factuelle, identifiant inversé, valeur fausse
- ⚠️ **bizarre** : ni clairement OK ni KO — formulation suspecte, partial, instruction-following bug

**Après la review, comptez** :
- Si > 2/10 cas où Claude-juge dit OK (score ≥ 0.7) mais vous dites KO → **judge-overscoring grave**
- → déclenche bake-off CH-40.4 même si Pearson global OK

Compléter en éditant la ligne `**Verdict** : ___` à la fin de chaque question.

---

## Question 1 — T6_AERO_NEG_009 (factual / fr)

**Question** : Selon le règlement 428/2009, qu'est-ce qui N'EST PAS soumis à autorisation pour les transferts intra-Communautaires ?

**Réponse V3** :

> None

**Scores** :
- LLM-judge : `0.0` (Answer is completely wrong and irrelevant.)
- structured_avg : `0.0`
- exact_match : 0/2 (missing : `['428/2009', 'Annexe IV']`)

**Référence** : Selon le règlement 428/2009, les items dual-use NON listés en Annexe IV ne sont pas soumis à autorisation pour les transferts intra-Communautaires.
**Identifiants attendus** : `['428/2009', 'Annexe IV']`

**Verdict** : `___` (OK | KO | bizarre)  
**Note libre** : ___

---

## Question 2 — T6_AERO_COND_011 (factual / fr)

**Question** : Si un transfert intra-Union concerne un item listé en Partie 2 de l'Annex IV (sous 428/2009), une autorisation générale est-elle suffisante ?

**Réponse V3** :

> Pour les transferts intra-Union concernant des items listés en Partie 2 de l'Annexe IV (sous 428/2009), une autorisation générale n'est pas suffisante. Selon le règlement, les items de la Partie 2 de l'Annexe IV ne bénéficient pas d'une autorisation générale pour le commerce intra-Communautaire [doc=dualuse_reg_428_2009_original_372b7ac3].

**Scores** :
- LLM-judge : `0.9` (Answer is mostly correct and grounded in sources.)
- structured_avg : `0.5`
- exact_match : 1/2 (missing : `["Partie 2 de l'Annex IV"]`)

**Référence** : Non : selon le règlement 428/2009, les items listés en Partie 2 de l'Annex IV ne sont pas couverts par une autorisation générale. Une autorisation spécifique est requise.
**Identifiants attendus** : `['428/2009', "Partie 2 de l'Annex IV"]`

**Verdict** : `___` (OK | KO | bizarre)  
**Note libre** : ___

---

## Question 3 — T6_AERO_SET_009 (list / fr)

**Question** : Liste les références EU externes citées dans le règlement 2021/821.

**Réponse V3** :

> Les références EU externes citées dans le règlement 2021/821 incluent les sites web des régimes de non-prolifération internationaux et des arrangements de contrôle des exportations : [1] https://www.opcw.org/chemical-weapons-convention, [2] https://www.wassenaar.org/, [3] http://www.nuclearsuppliersgroup.org/, [4] http://mtcr.info/, [5] http://www.australiagroup.net/ [doc=dualuse_del_2024_2547_cb08f84b].

**Scores** :
- LLM-judge : `0.0` (Answer is completely irrelevant to the question.)
- structured_avg : `0.333`
- exact_match : 0/4 (missing : `['Reg 952/2013', 'Reg 2016/679', 'Reg 2018/1725', 'Council Common Position 2008/944/CFSP']`)
- item_recall : 0/4 (missing : `['Reg 952/2013 (Code des douanes Union)', 'Reg 2016/679 (RGPD)', 'Reg 2018/1725 (traitement par institutions EU)', 'Common Military List of the European Union (Council Common Position 2008/944/CFSP)']`)

**Référence** : Les références EU externes citées dans le règlement 2021/821 sont : Reg 952/2013 (Code des douanes Union), Reg 2016/679 (RGPD), Reg 2018/1725 (traitement par institutions EU), et indirectement Common Military List of the European Union (Council Common Position 2008/944/CFSP).
**Identifiants attendus** : `['Reg 952/2013', 'Reg 2016/679', 'Reg 2018/1725', 'Council Common Position 2008/944/CFSP']`

**Verdict** : `___` (OK | KO | bizarre)  
**Note libre** : ___

---

## Question 4 — T6_AERO_SET_004 (list / fr)

**Question** : Liste les types d'autorisations d'export prévus par le règlement 2021/821.

**Réponse V3** :

> Les documents fournis ne permettent pas de répondre : The provided evidence does not list the specific types of export authorizations as required by the question. The evidence primarily discusses the structure of the export authorization form and amendments to the regulation, but does not enumerate the types of authorizations.

**Scores** :
- LLM-judge : `0.0` (Fails to list export authorization types.)
- structured_avg : `0.0`
- exact_match : 0/1 (missing : `['2021/821']`)
- item_recall : 0/4 (missing : `["autorisation d'exportation individuelle", "autorisation d'exportation globale", "autorisation d'exportation pour grands projets", "Autorisation Générale d'Exportation de l'Union (AGEU)"]`)

**Référence** : Les types d'autorisations d'export prévus par le règlement 2021/821 sont : autorisation d'exportation individuelle, autorisation d'exportation globale, autorisation d'exportation pour grands projets, et Autorisation Générale d'Exportation de l'Union (AGEU).
**Identifiants attendus** : `['2021/821']`

**Verdict** : `___` (OK | KO | bizarre)  
**Note libre** : ___

---

## Question 5 — T6_AERO_TMP_007 (temporal / fr)

**Question** : Le règlement 428/2009 était-il en vigueur le 1er janvier 2022 ?

**Réponse V3** :

> Le règlement 428/2009 n'était plus en vigueur le 1er janvier 2022. Ce règlement a été remplacé par le règlement (EU) 2021/821, qui est entré en vigueur le 9 juin 2021 [doc=dualuse_reg_2021_821_original_65eef5dc].

**Scores** :
- LLM-judge : `0.9` (Answer correctly identifies replacement rule with source.)
- structured_avg : `0.625`
- exact_match : 3/4 (missing : `['2021-06-11']`)

**Référence** : Non. Le 2021/821 (publié le 2021-06-11) avait déjà abrogé le 428/2009. Au 1er janvier 2022, c'était le règlement 2021/821 qui s'appliquait.
**Identifiants attendus** : `['2021/821', '2021-06-11', '428/2009', '1er janvier 2022']`

**Verdict** : `___` (OK | KO | bizarre)  
**Note libre** : ___

---

## Question 6 — T7_AERO_0034 (temporal / fr)

**Question** : Le règlement (UE) 2021/821 abroge-t-il en totalité ou partiellement le règlement 428/2009 ?

**Réponse V3** :

> Le règlement (UE) 2021/821 abroge partiellement le règlement (EC) No 428/2009. Le règlement 2021/821 remplace certaines dispositions du règlement 428/2009, notamment en mettant à jour les listes d'articles à double usage, mais ne l'abroge pas en totalité [doc=dualuse_reg_2021_821_original_65eef5dc].

**Scores** :
- LLM-judge : `0.3` (Misses the key point of total repeal.)
- structured_avg : `0.75`
- exact_match : 2/2 (missing : `[]`)

**Référence** : Le règlement (UE) 2021/821 abroge totalement le règlement 428/2009. Cependant, les références au 428/2009 dans d'autres textes EU sont à interpréter comme renvoyant au 2021/821, selon la pratique habituelle de continuité juridique.
**Identifiants attendus** : `['2021/821', '428/2009']`

**Verdict** : `___` (OK | KO | bizarre)  
**Note libre** : ___

---

## Question 7 — T6_AERO_CAUS_008 (causal / fr)

**Question** : Pourquoi le règlement 2021/821 confère-t-il à la Commission le pouvoir d'adopter des actes délégués pour modifier l'Annex I ?

**Réponse V3** :

> Le règlement 2021/821 confère à la Commission le pouvoir d'adopter des actes délégués pour modifier l'Annexe I afin de garantir une pleine conformité avec les obligations de sécurité internationale dès que possible. Cette compétence permet à la Commission de mettre à jour la liste des articles à double usage en fonction des changements apportés aux listes de contrôle des régimes internationaux de non-prolifération et des arrangements de contrôle des exportations [doc=dualuse_del_2023_996_3616a044].

**Scores** :
- LLM-judge : `0.8` (Answer is mostly correct and grounded in sources.)
- structured_avg : `0.5`
- exact_match : 1/2 (missing : `['Annex I']`)

**Référence** : Le règlement 2021/821 confère à la Commission le pouvoir d'adopter des actes délégués pour modifier l'Annex I afin de permettre une mise à jour rapide de la liste des items dual-use sans passer par la procédure législative ordinaire, alignée sur les évolutions des régimes internationaux qui sont fré
**Identifiants attendus** : `['2021/821', 'Annex I']`

**Verdict** : `___` (OK | KO | bizarre)  
**Note libre** : ___

---

## Question 8 — T6_AERO_HYP_010 (causal / fr)

**Question** : Si CS-25 Amendment 28 contenait une erreur de spécification (ex: 21 J au lieu de 12 J), comment serait-elle corrigée ?

**Réponse V3** :

> Si CS-25 Amendment 28 contenait une erreur de spécification, telle que 21 J au lieu de 12 J, cette erreur serait corrigée par un amendement éditorial. Les amendements éditoriaux sont utilisés pour corriger des erreurs mineures et des incohérences dans le texte des amendements précédents [doc=cs25_amdt_28_32f1a9ac].

**Scores** :
- LLM-judge : `0.8` (Answer is mostly correct and grounded in sources, but lacks direct reference to NPA + ED Decision.)
- structured_avg : `0.55`
- exact_match : 3/5 (missing : `['CS-25 Amendment 22', 'CS 25.951(c)']`)

**Référence** : Si CS-25 Amendment 28 contenait une erreur de spécification, comme 21 J au lieu de 12 J, cette erreur serait corrigée par publication d'un erratum ou d'un correctif via une Notice of Proposed Amendment (NPA) suivie d'une Decision de l'European Aviation Safety Agency (EASA). Par exemple, CS-25 Amendm
**Identifiants attendus** : `['21 J', '12 J', 'CS-25 Amendment 28', 'CS-25 Amendment 22', 'CS 25.951(c)']`

**Verdict** : `___` (OK | KO | bizarre)  
**Note libre** : ___

---

## Question 9 — T6_AERO_FP_009 (false_premise / fr)

**Question** : Pourquoi le règlement 2021/821 requiert-il l'unanimité du Conseil pour les modifications de l'Annex I ?

**Réponse V3** :

> Les documents fournis ne permettent pas de répondre : The provided evidence does not contain information about the requirement for unanimous consent from the Council for modifications to Annex I of Regulation 2021/821.

**Scores** :
- LLM-judge : `0.2` (Fails to correct the false premise and provide correct information.)
- structured_avg : `0.334`
- exact_match : 2/3 (missing : `['actes délégués de la Commission']`)

**Référence** : Le règlement 2021/821 ne requiert pas l'unanimité du Conseil pour les modifications de l'Annex I. Les modifications de l'Annex I sont adoptées par actes délégués de la Commission.
**Identifiants attendus** : `['2021/821', 'Annex I', 'actes délégués de la Commission']`

**Verdict** : `___` (OK | KO | bizarre)  
**Note libre** : ___

---

## Synthèse à compléter

À remplir une fois les 10 verdicts émis :

| Métrique | Valeur |
|---|---|
| Total OK | ___ |
| Total KO | ___ |
| Total bizarre | ___ |
| **Cas judge-overscoring grave** (Claude judge ≥ 0.7 mais Fred dit KO) | ___ |

**Si judge-overscoring grave > 2/10** :
- [ ] Déclencher bake-off A/B/C (CH-40.4) : `python scripts/judge_bakeoff.py`
- [ ] Documenter dans ADR un addendum sur les patterns d'overscoring observés

**Si judge-overscoring grave ≤ 2/10** :
- [ ] Sprint S0 gate validé sur le critère sanity check
- [ ] Continuer S1 (Verifier upgrade)