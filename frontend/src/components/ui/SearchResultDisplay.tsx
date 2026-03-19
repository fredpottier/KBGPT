'use client'

/**
 * OSMOS Search Result Display - Dark Elegance Edition
 * avec Answer+Proof Integration
 */

import {
  VStack,
  Box,
  Text,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalBody,
  ModalCloseButton,
  Image,
  useDisclosure,
  Icon,
  HStack,
  Badge,
  Tooltip,
  Link,
  Wrap,
  WrapItem,
} from '@chakra-ui/react'
import {
  SearchResponse,
  SearchChunk,
  ExplorationIntelligence,
  ConfidenceResult,
  KnowledgeProofSummary,
  ReasoningTrace,
  CoverageMap,
  RelatedArticle,
  InsightHint,
} from '@/types/api'
import type { InstrumentedAnswer } from '@/types/instrumented'
import { useState } from 'react'
import ThumbnailCarousel from './ThumbnailCarousel'
import SynthesizedAnswer from './SynthesizedAnswer'
import SourcesSection from './SourcesSection'
import KnowledgeProofPanel from '../chat/KnowledgeProofPanel'
import ReasoningTracePanel from '../chat/ReasoningTracePanel'
import CoverageMapPanel from '../chat/CoverageMapPanel'
import { InstrumentedAnswerDisplay } from '../chat'
import type { GraphData, ProofGraph } from '@/types/graph'
import NextLink from 'next/link'
import {
  FiAlertTriangle,
  FiFileText,
  FiCheckCircle,
  FiAlertCircle,
  FiXCircle,
  FiHelpCircle,
  FiCompass,
  FiStar,
  FiLink,
  FiAlertOctagon,
} from 'react-icons/fi'

interface SearchResultDisplayProps {
  searchResult: SearchResponse
  graphData?: GraphData
  proofGraph?: ProofGraph  // 🌊 Phase 3.5+: Proof Graph prioritaire
  explorationIntelligence?: ExplorationIntelligence
  onSearch?: (query: string) => void
  instrumentedAnswer?: InstrumentedAnswer  // 🎯 OSMOSE Assertion-Centric
}

// Configuration du badge de confiance (Bloc A)
const CONFIDENCE_BADGE_CONFIG: Record<string, {
  icon: any
  colorScheme: string
  color: string
}> = {
  established: { icon: FiCheckCircle, colorScheme: 'green', color: 'green.400' },
  partial: { icon: FiAlertCircle, colorScheme: 'yellow', color: 'yellow.400' },
  debate: { icon: FiAlertTriangle, colorScheme: 'orange', color: 'orange.400' },
  incomplete: { icon: FiXCircle, colorScheme: 'red', color: 'red.400' },
  out_of_scope: { icon: FiHelpCircle, colorScheme: 'gray', color: 'gray.400' },
}

export default function SearchResultDisplay({
  searchResult,
  graphData,
  proofGraph,
  explorationIntelligence,
  onSearch,
  instrumentedAnswer,
}: SearchResultDisplayProps) {
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [selectedImage, setSelectedImage] = useState<SearchChunk | null>(null)

  const handleSlideClick = (chunk: SearchChunk) => {
    setSelectedImage(chunk)
    onOpen()
  }

  const getDocumentName = (sourceFile: string) => {
    return sourceFile.split('/').pop() || sourceFile
  }

  if (searchResult.status === 'no_results') {
    return (
      <Box
        p={4}
        bg="rgba(251, 191, 36, 0.1)"
        borderRadius="lg"
        border="1px solid"
        borderColor="orange.500"
      >
        <HStack spacing={3}>
          <Icon as={FiAlertTriangle} boxSize={5} color="orange.400" />
          <VStack align="start" spacing={0}>
            <Text fontSize="sm" fontWeight="medium" color="orange.400">
              Aucun resultat trouve
            </Text>
            <Text fontSize="xs" color="text.secondary">
              {searchResult.message || "Aucune information pertinente n'a ete trouvee dans la base de connaissances."}
            </Text>
          </VStack>
        </HStack>
      </Box>
    )
  }

  return (
    <VStack spacing={4} align="stretch" w="full">
      {/* Thumbnail Carousel */}
      {searchResult.results && searchResult.results.length > 0 && (
        <ThumbnailCarousel
          chunks={searchResult.results}
          synthesizedAnswer={searchResult.synthesis?.synthesized_answer}
        />
      )}

      {/* Bloc A: Badge de confiance (masque si instrumented) */}
      {searchResult.confidence && !instrumentedAnswer && (
        <ConfidenceBadge confidence={searchResult.confidence} />
      )}

      {/* Synthesized Answer : toujours affichée en premier (réponse LLM reformulée) */}
      {searchResult.synthesis && (
        <SynthesizedAnswer
          synthesis={searchResult.synthesis}
          chunks={searchResult.results}
          onSlideClick={handleSlideClick}
          graphData={graphData}
          proofGraph={proofGraph || searchResult.proof_graph}
          explorationIntelligence={explorationIntelligence}
          onSearch={onSearch}
        />
      )}

      {/* 🌊 Atlas Convergence: Explorer ce sujet */}
      {searchResult.related_articles && searchResult.related_articles.length > 0 && (
        <RelatedArticlesBlock articles={searchResult.related_articles} />
      )}

      {/* 🌊 Atlas Convergence: Insight Hints */}
      {searchResult.insight_hints && searchResult.insight_hints.length > 0 && (
        <InsightHintsBlock hints={searchResult.insight_hints} />
      )}

      {/* 🎯 OSMOSE Assertion-Centric: Preuves détaillées (sous la synthèse) */}
      {instrumentedAnswer && (
        <InstrumentedAnswerDisplay
          answer={instrumentedAnswer}
          chunks={searchResult.results}
          onSlideClick={handleSlideClick}
        />
      )}

      {/* Answer+Proof Panels (Blocs B, C, D) - Masques si instrumented car il a sa propre logique */}
      {!instrumentedAnswer && (
        <VStack spacing={3} align="stretch">
          {/* Bloc B: Knowledge Proof Summary */}
          {searchResult.knowledge_proof && (
            <KnowledgeProofPanel proof={searchResult.knowledge_proof} />
          )}

          {/* Bloc C: Reasoning Trace */}
          {searchResult.reasoning_trace && (
            <ReasoningTracePanel trace={searchResult.reasoning_trace} />
          )}

          {/* Bloc D: Coverage Map - DÉSACTIVÉ
           * Raison: Les sub_domains du DomainContext sont définis au setup,
           * mais les documents peuvent ne pas correspondre aux catégories prédéfinies.
           * Cela donne une fausse impression de mauvaise couverture.
           * À réactiver si on implémente une détection automatique des catégories
           * basée sur le contenu réel du Knowledge Graph.
           */}
          {/* {searchResult.coverage_map && (
            <CoverageMapPanel coverage={searchResult.coverage_map} />
          )} */}
        </VStack>
      )}

      {/* Sources Section */}
      {searchResult.synthesis && (
        <SourcesSection synthesis={searchResult.synthesis} />
      )}

      {/* Fallback: show raw results if no synthesis */}
      {!searchResult.synthesis && searchResult.results && searchResult.results.length > 0 && (
        <Box>
          <HStack spacing={2} mb={3}>
            <Icon as={FiFileText} boxSize={4} color="text.muted" />
            <Text fontSize="xs" fontWeight="medium" color="text.muted">
              Resultats
            </Text>
          </HStack>
          <VStack spacing={2} align="stretch">
            {searchResult.results.slice(0, 5).map((result, index) => (
              <Box
                key={index}
                p={3}
                bg="bg.secondary"
                borderRadius="lg"
                border="1px solid"
                borderColor="border.default"
                _hover={{ borderColor: 'border.active' }}
                transition="all 0.2s"
              >
                <Text fontSize="sm" mb={2} color="text.primary" lineHeight="tall">
                  {result.text.length > 150
                    ? result.text.substring(0, 150) + '...'
                    : result.text
                  }
                </Text>
                <Text fontSize="xs" color="text.muted">
                  {result.source_file.split('/').pop()}
                  {result.slide_index && ` • slide ${result.slide_index}`}
                </Text>
              </Box>
            ))}
          </VStack>
        </Box>
      )}

      {/* Modal for enlarged image when slide number is clicked */}
      <Modal isOpen={isOpen} onClose={onClose} size="6xl" isCentered>
        <ModalOverlay bg="rgba(0, 0, 0, 0.85)" backdropFilter="blur(8px)" />
        <ModalContent
          bg="bg.secondary"
          border="1px solid"
          borderColor="border.default"
          rounded="xl"
          maxW="85vw"
          maxH="90vh"
          overflow="hidden"
        >
          <ModalCloseButton color="text.muted" zIndex={10} />
          <ModalBody p={6}>
            {selectedImage && (
              <VStack spacing={4} align="center">
                <Box
                  borderRadius="lg"
                  overflow="hidden"
                  border="1px solid"
                  borderColor="border.default"
                >
                  <Image
                    src={selectedImage.slide_image_url}
                    alt={`Slide ${selectedImage.slide_index}`}
                    maxW="100%"
                    maxH="70vh"
                    objectFit="contain"
                  />
                </Box>
                <VStack spacing={1} align="center">
                  <Text fontSize="lg" fontWeight="semibold" color="text.primary">
                    Slide {selectedImage.slide_index}
                  </Text>
                  <Text fontSize="sm" color="text.secondary" textAlign="center">
                    {getDocumentName(selectedImage.source_file)}
                  </Text>
                </VStack>
              </VStack>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
    </VStack>
  )
}

// 🌊 Atlas Convergence: Bloc "Explorer ce sujet"
const TIER_BADGE: Record<number, { label: string; color: string }> = {
  1: { label: 'Portail', color: 'purple' },
  2: { label: 'Principal', color: 'blue' },
  3: { label: 'Specifique', color: 'gray' },
}

function RelatedArticlesBlock({ articles }: { articles: RelatedArticle[] }) {
  return (
    <Box
      p={4}
      bg="rgba(99, 102, 241, 0.06)"
      borderRadius="lg"
      border="1px solid"
      borderColor="rgba(99, 102, 241, 0.2)"
    >
      <HStack spacing={2} mb={3}>
        <Icon as={FiCompass} boxSize={4} color="brand.400" />
        <Text fontSize="sm" fontWeight="semibold" color="brand.400">
          Explorer ce sujet
        </Text>
      </HStack>
      <Wrap spacing={2}>
        {articles.map((article) => {
          const tier = TIER_BADGE[article.importance_tier] || TIER_BADGE[3]
          return (
            <WrapItem key={article.slug}>
              <Link
                as={NextLink}
                href={`/wiki/${article.slug}`}
                _hover={{ textDecoration: 'none' }}
              >
                <HStack
                  spacing={2}
                  px={3}
                  py={2}
                  bg="bg.secondary"
                  rounded="lg"
                  border="1px solid"
                  borderColor={article.is_recommended ? 'brand.500' : 'border.default'}
                  cursor="pointer"
                  transition="all 0.2s"
                  _hover={{
                    borderColor: 'brand.500',
                    bg: 'bg.tertiary',
                    transform: 'translateY(-1px)',
                    boxShadow: '0 2px 8px rgba(99, 102, 241, 0.15)',
                  }}
                >
                  {article.is_recommended && (
                    <Icon as={FiStar} boxSize={3.5} color="yellow.400" />
                  )}
                  <Text fontSize="sm" color="text.primary" fontWeight="medium">
                    {article.title}
                  </Text>
                  <Badge colorScheme={tier.color} fontSize="2xs" variant="subtle">
                    {tier.label}
                  </Badge>
                </HStack>
              </Link>
            </WrapItem>
          )
        })}
      </Wrap>
      {articles.some(a => a.is_recommended) && (
        <Text fontSize="2xs" color="text.muted" mt={2}>
          <Icon as={FiStar} boxSize={2.5} color="yellow.400" /> A lire en priorite
        </Text>
      )}
    </Box>
  )
}

// 🌊 Atlas Convergence: Bloc "A savoir" (Insight Hints)
const INSIGHT_ICON: Record<string, any> = {
  contradiction: FiAlertOctagon,
  structuring_concept: FiCompass,
  related_concept: FiLink,
  low_coverage: FiAlertCircle,
}

const INSIGHT_COLOR: Record<string, string> = {
  contradiction: 'orange.400',
  structuring_concept: 'brand.400',
  related_concept: 'cyan.400',
  low_coverage: 'yellow.400',
}

function InsightHintsBlock({ hints }: { hints: InsightHint[] }) {
  return (
    <Box
      p={4}
      bg="rgba(251, 191, 36, 0.04)"
      borderRadius="lg"
      border="1px solid"
      borderColor="rgba(251, 191, 36, 0.15)"
    >
      <HStack spacing={2} mb={3}>
        <Icon as={FiAlertCircle} boxSize={4} color="yellow.400" />
        <Text fontSize="sm" fontWeight="semibold" color="yellow.400">
          A savoir
        </Text>
      </HStack>
      <VStack spacing={2} align="stretch">
        {hints.map((hint, i) => {
          const IconComp = INSIGHT_ICON[hint.type] || FiAlertCircle
          const color = INSIGHT_COLOR[hint.type] || 'text.muted'
          return (
            <HStack key={i} spacing={3} align="start">
              <Icon as={IconComp} boxSize={4} color={color} mt={0.5} flexShrink={0} />
              <VStack align="start" spacing={0.5}>
                <Text fontSize="sm" color="text.secondary" lineHeight="short">
                  {hint.message}
                </Text>
                {hint.action_label && hint.action_href && (
                  <Link
                    as={NextLink}
                    href={hint.action_href}
                    fontSize="xs"
                    color="brand.400"
                    _hover={{ textDecoration: 'underline' }}
                  >
                    {hint.action_label}
                  </Link>
                )}
              </VStack>
            </HStack>
          )
        })}
      </VStack>
    </Box>
  )
}

// Composant Badge de Confiance (Bloc A)
interface ConfidenceBadgeProps {
  confidence: ConfidenceResult
}

function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  // Utiliser out_of_scope si hors perimetre, sinon l'etat epistemique
  const stateKey = confidence.contract_state === 'out_of_scope'
    ? 'out_of_scope'
    : confidence.epistemic_state

  const config = CONFIDENCE_BADGE_CONFIG[stateKey] || CONFIDENCE_BADGE_CONFIG.incomplete

  return (
    <Box
      p={3}
      bg="bg.secondary"
      borderRadius="lg"
      border="1px solid"
      borderColor="border.default"
    >
      <HStack spacing={3} justify="space-between">
        <HStack spacing={2}>
          <Icon as={config.icon} color={config.color} boxSize={5} />
          <VStack align="start" spacing={0}>
            <HStack spacing={2}>
              <Text fontSize="sm" fontWeight="medium" color="text.primary">
                {confidence.badge}
              </Text>
              <Badge colorScheme={config.colorScheme} fontSize="2xs">
                {confidence.epistemic_state}
              </Badge>
            </HStack>
            <Text fontSize="xs" color="text.muted">
              {confidence.micro_text}
            </Text>
          </VStack>
        </HStack>

        {/* CTA optionnel */}
        {confidence.cta && (
          <Tooltip label={confidence.cta.action} placement="top" fontSize="xs">
            <Text
              fontSize="xs"
              color="brand.400"
              cursor="pointer"
              _hover={{ textDecoration: 'underline' }}
            >
              {confidence.cta.label}
            </Text>
          </Tooltip>
        )}
      </HStack>

      {/* Warnings */}
      {confidence.warnings.length > 0 && (
        <VStack align="start" mt={2} spacing={0.5}>
          {confidence.warnings.map((warning, idx) => (
            <Text key={idx} fontSize="2xs" color="yellow.400">
              {warning}
            </Text>
          ))}
        </VStack>
      )}

      {/* Blockers */}
      {confidence.blockers.length > 0 && (
        <VStack align="start" mt={2} spacing={0.5}>
          {confidence.blockers.map((blocker, idx) => (
            <Text key={idx} fontSize="2xs" color="red.400">
              {blocker}
            </Text>
          ))}
        </VStack>
      )}
    </Box>
  )
}
