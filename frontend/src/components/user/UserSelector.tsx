'use client'

import {
  Menu,
  MenuButton,
  MenuList,
  MenuItem,
  MenuDivider,
  Button,
  Avatar,
  HStack,
  VStack,
  Text,
  Badge,
  IconButton,
  useDisclosure,
  Spinner,
  Box,
  useToast,
} from '@chakra-ui/react'
import { ChevronDownIcon, AddIcon, DeleteIcon, StarIcon } from '@chakra-ui/icons'
import { useState, useEffect } from 'react'
import { useUser } from '@/contexts/UserContext'
import CreateUserModal from './CreateUserModal'

const getRoleBadgeColor = (role: string) => {
  switch (role) {
    case 'admin':
      return 'red'
    case 'expert':
      return 'orange'
    case 'user':
    default:
      return 'blue'
  }
}

const getRoleLabel = (role: string) => {
  switch (role) {
    case 'admin':
      return 'Admin'
    case 'expert':
      return 'Expert'
    case 'user':
    default:
      return 'Utilisateur'
  }
}

export default function UserSelector() {
  const {
    currentUser,
    availableUsers,
    defaultUser,
    isLoading,
    error,
    switchUser,
    deleteUser,
    refreshUsers,
    setDefaultUser
  } = useUser()

  const { isOpen, onOpen, onClose } = useDisclosure()
  const toast = useToast()
  const [isClient, setIsClient] = useState(false)

  // S'assurer qu'on est côté client pour éviter les erreurs d'hydratation
  useEffect(() => {
    setIsClient(true)
  }, [])

  const handleUserChange = async (userId: string) => {
    if (userId === currentUser?.id) return
    await switchUser(userId)
  }

  const handleCreateUser = () => {
    onOpen()
  }

  const handleUserCreated = async (user: any) => {
    // Le nouvel utilisateur a été créé, basculer vers lui directement
    try {
      // Passer l'objet utilisateur complet au lieu de juste l'ID
      await switchUser(user)
    } catch (error) {
      console.warn('Erreur lors du changement vers le nouvel utilisateur:', error)
      // En cas d'erreur, juste rafraîchir la liste des utilisateurs
      await refreshUsers()
    }
  }

  const handleDeleteUser = async (userId: string, userName: string, e: React.MouseEvent) => {
    e.stopPropagation()

    if (userId === 'default-user') {
      toast({
        title: 'Action impossible',
        description: 'L\'utilisateur par défaut ne peut pas être supprimé',
        status: 'warning',
        duration: 3000,
        isClosable: true,
      })
      return
    }

    const confirmed = window.confirm(`Êtes-vous sûr de vouloir supprimer "${userName}" ?`)
    if (confirmed) {
      try {
        await deleteUser(userId)
      } catch (error) {
        // Erreur déjà gérée par le UserProvider
        console.error('Erreur lors de la suppression:', error)
      }
    }
  }

  const handleSetDefaultUser = async (userId: string, userName: string, e: React.MouseEvent) => {
    e.stopPropagation()

    try {
      await setDefaultUser(userId)
    } catch (error) {
      // Erreur déjà gérée par le UserProvider
      console.error('Erreur lors de la définition de l\'utilisateur par défaut:', error)
    }
  }

  // Ne pas rendre avant l'hydratation côté client
  if (!isClient) {
    return (
      <Box minW="200px" maxW="250px">
        <Text fontSize="sm" color="gray.500">...</Text>
      </Box>
    )
  }

  // Affichage en cas de chargement initial
  if (isLoading && !currentUser) {
    return (
      <HStack spacing={2}>
        <Spinner size="sm" />
        <Text fontSize="sm" color="gray.500">Chargement...</Text>
      </HStack>
    )
  }

  // Affichage en cas d'erreur
  if (error && !currentUser) {
    return (
      <Box>
        <Button
          size="sm"
          colorScheme="red"
          variant="outline"
          onClick={() => window.location.reload()}
        >
          Erreur - Recharger
        </Button>
      </Box>
    )
  }

  // Affichage principal
  return (
    <>
      <Menu>
        <MenuButton
          as={Button}
          rightIcon={<ChevronDownIcon />}
          size="sm"
          variant="ghost"
          minW="200px"
          maxW="250px"
        >
          <HStack spacing={2} justify="flex-start">
            <Avatar
              size="xs"
              name={currentUser?.name || 'User'}
              bg={getRoleBadgeColor(currentUser?.role || 'user')}
            />
            <VStack spacing={0} align="flex-start" flex="1" minW="0">
              <Text fontSize="sm" fontWeight="medium" isTruncated maxW="160px">
                {currentUser?.name || 'Aucun utilisateur'}
              </Text>
              {currentUser && (
                <Badge
                  size="xs"
                  colorScheme={getRoleBadgeColor(currentUser.role)}
                  variant="subtle"
                >
                  {getRoleLabel(currentUser.role)}
                </Badge>
              )}
            </VStack>
          </HStack>
        </MenuButton>

        <MenuList minW="280px">
          {/* Liste des utilisateurs */}
          {availableUsers.map((user) => (
            <MenuItem
              key={user.id}
              onClick={() => handleUserChange(user.id)}
              bg={user.id === currentUser?.id ? 'blue.50' : undefined}
              _hover={{ bg: user.id === currentUser?.id ? 'blue.100' : 'gray.50' }}
            >
              <HStack spacing={3} flex="1">
                <Avatar
                  size="sm"
                  name={user.name}
                  bg={getRoleBadgeColor(user.role)}
                />
                <VStack spacing={0} align="flex-start" flex="1" minW="0">
                  <HStack spacing={2} w="full">
                    <Text fontSize="sm" fontWeight="medium" isTruncated>
                      {user.name}
                    </Text>
                    <Badge
                      size="xs"
                      colorScheme={getRoleBadgeColor(user.role)}
                      variant="subtle"
                    >
                      {getRoleLabel(user.role)}
                    </Badge>
                  </HStack>
                  {user.email && (
                    <Text fontSize="xs" color="gray.500" isTruncated maxW="180px">
                      {user.email}
                    </Text>
                  )}
                </VStack>
                <HStack spacing={1}>
                  {/* Bouton pour définir comme utilisateur par défaut */}
                  <IconButton
                    aria-label={user.id === defaultUser?.id ? 'Utilisateur par défaut' : `Définir ${user.name} comme utilisateur par défaut`}
                    icon={<StarIcon />}
                    size="xs"
                    variant="ghost"
                    colorScheme={user.id === defaultUser?.id ? 'yellow' : 'gray'}
                    color={user.id === defaultUser?.id ? 'yellow.500' : 'gray.400'}
                    onClick={(e) => handleSetDefaultUser(user.id, user.name, e)}
                    _hover={{
                      bg: user.id === defaultUser?.id ? 'yellow.100' : 'gray.100',
                      color: user.id === defaultUser?.id ? 'yellow.600' : 'yellow.500'
                    }}
                    isDisabled={user.id === defaultUser?.id}
                  />
                  {/* Bouton de suppression */}
                  {user.id !== 'default-user' && (
                    <IconButton
                      aria-label={`Supprimer ${user.name}`}
                      icon={<DeleteIcon />}
                      size="xs"
                      variant="ghost"
                      colorScheme="red"
                      onClick={(e) => handleDeleteUser(user.id, user.name, e)}
                      _hover={{ bg: 'red.100' }}
                    />
                  )}
                </HStack>
              </HStack>
            </MenuItem>
          ))}

          <MenuDivider />

          {/* Option pour créer un nouvel utilisateur */}
          <MenuItem onClick={handleCreateUser} icon={<AddIcon />}>
            <Text fontWeight="medium" color="blue.600">
              Nouvel utilisateur
            </Text>
          </MenuItem>
        </MenuList>
      </Menu>

      {/* Modal de création d'utilisateur */}
      <CreateUserModal
        isOpen={isOpen}
        onClose={onClose}
        onUserCreated={handleUserCreated}
      />
    </>
  )
}