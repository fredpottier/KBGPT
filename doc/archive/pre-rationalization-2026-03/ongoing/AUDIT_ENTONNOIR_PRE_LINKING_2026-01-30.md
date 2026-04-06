# Audit Entonnoir Pré-Linking — Pipeline OSMOSE Stratified V2

**Date :** 2026-01-30
**Document :** RISE with SAP Cloud ERP Private — Security (230 pages, EN)
**Objectif :** Objectiver où et pourquoi on perd la matière entre DocItems et linking
**Demandeurs :** ChatGPT + Utilisateur (collaborative review)

---

## Vue Synthétique de l'Entonnoir

```
6743 DocItems (cache Docling)
  │
  │  ▼ FILTRE 1: UnitIndexer (min_unit_length=30 chars)
  │  Perte: 5046 DocItems (74.8%)
  │
1697 DocItems indexés → 2091 unités d'extraction
  │
  │  ▼ FILTRE 2: LLM Extraction (Pass 1.3 POINTER, Qwen 16K)
  │  Perte: 1689 unités non-extractibles
  │
 402 assertions brutes extraites
  │
  │  ▼ FILTRE 3: Promotion Policy (fragment + meta + tier)
  │  Perte: 213 assertions (53%)
  │    - 173 fragments filtrés (81% des rejets)
  │    -  33 meta-patterns filtrés (15%)
  │    -   7 PROCEDURAL tier (3%)
  │
 189 assertions promues → envoyées au linking
  │
  │  ▼ FILTRE 4: Linking + Reranking (Pass 1.4)
  │  Perte: 70 (54 no_concept + 16 cross_docitem)
  │
 119 informations finales (32 SINK + 87 métier)
```

**Ratio global :** 6743 DocItems → 119 informations = **1.8% de rendement**

---

## AUDIT 1 — Distribution DocItems (6743 → 1697)

### 1.1 Composition des 6743 DocItems

Les DocItems sont extraits par Docling (PDF parsing). La distribution par type n'est pas persistée en Neo4j (LAZY MODE), mais l'UnitIndexer logue les paths :

| Type DocItem | Indexés | Non indexés (estimé) | Total estimé |
|---|---|---|---|
| TEXT (paragraphes) | **1691** | ~5000+ | ~6700 |
| TABLE | **9** | ~30+ | ~40 |
| HEADING | 0 (utilisés comme sections) | ~400+ | ~400 |
| LIST_ITEM | inclus dans TEXT | — | — |
| FIGURE/CAPTION | 0 | — | — |

### 1.2 Critère de filtrage UnitIndexer

**Fichier :** `src/knowbase/stratified/pass1/assertion_unit_indexer.py:98-148`

```python
min_unit_length: int = 30  # ← SEUIL UNIQUE
```

**Le seul critère est la longueur :** `len(text.strip()) < 30 → SKIP`

Il n'y a PAS de filtrage par type (TEXT, HEADING, TABLE sont tous éligibles), PAS de filtrage par contenu sémantique, PAS de blacklist.

### 1.3 Pourquoi 5046 DocItems sont filtrés (74.8%)

Pour un document de 230 pages (deck de slides SAP), les DocItems courts sont :
- **Titres de slides** : "Security Overview" (17 chars) → SKIP
- **Bullets courts** : "WAF Logs" (8 chars) → SKIP
- **Légendes** : "Figure 3" (8 chars) → SKIP
- **Cellules de tableau vides ou courtes** : "Yes" (3 chars) → SKIP
- **En-têtes/pieds de page** : "© 2023 SAP SE" (13 chars) → SKIP
- **Whitespace/vide** : "" (0 chars) → SKIP

### 1.4 Verdict Audit 1

| Catégorie | Évaluation |
|-----------|-----------|
| Filtrage par longueur 30 chars | **Raisonnable** pour les fragments < 15 chars |
| Perte des titres de slides (17-29 chars) | **Acceptable** — les titres sont utilisés comme sections, pas comme assertions |
| Perte des bullets courts (15-29 chars) | **Discutable** — "WAF Logs", "SLA 99.9%" portent de l'information condensée |
| Ratio 74.8% filtré | **Normal** pour un deck de slides — beaucoup de décoration visuelle |

**Gain potentiel si seuil abaissé à 15 chars :** ~40 DocItems supplémentaires indexés → impact marginal sur le total d'informations (< +5%). **Pas le goulot.**

---

## AUDIT 2 — Policy Rejected (213 = 53%)

### 2.1 Décomposition par sous-raison (log)

```
[OSMOSE:Pass1:1.3] Promotion Policy:
  57 ALWAYS, 132 CONDITIONAL, 7 PROCEDURAL (exclues),
  33 meta filtrées, 173 fragments filtrés → 189 promues
```

| Sous-raison | Count | % des rejets | Mécanisme |
|---|---|---|---|
| **fragment** | **173** | **81%** | `_is_fragment()` → < 15 chars, < 3 mots, pas de verbe |
| **meta_description** | 33 | 15% | `_is_meta_description()` → 147 regex patterns YAML |
| **PROCEDURAL tier** | 7 | 3% | Tier NEVER → jamais promu |
| **Total** | **213** | **100%** | |

**LE GOULOT EST LE FILTRE FRAGMENT (173 = 81% des rejets)**

### 2.2 Distribution par type d'assertion (les 213 rejetées)

| Type | Count | Tier attendu | Rejets légitimes ? |
|---|---|---|---|
| FACTUAL | 102 | CONDITIONAL | ⚠️ Mix fragment+meta+low_conf |
| DEFINITIONAL | 48 | **ALWAYS** | ❌ Ne peut être rejeté QUE par fragment/meta |
| PRESCRIPTIVE | 28 | **ALWAYS** | ❌ Idem |
| CONDITIONAL | 15 | CONDITIONAL | ⚠️ Mix |
| PROCEDURAL | 12 | NEVER | ✅ Légitime |
| PERMISSIVE | 5 | CONDITIONAL | ⚠️ Mix |
| CAUSAL | 3 | **ALWAYS** | ❌ Idem |

**79 assertions ALWAYS-tier rejetées** (48 DEFINITIONAL + 28 PRESCRIPTIVE + 3 CAUSAL).
Ces assertions ont le tier le plus élevé (promues inconditionnellement SI elles passent fragment/meta).
→ Le filtre fragment capture des assertions qui devraient être promues.

### 2.3 Distribution par longueur des rejetées

| Tranche | Count | % | Évaluation |
|---|---|---|---|
| < 15 chars | 22 | 10% | ✅ Fragments légitimes ("WAF Logs", "DNS Logs") |
| 15-29 chars | 40 | 19% | ⚠️ **Discutable** — "Compliance as a Code" (20), "Recovery Time Objective" (23) |
| 30-49 chars | 51 | 24% | ❌ **Souvent excessif** — "WAF = Web Application Firewall" (30), "AAG = Azure Application gateway" (31) |
| 50-99 chars | 71 | 33% | ❌ **CLAIREMENT EXCESSIF** — assertions complètes rejetées |
| 100-149 chars | 24 | 11% | ❌ **PERTE DE VALEUR** — phrases complètes |
| 150+ chars | 5 | 2% | ❌ **PERTE INJUSTIFIABLE** — paragraphes entiers |

**151 assertions ≥ 30 chars rejetées (71%)** — la majorité ne sont PAS des fragments.

### 2.4 Exemples par catégorie de rejet

#### ✅ Rejets légitimes (bruit réel)

| Texte | Len | Type | Pourquoi légitime |
|-------|-----|------|-------------------|
| "with WAF" | 8 | FACTUAL | Fragment incomplet |
| "DNS Logs" | 8 | FACTUAL | Label seul |
| "Pacemaker" | 9 | DEFINITIONAL | Mot seul sans contexte |
| "SAP Managed" | 11 | FACTUAL | Fragment |
| "All rights reserved." | 20 | PRESCRIPTIVE | Copyright boilerplate |
| "SAP SE or an SAP affiliate company owns the copyright." | 54 | FACTUAL | Copyright (×2) |
| "© 2023 SAP SE or an SAP affiliate..." | 63 | FACTUAL | Copyright (×3) |
| "INTERNAL \| SAP AND EXTERNAL PARTIES UNDER NDA USE ONLY" | 54 | PRESCRIPTIVE | Classif. header (×3) |

**Estimé : ~40-50 rejets légitimes (bruit, boilerplate, doublons copyright)**

#### ⚠️ Rejets discutables mais récupérables

| Texte | Len | Type | Pourquoi discutable |
|-------|-----|------|---------------------|
| "ISO 27001" | 9 | DEFINITIONAL | Standard connu, mais sans assertion |
| "Recovery Time Objective" | 23 | DEFINITIONAL | Concept clé, mais pas d'assertion |
| "Compliance as a Code" | 20 | DEFINITIONAL | Pattern SAP, information condensée |
| "WAF = Web Application Firewall" | 30 | DEFINITIONAL | Définition valide ! |
| "CDM = Common Data Model" | 23 | DEFINITIONAL | Définition valide ! |
| "Defence in Depth Security" | 25 | DEFINITIONAL | Concept architectural clé |
| "Incremental Backups" | 19 | DEFINITIONAL | Capacité technique |

**Estimé : ~30-40 rejets discutables — information condensée mais pas d'assertion formelle**

#### ❌ Rejets clairement excessifs (PERTE DE VALEUR)

| # | Texte | Len | Type | Règle bloquante |
|---|-------|-----|------|-----------------|
| 1 | "Enforce MFA for Admin Users" | 27 | PRESCRIPTIVE | Fragment (< 30 chars, probablement no_verb) |
| 2 | "Restriction of superuser access." | 32 | PRESCRIPTIVE | Fragment (no_verb? "of" n'est pas un verbe d'assertion) |
| 3 | "Enforcement of strong password policies." | 40 | PRESCRIPTIVE | Fragment (no_verb) |
| 4 | "Locking of system and service user accounts." | 44 | PRESCRIPTIVE | Fragment (no_verb) |
| 5 | "SAP uses existing on-premise and cloud user stores" | 50 | FACTUAL | Fragment (no_verb? "uses" devrait compter!) |
| 6 | "Detailed Scope of Application Logs provided by LogServ" | 54 | FACTUAL | Fragment ou meta? |
| 7 | "SAP SaaS Applications use OAuth 2.0, and X.509 certificates" | 59 | FACTUAL | Fragment? |
| 8 | "SAP conducts periodic security testing to identify vulnerabilities" | 66 | FACTUAL | Fragment? |
| 9 | "Database Replication for High Availability and Disaster Recovery" | 64 | FACTUAL | Fragment (no_verb) |
| 10 | "Encryption root key and master key generated during installation" | 87 | FACTUAL | Fragment (no_verb? "generated" est un participe passé) |
| 11 | "Access to customer's systems is only possible with 2-factor" | 59 | PRESCRIPTIVE | Fragment? |
| 12 | "Periodic patching of all Internet Facing Web Applications" | 85 | PRESCRIPTIVE | Fragment (no_verb) |
| 13 | "SAP's contractual commitment via SAP Personal Data Processing Agreement" | 90 | FACTUAL | Fragment (no_verb?) |
| 14 | "Can the different Prod and Non-Prod environments be segregated by different VPCs?" | 100 | PERMISSIVE | Meta (question pattern "Can...?") |
| 15 | "Do we contractually allow customers to undertake penetration testing?" | 90 | CONDITIONAL | Meta (question pattern "Do we...?") |
| 16 | "Perform operations and management via SAP admin Network" | 55 | PRESCRIPTIVE | Fragment (no_verb? "Perform" est un impératif!) |
| 17 | "Each customer receives their own isolated landscape Virtual Network created" | 75 | FACTUAL | Fragment? ("receives" devrait compter) |
| 18 | "SAP publishes patches in customers' launchpad environment from their Portal" | 75 | FACTUAL | Fragment? |
| 19 | "Vulnerability directly related to missing offline security patches of OS" | 72 | CAUSAL | Fragment (no_verb? "related" est participial) |
| 20 | "Continuous 24x7 monitoring of security events, managing event triage..." | 153 | PROCEDURAL | NEVER tier (PROCEDURAL) |

**Estimé : ~100-120 rejets clairement excessifs**

### 2.5 Diagnostic Root Cause du filtre fragment

Le filtre `_is_fragment()` dans `promotion_engine.py` rejette si :
1. `len(text) < 15` → OK
2. `len(words) < 3` → OK
3. **PAS de verbe d'assertion détecté** → **TROP STRICT**

**Le problème fondamental :** La détection de verbe cherche des verbes conjugués (is, are, has, shall, must, provides, requires...) mais rate :
- **Impératifs** : "Enforce", "Perform", "Manage" → pas dans la liste
- **Participes passés** : "generated", "encrypted", "isolated" → pas détectés
- **Noms d'action** : "Enforcement", "Restriction", "Locking" → pas de verbe
- **Structures nominales SAP** : "Database Replication for HA and DR" → pas de verbe mais information structurelle riche

**De plus**, les questions ("Can we...?", "Do we...?") sont filtrées par meta_pattern mais certaines sont des vraies assertions conditionnelles dans un contexte Q&A (ce document contient des FAQ).

---

## AUDIT 3 — Perte de Valeur (top 20 assertions perdues)

### 3.1 Assertions perdues les plus dommageables

| # | Texte (tronqué) | Len | Type | Règle | Impact Métier |
|---|-----------------|-----|------|-------|--------------|
| 1 | "Enforce MFA for Admin Users" | 27 | PRESCRIPTIVE | fragment | **CRITIQUE** — exigence sécurité |
| 2 | "Restriction of superuser access." | 32 | PRESCRIPTIVE | fragment | **CRITIQUE** — contrôle d'accès |
| 3 | "Enforcement of strong password policies." | 40 | PRESCRIPTIVE | fragment | **HAUTE** — politique sécurité |
| 4 | "Locking of system and service user accounts." | 44 | PRESCRIPTIVE | fragment | **HAUTE** — hardening |
| 5 | "Database Replication for High Availability and DR" | 64 | FACTUAL | fragment | **HAUTE** — architecture HA |
| 6 | "Encryption root key and master key generated during install" | 87 | FACTUAL | fragment | **HAUTE** — crypto |
| 7 | "SAP conducts periodic security testing" | 66 | FACTUAL | fragment | **HAUTE** — audit sécurité |
| 8 | "Periodic patching of all Internet Facing Web Apps" | 85 | PRESCRIPTIVE | fragment | **HAUTE** — patch management |
| 9 | "SAP SaaS Applications use OAuth 2.0 and X.509" | 59 | FACTUAL | fragment | **HAUTE** — auth standards |
| 10 | "Each customer receives their own isolated landscape VNet" | 75 | FACTUAL | fragment | **HAUTE** — tenant isolation |
| 11 | "Perform operations and management via SAP admin Network" | 55 | PRESCRIPTIVE | fragment | **MOYENNE** — opérations |
| 12 | "Access to customer's systems only possible with 2-factor" | 59 | PRESCRIPTIVE | fragment | **CRITIQUE** — MFA requirement |
| 13 | "SAP publishes patches in customers' launchpad environment" | 75 | FACTUAL | fragment | **HAUTE** — patch distribution |
| 14 | "Vulnerability related to missing offline security patches" | 72 | CAUSAL | fragment | **HAUTE** — risk assessment |
| 15 | "IGA = Intra Group Data Protection Agreement" | 52 | DEFINITIONAL | fragment | **MOYENNE** — définition |
| 16 | "Customer initiates DR drill by creating service request 6w advance" | 84 | PROCEDURAL | NEVER tier | **HAUTE** — DR procedure |
| 17 | "Continuous 24x7 monitoring of security events, triage, incidents..." | 153 | PROCEDURAL | NEVER tier | **HAUTE** — SOC operations |
| 18 | "ECS performs comprehensive testing of patches based on SAP CERT..." | 215 | PROCEDURAL | NEVER tier | **CRITIQUE** — patch validation |
| 19 | "Failover of SCS/ERS and DB through manually initiated auto failover" | 87 | FACTUAL | fragment | **HAUTE** — HA mechanism |
| 20 | "For HANA DB, 99.7% standby optional for ≤6TiB, mandatory >6TiB" | 94 | FACTUAL | fragment | **HAUTE** — SLA architecture |

### 3.2 Bilan par règle bloquante

| Règle | Assertions perdues (estimé) | Légitimes | Excessives |
|-------|---------------------------|-----------|-----------|
| **Fragment (no_verb)** | ~130 | ~30 (labels, acronymes seuls) | **~100** |
| **Fragment (too_short < 15)** | ~22 | ~20 | ~2 |
| **Fragment (< 3 words)** | ~20 | ~15 | ~5 |
| **Meta-pattern** | ~33 | ~20 (copyright, classif.) | ~13 (questions FAQ) |
| **NEVER tier (PROCEDURAL)** | ~7 | ~2 (navigation) | **~5** (DR, patching) |
| **Total** | **~213** | **~87 (41%)** | **~126 (59%)** |

---

## CONCLUSIONS

### 1. Le goulot principal est le filtre fragment (173/213 = 81%)

La détection de verbe (`_is_fragment()` dans `promotion_engine.py`) est **trop restrictive** pour un document technique SAP :
- Rate les **impératifs** ("Enforce", "Perform", "Manage")
- Rate les **participes passés** ("generated", "encrypted", "isolated", "managed")
- Rate les **structures nominales** riches en information ("Database Replication for HA and DR")
- Rate les **noms d'action** ("Enforcement", "Restriction", "Locking")

### 2. La chute 6743 → 1697 DocItems est NORMALE

Pour un deck de slides avec beaucoup de décoration visuelle, 75% de perte au seuil 30 chars est attendu. Ce n'est PAS le goulot.

### 3. Le tier PROCEDURAL (NEVER) perd 5-7 assertions de valeur

Des procédures comme "Customer initiates DR drill 6 weeks in advance" ou "ECS performs comprehensive testing of patches" sont des informations opérationnelles critiques, pas du bruit.

### 4. Gain potentiel estimé

| Scénario | Assertions récupérées | Informations finales estimées | Gain |
|----------|----------------------|------------------------------|------|
| **Actuel** | 0 | 119 | — |
| **Fix verbe (impératifs + participes)** | +60-80 | ~160-180 | **+35-50%** |
| **Fix verbe + structures nominales** | +100-120 | ~190-210 | **+60-75%** |
| **Fix verbe + nominales + PROCEDURAL→CONDITIONAL** | +105-125 | ~195-215 | **+65-80%** |

### 5. Proposition : Policy à 3 niveaux

| Niveau | Critère | Action |
|--------|---------|--------|
| **KEEP_STRICT** | Verbe conjugué détecté, ≥ 30 chars, pas meta | Promu normalement (actuel) |
| **KEEP_WEAK** | Structure nominale ou impératif, ≥ 20 chars, pas meta | Promu avec flag `evidence_quality=weak` |
| **REJECT** | < 15 chars, OU meta-pattern, OU pur boilerplate | Rejeté (actuel) |

---

## RECOMMANDATIONS (à valider avec ChatGPT)

### Priorité 1 — Enrichir la détection de verbe

**Fichier :** `src/knowbase/stratified/pass1/promotion_engine.py` — `is_fragment()`

Ajouter :
- Impératifs anglais : enforce, perform, manage, restrict, lock, monitor, encrypt, configure, enable, disable, deploy, patch
- Participes passés : generated, encrypted, isolated, managed, configured, deployed, maintained, monitored, replicated
- Noms d'action : enforcement, restriction, locking, monitoring, encryption, replication, deployment, patching

### Priorité 2 — Accepter les structures nominales ≥ 30 chars avec 2+ mots techniques

Pattern : `len ≥ 30 AND word_count ≥ 4 AND contains_technical_term` → KEEP_WEAK

### Priorité 3 — Passer PROCEDURAL de NEVER à CONDITIONAL (conf ≥ 0.7)

5-7 procédures opérationnelles de haute valeur seraient récupérées.

### Priorité 4 — Traiter les questions FAQ comme CONDITIONAL

Certaines questions ("Can we...?", "Do we...?") dans un contexte FAQ sont des assertions conditionnelles. Ne pas les filtrer par meta-pattern si le document contient des sections Q&A.

---

## DONNÉES BRUTES

### Entonnoir complet

```
6743 DocItems
  → 1697 indexés (min_unit_length=30)
    → 2091 unités
      → 402 assertions brutes (LLM extraction)
        → 173 fragments filtrés
        →  33 meta filtrés
        →   7 PROCEDURAL tier (NEVER)
        = 213 REJECTED (53%)
        → 189 promues
          → 54 ABSTAINED no_concept_match
          → 16 ABSTAINED cross_docitem
          → 119 PROMOTED (32 SINK + 87 métier)
```

### Rejection par type d'assertion

```
FACTUAL       : 102 (CONDITIONAL tier)
DEFINITIONAL  :  48 (ALWAYS tier → fragment/meta seul)
PRESCRIPTIVE  :  28 (ALWAYS tier → fragment/meta seul)
CONDITIONAL   :  15 (CONDITIONAL tier)
PROCEDURAL    :  12 (NEVER tier)
PERMISSIVE    :   5 (CONDITIONAL tier)
CAUSAL         :   3 (ALWAYS tier → fragment/meta seul)
```

### Distribution longueur des rejetées

```
< 15 chars  :  22 (10%)  ← légitimes
15-29 chars :  40 (19%)  ← discutables
30-49 chars :  51 (24%)  ← souvent excessif
50-99 chars :  71 (33%)  ← CLAIREMENT excessif
100-149     :  24 (11%)  ← perte de valeur
150+ chars  :   5 (2%)   ← perte injustifiable
```
