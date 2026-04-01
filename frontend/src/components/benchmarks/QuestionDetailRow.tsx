'use client'

import { useState } from 'react'
import { Box, HStack, VStack, Text, Badge, Collapse } from '@chakra-ui/react'
import { FiChevronDown, FiChevronRight } from 'react-icons/fi'

interface QuestionDetailRowProps {
  questionId: string
  question: string
  category: string
  score: number
  answer?: string
  evaluation?: Record<string, any>
  groundTruth?: Record<string, any>
  accentColor?: string
}

export function QuestionDetailRow({
  questionId,
  question,
  category,
  score,
  answer,
  evaluation,
  groundTruth,
  accentColor = '#f97316',
}: QuestionDetailRowProps) {
  const [expanded, setExpanded] = useState(false)

  const pct = Math.round(score * 100)
  const statusColor = pct >= 70 ? '#22c55e' : pct >= 50 ? '#eab308' : '#ef4444'
  const passed = pct >= 50

  return (
    <Box
      bg={expanded ? 'var(--bg-elevated, #1a1a35)' : 'transparent'}
      borderBottom="1px solid"
      borderColor="var(--border-subtle, #1e1e3a)"
      _hover={{ bg: 'var(--bg-elevated, #1a1a35)' }}
      transition="background 0.15s"
    >
      {/* Header row — always visible */}
      <HStack
        as="button"
        onClick={() => setExpanded(!expanded)}
        w="100%"
        px={4}
        py={2.5}
        spacing={3}
        cursor="pointer"
        align="center"
      >
        <Box as={expanded ? FiChevronDown : FiChevronRight} color="var(--text-muted, #475569)" fontSize="sm" flexShrink={0} />

        {/* Score badge */}
        <Badge
          fontFamily="'Fira Code', monospace"
          fontSize="12px"
          fontWeight="700"
          bg={`${statusColor}18`}
          color={statusColor}
          border="1px solid"
          borderColor={`${statusColor}40`}
          px={2}
          py={0.5}
          rounded="md"
          minW="48px"
          textAlign="center"
          flexShrink={0}
        >
          {pct}%
        </Badge>

        {/* Category badge */}
        <Badge
          fontSize="10px"
          bg={`${accentColor}18`}
          color={accentColor}
          px={2}
          rounded="sm"
          flexShrink={0}
        >
          {category.replace(/_/g, ' ')}
        </Badge>

        {/* Question text */}
        <Text
          fontSize="13px"
          color="var(--text-secondary, #94a3b8)"
          noOfLines={1}
          flex={1}
          textAlign="left"
        >
          {question}
        </Text>

        {/* Pass/Fail indicator */}
        <Badge
          fontSize="10px"
          bg={passed ? '#22c55e18' : '#ef444418'}
          color={passed ? '#22c55e' : '#ef4444'}
          px={2}
          rounded="sm"
          flexShrink={0}
        >
          {passed ? 'OK' : 'ECHEC'}
        </Badge>
      </HStack>

      {/* Expanded detail */}
      <Collapse in={expanded} animateOpacity>
        <Box px={4} pb={4} pl={12}>
          <Box
            bg="var(--bg-card, #12122a)"
            border="1px solid"
            borderColor="var(--border-subtle, #1e1e3a)"
            rounded="lg"
            p={4}
          >
            <SimpleDetailGrid>
              {/* Expected behavior */}
              {groundTruth?.expected_behavior && (
                <DetailItem
                  label="Comportement attendu"
                  value={groundTruth.expected_behavior.replace(/_/g, ' ')}
                />
              )}

              {/* Evidence claim */}
              {groundTruth?.evidence_claim && (
                <DetailItem
                  label="Evidence (ground truth)"
                  value={groundTruth.evidence_claim}
                  mono
                />
              )}

              {/* Correct fact (false_premise) */}
              {groundTruth?.correct_fact && (
                <DetailItem
                  label="Fait correct"
                  value={groundTruth.correct_fact}
                />
              )}

              {/* Reason (unanswerable) */}
              {groundTruth?.reason && (
                <DetailItem
                  label="Raison attendue"
                  value={groundTruth.reason}
                />
              )}

              {/* Answer */}
              {answer && (
                <DetailItem
                  label="Reponse OSMOSIS"
                  value={answer}
                  maxChars={300}
                />
              )}

              {/* Evaluation details */}
              {evaluation && (
                <Box mt={2} pt={2} borderTop="1px solid" borderColor="var(--border-subtle, #1e1e3a)">
                  <Text fontSize="11px" fontWeight="600" color="var(--text-muted, #475569)" mb={1}>
                    Metriques d'evaluation
                  </Text>
                  <HStack flexWrap="wrap" spacing={2}>
                    {Object.entries(evaluation)
                      .filter(([k]) => k !== 'category' && k !== 'score' && k !== 'error')
                      .map(([k, v]) => (
                        <Badge
                          key={k}
                          fontSize="10px"
                          fontFamily="'Fira Code', monospace"
                          bg="var(--bg-base, #0a0a1a)"
                          color="var(--text-secondary, #94a3b8)"
                          px={2}
                          py={0.5}
                        >
                          {k}: {typeof v === 'number' ? v.toFixed(2) : String(v)}
                        </Badge>
                      ))}
                  </HStack>
                </Box>
              )}
            </SimpleDetailGrid>
          </Box>
        </Box>
      </Collapse>
    </Box>
  )
}

function SimpleDetailGrid({ children }: { children: React.ReactNode }) {
  return <VStack align="stretch" spacing={2}>{children}</VStack>
}

function DetailItem({ label, value, mono, maxChars }: { label: string; value: string; mono?: boolean; maxChars?: number }) {
  const displayValue = maxChars && value.length > maxChars
    ? value.slice(0, maxChars) + '...'
    : value

  return (
    <Box>
      <Text fontSize="11px" fontWeight="600" color="var(--text-muted, #475569)" mb={0.5}>
        {label}
      </Text>
      <Text
        fontSize="12px"
        color="var(--text-secondary, #94a3b8)"
        fontFamily={mono ? "'Fira Code', monospace" : undefined}
        lineHeight="1.5"
        whiteSpace="pre-wrap"
      >
        {displayValue}
      </Text>
    </Box>
  )
}
