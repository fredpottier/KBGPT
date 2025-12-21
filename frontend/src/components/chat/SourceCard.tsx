'use client';

/**
 * OSMOSE Phase 3.5 - Source Card Component
 *
 * Affiche une source de maniere enrichie avec:
 * - Icone selon le type de document
 * - Extrait avec highlight des termes
 * - Badge de confiance/score
 * - Lien vers le document source
 */

import { memo, useCallback } from 'react';
import {
  Box,
  HStack,
  VStack,
  Text,
  Badge,
  Icon,
  Tooltip,
  Collapse,
  useDisclosure,
  IconButton,
} from '@chakra-ui/react';
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ExternalLinkIcon,
  AttachmentIcon,
} from '@chakra-ui/icons';
import { motion } from 'framer-motion';

const MotionBox = motion(Box);

// Types de documents avec leurs couleurs/icones
const DOC_TYPE_CONFIG: Record<string, { color: string; label: string }> = {
  PDF: { color: 'red', label: 'PDF' },
  PPTX: { color: 'orange', label: 'PPTX' },
  DOCX: { color: 'blue', label: 'DOCX' },
  XLSX: { color: 'green', label: 'XLSX' },
  TXT: { color: 'gray', label: 'TXT' },
  MD: { color: 'purple', label: 'MD' },
  DEFAULT: { color: 'gray', label: 'DOC' },
};

export interface Source {
  document_id?: string;
  document_name: string;
  document_type?: string;
  chunk_id?: string;
  text?: string;
  excerpt?: string;
  score?: number;
  page_number?: number;
  slide_number?: number;
  confidence?: number;
}

interface SourceCardProps {
  source: Source;
  index?: number;
  onSourceClick?: (source: Source) => void;
  isCompact?: boolean;
  highlightTerms?: string[];
}

/**
 * Highlight les termes recherches dans le texte
 */
function highlightText(text: string, terms: string[]): React.ReactNode {
  if (!terms || terms.length === 0) return text;

  const regex = new RegExp(`(${terms.join('|')})`, 'gi');
  const parts = text.split(regex);

  return parts.map((part, i) => {
    const isMatch = terms.some(
      (term) => part.toLowerCase() === term.toLowerCase()
    );
    if (isMatch) {
      return (
        <Text as="mark" key={i} bg="yellow.200" px={0.5} borderRadius="sm">
          {part}
        </Text>
      );
    }
    return part;
  });
}

/**
 * Obtient la config d'affichage pour un type de document
 */
function getDocTypeConfig(type?: string) {
  if (!type) return DOC_TYPE_CONFIG.DEFAULT;
  const upperType = type.toUpperCase();
  return DOC_TYPE_CONFIG[upperType] || DOC_TYPE_CONFIG.DEFAULT;
}

/**
 * Source Card - Affiche une source de maniere enrichie
 */
function SourceCardComponent({
  source,
  index = 0,
  onSourceClick,
  isCompact = false,
  highlightTerms = [],
}: SourceCardProps) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: !isCompact });
  const docConfig = getDocTypeConfig(source.document_type);

  const handleClick = useCallback(() => {
    onSourceClick?.(source);
  }, [onSourceClick, source]);

  // Texte a afficher (excerpt ou text)
  const displayText = source.excerpt || source.text || '';
  const hasText = displayText.length > 0;

  // Location (page ou slide)
  const location = source.slide_number
    ? `Slide ${source.slide_number}`
    : source.page_number
    ? `Page ${source.page_number}`
    : null;

  // Score formaté
  const scoreDisplay = source.score
    ? `${Math.round(source.score * 100)}%`
    : source.confidence
    ? `${Math.round(source.confidence * 100)}%`
    : null;

  return (
    <MotionBox
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      w="full"
    >
      <Box
        bg="white"
        borderRadius="md"
        border="1px solid"
        borderColor="gray.200"
        overflow="hidden"
        _hover={{ borderColor: 'blue.300', shadow: 'sm' }}
        transition="all 0.2s"
      >
        {/* Header */}
        <HStack
          px={3}
          py={2}
          bg="gray.50"
          borderBottom={isOpen && hasText ? '1px solid' : 'none'}
          borderColor="gray.100"
          justify="space-between"
          cursor="pointer"
          onClick={hasText ? onToggle : handleClick}
        >
          <HStack spacing={2} flex="1" minW={0}>
            {/* Icone type */}
            <Icon as={AttachmentIcon} color={`${docConfig.color}.500`} />

            {/* Badge type */}
            <Badge
              colorScheme={docConfig.color}
              fontSize="xs"
              variant="subtle"
            >
              {docConfig.label}
            </Badge>

            {/* Nom du document */}
            <Text
              fontSize="sm"
              fontWeight="medium"
              color="gray.700"
              noOfLines={1}
              flex="1"
            >
              {source.document_name}
            </Text>

            {/* Location */}
            {location && (
              <Badge variant="outline" colorScheme="gray" fontSize="xs">
                {location}
              </Badge>
            )}
          </HStack>

          <HStack spacing={1}>
            {/* Score */}
            {scoreDisplay && (
              <Tooltip label="Score de pertinence">
                <Badge
                  colorScheme={
                    (source.score || source.confidence || 0) >= 0.8
                      ? 'green'
                      : (source.score || source.confidence || 0) >= 0.5
                      ? 'yellow'
                      : 'gray'
                  }
                  fontSize="xs"
                >
                  {scoreDisplay}
                </Badge>
              </Tooltip>
            )}

            {/* Bouton expand/lien */}
            {hasText ? (
              <IconButton
                aria-label={isOpen ? 'Reduire' : 'Developper'}
                icon={isOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}
                size="xs"
                variant="ghost"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggle();
                }}
              />
            ) : (
              <Tooltip label="Ouvrir le document">
                <IconButton
                  aria-label="Ouvrir"
                  icon={<ExternalLinkIcon />}
                  size="xs"
                  variant="ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleClick();
                  }}
                />
              </Tooltip>
            )}
          </HStack>
        </HStack>

        {/* Contenu (excerpt) */}
        {hasText && (
          <Collapse in={isOpen}>
            <Box px={3} py={2}>
              <Text
                fontSize="sm"
                color="gray.600"
                lineHeight="tall"
                noOfLines={isCompact ? 3 : undefined}
              >
                {highlightText(displayText, highlightTerms)}
              </Text>

              {/* Lien vers document */}
              {onSourceClick && (
                <Text
                  fontSize="xs"
                  color="blue.500"
                  mt={2}
                  cursor="pointer"
                  _hover={{ textDecoration: 'underline' }}
                  onClick={handleClick}
                >
                  Voir le document source →
                </Text>
              )}
            </Box>
          </Collapse>
        )}
      </Box>
    </MotionBox>
  );
}

export const SourceCard = memo(SourceCardComponent);

/**
 * Sources List - Liste de sources
 */
interface SourcesListProps {
  sources: Source[];
  onSourceClick?: (source: Source) => void;
  maxVisible?: number;
  isCompact?: boolean;
  highlightTerms?: string[];
  title?: string;
}

function SourcesListComponent({
  sources,
  onSourceClick,
  maxVisible = 3,
  isCompact = false,
  highlightTerms = [],
  title = 'Sources',
}: SourcesListProps) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: false });

  if (!sources || sources.length === 0) return null;

  const visibleSources = isOpen ? sources : sources.slice(0, maxVisible);
  const hasMore = sources.length > maxVisible;

  return (
    <VStack align="stretch" spacing={2} w="full">
      {/* Header */}
      <HStack justify="space-between">
        <HStack spacing={2}>
          <Text fontSize="sm" fontWeight="semibold" color="gray.600">
            {title}
          </Text>
          <Badge colorScheme="blue" variant="subtle" fontSize="xs">
            {sources.length}
          </Badge>
        </HStack>

        {hasMore && (
          <Text
            fontSize="xs"
            color="blue.500"
            cursor="pointer"
            _hover={{ textDecoration: 'underline' }}
            onClick={onToggle}
          >
            {isOpen
              ? 'Voir moins'
              : `+${sources.length - maxVisible} autres`}
          </Text>
        )}
      </HStack>

      {/* Liste */}
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
  );
}

export const SourcesList = memo(SourcesListComponent);

export default SourceCard;
