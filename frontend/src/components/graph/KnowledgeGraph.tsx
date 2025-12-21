'use client';

/**
 * 🌊 OSMOSE Phase 3.5 - Knowledge Graph D3.js
 *
 * Composant de visualisation du Knowledge Graph avec D3.js force-directed layout.
 * Affiche les concepts et leurs relations avec couleurs selon le rôle.
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { Box, Spinner, Center, Text, VStack } from '@chakra-ui/react';
import * as d3 from 'd3';
import type {
  GraphNode,
  GraphEdge,
  KnowledgeGraphProps,
} from '@/types/graph';
import { GRAPH_COLORS, getNodeColor, getEdgeStyle } from '@/types/graph';
import { getNodeRadius, getNodeBorderColor, getLinkStrength } from '@/lib/graph';
import { useGraphStore } from '@/stores/graphStore';

// Types internes pour D3
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

export default function KnowledgeGraph({
  nodes,
  edges,
  queryConceptIds,
  usedConceptIds,
  suggestedConceptIds,
  onNodeClick,
  onNodeHover,
  onEdgeClick,
  width = 400,
  height = 500,
  showLegend = true,
  enableZoom = true,
  enablePan = true,
  maxNodes = 50,
}: KnowledgeGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simulationRef = useRef<d3.Simulation<D3Node, D3Edge> | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [dimensions, setDimensions] = useState({ width, height });

  // Store Zustand pour les interactions
  const { hoveredNodeId, selectedNodeId, hoverNode, selectNode } = useGraphStore();

  // Limiter le nombre de noeuds
  const limitedNodes = nodes.slice(0, maxNodes);
  const nodeIds = new Set(limitedNodes.map((n) => n.id));
  const limitedEdges = edges.filter((e) => {
    const sourceId = typeof e.source === 'string' ? e.source : e.source.id;
    const targetId = typeof e.target === 'string' ? e.target : e.target.id;
    return nodeIds.has(sourceId) && nodeIds.has(targetId);
  });

  // Observer pour le redimensionnement
  useEffect(() => {
    if (!containerRef.current) return;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width: w, height: h } = entry.contentRect;
        if (w > 0 && h > 0) {
          setDimensions({ width: w, height: h });
        }
      }
    });

    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
    };
  }, []);

  // Rendu D3
  useEffect(() => {
    if (!svgRef.current || limitedNodes.length === 0) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);

    const svg = d3.select(svgRef.current);
    const { width: w, height: h } = dimensions;

    // Clear previous content
    svg.selectAll('*').remove();

    // Create main group for zoom/pan
    const g = svg.append('g').attr('class', 'graph-container');

    // Zoom behavior
    if (enableZoom || enablePan) {
      const zoom = d3
        .zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 3])
        .on('zoom', (event) => {
          g.attr('transform', event.transform);
        });

      svg.call(zoom);

      // Initial zoom to fit
      const initialScale = 0.8;
      const initialTransform = d3.zoomIdentity
        .translate(w / 2, h / 2)
        .scale(initialScale)
        .translate(-w / 2, -h / 2);
      svg.call(zoom.transform, initialTransform);
    }

    // Préparer les données pour D3
    const d3Nodes: D3Node[] = limitedNodes.map((n) => ({
      ...n,
      x: w / 2 + (Math.random() - 0.5) * 100,
      y: h / 2 + (Math.random() - 0.5) * 100,
    }));

    const nodeMap = new Map(d3Nodes.map((n) => [n.id, n]));

    const d3Edges: D3Edge[] = limitedEdges
      .map((e) => {
        const sourceId = typeof e.source === 'string' ? e.source : e.source.id;
        const targetId = typeof e.target === 'string' ? e.target : e.target.id;
        const sourceNode = nodeMap.get(sourceId);
        const targetNode = nodeMap.get(targetId);

        if (!sourceNode || !targetNode) return null;

        return {
          ...e,
          source: sourceNode,
          target: targetNode,
        };
      })
      .filter((e): e is D3Edge => e !== null);

    // Définir les marqueurs de flèche
    const defs = svg.append('defs');

    // Marqueur pour arêtes normales
    defs
      .append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', GRAPH_COLORS.edge.available);

    // Marqueur pour arêtes utilisées
    defs
      .append('marker')
      .attr('id', 'arrowhead-used')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', GRAPH_COLORS.edge.used);

    // Créer les arêtes
    const links = g
      .append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(d3Edges)
      .join('line')
      .attr('stroke', (d) => getEdgeStyle(d).stroke)
      .attr('stroke-width', (d) => getEdgeStyle(d).strokeWidth)
      .attr('stroke-dasharray', (d) => getEdgeStyle(d).strokeDasharray)
      .attr('marker-end', (d) => (d.isUsed ? 'url(#arrowhead-used)' : 'url(#arrowhead)'))
      .attr('opacity', 0.6)
      .style('cursor', 'pointer')
      .on('click', (event, d) => {
        event.stopPropagation();
        onEdgeClick?.(d);
      });

    // Créer les noeuds
    const nodeGroups = g
      .append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(d3Nodes)
      .join('g')
      .attr('class', 'node')
      .style('cursor', 'pointer')
      .call(
        d3
          .drag<SVGGElement, D3Node>()
          .on('start', (event, d) => {
            if (!event.active) simulationRef.current?.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulationRef.current?.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      )
      .on('click', (event, d) => {
        event.stopPropagation();
        selectNode(d.id);
        onNodeClick?.(d);
      })
      .on('mouseenter', (event, d) => {
        hoverNode(d.id);
        onNodeHover?.(d, event);
      })
      .on('mousemove', (event, d) => {
        // Mettre à jour la position pendant le mouvement pour un tooltip fluide
        onNodeHover?.(d, event);
      })
      .on('mouseleave', () => {
        hoverNode(null);
        onNodeHover?.(null);
      });

    // Cercle de fond pour le halo
    nodeGroups
      .append('circle')
      .attr('class', 'node-halo')
      .attr('r', (d) => getNodeRadius(d) + 4)
      .attr('fill', 'none')
      .attr('stroke', 'none')
      .attr('stroke-width', 3);

    // Cercle principal
    nodeGroups
      .append('circle')
      .attr('class', 'node-circle')
      .attr('r', (d) => getNodeRadius(d))
      .attr('fill', (d) => getNodeColor(d.role))
      .attr('stroke', (d) => getNodeBorderColor(d.type))
      .attr('stroke-width', 2);

    // Label du noeud
    nodeGroups
      .append('text')
      .attr('class', 'node-label')
      .attr('dy', (d) => getNodeRadius(d) + 14)
      .attr('text-anchor', 'middle')
      .attr('font-size', '10px')
      .attr('fill', '#4A5568')
      .attr('pointer-events', 'none')
      .text((d) => d.name.length > 15 ? d.name.slice(0, 12) + '...' : d.name);

    // Simulation force-directed
    const simulation = d3
      .forceSimulation<D3Node>(d3Nodes)
      .force(
        'link',
        d3
          .forceLink<D3Node, D3Edge>(d3Edges)
          .id((d) => d.id)
          .distance(80)
          .strength((d) => getLinkStrength(d))
      )
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(w / 2, h / 2))
      .force('collision', d3.forceCollide().radius((d) => getNodeRadius(d as D3Node) + 10))
      .on('tick', () => {
        links
          .attr('x1', (d) => d.source.x)
          .attr('y1', (d) => d.source.y)
          .attr('x2', (d) => d.target.x)
          .attr('y2', (d) => d.target.y);

        nodeGroups.attr('transform', (d) => `translate(${d.x},${d.y})`);
      })
      .on('end', () => {
        setIsLoading(false);
      });

    simulationRef.current = simulation;

    // Timeout pour afficher même si simulation non terminée
    const timeout = setTimeout(() => {
      setIsLoading(false);
    }, 2000);

    // Cleanup
    return () => {
      simulation.stop();
      clearTimeout(timeout);
    };
  }, [
    limitedNodes,
    limitedEdges,
    dimensions,
    enableZoom,
    enablePan,
    onNodeClick,
    onNodeHover,
    onEdgeClick,
    selectNode,
    hoverNode,
  ]);

  // Effet de highlight sur hover/selection
  useEffect(() => {
    if (!svgRef.current) return;

    const svg = d3.select(svgRef.current);

    // Reset tous les noeuds
    svg.selectAll('.node-halo').attr('stroke', 'none');
    svg.selectAll('.node-circle').attr('opacity', 1);
    svg.selectAll('.node-label').attr('opacity', 1);

    // Si un noeud est survolé ou sélectionné
    if (hoveredNodeId || selectedNodeId) {
      const activeId = hoveredNodeId || selectedNodeId;

      // Dim les noeuds non connectés
      svg.selectAll('.node').each(function (d) {
        const node = d as D3Node;
        const isActive = node.id === activeId;
        const isConnected = limitedEdges.some((e) => {
          const sourceId = typeof e.source === 'string' ? e.source : (e.source as D3Node).id;
          const targetId = typeof e.target === 'string' ? e.target : (e.target as D3Node).id;
          return (
            (sourceId === activeId && targetId === node.id) ||
            (targetId === activeId && sourceId === node.id)
          );
        });

        d3.select(this)
          .select('.node-circle')
          .attr('opacity', isActive || isConnected ? 1 : 0.3);
        d3.select(this)
          .select('.node-label')
          .attr('opacity', isActive || isConnected ? 1 : 0.3);
      });

      // Highlight le noeud actif
      svg
        .selectAll('.node')
        .filter((d) => (d as D3Node).id === activeId)
        .select('.node-halo')
        .attr('stroke', GRAPH_COLORS.query)
        .attr('stroke-opacity', 0.5);
    }
  }, [hoveredNodeId, selectedNodeId, limitedEdges]);

  // Pas de données
  if (nodes.length === 0) {
    return (
      <Center h="full" w="full" bg="gray.50" borderRadius="md">
        <VStack spacing={2}>
          <Text color="gray.500" fontSize="sm">
            Aucun concept à afficher
          </Text>
          <Text color="gray.400" fontSize="xs">
            Le graphe apparaîtra après votre première question
          </Text>
        </VStack>
      </Center>
    );
  }

  return (
    <Box
      ref={containerRef}
      position="relative"
      w="full"
      h="full"
      bg="white"
      borderRadius="md"
      overflow="hidden"
    >
      {/* Loading overlay */}
      {isLoading && (
        <Center
          position="absolute"
          top={0}
          left={0}
          right={0}
          bottom={0}
          bg="whiteAlpha.800"
          zIndex={10}
        >
          <VStack>
            <Spinner size="lg" color="brand.500" />
            <Text fontSize="sm" color="gray.500">
              Calcul du graphe...
            </Text>
          </VStack>
        </Center>
      )}

      {/* SVG D3 */}
      <svg
        ref={svgRef}
        width="100%"
        height="100%"
        viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
        style={{ display: 'block' }}
      />

      {/* Légende */}
      {showLegend && (
        <Box
          position="absolute"
          bottom={2}
          left={2}
          bg="whiteAlpha.900"
          p={2}
          borderRadius="md"
          fontSize="xs"
          boxShadow="sm"
        >
          <VStack align="start" spacing={1}>
            <Box display="flex" alignItems="center" gap={2}>
              <Box w={3} h={3} borderRadius="full" bg={GRAPH_COLORS.query} />
              <Text>Question</Text>
            </Box>
            <Box display="flex" alignItems="center" gap={2}>
              <Box w={3} h={3} borderRadius="full" bg={GRAPH_COLORS.used} />
              <Text>Utilisé</Text>
            </Box>
            <Box display="flex" alignItems="center" gap={2}>
              <Box w={3} h={3} borderRadius="full" bg={GRAPH_COLORS.suggested} />
              <Text>Suggéré</Text>
            </Box>
            <Box display="flex" alignItems="center" gap={2}>
              <Box w={3} h={3} borderRadius="full" bg={GRAPH_COLORS.context} />
              <Text>Contexte</Text>
            </Box>
          </VStack>
        </Box>
      )}

      {/* Stats */}
      <Box
        position="absolute"
        top={2}
        right={2}
        bg="whiteAlpha.900"
        px={2}
        py={1}
        borderRadius="md"
        fontSize="xs"
        color="gray.500"
      >
        {limitedNodes.length} concepts • {limitedEdges.length} relations
      </Box>
    </Box>
  );
}
