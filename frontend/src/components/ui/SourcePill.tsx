'use client'

/**
 * SourcePill — Petite pastille de source inline, style ChatGPT.
 *
 * Affiche le nom lisible du document avec icone, dans un badge compact.
 * Cliquable → ouvre le fichier source dans un nouveau tab (CH-05.3).
 */

import { HStack, Text, Box, useToast } from '@chakra-ui/react'
import { FiFileText } from 'react-icons/fi'
import { formatDocumentName } from '@/lib/formatDocumentName'
import { openSourceFile } from '@/lib/openSourceFile'

interface SourcePillProps {
  /** doc_id brut (ex: "cs25_amdt_22_8e69026c") ou URL absolue */
  name: string
  /** Page/slide optionnel (ex: "p.433") */
  page?: string
}

export default function SourcePill({ name, page }: SourcePillProps) {
  const toast = useToast()
  const displayName = formatDocumentName(name) || name
  const shortName =
    displayName.length > 35 ? displayName.substring(0, 32) + '...' : displayName

  const handleClick = async () => {
    const err = await openSourceFile(name)
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
    <HStack
      as="button"
      onClick={handleClick}
      type="button"
      display="inline-flex"
      spacing={1}
      px={2}
      py={0.5}
      bg="rgba(120, 160, 220, 0.15)"
      border="1px solid"
      borderColor="rgba(120, 160, 220, 0.25)"
      borderRadius="full"
      fontSize="2xs"
      color="blue.300"
      verticalAlign="middle"
      cursor="pointer"
      _hover={{
        bg: 'rgba(120, 160, 220, 0.30)',
        color: 'blue.200',
        borderColor: 'rgba(120, 160, 220, 0.45)',
      }}
      transition="all 0.15s"
      lineHeight="1.4"
      title={`Ouvrir : ${displayName}${page ? ' ' + page : ''}`}
    >
      <Box as={FiFileText} boxSize="10px" flexShrink={0} opacity={0.8} />
      <Text as="span" fontSize="2xs" fontWeight="600" noOfLines={1}>
        {shortName}
        {page ? ` ${page}` : ''}
      </Text>
    </HStack>
  )
}

/**
 * Transforme le texte contenant des citations [[SOURCE:doc_id|page]] en
 * React nodes avec des SourcePill inline cliquables. (Legacy — non utilisé
 * depuis CH-05.4 footnotes ; conservé au cas où d'autres consommateurs.)
 */
export function renderWithSourcePills(text: string): React.ReactNode {
  const pattern = /\[\[SOURCE:([^\]|]+?)(?:\|([^\]]+?))?\]\]/g

  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let match
  let key = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index))
    }

    const docName = match[1].trim()
    const page = match[2]?.trim()

    parts.push(<SourcePill key={`src-${key++}`} name={docName} page={page} />)

    lastIndex = match.index + match[0].length
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex))
  }

  return parts.length > 1 ? <>{parts}</> : text
}

// ============================================================================
// CH-05.4 — Footnotes-style refs : pills compactes [N] + liste détaillée en bas
// ============================================================================

import type { SourceRef } from '@/lib/sourceRefs'

interface RefPillProps {
  index: number // 1-based
  sourceRef: SourceRef // renommé `sourceRef` car `ref` est une prop réservée React
}

/**
 * Pill compacte `[N]` cliquable qui ouvre le fichier source du SourceRef.
 * Format Wikipedia footnotes — l'info détaillée est en bas via SourcesFootnotes.
 */
function RefPill({ index, sourceRef }: RefPillProps) {
  const toast = useToast()
  const displayName = formatDocumentName(sourceRef.docId) || sourceRef.docId
  const tooltip = `[${index}] ${displayName}${sourceRef.page ? ' ' + sourceRef.page : ''}`

  const handleClick = async () => {
    const err = await openSourceFile(sourceRef.docId, sourceRef.page)
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
      as="button"
      type="button"
      onClick={handleClick}
      display="inline-flex"
      alignItems="center"
      px={1}
      mx={0.5}
      h="14px"
      minW="20px"
      fontSize="2xs"
      fontWeight="600"
      color="blue.300"
      bg="rgba(120, 160, 220, 0.12)"
      border="1px solid"
      borderColor="rgba(120, 160, 220, 0.20)"
      borderRadius="sm"
      cursor="pointer"
      verticalAlign="text-top"
      lineHeight="1.2"
      _hover={{
        bg: 'rgba(120, 160, 220, 0.30)',
        color: 'blue.200',
        borderColor: 'rgba(120, 160, 220, 0.40)',
      }}
      transition="all 0.15s"
      title={tooltip}
    >
      [{index}]
    </Box>
  )
}

/**
 * Transforme le texte contenant des `[[REF:N]]` (post-`indexAndReplaceSources`)
 * en React nodes avec des RefPill compactes cliquables.
 *
 * @param text texte avec marqueurs [[REF:N]]
 * @param refs index ordonné des sources (refs[N-1] = SourceRef)
 */
export function renderWithRefs(
  text: string,
  refs: SourceRef[],
): React.ReactNode {
  const pattern = /\[\[REF:(\d+)\]\]/g

  const parts: React.ReactNode[] = []
  let lastIndex = 0
  let match
  let key = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index))
    }
    const idx = parseInt(match[1], 10)
    const ref = refs[idx - 1]
    if (ref) {
      parts.push(
        <RefPill key={`ref-${key++}`} index={idx} sourceRef={ref} />,
      )
    } else {
      // Fallback : index hors range, on affiche le marqueur brut
      parts.push(`[${idx}]`)
    }
    lastIndex = match.index + match[0].length
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex))
  }

  return parts.length > 1 ? <>{parts}</> : text
}
