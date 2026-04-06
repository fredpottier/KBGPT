# OSMOSE — Chantiers prochaines étapes

*Date : 2026-02-13 — Mise à jour complète post-audit 22 documents*

---

## État actuel du KG (22 documents)

### Inventaire des nodes

| Label | Nombre | Par doc (moy.) | Projection 500 docs |
|-------|--------|----------------|---------------------|
| Claim | 37 748 | 1 716 | ~600 000* |
| Entity | 22 329 | ~1 015** | ~100 000** |
| ClaimCluster | 2 954 | 134 | ~50 000 |
| Passage | **0** | 0 | 0 |
| DocumentContext | 22 | 1 | 500 |
| **TOTAL NODES** | **63 147** | **2 870** | **~750 000** |

*\* Projection sub-linéaire : la dédup S/P/O et le partage d'entities cross-doc réduisent la croissance.*
*\*\* Les entities sont partiellement partagées entre docs. Scale sub-linéairement.*

### Inventaire des edges

| Type | Nombre | Description |
|------|--------|-------------|
| ABOUT | 63 181 | Claim → Entity |
| QUALIFIES | 38 173 | Claim → Claim (qualifie/conditionne) |
| IN_CLUSTER | 14 880 | Claim → ClaimCluster |
| CHAINS_TO | 4 862 | Claim → Claim (intra + cross-doc) |
| REFINES | 4 631 | Claim → Claim (précise/détaille) |
| CONTRADICTS | 334 | Claim → Claim (contradiction détectée) |
| Autres | ~3 212 | HAS_AXIS_VALUE, ABOUT_SUBJECT, ABOUT_COMPARABLE... |
| **TOTAL EDGES** | **~129 273** | **Ratio edges/nodes = 2.05** |

### Comparaison avec l'état précédent (5 docs → 22 docs)

| Métrique | 5 docs (09/02) | 22 docs (13/02) | Évolution |
|----------|----------------|-----------------|-----------|
| Nodes | 22 800 | 63 147 | ×2.8 (sub-linéaire) |
| Edges | 33 692 | 129 273 | ×3.8 |
| Passage nodes | 6 220 | **0** | **Phase 1A appliquée** |
| CONTRADICTS | 0 | 334 | **Phase 6 activée** |
| REFINES | 892 | 4 631 | ×5.2 |
| QUALIFIES | 222 | 38 173 | ×172 (explosion) |
| CHAINS_TO | 1 882 | 4 862 | ×2.6 |

---

## Bilan des chantiers — Ce qui est FAIT vs À FAIRE

### ✅ CHANTIER 0 Phase 1A — Passage → propriétés — **FAIT**

Les Passages sont stockés comme propriétés JSON sur les Claims (via `OSMOSE_SKIP_PASSAGE_PERSIST=true`, défaut). **0 nœuds Passage dans Neo4j**. L'evidence (verbatim + span) est préservée dans `passage_text`, `section_title`, `page_no`, etc.

### ⬜ CHANTIER 0 Phase 1B — Archivage claims isolées — **À FAIRE**

Pas de logique d'archivage implémentée. Toutes les claims sont persistées indifféremment.

### ⬜ CHANTIER 0 Phase 2 — Assainissement clusters — **À FAIRE**

Le `ClaimClusterer` n'a **aucun cap de taille** sur les clusters. Le Union-Find peut produire des méga-clusters non bornés. Pas de logique de split ni de recalcul d'intégrité.

- Avec 22 docs : 2 954 clusters, probablement ~13 clusters >100 claims
- Le `claim_count` sur les propriétés peut être désynchronisé des edges réels

### ⚠️ CHANTIER 0 Phase 3 — Entity Resolution — **PARTIELLEMENT FAIT**

L'`EntityCanonicalizer` (Phase 2.5 du pipeline) fait déjà une canonicalisation LLM. Mais pas d'ER agressive (normalisation + lex_key + gating + fusion d'alias). Avec 22 329 entities, beaucoup de variantes existent ("SAP S/4HANA" vs "S/4HANA" vs "S4HANA").

### ✅ CHANTIER 2 — Détection CONTRADICTS — **FAIT (intra-cluster)**

Le `RelationDetector` (Phase 6 du pipeline) détecte CONTRADICTS, REFINES et QUALIFIES automatiquement pendant l'import. **334 CONTRADICTS** trouvées. Fonctionne en intra-cluster (optimisation O(n²) → O(k²) par cluster).

**Limite** : Pas de détection CONTRADICTS cross-cluster ni cross-doc explicite. Les contradictions ne sont trouvées que si les claims sont dans le même cluster.

### ⚠️ CHANTIER 3 — Timeline / Evolution — **PARTIELLEMENT FAIT**

Le `VersionEvolutionDetector` est **construit et testé** (`composition/evolution_detector.py`), mais **NON intégré dans le pipeline orchestrateur**. Il :
- Détecte les paires de versions adjacentes via `ComparableSubject` + `ApplicabilityAxis`
- Compare les claims : UNCHANGED / MODIFIED / ADDED / REMOVED
- Fingerprinting déterministe S|P|O

**Ce qui manque** : intégration dans le pipeline OU persistence automatique des `EvolutionLink`.

### ✅ CHANTIER 5 — Plus de documents — **FAIT**

22 documents importés (vs 5 initiaux). 231 paires de documents possibles.

### ⚠️ CHANTIER 6 — REFINES cross-doc — **FAIT (intra-cluster)**

4 631 REFINES détectées automatiquement par le `RelationDetector`. Même limite que CONTRADICTS : intra-cluster uniquement.

---

## Nouveautés implémentées (session 2026-02-13)

### ✅ Track B — Domain Context Injection dans AxisDetector/Validator

- `AxisDetector._call_llm()` enrichit le system prompt via `DomainContextInjector`
- `AxisValueValidator._call_llm()` idem
- `tenant_id` propagé depuis l'orchestrateur

### ✅ Track C — Champ `versioning_hints` dans DomainContextProfile

Nouveau champ `versioning_hints` (texte libre, 500 chars max) ajouté sur toute la pile :
- Modèle Pydantic + sérialisation Neo4j
- Colonne PostgreSQL
- Store (save/get/list)
- API schemas (Create, Response, Preview)
- API router (create, get, preview, prompt generation)
- Injecteur : section "Versioning conventions" dans `[DOMAIN CONTEXT]`

### ✅ Track B1 — Fix re-persistence axes ordonnés

L'orchestrateur propage désormais les axes re-inférés (post-merge cache) dans `detected_axes` pour persistence. Les axes `is_orderable=True` ne sont plus perdus.

### ✅ Batch persistence (claim_persister.py)

Remplacement des appels Neo4j 1-par-1 par UNWIND batch pour passages, claims, entities, relations. ~90% de round-trips en moins (non commité).

### ✅ Nettoyage dead code

Suppression de `_get_domain_context_prompt()` (appelait `store.get_active_context()` inexistant).

---

## 🎯 UPGRADES À IMPLÉMENTER AVANT RÉIMPORT

Le réimport des 22 documents prend ~6 heures. Chaque upgrade implémenté maintenant sera appliqué à l'ensemble du corpus. Voici la liste exhaustive priorisée.

---

### PRIORITÉ 1 — Qualité d'extraction (impact direct sur toutes les claims)

#### 1.1 Filtres qualité post-extraction des claims

**Problème** : L'audit qualité (`AUDIT_QUALITE_CLAIMS_V1.6.md`) identifie ~13% de bruit dans les claims :
- Fragments < 30 chars ("You can also use the", "Refer to the SAP Notes")
- Claims commençant par "You can" (instructions génériques, pas des claims techniques)
- Boilerplate (copyright, disclaimers, "See SAP Note XXXX")
- Claims tronquées/incomplètes

**Implémentation** : Ajouter des filtres post-extraction dans le pipeline (Phase 1.5 ou nouveau Phase 1.6) :
- `min_claim_length` : 30 chars (vs 10 actuellement)
- Blacklist de patterns boilerplate : "Refer to SAP Note", "See the following", "You can also"
- Détection de fragments : claims sans verbe principal
- Flag `quality_score` ou `is_noise` sur la Claim

**Fichiers** : `claim_extractor.py`, nouveau `claim_quality_filter.py`
**Complexité** : Faible — filtrage déterministe, pas de LLM

#### 1.2 Resserrer les limites des noms d'entities

**Problème** : `max_entity_length = 60` chars laisse passer des noms trop longs qui sont en fait des phrases. Exemples : "SAP S/4HANA Cloud Private Edition with Intelligent Scenario Planning"

**Implémentation** :
- Baisser `max_entity_length` de 60 → 40 chars
- Ajouter filtre "that/which" explicite (actuellement indirect via PHRASE_FRAGMENT_INDICATORS)
- Ajouter "and", "or", "including" aux indicateurs de fragments

**Fichiers** : `entity_extractor.py` (L91, L314-348)
**Complexité** : Triviale

#### 1.3 Améliorer le prompt d'extraction V2

**Problème** : Le ratio structured_form est ~53%. Les claims sans SF sont des impasses.

**Implémentation** :
- Renforcer la consigne S/P/O dans le prompt d'extraction
- Ajouter des exemples few-shot pour les cas ambigus (titres de section, bullet points)
- Option : fallback extraction S/P/O pour les claims qui n'en ont pas après Phase 1

**Fichiers** : `claim_extractor.py`, `config/prompts.yaml` si externalisé
**Complexité** : Moyenne — itération sur le prompt LLM

---

### PRIORITÉ 2 — Cardinalité et structure du graphe

#### 2.1 Cap de taille sur les clusters (mega-cluster breaking)

**Problème** : Le Union-Find peut produire des clusters arbitrairement grands via dérive transitive. Ces méga-clusters polluent le query engine.

**Implémentation** :
- Ajouter `MAX_CLUSTER_SIZE = 20` dans `ClaimClusterer`
- Après Union-Find : si cluster > cap, split par re-clustering (k-means sur embeddings du cluster)
- Recalculer `claim_count` et `claim_ids` depuis les edges réels

**Fichiers** : `claim_clusterer.py` (L264-326)
**Complexité** : Moyenne — algorithme de split à concevoir

#### 2.2 Archivage des claims isolées (Chantier 0 Phase 1B)

**Problème** : Des milliers de claims sans structured_form, sans entity, sans relation — pur bruit.

**Implémentation** :
- Ajouter propriété `archived: true` aux claims isolées
- Critères : `structured_form IS NULL AND degree(ABOUT)=0 AND degree(CHAINS_TO)=0 AND degree(REFINES)=0`
- Exclure des traversées par défaut dans le query engine
- Mode verbose pour les inclure si besoin

**Fichiers** : `claim_persister.py` (post-persist flag), query engine (filter)
**Complexité** : Faible

#### 2.3 Nettoyage du répertoire doublé `composition/composition/`

**Problème** : `src/knowbase/claimfirst/composition/composition/` contient une vieille version du `chain_detector.py` (intra-doc only). Non importé, stale.

**Implémentation** : Supprimer le répertoire.
**Complexité** : Triviale

---

### PRIORITÉ 3 — Détection d'évolution temporelle (promesse OSMOSE)

#### 3.1 Intégrer EvolutionDetector dans le pipeline OU post-import automatique

**Problème** : `VersionEvolutionDetector` est construit et testé mais n'est appelé que via script offline. Après un réimport, il faut relancer manuellement.

**Options** :
- **Option A** : Intégrer comme Phase 6.7 dans l'orchestrateur (après relations, avant persist)
  - Pro : automatique à chaque import
  - Con : nécessite tous les docs chargés en mémoire pour comparer
- **Option B** : Script post-import automatique (déclenché par hook ou endpoint API)
  - Pro : simple, découplé
  - Con : pas intégré au pipeline

**Fichiers** : `orchestrator.py` ou nouveau script/endpoint
**Complexité** : Moyenne (option A) / Faible (option B)

#### 3.2 Persistence des EvolutionLink dans Neo4j

**Problème** : Le détecteur produit des `EvolutionLink` (UNCHANGED/MODIFIED/ADDED/REMOVED) mais il n'y a pas de persistence automatique. Seul le script offline persiste.

**Implémentation** :
- Ajouter `_persist_evolution_links()` au `ClaimPersister`
- Relation EVOLVES_TO avec propriétés : `evolution_type`, `old_object_raw`, `new_object_raw`
- Ou : réutiliser CHAINS_TO avec `method=version_evolution`

**Fichiers** : `claim_persister.py`, `evolution_detector.py`
**Complexité** : Faible

#### 3.3 Fix des axes pour la détection d'évolution

**Problème** : Le script `fix_axis_ordering.py` corrige les axes `is_orderable=False`. Après réimport, le fix B1 (re-persistence) devrait résoudre ça. Mais le `release_id` axis avec valeurs hétérogènes (semver+YYMM+SP+Edition) nécessite `versioning_hints` configuré.

**État** : versioning_hints déjà configuré via API pour le tenant "default". Le fix B1 est en place.

**Action** : Vérifier après réimport que les axes sont bien `is_orderable=True`.
**Complexité** : Validation seulement

---

### PRIORITÉ 4 — Cross-doc enrichi

#### 4.1 Cross-doc chain detection dans le pipeline

**Problème** : `ChainDetector.detect_cross_doc()` existe mais n'est pas appelé par le pipeline. Seul `detect()` (intra-doc) est appelé en Phase 6.5. Le cross-doc ne fonctionne que via le script offline.

**Implémentation** :
- Appeler `chain_detector.detect_cross_doc()` dans l'orchestrateur après Phase 6.5
- Nécessite accès aux claims des documents déjà importés (Neo4j query)
- Alternative : le garder en post-import script mais le déclencher automatiquement

**Fichiers** : `orchestrator.py` (Phase 6.5+)
**Complexité** : Moyenne — gestion du contexte multi-doc

#### 4.2 CONTRADICTS et REFINES cross-cluster

**Problème** : La détection actuelle est limitée aux paires intra-cluster. Des contradictions entre clusters différents ne sont pas détectées.

**Implémentation** : Étendre RelationDetector avec un mode cross-cluster basé sur :
- Mêmes entities (join par Entity node)
- Structured forms avec même subject+predicate, objects divergents

**Fichiers** : `relation_detector.py`
**Complexité** : Élevée — explosion combinatoire à maîtriser

---

### PRIORITÉ 5 — Améliorations secondaires

#### 5.1 Labels de navigation pour clusters

Ajouter `cluster_title` / `cluster_summary` (LLM-generated) pour remplacer le `canonical_label` actuel.

#### 5.2 Enrichissement slot (Phase 1.7 existante)

La Phase 1.7 "Slot Enrichment" existe déjà dans le pipeline. Vérifier son efficacité sur le corpus de 22 docs.

#### 5.3 Entity Resolution agressive (Chantier 0 Phase 3)

ER avec normalisation + lex_key + gating pour fusionner les variantes ("SAP S/4HANA" / "S/4HANA" / "S4HANA"). Objectif : réduire de 22 329 → ~10 000 entities.

---

## Recommandation pour le réimport

### Implémenter AVANT le réimport (gain maximal / effort minimal)

| # | Upgrade | Impact | Effort | Priorité |
|---|---------|--------|--------|----------|
| 1 | Filtres qualité claims (1.1) | Élimine ~13% de bruit | Faible | **P1** |
| 2 | Resserrer entity names (1.2) | Moins d'entities-phrases | Trivial | **P1** |
| 3 | Cap mega-clusters (2.1) | Clusters exploitables | Moyen | **P2** |
| 4 | Supprimer composition/composition/ (2.3) | Nettoyage | Trivial | **P2** |
| 5 | Commiter les 3 fichiers modifiés | Préservation | Trivial | **P0** |

### Implémenter PENDANT ou juste APRÈS le réimport

| # | Upgrade | Impact | Effort | Priorité |
|---|---------|--------|--------|----------|
| 6 | Script post-import evolution (3.1-B) | Evolution temporelle | Faible | **P3** |
| 7 | Script post-import cross-doc chains | Chaînes cross-doc | Faible | **P3** |
| 8 | Archivage claims isolées (2.2) | Réduction bruit | Faible | **P2** |

### Reporter (hors scope réimport)

| # | Upgrade | Raison du report |
|---|---------|-----------------|
| 9 | CONTRADICTS cross-cluster (4.2) | Complexité élevée, nécessite conception |
| 10 | ER agressive (5.3) | Chantier majeur, mérite sa propre itération |
| 11 | Hybride RAG+KG (Chantier 1) | Chantier produit, pas un upgrade pipeline |
| 12 | Labels clusters (5.1) | Nice-to-have, pas de valeur ajoutée pour l'import |

---

## Invariants non négociables

1. **Aucune perte de preuve** : claim → evidence exacte (verbatim + span) doit rester possible
2. **Aucune dégradation des requêtes existantes** : query engine, temporal, intent resolver
3. **Phases feature-flaggables / rollbackables** au besoin
4. **Les caches d'extraction (`data/extraction_cache/`) ne sont JAMAIS touchés**

---

## Références

- Audit qualité claims : `doc/ongoing/AUDIT_QUALITE_CLAIMS_V1.6.md`
- ClaimClusterer : `src/knowbase/claimfirst/clustering/claim_clusterer.py`
- Query engine : `src/knowbase/claimfirst/query/intent_resolver.py`, `temporal_query_engine.py`
- ChainDetector : `src/knowbase/claimfirst/composition/chain_detector.py`
- EvolutionDetector : `src/knowbase/claimfirst/composition/evolution_detector.py`
- RelationDetector : `src/knowbase/claimfirst/clustering/relation_detector.py`
- Script fix axes : `app/scripts/fix_axis_ordering.py`
- Script evolution : `app/scripts/detect_version_evolution.py`
- Script cross-doc chains : `app/scripts/detect_cross_doc_chains.py`
- Tests cross-doc : `tests/claimfirst/test_chain_detector_cross_doc.py` (32 tests)
- Tests evolution : `tests/claimfirst/test_evolution_detector.py`
