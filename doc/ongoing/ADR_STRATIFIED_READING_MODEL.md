# ADR: Modèle de Lecture Stratifiée OSMOSIS v2

**Statut**: Review Final - Prêt pour validation
**Date**: 2025-01-23
**Auteurs**: Fred, Claude, ChatGPT (collaboration)

---

## Le Problème Fondamental

### Ce qu'OSMOSIS v1 fait (et pourquoi ça échoue)

OSMOSIS v1 extrait des concepts **chunk par chunk**, puis tente de valider des relations entre ces concepts.

```
Chunk 1 → Extraction → Concept A, Concept B
Chunk 2 → Extraction → Concept C, Concept D
Chunk 3 → Extraction → Concept A', Concept E
...
Puis : "A et B sont-ils liés ?" → Validation LLM → souvent NON
       "A et A' sont-ils identiques ?" → Entity Resolution → incertain
```

**Résultat** :
- 90k+ nodes pour 19 documents
- Très peu de relations validées (la validation est trop stricte)
- Concepts isolés, non navigables
- Un graphe "pur" mais **fonctionnellement inutile**

### Diagnostic : OSMOSIS scanne, il ne lit pas

Un humain qui lit un document fait **l'inverse** :

1. **D'abord** : comprendre le sujet global ("ce document parle de...")
2. **Ensuite** : identifier la structure, les axes de raisonnement
3. **Puis** : repérer les quelques concepts structurants (pas des milliers)
4. **Enfin** : attacher de l'information à ces concepts

OSMOSIS fait :
```
Extraction locale → Concepts fragmentés → Tentative de liens → Échec
```

Un humain fait :
```
Compréhension globale → Concepts structurants → Information attachée → Sens émergent
```

### Le vrai problème

> **On utilise les LLM pour valider des liens entre artefacts fragmentés,
> au lieu de les utiliser pour comprendre et structurer.**

C'est un gâchis de leur capacité de compréhension.

---

## La Solution : Mimétisme Humain

### Principe fondamental

> **Lire comme un humain : comprendre d'abord, détailler ensuite.**

### Inversion du flux

| OSMOSIS v1 (bottom-up) | OSMOSIS v2 (top-down) |
|------------------------|----------------------|
| Chunk → Concepts → Relations (échoue) | Document → Structure → Concepts → Information |
| Extraction locale puis consolidation | Compréhension globale puis extraction ciblée |
| Beaucoup de concepts, peu de liens | Peu de concepts, beaucoup d'information rattachée |
| LLM = validateur oui/non | LLM = lecteur qui comprend |

### Ce que fait un humain (et ce qu'OSMOSIS v2 doit faire)

#### Étape 1 : Comprendre le document (NOUVEAU)

Avant d'extraire quoi que ce soit, le système doit :
- Identifier le **Subject** (de quoi parle ce document ?)
- Identifier les **Themes** (quels sont les axes de raisonnement ?)
- Comprendre la **structure** (comment le document est organisé ?)

##### Structure hiérarchique flexible (pas figée)

La structure n'est **pas** un schéma fixe "Subject > Theme > Section". C'est un **arbre de profondeur variable** qui épouse l'organisation réelle du document :

```
Document "Produit A - Guide Complet"
└── Subject: Produit A
    ├── Theme: Fabrication
    │   ├── Theme: Normes de sécurité        ← sous-thème
    │   │   ├── Theme: Normes européennes    ← sous-sous-thème
    │   │   └── Theme: Normes ISO
    │   ├── Theme: Entités impliquées
    │   │   ├── Section: Usine Lyon          ← feuille
    │   │   └── Section: Sous-traitants
    │   └── Theme: Contrôle qualité
    ├── Theme: Distribution
    │   └── ...
    └── Theme: Support
        └── ...
```

| Élément | Cardinalité | Description |
|---------|-------------|-------------|
| **Subject** | 1 par document | Racine : de quoi parle ce document |
| **Theme** | N, **récursif** | Axe de raisonnement, peut contenir des sous-Themes |
| **Section** | Feuille optionnelle | Unité terminale sans sous-structure |

> **Principe** : La profondeur de l'arbre est déterminée par le document, pas par le système.

#### Étape 2 : Identifier les concepts structurants (FRUGAL)

**Pas** d'extraction exhaustive. On identifie uniquement les concepts qui :
- Sont mentionnés plusieurs fois
- Jouent un rôle central dans le raisonnement
- Portent des informations significatives

```
Concepts structurants identifiés (20-50 par document) :
- FWaaS (Firewall as a Service)
- Pacemaker
- IPSec
- Clean Core
- ...
```

> **Règle clé** : On ne crée jamais un concept pour stocker une information.
> On crée un concept seulement s'il porte plusieurs informations.

##### Critères de création ConceptSitué (garde-fou)

Un ConceptSitué ne peut être créé que si **toutes** ces conditions sont remplies :

| Critère | Seuil minimum | Justification |
|---------|---------------|---------------|
| Information rattachées | ≥ 3 distinctes | Évite les concepts-poubelles |
| Types d'Information | ≥ 2 types différents | Assure richesse sémantique |
| Couverture structurelle | ≥ 2 sections/sous-themes | Prouve centralité dans le document |

> **Invariant** : Si un terme ne remplit pas ces critères, il reste une mention dans l'Information, pas un ConceptSitué.

##### Structures de dépendance des assertions (100% agnostique domaine)

**Principe fondamental** :

> **OSMOSIS n'interprète pas les documents par leur nature, mais par la structure de dépendance de leurs assertions.**

OSMOSIS **ne sait pas** ce qu'est un produit, une loi, un contrat, une procédure. Il ne raisonne que sur une chose : **comment la vérité d'une assertion dépend d'un contexte**.

C'est ce qui rend le modèle :
- Agnostique industrie (pharma, retail, légal, réglementaire, IT...)
- Agnostique métier (pas de liste de "types de documents")
- Robuste face à des corpus hétérogènes

##### Les 3 structures universelles (et seulement elles)

| Structure | Définition | Rôle ConceptSitué |
|-----------|------------|-------------------|
| **CENTRAL** | Assertions dépendantes d'un artefact unique | `role = CENTRAL` |
| **TRANSVERSAL** | Assertions indépendantes | Concepts autonomes |
| **CONTEXTUAL** | Assertions conditionnelles | `role = CONTEXTUAL` |

---

###### Structure 1 — CENTRAL (dépendance forte à un artefact unique)

**Définition** : Un artefact X est CENTRAL si la majorité des assertions du document **cessent d'être vraies si X n'existe pas**.

**Test** : *"Sans X, ce document a-t-il un sens ?"* → NON

**Exemples multi-domaines** :

| Domaine | Document | Artefact CENTRAL |
|---------|----------|------------------|
| IT/Cloud | "Guide S/4HANA Cloud Private Edition" | S/4HANA Cloud PE |
| Pharma | "Manufacturing process of Drug ABC" | Drug ABC |
| Retail | "Pricing model of Marketplace Y" | Marketplace Y |
| Légal | "Obligations under Agreement #123" | Agreement #123 |
| Réglementaire | "Compliance with Regulation Z" | Regulation Z |

**Conséquences** :
- Création d'un ConceptSitué avec `role = CENTRAL`
- Les Information sont rattachées par défaut à cet artefact
- L'artefact devient requêtable ("tout ce que le doc dit de X")

> **Règle Subject → CENTRAL** : Un artefact identifié comme Subject est promu en ConceptSitué CENTRAL **uniquement s'il porte directement des Information typées** (DEFINITION, CAPABILITY, CONSTRAINT, etc.), et pas seulement comme cadre discursif. Un document "à propos de X" où X n'est jamais décrit directement n'a pas de CENTRAL.

---

###### Structure 2 — TRANSVERSAL (assertions indépendantes)

**Définition** : Les assertions sont vraies **sans dépendre d'un artefact particulier**.

**Test** : *"Si je remplace le nom propre par 'another organization/system', l'assertion reste-t-elle vraie ?"* → OUI

**Exemples multi-domaines** :

| Domaine | Assertion transversale |
|---------|------------------------|
| Pharma | "Good Manufacturing Practices require validation of critical processes" |
| Retail | "Customer data should be anonymized before analytics" |
| IA/Réglementaire | "Risk assessment must be performed prior to deployment" |
| Légal | "Force majeure clauses typically include..." |
| Sécurité | "Threat modeling should precede architecture design" |

**Conséquences** :
- Pas d'artefact CENTRAL implicite
- Les ConceptSitué sont les concepts transversaux eux-mêmes
- Aucune tentative de rattachement artificiel

---

###### Structure 3 — CONTEXTUAL (dépendance conditionnelle)

**Définition** : Les assertions ne sont vraies **que sous certaines conditions**, sans définir l'artefact principal.

**Test** : *"Cette assertion commence-t-elle par 'Si...', 'Quand...', 'Dans le cas où...' ?"*

**Exemples multi-domaines** :

| Domaine | Assertion conditionnelle |
|---------|--------------------------|
| Pharma | "If cold-chain transport is used, additional monitoring is required" |
| Retail | "When cross-border shipping applies, customs fees may apply" |
| Réglementaire | "In case of high-risk classification, additional controls are mandatory" |
| Légal | "If the contract is terminated early, penalties apply" |

**Conséquences** :
- Création de ConceptSitué avec `role = CONTEXTUAL`
- L'Information porte le contexte conditionnel (type CONDITION + conséquence)
- Permet les requêtes contextuelles ("que se passe-t-il si...?")

> **Frugalité CONTEXTUAL** : Une condition ne devient ConceptSitué CONTEXTUAL que si elle est **récurrente** (≥2 occurrences) ou **structurante** (plusieurs Information en dépendent). Une condition locale unique reste purement informationnelle (CONDITION + conséquence), sans concept dédié.

---

> **Invariant** : Un artefact n'est promu en ConceptSitué que par analyse de la **dépendance logique des assertions**. Ce n'est ni automatique, ni basé sur une liste métier, ni basé sur le label.

#### Étape 3 : Extraire l'information rattachée (EXHAUSTIF)

Maintenant qu'on a les concepts structurants, on extrait **toute** l'information que le document donne sur chacun.

```
Concept: FWaaS
├── Information (DEFINITION): "Service de firewall cloud inspectant le trafic"
├── Information (CAPABILITY): "Inspecte le trafic entrant et sortant"
├── Information (OPTION): "Disponible en option dans RISE"
├── Information (CONSTRAINT): "Requiert configuration explicite"
└── Information (LIMITATION): "Ne couvre pas le trafic interne"
```

L'information est **abondante** et **typée**. Les concepts sont **rares** et **structurants**.

#### Étape 4 : Les relations — Médiées, pas supposées

**⚠️ Leçon d'OSMOSIS v1** : La co-occurrence (deux concepts dans le même paragraphe) ne prouve PAS une relation. FWaaS et IPSec dans la même section ? Ça ne dit rien sur leur lien direct.

**Principe humain** : Les relations entre concepts sont **médiées par l'Information**, pas par la proximité structurelle.

##### Relations STRUCTURELLES (certaines, hiérarchiques)

Ce sont des relations concept→structure, pas concept→concept :

```
FWaaS --[BELONGS_TO]--> Theme:Network Security
IPSec --[BELONGS_TO]--> Theme:Network Security
```

Ce n'est **PAS** une relation FWaaS↔IPSec. C'est deux relations indépendantes vers le même thème parent.

##### Relations DIRECTES (médiées par Information)

Une relation directe entre deux concepts existe **seulement si** une Information les mentionne ensemble :

```
Information: "Le trafic est chiffré via IPSec avant inspection par FWaaS"
                              ↓
         IPSec --[mentionné_dans]--> Info <--[mentionné_dans]-- FWaaS
                              ↓
         Inférence possible: IPSec --[PRECEDES_IN_FLOW]--> FWaaS
```

Le type de relation est **inféré du contenu** de l'Information, pas supposé.

##### Taxonomie bornée des relations (garde-fou)

Les relations concept↔concept inférées doivent appartenir à un **jeu fini et stable** :

| Relation | Sémantique | Exemple |
|----------|------------|---------|
| `PRECEDES` | Séquence temporelle/logique | IPSec → FWaaS |
| `REQUIRES` | Dépendance technique | FWaaS requires Network Config |
| `CONFIGURES` | Paramétrage | Admin configures FWaaS |
| `ENABLES` | Activation fonctionnelle | License enables Feature |
| `CONSTRAINS` | Limitation/restriction | Policy constrains Access |
| `EXCLUDES` | Incompatibilité | Option A excludes Option B |
| `IMPLEMENTS` | Réalisation concrète | FWaaS implements Firewall |
| `PART_OF` | Composition | Module part_of System |

> **Invariant** : Toute relation hors taxonomie reste **implicite** (non matérialisée dans le graphe).
> Le graphe reste navigable, pas exhaustif.

##### Absence de relation (valide)

FWaaS et IPSec dans le même thème mais **jamais co-mentionnés dans une Information** → **Pas de relation directe**. C'est normal et correct.

> **Règle clé** : Proximité structurelle = contexte partagé (relation au thème).
> Relation directe = preuve informationnelle (une Information qui les lie).

---

## Stratification de l'Information

### L'insight clé

> **Un humain est exhaustif sur l'information, mais sélectif sur ce qu'il promeut conceptuellement.**

L'erreur d'OSMOSIS v1 : confondre exhaustivité et promotion.

### Les niveaux

#### NIVEAU 0 — Information (fondation exhaustive, stockage léger)

Unité atomique de sens. **Tout** ce que le document dit est capturé ici.

- Une Information = une assertion vérifiable indépendamment
- Toujours typée (DEFINITION, FACT, CAPABILITY, CONSTRAINT, etc.)
- Toujours **ancrée** dans le texte source (pointeur, pas copie)
- Toujours rattachée à un Theme et si possible à un Concept

**Stockage** : Nœud léger dans Neo4j (type + anchor + refs). Le texte reste dans Qdrant.

**Volumétrie** : 200-500 par document (léger car pointeurs, pas texte dupliqué)

**Règle CONDITION** : Toute phrase conditionnelle produit 2 Information minimum :
- Une de type CONDITION (le "si")
- Une de type conséquence (le "alors")
- Liées par référence logique, pas par concept

#### NIVEAU 1 — ConceptSitué (doc-level, frugal)

Objet mental stable. Peu nombreux, structurants.

- Créé **uniquement** s'il porte plusieurs Information
- Situé dans le contexte du document (rattaché à un nœud de l'arbre thématique)
- Porteur d'une signature sémantique (meaning_signature)

##### Invariant meaning_signature (garde-fou anti-fusion naïve)

Une meaning_signature doit combiner :

| Composante | Type | Rôle |
|------------|------|------|
| Embedding contextuel | Distributionnel | Similarité sémantique globale |
| Co-termes fréquents | Structuré | Termes systématiquement associés |
| Verbes/actions | Structuré | Ce que le concept "fait" ou "subit" |
| Objets manipulés | Structuré | Sur quoi le concept agit |

> **Invariant** : Une similarité embedding élevée **ne suffit jamais** à justifier une fusion ou promotion.
> Il faut concordance sur **au moins 2 composantes structurées** en plus de l'embedding.

> **Nature** : La meaning_signature est un **faisceau d'indices**, pas une vérité mathématique. Elle guide la décision humaine ou algorithmique, mais n'impose pas de réponse unique. En cas de doute, l'état UNDECIDED est explicitement accepté.

**Volumétrie** : 20-50 par document (ordre de grandeur humain)

#### NIVEAU 2 — Projection contextuelle (query-time)

Pas un "mode tout". Une fermeture informationnelle calculée.

Quand on interroge sur un concept X dans un contexte Y :
- On récupère toutes les Information rattachées à X
- Plus celles de ses sous-concepts
- Plus les conditions et exceptions liées
- Filtré par le Theme Y si spécifié

> **La question choisit un angle. La structure du document détermine la complétude.**

#### NIVEAU 3 — ConceptCanonique (corpus-level, rare)

Stabilisation cross-document. Promotion **tardive** et **justifiée**.

- Regroupe des ConceptSitués de différents documents
- Uniquement si meaning_signature compatible et scope cohérent
- Conserve les divergences (pas de fusion aplatie)

**Volumétrie** : 50-150 pour 20 documents

---

## Règles Anti-Explosion

### Règle 1 : Comprendre avant d'extraire

Pas d'extraction chunk-par-chunk. D'abord le document entier.

### Règle 2 : Concepts frugaux

> Si un humain ne le garderait pas en tête après lecture, le système ne doit pas le matérialiser comme concept.

### Règle 3 : Information abondante

L'information est cheap. Les concepts sont chers. Privilégier l'information.

### Règle 4 : Relations médiées, pas supposées

- Relations concept→thème : **structurelles** (certaines)
- Relations concept↔concept : **médiées par Information** (une Info doit les mentionner ensemble)
- Co-occurrence sans Information commune : **pas de relation**

> Ni validation LLM stricte (v1), ni co-occurrence naïve. L'Information est le médiateur.

### Règle 5 : Pas de fusion par label

"Security" dans doc A ≠ "Security" dans doc B, sauf si meaning_signature et scope compatibles.

---

## Architecture de Stockage

### Principe clé : Information = OVERLAY, pas COPIE

L'Information n'est pas un stockage du texte. C'est une **annotation structurée** qui **pointe** vers le texte source. Pas de duplication.

```
QDRANT (texte + embeddings)          NEO4J (structure + références)
┌────────────────────────┐           ┌─────────────────────────────┐
│  Chunks                │           │  Information (N0) - LÉGER   │
│  - embedding           │◄─anchor───│  - type (FACT, CONSTRAINT)  │
│  - text (500-1000 ch)  │           │  - anchor {chunk_id, span}  │
│  - metadata            │           │  - concept_refs []          │
│  ~500-1000 pour 20docs │           │  ~5000-10000 pour 20 docs   │
└────────────────────────┘           │                             │
                                     │  ConceptSitué (N1)          │
                                     │  ~400-800 pour 20 docs      │
                                     │                             │
                                     │  ConceptCanonique (N3)      │
                                     │  ~50-150 pour 20 docs       │
                                     └─────────────────────────────┘
```

### Ce que contient un nœud Information

| Champ | Stocké | Description |
|-------|--------|-------------|
| `type` | ✅ | FACT, CONSTRAINT, OPTION, CAPABILITY, etc. |
| `anchor` | ✅ | Référence : `{chunk_id, start_char, end_char}` |
| `concept_refs` | ✅ | Liens vers ConceptSitué concernés |
| `theme_ref` | ✅ | Lien vers le Theme parent |
| `text` | ❌ | **PAS stocké** - récupéré à la demande via anchor |

> **Règle** : Le texte n'est jamais dupliqué. Il vit dans Qdrant. L'Information est un pointeur typé.

### Flux de requête

```
Question utilisateur
        │
        ▼
Recherche vectorielle (Qdrant) → Chunks pertinents
        │
        ▼
Pour chaque chunk → récupérer Information ancrées (Neo4j via chunk_id)
        │
        ▼
Depuis Information → naviguer vers Concepts liés
        │
        ▼
Depuis Concepts → récupérer toutes leurs Information
        │
        ▼
Récupérer textes via anchors → Synthèse
```

L'Information n'est pas cherchée par embedding. Elle est **atteinte** via :
- **Anchors** des chunks trouvés (vector search → Information)
- **Liens conceptuels** (Concept → Information)

---

## Flux de Traitement (NOUVEAU)

```
┌─────────────────────────────────────────────────────────────┐
│  PHASE 1 : LECTURE DU DOCUMENT (top-down, nouveau)          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1.1 Analyse globale                                        │
│      └── LLM lit le document entier (ou résumé dense)       │
│      └── Extrait: Subject, Themes, Structure                │
│                                                             │
│  1.2 Identification des concepts structurants               │
│      └── Quelles entités sont centrales ?                   │
│      └── Lesquelles portent le raisonnement ?               │
│      └── Résultat: 20-50 ConceptSitué                       │
│                                                             │
│  1.3 Extraction de l'information                            │
│      └── Pour chaque section, extraire les Information      │
│      └── Typer, ancrer, rattacher aux concepts              │
│      └── Résultat: 200-500 Information                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  PHASE 2 : CORPUS (optionnel, tardif)                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  2.1 Comparaison des ConceptSitués cross-doc                │
│      └── Même label + meaning_signature proche ?            │
│      └── Scope compatible ?                                 │
│                                                             │
│  2.2 Promotion sélective                                    │
│      └── Créer ConceptCanonique si justifié                 │
│      └── Ou marquer UNDECIDED (ambiguïté documentée)        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Ce qui change fondamentalement

| Avant | Après |
|-------|-------|
| Extraction myope chunk par chunk | Lecture globale puis extraction |
| Beaucoup de concepts, peu de relations | Peu de concepts, beaucoup d'information |
| Relations validées une par une (trop strict) | Relations médiées par Information |
| Co-occurrence = relation (trop lâche) | Co-occurrence ≠ relation (Information requise) |
| LLM = arbitre "oui/non" | LLM = lecteur qui comprend |
| KG de mots isolés | Graphe de compréhension documentaire |

---

## Critères de Succès

| Métrique | OSMOSIS v1 | Cible v2 |
|----------|------------|----------|
| Concepts par document | ~4000 | 20-50 |
| Information par concept | ~1 | 5-15 |
| Relations navigables | ~2% | 80%+ (structurelles) |
| Réponses pertinentes | ~50% | >80% |
| Assertions hors-sujet | ~70% | <10% |

---

## Questions Ouvertes

1. **Comment faire lire le document entier au LLM ?** Résumé dense ? Chunks chevauchants ? Map-reduce ?

2. **Seuils des critères ConceptSitué** : Les valeurs (≥3 Info, ≥2 types, ≥2 sections) sont-elles optimales ? À calibrer empiriquement.

3. **Extraction des composantes meaning_signature** : Comment extraire efficacement co-termes, verbes, objets ? NLP classique ou LLM ?

4. **Patterns d'inférence de relations** : Comment mapper le texte d'une Information vers la taxonomie de relations ? Règles ou LLM ?

---

## Historique

| Date | Modification |
|------|--------------|
| 2025-01-23 | Création - Focus sur le problème fondamental et le mimétisme humain |
| 2025-01-23 | Correction Étape 4 - Relations médiées par Information, pas par co-occurrence |
| 2025-01-23 | Clarification Étape 1 - Structure hiérarchique récursive, profondeur variable |
| 2025-01-23 | Clarification Architecture - Information = overlay (pointeur), pas copie du texte |
| 2025-01-23 | Ajout garde-fous (review ChatGPT) : critères ConceptSitué, taxonomie relations, invariant meaning_signature |
| 2025-01-23 | Refonte : 3 structures de dépendance universelles (CENTRAL/TRANSVERSAL/CONTEXTUAL) - 100% agnostique domaine |
| 2025-01-23 | Micro-ajustements finaux : règle Subject→CENTRAL, frugalité CONTEXTUAL, meaning_signature comme faisceau d'indices |
