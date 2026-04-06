# Audit Run 8 — Admissibility Upstream V2.1

**Date :** 2026-01-31
**Document :** RISE with SAP Cloud ERP Private (Security)
**Pipeline :** Pass 1 avec filtre admissibilité upstream

---

## Résumé Métriques

| Métrique | Run 6 (baseline) | **Run 8** | Δ |
|----------|------------------|-----------|---|
| Informations | 236 | **277** | +17% |
| Concepts total | 67 | **62** | -5 |
| Concepts avec infos | 28 (42%) | **50 (81%)** | +39pts |
| Concepts vides | 39 (58%) | **12 (19%)** | -39pts |
| SINK | 77 | **0** | -100% |
| Thèmes | ~40 | **40** | = |
| avg admissible/batch | 61 (pas de filtre) | **34** | -44% |
| Batches linking | 11 | **138** | section-aware |

---

## Sujet

**SAP Cloud ERP Private Deployment Models**
(ID: `subj_020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357`)

---

## Hiérarchie complète : Thème → Concept → Informations

### 1. Vulnerability Advisory Services (62 infos, 3 concepts)

#### 1.1 SAP Enterprise Cloud Services — 35 infos ⚠️ ASPIRATEUR

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Shell session timeouts | PRESCRIPTIVE | 0.9 |
| 2 | SAP ECS reserves the right to reject requests for an excessively large rule base | PRESCRIPTIVE | 0.9 |
| 3 | These guidelines are implemented for workstations, servers, hypervisors, and container hosts. | FACTUAL | 0.9 |
| 4 | All hosts are equipped with agents for Endpoint Detection and Response (EDR), antivirus, and anti-malware software. | FACTUAL | 0.9 |
| 5 | China Datacom Corp. (SAP's exclusive Chinese Partner) | DEFINITIONAL | 0.9 |
| 6 | Requires a telecom license in China | PRESCRIPTIVE | 0.9 |
| 7 | No telecom license in China required | PRESCRIPTIVE | 0.9 |
| 8 | SAP has unified the approach for all cloud solutions with the Data Processor Agreement (DPA) | FACTUAL | 0.9 |
| 9 | The customer is responsible for requesting the deployment of non-critical security patches with priorities ranging from 'very high' to 'low'. | PRESCRIPTIVE | 0.9 |
| 10 | The customer is responsible for initiating and implementing 'very high' rated security patches. | PRESCRIPTIVE | 0.9 |
| 11 | OS (Linux System) Logs | FACTUAL | 0.9 |
| 12 | OS (Windows Event) Logs | FACTUAL | 0.9 |
| 13 | Enterprise Cloud Services (ECS) performs comprehensive testing on verifications of patches based on the SAP CERT Advisory before creating a Mass Change Ticket (MCT) and Send for Change Advisory Board (CAB) Approval. | PROCEDURAL | 0.9 |
| 14 | Providing qualified DC or colocation facility to host the infrastructure; firewall and network traffic controls | PRESCRIPTIVE | 0.9 |
| 15 | RAVEN is an ECS service that simplifies the management of SAP Application Security and Threats, while delivering 'Security and Compliance' reports and dashboards to customer SIEM systems. | DEFINITIONAL | 0.9 |
| 16 | It is important to note that the customer is required to perform traffic validation/checking before it is sent to the ECS private cloud. | PRESCRIPTIVE | 0.9 |
| 17 | FWaaS is available for customers with RISE with SAP Private Cloud landscapes on Azure, AWS, and GCP. Both PTO and PCE are supported. | FACTUAL | 0.9 |
| 18 | FWaaS is specifically designed to filter traffic within the ECS landscape, where customers cannot intervene—such as filtering traffic between a PROD and a NON-PROD subnet. | FACTUAL | 0.9 |
| 19 | SAP ECS manage and operate the Firewall | FACTUAL | 0.9 |
| 20 | Short Distance DR vs Long Distance DR | FACTUAL | 0.9 |
| 21 | State of Art – Cyber SOC operating 24x7 | DEFINITIONAL | 0.9 |
| 22 | Customer manages configuration, implementation, integration, monitoring, application support etc | PRESCRIPTIVE | 0.9 |
| 23 | Use of Terminal Servers | PRESCRIPTIVE | 0.9 |
| 24 | There are two levels of encryption applies to data-at-Rest using symmetric keys. Database volume and backup encryption as well as the encryption of the IaaS provider storage where database files and its backups are stored. | FACTUAL | 0.9 |
| 25 | The storage used to store data files, log files and the backup sets are encrypted by default by IaaS provider using Server-Side Encryption (SSE) that uses server managed keys. | FACTUAL | 0.9 |
| 26 | By default, no internet-based access is enabled directly from Cloud ERP Private. However, access can be selectively enabled for specific systems or services that require it (e.g., external Fiori access or integrations). | FACTUAL | 0.9 |
| 27 | For outbound internet access, HTTPS traffic is routed through a standard forward proxy, while non-HTTPS traffic uses a SNAT (Source Network Address Translation) Load Balancer. | FACTUAL | 0.9 |
| 28 | Defined Key Rotation and Destruction processes | DEFINITIONAL | 0.9 |
| 29 | Customer must install, own and manage | PRESCRIPTIVE | 0.9 |
| 30 | a similar configuration is applicable for AWS and Google Cloud | FACTUAL | 0.9 |
| 31 | SAP Global Security Policies and SAP Enterprise Cloud Services (ECS) Policies are applies through secure default deployment and compliance scans | FACTUAL | 0.9 |
| 32 | Network Access Control & Security Group | DEFINITIONAL | 0.9 |
| 33 | Each customer receives their own isolated landscape Virtual Network created | FACTUAL | 0.9 |
| 34 | Each customer is isolated from the SAP Corporate Network | FACTUAL | 0.9 |
| 35 | Overall cloud security is assured via various contracting assurances such as General Terms & Conditions, Data Processing Agreement and Technical & Organizational Measures. | FACTUAL | 0.9 |

> **🔍 Verdict :** Concept aspirateur majeur. "SAP Enterprise Cloud Services" est trop générique — il absorbe tout ce qui mentionne ECS/Cloud sans discrimination. Beaucoup d'infos seraient mieux placées ailleurs (ex: #24-25 → Database encryption, #17-18 → Firewall, #5-7 → China operations, #20 → DR). Problème structurel : le concept est admissible dans presque toutes les sections car ECS est mentionné partout.

#### 1.2 SAP Global Security — 19 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Perform VAPT for cloud services; customer to provide downtime for infra patching | PRESCRIPTIVE | 0.9 |
| 2 | Disabling of insecure legacy protocols. | PRESCRIPTIVE | 0.9 |
| 3 | Enforcement of strong password policies. | PRESCRIPTIVE | 0.9 |
| 4 | Golden images are defined and versioned in accordance with the hardening guidelines. | DEFINITIONAL | 0.9 |
| 5 | Hardening guidelines are based on CIS Benchmark Controls. | FACTUAL | 0.9 |
| 6 | Security measures are audited and confirmed through various Certifications & Attestations | FACTUAL | 0.9 |
| 7 | Vulnerability arising due to weak configuration and security parameters | CAUSAL | 0.9 |
| 8 | Vulnerability directly related to missing offline security patches of OS | CAUSAL | 0.9 |
| 9 | Vulnerability directly related to missing online security patches | CAUSAL | 0.9 |
| 10 | Short Distance (Mixed HA/DR) | FACTUAL | 0.9 |
| 11 | Security Controls for Data Protection | DEFINITIONAL | 0.9 |
| 12 | SAP Internal Cyber Security Centre, dedicated to identifying & mitigating Cyber Security risks, issues & challenges | DEFINITIONAL | 0.9 |
| 13 | SAP develops and licenses a number of products to assist with managing security across your landscape. | FACTUAL | 0.9 |
| 14 | SAP Secure Login Service for SAP GUI | DEFINITIONAL | 0.9 |
| 15 | Enabling single sign-on with X.509 certificates | DEFINITIONAL | 0.9 |
| 16 | Defined Policy and Standard Operating Procedures | DEFINITIONAL | 0.9 |
| 17 | SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY | PRESCRIPTIVE | 0.9 |
| 18 | Continuous 24x7 monitoring of security events, managing event triage, handing incidents, overseeing containment procedures, and offering forensic Support | PROCEDURAL | 0.9 |
| 19 | Major security operational topics are implemented and managed globally across all cloud solutions offered by SAP. | FACTUAL | 0.9 |

> **🔍 Verdict :** Semi-aspirateur. Infos globalement cohérentes (hardening, VAPT, policies). Mais #10 "Short Distance DR" et #17 "NDA USE ONLY" sont clairement mal routées. #14-15 seraient mieux dans "Secure Admin Access".

#### 1.3 SAP Vulnerability Advisory Services — 8 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Certification and Compliance | DEFINITIONAL | 0.9 |
| 2 | Perform VAPT for custom applications; customer to provide downtime for infra patching | PRESCRIPTIVE | 0.9 |
| 3 | Preparation \| Detection & Analysis \| Containment, Eradication & Recovery \| Post-Incident Activity | PROCEDURAL | 0.9 |
| 4 | IT infrastructure and/or application affected | FACTUAL | 0.9 |
| 5 | SAP ensures the usage of an adequate internal or external US CERT advisory service for information about new security threats and vulnerabilities for all relevant components of the Cloud Service stack. | FACTUAL | 0.9 |
| 6 | Annual penetration tests | FACTUAL | 0.9 |
| 7 | Vulnerability Management Policy | FACTUAL | 0.9 |
| 8 | Vulnerability Scanning & Penetration Testing | FACTUAL | 0.9 |

> **🔍 Verdict :** Bon. Cohérent avec le concept. #3 est plus "Incident Response" que "Vulnerability Advisory" mais acceptable.

---

### 2. Privileged Access Management (22 infos, 4 concepts)

#### 2.1 Secure Administrative Access Control — 14 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Flow (processing incl. transfer, access or contract) of personal data | FACTUAL | 0.9 |
| 2 | Data transfer outside of China has to be validated and certified by Chinese authorities (CAC security assessment) | PRESCRIPTIVE | 0.9 |
| 3 | Customer controls creation, use, deletion, rotation of the Master Keys | FACTUAL | 0.9 |
| 4 | Customer can subscribe to SAP Data Custodian KMS to BYOK to encrypt HANA LSS. | PERMISSIVE | 0.9 |
| 5 | Locking of system and service user accounts. | PRESCRIPTIVE | 0.9 |
| 6 | Restriction of superuser access. | PRESCRIPTIVE | 0.9 |
| 7 | For HANA DB, 99.7% HANA standby optional for =<6TiB but mandatory for VM >6TiB and Bare Metal. | FACTUAL | 0.9 |
| 8 | SAP Manages technical stack and customer has no access to Infrastructure OS. | PRESCRIPTIVE | 0.9 |
| 9 | Contents of both SSFSs are protected by SSFS Master Keys. Unique master keys are generated during installation and update. Master keys are changed in regular intervals. Segregation of duties principle is applied to key management. | FACTUAL | 0.9 |
| 10 | Defence in Depth Security | DEFINITIONAL | 0.8 |
| 11 | Enforce MFA for Admin Users | PRESCRIPTIVE | 0.9 |
| 12 | Secure by Design and Secure by Default | DEFINITIONAL | 0.9 |
| 13 | SAP has no access to customer data that resides in SAP business client. | FACTUAL | 0.9 |
| 14 | SAP manages technical stack and customer has no access to Infrastructure OS. | FACTUAL | 0.9 |

> **🔍 Verdict :** Mixte. #5-6, #8, #11, #13-14 sont bien alignés (contrôle d'accès admin). Mais #1-2 (transfert données Chine), #3-4 (KMS/BYOK), #7 (HANA standby), #9 (SSFS keys) sont mal routés — ils relèvent respectivement de Data Protection, Encryption, HA, et Key Management.

#### 2.2 Role Based Access Control — 6 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Customer is entirely responsible | PRESCRIPTIVE | 0.9 |
| 2 | The customer requires compartmentalization | FACTUAL | 0.9 |
| 3 | Role Based Access Control (RBAC) | DEFINITIONAL | 0.9 |
| 4 | SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY | PRESCRIPTIVE | 0.9 |
| 5 | Secure Infrastructure as a Code | DEFINITIONAL | 0.9 |
| 6 | Additional License is required. | PRESCRIPTIVE | 0.9 |

> **🔍 Verdict :** Faible. #3 est le seul vraiment pertinent. #4 (NDA disclaimer), #5 (IaC), #6 (licence) sont du bruit.

#### 2.3 Secure Management Protocol — 2 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Manage 2 Internet VPN terminations at Internet access points | PRESCRIPTIVE | 0.9 |
| 2 | Azure Storage Account provides a unique namespace to store and access Azure Storage resources securely. | FACTUAL | 0.9 |

> **🔍 Verdict :** Faible. #2 (Azure Storage) n'a rien à voir avec "Secure Management Protocol".

#### 2.4 Identity and Access Management — 0 infos (VIDE)

> **🔍 Verdict :** Concept vide. Probablement absorbé par "Secure Administrative Access Control" et "Identity and Access Controls" qui couvrent le même périmètre.

---

### 3. Application Stack (16 infos, 1 concept)

#### 3.1 SAP Application Server — 16 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | SAP Managed Hyperscaler Environment | DEFINITIONAL | 0.9 |
| 2 | HANA DB Audit trail logs /var/hana/log | FACTUAL | 0.9 |
| 3 | Redundancy with multiple Application Servers across AZ's running Active-Active. Active-Passive DB across AZ's if Standby DB node is contracted. | FACTUAL | 0.9 |
| 4 | Failover of SCS/ERS and DB through manually initiated automatically failover procedure. | FACTUAL | 0.9 |
| 5 | VM self healing coupled with Application AutoStart is used for the SAP application servers. | FACTUAL | 0.9 |
| 6 | EBS storage for DB file systems like data and log volumes. EFS is used for shares and application file system. Amazon S3 is primarily used for backups. | FACTUAL | 0.9 |
| 7 | SAP Application Servers, SCS/ERS, DB, Web Dispatcher and Cloud Connector are typically in single Zone until CAA explicitly request them to be deployed across AZ's as part of DED during the S2D. | FACTUAL | 0.9 |
| 8 | VM / Hypervisor outage | FACTUAL | 0.9 |
| 9 | Central Services / App Server Outage | FACTUAL | 0.9 |
| 10 | Replication within 50 km – Multi Zones (AZ's) | FACTUAL | 0.9 |
| 11 | Replication Over 50 km – Cross Regions | FACTUAL | 0.9 |
| 12 | VM self healing coupled with Application AutoStart is used for the SAP application servers | FACTUAL | 0.9 |
| 13 | X.509 certificate token is used for authenticating the SAP GUI user to the ABAP system | FACTUAL | 0.9 |
| 14 | Encryption root key and master key generated during installation & HANA version updates | FACTUAL | 0.9 |
| 15 | SAP DBA authenticates via MFA | FACTUAL | 0.9 |
| 16 | It is allowed to access Fiori applications from customer's mobile devices over Internet. | PERMISSIVE | 0.9 |

> **🔍 Verdict :** Semi-aspirateur. Mélange HA/DR (#3-5, #8-12), auth (#13, #15), encryption (#14), network (#16) avec le serveur applicatif. #5 et #12 sont des doublons quasi-identiques. Beaucoup d'infos seraient mieux dans des concepts plus spécifiques.

---

### 4. Basic Technical Operations (15 infos, 6 concepts)

#### 4.1 SAP Operations Management — 6 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | If a customer experiences a security incident, are you prepared to provide the customer with the relevant security event logs? | CONDITIONAL | 0.9 |
| 2 | ASE error log Backup Server log Job scheduler error log | FACTUAL | 0.9 |
| 3 | Customer can choose to create service requests for patching the respective systems based on the downtime schedule convenient for the customer. | PERMISSIVE | 0.9 |
| 4 | Physical Hardware under SAP Contract with Infra Partners, Inter Rack Networking, Infrastructure Management, Maintenance and Support | FACTUAL | 0.9 |
| 5 | solutions are collected, correlated and analysed. | PROCEDURAL | 0.9 |
| 6 | Each customer landscape are connected to shared management | FACTUAL | 0.9 |

> **🔍 Verdict :** Acceptable. Cohérent dans l'ensemble. #5 est tronqué/incomplet.

#### 4.2 Disaster Recovery Site — 4 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Backup storage is replicated to secondary location | FACTUAL | 0.9 |
| 2 | Database Replication for High Availability and Disaster Recovery | FACTUAL | 0.9 |
| 3 | Once DR Testing is concluded at the customer, SAP rebuild the DR system and enable the replication from primary to secondary side. | PROCEDURAL | 0.9 |
| 4 | Disaster Recovery Plan and Regular Testing | FACTUAL | 0.9 |

> **🔍 Verdict :** Bon. Toutes les infos sont pertinentes pour le DR.

#### 4.3 Technical Validation of Patches — 3 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | SAP performed Regular VAPT | FACTUAL | 0.9 |
| 2 | Use the check boxes and 'Request patching' button to create multiple Service requests for different system numbers and patch types | PROCEDURAL | 0.9 |
| 3 | SAP Managed Patch Management and Upgrades | DEFINITIONAL | 0.9 |

> **🔍 Verdict :** Bon. Cohérent.

#### 4.4 Security Operations Playbooks — 1 info

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | SAP Managed Security Operations – People, Technology and Process | DEFINITIONAL | 0.9 |

> **🔍 Verdict :** OK.

#### 4.5 SAP Identity Authentication Service — 1 info

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | SAP Identity Authentication Service Basic SSO included in SAP S/4HANA Cloud | FACTUAL | 0.9 |

> **🔍 Verdict :** OK mais thème discutable ("Basic Technical Operations" vs "Secure Admin Access").

#### 4.6 Network Availability — 0 infos (VIDE)

> **🔍 Verdict :** Concept vide. Probablement absorbé par "Dedicated Private Connection" ou "Enterprise-grade Network Firewall".

---

### 5. Operational SLA (14 infos, 1 concept)

#### 5.1 System availability SLA — 14 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Patches that do not require downtime are patched automatically based on recommended due date. | FACTUAL | 0.9 |
| 2 | If the system remains available but the application ceases to respond, how should we approach resolving this issue? | CONDITIONAL | 0.9 |
| 3 | If data is corrupted during backup or any other scenario, is there a data availability SLA? | CONDITIONAL | 0.9 |
| 4 | SAP and its sub processors obligations and restrictions to process Personal Data in the provision of the Cloud Service, including: | PRESCRIPTIVE | 0.9 |
| 5 | Defines the cloud service specific system availability, uptime, update windows, credits and others | DEFINITIONAL | 0.9 |
| 6 | the audit trail feature has not been tampered with and the audit trail has been preserved by the company as per the statutory requirements for record retention | PRESCRIPTIVE | 0.9 |
| 7 | to provide the customer with 48 | PRESCRIPTIVE | 0.9 |
| 8 | SAP will use reasonable endeavors | PRESCRIPTIVE | 0.9 |
| 9 | Recovery Point Objective | FACTUAL | 0.9 |
| 10 | Recovery Time Objective | FACTUAL | 0.9 |
| 11 | With Multiple Architecture designs we can Cover below type of Outages | FACTUAL | 0.9 |
| 12 | Data Protection, Continuity and Recoverability | FACTUAL | 0.9 |
| 13 | 2 hours (24 x 7) for PROD 4 hours [Local Time on Business Days] for Non-PROD | PRESCRIPTIVE | 0.9 |
| 14 | 20 minutes (24 x 7) and (i) resolution or (ii) workaround or (iii) action plan within 4hrs for PRD | PRESCRIPTIVE | 0.9 |

> **🔍 Verdict :** Mixte. #5, #9-10, #13-14 sont bien alignés (SLA, RPO/RTO, temps de réponse). Mais #4 (Data Processing), #6 (audit trail), #7-8 (tronqués) sont du bruit. Plusieurs infos tronquées.

---

### 6. Audit and certifications (12 infos, 1 concept)

#### 6.1 SOC1 and SOC2 Audits — 12 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | The SAP Trust Center is a public-facing website designed to provide unified and easy access to trust related content | DEFINITIONAL | 0.9 |
| 2 | /var/log/messages /var/log/Localmessages /var/log/kernel /var/log/sssd /var/log/sudolog /var/log/warn /var/log/corn /var/log/pacemaker | FACTUAL | 0.9 |
| 3 | The backup storage of 1 month for productive systems and 14 days for nonproductive systems... replicated to an alternate location | FACTUAL | 0.9 |
| 4 | Pacemaker Cluster protect single points of failure (SPOFs)... automatic failover enabling rapid recovery | FACTUAL | 0.9 |
| 5 | Audit Compliance & Contractual Assurances | DEFINITIONAL | 0.9 |
| 6 | Regular Auditing ISO, SOC1 and SOC2 | FACTUAL | 0.9 |
| 7 | HANA Data Encryption – AES-256-CBC algorithm | FACTUAL | 0.9 |
| 8 | Crypto Libraries are FIPS 140-2 certified | FACTUAL | 0.9 |
| 9 | Master keys can be changed in regular intervals by request | PERMISSIVE | 0.9 |
| 10 | Service Continuity Management | FACTUAL | 0.9 |
| 11 | Golden Images (Secure by Default and Secure by Design) | DEFINITIONAL | 0.9 |
| 12 | ISAE3402 SOC 1 Type II, ISAE 3000 SOC2 Type II, ISO 27001:2013, ISAE 3000 C5 Type II... | FACTUAL | 0.9 |

> **🔍 Verdict :** Mixte. #5-6, #12 sont parfaitement alignés. Mais #2 (log paths), #3 (backup retention), #4 (Pacemaker HA), #7-9 (encryption) sont clairement mal routés.

---

### 7. Firewall as a Service (12 infos, 1 concept)

#### 7.1 Enterprise-grade Network Firewall — 12 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | NSGs act as a second firewall vendor in the landscape... | FACTUAL | 0.9 |
| 2 | WinEventLog:System WinEventLog:Security WinEventLog:Application | FACTUAL | 0.9 |
| 3 | Responsible for providing an Internet access point and managing routing and security | PRESCRIPTIVE | 0.9 |
| 4 | In a typical design, customers are advised to have at least two subnets or more. | PRESCRIPTIVE | 0.9 |
| 5 | Customers may have direct access to their Firewall rule base | PERMISSIVE | 0.8 |
| 6 | Next Generation Firewall supports SPI aware packet | FACTUAL | 0.9 |
| 7 | SAP ECS manage and operate the Firewall | FACTUAL | 0.9 |
| 8 | Periodic patching of all Internet Facing Web Applications, Malware Protection Enabled | PRESCRIPTIVE | 0.9 |
| 9 | All internet security such as Web Application Firewall are to be managed by the customer in their network. | PRESCRIPTIVE | 0.9 |
| 10 | *WAF setup only when RISE inbound is allowed from Internet | PRESCRIPTIVE | 0.9 |
| 11 | WAF setup only when RISE inbound is allowed from Internet | PRESCRIPTIVE | 0.9 |
| 12 | Inbound traffic from Internet can be allowed and will be screened via WAF. ALB will route traffic to the Web Dispatcher... | FACTUAL | 0.9 |

> **🔍 Verdict :** Bon globalement. #1, #3-7, #9-12 sont bien alignés firewall/WAF/network. #2 (Windows Event Logs) est mal routé. #10-11 sont des doublons.

---

### 8. Program Management Office (10 infos, 3 concepts)

#### 8.1 Security Information and Event Management — 6 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | RAVEN is an ECS service that simplifies the management of SAP Application Security and Threats... | DEFINITIONAL | 0.9 |
| 2 | Traffic to RISE can be routed via their own Firewall. | CONDITIONAL | 0.9 |
| 3 | The customer traffic can be routed via customer owned Proxy at their on-premise network. | CONDITIONAL | 0.9 |
| 4 | Data Lake platform to support both Customers and SAP for log retention and recovery of historical logs | FACTUAL | 0.9 |
| 5 | All sessions are monitored and recorded to SAP SIEM | FACTUAL | 0.9 |
| 6 | Incident Management 24x7 (Prod) Service Request Management (24x7 – Prod) Change Request Management (24x7) Security Monitoring – SIEM – 24x7 | FACTUAL | 0.9 |

> **🔍 Verdict :** Mixte. #1, #4-6 sont bien alignés SIEM. #2-3 (traffic routing) sont mal routés.

#### 8.2 Change Management — 2 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Patching, Malware and Change Management | FACTUAL | 0.9 |
| 2 | Security Incident & Problem Management | FACTUAL | 0.9 |

> **🔍 Verdict :** OK. Pertinent.

#### 8.3 Provisioning and Automation — 2 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Every change to customer landscape in SAP Cloud ERP Private is managed deployment. | FACTUAL | 0.9 |
| 2 | Internet outbound to be routed to customer's landing zone or to a gateway that customer provides. | PRESCRIPTIVE | 0.9 |

> **🔍 Verdict :** #1 OK. #2 est du routing réseau, mal routé.

---

### 9. Cloud Integration (9 infos, 1 concept)

#### 9.1 RISE with SAP Cloud ERP Private — 9 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Using dedicated connectivity options such as AWS Direct Connect, Azure Express Route and Google Cloud Interconnect... | FACTUAL | 0.9 |
| 2 | If I am running SAP S/4HANA on a Hyperscaler, why is it necessary to perform a lift and shift...? | CONDITIONAL | 0.9 |
| 3 | SAP is responsible for cloud services reference architecture | FACTUAL | 0.9 |
| 4 | RISE with SAP S/4HANA Cloud, private edition, CDC Option | DEFINITIONAL | 0.9 |
| 5 | This is a turn-key cloud offering fully compliant with SAP HEC concierge standard... | FACTUAL | 0.9 |
| 6 | SAP Solution is deployed across two AWS regions. HA with-in primary region. DR in secondary region... | FACTUAL | 0.9 |
| 7 | Customer must install, own and manage | PRESCRIPTIVE | 0.9 |
| 8 | RISE with SAP S/4HANA Cloud, Private Edition | DEFINITIONAL | 0.9 |
| 9 | RISE with SAP S/4HANA cloud, private edition | DEFINITIONAL | 0.9 |

> **🔍 Verdict :** Semi-aspirateur. #4-5, #8-9 sont des définitions du produit (dont doublons). #1 devrait aller dans "Dedicated Private Connection". #6 dans DR/HA.

---

### 10. Virtual Private Connection (8 infos, 1 concept)

#### 10.1 Dedicated Private Connection — 8 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | CDC connection to customer network using redundant links to carry all customer and management traffic | FACTUAL | 0.9 |
| 2 | Customer Network Setup – S/4HANA Private Cloud Edition, CDC Option | DEFINITIONAL | 0.9 |
| 3 | fastest single connection: 2.5 Gbps 5.0 Gbps (2 VMs, default) max. 50 custom rules | FACTUAL | 0.9 |
| 4 | Security Monitoring, Isolation of infected devices, Logging, security incident response, remediation and recovery | FACTUAL | 0.9 |
| 5 | Securing Data in Transit (Customer Managed Internet Access) | DEFINITIONAL | 0.9 |
| 6 | By default, there is no Internet based Inbound/Outbound is enabled directly from RISE VNET. | FACTUAL | 0.9 |
| 7 | A dedicated private connection with redundancy is recommended for accessing productive workload... | PRESCRIPTIVE | 0.9 |
| 8 | Each customer's landscape is fully integrated into the customer | FACTUAL | 0.9 |

> **🔍 Verdict :** Bon. #1-2, #5-7 sont bien alignés. #3 semble être des specs FWaaS. #4 (Security Monitoring) est mal routé.

---

### 11. Admin Logical Access Control (8 infos, 1 concept)

#### 11.1 Secured admin access point — 8 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | China Datacom Corp. is SAP's JV partner in China and IRCS telecom license holder | DEFINITIONAL | 0.9 |
| 2 | SOC reports and certifications to provide independent evidence... | FACTUAL | 0.9 |
| 3 | SAP products are assessed to internationally recognised standards and platform hardening | FACTUAL | 0.9 |
| 4 | through regular vulnerability advisories from software vendors and NIST, complemented by periodic system scans. | FACTUAL | 0.9 |
| 5 | Single sign-on based on X.509 certificates | DEFINITIONAL | 0.9 |
| 6 | Secure KMS Configuration Enforced | PRESCRIPTIVE | 0.9 |
| 7 | Secured admin access point (Customer Gateway Server (CGS)) with hosted firewall and access controls | FACTUAL | 0.9 |
| 8 | Only use an in-date presentation downloaded from Cyber Security Hub - Golden Assets | PRESCRIPTIVE | 0.9 |

> **🔍 Verdict :** Faible. Seuls #5 et #7 sont pertinents. #1 (China JV), #2-3 (certifications), #8 (presentation disclaimer) sont du bruit clair.

---

### 12. Secure Admin Access (7 infos, 2 concepts)

#### 12.1 Identity and Access Controls — 5 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | SAP establishes separate Customer environments, implements micro segmentation to restrict east-west traffic... | CAUSAL | 0.9 |
| 2 | Secure Login Client (SLC) redirects user to the identity provider logon page | PROCEDURAL | 0.9 |
| 3 | Optionally, authentication can be delegated to a corporate IdP (such as Azure AD) | PERMISSIVE | 0.9 |
| 4 | After successful authentication, SAP-managed Cloud CA issues an X.509 certificate | FACTUAL | 0.9 |
| 5 | User Certificate Service returns the X.509 certificate, valid for one day, to SLC | FACTUAL | 0.9 |

> **🔍 Verdict :** Bon. #2-5 forment un flux d'authentification cohérent. #1 (micro-segmentation) devrait être dans "Network Segregation".

#### 12.2 Dedicated Management Networks — 2 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Secure management protocol only accessible only via dedicated management networks. | PRESCRIPTIVE | 0.9 |
| 2 | Restricted access to administrative protocols is enforced. | PRESCRIPTIVE | 0.9 |

> **🔍 Verdict :** Bon. Parfaitement cohérent.

---

### 13. Supported Hyperscalers (7 infos, 2 concepts)

#### 13.1 SAP4me Service Request — 7 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | Option 1: Create a Service Request for patching a single system | PROCEDURAL | 0.9 |
| 2 | Option 2: Create multiple Service requests for patching two or more systems | PROCEDURAL | 0.9 |
| 3 | customers can use the SAP4me Service Request template to request an export of their rule base... | PERMISSIVE | 0.9 |
| 4 | The restore requestor must use the corresponding template and provide the necessary information. | PRESCRIPTIVE | 0.9 |
| 5 | Customers or customer representatives from cloud units can request restores by submitting a SR... | PROCEDURAL | 0.9 |
| 6 | One time DR drill per year is included as standard offering. Additional executions can be purchased... | PRESCRIPTIVE | 0.9 |
| 7 | Customer initiates DR drill by creating service request at least 6 weeks in advance. | PROCEDURAL | 0.9 |

> **🔍 Verdict :** Bon contenu MAIS mauvais thème. "SAP4me Service Request" n'a rien à voir avec "Supported Hyperscalers". Le concept est bien, le thème est faux.

#### 13.2 Cloud Foundry Runtime — 0 infos (VIDE)

> **🔍 Verdict :** Concept vide. Probablement pas assez de contenu dans le document sur ce sujet.

---

### 14. Long Distance DR (7 infos, 1 concept)

#### 14.1 Long Distance DR — 7 infos

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | VPC Peering is used to connect Primary with DR Region. | FACTUAL | 0.9 |
| 2 | SAP S/4HANA Cloud, private edition – Short Distance DR | DEFINITIONAL | 0.9 |
| 3 | Backups are run Automatically and Disaster Recovery is Tested Annually | PRESCRIPTIVE | 0.9 |
| 4 | RPO 30min, RTO 4hrs/12hrs | FACTUAL | 0.9 |
| 5 | Redundancy with multiple Application Servers across AZ's running Active-Active. Active-Passive DB across AZ's | FACTUAL | 0.9 |
| 6 | SAP Solution is deployed across two AWS regions. HA between AZ's in primary region. DR is in secondary region... | FACTUAL | 0.9 |
| 7 | SAP Solution is deployed across two AZ in a single region for HA/DR. Components in each AZ are symmetrical | FACTUAL | 0.9 |

> **🔍 Verdict :** Bon. Cohérent. #2 mentionne Short Distance DR mais dans un contexte de comparaison, acceptable.

---

### 15. Proxy Logs (7 infos, 1 concept)

#### 15.1 SAP Cloud ERP Private Proxy Logs — 7 infos (dont 1 renommé "Centralized API Logging")

| # | Information | Type | Conf |
|---|-------------|------|------|
| 1 | LogServ is an ECS service designed for storing and accessing logs... | DEFINITIONAL | 0.9 |
| 2 | DNS, Load Balancers, Internet Proxy are available to customer via LogServ. | FACTUAL | 0.9 |
| 3 | Operating Systems and Database Logs will be available to customer via LogServ. | FACTUAL | 0.9 |
| 4 | Detailed Scope of Application Logs provided by LogServ | FACTUAL | 0.9 |
| 5 | BOBJ Logs ABAP Logs JAVA Logs | FACTUAL | 0.8 |
| 6 | Centralized API Logging | DEFINITIONAL | 0.9 |

> **🔍 Verdict :** Bon. Toutes les infos sont liées aux logs/proxy. Cohérent.

---

### 16-20. Thèmes avec 4-6 infos

#### 16. Database (12 infos, 4 concepts)

**Database backup retention** (6) — ⚠️ 5/6 infos concernent les Companies Act India (obligations de conservation de livres comptables en Inde). Seule #6 "All backup copies are stored primary location" est pertinente. **Mauvais routage massif.**

**Database secure stores** (4) — #2-4 sont cohérents (SSFS, encryption). #1 "SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY" est du bruit.

**Database encryption keys** (1) — "All internet accesses must be encrypted in transit (via TLS)" — pas lié aux clés de chiffrement DB. **Mal routé.**

**Database backup** (1) — "Keys are securely backed up as part of the database backup" — OK, cohérent.

#### 17. OS Online Patches (6 infos, 1 concept)

**Online Security Patches** (6) — Bon. Toutes les infos concernent le patch management.

#### 18. Architecture 99.9 Multi-AZ + LDDR (6 infos, 1 concept) — Bon.

#### 19. Architecture 99.7 Multi-AZ + LDDR (4 infos, 1 concept) — Bon.

#### 20. Personal Data Breach Notification (4 infos, 1 concept) — Correct.

---

### 21-33. Thèmes avec 1-3 infos

| Thème | Concept | Infos | Verdict |
|-------|---------|-------|---------|
| Joule Activation S/4HANA | RISE with SAP | 3 | ⚠️ #2 (HANA encryption) mal routé |
| Detailed Scope Application Logs | Application Audit Logs | 3 | Bon |
| China Laws Cybersecurity | China Cybersecurity Law | 3 | ⚠️ #1 concerne l'Inde, pas la Chine |
| Customer Account Boundary | Isolated Network Environment | 2 | Faible (2 infos sur "Gateway Subnet Azure") |
| Integration with SAP BTP | ABAP GenAI SDK | 2 | ⚠️ #1 (proxy logs) mal routé |
| Enhanced HA Pacemaker | Enhanced HA Pacemaker Architecture | 2 | ⚠️ #1-2 sont du network security, pas Pacemaker |
| PIPL | Personal Information Protection Law | 2 | ⚠️ Contenu non pertinent |
| Customer Specific Subscription | Dedicated VPC | 1 | OK |
| TGW Attachment | Transit Gateway in SAP Account | 1 | OK (Flow Logs) |
| SAP Cloud Connector Reverse Proxy | SAP Cloud Connector | 1 | OK |
| Cloud Connector Logs | SAP Cloud Connector Logs | 1 | OK |
| India Companies Act 2022 | Companies Act India | 1 | OK |

---

### 34-40. Thèmes avec 0 infos (concepts vides)

| Thème | Concept vide | Analyse |
|-------|-------------|---------|
| Deployment Models | Assertions non classées (SINK) | ✅ Normal — SINK vide = objectif atteint |
| SAP Admin Access | SAP Cloud Access Manager | Absorbé par concepts plus généraux |
| Customer Network Connectivity | Network Segregation | Absorbé par "Isolated Network Environment" et "Enterprise-grade Network Firewall" |
| SAP Cloud Services Preventive Controls | SAP Cloud Identity Services | Absorbé par "Identity and Access Controls" |
| What are the rules/regulations? | Companies (Accounts) Rules 2014 | Contenu routé vers "Database backup retention" + "China Cybersecurity Law" |
| Cloud Service Supplemental T&C | SAP General Terms and Conditions | Peu de contenu dans le document |
| Security Operations | Internal Use Only | Concept trop vague |
| Secure Connections | Transport Layer Security requirement | Absorbé par "SAP Secure Network Communication" |
| Secure Connections | Secure dedicated network connections | Absorbé par "Dedicated Private Connection" |

---

## Relations entre concepts (Pass 2)

30 relations identifiées :

| Source | → | Cible | Verdict |
|--------|---|-------|---------|
| SAP Enterprise Cloud Services | → | Secured admin access point | ✅ |
| SAP Enterprise Cloud Services | → | SAP Vulnerability Advisory Services | ✅ |
| SAP Enterprise Cloud Services | → | SOC1 and SOC2 Audits | ✅ |
| RISE with SAP Cloud ERP Private | → | ABAP GenAI SDK | ⚠️ Lien faible |
| RISE with SAP Cloud ERP Private | → | SAP Global Security | ✅ |
| RISE with SAP Cloud ERP Private | → | System availability SLA | ✅ |
| SAP Application Server | → | Secure Administrative Access Control | ✅ |
| SAP Application Server | → | SAP Operations Management | ✅ |
| Dedicated Private Connection | → | 99.9 Multi-AZ + LDDR architecture | ✅ |
| Dedicated Private Connection | → | 99.7 Multi-AZ + LDDR architecture | ✅ |
| Dedicated Private Connection | → | Long Distance DR | ✅ |
| Fully encrypted VPN tunnels | → | Secure Management Protocol | ✅ |
| Secure by default and design | → | SAP Enterprise Cloud Services | ✅ |
| SAP Secure Network Communication | → | Enhanced HA Pacemaker Architecture | ⚠️ Lien faible |
| Dedicated Management Networks | → | SAP Application Server | ✅ |
| Database backup | → | Database secure stores | ✅ |
| Database backup retention | → | Companies Act India | ✅ Mais contenu Inde mal classé |
| Database encryption keys | → | Enterprise-grade Network Firewall | ❌ Incohérent |
| Technical Validation of Patches | → | Personal Information Protection Law | ❌ Incohérent |
| Security Operations Playbooks | → | Security Information and Event Management | ✅ |
| Disaster Recovery Site | → | 99.7 Multi-AZ + LDDR architecture | ✅ |
| SIEM | → | SAP Enterprise Cloud Services | ✅ |
| SIEM | → | 99.7 Multi-AZ + LDDR architecture | ⚠️ |
| SIEM | → | SOC1 and SOC2 Audits | ✅ |
| Provisioning and Automation | → | 99.7 Multi-AZ + LDDR architecture | ⚠️ |
| Provisioning and Automation | → | 99.9 Multi-AZ + LDDR architecture | ⚠️ |
| Provisioning and Automation | → | Long Distance DR | ⚠️ |
| Change Management | → | SOC1 and SOC2 Audits | ✅ |
| Change Management | → | System availability SLA | ✅ |
| Change Management | → | 99.7 Multi-AZ + LDDR architecture | ⚠️ |

---

## Synthèse Qualitative

### Problèmes systémiques identifiés

1. **Concept aspirateur "SAP Enterprise Cloud Services"** (35 infos) — absorbe tout ce qui mentionne ECS. Trop générique pour un document entièrement consacré à ECS. Devrait peut-être être exclu ou restreint.

2. **Routage hors-sujet par proximité lexicale** — Des infos sur l'Inde atterrissent dans "China Cybersecurity Law", des infos encryption dans "SOC1 and SOC2 Audits", des infos network dans "Secured admin access point". Le LLM semble parfois choisir le concept le plus "proche sémantiquement" au lieu du plus "structurellement pertinent".

3. **Infos tronquées** — Plusieurs informations sont des fragments incomplets ("to provide the customer with 48", "SAP publishes patches in", "solutions are collected, correlated and analysed."). Problème d'extraction en amont.

4. **Doublons** — Quelques doublons quasi-identiques (#5/#12 dans SAP Application Server, #10/#11 dans Firewall). Le dédoublonnage pré-linking ne les attrape pas.

5. **Thème ≠ Concept** — "SAP4me Service Request" (concept service request) classé dans le thème "Supported Hyperscalers" — incohérence thème/concept.

6. **Concepts redondants** — "Secure Administrative Access Control" vs "Secured admin access point" vs "Identity and Access Controls" vs "Identity and Access Management" couvrent le même domaine avec des frontières floues.

### Statistiques de qualité estimées

| Catégorie | Estimation |
|-----------|------------|
| Infos bien routées | ~65% |
| Infos acceptables (concept adjacent) | ~20% |
| Infos mal routées (concept incorrect) | ~15% |
| Relations cohérentes | 20/30 (67%) |
| Relations incohérentes | 3/30 (10%) |
| Relations discutables | 7/30 (23%) |

### Axes d'amélioration prioritaires

1. **Limiter les aspirateurs** : Plafond max d'infos par concept, ou exclusion des concepts trop génériques du document
2. **Améliorer la qualité d'extraction** : Réduire les fragments tronqués
3. **Dédoublonnage** : Filtrer les infos quasi-identiques avant linking
4. **Cohérence thème-concept** : Vérifier que le concept appartient bien sémantiquement au thème assigné
5. **Hiérarchie de headings** : Corriger l'inférence de niveaux pour les titres non numérotés (tous les slides)
