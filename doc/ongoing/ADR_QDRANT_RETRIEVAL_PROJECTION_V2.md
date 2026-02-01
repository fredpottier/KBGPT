# ADR: Rôle de Qdrant dans le Pipeline Stratifié V2

**Statut**: Accepted
**Date**: 2026-01-31
**Auteurs**: Fred, Claude, ChatGPT (collaboration)
**Dépendances**:
- ADR_STRATIFIED_READING_MODEL.md (modèle de lecture stratifiée)
- ADR_EXPLOITATION_LAYER.md (usages A, B, C)

---

## Contexte

### Le problème

Le pipeline stratifié V2 a remplacé le pipeline V1 comme chemin d'import principal. Cette migration a apporté des gains majeurs (ancrage atomique sur DocItem, extraction sémantique typée, ontologie structurée Subject/Theme/Concept/Information), mais a **rompu le lien avec Qdrant** : plus aucune donnée vectorielle n'est persistée.

Conséquence : le service de recherche Graph-First, conçu pour exploiter Qdrant comme substrat de retrieval, est inopérant. Les trois modes de recherche (REASONED, ANCHORED, TEXT_ONLY) dépendent tous de Qdrant pour récupérer des passages textuels. Sans données vectorielles, **aucun usage d'exploitation (A, B, C) ne peut fonctionner**.

### Ce qui existe aujourd'hui

| Composant | État |
|-----------|------|
| Neo4j | Vérité documentaire V2 : Document, Section, DocItem, Subject, Theme, Concept, Information, Relations |
| Qdrant `knowbase` | 0 points (vide) |
| Qdrant `concepts_proto` | 0 points (vide) |
| TypeAwareChunks | Existent dans le cache `.knowcache.json` (Pass 0), jamais vectorisés |
| Informations | Existent dans Neo4j (Pass 1), jamais vectorisées |
| TEI (multilingual-e5-large) | Disponible sur EC2 burst (port 8001), 1024D, cosine |

### Pourquoi le lien a été rompu

Le pipeline V2 a été conçu pour ancrer les Informations directement sur des DocItems (preuve atomique dans Neo4j) au lieu de chunks vectoriels dans Qdrant. C'est architecturalement correct : la vérité est dans le graphe. Mais la **projection retrieval** — nécessaire pour retrouver des passages par similarité sémantique — n'a jamais été reconstruite pour V2.

---

## Décision

### Principe directeur

> **Neo4j = vérité documentaire contextualisée.**
> **Qdrant = index de récupération (retrieval projection), filtrable par structure, concept-aware.**

Qdrant n'est jamais une source de vérité. C'est une projection optimisée pour le retrieval par similarité sémantique. Le graphe Neo4j reste l'unique référence pour les faits, les relations, les ancres et les contradictions.

Cela s'inscrit dans la séparation déjà actée :
- **DocItem = surface de preuve** (Neo4j)
- **TypeAwareChunk = projection retrieval** (Qdrant)

### Architecture cible : dual-layer

Deux layers complémentaires dans Qdrant, répondant à des besoins différents :

#### Layer R — Retrieval (TypeAwareChunks)

**Objectif** : couverture 100% du corpus, fallback RAG, récupération de passages textuels.

| Propriété | Valeur |
|-----------|--------|
| Collection Qdrant | `knowbase_chunks_v2` |
| Source | TypeAwareChunks du cache Pass 0 |
| Granularité | Chunk layout-aware (re-découpé si > 512 tokens) |
| Embedding | multilingual-e5-large, 1024D, cosine |
| Moment de calcul | Pendant le burst (TEI sur EC2, port 8001) |

**ID du point Qdrant** : `hash_stable(tenant_id + doc_id + chunk_id + sub_index)` — déterministe, idempotent. Un re-upsert du même cache produit les mêmes point_ids, sans doublons.

**Payload par point** :

```json
{
  "tenant_id": "default",
  "doc_id": "014_SAP_S4HANA_...",
  "section_id": "default:014_...:sec_3.2",
  "chunk_id": "chunk_abc123",
  "sub_index": 0,
  "parent_chunk_id": "chunk_abc123",
  "kind": "NARRATIVE_TEXT",
  "page_no": 42,
  "page_span_min": 42,
  "page_span_max": 43,
  "item_ids": ["item_1", "item_2"],
  "text_origin": "docling",
  "text": "Le texte original du sous-chunk (affiché, cité)",
  "embedding_text": null
}
```

**Séparation `text` / `embedding_text`** : le champ `text` contient le texte original tel qu'extrait, utilisé pour l'affichage et la citation. Le champ `embedding_text` n'est PAS stocké dans le payload (économie d'espace) — il est utilisé uniquement au moment du calcul de l'embedding puis jeté. Pour Layer R, `embedding_text` = `text` (pas d'enrichissement).

**Usages servis** :
- Usage B (Writing Companion) : recherche de passages par similarité avec le texte utilisateur
- Usages A et C : récupération du texte source étendu autour d'une Information, fallback "zones non couvertes"
- Mode TEXT_ONLY : RAG classique quand le graphe ne permet pas de répondre
- Mode ANCHORED : retrieval filtré par `doc_id` / `section_id`

#### Layer P — Precision (Informations promues)

**Objectif** : recherche précise sur des unités sémantiques validées et concept-aware.

| Propriété | Valeur |
|-----------|--------|
| Collection Qdrant | `knowbase_infos_v2` (nouvelle collection) |
| Source | Informations promues (Pass 1, dans Neo4j) |
| Granularité | Assertion individuelle (phrase/paragraphe court) |
| Embedding | multilingual-e5-large, 1024D, cosine |
| Moment de calcul | Après Pass 1, pendant le reprocess |

**ID du point Qdrant** : `information_id` directement (déjà unique et stable). Idempotent par construction.

**Payload par point** :

```json
{
  "tenant_id": "default",
  "doc_id": "014_SAP_S4HANA_...",
  "section_id": "default:014_...:sec_3.2",
  "information_id": "info_xyz789",
  "docitem_id": "default:014_...:item_42",
  "type": "PRESCRIPTIVE",
  "confidence": 0.9,
  "concept_id": "concept_..._SAP_Global_Security",
  "concept_name": "SAP Global Security",
  "theme_id": "theme_..._Vulnerability_Advisory",
  "text": "Hardening guidelines are based on CIS Benchmark Controls."
}
```

**Séparation `text` / `embedding_text`** : le champ `text` contient l'assertion originale telle qu'extraite — c'est ce qui est **affiché et cité** dans les résultats. Le `embedding_text` (utilisé uniquement pour le calcul du vecteur, jamais stocké dans le payload) est enrichi avec le contexte pour éviter la dilution sémantique sur des phrases courtes :
```
[Concept: SAP Global Security] [Theme: Vulnerability Advisory Services]
Hardening guidelines are based on CIS Benchmark Controls.
```

Le texte enrichi sert à l'embedding, jamais à l'affichage. L'utilisateur voit toujours l'assertion originale (`text`).

**Usages servis** :
- Usage B : challenge corpus-aware (recherche d'assertions qui supportent/contredisent le texte utilisateur)
- Mode REASONED : retrieval d'assertions précises le long de chemins sémantiques du graphe
- Comparaison inter-documents (futur) : assertions comparables via ClaimKey

---

### Chunking retrieval-only pour Layer R

Les TypeAwareChunks V2 font ~3000 chars (~750 tokens). Le modèle `multilingual-e5-large` a une fenêtre effective de 512 tokens. Un embedding sur un texte tronqué dégrade le recall.

**Décision** : les TypeAwareChunks sont re-découpés en **sous-chunks retrieval-only** avant vectorisation.

| Paramètre | Valeur |
|-----------|--------|
| Taille cible | ~400 tokens (~1600 chars) |
| Overlap | 50 tokens (~200 chars) |
| Héritage métadonnées | Le sous-chunk hérite du `section_id`, `doc_id`, `kind`, `page_no` du parent |
| Référence parent | `parent_chunk_id` conservé dans le payload |
| Contrainte section | Un sous-chunk ne franchit **jamais** une frontière de section |
| Alignement DocItem | Préférer couper aux frontières de DocItems quand c'est possible |

**Contrainte d'alignement structurel** : le re-chunking ne doit jamais produire un sous-chunk qui chevauche deux sections. Quand un TypeAwareChunk contient des DocItems de sections différentes, la coupure se fait à la frontière de section, même si le sous-chunk résultant est plus court que la cible. De même, l'alignement sur les frontières de DocItems (`item_ids`) est préféré à une coupure arbitraire au milieu d'un paragraphe.

Ce re-chunking est une opération de projection. Il ne modifie ni les TypeAwareChunks originaux (cache), ni les DocItems (Neo4j). La vérité documentaire n'est pas affectée.

**Justification pour Usage B** : le recall est critique. Si l'utilisateur écrit "le firewall est managé par défaut" et que la contradiction ("FWaaS est en option") se trouve en fin de chunk, la troncation la ferait disparaître.

---

### Identifiants stables et idempotence

Chaque layer utilise un schéma d'ID de point Qdrant **déterministe** qui garantit l'idempotence des upserts :

| Layer | Point ID Qdrant | Justification |
|-------|----------------|---------------|
| Layer R | `UUID5(tenant_id + doc_id + chunk_id + sub_index)` | Déterministe à partir du cache. Un re-upsert du même cache ne crée pas de doublons. |
| Layer P | `information_id` (UUID déjà existant dans Neo4j) | Identité naturelle. Lien direct Neo4j ↔ Qdrant sans table de mapping. |
| Layer C | `concept_id` (UUID déjà existant dans Neo4j) | Idem Layer P. |

**Garantie** : une purge Qdrant suivie d'un re-upsert depuis le cache (Layer R) et Neo4j (Layers P, C) reconstruit un état identique. Pas de migration nécessaire, pas de delta à gérer.

---

### Vectorisation des Concepts (Layer C)

Les Concepts V2 doivent également être vectorisés pour permettre le **concept matching sémantique** dans le search service.

| Propriété | Valeur |
|-----------|--------|
| Collection Qdrant | `concepts_v2` |
| Source | Concepts (Neo4j, Pass 1) |
| Texte embedé | `concept_name` enrichi du `theme_name` |
| Moment de calcul | Après Pass 1, pendant le reprocess |

**ID du point Qdrant** : `concept_id` directement (déjà unique et stable).

**Usage** : quand un utilisateur écrit un texte (Usage B) ou pose une question, le système doit identifier les Concepts du KG sémantiquement proches. Aujourd'hui le concept matching se fait en deux tiers (full-text Neo4j + sémantique Qdrant, fusion RRF). Sans la composante Qdrant, seul le full-text reste — ce qui rate les reformulations et synonymes.

---

## Timing des embeddings dans le pipeline

### Principe : découplage burst / runtime

Le burst (EC2 spot) **produit des artefacts** (cache + embeddings). Le reprocess (local) **consomme ces artefacts** et les distribue vers Neo4j et Qdrant. Le burst n'a jamais besoin de connaître Qdrant. Le reprocess n'a jamais besoin de TEI. Ce découplage garantit que :
- Le burst reste autonome (pas de dépendance vers l'infra locale)
- Le reprocess reste reproductible (re-upsert idempotent depuis le cache)
- Une purge Qdrant + re-upsert depuis le cache suffit à reconstruire l'index

```
BURST (EC2 spot, TEI disponible — produit les artefacts)
  │
  ├─ Pass 0 : Docling → DocItems + TypeAwareChunks → Cache
  │
  ├─ NEW: Layer R embedding (artefact, pas d'upsert)
  │   TypeAwareChunks → re-chunking → TEI → embeddings
  │   Stockage : dans le cache (.knowcache.json), section "retrieval_embeddings"
  │
  └─ Fin burst : cache prêt avec chunks + embeddings pré-calculés
      ⚠️ Aucun upsert Qdrant ici — le burst ne touche pas à Qdrant

REPROCESS (local, TEI non disponible — distribue vers Neo4j + Qdrant)
  │
  ├─ Charge cache → Pass 0 Neo4j (Document, Sections)
  │
  ├─ NEW: Upsert Layer R dans Qdrant (idempotent)
  │   Chunks + embeddings du cache → Qdrant `knowbase_chunks_v2`
  │   Point IDs déterministes → pas de doublons en cas de re-run
  │
  ├─ Pass 1 : LLM → Concepts, Informations → Neo4j
  │
  ├─ NEW: Layer P embedding + upsert
  │   Informations → embedding (modèle local ou API) → Qdrant `knowbase_infos_v2`
  │
  ├─ NEW: Layer C embedding + upsert
  │   Concepts → embedding → Qdrant `concepts_v2`
  │
  └─ Pass 2 : Relations → Neo4j
```

**Note sur l'embedding en reprocess** : TEI n'est pas disponible localement. Options pour Layer P et C :
1. Appel API OpenAI (`text-embedding-3-small`, 1536D — nécessite reconfiguration collections)
2. Modèle local léger (sentence-transformers)
3. Conserver `multilingual-e5-large` en local CPU (lent mais compatible)
4. Endpoint TEI hébergé permanent (coût)

La décision sur le modèle local est reportée. Pour la Phase A, seul Layer R est nécessaire, et les embeddings sont calculés sur l'EC2.

---

## Adaptation du search service

Le search service actuel est construit sur les nœuds V1 (ProtoConcept, CanonicalConcept, DocumentContext, SectionContext). L'adaptation se fait par phases, sans big-bang.

### Phase A — TEXT_ONLY + fallback RAG

**Objectif** : débloquer Usage B en mode minimal.

Modifications :
- Upsert Layer R dans Qdrant (chunks avec embeddings)
- Endpoint simple : `query → embedding → Qdrant search → passages`
- Pas besoin du graphe, pas besoin d'adapter le concept matching
- Filtrage basique par `tenant_id`, optionnellement `doc_id`

**Résultat** : un utilisateur peut soumettre un texte et recevoir les passages les plus proches du corpus. C'est du RAG basique mais fonctionnel.

### Phase B — ANCHORED V2

**Objectif** : réintroduire le graphe comme guide de recherche.

Modifications :
- Adapter le concept matching pour utiliser les Concepts V2 (Neo4j full-text + Qdrant `concepts_v2`)
- Routing structurel via Subject/Theme → `doc_id` / `section_id`
- Filtrage Qdrant Layer R par `section_id` (remplace `context_id` V1)

**Résultat** : le système peut diriger la recherche vers les bonnes sections du corpus en s'appuyant sur la structure du KG.

### Phase C — REASONED + Challenge

**Objectif** : version production de Usage B (Writing Companion).

Modifications :
- Layer P opérationnel (Informations vectorisées)
- Path finding dans le graphe V2 (Concept → Relations → Concept)
- Pour une question/assertion utilisateur :
  1. Recherche Layer P (assertions proches)
  2. Vérification dans le graphe (SUPPORTED / NOT_DOCUMENTED / TENSION)
  3. Fallback Layer R si couverture insuffisante
- Traçabilité : chaque verdict est lié à des Informations sources

**Résultat** : Usage B complet — feedback corpus-aware, traçable, explicable.

---

## Rationale

### Pourquoi dual-layer et pas un seul ?

- **Layer R seul** : couverture complète mais pas de recherche "concept-aware". Le RAG retourne des passages sans savoir s'ils sont validés comme Information dans le KG.
- **Layer P seul** : recherche précise mais couverture partielle (~65% du contenu utile est promu en Information). Pas de fallback sur le texte brut.
- **Les deux** : Layer P pour la précision (assertions validées), Layer R pour la couverture (tout le texte, y compris ce qui n'a pas été extrait en Information).

### Pourquoi re-chunking au lieu d'accepter la troncation ?

Pour Usage B, le recall prime. L'utilisateur peut écrire n'importe quelle assertion, et le système doit trouver le passage qui la supporte ou la contredit, même s'il est en fin de chunk. La troncation à 512 tokens est un risque acceptable pour du RAG généraliste, pas pour du challenge documentaire.

### Pourquoi embeddings pendant le burst ?

- TEI est déjà chargé en VRAM sur l'EC2 spot (à côté de Qwen 14B)
- Pas de coût additionnel (ni API, ni infra)
- Les chunks existent dans le cache dès Pass 0
- Le cache devient autosuffisant : structure + vecteurs

### Pourquoi pas d'embedding pendant le reprocess pour Layer R ?

- TEI n'est pas disponible localement
- Ajouter un modèle d'embedding local alourdit le setup
- Le burst produit déjà tout le nécessaire — le reprocess n'a qu'à upserter

---

## Non-goals

| Ce que cet ADR ne fait PAS | Pourquoi |
|---|---|
| Faire de Qdrant une source de vérité | Neo4j est l'unique vérité. Qdrant est reconstituable depuis le cache + Neo4j. |
| Rétablir le schéma V1 (ProtoConcept, CanonicalConcept) | V2 est le modèle cible. Pas de retour arrière. |
| Imposer un modèle d'embedding spécifique | `multilingual-e5-large` est le choix pragmatique actuel. Changeable quand un benchmark le justifie. |
| Refactorer le search service en une fois | Approche par phases (A → B → C). |
| Définir l'UI des usages A, B, C | C'est le rôle de l'ADR Exploitation Layer. |

---

## Risques et mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Re-chunking produit trop de points | Qdrant plus gros, recherche plus lente | Monitoring du nombre de points. Avec ~400 chunks/doc × 2-3 sous-chunks = ~1000 points/doc, largement dans les capacités de Qdrant. |
| Embeddings dans le cache augmentent la taille | Fichiers cache plus gros | 1000 embeddings × 1024 × 4 bytes = ~4 MB. Négligeable vs le cache actuel. |
| Modèle e5-large trop vieux | Recall insuffisant | Benchmark sur cas Usage B réels. Migration de modèle = re-embed + re-upsert, faisable sans changer l'architecture. |
| Drift entre Neo4j et Qdrant | Qdrant désynchronisé après modification KG | Qdrant est reconstituable. En cas de doute : purge + re-upsert depuis cache + Neo4j. |
| Informations trop courtes pour un bon embedding (Layer P) | Matching bruité | Enrichissement du texte embedé avec contexte (concept, theme). À valider empiriquement. |

---

## Critères de succès

### Phase A (Layer R + TEXT_ONLY)

| Critère | Mesure |
|---------|--------|
| Qdrant alimenté | `knowbase_chunks_v2` contient des points après import burst + reprocess |
| Idempotence | Deux re-upserts successifs du même cache → même nombre de points, pas de doublons |
| Recall@10 sur jeu de test Usage B | Constituer 10-20 paires (assertion utilisateur, passage attendu). Recall@10 ≥ 0.7 |
| Fallback RAG | Question hors KG → au moins 1 passage pertinent dans le top 5 |

**Jeu de test Usage B** : à constituer manuellement à partir du document RISE with SAP (assertions vraies, assertions fausses, reformulations). Ce jeu de test servira de benchmark pour toutes les phases.

### Phase B (ANCHORED V2)

| Critère | Mesure |
|---------|--------|
| Concept matching V2 | Concepts du KG identifiés dans une query utilisateur (Precision@5 ≥ 0.6) |
| Filtrage structurel | Recherche avec filtre `section_id` retourne des résultats cohérents avec la section |
| Recall@10 avec filtre | ≥ Recall@10 Phase A (le filtrage ne doit pas dégrader le recall) |

### Phase C (REASONED + Usage B)

| Critère | Mesure |
|---------|--------|
| Challenge fonctionnel | Phrase utilisateur → verdict SUPPORTED/NOT_DOCUMENTED/TENSION |
| Traçabilité | Chaque verdict lié à des Informations sources avec `information_id` + `docitem_id` |
| Recall@10 Layer P | ≥ 0.8 sur le jeu de test Usage B (assertions proches retrouvées) |
| Couverture dual-layer | Layer P + Layer R combinés ≥ 0.9 Recall@10 (la complémentarité améliore le recall) |

---

## Historique

| Date | Modification |
|------|-------------|
| 2026-01-31 | Création — diagnostic rupture Qdrant, décision dual-layer, roadmap 3 phases |
| 2026-01-31 | Révision — corrections A-F : découplage burst/runtime, collections versionnées, IDs stables + idempotence, re-chunking section-aligned, séparation text/embedding_text, critères Recall@k |
