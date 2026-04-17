'use client'

/**
 * Panneau actionables : top docs mal extraits, top hubs, singletons, perspective.
 */

import {
  Box,
  Text,
  HStack,
  VStack,
  SimpleGrid,
  Badge,
  Icon,
  Progress,
  Button,
} from '@chakra-ui/react'
import {
  FiFileText,
  FiTarget,
  FiGitBranch,
  FiClock,
  FiChevronRight,
} from 'react-icons/fi'
import { ActionablesPanel as ActionablesPanelData, zoneColor } from './types'

function formatDocId(docId: string): string {
  let label = docId
  if (label.includes('_')) {
    const parts = label.split('_')
    if (parts.length > 2 && parts[parts.length - 1].length >= 8) parts.pop()
    label = parts.join(' ')
    if (label.length > 48) label = label.slice(0, 45) + '...'
  }
  return label
}

const PERSPECTIVE_MAP: Record<string, { zone: 'green' | 'yellow' | 'red'; label: string }> = {
  fresh: { zone: 'green', label: 'A jour' },
  warning: { zone: 'yellow', label: 'A rafraichir' },
  stale: { zone: 'red', label: 'Obsolete' },
  no_perspectives: { zone: 'red', label: 'Aucune Perspective' },
  unknown: { zone: 'yellow', label: 'Inconnu' },
}

interface Props {
  data: ActionablesPanelData
  onDrilldown: (key: string) => void
}

export function ActionablesPanel({ data, onDrilldown }: Props) {
  const perspectiveInfo = data.perspective_status
    ? PERSPECTIVE_MAP[data.perspective_status] ?? PERSPECTIVE_MAP.unknown
    : null

  return (
    <Box mt={6}>
      <Text
        fontSize="xs"
        color="var(--text-muted)"
        textTransform="uppercase"
        letterSpacing="wide"
        mb={3}
      >
        Actionables
      </Text>

      <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={4} mb={4}>
        {/* Worst docs */}
        <Box
          bg="var(--bg-secondary)"
          borderRadius="xl"
          p={5}
          borderWidth="1px"
          borderColor="var(--border-default)"
        >
          <HStack justify="space-between" mb={3}>
            <HStack spacing={2}>
              <Icon as={FiFileText} color="red.400" boxSize={4} />
              <Text fontSize="sm" fontWeight="600" color="var(--text-primary)">
                Documents mal extraits
              </Text>
            </HStack>
            <Button
              size="xs"
              variant="ghost"
              color="brand.300"
              onClick={() => onDrilldown('worst_docs')}
              rightIcon={<Icon as={FiChevronRight} boxSize={3} />}
            >
              Tout voir
            </Button>
          </HStack>

          {data.worst_docs.length === 0 ? (
            <Text fontSize="sm" color="var(--text-muted)">
              Aucun document detecte.
            </Text>
          ) : (
            <VStack spacing={2} align="stretch">
              {data.worst_docs.slice(0, 5).map((d) => (
                <Box key={d.doc_id}>
                  <HStack justify="space-between" mb={1}>
                    <Text fontSize="xs" color="var(--text-primary)" noOfLines={1} flex={1}>
                      {formatDocId(d.doc_id)}
                    </Text>
                    <HStack spacing={2}>
                      <Badge fontSize="2xs" variant="outline" colorScheme="gray">
                        {d.claims_total} claims
                      </Badge>
                      <Badge
                        fontSize="2xs"
                        colorScheme={d.linkage_rate < 0.1 ? 'red' : d.linkage_rate < 0.3 ? 'orange' : 'yellow'}
                      >
                        {(d.linkage_rate * 100).toFixed(0)}% linkage
                      </Badge>
                    </HStack>
                  </HStack>
                  <Progress
                    value={d.linkage_rate * 100}
                    size="xs"
                    borderRadius="full"
                    bg="var(--bg-primary)"
                    colorScheme={d.linkage_rate < 0.1 ? 'red' : d.linkage_rate < 0.3 ? 'orange' : 'yellow'}
                  />
                </Box>
              ))}
            </VStack>
          )}
        </Box>

        {/* Top hubs */}
        <Box
          bg="var(--bg-secondary)"
          borderRadius="xl"
          p={5}
          borderWidth="1px"
          borderColor="var(--border-default)"
        >
          <HStack justify="space-between" mb={3}>
            <HStack spacing={2}>
              <Icon as={FiTarget} color="orange.400" boxSize={4} />
              <Text fontSize="sm" fontWeight="600" color="var(--text-primary)">
                Entites dominantes
              </Text>
            </HStack>
            <Button
              size="xs"
              variant="ghost"
              color="brand.300"
              onClick={() => onDrilldown('top_hubs')}
              rightIcon={<Icon as={FiChevronRight} boxSize={3} />}
            >
              Tout voir
            </Button>
          </HStack>

          {data.top_hubs.length === 0 ? (
            <Text fontSize="sm" color="var(--text-muted)">
              Aucun hub notable.
            </Text>
          ) : (
            <VStack spacing={2} align="stretch">
              {data.top_hubs.slice(0, 5).map((h) => (
                <HStack key={h.entity} justify="space-between" py={1}>
                  <Text fontSize="xs" color="var(--text-primary)" noOfLines={1} flex={1}>
                    {h.entity}
                  </Text>
                  <HStack spacing={2}>
                    <Text fontSize="2xs" color="var(--text-muted)">
                      {h.claims} claims
                    </Text>
                    <Badge
                      fontSize="2xs"
                      colorScheme={h.share_pct > 15 ? 'red' : h.share_pct > 5 ? 'orange' : 'gray'}
                    >
                      {h.share_pct.toFixed(1)}%
                    </Badge>
                  </HStack>
                </HStack>
              ))}
            </VStack>
          )}
        </Box>
      </SimpleGrid>

      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
        {/* Singletons / composantes */}
        {data.singleton_stats && (
          <Box
            bg="var(--bg-secondary)"
            borderRadius="xl"
            p={5}
            borderWidth="1px"
            borderColor="var(--border-default)"
          >
            <HStack spacing={2} mb={3}>
              <Icon as={FiGitBranch} color="purple.400" boxSize={4} />
              <Text fontSize="sm" fontWeight="600" color="var(--text-primary)">
                Fragmentation du graphe
              </Text>
            </HStack>

            <SimpleGrid columns={2} spacing={3}>
              <Box>
                <Text fontSize="xs" color="var(--text-muted)">
                  Composante geante
                </Text>
                <Text fontSize="lg" fontWeight="700" color="var(--text-primary)">
                  {data.singleton_stats.giant_component_pct.toFixed(1)}%
                </Text>
                <Text fontSize="2xs" color="var(--text-muted)">
                  {data.singleton_stats.giant_component_size.toLocaleString()} nodes
                </Text>
              </Box>
              <Box>
                <Text fontSize="xs" color="var(--text-muted)">
                  Singletons isoles
                </Text>
                <Text fontSize="lg" fontWeight="700" color="orange.400">
                  {data.singleton_stats.singletons.toLocaleString()}
                </Text>
                <Text fontSize="2xs" color="var(--text-muted)">
                  / {data.singleton_stats.total_components} composantes
                </Text>
              </Box>
            </SimpleGrid>
          </Box>
        )}

        {/* Perspective */}
        {perspectiveInfo && (
          <Box
            bg="var(--bg-secondary)"
            borderRadius="xl"
            p={5}
            borderWidth="1px"
            borderColor="var(--border-default)"
          >
            <HStack spacing={2} mb={3}>
              <Icon as={FiClock} color={zoneColor(perspectiveInfo.zone)} boxSize={4} />
              <Text fontSize="sm" fontWeight="600" color="var(--text-primary)">
                Couche Perspective
              </Text>
            </HStack>

            <HStack justify="space-between" align="start">
              <VStack align="start" spacing={0.5}>
                <Text
                  fontSize="lg"
                  fontWeight="700"
                  color={zoneColor(perspectiveInfo.zone)}
                >
                  {perspectiveInfo.label}
                </Text>
                <Text fontSize="xs" color="var(--text-muted)">
                  {data.perspective_new_claims} claims non integrees
                </Text>
              </VStack>
              <Badge colorScheme={perspectiveInfo.zone === 'green' ? 'green' : perspectiveInfo.zone === 'yellow' ? 'orange' : 'red'}>
                {data.perspective_status}
              </Badge>
            </HStack>
          </Box>
        )}
      </SimpleGrid>
    </Box>
  )
}
