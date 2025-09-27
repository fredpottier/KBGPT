'use client'

import {
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalFooter,
  ModalBody,
  ModalCloseButton,
  Button,
  FormControl,
  FormLabel,
  Input,
  Select,
  VStack,
  useToast,
} from '@chakra-ui/react'
import { useState } from 'react'
import { useUser } from '@/contexts/UserContext'
import { UserRole, UserCreate } from '@/types/user'

interface CreateUserModalProps {
  isOpen: boolean
  onClose: () => void
  onUserCreated?: (user: UserCreate & { id: string }) => void
}

export default function CreateUserModal({ isOpen, onClose, onUserCreated }: CreateUserModalProps) {
  const [formData, setFormData] = useState<UserCreate>({
    name: '',
    email: '',
    role: 'user'
  })
  const [isLoading, setIsLoading] = useState(false)
  const { createUser } = useUser()
  const toast = useToast()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!formData.name.trim()) {
      toast({
        title: 'Erreur de validation',
        description: 'Le nom est requis',
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
      return
    }

    try {
      setIsLoading(true)
      const newUser = await createUser({
        name: formData.name.trim(),
        email: formData.email?.trim() || undefined,
        role: formData.role
      })

      // Réinitialiser le formulaire
      setFormData({
        name: '',
        email: '',
        role: 'user'
      })

      onClose()

      // Callback optionnel pour sélectionner automatiquement le nouvel utilisateur
      if (onUserCreated) {
        onUserCreated(newUser)
      }

    } catch (error) {
      // L'erreur est déjà gérée par le UserProvider
      console.error('Erreur lors de la création:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleClose = () => {
    if (!isLoading) {
      setFormData({
        name: '',
        email: '',
        role: 'user'
      })
      onClose()
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={handleClose} size="md">
      <ModalOverlay />
      <ModalContent>
        <form onSubmit={handleSubmit}>
          <ModalHeader>Créer un nouvel utilisateur</ModalHeader>
          <ModalCloseButton isDisabled={isLoading} />

          <ModalBody>
            <VStack spacing={4}>
              <FormControl isRequired>
                <FormLabel>Nom</FormLabel>
                <Input
                  value={formData.name}
                  onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="Nom de l'utilisateur"
                  isDisabled={isLoading}
                  autoFocus
                />
              </FormControl>

              <FormControl>
                <FormLabel>Email</FormLabel>
                <Input
                  type="email"
                  value={formData.email}
                  onChange={(e) => setFormData(prev => ({ ...prev, email: e.target.value }))}
                  placeholder="email@example.com"
                  isDisabled={isLoading}
                />
              </FormControl>

              <FormControl>
                <FormLabel>Rôle</FormLabel>
                <Select
                  value={formData.role}
                  onChange={(e) => setFormData(prev => ({ ...prev, role: e.target.value as UserRole }))}
                  isDisabled={isLoading}
                >
                  <option value="user">Utilisateur</option>
                  <option value="expert">Expert</option>
                  <option value="admin">Administrateur</option>
                </Select>
              </FormControl>
            </VStack>
          </ModalBody>

          <ModalFooter>
            <Button variant="ghost" mr={3} onClick={handleClose} isDisabled={isLoading}>
              Annuler
            </Button>
            <Button
              colorScheme="blue"
              type="submit"
              isLoading={isLoading}
              loadingText="Création..."
            >
              Créer
            </Button>
          </ModalFooter>
        </form>
      </ModalContent>
    </Modal>
  )
}