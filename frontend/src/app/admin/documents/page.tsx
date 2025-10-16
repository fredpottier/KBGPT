'use client'

import { useState } from 'react'
import {
  Box,
  Card,
  CardBody,
  CardHeader,
  VStack,
  HStack,
  Text,
  Badge,
  Button,
  Spinner,
  Center,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Select,
  Input,
  InputGroup,
  InputLeftElement,
  Icon,
  Heading,
  Flex,
  Menu,
  MenuButton,
  MenuList,
  MenuItem,
  IconButton,
  Tooltip,
} from '@chakra-ui/react'
import {
  SearchIcon,
  WarningIcon,
  ChevronDownIcon,
  TimeIcon,
  ViewIcon,
} from '@chakra-ui/icons'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useRouter } from 'next/navigation'

export default function DocumentsListPage() {
  const router = useRouter()
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [page, setPage] = useState(0)
  const pageSize = 20

  const {
    data: documentsResponse,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['documents', 'list', statusFilter, typeFilter, page],
    queryFn: () =>
      api.documents.list({
        status: statusFilter || undefined,
        document_type: typeFilter || undefined,
        limit: pageSize,
        offset: page * pageSize,
      }),
    refetchInterval: 30000, // Refresh every 30s
  })

  if (isLoading) {
    return (
      <Center h="400px">
        <Spinner size="xl" color="brand.500" />
      </Center>
    )
  }

  if (error || !documentsResponse?.success) {
    return (
      <Card>
        <CardBody>
          <Center py={12}>
            <VStack spacing={4}>
              <Icon as={WarningIcon} boxSize={12} color="red.500" />
              <Text fontSize="lg" color="red.500">
                Erreur lors du chargement des documents
              </Text>
              <Text fontSize="sm" color="gray.500">
                {error?.toString() || 'Erreur inconnue'}
              </Text>
            </VStack>
          </Center>
        </CardBody>
      </Card>
    )
  }

  const documents = documentsResponse.data?.documents || []
  const total = documentsResponse.data?.total || 0

  // Filter by search query (client-side)
  const filteredDocuments = searchQuery
    ? documents.filter((doc: any) =>
        doc.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : documents

  const totalPages = Math.ceil(total / pageSize)

  return (
    <VStack spacing={6} align="stretch">
      {/* Header */}
      <Box>
        <Heading size="lg">Gestion des Documents</Heading>
        <Text color="gray.600" mt={2}>
          Versioning et traçabilité des documents
        </Text>
      </Box>

      {/* Filters */}
      <Card>
        <CardBody>
          <Flex gap={4} wrap="wrap">
            <InputGroup maxW="400px">
              <InputLeftElement pointerEvents="none">
                <Icon as={SearchIcon} color="gray.400" />
              </InputLeftElement>
              <Input
                placeholder="Rechercher par titre..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </InputGroup>

            <Select
              placeholder="Tous les statuts"
              maxW="200px"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="active">Actif</option>
              <option value="draft">Brouillon</option>
              <option value="archived">Archivé</option>
              <option value="obsolete">Obsolète</option>
            </Select>

            <Select
              placeholder="Tous les types"
              maxW="200px"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="pdf">PDF</option>
              <option value="pptx">PPTX</option>
              <option value="docx">DOCX</option>
              <option value="excel">Excel</option>
            </Select>

            {(searchQuery || statusFilter || typeFilter) && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setSearchQuery('')
                  setStatusFilter('')
                  setTypeFilter('')
                }}
              >
                Réinitialiser
              </Button>
            )}
          </Flex>
        </CardBody>
      </Card>

      {/* Documents Table */}
      <Card>
        <CardHeader>
          <HStack justify="space-between">
            <Text fontSize="lg" fontWeight="semibold">
              Documents ({total})
            </Text>
            <Badge colorScheme="blue">
              Page {page + 1} / {totalPages || 1}
            </Badge>
          </HStack>
        </CardHeader>
        <CardBody overflowX="auto">
          {filteredDocuments.length === 0 ? (
            <Center py={12}>
              <VStack spacing={4}>
                <Icon as={SearchIcon} boxSize={12} color="gray.400" />
                <Text color="gray.500">Aucun document trouvé</Text>
              </VStack>
            </Center>
          ) : (
            <Table variant="simple">
              <Thead>
                <Tr>
                  <Th>Titre</Th>
                  <Th>Type</Th>
                  <Th>Statut</Th>
                  <Th>Versions</Th>
                  <Th>Créé le</Th>
                  <Th>Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {filteredDocuments.map((document: any) => (
                  <Tr key={document.document_id} _hover={{ bg: 'gray.50' }}>
                    <Td>
                      <VStack align="start" spacing={0}>
                        <Text fontWeight="medium">{document.title}</Text>
                        {document.description && (
                          <Text fontSize="xs" color="gray.600" noOfLines={1}>
                            {document.description}
                          </Text>
                        )}
                      </VStack>
                    </Td>
                    <Td>
                      <Badge colorScheme="purple" variant="subtle">
                        {document.document_type.toUpperCase()}
                      </Badge>
                    </Td>
                    <Td>
                      <Badge
                        colorScheme={
                          document.status === 'active'
                            ? 'green'
                            : document.status === 'draft'
                            ? 'yellow'
                            : document.status === 'archived'
                            ? 'gray'
                            : 'orange'
                        }
                      >
                        {document.status}
                      </Badge>
                    </Td>
                    <Td>
                      <Text fontSize="sm">{document.version_count || 0}</Text>
                    </Td>
                    <Td>
                      <Text fontSize="sm" color="gray.600">
                        {new Date(document.created_at).toLocaleDateString('fr-FR')}
                      </Text>
                    </Td>
                    <Td>
                      <HStack spacing={2}>
                        <Tooltip label="Voir Timeline">
                          <IconButton
                            aria-label="Timeline"
                            icon={<TimeIcon />}
                            size="sm"
                            variant="ghost"
                            colorScheme="blue"
                            onClick={() =>
                              router.push(
                                `/admin/documents/${document.document_id}/timeline`
                              )
                            }
                          />
                        </Tooltip>

                        <Menu>
                          <MenuButton
                            as={IconButton}
                            aria-label="Plus d'actions"
                            icon={<ChevronDownIcon />}
                            size="sm"
                            variant="ghost"
                          />
                          <MenuList>
                            <MenuItem
                              icon={<TimeIcon />}
                              onClick={() =>
                                router.push(
                                  `/admin/documents/${document.document_id}/timeline`
                                )
                              }
                            >
                              Voir Timeline
                            </MenuItem>
                            <MenuItem
                              icon={<ViewIcon />}
                              onClick={() =>
                                router.push(
                                  `/admin/documents/${document.document_id}/compare`
                                )
                              }
                            >
                              Comparer Versions
                            </MenuItem>
                          </MenuList>
                        </Menu>
                      </HStack>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      {/* Pagination */}
      {totalPages > 1 && (
        <Card>
          <CardBody>
            <Flex justify="space-between" align="center">
              <Text fontSize="sm" color="gray.600">
                Affichage de {page * pageSize + 1} à{' '}
                {Math.min((page + 1) * pageSize, total)} sur {total} documents
              </Text>
              <HStack spacing={2}>
                <Button
                  size="sm"
                  onClick={() => setPage(Math.max(0, page - 1))}
                  isDisabled={page === 0}
                >
                  Précédent
                </Button>
                <Text fontSize="sm">
                  Page {page + 1} / {totalPages}
                </Text>
                <Button
                  size="sm"
                  onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                  isDisabled={page >= totalPages - 1}
                >
                  Suivant
                </Button>
              </HStack>
            </Flex>
          </CardBody>
        </Card>
      )}
    </VStack>
  )
}
