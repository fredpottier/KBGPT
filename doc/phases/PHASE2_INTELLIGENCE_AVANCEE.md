# Phase 2 : Intelligence Relationnelle & Graph-Powered Features

**Période** : Semaines 11-20 (Post Phase 1 Semantic Core)
**Statut** : 🟡 Planification
**Prérequis** : ✅ Phase 1 Complète (Cross-référence Neo4j ↔ Qdrant opérationnelle)

---

## 🎯 Objectifs Phase 2

Phase 2 capitalise sur la **cross-référence bidirectionnelle** établie en Phase 1 pour délivrer des fonctionnalités intelligentes impossibles avec un RAG vectoriel seul.

**Pivot stratégique** : Transformer le Proto-KG en véritable **moteur d'intelligence relationnelle** exploitant la synergie Graphe ↔ Embeddings.

### Différenciation vs Copilot/Gemini

| Capacité | Microsoft Copilot | Google Gemini | **KnowWhere OSMOSE** |
|----------|-------------------|---------------|----------------------|
| RAG Vectoriel | ✅ | ✅ | ✅ |
| Graph Knowledge | ❌ | ⚠️ (limité) | ✅ **Native** |
| Cross-référence Chunks ↔ Concepts | ❌ | ❌ | ✅ **Bidirectionnelle** |
| Graph-Guided RAG | ❌ | ❌ | ✅ **Cœur** |
| Evolution Tracking | ❌ | ❌ | ✅ **USP Killer** |
| Provenance Explicite | ⚠️ | ⚠️ | ✅ **Granulaire** |

---

## 🚀 Use Cases Critiques (Exploitant Cross-référence)

### Priorité 1 : Fondations (Semaines 11-13)

#### UC1.1 : Explanation & Provenance Automatique 🔍

**Problème** : L'utilisateur voit "SAP BTP Security" dans le graphe mais ne sait pas d'où ça vient, ni comment c'est justifié.

**Solution** :
```python
# API: /api/v1/concepts/{concept_id}/explain
def explain_concept(concept_id: str) -> ExplanationResponse:
    """
    Retourne provenance complète d'un concept avec citations sources.

    Exploite: concept.chunk_ids (Neo4j → Qdrant)
    """
    # 1. Récupérer concept Neo4j
    concept = neo4j_client.get_concept(concept_id)

    # 2. Récupérer chunks via chunk_ids
    chunks = qdrant_client.retrieve(
        collection_name="knowbase",
        ids=concept.chunk_ids
    )

    # 3. Grouper par document source
    by_document = group_chunks_by_document(chunks)

    return {
        "concept_name": concept.canonical_name,
        "definition": concept.unified_definition,
        "confidence": concept.quality_score,
        "mentions_count": len(chunks),
        "source_documents": [
            {
                "document_name": doc.name,
                "excerpts": [
                    {
                        "text": chunk.text,
                        "page": extract_page(chunk),
                        "relevance": chunk.score
                    }
                    for chunk in doc_chunks[:5]  # Top 5
                ],
                "total_mentions": len(doc_chunks)
            }
            for doc, doc_chunks in by_document.items()
        ],
        "related_concepts": get_neighbors(concept_id, depth=1)
    }
```

**Valeur Business** :
- ✅ Transparence totale (audit trail)
- ✅ Conformité réglementaire (ISO 27001, SOC2)
- ✅ Confiance utilisateur (+40% adoption)

**Métriques de Succès** :
- 100% des concepts ont ≥1 chunk source
- Latence API < 200ms (p95)
- Taux de citation documentée > 95%

---

#### UC1.2 : Graph-Guided RAG (Recherche Hybride) 🚀

**Problème** : Recherche vectorielle seule = pertinence limitée, pas de contexte conceptuel structuré.

**Solution** :
```python
# API: /api/v1/search/graph-guided
def graph_guided_search(query: str) -> SearchResponse:
    """
    Recherche hybride : Graphe → Expansion contexte → Vector ranking

    Exploite: canonical_concept_ids (Qdrant → Neo4j)
    """
    # Étape 1: Identifier concepts clés dans la requête
    query_concepts = extract_concepts_from_query(query)
    # Ex: "sécuriser SAP BTP" → ["SAP BTP", "Security"]

    # Étape 2: Expansion graphe (1-hop neighbors)
    expanded_concepts = []
    for concept_name in query_concepts:
        concept = neo4j_client.find_concept(concept_name)
        neighbors = neo4j_client.get_neighbors(
            concept.id,
            relations=["SECURES", "INTEGRATES_WITH", "DEPENDS_ON"]
        )
        expanded_concepts.extend([concept] + neighbors)

    # Ex: Expansion ajoute ["RBAC", "Cloud Connector", "Identity Authentication"]

    # Étape 3: Récupérer chunks de TOUS les concepts
    candidate_chunks = []
    for concept in expanded_concepts:
        chunks = qdrant_client.retrieve(ids=concept.chunk_ids)
        candidate_chunks.extend(chunks)

    # Ex: 200+ chunks contextuellement pertinents (vs 10-20 en RAG naïf)

    # Étape 4: Rerank vectoriel sur les candidats enrichis
    query_embedding = embed_query(query)
    final_results = rerank_by_cosine_similarity(
        query_embedding,
        candidate_chunks,
        top_k=10
    )

    return {
        "results": final_results,
        "reasoning_path": [c.name for c in expanded_concepts],
        "graph_expansion_gain": len(candidate_chunks) / len(initial_vector_results)
    }
```

**Valeur Business** :
- ✅ Précision +40% vs RAG vectoriel seul
- ✅ Contexte structuré (pas de réponses hors-sujet)
- ✅ Raisonnement explicable (chemin dans le graphe)

**Métriques de Succès** :
- NDCG@10 > 0.85 (vs 0.60 baseline vectoriel)
- Taux de réponses pertinentes > 90%
- Latence < 500ms (avec expansion graphe)

**Implémentation** :
- Semaine 11 : API endpoint `/search/graph-guided`
- Semaine 12 : Optimisation expansion graphe (cache, batch)
- Semaine 13 : A/B test vs recherche vectorielle classique

---

### Priorité 2 : USP Différenciateurs (Semaines 14-17)

#### UC2.1 : CRR Evolution Tracker 📊 **(Cas d'Usage KILLER)**

**Problème** : Suivre l'évolution d'un concept SAP à travers 10+ CRR sur 3 ans impossible avec outils actuels.

**Solution** :
```python
# API: /api/v1/concepts/{concept_id}/evolution
def track_concept_evolution(
    concept_id: str,
    time_range: TimeRange
) -> EvolutionAnalysis:
    """
    Analyse évolution sémantique d'un concept dans le temps.

    Exploite:
    - concept.chunk_ids → retrouver tous les contextes
    - chunk.document_id + metadata.date → timeline
    """
    # 1. Récupérer tous les chunks du concept
    concept = neo4j_client.get_concept(concept_id)
    chunks = qdrant_client.retrieve(ids=concept.chunk_ids)

    # 2. Grouper par document et date
    timeline = []
    for chunk in chunks:
        doc = get_document_metadata(chunk.document_id)
        timeline.append({
            "date": doc.publication_date,
            "document": doc.name,
            "chunk_text": chunk.text,
            "embedding": chunk.vector
        })

    timeline.sort(key=lambda x: x["date"])

    # 3. Analyser évolution sémantique (drift analysis)
    evolution_metrics = []
    for i in range(1, len(timeline)):
        prev = timeline[i-1]
        curr = timeline[i]

        # Calculer distance sémantique
        semantic_drift = cosine_distance(
            prev["embedding"],
            curr["embedding"]
        )

        # Extraire thèmes émergents
        theme_shift = llm_analyze_theme_change(
            prev["chunk_text"],
            curr["chunk_text"]
        )

        evolution_metrics.append({
            "period": f"{prev['date']} → {curr['date']}",
            "semantic_drift": semantic_drift,
            "theme_shift": theme_shift,
            "documents": [prev["document"], curr["document"]]
        })

    # 4. Identifier tendances macro
    trends = identify_trends(evolution_metrics)
    # Ex: "Migration focus" → "AI Features focus" (2023 Q1 → Q4)

    return {
        "concept": concept.canonical_name,
        "total_mentions": len(chunks),
        "time_span": f"{timeline[0]['date']} - {timeline[-1]['date']}",
        "evolution_timeline": evolution_metrics,
        "key_trends": trends,
        "visualization_data": generate_timeline_viz(timeline)
    }
```

**Valeur Business** :
- ✅ **USP Unique** : Impossible avec Copilot/Gemini/ChatGPT
- ✅ ROI Consultant : Détecter shifts stratégiques SAP
- ✅ Sales Enablement : Prouver expertise évolution produits

**Use Case Concret** :
> "Analyser l'évolution de 'SAP S/4HANA Cloud' dans 15 CRR (2022-2024)"
> - 2022 Q1 : Focus "Migration ECC → S/4"
> - 2023 Q2 : Shift vers "Green Ledger & Sustainability"
> - 2024 Q1 : Émergence "Joule AI-powered ERP"
> → Insight stratégique pour positionnement commercial

**Implémentation** :
- Semaine 14 : Backend timeline construction + drift calculation
- Semaine 15 : LLM theme extraction + trend detection
- Semaine 16 : Frontend visualization (timeline interactif)
- Semaine 17 : Multi-concept comparison (benchmark concepts)

---

#### UC2.2 : Quality Assurance & Validation ✅

**Problème** : Le graphe dit "X INTEGRATES_WITH Y" mais les chunks sources disent le contraire → hallucination.

**Solution** :
```python
# Background job: Relation Validation
def validate_graph_relations(batch_size: int = 100):
    """
    Valide cohérence relations Neo4j avec chunks sources Qdrant.
    """
    # 1. Récupérer relations à valider
    relations = neo4j_client.get_relations(
        filters={"confidence": {"$lt": 0.8}}  # Basse confiance
    )

    for relation in relations[:batch_size]:
        # 2. Récupérer chunks des 2 concepts
        source_chunks = qdrant_client.retrieve(
            ids=relation.source_concept.chunk_ids
        )
        target_chunks = qdrant_client.retrieve(
            ids=relation.target_concept.chunk_ids
        )

        # 3. Trouver co-occurrences
        common_chunks = find_common_contexts(
            source_chunks,
            target_chunks
        )

        # 4. LLM validation
        if len(common_chunks) >= 3:  # Seuil minimum
            validation = llm_validate_relation(
                relation_type=relation.type,
                source=relation.source_concept.name,
                target=relation.target_concept.name,
                evidence_chunks=common_chunks
            )

            # 5. Mettre à jour metadata Neo4j
            neo4j_client.update_relation(
                relation.id,
                confidence=validation.confidence,
                evidence_count=len(common_chunks),
                caveats=validation.caveats
            )
```

**Valeur Business** :
- ✅ Graphe de confiance (détection hallucinations)
- ✅ Qualité garantie (audit automatique)
- ✅ Amélioration continue (feedback loop)

**Métriques de Succès** :
- 95% relations ont confidence > 0.7
- Détection +80% des incohérences graphe/texte
- Faux positifs < 5%

---

### Priorité 3 : Auto-Apprentissage (Semaines 18-20)

#### UC3.1 : Concept Enrichment Dynamique 💡

**Solution** :
```python
# Cron job quotidien
def enrich_concept_definitions():
    """
    Enrichit définitions concepts avec contextes réels.
    """
    for concept in neo4j_client.get_all_concepts():
        # Récupérer tous les chunks
        chunks = qdrant_client.retrieve(ids=concept.chunk_ids)

        if len(chunks) < 10:
            continue  # Pas assez de données

        # Clustering thématique des chunks
        facets = cluster_chunks_by_theme(chunks)
        # Ex: "Change Management" → 3 facettes:
        #   - Technical (deployment, testing)
        #   - Organizational (training, adoption)
        #   - Governance (approval workflows)

        # Générer définition enrichie
        enriched_def = llm_synthesize_definition(
            concept_name=concept.name,
            facets=facets,
            representative_chunks=select_representative_chunks(chunks)
        )

        # Mettre à jour Neo4j
        neo4j_client.update_concept(
            concept.id,
            enriched_definition=enriched_def,
            facets=facets
        )
```

**Valeur Business** :
- ✅ Ontologie vivante (définitions basées usage réel)
- ✅ Auto-apprentissage (pas de maintenance manuelle)
- ✅ Multi-facette (nuances contextuelles)

---

#### UC3.2 : Co-occurrence Mining & Relation Discovery 🔗

**Solution** :
```python
# Background job hebdomadaire
def discover_implicit_relations():
    """
    Découvre relations implicites non capturées par extraction initiale.
    """
    # 1. Analyser co-occurrences dans chunks
    co_occurrences = analyze_concept_cooccurrences(
        min_frequency=10,  # Apparaissent ensemble ≥10 fois
        window_size=512    # Dans une fenêtre de 512 tokens
    )

    for (concept_a, concept_b), frequency in co_occurrences.items():
        # 2. Vérifier si relation existe déjà
        existing_relation = neo4j_client.find_relation(
            concept_a.id,
            concept_b.id
        )

        if existing_relation:
            continue

        # 3. Récupérer chunks communs
        common_chunks = get_common_chunks(
            concept_a.chunk_ids,
            concept_b.chunk_ids
        )

        # 4. LLM extraction relation
        relation = llm_extract_relation(
            concept_a=concept_a.name,
            concept_b=concept_b.name,
            evidence_chunks=common_chunks
        )

        # 5. Créer ProtoConcept (soumis à Gatekeeper)
        if relation.confidence > 0.7:
            create_proto_relation(
                source=concept_a.id,
                target=concept_b.id,
                relation_type=relation.type,
                confidence=relation.confidence,
                evidence_chunks=common_chunks
            )
```

**Valeur Business** :
- ✅ Découverte automatique (pas besoin extraction manuelle)
- ✅ Ontologie auto-apprenante (s'enrichit dans le temps)
- ✅ Détection patterns cachés

---

## 🏗️ Architecture Technique

### Nouveaux Composants Phase 2

```
┌─────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                   │
├─────────────────────────────────────────────────────────┤
│  /concepts/{id}/explain          │ UC1.1 Provenance     │
│  /search/graph-guided             │ UC1.2 Hybrid Search  │
│  /concepts/{id}/evolution         │ UC2.1 Evolution      │
│  /relations/{id}/validate         │ UC2.2 Validation     │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              Graph-Powered Services Layer                │
├─────────────────────────────────────────────────────────┤
│  • GraphGuidedSearchService    (UC1.2)                  │
│  • ConceptExplainerService     (UC1.1)                  │
│  • EvolutionAnalyzerService    (UC2.1)                  │
│  • RelationValidatorService    (UC2.2)                  │
│  • CooccurrenceMinerService    (UC3.2)                  │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
┌─────────────────┐              ┌──────────────────┐
│   Neo4j Graph   │◄────────────►│  Qdrant Vector   │
│                 │  Cross-Ref   │                  │
│ • chunk_ids []  │  Bidir.      │ • canonical_ids  │
└─────────────────┘              └──────────────────┘
```

### Services à Développer

#### 1. `GraphGuidedSearchService` (Semaines 11-13)
```python
class GraphGuidedSearchService:
    """
    Recherche hybride exploitant expansion graphe.
    """
    def __init__(
        self,
        neo4j_client: Neo4jClient,
        qdrant_client: QdrantClient,
        embedder: SentenceTransformer
    ):
        self.neo4j = neo4j_client
        self.qdrant = qdrant_client
        self.embedder = embedder

    async def search(
        self,
        query: str,
        expansion_depth: int = 1,
        top_k: int = 10
    ) -> SearchResponse:
        # 1. Extract concepts from query
        concepts = await self._extract_query_concepts(query)

        # 2. Expand via graph (1-hop)
        expanded = await self._expand_concepts_graph(
            concepts,
            depth=expansion_depth
        )

        # 3. Retrieve all chunks from expanded concepts
        candidate_chunks = await self._get_chunks_from_concepts(
            expanded
        )

        # 4. Vector rerank
        query_embedding = self.embedder.encode(query)
        ranked = self._rerank_chunks(
            query_embedding,
            candidate_chunks,
            top_k=top_k
        )

        return SearchResponse(
            results=ranked,
            reasoning_path=[c.name for c in expanded],
            expansion_gain=len(candidate_chunks)
        )
```

#### 2. `EvolutionAnalyzerService` (Semaines 14-17)
```python
class EvolutionAnalyzerService:
    """
    Analyse évolution sémantique concepts dans le temps.
    """
    async def analyze_evolution(
        self,
        concept_id: str,
        time_range: Optional[TimeRange] = None
    ) -> EvolutionAnalysis:
        # 1. Get all chunks with timestamps
        chunks_timeline = await self._build_chunks_timeline(
            concept_id,
            time_range
        )

        # 2. Calculate semantic drift
        drift_metrics = await self._calculate_semantic_drift(
            chunks_timeline
        )

        # 3. Extract theme shifts
        theme_evolution = await self._analyze_theme_shifts(
            chunks_timeline
        )

        # 4. Identify macro trends
        trends = self._identify_trends(
            drift_metrics,
            theme_evolution
        )

        return EvolutionAnalysis(
            timeline=chunks_timeline,
            drift_metrics=drift_metrics,
            theme_evolution=theme_evolution,
            trends=trends
        )
```

---

## 📊 Métriques de Succès Phase 2

### KPIs Techniques

| Métrique | Target | Mesure |
|----------|--------|--------|
| **Graph-Guided Search Precision** | NDCG@10 > 0.85 | A/B test vs baseline |
| **Provenance Coverage** | 100% concepts | % concepts avec ≥1 chunk |
| **Evolution Tracking Latency** | < 2s (p95) | API response time |
| **Relation Validation Accuracy** | > 90% | Precision/Recall validation |
| **Cross-ref Integrity** | 99.9% | Audit Neo4j.chunk_ids ↔ Qdrant.canonical_ids |

### KPIs Business

| Métrique | Target | Impact |
|----------|--------|--------|
| **User Trust Score** | > 4.5/5 | Survey "Je fais confiance aux résultats" |
| **Adoption Rate** | +40% vs Phase 1 | DAU (Daily Active Users) |
| **CRR Evolution Demos** | 10 clients | Sales enablement showcase |
| **Query Success Rate** | > 90% | % requêtes avec réponse pertinente |

---

## 🗓️ Roadmap Détaillée Phase 2

### Semaines 11-13 : Fondations (Priorité 1)

**Objectif** : Délivrer valeur immédiate avec cross-référence

**Livrables** :
- ✅ API `/concepts/{id}/explain` (UC1.1)
- ✅ API `/search/graph-guided` (UC1.2)
- ✅ Tests A/B vs recherche vectorielle classique
- ✅ Documentation API + exemples

**Critères de Succès** :
- Graph-Guided Search : NDCG@10 > 0.80
- Provenance Coverage : 95% concepts
- Latence API < 300ms (p95)

---

### Semaines 14-17 : USP Différenciateurs (Priorité 2)

**Objectif** : CRR Evolution Tracker (démo commerciale)

**Livrables** :
- ✅ Backend Evolution Analysis (UC2.1)
- ✅ Frontend Timeline Visualization
- ✅ Multi-concept Comparison
- ✅ Relation Validation automatique (UC2.2)
- ✅ Démo client prête (use case SAP S/4HANA)

**Critères de Succès** :
- 10 demos CRR Evolution auprès clients
- Relation validation accuracy > 85%
- User feedback > 4/5 sur timeline viz

---

### Semaines 18-20 : Auto-Apprentissage (Priorité 3)

**Objectif** : Ontologie auto-apprenante

**Livrables** :
- ✅ Concept Enrichment quotidien (UC3.1)
- ✅ Co-occurrence Mining hebdomadaire (UC3.2)
- ✅ Dashboard admin (monitoring auto-learning)
- ✅ Documentation patterns découverts

**Critères de Succès** :
- 50+ relations découvertes automatiquement
- Concept enrichment : 80% concepts ont facets
- Zero-intervention uptime : 7 jours

---

## 🧪 Proof of Concept (POC) Recommandé

**Avant démarrage Phase 2**, valider l'approche avec mini-POC :

### POC : "Explain this Concept" (2-3 jours)

**Objectif** : Prouver valeur cross-référence Neo4j ↔ Qdrant

**Scope** :
```python
# Script POC simple
def poc_explain_concept(concept_name: str):
    # 1. Find concept in Neo4j
    concept = neo4j_client.find_concept_by_name(concept_name)

    # 2. Retrieve chunks via chunk_ids
    chunks = qdrant_client.retrieve(
        collection_name="knowbase",
        ids=concept.chunk_ids
    )

    # 3. Display provenance
    print(f"Concept: {concept.canonical_name}")
    print(f"Definition: {concept.unified_definition}")
    print(f"\nMentions ({len(chunks)} total):\n")

    for i, chunk in enumerate(chunks[:5], 1):
        doc_name = chunk.payload.get("document_name", "Unknown")
        print(f"{i}. [{doc_name}]")
        print(f"   {chunk.payload['text'][:200]}...")
        print()
```

**Critères Validation POC** :
- ✅ 100% concepts testés ont ≥1 chunk
- ✅ Temps execution < 500ms
- ✅ Feedback positif (3+ stakeholders)

**Si POC réussit** → Green light Phase 2 complète

---

## 🎓 Conclusion Phase 2

Phase 2 transforme KnowWhere d'un **simple RAG vectoriel** en un véritable **moteur d'intelligence relationnelle**.

**Différenciation stratégique** :
- ✅ **CRR Evolution Tracker** : USP impossible à copier
- ✅ **Graph-Guided RAG** : Précision +40% vs concurrents
- ✅ **Provenance Explicite** : Confiance & conformité

**Prêt pour Phase 3** : Production KG avec qualité garantie et auto-apprentissage validé.

---

**Prochaine étape** : Validation POC "Explain this Concept" (2-3 jours) avant démarrage complet Phase 2.
