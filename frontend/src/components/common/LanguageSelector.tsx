'use client'

/**
 * OSMOS Language Selector - Dark Elegance Edition
 */

import { Box, HStack, Text, Icon, Menu, MenuButton, MenuList, MenuItem, Button } from '@chakra-ui/react'
import { ChevronDownIcon } from '@chakra-ui/icons'
import { FiGlobe } from 'react-icons/fi'
import { useLocale } from '@/contexts/LocaleContext'
import { SupportedLocale } from '@/lib/date-utils'

const LANGUAGE_OPTIONS: { value: SupportedLocale; label: string; flag: string }[] = [
  { value: 'fr', label: 'Francais', flag: '🇫🇷' },
  { value: 'en', label: 'English', flag: '🇬🇧' },
  { value: 'es', label: 'Espanol', flag: '🇪🇸' },
  { value: 'de', label: 'Deutsch', flag: '🇩🇪' },
]

interface LanguageSelectorProps {
  showLabel?: boolean
  size?: 'sm' | 'md' | 'lg'
}

export default function LanguageSelector({ showLabel = true, size = 'md' }: LanguageSelectorProps) {
  const { locale, setLocale } = useLocale()

  const currentLang = LANGUAGE_OPTIONS.find(opt => opt.value === locale) || LANGUAGE_OPTIONS[0]

  return (
    <Menu>
      <MenuButton
        as={Button}
        rightIcon={<ChevronDownIcon />}
        size={size}
        variant="ghost"
        bg="bg.tertiary"
        border="1px solid"
        borderColor="border.default"
        color="text.primary"
        _hover={{
          bg: 'bg.hover',
          borderColor: 'border.active',
        }}
        _active={{
          bg: 'bg.hover',
        }}
      >
        <HStack spacing={2}>
          <Icon as={FiGlobe} boxSize={4} color="text.muted" />
          {showLabel && (
            <Text fontSize={size}>{currentLang.flag} {currentLang.label}</Text>
          )}
          {!showLabel && (
            <Text fontSize={size}>{currentLang.flag}</Text>
          )}
        </HStack>
      </MenuButton>
      <MenuList
        bg="bg.secondary"
        border="1px solid"
        borderColor="border.default"
        rounded="xl"
        py={2}
        boxShadow="0 4px 20px rgba(0, 0, 0, 0.3)"
      >
        {LANGUAGE_OPTIONS.map((option) => (
          <MenuItem
            key={option.value}
            onClick={() => setLocale(option.value)}
            bg={locale === option.value ? 'rgba(99, 102, 241, 0.15)' : 'transparent'}
            _hover={{ bg: 'bg.hover' }}
            borderLeft={locale === option.value ? '3px solid' : '3px solid transparent'}
            borderColor="brand.500"
          >
            <HStack spacing={2}>
              <Text>{option.flag}</Text>
              <Text color="text.primary">{option.label}</Text>
            </HStack>
          </MenuItem>
        ))}
      </MenuList>
    </Menu>
  )
}
