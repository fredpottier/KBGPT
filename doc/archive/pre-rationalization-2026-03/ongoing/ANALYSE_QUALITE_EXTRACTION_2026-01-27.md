# Analyse Qualité Extraction - Pipeline Stratifié V2
**Date:** 2026-01-27
**Document testé:** RISE with SAP Cloud ERP Private (020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357)

---

## 1. Problème Initial : La Reformulation LLM

### 1.1 Description du Problème

Le pipeline d'extraction original souffrait d'un problème fondamental : le LLM (Qwen 14B) avait tendance à **reformuler** le texte source au lieu de le copier verbatim.

**Exemple concret :**
```
Texte source : "TLS 1.2 is required for all connections."
LLM retourne : { "exact_quote": "TLS version 1.2 is mandatory" }  ← REFORMULÉ
Résultat     : ÉCHEC de l'ancrage (le texte n'existe pas dans le document)
```

### 1.2 Conséquences

Cette reformulation causait :
1. **Impossibilité d'ancrer** les assertions (le texte reformulé n'existe pas dans le corpus)
2. **Perte de traçabilité** (on ne peut pas pointer vers la source exacte)
3. **Taux de rejet massif** : 83% des concepts extraits étaient rejetés

### 1.3 Distribution des Rejets (Avant Correction)

| Raison | Pourcentage | Description |
|--------|-------------|-------------|
| `value_mismatch` | **55%** | Le LLM assignait un `value_kind` (version, percentage, size) mais le pattern n'existait pas dans le texte |
| `no_lexical_support` | **45%** | Les labels proposés ne matchaient pas le texte de l'unité (labels abstraits comme "security requirement") |

---

## 2. Solution Implémentée : Mode Pointer-Based

### 2.1 Principe

Au lieu de demander au LLM de **copier** le texte, on lui demande de **pointer** vers des unités numérotées :

```
AVANT (échec):
  Input  → "TLS 1.2 is required for all connections."
  LLM    → { "exact_quote": "TLS version 1.2 is mandatory" }
  Match  → ÉCHEC (reformulé)

APRÈS (robuste):
  Input  → "U1: TLS 1.2 is required for all connections."
  LLM    → { "label": "TLS requirement", "unit_id": "U1" }
  Code   → exact_quote = units["U1"].text  // GARANTI VERBATIM
```

### 2.2 Modifications Clés

1. **Suppression de `value_kind`** du prompt LLM (détection côté code uniquement)
2. **Instruction explicite** : "Le LABEL doit contenir au moins 2 MOTS présents dans l'unité"
3. **Validation 3 niveaux** : Lexical + Type markers + Value patterns
4. **Reconstruction verbatim garantie** : exact_quote = unit.text (pas de copie LLM)

---

## 3. Métriques du Test du 2026-01-27

### 3.1 Performance Temporelle

| Métrique | Avant | Après | Amélioration |
|----------|-------|-------|--------------|
| **Temps total** | ~80 min | **33 min** | **-59%** |
| **Throughput vLLM** | ~60 req/min | ~80 req/min | +33% |
| **Prefix cache hit** | N/A | 53% | Nouveau |

### 3.2 Qualité d'Extraction

| Métrique | Avant | Après | Amélioration |
|----------|-------|-------|--------------|
| **ABSTAIN rate** | **83%** | **8%** | **-75 pts** |
| **Ancrages verbatim** | ~17% | **100%** | +83 pts |
| **value_mismatch** | 55% | **0%** | Éliminé |
| **Concepts valides** | ~17% | **92%** | +75 pts |

### 3.3 Distribution ABSTAIN Après Correction

| Raison | Count | Pourcentage |
|--------|-------|-------------|
| `no_lexical` | 157 | 100% |
| `value_mismatch` | 0 | 0% |
| `invalid_unit` | 0 | 0% |
| `empty_unit` | 0 | 0% |

**Analyse :** Les 157 ABSTAIN restants (8%) sont des cas où le LLM utilise encore des labels abstraits. C'est acceptable et représente une amélioration massive par rapport aux 83% précédents.

---

## 4. Organisation des Nodes Extraits

### 4.1 Vue d'Ensemble du Graphe

```
Document Source
├── 6743 DocItems (éléments Docling)
├── 1030 Chunks (segments textuels)
├── 206 Sections (structure TOC)
└── 2091 Unités d'assertion (mode Pointer)

Graphe de Connaissances Extrait
├── 1 Subject
├── 10 Themes
├── 14 Concepts
├── 61 Informations (liées aux concepts)
├── 209 InformationMVP (assertions validées)
├── 3 ClaimKeys
├── 340 AssertionLogs
└── 140 Relations (131 Pass1 + 9 Pass2)
```

### 4.2 Subject (Sujet Principal)

| Champ | Valeur |
|-------|--------|
| **ID** | `subj_020_RISE_with_SAP_Cloud_ERP_Private_full_363f5357` |
| **Nom** | SAP Cloud ERP Private |
| **Langue** | en |

### 4.3 Themes (10)

| # | Theme |
|---|-------|
| 1 | Architecture de référence |
| 2 | Déploiement des solutions cloud |
| 3 | Gestion des licences |
| 4 | Gestion des mises à jour |
| 5 | Infrastructure de données |
| 6 | Modèle de tenancy |
| 7 | Opérations techniques |
| 8 | Protection des points de terminaison |
| 9 | Responsabilité partagée en matière de sécurité |
| 10 | Surveillance et alertes |

### 4.4 Concepts (14)

| Concept | Rôle | Informations Liées |
|---------|------|-------------------|
| **security** | CENTRAL | 21 |
| **deployment** | CENTRAL | 2 |
| **tenancy** | CENTRAL | 0 |
| cloud | STANDARD | 13 |
| network | STANDARD | 9 |
| infrastructure | STANDARD | 5 |
| operations | STANDARD | 3 |
| endpoints | STANDARD | 3 |
| hyperscaler | STANDARD | 2 |
| monitoring | STANDARD | 2 |
| datacenter | STANDARD | 1 |
| architecture | STANDARD | 0 |
| licensing | STANDARD | 0 |
| updates | STANDARD | 0 |

**Observation :** 4 concepts n'ont aucune information liée (tenancy, architecture, licensing, updates). Cela suggère un problème de linking sémantique.

### 4.5 Informations (61)

**Distribution par type :**

| Type | Count | % |
|------|-------|---|
| FACTUAL | 40 | 66% |
| PRESCRIPTIVE | 10 | 16% |
| DEFINITIONAL | 5 | 8% |
| CONDITIONAL | 4 | 7% |
| PERMISSIVE | 1 | 2% |
| CAUSAL | 1 | 2% |

**Exemples d'informations extraites (concept: security) :**

| Type | Texte |
|------|-------|
| PRESCRIPTIVE | "All HTTP connections must be secured using Transport Layer Security (TLS) version 1.2 or higher." |
| DEFINITIONAL | "RAVEN is an ECS service that simplifies the management of SAP Application Security and Threats..." |
| FACTUAL | "Customer controls creation, use, deletion, rotation of the Master Keys" |
| CONDITIONAL | "If an event—such as a malware infection—is triggered by the endpoint protection software..." |

### 4.6 InformationMVP (209)

Ces sont les assertions validées par le mode Pointer-Based avec ancrage verbatim garanti.

**Distribution par type et statut :**

| Type | Statut | Count |
|------|--------|-------|
| DEFINITIONAL | PROMOTED_LINKED | 137 |
| PRESCRIPTIVE | PROMOTED_LINKED | 64 |
| PRESCRIPTIVE | PROMOTED_UNLINKED | 6 |
| CAUSAL | PROMOTED_LINKED | 2 |

**Exemples avec exact_quote verbatim :**

```
Type: DEFINITIONAL
Quote: "Subscriptions/Account/Projects are isolated containers for resources,
       billing, and quotas."

Type: DEFINITIONAL
Quote: "SAP Manages technical stack and customer has no access to
       Infrastructure OS."

Type: PRESCRIPTIVE
Quote: "All sessions are monitored and recorded to SAP SIEM"

Type: PRESCRIPTIVE
Quote: "Publishing such applications to Internet would require mandatory
       data-in-transit encryption using TLS 1.2 or above using customer
       provided certificates."
```

### 4.7 ClaimKeys (3)

| ClaimKey ID | Key | Description |
|-------------|-----|-------------|
| ck_general_responsibility | general_responsibility | Responsabilité partagée |
| ck_tls_min_version | tls_min_version | Version TLS minimum |
| ck_encryption_in_transit | encryption_in_transit | Chiffrement en transit |

### 4.8 Relations entre Concepts (9)

| Source | → | Cible |
|--------|---|-------|
| security | → | operations |
| security | → | infrastructure |
| security | → | deployment |
| deployment | → | hyperscaler |
| deployment | → | datacenter |
| cloud | → | hyperscaler |
| cloud | → | datacenter |
| network | → | hyperscaler |
| hyperscaler | → | cloud |

### 4.9 AssertionLogs (340)

**Distribution par statut :**

| Statut | Count | % |
|--------|-------|---|
| ABSTAINED | 148 | 44% |
| REJECTED | 131 | 39% |
| PROMOTED | 61 | 18% |

**Raisons des ABSTAINED :**
- `no_concept_match` : 141 (assertions sans concept correspondant)
- `cross_docitem` : 7 (référence à un autre DocItem)

**Raisons des REJECTED :**
- `policy_rejected` : 131 (filtré par la politique de promotion)

---

## 5. Analyse de la Captation Documentaire

### 5.1 Taux de Captation

| Métrique | Valeur Source | Valeur Extraite | Taux |
|----------|---------------|-----------------|------|
| DocItems | 6743 | - | - |
| Chunks | 1030 | - | - |
| Sections | 206 | 10 themes | 4.9% |
| Unités d'assertion | 2091 | 209 InformationMVP | **10.0%** |
| Concepts proposés LLM | 1970 | 1813 validés | 92% |
| Assertions | 340 | 61 promues | **18%** |

### 5.2 Diagnostic de la Faible Captation

**Constat :** Seulement ~10% des unités d'assertion et ~18% des assertions sont captées.

**Causes identifiées :**

1. **Filtrage par la Promotion Policy** (131 rejetés)
   - PROCEDURAL exclus (10)
   - Fragments filtrés (98)
   - Meta filtrées (23)

2. **Pas de concept correspondant** (141 abstained)
   - Les 14 concepts identifiés ne couvrent pas toutes les assertions
   - Concepts trop génériques (security, cloud, network)

3. **Échec du linking sémantique** (4 concepts sans information)
   - tenancy, architecture, licensing, updates n'ont aucune info liée
   - Pourtant le document parle extensivement de ces sujets

4. **Pass 1.2 trop restrictif** (seulement 14 concepts)
   - Le prompt demande "max 10 concepts" avec frugalité
   - Pour un document de 206 sections, c'est insuffisant

### 5.3 Couverture Thématique Manquante

En analysant les themes extraits vs le contenu probable du document RISE :

| Thème Attendu | Présent ? | Couverture |
|---------------|-----------|------------|
| Modèle de tenancy | ✅ | Faible (0 info) |
| Sécurité | ✅ | Bonne (21 info) |
| Architecture cloud | ✅ | Faible (0 info) |
| Networking | ✅ | Moyenne (9 info) |
| Gestion des updates | ✅ | Faible (0 info) |
| Licensing | ✅ | Faible (0 info) |
| High Availability | ❌ | Non identifié |
| Disaster Recovery | ❌ | Non identifié |
| Compliance (SOC2, ISO) | ⚠️ | Partiel |
| Migration | ❌ | Non identifié |
| Integration | ❌ | Non identifié |
| Performance | ❌ | Non identifié |

---

## 6. Recommandations d'Amélioration

### 6.1 Court Terme (Pass 1.2 - Identification Concepts)

1. **Augmenter le nombre de concepts** : passer de 10 à 25-30 concepts par document
2. **Concepts plus spécifiques** : "TLS encryption" au lieu de "security"
3. **Détecter les acronymes** et les définir comme concepts (SOC2, CGS, VPN, etc.)

### 6.2 Moyen Terme (Linking Sémantique)

1. **Améliorer le prompt de linking** pour réduire les "no_concept_match"
2. **Linking multi-concept** : une assertion peut informer plusieurs concepts
3. **Re-run du linking** si trop d'assertions non-liées

### 6.3 Long Terme (Architecture)

1. **Pass 1.2 itératif** : identifier plus de concepts sur les assertions non-liées
2. **Hiérarchie de concepts** : security → TLS → TLS_version
3. **Détection automatique de domaines** : High Availability, Disaster Recovery, etc.

---

## 7. Conclusion

### 7.1 Succès

✅ **Problème de reformulation résolu** : 100% d'ancrages verbatim
✅ **Taux ABSTAIN réduit** : de 83% à 8%
✅ **Performance améliorée** : temps divisé par 2.4
✅ **Qualité des données** : exact_quote = text (pas de dérive)

### 7.2 Axes d'Amélioration

⚠️ **Captation documentaire faible** : ~10% des unités, ~18% des assertions
⚠️ **Concepts insuffisants** : 14 concepts pour 206 sections
⚠️ **Linking incomplet** : 4 concepts sans information
⚠️ **Couverture thématique partielle** : domaines importants non identifiés

### 7.3 Prochaines Étapes

1. Analyser en détail les 131 `policy_rejected` pour ajuster la politique
2. Augmenter la limite de concepts en Pass 1.2
3. Améliorer le linking sémantique pour couvrir plus d'assertions
4. Ajouter une détection automatique des domaines techniques SAP

---

*Document généré automatiquement - OSMOSE Pipeline V2*
