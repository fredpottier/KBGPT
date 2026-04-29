'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import {
  Box,
  HStack,
  VStack,
  Text,
  Icon,
  IconButton,
  Drawer,
  DrawerOverlay,
  DrawerContent,
  DrawerCloseButton,
  DrawerBody,
  useDisclosure,
  useBreakpointValue,
} from '@chakra-ui/react'
import {
  FiHome,
  FiServer,
  FiCpu,
  FiCloud,
  FiArchive,
  FiSettings,
  FiUploadCloud,
  FiTarget,
  FiDatabase,
  FiGlobe,
  FiShare2,
  FiFilter,
  FiPackage,
  FiBookOpen,
  FiEdit,
  FiBarChart2,
  FiAlertTriangle,
  FiActivity,
  FiMenu,
  FiDroplet,
  FiCheckCircle,
} from 'react-icons/fi'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'

interface SidebarItem {
  label: string
  href: string
  icon: React.ElementType
}

interface SidebarSection {
  title: string
  icon: React.ElementType
  color: string
  items: SidebarItem[]
}

const ADMIN_SECTIONS: SidebarSection[] = [
  {
    title: 'Infrastructure',
    icon: FiServer,
    color: 'green',
    items: [
      { label: 'GPU & Compute', href: '/admin/gpu', icon: FiCpu },
      { label: 'Backup & Restore', href: '/admin/backup', icon: FiArchive },
      { label: 'Configuration', href: '/admin/settings', icon: FiSettings },
      { label: 'Apparence (theme)', href: '/admin/theme', icon: FiDroplet },
    ],
  },
  {
    title: 'Import',
    icon: FiUploadCloud,
    color: 'orange',
    items: [
      { label: 'Claim-First Pipeline', href: '/admin/claimfirst', icon: FiTarget },
      { label: 'Mode Burst', href: '/admin/burst', icon: FiCloud },
    ],
  },
  {
    title: 'Knowledge Graph',
    icon: FiDatabase,
    color: 'brand',
    items: [
      { label: 'Domain Context', href: '/admin/domain-context', icon: FiGlobe },
      { label: 'Post-Import', href: '/admin/post-import', icon: FiShare2 },
      { label: 'KG Hygiene', href: '/admin/kg-hygiene', icon: FiFilter },
      { label: 'Domain Packs', href: '/admin/domain-packs', icon: FiPackage },
    ],
  },
  {
    title: 'Analyse',
    icon: FiActivity,
    color: 'cyan',
    items: [
      { label: 'Corpus Intelligence', href: '/admin/corpus-intelligence', icon: FiBarChart2 },
      { label: 'Contradictions', href: '/admin/contradictions', icon: FiAlertTriangle },
      { label: 'Relations V3.3', href: '/admin/relations', icon: FiActivity },
      { label: 'Golden Set (annotation)', href: '/admin/relations/golden-set', icon: FiCheckCircle },
      { label: 'Audit Corpus', href: '/admin/corpus-audit', icon: FiActivity },
      { label: 'Benchmarks', href: '/admin/benchmarks', icon: FiBarChart2 },
    ],
  },
  {
    title: 'Atlas',
    icon: FiBookOpen,
    color: 'purple',
    items: [
      { label: 'Générateur Atlas', href: '/admin/wiki-generator', icon: FiEdit },
    ],
  },
]

function SidebarContent({ onClose }: { onClose?: () => void }) {
  const pathname = usePathname()

  const isActive = (href: string) => {
    if (href === '/admin') return pathname === '/admin'
    return pathname?.startsWith(href) ?? false
  }

  return (
    <Box py={4}>
      {/* Dashboard link */}
      <Box px={3} mb={4}>
        <Link href="/admin" onClick={onClose}>
          <HStack
            px={3}
            py={2}
            rounded="lg"
            cursor="pointer"
            bg={isActive('/admin') ? 'var(--accent-glow)' : 'transparent'}
            color={isActive('/admin') ? 'brand.400' : 'var(--fg-secondary)'}
            _hover={{ bg: 'var(--bg-hover)', color: 'var(--fg-primary)' }}
            transition="all 0.15s"
          >
            <Icon as={FiHome} boxSize={4} />
            <Text fontSize="sm" fontWeight={isActive('/admin') ? 'semibold' : 'normal'}>
              Dashboard
            </Text>
          </HStack>
        </Link>
      </Box>

      {/* Sections */}
      {ADMIN_SECTIONS.map((section) => (
        <Box key={section.title} mb={4}>
          <HStack px={6} mb={1} spacing={1.5}>
            <Icon as={section.icon} boxSize={3} color={`${section.color}.400`} />
            <Text
              fontSize="xs"
              fontWeight="semibold"
              color="var(--fg-muted)"
              textTransform="uppercase"
              letterSpacing="wider"
            >
              {section.title}
            </Text>
          </HStack>
          <VStack spacing={0} align="stretch" px={3}>
            {section.items.map((item) => (
              <Link key={item.href} href={item.href} onClick={onClose}>
                <HStack
                  px={3}
                  py={1.5}
                  rounded="lg"
                  cursor="pointer"
                  bg={isActive(item.href) ? 'var(--accent-glow)' : 'transparent'}
                  color={isActive(item.href) ? 'brand.400' : 'var(--fg-secondary)'}
                  _hover={{ bg: 'var(--bg-hover)', color: 'var(--fg-primary)' }}
                  transition="all 0.15s"
                  borderLeft={isActive(item.href) ? '2px solid' : '2px solid transparent'}
                  borderColor={isActive(item.href) ? 'brand.400' : 'transparent'}
                >
                  <Icon as={item.icon} boxSize={3.5} />
                  <Text fontSize="sm" fontWeight={isActive(item.href) ? 'medium' : 'normal'}>
                    {item.label}
                  </Text>
                </HStack>
              </Link>
            ))}
          </VStack>
        </Box>
      ))}
    </Box>
  )
}

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { isOpen, onOpen, onClose } = useDisclosure()
  const isMobile = useBreakpointValue({ base: true, lg: false })

  return (
    <ProtectedRoute requireRole="admin">
      <HStack align="start" spacing={0}>
        {/* Desktop sidebar */}
        {!isMobile && (
          <Box
            w="240px"
            minH="calc(100vh - 64px)"
            bg="var(--bg-canvas)"
            borderRight="1px solid"
            borderColor="var(--border-default)"
            position="sticky"
            top="64px"
            overflowY="auto"
            flexShrink={0}
          >
            <SidebarContent />
          </Box>
        )}

        {/* Mobile hamburger */}
        {isMobile && (
          <IconButton
            aria-label="Menu admin"
            icon={<FiMenu />}
            variant="ghost"
            position="fixed"
            top="72px"
            left={2}
            zIndex={10}
            onClick={onOpen}
            color="var(--fg-muted)"
            _hover={{ color: 'var(--fg-primary)' }}
          />
        )}

        {/* Mobile drawer */}
        <Drawer isOpen={isOpen} placement="left" onClose={onClose}>
          <DrawerOverlay />
          <DrawerContent bg="var(--bg-canvas)" maxW="260px" mt="64px">
            <DrawerCloseButton color="var(--fg-muted)" />
            <DrawerBody p={0}>
              <SidebarContent onClose={onClose} />
            </DrawerBody>
          </DrawerContent>
        </Drawer>

        {/* Main content */}
        <Box flex={1} p={6} minH="calc(100vh - 64px)" overflowX="hidden">
          {children}
        </Box>
      </HStack>
    </ProtectedRoute>
  )
}
