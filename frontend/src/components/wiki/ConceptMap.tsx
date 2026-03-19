'use client'

import { Box, Text, VStack, HStack, Link, Wrap, WrapItem } from '@chakra-ui/react'
import NextLink from 'next/link'
import { useMemo } from 'react'

interface RelatedConcept {
  entity_name: string
  entity_type: string
  co_occurrence_count: number
}

interface ConceptMapProps {
  centralConcept: string
  relatedConcepts: RelatedConcept[]
  maxNodes?: number
}

const TYPE_COLORS: Record<string, { color: string; label: string }> = {
  product: { color: '#818CF8', label: 'Produit' },
  service: { color: '#34D399', label: 'Service' },
  feature: { color: '#FBBF24', label: 'Fonction.' },
  actor: { color: '#F87171', label: 'Acteur' },
  concept: { color: '#60A5FA', label: 'Concept' },
  legal_term: { color: '#A78BFA', label: 'Juridique' },
  standard: { color: '#2DD4BF', label: 'Standard' },
  other: { color: '#9CA3AF', label: 'Autre' },
}

function slugify(name: string): string {
  // Doit correspondre au _slugify() backend (underscores, pas tirets)
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '')
}

export default function ConceptMap({ centralConcept, relatedConcepts, maxNodes = 6 }: ConceptMapProps) {
  const nodes = useMemo(() => relatedConcepts.slice(0, Math.min(maxNodes, 8)), [relatedConcepts, maxNodes])

  // Types présents dans ce graph (pour la légende)
  const usedTypes = useMemo(() => {
    const types = new Set(nodes.map(n => n.entity_type))
    return Array.from(types)
  }, [nodes])

  // Fallback : liste si < 2 relations
  if (nodes.length < 2) {
    return (
      <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
        <Text color="text.muted" fontSize="xs" mb={3} fontWeight="semibold" textTransform="uppercase">
          Concepts liés
        </Text>
        {nodes.length === 0 ? (
          <Text color="text.muted" fontSize="sm">Aucun concept lié détecté</Text>
        ) : (
          <VStack spacing={1} align="stretch">
            {nodes.map((n, i) => (
              <Link key={i} as={NextLink} href={`/wiki/${slugify(n.entity_name)}`} color="brand.300" fontSize="sm" _hover={{ textDecoration: 'underline' }}>
                {n.entity_name}
              </Link>
            ))}
          </VStack>
        )}
      </Box>
    )
  }

  // SVG star graph
  const width = 280
  const height = 220
  const cx = width / 2
  const cy = height / 2
  const radius = 80

  const nodePositions = nodes.map((_, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2
    return {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    }
  })

  return (
    <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
      <Text color="text.muted" fontSize="xs" mb={2} fontWeight="semibold" textTransform="uppercase">
        Concept Map
      </Text>
      <Box position="relative">
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
          {/* Liens */}
          {nodePositions.map((pos, i) => (
            <line
              key={`link-${i}`}
              x1={cx}
              y1={cy}
              x2={pos.x}
              y2={pos.y}
              stroke="#4A5568"
              strokeWidth={1.5}
              opacity={0.6}
            />
          ))}

          {/* Noeud central */}
          <circle cx={cx} cy={cy} r={24} fill="#4338CA" opacity={0.9} />
          <text
            x={cx}
            y={cy}
            textAnchor="middle"
            dominantBaseline="central"
            fill="white"
            fontSize={9}
            fontWeight="bold"
          >
            {centralConcept.length > 12 ? centralConcept.slice(0, 11) + '...' : centralConcept}
          </text>

          {/* Noeuds périphériques */}
          {nodes.map((node, i) => {
            const pos = nodePositions[i]
            const typeInfo = TYPE_COLORS[node.entity_type] || TYPE_COLORS.other
            const label = node.entity_name.length > 14
              ? node.entity_name.slice(0, 13) + '...'
              : node.entity_name
            return (
              <g key={i}>
                <a href={`/wiki/${slugify(node.entity_name)}`}>
                  <circle
                    cx={pos.x}
                    cy={pos.y}
                    r={18}
                    fill={typeInfo.color}
                    opacity={0.8}
                    style={{ cursor: 'pointer' }}
                  />
                  <text
                    x={pos.x}
                    y={pos.y}
                    textAnchor="middle"
                    dominantBaseline="central"
                    fill="white"
                    fontSize={8}
                    style={{ cursor: 'pointer' }}
                  >
                    {label}
                  </text>
                </a>
              </g>
            )
          })}
        </svg>
      </Box>

      {/* Légende */}
      {usedTypes.length > 0 && (
        <Wrap spacing={2} mt={2}>
          {usedTypes.map(t => {
            const info = TYPE_COLORS[t] || TYPE_COLORS.other
            return (
              <WrapItem key={t}>
                <HStack spacing={1}>
                  <Box w="8px" h="8px" rounded="full" bg={info.color} />
                  <Text color="text.muted" fontSize="9px">{info.label}</Text>
                </HStack>
              </WrapItem>
            )
          })}
        </Wrap>
      )}
    </Box>
  )
}
