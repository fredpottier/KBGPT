'use client'

/**
 * InsightCards — Cards proactives sous la réponse chat V2 (CH-06).
 *
 * 3 types alignés sur le backend `runtime_v2/insight_hints.py` :
 * - `attention` (⚠️ Point d'attention) : vraie contradiction non résolue par lifecycle
 * - `evolution` (📅 Évolution détectée) : LIFECYCLE_RELATION ou conflict résolu par lifecycle
 * - `cross_doc` (🔗 Contexte cross-document) : ≥2 docs autoritaires
 *
 * Bonus CH-06.3 : si une card `attention` est présente, on rend un badge
 * "Mode Audit" en tête pour signaler au compliance officer qu'il y a un point critique.
 */

import { Box, HStack, VStack, Text, Badge, Icon } from '@chakra-ui/react'
import { FiAlertTriangle, FiCalendar, FiLink, FiSearch, FiInfo } from 'react-icons/fi'

export type InsightHint = {
  type: 'attention' | 'evolution' | 'cross_doc' | string
  title?: string
  message: string
  priority?: number
  icon?: 'alert' | 'calendar' | 'link' | string
  action_label?: string | null
  action_href?: string | null
  metadata?: Record<string, any>
}

const STYLE: Record<string, { bg: string; border: string; accent: string; Icon: any; defaultTitle: string }> = {
  attention: {
    bg: 'rgba(239, 68, 68, 0.06)',
    border: 'rgba(239, 68, 68, 0.30)',
    accent: '#ef4444',
    Icon: FiAlertTriangle,
    defaultTitle: 'Point d\'attention',
  },
  evolution: {
    bg: 'rgba(124, 58, 237, 0.06)',
    border: 'rgba(124, 58, 237, 0.30)',
    accent: '#a78bfa',
    Icon: FiCalendar,
    defaultTitle: 'Évolution détectée',
  },
  cross_doc: {
    bg: 'rgba(20, 184, 166, 0.06)',
    border: 'rgba(20, 184, 166, 0.30)',
    accent: '#2dd4bf',
    Icon: FiLink,
    defaultTitle: 'Contexte cross-document',
  },
  default: {
    bg: 'rgba(148, 163, 184, 0.06)',
    border: 'rgba(148, 163, 184, 0.30)',
    accent: '#94a3b8',
    Icon: FiInfo,
    defaultTitle: 'Information',
  },
}

function styleFor(type: string) {
  return STYLE[type] || STYLE.default
}

interface InsightCardsProps {
  hints: InsightHint[]
  showAuditBadge?: boolean
}

export default function InsightCards({ hints, showAuditBadge = true }: InsightCardsProps) {
  if (!hints || hints.length === 0) return null

  const hasAttention = hints.some(h => h.type === 'attention')

  // Trier : attention > evolution > cross_doc, puis par priority (plus petit = plus haut)
  const ordered = [...hints].sort((a, b) => {
    const order = { attention: 0, evolution: 1, cross_doc: 2 } as Record<string, number>
    const oa = order[a.type] ?? 99
    const ob = order[b.type] ?? 99
    if (oa !== ob) return oa - ob
    return (a.priority ?? 99) - (b.priority ?? 99)
  })

  return (
    <VStack align="stretch" spacing={2.5} mt={4}>
      {/* Mode Audit auto badge — apparaît si attention ≥ 1 */}
      {showAuditBadge && hasAttention && (
        <HStack
          spacing={2}
          px={3}
          py={2}
          bg="rgba(239, 68, 68, 0.08)"
          border="1px solid"
          borderColor="rgba(239, 68, 68, 0.40)"
          borderRadius="md"
          alignSelf="flex-start"
        >
          <Icon as={FiSearch} color="#ef4444" boxSize={3.5} />
          <Text fontSize="xs" fontWeight="700" color="#ef4444" textTransform="uppercase" letterSpacing="0.05em">
            Mode Audit · Contradiction(s) détectée(s)
          </Text>
        </HStack>
      )}

      {ordered.map((h, i) => {
        const s = styleFor(h.type)
        return (
          <Box
            key={i}
            p={3.5}
            bg={s.bg}
            border="1px solid"
            borderColor={s.border}
            borderRadius="lg"
            transition="all 0.15s"
            _hover={{ borderColor: s.accent }}
          >
            <HStack align="start" spacing={3}>
              <Box
                p={1.5}
                bg={s.accent + '22'}
                borderRadius="md"
                flexShrink={0}
                mt={0.5}
              >
                <Icon as={s.Icon} color={s.accent} boxSize={3.5} />
              </Box>
              <VStack align="stretch" spacing={1} flex={1} minW={0}>
                <HStack spacing={2}>
                  <Text fontSize="xs" fontWeight="700" color={s.accent} textTransform="uppercase" letterSpacing="0.04em">
                    {h.title || s.defaultTitle}
                  </Text>
                  {h.metadata?.lifecycle_kind && (
                    <Badge fontSize="9px" bg={`${s.accent}22`} color={s.accent} px={1.5} rounded="sm">
                      {h.metadata.lifecycle_kind}
                    </Badge>
                  )}
                </HStack>
                <Text fontSize="sm" color="text.primary" lineHeight="1.5" sx={{ wordBreak: 'break-word' }}>
                  {h.message}
                </Text>
                {h.action_label && h.action_href && (
                  <Text
                    as="a"
                    href={h.action_href}
                    fontSize="xs"
                    color={s.accent}
                    fontWeight="600"
                    mt={1}
                    _hover={{ textDecoration: 'underline' }}
                  >
                    {h.action_label} →
                  </Text>
                )}
              </VStack>
            </HStack>
          </Box>
        )
      })}
    </VStack>
  )
}
