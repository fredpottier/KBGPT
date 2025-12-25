'use client'

/**
 * OSMOS Session Selector - Dark Elegance Edition
 *
 * Premium session management with dark theme
 */

import { useState } from 'react'
import {
  Box,
  Button,
  HStack,
  IconButton,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  MenuDivider,
  Text,
  Tooltip,
  useToast,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  ModalCloseButton,
  Input,
  useDisclosure,
  Icon,
  VStack,
} from '@chakra-ui/react'
import { ChevronDownIcon, AddIcon, DeleteIcon, EditIcon } from '@chakra-ui/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { FiMessageSquare, FiClock } from 'react-icons/fi'

interface Session {
  id: string
  title: string
  message_count: number
  updated_at: string
  is_active: boolean
}

interface SessionSelectorProps {
  currentSessionId: string | null
  onSessionChange: (sessionId: string | null) => void
  onNewSession: () => void
}

export default function SessionSelector({
  currentSessionId,
  onSessionChange,
  onNewSession,
}: SessionSelectorProps) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [editingTitle, setEditingTitle] = useState('')
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)

  // Fetch sessions list
  const { data: sessionsResponse, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => api.sessions.list(true, 20),
    refetchInterval: 30000,
  })

  const sessions: Session[] = sessionsResponse?.success
    ? (sessionsResponse.data as { sessions: Session[] })?.sessions || []
    : []

  const currentSession = sessions.find((s) => s.id === currentSessionId)

  // Create session mutation
  const createSessionMutation = useMutation({
    mutationFn: () => api.sessions.create(),
    onSuccess: (response) => {
      if (response.success && response.data) {
        const newSession = response.data as Session
        queryClient.invalidateQueries({ queryKey: ['sessions'] })
        onSessionChange(newSession.id)
        toast({
          title: 'Nouvelle session',
          description: 'Session de conversation creee',
          status: 'success',
          duration: 2000,
        })
      }
    },
    onError: () => {
      toast({
        title: 'Erreur',
        description: 'Impossible de creer la session',
        status: 'error',
        duration: 3000,
      })
    },
  })

  // Update session title mutation
  const updateSessionMutation = useMutation({
    mutationFn: ({ sessionId, title }: { sessionId: string; title: string }) =>
      api.sessions.update(sessionId, { title }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      onClose()
      toast({
        title: 'Titre mis a jour',
        status: 'success',
        duration: 2000,
      })
    },
  })

  // Delete session mutation
  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => api.sessions.delete(sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      if (currentSessionId) {
        onSessionChange(null)
      }
      toast({
        title: 'Session supprimee',
        status: 'info',
        duration: 2000,
      })
    },
  })

  const handleNewSession = () => {
    createSessionMutation.mutate()
  }

  const handleEditTitle = (session: Session) => {
    setEditingSessionId(session.id)
    setEditingTitle(session.title || '')
    onOpen()
  }

  const handleSaveTitle = () => {
    if (editingSessionId && editingTitle.trim()) {
      updateSessionMutation.mutate({
        sessionId: editingSessionId,
        title: editingTitle.trim(),
      })
    }
  }

  const handleDeleteSession = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (confirm('Supprimer cette session et tous ses messages ?')) {
      deleteSessionMutation.mutate(sessionId)
    }
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60))

    if (diffHours < 1) return 'Il y a quelques minutes'
    if (diffHours < 24) return `Il y a ${diffHours}h`
    if (diffHours < 48) return 'Hier'
    return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
  }

  return (
    <>
      <HStack spacing={2}>
        <Menu>
          <MenuButton
            as={Button}
            rightIcon={<ChevronDownIcon />}
            size="sm"
            variant="ghost"
            maxW="300px"
            isLoading={isLoading}
            bg="bg.tertiary"
            border="1px solid"
            borderColor="border.default"
            color="text.primary"
            _hover={{
              bg: 'bg.hover',
              borderColor: 'border.active',
            }}
            _active={{
              bg: 'bg.hover',
            }}
          >
            <HStack spacing={2}>
              <Icon as={FiMessageSquare} boxSize={4} color="brand.400" />
              <Text isTruncated fontWeight="medium">
                {currentSession?.title || 'Nouvelle conversation'}
              </Text>
            </HStack>
          </MenuButton>
          <MenuList
            bg="bg.secondary"
            border="1px solid"
            borderColor="border.default"
            rounded="xl"
            py={2}
            maxH="400px"
            overflowY="auto"
            boxShadow="0 4px 20px rgba(0, 0, 0, 0.3)"
          >
            {sessions.length === 0 ? (
              <MenuItem
                bg="transparent"
                color="text.muted"
                _hover={{ bg: 'bg.hover' }}
                isDisabled
              >
                Aucune session
              </MenuItem>
            ) : (
              sessions.map((session) => (
                <MenuItem
                  key={session.id}
                  onClick={() => onSessionChange(session.id)}
                  bg={session.id === currentSessionId ? 'rgba(99, 102, 241, 0.15)' : 'transparent'}
                  _hover={{ bg: 'bg.hover' }}
                  borderLeft={session.id === currentSessionId ? '3px solid' : '3px solid transparent'}
                  borderColor="brand.500"
                  px={4}
                  py={3}
                >
                  <HStack justify="space-between" w="full">
                    <VStack flex="1" minW={0} align="start" spacing={1}>
                      <Text fontSize="sm" fontWeight="medium" color="text.primary" noOfLines={1}>
                        {session.title || 'Sans titre'}
                      </Text>
                      <HStack spacing={3}>
                        <HStack spacing={1}>
                          <Icon as={FiClock} boxSize={3} color="text.muted" />
                          <Text fontSize="xs" color="text.muted">
                            {formatDate(session.updated_at)}
                          </Text>
                        </HStack>
                        <HStack
                          px={2}
                          py={0.5}
                          bg="bg.tertiary"
                          rounded="full"
                          spacing={1}
                        >
                          <Icon as={FiMessageSquare} boxSize={3} color="text.muted" />
                          <Text fontSize="xs" color="text.muted">
                            {session.message_count}
                          </Text>
                        </HStack>
                      </HStack>
                    </VStack>
                    <HStack spacing={1}>
                      <Tooltip label="Renommer" bg="bg.tertiary" color="text.primary">
                        <Box
                          as="span"
                          display="inline-flex"
                          cursor="pointer"
                          p={1.5}
                          borderRadius="md"
                          color="text.muted"
                          _hover={{ bg: 'bg.tertiary', color: 'text.primary' }}
                          onClick={(e: React.MouseEvent) => {
                            e.stopPropagation()
                            handleEditTitle(session)
                          }}
                        >
                          <EditIcon boxSize={3} />
                        </Box>
                      </Tooltip>
                      <Tooltip label="Supprimer" bg="bg.tertiary" color="text.primary">
                        <Box
                          as="span"
                          display="inline-flex"
                          cursor="pointer"
                          p={1.5}
                          borderRadius="md"
                          color="text.muted"
                          _hover={{ bg: 'rgba(239, 68, 68, 0.15)', color: 'red.400' }}
                          onClick={(e: React.MouseEvent) => handleDeleteSession(session.id, e)}
                        >
                          <DeleteIcon boxSize={3} />
                        </Box>
                      </Tooltip>
                    </HStack>
                  </HStack>
                </MenuItem>
              ))
            )}
            <MenuDivider borderColor="border.default" />
            <MenuItem
              icon={<AddIcon />}
              onClick={handleNewSession}
              isDisabled={createSessionMutation.isPending}
              bg="transparent"
              color="brand.400"
              _hover={{ bg: 'rgba(99, 102, 241, 0.15)' }}
              fontWeight="medium"
            >
              Nouvelle conversation
            </MenuItem>
          </MenuList>
        </Menu>

        <Tooltip label="Nouvelle conversation" bg="bg.tertiary" color="text.primary">
          <IconButton
            aria-label="New session"
            icon={<AddIcon />}
            size="sm"
            variant="ghost"
            onClick={handleNewSession}
            isLoading={createSessionMutation.isPending}
            color="text.muted"
            _hover={{
              bg: 'rgba(99, 102, 241, 0.15)',
              color: 'brand.400',
            }}
          />
        </Tooltip>
      </HStack>

      {/* Edit Title Modal */}
      <Modal isOpen={isOpen} onClose={onClose} size="sm" isCentered>
        <ModalOverlay bg="rgba(0, 0, 0, 0.7)" backdropFilter="blur(4px)" />
        <ModalContent
          bg="bg.secondary"
          border="1px solid"
          borderColor="border.default"
          rounded="xl"
        >
          <ModalHeader color="text.primary" borderBottom="1px solid" borderColor="border.default">
            Renommer la conversation
          </ModalHeader>
          <ModalCloseButton color="text.muted" />
          <ModalBody py={6}>
            <Input
              value={editingTitle}
              onChange={(e) => setEditingTitle(e.target.value)}
              placeholder="Titre de la conversation"
              autoFocus
              bg="bg.tertiary"
              border="1px solid"
              borderColor="border.default"
              color="text.primary"
              _placeholder={{ color: 'text.muted' }}
              _hover={{ borderColor: 'border.active' }}
              _focus={{
                borderColor: 'brand.500',
                boxShadow: '0 0 0 1px var(--chakra-colors-brand-500)',
              }}
            />
          </ModalBody>
          <ModalFooter borderTop="1px solid" borderColor="border.default">
            <Button
              variant="ghost"
              mr={3}
              onClick={onClose}
              color="text.secondary"
              _hover={{ bg: 'bg.hover', color: 'text.primary' }}
            >
              Annuler
            </Button>
            <Button
              bg="brand.500"
              color="white"
              onClick={handleSaveTitle}
              isLoading={updateSessionMutation.isPending}
              _hover={{
                bg: 'brand.600',
                boxShadow: '0 0 15px rgba(99, 102, 241, 0.4)',
              }}
            >
              Enregistrer
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  )
}
