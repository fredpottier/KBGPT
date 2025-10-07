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
  Switch,
  Text,
  Textarea,
  VStack,
  useToast,
  IconButton,
  Badge,
} from '@chakra-ui/react'
import { ArrowBackIcon } from '@chakra-ui/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import axios from 'axios'
import { useState } from 'react'

export default function NewDocumentTypePage() {
  const router = useRouter()
  const toast = useToast()
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [contextPrompt, setContextPrompt] = useState('')
  const [isActive, setIsActive] = useState(true)
  const [manualEntityTypes, setManualEntityTypes] = useState<string[]>([])
  const [newEntityType, setNewEntityType] = useState('')

  const createMutation = useMutation({
    mutationFn: async (data: any) => {
      const response = await axios.post('/api/document-types', data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-types'] })
      toast({
        title: 'Type de document créé',
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
      router.push('/admin/document-types')
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur de création',
        description: error.response?.data?.message || 'Échec de la création',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    },
  })

  const handleAddManualEntityType = () => {
    if (newEntityType.trim() && !manualEntityTypes.includes(newEntityType.trim().toUpperCase())) {
      setManualEntityTypes([...manualEntityTypes, newEntityType.trim().toUpperCase()])
      setNewEntityType('')
    }
  }

  const handleRemoveManualEntityType = (type: string) => {
    setManualEntityTypes(manualEntityTypes.filter((t) => t !== type))
  }

  const handleCreate = () => {
    createMutation.mutate({
      name,
      slug,
      description,
      context_prompt: contextPrompt,
      is_active: isActive,
      entity_types: manualEntityTypes,
    })
  }

  const isFormValid = name.trim() && slug.trim()

  return (
    <VStack spacing={6} align="stretch">
      <HStack>
        <IconButton
          aria-label="Retour"
          icon={<ArrowBackIcon />}
          onClick={() => router.push('/admin/document-types')}
          variant="ghost"
        />
        <Heading size="lg">Créer un Type de Document</Heading>
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
          </VStack>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <Heading size="md">Types d'Entités</Heading>
          <Text fontSize="sm" color="gray.600" mt={2}>
            Définissez les types d'entités suggérés pour ce type de document
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
                          handleAddManualEntityType()
                        }
                      }}
                    />
                    <Button colorScheme="green" onClick={handleAddManualEntityType}>
                      Ajouter
                    </Button>
                  </HStack>

                  {manualEntityTypes.length > 0 && (
                    <Box>
                      <Text fontSize="sm" fontWeight="semibold" mb={2}>
                        Types ajoutés ({manualEntityTypes.length})
                      </Text>
                      <HStack spacing={2} flexWrap="wrap">
                        {manualEntityTypes.map((type) => (
                          <Badge
                            key={type}
                            colorScheme="blue"
                            fontSize="sm"
                            px={3}
                            py={1}
                            cursor="pointer"
                            onClick={() => handleRemoveManualEntityType(type)}
                          >
                            {type} ✕
                          </Badge>
                        ))}
                      </HStack>
                    </Box>
                  )}
                </VStack>
        </CardBody>
      </Card>

      <HStack justify="flex-end">
        <Button variant="ghost" onClick={() => router.push('/admin/document-types')}>
          Annuler
        </Button>
        <Button
          colorScheme="blue"
          onClick={handleCreate}
          isLoading={createMutation.isPending}
          isDisabled={!isFormValid}
        >
          Créer le Type
        </Button>
      </HStack>

      <Card bg="blue.50" borderColor="blue.200" borderWidth="1px">
        <CardBody>
          <VStack align="start" spacing={2}>
            <Text fontSize="sm" fontWeight="semibold" color="blue.700">
              💡 Conseil
            </Text>
            <Text fontSize="sm" color="blue.600">
              Ajoutez les types d'entités pertinents pour votre cas d'usage. Ces types seront suggérés
              lors de l'import de documents de ce type. Le système découvrira automatiquement de nouveaux
              types lors de l'analyse des documents.
            </Text>
          </VStack>
        </CardBody>
      </Card>
    </VStack>
  )
}
