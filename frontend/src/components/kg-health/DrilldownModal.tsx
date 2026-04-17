'use client'

/**
 * Modal affichant le top N detaille d'une metrique.
 * Utilise l'endpoint /api/kg-health/drilldown/{key}
 */

import { useEffect, useState } from 'react'
import {
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalCloseButton,
  ModalBody,
  Spinner,
  VStack,
  HStack,
  Text,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Badge,
  Box,
} from '@chakra-ui/react'
import { KGHealthDrilldownResponse } from './types'

const API_BASE_URL =
  typeof window !== 'undefined'
    ? process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
    : 'http://localhost:8000'

interface Props {
  isOpen: boolean
  onClose: () => void
  drilldownKey: string | null
}

const COLUMN_LABELS: Record<string, string> = {
  doc_id: 'Document',
  claims_total: 'Claims',
  linkage_pct: 'Linkage %',
  subject_status: 'Sujet',
  entity: 'Entite',
  claims: 'Claims',
  share_pct: 'Part %',
  entity_type: 'Type',
  mention_count: 'Mentions',
}

function formatDocLabel(docId: string): string {
  if (!docId) return ''
  if (docId.includes('_')) {
    const parts = docId.split('_')
    if (parts.length > 2 && parts[parts.length - 1].length >= 8) parts.pop()
    return parts.join(' ')
  }
  return docId
}

function renderCell(col: string, value: any): React.ReactNode {
  if (value == null) return '-'

  if (col === 'doc_id') return formatDocLabel(value)

  if (col === 'linkage_pct' || col === 'share_pct') {
    const v = Number(value)
    const zone = v < 10 ? 'red' : v < 30 ? 'orange' : v < 50 ? 'yellow' : 'green'
    return (
      <Badge colorScheme={zone === 'yellow' ? 'yellow' : zone}>
        {v.toFixed(1)}%
      </Badge>
    )
  }

  if (col === 'subject_status') {
    const zone = value === 'resolved' ? 'green' : value === 'unresolved' ? 'orange' : 'red'
    return (
      <Badge colorScheme={zone === 'orange' ? 'orange' : zone} fontSize="2xs">
        {value}
      </Badge>
    )
  }

  if (typeof value === 'number') return value.toLocaleString()

  return String(value)
}

export function DrilldownModal({ isOpen, onClose, drilldownKey }: Props) {
  const [data, setData] = useState<KGHealthDrilldownResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen || !drilldownKey) return

    setLoading(true)
    setError(null)
    setData(null)

    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
    }

    fetch(`${API_BASE_URL}/api/kg-health/drilldown/${drilldownKey}?limit=50`, { headers })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((json: KGHealthDrilldownResponse) => setData(json))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [isOpen, drilldownKey])

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="3xl" scrollBehavior="inside">
      <ModalOverlay />
      <ModalContent bg="var(--bg-secondary)" color="var(--text-primary)">
        <ModalHeader borderBottom="1px solid" borderColor="var(--border-default)">
          {data?.title ?? 'Chargement...'}
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody py={5}>
          {loading && (
            <VStack py={10}>
              <Spinner size="lg" color="brand.400" />
              <Text fontSize="sm" color="var(--text-muted)">
                Chargement du drill-down...
              </Text>
            </VStack>
          )}

          {error && (
            <Box bg="rgba(239,68,68,0.08)" borderRadius="md" p={4}>
              <Text color="red.400">{error}</Text>
            </Box>
          )}

          {data && !loading && !error && (
            <VStack align="stretch" spacing={3}>
              <HStack>
                <Text fontSize="xs" color="var(--text-muted)">
                  {data.total_available} ligne(s) affichee(s)
                </Text>
              </HStack>
              <Box overflowX="auto">
                <Table size="sm" variant="simple">
                  <Thead>
                    <Tr>
                      {data.columns.map((col) => (
                        <Th key={col} color="var(--text-muted)" borderColor="var(--border-default)">
                          {COLUMN_LABELS[col] ?? col}
                        </Th>
                      ))}
                    </Tr>
                  </Thead>
                  <Tbody>
                    {data.rows.map((row, idx) => (
                      <Tr key={idx} _hover={{ bg: 'var(--bg-primary)' }}>
                        {data.columns.map((col) => (
                          <Td
                            key={col}
                            borderColor="var(--border-default)"
                            fontSize="xs"
                            color="var(--text-primary)"
                          >
                            {renderCell(col, row[col])}
                          </Td>
                        ))}
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </Box>
            </VStack>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}
