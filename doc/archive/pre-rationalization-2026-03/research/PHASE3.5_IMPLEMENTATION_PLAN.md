# Plan d'Implémentation Phase 3.5 - Frontend Explainable Graph-RAG

**Version:** 1.0
**Date:** 2025-12-19
**Status:** 🟢 EN COURS
**Estimation:** 4-5 semaines pour Scope Démo MVP

---

## 1. Analyse de l'Existant

### 1.1 Backend (Ce qui existe)

| Composant | Status | Fichier |
|-----------|--------|---------|
| `POST /api/search` avec `graph_context` | ✅ Existant | `routers/search.py` |
| `GET /api/concepts/{id}/explain` | ✅ Existant | `routers/concepts.py` |
| `GraphGuidedSearchService` | ✅ Existant | `services/graph_guided_search.py` |
| Sessions + Messages | ✅ Existant | `routers/sessions.py` |
| `InferenceEngine` | ✅ Existant | `semantic/inference.py` |

### 1.2 Backend (Ce qui manque)

| Composant | Priorité | Description |
|-----------|----------|-------------|
| `graph_data` formaté D3.js | P0 | Transformer `graph_context` en `nodes[]` + `edges[]` |
| Highlighting des concepts | P0 | `query_concept_ids`, `used_concept_ids`, `suggested_concept_ids` |
| `GET /api/concepts/{id}/card` | P1 | Version enrichie pour panel slide-in |
| `GET /api/graph/subgraph` | P2 | Sous-graphe autour de concepts sélectionnés |

### 1.3 Frontend (Ce qui existe)

| Composant | Status | Fichier |
|-----------|--------|---------|
| `ChatPage` basique | ✅ À refondre | `app/chat/page.tsx` |
| `SessionSelector` | ✅ Réutilisable | `components/chat/SessionSelector.tsx` |
| `SessionSummary` | ✅ Réutilisable | `components/chat/SessionSummary.tsx` |
| `SearchResultDisplay` | ✅ À enrichir | `components/ui/SearchResultDisplay.tsx` |

### 1.4 Frontend (Ce qui manque - TOUT)

| Composant | Priorité | Complexité |
|-----------|----------|------------|
| **D3.js Setup + Types** | P0 | Medium |
| **KnowledgeGraph.tsx** | P0 | High |
| **GraphNode + GraphEdge** | P0 | Medium |
| **GraphTooltip** | P0 | Low |
| **AssistantMessage.tsx** (refonte) | P0 | High |
| **ConceptCardPanel.tsx** | P1 | High |
| **SourcesPanel.tsx** | P1 | Medium |
| **QueryExplainer.tsx** | P2 | Low |

---

## 2. Architecture Cible

### 2.1 Structure Fichiers Frontend

```
frontend/src/
├── components/
│   ├── chat/                              # Chat refondé
│   │   ├── ChatContainer.tsx              # Container principal (refonte)
│   │   ├── ChatMessages.tsx               # Zone messages scrollable
│   │   ├── AssistantMessage.tsx           # Message avec graphe + sources
│   │   ├── QueryExplainer.tsx             # "Comment j'ai compris"
│   │   ├── GraphPanel.tsx                 # Panel graphe inline
│   │   ├── SourcesPanel.tsx               # Panel sources inline
│   │   ├── SuggestedQuestions.tsx         # Questions suggérées
│   │   ├── SessionSelector.tsx            # ✅ Existant
│   │   └── SessionSummary.tsx             # ✅ Existant
│   │
│   ├── graph/                             # Composants D3 (NOUVEAU)
│   │   ├── KnowledgeGraph.tsx             # Wrapper D3 principal
│   │   ├── GraphCanvas.tsx                # Canvas SVG D3
│   │   ├── GraphNode.tsx                  # Rendu noeud
│   │   ├── GraphEdge.tsx                  # Rendu arête
│   │   ├── GraphTooltip.tsx               # Tooltip hover
│   │   ├── GraphLegend.tsx                # Légende couleurs
│   │   ├── GraphControls.tsx              # Zoom/Reset
│   │   └── useGraphSimulation.ts          # Hook force D3
│   │
│   ├── concept/                           # Panel Carte Concept (NOUVEAU)
│   │   ├── ConceptCardPanel.tsx           # Panel slide-in
│   │   ├── ConceptHeader.tsx              # Header avec badges
│   │   ├── ConceptDefinition.tsx          # Section définition
│   │   ├── ConceptRelations.tsx           # Tableau relations
│   │   ├── ConceptSources.tsx             # Liste sources
│   │   └── ConceptSuggestions.tsx         # Questions suggérées
│   │
│   └── ui/                                # UI générique
│       ├── SlidePanel.tsx                 # Panel glissant (NOUVEAU)
│       ├── ConfidenceBadge.tsx            # Badge confidence (NOUVEAU)
│       └── ConceptTag.tsx                 # Tag concept cliquable (NOUVEAU)
│
├── hooks/
│   ├── useChat.ts                         # État chat
│   ├── useGraphData.ts                    # Données graphe (NOUVEAU)
│   ├── useConceptCard.ts                  # Carte concept (NOUVEAU)
│   └── useGraphInteractions.ts            # Interactions D3 (NOUVEAU)
│
├── lib/
│   └── graph/                             # Utilitaires graphe (NOUVEAU)
│       ├── graphLayout.ts                 # Algos layout D3
│       ├── graphColors.ts                 # Palette couleurs
│       └── graphTransform.ts              # Transform API → D3
│
├── stores/
│   └── graphStore.ts                      # Zustand store graphe (NOUVEAU)
│
└── types/
    ├── graph.ts                           # Types GraphNode, GraphEdge (NOUVEAU)
    └── concept.ts                         # Types Concept, ConceptCard (NOUVEAU)
```

### 2.2 Flow de Données

```
User Question
     │
     ▼
POST /api/search (avec use_graph_context=true)
     │
     ▼
Backend retourne:
{
  "synthesis": { "synthesized_answer": "..." },
  "results": [...chunks...],
  "graph_context": {
    "query_concepts": [...],
    "related_concepts": [...],
    "transitive_relations": [...]
  },
  "graph_data": {            // ← NOUVEAU (à implémenter backend)
    "nodes": [...],
    "edges": [...],
    "query_concept_ids": [...],
    "used_concept_ids": [...],
    "suggested_concept_ids": [...]
  }
}
     │
     ▼
Frontend: AssistantMessage.tsx
     │
     ├─► Texte réponse (gauche)
     ├─► GraphPanel avec KnowledgeGraph D3 (centre)
     └─► SourcesPanel (droite)
```

---

## 3. Planning Détaillé (Scope Démo MVP)

### Semaine 1 : Fondations D3.js + Layout Chat

#### Jour 1-2 : Setup Technique

**Backend - Adapter la réponse `/api/search`:**

```python
# Ajouter dans search.py

def _transform_graph_context_to_d3(graph_context: dict, chunks: list) -> dict:
    """Transforme le graph_context en format D3.js."""
    nodes = []
    edges = []

    # Concepts de la question → nodes jaunes
    query_concept_ids = []
    for concept_name in graph_context.get("query_concepts", []):
        node_id = f"concept-{concept_name.lower().replace(' ', '-')}"
        query_concept_ids.append(node_id)
        nodes.append({
            "id": node_id,
            "name": concept_name,
            "type": "query",  # Sera coloré en jaune
            "confidence": 0.95,
            "mentionCount": 0
        })

    # Concepts liés → nodes verts ou bleus
    used_concept_ids = []
    suggested_concept_ids = []
    for rel in graph_context.get("related_concepts", []):
        concept = rel.get("concept", "")
        node_id = f"concept-{concept.lower().replace(' ', '-')}"

        # Déterminer si utilisé ou suggéré
        is_used = any(concept.lower() in (c.get("text", "").lower()) for c in chunks)

        if is_used:
            used_concept_ids.append(node_id)
        else:
            suggested_concept_ids.append(node_id)

        nodes.append({
            "id": node_id,
            "name": concept,
            "type": "used" if is_used else "suggested",
            "confidence": rel.get("confidence", 0.8),
            "mentionCount": rel.get("mention_count", 0)
        })

        # Edge vers le concept de la question
        if query_concept_ids:
            edges.append({
                "source": query_concept_ids[0],
                "target": node_id,
                "relationType": rel.get("relationship_type", "RELATED_TO"),
                "confidence": rel.get("confidence", 0.8),
                "isUsed": is_used
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "query_concept_ids": query_concept_ids,
        "used_concept_ids": used_concept_ids,
        "suggested_concept_ids": suggested_concept_ids
    }
```

**Frontend - Installation dépendances:**

```bash
cd frontend
npm install d3 @types/d3 framer-motion zustand
```

**Tasks Jour 1-2:**
- [ ] Modifier `search.py` pour retourner `graph_data`
- [ ] Créer `frontend/src/types/graph.ts`
- [ ] Créer `frontend/src/lib/graph/graphColors.ts`
- [ ] Créer `frontend/src/lib/graph/graphTransform.ts`
- [ ] Tester que l'API retourne bien les données

#### Jour 3-4 : KnowledgeGraph D3 de Base

**Créer les composants graphe:**

```typescript
// frontend/src/components/graph/KnowledgeGraph.tsx

interface KnowledgeGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  queryConceptIds: string[];
  usedConceptIds: string[];
  suggestedConceptIds: string[];
  onNodeClick: (node: GraphNode) => void;
  onNodeHover: (node: GraphNode | null) => void;
  width: number;
  height: number;
}
```

**Tasks Jour 3-4:**
- [ ] Créer `KnowledgeGraph.tsx` avec D3 force simulation
- [ ] Créer `GraphNode.tsx` (cercles colorés)
- [ ] Créer `GraphEdge.tsx` (lignes)
- [ ] Créer `useGraphSimulation.ts` hook
- [ ] Test rendu basique avec données mock

#### Jour 5 : Intégration Chat + Graphe

**Refonte du layout chat:**

```
┌─────────────────────────────────────────────────────────────┐
│  [SessionSelector]                           [Summary btn]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─ Message User ────────────────────────────────────────┐  │
│  │ Question de l'utilisateur                             │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ Message Assistant ───────────────────────────────────┐  │
│  │ ┌─────────────────┬────────────────┬────────────────┐ │  │
│  │ │   Réponse       │    Graphe D3   │    Sources     │ │  │
│  │ │   (50%)         │    (30%)       │    (20%)       │ │  │
│  │ └─────────────────┴────────────────┴────────────────┘ │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  [Input zone avec options KG]                               │
└─────────────────────────────────────────────────────────────┘
```

**Tasks Jour 5:**
- [ ] Créer `AssistantMessage.tsx` avec layout 3 colonnes
- [ ] Créer `GraphPanel.tsx` (wrapper du graphe)
- [ ] Créer `SourcesPanel.tsx` (liste sources basique)
- [ ] Intégrer dans `ChatPage.tsx`
- [ ] Test E2E question → réponse avec graphe

---

### Semaine 2 : Interactivité Graphe + Tooltips

#### Jour 6-7 : Tooltips et Hover

**Tasks:**
- [ ] Créer `GraphTooltip.tsx`
- [ ] Implémenter hover highlighting (concepts liés s'illuminent)
- [ ] Animation scale + glow au hover
- [ ] Tester sur différentes tailles de graphe

#### Jour 8-9 : Couleurs et Légende

**Système de couleurs:**

```typescript
// graphColors.ts
export const GRAPH_COLORS = {
  query: '#F6AD55',      // Jaune - concepts de la question
  used: '#48BB78',       // Vert - concepts utilisés
  suggested: '#4299E1',  // Bleu - concepts à explorer
  context: '#A0AEC0',    // Gris - contexte
  conflict: '#F56565',   // Rouge - conflits
};

export const EDGE_STYLES = {
  used: { stroke: '#48BB78', strokeWidth: 3, strokeDasharray: 'none' },
  available: { stroke: '#A0AEC0', strokeWidth: 1, strokeDasharray: 'none' },
  inferred: { stroke: '#A0AEC0', strokeWidth: 1, strokeDasharray: '5,5' },
};
```

**Tasks:**
- [ ] Créer `GraphLegend.tsx`
- [ ] Appliquer couleurs selon type de concept
- [ ] Styles d'arêtes (plein/pointillé)
- [ ] Test visuel des différents états

#### Jour 10 : Zoom et Contrôles

**Tasks:**
- [ ] Créer `GraphControls.tsx` (zoom in/out, reset, fullscreen)
- [ ] Implémenter zoom molette
- [ ] Implémenter pan drag
- [ ] Responsive: adapter à la taille du conteneur

---

### Semaine 3 : Panel Carte Concept

#### Jour 11-12 : SlidePanel et Structure

**Tasks:**
- [ ] Créer `SlidePanel.tsx` générique (animation Framer Motion)
- [ ] Créer `ConceptCardPanel.tsx` container
- [ ] Créer `ConceptHeader.tsx` avec badges

#### Jour 13-14 : Contenu Carte Concept

**Backend - Adapter `/api/concepts/{id}/explain`:**

L'endpoint existe déjà, vérifier qu'il retourne :
- `canonical_name`, `aliases`, `type`
- `confidence`, `mention_count`, `document_count`
- `definition` avec sources
- `relations` typées
- `suggested_questions`

**Tasks:**
- [ ] Créer `ConceptDefinition.tsx`
- [ ] Créer `ConceptRelations.tsx` (tableau)
- [ ] Créer `ConceptSources.tsx` (liste avec extraits)
- [ ] Intégrer click node → ouverture panel

#### Jour 15 : Questions Suggérées

**Tasks:**
- [ ] Créer `ConceptSuggestions.tsx`
- [ ] Click question → pré-remplir input chat
- [ ] Animation fermeture panel + focus input

---

### Semaine 4 : Sources + Polish Démo

#### Jour 16-17 : Sources Enrichies

**Tasks:**
- [ ] Enrichir `SourcesPanel.tsx` avec extraits
- [ ] Créer modal aperçu document (optionnel - version light)
- [ ] Click source → highlight dans texte réponse

#### Jour 18-19 : Query Explainer + Evidence-First

**Tasks:**
- [ ] Créer `QueryExplainer.tsx` ("Comment j'ai compris votre question")
- [ ] Afficher concepts détectés comme badges cliquables
- [ ] Implémenter Evidence-First (preuves avant réponse)

#### Jour 20 : Polish et Tests Démo

**Tasks:**
- [ ] Animations Framer Motion partout
- [ ] Loading states (skeletons)
- [ ] États d'erreur gracieux
- [ ] Test scénario démo complet
- [ ] Performance audit (Lighthouse)

---

## 4. Scope Démo MVP (Features Essentielles)

### Inclus dans le MVP

| Feature | Status | Notes |
|---------|--------|-------|
| **Graphe D3 interactif** | 🔴 | Core différenciation |
| **Système couleurs** | 🔴 | Jaune/Vert/Bleu |
| **Tooltips hover** | 🔴 | Nom + type + confidence |
| **Panel Carte Concept** | 🔴 | Slide-in droite |
| **Sources avec extraits** | 🔴 | Liste cliquable |
| **Query Explainer** | 🔴 | Concepts détectés |
| **Evidence-First** | 🔴 | Preuves en header |
| **Guardrail 40 nœuds** | 🔴 | Performance garantie |

### Différé Post-Démo

| Feature | Raison |
|---------|--------|
| Living Graph persistant | Complexité Memory Layer |
| Export PDF Session | IntelligentSummarizer à compléter |
| Expert Mode complet | Complexifie UX |
| Concept Comparator | Nice-to-have |
| Timeline Evolution | Nécessite TemporalDiffEngine |

---

## 5. Critères de Succès

### Techniques

| KPI | Target |
|-----|--------|
| Temps chargement graphe | < 500ms |
| FPS animations | ≥ 60fps |
| Bundle size (chat page) | < 500KB |
| Erreurs runtime | 0 (démo) |

### Démo Partenaire

| KPI | Validation |
|-----|------------|
| "Wow effect" visuel | Réaction partenaire |
| Différenciation vs Copilot | "Copilot ne fait pas ça" verbalisé |
| Demande test données réelles | Engagement concret |

---

## 6. Risques et Mitigation

| Risque | Probabilité | Mitigation |
|--------|-------------|------------|
| D3.js courbe apprentissage | Medium | Exemples existants, start early |
| Backend graph_data pas prêt | Low | Mock data frontend, paralléliser |
| Performance >40 nœuds | Low | Guardrail par design |

---

## 7. Prochaine Action

**Étape 1 (Aujourd'hui) :**
1. Modifier `/api/search` pour ajouter `graph_data`
2. Installer dépendances frontend (d3, framer-motion, zustand)
3. Créer les types TypeScript de base

**Go/No-Go :** Valider que l'API retourne bien les données formatées D3.js avant de commencer le frontend.

---

*Document créé le 2025-12-19 - Phase 3.5 Frontend Explainable Graph-RAG*
