'use client'

/**
 * OSMOS Chat - Dark Elegance Edition
 *
 * Interface de chat premium avec Knowledge Graph intégré.
 * Style inspiré de Linear/Raycast avec touches high-tech.
 */

import {
  Box,
  Flex,
  HStack,
  Text,
  VStack,
  IconButton,
  useToast,
  Tooltip,
} from '@chakra-ui/react'
import { AttachmentIcon } from '@chakra-ui/icons'
import { useState, useRef, useEffect, useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '@/lib/api'
import { SearchResponse } from '@/types/api'
import CopyButton from '@/components/ui/CopyButton'
import AutoResizeTextarea from '@/components/ui/AutoResizeTextarea'
import SearchResultDisplay from '@/components/ui/SearchResultDisplay'
import SessionSelector from '@/components/chat/SessionSelector'
import SessionSummary from '@/components/chat/SessionSummary'
import { ConceptCardPanel } from '@/components/concept'
import { parseGraphData } from '@/lib/graph'
import type { GraphData } from '@/types/graph'
import type { ExplorationIntelligence } from '@/types/api'
import { useDisclosure } from '@chakra-ui/react'
import {
  FiSend,
  FiZap,
  FiLayers,
  FiCpu,
  FiMessageCircle,
  FiThumbsUp,
  FiThumbsDown,
} from 'react-icons/fi'

// Motion components
const MotionBox = motion(Box)
const MotionFlex = motion(Flex)

interface Message {
  id: string
  content: string
  role: 'user' | 'assistant'
  timestamp: string
  searchResult?: SearchResponse
  feedback_rating?: number
  graphData?: GraphData
  explorationIntelligence?: ExplorationIntelligence
}

type GraphEnrichmentLevel = 'none' | 'light' | 'standard' | 'deep'

// Composant EmptyState avec animation
const EmptyState = ({ useGraphContext }: { useGraphContext: boolean }) => (
  <MotionFlex
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.6, ease: 'easeOut' }}
    align="center"
    justify="center"
    h="full"
    direction="column"
    px={8}
  >
    {/* Icône animée */}
    <Box
      className="animate-float"
      mb={6}
    >
      <Box
        w={20}
        h={20}
        bgGradient="linear(to-br, brand.500, accent.400)"
        rounded="2xl"
        display="flex"
        alignItems="center"
        justifyContent="center"
        boxShadow="0 0 40px rgba(99, 102, 241, 0.3), 0 0 80px rgba(34, 211, 238, 0.1)"
      >
        <Box as={FiMessageCircle} size={36} color="white" />
      </Box>
    </Box>

    {/* Titre avec gradient */}
    <Text
      fontSize="2xl"
      fontWeight="bold"
      bgGradient="linear(to-r, text.primary, brand.400)"
      bgClip="text"
      mb={3}
    >
      Bienvenue dans OSMOSIS
    </Text>

    <Text
      color="text.secondary"
      textAlign="center"
      maxW="420px"
      lineHeight="tall"
      mb={6}
    >
      Posez vos questions sur vos documents. Le Cortex Documentaire analysera
      votre base de connaissances et vous guidera avec intelligence.
    </Text>

    {/* Badge Graph-Guided RAG */}
    {useGraphContext && (
      <MotionBox
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.3, duration: 0.4 }}
      >
        <HStack
          spacing={2}
          px={4}
          py={2}
          bg="bg.tertiary"
          rounded="full"
          border="1px solid"
          borderColor="brand.500"
          boxShadow="0 0 20px rgba(99, 102, 241, 0.2)"
        >
          <Box as={FiZap} color="brand.400" />
          <Text fontSize="sm" color="brand.400" fontWeight="medium">
            Knowledge Graph activé
          </Text>
        </HStack>
      </MotionBox>
    )}

    {/* Suggestions */}
    <VStack spacing={2} mt={8} w="full" maxW="400px">
      <Text fontSize="xs" color="text.muted" textTransform="uppercase" letterSpacing="wide">
        Essayez par exemple
      </Text>
      {[
        "Quels sont les risques GDPR liés au ransomware ?",
        "Comment fonctionne l'architecture SAP S/4HANA ?",
        "Résume les bonnes pratiques de sécurité",
      ].map((suggestion, i) => (
        <MotionBox
          key={i}
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.4 + i * 0.1, duration: 0.4 }}
          w="full"
        >
          <Box
            px={4}
            py={3}
            bg="bg.secondary"
            rounded="xl"
            border="1px solid"
            borderColor="border.default"
            cursor="pointer"
            transition="all 0.2s"
            _hover={{
              borderColor: 'brand.500',
              bg: 'bg.tertiary',
              transform: 'translateX(4px)',
            }}
          >
            <Text fontSize="sm" color="text.secondary">
              {suggestion}
            </Text>
          </Box>
        </MotionBox>
      ))}
    </VStack>
  </MotionFlex>
)

// Composant MessageBubble
const MessageBubble = ({
  message,
  onFeedback,
  feedbackLoading,
  currentSessionId,
  onSearch,
}: {
  message: Message
  onFeedback: (id: string, rating: 1 | 2) => void
  feedbackLoading: boolean
  currentSessionId: string | null
  onSearch: (query: string) => void
}) => {
  const isUser = message.role === 'user'

  return (
    <MotionBox
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      w="full"
    >
      <Flex justify={isUser ? 'flex-end' : 'flex-start'} w="full">
        <Box
          maxW={{ base: '90%', md: '80%' }}
          w={isUser ? 'auto' : 'full'}
        >
          {/* Avatar et header */}
          <HStack
            spacing={2}
            mb={2}
            justify={isUser ? 'flex-end' : 'flex-start'}
          >
            <Box
              w={7}
              h={7}
              rounded="lg"
              display="flex"
              alignItems="center"
              justifyContent="center"
              bg={isUser ? 'brand.500' : 'bg.tertiary'}
              border={isUser ? 'none' : '1px solid'}
              borderColor="border.default"
              order={isUser ? 1 : 0}
            >
              {isUser ? (
                <Text fontSize="xs" fontWeight="bold" color="white">U</Text>
              ) : (
                <Box as={FiCpu} size={14} color="accent.400" />
              )}
            </Box>
            <Text fontSize="xs" color="text.muted" order={isUser ? 0 : 1}>
              {isUser ? 'Vous' : 'OSMOSIS'}
            </Text>
            <Text fontSize="xs" color="text.muted">
              {new Date(message.timestamp).toLocaleTimeString('fr-FR', {
                hour: '2-digit',
                minute: '2-digit'
              })}
            </Text>
          </HStack>

          {/* Message content */}
          <Box
            bg={isUser ? 'brand.500' : 'bg.secondary'}
            px={4}
            py={3}
            rounded="2xl"
            roundedTopRight={isUser ? 'md' : '2xl'}
            roundedTopLeft={isUser ? '2xl' : 'md'}
            border={isUser ? 'none' : '1px solid'}
            borderColor="border.default"
            position="relative"
            transition="all 0.2s"
            _hover={{
              borderColor: isUser ? 'transparent' : 'border.active',
            }}
            css={{
              '&:hover .message-actions': { opacity: 1 },
            }}
          >
            {message.role === 'assistant' && message.searchResult ? (
              <SearchResultDisplay
                searchResult={message.searchResult}
                graphData={message.graphData}
                explorationIntelligence={message.explorationIntelligence}
                onSearch={onSearch}
                instrumentedAnswer={message.searchResult.instrumented_answer}
              />
            ) : (
              <Text
                fontSize="sm"
                color={isUser ? 'white' : 'text.primary'}
                whiteSpace="pre-line"
                wordBreak="break-word"
                lineHeight="tall"
                userSelect="text"
                cursor="text"
              >
                {message.content.trim()}
              </Text>
            )}

            {/* Actions pour messages utilisateur */}
            {isUser && (
              <HStack
                className="message-actions"
                opacity={0}
                transition="opacity 0.2s"
                spacing={1}
                mt={2}
                pt={2}
                borderTop="1px solid"
                borderColor="whiteAlpha.300"
              >
                <CopyButton
                  text={message.content}
                  size="xs"
                  variant="ghost"
                  color="whiteAlpha.700"
                  _hover={{ bg: 'whiteAlpha.200', color: 'white' }}
                />
              </HStack>
            )}

            {/* Actions pour messages assistant */}
            {!isUser && (
              <HStack
                className="message-actions"
                opacity={0}
                transition="opacity 0.2s"
                spacing={1}
                mt={3}
                pt={3}
                borderTop="1px solid"
                borderColor="border.default"
              >
                <CopyButton
                  text={message.content}
                  size="xs"
                />
                {currentSessionId && (
                  <>
                    <Tooltip label="Utile" hasArrow>
                      <IconButton
                        aria-label="Thumbs up"
                        icon={<FiThumbsUp size={14} />}
                        size="xs"
                        variant="ghost"
                        color={message.feedback_rating === 2 ? 'success.500' : 'text.muted'}
                        bg={message.feedback_rating === 2 ? 'success.500' : 'transparent'}
                        _hover={{ bg: 'bg.hover', color: 'success.500' }}
                        onClick={() => onFeedback(message.id, 2)}
                        isDisabled={feedbackLoading}
                        rounded="lg"
                      />
                    </Tooltip>
                    <Tooltip label="Pas utile" hasArrow>
                      <IconButton
                        aria-label="Thumbs down"
                        icon={<FiThumbsDown size={14} />}
                        size="xs"
                        variant="ghost"
                        color={message.feedback_rating === 1 ? 'error.500' : 'text.muted'}
                        bg={message.feedback_rating === 1 ? 'error.500' : 'transparent'}
                        _hover={{ bg: 'bg.hover', color: 'error.500' }}
                        onClick={() => onFeedback(message.id, 1)}
                        isDisabled={feedbackLoading}
                        rounded="lg"
                      />
                    </Tooltip>
                  </>
                )}
              </HStack>
            )}
          </Box>
        </Box>
      </Flex>
    </MotionBox>
  )
}

// Composant LoadingIndicator
const LoadingIndicator = () => (
  <MotionBox
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -10 }}
  >
    <Flex justify="flex-start" w="full">
      <Box maxW="80%">
        <HStack spacing={2} mb={2}>
          <Box
            w={7}
            h={7}
            rounded="lg"
            display="flex"
            alignItems="center"
            justifyContent="center"
            bg="bg.tertiary"
            border="1px solid"
            borderColor="border.default"
            className="animate-pulse-glow"
          >
            <Box as={FiCpu} size={14} color="accent.400" />
          </Box>
          <Text fontSize="xs" color="text.muted">OSMOSIS</Text>
        </HStack>

        <Box
          bg="bg.secondary"
          px={4}
          py={4}
          rounded="2xl"
          roundedTopLeft="md"
          border="1px solid"
          borderColor="brand.500"
          boxShadow="0 0 20px rgba(99, 102, 241, 0.15)"
        >
          <HStack spacing={3}>
            {/* Animated dots */}
            <HStack spacing={1}>
              {[0, 1, 2].map((i) => (
                <Box
                  key={i}
                  w={2}
                  h={2}
                  rounded="full"
                  bg="brand.500"
                  className="animate-bounce-dot"
                  sx={{ animationDelay: `${i * 0.15}s` }}
                />
              ))}
            </HStack>
            <Text fontSize="sm" color="text.secondary">
              Analyse du Cortex en cours...
            </Text>
          </HStack>
        </Box>
      </Box>
    </Flex>
  </MotionBox>
)

// Composant GraphToggle élégant
const GraphToggle = ({
  enabled,
  onChange,
  level,
  onLevelChange,
}: {
  enabled: boolean
  onChange: (val: boolean) => void
  level: GraphEnrichmentLevel
  onLevelChange: (val: GraphEnrichmentLevel) => void
}) => (
  <HStack spacing={3}>
    {/* Toggle principal */}
    <Tooltip label="Enrichir avec le Knowledge Graph" hasArrow>
      <Box
        as="button"
        onClick={() => onChange(!enabled)}
        display="flex"
        alignItems="center"
        gap={2}
        px={3}
        py={1.5}
        rounded="full"
        bg={enabled ? 'brand.500' : 'bg.tertiary'}
        border="1px solid"
        borderColor={enabled ? 'brand.400' : 'border.default'}
        transition="all 0.2s"
        _hover={{
          borderColor: 'brand.500',
          transform: 'translateY(-1px)',
        }}
        cursor="pointer"
      >
        <Box as={FiZap} size={14} color={enabled ? 'white' : 'text.muted'} />
        <Text fontSize="xs" fontWeight="medium" color={enabled ? 'white' : 'text.secondary'}>
          Knowledge Graph
        </Text>
      </Box>
    </Tooltip>

    {/* Niveau de profondeur */}
    <AnimatePresence>
      {enabled && (
        <MotionBox
          initial={{ opacity: 0, width: 0 }}
          animate={{ opacity: 1, width: 'auto' }}
          exit={{ opacity: 0, width: 0 }}
          overflow="hidden"
        >
          <HStack spacing={1} bg="bg.tertiary" rounded="full" p={1}>
            {(['light', 'standard', 'deep'] as const).map((lvl) => (
              <Tooltip
                key={lvl}
                label={
                  lvl === 'light' ? 'Concepts liés (~30ms)' :
                  lvl === 'standard' ? 'Relations transitives (~50ms)' :
                  'Analyse profonde (~200ms)'
                }
                hasArrow
              >
                <Box
                  as="button"
                  onClick={() => onLevelChange(lvl)}
                  px={3}
                  py={1}
                  rounded="full"
                  bg={level === lvl ? 'brand.500' : 'transparent'}
                  transition="all 0.2s"
                  cursor="pointer"
                  _hover={{ bg: level === lvl ? 'brand.500' : 'bg.hover' }}
                >
                  <HStack spacing={1}>
                    <Box
                      as={lvl === 'light' ? FiZap : lvl === 'standard' ? FiLayers : FiCpu}
                      size={12}
                      color={level === lvl ? 'white' : 'text.muted'}
                    />
                    <Text
                      fontSize="xs"
                      fontWeight="medium"
                      color={level === lvl ? 'white' : 'text.muted'}
                      textTransform="capitalize"
                    >
                      {lvl}
                    </Text>
                  </HStack>
                </Box>
              </Tooltip>
            ))}
          </HStack>
        </MotionBox>
      )}
    </AnimatePresence>
  </HStack>
)

export default function ChatPage() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [useGraphContext, setUseGraphContext] = useState<boolean>(true)
  const [graphEnrichmentLevel, setGraphEnrichmentLevel] = useState<GraphEnrichmentLevel>('standard')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const toast = useToast()
  const queryClient = useQueryClient()

  const {
    isOpen: isConceptPanelOpen,
    onOpen: openConceptPanel,
    onClose: closeConceptPanel,
  } = useDisclosure()
  const [selectedConceptId, setSelectedConceptId] = useState<string | null>(null)

  // Ref pour tracker si une mutation est en cours (evite probleme de timing avec useEffect)
  const isSendingRef = useRef(false)

  const { data: messagesResponse } = useQuery({
    queryKey: ['session-messages', currentSessionId],
    queryFn: () => currentSessionId ? api.sessions.getMessages(currentSessionId) : null,
    enabled: !!currentSessionId,
  })

  useEffect(() => {
    if (messagesResponse?.success && messagesResponse.data) {
      const sessionMessages = (messagesResponse.data as { messages: any[] }).messages || []
      // Ne pas ecraser les messages locaux si on est en train d'envoyer un nouveau message
      // Cela evite le flash de l'EmptyState lors de la creation d'une nouvelle session
      if (sessionMessages.length > 0 || !isSendingRef.current) {
        setMessages(sessionMessages.map((msg: any) => ({
          id: msg.id,
          content: msg.content,
          role: msg.role as 'user' | 'assistant',
          timestamp: msg.created_at,
          feedback_rating: msg.feedback_rating,
        })))
      }
    }
  }, [messagesResponse])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const formatSearchResults = (results: any[]): string => {
    if (!results || results.length === 0) {
      return 'Aucune information pertinente trouvée dans la base de connaissance.'
    }

    let markdown = ''
    const thumbnails = results
      .filter(r => r.slide_image_url)
      .slice(0, 4)
      .map(r => `[![Slide ${r.slide_index}](${r.slide_image_url})](${r.slide_image_url})`)

    if (thumbnails.length > 0) {
      markdown += '## Aperçus\n\n' + thumbnails.join(' ') + '\n\n---\n\n'
    }

    results.forEach((result) => {
      const sourceInfo = result.source_file
        ? `*(${result.source_file.split('/').pop()}, slide ${result.slide_index})*`
        : '*(Source inconnue)*'
      const truncatedText = result.text.length > 150
        ? result.text.substring(0, 150) + '...'
        : result.text
      markdown += `- ${truncatedText}\n  ${sourceInfo}\n\n`
    })

    const sourceSet = new Set(results.filter(r => r.source_file).map(r => r.source_file))
    const sources = Array.from(sourceSet)

    if (sources.length > 0) {
      markdown += '**Sources**\n\n'
      sources.forEach(source => {
        const filename = source.split('/').pop()
        const extension = filename?.split('.').pop()?.toUpperCase() || 'FILE'
        markdown += `- [${filename}](${source}) - ${extension}\n`
      })
    }

    return markdown
  }

  const sendMessageMutation = useMutation({
    mutationFn: async (message: string) => {
      isSendingRef.current = true
      let sessionId = currentSessionId
      if (!sessionId) {
        const sessionResponse = await api.sessions.create()
        if (sessionResponse.success && sessionResponse.data) {
          sessionId = (sessionResponse.data as { id: string }).id
          setCurrentSessionId(sessionId)
          queryClient.invalidateQueries({ queryKey: ['sessions'] })
        } else {
          throw new Error('Failed to create session')
        }
      }

      await api.sessions.addMessage(sessionId, { role: 'user', content: message })
      const response = await api.chat.send(
        message,
        undefined,
        undefined,
        undefined,  // solution - legacy, plus utilisé
        useGraphContext,
        useGraphContext ? graphEnrichmentLevel : undefined,
        sessionId
      )

      return { response, sessionId }
    },
    onSuccess: async ({ response, sessionId }) => {
      isSendingRef.current = false
      if (response.success) {
        const searchResult = response.data as SearchResponse

        let content = 'No response'
        if (searchResult?.synthesis?.synthesized_answer) {
          content = searchResult.synthesis.synthesized_answer
        } else if (searchResult?.results && Array.isArray(searchResult.results)) {
          content = formatSearchResults(searchResult.results)
        } else if ((response.data as any)?.answer_markdown) {
          content = (response.data as any).answer_markdown
        }

        let graphData: GraphData | undefined
        if ((searchResult as any)?.graph_data) {
          graphData = parseGraphData((searchResult as any).graph_data) || undefined
        }

        const explorationIntelligence: ExplorationIntelligence | undefined =
          (searchResult as any)?.exploration_intelligence

        const assistantMessageResponse = await api.sessions.addMessage(sessionId, {
          role: 'assistant',
          content: content,
          documents_referenced: searchResult?.results?.map((r: any) => r.source_file).filter(Boolean),
        })

        const newMessage: Message = {
          id: assistantMessageResponse.success && assistantMessageResponse.data
            ? (assistantMessageResponse.data as { id: string }).id
            : Date.now().toString(),
          content,
          role: 'assistant',
          timestamp: new Date().toISOString(),
          searchResult: searchResult,
          graphData: graphData,
          explorationIntelligence: explorationIntelligence,
        }
        setMessages(prev => [...prev, newMessage])

        if (messages.length <= 1) {
          api.sessions.generateTitle(sessionId)
            .then(() => queryClient.invalidateQueries({ queryKey: ['sessions'] }))
        }
      } else {
        toast({
          title: 'Erreur',
          description: response.error || 'Échec de l\'envoi du message',
          status: 'error',
          duration: 3000,
          isClosable: true,
        })
      }
    },
    onError: () => {
      isSendingRef.current = false
      toast({
        title: 'Erreur',
        description: 'Échec de l\'envoi du message',
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
    },
  })

  const feedbackMutation = useMutation({
    mutationFn: ({ messageId, rating }: { messageId: string, rating: 1 | 2 }) =>
      currentSessionId
        ? api.sessions.addFeedback(currentSessionId, messageId, rating)
        : Promise.reject('No session'),
    onSuccess: (_, { messageId, rating }) => {
      setMessages(prev => prev.map(msg =>
        msg.id === messageId ? { ...msg, feedback_rating: rating } : msg
      ))
      toast({
        title: rating === 2 ? 'Merci !' : 'Feedback enregistré',
        status: 'success',
        duration: 1500,
      })
    },
  })

  const handleSend = () => {
    if (!input.trim()) return

    const userMessage: Message = {
      id: Date.now().toString(),
      content: input,
      role: 'user',
      timestamp: new Date().toISOString(),
    }

    setMessages(prev => [...prev, userMessage])
    sendMessageMutation.mutate(input)
    setInput('')
  }

  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSessionChange = (sessionId: string | null) => {
    setCurrentSessionId(sessionId)
    if (!sessionId) {
      setMessages([])
    }
  }

  const handleNewSession = () => {
    setCurrentSessionId(null)
    setMessages([])
  }

  const handleFeedback = (messageId: string, rating: 1 | 2) => {
    feedbackMutation.mutate({ messageId, rating })
  }

  const handleConceptClickFromPanel = useCallback((conceptId: string) => {
    setSelectedConceptId(conceptId)
  }, [])

  const handleQuestionClick = useCallback((question: string) => {
    setInput(question)
    closeConceptPanel()
  }, [closeConceptPanel])

  const handleExplorationSearch = useCallback((query: string) => {
    setInput(query)
    setTimeout(() => {
      const userMessage: Message = {
        id: Date.now().toString(),
        content: query,
        role: 'user',
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => [...prev, userMessage])
      sendMessageMutation.mutate(query)
      setInput('')
    }, 100)
  }, [sendMessageMutation])

  return (
    <Flex h="calc(100vh - 64px - 48px)" w="full" overflow="hidden">
      <Flex direction="column" flex="1" minW={0} overflow="hidden">
        {/* Header avec Session Selector */}
        <Box
          flexShrink={0}
          bg="bg.secondary"
          py={3}
          px={4}
          borderBottom="1px"
          borderColor="border.default"
        >
          <HStack justify="space-between">
            <SessionSelector
              currentSessionId={currentSessionId}
              onSessionChange={handleSessionChange}
              onNewSession={handleNewSession}
            />
            <HStack spacing={3}>
              {currentSessionId && (
                <>
                  <Text fontSize="xs" color="text.muted">
                    {messages.length} message{messages.length !== 1 ? 's' : ''}
                  </Text>
                  {messages.length >= 2 && (
                    <SessionSummary sessionId={currentSessionId} />
                  )}
                </>
              )}
            </HStack>
          </HStack>
        </Box>

        {/* Zone des messages */}
        <Box
          flex="1"
          overflow="auto"
          px={4}
          py={6}
          css={{
            '&::-webkit-scrollbar': { width: '6px' },
            '&::-webkit-scrollbar-track': { background: 'transparent' },
            '&::-webkit-scrollbar-thumb': {
              background: 'rgba(99, 102, 241, 0.3)',
              borderRadius: '3px',
            },
            '&::-webkit-scrollbar-thumb:hover': {
              background: 'rgba(99, 102, 241, 0.5)',
            },
          }}
        >
          {messages.length === 0 ? (
            <EmptyState useGraphContext={useGraphContext} />
          ) : (
            <VStack spacing={4} align="stretch" maxW="1200px" mx="auto">
              <AnimatePresence mode="popLayout">
                {messages.map((message) => (
                  <MessageBubble
                    key={message.id}
                    message={message}
                    onFeedback={handleFeedback}
                    feedbackLoading={feedbackMutation.isPending}
                    currentSessionId={currentSessionId}
                    onSearch={handleExplorationSearch}
                  />
                ))}
              </AnimatePresence>

              <AnimatePresence>
                {sendMessageMutation.isPending && <LoadingIndicator />}
              </AnimatePresence>

              <div ref={messagesEndRef} />
            </VStack>
          )}
        </Box>

        {/* Zone de saisie */}
        <Box
          flexShrink={0}
          bg="bg.secondary"
          borderTop="1px"
          borderColor="border.default"
          p={4}
        >
          <VStack spacing={3} maxW="1200px" mx="auto">
            {/* Contrôles Knowledge Graph */}
            <Box w="full">
              <GraphToggle
                enabled={useGraphContext}
                onChange={setUseGraphContext}
                level={graphEnrichmentLevel}
                onLevelChange={setGraphEnrichmentLevel}
              />
            </Box>

            {/* Input principal */}
            <HStack
              spacing={3}
              w="full"
              bg="bg.tertiary"
              rounded="2xl"
              border="1px solid"
              borderColor="border.default"
              px={4}
              py={2}
              transition="all 0.2s"
              _focusWithin={{
                borderColor: 'brand.500',
                boxShadow: '0 0 20px rgba(99, 102, 241, 0.15)',
              }}
            >
              <Tooltip label="Joindre un fichier" hasArrow>
                <IconButton
                  aria-label="Attach file"
                  icon={<AttachmentIcon />}
                  variant="ghost"
                  size="sm"
                  color="text.muted"
                  _hover={{ color: 'brand.400', bg: 'bg.hover' }}
                  rounded="lg"
                />
              </Tooltip>

              <AutoResizeTextarea
                ref={inputRef}
                value={input}
                onChange={setInput}
                onKeyDown={handleKeyPress}
                placeholder="Posez votre question au Cortex..."
                flex="1"
                minW={0}
                minHeight={40}
                maxHeight={200}
                border="none"
                bg="transparent"
                _focus={{ boxShadow: 'none' }}
                _placeholder={{ color: 'text.muted' }}
              />

              <Tooltip label={input.trim() ? 'Envoyer (Entrée)' : 'Tapez un message'} hasArrow>
                <IconButton
                  aria-label="Send message"
                  icon={<FiSend size={18} />}
                  bg={input.trim() ? 'brand.500' : 'bg.hover'}
                  color={input.trim() ? 'white' : 'text.muted'}
                  isDisabled={!input.trim() || sendMessageMutation.isPending}
                  isLoading={sendMessageMutation.isPending}
                  onClick={handleSend}
                  rounded="xl"
                  size="md"
                  transition="all 0.2s"
                  _hover={{
                    bg: input.trim() ? 'brand.600' : 'bg.hover',
                    transform: input.trim() ? 'scale(1.05)' : 'none',
                  }}
                  _active={{
                    transform: 'scale(0.95)',
                  }}
                />
              </Tooltip>
            </HStack>

            {/* Hint */}
            <Text fontSize="xs" color="text.muted" textAlign="center">
              Appuyez sur <kbd style={{
                background: 'rgba(99, 102, 241, 0.2)',
                padding: '2px 6px',
                borderRadius: '4px',
                fontFamily: 'monospace'
              }}>Entrée</kbd> pour envoyer, <kbd style={{
                background: 'rgba(99, 102, 241, 0.2)',
                padding: '2px 6px',
                borderRadius: '4px',
                fontFamily: 'monospace'
              }}>Shift+Entrée</kbd> pour un saut de ligne
            </Text>
          </VStack>
        </Box>
      </Flex>

      {/* Concept Card Panel */}
      <ConceptCardPanel
        conceptId={selectedConceptId}
        isOpen={isConceptPanelOpen}
        onClose={closeConceptPanel}
        onConceptClick={handleConceptClickFromPanel}
        onQuestionClick={handleQuestionClick}
      />
    </Flex>
  )
}
