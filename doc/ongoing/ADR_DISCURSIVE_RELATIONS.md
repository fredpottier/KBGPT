# ADR - Relations Discursivement Déterminées

**Statut**: ACCEPTED
**Date**: 2026-01-20
**Auteurs**: Équipe OSMOSE
**Contexte**: Suite aux POC de discrimination Type 1 / Type 2 (90.5% v3, 87.5% v4)

---

## Contexte

Le projet OSMOSE extrait des relations depuis des documents techniques SAP. Deux types de relations émergent :

1. **Relations explicites** : directement exprimées dans une phrase ("A requires B")
2. **Relations discursivement déterminées** : reconstructibles par un lecteur rigoureux sans ajout de connaissance externe

Les POC de discrimination (v3: 42 cas, v4: 40 cas) ont démontré :
- **0% de faux positifs** sur les relations Type 2 (déduites/interdites)
- **90-100%** de succès sur les patterns discursifs (alternatives, défauts, exceptions)
- Un comportement **conservateur** (ABSTAIN) sur les cas ambigus

---

## Décision

Nous étendons l'architecture Assertion-Aware KG existante pour supporter les relations discursivement déterminées **sans introduire de nouvelle couche dans le graphe**.

Une relation discursivement déterminée est traitée comme une `RawAssertion` avec un marqueur de provenance explicite, soumise à des contraintes plus strictes que les relations explicites.

**L'extraction discursive agit comme un mécanisme supplémentaire de génération de candidates**, en complément de l'extraction explicite intra-segment existante. Elle permet de densifier le graphe sans remplacer ni modifier l'extraction explicite.

### Le pipeline à trois couches reste inchangé

```
RawAssertion (journal append-only, immuable)
    ↓
CanonicalRelation (dédoublonnage + agrégation)
    ↓
SemanticRelation (promue, traversable)
```

La justification reste fournie via `EvidenceBundle` (multi-span), qui demeure **non-navigable**.

---

## Ce qui change

### 1. Nouveaux champs sur RawAssertion

#### AssertionKind (enum)

```python
class AssertionKind(str, Enum):
    EXPLICIT = "EXPLICIT"      # Relation directement exprimée
    DISCURSIVE = "DISCURSIVE"  # Reconstructible sans ajout externe
```

- **EXPLICIT** : la relation est directement exprimée comme énoncé relationnel dans le texte
- **DISCURSIVE** : la relation est reconstructible par un lecteur rigoureux à partir des preuves fournies, sans connaissance externe, inférence transitive, ou complétion causale

#### DiscursiveBasis (enum, set fermé)

Les assertions discursives DOIVENT déclarer la base textuelle qui les rend déterminables :

```python
class DiscursiveBasis(str, Enum):
    ALTERNATIVE = "ALTERNATIVE"   # "X ou Y" explicite
    DEFAULT = "DEFAULT"           # Comportement par défaut
    EXCEPTION = "EXCEPTION"       # "sauf si", "à moins que"
    SCOPE = "SCOPE"               # Maintien de portée entre spans
    COREF = "COREF"               # Résolution référentielle (pronoms)
    ENUMERATION = "ENUMERATION"   # Listes explicites
```

#### AbstainReason (enum, pour gouvernance)

Tout ABSTAIN doit être motivé par une raison structurée :

```python
class DiscursiveAbstainReason(str, Enum):
    WEAK_BUNDLE = "WEAK_BUNDLE"           # Bundle trop court/peu diversifié
    SCOPE_BREAK = "SCOPE_BREAK"           # Rupture de portée référentielle
    COREF_UNRESOLVED = "COREF_UNRESOLVED" # Coréférence non résolue
    TYPE2_RISK = "TYPE2_RISK"             # Risque de relation déduite
    WHITELIST_VIOLATION = "WHITELIST_VIOLATION"  # RelationType interdit
    AMBIGUOUS_PREDICATE = "AMBIGUOUS_PREDICATE"  # Prédicat ambigu
```

#### Champs ajoutés

```python
# Sur RawAssertion
assertion_kind: AssertionKind = Field(default=AssertionKind.EXPLICIT)
discursive_basis: List[DiscursiveBasis] = Field(default_factory=list)
abstain_reason: Optional[DiscursiveAbstainReason] = Field(default=None)
```

---

## Contraintes (non négociables)

### C1. Pas de nouvelle couche

Les relations discursives ne sont **pas** un nouveau type d'entité. Ce sont des `RawAssertion` marquées `assertion_kind=DISCURSIVE`.

### C2. Evidence-first

Une assertion discursive DOIT avoir un `EvidenceBundle`. Elle DOIT pouvoir être expliquée comme :

> "Un lecteur raisonnable comprendrait que…"

basé strictement sur les spans fournis.

### C3. Pas de contamination par inférence

`ExtractionMethod=INFERRED` reste une voie séparée (et restreinte).

Les assertions discursives NE DOIVENT PAS être produites par :
- Fermeture transitive (A→C→B)
- Connaissance externe (background knowledge SAP)
- Raisonnement inter-edges

### C3bis. Contrainte sur ExtractionMethod

Pour éviter que le LLM "interprète" librement :

| AssertionKind | ExtractionMethod autorisé |
|---------------|---------------------------|
| `EXPLICIT` | `PATTERN`, `LLM`, `HYBRID` |
| `DISCURSIVE` | `PATTERN`, `HYBRID` uniquement |

**Interdit** : `assertion_kind=DISCURSIVE` + `ExtractionMethod=LLM` seul.

Rationale : les garde-fous pattern/heuristic doivent valider qu'il s'agit bien d'un pattern discursif reconnu (ALTERNATIVE, DEFAULT, etc.) avant que le LLM confirme.

### C4. Whitelist des RelationType par AssertionKind (V1)

Pour prévenir la dérive sémantique, les assertions DISCURSIVE sont restreintes à un sous-ensemble sûr.

#### Autorisés pour DISCURSIVE (V1)

| RelationType | Condition |
|--------------|-----------|
| `ALTERNATIVE_TO` | Toujours |
| `APPLIES_TO` | Toujours |
| `REQUIRES` | Seulement si obligation explicite (must/shall/required) |
| `REPLACES` | Seulement si temporalité explicite |
| `DEPRECATES` | Seulement si temporalité explicite |

#### Interdits pour DISCURSIVE (V1)

| RelationType | Raison |
|--------------|--------|
| `CAUSES` | Causalité = raisonnement monde |
| `PREVENTS` | Causalité = raisonnement monde |
| `MITIGATES` | Causalité = raisonnement monde |
| `ENABLES` | Implique capacité non-textuelle |
| `DEFINES` | Définitionnel = risque ontologique |

Les assertions EXPLICIT conservent l'accès à l'enum `RelationType` complet.

> **Note évolutive** : En V1, la whitelist est définie au niveau `AssertionKind`. Les versions futures pourraient affiner cette whitelist par `DefensibilityTier` si nécessaire.

### C5. Promotion intacte mais auditable

Les `RawAssertion` discursives peuvent être promues via `CanonicalRelation` → `SemanticRelation` sous le même cadre de gouvernance, tout en préservant la traçabilité via :

- `assertion_kind`
- `discursive_basis`
- `defensibility_tier`
- Références `EvidenceBundle`

Les consommateurs (runtime Graph-First, UI) DOIVENT pouvoir filtrer la traversée via `allowed_tiers` (Set).

Défaut : `{STRICT}` (relations défendables). Mode extended : `{STRICT, EXTENDED}`.

---

## Agrégation (CanonicalRelation)

`CanonicalRelation` doit inclure des compteurs séparés :

```python
explicit_support_count: int = 0    # Nombre de RawAssertion EXPLICIT
discursive_support_count: int = 0  # Nombre de RawAssertion DISCURSIVE
```

Cela permet :
- Scoring différencié par source
- Gouvernance basée sur la nature des preuves
- Transparence pour l'utilisateur

---

## Policy Promotion & Traversal

Cette section définit les règles de promotion (ingestion-time) et de traversée (runtime) pour les assertions EXPLICIT et DISCURSIVE.

### A. Promotion (Ingestion-time)

La promotion d'une `CanonicalRelation` vers `SemanticRelation` dépend de la force du support accumulé.

#### Métriques de support (support_strength)

```python
class SupportStrength(BaseModel):
    """Métriques agrégées pour évaluer la force d'une CanonicalRelation."""
    support_count: int          # Nombre total de RawAssertion
    explicit_count: int         # Nombre de RawAssertion EXPLICIT
    discursive_count: int       # Nombre de RawAssertion DISCURSIVE
    doc_coverage: int           # Nombre de documents distincts
    distinct_sections: int      # Nombre de SectionContext distincts
    bundle_diversity: float     # Score de diversité des EvidenceBundle (0-1)
```

#### Calcul de bundle_diversity (V1, déterministe)

Pour garantir un calcul stable et auditable :

```python
def compute_bundle_diversity(bundle: EvidenceBundle) -> float:
    """
    Diversité = min(1.0, distinct_context_count / 3)
    où distinct_context_count = nombre de SectionContext distincts couverts par les spans.
    """
    distinct_sections = len({span.section_context for span in bundle.spans if span.section_context})
    return min(1.0, distinct_sections / 3)
```

| Sections distinctes | bundle_diversity |
|---------------------|------------------|
| 1 | 0.33 |
| 2 | 0.66 |
| ≥ 3 | 1.0 |

Cette définition est cohérente avec l'esprit Evidence-first et exploite les objets `SectionContext` existants.

#### Agrégation au niveau CanonicalRelation

Quand une `CanonicalRelation` a plusieurs `RawAssertion` support (donc plusieurs bundles) :

```python
# bundle_diversity au niveau CanonicalRelation = max des bundles
canonical_bundle_diversity = max(compute_bundle_diversity(ra.evidence_bundle) for ra in raw_assertions)
```

Rationale : il suffit qu'**une** preuve soit très robuste (diversité élevée) pour "défendre" la relation.

#### Seuils de promotion (V1)

| Critère | EXPLICIT seul | DISCURSIVE seul | MIXED |
|---------|---------------|-----------------|-------|
| `min_support_count` | 1 | 2 | 1 EXPLICIT + 1 DISCURSIVE |
| `min_doc_coverage` | 1 | 1 | 1 |
| `min_distinct_sections` | - | 2 | - |

**Rationale** :
- Une assertion EXPLICIT suffit si elle est claire
- Les assertions DISCURSIVE nécessitent corroboration (2 occurrences dans des sections distinctes du même doc, ou 2 docs)
- `min_doc_coverage=1` pour DISCURSIVE : les patterns "by default… unless…" apparaissent souvent intra-doc mais dans des sections différentes
- `min_distinct_sections=2` : proxy de robustesse intra-doc, évite la promotion sur un seul pattern répété

Note : `bundle_diversity` reste disponible comme métrique d'observabilité mais sans seuil (car `min_distinct_sections=2` implique déjà `bundle_diversity ≥ 0.66`).

#### SemanticGrade (enum)

Chaque `SemanticRelation` promue porte un grade indiquant la nature de ses preuves :

```python
class SemanticGrade(str, Enum):
    EXPLICIT = "EXPLICIT"      # Uniquement des preuves EXPLICIT
    DISCURSIVE = "DISCURSIVE"  # Uniquement des preuves DISCURSIVE
    MIXED = "MIXED"            # Combinaison EXPLICIT + DISCURSIVE
```

Le grade est calculé automatiquement :
- Si `explicit_count > 0` et `discursive_count == 0` → `EXPLICIT`
- Si `explicit_count == 0` et `discursive_count > 0` → `DISCURSIVE`
- Si `explicit_count > 0` et `discursive_count > 0` → `MIXED`

> **Clarification importante** : `SemanticGrade` est purement descriptif et n'implique aucune hiérarchie de fiabilité. Il indique l'origine des preuves, pas leur qualité.

#### DefensibilityTier (enum) — Concept clé

**Principe fondamental** : DISCURSIVE n'est pas "moins fiable" que EXPLICIT. C'est une **autre forme de preuve**. La vraie question est : cette relation est-elle **défendable** ?

On sépare deux axes orthogonaux :
- `assertion_kind` = **comment** on l'a obtenu (EXPLICIT / DISCURSIVE)
- `defensibility_tier` = **à quel point** c'est défendable

```python
class DefensibilityTier(str, Enum):
    STRICT = "STRICT"           # Utilisable en mode strict (production)
    EXTENDED = "EXTENDED"       # Utilisable en mode élargi (exploration)
    EXPERIMENTAL = "EXPERIMENTAL"  # Réservé (INFERRED, hors scope V1)
```

```python
# Sur SemanticRelation
semantic_grade: SemanticGrade = Field(...)
defensibility_tier: DefensibilityTier = Field(...)  # Calculé à la promotion
```

Ainsi :
- `EXPLICIT + STRICT` : classique (relation écrite en toutes lettres)
- `DISCURSIVE + STRICT` : relation text-determined avec preuve forte (0% FP Type 2)
- `DISCURSIVE + EXTENDED` : bundle faible, pattern moins déterminant

**Le runtime STRICT traverse toutes les relations où `defensibility_tier = STRICT`**, indépendamment de leur `assertion_kind`.

#### Attribution du DefensibilityTier (ingestion-time)

##### Règle récapitulative par SemanticGrade

| SemanticGrade | DefensibilityTier | Rationale |
|---------------|-------------------|-----------|
| `EXPLICIT` | **STRICT** | Preuve directe, toujours défendable |
| `MIXED` | **STRICT** | Au moins une preuve EXPLICIT "ancre" la relation |
| `DISCURSIVE` | **STRICT ou EXTENDED** | Dépend de la matrice basis → tier (voir ci-dessous) |

##### EXPLICIT → STRICT

Par défaut, toute assertion EXPLICIT avec un EvidenceBundle valide est **STRICT**.

##### MIXED → STRICT

Une relation MIXED (au moins une preuve EXPLICIT + au moins une preuve DISCURSIVE) est **toujours STRICT**.

Rationale : la preuve EXPLICIT suffit à "porter" la relation. La preuve DISCURSIVE apporte une densification supplémentaire sans risque, puisque l'EXPLICIT ancre déjà la relation.

##### DISCURSIVE → STRICT si et seulement si :

1. `ExtractionMethod ∈ {PATTERN, HYBRID}` (contrainte C3bis)
2. `RelationType ∈ whitelist_discursive_v1` (contrainte C4)
3. `discursive_basis` contient au moins **une base déterministe forte**
4. EvidenceBundle satisfait le minimum adapté à la base

##### Bases déterministes fortes (V1)

Ces bases reposent sur des **opérateurs linguistiques structurants** très proches d'un énoncé explicite :

| DiscursiveBasis | Marqueurs textuels | Bundle minimum |
|-----------------|-------------------|----------------|
| `ALTERNATIVE` | "or", "either…or", "X ou Y" | 1 span si contient "or" + les deux options identifiées |
| `DEFAULT` | "by default", "par défaut" | 1 span si contient le marqueur explicite |
| `EXCEPTION` | "unless", "except", "sauf si" | 1 span si contient le marqueur explicite |

##### Bases moins déterministes (V1)

Ces bases peuvent être STRICT mais demandent **plus de friction** :

| DiscursiveBasis | Exigence supplémentaire |
|-----------------|------------------------|
| `SCOPE` | ≥ 2 spans (scope + référence) + audit anchor_type |
| `COREF` | ≥ 2 spans + résolution explicite documentée |
| `ENUMERATION` | Liste complète identifiable dans le bundle |

Si les exigences ne sont pas satisfaites : `defensibility_tier = EXTENDED` (ou ABSTAIN).

##### Matrice récapitulative basis → tier

| DiscursiveBasis | Conditions STRICT | Sinon |
|-----------------|-------------------|-------|
| ALTERNATIVE | marqueur "or" + options identifiées | EXTENDED |
| DEFAULT | marqueur "by default" explicite | EXTENDED |
| EXCEPTION | marqueur "unless/except" explicite | EXTENDED |
| SCOPE | ≥ 2 spans + anchor_type audité | EXTENDED |
| COREF | ≥ 2 spans + coref_path documenté | EXTENDED |
| ENUMERATION | liste complète dans bundle | EXTENDED |

### B. Traversal (Runtime)

#### Paramètre de filtrage — defensibility_tier

Le mode Reasoned filtre par **defensibility_tier**, pas par assertion_kind :

```python
allowed_tiers: Set[DefensibilityTier] = {DefensibilityTier.STRICT}
```

| Mode | `allowed_tiers` | Ce qui est traversé | Usage |
|------|-----------------|---------------------|-------|
| **Strict** (défaut) | `{STRICT}` | Toutes relations défendables (EXPLICIT ou DISCURSIVE) | Production, réponses contractuelles |
| **Extended** | `{STRICT, EXTENDED}` | + relations à bundle faible | Découverte, navigation |

**Règle clé** : le mode Strict traverse les relations **défendables**, qu'elles soient EXPLICIT ou DISCURSIVE.

Rationale : une relation DISCURSIVE avec base déterministe forte (ALTERNATIVE, DEFAULT, EXCEPTION) est aussi fiable qu'une relation EXPLICIT. Les POC ont démontré 0% de faux positifs Type 2 sur ces patterns.

> **Clarification importante** : Le terme "Strict" réfère à la **défendabilité épistémique**, pas à la méthode d'extraction. Une traversée Strict inclut toute relation dont l'existence est pleinement défendable à partir du texte, qu'elle soit explicite ou discursivement déterminée. **STRICT ≠ EXPLICIT**.

Note : `semantic_grade` reste disponible pour l'UI (transparence sur l'origine) mais n'est pas le critère de filtrage runtime.

#### Stratégie d'escalade (optionnelle)

Pour les cas où le mode Strict ne trouve pas de résultat :

```
1. Strict ({STRICT}) → Si résultat vide :
2. Extended ({STRICT, EXTENDED}) → Si toujours vide :
3. Anchored fallback (texte + ancrage)
```

L'escalade est **optionnelle** et configurable par le consommateur.

#### Anti-contamination

Pour éviter que les relations DISCURSIVE ne polluent le raisonnement :

1. **Séparation des chemins** : les traversées DISCURSIVE sont marquées distinctement
2. **Pas de transitivité croisée** : `EXPLICIT → DISCURSIVE → ?` ne doit pas produire de nouvelle relation
3. **Traçabilité** : chaque edge traversé porte son `semantic_grade`

**Clarification "No transitivity"** :

> Aucune écriture de relation dérivée (`ExtractionMethod=INFERRED`) ne peut être produite à partir d'un path contenant une edge DISCURSIVE, ni pendant le runtime (pathfinding), ni par un job offline de dérivation. Seul un mode expérimental explicitement activé pourrait lever cette restriction (hors scope V1).

### C. Garde-fous de la Policy

| Invariant | Description |
|-----------|-------------|
| **No silent upgrade** | Une relation DISCURSIVE ne peut jamais être présentée comme EXPLICIT |
| **Grade transparency** | Le `semantic_grade` est toujours accessible au consommateur |
| **Promotion audit** | Chaque promotion est loggée avec les métriques de support |

### D. Phasage recommandé

| Phase | Scope | `allowed_tiers` défaut |
|-------|-------|------------------------|
| **V1** (actuel) | Whitelist restreinte, bases fortes = STRICT | `{STRICT}` |
| **V2** | Élargissement bases STRICT si 0% FP maintenu | `{STRICT}` |
| **V3** | Mode Extended en production | `{STRICT, EXTENDED}` optionnel |

---

## Runtime Graph-First

### Mode Reasoned

- Traverse uniquement les `SemanticRelation`
- Applique la policy de traversal définie ci-dessus
- Paramètre de filtrage : `allowed_tiers` (Set de DefensibilityTier)
- Défaut : `{STRICT}` — traverse toutes les relations défendables (EXPLICIT ou DISCURSIVE)

### Mode Anchored

- Ne dépend pas des relations sémantiques
- Les assertions DISCURSIVE peuvent aider à router mais pas à raisonner
- Fallback naturel pour l'escalade

### Mode Text-only

- Inchangé

---

## Observabilité et Garde-fous

### KPI Sentinel (invariant)

| KPI | Seuil | Description |
|-----|-------|-------------|
| FP Type 2 | = 0% | Aucun faux positif sur relations interdites |
| Accept Type 1 | ≥ 80% | Densification suffisante |
| Abstain motivé | 100% | Tout ABSTAIN doit avoir une `abstain_reason` |

### Régression obligatoire

Chaque nouvelle version du prompt ou du bundle builder doit re-tester un set fixe de cas "pièges Type 2" avant déploiement.

---

## Résumé récapitulatif

Ce tableau synthétise les combinaisons possibles et leur comportement runtime :

| Dimension | EXPLICIT | DISCURSIVE (STRICT) | DISCURSIVE (EXTENDED) |
|-----------|----------|---------------------|----------------------|
| **AssertionKind** | EXPLICIT | DISCURSIVE | DISCURSIVE |
| **SemanticGrade** | EXPLICIT ou MIXED | DISCURSIVE ou MIXED | DISCURSIVE |
| **DefensibilityTier** | STRICT | STRICT | EXTENDED |
| **Traversable en STRICT** | ✅ | ✅ | ❌ |
| **Traversable en EXTENDED** | ✅ | ✅ | ✅ |
| **Bases typiques** | N/A | ALTERNATIVE, DEFAULT, EXCEPTION | SCOPE, COREF (bundle faible) |

**Lecture clé** : une relation DISCURSIVE avec base déterministe forte (ALTERNATIVE, DEFAULT, EXCEPTION) est promue en tier STRICT et donc traversable en mode production, au même titre qu'une relation EXPLICIT.

---

## Conséquences

### Positives

1. **Densification du KG** sur documents normatifs tout en maintenant l'intégrité épistémique
2. **Graphe navigable** sans recours à l'inférence interdite
3. **Égalité de traitement** : une relation DISCURSIVE avec base déterministe forte est aussi "fiable" qu'une EXPLICIT
4. **Mode STRICT = défendable** : le runtime ne discrimine pas par origine mais par qualité de preuve
5. **Invariant préservé** : aucune relation sans détermination textuelle défendable

### Négatives

1. Complexité accrue du modèle `RawAssertion` et `SemanticRelation`
2. Nécessité de maintenir la whitelist RelationType et la matrice basis → tier
3. Tests de régression obligatoires à chaque évolution

---

## Alternatives considérées

### A1. Nouvelle couche "DiscursiveRelation"

**Rejeté** : aurait créé une 4ème couche redondante avec `RawAssertion`.

### A2. Flag booléen `is_discursive`

**Rejeté** : insuffisant pour capturer la base textuelle (ALTERNATIVE, DEFAULT, etc.).

### A3. Pas de distinction

**Rejeté** : impossible de garantir l'intégrité du KG sans séparer les modes d'extraction.

---

## Références

- [ADR-20260104-assertion-aware-kg.md](../adr/ADR-20260104-assertion-aware-kg.md) - DocContextFrame, AnchorContext
- [ADR-20260106-graph-first-architecture.md](../adr/ADR-20260106-graph-first-architecture.md) - Modes runtime
- [ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md](../adr/ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md) - EvidenceBundle
- [POC v3 Results](../../scripts/poc_discursive/results/poc_v3_results_20260120_151909.json) - 90.5%, 0% FP
- [POC v4 Results](../../scripts/poc_discursive/results/poc_v4_results_20260120_153747.json) - 87.5%, 0% FP

---

## Extraction des Relations Discursives

Cette section définit **comment** extraire les relations discursives à partir du texte. Elle complète les sections précédentes qui définissaient **quoi** stocker et **comment** le promouvoir.

---

### Discursive Candidate Generation — Extraction Contract (V1)

L'extraction discursive est **strictement limitée à la génération de candidates déclenchée par pattern**.

Un candidat discursif **DOIT** satisfaire **TOUTES** les conditions suivantes :

#### Règle E1. Local Textual Trigger (Déclencheur textuel local)

Le candidat est généré **uniquement** à partir de segments textuels contenant un marqueur discursif explicite (`or`, `unless`, `by default`, énumération, etc.).

**Interdit** : scanner un document à la recherche de paires de concepts sans marqueur.

#### Règle E2. Local Co-presence (Co-présence locale)

Les concepts Subject et Object **DOIVENT** être présents (lexicalement ou référentiellement) dans le **même contexte textuel borné** :
- Même phrase, ou
- Même paragraphe, ou
- Même fenêtre EvidenceBundle (≤ 500 caractères autour du marqueur)

**Interdit** : relier deux concepts qui n'apparaissent pas ensemble localement.

#### Règle E3. No Global Pairing (Pas de pairing global)

L'extracteur **NE DOIT PAS** générer de candidates en appariant arbitrairement des concepts à travers un document ou une section.

**Interdit** : "Concept A est en page 1, Concept B est en page 5, le LLM pense qu'ils sont liés".

> **Rationale** : Cette règle protège explicitement contre les approches de type "pairwise concept testing" ou "concept graph completion", même lorsqu'un LLM est contraint. Ces approches génèrent du bruit massif et des relations non-défendables.

#### Règle E4. Pattern-First, LLM-Second

La génération de candidates discursives **DOIT** être initiée par une détection de pattern (déterministe ou heuristique).

Le LLM est utilisé **uniquement** pour :
- Valider ou rejeter un candidat proposé par le pattern
- Confirmer l'identification des concepts
- Jamais pour proposer librement une relation

**Séquence obligatoire** :
```
Pattern détecte marqueur → Pattern identifie concepts → [LLM valide] → Candidate créé
```

**Interdit** :
```
LLM scanne le texte → LLM propose une relation → Pattern vérifie après coup
```

#### Règle E5. Candidate ≠ Assertion

Un candidat généré **n'a aucun statut sémantique** tant qu'il n'est pas :
1. Validé par les contraintes (C3bis, C4, etc.)
2. Matérialisé comme `RawAssertion`
3. Promu via le pipeline standard

**Conséquence** : l'extracteur peut générer des candidates qui seront rejetés. C'est normal et attendu. Le taux de rejet est une métrique de qualité de l'extracteur.

#### Règle E6. No Concept Creation (Pas de création de concepts)

L'extraction discursive **NE DOIT PAS** introduire de nouveaux concepts. Elle opère **strictement** sur l'inventaire de concepts existant (CanonicalConcept).

**Interdit** : "Le pattern détecte un terme inconnu, on crée un concept pour pouvoir créer la relation".

**Conséquence** : si un marqueur discursif est détecté mais qu'un des termes n'est pas un concept connu, le candidat est rejeté (pas de RawAssertion créée).

---

### Objectif

Créer un mécanisme d'extraction qui:
1. Détecte les patterns discursifs dans le texte (marqueurs linguistiques)
2. Identifie les concepts impliqués autour de ces marqueurs
3. Génère des `RawAssertion` avec `assertion_kind=DISCURSIVE`
4. Respecte la contrainte C3bis (PATTERN ou HYBRID, pas LLM seul)

### Architecture proposée: Pattern-First avec validation LLM optionnelle

```
┌─────────────────────────────────────────────────────────────────────────┐
│ PIPELINE D'EXTRACTION (ordre séquentiel)                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. LLM Relation Extractor (existant)                                   │
│     → Extrait relations EXPLICIT                                        │
│     → assertion_kind = EXPLICIT                                         │
│     → ExtractionMethod = LLM ou HYBRID                                  │
│                                                                         │
│  2. Discursive Pattern Extractor (nouveau)                              │
│     → Scanne pour marqueurs discursifs                                  │
│     → Identifie concepts adjacents                                      │
│     → assertion_kind = DISCURSIVE                                       │
│     → ExtractionMethod = PATTERN (ou HYBRID si LLM valide)              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Rationale**: L'extraction discursive est un **complément** à l'extraction explicite, pas un remplacement. Les deux extracteurs tournent séquentiellement sur le même texte.

### Algorithmes de détection par DiscursiveBasis

#### A. ALTERNATIVE — Pattern "X or Y"

**Marqueurs détectés**:
- EN: `or`, `either...or`, `alternatively`
- FR: `ou`, `soit...soit`, `alternativement`

**Algorithme**:
```
1. Regex: trouver patterns "(Concept1) (or|ou) (Concept2)"
2. Vérifier que Concept1 et Concept2 sont dans le catalogue de concepts connus
3. Si oui:
   - Créer: ALTERNATIVE_TO(Concept1, Concept2)
   - Créer: ALTERNATIVE_TO(Concept2, Concept1)  # Symétrique
   - discursive_basis = [ALTERNATIVE]
   - ExtractionMethod = PATTERN
```

**Exemple**:
```
Texte: "You can deploy on SAP HANA or Oracle Database"
Détection: "SAP HANA" OR "Oracle Database"
Output: ALTERNATIVE_TO(SAP HANA, Oracle Database), ALTERNATIVE_TO(Oracle Database, SAP HANA)
```

**Cas limite - ABSTAIN**:
- Si un seul concept reconnu → ABSTAIN (WEAK_BUNDLE)
- Si "or" dans contexte négatif ("not X or Y") → ABSTAIN (AMBIGUOUS_PREDICATE)

#### B. DEFAULT — Pattern "by default"

**Marqueurs détectés**:
- EN: `by default`, `defaults to`, `default is`, `default value`
- FR: `par défaut`, `défaut est`, `valeur par défaut`

**Algorithme**:
```
1. Regex: trouver "by default" ou "par défaut" dans une phrase
2. Identifier le sujet (ce qui a un défaut) et l'objet (la valeur par défaut)
3. Patterns typiques:
   - "[Subject] defaults to [Object]"
   - "[Subject] uses [Object] by default"
   - "By default, [Subject] is configured with [Object]"
4. Si Subject et Object sont des concepts connus:
   - Créer: USES(Subject, Object) ou APPLIES_TO(Object, Subject)
   - discursive_basis = [DEFAULT]
   - ExtractionMethod = PATTERN
```

**Exemple**:
```
Texte: "SAP S/4HANA uses SAP HANA by default"
Détection: Subject="SAP S/4HANA", Object="SAP HANA", marker="by default"
Output: USES(SAP S/4HANA, SAP HANA) avec basis=[DEFAULT]
```

**Cas limite - ABSTAIN**:
- Si le défaut est une valeur non-concept (ex: "timeout defaults to 30s") → ABSTAIN (pas de relation inter-concepts)

#### C. EXCEPTION — Pattern "unless/except"

**Marqueurs détectés**:
- EN: `unless`, `except`, `except when`, `except if`, `excluding`
- FR: `sauf`, `sauf si`, `à moins que`, `excepté`, `hormis`

**Algorithme**:
```
1. Regex: trouver "unless|except|sauf" suivi d'une condition
2. Identifier:
   - La règle générale (avant le marqueur)
   - L'exception (après le marqueur)
3. Si les concepts sont identifiables:
   - Créer relation de la règle générale
   - Annoter avec discursive_basis = [EXCEPTION]
   - Stocker la condition d'exception dans evidence_text
```

**Exemple**:
```
Texte: "All modules require SAP HANA, unless you use the legacy adapter"
Détection: règle="modules require SAP HANA", exception="legacy adapter"
Output: REQUIRES(modules, SAP HANA) avec basis=[EXCEPTION]
        Note: l'exception est tracée mais ne crée pas de relation séparée (trop risqué)
```

**Cas limite - ABSTAIN**:
- Si l'exception invalide complètement la règle → ABSTAIN (SCOPE_BREAK)
- Si l'exception introduit un concept non-résolu → ABSTAIN (COREF_UNRESOLVED)

#### D. SCOPE — Maintien de portée inter-phrases

**Marqueurs détectés**:
- Références anaphoriques structurelles: "This module", "These components", "The following"
- Listes avec contexte partagé

**Algorithme**:
```
1. Détecter une phrase établissant un scope (ex: "SAP S/4HANA includes:")
2. Identifier les éléments dans le scope (liste, paragraphe suivant)
3. Pour chaque élément:
   - Hériter le sujet du scope
   - Créer relation avec discursive_basis = [SCOPE]
   - Exiger ≥ 2 spans (span scope + span élément)
```

**Exemple**:
```
Texte: "SAP S/4HANA includes the following modules:
        - Finance
        - Logistics
        - HR"
Détection: Scope="SAP S/4HANA includes", éléments=[Finance, Logistics, HR]
Output: PART_OF(Finance, SAP S/4HANA), PART_OF(Logistics, SAP S/4HANA), PART_OF(HR, SAP S/4HANA)
        Chacun avec basis=[SCOPE], 2 spans requis
```

**Risque élevé** → ExtractionMethod = HYBRID recommandé (pattern + validation LLM)

#### E. COREF — Résolution de coréférence

**Dépendance**: Nécessite le module de coréférence (Pass 0.5) déjà implémenté.

**Algorithme**:
```
1. Utiliser le résolveur de coréférence existant
2. Si un pronom est résolu vers un concept:
   - Créer la relation avec le concept résolu (pas le pronom)
   - discursive_basis = [COREF]
   - Stocker coref_resolution_path
   - Exiger ≥ 2 spans (span pronom + span antécédent)
```

**Exemple**:
```
Texte: "SAP HANA provides in-memory computing. It requires 256GB RAM minimum."
Coref: "It" → "SAP HANA"
Output: REQUIRES(SAP HANA, 256GB RAM) avec basis=[COREF]
```

#### F. ENUMERATION — Listes explicites

**Marqueurs détectés**:
- Listes numérotées ou à puces
- Patterns: "includes:", "consists of:", "comprend:", "se compose de:"

**Algorithme**:
```
1. Détecter structure de liste (markdown, HTML, ou textuelle)
2. Identifier le sujet de la liste
3. Pour chaque élément:
   - Vérifier si c'est un concept connu
   - Créer relation PART_OF ou USES selon contexte
   - discursive_basis = [ENUMERATION]
```

**Chevauchement avec SCOPE**: ENUMERATION est un cas particulier de SCOPE avec structure de liste explicite. Utiliser ENUMERATION si la liste est clairement délimitée.

#### Garde-fou pour SCOPE et ENUMERATION

> **Important** : Les relations structurelles (ex: `PART_OF`) extraites via SCOPE ou ENUMERATION **DOIVENT** rester document-scoped et **NE DOIVENT PAS** être interprétées comme une composition ontologique.
>
> Ces relations expriment "dans ce document, X est présenté comme partie de Y", pas "X est ontologiquement une partie de Y dans l'absolu".

### Règles de création de RawAssertion

#### Champs obligatoires pour DISCURSIVE

```python
RawAssertion(
    # Standard
    raw_assertion_id=generate_ulid(),
    subject_concept_id=subject_id,
    object_concept_id=object_id,
    predicate_raw=detected_predicate,      # Ex: "alternative to", "uses by default"
    predicate_norm=normalize(predicate),
    evidence_text=matched_span,            # Le texte contenant le marqueur

    # DISCURSIVE spécifique
    assertion_kind=AssertionKind.DISCURSIVE,
    discursive_basis=[detected_basis],     # Ex: [DiscursiveBasis.ALTERNATIVE]

    # Contrainte C3bis
    extraction_method=ExtractionMethod.PATTERN,  # ou HYBRID si LLM valide

    # Contrainte C4 - vérifier whitelist
    relation_type=validated_relation_type,  # Doit être dans whitelist DISCURSIVE

    # Confidence
    confidence_extractor=pattern_confidence,  # Typiquement 0.7-0.9 selon pattern
)
```

#### Validation pré-écriture

Avant de créer une RawAssertion DISCURSIVE, vérifier:

```python
def validate_before_write(assertion: RawAssertion) -> Optional[DiscursiveAbstainReason]:
    # C3bis: ExtractionMethod
    if assertion.extraction_method == ExtractionMethod.LLM:
        return DiscursiveAbstainReason.TYPE2_RISK

    # C4: Whitelist RelationType
    if assertion.relation_type not in DISCURSIVE_ALLOWED_RELATION_TYPES:
        return DiscursiveAbstainReason.WHITELIST_VIOLATION

    # Basis requise
    if not assertion.discursive_basis:
        return DiscursiveAbstainReason.WEAK_BUNDLE

    return None  # OK
```

### Intégration dans le pipeline existant

#### Option A: Extracteur séparé (recommandée)

```python
# Dans le pipeline d'ingestion

# 1. Extraction EXPLICIT (existant)
explicit_relations = llm_extractor.extract_relations(text, concepts)
for rel in explicit_relations:
    raw_assertion_writer.write_assertion(..., assertion_kind=AssertionKind.EXPLICIT)

# 2. Extraction DISCURSIVE (nouveau)
discursive_relations = discursive_pattern_extractor.extract_relations(text, concepts)
for rel in discursive_relations:
    # Dédoublonner avec EXPLICIT (même paire de concepts + même type)
    if not is_duplicate(rel, explicit_relations):
        raw_assertion_writer.write_assertion(..., assertion_kind=AssertionKind.DISCURSIVE)
```

**Avantage**: Séparation claire des responsabilités, facile à activer/désactiver.

#### Option B: Mode HYBRID intégré

```python
# L'extracteur LLM existant détecte aussi les patterns discursifs
relations = llm_extractor.extract_relations(text, concepts, detect_discursive=True)

# Le LLM retourne assertion_kind dans sa réponse
for rel in relations:
    if rel.assertion_kind == "DISCURSIVE":
        # Valider avec pattern matcher avant d'accepter
        if pattern_matcher.confirms(rel):
            extraction_method = ExtractionMethod.HYBRID
        else:
            continue  # Rejeter si LLM dit DISCURSIVE mais pas de pattern
```

**Avantage**: Un seul appel LLM. **Risque**: Le LLM peut sur-classifier en DISCURSIVE.

#### Recommandation

**Option A** pour V1 (extracteur séparé, PATTERN uniquement).
**Option B** peut être explorée en V2 si les patterns purs manquent trop de relations.

### Déduplication EXPLICIT vs DISCURSIVE

Si la même relation est trouvée par les deux extracteurs:

| Cas | Action |
|-----|--------|
| EXPLICIT trouvé, DISCURSIVE trouvé | Garder les deux (compteurs séparés sur CanonicalRelation) |
| Même evidence_text | Garder seulement EXPLICIT (plus direct) |
| Evidence différente | Garder les deux (renforce la relation) |

La déduplication finale se fait au niveau `CanonicalRelation` via les compteurs `explicit_support_count` et `discursive_support_count`.

### Métriques de succès

| Métrique | Cible V1 | Mesure |
|----------|----------|--------|
| **Nouvelles relations trouvées** | +20-50% vs EXPLICIT seul | Count après extraction |
| **Précision DISCURSIVE** | ≥ 90% | Validation manuelle échantillon |
| **FP Type 2** | = 0% | Tests de régression |
| **Patterns couverts** | ALTERNATIVE, DEFAULT, EXCEPTION | Bases fortes uniquement en V1 |

### Limitations V1

1. **Bases faibles (SCOPE, COREF, ENUMERATION)** : Implémentation différée ou EXTENDED-only
2. **Multilingual** : FR + EN uniquement
3. **Pas de LLM validation** : PATTERN pur (ExtractionMethod.PATTERN)
4. **Concepts connus uniquement** : Pas de découverte de nouveaux concepts

### Tests de validation

#### Test A/B requis

```
1. Corpus de test : 10 documents SAP représentatifs
2. Run A : Extraction EXPLICIT seule (baseline)
3. Run B : Extraction EXPLICIT + DISCURSIVE
4. Mesurer :
   - Δ relations trouvées
   - Δ concepts connectés (densité du graphe)
   - Précision manuelle sur échantillon DISCURSIVE
   - 0% FP Type 2 (invariant)
```

#### Cas de régression obligatoires

Chaque release doit passer les cas "pièges Type 2" :

```python
TYPE2_REGRESSION_CASES = [
    # Ne doit PAS créer de relation
    ("SAP is better than Oracle", None),  # Opinion, pas fait
    ("HANA enables real-time analytics", None),  # ENABLES interdit pour DISCURSIVE
    ("If you use BW, you need HANA", None),  # Causal implicite

    # DOIT créer une relation
    ("Use HANA or Oracle for the database", ALTERNATIVE_TO),
    ("S/4HANA uses HANA by default", USES),
    ("All modules require HANA, unless legacy", REQUIRES),
]
```

---

## Prochaines étapes

1. **Implémentation RawAssertion** : Ajouter `AssertionKind`, `DiscursiveBasis` et `DiscursiveAbstainReason`
2. **Whitelist** : Implémenter la validation des RelationType par AssertionKind
3. **ExtractionMethod** : Implémenter la contrainte DISCURSIVE → PATTERN/HYBRID uniquement
4. **Agrégation** : Ajouter les compteurs séparés sur `CanonicalRelation`
5. **SupportStrength** : Implémenter les métriques de support (support_count, doc_coverage, bundle_diversity)
6. **SemanticGrade** : Ajouter le grade sur `SemanticRelation` et le calcul automatique
7. **DefensibilityTier** : Implémenter l'attribution du tier (STRICT/EXTENDED) selon la matrice basis → tier
8. **Runtime** : Ajouter le paramètre `allowed_tiers` (Set de DefensibilityTier) au mode Reasoned
9. **Escalade** : Implémenter la stratégie d'escalade optionnelle (STRICT → EXTENDED → Anchored)
10. **Tests** : Créer le set de régression Type 2 permanent
