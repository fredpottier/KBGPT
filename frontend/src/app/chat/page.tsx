'use client'

import {
  Box,
  Button,
  Flex,
  HStack,
  Input,
  Text,
  VStack,
  Card,
  CardBody,
  Avatar,
  Spinner,
  IconButton,
  Textarea,
  useToast,
  Select,
  Switch,
  Tooltip,
  Badge,
} from '@chakra-ui/react'
import { AttachmentIcon, ArrowUpIcon } from '@chakra-ui/icons'
import { useState, useRef, useEffect } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { SearchResponse } from '@/types/api'
import CopyButton from '@/components/ui/CopyButton'
import AutoResizeTextarea from '@/components/ui/AutoResizeTextarea'
import SearchResultDisplay from '@/components/ui/SearchResultDisplay'

interface Message {
  id: string
  content: string
  role: 'user' | 'assistant'
  timestamp: string
  searchResult?: SearchResponse // Add search result for assistant messages
}

type GraphEnrichmentLevel = 'none' | 'light' | 'standard' | 'deep'

export default function ChatPage() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [selectedSolution, setSelectedSolution] = useState<string>('')
  const [useGraphContext, setUseGraphContext] = useState<boolean>(true)
  const [graphEnrichmentLevel, setGraphEnrichmentLevel] = useState<GraphEnrichmentLevel>('standard')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const toast = useToast()

  // Fetch available solutions
  const { data: solutionsResponse, isLoading: solutionsLoading } = useQuery({
    queryKey: ['solutions'],
    queryFn: () => api.search.solutions(),
  })

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }


  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Helper function to convert search results to markdown
  const formatSearchResults = (results: any[]): string => {
    if (!results || results.length === 0) {
      return 'Aucune information pertinente trouvée dans la base de connaissance.'
    }

    let markdown = ''

    // Add thumbnails if available
    const thumbnails = results
      .filter(r => r.slide_image_url)
      .slice(0, 4) // Limit to 4 thumbnails
      .map(r => `[![Slide ${r.slide_index}](${r.slide_image_url})](${r.slide_image_url})`)

    if (thumbnails.length > 0) {
      markdown += '## 📸 Aperçus\n\n' + thumbnails.join(' ') + '\n\n---\n\n'
    }

    // Add results
    results.forEach((result, index) => {
      const score = (result.score * 100).toFixed(0)
      const sourceInfo = result.source_file
        ? `*(${result.source_file.split('/').pop()}, slide ${result.slide_index})*`
        : '*(Source inconnue)*'

      const truncatedText = result.text.length > 150
        ? result.text.substring(0, 150) + '...'
        : result.text

      markdown += `- ${truncatedText}\n  ${sourceInfo}\n\n`
    })

    // Add sources section
    const sourceSet = new Set(results
      .filter(r => r.source_file)
      .map(r => r.source_file))
    const sources = Array.from(sourceSet)

    if (sources.length > 0) {
      markdown += '**📎 Sources**\n\n'
      sources.forEach(source => {
        const filename = source.split('/').pop()
        const extension = filename?.split('.').pop()?.toUpperCase() || 'FILE'
        markdown += `- [${filename}](${source}) — ${extension}\n`
      })
    }

    return markdown
  }

  const sendMessageMutation = useMutation({
    mutationFn: (message: string) =>
      api.chat.send(
        message,
        undefined,
        undefined,
        selectedSolution || undefined,
        useGraphContext,
        useGraphContext ? graphEnrichmentLevel : undefined
      ),
    onSuccess: (response) => {
      if (response.success) {
        const searchResult = response.data as SearchResponse

        // Use synthesis if available, otherwise fallback to formatted results
        let content = 'No response'
        if (searchResult?.synthesis?.synthesized_answer) {
          content = searchResult.synthesis.synthesized_answer
        } else if (searchResult?.results && Array.isArray(searchResult.results)) {
          content = formatSearchResults(searchResult.results)
        } else if ((response.data as any)?.answer_markdown) {
          // Fallback for dispatch format
          content = (response.data as any).answer_markdown
        }

        const newMessage: Message = {
          id: Date.now().toString(),
          content,
          role: 'assistant',
          timestamp: new Date().toISOString(),
          searchResult: searchResult
        }
        setMessages(prev => [...prev, newMessage])
      } else {
        toast({
          title: 'Error',
          description: response.error || 'Failed to send message',
          status: 'error',
          duration: 3000,
          isClosable: true,
        })
      }
    },
    onError: (error) => {
      toast({
        title: 'Error',
        description: 'Failed to send message',
        status: 'error',
        duration: 3000,
        isClosable: true,
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

  return (
    <Flex direction="column" h="full" gap={4} w="full" maxW="100%">
      {/* Chat messages */}
      <Box
        flex="1"
        overflow="auto"
        bg="white"
        borderRadius="lg"
        shadow="sm"
        p={4}
        w="full"
        maxW="100%"
      >
        {messages.length === 0 ? (
          <Flex align="center" justify="center" h="full" direction="column">
            <Text fontSize="lg" color="gray.500" mb={4}>
              Welcome to SAP Knowledge Base Chat
            </Text>
            <Text color="gray.400" textAlign="center">
              Ask me anything about your SAP documents and I&apos;ll help you find the information you need.
            </Text>
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
                      {/* Show SearchResultDisplay for assistant messages with search results */}
                      {message.role === 'assistant' && message.searchResult ? (
                        <SearchResultDisplay searchResult={message.searchResult} />
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
                        <Text fontSize="xs" color="gray.500">
                          {new Date(message.timestamp).toLocaleTimeString()}
                        </Text>
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
                          Thinking...
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
      <Card w="full">
        <CardBody>
          <VStack spacing={3} w="full">
            {/* Graph-Guided RAG controls */}
            <HStack spacing={4} w="full" justify="flex-start" flexWrap="wrap">
              <Tooltip label="Enrichir les réponses avec le Knowledge Graph" hasArrow>
                <HStack spacing={2}>
                  <Switch
                    id="use-graph"
                    isChecked={useGraphContext}
                    onChange={(e) => setUseGraphContext(e.target.checked)}
                    colorScheme="teal"
                    size="sm"
                  />
                  <Text fontSize="sm" color="gray.600">
                    🌊 Knowledge Graph
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
                        ? 'Concepts liés uniquement'
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
                      {graphEnrichmentLevel === 'deep' ? '🚀' : graphEnrichmentLevel === 'standard' ? '⚡' : '💨'}
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
                placeholder="Type your message here..."
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
  )
}