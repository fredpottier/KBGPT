/**
 * 🌊 OSMOSE Phase 3.5 - Graph Store (Zustand)
 *
 * Store de gestion d'état pour le Knowledge Graph D3.js.
 * Gère les noeuds, arêtes, interactions et accumulation de concepts par session.
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import type { GraphNode, GraphEdge, GraphData, ConceptRole } from '@/types/graph';

/**
 * État du graphe
 */
interface GraphState {
  // Données du graphe
  nodes: GraphNode[];
  edges: GraphEdge[];

  // Classification des concepts
  queryConceptIds: string[];
  usedConceptIds: string[];
  suggestedConceptIds: string[];

  // Interactions
  selectedNodeId: string | null;
  hoveredNodeId: string | null;
  focusedNodeId: string | null; // Pour centrer le graphe sur un noeud

  // Configuration
  isVisible: boolean;
  autoExpand: boolean; // Accumuler les concepts au fil de la session

  // Historique de session (pour accumulation)
  sessionHistory: {
    nodeIds: Set<string>;
    edgeIds: Set<string>;
  };
}

/**
 * Actions du store
 */
interface GraphActions {
  // Données
  setGraphData: (data: GraphData) => void;
  mergeGraphData: (data: GraphData) => void; // Accumule au lieu de remplacer
  clearGraph: () => void;

  // Interactions
  selectNode: (nodeId: string | null) => void;
  hoverNode: (nodeId: string | null) => void;
  focusNode: (nodeId: string | null) => void;

  // Classification
  markNodeAsUsed: (nodeId: string) => void;
  markNodesAsUsed: (nodeIds: string[]) => void;

  // Visibilité
  toggleVisibility: () => void;
  setVisibility: (visible: boolean) => void;

  // Configuration
  setAutoExpand: (enabled: boolean) => void;

  // Reset
  resetGraph: () => void;
  resetSession: () => void;
}

type GraphStore = GraphState & GraphActions;

/**
 * État initial
 */
const initialState: GraphState = {
  nodes: [],
  edges: [],
  queryConceptIds: [],
  usedConceptIds: [],
  suggestedConceptIds: [],
  selectedNodeId: null,
  hoveredNodeId: null,
  focusedNodeId: null,
  isVisible: true,
  autoExpand: true,
  sessionHistory: {
    nodeIds: new Set(),
    edgeIds: new Set(),
  },
};

/**
 * Store Zustand pour le graphe
 */
export const useGraphStore = create<GraphStore>()(
  devtools(
    (set, get) => ({
      ...initialState,

      /**
       * Remplace les données du graphe (nouvelle recherche)
       */
      setGraphData: (data: GraphData) => {
        const { autoExpand } = get();

        if (autoExpand) {
          // Si autoExpand, fusionner avec l'historique
          get().mergeGraphData(data);
        } else {
          // Sinon, remplacer complètement
          set({
            nodes: data.nodes,
            edges: data.edges,
            queryConceptIds: data.queryConceptIds,
            usedConceptIds: data.usedConceptIds,
            suggestedConceptIds: data.suggestedConceptIds,
            selectedNodeId: null,
            hoveredNodeId: null,
          });
        }
      },

      /**
       * Fusionne les nouvelles données avec le graphe existant
       * Permet l'accumulation de concepts au fil de la session
       */
      mergeGraphData: (data: GraphData) => {
        const state = get();
        const existingNodeIds = new Set(state.nodes.map((n) => n.id));
        const existingEdgeIds = new Set(state.edges.map((e) => e.id));

        // Ajouter les nouveaux noeuds (pas de doublons)
        const newNodes = data.nodes.filter((n) => !existingNodeIds.has(n.id));
        const mergedNodes = [...state.nodes, ...newNodes];

        // Mettre à jour les rôles des noeuds existants si nécessaire
        const updatedNodes = mergedNodes.map((node) => {
          // Si ce noeud est dans queryConceptIds du nouveau data, le marquer comme query
          if (data.queryConceptIds.includes(node.id)) {
            return { ...node, role: 'query' as ConceptRole };
          }
          // Si ce noeud est dans usedConceptIds, le marquer comme used
          if (data.usedConceptIds.includes(node.id)) {
            return { ...node, role: 'used' as ConceptRole };
          }
          return node;
        });

        // Ajouter les nouvelles arêtes
        const newEdges = data.edges.filter((e) => !existingEdgeIds.has(e.id));
        const mergedEdges = [...state.edges, ...newEdges];

        // Mettre à jour l'historique de session
        const newHistory = {
          nodeIds: new Set([...state.sessionHistory.nodeIds, ...data.nodes.map((n) => n.id)]),
          edgeIds: new Set([...state.sessionHistory.edgeIds, ...data.edges.map((e) => e.id)]),
        };

        // Fusionner les IDs de concepts
        const mergedQueryIds = [...new Set([...state.queryConceptIds, ...data.queryConceptIds])];
        const mergedUsedIds = [...new Set([...state.usedConceptIds, ...data.usedConceptIds])];
        const mergedSuggestedIds = [
          ...new Set([...state.suggestedConceptIds, ...data.suggestedConceptIds]),
        ];

        set({
          nodes: updatedNodes,
          edges: mergedEdges,
          queryConceptIds: mergedQueryIds,
          usedConceptIds: mergedUsedIds,
          suggestedConceptIds: mergedSuggestedIds,
          sessionHistory: newHistory,
        });
      },

      /**
       * Efface le graphe actuel
       */
      clearGraph: () => {
        set({
          nodes: [],
          edges: [],
          queryConceptIds: [],
          usedConceptIds: [],
          suggestedConceptIds: [],
          selectedNodeId: null,
          hoveredNodeId: null,
          focusedNodeId: null,
        });
      },

      /**
       * Sélectionne un noeud (ouvre le panel concept)
       */
      selectNode: (nodeId: string | null) => {
        set({ selectedNodeId: nodeId });
      },

      /**
       * Survol d'un noeud (tooltip)
       */
      hoverNode: (nodeId: string | null) => {
        set({ hoveredNodeId: nodeId });
      },

      /**
       * Focus sur un noeud (centrer le graphe)
       */
      focusNode: (nodeId: string | null) => {
        set({ focusedNodeId: nodeId });
      },

      /**
       * Marque un noeud comme "utilisé" (vert)
       */
      markNodeAsUsed: (nodeId: string) => {
        const { usedConceptIds, nodes } = get();

        if (!usedConceptIds.includes(nodeId)) {
          set({
            usedConceptIds: [...usedConceptIds, nodeId],
            nodes: nodes.map((n) =>
              n.id === nodeId ? { ...n, role: 'used' as ConceptRole } : n
            ),
          });
        }
      },

      /**
       * Marque plusieurs noeuds comme "utilisés"
       */
      markNodesAsUsed: (nodeIds: string[]) => {
        const { usedConceptIds, nodes } = get();
        const newUsedIds = [...new Set([...usedConceptIds, ...nodeIds])];
        const nodeIdSet = new Set(nodeIds);

        set({
          usedConceptIds: newUsedIds,
          nodes: nodes.map((n) =>
            nodeIdSet.has(n.id) ? { ...n, role: 'used' as ConceptRole } : n
          ),
        });
      },

      /**
       * Toggle visibilité du graphe
       */
      toggleVisibility: () => {
        set((state) => ({ isVisible: !state.isVisible }));
      },

      /**
       * Set visibilité du graphe
       */
      setVisibility: (visible: boolean) => {
        set({ isVisible: visible });
      },

      /**
       * Configure l'auto-expansion
       */
      setAutoExpand: (enabled: boolean) => {
        set({ autoExpand: enabled });
      },

      /**
       * Reset complet du graphe
       */
      resetGraph: () => {
        set(initialState);
      },

      /**
       * Reset de la session (conserve config)
       */
      resetSession: () => {
        const { isVisible, autoExpand } = get();
        set({
          ...initialState,
          isVisible,
          autoExpand,
        });
      },
    }),
    {
      name: 'graph-store',
    }
  )
);

/**
 * Sélecteurs utilitaires
 */
export const graphSelectors = {
  /**
   * Récupère un noeud par ID
   */
  getNodeById: (state: GraphState, nodeId: string): GraphNode | undefined => {
    return state.nodes.find((n) => n.id === nodeId);
  },

  /**
   * Récupère les arêtes connectées à un noeud
   */
  getConnectedEdges: (state: GraphState, nodeId: string): GraphEdge[] => {
    return state.edges.filter(
      (e) =>
        (typeof e.source === 'string' ? e.source : e.source.id) === nodeId ||
        (typeof e.target === 'string' ? e.target : e.target.id) === nodeId
    );
  },

  /**
   * Récupère les noeuds voisins d'un noeud
   */
  getNeighborNodes: (state: GraphState, nodeId: string): GraphNode[] => {
    const connectedEdges = graphSelectors.getConnectedEdges(state, nodeId);
    const neighborIds = new Set<string>();

    connectedEdges.forEach((e) => {
      const sourceId = typeof e.source === 'string' ? e.source : e.source.id;
      const targetId = typeof e.target === 'string' ? e.target : e.target.id;

      if (sourceId === nodeId) {
        neighborIds.add(targetId);
      } else {
        neighborIds.add(sourceId);
      }
    });

    return state.nodes.filter((n) => neighborIds.has(n.id));
  },

  /**
   * Compte les noeuds par rôle
   */
  getNodeCountByRole: (state: GraphState): Record<string, number> => {
    const counts: Record<string, number> = {
      query: 0,
      used: 0,
      suggested: 0,
      context: 0,
    };

    state.nodes.forEach((n) => {
      counts[n.role] = (counts[n.role] || 0) + 1;
    });

    return counts;
  },

  /**
   * Vérifie si le graphe a des données
   */
  hasData: (state: GraphState): boolean => {
    return state.nodes.length > 0;
  },
};

export type { GraphState, GraphActions, GraphStore };
