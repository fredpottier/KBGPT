'use client'

import {
  Box,
  Flex,
  HStack,
  Link,
  Text,
  Image,
  useColorModeValue,
} from '@chakra-ui/react'
import { usePathname } from 'next/navigation'
import NextLink from 'next/link'

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

        {/* Right side - could add user menu, settings, etc. */}
        <Box />
      </Flex>
    </Box>
  )
}