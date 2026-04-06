# Extraction Exhaustive - RISE with SAP Cloud ERP Private Security

**Document source:** `020_RISE_with_SAP_Cloud_ERP_Private_full.pdf`
**Document ID:** `020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357`
**Date d'extraction:** 2026-01-26
**Pipeline:** OSMOSE Pipeline V2 - Pass 1

---

## Sujet Principal

**SAP Cloud ERP Private** - Documentation de sécurité et conformité pour RISE with SAP S/4HANA Cloud, private edition.

---

## Structure Thématique

| # | Thème | Concepts associés |
|---|-------|-------------------|
| 1 | Contrôle de version | version control |
| 2 | Déploiement et gestion | azure storage, hyperscaler, sap cas, sap ecs, shared security |
| 3 | Modèle de déploiement | deployment models, forward-looking statements |
| 4 | Modèle de tenancy | azure storage, customer vm, deployment models, sap cas, security compliance, tenancy model (CENTRAL) |
| 5 | Partenaires technologiques | customer vm, hyperscaler, partners, version control |
| 6 | Responsabilité partagée | cloud solutions, partners, sap cloud, tenancy model (CENTRAL) |
| 7 | Responsabilité partagée en matière de sécurité | shared security |
| 8 | Stratégie SAP | cloud solutions, forward-looking statements, sap cloud, security professionals |
| 9 | Sécurité et conformité | sap ecs, security compliance, security professionals |

---

## Thèmes et Concepts Détaillés

### 1. Contrôle de version

#### Concept: version control (STANDARD)

**Informations extraites:**

1. "Regulation of the export of 'important' data outside of China" (conf: 0.9)
2. "Restricted access to administrative protocols is enforced." (conf: 0.9)
3. "Shell session timeouts Disabling of insecure legacy protocols." (conf: 0.9)
4. "Packet filtering using tools such as iptables." (conf: 0.9)
5. "Secure management protocol only accessible only via dedicated management networks." (conf: 0.9)
6. "Availability SLA" (conf: 0.9)
7. "Recovery Point Objective" (conf: 0.9)
8. "Incremental Backups" (conf: 0.9)
9. "Recovery Time Objective" (conf: 0.9)
10. "Virtual Private Cloud (VPC)" (conf: 0.9)
11. "By default no access to customer's business client (customer managed) unless authorized and granted by customer" (conf: 0.9)
12. "Attaching Direct Connect or VPN in SAP account to TGW in customer account is not possible." (conf: 0.9)
13. "Transit Gateway is region based and hence customer should have a TGW in the same region of SAP Cloud ERP Private deployment." (conf: 0.9)
14. "Customer must install, own and manage" (conf: 0.9)
15. "A dedicated private connection with redundancy is recommended for accessing productive workload as it ensures quality of service and higher availability service levels." (conf: 0.9)
16. "Publishing such applications to Internet would require mandatory data-in-transit encryption using TLS 1.2 or above using customer provided certificates." (conf: 0.9)
17. "Access to customer's systems is only possible with 2-factor" (conf: 0.9)

---

### 2. Déploiement et gestion

#### Concept: azure storage (STANDARD)

**Informations extraites:**

1. "Requires a telecom license in China" (conf: 0.9)
2. "No telecom license in China required" (conf: 0.9)
3. "Identification of important data shall be informed or publicly released by relevant departments or regions" (conf: 0.9)
4. "Data in electronic form, once tampered, destroyed, leaked or illegally obtained/used, may endanger national security and public interests." (conf: 0.9)
5. "Rule 3(1) of the Accounts Rules has been amended to provide that the books of account and other relevant books and papers maintained in an electronic mode should remain accessible in India, at all times so as to be usable for subsequent reference." (conf: 0.9)
6. "Rule 3(5) of the Accounts Rules requires every company to maintain the back-up of the books of account and other relevant books and papers in an electronic mode on servers physically located in India on a daily basis (earlier periodic basis) even in cases where such backups are maintained at a place outside India." (conf: 0.9)
7. "A definition of 'important' data is difficult and has to be analysed case by case. Examples would be critical infrastructures, energy related infrastructures and data, military goods, etc." (conf: 0.9)
8. "The purpose of Security Patch Management (SPM) is the mitigation of threats and vulnerabilities within HANA Enterprise Cloud according to the required SAP security standards." (conf: 0.9)
9. "The customer is responsible for requesting the deployment of non-critical security patches with priorities ranging from 'very high' to 'low'." (conf: 0.9)
10. "The customer is responsible for initiating and implementing 'very high' rated security patches." (conf: 0.9)
11. "SAP reserves the right to apply critical application and operating system security patches." (conf: 0.9)
12. "the audit trail feature has not been tampered with and the audit trail has been preserved by the company as per the statutory requirements for record retention" (conf: 0.9)
13. "Companies Act India, Rules 2014 require Books of Account and Other Records to be Maintained in Electronic Mode on a Server Physically Located in India" (conf: 0.9)
14. "RISE with SAP S/4HANA Cloud, private edition, CDC Option" (conf: 0.9)
15. "LogServ is an ECS service designed for storing and accessing logs. It enables both our customers and internal teams to collect and centralize logs from all systems, applications, and ECS services in use." (conf: 0.9)
16. "SAP ECS reserves the right to reject requests for an excessively large rule base" (conf: 0.9)

#### Concept: hyperscaler (STANDARD)

**Informations extraites:**

1. "Requires a telecom license in China" (conf: 0.9)
2. "No telecom license in China required" (conf: 0.9)
3. "Attaching Direct Connect or VPN in SAP account to TGW in customer account is not possible." (conf: 0.9)
4. "Transit Gateway is region based and hence customer should have a TGW in the same region of SAP Cloud ERP Private deployment." (conf: 0.9)
5. "Site-to-site IPSEC VPN between an on-premise network and Hyperscale Network. The traffic between the environment supports network layer encryption." (conf: 0.9)
6. "Virtual network peering creates network connectivity between two virtual networks (VPC for AWS or VNet for Azure), which are owned by different account holders." (conf: 0.9)

#### Concept: sap cas (STANDARD)

**Informations extraites:**

1. "The amendments require an additional disclosure relating to the name and address of the person in control of the books of account and other books and papers in India, where the service provider is located outside India" (conf: 0.9)
2. "Rule 3(6) of the Accounts Rules requires disclosure (such as name, internet protocol address and location of service provider) by a company to the Registrar of Companies (ROC) in case a service provider has been used for maintenance of books of account in an electronic form." (conf: 0.9)
3. "LogServ is an additional ECS Security service to store and access your Infrastructure (OS, DB, Proxy, etc) logs. The service allows customers to collect & centralize the Infra logs from all supported systems within the customer's RISE landscape. HANA business application logs are out-ofscope for this service." (conf: 0.9)
4. "SAP will use reasonable endeavors" (conf: 0.9)
5. "Customer is entirely responsible" (conf: 0.9)
6. "Responsible for providing an Internet access point and managing routing and security" (conf: 0.9)
7. "Perform VAPT for custom applications; customer to provide downtime for infra patching" (conf: 0.9)
8. "Vulnerability arising due to weak configuration and security parameters" (conf: 0.9)
9. "Vulnerability directly related to missing offline security patches of OS" (conf: 0.9)
10. "Data Controller notifies data protection authorities" (conf: 0.9)
11. "Use secure configuration of services and deletion of nonrequired user accounts." (conf: 0.9)

#### Concept: sap ecs (STANDARD)

**Informations extraites:**

1. "LogServ is an additional ECS Security service to store and access your Infrastructure (OS, DB, Proxy, etc) logs. The service allows customers to collect & centralize the Infra logs from all supported systems within the customer's RISE landscape." (conf: 0.9)
2. "LogServ is an ECS service designed for storing and accessing logs. It enables both our customers and internal teams to collect and centralize logs from all systems, applications, and ECS services in use." (conf: 0.9)
3. "RAVEN is an ECS service that simplifies the management of SAP Application Security and Threats, while delivering 'Security and Compliance' reports and dashboards to customer SIEM systems." (conf: 0.9)
4. "Enhanced HA (SLA 99.9%) Pacemaker Reference Architecture" (conf: 0.9)
5. "The restore requestor must use the corresponding template and provide the necessary information." (conf: 0.9)
6. "Availability SLA" (conf: 0.9)
7. "Recovery Point Objective" (conf: 0.9)
8. "Recovery Time Objective" (conf: 0.9)
9. "Golden images are defined and versioned in accordance with the hardening guidelines." (conf: 0.9)

#### Concept: shared security (STANDARD)

**Informations extraites:**

1. "RISE with SAP S/4HANA cloud, private edition" (conf: 0.9)

---

### 3. Modèle de déploiement

#### Concept: deployment models (STANDARD)

*Voir Modèle de tenancy pour les informations*

#### Concept: forward-looking statements (STANDARD)

**Informations extraites:**

1. "Readers are cautioned not to place undue reliance on these forward-looking statements, which speak only as of their dates, and they should not be relied upon in making purchasing decisions." (conf: 0.9)
2. "It is the responsibility of the management of a company to identify elements of its 'books of account' and 'other relevant books and papers'." (conf: 0.9)
3. "ALB = Application Load Balancer" (conf: 0.9)
4. "WAF = Web Application Firewall" (conf: 0.9)
5. "SAP has no obligation to pursue any course of business outlined in this presentation or any related document, or to develop or release any functionality mentioned therein." (conf: 0.9)
6. "SAP assumes no responsibility for errors or omissions in this presentation, except if such damages were caused by SAP's intentional or gross negligence." (conf: 0.9)

---

### 4. Modèle de tenancy

#### Concept: tenancy model (CENTRAL) ⭐

**Informations extraites:**

1. "RISE with SAP S/4HANA Cloud, private edition, CDC Option" (conf: 0.9)

#### Concept: customer vm (STANDARD)

**Informations extraites:**

1. "The customer requires compartmentalization" (conf: 0.9)
2. "Customer is entirely responsible" (conf: 0.9)
3. "Virtual Private Cloud (VPC)" (conf: 0.9)
4. "ALB = Application Load Balancer" (conf: 0.9)
5. "WAF = Web Application Firewall" (conf: 0.9)
6. "Any 'important' data collected from China by customer has to be stored in China" (conf: 0.9)
7. "SAP will make reasonable efforts to provide customers with 48 hours advance notice of critical patch deployment, unless a shorter notice period is necessary." (conf: 0.9)

#### Concept: security compliance (STANDARD)

*Voir Sécurité et conformité pour les informations détaillées*

---

### 5. Partenaires technologiques

#### Concept: partners (STANDARD)

**Informations extraites:**

1. "Site-to-site IPSEC VPN between an on-premise network and Hyperscale Network." (conf: 0.9)
2. "Virtual network peering creates network connectivity between two virtual networks (VPC for AWS or VNet for Azure), which are owned by different account holders." (conf: 0.9)

---

### 6. Responsabilité partagée

#### Concept: cloud solutions (STANDARD)

**Informations extraites:**

1. "RISE with SAP S/4HANA cloud, private edition" (conf: 0.9)
2. "FWaaS cannot be used to replace the customer's responsibility in this area." (conf: 0.9)
3. "customers are advised to have at least two subnets or more." (conf: 0.9)
4. "VPCs from customer's own subscription cannot be attached to SAP's TGW in any of these scenarios" (conf: 0.9)

#### Concept: sap cloud (STANDARD)

**Informations extraites:**

1. "Defines the cloud service specific system availability, uptime, update windows, credits and others" (conf: 0.9)
2. "Vulnerability arising due to weak configuration and security parameters" (conf: 0.9)
3. "Vulnerability directly related to missing offline security patches of OS" (conf: 0.9)
4. "Identity and access control for business users of the S/4HANA application" (conf: 0.9)
5. "Responsible for providing an Internet access point and managing routing and security" (conf: 0.9)
6. "Perform VAPT for custom applications; customer to provide downtime for infra patching" (conf: 0.9)
7. "SAP ECS reserves the right to reject requests for an excessively large rule base" (conf: 0.9)
8. "In a typical design, customers are advised to have at least two subnets or more." (conf: 0.9)
9. "Golden images are defined and versioned in accordance with the hardening guidelines." (conf: 0.9)
10. "Restricted access to administrative protocols is enforced." (conf: 0.9)
11. "Secure management protocol only accessible only via dedicated management networks." (conf: 0.9)
12. "Shell session timeouts Disabling of insecure legacy protocols." (conf: 0.9)
13. "Packet filtering using tools such as iptables." (conf: 0.9)
14. "Enforcement of strong password policies." (conf: 0.9)
15. "Locking of system and service user accounts." (conf: 0.9)
16. "Data transfer outside of China has to be validated and certified by Chinese authorities (CAC security assessment)" (conf: 0.9)
17. "Network Level" (conf: 0.8)
18. "Operating Systems and Database Level" (conf: 0.8)

---

### 7. Responsabilité partagée en matière de sécurité

#### Concept: shared security (STANDARD)

**Informations extraites:**

1. "RISE with SAP S/4HANA cloud, private edition" (conf: 0.9)

---

### 8. Stratégie SAP

#### Concept: security professionals (STANDARD)

**Informations extraites:**

1. "One time DR drill per year is included as standard offering. Additional executions can be purchased via chargeable service tickets." (conf: 0.9)
2. "Implement Network Security controls like Dedicated Network Connection, WAF, Security Groups. Load Balancers" (conf: 0.9)
3. "Periodic patching of all Internet Facing Web Applications, Malware Protection Enabled" (conf: 0.9)
4. "SAP establishes separate Customer environments, implements micro segmentation to restrict the flow of east-west traffic to prevent flat network. This will prevent the propagation of malware if any of the SAP customer is impacted by malware." (conf: 0.9)
5. "SAP ensures the usage of an adequate internal or external US CERT advisory service for information about new security threats and vulnerabilities for all relevant components of the Cloud Service stack." (conf: 0.9)
6. "Only use an in-date presentation downloaded from Cyber Security Hub - Golden Assets" (conf: 0.9)

---

### 9. Sécurité et conformité

#### Concept: security compliance (STANDARD)

**Informations extraites (35 items):**

**Confidentialité et droits:**
1. "The information in this presentation is confidential and proprietary to SAP and may not be disclosed without the permission of SAP." (conf: 0.9)
2. "All rights reserved." (conf: 0.9)

**Chiffrement et TLS:**
3. "All internet accesses must be encrypted in transit (via TLS)" (conf: 0.9)
4. "All HTTP connections must be secured using Transport Layer Security (TLS) version 1.2 or higher." (conf: 0.9)
5. "All HTTP connections are to be configured with transport layer security (TLS 1.2 and above)" (conf: 0.9)
6. "Customer to implement necessary transport layer security for Non-HTTP connections as well such as SAP SNC, SNC enabled RFC etc." (conf: 0.9)

**WAF et sécurité réseau:**
7. "WAF setup only when RISE inbound is allowed from Internet" (conf: 0.9)
8. "All internet security such as Web Application Firewall are to be managed by the customer in their network." (conf: 0.9)
9. "Implement Network Security controls like Dedicated Network Connection, WAF, Security Groups. Load Balancers" (conf: 0.9)

**Authentification:**
10. "SAP Secure Login Service for SAP GUI" (conf: 0.9)

**Chiffrement des données:**
11. "HANA Data Encryption – AES-256-CBC algorithm" (conf: 0.9)

**Connexion dédiée:**
12. "A dedicated private connection with redundancy is recommended for accessing productive workload as it ensures quality of service and higher availability service levels." (conf: 0.9)

**Segmentation et isolation:**
13. "SAP establishes separate Customer environments, implements micro segmentation to restrict the flow of east-west traffic to prevent flat network. This will prevent the propagation of malware if any of the SAP customer is impacted by malware." (conf: 0.9)

**Patching:**
14. "Periodic patching of all Internet Facing Web Applications, Malware Protection Enabled" (conf: 0.9)
15. "SAP reserves the right to apply critical application and operating system security patches." (conf: 0.9)
16. "SAP will make reasonable efforts to provide customers with 48 hours advance notice of critical patch deployment, unless a shorter notice period is necessary." (conf: 0.9)
17. "The customer is responsible for initiating and implementing 'very high' rated security patches." (conf: 0.9)
18. "The customer is responsible for requesting the deployment of non-critical security patches with priorities ranging from 'very high' to 'low'." (conf: 0.9)
19. "The purpose of Security Patch Management (SPM) is the mitigation of threats and vulnerabilities within HANA Enterprise Cloud according to the required SAP security standards." (conf: 0.9)

**GDPR et notification de brèche:**
20. "Meeting Data Processor Obligation, Notification without undue delay" (conf: 0.9)
21. "Requires approval from Cyber Legal via CISA Ticket for any non-standard breach notification timelines" (conf: 0.9)
22. "Data Controller notifies data protection authorities" (conf: 0.9)

**Centre de sécurité:**
23. "SAP Internal Cyber Security Centre, dedicated to identifying & mitigating Cyber Security risks, issues & challenges" (conf: 0.9)

**Audit et conformité:**
24. "Security Audit & Compliance" (conf: 0.9)
25. "Audits and compliance of cloud services" (conf: 0.9)
26. "the audit trail feature has not been tampered with and the audit trail has been preserved by the company as per the statutory requirements for record retention" (conf: 0.9)

**Réglementation Inde (Companies Act):**
27. "Books of Account and Other Records to be Maintained in Electronic Mode on a Server Physically Located in India" (conf: 0.9)
28. "Rule 3(1) of the Accounts Rules has been amended to provide that the books of account and other relevant books and papers maintained in an electronic mode should remain accessible in India, at all times so as to be usable for subsequent reference." (conf: 0.9)
29. "Rule 3(5) of the Accounts Rules requires every company to maintain the back-up of the books of account and other relevant books and papers in an electronic mode on servers physically located in India on a daily basis (earlier periodic basis) even in cases where such backups are maintained at a place outside India." (conf: 0.9)
30. "Rule 3(6) of the Accounts Rules requires disclosure (such as name, internet protocol address and location of service provider) by a company to the Registrar of Companies (ROC) in case a service provider has been used for maintenance of books of account in an electronic form." (conf: 0.9)
31. "The amendments require an additional disclosure relating to the name and address of the person in control of the books of account and other books and papers in India, where the service provider is located outside India" (conf: 0.9)
32. "The disclosure relating to the name and address of the person in control of the books of account and other books and papers in India, where the service provider is located outside India should include IP details and address (even where the service provider is a cloud based service provider)." (conf: 0.9)
33. "It is the responsibility of the management of a company to identify elements of its 'books of account' and 'other relevant books and papers'." (conf: 0.9)

**Réglementation Chine (Data Security):**
34. "Data transfer outside of China has to be validated and certified by Chinese authorities ( CAC security assessment )" (conf: 0.9)
35. "Any 'important' data collected from China by customer has to be stored in China" (conf: 0.9)
36. "Regulation of the export of 'important' data outside of China" (conf: 0.9)
37. "Identification of important data shall be informed or publicly released by relevant departments or regions" (conf: 0.9)

**Trust Center:**
38. "The SAP Trust Center is a public-facing website designed to provide unified and easy access to trust related content, such as security, privacy, and compliance." (conf: 0.9)

---

## Statistiques d'Extraction

| Métrique | Valeur |
|----------|--------|
| **Thèmes** | 10 |
| **Concepts** | 15 |
| **Informations** | 154 |
| **Concept central** | tenancy model |
| **Confidence moyenne** | 0.9 |

### Distribution des concepts par thème

```
Sécurité et conformité     ████████████████████████████████ 38 infos
Déploiement et gestion     ████████████████████ 22 infos
Contrôle de version        ████████████████ 17 infos
Responsabilité partagée    ██████████████ 18 infos
Modèle de tenancy          ████████ 8 infos
Stratégie SAP              ██████ 6 infos
Partenaires technologiques ████ 4 infos
Modèle de déploiement      ████ 6 infos
Autres                     ██ reste
```

---

## Notes d'Extraction

1. **Concept CENTRAL**: `tenancy model` identifié comme concept structurant du document
2. **Thème dominant**: Sécurité et conformité avec 38 informations
3. **Réglementations couvertes**: GDPR, Companies Act India 2014, China Data Security Law
4. **Services SAP mentionnés**: ECS, LogServ, RAVEN, CAS, Trust Center
5. **Hyperscalers**: AWS (VPC, TGW, Direct Connect) et Azure (VNet) référencés

---

*Document généré par OSMOSE Pipeline V2 - Pass 1*
