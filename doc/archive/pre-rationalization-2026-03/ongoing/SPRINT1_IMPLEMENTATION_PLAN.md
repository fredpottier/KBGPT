# Sprint 1 — Plan d'Implementation Detaille

**Date** : 24 mars 2026
**Base** : Analyse code search.py (2293 lignes) + synthesis.py + patterns Neo4j
**Architecture** : IntentResolver 2-passes + KG2RAG
**Consensus** : Claude Code (analyse code) + Claude Web (latence/reclassification) + ChatGPT (produit)

---

## 1. Graphe de Dependances des Livrables

```
1.1 Canary tests ──────────────────────────────────────────┐
     (FAIT)                                                 │
                                                            v
1.6 Benchmark enrichi ──> 1.2 Fix prompt ──> 1.3 Refactoring search.py
     (FAIT)                    (P0)                (P0)
                                                     │
                                                     ├──> 1.4 IntentResolver 2-passes
                                                     │         (P1)
                                                     │              │
                                                     └──> 1.5 KG2RAG chunk reorganization
                                                               (P1, apres 1.4)
```

**Ordre d'execution** : 1.2 → 1.3 → 1.4 → 1.5 (sequentiel, chaque etape validee par canary)
**Parallelisable** : rien — chaque livrable depend du precedent.

---

## 2. Livrable 1.2 — Fix Prompt Asymetrique (1 jour)

### Fichier : `src/knowbase/api/services/synthesis.py`

#### Probleme
Le SYSTEM_PROMPT actuel (ligne 155) dit :
```
"Tu es un assistant expert SAP qui synthetise des informations..."
```
Et le SYNTHESIS_PROMPT contient des regles de citation strictes mais aucune instruction explicite sur quand repondre vs refuser.

Le benchmark runner utilise un prompt different (en anglais) :
```
"ONLY say 'information not available' if NONE of the sources contain ANY relevant information"
```

#### Modification
Remplacer le SYSTEM_PROMPT par une version domain-agnostic avec calibrage asymetrique :

```python
SYSTEM_PROMPT = """You are a precise document analysis assistant.
You synthesize information from the provided sources to answer questions.

RESPONSE RULES:
1. Every factual statement MUST cite its source with (Source: document_name, page/slide)
2. If sources contain PARTIAL information, answer with what you have — do NOT refuse
3. If sources contain contradictions, present BOTH sides with their sources
4. ONLY say "information not available" if NONE of the sources contain ANY relevant information
5. When uncertain, say "Based on available sources..." rather than refusing
6. Answer in the SAME LANGUAGE as the question"""
```

**Changements cles** :
- Domain-agnostic (plus de "expert SAP")
- Regle 2 force la reponse partielle (reduit false_idk)
- Regle 5 ajoute un mode "incertain" au lieu du refus binaire
- Pas de changement sur la temperature (0.3) ni les tokens max (2000)

#### Validation
1. Canary test avant/apres
2. Benchmark T1 human (100 questions) : false_idk < 25%, false_answer < 15%
3. Benchmark questions negatives (10) : hallucination_rate ne doit pas augmenter

---

## 3. Livrable 1.3 — Refactoring search.py (3-4 jours)

### Principe : Strangler Fig Pattern

On ne reecrit PAS search.py d'un coup. On extrait les modules un par un en gardant `search_documents()` comme orchestrateur qui delegue progressivement.

### Phase A : Extraire le retriever (jour 1)

**Nouveau fichier** : `src/knowbase/api/services/retriever.py`

```python
@dataclass
class RetrievalResult:
    chunks: list[dict]          # Qdrant chunks bruts
    query_vector: list[float]   # Vecteur de la question
    scores: list[float]         # Scores Qdrant
    docs_involved: set[str]     # Doc IDs distincts

def retrieve_chunks(
    question: str,
    qdrant_client: QdrantClient,
    embedding_model: SentenceTransformer,
    top_k: int = 10,
    score_threshold: float = 0.5,
    solution_filter: str | None = None,
    release_filter: str | None = None,
    doc_filter: list[str] | None = None,
) -> RetrievalResult:
    """Qdrant vector search pur — invariant Type A."""
```

**Extraction depuis search.py** :
- Lignes 533 (encoding) → `_embed_query()` deja existant, integrer
- Lignes 738-771 (Qdrant search) → coeur du retriever
- Lignes 772-779 (filtrage score) → integrer
- Lignes 780-800 (build_response_payload) → integrer

**Test** : le canary doit passer identiquement avant/apres extraction.

### Phase B : Extraire l'enrichisseur KG (jour 2)

**Nouveau fichier** : `src/knowbase/api/services/kg_enricher.py`

```python
@dataclass
class KGEnrichment:
    entity_names: dict[str, list[str]]        # chunk_id → entites
    contradiction_texts: dict[str, list[str]]  # chunk_id → tensions
    kg_claims: list[dict]                      # Claims matchees
    tensions_doc_ids: set[str]                 # Docs en tension
    chains_text: str                           # CHAINS_TO markdown
    chains_doc_ids: list[str]                  # Docs decouverts par traversee
    chain_signals: dict                        # Metadata traversee
    qs_crossdoc_text: str                      # QuestionSignatures markdown
    qs_crossdoc_data: list[dict]               # Donnees comparaison

def enrich_with_kg(
    question: str,
    chunks: list[dict],
    tenant_id: str = "default",
    use_traversal: bool = True,
) -> KGEnrichment:
    """Enrichissement KG complet — entites, tensions, chains, QS."""
```

**Extraction depuis search.py** :
- `_search_claims_vector()` (lignes 69-140) → interne a kg_enricher
- `_enrich_chunks_with_kg()` (lignes 359-453) → interne
- `_get_kg_traversal_context()` (lignes 1736-1979) → interne
- `_get_qs_crossdoc_context()` (lignes 1982-2290) → interne
- Logique tensions doc_ids (lignes 781-839) → interne

### Phase C : Extraire l'organisateur de chunks (jour 3)

**Nouveau fichier** : `src/knowbase/api/services/chunk_organizer.py`

```python
@dataclass
class OrganizedChunks:
    chunks: list[dict]              # Chunks reorganises
    organization_type: str          # "raw" | "contradiction_adjacency" | "cluster_coverage"
    metadata: dict                  # Infos sur la reorganisation

def organize_chunks(
    chunks: list[dict],
    enrichment: KGEnrichment,
    intent_type: str,               # "A" | "B" | "C" | "D"
    top_k_override: int | None = None,
) -> OrganizedChunks:
    """KG2RAG — reorganise les chunks selon le type d'intent."""
```

**Logique par type** :
- Type A : return chunks tel quel (zero modification)
- Type B : placer les chunks contradictoires en adjacence
- Type C : elargir a top_k=20, diversifier par document
- Type D : mettre le chunk QD en premier

### Phase D : Nouvel orchestrateur (jour 3-4)

**Fichier modifie** : `src/knowbase/api/services/search.py`

`search_documents()` devient un orchestrateur mince :

```python
def search_documents(...) -> dict:
    # 1. Retrieval (invariant)
    retrieval = retrieve_chunks(question, qdrant_client, embedding_model, ...)

    # 2. Passe 1 : classification linguistique
    intent_type = classify_intent_linguistic(question, retrieval.query_vector)

    # 3. Enrichissement KG (si pas Type A pur)
    enrichment = None
    if use_graph_context:
        enrichment = enrich_with_kg(question, retrieval.chunks, tenant_id)

    # 4. Passe 2 : reclassification post-retrieval
    if enrichment:
        intent_type = reclassify_post_retrieval(intent_type, enrichment)

    # 5. Organisation des chunks (KG2RAG)
    organized = organize_chunks(retrieval.chunks, enrichment, intent_type)

    # 6. Synthese
    synthesis = synthesize_response(question, organized.chunks, ...)

    # 7. Post-processing (articles, hints, proof)
    ...
```

---

## 4. Livrable 1.4 — IntentResolver 2-Passes (3-4 jours)

### Nouveau fichier : `src/knowbase/api/services/intent_resolver.py`

### Passe 1 : Prototypes embeddes (< 5ms)

```python
# 20 prototypes domain-agnostic, embeddes une seule fois au demarrage
PROTOTYPES = {
    "A": [
        "What is X?",
        "How does X work?",
        "Explain X",
        "Comment fonctionne X ?",
        "Qu'est-ce que X ?",
    ],
    "B": [
        "What is the difference between X and Y?",
        "Compare X and Y",
        "How has X changed between version 1 and version 2?",
        "Quelle est la difference entre X et Y ?",
        "X versus Y",
    ],
    "C": [
        "Give me a complete summary of X across all documents",
        "What do all documents say about X?",
        "Audit X",
        "Fais un resume complet de X",
        "Que disent tous les documents sur X ?",
    ],
    "D": [
        "What is the exact value of X?",
        "What is the minimum/maximum threshold for X?",
        "Quel est le seuil exact de X ?",
        "Quelle est la valeur de X ?",
    ],
}

class IntentResolver:
    def __init__(self, embedding_model):
        # Embed prototypes une seule fois (startup)
        self._prototype_embeddings = {}
        for intent_type, texts in PROTOTYPES.items():
            embeddings = embedding_model.encode(texts, normalize_embeddings=True)
            self._prototype_embeddings[intent_type] = embeddings  # (N, 1024)

    def classify_linguistic(self, query_vector: list[float]) -> tuple[str, float]:
        """Passe 1 : cosine similarity avec prototypes. < 5ms."""
        best_type = "A"
        best_score = 0.0
        for intent_type, proto_embs in self._prototype_embeddings.items():
            # Max cosine sim avec n'importe quel prototype du type
            sims = proto_embs @ query_vector  # (N,) dot product (normalized)
            max_sim = float(sims.max())
            if max_sim > best_score:
                best_score = max_sim
                best_type = intent_type

        # Seuil de confiance : si le meilleur score < 0.35, defaut Type A
        if best_score < 0.35:
            return "A", best_score
        return best_type, best_score
```

**Pourquoi domain-agnostic** :
- Les prototypes sont des structures linguistiques ("What is", "Compare", "Summary of")
- Le contenu (X, Y) est variable — l'embedding capture la structure
- Fonctionne identiquement sur SAP, biomedical, reglementaire
- Zero training, zero annotation, zero KG necessaire

### Passe 2 : Reclassification post-retrieval

```python
def reclassify_post_retrieval(
    initial_type: str,
    enrichment: KGEnrichment,
    retrieval: RetrievalResult,
) -> str:
    """Passe 2 : upgrade le type si le KG revele de la complexite."""

    # Regle 1 : tensions detectees → upgrade Type B
    if enrichment.tensions_doc_ids and len(enrichment.tensions_doc_ids) >= 2:
        if initial_type == "A":
            return "B"

    # Regle 2 : 4+ documents distincts dans les chunks → upgrade Type C
    if len(retrieval.docs_involved) >= 4 and initial_type in ("A", "B"):
        return "C"

    # Regle 3 : QD match exact avec extracted_value → upgrade Type D
    if enrichment.qs_crossdoc_data:
        for qs in enrichment.qs_crossdoc_data:
            if qs.get("match_type") == "exact" and qs.get("extracted_value"):
                return "D"

    # Regle 4 : 2+ versions du meme sujet (ApplicabilityFrame) → upgrade Type B
    if _detect_multi_version(enrichment.kg_claims):
        if initial_type == "A":
            return "B"

    # Pas d'upgrade
    return initial_type

def _detect_multi_version(claims: list[dict]) -> bool:
    """Detecte si les claims impliquent 2+ versions du meme sujet."""
    version_docs = set()
    for c in claims:
        # Chercher des patterns de version dans le doc_id
        doc_id = c.get("doc_id", "")
        # Ex: "022_Business-Scope-2022" vs "023_Business-Scope-2023"
        version_docs.add(doc_id)
    # Simple heuristique : si meme prefixe avec annees differentes
    # Plus sophistique : utiliser ApplicabilityFrame.release_id
    return len(version_docs) >= 3  # 3+ docs = probablement multi-version
```

**Latence Passe 2** : ~0ms (regles deterministes sur des donnees deja en memoire, pas d'appel Neo4j supplementaire)

**Quand le KG est vide** :
- `enrichment.tensions_doc_ids` = vide → pas d'upgrade
- `enrichment.qs_crossdoc_data` = vide → pas d'upgrade
- `enrichment.kg_claims` = vide → pas d'upgrade
- Resultat : tout reste Type A → degradation gracieuse

---

## 5. Livrable 1.5 — KG2RAG Chunk Reorganization (3 jours)

### Fichier : `src/knowbase/api/services/chunk_organizer.py`

### Type A : Zero modification
```python
def _organize_type_a(chunks: list[dict]) -> OrganizedChunks:
    """Type A = RAG pur. HARD CONSTRAINT : zero modification."""
    return OrganizedChunks(chunks=chunks, organization_type="raw", metadata={})
```

### Type B : Adjacence contradictoire
```python
def _organize_type_b(chunks: list[dict], enrichment: KGEnrichment) -> OrganizedChunks:
    """Place les chunks contradictoires en paires adjacentes."""
    # 1. Identifier les paires de chunks en tension
    tension_pairs = []
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id", "")
        tensions = enrichment.contradiction_texts.get(chunk_id, [])
        if tensions:
            # Trouver le chunk cible de la tension
            for other_chunk in chunks:
                if other_chunk.get("doc_id") in enrichment.tensions_doc_ids:
                    tension_pairs.append((chunk, other_chunk))

    # 2. Reorganiser : paires en tension d'abord, puis le reste
    organized = []
    used = set()
    for c1, c2 in tension_pairs:
        if id(c1) not in used:
            organized.append(c1)
            used.add(id(c1))
        if id(c2) not in used:
            organized.append(c2)
            used.add(id(c2))

    # Ajouter les chunks non utilises
    for chunk in chunks:
        if id(chunk) not in used:
            organized.append(chunk)

    return OrganizedChunks(
        chunks=organized,
        organization_type="contradiction_adjacency",
        metadata={"tension_pairs": len(tension_pairs)}
    )
```

### Type C : Couverture cross-doc
```python
def _organize_type_c(
    chunks: list[dict],
    enrichment: KGEnrichment,
    qdrant_client: QdrantClient,
    query_vector: list[float],
) -> OrganizedChunks:
    """Elargir a top_k=20, diversifier par document, couvrir les clusters."""
    # 1. Recuperer 10 chunks supplementaires si necessaire
    if len(chunks) < 20 and enrichment.chains_doc_ids:
        extra = retrieve_chunks(
            ..., top_k=10, doc_filter=enrichment.chains_doc_ids
        )
        chunks = _merge_deduplicate(chunks, extra.chunks)

    # 2. Diversifier par document (max 3 chunks par doc)
    doc_buckets = defaultdict(list)
    for chunk in chunks:
        doc_buckets[chunk.get("doc_id", "")].append(chunk)

    organized = []
    round_robin = True
    while round_robin:
        round_robin = False
        for doc_id, doc_chunks in doc_buckets.items():
            if doc_chunks and len([c for c in organized if c.get("doc_id") == doc_id]) < 3:
                organized.append(doc_chunks.pop(0))
                round_robin = True

    return OrganizedChunks(
        chunks=organized[:20],
        organization_type="cluster_coverage",
        metadata={"docs_covered": len(doc_buckets), "total_chunks": len(organized)}
    )
```

### Type D : QD-first
```python
def _organize_type_d(chunks: list[dict], enrichment: KGEnrichment) -> OrganizedChunks:
    """Placer le chunk QD en premiere position."""
    qd_chunks = [c for c in chunks if c.get("source_type") == "qd_match"]
    other_chunks = [c for c in chunks if c.get("source_type") != "qd_match"]
    return OrganizedChunks(
        chunks=qd_chunks + other_chunks,
        organization_type="qd_first",
        metadata={"qd_chunks": len(qd_chunks)}
    )
```

---

## 6. Prompt Adapte par Type

### Fichier : `src/knowbase/api/services/synthesis.py`

Le SYNTHESIS_PROMPT varie selon le type :

```python
SYNTHESIS_PROMPT_SUFFIX = {
    "A": "",  # Aucune instruction supplementaire
    "B": """
IMPORTANT: The sources contain CONTRADICTIONS or DIVERGENCES on this topic.
You MUST:
- Present BOTH sides of any disagreement
- Explicitly mention the divergence using words like "however", "in contrast", "divergence"
- Cite the specific source for each position
- Do NOT silently pick one side""",
    "C": """
IMPORTANT: This is a COMPREHENSIVE analysis request.
You MUST:
- Cover the topic from ALL available sources
- Mention how many documents discuss this topic
- Group information by theme or document
- Note any gaps in coverage""",
    "D": """
IMPORTANT: The user is asking for a SPECIFIC VALUE or THRESHOLD.
You MUST:
- Lead with the exact value(s) found
- If multiple values exist across documents, list ALL with their sources
- Note any conditions or scopes that affect the value""",
}
```

---

## 7. Criteres de Validation par Livrable

| Livrable | Test | Seuil pass | Outil |
|----------|------|-----------|-------|
| 1.2 Prompt | false_idk T1 human | < 25% | benchmark full |
| 1.2 Prompt | false_answer T1 human | < 15% | benchmark full |
| 1.2 Prompt | hallucination neg | <= 30% (= baseline) | benchmark neg |
| 1.3 Refactoring | Canary 15/15 | 100% pass | canary_test.py |
| 1.3 Refactoring | Benchmark T1 human | delta < 2pp vs baseline | compare_runs.py |
| 1.4 IntentResolver | Classification accuracy | > 90% sur 275 questions | script dedie |
| 1.4 IntentResolver | Passe 1 latence | < 5ms | chrono inline |
| 1.4 IntentResolver | Passe 2 latence | < 1ms | chrono inline |
| 1.5 KG2RAG | Type A == RAG | delta 0pp | compare_runs.py |
| 1.5 KG2RAG | T2 both_sides | >= 100% (KG) | benchmark T2 |
| 1.5 KG2RAG | T4 completude | >= 68% (KG) | benchmark T4 |
| 1.5 KG2RAG | irrelevant_rate | <= RAG (17%) | benchmark full |

---

## 8. Fichiers a Creer / Modifier

| Fichier | Action | Livrable |
|---------|--------|----------|
| `src/knowbase/api/services/retriever.py` | **Creer** | 1.3 |
| `src/knowbase/api/services/kg_enricher.py` | **Creer** | 1.3 |
| `src/knowbase/api/services/chunk_organizer.py` | **Creer** | 1.5 |
| `src/knowbase/api/services/intent_resolver.py` | **Creer** | 1.4 |
| `src/knowbase/api/services/search.py` | **Modifier** (orchestrateur mince) | 1.3 |
| `src/knowbase/api/services/synthesis.py` | **Modifier** (prompt + suffix par type) | 1.2, 1.5 |
| `benchmark/evaluators/llm_judge.py` | **Modifie** (FAIT) | 1.6 |
| `benchmark/canary_test.py` | **Cree** (FAIT) | 1.1 |
| `benchmark/compare_runs.py` | **Cree** (FAIT) | 1.1 |

---

## 9. Risques et Mitigations

| Risque | Probabilite | Impact | Mitigation |
|--------|------------|--------|-----------|
| Fix prompt augmente false_answer au-dela de 15% | Moyenne | Fort | Trade-off asymetrique : garder false_idk a 20-25% plutot que risquer |
| Refactoring casse des fonctionnalites | Faible | Fort | Strangler Fig + canary test a chaque etape |
| Prototypes Passe 1 mal calibres | Moyenne | Moyen | Tester sur 275 questions + ajuster seuils |
| Passe 2 upgrade trop agressif | Moyenne | Moyen | Seuils conservateurs (4+ docs, 2+ tensions) + fallback Type A |
| KG2RAG Type C degrade irrelevant | Moyenne | Fort | Diversification round-robin (max 3 chunks/doc) + test systematique |
| Latence totale augmentee | Faible | Moyen | Passe 1 < 5ms, Passe 2 < 1ms, KG enrichment deja dans le flux |
