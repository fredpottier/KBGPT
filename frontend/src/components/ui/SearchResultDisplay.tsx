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
} from '@chakra-ui/react'
import {
  SearchResponse,
  SearchChunk,
  ExplorationIntelligence,
  ConfidenceResult,
  KnowledgeProofSummary,
  ReasoningTrace,
  CoverageMap,
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
import {
  FiAlertTriangle,
  FiFileText,
  FiCheckCircle,
  FiAlertCircle,
  FiXCircle,
  FiHelpCircle,
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
