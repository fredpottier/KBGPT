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
} from '@chakra-ui/react'
import { HamburgerIcon, BellIcon, ChevronDownIcon } from '@chakra-ui/icons'

interface HeaderProps {
  title?: string
  onMenuClick: () => void
}

export default function Header({ title, onMenuClick }: HeaderProps) {
  const isMobile = useBreakpointValue({ base: true, md: false })

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
                  name="John Doe"
                  bg="brand.500"
                />
                {!isMobile && (
                  <>
                    <Text fontSize="sm" fontWeight="medium">
                      John Doe
                    </Text>
                    <ChevronDownIcon />
                  </>
                )}
              </HStack>
            </MenuButton>
            <MenuList>
              <MenuItem>Profile</MenuItem>
              <MenuItem>Settings</MenuItem>
              <MenuItem>Billing</MenuItem>
              <MenuDivider />
              <MenuItem>Sign out</MenuItem>
            </MenuList>
          </Menu>
        </HStack>
      </Flex>
    </Box>
  )
}