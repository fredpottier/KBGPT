'use client'

import { Select, HStack, Text, Icon } from '@chakra-ui/react'
import { FiGlobe } from 'react-icons/fi'
import { useLocale } from '@/contexts/LocaleContext'
import { SupportedLocale } from '@/lib/date-utils'

const LANGUAGE_OPTIONS: { value: SupportedLocale; label: string; flag: string }[] = [
  { value: 'fr', label: 'Français', flag: '🇫🇷' },
  { value: 'en', label: 'English', flag: '🇬🇧' },
  { value: 'es', label: 'Español', flag: '🇪🇸' },
  { value: 'de', label: 'Deutsch', flag: '🇩🇪' },
]

interface LanguageSelectorProps {
  showLabel?: boolean
  size?: 'sm' | 'md' | 'lg'
}

export default function LanguageSelector({ showLabel = true, size = 'md' }: LanguageSelectorProps) {
  const { locale, setLocale } = useLocale()

  return (
    <HStack spacing={2}>
      {showLabel && (
        <>
          <Icon as={FiGlobe} />
          <Text fontSize={size} fontWeight="medium">
            Langue
          </Text>
        </>
      )}
      <Select
        value={locale}
        onChange={(e) => setLocale(e.target.value as SupportedLocale)}
        size={size}
        width="auto"
      >
        {LANGUAGE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.flag} {option.label}
          </option>
        ))}
      </Select>
    </HStack>
  )
}
