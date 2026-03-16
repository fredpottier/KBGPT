'use client'

import { useState } from 'react'
import {
  Box,
  VStack,
  HStack,
  Text,
  Button,
  Textarea,
  Icon,
  Spinner,
  Alert,
  AlertIcon,
  AlertDescription,
  Badge,
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverBody,
  PopoverArrow,
  useClipboard,
} from '@chakra-ui/react'
import { useMutation } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  FiSearch,
  FiEdit3,
  FiCheckCircle,
  FiXCircle,
  FiAlertCircle,
  FiHelpCircle,
  FiCopy,
  FiCheck,
  FiFile,
  FiRefreshCw,
} from 'react-icons/fi'
import { api } from '@/lib/api'
import type {
  VerificationResult,
  CorrectionResult,
  VerifyResponse,
  CorrectResponse,
  Assertion,
  VerificationStatus,
} from '@/types/verification'

// Status colors
const STATUS_CONFIG: Record<VerificationStatus, {
  bg: string
  border: string
  hoverBg: string
  label: string
  icon: typeof FiCheckCircle
  colorScheme: string
}> = {
  confirmed: {
    bg: 'rgba(34, 197, 94, 0.25)',
    border: '#22c55e',
    hoverBg: 'rgba(34, 197, 94, 0.4)',
    label: 'Confirmé',
    icon: FiCheckCircle,
    colorScheme: 'green',
  },
  contradicted: {
    bg: 'rgba(239, 68, 68, 0.25)',
    border: '#ef4444',
    hoverBg: 'rgba(239, 68, 68, 0.4)',
    label: 'Contredit',
    icon: FiXCircle,
    colorScheme: 'red',
  },
  incomplete: {
    bg: 'rgba(245, 158, 11, 0.25)',
    border: '#f59e0b',
    hoverBg: 'rgba(245, 158, 11, 0.4)',
    label: 'Incomplet',
    icon: FiAlertCircle,
    colorScheme: 'orange',
  },
  fallback: {
    bg: 'rgba(161, 161, 170, 0.15)',
    border: '#a1a1aa',
    hoverBg: 'rgba(161, 161, 170, 0.25)',
    label: 'RAG',
    icon: FiHelpCircle,
    colorScheme: 'gray',
  },
  unknown: {
    bg: 'rgba(61, 61, 92, 0.15)',
    border: '#3d3d5c',
    hoverBg: 'rgba(61, 61, 92, 0.25)',
    label: 'Inconnu',
    icon: FiHelpCircle,
    colorScheme: 'gray',
  },
}

// Evidence popover component
function EvidenceTooltip({ assertion }: { assertion: Assertion }) {
  const config = STATUS_CONFIG[assertion.status]
  // Meilleure preuve = celle avec la plus haute confiance
  const bestEvidence = assertion.evidence.length > 0
    ? [...assertion.evidence].sort((a, b) => b.confidence - a.confidence)[0]
    : null
  const otherCount = assertion.evidence.length - 1
  const uniqueDocs = new Set(assertion.evidence.map(e => e.sourceDoc)).size

  // Nettoyer le texte de la preuve : tronquer, retirer les artefacts tabulaires
  const cleanEvidenceText = (text: string): string => {
    if (!text) return ''
    // Retirer le préfixe [FACTUAL], [VALEUR ALTERNATIVE] etc.
    let cleaned = text.replace(/^\[[\w\s]+\]\s*/i, '')
    // Retirer les sauts de ligne multiples et les tabulations (résidus de tableaux)
    cleaned = cleaned.replace(/[\t]+/g, ' ').replace(/\n{2,}/g, ' ').replace(/\s{3,}/g, ' ')
    // Si ça ressemble à un tableau (beaucoup de chiffres séparés par des espaces), tronquer
    const numberDensity = (cleaned.match(/\d+[.,]?\d*/g) || []).length / cleaned.split(' ').length
    if (numberDensity > 0.4 && cleaned.length > 150) {
      // Garder la première phrase significative
      const firstSentence = cleaned.match(/^[^.!?]+[.!?]/)
      if (firstSentence) return firstSentence[0]
    }
    // Tronquer à 200 chars
    if (cleaned.length > 200) return cleaned.slice(0, 200) + '…'
    return cleaned
  }

  // Extraire un nom de document lisible depuis le doc_id
  const cleanDocName = (docId: string): string => {
    if (!docId) return 'Source inconnue'
    // PMC1234567_title_of_the_article_hash → Title Of The Article
    const parts = docId.split('_')
    if (parts.length > 2) {
      return parts.slice(1, -1).join(' ').replace(/\b\w/g, c => c.toUpperCase()).slice(0, 60)
    }
    return docId.slice(0, 60)
  }

  // Libellé du verdict
  const verdictLabel: Record<string, string> = {
    confirmed: 'Cette affirmation est confirmée par le corpus',
    contradicted: 'Cette affirmation est contredite par le corpus',
    incomplete: 'Information partielle — détails manquants',
    fallback: 'Trouvé dans les documents mais pas dans les claims vérifiées',
    unknown: 'Aucune information trouvée dans le corpus',
  }

  return (
    <VStack align="stretch" spacing={2} p={3} maxW="380px">
      {/* Verdict clair */}
      <HStack spacing={2}>
        <Icon as={config.icon} boxSize={4} color={`${config.colorScheme}.400`} />
        <Text fontSize="sm" fontWeight="semibold" color="text.primary">
          {config.label}
        </Text>
        <Text fontSize="xs" color="text.muted" ml="auto">
          {Math.round(assertion.confidence * 100)}%
        </Text>
      </HStack>

      <Text fontSize="xs" color="text.secondary" lineHeight="1.4">
        {verdictLabel[assertion.status] || ''}
      </Text>

      {bestEvidence ? (
        <VStack align="stretch" spacing={1.5}>
          {/* Citation source — nettoyée */}
          <Box
            p={2.5}
            bg="bg.primary"
            rounded="md"
            borderLeft="3px solid"
            borderLeftColor={`${config.colorScheme}.400`}
          >
            <Text color="text.primary" fontSize="xs" lineHeight="1.5" fontStyle="italic">
              « {cleanEvidenceText(bestEvidence.text)} »
            </Text>
          </Box>

          {/* Contradictions connues */}
          {(bestEvidence as any).comparison_details?.contradictions && (
            <Box p={2} bg="red.900" rounded="md" borderLeft="2px solid" borderLeftColor="red.400">
              <Text fontSize="xs" color="red.200" fontWeight="semibold" mb={1}>
                Contradiction connue dans le corpus :
              </Text>
              <Text fontSize="xs" color="red.100" fontStyle="italic">
                {(bestEvidence as any).comparison_details.contradictions}
              </Text>
            </Box>
          )}

          {/* Source document */}
          <HStack spacing={1.5} color="text.muted" fontSize="xs">
            <Icon as={FiFile} boxSize={3} flexShrink={0} />
            <Text noOfLines={1} title={bestEvidence.sourceDoc}>
              {cleanDocName(bestEvidence.sourceDoc)}
            </Text>
          </HStack>

          {/* Autres sources */}
          {otherCount > 0 && (
            <Text fontSize="xs" color="text.muted">
              + {otherCount} autre{otherCount > 1 ? 's' : ''} source{otherCount > 1 ? 's' : ''}
              {uniqueDocs > 1 && ` (${uniqueDocs} documents)`}
            </Text>
          )}
        </VStack>
      ) : (
        <Text fontSize="xs" color="text.muted" fontStyle="italic">
          Aucune source trouvée dans le corpus
        </Text>
      )}
    </VStack>
  )
}

// Annotated text display
function AnnotatedTextDisplay({
  text,
  assertions,
}: {
  text: string
  assertions: Assertion[]
}) {
  // Build segments from text and assertions
  const segments: Array<{ text: string; assertion?: Assertion }> = []
  const sorted = [...assertions].sort((a, b) => a.startIndex - b.startIndex)

  let currentPos = 0
  for (const assertion of sorted) {
    if (assertion.startIndex > currentPos) {
      segments.push({ text: text.slice(currentPos, assertion.startIndex) })
    }
    const segmentText = text.slice(assertion.startIndex, assertion.endIndex)
    if (segmentText) {
      segments.push({ text: segmentText, assertion })
      currentPos = assertion.endIndex
    }
  }
  if (currentPos < text.length) {
    segments.push({ text: text.slice(currentPos) })
  }

  return (
    <Box
      bg="bg.secondary"
      p={4}
      rounded="xl"
      border="1px solid"
      borderColor="border.default"
      minH="200px"
      lineHeight="1.8"
      fontSize="md"
      color="text.primary"
      whiteSpace="pre-wrap"
    >
      {segments.map((segment, i) =>
        segment.assertion ? (
          <Popover key={i} trigger="hover" placement="top" isLazy>
            <PopoverTrigger>
              <Text
                as="span"
                bg={STATUS_CONFIG[segment.assertion.status].bg}
                borderBottom="2px solid"
                borderColor={STATUS_CONFIG[segment.assertion.status].border}
                cursor="pointer"
                px="2px"
                rounded="sm"
                transition="all 0.2s"
                _hover={{
                  bg: STATUS_CONFIG[segment.assertion.status].hoverBg,
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
              rounded="lg"
              _focus={{ outline: 'none' }}
            >
              <PopoverArrow bg="bg.tertiary" />
              <PopoverBody p={0}>
                <EvidenceTooltip assertion={segment.assertion} />
              </PopoverBody>
            </PopoverContent>
          </Popover>
        ) : (
          <Text as="span" key={i}>{segment.text}</Text>
        )
      )}
    </Box>
  )
}

// Summary badges
function SummaryBadges({ summary }: { summary: VerificationResult['summary'] }) {
  const items = [
    { key: 'confirmed', label: 'Confirmé', color: 'green', icon: FiCheckCircle },
    { key: 'contradicted', label: 'Contredit', color: 'red', icon: FiXCircle },
    { key: 'incomplete', label: 'Incomplet', color: 'orange', icon: FiAlertCircle },
  ] as const

  return (
    <HStack spacing={3} flexWrap="wrap">
      {items.map(({ key, label, color, icon }) => (
        summary[key] > 0 && (
          <Badge
            key={key}
            colorScheme={color}
            variant="subtle"
            px={2}
            py={1}
            rounded="md"
            fontSize="sm"
          >
            <HStack spacing={1}>
              <Icon as={icon} boxSize={3} />
              <Text>{summary[key]} {label.toLowerCase()}</Text>
            </HStack>
          </Badge>
        )
      ))}
      {summary.total === 0 && (
        <Text fontSize="sm" color="text.muted">Aucune assertion détectée</Text>
      )}
    </HStack>
  )
}

export default function VerifyPage() {
  const [inputText, setInputText] = useState('')
  const [mode, setMode] = useState<'edit' | 'result'>('edit')
  const [result, setResult] = useState<VerificationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { hasCopied, onCopy } = useClipboard(inputText)

  // Analyze mutation
  const analyzeMutation = useMutation<VerifyResponse, Error, string>({
    mutationFn: async (text: string) => {
      const response = await api.verify.analyze(text)
      if (!response.success) {
        throw new Error(response.error || 'Erreur lors de l\'analyse')
      }
      return response.data as VerifyResponse
    },
    onSuccess: (data: VerifyResponse) => {
      const converted: VerificationResult = {
        originalText: data.original_text,
        assertions: data.assertions.map((a) => ({
          id: a.id,
          text: a.text,
          startIndex: a.start_index,
          endIndex: a.end_index,
          status: a.status,
          confidence: a.confidence,
          evidence: a.evidence.map((e) => ({
            type: e.type,
            text: e.text,
            sourceDoc: e.source_doc,
            sourcePage: e.source_page,
            sourceSection: e.source_section,
            confidence: e.confidence,
            relationship: e.relationship,
          })),
        })),
        summary: data.summary,
      }
      setResult(converted)
      setMode('result')
      setError(null)
    },
    onError: (err: Error) => {
      setError(err.message)
    },
  })

  // Correct mutation
  const correctMutation = useMutation<CorrectResponse, Error, void>({
    mutationFn: async () => {
      if (!result) throw new Error('Aucun résultat à corriger')

      const assertionsForApi = result.assertions.map((a) => ({
        id: a.id,
        text: a.text,
        start_index: a.startIndex,
        end_index: a.endIndex,
        status: a.status,
        confidence: a.confidence,
        evidence: a.evidence.map((e) => ({
          type: e.type,
          text: e.text,
          source_doc: e.sourceDoc,
          source_page: e.sourcePage,
          source_section: e.sourceSection,
          confidence: e.confidence,
          relationship: e.relationship,
        })),
      }))

      const response = await api.verify.correct(inputText, assertionsForApi)
      if (!response.success) {
        throw new Error(response.error || 'Erreur lors de la correction')
      }
      return response.data as CorrectResponse
    },
    onSuccess: (data: CorrectResponse) => {
      setInputText(data.corrected_text)
      setResult(null)
      setMode('edit')
      setError(null)
    },
    onError: (err: Error) => {
      setError(err.message)
    },
  })

  const handleAnalyze = () => {
    if (inputText.trim().length >= 10) {
      analyzeMutation.mutate(inputText)
    }
  }

  const handleEdit = () => {
    setMode('edit')
  }

  const handleReset = () => {
    setInputText('')
    setResult(null)
    setMode('edit')
    setError(null)
  }

  const needsCorrection = result && (
    result.summary.contradicted > 0 || result.summary.incomplete > 0
  )

  const isLoading = analyzeMutation.isPending || correctMutation.isPending

  return (
    <Box minH="calc(100vh - 64px)" bg="bg.primary" pt="64px">
      <Box maxW="900px" mx="auto" p={6}>
        {/* Header */}
        <HStack justify="space-between" mb={4}>
          <VStack align="start" spacing={0}>
            <Text fontSize="xl" fontWeight="bold" color="text.primary">
              Vérificateur de Texte
            </Text>
            <Text fontSize="sm" color="text.muted">
              Vérifiez vos affirmations contre la base de connaissances
            </Text>
          </VStack>
          {(result || inputText) && (
            <Button
              size="sm"
              variant="ghost"
              leftIcon={<FiRefreshCw />}
              onClick={handleReset}
            >
              Réinitialiser
            </Button>
          )}
        </HStack>

        {/* Error alert */}
        {error && (
          <Alert status="error" rounded="lg" mb={4}>
            <AlertIcon />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Main content area */}
        <AnimatePresence mode="wait">
          {mode === 'edit' ? (
            <motion.div
              key="edit"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              {/* Edit mode */}
              <Textarea
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="Collez ou saisissez le texte à vérifier..."
                minH="250px"
                bg="bg.secondary"
                border="1px solid"
                borderColor="border.default"
                rounded="xl"
                p={4}
                fontSize="md"
                lineHeight="1.8"
                color="text.primary"
                resize="vertical"
                _placeholder={{ color: 'text.muted' }}
                _hover={{ borderColor: 'border.hover' }}
                _focus={{
                  borderColor: 'brand.500',
                  boxShadow: '0 0 0 1px var(--chakra-colors-brand-500)',
                }}
                isDisabled={isLoading}
              />

              <HStack mt={4} justify="space-between">
                <Text fontSize="sm" color="text.muted">
                  {inputText.length} caractères
                </Text>
                <Button
                  leftIcon={isLoading ? <Spinner size="sm" /> : <FiSearch />}
                  bg="brand.500"
                  color="white"
                  onClick={handleAnalyze}
                  isLoading={analyzeMutation.isPending}
                  loadingText="Analyse..."
                  isDisabled={inputText.trim().length < 10}
                  _hover={{ bg: 'brand.600' }}
                >
                  Vérifier
                </Button>
              </HStack>
            </motion.div>
          ) : (
            <motion.div
              key="result"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              {/* Result mode */}
              {result && (
                <VStack align="stretch" spacing={4}>
                  {/* Summary */}
                  <HStack justify="space-between" flexWrap="wrap" gap={2}>
                    <SummaryBadges summary={result.summary} />
                    <Text fontSize="sm" color="text.muted">
                      Survolez le texte pour voir les sources
                    </Text>
                  </HStack>

                  {/* Annotated text */}
                  <AnnotatedTextDisplay
                    text={result.originalText}
                    assertions={result.assertions}
                  />

                  {/* Action buttons */}
                  <HStack justify="space-between" flexWrap="wrap" gap={2}>
                    <HStack spacing={2}>
                      <Button
                        leftIcon={<FiEdit3 />}
                        variant="outline"
                        onClick={handleEdit}
                      >
                        Modifier
                      </Button>
                      <Button
                        leftIcon={hasCopied ? <FiCheck /> : <FiCopy />}
                        variant="ghost"
                        onClick={onCopy}
                        size="sm"
                      >
                        {hasCopied ? 'Copié' : 'Copier'}
                      </Button>
                    </HStack>

                    {needsCorrection && (
                      <Button
                        leftIcon={correctMutation.isPending ? <Spinner size="sm" /> : <FiCheckCircle />}
                        colorScheme="orange"
                        onClick={() => correctMutation.mutate()}
                        isLoading={correctMutation.isPending}
                        loadingText="Correction..."
                      >
                        Corriger automatiquement
                      </Button>
                    )}
                  </HStack>
                </VStack>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </Box>
    </Box>
  )
}
