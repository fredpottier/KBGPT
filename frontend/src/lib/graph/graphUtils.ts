/**
 * OSMOS Phase 3.5 - Utilitaires Graph D3.js
 *
 * Fonctions utilitaires pour la manipulation et transformation des données de graphe.
 */

import type { GraphNode, GraphEdge, GraphData, ConceptRole, ConceptType } from '@/types/graph';
import { GRAPH_COLORS, EDGE_STYLES } from '@/types/graph';

/**
 * Calcule la taille d'un noeud basée sur son importance
 */
export function getNodeRadius(node: GraphNode, baseRadius: number = 20): number {
  // Facteur basé sur le rôle
  const roleFactors: Record<ConceptRole, number> = {
    query: 1.3,
    used: 1.2,
    suggested: 1.0,
    context: 0.8,
  };

  // Facteur basé sur le nombre de mentions (log scale)
  const mentionFactor = Math.log10(Math.max(node.mentionCount, 1) + 1) * 0.3 + 1;

  // Facteur de confiance
  const confidenceFactor = 0.7 + node.confidence * 0.3;

  return baseRadius * (roleFactors[node.role] || 1) * mentionFactor * confidenceFactor;
}

/**
 * Calcule la couleur d'un noeud basée sur son rôle
 */
export function getNodeColor(role: ConceptRole): string {
  return GRAPH_COLORS[role] || GRAPH_COLORS.context;
}

/**
 * Calcule la couleur de bordure d'un noeud basée sur son type
 */
export function getNodeBorderColor(type: ConceptType): string {
  const typeColors: Record<ConceptType, string> = {
    PRODUCT: '#3182CE',    // blue.500
    SERVICE: '#38A169',    // green.500
    TECHNOLOGY: '#805AD5', // purple.500
    PRACTICE: '#DD6B20',   // orange.500
    ORGANIZATION: '#00B5D8', // cyan.500
    PERSON: '#D53F8C',     // pink.500
    LOCATION: '#D69E2E',   // yellow.500
    EVENT: '#E53E3E',      // red.500
    CONCEPT: '#718096',    // gray.500
    UNKNOWN: '#A0AEC0',    // gray.400
  };

  return typeColors[type] || typeColors.UNKNOWN;
}

/**
 * Calcule le style d'une arête
 */
export function getEdgeStyle(edge: GraphEdge): typeof EDGE_STYLES.used {
  if (edge.isUsed) return EDGE_STYLES.used;
  if (edge.isInferred) return EDGE_STYLES.inferred;
  return EDGE_STYLES.available;
}

/**
 * Calcule la force d'attraction entre deux noeuds connectés
 */
export function getLinkStrength(edge: GraphEdge): number {
  // Arêtes utilisées = plus fortes
  if (edge.isUsed) return 0.8;
  // Arêtes inférées = plus faibles
  if (edge.isInferred) return 0.2;
  // Normal
  return 0.4 * edge.confidence;
}

/**
 * Trouve les noeuds connectés à un noeud donné
 */
export function getConnectedNodes(
  nodeId: string,
  nodes: GraphNode[],
  edges: GraphEdge[]
): GraphNode[] {
  const connectedIds = new Set<string>();

  edges.forEach((edge) => {
    const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id;
    const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id;

    if (sourceId === nodeId) {
      connectedIds.add(targetId);
    } else if (targetId === nodeId) {
      connectedIds.add(sourceId);
    }
  });

  return nodes.filter((n) => connectedIds.has(n.id));
}

/**
 * Filtre les noeuds par rôle
 */
export function filterNodesByRole(
  nodes: GraphNode[],
  roles: ConceptRole[]
): GraphNode[] {
  const roleSet = new Set(roles);
  return nodes.filter((n) => roleSet.has(n.role));
}

/**
 * Calcule les statistiques du graphe
 */
export function getGraphStats(data: GraphData): {
  nodeCount: number;
  edgeCount: number;
  queryCount: number;
  usedCount: number;
  suggestedCount: number;
  avgConfidence: number;
} {
  const avgConfidence =
    data.nodes.length > 0
      ? data.nodes.reduce((sum, n) => sum + n.confidence, 0) / data.nodes.length
      : 0;

  return {
    nodeCount: data.nodes.length,
    edgeCount: data.edges.length,
    queryCount: data.queryConceptIds.length,
    usedCount: data.usedConceptIds.length,
    suggestedCount: data.suggestedConceptIds.length,
    avgConfidence: Math.round(avgConfidence * 100) / 100,
  };
}

/**
 * Crée un sous-graphe centré sur un noeud
 */
export function createSubgraph(
  centerNodeId: string,
  nodes: GraphNode[],
  edges: GraphEdge[],
  depth: number = 1
): GraphData {
  const includedNodeIds = new Set<string>([centerNodeId]);
  let frontier = new Set<string>([centerNodeId]);

  // BFS pour trouver les noeuds à distance <= depth
  for (let d = 0; d < depth; d++) {
    const nextFrontier = new Set<string>();

    edges.forEach((edge) => {
      const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id;
      const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id;

      if (frontier.has(sourceId) && !includedNodeIds.has(targetId)) {
        nextFrontier.add(targetId);
        includedNodeIds.add(targetId);
      }
      if (frontier.has(targetId) && !includedNodeIds.has(sourceId)) {
        nextFrontier.add(sourceId);
        includedNodeIds.add(sourceId);
      }
    });

    frontier = nextFrontier;
  }

  const subNodes = nodes.filter((n) => includedNodeIds.has(n.id));
  const subEdges = edges.filter((e) => {
    const sourceId = typeof e.source === 'string' ? e.source : e.source.id;
    const targetId = typeof e.target === 'string' ? e.target : e.target.id;
    return includedNodeIds.has(sourceId) && includedNodeIds.has(targetId);
  });

  return {
    nodes: subNodes,
    edges: subEdges,
    queryConceptIds: subNodes.filter((n) => n.role === 'query').map((n) => n.id),
    usedConceptIds: subNodes.filter((n) => n.role === 'used').map((n) => n.id),
    suggestedConceptIds: subNodes.filter((n) => n.role === 'suggested').map((n) => n.id),
  };
}

/**
 * Trie les noeuds par importance (pour le rendu)
 */
export function sortNodesByImportance(nodes: GraphNode[]): GraphNode[] {
  const roleOrder: Record<ConceptRole, number> = {
    query: 0,
    used: 1,
    suggested: 2,
    context: 3,
  };

  return [...nodes].sort((a, b) => {
    // D'abord par rôle
    const roleCompare = roleOrder[a.role] - roleOrder[b.role];
    if (roleCompare !== 0) return roleCompare;

    // Puis par confiance
    const confCompare = b.confidence - a.confidence;
    if (confCompare !== 0) return confCompare;

    // Enfin par nombre de mentions
    return b.mentionCount - a.mentionCount;
  });
}

/**
 * Génère un ID unique pour un élément
 */
export function generateId(prefix: string = 'node'): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Valide les données du graphe
 */
export function validateGraphData(data: unknown): data is GraphData {
  if (!data || typeof data !== 'object') return false;

  const d = data as Record<string, unknown>;

  return (
    Array.isArray(d.nodes) &&
    Array.isArray(d.edges) &&
    Array.isArray(d.queryConceptIds) &&
    Array.isArray(d.usedConceptIds) &&
    Array.isArray(d.suggestedConceptIds)
  );
}

/**
 * Transforme les données brutes de l'API en GraphData typé
 */
export function parseGraphData(raw: unknown): GraphData | null {
  if (!validateGraphData(raw)) {
    console.warn('[Graph] Invalid graph data received:', raw);
    return null;
  }

  return {
    nodes: raw.nodes.map((n: Record<string, unknown>) => ({
      id: String(n.id || ''),
      name: String(n.name || ''),
      type: String(n.type || 'UNKNOWN') as ConceptType,
      role: String(n.role || 'context') as ConceptRole,
      confidence: Number(n.confidence || 0.5),
      mentionCount: Number(n.mentionCount || 1),
      documentCount: Number(n.documentCount || 0),
    })),
    edges: raw.edges.map((e: Record<string, unknown>) => ({
      id: String(e.id || generateId('edge')),
      source: e.source as string | GraphNode,
      target: e.target as string | GraphNode,
      relationType: String(e.relationType || 'RELATED_TO'),
      confidence: Number(e.confidence || 0.5),
      isUsed: Boolean(e.isUsed),
      isInferred: Boolean(e.isInferred),
    })),
    queryConceptIds: raw.queryConceptIds.map(String),
    usedConceptIds: raw.usedConceptIds.map(String),
    suggestedConceptIds: raw.suggestedConceptIds.map(String),
  };
}
