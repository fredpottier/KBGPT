# Analyse POC Composer Cross-Document

**Date :** 2026-02-06
**Contexte :** Évaluation d'un pivot architectural après v1.6.0 (Claim-First)
**Participants :** Analyse croisée Claude + ChatGPT

---

## 1. Problème identifié

L'approche Claim-First (v1.6.0) est **fonctionnellement robuste** mais **intellectuellement limitée** :
- Elle produit des faits défendables (claims avec evidence verbatim)
- Mais elle ne fait pas émerger de **connaissance structurée** (graphe de concepts liés)
- Le lien `Claim → ABOUT → Entity` est sémantiquement plat (pas de prédicat typé)
- Le graphe résultant est une topologie en étoile (entity → claims), pas un réseau navigable

**Ambition :** Après l'ingestion de N documents, pouvoir comprendre ce qu'est la connaissance d'une entreprise uniquement via l'analyse de ses docs, sans apprentissage préalable.

---

## 2. Historique des approches tentées (5 pivots)

| # | Approche | Dates | Résultat | Cause d'échec |
|---|----------|-------|----------|---------------|
| 1 | SAP KB — Basic RAG | 2024 | Pas de concept extraction | Pas pertinent |
| 2 | KnowWhere — Narrative/Semantic | Oct 2024 | Abandonné | Over-engineering, regex English-only |
| 3 | V1 — Bottom-up Pure + Gatekeeper | Oct-Nov 2025 | Échec | ~4700 nodes/doc, 2% relations, duplication massive |
| 4 | V2.1 — Top-down Pure (Stratified) | Jan 2026 | Échec | Concepts "hors-sol", 34% SINK, 37% concepts vides |
| 5 | V2.2 — Hybrid Extract-then-Structure | Fév 2026 | En pause | Résultats similaires à V2.1 en pratique |
| 6 | Claim-First | Fév 2026 | **v1.6.0** | Fonctionne mais pas de graphe de connaissance |

### Patterns qui ont échoué (à ne pas recycler)

- **Concept Registry / Taxonomie top-down** (V2.1) : Le LLM invente des catégories "hors-sol" depuis une GlobalView compressée
- **Proto-Concept → Canonical Concept via Gatekeeper** (V1) : Circuit breaker LLM → fallback naïf → 8 variantes S/4HANA
- **Promotion par fréquence** (V1) : "SAP" apparaît 500 fois → fréquent, pas informatif
- **Canonicalisation globale précoce** (V1) : Ambiguïté insoluble sur des tokens isolés
- **Budget seul comme solution** (V2.1, V2.2) : Le budget contrôle la quantité, pas la qualité

### Anti-patterns documentés (`OSMOSIS_PROJECT_HISTORY.md`)

1. Concept-focused chunks (organiser les chunks autour de concepts au lieu de la structure du doc)
2. Graphiti pour les faits (text-in-edges vs entités structurées)
3. Linearization comme source de vérité
4. Retrieval-first RAG
5. Per-document promotion (vs corpus-level)

---

## 3. Proposition initiale ChatGPT : "Éditeur de connaissance sous contrainte"

### Éléments proposés

1. **Global View normative** → Subject + Themes + Concept Registry (40-80 concepts)
2. **Traitement par chunks guidé** → 3-6 concepts activés par passage, 0-3 relations
3. **Relations EXPLICIT vs SCOPE_DERIVED** → statut épistémique sur chaque edge
4. **Budgets stricts** → cap dur à 80 concepts/doc
5. **Concept lifecycle** : CANDIDATE → PROMOTABLE → REGISTRY
6. **Séparation Graphe / Qdrant** pour la traçabilité

### Verdict Claude : ~70% de recyclage

| Élément proposé | Équivalent historique | Résultat passé |
|----------------|----------------------|----------------|
| Concept Registry | Taxonomie V2.1 | Concepts hors-sol, 37% vides |
| CANDIDATE → PROMOTABLE → REGISTRY | Gatekeeper V1 | Circuit breaker, duplication |
| Budget adaptatif | validation_gate.py V2.2 | Déjà implémenté |
| GlobalView normative | Pass 0.9 top-down V2.1 | Catégories qui ne matchent pas le contenu |

### Ce qui EST nouveau (les 30% intéressants)

- **EXPLICIT / SCOPE_DERIVED** : Aucune approche précédente ne typait les relations par statut épistémique
- **LLM comme "éditeur"** vs extracteur : Reframing juste mais le mécanisme sous-jacent reste similaire
- **Séparation Graphe/Qdrant** : Bonne décision d'architecture, pas un changement de paradigme

---

## 4. Contre-proposition : Le Composer cross-document

### Insight clé (convergence Claude + ChatGPT)

> Le levier disruptif n'est pas "comment extraire mieux dans UN doc".
> C'est "comment faire émerger de la connaissance ENTRE les docs, par composition contrôlée."

**Exemple concret :**
- Doc A : "S/4HANA utilise SAP BTP IAS pour l'authentification"
- Doc B : "SAP BTP IAS nécessite un Identity Provider SAML 2.0"
- Doc C : "Notre entreprise utilise Azure AD comme Identity Provider"
- **Connaissance émergente** : "S/4HANA s'authentifie via BTP IAS qui repose sur Azure AD en SAML 2.0"

Aucun document ne dit ça. C'est le graphe qui le révèle par transitivité.

### Architecture proposée

```
Couche 1 — Claim-First (v1.6.0, inchangé)
    Claims bien formées + evidence verbatim + métadonnées
    = socle de vérité documentaire

Couche 2 — Slot Enrichment (NOUVEAU)
    Claim → {subject, predicate, object, qualifiers}
    LLM borné sur une claim individuelle, auditable

Couche 3 — Join Index (déterministe, pas de LLM)
    Jointure sur (object.normalized ≈ subject.normalized)
    Guidée par le prédicat (USES→object ↔ REQUIRES→subject)

Couche 4 — Composer (LLM pour reformulation uniquement)
    Reformulation lisible des chaînes
    Signalement des trous
    Canonicalisation locale par chaîne (pas globale)
```

### Triplet épistémique

| Type | Origine | Exemple |
|------|---------|---------|
| EXPLICIT | Citation verbatim dans un document | "S/4HANA uses BTP IAS" |
| SCOPE_DERIVED | Attribution contextuelle contrôlée | Section auth → produit S/4HANA |
| DERIVED_BY_COMPOSITION | Composition multi-claims multi-docs | Chaîne A+B+C |

### Résolution du chicken-and-egg (canonicalisation)

**Problème V1 :** Canonicaliser des entités globalement → ambiguïté insoluble ("IAS" = "SAP BTP Identity Authentication Service" ?)

**Solution Composer :**
> On ne canonicalise pas des entités. On canonicalise des **rôles dans des relations**.

Pipeline :
1. Slot enrichment d'abord (pas de canonicalisation)
2. Join déterministe ensuite (normalized_name exact, puis fuzzy embedding > 0.90)
3. Canonicalisation locale **uniquement** quand une jointure est nécessaire, **scoped à la chaîne**

→ Pas de canonicalisation globale prématurée. La fusion cross-chaîne se fait a posteriori, prudemment.

---

## 5. Test de composabilité — Données réelles (30 claims)

### Méthode

30 claims extraites de Neo4j (3 docs S/4HANA), filtrées sur verbes relationnels (`uses`, `requires`, `supports`, `enables`, `based on`, `replaces`, `embedded`, etc.).

### Résultats

**Catégorie A — Triplet (S, P, O) clair et composable (~23%) :**

| Claim | S | P | O |
|-------|---|---|---|
| SAP NetWeaver App Server supports SSO with logon tickets | SAP NetWeaver AS | SUPPORTS | SSO |
| ILM enables decommissioning by transferring data to ILM Retention Warehouse | ILM | ENABLES | Legacy decommissioning |
| Material Ledger replaces traditional SAP Inventory Management | Material Ledger | REPLACES | SAP Inventory Management |
| The JIT process is based on sales scheduling agreements | JIT process | BASED_ON | Sales scheduling agreements |
| Actual Costing is based on Material Ledger | Actual Costing | BASED_ON | Material Ledger |
| The Consolidation application is embedded in SAP S/4HANA | Consolidation | EMBEDDED_IN | SAP S/4HANA |
| Advanced TM processes embedded in SAP S/4HANA | Advanced TM | EMBEDDED_IN | SAP S/4HANA |

**Catégorie B — Triplet extraible mais objet générique (~33%) :**

| Claim | Problème |
|-------|----------|
| Enterprise Search provides secure real-time access to enterprise data | `object` = "enterprise data" → trop générique |
| Credit Management provides credit scoring based on historical data | `object` = "historical data" → pas joinable |
| Master data supports transactional processes | Tautologique |
| eSPP provides planning functions specific to service parts | `object` = "planning functions" → pas composable |

**Catégorie C — Pas de triplet composable (~43%) :**

| Claim | Raison |
|-------|--------|
| Statutory reports can be preconfigured with relevant data | Pas de relation inter-artefact |
| You can maintain price change reasons when... | Procédural, pas relationnel |
| If a buyoff cycle has been assigned... | Conditionnelle interne |
| You can evaluate the amount of damage... | Procédural |

### Tableau récapitulatif

| Catégorie | % | Composable ? |
|-----------|---|-------------|
| A — Triplet net et composable | ~23% | **Oui** |
| B — Triplet mais objet générique | ~33% | Faiblement |
| C — Pas de triplet | ~43% | Non |

### Projection sur les 3 docs

- ~3500 claims totales dans Neo4j
- ~23% composables = **~800 claims** avec triplet (S, P, O) exploitable
- Estimation : **50-100 chaînes de longueur ≥ 2** possibles sur 3 docs

---

## 6. Conclusions

### Le Composer est viable comme couche de valorisation

- Il ne remplace PAS le claim-first (qui reste la fondation pour 77% des claims non-composables)
- Il ajoute une couche de **connaissance structurée** au-dessus du socle factuel
- Le claim-first continue à servir via Qdrant/RAG classique

### Le seuil go/no-go de ChatGPT (40-50%) n'est pas atteint

- 23% de claims réellement composables < seuil de 40%
- Mais sur ~3500 claims, 800 claims composables suffisent pour un POC démonstratif
- La question est : ces 800 claims produisent-elles des chaînes **intéressantes** ?

### Ce qui NE change PAS

- Pipeline Claim-First v1.6.0 (inchangé)
- Persistance Neo4j + Qdrant (inchangée)
- Evidence-locked ApplicabilityFrame (inchangé)

### Ce qui serait AJOUTÉ

- Slot enrichment sur claims existantes (LLM borné)
- Join index déterministe
- Composer pour chaînes cross-doc
- Nouvelle catégorie épistémique : DERIVED_BY_COMPOSITION

---

## 7. Plan POC proposé

| Étape | Description | LLM ? | Métrique de succès |
|-------|-------------|-------|-------------------|
| 1 | Slot enrichment sur 100 claims | Oui (borné) | >40% triplets (S,P,O) valides |
| 2 | Join index sur normalized_name | Non | Nb chaînes longueur ≥ 2 |
| 3 | Composer + reformulation | Oui (reformulation) | Chaînes lisibles et défendables |
| 4 | Évaluation qualitative | Humain | "Est-ce de la connaissance ?" |

---

## 8. Décision stratégique : Pas de couche d'émergence de concepts

**Date :** 2026-02-07
**Contexte :** Proposition ChatGPT d'ajouter une couche "Concept Emergence" au-dessus des claims

### Proposition évaluée

Faire émerger des concepts/entités à partir du graphe de claims existant :
- Analyse de fréquence/co-occurrence des entities
- Clustering sémantique pour regrouper concepts proches
- Promotion automatique d'entities récurrentes en "concepts de premier ordre"

### Verdict : NO-GO

**Données réelles du graphe (post-assainissement v1.6.1) :**

| Métrique | Valeur |
|----------|--------|
| Claims totales | 10 959 |
| Relations inter-claims | 1 114 (10.2%) |
| Relations cross-doc | **0** |
| Claims avec structured_form | ~3 030 (27.7%) |
| Claims orphelines (sans ABOUT) | 3 266 (29.8%) |
| Entities (post-assainissement) | ~4 435 |
| Hubs (>50 claims) | 21 |

**Pourquoi c'est prématuré :**

1. **0 relations cross-doc** → Pas de graphe navigable entre documents. L'émergence ne peut fonctionner que sur un graphe connecté.
2. **72.3% sans structured_form** → Le graphe S/P/O est trop clairsemé pour du clustering fiable
3. **Topologie en étoile** → Entity → N claims. Pas de relations entity-entity. L'émergence sur une étoile produit de la fréquence, pas de la connaissance.
4. **Recyclage de patterns échoués** → Concept Registry (V2.1), Promotion par fréquence (V1), Global taxonomy → déjà tentés, déjà échoués

### Principe retenu

> **"La connaissance n'émerge pas de l'abstraction, elle émerge de la jointure."**

La séquence correcte est :
1. **Slot enrichment** → structured_form sur 100% des claims (pas 27.7%)
2. **Join index** → chaînes (object_A = subject_B) intra puis cross-doc
3. **Composer** → reformulation des chaînes
4. **Observer** → si des patterns émergent du graphe de chaînes, ALORS envisager l'émergence

L'émergence est un **résultat possible** de la composition, pas une couche architecturale à construire.

---

## 9. Analyse des relations intra-doc : Approches non épuisées

**Date :** 2026-02-07
**Question :** Avant d'investir dans le cross-doc, a-t-on épuisé les approches intra-doc ?

### État actuel du RelationDetector

Le `RelationDetector` (Phase 6 du pipeline) produit 3 types de relations :

| Type | Méthode | Résultat actuel |
|------|---------|-----------------|
| CONTRADICTS | Pattern matching (negation/modality) | Rare (~0) |
| REFINES | Marqueurs lexicaux ("specifically", "in particular") + ratio longueur | 892 |
| QUALIFIES | Marqueurs conditionnels ("if", "when", "unless") + ratio longueur | 222 |

**Mécanisme :** Comparaison de **paires de claims** (texte brut), filtré par overlap d'entities ou de tokens significatifs.

### Ce qui N'EST PAS exploité

#### A. Structured_form pour la détection de relations (HAUTE VALEUR)

Le `structured_form` (S/P/O) est utilisé pour :
- la déduplication (Phase 1.5)
- l'extraction d'entities (Source #6)

Mais il est **totalement ignoré** par le RelationDetector.

**Opportunités concrètes :**

1. **Chaînes S/P/O intra-doc** : Si claim A a `object = "Material Ledger"` et claim B a `subject = "Material Ledger"`, il y a une relation de composition DANS le même document.
   ```
   Claim A: "Actual Costing" BASED_ON "Material Ledger"
   Claim B: "Material Ledger" REPLACES "SAP Inventory Management"
   → Chaîne intra-doc: Actual Costing ← Material Ledger ← SAP Inventory Management
   ```

2. **Prédication contradictoire** : Deux claims avec même `subject` mais prédicats incompatibles (REQUIRES vs NOT_REQUIRED) → CONTRADICTS plus précis que le pattern matching textuel.

3. **Hiérarchie PART_OF** : Claims avec prédicat PART_OF/INTEGRATED_IN sur le même document créent un arbre de composition.

**Impact estimé :** Sur les ~3 030 claims avec structured_form, ~23% ont un triplet composable (§5) → ~700 claims pourraient générer des chaînes intra-doc. C'est le même mécanisme que le Join Index cross-doc, mais applicable **immédiatement** sans aucune nouvelle donnée.

#### B. Adjacence de passages (VALEUR MOYENNE)

Actuellement, le RelationDetector **exclut** les claims du même passage (`c1.passage_id == c2.passage_id → skip`). C'est correct pour CONTRADICTS. Mais pour REFINES et QUALIFIES, l'adjacence est un signal fort :

- Claims de passages **consécutifs** dans le même document sont plus probablement liées
- Un passage "General" suivi d'un passage "Details" → REFINES probable
- Un passage "Requirements" suivi d'un passage "Exceptions" → QUALIFIES probable

Ceci nécessite l'information de **position de passage** (non disponible actuellement dans le modèle Passage sans ordinal).

#### C. Hiérarchie de sections (VALEUR MOYENNE)

Les claims sous la même section partagent un contexte thématique. Le `section_title` du passage est disponible mais pas utilisé pour les relations.

- Claims sous "Authentication" → entités communes probables
- Claims sous "Data Migration" → thème migration commun

#### D. POTENTIAL_CONFLICT non persisté (VALEUR FAIBLE)

Le code détecte déjà les conflits potentiels (`_looks_like_potential_conflict`) mais ne les persiste pas — il se contente de les logger. Persister ce signal enrichirait le graphe avec des edges de review humain.

### Synthèse : Intra-doc avant cross-doc

| Approche | Valeur | Effort | Données dispo ? | Priorité |
|----------|--------|--------|-----------------|----------|
| **A. Chaînes S/P/O intra-doc** | **Haute** | Moyen | Oui (27.7% claims) | **1** |
| B. Adjacence passages | Moyenne | Faible | Partiel (passage_id) | 3 |
| C. Hiérarchie sections | Moyenne | Faible | Oui (section_title) | 4 |
| D. POTENTIAL_CONFLICT | Faible | Trivial | Oui (code existant) | 5 |
| **Slot enrichment (augmenter couverture SF)** | **Haute** | Moyen (LLM) | Non (à créer) | **2** |

### Recommandation : Séquence corrigée

L'insight clé est que le Join Index (§4, Couche 3) peut s'appliquer **d'abord intra-doc**, avant d'être étendu au cross-doc :

```
Étape 0 — Chaînes S/P/O intra-doc (sur 27.7% existant)
    → Join déterministe sur object_A.normalized = subject_B.normalized
    → DANS le même document uniquement
    → Valide le mécanisme sans risque de faux cross-doc
    → Métrique: nombre de chaînes intra-doc de longueur ≥ 2

Étape 1 — Slot enrichment (augmenter couverture)
    → LLM borné sur claims sans structured_form
    → Objectif: 27.7% → >60% couverture S/P/O
    → Métrique: % claims avec structured_form valide

Étape 2 — Chaînes S/P/O intra-doc (round 2, couverture élargie)
    → Même mécanisme qu'étape 0 mais sur >60% des claims
    → Métrique: chaînes intra-doc (devrait tripler)

Étape 3 — Extension cross-doc
    → Même Join Index, étendu aux paires inter-documents
    → Métrique: chaînes cross-doc de longueur ≥ 2
```

**Avantage :** L'étape 0 est réalisable **immédiatement** avec les données actuelles. Elle permet de valider le mécanisme du Join Index sans aucun appel LLM supplémentaire, et de mesurer le potentiel réel avant d'investir dans le slot enrichment.

---

## 10. Fichiers de référence

| Fichier | Contenu |
|---------|---------|
| `doc/ongoing/ADR_HYBRID_EXTRACT_THEN_STRUCTURE_2026-02-01.md` | ADR V2.2 (échecs V1/V2.1) |
| `doc/ongoing/ADR_PASS09_GLOBAL_VIEW_CONSTRUCTION.md` | Design GlobalView |
| `doc/archive/diagnostics_2024/PROBLEME_QUALITE_CONCEPTS_20251021.md` | Diagnostic explosion concepts V1 |
| `doc/archive/diagnostics_2024/DUPLICATE_CONCEPTS_ANALYSIS_20251020.md` | Analyse duplication V1 |
| `doc/archive/phase1_osmose_old/ANALYSE_GAP_CANONICALISATION_P0_P1.md` | Gap canonicalisation Gatekeeper |
| `doc/OSMOSIS_PROJECT_HISTORY.md` | Historique complet du projet |
| `src/knowbase/claimfirst/models/claim.py` | Modèle Claim actuel |
| `src/knowbase/claimfirst/models/entity.py` | Modèle Entity actuel |
| `src/knowbase/claimfirst/clustering/relation_detector.py` | RelationDetector (3 types, pattern-based) |
| `scripts/canonicalize_existing_entities.py` | Canonicalisation rétroactive entities |
| `scripts/enrich_entities_from_structured_form.py` | Enrichissement entities depuis SF |
| `tests/claimfirst/test_entity_assainissement.py` | Tests assainissement (101 tests) |
