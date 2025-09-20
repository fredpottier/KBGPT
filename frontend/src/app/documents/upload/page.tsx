'use client'

import {
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  Center,
  Flex,
  HStack,
  Icon,
  Progress,
  Text,
  VStack,
  useToast,
} from '@chakra-ui/react'
import { AttachmentIcon, CheckCircleIcon, WarningIcon } from '@chakra-ui/icons'
import { useState, useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useDropzone } from 'react-dropzone'
import { api } from '@/lib/api'

interface UploadFile {
  file: File
  status: 'pending' | 'uploading' | 'success' | 'error'
  progress: number
  error?: string
}

export default function UploadPage() {
  const [uploadFiles, setUploadFiles] = useState<UploadFile[]>([])
  const toast = useToast()
  const router = useRouter()
  const queryClient = useQueryClient()

  const uploadMutation = useMutation({
    mutationFn: (file: File) => api.documents.upload(file),
    onSuccess: (response, file) => {
      setUploadFiles(prev =>
        prev.map(uf =>
          uf.file === file
            ? { ...uf, status: 'success', progress: 100 }
            : uf
        )
      )
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      toast({
        title: 'Success',
        description: `${file.name} uploaded successfully`,
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
    },
    onError: (error: any, file) => {
      setUploadFiles(prev =>
        prev.map(uf =>
          uf.file === file
            ? {
                ...uf,
                status: 'error',
                error: error?.response?.data?.message || 'Upload failed'
              }
            : uf
        )
      )
      toast({
        title: 'Error',
        description: `Failed to upload ${file.name}`,
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
    },
  })

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newUploadFiles = acceptedFiles.map(file => ({
      file,
      status: 'pending' as const,
      progress: 0,
    }))
    setUploadFiles(prev => [...prev, ...newUploadFiles])
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
    },
    maxSize: 50 * 1024 * 1024, // 50MB
  })

  const handleUpload = async () => {
    const pendingFiles = uploadFiles.filter(uf => uf.status === 'pending')

    for (const uploadFile of pendingFiles) {
      setUploadFiles(prev =>
        prev.map(uf =>
          uf === uploadFile
            ? { ...uf, status: 'uploading', progress: 0 }
            : uf
        )
      )

      // Simulate progress
      const progressInterval = setInterval(() => {
        setUploadFiles(prev =>
          prev.map(uf =>
            uf === uploadFile && uf.status === 'uploading'
              ? { ...uf, progress: Math.min(uf.progress + 10, 90) }
              : uf
          )
        )
      }, 100)

      try {
        await uploadMutation.mutateAsync(uploadFile.file)
      } finally {
        clearInterval(progressInterval)
      }
    }
  }

  const handleRemove = (fileToRemove: UploadFile) => {
    setUploadFiles(prev => prev.filter(uf => uf !== fileToRemove))
  }

  const handleClear = () => {
    setUploadFiles([])
  }

  const getStatusIcon = (status: UploadFile['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircleIcon color="green.500" />
      case 'error':
        return <WarningIcon color="red.500" />
      default:
        return <AttachmentIcon color="gray.500" />
    }
  }

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  const allComplete = uploadFiles.length > 0 && uploadFiles.every(uf => uf.status === 'success')
  const hasFiles = uploadFiles.length > 0
  const canUpload = uploadFiles.some(uf => uf.status === 'pending')

  return (
    <VStack spacing={6} align="stretch">
      {/* Upload Area */}
      <Card>
        <CardHeader>
          <Text fontSize="lg" fontWeight="semibold">
            Upload Documents
          </Text>
          <Text fontSize="sm" color="gray.600">
            Supported formats: PDF, DOC, DOCX, TXT, MD (Max: 50MB)
          </Text>
        </CardHeader>
        <CardBody>
          <Box
            {...getRootProps()}
            p={10}
            border="2px dashed"
            borderColor={isDragActive ? 'blue.400' : 'gray.300'}
            borderRadius="lg"
            cursor="pointer"
            bg={isDragActive ? 'blue.50' : 'gray.50'}
            transition="all 0.2s"
            _hover={{ borderColor: 'blue.400', bg: 'blue.50' }}
          >
            <input {...getInputProps()} />
            <Center>
              <VStack spacing={3}>
                <Icon as={AttachmentIcon} w={10} h={10} color="gray.400" />
                {isDragActive ? (
                  <Text>Drop the files here...</Text>
                ) : (
                  <VStack spacing={1}>
                    <Text fontWeight="medium">
                      Drag & drop files here, or click to select
                    </Text>
                    <Text fontSize="sm" color="gray.500">
                      Upload multiple files at once
                    </Text>
                  </VStack>
                )}
              </VStack>
            </Center>
          </Box>
        </CardBody>
      </Card>

      {/* File List */}
      {hasFiles && (
        <Card>
          <CardHeader>
            <Flex justify="space-between" align="center">
              <Text fontSize="lg" fontWeight="semibold">
                Files ({uploadFiles.length})
              </Text>
              <HStack spacing={2}>
                <Button size="sm" variant="outline" onClick={handleClear}>
                  Clear All
                </Button>
                {canUpload && (
                  <Button
                    size="sm"
                    colorScheme="blue"
                    onClick={handleUpload}
                    isLoading={uploadMutation.isPending}
                  >
                    Upload All
                  </Button>
                )}
                {allComplete && (
                  <Button
                    size="sm"
                    colorScheme="green"
                    onClick={() => router.push('/documents')}
                  >
                    View Documents
                  </Button>
                )}
              </HStack>
            </Flex>
          </CardHeader>
          <CardBody>
            <VStack spacing={3} align="stretch">
              {uploadFiles.map((uploadFile, index) => (
                <Box key={index} p={4} border="1px" borderColor="gray.200" borderRadius="md">
                  <Flex justify="space-between" align="center" mb={2}>
                    <HStack spacing={3} flex="1">
                      {getStatusIcon(uploadFile.status)}
                      <VStack align="start" spacing={0} flex="1">
                        <Text fontSize="sm" fontWeight="medium" noOfLines={1}>
                          {uploadFile.file.name}
                        </Text>
                        <Text fontSize="xs" color="gray.500">
                          {formatFileSize(uploadFile.file.size)}
                        </Text>
                      </VStack>
                    </HStack>
                    {uploadFile.status === 'pending' && (
                      <Button
                        size="xs"
                        variant="ghost"
                        onClick={() => handleRemove(uploadFile)}
                      >
                        Remove
                      </Button>
                    )}
                  </Flex>

                  {uploadFile.status === 'uploading' && (
                    <Progress
                      value={uploadFile.progress}
                      size="sm"
                      colorScheme="blue"
                      mt={2}
                    />
                  )}

                  {uploadFile.status === 'error' && (
                    <Text fontSize="xs" color="red.500" mt={1}>
                      {uploadFile.error}
                    </Text>
                  )}
                </Box>
              ))}
            </VStack>
          </CardBody>
        </Card>
      )}
    </VStack>
  )
}