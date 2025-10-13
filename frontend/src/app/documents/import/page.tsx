'use client'

import {
  Box,
  Button,
  FormControl,
  FormLabel,
  Heading,
  Input,
  Select,
  Text,
  VStack,
  useToast,
  Card,
  CardBody,
  Divider,
  Spinner,
  Switch,
  HStack,
  Alert,
  AlertIcon,
  AlertDescription,
} from '@chakra-ui/react'
import { useState, useCallback, useEffect } from 'react'
import { useDropzone } from 'react-dropzone'
import { AttachmentIcon, CheckIcon } from '@chakra-ui/icons'
import { useMutation } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import axios from 'axios'
import { authService } from '@/lib/auth'
import { fetchWithAuth } from '@/lib/fetchWithAuth'

interface FileUploadProps {
  onFileSelect: (file: File) => void
  selectedFile: File | null
}

const FileDropzone = ({ onFileSelect, selectedFile }: FileUploadProps) => {
  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      onFileSelect(acceptedFiles[0])
    }
  }, [onFileSelect])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
      'application/vnd.ms-powerpoint': ['.ppt'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
    },
    multiple: false,
    maxSize: 200 * 1024 * 1024, // 200MB - Supporte les gros documents SAP
  })

  return (
    <Box
      {...getRootProps()}
      p={8}
      border="2px dashed"
      borderColor={isDragActive ? 'blue.400' : selectedFile ? 'green.400' : 'gray.300'}
      borderRadius="lg"
      bg={isDragActive ? 'blue.50' : selectedFile ? 'green.50' : 'gray.50'}
      cursor="pointer"
      transition="all 0.2s"
      _hover={{
        borderColor: 'blue.400',
        bg: 'blue.50',
      }}
    >
      <input {...getInputProps()} />
      <VStack spacing={4}>
        {selectedFile ? (
          <>
            <CheckIcon boxSize={8} color="green.500" />
            <Text fontWeight="semibold" color="green.700">
              Fichier sélectionné
            </Text>
            <Text fontSize="sm" color="green.600">
              {selectedFile.name} ({(selectedFile.size / (1024 * 1024)).toFixed(2)} MB)
            </Text>
          </>
        ) : (
          <>
            <AttachmentIcon boxSize={8} color={isDragActive ? 'blue.500' : 'gray.400'} />
            <Text fontWeight="semibold" color={isDragActive ? 'blue.700' : 'gray.700'}>
              {isDragActive ? 'Déposez votre fichier ici' : 'Glissez-déposez votre fichier ou cliquez pour sélectionner'}
            </Text>
            <Text fontSize="sm" color="gray.500">
              Formats acceptés : PDF, PPTX, PPT, XLSX, XLS (max 200 MB)
            </Text>
          </>
        )}
      </VStack>
    </Box>
  )
}


export default function ImportPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [client, setClient] = useState('')
  const [documentType, setDocumentType] = useState('')
  const [documentTypes, setDocumentTypes] = useState<any[]>([])
  const [loadingTypes, setLoadingTypes] = useState(true)
  const [useVision, setUseVision] = useState(false) // Vision désactivée par défaut

  const toast = useToast()
  const router = useRouter()

  // Charger les types de documents depuis l'API
  useEffect(() => {
    async function fetchDocumentTypes() {
      try {
        const token = authService.getAccessToken()

        if (!token) {
          console.error('Pas de token d\'authentification disponible')
          toast({
            title: 'Erreur d\'authentification',
            description: 'Veuillez vous reconnecter',
            status: 'error',
            duration: 3000,
            isClosable: true,
          })
          setLoadingTypes(false)
          return
        }

        const response = await fetchWithAuth('/api/document-types?is_active=true')

        if (!response.ok) {
          throw new Error(`Erreur ${response.status}`)
        }

        const data = await response.json()
        console.log('Document types chargés:', data)
        setDocumentTypes(data.document_types || [])
      } catch (error) {
        console.error('Erreur lors du chargement des types de documents:', error)
        toast({
          title: 'Erreur de chargement',
          description: 'Impossible de charger les types de documents',
          status: 'error',
          duration: 3000,
          isClosable: true,
        })
      } finally {
        setLoadingTypes(false)
      }
    }
    fetchDocumentTypes()
  }, [toast])

  // Fonction pour déterminer le type de document basé sur l'extension
  const getFileType = (file: File): 'pptx' | 'pdf' | 'xlsx' => {
    const extension = file.name.split('.').pop()?.toLowerCase()
    if (extension === 'pdf') return 'pdf'
    if (extension === 'pptx' || extension === 'ppt') return 'pptx'
    return 'xlsx'
  }


  const uploadMutation = useMutation({
    mutationFn: async (formData: FormData) => {
      // Get JWT token from auth service
      const token = authService.getAccessToken()

      const response = await axios.post('/api/dispatch', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
          'Authorization': `Bearer ${token}`,
        },
      })
      return response.data
    },
    onSuccess: (data) => {
      console.log('Réponse du serveur:', data)

      toast({
        title: 'Fichier envoyé !',
        description: 'Redirection vers le suivi des imports...',
        status: 'success',
        duration: 2000,
        isClosable: true,
      })

      // Rediriger vers la page de suivi après un court délai
      setTimeout(() => {
        router.push('/documents/status')
      }, 1500)
    },
    onError: (error: any) => {
      console.error('Erreur d\'upload:', error)
      toast({
        title: 'Erreur d\'envoi',
        description: error.response?.data?.message || 'Échec de l\'envoi du fichier',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    },
  })

  const handleSubmit = () => {
    if (!selectedFile) {
      toast({
        title: 'Aucun fichier sélectionné',
        description: 'Veuillez sélectionner un fichier avant de continuer',
        status: 'warning',
        duration: 3000,
        isClosable: true,
      })
      return
    }


    if (!documentType) {
      toast({
        title: 'Type de document manquant',
        description: 'Veuillez sélectionner un type de document',
        status: 'warning',
        duration: 3000,
        isClosable: true,
      })
      return
    }

    const formData = new FormData()
    formData.append('action_type', 'ingest')
    formData.append('document_type', getFileType(selectedFile))
    formData.append('document_type_id', documentType) // ID du document type sélectionné
    formData.append('use_vision', useVision.toString()) // Activer/désactiver Vision

    const metadata = {
      client: client.trim(),
    }

    formData.append('meta', JSON.stringify(metadata))
    formData.append('file', selectedFile)

    uploadMutation.mutate(formData)
  }


  return (
    <VStack spacing={6} align="stretch" maxW="800px" mx="auto">
      <Box>
        <Heading size="lg" mb={2}>
          Import de fichiers
        </Heading>
        <Text color="gray.600">
          Importez vos documents SAP dans la base de connaissances
        </Text>
      </Box>


      <Card>
        <CardBody>
          <VStack spacing={6} align="stretch">
            {/* Zone de dépôt de fichier */}
            <FileDropzone onFileSelect={setSelectedFile} selectedFile={selectedFile} />

            <Divider />

            {/* Formulaire de métadonnées */}
            {/* Note: La date source est maintenant automatiquement extraite des métadonnées PPTX */}
            <VStack spacing={4} align="stretch">
              <Heading size="md">Métadonnées du document</Heading>

              <FormControl>
                <FormLabel>Client (optionnel)</FormLabel>
                <Input
                  value={client}
                  onChange={(e) => setClient(e.target.value)}
                  placeholder="ex: Entreprise ABC"
                />
              </FormControl>

              <FormControl isRequired>
                <FormLabel>Type de document</FormLabel>
                <Select
                  value={documentType}
                  onChange={(e) => setDocumentType(e.target.value)}
                  placeholder={loadingTypes ? "Chargement..." : "Sélectionnez un type"}
                  isDisabled={loadingTypes}
                >
                  {loadingTypes ? (
                    <option disabled>Chargement des types...</option>
                  ) : (
                    documentTypes.map((dt) => (
                      <option key={dt.id} value={dt.id}>
                        {dt.name}
                      </option>
                    ))
                  )}
                </Select>
              </FormControl>
            </VStack>

            <Divider />

            {/* Toggle Vision */}
            <VStack spacing={4} align="stretch">
              <Heading size="md">Mode d'analyse</Heading>

              <FormControl display="flex" alignItems="center">
                <HStack spacing={3} width="100%">
                  <Switch
                    id="vision-mode"
                    colorScheme="blue"
                    isChecked={useVision}
                    onChange={(e) => setUseVision(e.target.checked)}
                  />
                  <FormLabel htmlFor="vision-mode" mb={0} fontWeight="semibold">
                    Activer Vision (GPT-4 avec images)
                  </FormLabel>
                </HStack>
              </FormControl>

              <Alert status={useVision ? "info" : "success"} variant="left-accent">
                <AlertIcon />
                <AlertDescription fontSize="sm">
                  {useVision ? (
                    <>
                      <strong>Mode Vision activé :</strong> Utilise GPT-4 Vision pour analyser les images
                      du document. Plus précis pour les diagrammes et contenus visuels complexes, mais plus coûteux.
                    </>
                  ) : (
                    <>
                      <strong>Mode Texte activé (recommandé) :</strong> Analyse uniquement le texte extrait
                      avec un LLM rapide. Plus économique et suffisant pour la plupart des documents.
                    </>
                  )}
                </AlertDescription>
              </Alert>
            </VStack>

            <Divider />

            {/* Bouton d'envoi */}
            <Button
              colorScheme="blue"
              size="lg"
              onClick={handleSubmit}
              isLoading={uploadMutation.isPending}
              loadingText="Envoi en cours..."
              isDisabled={!selectedFile || !documentType}
            >
              Envoyer le document
            </Button>
          </VStack>
        </CardBody>
      </Card>
    </VStack>
  )
}