# Addendum — POC Graphiti UI (Visualisation & Navigation)

Ce document complète `doc/GRAPHITI_INTEGRATION_PLAN.md` et `doc/GRAPHITI_POC_TRACKING.md` avec un POC dédié à l’interface utilisateur (Phase 0-ter).  
Objectif : valider la faisabilité et l’ergonomie de la **visualisation et exploration interactive du Knowledge Graph** depuis le frontend ReactJS.

---

## 1) Phase 0-ter — POC UI Graphiti

### Objectifs
- Afficher un sous-graphe (entités + relations) à partir d’un `entity_id`.
- Naviguer dans le graphe (zoom/pan, clic sur nœud pour expansion).
- Intégrer une timeline (filtrage par date `as_of`) pour valider la dimension temporelle.
- Valider la compatibilité multi-tenant (`group_id` propagé depuis header).
- Mesurer les performances UI (latence < 500 ms perçu sur expansion).

### Périmètre POC
- ReactJS + lib de graphes (`react-force-graph` ou `Cytoscape.js`).
- Backend wrapper minimal (`/subgraph`, `/entity`, `/search`).
- Timeline : slider + rechargement du sous-graphe avec paramètre `at`.
- Panneau latéral “Entity detail” (nom, type, propriétés, relations sortantes/entrantes).
- Interactions : clic sur nœud = expansion `depth+1`.

### Livrables
- `src/ui/GraphViewer.jsx` (page principale).
- `src/ui/EntityDetail.jsx` (panneau d’info).
- `src/ui/hooks/useGraphData.js` (fetch API).
- Endpoints REST exposés (`/subgraph`, `/entity`, `/search`).
- `docker-compose.poc-ui.yml` incluant frontend servi via Nginx ou Vite.
- Captures/vidéo d’usage pour revue GO/NO-GO.

### Métriques baseline
- Rendu initial d’un sous-graphe depth=2 < 1,5 s (p95).
- Expansion d’un nœud depth+1 < 500 ms (perçu utilisateur).
- UI fluide (zoom/pan < 50 ms par frame).
- CPU navigateur < 50% sur graphe ≤ 300 nœuds.

### GO/NO-GO
- **GO** si UI fluide, navigation intuitive, endpoints backend suffisants.
- **NO-GO** si rendu trop lent (> 2s sur depth=2), freeze navigateur ou incapacité à filtrer temporellement.

### Checklist POC
- [ ] Endpoints `/subgraph`, `/entity` exposés (FastAPI).
- [ ] Page `GraphViewer` en React opérationnelle.
- [ ] Interaction clic→expansion validée.
- [ ] Timeline slider fonctionnelle.
- [ ] Bench UI exécuté (300 nœuds).
- [ ] Captures consignées.
- [ ] Décision GO/NO-GO documentée.

---

## 2) Interfaces d’Abstraction côté Frontend

```typescript
// src/ui/types.ts

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  properties?: Record<string, any>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  valid_from?: string;
  valid_to?: string;
}

export interface SubgraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
