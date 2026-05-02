'use client'

/**
 * SourcesFootnotes — Liste numérotée des sources en bas de réponse,
 * style Wikipedia footnotes.
 *
 * Couplé avec RefPill (pills inline `[N]`) — chaque entrée numérotée
 * correspond à un (doc_id, page) cité dans le texte.
 */

import { Box, Text, VStack, HStack, Icon, useToast } from '@chakra-ui/react'
import { FiFileText } from 'react-icons/fi'
import { formatDocumentName } from '@/lib/formatDocumentName'
import { openSourceFile } from '@/lib/openSourceFile'
import type { SourceRef } from '@/lib/sourceRefs'

interface SourcesFootnotesProps {
  refs: SourceRef[]
}

export default function SourcesFootnotes({ refs }: SourcesFootnotesProps) {
  const toast = useToast()

  if (!refs || refs.length === 0) return null

  const handleClick = async (docId: string) => {
    const err = await openSourceFile(docId)
    if (err) {
      toast({
        title: 'Source indisponible',
        description: `Impossible d'ouvrir le fichier source (${err.message})`,
        status: 'warning',
        duration: 4000,
        isClosable: true,
      })
    }
  }

  return (
    <Box
      mt={3}
      pt={3}
      borderTop="1px solid"
      borderColor="border.default"
      w="full"
    >
      <HStack spacing={2} mb={2}>
        <Icon as={FiFileText} boxSize={3.5} color="text.muted" />
        <Text fontSize="2xs" fontWeight="medium" color="text.muted" textTransform="uppercase" letterSpacing="wide">
          Sources
        </Text>
        <Text fontSize="2xs" color="text.muted" opacity={0.7}>
          ({refs.length})
        </Text>
      </HStack>
      <VStack spacing={1} align="stretch">
        {refs.map((ref, i) => {
          const idx = i + 1
          const displayName = formatDocumentName(ref.docId) || ref.docId
          return (
            <HStack
              key={idx}
              spacing={2}
              align="baseline"
              fontSize="xs"
              color="text.secondary"
              as="button"
              onClick={() => handleClick(ref.docId)}
              type="button"
              cursor="pointer"
              textAlign="left"
              borderRadius="sm"
              px={1}
              py={0.5}
              _hover={{ bg: 'bg.hover', color: 'text.primary' }}
              transition="all 0.15s"
              title={`Ouvrir : ${displayName}`}
            >
              <Text
                as="span"
                fontFamily="mono"
                fontSize="2xs"
                color="blue.300"
                minW="22px"
                fontWeight="600"
              >
                [{idx}]
              </Text>
              <Text as="span" flex="1" noOfLines={1}>
                {displayName}
              </Text>
            </HStack>
          )
        })}
      </VStack>
    </Box>
  )
}
