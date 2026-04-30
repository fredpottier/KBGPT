'use client'

/**
 * LifecycleGraphMini — SVG mini graph pour LIFECYCLE_RELATION.
 *
 * Layout radial : focus au centre (cercle bleu "ICI"), voisins en cercle.
 * Labels positionnés radialement avec textAnchor adapté à l'angle pour
 * éviter le chevauchement. Edge labels offset perpendiculaire.
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
const H = 420
const NODE_R = 14
const FOCUS_R = 22

/** Génère un label court à partir du doc_id en strippant le hash final. */
function shortLabel(docId: string): string {
  const m = docId.match(/^(.*?)_[0-9a-f]{6,}$/)
  const stem = m ? m[1] : docId

  // Pattern EU reg/del : <prefix>_<kind>_<a>_<b>(_original)?
  // Convention EU post-Lisbon : année/numéro (ex 2021/821)
  // Convention EC antérieure : numéro/année (ex 428/2009)
  // → on détecte l'année par sa magnitude (4 chiffres, 1950-2050)
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
  // Pattern CS-25 : cs25_(change_)?amdt_<num>
  const cs25 = stem.match(/^cs25_(?:change_)?amdt_(\d+)$/)
  if (cs25) {
    return `CS-25 amdt ${cs25[1]}`
  }
  // Fallback : underscores → espaces, max 26 chars
  const simple = stem.replace(/_/g, ' ')
  return simple.length > 26 ? simple.slice(0, 26) + '…' : simple
}

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

  const focus = data.nodes.find((n) => n.is_focus) || data.nodes[0]
  const others = data.nodes.filter((n) => n.id !== focus.id)
  const cx = W / 2
  const cy = H / 2
  const radius = Math.min(W, H) / 2 - 110

  // Stocker l'angle pour chaque voisin (sert au placement de label)
  const positions: Record<string, { x: number; y: number; angle: number }> = {
    [focus.id]: { x: cx, y: cy, angle: 0 },
  }
  others.forEach((n, i) => {
    const angle = (i / Math.max(1, others.length)) * 2 * Math.PI - Math.PI / 2
    positions[n.id] = {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
      angle,
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
              markerWidth="8"
              markerHeight="8"
              orient="auto"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={c} />
            </marker>
          ))}
          {/* Halo blanc pour les labels d'arête (lisibilité sur fond) */}
          <filter id="label-bg" x="-10%" y="-10%" width="120%" height="120%">
            <feFlood floodColor="var(--bg-page)" floodOpacity="0.85" />
            <feComposite in="SourceGraphic" operator="over" />
          </filter>
        </defs>

        {/* Edges (avec label perpendiculaire) */}
        {data.edges.map((e, i) => {
          const p1raw = positions[e.from]
          const p2raw = positions[e.to]
          if (!p1raw || !p2raw) return null
          const targetIsFocus = e.to === focus.id
          const sourceIsFocus = e.from === focus.id
          const targetR = targetIsFocus ? FOCUS_R : NODE_R
          const sourceR = sourceIsFocus ? FOCUS_R : NODE_R
          const p2 = shortenLine(p1raw, p2raw, targetR + 4)
          const p1 = shortenLine(p2raw, p1raw, sourceR + 4)
          const color = TYPE_COLORS[e.type] || '#888'
          // Milieu et normale perpendiculaire pour décaler le label hors de l'arête
          const dx = p2.x - p1.x
          const dy = p2.y - p1.y
          const len = Math.sqrt(dx * dx + dy * dy) || 1
          const nx = -dy / len
          const ny = dx / len
          const offset = 12
          const labelX = (p1.x + p2.x) / 2 + nx * offset
          const labelY = (p1.y + p2.y) / 2 + ny * offset
          return (
            <g key={i}>
              <line
                x1={p1.x}
                y1={p1.y}
                x2={p2.x}
                y2={p2.y}
                stroke={color}
                strokeWidth={2}
                opacity={0.9}
                markerEnd={`url(#arrow-${e.type})`}
              />
              {/* Halo de fond pour lisibilité */}
              <rect
                x={labelX - 36}
                y={labelY - 8}
                width={72}
                height={14}
                fill="var(--bg-page)"
                opacity={0.85}
                rx={3}
              />
              <text
                x={labelX}
                y={labelY + 3}
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
          // Label des voisins : décalé radialement vers l'extérieur
          let labelX = 0
          let labelY = 0
          let textAnchor: 'start' | 'middle' | 'end' = 'middle'
          if (!isFocus) {
            const dist = r + 8
            labelX = Math.cos(p.angle) * dist
            labelY = Math.sin(p.angle) * dist + 4
            // Anchor selon quadrant
            if (Math.cos(p.angle) > 0.3) textAnchor = 'start'
            else if (Math.cos(p.angle) < -0.3) textAnchor = 'end'
            else textAnchor = 'middle'
          }
          return (
            <g
              key={n.id}
              transform={`translate(${p.x},${p.y})`}
              style={{ cursor: 'pointer' }}
              onClick={() => onNodeClick?.(n.id)}
            >
              <title>
                {n.id} — {n.label}
              </title>
              <circle
                r={r}
                fill={isFocus ? '#3182ce' : 'var(--bg-surface)'}
                stroke={isFocus ? '#1e4e8c' : 'var(--fg-muted)'}
                strokeWidth={isFocus ? 3 : 1.5}
              />
              {isFocus && (
                <text
                  textAnchor="middle"
                  dy={4}
                  fontSize={12}
                  fontWeight="bold"
                  fill="white"
                  style={{ pointerEvents: 'none' }}
                >
                  ICI
                </text>
              )}
              {!isFocus && (
                <text
                  x={labelX}
                  y={labelY}
                  textAnchor={textAnchor}
                  fontSize={11}
                  fill="var(--fg)"
                  style={{ pointerEvents: 'none' }}
                >
                  {shortLabel(n.id)}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      {/* Légende */}
      <HStack mt={2} spacing={4} fontSize="xs" color="var(--fg-muted)" flexWrap="wrap">
        {Object.entries(TYPE_COLORS).map(([t, c]) => (
          <HStack key={t} spacing={1}>
            <Box as="span" w="14px" h="2px" bg={c} />
            <Text>
              <em>{TYPE_LABELS[t]}</em>
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
