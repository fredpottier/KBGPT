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
