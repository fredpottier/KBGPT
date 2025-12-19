'use client'

import {
  Box,
  VStack,
  Link,
  Text,
  Icon,
  Flex,
} from '@chakra-ui/react'
import { usePathname } from 'next/navigation'
import NextLink from 'next/link'
import { ReactNode } from 'react'
import {
  AttachmentIcon,
  EditIcon,
  ViewIcon,
  SettingsIcon,
  CheckCircleIcon,
} from '@chakra-ui/icons'
import { FiDatabase, FiLayers, FiGlobe } from 'react-icons/fi'

interface SidebarItemProps {
  icon?: any
  children: ReactNode
  href: string
  isActive?: boolean
}

const SidebarItem = ({ icon, children, href, isActive }: SidebarItemProps) => {
  return (
    <Link
      as={NextLink}
      href={href}
      style={{ textDecoration: 'none' }}
      _focus={{ boxShadow: 'none' }}
    >
      <Flex
        align="center"
        p="3"
        mx="3"
        borderRadius="lg"
        role="group"
        cursor="pointer"
        bg={isActive ? 'brand.500' : 'transparent'}
        color={isActive ? 'white' : 'gray.600'}
        _hover={{
          bg: isActive ? 'brand.600' : 'gray.100',
          color: isActive ? 'white' : 'gray.900',
        }}
        transition="all 0.2s"
      >
        {icon && (
          <Icon
            mr="3"
            fontSize="16"
            as={icon}
          />
        )}
        <Text fontSize="sm">{children}</Text>
      </Flex>
    </Link>
  )
}

interface ContextualSidebarProps {
  section: 'chat' | 'documents' | 'admin'
}

export default function ContextualSidebar({ section }: ContextualSidebarProps) {
  const pathname = usePathname()

  // Ne pas afficher de sidebar pour le chat
  if (section === 'chat') {
    return null
  }

  const getMenuItems = () => {
    switch (section) {
      case 'documents':
        return [
          {
            icon: AttachmentIcon,
            label: 'Import fichier',
            href: '/documents/import',
          },
          {
            icon: ViewIcon,
            label: 'Suivi imports',
            href: '/documents/status',
          },
          {
            icon: EditIcon,
            label: 'RFP Excel',
            href: '/rfp-excel',
          },
        ]
      case 'admin':
        return [
          {
            icon: ViewIcon,
            label: 'Dashboard',
            href: '/admin',
          },
          {
            icon: AttachmentIcon,
            label: 'Gestion Documents',
            href: '/admin/documents',
          },
          {
            icon: FiLayers,
            label: 'Types Entités',
            href: '/admin/dynamic-types',
          },
          {
            icon: FiGlobe,
            label: 'Domain Context',
            href: '/admin/domain-context',
          },
          {
            icon: SettingsIcon,
            label: 'Configuration',
            href: '/admin/settings',
          },
        ]
      default:
        return []
    }
  }

  const menuItems = getMenuItems()

  // Ne pas afficher la sidebar s'il n'y a pas d'éléments de menu
  if (menuItems.length === 0) {
    return null
  }

  return (
    <Box
      bg="white"
      borderRight="1px"
      borderRightColor="gray.200"
      w={64}
      h="full"
      shadow="sm"
      position="fixed"
      top="64px" // Hauteur de la TopNavigation
      left={0}
      bottom={0}
      overflowY="auto"
    >
      <VStack spacing={1} align="stretch" pt={4}>
        {menuItems.map((item) => (
          <SidebarItem
            key={item.href}
            icon={item.icon}
            href={item.href}
            isActive={pathname === item.href}
          >
            {item.label}
          </SidebarItem>
        ))}
      </VStack>
    </Box>
  )
}