# Rapport Circonstancié — Problème de Linking Information→Concept

**Date :** 2026-02-02
**Branche :** `feat/pass1-hybrid-extract-then-structure`
**Contexte :** Pipeline OSMOSE V2.1, import de 2 documents PPTX SAP sécurité
**Objectif :** Documenter le problème de rattachement incorrect d'informations aux concepts pour analyse collaborative

---

## 1. Description du Problème

Le pipeline stratifié OSMOSE extrait des assertions depuis des documents, identifie des concepts thématiques, puis **lie chaque assertion à un concept** par raisonnement LLM. Ces assertions liées deviennent des nœuds `Information` dans Neo4j, rattachés aux `Concept` via la relation `HAS_INFORMATION`.

**Le problème central : un grand nombre d'informations sont rattachées à des concepts qui n'ont aucun lien sémantique réel avec elles.**

Cela rend la base de connaissances inutilisable car :
- Les requêtes par concept retournent des informations non pertinentes
- La confiance utilisateur dans les résultats est détruite
- L'accumulation de bruit empêche toute exploitation analytique

---

## 2. Données Analysées

### Documents importés

| Document | doc_id | Nœuds créés |
|----------|--------|-------------|
| RISE with SAP Cloud ERP Private (full) | `020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357` | Document, Subject, 19 Themes, 68 Concepts, 230 Information, 1091 InformationMVP, 1213 AssertionLog |
| SAP S/4HANA 2021 Operations Guide | `014_SAP_S4HANA_2021_Operations_Guide_819d2c07` | Document + 332 VisionObservations seulement (Pass 1/2 n'a produit aucun résultat) |

### Graphe Neo4j actuel

| Label | Count |
|-------|-------|
| AssertionLog | 1213 |
| InformationMVP | 1091 |
| VisionObservation | 332 |
| Information | 230 |
| DocItem | 219 |
| Concept | 68 |
| Theme | 19 |
| Document | 2 |
| Subject | 1 |

---

## 3. Analyse Exhaustive Concept par Concept

Ci-dessous, pour chaque concept ayant des informations rattachées, la liste complète des informations avec évaluation de pertinence.

Légende :
- ✅ **Pertinent** — L'information est bien liée au concept
- ⚠️ **Discutable** — Lien ténu ou trop indirect
- ❌ **Hors-sujet** — Aucun rapport sémantique avec le concept

---

### 3.1 Concept: "Cloud Security Compliance Scanning"

| # | Information | Pertinence |
|---|------------|------------|
| 1 | "SAP S/4HANA cloud is GDPR Ready" | ⚠️ Compliance mais pas scanning |
| 2 | "Reporting on Audit Trail Under Rule 11(g) of Indian Companies Act" | ❌ Réglementation indienne, pas du scanning |
| 3 | "Operating Systems and Database Logs will be available to customer via LogServ." | ❌ Disponibilité de logs, pas de compliance scanning |
| 4 | "LogServ is an ECS service designed for storing and accessing logs..." | ❌ Service de logging, pas de scanning |
| 5 | "HANA Logs HANA Logs BOBJ Logs ABAP Logs JAVA Logs JAVA Logs" | ❌ Liste de types de logs |
| 6 | "RAVEN is an ECS service that simplifies the management of SAP Application Security and Threats..." | ⚠️ Outil sécurité, plus proche mais pas exactement du scanning |
| 7 | "You can retain your logs indefinitely..." | ❌ Rétention de logs |
| 8 | "Backups volumes are (AES256) encrypted." | ❌ Chiffrement de backups |
| 9 | "Annual penetration tests" | ⚠️ Tests de sécurité, pas du compliance scanning |
| 10 | "Overall cloud security is assured via various contracting assurances such as General Terms & Conditions, Data Processing Agreement and Technical & Organizational Measures." | ❌ Assurances contractuelles générales |

**Bilan : 0/10 vraiment pertinent, 3/10 discutables, 7/10 hors-sujet**

---

### 3.2 Concept: "Secure Connectivity"

| # | Information | Pertinence |
|---|------------|------------|
| 1 | "Data in electronic form, once tampered, destroyed, leaked or illegally obtained/used, may endanger national security and public interests." | ❌ Déclaration générale sur la sécurité des données (réglementation chinoise) |
| 2 | "Segregated Network Environment within the Workload domain" | ⚠️ Réseau ségregé, pas de la connectivité |
| 3 | "Short Distance DR vs Long Distance DR" | ❌ Disaster Recovery, pas de la connectivité |
| 4 | "Short Distance (Mixed HA/DR)" | ❌ Haute disponibilité, pas de la connectivité |
| 5 | "Replication within 50 km – Multi Zones (AZ's)" | ❌ Réplication de données |
| 6 | "Replication Over 50 km – Cross Regions" | ❌ Réplication de données |
| 7 | "SAP Secure Login Service for SAP GUI" | ✅ Service de login sécurisé |
| 8 | "Single sign-on based on X.509 certificates" | ⚠️ Authentification, lien indirect |
| 9 | "SAP Identity Authentication Service Basic SSO included in SAP S/4HANA Cloud" | ⚠️ Authentification SSO |

**Bilan : 1/9 pertinent, 3/9 discutables, 5/9 hors-sujet**

---

### 3.3 Concept: "Shared Security Governance"

| # | Information | Pertinence |
|---|------------|------------|
| 1 | "through regular vulnerability advisories from software vendors and NIST, complemented by periodic system scans." | ⚠️ Vulnérabilités, pas de la gouvernance |
| 2 | "Customer initiates DR drill by creating service request at least 6 weeks in advance." | ❌ Procédure de DR drill |
| 3 | "SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY" | ❌ Mention de confidentialité (bruit documentaire) |
| 4 | "Continuous Logging and Monitoring" | ❌ Monitoring, pas gouvernance |
| 5 | "the number of rules will always be limited, and SAP ECS reserves the right to reject requests for an excessively large rule base" | ⚠️ Règle opérationnelle FWaaS |
| 6 | "SAP ECS manage and operate the Firewall" | ❌ Gestion firewall, pas gouvernance |
| 7 | "Failover of SCS/ERS and DB through manually initiated automatically failover procedure." | ❌ Haute disponibilité technique |
| 8 | "The backup storage of 1 month for productive systems and 14 days for nonproductive systems..." | ❌ Politique de backup |
| 9 | "Customer to implement necessary transport layer security for Non-HTTP connections..." | ⚠️ Responsabilité client |
| 10 | "Internet outbound to be routed to customer's landing zone or to a gateway that customer provides." | ⚠️ Routing réseau |
| 11 | "All internet security such as Web Application Firewall are to be managed by the customer in their network." | ⚠️ Responsabilité partagée — le plus pertinent |
| 12 | "All internet accesses must be encrypted in transit (via TLS)" | ❌ Chiffrement en transit |
| 13 | "Securing Data in Transit (Customer Managed Internet Access)" | ⚠️ Titre de section |
| 14 | "All HTTP connections must be secured using Transport Layer Security (TLS) version 1.2 or higher." | ❌ Spécification technique TLS |
| 15 | "Customers can use IPSec based Site-to-Site (S2S) VPN over Internet to connect..." | ❌ Connectivité VPN |
| 16 | "A dedicated private connection with redundancy is recommended for accessing productive workload..." | ❌ Recommandation connectivité |
| 17 | "Only use an in-date presentation downloaded from Cyber Security Hub - Golden Assets" | ❌ Note de version du document (bruit) |

**Bilan : 0/17 vraiment pertinent, 6/17 discutables (lien via "responsabilité partagée"), 11/17 hors-sujet**

---

### 3.4 Concept: "Security Audit Logs"

| # | Information | Pertinence |
|---|------------|------------|
| 1 | "If data is corrupted during backup or any other scenario, is there a data availability SLA?" | ❌ Question sur SLA backup |
| 2 | "If a customer experiences a security incident, are you prepared to provide the customer with the relevant security event logs?" | ✅ Accès aux logs de sécurité |
| 3 | "SOC reports and certifications to provide independent evidence for security..." | ❌ Certifications et rapports |
| 4 | "Option 1: Create a Service Request for patching a single system" | ❌ Procédure de patching |
| 5 | "Use the check boxes and 'Request patching' button..." | ❌ Instruction UI de patching |
| 6 | "the company has used such accounting software for maintaining its books of account which has a feature of recording audit trail..." | ⚠️ Audit trail mais contexte comptable indien |
| 7 | "Amendments to rules relating to maintaining books of accounts in electronic mode" | ❌ Réglementation comptable indienne |
| 8 | "SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY" | ❌ Mention de confidentialité (bruit) |
| 9 | "Database Replication for High Availability and Disaster Recovery" | ❌ Réplication DB |
| 10 | "Defined Policy and Standard Operating Procedures" | ⚠️ Procédures, très vague |
| 11 | "Defined Key Rotation and Destruction processes" | ❌ Gestion de clés |
| 12 | "Secure Software Development Lifecycle" | ❌ SDLC |
| 13 | "Infrastructure as a Code" | ❌ IaC |
| 14 | "Incident Management 24x7 (Prod) Service Request Management..." | ⚠️ Gestion d'incidents, lien indirect |
| 15 | "Secure Infrastructure as a Code" | ❌ IaC |

**Bilan : 1/15 pertinent, 3/15 discutables, 11/15 hors-sujet**

---

### 3.5 Concept: "Penetration Testing"

| # | Information | Pertinence |
|---|------------|------------|
| 1 | "Defines the cloud service specific system availability, uptime, update windows, credits and others" | ❌ SLA/disponibilité |
| 2 | "Perform VAPT for custom applications; customer to provide downtime for infra patching" | ✅ VAPT directement |
| 3 | "Once DR Testing is concluded at the customer, SAP rebuild the DR system and enable the replication..." | ❌ DR testing |
| 4 | "SAP conducts periodic security testing to identify vulnerabilities" | ✅ Tests de sécurité |
| 5 | "Shift Left and Shield Right" | ⚠️ Philosophie sécurité, très vague |

**Bilan : 2/5 pertinents, 1/5 discutable, 2/5 hors-sujet**

---

### 3.6 Concept: "Application Logs"

| # | Information | Pertinence |
|---|------------|------------|
| 1 | "INTERNAL | SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY" | ❌ Bruit documentaire |
| 2 | "© 2023 SAP SE or an SAP affiliate company. All rights reserved." | ❌ Copyright (bruit) |
| 3 | "SAP and its sub processors obligations and restrictions to process Personal Data..." | ❌ Obligations RGPD |
| 4 | "HANA business application logs are out-of-scope for this service." | ✅ Pertinent |
| 5 | "LogServ is an ECS service designed for storing and accessing logs..." | ✅ Pertinent |
| 6 | "Extract embeddings for advanced prompting" | ❌ Totalement hors-sujet (IA/ML) |
| 7 | "Extract application data for model fine-tuning" | ❌ Totalement hors-sujet (IA/ML) |

**Bilan : 2/7 pertinents, 0/7 discutables, 5/7 hors-sujet**

---

### 3.7 Concept: "SAP4me Service Request"

| # | Information | Pertinence |
|---|------------|------------|
| 1 | "Option 2: Create multiple Service requests for patching two or more systems" | ✅ Pertinent |
| 2 | "FWaaS cannot be used to replace the customer's responsibility in this area" | ❌ FWaaS |
| 3 | "FWaaS is also active between the customer's on-premise connection and the landscape" | ❌ FWaaS |
| 4 | "FWaaS is specifically designed to filter traffic within the ECS landscape..." | ❌ FWaaS |
| 5 | "The restore requestor must use the corresponding template and provide the necessary information." | ⚠️ Procédure de restore via service request |

**Bilan : 1/5 pertinent, 1/5 discutable, 3/5 hors-sujet**

---

### 3.8 Concept: "Transit Gateway Integration"

| # | Information | Pertinence |
|---|------------|------------|
| 1 | "Logon to SAP for Me https://me.sap.com/home using your S-user credentials" | ❌ Procédure de connexion portail |
| 2 | "CDC connection to customer network using redundant links to carry all customer and management traffic" | ⚠️ Connectivité réseau, pas TGW |
| 3 | "With Multiple Architecture designs we can Cover below type of Outages" | ❌ Haute disponibilité |
| 4 | "This can be offered based on selected systems/services which would require such access..." | ⚠️ Accès sélectif |
| 5 | "In AWS deployment, SAP Cloud ERP Private VPC can be attached to customer provided Transit Gateway (TGW)." | ✅ Directement TGW |
| 6 | "Attaching Direct Connect or VPN in SAP account to TGW in customer account is not possible." | ✅ Contrainte TGW |
| 7 | "Transit Gateway is region based and hence customer should have a TGW in the same region..." | ✅ Contrainte TGW |
| 8 | "Gateway Subnet is applicable only for Azure." | ⚠️ Réseau Azure, pas TGW |

**Bilan : 3/8 pertinents, 3/8 discutables, 2/8 hors-sujet**

---

### 3.9 Concept: "Shared Security Responsibility Model"

| # | Information | Pertinence |
|---|------------|------------|
| 1 | "Vulnerability arising due to weak configuration and security parameters" | ⚠️ Vulnérabilité config |
| 2 | "If I am running SAP S/4HANA on a Hyperscaler, why is it necessary to perform a lift and shift..." | ❌ Question migration |
| 3 | "SAP has unified the approach for all cloud solutions with the Data Processor Agreement (DPA)" | ⚠️ DPA, lien indirect |
| 4 | "The purpose of Security Patch Management (SPM) is the mitigation of threats and vulnerabilities..." | ❌ Patch management |
| 5 | "Perform VAPT for cloud services; customer to provide downtime for infra patching" | ⚠️ Responsabilité partagée implicite |
| 6 | "SAP's contractual commitment via SAP Personal Data Processing Agreement for Cloud Services" | ⚠️ Engagement contractuel |
| 7 | "After successful authentication, SAP-managed Cloud CA issues an X.509 certificate" | ❌ Authentification technique |
| 8 | "X.509 certificate token is used for authenticating the SAP GUI user to the ABAP system" | ❌ Authentification technique |
| 9 | "SAP assumes no responsibility for errors or omissions in this presentation..." | ❌ Disclaimer juridique (bruit) |

**Bilan : 0/9 vraiment pertinent, 4/9 discutables, 5/9 hors-sujet**

---

### 3.10 Concept: "Assertions non classées" (SINK)

| # | Information (échantillon) | Pertinence |
|---|--------------------------|------------|
| 1 | "solutions are collected, correlated and analysed." | Fragment incomplet |
| 2 | "For HANA DB, 99.7% HANA standby optional for =<6TiB but mandatory for VM >6TiB and Bare Metal." | Info technique valide — aurait dû aller dans un concept HA/DR |
| 3 | "There are two levels of encryption applies to data-at-Rest..." | Info technique valide — aurait dû aller dans "Encrypted Storage" |
| 4 | "China Datacom Corp. (SAP's exclusive Chinese Partner)" | Info factuelle valide — aurait dû aller dans "Hyperscaler China Regions" |
| 5 | "INTERNAL | SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY" | ❌ Bruit documentaire |
| 6 | "© 2023 SAP SE or an SAP affiliate company. All rights reserved." | ❌ Copyright (bruit) |
| 7 | "SAP publishes patches in" | Fragment tronqué |
| 8 | "Golden images are defined and versioned in accordance with the hardening guidelines." | Info valide — aurait dû aller dans "Security Hardened System" |
| 9 | "24x7 (SIEM) Continuous Security" | Fragment — aurait dû aller dans "Security Automation for Detection" |
| 10 | "Secure Cloud Delivery" | Titre de section (bruit) |
| 11 | "Disaster Recovery Plan" | Titre/fragment trop court |
| 12 | "Additional License is required." | Fragment sans contexte |

**Bilan du SINK : mélange de bruit documentaire (copyright, disclaimers, titres) et d'informations valides qui auraient dû être classées dans des concepts existants.**

---

### 3.11 Concepts correctement peuplés (exemples positifs)

**"Secure KMS Configuration Enforced"** — 9 informations, majorité pertinente :
- ✅ "Customer controls creation, use, deletion, rotation of the Master Keys"
- ✅ "Customer can subscribe to SAP Data Custodian KMS to BYOK to encrypt HANA LSS."
- ✅ "Contents of both Secure Stores in the File System (SSFS) are protected by SSFS Master Keys..."
- ✅ "SAP HANA in-memory database uses HANA Volume Encryption to provide 'data-at-rest' encryption..."
- ✅ "Encryption root keys... are stored in the Instance Secure Store in File System (SSFS)..."
- ✅ "Master keys can be changed in regular intervals by request"
- ✅ "Keys are securely backed up as part of the database backup"
- ✅ "The storage used to store data files... are encrypted by default by IaaS provider..."
- ✅ "Secure KMS Configuration Enforced"

**Bilan : 9/9 pertinent** — Ce concept fonctionne car il est **spécifique** et **les mots-clés sont discriminants** (KMS, keys, encryption, SSFS).

**"Customer account isolation"** — 7 informations, majorité pertinente :
- ✅ "Each customer receives their own isolated landscape Virtual Network created"
- ✅ "Each customer is isolated from the SAP Corporate Network"
- ✅ "Azure Storage Account provides a unique namespace to store and access Azure Storage resources securely."
- ✅ "SAP Manages technical stack and customer has no access to Infrastructure OS."
- ⚠️ "Customer must install, own and manage" (×2, fragment sans contexte)

**Bilan : 5/7 pertinent** — Concept spécifique avec vocabulaire discriminant (isolation, isolated, customer, landscape).

**"VPC peering"** — 8 informations :
- ✅ "VPC Peering is used to connect Primary with DR Region."
- ✅ "Virtual network peering creates network connectivity between two virtual networks..."
- ✅ "SAP Solution is deployed across two Availability Zones (AZ) in a single region for HA/DR..."
- ✅ "Application components such as Application Servers and Web Dispatchers are running Active-Active..."
- ✅ "Database is running in Active-Passive mode. Synchronous Database Replication..."
- ⚠️ "This carries all the internal traffic for networked storage..."
- ⚠️ "fastest single connection: 2.5 Gbps 5.0 Gbps..."
- ⚠️ "Implement Network Security controls..."

**Bilan : 5/8 pertinent** — Les infos architecturales sont correctement groupées.

---

## 4. Synthèse Quantitative

| Concept | Total infos | Pertinent | Discutable | Hors-sujet | Taux pertinence |
|---------|-------------|-----------|------------|------------|-----------------|
| Cloud Security Compliance Scanning | 10 | 0 | 3 | 7 | **0%** |
| Secure Connectivity | 9 | 1 | 3 | 5 | **11%** |
| Shared Security Governance | 17 | 0 | 6 | 11 | **0%** |
| Security Audit Logs | 15 | 1 | 3 | 11 | **7%** |
| Penetration Testing | 5 | 2 | 1 | 2 | **40%** |
| Application Logs | 7 | 2 | 0 | 5 | **29%** |
| SAP4me Service Request | 5 | 1 | 1 | 3 | **20%** |
| Transit Gateway Integration | 8 | 3 | 3 | 2 | **38%** |
| Shared Security Responsibility Model | 9 | 0 | 4 | 5 | **0%** |
| Secure KMS Configuration Enforced | 9 | 9 | 0 | 0 | **100%** |
| Customer account isolation | 7 | 5 | 2 | 0 | **71%** |
| VPC peering | 8 | 5 | 3 | 0 | **63%** |

**Pattern clair : Les concepts vagues/larges (governance, compliance, security) attirent du bruit. Les concepts spécifiques avec vocabulaire discriminant (KMS, VPC peering, isolation) fonctionnent bien.**

---

## 5. Architecture du Mécanisme de Linking (Code)

### 5.1 Pipeline Pass 1 — Vue d'ensemble

```
Pass 1.1: Identification des Concepts (concept_identifier.py)
    → Identifie themes/concepts depuis le texte du document

Pass 1.2: Extraction des Assertions (assertion_extractor.py)
    → Extrait assertions brutes du texte

Pass 1.3: Linking Assertion→Concept (assertion_extractor.py)
    → LLM raisonne sur le lien sémantique
    → C3v2: Validation par triggers/gates
    → Rerank "Specificity Wins": Bonus/pénalités
    → _apply_margin_and_topk: Sélection finale

Pass 1.3b: Rescue des assertions SINK (assertion_extractor.py)
    → IDF-weighted lexical rescue pour assertions orphelines

Pass 1.4: Promotion → Information (orchestrator.py)
    → Les assertions liées deviennent des nœuds Information dans Neo4j
```

### 5.2 Étape 1 — Appel LLM (linking sémantique)

**Fichier :** `src/knowbase/stratified/pass1/assertion_extractor.py`, ligne 1459 (`_link_batch`)

Le LLM reçoit :
- Liste d'assertions avec leur texte
- Liste de concepts avec leur nom + description

**Prompt système :**
```
Tu es un expert en raisonnement sémantique pour OSMOSE.
Tu dois déterminer quelles ASSERTIONS apportent de la connaissance sur quels CONCEPTS.

IMPORTANT - Ce n'est PAS un matching lexical:
- Une assertion peut concerner un concept sans le mentionner explicitement
- Un concept en français peut être lié à une assertion en anglais
- Le lien doit être SÉMANTIQUE (le sens), pas lexical (les mots)

Types de liens:
- defines: L'assertion définit le concept
- describes: L'assertion décrit une propriété du concept
- constrains: L'assertion impose une contrainte
- enables: L'assertion dit ce que le concept permet
- conditions: L'assertion spécifie une condition
- causes: L'assertion décrit un effet

CONCEPT SPÉCIAL "Assertions non classées" (SINK):
- Si aucun concept n'est clairement applicable à une assertion, utilise le concept SINK
- Préfère toujours un concept métier spécifique quand c'est possible
- SINK est un dernier recours, pas un choix par défaut
```

**Problème identifié dans le prompt :**
- Le prompt dit explicitement "Ce n'est PAS un matching lexical" et encourage le LLM à trouver des liens sémantiques même sans mention explicite
- Cela pousse le LLM à **sur-interpréter** et trouver des liens ténus
- Le prompt ne dit jamais "Si le lien est indirect ou faible, préfère SINK"
- Le prompt n'a **aucune notion de spécificité** — il ne demande pas de choisir le concept LE PLUS spécifique

### 5.3 Étape 2 — Filtre C3v2 (post-LLM)

**Fichier :** `assertion_extractor.py`, ligne 1693 (`_filter_multi_links`)

Constantes :
```python
MIN_LINK_CONFIDENCE = 0.70
MAX_LINKS_PER_ASSERTION = 5
TOP_K_IF_CLOSE = 2
CLOSE_THRESHOLD = 0.10
```

Logique C3v2 :
1. **Soft gate** : Si concept a des triggers ET assertion ne match aucun trigger → `confidence -= 0.20`
2. **Hard gate** : Si (pas de trigger match ET pas de token du nom du concept dans l'assertion) ET `conf_adj < 0.55` → **rejeté**
3. **Sélection** : Garder si `confidence_adj >= 0.70` OU top-2 si écart faible (< 0.10)

**Problèmes identifiés :**
- Le seuil du hard gate (0.55) est **très bas** — un LLM qui retourne 0.80 (courant) passe même avec la pénalité soft gate (-0.20 → 0.60 > 0.55)
- Les concepts vagues ont rarement des triggers spécifiques, donc le soft gate ne s'applique souvent pas
- Si le concept n'a PAS de triggers définis, la pénalité soft gate ne s'applique pas du tout (`if triggers and not has_trigger`)

### 5.4 Étape 3 — Rerank "Specificity Wins"

**Fichier :** `assertion_extractor.py`, ligne 2511 (`_rerank_links_specificity`)

Le rerank en 2 passes :

**Pass 1** — Score sans pénalité saturante :
```
score = conf_llm × combined_bonus × bonus_central × sink_malus
```
- `combined_bonus` = bonus_lexical si > 1.0, sinon bonus_semantic
- `bonus_central` = 1.10 si concept CENTRAL et preuve locale
- `sink_malus` = 0.90 si concept SINK

**Pass 2** — Re-score avec pénalité saturante basée sur distribution provisoire :
```
score = conf_llm × combined_bonus × bonus_central × penalty × sink_malus
```
- `penalty` = pénalité saturante 3 phases basée sur le nombre d'assertions provisoirement gagnées par ce concept

**Problèmes identifiés :**
- La pénalité saturante ne s'active que quand un concept accumule BEAUCOUP d'assertions (c'est un anti-"aspirateur")
- Mais elle ne vérifie pas la **pertinence** des liens, seulement la **distribution**
- Un concept vague qui reçoit peu d'assertions (car il y a beaucoup de concepts vagues) échappe à la pénalité
- Le bonus lexical est calculé sur les tokens du nom du concept dans l'assertion — les concepts avec des noms génériques ("Security", "Governance") matchent facilement

### 5.5 Étape 4 — Sélection finale (`_apply_margin_and_topk`)

Sélectionne pour chaque assertion les liens finaux après rerank, en appliquant une marge et un top-k.

---

## 6. Identification des Causes Racines

### Cause 1 — Concepts trop vagues et larges

Les concepts suivants sont des "attrape-tout" sémantiques :
- **"Shared Security Governance"** — Tout ce qui touche à la sécurité partagée
- **"Cloud Security Compliance Scanning"** — Tout ce qui touche à la compliance ou au scanning
- **"Security Audit Logs"** — Tout ce qui touche aux logs ou à l'audit
- **"Secure Connectivity"** — Tout ce qui touche à la connectivité ou à la sécurité

Ces concepts couvrent des domaines si larges que le LLM trouve toujours un lien sémantique indirect.

### Cause 2 — Le prompt encourage la sur-interprétation

Le prompt système dit explicitement :
> "Ce n'est PAS un matching lexical"
> "Une assertion peut concerner un concept sans le mentionner explicitement"

Cela pousse le LLM à chercher des liens même quand ils sont très indirects. Par exemple :
- "Short Distance DR vs Long Distance DR" → Secure Connectivity (car le DR implique des connexions)
- "Annual penetration tests" → Cloud Security Compliance Scanning (car les pentests font partie de la compliance)

### Cause 3 — Le LLM retourne des confidences élevées par défaut

Les LLMs (surtout Qwen) ont tendance à retourner des confidences entre 0.75 et 0.90, rarement en dessous de 0.60. Cela rend les seuils de filtrage (hard gate à 0.55, min confidence à 0.70) largement inefficaces.

### Cause 4 — Bruit documentaire non filtré en amont

Des assertions comme :
- "© 2023 SAP SE or an SAP affiliate company. All rights reserved."
- "INTERNAL | SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY"
- "SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY"
- "The information in this presentation is confidential..."

Ces mentions n'ont aucune valeur informationnelle. Elles ne devraient jamais être extraites comme assertions en premier lieu (problème Pass 1.2, pas Pass 1.3).

### Cause 5 — Fragmentation PPTX et perte de contexte

Les documents PPTX contiennent des slides hétérogènes. Le chunking peut mélanger du contenu de slides adjacentes mais thématiquement différentes. Le LLM de linking ne voit que le texte de l'assertion sans le contexte visuel de la slide.

### Cause 6 — Absence de feedback négatif dans le prompt

Le prompt ne donne aucun exemple de ce qu'il ne faut PAS lier. Il n'y a pas de :
- Exemples de faux positifs à éviter
- Instruction de préférer SINK en cas de doute
- Notion de "seuil de pertinence" — le LLM doit-il lier uniquement les assertions DIRECTEMENT liées au concept ?

---

## 7. Pistes de Solution (Non Implémentées)

### Piste A — Améliorer la qualité des concepts (Pass 1.1)

Forcer des concepts plus spécifiques et distincts :
- Contraindre la granularité (ex: pas de "Security Governance" mais "SAP-Customer Security Responsibility Matrix")
- Valider que chaque concept a un vocabulaire discriminant unique
- Limiter le nombre de concepts "parapluie"

### Piste B — Durcir le prompt de linking

- Ajouter des exemples négatifs explicites
- Exiger une justification SPÉCIFIQUE (pas juste "related to security")
- Demander au LLM de scorer la SPÉCIFICITÉ du lien (pas juste la pertinence)
- Reformuler : "L'assertion apporte-t-elle une information NOUVELLE et SPÉCIFIQUE sur ce concept ?"

### Piste C — Durcir les seuils de filtrage

- Monter le hard gate de 0.55 à 0.65 ou 0.70
- Monter le MIN_LINK_CONFIDENCE de 0.70 à 0.80
- Réduire MAX_LINKS_PER_ASSERTION de 5 à 2

### Piste D — Filtrer le bruit documentaire en amont (Pass 1.2)

- Ajouter un filtre pré-extraction qui rejette :
  - Mentions de copyright
  - Disclaimers juridiques
  - Titres de section trop courts (< 5 mots sans verbe)
  - Fragments tronqués

### Piste E — Approche Extract-then-Structure (V2.2)

L'approche V2.2 déjà en développement (feature flag `pass1_v22`) utilise un GlobalView construit en Pass 0.9 qui identifie les zones thématiques du document AVANT l'extraction. Cela pourrait aider à :
- Restreindre les concepts candidats par zone
- Mieux contextualiser les assertions
- Réduire le "spray" du LLM sur des concepts non pertinents

### Piste F — Validation humaine dans la boucle

Ajouter une étape de revue où les liens à faible confiance sont présentés pour validation, créant un dataset de feedback pour améliorer le prompt.

---

## 8. Fichiers Clés du Pipeline

| Fichier | Rôle | Lignes clés |
|---------|------|-------------|
| `src/knowbase/stratified/pass1/assertion_extractor.py` | Extraction assertions + linking + rerank | L1291 (link_to_concepts), L1693 (C3v2 filter), L2511 (rerank), L3189 (prompts) |
| `src/knowbase/stratified/pass1/concept_identifier.py` | Identification des concepts | Pass 1.1 |
| `src/knowbase/stratified/pass1/orchestrator.py` | Orchestration Pass 1 | L427 (création Information) |
| `src/knowbase/stratified/pass1/verbatim_validator.py` | Validation anti-reformulation | Post-extraction |
| `src/knowbase/stratified/models/information.py` | Modèle Information/InformationMVP | Structures de données |
| `config/prompts.yaml` | Prompts configurables (si override) | N/A (défauts dans le code) |
| `config/feature_flags.yaml` | Feature flags (pass1_v22) | Activation V2.2 |

---

## 9. Annexe — Concepts avec 0 Information (non peuplés)

Les concepts suivants existent dans Neo4j mais n'ont reçu aucune Information (seuls les 68 concepts de l'arbre Subject→Theme→Concept sont créés, les Information sont ajoutées par Pass 1.3) :

Centralized tools for customer management, Compliance Scanning (doublon de "Cloud Security Compliance Scanning"), Configuration of customer business processes, Customer Landscape Account, Customer Penetration Testing, Customer Subscriptions, Customer Tenancy Model, Customer-managed breach notification approval, Customer-managed IPSec S2S VPN, Customer-managed backup schedule, Customer-managed private connection, Direct Connect and ExpressRoute, HEC3.0-based landscapes, Hyperscaler Account Management, Logical separation of customer environment, RFC1918 IP Addresses, Regional Admin VPC, SAP Enterprise Cloud Services, SAP Global Security Policies, Security Policy Inheritance, Tenancy Model, et d'autres.

**Observation :** Beaucoup de ces concepts non peuplés sont en fait PLUS spécifiques que les concepts "aspirateurs" qui accumulent des informations hors-sujet. Le LLM préfère les concepts larges car ils "matchent" toujours sémantiquement.

---

## 10. Documentation Technique Complète

Le document technique exhaustif du pipeline est disponible dans :
`doc/ongoing/DOC_PIPELINE_V2_TECHNIQUE_EXHAUSTIVE.md` (~4700 lignes)

Sections pertinentes :
- Section 8: Pipeline Pass 1 — Identification & Structuration
- Section 8.8: Pipeline V2.2 Extract-then-Structure
- Section 16: Conformité avec l'architecture V2
