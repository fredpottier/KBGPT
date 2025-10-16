'use client'

import {
  Box,
  Flex,
  Text,
  IconButton,
  Avatar,
  Menu,
  MenuButton,
  MenuList,
  MenuItem,
  MenuDivider,
  useBreakpointValue,
  HStack,
  Badge,
  Button,
} from '@chakra-ui/react'
import { HamburgerIcon, BellIcon, ChevronDownIcon } from '@chakra-ui/icons'
import { useAuth } from '@/contexts/AuthContext'
import { useRouter } from 'next/navigation'

interface HeaderProps {
  title?: string
  onMenuClick: () => void
}

export default function Header({ title, onMenuClick }: HeaderProps) {
  const isMobile = useBreakpointValue({ base: true, md: false })
  const { user, isAuthenticated, logout } = useAuth()
  const router = useRouter()

  const handleLogout = () => {
    logout()
  }

  const handleLogin = () => {
    router.push('/login')
  }

  // Si non authentifié, afficher bouton login simple
  if (!isAuthenticated) {
    return (
      <Box
        bg="white"
        px={4}
        h="16"
        borderBottom="1px"
        borderBottomColor="gray.200"
        shadow="sm"
      >
        <Flex h="100%" alignItems="center" justifyContent="space-between">
          <HStack spacing={4}>
            <IconButton
              display={{ base: 'flex', md: 'none' }}
              onClick={onMenuClick}
              variant="ghost"
              aria-label="Open menu"
              icon={<HamburgerIcon />}
            />
            {title && (
              <Text fontSize="xl" fontWeight="semibold" color="gray.800">
                {title}
              </Text>
            )}
          </HStack>

          <Button colorScheme="brand" size="sm" onClick={handleLogin}>
            Sign In
          </Button>
        </Flex>
      </Box>
    )
  }

  // Utilisateur authentifié
  return (
    <Box
      bg="white"
      px={4}
      h="16"
      borderBottom="1px"
      borderBottomColor="gray.200"
      shadow="sm"
    >
      <Flex h="100%" alignItems="center" justifyContent="space-between">
        <HStack spacing={4}>
          {/* Mobile menu button */}
          <IconButton
            display={{ base: 'flex', md: 'none' }}
            onClick={onMenuClick}
            variant="ghost"
            aria-label="Open menu"
            icon={<HamburgerIcon />}
          />

          {/* Page title */}
          {title && (
            <Text fontSize="xl" fontWeight="semibold" color="gray.800">
              {title}
            </Text>
          )}
        </HStack>

        <HStack spacing={3}>
          {/* Notifications */}
          <Box position="relative">
            <IconButton
              aria-label="Notifications"
              icon={<BellIcon />}
              variant="ghost"
              size="sm"
            />
            <Badge
              position="absolute"
              top="0"
              right="0"
              transform="translate(25%, -25%)"
              bg="red.500"
              color="white"
              fontSize="xs"
              borderRadius="full"
              minW="1.2em"
              h="1.2em"
              display="flex"
              alignItems="center"
              justifyContent="center"
            >
              3
            </Badge>
          </Box>

          {/* User menu */}
          <Menu>
            <MenuButton>
              <HStack spacing={2}>
                <Avatar
                  size="sm"
                  name={user?.full_name || user?.email}
                  bg="brand.500"
                />
                {!isMobile && (
                  <>
                    <Box textAlign="left">
                      <Text fontSize="sm" fontWeight="medium">
                        {user?.full_name || user?.email?.split('@')[0]}
                      </Text>
                      <Text fontSize="xs" color="gray.500">
                        {user?.role}
                      </Text>
                    </Box>
                    <ChevronDownIcon />
                  </>
                )}
              </HStack>
            </MenuButton>
            <MenuList>
              <Box px={3} py={2}>
                <Text fontSize="sm" fontWeight="medium">
                  {user?.email}
                </Text>
                <Badge colorScheme={
                  user?.role === 'admin' ? 'purple' :
                  user?.role === 'editor' ? 'blue' : 'gray'
                } size="sm">
                  {user?.role}
                </Badge>
              </Box>
              <MenuDivider />
              <MenuItem onClick={() => router.push('/admin/settings')}>
                Settings
              </MenuItem>
              <MenuDivider />
              <MenuItem onClick={handleLogout} color="red.500">
                Sign out
              </MenuItem>
            </MenuList>
          </Menu>
        </HStack>
      </Flex>
    </Box>
  )
}