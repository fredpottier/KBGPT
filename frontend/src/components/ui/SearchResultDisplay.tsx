'use client'

import {
  VStack,
  Box,
  Text,
  Divider,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalBody,
  ModalCloseButton,
  Image,
  useDisclosure,
} from '@chakra-ui/react'
import { SearchResponse, SearchChunk } from '@/types/api'
import { useState } from 'react'
import ThumbnailCarousel from './ThumbnailCarousel'
import SynthesizedAnswer from './SynthesizedAnswer'
import SourcesSection from './SourcesSection'

interface SearchResultDisplayProps {
  searchResult: SearchResponse
}

export default function SearchResultDisplay({ searchResult }: SearchResultDisplayProps) {
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
        p={6}
        bg="yellow.50"
        borderRadius="lg"
        border="1px solid"
        borderColor="yellow.200"
        textAlign="center"
      >
        <Text fontSize="lg" fontWeight="medium" color="yellow.800" mb={2}>
          🔍 Aucun résultat trouvé
        </Text>
        <Text fontSize="sm" color="yellow.700">
          {searchResult.message || "Aucune information pertinente n'a été trouvée dans la base de connaissances."}
        </Text>
      </Box>
    )
  }

  return (
    <VStack spacing={8} align="stretch" w="full">
      {/* Thumbnail Carousel */}
      {searchResult.results && searchResult.results.length > 0 && (
        <>
          <ThumbnailCarousel
            chunks={searchResult.results}
            synthesizedAnswer={searchResult.synthesis?.synthesized_answer}
          />
          <Divider />
        </>
      )}

      {/* Synthesized Answer */}
      {searchResult.synthesis && (
        <>
          <SynthesizedAnswer
            synthesis={searchResult.synthesis}
            chunks={searchResult.results}
            onSlideClick={handleSlideClick}
          />
          <Divider />
        </>
      )}

      {/* Sources Section */}
      {searchResult.synthesis && (
        <SourcesSection synthesis={searchResult.synthesis} />
      )}

      {/* Fallback: show raw results if no synthesis */}
      {!searchResult.synthesis && searchResult.results && searchResult.results.length > 0 && (
        <Box>
          <Text fontSize="lg" fontWeight="semibold" mb={4} color="gray.700">
            📄 Résultats de recherche
          </Text>
          <VStack spacing={3} align="stretch">
            {searchResult.results.slice(0, 5).map((result, index) => (
              <Box
                key={index}
                p={4}
                bg="gray.50"
                borderRadius="md"
                border="1px solid"
                borderColor="gray.200"
              >
                <Text fontSize="sm" mb={2} color="gray.800">
                  {result.text.length > 200
                    ? result.text.substring(0, 200) + '...'
                    : result.text
                  }
                </Text>
                <Text fontSize="xs" color="gray.500">
                  {result.source_file.split('/').pop()}
                  {result.slide_index && `, slide ${result.slide_index}`}
                  {result.rerank_score && ` • Score: ${result.rerank_score.toFixed(3)}`}
                </Text>
              </Box>
            ))}
          </VStack>
        </Box>
      )}

      {/* Modal for enlarged image when slide number is clicked */}
      <Modal isOpen={isOpen} onClose={onClose} size="6xl">
        <ModalOverlay />
        <ModalContent maxW="80vw" maxH="80vh">
          <ModalCloseButton />
          <ModalBody p={4}>
            {selectedImage && (
              <VStack spacing={4} align="center">
                <Image
                  src={selectedImage.slide_image_url}
                  alt={`Slide ${selectedImage.slide_index}`}
                  maxW="100%"
                  maxH="70vh"
                  objectFit="contain"
                  borderRadius="md"
                />
                <VStack spacing={1} align="center">
                  <Text fontSize="lg" fontWeight="semibold" color="gray.700">
                    Slide {selectedImage.slide_index}
                  </Text>
                  <Text fontSize="sm" color="gray.600" textAlign="center">
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