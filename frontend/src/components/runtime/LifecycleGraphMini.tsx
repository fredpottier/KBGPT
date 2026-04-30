'use client'

/**
 * LifecycleGraphMini — graphe lifecycle interactif (ReactFlow + dagre).
 *
 * Layout hiérarchique gauche→droite (dagre rankdir=LR) avec cartes
 * style SAP : titre, doc_id compact, dates. Flèches dans le sens
 * temporel (ancien → récent). Zoom/pan/minimap natifs.
 */

import { useEffect, useState, useMemo, useCallback } from 'react'
import { Box, Spinner, Text, HStack } from '@chakra-ui/react'
import { fetchWithAuth } from '@/lib/fetchWithAuth'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  ReactFlowProvider,
  useReactFlow,
  type Node,
  type Edge,
  type NodeProps,
} from 'reactflow'
import dagre from 'dagre'
import 'reactflow/dist/style.css'

type ApiNode = { id: string; label: string; is_focus: boolean }
type ApiEdge = { from: string; to: string; type: string; confidence: number }
type GraphData = {
  focus_doc_id: string | null
  nodes: ApiNode[]
  edges: ApiEdge[]
  n_nodes?: number
  n_edges?: number
}

type DocCardData = {
  docId: string
  shortId: string
  primarySubject: string
  isFocus: boolean
  publicationDate?: string | null
  onClick: (id: string) => void
}

const TYPE_COLORS: Record<string, string> = {
  SUPERSEDES: '#e53e3e',
  EVOLVES_FROM: '#3182ce',
  REAFFIRMS: '#38a169',
}

// Labels dans le sens temporel inversé (ancien → récent)
// L'API renvoie A SUPERSEDES B (A subject newer, B object older).
// On inverse pour afficher B → A, donc B "est remplacé par" A.
const TYPE_LABELS_INVERTED: Record<string, string> = {
  SUPERSEDES: 'remplacé par',
  EVOLVES_FROM: 'évolue en',
  REAFFIRMS: 'réaffirmé par',
}

const NODE_W = 240
const NODE_H = 110

/** Génère un label court à partir du doc_id en strippant le hash final. */
function shortLabel(docId: string): string {
  const m = docId.match(/^(.*?)_[0-9a-f]{6,}$/)
  const stem = m ? m[1] : docId

  // Pattern EU reg/del : <prefix>_<kind>_<a>_<b>(_original)?
  const eu = stem.match(/^[a-z]+_(\w+)_(\d+)_(\d+)(?:_original)?$/)
  if (eu) {
    const a = eu[2]
    const b = eu[3]
    const aIsYear = a.length === 4 && +a >= 1950 && +a <= 2050
    const bIsYear = b.length === 4 && +b >= 1950 && +b <= 2050
    if (aIsYear && !bIsYear) return `${eu[1]} ${a}/${b}`
    if (bIsYear && !aIsYear) return `${eu[1]} ${b}/${a}`
    return `${eu[1]} ${a}/${b}`
  }
  const cs25 = stem.match(/^cs25_(?:change_)?amdt_(\d+)$/)
  if (cs25) return `CS-25 amdt ${cs25[1]}`
  const simple = stem.replace(/_/g, ' ')
  return simple.length > 26 ? simple.slice(0, 26) + '…' : simple
}

/** Custom node — carte SAP-like. */
function DocCard({ data }: NodeProps<DocCardData>) {
  return (
    <Box
      onClick={() => data.onClick(data.docId)}
      cursor="pointer"
      bg={data.isFocus ? 'blue.700' : 'white'}
      color={data.isFocus ? 'white' : 'gray.800'}
      borderWidth={data.isFocus ? '2px' : '1px'}
      borderColor={data.isFocus ? 'blue.400' : 'gray.300'}
      borderRadius="md"
      boxShadow={data.isFocus ? 'lg' : 'sm'}
      p={3}
      width={`${NODE_W}px`}
      minHeight={`${NODE_H}px`}
      _hover={{ boxShadow: 'md', borderColor: 'blue.400' }}
      transition="all 0.15s"
    >
      <Handle type="target" position={Position.Left} style={{ background: '#888', width: 8, height: 8 }} />
      <Handle type="source" position={Position.Right} style={{ background: '#888', width: 8, height: 8 }} />
      <Text fontSize="sm" fontWeight="bold" lineHeight="1.2" mb={1} noOfLines={2}>
        {data.primarySubject || 'Document'}
      </Text>
      <Text fontSize="xs" fontFamily="mono" color={data.isFocus ? 'blue.100' : 'blue.600'} mb={1}>
        » {data.shortId}
      </Text>
      {data.publicationDate && (
        <Text fontSize="xs" color={data.isFocus ? 'blue.200' : 'gray.500'}>
          Publication : {data.publicationDate}
        </Text>
      )}
      {data.isFocus && (
        <Text fontSize="xs" color="blue.100" fontWeight="bold" mt={1}>
          ⬤ document courant
        </Text>
      )}
    </Box>
  )
}

const NODE_TYPES = { docCard: DocCard }

/** Sous-composant interne qui consomme le contexte ReactFlowProvider. */
function FlowInner({ nodes, edges, showMiniMap }: { nodes: Node[]; edges: Edge[]; showMiniMap: boolean }) {
  const { fitView } = useReactFlow()

  // Force fitView après mount + à chaque changement de nodes (le container Chakra
  // peut avoir une taille 0 au premier render, fitView initial échoue silencieusement).
  useEffect(() => {
    if (nodes.length === 0) return
    const timeouts = [50, 200, 500].map((delay) =>
      setTimeout(() => fitView({ padding: 0.2, duration: delay === 50 ? 0 : 250 }), delay),
    )
    return () => timeouts.forEach(clearTimeout)
  }, [nodes, fitView])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.3}
      maxZoom={1.5}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={16} size={1} color="rgba(128,128,128,0.15)" />
      <Controls showInteractive={false} position="bottom-left" />
      {showMiniMap && (
        <MiniMap
          position="bottom-right"
          nodeColor={(n) => ((n.data as DocCardData)?.isFocus ? '#3182ce' : '#cbd5e0')}
          maskColor="rgba(0,0,0,0.1)"
          pannable
          zoomable
          style={{ width: 160, height: 100 }}
        />
      )}
    </ReactFlow>
  )
}

/** Layout dagre LR avec dimensions fixes. */
function layoutDagre(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 80 })
  g.setDefaultEdgeLabel(() => ({}))

  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }))
  edges.forEach((e) => g.setEdge(e.source, e.target))

  dagre.layout(g)

  const laidOut = nodes.map((n) => {
    const pos = g.node(n.id)
    return {
      ...n,
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
      targetPosition: Position.Left,
      sourcePosition: Position.Right,
    }
  })
  return { nodes: laidOut, edges }
}

export function LifecycleGraphMini({
  focusDocId,
  onNodeClick,
}: {
  focusDocId: string
  onNodeClick?: (docId: string) => void
}) {
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchWithAuth(`/api/runtime_v2/lifecycle_graph?focus_doc_id=${encodeURIComponent(focusDocId)}&depth=1`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((e) => {
        console.error('Graph fetch failed', e)
        if (!cancelled) setData({ focus_doc_id: focusDocId, nodes: [], edges: [] })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [focusDocId])

  const handleNodeClick = useCallback(
    (id: string) => {
      onNodeClick?.(id)
    },
    [onNodeClick],
  )

  const { rfNodes, rfEdges } = useMemo(() => {
    if (!data) return { rfNodes: [], rfEdges: [] }
    const nodes: Node[] = data.nodes.map((n) => ({
      id: n.id,
      type: 'docCard',
      position: { x: 0, y: 0 },
      data: {
        docId: n.id,
        shortId: shortLabel(n.id),
        primarySubject: n.label,
        isFocus: n.is_focus,
        onClick: handleNodeClick,
      } as DocCardData,
    }))
    // INVERSION du sens des flèches : l'API renvoie subject → object (newer → older).
    // On flip pour avoir le sens temporel (older → newer) : source = e.to (older), target = e.from (newer).
    const edges: Edge[] = data.edges.map((e, i) => ({
      id: `e${i}`,
      source: e.to,
      target: e.from,
      label: TYPE_LABELS_INVERTED[e.type] || e.type,
      labelStyle: { fill: TYPE_COLORS[e.type], fontWeight: 600, fontSize: 11 },
      labelBgStyle: { fill: 'white', fillOpacity: 0.85 },
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 3,
      style: {
        stroke: TYPE_COLORS[e.type] || '#888',
        strokeWidth: 2,
      },
      animated: e.type === 'SUPERSEDES',
      markerEnd: {
        type: 'arrowclosed' as const,
        color: TYPE_COLORS[e.type] || '#888',
        width: 18,
        height: 18,
      },
    }))
    const laidOut = layoutDagre(nodes, edges)
    return { rfNodes: laidOut.nodes, rfEdges: laidOut.edges }
  }, [data, handleNodeClick])

  if (loading) {
    return (
      <Box p={4} textAlign="center">
        <Spinner size="sm" />
      </Box>
    )
  }
  if (!data || data.nodes.length === 0) {
    return (
      <Text fontSize="sm" color="var(--fg-muted)" fontStyle="italic">
        Aucune relation lifecycle dans le voisinage de ce document.
      </Text>
    )
  }

  // Affichage MiniMap uniquement quand le voisinage est dense (> 10 nœuds)
  const showMiniMap = rfNodes.length > 10

  return (
    <Box>
      <Box
        h="520px"
        borderWidth="1px"
        borderColor="var(--border)"
        borderRadius="md"
        overflow="hidden"
        bg="var(--bg-page)"
        position="relative"
      >
        <ReactFlowProvider>
          <FlowInner nodes={rfNodes} edges={rfEdges} showMiniMap={showMiniMap} />
        </ReactFlowProvider>
      </Box>
      {/* Légende */}
      <HStack mt={2} spacing={4} fontSize="xs" color="var(--fg-muted)" flexWrap="wrap">
        {Object.entries(TYPE_COLORS).map(([t, c]) => (
          <HStack key={t} spacing={1}>
            <Box as="span" w="14px" h="2px" bg={c} />
            <Text>
              <em>{TYPE_LABELS_INVERTED[t]}</em>
            </Text>
          </HStack>
        ))}
        <Text>·</Text>
        <Text>
          {data.n_nodes ?? data.nodes.length} docs · {data.n_edges ?? data.edges.length} relations · drag/zoom · click sur une carte pour naviguer
        </Text>
      </HStack>
    </Box>
  )
}
