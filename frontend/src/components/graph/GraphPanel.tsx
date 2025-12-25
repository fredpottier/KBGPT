'use client';

/**
 * OSMOS Phase 3.5 - Graph Panel
 *
 * Panel conteneur pour le Knowledge Graph avec contrôles.
 * Gère la visibilité, le redimensionnement et les interactions.
 */

import { useCallback, useMemo, useState } from 'react';
import {
  Box,
  Flex,
  IconButton,
  HStack,
  Text,
  Tooltip,
  Badge,
  Switch,
  FormControl,
} from '@chakra-ui/react';
import {
  ChevronRightIcon,
  ChevronLeftIcon,
  RepeatIcon,
} from '@chakra-ui/icons';
import KnowledgeGraph from './KnowledgeGraph';
import GraphTooltip from './GraphTooltip';
import { useGraphStore, graphSelectors } from '@/stores/graphStore';
import type { GraphNode, GraphEdge } from '@/types/graph';

interface GraphPanelProps {
  onNodeClick?: (node: GraphNode) => void;
  onConceptExplore?: (conceptId: string) => void;
  width?: string | number;
  minWidth?: number;
  maxWidth?: number;
}

export default function GraphPanel({
  onNodeClick,
  onConceptExplore,
  width = '30%',
  minWidth = 300,
  maxWidth = 500,
}: GraphPanelProps) {
  const {
    nodes,
    edges,
    queryConceptIds,
    usedConceptIds,
    suggestedConceptIds,
    isVisible,
    autoExpand,
    selectedNodeId,
    hoveredNodeId,
    toggleVisibility,
    setAutoExpand,
    resetSession,
    selectNode,
    hoverNode,
  } = useGraphStore();

  // État local pour la position de la souris (tooltip)
  const [mousePosition, setMousePosition] = useState<{ x: number; y: number } | null>(null);

  // Stats du graphe
  const stats = useMemo(() => {
    return graphSelectors.getNodeCountByRole({
      nodes,
      edges,
      queryConceptIds,
      usedConceptIds,
      suggestedConceptIds,
      selectedNodeId,
      hoveredNodeId: null,
      focusedNodeId: null,
      isVisible,
      autoExpand,
      sessionHistory: { nodeIds: new Set(), edgeIds: new Set() },
    });
  }, [nodes, edges, queryConceptIds, usedConceptIds, suggestedConceptIds, selectedNodeId, isVisible, autoExpand]);

  const hasData = nodes.length > 0;

  // Handlers
  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      selectNode(node.id);
      onNodeClick?.(node);
    },
    [selectNode, onNodeClick]
  );

  const handleNodeHover = useCallback((node: GraphNode | null, event?: MouseEvent) => {
    hoverNode(node?.id || null);
    if (event && node) {
      setMousePosition({ x: event.clientX, y: event.clientY });
    } else {
      setMousePosition(null);
    }
  }, [hoverNode]);

  const handleReset = useCallback(() => {
    resetSession();
  }, [resetSession]);

  const handleToggleAutoExpand = useCallback(() => {
    setAutoExpand(!autoExpand);
  }, [autoExpand, setAutoExpand]);

  // Panel réduit
  if (!isVisible) {
    return (
      <Box
        position="relative"
        w="40px"
        h="full"
        bg="gray.100"
        borderLeft="1px solid"
        borderColor="gray.200"
        display="flex"
        alignItems="center"
        justifyContent="center"
      >
        <Tooltip label="Afficher le graphe" placement="left">
          <IconButton
            aria-label="Show graph"
            icon={<ChevronLeftIcon />}
            size="sm"
            variant="ghost"
            onClick={toggleVisibility}
          />
        </Tooltip>
        {hasData && (
          <Badge
            position="absolute"
            top={2}
            colorScheme="blue"
            fontSize="xs"
            transform="rotate(-90deg)"
            transformOrigin="center"
          >
            {nodes.length}
          </Badge>
        )}
      </Box>
    );
  }

  return (
    <Box
      position="relative"
      w={width}
      minW={minWidth}
      maxW={maxWidth}
      h="full"
      bg="white"
      borderLeft="1px solid"
      borderColor="gray.200"
      display="flex"
      flexDirection="column"
    >
      {/* Header */}
      <Flex
        px={3}
        py={2}
        borderBottom="1px solid"
        borderColor="gray.100"
        align="center"
        justify="space-between"
        bg="gray.50"
      >
        <HStack spacing={2}>
          <Text fontWeight="semibold" fontSize="sm" color="gray.700">
            Knowledge Graph
          </Text>
          {hasData && (
            <Badge colorScheme="blue" fontSize="xs">
              {nodes.length} concepts
            </Badge>
          )}
        </HStack>

        <HStack spacing={1}>
          {/* Toggle auto-expand */}
          <Tooltip label={autoExpand ? 'Accumulation activée' : 'Accumulation désactivée'}>
            <Box>
              <FormControl display="flex" alignItems="center" size="sm">
                <Switch
                  id="auto-expand"
                  size="sm"
                  isChecked={autoExpand}
                  onChange={handleToggleAutoExpand}
                  colorScheme="green"
                />
              </FormControl>
            </Box>
          </Tooltip>

          {/* Reset */}
          <Tooltip label="Réinitialiser le graphe">
            <IconButton
              aria-label="Reset graph"
              icon={<RepeatIcon />}
              size="xs"
              variant="ghost"
              onClick={handleReset}
              isDisabled={!hasData}
            />
          </Tooltip>

          {/* Masquer */}
          <Tooltip label="Masquer le graphe">
            <IconButton
              aria-label="Hide graph"
              icon={<ChevronRightIcon />}
              size="xs"
              variant="ghost"
              onClick={toggleVisibility}
            />
          </Tooltip>
        </HStack>
      </Flex>

      {/* Stats rapides */}
      {hasData && (
        <Flex
          px={3}
          py={1}
          borderBottom="1px solid"
          borderColor="gray.100"
          gap={2}
          fontSize="xs"
          color="gray.500"
          flexWrap="wrap"
        >
          {stats.query > 0 && (
            <HStack spacing={1}>
              <Box w={2} h={2} borderRadius="full" bg="orange.400" />
              <Text>{stats.query}</Text>
            </HStack>
          )}
          {stats.used > 0 && (
            <HStack spacing={1}>
              <Box w={2} h={2} borderRadius="full" bg="green.400" />
              <Text>{stats.used}</Text>
            </HStack>
          )}
          {stats.suggested > 0 && (
            <HStack spacing={1}>
              <Box w={2} h={2} borderRadius="full" bg="blue.400" />
              <Text>{stats.suggested}</Text>
            </HStack>
          )}
          {stats.context > 0 && (
            <HStack spacing={1}>
              <Box w={2} h={2} borderRadius="full" bg="gray.400" />
              <Text>{stats.context}</Text>
            </HStack>
          )}
        </Flex>
      )}

      {/* Graphe */}
      <Box flex="1" position="relative" overflow="hidden">
        <KnowledgeGraph
          nodes={nodes}
          edges={edges}
          queryConceptIds={queryConceptIds}
          usedConceptIds={usedConceptIds}
          suggestedConceptIds={suggestedConceptIds}
          onNodeClick={handleNodeClick}
          onNodeHover={handleNodeHover}
          showLegend={!hasData || nodes.length < 5}
          enableZoom={true}
          enablePan={true}
          maxNodes={50}
        />
      </Box>

      {/* Concept sélectionné (preview) */}
      {selectedNodeId && (
        <Box
          px={3}
          py={2}
          borderTop="1px solid"
          borderColor="gray.200"
          bg="blue.50"
        >
          <HStack justify="space-between">
            <Text fontSize="sm" fontWeight="medium" color="blue.700" noOfLines={1}>
              {nodes.find((n) => n.id === selectedNodeId)?.name || 'Concept'}
            </Text>
            <Text
              fontSize="xs"
              color="blue.500"
              cursor="pointer"
              onClick={() => onConceptExplore?.(selectedNodeId)}
              _hover={{ textDecoration: 'underline' }}
            >
              Explorer →
            </Text>
          </HStack>
        </Box>
      )}

      {/* Tooltip pour le noeud survolé */}
      <GraphTooltip
        node={hoveredNodeId ? nodes.find((n) => n.id === hoveredNodeId) || null : null}
        position={mousePosition}
        isVisible={!!hoveredNodeId && !!mousePosition}
      />
    </Box>
  );
}
