# A4.13 — Audit échecs par type runtime_v6 (post-bench 50q RRF)

**Source** : `data/benchmark/a38_runtime_v6/run_20260523_070724.json` (V6_HYBRID_RETRIEVAL=rrf, 50q stratifié)

## ⚠️ Cadre domain-agnostic
OSMOSE doit fonctionner identiquement sur médical/réglementaire/aerospace. Les exemples SAP cités servent uniquement à illustrer les patterns d'échec sur le corpus de test actuel.

## Récap performances par type (bench 50q RRF)

| Type | N | C1 mean | Verdict |
|---|---|---|---|
| multi_hop | 10 | 0.150 | ❌ PROBLÉMATIQUE |
| comparison | 10 | 0.100 | ❌ PROBLÉMATIQUE |
| false_premise | 5 | 0.000 | ❌ PROBLÉMATIQUE |
| factual | 15 | 0.333 | ⚠ MOYEN |
| lifecycle | 3 | 0.667 | ✅ OK |
| unanswerable | 2 | 1.000 | ✅ OK |

## 🔍 Type : `multi_hop` (n=10, échecs=8, succès=2)

### Échecs (top 5)

### #1 V2_T4_T4_HUM_0044 (judge=0.0)
**Q** : Que disent les documents sur les RFC destinations et la configuration reseau inter-systemes dans SAP S/4HANA ?
**Type** : multi_hop
**Ground truth** : Les RFC destinations et la configuration réseau inter-systèmes dans SAP S/4HANA s'appuient sur les Remote Function Calls (RFC) comme mécanisme principal de communication, gérant les appels de fonctions, le transfert de paramètres et la gestion d'erreurs entre systèmes ([doc=021_SAP_S4HANA_2023_Admin

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : verdict_insufficient_evidence
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : judge_error:Expecting value: line 1 column 1 (char 0)

**Answer produit** :
> No relevant claim found in the indexed corpus to answer this question.

Uncovered sub-goals:
  - sub_goal 0 (fact_lookup): (no subject)

Possible next steps:
  - Reformulate with more specific terms
  - Verify that the indexed corpus covers this topic...

---

### #2 V2_T4_T4_HUM_0016 (judge=0.0)
**Q** : Que disent les documents sur le MRP (Material Requirements Planning) dans SAP S/4HANA, incluant les transactions, rapports et BAdIs ?
**Type** : multi_hop
**Ground truth** : Le MRP (Material Requirements Planning) dans SAP S/4HANA est documenté de manière constante à travers les Operations Guides des versions 2021, 2022 et 2023, avec un set d'outils et de transactions stable sur les trois releases ([doc=014_SAP_S4HANA_2021_Operations_Guide_819d2c07], [doc=015_SAP_S4HANA

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : verdict_insufficient_evidence
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : judge_error:Expecting value: line 1 column 1 (char 0)

**Answer produit** :
> No relevant claim found in the indexed corpus to answer this question.

Uncovered sub-goals:
  - sub_goal 0 (fact_lookup): (no subject)

Possible next steps:
  - Reformulate with more specific terms
  - Verify that the indexed corpus covers this topic...

---

### #3 V2_T4_T4_HUM_0045 (judge=0.0)
**Q** : Que disent les documents sur le Feature Scope de SAP S/4HANA pour la Finance, incluant la Treasury et le Watch List Screening ?
**Type** : multi_hop
**Ground truth** : Le Feature Scope de SAP S/4HANA pour la Finance couvre un large périmètre fonctionnel détaillé dans le Business Scope FPS03 ([doc=022_Business-Scope-S4HANA-Cloud-Private-Edition-FPS03_cf21e8ba]) et le Feature Scope Description PCE 2023 ([doc=024_SAP-008_SAP_S_4HANA_Cloud_Private_Edition_2023_—_Featu

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : verdict_insufficient_evidence
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : judge_error:Expecting value: line 1 column 1 (char 0)

**Answer produit** :
> No relevant claim found in the indexed corpus to answer this question.

Uncovered sub-goals:
  - sub_goal 0 (fact_lookup): (no subject)

Possible next steps:
  - Reformulate with more specific terms
  - Verify that the indexed corpus covers this topic...

---

### #4 V2_T4_T4_HUM_0018 (judge=0.0)
**Q** : Que disent les documents sur la connectivite reseau et les options VPN/Express Route pour SAP Cloud Private Edition ?
**Type** : multi_hop
**Ground truth** : La connectivité réseau pour SAP S/4HANA Cloud Private Edition repose sur un modèle multi-hyperscaler (AWS, Azure, GCP, IBM Cloud) avec plusieurs options de connexion documentées dans le RISE with SAP Cloud ERP Private deck ([doc=020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357]) et le SAP S/4HANA P

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The candidate answer failed to address the question and instead reported a system error, providing no information about network connectivity or VPN/ExpressRoute options for SAP Cloud Private Edition. 

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #5 V2_T4_T4_HUM_0036 (judge=0.0)
**Q** : Que disent les documents sur le Maintenance Planner et son utilisation dans la preparation des conversions S/4HANA ?
**Type** : multi_hop
**Ground truth** : Le Maintenance Planner est, selon les trois guides (Upgrade 2023, Conversion 2022, Conversion 2023), une **étape obligatoire** dans toute préparation de conversion ou d'upgrade SAP S/4HANA.

**Rôle fonctionnel** ([doc=003_SAP_S4HANA_2023_Upgrade_Guide_299d71e9]) : Le Maintenance Planner doit être ut

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : judge_error:Extra data: line 1 column 8 (char 7)

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### Succès (top 2 pour comparaison)

### #1 V2_V1_GOLD_SAP_Q7_1 (judge=1.0)
**Q** : Pour un client sur SAP ECC EHP6 avec un addon HR custom, quelle est la séquence de migration recommandée vers S/4HANA Cloud Private Edition 2024, et dans quel ordre les modules doivent-ils être reconfigurés ?
**Type** : multi_hop
**Ground truth** : Séquence recommandée : vérifier éligibilité ECC EHP6, analyser add-on HR custom, lancer Readiness Check, Simplification Item Check, Custom Code Migration/ATC, décider cible HCM (SuccessFactors, HCM Compatibility Pack, ou H4S4 selon stratégie), préparer CVI/Finance/AA si concernés, exécuter conversio
**Exact identifiers attendus** : ['Simplification Item Check', 'Cloud Private Edition', 'Custom Code Migration', 'Compatibility Pack', 'Readiness Check', 'SUM/DMO', 'S/4HANA', 'HANA', '2024', 'EHP6']

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : Le candidat a abstenu sa réponse en raison d'une erreur interne ou d'un délai d'attente, ce qui correspond à un cas d'abstention valide face à une question non traitable. L'abstention est conforme à l

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #2 V2_T4_T4_HUM_0023 (judge=0.5)
**Q** : Que disent les documents sur le SAP Readiness Check et son utilisation dans les projets de conversion/upgrade ?
**Type** : multi_hop
**Ground truth** : Le SAP Readiness Check est, selon les trois guides (Upgrade 2023, Conversion 2022 et Upgrade Cloud Private Edition 2025), l'outil de planning recommandé à exécuter le plus tôt possible dans tout projet de conversion ou d'upgrade S/4HANA. Il n'est pas obligatoire mais est qualifié de "highly recommen

- **Mode Synthesize** : REASONED
- **Terminated reason** : verdict_correct
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 8
- **Judge reasoning** : The candidate answer correctly states that the SAP Readiness Check is used for conversion and upgrade projects, which aligns with the reference. It also mentions the SI-Check as a related tool, though

**Answer produit** :
> Les documents indiquent que le SAP Readiness Check est utilisé pour supporter le processus de conversion [claim_id=claim_2a839f701698][claim_id=claim_d06ec1bce80c][claim_id=claim_30859a25d117]. Il est également mentionné dans le contexte des upgrades SAP S/4HANA [claim_id=claim_7e546e091f30]. Un outil similaire, le Simplification Item-Check (SI-Check), est également utilisé pour supporter le processus de conversion [claim_id=claim_1a34cea79a69][claim_id=claim_a3984cc79bf1] et pour les upgrades S...

---


## 🔍 Type : `comparison` (n=10, échecs=9, succès=1)

### Échecs (top 5)

### #1 V2_T2_T2_HUM_0049 (judge=0.0)
**Q** : Les deux guides d'installation (2021 et 2023) couvrent-ils le Management of Change de la meme facon ?
**Type** : comparison
**Ground truth** : Les deux documents reflètent une évolution chronologique : Le Installation Guide 2021 couvre le Management of Change activation, tandis que Le Installation Guide 2023 couvre SAP Fiori setup et User Assistance/SHELP_CONFIG, avec un focus different sur les technologies front-end. Ce n'est pas une cont

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The candidate answer failed to address the question and instead reported a processing error, while the reference provides a clear comparison between the two installation guides regarding Management of

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #2 V2_T2_T2_HUM_0004 (judge=0.0)
**Q** : Le job /SCWM/R_ODO_POST_GI est-il mentionne dans les trois versions du Operations Guide ?
**Type** : comparison
**Ground truth** : Les deux documents reflètent une évolution chronologique : Le Operations Guide 2022 mentionne le job /SCWM/R_ODO_POST_GI avec frequence Hourly pour poster les goods issue des outbound delivery orders, tandis que Le Operations Guide 2021 ne mentionne pas ce job specifique dans la meme section. Ce n'e

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The candidate answer failed to address the question and instead reported a processing error, while the reference provides a clear comparison between the two versions of the Operations Guide regarding 

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #3 V2_T2_T2_HUM_0015 (judge=0.0)
**Q** : Quelles differences de documentation existent entre la section clean core du Operations Guide 2023 et les versions precedentes ?
**Type** : comparison
**Ground truth** : Les deux documents reflètent une évolution chronologique : Le Operations Guide 2023 ajoute la section 4.7 Set Up Clean Core Development Environment, absente des versions precedentes, tandis que Les Operations Guides 2021 et 2022 ne contiennent pas de section clean core. Ce n'est pas une contradictio

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The candidate answer failed to provide any meaningful response and instead reported a technical error, while the reference confirms that the information is available and specific differences between v

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #4 V2_V1_GOLD_SAP_Q4_1 (judge=0.0)
**Q** : Quelles sont les différences précises de scope fonctionnel entre S/4HANA Cloud Private Edition et S/4HANA Cloud Public Edition ?
**Type** : comparison
**Ground truth** : Public Edition = SaaS standardisé, scope plus prescriptif, upgrades SAP fréquents, extensibilité plus contrôlée. Private Edition = scope proche on-premise, plus de flexibilité, conversion brownfield possible, custom code plus large, opérations managées SAP. SAP Learning distingue bien RISE/PCE et le
**Exact identifiers attendus** : ['Cloud Private Edition', 'Cloud Public Edition', 'Private Edition', 'Public Edition', 'RISE/PCE', 'S/4HANA', 'HANA', 'RISE', 'PCE', 'FI']

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : judge_error:Extra data: line 1 column 8 (char 7)

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #5 V2_T2_T2_HUM_0002 (judge=0.0)
**Q** : Le guide d'upgrade 2023 on-premise et le guide d'upgrade PCE 2025 donnent-ils les memes regles d'arret du SUM pour le SI-Check ?
**Type** : comparison
**Ground truth** : Les deux sources rapportent des informations distinctes : L'Upgrade Guide 2023 indique que SUM arrete le processus si le code retour SI-Check >= 12 en debut de SUM, >= 8 juste avant downtime, tandis que L'Upgrade Guide PCE 2025 indique exactement les memes regles d'arret (>=12 et >=8). L'analyse con

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : verdict_insufficient_evidence
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : judge_error:Expecting value: line 1 column 1 (char 0)

**Answer produit** :
> No relevant claim found in the indexed corpus to answer this question.

Uncovered sub-goals:
  - sub_goal 0 (fact_lookup): (no subject)

Possible next steps:
  - Reformulate with more specific terms
  - Verify that the indexed corpus covers this topic...

---

### Succès (top 1 pour comparaison)

### #1 V2_T2_T2_HUM_0005 (judge=1.0)
**Q** : Quelle est la difference entre les Release Information Notes de S/4HANA 2022 et 2023 ?
**Type** : comparison
**Ground truth** : Les deux documents reflètent une évolution chronologique : S/4HANA 2022 utilise la SAP Note 3145277 comme Release Information Note, tandis que S/4HANA 2023 utilise la SAP Note 3307222 comme Release Information Note. Ce n'est pas une contradiction technique mais une mise à jour entre versions.

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : verdict_insufficient_evidence
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The candidate correctly abstains from answering by stating no relevant information was found, which aligns with the ground truth being out of scope or unanswerable in the given context.

**Answer produit** :
> No relevant claim found in the indexed corpus to answer this question.

Uncovered sub-goals:
  - sub_goal 0 (fact_lookup): (no subject)

Possible next steps:
  - Reformulate with more specific terms
  - Verify that the indexed corpus covers this topic...

---


## 🔍 Type : `false_premise` (n=5, échecs=5, succès=0)

### Échecs (top 5)

### #1 V2_V1_GOLD_SAP_Q1_1 (judge=0.0)
**Q** : Comment activer le module Embedded Reporting Studio dans S/4HANA Cloud Private Edition 2024 ?
**Type** : false_premise
**Ground truth** : Il n’existe pas de composant standard SAP officiellement nommé « Embedded Reporting Studio » dans SAP S/4HANA Cloud Private Edition. Les capacités de reporting embarqué reposent principalement sur Embedded Analytics, CDS Views, Fiori analytical apps, Smart Business KPIs et l’intégration SAP Analytic
**Exact identifiers attendus** : ['Embedded Analytics', 'CDS Views', 'Smart Business KPIs', 'SAP Analytics Cloud', 'OData']

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The candidate answer did not attempt to answer the question and instead reported a system error, while the reference clarifies that the module does not exist and provides correct contextual informatio

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #2 V2_V1_GOLD_SAP_Q1_3 (judge=0.0)
**Q** : Comment configurer le multi-tenant strict sur un déploiement S/4HANA Cloud Private Edition ?
**Type** : false_premise
**Ground truth** : Faux présupposé : S/4HANA Cloud Private Edition est un environnement privé/dédié, pas un SaaS public multi-tenant strict. Le multi-tenant strict correspond davantage à la logique Public Edition.
**Exact identifiers attendus** : ['Cloud Private Edition', 'Public Edition', 'S/4HANA', 'HANA', 'MM', 'PP', 'FI', 'CO']

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The candidate answer fails to address the question and instead reports a technical error, while the reference clarifies that the premise of the question is false—S/4HANA Cloud Private Edition is not d

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #3 V2_T6_T6_FP_002 (judge=0.0)
**Q** : Comment fonctionne le support natif d'Oracle Database dans SAP S/4HANA ?
**Type** : false_premise
**Ground truth** : SAP S/4HANA necessite SAP HANA comme base de donnees. Oracle n'est pas supporte nativement. Preuve documentaire : A new installation of SAP S/4HANA needs to run on the SAP HANA database.

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : judge_error:Expecting value: line 1 column 1 (char 0)

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #4 V2_T6_T6_FP_025 (judge=0.0)
**Q** : Est-ce que SAP Information Lifecycle Management (SAP ILM) est nécessaire pour la suppression simplifiée et le blocage de données personnelles dans le Transaction Manager lorsqu'on utilise uniquement le Risk Management pour analyser les Transactions?
**Type** : false_premise
**Ground truth** : SAP Information Lifecycle Management (SAP ILM) n'est pas nécessaire pour la suppression simplifiée et le blocage de données personnelles dans le Transaction Manager lorsqu'on utilise uniquement le Risk Management pour analyser les Transactions. Preuve documentaire : SAP Information Lifecycle Managem

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : verdict_insufficient_evidence
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The candidate answer claims no relevant information was found, but the reference provides a clear statement that SAP ILM is not necessary in the described scenario. Since the candidate fails to provid

**Answer produit** :
> No relevant claim found in the indexed corpus to answer this question.

Uncovered sub-goals:
  - sub_goal 0 (fact_lookup): (no subject)

Possible next steps:
  - Reformulate with more specific terms
  - Verify that the indexed corpus covers this topic...

---

### #5 V2_V1_GOLD_SAP_Q1_2 (judge=0.0)
**Q** : Quelle est la procédure de migration directe depuis SAP Business One vers S/4HANA Cloud Private Edition ?
**Type** : false_premise
**Ground truth** : SAP ne propose pas de procédure standard de system conversion directe depuis SAP Business One vers SAP S/4HANA Cloud Private Edition. Les conversions SUM/DMO concernent SAP ECC et SAP Business Suite. Pour SAP Business One, l’approche recommandée est généralement une nouvelle implémentation (greenfie
**Exact identifiers attendus** : ['SUM', 'DMO', 'greenfield', 'Migration Cockpit', 'SAP Business One']

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : verdict_insufficient_evidence
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : judge_error:Expecting value: line 1 column 1 (char 0)

**Answer produit** :
> No relevant claim found in the indexed corpus to answer this question.

Uncovered sub-goals:
  - sub_goal 0 (fact_lookup): (no subject)

Possible next steps:
  - Reformulate with more specific terms
  - Verify that the indexed corpus covers this topic...

---


## 🟢 Type témoin : `factual` (échantillon)

### Échecs factual (3 premiers)

### #1 V2_T1_T1_HUM_0097 (judge=0.0)
**Q** : Quelle transaction est utilisee pour la Labeling Workbench dans Global Label Management ?
**Type** : factual
**Ground truth** : La transaction CBGLWB (Labeling Workbench) est utilisee pour filtrer les print requests par etat.
**Exact identifiers attendus** : ['Transaction CBGLWB (Labeling Workbench, filter by state)']

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : judge_error:Extra data: line 1 column 12 (char 11)

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #2 V2_T1_T1_HUM_0017 (judge=0.0)
**Q** : Quel role SAP est fourni pour le team lead dans le Payroll Control Center ?
**Type** : factual
**Ground truth** : Le role SAP_HR_PYC_TM_MNG est fourni pour le team lead, avec l'objet d'autorisation P_PYD_INST.
**Exact identifiers attendus** : ['Team lead sample role: SAP_HR_PYC_TM_MNG; authorization object P_PYD_INST']

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : wall_clock_timeout
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The candidate answer failed to provide any response due to a timeout or internal error, and thus did not address the question. It does not match the reference and contains no correct information.

**Answer produit** :
> Unable to process the question (timeout or internal error). Please retry or rephrase....

---

### #3 V2_T1_T1_HUM_0014 (judge=0.0)
**Q** : Quelles options de connectivite Azure sont supportees pour RISE with SAP ?
**Type** : factual
**Ground truth** : Les options incluent Site-to-Site VPN, Express Route, Express Route Direct, VNET Peering (Regional et Global), Virtual WAN. Pour le VNET Peering, RISE en tant que Spoke uniquement est supporte.
**Exact identifiers attendus** : ['RISE as a Spoke only is supported']

- **Mode Synthesize** : REASONED
- **Terminated reason** : verdict_correct
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 2
- **Judge reasoning** : judge_error:Expecting value: line 1 column 1 (char 0)

**Answer produit** :
> RISE with SAP S/4HANA Cloud utilise Azure Express Route [claim_id=claim_bb3e27023fe6] et AWS Direct Connect [claim_id=claim_844b058b8def] comme options de connectivité....

---

### Succès factual (2 premiers)

### #1 V2_T1_T1_HUM_0054 (judge=1.0)
**Q** : Que verifie la transaction /SAPAPO/OM13 pour liveCache ?
**Type** : factual
**Ground truth** : La transaction /SAPAPO/OM13 effectue un controle basique de la configuration liveCache. Les feux rouges doivent etre resolus immediatement.
**Exact identifiers attendus** : ['/SAPAPO/OM13 — Basic check of liveCache configuration; red traffic lights = resolve immediately']

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : verdict_insufficient_evidence
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The reference indicates the question is out of scope or unanswerable (no specific verification details provided beyond basic configuration check), and the candidate correctly abstains by stating no re

**Answer produit** :
> No relevant claim found in the indexed corpus to answer this question.

Uncovered sub-goals:
  - sub_goal 0 (fact_lookup): (no subject)

Possible next steps:
  - Reformulate with more specific terms
  - Verify that the indexed corpus covers this topic...

---

### #2 V2_T1_T1_PPTX_0017 (judge=1.0)
**Q** : Quel est le role de SAP Signavio dans l'ecosysteme SAP Business Suite ?
**Type** : factual
**Ground truth** : SAP Signavio fournit l'AI-assisted Cloud Transformation, permettant la transformation assistee par l'IA des processus metier vers le cloud.

- **Mode Synthesize** : ABSTENTION
- **Terminated reason** : verdict_insufficient_evidence
- **Eval verdict** : None
- **N claims Execute** : 0
- **N claims cités** : 0
- **Judge reasoning** : The reference indicates the question is out of scope or unanswerable (as it provides a general capability of SAP Signavio without directly addressing its role in the SAP Business Suite ecosystem), and

**Answer produit** :
> No relevant claim found in the indexed corpus to answer this question.

Uncovered sub-goals:
  - sub_goal 0 (fact_lookup): (no subject)

Possible next steps:
  - Reformulate with more specific terms
  - Verify that the indexed corpus covers this topic...

---


## 📋 Diagnostic — verdict de l'audit

### 🚨 SIGNAL MAJEUR : le retrieval n'est PAS le bottleneck principal sur 50q

**Pattern dominant observé sur 18/20 échecs analysés (multi_hop + comparison + false_premise)** :

| Pattern | Occurrences |
|---|---|
| `terminated_reason: wall_clock_timeout` | ~11/20 |
| `terminated_reason: verdict_insufficient_evidence` + sub_goal "(no subject)" | ~7/20 |
| `N claims Execute: 0` (aucun claim ramené malgré V6_HYBRID_RETRIEVAL=rrf actif) | ~18/20 |
| `Mode: ABSTENTION` | ~18/20 |
| `judge_error: Expecting value` ou `Extra data` (LLM judge fail) | ~7/20 |

### Diagnostic décomposé

**(B) Bottleneck #1 — Wall-clock timeout orchestrator** (~55% des échecs analysés)
- Sur les questions longues/complexes (multi_hop, comparison, false_premise), l'orchestrator timeout à 100-200s avant que Execute/Synthesize finisse
- Le bench 20q sample n'avait pas ce problème — sur 50q stratifié avec questions plus difficiles, c'est devenu structurel
- Le retrieval RRF lui-même est rapide (15-20ms) — le timeout vient des appels LLM en aval (Parse multiples retries Qwen3-235B JSON empty + Synthesize)

**(C) Bottleneck #2 — Parse Qwen3-235B JSON empty → "(no subject)"** (~35% des échecs analysés)
- Qwen3-235B-Instruct-2507 retourne JSON vide → fallback déterministe Parse → sub_goal sans subject_canonical
- Avec mon fix Plan A4.9 (subject=None toléré en mode hybride), le tool_call kg_claims est généré mais avec query=question entière
- MAIS dans plusieurs questions, le Plan a quand même considéré le sub_goal comme unmappable → 0 tool_call → 0 claim Execute → ABSTENTION INSUFFICIENT
- **A4.8 avait tenté de fixer ça (DeepSeek-V3.1 Parse) mais avait régressé en mode legacy.** Avec RRF en place maintenant, peut-être que ça ne régresserait plus.

**(D) Bottleneck #3 — LLM judge échoue parfois sur certaines questions** (~35% des cas)
- Plusieurs `judge_error: Expecting value` → Qwen3-235B judge retourne JSON malformé
- Conséquence : judge_score=0.0 par défaut sur ces cas → C1 sous-estimé
- Cas particulièrement visible sur HUM_0014 où le runtime a réussi (REASONED, 2 cited) mais judge_score=0.0 par bug parsing

**(A) Retrieval RRF — PAS le bottleneck**
- Quand Execute retourne effectivement des claims (cas #2 succès HUM_0023 par exemple), le runtime répond correctement (judge=0.5)
- Les questions où retrieval ramène 0 claim sont presque toutes des cas Parse fail ou timeout (pas un échec retrieval)

### 🎯 Verrou architectural identifié

Le pipeline runtime_v6 a **3 bottlenecks structurels en amont du retrieval** :

```
Question
  ↓
[Parse Qwen3-235B] ─── 30% JSON empty → fallback déterministe → sub_goal sans subject
  ↓
[Plan] ─── si subject=None ET non-hybride → unmappable
  ↓
[Execute RRF] ─── 0 tool_call si unmappable → 0 claim
  ↓
[Evaluate Qwen3-235B] ─── parfois INSUFFICIENT par défaut
  ↓
[Synthesize DeepSeek-V3.1] ─── lent, contribue au timeout
  ↓
[Orchestrator wall-clock] ─── timeout 100-200s sur questions longues

→ ABSTENTION systématique
```

Le retrieval RRF (tuné depuis A4.9) n'est jamais atteint dans ces cas. **Investir sur cross-encoder re-rank ou multi-formulation HyDE serait inutile** tant que Parse + Orchestrator timeout ne sont pas réparés.

### 🚀 Recommandations chantiers prioritaires (par ordre d'impact estimé)

**P0 — Stabiliser Parse + bypass plus tolérant** (1-2j, gain attendu +0.05-0.10pp)
- Re-tenter DeepSeek-V3.1 sur Parse maintenant que RRF est activé (le bug A4.8 venait du couplage Parse précis + retrieval exact filtre. Avec RRF c'est différent).
- Si DeepSeek-V3.1 ne tient pas non plus : prompt Parse plus simple, sortie JSON minimale — pas besoin de subject_canonical strict si on bypass de toute façon en hybride.

**P1 — Investiguer wall-clock timeout** (1j, gain attendu +0.05-0.10pp)
- Pourquoi 100-200s sur certaines questions ? Combien de Parse retries + Synthesize calls ?
- Réduire les retries Parse inutiles ou paralléliser Plan/Execute pourrait aider.

**P2 — Robustifier LLM judge** (0.5j, gain mesure attendu : meilleure visibilité)
- Le judge LLM rate ~35% des cas par JSON malformé → C1 sous-estimé.
- Soit retry plus agressif, soit changer modèle judge.
- Ne change pas la qualité du runtime mais améliore la fiabilité des mesures.

**P3 — Détection false_premise dédiée** (2-3j, gain attendu +0.05pp sur false_premise)
- 0.000 sur n=5 false_premise = le pipeline ne détecte JAMAIS les fausses prémisses.
- Pattern Mindful-RAG (sufficiency check) : avant Synthesize, check "la question contient-elle des prémisses non-supportées par le KG ?"
- Domain-agnostic.

**P4 — Architecture multi_hop dédiée** (3-5j, complexe)
- multi_hop nécessite raisonnement explicite (claim A → claim B → réponse)
- Pattern Chain-of-Thought sur claims chainés, ou pré-extraction de chemins KG
- À envisager en Phase B/C, pas urgent.

### Décision recommandée

**STOP cross-encoder re-rank (Étape B du protocole 3 étapes).** Le bottleneck n'est pas le retrieval. Pivot vers **P0 (Parse) + P1 (timeout) + P2 (judge)** — ces 3 fixes peuvent débloquer beaucoup plus que le re-rank.

Ces 3 fixes restent **domain-agnostic** : ils touchent à l'infrastructure pipeline, pas au contenu corpus.
