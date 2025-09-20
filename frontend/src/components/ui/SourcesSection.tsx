'use client'

import {
  Box,
  Text,
  VStack,
  HStack,
  Link,
  Icon,
  Divider,
} from '@chakra-ui/react'
import { ExternalLinkIcon, DownloadIcon } from '@chakra-ui/icons'
import { SynthesisResult } from '@/types/api'

interface SourcesSectionProps {
  synthesis: SynthesisResult
}

export default function SourcesSection({ synthesis }: SourcesSectionProps) {

  const getDocumentName = (sourceFile: string) => {
    return sourceFile.split('/').pop() || sourceFile
  }

  const getFileExtension = (filename: string) => {
    const ext = filename.split('.').pop()?.toUpperCase()
    return ext || 'FILE'
  }

  const getFileTypeColor = (extension: string) => {
    switch (extension) {
      case 'PDF':
        return 'red.500'
      case 'PPTX':
      case 'PPT':
        return 'orange.500'
      case 'XLSX':
      case 'XLS':
        return 'green.500'
      case 'DOCX':
      case 'DOC':
        return 'blue.500'
      default:
        return 'gray.500'
    }
  }

  if (!synthesis.sources_used || synthesis.sources_used.length === 0) {
    return null
  }

  return (
    <Box w="full">
      <VStack spacing={4} align="stretch">
        {/* Header */}
        <Text fontSize="lg" fontWeight="semibold" color="gray.700">
          📎 Sources utilisées
        </Text>

        <Divider />

        {/* Sources list */}
        <Box
          bg="blue.50"
          p={4}
          borderRadius="lg"
          border="1px solid"
          borderColor="blue.200"
        >
          <VStack spacing={3} align="stretch">
            {synthesis.sources_used.map((source, index) => {
              const filename = getDocumentName(source)
              const extension = getFileExtension(filename)

              return (
                <HStack
                  key={index}
                  spacing={3}
                  p={3}
                  bg="white"
                  borderRadius="md"
                  border="1px solid"
                  borderColor="gray.200"
                  _hover={{
                    borderColor: 'blue.300',
                    shadow: 'sm'
                  }}
                  transition="all 0.2s"
                >
                  {/* File type indicator */}
                  <Box
                    bg={getFileTypeColor(extension)}
                    color="white"
                    px={2}
                    py={1}
                    borderRadius="md"
                    fontSize="xs"
                    fontWeight="bold"
                    minW="50px"
                    textAlign="center"
                  >
                    {extension}
                  </Box>

                  {/* File info */}
                  <VStack spacing={1} align="start" flex="1">
                    <Text
                      fontSize="sm"
                      fontWeight="medium"
                      color="gray.800"
                      noOfLines={1}
                    >
                      {filename}
                    </Text>
                    <Text fontSize="xs" color="gray.500">
                      Source {index + 1} sur {synthesis.sources_used.length}
                    </Text>
                  </VStack>

                  {/* Download link */}
                  <Link
                    href={source}
                    isExternal
                    color="blue.600"
                    _hover={{ color: 'blue.800' }}
                    display="flex"
                    alignItems="center"
                    gap={1}
                    fontSize="sm"
                    fontWeight="medium"
                  >
                    <DownloadIcon w={3} h={3} />
                    Télécharger
                    <ExternalLinkIcon w={3} h={3} />
                  </Link>
                </HStack>
              )
            })}
          </VStack>
        </Box>

        {/* Summary */}
        <Text fontSize="xs" color="gray.500" textAlign="center">
          {synthesis.sources_used.length} document{synthesis.sources_used.length > 1 ? 's' : ''} utilisé{synthesis.sources_used.length > 1 ? 's' : ''} pour générer cette réponse
        </Text>
      </VStack>
    </Box>
  )
}