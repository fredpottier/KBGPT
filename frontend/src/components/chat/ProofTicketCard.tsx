'use client'

/**
 * Carte de Preuve (Proof Ticket) - OSMOSE Assertion-Centric.
 *
 * Affiche un resume de preuve pour une assertion cle:
 * - Titre de l'assertion
 * - Statut visuel
 * - Resume de la preuve
 * - CTA vers la source
 */

import {
  Box,
  VStack,
  HStack,
  Text,
  Badge,
  Button,
  Icon,
} from '@chakra-ui/react'
import { FiExternalLink, FiFileText } from 'react-icons/fi'
import type { ProofTicket, SourceRef } from '@/types/instrumented'
import { ASSERTION_STYLES } from '@/types/instrumented'

interface ProofTicketCardProps {
  ticket: ProofTicket
  sources: SourceRef[]
  onSourceClick?: (sourceId: string) => void
}

export default function ProofTicketCard({
  ticket,
  sources,
  onSourceClick,
}: ProofTicketCardProps) {
  const style = ASSERTION_STYLES[ticket.status]

  // Trouver la source principale
  const primarySource = ticket.primary_sources.length > 0
    ? sources.find(s => s.id === ticket.primary_sources[0])
    : null

  return (
    <Box
      bg="bg.secondary"
      border="1px solid"
      borderColor="border.default"
      borderRadius="lg"
      p={3}
      w="280px"
      flexShrink={0}
      transition="all 0.2s"
      _hover={{
        borderColor: style.borderColor,
        boxShadow: 'sm',
      }}
    >
      <VStack spacing={2} align="stretch">
        {/* Header avec statut */}
        <HStack justify="space-between">
          <Badge
            bg={style.bgColor}
            color={style.color}
            px={2}
            py={0.5}
            borderRadius="full"
            fontSize="xs"
          >
            <HStack spacing={1}>
              <Text>{style.indicator}</Text>
              <Text>{style.label}</Text>
            </HStack>
          </Badge>
          <Text fontSize="10px" color="text.muted">
            #{ticket.ticket_id}
          </Text>
        </HStack>

        {/* Titre */}
        <Text
          fontSize="sm"
          fontWeight="medium"
          color="text.primary"
          noOfLines={2}
          lineHeight="1.4"
        >
          {ticket.title}
        </Text>

        {/* Summary */}
        <Text fontSize="xs" color="text.secondary" noOfLines={2}>
          {ticket.summary}
        </Text>

        {/* Source info */}
        {primarySource && (
          <HStack
            spacing={1}
            fontSize="10px"
            color="text.muted"
            bg="bg.tertiary"
            px={2}
            py={1}
            borderRadius="sm"
          >
            <Icon as={FiFileText} boxSize={3} />
            <Text noOfLines={1} flex={1}>
              {primarySource.document.title}
            </Text>
            {primarySource.locator?.page_or_slide && (
              <Text>p.{primarySource.locator.page_or_slide}</Text>
            )}
          </HStack>
        )}

        {/* CTA */}
        {ticket.cta && onSourceClick && (
          <Button
            size="xs"
            variant="ghost"
            colorScheme="blue"
            leftIcon={<Icon as={FiExternalLink} boxSize={3} />}
            onClick={() => {
              if (ticket.cta?.type === 'source') {
                onSourceClick(ticket.cta.id)
              }
            }}
            justifyContent="flex-start"
            fontWeight="normal"
          >
            {ticket.cta.label}
          </Button>
        )}
      </VStack>
    </Box>
  )
}

/**
 * Liste horizontale de Proof Tickets.
 */
interface ProofTicketListProps {
  tickets: ProofTicket[]
  sources: SourceRef[]
  onSourceClick?: (sourceId: string) => void
}

export function ProofTicketList({
  tickets,
  sources,
  onSourceClick,
}: ProofTicketListProps) {
  if (tickets.length === 0) return null

  return (
    <Box>
      <Text fontSize="xs" fontWeight="semibold" color="text.secondary" mb={2}>
        Preuves cles ({tickets.length})
      </Text>
      <HStack
        spacing={3}
        overflowX="auto"
        pb={2}
        css={{
          '&::-webkit-scrollbar': {
            height: '6px',
          },
          '&::-webkit-scrollbar-track': {
            background: 'transparent',
          },
          '&::-webkit-scrollbar-thumb': {
            background: 'rgba(128, 128, 128, 0.3)',
            borderRadius: '3px',
          },
        }}
      >
        {tickets.map(ticket => (
          <ProofTicketCard
            key={ticket.ticket_id}
            ticket={ticket}
            sources={sources}
            onSourceClick={onSourceClick}
          />
        ))}
      </HStack>
    </Box>
  )
}

export { ProofTicketCard }
