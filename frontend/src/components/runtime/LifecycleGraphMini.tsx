'use client'

/**
 * LifecycleGraphMini — SVG mini graph pour LIFECYCLE_RELATION.
 *
 * Layout radial : focus au centre, voisins en cercle. Avec arrowheads,
 * légende des types, et labels courts dérivés du doc_id pour éviter
 * les ambiguïtés visuelles (plusieurs docs partagent souvent le même
 * primary_subject).
 */

import { useEffect, useState } from 'react'
import { Box, Spinner, Text, HStack } from '@chakra-ui/react'
import { fetchWithAuth } from '@/lib/fetchWithAuth'

type GraphNode = { id: string; label: string; is_focus: boolean }
type GraphEdge = { from: string; to: string; type: string; confidence: number }
type GraphData = { focus_doc_id: string | null; nodes: GraphNode[]; edges: GraphEdge[]; n_nodes?: number; n_edges?: number }

const TYPE_COLORS: Record<string, string> = {
  SUPERSEDES: '#e53e3e',
  EVOLVES_FROM: '#3182ce',
  REAFFIRMS: '#38a169',
}
const TYPE_LABELS: Record<string, string> = {
  SUPERSEDES: 'remplace',
  EVOLVES_FROM: 'évolue depuis',
  REAFFIRMS: 'réaffirme',
}

const W = 640
const H = 380
const NODE_R = 14
const FOCUS_R = 18

/** Génère un label compact à partir du doc_id en strippant le hash final. */
function shortLabel(docId: string): string {
  const m = docId.match(/^(.*?)_[0-9a-f]{6,}$/)
  return (m ? m[1] : docId).replace(/_/g, ' ')
}

/** Raccourcit une ligne en p1->p2 pour s'arrêter avant l'extrémité (laisse de la place à l'arrowhead). */
function shortenLine(p1: { x: number; y: number }, p2: { x: number; y: number }, offset: number) {
  const dx = p2.x - p1.x
  const dy = p2.y - p1.y
  const len = Math.sqrt(dx * dx + dy * dy)
  if (len === 0) return p2
  return {
    x: p2.x - (dx / len) * offset,
    y: p2.y - (dy / len) * offset,
  }
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

  // Layout radial
  const focus = data.nodes.find((n) => n.is_focus) || data.nodes[0]
  const others = data.nodes.filter((n) => n.id !== focus.id)
  const cx = W / 2
  const cy = H / 2 - 10
  const radius = Math.min(W, H) / 2 - 90

  const positions: Record<string, { x: number; y: number }> = {
    [focus.id]: { x: cx, y: cy },
  }
  others.forEach((n, i) => {
    const angle = (i / Math.max(1, others.length)) * 2 * Math.PI - Math.PI / 2
    positions[n.id] = {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    }
  })

  return (
    <Box>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} style={{ background: 'var(--bg-page)', borderRadius: 8 }}>
        <defs>
          {Object.entries(TYPE_COLORS).map(([t, c]) => (
            <marker
              key={t}
              id={`arrow-${t}`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={c} />
            </marker>
          ))}
        </defs>

        {/* Edges */}
        {data.edges.map((e, i) => {
          const p1 = positions[e.from]
          const p2raw = positions[e.to]
          if (!p1 || !p2raw) return null
          const targetIsFocus = e.to === focus.id
          const sourceIsFocus = e.from === focus.id
          // Raccourcir aux extrémités pour ne pas plonger sous les nodes
          const targetR = targetIsFocus ? FOCUS_R : NODE_R
          const sourceR = sourceIsFocus ? FOCUS_R : NODE_R
          const p2 = shortenLine(p1, p2raw, targetR + 3)
          const p1adj = shortenLine(p2raw, p1, sourceR + 3)
          const color = TYPE_COLORS[e.type] || '#888'
          const mid = { x: (p1adj.x + p2.x) / 2, y: (p1adj.y + p2.y) / 2 }
          return (
            <g key={i}>
              <line
                x1={p1adj.x}
                y1={p1adj.y}
                x2={p2.x}
                y2={p2.y}
                stroke={color}
                strokeWidth={2}
                opacity={0.85}
                markerEnd={`url(#arrow-${e.type})`}
              />
              {/* Étiquette type sur le milieu de l'arête */}
              <text
                x={mid.x}
                y={mid.y - 4}
                textAnchor="middle"
                fontSize={10}
                fill={color}
                fontWeight="bold"
                style={{ pointerEvents: 'none' }}
              >
                {TYPE_LABELS[e.type] || e.type}
              </text>
            </g>
          )
        })}

        {/* Nodes */}
        {data.nodes.map((n) => {
          const p = positions[n.id]
          if (!p) return null
          const isFocus = n.is_focus
          const r = isFocus ? FOCUS_R : NODE_R
          // Position label : focus en bas, autres rayonnent
          const labelDy = isFocus ? r + 16 : r + 14
          return (
            <g
              key={n.id}
              transform={`translate(${p.x},${p.y})`}
              style={{ cursor: 'pointer' }}
              onClick={() => onNodeClick?.(n.id)}
            >
              <title>
                {n.id}
                {'\n'}
                {n.label}
              </title>
              <circle
                r={r}
                fill={isFocus ? '#3182ce' : 'var(--bg-surface)'}
                stroke={isFocus ? '#1e4e8c' : 'var(--fg-muted)'}
                strokeWidth={isFocus ? 3 : 1.5}
              />
              {isFocus && (
                <text textAnchor="middle" dy={4} fontSize={11} fontWeight="bold" fill="white" style={{ pointerEvents: 'none' }}>
                  ICI
                </text>
              )}
              <text
                y={labelDy}
                textAnchor="middle"
                fontSize={11}
                fontWeight={isFocus ? 'bold' : 'normal'}
                fill="var(--fg)"
                style={{ pointerEvents: 'none' }}
              >
                {shortLabel(n.id)}
              </text>
            </g>
          )
        })}
      </svg>
      {/* Légende */}
      <HStack mt={2} spacing={4} fontSize="xs" color="var(--fg-muted)" flexWrap="wrap">
        {Object.entries(TYPE_COLORS).map(([t, c]) => (
          <HStack key={t} spacing={1}>
            <Box as="span" w="12px" h="2px" bg={c} />
            <Text>
              {t} <em>({TYPE_LABELS[t]})</em>
            </Text>
          </HStack>
        ))}
        <Text>·</Text>
        <Text>
          {data.n_nodes ?? data.nodes.length} docs · {data.n_edges ?? data.edges.length} relations · click pour naviguer
        </Text>
      </HStack>
    </Box>
  )
}
