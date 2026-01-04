'use client'

/**
 * OSMOS Import Analytics - Dark Elegance Edition
 *
 * Liste des imports avec metrics d'extraction V2
 */

import {
  Box,
  Text,
  VStack,
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
  Button,
  Icon,
  Flex,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  FiBarChart2,
  FiRefreshCw,
  FiFileText,
  FiFile,
  FiImage,
  FiGrid,
  FiArrowRight,
} from 'react-icons/fi'

const MotionBox = motion(Box)

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
    case 'pdf':
      return FiFileText
    case 'pptx':
      return FiImage
    case 'xlsx':
      return FiGrid
    default:
      return FiFile
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
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

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
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const data = await response.json()
      setImports(data.imports || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchImports()
  }, [])

  return (
    <Box minH="100vh" bg="bg.primary" pt={20} px={6} pb={10}>
      <Box maxW="1400px" mx="auto">
        {/* Header */}
        <MotionBox
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <Flex justify="space-between" align="center" mb={8}>
            <HStack spacing={4}>
              <Box
                p={3}
                bg="brand.500"
                rounded="xl"
                boxShadow="0 0 20px rgba(99, 102, 241, 0.3)"
              >
                <Icon as={FiBarChart2} boxSize={6} color="white" />
              </Box>
              <VStack align="start" spacing={0}>
                <Text fontSize="2xl" fontWeight="bold" color="text.primary">
                  Import Analytics
                </Text>
                <Text fontSize="sm" color="text.muted">
                  Analyse des extractions V2 et OSMOSE
                </Text>
              </VStack>
            </HStack>

            <Button
              leftIcon={<FiRefreshCw />}
              onClick={fetchImports}
              isLoading={loading}
              variant="outline"
              borderColor="border.default"
              color="text.secondary"
              _hover={{ bg: 'bg.hover', borderColor: 'brand.500' }}
            >
              Rafraichir
            </Button>
          </Flex>
        </MotionBox>

        {/* Content */}
        {loading ? (
          <Center h="300px">
            <VStack spacing={4}>
              <Spinner size="xl" color="brand.500" thickness="3px" />
              <Text color="text.muted">Chargement des imports...</Text>
            </VStack>
          </Center>
        ) : error ? (
          <MotionBox
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            bg="error.500/10"
            border="1px solid"
            borderColor="error.500"
            rounded="xl"
            p={6}
          >
            <VStack spacing={4}>
              <Text color="error.400" fontWeight="medium">
                Erreur: {error}
              </Text>
              <Button
                onClick={fetchImports}
                colorScheme="red"
                variant="outline"
              >
                Reessayer
              </Button>
            </VStack>
          </MotionBox>
        ) : imports.length === 0 ? (
          <MotionBox
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            bg="bg.secondary"
            border="1px solid"
            borderColor="border.default"
            rounded="xl"
            p={10}
            textAlign="center"
          >
            <Icon as={FiFileText} boxSize={12} color="text.muted" mb={4} />
            <Text color="text.muted" fontSize="lg">
              Aucun import trouve dans le cache V2
            </Text>
          </MotionBox>
        ) : (
          <MotionBox
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.1 }}
            bg="bg.secondary"
            border="1px solid"
            borderColor="border.default"
            rounded="xl"
            overflow="hidden"
          >
            <Table variant="simple">
              <Thead bg="bg.tertiary">
                <Tr>
                  <Th color="text.muted" borderColor="border.default">Document</Th>
                  <Th color="text.muted" borderColor="border.default" textAlign="center">Type</Th>
                  <Th color="text.muted" borderColor="border.default" textAlign="center">Pages</Th>
                  <Th color="text.muted" borderColor="border.default" textAlign="center">Caracteres</Th>
                  <Th color="text.muted" borderColor="border.default" textAlign="center">Date</Th>
                  <Th color="text.muted" borderColor="border.default" textAlign="center">Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {imports.map((imp, index) => (
                  <Tr
                    key={imp.file_hash}
                    _hover={{ bg: 'bg.hover' }}
                    transition="background 0.2s"
                  >
                    <Td borderColor="border.default">
                      <HStack spacing={3}>
                        <Box
                          p={2}
                          bg="bg.tertiary"
                          rounded="lg"
                          color="brand.400"
                        >
                          <Icon as={getFileIcon(imp.file_type)} boxSize={5} />
                        </Box>
                        <VStack align="start" spacing={0}>
                          <Text
                            color="text.primary"
                            fontWeight="medium"
                            fontSize="sm"
                            noOfLines={1}
                            maxW="300px"
                          >
                            {imp.document_id}
                          </Text>
                          <Text
                            color="text.muted"
                            fontSize="xs"
                            noOfLines={1}
                            maxW="300px"
                          >
                            {imp.source_path.split('/').pop()}
                          </Text>
                        </VStack>
                      </HStack>
                    </Td>
                    <Td borderColor="border.default" textAlign="center">
                      <Badge
                        colorScheme="blue"
                        variant="subtle"
                        px={2}
                        py={1}
                        rounded="md"
                        textTransform="uppercase"
                        fontSize="xs"
                      >
                        {imp.file_type}
                      </Badge>
                    </Td>
                    <Td borderColor="border.default" textAlign="center">
                      <Text color="text.primary" fontWeight="medium">
                        {imp.total_pages}
                      </Text>
                    </Td>
                    <Td borderColor="border.default" textAlign="center">
                      <Text color="text.primary">
                        {formatChars(imp.total_chars)}
                      </Text>
                    </Td>
                    <Td borderColor="border.default" textAlign="center">
                      <Text color="text.muted" fontSize="sm">
                        {formatDate(imp.created_at)}
                      </Text>
                    </Td>
                    <Td borderColor="border.default" textAlign="center">
                      <Button
                        size="sm"
                        rightIcon={<FiArrowRight />}
                        onClick={() => router.push(`/analytics/${imp.file_hash}`)}
                        bg="brand.500"
                        color="white"
                        _hover={{
                          bg: 'brand.600',
                          transform: 'translateX(2px)',
                        }}
                        transition="all 0.2s"
                      >
                        Analyser
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </MotionBox>
        )}

        {/* Footer */}
        {imports.length > 0 && (
          <MotionBox
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            mt={4}
          >
            <Text color="text.muted" fontSize="sm">
              Total: {imports.length} imports dans le cache V2
            </Text>
          </MotionBox>
        )}
      </Box>
    </Box>
  )
}
