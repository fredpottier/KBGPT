'use client'

import {
  Box,
  Flex,
  HStack,
  Link,
  Text,
  Image,
  useColorModeValue,
  Avatar,
  Menu,
  MenuButton,
  MenuList,
  MenuItem,
  MenuDivider,
  Badge,
  Button,
  IconButton,
} from '@chakra-ui/react'
import { ChevronDownIcon, BellIcon } from '@chakra-ui/icons'
import { usePathname, useRouter } from 'next/navigation'
import NextLink from 'next/link'
import { useAuth } from '@/contexts/AuthContext'

interface NavLinkProps {
  href: string
  children: React.ReactNode
  isActive?: boolean
}

const NavLink = ({ href, children, isActive }: NavLinkProps) => {
  const bg = useColorModeValue('brand.500', 'brand.200')
  const color = useColorModeValue('white', 'gray.800')
  const hoverBg = useColorModeValue('brand.600', 'brand.300')

  return (
    <Link
      as={NextLink}
      href={href}
      px={4}
      py={2}
      rounded="md"
      _hover={{
        textDecoration: 'none',
        bg: isActive ? hoverBg : 'gray.100',
      }}
      bg={isActive ? bg : 'transparent'}
      color={isActive ? color : 'gray.600'}
      fontWeight={isActive ? 'semibold' : 'normal'}
      transition="all 0.2s"
    >
      {children}
    </Link>
  )
}

export default function TopNavigation() {
  const pathname = usePathname()
  const router = useRouter()
  const { user, isAuthenticated, logout } = useAuth()

  const handleLogout = () => {
    logout()
  }

  const handleLogin = () => {
    router.push('/login')
  }

  return (
    <Box
      bg="white"
      px={4}
      shadow="sm"
      borderBottom="1px"
      borderColor="gray.200"
      position="fixed"
      top={0}
      left={0}
      right={0}
      zIndex={1000}
    >
      <Flex h={16} alignItems="center" justifyContent="space-between">
        {/* Logo */}
        <Flex alignItems="center">
          <Image
            src="https://www.sap.com/dam/application/shared/logos/sap_logo_rgb_onwhite_0300_0300.png"
            alt="SAP Logo"
            height="32px"
            width="auto"
            objectFit="contain"
            mr={8}
          />
        </Flex>

        {/* Navigation Links */}
        <HStack spacing={8}>
          <NavLink href="/chat" isActive={pathname?.startsWith('/chat')}>
            Chat
          </NavLink>
          <NavLink href="/documents" isActive={pathname?.startsWith('/documents')}>
            Documents
          </NavLink>
          <NavLink href="/admin" isActive={pathname?.startsWith('/admin')}>
            Administration
          </NavLink>
        </HStack>

        {/* Right side - User menu */}
        {isAuthenticated ? (
          <HStack spacing={3}>
            {/* User menu */}
            <Menu>
              <MenuButton>
                <HStack spacing={2}>
                  <Avatar
                    size="sm"
                    name={user?.full_name || user?.email}
                    bg="brand.500"
                  />
                  <Box textAlign="left" display={{ base: 'none', md: 'block' }}>
                    <Text fontSize="sm" fontWeight="medium">
                      {user?.full_name || user?.email?.split('@')[0]}
                    </Text>
                    <Text fontSize="xs" color="gray.500">
                      {user?.role}
                    </Text>
                  </Box>
                  <ChevronDownIcon />
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
        ) : (
          <Button colorScheme="brand" size="sm" onClick={handleLogin}>
            Sign In
          </Button>
        )}
      </Flex>
    </Box>
  )
}