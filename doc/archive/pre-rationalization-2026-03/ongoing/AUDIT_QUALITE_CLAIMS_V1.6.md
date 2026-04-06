# Audit Qualité des Claims — v1.6.0

**Date :** 2026-02-06
**Périmètre :** 8 849 claims + 2 079 entities — 3 documents S/4HANA
**Objectif :** Cartographier le bruit pour identifier les leviers d'amélioration de la qualité

---

## 1. Vue d'ensemble

| Doc | Claims | % total |
|-----|--------|---------|
| 025 (Feature Scope 2023) | 7 151 | 80.8% |
| 023 (Business Scope 2025) | 1 172 | 13.2% |
| 018 (Business Scope 1809) | 526 | 5.9% |
| **Total** | **8 849** | 100% |

### Distribution par type

| Type | Nb | % |
|------|-----|---|
| FACTUAL | 7 489 | 84.6% |
| DEFINITIONAL | 804 | 9.1% |
| PERMISSIVE | 303 | 3.4% |
| PRESCRIPTIVE | 184 | 2.1% |
| CONDITIONAL | 36 | 0.4% |
| PROCEDURAL | 33 | 0.4% |

### Distribution par longueur

| Bucket | Nb | % | Commentaire |
|--------|-----|---|-------------|
| < 30 chars | 58 | 0.7% | **Fragments inutilisables** |
| 30-49 chars | 865 | 9.8% | Beaucoup de bruit |
| 50-79 chars | 3 450 | 39.0% | Zone mixte |
| 80-119 chars | 3 229 | 36.5% | Zone utile |
| 120-199 chars | 1 181 | 13.3% | Zone riche |
| 200+ chars | 66 | 0.7% | Potentiellement trop long |

---

## 2. Catégories de bruit identifiées

### 2.1 — Fragments tronqués (< 30 chars) — 58 claims (0.7%)

Claims qui ne sont pas des phrases complètes, souvent des bouts de bullet points arrachés :

| Exemple | Longueur |
|---------|----------|
| `resolve issues` | 14 |
| `improve tracking` | 16 |
| `Create attachments` | 18 |
| `GSS reduces effort.` | 19 |
| `Define user validity` | 20 |
| `Capture detailed data` | 21 |
| `Post withholding tax.` | 21 |
| `reduce operational costs` | 24 |
| `Negotiate the best price` | 24 |
| `Reduced number of clicks` | 24 |

**Diagnostic :** L'extracteur LLM crée des claims à partir de bullets incomplets. Aucune valeur informationnelle exploitable.

**Action recommandée :** Filtre post-extraction `len(text) < 30 → REJECT`.

---

### 2.2 — Claims procédurales "You can..." / "Users can..." — 705 claims (8.0%)

| Pattern | Nb |
|---------|-----|
| `You can...` | 549 |
| `Users can...` / `User can...` | 156 |
| **Total** | **705** |

Exemples typiques :
- `"You can define synonyms."`
- `"You can collect evidence"`
- `"Users can create and edit locations."`
- `"You can evaluate search logs."`

**Diagnostic :** Ce sont des capacités UI/UX, pas de la connaissance. "You can define synonyms" ne dit rien sur l'architecture, les dépendances, ou les contraintes du produit.

**Action recommandée :** Filtre `starts_with("You can") → claim_type=PROCEDURAL` + flag `low_value=true`. Ne pas supprimer (utile pour le RAG) mais exclure du Composer.

---

### 2.3 — Claims d'existence passive — ~143 claims (1.6%)

Pattern : `"X is supported"`, `"X is available"`, `"X is provided"`

Exemples :
- `"Receiving purchase order confirmations is supported"`
- `"Sending purchase orders is supported"`
- `"Draft handling is supported"`
- `"PAL and ABC are supported"`
- `"Header variables are supported for authentication."`

**Diagnostic :** Pas de sujet clairement identifiable. "X is supported" sans dire *par quoi* ou *dans quel contexte* est une tautologie documentaire. Cependant, certaines sont utiles quand elles précisent le contexte (ex: `"SSO with X.509 client certificates is supported."` → information exploitable).

**Action recommandée :** Filtre conditionnel — rejeter si `text =~ "^.{5,30} is (supported|available)$"` (trop court), garder si le contexte est riche.

---

### 2.4 — Doublons exacts (intra-doc) — 192 claims excédentaires

| Texte dupliqué | Copies | Doc |
|----------------|--------|-----|
| `SAP Cloud ERP Private est basé sur SAP S/4HANA Cloud Private Edition 2025` | 6 | 023 |
| `Les fonctionnalités mentionnées dans ce chapitre peuvent ne pas être disponibles...` | 6 | 025 |
| `Ce document est fourni sans garantie de quelque nature que ce soit.` | 5 | 018 |
| `SAP peut modifier la présentation et sa stratégie à tout moment sans préavis.` | 5+3 | 018 |
| `SAP S/4HANA supports integration with external procurement systems` | 4 | 025 |
| Divers (169 textes distincts × 2-3 copies chacun) | ~169 | tous |

**Total :** 169 textes dupliqués → 361 claims impliquées → **192 claims excédentaires**.

**Diagnostic :** Le pipeline crée une claim par passage sans déduplication. Quand un même texte apparaît dans plusieurs sections (disclaimers, headers répétés), il génère N claims.

**Action recommandée :** Déduplication par `fingerprint` au moment de la persistance. Garder 1 claim + incrémenter `mention_count`.

---

### 2.5 — Boilerplate juridique — 21 claims (0.2%)

Claims extraites de disclaimers, copyrights, mentions légales :
- `"Ce document est fourni sans garantie de quelque nature que ce soit."`
- `"SAP peut modifier la présentation et sa stratégie à tout moment sans préavis."`
- `"Les fonctionnalités mentionnées dans ce chapitre peuvent ne pas être disponibles..."`

**Action recommandée :** Blacklist de patterns boilerplate dans l'extracteur.

---

### 2.6 — Claims terminant par préposition (tronquées) — ~40 claims (0.5%)

Claims coupées en milieu de phrase, se terminant par `data`, `for`, `to`, `with`, etc. :
- `"Capture detailed data"`
- `"Export and import principal data"`
- `"Support for mass maintenance of user data"`

**Diagnostic :** L'extracteur LLM coupe la claim au mauvais endroit. Le texte source contenait probablement une suite ("...data **from multiple sources**").

**Action recommandée :** Validation post-extraction : si la claim se termine par une préposition/article sans ponctuation, flag `truncated=true`.

---

## 3. Bruit côté Entities

### 3.1 — Entities à 2 caractères — 59 entities, ~200 relations ABOUT

| Catégorie | Exemples | Nb | Verdict |
|-----------|----------|-----|---------|
| Modules SAP légitimes | FI, CO, SD, MM, PP, PM, QM, PS, HR, CS, WM | 11 | ✅ Garder |
| Technos légitimes | ML, AI, UI, UX, QR, BW, BI, DB | 8 | ✅ Garder |
| Géographies | EU, UK, US | 3 | ✅ Garder |
| Ambigus SAP | IC, AS, CA, ED, TD, FX, SE, CW, PI, TM | 10 | ⚠️ À contextualiser |
| Bruit pur | HA, GI, ME, DN, PD, HT, FL, OP, TY, DG, MB, IA, LO, VC, RF, WS, EM, GM, GL, OM, ST, PO, BP | 23 | ❌ Bruit |
| **Non-SAP mais valides** | EWM, SSO, RFC, EDI, MRP, ATP, GTS, HCM, ESS, SOP, VAT | (3 chars) | ✅ Garder |

**Diagnostic :** 23 entities à 2 chars n'ont aucun sens isolé (HA=High Availability? Haiti? OP=Operation? Optional?). Elles polluent le graphe sans apporter de valeur.

**Action recommandée :** Whitelist de sigles SAP connus. Tout sigle ≤2 chars hors whitelist → ne pas créer de nœud Entity.

---

### 3.2 — Entities = fragments de phrases — 91+ entities (4.4%)

Entities dont le nom est une phrase complète ou un fragment >40 chars :

| Exemple | Type | Len |
|---------|------|-----|
| `Settlement management includes standalone processes that` | product | 56 |
| `Graphical representation of available assembly sequences` | concept | 56 |
| `Additional authorizations for any subsequent deliveries` | concept | 55 |
| `Standard analytics do not` | product | 24 |
| `Pre-defined aggregates` | concept | 22 |

**Total entités > 40 chars :** 91
**Entités contenant `that`/`which`/`where`/`when` :** 20

**Diagnostic :** L'extracteur d'entités capture des bouts de phrases au lieu de termes. `"Settlement management includes standalone processes that"` n'est pas une entité, c'est un début de phrase.

**Action recommandée :**
1. Filtre `len(entity_name) > 40 → REJECT` (sauf produits SAP connus avec noms longs)
2. Filtre `contains("that"|"which"|"where"|"includes"|"involves") → REJECT`
3. Filtre `ends_with("that"|"which"|"where") → REJECT`

---

## 4. Synthèse quantitative du bruit

| Catégorie de bruit | Claims affectées | % du total | Impact |
|--------------------|-----------------|------------|--------|
| **Fragments < 30 chars** | 58 | 0.7% | Inutilisables |
| **"You can" / "Users can"** | 705 | 8.0% | Faible valeur compositionnelle |
| **Existence passive ("is supported")** | ~143 | 1.6% | Tautologies |
| **Doublons exacts** | 192 excédentaires | 2.2% | Redondance pure |
| **Boilerplate juridique** | 21 | 0.2% | Zéro valeur |
| **Tronquées (fin préposition)** | ~40 | 0.5% | Incompréhensibles |
| **TOTAL BRUIT IDENTIFIÉ** | **~1 159** | **~13.1%** | |

| Catégorie de bruit Entity | Entities affectées | % de 2 079 |
|---------------------------|-------------------|------------|
| **2 chars bruit** | 23 | 1.1% |
| **Phrases > 40 chars** | 91 | 4.4% |
| **Fragments avec that/which** | 20 | 1.0% |
| **TOTAL BRUIT ENTITIES** | **~130** | **~6.3%** |

---

## 5. Impact sur la composabilité

### Avant nettoyage
- 8 849 claims totales
- ~23% composables (catégorie A) = ~2 035
- ~33% faiblement composables (catégorie B) = ~2 920
- ~43% non composables (catégorie C) = ~3 805

### Après nettoyage estimé
- 8 849 - 1 159 bruit = **~7 690 claims utiles**
- Les claims nettoyées ne sont PAS des claims composables (elles étaient en catégorie C)
- Donc le ratio composable augmente : ~2 035 / 7 690 = **~26.5%** (vs 23% avant)
- Gain marginal

### Vrai levier pour augmenter la catégorie A
Le nettoyage du bruit ne suffit pas. Pour passer de 23% à 40%+, il faudrait :

1. **Reformuler les claims de catégorie B** pour rendre l'objet spécifique
   - `"Enterprise Search provides secure real-time access to enterprise data"`
   - → Enrichir via le passage source : l'objet réel est peut-être "SAP HANA search indexes" et non "enterprise data"

2. **Fusionner les claims complémentaires** d'un même passage
   - Claim 1 : "S/4HANA supports SSO"
   - Claim 2 : "SSO uses X.509 certificates"
   - → Claim composée : "S/4HANA supports SSO via X.509 certificates"

3. **Améliorer le prompt d'extraction** pour favoriser les claims relationnelles
   - Actuellement le prompt demande "des claims factuelles"
   - Il faudrait guider vers "des claims décrivant des dépendances, intégrations, prérequis"

---

## 6. Recommandations prioritaires

### Priorité 1 — Filtres post-extraction (immédiat, sans réimport)

Ces filtres peuvent être appliqués sur les claims existantes :

| Filtre | Claims supprimées | Effort |
|--------|------------------|--------|
| `len < 30` → REJECT | 58 | Trivial |
| Déduplication par fingerprint | 192 | Trivial |
| Boilerplate blacklist | 21 | Trivial |
| `starts_with("You can"/"Users can")` → flag `low_value` | 705 | Trivial |
| **Total immédiat** | **~976** | **1h** |

### Priorité 2 — Filtres dans l'extracteur (prochain import)

| Filtre | Impact estimé |
|--------|---------------|
| Entity name > 40 chars → REJECT | -91 entities |
| Entity 2 chars hors whitelist → REJECT | -23 entities |
| Entity contient that/which → REJECT | -20 entities |
| Claim tronquée (fin préposition) → REJECT | -40 claims |
| Claim passive < 40 chars → flag low_value | -50 claims |

### Priorité 3 — Amélioration du prompt (réimport nécessaire)

Guider le LLM vers des claims plus relationnelles :
- Favoriser les claims de type "X uses/requires/depends_on Y"
- Décourager les claims de type "X is supported" sans contexte
- Limiter les claims procédurales "You can..."
- Exiger un subject et un object identifiables dans chaque claim

---

## 7. Fichiers de référence

| Fichier | Contenu |
|---------|---------|
| `src/knowbase/claimfirst/extractors/claim_extractor.py` | Prompt d'extraction des claims |
| `src/knowbase/claimfirst/extractors/entity_extractor.py` | Prompt d'extraction des entities |
| `src/knowbase/claimfirst/models/claim.py` | Modèle Claim (min_length=10, max=500) |
| `src/knowbase/claimfirst/models/entity.py` | Modèle Entity + stoplist + validation |
| `doc/ongoing/ANALYSE_POC_COMPOSER_CROSS_DOC.md` | Analyse complète du pivot Composer |
