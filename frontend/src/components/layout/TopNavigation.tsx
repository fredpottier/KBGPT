'use client'

import {
  Box,
  Flex,
  HStack,
  Link,
  Text,
  Avatar,
  Menu,
  MenuButton,
  MenuList,
  MenuItem,
  MenuDivider,
  Badge,
  Button,
  Icon,
  Image,
} from '@chakra-ui/react'
import { ChevronDownIcon } from '@chakra-ui/icons'
import { usePathname, useRouter } from 'next/navigation'
import NextLink from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import {
  FiMessageSquare,
  FiFolder,
  FiSettings,
  FiUpload,
  FiActivity,
  FiHome,
  FiGlobe,
  FiShare2,
  FiSliders,
  FiCloud,
  FiBarChart2,
} from 'react-icons/fi'

// Configuration des menus
const navigationConfig = {
  chat: {
    label: 'Chat',
    href: '/chat',
    icon: FiMessageSquare,
    isDropdown: false,
  },
  documents: {
    label: 'Documents',
    icon: FiFolder,
    isDropdown: true,
    items: [
      { label: 'Import fichier', href: '/documents/import', icon: FiUpload },
      { label: 'Suivi imports', href: '/documents/status', icon: FiActivity },
    ],
  },
  admin: {
    label: 'Administration',
    icon: FiSettings,
    isDropdown: true,
    items: [
      { label: 'Dashboard', href: '/admin', icon: FiHome },
      { label: 'Domain Context', href: '/admin/domain-context', icon: FiGlobe },
      { label: 'Profil Visibilite', href: '/admin/visibility-profile', icon: FiSliders },
      { label: 'Pass 2 Enrichment', href: '/admin/pass2', icon: FiActivity },
      { label: 'Consolidation KG', href: '/admin/consolidation', icon: FiShare2 },
      { label: 'Mode Burst (Spot)', href: '/admin/burst', icon: FiCloud },
      { label: 'Import Analytics', href: '/analytics', icon: FiBarChart2 },
      { label: 'Configuration', href: '/admin/settings', icon: FiSettings },
    ],
  },
}

interface NavLinkProps {
  href: string
  children: React.ReactNode
  isActive?: boolean
}

const NavLink = ({ href, children, isActive }: NavLinkProps) => {
  return (
    <Link
      as={NextLink}
      href={href}
      px={4}
      py={2}
      rounded="lg"
      display="flex"
      alignItems="center"
      gap={2}
      _hover={{
        textDecoration: 'none',
        bg: isActive ? undefined : 'bg.hover',
        bgGradient: isActive ? 'linear(to-r, #3730A3, #0E7490)' : undefined,
        transform: 'translateY(-1px)',
      }}
      bg={isActive ? undefined : 'transparent'}
      bgGradient={isActive ? 'linear(to-r, #4338CA, #0891B2)' : undefined}
      color={isActive ? 'white' : 'text.secondary'}
      fontWeight={isActive ? 'semibold' : 'medium'}
      transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
      boxShadow={isActive ? '0 0 15px rgba(67, 56, 202, 0.4)' : 'none'}
    >
      {children}
    </Link>
  )
}

interface NavDropdownProps {
  label: string
  icon: any
  items: { label: string; href: string; icon: any }[]
  isActive: boolean
}

const NavDropdown = ({ label, icon, items, isActive }: NavDropdownProps) => {
  const router = useRouter()
  const pathname = usePathname()

  return (
    <Menu>
      <MenuButton
        px={4}
        py={2}
        rounded="lg"
        bg={isActive ? undefined : 'transparent'}
        bgGradient={isActive ? 'linear(to-r, #4338CA, #0891B2)' : undefined}
        color={isActive ? 'white' : 'text.secondary'}
        fontWeight={isActive ? 'semibold' : 'medium'}
        transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
        boxShadow={isActive ? '0 0 15px rgba(67, 56, 202, 0.4)' : 'none'}
        _hover={{
          bg: isActive ? undefined : 'bg.hover',
          bgGradient: isActive ? 'linear(to-r, #3730A3, #0E7490)' : undefined,
          transform: 'translateY(-1px)',
        }}
      >
        <HStack spacing={2}>
          <Icon as={icon} />
          <Text>{label}</Text>
          <ChevronDownIcon />
        </HStack>
      </MenuButton>
      <MenuList
        bg="surface.default"
        shadow="xl"
        border="1px"
        borderColor="border.default"
        py={2}
        rounded="xl"
      >
        {items.map((item) => {
          const itemActive = pathname === item.href
          return (
            <MenuItem
              key={item.href}
              onClick={() => router.push(item.href)}
              icon={<Icon as={item.icon} />}
              bg={itemActive ? 'bg.hover' : 'transparent'}
              color={itemActive ? 'text.primary' : 'text.secondary'}
              fontWeight={itemActive ? 'semibold' : 'normal'}
              _hover={{ bg: 'bg.hover', color: 'text.primary' }}
              transition="all 0.15s"
            >
              {item.label}
            </MenuItem>
          )
        })}
      </MenuList>
    </Menu>
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

  const isActiveSection = (section: string) => {
    if (section === 'chat') return pathname?.startsWith('/chat')
    if (section === 'documents') return pathname?.startsWith('/documents')
    if (section === 'admin') return pathname?.startsWith('/admin')
    return false
  }

  return (
    <Box
      bg="bg.secondary"
      px={6}
      borderBottom="1px"
      borderColor="border.default"
      position="fixed"
      top={0}
      left={0}
      right={0}
      zIndex={1000}
      backdropFilter="blur(12px)"
    >
      <Flex h={16} alignItems="center" justifyContent="space-between">
        {/* Logo OSMOS */}
        <Flex alignItems="center" gap={2}>
          <Image
            src="/logo.png"
            alt="OSMOS Logo"
            h={10}
            w="auto"
            objectFit="contain"
          />
          <Text fontWeight="bold" fontSize="lg" color="text.primary">
            OSMOS
          </Text>
        </Flex>

        {/* Navigation Links avec Dropdowns */}
        <HStack spacing={2}>
          {/* Chat - lien direct */}
          <NavLink
            href={navigationConfig.chat.href!}
            isActive={isActiveSection('chat')}
          >
            <Icon as={navigationConfig.chat.icon} />
            <Text>{navigationConfig.chat.label}</Text>
          </NavLink>

          {/* Documents - dropdown */}
          <NavDropdown
            label={navigationConfig.documents.label}
            icon={navigationConfig.documents.icon}
            items={navigationConfig.documents.items!}
            isActive={isActiveSection('documents')}
          />

          {/* Administration - dropdown */}
          <NavDropdown
            label={navigationConfig.admin.label}
            icon={navigationConfig.admin.icon}
            items={navigationConfig.admin.items!}
            isActive={isActiveSection('admin')}
          />
        </HStack>

        {/* Right side - User menu */}
        {isAuthenticated ? (
          <HStack spacing={3}>
            <Menu>
              <MenuButton
                px={2}
                py={1}
                rounded="lg"
                transition="all 0.2s"
                _hover={{ bg: 'bg.hover' }}
              >
                <HStack spacing={2}>
                  <Avatar
                    size="sm"
                    name={user?.full_name || user?.email}
                    bg="brand.500"
                  />
                  <Box textAlign="left" display={{ base: 'none', md: 'block' }}>
                    <Text fontSize="sm" fontWeight="medium" color="text.primary">
                      {user?.full_name || user?.email?.split('@')[0]}
                    </Text>
                    <Text fontSize="xs" color="text.muted">
                      {user?.role}
                    </Text>
                  </Box>
                  <ChevronDownIcon color="text.secondary" />
                </HStack>
              </MenuButton>
              <MenuList bg="surface.default" borderColor="border.default" rounded="xl">
                <Box px={3} py={2}>
                  <Text fontSize="sm" fontWeight="medium" color="text.primary">
                    {user?.email}
                  </Text>
                  <Badge
                    colorScheme={
                      user?.role === 'admin' ? 'purple' :
                      user?.role === 'editor' ? 'blue' : 'gray'
                    }
                    size="sm"
                    mt={1}
                  >
                    {user?.role}
                  </Badge>
                </Box>
                <MenuDivider borderColor="border.default" />
                <MenuItem
                  onClick={() => router.push('/admin/settings')}
                  _hover={{ bg: 'bg.hover' }}
                >
                  Paramètres
                </MenuItem>
                <MenuDivider borderColor="border.default" />
                <MenuItem
                  onClick={handleLogout}
                  color="error.500"
                  _hover={{ bg: 'bg.hover' }}
                >
                  Déconnexion
                </MenuItem>
              </MenuList>
            </Menu>
          </HStack>
        ) : (
          <Button
            colorScheme="brand"
            size="sm"
            onClick={handleLogin}
            rounded="lg"
            _hover={{ transform: 'translateY(-1px)', boxShadow: 'md' }}
            transition="all 0.2s"
          >
            Connexion
          </Button>
        )}
      </Flex>
    </Box>
  )
}