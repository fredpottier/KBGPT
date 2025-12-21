'use client';

/**
 * 🌊 OSMOSE Phase 3.5 - Concept Card Panel
 *
 * Panel slide-in affichant la carte d'identité complète d'un concept.
 * S'ouvre au clic sur un noeud du Knowledge Graph.
 */

import { useEffect, useState, useCallback } from 'react';
import {
  Box,
  Drawer,
  DrawerBody,
  DrawerHeader,
  DrawerOverlay,
  DrawerContent,
  DrawerCloseButton,
  VStack,
  HStack,
  Text,
  Badge,
  Heading,
  Divider,
  Progress,
  List,
  ListItem,
  ListIcon,
  Button,
  IconButton,
  Tooltip,
  Skeleton,
  SkeletonText,
  Wrap,
  WrapItem,
  Collapse,
  useDisclosure,
} from '@chakra-ui/react';
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ExternalLinkIcon,
  InfoIcon,
  LinkIcon,
  TimeIcon,
  QuestionIcon,
  CheckCircleIcon,
} from '@chakra-ui/icons';
import { motion, AnimatePresence } from 'framer-motion';
import type {
  ConceptCard,
  ConceptRelation,
  SourceReference,
  TimelineEvent,
  ConceptCardPanelProps,
} from '@/types/concept';
import {
  CONCEPT_TYPE_LABELS,
  CONCEPT_TYPE_COLORS,
  RELATION_TYPE_LABELS,
} from '@/types/concept';
import { api } from '@/lib/api';

const MotionBox = motion(Box);

/**
 * Section Définition
 */
function DefinitionSection({ definition }: { definition: ConceptCard['definition'] }) {
  return (
    <Box>
      <HStack mb={2}>
        <InfoIcon color="blue.500" />
        <Heading size="sm">Définition</Heading>
      </HStack>
      <Box bg="gray.50" p={3} borderRadius="md" borderLeft="3px solid" borderColor="blue.400">
        <Text fontSize="sm">{definition.text}</Text>
        <HStack mt={2} fontSize="xs" color="gray.500">
          <Text>{definition.sourceCount} source{definition.sourceCount > 1 ? 's' : ''}</Text>
          <Text>•</Text>
          <Text>Consensus: {Math.round(definition.consensusScore * 100)}%</Text>
        </HStack>
      </Box>
    </Box>
  );
}

/**
 * Section Relations
 */
function RelationsSection({
  relations,
  onConceptClick,
}: {
  relations: ConceptRelation[];
  onConceptClick: (conceptId: string) => void;
}) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: true });
  const maxVisible = 5;
  const hasMore = relations.length > maxVisible;

  if (relations.length === 0) return null;

  return (
    <Box>
      <HStack mb={2} cursor="pointer" onClick={onToggle}>
        <LinkIcon color="green.500" />
        <Heading size="sm">Relations</Heading>
        <Badge colorScheme="green" variant="subtle">
          {relations.length}
        </Badge>
        <IconButton
          aria-label="Toggle relations"
          icon={isOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}
          size="xs"
          variant="ghost"
        />
      </HStack>

      <Collapse in={isOpen}>
        <VStack align="stretch" spacing={2}>
          {relations.slice(0, isOpen ? undefined : maxVisible).map((rel, idx) => (
            <Box
              key={idx}
              p={2}
              bg="gray.50"
              borderRadius="md"
              _hover={{ bg: 'gray.100', cursor: 'pointer' }}
              onClick={() => onConceptClick(rel.targetId)}
            >
              <HStack justify="space-between">
                <VStack align="start" spacing={0}>
                  <Text fontSize="sm" fontWeight="medium">
                    {rel.targetName}
                  </Text>
                  <Text fontSize="xs" color="gray.500">
                    {RELATION_TYPE_LABELS[rel.relationType] || rel.relationType}
                  </Text>
                </VStack>
                <VStack align="end" spacing={0}>
                  <Badge
                    colorScheme={rel.direction === 'outgoing' ? 'blue' : 'purple'}
                    variant="subtle"
                    fontSize="xs"
                  >
                    {rel.direction === 'outgoing' ? '→' : rel.direction === 'incoming' ? '←' : '↔'}
                  </Badge>
                  <Text fontSize="xs" color="gray.400">
                    {Math.round(rel.confidence * 100)}%
                  </Text>
                </VStack>
              </HStack>
            </Box>
          ))}
        </VStack>
      </Collapse>
    </Box>
  );
}

/**
 * Section Sources
 */
function SourcesSection({
  sources,
  onSourceClick,
  maxVisible = 3,
}: {
  sources: SourceReference[];
  onSourceClick: (sourceId: string) => void;
  maxVisible?: number;
}) {
  const [showAll, setShowAll] = useState(false);
  const hasMore = sources.length > maxVisible;

  if (sources.length === 0) return null;

  const visibleSources = showAll ? sources : sources.slice(0, maxVisible);

  return (
    <Box>
      <HStack mb={2}>
        <ExternalLinkIcon color="orange.500" />
        <Heading size="sm">Sources</Heading>
        <Badge colorScheme="orange" variant="subtle">
          {sources.length}
        </Badge>
      </HStack>

      <VStack align="stretch" spacing={2}>
        {visibleSources.map((source, idx) => (
          <Box
            key={idx}
            p={2}
            bg="gray.50"
            borderRadius="md"
            borderLeft="3px solid"
            borderColor={
              source.documentType === 'PDF' ? 'red.400' :
              source.documentType === 'PPTX' ? 'orange.400' :
              source.documentType === 'DOCX' ? 'blue.400' :
              'gray.400'
            }
            _hover={{ bg: 'gray.100', cursor: 'pointer' }}
            onClick={() => onSourceClick(source.documentId)}
          >
            <HStack justify="space-between">
              <VStack align="start" spacing={0} flex="1" minW={0}>
                <Text fontSize="sm" fontWeight="medium" noOfLines={1}>
                  {source.documentName}
                </Text>
                <Text fontSize="xs" color="gray.500" noOfLines={2}>
                  {source.excerpt}
                </Text>
              </VStack>
              <VStack align="end" spacing={0} flexShrink={0}>
                <Badge colorScheme="gray" fontSize="xs">
                  {source.documentType}
                </Badge>
                <Text fontSize="xs" color="gray.400">
                  {source.mentionCount}x
                </Text>
              </VStack>
            </HStack>
          </Box>
        ))}
      </VStack>

      {hasMore && (
        <Button
          size="xs"
          variant="ghost"
          mt={2}
          onClick={() => setShowAll(!showAll)}
          rightIcon={showAll ? <ChevronUpIcon /> : <ChevronDownIcon />}
        >
          {showAll ? 'Voir moins' : `Voir ${sources.length - maxVisible} de plus`}
        </Button>
      )}
    </Box>
  );
}

/**
 * Section Timeline
 */
function TimelineSection({ timeline }: { timeline: TimelineEvent[] }) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: false });

  if (!timeline || timeline.length === 0) return null;

  return (
    <Box>
      <HStack mb={2} cursor="pointer" onClick={onToggle}>
        <TimeIcon color="purple.500" />
        <Heading size="sm">Évolution</Heading>
        <Badge colorScheme="purple" variant="subtle">
          {timeline.length}
        </Badge>
        <IconButton
          aria-label="Toggle timeline"
          icon={isOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}
          size="xs"
          variant="ghost"
        />
      </HStack>

      <Collapse in={isOpen}>
        <VStack align="stretch" spacing={1}>
          {timeline.map((event, idx) => (
            <HStack key={idx} spacing={3} fontSize="sm">
              <Box
                w={2}
                h={2}
                borderRadius="full"
                bg={
                  event.changeType === 'added' ? 'green.400' :
                  event.changeType === 'modified' ? 'blue.400' :
                  event.changeType === 'deprecated' ? 'orange.400' :
                  event.changeType === 'removed' ? 'red.400' :
                  'gray.400'
                }
              />
              <VStack align="start" spacing={0} flex="1">
                <Text fontSize="xs" color="gray.500">{event.date}</Text>
                <Text fontSize="sm">{event.event}</Text>
              </VStack>
            </HStack>
          ))}
        </VStack>
      </Collapse>
    </Box>
  );
}

/**
 * Section Questions Suggérées
 */
function SuggestedQuestionsSection({
  questions,
  onQuestionClick,
}: {
  questions: string[];
  onQuestionClick: (question: string) => void;
}) {
  if (questions.length === 0) return null;

  return (
    <Box>
      <HStack mb={2}>
        <QuestionIcon color="teal.500" />
        <Heading size="sm">Explorer davantage</Heading>
      </HStack>

      <VStack align="stretch" spacing={2}>
        {questions.map((question, idx) => (
          <Box
            key={idx}
            p={2}
            bg="teal.50"
            borderRadius="md"
            _hover={{ bg: 'teal.100', cursor: 'pointer' }}
            onClick={() => onQuestionClick(question)}
          >
            <Text fontSize="sm" color="teal.700">
              {question}
            </Text>
          </Box>
        ))}
      </VStack>
    </Box>
  );
}

/**
 * Panel principal
 */
export default function ConceptCardPanel({
  conceptId,
  isOpen,
  onClose,
  onConceptClick,
  onQuestionClick,
}: ConceptCardPanelProps) {
  const [concept, setConcept] = useState<ConceptCard | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Charger les données du concept
  useEffect(() => {
    if (!conceptId || !isOpen) {
      return;
    }

    const fetchConcept = async () => {
      setIsLoading(true);
      setError(null);

      try {
        // Appeler l'API pour récupérer les détails du concept
        const response = await api.concepts.explain(conceptId);

        if (response.success && response.data) {
          setConcept(response.data as ConceptCard);
        } else {
          setError(response.error || 'Impossible de charger le concept');
        }
      } catch (e) {
        setError('Erreur de connexion');
        console.error('[ConceptCard] Error fetching concept:', e);
      } finally {
        setIsLoading(false);
      }
    };

    fetchConcept();
  }, [conceptId, isOpen]);

  const handleSourceClick = useCallback((sourceId: string) => {
    // TODO: Ouvrir le document source
    console.log('[ConceptCard] Open source:', sourceId);
  }, []);

  return (
    <Drawer isOpen={isOpen} placement="right" onClose={onClose} size="md">
      <DrawerOverlay />
      <DrawerContent>
        <DrawerCloseButton />

        {/* Header avec nom et type */}
        <DrawerHeader borderBottomWidth="1px">
          {isLoading ? (
            <VStack align="start" spacing={2}>
              <Skeleton height="24px" width="200px" />
              <Skeleton height="20px" width="100px" />
            </VStack>
          ) : concept ? (
            <VStack align="start" spacing={1}>
              <Heading size="md">{concept.canonicalName}</Heading>
              {concept.fullName && concept.fullName !== concept.canonicalName && (
                <Text fontSize="sm" color="gray.500">
                  {concept.fullName}
                </Text>
              )}
              <HStack>
                <Badge
                  colorScheme={CONCEPT_TYPE_COLORS[concept.type] || 'gray'}
                  textTransform="capitalize"
                >
                  {CONCEPT_TYPE_LABELS[concept.type] || concept.type}
                </Badge>
                <Badge variant="outline" colorScheme="blue">
                  {concept.mentionCount} mention{concept.mentionCount > 1 ? 's' : ''}
                </Badge>
                <Badge variant="outline" colorScheme="green">
                  {concept.documentCount} doc{concept.documentCount > 1 ? 's' : ''}
                </Badge>
              </HStack>
            </VStack>
          ) : error ? (
            <Text color="red.500">{error}</Text>
          ) : (
            <Text color="gray.500">Sélectionnez un concept</Text>
          )}
        </DrawerHeader>

        <DrawerBody>
          {isLoading ? (
            <VStack align="stretch" spacing={4} py={4}>
              <SkeletonText noOfLines={4} />
              <Skeleton height="100px" />
              <SkeletonText noOfLines={3} />
            </VStack>
          ) : concept ? (
            <VStack align="stretch" spacing={6} py={4}>
              {/* Confiance */}
              <Box>
                <HStack justify="space-between" fontSize="sm" mb={1}>
                  <Text color="gray.600">Confiance</Text>
                  <Text fontWeight="medium">{Math.round(concept.confidence * 100)}%</Text>
                </HStack>
                <Progress
                  value={concept.confidence * 100}
                  colorScheme={
                    concept.confidence >= 0.8 ? 'green' :
                    concept.confidence >= 0.5 ? 'yellow' : 'red'
                  }
                  size="sm"
                  borderRadius="full"
                />
              </Box>

              {/* Aliases */}
              {concept.aliases.length > 0 && (
                <Box>
                  <Text fontSize="sm" color="gray.600" mb={1}>
                    Aussi connu sous:
                  </Text>
                  <Wrap>
                    {concept.aliases.map((alias, idx) => (
                      <WrapItem key={idx}>
                        <Badge variant="subtle" colorScheme="gray">
                          {alias}
                        </Badge>
                      </WrapItem>
                    ))}
                  </Wrap>
                </Box>
              )}

              <Divider />

              {/* Définition */}
              <DefinitionSection definition={concept.definition} />

              <Divider />

              {/* Relations */}
              <RelationsSection
                relations={concept.relations}
                onConceptClick={onConceptClick}
              />

              <Divider />

              {/* Sources */}
              <SourcesSection
                sources={concept.sources}
                onSourceClick={handleSourceClick}
              />

              {/* Timeline */}
              {concept.timeline && concept.timeline.length > 0 && (
                <>
                  <Divider />
                  <TimelineSection timeline={concept.timeline} />
                </>
              )}

              {/* Questions suggérées */}
              {concept.suggestedQuestions.length > 0 && (
                <>
                  <Divider />
                  <SuggestedQuestionsSection
                    questions={concept.suggestedQuestions}
                    onQuestionClick={onQuestionClick}
                  />
                </>
              )}
            </VStack>
          ) : error ? (
            <VStack py={8} spacing={4}>
              <Text color="red.500">{error}</Text>
              <Button size="sm" onClick={onClose}>
                Fermer
              </Button>
            </VStack>
          ) : null}
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
