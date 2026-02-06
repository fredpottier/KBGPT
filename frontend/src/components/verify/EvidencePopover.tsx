'use client'

import {
  Box,
  VStack,
  HStack,
  Text,
  Badge,
  Divider,
  Icon,
} from '@chakra-ui/react'
import { FiFile, FiMapPin, FiTarget, FiCheckCircle, FiXCircle, FiAlertCircle, FiHelpCircle, FiDatabase } from 'react-icons/fi'
import type { Assertion, VerificationStatus } from '@/types/verification'

interface StatusInfo {
  label: string
  colorScheme: string
  icon: typeof FiCheckCircle
  bgColor: string
}

const STATUS_INFO: Record<VerificationStatus, StatusInfo> = {
  confirmed: {
    label: 'CONFIRMÉ',
    colorScheme: 'green',
    icon: FiCheckCircle,
    bgColor: 'rgba(34, 197, 94, 0.1)',
  },
  contradicted: {
    label: 'CONTREDIT',
    colorScheme: 'red',
    icon: FiXCircle,
    bgColor: 'rgba(239, 68, 68, 0.1)',
  },
  incomplete: {
    label: 'INCOMPLET',
    colorScheme: 'orange',
    icon: FiAlertCircle,
    bgColor: 'rgba(245, 158, 11, 0.1)',
  },
  fallback: {
    label: 'RAG SEULEMENT',
    colorScheme: 'gray',
    icon: FiDatabase,
    bgColor: 'rgba(161, 161, 170, 0.1)',
  },
  unknown: {
    label: 'NON TROUVÉ',
    colorScheme: 'gray',
    icon: FiHelpCircle,
    bgColor: 'rgba(61, 61, 92, 0.1)',
  },
}

interface EvidencePopoverProps {
  assertion: Assertion
}

export function EvidencePopover({ assertion }: EvidencePopoverProps) {
  const statusInfo = STATUS_INFO[assertion.status]

  return (
    <VStack align="stretch" spacing={3} p={3} maxW="400px">
      {/* Header avec statut */}
      <HStack justify="space-between">
        <Badge
          colorScheme={statusInfo.colorScheme}
          fontSize="sm"
          px={2}
          py={1}
          rounded="md"
        >
          <HStack spacing={1}>
            <Icon as={statusInfo.icon} />
            <Text>{statusInfo.label}</Text>
          </HStack>
        </Badge>
        <Text fontSize="xs" color="text.muted">
          Confiance: {Math.round(assertion.confidence * 100)}%
        </Text>
      </HStack>

      {/* Assertion text */}
      <Box
        p={2}
        bg={statusInfo.bgColor}
        rounded="md"
        borderLeft="3px solid"
        borderColor={`${statusInfo.colorScheme}.400`}
      >
        <Text fontSize="sm" color="text.primary" fontStyle="italic">
          "{assertion.text}"
        </Text>
      </Box>

      <Divider borderColor="border.default" />

      {/* Liste des preuves */}
      {assertion.evidence.length > 0 ? (
        <VStack align="stretch" spacing={2}>
          <Text fontSize="xs" fontWeight="semibold" color="text.muted" textTransform="uppercase">
            Sources ({assertion.evidence.length})
          </Text>
          {assertion.evidence.map((ev, i) => (
            <Box
              key={i}
              p={2}
              bg="bg.primary"
              rounded="md"
              border="1px solid"
              borderColor="border.default"
              fontSize="sm"
            >
              {/* Evidence type badge */}
              <HStack mb={2}>
                <Badge
                  size="sm"
                  colorScheme={ev.type === 'claim' ? 'purple' : 'blue'}
                  variant="subtle"
                >
                  {ev.type === 'claim' ? 'Claim KG' : 'Chunk RAG'}
                </Badge>
                <Badge
                  size="sm"
                  colorScheme={
                    ev.relationship === 'supports' ? 'green' :
                    ev.relationship === 'contradicts' ? 'red' : 'gray'
                  }
                  variant="outline"
                >
                  {ev.relationship === 'supports' ? 'Supporte' :
                   ev.relationship === 'contradicts' ? 'Contredit' : 'Partiel'}
                </Badge>
              </HStack>

              {/* Evidence text */}
              <Text color="text.primary" mb={2} noOfLines={3}>
                {ev.text}
              </Text>

              {/* Source info */}
              <HStack spacing={3} fontSize="xs" color="text.muted" flexWrap="wrap">
                <HStack spacing={1}>
                  <Icon as={FiFile} boxSize={3} />
                  <Text noOfLines={1} maxW="150px">{ev.sourceDoc}</Text>
                </HStack>
                {ev.sourcePage && (
                  <HStack spacing={1}>
                    <Icon as={FiMapPin} boxSize={3} />
                    <Text>Page {ev.sourcePage}</Text>
                  </HStack>
                )}
                <HStack spacing={1}>
                  <Icon as={FiTarget} boxSize={3} />
                  <Text>{Math.round(ev.confidence * 100)}%</Text>
                </HStack>
              </HStack>
            </Box>
          ))}
        </VStack>
      ) : (
        <Box p={3} bg="bg.primary" rounded="md" textAlign="center">
          <Icon as={FiHelpCircle} boxSize={6} color="text.muted" mb={2} />
          <Text fontSize="sm" color="text.muted">
            Aucune source trouvée dans la base de connaissances.
          </Text>
        </Box>
      )}
    </VStack>
  )
}
