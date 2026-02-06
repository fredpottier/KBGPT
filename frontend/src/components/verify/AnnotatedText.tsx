'use client'

import { Box, Text } from '@chakra-ui/react'
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverBody,
  PopoverArrow,
} from '@chakra-ui/react'
import { EvidencePopover } from './EvidencePopover'
import type { Assertion, VerificationStatus } from '@/types/verification'

// Background colors for each status (with transparency)
const STATUS_COLORS: Record<VerificationStatus, string> = {
  confirmed: 'rgba(34, 197, 94, 0.25)',
  contradicted: 'rgba(239, 68, 68, 0.25)',
  incomplete: 'rgba(245, 158, 11, 0.25)',
  fallback: 'rgba(161, 161, 170, 0.15)',
  unknown: 'rgba(61, 61, 92, 0.15)',
}

// Border colors for each status
const STATUS_BORDER: Record<VerificationStatus, string> = {
  confirmed: '#22c55e',
  contradicted: '#ef4444',
  incomplete: '#f59e0b',
  fallback: '#a1a1aa',
  unknown: '#3d3d5c',
}

// Hover colors (slightly more opaque)
const STATUS_HOVER: Record<VerificationStatus, string> = {
  confirmed: 'rgba(34, 197, 94, 0.4)',
  contradicted: 'rgba(239, 68, 68, 0.4)',
  incomplete: 'rgba(245, 158, 11, 0.4)',
  fallback: 'rgba(161, 161, 170, 0.25)',
  unknown: 'rgba(61, 61, 92, 0.25)',
}

interface Segment {
  text: string
  assertion?: Assertion
}

function buildSegments(text: string, assertions: Assertion[]): Segment[] {
  if (assertions.length === 0) {
    return [{ text }]
  }

  // Sort assertions by start index
  const sorted = [...assertions].sort((a, b) => a.startIndex - b.startIndex)

  const segments: Segment[] = []
  let currentPos = 0

  for (const assertion of sorted) {
    // Add plain text before this assertion
    if (assertion.startIndex > currentPos) {
      segments.push({
        text: text.slice(currentPos, assertion.startIndex),
      })
    }

    // Add the assertion segment
    // Use the actual text from the document to handle position mismatches
    const assertionText = text.slice(assertion.startIndex, assertion.endIndex)
    if (assertionText) {
      segments.push({
        text: assertionText,
        assertion,
      })
      currentPos = assertion.endIndex
    } else {
      // Fallback: use assertion's own text if positions don't match
      segments.push({
        text: assertion.text,
        assertion,
      })
      // Try to find where this text actually is
      const actualPos = text.indexOf(assertion.text, currentPos)
      if (actualPos >= 0) {
        currentPos = actualPos + assertion.text.length
      }
    }
  }

  // Add remaining text after last assertion
  if (currentPos < text.length) {
    segments.push({
      text: text.slice(currentPos),
    })
  }

  return segments
}

interface AnnotatedTextProps {
  text: string
  assertions: Assertion[]
}

export function AnnotatedText({ text, assertions }: AnnotatedTextProps) {
  const segments = buildSegments(text, assertions)

  return (
    <Box
      bg="bg.secondary"
      p={4}
      rounded="xl"
      border="1px solid"
      borderColor="border.default"
      lineHeight="1.8"
      fontSize="md"
      color="text.primary"
      whiteSpace="pre-wrap"
      wordBreak="break-word"
    >
      {segments.map((segment, i) =>
        segment.assertion ? (
          <Popover key={i} trigger="hover" placement="top" isLazy>
            <PopoverTrigger>
              <Text
                as="span"
                bg={STATUS_COLORS[segment.assertion.status]}
                borderBottom="2px solid"
                borderColor={STATUS_BORDER[segment.assertion.status]}
                cursor="pointer"
                transition="all 0.2s"
                rounded="sm"
                px="1px"
                _hover={{
                  bg: STATUS_HOVER[segment.assertion.status],
                }}
              >
                {segment.text}
              </Text>
            </PopoverTrigger>
            <PopoverContent
              bg="bg.tertiary"
              border="1px solid"
              borderColor="border.default"
              boxShadow="xl"
              rounded="xl"
              _focus={{ outline: 'none' }}
            >
              <PopoverArrow bg="bg.tertiary" />
              <PopoverBody p={0}>
                <EvidencePopover assertion={segment.assertion} />
              </PopoverBody>
            </PopoverContent>
          </Popover>
        ) : (
          <Text as="span" key={i}>
            {segment.text}
          </Text>
        )
      )}
    </Box>
  )
}
