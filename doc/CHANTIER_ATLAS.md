# Chantier Atlas & Wiki OSMOSIS

**Statut** : Design valide, implementation non demarree (prerequis : chunking + benchmark)
**Derniere mise a jour** : 29 mars 2026
**Sources archivees** : `doc/archive/pre-rationalization-2026-03/ongoing/ADR_ATLAS_EVOLUTION.md`, `WIKI_OSMOSIS_CONCEPT_ASSEMBLY_ENGINE.md`, `WIKI_OSMOSIS_PROJECT_PRESCRIPTION.md`, `ADR_FACET_ENGINE_V2.md`

---

## 1. Vision Atlas cognitif

### Posture produit

L'Atlas ne vise pas "un meilleur RAG + un meilleur wiki". Il vise :

> **Un systeme qui comprend le corpus mieux que l'utilisateur.**

Chaque phase pousse vers cette posture :
- Phase 1 : "je te guide vers ce que tu cherches" (convergence)
- Phase 2 : "je te montre ce que tu ne sais pas que tu ne sais pas" (orientation + blind spots)
- Phase 3 : "je prends l'initiative cognitive pour toi" (guidance active)

### Les 3 phases

| Phase | Quoi | Posture | Effort |
|-------|------|---------|--------|
| **1** | Chat <-> Atlas + insights + articles enrichis | Reactive intelligente | 2-3 jours |
| **2** | Homepage orientante + pages facettes + blind spots + reading paths | Orientante + alertante | 4-6 jours |
| **3** | Synthese LLM, thematic views, guidance active, articles vivants | Cognitive proactive | A evaluer |

### Phase 1 — Convergence Chat <-> Atlas (immediat)

**1a. Chat → Atlas ("Explorer ce sujet")**

Apres chaque reponse du Chat, un bloc propose les 3 meilleurs articles Atlas lies. Algorithme : extraire les concepts detectes dans la question + reponse, filtrer `has_article = true` dans Neo4j, trier par `importance_score DESC`, limiter a 3 articles.

**1b. Atlas → Chat ("Poser une question")**

Sur chaque page article `/wiki/[slug]`, un bouton ouvre le Chat pre-rempli avec le concept.

**1c. Articles enrichis via chunk_context**

Le `chunk_context` (deja implemente dans le Bridge) est utilise dans le `constrained_generator` pour que le LLM de generation ait du contexte documentaire long.

**1d. Insight Hints dans le Chat**

Apres la reponse, un bloc optionnel d'insights cognitifs (100% deterministe, pas de LLM) :
- Contradictions : `CONTRADICTS` relations sur les claims de la reponse
- Concepts lies manquants : `related_concepts` non mentionnes dans la question
- Couverture : `doc_count` faible sur les entites de la reponse
- Max 3 insights, rien si rien de saillant

**Pourquoi c'est un game changer** : le systeme passe de "je reponds a ta question" a "je t'aide a penser le sujet". L'utilisateur decouvre ce qu'il ne savait pas qu'il ne savait pas.

### Phase 2 — Orientation du corpus (court terme)

**2a. Homepage Atlas refondee**

La page `/wiki` passe de "classification par facettes" a "orientation intelligible" :
- Stats corpus (documents, claims, entites)
- Domaines principaux (bases sur les facettes validees)
- Concepts structurants (Tier 1)
- Couverture et contradictions detectees

**2b. Blind Spots & Risques ("Zones a surveiller")**

Un bloc d'alertes structurelles (deterministe) :
- Contradictions elevees par facette
- Couverture faible (facettes avec `doc_count < 3`)
- Dependance source unique (1 document contribue > 60% des claims)
- Concepts importants sans article

**2c. Reading Paths**

Sur chaque article, un chemin de lecture suggere (3-5 concepts, tries par importance + lien semantique, generaux d'abord, specifiques ensuite).

### Phase 3 — Atlas cognitif (moyen/long terme)

- Corpus Summary (synthese LLM contrainte par donnees structurees, persistee)
- Thematic Views (parcours par intention utilisateur, pas par facette)
- Exploration cross-concept (graphe interactif, timeline, vue contradictions)
- Articles vivants (versioning, detection de stale, suggestions de regeneration)
- Proactive insights ("Vu votre historique, vous devriez regarder X")

---

## 2. Concept Assembly Engine

### Architecture : pipeline en 4 briques

```
┌─────────────────────────────────────────────────────────┐
│                  CONCEPT ASSEMBLY ENGINE                  │
│                                                          │
│  Brique 1         Brique 2         Brique 3    Brique 4 │
│  Concept    ──>   Evidence    ──>  Section  ──> Constr.  │
│  Resolver         Pack Builder     Planner      Generator│
│  (Neo4j)          (Neo4j+Qdrant)   (KG-driven)  (LLM)   │
└─────────────────────────────────────────────────────────┘
```

### Brique 1 — Concept Resolver

A partir d'un nom de concept ou entity_id, rassembler toutes les metadonnees structurelles depuis Neo4j :
- Entity canonique + aliases
- Claims lies (count, types : FACTUAL, PRESCRIPTIVE, ...)
- Couverture documentaire (doc_ids, doc_count, titres)
- Facettes liees
- Relations structurelles (CHAINS_TO, entites co-mentionnees)
- Axes temporels (release_id, versions)

**Pivot d'adressage** : `Entity` (2198 noeuds, directement lie aux Claims via ABOUT). Les `SubjectAnchor` (131) et `ComparableSubject` (62) servent au scope, pas comme pivot article. A terme, `CanonicalEntity` deviendra le pivot de niveau superieur.

### Brique 2 — Evidence Pack Builder

Pour chaque claim, recuperer le contexte textuel depuis Qdrant via le Claim-Chunk Bridge. Le KG **decide** de quoi l'article doit parler, Qdrant **fournit** la matiere pour bien l'exprimer.

Output : un `EvidencePack` contenant claims + chunks contextuels + metadata documentaire.

### Brique 3 — Section Planner

A partir du `ResolvedConcept` et de l'`EvidencePack`, planifier les sections de l'article :
- Sections derivees de la structure du KG (types de claims, facettes, axes temporels)
- Sections pour contradictions (si tensions detectees)
- Sections pour evolution temporelle (si axes multiples)

### Brique 4 — Constrained Generator

LLM ancre qui redige sous contraintes strictes :
- Citations obligatoires (chaque phrase tracable a un DocItem)
- Pas d'invention (tout doit venir de l'EvidencePack)
- Le chunk_context enrichit la generation sans violer l'invariant

### Modele hybride

```
KG  → delimitation du sujet + selection des preuves + structure + gouvernance
Qdrant → recuperation du contexte textuel pertinent
KG + Qdrant → article genere sous contraintes de provenance
```

---

## 3. Facet Engine V2 pour navigation

### Diagnostic du systeme actuel

Le FacetMatcher V1 fait du keyword substring match : chaque facette a une liste de mots-cles. Resultat : **2% de couverture** (326/15566 claims). La facette "Security" n'a que 8 keywords alors que le Security Guide utilise des centaines de termes techniques.

### Probleme fondamental

On essaie de faire du tagging lexical dans un systeme information-first. Cela viole :
1. Addressability-first : une facette basee sur des mots-cles n'est pas un pivot structurant fiable
2. LLM = extracteur, pas classifieur : le matching substring est du bottom-up naif
3. Lecture stratifiee : on fait texte → mot → facette au lieu de information → sens → facette

### Decision : Facet = pole de regroupement semantique

Remplacer `Facet = {nom + keywords[]}` par `Facet = pole semantique` base sur des prototypes composites (embeddings).

### Pipeline FacetEngine V2

| Pass | Nom | Description |
|------|-----|-------------|
| F1 | Facet Bootstrap | LLM (1 call/doc) : extraire FacetCandidates (label + description, SANS keywords) |
| F2 | Facet Normalization | Dedupliquer les facettes proches (embedding clustering + arbitrage LLM) |
| F3 | Prototype Build | Vecteur composite : 50% centroid Informations + 25% label + 15% ClaimKeys + 10% Themes |
| F4 | Assignment multi-signal | Score global >= 0.82 → STRONG, >= 0.68 → WEAK, sinon pas de lien |
| F5 | Governance | Metriques de sante, merge/split candidates, drift alerts |

### Scoring multi-signal (Pass F4)

```
global_score =
  0.55 * semantic_similarity(info_vector, facet_vector) +
  0.20 * theme_alignment_score +
  0.15 * claimkey_alignment_score +
  0.10 * structural_cohesion_score
```

### Invariants

1. Aucune facette ne depend d'une liste de termes metier
2. Pas de matching par taxonomie fermee
3. Le label n'est qu'une facade lisible — le coeur est le prototype composite
4. Les facettes sont des surfaces d'organisation, pas des verites
5. STRONG vs WEAK comme gouvernance, pas comme verite

---

## 4. Wikipedia OSMOSIS (vision long terme)

### Differenciation vs Wikipedia classique

| Aspect | Wikipedia Public | Wikipedia OSMOSIS |
|--------|------------------|-------------------|
| Source | Edition manuelle | Extraction automatique depuis documents |
| Mise a jour | Contributeurs humains | Pipeline d'ingestion + detection de changements |
| Coherence | Moderation humaine | Detection automatique contradictions |
| Provenance | Citations manuelles | Evidence locking sur DocItem + bbox |
| Temporalite | Historique versions | Timeline bi-temporelle (valid_time + transaction_time) |

### Principes non-negociables

1. **Graph-First Architecture** : le KG est la source de verite, Wikipedia est une vue generee dynamiquement
2. **Evidence-Locked Content** : chaque affirmation tracable a un DocItem source
3. **Dual Source of Truth** : Couche 1 = contenu extrait (read-only), Couche 2 = annotations utilisateurs (editable, versionee)
4. **Temporal Awareness** : afficher QUAND une information etait valide, pas seulement CE QUI est dit

### Invariants du projet Wiki

| ID | Invariant |
|----|-----------|
| INV-W1 | Tout article correspond a un concept dans Neo4j |
| INV-W2 | Toute section a >= 1 DocItem source |
| INV-W3 | Les editions utilisateurs ne modifient jamais le contenu source |
| INV-W4 | L'historique conserve toutes les versions (soft delete) |
| INV-W5 | Chaque lien inter-articles reflete une relation Neo4j existante |

---

## 5. Travaux non termines

### Phase 1 — Convergence Chat <-> Atlas (2-3 jours)

- Ajouter `related_articles` dans la reponse API du Chat
- Bloc frontend "Explorer ce sujet" (max 3 articles, icone boussole)
- Bouton "Poser une question" sur chaque page article
- Insight Hints (3 max, deterministes, cliquables)
- Articles enrichis via chunk_context dans le constrained_generator
- **Prerequis** : benchmark chunking termine (chunks exploitables)

### Phase 2 — Orientation du corpus (4-6 jours)

- Homepage Atlas refondee (stats + domaines + concepts Tier 1)
- Pages facettes enrichies (`/wiki/domain/[facet_key]`)
- Blind Spots & Risques (alertes structurelles)
- Reading Paths (chemin de lecture par article)
- Suggestions croisees (articles lies, questions frequentes)
- **Prerequis** : FacetEngine V2 implemente

### POC Concept Assembly Engine

- Implementer les 4 briques sur un sous-ensemble du corpus (5 entites)
- Valider la qualite des articles generes (tracabilite, exactitude, couverture)
- **Prerequis** : canonicalisation entites (Chantier KG Quality C1)

### FacetEngine V2

```
src/knowbase/facets/
  models.py              # Facet, FacetCandidate, FacetPrototype, FacetAssignment
  bootstrap.py           # Pass F1 : extraction LLM
  normalizer.py          # Pass F2 : fusion/split/canonicalisation
  prototype_builder.py   # Pass F3 : prototypes composites + embeddings
  scorer.py              # Pass F4 : score multi-signal
  assigner.py            # Pass F4 : creation relations
  governance.py          # Pass F5 : metriques sante + alertes
  orchestrator.py        # Pipeline complet
```

Plan de migration en 4 sprints :
1. Assignment par embeddings
2. Signaux enrichis (Theme → Facet, ClaimKey → Facet)
3. Gouvernance (weak/strong, health metrics, merge/split)
4. Navigation (brancher l'UI)

---

## 6. Metriques de succes

### Phase 1
- % de reponses Chat avec articles lies : > 60%
- Taux de clic "Explorer ce sujet" : > 15%

### Phase 2
- Temps moyen avant premier clic (homepage) : < 10s
- % d'utilisateurs explorant > 3 pages : > 40%

### Phase 3
- Score de satisfaction sur la comprehension du corpus
- % de questions Chat auxquelles un article existant contribue
