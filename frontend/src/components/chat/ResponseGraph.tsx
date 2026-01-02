'use client';

/**
 * OSMOS Phase 3.5 - Response Graph Component
 *
 * Graphe intégré dans chaque réponse du chat.
 * Affichage en accordéon avec option d'agrandissement.
 */

import { memo, useState, useRef, useEffect, useCallback } from 'react';
import {
  Box,
  Collapse,
  HStack,
  Text,
  IconButton,
  Badge,
  Tooltip,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalCloseButton,
  useDisclosure,
  VStack,
  Flex,
  Divider,
  Button,
  Icon,
} from '@chakra-ui/react';
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ExternalLinkIcon,
  CloseIcon,
  SearchIcon,
  InfoIcon,
  QuestionIcon,
} from '@chakra-ui/icons';
import * as d3 from 'd3';
import type { GraphData, GraphNode, GraphEdge, ProofGraph } from '@/types/graph';
import type { ExplorationIntelligence, ConceptExplanation, ExplorationSuggestion, SuggestedQuestion, ResearchAxis } from '@/types/api';
import { GRAPH_COLORS, getNodeColor, getEdgeStyle } from '@/types/graph';
import { getNodeRadius, getNodeBorderColor } from '@/lib/graph';
import ResearchAxesSection from './ResearchAxesSection';
import ProofGraphViewer from '../graph/ProofGraphViewer';

interface ResponseGraphProps {
  graphData: GraphData;
  proofGraph?: ProofGraph;  // 🌊 Phase 3.5+: Proof Graph prioritaire
  explorationIntelligence?: ExplorationIntelligence;
  onSearch?: (query: string) => void;
  defaultExpanded?: boolean;
}

interface MiniGraphProps {
  graphData: GraphData;
  width: number;
  height: number;
  showLabels?: boolean;
  onNodeClick?: (node: GraphNode) => void;
}

// Types D3 internes
interface D3Node extends GraphNode {
  x: number;
  y: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
}

interface D3Edge extends Omit<GraphEdge, 'source' | 'target'> {
  source: D3Node;
  target: D3Node;
}

/**
 * Mini visualisation D3 du graphe avec simulation force-directed
 */
function MiniGraph({
  graphData,
  width,
  height,
  showLabels = false,
  onNodeClick,
}: MiniGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simulationRef = useRef<d3.Simulation<D3Node, D3Edge> | null>(null);

  useEffect(() => {
    if (!svgRef.current || graphData.nodes.length === 0) {
      return;
    }

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const g = svg.append('g');

    // Zoom
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });
    svg.call(zoom);

    // Adapter les forces au nombre de noeuds
    const nodeCount = graphData.nodes.length;

    // En mode labels, on a besoin de plus d'espace
    const spacingFactor = showLabels ? 2 : 1;
    const chargeStrength = Math.min(-50, -400 / Math.sqrt(nodeCount)) * spacingFactor;
    const linkDistance = Math.max(80, 200 / Math.sqrt(nodeCount)) * spacingFactor;
    const collisionRadius = Math.max(30, 100 / Math.sqrt(nodeCount)) * spacingFactor;

    // Préparer les données avec dispersion initiale plus large
    const d3Nodes: D3Node[] = graphData.nodes.map((n, i) => {
      // Disposition initiale en spirale pour meilleure répartition
      const angle = (i / nodeCount) * 2 * Math.PI * 3;
      const radius = 30 + (i / nodeCount) * Math.min(width, height) * 0.35;
      return {
        ...n,
        x: width / 2 + Math.cos(angle) * radius,
        y: height / 2 + Math.sin(angle) * radius,
      };
    });

    const nodeMap = new Map(d3Nodes.map((n) => [n.id, n]));

    const d3Edges: D3Edge[] = graphData.edges
      .map((e) => {
        const sourceId = typeof e.source === 'string' ? e.source : e.source.id;
        const targetId = typeof e.target === 'string' ? e.target : e.target.id;
        const sourceNode = nodeMap.get(sourceId);
        const targetNode = nodeMap.get(targetId);
        if (!sourceNode || !targetNode) return null;
        return { ...e, source: sourceNode, target: targetNode };
      })
      .filter((e): e is D3Edge => e !== null);

    // Arêtes - style dynamique selon layer (semantic=plein, navigation=pointillé)
    const links = g
      .append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(d3Edges)
      .join('line')
      .attr('stroke', (d) => getEdgeStyle(d).stroke)
      .attr('stroke-width', (d) => getEdgeStyle(d).strokeWidth)
      .attr('stroke-dasharray', (d) => getEdgeStyle(d).strokeDasharray)
      .attr('opacity', 0.6);

    // Noeuds
    const nodeGroups = g
      .append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(d3Nodes)
      .join('g')
      .attr('class', 'node')
      .style('cursor', onNodeClick ? 'pointer' : 'grab');

    // Taille des cercles adaptée
    const baseRadius = showLabels
      ? Math.max(20, Math.min(35, 300 / Math.sqrt(nodeCount)))
      : Math.max(6, Math.min(12, 100 / Math.sqrt(nodeCount)));

    // Cercles
    nodeGroups
      .append('circle')
      .attr('r', (d) => {
        const r = getNodeRadius(d, baseRadius);
        return Math.min(r, baseRadius * 1.5);
      })
      .attr('fill', (d) => getNodeColor(d.role))
      .attr('stroke', (d) => getNodeBorderColor(d.type))
      .attr('stroke-width', showLabels ? 2 : 1.5)
      .attr('opacity', 0.9);

    // Labels dans les cercles (mode agrandi)
    if (showLabels) {
      nodeGroups
        .append('text')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'central')
        .attr('font-size', (d) => {
          const r = Math.min(getNodeRadius(d, baseRadius), baseRadius * 1.5);
          // Calculer la taille de police en fonction du rayon et de la longueur du texte
          const maxFontSize = r * 0.6;
          const charWidth = maxFontSize * 0.6;
          const maxChars = Math.floor((r * 1.8) / charWidth);
          return `${Math.max(8, Math.min(maxFontSize, 14))}px`;
        })
        .attr('fill', 'white')
        .attr('font-weight', '500')
        .attr('pointer-events', 'none')
        .text((d) => {
          const r = Math.min(getNodeRadius(d, baseRadius), baseRadius * 1.5);
          const maxChars = Math.floor(r / 5);
          return d.name.length > maxChars ? d.name.slice(0, maxChars - 1) + '…' : d.name;
        });
    }

    // Tooltip enrichi sur hover (toujours)
    nodeGroups
      .append('title')
      .text((d) => {
        const lines = [
          d.name,
          `─────────────────`,
          `Type: ${getTypeLabel(d.type)}`,
          `Rôle: ${d.role === 'query' ? 'Concept de la question' :
                  d.role === 'used' ? 'Utilisé dans la réponse' :
                  d.role === 'suggested' ? 'Concept suggéré' : 'Contexte'}`,
        ];
        if (d.confidence !== undefined) {
          lines.push(`Confiance: ${Math.round(d.confidence * 100)}%`);
        }
        if (d.mentionCount && d.mentionCount > 0) {
          lines.push(`Mentions: ${d.mentionCount}`);
        }
        if (d.documentCount && d.documentCount > 0) {
          lines.push(`Documents: ${d.documentCount}`);
        }
        lines.push(`\n💡 Cliquez pour plus de détails`);
        return lines.join('\n');
      });

    // Click handler
    if (onNodeClick) {
      nodeGroups.on('click', (event, d) => {
        event.stopPropagation();
        onNodeClick(d);
      });
    }

    // Simulation force-directed
    const simulation = d3
      .forceSimulation<D3Node>(d3Nodes)
      .force(
        'link',
        d3
          .forceLink<D3Node, D3Edge>(d3Edges)
          .id((d) => d.id)
          .distance(linkDistance)
          .strength(0.6)
      )
      .force('charge', d3.forceManyBody().strength(chargeStrength))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(collisionRadius))
      .force('x', d3.forceX(width / 2).strength(0.03))
      .force('y', d3.forceY(height / 2).strength(0.03))
      .alphaDecay(0.015)
      .on('tick', () => {
        links
          .attr('x1', (d) => d.source.x)
          .attr('y1', (d) => d.source.y)
          .attr('x2', (d) => d.target.x)
          .attr('y2', (d) => d.target.y);
        nodeGroups.attr('transform', (d) => `translate(${d.x},${d.y})`);
      });

    simulationRef.current = simulation;

    // Drag behavior (seulement si pas de click handler ou pour réorganiser)
    const drag = d3.drag<SVGGElement, D3Node>()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on('drag', (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeGroups.call(drag as any);

    // Zoom initial pour voir tout le graphe
    const initialScale = showLabels
      ? Math.min(0.8, 0.6 * Math.min(width, height) / (nodeCount * 15))
      : Math.min(1, 0.8 * Math.min(width, height) / (nodeCount * 10));

    svg.call(zoom.transform as any, d3.zoomIdentity
      .translate(width / 2, height / 2)
      .scale(Math.max(0.25, initialScale))
      .translate(-width / 2, -height / 2)
    );

    return () => {
      simulation.stop();
    };
  }, [graphData, width, height, showLabels, onNodeClick]);

  if (graphData.nodes.length === 0) {
    return (
      <Flex
        w="100%"
        h={height}
        align="center"
        justify="center"
        bg="gray.50"
        borderRadius="md"
      >
        <Text fontSize="xs" color="gray.400">
          Aucun concept
        </Text>
      </Flex>
    );
  }

  return (
    <Box position="relative" w="100%" h={height} bg="white" borderRadius="md" border="1px solid" borderColor="gray.200">
      <svg
        ref={svgRef}
        width="100%"
        height={height}
        style={{ display: 'block' }}
      />
    </Box>
  );
}

/**
 * Helper pour obtenir le label français d'un type de relation
 */
function getRelationLabel(relationType: string): string {
  const labels: Record<string, string> = {
    PART_OF: 'Fait partie de',
    SUBTYPE_OF: 'Sous-type de',
    REQUIRES: 'Nécessite',
    USES: 'Utilise',
    INTEGRATES_WITH: 'S\'intègre avec',
    EXTENDS: 'Étend',
    ENABLES: 'Permet',
    VERSION_OF: 'Version de',
    PRECEDES: 'Précède',
    REPLACES: 'Remplace',
    DEPRECATES: 'Déprécie',
    ALTERNATIVE_TO: 'Alternative à',
    RELATED_TO: 'Lié à',
  };
  return labels[relationType] || relationType;
}

/**
 * Helper pour obtenir le label français d'un type de concept
 */
function getTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    PRODUCT: 'Produit',
    SERVICE: 'Service',
    TECHNOLOGY: 'Technologie',
    PRACTICE: 'Pratique',
    ORGANIZATION: 'Organisation',
    PERSON: 'Personne',
    LOCATION: 'Lieu',
    EVENT: 'Événement',
    CONCEPT: 'Concept',
    UNKNOWN: 'Inconnu',
  };
  return labels[type] || type;
}

/**
 * Panneau d'information enrichi sur un concept sélectionné
 * Inclut: explications de raisonnement, actions contextuelles, relations
 */
function ConceptInfoPanel({
  node,
  edges,
  nodes,
  conceptExplanation,
  onClose,
  onSearch,
}: {
  node: GraphNode;
  edges: GraphEdge[];
  nodes: GraphNode[];
  conceptExplanation?: ConceptExplanation;
  onClose: () => void;
  onSearch?: (query: string) => void;
}) {
  const getRoleLabel = (role: string) => {
    switch (role) {
      case 'query': return 'Concept de la question';
      case 'used': return 'Utilisé dans la réponse';
      case 'suggested': return 'Concept suggéré';
      case 'context': return 'Contexte';
      default: return role;
    }
  };

  const getRoleColor = (role: string) => {
    switch (role) {
      case 'query': return 'orange';
      case 'used': return 'green';
      case 'suggested': return 'blue';
      case 'context': return 'gray';
      default: return 'gray';
    }
  };

  // Trouver les relations entrantes et sortantes du concept
  const nodeMap = new Map(nodes.map(n => [n.id, n]));

  const outgoingRelations = edges.filter(e => {
    const sourceId = typeof e.source === 'string' ? e.source : e.source.id;
    return sourceId === node.id;
  }).map(e => {
    const targetId = typeof e.target === 'string' ? e.target : e.target.id;
    const targetNode = nodeMap.get(targetId);
    return { edge: e, targetNode };
  }).filter(r => r.targetNode);

  const incomingRelations = edges.filter(e => {
    const targetId = typeof e.target === 'string' ? e.target : e.target.id;
    return targetId === node.id;
  }).map(e => {
    const sourceId = typeof e.source === 'string' ? e.source : e.source.id;
    const sourceNode = nodeMap.get(sourceId);
    return { edge: e, sourceNode };
  }).filter(r => r.sourceNode);

  return (
    <Box
      bg="white"
      p={4}
      borderRadius="md"
      border="1px solid"
      borderColor="gray.200"
      shadow="md"
      maxW="350px"
      maxH="600px"
      overflowY="auto"
    >
      <Flex justify="space-between" align="flex-start" mb={2}>
        <Text fontWeight="bold" fontSize="md" color="gray.800">
          {node.name}
        </Text>
        <IconButton
          aria-label="Fermer"
          icon={<CloseIcon />}
          size="xs"
          variant="ghost"
          onClick={onClose}
        />
      </Flex>
      <Divider mb={3} />

      {/* 💡 Option C: Explication du raisonnement (si disponible) */}
      {conceptExplanation && (
        <>
          <Box bg="blue.50" p={3} borderRadius="md" mb={3} border="1px solid" borderColor="blue.100">
            <HStack spacing={2} mb={2}>
              <InfoIcon color="blue.500" boxSize={3} />
              <Text fontSize="xs" fontWeight="semibold" color="blue.700">
                Pourquoi ce concept ?
              </Text>
            </HStack>
            <Text fontSize="sm" color="gray.700" lineHeight="1.5">
              {conceptExplanation.why_used}
            </Text>
            {conceptExplanation.role_in_answer && (
              <Badge mt={2} colorScheme="blue" variant="subtle" fontSize="xs">
                Rôle: {conceptExplanation.role_in_answer}
              </Badge>
            )}
          </Box>
        </>
      )}

      {/* 🔘 Option A: Actions contextuelles */}
      {onSearch && (
        <>
          <VStack align="stretch" spacing={2} mb={3}>
            <Button
              size="sm"
              leftIcon={<SearchIcon />}
              colorScheme="teal"
              variant="outline"
              onClick={() => onSearch(node.name)}
            >
              Rechercher "{node.name}"
            </Button>
            {node.documentCount && node.documentCount > 0 && (
              <Button
                size="sm"
                leftIcon={<ExternalLinkIcon />}
                colorScheme="gray"
                variant="outline"
                onClick={() => onSearch(`documents contenant ${node.name}`)}
              >
                Voir les {node.documentCount} document{node.documentCount > 1 ? 's' : ''}
              </Button>
            )}
          </VStack>
          <Divider mb={3} />
        </>
      )}

      {/* Informations de base */}
      <VStack align="stretch" spacing={2}>
        <HStack>
          <Text fontSize="sm" color="gray.500" w="80px">Type:</Text>
          <Badge colorScheme="blue" variant="subtle">{getTypeLabel(node.type)}</Badge>
        </HStack>
        <HStack>
          <Text fontSize="sm" color="gray.500" w="80px">Rôle:</Text>
          <Badge colorScheme={getRoleColor(node.role)} variant="outline">
            {getRoleLabel(node.role)}
          </Badge>
        </HStack>
        {node.confidence !== undefined && (
          <HStack>
            <Text fontSize="sm" color="gray.500" w="80px">Confiance:</Text>
            <Text fontSize="sm" fontWeight="medium">{Math.round(node.confidence * 100)}%</Text>
          </HStack>
        )}
        {node.mentionCount !== undefined && node.mentionCount > 0 && (
          <HStack>
            <Text fontSize="sm" color="gray.500" w="80px">Mentions:</Text>
            <Text fontSize="sm">{node.mentionCount} occurrence{node.mentionCount > 1 ? 's' : ''}</Text>
          </HStack>
        )}
        {node.documentCount !== undefined && node.documentCount > 0 && (
          <HStack>
            <Text fontSize="sm" color="gray.500" w="80px">Documents:</Text>
            <Text fontSize="sm">{node.documentCount} document{node.documentCount > 1 ? 's' : ''}</Text>
          </HStack>
        )}
      </VStack>

      {/* Relations sortantes */}
      {outgoingRelations.length > 0 && (
        <>
          <Divider my={3} />
          <Text fontSize="xs" fontWeight="semibold" color="gray.600" mb={2}>
            🔗 Relations sortantes ({outgoingRelations.length})
          </Text>
          <VStack align="stretch" spacing={1}>
            {outgoingRelations.slice(0, 5).map(({ edge, targetNode }, idx) => (
              <Box key={idx} fontSize="xs" bg="gray.50" p={2} borderRadius="sm">
                <HStack spacing={1} flexWrap="wrap">
                  <Badge size="sm" colorScheme={edge.isUsed ? 'green' : 'gray'} variant="subtle">
                    {getRelationLabel(edge.relationType)}
                  </Badge>
                  <Text color="gray.400">→</Text>
                  <Text fontWeight="medium" color="gray.700">{targetNode?.name}</Text>
                </HStack>
                {edge.isInferred && (
                  <Text fontSize="xs" color="orange.500" mt={1}>⚡ Relation inférée</Text>
                )}
                {edge.confidence < 1 && (
                  <Text fontSize="xs" color="gray.400">
                    Confiance: {Math.round(edge.confidence * 100)}%
                  </Text>
                )}
              </Box>
            ))}
            {outgoingRelations.length > 5 && (
              <Text fontSize="xs" color="gray.400" fontStyle="italic">
                +{outgoingRelations.length - 5} autres relations...
              </Text>
            )}
          </VStack>
        </>
      )}

      {/* Relations entrantes */}
      {incomingRelations.length > 0 && (
        <>
          <Divider my={3} />
          <Text fontSize="xs" fontWeight="semibold" color="gray.600" mb={2}>
            🔙 Relations entrantes ({incomingRelations.length})
          </Text>
          <VStack align="stretch" spacing={1}>
            {incomingRelations.slice(0, 5).map(({ edge, sourceNode }, idx) => (
              <Box key={idx} fontSize="xs" bg="gray.50" p={2} borderRadius="sm">
                <HStack spacing={1} flexWrap="wrap">
                  <Text fontWeight="medium" color="gray.700">{sourceNode?.name}</Text>
                  <Text color="gray.400">→</Text>
                  <Badge size="sm" colorScheme={edge.isUsed ? 'green' : 'gray'} variant="subtle">
                    {getRelationLabel(edge.relationType)}
                  </Badge>
                </HStack>
                {edge.isInferred && (
                  <Text fontSize="xs" color="orange.500" mt={1}>⚡ Relation inférée</Text>
                )}
              </Box>
            ))}
            {incomingRelations.length > 5 && (
              <Text fontSize="xs" color="gray.400" fontStyle="italic">
                +{incomingRelations.length - 5} autres relations...
              </Text>
            )}
          </VStack>
        </>
      )}

      {/* Pas de relations */}
      {outgoingRelations.length === 0 && incomingRelations.length === 0 && (
        <>
          <Divider my={3} />
          <Text fontSize="xs" color="gray.400" fontStyle="italic">
            Aucune relation directe dans ce graphe
          </Text>
        </>
      )}
    </Box>
  );
}

/**
 * Section "Pour aller plus loin" avec suggestions et questions
 * Version ultra-compacte
 */
function ExplorationSection({
  explorationIntelligence,
  onSearch,
}: {
  explorationIntelligence: ExplorationIntelligence;
  onSearch?: (query: string) => void;
}) {
  const { exploration_suggestions, suggested_questions } = explorationIntelligence;

  if (exploration_suggestions.length === 0 && suggested_questions.length === 0) {
    return null;
  }

  return (
    <Box mt={1} p={1.5} bg="purple.50" borderRadius="sm" border="1px solid" borderColor="purple.100">
      <HStack spacing={1} mb={1}>
        <QuestionIcon color="purple.400" boxSize={2.5} />
        <Text fontSize="2xs" fontWeight="medium" color="purple.600">
          Pour aller plus loin
        </Text>
      </HStack>

      {/* Suggestions d'exploration - version ultra-compacte */}
      {exploration_suggestions.length > 0 && (
        <VStack align="stretch" spacing={0.5} mb={1}>
          {exploration_suggestions.slice(0, 2).map((suggestion, idx) => (
            <HStack
              key={idx}
              p={1}
              bg="white"
              borderRadius="sm"
              _hover={{ bg: 'purple.100', cursor: onSearch ? 'pointer' : 'default' }}
              onClick={() => onSearch && onSearch(suggestion.action_value)}
            >
              <Text fontSize="2xs" color="gray.700" noOfLines={1} flex={1}>
                {suggestion.title}
              </Text>
            </HStack>
          ))}
        </VStack>
      )}

      {/* Questions suggérées - version ultra-compacte */}
      {suggested_questions.length > 0 && (
        <VStack align="stretch" spacing={0.5}>
          {suggested_questions.slice(0, 2).map((q, idx) => (
            <HStack
              key={idx}
              p={1}
              bg="white"
              borderRadius="sm"
              _hover={{ bg: 'purple.100', cursor: onSearch ? 'pointer' : 'default' }}
              onClick={() => onSearch && onSearch(q.question)}
            >
              <Text fontSize="2xs" color="gray.600" noOfLines={1} flex={1}>
                {q.question}
              </Text>
            </HStack>
          ))}
        </VStack>
      )}
    </Box>
  );
}

/**
 * Composant principal - Graphe dépliable pour une réponse
 */
function ResponseGraphComponent({
  graphData,
  proofGraph,
  explorationIntelligence,
  onSearch,
  defaultExpanded = false,
}: ResponseGraphProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const { isOpen: isModalOpen, onOpen: openModal, onClose: closeModal } = useDisclosure();

  const nodeCount = graphData.nodes.length;
  const edgeCount = graphData.edges.length;
  const queryCount = graphData.queryConceptIds.length;
  const usedCount = graphData.usedConceptIds.length;

  // 🌊 Phase 3.5+: Utiliser ProofGraph si disponible (prioritaire)
  const useProofGraph = proofGraph && proofGraph.nodes.length > 0;

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode(node);
  }, []);

  const handleCloseInfo = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // Récupérer l'explication pour le concept sélectionné
  const getConceptExplanation = useCallback((nodeName: string): ConceptExplanation | undefined => {
    if (!explorationIntelligence?.concept_explanations) return undefined;
    return explorationIntelligence.concept_explanations[nodeName];
  }, [explorationIntelligence]);

  // Si pas de nodes ET pas d'exploration intelligence, ne rien afficher
  const hasExplorationContent = explorationIntelligence && (
    (explorationIntelligence.research_axes && explorationIntelligence.research_axes.length > 0) ||
    explorationIntelligence.exploration_suggestions.length > 0 ||
    explorationIntelligence.suggested_questions.length > 0
  );

  if (nodeCount === 0 && !hasExplorationContent) {
    return null;
  }

  return (
    <Box mt={1} borderTop="1px solid" borderColor="gray.100" pt={1}>
      {/* 🌊 Phase 3.5+: ProofGraphViewer prioritaire si disponible */}
      {useProofGraph ? (
        <ProofGraphViewer
          proofGraph={proofGraph}
          onSearch={onSearch}
          defaultExpanded={defaultExpanded}
        />
      ) : (
        <>
          {/* Legacy: Header compact - seulement si graphe disponible */}
          {nodeCount > 0 && (
            <HStack
              spacing={1}
              cursor="pointer"
              onClick={() => setIsExpanded(!isExpanded)}
              _hover={{ bg: 'gray.50' }}
              px={1.5}
              py={0.5}
              borderRadius="sm"
              transition="background 0.2s"
            >
              <Icon
                as={isExpanded ? ChevronUpIcon : ChevronDownIcon}
                boxSize={3}
                color="gray.400"
              />
              <HStack spacing={0.5}>
                <Box w={1.5} h={1.5} borderRadius="full" bg="teal.400" />
                <Text fontSize="2xs" color="gray.500" fontWeight="medium">
                  Graph
                </Text>
              </HStack>
              <Badge colorScheme="gray" fontSize="2xs" variant="subtle" px={1}>
                {nodeCount}
              </Badge>
              <Box flex="1" />
              {isExpanded && (
                <Tooltip label="Agrandir" fontSize="xs">
                  <IconButton
                    aria-label="Agrandir le graphe"
                    icon={<ExternalLinkIcon boxSize={2.5} />}
                    size="xs"
                    variant="ghost"
                    minW={4}
                    h={4}
                    onClick={(e) => {
                      e.stopPropagation();
                      openModal();
                    }}
                  />
                </Tooltip>
              )}
            </HStack>
          )}

          {/* Legacy: Contenu dépliable du graphe - seulement si nodes */}
          {nodeCount > 0 && (
            <Collapse in={isExpanded}>
              <Box mt={1} p={1.5} bg="gray.50" borderRadius="sm">
                <Flex gap={3}>
                  {/* Graphe - taille minimale pour interface pro */}
                  <Box flex="1">
                    <MiniGraph
                      graphData={graphData}
                      width={480}
                      height={200}
                      onNodeClick={handleNodeClick}
                    />
                  </Box>
                  {/* Panneau d'info concept sélectionné */}
                  {selectedNode && (
                    <ConceptInfoPanel
                      node={selectedNode}
                      edges={graphData.edges}
                      nodes={graphData.nodes}
                      conceptExplanation={getConceptExplanation(selectedNode.name)}
                      onClose={handleCloseInfo}
                      onSearch={onSearch}
                    />
                  )}
                </Flex>

                {/* Légende ultra-compacte */}
                <HStack mt={1} spacing={2} fontSize="2xs" color="gray.400" justify="center">
                  <HStack spacing={0.5}>
                    <Box w={1.5} h={1.5} borderRadius="full" bg={GRAPH_COLORS.query} />
                    <Text>Query</Text>
                  </HStack>
                  <HStack spacing={0.5}>
                    <Box w={1.5} h={1.5} borderRadius="full" bg={GRAPH_COLORS.used} />
                    <Text>Utilisé</Text>
                  </HStack>
                  <HStack spacing={0.5}>
                    <Box w={1.5} h={1.5} borderRadius="full" bg={GRAPH_COLORS.suggested} />
                    <Text>Suggéré</Text>
                  </HStack>
                  <HStack spacing={0.5}>
                    <Box w={1.5} h={1.5} borderRadius="full" bg={GRAPH_COLORS.context} />
                    <Text>Ctx</Text>
                  </HStack>
                </HStack>
              </Box>
            </Collapse>
          )}
        </>
      )}

      {/* Section Axes de recherche - priorité sur l'ancienne ExplorationSection */}
      {explorationIntelligence?.research_axes && explorationIntelligence.research_axes.length > 0 ? (
        <Box mt={1}>
          <ResearchAxesSection
            axes={explorationIntelligence.research_axes}
            onSearch={onSearch}
          />
        </Box>
      ) : (
        /* 💡 Fallback: Section "Pour aller plus loin" legacy */
        explorationIntelligence && (
          <ExplorationSection
            explorationIntelligence={explorationIntelligence}
            onSearch={onSearch}
          />
        )
      )}

      {/* Modal agrandi - seulement si graphe disponible */}
      {nodeCount > 0 && (
        <Modal isOpen={isModalOpen} onClose={closeModal} size="6xl">
          <ModalOverlay />
          <ModalContent maxW="95vw">
            <ModalHeader>
              <HStack>
                <Text>Knowledge Graph</Text>
                <Badge colorScheme="teal">{nodeCount} concepts</Badge>
                <Badge colorScheme="gray">{edgeCount} relations</Badge>
              </HStack>
            </ModalHeader>
            <ModalCloseButton />
            <ModalBody pb={6}>
              <Flex gap={4}>
                {/* Graphe avec labels */}
                <Box
                  flex="1"
                  h="600px"
                  border="1px solid"
                  borderColor="gray.200"
                  borderRadius="md"
                  overflow="hidden"
                >
                  <MiniGraph
                    graphData={graphData}
                    width={1000}
                    height={600}
                    showLabels={true}
                    onNodeClick={handleNodeClick}
                  />
                </Box>
                {/* Panneau d'info à droite */}
                {selectedNode && (
                  <Box w="320px" flexShrink={0}>
                    <ConceptInfoPanel
                      node={selectedNode}
                      edges={graphData.edges}
                      nodes={graphData.nodes}
                      conceptExplanation={getConceptExplanation(selectedNode.name)}
                      onClose={handleCloseInfo}
                      onSearch={onSearch}
                    />
                  </Box>
                )}
              </Flex>
              {/* Légende */}
              <HStack mt={4} spacing={4} fontSize="sm" color="gray.600" justify="center">
                <HStack spacing={1}>
                  <Box w={3} h={3} borderRadius="full" bg={GRAPH_COLORS.query} />
                  <Text>Question ({queryCount})</Text>
                </HStack>
                <HStack spacing={1}>
                  <Box w={3} h={3} borderRadius="full" bg={GRAPH_COLORS.used} />
                  <Text>Utilisé ({usedCount})</Text>
                </HStack>
                <HStack spacing={1}>
                  <Box w={3} h={3} borderRadius="full" bg={GRAPH_COLORS.suggested} />
                  <Text>Suggéré ({graphData.suggestedConceptIds.length})</Text>
                </HStack>
                <HStack spacing={1}>
                  <Box w={3} h={3} borderRadius="full" bg={GRAPH_COLORS.context} />
                  <Text>Contexte</Text>
                </HStack>
              </HStack>
              <Text mt={2} fontSize="xs" color="gray.400" textAlign="center">
                Cliquez sur un concept pour voir ses détails • Utilisez la molette pour zoomer • Glissez pour déplacer
              </Text>
            </ModalBody>
          </ModalContent>
        </Modal>
      )}
    </Box>
  );
}

export const ResponseGraph = memo(ResponseGraphComponent);
export default ResponseGraph;
