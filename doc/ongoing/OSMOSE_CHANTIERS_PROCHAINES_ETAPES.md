# OSMOSE — Chantiers prochaines étapes

*Date : 2026-02-09 — Mise à jour post-investigation clusters + query engine*

## État actuel du KG (5 documents)

### Inventaire des nodes

| Label | Nombre | Par doc (moy.) | Projection 500 docs |
|-------|--------|----------------|---------------------|
| Claim | 10 959 | 2 192 | ~1 096 000 |
| Passage | 6 220 | 1 244 | ~622 000 |
| Entity | 4 417 | ~883* | ~200 000** |
| ClaimCluster | 1 151 | 230 | ~115 000 |
| DocumentContext | 5 | 1 | 500 |
| Autres (Facet, SubjectAnchor...) | 48 | ~10 | ~5 000 |
| **TOTAL NODES** | **22 800** | **4 560** | **~2 038 000** |

*\* Les entities sont partiellement partagées entre docs (111 cross-doc sur 4 417).*
*\*\* L'Entity count scale sub-linéairement grâce au partage cross-doc, estimé ~200K.*

### Inventaire des edges

| Type | Nombre | Description |
|------|--------|-------------|
| ABOUT | 13 827 | Claim → Entity |
| SUPPORTED_BY | 10 959 | Claim → Passage |
| IN_CLUSTER | 4 443 | Claim → ClaimCluster |
| CHAINS_TO | 1 882 | Claim → Claim (1 596 intra + 286 cross) |
| HAS_FACET | 1 435 | Claim → Facet |
| REFINES | 892 | Claim → Claim |
| QUALIFIES | 222 | Claim → Claim |
| Autres | 32 | ABOUT_SUBJECT, HAS_AXIS_VALUE, ABOUT_COMPARABLE |
| **TOTAL EDGES** | **33 692** | **Ratio edges/nodes = 1.48** |

### Claims par document

| Document | Claims | Passages | Ratio claims/passages |
|----------|--------|----------|-----------------------|
| Feature Scope 2023 (025) | 5 839 | 1 927 | 3.03 |
| Business Scope 2025 (023) | 2 291 | 1 972 | 1.16 |
| Business Scope 1809 (018) | 1 245 | 1 072 | 1.16 |
| Operations Guide 2021 (014) | 929 | 719 | 1.29 |
| RISE with SAP (020) | 655 | 530 | 1.24 |

**Observation critique :** Le Feature Scope 2023 génère à lui seul 5 839 claims (53% du total). La densité de claims varie de 1:1 à 3:1 par passage.

### Distribution des Passages (partagés ou non)

| Bucket | Nb Passages | Total edges SUPPORTED_BY |
|--------|-------------|-------------------------|
| 1 claim (1:1) | 4 778 (77%) | 4 778 |
| 2-3 claims | 816 | 1 930 |
| 4-10 claims | 555 | 3 267 |
| 10+ claims | 71 | 984 |

**77% des Passages** sont 1:1 avec une Claim → transformables en propriété sans problème. **23%** supportent 2+ claims (co-localisation).

### Distribution des ClaimClusters

| Bucket | Nb clusters | % |
|--------|-------------|---|
| 1-5 claims | 1 084 | 94% |
| 6-20 claims | 58 | 5% |
| 21-50 claims | 3 | <1% |
| 51-100 claims | 1 | <1% |
| 100+ claims | 5 | <1% |

**94% des clusters sont petits et sains** (1-5 claims). 5 méga-clusters (100+ claims) sont des artefacts de la dérive transitive du Union-Find.

### Anatomie des claims sans structured_form

| has_chain | has_entity | has_refines | Nb claims | Archivable ? |
|-----------|-----------|-------------|-----------|-------------|
| Non | Non | Non | 2 986 | **Oui — candidats prioritaires** |
| Non | Oui | Non | 1 981 | Prudence — participent à ABOUT |
| Non | Oui | Oui | 64 | Non — participent à REFINES |
| Non | Non | Oui | 40 | Non — participent à REFINES |

---

## ⚠️ CHANTIER 0 — Rationalisation du graphe (BLOQUANT)

### Le problème

**22 800 nodes pour 5 documents.** Projection naïve : **~2 millions de nodes pour 500 documents.**

Problèmes concrets :
1. **Performance** — Les traversées cross-doc deviennent coûteuses à grande échelle
2. **Coût d'extraction** — Scale linéairement avec le nombre de claims
3. **Bruit** — Claims unitaires ("Feature X NEW 1809") gonflent le graphe sans valeur
4. **Visualisation** — Graphe illisible au-delà de ~50 000 nodes

### Diagnostic consolidé

#### Le ClaimClusterer est déjà sémantique (correction d'un diagnostic initial erroné)

Le `ClaimClusterer` (`src/knowbase/claimfirst/clustering/claim_clusterer.py`) fait un vrai clustering sémantique :
- **Étage 1** : similarité cosinus sur embeddings (seuil 0.85 — conservateur)
- **Étage 2** : validation stricte (mêmes entités, même modalité must/may, pas de négation inversée, overlap lexical minimum)

L'intention est explicite dans le code (INV-3) : *"Le cluster exprime : ces claims de différents docs disent la même chose."*

**L'algorithme est bon. Le problème est l'exploitabilité, pas la sémantique.**

#### Les clusters sont déjà consommés par le query engine

Investigation code : `intent_resolver.py` et `temporal_query_engine.py` traversent les clusters pour :
- **Claims similaires cross-doc** : `claim → IN_CLUSTER → cluster ← IN_CLUSTER ← other claims`
- **Évolution temporelle** : claims du cluster → documents datés → timeline
- **Détection de dépréciations** : claims contenant "removed/deprecated" dans le même cluster

**Conséquence : les clusters ne sont pas dormants. Leur assainissement améliore directement la qualité des résultats de recherche actuels.**

#### Les 3 vrais problèmes des clusters

**1. Méga-clusters (dérive transitive du Union-Find)**
- 5 clusters > 100 claims (total 1 322 claims)
- Cause : A~B et B~C ⇒ A,B,C fusionnés même si A et C n'ont rien en commun
- Impact : ces clusters "poubelles" polluent le temporal_query_engine et l'intent_resolver

**2. Intégrité incohérente**
- Certains clusters affichent `claim_count=1513` mais n'ont que 418 edges IN_CLUSTER
- Cause probable : résidus de purge/reimport, propriétés `claim_ids` désynchronisées
- Règle : **la vérité = les edges, pas les propriétés**

**3. Couverture insuffisante**
- 4 443 edges IN_CLUSTER pour 10 959 claims → **~40% de couverture seulement**
- Les 60% restantes sont des singletons sans cluster

---

### Plan d'exécution en 3 phases

### Phase 1 — Réduction cardinalité immédiate (quick win, faible risque)

#### A. Passage → propriété

Supprimer les 6 220 nodes Passage et les 10 959 edges SUPPORTED_BY. Migrer l'evidence dans un champ `Claim.evidence` (texte + localisation).

Gestion des Passages partagés (23%) :
- **Option simple** : duplication contrôlée de l'evidence sur chaque claim liée
- **Option avancée** : `evidence_key` + dédup externe

#### B. Archivage safe des claims isolées

Archiver uniquement les claims **totalement isolées** (~2 986) :
- `structured_form IS NULL`
- ET `degree(CHAINS_TO) = 0`
- ET `degree(ABOUT) = 0`
- ET `degree(REFINES) = 0`

Marquage `archived: true`, exclusion des traversées par défaut, accessibles en mode verbose.

**Gain attendu Phase 1 : ~40% de réduction** (6 220 Passage nodes + ~2 986 claims archivées = ~9 200 nodes en moins).

| Métrique | Avant | Après Phase 1 |
|----------|-------|---------------|
| Nodes | 22 800 | ~13 600 |
| Edges | 33 692 | ~22 700 |

---

### Phase 2-lite — Assainissement clusters (améliore le query engine existant)

**Ce n'est pas un "nice to have" futur — c'est une action de qualité immédiate** puisque les clusters sont déjà consommés par `intent_resolver.py` et `temporal_query_engine.py`.

#### A. Intégrité
- Recalculer `claim_count` et `claim_ids` depuis les edges IN_CLUSTER réels
- Éliminer les propriétés incohérentes

#### B. Casser les méga-clusters
- Cap de taille (ex. 20 claims max)
- Ou vérification de cohésion par rapport au centroïde (chaque claim doit rester proche du centre)
- Split en sous-clusters si hétérogénéité détectée

#### C. Couverture
- Stratégie pour les singletons : soit clusters singletons, soit fallback claim-level documenté et explicite

#### D. Labels de navigation
- Ajouter `cluster_title` / `cluster_summary` pour remplacer le `canonical_label` actuel (texte tronqué de la meilleure claim)

---

### Phase 3 — Entity Resolution agressive (win-win : cardinalité + qualité)

- **4 417 entities** dont beaucoup de variantes : "SAP S/4HANA", "S/4HANA", "S4HANA", "SAP S/4HANA Cloud"
- ER pragmatique orientée alias : normalisation + lex_key + gating
- Objectif : ~1 500-2 000 entities post-ER
- Ce levier **améliore aussi** le cross-doc (plus de partage d'entities entre documents) et la pertinence des résultats

---

### Cibles de rationalisation

| Métrique | Actuel (5 docs) | Post Phase 1 | Post Phase 3 | Projection 500 docs |
|----------|-----------------|--------------|--------------|---------------------|
| Claims actives | 10 959 | ~7 970 | ~7 000 | ~400 000 |
| Passages | 6 220 | 0 (propriétés) | 0 | 0 |
| Entities | 4 417 | 4 417 | ~1 500-2 000 | ~50 000 |
| ClaimClusters | 1 151 | 1 151 | ~1 000 | ~100 000 |
| **TOTAL NODES** | **22 800** | **~13 600** | **~9 500** | **~550 000** |
| **Réduction** | — | **40%** | **~58%** | **~73% vs naïf** |

---

### Invariants non négociables

1. **Aucune perte de preuve** : claim → evidence exacte (verbatim + span) doit rester possible
2. **Aucune dégradation des requêtes existantes** : query engine, temporal, intent resolver
3. **Phases feature-flaggables / rollbackables** au besoin
4. **Les caches d'extraction (`data/extraction_cache/`) ne sont JAMAIS touchés**

---

## Chantier 1 — Couche d'exploitation hybride RAG + KG

### Objectif
Permettre à un utilisateur de poser une question en langage naturel et recevoir une réponse qui combine le RAG (réponse directe) et le KG (connaissance transversale).

### Approche envisagée
1. L'utilisateur pose une question
2. **Branche RAG** : recherche vectorielle Qdrant → top-k chunks
3. **Branche KG** : extraction d'entités de la question → résolution vers Entity nodes → traversée CHAINS_TO (2-3 hops) → claims atteintes
4. **Fusion** : les deux ensembles de contexte sont combinés et passés au LLM pour synthèse
5. **Réponse** : le LLM cite ses sources (chunks RAG + chaînes KG)

### Valeur
C'est ce qui transforme le PoC en produit. Sans ça, le KG reste un bel objet technique que seul un développeur Cypher peut interroger.

### Prérequis
- Chantier 0 Phase 1 minimum (traversées performantes)
- Un endpoint API qui orchestre les deux branches

### Preuve de concept existante
- Comparaison RAG vs KG documentée : `doc/ongoing/COMPARAISON_RAG_VS_KG_CROSS_DOC.md`
- RAG : 0/40 pertinents sur questions transversales cross-doc
- KG : ~15/15 pertinents avec chaînes complètes sur 3 documents

---

## Chantier 2 — Détection CONTRADICTS cross-doc

### Objectif
Détecter les contradictions entre documents — cas critique pour la fiabilité des réponses RFP.

### Exemples concrets attendus
- Doc 1809 : *"Feature X is available"* → Doc 2023 : *"Feature X has been deprecated"*
- Doc scope : *"Supports up to 10 000 users"* → Doc ops : *"Recommended for up to 5 000 users"*

### Approche envisagée
1. **Phase déterministe** : mêmes subject+object, prédicats contradictoires (USES/REPLACES, ENABLES/REQUIRES)
2. **Phase LLM** : passer les paires ambiguës au LLM avec prompt de détection
3. **Relation CONTRADICTS** avec propriétés de traçabilité

### Prérequis
- Chantier 0 pour réduire le nombre de paires à comparer
- Structured_form sur un maximum de claims

---

## Chantier 3 — Timeline / Evolution Tracker

### Objectif
Matérialiser la dimension temporelle — comment les features évoluent entre versions de documents.

### Données disponibles
4 millésimes : 1809 → 2021 → 2023 → 2025. Les CHAINS_TO cross-doc relient déjà des claims entre versions mais sans notion d'ordre temporel.

### Approche envisagée
1. **Attribut `doc_date` ou `doc_version`** sur les DocumentContext
2. **Relation SUPERSEDES** : claim récente affine/remplace claim ancienne
3. **Vue timeline** : pour une entity, afficher l'évolution chronologique

### Valeur
Promesse originale OSMOSE ("CRR Evolution Tracker"). *"Le Material Ledger était optionnel en 1809, intégré en 2023, et inclus dans PCE en 2025."*

---

## Chantier 4 — Enrichissement des structured_forms manquantes

### Objectif
Passer de 53.7% à 80%+ de claims avec structured_form.

### Situation actuelle
- 5 888 / 10 959 claims ont une SF (53.7%)
- Les 46% restantes sont des impasses dans le graphe
- Beaucoup sont des titres de section, bullet points courts, ou phrases complexes

### Approche envisagée
- Prompt V3 plus agressif pour l'extraction S/P/O
- Pass de ré-extraction ciblé sur les claims sans SF
- Ou : archivage des claims non-structurables (cf. Chantier 0 Phase 1B)

---

## Chantier 5 — Ingestion de documents supplémentaires

### Objectif
Passer de 5 à 20+ documents pour augmenter la valeur cross-doc.

### Impact attendu
Valeur cross-doc **quadratique** : 5 docs = 10 paires, 20 docs = 190 paires.

### Prérequis
- Chantier 0 IMPÉRATIF avant de scale
- Pipeline d'ingestion optimisé pour batch

---

## Chantier 6 — Détection REFINES cross-doc

### Objectif
Détecter quand une claim d'un document précise/détaille une claim d'un autre.

### Exemple
- Doc A : *"S/4HANA supports asset management"*
- Doc B : *"S/4HANA supports asset management with predictive maintenance, IoT integration, and mobile work orders"*

### Note
892 REFINES intra-doc existent déjà. L'extension cross-doc suivrait le pattern CHAINS_TO cross-doc.

---

## Ordre de priorité

```
Chantier 0 — Rationalisation du graphe          ████████████ BLOQUANT
  Phase 1 : Passage→propriété + archivage         → gain 40%
  Phase 2 : Assainir clusters                      → qualité query engine
  Phase 3 : ER agressive                           → gain 58% + qualité
    ↓
Chantier 1 — Hybride RAG + KG                   ████████████ PRODUIT
    ↓
Chantier 5 — Plus de documents                   ████████░░░░ SCALE
    ↓
Chantier 2 — CONTRADICTS                         ███████░░░░░ VALEUR MÉTIER
Chantier 3 — Timeline                            ███████░░░░░ PROMESSE OSMOSE
    ↓
Chantier 4 — Enrichissement SF                   ██████░░░░░░ DENSIFICATION
Chantier 6 — REFINES cross-doc                   █████░░░░░░░ PRÉCISION
```

---

## Références

- Comparaison RAG vs KG : `doc/ongoing/COMPARAISON_RAG_VS_KG_CROSS_DOC.md`
- ClaimClusterer : `src/knowbase/claimfirst/clustering/claim_clusterer.py`
- Query engine (consomme clusters) : `src/knowbase/claimfirst/query/intent_resolver.py`, `temporal_query_engine.py`
- Implémentation cross-doc : `src/knowbase/claimfirst/composition/chain_detector.py`
- Script cross-doc : `app/scripts/detect_cross_doc_chains.py`
- Tests cross-doc : `tests/claimfirst/test_chain_detector_cross_doc.py` (32 tests)
- Tests intra-doc : `tests/claimfirst/test_chain_detector.py` (24 tests)
