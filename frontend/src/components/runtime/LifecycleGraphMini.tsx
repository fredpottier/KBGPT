'use client'

/**
 * LifecycleGraphMini — SVG mini graph pour LIFECYCLE_RELATION (P5 polish #4).
 *
 * Layout radial simple : focus_doc au centre, voisins en cercle autour.
 * Pas de force-directed (gardé minimal pour rester rapide à charger).
 */

import { useEffect, useState } from 'react'
import { Box, Spinner, Text, Tooltip } from '@chakra-ui/react'
import { fetchWithAuth } from '@/lib/fetchWithAuth'

type GraphNode = { id: string; label: string; is_focus: boolean }
type GraphEdge = { from: string; to: string; type: string; confidence: number }
type GraphData = { focus_doc_id: string | null; nodes: GraphNode[]; edges: GraphEdge[] }

const TYPE_COLORS: Record<string, string> = {
  SUPERSEDES: '#e53e3e',
  EVOLVES_FROM: '#3182ce',
  REAFFIRMS: '#38a169',
}

const W = 480
const H = 320

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

  if (loading) {
    return (
      <Box p={4} textAlign="center">
        <Spinner size="sm" />
      </Box>
    )
  }
  if (!data || data.nodes.length === 0) {
    return (
      <Text fontSize="sm" color="var(--fg-muted)">
        Aucune relation lifecycle dans le voisinage.
      </Text>
    )
  }

  // Layout radial : focus au centre, autres autour
  const focus = data.nodes.find((n) => n.is_focus) || data.nodes[0]
  const others = data.nodes.filter((n) => n.id !== focus.id)
  const cx = W / 2
  const cy = H / 2
  const radius = Math.min(W, H) / 2 - 50

  const positions: Record<string, { x: number; y: number }> = {
    [focus.id]: { x: cx, y: cy },
  }
  others.forEach((n, i) => {
    const angle = (i / others.length) * 2 * Math.PI - Math.PI / 2
    positions[n.id] = {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    }
  })

  return (
    <Box>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ background: 'var(--bg-page)', borderRadius: 8 }}>
        <defs>
          <marker id="arrow-supersedes" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={TYPE_COLORS.SUPERSEDES} />
          </marker>
          <marker id="arrow-evolves" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={TYPE_COLORS.EVOLVES_FROM} />
          </marker>
          <marker id="arrow-reaffirms" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={TYPE_COLORS.REAFFIRMS} />
          </marker>
        </defs>

        {/* Edges */}
        {data.edges.map((e, i) => {
          const p1 = positions[e.from]
          const p2 = positions[e.to]
          if (!p1 || !p2) return null
          const color = TYPE_COLORS[e.type] || '#888'
          const markerId =
            e.type === 'SUPERSEDES' ? 'arrow-supersedes' : e.type === 'EVOLVES_FROM' ? 'arrow-evolves' : 'arrow-reaffirms'
          return (
            <g key={i}>
              <line
                x1={p1.x}
                y1={p1.y}
                x2={p2.x}
                y2={p2.y}
                stroke={color}
                strokeWidth={1 + e.confidence * 2}
                opacity={0.6}
                markerEnd={`url(#${markerId})`}
              />
            </g>
          )
        })}

        {/* Nodes */}
        {data.nodes.map((n) => {
          const p = positions[n.id]
          if (!p) return null
          return (
            <g
              key={n.id}
              transform={`translate(${p.x},${p.y})`}
              style={{ cursor: 'pointer' }}
              onClick={() => onNodeClick?.(n.id)}
            >
              <title>{n.id}</title>
              <circle
                r={n.is_focus ? 16 : 12}
                fill={n.is_focus ? 'var(--accent-base)' : 'var(--bg-surface)'}
                stroke="var(--fg)"
                strokeWidth={n.is_focus ? 2 : 1}
              />
              <text
                y={n.is_focus ? 30 : 26}
                textAnchor="middle"
                fontSize={10}
                fill="var(--fg)"
                style={{ pointerEvents: 'none' }}
              >
                {n.label.length > 28 ? n.label.slice(0, 28) + '…' : n.label}
              </text>
            </g>
          )
        })}
      </svg>
      <Text fontSize="xs" color="var(--fg-muted)" mt={1}>
        {data.n_nodes} docs · {data.n_edges} relations · click sur un doc pour drill-down
      </Text>
    </Box>
  )
}
