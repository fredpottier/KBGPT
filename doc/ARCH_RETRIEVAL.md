# Architecture Retrieval & Synthese OSMOSIS

> **Niveau de fiabilite** : Code-verified (Mars 2026). Chaque composant est annote : **ACTIF** (branche et utilise en prod) / **CODE PRESENT** (existe mais non branche) / **DESIGN** (spec uniquement).

*Document consolide — Mars 2026*

---

## 1. Vue d'ensemble

OSMOSIS est un systeme de Q&A documentaire qui combine un Knowledge Graph (Neo4j) avec une base vectorielle (Qdrant) pour produire des reponses tracables et enrichies. L'architecture de retrieval repose sur trois principes :

1. **Graph-Guided RAG** — Le KG enrichit la synthese, pas le retrieval. Les chunks Qdrant restent identiques a ceux d'un RAG classique ; le KG produit un bloc de contexte separe injecte dans le prompt LLM.

2. **Signal-Driven** (pas Intent-Classification) — Au lieu de classifier la question en types (A/B/C/D) via un IntentResolver, le systeme detecte des *signaux* documentaires dans les claims KG (tensions, evolutions, couverture). Si aucun signal n'est detecte, le pipeline est un RAG pur (passthrough).

3. **Trois modes de reponse** (degradation gracieuse) :

| Mode | Condition | Comportement |
|------|-----------|-------------|
| **Reasoned** | Chemin semantique dans le KG avec preuves | Chaine cross-doc + preuves par arete |
| **Anchored** | Ancrage structurel (Topics/COVERS) | Scope documentaire + citations |
| **Text-only** | Rien dans le KG / silence des signaux | RAG classique, aucune modification |

Le mode Text-only est le defaut. Le KG est toujours interroge en premier, mais son silence est un resultat normal qui declenche le RAG pur sans penalite.

### Invariant fondamental

> **OSMOSIS >= RAG sur toutes les metriques, par construction.**

Si le KG ne detecte aucun signal, les chunks sont exactement ceux du RAG. Le KG ne peut qu'ajouter de la valeur (contexte supplementaire) sans jamais degrader le socle.

### Fichiers cles

| Composant | Fichier |
|-----------|---------|
| Orchestration search | `src/knowbase/api/services/search.py` |
| Retrieval Qdrant pur | `src/knowbase/api/services/retriever.py` |
| Detection de signaux KG | `src/knowbase/api/services/kg_signal_detector.py` |
| Politique signal→action | `src/knowbase/api/services/signal_policy.py` |
| Synthese LLM | `src/knowbase/api/services/synthesis.py` |
| Graph-Guided Search (V1) | `src/knowbase/api/services/graph_guided_search.py` |
| Rechunker Layer R | `src/knowbase/retrieval/rechunker.py` |
| Qdrant Layer R | `src/knowbase/retrieval/qdrant_layer_r.py` |

---

## 2. Flux de recherche

Le flux complet de `search_documents()` dans `search.py` :

```
Question utilisateur
    |
    v
[1] embed_query() ──────────────────────────── retriever.py
    | Encode la question via SentenceTransformer
    | Retourne un vecteur (multilingual-e5-large, 1024d)
    v
[2] _search_claims_vector() ────────────────── search.py:71
    | Neo4j vector search sur index 'claim_embedding'
    | Score > 0.65, top_k = 10
    | Retourne : claim_id, text, entity_names,
    |            contradiction_texts (REFINES/QUALIFIES/CONTRADICTS),
    |            chunk_ids (pont vers Qdrant)
    v
[3] retrieve_chunks() ─────────────────────── retriever.py:52
    | Qdrant vector search pur (invariant RAG)
    | Collection knowbase_chunks_v2
    | top_k=10, score_threshold=0.5
    | Filtres optionnels : solution, release_id, doc_filter
    | Retourne RetrievalResult(chunks, query_vector, docs_involved)
    |
    | ⏳ EVOLUTION PREVUE : Hybrid BM25+dense via Qdrant RRF
    |    Qdrant v1.10+ supporte hybrid queries (dense + sparse/BM25) + fusion RRF
    |    cote serveur. Levier critique pour les termes exacts (noms produits SAP,
    |    versions, codes TLS) ou le dense-only est fragile.
    |    Effort estime : 1-3 jours. Voir section 11.8.
    v
[4] Phase C light — KG Document Scoping ───── search.py:670
    | Si des claims KG ont des tensions (contradiction_texts non vides) :
    |   → Identifier les doc_ids en tension absents du retrieval initial
    |   → Lancer un retrieve_chunks() supplementaire filtre sur ces docs
    |   → Ajouter les chunks manquants (sans doublons)
    v
[5] _build_kg_context_block() ─────────────── search.py:361
    | Construit un bloc KG SEPARE (pas injecte dans les chunks)
    | Contenu : entites identifiees, tensions detectees,
    |           faits complementaires de docs absents du RAG
    | Limite a ~600 chars (guard-rail Sprint 0 : -8pp si > 150 tokens)
    v
[6] _enrich_chunks_with_kg() ──────────────── search.py:434
    | Propage entity_names et contradiction_texts sur les chunks
    | (metadata pour le frontend, pas dans le texte du chunk)
    | Match en 2 niveaux :
    |   1. Bridge exact chunk_id (claim.chunk_ids → chunk.chunk_id)
    |   2. Same-doc fallback (claims du meme doc_id)
    v
[7] _get_kg_traversal_context() ───────────── search.py:1629
    | Traversee multi-hop CHAINS_TO (1-3 hops)
    | Extraction regex des entites de la question (acronymes, termes capitalises)
    | Cypher : Entity → Claim ABOUT → CHAINS_TO*1..3
    | Priorise les chaines cross-doc et les entites specifiques
    | Genere un markdown "Cross-document reasoning" injecte dans le prompt
    | + recherche Qdrant ciblee sur les docs de la chaine
    v
[8] _get_qs_crossdoc_context() ────────────── search.py
    | QuestionDimension vector search (index qd_embedding)
    | Traverse QD → QuestionSignature → Claim → chunk_ids
    | Genere un bloc "Cross-document comparisons" avec valeurs extraites
    v
[9] detect_signals() ──────────────────────── kg_signal_detector.py:54
    | Analyse les claims KG deja en memoire (zero appel Neo4j supplementaire)
    | Detecte 4 types de signaux :
    |   - tension (REFINES/QUALIFIES/CONTRADICTS cross-doc)
    |   - temporal_evolution (meme entite, docs differents)
    |   - coverage_gap (docs avec claims absents des chunks Qdrant)
    |   - exactness (QD match avec extracted_value)
    | Si aucun signal → SignalReport.is_silent = True
    v
[10] build_policy() ───────────────────────── signal_policy.py:52
     | Transforme SignalReport en SignalPolicy (regles deterministes)
     | Si silence → passthrough (RAG pur, zero modification)
     | Sinon :
     |   - tension → fetch_missing_tension_docs + reorder + inject
     |   - evolution → inject_kg_traversal
     |   - coverage → elargir retrieval aux docs manquants
     |   - exactness → inject_qs_crossdoc
     | synthesis_additions : instructions textuelles pour le prompt LLM
     | Guard-rail : max 3 instructions, max ~150 tokens
     v
[11] LatestSelector boost ─────────────────── search.py:836
     | Si 2+ release_ids dans les resultats et pas de filtre explicite :
     |   → Boost x1.3 les chunks de la release la plus recente
     |   → Re-tri par score
     v
[12] synthesize_response() ────────────────── synthesis.py:118
     | Formate chunks + graph_context_text + session_context_text
     | Appel LLM tiered (Haiku > Qwen local)
     | Retourne reponse synthetisee + confiance
```

### Points d'attention sur le flux

- **Les etapes 2 et 3 sont paralleles dans l'intent** : les claims KG (etape 2) servent a l'enrichissement et a la detection de signaux, les chunks Qdrant (etape 3) sont la base invariante de la reponse.
- **Le graph_guided_search.py (Phase 2.3) est desactive** en mode ClaimFirst. Le commentaire dans `search.py` (ligne 763) note : *"graph_guided_search depend de CanonicalConcept + index concept_search + collection osmos_concepts (OSMOSE semantic pipeline) qui n'existent pas en mode ClaimFirst."*
- **La memoire conversationnelle** (session_id) est geree a part : le contexte de session est passe au LLM pour la synthese, mais n'enrichit PAS la requete vectorielle (fix 2026-01-23 pour eviter la pollution cross-question).

---

## 3. Concept Matching Engine (Phase 2.7)

### Contexte

Le Concept Matching Engine resout le probleme de decouverte de concepts dans le KG a partir d'une question utilisateur. Sans matching fiable, toute la chaine KG (relations transitives, clusters, bridges) est inutile.

**Bug fondateur** : la methode originale `extract_concepts_from_query()` avait 4 bugs critiques (LIMIT 500 sur 11796 concepts, filtre `len(word) > 3`, match substring exact, pas de ranking).

### Architecture en 3 paliers

Implemente dans `graph_guided_search.py` (Phase 2.7, decembre 2025).

#### Palier 1 — Full-Text Neo4j

```cypher
CALL db.index.fulltext.queryNodes('concept_search', $query_tokens)
YIELD node, score
WHERE node.tenant_id = $tenant_id
RETURN node.concept_id, node.canonical_name, score
ORDER BY score DESC LIMIT 50
```

Index `concept_search` sur : `canonical_name`, `name`, `surface_form`, `summary`, `unified_definition`.

Score ajuste par longueur (eviter biais "concepts bavards") :
```python
lex_adj = lex_score / math.log(20 + len_text)
```

Ranking palier 1 : `0.60 * norm(lex_adj) + 0.25 * norm(pop) + 0.15 * norm(quality)`

#### Palier 2 — Vector Search Qdrant

Collection `knowwhere_concepts` : 11796 concepts, embeddings 1024d (multilingual-e5-large).

Texte d'embedding : `"{canonical_name}. Type: {concept_type}. {summary}"`

Resout les problemes FR→EN (ex: "IA" → "AI", "RGPD" → "GDPR") que le full-text ne peut pas traiter.

#### Fusion RRF (Reciprocal Rank Fusion)

```python
Score final = 0.55 * semantic_norm + 0.35 * lexical_norm
            + 0.05 * quality_norm + 0.05 * log(popularity)_norm
```

Constante RRF k=60. Diversity re-ranking : max 4 concepts par `concept_type`, top 10 retournes.

#### Palier 3 — Surface Forms

71 436 surface forms generees (variantes typographiques, casing, tirets, pluriel).
Approche hybride sans LLM : dictionnaire de traductions pour acronymes reglementaires + variantes automatiques.

### Resultats empiriques

| Palier | Golden Set | Performance |
|--------|-----------|-------------|
| Palier 1 seul | 45% | ~50ms |
| Palier 1+2 | 67% | ~80ms (calls suivants) |
| Palier 1+2+3 | **78%** | ~80ms |

Amelioration cle : FR→EN passe de 0% (P1) a 100% (P1+2). "High-Risk AI System" trouve via surface forms.

### Benchmark KG vs No-KG (decembre 2025)

| Configuration | Precision decouverte concepts |
|---------------|-------------------------------|
| RAG classique (sans KG) | 31% (4/13) |
| Graph-Guided RAG (avec KG) | **62%** (8/13) |

Le Knowledge Graph double la precision de decouverte de concepts.

### Niveaux d'enrichissement

Definis dans `graph_guided_search.py` via `EnrichmentLevel` :

| Niveau | Temps | Usage | Description |
|--------|-------|-------|-------------|
| `NONE` | 0ms | Desactive | Pas d'enrichissement KG |
| `LIGHT` | ~100ms | Concepts lies | Concept matching seul |
| `STANDARD` | ~250ms | **Recommande** | Concepts + relations + clusters |
| `DEEP` | ~3 minutes | **Offline only** | InferenceEngine NetworkX (betweenness, Louvain) |

**Regle** : ne JAMAIS utiliser `DEEP` pour des requetes temps-reel (~12000 noeuds).

### Etat actuel (mars 2026)

Le Concept Matching Engine est **desactive en production** car le pipeline ClaimFirst utilise une ontologie differente (Claim/Entity/ClaimCluster au lieu de CanonicalConcept). L'index `concept_search` et la collection `osmos_concepts` n'existent pas en mode ClaimFirst. L'enrichissement KG passe desormais par le traversal CHAINS_TO (Entity → Claim → CHAINS_TO) et le signal detector.

---

## 4. Graph-Guided Search

### Architecture originale (Phase 2.3)

Implementee dans `graph_guided_search.py`. Enrichit la recherche vectorielle avec des insights du Knowledge Graph :

```
Question → Embedding → Top-K chunks
                        +
              Enrichissement KG :
              - Concepts extraits (Concept Matching Engine)
              - Relations transitives (GDS pathfinding)
              - Concepts lies (meme cluster)
              - Bridge concepts
                        ↓
              Reponse enrichie + insights connexes
```

### Relations semantiques

Approche **DENYLIST** (pas allowlist) pour le pathfinding. Cela **remplace** la logique whitelist stricte de l'ADR Navigation Layer original (Jan 2026). La DENYLIST a ete adoptee car : (1) une whitelist oublie silencieusement les nouvelles relations, (2) une DENYLIST est plus stable — on n'exclut que les relations faibles/techniques, tout le reste est semantique par defaut :

```python
# graph_guided_search.py — Relations EXCLUES
EXCLUDED_RELATION_TYPES = frozenset({
    "INSTANCE_OF", "MERGED_INTO", "COVERS", "HAS_TOPIC",
    "MENTIONED_IN", "HAS_SECTION", "CONTAINED_IN",
    "CO_OCCURS", "APPEARS_WITH", "CO_OCCURS_IN_DOCUMENT",
})
```

Toute relation non exclue est consideree semantique pour le pathfinding. Cela evite le bug ou de nouvelles relations (INTEGRATES_WITH, USES) seraient ignorees.

Relations semantiques indicatives (non exhaustif) :
```
REQUIRES, ENABLES, PREVENTS, CAUSES, APPLIES_TO, DEPENDS_ON,
MITIGATES, PART_OF, DEFINES, EXAMPLE_OF, GOVERNED_BY,
CONFLICTS_WITH, USES, INTEGRATES_WITH, COMPLIES_WITH,
RELATED_TO, SUBTYPE_OF, EXTENDS, VERSION_OF, PRECEDES,
REPLACES, DEPRECATES, ALTERNATIVE_TO, TRANSITIVE
```

### Traversee CHAINS_TO (implementation active)

La seule forme d'enrichissement KG active en production est la traversee multi-hop via `_get_kg_traversal_context()` dans `search.py` :

1. **Extraction d'entites** : regex sur la question (acronymes, termes capitalises, expressions techniques)
2. **Requete Cypher** : `Entity → Claim ABOUT → CHAINS_TO*1..3`
3. **Priorisation** : nombre de docs distincts DESC, cross-doc d'abord, hops longs
4. **Resultat** : markdown "Cross-document reasoning" injecte dans le contexte LLM

```cypher
MATCH (e:Entity {tenant_id: $tid})
WHERE toLower(e.normalized_name) CONTAINS toLower(candidate)
MATCH (start_claim:Claim)-[:ABOUT]->(e)
MATCH path = (start_claim)-[:CHAINS_TO*1..3]->(end_claim:Claim)
```

### QuestionDimension routing

Implementee dans `_search_via_question_dimensions()` (`search.py`) :

1. Embedding de la question via le meme modele que le corpus
2. Vector search Neo4j sur l'index `qd_embedding` (382 QuestionDimensions, seuil 0.75)
3. Traversee QD → QuestionSignature → Claim
4. Recuperation des chunks Qdrant exacts via `chunk_ids` (bridge KG → Qdrant)

C'est le differenciateur OSMOSIS : au lieu de chercher des chunks par similarite, on identifie QUELLE QUESTION FACTUELLE est posee, puis on recupere les reponses extraites de chaque document avec leurs preuves.

**Couverture** : 382 QD + 755 QS couvrent 4.8% des claims (gating volontairement restrictif : ne retient que les faits comparables — valeurs numeriques, versions, seuils).

---

## 5. Architecture Signal-Driven

### Pourquoi l'IntentResolver a ete abandonne

Le Sprint 1 (mars 2026) a implemente un IntentResolver a 2 passes :

- **Passe 1** : 27 prototypes embeddes repartis en 4 types (A factuel simple, B comparatif, C audit, D comparable). Cosine similarity avec la question, defaut Type A si confiance < 0.35.
- **Passe 2** : reclassification post-retrieval par signaux KG (tensions, multi-doc, QD match).

**Resultat catastrophique** : 75% des questions factuelles simples (Type A attendu) etaient classees Type C (audit/completude). Les prototypes C ("What do all documents say about X?") sont trop attracteurs car l'embedding capture la semantique du sujet, pas la structure interrogative.

Distribution observee vs attendue sur 100 questions T1 human :

| Type | Attendu | Observe | Ecart |
|------|---------|---------|-------|
| A (factuel simple) | ~85-90% | **25%** | -60pp |
| B (comparatif) | ~5% | 0% | -5pp |
| C (audit) | ~5-10% | **75%** | +65pp |
| D (comparable) | ~0-2% | 0% | 0pp |

**Consequences** :
- Le hard constraint Type A ("chunks identiques au RAG") etait contourne pour 75% des questions
- Le chunk_organizer appliquait `cluster_coverage` (round-robin par document) au lieu de `raw`
- L'irrelevant +8pp vs RAG pouvait venir de cette reorganisation inappropriee

**Decision** : abandonner la classification par prototypes embeddes. Les options evaluees (corriger les prototypes, LLM classifier, marqueurs explicites) ont toutes ete ecartees. A la place : architecture signal-driven.

### KG Signal Detector

Implemente dans `kg_signal_detector.py`. Detecte les signaux documentaires a partir des claims KG deja en memoire (zero appel Neo4j supplementaire).

```python
@dataclass
class Signal:
    type: str       # "tension", "temporal_evolution", "coverage_gap", "exactness"
    strength: float  # 0.0-1.0
    evidence: dict[str, Any]
```

**4 signaux detectes** :

| Signal | Detection | Force |
|--------|-----------|-------|
| `tension` | Claims avec `contradiction_texts` non vides, 2+ docs en tension | `min(1.0, nb_tensions / 5)` |
| `temporal_evolution` | Meme entite (entity_name) dans 2+ documents distincts | `min(1.0, nb_entites_multi_doc / 3)` |
| `coverage_gap` | Doc_ids dans les claims KG absents des chunks Qdrant | `min(1.0, nb_docs_manquants / 3)` |
| `exactness` | QuestionSignature avec `extracted_value` et confiance >= 0.7 | `max(confidence)` des QS matchees |

**Le silence est le resultat normal** : `SignalReport.is_silent == True` declenche le RAG pur.

### Signal Policy

Implementee dans `signal_policy.py`. Transforme un `SignalReport` en `SignalPolicy` (regles deterministes, zero appel externe).

```python
@dataclass
class SignalPolicy:
    fetch_missing_tension_docs: bool = False
    tension_doc_ids: set[str] = field(default_factory=set)
    reorder_by_tensions: bool = False
    inject_kg_enrichment: bool = False
    inject_kg_traversal: bool = False
    inject_qs_crossdoc: bool = False
    synthesis_additions: list[str] = field(default_factory=list)
```

**Regles** :

| Signal | Actions declenchees |
|--------|---------------------|
| `tension` | fetch_missing_tension_docs, reorder_by_tensions, inject_kg_enrichment, inject_kg_traversal, instruction "Present BOTH positions" |
| `temporal_evolution` | inject_kg_traversal, instruction "Distinguish earlier vs current" |
| `coverage_gap` | fetch_missing_tension_docs (reutilise le meme mecanisme) |
| `exactness` | inject_qs_crossdoc, instruction "Lead with exact value" |
| silence | `SignalPolicy()` — passthrough, zero modification |

**Guard-rail** : max 3 instructions supplementaires, max ~150 tokens de contexte KG injecte dans le prompt (lecon Sprint 0 : -8pp factual avec 144 tokens de bloc KG).

---

## 6. Navigation Layer

### Architecture

Implementee a 100% (janvier 2026) dans `navigation/`. Couche de navigation independante de la couche de raisonnement.

**Separation epistemique non-negociable** :
- **Semantic Relations Layer** : edges types entre concepts (REQUIRES, ENABLES...), evidence obligatoire
- **Navigation Layer** : Concept → ContextNode, ContextNode → Document. Strictement non semantique.

### Types de ContextNode

| Type | context_id | Cardinalite | Usage |
|------|-----------|-------------|-------|
| `DocumentContext` | `doc:{document_id}` | 1 par document | Navigation corpus |
| `SectionContext` | `sec:{document_id}:{section_hash}` | ~5-20 par doc | Granularite de preuve |
| `WindowContext` | `win:{chunk_id}` | 1 par chunk | **Desactive par defaut** |

WindowContext desactive par defaut (cardinalite lineaire, cap a 50 par document, traversal depth max 1 hop).

### Relations Navigation

| Relation | Direction | Proprietes |
|----------|-----------|-----------|
| `MENTIONED_IN` | CanonicalConcept → ContextNode | count, weight, first_seen |
| `IN_DOCUMENT` | ContextNode → Document | — |
| `CENTERED_ON` | WindowContext → DocumentChunk | — |

### Non-Promotion Clause

**Regle fondamentale** : aucun edge de la Navigation Layer ne peut etre "promu" vers la Semantic Layer. La co-occurrence peut *suggerer* ou chercher, jamais *affirmer* une relation.

### Semantique des poids

Le `weight` sur `MENTIONED_IN` est une frequence normalisee dans le contexte donne. Il **ne signifie pas** : importance conceptuelle, centralite semantique, probabilite ou relation causale.

**Comparabilite** : uniquement au sein du meme type de ContextNode, au sein du meme document. Jamais cross-type ni cross-tenant.

### Usages autorises

| Usage | Autorise |
|-------|----------|
| Explorer voisins contextuels | Oui |
| Router une recherche | Oui |
| Afficher en UI (liens pointilles) | Oui |
| Inferer des relations | **Non** |
| Calculer importance | **Non** |
| Alimenter RAG reasoning | **Non** |

### Anti-patterns documentes

1. **Interpreter la co-occurrence comme relation** : deux concepts dans le meme contexte ne partagent pas necessairement de lien causal.
2. **Confondre centralite et importance** : un concept tres mentionne peut etre un terme generique.
3. **Utiliser navigation pour le ranking semantique** : le ranking doit utiliser relations semantiques et embeddings.

### Implementation

```
navigation/
├── types.py                     # ContextNode, DocumentContext, SectionContext, WindowContext
├── navigation_layer_builder.py  # Builder Neo4j (create, link, compute weights)
└── graph_lint.py                # 4 regles lint (NAV-001 a NAV-004)

api/routers/navigation.py        # 4 endpoints REST
```

Graph lint (4 regles) :
- NAV-001 : Interdire edges navigation Concept→Concept
- NAV-002 : Interdire predicats semantiques vers ContextNode
- NAV-003 : Whitelist RAG (jamais MENTIONED_IN/IN_DOCUMENT)
- NAV-004 : Validation de coherence

---

## 7. Rechunker & Layer R

### Principe

Les TypeAwareChunks V2 font ~3000 chars (~750 tokens). Le modele `multilingual-e5-large` a une fenetre effective de 512 tokens. Un embedding sur un texte tronque degrade le recall. Le rechunker re-decoupe les chunks pour optimiser la qualite des embeddings.

### Rechunker (`rechunker.py`)

Fonction principale : `rechunk_for_retrieval()`

```python
def rechunk_for_retrieval(
    chunks: List[TypeAwareChunk],
    tenant_id: str,
    doc_id: str,
    target_chars: int = 1500,
    overlap_chars: int = 200,
    section_titles: Optional[dict] = None,
) -> List[SubChunk]:
```

**Pipeline V2 en 4 etapes** :
1. **Filtrage qualite** — supprime chunks vides/trop courts, fusionne titres isoles
2. **Consolidation par section** — fusionne cross-type dans meme section
3. **Decoupe avec overlap** — sliding window target_chars avec overlap
4. **Force-merge tiny** — filet securite pour chunks < 100 chars

**Seuils de filtrage** :
- `MIN_CHARS_MEANINGFUL = 30` (NARRATIVE_TEXT)
- `MIN_CHARS_NON_NARRATIVE = 15` (TABLE/FIGURE/CODE)
- `MIN_WORD_COUNT = 3`

**Strategie de coupe** (3 niveaux) :
1. Fin de phrase (`. ! ?`) dans les 200 derniers chars de la fenetre
2. Fin de ligne (`\n`) dans les 200 derniers chars
3. Hard cut a target_chars (garantit terminaison)

La regex de fin de phrase exclut les faux positifs : numeros de section (15.3.5), abbreviations (e.g.), URLs (sap.com), decimaux (3.14).

**Protection des blocs structurels** :
- Blocs visuels (`═══ VISUAL CONTENT ... ═══ END VISUAL CONTENT`) : jamais coupes
- Tableaux markdown : decoupe avec header replay si > `MAX_ATOMIC_TABLE_CHARS` (3000 chars)
- Listes numerotees (3+ items) : protegees comme bloc atomique

### SubChunk

```python
@dataclass
class SubChunk:
    chunk_id: str           # ID du chunk parent
    sub_index: int          # Index du sous-chunk (0 si non decoupe)
    text: str               # Texte original (affiche/cite)
    parent_chunk_id: str
    section_id: Optional[str]
    doc_id: str
    tenant_id: str
    kind: str               # ChunkKind.value
    page_no: int
    page_span_min: Optional[int]
    page_span_max: Optional[int]
    item_ids: List[str]
    text_origin: Optional[str]
    section_title: Optional[str]

    def point_id(self) -> str:
        """UUID5 deterministe pour idempotence Qdrant."""
        key = f"{self.tenant_id}:{self.doc_id}:{self.chunk_id}:{self.sub_index}"
        return str(uuid.uuid5(OSMOSE_NAMESPACE, key))
```

L'ID Qdrant est deterministe (UUID5) : un re-upsert du meme cache produit les memes points, sans doublons.

### Layer R (`qdrant_layer_r.py`)

Collection Qdrant `knowbase_chunks_v2` :
- Vecteurs 1024d, distance cosine
- Payload indexes sur `axis_release_id` et `axis_version` (keyword)
- Upsert idempotent via `upsert_layer_r()`
- Suppression par document pour re-import

```python
COLLECTION_NAME = "knowbase_chunks_v2"
VECTOR_SIZE = 1024
DISTANCE = Distance.COSINE
```

### Bridge Claims → Chunks

Chaque Claim Neo4j a un champ `chunk_ids[]` qui pointe vers les chunks Qdrant (format `default:DOC_ID:#/texts/N`). Le mapping est 100%. La fonction `_fetch_chunks_for_claims()` dans `search.py` utilise ce bridge pour recuperer les chunks exacts pointes par les claims KG, au lieu de faire un vector search aveugle.

```python
# Bridge : claim.chunk_ids → qdrant scroll(MatchAny)
scroll_result = qdrant_client.scroll(
    collection_name=collection_name,
    scroll_filter=Filter(must=[
        FieldCondition(key="chunk_id", match=MatchAny(any=batch))
    ]),
    limit=len(batch),
    with_payload=True,
    with_vectors=False,
)
```

### Architecture dual-layer (ADR Qdrant V2, planifiee)

L'ADR `ADR_QDRANT_RETRIEVAL_PROJECTION_V2.md` definit une architecture dual-layer non encore implementee :

| Layer | Collection | Source | Usage |
|-------|-----------|--------|-------|
| **Layer R** (Retrieval) | `knowbase_chunks_v2` | TypeAwareChunks cache Pass 0 | **Implemente** — couverture 100% corpus, fallback RAG |
| **Layer P** (Precision) | `knowbase_infos_v2` | Informations promues (Pass 1, Neo4j) | **Non implemente** — recherche precise concept-aware |
| **Layer C** (Concepts) | `concepts_v2` | Concepts Neo4j | **Non implemente** — concept matching V2 |

Layer P permettrait la recherche sur des assertions individuelles validees, avec embedding enrichi du contexte conceptuel. Layer C permettrait le concept matching semantique sur l'ontologie V2.

---

## 8. Synthese LLM

### Architecture tiered

Implementee dans `synthesis.py` :

| Tier | Modele | Cout | Usage | Condition |
|------|--------|------|-------|-----------|
| **Tier 1** | Claude Haiku 4.5 | ~$0.004/question | Defaut (synthese) | `ANTHROPIC_API_KEY` disponible |
| **Tier 2** | Qwen 14B (local via routeur) | $0 | Fallback | Si Tier 1 echoue |

Le modele Haiku est configurable via `OSMOSIS_SYNTHESIS_MODEL` (defaut : `claude-haiku-4-5-20251001`).

```python
# Tier 1 : Claude Haiku (API)
client = anthropic.Anthropic(api_key=anthropic_key)
response = client.messages.create(
    model=haiku_model,
    max_tokens=2000,
    system=SYSTEM_MSG,
    messages=[{"role": "user", "content": prompt}],
    temperature=0.3,
)
```

### Prompt de synthese (SYNTHESIS_PROMPT)

Le prompt est **domain-agnostic** (ne mentionne aucun domaine specifique). Regles principales :

1. **Synthesize** a partir des sources
2. **Cross-document reasoning (PRIORITE)** : si la section "Cross-document reasoning" est fournie, structurer la reponse autour des chaines (pas des chunks individuels)
3. **Citations obligatoires** : format `(Source: Document ABC, slide 12)`
4. **Partial information rule (CRITICAL)** : repondre avec ce qui est disponible, ne JAMAIS refuser si les sources contiennent de l'info meme partielle ou tangentielle
5. **Contradictions** : presenter TOUTES les versions avec leurs sources
6. **Cross-document comparisons** : section dediee pour EVOLUTION, CONTRADICTION, AGREEMENT
7. **Visual content** : langage conditionnel pour les interpretations de diagrammes AI
8. **Meme langue** que la question

### System message

```
"You are a precise document analysis assistant. You synthesize information
from provided sources to answer user questions. ALWAYS answer with what you
have — even partial or tangential information is valuable. Lead with facts,
never with disclaimers."
```

### Contextes injectes dans le prompt

Le prompt `SYNTHESIS_PROMPT` accepte 4 contextes :

| Contexte | Source | Contenu |
|----------|--------|---------|
| `chunks_content` | Qdrant (retrieval) | Texte des chunks formates avec source/slide |
| `graph_context` | KG (signal-driven) | Bloc KG + chaines CHAINS_TO + QS cross-doc + instructions signal |
| `session_context` | Memory Layer | Messages precedents de la conversation |
| (dans graph_context) | Signal Policy | Instructions textuelles ajoutees par la policy |

### Calcul de confiance

Le score de confiance combine :
- Scores de reranking des chunks
- Scores Qdrant
- Signaux KG (concepts_count, relations_count, avg_confidence)
- Signaux de chaines (chain_count, distinct_docs_count, max_hops)

---

## 9. Constats empiriques

### Benchmark OSMOSIS vs RAG (mars 2026)

275 questions, 3 taches, dual-juge (Qwen 14B + Claude Sonnet, convergence 0.3%).

#### T1 — Provenance et Citations

| Metrique | OSMOSIS KG (30q) | RAG KG | OSMOSIS Humain (100q) | RAG Humain |
|----------|------------------|--------|-----------------------|------------|
| factual_correctness_avg | **42%** | 27% | 35% | **41%** |
| answer_relevant_rate | **59%** | 47% | 44% | **52%** |
| correct_source_rate | **45%** | 23% | 31% | **36%** |
| false_idk_rate | **14%** | 33% | 35% | 37% |

**Pattern** : OSMOSIS +15pp factual sur questions cross-doc KG, mais RAG +6pp sur questions humaines simples. Le KG detourne la reponse du sujet sur les questions simples.

#### T2 — Detection des Contradictions

| Metrique | OSMOSIS KG (25q) | RAG KG | OSMOSIS Humain (50q) | RAG Humain |
|----------|------------------|--------|-----------------------|------------|
| both_sides_surfaced_rate | **100%** | 0% | 100% | 100% |
| tension_mentioned_rate | **100%** | 0% | **25%** | 0% |
| both_sourced_rate | **75%** | 0% | 0% | 0% |

**Game changer** : 100% vs 0% sur l'exposition des deux positions (questions KG). C'est le differentiel le plus fort d'OSMOSIS. Se dilue sur les questions humaines (25% vs 0%).

#### T4 — Audit et Completude

| Metrique | OSMOSIS KG (20q) | RAG KG | OSMOSIS Humain (50q) | RAG Humain |
|----------|------------------|--------|-----------------------|------------|
| topic_coverage_rate | **89%** | 58% | **82%** | 78% |
| completeness_avg | **68%** | 49% | **67%** | 62% |
| comprehensiveness_rate | **44%** | 16% | **50%** | 41% |
| contradictions_flagged_rate | **17%** | 0% | **18%** | 12% |

OSMOSIS +19pp completude, +31pp couverture, +29pp exhaustivite sur questions KG.

#### Synthese

| Force OSMOSIS | Metrique |
|---------------|----------|
| Contradictions cross-doc | T2 KG : 100% vs 0% |
| Completude cross-doc | T4 KG : +19pp |
| Refus injustifie cross-doc | T1 KG : 14% vs 33% |

| Faiblesse OSMOSIS | Metrique |
|-------------------|----------|
| Exactitude factuelle simple | T1 Humain : 35% vs 41% (-6pp) |
| Pertinence questions simples | T1 Humain : 44% vs 52% (-8pp) |
| Taux refus global | ~35% (identique RAG) |

#### Autres constats

- **Bloc KG dans prompt** : -8pp factual avec 144 tokens de contexte KG (Sprint 0 test v2). D'ou le guard-rail max ~150 tokens.
- **IntentResolver prototypes** : 75% misclassification (voir section 5).
- **Haiku 3.5** : 80% correct sur 5 questions a $0.004/q — candidat synthese production.
- **Claude Sonnet** : 54% vs Qwen 15% sur chunks reconstruits (+39pp) — test borne superieure.
- **Juges calibres** : factual >= 0.8 = correct. Vrai false_answer = 17%, vrai correct = 40%.

---

## 10. Pistes ecartees

### 10.1 Bloc KG riche dans le prompt de synthese — ABANDONNE, REMPLACE PAR KG PROCEDURAL

> **Historique** : Le bloc KG riche (entites, relations SPO, faits detailles — 144+ tokens) a ete abandonne au Sprint 0 (-8pp factual). Le bloc minimal actuel (`_build_kg_context_block()`, max 150 tokens) est **toujours actif** mais cause un gap faithfulness de -7pp vs RAG pur (benchmark RAGAS 31 mars 2026). Le LLM lit le bloc KG AVANT les chunks → "early commitment bias" (opinion prematuree).

**Evolution cible (Phase 3 tache 3.4) : KG narratif → KG procedural**

Le KG ne doit plus injecter du **contenu semantique concurrent** des chunks. Il doit injecter un **cadre d'interpretation** des chunks. Concretement :

```
ACTUEL (narratif, pollue la synthese) :
  "Entities: SAP S/4HANA, TLS 1.3. Tensions: Doc A says TLS 1.2, Doc B says TLS 1.3..."

CIBLE (procedural, guide la synthese) :
  kg_findings = [
    {"type": "tension", "instruction": "Sources disagree on TLS version. Present BOTH positions."},
    {"type": "cross_doc_discovery", "instruction": "Doc X (absent du retrieval initial) contient
     des informations complementaires. Comparer explicitement avec les sources primaires.",
     "chunks_added": ["chunk_id_1", "chunk_id_2"]},
    {"type": "coverage_gap", "instruction": "Aucune source ne couvre la version 2025. Mentionner cette limite."}
  ]
```

**Placement dans le prompt** : les instructions KG viennent APRES les chunks (pas avant), pour eviter l'early commitment bias. Le LLM lit d'abord les preuves, puis ajuste sa reponse selon les directives KG.

```
## Sources (lire en premier comme evidence primaire)
[chunk 1]
[chunk 2]
...

## Instructions de lecture (diagnostic documentaire)
- Les sources ne sont pas unanimes sur la version TLS. Presenter les DEUX positions.
- Le document X (ajoute par analyse cross-doc) contient des informations complementaires. Comparer explicitement.
```

**Roles clarifies** :
- **RAG** = moteur principal de recuperation de preuves (chunks inchanges, invariant Type A)
- **KG** = couche de diagnostic documentaire (signale tensions, evolutions, angles morts)
- **LLM** = synthetiseur qui distingue explicitement preuves (chunks) et diagnostic (KG)

**Cross-doc discovery** : quand le KG detecte des documents pertinents absents du retrieval RAG (via CHAINS_TO, CONTRADICTS, etc.), Phase C light ajoute des chunks supplementaires de ces docs. Ces chunks sont marques comme "decouverte KG" dans les `kg_findings` pour que le LLM sache qu'ils viennent d'une analyse cross-doc (pas du retrieval direct) et les compare explicitement avec les sources primaires.

**Impact attendu** : faithfulness OSMOSIS rejoint ou depasse RAG (+7pp a recuperer) sans perdre les gains cross-doc (context_relevance, tension detection).

### 10.2 IntentResolver par prototypes embeddes

27 prototypes repartis en 4 types (A/B/C/D). L'embedding model capture la semantique du sujet, pas la structure interrogative. 75% de misclassification sur les questions factuelles. Abandonne au profit de l'approche signal-driven.

### 10.3 Query rewriting LLM

Adapter la requete avant le search (a la Rewrite-Retrieve-Read). Ecarte car ajoute de la latence (appel LLM dans le chemin critique) pour un gain marginal par rapport au fix de prompt.

### 10.4 Community summaries (GraphRAG)

Pre-generer des resumes de clusters/communautes a la Microsoft GraphRAG. Ecarte car :
- Couteux en tokens
- Fragile (stale quand le corpus change)
- Perte de tracabilite (limitation reconnue par GraphRAG)
- OSMOSIS a un avantage : tracabilite claim-level vs summarization-level

Alternative retenue : utiliser les ClaimClusters (2381 noeuds, deja existants) au runtime pour identifier consensus et divergences, sans pre-generation.

### 10.5 Passage node (HippoRAG 2)

Creer un noeud `Passage` dans Neo4j, jumeau du chunk Qdrant. Ecarte car :
- Le bridge `Claim.chunk_ids → Qdrant` existe deja (100% mapping)
- Le champ `passage_text` existe deja sur les Claims
- HippoRAG 2 a besoin du Passage node car ils n'ont pas de base vectorielle separee — OSMOSIS a Qdrant
- Creer un Passage node dupliquerait les donnees sans valeur ajoutee

### 10.6 Extension massive des QuestionDimensions

Elargir le gating QD pour couvrir plus de 4.8% des claims. Ecarte car augmente le bruit. Les QD restent un accelerateur specialise pour les faits comparables (valeurs numeriques, versions, seuils).

### 10.7 Classificateur LLM pour l'intent

Appel rapide a Qwen 14B pour classifier la question en A/B/C/D (~100ms). Ecarte car : ajoute 100ms + dependance vLLM dans le chemin critique, et c'est une solution transitoire (le "pas de MVP transitoire" s'applique).

---

## 11. Travaux non termines

### 11.1 KG Signal Detector — implementation complete

Le signal detector est **implemente et actif** (`kg_signal_detector.py`, `signal_policy.py`). Les 4 signaux (tension, temporal_evolution, coverage_gap, exactness) sont detectes. La policy transforme les signaux en actions concretes.

**Travail restant** :
- Calibration des seuils de force (actuellement empiriques)
- Metriques de monitoring (combien de questions declenchent chaque signal)
- Tests de non-regression par signal

### 11.2 Layer P et Layer C (ADR Qdrant V2)

Collections `knowbase_infos_v2` et `concepts_v2` non creees. Les Informations et Concepts V2 ne sont pas vectorises dans Qdrant. Cela bloque :
- La recherche precise concept-aware (Layer P)
- Le concept matching sur l'ontologie V2 (Layer C)
- Le mode REASONED complet (path finding + Layer P)

### 11.3 Cross-encoder NLI reranker

Prevu comme amelioration du reranking pour detecter les relations d'entailment/contradiction entre question et chunks. Non implemente. Le reranking actuel utilise `rerank_chunks` (cross-encoder basique).

### 11.4 Always-on context layer

Inspire de l'article Zep/context graph : un contexte semantique persistant qui enrichit toute requete. Valide l'approche signal-driven + always-on context pour les sprints futurs. Non implemente.

### 11.5 Graph-First Runtime complet

L'ADR `ADR-20260106-graph-first-architecture.md` decrit un runtime ou le KG est interroge AVANT Qdrant (pathfinding GDS Yen k-shortest paths). Non implemente. Le runtime actuel est "retrieval-first enriched by KG" (le KG enrichit apres le retrieval Qdrant).

Les 3 invariants du Graph-First ne sont pas encore enforces :
- I1 : Le graphe est toujours interroge avant Qdrant (partiellement : claims vector search en parallele)
- I2 : Mode Reasoned = relations avec preuves (pas de mode Reasoned actif)
- I3 : SectionContext comme granularite de verite (partiellement implemente)

### 11.6 GDS Pathfinding

GDS Community (Yen k-shortest paths) pour le pathfinding dans le graphe semantique. Non installe. Le pathfinding actuel utilise Cypher natif (CHAINS_TO*1..3).

### 11.7 Pont SectionContext → Qdrant

Le champ `context_id` n'est pas injecte dans le payload Qdrant. Le filtrage direct par `context_id` (evidence plan) n'est donc pas possible. L'ADR definit le format canonique `sec:{document_id}:{section_hash}` et un helper `make_context_id()`, mais ce n'est pas implemente.

### 11.8 Hybrid retrieval BM25+dense via Qdrant RRF — DEPLOYE

**Statut : V2 DEPLOYE ET MESURE (31 mars 2026)**

**Constat RAGAS (30 mars 2026)** : 27% des questions (27/100) ont un context_relevance < 0.3. Ces questions portent sur des termes specifiques (SAP Notes, transactions, codes, tables) que le dense-only rate. C'est le **levier #1** pour ameliorer les scores.

**Probleme V1 actuelle** : L'implementation dans `retriever.py:_hybrid_search()` fait un 2e prefetch avec le **meme vecteur dense** + un filtre text en plus. Ce n'est PAS une vraie fusion RRF — c'est un sous-ensemble du dense filtre par text match. Le BM25 ne fournit pas de resultats independants.

**Refactoring necessaire** :
1. Scroll BM25 SEPARE (sans vecteur) : `qdrant.scroll(filter=MatchText("SAP Note 2008727"), limit=30)`
2. Dense search SEPARE : `qdrant.query_points(query=vector, limit=30)`
3. Fusion manuelle RRF : `score = 1/(k + rank_dense) + 1/(k + rank_bm25)`, k=60
4. Tri par score fusionne, top_k=10
5. Mesurer RAGAS avant/apres

**Impact mesure (31 mars 2026)** :
- Context Relevance : 0.580 → **0.730** (+15pp)
- Faithfulness : 0.743 → **0.793** (+5pp)
- Le BM25 apporte en moyenne 9 chunks uniques non trouves par le dense

**Implementation** : `retriever.py:_hybrid_search()` fait un scroll BM25 separe + dense query_points + fusion RRF manuelle (k=60). Keywords extraits via `_extract_bm25_keywords()` (stopwords FR/EN, max 4 termes techniques). Score threshold desactive en mode hybrid (scores RRF non comparables au cosine).

### 11.9 Ablation systematique signal ON/OFF

**Statut : A IMPLEMENTER (Phase 3)**

Le signal detector est actif mais son impact reel sur les reponses n'est pas mesure isolement. Une ablation rigoureuse est necessaire :

```
Run A : signal_policy = passthrough (RAG pur, zero KG injection)
Run B : signal_policy = active (production actuelle)
Comparer : factuality T1, false_idk, contradiction_f1 T2, latence p95
GO : B ameliore T2 sans degrader T1 au-dela d'un seuil
```

### 11.10 Pistes a terme (horizon 3-6 mois)

Les pistes suivantes sont **pertinentes mais non prioritaires** — elles deviennent actionnables quand le corpus depasse ~100 docs ou quand les Phases 1-3 sont validees :

| Piste | Quand | Pourquoi pas maintenant | Reference |
|-------|-------|------------------------|-----------|
| **Cross-encoder NLI reranker** | Apres hybrid RRF | Le reranker actuel (ms-marco-MiniLM) suffit a 28 docs. Un NLI reranker (entailment/contradiction) deviendrait pertinent pour detecter les tensions au retrieval, pas seulement au KG | BEIR, ColBERTv2 |
| **Leiden community clustering** | Apres canonicalisation (Phase 2) | Le KG est trop sparse pour des communautes significatives. Apres C1+C3, des clusters emergeront naturellement. Leiden + resumes par communaute = mode "global query" a la GraphRAG | Microsoft GraphRAG (2024) |
| **ALCE evaluation citations** | Apres UI tensions (Phase 4) | OSMOSIS promet la tracabilite — ALCE (EMNLP 2023) fournit un cadre reproductible pour evaluer la qualite des citations (correctness + citation quality). Pertinent quand l'UI est visible | ALCE benchmark |
| **BGE-M3 multi-functional embeddings** | Quand corpus > 100 docs | Remplacerait e5-large par un modele unifie dense+sparse+multi-vector. Migration couteuse (re-vectorisation totale). ROI faible a 28 docs, fort a 500+ | BGE-M3 paper |

---

## 12. References archive

Documents sources archives dans `doc/archive/pre-rationalization-2026-03/` :

| Document | Contenu | Statut |
|----------|---------|--------|
| `adr/ADR-20260106-graph-first-architecture.md` | Architecture Graph-First, 3 modes, pathfinding GDS, pont SectionContext→Qdrant | Partiellement implemente |
| `ongoing/ADR_QDRANT_RETRIEVAL_PROJECTION_V2.md` | Architecture dual-layer (R+P+C), re-chunking, timing embeddings | Layer R implemente, P et C non |
| `adr/ADR-20260101-navigation-layer.md` | Navigation Layer, ContextNodes, Non-Promotion Clause | **Entierement implemente** |
| `specs/graph/SPEC-PHASE2.7_CONCEPT_MATCHING_ENGINE.md` | Concept Matching 3 paliers, golden set 78% | Implemente mais desactive en mode ClaimFirst |
| `ongoing/PHASE_B_CONSOLIDATED_ANALYSIS.md` | Analyse consolidee benchmark, invariant Type A, pistes | Analyse de reference |
| `ongoing/PHASE_B_INTENT_DRIVEN_SEARCH_PROPOSAL.md` | Proposition KG-Augmented Synthesis, 4 types de questions | Architecture signal-driven adoptee a la place |
| `ongoing/SPRINT2_DIAGNOSTIC_INTENT_RESOLVER.md` | Diagnostic 75% misclassification, options evaluees | IntentResolver abandonne |

### Ontologie Neo4j active (mars 2026)

| Noeud | Count | Role |
|-------|-------|------|
| Claim | 15 861 | Fait atomique extrait |
| Entity | 7 059 | Entite nommee |
| CanonicalEntity | 267 | Pivot de deduplication |
| ClaimCluster | 2 381 | Groupement semantique |
| QuestionDimension | 382 | Question factuelle canonique |
| QuestionSignature | 755 | Reponse extraite a une QD |
| Facet | 9 | Domaine thematique |
| WikiArticle | 69 | Article de synthese |
| DocumentContext | 22 | Contexte d'applicabilite |

| Relation | Count | Direction |
|----------|-------|-----------|
| ABOUT | 25 634 | Claim → Entity |
| IN_CLUSTER | 7 728 | Claim → ClaimCluster |
| SIMILAR_TO | 4 208 | Claim ↔ Claim |
| BELONGS_TO_FACET | 2 659 | Claim → Facet |
| CHAINS_TO | 1 547 | Claim → Claim (cross-doc) |
| ANSWERS | 770 | QS → QD |
| REFINES | 280 | Claim → Claim |
| QUALIFIES | 249 | Claim → Claim |
| CONTRADICTS | 2 | Claim ↔ Claim |

**252 tensions cross-doc** (63 REFINES + 189 QUALIFIES entre documents differents) — source de la valeur T2.

---

*Derniere mise a jour : 29 mars 2026*
*Sources : code (`src/knowbase/api/services/`), archives (`doc/archive/pre-rationalization-2026-03/`)*
