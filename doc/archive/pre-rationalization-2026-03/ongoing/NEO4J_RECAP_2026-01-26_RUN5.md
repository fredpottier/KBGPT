# Récapitulatif Neo4j - Run du 26/01/2026 (16:09)

## Stats Globales du Run

| Étape | Valeur |
|-------|--------|
| Assertions extraites | 1492 |
| Meta filtrées | 304 |
| **Fragments filtrés** | **349** (nouveau filtre) |
| PROCEDURAL exclues | 8 |
| Promues vers linking | 831 |
| Anchor resolution | 149/831 = **17.9%** |
| cross_docitem | 19 |

---

## Inventaire des Nodes Neo4j

| Type | Count |
|------|-------|
| AssertionLog | 1492 |
| InformationMVP | 831 |
| Information | 149 |
| DocItem | 131 |
| Concept | 10 |
| Theme | 5 |
| ClaimKey | 3 |
| Document | 1 |
| Subject | 1 |

---

## Structure Hiérarchique Complète

### 1. SUBJECT (Racine)

```
Subject: "SAP Cloud ERP Private"
  └─ ID: subj_020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357
```

---

### 2. THEMES (5 thèmes)

| # | Theme | Description |
|---|-------|-------------|
| 0 | Déploiement SAP | Architecture et déploiement des solutions SAP |
| 1 | Modèle de Tenancy | Isolation et gestion des tenants |
| 2 | Services Cloud | Services cloud SAP (ECS, CAS) |
| 3 | Sécurité | Sécurité, conformité et protection des données |
| 4 | Partenaires Technologiques | Hyperscalers et partenaires (AWS, Azure, etc.) |

---

### 3. CONCEPTS (10 concepts)

#### Par Thème

| Theme | Concept | Informations |
|-------|---------|--------------|
| **Déploiement SAP** | Déploiement SAP | 9 |
| | Gestion des systèmes | 20 |
| | Infrastructure Client | 13 |
| **Modèle de Tenancy** | Modèle de Tenancy | 2 |
| **Services Cloud** | Services Cloud | 9 |
| | SAP Cloud Application Services | 4 |
| | SAP Enterprise Cloud Services | 1 |
| **Sécurité** | Sécurité | 70 |
| | Responsabilité partagée | 19 |
| **Partenaires Technologiques** | Partenaires Technologiques | 2 |

#### Relations entre Concepts

| Source | Relation | Target |
|--------|----------|--------|
| Déploiement SAP | ENABLES | SAP Cloud Application Services |
| Partenaires Technologiques | PART_OF | Déploiement SAP |
| Sécurité | REQUIRES | Responsabilité partagée |

---

### 4. INFORMATIONS PAR CONCEPT (149 total)

#### Concept: Sécurité (70 informations)

| Type | Count |
|------|-------|
| FACTUAL | 44 |
| PRESCRIPTIVE | 12 |
| DEFINITIONAL | 9 |
| CONDITIONAL | 4 |
| CAUSAL | 1 |

**Exemples DEFINITIONAL:**
- "Golden images are defined and versioned in accordance with the hardening guidelines."
- "The purpose of Security Patch Management (SPM) is the mitigation of threats and vulnerabilities within HANA Enterprise Cloud according to the required SAP security standards."
- "FWaaS is a Managed Service that brings Enterprise-grade Network Firewalls into ECS Private Cloud Landscapes with support for advanced traffic control and deep packet inspection."
- "RAVEN is an ECS service that simplifies the management of SAP Application Security and Threats, while delivering 'Security and Compliance' reports and dashboards to customer SIEM systems."

**Exemples PRESCRIPTIVE:**
- "All internet accesses must be encrypted in transit (via TLS)."
- "All HTTP connections must be secured using Transport Layer Security (TLS) version 1.2 or higher."
- "Customers are required to configure their firewall to control who is allowed to communicate with SAP systems in the ECS landscape."
- "Data-at-rest and Data-in-transit encryption to protect customer data at all time."

**Exemples FACTUAL:**
- "Hardening guidelines are based on CIS Benchmark Controls."
- "SAP S/4HANA cloud is GDPR Ready"
- "Next Generation Firewall supports SPI aware packet filtering, Intrusion Prevention, Bot Detection"
- "All sessions are monitored and recorded to SAP SIEM"

---

#### Concept: Gestion des systèmes (20 informations)

**Exemples:**
- "The backup is usually done on a weekend, as defined with the customer."
- "LogServ is an ECS service designed for storing and accessing logs."
- "Data Lake platform to support both Customers and SAP for log retention and recovery of historical logs"
- "Unique master keys are generated during installation and update."
- "Master keys are changed in regular intervals."

---

#### Concept: Responsabilité partagée (19 informations)

**Exemples:**
- "SAP Manages technical stack and customer has no access to Infrastructure OS."
- "Customer manages configuration, implementation, integration, monitoring, application support etc"
- "The customer is responsible for requesting the deployment of non-critical security patches with priorities ranging from 'very high' to 'low'."
- "SAP has no access to customer data that resides in SAP business client."

---

#### Concept: Infrastructure Client (13 informations)

**Exemples:**
- "Virtual network peering creates network connectivity between two virtual networks (VPC for AWS or VNet for Azure), which are owned by different account holders."
- "RISE Virtual Network (VNET) is created with an RFC 1918 Private IP Address range."
- "Azure Storage Account provides a unique namespace to store and access Azure Storage resources securely."
- "A dedicated private connection with redundancy is recommended for accessing productive workload."

---

#### Concept: Déploiement SAP (9 informations)

**Exemples:**
- "This is a turn-key cloud offering fully compliant with SAP HEC concierge standard of service, architecture, & security."
- "By default, there is no Internet based Inbound/Outbound is enabled directly from RISE VNET."
- "By default, no internet-based access is enabled directly from Cloud ERP Private."

---

#### Concept: Services Cloud (9 informations)

**Exemples:**
- "Centralized tools and services used by SAP to manage and monitor customer environments."
- "Overall cloud security is assured via various contracting assurances such as General Terms & Conditions, Data Processing Agreement and Technical & Organizational Measures."

---

#### Concept: SAP Cloud Application Services (4 informations)

**Exemples:**
- "Admin access from CGS is via redundant IPsec VPN to Admin VPCs in AWS."

---

#### Concept: Modèle de Tenancy (2 informations)

**Exemples:**
- "This tenant is the central identity and access management boundary for all cloud operations."
- "Each customer is isolated from the SAP Corporate Network"

---

#### Concept: Partenaires Technologiques (2 informations)

**Exemples:**
- "The principal account management and tenant isolation in RISE with SAP Cloud ERP Private is identical for AWS, Azure, Google Cloud Platform and IBM Cloud."
- "VPN configurations are very much dependant on the Hyperscaler platform of deployment."

---

#### Concept: SAP Enterprise Cloud Services (1 information)

**Exemples:**
- "A Web Application Firewall (WAF) is used to secure the internet inbound access."

---

### 5. CLAIMKEYS (3 clés de réponse)

| ClaimKey ID | MVP Liées | Exemples de réponses |
|-------------|-----------|---------------------|
| `ck_general_responsibility` | 15 | "SAP Manages technical stack and customer has no access to Infrastructure OS.", "Customer manages configuration, implementation, integration, monitoring, application support etc" |
| `ck_tls_min_version` | 6 | "All HTTP connections are to be configured with transport layer security (TLS 1.2 and above)", "Traffic is encrypted with TLS1.2 encryption." |
| `ck_encryption_in_transit` | 1 | "All internet accesses must be encrypted in transit (via TLS)." |

---

### 6. INFORMATIONS MVP (831 total)

| Statut | Count |
|--------|-------|
| PROMOTED_LINKED | 806 |
| PROMOTED_UNLINKED | 25 |

**Note:** Les InformationMVP représentent toutes les assertions promues (avant anchor resolution), dont 806 sont liées à un concept et 25 sont orphelines.

---

### 7. ASSERTION LOG (1492 entrées)

| Statut | Count | % |
|--------|-------|---|
| ABSTAINED | 682 | 45.7% |
| REJECTED | 661 | 44.3% |
| PROMOTED | 149 | 10.0% |

**Analyse:**
- **REJECTED (661):** Assertions filtrées par meta-patterns (304) + fragments (349) + autres règles
- **ABSTAINED (682):** Assertions promues mais sans anchor DocItem résolu (principalement no_concept_match)
- **PROMOTED (149):** Assertions complètement résolues avec anchor DocItem

---

## Visualisation de la Hiérarchie

```
Subject: "SAP Cloud ERP Private"
│
├── Theme: Déploiement SAP
│   ├── Concept: Déploiement SAP (9 infos)
│   │   └── Information: "This is a turn-key cloud offering..."
│   │   └── Information: "By default, no internet-based access..."
│   │
│   ├── Concept: Gestion des systèmes (20 infos)
│   │   └── Information: "The backup is usually done on a weekend..."
│   │   └── Information: "LogServ is an ECS service..."
│   │
│   └── Concept: Infrastructure Client (13 infos)
│       └── Information: "Virtual network peering creates..."
│       └── Information: "RISE Virtual Network (VNET) is created..."
│
├── Theme: Modèle de Tenancy
│   └── Concept: Modèle de Tenancy (2 infos)
│       └── Information: "This tenant is the central identity..."
│
├── Theme: Services Cloud
│   ├── Concept: Services Cloud (9 infos)
│   ├── Concept: SAP Cloud Application Services (4 infos)
│   └── Concept: SAP Enterprise Cloud Services (1 info)
│
├── Theme: Sécurité
│   ├── Concept: Sécurité (70 infos) ← DOMINANT
│   │   └── Information: "Golden images are defined..."
│   │   └── Information: "All internet accesses must be encrypted..."
│   │   └── Information: "RAVEN is an ECS service..."
│   │
│   └── Concept: Responsabilité partagée (19 infos)
│       └── Information: "SAP Manages technical stack..."
│       └── Information: "Customer manages configuration..."
│
└── Theme: Partenaires Technologiques
    └── Concept: Partenaires Technologiques (2 infos)
        └── Information: "The principal account management..."
```

---

## Comparaison avec Runs Précédents

| Métrique | Run Avant Filtres | Run Actuel (16:09) | Δ |
|----------|-------------------|---------------------|---|
| Assertions extraites | ~1300 | 1492 | +192 |
| Meta filtrées | ~120 | 304 | +184 |
| Fragments filtrés | 0 | **349** | +349 |
| Promues | ~1300 | 831 | -469 |
| Anchor resolution % | 11.9% | **17.9%** | +6% |
| Informations créées | 155 | 149 | -6 |

**Observations:**
1. **Filtre fragment actif** : 349 assertions non-informatives filtrées
2. **Amélioration qualité** : Moins d'assertions promues mais de meilleure qualité
3. **Anchor resolution améliorée** : 17.9% vs 11.9% (ratio meilleur car base plus propre)
4. **Informations stables** : ~149 informations finales (similaire à avant)

---

## Points d'Amélioration Identifiés

### Priorité 1: Anchor Resolution (cible: 80%)
- Actuellement: 17.9% (149/831)
- Problème: 682 assertions en ABSTAINED (no_concept_match principalement)
- Action: Améliorer le linking sémantique assertion↔concept

### Priorité 2: Qualité des Concepts
- 10 concepts identifiés avec répartition inégale
- "Sécurité" capture 70/149 = 47% des informations
- Action: Affiner la granularité des concepts

### Priorité 3: ClaimKey Coverage
- Seulement 3 ClaimKeys avec 22 InformationMVP liées
- Action: Enrichir le catalogue de ClaimKeys

---

*Généré le 26/01/2026 à 16:10*
