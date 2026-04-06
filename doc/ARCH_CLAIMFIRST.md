# Architecture ClaimFirst OSMOSIS

> **Niveau de fiabilité** : Code-verified (Mars 2026). Le pipeline ClaimFirst est le mode actif en production. La Phase 8 (Qdrant) est branchée dans le code mais nécessite une ré-ingestion du corpus existant — voir annotation inline.

*Document consolidé — Mars 2026*

---

## 1. Philosophie ClaimFirst

Le pipeline ClaimFirst repose sur un **pivot épistémique** : OSMOSIS ne cherche pas la vérité universelle d'une assertion, mais son **applicabilité** dans un contexte documentaire donné.

**Principes fondateurs :**

- **INV-1** : La preuve d'une Claim est `unit_ids` (passages source), pas `passage_id`
- **INV-3** : Une Claim appartient à UN document (`doc_id` obligatoire)
- **INV-8** : Le scope d'applicabilité appartient au Document, pas à la Claim — les claims héritent du contexte par relation, sans universaliser
- **INV-9** : Résolution conservative des sujets — jamais d'auto-fusion sur simple embedding
- **INV-10** : Les discriminants de comparaison sont découverts, pas hardcodés

Une Claim ne dit pas "ceci est VRAI pour ce produit en général". Elle dit "ceci est DIT dans ce document, sous ces conditions d'applicabilité".

**Charte de la "bonne Claim" (non négociable) :**

1. Dit UNE chose précise
2. Supportée par passage(s) verbatim exact(s)
3. Jamais exhaustive par défaut
4. Contextuelle (scope, conditions, version)
5. N'infère rien (pas de déduction)
6. Comparable (compatible/contradictoire/disjointe)
7. Peut NE PAS exister si le document est vague
8. Révisable par addition, jamais par réécriture

---

## 2. Pipeline — Les 9 phases

Le pipeline est orchestré par `ClaimFirstOrchestrator` (`src/knowbase/claimfirst/orchestrator.py`). Voici les phases telles qu'implémentées dans le code :

### Phase 0 — Création des Passages

Transforme les `DocItems` du cache Pass0 en objets `Passage` avec leurs unités de texte.

### Phase 0.5 — Extraction DocumentContext & SubjectAnchors

- `ContextExtractor` extrait le contexte du document (sujets bruts, qualificateurs, type documentaire)
- `SubjectResolver` résout les sujets vers des `SubjectAnchor` canoniques
- Validation LLM des nouveaux sujets (Phase 0.5b, quality gate)

### Phase 0.55 — Résolution ComparableSubject

- `SubjectResolverV2` (INV-25 : Domain-Agnostic) résout le sujet comparable et classifie en `AXIS_VALUE` / `DOC_TYPE` / `NOISE`
- Propage le `doc_id` au `ComparableSubject`
- Met à jour le `resolution_status` du `DocumentContext`

### Phase 0.6 — Construction Applicability Frame

- Pipeline evidence-locked : `EvidenceUnitSegmenter` -> `CandidateMiner` -> `FrameBuilder` -> `FrameValidationPipeline` -> `FrameAdapter`
- Détecte les `ApplicabilityAxis` (axes de comparaison entre documents)
- Produit un `ApplicabilityFrame` avec champs typés et unknowns explicites

### Phase 1 — Extraction Claims (pointer mode, prompt V2)

- `ClaimExtractor` extrait les claims en mode pointeur (verbatim garanti, pas de reformulation)
- Enrichi par le contexte documentaire et le domaine

### Phase 1.4 à 1.7 — Quality Gates

- **1.4** : Gate Vérifiabilité (rejet fabrication, réécriture evidence)
- **1.5** : Déduplication déterministe (texte exact + triplet S/P/O)
- **1.6** : Filtrage qualité (short, boilerplate, heading-like)
- **1.6b-c** : Gates déterministes (tautologie, template leak) + Atomicity splitter
- **1.7** : Slot enrichment via `SlotEnricher` pour les claims sans `structured_form`

### Phase 2 — Extraction Entities

- `EntityExtractor` extrait les entités (NER enrichi : capitalisés répétés, headings, acronymes, patterns syntaxiques)
- **Phase 2.5** : `EntityCanonicalizer` fusionne les entités via LLM
- **Phase 2.6** : Independence resolver (résolution des dépendances entre claims)
- **Phase 2.7** : Marquage PASS sur les claims restantes
- **Phase 2.8** : Dérivation de `SubjectAnchors` depuis les entités canonicalisées
- **Phase 2.9** : `FacetCandidateExtractor` (1 appel LLM par doc) -> `FacetRegistry`

### Phase 3 — Facet Assignment

- `FacetMatcher` affecte les claims aux facettes validées
- Assignment déterministe à 4 signaux pondérés

### Phase 4 — Linking

- **Claim -> Passage** : `PassageLinker` (relation `SUPPORTED_BY`)
- **Claim -> Entity** : `EntityLinker` (relation `ABOUT`)
- **Phase 4.5** : Domain Pack Enrichment (entités et liens supplémentaires)
- **Phase 4.6** : Canonical Alias Resolution (renommage via aliases domain pack)

### Phase 5 — Clustering

- `ClaimClusterer` regroupe les claims similaires (embeddings + entities partagées)
- Création des liens Claim -> ClaimCluster

### Phase 6 — Détection Relations

- `RelationDetector` : relations value-level (`CONTRADICTS`) + regex (`REFINES`, `QUALIFIES`)
- **Phase 6.5** : `ChainDetector` détecte les chaînes compositionnelles S/P/O
- **Phase 6.6** : Extraction `QuestionSignatures` (Level A, regex, zero-cost)

### Phase 7 — Persistance Neo4j

- `ClaimPersister` persiste tous les artefacts : Passages, Claims, Entities, Facets, Clusters, Relations, SubjectAnchors, DocumentContext, ApplicabilityAxes
- Utilise `MERGE` pour l'idempotence

### Phase 8 — Persistance Qdrant Layer R

> **Statut : ACTIF — 22/28 docs re-ingeres (30 mars 2026).** Le code dans `orchestrator.py:638-865` utilise TypeAwareChunks + rechunker. La re-ingestion a ete effectuee : 7629 chunks dans Qdrant, median 957 chars, 0% sous 100 chars, 92% avec prefixe contextuel. 6 documents restent a ingerer. Voir `CHANTIER_CHUNKING.md` §7 pour les metriques completes.

**Comportement du code** (`_persist_type_aware_chunks_to_qdrant`, lignes 718-865) :
- **Si TypeAwareChunks presentes dans le cache** : rechunker (target ~1500 chars, overlap 200) + prefixe contextuel
- **Si absentes (legacy)** : fallback vers `_persist_chunks_to_qdrant()` avec Passages atomiques, MIN_CHARS=20

**Apres re-ingestion** (comportement cible) :
- PDF : TypeAwareChunks Docling + rechunker (target 1500 chars, overlap 200)
- PPTX : slides reconstruites (speaker notes + contenu visible)
- Prefixe contextuel deterministe : `doc_title | section_title | page N`

---

## 3. Facet Engine V2

> **Statut : CODE PRESENT, non branché dans le pipeline principal.** Les 5 modules (F1-F5) existent dans `src/knowbase/facets/` (2971 lignes) et sont fonctionnels, mais l'orchestrateur n'est appelé depuis aucun flux automatique. L'exécution se fait manuellement via `run_facet_engine_v2(driver, tenant_id="default")`. L'intégration dans le pipeline ClaimFirst et la navigation runtime sont des travaux restants (Sprint 3-4, voir `CHANTIER_KG_QUALITY.md`).

**Source** : `src/knowbase/facets/` + `src/knowbase/claimfirst/linkers/facet_registry.py`

### Diagnostic de l'approche V1

Le FacetMatcher V1 fait du keyword substring match : chaque facette a une liste de mots-clés, et chaque claim est matchée si elle contient un de ces mots. Résultat : 2% de couverture (326/15566 claims). Le problème est le modèle mental — on essaie du tagging lexical dans un système qui est fondamentalement information-first.

### Modèle V2 — Prototypes sémantiques

Les facettes ne sont plus définies par des mots-clés mais par des **prototypes composites** (embeddings) calculés à partir des informations représentatives.

**Formule du vecteur composite** (`FacetPrototype` dans `src/knowbase/facets/models.py`) :

```
composite = 0.25 * label_description_vector
          + 0.50 * prototype_claims_centroid
          + 0.15 * claimkey_centroid
          + 0.10 * theme_centroid
```

### Pipeline en 5 passes

Les modules sont implémentés dans `src/knowbase/facets/` :

| Passe | Module | Rôle |
|-------|--------|------|
| F1 | `bootstrap.py` | Extraction LLM (1 appel/doc) -> `FacetCandidate` |
| F2 | `normalizer.py` | Fusion/split/canonicalisation par clustering embedding |
| F3 | `prototype_builder.py` | Construction des prototypes composites + embeddings |
| F4 | `scorer.py` | Score multi-signal pour assignment |
| F5 | `governance.py` | Métriques santé + alertes merge/split |

### Score d'assignment (Passe F4)

```
global_score = 0.55 * semantic_similarity(info_vector, facet_vector)
             + 0.20 * theme_alignment_score
             + 0.15 * claimkey_alignment_score
             + 0.10 * structural_cohesion_score

Si global_score >= 0.82 et semantic >= 0.75 -> STRONG
Si global_score >= 0.68                     -> WEAK
Sinon                                       -> pas de lien
```

### Lifecycle gouverné (FacetRegistry)

Le `FacetRegistry` (`src/knowbase/claimfirst/linkers/facet_registry.py`) gère le lifecycle :

- **candidate** : facette découverte, pas encore validée
- **validated** : promue à >= 3 documents + diversité minimale des sources (>= 2 titres distincts)
- **deprecated** : action admin manuelle

Near-duplicates détectés (Levenshtein <= 3 + keywords overlap >= 0.6) mais **PAS** mergés automatiquement (INV-9).

### Familles de facettes

Définies dans `src/knowbase/claimfirst/models/facet.py` :

- `thematic` : de quoi parle le document (domaine métier)
- `normative` : obligations, conformité, régulation
- `operational` : opérations, SLA, backup, monitoring

---

## 4. Marker Normalization

**Statut** : Implémenté (100%), janvier 2026.

### Architecture en couches

```
[Extraction agnostique]
         |
         v
   MarkerMention (raw)      -> Ce qui est ÉCRIT dans le document
         |
         v
[Normalization Layer]        <- Config Tenant (aliases, rules)
         |
         v
   CanonicalMarker           -> Forme normalisée structurée
```

**Code** : `src/knowbase/consolidation/normalization/`

| Fichier | Rôle |
|---------|------|
| `models.py` | `MarkerMention`, `CanonicalMarker`, `NormalizationRule` |
| `normalization_store.py` | CRUD Neo4j, stats, clustering |
| `normalization_engine.py` | Moteur de règles + Entity Anchor detection |

### Principes non négociables

- **Safe-by-default** : si normalisation incertaine, le marker reste `UNRESOLVED`
- **Entity Anchor obligatoire** pour les markers ambigus (années seules)
- **Pas de domain-specific dans le moteur** : les exemples SAP sont purement illustratifs
- La normalisation augmente la **cohérence**, pas le recall. Un marker non-normalisé est acceptable, un marker mal-normalisé est toxique.

### API REST complète

- `GET /markers/normalization/suggestions` : suggestions de normalisation
- `POST /markers/normalization/apply` : application manuelle
- `GET/POST/DELETE /markers/normalization/aliases` : CRUD aliases
- `POST /markers/normalization/blacklist` : ajout à la blacklist
- `GET /markers/normalization/stats` : statistiques (taux résolution)
- `GET /markers/normalization/clusters` : clustering suggestions

---

## 5. Corpus Promotion (Pass 2.0)

**Source** : `src/knowbase/consolidation/corpus_promotion.py`

### Problème résolu

L'ancienne promotion (Pass 1) était per-document : les concepts n'apparaissant qu'une fois par document mais dans plusieurs documents distincts n'étaient jamais promus. Résultat : 46 concepts cross-doc orphelins.

### Décision : Single-Stage via lex_key

Toute la promotion est centralisée en Pass 2.0. La Pass 1 ne crée **jamais** de `CanonicalConcept`.

**Normalisation** : La fonction `compute_lex_key()` (`src/knowbase/consolidation/lex_utils.py`) produit une clé technique canonique :

1. Lowercase
2. Unicode NFKD (supprime accents)
3. Remove punctuation
4. Normalize whitespace
5. Light singularization (EN/FR)

Exemple : `"SAP S/4HANA"` -> `"sap s 4hana"`

### Règles de promotion unifiées

| Règle | Condition | Stabilité |
|-------|-----------|-----------|
| Multi-occurrence doc | `doc_count >= 2` dans même document | STABLE |
| Multi-section | `section_count >= 2` sections différentes | STABLE |
| Multi-document | `corpus_count >= 1` + signal minimal | STABLE |
| Singleton high-signal | `doc_count == 1` + high-signal V2 | SINGLETON |

**Signal minimal cross-doc** (au moins un) :
- `anchor_status = SPAN` (preuve textuelle localisée)
- `role in {definition, constraint}` (rôle structurant)
- `confidence >= 0.7` (score d'extraction suffisant)

### Type Guard Soft

Pour éviter les faux positifs homonymes : si un type domine à >= 70% dans un bucket `lex_key`, on garde ensemble. Sinon, split par type pour les labels courts/acronymes, ou flag `type_conflict=true`.

---

## 6. ApplicabilityAxis

**Source** : `src/knowbase/claimfirst/models/applicability_axis.py`, `src/knowbase/claimfirst/axes/`

### Design V2.1

Les axes d'applicabilité sont les dimensions selon lesquelles on peut comparer des documents entre eux (version produit, édition, région, etc.). Ils sont **découverts** par le pipeline, pas hardcodés.

### Composants implémentés

- `ApplicabilityAxisDetector` : LLM-first extraction (INV-25 Domain Agnosticism)
- `AxisOrderInferrer` : inférence de l'ordre des valeurs
- `AxisValueValidator` : pattern Extract-then-Validate

### OrderType & OrderingConfidence

Les axes ont une confiance d'ordonnancement :
- `CERTAIN` : ordre vérifié (ex: années)
- `INFERRED` : ordre inféré par LLM
- `UNKNOWN` : impossible à ordonner

### Persistence structurée (V2.1)

Les `AxisValue` sont persistées avec types structurés dans Neo4j :

```
(DocumentContext)-[:HAS_AXIS_VALUE {
    value_type: "scalar" | "range" | "set",
    scalar_value, range_min, range_max, set_values
}]->(ApplicabilityAxis)
```

### Bug connu : année non propagée

La cause racine identifiée de `ApplicabilityAxis = 0` dans certains documents :

1. `ContextExtractor` ne propage pas l'année/version vers les `qualifiers` du `DocumentContext`
2. Le `full_text` contient le titre complet (ex: "Security Guide for SAP S/4HANA 2023") mais le titre passé au resolver est tronqué
3. `SubjectResolverV2` s'abstient faute de candidats avec version
4. `FrameBuilder` reçoit un prompt ultra-restrictif et produit 0 fields

**Fix identifié** : extraire le titre complet du `full_text` (premiers passages) et le passer comme candidat.

---

## 7. CanonicalClaim (unaires)

**Source** : `doc/archive/pre-rationalization-2026-03/specs/graph/SPEC-PHASE2.11_CANONICAL_CLAIMS_MIN_SPEC.md`

**Statut** : Spécification Draft (non implémentée). Le pipeline actuel utilise le modèle `Claim` de ClaimFirst.

### Pattern 2-Layer

```
Layer 1 — EXTRACTION
  Document -> LLM -> RawClaim (assertion unaire brute)
  - 1 RawClaim par mention, scope_raw texte libre
  - flags: negated, hedged, conditional, ambiguous_scope

Layer 2 — CONSOLIDATION
  RawClaims -> Groupement par (subject, claim_type, scope_key) -> CanonicalClaim
  - scope_struct = parsing structuré
  - Détection: refines / conflicts / supersedes
  - Maturity: VALIDATED / CANDIDATE / CONFLICTING / CONTEXT_DEPENDENT / SUPERSEDED
```

### Scope Parsing & Conflict Detection

Claims groupées par `(subject_concept_id, claim_type, scope_key)`. Le `scope_key` est un hash canonique du `scope_struct` normalisé.

Relations entre claims :
- **Même scope, même valeur** : `DUPLICATE` (fusion)
- **Même scope, valeur différente** : `CONFLICTS`
- **Scope enfant** : `REFINES` (B précise A)
- **Scopes disjoints** : `COEXIST` (variants indépendants)
- **Temporel, même scope** : `SUPERSEDES` (succession)

---

## 8. Modèles de données

### Claim (`src/knowbase/claimfirst/models/claim.py`)

- `ClaimType` : FACTUAL, PRESCRIPTIVE, DEFINITIONAL, CONDITIONAL, PERMISSIVE, PROCEDURAL
- `ClaimScope` : version, region, edition, conditions[]
- `Claim` : claim_id, doc_id, text, passage_id, unit_ids, structured_form, cluster_id, etc.

### Entity (`src/knowbase/claimfirst/models/entity.py`)

- `EntityType` : PRODUCT, SERVICE, FEATURE, ACTOR, CONCEPT, LEGAL_TERM
- INV-4 : Entity sans rôle structurant en V1, pas de primary/secondary
- INV-5 : EntityExtractor enrichi (NER + capitalisés + headings + acronymes + patterns)

### Facet (`src/knowbase/claimfirst/models/facet.py`)

- `FacetFamily` : thematic, normative, operational
- `FacetLifecycle` : candidate -> validated -> deprecated
- Facet V2 (`src/knowbase/facets/models.py`) : `FacetCandidate`, `FacetPrototype`, `FacetAssignment`, `FacetHealth`, `Facet`

### DocumentContext (`src/knowbase/claimfirst/models/document_context.py`)

- INV-8 : Le scope appartient au Document, pas à la Claim
- `ResolutionStatus` : RESOLVED, LOW_CONFIDENCE, AMBIGUOUS, UNRESOLVED
- Schéma Neo4j : `(Document)-[:HAS_CONTEXT]->(DocumentContext)-[:ABOUT_SUBJECT]->(SubjectAnchor)`

### SubjectAnchor (`src/knowbase/claimfirst/models/subject_anchor.py`)

- INV-9 : Conservative Subject Resolution
- `AliasSource` : EXPLICIT (fort), INFERRED (faible), LEARNED (moyen)
- Ordre de résolution strict : exact match -> normalisation -> aliases learned -> soft embedding (candidat seulement) -> création nouveau

---

## 9. Pistes écartées & travaux non terminés

### Pistes écartées

| Piste | Raison du rejet |
|-------|-----------------|
| Promotion two-stage (Pass 1 + Pass 4.5) | Les concepts promus tardivement ratent Pass 2 et 3 |
| Gating NER seul (sans LLM Arbiter) | Insuffisant pour les cas ambigus Named-Named |
| TF-IDF divergence comme règle dure | Trop de faux positifs — conservé uniquement comme signal |
| Facettes par keywords (V1) | 2% de couverture, modèle mental inadapté |
| Tout au LLM pour coréférences | Coût prohibitif, non scalable |

### Travaux non terminés

| Travail | Statut |
|---------|--------|
| FacetEngine V2 complet (F1-F5) | Modules créés (`src/knowbase/facets/`), orchestration à terminer |
| CanonicalClaim (Layer 2 consolidation) | Spec draft, non implémenté |
| NamedNamedGatingPolicy (coréf Named-Named) | ADR validé, implémentation non commencée |
| Layer P (Precision) dans Qdrant | Architecture définie, non implémenté |
| Coréférence avec LLM Arbiter | ADR validé, non implémenté |
| ApplicabilityAxis bug year propagation | Diagnostic complet, fix identifié mais non appliqué |

---

## 10. Références archive

Les documents sources de cette consolidation sont archivés dans `doc/archive/pre-rationalization-2026-03/` :

| Document archivé | Section couverte |
|-------------------|-----------------|
| `ongoing/ADR_FACET_ENGINE_V2.md` | Section 3 (Facet Engine V2) |
| `adr/ADR-20250105-marker-normalization-layer.md` | Section 4 (Marker Normalization) |
| `adr/ADR_COREF_NAMED_NAMED_VALIDATION.md` | Section 9 (piste validée, non implémentée) |
| `ongoing/APPLICABILITY_AXIS_DESIGN_V2.1.md` | Section 6 (ApplicabilityAxis) |
| `adr/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md` | Section 5 (lex_key) |
| `adr/ADR_UNIFIED_CORPUS_PROMOTION.md` | Section 5 (Corpus Promotion) |
| `specs/graph/SPEC-PHASE2.11_CANONICAL_CLAIMS_MIN_SPEC.md` | Section 7 (CanonicalClaim) |
