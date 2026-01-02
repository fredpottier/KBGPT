'use client';

/**
 * 🌊 OSMOSE Phase 3.5+ - Proof Graph Viewer
 *
 * Visualisation du Proof Graph avec:
 * - Layout hiérarchique (basé sur depth BFS)
 * - Labels lisibles (nom complet ou abrégé intelligent)
 * - Evidence Panel (quotes + sources pour chaque arête)
 * - Légende interactive
 *
 * PATCH-GRAPH-02: Evidence Panel frontend
 */

import { memo, useState, useRef, useEffect, useCallback } from 'react';
import {
  Box,
  Flex,
  VStack,
  HStack,
  Text,
  Badge,
  IconButton,
  Tooltip,
  Divider,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalCloseButton,
  useDisclosure,
  Collapse,
} from '@chakra-ui/react';
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ExternalLinkIcon,
  CloseIcon,
  InfoIcon,
} from '@chakra-ui/icons';
import * as d3 from 'd3';
import type { ProofGraph, ProofNode, ProofEdge, ProofEvidence } from '@/types/graph';

// Couleurs par rôle
const PROOF_COLORS = {
  query: '#F6AD55',    // Orange - concepts de la question
  used: '#48BB78',     // Vert - concepts utilisés
  bridge: '#4299E1',   // Bleu - concepts intermédiaires
  context: '#A0AEC0',  // Gris - contexte
  edge: {
    onPath: '#48BB78', // Vert - sur chemin de preuve
    normal: '#CBD5E0', // Gris - autres
  },
} as const;

// Labels français pour les types de relations
const RELATION_LABELS: Record<string, string> = {
  REQUIRES: 'nécessite',
  ENABLES: 'permet',
  PREVENTS: 'empêche',
  CAUSES: 'cause',
  APPLIES_TO: "s'applique à",
  DEPENDS_ON: 'dépend de',
  PART_OF: 'fait partie de',
  MITIGATES: 'atténue',
  CONFLICTS_WITH: 'en conflit avec',
  DEFINES: 'définit',
  EXAMPLE_OF: 'exemple de',
  GOVERNED_BY: 'régi par',
  RELATED_TO: 'lié à',
  USES: 'utilise',
  INTEGRATES_WITH: "s'intègre avec",
  EXTENDS: 'étend',
};

interface ProofGraphViewerProps {
  proofGraph: ProofGraph;
  onSearch?: (query: string) => void;
  defaultExpanded?: boolean;
}

interface D3ProofNode extends ProofNode {
  x: number;
  y: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
}

interface D3ProofEdge extends Omit<ProofEdge, 'source' | 'target'> {
  source: D3ProofNode;
  target: D3ProofNode;
}

/**
 * Evidence Panel - Affiche les évidences pour une arête sélectionnée
 */
function EvidencePanel({
  edge,
  sourceNode,
  targetNode,
  onClose,
}: {
  edge: ProofEdge;
  sourceNode?: ProofNode;
  targetNode?: ProofNode;
  onClose: () => void;
}) {
  const relationLabel = RELATION_LABELS[edge.relationType] || edge.relationType;

  return (
    <Box
      bg="white"
      p={4}
      borderRadius="md"
      border="1px solid"
      borderColor="gray.200"
      shadow="lg"
      maxW="400px"
      maxH="500px"
      overflowY="auto"
    >
      <Flex justify="space-between" align="flex-start" mb={3}>
        <VStack align="start" spacing={1}>
          <Text fontWeight="bold" fontSize="md" color="gray.800">
            Preuve de relation
          </Text>
          <HStack spacing={1} flexWrap="wrap">
            <Badge colorScheme="orange" fontSize="xs">{sourceNode?.name || edge.source}</Badge>
            <Text fontSize="sm" color="gray.500">{relationLabel}</Text>
            <Badge colorScheme="green" fontSize="xs">{targetNode?.name || edge.target}</Badge>
          </HStack>
        </VStack>
        <IconButton
          aria-label="Fermer"
          icon={<CloseIcon />}
          size="xs"
          variant="ghost"
          onClick={onClose}
        />
      </Flex>

      <Divider mb={3} />

      {/* Métadonnées de la relation */}
      <VStack align="stretch" spacing={2} mb={3}>
        <HStack>
          <Text fontSize="sm" color="gray.500" w="100px">Confiance:</Text>
          <Badge colorScheme={edge.confidence > 0.7 ? 'green' : edge.confidence > 0.4 ? 'yellow' : 'red'}>
            {Math.round(edge.confidence * 100)}%
          </Badge>
        </HStack>
        <HStack>
          <Text fontSize="sm" color="gray.500" w="100px">Sur chemin:</Text>
          <Badge colorScheme={edge.isOnPath ? 'green' : 'gray'}>
            {edge.isOnPath ? 'Oui (preuve directe)' : 'Non'}
          </Badge>
        </HStack>
        <HStack>
          <Text fontSize="sm" color="gray.500" w="100px">Sources:</Text>
          <Text fontSize="sm">{edge.evidenceCount} document{edge.evidenceCount > 1 ? 's' : ''}</Text>
        </HStack>
      </VStack>

      <Divider mb={3} />

      {/* Évidences */}
      <Text fontSize="sm" fontWeight="semibold" color="gray.700" mb={2}>
        Extraits justificatifs
      </Text>

      {edge.evidences.length === 0 ? (
        <Box p={3} bg="gray.50" borderRadius="md">
          <Text fontSize="sm" color="gray.500" fontStyle="italic">
            Aucun extrait disponible pour cette relation
          </Text>
        </Box>
      ) : (
        <VStack align="stretch" spacing={2}>
          {edge.evidences.map((evidence, idx) => (
            <Box key={idx} p={3} bg="blue.50" borderRadius="md" border="1px solid" borderColor="blue.100">
              {evidence.quote && (
                <Text fontSize="sm" color="gray.700" fontStyle="italic" mb={2}>
                  "{evidence.quote}"
                </Text>
              )}
              <HStack spacing={2} flexWrap="wrap">
                {evidence.source_doc && (
                  <Badge colorScheme="blue" variant="subtle" fontSize="xs">
                    {evidence.source_doc}
                  </Badge>
                )}
                {evidence.slide_index !== undefined && (
                  <Badge colorScheme="gray" variant="outline" fontSize="xs">
                    Slide {evidence.slide_index}
                  </Badge>
                )}
                {evidence.confidence !== undefined && (
                  <Badge colorScheme="green" variant="outline" fontSize="xs">
                    {Math.round(evidence.confidence * 100)}%
                  </Badge>
                )}
              </HStack>
            </Box>
          ))}
        </VStack>
      )}
    </Box>
  );
}

/**
 * Légende du graphe
 */
function ProofGraphLegend() {
  return (
    <VStack align="start" spacing={1} fontSize="xs">
      <HStack spacing={2}>
        <Box w={3} h={3} borderRadius="full" bg={PROOF_COLORS.query} />
        <Text color="gray.600">Question</Text>
      </HStack>
      <HStack spacing={2}>
        <Box w={3} h={3} borderRadius="full" bg={PROOF_COLORS.used} />
        <Text color="gray.600">Utilisé</Text>
      </HStack>
      <HStack spacing={2}>
        <Box w={3} h={3} borderRadius="full" bg={PROOF_COLORS.bridge} />
        <Text color="gray.600">Pont</Text>
      </HStack>
      <HStack spacing={2}>
        <Box w={3} h={3} borderRadius="full" bg={PROOF_COLORS.context} />
        <Text color="gray.600">Contexte</Text>
      </HStack>
      <Divider my={1} />
      <HStack spacing={2}>
        <Box w={4} h={0.5} bg={PROOF_COLORS.edge.onPath} />
        <Text color="gray.600">Chemin de preuve</Text>
      </HStack>
      <HStack spacing={2}>
        <Box w={4} h={0.5} bg={PROOF_COLORS.edge.normal} borderStyle="dashed" borderWidth={1} />
        <Text color="gray.600">Autre relation</Text>
      </HStack>
    </VStack>
  );
}

/**
 * Composant de rendu D3 du Proof Graph
 */
function ProofGraphD3({
  proofGraph,
  width,
  height,
  showLabels = false,
  onNodeClick,
  onEdgeClick,
}: {
  proofGraph: ProofGraph;
  width: number;
  height: number;
  showLabels?: boolean;
  onNodeClick?: (node: ProofNode) => void;
  onEdgeClick?: (edge: ProofEdge, sourceNode?: ProofNode, targetNode?: ProofNode) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || proofGraph.nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const g = svg.append('g');

    // Zoom
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });
    svg.call(zoom);

    // === LAYOUT BIPARTITE HORIZONTAL ===
    // Gauche: Query concepts | Droite: Used concepts
    // Simple, lisible, pas de superposition

    const queryNodes = proofGraph.nodes.filter(n => n.role === 'query');
    const usedNodes = proofGraph.nodes.filter(n => n.role === 'used');
    const otherNodes = proofGraph.nodes.filter(n => n.role !== 'query' && n.role !== 'used');

    const leftX = 120;  // Colonne gauche (Query)
    const rightX = width - 120;  // Colonne droite (Used)
    const middleX = width / 2;  // Colonne milieu (Bridge/Context)

    const nodeSpacingY = 70;  // Espacement vertical entre noeuds

    // Positionner les Query concepts à gauche
    const queryStartY = (height - (queryNodes.length - 1) * nodeSpacingY) / 2;

    // Positionner les Used concepts à droite
    const usedStartY = (height - (usedNodes.length - 1) * nodeSpacingY) / 2;

    // Positionner les autres au milieu
    const otherStartY = (height - (otherNodes.length - 1) * nodeSpacingY) / 2;

    const d3Nodes: D3ProofNode[] = proofGraph.nodes.map(n => {
      let x: number, y: number;

      if (n.role === 'query') {
        const idx = queryNodes.indexOf(n);
        x = leftX;
        y = queryStartY + idx * nodeSpacingY;
      } else if (n.role === 'used') {
        const idx = usedNodes.indexOf(n);
        x = rightX;
        y = usedStartY + idx * nodeSpacingY;
      } else {
        const idx = otherNodes.indexOf(n);
        x = middleX;
        y = otherStartY + idx * nodeSpacingY;
      }

      return { ...n, x, y };
    });

    const nodeMap = new Map(d3Nodes.map(n => [n.id, n]));

    const d3Edges: D3ProofEdge[] = proofGraph.edges
      .map(e => {
        const sourceNode = nodeMap.get(e.source);
        const targetNode = nodeMap.get(e.target);
        if (!sourceNode || !targetNode) return null;
        return { ...e, source: sourceNode, target: targetNode };
      })
      .filter((e): e is D3ProofEdge => e !== null);

    // Définir le marqueur de flèche
    const defs = svg.append('defs');
    defs.append('marker')
      .attr('id', 'proof-arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 25)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', PROOF_COLORS.edge.normal);

    defs.append('marker')
      .attr('id', 'proof-arrow-path')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 25)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', PROOF_COLORS.edge.onPath);

    // Arêtes
    const links = g.append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(d3Edges)
      .join('line')
      .attr('stroke', d => d.isOnPath ? PROOF_COLORS.edge.onPath : PROOF_COLORS.edge.normal)
      .attr('stroke-width', d => d.isOnPath ? 3 : 1.5)
      .attr('stroke-dasharray', d => d.isOnPath ? 'none' : '5,5')
      .attr('marker-end', d => d.isOnPath ? 'url(#proof-arrow-path)' : 'url(#proof-arrow)')
      .attr('opacity', 0.8)
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y)
      .style('cursor', 'pointer')
      .on('click', (event, d) => {
        event.stopPropagation();
        const originalEdge = proofGraph.edges.find(e => e.id === d.id);
        const srcNode = proofGraph.nodes.find(n => n.id === d.source.id);
        const tgtNode = proofGraph.nodes.find(n => n.id === d.target.id);
        if (originalEdge) {
          onEdgeClick?.(originalEdge, srcNode, tgtNode);
        }
      });

    // Labels sur les arêtes (type de relation)
    if (showLabels) {
      g.append('g')
        .attr('class', 'edge-labels')
        .selectAll('text')
        .data(d3Edges)
        .join('text')
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2 - 5)
        .attr('text-anchor', 'middle')
        .attr('font-size', '9px')
        .attr('fill', d => d.isOnPath ? PROOF_COLORS.edge.onPath : '#718096')
        .attr('pointer-events', 'none')
        .text(d => RELATION_LABELS[d.relationType] || d.relationType);
    }

    // Noeuds - petits cercles avec labels à côté
    const nodeRadius = 12;

    const nodeGroups = g.append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(d3Nodes)
      .join('g')
      .attr('class', 'node')
      .attr('transform', d => `translate(${d.x},${d.y})`)
      .style('cursor', 'pointer')
      .on('click', (event, d) => {
        event.stopPropagation();
        const originalNode = proofGraph.nodes.find(n => n.id === d.id);
        if (originalNode) {
          onNodeClick?.(originalNode);
        }
      });

    // Cercle du noeud (petit)
    nodeGroups.append('circle')
      .attr('r', nodeRadius)
      .attr('fill', d => PROOF_COLORS[d.role] || PROOF_COLORS.context)
      .attr('stroke', d => d.isOnPath ? '#2D3748' : 'white')
      .attr('stroke-width', 2);

    // Label À CÔTÉ du cercle (pas dedans)
    // Query (gauche) : texte à droite du cercle
    // Used (droite) : texte à gauche du cercle
    // Autres : texte en dessous
    nodeGroups.append('text')
      .attr('x', d => {
        if (d.role === 'query') return nodeRadius + 8;  // Texte à droite
        if (d.role === 'used') return -(nodeRadius + 8);  // Texte à gauche
        return 0;  // Centré
      })
      .attr('y', d => {
        if (d.role === 'query' || d.role === 'used') return 0;
        return nodeRadius + 15;  // En dessous
      })
      .attr('text-anchor', d => {
        if (d.role === 'query') return 'start';  // Aligné à gauche
        if (d.role === 'used') return 'end';  // Aligné à droite
        return 'middle';
      })
      .attr('dominant-baseline', 'central')
      .attr('font-size', '11px')
      .attr('fill', '#2D3748')
      .attr('font-weight', '500')
      .attr('pointer-events', 'none')
      .text(d => d.name.length > 30 ? d.name.slice(0, 28) + '...' : d.name);

    // Tooltip natif
    nodeGroups.append('title')
      .text(d => {
        const lines = [
          d.name,
          '─────────────',
          `Rôle: ${d.role === 'query' ? 'Question' : d.role === 'used' ? 'Utilisé' : d.role === 'bridge' ? 'Pont' : 'Contexte'}`,
          `Profondeur: ${d.depth}`,
          `Confiance: ${Math.round(d.confidence * 100)}%`,
        ];
        if (d.documentCount > 0) {
          lines.push(`Documents: ${d.documentCount}`);
        }
        if (d.isOnPath) {
          lines.push('✓ Sur chemin de preuve');
        }
        return lines.join('\n');
      });

    // Zoom initial pour voir tout le graphe (layout radial)
    const scale = showLabels ? 0.8 : 1.0;
    svg.call(zoom.transform as any, d3.zoomIdentity
      .translate(0, 0)
      .scale(scale)
    );

  }, [proofGraph, width, height, showLabels, onNodeClick, onEdgeClick]);

  if (proofGraph.nodes.length === 0) {
    return (
      <Flex w="100%" h={height} align="center" justify="center" bg="gray.50" borderRadius="md">
        <Text fontSize="sm" color="gray.500">Aucun concept à afficher</Text>
      </Flex>
    );
  }

  return (
    <Box position="relative" w="100%" h={height} bg="white" borderRadius="md" border="1px solid" borderColor="gray.200">
      <svg ref={svgRef} width="100%" height={height} style={{ display: 'block' }} />
    </Box>
  );
}

/**
 * Vue Confidence Trail - Timeline linéaire du chemin de preuve
 */
function ConfidenceTrail({
  proofGraph,
  onEdgeClick,
}: {
  proofGraph: ProofGraph;
  onEdgeClick?: (edge: ProofEdge, sourceNode?: ProofNode, targetNode?: ProofNode) => void;
}) {
  if (proofGraph.paths.length === 0) {
    return (
      <Box p={4} bg="gray.50" borderRadius="md">
        <Text fontSize="sm" color="gray.500">Aucun chemin de preuve disponible</Text>
      </Box>
    );
  }

  return (
    <VStack align="stretch" spacing={3} p={2}>
      {proofGraph.paths.slice(0, 3).map((path, pathIdx) => (
        <Box key={path.pathId} p={3} bg="white" borderRadius="md" border="1px solid" borderColor="gray.200">
          <HStack spacing={2} mb={2}>
            <Badge colorScheme="green" fontSize="xs">Chemin {pathIdx + 1}</Badge>
            <Badge colorScheme="blue" variant="outline" fontSize="xs">
              Confiance: {Math.round(path.totalConfidence * 100)}%
            </Badge>
          </HStack>

          {/* Timeline des étapes */}
          <VStack align="stretch" spacing={0} position="relative">
            {path.nodeIds.map((nodeId, nodeIdx) => {
              const node = proofGraph.nodes.find(n => n.id === nodeId);
              const isLast = nodeIdx === path.nodeIds.length - 1;
              const edgeToNext = nodeIdx < path.nodeIds.length - 1
                ? proofGraph.edges.find(e =>
                    e.source === nodeId && e.target === path.nodeIds[nodeIdx + 1]
                  )
                : null;

              return (
                <Box key={nodeId} position="relative">
                  {/* Noeud */}
                  <HStack spacing={3} py={2}>
                    {/* Indicateur de timeline */}
                    <VStack spacing={0} align="center" w="20px">
                      <Box
                        w={3}
                        h={3}
                        borderRadius="full"
                        bg={
                          node?.role === 'query' ? PROOF_COLORS.query :
                          node?.role === 'used' ? PROOF_COLORS.used :
                          PROOF_COLORS.bridge
                        }
                        border="2px solid white"
                        boxShadow="0 0 0 2px gray"
                      />
                      {!isLast && (
                        <Box w="2px" h="30px" bg="gray.300" />
                      )}
                    </VStack>

                    {/* Contenu du noeud */}
                    <VStack align="start" spacing={0} flex={1}>
                      <Text fontSize="sm" fontWeight="medium" color="gray.700">
                        {node?.name || nodeId}
                      </Text>
                      <HStack spacing={1}>
                        <Badge
                          size="sm"
                          colorScheme={
                            node?.role === 'query' ? 'orange' :
                            node?.role === 'used' ? 'green' : 'blue'
                          }
                          variant="subtle"
                          fontSize="2xs"
                        >
                          {node?.role === 'query' ? 'Question' :
                           node?.role === 'used' ? 'Utilisé' : 'Pont'}
                        </Badge>
                        {node?.confidence && (
                          <Text fontSize="2xs" color="gray.400">
                            {Math.round(node.confidence * 100)}%
                          </Text>
                        )}
                      </HStack>
                    </VStack>
                  </HStack>

                  {/* Relation vers le noeud suivant */}
                  {edgeToNext && (
                    <HStack
                      spacing={2}
                      pl="32px"
                      py={1}
                      cursor="pointer"
                      _hover={{ bg: 'blue.50' }}
                      borderRadius="sm"
                      onClick={() => {
                        const srcNode = proofGraph.nodes.find(n => n.id === edgeToNext.source);
                        const tgtNode = proofGraph.nodes.find(n => n.id === edgeToNext.target);
                        onEdgeClick?.(edgeToNext, srcNode, tgtNode);
                      }}
                    >
                      <Text fontSize="xs" color="gray.500">↓</Text>
                      <Badge
                        colorScheme={edgeToNext.isOnPath ? 'green' : 'gray'}
                        variant="outline"
                        fontSize="2xs"
                      >
                        {RELATION_LABELS[edgeToNext.relationType] || edgeToNext.relationType}
                      </Badge>
                      <Text fontSize="2xs" color="gray.400">
                        ({Math.round(edgeToNext.confidence * 100)}%)
                      </Text>
                      <InfoIcon boxSize={2.5} color="blue.400" />
                    </HStack>
                  )}
                </Box>
              );
            })}
          </VStack>
        </Box>
      ))}
    </VStack>
  );
}

// Types pour le mode de vue
type ViewMode = 'graph' | 'trail';

/**
 * Composant principal - Proof Graph Viewer
 */
function ProofGraphViewerComponent({
  proofGraph,
  onSearch,
  defaultExpanded = false,
}: ProofGraphViewerProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [viewMode, setViewMode] = useState<ViewMode>('graph');
  const [selectedEdge, setSelectedEdge] = useState<{
    edge: ProofEdge;
    sourceNode?: ProofNode;
    targetNode?: ProofNode;
  } | null>(null);
  const { isOpen: isModalOpen, onOpen: openModal, onClose: closeModal } = useDisclosure();

  const handleEdgeClick = useCallback((
    edge: ProofEdge,
    sourceNode?: ProofNode,
    targetNode?: ProofNode
  ) => {
    setSelectedEdge({ edge, sourceNode, targetNode });
  }, []);

  const handleCloseEvidence = useCallback(() => {
    setSelectedEdge(null);
  }, []);

  const nodeCount = proofGraph.nodes.length;
  const edgeCount = proofGraph.edges.length;
  const pathCount = proofGraph.paths.length;

  if (nodeCount === 0) {
    return null;
  }

  return (
    <Box mt={1} borderTop="1px solid" borderColor="gray.100" pt={1}>
      {/* Header compact */}
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
        <Box as={isExpanded ? ChevronUpIcon : ChevronDownIcon} boxSize={3} color="gray.400" />
        <HStack spacing={0.5}>
          <Box w={1.5} h={1.5} borderRadius="full" bg="teal.400" />
          <Text fontSize="2xs" color="gray.500" fontWeight="medium">
            Proof Graph
          </Text>
        </HStack>
        <Badge colorScheme="teal" fontSize="2xs" variant="subtle" px={1}>
          {nodeCount} concepts
        </Badge>
        {pathCount > 0 && (
          <Badge colorScheme="green" fontSize="2xs" variant="outline" px={1}>
            {pathCount} chemin{pathCount > 1 ? 's' : ''}
          </Badge>
        )}
        <Box flex="1" />
        {isExpanded && (
          <Tooltip label="Agrandir" fontSize="xs">
            <IconButton
              aria-label="Agrandir"
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

      {/* Contenu dépliable */}
      <Collapse in={isExpanded}>
        <Box mt={1} p={2} bg="gray.50" borderRadius="sm">
          {/* Mode Switch: Graph | Trail */}
          <HStack spacing={1} mb={2} justify="center">
            <HStack
              spacing={0}
              bg="gray.200"
              p={0.5}
              borderRadius="md"
            >
              <Box
                px={3}
                py={1}
                borderRadius="md"
                bg={viewMode === 'graph' ? 'white' : 'transparent'}
                color={viewMode === 'graph' ? 'teal.600' : 'gray.500'}
                fontWeight={viewMode === 'graph' ? 'medium' : 'normal'}
                fontSize="xs"
                cursor="pointer"
                transition="all 0.2s"
                boxShadow={viewMode === 'graph' ? 'sm' : 'none'}
                onClick={(e) => {
                  e.stopPropagation();
                  setViewMode('graph');
                }}
              >
                Graphe
              </Box>
              <Box
                px={3}
                py={1}
                borderRadius="md"
                bg={viewMode === 'trail' ? 'white' : 'transparent'}
                color={viewMode === 'trail' ? 'green.600' : 'gray.500'}
                fontWeight={viewMode === 'trail' ? 'medium' : 'normal'}
                fontSize="xs"
                cursor="pointer"
                transition="all 0.2s"
                boxShadow={viewMode === 'trail' ? 'sm' : 'none'}
                onClick={(e) => {
                  e.stopPropagation();
                  setViewMode('trail');
                }}
              >
                Timeline
              </Box>
            </HStack>
          </HStack>

          <Flex gap={3}>
            {/* Vue conditionnelle: Graph ou Trail */}
            <Box flex="1">
              {viewMode === 'graph' ? (
                <ProofGraphD3
                  proofGraph={proofGraph}
                  width={500}
                  height={250}
                  onEdgeClick={handleEdgeClick}
                />
              ) : (
                <Box maxH="300px" overflowY="auto">
                  <ConfidenceTrail
                    proofGraph={proofGraph}
                    onEdgeClick={handleEdgeClick}
                  />
                </Box>
              )}
            </Box>

            {/* Evidence Panel (si arête sélectionnée) */}
            {selectedEdge && (
              <Box flexShrink={0}>
                <EvidencePanel
                  edge={selectedEdge.edge}
                  sourceNode={selectedEdge.sourceNode}
                  targetNode={selectedEdge.targetNode}
                  onClose={handleCloseEvidence}
                />
              </Box>
            )}
          </Flex>

          {/* Stats et légende compacts - seulement en mode graphe */}
          {viewMode === 'graph' && (
          <Flex mt={2} justify="space-between" align="center">
            <HStack spacing={2} fontSize="2xs" color="gray.400">
              <HStack spacing={0.5}>
                <Box w={1.5} h={1.5} borderRadius="full" bg={PROOF_COLORS.query} />
                <Text>Question</Text>
              </HStack>
              <HStack spacing={0.5}>
                <Box w={1.5} h={1.5} borderRadius="full" bg={PROOF_COLORS.used} />
                <Text>Utilisé</Text>
              </HStack>
              <HStack spacing={0.5}>
                <Box w={1.5} h={1.5} borderRadius="full" bg={PROOF_COLORS.bridge} />
                <Text>Pont</Text>
              </HStack>
            </HStack>
            <Text fontSize="2xs" color="gray.400">
              Cliquez sur une relation pour voir les preuves
            </Text>
          </Flex>
          )}
        </Box>
      </Collapse>

      {/* Modal agrandi */}
      <Modal isOpen={isModalOpen} onClose={closeModal} size="6xl">
        <ModalOverlay />
        <ModalContent maxW="95vw">
          <ModalHeader>
            <HStack>
              <Text>Proof Graph - Chemin de raisonnement</Text>
              <Badge colorScheme="teal">{nodeCount} concepts</Badge>
              <Badge colorScheme="blue">{edgeCount} relations</Badge>
              <Badge colorScheme="green">{pathCount} chemin{pathCount > 1 ? 's' : ''} de preuve</Badge>
            </HStack>
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <Flex gap={4}>
              {/* Graphe avec labels */}
              <Box flex="1" h="600px" border="1px solid" borderColor="gray.200" borderRadius="md" overflow="hidden">
                <ProofGraphD3
                  proofGraph={proofGraph}
                  width={1000}
                  height={600}
                  showLabels={true}
                  onEdgeClick={handleEdgeClick}
                />
              </Box>

              {/* Panneau latéral */}
              <VStack w="350px" align="stretch" spacing={4}>
                {/* Légende */}
                <Box p={3} bg="gray.50" borderRadius="md">
                  <Text fontSize="sm" fontWeight="semibold" mb={2}>Légende</Text>
                  <ProofGraphLegend />
                </Box>

                {/* Evidence Panel */}
                {selectedEdge ? (
                  <EvidencePanel
                    edge={selectedEdge.edge}
                    sourceNode={selectedEdge.sourceNode}
                    targetNode={selectedEdge.targetNode}
                    onClose={handleCloseEvidence}
                  />
                ) : (
                  <Box p={4} bg="blue.50" borderRadius="md" border="1px solid" borderColor="blue.100">
                    <HStack spacing={2} mb={2}>
                      <InfoIcon color="blue.500" />
                      <Text fontSize="sm" fontWeight="medium" color="blue.700">
                        Sélectionnez une relation
                      </Text>
                    </HStack>
                    <Text fontSize="sm" color="gray.600">
                      Cliquez sur une ligne entre deux concepts pour voir les preuves documentaires qui justifient cette relation.
                    </Text>
                  </Box>
                )}

                {/* Chemins de preuve */}
                {proofGraph.paths.length > 0 && (
                  <Box p={3} bg="green.50" borderRadius="md" border="1px solid" borderColor="green.100">
                    <Text fontSize="sm" fontWeight="semibold" color="green.700" mb={2}>
                      Chemins de preuve ({proofGraph.paths.length})
                    </Text>
                    <VStack align="stretch" spacing={2}>
                      {proofGraph.paths.slice(0, 3).map((path, idx) => (
                        <Box key={path.pathId} p={2} bg="white" borderRadius="sm">
                          <HStack spacing={1} flexWrap="wrap">
                            {path.nodeIds.map((nodeId, nodeIdx) => {
                              const node = proofGraph.nodes.find(n => n.id === nodeId);
                              return (
                                <HStack key={nodeId} spacing={1}>
                                  <Badge
                                    colorScheme={
                                      node?.role === 'query' ? 'orange' :
                                      node?.role === 'used' ? 'green' : 'blue'
                                    }
                                    fontSize="xs"
                                  >
                                    {node?.name || nodeId.slice(0, 10)}
                                  </Badge>
                                  {nodeIdx < path.nodeIds.length - 1 && (
                                    <Text color="gray.400">→</Text>
                                  )}
                                </HStack>
                              );
                            })}
                          </HStack>
                          <Text fontSize="xs" color="gray.500" mt={1}>
                            Confiance: {Math.round(path.totalConfidence * 100)}%
                          </Text>
                        </Box>
                      ))}
                    </VStack>
                  </Box>
                )}
              </VStack>
            </Flex>

            <Text mt={4} fontSize="xs" color="gray.400" textAlign="center">
              Molette pour zoomer • Glissez pour déplacer • Cliquez sur une relation pour les preuves
            </Text>
          </ModalBody>
        </ModalContent>
      </Modal>
    </Box>
  );
}

export const ProofGraphViewer = memo(ProofGraphViewerComponent);
export default ProofGraphViewer;
