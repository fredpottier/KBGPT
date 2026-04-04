'use client'

/**
 * SourcePill — Petite pastille de source inline, style ChatGPT.
 *
 * Affiche un nom de document court avec icone, dans un badge compact.
 * Cliquable pour expansion future (preview, navigation).
 */

import { HStack, Text, Box } from '@chakra-ui/react'
import { FiFileText } from 'react-icons/fi'

interface SourcePillProps {
  /** Nom du document (deja nettoye) */
  name: string
  /** Page/slide optionnel */
  page?: string
}

export default function SourcePill({ name, page }: SourcePillProps) {
  // Tronquer le nom si trop long
  const shortName = name.length > 35 ? name.substring(0, 32) + '...' : name

  return (
    <HStack
      as="span"
      display="inline-flex"
      spacing={1}
      px={1.5}
      py={0.5}
      bg="rgba(156, 163, 175, 0.12)"
      borderRadius="md"
      fontSize="2xs"
      color="text.muted"
      verticalAlign="middle"
      cursor="default"
      _hover={{ bg: 'rgba(156, 163, 175, 0.20)', color: 'text.secondary' }}
      transition="all 0.15s"
      lineHeight="1.4"
    >
      <Box as={FiFileText} boxSize="10px" flexShrink={0} />
      <Text as="span" fontSize="2xs" fontWeight="500" noOfLines={1}>
        {shortName}{page ? `, ${page}` : ''}
      </Text>
    </HStack>
  )
}


/**
 * Transforme le texte contenant des citations *(Document, p.XX)* en React nodes
 * avec des SourcePill inline.
 */
export function renderWithSourcePills(text: string): React.ReactNode {
  // Pattern : [[SOURCE:nom|page]] — marqueur custom du backend
  const pattern = /\[\[SOURCE:([^\]|]+?)(?:\|([^\]]+?))?\]\]/g

  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let match
  let key = 0

  while ((match = pattern.exec(text)) !== null) {
    // Texte avant la citation
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index))
    }

    const docName = match[1].trim()
    const page = match[2]?.trim()

    parts.push(
      <SourcePill key={`src-${key++}`} name={docName} page={page} />
    )

    lastIndex = match.index + match[0].length
  }

  // Texte restant
  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex))
  }

  return parts.length > 1 ? <>{parts}</> : text
}
