'use client'

/**
 * OSMOS Thumbnail Carousel - Dark Elegance Edition
 */

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
  Icon,
} from '@chakra-ui/react'
import { ChevronLeftIcon, ChevronRightIcon } from '@chakra-ui/icons'
import { useState, useRef } from 'react'
import { SearchChunk } from '@/types/api'
import { FiImage } from 'react-icons/fi'

interface ThumbnailCarouselProps {
  chunks: SearchChunk[]
  synthesizedAnswer?: string
}

export default function ThumbnailCarousel({ chunks, synthesizedAnswer }: ThumbnailCarouselProps) {
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [selectedImage, setSelectedImage] = useState<SearchChunk | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const extractMentionedSlides = (answer: string): Set<string> => {
    const mentionedSlides = new Set<string>()

    const patterns = [
      /slide\s+(\d+)/gi,
      /slides\s+(\d+)-(\d+)/gi,
      /slides\s+(\d+),\s*(\d+)/gi,
      /slides\s+(\d+)\s+et\s+(\d+)/gi,
      /slides\s+(\d+)\s+à\s+(\d+)/gi,
    ]

    patterns.forEach(pattern => {
      let match
      while ((match = pattern.exec(answer)) !== null) {
        if (pattern.source.includes('-')) {
          const start = parseInt(match[1])
          const end = parseInt(match[2])
          for (let i = start; i <= end; i++) {
            mentionedSlides.add(i.toString())
          }
        } else if (match[2]) {
          mentionedSlides.add(match[1])
          mentionedSlides.add(match[2])
        } else {
          mentionedSlides.add(match[1])
        }
      }
    })

    return mentionedSlides
  }

  const allChunksWithImages = chunks.filter(chunk => chunk.slide_image_url)
  let chunksWithImages = allChunksWithImages

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
        <HStack spacing={2} mb={2}>
          <Icon as={FiImage} boxSize={4} color="text.muted" />
          <Text fontSize="xs" fontWeight="medium" color="text.muted">
            Apercus
          </Text>
        </HStack>

        <Box position="relative">
          {/* Left scroll button */}
          {chunksWithImages.length > 4 && (
            <IconButton
              aria-label="Defiler a gauche"
              icon={<ChevronLeftIcon boxSize={4} />}
              position="absolute"
              left={-2}
              top="50%"
              transform="translateY(-50%)"
              zIndex={2}
              bg="bg.secondary"
              border="1px solid"
              borderColor="border.default"
              color="text.primary"
              borderRadius="full"
              size="sm"
              _hover={{
                bg: 'bg.hover',
                borderColor: 'border.active',
              }}
              onClick={() => scroll('left')}
            />
          )}

          {/* Carousel container */}
          <Box
            ref={scrollRef}
            display="flex"
            gap={3}
            overflowX="auto"
            py={2}
            px={chunksWithImages.length > 4 ? 6 : 1}
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
                  transform: 'scale(1.03)',
                }}
                transition="all 0.2s"
              >
                <VStack spacing={1} align="center">
                  <Box
                    position="relative"
                    borderRadius="lg"
                    overflow="hidden"
                    border="1px solid"
                    borderColor="border.default"
                    w="120px"
                    h="75px"
                    bg="bg.tertiary"
                    _hover={{
                      borderColor: 'brand.500',
                      boxShadow: '0 0 10px rgba(99, 102, 241, 0.3)',
                    }}
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
                          bg="bg.tertiary"
                          display="flex"
                          alignItems="center"
                          justifyContent="center"
                        >
                          <Text fontSize="xs" color="text.muted">
                            N/A
                          </Text>
                        </Box>
                      }
                    />
                  </Box>
                  <HStack
                    px={2}
                    py={0.5}
                    bg="bg.tertiary"
                    rounded="full"
                    border="1px solid"
                    borderColor="border.default"
                  >
                    <Text fontSize="2xs" color="text.muted">
                      Slide {chunk.slide_index}
                    </Text>
                  </HStack>
                </VStack>
              </Box>
            ))}
          </Box>

          {/* Right scroll button */}
          {chunksWithImages.length > 4 && (
            <IconButton
              aria-label="Defiler a droite"
              icon={<ChevronRightIcon boxSize={4} />}
              position="absolute"
              right={-2}
              top="50%"
              transform="translateY(-50%)"
              zIndex={2}
              bg="bg.secondary"
              border="1px solid"
              borderColor="border.default"
              color="text.primary"
              borderRadius="full"
              size="sm"
              _hover={{
                bg: 'bg.hover',
                borderColor: 'border.active',
              }}
              onClick={() => scroll('right')}
            />
          )}
        </Box>
      </Box>

      {/* Modal for enlarged image */}
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
    </>
  )
}
