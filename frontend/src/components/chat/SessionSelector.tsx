'use client'

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
  Badge,
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
} from '@chakra-ui/react'
import { ChevronDownIcon, AddIcon, DeleteIcon, EditIcon } from '@chakra-ui/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

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
    refetchInterval: 30000, // Refresh every 30s
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
            variant="outline"
            maxW="300px"
            isLoading={isLoading}
          >
            <Text isTruncated>
              {currentSession?.title || 'Nouvelle conversation'}
            </Text>
          </MenuButton>
          <MenuList maxH="400px" overflowY="auto">
            {sessions.length === 0 ? (
              <MenuItem isDisabled>Aucune session</MenuItem>
            ) : (
              sessions.map((session) => (
                <MenuItem
                  key={session.id}
                  onClick={() => onSessionChange(session.id)}
                  bg={session.id === currentSessionId ? 'blue.50' : undefined}
                >
                  <HStack justify="space-between" w="full">
                    <Box flex="1" minW={0}>
                      <Text fontSize="sm" fontWeight="medium" isTruncated>
                        {session.title || 'Sans titre'}
                      </Text>
                      <HStack spacing={2}>
                        <Text fontSize="xs" color="gray.500">
                          {formatDate(session.updated_at)}
                        </Text>
                        <Badge size="sm" colorScheme="gray">
                          {session.message_count} msg
                        </Badge>
                      </HStack>
                    </Box>
                    <HStack spacing={1}>
                      <Tooltip label="Renommer">
                        <Box
                          as="span"
                          display="inline-flex"
                          cursor="pointer"
                          p={1}
                          borderRadius="md"
                          _hover={{ bg: 'gray.100' }}
                          onClick={(e: React.MouseEvent) => {
                            e.stopPropagation()
                            handleEditTitle(session)
                          }}
                        >
                          <EditIcon boxSize={3} />
                        </Box>
                      </Tooltip>
                      <Tooltip label="Supprimer">
                        <Box
                          as="span"
                          display="inline-flex"
                          cursor="pointer"
                          p={1}
                          borderRadius="md"
                          color="red.500"
                          _hover={{ bg: 'red.50' }}
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
            <MenuDivider />
            <MenuItem
              icon={<AddIcon />}
              onClick={handleNewSession}
              isDisabled={createSessionMutation.isPending}
            >
              Nouvelle conversation
            </MenuItem>
          </MenuList>
        </Menu>

        <Tooltip label="Nouvelle conversation">
          <IconButton
            aria-label="New session"
            icon={<AddIcon />}
            size="sm"
            variant="ghost"
            onClick={handleNewSession}
            isLoading={createSessionMutation.isPending}
          />
        </Tooltip>
      </HStack>

      {/* Edit Title Modal */}
      <Modal isOpen={isOpen} onClose={onClose} size="sm">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Renommer la conversation</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <Input
              value={editingTitle}
              onChange={(e) => setEditingTitle(e.target.value)}
              placeholder="Titre de la conversation"
              autoFocus
            />
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" mr={3} onClick={onClose}>
              Annuler
            </Button>
            <Button
              colorScheme="blue"
              onClick={handleSaveTitle}
              isLoading={updateSessionMutation.isPending}
            >
              Enregistrer
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  )
}
