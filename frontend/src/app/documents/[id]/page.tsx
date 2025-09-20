'use client'

import {
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  Flex,
  HStack,
  Text,
  VStack,
  Badge,
  Divider,
  Spinner,
  Center,
  IconButton,
  useToast,
} from '@chakra-ui/react'
import { ArrowBackIcon, DownloadIcon, DeleteIcon } from '@chakra-ui/icons'
import { useRouter, useParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Document } from '@/types/api'

const StatusBadge = ({ status }: { status: Document['status'] }) => {
  const colorScheme = {
    pending: 'yellow',
    processing: 'blue',
    completed: 'green',
    failed: 'red',
  }

  return (
    <Badge colorScheme={colorScheme[status]} variant="subtle" size="lg">
      {status.toUpperCase()}
    </Badge>
  )
}

export default function DocumentDetailPage() {
  const router = useRouter()
  const params = useParams()
  const toast = useToast()
  const queryClient = useQueryClient()
  const documentId = params.id as string

  const {
    data: documentResponse,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => api.documents.get(documentId),
    enabled: !!documentId,
  })

  const deleteDocumentMutation = useMutation({
    mutationFn: (id: string) => api.documents.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      toast({
        title: 'Success',
        description: 'Document deleted successfully',
        status: 'success',
        duration: 3000,
        isClosable: true,
      })
      router.push('/documents')
    },
    onError: (error: any) => {
      toast({
        title: 'Error',
        description: error?.response?.data?.message || 'Failed to delete document',
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
    },
  })

  const handleDelete = () => {
    if (confirm('Are you sure you want to delete this document? This action cannot be undone.')) {
      deleteDocumentMutation.mutate(documentId)
    }
  }

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString()
  }

  if (isLoading) {
    return (
      <Center h="400px">
        <Spinner size="xl" color="brand.500" />
      </Center>
    )
  }

  if (error || !documentResponse?.success) {
    return (
      <Card>
        <CardBody>
          <Center py={12}>
            <VStack spacing={4}>
              <Text fontSize="lg" color="red.500">
                Document not found
              </Text>
              <Button onClick={() => router.push('/documents')}>
                Back to Documents
              </Button>
            </VStack>
          </Center>
        </CardBody>
      </Card>
    )
  }

  const document: Document = documentResponse.data as Document

  return (
    <VStack spacing={6} align="stretch">
      {/* Header */}
      <Flex justify="space-between" align="center">
        <HStack spacing={4}>
          <IconButton
            aria-label="Go back"
            icon={<ArrowBackIcon />}
            onClick={() => router.push('/documents')}
            variant="ghost"
          />
          <Text fontSize="2xl" fontWeight="bold">
            Document Details
          </Text>
        </HStack>
        <HStack spacing={2}>
          <Button leftIcon={<DownloadIcon />} variant="outline" size="sm">
            Download
          </Button>
          <Button
            leftIcon={<DeleteIcon />}
            colorScheme="red"
            variant="outline"
            size="sm"
            onClick={handleDelete}
            isLoading={deleteDocumentMutation.isPending}
          >
            Delete
          </Button>
        </HStack>
      </Flex>

      {/* Document Info */}
      <Card>
        <CardHeader>
          <Flex justify="space-between" align="start">
            <VStack align="start" spacing={2}>
              <Text fontSize="xl" fontWeight="semibold">
                {document.title || document.filename}
              </Text>
              <Text fontSize="sm" color="gray.600">
                {document.filename}
              </Text>
            </VStack>
            <StatusBadge status={document.status} />
          </Flex>
        </CardHeader>
        <CardBody>
          <VStack align="stretch" spacing={4}>
            <Divider />

            {/* Basic Information */}
            <Box>
              <Text fontWeight="semibold" mb={2}>Basic Information</Text>
              <VStack align="stretch" spacing={2}>
                <Flex justify="space-between">
                  <Text color="gray.600">File Type:</Text>
                  <Text fontWeight="medium">{document.file_type.toUpperCase()}</Text>
                </Flex>
                <Flex justify="space-between">
                  <Text color="gray.600">File Size:</Text>
                  <Text fontWeight="medium">{formatFileSize(document.file_size)}</Text>
                </Flex>
                <Flex justify="space-between">
                  <Text color="gray.600">Uploaded:</Text>
                  <Text fontWeight="medium">{formatDate(document.created_at)}</Text>
                </Flex>
                <Flex justify="space-between">
                  <Text color="gray.600">Last Updated:</Text>
                  <Text fontWeight="medium">{formatDate(document.updated_at)}</Text>
                </Flex>
              </VStack>
            </Box>

            {/* Metadata */}
            {document.metadata && Object.keys(document.metadata).length > 0 && (
              <>
                <Divider />
                <Box>
                  <Text fontWeight="semibold" mb={2}>Metadata</Text>
                  <VStack align="stretch" spacing={2}>
                    {document.metadata.pages && (
                      <Flex justify="space-between">
                        <Text color="gray.600">Pages:</Text>
                        <Text fontWeight="medium">{document.metadata.pages}</Text>
                      </Flex>
                    )}
                    {document.metadata.word_count && (
                      <Flex justify="space-between">
                        <Text color="gray.600">Word Count:</Text>
                        <Text fontWeight="medium">{document.metadata.word_count.toLocaleString()}</Text>
                      </Flex>
                    )}
                    {document.metadata.language && (
                      <Flex justify="space-between">
                        <Text color="gray.600">Language:</Text>
                        <Text fontWeight="medium">{document.metadata.language}</Text>
                      </Flex>
                    )}
                  </VStack>
                </Box>
              </>
            )}

            {/* Content Preview */}
            {document.content && (
              <>
                <Divider />
                <Box>
                  <Text fontWeight="semibold" mb={2}>Content Preview</Text>
                  <Box
                    p={4}
                    bg="gray.50"
                    borderRadius="md"
                    maxH="300px"
                    overflow="auto"
                  >
                    <Text fontSize="sm" whiteSpace="pre-wrap">
                      {document.content.length > 1000
                        ? `${document.content.substring(0, 1000)}...`
                        : document.content
                      }
                    </Text>
                  </Box>
                </Box>
              </>
            )}

            {/* Processing Status */}
            {document.status === 'failed' && (
              <>
                <Divider />
                <Box>
                  <Text fontWeight="semibold" mb={2} color="red.600">
                    Processing Error
                  </Text>
                  <Text fontSize="sm" color="red.500">
                    This document failed to process. Please try uploading it again or contact support if the issue persists.
                  </Text>
                </Box>
              </>
            )}

            {document.status === 'processing' && (
              <>
                <Divider />
                <Box>
                  <Text fontWeight="semibold" mb={2} color="blue.600">
                    Processing Status
                  </Text>
                  <Text fontSize="sm" color="blue.500">
                    This document is currently being processed. It will be available for search once processing is complete.
                  </Text>
                </Box>
              </>
            )}
          </VStack>
        </CardBody>
      </Card>
    </VStack>
  )
}