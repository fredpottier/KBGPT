# Plan Architecte : Pont Claim ↔ Chunk — Unification des deux bases

**Version 3.1 — après review ChatGPT + arbitrage architectural + amendements finaux**

---

## Le problème

OSMOSE possède deux bases qui ne se parlent pas :

- **Neo4j** : 34 656 claims structurées avec relations (CONTRADICTS, REFINES, IN_CLUSTER, CHAINS_TO, ABOUT). C'est l'intelligence vérifiée.
- **Qdrant** : Chunks de documents avec embeddings multilingues. C'est la mémoire brute et la preuve verbatim.

Ces bases sont alimentées par des pipelines séparés et ne sont jamais reliées. On ne peut pas passer de l'une à l'autre.

---

## Invariant fondamental

> **Les claims sont la source de vérité. Les chunks sont la preuve.**
>
> Le flux est toujours : **Claims first** → **Chunks as proof**
>
> Jamais : Chunks first → RAG → essayer de raccrocher des claims

---

## Décision : Embeddings dans Neo4j

Neo4j 5.26 supporte les vector indexes natifs (HNSW). Les embeddings vivent sur les nœuds Claim dans Neo4j. Pas de collection Qdrant séparée pour les claims.

**Pourquoi :**
- Une seule requête = vector search + traversée graphe + contradictions
- Pas de double synchronisation
- Cohérence transactionnelle (ACID)
- Simplicité opérationnelle

**Contrat explicite sur les embeddings** (vigilance ChatGPT #2) :

Chaque nœud Claim porte :
```
embedding: List[float]          // vecteur 1024d
embedding_model: String         // "intfloat/multilingual-e5-large"
embedding_version: String       // "v1.0"
embedded_at: DateTime           // date de génération
```

Règles de gouvernance :
- Toutes les claims doivent utiliser le même modèle d'embedding
- Si le modèle change → rebuild complet obligatoire (étape Post-Import)
- Une claim sans embedding est exclue du vector search (filtre `WHERE c.embedding IS NOT NULL`)
- Le vector index Neo4j spécifie la dimension et la fonction de similarité

---

## Ancrage : DocItem first, Chunk as projection (vigilance ChatGPT #1)

Le pont claim↔chunk ne doit PAS faire du chunk le point d'ancrage de vérité. Le chunk est une projection de retrieval, pas une surface de preuve.

### Modèle d'ancrage

```
Claim (Neo4j)
  ├── embedding                     // recherche sémantique
  ├── verbatim_quote                // citation exacte du document source
  ├── doc_id                        // document source
  ├── anchor_docitem_id             // unité documentaire source (DocItem)
  ├── anchor_section_id             // section parente (optionnel, contexte large)
  └── chunk_ids: List[String]       // projection vers chunks Qdrant (CACHE runtime)

Chunk (Qdrant)
  ├── embedding                     // recherche textuelle
  ├── text                          // texte verbatim du passage
  ├── source_file / doc_id          // document source
  ├── page_number / section         // localisation
  └── claim_ids: List[String]       // liens vers claims (CACHE runtime)
```

**Terminologie** (amendement ChatGPT — lever l'ambiguïté) :
- `anchor_docitem_id` = l'unité documentaire précise d'où la claim est extraite. C'est la source de vérité d'ancrage. Un DocItem est une unité atomique du document (paragraphe, cellule de tableau, bullet point).
- `anchor_section_id` = la section parente (optionnelle). Fournit le contexte large.
- `chunk_ids` = projection vers les chunks Qdrant pour affichage runtime. **Ce n'est PAS l'ancrage de vérité.**

**Vérité d'ancrage** = `anchor_docitem_id` + `verbatim_quote`
**Commodité runtime** = `chunk_ids`

### Invariant : cache rebuildable

> **INV-BRIDGE : Les liens bidirectionnels Claim↔Chunk sont rebuildables à 100% et ne sont jamais la source canonique.**

Si le pont chunk↔claim casse (OCR, split/merge de chunks, encoding, re-chunking, rebuild Qdrant), la claim reste valide via son `anchor_docitem_id` et son `verbatim_quote`. Le lien chunk est un cache dénormalisé qui peut être recalculé à tout moment.

Conséquences :
- Un `chunk_ids = []` n'est pas une erreur — c'est une perte de confort UI, pas de validité épistémique
- Tout re-chunking, rebuild Qdrant ou changement de granularité chunk → rebuild automatique du pont (étape Post-Import)
- La suppression/recréation d'un document invalide le cache → rebuild nécessaire

### Algorithme de matching Claim → Chunk

1. Filtrer les chunks Qdrant par `doc_id` (même document)
2. Match exact : `verbatim_quote` est substring du chunk text (normalisation whitespace + lowercase)
3. Match fuzzy : si pas de match exact, ratio Levenshtein > 0.85 sur le verbatim vs chaque chunk
4. Match sémantique : si pas de match fuzzy, cosine similarity entre embedding du verbatim et embeddings des chunks du même doc (seuil > 0.90)
5. Si aucun match → `chunk_ids = []` (pas de lien, la claim reste valide via passage_id)

**Taux de couverture attendu** : 70-85% (les claims issues de tableaux, OCR ou chunks splittés n'auront pas de match).

---

## Flux par use case

### Verify (vérification de texte)

```
Texte utilisateur (FR ou EN)
      │
      ▼
  LLM : découper en assertions
      │
      ▼
  Pour chaque assertion :
      │
      ├─► Embedding (e5-large multilingue)
      │
      ├─► Neo4j vector search sur claims
      │   CALL db.index.vector.queryNodes('claim_embedding', 10, $embedding)
      │   + dans la même requête : CONTRADICTS, ABOUT→Entity
      │
      ├─► LLM : comparer assertion vs claims trouvées
      │   → Verdict : CONFIRMED / CONTRADICTED / INCOMPLETE
      │
      ├─► Si une claim trouvée est elle-même contredite par une autre
      │   → signaler le désaccord dans le verdict
      │
      └─► Hover :
            ├── Verdict + confiance
            ├── Claim pertinente (texte nettoyé)
            ├── Citation longue (chunk via chunk_ids, si disponible)
            ├── Document source (nom lisible)
            └── Contradictions connues (si existent)
```

### Chat (question-réponse)

Le graph-first search existant a 3 modes. Le changement :

```
Mode REASONED (existant, amélioré) :
  Extraction concepts → Graph path search → Evidence via arêtes
  + Les claims sur le chemin ont des embeddings → meilleur scoring
  + Accès aux chunks de preuve pour citations longues

Mode ANCHORED (existant, amélioré) :
  Routing structural via Topics/COVERS
  + Chunks de preuve accessibles

Mode TEXT_ONLY (REFONDU — vigilance ChatGPT) :
  AVANT : Qdrant chunks → RAG classique (bypass KG, ignore contradictions)
  APRÈS : Neo4j vector search sur claims → enrichissement KG → synthèse
  → Le mode TEXT_ONLY passe par le KG. Plus jamais de RAG aveugle.
```

### Wiki (génération d'articles)

```
Concept sélectionné
      │
      ▼
  Neo4j : claims ABOUT cette entité (déjà fait dans EvidencePack)
      │
      ▼  AMÉLIORATION
  Pour chaque claim :
      ├── chunk_ids → Qdrant → contexte verbatim long (paragraphe complet)
      ├── Claims REFINES/QUALIFIES → nuances et précisions
      └── Claims CONTRADICTS → points de désaccord à mentionner
      │
      ▼
  LLM : article enrichi avec contexte documentaire + sources + contradictions
```

---

## Plan d'implémentation

### Phase 1 — Embeddings sur les Claims dans Neo4j

**Script** : `build_claim_embeddings.py`

```python
# 1. Créer le vector index
CREATE VECTOR INDEX claim_embedding IF NOT EXISTS
FOR (c:Claim) ON c.embedding
OPTIONS {indexConfig: {
  `vector.dimensions`: 1024,
  `vector.similarity_function`: 'cosine'
}}

# 2. Pour chaque claim (batch de 500) :
#    - Encoder le texte via e5-large
#    - SET c.embedding = $vector, c.embedding_model = 'multilingual-e5-large',
#      c.embedding_version = 'v1.0', c.embedded_at = datetime()
```

**Intégration pipeline** : Phase 7 persist → chaque claim est persistée avec son embedding.
**Étape Post-Import** : "Indexation embeddings claims" pour rebuild.

**Effort** : 2-3 heures
**Durée exécution** : ~5 min pour 34k claims

### Phase 2 — Pont Claim ↔ Chunk

**Script** : `bridge_claims_chunks.py`

1. Pour chaque claim → chercher le chunk correspondant (algorithme 4 niveaux ci-dessus)
2. Persister `chunk_ids` sur la claim Neo4j
3. Mettre à jour le payload Qdrant du chunk avec `claim_ids`

**Intégration pipeline** : Phase 7 persist → lier au moment de la création.
**Étape Post-Import** : "Pont Claims ↔ Chunks" pour rebuild.

**Effort** : 3-4 heures
**Durée exécution** : ~10-15 min pour 34k claims

### Phase 3 — Refonte du Verify

Remplacer le keyword search par Neo4j vector search. Modifier le hover.

**Effort** : 3-4 heures

### Phase 4 — Refonte du Chat mode TEXT_ONLY

Remplacer Qdrant fallback par Neo4j vector search sur claims + enrichissement KG.

**Effort** : 4-6 heures

### Phase 5 — Amélioration du Wiki

Ajouter le contexte chunk dans le EvidencePackBuilder.

**Effort** : 2-3 heures

---

## Métriques de succès (par couche — vigilance ChatGPT #3)

### Couche Retrieval
| Métrique | Avant | Cible |
|----------|-------|-------|
| Claim recall@10 (vector search) | 0% (pas de vector) | > 80% |
| Latence vector search Neo4j | N/A | < 100ms |
| Cross-langue FR→EN | Non fonctionnel | Fonctionnel |

### Couche Verdict
| Métrique | Avant | Cible |
|----------|-------|-------|
| Précision du verdict (CONFIRMED/CONTRADICTED) | ~50% | > 85% |
| % de contradictions KG correctement remontées | 0% | > 70% |

### Couche Preuve
| Métrique | Avant | Cible |
|----------|-------|-------|
| Couverture pont claim↔chunk | 0% | > 75% |
| % de hover avec preuve pertinente et lisible | ~20% | > 85% |

### Couche Performance
| Métrique | Cible |
|----------|-------|
| Latence verify par assertion | < 3s |
| Latence chat response | < 5s |

---

## Résumé

Le KG est le cerveau. Qdrant est la mémoire brute. L'ancrage de vérité passe par le passage/DocItem, pas par le chunk.

En ajoutant des embeddings gouvernés sur les claims dans Neo4j et des liens chunk↔claim comme cache de projection, chaque question passe d'abord par le KG (recherche sémantique + intelligence relationnelle) puis remonte aux preuves verbatim via les chunks. Le KG n'est jamais bypassé. Les contradictions ne sont jamais ignorées. Chaque réponse est prouvable et sourcée.
