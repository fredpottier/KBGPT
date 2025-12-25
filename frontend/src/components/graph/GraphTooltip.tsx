'use client';

/**
 * OSMOS Phase 3.5 - Graph Tooltip
 *
 * Tooltip enrichi affiché au survol d'un noeud du graphe.
 * Affiche les informations clés du concept avec style.
 */

import { Box, Text, Badge, VStack, HStack, Progress, Divider } from '@chakra-ui/react';
import { motion, AnimatePresence } from 'framer-motion';
import type { GraphNode, ConceptType } from '@/types/graph';
import { GRAPH_COLORS, CONCEPT_TYPE_LABELS, CONCEPT_TYPE_COLORS } from '@/types/concept';

interface GraphTooltipProps {
  node: GraphNode | null;
  position: { x: number; y: number } | null;
  isVisible: boolean;
}

const MotionBox = motion(Box);

export default function GraphTooltip({ node, position, isVisible }: GraphTooltipProps) {
  if (!node || !position || !isVisible) {
    return null;
  }

  const roleLabels: Record<string, string> = {
    query: 'Question',
    used: 'Utilisé',
    suggested: 'Suggéré',
    context: 'Contexte',
  };

  const roleColors: Record<string, string> = {
    query: 'orange',
    used: 'green',
    suggested: 'blue',
    context: 'gray',
  };

  return (
    <AnimatePresence>
      {isVisible && (
        <MotionBox
          position="fixed"
          left={`${position.x + 15}px`}
          top={`${position.y - 10}px`}
          zIndex={1000}
          pointerEvents="none"
          initial={{ opacity: 0, scale: 0.95, y: 5 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 5 }}
          transition={{ duration: 0.15 }}
        >
          <Box
            bg="white"
            borderRadius="lg"
            boxShadow="lg"
            p={3}
            minW="200px"
            maxW="300px"
            border="1px solid"
            borderColor="gray.200"
          >
            <VStack align="stretch" spacing={2}>
              {/* Nom et type */}
              <Box>
                <Text fontWeight="bold" fontSize="sm" noOfLines={2}>
                  {node.name}
                </Text>
                <HStack mt={1} spacing={2}>
                  <Badge
                    colorScheme={CONCEPT_TYPE_COLORS[node.type as ConceptType] || 'gray'}
                    fontSize="xs"
                    textTransform="capitalize"
                  >
                    {CONCEPT_TYPE_LABELS[node.type as ConceptType] || node.type}
                  </Badge>
                  <Badge
                    colorScheme={roleColors[node.role] || 'gray'}
                    variant="subtle"
                    fontSize="xs"
                  >
                    {roleLabels[node.role] || node.role}
                  </Badge>
                </HStack>
              </Box>

              <Divider />

              {/* Statistiques */}
              <VStack align="stretch" spacing={1}>
                {/* Confiance */}
                <Box>
                  <HStack justify="space-between" fontSize="xs" color="gray.600">
                    <Text>Confiance</Text>
                    <Text fontWeight="medium">{Math.round(node.confidence * 100)}%</Text>
                  </HStack>
                  <Progress
                    value={node.confidence * 100}
                    size="xs"
                    colorScheme={
                      node.confidence >= 0.8 ? 'green' : node.confidence >= 0.5 ? 'yellow' : 'red'
                    }
                    borderRadius="full"
                    mt={1}
                  />
                </Box>

                {/* Mentions */}
                <HStack justify="space-between" fontSize="xs" color="gray.600">
                  <Text>Mentions</Text>
                  <Text fontWeight="medium">{node.mentionCount}</Text>
                </HStack>

                {/* Documents */}
                {node.documentCount !== undefined && node.documentCount > 0 && (
                  <HStack justify="space-between" fontSize="xs" color="gray.600">
                    <Text>Documents</Text>
                    <Text fontWeight="medium">{node.documentCount}</Text>
                  </HStack>
                )}
              </VStack>

              {/* Hint interaction */}
              <Text fontSize="xs" color="gray.400" textAlign="center" mt={1}>
                Cliquez pour explorer
              </Text>
            </VStack>
          </Box>
        </MotionBox>
      )}
    </AnimatePresence>
  );
}
