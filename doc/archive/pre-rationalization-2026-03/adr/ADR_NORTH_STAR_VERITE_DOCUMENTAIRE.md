# ADR: North Star - Vérité Documentaire Contextualisée

**Status:** ✅ VALIDÉ COMME NORTH STAR - Prêt pour implémentation MVP
**Date:** 2026-01-25
**Auteurs:** Fred, Claude
**Contexte:** Clarification stratégique post-implémentation Pipeline V2

---

## 1. Contexte et Problème

### 1.1 Constat d'échec

Après implémentation du Pipeline V2 (Pass 0 → Pass 1 → Pass 2), les imports de documents techniques (SAP Upgrade Guide, RISE Security Guide) produisent des résultats **techniquement corrects mais commercialement inutilisables** :

| Document | Pages | Concepts | Informations | Taux promotion |
|----------|-------|----------|--------------|----------------|
| SAP Upgrade Guide | ~50 | 5 | 20 | 8.5% |
| RISE Security Guide | ~200 | 6 | 62 | 7.1% |

**Problèmes identifiés :**
- Concepts trop génériques ("Security Policies" au lieu de "TLS 1.2", "WAF")
- Taux de promotion trop restrictif pour les faits techniques
- Assertions techniques précises rejetées ("HANA standby mandatory above 6TiB")
- Système "épistémiquement pur" mais **inutilisable**

### 1.2 Diagnostic racine

Le système actuel sait dire :
> "Ce document affirme X"

Mais il ne sait PAS dire :
> "L'information X vaut V selon le document A (contexte Y), mais vaut W selon le document B (contexte Z), et n'est pas documentée dans le document C."

**Sans cette capacité :**
- Impossible de confirmer/infirmer/nuancer une affirmation utilisateur
- Impossible de comparer deux documents
- Impossible de challenger un texte en écriture
- Impossible de vendre le produit

---

## 2. Décision

### 2.1 Principe fondateur : Vérité Documentaire Contextualisée

OSMOSE adopte le paradigme de **Vérité Documentaire Contextualisée** :

> Une **Information** est une assertion explicite, extraite d'un document source,
> qui est vraie **dans le contexte** de ce document, sans prétention à l'universalité.

**Ce que cela signifie :**
- Tout fait technique **explicitement affirmé** dans un document est une vérité exploitable
- Cette vérité est **toujours contextualisée** (document, version, édition, région, date)
- Les contradictions entre documents sont **exposées, jamais résolues arbitrairement**
- Le système ne tranche pas, il **informe**

### 2.2 Exemples de faits techniques à promouvoir

Ces assertions, actuellement rejetées, DOIVENT devenir des Informations :

| Assertion | Type | Pourquoi c'est défendable |
|-----------|------|---------------------------|
| "TLS 1.2 is enforced" | PRESCRIPTIVE | Fait technique explicite, vérifiable |
| "WAF is used to secure internet inbound" | DEFINITIONAL | Architecture documentée |
| "HANA standby mandatory above 6TiB" | PRESCRIPTIVE | Règle technique précise |
| "Data must remain in China" | PRESCRIPTIVE | Contrainte réglementaire explicite |
| "Backups run daily" | PRESCRIPTIVE | Politique opérationnelle |
| "99.7% SLA for HANA" | DEFINITIONAL | Engagement chiffré |

### 2.3 Ce qu'OSMOSE n'est PAS (hors périmètre corpus)

- **PAS** une vérité universelle (seulement documentaire)
- **PAS** un arbitre de contradictions **hors corpus** (mais arbitre les contradictions documentées)
- **PAS** une ontologie métier rigide
- **PAS** un système qui "décide" ce qui est vrai **dans le monde réel**
- **PAS** un oracle omniscient (muet hors corpus)

### 2.4 Ce qu'OSMOSE EST

- Un **registre de vérités documentaires contextualisées**
- Un **exposant de tensions** entre documents
- Un **outil de comparaison** factuelle
- Un **assistant de validation** de texte utilisateur

### 2.4.1 Positionnement Épistémique : Knowledge Graph Documentaire

#### Le postulat fondateur

> **Une entreprise sait la connaissance qu'elle place dans sa documentation.**
> Cette connaissance, même imparfaite, contradictoire ou contextualisée, **est sa vérité opérante**.

Les faits documentaires **sont de la connaissance**. Leur ensemble structuré **est un Knowledge Graph**.
Même si ces faits sont contradictoires, contextualisés, temporels, non universels.

- La connaissance n'est pas forcément cohérente
- La connaissance n'est pas forcément "vraie" au sens absolu
- Mais **c'est quand même de la connaissance**

#### Formulation North Star (DÉFINITIVE)

> **OSMOSIS est le Knowledge Graph documentaire de l'entreprise
> et l'arbitre de sa vérité documentaire :
> il capture, structure et expose la connaissance telle qu'elle est exprimée dans le corpus documentaire,
> sans jamais extrapoler au-delà de ce corpus.**

Version opérationnelle :

> **Dans le périmètre du corpus documentaire, OSMOSIS est la source de vérité.
> En dehors de ce périmètre, il n'a pas d'opinion.**

#### OSMOSIS EST un arbitre de vérité (précision cruciale)

**Oui, OSMOSIS arbitre la vérité.** Mais uniquement la **vérité documentaire** :

| Ce qu'OSMOSIS arbitre | Exemple |
|-----------------------|---------|
| Ce qui est **affirmé** | "TLS 1.2 est obligatoire" (doc A) → **vrai dans le corpus** |
| Ce qui est **contredit** | Doc A dit X, Doc B dit Y → **la contradiction est vraie** |
| Ce qui est **absent** | Aucun doc ne parle de Z → **l'absence est vraie** |

| Ce qu'OSMOSIS n'arbitre PAS | Pourquoi |
|-----------------------------|----------|
| Vérité universelle | Hors périmètre |
| Vérité scientifique | Hors périmètre |
| Vérité du "monde réel" | Hors périmètre |
| "Bon sens métier" non documenté | Hors périmètre |

**Ce n'est pas une faiblesse. C'est exactement ce qui rend le système robuste et vendable.**

#### Invariant Non-Négociable : Périmètre Corpus

> **Il ne faut JAMAIS essayer d'étendre le champ d'application d'OSMOSIS en dehors du corpus documentaire.**

Cet invariant entraîne directement :
- ❌ Interdiction de toute inférence externe
- ❌ Interdiction de "bon sens métier" non documenté
- ❌ Interdiction de résolution automatique de conflits hors documents
- ✅ Obligation de justifier **toute vérité par des documents**

> **OSMOSIS est un arbitre souverain, mais d'un territoire strictement borné.**

#### Ce qu'OSMOSIS EST (précisément)

OSMOSIS est un **Knowledge Graph documentaire, attributif, arbitral dans son périmètre** :

| Caractéristique | Signification |
|-----------------|---------------|
| **Documentaire** | Toute connaissance est attribuée à un document |
| **Attributif** | La vérité est toujours "selon document X" |
| **Arbitral (borné)** | Arbitre souverain de la vérité documentaire, muet au-delà |

#### Ce qu'OSMOSIS N'EST PAS

| Type de système | Pourquoi non |
|-----------------|--------------|
| KG ontologique encyclopédique | Pas de prétention universelle |
| KG inféré / déductif | Pas de raisonnement au-delà du texte |
| Système de "vérités du monde" | Vérité = documentaire uniquement |
| Oracle omniscient | Muet hors corpus |

#### Le Fact Registry comme cœur structurel

La notion de *Fact Registry* précise que :
- Le **grain primaire** n'est pas le concept mais l'énoncé factuel attribué
- Le graphe est **construit bottom-up**, pas top-down
- Le cœur de la valeur produit est dans : **ClaimKey + Value + Context + Contradictions**

> **OSMOSIS est un Knowledge Graph documentaire
> dont le cœur est un registre de faits documentaires interrogeables par question.**

**Conséquences architecturales :**
```
KG classique : Concept → Informations → Recherche par concept
OSMOSIS     : ClaimKey → Informations → Recherche par question factuelle
             (les Concepts organisent et naviguent, ils ne décident pas)
```

**Pourquoi cette architecture :**
- Sans ClaimKey : Usage B (challenge) infaisable
- Sans ClaimKey : Usage A devient un RAG déguisé
- Sans ClaimKey : Usage C devient narratif mais non défendable

### 2.5 Rôle du LLM : Extracteur, pas Arbitre (AMENDEMENT 4)

> **Principe fondamental :** Le LLM est un **extracteur evidence-locked**, jamais un arbitre.

**Obligations du LLM :**
1. **Citation exacte obligatoire** : Toute Information doit inclure le verbatim du texte source
2. **Span obligatoire** : Position exacte dans le document (page, paragraphe, ligne)
3. **Pas d'interprétation** : Le LLM extrait ce qui est écrit, pas ce qu'il "comprend"
4. **Pas de synthèse cross-source** : Une Information = un document source

**Ce que le LLM NE FAIT PAS :**
- ❌ Décider si une assertion est "vraie"
- ❌ Résoudre des contradictions entre documents
- ❌ Inférer des informations non explicites
- ❌ Créer des concepts sans informations à rattacher

---

## 3. Modèle cible : Information Documentaire

### 3.0 Principe Information-First avec Addressability (AMENDEMENT 1 RÉVISÉ)

> **L'Information est l'entité primaire. Le Concept est optionnel. Mais l'adressabilité est OBLIGATOIRE.**

#### 3.0.1 Invariant "Addressability-First"

> **Toute Information PROMOTED doit être attachée à au moins un pivot de navigation.**

**Pivots possibles (au choix, cumulables) :**
1. **Concept** — regroupement sémantique (optionnel)
2. **Theme** — axe de lecture du document (quasi-obligatoire)
3. **ClaimKey** — question factuelle canonique (obligatoire pour les facts)
4. **SectionPath / DocItem** — preuve de localisation (toujours présent)
5. **Facet/Tag** — étiquette légère ("security.encryption", "sla.availability")

**Règle cardinale :**
```
concept_id: null  → OK
MAIS theme_id + claimkey_id + facets TOUS null → INTERDIT
```

#### 3.0.2 Trois états de promotion (pas deux)

| État | Description | Cible |
|------|-------------|-------|
| **PROMOTED_LINKED** | Info promue + rattachée à ≥1 pivot navigable | **≥ 95%** |
| **PROMOTED_UNLINKED** | Info promue mais orpheline (alerte) | **< 5%** |
| **REJECTED** | Meta, bruit, illustration, disclaimer | Variable |

**Comportement système :**
- `PROMOTED_UNLINKED` déclenche un log d'alerte
- Si `%UNLINKED > 5%` → problème de routing à diagnostiquer
- `UNLINKED` reste dans AssertionLog + Qdrant, mais pas dans le graph navigable

#### 3.0.3 Pourquoi "orphelin total" est dangereux

| Risque | Conséquence |
|--------|-------------|
| **Non-traversabilité** | Impossible de naviguer, composer, expliquer |
| **Réplication Qdrant** | Info graph = duplicat inutile de Qdrant |
| **Perte compare/challenge** | Pas de pivot = pas d'alignement cross-doc |

#### 3.0.4 Ce qui change vs V1

```
AVANT (V1) : Assertion → doit matcher Concept → sinon REJETÉE
APRÈS (V2) : Assertion → Information créée → doit avoir AU MOINS UN pivot
             (Theme ou ClaimKey ou Concept ou Facet)
```

**Bénéfices :**
- Zéro perte d'information technique (pas de rejet pour no_concept_match)
- Traversabilité garantie (toujours un chemin de navigation)
- ClaimKey comme pivot principal pour comparaison cross-doc
- Concepts émergent naturellement, mais pas obligatoires

### 3.1 Structure d'une Information (AMENDEMENT 5 - Value Contract)

```yaml
Information:
  id: "info_xxx"

  # Contenu
  text: "TLS 1.2 is enforced for all connections"
  exact_quote: "TLS 1.2 is enforced for all connections"  # OBLIGATOIRE
  type: PRESCRIPTIVE | DEFINITIONAL | CAUSAL | COMPARATIVE
  rhetorical_role: fact | example | analogy | definition | instruction | claim | caution  # AMENDEMENT 6

  # Value extraction (AMENDEMENT 5 - pour compare/challenge)
  value:
    kind: number | percent | boolean | enum | string | range | set
    raw: "TLS 1.2"           # Valeur brute extraite
    normalized: "1.2"        # Valeur normalisée pour comparaison
    unit: "version"          # Unité (%, hours, TiB, version, etc.)
    operator: "="            # =, >=, <=, in, approx
    confidence: high | medium | low  # Parsabilité, pas "truth"

  # Source
  source:
    document_id: "rise_security_guide_2024"
    document_title: "RISE with SAP Cloud ERP Private - Security Guide"
    document_version: "2024.01"
    page: 45
    paragraph: 3
    line: 12
    anchor_docitem_ids: ["docitem_123", "docitem_124"]

  # Contexte documentaire (hérité du DocContextFrame - AMENDEMENT 5b)
  context:
    product: "SAP S/4HANA Cloud, Private Edition"
    edition: "Private"
    region: ["Global"]
    version: "2023+"
    deployment: "Cloud"
    markers_strong: ["RISE with SAP", "Private Edition"]
    markers_weak: ["Cloud ERP"]
    inheritance_mode: inherited | asserted | mixed | unknown  # NOUVEAU

  # Métadonnées extraction
  confidence: 0.9
  language: "en"
  extracted_at: "2026-01-25T10:00:00Z"

  # Déduplication (AMENDEMENT 5c)
  fingerprint: "hash(claimkey + value.normalized + context_key + span_bucket)"

  # Liens sémantiques
  concept_id: "concept_tls_encryption"  # Peut être null
  claimkey_id: "tls_min_version"        # Quasi-obligatoire pour facts
  theme_id: "theme_security"            # Quasi-obligatoire
  facets: ["security.encryption"]       # Tags légers optionnels
  related_informations: []

  # Contradictions connues (rempli par Pass 3)
  contradictions:
    - document_id: "s4hana_public_guide_2022"
      information_id: "info_yyy"
      nature: value_conflict | scope_conflict | temporal_conflict | exception_conflict | definition_conflict | missing_claim
      tension_level: hard | soft | unknown
      description: "Public Edition uses TLS 1.1 minimum"
```

### 3.1.1 Value Contract (AMENDEMENT 5 - Comparabilité)

> Sans extraction de valeurs normalisées, les contradictions ne sont détectables que textuellement.

**Champs obligatoires pour facts quantifiés :**

| Champ | Description | Exemple |
|-------|-------------|---------|
| `value.kind` | Type de valeur | `percent`, `number`, `version` |
| `value.raw` | Valeur brute du texte | "99.7%", "TLS 1.2", "6 TiB" |
| `value.normalized` | Valeur normalisée | `0.997`, `1.2`, `6` |
| `value.unit` | Unité | `%`, `version`, `TiB` |
| `value.operator` | Opérateur | `=`, `>=`, `<=`, `approx` |

**Exemples de normalisation :**
```
"99.7% SLA"           → {kind: percent, raw: "99.7%", normalized: 0.997, unit: "%"}
"TLS 1.2 minimum"     → {kind: version, raw: "1.2", normalized: 1.2, unit: "version", operator: ">="}
"above 6 TiB"         → {kind: number, raw: "6 TiB", normalized: 6, unit: "TiB", operator: ">"}
"daily backups"       → {kind: enum, raw: "daily", normalized: "daily", unit: "frequency"}
```

#### ⚠️ RISQUE : Value.normalized est un champ miné

**Problème identifié :** La normalisation peut créer de faux conflits ou en rater.

Exemples ambigus :
- "daily" vs "once per business day" vs "every 24 hours" vs "at least once a day"
- "minimum TLS 1.2" vs "TLS 1.2 or higher" vs "TLS 1.2+"

**Solution : Statut de comparabilité explicite**

```yaml
value:
  comparable: strict | loose | non_comparable
```

| Statut | Définition | Exemple |
|--------|------------|---------|
| `strict` | Valeurs directement comparables | "99.7%" vs "99.9%" |
| `loose` | Comparables avec interprétation | "daily" vs "24h" |
| `non_comparable` | Incomparables sans contexte | "fast" vs "quick" |

**Règle :** Contradiction `hard` uniquement si `comparable: strict`.

### 3.1.2 Context Inheritance Rules (AMENDEMENT 5b)

> Règles déterministes et conservatrices pour l'héritage de contexte.

**Règles d'héritage :**

| Source | Héritage | Condition |
|--------|----------|-----------|
| `markers_strong` (doc-level) | **Automatique** | Toujours hérité par défaut |
| `markers_weak` (doc-level) | **Conditionnel** | Seulement si section dans même scope |
| Assertion locale | **Prioritaire** | Override le contexte hérité |

**Modes d'héritage :**
- `inherited` : Contexte vient du DocContextFrame
- `asserted` : Contexte explicite dans l'assertion elle-même
- `mixed` : Combinaison (hérité + override local)
- `unknown` : Contexte non déterminable

**Exemple :**
```yaml
# Document-level
DocContextFrame:
  markers_strong: ["RISE with SAP", "Private Edition"]
  markers_weak: ["2024 version"]

# Information hérite automatiquement markers_strong
Information:
  context:
    edition: "Private"              # Hérité de markers_strong
    version: "2024"                 # Hérité de markers_weak (même chapitre)
    region: ["China"]               # Asserted localement (override)
    inheritance_mode: "mixed"
```

### 3.1.3 Deduplication Policy (AMENDEMENT 5c)

> Info-first génère des répétitions (headers, tables, redites). Il faut dédupliquer.

**Fingerprint = hash de :**
```
fingerprint = hash(
  claimkey_id,           # Question factuelle
  value.normalized,      # Valeur normalisée
  context_key,           # Edition + version + region
  span_bucket            # Page (pas ligne exacte, pour tolérer reformulations)
)
```

**Règle de déduplication :**
- Si `fingerprint` identique → **Merge evidence** (plusieurs anchors), pas 2 nodes
- Bénéfice : Multi-evidence augmente la défendabilité

**Exemple :**
```yaml
# Même fait répété 3 fois dans le doc
Information:
  text: "TLS 1.2 is enforced"
  fingerprint: "abc123"
  source:
    anchor_docitem_ids: ["docitem_10", "docitem_45", "docitem_89"]  # 3 anchors
```

### 3.1.4 Rhetorical Role (AMENDEMENT 6)

> Séparer faits vs exemples/illustrations sans les rejeter.

**Valeurs possibles :**

| Role | Description | Génère ClaimKey? |
|------|-------------|------------------|
| `fact` | Assertion factuelle | ✅ Oui |
| `definition` | Définition de terme | ✅ Oui |
| `instruction` | Procédure, how-to | ✅ Oui |
| `claim` | Affirmation non vérifiée | ⚠️ Conditionnel |
| `example` | Illustration, cas concret | ❌ Non |
| `analogy` | Comparaison explicative | ❌ Non |
| `caution` | Avertissement, disclaimer | ⚠️ Conditionnel |

**Règle :** `example` et `analogy` sont stockés mais **ne génèrent pas de ClaimKey comparatif**.

### 3.2 Concept-Frugal : LLM propose, Système dispose (AMENDEMENT 2)

> **Principe :** Les Concepts sont une **compression optionnelle**, pas un dumping obligatoire.

**DANGER identifié (V1 avec stéroïdes LLM) :**
```
❌ LLM génère 50 concepts "parce qu'on lui a demandé"
❌ Concepts vides ou quasi-vides (1-2 informations)
❌ Concepts-valeurs ("TLS 1.2" au lieu de "Transport Layer Security")
❌ Sur-conceptification = bruit inutilisable
```

**SOLUTION : Gates de validation Concept**

Un Concept proposé par le LLM n'est CRÉÉ que s'il passe TOUS les gates :

| Gate | Critère | Exemple rejet |
|------|---------|---------------|
| **G1: Cardinalité** | ≥ 3 Informations rattachées | "WAF" avec 1 seule info |
| **G2: Structurabilité** | Humain peut ranger dessous | "Misc Security" trop vague |
| **G3: Non-valeur** | Pas une valeur concrète | "TLS 1.2" est une valeur, pas un concept |
| **G4: Non-redondant** | Pas de quasi-synonyme existant | "SSL/TLS" si "TLS" existe |

**Workflow révisé :**
```
1. LLM extrait Informations (primaire, jamais rejetées)
2. LLM PROPOSE des Concepts (suggestions)
3. Système valide avec Gates G1-G4
4. Concepts non validés → Informations restent orphelines (OK!)
5. Pass ultérieure peut re-proposer regroupements
```

**Résultat attendu :**
```
AVANT (V1) : 50 concepts demandés → 50 créés (beaucoup vides/bruit)
APRÈS (V2) : 50 proposés → 8-15 validés (tous substantiels)
```

### 3.3 Hiérarchie révisée (Information-First)

```
Document
└── Subject (1 par document)
    └── Themes (axes de lecture, 5-15)
        └── Informations (assertions sourcées, ILLIMITÉES, entité primaire)
            └── Concepts (compression optionnelle, émergent des Informations)
```

**Changement clé par rapport à V1 :**
- Information est **primaire**, Concept est **dérivé**
- Les Informations existent indépendamment des Concepts
- Les Concepts sont créés **a posteriori** quand suffisamment d'Informations convergent

### 3.4 ClaimKey : Identifiant de Question Factuelle (AMENDEMENT 3 + 5d)

> Un **ClaimKey** est un identifiant stable représentant une question factuelle,
> indépendant du vocabulaire utilisé dans les documents.

**Définition :**
```yaml
ClaimKey:
  id: "claimkey_xxx"

  # Question factuelle canonique
  canonical_question: "Quelle est la version TLS minimum requise ?"

  # Identifiant machine
  key: "tls_min_version"

  # Domaine
  domain: "security.encryption.transport"

  # Informations liées (de différents documents)
  linked_informations:
    - info_id: "info_123"
      document: "RISE Security Guide 2024"
      value:
        raw: "TLS 1.2"
        normalized: 1.2
      context: {edition: "Private"}
    - info_id: "info_456"
      document: "S/4HANA Public Guide 2023"
      value:
        raw: "TLS 1.1"
        normalized: 1.1
      context: {edition: "Public"}

  # Contradictions détectées
  has_contradiction: true
  contradiction_type: "value_conflict"
  tension_level: "hard"
```

**Rôle du ClaimKey :**
1. **Pivot de comparaison** : Permet de comparer la même question entre documents
2. **Détection de contradictions** : Différentes valeurs normalisées = tension
3. **Indépendant du wording** : "TLS 1.2 is enforced" et "minimum TLS version is 1.2" → même ClaimKey
4. **Pas de création LLM** : Le système infère les ClaimKeys (voir §3.4.1)

### 3.4.1 ClaimKey Inference en 2 Niveaux (AMENDEMENT 5d)

> "Système infère" n'est pas assez précis. Voici la mécanique concrète.

#### Niveau A : Déterministe (cheap, patterns)

**Extraction automatique basée sur :**
- Patterns lexicaux : "SLA", "retention", "TLS", "encryption", "backup", "version"
- Unités détectées : %, TiB, hours, days, version
- Structures syntaxiques : "X is Y", "minimum X", "X must be Y"

**Exemples :**
```
"TLS 1.2 is enforced" → claimkey_candidate: tls_enforcement
"99.7% SLA"           → claimkey_candidate: sla_availability
"backups run daily"   → claimkey_candidate: backup_frequency
"data must remain in China" → claimkey_candidate: data_residency_china
```

#### Niveau B : LLM Assisté (non créateur)

**Workflow :**
1. LLM propose **mapping** : `Information → existing ClaimKey candidate set`
2. Si match avec candidat existant → Lier
3. Si aucun candidat → `UNASSIGNED_CLAIMKEY` + log
4. Création nouveau ClaimKey = **décision système** (pas LLM)

**Règle de création :**
```
Nouveau ClaimKey créé SI ET SEULEMENT SI:
- ≥3 Informations similaires cross-doc
- Pattern lexical identifié (Niveau A)
- Pas de quasi-synonyme existant
```

**Garde-fou anti-sprawl :**
```yaml
claimkey_creation:
  min_informations_cross_doc: 3
  require_pattern_match: true
  require_no_synonym: true
  human_review_if_uncertain: true
```

### 3.4.2 Statut ClaimKey (anti-sprawl)

#### ⚠️ RISQUE : Explosion silencieuse des ClaimKeys

**Scénario probable :**
- Corpus SAP = extrêmement riche (SLA par composant, seuils, variantes, exceptions)
- Sans vigilance : 300-500 ClaimKeys "légitimes"
- Dont 60% n'ont **qu'un seul document** → non comparables → peu utiles produit

**Solution : Statut de ClaimKey explicite**

```yaml
ClaimKey:
  status: emergent | comparable | deprecated | orphan
```

| Statut | Définition | Action |
|--------|------------|--------|
| `emergent` | Nouveau, < 3 infos ou 1 seul doc | Monitoring, pas exposé en UI |
| `comparable` | ≥ 2 docs avec valeurs comparables | **Pivot produit principal** |
| `deprecated` | Remplacé par autre ClaimKey (fusion) | Redirection |
| `orphan` | Aucune info récente, obsolète | Archive |

**Règle produit :**
- Seuls les ClaimKeys `comparable` sont exposés en UI par défaut
- `emergent` visible uniquement en mode "exploration"
- KPI : `% ClaimKeys comparable` > 50% (sinon corpus trop hétérogène)

### 3.4.3 Exemples de ClaimKeys

| ClaimKey | Question canonique | Domain |
|----------|-------------------|--------|
| `sla_hana_availability` | "Quel est le SLA de disponibilité HANA ?" | `sla.availability` |
| `data_residency_china` | "Les données doivent-elles rester en Chine ?" | `compliance.residency` |
| `backup_frequency` | "Quelle est la fréquence des backups ?" | `operations.backup` |
| `hana_standby_threshold` | "À partir de quelle taille HANA standby est-il requis ?" | `infrastructure.hana` |
| `tls_min_version` | "Quelle est la version TLS minimum ?" | `security.encryption` |
| `patch_responsibility` | "Qui est responsable des patches ?" | `operations.patching` |

---

## 4. Révision de la Promotion Policy

### 4.1 Critères actuels (trop restrictifs)

```python
# Actuel - rejette trop de faits techniques
ALWAYS_PROMOTE = ["must", "shall", "required", "is defined as"]
CONDITIONAL = ["should", "recommended", "can be"]
NEVER = ["describes", "shows", "presents"]  # ← Problème ici
```

### 4.2 Critères révisés (proposés)

```python
# Nouveau - accepte les faits techniques explicites
ALWAYS_PROMOTE = [
    # Obligations
    "must", "shall", "required", "mandatory", "enforced",
    # Définitions techniques
    "is", "are", "uses", "provides", "supports",
    # Capacités
    "enables", "allows", "can be configured",
    # Valeurs explicites
    "SLA", "%", "TiB", "hours", "daily", "version"
]

CONDITIONAL = [
    "should", "recommended", "optional", "by default"
]

REJECT = [
    # Méta-descriptions uniquement
    "this page describes", "this section shows",
    "see also", "refer to", "for more information"
]
```

### 4.3 Nouveau critère : Factualité Technique

Une assertion est promotable si elle répond à **AU MOINS UN** de ces critères :

1. **Prescriptive** : Exprime une obligation ou interdiction
2. **Définitionnelle** : Définit ce qu'est ou fait quelque chose
3. **Quantifiée** : Contient une valeur chiffrée (SLA, %, taille, durée)
4. **Technique explicite** : Nomme une technologie, protocole, ou configuration
5. **Contextuelle** : Spécifie une condition d'applicabilité (région, version, édition)

---

## 5. Implications sur les Passes (RÉVISÉ)

### 5.1 Pass 1.3 - Extraction Informations (PRIMAIRE)

**Changement majeur :** Information-first, jamais de rejet

```yaml
# Nouveau comportement
instruction: |
  Extrais TOUTES les assertions factuelles explicites du chunk.

  OBLIGATOIRE pour chaque Information:
  - exact_quote: verbatim du texte source (OBLIGATOIRE)
  - span: {page, paragraph, line} (OBLIGATOIRE)
  - type: PRESCRIPTIVE | DEFINITIONAL | CAUSAL | COMPARATIVE

  NE PAS rejeter une assertion parce qu'elle ne "matche" pas un concept.
  concept_id peut être null - c'est OK.

# Critères de promotion élargis
accept_technical_facts: true
accept_quantified_statements: true
accept_technology_mentions: true
reject_only_meta_descriptions: true
never_reject_for_no_concept: true  # ← NOUVEAU
```

### 5.2 Pass 1.2 - Proposition Concepts (SECONDAIRE)

**Changement :** Le LLM PROPOSE, le système VALIDE

```yaml
# Nouveau comportement
instruction: |
  Propose des Concepts pour regrouper les Informations extraites.

  Un Concept est une CATÉGORIE, pas une VALEUR.
  BONS: "Transport Layer Security", "Data Residency", "SLA Guarantees"
  MAUVAIS: "TLS 1.2", "China", "99.7%"

  Ces propositions seront VALIDÉES par des gates système.
  Ne pas forcer des concepts - mieux vaut moins mais pertinents.

# Gates de validation (côté système, pas LLM)
gates:
  min_informations: 3        # G1: Au moins 3 infos
  must_be_structurable: true # G2: Humain peut ranger dessous
  must_not_be_value: true    # G3: Pas une valeur concrète
  must_not_be_redundant: true # G4: Pas de quasi-synonyme
```

### 5.3 Pass 2+ - Inférence ClaimKeys

**Nouveau :** Système infère les ClaimKeys (pas le LLM)

```yaml
# Comportement système
instruction: |
  Analyser les Informations pour identifier les questions factuelles sous-jacentes.
  Regrouper les Informations qui répondent à la même question.

  Exemple:
  - Info A: "TLS 1.2 is enforced" (doc 1)
  - Info B: "Minimum TLS version: 1.1" (doc 2)
  → ClaimKey: tls_min_version
  → Contradiction détectée: 1.2 vs 1.1

# Pas de création LLM
llm_creates_claimkeys: false
system_infers_claimkeys: true
```

### 5.4 Pass 3 - Exposition Contradictions (AMENDEMENT 5e)

**Rôle :** Exposer, jamais arbitrer. Avec vocabulaire stable.

```yaml
# Comportement
detect_contradictions: true
expose_version_differences: true
expose_edition_differences: true
expose_region_differences: true
never_arbitrate: true  # Exposer, jamais trancher
link_via_claimkeys: true  # Utiliser ClaimKeys comme pivot
use_value_normalized: true  # Comparer valeurs normalisées
```

#### 5.4.1 Typologie des Contradictions (enum stable)

| Nature | Description | Exemple |
|--------|-------------|---------|
| `value_conflict` | Valeurs différentes pour même question | TLS 1.2 vs TLS 1.1 |
| `scope_conflict` | Applicabilité différente | Private vs Public Edition |
| `temporal_conflict` | Versions/dates différentes | 2022 vs 2024 |
| `exception_conflict` | Règle générale vs exception | "always" vs "except when..." |
| `definition_conflict` | Termes définis différemment | "backup" = daily vs weekly |
| `missing_claim` | Document ne se prononce pas | Doc B muet sur TLS |

#### 5.4.2 Tension Level

> Pas tout appeler "contradiction" - graduer la sévérité.

| Level | Définition | Action UI |
|-------|------------|-----------|
| `hard` | value_conflict dans même scope | ⚠️ Alerte rouge |
| `soft` | Différence de scope explicable | 🔶 Alerte orange |
| `unknown` | Contextes incomparables | ℹ️ Info seulement |

**Règles de classification :**
```yaml
tension_level:
  hard:
    - value_conflict AND same_edition AND same_version
    - definition_conflict
  soft:
    - value_conflict AND different_edition
    - scope_conflict
    - temporal_conflict (>2 ans d'écart)
  unknown:
    - missing_claim
    - exception_conflict (besoin analyse humaine)
```

#### 5.4.3 Structure Contradiction

```yaml
Contradiction:
  id: "contra_xxx"
  claimkey_id: "tls_min_version"

  # Informations en conflit
  info_a:
    id: "info_123"
    document: "RISE Security Guide 2024"
    value: {raw: "TLS 1.2", normalized: 1.2}
    context: {edition: "Private", version: "2024"}

  info_b:
    id: "info_456"
    document: "S/4HANA Public Guide 2023"
    value: {raw: "TLS 1.1", normalized: 1.1}
    context: {edition: "Public", version: "2023"}

  # Classification
  nature: "value_conflict"
  tension_level: "soft"  # Car different_edition
  explanation: "Private Edition requires TLS 1.2, Public allows TLS 1.1"

  # Métadonnées
  detected_at: "2026-01-25T10:00:00Z"
  detection_method: "value_normalized_comparison"
```

---

## 6. Cas d'usage cibles

### 6.1 Validation de texte utilisateur

**Utilisateur écrit :**
> "Notre système utilise TLS 1.3 pour toutes les connexions."

**OSMOSE répond :**
> ⚠️ Contradiction détectée :
> - Selon "RISE Security Guide 2024" (p.45) : "TLS 1.2 is enforced"
> - Votre affirmation mentionne TLS 1.3
>
> Action suggérée : Vérifier la version/édition applicable

### 6.2 Comparaison de documents

**Utilisateur demande :**
> "Quelles sont les différences de sécurité entre Private et Public Edition ?"

**OSMOSE répond :**
> | Aspect | Private Edition | Public Edition |
> |--------|-----------------|----------------|
> | TLS minimum | 1.2 enforced | 1.1 minimum |
> | WAF | Customer managed | SAP managed |
> | Data residency | Configurable | Standard regions |
>
> Sources : RISE Security Guide 2024, S/4HANA Public Guide 2023

### 6.3 Analyse d'écart réglementaire

**Utilisateur demande :**
> "Sommes-nous conformes aux exigences Chine ?"

**OSMOSE répond :**
> Selon "RISE Security Guide 2024" (p.78-82), les exigences Chine sont :
> - ✅ "Data collected in China must be stored in China"
> - ✅ "Data transfer outside China requires CAC assessment"
> - ⚠️ "Telecom license required" - Non documenté dans votre contrat

---

## 7. Métriques de succès révisées

### 7.1 KPIs quantitatifs (RÉVISÉ - Addressability-First)

| Métrique | Cible V1 | Cible V2 (révisée) |
|----------|----------|-------------------|
| **Informations** par document (100 pages) | 20-50 | **100-300** (primaire) |
| **PROMOTED_LINKED** (avec pivot) | N/A | **≥ 95%** |
| **PROMOTED_UNLINKED** (orphelins) | 0% (rejetées) | **< 5%** (alerte si dépassé) |
| **Concepts validés** par document | 5-15 | **5-15** (frugal, ≥3 infos chacun) |
| Concepts proposés vs validés | N/A | **Ratio < 50%** (filtrage actif) |
| Infos sans Concept mais avec ClaimKey | N/A | **OK, normal** |
| Taux de promotion assertions | 5-10% | **15-30%** |
| ClaimKeys inférés par corpus | N/A | **20-50** |
| Theme coverage (infos rattachées) | N/A | **100%** |
| Contradictions détectées (cross-doc) | N/A | **Toutes exposées** |

**Garde-fous critiques :**
- Si `%PROMOTED_UNLINKED > 5%` → bug de routing à diagnostiquer
- Si `theme coverage < 100%` → problème d'extraction Theme
- Si `avg claimkeys/100 pages` trop bas → prompt ClaimKey à revoir

### 7.2 KPIs de Comparabilité (AMENDEMENT 7)

> Ces KPIs mesurent si le système peut réellement faire "doc A vs doc B".

| Métrique | Cible | Description |
|----------|-------|-------------|
| **% Infos avec value.normalized** | **> 60%** | Sur docs techniques chiffrés |
| **% Infos rattachées à ClaimKey** | **> 80%** | Pour les facts (rhetorical_role=fact) |
| **avg docs per ClaimKey** | **> 1.3** | Sur corpus multi-doc (sinon pas de cross-doc) |
| **% ClaimKeys avec ≥2 docs** | **> 50%** | Potentiel de comparaison |
| **Contradictions hard détectées** | **Toutes** | Via value_normalized comparison |
| **Fingerprint collision rate** | **< 10%** | Mesure de déduplication |

**Interprétation :**
- `avg docs per ClaimKey < 1.3` → corpus trop hétérogène ou ClaimKeys trop spécifiques
- `% value.normalized < 60%` → extraction de valeurs à améliorer
- `% ClaimKey coverage < 80%` → routing ClaimKey défaillant

### 7.3 KPIs qualitatifs

- [ ] Un utilisateur peut valider un texte contre la base documentaire
- [ ] Un utilisateur peut comparer deux documents **via ClaimKeys**
- [ ] Les contradictions sont visibles et explicables (avec tension_level)
- [ ] Les faits techniques sont exploitables (pas seulement "le document parle de sécurité")
- [ ] **Zéro rejet** pour "no_concept_match"
- [ ] **Zéro orphelin total** (toujours au moins Theme ou ClaimKey)
- [ ] Chaque Information a un `exact_quote` et un `span`
- [ ] **NOUVEAU:** Chaque fact quantifié a `value.normalized`
- [ ] **NOUVEAU:** Exemples/analogies stockés mais non comparatifs

---

## 8. Plan d'action et Périmètre MVP

> **L'ADR est une boussole, pas un backlog.**
> Implémenter 100% de l'ADR d'un coup = risque de nouvelle itération longue sans produit visible.

### 8.0 Périmètre MVP V1 : Usage B (Challenge de Texte)

**Objectif unique : rendre l'Usage B utilisable en 4-6 semaines.**

#### ✅ À implémenter IMMÉDIATEMENT (MVP V1)

| Composant | Détail |
|-----------|--------|
| **Pass 1.3 Information-First** | `exact_quote` + `span` obligatoires |
| **ClaimKey inference minimale** | Patterns lexicaux (Niveau A) uniquement |
| **Value extraction limitée** | `number`, `percent`, `enum`, `version` |
| **Context inheritance** | `markers_strong` / `markers_weak` |
| **Contradiction detection** | `value_conflict` + `missing_claim` seulement |
| **API challenge(text)** | Endpoint pour challenger un texte utilisateur |

#### ❌ EXCLU de MVP V1 (itérations ultérieures)

| Composant | Raison |
|-----------|--------|
| Composition complète Usage A | Trop large pour MVP |
| UI riche d'exploration Concept-driven | Usage C secondaire |
| Tous les `tension_type` avancés | `value_conflict` suffit pour MVP |
| Normalisation cross-langue sophistiquée | Complexité excessive |
| Fusion automatique de ClaimKeys | Risque de sprawl mal géré |
| Concepts validés par Gates G1-G4 | Informations suffisent pour Usage B |

**Ce n'est pas un recul.** C'est ce qui garantit un système **utilisable, démontrable et fidèle à l'ADR** rapidement.

---

### Phase 1 : Information-First (MVP V1 - immédiat)
- [ ] Modifier Pass 1.3 pour ne JAMAIS rejeter pour "no_concept_match"
- [ ] Ajouter `exact_quote` et `span` obligatoires dans le prompt
- [ ] Ajouter `value` extraction (number/percent/enum/version)
- [ ] Ajouter `rhetorical_role` (fact vs example)
- [ ] Permettre `concept_id: null` dans le modèle Information
- [ ] Tester : toutes les assertions techniques sont capturées

### Phase 2 : ClaimKey Minimal (MVP V1 - immédiat)
- [ ] Définir modèle ClaimKey dans Neo4j (structure minimale)
- [ ] Implémenter ClaimKey inference Niveau A (patterns lexicaux)
- [ ] Ajouter `ClaimKey.status` (emergent/comparable)
- [ ] Lier Informations aux ClaimKeys
- [ ] API `challenge(text)` → retourne contradictions

### Phase 3 : Contradiction Detection (MVP V1 - immédiat)
- [ ] Détecter `value_conflict` via `value.normalized`
- [ ] Détecter `missing_claim` (doc ne se prononce pas)
- [ ] Exposer contradictions avec contexte basique
- [ ] API pour lister tensions d'un ClaimKey

---

### Phase 4 : Concept-Frugal avec Gates (POST-MVP)
- [ ] Implémenter les 4 Gates (G1-G4) côté système
- [ ] Modifier Pass 1.2 pour PROPOSER (pas créer directement)
- [ ] Workflow : LLM propose → System valide → Création si OK

### Phase 5 : Usage A Composition (POST-MVP)
- [ ] Composition ClaimKey-driven
- [ ] Affichage couverture ClaimKey
- [ ] Zones non couvertes explicites

### Phase 6 : Usage C Exploration (POST-MVP)
- [ ] UI Concept-driven avec densité ClaimKeys
- [ ] Refus composition si ClaimKeys insuffisants

---

## 8bis. Invariants Techniques (garde-fous implémentation)

> Ces invariants DOIVENT être respectés par toute implémentation.

### 8bis.1 Invariant de Comparabilité

> **Une Information n'est "utile produit" que si elle est rattachée à un ClaimKey comparable ou potentiellement comparable.**

**Conséquence :**
- Information sans ClaimKey = stockée mais non exploitable pour compare/challenge
- Information avec ClaimKey `emergent` = potentiellement utile (monitoring)
- Information avec ClaimKey `comparable` = **valeur produit**

### 8bis.2 Invariant d'Asymétrie Concept/ClaimKey

> **Tous les Concepts ne sont pas exposés en UI. Seuls ceux qui structurent des ClaimKeys comparables le sont.**

**Conséquence :**
- Concept "Data Residency" avec 0 ClaimKey comparable → **pas en UI principale**
- Concept "SLA Guarantees" avec 5 ClaimKeys comparables → **exposé en UI**
- Les Concepts sont un outil de navigation, **pas un outil de décision**

**⚠️ RISQUE identifié :** Concepts "frugaux" mais inutiles produit
- Un concept validé par G1-G4 peut rester **peu actionnable**
- Exemple : "Security Policies" (trop large pour comparer)
- Solution : densité de ClaimKeys comparables par Concept comme critère d'exposition

### 8bis.3 Invariant de Refus Assumé

> **Si une Information ne peut être ni comparée, ni contextualisée correctement, elle est visible mais non exploitable (et c'est acceptable).**

**Conséquence :**
- Pas de forçage de comparaison artificielle
- Honnêteté sur les limites : "cette info existe mais n'est pas comparable"
- Préférer l'absence de réponse à une réponse fausse

---

## 8ter. Compatibilité Usages A/B/C

### Usage A : Composition Assistée

**Statut : ✅ Aligné, attention au scope**

L'ADR permet Usage A **si et seulement si** :
- La composition est **ClaimKey-driven**, pas Concept-driven
- Les zones non couvertes sont **explicitement listées**

**Risque :**
- Produire un "document bien écrit" mais pas "défendable"
- Solution : afficher la couverture ClaimKey dans l'UI de composition

### Usage B : Challenge de Texte

**Statut : ✅ PARFAITEMENT aligné (MVP naturel)**

C'est le premier usage réellement rendu possible :
- ClaimKey = challenge phrase par phrase
- Value.normalized = détection de tension
- Context = nuance immédiate
- `missing_claim` = réponse honnête

**Usage B est le MVP naturel de cette architecture.**

### Usage C : Exploration Guidée

**Statut : ⚠️ Compatible mais fragile**

**Risque spécifique :**
- Navigation Concept → donne une **illusion de complétude**
- Alors que les ClaimKeys sous-jacents sont partiels

**Solutions requises :**
- Afficher la **densité de faits** par concept
- Refuser la composition si trop peu de ClaimKeys comparables
- Sinon, Usage C redevient un générateur narratif déguisé

---

## 9. Questions ouvertes (réduites)

1. **Granularité optimale des concepts ?**
   - Trop fin = bruit, trop gros = inutilisable
   - Proposition : niveau "technologie/protocole/politique"
   - ✅ PARTIELLEMENT RÉSOLU par Gates G1-G4 (Amendement 2)

2. **Gestion des quasi-synonymes ?**
   - "TLS 1.2" vs "Transport Layer Security 1.2"
   - Pass 3 doit-il fusionner ou garder distinct ?
   - ⏳ À RÉSOUDRE : définir règles de normalisation

3. ~~**Héritage de contexte ?**~~
   - ✅ RÉSOLU par Amendement 5b (Context Inheritance Rules)
   - markers_strong = héritage automatique, markers_weak = conditionnel

4. **Seuil de confiance ?**
   - Actuel : 0.85 pour promouvoir
   - Proposé : 0.7 pour les faits techniques explicites ?
   - ⏳ À TESTER empiriquement

5. **NOUVELLE : Normalisation des unités cross-domain ?**
   - Comment normaliser "daily" vs "24h" vs "1 jour" ?
   - Faut-il un dictionnaire d'équivalences ?

---

## 10. Amendements intégrés (2026-01-25)

Suite aux analyses critiques ChatGPT, **7 amendements** ont été intégrés pour rendre le compare/challenge réellement opérant :

### 10.1 Amendements 1-4 (Fondations)

| # | Amendement | Section | Risque évité |
|---|------------|---------|--------------|
| 1 | **Information-First + Addressability** | §3.0 | Rejet pour "no_concept_match" **ET** orphelins non-navigables |
| 2 | **Concept-Frugal** | §3.2 | Sur-conceptification (50 concepts vides) |
| 3 | **ClaimKey** | §3.4 | Impossibilité de comparer sans sur-conceptifier |
| 4 | **LLM Evidence-Locked** | §2.5 | LLM arbitre au lieu d'extraire |

### 10.2 Amendements 5-7 (Opérationnalisation compare/challenge)

| # | Amendement | Section | Problème résolu |
|---|------------|---------|-----------------|
| 5a | **Value Contract** | §3.1.1 | Contradictions uniquement textuelles (1.2 vs 1.1 non détecté) |
| 5b | **Context Inheritance** | §3.1.2 | Héritage de contexte instable/imprévisible |
| 5c | **Deduplication Policy** | §3.1.3 | Explosion du graphe par répétitions |
| 5d | **ClaimKey Inference 2 niveaux** | §3.4.1 | "System infers" trop vague, ClaimKey sprawl |
| 5e | **Contradiction Taxonomy** | §5.4.1 | Vocabulaire instable, UI/tests flous |
| 6 | **Rhetorical Role** | §3.1.4 | Exemples/analogies polluent ClaimKeys |
| 7 | **Comparability KPIs** | §7.2 | Pas de mesure du potentiel cross-doc |

### 10.3 Révision critique Amendement 1 (itération 2)

L'invariant initial "concept_id:null OK" risquait de créer des milliers d'Informations non-navigables.

**Solution : Invariant "Addressability-First"**
- `concept_id: null` → OK
- MAIS `theme_id + claimkey_id + facets` TOUS null → INTERDIT
- Trois états : PROMOTED_LINKED (≥95%), PROMOTED_UNLINKED (<5%), REJECTED

### 10.4 Règles cardinales finales (7 amendements + risques)

**Amendements 1-7 :**
1. Une Information existe SANS Concept → OK, **si rattachée à Theme ou ClaimKey**
2. Une Information SANS AUCUN pivot → PROMOTED_UNLINKED (alerte, <5%)
3. Un Concept n'existe PAS sans ≥3 Informations → Gate
4. Le LLM PROPOSE, le Système DISPOSE → Validation
5. Citation exacte + Span = OBLIGATOIRE → Traçabilité
6. **Value.normalized OBLIGATOIRE** pour facts quantifiés → Comparabilité
7. **ClaimKey inference en 2 niveaux** (pattern + LLM mapping) → Pas de sprawl
8. **Rhetorical_role** distingue facts vs examples → ClaimKeys non pollués
9. **Fingerprint** pour déduplication → Graphe navigable
10. **Contradiction taxonomy** (nature + tension_level) → Vocabulaire stable

**Garde-fous risques (itération 3) :**
11. **ClaimKey.status** (emergent/comparable/deprecated/orphan) → Anti-sprawl
12. **Value.comparable** (strict/loose/non_comparable) → Faux conflits évités
13. **Pivot assumé** : Fact Registry > Knowledge Graph → Direction claire
14. **Invariant de comparabilité** : Info utile ssi ClaimKey comparable
15. **Invariant d'asymétrie** : Concepts non exposés si pas de ClaimKeys comparables
16. **Invariant de refus** : Préférer absence de réponse à réponse fausse

---

## 11. Références

- ADR Stratified Reading Model (existant)
- ADR Exploitation Layer (existant)
- Conversation ChatGPT 2026-01-25 (clarification stratégique initiale)
- Analyse ChatGPT 2026-01-25 (amendements 1-4 critiques)
- Analyse ChatGPT 2026-01-25 (amendements 5-7 opérationnels)
- Pipeline V2 Implementation (en cours de refonte)

---

*Ce document est notre North Star. Toute implémentation doit s'aligner sur ces principes.*

**Historique des amendements :**
- 2026-01-25 v1 : Draft initial (Fred, Claude)
- 2026-01-25 v2 : Amendements 1-4 (Information-First, Concept-Frugal, ClaimKey, LLM Evidence-Locked)
- 2026-01-25 v3 : Révision Amendement 1 (Addressability-First)
- 2026-01-25 v4 : Amendements 5-7 (Value Contract, Context Inheritance, Dedup, ClaimKey Inference, Contradiction Taxonomy, Rhetorical Role, Comparability KPIs)
- 2026-01-25 v5 : Risques et invariants (ClaimKey.status, Value.comparable, Invariants techniques, Compatibilité A/B/C)
- 2026-01-25 v6 : Correction positionnement épistémique (OSMOSIS = KG documentaire) + Périmètre MVP V1 (Usage B)
- 2026-01-25 v7 : **VERROU FINAL** - OSMOSIS = arbitre de la vérité documentaire (souverain dans le corpus, muet au-delà)
- 2026-01-25 : **✅ NORTH STAR COMPLÈTE ET VERROUILLÉE**
