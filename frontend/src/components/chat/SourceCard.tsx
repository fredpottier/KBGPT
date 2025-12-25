'use client'

/**
 * OSMOS Source Card - Dark Elegance Edition
 *
 * Premium source display with dark theme
 */

import { memo, useCallback } from 'react'
import {
  Box,
  HStack,
  VStack,
  Text,
  Icon,
  Tooltip,
  Collapse,
  useDisclosure,
  IconButton,
} from '@chakra-ui/react'
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ExternalLinkIcon,
  AttachmentIcon,
} from '@chakra-ui/icons'
import { motion } from 'framer-motion'

const MotionBox = motion(Box)

// Document type colors for dark theme
const DOC_TYPE_CONFIG: Record<string, { color: string; bg: string; label: string }> = {
  PDF: { color: 'red.400', bg: 'rgba(239, 68, 68, 0.15)', label: 'PDF' },
  PPTX: { color: 'orange.400', bg: 'rgba(251, 146, 60, 0.15)', label: 'PPTX' },
  DOCX: { color: 'blue.400', bg: 'rgba(96, 165, 250, 0.15)', label: 'DOCX' },
  XLSX: { color: 'green.400', bg: 'rgba(34, 197, 94, 0.15)', label: 'XLSX' },
  TXT: { color: 'gray.400', bg: 'rgba(156, 163, 175, 0.15)', label: 'TXT' },
  MD: { color: 'purple.400', bg: 'rgba(192, 132, 252, 0.15)', label: 'MD' },
  DEFAULT: { color: 'gray.400', bg: 'rgba(156, 163, 175, 0.15)', label: 'DOC' },
}

export interface Source {
  document_id?: string
  document_name: string
  document_type?: string
  chunk_id?: string
  text?: string
  excerpt?: string
  score?: number
  page_number?: number
  slide_number?: number
  confidence?: number
}

interface SourceCardProps {
  source: Source
  index?: number
  onSourceClick?: (source: Source) => void
  isCompact?: boolean
  highlightTerms?: string[]
}

/**
 * Highlight search terms in text
 */
function highlightText(text: string, terms: string[]): React.ReactNode {
  if (!terms || terms.length === 0) return text

  const regex = new RegExp(`(${terms.join('|')})`, 'gi')
  const parts = text.split(regex)

  return parts.map((part, i) => {
    const isMatch = terms.some(
      (term) => part.toLowerCase() === term.toLowerCase()
    )
    if (isMatch) {
      return (
        <Text
          as="mark"
          key={i}
          bg="rgba(99, 102, 241, 0.3)"
          color="brand.300"
          px={0.5}
          borderRadius="sm"
        >
          {part}
        </Text>
      )
    }
    return part
  })
}

/**
 * Get display config for document type
 */
function getDocTypeConfig(type?: string) {
  if (!type) return DOC_TYPE_CONFIG.DEFAULT
  const upperType = type.toUpperCase()
  return DOC_TYPE_CONFIG[upperType] || DOC_TYPE_CONFIG.DEFAULT
}

/**
 * Source Card - Displays a source with rich formatting
 */
function SourceCardComponent({
  source,
  index = 0,
  onSourceClick,
  isCompact = false,
  highlightTerms = [],
}: SourceCardProps) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: !isCompact })
  const docConfig = getDocTypeConfig(source.document_type)

  const handleClick = useCallback(() => {
    onSourceClick?.(source)
  }, [onSourceClick, source])

  // Text to display
  const displayText = source.excerpt || source.text || ''
  const hasText = displayText.length > 0

  // Location (page or slide)
  const location = source.slide_number
    ? `Slide ${source.slide_number}`
    : source.page_number
    ? `Page ${source.page_number}`
    : null

  // Formatted score
  const scoreValue = source.score || source.confidence || 0
  const scoreDisplay = scoreValue > 0 ? `${Math.round(scoreValue * 100)}%` : null

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return { color: 'green.400', bg: 'rgba(34, 197, 94, 0.15)' }
    if (score >= 0.5) return { color: 'yellow.400', bg: 'rgba(250, 204, 21, 0.15)' }
    return { color: 'gray.400', bg: 'rgba(156, 163, 175, 0.15)' }
  }

  return (
    <MotionBox
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      w="full"
    >
      <Box
        bg="bg.secondary"
        borderRadius="lg"
        border="1px solid"
        borderColor="border.default"
        overflow="hidden"
        _hover={{ borderColor: 'border.active' }}
        transition="all 0.2s"
      >
        {/* Header */}
        <HStack
          px={3}
          py={2.5}
          bg="bg.tertiary"
          borderBottom={isOpen && hasText ? '1px solid' : 'none'}
          borderColor="border.default"
          justify="space-between"
          cursor="pointer"
          onClick={hasText ? onToggle : handleClick}
        >
          <HStack spacing={2} flex="1" minW={0}>
            {/* Type icon */}
            <Box
              w={7}
              h={7}
              rounded="md"
              bg={docConfig.bg}
              display="flex"
              alignItems="center"
              justifyContent="center"
            >
              <Icon as={AttachmentIcon} boxSize={3.5} color={docConfig.color} />
            </Box>

            {/* Type badge */}
            <HStack
              px={2}
              py={0.5}
              bg={docConfig.bg}
              rounded="md"
              spacing={1}
            >
              <Text fontSize="xs" fontWeight="medium" color={docConfig.color}>
                {docConfig.label}
              </Text>
            </HStack>

            {/* Document name */}
            <Text
              fontSize="sm"
              fontWeight="medium"
              color="text.primary"
              noOfLines={1}
              flex="1"
            >
              {source.document_name}
            </Text>

            {/* Location */}
            {location && (
              <HStack
                px={2}
                py={0.5}
                bg="bg.primary"
                border="1px solid"
                borderColor="border.default"
                rounded="md"
              >
                <Text fontSize="xs" color="text.muted">
                  {location}
                </Text>
              </HStack>
            )}
          </HStack>

          <HStack spacing={2}>
            {/* Score */}
            {scoreDisplay && (
              <Tooltip label="Score de pertinence" bg="bg.tertiary" color="text.primary">
                <HStack
                  px={2}
                  py={0.5}
                  bg={getScoreColor(scoreValue).bg}
                  rounded="md"
                >
                  <Text fontSize="xs" fontWeight="medium" color={getScoreColor(scoreValue).color}>
                    {scoreDisplay}
                  </Text>
                </HStack>
              </Tooltip>
            )}

            {/* Expand/link button */}
            {hasText ? (
              <IconButton
                aria-label={isOpen ? 'Reduire' : 'Developper'}
                icon={isOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}
                size="xs"
                variant="ghost"
                color="text.muted"
                _hover={{ bg: 'bg.hover', color: 'text.primary' }}
                onClick={(e) => {
                  e.stopPropagation()
                  onToggle()
                }}
              />
            ) : (
              <Tooltip label="Ouvrir le document" bg="bg.tertiary" color="text.primary">
                <IconButton
                  aria-label="Ouvrir"
                  icon={<ExternalLinkIcon />}
                  size="xs"
                  variant="ghost"
                  color="text.muted"
                  _hover={{ bg: 'bg.hover', color: 'brand.400' }}
                  onClick={(e) => {
                    e.stopPropagation()
                    handleClick()
                  }}
                />
              </Tooltip>
            )}
          </HStack>
        </HStack>

        {/* Content (excerpt) */}
        {hasText && (
          <Collapse in={isOpen}>
            <Box px={3} py={3}>
              <Text
                fontSize="sm"
                color="text.secondary"
                lineHeight="tall"
                noOfLines={isCompact ? 3 : undefined}
              >
                {highlightText(displayText, highlightTerms)}
              </Text>

              {/* Link to document */}
              {onSourceClick && (
                <Text
                  fontSize="xs"
                  color="brand.400"
                  mt={3}
                  cursor="pointer"
                  _hover={{ color: 'brand.300' }}
                  onClick={handleClick}
                  transition="color 0.2s"
                >
                  Voir le document source →
                </Text>
              )}
            </Box>
          </Collapse>
        )}
      </Box>
    </MotionBox>
  )
}

export const SourceCard = memo(SourceCardComponent)

/**
 * Sources List - List of sources
 */
interface SourcesListProps {
  sources: Source[]
  onSourceClick?: (source: Source) => void
  maxVisible?: number
  isCompact?: boolean
  highlightTerms?: string[]
  title?: string
}

function SourcesListComponent({
  sources,
  onSourceClick,
  maxVisible = 3,
  isCompact = false,
  highlightTerms = [],
  title = 'Sources',
}: SourcesListProps) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: false })

  if (!sources || sources.length === 0) return null

  const visibleSources = isOpen ? sources : sources.slice(0, maxVisible)
  const hasMore = sources.length > maxVisible

  return (
    <VStack align="stretch" spacing={3} w="full">
      {/* Header */}
      <HStack justify="space-between">
        <HStack spacing={2}>
          <Text fontSize="sm" fontWeight="semibold" color="text.primary">
            {title}
          </Text>
          <HStack
            px={2}
            py={0.5}
            bg="rgba(99, 102, 241, 0.15)"
            rounded="full"
          >
            <Text fontSize="xs" fontWeight="medium" color="brand.400">
              {sources.length}
            </Text>
          </HStack>
        </HStack>

        {hasMore && (
          <Text
            fontSize="xs"
            color="brand.400"
            cursor="pointer"
            _hover={{ color: 'brand.300' }}
            onClick={onToggle}
            transition="color 0.2s"
          >
            {isOpen ? 'Voir moins' : `+${sources.length - maxVisible} autres`}
          </Text>
        )}
      </HStack>

      {/* List */}
      <VStack align="stretch" spacing={2}>
        {visibleSources.map((source, idx) => (
          <SourceCard
            key={source.chunk_id || source.document_id || idx}
            source={source}
            index={idx}
            onSourceClick={onSourceClick}
            isCompact={isCompact}
            highlightTerms={highlightTerms}
          />
        ))}
      </VStack>
    </VStack>
  )
}

export const SourcesList = memo(SourcesListComponent)

export default SourceCard
