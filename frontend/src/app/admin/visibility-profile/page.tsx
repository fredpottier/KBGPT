'use client'

/**
 * Visibility Profile Selection - Admin Page
 *
 * Allows admin to select the visibility profile for the tenant.
 * Part of the Agnostic KG Architecture (Couche 3).
 *
 * 4 Profiles:
 * - verified: Only validated facts (2+ sources)
 * - balanced: Validated + reliable candidates (default)
 * - exploratory: Maximum connections for discovery
 * - full_access: Admin access, no filters
 */

import {
  Box,
  VStack,
  HStack,
  Text,
  Icon,
  Button,
  useToast,
  Spinner,
  Center,
  Collapse,
  Badge,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  FiShield,
  FiSliders,
  FiSearch,
  FiUnlock,
  FiCheck,
  FiChevronDown,
  FiChevronUp,
  FiInfo,
  FiAlertTriangle,
} from 'react-icons/fi'
import { apiClient } from '@/lib/api'

const MotionBox = motion(Box)

interface VisibilityProfile {
  id: string
  icon: string
  name: string
  short_description: string
  explanation: string
  is_current: boolean
}

interface ProfilesResponse {
  current_profile: string
  profiles: VisibilityProfile[]
}

// Map profile IDs to icons
const profileIcons: Record<string, any> = {
  verified: FiShield,
  balanced: FiSliders,
  exploratory: FiSearch,
  full_access: FiUnlock,
}

// Map profile IDs to colors
const profileColors: Record<string, string> = {
  verified: 'green',
  balanced: 'brand',
  exploratory: 'orange',
  full_access: 'red',
}

// Profile Card Component
const ProfileCard = ({
  profile,
  isSelected,
  onSelect,
  isLoading,
  delay = 0,
}: {
  profile: VisibilityProfile
  isSelected: boolean
  onSelect: () => void
  isLoading: boolean
  delay?: number
}) => {
  const [isExpanded, setIsExpanded] = useState(false)
  const color = profileColors[profile.id] || 'brand'
  const IconComponent = profileIcons[profile.id] || FiSliders

  return (
    <MotionBox
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay }}
    >
      <Box
        bg="bg.secondary"
        border="2px solid"
        borderColor={isSelected ? `${color}.500` : 'border.default'}
        rounded="xl"
        overflow="hidden"
        cursor="pointer"
        onClick={onSelect}
        _hover={{
          borderColor: `${color}.400`,
          transform: 'translateY(-2px)',
          boxShadow: `0 4px 20px rgba(99, 102, 241, 0.15)`,
        }}
        transition="all 0.2s"
        position="relative"
      >
        {/* Selection indicator */}
        {isSelected && (
          <Box
            position="absolute"
            top={3}
            right={3}
            w={6}
            h={6}
            rounded="full"
            bg={`${color}.500`}
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon as={FiCheck} color="white" boxSize={4} />
          </Box>
        )}

        {/* Main content */}
        <Box p={5}>
          <HStack spacing={4} align="start">
            {/* Icon */}
            <Box
              w={12}
              h={12}
              rounded="xl"
              bg={`rgba(99, 102, 241, 0.15)`}
              display="flex"
              alignItems="center"
              justifyContent="center"
              flexShrink={0}
            >
              <Icon as={IconComponent} boxSize={6} color={`${color}.400`} />
            </Box>

            {/* Text */}
            <VStack align="start" spacing={1} flex={1}>
              <HStack>
                <Text fontSize="lg" fontWeight="bold" color="text.primary">
                  {profile.icon} {profile.name}
                </Text>
                {profile.id === 'balanced' && (
                  <Badge colorScheme="brand" fontSize="xs">
                    Recommande
                  </Badge>
                )}
              </HStack>
              <Text fontSize="sm" color="text.secondary">
                {profile.short_description}
              </Text>
            </VStack>
          </HStack>

          {/* Expand button */}
          <Button
            variant="ghost"
            size="sm"
            mt={3}
            onClick={(e) => {
              e.stopPropagation()
              setIsExpanded(!isExpanded)
            }}
            rightIcon={<Icon as={isExpanded ? FiChevronUp : FiChevronDown} />}
            color="text.muted"
            _hover={{ color: 'text.primary' }}
          >
            {isExpanded ? 'Masquer les details' : 'Voir les details'}
          </Button>

          {/* Expanded content */}
          <Collapse in={isExpanded}>
            <Box
              mt={4}
              p={4}
              bg="bg.tertiary"
              rounded="lg"
              fontSize="sm"
              color="text.secondary"
              whiteSpace="pre-wrap"
              onClick={(e) => e.stopPropagation()}
            >
              {profile.explanation}
            </Box>
          </Collapse>
        </Box>

        {/* Loading overlay */}
        {isLoading && (
          <Box
            position="absolute"
            inset={0}
            bg="blackAlpha.600"
            display="flex"
            alignItems="center"
            justifyContent="center"
            rounded="xl"
          >
            <Spinner size="lg" color="white" />
          </Box>
        )}
      </Box>
    </MotionBox>
  )
}

export default function VisibilityProfilePage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [pendingProfile, setPendingProfile] = useState<string | null>(null)

  // Fetch profiles
  const {
    data: profilesData,
    isLoading,
    error,
  } = useQuery<ProfilesResponse>({
    queryKey: ['admin', 'visibility-profiles'],
    queryFn: async () => {
      const response = await apiClient.get<ProfilesResponse>('/admin/visibility-profiles')
      if (!response.success) throw new Error(response.error)
      return response.data
    },
  })

  // Mutation to change profile
  const changeProfileMutation = useMutation({
    mutationFn: async (profileId: string) => {
      const response = await apiClient.put('/admin/visibility-profiles/current', {
        profile_id: profileId,
      })
      if (!response.success) throw new Error(response.error)
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'visibility-profiles'] })
      toast({
        title: 'Profil mis a jour',
        description: data.message,
        status: 'success',
        duration: 3000,
      })
      setPendingProfile(null)
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur',
        description: error.response?.data?.detail || 'Impossible de changer le profil',
        status: 'error',
        duration: 5000,
      })
      setPendingProfile(null)
    },
  })

  const handleSelectProfile = (profileId: string) => {
    if (profileId === profilesData?.current_profile) return
    setPendingProfile(profileId)
    changeProfileMutation.mutate(profileId)
  }

  if (isLoading) {
    return (
      <Center h="400px">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="3px" />
          <Text color="text.muted">Chargement des profils...</Text>
        </VStack>
      </Center>
    )
  }

  if (error || !profilesData) {
    return (
      <Center h="400px">
        <Box
          bg="rgba(239, 68, 68, 0.1)"
          border="1px solid"
          borderColor="red.500"
          rounded="xl"
          p={8}
          textAlign="center"
        >
          <Icon as={FiAlertTriangle} boxSize={12} color="red.400" mb={4} />
          <Text fontSize="lg" fontWeight="medium" color="red.400" mb={2}>
            Erreur de chargement
          </Text>
          <Text fontSize="sm" color="text.muted">
            Impossible de charger les profils de visibilite
          </Text>
        </Box>
      </Center>
    )
  }

  return (
    <Box maxW="900px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={8}
      >
        <HStack spacing={3} mb={4}>
          <Box
            w={10}
            h={10}
            rounded="lg"
            bgGradient="linear(to-br, brand.500, accent.400)"
            display="flex"
            alignItems="center"
            justifyContent="center"
            boxShadow="0 0 20px rgba(99, 102, 241, 0.3)"
          >
            <Icon as={FiSliders} boxSize={5} color="white" />
          </Box>
          <VStack align="start" spacing={0}>
            <Text fontSize="2xl" fontWeight="bold" color="text.primary">
              Profil de Visibilite
            </Text>
            <Text color="text.secondary">
              Controlez les informations affichees aux utilisateurs
            </Text>
          </VStack>
        </HStack>

        {/* Info box */}
        <Box
          bg="bg.secondary"
          border="1px solid"
          borderColor="border.default"
          rounded="lg"
          p={4}
        >
          <HStack spacing={3} align="start">
            <Icon as={FiInfo} boxSize={5} color="brand.400" mt={0.5} />
            <VStack align="start" spacing={1}>
              <Text fontSize="sm" color="text.primary" fontWeight="medium">
                Comment ca fonctionne ?
              </Text>
              <Text fontSize="sm" color="text.secondary">
                Le profil determine quelles relations du graphe de connaissances sont
                visibles pour vos utilisateurs. Un profil plus restrictif affiche moins
                d&apos;informations mais avec plus de fiabilite. Ce parametre s&apos;applique
                a tous les utilisateurs de votre organisation.
              </Text>
            </VStack>
          </HStack>
        </Box>
      </MotionBox>

      {/* Profile Cards */}
      <VStack spacing={4} align="stretch">
        {profilesData.profiles.map((profile, index) => (
          <ProfileCard
            key={profile.id}
            profile={profile}
            isSelected={profile.id === profilesData.current_profile}
            onSelect={() => handleSelectProfile(profile.id)}
            isLoading={pendingProfile === profile.id}
            delay={index * 0.1}
          />
        ))}
      </VStack>

      {/* Footer note */}
      <MotionBox
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, delay: 0.5 }}
        mt={8}
      >
        <Box
          bg="bg.tertiary"
          rounded="lg"
          p={4}
          borderLeft="3px solid"
          borderColor="brand.500"
        >
          <Text fontSize="sm" color="text.muted">
            <strong>Note :</strong> Le changement de profil prend effet immediatement
            pour toutes les nouvelles requetes. Les donnees existantes ne sont pas
            modifiees, seul l&apos;affichage change.
          </Text>
        </Box>
      </MotionBox>
    </Box>
  )
}
