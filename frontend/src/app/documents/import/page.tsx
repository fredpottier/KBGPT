'use client'

/**
 * OSMOS Documents Import - Dark Elegance Edition
 *
 * Premium file upload experience with drag & drop
 */

import {
  Box,
  Button,
  FormControl,
  FormLabel,
  Text,
  VStack,
  useToast,
  Switch,
  HStack,
  Flex,
  Icon,
} from '@chakra-ui/react'
import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { CheckIcon } from '@chakra-ui/icons'
import { useMutation } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import { authService } from '@/lib/auth'
import {
  FiUploadCloud,
  FiFile,
  FiFileText,
  FiImage,
  FiArrowRight,
  FiInfo,
  FiCheckCircle,
  FiZap,
  FiCpu,
} from 'react-icons/fi'

const MotionBox = motion(Box)
const MotionFlex = motion(Flex)

interface FileUploadProps {
  onFileSelect: (file: File) => void
  selectedFile: File | null
  isUploading: boolean
}

// Get file icon based on type
const getFileIcon = (fileName: string) => {
  const ext = fileName.split('.').pop()?.toLowerCase()
  if (ext === 'pdf') return FiFileText
  if (ext === 'pptx' || ext === 'ppt') return FiImage
  return FiFile
}

// Premium Dropzone Component
const FileDropzone = ({ onFileSelect, selectedFile, isUploading }: FileUploadProps) => {
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
    maxSize: 200 * 1024 * 1024,
    disabled: isUploading,
  })

  return (
    <MotionBox
      {...getRootProps()}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Box
        p={10}
        border="2px dashed"
        borderColor={
          isDragActive
            ? 'brand.500'
            : selectedFile
              ? 'green.500'
              : 'border.default'
        }
        rounded="2xl"
        bg={
          isDragActive
            ? 'rgba(99, 102, 241, 0.1)'
            : selectedFile
              ? 'rgba(34, 197, 94, 0.05)'
              : 'bg.tertiary'
        }
        cursor={isUploading ? 'not-allowed' : 'pointer'}
        opacity={isUploading ? 0.6 : 1}
        transition="all 0.3s ease"
        position="relative"
        overflow="hidden"
        _hover={{
          borderColor: isUploading ? undefined : 'brand.500',
          bg: isUploading ? undefined : 'rgba(99, 102, 241, 0.05)',
          transform: isUploading ? undefined : 'translateY(-2px)',
          boxShadow: isUploading ? undefined : '0 0 30px rgba(99, 102, 241, 0.15)',
        }}
        _before={isDragActive ? {
          content: '""',
          position: 'absolute',
          inset: 0,
          bgGradient: 'linear(to-br, rgba(99, 102, 241, 0.1), transparent)',
          pointerEvents: 'none',
        } : undefined}
      >
        <input {...getInputProps()} />

        <AnimatePresence mode="wait">
          {selectedFile ? (
            <MotionFlex
              key="selected"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              direction="column"
              align="center"
              gap={4}
            >
              <Box
                w={16}
                h={16}
                rounded="2xl"
                bg="rgba(34, 197, 94, 0.15)"
                display="flex"
                alignItems="center"
                justifyContent="center"
                boxShadow="0 0 20px rgba(34, 197, 94, 0.2)"
              >
                <Icon
                  as={getFileIcon(selectedFile.name)}
                  boxSize={8}
                  color="green.400"
                />
              </Box>

              <VStack spacing={1}>
                <HStack spacing={2}>
                  <Icon as={FiCheckCircle} color="green.400" />
                  <Text fontWeight="semibold" color="green.400">
                    Fichier pret
                  </Text>
                </HStack>
                <Text fontSize="sm" color="text.secondary" textAlign="center">
                  {selectedFile.name}
                </Text>
                <Text fontSize="xs" color="text.muted">
                  {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB
                </Text>
              </VStack>

              <Text fontSize="xs" color="text.muted">
                Cliquez pour changer de fichier
              </Text>
            </MotionFlex>
          ) : (
            <MotionFlex
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              direction="column"
              align="center"
              gap={4}
            >
              <MotionBox
                animate={isDragActive ? { scale: 1.1, y: -5 } : { scale: 1, y: 0 }}
                transition={{ duration: 0.2 }}
              >
                <Box
                  w={16}
                  h={16}
                  rounded="2xl"
                  bg={isDragActive ? 'rgba(99, 102, 241, 0.2)' : 'bg.hover'}
                  display="flex"
                  alignItems="center"
                  justifyContent="center"
                  boxShadow={isDragActive ? '0 0 30px rgba(99, 102, 241, 0.3)' : undefined}
                  transition="all 0.3s ease"
                >
                  <Icon
                    as={FiUploadCloud}
                    boxSize={8}
                    color={isDragActive ? 'brand.400' : 'text.muted'}
                  />
                </Box>
              </MotionBox>

              <VStack spacing={1}>
                <Text fontWeight="semibold" color={isDragActive ? 'brand.400' : 'text.primary'}>
                  {isDragActive ? 'Deposez votre fichier ici' : 'Glissez-deposez votre fichier'}
                </Text>
                <Text fontSize="sm" color="text.muted">
                  ou cliquez pour parcourir
                </Text>
              </VStack>

              <HStack spacing={2} flexWrap="wrap" justify="center">
                {['PDF', 'PPTX', 'XLSX'].map((format) => (
                  <Box
                    key={format}
                    px={3}
                    py={1}
                    bg="bg.hover"
                    rounded="full"
                    fontSize="xs"
                    color="text.muted"
                  >
                    {format}
                  </Box>
                ))}
                <Text fontSize="xs" color="text.muted">max 200 MB</Text>
              </HStack>
            </MotionFlex>
          )}
        </AnimatePresence>
      </Box>
    </MotionBox>
  )
}

// Vision Mode Toggle Card
const VisionModeCard = ({
  useVision,
  setUseVision,
}: {
  useVision: boolean
  setUseVision: (value: boolean) => void
}) => (
  <MotionBox
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.3, delay: 0.1 }}
  >
    <Box
      bg="bg.secondary"
      border="1px solid"
      borderColor="border.default"
      rounded="xl"
      p={5}
      position="relative"
      overflow="hidden"
    >
      {/* Header */}
      <HStack justify="space-between" mb={4}>
        <HStack spacing={3}>
          <Box
            w={10}
            h={10}
            rounded="lg"
            bg={useVision ? 'rgba(99, 102, 241, 0.15)' : 'bg.tertiary'}
            display="flex"
            alignItems="center"
            justifyContent="center"
            transition="all 0.2s"
          >
            <Icon
              as={useVision ? FiCpu : FiZap}
              boxSize={5}
              color={useVision ? 'brand.400' : 'text.muted'}
            />
          </Box>
          <VStack align="start" spacing={0}>
            <Text fontWeight="medium" color="text.primary">
              Mode d'analyse
            </Text>
            <Text fontSize="xs" color="text.muted">
              Choisissez la methode d'extraction
            </Text>
          </VStack>
        </HStack>

        <FormControl display="flex" alignItems="center" w="auto">
          <Switch
            id="vision-mode"
            colorScheme="brand"
            isChecked={useVision}
            onChange={(e) => setUseVision(e.target.checked)}
            size="lg"
          />
        </FormControl>
      </HStack>

      {/* Mode Description */}
      <AnimatePresence mode="wait">
        <MotionBox
          key={useVision ? 'vision' : 'text'}
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.2 }}
        >
          <Box
            p={4}
            bg={useVision ? 'rgba(99, 102, 241, 0.08)' : 'rgba(34, 197, 94, 0.08)'}
            border="1px solid"
            borderColor={useVision ? 'rgba(99, 102, 241, 0.2)' : 'rgba(34, 197, 94, 0.2)'}
            rounded="lg"
          >
            <HStack align="start" spacing={3}>
              <Icon
                as={FiInfo}
                boxSize={4}
                color={useVision ? 'brand.400' : 'green.400'}
                mt={0.5}
              />
              <VStack align="start" spacing={1}>
                <Text fontSize="sm" fontWeight="medium" color={useVision ? 'brand.400' : 'green.400'}>
                  {useVision ? 'Mode Vision (GPT-4V)' : 'Mode Texte (Recommande)'}
                </Text>
                <Text fontSize="sm" color="text.secondary">
                  {useVision
                    ? 'Analyse les images et diagrammes avec GPT-4 Vision. Plus precis pour le contenu visuel complexe, mais plus couteux.'
                    : 'Extraction textuelle rapide et economique. Suffisant pour la plupart des documents SAP.'
                  }
                </Text>
              </VStack>
            </HStack>
          </Box>
        </MotionBox>
      </AnimatePresence>
    </Box>
  </MotionBox>
)

export default function ImportPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [useVision, setUseVision] = useState(false)

  const toast = useToast()
  const router = useRouter()

  const getFileType = (file: File): 'pptx' | 'pdf' | 'xlsx' => {
    const extension = file.name.split('.').pop()?.toLowerCase()
    if (extension === 'pdf') return 'pdf'
    if (extension === 'pptx' || extension === 'ppt') return 'pptx'
    return 'xlsx'
  }

  const uploadMutation = useMutation({
    mutationFn: async (formData: FormData) => {
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
      console.log('Reponse du serveur:', data)

      toast({
        title: 'Fichier envoye',
        description: 'Redirection vers le suivi des imports...',
        status: 'success',
        duration: 2000,
        isClosable: true,
        position: 'top',
      })

      setTimeout(() => {
        router.push('/documents/status')
      }, 1500)
    },
    onError: (error: any) => {
      console.error('Erreur d\'upload:', error)
      toast({
        title: 'Erreur d\'envoi',
        description: error.response?.data?.message || 'Echec de l\'envoi du fichier',
        status: 'error',
        duration: 5000,
        isClosable: true,
        position: 'top',
      })
    },
  })

  const handleSubmit = () => {
    if (!selectedFile) {
      toast({
        title: 'Aucun fichier selectionne',
        description: 'Veuillez selectionner un fichier avant de continuer',
        status: 'warning',
        duration: 3000,
        isClosable: true,
        position: 'top',
      })
      return
    }

    const formData = new FormData()
    formData.append('action_type', 'ingest')
    formData.append('document_type', getFileType(selectedFile))
    formData.append('use_vision', useVision.toString())
    formData.append('file', selectedFile)

    uploadMutation.mutate(formData)
  }

  return (
    <Box maxW="700px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={8}
      >
        <VStack align="start" spacing={2}>
          <HStack spacing={3}>
            <Box
              w={10}
              h={10}
              rounded="lg"
              bgGradient="linear(to-br, brand.500, accent.400)"
              display="flex"
              alignItems="center"
              justifyContent="center"
              boxShadow="0 0 20px rgba(99, 102, 241, 0.3)"
            >
              <Icon as={FiUploadCloud} boxSize={5} color="white" />
            </Box>
            <Text fontSize="2xl" fontWeight="bold" color="text.primary">
              Import de documents
            </Text>
          </HStack>
          <Text color="text.secondary" pl={13}>
            Enrichissez la base de connaissances OSMOS
          </Text>
        </VStack>
      </MotionBox>

      {/* Main Card */}
      <MotionBox
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.1 }}
      >
        <Box
          bg="rgba(26, 26, 46, 0.6)"
          backdropFilter="blur(12px)"
          border="1px solid"
          borderColor="border.default"
          rounded="2xl"
          p={6}
          boxShadow="0 0 40px rgba(0, 0, 0, 0.2)"
        >
          <VStack spacing={6} align="stretch">
            {/* Dropzone */}
            <FileDropzone
              onFileSelect={setSelectedFile}
              selectedFile={selectedFile}
              isUploading={uploadMutation.isPending}
            />

            {/* Vision Mode */}
            <VisionModeCard useVision={useVision} setUseVision={setUseVision} />

            {/* Submit Button */}
            <MotionBox
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3, delay: 0.2 }}
            >
              <Button
                w="full"
                size="lg"
                bg={selectedFile ? 'brand.500' : 'bg.tertiary'}
                color={selectedFile ? 'white' : 'text.muted'}
                rounded="xl"
                onClick={handleSubmit}
                isLoading={uploadMutation.isPending}
                loadingText="Envoi en cours..."
                isDisabled={!selectedFile}
                rightIcon={<FiArrowRight />}
                _hover={selectedFile ? {
                  bg: 'brand.600',
                  transform: 'translateY(-2px)',
                  boxShadow: '0 0 30px rgba(99, 102, 241, 0.4)',
                } : undefined}
                _active={{
                  transform: 'translateY(0)',
                }}
                transition="all 0.2s"
              >
                {selectedFile ? 'Envoyer le document' : 'Selectionnez un fichier'}
              </Button>
            </MotionBox>
          </VStack>
        </Box>
      </MotionBox>

      {/* Info Footer */}
      <MotionBox
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, delay: 0.3 }}
        mt={6}
      >
        <Text fontSize="xs" color="text.muted" textAlign="center">
          Les documents sont traites par OSMOS et indexes dans le Knowledge Graph
        </Text>
      </MotionBox>
    </Box>
  )
}
