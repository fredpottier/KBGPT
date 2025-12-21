/**
 * Types pour le Knowledge Graph D3.js - Phase 3.5 Explainable Graph-RAG
 */

// Types de concepts (couleurs)
export type ConceptRole = 'query' | 'used' | 'suggested' | 'context';

// Types de relations
export type RelationType =
  | 'PART_OF'
  | 'SUBTYPE_OF'
  | 'REQUIRES'
  | 'USES'
  | 'INTEGRATES_WITH'
  | 'EXTENDS'
  | 'ENABLES'
  | 'VERSION_OF'
  | 'PRECEDES'
  | 'REPLACES'
  | 'DEPRECATES'
  | 'ALTERNATIVE_TO'
  | 'RELATED_TO';

// Types de concepts (ontologie)
export type ConceptType =
  | 'PRODUCT'
  | 'SERVICE'
  | 'TECHNOLOGY'
  | 'PRACTICE'
  | 'ORGANIZATION'
  | 'PERSON'
  | 'LOCATION'
  | 'EVENT'
  | 'CONCEPT'
  | 'UNKNOWN';

/**
 * Noeud du graphe (concept)
 */
export interface GraphNode {
  id: string;
  name: string;
  type: ConceptType;
  role: ConceptRole;
  confidence: number;
  mentionCount: number;
  documentCount?: number;
  // Positions calculées par D3
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
}

/**
 * Arête du graphe (relation)
 */
export interface GraphEdge {
  id: string;
  source: string | GraphNode;
  target: string | GraphNode;
  relationType: RelationType;
  confidence: number;
  isUsed: boolean;      // Relation traversée dans le raisonnement
  isInferred: boolean;  // Relation inférée vs explicite
}

/**
 * Données du graphe complet retournées par l'API
 */
export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  queryConceptIds: string[];
  usedConceptIds: string[];
  suggestedConceptIds: string[];
}

/**
 * Contexte du graphe (enrichissement KG)
 */
export interface GraphContext {
  queryConceptIds: string[];
  relatedConcepts: RelatedConcept[];
  transitiveRelations: TransitiveRelation[];
  thematicCluster?: ThematicCluster;
  bridgeConcepts: string[];
  enrichmentLevel: 'none' | 'light' | 'standard' | 'deep';
  processingTimeMs: number;
}

export interface RelatedConcept {
  concept: string;
  relationshipType: RelationType;
  confidence: number;
  mentionCount?: number;
}

export interface TransitiveRelation {
  path: string[];
  concepts: string[];
  relationTypes: RelationType[];
}

export interface ThematicCluster {
  clusterId: string;
  name: string;
  concepts: string[];
}

/**
 * Props pour le composant KnowledgeGraph
 */
export interface KnowledgeGraphProps {
  // Données
  nodes: GraphNode[];
  edges: GraphEdge[];

  // Highlighting
  queryConceptIds: string[];
  usedConceptIds: string[];
  suggestedConceptIds: string[];

  // Interactions
  onNodeClick?: (node: GraphNode) => void;
  onNodeHover?: (node: GraphNode | null, event?: MouseEvent) => void;
  onEdgeClick?: (edge: GraphEdge) => void;

  // Configuration
  width?: number;
  height?: number;
  showLegend?: boolean;
  enableZoom?: boolean;
  enablePan?: boolean;
  maxNodes?: number;
}

/**
 * État du graphe (pour Zustand store)
 */
export interface GraphState {
  // Données
  nodes: GraphNode[];
  edges: GraphEdge[];

  // Highlighting
  queryConceptIds: string[];
  usedConceptIds: string[];
  suggestedConceptIds: string[];

  // Interactions
  selectedNodeId: string | null;
  hoveredNodeId: string | null;

  // Actions
  setGraphData: (data: GraphData) => void;
  selectNode: (nodeId: string | null) => void;
  hoverNode: (nodeId: string | null) => void;
  resetGraph: () => void;
}

/**
 * Couleurs du graphe
 */
export const GRAPH_COLORS = {
  query: '#F6AD55',      // Orange - concepts de la question
  used: '#48BB78',       // Vert - concepts utilisés dans la réponse
  suggested: '#4299E1',  // Bleu - concepts à explorer
  context: '#A0AEC0',    // Gris - contexte
  conflict: '#F56565',   // Rouge - conflits/alertes
  edge: {
    used: '#48BB78',
    available: '#CBD5E0',
    inferred: '#A0AEC0',
  },
} as const;

/**
 * Styles des arêtes
 */
export const EDGE_STYLES = {
  used: {
    stroke: GRAPH_COLORS.edge.used,
    strokeWidth: 3,
    strokeDasharray: 'none',
  },
  available: {
    stroke: GRAPH_COLORS.edge.available,
    strokeWidth: 1.5,
    strokeDasharray: 'none',
  },
  inferred: {
    stroke: GRAPH_COLORS.edge.inferred,
    strokeWidth: 1.5,
    strokeDasharray: '5,5',
  },
} as const;

/**
 * Helper pour obtenir la couleur d'un noeud selon son rôle
 */
export function getNodeColor(role: ConceptRole): string {
  return GRAPH_COLORS[role] || GRAPH_COLORS.context;
}

/**
 * Helper pour obtenir le style d'une arête
 */
export function getEdgeStyle(edge: GraphEdge) {
  if (edge.isUsed) return EDGE_STYLES.used;
  if (edge.isInferred) return EDGE_STYLES.inferred;
  return EDGE_STYLES.available;
}
