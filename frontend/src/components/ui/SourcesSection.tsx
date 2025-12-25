'use client'

/**
 * OSMOS Sources Section - Dark Elegance Edition
 */

import {
  Box,
  Text,
  VStack,
  HStack,
  Link,
  Icon,
} from '@chakra-ui/react'
import { SynthesisResult } from '@/types/api'
import { FiFileText } from 'react-icons/fi'

interface SourcesSectionProps {
  synthesis: SynthesisResult
}

const FILE_TYPE_CONFIG: Record<string, { color: string; bg: string }> = {
  PDF: { color: 'red.400', bg: 'rgba(239, 68, 68, 0.15)' },
  PPTX: { color: 'orange.400', bg: 'rgba(251, 146, 60, 0.15)' },
  PPT: { color: 'orange.400', bg: 'rgba(251, 146, 60, 0.15)' },
  XLSX: { color: 'green.400', bg: 'rgba(34, 197, 94, 0.15)' },
  XLS: { color: 'green.400', bg: 'rgba(34, 197, 94, 0.15)' },
  DOCX: { color: 'blue.400', bg: 'rgba(96, 165, 250, 0.15)' },
  DOC: { color: 'blue.400', bg: 'rgba(96, 165, 250, 0.15)' },
  DEFAULT: { color: 'gray.400', bg: 'rgba(156, 163, 175, 0.15)' },
}

export default function SourcesSection({ synthesis }: SourcesSectionProps) {
  const getDocumentName = (sourceFile: string) => {
    return sourceFile.split('/').pop() || sourceFile
  }

  const getFileExtension = (filename: string) => {
    const ext = filename.split('.').pop()?.toUpperCase()
    return ext || 'FILE'
  }

  const getFileTypeConfig = (extension: string) => {
    return FILE_TYPE_CONFIG[extension] || FILE_TYPE_CONFIG.DEFAULT
  }

  if (!synthesis.sources_used || synthesis.sources_used.length === 0) {
    return null
  }

  return (
    <Box w="full">
      <VStack spacing={2} align="stretch">
        {/* Header */}
        <HStack spacing={2}>
          <Icon as={FiFileText} boxSize={4} color="text.muted" />
          <Text fontSize="xs" fontWeight="medium" color="text.muted">
            Sources
          </Text>
          <HStack
            px={1.5}
            py={0.5}
            bg="rgba(99, 102, 241, 0.15)"
            rounded="full"
          >
            <Text fontSize="2xs" fontWeight="medium" color="brand.400">
              {synthesis.sources_used.length}
            </Text>
          </HStack>
        </HStack>

        {/* Sources list */}
        <HStack spacing={2} flexWrap="wrap">
          {synthesis.sources_used.map((source, index) => {
            const filename = getDocumentName(source)
            const extension = getFileExtension(filename)
            const config = getFileTypeConfig(extension)

            return (
              <Link
                key={index}
                href={source}
                isExternal
                px={2}
                py={1}
                bg="bg.tertiary"
                border="1px solid"
                borderColor="border.default"
                borderRadius="md"
                fontSize="xs"
                color="text.secondary"
                _hover={{
                  bg: 'bg.hover',
                  borderColor: 'border.active',
                  color: 'text.primary',
                }}
                display="inline-flex"
                alignItems="center"
                gap={1.5}
                transition="all 0.2s"
              >
                <HStack
                  px={1.5}
                  py={0.5}
                  bg={config.bg}
                  rounded="sm"
                >
                  <Text fontSize="2xs" fontWeight="bold" color={config.color}>
                    {extension}
                  </Text>
                </HStack>
                <Text noOfLines={1} maxW="150px">
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
