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
  Spinner,
  Center,
  Checkbox,
  Divider,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
} from '@chakra-ui/react'
import { ArrowBackIcon, AttachmentIcon, DeleteIcon } from '@chakra-ui/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useState, useCallback, useRef, useEffect } from 'react'
import { useDropzone } from 'react-dropzone'
import axiosInstance from '@/lib/axios'

interface SuggestedEntityType {
  name: string
  confidence: number
  examples: string[]
  description: string
  is_existing: boolean
}

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

  // LLM Analysis
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [analysisJobId, setAnalysisJobId] = useState<string | null>(null)
  const [suggestedTypes, setSuggestedTypes] = useState<SuggestedEntityType[]>([])
  const [selectedSuggested, setSelectedSuggested] = useState<string[]>([])
  const [isPolling, setIsPolling] = useState(false)
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const [suggestedPrompt, setSuggestedPrompt] = useState<string>('')

  const createMutation = useMutation({
    mutationFn: async (data: any) => {
      const response = await axiosInstance.post('/api/document-types', data)
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

  const analyzeMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData()
      formData.append('file', file)
      if (contextPrompt) {
        formData.append('context_prompt', contextPrompt)
      }

      const response = await axiosInstance.post('/api/document-types/analyze', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        timeout: 120000, // 2 minutes timeout pour l'analyse Claude
      })
      return response.data
    },
    onSuccess: (data) => {
      // Réponse directe (synchrone)
      setSuggestedTypes(data.suggested_types || [])
      setSelectedSuggested((data.suggested_types || []).map((t: SuggestedEntityType) => t.name))

      // Récupérer le prompt suggéré et le placer dans le champ context_prompt
      if (data.suggested_context_prompt) {
        setSuggestedPrompt(data.suggested_context_prompt)
        setContextPrompt(data.suggested_context_prompt)
      }

      toast({
        title: 'Analyse terminée',
        description: `${data.suggested_types?.length || 0} types suggérés`,
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur d\'analyse',
        description: error.response?.data?.message || 'Échec de l\'analyse',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    },
  })

  const startPolling = (jobId: string) => {
    // Poll toutes les 2 secondes
    pollingIntervalRef.current = setInterval(async () => {
      try {
        const response = await axiosInstance.get(`/api/jobs/${jobId}`)
        const job = response.data

        if (job.status === 'completed' && job.result) {
          stopPolling()
          setSuggestedTypes(job.result.suggested_types || [])
          // Pré-sélectionner tous les types
          setSelectedSuggested((job.result.suggested_types || []).map((t: SuggestedEntityType) => t.name))
          toast({
            title: 'Analyse terminée',
            description: `${job.result.suggested_types?.length || 0} types suggérés`,
            status: 'success',
            duration: 3000,
            isClosable: true,
          })
        } else if (job.status === 'failed') {
          stopPolling()
          toast({
            title: 'Erreur d\'analyse',
            description: job.error || 'L\'analyse a échoué',
            status: 'error',
            duration: 5000,
            isClosable: true,
          })
        }
      } catch (error) {
        console.error('Polling error:', error)
      }
    }, 2000)
  }

  const stopPolling = () => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current)
      pollingIntervalRef.current = null
    }
    setIsPolling(false)
  }

  // Cleanup polling on unmount
  useEffect(() => {
    return () => stopPolling()
  }, [])

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      const file = acceptedFiles[0]
      setUploadedFile(file)
      analyzeMutation.mutate(file)
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
    },
    multiple: false,
    maxSize: 10 * 1024 * 1024, // 10MB (Claude limite: 32MB total, on laisse de la marge)
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

  const handleToggleSuggested = (typeName: string) => {
    setSelectedSuggested(prev =>
      prev.includes(typeName)
        ? prev.filter(t => t !== typeName)
        : [...prev, typeName]
    )
  }

  const handleCreate = () => {
    // Combiner types manuels et suggérés sélectionnés
    const allEntityTypes = [
      ...manualEntityTypes,
      ...selectedSuggested.filter(s => !manualEntityTypes.includes(s)),
    ]

    createMutation.mutate({
      name,
      slug,
      description,
      context_prompt: contextPrompt,
      is_active: isActive,
      entity_types: allEntityTypes,
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
              <FormLabel>
                Prompt Contextuel
                {suggestedPrompt && (
                  <Badge ml={2} colorScheme="purple" fontSize="xs">
                    ✨ Optimisé par IA
                  </Badge>
                )}
              </FormLabel>
              <Textarea
                value={contextPrompt}
                onChange={(e) => setContextPrompt(e.target.value)}
                placeholder="Prompt utilisé pour guider l'extraction LLM (peut être généré automatiquement après analyse)"
                rows={5}
                borderColor={suggestedPrompt ? 'purple.300' : undefined}
              />
              <Text fontSize="sm" color="gray.500" mt={1}>
                {suggestedPrompt
                  ? "✨ Ce prompt a été optimisé par l'IA suite à l'analyse du document. Vous pouvez le modifier si nécessaire."
                  : "Ce prompt sera injecté dans l'analyse LLM pour contextualiser l'extraction. Uploadez un document sample pour qu'il soit généré automatiquement."}
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
            Définissez les types d'entités pour ce document type
          </Text>
        </CardHeader>
        <CardBody>
          <Tabs>
            <TabList>
              <Tab>Analyse LLM</Tab>
              <Tab>Manuel</Tab>
            </TabList>

            <TabPanels>
              {/* Analyse LLM */}
              <TabPanel>
                <VStack spacing={4} align="stretch">
                  <Box
                    {...getRootProps()}
                    p={8}
                    border="2px dashed"
                    borderColor={isDragActive ? 'blue.400' : 'gray.300'}
                    borderRadius="lg"
                    bg={isDragActive ? 'blue.50' : 'gray.50'}
                    cursor="pointer"
                    transition="all 0.2s"
                    _hover={{
                      borderColor: 'blue.400',
                      bg: 'blue.50',
                    }}
                  >
                    <input {...getInputProps()} />
                    <VStack spacing={4}>
                      <AttachmentIcon boxSize={8} color={isDragActive ? 'blue.500' : 'gray.400'} />
                      <Text fontWeight="semibold" color={isDragActive ? 'blue.700' : 'gray.700'}>
                        {isDragActive
                          ? 'Déposez votre fichier ici'
                          : 'Glissez-déposez un document PDF exemple'}
                      </Text>
                      <Text fontSize="xs" color="gray.500">
                        Max 10 MB, 100 pages • Format PDF uniquement
                      </Text>
                      {uploadedFile && (
                        <Badge colorScheme="green" fontSize="sm">
                          {uploadedFile.name} ({(uploadedFile.size / (1024 * 1024)).toFixed(2)} MB)
                        </Badge>
                      )}
                    </VStack>
                  </Box>

                  {analyzeMutation.isPending && (
                    <Center py={8}>
                      <VStack spacing={4}>
                        <Spinner size="xl" color="blue.500" />
                        <Text color="gray.600">Analyse en cours...</Text>
                      </VStack>
                    </Center>
                  )}

                  {suggestedTypes.length > 0 && (
                    <Box>
                      <Text fontSize="sm" fontWeight="semibold" mb={3}>
                        Types suggérés ({suggestedTypes.length})
                      </Text>
                      <VStack spacing={2} align="stretch">
                        {suggestedTypes.map((type) => (
                          <Card key={type.name} size="sm" variant="outline">
                            <CardBody>
                              <HStack spacing={3}>
                                <Checkbox
                                  isChecked={selectedSuggested.includes(type.name)}
                                  onChange={() => handleToggleSuggested(type.name)}
                                />
                                <VStack align="start" spacing={1} flex={1}>
                                  <HStack>
                                    <Badge colorScheme="blue" fontSize="sm">{type.name}</Badge>
                                    <Badge
                                      colorScheme={type.is_existing ? 'green' : 'orange'}
                                      fontSize="xs"
                                    >
                                      {type.is_existing ? 'Existant' : 'Nouveau'}
                                    </Badge>
                                    <Badge colorScheme="purple" fontSize="xs">
                                      {(type.confidence * 100).toFixed(0)}%
                                    </Badge>
                                  </HStack>
                                  <Text fontSize="xs" color="gray.600">
                                    {type.description}
                                  </Text>
                                  {type.examples.length > 0 && (
                                    <Text fontSize="xs" color="gray.500">
                                      Exemples: {type.examples.slice(0, 3).join(', ')}
                                    </Text>
                                  )}
                                </VStack>
                              </HStack>
                            </CardBody>
                          </Card>
                        ))}
                      </VStack>
                    </Box>
                  )}
                </VStack>
              </TabPanel>

              {/* Manuel */}
              <TabPanel>
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
              </TabPanel>
            </TabPanels>
          </Tabs>
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
