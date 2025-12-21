'use client'

/**
 * 🌊 OSMOSE Phase 3.5 - Chat Page avec Knowledge Graph intégré
 *
 * Page de chat avec graphe D3.js intégré dans chaque réponse (accordéon).
 */

import {
  Box,
  Flex,
  HStack,
  Text,
  VStack,
  Card,
  CardBody,
  Avatar,
  Spinner,
  IconButton,
  useToast,
  Select,
  Switch,
  Tooltip,
  Badge,
} from '@chakra-ui/react'
import { AttachmentIcon, ArrowUpIcon } from '@chakra-ui/icons'
import { useState, useRef, useEffect, useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

export default function ChatPage() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [selectedSolution, setSelectedSolution] = useState<string>('')
  const [useGraphContext, setUseGraphContext] = useState<boolean>(true)
  const [graphEnrichmentLevel, setGraphEnrichmentLevel] = useState<GraphEnrichmentLevel>('standard')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const toast = useToast()
  const queryClient = useQueryClient()

  // Concept card panel
  const {
    isOpen: isConceptPanelOpen,
    onOpen: openConceptPanel,
    onClose: closeConceptPanel,
  } = useDisclosure()
  const [selectedConceptId, setSelectedConceptId] = useState<string | null>(null)

  // Fetch available solutions
  const { data: solutionsResponse, isLoading: solutionsLoading } = useQuery({
    queryKey: ['solutions'],
    queryFn: () => api.search.solutions(),
  })

  // Fetch messages for current session
  const { data: messagesResponse, refetch: refetchMessages } = useQuery({
    queryKey: ['session-messages', currentSessionId],
    queryFn: () => currentSessionId ? api.sessions.getMessages(currentSessionId) : null,
    enabled: !!currentSessionId,
  })

  // Load messages when session changes
  useEffect(() => {
    if (messagesResponse?.success && messagesResponse.data) {
      const sessionMessages = (messagesResponse.data as { messages: any[] }).messages || []
      setMessages(sessionMessages.map((msg: any) => ({
        id: msg.id,
        content: msg.content,
        role: msg.role as 'user' | 'assistant',
        timestamp: msg.created_at,
        feedback_rating: msg.feedback_rating,
      })))
    }
  }, [messagesResponse])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Helper function to convert search results to markdown
  const formatSearchResults = (results: any[]): string => {
    if (!results || results.length === 0) {
      return 'Aucune information pertinente trouvee dans la base de connaissance.'
    }

    let markdown = ''

    const thumbnails = results
      .filter(r => r.slide_image_url)
      .slice(0, 4)
      .map(r => `[![Slide ${r.slide_index}](${r.slide_image_url})](${r.slide_image_url})`)

    if (thumbnails.length > 0) {
      markdown += '## Apercus\n\n' + thumbnails.join(' ') + '\n\n---\n\n'
    }

    results.forEach((result, index) => {
      const sourceInfo = result.source_file
        ? `*(${result.source_file.split('/').pop()}, slide ${result.slide_index})*`
        : '*(Source inconnue)*'

      const truncatedText = result.text.length > 150
        ? result.text.substring(0, 150) + '...'
        : result.text

      markdown += `- ${truncatedText}\n  ${sourceInfo}\n\n`
    })

    const sourceSet = new Set(results
      .filter(r => r.source_file)
      .map(r => r.source_file))
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
      // Create session if none exists
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

      // Save user message to session
      await api.sessions.addMessage(sessionId, {
        role: 'user',
        content: message,
      })

      // Send search request with session context for conversational continuity
      const response = await api.chat.send(
        message,
        undefined,
        undefined,
        selectedSolution || undefined,
        useGraphContext,
        useGraphContext ? graphEnrichmentLevel : undefined,
        sessionId
      )

      return { response, sessionId }
    },
    onSuccess: async ({ response, sessionId }) => {
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

        // 🌊 Phase 3.5: Extraire graph_data pour le ResponseGraph
        let graphData: GraphData | undefined
        if ((searchResult as any)?.graph_data) {
          graphData = parseGraphData((searchResult as any).graph_data) || undefined
        }

        // 🌊 Phase 3.5+: Extraire exploration_intelligence
        const explorationIntelligence: ExplorationIntelligence | undefined =
          (searchResult as any)?.exploration_intelligence

        // Save assistant message to session
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

        // Generate title if this is the first exchange
        if (messages.length <= 1) {
          api.sessions.generateTitle(sessionId)
            .then(() => queryClient.invalidateQueries({ queryKey: ['sessions'] }))
        }
      } else {
        toast({
          title: 'Erreur',
          description: response.error || 'Echec de l\'envoi du message',
          status: 'error',
          duration: 3000,
          isClosable: true,
        })
      }
    },
    onError: (error) => {
      toast({
        title: 'Erreur',
        description: 'Echec de l\'envoi du message',
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
    },
  })

  // Feedback mutation
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
        title: rating === 2 ? 'Merci !' : 'Feedback enregistre',
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
    // Naviguer vers un autre concept depuis le panel
    setSelectedConceptId(conceptId)
  }, [])

  const handleQuestionClick = useCallback((question: string) => {
    // Insérer la question suggérée dans l'input
    setInput(question)
    closeConceptPanel()
  }, [closeConceptPanel])

  // 🌊 Phase 3.5+: Callback pour les recherches depuis le graphe d'exploration
  const handleExplorationSearch = useCallback((query: string) => {
    // Insérer la requête dans l'input et déclencher la recherche
    setInput(query)
    // Auto-envoyer après un court délai pour que l'utilisateur voie la requête
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
    <Flex h="full" w="full" overflow="hidden">
      {/* Zone de Chat (100%) - graphe intégré dans chaque réponse */}
      <Flex
        direction="column"
        flex="1"
        minW={0}
        overflow="hidden"
      >
        {/* Session selector header */}
        <Box
          flexShrink={0}
          bg="gray.50"
          py={2}
          px={2}
          borderBottom="1px"
          borderColor="gray.200"
        >
          <HStack justify="space-between">
            <SessionSelector
              currentSessionId={currentSessionId}
              onSessionChange={handleSessionChange}
              onNewSession={handleNewSession}
            />
            <HStack spacing={2}>
              {currentSessionId && (
                <>
                  <Text fontSize="xs" color="gray.500">
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

        {/* Chat messages */}
        <Box
          flex="1"
          overflow="auto"
          bg="white"
          borderRadius="lg"
          shadow="sm"
          p={4}
          w="full"
          mt={2}
        >
          {messages.length === 0 ? (
            <Flex align="center" justify="center" h="full" direction="column">
              <Text fontSize="lg" color="gray.500" mb={4}>
                Bienvenue dans KnowWhere Chat
              </Text>
              <Text color="gray.400" textAlign="center" maxW="500px">
                Posez vos questions sur vos documents et je vous aiderai à trouver les informations.
                Chaque réponse affichera un Knowledge Graph dépliable montrant les concepts liés.
              </Text>
              {useGraphContext && (
                <Badge mt={4} colorScheme="teal" variant="subtle">
                  Graph-Guided RAG activé
                </Badge>
              )}
            </Flex>
          ) : (
            <VStack spacing={4} align="stretch">
              {messages.map((message) => (
                <Flex
                  key={message.id}
                  justify={message.role === 'user' ? 'flex-end' : 'flex-start'}
                >
                  <HStack
                    spacing={3}
                    maxW={{ base: "95%", md: "85%" }}
                    flexDirection={message.role === 'user' ? 'row-reverse' : 'row'}
                    align="flex-start"
                    w="full"
                  >
                    <Avatar
                      size="sm"
                      name={message.role === 'user' ? 'User' : 'Assistant'}
                      bg={message.role === 'user' ? 'blue.500' : 'green.500'}
                      flexShrink={0}
                    />
                    <Card flex="1" minW={0} position="relative" _hover={{ '& .copy-button': { opacity: 1 } }}>
                      <CardBody py={3} px={4}>
                        {message.role === 'assistant' && message.searchResult ? (
                          <SearchResultDisplay
                            searchResult={message.searchResult}
                            graphData={message.graphData}
                            explorationIntelligence={message.explorationIntelligence}
                            onSearch={handleExplorationSearch}
                          />
                        ) : (
                          <Text
                            fontSize="sm"
                            whiteSpace="pre-wrap"
                            wordBreak="break-word"
                            overflowWrap="break-word"
                          >
                            {message.content}
                          </Text>
                        )}
                        <Flex justify="space-between" align="center" mt={2}>
                          <HStack spacing={2}>
                            <Text fontSize="xs" color="gray.500">
                              {new Date(message.timestamp).toLocaleTimeString()}
                            </Text>
                            {/* Feedback buttons for assistant messages */}
                            {message.role === 'assistant' && currentSessionId && (
                              <HStack spacing={1}>
                                <Tooltip label="Utile">
                                  <IconButton
                                    aria-label="Thumbs up"
                                    icon={<span>+</span>}
                                    size="xs"
                                    variant={message.feedback_rating === 2 ? 'solid' : 'ghost'}
                                    colorScheme={message.feedback_rating === 2 ? 'green' : 'gray'}
                                    onClick={() => handleFeedback(message.id, 2)}
                                    isDisabled={feedbackMutation.isPending}
                                  />
                                </Tooltip>
                                <Tooltip label="Pas utile">
                                  <IconButton
                                    aria-label="Thumbs down"
                                    icon={<span>-</span>}
                                    size="xs"
                                    variant={message.feedback_rating === 1 ? 'solid' : 'ghost'}
                                    colorScheme={message.feedback_rating === 1 ? 'red' : 'gray'}
                                    onClick={() => handleFeedback(message.id, 1)}
                                    isDisabled={feedbackMutation.isPending}
                                  />
                                </Tooltip>
                              </HStack>
                            )}
                          </HStack>
                          <CopyButton
                            text={message.content}
                            className="copy-button"
                            size="xs"
                          />
                        </Flex>
                      </CardBody>
                    </Card>
                  </HStack>
                </Flex>
              ))}
              {sendMessageMutation.isPending && (
                <Flex justify="flex-start">
                  <HStack spacing={3}>
                    <Avatar size="sm" name="Assistant" bg="green.500" />
                    <Card>
                      <CardBody py={3} px={4}>
                        <HStack>
                          <Spinner size="sm" />
                          <Text fontSize="sm" color="gray.500">
                            Recherche en cours...
                          </Text>
                        </HStack>
                      </CardBody>
                    </Card>
                  </HStack>
                </Flex>
              )}
              <div ref={messagesEndRef} />
            </VStack>
          )}
        </Box>

        {/* Input area */}
        <Card w="full" flexShrink={0}>
          <CardBody>
            <VStack spacing={3} w="full">
              {/* Graph-Guided RAG controls */}
              <HStack spacing={4} w="full" justify="flex-start" flexWrap="wrap">
                <Tooltip label="Enrichir les reponses avec le Knowledge Graph" hasArrow>
                  <HStack spacing={2}>
                    <Switch
                      id="use-graph"
                      isChecked={useGraphContext}
                      onChange={(e) => setUseGraphContext(e.target.checked)}
                      colorScheme="teal"
                      size="sm"
                    />
                    <Text fontSize="sm" color="gray.600">
                      Knowledge Graph
                    </Text>
                  </HStack>
                </Tooltip>
                {useGraphContext && (
                  <HStack spacing={2}>
                    <Text fontSize="sm" color="gray.500">Niveau:</Text>
                    <Select
                      value={graphEnrichmentLevel}
                      onChange={(e) => setGraphEnrichmentLevel(e.target.value as GraphEnrichmentLevel)}
                      size="xs"
                      w="120px"
                      bg="white"
                    >
                      <option value="light">Light (~30ms)</option>
                      <option value="standard">Standard (~50ms)</option>
                      <option value="deep">Deep (~200ms)</option>
                    </Select>
                    <Tooltip
                      label={
                        graphEnrichmentLevel === 'light'
                          ? 'Concepts lies uniquement'
                          : graphEnrichmentLevel === 'standard'
                          ? 'Concepts + Relations transitives'
                          : 'Concepts + Relations + Clusters + Bridge concepts'
                      }
                      hasArrow
                    >
                      <Badge
                        colorScheme={
                          graphEnrichmentLevel === 'light'
                            ? 'gray'
                            : graphEnrichmentLevel === 'standard'
                            ? 'blue'
                            : 'purple'
                        }
                        fontSize="xs"
                      >
                        {graphEnrichmentLevel === 'deep' ? 'Deep' : graphEnrichmentLevel === 'standard' ? 'Std' : 'Light'}
                      </Badge>
                    </Tooltip>
                  </HStack>
                )}
              </HStack>

              {/* Message input row */}
              <HStack spacing={2} w="full">
                <IconButton
                  aria-label="Attach file"
                  icon={<AttachmentIcon />}
                  variant="ghost"
                  size="sm"
                  flexShrink={0}
                />
                <AutoResizeTextarea
                  value={input}
                  onChange={setInput}
                  onKeyDown={handleKeyPress}
                  placeholder="Posez votre question..."
                  flex="1"
                  minW={0}
                  minHeight={40}
                  maxHeight={200}
                />
                <IconButton
                  aria-label="Send message"
                  icon={<ArrowUpIcon />}
                  colorScheme="blue"
                  isDisabled={!input.trim() || sendMessageMutation.isPending}
                  isLoading={sendMessageMutation.isPending}
                  onClick={handleSend}
                  flexShrink={0}
                />
                <Select
                  placeholder="Toutes les solutions"
                  value={selectedSolution}
                  onChange={(e) => setSelectedSolution(e.target.value)}
                  size="sm"
                  bg="white"
                  isDisabled={solutionsLoading}
                  minW="200px"
                  maxW="250px"
                  flexShrink={0}
                >
                  {solutionsResponse?.success &&
                    Array.isArray(solutionsResponse.data) &&
                    solutionsResponse.data.map((solution: string) => (
                      <option key={solution} value={solution}>
                        {solution}
                      </option>
                    ))}
                </Select>
              </HStack>
            </VStack>
          </CardBody>
        </Card>
      </Flex>

      {/* Concept Card Panel (slide-in) */}
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
