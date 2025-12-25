'use client'

/**
 * OSMOS Search Result Display - Dark Elegance Edition
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
} from '@chakra-ui/react'
import { SearchResponse, SearchChunk, ExplorationIntelligence } from '@/types/api'
import { useState } from 'react'
import ThumbnailCarousel from './ThumbnailCarousel'
import SynthesizedAnswer from './SynthesizedAnswer'
import SourcesSection from './SourcesSection'
import type { GraphData } from '@/types/graph'
import { FiAlertTriangle, FiFileText } from 'react-icons/fi'

interface SearchResultDisplayProps {
  searchResult: SearchResponse
  graphData?: GraphData
  explorationIntelligence?: ExplorationIntelligence
  onSearch?: (query: string) => void
}

export default function SearchResultDisplay({
  searchResult,
  graphData,
  explorationIntelligence,
  onSearch,
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

      {/* Synthesized Answer (with integrated Knowledge Graph) */}
      {searchResult.synthesis && (
        <SynthesizedAnswer
          synthesis={searchResult.synthesis}
          chunks={searchResult.results}
          onSlideClick={handleSlideClick}
          graphData={graphData}
          explorationIntelligence={explorationIntelligence}
          onSearch={onSearch}
        />
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
