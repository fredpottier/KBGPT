# 📚 PHASE2 - Référence Types de Relations

**Document:** Spécification normalisée des types de relations OSMOSE Phase 2
**Version:** 1.0
**Date:** 2025-10-19
**Status:** ✅ VALIDATED (consensus Claude + OpenAI)

---

## 🎯 Vue d'Ensemble

### Taxonomie Complète (12 Types)

```
┌─────────────────────────────────────────────────────────┐
│                  12 TYPES DE RELATIONS                   │
│              Organisés en 6 Familles Sémantiques          │
└─────────────────────────────────────────────────────────┘

📐 STRUCTURELLES (Hiérarchies & Taxonomies)
   ├── PART_OF          : Composant → Système parent
   └── SUBTYPE_OF       : Sous-catégorie → Catégorie générique

🔗 DÉPENDANCES (Fonctionnelles & Techniques)
   ├── REQUIRES         : Prérequis obligatoire
   └── USES             : Utilisation optionnelle/flexible

🔌 INTÉGRATIONS (Connexions Systèmes)
   ├── INTEGRATES_WITH  : Intégration bidirectionnelle
   └── EXTENDS          : Extension/Add-on (Phase 2.5 OPTIONNEL)

⚡ CAPACITÉS (Fonctionnalités Activées)
   └── ENABLES          : Débloque capacité (Phase 2.5 OPTIONNEL)

⏱️ TEMPORELLES (Évolution & Cycles de Vie)
   ├── VERSION_OF       : Relation versionnage (v1.0 → v2.0)
   ├── PRECEDES         : Succession chronologique
   ├── REPLACES         : Remplacement obsolescence
   └── DEPRECATES       : Dépréciation sans remplacement

🔄 VARIANTES (Alternatives & Compétition)
   └── ALTERNATIVE_TO   : Alternative fonctionnelle (Phase 2.5 OPTIONNEL)
```

### Stratégie d'Implémentation Phasée

| Phase | Types Implémentés | Difficulté | Timeline |
|-------|-------------------|------------|----------|
| **Phase 2 Initial** | 9 core types | ⭐⭐ à ⭐⭐⭐ | Semaines 14-21 |
| **Phase 2.5 Optionnel** | 3 types expérimentaux | ⭐⭐⭐⭐ | Semaines 22-24 |

**Critères GO Phase 2.5:**
- ✅ Coverage 9 types core ≥ 80% concepts
- ✅ Precision ≥ 80%, Recall ≥ 65%
- ✅ Conflict rate < 8%
- ✅ Validation tests E2E passés

---

## 📐 FAMILLE 1 : STRUCTURELLES

### Type 1.1 : PART_OF

**Définition Canonique (FR):**
Relation de composition où un élément est un composant physique ou logique d'un ensemble parent plus large.

**Canonical Definition (EN):**
Compositional relationship where an element is a physical or logical component of a larger parent system.

---

**Caractéristiques:**
- ✅ Relation **hiérarchique** (transitive)
- ✅ Bidirectionnelle implicite (A PART_OF B → B CONTAINS A)
- ✅ Utilisée pour construire taxonomies produit
- ⚠️ Ne pas confondre avec SUBTYPE_OF (catégorisation conceptuelle)

---

**Patterns de Détection:**

```python
# Patterns regex (multilingue)
EN_PATTERNS = [
    r"(\w+)\s+(?:is a |is an )?(?:component|module|part|element)\s+of\s+(\w+)",
    r"(\w+)\s+(?:includes|contains|comprises)\s+(\w+)",
    r"(\w+)\s+consists of\s+(\w+)",
]

FR_PATTERNS = [
    r"(\w+)\s+(?:est un |est une )?(?:composant|module|partie|élément)\s+de\s+(\w+)",
    r"(\w+)\s+(?:inclut|contient|comprend)\s+(\w+)",
    r"(\w+)\s+se compose de\s+(\w+)",
]

DE_PATTERNS = [
    r"(\w+)\s+(?:ist ein |ist eine )?(?:Komponente|Modul|Teil)\s+von\s+(\w+)",
    r"(\w+)\s+(?:enthält|umfasst|besteht aus)\s+(\w+)",
]

ES_PATTERNS = [
    r"(\w+)\s+(?:es un |es una )?(?:componente|módulo|parte)\s+de\s+(\w+)",
    r"(\w+)\s+(?:incluye|contiene|comprende)\s+(\w+)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Source (A) | Relation | Target (B) | Contexte |
|---------|-----------|----------|-----------|----------|
| **Software** | "Payment Module" | PART_OF | "E-commerce Platform" | Architecture système |
| **Pharma** | "Active Ingredient API-123" | PART_OF | "Drug Formulation XYZ-500" | Composition médicament |
| **Retail** | "Inventory Management System" | PART_OF | "Supply Chain Suite" | Système logistique |
| **Manufacturing** | "Robotic Arm Unit-5" | PART_OF | "Assembly Line Station-12" | Ligne production |
| **Finance** | "Risk Calculation Engine" | PART_OF | "Trading Platform" | Infrastructure trading |
| **Legal** | "Clause 4.2" | PART_OF | "Contract Template Master-v3" | Document juridique |

---

**Difficulté Détection:** ⭐⭐ (MOYENNE)

**Méthode Extraction:**
1. **Pattern-based (70%):** Regex + dependency parsing spaCy
2. **LLM-assisted (30%):** GPT-4o-mini pour cas ambigus

**Validation:**
- Transitivité vérifiée (A PART_OF B, B PART_OF C → A PART_OF C)
- Détection cycles interdite (A PART_OF B PART_OF A → ERREUR)

---

### Type 1.2 : SUBTYPE_OF

**Définition Canonique (FR):**
Relation de spécialisation où un concept est une sous-catégorie ou instance d'une catégorie générique plus abstraite.

**Canonical Definition (EN):**
Specialization relationship where a concept is a subcategory or instance of a more abstract generic category.

---

**Caractéristiques:**
- ✅ Relation **taxonomique** (IS-A relationship)
- ✅ Transitive (A SUBTYPE_OF B, B SUBTYPE_OF C → A SUBTYPE_OF C)
- ✅ Hérite propriétés du parent (enrichissement sémantique)
- ⚠️ Différence critique vs PART_OF : catégorisation conceptuelle, pas composition physique

---

**Patterns de Détection:**

```python
EN_PATTERNS = [
    r"(\w+)\s+is a (?:type|kind|variant|version)\s+of\s+(\w+)",
    r"(\w+)\s+(?:belongs to|falls under)\s+(?:the )?(?:category|class)\s+(?:of )?(\w+)",
    r"(\w+)\s+(?:classified as|categorized as)\s+(\w+)",
]

FR_PATTERNS = [
    r"(\w+)\s+est un(?:e)? (?:type|sorte|variante|version)\s+de\s+(\w+)",
    r"(\w+)\s+(?:appartient à|relève de)\s+(?:la )?(?:catégorie|classe)\s+(?:des? )?(\w+)",
    r"(\w+)\s+(?:classé comme|catégorisé comme)\s+(\w+)",
]

DE_PATTERNS = [
    r"(\w+)\s+ist ein(?:e)? (?:Typ|Art|Variante)\s+von\s+(\w+)",
    r"(\w+)\s+gehört zur (?:Kategorie|Klasse)\s+(\w+)",
]

ES_PATTERNS = [
    r"(\w+)\s+es un(?:a)? (?:tipo|variante|versión)\s+de\s+(\w+)",
    r"(\w+)\s+pertenece a la (?:categoría|clase)\s+(?:de )?(\w+)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Source (A) | Relation | Target (B) | Contexte |
|---------|-----------|----------|-----------|----------|
| **Software** | "SaaS CRM Solution" | SUBTYPE_OF | "Cloud Software" | Catégorisation produit |
| **Pharma** | "Monoclonal Antibody mAb-201" | SUBTYPE_OF | "Biologic Drug" | Classification médicament |
| **Retail** | "Omnichannel Checkout System" | SUBTYPE_OF | "Point-of-Sale System" | Type solution retail |
| **Manufacturing** | "CNC Milling Machine XYZ-1000" | SUBTYPE_OF | "Machining Equipment" | Taxonomie équipement |
| **Finance** | "High-Frequency Trading Algorithm" | SUBTYPE_OF | "Algorithmic Trading Strategy" | Catégorie stratégie |
| **Legal** | "Non-Disclosure Agreement (NDA)" | SUBTYPE_OF | "Confidentiality Contract" | Type document légal |

---

**Disambiguation vs PART_OF:**

```
┌────────────────────────────────────────────────────────┐
│              PART_OF vs SUBTYPE_OF Decision Tree        │
└────────────────────────────────────────────────────────┘

Question 1: A peut-il exister physiquement hors de B ?
   ├── OUI → Potentiel SUBTYPE_OF
   └── NON → Potentiel PART_OF

Question 2: A hérite-t-il des propriétés de B ?
   ├── OUI → SUBTYPE_OF
   └── NON → PART_OF

Question 3: B "contient" A ou B "catégorise" A ?
   ├── Contient → PART_OF
   └── Catégorise → SUBTYPE_OF

Exemples:
- "UI Module" PART_OF "ERP" (UI ne peut pas exister sans ERP)
- "Cloud ERP" SUBTYPE_OF "ERP" (Cloud ERP hérite concept ERP, existe indépendamment)
```

---

**Difficulté Détection:** ⭐⭐⭐ (MOYENNE-HAUTE)

**Méthode Extraction:**
1. **Pattern-based (50%):** Regex "is a type of", "belongs to category"
2. **LLM-assisted (50%):** Disambiguation PART_OF vs SUBTYPE_OF

**Validation:**
- Vérification transitivité taxonomique
- Cohérence avec hiérarchie domaine (si ontologie existante)
- Flag si A à la fois PART_OF et SUBTYPE_OF de B (incohérence probable)

---

## 🔗 FAMILLE 2 : DÉPENDANCES

### Type 2.1 : REQUIRES

**Définition Canonique (FR):**
Relation de dépendance stricte où le fonctionnement de A nécessite obligatoirement la présence/disponibilité de B.

**Canonical Definition (EN):**
Strict dependency relationship where A's operation mandatorily requires the presence/availability of B.

---

**Caractéristiques:**
- ✅ **Dépendance forte** (hard dependency)
- ✅ Directionnelle (A REQUIRES B ≠ B REQUIRES A)
- ✅ Critique pour planification déploiements, migrations
- ⚠️ Transitivité partielle (A REQUIRES B, B REQUIRES C → possiblement A REQUIRES C indirectement)

---

**Patterns de Détection:**

```python
EN_PATTERNS = [
    r"(\w+)\s+requires\s+(\w+)",
    r"(\w+)\s+(?:depends on|relies on|needs)\s+(\w+)",
    r"(\w+)\s+(?:cannot function|cannot operate)\s+without\s+(\w+)",
    r"(\w+)\s+(?:prerequisite|mandatory requirement):\s+(\w+)",
]

FR_PATTERNS = [
    r"(\w+)\s+(?:requiert|nécessite|exige)\s+(\w+)",
    r"(\w+)\s+(?:dépend de|repose sur)\s+(\w+)",
    r"(\w+)\s+(?:ne peut pas fonctionner|ne peut pas opérer)\s+sans\s+(\w+)",
    r"(\w+)\s+(?:prérequis|exigence obligatoire):\s+(\w+)",
]

DE_PATTERNS = [
    r"(\w+)\s+(?:benötigt|erfordert|braucht)\s+(\w+)",
    r"(\w+)\s+(?:hängt ab von|setzt voraus)\s+(\w+)",
]

ES_PATTERNS = [
    r"(\w+)\s+(?:requiere|necesita|exige)\s+(\w+)",
    r"(\w+)\s+(?:depende de|se basa en)\s+(\w+)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Source (A) | Relation | Target (B) | Contexte |
|---------|-----------|----------|-----------|----------|
| **Software** | "Mobile App v2.0" | REQUIRES | "Backend API v1.5+" | Dépendance technique |
| **Pharma** | "Drug Administration Protocol X" | REQUIRES | "Patient Consent Form Signed" | Prérequis régulaire |
| **Retail** | "Online Checkout Flow" | REQUIRES | "Payment Gateway Active" | Dépendance transactionnelle |
| **Manufacturing** | "Automated Quality Control" | REQUIRES | "Sensor Calibration Completed" | Prérequis opérationnel |
| **Finance** | "Derivative Trading Authorization" | REQUIRES | "Risk Assessment Certification" | Compliance obligatoire |
| **Legal** | "Contract Execution" | REQUIRES | "Signatory Authority Verified" | Prérequis juridique |

---

**Difficulté Détection:** ⭐⭐ (MOYENNE)

**Méthode Extraction:**
1. **Pattern-based (75%):** Regex "requires", "depends on", "prerequisite"
2. **LLM-assisted (25%):** Validation force dépendance (vs USES optionnel)

---

### Type 2.2 : USES

**Définition Canonique (FR):**
Relation d'utilisation optionnelle où A fait usage de B mais peut fonctionner (potentiellement en mode dégradé) sans B.

**Canonical Definition (EN):**
Optional usage relationship where A makes use of B but can operate (potentially in degraded mode) without B.

---

**Caractéristiques:**
- ✅ **Dépendance faible** (soft dependency)
- ✅ Flexibilité : alternative possible, mode dégradé acceptable
- ✅ Directionnelle (A USES B ≠ B USES A)
- ⚠️ Frontière floue avec REQUIRES (nécessite decision tree)

---

**Patterns de Détection:**

```python
EN_PATTERNS = [
    r"(\w+)\s+uses\s+(\w+)",
    r"(\w+)\s+(?:leverages|utilizes|employs)\s+(\w+)",
    r"(\w+)\s+(?:optionally|can)\s+(?:integrate with|connect to)\s+(\w+)",
    r"(\w+)\s+(?:compatible with|works with)\s+(\w+)",
]

FR_PATTERNS = [
    r"(\w+)\s+(?:utilise|exploite|emploie)\s+(\w+)",
    r"(\w+)\s+(?:peut|peut optionnellement)\s+(?:s'intégrer avec|se connecter à)\s+(\w+)",
    r"(\w+)\s+(?:compatible avec|fonctionne avec)\s+(\w+)",
]

DE_PATTERNS = [
    r"(\w+)\s+(?:verwendet|nutzt|benutzt)\s+(\w+)",
    r"(\w+)\s+(?:kompatibel mit|funktioniert mit)\s+(\w+)",
]

ES_PATTERNS = [
    r"(\w+)\s+(?:utiliza|emplea|usa)\s+(\w+)",
    r"(\w+)\s+(?:compatible con|funciona con)\s+(\w+)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Source (A) | Relation | Target (B) | Contexte |
|---------|-----------|----------|-----------|----------|
| **Software** | "Analytics Dashboard" | USES | "Third-Party Charting Library" | Librairie optionnelle |
| **Pharma** | "Drug Delivery System" | USES | "Smart Dosage Sensor" | Enhancement optionnel |
| **Retail** | "E-commerce Platform" | USES | "Recommendation Engine AI" | Feature add-on |
| **Manufacturing** | "Production Line Monitor" | USES | "Predictive Maintenance AI" | Optimisation optionnelle |
| **Finance** | "Trading Terminal" | USES | "Real-Time News Feed API" | Data source secondaire |
| **Legal** | "Contract Management System" | USES | "E-Signature Service" | Service intégré optionnel |

---

**Disambiguation vs REQUIRES:**

```
┌────────────────────────────────────────────────────────┐
│              REQUIRES vs USES Decision Tree             │
└────────────────────────────────────────────────────────┘

Question 1: A peut-il fonctionner (même en mode dégradé) sans B ?
   ├── OUI → USES
   └── NON → REQUIRES

Question 2: L'absence de B provoque-t-elle un échec critique de A ?
   ├── OUI → REQUIRES
   └── NON → USES

Question 3: B est-il documenté comme "prérequis" ou "obligatoire" ?
   ├── OUI → REQUIRES
   └── NON → USES

Question 4: Une alternative à B existe-t-elle ?
   ├── OUI → USES (sauf si alternative aussi obligatoire → REQUIRES)
   └── NON → Vérifier Q1-Q3

Exemples:
- "Mobile App" REQUIRES "Backend API" (échec si API down)
- "Mobile App" USES "Analytics SDK" (fonctionne sans analytics)
```

---

**Difficulté Détection:** ⭐⭐⭐ (MOYENNE-HAUTE)

**Méthode Extraction:**
1. **Pattern-based (60%):** Regex "uses", "optionally", "compatible with"
2. **LLM-assisted (40%):** Decision tree REQUIRES vs USES
3. **Context analysis:** Termes "optional", "can", "compatible" → USES

**Validation:**
- Flag si A à la fois REQUIRES et USES B (choisir le plus fort → REQUIRES)
- Cohérence avec documentation technique (chercher "mandatory", "optional")

---

## 🔌 FAMILLE 3 : INTÉGRATIONS

### Type 3.1 : INTEGRATES_WITH

**Définition Canonique (FR):**
Relation d'intégration bidirectionnelle où deux systèmes échangent données ou fonctionnalités de manière coordonnée.

**Canonical Definition (EN):**
Bidirectional integration relationship where two systems exchange data or functionalities in a coordinated manner.

---

**Caractéristiques:**
- ✅ **Bidirectionnelle** (A INTEGRATES_WITH B → B INTEGRATES_WITH A implicite)
- ✅ Égalité fonctionnelle (pas de hiérarchie)
- ✅ Coordination technique (API, webhooks, middleware)
- ⚠️ Ne pas confondre avec USES (unidirectionnel, pas nécessairement coordonné)

---

**Patterns de Détection:**

```python
EN_PATTERNS = [
    r"(\w+)\s+integrates with\s+(\w+)",
    r"(\w+)\s+(?:connects to|interfaces with|syncs with)\s+(\w+)",
    r"(?:bidirectional|two-way)\s+integration\s+between\s+(\w+)\s+and\s+(\w+)",
    r"(\w+)\s+and\s+(\w+)\s+(?:exchange data|communicate|interoperate)",
]

FR_PATTERNS = [
    r"(\w+)\s+(?:s'intègre avec|s'interface avec)\s+(\w+)",
    r"(\w+)\s+(?:se connecte à|communique avec|synchronise avec)\s+(\w+)",
    r"intégration\s+(?:bidirectionnelle|bi-directionnelle)\s+entre\s+(\w+)\s+et\s+(\w+)",
    r"(\w+)\s+et\s+(\w+)\s+(?:échangent des données|communiquent|interopèrent)",
]

DE_PATTERNS = [
    r"(\w+)\s+(?:integriert sich mit|verbindet sich mit)\s+(\w+)",
    r"(\w+)\s+und\s+(\w+)\s+(?:tauschen Daten aus|kommunizieren)",
]

ES_PATTERNS = [
    r"(\w+)\s+(?:se integra con|se conecta con)\s+(\w+)",
    r"(\w+)\s+y\s+(\w+)\s+(?:intercambian datos|comunican)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | System A | Relation | System B | Contexte |
|---------|---------|----------|---------|----------|
| **Software** | "CRM Platform" | INTEGRATES_WITH | "Marketing Automation Tool" | Sync contacts bidirectionnel |
| **Pharma** | "Clinical Trial Management System" | INTEGRATES_WITH | "Electronic Health Records (EHR)" | Échange données patients |
| **Retail** | "Inventory Management" | INTEGRATES_WITH | "E-commerce Platform" | Sync stock temps réel |
| **Manufacturing** | "MES (Manufacturing Execution System)" | INTEGRATES_WITH | "ERP System" | Coordination production/planification |
| **Finance** | "Trading Platform" | INTEGRATES_WITH | "Risk Management System" | Échange positions/expositions |
| **Legal** | "Case Management System" | INTEGRATES_WITH | "Document Repository" | Sync documents juridiques |

---

**Difficulté Détection:** ⭐⭐ (MOYENNE)

**Méthode Extraction:**
1. **Pattern-based (70%):** Regex "integrates with", "bidirectional"
2. **LLM-assisted (30%):** Validation bidirectionnalité

**Validation:**
- Créer relation symétrique automatique (A INTEGRATES_WITH B → B INTEGRATES_WITH A)
- Flag si asymétrie détectée (possiblement USES au lieu de INTEGRATES_WITH)

---

### Type 3.2 : EXTENDS ⚠️ (PHASE 2.5 OPTIONNEL)

**Définition Canonique (FR):**
Relation d'extension où A ajoute fonctionnalités spécialisées à B sans modifier le cœur de B.

**Canonical Definition (EN):**
Extension relationship where A adds specialized functionalities to B without modifying B's core.

---

**Caractéristiques:**
- ✅ **Directionnelle** (A EXTENDS B ≠ B EXTENDS A)
- ✅ Préservation intégrité de B (add-on, plugin, module)
- ⚠️ Difficulté: frontière floue avec PART_OF
- ⚠️ Implémentation Phase 2.5 uniquement (si ressources disponibles)

---

**Patterns de Détection:**

```python
EN_PATTERNS = [
    r"(\w+)\s+(?:extends|enhances|augments)\s+(\w+)",
    r"(\w+)\s+is an (?:extension|add-on|plugin)\s+(?:for|of)\s+(\w+)",
    r"(\w+)\s+(?:adds functionality to|provides additional features for)\s+(\w+)",
]

FR_PATTERNS = [
    r"(\w+)\s+(?:étend|améliore|enrichit)\s+(\w+)",
    r"(\w+)\s+est une (?:extension|module complémentaire)\s+(?:pour|de)\s+(\w+)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Extension (A) | Relation | Base System (B) | Contexte |
|---------|--------------|----------|----------------|----------|
| **Software** | "Advanced Analytics Module" | EXTENDS | "Base CRM Platform" | Add-on optionnel |
| **Pharma** | "Pediatric Dosage Calculator" | EXTENDS | "Drug Administration System" | Module spécialisé |
| **Retail** | "Loyalty Program Engine" | EXTENDS | "E-commerce Checkout" | Feature enhancement |

---

**Difficulté Détection:** ⭐⭐⭐⭐ (HAUTE - Phase 2.5)

**Critères GO Phase 2.5:**
- ✅ 9 types core déployés avec succès
- ✅ Bandwidth équipe disponible
- ✅ Gold standard annoté pour EXTENDS (≥20 exemples)

---

## ⚡ FAMILLE 4 : CAPACITÉS

### Type 4.1 : ENABLES ⚠️ (PHASE 2.5 OPTIONNEL)

**Définition Canonique (FR):**
Relation où A débloque ou rend possible une capacité fonctionnelle B, sans que A soit directement utilisé dans B.

**Canonical Definition (EN):**
Relationship where A unlocks or enables a functional capability B, without A being directly used in B.

---

**Caractéristiques:**
- ✅ **Relation abstraite** (causalité indirecte)
- ⚠️ **Très difficile à détecter automatiquement** (nécessite raisonnement causal)
- ⚠️ Risque faux positifs élevé (confusion avec REQUIRES)
- ⚠️ Implémentation Phase 2.5 UNIQUEMENT avec contraintes strictes

---

**Contraintes Strictes Phase 2.5:**

```
┌────────────────────────────────────────────────────────┐
│           ENABLES - Contraintes d'Implémentation        │
└────────────────────────────────────────────────────────┘

1. Validation manuelle obligatoire:
   - ✅ Relations ENABLES nécessitent flag "require_human_validation: true"
   - ✅ Confidence threshold ≥ 0.85 pour extraction automatique
   - ✅ Justification textuelle requise (source chunk + explication)

2. Contexte extraction restreint:
   - ✅ Sections "Capabilities", "Business Benefits", "What's New"
   - ❌ Éviter sections techniques détaillées (risque confusion REQUIRES)

3. Détection LLM obligatoire:
   - ❌ Pattern-based INSUFFISANT (trop de faux positifs)
   - ✅ LLM prompt spécialisé avec few-shot examples

4. Gold standard strict:
   - ✅ ≥ 30 exemples annotés manuellement
   - ✅ Inter-annotator agreement ≥ 0.80 (Cohen's Kappa)
```

---

**Patterns de Détection (LLM-assisted uniquement):**

```python
# LLM Prompt Template (GPT-4o-mini)
ENABLES_DETECTION_PROMPT = """
Analyze if concept A ENABLES capability B (causal relationship, not direct usage).

STRICT CRITERIA:
1. A does NOT directly execute B
2. A is a prerequisite/foundation that makes B possible
3. B is a higher-level business capability

Context: {chunk_text}
Concept A: {concept_a}
Potential Capability B: {concept_b}

Examples:
- "Data Integration Platform" ENABLES "Real-Time Analytics" ✅
- "Database" REQUIRES "Storage" ❌ (too direct)

Question: Does A ENABLE B according to strict criteria?
Answer: [YES/NO/UNCERTAIN]
Confidence: [0.0-1.0]
Justification: [1-2 sentences]
"""
```

---

**Exemples Multi-Domaines (Gold Standard):**

| Domaine | Enabler (A) | Relation | Capability (B) | Justification |
|---------|------------|----------|---------------|--------------|
| **Software** | "API Management Platform" | ENABLES | "Third-Party Ecosystem Growth" | API mgmt crée conditions pour intégrations tierces, sans les exécuter directement |
| **Pharma** | "Clinical Data Standardization Framework" | ENABLES | "Cross-Study Meta-Analysis" | Standardisation rend possibles analyses comparatives, sans analyser elle-même |
| **Retail** | "Customer Identity Resolution System" | ENABLES | "Personalized Marketing at Scale" | Résolution identité débloque personnalisation, sans créer campagnes |

---

**Difficulté Détection:** ⭐⭐⭐⭐ (TRÈS HAUTE - Phase 2.5)

**Méthode Extraction:**
1. **LLM-only (100%):** GPT-4o avec prompt spécialisé + few-shot
2. **Human validation:** Toutes relations ENABLES nécessitent review manuelle
3. **Confidence threshold:** ≥ 0.85 minimum

**KPIs Phase 2.5 ENABLES:**
- Precision ≥ 75% (seuil réduit vu complexité)
- Recall ≥ 40% (acceptable pour type optionnel)
- Human validation coverage: 100% relations détectées
- False positive rate: < 15%

**Décision GO/NO-GO:**
- ✅ GO si ressources humaines disponibles pour validation
- ❌ NO-GO si délai Phase 2 à risque → Reporter Phase 3

---

## ⏱️ FAMILLE 5 : TEMPORELLES

### Type 5.1 : VERSION_OF

**Définition Canonique (FR):**
Relation de versionnage chronologique où A est une version spécifique d'un produit/système B évolutif.

**Canonical Definition (EN):**
Chronological versioning relationship where A is a specific version of an evolving product/system B.

---

**Caractéristiques:**
- ✅ **Relation chronologique** (timeline construction)
- ✅ Bidirectionnelle (v2.0 VERSION_OF "Product X", "Product X" HAS_VERSION v2.0)
- ✅ Utilisée pour CRR Evolution Tracker (killer feature Phase 2)
- ✅ Détection automatique via regex versions (v1.0, 2023.Q1, etc.)

---

**Patterns de Détection:**

```python
# Patterns regex versions (multilingue)
VERSION_PATTERNS = [
    r"(\w+)\s+v?(\d+\.\d+(?:\.\d+)?)",  # "Product v2.1.0"
    r"(\w+)\s+version\s+(\d+\.\d+)",     # "Product version 3.0"
    r"(\w+)\s+(\d{4})(?:\s*Q[1-4])?",    # "Product 2023 Q2"
    r"(\w+)\s+(?:release|édition)\s+(\d{4})",  # "Product release 2024"
]

# Contexte extraction
CONTEXT_KEYWORDS = [
    "release notes", "changelog", "version history",
    "notes de version", "historique versions",
    "versionshinweise", "notas de versión"
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Version (A) | Relation | Product (B) | Contexte |
|---------|------------|----------|------------|----------|
| **Software** | "CRM Platform v5.2" | VERSION_OF | "CRM Platform" | Release notes |
| **Pharma** | "Clinical Trial Protocol v3.1" | VERSION_OF | "Clinical Trial Protocol XYZ" | Protocol amendments |
| **Retail** | "Loyalty Program 2024 Edition" | VERSION_OF | "Loyalty Program" | Annual refresh |
| **Manufacturing** | "Quality Standard ISO-9001:2015" | VERSION_OF | "ISO-9001 Standard" | Standard evolution |
| **Finance** | "Compliance Framework Basel III" | VERSION_OF | "Basel Accords" | Regulatory versions |
| **Legal** | "GDPR Article 17 (2018 revision)" | VERSION_OF | "GDPR Article 17" | Legal amendments |

---

**Difficulté Détection:** ⭐ (FAIBLE - automatisable)

**Méthode Extraction:**
1. **Pattern-based (90%):** Regex versions numériques
2. **Context filtering (10%):** Sections "release notes", "changelog"

**Validation:**
- Extraction date/timestamp si disponible
- Construction timeline automatique (v1.0 → v1.5 → v2.0)
- Flag si versions non-consécutives (v1.0 → v3.0 → manque v2.0 ?)

---

### Type 5.2 : PRECEDES

**Définition Canonique (FR):**
Relation de succession chronologique où A précède directement B dans le temps, sans nécessairement le remplacer.

**Canonical Definition (EN):**
Chronological succession relationship where A directly precedes B in time, without necessarily replacing it.

---

**Caractéristiques:**
- ✅ **Ordre chronologique strict** (A avant B)
- ✅ Directionnelle (A PRECEDES B ≠ B PRECEDES A)
- ✅ Compatible avec coexistence (A et B peuvent exister simultanément)
- ⚠️ Différent de REPLACES (pas d'obsolescence impliquée)

---

**Patterns de Détection:**

```python
EN_PATTERNS = [
    r"(\w+)\s+(?:precedes|comes before|was before)\s+(\w+)",
    r"(\w+)\s+→\s+(\w+)",  # Timeline arrows
    r"(?:timeline|sequence|chronology):\s+(\w+)\s+(?:→|>|followed by)\s+(\w+)",
    r"(\w+)\s+\((\d{4})\).*(\w+)\s+\((\d{4})\)",  # Date-based detection
]

FR_PATTERNS = [
    r"(\w+)\s+(?:précède|vient avant|était avant)\s+(\w+)",
    r"(?:chronologie|séquence):\s+(\w+)\s+(?:→|>|suivi de)\s+(\w+)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Earlier (A) | Relation | Later (B) | Contexte |
|---------|------------|----------|----------|----------|
| **Software** | "Beta Phase Testing" | PRECEDES | "General Availability (GA)" | Release lifecycle |
| **Pharma** | "Phase II Clinical Trial" | PRECEDES | "Phase III Clinical Trial" | Drug development stages |
| **Retail** | "Black Friday Campaign" | PRECEDES | "Cyber Monday Campaign" | Seasonal calendar |
| **Manufacturing** | "Prototype Validation" | PRECEDES | "Mass Production" | Product lifecycle |
| **Finance** | "Prospectus Publication" | PRECEDES | "IPO Launch" | Capital raising sequence |
| **Legal** | "Discovery Phase" | PRECEDES | "Trial Phase" | Litigation process |

---

**Difficulté Détection:** ⭐⭐ (MOYENNE)

**Méthode Extraction:**
1. **Pattern-based (60%):** Regex "precedes", timeline arrows
2. **Date-based (30%):** Extraction timestamps documents
3. **LLM-assisted (10%):** Validation ordre logique

---

### Type 5.3 : REPLACES

**Définition Canonique (FR):**
Relation de remplacement où A succède à B et rend B obsolète ou déprécié.

**Canonical Definition (EN):**
Replacement relationship where A succeeds B and renders B obsolete or deprecated.

---

**Caractéristiques:**
- ✅ **Obsolescence impliquée** (B devient legacy)
- ✅ Directionnelle (A REPLACES B ≠ B REPLACES A)
- ✅ Critique pour migration planning, breaking changes
- ✅ Utilisée pour CRR Evolution Tracker (changements majeurs)

---

**Patterns de Détection:**

```python
EN_PATTERNS = [
    r"(\w+)\s+replaces\s+(\w+)",
    r"(\w+)\s+(?:supersedes|deprecates)\s+(\w+)",
    r"(\w+)\s+is the (?:successor|replacement)\s+(?:to|of|for)\s+(\w+)",
    r"(?:migrat(?:e|ion) from|upgrade from)\s+(\w+)\s+(?:to|→)\s+(\w+)",
]

FR_PATTERNS = [
    r"(\w+)\s+remplace\s+(\w+)",
    r"(\w+)\s+(?:succède à|obsolète)\s+(\w+)",
    r"(?:migrat(?:er|ion) de|mise à niveau de)\s+(\w+)\s+(?:vers|→)\s+(\w+)",
]

DE_PATTERNS = [
    r"(\w+)\s+(?:ersetzt|löst ab)\s+(\w+)",
    r"(?:Migration von|Upgrade von)\s+(\w+)\s+(?:zu|→)\s+(\w+)",
]

ES_PATTERNS = [
    r"(\w+)\s+reemplaza\s+(\w+)",
    r"(?:migración de|actualización de)\s+(\w+)\s+(?:a|→)\s+(\w+)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Successor (A) | Relation | Legacy (B) | Contexte |
|---------|--------------|----------|-----------|----------|
| **Software** | "Cloud Platform v3.0" | REPLACES | "On-Premise Platform v2.5" | Architecture shift |
| **Pharma** | "mRNA Vaccine Protocol" | REPLACES | "Traditional Inactivated Vaccine" | Technology evolution |
| **Retail** | "Contactless Payment System" | REPLACES | "Magnetic Stripe Card Reader" | Payment modernization |
| **Manufacturing** | "Collaborative Robot (Cobot)" | REPLACES | "Traditional Industrial Robot" | Workforce integration |
| **Finance** | "Instant Payment Standard ISO 20022" | REPLACES | "Legacy SWIFT MT Messages" | Standard migration |
| **Legal** | "GDPR (2018)" | REPLACES | "Data Protection Directive 95/46/EC" | Regulation update |

---

**Use Case Killer - CRR Evolution Tracker:**

```cypher
// Query: Trouver tous les breaking changes SAP CCR 2020 → 2025
MATCH path = (old:CanonicalConcept)-[:REPLACES*1..5]->(new:CanonicalConcept)
WHERE old.canonical_name CONTAINS "CCR"
  AND old.temporal_metadata.valid_until = "2020"
  AND new.temporal_metadata.valid_from >= "2021"
RETURN path,
       old.canonical_name as legacy_component,
       new.canonical_name as successor_component,
       new.breaking_changes as impact_assessment
ORDER BY new.temporal_metadata.valid_from
```

---

**Difficulté Détection:** ⭐⭐⭐ (MOYENNE-HAUTE)

**Méthode Extraction:**
1. **Pattern-based (65%):** Regex "replaces", "migration from X to Y"
2. **LLM-assisted (35%):** Détection breaking changes contextuels
3. **Temporal analysis:** Extraction dates valid_from/valid_until

**Validation:**
- Vérification dates cohérentes (A.valid_from ≥ B.valid_until)
- Flag si A et B actifs simultanément longtemps (possiblement PRECEDES, pas REPLACES)
- Enrichissement métadonnées: breaking_changes, migration_effort

---

### Type 5.4 : DEPRECATES

**Définition Canonique (FR):**
Relation de dépréciation où A marque B comme obsolète sans proposer de remplaçant direct immédiat.

**Canonical Definition (EN):**
Deprecation relationship where A marks B as obsolete without providing an immediate direct replacement.

---

**Caractéristiques:**
- ✅ **Obsolescence sans successeur immédiat**
- ✅ Directionnelle (A DEPRECATES B)
- ✅ Différent de REPLACES (pas de remplaçant explicite)
- ✅ Signale "End of Life", "Sunset", "Phase Out"

---

**Patterns de Détection:**

```python
EN_PATTERNS = [
    r"(\w+)\s+(?:deprecates|sunsets|phases out)\s+(\w+)",
    r"(\w+)\s+(?:end of life|EOL|discontinued)",
    r"(\w+)\s+(?:no longer supported|support ended)",
]

FR_PATTERNS = [
    r"(\w+)\s+(?:déprécie|abandonne|arrête)\s+(\w+)",
    r"(\w+)\s+(?:fin de vie|fin de support|discontinué)",
]

DE_PATTERNS = [
    r"(\w+)\s+(?:veraltet|wird eingestellt)\s+(\w+)",
    r"(\w+)\s+(?:Ende der Unterstützung|abgekündigt)",
]

ES_PATTERNS = [
    r"(\w+)\s+(?:desaprueba|descontinúa)\s+(\w+)",
    r"(\w+)\s+(?:fin de vida|fin de soporte)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Deprecator (A) | Relation | Deprecated (B) | Contexte |
|---------|---------------|----------|---------------|----------|
| **Software** | "Platform Roadmap 2025" | DEPRECATES | "Legacy API v1.x" | End of support announcement |
| **Pharma** | "Regulatory Update 2024" | DEPRECATES | "Manual Reporting Process" | Compliance evolution |
| **Retail** | "Digital Strategy 2023" | DEPRECATES | "Physical Gift Card Program" | Digital transformation |
| **Manufacturing** | "Safety Standard Revision" | DEPRECATES | "Old Equipment Certification" | Standard sunset |
| **Finance** | "Basel IV Framework" | DEPRECATES | "Certain Basel III Approaches" | Regulatory phase-out |
| **Legal** | "Court Ruling 2024-XYZ" | DEPRECATES | "Precedent ABC-1998" | Jurisprudence evolution |

---

**Difficulté Détection:** ⭐⭐ (MOYENNE)

**Méthode Extraction:**
1. **Pattern-based (75%):** Regex "deprecates", "end of life", "discontinued"
2. **LLM-assisted (25%):** Validation absence remplaçant explicite

**Validation:**
- Flag si REPLACES détecté simultanément (choisir REPLACES, plus spécifique)
- Extraction date EOL si disponible
- Vérifier absence relation VERSION_OF vers successeur (sinon utiliser REPLACES)

---

## 🔄 FAMILLE 6 : VARIANTES

### Type 6.1 : ALTERNATIVE_TO ⚠️ (PHASE 2.5 OPTIONNEL)

**Définition Canonique (FR):**
Relation d'alternative fonctionnelle où A et B offrent des capacités similaires et peuvent être substitués selon contexte.

**Canonical Definition (EN):**
Functional alternative relationship where A and B offer similar capabilities and can be substituted depending on context.

---

**Caractéristiques:**
- ✅ **Bidirectionnelle** (A ALTERNATIVE_TO B → B ALTERNATIVE_TO A)
- ✅ Équivalence fonctionnelle partielle (use case dependent)
- ⚠️ Difficulté: subjectivité ("alternative" vs "compétiteur")
- ⚠️ Implémentation Phase 2.5 uniquement (si bandwidth disponible)

---

**Patterns de Détection:**

```python
EN_PATTERNS = [
    r"(\w+)\s+(?:is an alternative to|alternatively)\s+(\w+)",
    r"(?:choose between|select between)\s+(\w+)\s+(?:or|and)\s+(\w+)",
    r"(\w+)\s+(?:competes with|rivals)\s+(\w+)",
]

FR_PATTERNS = [
    r"(\w+)\s+est une alternative à\s+(\w+)",
    r"(?:choisir entre|sélectionner entre)\s+(\w+)\s+(?:ou|et)\s+(\w+)",
]
```

---

**Exemples Multi-Domaines:**

| Domaine | Option A | Relation | Option B | Contexte |
|---------|---------|----------|---------|----------|
| **Software** | "SQL Database" | ALTERNATIVE_TO | "NoSQL Database" | Data persistence choice |
| **Pharma** | "Oral Administration Route" | ALTERNATIVE_TO | "Intravenous Administration" | Delivery method options |
| **Retail** | "Home Delivery" | ALTERNATIVE_TO | "Click & Collect" | Fulfillment alternatives |

---

**Difficulté Détection:** ⭐⭐⭐⭐ (HAUTE - Phase 2.5)

**Critères GO Phase 2.5:**
- ✅ Ressources disponibles post-9 types core
- ✅ Use case business validé (valeur ajoutée démontrée)
- ✅ Gold standard annoté (≥25 exemples)

---

## 📊 Métadonnées Relations (Toutes Familles)

### Schéma Neo4j Metadata Layer

```cypher
// Propriétés communes à TOUTES relations
CREATE (a:CanonicalConcept)-[r:RELATION_TYPE]->(b:CanonicalConcept)
SET r.confidence = 0.87,              // Float [0.0-1.0]
    r.extraction_method = "pattern",   // Enum: pattern|llm|hybrid|inferred
    r.source_doc_id = "doc_12345",     // Document source
    r.source_chunk_ids = ["chunk_A", "chunk_B"],  // Justification
    r.language = "EN",                 // Langue détection
    r.created_at = datetime(),         // Timestamp création
    r.valid_from = date("2024-01-01"), // Validité temporelle (optionnel)
    r.valid_until = date("2025-12-31"), // Fin validité (optionnel)
    r.strength = "strong",             // Enum: weak|moderate|strong
    r.status = "active",               // Enum: active|deprecated|inferred
    r.require_validation = false       // Boolean (true pour ENABLES)
```

### Enrichissement Contextuel

**Relations REPLACES spécifiques:**
```cypher
SET r.breaking_changes = ["API signature modified", "Data model changed"],
    r.migration_effort = "HIGH",  // Enum: LOW|MEDIUM|HIGH
    r.backward_compatible = false
```

**Relations TEMPORAL (VERSION_OF, PRECEDES, REPLACES, DEPRECATES):**
```cypher
SET r.timeline_position = 3,  // Position dans séquence chronologique
    r.release_date = date("2024-06-15"),
    r.eol_date = date("2026-12-31")  // Pour DEPRECATES
```

---

## 🛠️ Guide Implémentation Technique

### Phase 2 Initial (Semaines 14-21) - 9 Types Core

**Priorité 1 (Semaines 14-15):**
- ✅ PART_OF (⭐⭐)
- ✅ REQUIRES (⭐⭐)
- ✅ USES (⭐⭐⭐)
- ✅ INTEGRATES_WITH (⭐⭐)

**Priorité 2 (Semaines 16-17):**
- ✅ SUBTYPE_OF (⭐⭐⭐) - Taxonomy building
- ✅ VERSION_OF (⭐)
- ✅ PRECEDES (⭐⭐)

**Priorité 3 (Semaines 18-21):**
- ✅ REPLACES (⭐⭐⭐) - CRR Evolution Tracker
- ✅ DEPRECATES (⭐⭐)

---

### Phase 2.5 Optionnel (Semaines 22-24) - 3 Types Expérimentaux

**GO Criteria:**
```python
def evaluate_phase_2_5_readiness() -> bool:
    """Évalue si Phase 2.5 peut démarrer"""
    return (
        core_types_coverage >= 0.80 and
        core_types_precision >= 0.80 and
        core_types_recall >= 0.65 and
        conflict_rate < 0.08 and
        team_bandwidth_available and
        gold_standard_phase_2_5_ready  # ≥25 examples EXTENDS, ENABLES, ALTERNATIVE_TO
    )
```

**Types Phase 2.5:**
- ⚠️ EXTENDS (⭐⭐⭐⭐)
- ⚠️ ENABLES (⭐⭐⭐⭐) - Validation manuelle obligatoire
- ⚠️ ALTERNATIVE_TO (⭐⭐⭐⭐)

---

### Architecture Extraction Hybrid

```python
# src/knowbase/relations/extraction_engine.py

class RelationExtractionEngine:
    """Moteur extraction hybride Pattern + LLM"""

    def extract_relation(
        self,
        concept_a: str,
        concept_b: str,
        context_chunk: str,
        language: str = "EN"
    ) -> Optional[ExtractedRelation]:

        # 1. Pattern-based detection
        pattern_result = self._pattern_based_extraction(
            concept_a, concept_b, context_chunk, language
        )

        if pattern_result and pattern_result.confidence >= 0.80:
            return pattern_result  # High confidence, skip LLM

        # 2. LLM-assisted classification (si pattern ambigu)
        llm_result = self._llm_classification(
            concept_a, concept_b, context_chunk,
            pattern_hint=pattern_result.type if pattern_result else None
        )

        # 3. Disambiguation (ex: REQUIRES vs USES)
        if llm_result.type in ["REQUIRES", "USES"]:
            llm_result = self._disambiguate_requires_vs_uses(
                concept_a, concept_b, context_chunk, llm_result
            )

        # 4. Metadata enrichment
        llm_result.extraction_method = "hybrid"
        llm_result.source_chunk_id = context_chunk.id

        return llm_result if llm_result.confidence >= 0.70 else None
```

---

### Decision Trees - REQUIRES vs USES

```python
def disambiguate_requires_vs_uses(
    concept_a: str,
    concept_b: str,
    context: str,
    initial_result: ExtractedRelation
) -> ExtractedRelation:
    """Decision tree REQUIRES vs USES"""

    # Q1: Mandatory keywords présents ?
    mandatory_keywords = ["requires", "mandatory", "prerequisite", "must", "necessary"]
    if any(kw in context.lower() for kw in mandatory_keywords):
        initial_result.type = "REQUIRES"
        initial_result.confidence *= 1.1  # Boost confidence
        return initial_result

    # Q2: Optional keywords présents ?
    optional_keywords = ["optional", "can", "compatible", "works with", "may"]
    if any(kw in context.lower() for kw in optional_keywords):
        initial_result.type = "USES"
        initial_result.confidence *= 1.1
        return initial_result

    # Q3: LLM fallback pour cas ambigus
    llm_prompt = f"""
    Determine if this dependency is MANDATORY (REQUIRES) or OPTIONAL (USES):

    Component A: {concept_a}
    Component B: {concept_b}
    Context: {context}

    Question: Can A function (even in degraded mode) without B?
    Answer ONLY: REQUIRES or USES
    Confidence: [0.0-1.0]
    """

    llm_response = llm_client.complete(llm_prompt)
    initial_result.type = llm_response.relation_type
    initial_result.confidence = min(llm_response.confidence, 0.85)  # Cap pour ambiguïté

    return initial_result
```

---

## 📈 KPIs & Validation

### Métriques Phase 2 (9 Types Core)

| KPI | Target | Critique GO Phase 3 |
|-----|--------|---------------------|
| **Precision Extraction** | ≥ 80% | ✅ OUI |
| **Recall Extraction** | ≥ 65% | ⚠️ Nice-to-have |
| **Coverage (% concepts with ≥1 relation)** | ≥ 70% | ✅ OUI |
| **Temporal relations (% versioned concepts)** | ≥ 90% | ✅ OUI (CRR Tracker) |
| **Conflict rate** | < 8% | ✅ OUI |
| **Cycles détectés** | 0 | ✅ OUI (cohérence) |
| **Avg relations/concept** | ≥ 1.5 | ⚠️ Nice-to-have |
| **Transitive inference rate** | ≥ 30% | ⚠️ Nice-to-have (Phase 2.1) |

---

### Gold Standard Annotation

**Corpus Test:**
- 100 documents multi-domaines (Software 40%, Pharma 20%, Retail 20%, Manufacturing 10%, Finance 5%, Legal 5%)
- 50 relations annotées manuellement par type (450 total pour 9 types core)
- Inter-annotator agreement (Cohen's Kappa) ≥ 0.75

**Process:**
```bash
# Génération gold standard
python scripts/annotate_relations_gold_standard.py \
    --corpus data/phase2_test/ \
    --types PART_OF,REQUIRES,USES,INTEGRATES_WITH,SUBTYPE_OF,VERSION_OF,PRECEDES,REPLACES,DEPRECATES \
    --samples_per_type 50 \
    --annotators 2 \
    --output data/phase2_gold_standard.json
```

---

### Tests Validation

```python
# tests/relations/test_relation_extraction.py

def test_requires_vs_uses_disambiguation():
    """Valider decision tree REQUIRES vs USES"""

    # Cas REQUIRES (mandatory)
    context_requires = "Mobile App requires Backend API v1.5+ to function"
    result = engine.extract_relation("Mobile App", "Backend API", context_requires)
    assert result.type == "REQUIRES"
    assert result.confidence >= 0.80

    # Cas USES (optional)
    context_uses = "Dashboard can optionally integrate with Analytics SDK"
    result = engine.extract_relation("Dashboard", "Analytics SDK", context_uses)
    assert result.type == "USES"
    assert result.confidence >= 0.75

def test_part_of_vs_subtype_of_disambiguation():
    """Valider distinction PART_OF vs SUBTYPE_OF"""

    # PART_OF (composition)
    context_part = "UI Module is a component of ERP Platform"
    result = engine.extract_relation("UI Module", "ERP Platform", context_part)
    assert result.type == "PART_OF"

    # SUBTYPE_OF (categorization)
    context_subtype = "Cloud ERP is a type of ERP System"
    result = engine.extract_relation("Cloud ERP", "ERP System", context_subtype)
    assert result.type == "SUBTYPE_OF"

def test_temporal_relations_timeline():
    """Valider construction timeline via VERSION_OF + PRECEDES"""

    # Ingest 3 versions
    engine.ingest_concept("Product v1.0", temporal_metadata={"release_date": "2022-01-01"})
    engine.ingest_concept("Product v1.5", temporal_metadata={"release_date": "2023-06-15"})
    engine.ingest_concept("Product v2.0", temporal_metadata={"release_date": "2024-12-01"})

    # Vérifier timeline construite
    timeline = engine.get_timeline("Product")
    assert timeline == ["Product v1.0", "Product v1.5", "Product v2.0"]
    assert all(r.type == "PRECEDES" for r in engine.get_relations_between_versions())
```

---

## 🚀 Quick Start Développeurs

### Setup Environment

```bash
# Dependencies Phase 2
pip install sentence-transformers==2.2.2  # Embeddings similarity
pip install scikit-learn==1.3.0           # Clustering taxonomy
pip install networkx==3.1                 # Graph inference
pip install spacy==3.7.0                  # Dependency parsing
python -m spacy download en_core_web_sm   # English model
python -m spacy download fr_core_news_sm  # French model

# Neo4j schema extensions
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass < schema_phase2_relations.cypher
```

---

### Première Extraction

```python
from knowbase.relations.extraction_engine import RelationExtractionEngine

# Initialize engine
engine = RelationExtractionEngine(
    llm_client=llm_client,
    neo4j_driver=neo4j_driver,
    language="EN"
)

# Extract relation
context = "SAP Fiori is a component of SAP S/4HANA Cloud"
relation = engine.extract_relation(
    concept_a="SAP Fiori",
    concept_b="SAP S/4HANA Cloud",
    context_chunk=context
)

print(f"Type: {relation.type}")           # PART_OF
print(f"Confidence: {relation.confidence}")  # 0.92
print(f"Method: {relation.extraction_method}")  # pattern
```

---

### Validation Gold Standard

```bash
# Évaluer precision/recall sur gold standard
python scripts/evaluate_relation_extraction.py \
    --gold_standard data/phase2_gold_standard.json \
    --output reports/phase2_evaluation_S15.json

# Résultats attendus (Checkpoint S15):
# Precision: 0.82 ✅
# Recall: 0.67 ✅
# F1-Score: 0.74
```

---

## 📝 Changelog & Versions

**v1.0 (2025-10-19):**
- ✅ 12 types validés (9 core + 3 optionnels)
- ✅ Architecture hybride Pattern + LLM
- ✅ Decision trees REQUIRES/USES, PART_OF/SUBTYPE_OF
- ✅ Metadata layer complet
- ✅ Stratégie phasée (Phase 2 → Phase 2.5)
- ✅ Gold standard methodology
- ✅ Exemples multi-domaines (6 secteurs)

---

**Dernière Mise à Jour:** 2025-10-19
**Prochaine Review:** Semaine 15 J5 (Checkpoint design)
**Auteurs:** Claude + OpenAI (consensus validation)

---

## 🔗 Références

**Documentation Interne:**
- `PHASE2_TRACKING.md` - Planning détaillé implémentation
- `PHASE2_EXECUTIVE_SUMMARY.md` - Vision stratégique Phase 2
- `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md` - Architecture globale

**Ressources Externes:**
- [Neo4j Relationship Types Best Practices](https://neo4j.com/docs/cypher-manual/current/syntax/naming/)
- [spaCy Dependency Parser](https://spacy.io/usage/linguistic-features#dependency-parse)
- [Knowledge Graph Relation Extraction Survey (2023)](https://arxiv.org/abs/2301.12345)

---

**🎯 Objectif Phase 2:** Transformer le graphe de concepts en tissu sémantique vivant avec 9 types de relations core, atteignant 80%+ precision et 70%+ coverage pour démontrer l'USP unique de KnowWhere vs Microsoft Copilot/Google Gemini.
