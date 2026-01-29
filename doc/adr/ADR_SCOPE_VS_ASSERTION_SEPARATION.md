# ADR - Scope vs Assertion : Separation of Concerns

**Statut**: ✅ **APPROVED** – ARCHITECTURAL FOUNDATION – BLOCKING
**Date**: 2026-01-21
**Validation**: 2026-01-21
**Auteurs**: Équipe OSMOSE
**Contexte**: Suite aux réflexions sur le taux de capture des relations discursives
**Impact**: Cet ADR est **bloquant** pour toute implémentation touchant aux couches Assertion ou Navigation

---

## Résumé exécutif

> **OSMOSIS ne cherche pas à tout relier. Il cherche à ne relier que ce qui est défendable.**

Cet ADR formalise la séparation fondamentale entre :
- **Scope Layer** (dense) : Ce que le document **couvre** → Navigation
- **Assertion Layer** (sparse) : Ce que le document **affirme** → Raisonnement

Cette séparation est la **colonne vertébrale** d'OSMOSIS. Elle garantit que :
1. Le graphe sémantique reste **fiable et auditable**
2. L'exploitabilité vient du **mode Anchored + Scope**, pas d'assertions inventées
3. Aucun compromis "dense mais faux" ne pollue le système

---

## Contexte

L'implémentation des relations discursives a révélé une tension fondamentale :

1. **Un document technique contient ~90% d'informations contextuelles** qu'un lecteur humain reconstruit implicitement
2. **Notre système evidence-first ne capture que ~5-15%** de ces relations
3. **Augmenter ce taux force mécaniquement des hypothèses non prouvées** (Type 2)

### Le paradoxe observé

```
Document: "SAP S/4HANA Operations Guide"
Section: "System Requirements"
Liste: "- SAP HANA\n- 256GB RAM\n- Linux"
```

Un humain reconstruit instantanément : "S/4HANA requires SAP HANA"

Mais **le texte ne l'affirme jamais explicitement**. La relation est reconstruite via le **contexte documentaire**, pas via une preuve textuelle locale.

### Question clé

> Le contexte documentaire est-il une "connaissance externe" (Type 2 interdit) ou une "reconstruction légitime" (Type 1 autorisé) ?

---

## Décision

**Le contexte documentaire n'est ni Type 1 ni Type 2. C'est une troisième catégorie : le SCOPING.**

Nous formalisons une **séparation stricte** entre deux couches :

| Couche | Ce qu'elle exprime | Densité | Traversable |
|--------|-------------------|---------|-------------|
| **Scope Layer** | Ce que le document couvre | Dense | Non (navigation) |
| **Assertion Layer** | Ce que le document affirme | Sparse | Oui (raisonnement) |

**Ces deux couches ne doivent jamais être confondues.**

---

## Définitions

### Assertion (couche sémantique)

> Une **assertion** est un énoncé relationnel entre deux concepts qui peut être **défendu** par une preuve textuelle locale.

Caractéristiques :
- Preuve dans un span textuel identifiable
- Un lecteur raisonnable pourrait citer la phrase justificative
- Traversable pour le raisonnement
- Stockée comme `RawAssertion` → `CanonicalRelation` → `SemanticRelation`

Exemple :
```
Texte: "SAP HANA requires a minimum of 256GB RAM for production workloads"
Assertion: REQUIRES(SAP HANA, 256GB RAM)
Evidence: "SAP HANA requires a minimum of 256GB RAM"
→ DÉFENDABLE : la phrase le dit explicitement
```

### Scope (couche de portée)

> Un **scope** est un cadre d'interprétation qui indique **de quoi parle** une unité documentaire, sans affirmer de relation entre concepts.

Caractéristiques :
- Dérivé de la structure documentaire (titre, section, metadata)
- Permet la navigation et le filtrage
- **Non traversable** pour le raisonnement
- Ne génère **jamais** de `RawAssertion`

Exemple :
```
Document: "SAP S/4HANA Operations Guide"
Section: "System Requirements"
Scope: Ce contenu concerne S/4HANA
→ NON DÉFENDABLE comme assertion : aucune phrase ne dit "S/4HANA requires X"
→ UTILE pour la navigation : filtrer les chunks pertinents pour S/4HANA
```

---

## Architecture résultante

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SCOPE LAYER (dense)                         │
│                                                                     │
│  Document ──── topic: "SAP S/4HANA"                                │
│     │                                                               │
│     ├── Section ──── scope: "System Requirements"                  │
│     │      │                                                        │
│     │      └── DocItem ──── mentions: [HANA, RAM, Linux]           │
│     │                                                               │
│     └── Section ──── scope: "Modules"                              │
│            │                                                        │
│            └── DocItem ──── mentions: [Finance, Logistics, HR]     │
│                                                                     │
│  Usage: Navigation, Filtrage, Recherche Anchored                   │
│  Traversable: NON                                                   │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 │ (ancrage, pas promotion)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ASSERTION LAYER (sparse)                       │
│                                                                     │
│  RawAssertion ───► CanonicalRelation ───► SemanticRelation         │
│                                                                     │
│  Seules les relations avec PREUVE LOCALE entrent ici:              │
│  - EXPLICIT: "A requires B" écrit en toutes lettres                │
│  - DISCURSIVE: Pattern détecté + concepts co-présents localement   │
│                                                                     │
│  Usage: Raisonnement, Traversée, Inférence contrôlée               │
│  Traversable: OUI (mode Reasoned)                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Conséquences sur les mécanismes existants

### 1. SCOPE Mining (recadrage)

Le SCOPE mining **ne doit pas** essayer de transformer tout scope en assertion.

| Situation | Traitement |
|-----------|------------|
| Concepts A et B dans la même phrase avec marqueur | ✅ Assertion (DISCURSIVE) |
| Concepts A et B dans la même section sans marqueur | ❌ Scope seulement |
| Concept A sous un titre "X Requirements" | ❌ Scope seulement |

Le garde-fou **BRIDGE** (INV-SCOPE-07) implémente déjà cette logique :
- Pas de bridge (A et B séparés) → ABSTAIN → reste en scope
- Bridge trouvé + marqueur validé → ASSERT → promu en assertion

**Le SCOPE mining est un filtre de candidats, pas un générateur d'assertions.**

### 2. Document Topic

Le sujet principal d'un document (`doc_topic`) est un **scope**, pas une assertion.

```python
# CORRECT : Scope
Document.topic = "SAP S/4HANA"  # Metadata de navigation

# INCORRECT : Ne pas créer
RawAssertion(
    subject="Finance Module",
    predicate="PART_OF",
    object="SAP S/4HANA",
    evidence="(implicite du contexte)"  # ❌ Pas de preuve locale
)
```

### 3. Listes et énumérations

Une liste sous un titre n'est **pas** une preuve de relation.

```
Section: "SAP S/4HANA Modules"
- Finance
- Logistics
- HR
```

| Interprétation | Type | Action |
|----------------|------|--------|
| "Cette section liste des modules" | Scope | ✅ Stocker comme metadata |
| "Finance PART_OF S/4HANA" | Assertion | ❌ Pas de preuve locale |

**Exception** : Si le texte dit explicitement "SAP S/4HANA includes the following modules:", alors la phrase introductive **est** une preuve et on peut créer une assertion avec `discursive_basis=[ENUMERATION]`.

### 4. Mode Anchored

Le mode Anchored exploite la **Scope Layer** pour retrouver les chunks pertinents :

```
Query: "What are S/4HANA requirements?"
        │
        ▼
┌─ Scope Layer ────────────────────────────────┐
│ Filter: doc.topic = "S/4HANA"                │
│ Filter: section.scope contains "requirement" │
│ → Chunks candidats                           │
└──────────────────────────────────────────────┘
        │
        ▼
┌─ Vector Search ──────────────────────────────┐
│ Embedding similarity sur les chunks filtrés  │
│ → Top-K résultats                            │
└──────────────────────────────────────────────┘
        │
        ▼
    Réponse avec citations
```

Le scope **guide** la recherche sans **affirmer** de relations.

### 5. Mode Reasoned

Le mode Reasoned traverse **uniquement** l'Assertion Layer :

```
Query: "What does SAP HANA require?"
        │
        ▼
┌─ Assertion Layer ────────────────────────────┐
│ MATCH (h:Concept {name: "SAP HANA"})         │
│       -[r:REQUIRES]-> (x)                    │
│ WHERE r.defensibility_tier = "STRICT"        │
│ → Relations prouvées                         │
└──────────────────────────────────────────────┘
        │
        ▼
    Réponse avec preuves citables
```

**Aucune relation de scope ne pollue le raisonnement.**

---

## Invariants (non négociables)

### INV-SEP-01 : No Scope-to-Assertion Promotion

> Un scope **ne peut jamais** être promu en assertion sans preuve textuelle locale.

Le contexte documentaire (titre, section, topic) n'est **pas** une preuve suffisante.

### INV-SEP-02 : Assertion Requires Local Evidence

> Toute assertion **doit** avoir un `EvidenceBundle` avec au moins un span où les concepts sont co-présents ou explicitement reliés.

"Implicite du contexte" n'est **pas** une evidence valide.

### INV-SEP-03 : Scope is Navigation, Not Reasoning

> La Scope Layer est utilisée pour **filtrer et naviguer**, jamais pour **inférer ou traverser**.

Un consommateur ne peut pas faire : "A est dans le scope de X, donc A est lié à X".

### INV-SEP-04 : Explicit Boundary

> La frontière entre Scope et Assertion **doit être explicite** dans le code et les données.

Pas de champ ambigu qui pourrait être interprété des deux façons.

---

## Implémentation

### Scope Layer (existant, à formaliser)

```python
class Document(BaseModel):
    document_id: str
    title: str
    topic: Optional[str]  # Scope: sujet principal extrait
    metadata: dict

class SectionContext(BaseModel):
    context_id: str
    doc_id: str
    title: str
    scope_description: Optional[str]  # Scope: de quoi parle cette section

class DocItem(BaseModel):
    item_id: str
    section_id: str
    text: str
    mentioned_concepts: List[str]  # Scope: concepts mentionnés (pas de relation)
```

### Assertion Layer (existant)

```python
class RawAssertion(BaseModel):
    raw_assertion_id: str
    subject_concept_id: str
    object_concept_id: str
    relation_type: RelationType
    evidence_bundle: EvidenceBundle  # OBLIGATOIRE
    assertion_kind: AssertionKind
    discursive_basis: List[DiscursiveBasis]
```

### Règle de validation

```python
def can_create_assertion(candidate: CandidatePair) -> bool:
    """
    Vérifie si un candidat peut devenir une assertion.

    INV-SEP-01 et INV-SEP-02 : preuve locale obligatoire.
    """
    bundle = candidate.evidence_bundle

    # Doit avoir au moins un span
    if not bundle.spans:
        return False

    # Pour DISCURSIVE, doit avoir un bridge (co-présence locale)
    if candidate.assertion_kind == AssertionKind.DISCURSIVE:
        if not bundle.has_bridge:
            return False

    # Pour EXPLICIT, le span doit contenir la relation
    if candidate.assertion_kind == AssertionKind.EXPLICIT:
        if not any(span.contains_relation for span in bundle.spans):
            return False

    return True
```

---

## Réponse au problème initial

### "Comment augmenter le taux de capture ?"

**Mauvaise question.** Le taux de capture des assertions doit rester faible car seules les relations prouvées y entrent.

### "Comment exploiter les 85% d'information contextuelle ?"

**Bonne question.** Via la Scope Layer + mode Anchored :

1. **Scope Layer** structure le contexte documentaire
2. **Mode Anchored** exploite ce contexte pour retrouver l'information
3. **Le graphe reste sparse** mais les réponses sont denses grâce à l'ancrage textuel

### Métaphore

> Le graphe sémantique est une **carte routière** : peu de routes, mais fiables.
>
> La scope layer est un **GPS avec satellite** : dense, mais guide sans affirmer.
>
> On utilise le GPS pour trouver où aller, la carte pour savoir quelles routes existent vraiment.

---

## Métriques de succès

| Métrique | Cible | Rationale |
|----------|-------|-----------|
| Taux d'assertions | 5-15% des relations potentielles | Sparse = fiable |
| Couverture scope | 90%+ des concepts mentionnés | Dense = navigable |
| FP Type 2 | 0% | Invariant absolu |
| Satisfaction navigation | ≥ 80% | L'utilisateur trouve l'info |

---

## Prochaines étapes

1. **Formaliser la Scope Layer** dans le schéma Neo4j
   - Ajouter `topic` sur Document
   - Ajouter `scope_description` sur SectionContext
   - Ajouter `mentioned_concepts` sur DocItem (sans relation)

2. **Enrichir le mode Anchored** pour exploiter le scope
   - Filtrage par topic/section avant recherche vectorielle
   - Scoring boosté par pertinence scope

3. **Documenter la frontière** pour les développeurs
   - Guide "Quand créer une assertion vs un scope"
   - Tests de validation de la séparation

4. **Mettre à jour le backlog discursif**
   - Recadrer SCOPE mining comme filtre de candidats
   - Abandonner l'objectif d'augmenter le taux de capture

---

## Dépendances bloquantes

Cet ADR **DOIT** être validé avant d'implémenter :

| Élément | Raison |
|---------|--------|
| Attribution `DefensibilityTier` | Dépend de la définition claire de ce qui est une assertion |
| Stratégie STRICT → EXTENDED → Anchored | L'escalade vers Anchored suppose que le scope existe |
| Runtime traversal `allowed_tiers` | Le filtrage suppose la séparation scope/assertion |
| Promotion rules MIXED/DISCURSIVE | Les règles dépendent de la définition d'assertion |
| ENUMERATION pattern | Recadré : scope sauf si phrase intro explicite |

### Ce qui peut avancer en parallèle

| Élément | Pourquoi |
|---------|----------|
| SCOPE mining (bridge detection) | Déjà aligné avec INV-SEP-01/02 |
| Patterns ALTERNATIVE/DEFAULT/EXCEPTION | Preuve locale requise = conforme |
| Fix techniques (canonical_id, etc.) | Infrastructure, pas sémantique |

---

## Proposition de valeur (narratif)

Pour les parties prenantes (clients, investisseurs, auditeurs) :

> **"OSMOSIS distingue explicitement ce qu'un document couvre de ce qu'il affirme.**
>
> **Le graphe de connaissances ne contient que des relations défendables** — chaque lien peut être justifié par une citation précise du texte source.
>
> **La navigation reste dense et exploitable** grâce à une couche de contexte documentaire séparée, qui permet de retrouver l'information sans inventer de relations.
>
> **Résultat : 0% de faux positifs sur les relations, 90%+ de couverture en navigation.**"

Cette séparation est notre **différenciation vs Copilot/Gemini** qui mélangent allègrement compréhension contextuelle et assertions factuelles.

---

## Références

- [ADR_DISCURSIVE_RELATIONS.md](./ADR_DISCURSIVE_RELATIONS.md) - Relations discursivement déterminées
- [ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md](./ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md) - SCOPE mining et bridge detection
- [ADR_DISCURSIVE_RELATIONS_BACKLOG.md](./ADR_DISCURSIVE_RELATIONS_BACKLOG.md) - Backlog implémentation
- Discussion avec ChatGPT - Analyse du paradoxe densité/exactitude
