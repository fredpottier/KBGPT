'use client'

import {
  Box,
  Text,
  VStack,
  HStack,
  Link,
} from '@chakra-ui/react'
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
      <VStack spacing={1} align="stretch">
        {/* Header compact */}
        <Text fontSize="xs" fontWeight="medium" color="gray.500">
          Sources ({synthesis.sources_used.length})
        </Text>

        {/* Sources list - inline compact */}
        <HStack spacing={1} flexWrap="wrap">
          {synthesis.sources_used.map((source, index) => {
            const filename = getDocumentName(source)
            const extension = getFileExtension(filename)

            return (
              <Link
                key={index}
                href={source}
                isExternal
                px={1.5}
                py={0.5}
                bg="gray.100"
                borderRadius="sm"
                fontSize="2xs"
                color="gray.600"
                _hover={{ bg: 'blue.100', color: 'blue.700' }}
                display="inline-flex"
                alignItems="center"
                gap={0.5}
              >
                <Text as="span" fontWeight="medium" color={getFileTypeColor(extension)}>
                  {extension}
                </Text>
                <Text as="span" noOfLines={1} maxW="120px">
                  {filename.replace(`.${extension.toLowerCase()}`, '')}
                </Text>
              </Link>
            )
          })}
        </HStack>
      </VStack>
    </Box>
  )
}