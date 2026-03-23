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
import { useState, useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import NextLink from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import ThemeToggle from '@/components/layout/ThemeToggle'
import {
  FiMessageSquare,
  FiFolder,
  FiSettings,
  FiUpload,
  FiActivity,
  FiHome,
  FiGlobe,
  FiCloud,
  FiGitBranch,
  FiTarget,
  FiCheckSquare,
  FiCpu,
  FiArchive,
  FiBook,
  FiEdit,
  FiFilter,
} from 'react-icons/fi'

// Configuration des menus
const navigationConfig = {
  chat: {
    label: 'Chat',
    href: '/chat',
    icon: FiMessageSquare,
    isDropdown: false,
  },
  compare: {
    label: 'Compare',
    href: '/compare',
    icon: FiGitBranch,
    isDropdown: false,
  },
  verify: {
    label: 'Vérifier',
    href: '/verify',
    icon: FiCheckSquare,
    isDropdown: false,
  },
  wiki: {
    label: 'Atlas',
    icon: FiGlobe,
    isDropdown: true,
    items: [
      { label: 'Accueil', href: '/wiki', icon: FiHome },
      { label: 'Articles', href: '/wiki/articles', icon: FiBook },
    ],
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
    href: '/admin',
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
        bg: isActive ? undefined : 'var(--bg-hover)',
        bgGradient: isActive ? 'linear(to-r, brand.700, accent.700)' : undefined,
        transform: 'translateY(-1px)',
      }}
      bg={isActive ? undefined : 'transparent'}
      bgGradient={isActive ? 'linear(to-r, brand.600, accent.600)' : undefined}
      color={isActive ? 'white' : 'var(--text-secondary)'}
      fontWeight={isActive ? 'semibold' : 'medium'}
      transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
      boxShadow={isActive ? '0 0 15px var(--accent-glow)' : 'none'}
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
        bgGradient={isActive ? 'linear(to-r, brand.600, accent.600)' : undefined}
        color={isActive ? 'white' : 'var(--text-secondary)'}
        fontWeight={isActive ? 'semibold' : 'medium'}
        transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
        boxShadow={isActive ? '0 0 15px var(--accent-glow)' : 'none'}
        _hover={{
          bg: isActive ? undefined : 'var(--bg-hover)',
          bgGradient: isActive ? 'linear(to-r, brand.700, accent.700)' : undefined,
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
  const [hasCompare, setHasCompare] = useState(false)

  // Charger les features du corpus pour conditionner la navigation
  useEffect(() => {
    if (!isAuthenticated) return
    const token = localStorage.getItem('auth_token')
    if (!token) return
    fetch('/api/corpus-features', {
      headers: { 'Authorization': `Bearer ${token}` },
    })
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data) setHasCompare(!!data.has_compare)
      })
      .catch(() => {})
  }, [isAuthenticated])

  const handleLogout = () => {
    logout()
  }

  const handleLogin = () => {
    router.push('/login')
  }

  const isActiveSection = (section: string) => {
    if (section === 'chat') return pathname?.startsWith('/chat')
    if (section === 'compare') return pathname?.startsWith('/compare')
    if (section === 'verify') return pathname?.startsWith('/verify')
    if (section === 'wiki') return pathname?.startsWith('/wiki')
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
            alt="OSMOSIS Logo"
            h={10}
            w="auto"
            objectFit="contain"
          />
          <Text fontWeight="bold" fontSize="lg" color="text.primary">
            OSMOSIS
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

          {/* Compare - conditionné à la présence de versioning dans le corpus */}
          {hasCompare && (
            <NavLink
              href={navigationConfig.compare.href!}
              isActive={isActiveSection('compare')}
            >
              <Icon as={navigationConfig.compare.icon} />
              <Text>{navigationConfig.compare.label}</Text>
            </NavLink>
          )}

          {/* Verify - lien direct */}
          <NavLink
            href={navigationConfig.verify.href!}
            isActive={isActiveSection('verify')}
          >
            <Icon as={navigationConfig.verify.icon} />
            <Text>{navigationConfig.verify.label}</Text>
          </NavLink>

          {/* Atlas - dropdown */}
          <NavDropdown
            label={navigationConfig.wiki.label}
            icon={navigationConfig.wiki.icon}
            items={navigationConfig.wiki.items!}
            isActive={isActiveSection('wiki')}
          />

          {/* Documents - dropdown */}
          <NavDropdown
            label={navigationConfig.documents.label}
            icon={navigationConfig.documents.icon}
            items={navigationConfig.documents.items!}
            isActive={isActiveSection('documents')}
          />

          {/* Administration supprimé de la top nav — accessible via le menu utilisateur */}
        </HStack>

        {/* Right side - Theme toggle + User menu */}
        {isAuthenticated ? (
          <HStack spacing={3}>
            <ThemeToggle />
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