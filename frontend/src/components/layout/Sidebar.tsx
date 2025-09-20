'use client'

import {
  Box,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerOverlay,
  Flex,
  Icon,
  Link,
  Text,
  VStack,
  useBreakpointValue,
  Image,
} from '@chakra-ui/react'
import { usePathname } from 'next/navigation'
import NextLink from 'next/link'
import { ReactNode } from 'react'
import {
  ChatIcon,
  ViewIcon,
  SettingsIcon,
  ExternalLinkIcon
} from '@chakra-ui/icons'

interface SidebarProps {
  isOpen: boolean
  onClose: () => void
}

interface NavItemProps {
  icon: any
  children: ReactNode
  href: string
  isActive?: boolean
  onClick?: () => void
}

const NavItem = ({ icon, children, href, isActive, onClick }: NavItemProps) => {
  return (
    <Link
      as={NextLink}
      href={href}
      onClick={onClick}
      style={{ textDecoration: 'none' }}
      _focus={{ boxShadow: 'none' }}
    >
      <Flex
        align="center"
        p="4"
        mx="4"
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
            mr="4"
            fontSize="16"
            as={icon}
          />
        )}
        {children}
      </Flex>
    </Link>
  )
}

export default function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname()
  const isMobile = useBreakpointValue({ base: true, md: false })

  const SidebarContent = () => (
    <Box
      bg="white"
      borderRight="1px"
      borderRightColor="gray.200"
      w={{ base: 'full', md: 60 }}
      pos="fixed"
      h="full"
      shadow="sm"
    >
      <Flex h="16" alignItems="center" mx="8" justifyContent="flex-start">
        <Image
          src="https://www.sap.com/dam/application/shared/logos/sap_logo_rgb_onwhite_0300_0300.png"
          alt="SAP Logo"
          height="40px"
          width="auto"
          objectFit="contain"
        />
      </Flex>

      <VStack spacing={1} align="stretch" mt={4}>
        <NavItem
          icon={ChatIcon}
          href="/chat"
          isActive={pathname?.startsWith('/chat')}
          onClick={isMobile ? onClose : undefined}
        >
          Chat
        </NavItem>
        <NavItem
          icon={ViewIcon}
          href="/documents"
          isActive={pathname?.startsWith('/documents')}
          onClick={isMobile ? onClose : undefined}
        >
          Documents
        </NavItem>
        <NavItem
          icon={SettingsIcon}
          href="/admin"
          isActive={pathname?.startsWith('/admin')}
          onClick={isMobile ? onClose : undefined}
        >
          Administration
        </NavItem>
      </VStack>

      {/* Footer */}
      <Box position="absolute" bottom="4" left="0" right="0" px="4">
        <Link
          href="https://github.com/yourusername/sap-kb"
          isExternal
          display="flex"
          alignItems="center"
          p="2"
          borderRadius="md"
          color="gray.500"
          _hover={{ color: 'gray.700', bg: 'gray.50' }}
          fontSize="sm"
        >
          <ExternalLinkIcon mr="2" />
          View on GitHub
        </Link>
      </Box>
    </Box>
  )

  if (isMobile) {
    return (
      <Drawer
        isOpen={isOpen}
        placement="left"
        onClose={onClose}
        returnFocusOnClose={false}
        onOverlayClick={onClose}
        size="full"
      >
        <DrawerOverlay />
        <DrawerContent>
          <DrawerCloseButton />
          <DrawerBody p={0}>
            <SidebarContent />
          </DrawerBody>
        </DrawerContent>
      </Drawer>
    )
  }

  return <SidebarContent />
}