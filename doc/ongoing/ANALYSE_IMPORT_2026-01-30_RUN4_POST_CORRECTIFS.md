# Analyse Import Run 4 — Post-Correctifs no_verb + Calibration + Langue

**Date :** 2026-01-30
**Document :** RISE with SAP Cloud ERP Private — Security (PDF, 447 pages, EN)
**Pipeline :** OSMOSE Stratified V2 (Pass 0.9 + Pass 1 + Pass 2)
**Correctifs appliqués :** Issue 1 (C1 triggers vs original), Issue 2 (calibration YAML), Issue 3 (langue EN), no_verb désactivé, PROCEDURAL→CONDITIONAL

---

## 1. Métriques Globales

| Métrique | Run 2 (baseline) | Run 3 (no_verb seul) | **Run 4 (complet)** |
|----------|-----------------|---------------------|---------------------|
| Informations | 119 | 233 | **233** |
| Rejected | 213 | 73 | **66** |
| Abstained | 70 | 168 | **145** |
| Thèmes | 19 | 54 | **26** |
| Concepts (métier) | 60 | 62 | **67** |
| SINK | 32/119 (27%) | 107/233 (46%) | **41/233 (18%)** |
| Max concept métier | "Security Architecture" 29 (24%) | 11 (5%) | **"Technical Organisational Measures" 24 (10%)** |
| Calibration | AUTO (spread=0.084) | fallback (spread=0.050) | **AUTO (spread=0.085)** |
| Liens rerank | 152 | 62 | **229** |
| Langue thèmes | FR | FR | **EN** |
| Concepts vides | 42/60 (70%) | ? | **29/67 (43%)** |
| Pass 2 (relations) | crash (0) | crash (0) | **crash (0)** |

### Verdict global
- **Informations ×2** par rapport au baseline (119 → 233)
- **SINK = 18%** — dans la cible 15-30%
- **Calibration AUTO** — plus de fallback
- **Thèmes en anglais** — cohérents avec le document
- **43% concepts vides** — amélioré (70% → 43%) mais encore élevé
- **Pass 2 toujours crashé** — 0 relations inter-concepts

---

## 2. Sujet Détecté

| Champ | Valeur |
|-------|--------|
| Nom | SAP Cloud ERP Private Deployment |
| Description | Describes the deployment models and shared security responsibility for SAP Cloud ERP Private. |
| Structure | CENTRAL |
| Langue | en |

---

## 3. Thèmes (26 total)

### 3.1 Thèmes avec concepts (17 thèmes)

| Thème | Concepts | Concepts peuplés | Concepts vides |
|-------|----------|-----------------|----------------|
| Shared Security Responsibility | 8 | 4 | 4 |
| Customer Account Isolation | 7 | 2 | 5 |
| Secure Admin Access | 6 | 5 | 1 |
| SAP Managed Services | 5 | 4 | 1 |
| Secure Connections | 5 | 3 | 2 |
| Technical Basis | 5 | 3 | 2 |
| Audit and Compliance | 5 | 2 | 3 |
| Deployment Models | 4 (dont SINK) | 2 + SINK | 1 |
| Access to Customer Data | 4 | 3 | 1 |
| Infrastructure Management | 4 | 4 | 0 |
| Basic Technical Operations | 4 | 1 | 3 |
| Supported Hyperscalers | 3 | 1 | 2 |
| Data Protection | 2 | 1 | 1 |
| Application Stack | 2 | 2 | 0 |
| Secure KMS Configuration | 2 | 1 | 1 |
| Service Management | 1 | 0 | 1 |
| Database Management | 1 | 0 | 1 |

### 3.2 Thèmes VIDES (9 thèmes — 0 concepts)

| Thème vide |
|------------|
| Centralized API Logging |
| Change Control |
| Cloud Management Plane Security |
| Customer FAQ |
| Network Access Control |
| Overview of Services |
| Secure Infrastructure as a Code |
| Security Assurance |
| Security Operations |

**Observation :** 9/26 thèmes (35%) n'ont aucun concept rattaché. Ce sont des thèmes sémantiquement pertinents (Security Operations, Change Control, Network Access Control) mais le LLM Pass 1.2 n'a pas généré de concepts pour eux, ou les concepts ont été filtrés par la frugalité (153 → 60).

---

## 4. Concepts — Top 20 par nombre d'informations

| # | Concept | Rôle | Infos | Thème |
|---|---------|------|-------|-------|
| 1 | **Assertions non classées (SINK)** | SINK | **41** | Deployment Models |
| 2 | Technical Organisational Measures | STANDARD | 24 | Basic Technical Operations |
| 3 | Incident Management | CONTEXTUAL | 15 | Shared Security Responsibility |
| 4 | Account Management | STANDARD | 13 | Infrastructure Management |
| 5 | Isolated Network Environments | CONTEXTUAL | 11 | Customer Account Isolation |
| 6 | TLS Encryption Requirement | STANDARD | 10 | Secure Connections |
| 7 | Personal Information Protection Law | STANDARD | 10 | Data Protection |
| 8 | Incremental Backups | STANDARD | 10 | Technical Basis |
| 9 | IaaS Provider | CENTRAL | 10 | Deployment Models |
| 10 | Operational Security | CONTEXTUAL | 10 | Shared Security Responsibility |
| 11 | SAP Managed Security Operations | STANDARD | 8 | SAP Managed Services |
| 12 | Security Use Cases | CONTEXTUAL | 7 | Shared Security Responsibility |
| 13 | Compliance Scans | STANDARD | 6 | Audit and Compliance |
| 14 | Web Application Firewall | STANDARD | 5 | Secure Admin Access |
| 15 | Application Processing | STANDARD | 5 | Application Stack |
| 16 | Patch Management | STANDARD | 4 | Infrastructure Management |
| 17 | SAP Cloud ERP Private Deployment | CENTRAL | 4 | Deployment Models |
| 18 | Dedicated Account/Subscription/Projects | CONTEXTUAL | 4 | Customer Account Isolation |
| 19 | SAP Vulnerability Advisory Services | STANDARD | 3 | SAP Managed Services |
| 20 | SAP Managed Patch Management | STANDARD | 3 | SAP Managed Services |

### Distribution par rôle (concepts métier, hors SINK)

| Rôle | Nombre | % |
|------|--------|---|
| STANDARD | 44 | 66% |
| CONTEXTUAL | 19 | 28% |
| CENTRAL | 4 | 6% |

---

## 5. Concepts VIDES (29/67 = 43%)

### 5.1 Concepts vides CENTRAL (1)
- Customer Gateway Server

### 5.2 Concepts vides CONTEXTUAL (12)
- Application Security Audit Logging
- Azure VNET Peering
- Certification for Information Security Management Systems
- Customer Account Isolation
- Customer Integration Server
- Customer Managed Configuration
- Hyperscaler Platform
- Logical Separation of Customer Environment
- Physical Data Center Security
- RFC1918 IP Addresses Isolation
- SAP Managed Technical Stack
- Shared Security Responsibility

### 5.3 Concepts vides STANDARD (16)
- Basic DDoS Protection
- Cloud Foundry Runtime Support
- Compliance with Data Privacy Regulations
- Compliance with GDPR
- DR Drill Scheduling
- Data Controller Notification
- Database log file backup
- Full Backup
- Fully encrypted VPN tunnels
- Insecure Legacy Protocol Disabling
- Internal Use Only
- Patch and Upgrade Execution
- Secure Admin Connectivity
- Security Operations Playbooks
- Security and Compliance Reports
- Technical Managed Services

**Observation :** Certains concepts vides sont clairement présents dans le document (GDPR, DDoS Protection, VPN tunnels, DR Drill). Cela pointe soit vers un problème de linking (l'assertion existe mais n'est pas rattachée), soit un problème d'extraction (l'assertion n'a pas été extraite pour cette zone du document).

---

## 6. SINK — Analyse détaillée (41 assertions, 18%)

### 6.1 Exemples d'assertions SINK (top par longueur)

| # | Texte (tronqué) | Diagnostic |
|---|-----------------|-----------|
| 1 | "Browser requests live data based on meta definition. Browser will now directly contact the SAP HANA database..." (337 chars) | PROCEDURAL technique — devrait aller vers un concept SAP HANA ou Data Access |
| 2 | "They collect and log relevant events and activities at the operating system level, including information about running or executed processes..." | DEFINITIONAL sécurité — devrait aller vers Security Monitoring |
| 3 | "The backup storage of 1 month for productive systems and 14 days for nonproductive systems..." | FACTUAL backup — devrait aller vers Incremental Backups ou Full Backup |
| 4 | "Readers are cautioned not to place undue reliance on these forward-looking statements..." | META disclaimer — devrait être REJECTED |
| 5 | "ISAE3402 SOC 1 Type II, ISAE 3000 SOC2 Type II, ISO 27001:2013..." | FACTUAL compliance — devrait aller vers Compliance Scans |
| 6 | "SAP Global Security Policies and SAP Enterprise Cloud Services (ECS) Policies are applies through secure default deployment..." | FACTUAL — devrait aller vers Operational Security |
| 7 | "Encryption root keys stored in the Instance Secure Store in File System (SSFS) within HANA DB" | FACTUAL crypto — devrait aller vers Hardware Security Module |
| 8 | "SAP Internal Cyber Security Centre, dedicated to identifying & mitigating Cyber Security risks" | DEFINITIONAL — devrait aller vers SAP Managed Security Operations |
| 9 | "SAP Consulting Deliver a commercial offering assisting with securing & protecting your SAP landscape" | FACTUAL services — discutable |
| 10 | "SAP reserves the right to apply critical application and operating system security patches." | PRESCRIPTIVE — devrait aller vers Patch Management |
| 11 | "X.509 certificate token is used for authenticating the SAP GUI user to the ABAP system" | FACTUAL auth — devrait aller vers Single Sign-On with X.509 |
| 12 | "Only use an in-date presentation downloaded from Cyber Security Hub - Golden Assets" | META instruction — devrait être REJECTED |
| 13 | "SAP Identity Authentication Service Basic SSO included in SAP S/4HANA Cloud" | FACTUAL — devrait aller vers Identity and Access Controls |
| 14 | "SAP conducts periodic security testing to identify vulnerabilities" | FACTUAL — devrait aller vers Compliance Scans |
| 15 | "© 2023 SAP SE or an SAP affiliate company. All rights reserved." | META copyright — devrait être REJECTED |

### 6.2 Diagnostic SINK

| Catégorie | Estimation | Commentaire |
|-----------|-----------|-------------|
| Linking échoué (concept existe mais pas matché) | ~20 | Backups, Patch, Compliance, Auth → concepts existent |
| Thème manquant (pas de concept cible) | ~10 | Security Operations, Change Control → thèmes vides |
| META/bruit (devrait être REJECTED) | ~5 | Copyright, disclaimers, instructions Golden Assets |
| Discutable | ~6 | Services SAP commerciaux, forward-looking statements |

---

## 7. Pipeline d'assertions — Funnel complet

```
DocItems totaux            : 6 743
  → Filtrés (trop courts)  : 5 046 (75%)
  → Indexés                : 1 697 (25%)
  → Unités extraites       : 2 091

Assertions LLM extraites   :   390
  → REJECTED (policy)      :    66 (17%)
  → ABSTAINED              :   145 (37%)
     dont no_concept_match  :   127
     dont cross_docitem     :    18
  → PROMOTED               :   179 (46%)

Liens sémantiques bruts     :   304+ (Pass 1.4 + saturation)
  → Liens après rerank      :   229 + 75 = 304
  → Informations créées     :   233
     dont SINK              :    41 (18%)
     dont métier            :   192 (82%)
```

### Calibration Rerank

| Phase | Mode | Spread | Q10 | Q50 | Q75 | Liens promus |
|-------|------|--------|-----|-----|-----|-------------|
| Pass 1.4 (principal) | AUTO | 0.085 | 0.600 | 0.650 | 0.685 | 229 (SINK=36, métier=193) |
| Saturation (iter 1) | AUTO tight_spread | 0.060 | 0.600 | 0.645 | 0.660 | 75 (SINK=13, métier=62) |

Qualité des liens :
- **46% avec signal** (lex ou sem) sur le rerank principal — bon niveau
- **tight_spread** activé sur la saturation (spread < 0.08) — band3 = Q50 au lieu de Q75

---

## 8. Rejections — Détail (66 total)

### Par type d'assertion rejetée

| Type | Nombre | % |
|------|--------|---|
| FACTUAL | 26 | 39% |
| CONDITIONAL | 17 | 26% |
| DEFINITIONAL | 15 | 23% |
| PRESCRIPTIVE | 6 | 9% |
| PERMISSIVE | 2 | 3% |

### Échantillons de rejetés (top 10)

| # | Type | Texte (tronqué) | Diagnostic |
|---|------|-----------------|-----------|
| 1 | CONDITIONAL | "Does it have E-W and N-S segregation of traffic between subnets..." | Question FAQ → rejet correct (meta:question) |
| 2 | CONDITIONAL | "What are the shared services involved in managing RISE..." | Question FAQ → rejet correct |
| 3 | CONDITIONAL | "Is your SOC 24x7, and do you have playbooks..." | Question FAQ → rejet correct |
| 4 | CONDITIONAL | "Is it necessary for SAP Development, QA, and Production environments..." | Question FAQ → rejet correct |
| 5 | FACTUAL | "Note: While the diagram shows AWS setup, this is similar configuration..." | Note de figure → rejet correct |
| 6 | CONDITIONAL | "Will SAP provide a immediate notification..." | Question FAQ → rejet correct |
| 7 | PRESCRIPTIVE | "Requires approval from Cyber Legal via CISA Ticket..." | **Faux négatif possible** — prescriptif utile |
| 8 | PRESCRIPTIVE | "Note: VPCs from customer's own subscription cannot be attached..." | Note technique → discutable |
| 9 | CONDITIONAL | "Can the different Prod and Non-Prod environments be segregated..." | Question FAQ → rejet correct |
| 10 | CONDITIONAL | "Can I use AWS or Azure Private Link..." | Question FAQ → rejet correct |

**Verdict rejections :** Majoritairement correctes. Les questions FAQ (CONDITIONAL) sont bien filtrées. Quelques prescriptifs pourraient être récupérés mais le ratio est acceptable.

---

## 9. Abstentions — Détail (145 total)

| Raison | Nombre | % |
|--------|--------|---|
| no_concept_match | 127 | 88% |
| cross_docitem | 18 | 12% |

### Échantillons no_concept_match (assertions promues mais non liées)

| # | Type | Texte (tronqué) | Concept cible probable |
|---|------|-----------------|----------------------|
| 1 | PROCEDURAL | "Browser requests live data based on meta definition..." | Data Access / SAP HANA |
| 2 | CAUSAL | "SAP establishes separate Customer environments, implements micro segmentation..." | Network Segmentation |
| 3 | PROCEDURAL | "ECS performs comprehensive testing on verifications of patches..." | Patch Management |
| 4 | DEFINITIONAL | "LogServ is an ECS service designed for storing and accessing logs..." | Centralized Logging |
| 5 | FACTUAL | "SAP ensures the usage of an adequate US CERT advisory service..." | Vulnerability Advisory |
| 6 | DEFINITIONAL | "RAVEN is an ECS service that simplifies management of SAP Application Security..." | Security Monitoring |
| 7 | FACTUAL | "You can retain your logs indefinitely..." | Log Retention |
| 8 | DEFINITIONAL | "Virtual network peering creates network connectivity between two virtual networks..." | VPC/VNET Peering |
| 9 | PROCEDURAL | "Continuous 24x7 monitoring of security events..." | Security Operations |

**Observation :** 127 assertions promues par la policy mais non rattachées à aucun concept. Beaucoup pointent vers des thèmes qui existent (Security Operations, Network Access Control) mais n'ont pas de concepts. C'est le **principal gisement d'amélioration** restant.

---

## 10. Informations — Distribution par type

| Type | Nombre | % |
|------|--------|---|
| FACTUAL | 121 | 52% |
| PRESCRIPTIVE | 49 | 21% |
| DEFINITIONAL | 32 | 14% |
| CONDITIONAL | 14 | 6% |
| PROCEDURAL | 9 | 4% |
| PERMISSIVE | 6 | 3% |
| CAUSAL | 2 | 1% |

---

## 11. Concept saturant — "Technical Organisational Measures" (24 infos)

Ce concept aspire 10% des informations. Échantillon :

1. "SAP establishes separate Customer environments, implements micro segmentation..."
2. "If the software is unable to automatically remediate the threat... the infected system is isolated"
3. "This is required by several Compliance Frameworks like PCI DSS, CCSP..."
4. "The regulation applies to SAP customers in India..."
5. "Customers can use the SAP4me Service Request template to request an export..."
6. "In AWS deployment, SAP Cloud ERP Private VPC can be attached to customer provided TGW."
7. "Data Lake platform to support both Customers and SAP for log retention..."
8. "Internet outbound to be routed to customer's landing zone..."
9. "It is allowed to access Fiori applications from customer's mobile devices over Internet."
10. "Customer initiates DR drill by creating service request at least 6 weeks in advance."

**Diagnostic :** Ce concept est un "fourre-tout" pour mesures techniques et organisationnelles. Les assertions 1-2 sont légitimes (micro-segmentation, isolation). Mais les assertions 6-10 (TGW, DR drill, Fiori access, Data Lake) devraient être dans des concepts plus spécifiques. Le nom trop générique ("Technical Organisational Measures") attire des assertions variées.

---

## 12. ThemeLint — 7 thèmes suspects

| Thème suspect | Infos aspirées ailleurs | Keywords déclencheurs |
|---------------|------------------------|----------------------|
| Change Control | 5 | change |
| Service Management | 3 | initiates, DR drill, 6 weeks |
| Cloud Management Plane Security | 33 | cloud, plane |
| Secure Infrastructure as a Code | 11 | infrastructure, secure |
| Network Access Control | 22 | network, access |
| Customer FAQ | 36 | customer |
| Gestion de la sécurité des données en transit | 5 | transit |

**Diagnostic :** Le ThemeLint détecte des thèmes dont les keywords sont trop génériques ("cloud", "customer", "access") et matchent massivement des infos rattachées à d'autres concepts. Ce n'est pas un bug de linking mais un signal de granularité insuffisante des thèmes.

---

## 13. Pass 2 — Relations inter-concepts

**Résultat :** 0 relations (crash JSON parse)
```
[OSMOSE:Pass2] Parse JSON échoué: Expecting value: line 1 column 1 (char 0)
```

Le LLM retourne une réponse vide. Problème indépendant des correctifs Pass 1.

---

## 14. Synthèse des problèmes restants (priorité)

| # | Problème | Impact | Piste |
|---|----------|--------|-------|
| 1 | **127 no_concept_match** (55% des assertions non-SINK non liées) | Infos perdues | Les 9 thèmes vides n'ont pas de concepts → pas de cible de linking |
| 2 | **Frugalité trop agressive** (153 → 60 concepts) | 93 concepts refusés → thèmes vides | Augmenter max_concepts ou lever la frugalité pour les thèmes sans concepts |
| 3 | **29 concepts vides** (43%) | Graphe incomplet | Certains concepts (GDPR, DDoS, VPN) existent dans le doc mais pas d'assertions matchées |
| 4 | **"Technical Organisational Measures" saturant** (24 infos, 10%) | Concentration | Nom trop générique → splitting ou triggers plus restrictifs |
| 5 | **Pass 2 crash** (0 relations) | Graphe plat | Réponse LLM vide → debug prompt/modèle Pass 2 |
| 6 | **~5 assertions META dans SINK** | Bruit | Copyright, disclaimers non filtrés par meta_patterns |

---

## 15. Évolution historique

```
Run 1 (pre-correctifs)     :  89 infos, SINK 50%+, calibration fallback, FR
Run 2 (Issue 1 only)       : 119 infos, SINK 27%, calibration AUTO, FR, 70% concepts vides
Run 3 (+ no_verb)          : 233 infos, SINK 46%, calibration FALLBACK, FR, concepts vides ?
Run 4 (+ calibration + EN) : 233 infos, SINK 18%, calibration AUTO, EN, 43% concepts vides
```

**Gain total Run 1 → Run 4 :**
- Informations : ×2.6 (89 → 233)
- SINK : 50% → 18%
- Langue : FR → EN (cohérent avec le document)
- Thèmes : 19 (FR, pauvres) → 26 (EN, structurés)
- Calibration : fallback → AUTO stable
