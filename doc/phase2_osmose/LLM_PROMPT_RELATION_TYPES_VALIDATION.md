# Prompt LLM : Validation Types de Relations Sémantiques Phase 2

**Date:** 2025-10-19
**Objectif:** Challenger et valider les 8 types de relations proposés pour Phase 2 OSMOSE
**LLM Cible:** GPT-4o, Claude Sonnet 3.5, ou équivalent

---

## 🎯 Prompt Principal

```markdown
# Contexte

Je développe **OSMOSE**, un système d'intelligence sémantique **domain-agnostic** pour documents enterprise.

**Architecture actuelle (Phase 1.5 COMPLÉTÉE) :**
- Extraction concepts canoniques via LLM + NER multilingue
- Graphe de connaissances Neo4j (Published KG)
- Cross-référence avec Qdrant (chunks sources)
- Relations basiques : co-occurrences simples détectées

**Objectif Phase 2 :**
Enrichir le graphe avec **relations sémantiques typées** pour :
1. Dépasser limitations RAG simple (Microsoft Copilot, Google Gemini)
2. Permettre queries structurées complexes ("Quelles dépendances de X ?", "Évolution produit Y 2020-2025 ?")
3. Construire hiérarchies produit/concept auto-détectées
4. Tracker évolutions temporelles avec breaking changes

**IMPORTANT : Domain-Agnostic Design**
La solution doit fonctionner pour **TOUS secteurs** :
- ✅ Enterprise Software (SAP, Oracle, Salesforce, etc.)
- ✅ Pharma (médicaments, essais cliniques, régulations)
- ✅ Retail (produits, supply chain, stratégies marketing)
- ✅ Finance (produits financiers, régulations, compliance)
- ✅ Manufacturing (équipements, processus, normes qualité)
- ✅ Legal (cas juridiques, jurisprudence, législations)

**Cas d'usage prioritaires (exemples multi-domaines) :**
- UC1 : Product Dependencies
  - Software : "Toutes dépendances de [Product X] ?"
  - Pharma : "Composants actifs de [Drug Y] ?"
  - Retail : "Fournisseurs de [Product Z] ?"

- UC2 : Evolution Tracker
  - Software : "Breaking changes [Product] 2020-2025 ?"
  - Pharma : "Évolution formule [Drug] entre essais Phase I et III ?"
  - Legal : "Amendements [Loi] depuis 2018 ?"

- UC3 : Taxonomy Navigation
  - Software : "Tous modules de [Platform] ?"
  - Pharma : "Toutes indications thérapeutiques de [Drug Class] ?"
  - Retail : "Toutes catégories sous [Product Line] ?"

**Corpus documents (exemples) :**
- Présentations techniques (PPTX, 50-300 slides)
- Whitepapers produit (PDF, 20-100 pages)
- Documentation architecture/processus
- Release notes & changelogs
- Rapports réglementaires (pharma, finance)
- Manuels juridiques (legal, compliance)

---

# Proposition Initiale (8 Types Relations)

J'ai défini **8 types de relations** sémantiques à détecter (exemples multi-domaines) :

1. **PART_OF** : Composant → Ensemble parent
   - Software : "User Interface Module" PART_OF "ERP Platform"
   - Pharma : "Active Ingredient X" PART_OF "Drug Formulation Y"
   - Retail : "Payment Processing" PART_OF "E-commerce Platform"

2. **USES** : Technologie/Composant → Dépendance technique
   - Software : "Application Server" USES "Database Engine"
   - Manufacturing : "Assembly Line" USES "Robotic Arm Model Z"
   - Finance : "Trading Platform" USES "Risk Calculation Engine"

3. **REPLACES** : Évolution (obsolescence, succession)
   - Software : "Platform v2.0" REPLACES "Platform v1.5"
   - Pharma : "New Formulation" REPLACES "Legacy Formula"
   - Legal : "Regulation 2024" REPLACES "Regulation 2018"

4. **REQUIRES** : Prérequis fonctionnel/obligatoire
   - Software : "Cloud Service X" REQUIRES "Authentication Service Y"
   - Pharma : "Clinical Trial Phase III" REQUIRES "Phase II Completion"
   - Finance : "Investment Product" REQUIRES "Regulatory Approval"

5. **EXTENDS** : Extension/Add-on optionnel
   - Software : "Advanced Analytics Module" EXTENDS "Core Platform"
   - Retail : "Loyalty Program" EXTENDS "Payment System"
   - Manufacturing : "Quality Control Add-on" EXTENDS "Production Line"

6. **INTEGRATES_WITH** : Intégration système bidirectionnelle
   - Software : "CRM System" INTEGRATES_WITH "ERP System"
   - Pharma : "Lab Management System" INTEGRATES_WITH "Hospital IT"
   - Retail : "Inventory System" INTEGRATES_WITH "POS System"

7. **ENABLES** : Capacité fonctionnelle offerte
   - Software : "In-Memory Database" ENABLES "Real-time Analytics"
   - Pharma : "Biomarker Test" ENABLES "Personalized Treatment"
   - Finance : "Blockchain Technology" ENABLES "Decentralized Trading"

8. **COMPETES_WITH** : Alternative marché
   - Software : "ERP Platform A" COMPETES_WITH "ERP Platform B"
   - Pharma : "Drug X" COMPETES_WITH "Drug Y" (même indication)
   - Retail : "E-commerce Platform A" COMPETES_WITH "Platform B"

---

# Mission

**Analyse critique demandée :**

## 1. Évaluation Granularité

Pour chaque type proposé :
- Est-il **suffisamment distinct** des autres ? (risque confusion extraction)
- Est-il **trop granulaire** (sur-spécialisation inutile) ?
- Y a-t-il des **chevauchements sémantiques** problématiques ?

**Exemple de confusion potentielle :**
- "USES" vs "REQUIRES" : Quelle différence claire ?
- "EXTENDS" vs "INTEGRATES_WITH" : Frontière floue ?

## 2. Coverage Cas d'Usage

Vérifier si les 8 types **couvrent exhaustivement** mes use cases :
- UC1 : Product Dependencies → Quels types nécessaires ?
- UC2 : Evolution Tracker → Quels types nécessaires ?
- UC3 : Taxonomy Navigation → Quels types nécessaires ?

**Types manquants potentiels :**
- Relations temporelles (PRECEDES, SUCCEEDS) ?
- Relations organisationnelles (OWNED_BY, MAINTAINED_BY) ?
- Relations de performance (OPTIMIZES, DEGRADES) ?

## 3. Détectabilité Automatique

Pour chaque type, évaluer **faisabilité détection** :
- **Pattern-based** (regex, dependency parsing) : Facile/Difficile ?
- **LLM-assisted** : Nécessaire ? Ambiguïté fréquente ?
- **Faux positifs** attendus : Élevé/Faible ?

**Exemple :**
- "PART_OF" : Patterns clairs ("component of", "module of") → Facile
- "ENABLES" : Patterns flous, nécessite compréhension contextuelle → Difficile

## 4. Propositions Alternatives

**Option A : Réduction (Types "Core")**
- Identifier 4-5 types **essentiels** couvrant 80% use cases
- Justifier exclusions

**Option B : Extension (Types Additionnels)**
- Proposer 2-3 types **manquants critiques**
- Justifier ajouts

**Option C : Refonte (Taxonomie Alternative)**
- Proposer **structure différente** (ex: hiérarchie types, super-types)
- Exemple : DEPENDENCY (super-type) → USES, REQUIRES (sous-types)

---

# Format Réponse Attendu

Structure ta réponse selon ce template :

## 1. Analyse Granularité (par type)

| Type | Distinct ? | Trop Granulaire ? | Chevauchements | Recommandation |
|------|-----------|------------------|----------------|----------------|
| PART_OF | ✅/⚠️/❌ | ✅/⚠️/❌ | [Types similaires] | Garder/Modifier/Supprimer |
| ... | ... | ... | ... | ... |

## 2. Coverage Cas d'Usage

### UC1 : Product Dependencies
- Types nécessaires : [Liste]
- Types manquants : [Liste si applicable]

### UC2 : Evolution Tracker
- Types nécessaires : [Liste]
- Types manquants : [Liste si applicable]

### UC3 : Taxonomy Navigation
- Types nécessaires : [Liste]
- Types manquants : [Liste si applicable]

## 3. Détectabilité Automatique

| Type | Pattern-Based | LLM-Assisted | Faux Positifs | Difficulté |
|------|---------------|--------------|---------------|------------|
| PART_OF | Facile | Optionnel | Faible | ⭐⭐ |
| ... | ... | ... | ... | ... |

## 4. Recommandations Finales

### Option Recommandée : [A/B/C/Hybride]

**Justification :** [3-5 lignes]

### Types Finaux Proposés

1. **[NOM_TYPE]** : [Description courte]
   - Exemple : [...]
   - Patterns détection : [...]
   - Utilité UC : [UC1, UC2, UC3]

2. **[...]**

### Types Retirés (si applicable)

- **[NOM_TYPE]** : Raison suppression [...]

### Types Ajoutés (si applicable)

- **[NOM_TYPE]** : Raison ajout [...]

---

# Contraintes

- **Nombre types final :** Entre 5 et 12 (pas trop peu, pas trop)
- **Clarté définition :** Chaque type doit avoir frontière claire
- **Détectabilité :** Privilégier types détectables avec ≥70% precision
- **Coverage UC :** Les 3 use cases DOIVENT être couverts à 100%

---

# Contexte Additionnel (si besoin)

**Exemples de phrases typiques dans corpus (multi-domaines) :**

## Software / Technology

```
"The ERP platform is built on a distributed database engine."
→ Relation attendue : (ERP Platform) -[USES]-> (Database Engine)

"The user interface module serves as the front-end for the core application."
→ Relation attendue : (UI Module) -[PART_OF]-> (Core Application)

"Version 3.0 replaces the legacy 2.x architecture."
→ Relation attendue : (Version 3.0) -[REPLACES]-> (Version 2.x)

"Integration with the CRM system enables customer data synchronization."
→ Relation attendue : (ERP) -[INTEGRATES_WITH]-> (CRM System)

"The cloud platform requires an identity provider for authentication."
→ Relation attendue : (Cloud Platform) -[REQUIRES]-> (Identity Provider)

"The analytics module extends the core platform with advanced reporting."
→ Relation attendue : (Analytics Module) -[EXTENDS]-> (Core Platform)

"In-memory technology enables real-time data processing."
→ Relation attendue : (In-Memory Technology) -[ENABLES]-> (Real-time Processing)

"Platform A competes with Platform B in the enterprise software market."
→ Relation attendue : (Platform A) -[COMPETES_WITH]-> (Platform B)
```

## Pharma / Healthcare

```
"The drug formulation contains aspirin as the active ingredient."
→ Relation attendue : (Aspirin) -[PART_OF]-> (Drug Formulation)

"The treatment protocol uses monoclonal antibody therapy."
→ Relation attendue : (Treatment Protocol) -[USES]-> (Monoclonal Antibody)

"The new formulation replaces the legacy tablet form."
→ Relation attendue : (New Formulation) -[REPLACES]-> (Legacy Tablet)

"Phase III trial requires Phase II completion and FDA approval."
→ Relation attendue : (Phase III) -[REQUIRES]-> (Phase II Completion)

"The diagnostic test integrates with the hospital electronic health record system."
→ Relation attendue : (Diagnostic Test) -[INTEGRATES_WITH]-> (EHR System)

"Biomarker testing enables personalized medicine approaches."
→ Relation attendue : (Biomarker Testing) -[ENABLES]-> (Personalized Medicine)

"Drug X competes with Drug Y for the same therapeutic indication."
→ Relation attendue : (Drug X) -[COMPETES_WITH]-> (Drug Y)
```

## Retail / E-commerce

```
"The checkout system is part of the e-commerce platform."
→ Relation attendue : (Checkout System) -[PART_OF]-> (E-commerce Platform)

"The payment gateway uses tokenization technology for security."
→ Relation attendue : (Payment Gateway) -[USES]-> (Tokenization)

"The new POS system replaces the legacy cash register system."
→ Relation attendue : (New POS) -[REPLACES]-> (Legacy Cash Register)

"The loyalty program requires customer account creation."
→ Relation attendue : (Loyalty Program) -[REQUIRES]-> (Customer Account)

"The inventory system integrates with the supplier management platform."
→ Relation attendue : (Inventory System) -[INTEGRATES_WITH]-> (Supplier Platform)

"Mobile payment enables frictionless checkout experience."
→ Relation attendue : (Mobile Payment) -[ENABLES]-> (Frictionless Checkout)
```

## Manufacturing

```
"The robotic arm is a component of the assembly line system."
→ Relation attendue : (Robotic Arm) -[PART_OF]-> (Assembly Line)

"The quality control system uses computer vision for defect detection."
→ Relation attendue : (QC System) -[USES]-> (Computer Vision)

"The automated system replaces manual inspection processes."
→ Relation attendue : (Automated System) -[REPLACES]-> (Manual Inspection)

"The production line requires calibrated sensors for operation."
→ Relation attendue : (Production Line) -[REQUIRES]-> (Calibrated Sensors)

"Predictive maintenance enables reduced downtime."
→ Relation attendue : (Predictive Maintenance) -[ENABLES]-> (Reduced Downtime)
```

**Exemples évolution temporelle (UC2 - multi-domaines) :**

## Software Evolution

```
"Platform 2020 used XML-based configuration."
"Platform 2021 introduced JSON configuration, deprecating XML support."
"Platform 2023 removed XML parser, making JSON mandatory."

→ Relations attendues :
   (Platform_2020) -[PRECEDES]-> (Platform_2021) ?
   (Platform_2021) -[EVOLVES_TO]-> (Platform_2023) ?
   (XML_config) -[DEPRECATED_BY]-> (JSON_config) ?
```

## Pharma Evolution

```
"Drug formulation v1 (2018) used tablet delivery."
"Formulation v2 (2020) introduced sustained-release capsules."
"Formulation v3 (2023) replaced tablets entirely with injectable form."

→ Relations attendues :
   (Formulation_v1) -[PRECEDES]-> (Formulation_v2)
   (Formulation_v3) -[REPLACES]-> (Formulation_v1)
   (Injectable) -[REPLACES]-> (Tablet_delivery)
```

## Regulatory Evolution

```
"Regulation 2018 required annual compliance reporting."
"Regulation 2021 amended reporting frequency to quarterly."
"Regulation 2024 supersedes 2021 version with real-time reporting."

→ Relations attendues :
   (Regulation_2018) -[PRECEDES]-> (Regulation_2021)
   (Regulation_2024) -[REPLACES]-> (Regulation_2021)
   (Real-time_reporting) -[REPLACES]-> (Quarterly_reporting)
```

---

# Question Finale

**En tant qu'expert en knowledge graphs et semantic relations :**

**Quelle serait la taxonomie optimale de types de relations pour mon use case DOMAIN-AGNOSTIC ?**

Justifie tes choix avec :
1. **Analyse granularité** : Distinctions claires, pas de chevauchements
2. **Coverage use cases** : 100% des 3 UC couverts (Dependencies, Evolution, Taxonomy)
3. **Détectabilité pratique** : Patterns linguistiques génériques (pas domain-specific)
4. **Domain-agnostic validation** : Types applicables à Software, Pharma, Retail, Finance, Manufacturing, Legal
5. **Exemples concrets multi-domaines** : Au moins 3 domaines par type proposé

**Contraintes critiques :**
- ❌ Éviter termes domain-specific (ex: "API", "database", "clinical trial")
- ✅ Privilégier termes génériques (ex: "component", "system", "process")
- ✅ Types doivent fonctionner pour documents techniques, réglementaires, commerciaux
- ✅ Patterns détection doivent être langue-agnostic (EN, FR, DE, ES, etc.)

Sois critique et propose des améliorations substantielles si la proposition initiale est sous-optimale ou trop domain-specific.
```

---

## 📋 Instructions d'Utilisation

### 1. Copier le Prompt

Copier l'intégralité du bloc markdown ci-dessus (entre les ```markdown ... ```)

### 2. Utiliser avec LLM

**Recommandé :**
- **GPT-4o** (OpenAI) : Meilleure compréhension knowledge graphs
- **Claude Sonnet 3.5** (Anthropic) : Excellent pour analyse structurelle
- **Gemini 1.5 Pro** (Google) : Bonne alternative

**Via API :**
```python
import openai

response = openai.ChatCompletion.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "Tu es un expert en knowledge graphs et semantic relations pour systèmes enterprise."},
        {"role": "user", "content": PROMPT_CI_DESSUS}
    ],
    temperature=0.3,  # Équilibre créativité/précision
    max_tokens=4000
)

print(response.choices[0].message.content)
```

**Via Interface Web :**
- ChatGPT Plus (GPT-4o)
- Claude.ai (Sonnet 3.5)
- Google AI Studio (Gemini 1.5 Pro)

### 3. Analyser la Réponse

**Attentes :**
- Tableau analyse granularité (8 types)
- Coverage détaillée 3 use cases
- Évaluation détectabilité (difficulté extraction)
- Proposition finale (5-12 types avec justification)

**Red Flags à Surveiller :**
- ❌ Recommandation < 5 types (trop peu, coverage insuffisante)
- ❌ Recommandation > 12 types (trop granulaire, complexité excessive)
- ❌ Chevauchements sémantiques non résolus
- ❌ Use cases UC1/UC2/UC3 non couverts à 100%

### 4. Itérer si Nécessaire

Si réponse pas satisfaisante, **follow-up prompts :**

**Exemple 1 : Clarification chevauchements**
```
"Tu as identifié un chevauchement entre USES et REQUIRES.
Peux-tu proposer une distinction claire avec :
- Définition précise de chaque type
- 3 exemples SAP pour chacun
- Critères décision automatique (pour LLM classifier)"
```

**Exemple 2 : Validation détectabilité**
```
"Pour le type ENABLES que tu proposes, peux-tu :
1. Lister 5 patterns linguistiques détectables (regex/dependency parsing)
2. Estimer precision/recall attendus
3. Identifier cas ambigus nécessitant LLM
4. Proposer prompt LLM pour classification"
```

**Exemple 3 : Extension use case**
```
"J'ai un 4ème use case : 'Compliance Tracking'
(ex: 'Quels produits SAP sont GDPR-compliant ?')

Quels types de relations additionnels seraient nécessaires ?
Exemples : COMPLIES_WITH, CERTIFIED_FOR, REGULATED_BY ?"
```

---

## 🎯 Utilisation des Résultats

### Après Validation LLM

1. **Mettre à jour PHASE2_EXECUTIVE_SUMMARY.md**
   - Section "Types de relations à détecter"
   - Justification choix (basée sur analyse LLM)

2. **Mettre à jour PHASE2_TRACKING.md**
   - Jour 2 : Liste types finaux validés
   - Patterns détection (si fournis par LLM)

3. **Créer fichier référence**
   - `PHASE2_RELATION_TYPES_REFERENCE.md`
   - Définitions précises
   - Exemples SAP par type
   - Patterns détection
   - Cas ambigus

4. **Adapter implémentation**
   - `src/knowbase/relations/relation_types.py` (enum types)
   - Prompts LLM classifier
   - Règles pattern-based extractor

---

## 📊 Exemple Réponse Attendue (Extrait)

```markdown
## 1. Analyse Granularité

| Type | Distinct ? | Trop Granulaire ? | Chevauchements | Recommandation |
|------|-----------|------------------|----------------|----------------|
| PART_OF | ✅ | ✅ | Aucun | **Garder** (essentiel UC3) |
| USES | ⚠️ | ✅ | REQUIRES (70% overlap) | **Merger** avec REQUIRES → DEPENDS_ON |
| REPLACES | ✅ | ✅ | SUCCEEDS (temporel) | **Garder** + ajouter SUCCEEDS |
| REQUIRES | ⚠️ | ✅ | USES (70% overlap) | **Merger** → DEPENDS_ON |
| EXTENDS | ⚠️ | ⚠️ | INTEGRATES_WITH (50% overlap) | **Simplifier** → INTEGRATES_WITH |
| INTEGRATES_WITH | ✅ | ✅ | EXTENDS (mineur) | **Garder** (essentiel UC1) |
| ENABLES | ⚠️ | ❌ | Trop abstrait | **Supprimer** (difficilement détectable) |
| COMPETES_WITH | ✅ | ⚠️ | Aucun | **Optionnel** (nice-to-have, pas critique UC) |

## 4. Recommandations Finales

### Option Recommandée : **A (Réduction) + Extensions ciblées**

**Justification :**
- Réduire chevauchements USES/REQUIRES → DEPENDS_ON (plus clair)
- Supprimer ENABLES (trop abstrait, faible détectabilité)
- Ajouter relations temporelles (critiques UC2)
- Garder COMPETES_WITH optionnel (Phase 2.5)

### Types Finaux Proposés (7 types)

1. **PART_OF** : Composant → Système parent
   - Patterns : "component of", "module of", "part of"
   - UC : UC3 (taxonomy)

2. **DEPENDS_ON** : Dépendance technique/fonctionnelle (merge USES + REQUIRES)
   - Patterns : "depends on", "requires", "uses", "built on"
   - UC : UC1 (dependencies)

3. **REPLACES** : Obsolescence produit
   - Patterns : "replaces", "supersedes", "deprecates"
   - UC : UC2 (evolution)

4. **INTEGRATES_WITH** : Intégration système (absorbe EXTENDS)
   - Patterns : "integrates with", "connects to", "extends"
   - UC : UC1 (integrations)

5. **PRECEDES** : ⭐ NOUVEAU - Ordre temporel
   - Patterns : "before", "prior to", "version X precedes Y"
   - UC : UC2 (timeline)

6. **SUCCEEDS** : ⭐ NOUVEAU - Succession temporelle
   - Patterns : "after", "following", "version Y succeeds X"
   - UC : UC2 (timeline)

7. **HAS_VERSION** : ⭐ NOUVEAU - Relation version produit
   - Patterns : "version X of Y", "Y v1.5"
   - UC : UC2 (versioning)

### Types Retirés

- **USES** : Mergé avec REQUIRES → DEPENDS_ON
- **REQUIRES** : Mergé avec USES → DEPENDS_ON
- **EXTENDS** : Absorbé par INTEGRATES_WITH
- **ENABLES** : Supprimé (trop abstrait, faible détectabilité <60%)

### Types Ajoutés

- **PRECEDES/SUCCEEDS** : Essentiels UC2 (timeline structurée)
- **HAS_VERSION** : Critique UC2 (versioning produits)
```

---

## ✅ Checklist Validation

Après réception réponse LLM, vérifier :

- [ ] Nombre types final : 5-12 ✅
- [ ] UC1 (Dependencies) couvert à 100% ✅
- [ ] UC2 (Evolution) couvert à 100% ✅
- [ ] UC3 (Taxonomy) couvert à 100% ✅
- [ ] Chevauchements sémantiques résolus ✅
- [ ] Détectabilité ≥70% pour chaque type ✅
- [ ] Exemples SAP concrets fournis ✅
- [ ] Patterns détection listés ✅

Si tous ✅ → **Valider taxonomie finale** et mettre à jour docs Phase 2

---

**Prochaine Étape :** Exécuter ce prompt avec GPT-4o et analyser résultats.
