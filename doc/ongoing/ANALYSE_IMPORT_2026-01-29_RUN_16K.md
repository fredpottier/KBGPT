# Analyse Import RISE with SAP Cloud ERP Private — Run 16K
**Date :** 2026-01-29 22:00–22:36 UTC
**Document :** 020_RISE_with_SAP_Cloud_ERP_Private_full (363f5357)
**Modèle LLM :** Qwen 2.5 14B AWQ via vLLM (burst EC2 Spot)
**Context window :** 16384 tokens (upgrade depuis 8192)

---

## 1. Métriques Pipeline

| Phase | Métrique | Valeur | Commentaire |
|-------|----------|--------|-------------|
| Pass 0.9 | Sections | 206 | Créées depuis 1030 chunks |
| Pass 0.9 | Résumés LLM | 105 | 66 skipped, 35 verbatim |
| Pass 0.9 | Parallélisation | 10 workers | ~3 min (vs ~36 min séquentiel) |
| Pass 0.9 | GlobalView | 29910 chars | 68% coverage (warning validation) |
| Pass 1.1 | Thèmes | **15** | Structure: CENTRAL |
| Pass 1.1 | char_limit | 25000 | Meta-document complet envoyé (plus de troncature) |
| Pass 1.2 | Concepts bruts | 94 | Avant dédup |
| Pass 1.2 | Concepts uniques | 73 | Après dédup |
| Pass 1.2 | Concepts après frugalité | **58** | Budget adaptatif (206 sections) |
| Pass 1.2 | Termes refusés | 110 | C1 validation |
| Pass 1.2c | Concepts enrichis | 40 | 116 triggers ajoutés |
| Pass 1.3 | Assertions extraites | 267 | assertion_logs |
| Rerank | Calibration | **mode=fallback** | spread=0.050 < seuil 0.05 |
| Rerank | Q10/Q50/Q75 | 0.600/0.645/0.650 | Scores Qwen très serrés |
| Rerank | Liens promus | 107 | |
| Rerank | Signal | 19% (12 liens) | 80% neutre, 5 lex, 7 sem |
| **Final** | **Informations** | **89** | |
| **Final** | **SINK** | **38/89 (43%)** | **Cible 15-30% — HORS CIBLE** |
| **Final** | **Max métier** | 11 (conformité réglementaire, 12%) | OK < 20% |
| **Final** | **Concepts avec infos** | 17/59 (29%) | **42 concepts vides** |

---

## 2. Sujet

| Champ | Valeur |
|-------|--------|
| Nom | SAP Cloud ERP Private Security Hub |
| Texte | Document présente les détails de sécurité et opérationnels pour SAP Cloud ERP Private |
| Structure | CENTRAL |
| Langue | fr |

---

## 3. Thèmes et Concepts

### 3.1 Thèmes avec concepts et informations

#### Theme 1 : Sécurité des données et gestion des accès (9 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| Contrôles de sécurité | 4 | Certifications & Attestations ; SAP Trust Center ; SAP Global Security Policies ; Major security operational topics |
| Gestion des données | 3 | Books of account accessible in India ; Daily backup requirement ; Disclosure of service provider details |
| Assertions non classées (SINK) | 38 | *(voir section SINK)* |
| Gestion des performances des applications | 0 | - |
| Gestion des incidents de sécurité | 0 | - |
| Gestion des fournisseurs | 0 | - |
| Gestion des accès basés sur les rôles | 0 | - |
| Gestion des identités | 0 | - |
| Gestion des vulnérabilités | 0 | - |

#### Theme 2 : Modèle de tenancy et isolation des clients (8 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| Isolation réseau | 6 | Security Patch Management purpose ; Firewall rule base export ; Next Gen Firewall SPI ; Heuristic/ML malware detection ; Secure Login Client redirection ; Customer manages internet security |
| Access control | 3 | DC/colocation firewall controls ; Customer no access to OS ; Network ACL & Security Groups |
| Modèle de tenancy | 3 | Customer compartmentalization ; Landscape integrated into customer ; Customer isolated from SAP Corporate Network |
| Encryption des données | 2 | TLS 1.2+ mandatory ; Azure Storage Account secure namespace |
| Infrastructure administrative partagée | 2 | Shared admin infrastructure ; Shared management landscape |
| Sécurité et conformité | 2 | ROC disclosure requirements ; Dual-region deployment HA/DR |
| Gestion des abonnements clients | 1 | Customer must install/own/manage |
| Gestion des comptes cloud | 0 | - |

#### Theme 3 : Gestion des mises à jour et des correctifs de sécurité (8 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| **Tous les 8 concepts = 0 infos** | 0 | Gestion des instances d'application, Gestion des sous-réseaux, Traitement des applications, Gestion des mises à jour pour les clients, Surveillance et dépannage, Planification mises à jour techniques, Gestion des correctifs de sécurité, Gestion des mises à jour |

#### Theme 4 : Connectivité réseau et haute disponibilité (6 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| Virtual WAN | 4 | 4× "Azure setup, similar for AWS/GCP" (doublons) |
| Web Application Firewall | 1 | WAF, Security Groups, Load Balancers |
| S2S IPSEC VPN | 1 | Rule base size limited |
| Azure Application Gateway | 0 | - |
| Transit VNET | 0 | - |
| Virtual Network Subnets | 0 | - |

#### Theme 5 : Contrôles de sécurité et gestion des incidents (6 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| Contrôle de sécurité DLP | 0 | - |
| Contrôle de sécurité SIEM | 0 | - |
| Certifications de sécurité | 0 | - |
| Protection des données | 0 | - |
| Contrôle d'accès | 0 | - |
| Contrôle de sécurité | 0 | - |

#### Theme 6 : Contrôles de sécurité et conformité réglementaire (5 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| conformité réglementaire | **11** | AZ deployment ; Dual-AZ HA/DR ; Backup encryption AES256 ; Micro-segmentation ; FIPS 140-2 ; Dual encryption layers ; SSE provider-managed keys ; Encryption in Transit ; HANA Volume Encryption AES-256-CBC ; TLS mandatory ; TLS mandatory (doublon) |
| conformité PCI-DSS | 1 | FWaaS on Azure/AWS/GCP |
| gestion physique de la sécurité | 0 | - |
| gestion des politiques de sécurité | 0 | - |
| gestion des risques | 0 | - |

#### Theme 7 : Principes de sécurité et architecture (4 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| infrastructure autonome | 6 | India regulation ; Books of account in India ; Turn-key cloud offering ; Secure management protocol ; Synchronous DB replication ; Annual DR drill |
| groupes d'accès réseau | 0 | - |
| groupes de sécurité | 0 | - |
| pare-feu WebAppFirewall | 0 | - |

#### Theme 8 : Mises à jour et maintenance des systèmes (4 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| **Tous les 4 = 0 infos** | 0 | gestion de la sécurité, gestion des solutions de reprise d'activité, gestion des systèmes d'exploitation, surveillance de la disponibilité |

#### Theme 9 : Opérations techniques et gestion du service (3 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| Gestion des comptes | 1 | Fiori mobile access over Internet |
| Gestion des applications | 0 | - |
| RFC1918 | 0 | - |

#### Theme 10 : Responsabilités partagées en matière de sécurité (2 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| Mises à jour de sécurité | 0 | - |
| Responsabilité partagée sécurité | 0 | - |

#### Theme 11 : Contrôle des accès et gestion des identités (2 concepts)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| Contrôle de conformité | 0 | - |
| Politiques de sécurité | 0 | - |

#### Theme 12 : Infrastructure cloud et gestion des services (1 concept)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| Gestion des bases de données | 0 | - |

#### Theme 13 : Gestion des données et sauvegardes (1 concept)
| Concept | Infos | Contenu informations |
|---------|-------|---------------------|
| Conditions Générales | 0 | - |

#### Theme 14 : Certifications et attestations de sécurité (0 concept)
*(Aucun concept rattaché)*

#### Theme 15 : Contrôle des vulnérabilités et tests de pénétration (0 concept)
*(Aucun concept rattaché)*

---

## 4. Analyse SINK (38 informations)

Le SINK ("Assertions non classées") contient 38/89 informations (43%).

### 4.1 Informations dans le SINK

| # | Information SINK | Concept métier logique manquant |
|---|-----------------|-------------------------------|
| 1 | Requires a telecom license in China | Réglementation Chine |
| 2 | SAP DPA unified approach | Protection des données / DPA |
| 3 | Hyperscaler China regions physically disconnected | Réglementation Chine |
| 4 | Data tampered/destroyed may endanger national security | Réglementation Chine |
| 5 | Data transfer outside China needs CAC assessment | Réglementation Chine |
| 6 | Audit trail preservation requirements | Audit & conformité |
| 7 | Identity and access controls of SAP administrators | Gestion des identités |
| 8 | Hardware, hypervisor partnerships (Lenovo, HP, Dell) | Infrastructure physique |
| 9 | Customer is entirely responsible | Responsabilité partagée |
| 10 | Physical Hardware under SAP Contract | Infrastructure physique |
| 11 | RAVEN ECS service for Security & Compliance reports | SIEM / Monitoring sécurité |
| 12 | Log retention 10 years to 1 month | Gestion des logs |
| 13 | SAP ECS manages Firewall | Gestion pare-feu |
| 14 | Backup storage replicated to secondary location | Sauvegarde & DR |
| 15 | All backup copies stored primary location | Sauvegarde & DR |
| 16 | Backups automatic, DR tested annually | Sauvegarde & DR |
| 17 | EDR, antivirus, anti-malware on all hosts | Endpoint protection |
| 18 | PCI DSS, CCSP compliance requirement | Certifications |
| 19 | SAP ECS manages Firewall (doublon #13) | Gestion pare-feu |
| 20 | EBS/EFS/S3 storage architecture | Infrastructure stockage |
| 21 | Golden images versioned per hardening guidelines | Hardening |
| 22 | Backup 1 month prod / 14 days non-prod replicated | Sauvegarde & DR |
| 23 | Full backup monthly on weekends | Sauvegarde & DR |
| 24 | Active-Active across two AZs with ALB | Haute disponibilité |
| 25 | Pacemaker Cluster for HANA DB and SCS/ERS failover | Haute disponibilité |
| 26 | US CERT advisory service for security threats | Veille sécurité |
| 27 | Encryption root keys in HANA SSFS | Gestion des clés |
| 28 | Keys backed up as part of database backup | Gestion des clés |
| 29 | TLS 1.2+ for all HTTP connections | Encryption en transit |
| 30 | Customer implements TLS for non-HTTP (SNC, RFC) | Encryption en transit |
| 31 | No internet inbound/outbound by default from RISE VNET | Isolation réseau |
| 32 | External access offered per system/service | Connectivité |
| 33 | Dedicated private connection recommended for prod | Connectivité |
| 34 | ISAE3402 SOC1, SOC2, ISO 27001, C5 certifications | Certifications |
| 35 | Secure Infrastructure as Code | DevSecOps |
| 36 | Secure KMS Configuration Enforced | Gestion des clés |
| 37 | SAP manages tech stack, customer no OS access | Responsabilité partagée |
| 38 | Secured admin access point (CGS) with firewall | Gestion des accès |

### 4.2 Analyse du SINK

**Informations qui auraient dû aller vers des concepts existants mais vides :**
- #7 → "Gestion des identités" (0 infos)
- #9, #37 → "Responsabilité partagée sécurité" (0 infos)
- #11 → "Contrôle de sécurité SIEM" (0 infos)
- #17 → "Gestion des vulnérabilités" (0 infos) ou "Protection des données" (0 infos)
- #18, #34 → "Certifications de sécurité" (0 infos)
- #31 → "Isolation réseau" (a déjà 6 infos mais pas celles-ci)
- #13, #19 → "pare-feu WebAppFirewall" (0 infos)

**Informations pour des concepts manquants (non identifiés par le pipeline) :**
- #1, #3, #4, #5 → Réglementation Chine (4 infos)
- #14, #15, #16, #22, #23 → Sauvegarde & Disaster Recovery (5 infos)
- #24, #25 → Haute disponibilité (2 infos)
- #27, #28, #36 → Gestion des clés cryptographiques (3 infos)
- #29, #30 → Encryption en transit (2 infos)
- #12 → Gestion des logs (1 info)

---

## 5. Fragilités identifiées

### 5.1 SINK à 43% (cible 15-30%)

**Cause racine :** La calibration est en mode `fallback` car le spread des scores Qwen (Q75-Q10 = 0.050) est à la limite du seuil `min_score_spread=0.05`. Les constantes fallback (Sprint 4.3, calibrées pour un spread plus large) ne correspondent pas au profil très serré de Qwen sur ce document.

**Conséquence :** 38 informations potentiellement pertinentes sont rejetées vers le SINK au lieu d'être liées à des concepts métier.

### 5.2 Concepts vides : 42/59 (71%)

**Constat :** 42 concepts sur 59 n'ont aucune information rattachée. Ces concepts ont été identifiés par le LLM mais aucune assertion n'a été liée à eux lors du rerank.

**Causes possibles :**
- Les triggers C1 de ces concepts ne matchent pas le vocabulaire du document (les résumés Pass 0.9 utilisent un vocabulaire différent du texte original)
- Le rerank élimine trop de liens faibles vers le SINK
- Certains concepts sont trop génériques ("Gestion de la sécurité") ou trop abstraits pour avoir des triggers lexicaux discriminants

**Exemples frappants :**
- "Gestion des correctifs de sécurité" : 0 infos (alors que le document traite extensivement du Security Patch Management)
- "Certifications de sécurité" : 0 infos (alors que ISAE3402, SOC1/2, ISO 27001 sont dans le SINK)
- "Gestion des vulnérabilités" : 0 infos (alors que le document couvre EDR, antivirus, etc.)

### 5.3 Thèmes sans concepts (2/15)

- **"Certifications et attestations de sécurité"** : 0 concepts → Le thème existe mais aucun concept n'a été rattaché
- **"Contrôle des vulnérabilités et tests de pénétration"** : 0 concepts → Idem

### 5.4 Thèmes avec concepts mais 0 informations (3/15)

- **"Gestion des mises à jour et des correctifs"** : 8 concepts, **tous à 0 infos**
- **"Mises à jour et maintenance des systèmes"** : 4 concepts, **tous à 0 infos**
- **"Contrôles de sécurité et gestion des incidents"** : 6 concepts, **tous à 0 infos**

### 5.5 Concept aspirateur : "conformité réglementaire" (11 infos)

Ce concept absorbe des informations hétérogènes :
- Déploiement AZ (infrastructure) → devrait être "Haute disponibilité"
- Encryption AES256 des backups → devrait être "Encryption des données"
- Micro-segmentation → devrait être "Isolation réseau"
- FIPS 140-2 → devrait être "Certifications de sécurité"
- HANA Volume Encryption → devrait être "Encryption des données"
- TLS mandatory → devrait être "Encryption en transit"

**Pattern :** "conformité réglementaire" est un concept trop large qui attire tout ce qui mentionne des standards, normes, ou exigences.

### 5.6 Concept "Isolation réseau" : informations mal routées

6 informations rattachées mais au moins 3 sont hors-sujet :
- "Security Patch Management purpose" → devrait être "Gestion des correctifs"
- "Firewall rule base export" → devrait être "Gestion pare-feu"
- "Heuristic/ML malware detection" → devrait être "Endpoint protection"

### 5.7 Doublons

- "Virtual WAN" : 4 informations qui sont 4 variantes de "Azure setup, similar for AWS/GCP"
- "conformité réglementaire" : "TLS mandatory" apparaît 2 fois
- SINK : "SAP ECS manages Firewall" apparaît 2 fois (#13, #19)

### 5.8 Calibration Qwen — scores serrés

```
mode=fallback  reason=degenerate_spread
spread=0.050  Q10=0.600  Q50=0.645  Q75=0.650  n=99
```

Le spread de 0.050 est très faible — tous les scores sont entre 0.60 et 0.65. Cela signifie que Qwen ne discrimine pas bien entre les bonnes et mauvaises associations concept-assertion. Les bonus lexicaux/sémantiques sont les seuls facteurs de discrimination (19% des liens promus ont un signal).

### 5.9 Coverage cascade — pas de log de promotion

Aucun log `[OSMOSE:Pass1:1.1:Coverage]` n'a été émis, ce qui signifie que soit tous les headings Docling étaient couverts par les thèmes LLM, soit les sections passées étaient des sections artificielles (créées depuis chunks, donc sans vrais titres de sections).

**Note :** Les sections sont en fait créées via `_create_sections_from_chunks()` (log : "Sections créées depuis chunks: 206"). Ces sections artificielles n'ont probablement pas de champ `title` significatif, ce qui rend la cascade headings inefficace.

---

## 6. Métriques de qualité synthétiques

| Indicateur | Valeur | Cible | Statut |
|-----------|--------|-------|--------|
| SINK % | 43% | 15-30% | **KO** |
| Max concept métier | 12% (11 infos) | < 20% | OK |
| Concepts avec infos | 29% (17/59) | > 60% | **KO** |
| Thèmes avec concepts | 87% (13/15) | > 90% | LIMITE |
| Thèmes avec infos | 53% (8/15) | > 80% | **KO** |
| Doublons | ~5 | 0 | FAIBLE |
| Signal rerank | 19% | > 30% | **KO** |
| Calibration mode | fallback | auto | NON-OPTIMAL |

---

## 7. Pistes d'amélioration

### 7.1 Urgentes (impactent directement la qualité)

1. **C1 trigger validation trop stricte** : 42 concepts n'ont aucun trigger qui matche → assouplir la validation ou générer des triggers plus variés (synonymes, formes alternatives)

2. **Rerank scores serrés Qwen** : Le spread 0.050 empêche la calibration auto. Options :
   - Baisser `min_score_spread` de 0.05 à 0.03
   - Utiliser un temperature plus élevé pour Qwen (actuellement 0.3)
   - Ajouter un mode calibration "tight_spread" spécifique aux distributions serrées

3. **Sections artificielles** : Les sections créées depuis chunks (`_create_sections_from_chunks`) n'ont pas de vrais titres → la cascade coverage headings ne peut pas fonctionner. Il faut soit utiliser les vrais headings Docling, soit enrichir les sections artificielles.

### 7.2 Moyennes (améliorations structurelles)

4. **Concept aspirateur** : Détecter post-rerank les concepts avec > 8 infos hétérogènes et les splitter

5. **Informations mal routées** : Ajouter une validation sémantique post-link (l'info est-elle réellement en rapport avec le concept ?)

6. **Dédup informations** : Détecter et fusionner les doublons (TLS mandatory, SAP ECS Firewall, Azure setup)

### 7.3 Futures

7. **Pass 0 enrichi** : Utiliser Docling pour extraire la vraie structure du document (sections, headings) plutôt que des sections artificielles depuis les chunks

8. **Feedback loop** : Utiliser les informations SINK comme signal pour identifier les concepts manquants et relancer un cycle d'identification

---

## 8. Comparaison avec le run précédent (Sprint 4.3, 8K context)

| Métrique | Run précédent | Ce run | Tendance |
|----------|--------------|--------|----------|
| Thèmes | 8 | 15 | Meilleur (plus granulaire) |
| Concepts | ~40 | 59 | Plus de concepts |
| Informations | 131 | 89 | Moins (SINK plus agressif) |
| SINK % | 23% | 43% | Dégradé |
| Concepts avec infos | ~50% | 29% | Dégradé |
| Pass 0.9 | Troncature (pas de LLM) | LLM via vLLM | Amélioré |
| Pass 1.1 | Tronqué à 4K chars | 25K chars complet | Amélioré |
| Pass 0.9 temps | N/A | ~3 min (parallélisé) | Nouveau |

**Paradoxe :** Plus de thèmes et concepts → mais MOINS d'informations rattachées. Le pipeline identifie mieux la structure mais ne parvient pas à lier les assertions aux concepts identifiés. Le goulot d'étranglement est clairement le **C1 trigger matching + rerank scoring**.

---

*Généré automatiquement par Claude Code — 2026-01-29 22:45 UTC*
