# Extraction Exhaustive V2 - RISE with SAP Cloud ERP Private Security

**Document source:** `020_RISE_with_SAP_Cloud_ERP_Private_full.pdf`
**Document ID:** `020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357`
**Date d'extraction:** 2026-01-26
**Pipeline:** OSMOSE Pipeline V2 - Pass 1 (avec fix `strict_promotion=false`)

---

## Sujet Principal

**SAP Cloud ERP Private** - Documentation de sécurité, déploiement et responsabilités partagées pour RISE with SAP S/4HANA Cloud, private edition.

---

## Statistiques d'Extraction

| Métrique | Valeur |
|----------|--------|
| **Thèmes** | 5 |
| **Concepts** | 10 (dont 3 CENTRAL) |
| **Informations ancrées** | 155 |
| **InformationMVP** | 1292 |
| **Assertions extraites** | 1465 |
| **Promues** | 1300 (217 ALWAYS + 1083 CONDITIONAL) |
| **Meta filtrées** | 148 |
| **Abstentions** | 1145 (principalement ancrage) |
| **Rejets** | 165 |

### Distribution des Informations par Concept

```
SAP Enterprise Cloud Services     ████████████████████████████████████████████ 43
Shared Security Responsibility    ███████████████████████████████████████ 39
SAP Cloud ERP                     ████████████████████████████ 28
Customer VNETS/VPC                █████████████████████ 21
Technical System Operations       ███████████ 11
Customer Data Center              ██████ 6
Logical Separation                █████ 5
Deployment Models                 █ 1
SAP Cloud Application Services    █ 1
```

---

## Structure Thématique

| # | Thème | Concepts | Rôle |
|---|-------|----------|------|
| 1 | **Modèles de déploiement** | Deployment Models, Customer Data Center, SAP CAS, SAP ECS, Technical System Operations, Application Performance Monitoring | CENTRAL + 5 STANDARD |
| 2 | **SAP Cloud ERP** | SAP Cloud ERP | CENTRAL |
| 3 | **Sécurité** | Shared Security Responsibility, Customer VNETS/VPC, Logical Separation | CENTRAL + 2 STANDARD |
| 4 | Partenaires technologiques | (non peuplé) | - |
| 5 | Responsabilité partagée | (non peuplé) | - |

---

## Thèmes et Informations Détaillées

### 1. Modèles de déploiement

#### Concept: Deployment Models (CENTRAL)

| # | Information | Conf. |
|---|-------------|-------|
| 1 | The Private IP is determined by customer for their landscape in RISE. | 0.9 |

#### Concept: Customer Data Center (STANDARD)

| # | Information | Conf. |
|---|-------------|-------|
| 1 | China issued laws which require under some circumstances to place instances directly in China | 0.9 |
| 2 | Any "important" data collected from China by customer has to be stored in China | 0.9 |
| 3 | Data transfer outside of China has to be validated and certified by Chinese authorities (CAC security assessment) | 0.9 |
| 4 | Each customer's landscape is fully integrated into the customer | 0.9 |
| 5 | SAP has no access to customer data that resides in SAP business client. | 0.9 |
| 6 | Is there any risk associated with data handling after the contract ends, or has this been addressed in the Master Services Agreement (MSA)? | 0.8 |

#### Concept: SAP Cloud Application Services (STANDARD)

| # | Information | Conf. |
|---|-------------|-------|
| 1 | RAVEN is an ECS service that simplifies the management of SAP Application Security and Threats, while delivering 'Security and Compliance' reports and dashboards to customer SIEM systems. | 0.9 |

#### Concept: SAP Enterprise Cloud Services (STANDARD)

| # | Information | Conf. |
|---|-------------|-------|
| 1 | Service Organisation Control (SOC) reports and certifications to provide independent evidence for security, availability, confidentiality, data protection, and quality. | 0.9 |
| 2 | Flow (processing incl. transfer, access or contract) of personal data | 0.9 |
| 3 | Data Processing Agreements (for Non EU-Entity based on "Standard Contractual Clauses") | 0.9 |
| 4 | Mutual Data Processing Agreements | 0.9 |
| 5 | SAP Intra Group Data Protection Agreement (IGA) | 0.9 |
| 6 | SAP performs testing of patch collections | 0.9 |
| 7 | No customer downtime is required | 0.9 |
| 8 | Enterprise Cloud Services (ECS) performs comprehensive testing on verifications of patches based on the SAP CERT Advisory before creating a Mass Change Ticket (MCT) and Send for Change Advisory Board (CAB) Approval. | 0.9 |
| 9 | Vulnerability directly related to missing online security patches | 0.9 |
| 10 | This carries the administrative and operational support traffic from the SAP and it's Infrastructure supplier support and operations staff. | 0.9 |
| 11 | It enables both our customers and internal teams to collect and centralize logs from all systems, applications, and ECS services in use. | 0.9 |
| 12 | LogServ is an ECS service designed for storing and accessing logs. | 0.9 |
| 13 | Customer can subscribe to SAP Data Custodian KMS to BYOK to encrypt HANA LSS. | 0.9 |
| 14 | LogServ service provide customers with access to Application and Infrastructure Logs | 0.9 |
| 15 | Data Lake provides compliant log retention & recovery requirement | 0.9 |
| 16 | Data Lake platform to support both Customers and SAP for log retention and recovery of historical logs | 0.9 |
| 17 | We are offering retention periods between 10 years and one Month. | 0.9 |
| 18 | You can retain your logs indefinitely. | 0.9 |
| 19 | RAVEN is an ECS service that simplifies the management of SAP Application Security and Threats, while delivering 'Security and Compliance' reports and dashboards to customer SIEM systems. | 0.9 |
| 20 | SAP ECS will investigate how we can provide direct customer access in the future | 0.9 |
| 21 | FWaaS has been designed to filter traffic within an ECS landscape. | 0.9 |
| 22 | FWaaS is available for customers with RISE with SAP Private Cloud landscapes on Azure, AWS, and GCP. | 0.9 |
| 23 | FWaaS is specifically designed to filter traffic within the ECS landscape, where customers cannot intervene—such as filtering traffic between a PROD and a NON-PROD subnet. | 0.9 |
| 24 | Backup storage is replicated to secondary location | 0.9 |
| 25 | Backups are run Automatically and Disaster Recovery is Tested Annually | 0.9 |
| 26 | The backup storage of 1 month for productive systems and 14 days for nonproductive systems (as part of the standard S/4HANA private cloud edition offering) will be replicated to an alternate location | 0.9 |
| 27 | Database and log-file backups are stored in a multi-AZ but stay in the designated region. | 0.9 |
| 28 | During Offline DR Testing, the SAP team shuts down the Primary side and provides access to customer on the secondary side to validate the system. | 0.9 |
| 29 | SAP ensures the usage of an adequate internal or external US CERT advisory service for information about new security threats and vulnerabilities for all relevant components of the Cloud Service stack. | 0.9 |
| 30 | Administration is done using shared administrative infrastructure | 0.9 |
| 31 | Each customer landscape are connected to shared management | 0.9 |
| 32 | SAP Manages technical stack and customer has no access to Infrastructure OS. | 0.9 |
| 33 | Customer can integrate it into their SIEM or Log Management system. | 0.8 |
| 34 | You can recover the logs which were retained for you by ECS | 0.8 |
| 35 | Next Generation Firewall supports SPI aware packet | 0.8 |
| 36 | Protect against AWS Region outages. | 0.8 |
| 37 | RPO 30min, RTO 4hrs/12hrs. | 0.8 |
| 38 | SAP Enterprise Cloud Services – operated by SAP on IaaS provider (AWS, Azure or GCP) | 0.8 |
| 39 | for how long will backup and restore services be provided once the contract has concluded? | 0.8 |
| 40 | Is FWaaS supported in HEC3.0-based landscapes? | 0.9 |
| 41 | Protect against AWS Region outages | 0.7 |

#### Concept: Technical System Operations (STANDARD)

| # | Information | Conf. |
|---|-------------|-------|
| 1 | Measures of Data Cross-Border Transfer Security Assessment took effective on September 1st 2022. | 0.9 |
| 2 | Customers can view the patch schedule on the Customer Portal, with deployment managed in a coordinated manner. | 0.9 |
| 3 | Testing and validation are thoroughly documented and reviewed by the Change Advisory Board (CAB). | 0.9 |
| 4 | Identity and access control for business users of the S/4HANA application | 0.9 |
| 5 | CDM = Common Data Model | 0.9 |
| 6 | Additional executions can be purchased via chargeable service tickets. | 0.9 |
| 7 | One time DR drill per year is included as standard offering. | 0.9 |
| 8 | Reverse replication from secondary site to primary site is not offered. | 0.9 |
| 9 | The components deployed in each of the AZ's are symmetrical | 0.9 |
| 10 | Customer manages configuration, implementation, integration, monitoring, application support etc. | 0.9 |
| 11 | do we require communication between non-production (lower) and production environments? | 0.8 |

---

### 2. SAP Cloud ERP

#### Concept: SAP Cloud ERP (CENTRAL)

| # | Information | Conf. |
|---|-------------|-------|
| 1 | The SAP Trust Center is a public-facing website designed to provide unified and easy access to trust related content, such as security, privacy, and compliance. | 0.9 |
| 2 | The essential legal terms that apply to the Cloud Service | 0.9 |
| 3 | The service specific legal terms that apply to the Cloud Service | 0.9 |
| 4 | SAP S/4HANA cloud is GDPR Ready | 0.9 |
| 5 | Patches are listed on the Customer Portal for customer visibility. | 0.9 |
| 6 | This carries all the front-end access network traffic and inter-server application traffic of the SAP Systems. | 0.9 |
| 7 | The ABAP GenAI SDK will be the official client provided by BTP ABAP for consuming LLMs like GPT-4 or SAP-internally trained LLMs via ABAP. | 0.9 |
| 8 | The ABAP GenAI SDK is designed to standardize and facilitate this access to LLMs, providing convenient features for ABAP developers. | 0.9 |
| 9 | SAP Solution is deployed across two Availability Zones (AZ) in a single region for HA/DR. | 0.9 |
| 10 | This depicts the architecture for 99.9 Multi-AZ + LDDR with CS / ERS on Dedicated host. | 0.9 |
| 11 | Breach notification is required | 0.9 |
| 12 | Data Controller (Customer) notifies data protection authorities | 0.9 |
| 13 | Metadata doesn't contain any sensitive data, which also means that no transactional data is stored in the cloud. | 0.9 |
| 14 | When using a live connection, only metadata is stored in the cloud. | 0.9 |
| 15 | Browser will now directly contact the SAP HANA database at the address indicated in the metadata to get data. | 0.9 |
| 16 | Encryption root key and master key generated during installation & HANA version updates | 0.9 |
| 17 | However, access can be selectively enabled for specific systems or services that require it (e.g., external Fiori access or integrations). | 0.9 |
| 18 | By default, no internet-based access is enabled directly from Cloud ERP Private. | 0.9 |
| 19 | By default, there is no Internet based Inbound/Outbound is enabled directly from RISE VNET. | 0.9 |
| 20 | S/4HANA Private Cloud Edition provides connectors and agents that are required to integrate the S/4HANA system with other public cloud solutions from SAP. | 0.9 |
| 21 | The principal account management and tenant isolation in RISE with SAP Cloud ERP Private is identical for AWS, Azure, Google Cloud Platform and IBM Cloud. | 0.9 |
| 22 | Azure Storage Account provides a unique namespace to store and access Azure Storage resources securely. | 0.9 |
| 23 | SAP HANA in-memory database uses HANA Volume Encryption to provide "data-at-rest" encryption for data, log and backup volumes. | 0.8 |
| 24 | SAP Solution is deployed across two AWS regions. | 0.8 |
| 25 | Meeting Data Processor Obligation, Notification without undue delay | 0.8 |
| 26 | Outbound non-HTTPS is possible via SNAT Load Balancer. | 0.8 |
| 27 | this is similar configuration is applicable for Azure and Google Cloud | 0.8 |
| 28 | If I am running SAP S/4HANA on a Hyperscaler, why is it necessary to perform a lift and shift, rather than simply transferring the management of services on the existing Hyperscaler deployment? | 0.8 |

---

### 3. Sécurité

#### Concept: Shared Security Responsibility (CENTRAL)

| # | Information | Conf. |
|---|-------------|-------|
| 1 | Can SAP extend enhanced data center audits for customers in FSI? | 0.9 |
| 2 | My customer is operating in FSI space and are highly regulated | 0.9 |
| 3 | SAP and its sub processors obligations and restrictions to process Personal Data in the provision of the Cloud Service, including: | 0.9 |
| 4 | The customer is responsible for requesting the deployment of non-critical security patches with priorities ranging from 'very high' to 'low'. | 0.9 |
| 5 | SAP reserves the right to apply critical application and operating system security patches. | 0.9 |
| 6 | The purpose of Security Patch Management (SPM) is the mitigation of threats and vulnerabilities within HANA Enterprise Cloud according to the required SAP security standards. | 0.9 |
| 7 | An effective incident management process swiftly addresses any issues with system patches. | 0.9 |
| 8 | Customer is entirely responsible | 0.9 |
| 9 | Providing qualified DC or colocation facility to host the infrastructure; firewall and network traffic controls | 0.9 |
| 10 | Responsible for providing an Internet access point and managing routing and security | 0.9 |
| 11 | Traffic to RISE can be routed via their own Firewall. | 0.9 |
| 12 | Customers are required to configure their firewall to control who is allowed to communicate with SAP systems in the ECS landscape. | 0.9 |
| 13 | They support the identification of known malware using virus signatures, as well as the detection of abnormal behavior through heuristic algorithms and machine learning techniques. | 0.9 |
| 14 | This will prevent the propagation of malware if any of the SAP customer is impacted by malware. | 0.9 |
| 15 | The storage used to store data files, log files and the backup sets are encrypted by default by IaaS provider using Server-Side Encryption (SSE) that uses server managed keys. | 0.9 |
| 16 | All HTTP connections are to be configured with transport layer security (TLS 1.2 and above) | 0.9 |
| 17 | Customer to implement necessary transport layer security for Non-HTTP connections as well such as SAP SNC, SNC enabled RFC etc. | 0.9 |
| 18 | All internet security such as Web Application Firewall are to be managed by the customer in their network. | 0.9 |
| 19 | All HTTP connections must be secured using Transport Layer Security (TLS) version 1.2 or higher. | 0.9 |
| 20 | All internet accesses must be encrypted in transit (via TLS). | 0.9 |
| 21 | Customer must install, own and manage | 0.9 |
| 22 | Publishing such applications to Internet would require mandatory data-in-transit encryption using TLS 1.2 or above using customer provided certificates. | 0.9 |
| 23 | A Web Application Firewall (WAF) is used to secure the internet inbound access. | 0.9 |
| 24 | All such outgoing accesses are to use TLS 1.2 or above based in-transit encryption. | 0.9 |
| 25 | All such outbound connections are based on restricted access control list configured in the security components that are used within the cloud. | 0.9 |
| 26 | Secure Connectivity between SAP managed customer landscape and customer owned landscape on Hyperscaler. | 0.9 |
| 27 | The traffic between the environment supports network layer encryption. | 0.9 |
| 28 | Major security operational topics are implemented and managed globally across all cloud solutions offered by SAP. | 0.9 |
| 29 | RISE roles and responsibilities document as part of the contract describes regular operational tasks in cloud delivery and security aspect is mostly implicit on all of those tasks that SAP performs under our responsibility. | 0.9 |
| 30 | Additional License is required. | 0.9 |
| 31 | Overall cloud security is assured via various contracting assurances such as General Terms & Conditions, Data Processing Agreement and Technical & Organizational Measures. | 0.9 |
| 32 | Access to customer's systems is only possible with 2-factor | 0.9 |
| 33 | Data-at-rest and Data-in-transit encryption to protect customer data at all time. | 0.9 |
| 34 | By default no access to customer's business client (customer managed) unless authorized and granted by customer. | 0.9 |
| 35 | Do we contractually allow customers to undertake penetration testing of the cloud service? | 0.8 |
| 36 | WAF setup only when RISE inbound is allowed from Internet | 0.8 |
| 37 | ISO 27001 | 0.8 |
| 38 | Service Organization Controls Report (Attestation report) SOC 2 | 0.8 |
| 39 | ISAE3402 SOC 1 Type II, ISAE 3000 SOC2 Type II, ISO 27001:2013, ISAE 3000 C5 Type II SOC2: 12 months ISO: 36 months with surveillance audits every 12 months. | 0.8 |

#### Concept: Customer VNETS/VPC (STANDARD)

| # | Information | Conf. |
|---|-------------|-------|
| 1 | SAP establishes separate Customer environments, implements micro segmentation to restrict the flow of east-west traffic to prevent flat network. | 0.9 |
| 2 | RISE Virtual Network (VNET) is created with an RFC 1918 Private IP Address range. | 0.9 |
| 3 | Traffic is encrypted with TLS1.2 encryption. | 0.9 |
| 4 | Application Load Balancer will be able to route traffic to the Web Dispatcher in the production subnet. | 0.9 |
| 5 | Virtual network peering creates network connectivity between two virtual networks (VPC for AWS or VNet for Azure), which are owned by different account holders. | 0.9 |
| 6 | AAG = Azure Application gateway | 0.9 |
| 7 | WAF = Web Application Firewall | 0.9 |
| 8 | Point-to-Site (P2S) scenario is not supported. | 0.9 |
| 9 | Customers can use IPSec based Site-to-Site (S2S) VPN over Internet to connect to their dedicated virtual network in the cloud. | 0.9 |
| 10 | A dedicated private connection with redundancy is recommended for accessing productive workload as it ensures quality of service and higher availability service levels. | 0.9 |
| 11 | Hyperscaler provided solutions such as AWS Direct Connect, Azure ExpressRoute and GCP Cloud Interconnect can be used to establish such network connection. | 0.9 |
| 12 | VPN configurations are very much dependant on the Hyperscaler platform of deployment. | 0.9 |
| 13 | Each customer receives their own isolated landscape Virtual Network created | 0.9 |
| 14 | Subscriptions/Account/Projects are isolated containers for resources, billing, and quotas. | 0.9 |
| 15 | Using dedicated connectivity options such as AWS Direct Connect, Azure Express Route and Google Cloud Interconnect, customer can establish dedicated connectivity from customer on-premise network to RISE with SAP S/4HANA Cloud. | 0.8 |
| 16 | Is it necessary for SAP Development, QA, and Production environments to be part of the same Virtual Network (VPC or VNET)? | 0.8 |
| 17 | VPC must be whitelisted. | 0.8 |
| 18 | VPC Peering is used to connect Primary with DR Region. | 0.8 |
| 19 | Inbound traffic from Internet can be allowed and will be screened via WAF. | 0.8 |
| 20 | VPC Peering. | 0.7 |
| 21 | Dedicated Private Connection. | 0.7 |

#### Concept: Logical Separation (STANDARD)

| # | Information | Conf. |
|---|-------------|-------|
| 1 | The customer requires compartmentalization | 0.9 |
| 2 | The storage and admin networks will not be accessible from the customer access network. | 0.9 |
| 3 | Each customer is isolated from the SAP Corporate Network | 0.9 |
| 4 | This tenant is the central identity and access management boundary for all cloud operations. | 0.9 |
| 5 | NSGs act as a second firewall vendor in the landscape and are sometimes required for additional functionality like Flow Logs in Azure. | 0.8 |

---

## Observations Qualitatives

### Points Positifs
1. **Couverture complète** de la sécurité cloud (TLS, WAF, encryption at-rest/in-transit)
2. **Réglementations couvertes**: GDPR, China Data Laws, India Companies Act
3. **Services SAP bien documentés**: ECS, LogServ, RAVEN, FWaaS, Data Custodian KMS
4. **SLA/DR clairs**: RPO 30min, RTO 4hrs/12hrs, Multi-AZ, backup 1 mois prod / 14 jours non-prod

### Points d'Attention (ChatGPT)
1. **Anchor Resolution faible**: 155/1300 = 11.9% (cible: ≥95%)
2. **Fragments présents**: "VPC Peering.", "ISO 27001", "CDM = Common Data Model" - pas des assertions complètes
3. **Questions mélangées aux assertions**: "Is FWaaS supported in HEC3.0?" devrait être filtré

### Recommandations Pipeline
1. Ajouter filtre "assertion minimale" (prédicat requis)
2. Améliorer anchor resolution (mapping chunk → docitem)
3. Filtrer les questions (pattern "Is it...", "Do we...")

---

## Comparaison Avant/Après Fix

| Métrique | Avant (bug strict) | Après (fix) | Delta |
|----------|-------------------|-------------|-------|
| Assertions extraites | 893 | 1465 | +64% |
| CONDITIONAL promues | 0 | 1083 | +∞ |
| Informations | 77 | **155** | **+101%** |
| InformationMVP | 124 | **1292** | **+942%** |

---

*Document généré par OSMOSE Pipeline V2 - Pass 1 (strict_promotion=false)*
*Date: 2026-01-26*
