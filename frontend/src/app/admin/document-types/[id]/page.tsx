'use client'

import {
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  FormControl,
  FormLabel,
  Heading,
  HStack,
  Input,
  Spinner,
  Switch,
  Text,
  Textarea,
  VStack,
  useToast,
  Badge,
  Wrap,
  WrapItem,
  IconButton,
  Divider,
  Center,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
} from '@chakra-ui/react'
import { ArrowBackIcon, DeleteIcon, AddIcon } from '@chakra-ui/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter, useParams } from 'next/navigation'
import axios from 'axios'
import { useState, useEffect } from 'react'

interface EntityTypeAssociation {
  entity_type_name: string
  source: string
  confidence: number | null
  examples: string[]
}

export default function DocumentTypeDetailPage() {
  const router = useRouter()
  const params = useParams()
  const id = params.id as string
  const toast = useToast()
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [contextPrompt, setContextPrompt] = useState('')
  const [isActive, setIsActive] = useState(true)
  const [newEntityType, setNewEntityType] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['document-type', id],
    queryFn: async () => {
      const response = await axios.get(`/api/document-types/${id}`)
      return response.data
    },
    enabled: !!id,
  })

  const { data: entityTypesData } = useQuery({
    queryKey: ['document-type-entity-types', id],
    queryFn: async () => {
      const response = await axios.get(`/api/document-types/${id}/entity-types`)
      return response.data
    },
    enabled: !!id,
  })

  // Initialiser les champs quand les données arrivent
  useEffect(() => {
    if (data) {
      setName(data.name || '')
      setSlug(data.slug || '')
      setDescription(data.description || '')
      setContextPrompt(data.context_prompt || '')
      setIsActive(data.is_active ?? true)
    }
  }, [data])

  const updateMutation = useMutation({
    mutationFn: async (updateData: any) => {
      await axios.put(`/api/document-types/${id}`, updateData)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-type', id] })
      queryClient.invalidateQueries({ queryKey: ['document-types'] })
      toast({
        title: 'Type de document mis à jour',
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur de mise à jour',
        description: error.response?.data?.message || 'Échec de la mise à jour',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    },
  })

  const addEntityTypeMutation = useMutation({
    mutationFn: async (entityTypeName: string) => {
      await axios.post(`/api/document-types/${id}/entity-types`, {
        entity_type_names: [entityTypeName],
        source: 'manual',
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-type-entity-types', id] })
      setNewEntityType('')
      toast({
        title: 'Type d\'entité ajouté',
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur d\'ajout',
        description: error.response?.data?.message || 'Échec de l\'ajout',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    },
  })

  const removeEntityTypeMutation = useMutation({
    mutationFn: async (entityTypeName: string) => {
      await axios.delete(`/api/document-types/${id}/entity-types/${entityTypeName}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-type-entity-types', id] })
      toast({
        title: 'Type d\'entité retiré',
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur de retrait',
        description: error.response?.data?.message || 'Échec du retrait',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    },
  })

  const handleSave = () => {
    updateMutation.mutate({
      name,
      slug,
      description,
      context_prompt: contextPrompt,
      is_active: isActive,
    })
  }

  const handleAddEntityType = () => {
    if (newEntityType.trim()) {
      addEntityTypeMutation.mutate(newEntityType.trim().toUpperCase())
    }
  }

  if (isLoading) {
    return (
      <Center h="400px">
        <Spinner size="xl" color="blue.500" />
      </Center>
    )
  }

  const entityTypes: EntityTypeAssociation[] = entityTypesData || []

  return (
    <VStack spacing={6} align="stretch">
      <HStack>
        <IconButton
          aria-label="Retour"
          icon={<ArrowBackIcon />}
          onClick={() => router.push('/admin/document-types')}
          variant="ghost"
        />
        <Heading size="lg">Éditer Type de Document</Heading>
      </HStack>

      <Card>
        <CardHeader>
          <Heading size="md">Informations Générales</Heading>
        </CardHeader>
        <CardBody>
          <VStack spacing={4} align="stretch">
            <FormControl isRequired>
              <FormLabel>Nom</FormLabel>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="ex: Technical Documentation"
              />
            </FormControl>

            <FormControl isRequired>
              <FormLabel>Slug</FormLabel>
              <Input
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="ex: technical"
              />
              <Text fontSize="sm" color="gray.500" mt={1}>
                Identifiant unique (minuscules, sans espaces)
              </Text>
            </FormControl>

            <FormControl>
              <FormLabel>Description</FormLabel>
              <Textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Description du type de document"
                rows={3}
              />
            </FormControl>

            <FormControl>
              <FormLabel>Prompt Contextuel</FormLabel>
              <Textarea
                value={contextPrompt}
                onChange={(e) => setContextPrompt(e.target.value)}
                placeholder="Prompt utilisé pour guider l'extraction LLM"
                rows={5}
              />
              <Text fontSize="sm" color="gray.500" mt={1}>
                Ce prompt sera injecté dans l'analyse LLM pour contextualiser l'extraction
              </Text>
            </FormControl>

            <FormControl display="flex" alignItems="center">
              <FormLabel mb="0">Actif</FormLabel>
              <Switch
                isChecked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                colorScheme="green"
              />
            </FormControl>

            <HStack justify="flex-end">
              <Button
                colorScheme="blue"
                onClick={handleSave}
                isLoading={updateMutation.isPending}
              >
                Enregistrer
              </Button>
            </HStack>
          </VStack>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <Heading size="md">Types d'Entités Associés</Heading>
          <Text fontSize="sm" color="gray.600" mt={2}>
            Types d'entités suggérés pour ce type de document
          </Text>
        </CardHeader>
        <CardBody>
          <VStack spacing={4} align="stretch">
            <HStack>
              <Input
                value={newEntityType}
                onChange={(e) => setNewEntityType(e.target.value)}
                placeholder="ex: SOLUTION, TECHNOLOGY..."
                onKeyPress={(e) => {
                  if (e.key === 'Enter') {
                    handleAddEntityType()
                  }
                }}
              />
              <Button
                leftIcon={<AddIcon />}
                colorScheme="green"
                onClick={handleAddEntityType}
                isLoading={addEntityTypeMutation.isPending}
              >
                Ajouter
              </Button>
            </HStack>

            <Divider />

            {entityTypes.length === 0 ? (
              <Center py={8}>
                <Text color="gray.500">Aucun type d'entité associé</Text>
              </Center>
            ) : (
              <Table variant="simple" size="sm">
                <Thead>
                  <Tr>
                    <Th>Type d'Entité</Th>
                    <Th>Source</Th>
                    <Th>Confiance</Th>
                    <Th>Actions</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {entityTypes.map((et) => (
                    <Tr key={et.entity_type_name}>
                      <Td>
                        <Badge colorScheme="blue" fontSize="sm">
                          {et.entity_type_name}
                        </Badge>
                      </Td>
                      <Td>
                        <Badge
                          colorScheme={
                            et.source === 'manual'
                              ? 'purple'
                              : et.source === 'llm_discovered'
                              ? 'orange'
                              : 'green'
                          }
                          fontSize="xs"
                        >
                          {et.source}
                        </Badge>
                      </Td>
                      <Td>
                        {et.confidence !== null ? `${(et.confidence * 100).toFixed(0)}%` : '-'}
                      </Td>
                      <Td>
                        <IconButton
                          aria-label="Retirer"
                          icon={<DeleteIcon />}
                          size="xs"
                          colorScheme="red"
                          variant="ghost"
                          onClick={() => removeEntityTypeMutation.mutate(et.entity_type_name)}
                          isLoading={removeEntityTypeMutation.isPending}
                        />
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
          </VStack>
        </CardBody>
      </Card>

      <Card bg="blue.50" borderColor="blue.200" borderWidth="1px">
        <CardBody>
          <VStack align="start" spacing={2}>
            <Text fontSize="sm" fontWeight="semibold" color="blue.700">
              💡 Sources des Types d'Entités
            </Text>
            <HStack spacing={4}>
              <Badge colorScheme="purple">manual</Badge>
              <Text fontSize="xs" color="blue.600">
                Ajouté manuellement
              </Text>
            </HStack>
            <HStack spacing={4}>
              <Badge colorScheme="orange">llm_discovered</Badge>
              <Text fontSize="xs" color="blue.600">
                Découvert par le LLM lors de l'analyse
              </Text>
            </HStack>
            <HStack spacing={4}>
              <Badge colorScheme="green">template</Badge>
              <Text fontSize="xs" color="blue.600">
                Importé depuis un template
              </Text>
            </HStack>
          </VStack>
        </CardBody>
      </Card>
    </VStack>
  )
}
