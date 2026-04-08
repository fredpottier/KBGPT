# Dette — rebuild incrémental des couches pré-calculées

*Diagnostic avril 2026 déclenché par la lecture d'un article sur les limitations de Microsoft GraphRAG (incremental update problem). Identifié que OSMOSIS a le même type de dette, mais sur un périmètre plus réduit grâce au découplage ResponseMode. Document de diagnostic, pas de fix immédiat — à relire quand on stabilisera les benchmarks et qu'on voudra industrialiser le cycle d'ingestion.*

---

## 1. Le problème en une phrase

Ajouter des documents à OSMOSIS ne casse rien et ne génère pas d'erreur visible, **mais dégrade silencieusement les couches pré-calculées qui dépendent d'un calcul global sur l'ensemble du corpus** — principalement la couche Perspective V2 (HDBSCAN global). Tant qu'on ne relance pas explicitement ces calculs, les nouveaux claims sont invisibles à la couche meso de raisonnement.

L'utilisateur ne voit pas immédiatement la dégradation parce que :

1. Les chunks Qdrant et les claims Neo4j restent frais (append-only)
2. La majorité des modes de réponse (DIRECT, AUGMENTED, TENSION, STRUCTURED_FACT) utilisent ces données fraîches, pas les clusters pré-calculés
3. Seul le mode PERSPECTIVE dégrade, et il n'est déclenché que sur les questions ouvertes/thématiques — donc une fraction des requêtes

C'est le **problème du "silent drift"** : la qualité baisse progressivement sans signal d'alerte.

---

## 2. Analyse par couche

### 2.1. Couches qui survivent proprement (append-only, aucun effet)

| Couche | Pourquoi c'est safe |
|---|---|
| Chunks Qdrant | Collection vectorielle pure, pas de voisinage global |
| Claim extraction | Par document, zéro dépendance |
| Embeddings E5-large des claims | Par claim, indépendant du corpus |
| Entity via `canonical_aliases` | Matching contre gazetteer statique |
| Attachement `ABOUT_COMPARABLE` | Rattachement à un Subject existant |

**Verdict** : ajouter un doc n'a aucun impact négatif sur ces couches.

### 2.2. Couches qui dégradent silencieusement (le vrai problème)

| Couche | Nature de la dérive | Gravité |
|---|---|---|
| **Perspective V2** (HDBSCAN global) | Nouveaux claims invisibles, frontières obsolètes, centroids périmés, `claim_count`/`doc_count`/`coverage_ratio` faux | **Élevée** — mode PERSPECTIVE utilise des axes stales |
| **Consolidation Facet** | Nouvelles dimensions structurelles non créées, nouveaux claims attachés à la Facet la plus proche même si inadéquate | Moyenne — stable sur domain pack mûr |
| **Relations `CONTRADICTS`/`REFINES`** | Pairwise non calculées entre nouveau doc et ancien corpus → contradictions invisibles | **Élevée** pour mode TENSION |
| **`CHAINS_TO` cross-doc** | Nouveaux maillons de chaîne non détectés | Moyenne |
| **`QuestionSignature` comparisons** | Nouvelles évolutions cross-version non détectées | Moyenne |
| **Claim-chunk bridge** | Nouveaux claims sans pointeur vers leur chunk source → citations dégradées | Élevée si oublié |
| **Perspective embeddings** (25% label + 75% centroid) | Centroid périmé, scoring runtime faussé | Élevée |

### 2.3. Couches futures qui hériteront du problème

- **NarrativeTopic (Atlas)** : dépend simultanément de Perspective V2 **et** de ComparableSubject. Toute dérive sur l'une ou l'autre se propage. Le plus coûteux à rebuild (community detection + résumés LLM par topic).
- **Toute future couche de résumés pré-calculés** (community summaries à la Microsoft GraphRAG si on en ajoute un jour).

---

## 3. Pourquoi on a pu "ajouter des documents sans reconstruire" quand même

Deux raisons architecturales **non planifiées** nous ont protégés jusqu'ici.

### 3.1. Le découplage ResponseMode est une bénédiction cachée

OSMOSIS route les requêtes via le `strategy_analyzer` vers l'un des 4-5 modes. **Seul le mode PERSPECTIVE dépend des clusters pré-calculés**. Les autres utilisent directement les chunks Qdrant et les claims Neo4j, qui sont frais par construction.

Donc sur ~80% des requêtes courantes, aucune dégradation n'est visible après une ingestion. Microsoft GraphRAG n'a pas ce découplage — leurs community summaries sont toujours dans le pipeline → dégradation visible partout. Chez nous, c'est localisé.

**Conséquence perverse** : on ne voit pas le problème, donc on ne le traite pas, donc il s'aggrave dans l'ombre.

### 3.2. Post-import pipeline existant (partiellement)

Un pipeline `post-import` existe déjà dans le code (`src/knowbase/claimfirst/post_import/`) et est visible dans `cockpit/pipeline_defs.yaml`. Il relance automatiquement après une ingestion :

- `canonicalize` (entités)
- `facets` (bootstrap + consolidation)
- `cluster_cross_doc` (clustering cross-doc)
- `chains_cross_doc` (chaînes de causalité)
- `detect_contradictions`
- `domain_pack_reprocess`
- `claim_embeddings`
- `claim_chunk_bridge`
- `archive_isolated`

**Mais il ne relance PAS la couche Perspective V2.** La construction des Perspectives est un job séparé (`app/scripts/build_perspectives.py`) qui doit être déclenché manuellement. C'est le trou central dans notre orchestration incrémentale.

---

## 4. Comparaison avec Microsoft GraphRAG

| Aspect | Microsoft GraphRAG | OSMOSIS |
|---|---|---|
| Couche de clustering global | Leiden multi-niveaux sur entity graph | HDBSCAN sur embeddings Claims (Perspective V2) ; futur Leiden bipartie pour NarrativeTopic |
| Community summaries pré-calculés | Oui, LLM text à chaque niveau | Oui (Perspective `label`, `description`, `representative_texts`) |
| Dégradation à l'ajout de doc | **Visible** sur toutes les requêtes globales | **Silencieuse**, seulement sur le mode PERSPECTIVE |
| Alternative fraîche pour les requêtes | Non, bloqués sur community summaries | **Oui** : DIRECT/AUGMENTED/TENSION/STRUCTURED_FACT utilisent les données live |
| Pipeline post-import incrémental | Non documenté | Partiellement implémenté, mais pas Perspective |
| Détection automatique de staleness | Non | Non |
| Mécanisme anti-dérive | Rebuild complet périodique | Rebuild manuel (aujourd'hui) ; prévu : dette structurelle (cf. Atlas) |

**Où on est meilleurs qu'eux** : découplage ResponseMode → issue de secours fraîche.
**Où on est pareils** : mode PERSPECTIVE et futur NarrativeTopic dégradent comme chez eux.
**Où on est moins bons** : pas de pipeline unifié qui rebuild tout en une passe — HDBSCAN est un orphelin dans le post-import.

---

## 5. Vision architecturale — le post-import comme orchestrateur de la couche de raisonnement

**Insight clé (avril 2026)** : le pipeline `post-import` a été conçu à l'origine comme une **agrégation de scripts correctifs** destinés à réparer des problèmes progressifs du KG au fil des ingestions. À l'usage, il s'avère être **exactement la bonne abstraction** pour orchestrer le rebuild régulier des couches de raisonnement.

Ce qui change dans la vision :

- **Avant** : post-import = "un ensemble de fixes à lancer après une ingestion pour corriger les dérives"
- **Maintenant** : post-import = "l'orchestrateur de la couche de raisonnement du KG, déclenché régulièrement pour maintenir la fraîcheur des calculs globaux"

Cette reframing est importante parce qu'elle justifie d'**intégrer Perspective V2 (et plus tard NarrativeTopic) comme étapes de premier plan du post-import**, plutôt que comme des jobs séparés à lancer manuellement. Le post-import devient le **point unique de vérité** pour la fraîcheur des couches pré-calculées.

### 5.1. Ce que ça change concrètement

Le post-import pipeline gagne une nouvelle étape :

```
canonicalize → facets → cluster_cross_doc → chains_cross_doc
  → detect_contradictions → domain_pack_reprocess → claim_embeddings
  → claim_chunk_bridge → archive_isolated
  → **build_perspectives**  ← NOUVEAU
  → (futur) build_narrative_topics
```

Et le trigger du post-import peut devenir composite :

- Automatique à la fin de chaque batch d'ingestion (comme aujourd'hui)
- Automatique au-delà d'un seuil de claims ajoutés depuis le dernier rebuild (ex: 500 nouveaux claims ou 10% du corpus)
- Manuel sur commande pour forcer un rebuild complet

### 5.2. Point d'attention : coût du rebuild Perspective

Rebuild Perspective V2 n'est **pas gratuit** :
- HDBSCAN + UMAP sur ~15k embeddings : quelques minutes
- Labellisation LLM Haiku pour chaque cluster (60 clusters × ~1s × coût Haiku) : ~1 minute + ~$0.10
- Calcul des embeddings de Perspective (centroid 25% label + 75% claims) : secondes
- Persist Neo4j : secondes

Total ~3-5 minutes + quelques cents. Ce n'est pas bloquant mais ce n'est pas trivial non plus — on ne veut **pas** le faire à chaque document ingéré (trop coûteux, trop d'interruption). Le **seuil composite** proposé ci-dessus est donc essentiel.

---

## 6. Plan d'amélioration à moindre coût

*Pas un plan d'implémentation détaillé, juste l'ordre des étapes pour le jour où on l'attaque.*

### Étape 1 — Instrumentation (prérequis, 1h)

Ajouter au cockpit ou au post-import un calcul de **staleness de la couche Perspective** :

```cypher
MATCH (p:Perspective) WITH max(p.updated_at) AS last_build
MATCH (c:Claim) WHERE c.created_at > last_build RETURN count(c) AS new_claims_since_build
```

Exposer dans le cockpit comme un indicateur visible (ex: tuile "Perspective staleness: 237 new claims since last build"). Dès que cette métrique existe, on voit si c'est un problème réel ou théorique.

### Étape 2 — Intégration dans le post-import (2-4h)

Ajouter `build_perspectives` comme étape du post-import pipeline :

1. Créer une fonction `rebuild_perspectives_incremental()` dans `src/knowbase/perspectives/orchestrator.py` qui wrappe le script CLI existant
2. L'ajouter à la séquence du post-import juste après `claim_chunk_bridge` et avant `archive_isolated`
3. L'étape peut être skippée si `new_claims_since_build < threshold` (configurable, défaut 100)
4. Mettre à jour `cockpit/pipeline_defs.yaml` pour inclure la nouvelle étape dans la vue cockpit

### Étape 3 — Trigger composite (facultatif, 1-2h)

Ajouter un endpoint admin `/api/post-import/rebuild-if-stale` qui :

- Calcule le `new_claims_since_build`
- Déclenche le post-import si > seuil
- Retourne un statut (`triggered` | `not_needed`)

Ce endpoint peut être appelé par un cron externe, par l'UI admin, ou par un bouton cockpit.

### Étape 4 — Staleness visible côté chat (facultatif)

Si le mode PERSPECTIVE est déclenché alors que `staleness > 50%`, logger un warning et/ou downgrader explicitement vers DIRECT avec une note dans les métadonnées de la réponse. C'est une protection de dernier recours qui évite de servir des clusters trop périmés sans prévenir.

---

## 7. Ce qu'il ne faut PAS faire

- **Ne pas rebuild sur chaque ajout de doc.** Trop coûteux, trop d'interruption, gain nul entre deux documents.
- **Ne pas cacher la staleness.** Si le mode PERSPECTIVE est dégradé, il faut que ce soit visible quelque part (cockpit, logs, métadonnées de réponse).
- **Ne pas imiter Microsoft sur le rebuild complet monolithique.** Leur choix est forcé par leur archi. On a un découplage qui permet une stratégie plus fine — autant l'exploiter.
- **Ne pas attendre NarrativeTopic pour agir.** Le problème existe déjà avec Perspective V2. NarrativeTopic ne fera qu'aggraver.

---

## 8. Questions ouvertes

**Q1. Seuil de déclenchement du rebuild** — quelle est la métrique la plus pertinente ? Nombre absolu de nouveaux claims ? Pourcentage du corpus ? Nombre de documents ? Temps écoulé ? Probablement une combinaison, à tuner empiriquement.

**Q2. Rebuild incrémental partiel** — est-il possible de **ne rebuild que les Perspectives impactées** par les nouveaux claims (celles dont la distance est < seuil au centroid des nouveaux claims) au lieu de tout rebuild ? Ça demande une réflexion algorithmique sérieuse mais ça pourrait diviser le coût par 5-10.

**Q3. Versioning des Perspectives** — faut-il garder l'historique des Perspectives passées (avec timestamp de build) pour pouvoir tracer les évolutions thématiques dans le temps ? Utile pour un "diff de corpus" entre deux ingestions majeures.

**Q4. Relation avec la dette ComparableSubject** — le fix de la dette Subject améliorera la qualité des Perspectives (les `linked_subject_names` seront corrects), mais ne résout pas le problème du rebuild incrémental. Les deux dettes sont **orthogonales** et peuvent être traitées indépendamment.

**Q5. Point de départ du "compteur de dette structurelle" Atlas** — la réflexion Atlas (Q3) a introduit le mécanisme de dette structurelle pour le niveau macro (NarrativeTopic). Faut-il généraliser ce mécanisme à toutes les couches pré-calculées, ou garder un seuil simple pour Perspective et réserver la dette structurelle à Atlas ? Probablement le premier — c'est le même pattern.

---

## 9. Décision actuelle

**Ne rien faire maintenant.** Cette dette est tracée ici pour :

1. Qu'on ne l'oublie pas
2. Qu'on puisse revenir dessus avec le diagnostic complet au moment où on voudra stabiliser le cycle d'ingestion
3. Qu'on ait un plan d'attaque prêt quand les benchmarks seront stables et qu'on sera prêt à industrialiser

**Prérequis de priorité plus haute** :

- Stabiliser les benchmarks actuels (RAGAS, T2/T5, Robustness) — en cours
- Fixer la dette `ComparableSubject` — tracée séparément (cf. `doc/ongoing/[futur]_DETTE_COMPARABLE_SUBJECT.md`)

Dès que ces deux points sont OK, attaquer l'étape 1 (instrumentation de la staleness) de ce document devient raisonnable et à coût faible.

---

## 10. Voir aussi

- `doc/ongoing/[futur]_DETTE_COMPARABLE_SUBJECT.md` — autre dette identifiée, orthogonale mais concerne aussi les couches de raisonnement
- `doc/ongoing/[futur]_REFLEXION_LEIDEN_GRAPHRAG.md` — réflexion sur GraphRAG Microsoft qui a déclenché cette analyse
- `doc/CHANTIER_ATLAS.md` section 7 — réflexion Atlas narratif, Q3 introduit le mécanisme de "dette structurelle" qui est la réponse générique à ce problème
- `doc/ongoing/ADR_PERSPECTIVE_LAYER_ARCHITECTURE.md` — architecture Perspective V2 et coûts de rebuild
- `cockpit/pipeline_defs.yaml` — définition actuelle du pipeline post-import à étendre
- `src/knowbase/claimfirst/post_import/` — code du post-import existant
- `app/scripts/build_perspectives.py` — script de rebuild Perspective à intégrer dans le post-import
