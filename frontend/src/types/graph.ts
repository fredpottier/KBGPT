/**
 * Types pour le Knowledge Graph D3.js - Phase 3.5 Explainable Graph-RAG
 */

// Types de concepts (couleurs)
export type ConceptRole = 'query' | 'used' | 'suggested' | 'context';

// Types de relations sémantiques (pour raisonnement)
export type SemanticRelationType =
  | 'REQUIRES'
  | 'ENABLES'
  | 'PREVENTS'
  | 'CAUSES'
  | 'APPLIES_TO'
  | 'DEPENDS_ON'
  | 'PART_OF'
  | 'MITIGATES'
  | 'CONFLICTS_WITH'
  | 'DEFINES'
  | 'EXAMPLE_OF'
  | 'GOVERNED_BY';

// Types de relations navigation (corpus-level, pas pour raisonnement)
export type NavigationRelationType =
  | 'MENTIONED_IN'
  | 'HAS_SECTION'
  | 'CONTAINED_IN'
  | 'CO_OCCURS';

// Types de relations (union)
export type RelationType =
  | SemanticRelationType
  | NavigationRelationType
  | 'SUBTYPE_OF'
  | 'USES'
  | 'INTEGRATES_WITH'
  | 'EXTENDS'
  | 'VERSION_OF'
  | 'PRECEDES'
  | 'REPLACES'
  | 'DEPRECATES'
  | 'ALTERNATIVE_TO'
  | 'RELATED_TO';

// Couche du graphe (ADR: ADR_NAVIGATION_LAYER.md)
export type GraphLayer = 'semantic' | 'navigation';

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
  layer?: GraphLayer;   // Couche: semantic (raisonnement) ou navigation (corpus) - optionnel, déduit si absent
}

/**
 * Helper pour déterminer la couche d'une relation
 */
export function getRelationLayer(relationType: RelationType): GraphLayer {
  const navigationTypes: NavigationRelationType[] = [
    'MENTIONED_IN', 'HAS_SECTION', 'CONTAINED_IN', 'CO_OCCURS'
  ];
  return navigationTypes.includes(relationType as NavigationRelationType)
    ? 'navigation'
    : 'semantic';
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

// ============================================================================
// 🌊 PROOF GRAPH TYPES (Phase 3.5+ - PATCH-GRAPH-02)
// ============================================================================

/**
 * Rôle d'un noeud dans le Proof Graph
 */
export type ProofNodeRole = 'query' | 'used' | 'bridge' | 'context';

/**
 * Noeud du Proof Graph (enrichi avec depth pour layout hiérarchique)
 */
export interface ProofNode {
  id: string;
  name: string;
  type: string;
  role: ProofNodeRole;
  confidence: number;
  mentionCount: number;
  documentCount: number;
  depth: number;           // Distance depuis la question (BFS)
  isOnPath: boolean;       // Sur un chemin de preuve
}

/**
 * Evidence pour une arête (quote + source)
 */
export interface ProofEvidence {
  source_doc?: string;
  quote?: string;
  confidence?: number;
  slide_index?: number;
}

/**
 * Arête du Proof Graph (avec evidences)
 */
export interface ProofEdge {
  id: string;
  source: string;
  target: string;
  relationType: string;
  confidence: number;
  isUsed: boolean;
  isOnPath: boolean;
  evidenceCount: number;
  evidences: ProofEvidence[];
}

/**
 * Chemin de preuve query → used
 */
export interface ProofPath {
  pathId: string;
  fromConcept: string;
  toConcept: string;
  nodeIds: string[];
  edgeIds: string[];
  totalConfidence: number;
  length: number;
}

/**
 * Statistiques du Proof Graph
 */
export interface ProofGraphStats {
  total_nodes: number;
  total_edges: number;
  total_paths: number;
  query_count: number;
  used_count: number;
  bridge_count: number;
  context_count: number;
  max_depth: number;
}

/**
 * Proof Graph complet retourné par l'API
 */
export interface ProofGraph {
  nodes: ProofNode[];
  edges: ProofEdge[];
  paths: ProofPath[];
  rootId: string;
  queryConceptIds: string[];
  usedConceptIds: string[];
  stats: ProofGraphStats;
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
    navigation: '#9F7AEA', // Violet - navigation layer (corpus-level)
  },
} as const;

/**
 * Styles des arêtes
 *
 * ADR: ADR_NAVIGATION_LAYER.md
 * - Semantic layer: lignes pleines (pour raisonnement)
 * - Navigation layer: lignes pointillées (pour exploration corpus)
 */
export const EDGE_STYLES = {
  // Sémantique - utilisé dans le raisonnement
  used: {
    stroke: GRAPH_COLORS.edge.used,
    strokeWidth: 3,
    strokeDasharray: 'none',
  },
  // Sémantique - disponible
  available: {
    stroke: GRAPH_COLORS.edge.available,
    strokeWidth: 1.5,
    strokeDasharray: 'none',
  },
  // Sémantique - inféré
  inferred: {
    stroke: GRAPH_COLORS.edge.inferred,
    strokeWidth: 1.5,
    strokeDasharray: '5,5',
  },
  // Navigation - corpus-level (pointillés fins, violet)
  navigation: {
    stroke: GRAPH_COLORS.edge.navigation,
    strokeWidth: 1,
    strokeDasharray: '3,3',  // Pointillés fins pour distinguer
  },
  // Navigation - utilisé (si on veut highlighter)
  navigationUsed: {
    stroke: GRAPH_COLORS.edge.navigation,
    strokeWidth: 2,
    strokeDasharray: '3,3',
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
 *
 * Priorité:
 * 1. Navigation layer → style pointillé (navigation ou navigationUsed)
 * 2. Used → style plein épais
 * 3. Inferred → style pointillé léger
 * 4. Default → style plein fin
 */
export function getEdgeStyle(edge: GraphEdge) {
  // Déterminer le layer (explicite ou déduit du type de relation)
  const layer = edge.layer ?? getRelationLayer(edge.relationType);

  // Navigation layer: toujours pointillé
  if (layer === 'navigation') {
    return edge.isUsed ? EDGE_STYLES.navigationUsed : EDGE_STYLES.navigation;
  }

  // Semantic layer: style selon état
  if (edge.isUsed) return EDGE_STYLES.used;
  if (edge.isInferred) return EDGE_STYLES.inferred;
  return EDGE_STYLES.available;
}
