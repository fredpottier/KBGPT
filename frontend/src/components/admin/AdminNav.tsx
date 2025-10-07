'use client'

import { Box, HStack, Link, Text } from '@chakra-ui/react'
import NextLink from 'next/link'
import { usePathname } from 'next/navigation'

interface NavItem {
  label: string
  href: string
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', href: '/admin' },
  { label: 'Types Entités', href: '/admin/dynamic-types' },
  { label: 'Types de Documents', href: '/admin/document-types' },
  { label: 'Configuration', href: '/admin/settings' },
]

export default function AdminNav() {
  const pathname = usePathname()

  return (
    <Box
      bg="white"
      borderBottom="1px"
      borderColor="gray.200"
      px={6}
      py={3}
      mb={6}
      position="sticky"
      top={0}
      zIndex={10}
      shadow="sm"
    >
      <HStack spacing={6} overflowX="auto" css={{
        '&::-webkit-scrollbar': {
          height: '4px',
        },
        '&::-webkit-scrollbar-thumb': {
          background: '#CBD5E0',
          borderRadius: '4px',
        },
      }}>
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href || (item.href !== '/admin' && pathname?.startsWith(item.href))

          return (
            <Link
              key={item.href}
              as={NextLink}
              href={item.href}
              px={3}
              py={2}
              borderRadius="md"
              whiteSpace="nowrap"
              fontWeight={isActive ? 'semibold' : 'normal'}
              color={isActive ? 'blue.600' : 'gray.600'}
              bg={isActive ? 'blue.50' : 'transparent'}
              borderBottom={isActive ? '2px solid' : 'none'}
              borderColor="blue.600"
              _hover={{
                bg: isActive ? 'blue.100' : 'gray.50',
                color: isActive ? 'blue.700' : 'gray.900',
              }}
              transition="all 0.2s"
              textDecoration="none"
            >
              <Text fontSize="sm">{item.label}</Text>
            </Link>
          )
        })}
      </HStack>
    </Box>
  )
}
