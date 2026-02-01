# Analyse Extraction Knowledge Graph - RISE with SAP Cloud ERP Private

**Document source:** 020_RISE_with_SAP_Cloud_ERP_Private_full.pptx
**Date extraction:** 2026-01-28
**Pipeline:** OSMOSE v2 (Batch Thématique + Pointer-Based Extraction)

---

## 1. Subject

| Propriété | Valeur |
|-----------|--------|
| **Nom** | SAP Cloud ERP Private |
| **Type** | Documentation technique SAP |
| **Langue** | Anglais |

---

## 2. Vue d'ensemble

| Métrique | Valeur |
|----------|--------|
| Thèmes | 6 |
| Concepts | 42 |
| Informations | 152 |
| Relations inter-concepts | 13 |
| Concepts avec informations | 19 (45%) |
| Concepts sans information | 23 (55%) |

---

## 3. Thèmes et Concepts

### 3.1 Capacity Management (4 concepts, 69 informations)

| Rôle | Concept | Infos |
|------|---------|-------|
| CONTEXTUAL | Infrastructure Security | **68** |
| CONTEXTUAL | Information Security Management | 1 |
| CONTEXTUAL | Business Continuity Management | 0 |
| CONTEXTUAL | Monitoring & Alerting | 0 |

**Observation:** Ce thème est dominé par "Infrastructure Security" qui concentre 68 informations (45% du total). Les 3 autres concepts n'ont quasi pas d'informations liées.

---

### 3.2 Deployment Models (8 concepts, 14 informations)

| Rôle | Concept | Infos |
|------|---------|-------|
| STANDARD | IaaS Provider | 6 |
| CONTEXTUAL | SAP Cloud ERP Private | 3 |
| CONTEXTUAL | Compliance Scans | 2 |
| CONTEXTUAL | SAP Enterprise Cloud Services Policies | 2 |
| CONTEXTUAL | SAP Global Security Policies | 1 |
| CONTEXTUAL | Customer Provided Transit Gateway | 0 |
| CONTEXTUAL | Secure Default Deployment | 0 |
| CONTEXTUAL | Transit Gateway | 0 |

**Observation:** Distribution plus équilibrée. "IaaS Provider" est le concept principal avec 6 informations.

---

### 3.3 End Point Protection (6 concepts, 43 informations)

| Rôle | Concept | Infos |
|------|---------|-------|
| STANDARD | Secured Admin Access Point | 0 |
| CONTEXTUAL | Access Controls | **34** |
| CONTEXTUAL | Vulnerability Assessment | 5 |
| CONTEXTUAL | Penetration Testing | 4 |
| CONTEXTUAL | Hosted Firewall | 0 |
| CONTEXTUAL | Patch Management | 0 |

**Observation:** "Access Controls" concentre 34 informations (79% du thème). Le concept STANDARD "Secured Admin Access Point" n'a aucune information liée.

---

### 3.4 Patch Management (5 concepts, 0 informations)

| Rôle | Concept | Infos |
|------|---------|-------|
| **CENTRAL** | **Patch Management Process** | 0 |
| STANDARD | Certification for BCM Systems | 0 |
| CONTEXTUAL | Access Control Mechanism | 0 |
| CONTEXTUAL | Hyperscaler Contract Management | 0 |
| CONTEXTUAL | Incident Management Services | 0 |

**Observation:** Aucune information liée à ce thème malgré un concept CENTRAL. Problème potentiel de linking ou contenu insuffisant dans le document source.

---

### 3.5 Security Operations (11 concepts, 7 informations)

| Rôle | Concept | Infos |
|------|---------|-------|
| STANDARD | forward-looking statements | 2 |
| STANDARD | Security Monitoring | 2 |
| STANDARD | Certification for Information Security Management Systems | 1 |
| STANDARD | Cloud Operational Security | 1 |
| STANDARD | Shared Security Governance | 1 |
| STANDARD | Security Incident Management | 0 |
| STANDARD | Security Operations and Compliance | 0 |
| STANDARD | Security Roles and Responsibilities | 0 |
| STANDARD | customer firewall whitelisting | 0 |
| STANDARD | internal use information | 0 |
| STANDARD | traffic validation requirement | 0 |
| CONTEXTUAL | Security Monitoring | 0 |

**Observation:** Beaucoup de concepts STANDARD (10) mais peu d'informations. "forward-looking statements" semble être un faux positif (concept non pertinent au domaine).

---

### 3.6 Tenancy Model Shared Security Responsibility (8 concepts, 19 informations)

| Rôle | Concept | Infos |
|------|---------|-------|
| CONTEXTUAL | Security Assurance Policies | 9 |
| CONTEXTUAL | TLS Encryption Requirement | 4 |
| CONTEXTUAL | Multi-cloud Security Best Practices | 3 |
| CONTEXTUAL | Security Operations Management | 3 |
| CONTEXTUAL | Cloud Service Group Compliance | 0 |
| CONTEXTUAL | SAP Cloud ERP Private Deployment Models | 0 |
| CONTEXTUAL | Shared Security Responsibility | 0 |
| CONTEXTUAL | Technical & Organizational Measures | 0 |

**Observation:** "Security Assurance Policies" est le concept le plus riche avec 9 informations. Distribution relativement équilibrée.

---

## 4. Top 10 Concepts par Richesse Informationnelle

| Rang | Concept | Thème | Informations |
|------|---------|-------|--------------|
| 1 | Infrastructure Security | Capacity Management | 68 |
| 2 | Access Controls | End Point Protection | 34 |
| 3 | Security Assurance Policies | Tenancy Model... | 9 |
| 4 | IaaS Provider | Deployment Models | 6 |
| 5 | Vulnerability Assessment | End Point Protection | 5 |
| 6 | TLS Encryption Requirement | Tenancy Model... | 4 |
| 7 | Penetration Testing | End Point Protection | 4 |
| 8 | Multi-cloud Security Best Practices | Tenancy Model... | 3 |
| 9 | SAP Cloud ERP Private | Deployment Models | 3 |
| 10 | Security Operations Management | Tenancy Model... | 3 |

**Concentration:** Les 2 premiers concepts (Infrastructure Security + Access Controls) détiennent 67% des informations (102/152).

---

## 5. Relations Inter-Concepts (Navigabilité du Graphe)

### 5.1 Graphe des Relations

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RELATIONS INTER-CONCEPTS                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Information Security Management ──┬──► Infrastructure Security ◄──┬──    │
│                                     │                               │       │
│   SAP Enterprise Cloud Services ────┘                               │       │
│   Policies                                                          │       │
│                                                                     │       │
│   SAP Global Security Policies ─────────────────────────────────────┘       │
│                                                                             │
│   Security Assurance Policies ──────► SAP Global Security Policies          │
│            │                                                                │
│            └────────────────────────► Infrastructure Security               │
│                                                                             │
│   ─────────────────────────────────────────────────────────────────────     │
│                                                                             │
│   Penetration Testing ──────────────► Access Controls ◄─────────────────    │
│                                              ▲                              │
│   Vulnerability Assessment ─────────────────┘                              │
│                                                                             │
│   Access Controls ──────────────────► Infrastructure Security               │
│                                                                             │
│   ─────────────────────────────────────────────────────────────────────     │
│                                                                             │
│   Compliance Scans ─────────────────► SAP Enterprise Cloud Services         │
│                                       Policies                              │
│                                                                             │
│   Security Operations Management ───► SAP Cloud ERP Private ◄───────────    │
│                                              ▲                              │
│   Shared Security Governance ───────────────┘                              │
│                                                                             │
│   Information Security Management ──► forward-looking statements            │
│            │                                                                │
│            └────────────────────────► customer firewall whitelisting        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Liste des Relations

| Source | Relation | Cible |
|--------|----------|-------|
| Access Controls | CONCEPT_RELATION | Infrastructure Security |
| Compliance Scans | CONCEPT_RELATION | SAP Enterprise Cloud Services Policies |
| Information Security Management | CONCEPT_RELATION | Infrastructure Security |
| Information Security Management | CONCEPT_RELATION | forward-looking statements |
| Information Security Management | CONCEPT_RELATION | customer firewall whitelisting |
| Penetration Testing | CONCEPT_RELATION | Access Controls |
| SAP Enterprise Cloud Services Policies | CONCEPT_RELATION | Infrastructure Security |
| SAP Global Security Policies | CONCEPT_RELATION | Infrastructure Security |
| Security Assurance Policies | CONCEPT_RELATION | SAP Global Security Policies |
| Security Assurance Policies | CONCEPT_RELATION | Infrastructure Security |
| Security Operations Management | CONCEPT_RELATION | SAP Cloud ERP Private |
| Shared Security Governance | CONCEPT_RELATION | SAP Cloud ERP Private |
| Vulnerability Assessment | CONCEPT_RELATION | Access Controls |

### 5.3 Analyse de la Navigabilité

| Métrique | Valeur |
|----------|--------|
| Relations totales | 13 |
| Concepts connectés | 15/42 (36%) |
| Concepts isolés | 27/42 (64%) |
| Hub principal (in-degree) | Infrastructure Security (5 liens entrants) |
| Hub secondaire | Access Controls (3 liens entrants) |
| Hub secondaire | SAP Cloud ERP Private (2 liens entrants) |

**Problème identifié:** 64% des concepts sont isolés (aucune relation). Le graphe est fragmenté en plusieurs composantes non connectées.

---

## 6. Exemples d'Informations Extraites

### 6.1 Infrastructure Security (échantillon)

| Type | Information |
|------|-------------|
| FACTUAL | Administration is done using shared administrative infrastructure |
| FACTUAL | Identity and access controls of SAP administrators for managing and operating the environment |
| FACTUAL | Hardware, hypervisor, virtualization infrastructure. Partnerships with Lenovo, HP, and Dell to supply, maintain, and manage |
| FACTUAL | SAP is responsible for cloud services reference architecture |
| DEFINITIONAL | LogServ is an ECS service designed for storing and accessing logs. It enables both our customers and internal teams to collect and centralize logs from all systems, applications, and ECS services in use. |

### 6.2 Security Assurance Policies (échantillon)

| Type | Information |
|------|-------------|
| PERMISSIVE | Customer can choose to create service requests for patching the respective systems based on the downtime schedule convenient for the customer. |
| PRESCRIPTIVE | The customer requires compartmentalization |
| CONDITIONAL | Additionally, for how long will backup and restore services be provided once the contract has concluded? |
| CONDITIONAL | If data is corrupted during backup or any other scenario, is there a data availability SLA? |
| FACTUAL | The customer traffic can be routed via customer owned Proxy at their on-premise network. |

---

## 7. Diagnostics et Recommandations

### 7.1 Points Positifs

1. **Extraction thématique cohérente** - Les 6 thèmes couvrent bien le périmètre sécurité/infrastructure SAP
2. **Diversité des types d'information** - FACTUAL, PRESCRIPTIVE, PERMISSIVE, CONDITIONAL, DEFINITIONAL
3. **Relations sémantiques pertinentes** - Les liens entre concepts semblent logiques (ex: Penetration Testing → Access Controls)

### 7.2 Problèmes Identifiés

| Problème | Impact | Recommandation |
|----------|--------|----------------|
| **Concentration excessive** | 2 concepts détiennent 67% des informations | Affiner le linking pour redistribuer |
| **Concepts vides** | 23 concepts (55%) sans information | Vérifier le linking ou supprimer les concepts non ancrés |
| **Graphe fragmenté** | 64% concepts isolés | Améliorer l'extraction des relations |
| **Faux positifs** | "forward-looking statements" n'est pas pertinent | Améliorer le filtrage des concepts |
| **Thème vide** | "Patch Management" a 0 informations malgré un concept CENTRAL | Investiguer le document source |

### 7.3 Questions pour Validation

1. Le concept "Infrastructure Security" devrait-il être éclaté en sous-concepts plus spécifiques ?
2. Les concepts sans information doivent-ils être conservés ou supprimés ?
3. La relation générique "CONCEPT_RELATION" devrait-elle être typée (PART_OF, REQUIRES, IMPLEMENTS, etc.) ?

---

## 8. Statistiques Techniques

| Métrique | Valeur |
|----------|--------|
| DocItems extraits | 144 |
| Unités analysées | 2091 |
| Concepts LLM (avant validation) | 1090 |
| Concepts validés (après C1) | 1000 |
| Taux ABSTAIN | 8.3% |
| Assertions extraites | 396 |
| Assertions promues | 189 |
| Temps total pipeline | ~32 minutes |

---

*Document généré pour analyse comparative par ChatGPT*
