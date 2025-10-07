'use client'

import {
  Box,
  Button,
  Card,
  CardBody,
  Heading,
  HStack,
  Icon,
  Spinner,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  VStack,
  Badge,
  useToast,
  IconButton,
  Tooltip,
  Center,
} from '@chakra-ui/react'
import { AddIcon, EditIcon, ViewIcon, DeleteIcon } from '@chakra-ui/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import axios from 'axios'

interface DocumentType {
  id: string
  name: string
  slug: string
  description: string
  context_prompt: string
  is_active: boolean
  usage_count: number
  entity_type_count: number
  suggested_entity_types: string[]
  created_at: string
  updated_at: string
}

export default function DocumentTypesPage() {
  const router = useRouter()
  const toast = useToast()
  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['document-types'],
    queryFn: async () => {
      const response = await axios.get('/api/document-types')
      return response.data
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      await axios.delete(`/api/document-types/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-types'] })
      toast({
        title: 'Type de document supprimé',
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur de suppression',
        description: error.response?.data?.message || 'Échec de la suppression',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    },
  })

  const handleDelete = (id: string, name: string) => {
    if (confirm(`Êtes-vous sûr de vouloir supprimer le type "${name}" ?`)) {
      deleteMutation.mutate(id)
    }
  }

  if (isLoading) {
    return (
      <Center h="400px">
        <Spinner size="xl" color="blue.500" />
      </Center>
    )
  }

  if (error) {
    return (
      <Card>
        <CardBody>
          <Text color="red.500">Erreur lors du chargement des types de documents</Text>
        </CardBody>
      </Card>
    )
  }

  const documentTypes: DocumentType[] = data?.document_types || []

  return (
    <VStack spacing={6} align="stretch">
      <HStack justify="space-between">
        <Box>
          <Heading size="lg">Types de Documents</Heading>
          <Text color="gray.600" mt={2}>
            Gérez les types de documents et leurs types d'entités associés
          </Text>
        </Box>
        <Button
          leftIcon={<AddIcon />}
          colorScheme="blue"
          onClick={() => router.push('/admin/document-types/new')}
        >
          Nouveau Type
        </Button>
      </HStack>

      <Card>
        <CardBody>
          {documentTypes.length === 0 ? (
            <Center py={12}>
              <VStack spacing={4}>
                <Icon as={ViewIcon} boxSize={12} color="gray.400" />
                <Text fontSize="lg" color="gray.500">
                  Aucun type de document
                </Text>
                <Button
                  leftIcon={<AddIcon />}
                  colorScheme="blue"
                  variant="outline"
                  onClick={() => router.push('/admin/document-types/new')}
                >
                  Créer le premier type
                </Button>
              </VStack>
            </Center>
          ) : (
            <Table variant="simple">
              <Thead>
                <Tr>
                  <Th>Nom</Th>
                  <Th>Slug</Th>
                  <Th>Description</Th>
                  <Th>Types d'Entités</Th>
                  <Th>Utilisations</Th>
                  <Th>Statut</Th>
                  <Th>Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {documentTypes.map((docType) => (
                  <Tr key={docType.id}>
                    <Td fontWeight="semibold">{docType.name}</Td>
                    <Td>
                      <Badge colorScheme="purple">{docType.slug}</Badge>
                    </Td>
                    <Td maxW="300px">
                      <Text noOfLines={2} fontSize="sm">
                        {docType.description || '-'}
                      </Text>
                    </Td>
                    <Td>
                      <Badge colorScheme="blue">{docType.entity_type_count} types</Badge>
                    </Td>
                    <Td>
                      <Badge colorScheme={docType.usage_count > 0 ? 'green' : 'gray'}>
                        {docType.usage_count}
                      </Badge>
                    </Td>
                    <Td>
                      <Badge colorScheme={docType.is_active ? 'green' : 'red'}>
                        {docType.is_active ? 'Actif' : 'Inactif'}
                      </Badge>
                    </Td>
                    <Td>
                      <HStack spacing={2}>
                        <Tooltip label="Voir / Éditer">
                          <IconButton
                            aria-label="Voir détails"
                            icon={<EditIcon />}
                            size="sm"
                            colorScheme="blue"
                            variant="ghost"
                            onClick={() => router.push(`/admin/document-types/${docType.id}`)}
                          />
                        </Tooltip>
                        <Tooltip label="Supprimer">
                          <IconButton
                            aria-label="Supprimer"
                            icon={<DeleteIcon />}
                            size="sm"
                            colorScheme="red"
                            variant="ghost"
                            onClick={() => handleDelete(docType.id, docType.name)}
                            isLoading={deleteMutation.isPending}
                          />
                        </Tooltip>
                      </HStack>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Card bg="blue.50" borderColor="blue.200" borderWidth="1px">
        <CardBody>
          <VStack align="start" spacing={2}>
            <Heading size="sm" color="blue.700">
              💡 À propos des Types de Documents
            </Heading>
            <Text fontSize="sm" color="blue.600">
              Les types de documents permettent de contextualiser l'extraction d'entités par le LLM.
              Chaque type peut avoir des types d'entités suggérés qui guident l'analyse.
            </Text>
          </VStack>
        </CardBody>
      </Card>
    </VStack>
  )
}
