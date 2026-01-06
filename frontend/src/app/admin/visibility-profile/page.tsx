'use client'

/**
 * Visibility Profile Selection - Admin Page
 * Left: vertical list, Right: detail on hover
 */

import {
  Box,
  VStack,
  HStack,
  Text,
  Icon,
  useToast,
  Spinner,
  Center,
  Badge,
  Flex,
} from '@chakra-ui/react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  FiShield,
  FiSliders,
  FiSearch,
  FiUnlock,
  FiCheck,
  FiInfo,
  FiAlertTriangle,
  FiChevronRight,
} from 'react-icons/fi'
import { apiClient } from '@/lib/api'

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

// Map profile IDs to icons and colors
const profileConfig: Record<string, { icon: any; color: string; gradient: string }> = {
  verified: { icon: FiShield, color: 'green', gradient: 'linear(to-br, green.500, green.600)' },
  balanced: { icon: FiSliders, color: 'blue', gradient: 'linear(to-br, #4338CA, #6366F1)' },
  exploratory: { icon: FiSearch, color: 'orange', gradient: 'linear(to-br, orange.500, orange.600)' },
  full_access: { icon: FiUnlock, color: 'red', gradient: 'linear(to-br, red.500, red.600)' },
}

export default function VisibilityProfilePage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [pendingProfile, setPendingProfile] = useState<string | null>(null)
  const [hoveredProfile, setHoveredProfile] = useState<string | null>(null)

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
        title: 'Profil mis à jour',
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
    return <Center h="200px"><Spinner size="md" color="brand.500" /></Center>
  }

  if (error || !profilesData) {
    return (
      <Center h="200px">
        <VStack spacing={2}>
          <Icon as={FiAlertTriangle} boxSize={8} color="red.400" />
          <Text fontSize="sm" color="text.muted">Erreur de chargement des profils</Text>
        </VStack>
      </Center>
    )
  }

  // Profile to display in detail panel (hovered or current)
  const displayedProfileId = hoveredProfile || profilesData.current_profile
  const displayedProfile = profilesData.profiles.find(p => p.id === displayedProfileId)
  const displayConfig = displayedProfile ? profileConfig[displayedProfile.id] : null

  return (
    <Box maxW="1000px" mx="auto" p={3}>
      {/* Compact Header */}
      <Flex justify="space-between" align="center" mb={4}>
        <HStack spacing={3}>
          <Box
            w={8}
            h={8}
            rounded="lg"
            bgGradient="linear(to-br, #4338CA, #6366F1)"
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon as={FiSliders} boxSize={4} color="white" />
          </Box>
          <Box>
            <Text fontSize="lg" fontWeight="bold" color="text.primary" lineHeight={1}>
              Profil de Visibilité
            </Text>
            <Text fontSize="xs" color="text.muted">
              Contrôle des informations affichées aux utilisateurs
            </Text>
          </Box>
        </HStack>
      </Flex>

      {/* Main content: List + Detail Panel - align stretch so left matches right height */}
      <Flex gap={4} direction={{ base: 'column', md: 'row' }} align="stretch">
        {/* Left: Vertical scale + list of profiles */}
        <Flex gap={0} flexShrink={0}>
          {/* Vertical scale indicator */}
          <Flex direction="column" align="center" py={1} pr={2}>
            <Text
              fontSize="9px"
              fontWeight="bold"
              color="green.400"
              style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
              letterSpacing="1px"
              flexShrink={0}
            >
              RESTRICTIF
            </Text>
            <Box
              w="3px"
              flex={1}
              my={1}
              rounded="full"
              bgGradient="linear(to-b, green.500, yellow.500, orange.500, red.500)"
              minH="50px"
            />
            <Text
              fontSize="9px"
              fontWeight="bold"
              color="red.400"
              style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
              letterSpacing="1px"
              flexShrink={0}
            >
              PERMISSIF
            </Text>
          </Flex>

          {/* Profile list - cards expand to fill height */}
          <Flex direction="column" gap={2} w={{ base: '100%', md: '320px' }} flex={1}>
            {profilesData.profiles.map((profile) => {
            const config = profileConfig[profile.id] || { icon: FiSliders, color: 'gray', gradient: 'linear(to-br, gray.500, gray.600)' }
            const isSelected = profile.id === profilesData.current_profile
            const isHovered = profile.id === hoveredProfile
            const isLoading = pendingProfile === profile.id

            return (
              <Flex
                key={profile.id}
                flex={1}
                bg={isSelected ? 'whiteAlpha.100' : 'whiteAlpha.50'}
                border="2px solid"
                borderColor={isSelected ? `${config.color}.500` : isHovered ? 'whiteAlpha.300' : 'whiteAlpha.100'}
                rounded="lg"
                p={3}
                cursor={isLoading ? 'wait' : 'pointer'}
                onClick={() => handleSelectProfile(profile.id)}
                onMouseEnter={() => setHoveredProfile(profile.id)}
                onMouseLeave={() => setHoveredProfile(null)}
                position="relative"
                transition="all 0.15s ease"
                align="center"
                _hover={{
                  bg: 'whiteAlpha.100',
                }}
              >
                {/* Loading overlay */}
                {isLoading && (
                  <Box
                    position="absolute"
                    inset={0}
                    bg="blackAlpha.600"
                    display="flex"
                    alignItems="center"
                    justifyContent="center"
                    rounded="lg"
                    zIndex={1}
                  >
                    <Spinner size="sm" color="white" />
                  </Box>
                )}

                <HStack spacing={3}>
                  {/* Icon */}
                  <Box
                    w={9}
                    h={9}
                    rounded="lg"
                    bgGradient={config.gradient}
                    display="flex"
                    alignItems="center"
                    justifyContent="center"
                    flexShrink={0}
                  >
                    <Icon as={config.icon} boxSize={4} color="white" />
                  </Box>

                  {/* Text */}
                  <Box flex={1} minW={0}>
                    <HStack spacing={1.5}>
                      <Text fontSize="sm" fontWeight="bold" color="text.primary" noOfLines={1}>
                        {profile.name}
                      </Text>
                      {profile.id === 'balanced' && (
                        <Badge colorScheme="blue" fontSize="9px" px={1}>Défaut</Badge>
                      )}
                    </HStack>
                    <Text fontSize="xs" color="text.muted" noOfLines={1}>
                      {profile.short_description}
                    </Text>
                  </Box>

                  {/* Selection indicator or arrow */}
                  {isSelected ? (
                    <Box
                      w={5}
                      h={5}
                      rounded="full"
                      bg={`${config.color}.500`}
                      display="flex"
                      alignItems="center"
                      justifyContent="center"
                      flexShrink={0}
                    >
                      <Icon as={FiCheck} color="white" boxSize={3} />
                    </Box>
                  ) : (
                    <Icon as={FiChevronRight} boxSize={4} color="text.muted" opacity={isHovered ? 1 : 0.3} />
                  )}
                </HStack>
              </Flex>
            )
          })}

            {/* Hint */}
            <HStack spacing={1.5} px={2} flexShrink={0}>
              <Icon as={FiInfo} boxSize={3} color="text.muted" />
              <Text fontSize="10px" color="text.muted">Survolez pour détails, cliquez pour activer</Text>
            </HStack>
          </Flex>
        </Flex>

        {/* Right: Detail Panel - Longest profile (full_access) sets height */}
        <Box
          flex={1}
          bg="whiteAlpha.50"
          border="1px solid"
          borderColor={displayConfig ? `${displayConfig.color}.500` : 'whiteAlpha.200'}
          borderLeftWidth="3px"
          rounded="lg"
          p={4}
          position="relative"
        >
          {/* Render full_access (longest) invisibly to establish container height */}
          {(() => {
            const longestProfile = profilesData.profiles.find(p => p.id === 'full_access') || profilesData.profiles[profilesData.profiles.length - 1]
            return (
              <VStack align="stretch" spacing={3} visibility="hidden" aria-hidden="true">
                <HStack spacing={3}>
                  <Box w={9} h={9} flexShrink={0} />
                  <Box flex={1}>
                    <HStack spacing={2}>
                      <Text fontSize="sm" fontWeight="bold">{longestProfile.name}</Text>
                    </HStack>
                    <Text fontSize="xs">{longestProfile.short_description}</Text>
                  </Box>
                </HStack>
                <Text fontSize="sm" whiteSpace="pre-wrap" lineHeight="tall">
                  {longestProfile.explanation}
                </Text>
                <Text fontSize="xs">→ Cliquez pour activer ce profil</Text>
              </VStack>
            )
          })()}

          {/* Actual visible content - positioned absolute */}
          {displayedProfile && displayConfig && (
            <VStack
              position="absolute"
              top={4}
              left={4}
              right={4}
              align="stretch"
              spacing={3}
            >
              <HStack spacing={3}>
                <Box
                  w={9}
                  h={9}
                  rounded="lg"
                  bgGradient={displayConfig.gradient}
                  display="flex"
                  alignItems="center"
                  justifyContent="center"
                  flexShrink={0}
                >
                  <Icon as={displayConfig.icon} boxSize={4} color="white" />
                </Box>
                <Box flex={1}>
                  <HStack spacing={2}>
                    <Text fontSize="sm" fontWeight="bold" color="text.primary">
                      {displayedProfile.name}
                    </Text>
                    {displayedProfile.id === profilesData.current_profile && (
                      <Badge colorScheme={displayConfig.color} fontSize="xs">Actif</Badge>
                    )}
                    {hoveredProfile && hoveredProfile !== profilesData.current_profile && (
                      <Badge colorScheme="gray" fontSize="xs" variant="outline">Aperçu</Badge>
                    )}
                  </HStack>
                  <Text fontSize="xs" color="text.muted">
                    {displayedProfile.short_description}
                  </Text>
                </Box>
              </HStack>

              <Text
                fontSize="sm"
                color="text.secondary"
                whiteSpace="pre-wrap"
                lineHeight="tall"
              >
                {displayedProfile.explanation}
              </Text>

              {hoveredProfile && hoveredProfile !== profilesData.current_profile && (
                <Text fontSize="xs" color={`${displayConfig.color}.400`} fontStyle="italic">
                  → Cliquez pour activer ce profil
                </Text>
              )}
            </VStack>
          )}
        </Box>
      </Flex>

      {/* Footer note */}
      <Box mt={4} px={3} py={2} borderLeft="2px solid" borderColor="#4338CA">
        <Text fontSize="xs" color="text.muted">
          <Text as="span" fontWeight="bold" color="text.secondary">Note :</Text> Le changement prend effet immédiatement pour toutes les requêtes. Les données existantes ne sont pas modifiées.
        </Text>
      </Box>
    </Box>
  )
}
