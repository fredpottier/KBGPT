'use client'

import {
  Box,
  HStack,
  Image,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalBody,
  ModalCloseButton,
  Text,
  VStack,
  useDisclosure,
  IconButton,
} from '@chakra-ui/react'
import { ChevronLeftIcon, ChevronRightIcon } from '@chakra-ui/icons'
import { useState, useRef } from 'react'
import { SearchChunk } from '@/types/api'

interface ThumbnailCarouselProps {
  chunks: SearchChunk[]
  synthesizedAnswer?: string // Ajout pour filtrer selon les slides mentionnés
}

export default function ThumbnailCarousel({ chunks, synthesizedAnswer }: ThumbnailCarouselProps) {
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [selectedImage, setSelectedImage] = useState<SearchChunk | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Fonction pour extraire les numéros de slides mentionnés dans la réponse synthétisée
  const extractMentionedSlides = (answer: string): Set<string> => {
    const mentionedSlides = new Set<string>()

    // Patterns pour capturer les références aux slides
    const patterns = [
      /slide\s+(\d+)/gi,                    // "slide 36"
      /slides\s+(\d+)-(\d+)/gi,             // "slides 71-73"
      /slides\s+(\d+),\s*(\d+)/gi,          // "slides 71, 72"
      /slides\s+(\d+)\s+et\s+(\d+)/gi,      // "slides 71 et 72"
      /slides\s+(\d+)\s+à\s+(\d+)/gi,       // "slides 71 à 73"
    ]

    patterns.forEach(pattern => {
      let match
      while ((match = pattern.exec(answer)) !== null) {
        if (pattern.source.includes('-')) {
          // Range de slides (ex: "slides 71-73")
          const start = parseInt(match[1])
          const end = parseInt(match[2])
          for (let i = start; i <= end; i++) {
            mentionedSlides.add(i.toString())
          }
        } else if (match[2]) {
          // Deux slides séparés (ex: "slides 71, 72")
          mentionedSlides.add(match[1])
          mentionedSlides.add(match[2])
        } else {
          // Un seul slide (ex: "slide 36")
          mentionedSlides.add(match[1])
        }
      }
    })

    return mentionedSlides
  }

  // Filter chunks that have thumbnail images
  const allChunksWithImages = chunks.filter(chunk => chunk.slide_image_url)
  let chunksWithImages = allChunksWithImages

  // Si on a une réponse synthétisée, filtrer selon les slides mentionnés
  if (synthesizedAnswer) {
    const mentionedSlides = extractMentionedSlides(synthesizedAnswer)
    if (mentionedSlides.size > 0) {
      const filtered = allChunksWithImages.filter(chunk =>
        chunk.slide_index && mentionedSlides.has(chunk.slide_index.toString())
      )
      if (filtered.length > 0) {
        chunksWithImages = filtered
      }
    }
  }

  const handleImageClick = (chunk: SearchChunk) => {
    setSelectedImage(chunk)
    onOpen()
  }

  const scroll = (direction: 'left' | 'right') => {
    if (scrollRef.current) {
      const scrollAmount = 200
      scrollRef.current.scrollBy({
        left: direction === 'left' ? -scrollAmount : scrollAmount,
        behavior: 'smooth'
      })
    }
  }

  if (chunksWithImages.length === 0) {
    return null
  }

  const getDocumentName = (sourceFile: string) => {
    return sourceFile.split('/').pop() || sourceFile
  }

  return (
    <>
      <Box position="relative" w="full">
        <Text fontSize="lg" fontWeight="semibold" mb={4} color="gray.700">
          📸 Aperçus des documents
        </Text>

        <Box position="relative">
          {/* Left scroll button */}
          {chunksWithImages.length > 3 && (
            <IconButton
              aria-label="Scroll left"
              icon={<ChevronLeftIcon />}
              position="absolute"
              left={-2}
              top="50%"
              transform="translateY(-50%)"
              zIndex={2}
              bg="white"
              shadow="md"
              borderRadius="full"
              size="sm"
              onClick={() => scroll('left')}
            />
          )}

          {/* Carousel container */}
          <Box
            ref={scrollRef}
            display="flex"
            gap={4}
            overflowX="auto"
            py={2}
            px={6}
            css={{
              scrollbarWidth: 'none',
              '&::-webkit-scrollbar': {
                display: 'none'
              }
            }}
          >
            {chunksWithImages.map((chunk, index) => (
              <Box
                key={index}
                flexShrink={0}
                cursor="pointer"
                onClick={() => handleImageClick(chunk)}
                _hover={{
                  transform: 'scale(1.05)',
                  shadow: 'lg'
                }}
                transition="all 0.2s"
              >
                <VStack spacing={2} align="center">
                  <Box
                    position="relative"
                    borderRadius="md"
                    overflow="hidden"
                    border="2px solid"
                    borderColor="gray.200"
                    w="150px"
                    h="100px"
                  >
                    <Image
                      src={chunk.slide_image_url}
                      alt={`Slide ${chunk.slide_index}`}
                      w="full"
                      h="full"
                      objectFit="cover"
                      fallback={
                        <Box
                          w="full"
                          h="full"
                          bg="gray.100"
                          display="flex"
                          alignItems="center"
                          justifyContent="center"
                        >
                          <Text fontSize="xs" color="gray.500">
                            Image non disponible
                          </Text>
                        </Box>
                      }
                    />
                  </Box>
                  <VStack spacing={1} align="center">
                    <Text fontSize="xs" fontWeight="medium" color="gray.600">
                      Slide {chunk.slide_index}
                    </Text>
                    <Text
                      fontSize="xs"
                      color="gray.500"
                      textAlign="center"
                      maxW="150px"
                      noOfLines={2}
                    >
                      {getDocumentName(chunk.source_file)}
                    </Text>
                  </VStack>
                </VStack>
              </Box>
            ))}
          </Box>

          {/* Right scroll button */}
          {chunksWithImages.length > 3 && (
            <IconButton
              aria-label="Scroll right"
              icon={<ChevronRightIcon />}
              position="absolute"
              right={-2}
              top="50%"
              transform="translateY(-50%)"
              zIndex={2}
              bg="white"
              shadow="md"
              borderRadius="full"
              size="sm"
              onClick={() => scroll('right')}
            />
          )}
        </Box>
      </Box>

      {/* Modal for enlarged image */}
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
    </>
  )
}