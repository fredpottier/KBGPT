'use client'

/**
 * OSMOS Import Analytics - Compact Industrial Design
 * Dense, information-rich imports listing
 */

import {
  Box,
  Text,
  HStack,
  Spinner,
  Center,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Badge,
  Icon,
  Flex,
  IconButton,
  Tooltip,
} from '@chakra-ui/react'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  FiBarChart2,
  FiRefreshCw,
  FiFileText,
  FiFile,
  FiImage,
  FiGrid,
  FiChevronRight,
  FiDatabase,
  FiClock,
} from 'react-icons/fi'

interface ImportItem {
  cache_file: string
  file_hash: string
  document_id: string
  source_path: string
  file_type: string
  total_pages: number
  total_chars: number
  created_at: string
}

const getFileIcon = (type: string) => {
  switch (type.toLowerCase()) {
    case 'pdf': return FiFileText
    case 'pptx': return FiImage
    case 'xlsx': return FiGrid
    default: return FiFile
  }
}

const formatChars = (chars: number) => {
  if (chars > 1000000) return `${(chars / 1000000).toFixed(1)}M`
  if (chars > 1000) return `${(chars / 1000).toFixed(0)}K`
  return chars.toString()
}

const formatDate = (isoDate: string) => {
  if (!isoDate) return '-'
  const date = new Date(isoDate)
  return date.toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Compact stat item
const StatItem = ({ value, label, icon, color = 'gray' }: { value: number | string; label: string; icon: any; color?: string }) => (
  <HStack spacing={1.5} px={2} py={1} bg="whiteAlpha.50" rounded="md">
    <Icon as={icon} boxSize={3} color={`${color}.400`} />
    <Text fontSize="xs" fontWeight="bold" fontFamily="mono" color="text.primary">{value}</Text>
    <Text fontSize="xs" color="text.muted">{label}</Text>
  </HStack>
)

export default function AnalyticsPage() {
  const router = useRouter()
  const [imports, setImports] = useState<ImportItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const getAuthHeaders = () => ({
    'Content-Type': 'application/json',
    Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
  })

  const fetchImports = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await fetch('/api/analytics/imports', {
        headers: getAuthHeaders(),
        credentials: 'include',
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      setImports(data.imports || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchImports() }, [])

  // Aggregate stats
  const totalPages = imports.reduce((sum, i) => sum + i.total_pages, 0)
  const totalChars = imports.reduce((sum, i) => sum + i.total_chars, 0)

  return (
    <Box maxW="1400px" mx="auto" p={3}>
      {/* Header Row */}
      <Flex justify="space-between" align="center" mb={3}>
        <HStack spacing={3}>
          <Box w={8} h={8} rounded="lg" bgGradient="linear(to-br, brand.500, cyan.500)" display="flex" alignItems="center" justifyContent="center">
            <Icon as={FiBarChart2} boxSize={4} color="white" />
          </Box>
          <Box>
            <Text fontSize="lg" fontWeight="bold" color="text.primary" lineHeight={1}>Import Analytics</Text>
            <Text fontSize="xs" color="text.muted">Analyse des extractions V2 et OSMOSE</Text>
          </Box>
        </HStack>
        <HStack spacing={2}>
          {imports.length > 0 && (
            <HStack spacing={2}>
              <StatItem value={imports.length} label="imports" icon={FiDatabase} color="brand" />
              <StatItem value={totalPages} label="pages" icon={FiFileText} color="blue" />
              <StatItem value={formatChars(totalChars)} label="chars" icon={FiGrid} color="purple" />
            </HStack>
          )}
          <IconButton
            aria-label="Refresh"
            icon={<FiRefreshCw />}
            size="sm"
            variant="ghost"
            onClick={fetchImports}
            isLoading={loading}
          />
        </HStack>
      </Flex>

      {/* Content */}
      {loading ? (
        <Center h="150px">
          <Spinner size="md" color="brand.500" />
        </Center>
      ) : error ? (
        <Box bg="red.900" border="1px solid" borderColor="red.600" rounded="lg" p={3} textAlign="center">
          <Text fontSize="sm" color="red.300">Erreur: {error}</Text>
        </Box>
      ) : imports.length === 0 ? (
        <Box bg="whiteAlpha.50" rounded="lg" p={6} textAlign="center" border="1px solid" borderColor="whiteAlpha.100">
          <Icon as={FiFileText} boxSize={8} color="text.muted" mb={2} />
          <Text fontSize="sm" color="text.muted">Aucun import dans le cache V2</Text>
        </Box>
      ) : (
        <Box bg="whiteAlpha.50" rounded="lg" overflow="hidden" border="1px solid" borderColor="whiteAlpha.100">
          <Table size="sm" variant="unstyled">
            <Thead>
              <Tr borderBottom="1px solid" borderColor="whiteAlpha.100">
                <Th py={2} px={3} color="text.muted" fontSize="xs" fontWeight="medium">Document</Th>
                <Th py={2} px={3} color="text.muted" fontSize="xs" fontWeight="medium" textAlign="center">Type</Th>
                <Th py={2} px={3} color="text.muted" fontSize="xs" fontWeight="medium" isNumeric>Pages</Th>
                <Th py={2} px={3} color="text.muted" fontSize="xs" fontWeight="medium" isNumeric>Chars</Th>
                <Th py={2} px={3} color="text.muted" fontSize="xs" fontWeight="medium" textAlign="center">Date</Th>
                <Th py={2} px={3} w="40px"></Th>
              </Tr>
            </Thead>
            <Tbody>
              {imports.map((imp) => (
                <Tr
                  key={imp.file_hash}
                  borderBottom="1px solid"
                  borderColor="whiteAlpha.50"
                  _hover={{ bg: 'whiteAlpha.100', cursor: 'pointer' }}
                  onClick={() => router.push(`/analytics/${imp.file_hash}`)}
                  transition="background 0.15s"
                >
                  <Td py={2} px={3}>
                    <HStack spacing={2}>
                      <Icon as={getFileIcon(imp.file_type)} boxSize={3.5} color="brand.400" flexShrink={0} />
                      <Box minW={0}>
                        <Text fontSize="sm" fontWeight="medium" color="text.primary" noOfLines={1}>
                          {imp.document_id}
                        </Text>
                        <Text fontSize="xs" color="text.muted" noOfLines={1}>
                          {imp.source_path.split('/').pop()}
                        </Text>
                      </Box>
                    </HStack>
                  </Td>
                  <Td py={2} px={3} textAlign="center">
                    <Badge size="sm" colorScheme="blue" variant="subtle" fontSize="xs" textTransform="uppercase">
                      {imp.file_type}
                    </Badge>
                  </Td>
                  <Td py={2} px={3} isNumeric>
                    <Text fontSize="sm" fontFamily="mono" color="text.primary">{imp.total_pages}</Text>
                  </Td>
                  <Td py={2} px={3} isNumeric>
                    <Text fontSize="sm" fontFamily="mono" color="text.muted">{formatChars(imp.total_chars)}</Text>
                  </Td>
                  <Td py={2} px={3} textAlign="center">
                    <HStack spacing={1} justify="center">
                      <Icon as={FiClock} boxSize={3} color="text.muted" />
                      <Text fontSize="xs" color="text.muted">{formatDate(imp.created_at)}</Text>
                    </HStack>
                  </Td>
                  <Td py={2} px={3}>
                    <Tooltip label="Voir details" placement="left">
                      <IconButton
                        aria-label="View"
                        icon={<FiChevronRight />}
                        size="xs"
                        variant="ghost"
                        colorScheme="brand"
                      />
                    </Tooltip>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </Box>
      )}
    </Box>
  )
}
