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

#### UC3.3 : InferenceEngine - Découverte de Connaissances Cachées 🧠 **(KILLER FEATURE)**

**Problème** : Les documents contiennent des connaissances **implicites** non directement lisibles :
- Inférences transitives (A→B, B→C implique A~C)
- Signaux faibles (mentions rares mais critiques)
- Corrélations cachées (patterns non évidents)
- Contradictions inter-documents
- Trous structurels (concepts liés mais non connectés)

**Différenciation MASSIVE** : Aucun concurrent (Copilot, Gemini, ChatGPT) ne peut faire cela car ils n'ont pas de graphe de connaissances exploitable.

**Solution Architecture** (100% composants GRATUITS) :

```
┌─────────────────────────────────────────────────────────────┐
│                     INFERENCE ENGINE                         │
│                (Composants 100% Open Source)                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │  Neo4j GDS      │  │    PyKEEN       │  │   LLM        │ │
│  │  Community      │  │    (MIT)        │  │   Validator  │ │
│  │  (GPLv3 Free)   │  │                 │  │   (optionnel)│ │
│  ├─────────────────┤  ├─────────────────┤  ├──────────────┤ │
│  │ • PageRank      │  │ • TransE        │  │ • Valide     │ │
│  │ • Louvain       │  │ • RotatE        │  │   inférences │ │
│  │ • WCC           │  │ • ComplEx       │  │ • Génère     │ │
│  │ • Betweenness   │  │ • Link Predict. │  │   explications│ │
│  │ • Similarity    │  │ • Embedding KG  │  │              │ │
│  └────────┬────────┘  └────────┬────────┘  └──────┬───────┘ │
│           │                    │                   │         │
│           └────────────────────┼───────────────────┘         │
│                                ▼                             │
│                    ┌───────────────────┐                     │
│                    │  Insight Ranker   │                     │
│                    │  & Deduplicator   │                     │
│                    └───────────────────┘                     │
│                                │                             │
└────────────────────────────────┼─────────────────────────────┘
                                 ▼
                    ┌───────────────────┐
                    │  Hidden Insights  │
                    │  Dashboard        │
                    └───────────────────┘
```

**Licences et Coûts** :

| Composant | Licence | Coût | Limitations |
|-----------|---------|------|-------------|
| **Neo4j Community** | GPLv3 | **GRATUIT** | Single instance |
| **Neo4j GDS Community** | GPLv3 | **GRATUIT** | 4 CPU cores max |
| **PyKEEN** | MIT | **GRATUIT** | Aucune |
| **NetworkX** (fallback) | BSD | **GRATUIT** | Aucune |

**Implémentation** :

```python
# src/knowbase/semantic/inference_engine.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import asyncio


class InsightType(Enum):
    """Types d'insights découvrables."""
    TRANSITIVE_INFERENCE = "transitive"      # A→B→C implique A~C
    WEAK_SIGNAL = "weak_signal"              # Mention rare mais critique
    STRUCTURAL_HOLE = "structural_hole"      # Lien manquant évident
    CONTRADICTION = "contradiction"          # Conflit inter-documents
    HIDDEN_CLUSTER = "hidden_cluster"        # Communauté non évidente
    BRIDGE_CONCEPT = "bridge_concept"        # Concept connecteur clé


@dataclass
class DiscoveredInsight:
    """Insight découvert par l'InferenceEngine."""
    insight_type: InsightType
    title: str
    description: str
    confidence: float  # 0.0 - 1.0
    evidence: list[str]  # Chunks/documents sources
    affected_concepts: list[str]
    business_impact: Optional[str] = None


class InferenceEngine:
    """
    Moteur de découverte de connaissances cachées.

    Utilise UNIQUEMENT des composants gratuits :
    - Neo4j GDS Community (graph algorithms)
    - PyKEEN (knowledge graph embeddings)
    - LLM optionnel (validation/explication)
    """

    def __init__(
        self,
        neo4j_client,
        qdrant_client,
        llm_client=None  # Optionnel pour validation
    ):
        self.neo4j = neo4j_client
        self.qdrant = qdrant_client
        self.llm = llm_client

    async def discover_insights(
        self,
        scope: Optional[str] = None,  # Filtre domaine
        methods: list[str] = None     # Méthodes à utiliser
    ) -> list[DiscoveredInsight]:
        """
        Lance la découverte d'insights sur le graphe.

        Args:
            scope: Filtrer par domaine (ex: "SAP BTP")
            methods: Liste de méthodes ["transitive", "weak_signal", ...]
                     Si None, utilise toutes les méthodes
        """
        methods = methods or [
            "transitive", "weak_signal", "structural_hole",
            "contradiction", "community"
        ]

        insights = []

        # Exécuter méthodes en parallèle
        tasks = []
        if "transitive" in methods:
            tasks.append(self._find_transitive_inferences(scope))
        if "weak_signal" in methods:
            tasks.append(self._detect_weak_signals(scope))
        if "structural_hole" in methods:
            tasks.append(self._find_structural_holes(scope))
        if "contradiction" in methods:
            tasks.append(self._detect_contradictions(scope))
        if "community" in methods:
            tasks.append(self._discover_hidden_communities(scope))

        results = await asyncio.gather(*tasks)
        for result in results:
            insights.extend(result)

        # Dédupliquer et ranker
        insights = self._rank_and_deduplicate(insights)

        return insights

    # ============================================================
    # MÉTHODE 1: Inférences Transitives (Cypher natif - GRATUIT)
    # ============================================================
    async def _find_transitive_inferences(
        self,
        scope: Optional[str] = None
    ) -> list[DiscoveredInsight]:
        """
        Trouve les chemins transitifs A→B→C où A et C ne sont pas
        directement liés mais devraient l'être.

        Utilise: Cypher natif (aucun plugin requis)
        """
        query = """
        // Trouver concepts connectés via intermédiaire mais pas directement
        MATCH path = (a:Concept)-[r1]->(b:Concept)-[r2]->(c:Concept)
        WHERE a <> c
        AND NOT (a)-[]-(c)  // Pas de lien direct
        AND a.quality_score > 0.6
        AND c.quality_score > 0.6

        // Calculer force inférence
        WITH a, b, c, r1, r2,
             (a.quality_score + c.quality_score) / 2 AS confidence
        WHERE confidence > 0.7

        RETURN
            a.canonical_name AS source,
            type(r1) AS rel1,
            b.canonical_name AS bridge,
            type(r2) AS rel2,
            c.canonical_name AS target,
            confidence,
            a.chunk_ids AS source_chunks,
            c.chunk_ids AS target_chunks
        ORDER BY confidence DESC
        LIMIT 50
        """

        results = await self.neo4j.execute_query(query)
        insights = []

        for row in results:
            insight = DiscoveredInsight(
                insight_type=InsightType.TRANSITIVE_INFERENCE,
                title=f"Lien implicite: {row['source']} ↔ {row['target']}",
                description=(
                    f"'{row['source']}' est lié à '{row['target']}' "
                    f"via '{row['bridge']}' "
                    f"({row['rel1']} → {row['rel2']}), "
                    f"mais aucun lien direct n'existe."
                ),
                confidence=row['confidence'],
                evidence=row['source_chunks'][:3] + row['target_chunks'][:3],
                affected_concepts=[row['source'], row['bridge'], row['target']],
                business_impact=self._assess_transitive_impact(row)
            )
            insights.append(insight)

        return insights

    # ============================================================
    # MÉTHODE 2: Signaux Faibles (Neo4j GDS Community - GRATUIT)
    # ============================================================
    async def _detect_weak_signals(
        self,
        scope: Optional[str] = None
    ) -> list[DiscoveredInsight]:
        """
        Détecte les concepts rarement mentionnés mais à haute valeur.

        Utilise: PageRank + analyse mentions (Neo4j GDS Community)
        """
        # Étape 1: Calculer PageRank pour importance structurelle
        pagerank_query = """
        CALL gds.pageRank.stream('concept-graph', {
            maxIterations: 20,
            dampingFactor: 0.85
        })
        YIELD nodeId, score
        WITH gds.util.asNode(nodeId) AS concept, score AS pagerank

        // Trouver concepts à haut PageRank mais peu de chunks
        WHERE size(concept.chunk_ids) < 5  // Rarement mentionné
        AND pagerank > 0.1                  // Mais structurellement important

        RETURN
            concept.canonical_name AS name,
            concept.unified_definition AS definition,
            size(concept.chunk_ids) AS mention_count,
            pagerank,
            concept.chunk_ids AS chunks
        ORDER BY pagerank DESC
        LIMIT 20
        """

        results = await self.neo4j.execute_query(pagerank_query)
        insights = []

        for row in results:
            insight = DiscoveredInsight(
                insight_type=InsightType.WEAK_SIGNAL,
                title=f"Signal faible: {row['name']}",
                description=(
                    f"'{row['name']}' n'est mentionné que {row['mention_count']} fois "
                    f"mais possède une importance structurelle élevée "
                    f"(PageRank: {row['pagerank']:.3f}). "
                    f"Ce concept mérite une attention particulière."
                ),
                confidence=min(row['pagerank'] * 2, 0.95),
                evidence=row['chunks'],
                affected_concepts=[row['name']],
                business_impact="Concept potentiellement sous-estimé"
            )
            insights.append(insight)

        return insights

    # ============================================================
    # MÉTHODE 3: Trous Structurels (Neo4j GDS Community - GRATUIT)
    # ============================================================
    async def _find_structural_holes(
        self,
        scope: Optional[str] = None
    ) -> list[DiscoveredInsight]:
        """
        Identifie les paires de concepts qui devraient être liées
        (voisins communs, similarité sémantique) mais ne le sont pas.

        Utilise: Node Similarity (Neo4j GDS Community)
        """
        # Projeter graphe pour GDS
        project_query = """
        CALL gds.graph.project(
            'similarity-graph',
            'Concept',
            {
                RELATES_TO: {orientation: 'UNDIRECTED'},
                INTEGRATES_WITH: {orientation: 'UNDIRECTED'},
                DEPENDS_ON: {orientation: 'UNDIRECTED'}
            }
        )
        """

        # Calculer similarité nodale (voisins communs)
        similarity_query = """
        CALL gds.nodeSimilarity.stream('similarity-graph', {
            topK: 10,
            similarityCutoff: 0.5
        })
        YIELD node1, node2, similarity
        WITH gds.util.asNode(node1) AS c1,
             gds.util.asNode(node2) AS c2,
             similarity

        // Filtrer paires sans lien direct
        WHERE NOT (c1)-[]-(c2)
        AND similarity > 0.6

        RETURN
            c1.canonical_name AS concept1,
            c2.canonical_name AS concept2,
            similarity,
            c1.chunk_ids AS chunks1,
            c2.chunk_ids AS chunks2
        ORDER BY similarity DESC
        LIMIT 30
        """

        try:
            await self.neo4j.execute_query(project_query)
            results = await self.neo4j.execute_query(similarity_query)
        finally:
            # Nettoyer projection
            await self.neo4j.execute_query(
                "CALL gds.graph.drop('similarity-graph', false)"
            )

        insights = []
        for row in results:
            insight = DiscoveredInsight(
                insight_type=InsightType.STRUCTURAL_HOLE,
                title=f"Lien manquant: {row['concept1']} ↔ {row['concept2']}",
                description=(
                    f"'{row['concept1']}' et '{row['concept2']}' partagent "
                    f"de nombreux voisins communs (similarité: {row['similarity']:.2f}) "
                    f"mais n'ont aucun lien direct. "
                    f"Un lien devrait probablement exister."
                ),
                confidence=row['similarity'],
                evidence=row['chunks1'][:2] + row['chunks2'][:2],
                affected_concepts=[row['concept1'], row['concept2']],
                business_impact="Relation potentiellement non documentée"
            )
            insights.append(insight)

        return insights

    # ============================================================
    # MÉTHODE 4: Détection Contradictions (LLM + Qdrant)
    # ============================================================
    async def _detect_contradictions(
        self,
        scope: Optional[str] = None
    ) -> list[DiscoveredInsight]:
        """
        Trouve les affirmations contradictoires entre documents.

        Utilise: Qdrant similarity + LLM validation
        """
        if not self.llm:
            return []  # LLM requis pour cette méthode

        # Récupérer concepts avec plusieurs sources
        query = """
        MATCH (c:Concept)
        WHERE size(c.chunk_ids) >= 3
        RETURN c.canonical_name AS name, c.chunk_ids AS chunks
        LIMIT 100
        """

        concepts = await self.neo4j.execute_query(query)
        insights = []

        for concept in concepts:
            # Récupérer chunks du concept
            chunks = await self.qdrant.retrieve(
                collection_name="knowbase",
                ids=concept['chunks']
            )

            if len(chunks) < 2:
                continue

            # Comparer paires de chunks pour contradictions
            for i, chunk_a in enumerate(chunks[:-1]):
                for chunk_b in chunks[i+1:]:
                    # Skip si même document
                    if (chunk_a.payload.get('document_id') ==
                        chunk_b.payload.get('document_id')):
                        continue

                    # LLM vérifie contradiction
                    contradiction = await self._check_contradiction(
                        concept['name'],
                        chunk_a.payload['text'],
                        chunk_b.payload['text']
                    )

                    if contradiction and contradiction['is_contradiction']:
                        insight = DiscoveredInsight(
                            insight_type=InsightType.CONTRADICTION,
                            title=f"Contradiction: {concept['name']}",
                            description=contradiction['explanation'],
                            confidence=contradiction['confidence'],
                            evidence=[chunk_a.id, chunk_b.id],
                            affected_concepts=[concept['name']],
                            business_impact="Information incohérente à résoudre"
                        )
                        insights.append(insight)
                        break  # Une contradiction suffit par concept

        return insights

    # ============================================================
    # MÉTHODE 5: Communautés Cachées (Louvain - GDS Community)
    # ============================================================
    async def _discover_hidden_communities(
        self,
        scope: Optional[str] = None
    ) -> list[DiscoveredInsight]:
        """
        Découvre des clusters de concepts non évidents.

        Utilise: Louvain Community Detection (Neo4j GDS Community)
        """
        # Projeter et détecter communautés
        community_query = """
        CALL gds.louvain.stream('concept-graph', {
            maxLevels: 10,
            maxIterations: 10
        })
        YIELD nodeId, communityId
        WITH communityId, collect(gds.util.asNode(nodeId)) AS members
        WHERE size(members) >= 3 AND size(members) <= 15

        // Récupérer infos communauté
        RETURN
            communityId,
            [m IN members | m.canonical_name] AS concept_names,
            size(members) AS size,
            reduce(s = 0.0, m IN members | s + m.quality_score) / size(members) AS avg_quality
        ORDER BY size DESC
        LIMIT 20
        """

        results = await self.neo4j.execute_query(community_query)
        insights = []

        for row in results:
            # Vérifier si communauté est "surprenante" (concepts de domaines différents)
            is_surprising = await self._is_surprising_cluster(row['concept_names'])

            if is_surprising:
                insight = DiscoveredInsight(
                    insight_type=InsightType.HIDDEN_CLUSTER,
                    title=f"Cluster caché: {', '.join(row['concept_names'][:3])}...",
                    description=(
                        f"Un groupe de {row['size']} concepts forme une communauté "
                        f"non évidente: {', '.join(row['concept_names'])}. "
                        f"Ces concepts sont fortement interconnectés dans la documentation."
                    ),
                    confidence=row['avg_quality'],
                    evidence=[],  # Pas de chunks spécifiques
                    affected_concepts=row['concept_names'],
                    business_impact="Synergie potentielle à explorer"
                )
                insights.append(insight)

        return insights

    # ============================================================
    # Méthodes utilitaires
    # ============================================================
    def _rank_and_deduplicate(
        self,
        insights: list[DiscoveredInsight]
    ) -> list[DiscoveredInsight]:
        """Trie par confiance et déduplique insights similaires."""
        # Trier par confiance
        insights.sort(key=lambda x: x.confidence, reverse=True)

        # Dédupliquer (concepts similaires)
        seen_concepts = set()
        unique_insights = []

        for insight in insights:
            key = frozenset(insight.affected_concepts)
            if key not in seen_concepts:
                seen_concepts.add(key)
                unique_insights.append(insight)

        return unique_insights[:50]  # Top 50

    async def _check_contradiction(
        self,
        concept_name: str,
        text_a: str,
        text_b: str
    ) -> Optional[dict]:
        """Utilise LLM pour vérifier contradiction."""
        prompt = f"""
        Analyse ces deux extraits concernant "{concept_name}".

        Extrait A: {text_a[:500]}
        Extrait B: {text_b[:500]}

        Ces extraits contiennent-ils une CONTRADICTION factuelle ?
        Réponds en JSON: {{"is_contradiction": bool, "confidence": float, "explanation": str}}
        """

        response = await self.llm.complete(prompt)
        # Parser JSON response...
        return response

    def _assess_transitive_impact(self, row: dict) -> str:
        """Évalue impact business d'une inférence transitive."""
        rel_types = {row['rel1'], row['rel2']}

        if 'DEPENDS_ON' in rel_types:
            return "Dépendance indirecte potentielle"
        elif 'SECURES' in rel_types:
            return "Implication sécurité à vérifier"
        elif 'INTEGRATES_WITH' in rel_types:
            return "Intégration possible non documentée"
        else:
            return "Relation à investiguer"

    async def _is_surprising_cluster(self, concepts: list[str]) -> bool:
        """Vérifie si cluster est surprenant (cross-domaine)."""
        # Logique simplifiée : surprenant si > 1 domaine
        domains = set()
        domain_keywords = {
            'security': ['security', 'auth', 'sso', 'rbac'],
            'integration': ['api', 'integration', 'connector'],
            'analytics': ['analytics', 'report', 'dashboard'],
            'cloud': ['cloud', 'btp', 'azure', 'aws']
        }

        for concept in concepts:
            concept_lower = concept.lower()
            for domain, keywords in domain_keywords.items():
                if any(kw in concept_lower for kw in keywords):
                    domains.add(domain)

        return len(domains) >= 2  # Cross-domaine
```

**API Endpoints** :

```python
# src/knowbase/api/routers/inference.py

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/v1/inference", tags=["inference"])

@router.get("/discover")
async def discover_insights(
    scope: Optional[str] = Query(None, description="Filtrer par domaine"),
    methods: Optional[str] = Query(
        None,
        description="Méthodes (comma-sep): transitive,weak_signal,structural_hole,contradiction,community"
    ),
    limit: int = Query(20, le=50)
):
    """
    Découvre des connaissances cachées dans le graphe.

    Returns:
        Liste d'insights avec type, description, confiance et preuves.
    """
    method_list = methods.split(',') if methods else None

    engine = InferenceEngine(
        neo4j_client=get_neo4j(),
        qdrant_client=get_qdrant(),
        llm_client=get_llm()  # Optionnel
    )

    insights = await engine.discover_insights(
        scope=scope,
        methods=method_list
    )

    return {
        "total": len(insights),
        "insights": [
            {
                "type": i.insight_type.value,
                "title": i.title,
                "description": i.description,
                "confidence": i.confidence,
                "affected_concepts": i.affected_concepts,
                "business_impact": i.business_impact,
                "evidence_count": len(i.evidence)
            }
            for i in insights[:limit]
        ]
    }

@router.get("/insights/{insight_type}")
async def get_insights_by_type(
    insight_type: str,
    limit: int = Query(10, le=30)
):
    """Récupère insights d'un type spécifique."""
    # Implementation...
    pass
```

**Valeur Business** :
- ✅ **USP KILLER** : Aucun concurrent ne peut découvrir des connaissances cachées
- ✅ **Due Diligence** : Détecter risques/contradictions avant décision
- ✅ **Innovation** : Identifier opportunités cross-domaine non évidentes
- ✅ **Audit** : Repérer incohérences documentaires automatiquement

**Use Cases Concrets** :

| Insight Type | Exemple Réel | Impact Business |
|--------------|--------------|-----------------|
| **Transitive** | "SAP BTP → Cloud Connector → S/4HANA" implique BTP↔S/4 | Dépendance critique non documentée |
| **Weak Signal** | "Green Ledger" mentionné 2x mais PageRank élevé | Trend émergent à surveiller |
| **Structural Hole** | "RBAC" et "SSO" jamais liés mais voisins communs | Intégration sécurité à documenter |
| **Contradiction** | Doc A: "BTP supporte X", Doc B: "X n'est pas supporté" | Incohérence à résoudre |
| **Hidden Cluster** | {Analytics, ML, Joule, BTP} forment communauté | Convergence IA SAP |

**Métriques de Succès** :
- 50+ insights pertinents par run
- Precision des insights > 70% (validation humaine)
- Temps d'exécution < 30s (graphe 10K concepts)
- Adoption : 80% users trouvent ≥1 insight actionable

**Implémentation** :
- Semaine 18 : InferenceEngine core (transitive, weak_signal)
- Semaine 19 : Méthodes avancées (structural_hole, community)
- Semaine 20 : API + Dashboard insights + Validation LLM

---

## 🏗️ Architecture Technique

### Nouveaux Composants Phase 2

```
┌───────────────────────────────────────────────────────────────┐
│                      API Layer (FastAPI)                       │
├───────────────────────────────────────────────────────────────┤
│  /concepts/{id}/explain          │ UC1.1 Provenance           │
│  /search/graph-guided            │ UC1.2 Hybrid Search        │
│  /concepts/{id}/evolution        │ UC2.1 Evolution            │
│  /relations/{id}/validate        │ UC2.2 Validation           │
│  /inference/discover             │ UC3.3 Hidden Knowledge 🆕  │
│  /inference/insights/{type}      │ UC3.3 Insights by Type 🆕  │
└───────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────┐
│                Graph-Powered Services Layer                    │
├───────────────────────────────────────────────────────────────┤
│  • GraphGuidedSearchService    (UC1.2)                        │
│  • ConceptExplainerService     (UC1.1)                        │
│  • EvolutionAnalyzerService    (UC2.1)                        │
│  • RelationValidatorService    (UC2.2)                        │
│  • CooccurrenceMinerService    (UC3.2)                        │
│  • InferenceEngine             (UC3.3) 🆕 KILLER FEATURE      │
└───────────────────────────────────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐
│   Neo4j Graph   │  │  Neo4j GDS   │  │  Qdrant Vector   │
│   Community     │  │  Community   │  │                  │
│                 │  │  (GRATUIT)   │  │                  │
│ • chunk_ids []  │  │ • PageRank   │  │ • canonical_ids  │
│ • Cypher natif  │  │ • Louvain    │  │ • embeddings     │
│                 │  │ • Similarity │  │                  │
└────────┬────────┘  └──────────────┘  └────────┬─────────┘
         │                                      │
         └──────────── Cross-Ref ───────────────┘
                      Bidirectionnelle
```

### Stack Technique InferenceEngine (100% GRATUIT)

| Composant | Rôle | Licence | Coût |
|-----------|------|---------|------|
| **Neo4j Community** | Base graphe | GPLv3 | GRATUIT |
| **Neo4j GDS Community** | Algorithmes graphe (PageRank, Louvain, Similarity) | GPLv3 | GRATUIT |
| **PyKEEN** | Embeddings KG (TransE, RotatE) | MIT | GRATUIT |
| **NetworkX** | Fallback Python natif | BSD | GRATUIT |
| **LLM** (optionnel) | Validation insights | - | Usage existant |

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

### Semaines 18-20 : Auto-Apprentissage & Découverte (Priorité 3)

**Objectif** : Ontologie auto-apprenante + **InferenceEngine (KILLER FEATURE)**

**Livrables** :
- ✅ Concept Enrichment quotidien (UC3.1)
- ✅ Co-occurrence Mining hebdomadaire (UC3.2)
- ✅ **InferenceEngine core** (UC3.3) 🆕
  - Inférences transitives (Cypher natif)
  - Signaux faibles (PageRank - Neo4j GDS Community)
  - Trous structurels (Node Similarity - Neo4j GDS Community)
- ✅ **API `/inference/discover`** 🆕
- ✅ **Dashboard Hidden Insights** 🆕
- ✅ Dashboard admin (monitoring auto-learning)
- ✅ Documentation patterns découverts

**Critères de Succès** :
- 50+ relations découvertes automatiquement
- Concept enrichment : 80% concepts ont facets
- Zero-intervention uptime : 7 jours
- **InferenceEngine** 🆕 :
  - 50+ insights pertinents par run
  - Précision insights > 70% (validation humaine)
  - Temps d'exécution < 30s (graphe 10K concepts)
  - 80% users trouvent ≥1 insight actionable

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
