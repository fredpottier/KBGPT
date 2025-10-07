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
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  Badge,
  List,
  ListItem,
  Divider,
  Spinner,
  Center,
  Checkbox,
  CheckboxGroup,
  Stack,
} from '@chakra-ui/react'
import { ArrowBackIcon, AttachmentIcon } from '@chakra-ui/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import axios from 'axios'
import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'

interface SuggestedEntityType {
  name: string
  confidence: number
  examples: string[]
  description: string
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
  const [analyzedFile, setAnalyzedFile] = useState<File | null>(null)
  const [analysisJobId, setAnalysisJobId] = useState<string | null>(null)
  const [suggestedTypes, setSuggestedTypes] = useState<SuggestedEntityType[]>([])
  const [selectedSuggested, setSelectedSuggested] = useState<string[]>([])

  // Templates
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)

  const { data: templatesData } = useQuery({
    queryKey: ['document-type-templates'],
    queryFn: async () => {
      const response = await axios.get('/api/document-types/templates')
      return response.data
    },
  })

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

  const analyzeMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData()
      formData.append('file', file)
      if (contextPrompt) {
        formData.append('context_prompt', contextPrompt)
      }
      const response = await axios.post('/api/document-types/analyze', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return response.data
    },
    onSuccess: (data) => {
      setAnalysisJobId(data.job_id)
      toast({
        title: 'Analyse en cours',
        description: 'Le LLM analyse votre document...',
        status: 'info',
        duration: 3000,
        isClosable: true,
      })
      // Simuler le polling des résultats (à implémenter proprement avec un vrai polling)
      setTimeout(() => {
        // Mock des résultats pour l'instant
        setSuggestedTypes([
          {
            name: 'SOLUTION',
            confidence: 0.95,
            examples: ['SAP S/4HANA', 'SAP BTP'],
            description: 'Solution SAP mentionnée',
          },
          {
            name: 'TECHNOLOGY',
            confidence: 0.88,
            examples: ['Cloud', 'API'],
            description: 'Technologie utilisée',
          },
        ])
      }, 2000)
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

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      const file = acceptedFiles[0]
      setAnalyzedFile(file)
      analyzeMutation.mutate(file)
    }
  }, [analyzeMutation])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
    },
    multiple: false,
    maxSize: 50 * 1024 * 1024, // 50MB
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

  const handleApplyTemplate = (templateSlug: string) => {
    const template = templatesData?.templates?.find((t: any) => t.slug === templateSlug)
    if (template) {
      setName(template.name)
      setSlug(template.slug)
      setDescription(template.description)
      setContextPrompt(template.context_prompt || '')
      setManualEntityTypes(template.entity_types || [])
      setSelectedTemplate(templateSlug)
      toast({
        title: 'Template appliqué',
        status: 'success',
        duration: 2000,
        isClosable: true,
      })
    }
  }

  const handleCreate = () => {
    // Combiner les types manuels et suggérés sélectionnés
    const allEntityTypes = [
      ...manualEntityTypes,
      ...selectedSuggested.filter((s) => !manualEntityTypes.includes(s)),
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
          <Tabs>
            <TabList>
              <Tab>Manuel</Tab>
              <Tab>Analyse LLM</Tab>
              <Tab>Templates</Tab>
            </TabList>

            <TabPanels>
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
                          : 'Glissez-déposez un document exemple (PDF/PPTX)'}
                      </Text>
                      {analyzedFile && (
                        <Badge colorScheme="green">
                          {analyzedFile.name} ({(analyzedFile.size / (1024 * 1024)).toFixed(2)} MB)
                        </Badge>
                      )}
                    </VStack>
                  </Box>

                  {analyzeMutation.isPending && (
                    <Center py={8}>
                      <VStack spacing={4}>
                        <Spinner size="xl" color="blue.500" />
                        <Text color="gray.600">Analyse du document en cours...</Text>
                      </VStack>
                    </Center>
                  )}

                  {suggestedTypes.length > 0 && (
                    <Box>
                      <Text fontSize="sm" fontWeight="semibold" mb={3}>
                        Types suggérés par le LLM ({suggestedTypes.length})
                      </Text>
                      <CheckboxGroup
                        value={selectedSuggested}
                        onChange={(values) => setSelectedSuggested(values as string[])}
                      >
                        <Stack spacing={3}>
                          {suggestedTypes.map((type) => (
                            <Card key={type.name} size="sm" variant="outline">
                              <CardBody>
                                <HStack justify="space-between">
                                  <Checkbox value={type.name}>
                                    <VStack align="start" spacing={1}>
                                      <HStack>
                                        <Badge colorScheme="blue">{type.name}</Badge>
                                        <Badge colorScheme="green">
                                          {(type.confidence * 100).toFixed(0)}%
                                        </Badge>
                                      </HStack>
                                      <Text fontSize="xs" color="gray.600">
                                        {type.description}
                                      </Text>
                                      <Text fontSize="xs" color="gray.500">
                                        Exemples: {type.examples.join(', ')}
                                      </Text>
                                    </VStack>
                                  </Checkbox>
                                </HStack>
                              </CardBody>
                            </Card>
                          ))}
                        </Stack>
                      </CheckboxGroup>
                    </Box>
                  )}
                </VStack>
              </TabPanel>

              {/* Templates */}
              <TabPanel>
                <VStack spacing={3} align="stretch">
                  {templatesData?.templates?.map((template: any) => (
                    <Card
                      key={template.slug}
                      variant="outline"
                      cursor="pointer"
                      onClick={() => handleApplyTemplate(template.slug)}
                      bg={selectedTemplate === template.slug ? 'blue.50' : 'white'}
                      borderColor={selectedTemplate === template.slug ? 'blue.400' : 'gray.200'}
                      _hover={{ borderColor: 'blue.400', bg: 'blue.50' }}
                    >
                      <CardBody>
                        <VStack align="start" spacing={2}>
                          <HStack>
                            <Text fontWeight="semibold">{template.name}</Text>
                            <Badge colorScheme="purple">{template.slug}</Badge>
                          </HStack>
                          <Text fontSize="sm" color="gray.600">
                            {template.description}
                          </Text>
                          <HStack spacing={2} flexWrap="wrap">
                            {template.entity_types?.map((type: string) => (
                              <Badge key={type} colorScheme="blue" fontSize="xs">
                                {type}
                              </Badge>
                            ))}
                          </HStack>
                        </VStack>
                      </CardBody>
                    </Card>
                  ))}
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
              Utilisez l'analyse LLM pour identifier automatiquement les types d'entités pertinents à
              partir d'un document exemple. Vous pouvez ensuite affiner manuellement.
            </Text>
          </VStack>
        </CardBody>
      </Card>
    </VStack>
  )
}
