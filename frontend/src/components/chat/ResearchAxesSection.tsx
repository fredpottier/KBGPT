'use client'

/**
 * 🌊 OSMOSE Phase 3.5 - Research Axes Section
 *
 * Affiche les axes de recherche structurés générés par le ResearchAxesEngine.
 * Design ultra-compact et professionnel.
 */

import {
  Box,
  HStack,
  Text,
  Tooltip,
  Icon,
  Collapse,
  useDisclosure,
  Badge,
  Wrap,
  WrapItem,
} from '@chakra-ui/react'
import {
  ChevronDownIcon,
  ChevronUpIcon,
} from '@chakra-ui/icons'
import { ResearchAxis } from '@/types/api'

// Couleurs pour chaque type d'axe (pas d'icônes - trop gros)
const AXIS_COLORS: Record<string, string> = {
  bridge: 'purple',
  weak_signal: 'orange',
  cluster: 'teal',
  continuity: 'blue',
  unexplored: 'green',
  transitive: 'cyan',
}

interface ResearchAxesSectionProps {
  axes: ResearchAxis[]
  onSearch?: (query: string) => void
}

export default function ResearchAxesSection({
  axes,
  onSearch,
}: ResearchAxesSectionProps) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: false })

  if (!axes || axes.length === 0) {
    return null
  }

  const handleAxisClick = (axis: ResearchAxis) => {
    if (onSearch) {
      onSearch(axis.contextual_question)
    }
  }

  return (
    <Box
      bg="gray.50"
      borderRadius="sm"
      border="1px solid"
      borderColor="gray.200"
      overflow="hidden"
    >
      {/* Header ultra-compact */}
      <HStack
        px={2}
        py={1}
        bg="white"
        borderBottom={isOpen ? "1px solid" : "none"}
        borderColor="gray.200"
        cursor="pointer"
        onClick={onToggle}
        _hover={{ bg: "gray.50" }}
        justify="space-between"
      >
        <HStack spacing={1}>
          <Text fontSize="xs" fontWeight="medium" color="gray.600">
            Pistes de recherche
          </Text>
          <Badge colorScheme="gray" size="sm" fontSize="2xs" variant="subtle">
            {axes.length}
          </Badge>
        </HStack>
        <Icon
          as={isOpen ? ChevronUpIcon : ChevronDownIcon}
          color="gray.400"
          boxSize={3}
        />
      </HStack>

      {/* Content - horizontal wrap layout */}
      <Collapse in={isOpen}>
        <Wrap spacing={1} p={1.5}>
          {axes.slice(0, 6).map((axis) => (
            <WrapItem key={axis.axis_id}>
              <ResearchAxisChip
                axis={axis}
                onClick={() => handleAxisClick(axis)}
              />
            </WrapItem>
          ))}
        </Wrap>
      </Collapse>
    </Box>
  )
}

interface ResearchAxisChipProps {
  axis: ResearchAxis
  onClick: () => void
}

/**
 * Chip ultra-compact pour un axe de recherche
 * Affiche juste le titre tronqué, cliquable
 */
function ResearchAxisChip({ axis, onClick }: ResearchAxisChipProps) {
  const colorScheme = AXIS_COLORS[axis.axis_type] || 'gray'

  return (
    <Tooltip
      label={axis.contextual_question}
      placement="top"
      hasArrow
      fontSize="xs"
    >
      <Badge
        colorScheme={colorScheme}
        variant="subtle"
        px={2}
        py={0.5}
        borderRadius="full"
        cursor="pointer"
        fontSize="2xs"
        fontWeight="normal"
        _hover={{
          bg: `${colorScheme}.100`,
        }}
        onClick={onClick}
        maxW="180px"
        isTruncated
      >
        {truncateQuestion(axis.title, 25)}
      </Badge>
    </Tooltip>
  )
}

/**
 * Tronque une question pour l'affichage dans le bouton
 */
function truncateQuestion(question: string, maxLength: number): string {
  if (question.length <= maxLength) {
    return question
  }
  // Trouver le dernier espace avant maxLength
  const truncated = question.substring(0, maxLength)
  const lastSpace = truncated.lastIndexOf(' ')
  if (lastSpace > maxLength * 0.5) {
    return truncated.substring(0, lastSpace) + '...'
  }
  return truncated + '...'
}
