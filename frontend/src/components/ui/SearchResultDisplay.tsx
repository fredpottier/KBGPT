'use client'

import {
  VStack,
  Box,
  Text,
  Divider,
} from '@chakra-ui/react'
import { SearchResponse } from '@/types/api'
import ThumbnailCarousel from './ThumbnailCarousel'
import SynthesizedAnswer from './SynthesizedAnswer'
import SourcesSection from './SourcesSection'

interface SearchResultDisplayProps {
  searchResult: SearchResponse
}

export default function SearchResultDisplay({ searchResult }: SearchResultDisplayProps) {
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
          <SynthesizedAnswer synthesis={searchResult.synthesis} />
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
    </VStack>
  )
}